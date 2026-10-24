"""編集カットの形「無音を詰める」(pipeline/pack/tidy)。音は偽の 20 ms の音量(edge_pause.levels を差し替え)"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src"))
from pipeline.pack import edge_pause as E, tidy as T  # noqa: E402


def db_of(spans, sec, loud=-20.0, quiet=-60.0, faint=()):
    """20 ms ごとの音量: spans [(から, まで)](秒)が声・faint が小さい声(声より 20 dB 小さい)・ほかは静か"""
    def one(t):
        if any(a <= t < b for a, b in spans):
            return loud
        return loud - 20 if any(a <= t < b for a, b in faint) else quiet
    return [one(i * E.HOP) for i in range(int(sec / E.HOP))]


class TidyTest(unittest.TestCase):
    def drops(self, voice, words, sec=10.0, faint=()):
        with mock.patch.object(E, "levels", lambda video, a, b: db_of(voice, sec, faint=faint)):
            return T.drops("v.mp4", words, 0.0, sec)

    def test_never_cuts_words(self):
        """言葉は削らない: どの単語(つなぎの言葉も・音量で声に見えない小さな声も・長さ 0 も)も、詰める所にかからない"""
        voice = [(0.0, 2.0), (4.0, 6.0), (8.5, 10.0)]
        words = [[0.2, 0.6, "今日は"], [1.0, 1.4, "えー"], [1.5, 1.9, "ゲーム"],
                 [3.0, 3.06, "ん"],       # 2〜4 秒の間の中の小さな声
                 [7.2, 7.2, "や"],        # 6〜8.5 秒の間の中の長さ 0 の単語
                 [4.2, 5.8, "やります"], [8.6, 9.5, "あの"]]
        ds = self.drops(voice, words)
        for a, b, t in words:
            self.assertFalse(any(x < b + 1e-9 and y > a - 1e-9 for x, y, _k in ds), (t, ds))
        self.assertEqual({k for *_x, k in ds}, {"pause"})
        self.assertIn((round(2.0 + T.TAIL, 3), round(3.0 - T.HEAD, 3), "pause"), ds)   # 単語の無い部分だけ詰める

    def test_keeps_tail_and_head(self):
        """言い終わりの後に TAIL 秒・話し始めの前に HEAD 秒を残す"""
        ds = self.drops([(0.0, 1.0), (3.0, 4.0)], [[0.1, 0.9, "はい"], [3.1, 3.9, "そう"]], 4.0)
        self.assertEqual(ds, [(round(1.0 + T.TAIL, 3), round(3.0 - T.HEAD, 3), "pause")])

    def test_faint_voice_keeps_the_pause(self):
        """詰める所に小さい声・息・語尾のかすれ(声の中央から 25 dB 以内)が 0.06 秒以上続けば、その間は詰めない"""
        voice, words = [(0.0, 1.0), (3.0, 4.0)], [[0.1, 0.9, "はい"], [3.1, 3.9, "そう"]]
        self.assertEqual(self.drops(voice, words, 4.0, faint=[(1.5, 1.6)]), [])
        self.assertEqual(len(self.drops(voice, words, 4.0, faint=[(1.5, 1.52)])), 1)   # 0.02 秒は守らない

    def test_switch_and_no_words(self):
        with mock.patch.object(T, "ON", False):
            self.assertEqual(self.drops([(0, 1)], [[0.1, 0.5, "今日"]]), [])
        self.assertEqual(self.drops([(0, 1)], []), [])   # 単語の時刻が無い文書は詰めない
        self.assertEqual(T.keeps(0.0, 4.0, [(1.1, 2.95, "pause")]), [(0.0, 1.1), (2.95, 4.0)])


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
        self.assertEqual(req.keep_pairs, [(1.0, round(3.0 + T.TAIL, 3)), (round(5.0 - T.HEAD, 3), 9.0)])


if __name__ == "__main__":
    unittest.main()
