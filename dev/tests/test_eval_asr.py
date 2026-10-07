"""dev/eval_asr.py(文字起こしの精度を測る道具。計画 段0-2)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_asr.py

作業データは一時フォルダに作る(本物の作業データは読まない)。run は偽の認識(TRANSCRIBE_BACKEND=fake)で流れだけ確かめる(ffmpeg が必要)。
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import wave
import zipfile
from contextlib import redirect_stdout
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
sys.path.insert(0, HERE)
import eval_asr as E  # noqa: E402
import eval_import as EI  # noqa: E402


def seg(i, a, b, text, proofed=True, tags=None, flag=""):
    g = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": flag}
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
    buf = io.StringIO()
    with redirect_stdout(buf):
        return fn(*a)


class EvalAsrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0"
        # 評価用: 置換 1(祭り→まつり)・重なり・人が足した行(抜け)・人が消した行(余分)・未校正の行(数えない)
        self.write("aaaaaaaaaaa1", evalSet=True, segments=[
            seg(1, 0.0, 4.0, "まつりが来た"), seg(2, 4.0, 8.0, "二人で話す", tags=["overlap"]), seg(3, 20.0, 22.0, "足した行"),
            seg(4, 30.0, 34.0, "まだ見ていない", proofed=False)],
            original=[{"start": 0.0, "end": 4.0, "text": "祭りが来た"}, {"start": 4.0, "end": 8.0, "text": "二人で話す"},
                      {"start": 12.0, "end": 13.0, "text": "ご視聴ありがとうございました"}, {"start": 30.0, "end": 34.0, "text": "まだ見てない"}])
        self.write("bbbbbbbbbbb2", segments=[seg(1, 0.0, 2.0, "学習用")], original=[{"start": 0.0, "end": 2.0, "text": "学習よう"}])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def snapshot(self):
        d = os.path.join(self.data, "transcripts")
        out = {}
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_stored_counts_like_the_screen(self):
        before = self.snapshot()
        res = quiet(E.main, ["stored", "--data", self.data, "--no-save"])
        o = res["summary"]["overall"]
        self.assertEqual(res["meta"]["docs"], ["aaaaaaaaaaa1"])          # 既定は評価用だけ
        self.assertEqual(res["meta"]["mismatch"], [])                   # 画面の「認識精度の測定」と同じ数
        # 正解 = まつりが来た(6)+ 二人で話す(5)+ 足した行(4)= 15 字。祭り→まつり は置換 1・抜け 1(編集距離が最小の数え方)
        self.assertEqual(o["refChars"], 15)
        self.assertEqual(res["summary"]["byKind"]["両方にある"]["errs"], 2)
        self.assertEqual(res["summary"]["byKind"]["人が足した(抜け)"]["del"], 4)   # 人が足した行 = 抜け
        self.assertEqual(res["summary"]["byKind"]["人が消した(余分)"]["ins"], len("ご視聴ありがとうございました"))
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["refChars"], 5)
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["errs"], 0)
        self.assertTrue(all(g["start"] < 30 for g in res["groups"]))    # 未校正の行は数えない
        self.assertEqual(self.snapshot(), before)                       # 文書は書き換えない
        allres = quiet(E.main, ["stored", "--data", self.data, "--scope", "all", "--no-save"])
        self.assertEqual(sorted(allres["meta"]["docs"]), ["aaaaaaaaaaa1", "bbbbbbbbbbb2"])
        # 時刻によらない数え方(段2-3): 数えたまとまりの文字を通しでつないで比べる。まとまりの数え方と同じ文字数・誤りはそれ以下
        dt = res["summary"]["docText"]
        self.assertEqual(dt["refChars"], 15)
        self.assertLessEqual(dt["sub"] + dt["del"] + dt["ins"], o["errs"])

    def test_doc_text_ignores_time_shift(self):
        """行の時刻がずれて文字が隣のまとまりへ移っても、時刻によらない数え方では誤りにならない"""
        S = E.load_serve("fake")
        groups = [{"doc": "d", "start": 0.0, "ref": "あいう", "hyp": "あい"}, {"doc": "d", "start": 5.0, "ref": "えお", "hyp": "うえお"}]
        dt = E.doc_text(S, groups)
        self.assertEqual((dt["refChars"], dt["sub"], dt["del"], dt["ins"], dt["cer"]), (5, 0, 0, 0, 0.0))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_recognizes_and_saves_without_touching_docs(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
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
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_with_context(self):
        """--context auto = 文書の題名などから出る人を決めて渡す(計画 段1-2)。既定の none では渡さない。--temp0 は設定に残る"""
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 8.0)
            self.write("ddddddddddd4", evalSet=True, title="教師データ＿さくらみこ01", sourcePath=src, start=0, end=8,
                       segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2")], original=[])
            res = quiet(E.main, ["run", "--data", self.data, "--docs", "ddddddddddd4", "--context", "auto", "--temp0", "--no-save"])
            self.assertEqual(res["meta"]["perDoc"][0]["context"], ["さくらみこ"])
            self.assertEqual((res["meta"]["engine"]["context"], res["meta"]["engine"]["settings"]["temp0"]), ("auto", True))
            self.assertIn("みこち", res["terms"])                                          # 名前の再現率に呼び名も数える(段1-1)
            base = quiet(E.main, ["run", "--data", self.data, "--docs", "ddddddddddd4", "--no-save"])
            self.assertEqual((base["meta"]["perDoc"][0]["context"], base["meta"]["engine"]["context"]), ([], "none"))
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    def test_load_serve_forwards_settings_to_the_parts(self):
        """load_serve は serve を sys.modules に登録して読む = 「S.名前 = …」が持ち主の部品(ed_jobs・ed_state)に届く。
        2026-10-07 まで届いていなかった(認識は認識ワーカーで動き・--context auto はスタジオの data.json を読めず・差し替えた QUANT_ON などは後処理に効かない)"""
        S = E.load_serve("fake")
        J = S.ed_jobs
        self.assertIs(sys.modules[E.C.SERVE_NAME], S)
        self.assertTrue(J.IN_WORKER)                                         # 認識はこのプロセスの中で(認識ワーカーを起動しない)
        self.assertEqual(S.ed_state.STUDIO_DATA, S.studio_data_path())      # スタジオの data.json は起動したツールと同じ決め方
        before = (J.QUANT_ON, J.JOIN_GAP)
        with mock.patch.object(S, "QUANT_ON", not before[0]), mock.patch.object(S, "JOIN_GAP", 0.0):
            self.assertEqual((J.QUANT_ON, J.JOIN_GAP), (not before[0], 0.0))   # 差し替えは部品に届く
        self.assertEqual((J.QUANT_ON, J.JOIN_GAP), before)                       # 戻すのも部品へ

    def test_retime_words_reach_the_model_in_this_process(self):
        """1 秒丸めの聞き直し(quant_words_provider)は WavSlice(認識ワーカーへ渡す形)をモデルに渡す。道具はモデルをこのプロセスの中で読む(IN_WORKER)ので、
        load_serve がワーカーの受け口と同じく範囲のサンプルに直して渡す(InProcessModel)。2026-10-07 夜まで faster-whisper が読めずに落ち、
        eval_asr run は丸まった窓のある文書を「とばしました」で数えていなかった。モデルは偽物(本物は読まない)"""
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

        S = E.load_serve("fake")
        S2 = E.load_serve("fake")   # 何回読んでも包むのは 1 回(部品は同じもの)
        J, SP = S.ed_jobs, S.ed_speakers
        self.assertIs(J, S2.ed_jobs)
        fw = J.tx_engines.FasterWhisper.id
        job = {"cancel": False, "phase": ""}
        with mock.patch.dict(J._models, {(J.QUANT_MODEL, "cpu", fw): Model()}, clear=True), mock.patch.object(S.ed_state, "gpu_ready", lambda: False), \
                mock.patch.object(S.ed_state, "backend_name", lambda: "faster-whisper"):
            words = S.quant_words_provider(job, {"language": "ja"}, wav)(0.5, 1.5)
            self.assertEqual(len(got), 1)
            self.assertIsInstance(got[0], np.ndarray)                                    # 範囲のサンプル(wav の 0.5〜1.5 秒)
            self.assertEqual(len(got[0]), 16000)
            self.assertAlmostEqual(float(got[0][0]) * 32768, 8000, places=3)
            self.assertEqual([w[2] for w in words], ["テスト"])
            self.assertAlmostEqual(words[0][0], 0.6, places=6)                           # 単語の時刻は行の秒(範囲の先頭を足す)
            m, _dev = J.load_model(J.QUANT_MODEL, job, "cpu", engine=fw)
            self.assertEqual(m.transcribe(SP.WavRef(wav))[0].__next__().text, "テスト")
            self.assertEqual(got[-1], wav)                                                # WavRef = wav のパスのまま
            m.hooks = {"x": 1}
            self.assertEqual(J._models[(J.QUANT_MODEL, "cpu", fw)].hooks, {"x": 1})       # 属性は中のモデルへ
            self.assertIn("word_timestamps", m.params())

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
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
        J = E.load_serve().ed_jobs   # main も同じ部品を使う
        with mock.patch.dict(os.environ), mock.patch.object(J, "_load_model_local", lambda *a, **k: (Model(), "cpu")), \
                mock.patch.object(J, "check_engine", lambda spec: None), mock.patch.object(J.WORKER, "call", no_worker), mock.patch.object(J.WORKER, "stream", no_worker):
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

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_context_reads_studio_streams(self):
        """--context auto はスタジオの data.json の配信のチャンネル名・コラボ相手から出る人を決める(load_serve が STUDIO_DATA を ed_state に届ける。
        2026-10-07 までは届かず以前の置き場所を見ていた = 題名・話者の名前からの文脈だけ)"""
        studio = os.path.join(self.tmp, "studio-data.json")
        with open(studio, "w", encoding="utf-8") as f:
            json.dump({"videos": {"vidAAAAAAAAA": {"channel": "Miko Ch. さくらみこ", "title": "配信"}, "vidBBBBBBBBB": {"channel": "Pekora Ch. 兎田ぺこら", "title": "配信"}},
                       "groups": {"g1": {"members": ["vidAAAAAAAAA", "vidBBBBBBBBB"]}}}, f, ensure_ascii=False)
        src = os.path.join(self.tmp, "clip.wav")
        silence_wav(src, 8.0)
        self.write("dddddddddd08", evalSet=True, title="切り抜き", sourcePath=src, start=0, end=8, clip={"source": {"videoId": "vidAAAAAAAAA"}},
                   segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2")], original=[])
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_STUDIO_DATA": studio}):
            res = quiet(E.main, ["run", "--data", self.data, "--docs", "dddddddddd08", "--context", "auto", "--no-save"])
        self.assertEqual(res["meta"]["perDoc"][0]["context"], ["さくらみこ", "兎田ぺこら"])   # チャンネル → コラボ相手

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_recognize_doc_applies_row_post_processing(self):
        """本番(run_job)と同じ行の後処理を通す(0.52.1): 長さより後ろの行を捨てる・dur と levels(whisper.cpp のときだけ)を expand_segments へ渡す"""
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            S = E.load_serve("fake")
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 8.0)
            doc = {"id": "eeeeeeeeeee5", "sourcePath": src, "start": 0, "end": 8}
            ed_jobs = S.ed_jobs
            real = ed_jobs.expand_segments
            calls = []

            def spy(gen, spec, dur=None, levels=None):
                calls.append((dur, levels))
                return real(gen, spec, dur, levels)

            def fake(job, spec, wav, total):   # 8 秒の音声に、長さの外(100 秒)の行
                yield {"start": 0.0, "end": 4.0, "text": "中の行"}
                yield {"start": 100.0, "end": 104.0, "text": "外の行"}

            def spec_of(engine):
                a = types.SimpleNamespace(glossary=None, beam=0, model="small", engine=engine, vad=None, boost=None, device="auto", temp0=False)
                return dict(E.run_spec(S, a, {}, True), context={"members": []})
            with mock.patch.object(ed_jobs, "expand_segments", spy), mock.patch.object(ed_jobs, "transcribe_fake", fake):
                rows, audio_sec, _w, _where, _dev = E.recognize_doc(S, doc, spec_of("faster-whisper"), self.data)
                self.assertEqual([r["text"] for r in rows], ["中の行"])
                self.assertAlmostEqual(calls[-1][0], audio_sec)
                self.assertIsNone(calls[-1][1])                                    # faster-whisper は音の谷へ寄せない
                E.recognize_doc(S, doc, spec_of("whisper.cpp"), self.data)
                self.assertIsNotNone(calls[-1][1])                                 # whisper.cpp は音の大きさ(WavLevels)を渡す
            # 行の後処理の印(meta.post)。joinGap = 続いている行をつなぐすき間(0.57.1。全エンジン)= editor の post_record と同じ値
            self.assertEqual(E.post_meta(S, spec_of("faster-whisper")), {"clip": True, "mergeRepeats": True, "pullEnds": False, "joinGap": 0.5})
            # whisper.cpp は 1 秒丸めの配り直し(編集 0.57.0。quant_retime)のモデルと endTrim(0.57.1 から 0)も印に残す。音の谷へ寄せる pullEnds は 10-05 から既定でやめた
            self.assertEqual(E.post_meta(S, spec_of("whisper.cpp")),
                             {"clip": True, "mergeRepeats": True, "pullEnds": False, "quantRetime": S.QUANT_MODEL, "endTrim": 0.0, "joinGap": 0.5})
            with mock.patch.object(S, "QUANT_ON", False), mock.patch.object(S, "END_TRIM", 0.1), mock.patch.object(S, "JOIN_GAP", 0.0), \
                    mock.patch.object(S, "PULL_ENDS_ON", True):   # TRANSCRIBE_RETIME=0・END_TRIM=0.1・JOIN_GAP=0・PULL_ENDS=1(0.57.0 より前の形)
                self.assertEqual(E.post_meta(S, spec_of("whisper.cpp")),
                                 {"clip": True, "mergeRepeats": True, "pullEnds": True, "quantRetime": False, "endTrim": 0.1, "joinGap": 0.0})
                self.assertEqual(E.post_meta(S, spec_of("faster-whisper"))["pullEnds"], False)   # 音の大きさを使うのは whisper.cpp だけ
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_result_has_post_mark(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 8.0)
            self.write("ffffffffff06", evalSet=True, sourcePath=src, start=0, end=8,
                       segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2")], original=[])
            res = quiet(E.main, ["run", "--data", self.data, "--docs", "ffffffffff06", "--no-save"])
            self.assertEqual(res["meta"]["post"], {"clip": True, "mergeRepeats": True, "pullEnds": False, "joinGap": 0.5})
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    def test_compare_notes_different_row_post_processing(self):
        """片方に post が無い(0.51.0 より前の測定)・中身が違う(0.57.1 の前後の joinGap など)結果どうしは、注意を出す。同じ・両方無いなら出さない"""
        a = quiet(E.main, ["stored", "--data", self.data, "--label", "a"])
        pa = os.path.join(self.data, "evals", "asr", sorted(os.listdir(os.path.join(self.data, "evals", "asr")))[0])
        post = {"clip": True, "mergeRepeats": True, "pullEnds": False}

        def variant(name, p):
            r = json.loads(json.dumps(a))
            if p is not None:
                r["meta"]["post"] = p
            path = os.path.join(self.tmp, name)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False)
            return path
        p_none, p_new, p_new2, p_pull = variant("n.json", None), variant("a.json", post), variant("b.json", post), variant("c.json", dict(post, pullEnds=True))
        res = quiet(E.cmd_compare, p_none, p_new)
        self.assertIn(E.POST_NOTE, res["warnings"])
        self.assertEqual(res["postNote"], E.POST_NOTE)
        self.assertIn("行の後処理が違う結果どうしです", res["postNote"])
        self.assertIn(E.POST_NOTE, quiet(E.cmd_compare, p_new, p_pull)["warnings"])
        p_571, p_join0 = variant("d.json", dict(post, joinGap=0.5)), variant("e.json", dict(post, joinGap=0.0))
        for x, y in ((p_new, p_571), (p_571, p_join0)):   # 2 周目より前の印(joinGap が無い)・つなぐすき間が違う
            self.assertIn(E.POST_NOTE, quiet(E.cmd_compare, x, y)["warnings"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            E.cmd_compare(p_new, p_none)
        self.assertIn(E.POST_NOTE, buf.getvalue())
        for x, y in ((p_new, p_new2), (p_none, p_none)):
            res = quiet(E.cmd_compare, x, y)
            self.assertNotIn("postNote", res)
            self.assertNotIn(E.POST_NOTE, res["warnings"])

    def test_compare_same_docs(self):
        a = quiet(E.main, ["stored", "--data", self.data, "--label", "a"])
        pa = os.path.join(self.data, "evals", "asr", sorted(os.listdir(os.path.join(self.data, "evals", "asr")))[0])
        same = quiet(E.cmd_compare, pa, pa)
        self.assertEqual(same["diff"], 0)
        self.assertIn("差があるとは言えない", same["verdict"])
        # B: 置換の誤りを直した結果(文書を1本足して、文書ごとの差が出るように)
        b = json.loads(json.dumps(a))
        for g in b["groups"]:
            g["sub"] = 0
        pb = os.path.join(self.tmp, "b.json")
        with open(pb, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False)
        out = quiet(E.cmd_compare, pa, pb)
        self.assertLess(out["diff"], 0)                                   # B の方が誤りが少ない
        self.assertEqual(out["docs"], 1)


def ms(y, m, d, h=12):
    """この PC の時刻の日時 -> ミリ秒(--since・--until は日付をこの PC の時刻で読む)"""
    return int(datetime.datetime(y, m, d, h).timestamp() * 1000)


def pseg(i, a, b, text, at=None):
    """校正済みの行(proofedAt = 初めて校正済みにした時刻。at が None なら付けない = 以前の文書)"""
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


class EvalAsrSelectTest(unittest.TestCase):
    """マスタープラン Q3: 時期で分ける・出どころ(評価用・普段・友人)・下書きのエンジンの注意・エンジン別の集計・少ないデータ"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_sel_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        self.intake = os.path.join(self.tmp, "intake")
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0"
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

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def stored(self, *argv):
        return quiet(E.main, ["stored", "--data", self.data, "--intake", self.intake, "--no-save", *argv])

    def ids(self, res):
        return sorted(res["meta"]["docs"])

    def printed(self, res):
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        return out.getvalue()

    # ---------------- 時期

    def test_doc_time_is_max_proofed_at_then_updated_at(self):
        d = {"segments": [pseg(1, 0, 1, "a", 100), pseg(2, 1, 2, "b", 300), pseg(3, 2, 3, "c")], "updatedAt": 999}
        self.assertEqual(E.doc_time(d), (300, "proofedAt"))                       # 行の proofedAt の最大
        self.assertEqual(E.doc_time(dict(d, segments=[seg(1, 0, 1, "a")])), (999, "updatedAt"))   # 無ければ updatedAt
        self.assertEqual(E.doc_time({"segments": [seg(1, 0, 1, "a", proofed=False)]}), (None, ""))
        # 校正済みでない行の proofedAt(外した行の残り)は数えない
        self.assertEqual(E.doc_time({"segments": [dict(seg(1, 0, 1, "a", proofed=False), proofedAt=500)], "updatedAt": 7}), (7, "updatedAt"))

    def test_since_until(self):
        every = ["dddddddddd01", "dddddddddd03", "dddddddddd04", "eeeeeeeeee01", "eeeeeeeeee02"]   # 時期が分からない dddddddddd02 は、時期の指定がなければ数える
        res = self.stored("--scope", "all")
        self.assertEqual(self.ids(res), sorted(every + ["dddddddddd02"]))
        # --since: その日を含む。eeeeeeeeee01 は行の proofedAt の最大(09-10)で決まる(最初の行 09-01 ではない)
        res = self.stored("--scope", "all", "--since", "2026-09-10")
        self.assertEqual(self.ids(res), ["dddddddddd01", "dddddddddd04", "eeeeeeeeee01", "eeeeeeeeee02"])
        self.assertEqual((res["meta"]["since"], res["meta"]["selection"]["unknownTime"], res["meta"]["selection"]["excludedByTime"]), ("2026-09-10", 1, 1))
        res = self.stored("--scope", "all", "--since", "2026-09-11")
        self.assertNotIn("eeeeeeeeee01", self.ids(res))
        # --until: その日の終わりまで含む(updatedAt が 10-02 の昼でも 10-02 を含む)
        res = self.stored("--scope", "all", "--until", "2026-10-02")
        self.assertEqual(self.ids(res), ["dddddddddd03", "eeeeeeeeee01", "eeeeeeeeee02"])
        res = self.stored("--scope", "all", "--since", "2026-09-11", "--until", "2026-10-02")
        self.assertEqual(self.ids(res), ["eeeeeeeeee02"])
        self.assertEqual(self.stored("--scope", "all", "--since", "2026-10-05")["meta"]["docs"], [])
        # 結果の「正解のデータの版」は選んだ文書で決まる(時期を変えれば別の正解 = compare が警告する)
        self.assertNotEqual(res["meta"]["dataFingerprint"], self.stored("--scope", "all")["meta"]["dataFingerprint"])
        with self.assertRaises(SystemExit):
            self.stored("--since", "10/01")

    # ---------------- 出どころ

    def test_source_choices(self):
        self.assertEqual(self.ids(self.stored()), ["eeeeeeeeee01", "eeeeeeeeee02"])                                    # 既定は今までどおり評価用だけ
        self.assertEqual(self.ids(self.stored("--source", "eval")), ["eeeeeeeeee01", "eeeeeeeeee02"])
        daily = ["dddddddddd01", "dddddddddd02", "dddddddddd03", "dddddddddd04"]
        self.assertEqual(self.ids(self.stored("--source", "daily")), daily)
        self.assertEqual(self.ids(self.stored("--scope", "train")), daily)                                             # 古い --scope も同じ
        self.assertEqual(self.ids(self.stored("--source", "all")), sorted(daily + ["eeeeeeeeee01", "eeeeeeeeee02"]))   # 友人の zip が無ければ自分の文書だけ
        self.assertEqual(self.ids(self.stored("--source", "friend")), [])
        res = self.stored("--source", "daily", "--docs", "eeeeeeeeee01")                                              # --docs は出どころより優先
        self.assertEqual(self.ids(res), ["eeeeeeeeee01"])
        src = {d["id"]: d["source"] for d in self.stored("--source", "all")["summary"]["byDoc"]}
        self.assertEqual((src["dddddddddd01"], src["eeeeeeeeee01"]), ("daily", "eval"))

    def make_zip(self, name, wid, rows, raw_segments, exported="2026-10-02T10:00:00+0900"):
        """友人の送る用 zip(形は src/ytt_core/evaldata.py)を作って eval_import で取り込む"""
        common = {"format": EI.ev.FORMAT, "formatVersion": EI.ev.FORMAT_VERSION, "workId": wid}
        parts = {"final.json": dict(common, rows=rows),
                 "asr_raw.json": dict(common, run=run_rec(), segments=raw_segments),
                 "meta.json": dict(common, rulesVersion=EI.ev.RULES_VERSION, streamer="テスト配信者", performers=[], sourceName="clip.mp4", exportedAt=exported)}
        path = os.path.join(self.tmp, name)
        with zipfile.ZipFile(path, "w") as z:
            for fn, obj in parts.items():
                z.writestr(fn, json.dumps(obj, ensure_ascii=False))
            z.writestr("audio.flac", b"fLaC")
            z.writestr("edits.jsonl", b"")
        res = EI.import_zip(path, self.intake, no_train=set())
        self.assertEqual(res["result"], "imported", res)

    def friend_fixture(self):
        def row(i, a, b, text, checked=True):
            return {"id": "r%d" % i, "start": a, "end": b, "text": text, "speaker": "", "checked": checked, "tags": [], "raw": [i - 1]}
        rows = [row(1, 0, 4, "こんにちは"), row(2, 4, 6, "[笑]"), row(3, 6, 9, "未確認の行", checked=False), row(4, 9, 12, "【笑】あ"), row(5, 12, 15, "これはテスト[?]")]
        raw = [{"start": 0, "end": 4, "text": "こんにちわ"}, {"start": 4, "end": 6, "text": "あはは"}, {"start": 6, "end": 9, "text": "みかくにん"},
               {"start": 9, "end": 12, "text": "あ"}, {"start": 12, "end": 15, "text": "これはてすと"}]
        self.make_zip("2026-10-01_配信者_abcdef012345.zip", "abcdef012345", rows, raw)
        # 確認済みの行が 1 つも無い作業 = 作業ごと外れる(数えない)
        self.make_zip("2026-10-01_配信者_abcdef012346.zip", "abcdef012346", [row(1, 0, 4, "あ", checked=False)], raw[:1])

    def test_friend_zip(self):
        self.friend_fixture()
        res = self.stored("--source", "friend")
        self.assertEqual(self.ids(res), ["abcdef012345"])
        self.assertEqual(res["meta"]["mismatch"], [])
        self.assertEqual([x["id"] for x in res["meta"]["selection"]["friendSkipped"]], ["abcdef012346"])
        self.assertIn("作業ごと", res["meta"]["selection"]["friendSkipped"][0]["why"])
        o = res["summary"]["overall"]
        # 数えるのは「こんにちは」だけ: 形式違いの記号の行・未確認の行は校正済みにしない。[笑] だけ・[?] の行は聞き取れない扱いで数えない
        self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (5, 1, 0, 0))
        d = res["summary"]["byDoc"][0]
        self.assertEqual((d["source"], d["draft"], d["timeBasis"]), ("friend", "faster-whisper large-v3 v1.0", "exportedAt"))
        self.assertTrue(d["draftBias"])
        # 友人の zip は all に入る・時期は書き出した時刻(10-02)で分ける
        self.assertIn("abcdef012345", self.ids(self.stored("--source", "all")))
        self.assertEqual(self.ids(self.stored("--source", "friend", "--since", "2026-10-03")), [])
        self.assertEqual(self.ids(self.stored("--source", "friend", "--until", "2026-10-02")), ["abcdef012345"])
        # 友人の zip は --scope all(自分の文書だけ)には入らない
        self.assertNotIn("abcdef012345", self.ids(self.stored("--scope", "all")))
        docs, skipped = E.load_friend_docs(self.intake)
        self.assertTrue(docs[0]["sourcePath"].endswith("audio.flac"))      # run で認識し直す音声(作業ごとの audio.flac)
        self.assertEqual(len(skipped), 1)

    # ---------------- 下書きのエンジン

    def test_draft_bias_rules(self):
        ev_doc = {"_source": "eval", "recognition": {"runs": [run_rec()]}}
        daily = {"recognition": {"runs": [run_rec(), run_rec("whisper.cpp", kind="range")]}}
        self.assertEqual(E.draft_bias(ev_doc, E.STORED), "")                                    # 評価用は丁寧に校正してあるので注意しない
        self.assertIn("下書きそのもの", E.draft_bias(daily, E.STORED))                             # 保存した出力を測るのは下書きを測ること
        self.assertIn("モデルも同じ", E.draft_bias(daily, {"engine": "faster-whisper", "model": "large-v3"}))
        self.assertIn("モデルは違う", E.draft_bias(daily, {"engine": "faster-whisper", "model": "small"}))
        self.assertEqual(E.draft_bias(daily, {"engine": "whisper.cpp", "model": "large-v3"}), "")   # 下書きは最初の認識(再認識の記録 kind ではない)
        self.assertEqual(E.draft_bias({}, {"engine": "faster-whisper", "model": "large-v3"}), "")   # 記録が無ければ分からない
        self.assertEqual(E.draft_of({"recognition": {"runs": [run_rec("whisper.cpp", kind="range")]}})["engine"], "whisper.cpp")   # 再認識の記録しか無ければそれ
        self.assertIsNone(E.draft_of({}))

    def test_stored_marks_draft(self):
        res = self.stored("--source", "all")
        bias = {b["id"]: b["note"] for b in res["summary"]["draftBias"]}
        self.assertEqual(sorted(bias), ["dddddddddd01", "dddddddddd02", "dddddddddd03", "dddddddddd04"])   # 評価用は出ない
        by = {d["id"]: d for d in res["summary"]["byDoc"]}
        self.assertEqual((by["eeeeeeeeee01"]["draft"], by["dddddddddd01"]["draft"], by["dddddddddd02"]["draft"]),
                         ("faster-whisper large-v3 v1.0", "whisper.cpp large-v3 v1.0", E.DRAFT_NONE))
        self.assertEqual(by["dddddddddd03"]["draft"], "faster-whisper large-v3 v1.0")                   # 下書き = 最初の認識(あとの再認識ではない)
        self.assertEqual(res["summary"]["byDraft"]["whisper.cpp large-v3 v1.0"]["docs"], 2)
        text = self.printed(res)
        self.assertIn("下書きそのもの", text)
        self.assertIn("下書き: whisper.cpp large-v3 v1.0 ※", text)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_is_hint_free_and_warns_same_draft_engine(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
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
            # 自分で付けた --glossary は渡す。評価用だけのときは今までどおり設定の用語集・下書きの注意は付かない
            res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff01", "--glossary", "あ、い"])
            self.assertEqual(res["meta"]["engine"]["glossary"], ["あ", "い"])
            res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff03"])
            self.assertEqual((res["meta"]["engine"]["glossary"], res["meta"]["engine"]["hintFree"], res["summary"]["draftBias"]), (["トワ", "スバル"], False, []))
            # 辞書(置換・学習)は常に使わない
            S = E.load_serve("fake")
            args = type("A", (), dict(glossary=None, beam=None, model=None, engine="faster-whisper", vad=None, boost=None, device="auto", temp0=False))()
            spec = E.run_spec(S, args, {"glossary": "トワ"}, hint_free=True)
            self.assertEqual((spec["glossary"], spec["autoDict"], spec["autoLearned"]), ([], False, False))
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    # ---------------- エンジン・設定ごと

    def test_group_by_engine(self):
        res = self.stored("--source", "all", "--group-by", "engine")
        g = res["summary"]["byGroup"]
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
        self.assertIn("--group-by engine", self.printed(res))
        # run では、比べるエンジンは全部同じなので、下書きを作ったエンジンで分ける(group_spec)
        title, key_of = E.group_spec(type("A", (), {"group_by": "model"})(), "run")
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
        self.assertTrue(res["summary"]["lowData"])
        self.assertEqual(res["summary"]["proofedSec"], 16.0)               # 8 秒 × 2 本
        self.assertIn("まだ少ない(参考)", self.printed(res))
        # 校正済みが 15 分に届けば外れる
        self.write("bbbbbbbbbb01", evalSet=True, segments=[pseg(1, 0, 900, "長い行のテスト文章です")], original=[{"start": 0, "end": 900, "text": "長い行のテスト文章です"}])
        res = self.stored("--docs", "bbbbbbbbbb01")
        self.assertEqual((res["summary"]["lowData"], res["summary"]["proofedSec"]), (False, 900.0))
        self.assertNotIn("まだ少ない", self.printed(res))
        res = self.stored("--docs", "bbbbbbbbbb01,eeeeeeeeee01", "--group-by", "model")      # 組ごとにも出す(組の校正済みが少なければ参考)
        self.assertEqual({k: v["lowData"] for k, v in res["summary"]["byGroup"].items()}, {E.DRAFT_NONE: False, "faster-whisper large-v3 v1.0": True})


class EvalAsrReviewedTest(unittest.TestCase):
    """確かめ済み(evalReviewed = 動画を全部聞いて直した印)の文書は、動画全体が正解。--reviewed の選び分け・確かめ済みが 0 本のときの戻り"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_rev_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        # 人の行は 10〜14 と 30〜33(足した行 = 機械が出していない)。機械は 0〜3(ええと)と 50〜54(ご視聴…)に人の行の無い所へ出した
        self.human = [seg(1, 10.0, 14.0, "こんにちは"), seg(2, 30.0, 33.0, "足した行")]
        self.machine = [{"start": 0.0, "end": 3.0, "text": "ええと"}, {"start": 10.0, "end": 14.0, "text": "こんにちは"},
                        {"start": 50.0, "end": 54.0, "text": "ご視聴ありがとう"}]
        self.write("aaaaaaaaaa01", evalSet=True, evalReviewed={"at": 5, "rows": 2, "durationSec": 60.0, "via": "drill"}, segments=self.human, original=self.machine)
        self.write("bbbbbbbbbb01", evalSet=True, segments=self.human, original=self.machine)        # 同じ中身で確かめ済みの印なし
        self.write("dddddddddd01", segments=self.human, original=self.machine)                     # 普段の文書(評価用でない)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def stored(self, *argv):
        return quiet(E.main, ["stored", "--data", self.data, "--intake", os.path.join(self.tmp, "intake"), "--no-save", *argv])

    def by_doc(self, res):
        return {d["id"]: d for d in res["summary"]["byDoc"]}

    def printed(self, res):
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        return out.getvalue()

    def test_reviewed_doc_is_scored_over_the_whole_video(self):
        res = self.stored()                                    # 評価用の既定は only = 確かめ済みの動画だけ
        self.assertEqual(res["meta"]["docs"], ["aaaaaaaaaa01"])
        self.assertEqual(res["meta"]["mismatch"], [])           # 画面の測定との照合は、今までの規則で数え直した方で行う(確かめ済みは画面と数が違って当たり前)
        o = res["summary"]["overall"]
        extra = len("ええと") + len("ご視聴ありがとう")
        self.assertEqual((o["sub"], o["del"], o["ins"]), (0, len("足した行"), extra))   # 人の行の無い所の機械の文字 = 余分・機械の無い所の人の行 = 抜け
        self.assertEqual(o["refChars"], len("こんにちは足した行"))
        rv = res["summary"]["reviewed"]
        self.assertEqual(rv, {"docs": 1, "sec": 60.0, "refChars": 9, "missChars": 4, "extraChars": extra, "extraOutsideChars": extra})
        self.assertEqual(res["summary"]["proofedSec"], 60.0)    # 動画の長さ(すき間まで聞いた)
        self.assertEqual(res["summary"]["byKind"]["人が消した(余分)"]["ins"], extra)
        self.assertTrue(self.by_doc(res)["aaaaaaaaaa01"]["reviewed"])
        self.assertTrue(all(g["whole"] for g in res["groups"]))
        # 時刻によらない CER も全体の文字で(ええと + こんにちは + ご視聴ありがとう と、こんにちは + 足した行)
        S = E.load_serve("fake")
        a, b, c = S.lev_counts(S.norm_cer("こんにちは足した行"), S.norm_cer("ええとこんにちはご視聴ありがとう"))
        dt = res["summary"]["docText"]
        self.assertEqual((dt["refChars"], dt["sub"], dt["del"], dt["ins"]), (9, a, b, c))
        self.assertIn("確かめ済み 1 本", self.printed(res))

    def test_unreviewed_doc_is_scored_as_before(self):
        res = self.stored("--reviewed", "ignore")              # 印を見ない = 今までどおり。校正した行の範囲(10〜33)の外の機械の文字は数えない
        self.assertEqual(sorted(res["meta"]["docs"]), ["aaaaaaaaaa01", "bbbbbbbbbb01"])
        for d in res["summary"]["byDoc"]:
            self.assertEqual((d["sub"], d["del"], d["ins"]), (0, 4, 0), d["id"])
        self.assertEqual(res["summary"]["reviewed"]["docs"], 0)
        self.assertFalse(any(g.get("whole") for g in res["groups"]))
        self.assertEqual(res["summary"]["proofedSec"], 2 * (4.0 + 3.0))   # 人の行があるまとまりの幅だけ
        # 確かめ済みでない文書(prefer の中)も同じ
        res = self.stored("--reviewed", "prefer")
        d = self.by_doc(res)
        self.assertEqual((d["bbbbbbbbbb01"]["del"], d["bbbbbbbbbb01"]["ins"]), (4, 0))
        self.assertEqual(d["aaaaaaaaaa01"]["ins"], len("ええと") + len("ご視聴ありがとう"))

    def test_reviewed_choices(self):
        ids = lambda res: sorted(res["meta"]["docs"])
        self.assertEqual(ids(self.stored()), ["aaaaaaaaaa01"])                                           # 既定(評価用)= only
        self.assertEqual(ids(self.stored("--reviewed", "only")), ["aaaaaaaaaa01"])
        self.assertEqual(ids(self.stored("--reviewed", "prefer")), ["aaaaaaaaaa01", "bbbbbbbbbb01"])     # 確かめ済みは全体で・ほかも混ぜる
        self.assertEqual(ids(self.stored("--reviewed", "ignore")), ["aaaaaaaaaa01", "bbbbbbbbbb01"])
        res = self.stored("--reviewed", "prefer")
        self.assertEqual(res["summary"]["proofedSec"], 60.0 + 7.0)                                       # 確かめ済みは動画の長さ・ほかは人の行の幅
        self.assertEqual(self.stored("--source", "daily")["meta"]["selection"]["reviewed"]["mode"], "prefer")      # 評価用以外は prefer
        self.assertEqual(ids(self.stored("--source", "daily")), ["dddddddddd01"])
        allres = self.stored("--source", "all")                                                          # 評価用 + 普段: prefer(確かめ済みの印は評価用の文書だけ)
        self.assertEqual(ids(allres), ["aaaaaaaaaa01", "bbbbbbbbbb01", "dddddddddd01"])
        self.assertEqual(allres["summary"]["reviewed"]["docs"], 1)
        res = self.stored("--docs", "bbbbbbbbbb01")                                                      # --docs を渡したら only にしない(指定した文書を落とさない)
        self.assertEqual((ids(res), res["meta"]["selection"]["reviewed"]["mode"]), (["bbbbbbbbbb01"], "prefer"))
        self.assertEqual(self.stored()["meta"]["selection"]["reviewed"], {"mode": "only", "effective": "only", "candidates": 2, "reviewedDocs": 1, "fallback": False})

    def test_only_falls_back_when_nothing_is_reviewed(self):
        os.unlink(os.path.join(self.data, "transcripts", "aaaaaaaaaa01.json"))
        res = self.stored()
        self.assertEqual(res["meta"]["docs"], ["bbbbbbbbbb01"])                                           # 今までどおりの選び方
        self.assertEqual(res["meta"]["selection"]["reviewed"], {"mode": "only", "effective": "ignore", "candidates": 1, "reviewedDocs": 0, "fallback": True})
        self.assertEqual(res["summary"]["reviewed"]["docs"], 0)
        self.assertEqual(res["summary"]["overall"]["ins"], 0)
        self.assertIn("確かめ済みの動画が 0 本", self.printed(res))
        self.assertNotIn("確かめ済みの動画が 0 本", self.printed(self.stored("--reviewed", "prefer")))   # 戻りの注意は only のときだけ

    def test_silent_reviewed_docs(self):
        # 行の無い確かめ済みの文書 = 何も話していない。機械が出した文字はすべて余分。機械も出していなければ誤りなし(本数と秒には数える)
        self.write("aaaaaaaaaa02", evalSet=True, evalReviewed={"at": 5, "rows": 0, "durationSec": 30.0}, segments=[], original=[{"start": 5.0, "end": 8.0, "text": "幻覚の文"}])
        self.write("aaaaaaaaaa03", evalSet=True, evalReviewed={"at": 5, "rows": 0, "durationSec": 20.0}, segments=[], original=[])
        res = self.stored("--docs", "aaaaaaaaaa02,aaaaaaaaaa03")
        d = self.by_doc(res)
        self.assertEqual((d["aaaaaaaaaa02"]["ins"], d["aaaaaaaaaa02"]["refChars"]), (len("幻覚の文"), 0))
        self.assertNotIn("aaaaaaaaaa03", d)                                                              # 文字が無いので byDoc には出ない
        rv = res["summary"]["reviewed"]
        self.assertEqual((rv["docs"], rv["sec"], rv["extraChars"], rv["missChars"]), (2, 50.0, 4, 0))
        self.assertEqual(res["summary"]["proofedSec"], 50.0)
        # 印を見ない(ignore)なら、行の無い文書は測る正解が無いので外れる
        self.assertEqual(self.stored("--docs", "aaaaaaaaaa02", "--reviewed", "ignore")["meta"]["docs"], [])

    def test_human_row_without_machine_is_miss_even_when_original_is_empty(self):
        self.write("aaaaaaaaaa04", evalSet=True, evalReviewed={"at": 5, "rows": 1, "durationSec": 20.0}, segments=[seg(1, 2.0, 5.0, "全部抜けた")], original=[])
        res = self.stored("--docs", "aaaaaaaaaa04")
        o = res["summary"]["overall"]
        self.assertEqual((o["refChars"], o["del"], o["ins"]), (5, 5, 0))
        self.assertEqual(res["summary"]["reviewed"]["missChars"], 5)
        self.assertEqual(res["meta"]["mismatch"], [])

    def test_accuracy_keys_unchanged(self):
        """入口の自動の測定(src/home/accuracy.py の summarize_asr)が読む鍵: summary.overall(cer・refChars)・ci95・byDoc・lowData・proofedSec"""
        res = self.stored()
        s = res["summary"]
        for k in ("overall", "ci95", "byDoc", "lowData", "proofedSec"):
            self.assertIn(k, s)
        for k in ("cer", "refChars"):
            self.assertIn(k, s["overall"])
        root = os.path.join(os.path.dirname(HERE), "src")   # ツールと ytt_core の置き場所(src/home/accuracy.py を読む)
        for p in (os.path.join(root, "home"), root):
            if p not in sys.path:
                sys.path.insert(0, p)
        import accuracy
        out = accuracy.summarize_asr(res)
        self.assertEqual((out["chars"], out["proofedSec"]), (s["overall"]["refChars"], 60))


class EvalAsrGateRepeatTest(unittest.TestCase):
    """量の関門(gate_of・表示・compare の判定)と、run --repeat N(N 回の認識の中央)。認識は偽(recognize_doc を差し替える)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_gate_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        self.orig_recognize = E.recognize_doc
        # メモリの最大は実行のたびに揺れる(35MB / 36MB)。出力を突き合わせる試験のため固定する
        self.orig_peak = E.peak_memory_mb
        E.peak_memory_mb = lambda: 0
        self.write("aaaaaaaaaa01", 60.0)

    def tearDown(self):
        E.recognize_doc = self.orig_recognize
        E.peak_memory_mb = self.orig_peak
        os.environ.pop("TRANSCRIBE_BACKEND", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, dur):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja", "speakers": [],
               "updatedAt": 1, "evalSet": True, "evalReviewed": {"at": 5, "rows": 1, "durationSec": dur, "via": "drill"},
               "segments": [seg(1, 10.0, 14.0, "こんにちは")], "original": [{"start": 10.0, "end": 14.0, "text": "こんにちは"}]}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def script(self, plan):
        """認識の偽物: 呼ばれた順に plan の要素(文字 = その文字を出す・Exception = 認識できない)を使う。呼ばれた文書の id を calls に残す"""
        calls = []

        def fake(S, doc, spec, data):
            item = plan[len(calls)]
            calls.append(doc["id"])
            if isinstance(item, Exception):
                raise item
            return [{"start": 10.0, "end": 14.0, "text": item}], 60.0, 1.0, "動画", "cpu"
        E.recognize_doc = fake
        return calls

    def run_cmd(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = E.main(["run", "--data", self.data, "--intake", os.path.join(self.tmp, "intake"), "--no-save", *argv])
        return res, buf.getvalue()

    def stored(self):
        return quiet(E.main, ["stored", "--data", self.data, "--intake", os.path.join(self.tmp, "intake"), "--no-save"])

    def printed(self, res):
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        return out.getvalue()

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

    def test_gate_line(self):
        self.assertEqual(E.gate_line(E.gate_of(972)), "関門: G1(定点 16.2 分)・次の G2 まであと 13.8 分")
        self.assertEqual(E.gate_line(E.gate_of(0)), "関門: まだ(定点 0 分)")
        self.assertEqual(E.gate_line(E.gate_of(180)), "関門: まだ(定点 3 分)・次の G0 まであと 2 分")
        self.assertEqual(E.gate_line(E.gate_of(4000)), "関門: G3(定点 66.7 分)")

    def test_gate_in_stored_and_run_summary(self):
        res = self.stored()
        self.assertEqual(res["summary"]["gate"], E.gate_of(60.0))                       # 確かめ済み 60 秒 = まだ(G0 の 5 分に届かない)
        self.assertIn("関門: まだ(定点 1 分)・次の G0 まであと 4 分", self.printed(res))
        self.write("aaaaaaaaaa02", 900.0)
        res = self.stored()
        self.assertEqual(res["summary"]["gate"]["gate"], "G1")                          # 60 + 900 = 16 分
        self.assertIn("関門: G1(定点 16 分)・次の G2 まであと 14 分", self.printed(res))
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
        res = self.stored()
        self.assertEqual(res["summary"]["gate"], {"gate": None, "sec": 0.0, "next": "G0", "nextSec": 300})
        out = self.printed(res)
        self.assertIn("関門: まだ(定点 0 分)\n", out)
        self.assertNotIn("次の G0", out)

    def make_result(self, path, sec, errs, with_gate=True):
        """compare が読む最小の結果。errs = 文書ごとの誤り字数(正解は 100 字ずつ)"""
        summary = {"byTag": {}, "byKind": {}}
        if with_gate:
            summary["gate"] = E.gate_of(sec)
        groups = [{"doc": "d%d" % i, "sub": e, "del": 0, "ins": 0, "refChars": 100} for i, e in enumerate(errs)]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"meta": {"dataFingerprint": "x"}, "summary": summary, "groups": groups}, f)
        return path

    def test_compare_gate_verdict(self):
        pa = self.make_result(os.path.join(self.tmp, "a.json"), 3600, [10, 10, 10, 10, 10, 10])
        # 文書によって良くも悪くもなる = 範囲が 0 をまたぐ → 決められない。関門は小さい方(定点 15 分 = G1)
        pb = self.make_result(os.path.join(self.tmp, "b.json"), 900, [2, 18, 3, 17, 10, 10])
        out = quiet(E.cmd_compare, pa, pb)
        self.assertEqual(out["gate"]["gate"], "G1")
        self.assertIn("この量では決められない(分からない)", out["gateVerdict"])
        self.assertIn("G1", out["gateVerdict"])
        self.assertIn("エンジンの決定", out["gateVerdict"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            E.cmd_compare(pa, pb)
        self.assertIn(out["gateVerdict"], buf.getvalue())
        # どの文書も良くなる = 範囲が 0 より下 → 改善の側(今までの鍵は残る)
        pc = self.make_result(os.path.join(self.tmp, "c.json"), 1800, [4, 5, 6, 5, 4, 6])
        better = quiet(E.cmd_compare, pa, pc)
        self.assertEqual(better["gate"]["gate"], "G2")
        self.assertIn("改善 の側", better["gateVerdict"])
        self.assertNotIn("決められない", better["gateVerdict"])
        for k in ("a", "b", "docs", "cerA", "cerB", "diff", "ci95", "verdict", "warnings", "byDoc"):
            self.assertIn(k, better)
        worse = quiet(E.cmd_compare, pc, pa)
        self.assertIn("悪化 の側", worse["gateVerdict"])
        # 定点が 5 分に届かない結果が混ざれば「まだ」
        pd = self.make_result(os.path.join(self.tmp, "d.json"), 60, [4, 5, 6, 5, 4, 6])
        self.assertIn("まだ", quiet(E.cmd_compare, pa, pd)["gateVerdict"])
        # 関門の無い(古い)結果なら、関門の行を出さない(判定の鍵も付けない)
        old = self.make_result(os.path.join(self.tmp, "old.json"), 3600, [10, 10, 10, 10, 10, 10], with_gate=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = E.cmd_compare(old, pb)
        self.assertNotIn("gate", res)
        self.assertNotIn("関門", buf.getvalue())
        self.assertIn("verdict", res)

    # ---- --repeat

    def test_repeat_picks_median_run(self):
        # 回ごとの CER: こんにちわ(置換 1 / 5 字 = 20%)・こんにちは(0%)・こんばんは(置換 2 = 40%)→ 中央は 1 回目(20%)
        self.script(["こんにちわ", "こんにちは", "こんばんは"])
        res, out = self.run_cmd("--repeat", "3")
        rp = res["meta"]["repeat"]
        self.assertEqual(rp["n"], 3)
        self.assertEqual(rp["cers"], [0.2, 0.0, 0.4])
        self.assertEqual(rp["median"], 0)
        self.assertEqual(rp["spread"], 0.4)
        self.assertTrue(rp["complete"])
        self.assertEqual(rp["docs"], [1, 1, 1])
        self.assertEqual(res["summary"]["overall"]["cer"], 0.2)                    # 本体は代表の回の結果(今までと同じ形)
        self.assertEqual(res["groups"][0]["hyp"], "こんにちわ")
        self.assertEqual(rp["docTextCers"], [0.2, 0.0, 0.4])
        self.assertIn("3 回の CER: 20.0% / 0.0% / 40.0%(幅 40.0 pt)・代表は 1 回目", self.printed(res))
        # 順番が違っても、中央の回を選ぶ
        self.script(["こんばんは", "こんにちわ", "こんにちは"])
        res, _ = self.run_cmd("--repeat", "3")
        self.assertEqual((res["meta"]["repeat"]["median"], res["summary"]["overall"]["cer"]), (1, 0.2))

    def test_repeat_even_takes_smaller_middle_and_ties_go_first(self):
        # 20% 0% 40% 20% → 並べると 0%(2 回目)・20%(1 回目)・20%(4 回目)・40%。中央の 2 つの小さい方 = 1 回目(同じ CER は早い回が先)
        self.script(["こんにちわ", "こんにちは", "こんばんは", "こんにちわ"])
        res, _ = self.run_cmd("--repeat", "4")
        self.assertEqual(res["meta"]["repeat"]["median"], 0)
        self.script(["こんにちわ", "こんにちは"])                               # 2 回: 小さい方(CER が低い 2 回目)
        res, _ = self.run_cmd("--repeat", "2")
        self.assertEqual((res["meta"]["repeat"]["median"], res["summary"]["overall"]["cer"]), (1, 0.0))

    def test_repeat_one_is_same_as_before(self):
        self.script(["こんにちわ", "こんにちわ"])
        base, out1 = self.run_cmd()
        one, out2 = self.run_cmd("--repeat", "1")
        self.assertNotIn("repeat", base["meta"])
        self.assertNotIn("repeat", one["meta"])
        self.assertEqual(base["summary"], one["summary"])
        self.assertEqual(base["groups"], one["groups"])
        self.assertEqual(out1, out2)
        self.assertNotIn("回の CER", self.printed(one))
        self.assertNotIn("意味が薄い", out2)
        with self.assertRaises(SystemExit):
            self.run_cmd("--repeat", "0")

    def test_repeat_with_temp0_warns_but_runs(self):
        self.script(["こんにちは", "こんにちは"])
        res, out = self.run_cmd("--repeat", "2", "--temp0")
        self.assertIn("--temp0", out)
        self.assertIn("意味が薄い", out)
        self.assertEqual(res["meta"]["repeat"]["n"], 2)
        self.script(["こんにちは"])
        _res, out = self.run_cmd("--temp0")
        self.assertNotIn("意味が薄い", out)

    def test_repeat_with_dropped_doc_is_flagged(self):
        self.write("aaaaaaaaaa02", 60.0)
        # 1 回目: 2 本とも認識できた / 2 回目: 2 本目が落ちた / 3 回目: 2 本とも
        boom = RuntimeError("音声が見つかりません")
        calls = self.script(["こんにちは", "こんにちは", "こんにちは", boom, "こんにちわ", "こんにちわ"])
        res, out = self.run_cmd("--repeat", "3")
        rp = res["meta"]["repeat"]
        self.assertEqual(len(calls), 6)
        self.assertFalse(rp["complete"])
        self.assertEqual(rp["docs"], [2, 1, 2])
        self.assertIn("回ごとに数えた文書がそろっていません", out)
        self.assertIn("2 本 / 1 本 / 2 本", out)
        # 選ぶときの CER は全部の回にある文書だけで出す(aaaaaaaaaa01 だけ): 0%・0%・20% → 中央は 2 回目
        self.assertEqual(rp["cers"], [0.0, 0.0, 0.2])
        self.assertEqual(rp["median"], 1)
        self.assertIn("そろっていない", self.printed(res))
        # 全部そろっていれば注意は出ない
        self.script(["こんにちは"] * 6)
        res, out = self.run_cmd("--repeat", "3")
        self.assertTrue(res["meta"]["repeat"]["complete"])
        self.assertNotIn("そろっていません", out)


class EvalAsrOriginTest(unittest.TestCase):
    """定点の出どころ別(編集前・ショート。計画 3-3): origin_of・summary.origins・表示の 2 行・--group-by origin・compare の食い違いの注意"""

    CLIP = {"schema": "youtube-tools-clip/v1", "source": {"kind": "youtube", "videoId": "abcdefghijk"}}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_origin_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, dur, heard="こんにちは", **kw):
        """確かめ済みの評価用の文書(正解は「こんにちは」。機械の出力が heard)"""
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja", "speakers": [],
               "updatedAt": 1, "evalSet": True, "evalReviewed": {"at": 5, "rows": 1, "durationSec": dur, "via": "drill"},
               "segments": [seg(1, 10.0, 14.0, "こんにちは")], "original": [{"start": 10.0, "end": 14.0, "text": heard}], **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def stored(self, *argv):
        return quiet(E.main, ["stored", "--data", self.data, "--intake", os.path.join(self.tmp, "intake"), "--no-save", *argv])

    def printed(self, res):
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        return out.getvalue()

    def test_origin_of(self):
        self.assertEqual(E.origin_of({"clip": self.CLIP}), "raw")
        self.assertEqual(E.origin_of({"clip": {"source": {"videoId": "x"}}}), "raw")
        self.assertEqual(E.origin_of({"clip": {"source": {"kind": "local"}}}), "raw")          # videoId が無くても kind があれば編集前
        self.assertEqual(E.origin_of({}), "short")                                              # clip が無い = ショート
        for clip in (None, "x", [], {}, {"source": None}, {"source": {}}, {"source": "x"}, {"source": {"videoId": ""}}):
            self.assertEqual(E.origin_of({"clip": clip}), "short")
        self.assertEqual(E.origin_of(None), "short")

    def test_summary_origins_both(self):
        self.write("aaaaaaaaaa01", 300.0, heard="こんにちわ", clip=self.CLIP)   # 編集前: 置換 1 / 5 字 = 20%
        self.write("bbbbbbbbbb01", 120.0)                                       # ショート: 全部合う
        res = self.stored()
        og = res["summary"]["origins"]
        self.assertEqual(sorted(og), ["raw", "short"])
        self.assertEqual((og["raw"]["docs"], og["raw"]["ids"], og["raw"]["reviewedSec"], og["raw"]["cer"]), (1, ["aaaaaaaaaa01"], 300.0, 0.2))
        self.assertEqual((og["short"]["docs"], og["short"]["reviewedSec"], og["short"]["cer"]), (1, 120.0, 0.0))
        self.assertEqual((og["raw"]["sub"], og["raw"]["del"], og["raw"]["ins"], og["raw"]["refChars"]), (1, 0, 0, 5))
        self.assertIn("docText", og["raw"])                                                     # 時刻によらない CER も
        # 全体の数字・既存の鍵はそのまま(src/home/accuracy.py が読む)
        self.assertEqual(res["summary"]["overall"]["refChars"], 10)
        for k in ("overall", "ci95", "byDoc", "lowData", "proofedSec", "gate", "reviewed", "byKind"):
            self.assertIn(k, res["summary"])
        self.assertEqual({d["id"]: d["origin"] for d in res["summary"]["byDoc"]}, {"aaaaaaaaaa01": "raw", "bbbbbbbbbb01": "short"})
        out = self.printed(res)
        self.assertIn("  編集前: 1 本・5 分・CER 20.0%", out)
        self.assertIn("  ショート: 1 本・2 分・CER 0.0%", out)

    def test_summary_origins_one_side_only(self):
        self.write("bbbbbbbbbb01", 120.0)
        res = self.stored()
        self.assertEqual(list(res["summary"]["origins"]), ["short"])                           # ある方だけ
        out = self.printed(res)
        self.assertNotIn("編集前:", out)                                                        # 両方あるときだけ表示する
        self.assertNotIn("ショート:", out)
        self.write("aaaaaaaaaa01", 120.0, clip=self.CLIP)
        os.unlink(os.path.join(self.data, "transcripts", "bbbbbbbbbb01.json"))
        self.assertEqual(list(self.stored()["summary"]["origins"]), ["raw"])

    def test_group_by_origin(self):
        self.write("aaaaaaaaaa01", 300.0, heard="こんにちわ", clip=self.CLIP)
        self.write("bbbbbbbbbb01", 120.0)
        res = self.stored("--group-by", "origin")
        by = res["summary"]["byGroup"]
        self.assertEqual(sorted(by), ["ショート", "編集前"])
        self.assertEqual((by["編集前"]["cer"], by["ショート"]["cer"], by["編集前"]["docs"]), (0.2, 0.0, 1))
        self.assertIn("出どころごと", res["summary"]["groupBy"])

    def make_result(self, path, raw_errs, short_errs, origins=True):
        """compare が読む最小の結果。raw の文書は r0.. / short の文書は s0..(正解は 100 字ずつ)"""
        ids = {"raw": ["r%d" % i for i in range(len(raw_errs))], "short": ["s%d" % i for i in range(len(short_errs))]}
        groups = [{"doc": i, "sub": e, "del": 0, "ins": 0, "refChars": 100} for k, errs in (("raw", raw_errs), ("short", short_errs)) for i, e in zip(ids[k], errs)]
        summary = {"byTag": {}, "byKind": {}}
        if origins:
            summary["origins"] = {k: {"ids": v, "docs": len(v)} for k, v in ids.items() if v}
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"meta": {"dataFingerprint": "x"}, "summary": summary, "groups": groups}, f)
        return path

    def compare(self, a, b):
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = E.cmd_compare(a, b)
        return res, buf.getvalue()

    def path(self, name):
        return os.path.join(self.tmp, name)

    def test_compare_origin_conflict_is_noted(self):
        pa = self.make_result(self.path("a.json"), [10, 10, 10], [10, 10, 10])
        # 編集前は良くなる(-8 pt)・ショートは悪くなる(+2 pt)・全体は良くなる(-3 pt)→ ショートの向きが食い違う
        pb = self.make_result(self.path("b.json"), [2, 2, 2], [12, 12, 12])
        res, out = self.compare(pa, pb)
        self.assertLess(res["diff"], 0)
        self.assertEqual(res["origins"]["raw"]["diff"], -0.08)
        self.assertEqual((res["origins"]["short"]["diff"], res["origins"]["short"]["cerA"], res["origins"]["short"]["cerB"]), (0.02, 0.1, 0.12))
        self.assertEqual((res["origins"]["raw"]["docs"], len(res["origins"]["raw"]["ci95"])), (3, 2))
        self.assertEqual((res["origins"]["raw"]["conflict"], res["origins"]["short"]["conflict"]), (False, True))
        self.assertEqual(res["originConflict"], ["short"])
        self.assertIn("ショートで向きが食い違っています", res["originNote"])
        self.assertIn("採らない", out)
        self.assertIn("編集前 3 本: A 10.0% → B 2.0%", out)
        for k in ("a", "b", "docs", "cerA", "cerB", "diff", "ci95", "verdict", "warnings", "byDoc"):   # 今までの鍵はそのまま
            self.assertIn(k, res)

    def test_compare_origin_agreeing_has_no_note(self):
        pa = self.make_result(self.path("a.json"), [10, 10, 10], [10, 10, 10])
        pb = self.make_result(self.path("b.json"), [2, 2, 2], [8, 8, 8])                        # どちらも良くなる
        res, out = self.compare(pa, pb)
        self.assertEqual(res["originConflict"], [])
        self.assertNotIn("originNote", res)
        self.assertNotIn("食い違", out)
        self.assertIn("ショート 3 本", out)
        # 小さい差(0.5 pt に届かない)は向きを見ない
        pc = self.make_result(self.path("c.json"), [2, 2, 2], [10, 10, 10])                      # ショートは差 0
        self.assertEqual(self.compare(pa, pc)[0]["originConflict"], [])

    def test_compare_single_doc_origin_has_no_range(self):
        pa = self.make_result(self.path("a.json"), [10, 10, 10], [10])
        pb = self.make_result(self.path("b.json"), [2, 2, 2], [10])
        res, out = self.compare(pa, pb)
        self.assertIsNone(res["origins"]["short"]["ci95"])
        self.assertIn("範囲は出せない", out)

    def test_compare_old_result_without_origins_works_as_before(self):
        pa = self.make_result(self.path("a.json"), [10, 10, 10], [10, 10, 10], origins=False)
        pb = self.make_result(self.path("b.json"), [2, 2, 2], [12, 12, 12])
        for x, y in ((pa, pb), (pb, pa), (pa, pa)):                                              # 片方・両方が古くても落ちない・出どころの鍵は付かない
            res, out = self.compare(x, y)
            self.assertNotIn("origins", res)
            self.assertNotIn("originConflict", res)
            self.assertNotIn("食い違", out)
            self.assertIn("verdict", res)

    def test_compare_origin_only_in_both_results_is_shown(self):
        pa = self.make_result(self.path("a.json"), [10, 10, 10], [10])
        pb = self.make_result(self.path("b.json"), [2, 2, 2], [])                                # ショートは B に無い
        res, _ = self.compare(pa, pb)
        self.assertEqual(list(res["origins"]), ["raw"])


