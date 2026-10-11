# -*- coding: utf-8 -*-
"""flow/jobs.Table(② の 1 つの器。OPT2 後半 J6): 積む・糸・枠・状態・取り消し・やり直し・履歴・busy・終了の流れ・掲示板

    py -3.10 -m unittest src/flow/tests/test_jobs_table.py -v
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> flow -> src
from flow import board as B  # noqa: E402
from flow.jobs import Table  # noqa: E402
from ytt import jobs as slots  # noqa: E402
from ytt.errors import ApiError, Cancelled  # noqa: E402


def wait(pred, sec=5):
    end = time.time() + sec
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def one_at_a_time(active, spec, kind):
    if active:
        raise ApiError("busy", "動いています", 409)


def board_job(rec):
    st = rec["state"]
    return {"id": "pk:" + rec["id"], "kind": "pack", "title": rec["title"], "state": st,
            "canCancel": st in ("queued", "running"), "canRetry": st in ("error", "cancelled")}


class TestTable(unittest.TestCase):
    def table(self, run, **kw):
        kw.setdefault("board_job", board_job)
        return Table("pk", "t", run=run, **kw)

    def test_runs_in_order_and_keeps_result(self):
        seen = []
        t = self.table(lambda rec, ctl: seen.append(rec["spec"]["n"]) or rec["spec"]["n"] * 10, title=lambda spec, kind: "n%d" % spec["n"])
        recs = [t.add({"n": i}) for i in range(3)]
        self.assertTrue(wait(lambda: not t.busy()))
        self.assertEqual(seen, [0, 1, 2])
        self.assertEqual([(r["state"], r["result"], r["title"]) for r in recs], [("done", 0, "n0"), ("done", 10, "n1"), ("done", 20, "n2")])
        self.assertTrue(all(r["finishedAt"] and r["startedAt"] for r in recs))

    def test_admit_kinds_and_closing(self):
        gate = threading.Event()
        t = self.table(lambda rec, ctl: gate.wait(5), admit=one_at_a_time, kinds=("plan", "build"))
        rec = t.add({}, "build")
        self.assertEqual(rec["kind"], "build")
        with self.assertRaises(ApiError) as c:
            t.add({})
        self.assertEqual(c.exception.status, 409)
        with self.assertRaises(ValueError):
            t.add({}, "nai")
        gate.set()
        self.assertTrue(wait(lambda: not t.busy()))
        self.assertEqual(t.shutdown(), [])
        with self.assertRaises(ApiError) as c:
            t.add({})
        self.assertEqual((c.exception.code, c.exception.status), ("closing", 503))

    def test_cancel_queued_and_running(self):
        gate = threading.Event()

        def run(rec, ctl):
            gate.wait(5)
            ctl.check()
        t = self.table(run, drop_state="skipped", phases={"cancelled": "中止しました"})
        a, b = t.add({}), t.add({})
        self.assertTrue(wait(lambda: a["state"] == "running"))
        t.cancel(b["id"])
        self.assertEqual(b["state"], "skipped")
        t.cancel(a["id"])
        gate.set()
        self.assertTrue(wait(lambda: a["state"] == "cancelled"))
        self.assertEqual(a["phase"], "中止しました")
        t.cancel(a["id"])   # 終わった物は何もしない
        with self.assertRaises(ApiError) as c:
            t.cancel("nai")
        self.assertEqual(c.exception.status, 404)

    def test_errors_and_custom_cancel_exception(self):
        class MyStop(Exception):
            pass

        def run(rec, ctl):
            if rec["spec"]["x"] == "api":
                raise ApiError("bad", "だめです")
            if rec["spec"]["x"] == "stop":
                raise MyStop()
            raise ValueError("boom")
        t = self.table(run, cancelled_exc=(MyStop, Cancelled))
        api, stop, boom = t.add({"x": "api"}), t.add({"x": "stop"}), t.add({"x": "boom"})
        self.assertTrue(wait(lambda: not t.busy()))
        self.assertEqual((api["state"], api["error"]), ("error", "だめです"))
        self.assertEqual(stop["state"], "cancelled")
        self.assertEqual(boom["state"], "error")
        self.assertIn("ValueError", boom["error"])

    def test_retry_and_history(self):
        t = self.table(lambda rec, ctl: 1 / 0, keep=3, retryable=("error",))
        recs = [t.add({"n": i}) for i in range(5)]
        self.assertTrue(wait(lambda: not t.busy()))
        self.assertEqual(list(t.jobs), [r["id"] for r in recs[2:]])   # 終わった物は新しい 3 つだけ
        new = t.retry(recs[2]["id"])
        self.assertNotIn(recs[2]["id"], t.jobs)
        self.assertEqual(list(t.jobs)[-1], new["id"])
        self.assertTrue(wait(lambda: new["state"] == "error"))
        t2 = self.table(lambda rec, ctl: None)
        done = t2.add({})
        self.assertTrue(wait(lambda: not t2.busy()))
        with self.assertRaises(ApiError) as c:
            t2.retry(done["id"])
        self.assertEqual(c.exception.code, "bad_state")

    def test_slot_wait_and_progress(self):
        held_slots = slots.HeavySlots(1)
        held = held_slots.acquire("other")

        def run(rec, ctl):
            ctl.report(0.5, "半分")
            ctl.note("k", 1)
        with mock.patch.object(slots, "SLOTS", held_slots):
            t = self.table(run, slot=lambda rec: "重い")
            rec = t.add({})
            self.assertTrue(wait(lambda: rec["waiting"]))
            self.assertEqual(rec["phase"], slots.WAIT_MESSAGE)
            held_slots.release(held)
            self.assertTrue(wait(lambda: rec["state"] == "done"))
        self.assertEqual((rec["waiting"], rec["progress"], rec["phase"], rec["notes"]), (False, 0.5, "半分", {"k": 1}))

    def test_cancel_while_waiting_for_slot(self):
        held_slots = slots.HeavySlots(1)
        held = held_slots.acquire("other")
        ran = []
        with mock.patch.object(slots, "SLOTS", held_slots):
            t = self.table(lambda rec, ctl: ran.append(1), slot=lambda rec: "重い")
            rec = t.add({})
            self.assertTrue(wait(lambda: rec["waiting"]))
            t.cancel(rec["id"])
            self.assertTrue(wait(lambda: rec["state"] == "cancelled"))
        held_slots.release(held)
        self.assertEqual(ran, [])

    def test_shutdown_interrupts(self):
        gate = threading.Event()

        def run(rec, ctl):
            gate.wait(5)
            ctl.check()
        t = self.table(run, interrupt_phase="中断しました(終了)")
        a, b = t.add({}), t.add({})
        self.assertTrue(wait(lambda: a["state"] == "running"))
        self.assertEqual({r["id"] for r in t.shutdown("終了のため")}, {a["id"], b["id"]})
        self.assertEqual((b["state"], b["error"], b["phase"]), ("cancelled", "終了のため", "中断しました(終了)"))
        gate.set()
        self.assertTrue(wait(lambda: a["state"] == "cancelled"))
        self.assertEqual((a["error"], a["interrupted"]), ("終了のため", True))
        self.assertFalse(t.busy())

    def test_busy_pred_and_clear(self):
        gate = threading.Event()
        t = self.table(lambda rec, ctl: gate.wait(5))
        rec = t.add({"v": "a"})
        self.assertTrue(t.busy(lambda r: r["spec"]["v"] == "a"))
        self.assertFalse(t.busy(lambda r: r["spec"]["v"] == "b"))
        gate.set()
        self.assertTrue(wait(lambda: not t.busy()))
        self.assertEqual(t.clear(), 1)
        self.assertIsNone(t.find(rec["id"]))

    def test_board(self):
        gate = threading.Event()
        t = self.table(lambda rec, ctl: gate.wait(5) and ctl.check(), retryable=("cancelled",))
        b = B.Board()
        t.attach_board(b)
        rec = t.add({})
        self.assertTrue(wait(lambda: rec["state"] == "running"))
        b.refresh()
        self.assertEqual(b.get("pk:" + rec["id"])["state"], "running")
        b.cancel("pk:" + rec["id"])
        gate.set()
        self.assertTrue(wait(lambda: rec["state"] == "cancelled"))
        b.refresh()
        with self.assertRaises(B.Refused):
            b.cancel("pk:" + rec["id"])
        with self.assertRaises(B.NotFound):
            b.cancel("pk:nai")
        new = b.retry("pk:" + rec["id"])
        self.assertNotEqual(new["id"], "pk:" + rec["id"])
        self.assertTrue(wait(lambda: not t.busy()))


if __name__ == "__main__":
    unittest.main()
