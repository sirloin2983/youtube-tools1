"""「確かめる」の記号のカードの出どころ(src/app/check/symbol_sources.py)の単体テスト: 文字起こしの素(<id>.asr.json)から消した記号 1 つ = 1 枚・
数の多い記号から・例は文書ごとに 1 つで 3 つまで・評価用の文書は見ない・動画の無い文書も見る・答えた記号と「例外にする」で足した字は出ない・id が読める。
一時フォルダの文書と asr.json だけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_symbol_sources.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT

from app.check import lineup, sources, symbol_sources  # noqa: E402
from human.check import apply, symbol  # noqa: E402

DOCS = {"aaaaaaaaaaaa": ["え?何それ!", "うん、そう、ね。"], "bbbbbbbbbbbb": ["0.5倍、ほんと?"], "cccccccccccc": ["あ、い、う、え"]}
EVAL_DOC = "eeeeeeeeeeee"


class SymbolSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-symbol-")
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        for k, (tid, texts) in enumerate(list(DOCS.items()) + [(EVAL_DOC, ["評価!!!!"])]):
            d = {"title": "t" + tid[:2], "updatedAt": k, "sourcePath": "", "segments": [{"id": "s1", "start": 0.0, "end": 1.0, "text": "あ"}]}
            if tid == EVAL_DOC:
                d["evalSet"] = True
            kit.write(os.path.join(tx, tid + ".json"), d)
            kit.write(os.path.join(tx, tid + ".asr.json"), {"schema": "x", "segments": [{"start": 0, "end": 1, "text": t} for t in texts]})
        self.ctx = kit.Ctx(os.path.join(self.tmp, "app"), ROOT, env={"YTT_DATA_DIR": self.tmp}, eval_dirs=[])

    def cards(self):
        return symbol_sources.symbol_asr(sources.View(self.ctx))

    def test_cards(self):
        got = self.cards()
        by = {c["text"]: c for c in got}
        self.assertEqual([c["text"] for c in got][:1], ["、"])       # 一番多い(6 回)
        self.assertEqual(set(by), {"、", "?", "!", "。"})            # 「.」は数字の間 = 残す・評価用の「!!!!」は数えない
        self.assertEqual(by["、"]["count"], 6)
        self.assertEqual(by["、"]["docs"], 3)
        self.assertEqual(by["!"]["count"], 1)
        self.assertEqual(len(by["、"]["examples"]), 3)
        self.assertEqual(len({e["docId"] for e in by["、"]["examples"]}), 3)
        ex = [e for e in by["?"]["examples"] if e["docId"] == "aaaaaaaaaaaa"][0]
        self.assertEqual((ex["left"], ex["right"]), ("え", "何それ!"))
        for c in got:
            self.assertEqual(lineup.parse_id(c["id"])[:2], ("symbol", "asr"))
            self.assertIsNone(c["media"])

    def test_answered_and_kept_are_hidden(self):
        r = apply.answer(self.ctx, {"id": "symbol:asr:u3001", "kind": "symbol", "source": "asr", "case": {"id": "", "title": ""},
                                    "target": {"symbol": "u3001"}}, {"answer": {"choice": "ok"}})
        self.assertTrue(r.get("answer"))
        apply.answer(self.ctx, {"id": "symbol:asr:u0021", "kind": "symbol", "source": "asr", "case": {"id": "", "title": ""},
                                "target": {"symbol": "u0021"}}, {"answer": {"choice": "keep"}})
        st = __import__("human.check.answerlog", fromlist=["state"]).state(self.ctx.app_dir)
        got = symbol_sources.symbol_asr(sources.View(self.ctx, st))
        self.assertEqual({c["text"] for c in got}, {"?", "。"})
        self.assertTrue(os.path.exists(symbol.extra_path(self.ctx.app_dir)))

    def test_registered(self):
        self.assertIn(("symbol", "asr"), sources.registered())
        self.assertIn("symbol", lineup.NORMAL_KINDS)


if __name__ == "__main__":
    unittest.main()
