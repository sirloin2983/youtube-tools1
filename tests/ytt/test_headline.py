"""ytt/headline.py(届くパックの機械の見出しと選んだ理由。規則だけ。新機能 C・10-23)のテスト"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from ytt import headline as H  # noqa: E402


def row(a, b, text, **kw):
    return dict({"start": a, "end": b, "text": text}, **kw)


class TestHeadline(unittest.TestCase):
    def test_picks_emotional_line_near_peak(self):
        rows = [row(0, 2, "えっとじゃあ次の場所に行きますね"), row(10, 12, "うわ最悪だね!"), row(30, 32, "やばいこれは強い!!"),
                row(40, 41, "なんで"), row(50, 52, "カットした行やばい!!!", cut=True)]
        h = H.headline(rows, peak=13.0, reasons=["チャットが急増"])
        self.assertEqual((h["text"], h["by"]), ("「うわ最悪だね!」", "rule"))   # 山の近くの行に点(遠い「やばい」より上)・切った行・短い行は使わない
        self.assertIn("チャットが急増", h["why"])
        self.assertIn("叫び・驚き", h["why"])

    def test_filler_and_span_and_switch(self):
        rows = [row(0, 3, "ちょっと準備するからねみんな"), row(5, 8, "今日はゆっくり雑談していきます")]
        self.assertEqual(H.headline(rows)["text"], "「今日はゆっくり雑談していきます」")   # 「ちょっと」は感情の言葉に数えない
        self.assertEqual(H.headline(rows, span=(0, 4))["text"], "「ちょっと準備するからねみんな」")   # マークの区間の中の行だけ
        self.assertIsNone(H.headline([row(0, 1, "うん")]))   # 相づちだけ = 作らない
        long = H.headline([row(0, 9, "あ" * 40)])["text"]
        self.assertEqual(len(long), H.HEAD_MAX + 2)   # 「」の中は HEAD_MAX 字まで(… で切る)
        H.HEADLINE = False
        self.addCleanup(setattr, H, "HEADLINE", True)
        self.assertIsNone(H.headline(rows))


if __name__ == "__main__":
    unittest.main()