def sg(i, a, b, text, **kw):
    """seg に話者・noSub などの項目を足した行"""
    g = seg(i, a, b, text)
    g.update(kw)
    return g


class EvalAsrNoSubOverlapTest(unittest.TestCase):
    """字幕に出さない行(noSub)の別集計と、重なりのまとまりの別集計(overlap・nonOverlap)。noSub も重なりも無い文書は今までと同じ数"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_nosub_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, "evalSet": True, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def stored(self, *argv):
        return quiet(E.main, ["stored", "--data", self.data, "--intake", os.path.join(self.tmp, "intake"), "--no-save", "--reviewed", "ignore", *argv])

    def test_no_nosub_no_overlap_is_zero_and_numbers_unchanged(self):
        self.write("aaaaaaaaaa01", segments=[sg(1, 0.0, 4.0, "まつりが来た")], original=[{"start": 0.0, "end": 4.0, "text": "祭りが来た"}])
        res = self.stored()
        s = res["summary"]
        self.assertEqual(res["meta"]["mismatch"], [])
        self.assertEqual((s["overall"]["refChars"], s["overall"]["sub"], s["overall"]["del"], s["overall"]["ins"]), (6, 1, 1, 0))
        self.assertEqual(s["overlap"], {"groups": 0, "sec": 0, "refChars": 0, "cer": None, "miss": 0})
        self.assertEqual(s["nonOverlap"], {"refChars": 6, "cer": s["overall"]["cer"]})
        self.assertEqual((s["noSub"]["docs"], s["noSub"]["rows"], s["noSub"]["sec"], s["noSub"]["machineChars"]), (0, 0, 0, 0))
        self.assertTrue(all("ovl" not in g for g in res["groups"]))

    def test_nosub_rows_and_machine_chars_are_separate(self):
        machine = [{"start": 0.0, "end": 4.0, "text": "こんにちは"}, {"start": 10.0, "end": 14.0, "text": "ゲームのセリフです"}, {"start": 50.0, "end": 54.0, "text": "ご視聴"}]
        base = [sg(1, 0.0, 4.0, "こんにちは")]
        self.write("aaaaaaaaaa01", evalReviewed={"at": 5, "rows": 1, "durationSec": 60.0, "via": "drill"}, segments=base, original=machine)       # noSub の行なし
        self.write("bbbbbbbbbb01", evalReviewed={"at": 5, "rows": 2, "durationSec": 60.0, "via": "drill"},
                   segments=base + [sg(2, 10.0, 14.0, "ゲームのセリフ", speaker="S2", noSub=True)], original=machine)
        res = quiet(E.main, ["stored", "--data", self.data, "--intake", os.path.join(self.tmp, "intake"), "--no-save"])
        by = {d["id"]: d for d in res["summary"]["byDoc"]}
        self.assertEqual(res["meta"]["mismatch"], [])
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
        segs = [sg(1, 0.0, 3.0, "あいうえお", speaker="A"), sg(2, 1.0, 4.0, "かきくけこ", speaker="B"), sg(3, 10.0, 12.0, "ふつうの行", speaker="A")]
        machine = [{"start": 0.0, "end": 4.0, "text": "かきくけこあいうえお"}, {"start": 10.0, "end": 12.0, "text": "ふつうの行"}]
        self.write("aaaaaaaaaa01", segments=segs, original=machine)
        res = self.stored()
        s = res["summary"]
        self.assertEqual(res["meta"]["mismatch"], [])
        self.assertEqual(s["overlap"], {"groups": 1, "sec": 4.0, "refChars": 10, "cer": 0.0, "miss": 0})   # 並べ方を入れ替えた小さい方 = 誤りなし
        self.assertEqual(s["nonOverlap"], {"refChars": 5, "cer": 0.0})
        o = s["overall"]                                                                                 # 主な数字は今までの数え方(開始時刻の順)のまま = 誤りが出る
        self.assertEqual(o["refChars"], 15)
        self.assertGreater(o["errs"], 0)
        g = next(g for g in res["groups"] if "ovl" in g)
        self.assertEqual(g["ovl"]["sub"] + g["ovl"]["del"] + g["ovl"]["ins"], 0)
        self.assertGreater(g["sub"] + g["del"] + g["ins"], 0)

    def test_overlap_miss_counts_deleted_chars(self):
        segs = [sg(1, 0.0, 3.0, "あいうえお", speaker="A"), sg(2, 1.0, 4.0, "かきくけこ", speaker="B")]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 4.0, "text": "あいうえお"}])   # 片方しか書かなかった
        s = self.stored()["summary"]
        self.assertEqual((s["overlap"]["groups"], s["overlap"]["miss"], s["overlap"]["cer"]), (1, 5, 0.5))

    def test_overlap_needs_different_speakers_and_0_3_sec(self):
        self.write("aaaaaaaaaa01", segments=[sg(1, 0.0, 3.0, "あいう", speaker="A"), sg(2, 1.0, 4.0, "えおか", speaker="A")], original=[{"start": 0.0, "end": 4.0, "text": "あいうえおか"}])
        self.assertEqual(self.stored()["summary"]["overlap"]["groups"], 0)                              # 同じ話者
        self.write("aaaaaaaaaa01", segments=[sg(1, 0.0, 1.29, "あいう", speaker="A"), sg(2, 1.0, 4.0, "えおか", speaker="B")], original=[{"start": 0.0, "end": 4.0, "text": "あいうえおか"}])
        self.assertEqual(self.stored()["summary"]["overlap"]["groups"], 0)                              # 0.29 秒
        self.write("aaaaaaaaaa01", segments=[sg(1, 0.0, 1.3, "あいう", speaker="A"), sg(2, 1.0, 4.0, "えおか", speaker="B")], original=[{"start": 0.0, "end": 4.0, "text": "あいうえおか"}])
        self.assertEqual(self.stored()["summary"]["overlap"]["groups"], 1)                              # 0.3 秒ちょうど

    def test_nosub_is_removed_before_counting_overlap(self):
        """字幕に出さない行は先に外す: ゲーム音声と重なっても重なりのまとまりにならない"""
        segs = [sg(1, 0.0, 3.0, "あいう", speaker="A"), sg(2, 1.0, 4.0, "ゲーム", speaker="G", noSub=True)]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 3.0, "text": "あいう"}, {"start": 1.0, "end": 4.0, "text": "ゲーム"}])
        s = self.stored()["summary"]
        self.assertEqual(s["overlap"]["groups"], 0)
        self.assertEqual(s["noSub"]["rows"], 1)

    def test_print_and_compare_show_overlap(self):
        segs = [sg(1, 0.0, 3.0, "あいうえお", speaker="A"), sg(2, 1.0, 4.0, "かきくけこ", speaker="B"), sg(3, 10.0, 12.0, "ふつうの行", speaker="A")]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 4.0, "text": "かきくけこあいうえお"}, {"start": 10.0, "end": 12.0, "text": "ふつう行"}])
        res = self.stored()
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        self.assertIn("重なりのまとまり 1", out.getvalue())
        pa = os.path.join(self.tmp, "a.json")
        pb = os.path.join(self.tmp, "b.json")
        b = json.loads(json.dumps(res))
        for g in b["groups"]:
            if "ovl" in g:
                g["ovl"] = {"sub": 2, "del": 0, "ins": 0}
            else:
                g["del"] = 0
        for path, r in ((pa, res), (pb, b)):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False)
        cmp_ = quiet(E.cmd_compare, pa, pb)
        self.assertEqual(cmp_["overlap"]["groups"], 1)
        self.assertEqual((cmp_["overlap"]["cerA"], cmp_["overlap"]["cerB"]), (0.0, 0.2))
        self.assertEqual((cmp_["nonOverlap"]["cerA"], cmp_["nonOverlap"]["cerB"]), (0.2, 0.0))
        self.assertEqual(cmp_["nonOverlap"]["diff"], -0.2)
        # 重なりの無い結果どうしの compare には、重なりの欄を足さない(今までと同じ出力)
        self.write("aaaaaaaaaa01", segments=[sg(1, 0.0, 4.0, "あいう", speaker="A")], original=[{"start": 0.0, "end": 4.0, "text": "あいう"}])
        plain = self.stored()
        pp = os.path.join(self.tmp, "p.json")
        with open(pp, "w", encoding="utf-8") as f:
            json.dump(plain, f, ensure_ascii=False)
        c2 = quiet(E.cmd_compare, pp, pp)
        self.assertNotIn("overlap", c2)
        self.assertNotIn("nonOverlap", c2)

    def test_group_by_still_works_with_overlap(self):
        segs = [sg(1, 0.0, 3.0, "あいうえお", speaker="A"), sg(2, 1.0, 4.0, "かきくけこ", speaker="B")]
        self.write("aaaaaaaaaa01", segments=segs, original=[{"start": 0.0, "end": 4.0, "text": "あいうえお"}])
        res = self.stored("--group-by", "origin")
        self.assertEqual(list(res["summary"]["byGroup"]), ["ショート"])
        self.assertEqual(res["summary"]["overlap"]["groups"], 1)


if __name__ == "__main__":
    unittest.main()
