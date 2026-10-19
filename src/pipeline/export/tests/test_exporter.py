"""書き出しの音量調整(切り出しの作り直しに入る音量 / build_spec の volume 検証)のテスト。
実際に ffmpeg を1回動かして確認する(合成した2秒の無音動画を使う。数秒で終わる)。

    py -3.12 -m unittest src/pipeline/export/tests/test_exporter.py
"""
import hashlib
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
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
import startup  # noqa: E402  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
from ytt import testkit  # noqa: E402
from ytt import errors, jobs, mediainfo, studio_env  # noqa: E402
from pipeline.export import exporter
from flow import export as _fexport  # noqa: E402  (指定は ② の build_spec = 台帳から引く口。① の spec_from_video は配信の dict を受けるだけ)
from ytt import names, normalize, schemas  # noqa: E402  (途中のファイルの置き場所 WORK_DIR)


def _make_clip(path, sec=2.0):
    """テスト用の短い合成動画(映像+無音の音声)を作る。ffmpeg が無ければテストをスキップする。"""
    ff = studio_env.find_tool("ffmpeg")
    if not ff:
        return False
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%.1f" % sec,
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "%.1f" % sec, "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", path]
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode == 0 and os.path.isfile(path)


@unittest.skipUnless(studio_env.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestApplyVolume(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.clip = os.path.join(self.tmp, "01_clip.mp4")
        if not _make_clip(self.clip):
            self.skipTest("テスト用動画を作れなかった(ffmpeg のビルドを確認してください)")

    def _job_it(self):
        return jobs.Ctl(), {"start": 0.0, "end": 2.0, "progress": 0.0}

    def test_volume_is_in_the_first_encode(self):
        """O3: 音量(%)は切り出しの作り直しの -af に入る(後から音声だけ作り直さない)。100 は付けない"""
        self.assertNotIn("-af", exporter._enc({"volume": 100}))
        self.assertNotIn("-af", exporter._enc({}))
        for fast in (False, True):
            enc = exporter._enc({"volume": 75, "fast": fast})
            self.assertEqual(enc[enc.index("-af") + 1], "volume=0.750")
            self.assertEqual(enc[:-2], exporter.ENC_FAST if fast else exporter.ENC)

    def test_volume_changes_decoded_level_and_keeps_length(self):
        """本物の ffmpeg で音を測る唯一の確かめ: 切り出し 1 回(50%)で、デコードした音量が元から約 -6dB 下がり、長さは変わらない"""
        src = os.path.join(self.tmp, "sine.mp4")
        ff = studio_env.find_tool("ffmpeg")
        subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=30:duration=4",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                        "-shortest", src], check=True, stdin=subprocess.DEVNULL)

        def level(path):
            r = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
            return float(r.stdout.split("mean_volume:")[1].split("dB")[0])
        spec = {"outDir": self.tmp, "folder": "f", "sourcePath": src, "volume": 50}
        it = {"start": 1.0, "end": 3.0, "progress": 0.0}
        path = os.path.join(self.tmp, os.path.basename(exporter.run_ffmpeg(jobs.Ctl(), spec, it, "v50")))
        self.assertAlmostEqual(mediainfo.media_info(path)[0], 2.0, delta=0.2)
        self.assertAlmostEqual(level(path) - level(src), -6.02, delta=0.5)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.endswith(".vol.mp4")], [])

    def _fake_store(self):
        clip = self.clip

        class FakeStore:
            def internal(self, vid):
                return {"id": vid, "marks": [{"id": "m1", "start": 1.0, "end": 2.0, "label": ""}], "kind": "file", "path": clip, "title": "t", "fileName": ""}
        return FakeStore()

    def test_volume_out_of_range_rejected_by_build_spec(self):
        """build_spec(② の口)は 1〜200 の範囲外を bad_request で断る(ffmpeg は呼ばない)。"""
        store = self._fake_store()
        for bad in (0, 201, -5, "abc"):
            with self.assertRaises(errors.ApiError):
                _fexport.build_spec(store, {"id": "v1", "markIds": ["m1"], "volume": bad})

    def test_margin_is_checked_and_kept_out_of_combine(self):
        self.assertEqual(_fexport.build_spec(self._fake_store(), {"id": "v1", "markIds": ["m1"], "margin": 10}).get("margin"), 10.0)
        self.assertNotIn("margin", _fexport.build_spec(self._fake_store(), {"id": "v1", "markIds": ["m1"]}))
        with self.assertRaises(errors.ApiError):
            _fexport.build_spec(self._fake_store(), {"id": "v1", "markIds": ["m1"], "margin": 99})

    def test_volume_missing_defaults_to_75(self):
        spec = _fexport.build_spec(self._fake_store(), {"id": "v1", "markIds": ["m1"]})
        self.assertEqual(spec["volume"], exporter.DEFAULT_EXPORT_VOLUME)


