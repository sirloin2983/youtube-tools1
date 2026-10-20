# -*- coding: utf-8 -*-
"""行の印(flag)のつなぎ方・探し方(ytt.schemas の join_flags・has_flag・flag_parts)のテスト。  py -3.12 -m unittest tests/ytt/test_flags.py -v
印の組の見本(決まった印・長い手書きの印・同じ印・空・決まった印だけで上限を超える)を join_flags に通し、並び・長さ・やり直しても同じかをまとめて確かめる。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import sys
import unittest

REPO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, REPO)
from ytt import schemas as ys  # noqa: E402


class FlagsTest(unittest.TestCase):
    def test_join_and_find(self):
        MC = ys.MACH_CHANGED
        fixed = [MC, ys.SPK_CHANGED, ys.STALE_FLAG, ys.EMPTY_FLAG, ys.MIXED_FLAG]
        cases = [   # (つなぐ印, 答え)。答え None は長さと中身だけ見る
            (("ほかの印", MC), MC + "、ほかの印"),                                        # 決まった印が先
            (("あ" * 90, MC), MC + "、" + "あ" * (ys.FLAG_MAX - len(MC) - 1)),          # 決まった印は切らず、ほかの印を入る所まで切る
            (("a、a、", "", None, "a"), "a"), (("", None), ""), ((), ""), ((MC, MC), MC),   # 同じ印は 1 回・空は捨てる
            (("あ" * 150,), "あ" * ys.FLAG_MAX),                                         # 長い手書きの印 1 つは切る
            (tuple(reversed(fixed)), None),                                              # 決まった印だけなら上限を超えても切らない
            (("a", "b", "a"), None), ((MC, "い" * 60, "う" * 60), None), (("う" * 99, "え" * 5), None),
            (("x" * 30, "y" * 30, "z" * 30, "w" * 30), None), ((ys.STALE_FLAG, ys.EMPTY_FLAG, "か" * 80, "き" * 80), None),
        ]
        for parts, want in cases:
            with self.subTest(parts=parts):
                j = ys.join_flags(*parts)
                if want is not None:
                    self.assertEqual(j, want)
                elif parts == tuple(reversed(fixed)):
                    self.assertGreater(len(j), ys.FLAG_MAX)
                    self.assertEqual(sorted(ys.flag_parts(j)), sorted(fixed))
                else:
                    self.assertLessEqual(len(j), ys.FLAG_MAX)
                self.assertEqual((ys.join_flags(j), ys.join_flags(j, j)), (j, j))   # やり直しても同じ
        self.assertEqual(ys.flag_parts(ys.join_flags("ほかの印", MC))[0], MC)
        self.assertTrue(ys.has_flag(ys.join_flags("あ" * 90, MC), MC))
        for flag, want in ((ys.join_flags("ほかの印", MC), True), (MC[:3], False), (MC + "x", False), ("", False), (None, False)):   # 印の丸ごとだけが当たる
            self.assertIs(ys.has_flag(flag, MC), want, flag)


if __name__ == "__main__":
    unittest.main()
