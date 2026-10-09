"""設定の画面のスキーマ(src/home/settings/schema.json。S5)のスタジオの分(store studio の節 analyze)が、analyze.validate_settings の
範囲・既定値と食い違っていないか。リポジトリ直下で:
    python -m unittest src/studio/tests/test_settings_schema.py
review の節は画面側(review.js の sanitizeSettings)だけで検査するので、ここでは鍵の形だけ見る。"""
import json
import os
import sys
import unittest

STUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, STUDIO)
import analyze  # noqa: E402

SCHEMA_PATH = os.path.join(os.path.dirname(STUDIO), "home", "settings", "schema.json")


def studio_items():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sc = json.load(f)
    for sec in sc["sections"]:
        for g in sec.get("groups", []):
            if (g.get("store") or sec.get("store")) == "studio":
                for it in g["items"]:
                    yield it


@unittest.skipUnless(os.path.isfile(SCHEMA_PATH), "schema.json が無い(ツールだけを写したテスト)")
class TestStudioSchema(unittest.TestCase):
    def setUp(self):
        self.items = [it for it in studio_items() if it["key"].startswith("analyze.")]
        self.assertTrue(self.items)

    def test_analyze_defaults_and_ranges(self):
        base = analyze.validate_settings({})
        for it in self.items:
            k = it["key"].split(".", 1)[1]
            self.assertIn(k, base, it["key"])
            self.assertEqual(base[k], it["default"], "既定値が違う: %s" % it["key"])
            t = it["type"]
            if t in ("int", "number"):
                lo, hi = it["min"], it["max"]
                self.assertEqual(analyze.validate_settings({k: lo})[k], lo, it["key"])
                self.assertEqual(analyze.validate_settings({k: hi})[k], hi, it["key"])
                self.assertEqual(analyze.validate_settings({k: lo - 1})[k], lo, "下限で丸めるはず: %s" % it["key"])
                self.assertEqual(analyze.validate_settings({k: hi + 1})[k], hi, "上限で丸めるはず: %s" % it["key"])
            elif t == "enum":
                for v, _label in it["options"]:
                    self.assertEqual(analyze.validate_settings({k: v})[k], v, it["key"])
                self.assertEqual(analyze.validate_settings({k: "zz-bad"})[k], it["default"], it["key"])
            elif t == "bool":
                self.assertIs(analyze.validate_settings({k: True})[k], True, it["key"])
                self.assertIs(analyze.validate_settings({k: False})[k], False, it["key"])

    def test_analyze_covers_all_keys(self):
        keys = {it["key"].split(".", 1)[1] for it in self.items}
        missing = [k for k in analyze.validate_settings({}) if k not in keys and k != "noCache"]   # noCache は 1 回だけの印(保存しない)
        self.assertEqual(missing, [], "画面に無い解析の設定")

    def test_review_items_shape(self):
        for it in studio_items():
            if it["key"].startswith("review."):
                self.assertIn(it["type"], ("bool", "enum", "int", "number"), it["key"])


if __name__ == "__main__":
    unittest.main()
