# -*- coding: utf-8 -*-
"""pipeline/transcribe/postproc(行の後処理と要確認の印。役割で組み直す RS2-4b)を、編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_postproc.py -v

細かい決まり(印の条件・行の分け方・つなぎ方の数字)は編集のテスト(src/editor/tests/test_metrics.py・test_whispercpp.py。serve の名前で読む)が確かめる。
ここは「① が serve なしで読めて同じ物が動く」ことと、読み込みでネイティブの部品・app・eval を読まないことだけ。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import subprocess
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import postproc, txbase, txenv  # noqa: E402


def _row(a, b, text, **kw):
    return {"start": a, "end": b, "text": text, **kw}


class TestFlags(unittest.TestCase):
    def test_sparse_and_stock_phrase(self):
        self.assertIn(postproc.SPARSE_FLAG, postproc.make_flags(_row(0, 7.2, "黒"), []))
        self.assertIn("よくある誤認識の文", postproc.make_flags(_row(0, 2.0, "ご視聴ありがとうございました"), []))
        self.assertEqual(postproc.make_flags(_row(0, 2.0, "こんにちは"), []), "")

    def test_leak_uses_roster(self):
        flag = postproc.make_flags(_row(0, 1.0, "ぺこら"), [], "ja", ["ぺこら"])
        self.assertIn(txbase.LEAK_FLAG, flag)


class TestRows(unittest.TestCase):
    def test_split_segment_by_word_gap(self):
        s = _row(0.0, 5.0, "あいうえお", words=[(0.0, 0.5, "あい"), (2.0, 2.5, "うえお")])
        out = postproc.split_segment(s)
        self.assertEqual([(o["start"], o["end"], o["text"]) for o in out], [(0.0, 0.5, "あい"), (2.0, 2.5, "うえお")])

    def test_expand_segments_clip_merge_join_strip(self):
        gen = [_row(0.0, 1.0, "こんにちは。"), _row(1.3, 2.0, "ああ"), _row(2.1, 2.5, "ああ"), _row(2.6, 3.0, "ああ"), _row(50.0, 60.0, "外")]
        out = list(postproc.expand_segments(gen, {}, dur=10.0))
        self.assertEqual([o["text"] for o in out], ["こんにちは", "ああああああ"])   # 長さの外を捨て・同じ文字の行をまとめ・句読点を除く
        self.assertEqual(out[0]["end"], 1.3)                                       # すき間 0.3 秒 ≤ JOIN_GAP でつなぐ
        self.assertEqual(out[1]["_rep"], 3)
        with mock.patch.object(postproc, "JOIN_GAP", 0.0):                       # 差し替えはこのモジュールの値を読む所に効く
            self.assertEqual(list(postproc.expand_segments(gen, {}, dur=10.0))[0]["end"], 1.0)

    def test_machine_conf_and_row_words(self):
        self.assertEqual(postproc.machine_conf({"avg_logprob": -0.123456, "no_speech_prob": float("nan"), "x": 1}), {"avg_logprob": -0.1235})
        self.assertEqual(postproc.row_words({"_words": [(0.0, 0.5, "あ")]}, 10.0), [[10.0, 10.5, "あ"]])

    def test_char_class(self):
        self.assertEqual([txbase.char_class(c) for c in "カ漢Aあ、"], ["K", "H", "A", "", ""])


class TestPostRecord(unittest.TestCase):
    def setUp(self):
        self.saved = dict(txenv._providers)

    def tearDown(self):
        txenv._providers.clear()
        txenv._providers.update(self.saved)

    def test_reads_version_from_txenv(self):
        txenv.register(SERVER_VERSION=lambda: "9.9.9")
        with mock.patch.object(postproc, "END_TRIM", 0.1):
            self.assertEqual(postproc.post_record(), {"version": "9.9.9", "endTrim": 0.1, "joinGap": postproc.JOIN_GAP})


class TestImportsAlone(unittest.TestCase):
    def test_no_native_app_or_eval(self):
        """postproc と兄弟(txenv・backend・roster・tx_engines・txbase・records(RS2-5)・worker_client(RS2-6)・recognize(RS2-7)・diarize(RS2-9))は、numpy などのネイティブの部品・serve などの app・eval を読まずに import できる
        (serve の import で読まれる = 編集のサーバーのプロセスにネイティブの部品を入れない決まり。src/editor/tests/test_worker.py と同じ)"""
        code = ("import sys; sys.path.insert(0, %r); "
                "from pipeline.transcribe import postproc, txenv, backend, roster, tx_engines, txbase, records, worker_client, recognize, diarize; "
                "native = ('numpy', 'faster_whisper', 'ctranslate2', 'sherpa_onnx', 'onnxruntime'); "
                "bad = [m for m in sys.modules if m in native or m.startswith('ed_') or m == 'serve' or m == 'eval' or m.startswith('eval.')]; "
                "print(bad); sys.exit(1 if bad else 0)") % SRC
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
