"""設定の画面のスキーマ(src/home/settings/schema.json。S5)の編集の分(store editor)が、ytt/settings の検査(SETTINGS_PATCH_KEYS・CUT_SILENCE_RANGE。RS3-1 まで ed_learn)と
食い違っていないか。リポジトリ直下で:
    python -m unittest src/editor/tests/test_settings_schema.py
validated の鍵は api/settings/patch の検査(予定どおり通る・範囲の外は断る)、validated でない鍵は検査が無い(差分の PUT)ことを見る。"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

EDITOR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(EDITOR))   # 共通部品 ytt(src/)
sys.path.insert(0, EDITOR)
from human.proof import alt as _alt  # noqa: E402,F401  (鍵の検査の持ち主が読み込みのときに ytt/settings へ登録する = altEngine)
from ytt import settings as _settings  # noqa: E402  (編集の設定の鍵の検査。RS3-1 に ed_learn から)

SCHEMA_PATH = os.path.join(os.path.dirname(EDITOR), "home", "settings", "schema.json")


def editor_items():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        sc = json.load(f)
    for sec in sc["sections"]:
        for g in sec.get("groups", []):
            if (g.get("store") or sec.get("store")) == "editor":
                for it in g["items"]:
                    yield it


@unittest.skipUnless(os.path.isfile(SCHEMA_PATH), "schema.json が無い(ツールだけを写したテスト)")
class TestEditorSchema(unittest.TestCase):
    def setUp(self):
        self.items = list(editor_items())
        self.assertTrue(self.items)
        self.by_key = {it["key"]: it for it in self.items}

    def whole(self, top, k, v):
        """入れ子の鍵(cutSilence.noise)は最上位の物を丸ごと(ほかは既定)にして検査に渡す"""
        d = {it["key"].split(".", 1)[1]: it["default"] for it in self.items if it["key"].startswith(top + ".")}
        d[k] = v
        return d

    def test_validated_flag_matches_patch_keys(self):
        for it in self.items:
            if it["type"] == "link":
                continue
            top = it["key"].split(".")[0]
            self.assertEqual(bool(it.get("validated")), top in _settings.SETTINGS_PATCH_KEYS, "validated の印が検査の有無と違う: %s" % it["key"])

    def test_validated_values(self):
        for it in self.items:
            if not it.get("validated"):
                continue
            parts = it["key"].split("."); top = parts[0]; chk = _settings.SETTINGS_PATCH_KEYS[top]
            if len(parts) > 1:
                k = parts[1]
                ok = lambda v: chk(self.whole(top, k, v))   # noqa: E731
            else:
                ok = chk
            t = it["type"]
            if t == "enum":
                for v, _label in it["options"]:
                    self.assertTrue(ok(v), "%s = %r は通るはず" % (it["key"], v))
                self.assertFalse(ok("zz-bad"), it["key"])
            elif t in ("int", "number"):
                lo, hi = it["min"], it["max"]
                self.assertTrue(ok(lo) and ok(hi), it["key"])
                self.assertFalse(ok(lo - 1) or ok(hi + 1), "%s の範囲の外は断るはず" % it["key"])
            elif t == "bool":
                self.assertTrue(ok(True) and ok(False), it["key"])
                self.assertFalse(ok("x"), it["key"])

    def test_cut_silence_range(self):
        for k, (lo, hi) in _settings.CUT_SILENCE_RANGE.items():
            it = self.by_key["cutSilence." + k]
            self.assertEqual((it["min"], it["max"]), (lo, hi), k)

    def test_defaults_are_sane(self):
        for it in self.items:
            if it["type"] in ("int", "number"):
                self.assertTrue(it["min"] <= it["default"] <= it["max"], it["key"])


if __name__ == "__main__":
    unittest.main()
