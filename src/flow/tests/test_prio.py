# -*- coding: utf-8 -*-
"""flow/prio(処理の優先度の 1 つの表。PRIO・決定 3-49): 表・級の決め方・重い処理の枠の順番と「空いているときだけ」・
ジョブの器の待ちの順・まとめて実行の待ち行列の選び方・後回しの仕事の OS の優先度

    py -3.12 -m unittest src/flow/tests/test_prio.py -v
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> flow -> src
from flow import prio  # noqa: E402
from flow import runqueue  # noqa: E402
from flow.jobs import Table  # noqa: E402
from ytt import jobs as slots  # noqa: E402
from ytt import procs  # noqa: E402


def wait(pred, sec=5):
    end = time.time() + sec
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class TestTable(unittest.TestCase):
    def test_order_and_values(self):
        """録画中のライブ > 友人の依頼 > 自分の配信のまとめて実行 > 後回しの仕事(空いているときだけ・OS はアイドル)"""
        self.assertEqual(prio.NAMES, ("live", "friend", "batch", "later"))
        self.assertEqual([prio.rank(n) for n in prio.NAMES], [0, 1, 2, 3])
        self.assertEqual(prio.rank(prio.DEFAULT), slots.DEFAULT_RANK)
        self.assertEqual([prio.idle_only(n) for n in prio.NAMES], [False, False, False, True])
        self.assertEqual(prio.os_priority("later"), "idle")
        self.assertIsNone(prio.os_priority("batch"))
        self.assertEqual(prio.rank("知らない"), prio.rank("batch"))
        self.assertEqual(prio.slot_kw("live"), {"rank": 0, "idle_only": False})

    def test_of_run_and_spec(self):
        R = types.SimpleNamespace
        self.assertEqual(prio.of_run(R(pool={"key": "k"}, request_id="r1")), "live")
        self.assertEqual(prio.of_run(R(pool=None, request_id="r1")), "friend")
        self.assertEqual(prio.of_run(R(pool=None, request_id=None)), "batch")
        self.assertEqual(prio.of_spec({"evalBatch": True}), "later")
        self.assertEqual(prio.of_spec({"prio": "friend", "evalBatch": True}), "friend")
        self.assertEqual(prio.of_spec({"prio": "x"}), "batch")
        self.assertEqual(prio.of_spec(None), "batch")


class TestSlots(unittest.TestCase):
    def _hold(self, s, tool="a", **kw):
        """枠を 1 つ取って持つ糸 -> (取れた印, 返す印)"""
        got, free = threading.Event(), threading.Event()

        def body():
            with s.slot(tool, tool, poll=0.01, **kw):
                got.set()
                free.wait(5)
        threading.Thread(target=body, daemon=True).start()
        return got, free

    def test_rank_order_then_first_come(self):
        """待ちは rank の小さい順・同じなら先に来た順(動いている処理は止めない)"""
        s = slots.HeavySlots(limit=1, reserved={})
        got, free = self._hold(s, "batch-run")
        self.assertTrue(got.wait(2))
        order = []

        def body(tool, rank):
            with s.slot(tool, tool, poll=0.01, rank=rank):
                order.append(tool)
        ths = []
        for tool, rank in (("b1", 2), ("b2", 2), ("live", 0), ("friend", 1)):
            th = threading.Thread(target=body, args=(tool, rank), daemon=True)
            th.start()
            ths.append(th)
            self.assertTrue(wait(lambda n=len(ths): len(s.snapshot()["waiting"]) == n))
        self.assertEqual([w["tool"] for w in s.snapshot()["waiting"]], ["live", "friend", "b1", "b2"])
        free.set()
        for th in ths:
            th.join(5)
        self.assertEqual(order, ["live", "friend", "b1", "b2"])

    def test_idle_only_waits_for_free_and_check(self):
        """後回しの仕事: ほかの処理が動いている・idle の答えが偽の間は取らない(上限に空きがあっても)"""
        s = slots.HeavySlots(limit=2, reserved={})
        idle = {"v": True}
        s.set_idle_check(lambda: idle["v"])
        got, free = self._hold(s, "batch")
        self.assertTrue(got.wait(2))
        self.assertFalse(s.idle_now())
        lg, lf = self._hold(s, "later", rank=3, idle_only=True)
        self.assertFalse(lg.wait(0.3))
        self.assertTrue(s.snapshot()["waiting"][0].get("later"))
        idle["v"] = False
        free.set()
        self.assertFalse(lg.wait(2.5))   # 枠は空いたが idle の答えが偽
        idle["v"] = True
        self.assertTrue(lg.wait(5))
        self.assertTrue(s.idle_now())   # 後回しの仕事どうしは邪魔しない
        lf.set()

    def test_idle_check_errors_mean_busy(self):
        s = slots.HeavySlots(limit=1, reserved={})
        s.set_idle_check(lambda: 1 / 0)
        self.assertFalse(s.idle_now())
        s.set_idle_check(None)
        self.assertTrue(s.idle_now())

    def test_reserved_still_works(self):
        """用途つきの枠(M6)は rank を渡しても今のまま"""
        s = slots.HeavySlots(limit=1, reserved={"live": 1})
        got, free = self._hold(s, "batch")
        self.assertTrue(got.wait(2))
        lg, lf = self._hold(s, "live", reserved=True, **prio.slot_kw("live"))
        self.assertTrue(lg.wait(2))
        self.assertTrue(any(a.get("extra") for a in s.snapshot()["active"]))
        free.set()
        lf.set()


class TestJobTable(unittest.TestCase):
    def setUp(self):
        self.s = slots.HeavySlots(limit=2, reserved={})
        p = mock.patch.object(slots, "SLOTS", self.s)
        p.start()
        self.addCleanup(p.stop)

    def test_queue_order_by_table_then_kind(self):
        """待ちは 表の順 → 種類の数字 → 入れた順。後回しの仕事は空いているときだけ並ぶ"""
        t = Table("tx", "t", run=lambda rec, ctl: None, kinds=(), autostart=False, priority=lambda rec: rec["spec"].get("pr", 1))
        later = t.add({"evalBatch": True, "pr": 0}, "x")
        b1 = t.add({"pr": 1}, "x")
        diar = t.add({"pr": 0}, "x")
        fr = t.add({"pr": 1, "prio": "friend"}, "x")
        self.assertEqual([r["id"] for r in t.queue_order(idle=True)], [fr["id"], diar["id"], b1["id"], later["id"]])
        self.assertEqual([r["id"] for r in t.queue_order(idle=False)], [fr["id"], diar["id"], b1["id"]])
        self.s.set_idle_check(lambda: False)
        self.assertNotIn(later["id"], [r["id"] for r in t.queue_order()])
        self.s.set_idle_check(lambda: True)
        self.assertIn(later["id"], [r["id"] for r in t.queue_order()])

    def test_later_runs_only_when_idle_and_gets_idle_os_priority(self):
        idle = {"v": False}
        self.s.set_idle_check(lambda: idle["v"])
        seen = []
        t = Table("an", "t", run=lambda rec, ctl: seen.append((rec["id"], ctl.os_priority)), kinds=(), slot=lambda rec: "x")
        with mock.patch("flow.jobs.LATER_POLL", 0.05):
            later = t.add({"prio": "later"}, "x")
            time.sleep(0.3)
            self.assertEqual((later["state"], seen), ("queued", []))
            norm = t.add({}, "x")
            self.assertTrue(wait(lambda: norm["state"] == "done"))
            self.assertEqual(later["state"], "queued")
            idle["v"] = True
            self.assertTrue(wait(lambda: later["state"] == "done"))
        self.assertEqual(seen, [(norm["id"], None), (later["id"], "idle")])


class TestRunQueue(unittest.TestCase):
    def test_next_queued_by_table(self):
        """まとめて実行の待ち行列: 録画中のライブ(組の溜め)> 友人の依頼 > 自分の配信、同じなら入れた順。実行中は数えない"""
        def R(i, state="queued", pool=None, rid=None):
            return types.SimpleNamespace(id=i, state=state, pool=pool, request_id=rid)
        q = types.SimpleNamespace(runs=[R("own1"), R("run", state="running", rid="x"), R("fr1", rid="a"), R("own2"), R("fr2", rid="b")])
        pick = runqueue.Queue._next_queued
        self.assertEqual(pick(q).id, "fr1")
        q.runs.append(R("live", pool={"key": "k"}))
        self.assertEqual(pick(q).id, "live")
        q.runs = [R("own1"), R("own2")]
        self.assertEqual(pick(q).id, "own1")
        q.runs = []
        self.assertIsNone(pick(q))

    def test_idle_for_later(self):
        lock = threading.Lock()
        q = types.SimpleNamespace(cv=threading.Condition(lock), closed=False, runs=[], _status_hook=None)
        q._active_runs = lambda: [r for r in q.runs if r.state in runqueue.ACTIVE_STATES]
        f = runqueue.Queue.idle_for_later
        self.assertTrue(f(q))
        q.runs = [types.SimpleNamespace(state="queued")]
        self.assertFalse(f(q))
        q.runs = []
        q._status_hook = lambda: {"recording": 1}
        self.assertFalse(f(q))
        q._status_hook = lambda: {"recording": 0, "detecting": 2}
        self.assertTrue(f(q))
        q._status_hook = lambda: 1 / 0
        self.assertFalse(f(q))

    def test_watch_installs_check(self):
        s = slots.HeavySlots(limit=1, reserved={})
        q = types.SimpleNamespace(idle_for_later=lambda: False)
        prio.watch(q, s)
        self.assertFalse(s.idle_now())


class TestOsPriority(unittest.TestCase):
    def test_run_capture_uses_ctl_priority(self):
        got = []

        def fake(cmd, flags=None, **kw):
            got.append(flags)
            return 0, [], None
        ctl = slots.Ctl()
        with mock.patch.object(procs._tools, "run_progress", fake):
            procs.run_capture(ctl, ["x"])
            ctl.os_priority = "idle"
            procs.run_capture(ctl, ["x"])
            procs.run_capture({"cancel": False}, ["x"])
        self.assertIsNone(got[0])
        self.assertEqual(got[1], procs._tools.no_window_flags(priority="idle"))
        self.assertIsNone(got[2])
        self.assertEqual(ctl.span(0, 1).os_priority, "idle")


if __name__ == "__main__":
    unittest.main()
