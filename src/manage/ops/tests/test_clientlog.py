"""画面のエラーの記録(src/manage/ops/clientlog.py の ClientLog・clean)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest src/manage/ops/tests/test_clientlog.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> ops -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from manage.ops import clientlog as C  # noqa: E402


class TestClientLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-clog-")
        self.t = [1000.0]
        self.log = C.ClientLog(self.tmp, per_minute=3, max_bytes=400, clock=lambda: self.t[0])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lines(self, path=None):
        with open(path or self.log.path, encoding="utf-8") as f:
            return [json.loads(x) for x in f.read().splitlines()]

    def test_clean(self):
        e = C.clean({"kind": "evil", "message": "x" * 900, "stack": "s\n" * 2000, "line": 12, "col": True, "extra": "捨てる", "page": 5})
        self.assertEqual(e["kind"], "report")
        self.assertEqual(len(e["message"]), 500)
        self.assertEqual(len(e["stack"]), 2000)
        self.assertEqual(e["line"], 12)
        self.assertNotIn("col", e)
        self.assertNotIn("extra", e)
        self.assertNotIn("page", e)
        for bad in ({}, {"message": ""}, {"message": 3}, [], "x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                C.clean(bad)

    def test_one_line_per_entry_and_limit(self):
        self.log.max_bytes = 10 ** 6   # 回さない
        self.assertTrue(self.log.record("studio", {"kind": "error", "message": "a\n{\"tool\":\"fake\"}\r\nb"}, "0.7.0"))
        self.assertTrue(self.log.record("portal", {"message": "2"}))
        self.assertTrue(self.log.record("portal", {"message": "3"}))
        self.assertFalse(self.log.record("portal", {"message": "4"}))   # 1分に3件まで
        self.assertFalse(self.log.record("portal", {"message": "5"}))
        got = self.lines()
        self.assertEqual(len(got), 3)   # 改行を含むエラーの文でも1件は1行(偽の行を作れない)
        self.assertEqual((got[0]["tool"], got[0]["version"], got[0]["kind"]), ("studio", "0.7.0", "error"))
        self.assertIn("\n", got[0]["message"])
        self.t[0] += 61
        self.assertTrue(self.log.record("portal", {"message": "6"}))
        got = self.lines()
        self.assertEqual((got[3]["kind"], got[3]["count"]), ("dropped", 2))   # 書かなかった件数を残す
        self.assertEqual(got[4]["message"], "6")

    def test_rotation(self):
        for i in range(12):
            self.t[0] += 61
            self.log.record("portal", {"message": "m%d" % i + "x" * 60})
        self.assertTrue(os.path.exists(self.log.path + ".1"))
        self.assertLess(os.path.getsize(self.log.path), 400 + 200)


if __name__ == "__main__":
    unittest.main()
