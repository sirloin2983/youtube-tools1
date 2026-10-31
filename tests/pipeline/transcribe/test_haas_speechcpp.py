"""speech.cpp の Haas のエンジン(src/pipeline/transcribe/tx_engines.py の HaasSpeechCpp・SpeechWorker)の単体テスト: 登録・取得先の固定・
機器の順(黙って CPU にしない)・実行ファイルが無い時・区切りごとに words と確率つきの 1 行・用語のヒントを keywords へ・空の行を捨てる・
worker が終わったら 1 回だけ起こし直す(2 回目は上へ)・GPU を頼んだのに CPU で起きたら止める。偽の worker(fake_speech_worker.py)だけを使う(音・窓を出さない)。

実行(リポジトリ直下から): py -3.12 -m unittest tests/pipeline/transcribe/test_haas_speechcpp.py -v
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pipeline.transcribe import tx_engines as E  # noqa: E402
from ytt import txbase  # noqa: E402

FAKE = [sys.executable, os.path.join(HERE, "fake_speech_worker.py")]


def tone(sec, amp=0.3):
    """声のある音(区切りが無音で飛ばされない大きさ)。float の並び"""
    import math
    return [amp * math.sin(2 * math.pi * 220 * k / 16000) for k in range(int(sec * 16000))]


class HaasSpeechCppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-haas-sc-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.model = os.path.join(self.tmp, "m.gguf")
        open(self.model, "wb").close()
        for p in (mock.patch.object(E.HaasSpeechCpp, "COMMAND", FAKE), mock.patch.object(E, "fetch_file", return_value=self.model)):
            p.start()
            self.addCleanup(p.stop)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_SPEECH_")}
        self.log = os.path.join(self.tmp, "req.jsonl")

    def engine(self, device="vulkan", **env):
        with mock.patch.dict(os.environ, dict(self.env, FAKE_SPEECH_LOG=self.log, **env), clear=True):
            e = E.HaasSpeechCpp.create("haas-ja-v1.0", device, data_dir=self.tmp)
        self.addCleanup(e.close)
        return e

    def run_engine(self, e, x, **kw):
        gen, info = e.transcribe(x, language="ja", **kw)
        return list(gen), info

    def reqs(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(x) for x in f]

    def test_registered(self):
        self.assertTrue(E.valid("haas-speechcpp") and E.valid("haas"))   # sherpa の haas(声の材料)はそのまま
        c = E.HaasSpeechCpp
        self.assertTrue(c.valid_model("haas-ja-v1.0") and not c.valid_model("large-v3"))
        self.assertEqual((c.device_order("auto", True), c.device_order("vulkan", False), c.device_order("cpu", False)), (["vulkan"], ["vulkan"], ["cpu"]))
        self.assertEqual(E.caps_of("haas-speechcpp"), {"word_timestamps", "hotwords"})
        m = E.HAAS_GGUF_MODELS["haas-ja-v1.0"]
        self.assertTrue(m["url"].startswith("https://huggingface.co/sakasegawa/Haas-ja-v1.0-GGUF/resolve/") and len(m["sha256"]) == 64 and m["size"] > 6e8)
        self.assertEqual(c.version(), "%s-%s" % (txbase.SPEECH_CPP_VERSION, txbase.SPEECH_CPP_FLAVOR))
        self.assertTrue(txbase.speech_bin_dir("D").endswith(os.path.join("bin", "speech.cpp-0.10.0-conf")))

    def test_missing_exe_and_bad_model(self):
        with mock.patch.object(E.HaasSpeechCpp, "COMMAND", None):
            self.assertFalse(E.HaasSpeechCpp.ready(self.tmp))
            with self.assertRaises(E.EngineError) as cm:
                E.HaasSpeechCpp.create("haas-ja-v1.0", "vulkan", data_dir=self.tmp)
            self.assertEqual(cm.exception.code, "engine_missing")
        with self.assertRaises(E.EngineError) as cm:
            E.HaasSpeechCpp.create("large-v3", "vulkan", data_dir=self.tmp)
        self.assertEqual(cm.exception.code, "bad_model")

    def test_rows_words_probs_and_keywords(self):
        e = self.engine()
        self.assertEqual(e.gpu_name, "Vulkan0")
        segs, info = self.run_engine(e, tone(20) + [0.0] * 16000 * 2 + tone(15), hotwords="ルーナ, 姫森ルーナ")
        self.assertEqual(info.language, "ja")
        self.assertGreaterEqual(len(segs), 1)
        s = segs[0]
        self.assertTrue(s.text.startswith("あ") and s.text.endswith("ルーナ\n姫森ルーナ。".replace("\n", "")))
        self.assertEqual([w.word for w in s.words][:1], ["あ"])
        self.assertEqual(s.words[0].start, round(s.start, 3))
        self.assertAlmostEqual(s.words[0].probability, 0.9)
        self.assertLess(s.avg_logprob, 0)
        r = self.reqs()
        self.assertTrue(all(x["timestamps"] for x in r))
        self.assertEqual(r[0]["keywords"], "ルーナ\n姫森ルーナ")
        self.assertGreater(r[0]["bytes"], 16000 * 2 * 10)   # 10 秒より長い区切り = chunk を分けて送っても 1 つに届く

    def test_empty_rows_dropped(self):
        e = self.engine(FAKE_SPEECH_EMPTY="1")
        segs, _ = self.run_engine(e, tone(15))
        self.assertEqual(segs, [])

    def test_restart_once(self):
        mark = os.path.join(self.tmp, "died")
        e = self.engine(FAKE_SPEECH_DIE="1:" + mark)
        with mock.patch.dict(os.environ, dict(self.env, FAKE_SPEECH_DIE="1:" + mark), clear=True):
            segs, _ = self.run_engine(e, tone(15))
        self.assertEqual(e.restarts, 1)
        self.assertEqual(len(segs), 1)

    def test_second_failure_goes_up(self):
        e = self.engine()
        e.cmd = [sys.executable, "-c", "import sys; sys.exit(2)"]   # 起こし直しても起きない
        e.model.close()
        with self.assertRaises(E.EngineError) as cm:
            self.run_engine(e, tone(15))
        self.assertIn(cm.exception.code, ("worker_down", "engine_failed"))

    def test_gpu_not_used_stops(self):
        with self.assertRaises(E.EngineError) as cm:
            self.engine(FAKE_SPEECH_DEVICE="CPU")
        self.assertEqual(cm.exception.code, "gpu_failed")
        e = self.engine("cpu")   # CPU を頼んだ時は CPU で起きてよい
        self.assertEqual(e.gpu_name, "CPU")


if __name__ == "__main__":
    unittest.main()
