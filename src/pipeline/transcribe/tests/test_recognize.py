# -*- coding: utf-8 -*-
"""pipeline/transcribe/recognize(音声の取り出し・認識・範囲の行・全体の再認識の続きから。役割で組み直す RS2-7)を、編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_recognize.py -v

認識の流れ(声の検出のやり直し・GPU から CPU・全体の区間ごとの続き)は編集のテスト(src/editor/tests/test_metrics.py・test_worker.py・test_whispercpp.py。
serve の名前で読む)が確かめる。ここは「① が serve なしで読めて、行の頭の名前を外す決まりと ffmpeg を口(set_head_stripper・txenv)から読む」ことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend, recognize, txenv  # noqa: E402
from ytt import errors  # noqa: E402

SPEC = {"range": [10.0, 20.0], "language": "ja", "wordSplit": False}


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="txrecognize_")
        self.saved = (dict(txenv._providers), list(recognize._head_stripper))
        txenv.register(TX_DIR=lambda: self.tmp, find_ffmpeg=lambda: (lambda: None))

    def tearDown(self):
        txenv._providers.clear()
        txenv._providers.update(self.saved[0])
        recognize._head_stripper[:] = self.saved[1]
        shutil.rmtree(self.tmp, True)


class TestTranscribeRows(_Env):
    """transcribe_rows(RS2-8e): 取り出し → 長さ(txenv.media_duration)→ backend.select().transcribe → 生出力を控えながら整えた行。serve なし"""

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
        txenv.register(media_duration=lambda: (lambda p: 8.0))
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
        txenv.register(media_duration=lambda: (lambda p: None))
        with mock.patch.object(recognize, "extract_audio", self.extract):
            res = recognize.transcribe_rows({"state": "queued"}, {"start": 10.0, "end": 20.0, "language": "ja"}, "w.wav")
        self.assertEqual(res["total"], 10.0)   # 長さが分からなければ範囲の長さ(end が無ければ 0)
        self.assertEqual(len(res["rows"]), 3)


class TestFinishRangeLines(_Env):
    def test_head_stripper_from_app(self):
        raw = [{"start": 1.0, "end": 2.0, "text": "名前:こんにちは", "avg_logprob": -0.2}]

        def split(text):
            return (text.split(":", 1)[1], "印") if ":" in text else (text, None)
        recognize.set_head_stripper(lambda spec: None if spec.get("evalSet") else split)
        out = recognize.finish_range_lines(raw, SPEC, 10.0)
        self.assertEqual([(x["start"], x["end"], x["raw"], x["flag"]) for x in out], [(11.0, 12.0, "こんにちは", "印")])
        out = recognize.finish_range_lines(raw, dict(SPEC, evalSet=True), 10.0)   # 外さない(None)
        self.assertEqual(out[0]["raw"], "名前:こんにちは")

    def test_unregistered_is_an_error(self):
        recognize._head_stripper[:] = []
        with self.assertRaises(RuntimeError):
            recognize.finish_range_lines([], SPEC, 0.0)


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


if __name__ == "__main__":
    unittest.main()
