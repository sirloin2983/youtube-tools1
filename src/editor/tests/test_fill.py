#!/usr/bin/env python3
"""認識のあとの後処理 A・B・C・D(pipeline/transcribe/fill.py。旧 src/editor/ed_fill.py。10-08 の実験ループ。編集 0.60.0。B = 行の頭の話者名は 0.67.0)のテスト。test_metrics から読み込まれる。

    py -3.10 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest test_fill -q                        # これだけ(src/editor/tests で)

- 純粋な関数: 文字の少ない行の見分け・窓の読みでの置き換え(3 倍の条件・印と元の文字)・末尾の重複・定型の幻覚と声の区間・名簿の呼び名の 1 字違い
- ジョブ(疑似の認識 TRANSCRIBE_BACKEND=fake + TRANSCRIBE_FAKE_FILL): 行が置き換わり fill と印が付く・記録 recognition.runs[].fill・設定 autoFill(既定オン・評価用はオフ)・保存で fill が残る
- エンジン: SenseVoice の登録(light)・トークンの時刻からの行・偽(FAKE_TEXT)・小さいモデルは主のモデルを手放さない
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, StoreDir, write_json  # noqa: F401,E402  (S = serve)
from test_alt import make_video  # noqa: E402
from pipeline.transcribe import fill  # noqa: E402  (RS2-9 から持ち主 pipeline/transcribe/fill.py を直に読む。旧 ed_fill)
import ed_jobs  # noqa: E402
import ed_store  # noqa: E402
from pipeline.transcribe import tx_engines as E  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))
LONG = "これは別の読みで埋めた長い文です"   # 16 字(テスト文n の 5 字の 3 倍以上)


def _row(a, b, text, **kw):
    return dict({"start": a, "end": b, "text": text, "words": [], "avg_logprob": -0.3, "no_speech_prob": 0.1, "compression_ratio": 1.2}, **kw)


class TestFillPure(unittest.TestCase):
    def test_sparse_row(self):
        self.assertTrue(fill.fill_sparse_row(_row(0, 4, "テスト文1")))                     # 5 字 / 4 秒 = 1.25 < 1.5
        self.assertFalse(fill.fill_sparse_row(_row(0, 1.5, "テスト文1")))                  # 2 秒未満
        self.assertFalse(fill.fill_sparse_row(_row(0, 4, "これは十分に長い文字の行です")))     # 3.5 字/秒
        self.assertTrue(fill.fill_sparse_row(_row(0, 2, "うわああああああああああああ")))        # 繰り返しで 3 字に縮む(密度は高い)
        self.assertFalse(fill.fill_sparse_row(_row(0, 2, "ああいいううええおお")))             # 2 回の繰り返しは縮めない
        self.assertFalse(fill.fill_sparse_row({"start": "x", "end": 1, "text": "a"}))
        self.assertEqual((fill.fill_chars("うわああああ!!"), fill.fill_norm("A B、c。")), (3, "ABc"))   # う・わ・あ(3 回以上の繰り返しは 1 字)

    def test_apply_replaces_only_when_three_times(self):
        r1, r2 = _row(0, 4, "テスト文1"), _row(4, 8, "これは十分に長い文字の行です")
        calls = []

        def read(s0, e0):
            calls.append((s0, e0))
            return [{"start": s0 + 0.2, "end": e0 - 0.2, "text": LONG}]
        out, st = fill.fill_apply([r1, r2], read, 8.0)
        self.assertEqual((st, calls), ({"windows": 1, "rows": 1, "added": 1}, [(0.0, 4.5)]))   # 窓は前後 0.5 秒(0 より前・total より後ろへは出ない)
        self.assertEqual([(x["start"], x["end"], x["text"]) for x in out], [(0.2, 4.3, LONG), (4, 8, "これは十分に長い文字の行です")])
        self.assertEqual(out[0]["fill"], {"from": "テスト文1", "by": "sense-voice"})
        self.assertNotIn("fill", out[1])
        # 字数が 3 倍未満・窓の読みが元の行の時間に半分も入らない → 置き換えない
        out, st = fill.fill_apply([r1], lambda s0, e0: [{"start": s0, "end": e0, "text": "短い文です"}], 8.0)
        self.assertEqual((st["rows"], out[0]["text"]), (0, "テスト文1"))
        out, st = fill.fill_apply([r1], lambda s0, e0: [{"start": 3.9, "end": 4.5, "text": LONG}], 8.0)
        self.assertEqual((st["rows"], out[0]["text"]), (0, "テスト文1"))
        out, st = fill.fill_apply([r1], lambda s0, e0: [], 8.0)
        self.assertEqual((st, out[0]["text"]), ({"windows": 1, "rows": 0, "added": 0}, "テスト文1"))

    def test_clean_tail(self):
        rows = [_row(0, 3, "今日はいい天気ですね"), _row(3, 4, "いい天気ですね"), _row(4, 5, "ですね"), _row(5, 6, "いい天気ですね")]
        out, n = fill.fill_clean_tail(rows)
        self.assertEqual(([r["text"] for r in out], n), (["今日はいい天気ですね", "ですね", "いい天気ですね"], 1))   # 6 字未満・前の行の末尾でない行は残す

    def test_clean_turns(self):
        seg = [{"id": "s1", "start": 10, "end": 12, "text": "ご視聴ありがとうございました", "speaker": "", "flag": ""},
               {"id": "s2", "start": 0, "end": 2, "text": "ご視聴ありがとうございました", "speaker": "", "flag": ""},
               {"id": "s3", "start": 20, "end": 22, "text": "ご視聴ありがとうございました", "speaker": "", "flag": "", "proofed": True},
               {"id": "s4", "start": 30, "end": 32, "text": "ご視聴ありがとうございました", "speaker": "", "flag": ""},
               {"id": "s5", "start": 40, "end": 42, "text": "こんばんは", "speaker": "", "flag": ""}]
        orig = [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in seg]
        orig[3]["text"] = "ご視聴ありがとう"   # s4 は人(か辞書)が直した行
        doc = {"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig}
        turns = [(0.0, 5.0, 0), (39.0, 45.0, 1)]   # 声があるのは 0〜5 秒と 39〜45 秒(wav の秒。offset 0)
        self.assertEqual(fill.fill_clean_turns(doc, turns, 0.0), 1)
        self.assertEqual([g["id"] for g in doc["segments"]], ["s2", "s3", "s4", "s5"])   # 声の中・校正済み・直した行・普通の文は残す
        doc2 = {"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig, "evalSet": True}
        self.assertEqual(fill.fill_clean_turns(doc2, turns, 0.0), 0)
        doc3 = {"params": {}, "segments": [dict(g) for g in seg], "original": orig}
        self.assertEqual(fill.fill_clean_turns(doc3, turns, 0.0), 0)
        doc4 = {"params": {"autoFill": True}, "segments": [dict(g) for g in seg], "original": orig}
        self.assertEqual(fill.fill_clean_turns(doc4, [(0.0, 5.0, 0)], 10.0), 1)   # offset で声の区間が 10〜15 秒 = s1 は声の中・s2 が声の外
        self.assertEqual([g["id"] for g in doc4["segments"]], ["s1", "s3", "s4", "s5"])

    def test_aliases(self):
        r = {"members": {"さくらみこ": {"aliases": ["みこ", "みこち"], "common": ["みこ"]}, "白上フブキ": {"aliases": ["フブキ", "フブ"], "common": []}}}
        self.assertEqual(fill.fill_aliases(r), {"さくらみこ", "みこち", "白上フブキ", "フブキ"})   # 3 字未満と common は入れない

    def test_agree(self):
        segs = [{"id": "s1", "start": 0, "end": 3, "text": "みこぢが来たよ", "speaker": "", "flag": "自信が低い"},
                {"id": "s2", "start": 3, "end": 6, "text": "みこちが来たよ", "speaker": "", "flag": ""},
                {"id": "s3", "start": 6, "end": 9, "text": "みこぢが来たよ", "speaker": "", "flag": "", "proofed": True},
                {"id": "s4", "start": 20, "end": 23, "text": "みこぢが来たよ", "speaker": "", "flag": ""},
                {"id": "s5", "start": 9, "end": 12, "text": "ミコチが来たよ", "speaker": "", "flag": ""}]
        others = [{"start": 0.2, "end": 12, "text": "みこちが来たよみこちが来たよ"}]
        n = fill.fill_agree(segs, others, {"みこち", "さくらみこ"})
        self.assertEqual(n, 1)
        self.assertEqual((segs[0]["text"], segs[0]["fill"], segs[0]["flag"]), ("みこちが来たよ", {"from": "みこぢが来たよ", "by": "sense-voice"}, "名簿の呼び名に直した(別のエンジンも同じ呼び名)、自信が低い"))
        self.assertEqual([g["text"] for g in segs[1:]], ["みこちが来たよ", "みこぢが来たよ", "みこぢが来たよ", "ミコチが来たよ"])   # 既にある・校正済み・時間が違う・かなの違いだけ は直さない
        self.assertEqual(fill.fill_agree(segs, [{"start": 0, "end": 3, "text": "こんばんは"}], {"みこち"}), 0)

    def test_strip_names(self):
        """B: 行の頭の「名前:」を外す(名簿・用語集の名前か、かな・カタカナだけの短い語。直後に本文があるときだけ)"""
        names = {"宝鐘マリン", "マリン"}
        split = fill.fill_spk_split
        self.assertEqual(split("リリー:ラデンだねぇ", names), ("ラデンだねぇ", "リリー:"))
        self.assertEqual(split(" リリー： もう一回言って", names), ("もう一回言って", " リリー： "))
        self.assertEqual(split("宝鐘マリン:ahoy", names), ("ahoy", "宝鐘マリン:"))
        self.assertEqual(split("マリン船長:ahoy", names)[1], None)               # 名簿に無い漢字まじり
        self.assertEqual(split("マリンさん:ahoy", names)[1], "マリンさん:")     # 敬称を除くと名簿の名前
        for text in ("結論:やらない", "12:30に集合", "リリー:", "リリー:!?", "とてもとても長いなまえです:はい", "Q:質問"):
            self.assertEqual(split(text, names), (text, None), text)
        rows = [_row(0, 2, "リリー:もう一回", _words=[[0, 0.3, "リ"], [0.3, 0.6, "リー"], [0.6, 0.7, ":"], [0.7, 2, "もう一回"]]),
                _row(2, 4, "テスト文2", fill={"from": "x", "by": "sense-voice"}), _row(4, 6, "ねえ:テスト文3", fill={"from": "y", "by": "sense-voice"})]
        out, n = fill.fill_strip_names({"stripNames": True, "glossary": ["マリン"]}, rows)
        self.assertEqual((n, [r["text"] for r in out]), (2, ["もう一回", "テスト文2", "テスト文3"]))
        self.assertEqual(out[0]["fill"], {"from": "リリー:もう一回", "by": "name"})
        self.assertEqual(out[0]["_words"], [[0.7, 2, "もう一回"]])                # 名前と「:」の単語は除く
        self.assertEqual(out[2]["fill"], {"from": "y", "by": "sense-voice"})     # 先に付いた元の文字は残す
        rows = [_row(0, 2, "リリー:もう一回")]
        self.assertEqual(fill.fill_strip_names({"stripNames": False}, rows), (rows, 0))
        self.assertEqual(rows[0]["text"], "リリー:もう一回")


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestFillJob(StoreDir):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.video = make_video(os.path.join(cls.src_dir, "v.mp4"))   # 9 秒 = 疑似の行 0〜4・4〜8(文字が少ない)・8〜9(2 秒未満)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off", "TRANSCRIBE_FAKE_FILL": LONG})
        self.env.start()
        self.mine = set()

    def tearDown(self):
        self.env.stop()
        with ed_jobs._jobs_lock:
            for k in list(ed_jobs._jobs):
                if k in self.mine or (ed_jobs._jobs[k].get("spec") or {}).get("sourcePath") == self.video:
                    ed_jobs._jobs.pop(k, None)
        super().tearDown()

    def transcribe(self, **req):
        job = ed_jobs.add_job(ed_jobs.validate_job(dict({"sourcePath": self.video, "model": "small"}, **req)))
        self.mine.add(job["id"])
        ed_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def test_job_fills_sparse_rows_and_records(self):
        job = self.transcribe()
        doc = ed_store.read_transcript(job["tid"])
        segs = doc["segments"]
        self.assertEqual([(g["start"], g["end"], g["text"]) for g in segs], [(0.0, 4.5, LONG), (3.5, 8.5, LONG), (8.0, 9.0, "テスト文3")])   # 窓 = 前後 0.5 秒
        self.assertEqual([g.get("fill") for g in segs], [{"from": "テスト文1", "by": "sense-voice"}, {"from": "テスト文2", "by": "sense-voice"}, None])
        self.assertTrue(all(g["flag"].startswith(fill.FILL_FLAG) for g in segs[:2]), [g["flag"] for g in segs])
        self.assertNotIn(fill.FILL_FLAG, segs[2]["flag"])
        run = doc["recognition"]["runs"][0]
        self.assertEqual(run["fill"], {"engine": "sense-voice", "windows": 2, "rows": 2, "added": 2, "dup": 0, "agree": 0})
        self.assertIs(doc["params"]["autoFill"], True)
        self.assertEqual([o["text"] for o in doc["original"]], [LONG, LONG, "テスト文3"])   # 機械の出力 = 後処理のあと(whisper の生の結果は asr.json)
        self.assertEqual([a["text"] for a in ed_jobs.read_asr(job["tid"])["segments"]], ["テスト文1", "テスト文2", "テスト文3"])
        # 保存しても fill は残る(画面の「別の読み」の札で戻せる)。形の違う fill は捨てる
        saved = ed_store.sanitize_transcript(dict(doc, segments=[dict(segs[0]), dict(segs[2], fill="x")]), doc)
        self.assertEqual([g.get("fill") for g in saved["segments"]], [{"from": "テスト文1", "by": "sense-voice"}, None])

    def test_no_reading_keeps_rows(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_FILL": ""}):
            job = self.transcribe()
        doc = ed_store.read_transcript(job["tid"])
        self.assertEqual([g["text"] for g in doc["segments"]], ["テスト文1", "テスト文2", "テスト文3"])
        self.assertEqual(doc["recognition"]["runs"][0]["fill"], {"engine": "sense-voice", "windows": 2, "rows": 0, "added": 0, "dup": 0, "agree": 0})

    def test_setting_and_eval_set(self):
        """設定 autoFill(既定オン): 要求が優先・保存した設定・評価用はオフ"""
        job = self.transcribe(autoFill=False)
        doc = ed_store.read_transcript(job["tid"])
        self.assertEqual(([g["text"] for g in doc["segments"]][0], doc["params"]["autoFill"]), ("テスト文1", False))
        self.assertNotIn("fill", doc["recognition"]["runs"][0])
        self.assertTrue(ed_jobs.validate_job({"sourcePath": self.video, "model": "small"})["autoFill"])
        write_json(S.SETTINGS, {"autoFill": False})
        self.assertFalse(ed_jobs.validate_job({"sourcePath": self.video, "model": "small"})["autoFill"])
        self.assertTrue(ed_jobs.validate_job({"sourcePath": self.video, "model": "small", "autoFill": True})["autoFill"])
        self.assertFalse(ed_jobs.validate_job({"sourcePath": self.video, "model": "small", "autoFill": True, "evalSet": True})["autoFill"])

    def test_job_strips_speaker_names(self):
        """B のジョブ: 「名前:」を外し、fill(by name)と印・記録 runs[].names・params.stripNames。設定でオフ・評価用はオフ"""
        orig = ed_jobs.expand_segments

        def named(gen, spec, *a, **kw):
            for i, r in enumerate(orig(gen, spec, *a, **kw)):
                yield dict(r, text="リリー:" + r["text"]) if i == 0 else r
        with mock.patch.object(ed_jobs, "expand_segments", named), mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_FILL": ""}):
            doc = ed_store.read_transcript(self.transcribe()["tid"])
            off = ed_store.read_transcript(self.transcribe(stripNames=False)["tid"])
        g = doc["segments"][0]
        self.assertEqual((g["text"], g["fill"]), ("テスト文1", {"from": "リリー:テスト文1", "by": "name"}))
        self.assertTrue(g["flag"].startswith(fill.FILL_SPK_FLAG), g["flag"])
        self.assertNotIn("fill", doc["segments"][1])
        self.assertEqual((doc["recognition"]["runs"][0]["names"], doc["params"]["stripNames"]), (1, True))
        self.assertEqual((off["segments"][0]["text"], off["params"]["stripNames"]), ("リリー:テスト文1", False))
        self.assertNotIn("names", off["recognition"]["runs"][0])
        self.assertTrue(ed_jobs.validate_job({"sourcePath": self.video, "model": "small"})["stripNames"])
        self.assertFalse(ed_jobs.validate_job({"sourcePath": self.video, "model": "small", "evalSet": True})["stripNames"])


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
        with mock.patch.object(E.SenseVoice, "FAKE_TEXT", "あいう"):
            e = E.SenseVoice.create("sense-voice-small", "cpu", "int8", data_dir=tempfile.gettempdir())
            segs, info = e.transcribe([0.0] * 32000, language="ja")
            self.assertEqual([(s.start, s.end, s.text) for s in segs], [(0.0, 2.0, "あいう")])
            self.assertEqual((info.language, info.duration, e.params()), ("ja", 2.0, ["language", "vad_filter", "vad_parameters", "word_timestamps"]))
        with mock.patch.object(E.SenseVoice, "FAKE_TEXT", ""):
            e = E.SenseVoice.create("sense-voice-small", "cpu", "int8")
            self.assertEqual(list(e.transcribe([0.0] * 16000)[0]), [])
        with self.assertRaises(E.EngineError):
            E.SenseVoice.create("large-v3", "cpu", "int8")

    def test_light_model_keeps_heavy_one(self):
        """小さいモデル(SenseVoice)を読んでも、主のモデル(faster-whisper など)は手放さない(文字起こしのたびに読み直さない)"""
        heavy = ("large-v3", "cpu", "faster-whisper")
        with mock.patch.dict(ed_jobs._models, {heavy: object()}, clear=True), mock.patch.object(E.SenseVoice, "FAKE_TEXT", "x"):
            m, dev = ed_jobs._load_model_local("sense-voice-small", {"cancel": False}, "cpu", engine="sense-voice")
            self.assertEqual((dev, set(ed_jobs._models)), ("cpu", {heavy, ("sense-voice-small", "cpu", "sense-voice")}))
            self.assertIs(ed_jobs._load_model_local("sense-voice-small", {"cancel": False}, "cpu", engine="sense-voice")[0], m)   # 2 回目は使い回す


if __name__ == "__main__":
    unittest.main()
