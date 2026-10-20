# -*- coding: utf-8 -*-
"""flow/learning(学習データを読む側。F1)のテスト。  py -3.12 -m unittest tests/flow/test_learning.py -v

- 学習の束(learning.json がある learningDir)は、文書も ③ も読まずに計算済みの規則で用語・置換・辞書の版を返す(= 友人の PC は文書なしで動く)
- 束がなければ今のまま(文書が無い・③ の読み込みを渡されなければ「学習なし」)
- learning_dir は束ならそのフォルダ・apply_places が置換辞書・採用の記録・名簿・声・色の場所を入れる
- stamp が束の post.learning.version に版を入れ、後処理の鍵(keys.post_inputs)に載る
作業データは一時フォルダ
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import json
import sys
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import diar, keys, learning, spec  # noqa: E402
from manage.keep import learnpack  # noqa: E402  (束を作る側。テストの材料)
from pipeline.transcribe import roster  # noqa: E402
from ytt import colors, workdata  # noqa: E402

RULES = {"schema": "ytt-learned-rules/v1",
         "high": [{"wrong": "ぺこ", "right": "ぺこら", "pos": 4, "docs": 2}, {"wrong": "ぺこらん", "right": "ぺこらさん", "pos": 3, "docs": 2}],
         "glossary": ["ぺこら", "マリン"], "dictLearned": '{"rules": [["ぺこ", "ぺこら", 4, 2]]}'}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-learning-")
        data = os.path.join(self.tmp, "data", "transcribe")
        testkit.write_json(os.path.join(data, "settings.json"), {"replacements": "a=>b"})
        rp = os.path.join(self.tmp, "roster.json")
        testkit.write_json(rp, {"groups": [{"id": "g", "label": "G", "names": ["兎田ぺこら"]}]})
        testkit.write_json(os.path.join(data, "voices", "voxceleb.json"), {"voices": {"兎田ぺこら": {"vec": [1.0, 0.0], "rows": 1, "sec": 10, "updatedAt": 1},
                                                                         "ほか": {"vec": [0.0, 1.0], "rows": 1, "sec": 10, "updatedAt": 1}}})
        mp = os.path.join(self.tmp, "members.json")
        testkit.write_json(mp, [])
        r = learnpack.build(os.path.join(self.tmp, "学習"), data_dir=data, roster_path=rp, members_path=mp, rules=RULES)
        self.pack = r["dir"]
        self.version = r["version"]
        keep = (workdata.SETTINGS, workdata.FEEDBACK, roster.ROSTER, diar.VOICES_DIR)
        self.addCleanup(self._restore, keep)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(colors.MEMBERS_ENV, None)

    @staticmethod
    def _restore(keep):
        workdata.SETTINGS, workdata.FEEDBACK, roster.ROSTER, diar.VOICES_DIR = keep


class TestPackReader(Base):
    def loader_must_not_run(self):
        raise AssertionError("束のときは ③ を読まない")

    def test_reads_rules_without_human(self):
        lr = learning.Learning(self.pack, human_loader=self.loader_must_not_run)
        self.assertEqual(lr.version, self.version)
        self.assertEqual(lr.glossary(["ぺこら"]), ["マリン"])
        self.assertEqual(lr.glossary([]), ["ぺこら", "マリン"])
        self.assertEqual(lr.dict_learned(), RULES["dictLearned"])
        find = lr.learned()
        self.assertEqual([(s["i"], s["wrong"], s["right"]) for s in find("ぺこらんとぺこ")], [(0, "ぺこらん", "ぺこらさん"), (5, "ぺこ", "ぺこら")])

    def test_broken_rules_means_no_learning(self):
        testkit.write_text(os.path.join(self.pack, "learned-rules.json"), "{not json")
        lr = learning.Learning(self.pack, human_loader=self.loader_must_not_run)
        self.assertEqual((lr.glossary([]), lr.dict_learned(), lr.learned()), ([], "", None))

    def test_without_pack_and_loader_is_empty(self):
        lr = learning.Learning(None)
        self.assertEqual((lr.glossary([]), lr.dict_learned(), lr.learned(), lr.version), ([], "", None, ""))

    def test_without_docs_loader_is_not_called(self):
        empty = os.path.join(self.tmp, "ld")
        os.makedirs(os.path.join(empty, "transcripts"))
        lr = learning.Learning(empty, human_loader=self.loader_must_not_run)   # 文書が 1 つも無い = 読み込みを呼ばない
        self.assertEqual((lr.glossary(["あ"]), lr.learned()), ([], None))


class TestPlaces(Base):
    def test_learning_dir_pack(self):
        with mock.patch.dict(os.environ, {"YTT_MACHINE_LEARNING_DIR": self.pack}):
            self.assertEqual(learning.learning_dir(), os.path.abspath(self.pack))

    def _data_root(self, folder):
        """一時の作業データの根(<根>/app/prefs.json の intake.folder = folder。None なら prefs.json を置かない)"""
        root = os.path.join(self.tmp, "root-%s" % (folder is None and "none" or len(folder)))
        os.makedirs(os.path.join(root, "app"), exist_ok=True)
        if folder is not None:
            testkit.write_json(os.path.join(root, "app", "prefs.json"), {"intake": {"enabled": True, "folder": folder}})
        return root

    def test_maker_pc_does_not_read_pack(self):
        """6d-1: 作る側の PC(受付のフォルダの設定がある)では、learningDir が束でも読まない = 理由の 1 行。CLI の learning_dir も同じ"""
        root = self._data_root(os.path.join(self.tmp, "受付"))
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": root, "YTT_MACHINE_LEARNING_DIR": self.pack}):
            self.assertTrue(learning.maker_pc())
            ld, why = learning.learning_dir_checked()
            self.assertIsNone(ld)
            self.assertIn("作る側", why)
            self.assertIn(self.pack, why)
            self.assertIsNone(learning.learning_dir())

    def test_friend_pc_reads_pack(self):
        """友人の PC(prefs.json が無い・受付のフォルダが空)では今まで通り束を読む"""
        for folder in (None, "", "  "):
            root = self._data_root(folder)
            with mock.patch.dict(os.environ, {"YTT_DATA_DIR": root, "YTT_MACHINE_LEARNING_DIR": self.pack}):
                self.assertFalse(learning.maker_pc(), folder)
                self.assertEqual(learning.learning_dir_checked(), (os.path.abspath(self.pack), ""))

    def test_maker_pc_keeps_default_and_legacy(self):
        """作る側でも束でない learningDir(既定・作業データの置き方)は今まで通り(守るのは束だけ)"""
        root = self._data_root(os.path.join(self.tmp, "受付"))
        legacy = os.path.join(self.tmp, "legacy-data")
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": root, "YTT_MACHINE_LEARNING_DIR": root}):
            self.assertEqual(learning.learning_dir_checked(), (None, ""))
        with mock.patch.dict(os.environ, {"YTT_DATA_DIR": root, "YTT_MACHINE_LEARNING_DIR": legacy}):
            self.assertEqual(learning.learning_dir_checked(), (os.path.join(legacy, "transcribe"), ""))

    def test_broken_prefs_is_not_maker(self):
        root = self._data_root(None)
        testkit.write_text(os.path.join(root, "app", "prefs.json"), "{broken")
        self.assertFalse(learning.maker_pc(env={"YTT_DATA_DIR": root}))
        testkit.write_json(os.path.join(root, "app", "prefs.json"), {"intake": "x"})
        self.assertFalse(learning.maker_pc(env={"YTT_DATA_DIR": root}))

    def test_is_pack_and_version(self):
        self.assertTrue(learning.is_pack(self.pack))
        self.assertFalse(learning.is_pack(os.path.join(self.tmp, "nothing")))
        self.assertEqual(learning.pack_version(self.pack), self.version)
        self.assertEqual(learning.pack_version(None), "")

    def test_apply_places_pack(self):
        learning.apply_places(self.pack)
        self.assertEqual(workdata.SETTINGS, os.path.join(self.pack, "settings.json"))
        self.assertEqual(workdata.FEEDBACK, os.path.join(self.pack, "learn-feedback.json"))
        self.assertEqual(roster.ROSTER, os.path.join(self.pack, "hololive-roster.json"))
        self.assertEqual(os.environ[colors.MEMBERS_ENV], os.path.join(self.pack, "members.json"))
        self.assertEqual(sorted(diar.load_voices("voxceleb")), ["兎田ぺこら"])   # 名簿にある人の声だけが友人の ② に届く

    def test_apply_places_legacy_and_none(self):
        keep = workdata.SETTINGS
        learning.apply_places(None)
        self.assertEqual(workdata.SETTINGS, keep)
        legacy = os.path.join(self.tmp, "legacy")
        learning.apply_places(legacy)
        self.assertEqual((workdata.SETTINGS, workdata.FEEDBACK), (os.path.join(legacy, "settings.json"), os.path.join(legacy, "learn-feedback.json")))
        self.assertNotIn(colors.MEMBERS_ENV, os.environ)


class TestStamp(Base):
    def test_version_goes_into_bundle_and_key(self):
        lr = learning.Learning(self.pack)
        b = spec.validate(spec.merge({}))
        self.assertEqual(b["post"]["learning"]["version"], "")
        s = learning.stamp(b, lr)
        self.assertEqual(s["post"]["learning"]["version"], self.version)
        self.assertEqual(spec.validate(s)["post"]["learning"]["version"], self.version)   # 検査も通る
        self.assertEqual(b["post"]["learning"]["version"], "")                           # 元は変えない
        self.assertEqual(keys.post_inputs("h", s["post"], "d", s["post"]["learning"]["version"])["learning"], self.version)

    def test_stamp_leaves_bundle_alone_without_pack_or_with_given_version(self):
        b = spec.validate(spec.merge({}))
        self.assertIs(learning.stamp(b, learning.Learning(None)), b)
        given = spec.validate(spec.merge({"post": {"learning": {"version": "mine"}}}))
        self.assertIs(learning.stamp(given, learning.Learning(self.pack)), given)


if __name__ == "__main__":
    unittest.main()
