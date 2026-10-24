"""編集カットの形「言いよどみと長い間を詰める」(pipeline/pack/tidy)。音は偽の 20 ms の音量(edge_pause.levels を差し替え)"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))
from pipeline.pack import edge_pause as E, tidy as T  # noqa: E402


def db_of(spans, sec, loud=-20.0, quiet=-60.0):
    """20 ms ごとの音量: spans [(から, まで)](秒)が声・ほかは静か"""
    return [loud if any(a <= i * E.HOP < b for a, b in spans) else quiet for i in range(int(sec / E.HOP))]


class TidyTest(unittest.TestCase):
    def drops(self, voice, words, sec=10.0):
        with mock.patch.object(E, "levels", lambda video, a, b: db_of(voice, sec)):
            return T.drops("v.mp4", words, 0.0, sec)

    def test_never_cuts_content_words(self):
        """内容を失わない: つなぎの言葉でない単語(小さな声・長さ 0 の単語も)は、どの削る所にもかからない"""
        voice = [(0.0, 2.0), (4.0, 6.0), (8.5, 10.0)]
        words = [[0.2, 0.6, "今日は"], [1.0, 1.4, "えー"], [1.5, 1.9, "ゲーム"],
                 [3.0, 3.06, "ん"],       # 2〜4 秒の間の中の小さな声(音量では声に見えない)
                 [7.2, 7.2, "や"],        # 6〜8.5 秒の間の中の長さ 0 の単語
                 [4.2, 5.8, "やります"], [8.6, 9.5, "はい"]]
        ds = self.drops(voice, words)
        for a, b, t in words:
            if not T.is_filler(t):
                self.assertFalse(any(x < b + 1e-9 and y > a - 1e-9 for x, y, _k in ds), (t, ds))
        self.assertIn("filler", [k for *_x, k in ds])          # 「えー」は削る
        self.assertTrue(any(k == "pause" and x >= 2.0 and y <= 2.95 for x, y, k in ds))   # 間は単語の無い部分だけ詰める
        self.assertTrue(any(k == "pause" and x >= 3.14 and y <= 4.0 for x, y, k in ds))

    def test_pause_keeps_edges_and_reply_words(self):
        """間は両側に KEEP 秒残す・「はい」は既定で削らない(extra で足せる)"""
        voice = [(0.0, 1.0), (3.0, 4.0)]
        words = [[0.1, 0.5, "はい"], [3.1, 3.9, "そう"]]
        ds = self.drops(voice, words, 4.0)
        self.assertEqual(ds, [(round(1.0 + T.KEEP, 3), round(3.0 - T.KEEP, 3), "pause")])
        self.assertEqual(len([d for d in self.drops(voice, words, 4.0) if d[2] == "filler"]), 0)
        with mock.patch.object(E, "levels", lambda video, a, b: db_of(voice, 4.0)):
            self.assertEqual([k for *_x, k in T.drops("v.mp4", words, 0.0, 4.0, extra=T.REPLY_FILLERS)].count("filler"), 2)

    def test_filler_exact_match_only(self):
        """言いよどみは一覧とぴったり同じ単語だけ(「あのね」「えーそれ」「あ」は内容)"""
        self.assertTrue(T.is_filler("えー、"))
        for w in ("あのね", "えーそれ", "あ", "え", "その", "うん"):
            self.assertFalse(T.is_filler(w), w)

    def test_switch_and_no_words(self):
        with mock.patch.object(T, "ON", False):
            self.assertEqual(self.drops([(0, 1)], [[0.1, 0.5, "えー"]]), [])
        self.assertEqual(self.drops([(0, 1)], []), [])
        self.assertEqual(T.keeps(0.0, 4.0, [(1.08, 2.92, "pause")]), [(0.0, 1.08), (2.92, 4.0)])


class TidyRequestTest(unittest.TestCase):
    def test_request_mode_tidy_keeps_clip_range(self):
        """まとめて実行のカットの方法 tidy(spec.mode "tidy"・words): 区間 = clipRange の中だけを詰めて残す区間にする"""
        from pipeline.pack import request as R, srt2resolve as S
        voice = [(0.0, 3.0), (5.0, 9.0)]
        with mock.patch.object(S, "probe", lambda v, *a, **k: {"fps": (30, 1), "total": 300}), \
                mock.patch.object(E, "levels", lambda video, a, b: db_of([(x - a, y - a) for x, y in voice], b - a)), \
                mock.patch.object(R, "input_path", lambda v, f: v):
            req = R.request_from_spec({"video": "v.mp4", "mode": "tidy", "clipRange": [1.0, 9.0],
                                       "words": [[1.2, 2.5, "今日は"], [5.2, 8.0, "ゲーム"], "壊れた単語"]})
        self.assertEqual(req.keep_pairs, [(1.0, round(3.0 + T.KEEP, 3)), (round(5.0 - T.KEEP, 3), 9.0)])


if __name__ == "__main__":
    unittest.main()
