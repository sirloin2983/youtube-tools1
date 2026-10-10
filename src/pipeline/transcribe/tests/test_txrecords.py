# -*- coding: utf-8 -*-
"""pipeline/transcribe/records(認識の記録・辞書の版・生出力・単語の時刻。役割で組み直す RS2-5)を、編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_txrecords.py -v

細かい決まり(記録の項目・辞書の版の中身)は編集のテスト(src/editor/tests/test_records.py・test_whispercpp.py。serve の名前で読む)が確かめる。
ここは「① が serve なしで読めて、置き場所と辞書の材料を持ち主(ytt/workdata・roster.ROSTER)・口(set_dict_inputs)か引数から読む」ことだけ。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import records, roster as roster_mod  # noqa: E402
from ytt import txwords, workdata  # noqa: E402


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="txrecords_")
        self.saved = dict(records._dict_inputs)
        roster = os.path.join(self.tmp, "roster.json")
        with open(roster, "w", encoding="utf-8") as f:
            f.write("{}")
        for mod, name, value in ((workdata, "TX_DIR", self.tmp), (roster_mod, "ROSTER", roster), (workdata, "SERVER_VERSION", "9.9.9")):
            p = mock.patch.object(mod, name, value)   # 試験の間だけ(終わったら元に戻す)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        records._dict_inputs.clear()
        records._dict_inputs.update(self.saved)
        shutil.rmtree(self.tmp, True)


class TestDictVersion(_Env):
    def test_arguments_and_inputs(self):
        spec = {"glossary": ["兎田ぺこら"], "autoDict": True, "autoLearned": True}
        a = records.dict_version(spec, [("ぺこら", "ペコラ")], "learned-1")
        self.assertEqual(set(a), {"glossary", "replacements", "learned", "roster"})
        self.assertEqual(a["replacements"], records.short_hash("ぺこら=>ペコラ"))
        self.assertEqual(a["learned"], records.short_hash("learned-1"))
        records.set_dict_inputs(pairs=lambda s: [("ぺこら", "ペコラ")], learned=lambda: "learned-1")   # 渡さなければ登録した口から
        self.assertEqual(records.dict_version(spec), a)

    def test_unregistered_inputs_are_an_error(self):
        records._dict_inputs.clear()
        with self.assertRaises(RuntimeError):
            records.dict_version({"autoDict": True})
        self.assertEqual(set(records.dict_version({"glossary": ["x"]})), {"glossary", "roster"})   # 材料の要らない版は作れる

    def test_run_base_reads_patched_dict_version(self):
        with mock.patch.object(records, "dict_version", lambda s: {"x": 1}):
            run = records.recognition_run({"model": "small", "language": "ja"}, {"device": "cpu"}, 1.0, 2.0)
        self.assertEqual((run["settings"]["dict"], run["device"], run["post"]["version"]), ({"x": 1}, "cpu", "9.9.9"))


class TestFiles(_Env):
    def test_words_and_asr_in_tx_dir(self):
        txwords.write_words("abc", [[1.0, 1.5, "い"], [0.0, 0.5, "あ"]], "small")
        self.assertEqual(txwords.words_path("abc"), os.path.join(self.tmp, "abc.words.json"))
        self.assertEqual(txwords.read_words("abc"), [[0.0, 0.5, "あ"], [1.0, 1.5, "い"]])
        raw = []
        rows = list(records.capture_raw(iter([{"start": 0.0, "end": 1.0, "text": "あ", "words": [(0.0, 1.0, "あ")], "wordProbs": [0.9]}]), raw, 10.0))
        self.assertEqual((len(rows), raw[0]["words"]), (1, [[10.0, 11.0, "あ", 0.9]]))
        records.write_asr("abc", raw, {"engine": "x"})
        with open(records.asr_path("abc"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["segments"], raw)
        txwords.write_words("abc", [])
        self.assertIsNone(txwords.read_words("abc"))


if __name__ == "__main__":
    unittest.main()
