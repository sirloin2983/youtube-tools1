# -*- coding: utf-8 -*-
"""pipeline/transcribe/worker_client(認識ワーカーとのやり取り・モデル・wav を読まずに渡す形。役割で組み直す RS2-6)を、編集の serve を読まずに使うテスト。

    py -3.12 -m unittest src/pipeline/transcribe/tests/test_worker_client.py -v

本物のワーカーの通し・取り消し・落ちたときの立ち直りは編集のテスト(src/editor/tests/test_worker.py。serve の名前で読む)が確かめる。
ここは「① が serve なしで読めて、ワーカーの本体と記録のパスを差し替えか ytt/workdata から読む・サーバーのプロセスでは wav を読まない」ことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import sys
import unittest
import wave
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from pipeline.transcribe import models, worker_client as W  # noqa: E402
from ytt import workdata  # noqa: E402
from ytt import errors  # noqa: E402


class TestPaths(unittest.TestCase):
    def setUp(self):
        for name, value in (("ROOT", "/tool"), ("DATA_DIR", "/data")):
            self.enterContext(mock.patch.object(workdata, name, value))   # 試験の間だけ(終わったら元に戻す)

    def test_script_and_log_fall_back_to_workdata(self):
        with mock.patch.object(W, "WORKER_SCRIPT", None), mock.patch.object(W, "WORKER_LOG", None):
            here = os.path.dirname(os.path.abspath(W.__file__))
            self.assertEqual(W.worker_script(), os.path.join(here, "worker.py"))   # 本体はこのフォルダの worker.py
            self.assertTrue(os.path.isfile(W.worker_script()))
            self.assertEqual(W.worker_log(), os.path.join("/data", "worker.log"))
        with mock.patch.object(W, "WORKER_SCRIPT", "/x/w.py"), mock.patch.object(W, "WORKER_LOG", "/x/w.log"):   # 入れた値(app・テスト)が先
            self.assertEqual((W.worker_script(), W.worker_log()), ("/x/w.py", "/x/w.log"))

    def test_worker_env(self):
        """作業データの場所は必ず渡す。疑似の部品の名前は worker-fake のときだけ(サーバーの環境変数に残っていても本物には渡さない)・
        worker-fake なのに名前が登録されていなければ RuntimeError(RS2-9)"""
        fake = [False]
        self.enterContext(mock.patch.object(W, "worker_fake", lambda: fake[0]))   # この試験の終わりまで(下の FAKES_MODULE なしの確かめも worker-fake のまま)
        with mock.patch.dict(os.environ, {W.FAKES_ENV: "x.y"}), mock.patch.object(W, "FAKES_MODULE", "eval.fake.fake_worker"):
            env = W.worker_env()
            self.assertEqual(env["TRANSCRIBE_DATA_DIR"], "/data")
            self.assertNotIn(W.FAKES_ENV, env)
            fake[0] = True
            self.assertEqual(W.worker_env()[W.FAKES_ENV], "eval.fake.fake_worker")
        with mock.patch.object(W, "FAKES_MODULE", None), self.assertRaises(RuntimeError):
            W.worker_env()


class TestWorkerModule(unittest.TestCase):
    """認識ワーカーの本体 worker.py を serve なしで読む(本物の要求の道は src/editor/tests/test_worker.py の RealWorkerTest)"""

    def test_handle_errors_and_cancel(self):
        """知らない要求は bad_op・知らないエンジンは ApiError・読み込み中の取り消しは cancelled"""
        from pipeline.transcribe import worker
        from ytt import jobs
        sent = []

        class Out:
            def send(self, obj):
                sent.append(obj)
        worker.handle({"rid": 8, "op": "nope"}, Out(), set())
        worker.handle({"rid": 1, "op": "load", "name": "small", "engine": "no-such"}, Out(), set())
        with mock.patch.object(models, "_load_model_local", mock.Mock(side_effect=jobs.Cancelled())):
            worker.handle({"rid": 2, "op": "load", "name": "small"}, Out(), {2})
        self.assertEqual((sent[0]["rid"], sent[0]["ev"], sent[0]["code"]), (8, "error", "bad_op"))
        self.assertEqual((sent[1]["code"], sent[1]["status"]), ("bad_engine", 400))
        self.assertEqual((sent[2]["rid"], sent[2]["code"]), (2, "cancelled"))


class TestWav(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, prefix="txworker_")

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
            self.assertEqual(models.cuda_compute(), "int8_float16")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "rm -rf"}):
            self.assertEqual(models.cuda_compute(), "float16")
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("TRANSCRIBE_CUDA_COMPUTE", None)
            self.assertEqual(models.cuda_compute(), "float16")   # 無ければ既定
        kw = W.whisper_kwargs({"language": "ja", "beam": 5, "model": "small", "vadMode": "off", "wordSplit": True})
        self.assertEqual((kw["vad_filter"], kw["word_timestamps"], kw["language"]), (False, True, "ja"))

        class M:
            params = ("language", "beam_size")
        self.assertEqual(W.filter_kwargs(M(), kw), {"language": "ja", "beam_size": 5})

    def test_prompt_hotwords_and_context_record(self):
        """用語集 + 配信ごとの文脈 → initial_prompt・hotwords。文書に残す文脈の記録は records.context_record"""
        from pipeline.transcribe import records
        spec = {"language": "ja", "beam": 5, "vadMode": "normal", "model": "large-v3", "glossary": ["ホロライブ"],
                "context": {"members": [{"name": "兎田ぺこら", "from": ["channel"]}], "terms": ["兎田ぺこら", "ぺこら"]}}
        kw = W.whisper_kwargs(spec)
        self.assertEqual(kw["initial_prompt"], "用語: ホロライブ、兎田ぺこら、ぺこら")   # 用語集が先・文脈が後
        self.assertEqual(kw["hotwords"], "ホロライブ, 兎田ぺこら, ぺこら")
        self.assertNotIn("temperature", kw)
        self.assertEqual(W.whisper_kwargs(dict(spec, temp0=True))["temperature"], 0.0)
        long = dict(spec, glossary=["語%03d" % i for i in range(60)])
        p = W.whisper_kwargs(long)["initial_prompt"]
        self.assertLessEqual(len(p) - len("用語: "), 150)
        self.assertTrue(p.endswith(tuple("語%03d" % i for i in range(60))))                # 語の途中で切らない
        self.assertNotIn("initial_prompt", W.whisper_kwargs(dict(spec, glossary=[], context={})))
        self.assertEqual(records.context_record(spec), {"members": [{"name": "兎田ぺこら", "from": ["channel"]}], "terms": 2})
        self.assertIsNone(records.context_record({"context": {"members": []}}))


if __name__ == "__main__":
    unittest.main()
