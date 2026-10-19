# -*- coding: utf-8 -*-
"""② 書き出しの器 flow/export.ExportJobs(OPT2 の J2)。① の中身(exporter.run)は差し替える。

    py -3.12 -m unittest src/flow/tests/test_export_jobs.py -v

本物の ① で書き終えるまでの道(public の done の形・同時 1 本の 409・動いている間は書き出し先を変えない・無い id は 404・掲示板の載り方)は
通し src/pipeline/export/tests/test_exporter.py の TestExportThrough。ここは通しでは起こせない物だけ:
- 取り消し・終了の流れの cancel_all(interrupted)
- 枠(SLOTS)をほかの重い処理が持っている間は waiting・待ちの間の取り消し・想定外の例外でも「実行中」のまま残らない
- 掲示板からの取り消し
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import threading
import time
import unittest
from unittest.mock import patch

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from flow import board as B, export as E  # noqa: E402
from pipeline.export import exporter  # noqa: E402
from ytt import jobs, studio_env  # noqa: E402

CLIP = {"id": "m1", "start": 0.0, "end": 1.0, "title": "a", "label": ""}


def spec(vid="abcdefghijk", n=1):
    return {"videoId": vid, "clips": [dict(CLIP, id="m%d" % i) for i in range(1, n + 1)]}


def slow_run(spec, res, ctl, on_done=None):
    """① の代わり: 取り消されるまで「実行中」。取り消されたら中止で終わる"""
    res["items"][0]["status"] = "running"
    for _ in range(400):
        if ctl.cancelled:
            for it in res["items"]:
                it["status"] = "cancelled"
            res["state"] = "cancelled"
            return
        time.sleep(0.01)
    res["state"] = "error"


def wait(pred, sec=5):
    return testkit.wait_for(pred, sec, 0.01)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        saved = studio_env._home
        studio_env.set_home(self.tmp)
        self.addCleanup(setattr, studio_env, "_home", saved)
        self.ex = E.ExportJobs()
        self.addCleanup(self.ex.clear)


class TestExportJobs(Base):
    def test_cancel(self):
        with patch.object(exporter, "run", side_effect=slow_run):
            rec = self.ex.start(spec())
            self.assertTrue(self.ex.is_busy())
            self.ex.cancel(rec["id"])
            self.assertTrue(wait(lambda: not self.ex.is_busy()))
        p = self.ex.public(rec["id"])
        self.assertEqual(list(p), ["id", "state", "outDir", "folder", "waiting", "items", "combined"])   # GET /api/export の形
        self.assertEqual((p["id"], p["state"], p["items"][0]["status"], p["waiting"], p["combined"]), (rec["id"], "cancelled", "cancelled", False, None))
        self.assertEqual(p["outDir"], studio_env.get_out_dir())

    def test_cancel_all_marks_interrupted(self):
        with patch.object(exporter, "run", side_effect=slow_run):
            rec = self.ex.start(spec())
            self.assertEqual([r["id"] for r in self.ex.cancel_all()], [rec["id"]])
            self.assertTrue(wait(lambda: not self.ex.is_busy()))
        self.assertTrue(rec["interrupted"])
        self.assertEqual(rec["res"]["state"], "cancelled")
        self.assertEqual(self.ex.cancel_all(), [])

    def test_unexpected_error_settles(self):
        rec = self.ex.table._new(spec(), "export", "", {"videoId": "abcdefghijk", "outDir": "", "res": exporter.new_result(spec())})
        rec["state"] = "running"
        self.ex.table.jobs[rec["id"]] = rec
        with patch.object(exporter, "_run_job", side_effect=ValueError("boom")), patch.object(studio_env, "log_failure"):
            self.ex.table.work(rec)   # 糸の中身(② の器 flow/jobs.Table。OPT2 の J6)。想定外の例外は糸の外へ出さない
        self.assertEqual(rec["state"], "error")
        self.assertEqual((rec["res"]["state"], rec["res"]["items"][0]["status"]), ("error", "error"))
        self.assertIn("studio-errors.log", rec["res"]["items"][0]["error"])
        self.assertIsNotNone(rec["finishedAt"])


class TestHeavySlot(Base):
    """書き出しは、他のツールの重い処理と順番を待つ(ytt.jobs)。待っている間は waiting、取り消せる"""

    def test_waits_and_cancels(self):
        slots = jobs.HeavySlots(1)
        held = slots.acquire("transcribe")
        with patch.object(jobs, "SLOTS", slots), patch.object(exporter, "run") as body:
            rec = self.ex.start(spec())
            self.assertTrue(wait(lambda: rec["waiting"]))
            self.assertTrue(self.ex.public(rec["id"])["waiting"])
            self.assertEqual(self.ex.board_jobs()[0]["phase"], "順番待ち")
            self.ex.cancel(rec["id"])
            self.assertTrue(wait(lambda: not self.ex.is_busy()))
            body.assert_not_called()
            p = self.ex.public(rec["id"])
            self.assertEqual((p["state"], p["items"][0]["status"], p["waiting"]), ("cancelled", "cancelled", False))
            slots.release(held)
            rec2 = self.ex.start(spec())
            self.assertTrue(wait(lambda: body.called))
            self.assertTrue(wait(lambda: rec2["finishedAt"] is not None))


class TestBoard(Base):
    def test_states_and_cancel(self):
        board = B.Board()
        self.ex.attach_board(board)
        gate = threading.Event()

        def run(spec, res, ctl, on_done=None):
            gate.wait(5)
            slow_run(spec, res, ctl)
        with patch.object(exporter, "run", side_effect=run):
            rec = self.ex.start(spec(n=2))
            board.refresh()
            self.assertEqual(board.get("ex:" + rec["id"])["state"], "running")
            gate.set()
            board.cancel("ex:" + rec["id"])
            self.assertTrue(rec["ctl"].cancelled)
            self.assertTrue(wait(lambda: not self.ex.is_busy()))
        board.refresh()
        self.assertEqual(board.get("ex:" + rec["id"])["state"], "cancelled")
        with self.assertRaises(B.Refused):
            board.cancel("ex:" + rec["id"])
        with self.assertRaises(B.NotFound):
            board.cancel("ex:nai")

    def test_default_is_one_per_process(self):
        self.assertIs(E.default(), E.default())


if __name__ == "__main__":
    unittest.main()
