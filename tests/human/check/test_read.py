"""「確かめる」の読みのカードの反映(src/human/check/read.py)の単体テスト。一時フォルダの文書と learn-feedback.json だけを使う。
決まり: 行を校正済みにしない・時刻に触れない・文書は commit(why='check:read')・採否は編集の「提案」と同じ記録・Z で戻る。

実行(リポジトリ直下から): py -3.12 -m unittest tests/human/check/test_read.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> check -> human -> src
for _p in (os.path.join(ROOT, "editor"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human.check import answerlog, apply, read  # noqa: E402,F401
from human.proof import learn, store  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "human"))   # tests/human/(_workdata)
from _workdata import temporary_workdata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

TID = "aaaaaaaaaaaa"
FLAG = "別の読みで埋めた(元の文字は「別の読み」の札)"


def doc():
    return {"id": TID, "title": "t", "updatedAt": 100, "speakers": [{"id": "S1", "name": "あ"}], "segments": [
        {"id": "s1", "start": 1.0, "end": 3.0, "text": "埋めた文", "flag": FLAG + "、要確認", "fill": {"from": "うめたぶん", "by": "llm"}},
        {"id": "s2", "start": 3.0, "end": 5.0, "text": "今日は晴れです"},
        {"id": "s3", "start": 5.0, "end": 7.0, "text": "もう一行"}]}


def card(source, row, cand=None):
    c = {"id": "read:%s:%s#%s" % (source, TID, row), "kind": "read", "source": source, "case": {"id": "v1", "title": "t"},
         "target": {"docId": TID, "row": row}, "guess": None}
    if cand:
        c["_cand"] = cand
    return c


CAND = {"i": 3, "wrong": "晴", "right": "腫", "tier": "alt", "also": []}


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "ytt-check-read-")
        testkit.write_json(store.tx_path(TID), doc())
        self.app = os.path.join(self.tmp, "app")
        self.ctx = apply.Context(self.app, ROOT)

    def seg(self, row):
        return next(g for g in testkit.read_json(store.tx_path(TID))["segments"] if g["id"] == row)

    def refused(self, c, ans, error=None):
        with self.assertRaises(apply.Refused) as e:
            apply.answer(self.ctx, c, {"answer": ans})
        if error:
            self.assertEqual(e.exception.error, error)

    def fb(self):
        return learn.load_feedback()

    def test_registered_for_three_sources(self):
        for s in ("fill", "alt"):
            self.assertTrue(apply._registered("read", s))
        self.assertFalse(apply._registered("read", "yt"))   # YouTube の字幕の候補は出さない(yt の札は 409 で断る)

    def test_check_answer_shape(self):
        self.assertEqual(read._check({"choice": "2", "x": 1}), {"choice": "2"})
        self.assertEqual(read._check({"choice": "other", "text": "  正しい文字 "}), {"choice": "other", "text": "正しい文字"})
        for bad in ({"choice": "3"}, {"choice": "other"}, {"choice": "other", "text": "  "}, {"choice": "other", "text": "あ" * 5000}, "1", None,
                    {"choice": "other", "text": "a\x01b"}):
            with self.assertRaises(ValueError):
                read._check(bad)

    def test_fill_keep_changes_nothing(self):
        with self.assertNoLogs("tx", level="INFO"):
            got = apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "1"}})
        s = self.seg("s1")
        self.assertEqual((s["text"], s["fill"]["from"], s.get("proofed")), ("埋めた文", "うめたぶん", None))
        self.assertTrue(got["ok"])

    def test_fill_revert_to_recognized_and_undo(self):
        # 読みの答えは編集の保存と同じく履歴を 10 分に 1 つ(必ず 1 つ残して 30 個の履歴を押し出さない)・.bak の控えを作らない
        with self.assertLogs("tx", level="INFO") as cm, mock.patch.object(store, "snapshot") as snap, mock.patch.object(store, "backup_doc") as bak:
            got = apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "2"}})
        snap.assert_called_once_with(TID, False)
        bak.assert_not_called()
        self.assertTrue(any("why=check:read" in m and "by=human" in m for m in cm.output), cm.output)
        s = self.seg("s1")
        self.assertEqual((s["text"], s.get("fill"), s["flag"]), ("うめたぶん", None, "要確認"))   # 「別の読み」の札と同じ(印だけ外す)
        self.assertNotIn("proofed", s)                                                          # 校正済みにしない
        self.assertEqual((s["start"], s["end"]), (1.0, 3.0))                                    # 時刻に触れない
        self.assertEqual(got["applied"]["before"]["text"], "埋めた文")
        apply.undo(self.ctx, got["answer"])
        s = self.seg("s1")
        self.assertEqual((s["text"], s["fill"], s["flag"]), ("埋めた文", {"from": "うめたぶん", "by": "llm"}, FLAG + "、要確認"))

    def test_shift_changes_nothing_and_records_no_feedback(self):
        self.assertEqual(read._check({"choice": "shift", "text": "x"}), {"choice": "shift"})
        got = apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "shift"}})
        self.assertTrue(got["ok"])
        self.assertEqual(self.seg("s2")["text"], "今日は晴れです")
        self.assertNotIn("feedback", got.get("applied") or {})
        self.assertFalse(self.fb().get("dismissed"))   # 候補は却下しない(編集の「提案」に残る)
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(self.seg("s2")["text"], "今日は晴れです")

    def test_unclear_tags_row_only_and_undo(self):
        # 聞き取れない(5)= 音のメモ unclear だけ。文字・fill・候補の採否は触らない・Z で外れる(10-25 確かめるの混ざりと BGM のルール)
        got = apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "unclear"}})
        s = self.seg("s1")
        self.assertEqual((s["text"], s["fill"]["from"], s.get("tags")), ("埋めた文", "うめたぶん", ["unclear"]))
        apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "unclear"}})
        self.assertEqual((self.seg("s2")["text"], self.seg("s2").get("tags")), ("今日は晴れです", ["unclear"]))
        self.assertFalse(self.fb().get("dismissed"))
        apply.undo(self.ctx, got["answer"])
        self.assertNotIn("tags", self.seg("s1"))

    def test_fill_typed_text(self):
        apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "other", "text": "梅田分"}})
        s = self.seg("s1")
        self.assertEqual((s["text"], s.get("fill"), s.get("proofed")), ("梅田分", None, None))

    def test_alt_accept_and_keep_record_feedback_and_undo(self):
        got = apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "2"}})
        self.assertEqual(self.seg("s2")["text"], "今日は腫れです")
        fb = self.fb()
        self.assertEqual(fb["alt"], {"acc": 1, "rej": 0})
        self.assertEqual(fb["dismissed"], {})
        self.assertNotIn("proofed", self.seg("s2"))
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(self.seg("s2")["text"], "今日は晴れです")
        self.assertEqual(self.fb()["alt"], {"acc": 0, "rej": 0})

        # 「そのまま」は候補を出さない印にする
        got = apply.answer(self.ctx, card("alt", "s2", dict(CAND, also=[])), {"answer": {"choice": "1"}})
        self.assertEqual(self.seg("s2")["text"], "今日は晴れです")
        fb = self.fb()
        self.assertEqual(fb["alt"], {"acc": 0, "rej": 1})
        self.assertEqual(fb["dismissed"], {TID: ["s2|晴=>腫"]})
        apply.undo(self.ctx, got["answer"])
        self.assertEqual((self.fb()["alt"], self.fb()["dismissed"]), ({"acc": 0, "rej": 0}, {}))

    def test_stale_row_is_refused(self):
        d = doc()
        d["segments"][1]["text"] = "全然違う文"
        testkit.write_json(store.tx_path(TID), d)
        self.refused(card("alt", "s2", CAND), {"choice": "2"}, "gone")
        self.assertNotIn("alt", self.fb())   # 断ったら記録も残さない
        self.refused(card("alt", "s9", CAND), {"choice": "2"})   # 行がもう無い
        self.refused(card("alt", "s2"), {"choice": "2"})         # 候補が組み直せない

    def test_undo_refused_when_row_changed_afterwards(self):
        got = apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "2"}})
        d = doc()
        d["segments"][1]["text"] = "人が直した"
        testkit.write_json(store.tx_path(TID), d)
        with self.assertRaises(apply.Refused) as e:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(e.exception.error, "changed")
        self.assertEqual(self.fb()["alt"]["acc"], 1)   # 文書を戻せないときは記録も戻さない

    def test_undo_refused_when_flag_changed_afterwards(self):
        """文字が同じでも、答えたあとに印を直していたら Z は断る(印・後処理の札を黙って上書きしない)"""
        got = apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "2"}})
        d = store.read_transcript(TID)
        d["segments"][0]["flag"] = "メモ、人が足した印"
        store.commit(TID, d, why="save")
        with self.assertRaises(apply.Refused) as e:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(e.exception.error, "changed")
        self.assertEqual(self.seg("s1")["flag"], "メモ、人が足した印")

    def test_busy_and_eval_are_refused(self):
        """処理中の文書と評価用の文書には反映しない(声・時刻のカードと同じ守り)"""
        from flow import jobs as _heavy
        with mock.patch.object(_heavy, "doc_busy", return_value=True):
            self.refused(card("fill", "s1"), {"choice": "2"}, "busy")
        d = store.read_transcript(TID)
        d["evalSet"] = True
        store.commit(TID, d, why="save")
        self.refused(card("fill", "s1"), {"choice": "2"}, "eval")

    def test_human_why_is_registered(self):
        self.assertIn("check:read", store.HUMAN_WHYS)
        self.assertFalse(store.HUMAN_WHYS & store.MACHINE_WHYS)

    def test_answer_is_logged_with_choice(self):
        apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "1"}, "ms": 900})
        with open(answerlog.answers_path(self.app), encoding="utf-8") as f:
            row = json.loads(f.readline())
        self.assertEqual((row["kind"], row["source"], row["answer"]), ("read", "fill", {"choice": "1"}))


if __name__ == "__main__":
    unittest.main()
