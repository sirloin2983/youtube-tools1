#!/usr/bin/env python3
"""LLM の後処理 E(pipeline/transcribe/llm.py。旧 src/editor/ed_llm.py。提案 P18。編集 0.61.0)のテスト。test_metrics から読み込まれる。

    py -3.10 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest test_llm -q                         # これだけ(src/editor/tests で)

- 規則: 選ぶ(名簿の呼び名に 1 字違い・誤りやすい形・カタカナの規則・後処理の行は選ばない)・答えの読み方・検査・上限・当てる(印と元の文字)
- ジョブ(疑似の認識 TRANSCRIBE_BACKEND=fake + TRANSCRIBE_FAKE_LLM): 行が直り fill {by: llm} と印・記録 recognition.runs[].llm・<id>.llm.json・
  設定 autoLlm(既定オン・評価用はオフ)・選んだ所が無ければ LLM を読まない・失敗しても文字起こしは成功(警告)・文書の削除で llm.json も消える
- 学習: 後処理が直した行(fill)を含むまとまりは learn_events の材料にしない
- エンジン: LlamaText の登録(light・モデルの表・置き場所)・偽(FAKE_REPLY)・音声は認識しない・ワーカーの op complete
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, StoreDir, write_json  # noqa: F401,E402  (S = serve)
from test_alt import make_video  # noqa: E402
import ed_jobs  # noqa: E402
import ed_learn  # noqa: E402
from pipeline.transcribe import llm  # noqa: E402  (RS2-9 から持ち主 pipeline/transcribe/llm.py を直に読む。旧 ed_llm)
import ed_state  # noqa: E402
import ed_store  # noqa: E402
from pipeline.transcribe import tx_engines as E  # noqa: E402
from pipeline.transcribe import worker as W  # noqa: E402  (認識ワーカーの受け口。RS2-9 から pipeline/transcribe/worker.py。旧 tx_worker)

HAVE_FF = bool(shutil.which("ffmpeg"))
MEMBERS = [{"name": "雪花ラミィ", "aliases": ["ラミィ", "ラミィちゃん"], "common": []},
           {"name": "常闇トワ", "aliases": ["トワ", "トワ様"], "common": ["トワ"], "misrecognitions": [{"wrong": "トーイ", "right": "トワ"}]},
           {"name": "尾丸ポルカ", "aliases": ["ポルカ"], "common": []}]


def _seg(i, text, **kw):
    return dict({"id": "s%d" % i, "start": float(i), "end": i + 1.0, "text": text, "speaker": "", "flag": ""}, **kw)


class TestLlmRules(unittest.TestCase):
    def test_members_and_pick(self):
        doc = {"title": "配信_雪花ラミィ_x", "sourcePath": "E:/v.mp4"}
        self.assertEqual([m["name"] for m in llm.llm_members(doc, MEMBERS)], ["雪花ラミィ"])
        rows = [_seg(0, "生き花ラミーちゃんが好き"), _seg(1, "ラミィちゃん来た"), _seg(2, "ラミーちゃん", fill={"from": "x", "by": "sense-voice"}), _seg(3, "")]
        picks = llm.llm_pick(rows, MEMBERS, doc)
        self.assertEqual([(p["row"], p["span"], p["why"]) for p in picks], [(0, "ラミーちゃん", "name")])   # 長い方だけ・そのまま出ている行・後処理の行・空の行は選ばない
        doc2 = {"title": "26-01-01_常闇トワ"}
        self.assertEqual([p["why"] for p in llm.llm_pick([_seg(0, "トーイ様こんばんは")], MEMBERS, doc2)], ["mis"])
        self.assertEqual(len(llm.llm_pick([_seg(i, "ラミーちゃん") for i in range(40)], MEMBERS, doc)), llm.LLM_MAX_PICKS)

    def test_katakana_rule(self):
        targets = llm.llm_targets([MEMBERS[2]])
        self.assertEqual(llm.llm_near("言ってみるか", targets), [])   # ひらがなの普通の言葉はカタカナの名前に近いとみない
        self.assertIn(("トルカ", "ポルカ"), llm.llm_near("トルカ来た", targets))

    def test_parse_and_messages(self):
        self.assertEqual(llm.llm_parse('<think>x</think>答え {"edits": [{"from": "a", "to": "b", "confidence": 0.9}, {"from": 1}]}'),
                         [{"from": "a", "to": "b", "confidence": 0.9}])
        self.assertEqual(llm.llm_parse("なし"), [])
        m = llm.llm_messages([_seg(i, "行%d" % i) for i in range(6)], 3, [{"span": "行", "cands": ["ラミィ"]}], ["雪花ラミィ"])
        self.assertEqual([x["role"] for x in m], ["system", "user"])
        self.assertIn("/no_think", m[0]["content"])
        self.assertIn("→ 行3", m[1]["content"])
        self.assertNotIn("行0", m[1]["content"])

    def test_guard_cap_apply(self):
        t = "生き花ラミーちゃんが好き"
        names = llm.llm_names(MEMBERS)
        self.assertIsNone(llm.llm_guard(t, {"from": "ラミー", "to": "ラミィ", "confidence": 0.9}, ["ラミィ"], names))
        self.assertEqual(llm.llm_guard(t, {"from": "無い", "to": "x", "confidence": 0.9}, [], names), "notInRow")
        self.assertEqual(llm.llm_guard(t, {"from": "ラミー", "to": "ラミィ", "confidence": 0.1}, [], names), "lowConfidence")
        self.assertEqual(llm.llm_guard(t, {"from": "好き", "to": "とても大好きです", "confidence": 0.9}, [], names), "length")
        self.assertEqual(llm.llm_guard("言ってみるか", {"from": "みるか", "to": "ポルカ", "confidence": 0.9}, [], names), "newName")
        rows = [_seg(i, "あいう") for i in range(10)]
        keep, drop = llm.llm_cap([(0, {"from": "あ", "to": "か", "confidence": 0.9}), (1, {"from": "あ", "to": "か", "confidence": None})], len(rows))
        self.assertEqual(([i for i, _ in keep], len(drop)), ([0], 1))
        llm.llm_apply(rows, keep)
        self.assertEqual((rows[0]["text"], rows[0]["fill"], rows[0]["flag"]), ("かいう", {"from": "あいう", "by": "llm"}, llm.LLM_FLAG))
        self.assertTrue(llm.LLM_FLAG.startswith("名簿の呼び名に直した"))   # 画面の「戻す」(app.js の unfill)が同じ規則で印を外す

    def test_run_records_and_skips_ask_without_picks(self):
        doc = {"title": "配信_雪花ラミィ"}
        asked = []

        def ask(messages):
            asked.append(messages)
            return json.dumps({"edits": [{"from": "ラミーちゃん", "to": "ラミィちゃん", "confidence": 0.95}, {"from": "好き", "to": "大嫌いだよね", "confidence": 0.9}]})
        rows = [_seg(0, "生き花ラミーちゃんが好き")] + [_seg(i, "行") for i in range(1, 10)]
        rec = llm.llm_run(rows, MEMBERS, doc, ask)
        self.assertEqual((rec["picked"], rec["proposed"], rec["applied"], rec["rejected"]), (1, 2, 1, {"length": 1}))
        self.assertEqual(rows[0]["text"], "生き花ラミィちゃんが好き")
        self.assertEqual([it["rejected"] for it in rec["items"]], [None, "length"])
        asked.clear()
        llm.llm_run([_seg(0, "こんにちは")], MEMBERS, doc, ask)
        self.assertEqual(asked, [])


class TestLlmLearn(unittest.TestCase):
    def test_learn_events_skip_postfix_rows(self):
        doc = {"original": [{"start": 0, "end": 2, "text": "ラミーちゃん来た"}, {"start": 3, "end": 5, "text": "トーイ様"}],
               "segments": [_seg(0, "ラミィちゃん来た", end=2, fill={"from": "ラミーちゃん来た", "by": "llm"}, proofed=True),
                            _seg(3, "トワ様", end=5, proofed=True)]}
        ev = ed_learn.learn_events(doc)
        self.assertTrue(ev and all("ラミ" not in w and "ラミ" not in r for w, r, *_ in ev), ev)   # LLM が直した行は覚えない
        self.assertTrue(any("ト" in w for w, *_ in ev), ev)                                     # 人が直した行は今までどおり


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestLlmJob(StoreDir):
    REPLY = json.dumps({"edits": [{"from": "テスト文", "to": "テスト分", "confidence": 0.9}]})

    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.video = make_video(os.path.join(cls.src_dir, "テスト分の配信.mp4"))   # 題名に呼び名「テスト分」= 名簿のメンバーが出る文書。疑似の行は「テスト文n」

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        roster = os.path.join(self.tmp, "roster.json")
        write_json(roster, {"groups": [{"id": "t", "label": "試し", "names": ["テスト分子"]}], "members": [{"name": "テスト分子", "aliases": ["テスト分"]}]})
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off",
                                                "TRANSCRIBE_FAKE_FILL": "", "TRANSCRIBE_FAKE_LLM": self.REPLY})
        self.env.start()
        self.roster = mock.patch.object(ed_state, "ROSTER", roster)
        self.roster.start()
        self.mine = set()

    def tearDown(self):
        self.roster.stop()
        self.env.stop()
        with ed_jobs._jobs_lock:
            for k in list(ed_jobs._jobs):
                if k in self.mine or (ed_jobs._jobs[k].get("spec") or {}).get("sourcePath") == self.video:
                    ed_jobs._jobs.pop(k, None)
        super().tearDown()

    def transcribe(self, **req):
        job = ed_jobs.add_job(ed_jobs.validate_job(dict({"sourcePath": self.video, "model": "small", "autoFill": False}, **req)))
        self.mine.add(job["id"])
        ed_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def test_job_fixes_names_and_records(self):
        job = self.transcribe()
        doc = ed_store.read_transcript(job["tid"])
        segs = doc["segments"]
        self.assertEqual(segs[0]["text"], "テスト分1")   # 3 行のうち 15% = 1 行まで
        self.assertEqual(segs[0]["fill"], {"from": "テスト文1", "by": "llm"})
        self.assertTrue(segs[0]["flag"].startswith(llm.LLM_FLAG))
        self.assertEqual([g["text"] for g in segs[1:]], ["テスト文2", "テスト文3"])
        self.assertEqual([o["text"] for o in doc["original"]], ["テスト文1", "テスト文2", "テスト文3"])   # 機械の出力は変えない
        run = doc["recognition"]["runs"][0]
        self.assertEqual(run["llm"], {"engine": "llama-text", "model": "qwen3-8b", "picked": 3, "proposed": 3, "applied": 1, "rejected": {"cap": 2}})
        self.assertIs(doc["params"]["autoLlm"], True)
        raw = llm.read_llm(job["tid"])
        self.assertEqual([it["rejected"] for it in raw["items"]], [None, "cap", "cap"])
        # 保存しても fill は残る・文書を消すと llm.json も消える
        saved = ed_store.sanitize_transcript(dict(doc), doc)
        self.assertEqual(saved["segments"][0]["fill"], {"from": "テスト文1", "by": "llm"})
        self.assertTrue(os.path.exists(llm.llm_path(job["tid"])))

    def test_no_picks_does_not_load_llm(self):
        other = os.path.join(self.tmp, "roster2.json")
        write_json(other, {"groups": [{"id": "t", "label": "試し", "names": ["別の人"]}], "members": [{"name": "別の人", "aliases": ["べつのひと"]}]})
        called = []
        with mock.patch.object(ed_state, "ROSTER", other), mock.patch.object(llm, "llm_ask_fn", side_effect=lambda job, spec: called.append(1)):
            job = self.transcribe()
        doc = ed_store.read_transcript(job["tid"])
        self.assertEqual((doc["recognition"]["runs"][0]["llm"]["picked"], called), (0, []))   # 名簿の人が出ない文書 = 選んだ所なし = LLM を読み込まない
        self.assertFalse(os.path.exists(llm.llm_path(job["tid"])))

    def test_failure_keeps_transcript(self):
        def boom(job, spec):
            raise ed_state.ApiError("engine_failed", "llama-server が起動の途中で止まりました", 500)
        with mock.patch.object(llm, "llm_ask_fn", side_effect=boom):
            job = self.transcribe()
        doc = ed_store.read_transcript(job["tid"])
        self.assertEqual([g["text"] for g in doc["segments"]], ["テスト文1", "テスト文2", "テスト文3"])
        self.assertIn("llama-server", doc["recognition"]["runs"][0]["llm"]["error"])
        self.assertTrue(any("LLM" in w for w in job.get("warnings") or []), job.get("warnings"))

    def test_setting_and_eval_set(self):
        job = self.transcribe(autoLlm=False)
        doc = ed_store.read_transcript(job["tid"])
        self.assertEqual((doc["segments"][0]["text"], doc["params"]["autoLlm"]), ("テスト文1", False))
        self.assertNotIn("llm", doc["recognition"]["runs"][0])
        self.assertTrue(ed_jobs.validate_job({"sourcePath": self.video, "model": "small"})["autoLlm"])
        write_json(ed_state.SETTINGS, {"autoLlm": False})
        self.assertFalse(ed_jobs.validate_job({"sourcePath": self.video, "model": "small"})["autoLlm"])
        self.assertFalse(ed_jobs.validate_job({"sourcePath": self.video, "model": "small", "autoLlm": True, "evalSet": True})["autoLlm"])


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

    def test_fake_and_no_audio(self):
        with mock.patch.object(E.LlamaText, "FAKE_REPLY", '{"edits": []}'):
            e = E.LlamaText.create("qwen3-8b", "vulkan", "int8")
        self.assertEqual(e.complete([{"role": "user", "content": "x"}]), '{"edits": []}')
        with self.assertRaises(E.EngineError):
            e.transcribe("a.wav")

    def test_worker_op_complete(self):
        model = types.SimpleNamespace(complete=lambda msgs, n: "答え:%d:%d" % (len(msgs), n))
        m = {"name": "qwen3-8b", "device": "vulkan", "engine": "llama-text", "messages": [{"role": "user", "content": "x"}], "max_tokens": 50}
        # ワーカーは読み込んだモデルを worker_client._models から呼ぶたびに読む(S._models は同じ辞書。_model_used は差し替えて元に戻す)
        with mock.patch.dict(S._models, {("qwen3-8b", "vulkan", "llama-text"): model}, clear=True), mock.patch.object(S, "_model_used", [0]), \
                mock.patch.object(S, "_load_model_local", None):
            self.assertEqual(W._op_complete(m, 1, {}, None, set()), {"content": "答え:1:50"})
            with self.assertRaises(ed_state.ApiError):
                W._op_complete(dict(m, messages=[{"role": "tool", "content": "x"}]), 1, {}, None, set())
            with self.assertRaises(ed_state.ApiError):
                W._op_complete(dict(m, engine="faster-whisper"), 1, {}, None, set())


if __name__ == "__main__":
    unittest.main()
