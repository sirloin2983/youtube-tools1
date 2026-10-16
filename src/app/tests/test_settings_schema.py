"""設定の画面のスキーマ(src/home/settings/schema.json。S5)と、ホームの設定の検査(prefs.py)が食い違っていないか。リポジトリ直下で:
    python -m unittest src/home/tests/test_settings_schema.py
スキーマの型・範囲・選択肢・既定値を、prefs.py の CLEANERS / DEFAULTS に実際に通して確かめる(数字をここに写さない)。
スタジオ・編集の分は src/studio/tests/test_settings_schema.py・src/editor/tests/test_settings_schema.py。"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.dirname(HERE)
sys.path.insert(0, HOME)
import prefs as PR  # noqa: E402

SCHEMA_PATH = os.path.join(HOME, "settings", "schema.json")
TYPES = ("bool", "enum", "int", "number", "text", "folder", "textarea", "link")
NO_UI = {"autorun.mode", "live.recorders", "live.liveTx.model"}   # 画面に出さない鍵(mode は案件ごと・recorders は一覧・liveTx.model は固定)


def load_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def items_of(schema, store):
    """(節, 項目) を store ごとに"""
    for sec in schema["sections"]:
        for g in sec.get("groups", []):
            st = g.get("store") or sec.get("store")
            if st == store:
                for it in g["items"]:
                    yield sec, it


def nest(parts, v):
    for p in reversed(parts):
        v = {p: v}
    return v


def leaf(d, parts):
    for p in parts:
        if not isinstance(d, dict) or p not in d:
            return KeyError
        d = d[p]
    return d


def leaves(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict) and v:
            yield from leaves(v, prefix + k + ".")
        else:
            yield prefix + k


class TestSchemaShape(unittest.TestCase):
    def test_shape(self):
        sc = load_schema()
        ids, keys = [], []
        for sec in sc["sections"]:
            ids.append(sec["id"])
            self.assertTrue(sec.get("title"))
            for g in sec.get("groups", []):
                self.assertTrue(g.get("store") or sec.get("store") or sec.get("kind"), sec["id"])
                for it in g["items"]:
                    keys.append(it["key"])
                    self.assertIn(it["type"], TYPES, it["key"])
                    self.assertTrue(it.get("label"), it["key"])
                    if it["type"] == "enum":
                        self.assertTrue(it.get("options"), it["key"])
                        self.assertIn(it["default"], [o[0] for o in it["options"]], it["key"])
                    if it["type"] in ("int", "number"):
                        self.assertIn("min", it, it["key"]); self.assertIn("max", it, it["key"])
                        self.assertTrue(it["min"] <= it["default"] <= it["max"], it["key"])
                    if it["type"] == "link":
                        self.assertTrue(it.get("link", {}).get("href"), it["key"])
                    if it.get("when"):
                        self.assertIn(it["when"]["key"], [x["key"] for s2 in sc["sections"] for g2 in s2.get("groups", []) for x in g2["items"]], it["key"])
        self.assertEqual(len(ids), len(set(ids)), "節の id が重なる")
        self.assertEqual(len(keys), len(set(keys)), "鍵が重なる")


class TestHomeStore(unittest.TestCase):
    """store home の項目を prefs.py の検査に通す"""

    def setUp(self):
        self.sc = load_schema()
        self.items = list(items_of(self.sc, "home"))
        self.assertTrue(self.items)

    def cur(self, section):
        c = copy.deepcopy(PR.DEFAULTS[section])
        if section == "backup":
            c["folder"] = "C:\\x\\backup"   # enabled をオンにする検査はフォルダが要る
        if section == "accuracy":
            c["nightFrom"] = 12   # 開始と終わりが同じ時刻は断る(別のテストで見る)ので、範囲の端の検査がそれに当たらない値に
        return c

    def accept(self, section, parts, v):
        out = PR.CLEANERS[section](nest(parts, v), self.cur(section))
        return leaf(out, parts)

    def reject(self, section, parts, v, key):
        with self.assertRaises(PR.PrefsError, msg="%s = %r は断るはず" % (key, v)):
            PR.CLEANERS[section](nest(parts, v), self.cur(section))

    def test_keys_exist_and_defaults_match(self):
        for _sec, it in self.items:
            parts = it["key"].split(".")
            self.assertIn(parts[0], PR.PATCHABLE, it["key"])
            d = leaf(PR.DEFAULTS[parts[0]], parts[1:])
            self.assertIsNot(d, KeyError, "prefs.py に無い鍵: %s" % it["key"])
            if "default" in it:
                self.assertEqual(it["default"], d, "既定値が違う: %s" % it["key"])

    def test_all_leaves_are_in_schema(self):
        keys = {it["key"] for _s, it in self.items}
        sections = {it["key"].split(".")[0] for _s, it in self.items}
        missing = [k for sec in sections for k in (sec + "." + x for x in leaves(PR.DEFAULTS[sec])) if k not in keys and k not in NO_UI]
        self.assertEqual(missing, [], "画面に無い設定(出すか NO_UI に書く)")

    def test_values_pass_cleaners(self):
        for _sec, it in self.items:
            parts = it["key"].split("."); section, rest, key = parts[0], parts[1:], it["key"]
            t = it["type"]
            if t == "bool":
                self.assertIs(self.accept(section, rest, True), True, key)
                self.assertIs(self.accept(section, rest, False), False, key)
            elif t == "enum":
                for v, _label in it["options"]:
                    self.assertEqual(self.accept(section, rest, v), v, key)
                self.reject(section, rest, "zz-bad-zz", key)
            elif t in ("int", "number"):
                lo, hi = it["min"], it["max"]
                self.assertEqual(self.accept(section, rest, lo), lo, key)
                self.assertEqual(self.accept(section, rest, hi), hi, key)
                self.reject(section, rest, lo - 1, key)
                self.reject(section, rest, hi + 1, key)
                if t == "int":
                    self.reject(section, rest, lo + 0.5, key)
            elif t == "folder":
                self.assertEqual(self.accept(section, rest, "C:\\x\\y"), "C:\\x\\y", key)
                self.assertEqual(self.accept(section, rest, ""), "", key)
                self.reject(section, rest, "x" * 300, key)
            elif t in ("text", "textarea"):
                self.assertEqual(self.accept(section, rest, it["default"]), it["default"], key)
                self.reject(section, rest, "\x00bad", key)

    def test_accuracy_cross_field(self):
        """夜の窓の開始と終わりが同じは断る(スキーマは範囲だけ。画面は行に理由を出す)"""
        with self.assertRaises(PR.PrefsError):
            PR.CLEANERS["accuracy"]({"nightFrom": 6}, {"enabled": True, "nightFrom": 1, "nightTo": 6})


if __name__ == "__main__":
    unittest.main()
