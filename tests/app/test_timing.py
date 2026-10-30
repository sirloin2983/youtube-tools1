"""ホームの読み込みの記録(src/app/timing.py): 遅い口・失敗した口だけを api-timing.jsonl へ、画面の 1 行を ui-timing.jsonl へ。
実行(リポジトリ直下から): python -m unittest tests/app/test_timing.py -v
"""
import json
import os
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import timing as T  # noqa: E402


def lines(d, name):
    p = os.path.join(d, name)
    return [json.loads(x) for x in open(p, encoding="utf-8")] if os.path.exists(p) else []


class TestTiming(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_api_only_slow_or_failed(self):
        """速くて成功した口は書かない・遅い口と失敗(400 以上・応答なし)は 1 行(道の ? の後は外す)"""
        self.assertFalse(T.api_record(self.d, 1.0, "GET", "/api/status", 0.1, 200, 10, 1))
        self.assertTrue(T.api_record(self.d, 2.0, "GET", "/api/cases?view=home", 13.2, 200, 367000, 4, {"lock": 9.1}, {"runs": 1, "rec": 2}))
        self.assertTrue(T.api_record(self.d, 3.0, "POST", "/api/cases/auto", 0.1, 409, 50, 1))
        self.assertTrue(T.api_record(self.d, 4.0, "GET", "/api/health", 0.2, None, None, 2))
        got = lines(self.d, T.API_NAME)
        self.assertEqual([g["p"] for g in got], ["/api/cases", "/api/cases/auto", "/api/health"])
        self.assertEqual((got[0]["sec"], got[0]["waits"], got[0]["busy"], got[0]["inflight"]), (13.2, {"lock": 9.1}, {"runs": 1, "rec": 2}, 4))

    def test_inflight_counts(self):
        T.begin()
        T.begin()
        self.assertEqual(T.end(), 2)
        self.assertEqual(T.end(), 1)

    def test_ui_record_checks_shape(self):
        row = T.ui_record(self.d, {"page": "cases", "state": "stuck", "ms": 60012.4,
                                   "calls": [["/api/cases", 120, -1, ""], ["/api/flow/status?case=x", 130, 40, 200], ["bad"], ["/x", 1, 2, "evil"]]}, "0.99.385", now=5.0)
        self.assertEqual(row["calls"], [["/api/cases", 120, -1, ""], ["/api/flow/status", 130, 40, 200], ["/x", 1, 2, None]])
        self.assertEqual((row["ms"], row["v"]), (60012, "0.99.385"))
        self.assertEqual(lines(self.d, T.UI_NAME), [row])
        for bad in ({"page": "x", "state": "done"}, {"page": "home", "state": "nope"}, []):
            with self.assertRaises(ValueError):
                T.ui_record(self.d, bad, "v")


if __name__ == "__main__":
    unittest.main()