class TestClipNumbering(unittest.TestCase):
    def test_numbers_continue_from_existing_clips(self):
        """同じ配信のフォルダに書き出しがあれば、開き直した 2 回目の書き出しは続きの番号から(01 から振り直さない)"""
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("01_00h00m10s-00h00m15s_a.mp4", "02_00h01m00s-00h01m05s.partial.mp4", "メモ.txt"):
                open(os.path.join(tmp, n), "w").close()
            items = [{"id": "m%d" % i, "start": 10.0 * i, "end": 10.0 * i + 5, "label": "", "status": "queued"} for i in (1, 2)]
            job = {"items": items, "state": "running"}
            seen = []
            with patch.object(studio_env, "get_out_dir", return_value=tmp), patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                    patch.object(exporter, "_export_clip", side_effect=lambda ctl, spec, it, idx, on_done: seen.append(idx) or it.update(status="done")):
                _run(job, {"videoId": "abcdefghijk", "mode": "file"})
            self.assertEqual(seen, [3, 4])
            self.assertEqual(names.next_clip_number(os.path.join(tmp, "無い")), 1)


def _make_source(path, sec=30, gop=300, rate=60, video=None):
    """キーフレームが5秒ごと(60fps・gop=300)の合成動画(映像+音声)。配信の録画によくある 60fps(書き出しで 30fps に作り直される)。
    video: 映像の lavfi の指定を差し替える(明るさで時刻が分かる映像など)"""
    ff = studio_env.find_tool("ffmpeg")
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", video or "testsrc=size=64x64:rate=%d:duration=%d" % (rate, sec),
           "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % sec, "-c:v", "libx264", "-preset", "veryfast", "-g", str(gop),
           "-keyint_min", str(gop), "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    return subprocess.run(cmd, stdin=subprocess.DEVNULL).returncode == 0 and os.path.isfile(path)


def _job(clips, out_dir):
    """① の結果の辞書(exporter.new_result と同じ形)。out_dir は今の呼び手との互換で受けるだけ"""
    return exporter.new_result({"videoId": "j1", "clips": clips})


def _run(res, spec, on_done=None, ctl=None):
    """① の run を同じ糸で動かす(器 = ② の flow/export は通さない)"""
    exporter.run(spec, res, ctl or jobs.Ctl(), on_done)
    return res


def _spec(src, clips, fast=False, volume=75):
    return {"videoId": "f0123456789", "title": "テスト 配信", "clips": clips, "fast": fast, "maxHeight": 0, "volume": volume,
            "kind": "file", "sourceTitle": "テスト 配信", "sourceFile": src, "sourceDuration": 30.0, "mode": "file", "sourcePath": src}


def _fps(path):
    """r_frame_rate(ffprobe が無ければ None)"""
    i = normalize.probe(path)
    return i and i["r_frame_rate"]


