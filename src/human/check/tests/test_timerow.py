"""時刻のカードの反映(src/human/check/timerow.py)の単体テスト。一時の作業データに文書を作って、答える・戻すを確かめる。

実行(リポジトリ直下から): py -3.10 -m unittest src/human/check/tests/test_timerow.py -v
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> human -> src
for _p in (os.path.join(ROOT, "editor"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human.check import answerlog, apply  # noqa: E402
from human.check import timerow as check_time  # noqa: E402
from human.proof import store  # noqa: E402
from human.tests._workdata import temporary_workdata  # noqa: E402

TID = "0123456789ab"


def card(row="s1", tid=TID):
    return {"id": "time:row:%s#%s" % (tid, row), "kind": "time", "source": "row", "case": {"id": "v1", "title": "t"},
            "target": {"docId": tid, "row": row}, "guess": "ok"}


class TimeApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "ytt-check-time-")
        self.doc = {"id": TID, "updatedAt": 1, "segments": [
            {"id": "s1", "start": 10.0, "end": 12.0, "text": "あいう", "speaker": "", "proofed": True, "flag": ""},
            {"id": "s2", "start": 12.5, "end": 14.0, "text": "えお", "speaker": "", "proofed": True, "flag": ""}]}
        store.commit(TID, self.doc, why="save")
        self.ctx = apply.Context(os.path.join(self.tmp, "app"), ROOT)

    def seg(self, rid="s1"):
        return next(g for g in store.read_transcript(TID)["segments"] if g["id"] == rid)

    def test_registered_and_why(self):
        self.assertTrue(apply._registered("time", "row"))
        self.assertIn("check:time", store.HUMAN_WHYS)

    def test_check(self):
        c = check_time._check
        self.assertEqual(c({"choice": "ok"}), {"choice": "ok", "dStart": 0.0, "dEnd": 0.0})
        self.assertEqual(c({"choice": "head", "dStart": -0.1004}), {"choice": "head", "dStart": -0.1, "dEnd": 0.0})
        self.assertEqual(c({"choice": "both", "dStart": 0.2, "dEnd": -0.3})["dEnd"], -0.3)
        for bad in (None, {}, {"choice": "x"}, {"choice": "ok", "dStart": 0.1}, {"choice": "head", "dEnd": 0.1}, {"choice": "tail", "dStart": 0.1},
                    {"choice": "both", "dStart": 9}, {"choice": "both", "dStart": True}, {"choice": "both", "dEnd": "1"}, {"choice": "both", "dEnd": float("nan")}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                c(bad)

    def test_marks_only_does_not_touch_doc(self):
        before = store.read_transcript(TID)
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "head"}, "ms": 900})
        self.assertEqual(r["applied"], {"docId": TID, "row": "s1", "moved": False})
        self.assertEqual(store.read_transcript(TID), before)   # 更新日時も含めて同じ
        row = answerlog.state(self.ctx.app_dir).answers[r["answer"]]
        self.assertEqual(row["answer"], {"choice": "head", "dStart": 0.0, "dEnd": 0.0})

    def test_move_and_undo(self):
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "both", "dStart": -0.2, "dEnd": 0.3}})
        self.assertTrue(r["applied"]["moved"])
        g = self.seg()
        self.assertEqual((g["start"], g["end"]), (9.8, 12.3))
        self.assertGreater(store.read_transcript(TID)["updatedAt"], 1)
        self.assertEqual(self.seg("s2")["start"], 12.5)
        u = apply.undo(self.ctx, r["answer"])
        self.assertTrue(u["reverted"]["moved"])
        g = self.seg()
        self.assertEqual((g["start"], g["end"]), (10.0, 12.0))

    def test_one_edge_only(self):
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "tail", "dEnd": 0.5}})
        g = self.seg()
        self.assertEqual((g["start"], g["end"]), (10.0, 12.5))
        # 頭の端はあとで人が直した -> 末だけ動かした答えは戻せる(動かしていない端は見ない)
        doc = store.read_transcript(TID)
        doc["segments"][0]["start"] = 10.4
        store.commit(TID, doc, why="save")
        apply.undo(self.ctx, r["answer"])
        g = self.seg()
        self.assertEqual((g["start"], g["end"]), (10.4, 12.0))

    def test_undo_refused_when_edge_changed_later(self):
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "head", "dStart": 0.5}})
        doc = store.read_transcript(TID)
        doc["segments"][0]["start"] = 10.9
        store.commit(TID, doc, why="save")
        with self.assertRaises(apply.Refused) as cm:
            apply.undo(self.ctx, r["answer"])
        self.assertEqual(cm.exception.error, "changed")
        self.assertEqual(self.seg()["start"], 10.9)

    def test_refusals_leave_doc_and_record_unwritten(self):
        """短すぎる・行が無い・処理中(busy)・評価用の文書(eval)は断り、文書も記録も変えない"""
        from flow import jobs as _heavy
        head = {"answer": {"choice": "head", "dStart": 0.1}}
        for name, c, body, err in (("too_short", card(), {"answer": {"choice": "both", "dStart": 1.0, "dEnd": -1.0}}, "too_short"),
                                   ("no_row", card("nope"), {"answer": {"choice": "ok"}}, "no_row")):
            with self.subTest(name), self.assertRaises(apply.Refused) as cm:
                apply.answer(self.ctx, c, body)
            self.assertEqual(cm.exception.error, err)
        with mock.patch.object(_heavy, "doc_busy", return_value=True):
            with self.assertRaises(apply.Refused) as cm:
                apply.answer(self.ctx, card(), head)
        self.assertEqual(cm.exception.error, "busy")
        self.assertEqual((self.seg()["start"], self.seg()["end"]), (10.0, 12.0))
        self.assertEqual(answerlog.state(self.ctx.app_dir).order, [])
        doc = store.read_transcript(TID)
        doc["evalSet"] = True
        store.commit(TID, doc, why="save")
        with self.assertRaises(apply.Refused) as cm:
            apply.answer(self.ctx, card(), head)
        self.assertEqual(cm.exception.error, "eval")

    def test_undo_log_failure_then_retry(self):
        """部品 H2 の再現: 頭を 1.0 → 1.5 秒へ答え、Z で 1.0 へ戻したあと戻すの行だけ OSError → 評価の有効な答えから外れ、
        同じ Z のやり直しで 409 changed にならずに記録が整う・同じカードに答え直せる"""
        doc = store.read_transcript(TID)
        doc["segments"][0].update(start=1.0, end=3.0)
        store.commit(TID, doc, why="save")
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "head", "dStart": 0.5}})
        self.assertEqual(self.seg()["start"], 1.5)
        real = answerlog.append

        def append(app_dir, row):
            if "undo" in row:
                raise OSError("full")
            return real(app_dir, row)
        with mock.patch.object(answerlog, "append", side_effect=append):
            with self.assertRaises(OSError):
                apply.undo(self.ctx, r["answer"])
        self.assertEqual(self.seg()["start"], 1.0)
        st = answerlog.state(self.ctx.app_dir)
        self.assertEqual([x for x in st.effective() if x["kind"] == "time"], [])   # eval_timing は effective を読む = 戻した答えを使わない
        u = apply.undo(self.ctx, r["answer"])
        self.assertTrue(u["ok"])
        self.assertEqual(self.seg()["start"], 1.0)
        again = apply.answer(self.ctx, card(), {"answer": {"choice": "ok"}})
        self.assertTrue(again["ok"])

    def test_move_limit_matches_screen(self):
        self.assertEqual(check_time.MAX_MOVE, 2.5)   # 画面 cards/time.js の LIMIT と同じ
        with self.assertRaises(ValueError):
            check_time._check({"choice": "head", "dStart": 3.0})

    def test_start_not_before_zero(self):
        doc = store.read_transcript(TID)
        doc["segments"][0].update(start=0.05, end=2.0)
        store.commit(TID, doc, why="save")
        apply.answer(self.ctx, card(), {"answer": {"choice": "head", "dStart": -0.5}})
        self.assertEqual(self.seg()["start"], 0.0)


if __name__ == "__main__":
    unittest.main()
