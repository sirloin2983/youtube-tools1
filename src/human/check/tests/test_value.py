"""価値のカードの反映(src/human/check/value.py)の単体テスト。入口が渡す口(studio)は偽物。value:auto は記録だけ(案件の口を呼ばない)。

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

from human import judgments  # noqa: E402
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
        self.export_state = "running"

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
            return self.export_code, {"message": "別の書き出しが実行中です"} if self.export_code != 200 else {"id": "ex1", "state": "queued"}
        if method == "GET" and path.startswith("/api/export?id="):
            return 200, {"id": "ex1", "state": self.export_state}
        return 200, {"ok": True}


class ValueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-check-value-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.studio = FakeStudio()
        self.hook_calls = []

        def auto_review(body):   # 案件の口。value:auto は呼んではいけない(記録だけ)
            self.hook_calls.append(body)
            return 200, {"ok": True}
        self.ctx = apply.Context(self.tmp, ROOT, hooks={"auto_review": auto_review, "studio": lambda *a: self.studio(*a)})

    def test_registered(self):
        self.assertTrue(apply._registered("value", "auto") and apply._registered("value", "cand"))

    def test_auto_good_is_recorded_at_once_and_touches_nothing(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "good"}})
        self.assertEqual((got["held"], got["applied"]["choice"]), (False, "good"))   # 1 枚遅れなし = すぐ記録
        self.assertEqual(self.hook_calls, [])   # 送るかには効かせない
        self.assertEqual(apply.flush(self.ctx)["flushed"], [])
        self.assertEqual(self.studio.calls, [])

    def test_auto_bad_with_reason_and_undo_is_record_only(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "bad", "reason": "long"}})
        self.assertEqual(got["applied"]["reason"], "long")
        back = apply.undo(self.ctx, got["answer"])   # Z は記録の取り消し
        self.assertEqual(back["reverted"], {"judgment": got["applied"]["judgment"]})
        self.assertEqual(self.hook_calls, [])
        again = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "bad"}})   # 取り消したカードはもう一度答えられる
        self.assertEqual({k: again["applied"][k] for k in ("videoId", "markId", "choice")}, {"videoId": VID, "markId": "a1", "choice": "bad"})

    def test_auto_reason_only_for_bad_and_must_be_a_card_reason(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "good", "reason": "long"}})
        self.assertNotIn("reason", got["applied"])   # 良いに付いた理由は捨てる
        with self.assertRaises(apply.Refused) as e:
            apply.answer(self.ctx, dict(auto_card(), id="value:auto:%s#a9" % VID), {"answer": {"choice": "bad", "reason": "nope"}})
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(self.hook_calls, [])

    def test_auto_writes_judgment_and_undo_retracts_it(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "bad", "reason": "boring"}})
        rows = judgments.rows(self.tmp)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["what"], r["who"], r["via"], r["origin"], r["videoId"], r["markId"]), ("quality_bad", "self", "check", "auto", VID, "a1"))
        self.assertEqual(r["reason"], "boring")
        self.assertEqual(r["id"], got["applied"]["judgment"])
        self.assertTrue(r["key"].startswith("ans:"))
        apply.undo(self.ctx, got["answer"])
        rows = judgments.rows(self.tmp)
        self.assertEqual([x["what"] for x in rows], ["quality_bad", "retract"])
        self.assertEqual((rows[1]["of"], rows[1]["key"]), (r["id"], r["key"] + ":retract"))
        self.assertIsNone(judgments.fold(rows)[(VID, "a1")]["quality"])   # 取り消したら品質のレーンは空

    def test_auto_good_writes_quality_good_without_reason(self):
        apply.answer(self.ctx, auto_card(), {"answer": {"choice": "good", "reason": "long"}})
        rows = judgments.rows(self.tmp)
        self.assertEqual((rows[0]["what"], rows[0]["via"]), ("quality_good", "check"))
        self.assertNotIn("reason", rows[0])
        self.assertEqual(self.studio.calls, [])

    def test_auto_unknown_writes_quality_unknown_without_reason_and_undo(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "unknown", "reason": "boring"}})
        self.assertEqual((got["applied"]["choice"], self.hook_calls), ("unknown", []))
        self.assertNotIn("reason", got["applied"])   # 不明に付いた理由は捨てる(理由は悪いのときだけ)
        rows = judgments.rows(self.tmp)
        self.assertEqual((rows[0]["what"], rows[0]["who"], rows[0]["via"], rows[0]["origin"]), ("quality_unknown", "self", "check", "auto"))
        self.assertNotIn("reason", rows[0])
        self.assertEqual(judgments.fold(rows)[(VID, "a1")]["quality"]["what"], "quality_unknown")
        apply.undo(self.ctx, got["answer"])
        self.assertIsNone(judgments.fold(judgments.rows(self.tmp))[(VID, "a1")]["quality"])

    def test_cand_writes_no_judgment(self):
        apply.answer(self.ctx, cand_card(), {"answer": {"choice": "reject"}})
        self.assertEqual(judgments.rows(self.tmp), [])

    def test_retract_is_not_written_twice(self):
        got = apply.answer(self.ctx, auto_card(), {"answer": {"choice": "good"}})
        value._auto_revert(self.ctx, {"applied": got["applied"]})
        value._auto_revert(self.ctx, {"applied": got["applied"]})
        self.assertEqual([x["what"] for x in judgments.rows(self.tmp)], ["quality_good", "retract"])

    def test_bad_answer(self):
        for bad in ({"choice": "adopt"}, {"choice": "send"}, "bad", {"choice": None}, {}):
            with self.assertRaises(apply.Refused) as e:
                apply.answer(self.ctx, auto_card(), {"answer": bad})
            self.assertEqual(e.exception.code, 400)
        with self.assertRaises(apply.Refused):
            apply.answer(self.ctx, cand_card(), {"answer": {"choice": "good"}})

    def test_cand_adopt_exports_and_undo(self):
        got = apply.answer(self.ctx, cand_card(), {"answer": {"choice": "adopt"}})
        self.assertEqual((self.studio.status, got["applied"]["export"], got["applied"]["before"], got["applied"]["exportJob"]), ("adopted", "started", "", "ex1"))
        self.assertIn(("POST", "/api/export", {"id": VID, "markIds": ["m1"]}), self.studio.calls)
        put = next(c for c in self.studio.calls if c[0] == "PUT")
        self.assertEqual(put[2]["baseRev"], 3)
        self.assertEqual([m["status"] for m in put[2]["marks"]], ["adopted", ""])   # 他のマークは触らない
        back = apply.undo(self.ctx, got["answer"])
        self.assertEqual((self.studio.status, back["reverted"]["status"]), ("", ""))
        self.assertIn(("POST", "/api/export/cancel", {"id": "ex1"}), self.studio.calls)   # 取り消すのは書き出しのジョブ(6e-1)

    def test_cand_adopt_undo_refused_when_export_done(self):
        """6e-1: 頼んだ書き出しがもう済んでいたら Z を断る(status を戻しても切り抜きはできている)"""
        got = apply.answer(self.ctx, cand_card(), {"answer": {"choice": "adopt"}})
        self.studio.export_state = "done"
        with self.assertRaises(apply.Refused) as e:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual((e.exception.error, self.studio.status), ("changed", "adopted"))

    def test_cand_undo_again_when_already_back(self):
        """やりかけの Z のやり直し: status がもう元なら書かずに済ませる"""
        got = apply.answer(self.ctx, cand_card(), {"answer": {"choice": "reject"}})
        self.studio.status = ""
        puts = len([c for c in self.studio.calls if c[0] == "PUT"])
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(len([c for c in self.studio.calls if c[0] == "PUT"]), puts)

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
