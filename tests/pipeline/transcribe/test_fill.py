#!/usr/bin/env python3
"""文字起こしのジョブの後処理(B 頭の名前・E LLM・配信ごとの文脈。A・C・D は 11-01 に消した)を ③ の run_job で 1 回通し、文書と記録に残る形を確かめるテスト。test_metrics から読み込まれる。

    py -3.12 -m unittest tests/eval/drill/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest test_fill -q                        # これだけ(tests/editor で)

- ジョブの通し(疑似の認識 TRANSCRIBE_BACKEND=fake の行を差し替え + TRANSCRIBE_FAKE_LLM): 行が置き換わり fill と印・
  記録 recognition.runs[].names・llm・settings.context・<id>.llm.json・<id>.asr.json・params・保存で fill が残る・評価用は後処理も文脈も使わない
- 規則の答え(行の並びの見本)は tests/pipeline/transcribe/test_postproc.py、本物の LLM の通しは test_fill_llm.py
- ここに残す単体: sherpa-onnx の Haas(声の材料)のエンジンの表とトークン
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS))), "src", "editor"))
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "editor"))   # test_backend・test_edit(編集のサーバーを一時フォルダで動かす道具)
from test_backend import StoreDir, write_json  # noqa: F401,E402  (S = serve)
from ytt import workdata as _workdata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402
from pipeline.transcribe import fill, separate  # noqa: E402
from pipeline.transcribe import llm  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from human.proof import store  # noqa: E402
from pipeline.transcribe import records  # noqa: E402
from pipeline.transcribe import models  # noqa: E402
from flow import jobs  # noqa: E402
from pipeline.transcribe import tx_engines as E  # noqa: E402
from eval.fake import fake_asr  # noqa: E402  (疑似の認識)
from ytt import studiodata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))


def _fake_rows(job, spec, wav, total):
    """疑似の認識の行: 頭の名前(B)・名簿の呼び名の 1 字違い(E)"""
    job["state"] = "running"
    yield {"start": 0.0, "end": 4.0, "text": "テスト文1", "avg_logprob": -0.3}
    yield {"start": 4.5, "end": 6.0, "text": "リリー:テスト文2", "avg_logprob": -0.3}
    yield {"start": 6.5, "end": 8.5, "text": "テスト文3", "avg_logprob": -0.3}


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestFillJobRun(StoreDir):
    REPLY = json.dumps({"edits": [{"from": "テスト文", "to": "テスト分", "confidence": 0.9}]})

    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.src_dir, "テスト分子 雑談"))
        cls.video = testkit.make_video(os.path.join(cls.src_dir, "テスト分子 雑談", "テスト分の配信.mp4"), 9)   # フォルダの名前 = 配信ごとの文脈・題名の呼び名 = LLM の出る人

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        path = os.path.join(self.tmp, "roster.json")
        write_json(path, {"groups": [{"id": "t", "label": "試し", "names": ["テスト分子"]}], "members": [{"name": "テスト分子", "aliases": ["テスト分"]}]})
        self.enterContext(mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off",
                                                       "TRANSCRIBE_FAKE_LLM": self.REPLY}))
        for mod, name, value in ((roster, "ROSTER", path), (studiodata, "studio_stream", lambda vid: None), (fake_asr, "transcribe_fake", _fake_rows)):
            self.enterContext(mock.patch.object(mod, name, value))
        self.mine = set()
        self.addCleanup(self._drop_jobs)

    def _drop_jobs(self):
        with jobs._jobs_lock:
            for k in list(jobs._jobs):
                if k in self.mine or (jobs._jobs[k].get("spec") or {}).get("sourcePath") == self.video:
                    jobs._jobs.pop(k, None)

    def transcribe(self, **req):
        job = jobs.add_job(doc_jobs.validate_job(dict({"sourcePath": self.video, "model": "small", "autoGloss": False}, **req)))
        self.mine.add(job["id"])
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def test_job_post_processing_is_recorded(self):
        job = self.transcribe(autoContext=True, glossary="ホロライブ", autoLlm=True)
        doc = store.read_transcript(job["tid"])
        segs = doc["segments"]
        self.assertEqual([(g["start"], g["end"], g["text"]) for g in segs], [(0.0, 4.5, "テスト分1"), (4.5, 6.5, "テスト文2"), (6.5, 8.5, "テスト文3")])   # 続いている行はつなぐ
        self.assertEqual([g.get("fill") for g in segs], [{"from": "テスト文1", "by": "llm"}, {"from": "リリー:テスト文2", "by": "name"}, None])   # 後処理 B の行は LLM に選ばれない
        self.assertEqual([g["flag"].split("(")[0] for g in segs], [llm.LLM_FLAG.split("(")[0], fill.FILL_SPK_FLAG.split("(")[0], ""])
        run = doc["recognition"]["runs"][0]
        self.assertEqual(run["fill"], {"dropped": {"n": 0, "db": -separate.SEP_DB, "rows": []}})   # 2 つ目の読み(A・C・D)は 11-01 に消した。残るのは dropSilent の記録だけ(疑似は全部が声)
        self.assertEqual((run["names"], run["llm"]), (1, {"engine": "llama-text", "model": "qwen3-8b", "picked": 2, "proposed": 2, "applied": 1, "rejected": {"cap": 1}, "gloss": 0}))
        self.assertEqual({k: doc["params"][k] for k in ("autoFill", "stripNames", "autoLlm")}, {"autoFill": True, "stripNames": True, "autoLlm": True})
        self.assertEqual(doc["params"]["context"], {"members": [{"name": "テスト分子", "from": ["title"]}], "terms": 2})   # 動画のフォルダの名前から
        self.assertEqual(run["settings"]["context"], ["テスト分子"])
        self.assertNotIn("evalSet", doc)
        self.assertEqual([o["text"] for o in doc["original"]], ["テスト文1", "テスト文2", "テスト文3"])   # 機械の出力 = B のあと・LLM の前
        self.assertEqual([a["text"] for a in testkit.read_json(records.asr_path(job["tid"]))["segments"]],
                         ["テスト文1", "リリー:テスト文2", "テスト文3"])   # whisper の生の結果
        self.assertEqual([it["rejected"] for it in llm.read_llm(job["tid"])["items"]], [None, "cap"])
        # 保存しても fill は残る(画面の「別の読み」の札で戻せる)。形の違う fill は捨てる
        saved = store.sanitize_transcript(dict(doc, segments=[dict(segs[0]), dict(segs[2], fill="x")]), doc)
        self.assertEqual([g.get("fill") for g in saved["segments"]], [{"from": "テスト文1", "by": "llm"}, None])

    def test_settings_and_eval_set(self):
        """設定 autoFill・autoLlm・stripNames(autoLlm だけ既定オフ): 要求が優先・保存した設定・評価用は全部オフ(用語集・文脈・辞書・学習も)"""
        base = {"sourcePath": self.video, "model": "small"}
        v = doc_jobs.validate_job(base)
        self.assertEqual((v["autoFill"], v["autoLlm"], v["stripNames"], v["context"]), (True, False, True, {"members": [], "terms": []}))   # 配信ごとの文脈は既定オフ
        self.assertEqual((v["dropSilent"], v["endSnap"]), (True, False))   # 編集の画面から頼んでも声の無い行を捨てる(束の既定と同じ。Haas の変更の一覧 0-5)
        self.assertFalse(doc_jobs.validate_job(dict(base, evalSet=True))["dropSilent"])   # 評価用には当てない
        write_json(_workdata.SETTINGS, {"autoFill": False, "autoLlm": False})
        v = doc_jobs.validate_job(base)
        self.assertEqual((v["autoFill"], v["autoLlm"]), (False, False))
        self.assertTrue(doc_jobs.validate_job(dict(base, autoFill=True))["autoFill"])
        write_json(_workdata.SETTINGS, {})
        job = self.transcribe(autoContext=True, glossary="ホロライブ", evalSet=True, autoDict=True, autoLearned=True, autoFill=True, autoLlm=True)
        d = store.read_transcript(job["tid"])
        self.assertIs(d["evalSet"], True)
        self.assertEqual({k: d["params"][k] for k in ("glossary", "context", "autoDict", "autoLearned", "autoFill", "autoLlm", "stripNames")},
                         {"glossary": [], "context": None, "autoDict": False, "autoLearned": False, "autoFill": False, "autoLlm": False, "stripNames": False})
        run = d["recognition"]["runs"][0]
        self.assertEqual((run["settings"]["promptChars"], [k for k in ("fill", "names", "llm") if k in run]), (0, []))
        self.assertEqual([g["text"] for g in d["segments"]], ["テスト文1", "リリー:テスト文2", "テスト文3"])


class TestHaasEngine(unittest.TestCase):
    """Haas-ja(誰の声の材料の文字起こし。10-31): 登録・取得先の固定・バイトのトークンを字に戻す・区切りの 1 行(words つき)"""
    def test_registered(self):
        self.assertTrue(E.valid("haas") and E.Haas.valid_model("haas-ja-v1.0") and not E.Haas.valid_model("large-v3"))
        self.assertEqual((E.Haas.device_order("auto", True), E.Haas.light), (["cpu"], False))
        for f in E.HAAS_MODELS["haas-ja-v1.0"]["files"]:
            self.assertTrue(f["url"].startswith("https://huggingface.co/oboroge0/Haas-ja-v1.0-onnx/resolve/") and len(f["sha256"]) == 64)

    def test_segment_from_tokens(self):
        # 「日」= E6 97 A5 のバイトのトークン 3 つ → 1 字。時刻は最初のバイト・長さはバイトの和
        toks = ["▁今", "<0xE6>", "<0x97>", "<0xA5>", "は", "<0xFF>"]
        s = E.haas_segment(toks, [0.0, 0.3, 0.32, 0.34, 0.6, 0.9], [0.2, 0.02, 0.02, 0.02, 0.2, 0.1], [-0.1, -0.2, -0.2, -0.2, -0.1, -0.5], 10.0)
        self.assertEqual(s.text, "今日は")   # 字にならないバイト(<0xFF>)は捨てる
        self.assertEqual([(w.start, w.end, w.word) for w in s.words], [(10.0, 10.2, "今"), (10.3, 10.36, "日"), (10.6, 10.8, "は")])
        self.assertEqual((s.start, s.end, round(s.avg_logprob, 3)), (10.0, 10.8, -0.267))
        self.assertIsNone(E.haas_segment([], [], [], [], 0.0))


if __name__ == "__main__":
    unittest.main()
