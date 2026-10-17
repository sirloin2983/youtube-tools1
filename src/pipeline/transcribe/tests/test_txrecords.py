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


TID = "abc123abc123"   # 文書の id の形(12 文字の 16 進)


class TestFiles(_Env):
    def test_words_and_asr_in_tx_dir(self):
        txwords.write_words(TID, [[1.0, 1.5, "い"], [0.0, 0.5, "あ"]], "small")
        self.assertEqual(txwords.words_path(TID), os.path.join(self.tmp, TID + ".words.json"))
        self.assertEqual(txwords.read_words(TID), [[0.0, 0.5, "あ"], [1.0, 1.5, "い"]])
        raw = []
        rows = list(records.capture_raw(iter([{"start": 0.0, "end": 1.0, "text": "あ", "words": [(0.0, 1.0, "あ")], "wordProbs": [0.9]}]), raw, 10.0))
        self.assertEqual((len(rows), raw[0]["words"]), (1, [[10.0, 11.0, "あ", 0.9]]))
        records.write_asr(TID, raw, {"engine": "x"})
        with open(records.asr_path(TID), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["segments"], raw)
        txwords.write_words(TID, [])
        self.assertIsNone(txwords.read_words(TID))


    def test_indexed_doc_files_follow_the_index(self):
        """索引(docloc.place)を置いた文書の 単語の時刻・生出力は 作業用 のフォルダから読み書きされる"""
        from ytt import docloc
        work = os.path.join(self.tmp, "案件", "作業用")
        os.makedirs(work)
        with open(os.path.join(work, TID + ".json"), "w", encoding="utf-8") as f:
            f.write("{}")
        docloc.place(TID, work)
        txwords.write_words(TID, [[0.0, 0.5, "あ"]], "small")
        records.write_asr(TID, [], {"engine": "x"})
        self.assertEqual(txwords.words_path(TID), os.path.join(os.path.normpath(work), TID + ".words.json"))
        self.assertTrue(os.path.isfile(os.path.join(work, TID + ".words.json")))
        self.assertTrue(os.path.isfile(os.path.join(work, TID + ".asr.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, TID + ".words.json")))
        self.assertEqual(txwords.read_words(TID), [[0.0, 0.5, "あ"]])


class ScanGpuTest(unittest.TestCase):
    """whisper.cpp の標準エラーの装置の行の読み取り(友人の PC の遅さを調べる記録用。見本の文字列だけ)"""

    def test_vulkan_and_cuda_samples(self):
        from pipeline.transcribe import tx_engines as te
        vk = ["ggml_vulkan: Found 1 Vulkan devices:", "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | uma: 0 | fp16: 1 | warp size: 32",
              "whisper_backend_init_gpu: using Vulkan0 backend"]
        self.assertEqual(te.WhisperCpp.scan_gpu(vk), ("Vulkan0", "NVIDIA GeForce RTX 3060"))
        cu = ["ggml_cuda_init: found 1 CUDA devices:", "  Device 0: NVIDIA GeForce RTX 3060, compute capability 8.6, VMM: yes",
              "whisper_backend_init_gpu: using CUDA0 backend"]
        self.assertEqual(te.WhisperCpp.scan_gpu(cu), ("CUDA0", "NVIDIA GeForce RTX 3060"))
        self.assertEqual(te.WhisperCpp.scan_gpu(["whisper_backend_init_gpu: no GPU found"]), ("", ""))   # CPU に落ちた
        self.assertEqual(te.WhisperCpp.scan_gpu(["progress = 5%"]), (None, ""))   # 装置の行なし

    def test_recognition_run_keeps_gpu_only_when_known(self):
        with mock.patch.object(records, "dict_version", lambda s: {}):
            a = records.recognition_run({"model": "small", "language": "ja"}, {"device": "vulkan", "gpu": "RTX 3060", "backend": "Vulkan0"}, 1.0, 2.0)
            b = records.recognition_run({"model": "small", "language": "ja"}, {"device": "cpu"}, 1.0, 2.0)
        self.assertEqual((a["gpu"], a["backend"]), ("RTX 3060", "Vulkan0"))
        self.assertNotIn("gpu", b)   # 無いときは書かない(記録の形を変えない)


if __name__ == "__main__":
    unittest.main()
