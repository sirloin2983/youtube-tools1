#!/usr/bin/env python3
"""元の配信の YouTube の字幕の候補の、比べ方の部品(human/proof/ytcap.py)のテスト。**通信しない**。
YouTube の字幕の候補(取得・ジョブ・API・画面・提案)は消した(OPT-H1。決定 notes:plan/decisions.md の 3-47 Q10)。
残る部品は ⑤ の「確かめる」の読みのカード read:yt と測る道具 eval_alt の --source yt が読む(⑤ の呼び手を消したら、このテストごと消す)。

    py -3.10 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest test_ytcap -q                  # これだけ(src/editor/tests で)

- 文書の範囲の切り出しと時刻の直し(clip_offset・actualStart・文書の範囲)・元の配信が分からない文書・ID の検査・
  alt_diffs をそのまま使う比べ方(tier yt)・切り抜きの頭と終わりは出さない・言いよどみだけの候補は出さない
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, TID  # noqa: F401,E402  (S = serve)
from human.proof import alt as proof_alt  # noqa: E402
import ed_state  # noqa: E402
from human.proof import ytcap as Y  # noqa: E402

__all__ = ["TestYtcapPure"]   # test_metrics の import * で、テストの小道具(seg・doc など)が test_metrics の同じ名前を隠さないように
VID = "AbCdEfGh_-1"
OFF = 100.0   # 切り抜きの先頭 = 配信の 100 秒目


def clip(vid=VID, start=OFF, end=OFF + 9, kind="youtube", **export):
    return {"schema": "youtube-tools-clip/v1", "tool": {"name": "clip-studio", "version": "x"}, "media": {"path": "x.mp4", "name": "x.mp4", "durationSec": end - start},
            "source": {"kind": kind, "videoId": vid, "url": None, "title": "配信", "path": None}, "range": {"start": start, "end": end},
            "mark": {"id": "m1", "label": "", "status": "exported", "src": "manual"}, "export": dict({"mode": "precise"}, **export)}


def seg(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


# 配信ごとの字幕の記録の cues(配信の時刻のミリ秒。1 つの字幕 = [[開始, 終わり, 言葉]…])。切り抜きは 100〜109 秒。範囲の前後の字幕は切り出しで消える
CUES = [[[97000, 99000, "前の話です"]],
        [[100100, 100800, "こんばんは"], [100800, 101200, "白神"], [101200, 101700, "フブキ"], [101700, 102100, "です"]],
        [[103100, 104000, "今日は"], [104000, 104600, "マイクラを"], [104600, 105400, "やります"]],
        [[106100, 106600, "よろしく"], [106600, 107000, "お願い"], [107000, 107600, "します"]],
        [[109600, 110600, "次の話です"]]]


def doc(**over):
    d = {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "", "start": 0, "end": 9, "updatedAt": 1000, "clip": clip(),
         "segments": [seg(1, 0, 3, "こんばんは白上フブキです"), seg(2, 3, 6, "今日はマイクラをやります"), seg(3, 6, 9, "よろしくお願いします")], "original": []}
    d.update(over)
    return d


class TestYtcapPure(unittest.TestCase):
    def test_doc_range_and_offset(self):
        r = Y.ytcap_doc_range(doc())
        self.assertEqual((r["videoId"], r["offset"], r["a"], r["b"]), (VID, 100.0, 100.0, 109.0))
        r = Y.ytcap_doc_range(doc(start=2, end=None))   # 文書が切り抜きの 2 秒目〜最後
        self.assertEqual((r["a"], r["b"], r["docStart"], r["docEnd"]), (102.0, 109.0, 2.0, 9.0))
        r = Y.ytcap_doc_range(doc(clip=clip(actualStart=99.5)))   # 以前の高速の書き出し: キーフレームにずれた実際の開始を優先
        self.assertEqual((r["offset"], r["a"]), (99.5, 99.5))
        for d, why in ((doc(clip=None), "no clip"), (doc(clip=clip(kind="file")), "file"), (doc(clip=clip(kind="live")), "live"),
                       (doc(clip=clip(vid="abc")), "short id"), (doc(clip=clip(vid="AbCdEfGh_-1\n")), "newline"), (doc(clip=clip(vid="AbCdEfGh/-1")), "slash"),
                       (doc(clip=clip(start=5, end=1)), "bad range"), (doc(clip=dict(clip(), schema="other")), "schema")):
            with self.subTest(why=why):
                with self.assertRaises(ed_state.ApiError) as cm:
                    Y.ytcap_doc_range(d)
                self.assertEqual(cm.exception.code, "no_clip")

    def test_cut_converts_times(self):
        rows, _rng = Y.ytcap_doc_rows(doc(), {"cues": CUES})
        self.assertEqual([r["text"] for r in rows], ["こんばんは白神フブキです", "今日はマイクラをやります", "よろしくお願いします"])
        self.assertEqual([r["start"] for r in rows], [0.1, 3.1, 6.1])    # 配信の時刻 − 100 秒 = 文書の時刻
        self.assertTrue(all(r["end"] > r["start"] for r in rows))
        # 範囲の途中にかかる言葉は、文字ごとの時刻(言葉の長さを字数で等分)の真ん中で分ける
        cues = [[[99000, 101000, "あいうえ"]]]   # 1 文字 0.5 秒: 真ん中 99.25・99.75・100.25・100.75
        self.assertEqual(Y.ytcap_cut(cues, 100.0, 109.0, 100.0), [{"start": 0.0, "end": 1.0, "text": "うえ"}])
        self.assertEqual(Y.ytcap_cut(cues, 98.0, 100.0, 98.0)[0]["text"], "あい")
        self.assertEqual(Y.ytcap_cut([[["x", 1, 2]], "bad", []], 0, 9, 0), [])   # 壊れた形は黙って捨てる

    def test_valid_cache(self):
        good = {"schema": Y.YTCAP_VIDEO_SCHEMA, "videoId": VID, "kind": "auto", "cues": [], "at": 1}
        self.assertTrue(Y.ytcap_valid_cache(good, VID))
        self.assertFalse(Y.ytcap_valid_cache(good, "other_id_00"))
        self.assertFalse(Y.ytcap_valid_cache(dict(good, kind="x")))
        self.assertFalse(Y.ytcap_valid_cache(dict(good, schema="other")))

    def test_diffs_are_alt_diffs_with_tier_yt(self):
        rows = doc()["segments"]
        yt, _rng = Y.ytcap_doc_rows(doc(), {"cues": CUES})
        items, st = Y.ytcap_diffs(rows, yt)
        self.assertEqual(items, [{"seg": "s1", "i": 6, "wrong": "上", "right": "神", "tier": "yt", "pos": 0, "neg": 0}])
        self.assertEqual(items[0]["wrong"], proof_alt.alt_diffs(rows, yt)[0][0]["wrong"])   # 比べ方は alt_diffs そのもの
        self.assertEqual(set(st), {"long", "cross", "mostly", "notation", "edge", "clipEdge", "filler"})
        # 句読点・カタカナ/ひらがな・全角/半角の違いは出さない
        items, _st = Y.ytcap_diffs([seg(1, 0, 3, "ＯＫです、ふぶきちゃん")], [{"start": 0, "end": 3, "text": "OKです。フブキちゃん"}])
        self.assertEqual(items, [])

    def test_fillers_are_not_candidates(self):
        """YouTube の字幕が句読点で区切って足した言いよどみ(え・あの・おお・ああ)だけの候補は出さない。句読点の無い 1 文字の足しは本当の直しのことがあるので出す"""
        self.assertTrue(Y.ytcap_filler_only("よ", "よ。あの"))
        self.assertTrue(Y.ytcap_filler_only("て", "て。え"))
        self.assertTrue(Y.ytcap_filler_only("な", "な。おお。ああ"))
        self.assertTrue(Y.ytcap_filler_only("何", "えっ、何"))
        self.assertFalse(Y.ytcap_filler_only("す", "ます"))
        self.assertFalse(Y.ytcap_filler_only("なで", "なんで"))
        self.assertFalse(Y.ytcap_filler_only("よ", "よ。本当"))
        self.assertFalse(Y.ytcap_filler_only("上", "神"))
        rows = [seg(1, 0, 3, "はじめに"), seg(2, 3, 6, "今日はいい天気だよそれでね"), seg(3, 6, 9, "おわりに")]
        items, st = Y.ytcap_diffs(rows, [{"start": 0, "end": 3, "text": "はじめに"}, {"start": 3, "end": 6, "text": "今日はいい天気だよ。あの、それでね"},
                                         {"start": 6, "end": 9, "text": "おわりに"}])
        self.assertEqual((items, st["filler"]), ([], 1))

    def test_clip_edges_are_not_candidates(self):
        """切り抜きの頭(最初の行の頭)と終わり(最後の行の終わり)にかかる食い違いは出さない(字幕の時刻で切るので境目の言葉がずれる)"""
        rows = doc()["segments"]
        yt = [{"start": 0, "end": 3, "text": "ねこんばんは白上フブキです"}, {"start": 3, "end": 6, "text": "今日はマイクラをやります"},
              {"start": 6, "end": 9, "text": "よろしくお願いしますね"}]
        items, st = Y.ytcap_diffs(rows, yt)
        self.assertEqual((items, st["clipEdge"]), ([], 2))
        self.assertEqual(len(proof_alt.alt_diffs(rows, yt)[0]), 2)   # alt_diffs だけなら出る
        # 真ん中の行の頭・終わりは出す
        yt[1] = {"start": 3, "end": 6, "text": "今日もマイクラをやります"}
        items, _st = Y.ytcap_diffs(rows, yt)
        self.assertEqual([(x["seg"], x["wrong"], x["right"]) for x in items], [("s2", "は", "も")])


if __name__ == "__main__":
    unittest.main()
