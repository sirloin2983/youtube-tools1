#!/usr/bin/env python3
"""評価用の動画の「手が空いたとき少しずつまとめて文字起こし」(ed_evalbatch.py。マスタープラン Q4(b))のテスト。

    py -3.10 -m unittest editor/tests/test_metrics.py     # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest editor/tests/test_evalbatch.py   # これだけ
ffmpeg が必要(2 秒の小さな動画を lavfi で作る)。ワーカーのスレッドは動かさず、テストが待機列のジョブを疑似の認識(TRANSCRIBE_BACKEND=fake)で
その場で動かして「終わった」ことにする(= 偽のワーカー)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import serve as S  # noqa: E402
import ed_evalaudio  # noqa: E402
import ed_evalbatch as EB  # noqa: E402
import ed_jobs  # noqa: E402
import ed_relink  # noqa: E402
import ed_store  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
MEMBER = "評価用データ01_ときのそら"


def _make_video(path, seconds=2):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=%s" % seconds,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % seconds, "-c:v", "mpeg4", "-c:a", "aac", "-shortest", path],
                   check=True, stdin=subprocess.DEVNULL)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class TestEvalBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()    # 作業データの代わり(設定・eval-batch.json・文書)
        self.ev = tempfile.mkdtemp()     # 評価用のフォルダ(動画)
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = os.path.join(self.tmp, "transcripts"), os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")
        os.makedirs(S.TX_DIR)
        self.old_jobs = (dict(ed_jobs._jobs), list(ed_jobs._order))
        ed_jobs._jobs.clear()
        ed_jobs._order.clear()
        self.drain()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off",
                                                "TRANSCRIBE_EVAL_BATCH": "off"})   # 裏のスレッドは動かさない(見回りはテストが呼ぶ)
        self.env.start()
        self.stg = os.path.join(self.ev, ed_relink.EVAL_STAGING)
        self.mem = os.path.join(self.ev, "1_JP", MEMBER)
        os.makedirs(self.stg)
        os.makedirs(self.mem)
        self.settings({"evalDirs": [self.ev]})

    def tearDown(self):
        EB.eb_shutdown()
        self.env.stop()
        self.drain()
        ed_jobs._jobs.clear()
        ed_jobs._jobs.update(self.old_jobs[0])
        ed_jobs._order[:] = self.old_jobs[1]
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.ev, ignore_errors=True)

    # -- 道具
    def drain(self):
        while not ed_jobs._queue.empty():
            ed_jobs._queue.get_nowait()

    def settings(self, d):
        with open(S.SETTINGS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def video(self, folder, name):
        p = os.path.join(folder, name)
        _make_video(p)
        return p

    def staged(self, *names):
        return [self.video(self.stg, n) for n in names]

    def mine(self, *states):
        return [j for j in ed_jobs._jobs.values() if (j.get("spec") or {}).get("evalBatch") and (not states or j["state"] in states)]

    def waiting(self):
        return len([j for j in ed_jobs._jobs.values() if j["state"] in ed_jobs.ACTIVE_STATES])

    def finish(self, job):
        """偽のワーカー: 待機列のジョブを疑似の認識でその場で動かして終わらせる"""
        ed_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def paths_of(self, jobs):
        return sorted(os.path.basename(j["spec"]["sourcePath"]) for j in jobs)

    # -- テスト
    def test_candidates_are_staging_and_untranscribed_names(self):
        self.staged("a.mp4", "b.mp4")
        self.video(self.mem, MEMBER + "_01_未文字起こし.mp4")
        self.video(self.mem, MEMBER + "_02_済.mp4")
        self.video(self.mem, MEMBER + "_03_未.mp4")
        self.video(self.mem, "ただの動画.mp4")
        got = EB.eb_candidates({})
        self.assertEqual(sorted(os.path.basename(p) for p, _t in got), ["a.mp4", "b.mp4", MEMBER + "_01_未文字起こし.mp4"])
        self.assertTrue(all(t is None for _p, t in got))

    def test_keeps_waiting_at_most_two_and_runs_to_the_end(self):
        names = ["a.mp4", "b.mp4", "c.mp4", "d.mp4"]
        self.staged(*names[:3])
        self.video(self.mem, MEMBER + "_01_未文字起こし.mp4")
        total = 4
        st = EB.eval_batch_start()
        self.assertTrue(st["enabled"])
        r = EB.eb_tick("test")
        self.assertEqual((r["added"], r["remaining"]), (2, 2), r)
        self.assertEqual(self.waiting(), 2)
        r = EB.eb_tick("test")   # 待ちが 2 件のまま: 増やさない
        self.assertEqual((r["added"], self.waiting()), (0, 2), r)
        s = EB.eval_batch_status()
        self.assertEqual((s["enqueued"], s["active"], s["remaining"], s["done"]), (2, 2, 2, 0))
        seen_done = []
        for _ in range(10):
            ms = self.mine("queued")
            if not ms:
                break
            seen_done.append(self.finish(ms[0]))   # 1 本終わる → 見回りで補う
            EB.eb_tick("test")
            self.assertLessEqual(self.waiting(), EB.EB_MAX_WAIT)
        self.assertEqual(len(seen_done), total)
        self.assertEqual(len(self.mine()), total)   # 1 本も重ねて入れていない
        self.assertEqual(self.paths_of(self.mine()), sorted(names[:3] + [MEMBER + "_01_未文字起こし.mp4"]))
        s = EB.eval_batch_status()
        self.assertEqual((s["enabled"], s["finished"], s["done"], s["failed"], s["remaining"], s["active"]), (False, True, total, 0, 0, 0), s)
        self.assertEqual(EB.eb_tick("test"), {"skipped": "stopped"})   # 終わったら何も入れない
        self.assertEqual(len(self.mine()), total)

    def test_job_has_eval_mark_and_no_hints(self):
        """評価用の印・ヒントなし(用語集・文脈・置換辞書・学習した置換を渡さない)。処理方式・モデルなどは設定のまま"""
        self.settings({"evalDirs": [self.ev], "glossary": "ホロライブ\nときのそら", "autoDict": True, "autoGloss": True, "autoContext": True,
                       "autoLearned": True, "model": "base", "language": "ja", "quality": "fast", "device": "cpu", "vadMode": "off",
                       "replacements": "あ→い"})
        self.staged("a.mp4")
        self.video(self.mem, MEMBER + "_01_未文字起こし.mp4")
        EB.eval_batch_start()
        EB.eb_tick("test")
        jobs = self.mine()
        self.assertEqual(len(jobs), 2)
        for j in jobs:
            sp = j["spec"]
            self.assertIs(sp["evalSet"], True)
            self.assertEqual((sp["glossary"], sp["glossAuto"], sp["autoDict"], sp["autoLearned"]), ([], [], False, False))
            self.assertEqual(sp["context"], {"members": [], "terms": []})
            self.assertEqual((sp["model"], sp["language"], sp["beam"], sp["device"], sp["vadMode"]), ("base", "ja", 1, "cpu", "off"))   # 編集の設定のまま
            self.assertTrue(sp["whole"])
        done = self.finish(jobs[0])
        self.assertIs(ed_store.read_transcript(done["tid"]).get("evalSet"), True)

    def test_does_not_enqueue_transcribed_or_active(self):
        a, b, c = self.staged("a.mp4", "b.mp4", "c.mp4")
        ed_jobs.add_job(ed_jobs.validate_job({"sourcePath": a, "model": "small"}))   # a: ユーザーが待ちに入れた(別の人のジョブ)
        job_a = next(iter(ed_jobs._jobs.values()))
        self.finish(job_a)   # a は済(文書ができた)
        spec_b = ed_jobs.validate_job({"sourcePath": b, "model": "small", "evalSet": True})
        self.finish(ed_jobs.add_job(spec_b))   # b も済
        EB.eval_batch_start()
        r = EB.eb_tick("test")
        self.assertEqual(r["added"], 1, r)
        self.assertEqual(self.paths_of(self.mine()), ["c.mp4"])
        self.assertEqual(EB.eval_batch_status()["remaining"], 0)

    def test_rowless_doc_gets_into_doc(self):
        """文字起こしせずに開いた動画(行の無い文書)は、その文書へ入れる(文書が2つにならない)"""
        (a,) = self.staged("a.mp4")
        tid = ed_store.open_video({"path": a})["id"]
        EB.eval_batch_start()
        EB.eb_tick("test")
        (j,) = self.mine()
        self.assertEqual(j["spec"]["intoDoc"], tid)
        self.finish(j)
        self.assertEqual(len([n for n in os.listdir(S.TX_DIR) if n.endswith(".json") and ".edit" not in n and ".words" not in n and ".asr" not in n]), 1)

    def test_user_job_makes_it_wait(self):
        """ユーザーのジョブが動いている・待っているときは自分の分を増やさない。終われば再開する"""
        (a,) = self.staged("a.mp4")
        other = self.video(self.mem, "ユーザーの動画.mp4")
        user = ed_jobs.add_job(ed_jobs.validate_job({"sourcePath": other, "model": "small"}))
        EB.eval_batch_start()
        r = EB.eb_tick("test")
        self.assertEqual(r["added"], 0)
        self.assertIn("ほかのジョブ", r["deferred"])
        self.assertIn("ほかのジョブ", EB.eval_batch_status()["deferred"])
        self.assertEqual(self.mine(), [])
        self.finish(user)
        r = EB.eb_tick("test")
        self.assertEqual(r["added"], 1, r)
        self.assertIsNone(EB.eval_batch_status()["deferred"])

    def test_user_job_added_while_running_blocks_further_adds(self):
        self.staged("a.mp4", "b.mp4", "c.mp4", "d.mp4")
        EB.eval_batch_start()
        EB.eb_tick("test")
        self.assertEqual(len(self.mine()), 2)
        other = self.video(self.mem, "ユーザーの動画.mp4")
        user = ed_jobs.add_job(ed_jobs.validate_job({"sourcePath": other, "model": "small"}))   # ユーザーの操作が割り込めた
        self.finish(self.mine("queued")[0])
        r = EB.eb_tick("test")
        self.assertEqual(r["added"], 0, r)   # ユーザーのジョブが待っている間は増やさない
        self.assertEqual(len(self.mine()), 2)
        self.finish(user)
        self.assertEqual(EB.eb_tick("test")["added"], 1)

    def test_stop_cancels_waiting_but_not_running_and_stays_stopped(self):
        self.staged("a.mp4", "b.mp4", "c.mp4")
        EB.eval_batch_start()
        EB.eb_tick("test")
        j1, j2 = sorted(self.mine(), key=lambda j: j["createdAt"])
        j1["state"] = "running"   # 1 本は動いている
        s = EB.eval_batch_stop()
        self.assertFalse(s["enabled"])
        self.assertFalse(s["finished"])
        self.assertEqual((j1["state"], j2["state"]), ("running", "cancelled"))   # 動いている分は最後まで・待っている分は取り消す
        self.assertEqual(EB.eb_tick("test"), {"skipped": "stopped"})
        self.assertEqual(len(self.mine()), 2)
        # 止めたあとの再開: 取り消した分もやり直す
        j1["state"] = "done"
        EB.eval_batch_start()
        r = EB.eb_tick("test")
        self.assertGreaterEqual(r["added"], 1, r)
        self.assertEqual(EB.eval_batch_status()["enqueued"], r["added"])   # 数え直している

    def test_restart_continues_when_enabled(self):
        self.staged("a.mp4", "b.mp4", "c.mp4")
        EB.eval_batch_start()
        EB.eb_tick("test")
        with open(EB.eb_path(), encoding="utf-8") as f:
            self.assertIs(json.load(f)["enabled"], True)
        # 起動し直し: ジョブの表・待機列は空(プロセスが入れ替わった)。状態ファイルの enabled で続く
        ed_jobs._jobs.clear()
        ed_jobs._order.clear()
        self.drain()
        self.assertTrue(EB.eval_batch_status()["enabled"])
        r = EB.eb_tick("after-restart")
        self.assertEqual(r["added"], 2, r)
        self.assertEqual(len(self.mine()), 2)
        # 裏のスレッドも状態ファイルを見て動く(start を呼ばなくても)
        ed_jobs._jobs.clear()
        self.drain()
        with mock.patch.dict(os.environ, {"TRANSCRIBE_EVAL_BATCH": ""}):
            self.assertIsNotNone(EB.eb_start_background(first_delay=0.05, interval=0.05))
        for _ in range(100):
            if self.mine():
                break
            time.sleep(0.05)
        EB.eb_shutdown()
        self.assertEqual(len(self.mine()), 2)
        self.assertEqual(self.waiting(), 2)

    def test_failed_video_is_retried_twice_then_skipped(self):
        a, b = self.staged("a.mp4", "b.mp4")
        self.staged("c.mp4")
        EB.eval_batch_start()
        for _ in range(3):
            EB.eb_tick("test")
            for j in self.mine("queued"):
                if j["spec"]["sourceName"] == "a.mp4":
                    j["state"], j["error"] = "error", "テストの失敗"   # a だけ失敗する
                else:
                    self.finish(j)
        names = [os.path.basename(j["spec"]["sourcePath"]) for j in sorted(self.mine(), key=lambda j: j["createdAt"])]
        self.assertEqual(names.count("a.mp4"), EB.EB_MAX_FAILS)   # 2 回までやり直して、それ以降は入れない
        self.assertEqual((names.count("b.mp4"), names.count("c.mp4")), (1, 1))
        EB.eb_tick("test")
        s = EB.eval_batch_status()
        self.assertEqual((s["failed"], s["done"], s["enabled"], s["finished"]), (1, 2, False, True), s)
        self.assertEqual(s["lastError"]["message"], "テストの失敗")

    def test_user_cancelled_job_is_not_retried(self):
        self.staged("a.mp4", "b.mp4")
        EB.eval_batch_start()
        EB.eb_tick("test")
        a = next(j for j in self.mine() if j["spec"]["sourceName"] == "a.mp4")
        ed_jobs.cancel_job(a["id"])   # ユーザーが処理状況から取り消した
        self.finish(next(j for j in self.mine("queued")))
        EB.eb_tick("test")
        self.assertEqual(self.paths_of(self.mine()), ["a.mp4", "b.mp4"])   # a は入れ直さない

    def test_unreadable_video_is_skipped_and_next_goes_in(self):
        a, b = self.staged("a.mp4", "b.mp4")
        real = ed_jobs.validate_job

        def fake(req):
            if req["sourcePath"] == a:
                raise S.ApiError("too_long", "1回に処理できるのは6時間までです", 400)
            return real(req)
        EB.eval_batch_start()
        with mock.patch.object(ed_jobs, "validate_job", side_effect=fake):
            r = EB.eb_tick("test")
            r2 = EB.eb_tick("test")
        self.assertEqual((r["added"], r2["added"]), (1, 0), (r, r2))
        self.assertEqual(self.paths_of(self.mine()), ["b.mp4"])
        s = EB.eval_batch_status()
        self.assertEqual((s["failed"], s["lastError"]["src"]), (1, "a.mp4"))

    def test_no_eval_dirs(self):
        self.staged("a.mp4")
        self.settings({})
        with self.assertRaises(S.ApiError) as cm:
            EB.eval_batch_start()
        self.assertEqual(cm.exception.code, "no_eval_dirs")
        self.assertFalse(EB.eval_batch_status()["enabled"])
        # 動いている途中でドライブが見えなくなっても、止めたことにも終わったことにもしない
        self.settings({"evalDirs": [self.ev]})
        EB.eval_batch_start()
        self.settings({})
        r = EB.eb_tick("test")
        self.assertEqual(r, {"skipped": "no_eval_dirs"})
        s = EB.eval_batch_status()
        self.assertTrue(s["enabled"] and not s["finished"])
        self.assertEqual(self.mine(), [])
        self.settings({"evalDirs": [self.ev]})
        self.assertEqual(EB.eb_tick("test")["added"], 1)

    def test_other_process_holding_lock_skips(self):
        self.staged("a.mp4")
        EB.eval_batch_start()
        with ed_evalaudio._file_lock(EB.eb_lock_path()) as got:   # 別のプロセスが見回り中のつもり
            self.assertTrue(got)
            self.assertEqual(EB.eb_tick("test"), {"skipped": "running"})
        self.assertEqual(self.mine(), [])
        self.assertEqual(EB.eb_tick("test")["added"], 1)

    def test_organizing_makes_it_wait(self):
        self.staged("a.mp4")
        EB.eval_batch_start()
        with ed_relink._evalorg_lock:
            r = EB.eb_tick("test")
        self.assertEqual(r["added"], 0)
        self.assertIn("整理", r["deferred"])
        self.assertEqual(EB.eb_tick("test")["added"], 1)

    def test_start_is_idempotent_and_status_shape(self):
        self.staged("a.mp4", "b.mp4", "c.mp4")
        s0 = EB.eval_batch_status()
        self.assertEqual((s0["enabled"], s0["enqueued"], s0["active"], s0["finished"]), (False, 0, 0, False))
        EB.eval_batch_start()
        EB.eb_tick("test")
        enq = EB.eval_batch_status()["enqueued"]
        s = EB.eval_batch_start()   # もう一度押しても数え直さない
        self.assertEqual((s["enabled"], s["enqueued"]), (True, enq))
        for k in ("enabled", "running", "enqueued", "remaining", "active", "done", "failed", "finished", "deferred", "lastError", "titles"):
            self.assertIn(k, s)
        self.assertEqual(len(s["titles"]), 2)


if __name__ == "__main__":
    unittest.main()
