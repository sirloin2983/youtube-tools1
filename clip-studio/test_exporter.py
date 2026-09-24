"""書き出しの音量調整(exporter.apply_volume / build_spec の volume 検証)のテスト。
実際に ffmpeg を1回動かして確認する(合成した2秒の無音動画を使う。数秒で終わる)。

    python3 test_exporter.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common
import exporter
import handoff


def _make_clip(path, sec=2.0):
    """テスト用の短い合成動画(映像+無音の音声)を作る。ffmpeg が無ければテストをスキップする。"""
    ff = common.find_tool("ffmpeg")
    if not ff:
        return False
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%.1f" % sec,
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "%.1f" % sec, "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", path]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode == 0 and os.path.isfile(path)


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestApplyVolume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clip = os.path.join(self.tmp, "01_clip.mp4")
        if not _make_clip(self.clip):
            self.skipTest("テスト用動画を作れなかった(ffmpeg のビルドを確認してください)")

    def _job_it(self):
        return {"cancel": False, "proc": None}, {"start": 0.0, "end": 2.0, "progress": 0.0}

    def test_volume_100_is_a_noop(self):
        """既定の100(調整なし)では、ffmpeg を呼び直さずファイルはそのまま(バイト列が変わらない)。"""
        with open(self.clip, "rb") as f:
            before = hashlib.sha1(f.read()).hexdigest()
        job, it = self._job_it()
        exporter.apply_volume(job, {"outDir": self.tmp, "volume": 100}, it, os.path.basename(self.clip))
        with open(self.clip, "rb") as f:
            after = hashlib.sha1(f.read()).hexdigest()
        self.assertEqual(before, after)
        self.assertFalse(os.path.exists(self.clip + ".vol.mp4"))

    def test_volume_75_reencodes_audio_and_keeps_length(self):
        """既定値75では実際に ffmpeg が動き、映像は無劣化(長さが変わらない)のまま音量だけ変わる。"""
        job, it = self._job_it()
        exporter.apply_volume(job, {"outDir": self.tmp, "volume": 75}, it, os.path.basename(self.clip))
        dur, has_v, has_a, _ = common.media_info(self.clip)
        self.assertTrue(has_v)
        self.assertTrue(has_a)
        self.assertAlmostEqual(dur, 2.0, delta=0.3)
        self.assertFalse(os.path.exists(self.clip + ".vol.mp4"))   # 一時ファイルは置き換え後に残らない

    def _fake_store(self):
        clip = self.clip

        class FakeStore:
            def internal(self, vid):
                return {"id": vid, "marks": [{"id": "m1", "start": 1.0, "end": 2.0, "label": ""}], "kind": "file", "path": clip, "title": "t", "fileName": ""}
        return FakeStore()

    def test_volume_out_of_range_rejected_by_build_spec(self):
        """build_spec は 1〜200 の範囲外を bad_request で断る(ffmpeg は呼ばない)。"""
        store = self._fake_store()
        for bad in (0, 201, -5, "abc"):
            with self.assertRaises(common.ApiError):
                exporter.build_spec(store, {"id": "v1", "markIds": ["m1"], "volume": bad})

    def test_volume_missing_defaults_to_75(self):
        spec = exporter.build_spec(self._fake_store(), {"id": "v1", "markIds": ["m1"]})
        self.assertEqual(spec["volume"], exporter.DEFAULT_EXPORT_VOLUME)


class TestExportCompletion(unittest.TestCase):
    def test_callback_receives_the_exported_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = {"videoId": "abcdefghijk", "mode": "file"}
            item = {"id": "m1", "start": 10.0, "end": 15.0, "label": "", "status": "queued"}
            job = {"items": [item], "cancel": False}
            done = Mock(return_value=False)   # マークが変更されていても、出力ファイル自体は成功
            with patch.object(common, "get_out_dir", return_value=tmp), \
                    patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                    patch.object(exporter, "run_ffmpeg", return_value="video/clip.mp4"), \
                    patch.object(exporter, "apply_volume"):
                exporter.run_job(job, spec, done)
            done.assert_called_once_with("abcdefghijk", "m1", "video/clip.mp4", 10.0, 15.0, os.path.join(tmp, "clip.mp4"))   # 最後は書き出した mp4 の絶対パス(マークに残す)
            self.assertEqual((job["state"], item["status"], item["file"]), ("done", "done", "video/clip.mp4"))


def _make_source(path, sec=30, gop=50):
    """キーフレームが5秒ごと(10fps・gop=50)の合成動画(映像+音声)。速度優先(コピー)の開始のずれを確かめるため。"""
    ff = common.find_tool("ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%d" % sec,
           "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % sec, "-c:v", "libx264", "-preset", "veryfast", "-g", str(gop),
           "-keyint_min", str(gop), "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    return subprocess.run(cmd, stdin=subprocess.DEVNULL).returncode == 0 and os.path.isfile(path)


def _job(clips, out_dir):
    return {"id": "j1", "state": "running", "cancel": False, "proc": None, "outDir": out_dir,
            "items": [dict(c, status="queued", progress=0.0, file=None, error=None) for c in clips]}


def _spec(src, clips, fast=False, volume=75):
    return {"videoId": "f0123456789", "title": "テスト 配信", "clips": clips, "fast": fast, "maxHeight": 0, "volume": volume,
            "kind": "file", "sourceTitle": "テスト 配信", "sourceFile": src, "sourceDuration": 30.0, "mode": "file", "sourcePath": src}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestClipManifestExport(unittest.TestCase):
    """書き出した mp4 ごとに .clip.json(youtube-tools-clip/v1)が隣にできること(docs/pipeline.md の 2.1)。"""
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.src = os.path.join(cls.src_dir, "元の配信.mp4")
        if not _make_source(cls.src):
            raise unittest.SkipTest("テスト用動画を作れなかった")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        common.set_home(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self, clips, fast=False, recorded=True):
        spec = _spec(self.src, clips, fast)
        job = _job(clips, common.get_out_dir())
        calls = []

        def on_done(*a):
            calls.append(a)
            return recorded
        exporter.run_job(job, spec, on_done)
        return job, calls

    def test_precise_export_writes_manifest_next_to_each_mp4(self):
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "見どころ", "label": "見どころ", "src": "manual", "markStatus": "adopted"}
        job, calls = self.export([clip])
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"], it.get("warning", "")), ("done", "done", ""))
        self.assertTrue(it["path"].endswith(".mp4") and os.path.isfile(it["path"]))
        self.assertEqual(it["manifest"], os.path.splitext(it["path"])[0] + ".clip.json")
        d = _read(it["manifest"])
        self.assertEqual(d["schema"], "youtube-tools-clip/v1")
        self.assertEqual(d["media"]["path"], it["path"])
        self.assertAlmostEqual(d["media"]["durationSec"], 5.0, delta=0.3)
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})   # 元の配信の秒
        self.assertEqual(d["source"], {"kind": "file", "videoId": "f0123456789", "url": None, "title": "テスト 配信", "path": self.src})
        self.assertEqual(d["mark"], {"id": "m1", "label": "見どころ", "status": "exported", "src": "manual"})
        self.assertEqual(d["export"], {"mode": "precise", "volume": 75})   # 精度優先は actualStart なし(= range.start)
        # 前後10秒の編集用素材にも、その範囲の .clip.json が付く
        e = _read(it["editManifest"])
        self.assertEqual(e["media"]["path"], it["editPath"])
        self.assertTrue(it["editPath"].endswith("_edit.mp4") and os.path.isfile(it["editPath"]))
        self.assertEqual(e["range"], {"start": 0.0, "end": 22.0})
        self.assertEqual((e["export"]["purpose"], e["export"]["selection"]), ("edit-handles", {"start": 7.0, "end": 12.0}))
        # GET /api/export の形
        pub = exporter.job_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["editManifest"]), (it["path"], it["manifest"], it["editPath"], it["editManifest"]))
        self.assertEqual(pub["file"], job["folder"] + "/" + os.path.basename(it["path"]))
        self.assertEqual(len(calls), 1)
        leftovers = [n for n in os.listdir(os.path.dirname(it["path"])) if n.endswith((".part", ".vol.mp4")) or n.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_status_when_mark_changed_during_export(self):
        clip = {"id": "m2", "start": 1.0, "end": 3.0, "title": "x", "label": "", "src": "auto", "markStatus": "adopted"}
        job, _ = self.export([clip], recorded=False)   # 書き出し中にマークを動かした → 書き出し済みにはならない
        d = _read(job["items"][0]["manifest"])
        self.assertEqual((d["mark"]["status"], d["mark"]["src"]), ("adopted", "auto"))

    def test_end_is_clamped_to_source_length(self):
        clip = {"id": "m3", "start": 25.0, "end": 40.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        job, _ = self.export([clip])
        it = job["items"][0]
        self.assertEqual(_read(it["manifest"])["range"], {"start": 25.0, "end": 30.0})
        self.assertEqual(_read(it["editManifest"])["range"], {"start": 15.0, "end": 30.0})

    @unittest.skipUnless(common.find_tool("ffprobe"), "ffprobe が無い環境では actualStart を出さない")
    def test_fast_copy_records_actual_start(self):
        clip = {"id": "m4", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": "adopted"}
        job, _ = self.export([clip], fast=True)
        it = job["items"][0]
        d = _read(it["manifest"])
        self.assertEqual(d["export"]["mode"], "fast")
        # キーフレームは 0,5,10… 秒。7秒からのコピーは 5秒のキーフレームから始まる(B フレームの遅延ぶん少し前)
        self.assertGreater(d["export"]["actualStart"], 4.5)
        self.assertLessEqual(d["export"]["actualStart"], 5.0)
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})
        # 実際の中身の長さも、開始がずれた分だけ長い(= actualStart から range.end まで)
        self.assertAlmostEqual(d["media"]["durationSec"], d["range"]["end"] - d["export"]["actualStart"], delta=0.4)

    def test_fast_without_ffprobe_omits_actual_start(self):
        clip = {"id": "m5", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        real = common.find_tool
        with patch.object(exporter, "find_tool", side_effect=lambda n: None if n == "ffprobe" else real(n)):
            job, _ = self.export([clip], fast=True)
        d = _read(job["items"][0]["manifest"])
        self.assertEqual(d["export"]["mode"], "fast")
        self.assertNotIn("actualStart", d["export"])   # 分からないときは推定値を入れない


class TestManifestFailure(unittest.TestCase):
    def test_manifest_write_failure_is_only_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            common.set_home(tmp)
            item = {"id": "m1", "start": 0.0, "end": 5.0, "label": "", "title": "t", "src": "manual", "markStatus": ""}
            job = _job([item], tmp)
            spec = {"videoId": "abcdefghijk", "mode": "file", "kind": "youtube", "title": "t"}
            denied = PermissionError(13, "denied", os.path.join(tmp, "clip.clip.json"))
            with patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                    patch.object(exporter, "run_ffmpeg", return_value="video/clip.mp4"), \
                    patch.object(exporter, "apply_volume"), patch.object(exporter, "export_edit_media", return_value="video/clip_edit.mp4"), \
                    patch.object(handoff, "write_clip_manifest", side_effect=denied), patch.object(common, "log_failure") as log:
                exporter.run_job(job, spec, Mock(return_value=True))
            it = job["items"][0]
            self.assertEqual((job["state"], it["status"]), ("done", "done"))   # 書き出し自体は成功
            self.assertIn(".clip.json", it["warning"])
            self.assertIn("clip.clip.json", it["warning"])   # どのファイルか分かる
            pub = exporter.job_public(job)["items"][0]
            self.assertEqual((pub["path"], pub["manifest"]), (os.path.join(tmp, "clip.mp4"), None))
            log.assert_called_once()

    def test_paths_are_public_only_when_done(self):
        job = {"id": "j", "state": "error", "items": [{"id": "m", "start": 0, "end": 1, "title": "", "status": "error", "progress": 0, "file": "v/a.mp4",
                                                        "error": "x", "path": "/o/a.mp4", "manifest": "/o/a.clip.json"}]}
        pub = exporter.job_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["editManifest"]), (None, None, None, None))


class TestNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, name):
        with open(os.path.join(self.tmp, name), "w") as f:
            f.write("x")

    def test_unique_base_also_checks_edit_variant(self):
        self.touch("01_a_edit.mp4")   # 前回の編集用素材だけが残っている
        self.assertEqual(exporter.unique_base("01_a", self.tmp), "01_a_2")
        self.touch("01_a_2.clip.json")
        self.assertEqual(exporter.unique_base("01_a", self.tmp), "01_a_3")
        self.assertEqual(exporter.unique_base("01_b", self.tmp), "01_b")

    def test_reserved_names(self):
        for name in ("CON", "con .txt", "Nul.mp4", "COM1", "COM¹", "lpt³.x", "CONIN$", "conout$.log"):
            self.assertTrue(exporter.is_reserved(name), name)
        for name in ("CONSOLE", "COM0", "COM10", "動画", "PRN_2"):
            self.assertFalse(exporter.is_reserved(name), name)
        with patch.object(common, "get_out_dir", return_value=self.tmp):
            folder, _ = exporter.pick_folder({"title": "com²", "videoId": "abcdefghijk"})
        self.assertEqual(folder, "_com²")

    def test_long_output_dir_keeps_paths_short(self):
        root = os.path.join(self.tmp, "d" * max(1, 170 - exporter.path_units(self.tmp)))
        os.makedirs(root)
        title = "とても長い配信タイトル" * 10 + "😀"
        with patch.object(common, "get_out_dir", return_value=root):
            folder, path = exporter.pick_folder({"title": title, "videoId": "abcdefghijk"})
            self.assertLess(len(folder), 60)
            spec = {"videoId": "abcdefghijk", "mode": "file", "folder": folder, "outDir": path}
            item = {"id": "m1", "start": 3600.0, "end": 3660.0, "label": "長いラベル" * 10, "title": "", "src": "manual", "markStatus": ""}
            seen = []

            def runner(job, spec, it, base):
                seen.append(os.path.join(spec["outDir"], base))
                raise exporter.ExportError("止める")
            with patch.object(exporter, "pick_folder", return_value=(folder, path)), patch.object(exporter, "run_ffmpeg", side_effect=runner):
                exporter.run_job(_job([item], root), spec)
        longest = seen[0] + "_edit.clip.json"
        self.assertLessEqual(exporter.path_units(longest), exporter.MAX_PATH_UNITS - exporter.SUFFIX_ROOM + len("_edit.clip.json") + 3)
        self.assertLessEqual(exporter.path_units(seen[0]) + exporter.SUFFIX_ROOM, exporter.MAX_PATH_UNITS)

    def test_trim_units_counts_utf16(self):
        self.assertEqual(exporter.path_units("a😀"), 3)
        self.assertEqual(exporter.trim_units("ab😀", 3), "ab")
        self.assertEqual(exporter.trim_units("ab. c", 4), "ab")


class TestExportLog(unittest.TestCase):
    def test_log_is_rotated_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, "get_out_dir", return_value=tmp), patch.object(exporter, "LOG_MAX", 100):
            exporter.log_export("first " + "x" * 200, ["ffmpeg"], [])
            exporter.log_export("second", ["ffmpeg"], [])
            with open(os.path.join(tmp, "export-log.old.txt"), encoding="utf-8") as f:
                self.assertIn("first", f.read())
            with open(os.path.join(tmp, "export-log.txt"), encoding="utf-8") as f:
                self.assertIn("second", f.read())


class TestBuildSpecIds(unittest.TestCase):
    def test_bad_youtube_id_is_refused_before_building_url(self):
        class S:
            def internal(self, vid):
                return {"id": "-o /tmp/x", "kind": "youtube", "marks": [{"id": "m1", "start": 0, "end": 1, "label": ""}], "title": "", "fileName": "", "path": ""}
        with patch.dict(os.environ, {"STUDIO_FAKE": ""}), patch.object(exporter, "find_tool", return_value="/bin/true"):
            with self.assertRaises(common.ApiError) as cm:
                exporter.build_spec(S(), {"id": "x", "markIds": ["m1"]})
        self.assertIn("動画ID", cm.exception.message)


if __name__ == "__main__":
    unittest.main(verbosity=1)
