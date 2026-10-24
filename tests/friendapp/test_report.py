"""src/friendapp/report.py(状態の書き出しとそのきっかけ)・oplog.py(操作の記録)・tidy.prune_diag の境目のテスト。
本物の Dropbox・作業データ・GPU の調べは使わない(一時フォルダ・偽の io)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_report.py"""
import json
import os
import sys
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from friendapp import diag as G, oplog as O, report as R, tidy as T  # noqa: E402
from test_sync import FakeIo  # noqa: E402

NOW = float(int(time.time()))
TOKEN = "f" * 48
ENV = {"USERPROFILE": r"C:\Users\taro", "USERNAME": "taro", "YTT_FRIEND_TOKEN": TOKEN}


class Stub:
    """玄関の代わり(api・engine などは無い = その欄は空)"""
    api = inbox = sync = engine = settings = None


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "friendreport-")
        self.t = [NOW]
        clock = lambda: self.t[0]   # noqa: E731
        self.places = {"home": os.path.join(self.tmp, "home"), "data": os.path.join(self.tmp, "data"),
                       "friend": os.path.join(self.tmp, "data", "app", "friendapp"), "outbox": os.path.join(self.tmp, "data", "app", "outbox"),
                       "cases": os.path.join(self.tmp, "作業"), "save": lambda: os.path.join(self.tmp, "save")}
        for k in ("home", "friend", "cases"):
            os.makedirs(self.places[k], exist_ok=True)
        self.diag = G.Diag(self.places, clock=clock, env=dict(ENV), gpu_fn=lambda: {"name": "RTX 3060", "vramGB": 12.0})
        self.ops = O.OpLog(self.places["data"], clock=clock)
        self.rep = R.Reporter(Stub(), self.places, self.diag, self.ops, clock=clock)
        self.diag.on_write = self.rep.on_diag

    def states(self):
        box = self.places["outbox"]
        return sorted(n for n in os.listdir(box) if G.STATE_NAME_RE.match(n)) if os.path.isdir(box) else []

    def read(self, name):
        with open(os.path.join(self.places["outbox"], name), encoding="utf-8") as f:
            return json.load(f)

    def locals(self):
        d = self.rep.local_dir()
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_secrets_and_text_are_not_written(self):
        """入れない物: 合言葉・ユーザー名・入力欄の文・鍵の欄の値・名前でない target"""
        log = os.path.join(self.places["friend"], "logs", "friendapp.log")
        os.makedirs(os.path.dirname(log))
        with open(log, "w", encoding="utf-8") as f:
            f.write("%s 同期の失敗 C:\\Users\\taro\\x token=%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW)), TOKEN))
        self.rep.ui_ops({"ops": [
            {"kind": "setting", "target": "#urlInput", "detail": {"before": None, "after": "https://youtu.be/秘密の題", "len": 30}},
            {"kind": "setting", "target": "#apiKey", "detail": {"before": "AIzaXXX", "after": "AIzaYYY"}},
            {"kind": "setting", "target": "#sens", "detail": {"before": "normal", "after": "high"}},
            {"kind": "click", "target": "送るボタンの文", "detail": {}},
            {"kind": "click", "target": "#btnSend", "detail": {"view": "send"}},
            {"kind": "error", "target": "send", "detail": {"message": "C:\\Users\\taro\\a.mp4 が開けません " + TOKEN}}],
            "screen": {"name": "send", "texts": ["合言葉 " + TOKEN, "題"], "disabled": [{"id": "#btnSend", "why": "準備中"}]}})
        self.rep.tick()
        names = self.states()
        self.assertEqual(len(names), 1)   # 画面のエラー = error(すぐ送る)
        doc = self.read(names[0])
        text = json.dumps(doc, ensure_ascii=False)
        for bad in (TOKEN, "taro", "秘密の題", "AIzaXXX", "AIzaYYY", "送るボタンの文"):
            self.assertNotIn(bad, text)
        ops = {o["target"]: o for o in doc["ops"]}
        self.assertEqual(ops["#urlInput"]["detail"], {"len": 30})
        self.assertEqual(ops["#apiKey"]["detail"], {"secret": True})
        self.assertEqual(ops["#sens"]["detail"], {"before": "normal", "after": "high"})
        self.assertEqual(doc["screen"]["disabled"], [{"id": "#btnSend", "why": "準備中"}])
        self.assertEqual(doc["codes"], ["unknown"])
        self.assertTrue(doc["urgent"])
        with open(os.path.join(self.places["data"], O.OPS_DIR, O.day_name(NOW)), encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 5)   # 1 日 1 ファイル・形の違う 1 件は捨てた

    def test_size_is_cut(self):
        log = os.path.join(self.places["friend"], "logs", "friendapp.log")
        os.makedirs(os.path.dirname(log))
        with open(log, "w", encoding="utf-8") as f:
            for i in range(3000):
                f.write("2026-10-25 10:00:00 行 %d %s\n" % (i, "あ" * 250))
        self.rep.set_screen({"name": "receive", "texts": ["い" * 200] * 500})
        path = self.rep.fire("error", None, "x")
        size = os.path.getsize(path)
        self.assertLessEqual(size, R.TARGET_BYTES)
        doc = self.read(os.path.basename(path))
        self.assertTrue(doc["truncated"])
        self.assertEqual(doc["trigger"], "error")
        self.assertIn("env", doc)

    def test_same_trigger_within_5_minutes(self):
        self.assertIsNotNone(self.rep.fire("error", None, "a"))
        self.assertIsNone(self.rep.fire("error", None, "b"))
        self.assertIsNotNone(self.rep.fire("error", "20261025-100000-abcdef", "別の依頼"))
        self.t[0] += R.DEDUPE_SEC
        self.assertIsNotNone(self.rep.fire("error", None, "c"))
        self.assertEqual(len(self.states()), 3)

    def test_diag_kinds_pick_trigger_and_place(self):
        """失敗した実行 = error(箱)・済んだ実行 = request_end(手元)"""
        self.diag.write("run", rid="20261025-100000-abcdef", summary="error", request={"state": "error"})
        self.diag.write("run", rid="20261025-100000-abcdee", summary="done", request={"state": "done"})
        self.rep.tick()
        names = self.states()
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("20261025-100000-abcdef__state-"))
        doc = self.read(names[0])
        self.assertTrue(any(n.endswith(".diag.json") for n in doc["diag"]))
        self.assertEqual([n.split("-", 1)[1] for n in self.locals()], ["request_end.state.json"])

    def test_update_trigger_for_rollback_and_fetch_failure(self):
        """前の版で起こした(rollback)・新しい版を取れない(同期の 更新)は trigger update(すぐ送る・stage rollback / update・codes unknown)"""
        self.diag.write("rollback", summary="戻した")
        self.diag.write("sync", summary="取れない", stage="更新")
        self.rep.tick()
        docs = [self.read(n) for n in self.states()]
        self.assertEqual(sorted((d["trigger"], d["facts"].get("stage"), d["codes"][0]) for d in docs),
                         [("update", "rollback", "unknown")])   # 同じきっかけは 5 分に 1 回
        self.t[0] += 301
        self.diag.write("sync", summary="取れない", stage="更新")
        self.rep.tick()
        self.assertIn("update", [self.read(n)["facts"].get("stage") for n in self.states()])

    def test_trouble_three_clicks(self):
        self.rep.ui_ops({"ops": [{"kind": "click", "target": "#btnSend", "at": int(NOW * 1000) - i * 1000} for i in (3, 2, 1)]})
        self.rep.tick()
        self.assertEqual(self.states(), [])   # 手元だけ
        self.assertEqual(len(self.locals()), 1)

    def test_ask_sends_local_and_removes_mark(self):
        self.rep.fire("trouble", None, "a")
        self.t[0] += 1
        self.rep.fire("periodic", None, "b")
        self.assertEqual(len(self.locals()), 2)
        io = FakeIo(lambda: self.t[0])
        io.put("/診断/送って/q1.ask.json", json.dumps({"v": 1, "id": "q1", "at": 1, "note": "見たい"}).encode("utf-8"))
        self.rep.answer_asks(io)
        names = self.states()
        self.assertEqual(len(names), 1)
        doc = self.read(names[0])
        self.assertEqual((doc["trigger"], doc["ask"]), ("ask", "q1"))
        self.assertEqual([x["trigger"] for x in doc["local"]], ["trouble", "periodic"])
        self.assertIsNone(io.data("/診断/送って/q1.ask.json"))
        self.assertEqual(self.locals(), [])
        self.rep.answer_asks(io)   # 印が無ければ何もしない
        self.assertEqual(len(self.states()), 1)

    def test_sync_answers_ask_then_uploads_to_diag(self):
        """同期の 1 回: 印に答えた状態を同じ回の送り返しで /診断/ へ上げる"""
        from friendapp import inbox as I, sync as S
        box = I.Inbox(os.path.join(self.places["friend"], "inbox.json"), self.places["outbox"], self.places["save"], lambda: self.places["cases"],
                      clock=lambda: self.t[0])
        io = FakeIo(lambda: self.t[0])
        sync = S.Sync(self.places, box, lambda: None, client_factory=lambda cfg, c: io, clock=lambda: self.t[0], env={}, version="0.90.0")
        sync.asks = self.rep.answer_asks
        io.put("/診断/送って/q2.ask.json", b'{"v": 1, "id": "q2", "at": 1}')
        sync._asks(io)
        sync._returns(io)
        up = [k for k in io.files if k.startswith("/診断/") and k.endswith(".state.json")]
        self.assertEqual(len(up), 1)
        self.assertEqual(self.states(), [])   # 上げたら箱から消える
        self.assertIsNotNone(sync.sent_at)

    def test_crash_mark(self):
        self.rep.started()
        self.rep.tick()
        self.assertEqual(self.states(), [])   # 初めての起動
        self.rep.stopped()
        self.rep.started()
        self.rep.tick()
        self.assertEqual(self.states(), [])   # 前回は閉じる途中を通った
        rep2 = R.Reporter(Stub(), self.places, self.diag, self.ops, clock=lambda: self.t[0])   # 印を残したまま起動し直した
        rep2.started()
        rep2.tick()
        names = self.states()
        self.assertEqual(len(names), 1)
        self.assertEqual(self.read(names[0])["trigger"], "crash")

    def test_switch_off_writes_nothing(self):
        self.diag.env[G.SWITCH_ENV] = "0"
        self.assertIsNone(self.rep.fire("error", None, "x"))
        self.assertEqual(self.states(), [])

    def test_old_ops_and_local_go_after_3_days(self):
        self.rep.fire("trouble", None, "a")
        self.ops.add("click", "#btnSend")
        files = [os.path.join(self.places["data"], d, n) for d in T.DIAG_DIRS for n in os.listdir(os.path.join(self.places["data"], d))]
        self.assertEqual(len(files), 2)
        old = NOW - 3 * 86400 - 10
        os.utime(files[0], (old, old))
        self.assertEqual(T.prune_diag(self.places["data"], NOW), 1)
        self.assertFalse(os.path.exists(files[0]))
        self.assertTrue(os.path.exists(files[1]))


