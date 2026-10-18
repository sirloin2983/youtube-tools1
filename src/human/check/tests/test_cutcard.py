"""「確かめる」の自動カットのカードの答えの記録(src/human/check/cutcard.py)の単体テスト: 答えの形(出どころごとの選び)・
スイッチ(環境変数と編集の設定)・3 つの出どころの登録・答えと Z が文書と編集の内容(.edit.json)を変えないこと。
一時の作業データの文書と編集の内容だけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest src/human/check/tests/test_cutcard.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> human -> src
for _p in (os.path.join(ROOT, "editor"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human.check import answerlog, apply, cutcard  # noqa: E402
from human.proof import store  # noqa: E402
from human.tests._workdata import temporary_workdata  # noqa: E402

TID = "0123456789ab"
KEEPS = [[0.0, 10.0], [10.5, 20.0], [22.0, 30.0]]


def card(source, tid=TID):
    return {"id": "cut:%s:%s#5" % (source, tid), "kind": "cut", "source": source, "case": {"id": "v1", "title": "t"},
            "target": {"docId": tid, "cut": [10.0, 10.5]} if source != "whole" else {"docId": tid, "keeps": KEEPS},
            "options": []}


class CutCardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "ytt-check-cut-")
        self.doc = {"id": TID, "updatedAt": 1, "segments": [
            {"id": "s1", "start": 0.0, "end": 10.0, "text": "あいう", "speaker": "S1", "flag": "", "proofed": False}]}
        store.commit(TID, self.doc, why="save")
        self.edit_file = store.edit_path(TID, for_write=True)
        os.makedirs(os.path.dirname(self.edit_file), exist_ok=True)
        with open(self.edit_file, "w", encoding="utf-8") as f:
            json.dump({"schema": store.EDIT_SCHEMA, "rev": 1, "updatedAt": 1, "sources": [], "clips": [],
                       "draft": {"origin": "rows", "settings": {}, "keepsSec": KEEPS, "at": 1}}, f)
        self.ctx = apply.Context(os.path.join(self.tmp, "app"), ROOT)

    def read_edit(self):
        with open(self.edit_file, "rb") as f:
            return f.read()

    def test_registered_for_three_sources(self):
        for src in ("edge", "gap", "whole"):
            self.assertTrue(apply._registered("cut", src), src)

    def test_switch(self):
        """既定オン(3-64 (cc1) B)。明示でオフにした新しい鍵だけが効き、既定オフのころの鍵のオフは読み替える"""
        def with_settings(d, env=""):
            return mock.patch.dict(os.environ, {cutcard.SWITCH_ENV: env}), mock.patch.object(cutcard._settings, "load_settings", return_value=d)
        for d, want in (({}, True), ({"checkCutCards": False}, True), ({cutcard.SETTING: False}, False), ({cutcard.SETTING: True}, True)):
            e, s = with_settings(d)
            with e, s:
                self.assertEqual(cutcard.enabled(), want, d)
        e, s = with_settings({}, "off")
        with e, s:
            self.assertFalse(cutcard.enabled())

    def test_check_per_source(self):
        ok = {"edge": ("good", "early", "late", "keep"), "gap": ("ok", "keep"), "whole": ("good", "tempo", "unnatural")}
        for src, choices in ok.items():
            check = cutcard._checker(src)
            for c in choices:
                self.assertEqual(check({"choice": c}), {"choice": c})
            bad = [None, {}, {"choice": "x"}, "good", {"choice": "good", "x": 1}, {"choice": True}]
            if src == "edge":
                bad += [{"choice": "ok"}]
            if src == "gap":
                bad += [{"choice": "good"}, {"choice": "early"}]
            if src == "whole":
                bad += [{"choice": "keep"}]
            for b in bad:
                with self.assertRaises(ValueError, msg="%s %r" % (src, b)):
                    check(b)

    def test_answer_and_undo_leave_doc_and_edit_unchanged(self):
        before_doc = store.read_transcript(TID)
        before_edit = self.read_edit()
        for src, choice in (("edge", "early"), ("gap", "keep"), ("whole", "tempo")):
            r = apply.answer(self.ctx, card(src), {"answer": {"choice": choice}})
            self.assertEqual(r["applied"], {"docId": TID, "recorded": True})
            row = answerlog.state(self.ctx.app_dir).answers[r["answer"]]
            self.assertEqual(row["answer"], {"choice": choice})
            u = apply.undo(self.ctx, r["answer"])
            self.assertTrue(u.get("ok", True))
        self.assertEqual(store.read_transcript(TID), before_doc)   # 文書は更新日時も含めて同じ
        self.assertEqual(self.read_edit(), before_edit)            # 編集の内容は同じ
        with self.assertRaises(apply.Refused):                     # 許されない答え(edge に ok など)は記録より前に断る
            apply.answer(self.ctx, card("edge"), {"answer": {"choice": "ok"}})


if __name__ == "__main__":
    unittest.main()