@unittest.skipUnless(studio_env.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestClipManifestExport(unittest.TestCase):
    """書き出した mp4 ごとに .clip.json(youtube-tools-clip/v1)が隣にできること(notes:docs/spec/pipeline.md の 2.1)。"""
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
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)

    def export(self, clips, fast=False, recorded=True):
        spec = _spec(self.src, clips, fast)
        job = _job(clips, studio_env.get_out_dir())
        calls = []

        def on_done(*a):
            calls.append(a)
            return recorded
        _run(job, spec, on_done)
        return job, calls

    def test_precise_export_writes_manifest_next_to_each_mp4(self):
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "見どころ", "label": "見どころ", "src": "manual", "markStatus": "adopted"}
        job, calls = self.export([clip])
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"], it.get("warning", "")), ("done", "done", ""))
        self.assertTrue(it["path"].endswith(".mp4") and os.path.isfile(it["path"]))
        # 完了の呼び返し: (配信 ID・マーク ID・出力の相対名・始め・終わり・書き出した mp4 の絶対パス = マークに残す)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0][:2], ("f0123456789", "m1"))
        self.assertEqual(calls[0][2], it["file"])   # 出力の相対名(画面へ返す物と同じ)
        self.assertEqual(calls[0][3:], (7.0, 12.0, it["path"]))
        work = os.path.join(os.path.dirname(it["path"]), schemas.WORK_DIR)   # 途中のファイル
        self.assertEqual(it["manifest"], os.path.join(work, os.path.splitext(os.path.basename(it["path"]))[0] + ".clip.json"))
        d = testkit.read_json(it["manifest"])
        self.assertEqual(d["schema"], "youtube-tools-clip/v1")
        self.assertEqual(d["media"]["path"], it["path"])
        self.assertAlmostEqual(d["media"]["durationSec"], 5.0, delta=0.3)
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})   # 元の配信の秒
        self.assertEqual(d["source"], {"kind": "file", "videoId": "f0123456789", "url": None, "title": "テスト 配信", "path": self.src})
        self.assertEqual(d["mark"], {"id": "m1", "label": "見どころ", "status": "exported", "src": "manual"})
        self.assertEqual(d["export"], {"mode": "precise", "volume": 75})   # 精度優先は actualStart なし(= range.start)
        if studio_env.find_tool("ffprobe"):   # 60fps の元から、切り抜きも編集用素材も 30fps に作り直される(Q1)
            self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))
        # 前後10秒の編集用素材にも、その範囲の .clip.json が付く
        e = testkit.read_json(it["editManifest"])
        self.assertEqual(e["media"]["path"], it["editPath"])
        self.assertTrue(it["editPath"].endswith("_edit.mp4") and os.path.isfile(it["editPath"]) and os.path.dirname(it["editPath"]) == work)
        self.assertEqual(it["editManifest"], os.path.splitext(it["editPath"])[0] + ".clip.json")      # 編集用素材の .clip.json も 作業用/ に(二重にしない)
        self.assertTrue(os.path.isfile(os.path.join(work, os.path.splitext(os.path.basename(it["path"]))[0] + ".edit.json")))
        self.assertEqual(sorted(n for n in os.listdir(os.path.dirname(it["path"])) if not os.path.isdir(os.path.join(os.path.dirname(it["path"]), n))),
                         [os.path.basename(it["path"])])                                               # 直下は元動画だけ
        self.assertEqual(e["range"], {"start": 0.0, "end": 22.0})
        self.assertEqual((e["export"]["purpose"], e["export"]["selection"]), ("edit-handles", {"start": 7.0, "end": 12.0}))
        # GET /api/export の形
        pub = exporter.result_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["editManifest"]), (it["path"], it["manifest"], it["editPath"], it["editManifest"]))
        self.assertEqual(pub["file"], job["folder"] + "/" + os.path.basename(it["path"]))
        self.assertEqual(len(calls), 1)
        leftovers = [n for d in (os.path.dirname(it["path"]), work) for n in os.listdir(d) if n.endswith((".part", ".vol.mp4")) or n.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_margin_pads_clip_and_marks_actual_start(self):
        # LD-2f: 余白 3 秒。動画は 4〜15 秒(前は 0 秒の手前で止まらない範囲・後は元の長さの中)・range はマークのまま・actualStart と margin が印
        clip = {"id": "m4", "start": 7.0, "end": 12.0, "title": "x", "label": "", "src": "auto", "markStatus": "adopted"}
        spec = dict(_spec(self.src, [clip]), margin=3.0)
        job, calls = _job([clip], studio_env.get_out_dir()), []
        _run(job, spec, lambda *a, **k: calls.append((a, k)) or True)
        it = job["items"][0]
        self.assertEqual((it["status"], it["start"], it["end"]), ("done", 7.0, 12.0))   # 画面へ返す区間はマークのまま
        d = testkit.read_json(it["manifest"])
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})
        self.assertAlmostEqual(d["media"]["durationSec"], 11.0, delta=0.3)
        self.assertEqual(d["export"]["actualStart"], 4.0)
        self.assertEqual(d["export"]["margin"]["before"], 3.0)
        self.assertAlmostEqual(d["export"]["margin"]["after"], 3.0, delta=0.3)
        self.assertEqual(schemas.clip_offset(d), 4.0)
        self.assertEqual(schemas.clip_mark_span(d), (3.0, 8.0))
        (args, kw), = calls
        self.assertEqual(args[3:5], (7.0, 12.0))
        self.assertEqual(kw["clip"][0], 4.0)
        self.assertAlmostEqual(kw["clip"][1], 15.0, delta=0.3)
        self.assertEqual(testkit.read_json(it["editManifest"])["range"]["start"], 0.0)   # 編集用素材 = 余白つきの動画の前後 10 秒

    def test_status_when_mark_changed_during_export(self):
        clip = {"id": "m2", "start": 1.0, "end": 3.0, "title": "x", "label": "", "src": "auto", "markStatus": "adopted"}
        job, _ = self.export([clip], recorded=False)   # 書き出し中にマークを動かした → 書き出し済みにはならない
        d = testkit.read_json(job["items"][0]["manifest"])
        self.assertEqual((d["mark"]["status"], d["mark"]["src"]), ("adopted", "auto"))

    def test_end_is_clamped_to_source_length(self):
        clip = {"id": "m3", "start": 25.0, "end": 40.0, "title": "x", "label": "", "src": "manual", "markStatus": ""}
        job, _ = self.export([clip])
        it = job["items"][0]
        self.assertEqual(testkit.read_json(it["manifest"])["range"], {"start": 25.0, "end": 30.0})
        self.assertEqual(testkit.read_json(it["editManifest"])["range"], {"start": 15.0, "end": 30.0})

    def test_fast_reencodes_to_30fps_at_exact_position(self):
        """高速 = 速い設定(ultrafast)での作り直し(コピーでは fps を変えられず、開始もキーフレームへずれるため)。
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
        d = testkit.read_json(it["manifest"])
        self.assertEqual(d["export"], {"mode": "fast", "volume": 75})
        self.assertEqual(d["range"], {"start": 7.0, "end": 12.0})
        self.assertAlmostEqual(d["media"]["durationSec"], 5.0, delta=0.2)
        cut = [c for c in cmds if "-preset" in c]
        self.assertTrue(cut and all(c[c.index("-preset") + 1] == "ultrafast" and c[c.index("-crf") + 1] == "18" for c in cut))
        self.assertFalse(any("copy" == c[c.index("-c") + 1] for c in cmds if "-c" in c))   # コピーはもう使わない
        if studio_env.find_tool("ffprobe"):
            self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))

    def test_combine_is_30fps(self):
        clips = [{"id": "a", "start": 2.0, "end": 4.0, "title": "a", "label": "a", "src": "manual", "markStatus": ""},
                 {"id": "b", "start": 10.0, "end": 12.0, "title": "b", "label": "b", "src": "manual", "markStatus": ""}]
        spec = dict(_spec(self.src, clips), combine=True)
        job = _job(clips, studio_env.get_out_dir())
        _run(job, spec)
        c = job["combined"]
        self.assertEqual((job["state"], c["status"]), ("done", "done"), c.get("error"))
        self.assertAlmostEqual(mediainfo.media_info(c["path"])[0], 4.0, delta=0.3)
        if studio_env.find_tool("ffprobe"):
            self.assertEqual(_fps(c["path"]), "30/1")

    def test_combine_failure_leaves_no_piece(self):
        """M2: つなぐ書き出しが部品の 2 本目・つなぐ段のどちらで失敗しても、切り出した部品と書きかけを残さない"""
        clips = [{"id": "a", "start": 2.0, "end": 4.0, "title": "a", "label": "a", "src": "manual", "markStatus": ""},
                 {"id": "b", "start": 10.0, "end": 12.0, "title": "b", "label": "b", "src": "manual", "markStatus": ""}]
        real = exporter.run_ffmpeg
        n = [0]

        def second_fails(ctl, spec, it, base):
            n[0] += 1
            if n[0] == 2:
                raise exporter.ExportError("2 本目の切り出し 失敗")
            return real(ctl, spec, it, base)
        for name, patcher in (("piece", patch.object(exporter, "run_ffmpeg", side_effect=second_fails)),
                              ("concat", patch.object(exporter, "concat_pieces", side_effect=exporter.ExportError("つなぐ 失敗")))):
            with self.subTest(name=name):
                n[0] = 0
                job = _job(clips, studio_env.get_out_dir())
                with patcher:
                    _run(job, dict(_spec(self.src, clips), combine=True))
                self.assertEqual((job["state"], job["combined"]["status"]), ("error", "error"))
                self.assertEqual(self._files(job), [])

    # ---- 書きかけの名前(<base>.partial.mp4)に書いて、仕上がったら置き換える----
    def _files(self, job):
        folder = os.path.join(studio_env.get_out_dir(), job["folder"])
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
        self.assertEqual(testkit.read_json(side)["media"], os.path.basename(it["editPath"]))   # .edit.json は本当の名前を指す

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
        real = exporter.run_ffmpeg
        state = {"n": 0}

        def cancel_on_second(job, spec, it, base):   # 1回目 = 本体、2回目 = 編集用素材 の切り出しで「中止」
            state["n"] += 1
            if state["n"] == 2:
                job.cancel()   # job = ① に渡る Ctl
                raise exporter.ExportError("中止しました")
            return real(job, spec, it, base)
        with patch.object(exporter, "run_ffmpeg", side_effect=cancel_on_second):
            job, _ = self.export([clip])
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertEqual(self._files(job), [])


class TestLegacyFfmpeg(unittest.TestCase):
    def test_old_ffmpeg_retries_once_with_vsync(self):
        """ffmpeg 5.1 より古い(-fps_mode を知らない)ときは -vsync に替えて 1 回だけやり直す。中止ではやり直さない(ほかの失敗の判定は ytt 側)"""
        old = (1, ["Unrecognized option 'fps_mode'.", "Error splitting the argument list: Option not found"], None)
        cmd = ["ffmpeg", "-i", "a.mp4"] + exporter.ENC + ["out.mp4"]
        calls = []

        def fake(results):
            def once(job, c, it, dur, span):
                calls.append(c)
                return results.pop(0)
            return once
        job, it = jobs.Ctl(), {}
        with patch.object(exporter, "_pump_once", fake([old, (0, ["ok"], None)])):
            self.assertEqual(exporter._pump(job, cmd, it, 2.0), ["ok"])
        self.assertEqual((len(calls), "-vsync" in calls[1], "-fps_mode" in calls[1]), (2, True, False))
        calls.clear()
        with patch.object(exporter, "_pump_once", fake([(1, list(old[1]), "cancel")])), self.assertRaises(exporter.ExportError) as cm:
            stop = jobs.Ctl()
            stop.cancel()
            exporter._pump(stop, cmd, it, 2.0)
        self.assertEqual((len(calls), str(cm.exception)), (1, "中止しました"))

class TestPartialNames(unittest.TestCase):
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
            # 書き出しが始まっていたら消さない(busy = 器 flow/export の is_busy を呼び手が渡す)
            open(gone[0], "wb").close()
            self.assertEqual(exporter.clean_partials(root, busy=lambda: True), 0)
            self.assertTrue(os.path.exists(gone[0]))


class TestManifestFailure(unittest.TestCase):
    def test_manifest_write_failure_is_only_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            studio_env.set_home(tmp)
            item = {"id": "m1", "start": 0.0, "end": 5.0, "label": "", "title": "t", "src": "manual", "markStatus": ""}
            job = _job([item], tmp)
            spec = {"videoId": "abcdefghijk", "mode": "file", "kind": "youtube", "title": "t"}
            denied = PermissionError(13, "denied", os.path.join(tmp, "clip.clip.json"))
            with patch.object(exporter, "pick_folder", return_value=("video", tmp)), \
                    patch.object(exporter, "run_ffmpeg", return_value="video/clip.mp4"), \
                    patch.object(exporter, "export_edit_media", return_value="video/clip_edit.mp4"), \
                    patch.object(exporter, "write_clip", side_effect=denied), patch.object(studio_env, "log_failure") as log:
                _run(job, spec, Mock(return_value=True))
            it = job["items"][0]
            self.assertEqual((job["state"], it["status"]), ("done", "done"))   # 書き出し自体は成功
            self.assertIn(".clip.json", it["warning"])
            self.assertIn("clip.clip.json", it["warning"])   # どのファイルか分かる
            pub = exporter.result_public(job)["items"][0]
            self.assertEqual((pub["path"], pub["manifest"]), (os.path.join(tmp, "clip.mp4"), None))
            log.assert_called_once()

    def test_paths_are_public_only_when_done(self):
        job = {"id": "j", "state": "error", "items": [{"id": "m", "start": 0, "end": 1, "title": "", "status": "error", "progress": 0, "file": "v/a.mp4",
                                                        "error": "x", "path": "/o/a.mp4", "manifest": "/o/a.clip.json"}]}
        pub = exporter.result_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["editManifest"]), (None, None, None, None))


class TestNames(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)

    def test_long_output_dir_keeps_paths_short(self):
        root = os.path.join(self.tmp, "d" * max(1, 170 - exporter.path_units(self.tmp)))
        os.makedirs(root)
        title = "とても長い配信タイトル" * 10 + "😀"
        with patch.object(studio_env, "get_out_dir", return_value=root):
            folder, path = exporter.pick_folder({"title": title, "videoId": "abcdefghijk"})
            self.assertLess(len(folder), 60)
            spec = {"videoId": "abcdefghijk", "mode": "file", "folder": folder, "outDir": path}
            item = {"id": "m1", "start": 3600.0, "end": 3660.0, "label": "長いラベル" * 10, "title": "", "src": "manual", "markStatus": ""}
            seen = []

            def runner(job, spec, it, base):
                seen.append(os.path.join(spec["outDir"], base))
                raise exporter.ExportError("止める")
            with patch.object(exporter, "pick_folder", return_value=(folder, path)), patch.object(exporter, "run_ffmpeg", side_effect=runner):
                _run(_job([item], root), spec)
        longest = os.path.join(os.path.dirname(seen[0]), schemas.WORK_DIR, os.path.basename(seen[0]) + "_edit.clip.json")   # 作業用/ の中が一番長い
        self.assertLessEqual(exporter.path_units(longest), exporter.MAX_PATH_UNITS)
        self.assertLessEqual(exporter.path_units(seen[0]) + exporter.SUFFIX_ROOM, exporter.MAX_PATH_UNITS)


class TestExportLog(unittest.TestCase):
    def test_log_is_rotated_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(studio_env, "get_out_dir", return_value=tmp), patch.object(exporter, "LOG_MAX", 100):
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
        with patch.dict(os.environ, {"STUDIO_FAKE": ""}), patch.object(studio_env, "find_tool", return_value="/bin/true"):
            with self.assertRaises(errors.ApiError) as cm:
                _fexport.build_spec(S(), {"id": "x", "markIds": ["m1"]})
        self.assertIn("配信の ID", cm.exception.message)   # 文では配信の意味の「動画」は「配信」と呼ぶ


@unittest.skipUnless(studio_env.find_tool("ffmpeg"), "ffmpeg が無い環境ではスキップ")
class TestLoudness(unittest.TestCase):
    """ラウドネス(聞こえ方の音量)をそろえる書き出し。切り抜きと編集用素材に同じ量だけかける"""
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
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)

    def measure(self, path):
        return exporter.measure_loudness(jobs.Ctl(), {"start": 0.0, "end": 1.0, "progress": 0.0}, path)

    def test_build_spec_choices(self):
        src = self.src

        class Store:
            def internal(self, vid):
                return {"id": vid, "marks": [{"id": "m1", "start": 1.0, "end": 2.0, "label": ""}], "kind": "file", "path": src, "title": "t", "fileName": ""}
        self.assertIsNone(_fexport.build_spec(Store(), {"id": "v1", "markIds": ["m1"]})["loudness"])   # 送らなければ今までどおり音量(%)
        self.assertEqual(_fexport.build_spec(Store(), {"id": "v1", "markIds": ["m1"], "loudness": -14})["loudness"], -14.0)
        self.assertIsNone(_fexport.build_spec(Store(), {"id": "v1", "markIds": ["m1"], "loudness": 0})["loudness"])
        for bad in (-13, -40, "x", [1]):
            with self.subTest(bad=bad), self.assertRaises(errors.ApiError):
                _fexport.build_spec(Store(), {"id": "v1", "markIds": ["m1"], "loudness": bad})

    def test_clip_and_edit_media_reach_target_with_same_gain(self):
        clips = [{"id": "m1", "start": 12.0, "end": 18.0, "title": "t", "label": "t", "src": "manual", "markStatus": "adopted"}]
        spec = dict(_spec(self.src, clips), loudness=-14.0)
        job = _job(clips, studio_env.get_out_dir())
        _run(job, spec, lambda *a: True)
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
        self.assertAlmostEqual(lo["measured"], before, delta=1.0)
        for m in (it["manifest"], it["editManifest"]):
            ex = testkit.read_json(m)["export"]
            self.assertEqual(ex["loudness"], lo)
            self.assertNotIn("volume", ex)   # 音量(%)は使っていない
        self.assertEqual(exporter.result_public(job)["items"][0]["loudness"], lo)
        leftovers = [n for n in os.listdir(os.path.dirname(it["path"])) if n.endswith(".vol.mp4")]
        self.assertEqual(leftovers, [])

    def test_silence_is_skipped(self):
        clip = os.path.join(self.tmp, "silent.mp4")
        if not _make_clip(clip):
            self.skipTest("テスト用動画を作れなかった")
        with open(clip, "rb") as f:
            before = hashlib.sha1(f.read()).hexdigest()
        it = {"start": 0.0, "end": 2.0, "progress": 0.0, "path": clip}
        exporter.apply_loudness(jobs.Ctl(), {"loudness": -14.0}, it)
        self.assertIn("skipped", it["loudness"])
        with open(clip, "rb") as f:
            self.assertEqual(hashlib.sha1(f.read()).hexdigest(), before)   # 無音は触らない

    def test_volume_is_not_applied_when_loudness_is_on(self):
        self.assertNotIn("-af", exporter._enc({"volume": 75, "loudness": -14.0}))   # ラウドネスは測ってから apply_loudness がかける


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
    r = subprocess.run([studio_env.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", path, "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
                        "-frames:v", "1", "-f", "null", "-"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    import re
    m = re.search(r"YAVG=([\d.]+)", r.stdout)
    return float(m.group(1)) if m else None


@unittest.skipUnless(studio_env.find_tool("ffmpeg") and studio_env.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
class TestYoutubeTwoStage(unittest.TestCase):
    """YouTube の区間取得は2段: yt-dlp で区間をそのまま取る(前後に余裕・作り直さない)→ ffmpeg の ENC で正確な区間に切って 30fps に"""
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
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)
        self.log = os.path.join(self.tmp, "ytdlp-args.jsonl")

    def export(self, clip, fast=False, preroll=False):
        spec = dict(_spec(None, [clip], fast), kind="youtube", videoId="abcdefghijk", sourceFile=None, mode="url")
        spec.pop("sourcePath")
        job = _job([clip], studio_env.get_out_dir())
        env = {"FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_SRC": self.src, "FAKE_YTDLP_PREROLL": "1" if preroll else ""}
        with patch.dict(os.environ, env), patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, self.fake]):
            _run(job, spec, lambda *a: True)
        with open(self.log, encoding="utf-8") as f:
            calls = [json.loads(l) for l in f]
        return job, calls

    def test_blocked_by_youtube_stops_asking_again(self):
        """YouTube に止められた(bot 判定)ら、方法2(-g)も同じ動画の残りの切り抜きも yt-dlp を呼ばない = 1 回だけ問い合わせて全部同じ失敗"""
        msg = "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies"
        bad = os.path.join(self.tmp, "bot_ytdlp.py")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("import json, os, sys\nopen(os.environ['FAKE_YTDLP_LOG'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    "sys.stderr.buffer.write(%r.encode('utf-8') + b'\\n')\nsys.exit(1)\n" % msg)
        clips = [{"id": "m%d" % i, "start": 3.0 * i, "end": 3.0 * i + 2, "title": "t", "label": "", "src": "manual", "markStatus": ""} for i in range(1, 4)]
        spec = dict(_spec(None, clips, False), kind="youtube", videoId="abcdefghijk", sourceFile=None, mode="url")
        spec.pop("sourcePath")
        job = _job(clips, studio_env.get_out_dir())
        with patch.dict(os.environ, {"FAKE_YTDLP_LOG": self.log}), patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, bad]):
            _run(job, spec, lambda *a: True)
        with open(self.log, encoding="utf-8") as f:
            calls = [json.loads(l) for l in f]
        self.assertEqual(len(calls), 1, calls)   # 区間取得の 1 回だけ(-g も 2 本目・3 本目も呼ばない)
        self.assertEqual([it["status"] for it in job["items"]], ["error"] * 3)
        self.assertTrue(all("not a bot" in it["error"] for it in job["items"]))
        self.assertIn("試していません", job["items"][0]["error"])
        self.assertTrue(exporter.blocked("HTTP Error 429: Too Many Requests") and not exporter.blocked("timed out"))

    def test_ytdlp_error_text_is_read_as_utf8(self):
        """yt-dlp のエラーの文(UTF-8)が化けない: ’ ' と全角の記号がそのまま失敗の文に。
        本物の yt-dlp.exe は --encoding utf-8 が無いと管に cp932 で書くので、起こすコマンドに必ず付ける"""
        with patch.object(studio_env, "find_tool", lambda n: "yt-dlp.exe"):
            self.assertEqual(exporter._ytdlp_cmd(), ["yt-dlp.exe", "--encoding", "utf-8"])
        msg = "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. it's【全角】「記号」〜"
        bad = os.path.join(self.tmp, "bad_ytdlp.py")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("import sys\nsys.stderr.buffer.write(%r.encode('utf-8') + b'\\n')\nsys.exit(1)\n" % msg)
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "t", "label": "", "src": "manual", "markStatus": ""}
        spec = dict(_spec(None, [clip], False), kind="youtube", videoId="abcdefghijk", sourceFile=None, mode="url")
        spec.pop("sourcePath")
        job = _job([clip], studio_env.get_out_dir())
        with patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, bad]):
            _run(job, spec, lambda *a: True)
        err = job["items"][0].get("error") or ""
        self.assertIn("you’re not a bot", err)
        self.assertIn("it's【全角】「記号」〜", err)
        self.assertNotIn("\ufffd", err)
        # 本物の yt-dlp(無い環境ではここだけ飛ばす)に URL でない文字(’ と全角)を渡す = ネットを使わずにエラーの文が出る。_ytdlp_cmd の形で UTF-8 のまま読める
        if studio_env.find_tool("yt-dlp"):
            from ytt import procs as _procs
            p = _procs.run_short(exporter._ytdlp_cmd() + ["--", "テスト’you're【】"], timeout=60)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("テスト’you're【】", p.stderr)

    def test_two_stage_exact_and_30fps(self):
        clip = {"id": "m1", "start": 7.0, "end": 12.0, "title": "t", "label": "", "src": "manual", "markStatus": ""}
        job, calls = self.export(clip)
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        # 1段目: 前後に編集用素材の 10 秒(EDIT_HANDLE_SEC。SECTION_PAD より広い)の余裕・作り直さない(--force-keyframes-at-cuts を付けない)。
        # 本体と前後10秒の編集用素材は同じ 1 回の取得から切る(YouTube への問い合わせは 1 本に 1 回。10-18)
        sections = [c[c.index("--download-sections") + 1] for c in calls]
        self.assertEqual(sections, ["*00:00:00.000-00:00:22.000"])
        self.assertFalse(any("--force-keyframes-at-cuts" in c for c in calls))
        # 2段目: 正確な区間・30fps・crf 18
        self.assertAlmostEqual(mediainfo.media_info(it["path"])[0], 5.0, delta=0.2)
        self.assertEqual((_fps(it["path"]), _fps(it["editPath"])), ("30/1", "30/1"))
        self.assertAlmostEqual(_y_avg(it["path"]), 56, delta=3)      # 最初のコマ = 元の 7 秒(余裕の 2 秒ぶんずれていない)
        self.assertAlmostEqual(_y_avg(it["editPath"]), 0, delta=3)   # 編集用素材は 0 秒から
        d = testkit.read_json(it["manifest"])
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
        self.assertEqual(testkit.read_json(it["manifest"])["export"]["mode"], "fast")
        self.assertAlmostEqual(_y_avg(it["path"]), 56, delta=3)

    def test_unknown_start_falls_back_and_cleans_up(self):
        """取ったファイルが頼んだより長い(手前のキーフレームから見えている)ときは、位置が分からないので方法2(直接指定)へ回す"""
        clip = {"id": "m1", "start": 15.0, "end": 17.5, "title": "t", "label": "", "src": "manual", "markStatus": ""}   # 取る始まり 5 秒より手前から取れる所
        job, calls = self.export(clip, preroll=True)
        it = job["items"][0]
        self.assertEqual(it["status"], "error")
        self.assertIn("開始の位置", it["error"])
        self.assertIn("-g", calls[-1])   # 方法2 を試した
        folder = os.path.join(studio_env.get_out_dir(), job["folder"])
        left = [n for dd in (folder, os.path.join(folder, schemas.WORK_DIR)) if os.path.isdir(dd) for n in os.listdir(dd)
                if os.path.isfile(os.path.join(dd, n)) and n != ".studio-id"]
        self.assertEqual(left, [])


@unittest.skipUnless(studio_env.find_tool("ffmpeg") and studio_env.find_tool("ffprobe"), "ffmpeg・ffprobe が無い環境ではスキップ")
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
        self.tmp = testkit.tempdir(self)
        studio_env.set_home(self.tmp)
        self.folder = os.path.join(studio_env.get_out_dir(), "配信フォルダ")
        os.makedirs(self.folder)
        self.final = os.path.join(self.folder, "01_速報版を作り直す.mp4")
        self.log = os.path.join(self.tmp, "ytdlp-args.jsonl")
        real = studio_env.find_tool
        self.patches = [patch.dict(os.environ, {"STUDIO_FAKE": "0", "FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_SRC": self.src, "FAKE_YTDLP_PREROLL": ""}),
                        patch.object(studio_env, "find_tool", lambda n: "yt-dlp" if n == "yt-dlp" else real(n)),   # 本物の yt-dlp が無くても組み立てられる
                        patch.object(exporter, "_ytdlp_cmd", return_value=[sys.executable, self.fake])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def req(self, **kw):
        return dict({"videoId": "abcdefghijk", "start": 7, "end": 12, "path": self.final}, **kw)

    def run_section(self, **kw):
        spec = exporter.build_section_spec(self.req(**kw))
        return _run(exporter.new_result(spec), spec)

    def tree(self):
        return sorted(os.path.relpath(os.path.join(d, n), self.folder) for d, _ds, ns in os.walk(self.folder) for n in ns)

    def test_exact_path_30fps_and_nothing_else(self):
        job = self.run_section()
        it = job["items"][0]
        self.assertEqual((job["state"], it["status"]), ("done", "done"), it.get("error"))
        pub = exporter.result_public(job)["items"][0]
        self.assertEqual((pub["path"], pub["manifest"], pub["editPath"], pub["status"]), (self.final, None, None, "done"))
        self.assertEqual(pub["file"], "配信フォルダ/" + os.path.basename(self.final))
        self.assertAlmostEqual(mediainfo.media_info(self.final)[0], 5.0, delta=0.2)
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
        def slow(ctl, *a, **kw):
            for _ in range(200):
                if ctl.cancelled:
                    raise exporter.ExportError("中止しました")
                time.sleep(0.05)
        with patch.object(exporter, "run_ytdlp", side_effect=slow):
            spec = exporter.build_section_spec(self.req())
            job, ctl = exporter.new_result(spec), jobs.Ctl()   # 同時 1 本(409)は器 = ② の flow/export の側(src/flow/tests/test_export_jobs.py)
            t = threading.Thread(target=_run, args=(job, spec, None, ctl))
            t.start()
            time.sleep(0.2)
            ctl.cancel()
            t.join(10)
        self.assertEqual((job["state"], job["items"][0]["status"]), ("cancelled", "cancelled"))
        self.assertFalse(os.path.exists(self.final))

    def test_fake_mode_uses_fake_media(self):
        with patch.dict(os.environ, {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": self.src}):
            spec = exporter.build_section_spec(self.req())
            self.assertEqual((spec["mode"], spec["sourcePath"]), ("file", self.src))
            job = self.run_section()
        self.assertEqual(job["items"][0]["status"], "done", job["items"][0].get("error"))
        self.assertEqual(_fps(self.final), "30/1")
        with patch.dict(os.environ, {"STUDIO_FAKE": "1", "STUDIO_FAKE_MEDIA": ""}), self.assertRaises(errors.ApiError) as c:
            exporter.build_section_spec(self.req(path=os.path.join(self.folder, "c.mp4")))
        self.assertEqual(c.exception.status, 500)

    def test_bad_requests(self):
        out = studio_env.get_out_dir()
        os.makedirs(os.path.join(out, "x"), exist_ok=True)
        with open(os.path.join(self.folder, "exists.mp4"), "wb") as f:
            f.write(b"x")
        bads = [dict(videoId="short"), dict(videoId="abcdefghijk\n"), dict(videoId="あいうえおかきくけこさ"), dict(videoId=None), dict(videoId=12345678901), dict(videoId="abcdefghij/"),
                dict(start=-1), dict(start=12), dict(start=13), dict(end=7), dict(start="7"), dict(start=None), dict(start=True), dict(end=float("nan")), dict(end=float("inf")),
                dict(start=0, end=3601), dict(end=None), dict(start=10 ** 400), dict(end=10 ** 400),   # float にできない巨大な整数(OverflowError にしない)
                dict(path=None), dict(path=""), dict(path="rel.mp4"), dict(path=os.path.join(self.folder, "a.mkv")), dict(path=os.path.join(self.folder, "a")),
                dict(path=os.path.join(self.folder, "a%b.mp4")), dict(path=os.path.join(self.folder, "a.partial.mp4")), dict(path=os.path.join(self.folder, "CON.mp4")),
                dict(path=os.path.join(self.dir, "outside.mp4")), dict(path=os.path.join(out, "..", "outside.mp4")), dict(path=os.path.join(self.folder, "..", "..", "o.mp4")),
                dict(path=os.path.join(out, "nodir", "a.mp4")), dict(path=os.path.join(self.folder, "exists.mp4")), dict(path=os.path.join(self.folder, "a" * 300 + ".mp4")),
                dict(path=os.path.join(out, "x")), dict(path="a\x00.mp4"),
                dict(volume=0), dict(volume=201), dict(volume="abc"), dict(loudness=-13), dict(loudness="x"), dict(precision="turbo")]
        for kw in bads:
            with self.subTest(kw=kw), self.assertRaises(errors.ApiError) as c:
                exporter.build_section_spec(self.req(**kw))
            self.assertEqual((c.exception.status, c.exception.code), (400, "bad_request"), kw)
        # 正しい形は通る(マークも配信の登録も要らない)・path の親が書き出し先そのもの(直下)でもよい
        self.assertEqual(exporter.build_section_spec(self.req(path=os.path.join(out, "direct.mp4")))["outDir"], out)
        self.assertEqual(exporter.build_section_spec(self.req(start=0, end=3600, loudness=0, maxHeight=None, volume=None))["clips"][0]["end"], 3600.0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
