# -*- coding: utf-8 -*-
"""pipeline/transcribe/worker_client(認識ワーカーとのやり取り・モデル・wav を読まずに渡す形。役割で組み直す RS2-6)を、編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_worker_client.py -v

ワーカーの起動・取り消し・落ちたときの立ち直りは編集のテスト(src/editor/tests/test_worker.py。serve の名前で読む・本物の経路)が確かめる。
ここは「① が serve なしで読めて、ワーカーの本体と記録のパスを差し替えか txenv から読む・サーバーのプロセスでは wav を読まない」ことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import shutil
import sys
import tempfile
import unittest
import wave
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import txenv, worker_client as W  # noqa: E402
from ytt import errors  # noqa: E402


class TestPaths(unittest.TestCase):
    def setUp(self):
        self.saved = dict(txenv._providers)
        txenv.register(ROOT=lambda: "/tool", DATA_DIR=lambda: "/data")

    def tearDown(self):
        txenv._providers.clear()
        txenv._providers.update(self.saved)

    def test_script_and_log_fall_back_to_txenv(self):
        with mock.patch.object(W, "WORKER_SCRIPT", None), mock.patch.object(W, "WORKER_LOG", None):
            self.assertEqual(W.worker_script(), os.path.join("/tool", "tx_worker.py"))
            self.assertEqual(W.worker_log(), os.path.join("/data", "worker.log"))
        with mock.patch.object(W, "WORKER_SCRIPT", "/x/w.py"), mock.patch.object(W, "WORKER_LOG", "/x/w.log"):   # 入れた値(app・テスト)が先
            self.assertEqual((W.worker_script(), W.worker_log()), ("/x/w.py", "/x/w.log"))


class TestWav(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="txworker_")

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def _wav(self, rate=16000, n=16000):
        p = os.path.join(self.tmp, "a%d.wav" % rate)
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"\0\0" * n)
        return p

    def test_server_process_does_not_read_samples(self):
        p = self._wav()
        with mock.patch.object(W, "IN_WORKER", False):
            ref = W.read_wav_f32(p)
        self.assertIsInstance(ref, W.WavRef)
        self.assertEqual(len(ref), 16000)
        part = ref[1600:3200]
        self.assertIsInstance(part, W.WavSlice)
        self.assertEqual((part.path, part.a, part.b, len(part)), (p, 1600, 3200, 1600))
        with self.assertRaises(errors.ApiError):
            W.WavRef(self._wav(rate=8000))


class TestKwargs(unittest.TestCase):
    def test_cuda_compute_and_filter(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "int8_float16"}):
            self.assertEqual(W.cuda_compute(), "int8_float16")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "bogus"}):
            self.assertEqual(W.cuda_compute(), "float16")
        kw = W.whisper_kwargs({"language": "ja", "beam": 5, "model": "small", "vadMode": "off", "wordSplit": True})
        self.assertEqual((kw["vad_filter"], kw["word_timestamps"], kw["language"]), (False, True, "ja"))

        class M:
            params = ("language", "beam_size")
        self.assertEqual(W.filter_kwargs(M(), kw), {"language": "ja", "beam_size": 5})


if __name__ == "__main__":
    unittest.main()
