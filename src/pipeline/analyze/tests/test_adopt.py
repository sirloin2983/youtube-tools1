# -*- coding: utf-8 -*-
"""pipeline/analyze/adopt.py(採用の規則 F-5 の純粋な関数。RS8 B3-2 の G1a)と ② の口 flow/adopt のテスト。
    py -3.10 -m unittest src/pipeline/analyze/tests/test_adopt.py -v
期待値は store のテスト(src/human/review/tests/test_studio.py の TestAdoptRule)と同じ。保存を通した動きはそちらが確かめる。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import copy
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # src
from flow import adopt as flow_adopt  # noqa: E402
from pipeline.analyze import adopt as A  # noqa: E402
from ytt import marks as M, yturl  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

DUR = 600


def auto(i, s, e, score):
    """解析が足した自動マーク(候補・手つかず)"""
    return M.build_mark({"id": "a%d" % i, "start": s, "end": e, "src": "auto", "score": score, "auto0": [s, e]}, None, True)


def base():
    return [auto(1, 10, 40, 2.0), auto(2, 100, 130, 9.0), auto(3, 200, 230, 5.0), auto(4, 300, 330, 7.0)]


class TestAdoptRule(unittest.TestCase):
    def setUp(self):
        self.marks = base()

    def run_rule(self, ranges, top):
        r = A.adopt(self.marks, A.check_args(ranges, top), top, DUR)
        self.marks = r["marks"]
        return r

    def starts(self, ids):
        by = {m["id"]: m["start"] for m in self.marks}
        return [by[i] for i in ids]

    def set_status(self, start, status):
        self.marks = [M.build_mark(dict(m, status=status), m) if m["start"] == start else m for m in self.marks]

    def test_top_by_score(self):
        r = self.run_rule([], 2)
        self.assertEqual(self.starts(r["added"]), [100, 300])
        self.assertEqual({m["start"]: m.get("adoptedBy") for m in self.marks if m["status"] == "adopted"}, {100: "auto", 300: "auto"})
        r = self.run_rule([], 2)   # 再実行: 前に機械が採用した分を数に入れる(増やさない)
        self.assertEqual((self.starts(r["autoIds"]), r["humanIds"], r["added"]), ([100, 300], [], []))

    def test_human_adoption_counts_and_rest_is_filled(self):
        self.set_status(10, "adopted")
        r = self.run_rule([], 3)
        self.assertEqual(self.starts(r["added"]), [100, 300])
        r = self.run_rule([], 3)
        self.assertEqual((self.starts(r["humanIds"]), self.starts(r["autoIds"]), r["added"]), ([10], [100, 300], []))
        self.assertEqual(self.run_rule([], 1)["autoIds"], [])   # 人の分だけで上限

    def test_rejected_and_overlaps_are_skipped(self):
        self.set_status(100, "rejected")
        self.set_status(10, "adopted")
        r = self.run_rule([[305, 320]], 3)
        self.assertEqual(self.starts(r["rangeIds"]), [305])
        self.assertEqual((self.starts(r["humanIds"]), self.starts(r["autoIds"])), ([10], [200]))   # 300 は区間に重なる・100 は不採用
        self.assertEqual(sorted(self.starts(r["added"])), [200, 305])
        new = next(m for m in self.marks if m["start"] == 305)
        self.assertEqual((new["status"], new["adoptedBy"], new["src"]), ("adopted", "request", "manual"))
        self.assertEqual([m["start"] for m in self.marks], sorted(m["start"] for m in self.marks))   # 足したら時刻の順

    def test_ranges_beyond_top_are_all_taken(self):
        r = self.run_rule([[400, 420], [500, 520]], 1)
        self.assertEqual((self.starts(r["rangeIds"]), r["autoIds"]), ([400, 500], []))

    def test_range_reuses_same_mark_and_revives_rejected(self):
        self.set_status(200, "rejected")
        r = self.run_rule([[200.4, 229.6]], 0)   # ±0.5 秒の中 = 同じ区間
        self.assertEqual((self.starts(r["rangeIds"]), self.starts(r["added"])), ([200], [200]))
        m = next(m for m in self.marks if m["start"] == 200)
        self.assertEqual((m["status"], m["adoptedBy"], len(self.marks)), ("adopted", "request", 4))

    def test_input_is_not_changed(self):
        before = copy.deepcopy(self.marks)
        A.adopt(self.marks, [(400.0, 420.0)], 3, DUR)
        self.assertEqual(self.marks, before)

    def test_range_end_is_clamped_and_outside_is_refused(self):
        r = self.run_rule([[590, 700]], 0)
        self.assertEqual(next(m for m in self.marks if m["id"] == r["rangeIds"][0])["end"], 600.0)
        with self.assertRaises(ValueError):
            A.adopt(self.marks, [(600.0, 700.0)], 0, DUR)

    def test_bad_args(self):
        for ranges, top in (([], -1), ([], 31), ([], "1"), ([], None), ([], True), ([[1, 2]] * 11, 1), ("x", 1), ([[1]], 1), ([[5, 4]], 1)):
            with self.assertRaises(ValueError, msg=(ranges, top)):
                A.check_args(ranges, top)
        self.assertEqual(A.check_args([[1.04, 10.26]], 0), [(1.0, 10.3)])


class TestFlowVerb(unittest.TestCase):
    """② flow/adopt: 理由を ApiError 400 にそろえる・kind live は通さない・配信の長さで切る"""

    def test_check_and_pick(self):
        with self.assertRaises(ApiError) as c:
            flow_adopt.check([], 31)
        self.assertEqual((c.exception.code, c.exception.status, c.exception.message), ("bad_request", 400, "採用する数は0〜30です"))
        v = {"kind": "youtube", "duration": DUR, "marks": base()}
        r = flow_adopt.pick(v, flow_adopt.check([], 2), 2)
        self.assertEqual(len(r["added"]), 2)
        with self.assertRaises(ApiError) as c:
            flow_adopt.pick(v, [(600.0, 700.0)], 0)
        self.assertEqual(c.exception.status, 400)

    def test_live_is_refused(self):
        with self.assertRaises(ApiError) as c:
            flow_adopt.pick({"kind": "live", "duration": 0, "marks": []}, [], 3)
        self.assertEqual((c.exception.code, c.exception.status, c.exception.message), ("bad_request", 400, yturl.LIVE_NO_ANALYZE))


if __name__ == "__main__":
    unittest.main()
