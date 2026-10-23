"""切り抜きの両端を話の間へ寄せる(pipeline/pack/edge_pause)の純粋な部分"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))
from pipeline.pack import edge_pause as E  # noqa: E402


def db_of(spans, n, loud=-10.0, quiet=-50.0):
    """20 ms ごとの音量: spans [(から, まで)](秒)が声・ほかは静か"""
    return [loud if any(a <= i * E.HOP < b for a, b in spans) else quiet for i in range(n)]


class EdgePauseTest(unittest.TestCase):
    def test_pauses_need_min_gap(self):
        db = db_of([(0, 1.0), (1.1, 2.0), (2.5, 4.0)], 200)   # 0.1 秒の切れ目は間でない・0.5 秒は間
        ps = E.pauses(db, 0.0, -10.0)
        self.assertEqual(len(ps), 1)
        self.assertAlmostEqual(ps[0][0], 2.0, places=2)
        self.assertAlmostEqual(ps[0][1], 2.5, places=2)

    def test_end_prefers_pause_after_and_start_prefers_pause_before(self):
        ps = [(8.0, 8.5), (10.6, 11.0)]
        self.assertAlmostEqual(E.snap_end(10.0, ps), 10.65)   # 言い終わりの後ろの間・声の側から 0.05 秒
        self.assertAlmostEqual(E.snap_start(10.0, ps), 8.45)   # 話し始めの前の間
        self.assertEqual(E.snap_end(10.0, []), 10.0)   # 間が無ければ動かさない
        self.assertEqual(E.snap_end(10.7, ps), 10.7)   # もう間の中

    def test_switch_off_keeps_edges(self):
        with mock.patch.object(E, "ON", False):
            self.assertEqual(E.snap("none.mp4", 10.0, 100.0, 120.0), (10.0, 100.0, None))


if __name__ == "__main__":
    unittest.main()
