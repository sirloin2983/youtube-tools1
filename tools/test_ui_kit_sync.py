"""ui-kit の写しが正本と一致しているか(python -m unittest tools/test_ui_kit_sync.py)。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_ui_kit as S  # noqa: E402


class UiKitSyncTest(unittest.TestCase):
    def test_copies_match(self):
        self.assertEqual(S.main(["--check"]), 0, "python tools/sync_ui_kit.py で写し直してください")

    def test_embed_replaces_only_between_marks(self):
        k = {"css": ".a{}\n", "js": "var x=1;\n"}
        src = "<style>/* ui-kit:css:begin */old/* ui-kit:css:end */ .mine{}</style><script>/* ui-kit:js:begin */old/* ui-kit:js:end */</script>"
        out = S.embed(src, k, "t")
        self.assertIn("/* ui-kit:css:begin */\n.a{}\n/* ui-kit:css:end */ .mine{}", out)
        self.assertIn("/* ui-kit:js:begin */\nvar x=1;\n/* ui-kit:js:end */", out)
        self.assertEqual(S.embed(out, k, "t"), out)   # 2回目は変わらない

    def test_embed_rejects_missing_or_duplicate_marks(self):
        k = {"css": "", "js": ""}
        with self.assertRaises(ValueError):
            S.embed("<style></style>", k, "t")
        dup = "/* ui-kit:css:begin *//* ui-kit:css:end *//* ui-kit:css:begin *//* ui-kit:css:end *//* ui-kit:js:begin *//* ui-kit:js:end */"
        with self.assertRaises(ValueError):
            S.embed(dup, k, "t")

    def test_embed_rejects_closing_tags(self):
        src = "/* ui-kit:css:begin *//* ui-kit:css:end *//* ui-kit:js:begin *//* ui-kit:js:end */"
        with self.assertRaises(ValueError):
            S.embed(src, {"css": "", "js": "a='</script>'"}, "t")


if __name__ == "__main__":
    unittest.main()
