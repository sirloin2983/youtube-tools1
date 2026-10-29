# -*- coding: utf-8 -*-
"""自動の起動し直しの判定(src/ytt/autorestart.py)のテスト。  python -m unittest tests/ytt/test_autorestart.py -v

待つ・起こす・1 版 1 回・失敗したら手で、を値だけで確かめる(本物の起動はしない)"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import autorestart as A  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
from testkit import tempdir  # noqa: E402


class TestDecide(unittest.TestCase):
    def test_same_or_unreadable_version_does_nothing(self):
        self.assertEqual(A.decide("0.1", "0.1", "", None)[0], A.NOTHING)
        self.assertEqual(A.decide("", "0.1", "", None)[0], A.NOTHING)

    def test_busy_waits_then_goes(self):
        self.assertEqual(A.decide("0.2", "0.1", "", "文字起こし"), (A.WAIT, "文字起こし"))
        self.assertEqual(A.decide("0.2", "0.1", "", None), (A.GO, ""))

    def test_once_per_version(self):
        act, why = A.decide("0.2", "0.1", "0.2", None)   # 試したのに動いている版が変わっていない = 手に任せる
        self.assertEqual(act, A.NOTHING)
        self.assertIn("手の", why)
        self.assertEqual(A.decide("0.2", "0.1", "0.2", "処理中")[0], A.NOTHING)   # 処理中でも試し済みは待たない
        self.assertEqual(A.decide("0.3", "0.1", "0.2", None)[0], A.GO)   # 次の版は改めて 1 回

    def test_tried_record(self):
        d = tempdir(self, "ytt-autorestart-")
        p = os.path.join(d, "app", A.STATE_NAME)
        self.assertEqual(A.read_tried(p), "")
        A.write_tried(p, "0.2", "0.1", now=5)
        self.assertEqual(A.read_tried(p), "0.2")

    def test_editor_in_use(self):
        self.assertFalse(A.editor_in_use(None, 100))
        self.assertTrue(A.editor_in_use(100, 100 + A.EDITOR_IDLE - 1))
        self.assertFalse(A.editor_in_use(100, 100 + A.EDITOR_IDLE))

    def test_settling_since_counts_from_first_difference(self):
        """待ちは版が違い始めた時から SETTLE_SEC だけ(続けて上がっても延びない = 10-29 の 18:13〜18:21 の land で起き直さなかった件)"""
        self.assertIsNone(A.settling_since(None, 100))
        self.assertIn("あと 10 分", A.settling_since(100, 100))
        self.assertIn("あと 1 分", A.settling_since(100, 100 + A.SETTLE_SEC - 1))
        self.assertIsNone(A.settling_since(100, 100 + A.SETTLE_SEC))


if __name__ == "__main__":
    unittest.main()
