#!/usr/bin/env python3
"""字幕の読む速さの印(T2)と、行の時刻を単語の時刻に合わせる候補(T1 の簡易版)のテスト(計算は pipeline/transcribe/retime.py・文書を読む包みは editor/ed_retime.py。RS2-9)。

    py -3.10 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest test_retime -q                 # これだけ(src/editor/tests で)

- 読む速さ: 文字の数え方・速い/短いの印・対象外(noSub・カット済・空の下書き・1 文字)・設定 subtitle.read。
  例は tests/subread_cases.json(画面の readMark も同じ例で確かめる = test_document_save.cjs)
- 時刻の候補 retime_candidates(純粋な関数): 当て方・人が足した文字・当たりが少ない・差が小さい・前後の行で詰める(同じ話者だけ)・
  伸ばしの単語・短すぎる・大きく動かした行・単語の途中・終わりの端を出さない
- API の本体 retime_doc: 単語の時刻が無い・候補・文書を書き換えない・行の指定の検査・serve の名前で呼べる
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, TID, StoreDir  # noqa: F401,E402  (S = serve)
import ed_retime as R  # noqa: E402  (文書を読む包み = retime_engine・retime_doc)
from pipeline.transcribe import retime  # noqa: E402  (計算 = subread_*・retime_candidates。RS2-9 から持ち主を直に読む。ed_retime に別名・転送は無い)
import ed_state  # noqa: E402

with open(os.path.join(TESTS, "subread_cases.json"), encoding="utf-8") as _f:
    CASES = json.load(_f)


def _row(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": ""}, **kw)


def _chars(t0, text, step=0.2):
    """1 文字ずつの単語(t0 から step 秒ずつ)"""
    return [[round(t0 + i * step, 3), round(t0 + (i + 1) * step, 3), ch] for i, ch in enumerate(text)]


class TestSubread(unittest.TestCase):
    def test_chars_same_as_screen(self):
        for text, n in CASES["chars"]:
            with self.subTest(text=text):
                self.assertEqual(retime.subread_chars(text), n)

    def test_marks_same_as_screen(self):
        for row, want in CASES["marks"]:
            with self.subTest(row=row):
                m = retime.subread_mark(row)
                self.assertEqual(None if m is None else [m["fast"], m["short"]], want)

    def test_mark_values(self):
        m = retime.subread_mark({"start": 1.0, "end": 1.4, "text": "あいうえおかき"})   # 7 文字 / 0.4 秒
        self.assertEqual((m["chars"], m["sec"], m["cps"]), (7, 0.4, 17.5))
        self.assertIsNone(retime.subread_mark({"start": 0, "end": 0, "text": "あ"}))      # 1 文字は数えない(長さ 0 でも)
        self.assertIsNone(retime.subread_mark("not a row"))

    def test_limits_from_settings(self):
        self.assertEqual(retime.subread_limits({}), {"fastCps": 10.0, "shortSec": 0.5})
        st = {"subtitle": {"orientation": "vertical", "read": {"fastCps": 14, "shortSec": 0.3}}}
        lim = retime.subread_limits(st)
        self.assertEqual(lim, {"fastCps": 14.0, "shortSec": 0.3})
        self.assertIsNone(retime.subread_mark({"start": 0, "end": 1.0, "text": "あいうえおかきくけこさ"}, lim))   # 11 字/秒 < 14
        for bad in ({"fastCps": 1}, {"fastCps": True}, {"shortSec": "0.3"}, {"shortSec": 9}, "x"):
            with self.subTest(bad=bad):
                self.assertEqual(retime.subread_limits({"subtitle": {"read": bad}}), {"fastCps": 10.0, "shortSec": 0.5})

    def test_subtitle_settings_unchanged(self):
        """設定の subtitle に read を足しても、今の subtitle_settings の結果(向き・文字数)は変わらない"""
        st = {"subtitle": {"orientation": "horizontal", "maxChars": {"vertical": 16, "horizontal": 28}, "read": {"fastCps": 12}}}
        self.assertEqual(S.subtitle_settings(st)["orientation"], "horizontal")
        self.assertNotIn("read", S.subtitle_settings(st))


class TestRetimeCandidates(unittest.TestCase):
    def test_moves_both_edges_to_words(self):
        words = _chars(1.0, "こんにちは")          # 1.0〜2.0
        c = retime.retime_candidates([_row(1, 0.5, 2.5, "こんにちは")], words)
        self.assertEqual(c, [{"id": "s1", "start": 1.0, "end": 2.0, "matched": 1.0, "dStart": 0.5, "dEnd": -0.5,
                              "edges": ["start", "end"], "from": {"start": 0.5, "end": 2.5}}])

    def test_folds_kana_and_punct(self):
        """寄せて比べる(カタカナ ↔ ひらがな・句読点・伸ばし)"""
        words = _chars(1.0, "コンニチハ、")
        c = retime.retime_candidates([_row(1, 1.4, 2.6, "こんにちは")], words)
        self.assertEqual((c[0]["start"], c[0]["end"]), (1.0, 2.2))   # 最後の「、」(寄せると何も残らない単語)まで終わりに含める

    def test_human_added_head_char_keeps_start(self):
        """人が足した頭の字(単語に無い)は当たらない → 開始は候補にしない(終わりだけ)"""
        words = _chars(1.0, "こんにちは")
        c = retime.retime_candidates([_row(1, 0.5, 2.5, "えっこんにちは")], words)
        self.assertEqual((c[0]["start"], c[0]["end"], c[0]["edges"]), (0.5, 2.0, ["end"]))
        self.assertAlmostEqual(c[0]["matched"], 5 / 7, places=3)

    def test_human_added_middle_char(self):
        words = _chars(1.0, "こんにちは")
        c = retime.retime_candidates([_row(1, 0.5, 2.5, "こんにわちは")], words)
        self.assertEqual((c[0]["start"], c[0]["end"]), (1.0, 2.0))

    def test_low_match_gives_nothing(self):
        words = _chars(1.0, "こんにちは")
        self.assertEqual(retime.retime_candidates([_row(1, 0.5, 2.5, "さようならまたね")], words), [])
        self.assertEqual(retime.retime_candidates([_row(1, 0.5, 2.5, "こんばんはみなさま")], words), [])   # 3/9 < 0.6

    def test_small_delta_gives_nothing(self):
        words = _chars(1.0, "こんにちは")
        self.assertEqual(retime.retime_candidates([_row(1, 0.95, 2.05, "こんにちは")], words), [])
        c = retime.retime_candidates([_row(1, 0.95, 2.4, "こんにちは")], words)
        self.assertEqual(c[0]["edges"], ["end"])

    def test_clamped_by_same_speaker_neighbor(self):
        """前の行と同じ話者(か話者なし)なら、重ならない所まで詰める。違う話者の行・字幕に出さない行とはそのまま重ねる"""
        words = _chars(0.0, "まえ") + _chars(0.8, "こんにちは")      # 「こ」は 0.8 から
        segs = [_row(1, 0.0, 1.0, "まえ", speaker="a"), _row(2, 1.3, 1.8, "こんにちは", speaker="a")]
        c = retime.retime_candidates(segs, words, ["s2"])
        self.assertEqual((c[0]["start"], c[0]["end"]), (1.0, 1.8))   # 0.8 → 前の行の終わり 1.0 まで
        segs[0]["speaker"] = "b"
        c = retime.retime_candidates(segs, words, ["s2"])
        self.assertEqual(c[0]["start"], 0.8)
        segs[0]["speaker"] = "a"
        segs[0]["noSub"] = True
        self.assertEqual(retime.retime_candidates(segs, words, ["s2"])[0]["start"], 0.8)
        segs[0].pop("noSub")
        segs[1]["speaker"] = ""                                            # 話者の無い行は重ならない側
        self.assertEqual(retime.retime_candidates(segs, words, ["s2"])[0]["start"], 1.0)

    def test_neighbor_candidates_do_not_cross(self):
        """両方の行に候補があっても、両方を採って重ならない"""
        words = _chars(0.0, "あいうえお") + _chars(1.0, "かきくけこ")
        segs = [_row(1, 0.0, 0.8, "あいうえおか"), _row(2, 1.4, 2.0, "かきくけこ")]   # 1 行目に「か」を足した(人)・2 行目の頭は 1.0
        c = {x["id"]: x for x in retime.retime_candidates(segs, words)}
        self.assertLessEqual(c["s1"]["end"], c["s2"]["start"])

    def test_long_vowel_word_extends_end(self):
        words = [[1.0, 1.5, "うわ"], [1.52, 2.4, "ー"], [2.45, 3.0, "天井"]]
        c = retime.retime_candidates([_row(1, 1.0, 1.5, "うわー")], words)
        self.assertEqual((c[0]["end"], c[0]["edges"]), (2.4, ["end"]))
        words[1][0] = 1.8                                                  # すき間が空いていれば含めない
        self.assertEqual(retime.retime_candidates([_row(1, 1.0, 1.3, "うわー")], words)[0]["end"], 1.5)

    def test_too_short_gives_nothing(self):
        words = [[1.0, 1.1, "あ"], [1.1, 1.2, "い"]]
        self.assertEqual(retime.retime_candidates([_row(1, 0.6, 1.6, "あい")], words), [])

    def test_moved_far_gives_nothing(self):
        words = _chars(10.0, "こんにちは")
        self.assertEqual(retime.retime_candidates([_row(1, 6.0, 7.0, "こんにちは")], words), [])

    def test_inside_multichar_word(self):
        """単語の途中の字は字数で割り振る(「こんにちは」1.0〜2.0 の 3 字目から)"""
        c = retime.retime_candidates([_row(1, 0.8, 2.5, "にちは")], [[1.0, 2.0, "こんにちは"]])
        self.assertEqual((c[0]["start"], c[0]["end"]), (1.4, 2.0))

    def test_end_edge_off(self):
        words = _chars(1.0, "こんにちは")
        c = retime.retime_candidates([_row(1, 0.5, 2.5, "こんにちは")], words, end_ok=False)
        self.assertEqual((c[0]["start"], c[0]["end"], c[0]["edges"]), (1.0, 2.5, ["start"]))

    def test_skips_blank_and_unknown(self):
        words = _chars(1.0, "こんにちは")
        segs = [_row(1, 0.5, 2.5, "", draft="overlap"), _row(2, 0.5, 2.5, "   "), _row(3, 0.5, 2.5, "こんにちは")]
        self.assertEqual([x["id"] for x in retime.retime_candidates(segs, words)], ["s3"])
        self.assertEqual(retime.retime_candidates(segs, words, ["nope"]), [])
        self.assertEqual(retime.retime_candidates(segs, []), [])

    def test_repeated_phrase_prefers_near_current_end(self):
        """同じ言葉が窓の中に 2 回あれば、今の行の終わりに近い方"""
        words = _chars(0.0, "はい") + _chars(1.2, "はい")
        c = retime.retime_candidates([_row(1, 1.0, 1.9, "はい")], words)
        self.assertEqual((c[0]["start"], c[0]["end"]), (1.2, 1.6))

    def test_engine(self):
        self.assertEqual(R.retime_engine({}), "faster-whisper")
        self.assertEqual(R.retime_engine({"recognition": {"runs": [{"kind": "alt", "engine": "x"}, {"engine": "whisper.cpp"}]}}), "whisper.cpp")


class TestRetimeApi(StoreDir):
    def setUp(self):
        super().setUp()
        self.doc = {"id": TID, "title": "t", "updatedAt": 123, "speakers": [], "segments": [_row(1, 0.5, 2.5, "こんにちは"), _row(2, 3.0, 4.0, "またね")]}
        self.put_doc(self.doc)

    def _words(self, words):
        with open(S.words_path(TID), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-words/v1", "words": words}, f, ensure_ascii=False)

    def _bytes(self):
        with open(S.tx_path(TID), "rb") as f:
            return f.read()

    def test_no_words(self):
        r = S.retime_doc({"id": TID, "rows": ["s1"]})
        self.assertEqual((r["items"], r["reasonCode"], r["updatedAt"]), ([], "no_words", 123))
        self.assertIn("範囲を再認識", r["reason"])

    def test_candidates_and_doc_untouched(self):
        self._words(_chars(1.0, "こんにちは") + _chars(3.0, "またね"))
        before = self._bytes()
        r = S.retime_doc({"id": TID, "rows": ["s1", "s2"]})
        self.assertEqual([(x["id"], x["start"], x["end"]) for x in r["items"]], [("s1", 1.0, 2.0), ("s2", 3.0, 3.6)])
        self.assertEqual((r["checked"], r["updatedAt"], r["engine"], r["endEdge"]), (2, 123, "faster-whisper", True))
        self.assertEqual(self._bytes(), before)                             # 文書は書き換えない
        r = S.retime_doc({"id": TID, "rows": ["s2"]})
        self.assertEqual([x["id"] for x in r["items"]], ["s2"])

    def test_bad_request(self):
        for body in ({"id": TID}, {"id": TID, "rows": []}, {"id": TID, "rows": [1]}, {"id": TID, "rows": "s1"}):
            with self.subTest(body=body):
                with self.assertRaises(ed_state.ApiError) as cm:
                    S.retime_doc(body)
                self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ed_state.ApiError) as cm:
            S.retime_doc({"id": "zzzzzzzzzzzz", "rows": ["s1"]})
        self.assertEqual(cm.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
