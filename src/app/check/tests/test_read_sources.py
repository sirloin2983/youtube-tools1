"""「確かめる」の読みのカードの出どころ read:alt(src/app/check/read_sources.py。V2b)の単体テスト。一時フォルダの文書・alt.json だけを使う。
評価用の文書・校正済みの行・却下した候補は出ない。

実行(リポジトリ直下から): py -3.12 -m unittest src/app/check/tests/test_read_sources.py -v
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT
for _p in (os.path.join(ROOT, "editor"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.check import deck, lineup, read_sources, sources  # noqa: E402
from human.check import apply  # noqa: E402
from human.proof import alt, learn  # noqa: E402
from ytt import workdata  # noqa: E402

DOC, EVAL_DOC = "aaaaaaaaaaaa", "bbbbbbbbbbbb"


write = kit.write


def doc(eval_set=False):
    d = {"title": "t", "sourcePath": "", "updatedAt": 200, "speakers": [], "segments": [
        {"id": "s1", "start": 0.0, "end": 4.0, "text": "今日は晴れです"},
        {"id": "s2", "start": 4.0, "end": 8.0, "text": "明日は雨でしょう"},
        {"id": "s3", "start": 8.0, "end": 12.0, "text": "校正済みの行です", "proofed": True},
        {"id": "s4", "start": 12.0, "end": 16.0, "text": "そのままの行です"}]}
    if eval_set:
        d["evalSet"] = True
    return d


def engine_rows():
    return [{"start": 0.0, "end": 4.0, "text": "今日は腫れです"}, {"start": 4.0, "end": 8.0, "text": "明日は雨でしょう"},
            {"start": 8.0, "end": 12.0, "text": "校正済みの行ですよ"}, {"start": 12.0, "end": 16.0, "text": "そのままの行です"}]


Ctx = kit.Ctx


class ReadSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-readsrc-")
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))   # learn-feedback.json の置き場所(読むだけ)
        self.env = {"YTT_DATA_DIR": self.tmp}
        self.tx = os.path.join(self.tmp, "transcribe", "transcripts")
        for t, e in ((DOC, False), (EVAL_DOC, True)):
            write(os.path.join(self.tx, t + ".json"), doc(e))
            write(os.path.join(self.tx, t + ".alt.json"), {"schema": alt.ALT_SCHEMA, "rows": engine_rows()})
        self.ctx = Ctx(os.path.join(self.tmp, "app"), ROOT, env=self.env, eval_dirs=[])
        deck.invalidate()

    def cards(self, source):
        return [c for c in sources.collect(self.ctx)[0] if c["kind"] == "read" and c["source"] == source]

    def test_alt_card_shape(self):
        got = self.cards("alt")
        self.assertEqual([c["id"] for c in got], ["read:alt:%s#s1" % DOC])   # 食い違う行だけ・校正済みの行と評価用は出ない
        c = got[0]
        self.assertEqual([o["text"] for o in c["options"]], ["今日は晴れです", "今日は腫れです"])
        self.assertEqual((c["target"]["docId"], c["target"]["row"], c["media"]["url"]), (DOC, "s1", "transcribe/media?id=" + DOC))
        self.assertEqual((c["_cand"]["wrong"], c["_cand"]["right"], c["_cand"]["i"]), ("晴", "腫", 3))
        self.assertEqual(c["_cand"]["tier"], "alt")

    def test_find_returns_card_with_inner_key(self):
        card = deck.find(self.ctx, "read:alt:%s#s1" % DOC)
        self.assertEqual(card["_cand"]["right"], "腫")   # 答える前の引き直しは内側の鍵も持つ

    def test_dismissed_candidate_is_not_shown(self):
        learn.record_feedback({"tid": DOC, "action": "reject", "items": [{"seg": "s1", "wrong": "晴", "right": "腫", "tier": "alt"}]})
        self.assertEqual(self.cards("alt"), [])

    def test_eval_docs_never_appear(self):
        for c in sources.collect(self.ctx, kinds=lineup.NORMAL_KINDS)[0]:   # 普段のレーン(区間カードは評価用の文書だけ)
            self.assertNotIn(EVAL_DOC, c["id"])

    def test_no_files_no_cards(self):
        os.remove(os.path.join(self.tx, DOC + ".alt.json"))
        self.assertEqual(self.cards("alt"), [])

    def test_module_registers_on_import(self):
        self.assertTrue(callable(read_sources.read_alt))


if __name__ == "__main__":
    unittest.main()
