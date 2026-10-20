# -*- coding: utf-8 -*-
"""配信中の候補の文字起こしの子プロセス src/pipeline/transcribe/live_tx_worker.py のテスト(D-11 案 b)。本物の認識はしない。

    py -3.12 -m unittest tests/pipeline/transcribe/test_live_tx_worker.py

確かめること(本物では起こせない物だけ):
  - 引数の数が違えば 2・知らないモデル・whisper-cli が無ければ ok false の json
  - GPU が無ければ ok false(偽の whisper-cli = 編集の tests/fake_whisper_cli.py)
本物の whisper.cpp で text・rows・gpu・whisper-cli の引数を見る通しと、入口 flow 側(live_tx の _run_worker)は tests/flow/test_live_tx.py。
作業データはテストの一時フォルダだけ(YTT_DATA_DIR=inplace)。
"""
import json
import os
import subprocess
import sys
import unittest
import wave
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS))), "src")   # tests -> transcribe -> pipeline -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402
from pipeline.transcribe import live_tx_worker as TW  # noqa: E402

WORKER = os.path.abspath(TW.__file__)
FAKE_WCPP = os.path.join(os.path.dirname(SRC), "tests", "pipeline", "transcribe", "fake_whisper_cli.py")


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
        self.tmp = testkit.tempdir(self, prefix="ytt-livetx-w-")
        self.wav = os.path.join(self.tmp, "in.wav")
        write_wav(self.wav, 10.0)
        self.data = os.path.join(self.tmp, "editor")
        self.out = os.path.join(self.tmp, "out.json")

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

    def test_gpu_missing_is_a_failure(self):
        """GPU が無い(この PC では起こせない): 黙って CPU にせず ok false。偽の whisper-cli(編集の tests/fake_whisper_cli.py)で通す。
        正しく動く道(引数・行・GPU の名前)は本物の whisper.cpp の通し tests/flow/test_live_tx.py の RealWhisperTest"""
        te = tx_engines()
        touch(os.path.join(te.wcpp_bin_dir(self.data), te.WCPP_EXE))
        touch(os.path.join(te.wcpp_model_dir(self.data), te.WCPP_MODELS["large-v3"]["file"]))
        real = te.WhisperCpp

        class Fake(real):
            def __init__(self, name, device, model):
                super().__init__(name, device, dict(model, cmd=[sys.executable, FAKE_WCPP]))
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))   # recognize() が sys.path に編集のフォルダを足すので戻す
        with mock.patch.object(te, "WhisperCpp", Fake), mock.patch.dict(os.environ, {"FAKE_WCPP_GPU": "none"}):
            self.assertEqual(TW.main(["live_tx_worker.py", self.data, "large-v3", self.wav, self.out]), 1)
        r = self.result()
        self.assertEqual(r["ok"], False)
        self.assertTrue(r["reason"].startswith("EngineError: GPU(Vulkan)を使えませんでした"), r)


if __name__ == "__main__":
    unittest.main()
