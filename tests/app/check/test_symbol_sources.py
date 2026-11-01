"""「確かめる」の記号のカードの出どころ(src/app/check/symbol_sources.py)の単体テスト(11-02 の案 1): 文字起こしの素(<id>.asr.json)で消す記号が出てきた
1 か所 = 1 枚・文脈と消した後の文・記号の名前と全角 / 半角・場面(前後の字の種類)・出てくる数の多い場面から・消すと決めた記号は聞かない・評価用の文書と
whisper の頃の文字起こしの素は見ない・答えた所と認めた決まりの場面と「例外にする」で足した字(11-01)は出ない・id が読める。一時フォルダの文書と asr.json だけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_symbol_sources.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT

from app.check import lineup, sources, symbol_sources  # noqa: E402
from human.check import answerlog, apply, symbol  # noqa: E402

DOCS = {"aaaaaaaaaaaa": ["え~何それ…", "うん・そう・ね×"], "bbbbbbbbbbbb": ["0.5倍・ほんと~"], "cccccccccccc": ["あ・い・う・え、。?!「」♪"]}
EVAL_DOC, OLD_DOC = "eeeeeeeeeeee", "ffffffffffff"


class SymbolSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-symbol-")
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        for k, (tid, texts) in enumerate(list(DOCS.items()) + [(EVAL_DOC, ["評価・です"]), (OLD_DOC, ["古い・素"])]):
            d = {"title": "t" + tid[:2], "updatedAt": k, "sourcePath": "", "segments": [{"id": "s1", "start": 0.0, "end": 1.0, "text": "あ"}]}
            if tid == EVAL_DOC:
                d["evalSet"] = True
            kit.write(os.path.join(tx, tid + ".json"), d)
            run = {"engine": "whisper.cpp"} if tid == OLD_DOC else {"engine": "haas"}
            kit.write(os.path.join(tx, tid + ".asr.json"), {"schema": "x", "run": run, "segments": [{"start": 0, "end": 1, "text": t} for t in texts]})
        self.ctx = kit.Ctx(os.path.join(self.tmp, "app"), ROOT, env={"YTT_DATA_DIR": self.tmp}, eval_dirs=[])

    def cards(self):
        return symbol_sources.symbol_asr(sources.View(self.ctx, answerlog.state(self.ctx.app_dir)))

    def test_one_card_per_place(self):
        got = self.cards()
        self.assertEqual(sum(1 for c in got if c["text"] == "・"), 6)   # 1 か所 = 1 枚(評価用・whisper の頃の「・」は数えない)
        self.assertEqual({c["text"] for c in got}, {"・", "~", ".", "×"})   # 数字の間の「.」は残す・消すと決めた 、。?!「」♪ は聞かない
        first = got[0]
        self.assertEqual((first["text"], first["scene"], first["sceneCount"]), ("・", "かなとかなの間", 5))   # 出てくる数の多い場面から
        c = next(c for c in got if c["text"] == "~" and c["target"]["docId"] == "aaaaaaaaaaaa")
        self.assertEqual((c["context"]["left"], c["context"]["right"], c["context"]["removed"]), ("え", "何それ...", "え何それ..."))
        self.assertEqual((c["name"], c["target"]["scene"]), ("チルダ(半角)", ["kana", "kanji"]))
        self.assertEqual(next(x for x in got if x["text"] == "・")["name"], "中黒(全角)")
        for c in got:
            self.assertEqual(lineup.parse_id(c["id"])[:2], ("symbol", "asr"))
            self.assertIsNone(c["media"])

    def test_answered_rule_and_old_exception_are_hidden(self):
        got = self.cards()
        one = next(c for c in got if c["text"] == "×")
        apply.answer(self.ctx, one, {"answer": {"choice": "unsure"}})
        self.assertNotIn(one["id"], {c["id"] for c in self.cards()})   # 答えた所は出ない
        self.assertEqual(symbol.unsure_list(self.ctx.app_dir)[0]["text"], "うん・そう・ね[×]")   # 迷うの一覧で見返す
        symbol.decide(self.ctx.app_dir, "・", "kana", "kana", "remove", True)
        self.assertEqual(sum(1 for c in self.cards() if c["text"] == "・"), 1)   # 認めた場面(かなとかなの間)のカードは出ない
        old = {"id": "symbol:asr:u007e", "kind": "symbol", "source": "asr", "case": {"id": "", "title": ""}, "target": {"symbol": "u007e"}}
        apply.answer(self.ctx, old, {"answer": {"choice": "keep"}})   # 11-01 の記号ごとのカードの「例外にする」= その字は決まりが残す
        self.assertNotIn("~", {c["text"] for c in self.cards()})
        self.assertTrue(os.path.exists(symbol.extra_path(self.ctx.app_dir)))

    def test_registered(self):
        self.assertIn(("symbol", "asr"), sources.registered())
        self.assertIn("symbol", lineup.NORMAL_KINDS)


if __name__ == "__main__":
    unittest.main()
