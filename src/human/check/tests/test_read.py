"""「確かめる」の読みのカードの反映(src/human/check/read.py。V2b)の単体テスト。一時フォルダの文書と learn-feedback.json だけを使う。
決まり: 行を校正済みにしない・時刻に触れない・文書は commit(why='check:read')・採否は編集の「提案」と同じ記録・Z で戻る。

実行(リポジトリ直下から): py -3.10 -m unittest src/human/check/tests/test_read.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> human -> src
for _p in (os.path.join(ROOT, "editor"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human.check import answerlog, apply, read  # noqa: E402,F401
from human.proof import learn, store  # noqa: E402
from ytt import workdata  # noqa: E402

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


CAND = {"i": 3, "wrong": "晴", "right": "腫", "tier": "alt", "also": ["yt"]}


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-check-read-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        os.makedirs(workdata.TX_DIR)
        with open(store.tx_path(TID), "w", encoding="utf-8") as f:
            json.dump(doc(), f, ensure_ascii=False)
        self.app = os.path.join(self.tmp, "app")
        self.ctx = apply.Context(self.app, ROOT)

    def seg(self, row):
        with open(store.tx_path(TID), encoding="utf-8") as f:
            return next(g for g in json.load(f)["segments"] if g["id"] == row)

    def fb(self):
        return learn.load_feedback()

    def test_registered_for_three_sources(self):
        for s in ("fill", "alt", "yt"):
            self.assertTrue(apply.registered("read", s))

    def test_check_answer_shape(self):
        self.assertEqual(read.check({"choice": "2", "x": 1}), {"choice": "2"})
        self.assertEqual(read.check({"choice": "other", "text": "  正しい文字 "}), {"choice": "other", "text": "正しい文字"})
        for bad in ({"choice": "3"}, {"choice": "other"}, {"choice": "other", "text": "  "}, {"choice": "other", "text": "あ" * 5000}, "1", None,
                    {"choice": "other", "text": "a\x01b"}):
            with self.assertRaises(ValueError):
                read.check(bad)

    def test_fill_keep_changes_nothing(self):
        with self.assertNoLogs("tx", level="INFO"):
            got = apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "1"}})
        s = self.seg("s1")
        self.assertEqual((s["text"], s["fill"]["from"], s.get("proofed")), ("埋めた文", "うめたぶん", None))
        self.assertTrue(got["ok"])

    def test_fill_revert_to_recognized_and_undo(self):
        with self.assertLogs("tx", level="INFO") as cm:
            got = apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "2"}})
        self.assertTrue(any("why=check:read" in m and "by=human" in m for m in cm.output), cm.output)
        s = self.seg("s1")
        self.assertEqual((s["text"], s.get("fill"), s["flag"]), ("うめたぶん", None, "要確認"))   # 「別の読み」の札と同じ(印だけ外す)
        self.assertNotIn("proofed", s)                                                          # 校正済みにしない
        self.assertEqual((s["start"], s["end"]), (1.0, 3.0))                                    # 時刻に触れない
        self.assertEqual(got["applied"]["before"]["text"], "埋めた文")
        apply.undo(self.ctx, got["answer"])
        s = self.seg("s1")
        self.assertEqual((s["text"], s["fill"], s["flag"]), ("埋めた文", {"from": "うめたぶん", "by": "llm"}, FLAG + "、要確認"))

    def test_fill_typed_text(self):
        apply.answer(self.ctx, card("fill", "s1"), {"answer": {"choice": "other", "text": "梅田分"}})
        s = self.seg("s1")
        self.assertEqual((s["text"], s.get("fill"), s.get("proofed")), ("梅田分", None, None))

    def test_alt_accept_records_feedback_and_undo(self):
        got = apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "2"}})
        self.assertEqual(self.seg("s2")["text"], "今日は腫れです")
        fb = self.fb()
        self.assertEqual((fb["alt"], fb["yt"]), ({"acc": 1, "rej": 0}, {"acc": 1, "rej": 0}))   # also の yt にも数える(編集の提案と同じ)
        self.assertEqual(fb["dismissed"], {})
        self.assertNotIn("proofed", self.seg("s2"))
        apply.undo(self.ctx, got["answer"])
        self.assertEqual(self.seg("s2")["text"], "今日は晴れです")
        self.assertEqual((self.fb()["alt"], self.fb()["yt"]), ({"acc": 0, "rej": 0}, {"acc": 0, "rej": 0}))

    def test_alt_keep_dismisses_candidate(self):
        got = apply.answer(self.ctx, card("alt", "s2", dict(CAND, also=[])), {"answer": {"choice": "1"}})
        self.assertEqual(self.seg("s2")["text"], "今日は晴れです")
        fb = self.fb()
        self.assertEqual(fb["alt"], {"acc": 0, "rej": 1})
        self.assertEqual(fb["dismissed"], {TID: ["s2|晴=>腫"]})
        apply.undo(self.ctx, got["answer"])
        self.assertEqual((self.fb()["alt"], self.fb()["dismissed"]), ({"acc": 0, "rej": 0}, {}))

    def test_yt_neither_types_text_and_rejects(self):
        cand = {"i": 3, "wrong": "晴", "right": "春", "tier": "yt", "also": []}
        apply.answer(self.ctx, card("yt", "s2", cand), {"answer": {"choice": "other", "text": "今日は晴れでした"}})
        self.assertEqual(self.seg("s2")["text"], "今日は晴れでした")
        self.assertEqual(self.fb()["yt"], {"acc": 0, "rej": 1})

    def test_stale_row_is_refused(self):
        d = doc()
        d["segments"][1]["text"] = "全然違う文"
        with open(store.tx_path(TID), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        with self.assertRaises(apply.Refused) as e:
            apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "2"}})
        self.assertEqual(e.exception.error, "gone")
        self.assertNotIn("alt", self.fb())   # 断ったら記録も残さない
        with self.assertRaises(apply.Refused):
            apply.answer(self.ctx, card("alt", "s9", CAND), {"answer": {"choice": "2"}})   # 行がもう無い
        with self.assertRaises(apply.Refused):
            apply.answer(self.ctx, card("alt", "s2"), {"answer": {"choice": "2"}})         # 候補が組み直せない

    def test_undo_refused_when_row_changed_afterwards(self):
        got = apply.answer(self.ctx, card("alt", "s2", CAND), {"answer": {"choice": "2"}})
        d = doc()
        d["segments"][1]["text"] = "人が直した"
        with open(store.tx_path(TID), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        with self.assertRaises(apply.Refused) as e:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(e.exception.error, "changed")
        self.assertEqual(self.fb()["alt"]["acc"], 1)   # 文書を戻せないときは記録も戻さない

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
