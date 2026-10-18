"""「この行は声ですか?」の反映(src/human/check/speech.py)の単体テスト: 答えの形・keep は文書を触らない・drop は noSub と novoice を付ける(行は消さない・
校正済みにしない・ほかのメモは残す)・Z で戻す・直されたら断る・評価用を断る。一時の作業データの文書だけを使う。

実行(リポジトリ直下から): py -3.10 -m unittest src/human/check/tests/test_speech.py -v
"""
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> human -> src
for _p in (os.path.join(ROOT, "editor"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human.check import answerlog, apply, speech  # noqa: E402
from human.proof import store  # noqa: E402
from ytt import schemas  # noqa: E402
from human.tests._workdata import temporary_workdata  # noqa: E402

TID = "0123456789ab"


def card(row="s1", tid=TID):
    return {"id": "speech:diar:%s#%s" % (tid, row), "kind": "speech", "source": "diar", "case": {"id": "v1", "title": "t"},
            "target": {"docId": tid, "row": row}, "options": ["keep", "drop"]}


class SpeechApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "ytt-check-speech-")
        self.doc = {"id": TID, "updatedAt": 1, "segments": [
            {"id": "s1", "start": 10.0, "end": 12.0, "text": "あいう", "speaker": "S1", "flag": "", "proofed": False},
            {"id": "s2", "start": 12.5, "end": 14.0, "text": "えお", "speaker": "S1", "flag": "", "tags": ["bgm"]}]}
        store.commit(TID, self.doc, why="save")
        self.ctx = apply.Context(os.path.join(self.tmp, "app"), ROOT)

    def seg(self, rid="s1"):
        return next(g for g in store.read_transcript(TID)["segments"] if g["id"] == rid)

    def test_registered_and_why(self):
        self.assertTrue(apply._registered("speech", "diar"))
        self.assertIn("check:speech", store.HUMAN_WHYS)
        self.assertIn("novoice", schemas.ROW_TAGS)

    def test_check(self):
        self.assertEqual(speech._check({"choice": "keep"}), {"choice": "keep"})
        self.assertEqual(speech._check({"choice": "drop"}), {"choice": "drop"})
        for bad in (None, {}, {"choice": "x"}, "keep", {"choice": "drop", "x": 1}, {"choice": True}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                speech._check(bad)

    def test_keep_does_not_touch_doc(self):
        before = store.read_transcript(TID)
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "keep"}})
        self.assertEqual(r["applied"], {"docId": TID, "row": "s1", "changed": False})
        self.assertEqual(store.read_transcript(TID), before)   # 更新日時も含めて同じ
        row = answerlog.state(self.ctx.app_dir).answers[r["answer"]]
        self.assertEqual(row["answer"], {"choice": "keep"})

    def test_drop_sets_nosub_and_tag_then_undo(self):
        before = self.doc["updatedAt"]
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "drop"}})
        self.assertEqual(r["applied"]["changed"], True)
        self.assertEqual(r["applied"]["before"], {"noSub": False, "tags": []})
        g = self.seg()
        self.assertEqual((g.get("noSub"), g["tags"]), (True, ["novoice"]))
        self.assertEqual((g["start"], g["end"], g["text"]), (10.0, 12.0, "あいう"))   # 行は消さない・時刻と文字は変えない
        self.assertFalse(g["proofed"])   # 校正済みにはしない(元のまま)
        self.assertGreater(store.read_transcript(TID)["updatedAt"], before)
        u = apply.undo(self.ctx, r["answer"])
        self.assertTrue(u["reverted"]["changed"])
        g = self.seg()
        self.assertNotIn("noSub", g)
        self.assertNotIn("tags", g)

    def test_drop_keeps_existing_tags(self):
        r = apply.answer(self.ctx, card("s2"), {"answer": {"choice": "drop"}})
        self.assertEqual(r["applied"]["before"], {"noSub": False, "tags": ["bgm"]})
        self.assertEqual(self.seg("s2")["tags"], ["bgm", "novoice"])
        apply.undo(self.ctx, r["answer"])
        self.assertEqual(self.seg("s2")["tags"], ["bgm"])
        # 二度目の消すは文書を変えない(冪等)
        apply.answer(self.ctx, card(), {"answer": {"choice": "drop"}})
        before = store.read_transcript(TID)
        out = speech._apply_speech(self.ctx, card(), {"choice": "drop"})
        self.assertEqual(out["changed"], False)
        self.assertEqual(store.read_transcript(TID), before)

    def test_undo_refused_when_changed_later(self):
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "drop"}})
        doc = store.read_transcript(TID)
        next(g for g in doc["segments"] if g["id"] == "s1")["noSub"] = False
        store.commit(TID, doc, why="save")
        with self.assertRaises(apply.Refused) as cm:
            apply.undo(self.ctx, r["answer"])
        self.assertEqual((cm.exception.code, cm.exception.error), (409, "changed"))

    def test_eval_doc_refused(self):
        doc = store.read_transcript(TID)
        doc["evalSet"] = True
        store.commit(TID, doc, why="save")
        with self.assertRaises(apply.Refused) as cm:
            apply.answer(self.ctx, card(), {"answer": {"choice": "drop"}})
        self.assertEqual((cm.exception.code, cm.exception.error), (409, "eval"))
        self.assertFalse(self.seg().get("noSub"))


if __name__ == "__main__":
    unittest.main()
