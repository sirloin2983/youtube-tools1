"""「確かめる」の記号のカードの反映(src/human/check/symbol.py)の単体テスト: 答えの形・「例外にする」で字を足し Z で外す・
前から足してあった字は Z で外さない・ok と迷うは記録だけ・記号でない鍵は断る。一時の作業データだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/human/check/test_symbol.py -v
"""
import json
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> check -> human -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from human.check import apply, symbol  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402


def card(code="u0021"):
    return {"id": "symbol:asr:" + code, "kind": "symbol", "source": "asr", "case": {"id": "", "title": ""},
            "target": {"symbol": code, "docId": None, "row": None}, "options": []}


class SymbolCardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-check-symbol-")
        self.ctx = apply.Context(os.path.join(self.tmp, "app"), ROOT)
        self.path = symbol.extra_path(self.ctx.app_dir)

    def kept(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)["keep_chars"]

    def test_check(self):
        check = apply._REG[("symbol", "asr")].check
        for c in ("ok", "keep", "unsure"):
            self.assertEqual(check({"choice": c}), {"choice": c})
        for b in (None, {}, {"choice": "x"}, {"choice": "ok", "x": 1}):
            with self.assertRaises(ValueError):
                check(b)

    def test_keep_adds_and_undo_removes(self):
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "keep"}})
        self.assertEqual(r["applied"], {"symbol": "u0021", "added": True})
        self.assertIn("!", self.kept())
        apply.undo(self.ctx, r["answer"])
        self.assertNotIn("!", self.kept())

    def test_ok_and_unsure_record_only(self):
        for c, code in (("ok", "u3001"), ("unsure", "u3002")):   # 同じカードに 2 度は答えられない
            r = apply.answer(self.ctx, card(code), {"answer": {"choice": c}})
            self.assertEqual(r["applied"], {"symbol": code, "added": False})
        self.assertFalse(os.path.exists(self.path))

    def test_undo_keeps_char_added_before(self):
        testkit.write_json(self.path, {"keep_chars": {"!": {"card": "earlier"}}})
        r = apply.answer(self.ctx, card(), {"answer": {"choice": "keep"}})
        self.assertFalse(r["applied"]["added"])
        apply.undo(self.ctx, r["answer"])
        self.assertIn("!", self.kept())

    def test_bad_target(self):
        with self.assertRaises(apply.Refused):
            apply.answer(self.ctx, card("u0041"), {"answer": {"choice": "keep"}})   # 「A」は記号でない


if __name__ == "__main__":
    unittest.main()
