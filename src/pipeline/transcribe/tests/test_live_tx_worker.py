# -*- coding: utf-8 -*-
"""配信中の候補の文字起こしの子プロセス src/pipeline/transcribe/live_tx_worker.py のテスト(D-11 案 b)。本物の認識はしない。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_live_tx_worker.py

確かめること:
  - 引数の数が違えば 2・知らないモデル・whisper-cli が無ければ ok false の json
  - 偽の whisper-cli(編集の tests/fake_whisper_cli.py)で text・rows・gpu・whisper-cli の引数(-l ja・-bs 5・-mc 0・-nfa)。GPU が無ければ ok false
入口 flow 側(live_tx の _run_worker が子プロセスを起動して結果を読む)は src/flow/tests/test_live_tx.py。
作業データはテストの一時フォルダだけ(YTT_DATA_DIR=inplace)。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(os.path.dirname(TESTS)))   # tests -> transcribe -> pipeline -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from pipeline.transcribe import live_tx_worker as TW  # noqa: E402

WORKER = os.path.abspath(TW.__file__)
FAKE_WCPP = os.path.join(SRC, "editor", "tests", "fake_whisper_cli.py")


def tx_engines():
    """編集の認識エンジンの口(値を比べるため・偽の whisper-cli で子プロセスの道を通すため。テストのプロセスだけで読む)"""
    from pipeline.transcribe import tx_engines as te
    return te


def write_wav(path, sec, rate=16000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * sec))


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class WorkerTest(unittest.TestCase):
    """live_tx_worker.py(子プロセス)。本物の認識はしない"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-livetx-w-")
        self.wav = os.path.join(self.tmp, "in.wav")
        write_wav(self.wav, 10.0)
        self.data = os.path.join(self.tmp, "editor")
        self.out = os.path.join(self.tmp, "out.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args):
        p = subprocess.run([sys.executable, WORKER] + list(args), stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        return p.returncode, p.stderr.decode("utf-8", "replace")

    def result(self):
        with open(self.out, encoding="utf-8") as f:
            return json.load(f)

    def test_command_line(self):
        code, err = self.cli(self.data, "large-v3", self.wav)
        self.assertEqual(code, 2)
        self.assertIn("usage: live_tx_worker.py", err)
        self.assertEqual(self.cli(self.data, "small", self.wav, self.out)[0], 1)
        self.assertEqual(self.result(), {"ok": False, "reason": "whisper.cpp で使えないモデルです: small"})
        self.assertEqual(self.cli(self.data, "large-v3", self.wav, self.out)[0], 1)
        r = self.result()
        self.assertEqual(r["ok"], False)
        self.assertTrue(r["reason"].startswith("whisper.cpp かモデルがありません"), r)
        touch(os.path.join(self.data, "bin", "whisper.cpp-%s-vulkan" % tx_engines().WHISPER_CPP["version"], tx_engines().WCPP_EXE))   # 実行ファイルだけ(モデルが無い)
        self.assertEqual(self.cli(self.data, "large-v3", self.wav, self.out)[0], 1)
        self.assertIn("ggml-large-v3.bin", self.result()["reason"])
        self.assertFalse(os.path.exists(self.out + ".part"))

    def test_recognize_with_fake_whisper_cli(self):
        """編集の WhisperCpp(本物の引数の作り方・-ojf の読み方・GPU の確かめ)を、偽の whisper-cli(編集の tests/fake_whisper_cli.py)で通す"""
        te = tx_engines()
        touch(os.path.join(te.wcpp_bin_dir(self.data), te.WCPP_EXE))
        touch(os.path.join(te.wcpp_model_dir(self.data), te.WCPP_MODELS["large-v3"]["file"]))
        real = te.WhisperCpp

        class Fake(real):
            def __init__(self, name, device, model):
                super().__init__(name, device, dict(model, cmd=[sys.executable, FAKE_WCPP]))
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))   # recognize() が sys.path に編集のフォルダを足すので戻す
        argf = os.path.join(self.tmp, "wcpp-args.json")
        with mock.patch.object(te, "WhisperCpp", Fake), mock.patch.dict(os.environ, {"FAKE_WCPP_ARGS": argf}):
            r = TW.recognize(self.data, "large-v3", self.wav)
        self.assertEqual({k: r[k] for k in ("ok", "text", "gpu", "model", "engine")},
                         {"ok": True, "text": "テスト文1テスト文2テスト文3", "gpu": "AMD Radeon RX 7800 XT", "model": "large-v3", "engine": "whisper.cpp"})
        self.assertEqual(r["rows"], [{"start": 0.0, "end": 4.0, "text": "テスト文1"}, {"start": 4.0, "end": 8.0, "text": "テスト文2"},
                                     {"start": 8.0, "end": 10.0, "text": "テスト文3"}])
        self.assertIsInstance(r["sec"], float)
        with open(argf, encoding="utf-8") as f:
            a = json.load(f)
        self.assertEqual([a[a.index(k) + 1] for k in ("-l", "-bs", "-mc")], ["ja", "5", "0"])
        self.assertIn("-nfa", a)
        self.assertNotIn("-ng", a)   # GPU(vulkan)
        self.assertNotIn("--vad", a)
        self.assertEqual(a[a.index("-m") + 1], os.path.join(te.wcpp_model_dir(self.data), "ggml-large-v3.bin"))
        with mock.patch.object(te, "WhisperCpp", Fake), mock.patch.dict(os.environ, {"FAKE_WCPP_GPU": "none"}):   # GPU が無い: 黙って CPU にしない
            self.assertEqual(TW.main(["live_tx_worker.py", self.data, "large-v3", self.wav, self.out]), 1)
        r = self.result()
        self.assertEqual(r["ok"], False)
        self.assertTrue(r["reason"].startswith("EngineError: GPU(Vulkan)を使えませんでした"), r)


if __name__ == "__main__":
    unittest.main()
