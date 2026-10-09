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
from pipeline.transcribe import recognize, txenv  # noqa: E402
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
