#!/usr/bin/env python3
"""LLM の後処理 E(pipeline/transcribe/llm.py)の、通しで起こせない所のテスト。test_metrics から読み込まれる。

    py -3.12 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest test_llm -q                         # これだけ(src/editor/tests で)

規則(選ぶ・聞く・検査・上限・当てる)は src/pipeline/transcribe/tests/test_postproc.py の見本の通し、ジョブの記録は test_fill.py の通し、
本物の Qwen3-4B は test_fill_llm.py が確かめる。ここに残すのは:
- 学習: 後処理が直した行(fill)を含むまとまりは learn_events の材料にしない(校正のあとの話。文字起こしの通しでは起きない)
- エンジン: LlamaText の登録(モデルの表・取得先と SHA-256)・サーバーからワーカーへ頼む op complete(通しはワーカーの中で読むので通らない)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import types
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
import test_backend  # noqa: E402,F401  (serve を読んで src を sys.path に足す)
from pipeline.transcribe import models as _models  # noqa: E402
from human.proof import learn  # noqa: E402
import ed_state  # noqa: E402
from pipeline.transcribe import tx_engines as E  # noqa: E402
from pipeline.transcribe import worker as W  # noqa: E402  (認識ワーカーの受け口)


def _seg(i, text, **kw):
    return dict({"id": "s%d" % i, "start": float(i), "end": i + 1.0, "text": text, "speaker": "", "flag": ""}, **kw)


class TestLlmLearn(unittest.TestCase):
    def test_learn_events_skip_postfix_rows(self):
        doc = {"original": [{"start": 0, "end": 2, "text": "ラミーちゃん来た"}, {"start": 3, "end": 5, "text": "トーイ様"}],
               "segments": [_seg(0, "ラミィちゃん来た", end=2, fill={"from": "ラミーちゃん来た", "by": "llm"}, proofed=True),
                            _seg(3, "トワ様", end=5, proofed=True)]}
        ev = learn.learn_events(doc)
        self.assertTrue(ev and all("ラミ" not in w and "ラミ" not in r for w, r, *_ in ev), ev)   # LLM が直した行は覚えない
        self.assertTrue(any("ト" in w for w, *_ in ev), ev)                                     # 人が直した行は今までどおり


class TestLlamaTextEngine(unittest.TestCase):
    def test_registered(self):
        self.assertTrue(E.valid("llama-text"))
        self.assertIs(E.get("llama-text").light, True)
        self.assertTrue(E.LlamaText.valid_model("qwen3-8b"))
        self.assertFalse(E.LlamaText.valid_model("qwen3-asr-1.7b"))   # 表は Qwen3-ASR と別
        self.assertTrue(E.LlamaQwen3.valid_model("qwen3-asr-1.7b"))
        spec = E.LLAMA_TEXT_MODELS["qwen3-8b"]["model"]
        self.assertTrue(spec["url"].startswith("https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/"))
        self.assertEqual((spec["size"], len(spec["sha256"])), (5027783488, 64))
        self.assertEqual((E.LlamaText.MODEL_SUBDIR, E.LlamaQwen3.MODEL_SUBDIR), ("llm-gguf", "qwen3asr-gguf"))

    def test_worker_op_complete(self):
        model = types.SimpleNamespace(complete=lambda msgs, n: "答え:%d:%d" % (len(msgs), n))
        m = {"name": "qwen3-8b", "device": "vulkan", "engine": "llama-text", "messages": [{"role": "user", "content": "x"}], "max_tokens": 50}
        # ワーカーは読み込んだモデルを worker_client._models から呼ぶたびに読む(S._models は同じ辞書。_model_used は差し替えて元に戻す)
        with mock.patch.dict(_models._models, {("qwen3-8b", "vulkan", "llama-text"): model}, clear=True), mock.patch.object(_models, "_model_used", [0]), \
                mock.patch.object(_models, "_load_model_local", None):
            self.assertEqual(W._op_complete(m, 1, {}, None, set()), {"content": "答え:1:50"})
            with self.assertRaises(ed_state.ApiError):
                W._op_complete(dict(m, messages=[{"role": "tool", "content": "x"}]), 1, {}, None, set())
            with self.assertRaises(ed_state.ApiError):
                W._op_complete(dict(m, engine="faster-whisper"), 1, {}, None, set())


if __name__ == "__main__":
    unittest.main()
