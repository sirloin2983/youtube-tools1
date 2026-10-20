# -*- coding: utf-8 -*-
"""pipeline/analyze/breaks.py(話の切れ目)のテスト。  py -3.12 -m unittest src/pipeline/analyze/tests/test_breaks.py -v
パックと同じ順(cuts → snap)で、行の並びの見本(頭の余白・間・句読点・半角の ?・終助詞・語尾の空白・短い間・壊れた行・文字の無い行・長い間)を 1 回通し、
切れ目の一覧と寄せた端をまとめて確かめる。
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests の 3 つ上 = src
sys.path.insert(0, REPO)
from pipeline.analyze import breaks  # noqa: E402


def row(s, e, text=""):
    return {"start": s, "end": e, "text": text}


ROWS = [row(0.5, 2, "あ"),                                                   # 頭の切れ目は 0 で止まらず 0.3
        row(3, 5, "はい。"),                                                 # 間 1 秒・前の行は句読点なし = gap 1.0
        {"start": "x", "end": 1, "text": "a"}, None, row(9, 8, "壊"),        # 壊れた行は飛ばす
        row(6, 8, "本当?"),                                                  # 前の「はい。」= 句読点の加点
        row(9, 10, "そうだよ"),                                              # 前の「本当?」= 半角の ? も句読点
        row(11, 12, "はい。   "),                                            # 前の「そうだよ」= 終助詞の加点
        row(12.1, 13, "次"),                                                 # 間 0.1 秒でも前が句読点(語尾の空白は見ない)なら切れ目
        row(13.1, 14, "あ"),                                                 # 間 0.1 秒・句読点なし = 切れ目にしない
        {"start": 15, "end": 16},                                            # 文字の無い行は間として扱う
        row(30, 31, "う")]                                                   # 14 秒の間は GAP_CAP で頭打ち


class BreaksRunTest(unittest.TestCase):
    def test_cuts_then_snap(self):
        cs = breaks.cuts(ROWS)
        P, T = breaks.PUNCT_BONUS, breaks.TAIL_BONUS
        self.assertEqual([(round(c["t"], 2), c["kind"], round(c["score"], 2)) for c in cs],
                         [(0.3, "gap", breaks.GAP_CAP), (2.5, "gap", 1.0), (5.5, "punct", 1.0 + P), (8.5, "punct", 1.0 + P),
                          (10.5, "punct", 1.0 + T), (12.05, "punct", P), (14.5, "gap", 1.0), (23.0, "gap", breaks.GAP_CAP),
                          (31.2, "gap", breaks.GAP_CAP)])   # t の順・最後の行の後ろにも切れ目
        self.assertAlmostEqual(cs[7]["gap"], 14.0)
        self.assertEqual([c["t"] for c in breaks.cuts([row(0.2, 1, "あ")])], [1.2])   # 0 秒近くから始まる話に頭の切れ目は作らない
        self.assertEqual((breaks.cuts([]), breaks.cuts(None)), ([], []))

        snap = breaks.snap
        self.assertEqual(snap(13.0, 60.0, cs), (23.0, 60.0, {"in": [13.0, 23.0, "gap"], "out": [60.0, 60.0, None]}))   # 近い低い点より少し遠い高い点・半径の外は動かさない
        a, b, info = snap(6.5, 30.0, cs, radius=3.0)                         # 同じ点(5.5 と 8.5)なら近い方
        self.assertEqual((a, b, info["in"][2], info["out"][2]), (5.5, 31.2, "punct", "gap"))
        self.assertEqual(snap(9.0, 30.0, cs, radius=1.0)[:2], (8.5, 30.0))
        for why, a, b, kw in (("半径の外", -20.0, 50.0, {}), ("短くなりすぎ", 22.0, 24.0, {"radius": 3.0})):
            with self.subTest(why):
                self.assertEqual(snap(a, b, cs, **kw), (a, b, {"in": [a, a, None], "out": [b, b, None]}))
        self.assertEqual(snap(3.0, 40.0, []), (3.0, 40.0, {"in": [3.0, 3.0, None], "out": [40.0, 40.0, None]}))


if __name__ == "__main__":
    unittest.main()
