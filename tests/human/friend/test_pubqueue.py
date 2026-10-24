"""src/human/friend/pubqueue.py(友人の zip を配る待ちの列と 3 時間ごとの配る回)のテスト。リポジトリ直下で:

    py -3.12 -m unittest tests/human/friend/test_pubqueue.py

一時フォルダだけを使う。配る道具は起こさない(spawn を差し替え)。
"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from human.friend import pubqueue as Q, upwatch as U  # noqa: E402


class FakeProc:
    def __init__(self, pid):
        self.pid, self.rc = pid, None

    def poll(self):
        return self.rc


class PubQueueTest(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.now = datetime.datetime(2026, 10, 25, 10, 30).timestamp()   # 9 時の区切りの中
        self.spawned = []
        os.environ.pop(Q.SWITCH_ENV, None)

    def tearDown(self):
        Q._running.clear()
        shutil.rmtree(self.app, ignore_errors=True)

    def spawn(self, cmd, cwd, out):
        p = FakeProc(5000 + len(self.spawned))
        self.spawned.append((cmd, cwd, p))
        return p

    def tick(self):
        return Q.tick(self.app, "C:/repo", lambda: self.now, spawn=self.spawn)

    def test_add_take_changes(self):
        Q.add(self.app, "直した A", "0.99.1", now=self.now)
        Q.add(self.app, "直した A", "0.99.2", now=self.now + 1)
        Q.add(self.app, "直した B", "0.99.3", now=self.now + 10)
        self.assertEqual(Q.changes(Q.items(self.app)), ["直した A", "直した B"])   # 同じ一言は 1 つ
        got = Q.take(self.app, int((self.now + 5) * 1000))
        self.assertEqual(len(got), 2)
        self.assertEqual([x["note"] for x in Q.items(self.app)], ["直した B"])      # 配っている間に積んだ物は次の回へ

    def test_once_per_slot_and_only_when_queued(self):
        self.tick()
        self.assertEqual(self.spawned, [])                                  # 何も無ければ何もしない
        Q.add(self.app, "直した", "0.99.1", now=self.now)
        self.now += 600
        self.tick()
        self.assertEqual(self.spawned, [])                                  # 同じ区切りの中では配らない(次の区切りを待つ)
        self.now = datetime.datetime(2026, 10, 25, 12, 1).timestamp()
        run = self.tick()
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("--from-queue", self.spawned[0][0])
        self.assertEqual(run["slot"], "20261025-12")
        self.spawned[0][2].rc = 0
        Q.take(self.app, int(run["started"] * 1000))                       # 配る道具が列から外した
        self.now += 60
        self.tick()
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(U.alerts(self.app, self.now), [])

    def test_missed_slot_runs_once_after_restart(self):
        Q.add(self.app, "直した", "0.99.1", now=self.now)
        self.tick()                                                         # 9 時の区切りを見た
        self.now = datetime.datetime(2026, 10, 25, 22, 0).timestamp()       # 入口が落ちていて 12・15・18 を逃した
        Q._running.clear()
        self.tick()
        self.assertEqual(len(self.spawned), 1)

    def test_failed_publish_alerts_and_keeps_queue(self):
        Q.add(self.app, "直した", "0.99.1", now=self.now - 3600)
        self.tick()                                                         # 初めての見回りは区切りを覚えるだけ
        self.now = datetime.datetime(2026, 10, 25, 12, 1).timestamp()
        self.tick()
        self.spawned[0][2].rc = 1                                           # 配れなかった(列が残る)
        self.now += 60
        self.tick()
        got = U.alerts(self.app, self.now)
        self.assertEqual(got[0]["level"], "warn")
        self.assertEqual(len(Q.items(self.app)), 1)

    def test_switch_off(self):
        Q.add(self.app, "直した", "0.99.1", now=self.now)
        self.tick()
        os.environ[Q.SWITCH_ENV] = "0"
        try:
            self.now = datetime.datetime(2026, 10, 25, 12, 1).timestamp()
            self.tick()
        finally:
            os.environ.pop(Q.SWITCH_ENV, None)
        self.assertEqual(self.spawned, [])


if __name__ == "__main__":
    unittest.main()
