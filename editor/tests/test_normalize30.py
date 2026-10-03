#!/usr/bin/env python3
"""素材を 30fps にそろえる(マスタープラン Q1)の「編集」の側のテスト: 単体の文字起こし・動画を選び直す・友人用簡易版。

    py -3.10 -m unittest editor/tests/test_metrics.py        # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest editor/tests/test_normalize30.py    # これだけ

ffmpeg・ffprobe で数秒の合成動画(lavfi)を作り、疑似の認識(TRANSCRIBE_BACKEND=fake)で文字起こしのジョブをその場で動かす。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, StoreDir  # noqa: F401  (S = serve)
import ed_jobs  # noqa: E402
import ed_lite  # noqa: E402
import ed_relink  # noqa: E402
import ed_store  # noqa: E402
from ytt_core import normalize as N  # noqa: E402

os.environ.setdefault("YTT_CUT2RESOLVE_DIR", os.path.join(os.path.dirname(os.path.dirname(TESTS)), "cut2resolve"))
HAVE_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_video(path, fps=60, sec=8, codec="libx264"):
    """testsrc の映像 + sine の音(AAC)。疑似の文字起こしは 4 秒ごとに1行"""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=160x90:rate=%s:duration=%s" % (fps, sec),
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % sec,
                    "-c:v", codec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path], check=True)
    return path


@unittest.skipUnless(HAVE_FF, "ffmpeg・ffprobe が必要")
class _Base(StoreDir):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.v60 = make_video(os.path.join(cls.src_dir, "v60.mp4"), 60)
        cls.v30 = make_video(os.path.join(cls.src_dir, "v30.mp4"), 30)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.media = os.path.join(self.tmp, "動画")   # 作業データ(TX_DIR = self.tmp)の lite-media/ とは別のフォルダ
        os.makedirs(self.media)
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "LITE_MODEL": "small",
                                                "TRANSCRIBE_NORMALIZE": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        with ed_jobs._jobs_lock:   # このテストのジョブを残さない(ほかのテストの _doc_busy に掛からないように)
            for k in [k for k, j in ed_jobs._jobs.items() if str((j.get("spec") or {}).get("sourcePath") or "").startswith(self.tmp)
                      or (j.get("spec") or {}).get("tid") in self.tids()]:
                ed_jobs._jobs.pop(k, None)
        super().tearDown()

    def tids(self):
        return [n[:-5] for n in os.listdir(self.tmp) if n.endswith(".json") and len(n) == 17] if os.path.isdir(self.tmp) else []

    def copy(self, src, name):
        p = os.path.join(self.media, name)
        shutil.copy(src, p)
        return p

    def run_job(self, job):
        ed_jobs._queue.get_nowait()   # 待機列のワーカーに取られないように、ここで直接動かす
        ed_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def transcribe(self, path, **req):
        spec = ed_jobs.validate_job(dict({"sourcePath": path, "model": "small"}, **req))
        return self.run_job(ed_jobs.add_job(spec))

    def doc(self, tid):
        return ed_store.read_transcript(tid)

    def assert_30(self, path):
        info = N.probe(path)
        self.assertTrue(N.is_30fps(info), info)
        self.assertEqual(N.needs_normalize(info), (False, []))


class TestTranscribeNormalize(_Base):
    def test_60fps_makes_sibling_and_relinks(self):
        """文字起こしのあと、隣に <名前>_30fps.mp4 を作って文書をそれに付け替える。元は残る。行は元の動画で作ったまま"""
        src = self.copy(self.v60, "配信 60.mp4")
        seen = []
        real = N.normalize

        def spy(*a, **kw):
            seen.append((job["state"], job["phase"], job.get("tid")))
            return real(*a, **kw)
        spec = ed_jobs.validate_job({"sourcePath": src, "model": "small"})
        job = ed_jobs.add_job(spec)
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=spy):
            self.run_job(job)
        dst = os.path.join(self.media, "配信 60_30fps.mp4")
        self.assertEqual(seen, [("running", ed_relink.NORM_PHASE, job["tid"])])   # 進み具合は「30fps にそろえています… n%」・作り直しの間は文書を止める
        self.assertEqual(job["progress"], 1.0)
        d = self.doc(job["tid"])
        self.assertEqual((os.path.normcase(d["sourcePath"]), d["sourceName"]), (os.path.normcase(dst), "配信 60_30fps.mp4"))
        self.assertEqual(len(d["segments"]), 2)
        self.assertEqual(d["relinks"][-1]["why"], ed_relink.NORM_WHY)
        self.assertEqual(os.path.normcase(d["relinks"][-1]["from"]), os.path.normcase(src))
        self.assertTrue(os.path.isfile(src))   # 元は消さない
        self.assert_30(dst)
        self.assertTrue(ed_jobs.public_job(job)["normOk"])
        self.assertIn("30fps", ed_jobs.public_job(job)["normNote"])
        self.assertEqual([n for n in os.listdir(self.media) if N.PART in n], [])

    def test_30fps_is_not_remade(self):
        src = self.copy(self.v30, "そのまま.mp4")
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=AssertionError("作り直さない")):
            job = self.transcribe(src)
        d = self.doc(job["tid"])
        self.assertEqual(os.path.normcase(d["sourcePath"]), os.path.normcase(src))
        self.assertNotIn("relinks", d)
        self.assertEqual(sorted(os.listdir(self.media)), ["そのまま.mp4"])
        self.assertEqual(ed_jobs.public_job(job)["normNote"], "")

    def test_existing_30fps_copy_is_reused(self):
        src = self.copy(self.v60, "a.mp4")
        made = self.copy(self.v30, "a_30fps.mp4")   # 前に作った 30fps の写し(長さも同じ)
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=AssertionError("作り直さない")):
            job = self.transcribe(src)
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(made))
        self.assertIn("があったので", job["normNote"])

    def test_unusable_existing_name_is_not_overwritten(self):
        """同じ名前があっても 30fps でない(別の動画)なら上書きせず、次の名前に作る"""
        src = self.copy(self.v60, "b.mp4")
        other = self.copy(self.v60, "b_30fps.mp4")
        size = os.path.getsize(other)
        job = self.transcribe(src)
        dst = os.path.join(self.media, "b_30fps_2.mp4")
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(dst))
        self.assertEqual(os.path.getsize(other), size)
        self.assert_30(dst)

    def test_eval_is_not_remade(self):
        """評価用(evalSet)は作り直さない(パックを作らない・評価用のフォルダの整理が動画の数を数えるため)"""
        src = self.copy(self.v60, "評価.mp4")
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=AssertionError("作り直さない")):
            job = self.transcribe(src, evalSet=True)
        d = self.doc(job["tid"])
        self.assertTrue(d["evalSet"])
        self.assertEqual(os.path.normcase(d["sourcePath"]), os.path.normcase(src))
        self.assertEqual(os.listdir(self.media), ["評価.mp4"])

    def test_eval_dir_is_not_remade(self):
        """評価用のフォルダ(設定 evalDirs)の中の動画も、画面のチェックが無くても作り直さない"""
        root = os.path.join(self.tmp, "評価用データ")
        os.makedirs(os.path.join(root, "01_ときのそら"))
        src = os.path.join(root, "01_ときのそら", "x.mp4")
        shutil.copy(self.v60, src)
        with open(S.SETTINGS, "w", encoding="utf-8") as f:
            json.dump({"evalDirs": [root]}, f)
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=AssertionError("作り直さない")):
            job = self.transcribe(src)
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src))
        self.assertEqual(os.listdir(os.path.join(root, "01_ときのそら")), ["x.mp4"])

    def test_failure_keeps_doc(self):
        """作り直しに失敗しても文書(文字起こしの結果)は残り、元の動画を指す。知らせに理由"""
        src = self.copy(self.v60, "c.mp4")
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=N.NormalizeError("こわれた")):
            job = self.transcribe(src)
        d = self.doc(job["tid"])
        self.assertEqual(os.path.normcase(d["sourcePath"]), os.path.normcase(src))
        self.assertEqual(len(d["segments"]), 2)
        pj = ed_jobs.public_job(job)
        self.assertFalse(pj["normOk"])
        self.assertIn("こわれた", pj["normNote"])
        self.assertTrue(any("こわれた" in w for w in pj["warnings"]))

    def test_real_ffmpeg_failure_keeps_doc(self):
        src = self.copy(self.v60, "d.mp4")
        with mock.patch.object(N, "encode_args", return_value=["-no_such_option_xyz", "1"]):
            job = self.transcribe(src)
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src))
        self.assertIn("30fps にそろえられませんでした", job["normNote"])
        self.assertEqual(os.listdir(self.media), ["d.mp4"])   # 書きかけは残らない

    def test_cancel_during_normalize_keeps_doc(self):
        src = self.copy(self.v60, "e.mp4")
        spec = ed_jobs.validate_job({"sourcePath": src, "model": "small"})
        job = ed_jobs.add_job(spec)
        real = N.normalize

        def cancel_then_run(*a, **kw):
            job["cancel"] = True   # 「中止」が押された
            return real(*a, **kw)
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=cancel_then_run):
            self.run_job(job)
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src))
        self.assertIn("取り消しました", job["normNote"])
        self.assertEqual(os.listdir(self.media), ["e.mp4"])

    def test_no_room_keeps_doc(self):
        """空きが足りない・書き込めないときは作らずに知らせる"""
        src = self.copy(self.v60, "f.mp4")
        with mock.patch.object(ed_relink.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 1)):
            job = self.transcribe(src)
        self.assertIn("空きが足りない", job["normNote"])
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src))
        src2 = self.copy(self.v60, "g.mp4")
        real = tempfile.mkstemp

        def mkstemp(*a, **kw):   # 動画のフォルダにだけ書けない(読み取り専用のふり。ほかの一時ファイルは今までどおり)
            if os.path.normcase(str(kw.get("dir") or "")) == os.path.normcase(self.media):
                raise PermissionError("読み取り専用")
            return real(*a, **kw)
        with mock.patch.object(ed_relink.tempfile, "mkstemp", side_effect=mkstemp):
            job = self.transcribe(src2)
        self.assertIn("書き込めない", job["normNote"])
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src2))

    def test_switch_off(self):
        src = self.copy(self.v60, "h.mp4")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_NORMALIZE": "off"}):
            job = self.transcribe(src)
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src))

    def test_audio_only_is_skipped(self):
        wav = os.path.join(self.media, "声.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", wav], check=True)
        job = self.transcribe(wav)
        self.assertEqual(job["normNote"] if "normNote" in job else "", "")
        self.assertEqual(os.listdir(self.media), ["声.wav"])

    def test_swap_skipped_when_doc_moved(self):
        """作り直しの間に文書の動画が変わった(以前の版に戻した など)ら付け替えない"""
        src = self.copy(self.v60, "i.mp4")
        job = self.transcribe(src)
        tid = job["tid"]
        d = self.doc(tid)
        before = d["updatedAt"]
        self.assertEqual(ed_relink.norm_swap(tid, src, os.path.join(self.media, "x.mp4")) is not None, True)
        self.assertEqual(self.doc(tid)["updatedAt"], before)   # 付け替え(bump=False)は更新日時を変えない = 開いている画面の保存が 409 にならない


class TestRelinkNormalize(_Base):
    def make_doc(self, path):
        tid = ed_store.open_video({"path": path})["id"]
        return tid, self.doc(tid)

    def test_relink_then_background_job(self):
        """選び直しで 30fps でない動画を選んだ: すぐに付け替え、裏のジョブで作り直して付け替え直す(更新日時は変えない)"""
        old = self.copy(self.v30, "元.mp4")
        tid, d = self.make_doc(old)
        os.remove(old)
        moved = self.copy(self.v60, "移した先.mp4")
        r = S.relink_doc({"id": tid, "path": moved, "baseUpdatedAt": d["updatedAt"], "acceptDiff": True})
        self.assertTrue(r["normalizing"])
        self.assertEqual(os.path.normcase(self.doc(tid)["sourcePath"]), os.path.normcase(moved))   # 付け替えは済んでいる
        job = ed_jobs._jobs[r["normalizing"]]
        self.assertEqual((job["kind"], job["tid"]), ("normalize", tid))
        with self.assertRaises(S.ApiError) as cm:   # 作り直しの間は、この文書を選び直せない
            S.relink_doc({"id": tid, "path": old, "baseUpdatedAt": r["updatedAt"]})
        self.assertIn(cm.exception.code, ("busy", "no_file"))
        self.run_job(job)
        d2 = self.doc(tid)
        dst = os.path.join(self.media, "移した先_30fps.mp4")
        self.assertEqual(os.path.normcase(d2["sourcePath"]), os.path.normcase(dst))
        self.assertEqual(d2["updatedAt"], r["updatedAt"])
        self.assertEqual(d2["relinks"][-1]["why"], ed_relink.NORM_WHY)
        self.assertTrue(ed_jobs.public_job(job)["normOk"])
        self.assert_30(dst)
        self.assertTrue(os.path.isfile(moved))

    def test_bulk_relink_does_not_normalize(self):
        """まとめて付け替える(normalize: false)は作り直さない(以前の文書の動画はそのまま)"""
        old = self.copy(self.v30, "元2.mp4")
        tid, d = self.make_doc(old)
        moved = self.copy(self.v60, "先2.mp4")
        r = S.relink_doc({"id": tid, "path": moved, "baseUpdatedAt": d["updatedAt"], "acceptDiff": True, "normalize": False})
        self.assertIsNone(r["normalizing"])
        self.assertEqual(sorted(os.listdir(self.media)), sorted(["先2.mp4", "元2.mp4"]))

    def test_relink_to_30fps_needs_nothing(self):
        old = self.copy(self.v60, "元3.mp4")
        tid, d = self.make_doc(old)
        moved = self.copy(self.v30, "先3.mp4")
        r = S.relink_doc({"id": tid, "path": moved, "baseUpdatedAt": d["updatedAt"], "acceptDiff": True})
        self.assertIsNone(r["normalizing"])
        self.assertEqual(r["normNote"], "")

    def test_eval_doc_relink_does_not_normalize(self):
        old = self.copy(self.v30, "元4.mp4")
        tid, d = self.make_doc(old)
        doc = self.doc(tid)
        doc["evalSet"] = True
        S.atomic_write(S.tx_path(tid), json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        moved = self.copy(self.v60, "先4.mp4")
        r = S.relink_doc({"id": tid, "path": moved, "baseUpdatedAt": doc["updatedAt"], "acceptDiff": True})
        self.assertIsNone(r["normalizing"])


class TestLiteNormalize(_Base):
    def start(self, path):
        job = ed_lite.start({"path": path, "streamer": "兎田ぺこら"})
        return self.run_job(ed_jobs._jobs[job["id"]])

    def test_drop_makes_30fps_copy_in_lite_media(self):
        """ドロップ(lite-media/ に受け取った写し)が 60fps: lite-media/<番号>/<元の名前>.mp4 に 30fps の写しを作って使い、受け取った写しは消す"""
        with open(self.v60, "rb") as f:
            data = f.read()
        import io
        up = ed_lite.receive_upload(io.BytesIO(data), len(data), "配信 動画.mp4")
        job = self.start(up["path"])
        d = self.doc(job["tid"])
        p = d["sourcePath"]
        self.assertEqual(os.path.normcase(os.path.dirname(os.path.dirname(p))), os.path.normcase(ed_lite.media_dir()))
        self.assertEqual(os.path.basename(p), "配信_動画.mp4")   # 受け取りのときに付けた番号は外す(名前は受け取りのときの安全な形)
        self.assert_30(p)
        self.assertFalse(os.path.exists(up["path"]))
        self.assertEqual(d["title"], "配信_動画")
        self.assertEqual(d["lite"]["streamer"], "兎田ぺこら")

    def test_pick_makes_30fps_copy_and_keeps_original(self):
        src = self.copy(self.v60, "友人の動画.mp4")
        job = self.start(src)
        p = self.doc(job["tid"])["sourcePath"]
        self.assertTrue(p.startswith(ed_lite.media_dir()))
        self.assertEqual(os.path.basename(p), "友人の動画.mp4")
        self.assert_30(p)
        self.assertTrue(os.path.isfile(src))
        self.assertEqual(os.listdir(self.media), ["友人の動画.mp4"])   # 友人の動画のフォルダには書かない

    def test_30fps_pick_is_used_as_is(self):
        src = self.copy(self.v30, "30.mp4")
        job = self.start(src)
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(src))
        self.assertFalse(os.path.isdir(ed_lite.media_dir()) and os.listdir(ed_lite.media_dir()))

    def test_failure_keeps_upload(self):
        with open(self.v60, "rb") as f:
            data = f.read()
        import io
        up = ed_lite.receive_upload(io.BytesIO(data), len(data), "x.mp4")
        with mock.patch.object(ed_relink._vnorm, "normalize", side_effect=N.NormalizeError("こわれた")):
            job = self.start(up["path"])
        self.assertEqual(os.path.normcase(self.doc(job["tid"])["sourcePath"]), os.path.normcase(up["path"]))
        self.assertTrue(os.path.isfile(up["path"]))
        self.assertEqual(sorted(os.listdir(ed_lite.media_dir())), [os.path.basename(up["path"])])   # 作りかけのフォルダは残さない


if __name__ == "__main__":
    unittest.main(verbosity=2)
