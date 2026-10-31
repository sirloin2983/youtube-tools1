"""文字起こしの記号の決まり(src/pipeline/transcribe/symbols.py)の単体テスト: 句読点と記号を消す・例外(名簿の名前の中・Mr.・%・
数字の間・英字にはさまれた)は残す・「ー」「っ」「々」は字・確かめるで足した字(extra)は残す・鍵の形の往復。

実行(リポジトリ直下から): py -3.12 -m unittest tests/pipeline/transcribe/test_symbols.py -v
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pipeline.transcribe import symbols  # noqa: E402


def out(s, extra=None):
    return symbols.apply(s, extra)[0]


class SymbolsTest(unittest.TestCase):
    def test_removes_punct_and_symbols(self):
        self.assertEqual(out("え?何それ!すごい…。"), "え何それすごい")
        self.assertEqual(out("♪〜だよ♪「うん」#生スバル ×"), "だようん生スバル ")
        self.assertEqual(out("ナイスー、やったっ々"), "ナイスーやったっ々")   # ー っ 々 は字

    def test_exceptions(self):
        self.assertEqual(out("アーニャ・メルフィッサだよ"), "アーニャ・メルフィッサだよ")   # 名簿の名前の中
        self.assertEqual(out("あ・い"), "あい")
        self.assertEqual(out("0.5倍で3:00〜5:00、50%"), "0.5倍で3:00〜5:0050%")
        self.assertEqual(out("10/31"), "10/31")
        self.assertEqual(out("Mr.ハコスと A-B と rock'n"), "Mr.ハコスと A-B と rock'n")
        self.assertEqual(out("あ-い"), "あい")   # 英字にはさまれていない
        self.assertEqual(out("3〜あ"), "3あ")    # 数字の間でない

    def test_events(self):
        _o, ev = symbols.apply("0.5。")
        self.assertEqual([(e["ch"], e["kept"]) for e in ev], [(".", True), ("。", False)])
        self.assertTrue(ev[0]["why"])

    def test_extra_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            self.assertEqual(symbols.read_extra(p), {})
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"keep_chars": {"!": {"card": "c"}, "ab": {}}}, f)
            extra = symbols.read_extra(p)
            self.assertEqual(set(extra), {"!"})
            self.assertEqual(out("やった!", extra), "やった!")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{壊れ")
            os.utime(p, ns=(1, 1))
            self.assertEqual(symbols.read_extra(p), {})

    def test_code_roundtrip(self):
        self.assertEqual(symbols.code_of("、"), "u3001")
        self.assertEqual(symbols.char_of("u3001"), "、")
        for bad in ("u0041", "x3001", "u", "uzzzz", None, "u110000"):
            self.assertIsNone(symbols.char_of(bad), bad)


if __name__ == "__main__":
    unittest.main()
