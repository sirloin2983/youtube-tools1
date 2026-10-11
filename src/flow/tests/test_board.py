# -*- coding: utf-8 -*-
"""flow/board.py(② のジョブの掲示板。RS8 の ② の口 S1)のテスト。  py -3.10 -m unittest src/flow/tests/test_board.py -v
形の検査・押す形(upsert)と引く形(register の source)・rev・終わった直近の数・案件ごとの絞り込みとまとめ・親子の印・取り消しとやり直しの振り分け。
器ごとに「状態が変わったら掲示板にその id がその state で載る」は各器のテスト(② の Run は test_runqueue.py)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import board as B  # noqa: E402
from ytt import fsio  # noqa: E402

ROOT = os.path.abspath(os.path.join(tempfile.gettempdir(), "案件A"))
OTHER = os.path.abspath(os.path.join(tempfile.gettempdir(), "案件B"))


def job(jid="tx:j1", state="running", **kw):
    return dict({"id": jid, "kind": "transcribe", "state": state}, **kw)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestNormalize(unittest.TestCase):
    def test_defaults(self):
        j = B.normalize(job(), now_ms=5)
        self.assertEqual(set(j), set(B.FIELDS))
        self.assertEqual((j["parent"], j["case"], j["target"], j["title"], j["phase"], j["progress"], j["waiting"]),
                         (None, None, {}, "", "", None, False))
        self.assertEqual((j["stateLabel"], j["createdAt"], j["startedAt"], j["finishedAt"], j["error"], j["canCancel"], j["canRetry"], j["steps"]),
                         ("実行中", 5, None, None, None, False, False, None))

    def test_rejects(self):
        """知らない項目・語彙の外の kind / state・形の違う id・知らない頭は理由つきの ValueError"""
        for bad, why in ((job(extra=1), "知らない項目"), (job(kind="nai"), "Job.kind"), (job(state="wait"), "Job.state"),
                         (job("j1"), "頭:id"), (job("zz:j1"), "頭:id"), (job("tx:"), "頭:id"), (job("tx:a/b"), "頭:id"),
                         (job(parent="nai"), "頭:id"), (job(error=3), "Job.error"), (job(target="x"), "Job.target"),
                         (dict(job(kind="run", steps="x")), "Job.steps"), ("x", "辞書")):
            with self.assertRaisesRegex(ValueError, why, msg=bad):
                B.normalize(bad)

    def test_values(self):
        """progress は 0〜1 に丸める・時刻は整数・error は {code, text, detail}・target は決まった鍵だけ・steps は kind run だけ"""
        j = B.normalize(job(progress=1.7, createdAt=12.9, startedAt=-1, error="だめ", target={"videoId": "v", "nai": "x", "path": 3},
                            case=ROOT, waiting=True, canCancel=True, canRetry=True, steps=[{"key": "a"}]))
        self.assertEqual((j["progress"], j["createdAt"], j["startedAt"]), (1.0, 12, None))
        self.assertEqual(j["error"], {"code": None, "text": "だめ", "detail": None})
        self.assertEqual(j["target"], {"videoId": "v", "path": 3})
        self.assertEqual((j["case"], j["waiting"], j["canCancel"], j["canRetry"], j["steps"]), (fsio.norm_path(ROOT), True, True, False, None))
        self.assertIsNone(B.normalize(job(progress=float("nan")))["progress"])
        self.assertIsNone(B.normalize(job(case="相対/パス"))["case"])
        done = B.normalize(job(state="done", canCancel=True, canRetry=True, waiting=True, error={"code": "x", "text": "t", "detail": "d", "nai": 1}))
        self.assertEqual((done["canCancel"], done["canRetry"], done["waiting"]), (False, True, False))
        self.assertEqual(done["error"], {"code": "x", "text": "t", "detail": "d"})
        run = B.normalize({"id": "run:0123456789", "kind": "run", "state": "queued", "steps": [{"key": "pack", "label": "パック", "state": "wait", "nai": 1}]})
        self.assertEqual(run["steps"], [{"key": "pack", "label": "パック", "state": "wait"}])

    def test_split_id(self):
        self.assertEqual(B.split_id("run:0123456789"), ("run", "0123456789"))
        self.assertEqual(set(B.OWNED_PREFIX.values()) <= set(B.PREFIXES), True)


class TestUpsert(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.b = B.Board(recent=3, clock=self.clock)

    def test_rev_only_when_changed(self):
        self.assertEqual(self.b.rev, 0)
        j = self.b.upsert(job())
        self.assertEqual((self.b.rev, j["createdAt"]), (1, 1000000))
        self.clock.t = 2000.0
        self.b.upsert(job())   # 同じ中身(時刻の無い器は最初の時刻のまま)
        self.assertEqual(self.b.rev, 1)
        self.b.upsert(job(phase="認識中 1/2"))
        self.assertEqual((self.b.rev, self.b.get("tx:j1")["phase"], self.b.get("tx:j1")["createdAt"]), (2, "認識中 1/2", 1000000))
        self.b.remove("tx:j1")
        self.b.remove("tx:j1")
        self.assertEqual((self.b.rev, self.b.get("tx:j1")), (3, None))

    def test_order_and_recent(self):
        """並びは入れた順(置き換えても動かない)。終わった物は終わった時刻の新しい recent 件まで・待ち・実行中は消さない"""
        self.b.upsert(job("tx:a", "running"))
        for i in range(5):
            self.b.upsert(job("tx:d%d" % i, "done", finishedAt=100 + i))
        self.b.upsert(job("tx:a", "running", phase="x"))
        self.assertEqual([j["id"] for j in self.b.list()], ["tx:a", "tx:d2", "tx:d3", "tx:d4"])

    def test_case_filter_and_cases(self):
        self.b.upsert(job("tx:a", "running", case=ROOT))
        self.b.upsert(job("tx:b", "done", case=ROOT, finishedAt=10))
        self.b.upsert(job("tx:c", "error", case=ROOT, finishedAt=20))
        self.b.upsert(job("an:x", "queued", kind="analyze", case=OTHER))
        self.b.upsert(job("tx:n", "running"))
        self.assertEqual([j["id"] for j in self.b.list(ROOT)], ["tx:a", "tx:b", "tx:c"])
        self.assertEqual([j["id"] for j in self.b.list(ROOT.upper() if os.name == "nt" else ROOT)], ["tx:a", "tx:b", "tx:c"])
        self.assertEqual(self.b.list("相対"), [])
        cs = self.b.cases()
        self.assertEqual(cs[fsio.norm_path(ROOT)], {"active": 1, "lastState": "error", "lastFinished": 20})
        self.assertEqual(cs[fsio.norm_path(OTHER)], {"active": 1, "lastState": None, "lastFinished": None})
        snap = self.b.snapshot(case=OTHER)
        self.assertEqual(([j["id"] for j in snap["jobs"]], len(snap["cases"]), snap["rev"]), (["an:x"], 2, self.b.rev))

    def test_link_parent(self):
        """親子の印: 先に印 → 載ったら親を足す / 先に載っていて親が無ければ今足す。器が親を書いていればそれ"""
        self.b.link("tx:j1", "run:0123456789")
        self.assertEqual(self.b.upsert(job())["parent"], "run:0123456789")
        self.b.upsert(job("pk:p1", kind="pack"))
        rev = self.b.rev
        self.b.link("pk:p1", "run:0123456789")
        self.assertEqual((self.b.get("pk:p1")["parent"], self.b.rev), ("run:0123456789", rev + 1))
        self.b.link("an:q1", "run:aaaaaaaaaa")
        self.assertEqual(self.b.upsert(job("an:q1", kind="analyze", parent="run:bbbbbbbbbb"))["parent"], "run:bbbbbbbbbb")
        with self.assertRaises(ValueError):
            self.b.link("nai", "run:0123456789")

    def test_case_hook(self):
        """case の無い Job は hook で引く(target があるときだけ)。引けなかった物は CASE_RETRY_SEC ごとにだけ引き直す・失敗しても載せる"""
        calls = []

        def hook(j):
            calls.append(j["id"])
            if j["id"] == "tx:boom":
                raise OSError("x")
            return ROOT if len(calls) > 1 else None
        self.b.set_case_hook(hook)
        self.assertIsNone(self.b.upsert(job(target={"docId": "d"}))["case"])
        self.b.upsert(job(target={"docId": "d"}, phase="1"))
        self.assertEqual(calls, ["tx:j1"])   # まだ引き直さない
        self.clock.t += B.CASE_RETRY_SEC + 1
        self.assertEqual(self.b.upsert(job(target={"docId": "d"}, phase="2"))["case"], fsio.norm_path(ROOT))
        self.b.upsert(job(target={"docId": "d"}, phase="3"))
        self.assertEqual(len(calls), 2)   # 引けた物は覚える
        self.assertIsNone(self.b.upsert(job("tx:none"))["case"])   # target が無ければ引かない
        self.assertIsNone(self.b.upsert(job("tx:boom", target={"docId": "x"}))["case"])
        self.assertEqual(self.b.upsert(job("tx:own", target={"docId": "x"}, case=OTHER))["case"], fsio.norm_path(OTHER))   # 器が書いた物が勝つ
        self.assertNotIn("tx:own", calls)


class TestSource(unittest.TestCase):
    def setUp(self):
        self.b = B.Board(recent=5, clock=Clock())
        self.now = [job("run:0000000001", "running", kind="run"), job("run:0000000002", "queued", kind="run")]
        self.b.register("run", source=lambda: list(self.now))

    def test_sync(self):
        """問い合わせのたびに読み直す。器が忘れた待ち・実行中は消す・終わった物は残す・同じ中身なら rev は増えない"""
        s1 = self.b.snapshot()
        self.assertEqual([j["id"] for j in s1["jobs"]], ["run:0000000001", "run:0000000002"])
        self.assertEqual(self.b.snapshot()["rev"], s1["rev"])
        self.now = [job("run:0000000001", "done", kind="run", finishedAt=5)]
        s2 = self.b.snapshot()
        self.assertGreater(s2["rev"], s1["rev"])
        self.assertEqual([(j["id"], j["state"]) for j in s2["jobs"]], [("run:0000000001", "done")])
        self.now = []
        self.assertEqual([j["id"] for j in self.b.snapshot()["jobs"]], ["run:0000000001"])

    def test_bad_source(self):
        """器の 1 件の形が違う・頭が違う → その件だけ飛ばす。器が上げても掲示板は返す"""
        logs = []
        self.b.log = logs.append
        self.now = [job("run:0000000001", "running", kind="run"), job("run:0000000002", "nai", kind="run"), job("tx:j1")]
        self.assertEqual([j["id"] for j in self.b.snapshot()["jobs"]], ["run:0000000001"])
        self.assertEqual(len(logs), 2)
        self.b.register("tx", source=lambda: 1 / 0)
        self.assertEqual([j["id"] for j in self.b.snapshot()["jobs"]], ["run:0000000001"])
        with self.assertRaises(ValueError):
            self.b.register("zz", source=list)


class TestCancelRetry(unittest.TestCase):
    def setUp(self):
        self.b = B.Board(clock=Clock())
        self.calls = []
        self.state = {"r1": "running", "r2": "error", "r3": "done"}

        def source():
            return [job("run:" + k, v, kind="run", canCancel=True, canRetry=v == "error") for k, v in self.state.items()]

        def cancel(inner):
            self.calls.append(("cancel", inner))
            self.state[inner] = "cancelled"

        def retry(inner):
            self.calls.append(("retry", inner))
            self.state["r9"] = "queued"
            return job("run:r9", "queued", kind="run")
        self.b.register("run", source=source, cancel=cancel, retry=retry)

    def test_cancel(self):
        out = self.b.cancel("run:r1")
        self.assertEqual((out["state"], self.calls), ("cancelled", [("cancel", "r1")]))
        with self.assertRaises(B.Refused) as cm:
            self.b.cancel("run:r3")
        self.assertEqual(cm.exception.code, "cannot_cancel")
        with self.assertRaises(B.NotFound):
            self.b.cancel("run:nai")
        with self.assertRaises(ValueError):
            self.b.cancel("nai")
        self.b.upsert(job("tx:j1", "running", canCancel=True))   # 器に cancel が無い
        with self.assertRaises(B.Refused):
            self.b.cancel("tx:j1")

    def test_cancel_errors_from_handler(self):
        def gone(inner):
            raise LookupError("もうありません")

        def no(inner):
            raise ValueError("止められません")
        for fn, exc in ((gone, B.NotFound), (no, B.Refused)):
            self.b.register("tx", cancel=fn)
            self.b.upsert(job("tx:j1", "running", canCancel=True))
            with self.assertRaises(exc):
                self.b.cancel("tx:j1")

    def test_retry(self):
        out = self.b.retry("run:r2")
        self.assertEqual((out["id"], out["state"], self.calls), ("run:r9", "queued", [("retry", "r2")]))
        for jid in ("run:r1", "run:r3"):   # 実行中・済み(canRetry が偽)
            with self.assertRaises(B.Refused) as cm:
                self.b.retry(jid)
            self.assertEqual(cm.exception.code, "cannot_retry")
        with self.assertRaises(B.NotFound):
            self.b.retry("run:nai")


class TestDefault(unittest.TestCase):
    def test_one_per_process(self):
        self.assertIs(B.default(), B.default())

    def test_guess_case(self):
        """既定の hook: 動画のパス = そのフォルダ(作業用/ の中なら 1 つ上)・引けなければ None"""
        with tempfile.TemporaryDirectory() as d:
            work = os.path.join(d, "作業用")
            os.makedirs(work)
            clip = os.path.join(work, "a_edit.mp4")
            with open(clip, "wb") as f:
                f.write(b"x")
            self.assertEqual(os.path.normcase(B.guess_case({"target": {"path": clip}})), os.path.normcase(d))
            self.assertIsNone(B.guess_case({"target": {"path": os.path.join(d, "nai", "x.mp4")}}))
            self.assertIsNone(B.guess_case({"target": {}}))
            self.assertIsNone(B.guess_case({"target": {"docId": "../x"}}))


if __name__ == "__main__":
    unittest.main()