class JudgeTest(unittest.TestCase):
    def test_codes(self):
        row = {"id": "a", "state": "failed", "autoRetries": 2, "fail": {"code": "ytFetch", "retrying": False}, "packs": [],
               "source": {"videoId": "v1"}, "form": {"ranges": None}}
        codes, facts = R.judge("error", row, [row, dict(row, id="b")])
        self.assertEqual(codes, ["yt_fetch_gave_up", "undelivered", "duplicate"])
        self.assertEqual(facts["retry"], {"scheduled": False, "gaveUp": True})
        self.assertFalse(facts["delivered"])
        codes, _ = R.judge("error", dict(row, fail={"code": "ytFetch", "retrying": True}), [])
        self.assertEqual(codes, ["yt_fetch_retry"])
        codes, facts = R.judge("live_end", {"id": "a", "state": "arrived", "packs": [{}]}, [], {"peaksDoc": {"peaks": 0}})
        self.assertEqual((codes, facts["candidates"], facts["delivered"]), (["zero_cand_filled"], 0, True))

    def test_ok_when_finished_without_problem(self):
        """問題なく終わった live_end・request_end は ok(空にしない)。失敗や error のきっかけには付けない"""
        done = {"id": "a", "state": "arrived", "packs": [{}]}
        self.assertEqual(R.judge("request_end", done, [])[0], ["ok"])
        self.assertEqual(R.judge("live_end", done, [], {"peaksDoc": {"peaks": 3}})[0], ["ok"])
        self.assertEqual(R.judge("live_end", None, [])[0], ["ok"])
        failed = {"id": "a", "state": "failed", "fail": {"code": "members", "retrying": False}, "packs": []}
        self.assertEqual(R.judge("request_end", failed, [])[0], ["undelivered"])
        self.assertEqual(R.judge("error", done, [])[0], ["unknown"])


if __name__ == "__main__":
    unittest.main()
