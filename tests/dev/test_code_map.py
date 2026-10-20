"""dev/code_map.py(コードの地図と言葉の索引を作る道具)の古さの判定と書き出しのテスト。リポジトリ直下で:

    py -3.12 -m unittest dev/tests/test_code_map.py
"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 本物の作業データに触らない(test_ytt_core の「serve の語があるテストは YTT_DATA_DIR」)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import code_map  # noqa: E402


class CodeMapTest(unittest.TestCase):
    def test_stale(self):
        with tempfile.TemporaryDirectory() as d:
            old = code_map.OUT
            code_map.OUT = d
            try:
                pages = {"index.md": "a\n", "x.md": "b\n"}
                self.assertEqual(code_map.stale(pages), ["index.md", "x.md"])
                code_map.write(pages)
                self.assertEqual(code_map.stale(pages), [])
                with open(os.path.join(d, "gone.md"), "w") as f:
                    f.write("z")
                self.assertEqual(code_map.stale(pages), ["gone.md"])
                self.assertEqual(code_map.stale({"index.md": "a\n", "x.md": "c\n"}), ["gone.md", "x.md"])
            finally:
                code_map.OUT = old


if __name__ == "__main__":
    unittest.main()
