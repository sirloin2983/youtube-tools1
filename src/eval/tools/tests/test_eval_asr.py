"""src/eval/tools/eval_asr.py(文字起こしの精度を測る道具)のテスト。リポジトリ直下で:

    py -3.12 -m unittest src/eval/tools/tests/test_eval_asr.py

作業データは一時フォルダに作る(本物の作業データは読まない)。run は偽の認識(TRANSCRIBE_BACKEND=fake)で流れだけ確かめる(ffmpeg が必要)。
数字の計算・壊れた入力・作業データを壊さない・途中の失敗を確かめる。表示の文言は固定しない(数字は結果の鍵で見る)。
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import types
import unittest
import wave
from contextlib import redirect_stdout
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import eval_asr as E  # noqa: E402
from eval.fake import fake_asr  # noqa: E402
from pipeline.transcribe import postproc  # noqa: E402
from pipeline.transcribe import tx_engines as _tx_engines  # noqa: E402
from pipeline.transcribe import worker_client as _worker_client  # noqa: E402
from pipeline.transcribe import models as _txmodels  # noqa: E402
from pipeline.transcribe import backend as _backend  # noqa: E402
from ytt import workdata as _workdata  # noqa: E402
from ytt import testkit  # noqa: E402
from eval.drill import metrics as _metrics  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
POST_FW = {"clip": True, "mergeRepeats": True, "joinGap": 0.5}   # faster-whisper の行の後処理の印(editor の post_record と同じ値)


def seg(i, a, b, text, proofed=True, tags=None, flag="", **kw):
    g = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": flag, **kw}
    if proofed:
        g["proofed"] = True
    if tags:
        g["tags"] = tags
    return g


def silence_wav(path, sec):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * sec))


def quiet(fn, *a):
    with redirect_stdout(io.StringIO()):
        return fn(*a)


def ms(y, m, d, h=12):
    """この PC の時刻の日時 -> ミリ秒(--since・--until は日付をこの PC の時刻で読む)"""
    return int(datetime.datetime(y, m, d, h).timestamp() * 1000)


def pseg(i, a, b, text, at=None):
    """校正済みの行(proofedAt = 初めて校正済みにした時刻。at が None なら付けない)"""
    g = seg(i, a, b, text)
    if at is not None:
        g["proofedAt"] = at
    return g


def run_rec(engine="faster-whisper", model="large-v3", dict_=None, kind=None, beam=5, hint=False):
    r = {"engine": engine, "engineVersion": "1.0", "model": model, "device": "cpu", "language": "ja",
         "settings": {"beam": beam, "vadMode": "normal", "boost": False, "wordSplit": True, "glossaryChars": 5 if hint else 0, "promptChars": 0,
                      "context": [], "dict": dict_ or {}}}
    if kind:
        r["kind"] = kind
    return r


class Base(unittest.TestCase):
    """一時の作業データ(transcripts だけ)と、文書を書く・stored で数える・compare する口。環境変数は流し終わったら元に戻す"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, prefix="test_eval_asr_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        self.enterContext(mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_DELAY": "0"}))

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def reviewed_doc(self, tid, dur, heard="こんにちは", **kw):
        """確かめ済みの評価用の文書(正解は「こんにちは」。機械の出力が heard)"""
        self.write(tid, evalSet=True, evalReviewed={"at": 5, "rows": 1, "durationSec": dur, "via": "drill"},
                   segments=[seg(1, 10.0, 14.0, "こんにちは")], original=[{"start": 10.0, "end": 14.0, "text": heard}], **kw)

    def stored(self, *argv):
        return quiet(E.main, ["stored", "--data", self.data, "--no-save", *argv])

    def by_doc(self, res):
        return {d["id"]: d for d in res["summary"]["byDoc"]}

    def dump(self, name, obj):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return path

    def compare(self, a, b):
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = E.cmd_compare(a, b)
        return res, buf.getvalue()


class EvalAsrTest(Base):
    def setUp(self):
        super().setUp()
        # 評価用: 置換 1(祭り→まつり)・重なり・人が足した行(抜け)・人が消した行(余分)・未校正の行(数えない)
        self.write("aaaaaaaaaaa1", evalSet=True, segments=[
            seg(1, 0.0, 4.0, "まつりが来た"), seg(2, 4.0, 8.0, "二人で話す", tags=["overlap"]), seg(3, 20.0, 22.0, "足した行"),
            seg(4, 30.0, 34.0, "まだ見ていない", proofed=False)],
            original=[{"start": 0.0, "end": 4.0, "text": "祭りが来た"}, {"start": 4.0, "end": 8.0, "text": "二人で話す"},
                      {"start": 12.0, "end": 13.0, "text": "ご視聴ありがとうございました"}, {"start": 30.0, "end": 34.0, "text": "まだ見てない"}])
        self.write("bbbbbbbbbbb2", segments=[seg(1, 0.0, 2.0, "学習用")], original=[{"start": 0.0, "end": 2.0, "text": "学習よう"}])

    def snapshot(self):
        d = os.path.join(self.data, "transcripts")
        out = {}
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_stored_counts_like_the_screen(self):
        before = self.snapshot()
        res = self.stored()
        o = res["summary"]["overall"]
        self.assertEqual(res["meta"]["docs"], ["aaaaaaaaaaa1"])          # 既定は評価用だけ
        # 正解 = まつりが来た(6)+ 二人で話す(5)+ 足した行(4)= 15 字。祭り→まつり は置換 1・抜け 1(編集距離が最小の数え方)
        self.assertEqual(o["refChars"], 15)
        self.assertEqual(res["summary"]["byKind"]["両方にある"]["errs"], 2)
        self.assertEqual(res["summary"]["byKind"]["人が足した(抜け)"]["del"], 4)   # 人が足した行 = 抜け
        self.assertEqual(res["summary"]["byKind"]["人が消した(余分)"]["ins"], len("ご視聴ありがとうございました"))
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["refChars"], 5)
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["errs"], 0)
        self.assertTrue(all(g["start"] < 30 for g in res["groups"]))    # 未校正の行は数えない
        self.assertEqual(self.snapshot(), before)                       # 文書は書き換えない
        self.assertEqual(sorted(self.stored("--source", "all")["meta"]["docs"]), ["aaaaaaaaaaa1", "bbbbbbbbbbb2"])
        # 時刻によらない数え方: 数えたまとまりの文字を通しでつないで比べる。まとまりの数え方と同じ文字数・誤りはそれ以下
        dt = res["summary"]["docText"]
        self.assertEqual(dt["refChars"], 15)
        self.assertLessEqual(dt["sub"] + dt["del"] + dt["ins"], o["errs"])

    def test_doc_text_ignores_time_shift(self):
        """行の時刻がずれて文字が隣のまとまりへ移っても、時刻によらない数え方では誤りにならない"""
        E.C.prepare("fake")
        groups = [{"doc": "d", "start": 0.0, "ref": "あいう", "hyp": "あい"}, {"doc": "d", "start": 5.0, "ref": "えお", "hyp": "うえお"}]
        dt = E.doc_text(groups)
        self.assertEqual((dt["refChars"], dt["sub"], dt["del"], dt["ins"], dt["cer"]), (5, 0, 0, 0, 0.0))

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
    def test_run_recognizes_and_saves_without_touching_docs(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        src = os.path.join(self.tmp, "clip.wav")
        silence_wav(src, 12.0)
        # 偽の認識は 4 秒ごとに「テスト文N」を出す
        self.write("ccccccccccc3", evalSet=True, sourcePath=src, start=0, end=12,
                   segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2x"), seg(3, 8.0, 12.0, "テスト文3")], original=[])
        before = self.snapshot()
        res = quiet(E.main, ["run", "--data", self.data, "--docs", "ccccccccccc3", "--label", "fake-test"])
        o = res["summary"]["overall"]
        self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (16, 0, 1, 0))   # 「x」が抜けた 1 字だけ
        self.assertEqual(res["meta"]["engine"]["engine"], "fake")
        self.assertEqual(res["meta"]["perDoc"][0]["audio"], "動画")
        self.assertGreater(res["meta"]["audioSec"], 11)
        self.assertEqual(res["meta"]["post"], POST_FW)                   # 行の後処理の印
        self.assertEqual(self.snapshot(), before)                     # 文書は書き換えない
        saved = os.listdir(os.path.join(self.data, "evals", "asr"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].endswith("_fake-test.json"))
        # 元の動画が無ければ、保管データの全体の音声(文書の範囲の先頭 = 0 秒)で測る
        full = os.path.join(self.data, "dataset", "docs", "ccccccccccc3")
        os.makedirs(full)
        shutil.copy(src, os.path.join(full, "full.flac"))
        os.unlink(src)
        res2 = quiet(E.main, ["run", "--data", self.data, "--docs", "ccccccccccc3", "--no-save"])
        self.assertEqual(res2["meta"]["perDoc"][0]["audio"], "保管の音声")
        self.assertEqual(res2["summary"]["overall"]["errs"], 1)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
    def test_run_with_context(self):
        """--context auto = 文書の題名・配信のチャンネル名・コラボ相手(スタジオの data.json を TRANSCRIBE_STUDIO_DATA で読む)から出る人を決めて渡す。
        既定の none では渡さない"""
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        studio = self.dump("studio-data.json", {
            "videos": {"vidAAAAAAAAA": {"channel": "Miko Ch. さくらみこ", "title": "配信"}, "vidBBBBBBBBB": {"channel": "Pekora Ch. 兎田ぺこら", "title": "配信"}},
            "groups": {"g1": {"members": ["vidAAAAAAAAA", "vidBBBBBBBBB"]}}})
        os.environ["TRANSCRIBE_STUDIO_DATA"] = studio
        src = os.path.join(self.tmp, "clip.wav")
        silence_wav(src, 8.0)
        rows = [seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2")]
        self.write("ddddddddddd4", evalSet=True, title="教師データ＿さくらみこ01", sourcePath=src, start=0, end=8, segments=rows, original=[])
        self.write("dddddddddd08", evalSet=True, title="切り抜き", sourcePath=src, start=0, end=8, clip={"source": {"videoId": "vidAAAAAAAAA"}},
                   segments=rows, original=[])
        res = quiet(E.main, ["run", "--data", self.data, "--docs", "ddddddddddd4,dddddddddd08", "--context", "auto", "--no-save"])
        ctx = {d["id"]: d["context"] for d in res["meta"]["perDoc"]}
        self.assertEqual(ctx, {"ddddddddddd4": ["さくらみこ"], "dddddddddd08": ["さくらみこ", "兎田ぺこら"]})   # 題名 / チャンネル → コラボ相手
        self.assertEqual(res["meta"]["engine"]["context"], "auto")
        self.assertIn("みこち", res["terms"])                                          # 名前の再現率に呼び名も数える
        base = quiet(E.main, ["run", "--data", self.data, "--docs", "ddddddddddd4", "--no-save"])
        self.assertEqual((base["meta"]["perDoc"][0]["context"], base["meta"]["engine"]["context"]), ([], "none"))

    def test_prepare_uses_the_owner_modules(self):
        """C.prepare は入口(編集の serve)を読まず、持ち主のモジュールを直に使う。認識はこのプロセスの中で、スタジオの data.json は
        環境変数 TRANSCRIBE_STUDIO_DATA どおり、TRANSCRIBE_DATA_DIR は書き換えない"""
        studio = os.path.join(self.tmp, "data.json")
        data_dir = os.environ.get("TRANSCRIBE_DATA_DIR")
        before_mods = set(sys.modules)
        with mock.patch.dict(os.environ, {"TRANSCRIBE_STUDIO_DATA": studio}):
            E.C.prepare("fake")
            self.assertEqual(_workdata.STUDIO_DATA, studio)
        self.assertTrue(_worker_client.IN_WORKER)                                         # 認識はこのプロセスの中で(認識ワーカーを起動しない)
        self.assertEqual(os.environ.get("TRANSCRIBE_DATA_DIR"), data_dir)
        self.assertNotIn("tx_serve_for_eval", sys.modules)
        self.assertFalse({n for n in set(sys.modules) - before_mods if n.split(".")[-1] in ("serve", "ed_state")})

    def test_wav_slice_reaches_the_model_in_this_process(self):
        """editor のサーバー側の書き方は WavSlice・WavRef(認識ワーカーへ渡す形)をモデルに渡す。道具はモデルをこのプロセスの中で読む(IN_WORKER)ので、
        C.prepare の in_process_models がワーカーの受け口と同じく範囲のサンプルに直して渡す(faster-whisper はファイルの範囲を読めない)。モデルは偽物"""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy が無い")
        wav = os.path.join(self.tmp, "ramp.wav")
        with wave.open(wav, "wb") as w:   # サンプルの値 = 番号(どの範囲が届いたか分かるように)
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(np.arange(32000, dtype=np.int16).tobytes())
        got = []

        class Model:   # faster-whisper の WhisperModel と同じ形
            hooks = {}

            def params(self):
                return ["language", "beam_size", "condition_on_previous_text", "word_timestamps", "vad_filter", "no_speech_threshold"]

            def transcribe(self, audio, **kw):
                if not isinstance(audio, (str, np.ndarray)):
                    raise ValueError("File object has no read() method, or readable() returned False.")   # faster-whisper と同じ落ち方
                got.append(audio)
                word = types.SimpleNamespace(start=0.1, end=0.4, word="テスト", probability=0.9)
                row = types.SimpleNamespace(start=0.0, end=0.5, text="テスト", avg_logprob=-0.1, no_speech_prob=0.0, compression_ratio=1.0, words=[word])
                return iter([row]), types.SimpleNamespace(duration=1.0, language="ja")

        E.C.prepare("fake")
        local = _txmodels._load_model_local
        E.C.prepare("fake")   # 何回呼んでも包むのは 1 回(部品は同じもの)
        self.assertIs(_txmodels._load_model_local, local)
        fw = _tx_engines.FasterWhisper.id
        job = {"cancel": False, "phase": ""}
        with mock.patch.dict(_txmodels._models, {("small", "cpu", fw): Model()}, clear=True), mock.patch.object(_worker_client, "gpu_ready", lambda: False), \
                mock.patch.object(_backend, "is_fake", lambda: False):
            m, _dev = _worker_client.load_model("small", job, "cpu", engine=fw)
            segs, _info = m.transcribe(_worker_client.WavSlice(wav, 8000, 24000), language="ja")
            self.assertEqual([x.text for x in segs], ["テスト"])
            self.assertEqual(len(got), 1)
            self.assertIsInstance(got[0], np.ndarray)                                    # 範囲のサンプル(wav の 0.5〜1.5 秒)
            self.assertEqual(len(got[0]), 16000)
            self.assertAlmostEqual(float(got[0][0]) * 32768, 8000, places=3)
            self.assertEqual(m.transcribe(_worker_client.WavRef(wav))[0].__next__().text, "テスト")
            self.assertEqual(got[-1], wav)                                                # WavRef = wav のパスのまま
            m.hooks = {"x": 1}
            self.assertEqual(_txmodels._models[("small", "cpu", fw)].hooks, {"x": 1})             # 属性は中のモデルへ
            self.assertIn("word_timestamps", m.params())

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
    def test_run_temp0_reaches_the_model_in_this_process(self):
        """--temp0 が認識のモデルまで届く(temperature=0.0。付けなければ渡さない = faster-whisper の既定の温度のやり直し)。
        モデルはこのプロセスの中で読む(認識ワーカーを起動しない)。モデルは偽物に差し替える(本物は読まない)"""
        src = os.path.join(self.tmp, "clip.wav")
        silence_wav(src, 8.0)
        self.write("cccccccccc07", evalSet=True, sourcePath=src, start=0, end=8,
                   segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2")], original=[])
        calls = []

        class Model:   # faster-whisper の WhisperModel と同じ形(params = 受け付ける引数の名前)
            def params(self):
                return ["language", "beam_size", "condition_on_previous_text", "vad_filter", "vad_parameters", "no_speech_threshold",
                        "word_timestamps", "temperature", "initial_prompt", "hotwords"]

            def transcribe(self, audio, **kw):
                calls.append(kw)
                row = types.SimpleNamespace(start=0.0, end=4.0, text="テスト文1", avg_logprob=-0.1, no_speech_prob=0.0, compression_ratio=1.0, words=[])
                return iter([row]), types.SimpleNamespace(duration=8.0, duration_after_vad=8.0, language="ja")

        def no_worker(*a, **k):
            raise AssertionError("認識ワーカーを起動した(IN_WORKER が ed_jobs に届いていない)")
        E.C.prepare()   # main も同じ部品を使う
        with mock.patch.object(_txmodels, "_load_model_local", lambda *a, **k: (Model(), "cpu")), \
                mock.patch.object(_worker_client, "check_engine", lambda spec: None), mock.patch.object(_worker_client.WORKER, "call", no_worker), mock.patch.object(_worker_client.WORKER, "stream", no_worker):
            os.environ.pop("TRANSCRIBE_BACKEND", None)
            args = ["run", "--data", self.data, "--docs", "cccccccccc07", "--model", "small", "--vad", "off", "--no-save"]
            res = quiet(E.main, args + ["--temp0"])
            self.assertEqual(calls[-1].get("temperature"), 0.0)
            self.assertEqual((res["meta"]["engine"]["engine"], res["meta"]["engine"]["settings"]["temp0"]), ("faster-whisper", True))
            self.assertEqual(res["summary"]["overall"]["refChars"], 10)
            n = len(calls)
            quiet(E.main, args)
            self.assertEqual(len(calls), n + 1)
            self.assertNotIn("temperature", calls[-1])

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
    def test_recognize_doc_applies_row_post_processing(self):
        """本番(run_job)と同じ行の後処理を通す: 長さより後ろの行を捨てる・dur を expand_segments へ渡す・続いている行をつなぐ。
        行の後処理の印(meta.post)は持ち主(postproc)の今の値を写す"""
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        E.C.prepare("fake")
        src = os.path.join(self.tmp, "clip.wav")
        silence_wav(src, 8.0)
        doc = {"id": "eeeeeeeeeee5", "sourcePath": src, "start": 0, "end": 8}
        real = postproc.expand_segments
        calls = []

        def spy(gen, spec, dur=None, join=True):
            calls.append((dur, join))
            return real(gen, spec, dur, join=join)

        def fake(job, spec, wav, total):   # 8 秒の音声に、長さの外(100 秒)の行
            yield {"start": 0.0, "end": 4.0, "text": "中の行"}
            yield {"start": 100.0, "end": 104.0, "text": "外の行"}

        def spec_of(engine):
            a = types.SimpleNamespace(glossary=None, beam=0, model="small", engine=engine, vad=None, boost=None, device="auto", temp0=False)
            return dict(E.run_spec(a, {}, True), context={"members": []})
        with mock.patch.object(postproc, "expand_segments", spy), mock.patch.object(fake_asr, "transcribe_fake", fake):
            rows, audio_sec, _w, _where, _dev = E.recognize_doc(doc, spec_of("faster-whisper"), self.data)
            self.assertEqual([r["text"] for r in rows], ["中の行"])
            self.assertAlmostEqual(calls[-1][0], audio_sec)
            self.assertTrue(calls[-1][1])
            E.recognize_doc(doc, spec_of("whisper.cpp"), self.data)
            self.assertEqual(len(calls), 2)                                    # whisper.cpp も同じ整え方
        self.assertEqual(E.post_meta(spec_of("faster-whisper")), POST_FW)
        self.assertEqual(E.post_meta(spec_of("whisper.cpp")), dict(POST_FW, endTrim=0.0))   # 終わりを早める endTrim は whisper.cpp だけ
        with mock.patch.object(postproc, "END_TRIM", 0.1), mock.patch.object(postproc, "JOIN_GAP", 0.0):
            self.assertEqual(E.post_meta(spec_of("whisper.cpp")), {"clip": True, "mergeRepeats": True, "endTrim": 0.1, "joinGap": 0.0})

    def test_compare_notes_different_row_post_processing(self):
        """行の後処理の印(meta.post)が片方に無い・中身が違う結果どうしは、注意を出す(落ちない)。同じ・両方無いなら出さない"""
        a = self.stored()
        post = {"clip": True, "mergeRepeats": True}

        def variant(name, p):
            r = json.loads(json.dumps(a))
            if p is not None:
                r["meta"]["post"] = p
            return self.dump(name, r)
        cases = [(None, post, True), (dict(post, pullEnds=False, quantRetime=False, endTrim=0.0), post, True),   # 片方に無い / 今は無い鍵がある
                 (post, dict(post, pullEnds=True), True), (post, dict(post, joinGap=0.5), True),
                 (dict(post, joinGap=0.5), dict(post, joinGap=0.0), True),                                       # つなぐすき間が違う
                 (post, dict(post), False), (None, None, False)]
        for i, (x, y, want) in enumerate(cases):
            with self.subTest(i=i):
                res, out = self.compare(variant("x%d.json" % i, x), variant("y%d.json" % i, y))
                self.assertEqual(E.POST_NOTE in res["warnings"], want)
                self.assertEqual(res.get("postNote") == E.POST_NOTE, want)
                self.assertEqual(E.POST_NOTE in out, want)

    def test_compare_same_docs(self):
        quiet(E.main, ["stored", "--data", self.data, "--label", "a"])
        pa = os.path.join(self.data, "evals", "asr", sorted(os.listdir(os.path.join(self.data, "evals", "asr")))[0])
        with open(pa, encoding="utf-8") as f:
            a = json.load(f)
        same = quiet(E.cmd_compare, pa, pa)
        self.assertEqual(same["diff"], 0)
        self.assertIn("差があるとは言えない", same["verdict"])
        b = json.loads(json.dumps(a))   # 置換の誤りを直した結果
        for g in b["groups"]:
            g["sub"] = 0
        out = quiet(E.cmd_compare, pa, self.dump("b.json", b))
        self.assertLess(out["diff"], 0)                                   # B の方が誤りが少ない
        self.assertEqual(out["docs"], 1)


class EvalAsrSelectTest(Base):
    """時期で分ける・出どころ(評価用・普段)・下書きのエンジンの注意・エンジン別の集計・少ないデータ"""

    def setUp(self):
        super().setUp()
        orig = [{"start": 0.0, "end": 4.0, "text": "あいくお"}, {"start": 4.0, "end": 8.0, "text": "えお"}]   # 1 行目は「あいう」を聞き違えた
        # 評価用: 行ごとの proofedAt の最大が 09-10(最初の行は 09-01)/ proofedAt なしで updatedAt = 10-02
        self.write("eeeeeeeeee01", evalSet=True, segments=[pseg(1, 0, 4, "あいう", ms(2026, 9, 1)), pseg(2, 4, 8, "えお", ms(2026, 9, 10))],
                   original=orig, recognition={"runs": [run_rec()]})
        self.write("eeeeeeeeee02", evalSet=True, updatedAt=ms(2026, 10, 2), segments=[pseg(1, 0, 4, "あいう"), pseg(2, 4, 8, "えお")],
                   original=orig, recognition={"runs": [run_rec()]})
        # 普段: whisper.cpp(辞書の版 abc)・時期が分からない(updatedAt も無い)・途中で別のエンジンで認識し直した・同じ whisper.cpp で辞書の版だけ違う
        self.write("dddddddddd01", segments=[pseg(1, 0, 4, "あいう", ms(2026, 10, 3)), pseg(2, 4, 8, "えお", ms(2026, 10, 3))], original=orig,
                   recognition={"runs": [run_rec("whisper.cpp", "large-v3", {"glossary": "abc"})]})
        self.write("dddddddddd02", updatedAt=0, segments=[pseg(1, 0, 4, "あいう"), pseg(2, 4, 8, "えお")], original=orig)
        self.write("dddddddddd03", updatedAt=ms(2026, 8, 1), segments=[pseg(1, 0, 4, "あいう"), pseg(2, 4, 8, "えお")], original=orig,
                   recognition={"runs": [run_rec(), run_rec("whisper.cpp", kind="range")]})
        self.write("dddddddddd04", segments=[pseg(1, 0, 4, "あいう", ms(2026, 10, 4)), pseg(2, 4, 8, "えお", ms(2026, 10, 4))], original=orig,
                   recognition={"runs": [run_rec("whisper.cpp", "large-v3", {"glossary": "zzz"})]})

    def ids(self, res):
        return sorted(res["meta"]["docs"])

    # ---------------- 時期

    def test_doc_time_is_max_proofed_at_then_updated_at(self):
        d = {"segments": [pseg(1, 0, 1, "a", 100), pseg(2, 1, 2, "b", 300), pseg(3, 2, 3, "c")], "updatedAt": 999}
        for doc, want in ((d, (300, "proofedAt")),                                               # 行の proofedAt の最大
                          (dict(d, segments=[seg(1, 0, 1, "a")]), (999, "updatedAt")),           # 無ければ updatedAt
                          ({"segments": [seg(1, 0, 1, "a", proofed=False)]}, (None, "")),
                          ({"segments": [seg(1, 0, 1, "a", proofed=False, proofedAt=500)], "updatedAt": 7}, (7, "updatedAt"))):   # 校正済みでない行の proofedAt は数えない
            self.assertEqual(E.doc_time(doc), want)

    def test_since_until(self):
        every = ["dddddddddd01", "dddddddddd03", "dddddddddd04", "eeeeeeeeee01", "eeeeeeeeee02"]   # 時期が分からない dddddddddd02 は、時期の指定がなければ数える
        res = self.stored("--source", "all")
        self.assertEqual(self.ids(res), sorted(every + ["dddddddddd02"]))
        # --since: その日を含む。eeeeeeeeee01 は行の proofedAt の最大(09-10)で決まる(最初の行 09-01 ではない)
        res = self.stored("--source", "all", "--since", "2026-09-10")
        self.assertEqual(self.ids(res), ["dddddddddd01", "dddddddddd04", "eeeeeeeeee01", "eeeeeeeeee02"])
        self.assertEqual((res["meta"]["since"], res["meta"]["selection"]["unknownTime"], res["meta"]["selection"]["excludedByTime"]), ("2026-09-10", 1, 1))
        res = self.stored("--source", "all", "--since", "2026-09-11")
        self.assertNotIn("eeeeeeeeee01", self.ids(res))
        # --until: その日の終わりまで含む(updatedAt が 10-02 の昼でも 10-02 を含む)
        res = self.stored("--source", "all", "--until", "2026-10-02")
        self.assertEqual(self.ids(res), ["dddddddddd03", "eeeeeeeeee01", "eeeeeeeeee02"])
        res = self.stored("--source", "all", "--since", "2026-09-11", "--until", "2026-10-02")
        self.assertEqual(self.ids(res), ["eeeeeeeeee02"])
        self.assertEqual(self.stored("--source", "all", "--since", "2026-10-05")["meta"]["docs"], [])
        # 結果の「正解のデータの版」は選んだ文書で決まる(時期を変えれば別の正解 = compare が警告する)
        self.assertNotEqual(res["meta"]["dataFingerprint"], self.stored("--source", "all")["meta"]["dataFingerprint"])
        with self.assertRaises(SystemExit):
            self.stored("--since", "10/01")

    # ---------------- 出どころ

    def test_source_choices(self):
        ev, daily = ["eeeeeeeeee01", "eeeeeeeeee02"], ["dddddddddd01", "dddddddddd02", "dddddddddd03", "dddddddddd04"]
        for argv, want in (((), ev),                                               # 既定は評価用だけ
                           (("--source", "eval"), ev), (("--source", "daily"), daily), (("--source", "all"), sorted(daily + ev)),
                           (("--source", "daily", "--docs", "eeeeeeeeee01"), ["eeeeeeeeee01"])):   # --docs は出どころより優先
            self.assertEqual(self.ids(self.stored(*argv)), want, argv)
        src = {d["id"]: d["source"] for d in self.stored("--source", "all")["summary"]["byDoc"]}
        self.assertEqual((src["dddddddddd01"], src["eeeeeeeeee01"]), ("daily", "eval"))

    # ---------------- 下書きのエンジン

    def test_draft_bias_rules(self):
        ev_doc = {"_source": "eval", "recognition": {"runs": [run_rec()]}}
        daily = {"recognition": {"runs": [run_rec(), run_rec("whisper.cpp", kind="range")]}}
        fw = {"engine": "faster-whisper", "model": "large-v3"}
        for doc, spec, want in ((ev_doc, E.STORED, ""),                                              # 評価用は丁寧に校正してあるので注意しない
                                (daily, E.STORED, "下書きそのもの"),                                  # 保存した出力を測るのは下書きを測ること
                                (daily, fw, "モデルも同じ"),
                                (daily, dict(fw, model="small"), "モデルは違う"),
                                (daily, dict(fw, engine="whisper.cpp"), ""),                         # 下書きは最初の認識(再認識の記録 kind ではない)
                                ({}, fw, "")):                                                       # 記録が無ければ分からない
            got = E.draft_bias(doc, spec)
            if want:
                self.assertIn(want, got)
            else:
                self.assertEqual(got, "")
        self.assertEqual(E.draft_of({"recognition": {"runs": [run_rec("whisper.cpp", kind="range")]}})["engine"], "whisper.cpp")   # 再認識の記録しか無ければそれ
        self.assertIsNone(E.draft_of({}))

    def test_stored_marks_draft(self):
        res = self.stored("--source", "all")
        bias = {b["id"]: b["note"] for b in res["summary"]["draftBias"]}
        self.assertEqual(sorted(bias), ["dddddddddd01", "dddddddddd02", "dddddddddd03", "dddddddddd04"])   # 評価用は出ない
        by = self.by_doc(res)
        self.assertEqual((by["eeeeeeeeee01"]["draft"], by["dddddddddd01"]["draft"], by["dddddddddd02"]["draft"]),
                         ("faster-whisper large-v3 v1.0", "whisper.cpp large-v3 v1.0", E.DRAFT_NONE))
        self.assertEqual(by["dddddddddd03"]["draft"], "faster-whisper large-v3 v1.0")                   # 下書き = 最初の認識(あとの再認識ではない)
        self.assertEqual(res["summary"]["byDraft"]["whisper.cpp large-v3 v1.0"]["docs"], 2)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg が無い")
    def test_run_is_hint_free_and_warns_same_draft_engine(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        src = os.path.join(self.tmp, "clip.wav")
        silence_wav(src, 8.0)
        with open(os.path.join(self.data, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"glossary": "トワ、スバル"}, f, ensure_ascii=False)
        segs = [pseg(1, 0, 4, "テスト文1", ms(2026, 10, 3)), pseg(2, 4, 8, "テスト文2", ms(2026, 10, 3))]
        self.write("ffffffffff01", sourcePath=src, start=0, end=8, segments=segs, original=[], recognition={"runs": [run_rec("fake", "tiny")]})
        self.write("ffffffffff02", sourcePath=src, start=0, end=8, segments=segs, original=[], recognition={"runs": [run_rec("faster-whisper")]})
        self.write("ffffffffff03", evalSet=True, sourcePath=src, start=0, end=8, segments=segs, original=[], recognition={"runs": [run_rec("fake")]})
        # 普段の文書: 設定の用語集があっても渡さない(ヒントなし)。評価用と同じ条件
        res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff01,ffffffffff02"])
        self.assertEqual((res["meta"]["engine"]["glossary"], res["meta"]["engine"]["hintFree"]), ([], True))
        self.assertEqual(res["summary"]["overall"]["errs"], 0)
        # 比べるエンジン(fake)と下書きのエンジンが同じ文書だけに注意が付く
        bias = {b["id"]: b["note"] for b in res["summary"]["draftBias"]}
        self.assertEqual(list(bias), ["ffffffffff01"])
        self.assertIn("同じ", bias["ffffffffff01"])
        # 自分で付けた --glossary は渡す。評価用だけのときは設定の用語集を渡し・下書きの注意は付かない
        res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff01", "--glossary", "あ、い"])
        self.assertEqual(res["meta"]["engine"]["glossary"], ["あ", "い"])
        res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff03"])
        self.assertEqual((res["meta"]["engine"]["glossary"], res["meta"]["engine"]["hintFree"], res["summary"]["draftBias"]), (["トワ", "スバル"], False, []))
        # 辞書(置換・学習)は常に使わない
        E.C.prepare("fake")
        args = types.SimpleNamespace(glossary=None, beam=None, model=None, engine="faster-whisper", vad=None, boost=None, device="auto", temp0=False)
        spec = E.run_spec(args, {"glossary": "トワ"}, hint_free=True)
        self.assertEqual((spec["glossary"], spec["autoDict"], spec["autoLearned"]), ([], False, False))

    # ---------------- エンジン・設定ごと

    def test_group_by_engine(self):
        g = self.stored("--source", "all", "--group-by", "engine")["summary"]["byGroup"]
        by_key = {k: v["docs"] for k, v in g.items()}
        fw = "faster-whisper large-v3 v1.0 beam5 vad:normal boost:off ヒント:なし 辞書:-"
        self.assertEqual(by_key[fw], 2)                                                      # 評価用の 2 本は同じエンジン・設定
        self.assertEqual(by_key["whisper.cpp large-v3 v1.0 beam5 vad:normal boost:off ヒント:なし 辞書:glossary=abc"], 1)   # 辞書の版が違えば別の組
        self.assertEqual(by_key["whisper.cpp large-v3 v1.0 beam5 vad:normal boost:off ヒント:なし 辞書:glossary=zzz"], 1)
        mixed = [k for k in g if k.startswith("混在")]                                         # 途中で別のエンジンで認識し直した文書は混ぜない
        self.assertEqual(len(mixed), 1)
        self.assertIn("faster-whisper", mixed[0])
        self.assertIn("whisper.cpp", mixed[0])
        self.assertEqual(g[E.DRAFT_NONE]["docs"], 1)                                          # 記録が無い文書
        self.assertEqual(sum(v["docs"] for v in g.values()), 6)
        self.assertEqual(g[fw]["refChars"], 10)
        # 設定・辞書の版を混ぜる粗い分け方
        g2 = self.stored("--source", "all", "--group-by", "model")["summary"]["byGroup"]
        self.assertEqual({k: v["docs"] for k, v in g2.items()}["whisper.cpp large-v3 v1.0"], 2)
        self.assertNotIn("byGroup", self.stored("--source", "all")["summary"])                 # 指定しなければ出さない
        # run では、比べるエンジンは全部同じなので、下書きを作ったエンジンで分ける(group_spec)
        title, key_of = E.group_spec(types.SimpleNamespace(group_by="model"), "run")
        self.assertIn("下書き", title)
        self.assertEqual(key_of({"recognition": {"runs": [run_rec("whisper.cpp")]}}), "whisper.cpp large-v3 v1.0")
        self.assertEqual(key_of({}), E.DRAFT_NONE)

    def test_run_label_old_records(self):
        """辞書の版・設定が無い古い記録(設定が params にある・何も無い)でも落ちない"""
        self.assertEqual(E.run_label({"engine": "faster-whisper", "model": "small"}, "engine"), "faster-whisper small ヒント:なし 辞書:-")
        r = {"engine": "faster-whisper", "model": "small", "params": {"beam": 1, "dict": {"roster": "r1"}}}
        self.assertEqual(E.run_label(r, "engine"), "faster-whisper small beam1 ヒント:なし 辞書:roster=r1")
        self.assertEqual(E.engine_key({"recognition": {"runs": [{"kind": "range"}]}}), E.DRAFT_NONE)

    # ---------------- 少ないデータ

    def test_low_data(self):
        res = self.stored()
        self.assertEqual((res["summary"]["lowData"], res["summary"]["proofedSec"]), (True, 16.0))   # 8 秒 × 2 本
        # 校正済みが 15 分に届けば外れる
        self.write("bbbbbbbbbb01", evalSet=True, segments=[pseg(1, 0, 900, "長い行のテスト文章です")], original=[{"start": 0, "end": 900, "text": "長い行のテスト文章です"}])
        res = self.stored("--docs", "bbbbbbbbbb01")
        self.assertEqual((res["summary"]["lowData"], res["summary"]["proofedSec"]), (False, 900.0))
        res = self.stored("--docs", "bbbbbbbbbb01,eeeeeeeeee01", "--group-by", "model")      # 組ごとにも出す(組の校正済みが少なければ参考)
        self.assertEqual({k: v["lowData"] for k, v in res["summary"]["byGroup"].items()}, {E.DRAFT_NONE: False, "faster-whisper large-v3 v1.0": True})


class EvalAsrReviewedTest(Base):
    """確かめ済み(evalReviewed = 動画を全部聞いて直した印)の文書は、動画全体が正解。--reviewed の選び分け・確かめ済みが 0 本のときの戻り"""

    def setUp(self):
        super().setUp()
        # 人の行は 10〜14 と 30〜33(足した行 = 機械が出していない)。機械は 0〜3(ええと)と 50〜54(ご視聴…)に人の行の無い所へ出した
        human = [seg(1, 10.0, 14.0, "こんにちは"), seg(2, 30.0, 33.0, "足した行")]
        machine = [{"start": 0.0, "end": 3.0, "text": "ええと"}, {"start": 10.0, "end": 14.0, "text": "こんにちは"},
                   {"start": 50.0, "end": 54.0, "text": "ご視聴ありがとう"}]
        self.write("aaaaaaaaaa01", evalSet=True, evalReviewed={"at": 5, "rows": 2, "durationSec": 60.0, "via": "drill"}, segments=human, original=machine)
        self.write("bbbbbbbbbb01", evalSet=True, segments=human, original=machine)        # 同じ中身で確かめ済みの印なし
        self.write("dddddddddd01", segments=human, original=machine)                     # 普段の文書(評価用でない)

    def test_reviewed_doc_is_scored_over_the_whole_video(self):
        res = self.stored()                                    # 評価用の既定は only = 確かめ済みの動画だけ
        self.assertEqual(res["meta"]["docs"], ["aaaaaaaaaa01"])
        o = res["summary"]["overall"]
        extra = len("ええと") + len("ご視聴ありがとう")
        self.assertEqual((o["sub"], o["del"], o["ins"]), (0, len("足した行"), extra))   # 人の行の無い所の機械の文字 = 余分・機械の無い所の人の行 = 抜け
        self.assertEqual(o["refChars"], len("こんにちは足した行"))
        self.assertEqual(res["summary"]["reviewed"], {"docs": 1, "sec": 60.0, "refChars": 9, "missChars": 4, "extraChars": extra, "extraOutsideChars": extra})
        self.assertEqual(res["summary"]["proofedSec"], 60.0)    # 動画の長さ(すき間まで聞いた)
        self.assertEqual(res["summary"]["byKind"]["人が消した(余分)"]["ins"], extra)
        self.assertTrue(self.by_doc(res)["aaaaaaaaaa01"]["reviewed"])
        self.assertTrue(all(g["whole"] for g in res["groups"]))
        # 時刻によらない CER も全体の文字で(ええと + こんにちは + ご視聴ありがとう と、こんにちは + 足した行)
        E.C.prepare("fake")
        a, b, c = _metrics.lev_counts(_metrics.norm_cer("こんにちは足した行"), _metrics.norm_cer("ええとこんにちはご視聴ありがとう"))
        dt = res["summary"]["docText"]
        self.assertEqual((dt["refChars"], dt["sub"], dt["del"], dt["ins"]), (9, a, b, c))
        # 入口の自動の測定(src/eval/drill/accuracy.py の summarize_asr)が読む鍵
        for k in ("overall", "ci95", "byDoc", "lowData", "proofedSec"):
            self.assertIn(k, res["summary"])
        self.assertIn("cer", o)
        from eval.drill import accuracy
        out = accuracy.summarize_asr(res)
        self.assertEqual((out["chars"], out["proofedSec"], out["reviewedSec"]), (9, 60, 60.0))

    def test_unreviewed_doc_is_scored_as_before(self):
        res = self.stored("--reviewed", "ignore")              # 印を見ない。校正した行の範囲(10〜33)の外の機械の文字は数えない
        self.assertEqual(sorted(res["meta"]["docs"]), ["aaaaaaaaaa01", "bbbbbbbbbb01"])
        for d in res["summary"]["byDoc"]:
            self.assertEqual((d["sub"], d["del"], d["ins"]), (0, 4, 0), d["id"])
        self.assertEqual(res["summary"]["reviewed"]["docs"], 0)
        self.assertFalse(any(g.get("whole") for g in res["groups"]))
        self.assertEqual(res["summary"]["proofedSec"], 2 * (4.0 + 3.0))   # 人の行があるまとまりの幅だけ
        # 確かめ済みでない文書(prefer の中)も同じ
        d = self.by_doc(self.stored("--reviewed", "prefer"))
        self.assertEqual((d["bbbbbbbbbb01"]["del"], d["bbbbbbbbbb01"]["ins"]), (4, 0))
        self.assertEqual(d["aaaaaaaaaa01"]["ins"], len("ええと") + len("ご視聴ありがとう"))

    def test_reviewed_choices(self):
        a, b, d = "aaaaaaaaaa01", "bbbbbbbbbb01", "dddddddddd01"
        for argv, ids, mode in (((), [a], "only"),                                  # 既定(評価用)= only
                                (("--reviewed", "prefer"), [a, b], "prefer"),      # 確かめ済みは全体で・ほかも混ぜる
                                (("--reviewed", "ignore"), [a, b], "ignore"),
                                (("--source", "daily"), [d], "prefer"),             # 評価用以外は prefer
                                (("--source", "all"), [a, b, d], "prefer"),         # 確かめ済みの印は評価用の文書だけ
                                (("--docs", b), [b], "prefer")):                    # --docs を渡したら only にしない(指定した文書を落とさない)
            res = self.stored(*argv)
            self.assertEqual((sorted(res["meta"]["docs"]), res["meta"]["selection"]["reviewed"]["mode"]), (ids, mode), argv)
        self.assertEqual(self.stored("--reviewed", "prefer")["summary"]["proofedSec"], 60.0 + 7.0)   # 確かめ済みは動画の長さ・ほかは人の行の幅
        self.assertEqual(self.stored("--source", "all")["summary"]["reviewed"]["docs"], 1)
        self.assertEqual(self.stored()["meta"]["selection"]["reviewed"], {"mode": "only", "effective": "only", "candidates": 2, "evalDocs": 2, "reviewedDocs": 1, "fallback": False, "notReviewed": 1})

    def test_only_falls_back_when_nothing_is_reviewed(self):
        os.unlink(os.path.join(self.data, "transcripts", "aaaaaaaaaa01.json"))
        res = self.stored()
        self.assertEqual(res["meta"]["docs"], ["bbbbbbbbbb01"])                                           # 今までどおりの選び方
        self.assertEqual(res["meta"]["selection"]["reviewed"], {"mode": "only", "effective": "ignore", "candidates": 1, "evalDocs": 1, "reviewedDocs": 0, "fallback": True, "notReviewed": 0})
        self.assertEqual(res["summary"]["reviewed"]["docs"], 0)
        self.assertEqual(res["summary"]["overall"]["ins"], 0)

    def test_silent_and_missed_reviewed_docs(self):
        # 行の無い確かめ済みの文書 = 何も話していない。機械が出した文字はすべて余分。機械も出していなければ誤りなし(本数と秒には数える)
        # 機械が何も出していない所の人の行は、original が空でも抜け
        self.write("aaaaaaaaaa02", evalSet=True, evalReviewed={"at": 5, "rows": 0, "durationSec": 30.0}, segments=[], original=[{"start": 5.0, "end": 8.0, "text": "幻覚の文"}])
        self.write("aaaaaaaaaa03", evalSet=True, evalReviewed={"at": 5, "rows": 0, "durationSec": 20.0}, segments=[], original=[])
        self.write("aaaaaaaaaa04", evalSet=True, evalReviewed={"at": 5, "rows": 1, "durationSec": 20.0}, segments=[seg(1, 2.0, 5.0, "全部抜けた")], original=[])
        res = self.stored("--docs", "aaaaaaaaaa02,aaaaaaaaaa03,aaaaaaaaaa04")
        d = self.by_doc(res)
        self.assertEqual((d["aaaaaaaaaa02"]["ins"], d["aaaaaaaaaa02"]["refChars"]), (len("幻覚の文"), 0))
        self.assertNotIn("aaaaaaaaaa03", d)                                                              # 文字が無いので byDoc には出ない
        self.assertEqual((d["aaaaaaaaaa04"]["refChars"], d["aaaaaaaaaa04"]["del"], d["aaaaaaaaaa04"]["ins"]), (5, 5, 0))
        rv = res["summary"]["reviewed"]
        self.assertEqual((rv["docs"], rv["sec"], rv["extraChars"], rv["missChars"]), (3, 70.0, 4, 5))
        self.assertEqual(res["summary"]["proofedSec"], 70.0)
        # 印を見ない(ignore)なら、行の無い文書は測る正解が無いので外れる
        self.assertEqual(self.stored("--docs", "aaaaaaaaaa02", "--reviewed", "ignore")["meta"]["docs"], [])


class EvalAsrGateRepeatTest(Base):
    """量の関門(gate_of・compare の判定)と、run --repeat N(N 回の認識の中央)。認識は偽(recognize_doc を差し替える)"""

    def setUp(self):
        super().setUp()
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        self.enterContext(mock.patch.object(E, "peak_mem", lambda: 0))   # メモリの最大は実行のたびに揺れる。出力を突き合わせるため固定する
        self.reviewed_doc("aaaaaaaaaa01", 60.0)

    def script(self, plan):
        """認識の偽物: 呼ばれた順に plan の要素(文字 = その文字を出す・Exception = 認識できない)を使う。呼ばれた文書の id を calls に残す"""
        calls = []

        def fake(doc, spec, data):
            item = plan[len(calls)]
            calls.append(doc["id"])
            if isinstance(item, Exception):
                raise item
            return [{"start": 10.0, "end": 14.0, "text": item}], 60.0, 1.0, "動画", "cpu"
        self.enterContext(mock.patch.object(E, "recognize_doc", fake))
        return calls

    def run_cmd(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = E.main(["run", "--data", self.data, "--no-save", *argv])
        return res, buf.getvalue()

    # ---- 量の関門

    def test_gate_of_boundaries(self):
        g = E.gate_of
        self.assertEqual(E.GATES, (("G0", 300), ("G1", 900), ("G2", 1800), ("G3", 3600)))
        self.assertEqual(g(0), {"gate": None, "sec": 0.0, "next": "G0", "nextSec": 300})
        self.assertEqual((g(299.9)["gate"], g(299.9)["next"]), (None, "G0"))
        self.assertEqual((g(300)["gate"], g(300)["next"], g(300)["nextSec"]), ("G0", "G1", 600))
        self.assertEqual((g(899)["gate"], g(899)["nextSec"]), ("G0", 1))
        self.assertEqual((g(900)["gate"], g(900)["next"]), ("G1", "G2"))
        self.assertEqual((g(1800)["gate"], g(1800)["next"]), ("G2", "G3"))
        self.assertEqual((g(3599)["gate"], g(3599)["next"]), ("G2", "G3"))
        self.assertEqual(g(3600), {"gate": "G3", "sec": 3600, "next": None, "nextSec": 0.0})
        self.assertEqual((g(7200)["gate"], g(7200)["next"]), ("G3", None))
        for bad in (None, -5, "x", True):
            self.assertEqual((g(bad)["gate"], g(bad)["sec"]), (None, 0.0))

    def test_gate_in_stored_and_run_summary(self):
        res = self.stored()
        self.assertEqual(res["summary"]["gate"], E.gate_of(60.0))                       # 確かめ済み 60 秒 = まだ(G0 の 5 分に届かない)
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        self.assertIn("関門: まだ(定点 1 分)・次の G0 まであと 4 分", out.getvalue())      # 秒 → 分の数え方
        self.reviewed_doc("aaaaaaaaaa02", 900.0)
        self.assertEqual(self.stored()["summary"]["gate"]["gate"], "G1")               # 60 + 900 = 16 分
        self.script(["こんにちは", "こんにちは"])
        res, _ = self.run_cmd()
        self.assertEqual(res["summary"]["gate"]["gate"], "G1")
        # 確かめ済みが 0(従来の選び方に戻ったとき)は「まだ(定点 0 分)」
        for t in ("aaaaaaaaaa01", "aaaaaaaaaa02"):
            path = os.path.join(self.data, "transcripts", t + ".json")
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            d.pop("evalReviewed")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        self.assertEqual(self.stored()["summary"]["gate"], {"gate": None, "sec": 0.0, "next": "G0", "nextSec": 300})

    def make_result(self, name, sec, errs, with_gate=True):
        """compare が読む最小の結果。errs = 文書ごとの誤り字数(正解は 100 字ずつ)"""
        summary = {"byTag": {}, "byKind": {}}
        if with_gate:
            summary["gate"] = E.gate_of(sec)
        groups = [{"doc": "d%d" % i, "sub": e, "del": 0, "ins": 0, "refChars": 100} for i, e in enumerate(errs)]
        return self.dump(name, {"meta": {"dataFingerprint": "x"}, "summary": summary, "groups": groups})

    def test_compare_gate_verdict(self):
        pa = self.make_result("a.json", 3600, [10, 10, 10, 10, 10, 10])
        # 文書によって良くも悪くもなる = 範囲が 0 をまたぐ → 決められない。関門は小さい方(定点 15 分 = G1)
        out = quiet(E.cmd_compare, pa, self.make_result("b.json", 900, [2, 18, 3, 17, 10, 10]))
        self.assertEqual(out["gate"]["gate"], "G1")
        self.assertIn("この量では決められない(分からない)", out["gateVerdict"])
        self.assertIn("G1", out["gateVerdict"])
        # どの文書も良くなる = 範囲が 0 より下 → 改善の側
        pc = self.make_result("c.json", 1800, [4, 5, 6, 5, 4, 6])
        better = quiet(E.cmd_compare, pa, pc)
        self.assertEqual(better["gate"]["gate"], "G2")
        self.assertIn("改善 の側", better["gateVerdict"])
        self.assertNotIn("決められない", better["gateVerdict"])
        self.assertIn("悪化 の側", quiet(E.cmd_compare, pc, pa)["gateVerdict"])
        # 定点が 5 分に届かない結果が混ざれば「まだ」
        self.assertIn("まだ", quiet(E.cmd_compare, pa, self.make_result("d.json", 60, [4, 5, 6, 5, 4, 6]))["gateVerdict"])
        # 関門の無い(古い)結果なら、判定の鍵を付けない(落ちない)
        res = quiet(E.cmd_compare, self.make_result("old.json", 3600, [10] * 6, with_gate=False), pc)
        self.assertNotIn("gate", res)
        self.assertIn("verdict", res)

    # ---- --repeat

    def test_repeat_picks_median_run(self):
        # 回ごとの CER: こんにちわ(置換 1 / 5 字 = 20%)・こんにちは(0%)・こんばんは(置換 2 = 40%)→ 中央は 1 回目(20%)
        self.script(["こんにちわ", "こんにちは", "こんばんは"])
        res, _ = self.run_cmd("--repeat", "3")
        rp = res["meta"]["repeat"]
        self.assertEqual((rp["n"], rp["cers"], rp["median"], rp["spread"], rp["complete"], rp["docs"]), (3, [0.2, 0.0, 0.4], 0, 0.4, True, [1, 1, 1]))
        self.assertEqual(rp["docTextCers"], [0.2, 0.0, 0.4])
        self.assertEqual(res["summary"]["overall"]["cer"], 0.2)                    # 本体は代表の回の結果(今までと同じ形)
        self.assertEqual(res["groups"][0]["hyp"], "こんにちわ")
        # 順番が違っても中央の回。偶数回は中央の 2 つの小さい方(同じ CER は早い回が先)
        for plan, median, cer in ((["こんばんは", "こんにちわ", "こんにちは"], 1, 0.2),
                                  (["こんにちわ", "こんにちは", "こんばんは", "こんにちわ"], 0, 0.2),   # 0%(2)・20%(1)・20%(4)・40% → 1 回目
                                  (["こんにちわ", "こんにちは"], 1, 0.0)):
            self.script(plan)
            res, _ = self.run_cmd("--repeat", str(len(plan)))
            self.assertEqual((res["meta"]["repeat"]["median"], res["summary"]["overall"]["cer"]), (median, cer), plan)

    def test_repeat_one_is_same_as_before(self):
        self.script(["こんにちわ", "こんにちわ"])
        base, out1 = self.run_cmd()
        one, out2 = self.run_cmd("--repeat", "1")
        self.assertNotIn("repeat", base["meta"])
        self.assertNotIn("repeat", one["meta"])
        self.assertEqual(base["summary"], one["summary"])
        self.assertEqual(base["groups"], one["groups"])
        self.assertEqual(out1, out2)
        with self.assertRaises(SystemExit):
            self.run_cmd("--repeat", "0")
        # --temp0 と一緒なら注意を出すが、流れは止めない
        self.script(["こんにちは", "こんにちは"])
        res, out = self.run_cmd("--repeat", "2", "--temp0")
        self.assertEqual(res["meta"]["repeat"]["n"], 2)
        self.assertIn("--temp0", out)

    def test_repeat_with_dropped_doc_is_flagged(self):
        self.reviewed_doc("aaaaaaaaaa02", 60.0)
        # 1 回目: 2 本とも認識できた / 2 回目: 2 本目が落ちた / 3 回目: 2 本とも
        calls = self.script(["こんにちは", "こんにちは", "こんにちは", RuntimeError("音声が見つかりません"), "こんにちわ", "こんにちわ"])
        res, out = self.run_cmd("--repeat", "3")
        rp = res["meta"]["repeat"]
        self.assertEqual(len(calls), 6)
        self.assertEqual((rp["complete"], rp["docs"]), (False, [2, 1, 2]))
        self.assertIn("回ごとに数えた文書がそろっていません", out)
        # 選ぶときの CER は全部の回にある文書だけで出す(aaaaaaaaaa01 だけ): 0%・0%・20% → 中央は 2 回目
        self.assertEqual((rp["cers"], rp["median"]), ([0.0, 0.0, 0.2], 1))


class EvalAsrOriginTest(Base):
    """定点の出どころ別(編集前・ショート): origin_of・summary.origins・--group-by origin・compare の食い違いの注意"""

    CLIP = {"schema": "youtube-tools-clip/v1", "source": {"kind": "youtube", "videoId": "abcdefghijk"}}

    def test_origin_of(self):
        for clip in (self.CLIP, {"source": {"videoId": "x"}}, {"source": {"kind": "local"}}):   # videoId が無くても kind があれば編集前
            self.assertEqual(E.origin_of({"clip": clip}), "raw")
        self.assertEqual(E.origin_of({}), "short")                                              # clip が無い = ショート
        for clip in (None, "x", [], {}, {"source": None}, {"source": {}}, {"source": "x"}, {"source": {"videoId": ""}}):
            self.assertEqual(E.origin_of({"clip": clip}), "short")
        self.assertEqual(E.origin_of(None), "short")

    def test_summary_origins_both(self):
        self.reviewed_doc("aaaaaaaaaa01", 300.0, heard="こんにちわ", clip=self.CLIP)   # 編集前: 置換 1 / 5 字 = 20%
        self.reviewed_doc("bbbbbbbbbb01", 120.0)                                       # ショート: 全部合う
        res = self.stored()
        og = res["summary"]["origins"]
        self.assertEqual(sorted(og), ["raw", "short"])
        self.assertEqual((og["raw"]["docs"], og["raw"]["ids"], og["raw"]["reviewedSec"], og["raw"]["cer"]), (1, ["aaaaaaaaaa01"], 300.0, 0.2))
        self.assertEqual((og["short"]["docs"], og["short"]["reviewedSec"], og["short"]["cer"]), (1, 120.0, 0.0))
        self.assertEqual((og["raw"]["sub"], og["raw"]["del"], og["raw"]["ins"], og["raw"]["refChars"]), (1, 0, 0, 5))
        self.assertIn("docText", og["raw"])                                                     # 時刻によらない CER も
        self.assertEqual(res["summary"]["overall"]["refChars"], 10)                             # 全体の数字はそのまま
        self.assertEqual({d["id"]: d["origin"] for d in res["summary"]["byDoc"]}, {"aaaaaaaaaa01": "raw", "bbbbbbbbbb01": "short"})
        res = self.stored("--group-by", "origin")
        by = res["summary"]["byGroup"]
        self.assertEqual(sorted(by), ["ショート", "編集前"])
        self.assertEqual((by["編集前"]["cer"], by["ショート"]["cer"], by["編集前"]["docs"]), (0.2, 0.0, 1))
        self.assertIn("出どころごと", res["summary"]["groupBy"])

    def test_summary_origins_one_side_only(self):
        self.reviewed_doc("bbbbbbbbbb01", 120.0)
        self.assertEqual(list(self.stored()["summary"]["origins"]), ["short"])                 # ある方だけ
        self.reviewed_doc("aaaaaaaaaa01", 120.0, clip=self.CLIP)
        os.unlink(os.path.join(self.data, "transcripts", "bbbbbbbbbb01.json"))
        self.assertEqual(list(self.stored()["summary"]["origins"]), ["raw"])

    def make_result(self, name, raw_errs, short_errs, origins=True):
        """compare が読む最小の結果。raw の文書は r0.. / short の文書は s0..(正解は 100 字ずつ)"""
        ids = {"raw": ["r%d" % i for i in range(len(raw_errs))], "short": ["s%d" % i for i in range(len(short_errs))]}
        groups = [{"doc": i, "sub": e, "del": 0, "ins": 0, "refChars": 100} for k, errs in (("raw", raw_errs), ("short", short_errs)) for i, e in zip(ids[k], errs)]
        summary = {"byTag": {}, "byKind": {}}
        if origins:
            summary["origins"] = {k: {"ids": v, "docs": len(v)} for k, v in ids.items() if v}
        return self.dump(name, {"meta": {"dataFingerprint": "x"}, "summary": summary, "groups": groups})

    def test_compare_origin_conflict_is_noted(self):
        pa = self.make_result("a.json", [10, 10, 10], [10, 10, 10])
        # 編集前は良くなる(-8 pt)・ショートは悪くなる(+2 pt)・全体は良くなる(-3 pt)→ ショートの向きが食い違う
        res, _ = self.compare(pa, self.make_result("b.json", [2, 2, 2], [12, 12, 12]))
        self.assertLess(res["diff"], 0)
        self.assertEqual(res["origins"]["raw"]["diff"], -0.08)
        self.assertEqual((res["origins"]["short"]["diff"], res["origins"]["short"]["cerA"], res["origins"]["short"]["cerB"]), (0.02, 0.1, 0.12))
        self.assertEqual((res["origins"]["raw"]["docs"], len(res["origins"]["raw"]["ci95"])), (3, 2))
        self.assertEqual((res["origins"]["raw"]["conflict"], res["origins"]["short"]["conflict"]), (False, True))
        self.assertIn("originNote", res)
        for k in ("a", "b", "docs", "cerA", "cerB", "diff", "ci95", "verdict", "warnings", "byDoc"):   # compare の結果の鍵
            self.assertIn(k, res)
        # 食い違う / どちらも良くなる / 小さい差(0.5 pt に届かない)は向きを見ない
        for short_b, want in (([12, 12, 12], ["short"]), ([8, 8, 8], []), ([10, 10, 10], [])):
            res, _ = self.compare(pa, self.make_result("c.json", [2, 2, 2], short_b))
            self.assertEqual(res["originConflict"], want, short_b)
            self.assertEqual("originNote" in res, bool(want))

    def test_compare_origin_with_one_doc_or_one_side(self):
        pa = self.make_result("a.json", [10, 10, 10], [10])
        res, _ = self.compare(pa, self.make_result("b.json", [2, 2, 2], [10]))
        self.assertIsNone(res["origins"]["short"]["ci95"])                                      # 1 本では範囲を出さない
        res, _ = self.compare(pa, self.make_result("c.json", [2, 2, 2], []))                     # 両方にある出どころだけ
        self.assertEqual(list(res["origins"]), ["raw"])

    def test_compare_old_result_without_origins_works_as_before(self):
        pa = self.make_result("a.json", [10, 10, 10], [10, 10, 10], origins=False)
        pb = self.make_result("b.json", [2, 2, 2], [12, 12, 12])
        for x, y in ((pa, pb), (pb, pa), (pa, pa)):                                              # 片方・両方が古くても落ちない・出どころの鍵は付かない
            res, _ = self.compare(x, y)
            self.assertNotIn("origins", res)
            self.assertNotIn("originConflict", res)
            self.assertIn("verdict", res)


class EvalAsrNoSubOverlapTest(Base):
    """字幕に出さない行(noSub)の別集計と、重なりのまとまりの別集計(overlap・nonOverlap)。noSub も重なりも無い文書は今までと同じ数"""

    def write(self, tid, **kw):
        super().write(tid, evalSet=True, **kw)

    def stored(self, *argv):
        return super().stored("--reviewed", "ignore", *argv)

    def test_no_nosub_no_overlap_is_zero_and_numbers_unchanged(self):
        self.write("aaaaaaaaaa01", segments=[seg(1, 0.0, 4.0, "まつりが来た")], original=[{"start": 0.0, "end": 4.0, "text": "祭りが来た"}])
        res = self.stored()
        s = res["summary"]
        self.assertEqual((s["overall"]["refChars"], s["overall"]["sub"], s["overall"]["del"], s["overall"]["ins"]), (6, 1, 1, 0))
        self.assertEqual(s["overlap"], {"groups": 0, "sec": 0, "refChars": 0, "cer": None, "miss": 0})
        self.assertEqual(s["nonOverlap"], {"refChars": 6, "cer": s["overall"]["cer"]})
        self.assertEqual((s["noSub"]["docs"], s["noSub"]["rows"], s["noSub"]["sec"], s["noSub"]["machineChars"]), (0, 0, 0, 0))
        self.assertTrue(all("ovl" not in g for g in res["groups"]))

    def test_nosub_rows_and_machine_chars_are_separate(self):
        machine = [{"start": 0.0, "end": 4.0, "text": "こんにちは"}, {"start": 10.0, "end": 14.0, "text": "ゲームのセリフです"}, {"start": 50.0, "end": 54.0, "text": "ご視聴"}]
        base = [seg(1, 0.0, 4.0, "こんにちは")]
        self.write("aaaaaaaaaa01", evalReviewed={"at": 5, "rows": 1, "durationSec": 60.0, "via": "drill"}, segments=base, original=machine)       # noSub の行なし
        self.write("bbbbbbbbbb01", evalReviewed={"at": 5, "rows": 2, "durationSec": 60.0, "via": "drill"},
                   segments=base + [seg(2, 10.0, 14.0, "ゲームのセリフ", speaker="S2", noSub=True)], original=machine)
        res = Base.stored(self)
        by = self.by_doc(res)
        # 余分: noSub の行が無い文書は「ゲームのセリフです」+「ご視聴」、ある文書は「ご視聴」だけ
        self.assertEqual(by["aaaaaaaaaa01"]["ins"], len("ゲームのセリフです") + len("ご視聴"))
        self.assertEqual(by["bbbbbbbbbb01"]["ins"], len("ご視聴"))
        self.assertEqual(by["bbbbbbbbbb01"]["refChars"], by["aaaaaaaaaa01"]["refChars"])           # 人の noSub の行は正解に入れない
        ns = res["summary"]["noSub"]
        self.assertEqual((ns["docs"], ns["rows"], ns["sec"], ns["machineChars"]), (1, 1, 4.0, len("ゲームのセリフです")))
        self.assertEqual(list(ns["byDoc"]), ["bbbbbbbbbb01"])
        self.assertEqual(res["summary"]["reviewed"]["extraChars"], len("ゲームのセリフです") + 2 * len("ご視聴"))   # 確かめ済みの余分にも入れない(2 本目は ご視聴 だけ)

    def test_overlap_group_is_counted_separately_with_best_order(self):
        # 2 人が同時にしゃべる(0〜3 の A「あいうえお」・1〜4 の B「かきくけこ」)。機械は話者ごとに B → A の順で書いた
        segs = [seg(1, 0.0, 3.0, "あいうえお", speaker="A"), seg(2, 1.0, 4.0, "かきくけこ", speaker="B"), seg(3, 10.0, 12.0, "ふつうの行", speaker="A")]
        machine = [{"start": 0.0, "end": 4.0, "text": "かきくけこあいうえお"}, {"start": 10.0, "end": 12.0, "text": "ふつうの行"}]
        self.write("aaaaaaaaaa01", segments=segs, original=machine)
        res = self.stored()
        s = res["summary"]
        self.assertEqual(s["overlap"], {"groups": 1, "sec": 4.0, "refChars": 10, "cer": 0.0, "miss": 0})   # 並べ方を入れ替えた小さい方 = 誤りなし
        self.assertEqual(s["nonOverlap"], {"refChars": 5, "cer": 0.0})
        o = s["overall"]                                                                                 # 主な数字は今までの数え方(開始時刻の順)のまま = 誤りが出る
        self.assertEqual(o["refChars"], 15)
        self.assertGreater(o["errs"], 0)
        g = next(g for g in res["groups"] if "ovl" in g)
        self.assertEqual(g["ovl"]["sub"] + g["ovl"]["del"] + g["ovl"]["ins"], 0)
        self.assertGreater(g["sub"] + g["del"] + g["ins"], 0)

    def test_overlap_miss_counts_deleted_chars(self):
        segs = [seg(1, 0.0, 3.0, "あいうえお", speaker="A"), seg(2, 1.0, 4.0, "かきくけこ", speaker="B")]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 4.0, "text": "あいうえお"}])   # 片方しか書かなかった
        s = self.stored()["summary"]
        self.assertEqual((s["overlap"]["groups"], s["overlap"]["miss"], s["overlap"]["cer"]), (1, 5, 0.5))
        res = self.stored("--group-by", "origin")                                                        # 組で分けても重なりは数える
        self.assertEqual((list(res["summary"]["byGroup"]), res["summary"]["overlap"]["groups"]), (["ショート"], 1))

    def test_overlap_needs_different_speakers_and_0_3_sec(self):
        for case, end1, spk2, want in [("同じ話者は数えない", 3.0, "A", 0),
                                        ("重なりが 0.29 秒", 1.29, "B", 0),
                                        ("重なりが 0.3 秒ちょうど", 1.3, "B", 1)]:
            with self.subTest(case):
                self.write("aaaaaaaaaa01", segments=[seg(1, 0.0, end1, "あいう", speaker="A"), seg(2, 1.0, 4.0, "えおか", speaker=spk2)],
                           original=[{"start": 0.0, "end": 4.0, "text": "あいうえおか"}])
                self.assertEqual(self.stored()["summary"]["overlap"]["groups"], want)

    def test_nosub_is_removed_before_counting_overlap(self):
        """字幕に出さない行は先に外す: ゲーム音声と重なっても重なりのまとまりにならない"""
        segs = [seg(1, 0.0, 3.0, "あいう", speaker="A"), seg(2, 1.0, 4.0, "ゲーム", speaker="G", noSub=True)]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 3.0, "text": "あいう"}, {"start": 1.0, "end": 4.0, "text": "ゲーム"}])
        s = self.stored()["summary"]
        self.assertEqual((s["overlap"]["groups"], s["noSub"]["rows"]), (0, 1))

    def test_compare_shows_overlap(self):
        segs = [seg(1, 0.0, 3.0, "あいうえお", speaker="A"), seg(2, 1.0, 4.0, "かきくけこ", speaker="B"), seg(3, 10.0, 12.0, "ふつうの行", speaker="A")]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 4.0, "text": "かきくけこあいうえお"}, {"start": 10.0, "end": 12.0, "text": "ふつう行"}])
        res = self.stored()
        b = json.loads(json.dumps(res))
        for g in b["groups"]:
            if "ovl" in g:
                g["ovl"] = {"sub": 2, "del": 0, "ins": 0}
            else:
                g["del"] = 0
        cmp_ = quiet(E.cmd_compare, self.dump("a.json", res), self.dump("b.json", b))
        self.assertEqual(cmp_["overlap"]["groups"], 1)
        self.assertEqual((cmp_["overlap"]["cerA"], cmp_["overlap"]["cerB"]), (0.0, 0.2))
        self.assertEqual((cmp_["nonOverlap"]["cerA"], cmp_["nonOverlap"]["cerB"]), (0.2, 0.0))
        self.assertEqual(cmp_["nonOverlap"]["diff"], -0.2)
        # 重なりの無い結果どうしの compare には、重なりの欄を足さない
        self.write("aaaaaaaaaa01", segments=[seg(1, 0.0, 4.0, "あいう", speaker="A")], original=[{"start": 0.0, "end": 4.0, "text": "あいう"}])
        pp = self.dump("p.json", self.stored())
        c2 = quiet(E.cmd_compare, pp, pp)
        self.assertNotIn("overlap", c2)
        self.assertNotIn("nonOverlap", c2)


if __name__ == "__main__":
    unittest.main()
