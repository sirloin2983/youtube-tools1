#!/usr/bin/env python3
"""whisper.cpp のエンジン(tx_engines.WhisperCpp。精度改善の計画 段2-2)のテスト。test_metrics から読み込まれる。

本物の whisper-cli の代わりに tests/fake_whisper_cli.py を子プロセスで動かす(引数・応答ファイル・結果の JSON・GPU の行・進み具合・取り消し)。
確かめること: faster-whisper の引数 → whisper-cli の引数 / 日本語のヒントが UTF-8 の応答ファイルで渡る / 結果 → 行・単語・自信の度合い /
GPU を頼んだのに Vulkan で動かなければ止める(黙って CPU にしない)/ 取り消し / 取得するファイルの大きさと SHA-256 / サーバーの受付と準備の確認。
"""
import hashlib
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない
import shutil
import sys
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
import serve as S  # noqa: E402
import tx_engines as E  # noqa: E402

FAKE = [sys.executable, os.path.join(TESTS, "fake_whisper_cli.py")]


def make_wav(path, sec=10.0):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * sec))


class WhisperCppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wcpp-test-")
        self.wav = os.path.join(self.tmp, "a.wav")
        make_wav(self.wav)
        for n in ("m.bin", "vad.bin"):
            open(os.path.join(self.tmp, n), "wb").close()
        self.args_file = os.path.join(self.tmp, "args.json")
        self.env = mock.patch.dict(os.environ, {"FAKE_WCPP_ARGS": self.args_file})
        self.env.start()
        for k in ("FAKE_WCPP_GPU", "FAKE_WCPP_SLEEP", "FAKE_WCPP_FAIL"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def engine(self, device="vulkan"):
        return E.WhisperCpp("large-v3-turbo", device, {"cmd": FAKE, "model": os.path.join(self.tmp, "m.bin"), "vad": os.path.join(self.tmp, "vad.bin")})

    def sent_args(self):
        with open(self.args_file, encoding="utf-8") as f:
            return json.load(f)

    def test_transcribe_maps_args_and_parses(self):
        e = self.engine()
        prog = []
        e.hooks = {"progress": prog.append}
        kw = S.whisper_kwargs({"language": "ja", "beam": 5, "model": "large-v3-turbo", "vadMode": "weak", "wordSplit": True,
                               "glossary": ["白上フブキ", "さくらみこ"]})
        kw = S.filter_kwargs(e, kw)
        self.assertNotIn("hotwords", kw)                                   # whisper.cpp に無い引数は渡さない
        segs, info = e.transcribe(self.wav, **kw)
        segs = list(segs)
        a = self.sent_args()
        self.assertEqual(a[a.index("-l") + 1], "ja")
        self.assertEqual(a[a.index("-bs") + 1], "5")
        self.assertEqual(a[a.index("-mc") + 1], "0")                       # 前の文を文脈にしない
        self.assertIn("用語: 白上フブキ、さくらみこ", a[a.index("--prompt") + 1])   # 日本語のヒントが化けずに届く(UTF-8 の応答ファイル)
        self.assertIn("--vad", a)
        self.assertEqual((a[a.index("-vt") + 1], a[a.index("-vsd") + 1], a[a.index("-vp") + 1]), ("0.3", "1000", "600"))   # 声の検出「弱め」
        self.assertEqual(a[a.index("-nth") + 1], "0.9")
        self.assertNotIn("-ng", a)
        self.assertEqual(len(segs), 3)                                     # 10 秒 ÷ 4 秒
        s = segs[0]
        self.assertEqual((s.start, s.end, s.text), (0.0, 4.0, "テスト文1"))
        self.assertEqual([w.word for w in s.words], ["テスト", "文1"])      # 特別なトークン [_…] は単語にしない
        self.assertEqual((s.words[1].start, s.words[1].end, s.words[1].probability), (2.0, 4.0, 0.5))
        self.assertAlmostEqual(s.avg_logprob, (__import__("math").log(0.8) + __import__("math").log(0.5)) / 2, places=5)
        self.assertIsNone(s.no_speech_prob)
        self.assertGreater(s.compression_ratio, 0)
        self.assertEqual((info.language, info.duration, info.duration_after_vad), ("ja", 10.0, None))
        self.assertEqual(e.gpu_name, "AMD Radeon RX 7800 XT")
        self.assertTrue(prog and prog[-1] >= 0.99 - 1e-9)
        # seg_to_dict(サーバーの行の整え方)がそのまま読める
        d = S.seg_to_dict(s)
        self.assertEqual((d["text"], d["words"][0][2], d["wordProbs"]), ("テスト文1", "テスト", [0.8, 0.5]))

    def test_temp0_and_cpu_and_samples(self):
        e = self.engine("cpu")
        segs, info = e.transcribe([0.0] * 16000 * 5, language="ja", beam_size=5, temperature=0.0, vad_filter=False)   # サンプル(範囲の音声)は一時の wav に
        self.assertEqual(len(list(segs)), 2)
        a = self.sent_args()
        self.assertIn("-ng", a)
        self.assertEqual(a[a.index("-tp") + 1], "0")
        self.assertIn("-nf", a)
        self.assertNotIn("--vad", a)
        self.assertNotIn("--prompt", a)
        self.assertAlmostEqual(info.duration, 5.0)

    def test_gpu_required_when_asked(self):
        """GPU(Vulkan)を頼んだのに GPU が見つからなければ止める(黙って CPU の結果を GPU として残さない)"""
        os.environ["FAKE_WCPP_GPU"] = "none"
        with self.assertRaises(E.EngineError) as cm:
            self.engine("vulkan").transcribe(self.wav, language="ja")
        self.assertEqual(cm.exception.code, "gpu_failed")
        segs, _ = self.engine("cpu").transcribe(self.wav, language="ja")   # CPU を選んだときは動く
        self.assertEqual(len(list(segs)), 3)

    def test_failure_and_cancel(self):
        os.environ["FAKE_WCPP_FAIL"] = "1"
        with self.assertRaises(E.EngineError) as cm:
            self.engine().transcribe(self.wav, language="ja")
        self.assertEqual(cm.exception.code, "engine_failed")
        self.assertIn("failed to read audio", cm.exception.message)
        del os.environ["FAKE_WCPP_FAIL"]
        os.environ["FAKE_WCPP_SLEEP"] = "30"
        e, flag = self.engine(), threading.Event()
        e.hooks = {"cancelled": flag.is_set}
        threading.Timer(0.5, flag.set).start()
        t0 = time.monotonic()
        with self.assertRaises(E.EngineError) as cm:
            e.transcribe(self.wav, language="ja")
        self.assertEqual(cm.exception.code, "cancelled")
        self.assertLess(time.monotonic() - t0, 10)                         # 子プロセスを止めてすぐ戻る

    def test_device_order_never_falls_back(self):
        self.assertEqual(E.WhisperCpp.device_order("auto", False), ["vulkan"])
        self.assertEqual(E.WhisperCpp.device_order("cuda", True), ["vulkan"])
        self.assertEqual(E.WhisperCpp.device_order("cpu", True), ["cpu"])
        self.assertEqual(E.FasterWhisper.device_order("auto", True), ["cuda", "cpu"])   # faster-whisper は今までどおり

    def test_fetch_file_checks_size_and_hash(self):
        body = b"model-bytes" * 100
        spec = {"file": "x.bin", "url": "https://example.invalid/x.bin", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        folder = os.path.join(self.tmp, "models")

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()
        with mock.patch("urllib.request.urlopen", lambda url, timeout=0: Resp(b"evil" + body[4:])):
            with self.assertRaises(E.EngineError) as cm:
                E.fetch_file(spec, folder)
        self.assertEqual(cm.exception.code, "fetch_failed")
        self.assertEqual(os.listdir(folder), [])                            # 中身が違えば .part も残さない
        with mock.patch("urllib.request.urlopen", lambda url, timeout=0: Resp(body)):
            p = E.fetch_file(spec, folder)
        self.assertEqual(open(p, "rb").read(), body)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("通信しない")):
            self.assertEqual(E.fetch_file(spec, folder), p)                  # あって中身が合えば取らない
        with self.assertRaises(E.EngineError):
            E.fetch_file(dict(spec, url="http://example.invalid/x.bin", sha256="0" * 64), folder)   # https 以外からは取らない

    def test_pinned_files_are_https_and_hashed(self):
        for spec in list(E.WCPP_MODELS.values()) + [E.WCPP_VAD]:
            self.assertTrue(spec["url"].startswith("https://huggingface.co/"))
            self.assertRegex(spec["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(spec["size"], 0)
        self.assertRegex(E.WHISPER_CPP["commit"], r"^[0-9a-f]{40}$")

    def test_server_accepts_engine_and_checks_ready(self):
        media = os.path.join(self.tmp, "v.wav")
        make_wav(media, 3)
        with mock.patch.object(S, "media_duration", lambda p: 3.0):
            spec = S.validate_job({"sourcePath": media, "model": "large-v3-turbo", "engine": "whisper.cpp"})
            self.assertEqual(spec["engine"], "whisper.cpp")
            self.assertEqual(S.validate_job({"sourcePath": media, "model": "small"})["engine"], "faster-whisper")
            for bad, code in (({"engine": "whisper.cpp", "model": "small"}, "bad_model"), ({"engine": "nope", "model": "small"}, "bad_engine")):
                with self.assertRaises(S.ApiError) as cm:
                    S.validate_job(dict({"sourcePath": media}, **bad))
                self.assertEqual(cm.exception.code, code)
        with mock.patch.object(S, "DATA_DIR", self.tmp):
            with self.assertRaises(S.ApiError) as cm:
                S.check_engine(spec)                                        # まだ作っていない → 理由を出して止める
            self.assertEqual(cm.exception.code, "engine_missing")
            self.assertIn("build-whisper-vulkan.bat", cm.exception.message)
            d = E.wcpp_bin_dir(self.tmp)
            os.makedirs(d)
            open(os.path.join(d, E.WCPP_EXE), "wb").close()
            with open(os.path.join(d, "build.json"), "w") as f:
                json.dump({"commit": "0" * 40}, f)
            with self.assertRaises(S.ApiError):                              # 版(コミット)が違う物は使わない
                S.check_engine(spec)
            with open(os.path.join(d, "build.json"), "w") as f:
                json.dump({"commit": E.WHISPER_CPP["commit"]}, f)
            S.check_engine(spec)
        rec = S.recognition_run(dict(spec, beam=5, vadMode="weak"), {"device": "vulkan"}, 1, 1)
        if S.backend_name() != "fake":
            self.assertEqual((rec["engine"], rec["engineVersion"]), ("whisper.cpp", E.WHISPER_CPP["version"]))


if __name__ == "__main__":
    unittest.main()
