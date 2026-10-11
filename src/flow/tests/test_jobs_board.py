# -*- coding: utf-8 -*-
"""flow/jobs の掲示板への見せ方(RS8 の ② の口 S2。頭 tx)。

    py -3.10 -m unittest src/flow/tests/test_jobs_board.py -v

- ジョブの状態が変わると、掲示板にその id(tx:<ジョブの id>)がその state で載る(引く形)
- 取り消し・失敗のやり直しが掲示板の口から器の cancel_job・retry_job に届く
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import board as B, jobs  # noqa: E402


class TestJobsBoard(unittest.TestCase):
    def setUp(self):
        saved = (dict(jobs._jobs), list(jobs._order), tuple(jobs.RETRY_KINDS))
        self.addCleanup(self._restore, saved)
        jobs._jobs.clear()
        jobs._order[:] = []
        jobs.RETRY_KINDS = ("transcribe",)
        self.board = B.Board()
        jobs.attach_board(self.board)

    @staticmethod
    def _restore(saved):
        jobs._jobs.clear()
        jobs._jobs.update(saved[0])
        jobs._order[:] = saved[1]
        jobs.RETRY_KINDS = saved[2]

    def test_state_changes_reach_board(self):
        job = jobs.add_job({"title": "配信 A", "tid": "t1"}, "transcribe")
        jid = "tx:" + job["id"]
        j = self.board.snapshot()["jobs"][0]
        self.assertEqual((j["id"], j["kind"], j["state"], j["waiting"], j["canCancel"]), (jid, "transcribe", "queued", True, True))
        job["state"], job["phase"], job["progress"] = "extracting", "音声を取り出し中", 0.2
        j = self.board.snapshot()["jobs"][0]
        self.assertEqual((j["state"], j["phase"], j["progress"], j["waiting"]), ("running", "音声を取り出し中", 0.2, False))
        job["state"], job["error"], job["errorCode"] = "error", "失敗しました", "x"
        j = self.board.snapshot()["jobs"][0]
        self.assertEqual((j["state"], j["error"]["code"], j["error"]["text"], j["canCancel"], j["canRetry"]), ("error", "x", "失敗しました", False, True))

    def test_cancel_and_retry_go_through(self):
        job = jobs.add_job({"title": "配信 B", "tid": "t2"}, "transcribe")
        got = self.board.cancel("tx:" + job["id"])
        self.assertEqual((got["state"], got["finishedAt"] is not None), ("cancelled", True))
        self.assertTrue(job["cancel"])
        with self.assertRaises(B.NotFound):
            self.board.cancel("tx:nothere")
        job["state"], job["error"] = "error", "失敗しました"
        new = self.board.retry("tx:" + job["id"])
        self.assertNotEqual(new["id"], "tx:" + job["id"])
        self.assertEqual(new["state"], "queued")


if __name__ == "__main__":
    unittest.main()
