#!/usr/bin/env python3
"""文字起こしのジョブの後処理(A 別の読み・B 頭の名前・E LLM・配信ごとの文脈)を ③ の run_job で 1 回通し、文書と記録に残る形を確かめるテスト。test_metrics から読み込まれる。

    py -3.12 -m unittest tests/eval/drill/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest test_fill -q                        # これだけ(tests/editor で)

- ジョブの通し(疑似の認識 TRANSCRIBE_BACKEND=fake の行を差し替え + TRANSCRIBE_FAKE_FILL・TRANSCRIBE_FAKE_LLM): 行が置き換わり fill と印・
  記録 recognition.runs[].fill・names・llm・settings.context・<id>.llm.json・<id>.asr.json・params・保存で fill が残る・評価用は後処理も文脈も使わない
- 規則の答え(行の並びの見本)は tests/pipeline/transcribe/test_postproc.py、本物の SenseVoice・LLM の通しは test_fill_llm.py
- ここに残す単体: 声の区間の外の幻覚を捨てる fill_clean_turns(評価用・設定オフ・offset の別の道)・SenseVoice のエンジンの表とトークンの時刻・偽物・小さいモデル
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
from pipeline.transcribe import fill  # noqa: E402
from pipeline.transcribe import llm  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from human.proof import store  # noqa: E402
from pipeline.transcribe import records  # noqa: E402
from pipeline.transcribe import models  # noqa: E402
from flow import jobs  # noqa: E402
from pipeline.transcribe import tx_engines as E  # noqa: E402
from eval.fake import fake_asr, fake_worker  # noqa: E402  (疑似の認識・SenseVoice の偽物)
from ytt import studiodata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))
LONG = "これは別の読みで埋めた長い文です"   # 16 字(テスト文n の 5 字の 3 倍以上)


def _fake_rows(job, spec, wav, total):
    """疑似の認識の行: 文字の少ない行(A)・頭の名前(B)・名簿の呼び名の 1 字違い(E)"""
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
                                                       "TRANSCRIBE_FAKE_FILL": LONG, "TRANSCRIBE_FAKE_LLM": self.REPLY}))
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
        job = self.transcribe(autoContext=True, glossary="ホロライブ")
        doc = store.read_transcript(job["tid"])
        segs = doc["segments"]
        self.assertEqual([(g["start"], g["end"], g["text"]) for g in segs], [(0.0, 5.0, LONG), (4.5, 6.5, "テスト文2"), (6.5, 8.5, "テスト分3")])   # 続いている行はつなぐ・窓 = 前後 0.5 秒
        self.assertEqual([g.get("fill") for g in segs], [{"from": "テスト文1", "by": "sense-voice"}, {"from": "リリー:テスト文2", "by": "name"},
                                                         {"from": "テスト文3", "by": "llm"}])   # 後処理の行は LLM に選ばれない
        self.assertEqual([g["flag"].split("(")[0] for g in segs], [fill.FILL_FLAG.split("(")[0], fill.FILL_SPK_FLAG.split("(")[0], llm.LLM_FLAG.split("(")[0]])
        run = doc["recognition"]["runs"][0]
        self.assertEqual(run["fill"], {"engine": "sense-voice", "windows": 1, "rows": 1, "added": 1, "dup": 0, "agree": 0, "order": "AC"})
        self.assertEqual((run["names"], run["llm"]), (1, {"engine": "llama-text", "model": "qwen3-8b", "picked": 1, "proposed": 1, "applied": 1, "rejected": {}, "gloss": 0}))
        self.assertEqual({k: doc["params"][k] for k in ("autoFill", "stripNames", "autoLlm")}, {"autoFill": True, "stripNames": True, "autoLlm": True})
        self.assertEqual(doc["params"]["context"], {"members": [{"name": "テスト分子", "from": ["title"]}], "terms": 2})   # 動画のフォルダの名前から
        self.assertEqual(run["settings"]["context"], ["テスト分子"])
        self.assertNotIn("evalSet", doc)
        self.assertEqual([o["text"] for o in doc["original"]], [LONG, "テスト文2", "テスト文3"])   # 機械の出力 = A・B のあと・LLM の前
        self.assertEqual([a["text"] for a in testkit.read_json(records.asr_path(job["tid"]))["segments"]],
                         ["テスト文1", "リリー:テスト文2", "テスト文3"])   # whisper の生の結果
        self.assertEqual([(it["from"], it["to"], it["rejected"]) for it in llm.read_llm(job["tid"])["items"]], [("テスト文", "テスト分", None)])
        # 保存しても fill は残る(画面の「別の読み」の札で戻せる)。形の違う fill は捨てる
        saved = store.sanitize_transcript(dict(doc, segments=[dict(segs[0]), dict(segs[2], fill="x")]), doc)
        self.assertEqual([g.get("fill") for g in saved["segments"]], [{"from": "テスト文1", "by": "sense-voice"}, None])

    def test_settings_and_eval_set(self):
        """設定 autoFill・autoLlm・stripNames(既定オン): 要求が優先・保存した設定・評価用は全部オフ(用語集・文脈・辞書・学習も)"""
        base = {"sourcePath": self.video, "model": "small"}
        v = doc_jobs.validate_job(base)
        self.assertEqual((v["autoFill"], v["autoLlm"], v["stripNames"], v["context"]), (True, True, True, {"members": [], "terms": []}))   # 配信ごとの文脈は既定オフ
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


class TestCleanTurns(unittest.TestCase):
    def test_clean_turns(self):
        """定型の幻覚で声の区間(話者判別)と重ならない行を捨てる。声の中・校正済み・人が直した行・普通の文は残す。評価用・設定オフは何もしない・offset で動画の秒"""
        seg = [{"id": "s1", "start": 10, "end": 12, "text": "ご視聴ありがとうございました", "speaker": "", "flag": ""},
               {"id": "s2", "start": 0, "end": 2, "text": "ご視聴ありがとうございました", "speaker": "", "flag": ""},
               {"id": "s3", "start": 20, "end": 22, "text": "ご視聴ありがとうございました", "speaker": "", "flag": "", "proofed": True},
               {"id": "s4", "start": 30, "end": 32, "text": "ご視聴ありがとうございました", "speaker": "", "flag": ""},
               {"id": "s5", "start": 40, "end": 42, "text": "こんばんは", "speaker": "", "flag": ""}]
        orig = [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in seg]
        orig[3]["text"] = "ご視聴ありがとう"   # s4 は人(か辞書)が直した行
        turns = [(0.0, 5.0, 0), (39.0, 45.0, 1)]   # 声があるのは 0〜5 秒と 39〜45 秒(wav の秒。offset 0)
        doc = {"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig}
        self.assertEqual(fill.fill_clean_turns(doc, turns, 0.0), 1)
        self.assertEqual([g["id"] for g in doc["segments"]], ["s2", "s3", "s4", "s5"])
        for over in ({"evalSet": True}, {"params": {}}):
            self.assertEqual(fill.fill_clean_turns(dict({"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig}, **over), turns, 0.0), 0)
        doc4 = {"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig}
        self.assertEqual(fill.fill_clean_turns(doc4, [(0.0, 5.0, 0)], 10.0), 1)   # offset で声の区間が 10〜15 秒 = s1 は声の中・s2 が声の外
        self.assertEqual([g["id"] for g in doc4["segments"]], ["s1", "s3", "s4", "s5"])
        # 判別が無くても: 正弦波だけの音で whisper が書いた定型の文(単語の間で 3 行に分かれた)は、別の読みで読めなければ捨てる(10-23 配る前の検査)
        sine = [{"start": 0.0, "end": 1.87, "text": "ご"}, {"start": 1.87, "end": 9.35, "text": "視聴"}, {"start": 9.35, "end": 29.98, "text": "ありがとうございました"}]
        self.assertEqual(fill.fill_clean_read(sine, lambda a, b: []), ([], [{"start": r["start"], "end": r["end"], "text": r["text"]} for r in sine]))
        said = [{"start": 0.0, "end": 2.0, "text": "今日は"}, {"start": 2.1, "end": 4.0, "text": "ありがとうございました"}]
        self.assertEqual(fill.fill_clean_read(said, lambda a, b: [{"start": 2.0, "end": 4.0, "text": "ありがとうございました。"}])[0], said)   # 別の読みも同じ文 = 本当の声
        self.assertEqual(fill.fill_clean_read(said, lambda a, b: [])[0], said[:1])   # 定型の文だけの行だけを捨てる(前の行は残す)
        notes = sine + [{"start": 29.98, "end": 31.0, "text": "♪"}]
        self.assertEqual(fill.fill_clean_read(notes, lambda a, b: [])[0], notes[3:])   # 続く ♪ だけの行はつながない(字幕に出さない印に任せる)
        doc5 = {"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig}
        self.assertEqual(fill.fill_clean_turns(doc5, [], 0.0), 2)   # 声が 1 つも無い(BGM だけ)= 定型の文は声の外(10-23 f469fd で残っていた)
        self.assertEqual([g["id"] for g in doc5["segments"]], ["s3", "s4", "s5"])


class TestFillEdges(unittest.TestCase):
    def test_a_trims_neighbor_words(self):
        """A: 置き換えた行の尻が次の行の頭と同じ字(窓の余白で入った隣の言葉)は落とす・置き換えるかは落とす前の字数で決める・印 fill.trim。
        行の半分を超える重なり(同じ言葉の繰り返し)は落とさない。スイッチを切れば前の形(10-26 確かめるの答え)"""
        rows = [{"start": 0.0, "end": 2.0, "text": "これってどうしキャンス", "avg_logprob": -0.2},
                {"start": 2.1, "end": 5.0, "text": "ごめん", "avg_logprob": -0.2},
                {"start": 5.1, "end": 7.0, "text": "ごめんペコランチョ", "avg_logprob": -0.2}]
        read = lambda a, b: [{"start": 2.2, "end": 4.9, "text": "目押しが下たごめん"}]   # noqa: E731
        out, st = fill.fill_apply([dict(r) for r in rows], read, 10)
        self.assertEqual((out[1]["text"], out[1]["fill"]["trim"], st["rows"]), ("目押しが下た", {"tail": 3}, 1))
        with mock.patch.object(fill, "FILL_TRIM_EDGE", False):
            self.assertEqual(fill.fill_apply([dict(r) for r in rows], read, 10)[0][1]["text"], "目押しが下たごめん")
        same = fill.fill_trim_edges([{"text": "気持ちいい", "fill": {}}], {"text": "気持ちいい"}, None)
        self.assertEqual(same[0]["text"], "気持ちいい")

    def test_d_keeps_small_kana_variants(self):
        """D: 違う 1 字が小さい字(みこっち の っ)・置き換えると同じ字が並ぶ(みこち + ち)なら直さない(確かめるで「みこちち」が 3 件)。普通の 1 字違いは直す"""
        def run(t, o, al):
            g = [{"start": 0, "end": 3, "text": t}]
            return fill.fill_agree(g, [{"start": 0, "end": 3, "text": o}], al), g[0]["text"]
        self.assertEqual(run("ちょっと待ってみこっち", "ちょっと待ってみこち", ["みこち"]), (0, "ちょっと待ってみこっち"))
        self.assertEqual(run("ミコっち恵方巻き", "みこち恵方巻き", ["みこち"]), (0, "ミコっち恵方巻き"))
        self.assertEqual(run("すいちょんかわいい", "すいちゃんかわいい", ["すいちゃん"]), (1, "すいちゃんかわいい"))
        with mock.patch.object(fill, "FILL_AGREE_SMALL_SKIP", False):
            self.assertEqual(run("ちょっと待ってみこっち", "ちょっと待ってみこち", ["みこち"]), (1, "ちょっと待ってみこちち"))


class TestSenseVoiceEngine(unittest.TestCase):
    def test_registered(self):
        self.assertTrue(E.valid("sense-voice"))
        self.assertIs(E.get("sense-voice").light, True)
        self.assertIs(E.FasterWhisper.light, False)
        self.assertTrue(E.SenseVoice.valid_model("sense-voice-small"))
        self.assertFalse(E.SenseVoice.valid_model("../x"))
        self.assertEqual(E.SenseVoice.device_order("auto", True), ["cpu"])
        spec = E.SENSE_VOICE_MODELS["sense-voice-small"]
        self.assertTrue(spec["url"].startswith("https://github.com/k2-fsa/sherpa-onnx/"))
        self.assertEqual((spec["size"], len(spec["sha256"])), (163002883, 64))

    def test_rows_from_token_times(self):
        toks = ["<|ja|>", "<|NEUTRAL|>", "こ", "ん", "ば", "ん", "は", "。", "元", "気", "▁ok"]
        ts = [0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 2.0, 2.1, 2.2]
        rows = E.sv_rows(toks, ts, 10.0, 13.0)
        self.assertEqual([(round(a, 2), round(b, 2), t) for a, b, t in rows], [(10.1, 11.1, "こんばんは。"), (12.0, 12.7, "元気 ok")])   # 文末と 1 秒以上の間で分ける。終わり = 時刻 + 0.2 + 0.3
        self.assertEqual(E.sv_rows(["あ"] * 45, [i * 0.05 for i in range(45)], 0.0, 5.0)[0][2], "あ" * E.Q3_REPEAT_KEEP)   # 同じ字の繰り返しは縮める(q3_squash)
        self.assertEqual(len(E.sv_rows(["あ", "い"] * 25, [i * 0.05 for i in range(50)], 0.0, 5.0)), 2)   # 40 字で分ける

    def test_fake_engine(self):
        with mock.patch.dict(E.ENGINES, {E.SenseVoice.id: fake_worker.fake_sense_voice("あいう")}):   # 偽物は ⑤ fake_worker
            e = E.get("sense-voice").create("sense-voice-small", "cpu", "int8", data_dir=tempfile.gettempdir())
            segs, info = e.transcribe([0.0] * 32000, language="ja")
            self.assertEqual([(s.start, s.end, s.text) for s in segs], [(0.0, 2.0, "あいう")])
            self.assertEqual((info.language, info.duration, e.params()), ("ja", 2.0, ["language", "vad_filter", "vad_parameters", "word_timestamps"]))
        with mock.patch.dict(E.ENGINES, {E.SenseVoice.id: fake_worker.fake_sense_voice("")}):
            e = E.get("sense-voice").create("sense-voice-small", "cpu", "int8")
            self.assertEqual(list(e.transcribe([0.0] * 16000)[0]), [])
            with self.assertRaises(E.EngineError):
                E.get("sense-voice").create("large-v3", "cpu", "int8")

    def test_light_model_keeps_heavy_one(self):
        """小さいモデル(SenseVoice)を読んでも、主のモデル(faster-whisper など)は手放さない(文字起こしのたびに読み直さない)"""
        heavy = ("large-v3", "cpu", "faster-whisper")
        with mock.patch.dict(models._models, {heavy: object()}, clear=True), mock.patch.dict(E.ENGINES, {E.SenseVoice.id: fake_worker.fake_sense_voice("x")}):
            m, dev = models._load_model_local("sense-voice-small", {"cancel": False}, "cpu", engine="sense-voice")
            self.assertEqual((dev, set(models._models)), ("cpu", {heavy, ("sense-voice-small", "cpu", "sense-voice")}))
            self.assertIs(models._load_model_local("sense-voice-small", {"cancel": False}, "cpu", engine="sense-voice")[0], m)   # 2 回目は使い回す


if __name__ == "__main__":
    unittest.main()
