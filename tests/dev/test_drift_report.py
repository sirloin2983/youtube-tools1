"""dev/drift_report.py の索引の判定。リポジトリ直下で:

    py -3.12 -m unittest tests/dev/test_drift_report.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dev"))
import drift_report as D  # noqa: E402


class IsIndexTest(unittest.TestCase):
    def test_head_only(self):
        self.assertTrue(D.is_index("---\r\n種類: 索引\r\n状態: 有効\r\n---\r\n本文"))
        self.assertTrue(D.is_index("---\n状態: 有効\n種類: 索引\n---\n"))
        self.assertFalse(D.is_index("---\r\n種類: 記録\r\n---\r\n種類: 索引\r\n"))   # 本文の中は見ない
        self.assertFalse(D.is_index("本文\n種類: 索引"))

    def test_long_crlf_document_is_quick(self):
        """索引でない長い CRLF の文書でも一瞬(行を繰り返す正規表現はバックトラックで止まらなくなる)"""
        big = "---\r\n種類: 記録\r\n" + ("い" * 80 + "\r\n") * 3000
        t0 = time.monotonic()
        self.assertFalse(D.is_index(big))
        self.assertLess(time.monotonic() - t0, 1.0)


if __name__ == "__main__":
    unittest.main()
