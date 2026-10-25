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

    def test_other_app_dir_is_not_served_stale(self):
        with mock.patch.object(sources, "collect", lambda ctx, st: ([{"id": ctx.app_dir}], mock.Mock(errors=[]))):
            deck._collect(Ctx(), St())
            other = Ctx()
            other.app_dir = "other"
            self.assertEqual(deck._collect(other, St())[0], [{"id": "other"}])


if __name__ == "__main__":
    unittest.main()
