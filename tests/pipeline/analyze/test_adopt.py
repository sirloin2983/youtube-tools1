# -*- coding: utf-8 -*-
"""pipeline/analyze/adopt.py(採用の規則 F-5 の純粋な関数)と ② の口 flow/adopt のテスト。
    py -3.12 -m unittest tests/pipeline/analyze/test_adopt.py -v
自動マーク 5 つの配信を、使う順(上位を採用 → 再実行 → 人の採用 → 区間つきの依頼)に通して、採った id と印をまとめて確かめる。
期待値は store のテスト(tests/human/review/test_studio.py の TestAdoptRule)と同じ。保存を通した動きはそちらが確かめる。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import copy
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src"))   # src
from flow import adopt as flow_adopt  # noqa: E402
from pipeline.analyze import adopt as A  # noqa: E402
from ytt import marks as M, yturl  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

DUR = 600


def auto(i, s, e, score):
    """解析が足した自動マーク(候補・手つかず)"""
    return M.build_mark({"id": "a%d" % i, "start": s, "end": e, "src": "auto", "score": score, "auto0": [s, e]}, None, True)


def base():
    return [auto(1, 10, 40, 2.0), auto(2, 100, 130, 9.0), auto(3, 200, 230, 5.0), auto(4, 300, 330, 7.0), auto(5, 400, 430, 1.0)]


def set_status(marks, start, status):
    return [M.build_mark(dict(m, status=status), m) if m["start"] == start else m for m in marks]


class TestAdoptRun(unittest.TestCase):
    def test_pieces_from_candidates_and_bounds(self):
        """解析の候補の pieces(つないだ本数)が replace_auto で自動マークに渡る・2〜50 の整数だけ(ほかは付けない = 1 本)"""
        got, _n = M.replace_auto([], [{"start": s, "end": s + 30, "score": 1.0, "pieces": p} for s, p in
                                      ((10, 2), (60, 1), (110, 50), (160, 51), (210, True), (260, "2"), (310, 2.0))])
        self.assertEqual([(m["start"], M.pieces_of(m)) for m in got], [(10, 2), (60, 1), (110, 50), (160, 1), (210, 1), (260, 1), (310, 1)])
        self.assertEqual([m.get("pieces") for m in M.load_marks(got)], [2, None, 50, None, None, None, None])   # 保存して読み直しても同じ

    def test_machine_adopted_counts_after_reanalysis(self):
        """機械が採用した自動マークは、解析し直しで手動(replace_auto の touched)になっても採用の上限で数える・つないだ本数も読み直しで残る"""
        marks = base()
        marks[1] = M.build_mark(dict(marks[1], pieces=2), None, True)   # 100〜130(点数 9)= 2 本をつないだ物
        first = A.adopt(marks, A.check_args([], 3), 3, DUR)
        self.assertEqual(first["autoIds"], ["a2", "a4"])
        cands = [{"start": s, "end": s + 30, "score": sc} for s, sc in ((10, 2.0), (200, 5.0), (400, 1.0), (500, 8.0))]
        again, _n = M.replace_auto(first["marks"], cands)
        again = M.load_marks(again)   # 保存して読み直した形
        kept = {m["id"]: m for m in again if m["id"] in ("a2", "a4")}
        self.assertEqual([(kept[i]["src"], kept[i].get("adoptedBy"), M.pieces_of(kept[i])) for i in ("a2", "a4")],
                         [("manual", "auto", 2), ("manual", "auto", 1)])
        r = A.adopt(again, A.check_args([], 3), 3, DUR)
        self.assertEqual((r["autoIds"], r["added"]), (["a2", "a4"], []))   # 前の採用で 3 本 = 新しい自動マーク(500 秒・点数 8)は足さない

    def test_joined_mark_counts_as_its_pieces(self):
        """つないだ自動マーク(excite.join_clips の pieces)は採用の上限で元の本数と数える。残りに入らなければ飛ばして次へ"""
        marks = base()
        marks[1] = M.build_mark(dict(marks[1], pieces=2), None, True)   # 100〜130(点数 9)= 2 本をつないだ物
        self.assertEqual((M.pieces_of(marks[1]), M.pieces_of(marks[0])), (2, 1))
        r = A.adopt(marks, A.check_args([], 3), 3, DUR)
        self.assertEqual(r["autoIds"], ["a2", "a4"])   # 2 + 1 = 3 本(前は 3 つ = 4 本ぶん)
        r = A.adopt(marks, A.check_args([], 2), 2, DUR)
        self.assertEqual(r["autoIds"], ["a2"])
        r = A.adopt(set_status(marks, 300, "adopted"), A.check_args([], 2), 2, DUR)
        self.assertEqual((r["humanIds"], r["autoIds"]), (["a4"], ["a3"]))   # 人の 1 本 + 残り 1 本: 2 本ぶんの a2 は入らない = 次の a3
        self.assertNotIn("pieces", M.build_mark(dict(marks[1], src="manual", pieces=2), None, True))   # 手動のマークには付けない

    def test_rule_in_order_of_use(self):
        def run(marks, ranges, top):
            r = A.adopt(marks, A.check_args(ranges, top), top, DUR)
            by = {m["id"]: m["start"] for m in r["marks"]}
            return r, {k: [by[i] for i in r[k]] for k in ("added", "autoIds", "humanIds", "rangeIds")}

        r, got = run(base(), [], 2)                                          # 点数の上位 2 つ
        self.assertEqual(got, {"added": [100, 300], "autoIds": [100, 300], "humanIds": [], "rangeIds": []})
        self.assertEqual({m["start"]: m.get("adoptedBy") for m in r["marks"] if m["status"] == "adopted"}, {100: "auto", 300: "auto"})
        r, got = run(r["marks"], [], 2)                                      # 再実行: 前に機械が採用した分を数に入れる(増やさない)
        self.assertEqual(got, {"added": [], "autoIds": [100, 300], "humanIds": [], "rangeIds": []})
        r, got = run(set_status(r["marks"], 10, "adopted"), [], 3)           # 人の採用は数に入る・機械の印は付けない
        self.assertEqual((got["humanIds"], got["autoIds"]), ([10], [100, 300]))
        self.assertEqual(run(r["marks"], [], 1)[1]["autoIds"], [])           # 人の分だけで上限

        ms = set_status(set_status(set_status(base(), 100, "rejected"), 10, "adopted"), 200, "rejected")
        before = copy.deepcopy(ms)
        ranges = [[305, 320], [200.4, 229.6], [590, 700]]                    # 新しい区間・不採用と同じ区間(±0.5 秒)・配信の終わりを越える区間
        r, got = run(ms, ranges, 5)
        self.assertEqual(ms, before)                                         # 入力は変えない
        self.assertEqual(got, {"added": [305, 200, 590, 400], "autoIds": [400], "humanIds": [10], "rangeIds": [305, 200, 590]})   # 300 は区間に重なる・100 は不採用
        out = {m["start"]: m for m in r["marks"]}
        self.assertEqual([(out[s]["status"], out[s]["adoptedBy"], out[s]["src"]) for s in (305, 200)], [("adopted", "request", "manual"), ("adopted", "request", "auto")])
        self.assertEqual((out[590]["end"], len(r["marks"]), [m["start"] for m in r["marks"]]), (600.0, 7, sorted(out)))   # 終わりは配信の長さ・同じ区間は使い回す・時刻の順
        self.assertEqual(run(ms, ranges, 1)[1]["rangeIds"], [305, 200, 590])   # 区間は上限を超えても全部
        with self.assertRaises(ValueError):
            A.adopt(ms, [(600.0, 700.0)], 0, DUR)                            # 配信の外

        want = A.check_args([[598, 598 + 3 * 3600 + 4]], 0)                 # 友人の依頼の区間の長さは上限なし(C-2-7・C-5-5)
        r = A.adopt(base(), want, 0, 5 * 3600)
        m = next(x for x in r["marks"] if x["id"] == r["rangeIds"][0])
        self.assertEqual((want, m["start"], m["end"], m["status"], m["adoptedBy"]), ([(598.0, 11402.0)], 598.0, 11402.0, "adopted", "request"))
        self.assertEqual(M.load_marks([m]), [m], "保存したあと読み直しても残る(読み込みは長さを見ない)")
        self.assertEqual(A.check_args([[1.04, 10.26]], 0), [(1.0, 10.3)])
        self.assertEqual(A.check_args([], 99), [])   # 上限なし(10-20)
        for ranges, top in (([], -1), ([], "1"), ([], None), ([], True), ([[1, 2]] * 11, 1), ("x", 1), ([[1]], 1), ([[5, 4]], 1)):
            with self.assertRaises(ValueError, msg=(ranges, top)):
                A.check_args(ranges, top)


class TestPref(unittest.TestCase):
    def test_order_ends_extra(self):
        """pref(flow/url_pick): order の並びで選ぶ(当たらない物は後ろで点数の順)・ends で採用にした物の終わりを縮める・
        extra から上限の外に、採用した物と重ならない最初の 1 本(extraIds)。pref が無ければ今のまま"""
        pref = {"order": [[400, 430], [10, 40]], "ends": [[400, 430, 420.0], [100, 130, 110.0]], "extra": [[105, 120], [300, 330]]}
        r = A.adopt(base(), A.check_args([], 3), 3, DUR, pref)
        self.assertEqual(r["autoIds"], ["a5", "a1", "a2"])   # 並びの 2 本 → 残りは点数の順(a2 = 9)
        got = {m["id"]: m for m in r["marks"]}
        self.assertEqual((got["a5"]["end"], got["a2"]["end"], got["a1"]["end"]), (420.0, 110.0, 40))
        self.assertEqual(r["extraIds"], ["a4"])   # 105〜120 はマークが無い → 300〜330(a4)
        self.assertEqual((got["a4"]["status"], got["a4"]["adoptedBy"]), ("adopted", "auto"))
        self.assertIn("a4", r["added"])
        r0 = A.adopt(base(), A.check_args([], 3), 3, DUR)
        self.assertEqual((r0["autoIds"], r0["extraIds"]), (["a2", "a4", "a3"], []))
        self.assertEqual(A.adopt(base(), A.check_args([], 3), 3, DUR, {"order": "x", "extra": [[1]]})["autoIds"], ["a2", "a4", "a3"])   # 形の違う pref は無視


class TestFlowVerb(unittest.TestCase):
    def test_check_pick_and_live(self):
        """② flow/adopt: 理由を ApiError 400 にそろえる・配信の長さで切る・kind live は通さない"""
        with self.assertRaises(ApiError) as c:
            flow_adopt.check([], -1)
        self.assertEqual((c.exception.code, c.exception.status), ("bad_request", 400))
        v = {"kind": "youtube", "duration": DUR, "marks": base()}
        self.assertEqual(len(flow_adopt.pick(v, flow_adopt.check([], 2), 2)["added"]), 2)
        with self.assertRaises(ApiError) as c:
            flow_adopt.pick(v, [(600.0, 700.0)], 0)
        self.assertEqual(c.exception.status, 400)
        with self.assertRaises(ApiError) as c:
            flow_adopt.pick({"kind": "live", "duration": 0, "marks": []}, [], 3)
        self.assertEqual((c.exception.code, c.exception.status, c.exception.message), ("bad_request", 400, yturl.LIVE_NO_ANALYZE))


if __name__ == "__main__":
    unittest.main()
