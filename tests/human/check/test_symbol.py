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

    def test_place_cards_make_proposals(self):
        """1 か所ずつのカード(11-02 の案 1): 記録だけ・同じ場面の答えが 3 件そろうと決まりの案・認めた「残す」は symbols.apply が残す・
        認めなかった案は答えが 3 件増えるまで出ない・食い違う答えの場面は案にしない"""
        from pipeline.transcribe import symbols as S

        def place(i, ch="u002e", scene=("digit", "digit")):
            return {"id": "symbol:asr:aaaaaaaaaaaa#0#%d" % i, "kind": "symbol", "source": "asr", "case": {"id": "", "title": ""},
                    "target": {"symbol": ch, "docId": "aaaaaaaaaaaa", "row": None, "seg": 0, "at": i, "scene": list(scene), "ctx": "1[.]5"}}
        for i in range(2):
            got = apply.answer(self.ctx, place(i), {"answer": {"choice": "keep"}})
            self.assertEqual(got["applied"]["scene"], ["u002e", "digit", "digit"])
        self.assertFalse(os.path.exists(self.path))   # 記録だけ(字を足さない)
        self.assertEqual(symbol.proposals(self.ctx.app_dir), [])   # 2 件では案にしない
        apply.answer(self.ctx, place(2), {"answer": {"choice": "keep"}})
        apply.answer(self.ctx, place(3, scene=("kana", "kana")), {"answer": {"choice": "keep"}})
        apply.answer(self.ctx, place(4, scene=("kana", "kana")), {"answer": {"choice": "ok"}})
        apply.answer(self.ctx, place(5, scene=("kana", "kana")), {"answer": {"choice": "keep"}})
        p = symbol.proposals(self.ctx.app_dir)
        self.assertEqual([(x["text"], x["n"]) for x in p], [("数字と数字の間の「.」は残す", 3)])   # かなの間は答えが食い違うので案にしない
        symbol.decide(self.ctx.app_dir, ".", "digit", "digit", "keep", False)
        self.assertEqual(symbol.proposals(self.ctx.app_dir), [])   # 認めなかった = 答えが増えるまで出さない
        symbol.decide(self.ctx.app_dir, ".", "digit", "digit", "keep", True)
        scenes = S.read_scenes(symbol.rules_path(self.ctx.app_dir))
        self.assertEqual((S.apply("1・2")[0], S.apply("1・2", None, {("・", "digit", "digit"): "認めた"})[0]), ("12", "1・2"))   # 場面の決まりで残す
        self.assertEqual(symbol.decided_scenes(self.ctx.app_dir), {(".", "digit", "digit"): "keep"})
        self.assertIn((".", "digit", "digit"), scenes)
        apply.answer(self.ctx, place(6, scene=("kana", "kana")), {"answer": {"choice": "unsure"}})
        self.assertEqual([u["text"] for u in symbol.unsure_list(self.ctx.app_dir)], ["1[.]5"])
        with self.assertRaises(ValueError):
            symbol.decide(self.ctx.app_dir, ".", "digit", "nope", "keep", True)


if __name__ == "__main__":
    unittest.main()
