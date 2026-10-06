#!/usr/bin/env python3
"""Qwen3-ASR のエンジン(tx_engines.Qwen3Asr = sherpa-onnx の 0.6B・LlamaQwen3 = llama.cpp の 1.7B。精度改善の計画 段2-3)のテスト。test_metrics から読み込まれる。

本物のモデルは使わない: 区切り・行の作り方・繰り返しの縮め方・答えの読み取り・圧縮ファイルの検査は関数を直に、
llama.cpp は偽の llama-server(tests/fake_llama_server.py)を子プロセスで動かす(合言葉・言語の先書き・GPU の確認・落ちたら起動し直す)。
"""
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない
import shutil
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
import serve as S  # noqa: E402
import tx_engines as E  # noqa: E402

FAKE = [sys.executable, os.path.join(TESTS, "fake_llama_server.py")]


class Qwen3TextTest(unittest.TestCase):
    def test_chunks_cut_at_quiet_point(self):
        fr = E.Q3_FRAME
        rms = [0.5] * int(40 / fr)
        q = int(20 / fr)
        rms[q] = rms[q + 1] = 0.0   # 20 秒の所が静か
        ch = E.q3_chunks(rms)
        self.assertEqual(ch[0][0], 0)
        self.assertTrue(abs(ch[0][1] - q) <= 2, ch)
        self.assertEqual(ch[-1][1], len(rms))
        self.assertTrue(all(b - a <= int(E.Q3_MAX / fr) for a, b in ch))
        self.assertEqual(E.q3_chunks([0.1] * int(10 / fr)), [(0, int(10 / fr))])   # 短ければ1つ
        self.assertEqual(E.q3_chunks([]), [])

    def test_rows_split_and_time(self):
        rows = E.q3_rows("こんにちは。元気ですか？はい", 10.0, 16.0)
        self.assertEqual([r[2] for r in rows], ["こんにちは。", "元気ですか？", "はい"])
        self.assertEqual(rows[0][0], 10.0)
        self.assertEqual(rows[-1][1], 16.0)
        self.assertTrue(all(rows[i][1] <= rows[i + 1][0] + 1e-6 for i in range(len(rows) - 1)))
        long = "、".join(["あいうえおかきくけこ"] * 6) + "。"   # 65 字 → 「、」でも分ける
        self.assertTrue(all(len(r[2]) <= 16 * 2 + 11 for r in E.q3_rows(long, 0, 10)))
        self.assertGreater(len(E.q3_rows(long, 0, 10)), 1)
        self.assertEqual(E.q3_rows("", 0, 1), [])
        self.assertEqual(E.q3_rows("文章<|endoftext|>The Simpsons Wiki", 0, 1)[0][2], "文章")   # 特別なトークンから先は捨てる

    def test_rows_follow_voiced_frames(self):
        # 前半 2 秒が静か・後半 2 秒に声 → 行は声のある所に置く
        voiced = [False] * 40 + [True] * 40
        rows = E.q3_rows("あいう", 0.0, 4.0, voiced=voiced)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][0], 2.0)
        self.assertAlmostEqual(rows[0][1], 4.0)

    def test_squash_repeats(self):
        self.assertEqual(E.q3_squash("过来，来" * 30), "过来，来" * E.Q3_REPEAT_KEEP)
        self.assertEqual(E.q3_squash("う" * 50), "う" * E.Q3_REPEAT_KEEP)
        self.assertEqual(E.q3_squash("OKOKOK"), "OKOKOK")   # 4 回までは残す
        self.assertEqual(E.q3_squash("普通の文章です"), "普通の文章です")

    def test_parse_answer(self):
        self.assertEqual(E.q3_parse("language Japanese<asr_text>こんにちは"), ("Japanese", "こんにちは"))
        self.assertEqual(E.q3_parse("こんにちは"), ("", "こんにちは"))
        self.assertEqual(E.q3_parse("language Japanese<asr_text>"), ("Japanese", ""))
        self.assertEqual(E.q3_parse(None), ("", ""))

    def test_floor(self):
        self.assertEqual(E.q3_floor([]), 0.0)
        self.assertAlmostEqual(E.q3_floor([0.01] * 8 + [1.0, 1.0]), 0.05)


class Qwen3ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_qwen3_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tar(self, names):
        p = os.path.join(self.tmp, "m.tar.bz2")
        with tarfile.open(p, "w:bz2") as t:
            for n in names:
                info = tarfile.TarInfo(n)
                info.size = 1
                t.addfile(info, io.BytesIO(b"x"))
        return p

    def test_extract_only_inside_top(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        E._safe_extract(self._tar(["top/a.onnx", "top/tokenizer/vocab.json"]), out, "top")
        self.assertTrue(os.path.isfile(os.path.join(out, "top", "tokenizer", "vocab.json")))
        for bad in (["../evil"], ["top/../../evil"], ["other/a"], ["/abs"]):
            with self.assertRaises(E.EngineError):
                E._safe_extract(self._tar(bad), out, "top")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))

    def test_unzip_rejects_traversal(self):
        out = os.path.join(self.tmp, "bin")
        os.makedirs(out)
        good = os.path.join(self.tmp, "g.zip")
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("llama-server.exe", b"x")
        E._safe_unzip(good, out)
        self.assertTrue(os.path.isfile(os.path.join(out, "llama-server.exe")))
        for bad in ("../evil.dll", "C:/evil.dll", "a/../../evil.dll"):
            p = os.path.join(self.tmp, "b.zip")
            with zipfile.ZipFile(p, "w") as z:
                z.writestr(bad, b"x")
            with self.assertRaises(E.EngineError):
                E._safe_unzip(p, out)


