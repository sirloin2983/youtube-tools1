#!/usr/bin/env python3
"""行の時刻を単語の時刻に合わせる候補(T1 の簡易版)のテスト(計算は pipeline/transcribe/retime.py・文書を読む包みは human/proof/retime.py)。

    py -3.12 -m unittest tests/eval/drill/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest test_retime -q                 # これだけ(tests/editor で)

- 時刻の候補: 保存した文書 1 本(場面ごとに 100 秒ずつ離した行の見本)と words.json を API の入口 retime_doc に通し、候補をまとめて確かめる
  (当て方・かなと句読点・人が足した字・当たりが少ない・差が小さい・短すぎる・大きく動かした行・前後の同じ話者の行で詰める・両方の候補が重ならない・
  伸ばしの単語・単語の途中・同じ言葉が 2 回・空の行・知らない行・文書を書き換えない)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS))), "src", "editor"))
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "editor"))   # test_backend・test_edit(編集のサーバーを一時フォルダで動かす道具)
from test_backend import TID, StoreDir  # noqa: F401,E402  (S = serve)
from human.proof import retime as _retime  # noqa: E402
from human.proof import store as _store  # noqa: E402
from ytt import txwords as _txwords  # noqa: E402
from pipeline.transcribe import retime  # noqa: E402  (計算 = retime_candidates)
import ed_state  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

def _chars(t0, text, step=0.2):
    """1 文字ずつの単語(t0 から step 秒ずつ)"""
    return [[round(t0 + i * step, 3), round(t0 + (i + 1) * step, 3), ch] for i, ch in enumerate(text)]


def _row(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": ""}, **kw)


# (行, 単語)。場面ごとに 100 秒ずつ離す(単語を探す窓と前後の行に届かない)
SCENES = [
    ([_row(1, 0.5, 2.5, "こんにちは")], _chars(1.0, "こんにちは")),                         # 両端を単語へ
    ([_row(2, 101.4, 102.6, "こんにちは")], _chars(101.0, "コンニチハ、")),                 # カタカナ ↔ ひらがな・最後の「、」まで終わりに含める
    ([_row(3, 200.5, 202.5, "えっこんにちは")], _chars(201.0, "こんにちは")),               # 人が足した頭の字 → 終わりだけ
    ([_row(4, 300.5, 302.5, "こんにわちは")], _chars(301.0, "こんにちは")),                 # 人が足した途中の字
    ([_row(5, 400.5, 402.5, "さようならまたね")], _chars(401.0, "こんにちは")),             # 当たりが少ない
    ([_row(6, 500.5, 502.5, "こんばんはみなさま")], _chars(501.0, "こんにちは")),           # 3/9 < 0.6
    ([_row(7, 600.95, 602.05, "こんにちは")], _chars(601.0, "こんにちは")),                 # 差が小さい
    ([_row(8, 700.6, 701.6, "あい")], [[701.0, 701.1, "あ"], [701.1, 701.2, "い"]]),         # 短すぎる
    ([_row(9, 806.0, 807.0, "こんにちは")], _chars(810.0, "こんにちは")),                   # 大きく動かした行
    ([_row(10, 900.95, 902.4, "こんにちは")], _chars(901.0, "こんにちは")),                 # 頭の差が小さい → 終わりだけ
    ([_row(11, 1000.0, 1001.0, "まえ", speaker="a"), _row(12, 1001.3, 1001.8, "こんにちは", speaker="a")],
     _chars(1000.4, "まえ") + _chars(1000.8, "こんにちは")),                                 # 同じ話者の前の行と重ならない所まで詰める
    ([_row(13, 1100.0, 1101.0, "まえ", speaker="b"), _row(14, 1101.3, 1101.8, "こんにちは", speaker="a")],
     _chars(1100.4, "まえ") + _chars(1100.8, "こんにちは")),                                 # 違う話者とは重ねる
    ([_row(15, 1200.0, 1201.0, "まえ", speaker="a", noSub=True), _row(16, 1201.3, 1201.8, "こんにちは", speaker="a")],
     _chars(1200.4, "まえ") + _chars(1200.8, "こんにちは")),                                 # 字幕に出さない行とも重ねる
    ([_row(17, 1300.0, 1301.0, "まえ", speaker="a"), _row(18, 1301.3, 1301.8, "こんにちは")],
     _chars(1300.4, "まえ") + _chars(1300.8, "こんにちは")),                                 # 話者の無い行は重ならない側
    ([_row(19, 1400.0, 1400.8, "あいうえおか"), _row(20, 1401.4, 1402.0, "かきくけこ")], _chars(1400.0, "あいうえお") + _chars(1401.0, "かきくけこ")),   # 両方の候補
    ([_row(21, 1500.0, 1500.5, "うわー")], [[1500.0, 1500.5, "うわ"], [1500.52, 1501.4, "ー"], [1501.45, 1502.0, "天井"]]),   # 伸ばしの単語まで
    ([_row(22, 1600.0, 1600.3, "うわー")], [[1600.0, 1600.5, "うわ"], [1600.8, 1601.4, "ー"], [1601.45, 1602.0, "天井"]]),   # すき間が空けば含めない
    ([_row(23, 1700.8, 1702.5, "にちは")], [[1701.0, 1702.0, "こんにちは"]]),                # 単語の途中の字は字数で割り振る
    ([_row(24, 1800.5, 1802.5, ""), _row(25, 1803.5, 1804.5, "   ")], _chars(1801.0, "こんにちは")),   # 空の行
    ([_row(26, 1901.0, 1901.9, "はい")], _chars(1900.0, "はい") + _chars(1901.2, "はい")),   # 同じ言葉が 2 回 → 今の終わりに近い方
]


class TestRetimeApi(StoreDir):
    def setUp(self):
        super().setUp()
        self.segs = [g for rows, _w in SCENES for g in rows]
        self.words = [w for _r, ws in SCENES for w in ws]
        self.put_doc({"id": TID, "title": "t", "updatedAt": 123, "speakers": [], "segments": self.segs})

    def _bytes(self):
        with open(_store.tx_path(TID), "rb") as f:
            return f.read()

    def test_candidates_through_api(self):
        ids = [g["id"] for g in self.segs if g["id"] not in ("s11", "s13", "s15", "s17")] + ["nope"]   # 前の行(詰める相手)には候補を出さない
        r = _retime.retime_doc({"id": TID, "rows": ids})
        self.assertEqual((r["items"], r["reasonCode"], r["updatedAt"]), ([], "no_words", 123))   # 単語の時刻が無い文書
        self.assertIn("範囲を再認識", r["reason"])
        testkit.write_json(_txwords.words_path(TID), {"schema": "youtube-tools-words/v1", "words": self.words})
        before = self._bytes()
        r = _retime.retime_doc({"id": TID, "rows": ids})
        got = {x["id"]: (x["start"], x["end"], x["edges"]) for x in r["items"]}
        self.assertEqual(got, {"s1": (1.0, 2.0, ["start", "end"]), "s2": (101.0, 102.2, ["start", "end"]), "s3": (200.5, 202.0, ["end"]),
                               "s4": (301.0, 302.0, ["start", "end"]), "s10": (900.95, 902.0, ["end"]), "s12": (1001.0, 1001.8, ["start"]),
                               "s14": (1100.8, 1101.8, ["start"]), "s16": (1200.8, 1201.8, ["start"]), "s18": (1301.0, 1301.8, ["start"]),
                               "s19": got.get("s19", (None,) * 3), "s20": got.get("s20", (None,) * 3), "s21": (1500.0, 1501.4, ["end"]),
                               "s22": (1600.0, 1600.5, ["end"]), "s23": (1701.4, 1702.0, ["start", "end"]), "s26": (1901.2, 1901.6, ["start", "end"])})
        self.assertLessEqual(got["s19"][1], got["s20"][0])                    # 両方を採っても重ならない
        s1 = r["items"][0]
        self.assertEqual((s1["matched"], s1["dStart"], s1["dEnd"], s1["from"]), (1.0, 0.5, -0.5, {"start": 0.5, "end": 2.5}))
        self.assertAlmostEqual(next(x for x in r["items"] if x["id"] == "s3")["matched"], 5 / 7, places=3)
        self.assertEqual((r["checked"], r["updatedAt"], r["engine"]), (len(ids), 123, "faster-whisper"))
        self.assertEqual(self._bytes(), before)                             # 文書は書き換えない
        # 返すエンジンは最初の認識の記録(2 つ目のエンジンの記録は見ない)
        self.put_doc({"id": TID, "title": "t", "updatedAt": 124, "speakers": [], "segments": self.segs,
                      "recognition": {"runs": [{"kind": "alt", "engine": "x"}, {"engine": "whisper.cpp"}]}})
        self.assertEqual(_retime.retime_doc({"id": TID, "rows": ["s1"]})["engine"], "whisper.cpp")

    def test_bad_request(self):
        for body in ({"id": TID}, {"id": TID, "rows": []}, {"id": TID, "rows": [1]}, {"id": TID, "rows": "s1"}):
            with self.assertRaises(ed_state.ApiError, msg=body) as cm:
                _retime.retime_doc(body)
            self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ed_state.ApiError) as cm:
            _retime.retime_doc({"id": "zzzzzzzzzzzz", "rows": ["s1"]})
        self.assertEqual(cm.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
