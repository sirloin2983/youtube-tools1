# -*- coding: utf-8 -*-
"""pipeline/transcribe/worker_client(認識ワーカーとのやり取り・モデル・wav を読まずに渡す形。役割で組み直す RS2-6)を、編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_worker_client.py -v

ワーカーの起動・取り消し・落ちたときの立ち直りは編集のテスト(src/editor/tests/test_worker.py。serve の名前で読む・本物の経路)が確かめる。
ここは「① が serve なしで読めて、ワーカーの本体と記録のパスを差し替えか ytt/workdata から読む(RS3-0A まで txenv の口)・サーバーのプロセスでは wav を読まない」ことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import worker_client as W  # noqa: E402
from ytt import workdata  # noqa: E402
from ytt import errors  # noqa: E402


class TestPaths(unittest.TestCase):
    def setUp(self):
        for mod, name, value in ((workdata, "ROOT", "/tool"), (workdata, "DATA_DIR", "/data")):
            p = mock.patch.object(mod, name, value)   # 試験の間だけ(終わったら元に戻す)
            p.start()
            self.addCleanup(p.stop)

    def test_script_and_log_fall_back_to_workdata(self):
        with mock.patch.object(W, "WORKER_SCRIPT", None), mock.patch.object(W, "WORKER_LOG", None):
            here = os.path.dirname(os.path.abspath(W.__file__))
            self.assertEqual(W.worker_script(), os.path.join(here, "worker.py"))   # 本体はこのフォルダの worker.py(RS2-9。以前は編集の tx_worker.py)
            self.assertTrue(os.path.isfile(W.worker_script()))
            self.assertEqual(W.worker_log(), os.path.join("/data", "worker.log"))
        with mock.patch.object(W, "WORKER_SCRIPT", "/x/w.py"), mock.patch.object(W, "WORKER_LOG", "/x/w.log"):   # 入れた値(app・テスト)が先
            self.assertEqual((W.worker_script(), W.worker_log()), ("/x/w.py", "/x/w.log"))

    def test_worker_env(self):
        """作業データの場所は必ず渡す。疑似の部品の名前は worker-fake のときだけ(サーバーの環境変数に残っていても本物には渡さない)・
        worker-fake なのに名前が登録されていなければ RuntimeError(RS2-9)"""
        fake = [False]
        p = mock.patch.object(W, "worker_fake", lambda: fake[0])   # この試験の終わりまで(下の FAKES_MODULE なしの確かめも worker-fake のまま)
        p.start()
        self.addCleanup(p.stop)
        with mock.patch.dict(os.environ, {W.FAKES_ENV: "x.y"}), mock.patch.object(W, "FAKES_MODULE", "eval.fake.fake_worker"):
            env = W.worker_env()
            self.assertEqual(env["TRANSCRIBE_DATA_DIR"], "/data")
            self.assertNotIn(W.FAKES_ENV, env)
            fake[0] = True
            self.assertEqual(W.worker_env()[W.FAKES_ENV], "eval.fake.fake_worker")
        with mock.patch.object(W, "FAKES_MODULE", None), self.assertRaises(RuntimeError):
            W.worker_env()


class TestWorkerModule(unittest.TestCase):
    """認識ワーカーの本体 worker.py(RS2-9 に編集の tx_worker.py から移した)を serve なしで読む"""

    def test_import_reads_no_app_eval_or_native(self):
        """import しただけでは、編集の serve・ed_*・eval(疑似)・numpy などを読まない(疑似は worker-fake のときに main が名前で読む)"""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import pipeline.transcribe.worker as w; "
                "native = ('numpy', 'faster_whisper', 'ctranslate2', 'sherpa_onnx', 'onnxruntime'); "
                "print(sorted(m for m in sys.modules if m in native or m == 'serve' or m.startswith('ed_') or m == 'eval' or m.startswith('eval.')))")
        p = subprocess.run([sys.executable, "-c", code, SRC], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertEqual(p.stdout.strip(), "[]")

    def test_handle_routes_to_owner_modules(self):
        """要求は呼ぶたびに持ち主のモジュールの名前を読む(diarize._diarize_local の差し替えが届く)・知らない要求は bad_op"""
        from pipeline.transcribe import diarize, worker
        sent, got = [], []

        class Out:
            def send(self, obj):
                sent.append(obj)

        def fake(job, wav, num, emb, **kw):
            got.append((wav, num, emb, kw))
            return [(0.0, 1.5, 1)]
        with mock.patch.object(diarize, "_diarize_local", fake):
            worker.handle({"rid": 7, "op": "diarize", "wav": "a.wav", "num": 2, "minOn": 0.2}, Out(), set())
        worker.handle({"rid": 8, "op": "nope"}, Out(), set())
        self.assertEqual(got, [("a.wav", 2, diarize.DIAR_EMB_DEFAULT, {"min_on": 0.2})])
        self.assertEqual(sent[0], {"rid": 7, "ev": "result", "v": [[0.0, 1.5, 1]]})
        self.assertEqual((sent[1]["rid"], sent[1]["ev"], sent[1]["code"]), (8, "error", "bad_op"))

    def test_handle_api_error_and_cancel(self):
        from pipeline.transcribe import worker
        from ytt import jobs
        sent = []

        class Out:
            def send(self, obj):
                sent.append(obj)
        worker.handle({"rid": 1, "op": "load", "name": "small", "engine": "no-such"}, Out(), set())   # 知らないエンジンは ApiError
        with mock.patch.object(W, "_load_model_local", mock.Mock(side_effect=jobs.Cancelled())):
            worker.handle({"rid": 2, "op": "load", "name": "small"}, Out(), {2})
        self.assertEqual((sent[0]["code"], sent[0]["status"]), ("bad_engine", 400))
        self.assertEqual((sent[1]["rid"], sent[1]["code"]), (2, "cancelled"))


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
