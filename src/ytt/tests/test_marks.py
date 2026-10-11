#!/usr/bin/env python3
"""ytt/marks.py(マークの純粋な語彙。RS8 B3-2 で human/review/store.py から下ろした)の単体テスト。

    python -m unittest src/ytt/tests/test_marks.py

期待値は store のテスト(src/human/review/tests/test_studio.py)と同じ。Store を通した動き(保存・学習の記録)はそちらが確かめる。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # src
from ytt import marks as M  # noqa: E402


def auto_mark(s, e, **kw):
    """保存済みの自動マーク(候補・手つかず)"""
    d = {"id": "a1", "start": s, "end": e, "label": "", "src": "auto", "score": 5.0, "status": "", "auto0": [s, e]}
    d.update(kw)
    return M.build_mark(d, None, True)


class TestCheckTimes(unittest.TestCase):
    def test_ok_rounds(self):
        self.assertEqual(M.check_times(1.04, 10.26), (1.0, 10.3))

    def test_rejects(self):
        for a, b in [("1", 2), (True, 2), (float("nan"), 2), (-1, 5), (5, 5), (5, 4), (0, 3601), (0, 1e9), (None, 1)]:
            with self.assertRaises(M.BadMark, msg=(a, b)):
                M.check_times(a, b)

    def test_clamp_end(self):
        self.assertEqual(M.clamp_end(600, 10, 700), 600.0)
        self.assertEqual(M.clamp_end(0, 10, 700), 700)       # 長さが分からなければ切らない
        self.assertIsNone(M.clamp_end(600, 600, 700))        # 開始より後でなくなる


class TestBuildMark(unittest.TestCase):
    def test_new_mark_is_manual_and_server_fields_ignored(self):
        m = M.build_mark({"id": "m1", "start": 1, "end": 9, "src": "auto", "score": 99, "status": "exported", "file": "x.mp4", "auto0": [1, 9]}, None)
        self.assertEqual((m["src"], m["status"], m["file"], m["score"]), ("manual", "", "", None))
        self.assertNotIn("auto0", m)

    def test_client_can_set_adopted_rejected_on_new(self):
        self.assertEqual([M.build_mark({"id": "x", "start": 1, "end": 9, "status": st}, None)["status"] for st in ("adopted", "rejected")],
                         ["adopted", "rejected"])

    def test_trusted_keeps_server_fields(self):
        m = auto_mark(10, 40, reasons=["音量"] * 9, parts={"audio": 1.234, "x": 3}, peak=11.26)
        self.assertEqual((m["src"], m["score"], m["auto0"], m["peak"]), ("auto", 5.0, [10.0, 40.0], 11.3))
        self.assertEqual((len(m["reasons"]), m["parts"]), (6, {"audio": 1.23}))

    def test_exported_moved_goes_back_to_adopted(self):
        old = M.build_mark({"id": "a1", "start": 10, "end": 40, "status": "exported", "file": "f/a.mp4", "path": "C:/x/a.mp4"}, None, True)
        self.assertEqual((old["status"], old["path"]), ("exported", "C:/x/a.mp4"))
        same = M.build_mark({"id": "a1", "start": 10.02, "end": 40}, old)   # EDIT_TOL の中: そのまま
        self.assertEqual((same["status"], same["file"]), ("exported", "f/a.mp4"))
        moved = M.build_mark({"id": "a1", "start": 12, "end": 40}, old)
        self.assertEqual((moved["status"], moved["file"]), ("adopted", ""))
        self.assertNotIn("path", moved)

    def test_human_status_change_drops_adopted_by(self):
        old = auto_mark(10, 40, status="adopted", adoptedBy="auto")
        self.assertEqual(old["adoptedBy"], "auto")
        self.assertEqual(M.build_mark(dict(old), old).get("adoptedBy"), "auto")   # 状態を変えなければ残る
        self.assertNotIn("adoptedBy", M.build_mark(dict(old, status="rejected"), old))

    def test_archived_only_with_file(self):
        m = M.build_mark({"id": "a1", "start": 1, "end": 9, "status": "exported", "file": "f.mp4", "archived": True}, None, True)
        self.assertTrue(m["archived"])
        self.assertNotIn("archived", M.drop_archived([dict(m)], "youtube")[0])
        self.assertTrue(M.drop_archived([dict(m)], "live")[0]["archived"])

    def test_collab_from(self):
        self.assertEqual(M.collab_from({"videoId": "v1", "markId": "m1", "x": 1}), {"videoId": "v1", "markId": "m1"})
        self.assertIsNone(M.collab_from({"videoId": "bad id!", "markId": "m1"}))

    def test_new_mark(self):
        m = M.new_mark("r", 1.0, 9.0, "adopted")
        self.assertTrue(m["id"].startswith("r") and M.ID_RE.match(m["id"]))
        self.assertEqual((m["src"], m["status"], m["start"], m["end"]), ("manual", "adopted", 1.0, 9.0))


class TestLoadMarks(unittest.TestCase):
    def test_skips_broken_and_duplicates(self):
        raw = [{"id": "a1", "start": 1, "end": 9}, {"id": "a1", "start": 2, "end": 9}, {"id": "bad id!", "start": 1, "end": 9},
               {"id": "a2", "start": 9, "end": 1}, "x", {"id": "a3", "start": 20, "end": 30, "status": "adopted"}]
        self.assertEqual([m["id"] for m in M.load_marks(raw)], ["a1", "a3"])
        self.assertEqual(M.load_marks(None), [])

    def test_cap(self):
        raw = [{"id": "m%d" % i, "start": i, "end": i + 1} for i in range(M.MAX_MARKS + 5)]
        self.assertEqual(len(M.load_marks(raw)), M.MAX_MARKS)


class TestSameTouched(unittest.TestCase):
    def test_same_and_near(self):
        self.assertTrue(M.same({"start": 10, "end": 40}, {"start": 10.5, "end": 39.5}))
        self.assertFalse(M.same({"start": 10, "end": 40}, {"start": 10.6, "end": 40}))
        self.assertTrue(M.near(10, 40, 10.9, 40, tol=1.0))

    def test_similar(self):
        a = {"start": 100.0, "end": 140.0}
        self.assertTrue(M.similar(a, {"start": 104.9, "end": 144.9}))    # ±5 秒の中
        self.assertFalse(M.similar(a, {"start": 105.1, "end": 140.0}))   # 開始が 5 秒を超えてずれた
        self.assertFalse(M.similar({"start": 0.0, "end": 6.0}, {"start": 4.0, "end": 10.0}))   # 短い区間どうしで重なりが半分未満
        self.assertTrue(M.similar({"start": 0.0, "end": 6.0}, {"start": 3.0, "end": 9.0}))     # ちょうど半分

    def test_overlaps(self):
        self.assertTrue(M.overlaps(10, 40, 39, 50))
        self.assertFalse(M.overlaps(10, 40, 40, 50))   # 端が接するだけは重ならない

    def test_touched(self):
        self.assertFalse(M.touched(auto_mark(10, 40)))
        self.assertTrue(M.touched(auto_mark(10, 40, status="rejected")))
        self.assertTrue(M.touched(auto_mark(10, 40, label="x")))
        self.assertTrue(M.touched(dict(auto_mark(10, 40), start=12.0)))
        self.assertFalse(M.touched(dict(auto_mark(10, 40), start=10.04)))   # EDIT_TOL の中
        self.assertTrue(M.touched(M.build_mark({"id": "m1", "start": 1, "end": 9}, None)))   # auto0 が無い = 手のマーク


if __name__ == "__main__":
    unittest.main()
