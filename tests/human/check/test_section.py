"""評価のレーンの区間カードの反映(src/human/check/section.py)の単体テスト。一時の作業データに評価用の文書を作って、答える・戻すを確かめる。

実行(リポジトリ直下から): py -3.12 -m unittest tests/human/check/test_section.py -v
"""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> check -> human -> src
for _p in (os.path.join(ROOT, "editor"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from human.check import answerlog, apply  # noqa: E402
from human.check import section  # noqa: E402
from human.proof import store  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "human"))   # tests/human/(_workdata)
from _workdata import temporary_workdata  # noqa: E402

TID = "0123456789ab"


class SectionApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "ytt-check-section-")
        self.doc = {"id": TID, "evalSet": True, "start": 0.0, "end": 60.0, "updatedAt": 1, "speakers": [{"id": "S1", "name": "話者 1", "color": "#123456"}],
                    "segments": [{"id": "s1", "start": 1.0, "end": 3.0, "text": "あいう", "speaker": "S1", "flag": ""},
                                 {"id": "s2", "start": 4.0, "end": 6.0, "text": "えお", "speaker": "S1", "flag": ""},
                                 {"id": "s3", "start": 31.0, "end": 33.0, "text": "かき", "speaker": "S1", "flag": ""}]}
        store.commit(TID, self.doc, why="save")
        self.ctx = apply.Context(os.path.join(self.tmp, "app"), ROOT)

    def card(self, a=0.0, b=30.0, rows=("s1", "s2"), last=False, index=0, stamp=None):
        d = store.read_transcript(TID)
        return {"id": "section:eval:%s#%d" % (TID, int(a * 1000)), "kind": "section", "source": "eval", "case": {"id": "", "title": "t"},
                "target": {"docId": TID, "from": a, "to": b, "rows": list(rows), "updatedAt": d["updatedAt"] if stamp is None else stamp,
                           "last": last, "index": index}}

    def seg(self, rid):
        return next((g for g in store.read_transcript(TID)["segments"] if g["id"] == rid), None)

    def refused(self, c, body, error):
        with self.assertRaises(apply.Refused) as cm:
            apply.answer(self.ctx, c, body)
        self.assertEqual(cm.exception.error, error)

    def test_registered_and_why(self):
        self.assertTrue(apply._registered("section", "eval"))
        self.assertIn("check:section", store.HUMAN_WHYS)

    def test_check(self):
        c = section._check
        self.assertEqual(c({}), {"rows": [], "add": []})
        self.assertEqual(c({"rows": [{"id": "s1", "text": " い ", "speaker": "兎田ぺこら"}]})["rows"], [{"id": "s1", "text": "い", "speaker": "兎田ぺこら"}])
        self.assertEqual(c({"rows": [{"id": "s1", "drop": True, "text": "x"}]})["rows"], [{"id": "s1", "drop": True}])
        for bad in (None, [], {"x": 1}, {"rows": [{"id": "s1"}, {"id": "s1"}]}, {"rows": [{"id": "../x"}]}, {"rows": [{"id": "s1", "speaker": ""}]},
                    {"rows": [{"id": "s1", "speaker": "話者 2"}]}, {"add": [{"start": 2, "end": 1, "text": "a"}]}, {"add": [{"start": 1, "end": 2, "text": ""}]},
                    {"add": [{"start": True, "end": 2, "text": "a"}]}):
            with self.assertRaises(ValueError, msg=repr(bad)):
                c(bad)

    def test_ok_proofs_owned_rows_only(self):
        r = apply.answer(self.ctx, self.card(), {"answer": {}})
        self.assertFalse(r["applied"]["reviewed"])
        self.assertTrue(self.seg("s1")["proofed"] and self.seg("s2")["proofed"])
        self.assertNotIn("proofed", self.seg("s3"))   # 次の区間の行は触らない
        self.assertNotIn("evalReviewed", store.read_transcript(TID))

    def test_edit_add_drop_and_undo(self):
        ans = {"rows": [{"id": "s1", "text": "あいうえ", "speaker": "兎田ぺこら"}, {"id": "s2", "drop": True}],
               "add": [{"start": 25.0, "end": 40.0, "text": "足した", "speaker": "兎田ペこら"}]}
        r = apply.answer(self.ctx, self.card(), {"answer": ans})
        d = store.read_transcript(TID)
        names = {s["id"]: s["name"] for s in d["speakers"]}
        g1 = self.seg("s1")
        self.assertEqual((g1["text"], names[g1["speaker"]], g1["proofed"]), ("あいうえ", "兎田ぺこら", True))
        self.assertIsNone(self.seg("s2"))
        add = self.seg(r["applied"]["added"][0])
        self.assertEqual((add["start"], add["end"], add["text"], add["speaker"], add["proofed"]), (25.0, 30.0, "足した", g1["speaker"], True))   # 区間の終わりで切る・同じ人(ひらがなとカタカナの違い)は同じ話者
        u = apply.undo(self.ctx, r["answer"])
        self.assertTrue(u["reverted"]["reverted"])
        d = store.read_transcript(TID)
        self.assertEqual([g["id"] for g in d["segments"]], ["s1", "s2", "s3"])
        self.assertEqual((self.seg("s1")["text"], self.seg("s1")["speaker"]), ("あいう", "S1"))
        self.assertNotIn("proofed", self.seg("s1"))
        self.assertEqual([s["name"] for s in d["speakers"]], ["話者 1"])   # 足した話者は外す

    def test_last_section_marks_reviewed_and_undo_removes(self):
        apply.answer(self.ctx, self.card(), {"answer": {}})
        r = apply.answer(self.ctx, self.card(30.0, 60.0, ("s3",), last=True, index=1), {"answer": {}})
        d = store.read_transcript(TID)
        rv = d["evalReviewed"]
        self.assertEqual((rv["via"], rv["sections"], rv["rows"]), ("card", 2, 3))
        self.assertTrue(all(g.get("proofedAt") != rv["at"] for g in d["segments"]))   # drill_unreviewed が区間の答えを外さない
        apply.undo(self.ctx, r["answer"])
        d = store.read_transcript(TID)
        self.assertNotIn("evalReviewed", d)
        self.assertTrue(self.seg("s1")["proofed"])   # 前の区間の答えはそのまま

    def test_refuse(self):
        self.refused(self.card(stamp=12345), {"answer": {}}, "changed")
        self.refused(self.card(rows=("s1", "nope")), {"answer": {}}, "changed")
        self.refused(self.card(), {"answer": {"rows": [{"id": "s3", "text": "x"}]}}, "bad_request")   # 持ち主でない行は直せない
        with mock.patch.object(section._doc, "busy", return_value=True):
            self.refused(self.card(), {"answer": {}}, "busy")
        d = store.read_transcript(TID)
        d.pop("evalSet")
        store.commit(TID, d, why="save")
        self.refused(self.card(), {"answer": {}}, "not_eval")
        self.assertEqual(answerlog.state(self.ctx.app_dir).effective(), [])

    def test_undo_refused_when_changed_later(self):
        r = apply.answer(self.ctx, self.card(), {"answer": {"rows": [{"id": "s1", "text": "直した"}]}})
        d = store.read_transcript(TID)
        next(g for g in d["segments"] if g["id"] == "s1")["text"] = "あとで別に"
        store.commit(TID, d, why="save")
        with self.assertRaises(apply.Refused) as cm:
            apply.undo(self.ctx, r["answer"])
        self.assertEqual(cm.exception.error, "changed")

    def test_switch(self):
        """既定オン。明示でオフにした新しい鍵だけが効き、既定オフのころの鍵のオフは読み替える"""
        def with_settings(d, env=""):
            return mock.patch.dict(os.environ, {section.SWITCH_ENV: env}), mock.patch.object(section._settings, "load_settings", return_value=d)
        for d, want in (({}, True), ({"checkSectionCards": False}, True), ({section.SETTING: False}, False), ({section.SETTING: True}, True)):
            e, s = with_settings(d)
            with e, s:
                self.assertEqual(section.enabled(), want, d)
        e, s = with_settings({section.SETTING: False}, "on")
        with e, s:
            self.assertTrue(section.enabled())
        e, s = with_settings({}, "off")
        with e, s:
            self.assertFalse(section.enabled())


if __name__ == "__main__":
    unittest.main()
