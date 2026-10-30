"""確かめるの集め(deck._collect)の「覚えを先に返して裏で集め直す」(10-25 答えたあとの読み込みの待ちを無くす)"""
import os
import sys
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))
from app.check import deck, sources  # noqa: E402


class Ctx:
    app_dir, root = "app", "root"


class St:
    rev = 1


class DeckStaleTest(unittest.TestCase):
    def setUp(self):
        deck.invalidate()
        self.addCleanup(deck.invalidate)
        self.calls, self.gate = [], threading.Event()

    def collect(self, ctx, st):
        self.calls.append(st.rev)
        if len(self.calls) > 1:
            self.gate.wait(5)   # 2 回目(裏の集め直し)は遅い
        view = mock.Mock(errors=[])
        return [{"id": "c%d" % len(self.calls)}], view

    def test_stale_is_returned_and_refreshed_in_background(self):
        with mock.patch.object(sources, "collect", self.collect):
            cards, _ = deck._collect(Ctx(), St())   # 覚えが無い = 待って集める
            self.assertEqual(cards, [{"id": "c1"}])
            deck.mark_stale()
            st2 = St()
            st2.rev = 2
            t0 = time.monotonic()
            cards, _ = deck._collect(Ctx(), st2)   # 答えた後 = 覚えを先に返す(待たない)
            self.assertLess(time.monotonic() - t0, 0.5)
            self.assertEqual(cards, [{"id": "c1"}])
            self.gate.set()
            for _ in range(50):
                if not deck._refreshing["on"]:
                    break
                time.sleep(0.05)
            cards, _ = deck._collect(Ctx(), st2)
            self.assertEqual(cards, [{"id": "c2"}])   # 裏の集め直しの結果
            self.assertEqual(self.calls, [1, 2])

    def test_cold_collect_is_shared(self):
        """10-30: 覚えが無い時(起動の直後)に同時に来た頼みは、走っている 1 回の集めを待って分け合う(前は 7〜8 本が別々に集めて 1 本 15〜34 秒)"""
        started = threading.Event()

        def slow(ctx, st):
            self.calls.append(st.rev)
            started.set()
            self.gate.wait(5)
            return [{"id": "c%d" % len(self.calls)}], mock.Mock(errors=[])
        out = []
        with mock.patch.object(sources, "collect", slow):
            ths = [threading.Thread(target=lambda: out.append(deck._collect(Ctx(), St())[0]))]
            ths[0].start()
            started.wait(5)
            ths += [threading.Thread(target=lambda: out.append(deck._collect(Ctx(), St())[0])) for _ in range(6)]
            [t.start() for t in ths[1:]]
            time.sleep(0.2)
            self.gate.set()
            [t.join(5) for t in ths]
        self.assertEqual(self.calls, [1])
        self.assertEqual(out, [[{"id": "c1"}]] * 7)
        self.assertIsNone(deck._cold["ev"])

    def test_other_app_dir_is_not_served_stale(self):
        with mock.patch.object(sources, "collect", lambda ctx, st: ([{"id": ctx.app_dir}], mock.Mock(errors=[]))):
            deck._collect(Ctx(), St())
            other = Ctx()
            other.app_dir = "other"
            self.assertEqual(deck._collect(other, St())[0], [{"id": "other"}])


if __name__ == "__main__":
    unittest.main()