class Qwen3EngineTest(unittest.TestCase):
    def test_registered_and_models(self):
        self.assertTrue(E.valid("qwen3-asr"))
        self.assertTrue(E.valid("llama.cpp"))
        self.assertTrue(E.get("qwen3-asr").valid_model("qwen3-asr-0.6b"))
        self.assertFalse(E.get("qwen3-asr").valid_model("large-v3"))
        self.assertTrue(E.get("llama.cpp").valid_model("qwen3-asr-1.7b"))
        self.assertFalse(E.get("llama.cpp").valid_model("../x"))
        self.assertEqual(E.get("qwen3-asr").device_order("auto", True), ["cpu"])
        self.assertEqual(E.get("llama.cpp").device_order("auto", False), ["vulkan"])
        self.assertEqual(E.get("llama.cpp").device_order("cpu", False), ["cpu"])
        for spec in [E.QWEN3_MODELS["qwen3-asr-0.6b"], E.LLAMA_CPP] + [v for m in E.LLAMA_MODELS.values() for v in m.values()]:
            self.assertTrue(spec["url"].startswith("https://"))
            self.assertRegex(spec["sha256"], r"^[0-9a-f]{64}$")

    def test_server_accepts_engine(self):
        self.assertEqual(S.req_engine({"engine": "llama.cpp"}, "qwen3-asr-1.7b"), "llama.cpp")
        self.assertEqual(S.req_engine({"engine": "qwen3-asr"}, "qwen3-asr-0.6b"), "qwen3-asr")
        with self.assertRaises(S.ApiError) as c:
            S.req_engine({"engine": "llama.cpp"}, "large-v3")
        self.assertEqual(c.exception.code, "bad_model")

    def test_engine_module_has_no_native_imports(self):
        with open(os.path.join(HERE, "tx_engines.py"), encoding="utf-8") as f:
            src = f.read()
        top = [l for l in src.splitlines() if l.startswith(("import ", "from "))]
        self.assertFalse([l for l in top if any(m in l for m in ("numpy", "sherpa_onnx", "faster_whisper"))], top)


@unittest.skipUnless(os.name == "nt" or shutil.which("python3"), "子プロセスの偽の server")
class LlamaServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_llama_")
        self.log = os.path.join(self.tmp, "req.jsonl")
        self.env = mock.patch.dict(os.environ, {"FAKE_LLAMA_LOG": self.log})
        self.env.start()
        self.cmd = mock.patch.object(E.LlamaQwen3, "COMMAND", FAKE)
        self.cmd.start()
        self.fetch = mock.patch.object(E, "fetch_file", lambda spec, folder, *a, **k: os.path.join(folder, spec["file"]))
        self.fetch.start()
        self.engines = []

    def tearDown(self):
        for e in self.engines:
            e.close()
        self.fetch.stop()
        self.cmd.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, device="vulkan"):
        e = E.LlamaQwen3.create("qwen3-asr-1.7b", device, "int8", data_dir=self.tmp)
        self.engines.append(e)
        return e

    def requests(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_transcribe_with_language_and_key(self):
        e = self.make()
        self.assertEqual(e.gpu_name, "Fake GPU")
        x = [0.0] * 16000 + [0.3, -0.3] * 8000 * 3 + [0.0] * 16000   # 1 秒の無音・3 秒の音・1 秒の無音
        segs, info = e.transcribe(x, language="ja", hotwords="スバル, みこち")
        rows = list(segs)
        self.assertEqual(info.duration, 5.0)
        self.assertEqual([r.text for r in rows], ["音声 5 秒。"])
        self.assertGreaterEqual(rows[0].start, 0.9)   # 時刻は音のある所
        self.assertLessEqual(rows[0].end, 4.1)
        req = self.requests()[0]
        self.assertEqual(req["messages"][0], {"role": "system", "text": "スバル、みこち"})
        self.assertEqual(req["messages"][-1], {"role": "assistant", "text": "language Japanese<asr_text>"})
        with self.assertRaises(urllib.error.HTTPError) as c:   # 合言葉なしは断られる
            urllib.request.urlopen("http://127.0.0.1:%d/health" % e.port, timeout=5)
        self.assertEqual(c.exception.code, 401)

    def test_silence_is_not_sent(self):
        e = self.make()
        self.assertEqual(list(e.transcribe([0.0] * 32000, language="ja")[0]), [])
        self.assertFalse(os.path.exists(self.log))

    def test_gpu_required(self):
        with mock.patch.dict(os.environ, {"FAKE_LLAMA_GPU": "none"}):
            with self.assertRaises(E.EngineError) as c:
                self.make()
        self.assertEqual(c.exception.code, "gpu_failed")
        self.make(device="cpu")   # CPU を選んだときは GPU の行が無くてよい

    def test_restart_after_crash(self):
        with mock.patch.dict(os.environ, {"FAKE_LLAMA_DIE_AFTER": "1"}):
            e = self.make()
            x = ([0.3, -0.3] * 8000 * 20 + [0.0] * 16000) * 2   # 約 42 秒 → 2 つの区切り
            rows = list(e.transcribe(x, language="ja")[0])
        self.assertEqual(len(rows), 2)   # 2 つ目の区切りの前に落ちた server を起動し直して続けた
        self.assertIsNotNone(e.proc)

    def test_close_stops_server(self):
        e = self.make()
        p = e.proc
        e.close()
        self.assertIsNotNone(p.poll())
        self.assertIsNone(e.proc)


if __name__ == "__main__":
    unittest.main()
