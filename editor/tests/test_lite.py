#!/usr/bin/env python3
"""友人用 文字起こし簡易版(docs/plan/friend-lite-plan.md)のサーバー側のテスト。
L1 = 共通コアの editor 側(GPU の精度の型・生出力 <id>.asr.json・話者のふちの色)。
L2 = 書き出し(ed_lite.py。Resolve 用ファイルと送る用 zip)。

    python -m unittest editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest editor/tests/test_lite.py      # これだけ
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import serve as S  # noqa: E402
import ed_jobs  # noqa: E402
import ed_store  # noqa: E402


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.tmp, os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class LiteCoreCompute(unittest.TestCase):
    def test_cuda_compute_env(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "int8_float16"}):
            self.assertEqual(ed_jobs.cuda_compute(), "int8_float16")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "rm -rf"}):
            self.assertEqual(ed_jobs.cuda_compute(), "float16")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRANSCRIBE_CUDA_COMPUTE", None)
            self.assertEqual(ed_jobs.cuda_compute(), "float16")   # 編集は今までどおり


class LiteCoreRaw(_Store):
    def test_capture_raw_keeps_words_and_probs(self):
        segs = [{"start": 0.0, "end": 1.5, "text": "えーこんにちは", "avg_logprob": -0.21234, "words": [(0.0, 0.4, "えー"), (0.5, 1.5, "こんにちは")],
                 "wordProbs": [0.5, 0.98]},
                {"start": 2.0, "end": 3.0, "text": "テスト"}]
        raw = []
        out = list(ed_jobs.capture_raw(iter(segs), raw, shift=10.0))
        self.assertEqual(out, segs)   # 流れはそのまま
        self.assertEqual(raw[0]["start"], 10.0)
        self.assertEqual(raw[0]["words"], [[10.0, 10.4, "えー", 0.5], [10.5, 11.5, "こんにちは", 0.98]])
        self.assertEqual(raw[0]["avg_logprob"], -0.2123)
        self.assertEqual(raw[1]["words"], [])

    def test_seg_to_dict_word_probs(self):
        class W:
            def __init__(self, a, b, t, p):
                self.start, self.end, self.word, self.probability = a, b, t, p

        class Sg:
            start, end, text = 0.0, 1.0, " あ い "
            words = [W(0.0, 0.5, "あ", 0.9), W(0.5, 1.0, "い", None)]
        d = ed_jobs.seg_to_dict(Sg())
        self.assertEqual(d["words"], [(0.0, 0.5, "あ"), (0.5, 1.0, "い")])   # 3つ組は変えない
        self.assertEqual(d["wordProbs"], [0.9, None])

    def test_write_read_asr(self):
        ed_jobs.write_asr("0123456789ab", [{"start": 0, "end": 1, "text": "x", "words": []}], {"model": "small"})
        d = ed_jobs.read_asr("0123456789ab")
        self.assertEqual(d["run"], {"model": "small"})
        self.assertEqual(len(d["segments"]), 1)
        self.assertIsNone(ed_jobs.read_asr("ffffffffffff"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
    def test_fake_job_writes_asr(self):
        src = os.path.join(self.tmp, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=9", "-ar", "16000", src], check=True)
        spec = ed_jobs.validate_job({"sourcePath": src, "model": "small"})
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0"}):
            job = ed_jobs.add_job(spec)
            ed_jobs._queue.get_nowait()   # 待機列のワーカーに取られないように、ここで直接動かす
            ed_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        d = ed_jobs.read_asr(job["tid"])
        self.assertTrue(d["segments"])
        self.assertEqual(d["segments"][0]["text"], "テスト文1")
        self.assertEqual(d["run"]["engine"], "fake")


class LiteCoreSpeakers(unittest.TestCase):
    def test_outline_saved(self):
        doc = ed_store.sanitize_transcript({"speakers": [{"id": "A", "name": "a", "color": "#ffe600", "outline": "#000000"},
                                                         {"id": "B", "name": "b", "color": "#ffffff", "outline": "red;x"}], "segments": []})
        self.assertEqual(doc["speakers"][0]["outline"], "#000000")
        self.assertNotIn("outline", doc["speakers"][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
