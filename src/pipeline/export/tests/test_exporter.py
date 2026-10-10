"""書き出しの音量調整(exporter.apply_volume / build_spec の volume 検証)のテスト。
実際に ffmpeg を1回動かして確認する(合成した2秒の無音動画を使う。数秒で終わる)。

    py -3.10 -m unittest src/pipeline/export/tests/test_exporter.py
"""
import hashlib
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(os.path.dirname(TESTS)))   # tests → export → pipeline → src
HERE = os.path.join(SRC, "studio")   # テストが使うスタジオの殻 common のあるフォルダ(studio/。exporter 自身は common を読まない)
sys.path.insert(0, HERE)
sys.path.insert(0, SRC)
import common
from pipeline.export import exporter, manifest
from ytt import normalize, schemas  # noqa: E402  (途中のファイルの置き場所 WORK_DIR)


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


def _make_source(path, sec=30, gop=300, rate=60, video=None):
    """キーフレームが5秒ごと(60fps・gop=300)の合成動画(映像+音声)。配信の録画によくある 60fps(書き出しで 30fps に作り直される。2026-10-04 Q1)。
    video: 映像の lavfi の指定を差し替える(明るさで時刻が分かる映像など)"""
    ff = common.find_tool("ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", video or "testsrc=size=64x64:rate=%d:duration=%d" % (rate, sec),
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


def _fps(path):
    """r_frame_rate(ffprobe が無ければ None)"""
    i = normalize.probe(path)
    return i and i["r_frame_rate"]


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestClipManifestExport(unittest.TestCase):
    """書き出した mp4 ごとに .clip.json(youtube-tools-clip/v1)が隣にできること(docs/spec/pipeline.md の 2.1)。"""
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
        work = os.path.join(os.path.dirname(it["path"]), schemas.WORK_DIR)   # 途中のファイル(2026-09-27)
        self.assertEqual(it["manifest"], os.path.join(work, os.path.splitext(os.path.basename(it["path"]))[0] + ".clip.json"))
        d = _read(it["manifest"])
        self.assertEqual(d["schema"], "youtube-tools-clip/v1")
        self.assertEqual(d["media"]["path"], it["path"])
        self.assertAlmostEqual(d["media"]["durationSec"], 5.0, delta=0.3)
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})   # 元の配信の秒
        self.assertEqual(d["source"], {"kind": "file", "videoId": "f0123456789", "url": None, "title": "テスト 配信", "path": self.src})
        self.assertEqual(d["mark"], {"id": "m1", "label": "見どころ", "status": "exported", "src": "manual"})
        self.assertEqual(d["export"], {"mode": "precise", "volume": 75})   # 精度優先は actualStart なし(= range.start)
        if common.find_tool("ffprobe"):   # 60fps の元から、切り抜きも編集用素材も 30fps に作り直される(Q1)
            self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))
        # 前後10秒の編集用素材にも、その範囲の .clip.json が付く
        e = _read(it["editManifest"])
        self.assertEqual(e["media"]["path"], it["editPath"])
        self.assertTrue(it["editPath"].endswith("_edit.mp4") and os.path.isfile(it["editPath"]) and os.path.dirname(it["editPath"]) == work)
        self.assertEqual(it["editManifest"], os.path.splitext(it["editPath"])[0] + ".clip.json")      # 編集用素材の .clip.json も 作業用/ に(二重にしない)
        self.assertTrue(os.path.isfile(os.path.join(work, os.path.splitext(os.path.basename(it["path"]))[0] + ".edit.json")))
        self.assertEqual(sorted(n for n in os.listdir(os.path.dirname(it["path"])) if not os.path.isdir(os.path.join(os.path.dirname(it["path"]), n))),
                         [os.path.basename(it["path"])])                                               # 直下は元動画だけ
        self.assertEqual(e["range"], {"start": 0.0, "end": 22.0})
        self.assertEqual((e["export"]["purpose"], e["export"]["selection"]), ("edit-handles", {"start": 7.0, "end": 12.0}))
        # GET /api/export の形
        pub = exporter.job_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["editManifest"]), (it["path"], it["manifest"], it["editPath"], it["editManifest"]))
        self.assertEqual(pub["file"], job["folder"] + "/" + os.path.basename(it["path"]))
        self.assertEqual(len(calls), 1)
        leftovers = [n for d in (os.path.dirname(it["path"]), work) for n in os.listdir(d) if n.endswith((".part", ".vol.mp4")) or n.startswith(".tmp-")]
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

    def test_fast_reencodes_to_30fps_at_exact_position(self):
        """高速 = 速い設定(ultrafast)での作り直し(2026-10-04 Q1。以前のコピーは fps を変えられず、開始もキーフレームへずれた)。
        位置ちょうどなので actualStart は付けない"""
        clip = {"id": "m4", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": "adopted"}
        cmds = []
        real = exporter._pump

        def spy(job, cmd, it, dur, *a, **kw):
            cmds.append(cmd)
            return real(job, cmd, it, dur, *a, **kw)
        with patch.object(exporter, "_pump", side_effect=spy):
            job, _ = self.export([clip], fast=True)
        it = job["items"][0]
        self.assertEqual(it["status"], "done", it.get("error"))
        d = _read(it["manifest"])
        self.assertEqual(d["export"], {"mode": "fast", "volume": 75})
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})
        self.assertAlmostEqual(d["media"]["durationSec"], 5.0, delta=0.2)
        cut = [c for c in cmds if "-preset" in c]
        self.assertTrue(cut and all(c[c.index("-preset") + 1] == "ultrafast" and c[c.index("-crf") + 1] == "18" for c in cut))
        self.assertFalse(any("copy" == c[c.index("-c") + 1] for c in cmds if "-c" in c))   # コピーはもう使わない
        if common.find_tool("ffprobe"):
            self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))

    def test_combine_is_30fps(self):
        clips = [{"id": "a", "start": 2.0, "end": 4.0, "title": "a", "label": "a", "src": "manual", "markStatus": ""},
                 {"id": "b", "start": 10.0, "end": 12.0, "title": "b", "label": "b", "src": "manual", "markStatus": ""}]
        spec = dict(_spec(self.src, clips), combine=True)
        job = dict(_job(clips, common.get_out_dir()), combined=None)
        exporter.run_job(job, spec)
        c = job["combined"]
        self.assertEqual((job["state"], c["status"]), ("done", "done"), c.get("error"))
        self.assertAlmostEqual(common.media_info(c["path"])[0], 4.0, delta=0.3)
        if common.find_tool("ffprobe"):
            self.assertEqual(_fps(c["path"]), "30/1")

    # ---- 書きかけの名前(<base>.partial.mp4)に書いて、仕上がったら置き換える(2026-09-30。設計レビュー studio の 4) ----
    def _files(self, job):
        folder = os.path.join(common.get_out_dir(), job["folder"])
        out = []
        for d in (folder, os.path.join(folder, schemas.WORK_DIR)):
            if os.path.isdir(d):
                out += [n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)) and n != ".studio-id"]
        return sorted(out)

    def test_success_leaves_no_partial_and_sidecar_names_final(self):
        clip = {"id": "m6", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        job, _ = self.export([clip])
        it = job["items"][0]
        self.assertEqual(it["status"], "done")
        self.assertEqual([n for n in self._files(job) if exporter.PARTIAL in n], [])
        self.assertFalse(exporter.is_partial(it["path"]) or exporter.is_partial(it["editPath"]))
        self.assertEqual(it["file"], job["folder"] + "/" + os.path.basename(it["path"]))
        side = os.path.join(os.path.dirname(it["editPath"]), os.path.splitext(os.path.basename(it["path"]))[0] + ".edit.json")
        self.assertEqual(_read(side)["media"], os.path.basename(it["editPath"]))   # .edit.json は本当の名前を指す

    def test_failure_after_cut_leaves_no_file(self):
        """切り出しのあと(ラウドネスの調整など)で失敗しても、完成品の名前のファイル・書きかけ・.edit.json を残さない"""
        clip = {"id": "m7", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        seen = []

        def boom(job, spec, it):
            seen.append((it["path"], it.get("editPath")))
            raise exporter.ExportError("ラウドネス調整 失敗")
        with patch.object(exporter, "apply_loudness", side_effect=boom):
            job, calls = self.export([clip])
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("error", "error"))
        self.assertTrue(exporter.is_partial(seen[0][0]) and exporter.is_partial(seen[0][1]))   # 仕上げの間は書きかけの名前
        self.assertEqual(self._files(job), [])
        self.assertEqual(calls, [])   # 書き出し済みの記録もしない

    def test_cancel_during_edit_media_leaves_no_file(self):
        clip = {"id": "m8", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        real = exporter.apply_volume
        state = {"n": 0}

        def cancel_on_second(job, spec, it, rel):   # 1回目 = 本体、2回目 = 編集用素材 の音量の調整で「中止」
            state["n"] += 1
            if state["n"] == 2:
                job["cancel"] = True
                raise exporter.ExportError("中止しました")
            return real(job, spec, it, rel)
        with patch.object(exporter, "apply_volume", side_effect=cancel_on_second):
            job, _ = self.export([clip])
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertEqual(self._files(job), [])


class TestPartialNames(unittest.TestCase):
    def test_names(self):
        p = os.path.join("d", "01_a.partial.mp4")
        self.assertTrue(exporter.is_partial(p))
        self.assertEqual(exporter.final_path(p), os.path.join("d", "01_a.mp4"))
        self.assertEqual(exporter.final_path(os.path.join("d", "01_a.mp4")), os.path.join("d", "01_a.mp4"))
        self.assertEqual(exporter.final_path("x.partial.webm"), "x.webm")
        self.assertFalse(exporter.is_partial("x.partial.mp4.vol.mp4"))   # 音量の調整の途中は drop_partial が一緒に消す
        self.assertEqual(exporter.partial_path("d", "b"), os.path.join("d", "b.partial.mp4"))

    def test_clean_partials_only_in_studio_folders(self):
        with tempfile.TemporaryDirectory() as root:
            ours, theirs = os.path.join(root, "配信A"), os.path.join(root, "手で作った")
            exporter._write_owner(ours, "abcdefghijk")
            os.makedirs(theirs)
            keep = [os.path.join(ours, "01_a.mp4"), os.path.join(ours, schemas.WORK_DIR, "01_a_edit.mp4"), os.path.join(theirs, "x.partial.mp4")]
            gone = [os.path.join(ours, "02_b.partial.mp4"), os.path.join(ours, schemas.WORK_DIR, "02_b_edit.partial.mp4"),
                    os.path.join(ours, "03_c.partial.f399.mp4.part"), os.path.join(ours, "02_b.partial.mp4.vol.mp4")]
            for f in keep + gone:
                open(f, "wb").close()
            self.assertEqual(exporter.clean_partials(root), len(gone))
            self.assertEqual([f for f in keep if os.path.exists(f)], keep)
            self.assertEqual([f for f in gone if os.path.exists(f)], [])
            with patch.object(exporter, "is_busy", return_value=True):   # 書き出しが始まっていたら消さない
                open(gone[0], "wb").close()
                self.assertEqual(exporter.clean_partials(root), 0)
                self.assertTrue(os.path.exists(gone[0]))


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
                    patch.object(manifest, "write_clip_manifest", side_effect=denied), patch.object(common, "log_failure") as log:
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
        self.touch("01_a_edit.mp4")   # 前回の編集用素材だけが残っている(以前の置き方 = 直下)
        self.assertEqual(exporter.unique_base("01_a", self.tmp), "01_a_2")
        self.touch("01_a_2.clip.json")
        self.assertEqual(exporter.unique_base("01_a", self.tmp), "01_a_3")
        self.assertEqual(exporter.unique_base("01_b", self.tmp), "01_b")
        os.makedirs(os.path.join(self.tmp, schemas.WORK_DIR))
        self.touch(os.path.join(schemas.WORK_DIR, "01_b_edit.mp4"))   # 今の置き方: 途中のファイルは 作業用/
        self.assertEqual(exporter.unique_base("01_b", self.tmp), "01_b_2")

    def test_folder_owner_marker_in_work_dir(self):
        """フォルダの持ち主の印 .studio-id も 作業用/ に(2026-09-27)。以前の置き方(直下)の印も読む・書き換えない"""
        with patch.object(common, "get_out_dir", return_value=self.tmp):
            folder, path = exporter.pick_folder({"title": "配信", "videoId": "abcdefghijk"})
            self.assertEqual(os.listdir(path), [schemas.WORK_DIR])
            with open(os.path.join(path, schemas.WORK_DIR, ".studio-id"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "abcdefghijk")
            self.assertEqual(exporter.pick_folder({"title": "配信", "videoId": "abcdefghijk"})[1], path)          # 同じ動画は同じフォルダ
            self.assertEqual(exporter.pick_folder({"title": "配信", "videoId": "zzzzzzzzzzz"})[0], "配信_2")      # 別の動画は別のフォルダ
            old = os.path.join(self.tmp, "以前")
            os.makedirs(old)
            with open(os.path.join(old, ".studio-id"), "w", encoding="utf-8") as f:
                f.write("yyyyyyyyyyy")
            self.assertEqual(exporter.pick_folder({"title": "以前", "videoId": "yyyyyyyyyyy"})[1], old)           # 以前の印(直下)も読む
            self.assertEqual(exporter.pick_folder({"title": "以前", "videoId": "xxxxxxxxxxx"})[0], "以前_2")
            self.assertEqual(os.listdir(old), [".studio-id"])                                                # 以前の印は動かさない

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
        longest = os.path.join(os.path.dirname(seen[0]), schemas.WORK_DIR, os.path.basename(seen[0]) + "_edit.clip.json")   # 作業用/ の中が一番長い
        self.assertLessEqual(exporter.path_units(longest), exporter.MAX_PATH_UNITS)
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
        with patch.dict(os.environ, {"STUDIO_FAKE": ""}), patch.object(common, "find_tool", return_value="/bin/true"):
            with self.assertRaises(common.ApiError) as cm:
                exporter.build_spec(S(), {"id": "x", "markIds": ["m1"]})
        self.assertIn("配信の ID", cm.exception.message)   # 0.22.3: 配信の意味の「動画」は「配信」(見直し S5)


class TestHeavyJobLimit(unittest.TestCase):
    """書き出しは、他のツールの重い処理と順番を待つ(ytt_core.jobs)。待っている間は waiting、取り消せる"""

    def test_waits_and_cancels(self):
        from ytt_core import jobs
        slots = jobs.HeavySlots(1)
        held = slots.acquire("transcribe")
        job = {"id": "x", "videoId": "abcdefghijk", "state": "running", "cancel": False, "proc": None, "created": 0, "outDir": "",
               "items": [{"id": "m1", "start": 0, "end": 1, "title": "a", "status": "queued", "progress": 0.0, "file": None, "error": None}]}
        with patch.object(exporter.jobs, "SLOTS", slots), patch.object(exporter, "_run_job") as body:
            t = threading.Thread(target=exporter.run_job, args=(job, {}, None))
            t.start()
            for _ in range(100):
                if job.get("waiting"):
                    break
                time.sleep(0.02)
            self.assertTrue(exporter.job_public(job)["waiting"])
            job["cancel"] = True
            t.join(5)
            body.assert_not_called()
            self.assertEqual((job["state"], job["items"][0]["status"], exporter.job_public(job)["waiting"]), ("cancelled", "cancelled", False))
            slots.release(held)
            job2 = dict(job, cancel=False, state="running")
            exporter.run_job(job2, {}, None)
            body.assert_called_once()


@unittest.skipUnless(common.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestLoudness(unittest.TestCase):
    """ラウドネス(聞こえ方の音量)をそろえる書き出し(2026-09-26)。切り抜きと編集用素材に同じ量だけかける"""
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.src = os.path.join(cls.src_dir, "src.mp4")
        if not _make_source(cls.src):   # 440Hz の正弦波(振幅 1/8。約 -21 LUFS)
            raise unittest.SkipTest("テスト用動画を作れなかった")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        common.set_home(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def measure(self, path):
        return exporter.measure_loudness({"cancel": False, "proc": None}, {"start": 0.0, "end": 1.0, "progress": 0.0}, path)

    def test_build_spec_choices(self):
        src = self.src

        class Store:
            def internal(self, vid):
                return {"id": vid, "marks": [{"id": "m1", "start": 1.0, "end": 2.0, "label": ""}], "kind": "file", "path": src, "title": "t", "fileName": ""}
        self.assertIsNone(exporter.build_spec(Store(), {"id": "v1", "markIds": ["m1"]})["loudness"])   # 送らなければ今までどおり音量(%)
        self.assertEqual(exporter.build_spec(Store(), {"id": "v1", "markIds": ["m1"], "loudness": -14})["loudness"], -14.0)
        self.assertIsNone(exporter.build_spec(Store(), {"id": "v1", "markIds": ["m1"], "loudness": 0})["loudness"])
        for bad in (-13, -40, "x", [1]):
            with self.subTest(bad=bad), self.assertRaises(common.ApiError):
                exporter.build_spec(Store(), {"id": "v1", "markIds": ["m1"], "loudness": bad})

    def test_clip_and_edit_media_reach_target_with_same_gain(self):
        clips = [{"id": "m1", "start": 12.0, "end": 18.0, "title": "t", "label": "t", "src": "manual", "markStatus": "adopted"}]
        spec = dict(_spec(self.src, clips), loudness=-14.0)
        job = _job(clips, common.get_out_dir())
        exporter.run_job(job, spec, lambda *a: True)
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        before, _ = self.measure(self.src)
        i_main, tp_main = self.measure(it["path"])
        i_edit, _ = self.measure(it["editPath"])
        self.assertAlmostEqual(i_main, -14.0, delta=1.0)
        self.assertAlmostEqual(i_edit, -14.0, delta=1.0)   # 同じ音なので、同じ量をかければ編集用素材も同じ大きさ
        self.assertLessEqual(tp_main, exporter.TRUE_PEAK_CEIL + 0.5)
        lo = it["loudness"]
        self.assertEqual(lo["target"], -14.0)
        self.assertAlmostEqual(lo["gainDb"], -14.0 - lo["measured"], delta=0.2)
        self.assertAlmostEqual(lo["measured"], before, delta=1.0)
        for m in (it["manifest"], it["editManifest"]):
            ex = _read(m)["export"]
            self.assertEqual(ex["loudness"], lo)
            self.assertNotIn("volume", ex)   # 音量(%)は使っていない
        self.assertEqual(exporter.job_public(job)["items"][0]["loudness"], lo)
        leftovers = [n for n in os.listdir(os.path.dirname(it["path"])) if n.endswith(".vol.mp4")]
        self.assertEqual(leftovers, [])

    def test_gain_is_limited_by_true_peak(self):
        loud = os.path.join(self.tmp, "loud.mp4")
        ff = common.find_tool("ffmpeg")
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=4",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4,volume=7", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                        "-shortest", loud], check=True, stdin=subprocess.DEVNULL)   # ほぼ 0dBFS のピーク
        it = {"start": 0.0, "end": 4.0, "progress": 0.0, "path": loud}
        exporter.apply_loudness({"cancel": False, "proc": None}, {"loudness": -11.0}, it)
        _i, tp = self.measure(loud)
        self.assertLessEqual(tp, exporter.TRUE_PEAK_CEIL + 0.5)   # 目標まで上げると割れるときは、ピークの手前で止める

    def test_silence_is_skipped(self):
        clip = os.path.join(self.tmp, "silent.mp4")
        if not _make_clip(clip):
            self.skipTest("テスト用動画を作れなかった")
        with open(clip, "rb") as f:
            before = hashlib.sha1(f.read()).hexdigest()
        it = {"start": 0.0, "end": 2.0, "progress": 0.0, "path": clip}
        exporter.apply_loudness({"cancel": False, "proc": None}, {"loudness": -14.0}, it)
        self.assertIn("skipped", it["loudness"])
        with open(clip, "rb") as f:
            self.assertEqual(hashlib.sha1(f.read()).hexdigest(), before)   # 無音は触らない

    def test_volume_is_not_applied_when_loudness_is_on(self):
        job = {"cancel": False, "proc": None}
        with patch.object(exporter, "_reencode_audio") as re_:
            exporter.apply_volume(job, {"outDir": self.tmp, "volume": 75, "loudness": -14.0}, {"start": 0, "end": 1}, "x.mp4")
        re_.assert_not_called()


# 偽物の yt-dlp: --download-sections の区間を、手元の動画から本物の yt-dlp と同じ形(入力側の -ss + コピー)で取る。
# 受け取った引数を FAKE_YTDLP_LOG に1行ずつ残す。FAKE_YTDLP_PREROLL=1 なら頼んだより3秒手前から取る(位置が分からない場合)。-g(方法2)は失敗する
FAKE_YTDLP = r'''
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_YTDLP_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
if "-g" in args:
    print("ERROR: fake", file=sys.stderr)
    sys.exit(1)
val = lambda k: args[args.index(k) + 1]
def secs(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
a, b = val("--download-sections").lstrip("*").split("-")
s, e = secs(a), secs(b)
if os.environ.get("FAKE_YTDLP_PREROLL") == "1":
    s = max(0.0, s - 3)
out = val("-o").replace("%(ext)s", "mp4").replace("%%", "%")
print("[download] Destination: " + out, flush=True)
r = subprocess.run([val("--ffmpeg-location"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", "%.3f" % s, "-t", "%.3f" % (e - s),
                    "-i", os.environ["FAKE_YTDLP_SRC"], "-c", "copy", "-f", "mp4", out], stdin=subprocess.DEVNULL)
sys.exit(r.returncode)
'''


def _y_avg(path):
    """最初のコマの明るさの平均(signalstats の YAVG)"""
    r = subprocess.run([common.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", path, "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-frames:v", "1", "-f", "null", "-"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    import re
    m = re.search(r"YAVG=([\d.]+)", r.stdout)
    return float(m.group(1)) if m else None


@unittest.skipUnless(common.find_tool("ffmpeg") and common.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
class TestYoutubeTwoStage(unittest.TestCase):
    """YouTube の区間取得は2段(2026-10-04 Q1): yt-dlp で区間をそのまま取る(前後に余裕・作り直さない)→ ffmpeg の ENC で正確な区間に切って 30fps に"""
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.src = os.path.join(cls.dir, "yt.mp4")
        # 明るさ = 秒 × 8(7 秒のコマは 56)。60fps・キーフレームは5秒ごと
        video = "color=c=gray:size=64x64:rate=60:duration=30,format=yuv420p,geq=lum='min(250,T*8)':cb=128:cr=128"
        if not _make_source(cls.src, video=video):
            raise unittest.SkipTest("テスト用動画を作れなかった")
        cls.fake = os.path.join(cls.dir, "fake_ytdlp.py")
        with open(cls.fake, "w", encoding="utf-8") as f:
            f.write(FAKE_YTDLP)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        common.set_home(self.tmp)
        self.log = os.path.join(self.tmp, "ytdlp-args.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def export(self, clip, fast=False, preroll=False):
        spec = dict(_spec(None, [clip], fast), kind="youtube", videoId="abcdefghijk", sourceFile=None, mode="url")
        spec.pop("sourcePath")
        job = _job([clip], common.get_out_dir())
        env = {"FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_SRC": self.src, "FAKE_YTDLP_PREROLL": "1" if preroll else ""}
        with patch.dict(os.environ, env), patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, self.fake]):
            exporter.run_job(job, spec, lambda *a: True)
        with open(self.log, encoding="utf-8") as f:
            calls = [json.loads(l) for l in f]
        return job, calls

    def test_two_stage_exact_and_30fps(self):
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "t", "label": "", "src": "manual", "markStatus": ""}
        job, calls = self.export(clip)
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        # 1段目: 前後に SECTION_PAD 秒の余裕・作り直さない(--force-keyframes-at-cuts を付けない)。本体と前後10秒の編集用素材の2回
        sections = [c[c.index("--download-sections") + 1] for c in calls]
        self.assertEqual(sections, ["*00:00:05.000-00:00:14.000", "*00:00:00.000-00:00:24.000"])
        self.assertFalse(any("--force-keyframes-at-cuts" in c for c in calls))
        # 2段目: 正確な区間・30fps・crf 18
        self.assertAlmostEqual(common.media_info(it["path"])[0], 5.0, delta=0.2)
        self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))
        self.assertAlmostEqual(_y_avg(it["path"]), 56, delta=3)      # 最初のコマ = 元の 7 秒(余裕の 2 秒ぶんずれていない)
        self.assertAlmostEqual(_y_avg(it["editPath"]), 0, delta=3)   # 編集用素材は 0 秒から
        d = _read(it["manifest"])
        self.assertEqual((d["range"], d["export"]["mode"], d["source"]["kind"]), ({"start": 7.0, "end": 12.0}, "precise", "youtube"))
        # 取った区間(_dl)は残さない
        folder = os.path.dirname(it["path"])
        left = [n for dd in (folder, os.path.join(folder, schemas.WORK_DIR)) for n in os.listdir(dd) if exporter.DL_TAG in n or exporter.PARTIAL in n]
        self.assertEqual(left, [])

    def test_fast_uses_ultrafast(self):
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "t", "label": "", "src": "manual", "markStatus": ""}
        cmds = []
        real = exporter._pump

        def spy(job, cmd, it, dur, *a, **kw):
            cmds.append(cmd)
            return real(job, cmd, it, dur, *a, **kw)
        with patch.object(exporter, "_pump", side_effect=spy):
            job, _ = self.export(clip, fast=True)
        it = job["items"][0]
        self.assertEqual(it["status"], "done", it.get("error"))
        cut = [c for c in cmds if "-preset" in c]
        self.assertEqual([c[c.index("-preset") + 1] for c in cut], ["ultrafast", "ultrafast"])
        self.assertEqual(_read(it["manifest"])["export"]["mode"], "fast")
        self.assertAlmostEqual(_y_avg(it["path"]), 56, delta=3)

    def test_unknown_start_falls_back_and_cleans_up(self):
        """取ったファイルが頼んだより長い(手前のキーフレームから見えている)ときは、位置が分からないので方法2(直接指定)へ回す"""
        clip = {"id": "m1", "start": 9.5, "end": 12.0, "title": "t", "label": "", "src": "manual", "markStatus": ""}
        job, calls = self.export(clip, preroll=True)
        it = job["items"][0]
        self.assertEqual(it["status"], "error")
        self.assertIn("開始の位置", it["error"])
        self.assertIn("-g", calls[-1])   # 方法2 を試した
        folder = os.path.join(common.get_out_dir(), job["folder"])
        left = [n for dd in (folder, os.path.join(folder, schemas.WORK_DIR)) if os.path.isdir(dd) for n in os.listdir(dd)
                if os.path.isfile(os.path.join(dd, n)) and n != ".studio-id"]
        self.assertEqual(left, [])


@unittest.skipUnless(common.find_tool("ffmpeg") and common.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
class TestLiveSection(unittest.TestCase):
    """POST /api/live/section の中身(線 D の P4): YouTube の videoId の区間を、今の YouTube の書き出しと同じ中身で、ちょうど指定の path へ。
    マーク・.clip.json・編集用素材は作らない"""
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.src = os.path.join(cls.dir, "yt.mp4")
        video = "color=c=gray:size=64x64:rate=60:duration=30,format=yuv420p,geq=lum='min(250,T*8)':cb=128:cr=128"
        if not _make_source(cls.src, video=video):
            raise unittest.SkipTest("テスト用動画を作れなかった")
        cls.fake = os.path.join(cls.dir, "fake_ytdlp.py")
        with open(cls.fake, "w", encoding="utf-8") as f:
            f.write(FAKE_YTDLP)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        common.set_home(self.tmp)
        self.folder = os.path.join(common.get_out_dir(), "配信フォルダ")
        os.makedirs(self.folder)
        self.final = os.path.join(self.folder, "01_速報版を作り直す.mp4")
        self.log = os.path.join(self.tmp, "ytdlp-args.jsonl")
        real = common.find_tool
        self.patches = [patch.dict(os.environ, {"STUDIO_FAKE": "0", "FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_SRC": self.src, "FAKE_YTDLP_PREROLL": ""}),
                        patch.object(common, "find_tool", lambda n: "yt-dlp" if n == "yt-dlp" else real(n)),   # 本物の yt-dlp が無くても組み立てられる
                        patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, self.fake])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, **kw):
        return dict({"videoId": "abcdefghijk", "start": 7, "end": 12, "path": self.final}, **kw)

    def run_section(self, **kw):
        job = exporter.start_job(exporter.build_section_spec(self.req(**kw)))
        for _ in range(600):
            if job["state"] != "running":
                break
            time.sleep(0.1)
        return job

    def tree(self):
        return sorted(os.path.relpath(os.path.join(d, n), self.folder) for d, _ds, ns in os.walk(self.folder) for n in ns)

    def test_exact_path_30fps_and_nothing_else(self):
        job = self.run_section()
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        pub = exporter.job_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["status"]), (self.final, None, None, "done"))
        self.assertEqual(pub["file"], "配信フォルダ/" + os.path.basename(self.final))
        self.assertAlmostEqual(common.media_info(self.final)[0], 5.0, delta=0.2)
        self.assertEqual(_fps(self.final), "30/1")
        self.assertAlmostEqual(_y_avg(self.final), 56, delta=3)   # 最初のコマ = 元の 7 秒
        with open(self.log, encoding="utf-8") as f:
            calls = [json.loads(l) for l in f]
        self.assertEqual([c[c.index("--download-sections") + 1] for c in calls], ["*00:00:05.000-00:00:14.000"])   # 今の書き出しと同じ区間取得(前後 2 秒)
        # 仕上がりの mp4 だけ(.clip.json・編集用素材・書きかけ・取った区間・.studio-id は作らない)
        self.assertEqual(self.tree(), [os.path.basename(self.final)])
        self.assertEqual(os.listdir(os.path.join(self.folder, schemas.WORK_DIR)), [])

    def test_volume_and_loudness_options_are_used(self):
        self.assertEqual(exporter.build_section_spec(self.req())["volume"], exporter.DEFAULT_EXPORT_VOLUME)
        spec = exporter.build_section_spec(self.req(volume=100, loudness=-14, maxHeight=720, precision="fast"))
        self.assertEqual((spec["volume"], spec["loudness"], spec["maxHeight"], spec["fast"], spec["mode"]), (100, -14.0, 720, True, "url"))
        job = self.run_section(loudness=-14)
        self.assertEqual(job["items"][0]["status"], "done", job["items"][0].get("error"))
        self.assertAlmostEqual(job["items"][0]["loudness"]["target"], -14.0)

    def test_failure_leaves_nothing(self):
        with patch.dict(os.environ, {"FAKE_YTDLP_PREROLL": "1"}):   # 取った区間の開始の位置が分からない → 方法2(失敗)
            job = self.run_section(start=9.5, end=12)
        self.assertEqual((job["state"], job["items"][0]["status"]), ("error", "error"))
        self.assertFalse(os.path.exists(self.final))
        self.assertEqual(self.tree(), [])

    def test_does_not_overwrite_a_file_that_appeared(self):
        def appear(*a, **kw):
            with open(self.final, "wb") as f:
                f.write(b"mine")
        with patch.object(exporter, "apply_loudness", side_effect=appear):
            job = self.run_section()
        self.assertEqual(job["items"][0]["status"], "error")
        with open(self.final, "rb") as f:
            self.assertEqual(f.read(), b"mine")
        self.assertEqual(self.tree(), [os.path.basename(self.final)])   # 書きかけは消える

    def test_cancel(self):
        def slow(job, *a, **kw):
            for _ in range(200):
                if job["cancel"]:
                    raise exporter.ExportError("中止しました")
                time.sleep(0.05)
        with patch.object(exporter, "run_ytdlp", side_effect=slow):
            job = exporter.start_job(exporter.build_section_spec(self.req()))
            with self.assertRaises(common.ApiError) as c:   # 今の書き出しと同じ: 実行中は別のジョブを始められない(409)
                exporter.start_job(exporter.build_section_spec(self.req(path=os.path.join(self.folder, "b.mp4"))))
            self.assertEqual((c.exception.status, c.exception.code), (409, "busy"))
            exporter.cancel(job["id"])
            for _ in range(100):
                if job["state"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertFalse(os.path.exists(self.final))

    def test_fake_mode_uses_fake_media(self):
        with patch.dict(os.environ, {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": self.src}):
            spec = exporter.build_section_spec(self.req())
            self.assertEqual((spec["mode"], spec["sourcePath"]), ("file", self.src))
            job = self.run_section()
        self.assertEqual(job["items"][0]["status"], "done", job["items"][0].get("error"))
        self.assertEqual(_fps(self.final), "30/1")
        with patch.dict(os.environ, {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": ""}), self.assertRaises(common.ApiError) as c:
            exporter.build_section_spec(self.req(path=os.path.join(self.folder, "c.mp4")))
        self.assertEqual(c.exception.status, 500)

    def test_bad_requests(self):
        out = common.get_out_dir()
        os.makedirs(os.path.join(out, "x"), exist_ok=True)
        with open(os.path.join(self.folder, "exists.mp4"), "wb") as f:
            f.write(b"x")
        bads = [dict(videoId="short"), dict(videoId="abcdefghijk\n"), dict(videoId="あいうえおかきくけこさ"), dict(videoId=None), dict(videoId=12345678901), dict(videoId="abcdefghij/"),
                dict(start=-1), dict(start=12), dict(start=13), dict(end=7), dict(start="7"), dict(start=None), dict(start=True), dict(end=float("nan")), dict(end=float("inf")),
                dict(start=0, end=3601), dict(end=None), dict(start=10 ** 400), dict(end=10 ** 400),   # float にできない巨大な整数(以前は OverflowError)
                dict(path=None), dict(path=""), dict(path="rel.mp4"), dict(path=os.path.join(self.folder, "a.mkv")), dict(path=os.path.join(self.folder, "a")),
                dict(path=os.path.join(self.folder, "a%b.mp4")), dict(path=os.path.join(self.folder, "a.partial.mp4")), dict(path=os.path.join(self.folder, "CON.mp4")),
                dict(path=os.path.join(self.dir, "outside.mp4")), dict(path=os.path.join(out, "..", "outside.mp4")), dict(path=os.path.join(self.folder, "..", "..", "o.mp4")),
                dict(path=os.path.join(out, "nodir", "a.mp4")), dict(path=os.path.join(self.folder, "exists.mp4")), dict(path=os.path.join(self.folder, "a" * 300 + ".mp4")),
                dict(path=os.path.join(out, "x")), dict(path="a\x00.mp4"),
                dict(volume=0), dict(volume=201), dict(volume="abc"), dict(loudness=-13), dict(loudness="x"), dict(precision="turbo")]
        for kw in bads:
            with self.subTest(kw=kw), self.assertRaises(common.ApiError) as c:
                exporter.build_section_spec(self.req(**kw))
            self.assertEqual((c.exception.status, c.exception.code), (400, "bad_request"), kw)
        # 正しい形は通る(マークも配信の登録も要らない)・path の親が書き出し先そのもの(直下)でもよい
        self.assertEqual(exporter.build_section_spec(self.req(path=os.path.join(out, "direct.mp4")))["outDir"], out)
        self.assertEqual(exporter.build_section_spec(self.req(start=0, end=3600, loudness=0, maxHeight=None, volume=None))["clips"][0]["end"], 3600.0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
