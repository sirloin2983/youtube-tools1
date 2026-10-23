#!/usr/bin/env python3
"""LLM の後処理 E(pipeline/transcribe/llm.py)の、通しで起こせない所のテスト。test_metrics から読み込まれる。

    py -3.12 -m unittest tests/eval/drill/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest test_llm -q                         # これだけ(tests/editor で)

規則(選ぶ・聞く・検査・上限・当てる)は tests/pipeline/transcribe/test_postproc.py の見本の通し、ジョブの記録は test_fill.py の通し、
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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS))), "src", "editor"))
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "editor"))   # test_backend・test_edit(編集のサーバーを一時フォルダで動かす道具)
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


class TestLlmNames(unittest.TestCase):
    MEMBERS = [{"name": "雪花ラミィ", "aliases": ["ラミィ", "ラミィちゃん"]}, {"name": "赤井はあと", "aliases": ["はあちゃま", "はあちゃん"]},
               {"name": "さくらみこ", "aliases": ["みこち"]}]

    def test_members_from_text_and_keep_written_names(self):
        from pipeline.transcribe import llm
        doc = {"title": "配信", "text": "はあちゃまと ラミィちゃん来た みこちー"}
        self.assertEqual([m["name"] for m in llm.llm_members(doc, self.MEMBERS)], ["雪花ラミィ", "赤井はあと", "さくらみこ"])   # 行の文字に出た人も足す
        with mock.patch.object(llm, "LLM_FROM_TEXT", False):
            self.assertEqual(llm.llm_members(doc, self.MEMBERS), [])
        t = llm.llm_targets(self.MEMBERS)
        self.assertEqual(llm.llm_near("はあちゃまが来た", t), [])        # すでに書かれた呼び名を別の呼び名に言い換えない
        self.assertEqual(llm.llm_near("ラミィちゃん来た", t), [])        # 書かれた名前の中の「ミィち」を「みこち」にしない
        self.assertIn(("き花ラミィ", "雪花ラミィ"), llm.llm_near("き花ラミィだよ", t))   # 同じ人の名前(姓と名)には直せる
        self.assertEqual(llm.llm_near("はいこちらどうぞ", t), [])   # 語の途中(「は|い」)から切り出した「いこち」を「みこち」にしない(10-23)
        self.assertIn(("メコち", "みこち"), llm.llm_near("なったらメコちゃん", t))   # かなの種類が替わる所は語の切れ目 = 直せる

    def test_glossary_terms(self):
        from pipeline.transcribe import llm
        rows = [_seg(0, "リスカーが来た"), _seg(1, "リッカーだ"), _seg(2, "ナイスー")]
        picks = llm.llm_pick(rows, self.MEMBERS, {"title": "配信"}, gloss=["リッカー", "ナイフ"])   # 用語集の語の 1 字違いを候補に(3 字の語は探さない)
        self.assertEqual([(p["row"], p["span"], p["why"], p["cands"]) for p in picks], [(0, "リスカー", "gloss", ["リッカー"])])   # 書かれた語は直さない
        self.assertEqual(llm.llm_pick(rows, self.MEMBERS, {"title": "配信"}), [])            # 用語集が空なら今までどおり
        with mock.patch.object(llm, "LLM_GLOSSARY", False):
            self.assertEqual(llm.llm_pick(rows, self.MEMBERS, {"title": "配信"}, gloss=["リッカー"]), [])
        self.assertEqual(llm.llm_guard("トップ下", {"from": "トップ", "to": "リッカー", "confidence": 0.9}, [], llm.llm_names(llm.llm_gloss(["リッカー"]))), "newName")   # 候補に無い所へ持ち込まない


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
