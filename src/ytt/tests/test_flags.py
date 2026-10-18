# -*- coding: utf-8 -*-
"""行の印(flag)のつなぎ方・探し方(ytt.schemas の join_flags・has_flag・flag_parts)のテスト。  py -3.12 -m unittest src/ytt/tests/test_flags.py -v
純粋な関数だけ(ファイル・ffmpeg は使わない)。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from ytt import schemas as ys  # noqa: E402


class JoinFlagsTest(unittest.TestCase):
    def test_fixed_flags_come_first(self):
        out = ys.join_flags("ほかの印", ys.MACH_CHANGED)
        self.assertEqual(ys.flag_parts(out)[0], ys.MACH_CHANGED)
        self.assertEqual(out, ys.MACH_CHANGED + "、ほかの印")

    def test_fixed_flag_kept_whole_when_other_flag_is_long(self):
        out = ys.join_flags("あ" * 90, ys.MACH_CHANGED)
        self.assertLessEqual(len(out), ys.FLAG_MAX)
        self.assertTrue(ys.has_flag(out, ys.MACH_CHANGED))
        # MACH_CHANGED は 38 字・残りは 61 字。最初のほかの印は入る所まで切って残す
        self.assertEqual(out, ys.MACH_CHANGED + "、" + "あ" * (ys.FLAG_MAX - len(ys.MACH_CHANGED) - 1))

    def test_fixed_flags_not_cut_over_flag_max(self):
        fixed = [ys.MACH_CHANGED, ys.SPK_CHANGED, ys.STALE_FLAG, ys.EMPTY_FLAG, ys.MIXED_FLAG]
        out = ys.join_flags(*reversed(fixed))
        self.assertGreater(len(out), ys.FLAG_MAX)
        self.assertEqual(sorted(ys.flag_parts(out)), sorted(fixed))

    def test_same_flag_once_and_empty_dropped(self):
        self.assertEqual(ys.join_flags("a、a、", "", None, "a"), "a")
        self.assertEqual(ys.join_flags("", None), "")
        self.assertEqual(ys.join_flags(), "")
        self.assertEqual(ys.join_flags(ys.MACH_CHANGED, ys.MACH_CHANGED), ys.MACH_CHANGED)

    def test_idempotent(self):
        cases = [
            ("a", "b", "a"),
            ("あ" * 90, ys.MACH_CHANGED),
            (ys.MACH_CHANGED, "い" * 60, "う" * 60),
            ("う" * 99, "え" * 5),
            ("x" * 30, "y" * 30, "z" * 30, "w" * 30),
            (ys.STALE_FLAG, ys.EMPTY_FLAG, "か" * 80, "き" * 80),
        ]
        for c in cases:
            j = ys.join_flags(*c)
            self.assertEqual(ys.join_flags(j), j, c)
            self.assertEqual(ys.join_flags(j, j), j, c)

    def test_one_long_hand_written_flag_is_cut(self):
        out = ys.join_flags("あ" * 150)
        self.assertEqual(out, "あ" * ys.FLAG_MAX)


class HasFlagTest(unittest.TestCase):
    def test_whole_part_match_only(self):
        self.assertTrue(ys.has_flag(ys.join_flags("ほかの印", ys.MACH_CHANGED), ys.MACH_CHANGED))
        self.assertFalse(ys.has_flag(ys.MACH_CHANGED[:3], ys.MACH_CHANGED))   # 頭の文字だけの印では False
        self.assertFalse(ys.has_flag(ys.MACH_CHANGED + "x", ys.MACH_CHANGED))
        self.assertFalse(ys.has_flag("", ys.MACH_CHANGED))
        self.assertFalse(ys.has_flag(None, ys.MACH_CHANGED))


if __name__ == "__main__":
    unittest.main()
