# -*- coding: utf-8 -*-
"""flow/packjobs.py(パックのジョブの器。OPT2 J3): 同時 1 本・取り消し・履歴・SLOTS・掲示板の形"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parents[1] / "src"))

from flow import board as B  # noqa: E402
from flow.packjobs import KEEP_JOBS, PackJobs  # noqa: E402
from pipeline.pack import cut2resolve_core as C  # noqa: E402
from ytt import jobs  # noqa: E402
from ytt.errors import ApiError  # noqa: E402


def wait(job, n=200):
    for _ in range(n):
        if job.state != "running":
            break
        time.sleep(0.02)
    return job


class TestPackJobs(unittest.TestCase):
    def test_one_at_a_time_and_public_shape(self):
        pj = PackJobs("t")
        gate = threading.Event()
        job = pj.start_job("plan", lambda task: gate.wait(5) and {"ok": 1})
        with self.assertRaises(ApiError) as cm:
            pj.start_job("plan", lambda task: 1)
        self.assertEqual((cm.exception.code, cm.exception.status), ("busy", 409))
        gate.set()
        wait(job)
        d = job.public()
        self.assertEqual((d["state"], d["result"], sorted(d)), ("done", {"ok": 1}, ["elapsed", "id", "kind", "message", "progress", "result", "state"]))
        self.assertIsNotNone(pj.start_job("plan", lambda task: 2))   # 終わったら次を受ける

    def test_cancel_and_errors(self):
        pj = PackJobs("t")
        gate = threading.Event()
        job = pj.start_job("plan", lambda task: gate.wait(5) and task.check())
        pj.board_cancel(job.id)
        gate.set()
        self.assertEqual((wait(job).state, job.message), ("cancelled", "取り消しました"))
        with self.assertRaises(LookupError):
            pj.board_cancel("nothere")
        e = wait(pj.start_job("plan", lambda task: 1 / 0))
        self.assertEqual((e.state, e.error["code"]), ("error", "internal"))

        def tool(task):
            raise C.ToolError("だめ")
        last = wait(pj.start_job("plan", tool))
        self.assertEqual(last.error["code"], "tool")
        self.assertIs(pj.job(last.id).id, last.id)
        with self.assertRaises(ApiError):
            pj.job("nothere")
        self.assertIsNone(pj.running_now())
        self.assertEqual(pj.table.keep, KEEP_JOBS)   # 履歴の削り方そのものは test_jobs_table の test_retry_and_history

    def test_build_always_waits_plan_only_when_heavy(self):
        slots = jobs.HeavySlots(1)
        held = slots.acquire("transcribe")
        with mock.patch.object(jobs, "SLOTS", slots):
            pj = PackJobs("t")
            ran = []
            b = pj.start_job("build", lambda task: ran.append(1) or "built")
            for _ in range(100):
                if b.message == jobs.WAIT_MESSAGE:
                    break
                time.sleep(0.02)
            self.assertEqual((b.state, ran), ("running", []))
            p = wait(PackJobs("t").start_job("plan", lambda task: "planned", heavy=lambda: False))
            self.assertEqual(p.state, "done")
            b.task.cancel()
            self.assertEqual((wait(b).state, ran), ("cancelled", []))
            slots.release(held)
            self.assertEqual(wait(pj.start_job("build", lambda task: "built")).state, "done")

    def test_board_shape(self):
        pj = PackJobs("t")
        b = B.Board()
        b.register("pk", source=pj.board_jobs, cancel=pj.board_cancel)
        done = wait(pj.start_job("plan", lambda task: {"outDir": "D:/x/pack"}))
        b.snapshot()
        d = b.get("pk:" + done.id)
        self.assertEqual((d["kind"], d["title"], d["state"], d["target"]), ("pack", "試算", "done", {"path": "D:/x/pack"}))
        bj = wait(pj.start_job("build", lambda task: 1))
        self.assertEqual(pj.board_jobs()[-1]["title"], "パックの作成")
        self.assertEqual(pj.board_jobs()[-1]["id"], "pk:" + bj.id)


if __name__ == "__main__":
    unittest.main()
