"""設定の画面のスキーマ(src/app/ui/settings/schema.json。S5)と、ホームの設定の検査(prefs.py)が食い違っていないか。リポジトリ直下で:
    python -m unittest src/app/tests/test_settings_schema.py
スキーマの型・範囲・選択肢・既定値を、prefs.py の CLEANERS / DEFAULTS に実際に通して確かめる(数字をここに写さない)。
スタジオ・編集の分は src/studio/tests/test_settings_schema.py・src/editor/tests/test_settings_schema.py。"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(HOME))   # src
from app import prefs as PR  # noqa: E402

SCHEMA_PATH = os.path.join(HOME, "ui", "settings", "schema.json")
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
