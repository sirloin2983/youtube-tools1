#!/usr/bin/env python3
"""評価用の動画の「手が空いたとき少しずつまとめて文字起こし」(eval/drill/evalbatch.py。RS4-2 まで editor/ed_evalbatch.py。マスタープラン Q4(b))のテスト。

    py -3.10 -m unittest src/editor/tests/test_metrics.py     # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest src/editor/tests/test_evalbatch.py   # これだけ
ffmpeg が必要(2 秒の小さな動画を lavfi で作る)。ワーカーのスレッドは動かさず、テストが待機列のジョブを疑似の認識(TRANSCRIBE_BACKEND=fake)で
その場で動かして「終わった」ことにする(= 偽のワーカー)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
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
from eval.drill import evalbatch as EB  # noqa: E402   (RS4-2 に editor/ed_evalbatch.py から)
from human.proof import doc_jobs  # noqa: E402
from human.proof import store  # noqa: E402
from ytt import jobs as ytt_jobs  # noqa: E402
from eval.drill import folders as EF  # noqa: E402   評価用のフォルダの整理(RS3-E7 に ed_relink から)

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
        self.old_jobs = (dict(ytt_jobs._jobs), list(ytt_jobs._order))
        ytt_jobs._jobs.clear()
        ytt_jobs._order.clear()
        self.drain()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off",
                                                "TRANSCRIBE_EVAL_BATCH": "off",   # 裏のスレッドは動かさない(見回りはテストが呼ぶ)
                                                "TRANSCRIBE_AUTO_DIARIZE": "off"})   # 文字起こしの続きの話者の自動判別・後追いは test_autodiar で(ここは文字起こしの数え方だけ)
        self.env.start()
        self.stg = os.path.join(self.ev, EF.EVAL_STAGING)
        self.mem = os.path.join(self.ev, "1_JP", MEMBER)
        os.makedirs(self.stg)
        os.makedirs(self.mem)
        self.settings({"evalDirs": [self.ev]})

    def tearDown(self):
        EB.eb_shutdown()
        self.env.stop()
        self.drain()
        ytt_jobs._jobs.clear()
        ytt_jobs._jobs.update(self.old_jobs[0])
        ytt_jobs._order[:] = self.old_jobs[1]
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.ev, ignore_errors=True)

    # -- 道具
    def drain(self):
        while not ytt_jobs._queue.empty():
            ytt_jobs._queue.get_nowait()

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
        return [j for j in ytt_jobs._jobs.values() if (j.get("spec") or {}).get("evalBatch") and (not states or j["state"] in states)]

    def waiting(self):
        return len([j for j in ytt_jobs._jobs.values() if j["state"] in ytt_jobs.ACTIVE_STATES])

    def finish(self, job):
        """偽のワーカー: 待機列のジョブを疑似の認識でその場で動かして終わらせる"""
        doc_jobs.run_job(job)
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
        self.assertIs(store.read_transcript(done["tid"]).get("evalSet"), True)

    def test_does_not_enqueue_transcribed_or_active(self):
        a, b, c = self.staged("a.mp4", "b.mp4", "c.mp4")
        ytt_jobs.add_job(doc_jobs.validate_job({"sourcePath": a, "model": "small"}))   # a: ユーザーが待ちに入れた(別の人のジョブ)
        job_a = next(iter(ytt_jobs._jobs.values()))
        self.finish(job_a)   # a は済(文書ができた)
        spec_b = doc_jobs.validate_job({"sourcePath": b, "model": "small", "evalSet": True})
        self.finish(ytt_jobs.add_job(spec_b))   # b も済
        EB.eval_batch_start()
        r = EB.eb_tick("test")
        self.assertEqual(r["added"], 1, r)
        self.assertEqual(self.paths_of(self.mine()), ["c.mp4"])
        self.assertEqual(EB.eval_batch_status()["remaining"], 0)

    def test_rowless_doc_gets_into_doc(self):
        """文字起こしせずに開いた動画(行の無い文書)は、その文書へ入れる(文書が2つにならない)"""
        (a,) = self.staged("a.mp4")
        tid = store.open_video({"path": a})["id"]
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
        user = ytt_jobs.add_job(doc_jobs.validate_job({"sourcePath": other, "model": "small"}))
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
        user = ytt_jobs.add_job(doc_jobs.validate_job({"sourcePath": other, "model": "small"}))   # ユーザーの操作が割り込めた
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
        ytt_jobs._jobs.clear()
        ytt_jobs._order.clear()
        self.drain()
        self.assertTrue(EB.eval_batch_status()["enabled"])
        r = EB.eb_tick("after-restart")
        self.assertEqual(r["added"], 2, r)
        self.assertEqual(len(self.mine()), 2)
        # 裏のスレッドも状態ファイルを見て動く(start を呼ばなくても)
        ytt_jobs._jobs.clear()
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
        ytt_jobs.cancel_job(a["id"])   # ユーザーが処理状況から取り消した
        self.finish(next(j for j in self.mine("queued")))
        EB.eb_tick("test")
        self.assertEqual(self.paths_of(self.mine()), ["a.mp4", "b.mp4"])   # a は入れ直さない

    def test_unreadable_video_is_skipped_and_next_goes_in(self):
        a, b = self.staged("a.mp4", "b.mp4")
        real = doc_jobs.validate_job

        def fake(req):
            if req["sourcePath"] == a:
                raise S.ApiError("too_long", "1回に処理できるのは6時間までです", 400)
            return real(req)
        EB.eval_batch_start()
        with mock.patch.object(doc_jobs, "validate_job", side_effect=fake):
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
        with EB._file_lock(EB.eb_lock_path()) as got:   # 別のプロセスが見回り中のつもり
            self.assertTrue(got)
            with EB._file_lock(EB.eb_lock_path()) as got2:   # 同じ印は二重に取れない
                self.assertFalse(got2)
            self.assertEqual(EB.eb_tick("test"), {"skipped": "running"})
        self.assertEqual(self.mine(), [])
        self.assertEqual(EB.eb_tick("test")["added"], 1)

    def test_organizing_makes_it_wait(self):
        self.staged("a.mp4")
        EB.eval_batch_start()
        with EF._evalorg_lock:
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

    # -- 未確認の評価用の作り直し(eval_batch_redo。2026-10-04 ユーザー承認)
    def eval_doc(self, name, old=True):
        """評価用として文字起こし済みの文書(人の手が入っていない)。old = 更新を 1 時間前にずらす(直近 10 分の除外に当たらない)"""
        p = os.path.join(self.stg, name)
        _make_video(p, 9)   # 疑似の認識は 4 秒ごとに 1 行 = 3 行
        job = self.finish(ytt_jobs.add_job(doc_jobs.validate_job({"sourcePath": p, "model": "small", "evalSet": True})))
        if old:
            self.edit_doc(job["tid"], lambda d: None)
        return job["tid"]

    def edit_doc(self, tid, fn, old=True):
        """文書をじかに書き換える(fn(doc))。old = updatedAt を 1 時間前に"""
        d = store.read_transcript(tid)
        fn(d)
        if old:
            d["updatedAt"] = int(time.time() * 1000) - 3600 * 1000
        with open(store.tx_path(tid), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        return d

    def auto_speakers(self, tid, name="話者1", by=None):
        """自動の判別が付けたのと同じ形(全行を S1・diar.json の latest.auto と行ごとの割り当て)"""
        def fn(d):
            d["speakers"] = [{"id": "S1", "name": name, "color": "#123456"}]
            for g in d["segments"]:
                g["speaker"] = "S1"
        d = self.edit_doc(tid, fn)
        voices = {"checked": True, "speakers": {"S1": {"decided": name, "by": by}} if by else {}}
        S.write_diar(tid, {"at": int(time.time() * 1000), "engine": {"name": "fake"}, "rows": {g["id"]: {"label": 0, "speaker": "S1"} for g in d["segments"]},
                           "labelMap": {"0": "S1"}, "voices": voices, "auto": {"eval": True, "contextName": None}})

    def redo_jobs(self, *states):
        return [j for j in self.mine(*states) if j["spec"].get("evalRedo")]

    def test_redo_untouched_rules(self):
        tid = self.eval_doc("a.mp4")
        doc = store.read_transcript(tid)
        why = lambda d, **kw: EB.eb_redo_why(tid, d, **kw)   # noqa: E731
        cp = lambda: json.loads(json.dumps(doc))   # noqa: E731
        self.assertIsNone(why(doc))   # 手つかず
        d = cp(); d["segments"][0]["proofed"] = True
        self.assertEqual(why(d), "proofed")   # 校正済みの行がある
        d = cp(); d["segments"][0]["text"] += "あ"
        self.assertEqual(why(d), "text")   # 文字を直した
        d = cp(); d["segments"][0]["end"] = round(d["segments"][0]["end"] - 0.1, 2)
        self.assertEqual(why(d), "time")   # 時刻を直した
        d = cp(); d["segments"][0]["end"] = round(d["segments"][0]["end"] + 0.004, 3)
        self.assertIsNone(why(d))   # 0.005 秒以内は同じ
        d = cp(); d["segments"].pop()
        self.assertEqual(why(d), "rows")   # 行を消した
        d = cp(); d["segments"][0]["tags"] = ["overlap"]
        self.assertEqual(why(d), "tags")
        d = cp(); d["evalReviewed"] = {"at": 1, "rows": 1, "durationSec": 2}
        self.assertEqual(why(d), "reviewed")   # 確かめ済み
        d = cp(); d.pop("original")
        self.assertEqual(why(d), "noOriginal")   # 比べられないものは作り直さない
        d = cp(); d["updatedAt"] = int(time.time() * 1000) - 60 * 1000
        self.assertEqual(why(d), "recent")   # 直近 10 分に更新した
        d = cp(); d["effort"] = {"lastAt": int(time.time() * 1000)}
        self.assertEqual(why(d), "recent")   # 開いて操作していた(updatedAt は動かない)
        self.assertEqual(why(doc, busy={tid}), "busy")   # ジョブの最中
        d = cp(); d["evalSet"] = False
        self.assertEqual(why(d), "notEval")
        # 人が付けた話者(diar.json が無い)
        d = cp(); d["speakers"] = [{"id": "S1", "name": "ときのそら"}]; d["segments"][0]["speaker"] = "S1"
        self.assertEqual(why(d), "speaker")
        # 自動の判別のまま(仮の名前・覚えた声/動画の手がかりで付いた名前)は手つかず
        self.auto_speakers(tid)
        self.assertIsNone(why(store.read_transcript(tid)))
        self.auto_speakers(tid, "ときのそら", by="context")
        self.assertIsNone(why(store.read_transcript(tid)))
        d = store.read_transcript(tid); d["segments"][1]["speaker"] = ""
        self.assertEqual(why(d), "speaker")   # 人が行の話者を選び直した(外した)
        d = store.read_transcript(tid)
        for g in d["segments"]:
            g["speaker"] = ""
        self.assertEqual(why(d), "speaker")   # 判別のあとで人が全部の話者を外した
        d = store.read_transcript(tid); d["speakers"][0]["name"] = "AZKi"
        self.assertEqual(why(d), "speaker")   # 人が名前を変えた
        self.auto_speakers(tid, "ときのそら", by="request")
        self.assertEqual(why(store.read_transcript(tid)), "speaker")   # 依頼の名前(人の入力)は迷うので手を入れた側
        S.write_diar(tid, dict(S.read_diar(tid)["latest"], auto=None))
        self.assertEqual(why(store.read_transcript(tid)), "speaker")   # 人が始めた判別

    def test_redo_dry_run_counts_and_does_nothing(self):
        a = self.eval_doc("a.mp4")
        b = self.eval_doc("b.mp4")
        c = self.eval_doc("c.mp4")
        self.edit_doc(b, lambda d: d["segments"][0].update(proofed=True))
        self.edit_doc(c, lambda d: d.update(evalReviewed={"at": 1, "rows": 1, "durationSec": 2}))
        before = store.read_transcript(a)
        r = EB.eval_batch_redo({"dryRun": True})
        self.assertEqual((r["targets"], r["touched"], r["reasons"]), (1, 1, {"proofed": 1, "reviewed": 1}), r)
        self.assertEqual(r["labels"]["proofed"], "校正済みの行がある")
        self.assertEqual(EB.eval_batch_redo({})["dryRun"], True)   # 既定は数えるだけ
        self.assertFalse(EB.eval_batch_status()["enabled"])
        self.assertEqual(self.mine(), [])
        self.assertEqual(store.read_transcript(a), before)

    def test_redo_replaces_in_place_keeps_history_and_record(self):
        tid = self.eval_doc("a.mp4")
        def old_output(d):   # 直す前の機械の出力(人の手は入っていない = segments と original が同じ)
            d["model"] = "large-v3"
            for g, o in zip(d["segments"], d["original"]):
                g["text"] = o["text"] = "古い文"
        self.edit_doc(tid, old_output)
        n_docs = len(store._tids())
        self.settings({"evalDirs": [self.ev], "model": "base"})   # 今の編集の設定
        r = EB.eval_batch_redo({"dryRun": False})
        self.assertEqual((r["targets"], r["added"]), (1, 1), r)
        st = EB.eval_batch_status()
        self.assertEqual((st["enabled"], st["redoWaiting"]), (True, 1))
        t = EB.eb_tick("test")
        self.assertEqual(t["redoAdded"], 1, t)
        (job,) = self.redo_jobs()
        self.assertEqual((job["spec"]["intoDoc"], job["spec"]["tid"], job["spec"]["model"], job["spec"]["evalSet"]), (tid, tid, "base", True))
        self.assertEqual(job["spec"]["glossary"], [])   # 評価用 = ヒントなし
        self.assertIn(tid, S._busy_tids())   # 待っている間は処理中(ドリルが出さない)
        self.finish(job)
        self.assertEqual((job["tid"], job.get("redoSkipped")), (tid, None))
        self.assertEqual(len(store._tids()), n_docs)   # 新しい文書は作らない
        d = store.read_transcript(tid)
        self.assertEqual(d["model"], "base")
        self.assertTrue(d["segments"] and all(g["text"].startswith("テスト文") for g in d["segments"]))
        self.assertEqual([o["text"] for o in d["original"]], [g["text"] for g in d["segments"]])
        self.assertIs(d["evalSet"], True)
        runs = d["recognition"]["runs"]
        self.assertNotIn("kind", runs[0])   # 新しい最初の認識の記録が先頭
        self.assertEqual(runs[0]["model"], "base")
        rec = [x for x in runs if x.get("kind") == "evalRedo"]
        self.assertEqual(len(rec), 1)
        self.assertTrue(rec[0]["replaced"] and all(o["text"] == "古い文" for o in rec[0]["replaced"]))   # 前の機械の出力を残す
        self.assertEqual(rec[0]["replacedRun"]["model"], "small")
        self.assertIsNone(EB.eb_redo_why(tid, dict(d, updatedAt=1)))   # 作り直した結果も手つかず(また作り直せる)
        # 以前の版に戻す で戻せる
        hist = store.list_history(tid)
        self.assertTrue(hist)
        old = store.restore_history(tid, hist[0]["ts"])
        self.assertEqual({g["text"] for g in old["segments"]}, {"古い文"})
        # 見回りが結果を写す・残りが無ければ終わる
        EB.eb_tick("test")
        st = EB.eval_batch_status()
        self.assertEqual((st["redoDone"], st["redoWaiting"], st["enabled"], st["finished"]), (1, 0, False, True), st)

    def test_redo_runs_auto_diarize_again(self):
        tid = self.eval_doc("a.mp4")
        self.auto_speakers(tid)
        with mock.patch.dict(os.environ, {"TRANSCRIBE_AUTO_DIARIZE": ""}):
            EB.eval_batch_redo({"dryRun": False})
            EB.eb_tick("test")
            (job,) = self.redo_jobs()
            self.finish(job)
            d = store.read_transcript(tid)
            self.assertEqual(d["speakers"], [])   # 話者は消した
            self.assertNotIn("diarization", d)
            self.assertFalse(any(g.get("speaker") for g in d["segments"]))
            dj = [j for j in ytt_jobs._jobs.values() if j.get("kind") == "diarize" and j["spec"].get("tid") == tid and j["state"] == "queued"]
            self.assertEqual(len(dj), 1)   # 評価用の自動の判別をもう一度
            self.assertTrue(dj[0]["spec"]["auto"] and dj[0]["spec"]["evalBatch"])
            doc_jobs.run_job(dj[0])
            self.assertEqual(dj[0]["state"], "done", dj[0].get("error"))
        d = store.read_transcript(tid)
        self.assertTrue(d["speakers"] and any(g.get("speaker") for g in d["segments"]))
        self.assertTrue(d["diarization"].get("auto"))

    def test_redo_skips_when_touched_before_start(self):
        tid = self.eval_doc("a.mp4")
        EB.eval_batch_redo({"dryRun": False})
        EB.eb_tick("test")
        (job,) = self.redo_jobs()
        doc = store.read_transcript(tid)   # 待っている間に人が校正した
        doc["segments"][0]["proofed"] = True
        store.save_transcript(tid, dict(doc, baseUpdatedAt=doc["updatedAt"]))
        doc_jobs.run_job(job)
        self.assertEqual((job["state"], job["redoSkipped"]), ("done", "proofed"))
        self.assertIn("作り直しませんでした", job["phase"])
        d = store.read_transcript(tid)
        self.assertTrue(d["segments"][0].get("proofed"))   # 書いていない
        self.assertFalse(any(x.get("kind") for x in d["recognition"]["runs"]))
        EB.eb_tick("test")
        self.assertEqual(EB.eval_batch_status()["redoSkipped"], 1)

    def test_redo_skips_when_touched_while_recognizing(self):
        tid = self.eval_doc("a.mp4")
        EB.eval_batch_redo({"dryRun": False})
        EB.eb_tick("test")
        (job,) = self.redo_jobs()
        real = EB.eb_redo_skip_at_start

        def start_then_edit(j):   # 動き出したあと(認識の間)に人が画面で直して保存した
            r = real(j)
            doc = store.read_transcript(tid)
            doc["segments"][0]["text"] = "人が直した"
            store.save_transcript(tid, dict(doc, baseUpdatedAt=doc["updatedAt"]))
            return r
        with mock.patch.object(EB, "eb_redo_skip_at_start", side_effect=start_then_edit):
            doc_jobs.run_job(job)
        self.assertEqual((job["state"], job["redoSkipped"]), ("done", "changed"))
        self.assertEqual(store.read_transcript(tid)["segments"][0]["text"], "人が直した")   # 人の直しは消さない

    def test_redo_waits_at_most_two_and_stop_clears(self):
        tids = [self.eval_doc(n) for n in ("a.mp4", "b.mp4", "c.mp4")]
        r = EB.eval_batch_redo({"dryRun": False})
        self.assertEqual(r["added"], 3)
        self.assertEqual(EB.eval_batch_redo({"dryRun": True})["reasons"].get("queued"), 3)   # もう待っているものは数え直さない
        self.assertEqual(EB.eb_tick("test")["redoAdded"], 2)
        self.assertEqual(len(self.redo_jobs("queued")), 2)
        self.assertEqual(EB.eval_batch_status()["redoWaiting"], 3)
        s = EB.eval_batch_stop()
        self.assertEqual((s["enabled"], s["redoWaiting"]), (False, 0))   # 止めると作り直しの待ちも止まる
        self.assertEqual(self.redo_jobs("queued"), [])
        self.assertEqual(EB.eb_tick("test"), {"skipped": "stopped"})
        for t in tids:
            self.assertTrue(all(g["text"].startswith("テスト文") for g in store.read_transcript(t)["segments"]))

    # -- 1 本ずつの作り直し(eval_batch_redo_one。2026-10-05 ユーザー要望)
    def one(self, tid, force=None, base=None):
        d = store.read_transcript(tid)
        req = {"id": tid, "baseUpdatedAt": d["updatedAt"] if base is None else base}
        if force is not None:
            req["force"] = force
        return EB.eval_batch_redo_one(req)

    def one_err(self, tid, **kw):
        with self.assertRaises(S.ApiError) as cm:
            self.one(tid, **kw)
        return cm.exception

    def one_jobs(self, *states):
        return [j for j in ytt_jobs._jobs.values() if ((j.get("spec") or {}).get("evalRedo") or {}).get("one") and (not states or j["state"] in states)]

    def test_redo_one_untouched_runs_now_with_current_settings(self):
        tid = self.eval_doc("a.mp4")
        # 開いて操作した直後(直近 10 分)でも押せる・まとめての文字起こしは止まったまま
        self.edit_doc(tid, lambda d: d.update(effort={"lastAt": int(time.time() * 1000)}), old=False)
        self.settings({"evalDirs": [self.ev], "model": "base"})
        r = self.one(tid)
        self.assertTrue(r["ok"])
        self.assertFalse(r["forced"])
        (job,) = self.one_jobs("queued")   # 見回りを待たずに待機列へ
        self.assertEqual(r["job"]["id"], job["id"])
        self.assertTrue(r["job"]["redo"] and r["job"]["redoOne"])
        sp = job["spec"]
        self.assertEqual((sp["intoDoc"], sp["tid"], sp["model"], sp["evalSet"], sp["glossary"]), (tid, tid, "base", True, []))
        self.assertNotIn("evalBatch", sp)   # ユーザーのジョブ(まとめての文字起こしの待ちの数に入れない)
        self.assertFalse(EB.eval_batch_status()["enabled"])
        self.assertIn(tid, S._busy_tids())
        self.assertEqual(self.one_err(tid).code, "busy")   # 2 回押しても 1 本だけ
        self.assertEqual(len(self.one_jobs()), 1)
        self.finish(job)
        self.assertEqual((job["tid"], job.get("redoSkipped")), (tid, None))
        d = store.read_transcript(tid)
        self.assertEqual(d["model"], "base")
        self.assertEqual([x.get("kind") for x in d["recognition"]["runs"]].count("evalRedo"), 1)
        self.assertTrue(store.list_history(tid))   # 前の版は「以前の版に戻す」に

    def test_redo_one_refuses(self):
        tid = self.eval_doc("a.mp4")
        e = self.one_err(tid, base=1)
        self.assertEqual((e.code, e.status), ("conflict", 409))
        with self.assertRaises(S.ApiError) as cm:
            EB.eval_batch_redo_one({"id": tid})
        self.assertEqual(cm.exception.code, "bad_request")
        self.edit_doc(tid, lambda d: d.update(evalReviewed={"at": 1, "rows": 1, "durationSec": 2}))
        e = self.one_err(tid, force=True)
        self.assertEqual((e.code, e.status), ("reviewed", 400))   # 確かめ済みは force でも断る
        self.assertIn("確かめ済みを取り消して", e.message)
        self.edit_doc(tid, lambda d: (d.pop("evalReviewed"), d.update(evalSet=False)))
        self.assertEqual(self.one_err(tid).code, "not_eval")
        self.assertEqual(self.one_jobs(), [])

    def test_redo_one_touched_needs_force(self):
        tid = self.eval_doc("a.mp4")
        def touch(d):
            d["segments"][0]["proofed"] = True
            d["segments"][1]["text"] = "人が直した"
        self.edit_doc(tid, touch)
        e = self.one_err(tid)
        self.assertEqual((e.code, e.status), ("touched", 409))
        self.assertEqual((e.extra["why"], e.extra["rows"], e.extra["total"]), ("proofed", 2, 3), e.extra)
        self.assertEqual(e.extra["label"], "校正済みの行がある")
        self.assertEqual(self.one_jobs(), [])
        r = self.one(tid, force=True)
        self.assertTrue(r["forced"])
        (job,) = self.one_jobs("queued")
        self.assertTrue(job["spec"]["evalRedo"]["force"])
        self.finish(job)
        self.assertIsNone(job.get("redoSkipped"))
        d = store.read_transcript(tid)
        self.assertTrue(all(g["text"].startswith("テスト文") and not g.get("proofed") for g in d["segments"]))   # 置き換わった
        old = store.restore_history(tid, store.list_history(tid)[0]["ts"])   # 以前の版に戻すで戻せる
        self.assertEqual(old["segments"][1]["text"], "人が直した")

    def test_redo_one_not_written_when_changed_after_press(self):
        tid = self.eval_doc("a.mp4")
        self.edit_doc(tid, lambda d: d["segments"][0].update(proofed=True))
        self.one(tid, force=True)
        (job,) = self.one_jobs("queued")
        doc = store.read_transcript(tid)   # 押したあと(待っている間)に直した
        doc["segments"][1]["text"] = "押したあとに直した"
        store.save_transcript(tid, dict(doc, baseUpdatedAt=doc["updatedAt"]))
        doc_jobs.run_job(job)
        self.assertEqual((job["state"], job["redoSkipped"]), ("done", "pressedChanged"))
        self.assertIn("作り直しませんでした(押したあとに直されたため)", job["phase"])
        self.assertEqual(store.read_transcript(tid)["segments"][1]["text"], "押したあとに直した")
        # 認識の間に直した(書く直前の確かめ)
        self.one(tid, force=True)
        (job,) = self.one_jobs("queued")
        real = EB.eb_redo_skip_at_start

        def start_then_edit(j):
            r = real(j)
            d = store.read_transcript(tid)
            d["segments"][2]["text"] = "認識の間に直した"
            store.save_transcript(tid, dict(d, baseUpdatedAt=d["updatedAt"]))
            return r
        with mock.patch.object(EB, "eb_redo_skip_at_start", side_effect=start_then_edit):
            doc_jobs.run_job(job)
        self.assertEqual((job["state"], job["redoSkipped"]), ("done", "pressedChanged"))
        d = store.read_transcript(tid)
        self.assertEqual((d["segments"][1]["text"], d["segments"][2]["text"]), ("押したあとに直した", "認識の間に直した"))
        self.assertFalse(any(x.get("kind") == "evalRedo" for x in d["recognition"]["runs"]))

    def test_redo_needs_eval_dirs_only_when_running(self):
        self.eval_doc("a.mp4")
        self.settings({})
        r = EB.eval_batch_redo({"dryRun": True})   # 数えるのは評価用のフォルダが無くてもできる(文書の印で見る)
        self.assertEqual(r["targets"], 1)
        with self.assertRaises(S.ApiError) as cm:
            EB.eval_batch_redo({"dryRun": False})
        self.assertEqual(cm.exception.code, "no_eval_dirs")


if __name__ == "__main__":
    unittest.main()
