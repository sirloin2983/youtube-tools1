# -*- coding: utf-8 -*-
"""flow/machine(この PC の設定。役割で組み直す RS7-1 S1)のテスト。  py -3.10 -m unittest src/flow/tests/test_machine.py -v

- 読む順の強さ: 引数 > 環境変数 > ファイル > 既定(sources も)・既定 = 今の値(編集の設定の device・qwen3-8b・スタジオの outDir・20・作業データの根)
- machine.json が無ければ書かない・save の検査(知らない項目・合わない値はファイルを変えない)・None で既定へ
- overlay: 決めた値だけを束に重ねる(何も決めていなければ束は同じ)・device だけのときは機器から決まるエンジンも・LLM のモデル
- 束 → 要求の本文: 既定の LLM のモデルは書かない・違えば llmModel
- llm.llm_model・worker_client の機器の決め方(本文が先・auto のときだけ TRANSCRIBE_DEVICE)・live_tx の機械の都合
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import live_tx as LT, machine as M, spec as S  # noqa: E402
from pipeline.transcribe import llm, tx_engines  # noqa: E402
from ytt import workdata  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-machine-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.file = os.path.join(self.tmp, "machine.json")
        self.settings = os.path.join(self.tmp, "editor-settings.json")
        p = mock.patch.object(workdata, "SETTINGS", self.settings)
        p.start()
        self.addCleanup(p.stop)
        self.env = {"YTT_DATA_DIR": self.tmp, M.FILE_ENV: self.file}

    def write(self, obj, path=None):
        with open(path or self.file, "w", encoding="utf-8") as f:
            json.dump(obj, f)


class TestLoad(Base):
    def test_defaults_are_todays_values(self):
        self.write({"device": "vulkan"}, self.settings)
        m = M.load(env=self.env)
        self.assertEqual(m["device"], "vulkan")
        self.assertEqual(m["engine"], "whisper.cpp")   # 機器から決まるエンジン(spec.implied_engine)
        self.assertEqual(m["llmModel"], llm.LLM_MODEL)
        self.assertEqual(m["diskMinGB"], 20)
        self.assertEqual(m["learningDir"], os.path.abspath(self.tmp))   # 作業データの根
        self.assertEqual(m["caseRoot"], os.path.join(self.tmp, "studio", "exports"))   # スタジオの outDir(設定が無ければ exports)
        self.assertEqual(set(m["sources"].values()), {"default"})
        self.assertFalse(os.path.exists(self.file))   # 読むだけでは書かない

    def test_default_device_auto_when_editor_setting_missing_or_odd(self):
        self.assertEqual(M.load(env=self.env)["device"], "auto")
        self.write({"device": "gpu"}, self.settings)
        m = M.load(env=self.env)
        self.assertEqual((m["device"], m["engine"]), ("auto", "faster-whisper"))

    def test_llm_default_matches_llm_py(self):
        self.assertEqual(M.LLM_MODEL, llm.LLM_MODEL)
        self.assertEqual(S.DEFAULTS["post"]["llmModel"], llm.LLM_MODEL)
        self.assertIn(M.LLM_MODEL, tx_engines.LLAMA_TEXT_MODELS)

    def test_order_arg_env_file_default(self):
        self.write({"device": "cpu", "diskMinGB": 50, "llmModel": "file-model"})
        env = dict(self.env, YTT_MACHINE_DEVICE="cuda", YTT_MACHINE_DISK_MIN_GB="30")
        m = M.load({"device": "vulkan"}, env=env)
        self.assertEqual((m["device"], m["sources"]["device"]), ("vulkan", "arg"))
        self.assertEqual((m["diskMinGB"], m["sources"]["diskMinGB"]), (30, "env"))
        self.assertEqual((m["llmModel"], m["sources"]["llmModel"]), ("file-model", "file"))
        self.assertEqual(m["sources"]["caseRoot"], "default")
        self.assertEqual(M.load(env=dict(self.env, YTT_MACHINE_DEVICE="cuda"))["device"], "cuda")
        self.assertEqual(M.load(env=self.env)["device"], "cpu")
        self.assertEqual(M.get("diskMinGB", env=env), 30)

    def test_legacy_transcribe_device_env(self):
        self.assertEqual(M.load(env=dict(self.env, TRANSCRIBE_DEVICE="cpu"))["device"], "cpu")
        self.assertEqual(M.load(env=dict(self.env, TRANSCRIBE_DEVICE="cpu", YTT_MACHINE_DEVICE="cuda"))["device"], "cuda")   # 新しい名前が先

    def test_bad_values_fall_through(self):
        self.write({"device": "gpu", "diskMinGB": -1, "unknown": 1, "caseRoot": "relative/dir", "engine": "whisper.cpp"})
        with self.assertLogs("ytt.flow.machine", "WARNING"):
            m = M.load(env=dict(self.env, YTT_MACHINE_ENGINE="nope"))
        self.assertEqual((m["engine"], m["sources"]["engine"]), ("whisper.cpp", "file"))
        self.assertEqual(m["sources"]["device"], "default")
        self.assertEqual(m["sources"]["diskMinGB"], "default")
        self.assertEqual(m["sources"]["caseRoot"], "default")
        with self.assertRaises(ValueError):
            M.load({"device": "gpu"}, env=self.env)   # 引数の間違いは理由つきで止める
        with self.assertRaises(ValueError):
            M.load({"color": 1}, env=self.env)

    def test_broken_file_is_default(self):
        with open(self.file, "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertLogs("ytt.flow.machine", "WARNING"):
            self.assertEqual(M.load(env=self.env)["sources"]["device"], "default")

    def test_path(self):
        self.assertEqual(M.path(self.env), os.path.abspath(self.file))
        self.assertEqual(M.path({"YTT_DATA_DIR": self.tmp}), os.path.join(os.path.abspath(self.tmp), "machine.json"))
        self.assertEqual(M.path({"YTT_DATA_DIR": "inplace"}), os.path.join(SRC, "machine.json"))


class TestSave(Base):
    def test_save_merges_and_checks(self):
        got = M.save({"device": "vulkan", "diskMinGB": "25"}, env=self.env)
        self.assertEqual(got, {"device": "vulkan", "diskMinGB": 25, "schema": M.SCHEMA})
        M.save({"llmModel": "qwen3-8b"}, env=self.env)
        with open(self.file, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"device": "vulkan", "diskMinGB": 25, "llmModel": "qwen3-8b", "schema": M.SCHEMA})
        M.save({"device": None}, env=self.env)   # None = 消して既定へ
        self.assertNotIn("device", M.read_file(env=self.env))
        self.assertEqual(M.load(env=self.env)["sources"]["device"], "default")

    def test_save_rejects_without_writing(self):
        M.save({"device": "cpu"}, env=self.env)
        with open(self.file, "rb") as f:
            before = f.read()
        for bad in ({"device": "gpu"}, {"color": "red"}, {"caseRoot": "rel"}, {"diskMinGB": True}, {"llmModel": "a b"}, ["device"]):
            with self.assertRaises(ValueError, msg=bad):
                M.save(bad, env=self.env)
        with open(self.file, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_save_drops_bad_old_values(self):
        self.write({"device": "gpu", "other": 1, "engine": "whisper.cpp"})
        self.assertEqual(M.save({"diskMinGB": 5}, env=self.env), {"engine": "whisper.cpp", "diskMinGB": 5, "schema": M.SCHEMA})

    def test_check_paths_and_numbers(self):
        p = os.path.abspath(self.tmp)
        self.assertEqual(M.check("caseRoot", " %s " % p), os.path.normpath(p))
        self.assertEqual(M.check("diskMinGB", 12.5), 12.5)
        self.assertEqual(M.check("diskMinGB", "0"), 0)
        for v in (float("nan"), -0.1, M.DISK_MAX_GB + 1, "x"):
            with self.assertRaises(ValueError):
                M.check("diskMinGB", v)


class TestOverlay(Base):
    def bundle(self, **tx):
        return S.validate(S.merge({"transcribe": tx} if tx else None))

    def test_nothing_set_keeps_bundle(self):
        self.write({"device": "vulkan"}, self.settings)   # 編集の設定の既定は重ねない(束の側の値のまま)
        b = self.bundle(device="cpu", engine="faster-whisper")
        out = M.overlay(b, env=self.env)
        self.assertEqual(out, b)
        self.assertIsNot(out, b)
        self.assertEqual(S.tx_opts(out), S.tx_opts(b))
        self.assertNotIn("llmModel", S.tx_opts(out))

    def test_device_and_derived_engine(self):
        b = self.bundle()   # auto・faster-whisper(機器から決まるエンジン)
        out = M.overlay(b, env=dict(self.env, YTT_MACHINE_DEVICE="vulkan"))
        self.assertEqual((out["transcribe"]["device"], out["transcribe"]["engine"]), ("vulkan", "whisper.cpp"))
        S.validate(out)
        self.assertEqual(b["transcribe"]["device"], "auto")   # 元の束は変えない
        self.assertNotIn("engine", S.tx_opts(out))   # 本文は機器だけ(エンジンは機器から決まる)

    def test_device_keeps_chosen_engine(self):
        b = self.bundle(engine="qwen3-asr")
        out = M.overlay(b, env=dict(self.env, TRANSCRIBE_DEVICE="cpu"))
        self.assertEqual((out["transcribe"]["device"], out["transcribe"]["engine"]), ("cpu", "qwen3-asr"))

    def test_file_engine_and_llm(self):
        self.write({"engine": "whisper.cpp", "device": "vulkan", "llmModel": "qwen3-4b"})
        out = M.overlay(self.bundle(), env=self.env)
        self.assertEqual(out["transcribe"]["engine"], "whisper.cpp")
        self.assertEqual(out["post"]["llmModel"], "qwen3-4b")
        S.validate(out)
        self.assertEqual(S.tx_opts(out)["llmModel"], "qwen3-4b")
        self.assertEqual(M.overlay(self.bundle(), {"llmModel": "x-1"}, env=self.env)["post"]["llmModel"], "x-1")   # 引数が先


class TestFirstLayer(Base):
    def test_llm_model_from_request(self):
        self.assertEqual(llm.llm_model({}), llm.LLM_MODEL)
        self.assertEqual(llm.llm_model({"llmModel": "qwen3-8b"}), "qwen3-8b")
        with mock.patch.dict(tx_engines.LLAMA_TEXT_MODELS, {"tiny-llm": {}}):
            self.assertEqual(llm.llm_model({"llmModel": "tiny-llm"}), "tiny-llm")
        with self.assertLogs(level="WARNING"):
            self.assertEqual(llm.llm_model({"llmModel": "unknown-llm"}), llm.LLM_MODEL)   # 知らない名前は既定(警告だけ)

    def test_worker_prefers_request_device(self):
        from pipeline.transcribe import worker_client as W
        seen = []

        class Eng:
            light = False

            @staticmethod
            def device_order(pref, cuda_ok):
                seen.append(pref)
                return []

        with mock.patch.object(W.tx_engines, "get", return_value=Eng), mock.patch.dict(os.environ, {"TRANSCRIBE_DEVICE": "cuda"}):
            for pref in ("cpu", "auto"):
                with self.assertRaises(Exception):
                    W._load_model_local("small", {}, pref, engine="whisper.cpp")
        self.assertEqual(seen, ["cpu", "cuda"])   # 本文の cpu が先・auto のときだけ環境変数

    def test_live_tx_machine(self):
        with mock.patch.dict(os.environ, {M.FILE_ENV: self.file}):
            for k in ("YTT_MACHINE_DEVICE", "YTT_MACHINE_ENGINE", "TRANSCRIBE_DEVICE"):
                os.environ.pop(k, None)
            self.assertEqual(LT.LiveTx.machine(), {"engine": "whisper.cpp", "device": "vulkan"})   # 何も決めていない = 今まで
            self.write({"device": "cpu"})   # 機器だけ cpu = faster-whisper の CPU = 配信中は今までどおり
            self.assertEqual(LT.LiveTx.machine()["device"], "vulkan")
            self.write({"device": "cpu", "engine": "whisper.cpp"})
            self.assertEqual(LT.LiveTx.machine()["device"], "cpu")
            self.write({"device": "cuda", "engine": "whisper.cpp"})   # whisper.cpp の CUDA 版はまだ無い
            self.assertEqual(LT.LiveTx.machine()["device"], "vulkan")


if __name__ == "__main__":
    unittest.main()
