"""src/friendapp/upgrade.py(更新の決まり: いつ入れ替える・重要な直し・確かめと戻し・戻す印・取り消し・心拍・直しの版のやり直し・固まり)の境目のテスト。
玄関は tests/friendapp/test_server.py の Base(② は偽物・一時フォルダ)。本物の Dropbox・exe・作業データには触らない。
入口は起こさない(YTT_DATA_DIR は要らない): 下の server.py は版のフォルダの形だけを作る空のファイル。
リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_upgrade.py"""
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # tests/friendapp(test_server の Base)
import test_server as T  # noqa: E402
from friendapp import upgrade as U  # noqa: E402
from ytt import version as _version  # noqa: E402

VER = _version.VERSION
NEWER = "999.0.0"
RID = "20261025-010203-abcdef"


class WaitReasonTest(unittest.TestCase):
    def st(self, **kw):
        d = {"recording": 0, "making": 0, "waiting": 0, "reserved": 0, "setup": False}
        d.update(kw)
        return d

    def test_table(self):
        """ふだん = 全部が空いたら・重要 = 録画と処理中の 1 本だけ待つ・今すぐ = 録画だけ待つ・1 分増えない録画は待たない"""
        w = U.wait_reason
        self.assertEqual(w(self.st(), U.NORMAL), "")
        self.assertEqual(w(self.st(waiting=1), U.NORMAL), U.BUSY)
        self.assertEqual(w(self.st(reserved=1), U.NORMAL), U.RECORDING)
        self.assertEqual(w(self.st(), U.NORMAL, busy=True), U.BUSY)   # Dropbox の上げ下ろし
        self.assertEqual(w(self.st(waiting=2, reserved=1), U.IMPORTANT), "")   # 順番待ちだけなら入れ替えて続きから
        self.assertEqual(w(self.st(making=1), U.IMPORTANT), U.BUSY)
        self.assertEqual(w(self.st(recording=1), U.IMPORTANT), U.RECORDING)
        self.assertEqual(w(self.st(recording=1), U.IMPORTANT, stalled=1), "")
        self.assertEqual(w(self.st(making=1, setup=True), U.NOW), "")
        self.assertEqual(w(self.st(recording=1), U.NOW), U.RECORDING)
        self.assertIsNone(U.typical([10, 20]))
        self.assertEqual(U.typical([10, 30, 20]), 20)


