"""価値のカードの反映(src/human/check/value.py)の単体テスト。入口が渡す口(auto_review・studio)は偽物。

実行(リポジトリ直下から): py -3.10 -m unittest src/human/check/tests/test_value.py -v
"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> human -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from human.check import answerlog, apply, value  # noqa: E402,F401

VID = "abcdefghijk"


def auto_card():
    return {"id": "value:auto:%s#a1" % VID, "kind": "value", "source": "auto", "case": {"id": VID, "title": "t"},
            "target": {"videoId": VID, "markId": "a1", "docId": "aaaaaaaaaaaa", "row": None}}


def cand_card():
    return {"id": "value:cand:%s#m1" % VID, "kind": "value", "source": "cand", "case": {"id": VID, "title": "t"},
            "target": {"videoId": VID, "markId": "m1", "docId": None, "row": None}}


class FakeStudio:
    def __init__(self, status="", export_code=200):
        self.status, self.rev, self.calls, self.export_code, self.put_409 = status, 3, [], export_code, 0

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/api/video"):
            return 200, {"video": {"id": VID, "rev": self.rev, "marks": [{"id": "m1", "start": 1, "end": 2, "status": self.status}, {"id": "m2", "start": 5, "end": 6, "status": ""}]}}
        if method == "PUT":
            if self.put_409:
                self.put_409 -= 1
                return 409, {"message": "ぶつかった"}
            self.status = next(m["status"] for m in body["marks"] if m["id"] == "m1")
            return 200, {"ok": True}
        if path == "/api/export":
            return self.export_code, {"message": "別の書き出しが実行中です"} if self.export_code != 200 else {"id": VID}
        return 200, {"ok": True}


class ValueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-check-value-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reviews = []
        self.review_result = (200, {"ok": True, "job": "j1"})
        self.studio = FakeStudio()

        def auto_review(body):
            self.reviews.append(body)
            return self.review_result
        self.ctx = apply.Context(self.tmp, ROOT, hooks={"auto_review": auto_review, "studio": lambda *a: self.studio(*a)})

    def test_registered(self):
        self.assertTrue(apply.registered("value", "auto") and apply.registered("value", "cand"))

    def test_send_is_deferred_until_next_answer_and_undo_cancels(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "send"}})
        self.assertEqual((got["held"], self.reviews), (True, []))   # 1 枚遅れ: まだ届けない
        back = apply.undo(self.ctx, got["answer"])
        self.assertEqual((back["reverted"], self.reviews), ({"held": True}, []))   # 保留のうちの Z は何も起こさない
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "send"}})
        self.assertEqual(self.reviews, [])
        out = apply.flush(self.ctx)
        self.assertEqual(self.reviews, [{"op": "deliver", "id": VID, "markId": "a1"}])
        self.assertEqual(out["flushed"][0]["applied"]["job"], "j1")
        with self.assertRaises(apply.Refused) as e:   # 届けた後は戻せない
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(e.exception.error, "cannot_undo")

    def test_send_flushed_by_next_answer(self):
        apply.answer(self.ctx, auto_card(), {"answer": {"choice": "send"}})
        other = dict(auto_card(), id="value:auto:%s#a2" % VID, target=dict(auto_card()["target"], markId="a2"))
        got = apply.answer(self.ctx, other, {"answer": {"choice": "drop"}})
        self.assertEqual([r["op"] for r in self.reviews], ["deliver"])   # 要らないも保留(次の答えか flush で確定)
        self.assertEqual((len(got["flushed"]), got["held"]), (1, True))

    def test_send_failure_is_recorded_not_raised_on_flush(self):
        apply.answer(self.ctx, auto_card(), {"answer": {"choice": "send"}})
        self.review_result = (409, {"error": "conflict", "message": "パックがまだありません"})
        out = apply.flush(self.ctx)
        self.assertIn("パックがまだありません", out["flushed"][0]["failed"])

    def test_drop_is_held_and_undoable(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "drop"}})
        self.assertEqual((got["held"], self.reviews), (True, []))   # 1 枚遅れ = まだ片付けない
        apply.undo(self.ctx, got["answer"])                          # 保留のうちの Z は何もしない
        self.assertEqual(apply.flush(self.ctx)["flushed"], [])
        self.assertEqual(self.reviews, [])
        apply.answer(self.ctx, auto_card(), {"answer": {"choice": "drop"}})
        self.review_result = (409, {"error": "conflict", "message": "片付けている途中です"})
        out = apply.flush(self.ctx)
        self.assertIn("片付けている途中です", out["flushed"][0]["failed"])   # 確定の失敗は記録に残す

    def test_bad_answer(self):
        for bad in ({"choice": "adopt"}, "send", {"choice": None}, {}):
            with self.assertRaises(apply.Refused) as e:
                apply.answer(self.ctx, auto_card(), {"answer": bad})
            self.assertEqual(e.exception.code, 400)
        with self.assertRaises(apply.Refused):
            apply.answer(self.ctx, cand_card(), {"answer": {"choice": "send"}})

    def test_cand_adopt_exports_and_undo(self):
        got = apply.answer(self.ctx, cand_card(), {"answer": {"choice": "adopt"}})
        self.assertEqual((self.studio.status, got["applied"]["export"], got["applied"]["before"]), ("adopted", "started", ""))
        self.assertIn(("POST", "/api/export", {"id": VID, "markIds": ["m1"]}), self.studio.calls)
        put = next(c for c in self.studio.calls if c[0] == "PUT")
        self.assertEqual(put[2]["baseRev"], 3)
        self.assertEqual([m["status"] for m in put[2]["marks"]], ["adopted", ""])   # 他のマークは触らない
        back = apply.undo(self.ctx, got["answer"])
        self.assertEqual((self.studio.status, back["reverted"]["status"]), ("", ""))
        self.assertIn(("POST", "/api/export/cancel", {"id": VID}), self.studio.calls)

    def test_cand_adopt_when_export_busy_still_adopts(self):
        self.studio.export_code = 409
        got = apply.answer(self.ctx, cand_card(), {"answer": {"choice": "adopt"}})
        self.assertEqual(self.studio.status, "adopted")
        self.assertIn("書き出し", got["applied"]["export"])
        apply.undo(self.ctx, got["answer"])
        self.assertNotIn("/api/export/cancel", [c[1] for c in self.studio.calls])   # 頼めていないなら取り消さない

    def test_cand_reject_undo_and_exported_cannot_undo(self):
        got = apply.answer(self.ctx, cand_card(), {"answer": {"choice": "reject"}})
        self.assertEqual(self.studio.status, "rejected")
        self.assertNotIn("/api/export", [c[1] for c in self.studio.calls])
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(self.studio.status, "")
        got = apply.answer(self.ctx, dict(cand_card(), id="value:cand:%s#m1b" % VID), {"answer": {"choice": "adopt"}})
        self.studio.status = "exported"   # 書き出しが済んだ
        with self.assertRaises(apply.Refused) as e:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(e.exception.error, "changed")

    def test_cand_retries_on_conflict_and_gone(self):
        self.studio.put_409 = 1
        apply.answer(self.ctx, cand_card(), {"answer": {"choice": "reject"}})
        self.assertEqual(self.studio.status, "rejected")
        self.studio.put_409 = 5
        with self.assertRaises(apply.Refused) as e:
            apply.answer(self.ctx, dict(cand_card(), id="value:cand:%s#m1c" % VID), {"answer": {"choice": "adopt"}})
        self.assertEqual(e.exception.error, "busy")
        card = cand_card()
        card["id"] = "value:cand:%s#zz" % VID
        card["target"] = dict(card["target"], markId="zz")
        with self.assertRaises(apply.Refused) as e:
            apply.answer(self.ctx, card, {"answer": {"choice": "adopt"}})
        self.assertEqual(e.exception.error, "gone")

    def test_studio_down(self):
        ctx = apply.Context(self.tmp, ROOT, hooks={"studio": lambda *a: (None, {"message": "つながらない"})})
        with self.assertRaises(apply.Refused) as e:
            apply.answer(ctx, cand_card(), {"answer": {"choice": "reject"}})
        self.assertEqual(e.exception.error, "studio_down")


if __name__ == "__main__":
    unittest.main()
