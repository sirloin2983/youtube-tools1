#!/usr/bin/env python3
"""素材を 30fps にそろえるテスト: ② flow/normalize の段・動画を選び直す(④ の付け替え)。

    py -3.12 -m unittest src/editor/tests/test_metrics.py        # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest src/editor/tests/test_normalize30.py    # これだけ

ffmpeg・ffprobe で数秒の合成動画(lavfi)を作り、疑似の認識(TRANSCRIBE_BACKEND=fake)で文字起こしのジョブをその場で動かす。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
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
from human.proof import doc_jobs  # noqa: E402
from human.proof import store  # noqa: E402
from flow import jobs  # noqa: E402
from flow import normalize as FN  # noqa: E402   ② 30fps にそろえる段
from manage.cases import relink as RL  # noqa: E402   付け替えと 30fps
from ytt import normalize as N  # noqa: E402

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
        self.media = os.path.join(self.tmp, "動画")   # 作業データ(TX_DIR = self.tmp)とは別のフォルダ
        os.makedirs(self.media)
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0",
                                                "TRANSCRIBE_NORMALIZE": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        with jobs._jobs_lock:   # このテストのジョブを残さない(ほかのテストの _doc_busy に掛からないように)
            for k in [k for k, j in jobs._jobs.items() if str((j.get("spec") or {}).get("sourcePath") or "").startswith(self.tmp)
                      or (j.get("spec") or {}).get("tid") in self.tids()]:
                jobs._jobs.pop(k, None)
        super().tearDown()

    def tids(self):
        return [n[:-5] for n in os.listdir(self.tmp) if n.endswith(".json") and len(n) == 17] if os.path.isdir(self.tmp) else []

    def copy(self, src, name):
        p = os.path.join(self.media, name)
        shutil.copy(src, p)
        return p

    def run_job(self, job):
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def transcribe(self, path, **req):
        spec = doc_jobs.validate_job(dict({"sourcePath": path, "model": "small"}, **req))
        return self.run_job(jobs.add_job(spec))

    def doc(self, tid):
        return store.read_transcript(tid)

    def assert_30(self, path):
        info = N.probe(path)
        self.assertTrue(N.is_30fps(info), info)
        self.assertEqual(N.needs_normalize(info), (False, []))


class TestFlowNormalize(_Base):
    """② flow/normalize の plan・run(30fps にそろえる 1 つの段)"""

    def make_run(self, src, **kw):
        p = FN.plan(src, **kw)
        self.assertTrue(p)
        return p, FN.run(p)

    def test_job_through(self):
        """30fps にそろえる通し: 予定(隣に <名前>_30fps.mp4)→ ジョブの本体(本物の ffmpeg)→ 付け替え。
        できた動画は 30fps の H.264・yuv420p・8bit・AAC で長さは元のまま・元は残る・書きかけは残らない"""
        src = self.copy(self.v60, "配信 60.mp4")
        before = N.probe(src)
        p = FN.plan(src)
        dst = os.path.join(self.media, "配信 60_30fps.mp4")
        self.assertEqual((os.path.normcase(p["dst"]), p["reuse"], p["replace"]), (os.path.normcase(dst), False, False))
        self.assertTrue(any("30fps" in w for w in p["why"]), p["why"])

        class Job(dict):   # 進み具合と段の移り変わりを残す
            seen = []

            def __setitem__(self, k, v):
                if k in ("progress", "phase"):
                    self.seen.append((k, v))
                super().__setitem__(k, v)
        job, calls = Job(spec={"tid": "t1", "plan": p}, state="queued"), []
        FN.run_job(job, swap=lambda tid, s, d: calls.append((tid, os.path.normcase(s), os.path.normcase(d))))
        self.assertEqual(calls, [("t1", os.path.normcase(os.path.abspath(src)), os.path.normcase(dst))])
        self.assertEqual((job["state"], job["phase"], job["progress"], job["normOk"]), ("done", "完了", 1.0, True))
        self.assertIn(os.path.basename(dst), job["normNote"])
        self.assertEqual(job.seen[:2], [("phase", FN.NORM_PHASE), ("progress", 0.0)])   # ffmpeg を回す直前に「30fps にそろえています」
        self.assertEqual(job.seen[-3:], [("progress", 1.0), ("progress", 1.0), ("phase", "完了")])   # 作り直しの進み具合が 1.0 まで届いてから完了
        after = N.probe(dst)
        self.assertEqual((after["r_frame_rate"], after["vcodec"], after["pix_fmt"], after["bit_depth"], after["acodec"], after["cfr"], after["width"]),
                         ("30/1", "h264", "yuv420p", 8, "aac", True, 160))
        self.assertAlmostEqual(after["duration"], before["duration"], delta=0.1)   # 長さ(= 時刻)は保たれる
        self.assert_30(dst)
        self.assertEqual(sorted(os.listdir(self.media)), sorted([os.path.basename(src), os.path.basename(dst)]))   # 元は残る・書きかけは残らない

    def test_no_plan(self):
        """予定を立てない: 30fps のまま・切り替えがオフ・音声だけ"""
        wav = os.path.join(self.media, "声.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", wav], check=True)
        self.assertIsNone(FN.plan(self.copy(self.v30, "そのまま.mp4")))
        self.assertIsNone(FN.plan(wav))
        with mock.patch.dict(os.environ, {"TRANSCRIBE_NORMALIZE": "off"}):
            self.assertIsNone(FN.plan(self.copy(self.v60, "h.mp4")))

    def test_2997_is_made_30_and_keeps_length(self):
        """配信の録画に多い 29.97fps も 30/1 に作り直し、長さ(= 時刻)は保つ(60 と別の入力で fps の丸めを見る)"""
        src = make_video(os.path.join(self.media, "配信 2997.mp4"), "30000/1001", sec=4)
        before = N.probe(src)
        p, _ran = self.make_run(src)
        after = N.probe(p["dst"])
        self.assertEqual(after["r_frame_rate"], "30/1")
        self.assertAlmostEqual(after["duration"], before["duration"], delta=0.1)

    def test_existing_30fps_copy_is_reused(self):
        src = self.copy(self.v60, "a.mp4")
        made = self.copy(self.v30, "a_30fps.mp4")   # 前に作った 30fps の写し(長さも同じ)
        p = FN.plan(src)
        self.assertTrue(p["reuse"])
        with mock.patch.object(N, "normalize", side_effect=AssertionError("作り直さない")):
            path, note = FN.run(p)
        self.assertEqual(os.path.normcase(path), os.path.normcase(made))
        self.assertIn("があったので", note)

    def test_unusable_existing_name_is_not_overwritten(self):
        """同じ名前があっても 30fps でない(別の動画)なら上書きせず、次の名前に作る"""
        src = self.copy(self.v60, "b.mp4")
        other = self.copy(self.v60, "b_30fps.mp4")
        size = os.path.getsize(other)
        p, (path, note) = self.make_run(src)
        dst = os.path.join(self.media, "b_30fps_2.mp4")
        self.assertEqual(os.path.normcase(path), os.path.normcase(dst))
        self.assertEqual(os.path.getsize(other), size)
        self.assert_30(dst)

    def test_names_all_taken_gives_note(self):
        src = self.copy(self.v60, "n.mp4")
        for nm in ["n_30fps.mp4"] + ["n_30fps_%d.mp4" % i for i in range(2, 10)]:
            self.copy(self.v60, nm)
        p = FN.plan(src)
        self.assertIsNone(p["dst"])
        self.assertIn("空いていない", p["note"])
        self.assertEqual(FN.run(p), (None, p["note"]))

    def test_failure_gives_reason(self):
        src = self.copy(self.v60, "c.mp4")
        with mock.patch.object(N, "normalize", side_effect=N.NormalizeError("こわれた")):
            path, note = FN.run(FN.plan(src))
        self.assertIsNone(path)
        self.assertIn("こわれた", note)

    def test_real_ffmpeg_failure(self):
        src = self.copy(self.v60, "d.mp4")
        with mock.patch.object(N, "encode_args", return_value=["-no_such_option_xyz", "1"]):
            path, note = FN.run(FN.plan(src))
        self.assertIsNone(path)
        self.assertIn("30fps にそろえられませんでした", note)
        self.assertEqual(os.listdir(self.media), ["d.mp4"])   # 書きかけは残らない

    def test_cancel(self):
        src = self.copy(self.v60, "e.mp4")
        path, note = FN.run(FN.plan(src), cancelled=lambda: True)
        self.assertIsNone(path)
        self.assertIn("取り消しました", note)
        self.assertEqual(os.listdir(self.media), ["e.mp4"])

    def test_no_room(self):
        """空きが足りない・書き込めないときは作らずに理由を返す"""
        src = self.copy(self.v60, "f.mp4")
        with mock.patch.object(FN.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 1)):
            path, note = FN.run(FN.plan(src))
        self.assertIsNone(path)
        self.assertIn("空きが足りない", note)
        src2 = self.copy(self.v60, "g.mp4")
        real = tempfile.mkstemp

        def mkstemp(*a, **kw):   # 動画のフォルダにだけ書けない(読み取り専用のふり)
            if os.path.normcase(str(kw.get("dir") or "")) == os.path.normcase(self.media):
                raise PermissionError("読み取り専用")
            return real(*a, **kw)
        with mock.patch.object(FN.tempfile, "mkstemp", side_effect=mkstemp):
            path, note = FN.run(FN.plan(src2))
        self.assertIsNone(path)
        self.assertIn("書き込めない", note)

    def test_replace_mode_swaps_the_copy(self):
        """replace=True(③ 受付の写し用): 同じ名前の .mp4 に作って、拡張子が違えば古い写しを消す。mp4 なら同じ名前のまま上書き"""
        mov = self.copy(self.v60, "写し.mov")   # 中身は mp4 でも拡張子は .mov の写し
        p = FN.plan(mov, replace=True)
        self.assertEqual((os.path.basename(p["dst"]), p["replace"], p["reuse"]), ("写し.mp4", True, False))
        path, note = FN.run(p)
        self.assertEqual(os.listdir(self.media), ["写し.mp4"])
        self.assert_30(path)
        mp4 = self.copy(self.v60, "同じ.mp4")
        p2 = FN.plan(mp4, replace=True)
        self.assertEqual(os.path.normcase(p2["dst"]), os.path.normcase(mp4))
        path2, _ = FN.run(p2)
        self.assertEqual(os.listdir(self.media), sorted(["写し.mp4", "同じ.mp4"], key=str))
        self.assert_30(path2)
        taken = self.copy(self.v60, "かぶる.mov")
        self.copy(self.v30, "かぶる.mp4")   # 同じ名前の .mp4 が別にある → 乱数つき
        p3 = FN.plan(taken, replace=True)
        self.assertNotEqual(os.path.basename(p3["dst"]), "かぶる.mp4")

    def test_job_body_swap_refused(self):
        """ジョブ normalize の本体: 付け替えなかったら元の動画のまま・知らせに理由"""
        src2 = self.copy(self.v60, "k.mp4")
        job2 = {"spec": {"tid": "t2", "plan": FN.plan(src2)}, "state": "queued"}
        FN.run_job(job2, swap=lambda tid, s, d: "動いたので付け替えません")
        self.assertEqual((job2["phase"], job2["normOk"], job2["normNote"]), ("元の動画のまま", False, "動いたので付け替えません"))
        self.assertTrue(job2["warnings"])

    def test_swap_skipped_when_doc_moved(self):
        """④ norm_swap: 作り直しの間に文書の動画が変わった(以前の版に戻した など)ら付け替えない"""
        src = self.copy(self.v60, "i.mp4")
        from test_edit import put_empty_doc   # 行の無い文書
        tid = put_empty_doc(store._workdata.TX_DIR, src)
        before = self.doc(tid)["updatedAt"]
        self.assertIsNotNone(RL.norm_swap(tid, os.path.join(self.media, "other.mp4"), os.path.join(self.media, "x.mp4")))
        self.assertEqual(self.doc(tid)["updatedAt"], before)
        dst = self.copy(self.v30, "i_30fps.mp4")
        self.assertIsNone(RL.norm_swap(tid, src, dst))
        d = self.doc(tid)
        self.assertEqual(d["updatedAt"], before)   # 付け替え(bump=False)は更新日時を変えない = 開いている画面の保存が 409 にならない
        self.assertEqual(os.path.normcase(d["sourcePath"]), os.path.normcase(dst))
        self.assertEqual(d["relinks"][-1]["why"], RL.NORM_WHY)
        self.assertEqual(store.find_doc_for_media(src)["id"], tid)   # 付け替える前のパスからも見つかる(?media=・スタジオから開く)


class TestRelinkNormalize(_Base):
    def make_doc(self, path):
        from test_edit import put_empty_doc   # 行の無い文書
        tid = put_empty_doc(store._workdata.TX_DIR, path)
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
        job = jobs._jobs[r["normalizing"]]
        self.assertEqual((job["kind"], job["tid"]), ("normalize", tid))
        with self.assertRaises(S.ApiError) as cm:   # 作り直しの間は、この文書を選び直せない
            S.relink_doc({"id": tid, "path": old, "baseUpdatedAt": r["updatedAt"]})
        self.assertIn(cm.exception.code, ("busy", "no_file"))
        self.run_job(job)
        d2 = self.doc(tid)
        dst = os.path.join(self.media, "移した先_30fps.mp4")
        self.assertEqual(os.path.normcase(d2["sourcePath"]), os.path.normcase(dst))
        self.assertEqual(d2["updatedAt"], r["updatedAt"])
        self.assertEqual(d2["relinks"][-1]["why"], RL.NORM_WHY)
        self.assertTrue(doc_jobs.public_job(job)["normOk"])
        self.assert_30(dst)
        self.assertTrue(os.path.isfile(moved))

    def test_relink_without_normalizing(self):
        """作り直さない付け替え: まとめて付け替える(normalize: false)・選んだ先がもう 30fps・評価用の文書"""
        for name, old_v, new_v, extra, eval_set in (("bulk", self.v30, self.v60, {"normalize": False}, False),
                                                    ("already30", self.v60, self.v30, {}, False),
                                                    ("eval", self.v30, self.v60, {}, True)):
            with self.subTest(name):
                old = self.copy(old_v, "元%s.mp4" % name)
                tid, d = self.make_doc(old)
                if eval_set:
                    d["evalSet"] = True
                    S.atomic_write(S.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))
                moved = self.copy(new_v, "先%s.mp4" % name)
                r = S.relink_doc(dict({"id": tid, "path": moved, "baseUpdatedAt": d["updatedAt"], "acceptDiff": True}, **extra))
                self.assertIsNone(r["normalizing"])
                self.assertEqual(r["normNote"], "")
                self.assertEqual([n for n in os.listdir(self.media) if "30fps" in n], [])   # 作り直した写しは無い


if __name__ == "__main__":
    unittest.main(verbosity=2)
