# -*- coding: utf-8 -*-
"""pipeline/analyze/breaks.py(話の切れ目)のテスト。  py -3.10 -m unittest src/pipeline/analyze/tests/test_breaks.py -v
- cuts: 間の切れ目・句読点と終助詞の加点・間が短くても句読点なら切れ目・最初と最後・壊れた行・空
- snap: 近くて点の高い方を選ぶ・radius の外は動かさない・短くなりすぎるなら動かさない
- inside_row: 端が行の中か
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests の 3 つ上 = src
sys.path.insert(0, REPO)
from pipeline.analyze import breaks  # noqa: E402


def row(s, e, text=""):
    return {"start": s, "end": e, "text": text}


class CutsTest(unittest.TestCase):
    def test_gap_cut(self):
        cs = breaks.cuts([row(0, 2, "あ"), row(3, 5, "い")])
        self.assertEqual(len(cs), 2)
        self.assertAlmostEqual(cs[0]["t"], 2.5)
        self.assertAlmostEqual(cs[0]["gap"], 1.0)
        self.assertEqual(cs[0]["kind"], "gap")
        self.assertAlmostEqual(cs[0]["score"], 1.0)

    def test_gap_capped(self):
        cs = breaks.cuts([row(0, 1, "あ"), row(11, 12, "い")])
        self.assertAlmostEqual(cs[0]["score"], breaks.GAP_CAP)

    def test_punct_bonus(self):
        cs = breaks.cuts([row(0, 2, "はい。"), row(3, 5, "次")])
        self.assertEqual(cs[0]["kind"], "punct")
        self.assertAlmostEqual(cs[0]["score"], 1.0 + breaks.PUNCT_BONUS)

    def test_ascii_question_is_punct(self):
        cs = breaks.cuts([row(0, 2, "本当?"), row(3, 5, "次")])
        self.assertEqual(cs[0]["kind"], "punct")

    def test_tail_bonus(self):
        cs = breaks.cuts([row(0, 2, "そうだよ"), row(3, 5, "次")])
        self.assertEqual(cs[0]["kind"], "punct")
        self.assertAlmostEqual(cs[0]["score"], 1.0 + breaks.TAIL_BONUS)

    def test_trailing_spaces_ignored(self):
        cs = breaks.cuts([row(0, 2, "はい。   "), row(3, 5, "次")])
        self.assertEqual(cs[0]["kind"], "punct")

    def test_short_gap_with_punct_is_cut(self):
        cs = breaks.cuts([row(0, 2, "はい。"), row(2.1, 4, "次")])
        self.assertEqual(len(cs), 2)
        self.assertAlmostEqual(cs[0]["t"], 2.05)
        self.assertEqual(cs[0]["kind"], "punct")
        self.assertAlmostEqual(cs[0]["score"], breaks.PUNCT_BONUS)

    def test_short_gap_without_punct_is_not_cut(self):
        cs = breaks.cuts([row(0, 2, "あ"), row(2.1, 4, "次")])
        self.assertEqual(len(cs), 1)   # 末尾の切れ目だけ

    def test_first_and_last_edges(self):
        cs = breaks.cuts([row(5, 6, "あ")])
        self.assertEqual(len(cs), 2)
        self.assertAlmostEqual(cs[0]["t"], 4.8)
        self.assertEqual(cs[0]["kind"], "gap")
        self.assertAlmostEqual(cs[0]["score"], breaks.GAP_CAP)
        self.assertAlmostEqual(cs[1]["t"], 6.2)
        self.assertAlmostEqual(cs[1]["score"], breaks.GAP_CAP)

    def test_no_head_cut_when_speech_starts_early(self):
        cs = breaks.cuts([row(0.2, 1, "あ")])
        self.assertEqual([c["t"] for c in cs], [1.2])

    def test_head_clamped_at_zero(self):
        cs = breaks.cuts([row(0.5, 1, "あ")])
        self.assertAlmostEqual(cs[0]["t"], 0.3)

    def test_broken_rows_skipped(self):
        rows = [{"start": "x", "end": 1, "text": "a"}, row(3, 2, "b"), None, row(5, 6, "c")]
        cs = breaks.cuts(rows)
        self.assertEqual([round(c["t"], 2) for c in cs], [4.8, 6.2])

    def test_missing_text_is_gap(self):
        cs = breaks.cuts([{"start": 0, "end": 2}, {"start": 3, "end": 4}])
        self.assertEqual(cs[0]["kind"], "gap")

    def test_empty(self):
        self.assertEqual(breaks.cuts([]), [])
        self.assertEqual(breaks.cuts(None), [])

    def test_sorted_by_t(self):
        cs = breaks.cuts([row(0, 1, "あ"), row(5, 6, "い"), row(10, 11, "う")])
        ts = [c["t"] for c in cs]
        self.assertEqual(ts, sorted(ts))


class SnapTest(unittest.TestCase):
    CS = [{"t": 10.0, "gap": 1.0, "kind": "gap", "score": 1.0},
          {"t": 12.0, "gap": 1.0, "kind": "punct", "score": 2.0}]

    def test_picks_higher_score_nearby(self):
        # a=9: t=10 は 1/1.1 = 0.91、t=12 は 2/1.3 = 1.54 なので 12
        a2, b2, info = breaks.snap(9.0, 100.0, self.CS)
        self.assertAlmostEqual(a2, 12.0)
        self.assertEqual(info["in"], [9.0, 12.0, "punct"])
        self.assertEqual(info["out"], [100.0, 100.0, None])

    def test_nearest_wins_when_scores_equal(self):
        cs = [{"t": 10.0, "gap": 1.0, "kind": "gap", "score": 1.0},
              {"t": 14.0, "gap": 1.0, "kind": "gap", "score": 1.0}]
        a2, _b2, info = breaks.snap(11.0, 100.0, cs)
        self.assertAlmostEqual(a2, 10.0)
        self.assertEqual(info["in"][2], "gap")

    def test_outside_radius_not_moved(self):
        a2, b2, info = breaks.snap(-1.0, 50.0, self.CS)   # 最も近い 10 までは距離 11
        self.assertEqual((a2, b2), (-1.0, 50.0))
        self.assertEqual(info["in"], [-1.0, -1.0, None])
        self.assertEqual(info["out"], [50.0, 50.0, None])

    def test_too_short_not_moved(self):
        # 両端とも 12 へ寄ると長さが 0 になるので、どちらも動かさない
        a2, b2, info = breaks.snap(10.0, 14.0, [self.CS[1]])
        self.assertEqual((a2, b2), (10.0, 14.0))
        self.assertEqual(info["in"], [10.0, 10.0, None])
        self.assertEqual(info["out"], [14.0, 14.0, None])

    def test_no_cuts(self):
        a2, b2, info = breaks.snap(3.0, 40.0, [])
        self.assertEqual((a2, b2), (3.0, 40.0))
        self.assertIsNone(info["in"][2])

    def test_custom_radius(self):
        a2, _b2, _info = breaks.snap(9.0, 100.0, self.CS, radius=2.0)
        self.assertAlmostEqual(a2, 10.0)   # 10 は距離 1 で 2.0 の中。12 は距離 3 で外
        a3, _b3, _i = breaks.snap(7.0, 100.0, self.CS, radius=2.0)
        self.assertAlmostEqual(a3, 7.0)    # 10 は距離 3 で外


class InsideRowTest(unittest.TestCase):
    def test_inside_only_strict(self):
        rows = [row(1, 3, "あ")]
        self.assertTrue(breaks.inside_row(2, rows))
        self.assertFalse(breaks.inside_row(1, rows))
        self.assertFalse(breaks.inside_row(3, rows))
        self.assertFalse(breaks.inside_row(0, rows))

    def test_broken_rows_ignored(self):
        self.assertFalse(breaks.inside_row(2, [row(3, 1, "x"), None]))
        self.assertFalse(breaks.inside_row(2, []))


if __name__ == "__main__":
    unittest.main()
