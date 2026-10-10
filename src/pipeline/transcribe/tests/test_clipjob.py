# -*- coding: utf-8 -*-
"""pipeline/transcribe/clipjob(文字起こしのジョブの機械の文書の行。役割で組み直す RS6 a-3 に human/proof/doc_jobs の run_job から切り出した)を、
編集の serve を読まずに疑似のエンジンで使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_clipjob.py -v

run_job が作っていた行(行の id・範囲の開始を足した時刻・要確認の印・学習した置換は original にも・置換辞書は segments だけ・単語の時刻・
「長い区間に文字が少ない」行の avg_logprob)と同じになることを、手で決めた期待値で確かめる。文字起こしの通し(文書・words.json・asr.json)は
編集のテスト(src/editor/tests/test_metrics.py ほか。serve の名前で読む)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend, clipjob, recognize, replace  # noqa: E402
from ytt import tools, txtext, workdata  # noqa: E402

ROWS = [   # 疑似のエンジンの行(取り出した音声の先頭からの秒)
    {"start": 0.0, "end": 2.0, "text": "こんにちはペコラです", "avg_logprob": -0.3, "no_speech_prob": 0.1, "compression_ratio": 1.2,
     "words": [(0.0, 1.0, "こんにちは"), (1.0, 2.0, "ペコラです")]},
    {"start": 2.0, "end": 9.0, "text": "黒", "avg_logprob": -0.8},
    {"start": 9.0, "end": 9.5, "text": "", "avg_logprob": -0.1},
]
SPEC = {"start": 100.0, "end": 110.0, "language": "ja", "wordSplit": False, "stripPunct": True, "glossary": [], "context": {"members": [], "terms": []},
        "autoFill": False, "autoLlm": False, "stripNames": False, "model": "small", "engine": "faster-whisper", "beam": 5, "vadMode": "weak", "boost": False}


class _FakeEngine(backend.Backend):
    name = "fake"

    def transcribe(self, job, spec, wav, total, real):
        job["state"] = "running"
        return iter([dict(r) for r in ROWS])


class TestMakeDocRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clipjob_")
        for mod, name, value in ((workdata, "TX_DIR", self.tmp), (tools, "media_duration", lambda path: 10.0),
                                 (recognize, "extract_audio", lambda job, spec, wav: None)):
            p = mock.patch.object(mod, name, value)
            p.start()
            self.addCleanup(p.stop)
        saved = backend._selector[0]
        backend.set_selector(lambda: _FakeEngine())
        self.addCleanup(backend.set_selector, saved)

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def run_rows(self, pairs=(), learned=None):
        job = {"id": "j1", "cancel": False, "state": "queued"}
        return job, clipjob.make_doc_rows(job, dict(SPEC), os.path.join(self.tmp, "w.wav"), list(pairs), learned)

    def test_rows_like_run_job(self):
        job, res = self.run_rows(pairs=[("ペコラ", "ぺこら")])
        self.assertEqual([g["id"] for g in res["segs"]], ["s1", "s2"])   # 文字の無い行は捨てる
        self.assertEqual([(g["start"], g["end"]) for g in res["segs"]], [(100.0, 102.0), (102.0, 109.0)])   # 範囲の開始を足す
        self.assertEqual(res["segs"][0]["text"], "こんにちはぺこらです")   # 置換辞書は segments だけ
        self.assertEqual(res["original"][0]["text"], "こんにちはペコラです")   # 機械の出力はそのまま
        self.assertEqual(res["original"][0]["avg_logprob"], -0.3)
        self.assertEqual(res["dictApplied"], 1)
        self.assertEqual(res["learnApplied"], 0)
        self.assertIn(txtext.SPARSE_FLAG, res["segs"][1]["flag"])   # 7 秒に 1 文字
        self.assertEqual(res["sparseLp"], {"s2": -0.8})
        self.assertEqual(res["words"], [[100.0, 101.0, "こんにちは"], [101.0, 102.0, "ペコラです"]])
        self.assertEqual(res["total"], 10.0)
        self.assertEqual(len(res["raw"]), 3)   # 生出力は整える前の行
        self.assertEqual((res["fill_rec"], res["names_n"], res["llm_rec"], res["llm_items"]), (None, 0, None, None))
        self.assertEqual(job["segments"], 2)

    def test_learned_replace_goes_to_original_too(self):
        def find(text):
            k = text.find("こんにちは")
            return [{"i": k, "wrong": "こんにちは", "right": "こんばんは"}] if k >= 0 else []
        _job, res = self.run_rows(learned=find)
        self.assertEqual(res["segs"][0]["text"], "こんばんはペコラです")
        self.assertEqual(res["original"][0]["text"], "こんばんはペコラです")   # 自分の置換を「人が直した」と数えない
        self.assertEqual(res["learnApplied"], 1)

    def test_auto_learned_replace_is_pure(self):
        self.assertEqual(replace.auto_learned_replace("あいう", lambda t: [{"i": 1, "wrong": "い", "right": "イイ"}]), ("あイイう", 1))
        self.assertEqual(replace.auto_learned_replace("あいう", lambda t: []), ("あいう", 0))


class TestImportsAlone(unittest.TestCase):
    def test_reads_no_flow_human_or_app(self):
        """① の clipjob は ② ③ と app を読まない(serve なしで import できる)"""
        code = ("import sys; sys.path.insert(0, %r); from pipeline.transcribe import clipjob; "
                "bad = [m for m in sys.modules if m.split('.')[0] in ('flow', 'human', 'manage', 'eval') or m == 'serve' or m.startswith('ed_')]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