class UpgradeTest(T.Base):
    def setUp(self):
        super().setUp()
        self.t = self.fake_clock()
        self.app.clock = self.app.upgrade.clock = lambda: self.t[0]

    def make_version(self, ver):
        d = os.path.join(self.places["home"], "app-" + ver)
        os.makedirs(os.path.join(d, "src", "friendapp"), exist_ok=True)
        os.makedirs(os.path.join(d, "python"), exist_ok=True)
        open(os.path.join(d, "src", "friendapp", "server.py"), "w").close()
        open(os.path.join(d, "python", "python.exe"), "w").close()

    def latest(self, **kw):
        self.app.sync.state["latest"] = dict({"version": NEWER, "important": False, "fixes": {"requests": [], "kinds": []}, "cancel": []}, **kw)

    def launched(self, good="0.0.1"):
        """exe から app-<今の版> で動いている形・確かに動いた版 good -> 作り直した Upgrade"""
        self.make_version(VER)
        if good:
            self.make_version(good)
        T.testkit.write_json(os.path.join(self.places["home"], "app-versions.json"), {"current": VER, "good": good or ""})
        up = U.Upgrade(self.app, self.places, clock=lambda: self.t[0], env={U.LAUNCHER_ENV: "1"})
        self.app.upgrade = up
        return up

    def fail_doc(self):
        with open(os.path.join(self.places["outbox"], self.outbox(".fail.json")[0]), encoding="utf-8") as f:
            return json.load(f)

    def outbox(self, suffix):
        box = self.places["outbox"]
        return sorted(n for n in os.listdir(box) if n.endswith(suffix)) if os.path.isdir(box) else []

    # ---------------------------------------------------------------- 1・2 入れ替える時機
    def test_important_swaps_with_queue_but_waits_for_running_and_recording(self):
        """重要な直し: 頼みは自動・順番待ちだけなら swap・作っている 1 本と録画は待つ・[今すぐ] は作っていても swap・ふだんの版は順番待ちで待つ"""
        self.make_version(NEWER)
        self.latest()
        self.engine.queue.runs = [{"id": "r1", "state": "queued"}]
        self.app.update_requested = True
        self.assertFalse(self.app.state()["swap"])   # ふだん: 順番待ちがあれば待つ
        self.latest(important=True)
        self.app.upgrade.tick()
        st = self.app.state()
        self.assertTrue(st["updateRequested"] and st["swap"])
        self.engine.queue.runs = [{"id": "r1", "state": "running"}]
        self.assertFalse(self.app.state()["swap"])
        self.assertTrue(self.app.update_view()["important"] and self.app.update_view()["waiting"])
        self.app.upgrade.press_now()
        self.assertTrue(self.app.state()["swap"])
        self.app.recording_count = lambda: 1
        self.assertFalse(self.app.state()["swap"])   # 録画は止めない
        self.app.report._stuck_on.add(("rec", "x"))   # 1 分増えない録画は止まったと見なす
        self.assertTrue(self.app.state()["swap"])

    def test_overdue_after_24h(self):
        self.make_version(NEWER)
        self.latest()
        self.app.upgrade.tick()
        self.assertFalse(self.app.update_view()["overdue"])
        self.t[0] += U.OVERDUE_SEC
        self.assertTrue(self.app.update_view()["overdue"])

    def test_cancelled_or_lower_or_gone_latest_discards_pending(self):
        """latest.json の cancel・版が下がった・外された(gone)なら、取ってある版を捨てる(心拍の pending が null)"""
        for mark in ({"cancel": [NEWER]}, {"version": "998.0.0"}, None):
            self.make_version(NEWER)
            if mark is None:
                self.app.sync.state["latest"] = {"gone": True}
            else:
                self.latest(**mark)
            self.app.update_requested = True
            self.app.upgrade.tick()
            self.assertFalse(os.path.exists(os.path.join(self.places["home"], "app-" + NEWER)), mark)
            self.assertEqual(self.app.update_version(), "")
            self.assertFalse(self.app.update_requested)
        self.app.sync.state.pop("latest")
        self.make_version(NEWER)
        self.app.upgrade.tick()
        self.assertEqual(self.app.update_version(), NEWER)   # latest を読めていないだけなら捨てない

    # ---------------------------------------------------------------- 4 確かめと戻し
    def test_verify_ok_after_window_with_screen_and_sync(self):
        up = self.launched()
        self.assertEqual(up.verify, "pending")
        up.tick()
        self.t[0] += U.VERIFY_SEC
        up.saw_screen()
        self.app.sync.passes = 1
        up.tick()
        self.assertEqual(self.app.state()["verify"], "ok")

    def test_verify_pauses_during_live_and_rolls_back_after(self):
        """録画中は確かめの時計を止める・失敗しても戻すのは録画の後・戻す先は確かに動いた版"""
        up = self.launched(good="0.0.1")
        self.app.recording_count = lambda: 1
        up.tick()
        self.t[0] += U.VERIFY_SEC * 3
        up.tick()
        self.assertEqual(up.verify, "pending")   # 録画中は数えない
        self.app.recording_count = lambda: 0
        up.tick()
        self.t[0] += U.VERIFY_SEC
        up.tick()   # 画面が返事をしなかった
        self.assertEqual(up.verify, "fail")
        self.app.recording_count = lambda: 1
        self.assertNotIn("rollback", self.app.state())   # 録画中は待つ
        self.app.recording_count = lambda: 0
        self.assertEqual(self.app.state()["rollback"]["to"], "0.0.1")

    def test_verify_error_without_good_reports_fail_file(self):
        up = self.launched(good=None)
        up.on_diag("exception", {"summary": "思わぬ例外"}, "")
        up.tick()
        self.assertEqual(up.verify, "fail")
        self.assertNotIn("rollback", self.app.state())
        doc = self.fail_doc()
        self.assertEqual((doc["v"], doc["kind"], doc["from"], doc["to"]), (1, "rollback", VER, None))
        self.assertIn("戻せませんでした", doc["why"])

    def test_rollback_marks(self):
        """戻す印: to null は確かに動いた版へ・残っていない版は戻さず fail.json・印は消す"""
        up = self.launched(good="0.0.1")
        io = T.FakeDropbox()
        io.read_small = lambda p, cap=0: (io.files[p], False) if p in io.files else None
        io.files[U.ROLLBACK_DIR + "/rollback-1.rollback.json"] = json.dumps({"v": 1, "id": "rollback-1", "to": "0.0.9", "why": "試し"}).encode()
        self.assertEqual(up.take_marks(io), 0)
        self.assertEqual(io.files, {})
        self.assertIn("残っていません", self.fail_doc()["why"])
        io.files[U.ROLLBACK_DIR + "/rollback-2.rollback.json"] = json.dumps({"v": 1, "id": "rollback-2", "to": None, "why": "直す"}).encode()
        self.assertEqual(up.take_marks(io), 1)
        self.assertEqual(self.app.state()["rollback"], {"to": "0.0.1", "why": "直す"})
        self.assertFalse(self.app.state()["swap"])   # 戻すときは入れ替えない

    # ---------------------------------------------------------------- 6 心拍
    def test_beat_small_and_only_newest_kept(self):
        self.make_version(NEWER)
        self.latest()
        self.engine.queue.runs = [{"id": "r1", "state": "running", "requestId": RID}]
        self.app.update_requested = True
        self.app.upgrade.beat(self.t[0])
        self.t[0] += 1
        self.app.upgrade.beat(self.t[0])
        names = self.outbox(".beat.json")
        self.assertEqual(len(names), 1)
        with open(os.path.join(self.places["outbox"], names[0]), "rb") as f:
            raw = f.read()
        self.assertLessEqual(len(raw), U.BEAT_MAX)
        d = json.loads(raw)
        self.assertEqual((d["v"], d["kind"], d["appVersion"], d["pending"], d["wait"], d["live"], d["request"]["id"]),
                         (1, "beat", VER, NEWER, "busy", {"state": ""}, RID))

    # ---------------------------------------------------------------- 3 直しの版のやり直し
    def test_fix_retry_once_then_gave_up(self):
        """直す対象の失敗の行は 1 回だけやり直す・また失敗したら自動のやり直しを使い切った(gaveUp)・引き継いだ行はやり直さない"""
        rid = self.failing_row()
        taken = self.failing_row()
        self.app.inbox.row(taken)["takeover"] = True
        self.app.sync.state["latest"] = {"version": VER, "important": True, "fixes": {"requests": [rid, taken], "kinds": [1]}, "cancel": []}
        self.assertEqual(self.app.upgrade.fix_retries(), [rid])
        self.assertEqual(self.app.inbox.row(rid)["state"], "sent")
        self.assertEqual(self.app.upgrade.fix_retries(), [])   # 2 回目はしない
        self.fail_again(rid)
        f = self.view_row(rid)["fail"]
        self.assertFalse(f["retrying"])
        self.assertTrue(T._api.RETRY_MAX < self.app.inbox.row(rid)["autoRetries"])
        self.assertEqual(self.app.inbox.row(taken)["state"], "failed")

    # ---------------------------------------------------------------- 5 固まり
    def test_stuck_stage_cancels_run_and_fails_row(self):
        rid = self.send()[1]["row"]["id"]
        run = self.app.inbox.row(rid)["runId"]
        for s in (100, 200, 300):
            self.app.inbox.record_stage("切り抜き", s)
        now = int(self.t[0] * 1000)
        self.app.api._stages[rid] = ["切り抜き", now, "x", now]
        self.assertEqual(self.app.upgrade.stuck_check(self.t[0] + U.STUCK_FLOOR - 1), [])   # ふだん 200 秒 x3 < 下限 10 分
        self.assertEqual(self.app.upgrade.stuck_check(self.t[0] + U.STUCK_FLOOR + 1), [rid])
        self.assertIn(run, self.engine.queue.cancelled)
        self.assertEqual(self.app.inbox.row(rid)["state"], "failed")
        self.app.inbox.finished(run, "cancelled", "", [])   # 止めた実行の終わりの知らせ(runqueue → engine.after_run)でも行は消えない
        self.assertEqual(self.app.inbox.row(rid)["state"], "failed")
        self.assertTrue(self.view_row(rid)["fail"]["retrying"])   # 自動のやり直しへ(問題 1 の流れ)
        self.app.inbox.row(rid)["state"], self.app.inbox.row(rid)["runId"] = "making", "run-next"   # 自動のやり直しの次の実行がまた固まる = また見張る
        self.app.api._stages[rid] = ["切り抜き", now, "x", now]
        self.assertEqual(self.app.upgrade.stuck_check(self.t[0] + U.STUCK_FLOOR + 1), [rid])
        self.assertIn("run-next", self.engine.queue.cancelled)

    # ---------------------------------------------------------------- 止まった録画のやり直し
    def fake_live(self, recs):
        """録画元の偽物(一覧 = recs・やり直しの呼び出しを覚える)。録画 rec-1 を 1 分増えない(止まった)にする -> 呼び出しの覚え"""
        calls = []
        self.engine.live = types.SimpleNamespace(recent=lambda: recs,
                                                   restart_recording=lambda rc, rec, whole=False: calls.append((rc, rec, whole)) or ("respawn" if whole else "reconnect"))
        rep = self.app.report
        rep._stuck_on.add(("rec", "rec-1"))
        rep._recs["rec-1"] = {"secs": 10, "since": self.t[0], "active": True}
        return calls

    def rec(self, rid, state="recording", active=True):
        return {"recorder": "local", "id": rid, "state": state, "active": active, "seconds": 10}

    def test_stalled_recording_restarts_only_that_one_up_to_max(self):
        """止まった録画だけをやり直す(ほかの録画・処理は止めない)・間をあける・回数の上限・状態の書き出し(stage record)と操作の記録"""
        self.engine.queue.runs = [{"id": "r1", "state": "running"}]
        calls = self.fake_live([self.rec("rec-1"), self.rec("rec-2")])
        up = self.app.upgrade
        self.assertEqual(up.rec_retry(self.t[0] + U.REC_RETRY_AFTER - 1), [])   # 録画の部品が自分でつなぎ直す間は待つ
        now = self.t[0] + U.REC_RETRY_AFTER
        self.assertEqual(up.rec_retry(now), ["rec-1"])
        self.assertEqual(calls, [("local", "rec-1", False)])
        self.assertEqual(up.rec_retry(now + U.REC_RETRY_GAP - 1), [])   # 間をあける
        for i in range(1, U.REC_RETRY_MAX + 1):
            up.rec_retry(now + U.REC_RETRY_GAP * i)
        self.assertEqual(calls, [("local", "rec-1", False)] * U.REC_RETRY_MAX)   # rec-2 が録れているので録画の部品ごとにはしない
        self.assertEqual(self.engine.queue.cancelled, [])
        self.assertEqual(self.engine.queue.runs[0]["state"], "running")
        marks = [p for p in self.app.report._pending if p[0] == "stuck" and p[3].get("stage") == "record"]
        self.assertEqual([m[3]["attempt"] for m in marks], list(range(1, U.REC_RETRY_MAX + 1)))
        ops = [r for r in self.app.report.ops.recent(10 ** 6) if r["kind"] == "job_retry"]
        self.assertEqual(len(ops), U.REC_RETRY_MAX)
        self.assertEqual(U.Upgrade(self.app, self.places).state["recRetry"]["rec-1"]["n"], U.REC_RETRY_MAX)   # 開き直しても数え直さない

    def test_stalled_recording_second_try_restarts_recorder_when_alone(self):
        calls = self.fake_live([self.rec("rec-1")])
        now = self.t[0] + U.REC_RETRY_AFTER
        self.app.upgrade.rec_retry(now)
        self.app.upgrade.rec_retry(now + U.REC_RETRY_GAP)
        self.assertEqual(calls, [("local", "rec-1", False), ("local", "rec-1", True)])   # つなぎ直しで直らなければ録画の部品ごと(続きから)

    def test_ended_or_reconnecting_recording_is_left_alone(self):
        """配信が終わった・つなぎ直し中・配信を待っている録画はやり直さない"""
        for r in (self.rec("rec-1", "ended", False), self.rec("rec-1", "reconnecting"), self.rec("rec-1", "waiting")):
            calls = self.fake_live([r])
            self.assertEqual(self.app.upgrade.rec_retry(self.t[0] + U.REC_RETRY_AFTER * 10), [], r["state"])
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
