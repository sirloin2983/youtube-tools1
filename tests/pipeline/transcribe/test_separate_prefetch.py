"""pipeline/transcribe/separate.py の先回り(認識の前に裏の糸で声を分け始め、あとの voice_spans が同じ音の結果を使う。10-23)のテスト。
分ける本体(_separate_local)は差し替える(本物の分離の結果が同じことは scratchpad の評価用 23 本・本物 4 本で確かめた)"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402
from pipeline.transcribe import separate as SP  # noqa: E402


class TestPrefetch(unittest.TestCase):
    def setUp(self):
        self.wav = os.path.join(testkit.tempdir(self), "a.wav")
        with open(self.wav, "wb") as f:
            f.write(b"x" * 100)
        self.calls = []
        self.gate = threading.Event()

        def sep(job, wav):
            self.calls.append(wav)
            self.gate.wait(5)
            return [(1.0, 2.0)]
        p = mock.patch.object(SP, "_separate_local", sep)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(SP._pre.clear)

    def test_reuses_prefetched_result(self):
        SP.prefetch_local(self.wav)
        SP.prefetch_local(self.wav)   # 同じ音は 2 回始めない
        self.gate.set()
        self.assertEqual(SP._voice_spans_local({"cancel": False}, self.wav), [(1.0, 2.0)])
        self.assertEqual(len(self.calls), 1)   # 先回りの 1 回だけ = 後処理では分け直さない
        self.assertEqual(SP._pre, {})

    def test_changed_audio_is_separated_again(self):
        SP.prefetch_local(self.wav)
        self.gate.set()
        with open(self.wav, "ab") as f:   # 音が変わった(大きさ・更新日時)= 先回りは使わない
            f.write(b"y")
        self.assertEqual(SP._voice_spans_local({"cancel": False}, self.wav), [(1.0, 2.0)])
        self.assertEqual(len(self.calls), 2)

    def test_switch_off_and_fake_do_nothing(self):
        with mock.patch.object(SP, "SEP_PREFETCH", False):
            SP.prefetch({"cancel": False}, self.wav)
        with mock.patch.object(SP._backend, "is_fake", lambda: True):
            SP.prefetch({"cancel": False}, self.wav)
        self.assertEqual(SP._pre, {})


if __name__ == "__main__":
    unittest.main()
