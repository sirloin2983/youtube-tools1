# -*- coding: utf-8 -*-
"""manage/keep/learnpack(学習の束を作る側)のテスト。  py -3.12 -m unittest src/manage/keep/tests/test_learnpack.py -v

- 束ができる(learning.json の sha256・size が中身と合う・latest.json・設定は置換辞書と用語集だけ)
- 元が変わらなければ作らない / 変われば新しい版 / 直近 3 版を残して古い版は消す
- 声は名簿にある人だけ(名簿に無い人の声が出ない)
- ③ の export_rules は、計算済みの規則から ① の fixed_finder・pick_glossary で選んだ結果が learn.find_suggestions(only_high)・auto_glossary と同じ・辞書の版の元の文字が doc_jobs.dict_learned と同じ
作業データは一時フォルダ(本物には触らない)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import json
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> keep -> manage -> src
sys.path.insert(0, SRC)
from human.proof import doc_jobs, learn  # noqa: E402
from manage.keep import learnpack  # noqa: E402
from pipeline.transcribe import replace  # noqa: E402
from ytt.testkit import read_json as rd, tempdir, write_json as jwrite  # noqa: E402

RULES = {
    ("ぺこ", "ぺこら"): {"pos": 4, "docs": {"a", "b"}, "pctx": [("あ", "い")] * 4, "neg": [], "ctx": False},                 # 高
    ("トル", "ポル"): {"pos": 3, "docs": {"a"}, "pctx": [("あ", "い")] * 3, "neg": [], "ctx": False},                       # 文書 1 件 = 高でない
    ("きも", "肝"): {"pos": 5, "docs": {"a", "b"}, "pctx": [("あ", "い")] * 5, "neg": [("x", "y")], "ctx": False},          # 残した例あり = 高でない
    ("あれ", "これ"): {"pos": 5, "docs": {"a", "b", "c"}, "pctx": [("あ", "い")] * 5, "neg": [], "ctx": True},               # 高(用語には入れない)
    ("ぺこらん", "ぺこらさん"): {"pos": 3, "docs": {"a", "b"}, "pctx": [("あ", "い")] * 3, "neg": [], "ctx": False},       # 高(長い誤りを優先)
    ("むむ", "ふふ"): {"pos": 6, "docs": {"a", "b"}, "pctx": [("あ", "い")] * 6, "neg": [], "ctx": False},                   # 却下ありで高でない
}
FB = {"stat": {"むむ=>ふふ": {"acc": 0, "rej": 1}}, "dismissed": {}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempdir(self, "ytt-learnpack-")
        self.data = os.path.join(self.tmp, "transcribe")
        self.root = os.path.join(self.tmp, "sync", "学習")
        jwrite(os.path.join(self.data, "settings.json"), {"replacements": "a=>b", "glossary": "ぺこら", "model": "large", "evalDirs": ["x"]})
        jwrite(os.path.join(self.data, "learn-feedback.json"), FB)
        self.roster = os.path.join(self.tmp, "roster.json")
        jwrite(self.roster, {"asOf": "2026", "groups": [{"id": "g", "label": "G", "names": ["兎田ぺこら", "宝鐘 マリン"]}]})
        self.members = os.path.join(self.tmp, "members.json")
        jwrite(self.members, [{"name": "兎田ぺこら", "color": "#fff"}])
        jwrite(os.path.join(self.data, "voices", "voxceleb.json"), {"schema": "ytt-voices/v1", "embedding": "voxceleb", "voices": {
            "兎田ぺこら": {"vec": [1.0, 0.0], "rows": 3, "sec": 30, "updatedAt": 1, "learnedFrom": [{"doc": "d1", "at": 1}]},
            "宝鐘マリン": {"vec": [0.0, 1.0], "rows": 3, "sec": 30, "updatedAt": 1},       # 名簿は「宝鐘 マリン」= 空白の違いは同じ人
            "友達のA": {"vec": [0.5, 0.5], "rows": 3, "sec": 30, "updatedAt": 1}}})        # 名簿に無い人
        self.rules = learn_export()

    def build(self, now=1_800_000_000, **kw):
        return learnpack.build(self.root, data_dir=self.data, roster_path=self.roster, members_path=self.members, rules=self.rules, now=now, **kw)


def learn_export():
    with mock.patch.object(learn, "learn_rules", return_value=RULES), mock.patch.object(learn, "load_feedback", return_value=FB):
        return learn.export_rules()


class TestBuild(Base):
    def test_creates_pack(self):
        r = self.build()
        self.assertTrue(r["created"])
        self.assertRegex(r["version"], r"^\d{8}-\d{6}-[0-9a-f]{8}$")
        pack = rd(os.path.join(r["dir"], "learning.json"))
        self.assertEqual(pack["version"], r["version"])
        self.assertEqual(sorted(f["path"] for f in pack["files"]),
                         ["hololive-roster.json", "learn-feedback.json", "learned-rules.json", "members.json", "settings.json", "voices/voxceleb.json"])
        latest = rd(os.path.join(self.root, "latest.json"))
        self.assertEqual((latest["version"], latest["dir"]), (r["version"], r["version"]))
        settings = rd(os.path.join(r["dir"], "settings.json"))
        self.assertEqual(settings, {"glossary": "ぺこら"})   # 他の項目(モデル・評価用フォルダ)と、今はオフの人の置換辞書(dictfmt.USER_DICT)は入れない

    def test_voices_only_roster_people(self):
        r = self.build()
        v = rd(os.path.join(r["dir"], "voices", "voxceleb.json"))["voices"]
        self.assertEqual(sorted(v), ["兎田ぺこら", "宝鐘マリン"])
        self.assertEqual(v["兎田ぺこら"]["learnedFrom"][0]["doc"], "d1")       # どの文書から覚えたかは残る
        self.assertNotIn("友達のA", json.dumps(v, ensure_ascii=False))

    def test_no_roster_means_no_voices(self):
        os.remove(self.roster)
        r = self.build()
        self.assertFalse(os.path.exists(os.path.join(r["dir"], "voices")))

    def test_unchanged_is_not_rebuilt(self):
        a = self.build()
        b = self.build(now=1_800_000_500)
        self.assertEqual((b["created"], b["version"]), (False, a["version"]))
        self.assertEqual(len(learnpack.versions(self.root)), 1)

    def test_changed_makes_new_version_and_keeps_three(self):
        seen = [self.build()["version"]]
        for i in range(4):
            jwrite(os.path.join(self.data, "settings.json"), {"glossary": "語%d" % i})
            r = self.build(now=1_800_000_000 + 100 * (i + 1))
            self.assertTrue(r["created"])
            seen.append(r["version"])
        self.assertEqual(learnpack.versions(self.root), sorted(seen[-3:], reverse=True))   # 直近 3 版だけ
        self.assertEqual(rd(os.path.join(self.root, "latest.json"))["version"], seen[-1])
        self.assertFalse([n for n in os.listdir(self.root) if n.endswith(".tmp")])

    def test_leftover_tmp_is_cleaned(self):
        os.makedirs(os.path.join(self.root, "20200101-000000-deadbeef.tmp"))
        self.build()
        self.assertFalse([n for n in os.listdir(self.root) if n.endswith(".tmp")])


class TestExportRules(unittest.TestCase):
    def test_high_rules_and_glossary(self):
        ex = learn_export()
        self.assertEqual([(h["wrong"], h["right"]) for h in ex["high"]], [("あれ", "これ"), ("ぺこ", "ぺこら"), ("ぺこらん", "ぺこらさん")])
        self.assertNotIn("これ", ex["glossary"])                       # 文脈つき(ctx)は用語に入れない
        self.assertEqual(ex["dictLearned"], learn.dict_learned_text(RULES, FB))

    def test_same_selection_as_learn(self):
        ex = learn_export()
        find = replace.fixed_finder([(h["wrong"], h["right"]) for h in ex["high"]])
        for text in ("ぺこらんが来た", "ぺこがぺこ", "あれとトルときも", "むむ", "何もない", "ぺこらそしてぺこ"):
            want = [{"i": s["i"], "wrong": s["wrong"], "right": s["right"]} for s in learn.find_suggestions(text, RULES, FB, only_high=True)]
            self.assertEqual(find(text), want, text)
            self.assertEqual(replace.auto_learned_replace(text, find), replace.auto_learned_replace(text, lambda t: want))

    def test_same_glossary_as_learn(self):
        ex = learn_export()
        with mock.patch.object(learn, "learn_rules", return_value=RULES):
            for terms in ([], ["ぺこら"], ["ア" * 140]):
                self.assertEqual(replace.pick_glossary(terms, ex["glossary"]), learn.auto_glossary(terms), terms)

    def test_dict_learned_is_shared_with_doc_jobs(self):
        with mock.patch.object(learn, "learn_rules", return_value=RULES), mock.patch.object(learn, "load_feedback", return_value=FB):
            self.assertEqual(doc_jobs.dict_learned(), learn.dict_learned_text())

    def test_fixed_finder_empty_is_none(self):
        self.assertIsNone(replace.fixed_finder([]))


if __name__ == "__main__":
    unittest.main()
