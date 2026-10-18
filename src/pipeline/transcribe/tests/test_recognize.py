# -*- coding: utf-8 -*-
"""pipeline/transcribe/recognize(音声の取り出し・認識・範囲の行・全体の再認識の続きから。役割で組み直す RS2-7)を、編集の serve を読まずに使うテスト。

    py -3.12 -m unittest src/pipeline/transcribe/tests/test_recognize.py -v

認識の流れ(声の検出のやり直し・GPU から CPU・全体の区間ごとの続き)は編集のテスト(src/editor/tests/test_metrics.py・test_worker.py・test_whispercpp.py。
serve の名前で読む)が確かめる。ここは「① が serve なしで読めて、行の頭の名前を外す決まり(同じ ① の fill)と ffmpeg(ytt/tools)を読む」ことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import sys
import types
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from pipeline.transcribe import backend, fill, recognize, tx_engines  # noqa: E402
from ytt import errors, tools, workdata  # noqa: E402

SPEC = {"range": [10.0, 20.0], "language": "ja", "wordSplit": False}


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, prefix="txrecognize_")
        self.patch(workdata, "TX_DIR", self.tmp)
        self.patch(tools, "find_ffmpeg", lambda: None)

    def patch(self, mod, name, value):
        """mod.name を試験の間だけ value に(終わったら元に戻す。serve と同じプロセスで流しても壊さない)"""
        p = mock.patch.object(mod, name, value)
        p.start()
        self.addCleanup(p.stop)

class TestTranscribeRows(_Env):
    """transcribe_rows(RS2-8e): 取り出し → 長さ(ytt/tools の media_duration)→ backend.select().transcribe → 生出力を控えながら整えた行。serve なし"""

    def setUp(self):
        super().setUp()
        self.saved_selector = backend._selector[0]
        self.calls = []
        calls = self.calls

        class Fake(backend.Backend):
            name = "fake"

            def transcribe(self, job, spec, wav, total, real):
                calls.append(("transcribe", job["state"], wav, total, real is recognize._transcribe_checked))

                def gen():   # 生成器は遅延 = 認識が動くのは行を読む所
                    calls.append(("recognize", job["state"]))
                    yield {"start": 0.0, "end": 2.0, "text": "こんにちは。", "avg_logprob": -0.2}
                    yield {"start": 2.1, "end": 9.5, "text": "長さの外まで", "avg_logprob": -0.4}
                    yield {"start": 8.5, "end": 9.0, "text": "捨てる行"}
                return gen()
        backend.set_selector(lambda: Fake())

    def tearDown(self):
        backend.set_selector(self.saved_selector)
        super().tearDown()

    def extract(self, job, spec, wav):
        self.calls.append(("extract", job["state"], job["phase"], wav, spec["start"]))

    def test_rows_raw_total(self):
        self.patch(tools, "media_duration", lambda p: 8.0)
        job = {"state": "queued"}
        spec = {"start": 10.0, "end": 20.0, "language": "ja", "wordSplit": False, "stripPunct": True}
        with mock.patch.object(recognize, "extract_audio", self.extract):   # 呼ぶたびに recognize.extract_audio を読む(S.extract_audio の差し替えが届く)
            res = recognize.transcribe_rows(job, spec, "w.wav")
        self.assertEqual(self.calls[0], ("extract", "extracting", "音声を取り出し中", "w.wav", 10.0))
        self.assertEqual(self.calls[1], ("transcribe", "extracting", "w.wav", 8.0, True))
        self.assertEqual(self.calls[2][0], "recognize")
        self.assertEqual(res["total"], 8.0)
        self.assertIsInstance(res["t_rec"], float)
        self.assertEqual([(r["start"], r["end"], r["text"]) for r in res["raw"]],
                         [(10.0, 12.0, "こんにちは。"), (12.1, 19.5, "長さの外まで"), (18.5, 19.0, "捨てる行")])   # 生出力は整える前・元の動画の秒
        self.assertEqual([(r["start"], r["end"], r["text"]) for r in res["rows"]],
                         [(0.0, 2.1, "こんにちは"), (2.1, 8.0, "長さの外まで")])   # 長さの外を捨てて切る・続く行をつなぐ・句読点を除く(postproc.expand_segments)

    def test_total_falls_back_to_range(self):
        self.patch(tools, "media_duration", lambda p: None)
        with mock.patch.object(recognize, "extract_audio", self.extract):
            res = recognize.transcribe_rows({"state": "queued"}, {"start": 10.0, "end": 20.0, "language": "ja"}, "w.wav")
        self.assertEqual(res["total"], 10.0)   # 長さが分からなければ範囲の長さ(end が無ければ 0)
        self.assertEqual(len(res["rows"]), 3)


class TestFinishRangeLines(_Env):
    def test_head_stripper_from_app(self):
        raw = [{"start": 1.0, "end": 2.0, "text": "名前:こんにちは", "avg_logprob": -0.2}]

        def split(text):
            return (text.split(":", 1)[1], "印") if ":" in text else (text, None)
        self.patch(fill, "fill_head_stripper", lambda spec: None if spec.get("evalSet") else split)
        out = recognize.finish_range_lines(raw, SPEC, 10.0)
        self.assertEqual([(x["start"], x["end"], x["raw"], x["flag"]) for x in out], [(11.0, 12.0, "こんにちは", "印")])
        out = recognize.finish_range_lines(raw, dict(SPEC, evalSet=True), 10.0)   # 外さない(None)
        self.assertEqual(out[0]["raw"], "名前:こんにちは")

    def test_reads_fill_without_registration(self):
        """登録しなくても fill の決まりで外す(評価用は外さない)"""
        out = recognize.finish_range_lines([], SPEC, 0.0)
        self.assertEqual(out, [])


class TestWhole(_Env):
    def test_parts_and_key_follow_part_sec(self):
        self.assertEqual(recognize.whole_parts({"segments": []}, 0.0, 800.0), [[0.0, 800.0]])
        doc = {"segments": [{"start": 0.0, "end": 595.0}, {"start": 605.0, "end": 1300.0}]}
        self.assertEqual(recognize.whole_parts(doc, 0.0, 1300.0), [[0.0, 600.0], [600.0, 1300.0]])   # 行の無いすき間の真ん中で切る
        spec = {"tid": "abc", "range": [0.0, 1300.0], "model": "small", "language": "ja", "beam": 5, "vadMode": "weak"}
        k = recognize.whole_key(spec, {"sourcePath": ""})
        with mock.patch.object(recognize, "WHOLE_PART_SEC", 300):   # 差し替えはこのモジュールの値を読む所に効く
            self.assertNotEqual(recognize.whole_key(spec, {"sourcePath": ""}), k)
        recognize.write_resume("abc", {"key": k, "parts": [[0, 1]], "done": {}})
        self.assertEqual(recognize.resume_path("abc"), os.path.join(self.tmp, ".resume", "abc.whole.json"))
        self.assertEqual(recognize.read_resume("abc", k)["parts"], [[0, 1]])
        self.assertIsNone(recognize.read_resume("abc", "other"))
        recognize.drop_resume("abc")
        self.assertIsNone(recognize.read_resume("abc", k))


class TestAudio(_Env):
    def test_audio_span_and_no_ffmpeg(self):
        self.assertEqual(recognize.audio_span([{"start": 10.0, "end": 11.0}], 0.0, None), (6.7, 14.3))
        with self.assertRaises(errors.ApiError) as cm:
            recognize.extract_audio({}, {"start": 0.0, "end": None, "sourcePath": "x.mp4"}, os.path.join(self.tmp, "a.wav"))
        self.assertEqual(cm.exception.code, "no_ffmpeg")

    def test_extract_audio_args_unchanged(self):
        """OPT2: 音声を取り出す ffmpeg の引数の列(16kHz)は、引数を組む関数を 1 か所(wav_args)にしても 1 つも変わらない"""
        cmds = []

        def run(cmd, **kw):
            cmds.append(list(cmd))
            return 1, [], None
        wav = os.path.join(self.tmp, "a.wav")
        with mock.patch.object(recognize._tools, "find_ffmpeg", return_value="FF"), mock.patch.object(recognize._tools, "run_progress", side_effect=run):
            for spec in ({"start": 0.0, "end": None, "sourcePath": "x.mp4"}, {"start": 5.0, "end": 12.5, "sourcePath": "x.mp4", "boost": True}):
                with self.assertRaises(errors.ApiError):
                    recognize.extract_audio({}, spec, wav)
        head = ["FF", "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file"]
        tail = ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav]
        self.assertEqual(cmds, [head + ["-i", "x.mp4", "-vn"] + tail,
                                head + ["-ss", "5.000", "-i", "x.mp4", "-t", "7.500", "-vn", "-af", "highpass=f=70,dynaudnorm=f=200:g=15:m=15"] + tail])


class _Segs(list):
    """faster-whisper の行の生成器の代わり(for で読める・close できる)"""

    def close(self):
        pass


def _seg(text, start=0.0, end=2.0):
    return types.SimpleNamespace(start=start, end=end, text=text, words=[], avg_logprob=-0.2, no_speech_prob=0.1, compression_ratio=1.1)


class _VadFake:
    """声の検出の設定(vad_filter・vad_parameters)を読むエンジンの偽物。normal は 9 割捨てる・weak は残るが文字が出ない・off は文字が出る"""
    CAPS = tx_engines.FasterWhisper.CAPS
    params = {"vad_filter", "vad_parameters", "language", "beam_size", "condition_on_previous_text", "no_speech_threshold", "word_timestamps"}   # 受け付ける引数(worker が調べる一覧の代わり)

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kw):
        mode = "off" if not kw.get("vad_filter") else ("weak" if kw.get("vad_parameters", {}).get("threshold") == 0.3 else "normal")
        self.calls.append(mode)
        if mode == "normal":
            return _Segs([_seg("こんにちは")]), types.SimpleNamespace(duration=10.0, duration_after_vad=1.0)
        if mode == "weak":
            return _Segs([_seg("")]), types.SimpleNamespace(duration=10.0, duration_after_vad=8.0)
        return _Segs([_seg("こんにちは")]), types.SimpleNamespace(duration=10.0, duration_after_vad=10.0)


class _CapsFake:
    """声の検出の設定を受け取らない(CAPS に vad が無い)エンジンの偽物。文字が 1 つも出なくても 1 回しか認識しない"""
    CAPS = frozenset({"word_timestamps"})

    def __init__(self, engine=None):
        self.calls = []
        if engine is not None:
            self.engine = engine   # 認識ワーカーの代理(RemoteModel)と同じ形: エンジンの名前だけ持つ

    def transcribe(self, audio, **kw):
        self.calls.append(dict(kw))
        return _Segs([]), types.SimpleNamespace(duration=10.0, duration_after_vad=None)


class TestVadFallbackCaps(_Env):
    SPEC = dict(SPEC, vadMode="normal", beam=5)

    def test_caps_table(self):
        """エンジンごとの能力(CAPS)の表。根拠は tx_engines の各クラスのコメント(コードを読んで確かめた物だけ)"""
        self.assertEqual(tx_engines.FasterWhisper.CAPS, {"vad", "chunk", "hotwords", "word_timestamps"})
        self.assertEqual(tx_engines.WhisperCpp.CAPS, {"word_timestamps"})
        for cls in (tx_engines.SenseVoice, tx_engines.LlamaText, tx_engines._Qwen3Chunked, tx_engines.Engine):
            self.assertEqual(cls.CAPS, frozenset(), cls.__name__)
        self.assertEqual(tx_engines.LlamaQwen3.CAPS, {"hotwords"})
        self.assertEqual(tx_engines.caps_of("faster-whisper"), tx_engines.FasterWhisper.CAPS)
        self.assertEqual(tx_engines.caps_of(""), tx_engines.FasterWhisper.CAPS)   # 名前が空 = 既定
        self.assertIsNone(tx_engines.caps_of("no-such-engine"))
        self.assertIsNone(tx_engines.caps_of(object()))   # CAPS を持たない偽物は分からない扱い

    def test_faster_whisper_ladder_still_steps(self):
        """faster-whisper(CAPS に vad がある)では今までどおり、捨てすぎなら「標準→弱め」と段が進む"""
        model = _VadFake()
        raw, vad = recognize.transcribe_vad_fallback({"cancel": False}, model, "a.wav", dict(self.SPEC, vadMode="normal"))
        self.assertEqual(model.calls, ["normal", "weak", "off"])   # 標準は 9 割捨てる → 弱めは文字が 0 → なし
        self.assertEqual(vad["used"], "off")
        self.assertEqual([r["mode"] for r in vad["retries"]], ["normal", "weak"])
        self.assertIn("検出を緩めて", recognize.vad_note(vad))

    def test_object_without_caps_still_ladders(self):
        """CAPS を持たない物(能力が分からない)は今までどおり段を進める"""
        class Plain:
            params = {"vad_filter", "vad_parameters", "language", "beam_size", "condition_on_previous_text", "no_speech_threshold"}

            def __init__(self):
                self.calls = []

            def transcribe(self, audio, **kw):
                self.calls.append(kw.get("vad_filter"))
                return _Segs([_seg("こんにちは")]), types.SimpleNamespace(duration=10.0, duration_after_vad=None)
        model = Plain()
        raw, vad = recognize.transcribe_vad_fallback({"cancel": False}, model, "a.wav", dict(self.SPEC, vadMode="normal"))
        self.assertEqual(vad["used"], "normal")
        self.assertEqual(vad["retries"], [])
        self.assertEqual(model.calls, [True])

    def test_engine_without_vad_runs_once(self):
        """CAPS に vad が無いエンジンは、頼まれた段で 1 回だけ。文字が 0 でも緩めず、記録は unsupported・知らせは出ない"""
        model = _CapsFake()
        with mock.patch.object(recognize._txbase.log, "info") as info:
            raw, vad = recognize.transcribe_vad_fallback({"cancel": False}, model, "a.wav", dict(self.SPEC, vadMode="normal"))
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(raw, [])
        self.assertEqual(vad, {"requested": "normal", "used": "none", "unsupported": True, "removedSec": 0.0, "retries": []})
        self.assertEqual(recognize.vad_note(vad), "")
        info.assert_not_called()

    def test_remote_model_uses_engine_name(self):
        """認識ワーカーの代理(engine の名前だけ持つ)は、名前から能力を引く: whisper.cpp は 1 回だけ、faster-whisper は段を進める"""
        model = _CapsFake(engine="whisper.cpp")
        raw, vad = recognize.transcribe_vad_fallback({"cancel": False}, model, "a.wav", dict(self.SPEC, vadMode="weak"))
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(vad["unsupported"])
        self.assertEqual(vad["requested"], "weak")
        ladder = _VadFake()
        ladder.engine = "faster-whisper"
        recognize.transcribe_vad_fallback({"cancel": False}, ladder, "a.wav", dict(self.SPEC, vadMode="normal"))
        self.assertEqual(ladder.calls, ["normal", "weak", "off"])


if __name__ == "__main__":
    unittest.main()
