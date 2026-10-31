"""Haas(speech.cpp)の行の作りと後処理(段 2。src/pipeline/transcribe/postproc.py の haas_pieces・haas_times・haas_text・expand_segments の Haas の道、
tx_engines.second_names・speech_vad、fill.fill_after_rows の Haas の道)の単体テスト。音・窓を出さない(偽の worker だけ)。

実行(リポジトリ直下から): py -3.12 -m unittest tests/pipeline/transcribe/test_haas_rows.py -v
"""
import math
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pipeline.transcribe import fill, postproc as P, tx_engines as E  # noqa: E402

HAAS = {"engine": "haas-speechcpp", "wordSplit": True, "splitChars": 24, "stripPunct": True}
FAKE = [sys.executable, os.path.join(HERE, "fake_speech_worker.py")]


def seg(tokens, probs=None):
    """区切りの 1 行(seg_to_dict の形)。tokens = [(始め, 終わり, 字)]"""
    ws = [list(t) for t in tokens]
    return {"start": ws[0][0], "end": ws[-1][1], "text": "".join(w[2] for w in ws), "avg_logprob": -0.5, "no_speech_prob": None,
            "compression_ratio": 1.2, "words": ws, "wordProbs": list(probs) if probs else [0.9] * len(ws)}


class HaasRowsTest(unittest.TestCase):
    def test_pieces_cut_merge_and_own_conf(self):
        s = seg([(0.0, 0.4, "え"), (0.4, 0.6, "、"), (0.6, 1.0, "今日"), (1.0, 1.2, "は"), (1.2, 1.4, "、"), (1.5, 2.0, "雨"), (2.0, 2.2, "。"),
                 (2.5, 3.0, "明日"), (3.0, 3.3, "も"), (3.3, 3.5, "晴れ"), (3.5, 3.6, "?")],
                probs=[0.5, 1, 0.9, 0.9, 1, 0.2, 1, 0.8, 0.8, 0.8, 1])
        got = P.haas_pieces([s])
        self.assertEqual([g["text"] for g in got], ["え、今日は、雨。", "明日も晴れ?"])   # 「え、」「雨。」は 2 字以下 = 前(頭は次)につなぐ
        self.assertEqual((got[1]["start"], got[1]["end"]), (2.5, 3.6))
        want = sum(math.log(p) for p in [0.8, 0.8, 0.8, 1]) / 4
        self.assertAlmostEqual(got[1]["avg_logprob"], want)
        self.assertIsNone(got[0]["compression_ratio"])
        self.assertEqual(len(got[0]["wordProbs"]), len(got[0]["words"]))

    def test_times_extend_end_and_early_head(self):
        rows = [{"start": 1.0, "end": 2.0, "text": "a"}, {"start": 2.6, "end": 3.0, "text": "b"}, {"start": 6.0, "end": 6.5, "text": "c"}]
        got = P.haas_times([dict(r) for r in rows], [(0.9, 2.3), (2.5, 5.0), (5.9, 9.0)], dur=10.0)
        self.assertEqual([(r["start"], r["end"]) for r in got], [(0.95, 2.3), (2.55, 4.0), (5.95, 7.5)])   # 声の終わりまで・多くて 1 秒・次の頭まで
        got = P.haas_times([dict(r) for r in rows], None)
        self.assertEqual(got[1]["end"], 3.0)   # 声の区間が無ければ伸ばさない

    def test_expand_segments_haas_path(self):
        s = seg([(0.0, 0.3, "え"), (0.3, 0.5, "?"), (0.5, 1.0, "何"), (1.0, 1.4, "それ"), (1.4, 1.5, "!"), (3.0, 3.4, "アーニャ"), (3.4, 3.5, "・"),
                 (3.5, 4.0, "メルフィッサ"), (4.0, 4.2, "だよ"), (4.2, 4.3, "。")])
        rows = list(P.expand_segments(iter([s]), HAAS, 10.0, voice=[(2.9, 4.8)]))
        self.assertEqual([r["text"] for r in rows], ["え何それ", "アーニャ・メルフィッサだよ"])   # 記号の決まり(名簿の名前の中の「・」は残す)
        self.assertEqual(rows[1]["end"], 4.8)   # 声の終わりまで
        self.assertEqual(rows[1]["start"], 2.95)
        rows = list(P.expand_segments(iter([seg([(0.0, 0.4, "あ"), (0.5, 0.9, "い")])]), {"engine": "whisper.cpp", "wordSplit": True, "stripPunct": True}, 5.0))
        self.assertEqual([r["text"] for r in rows], ["あい"])   # whisper の道は今のまま

    def test_second_names(self):
        members = {"大神ミオ": {"name": "大神ミオ", "aliases": ["ミオ", "ミオしゃ", "ミオちゃん"], "common": []},
                   "白上フブキ": {"name": "白上フブキ", "aliases": ["フブキ", "白上"], "common": []}}
        self.assertEqual(E.second_names("ミオがさ、ミオってさ", ["大空スバル"], members), ["大神ミオ", "ミオしゃ", "ミオちゃん"])
        self.assertEqual(E.second_names("ミオがさ", ["大空スバル"], members), [])   # 1 回だけなら足さない
        self.assertEqual(E.second_names("ミオミオ", ["大神ミオ"], members), [])     # 出る人なら足さない

    def test_speech_vad(self):
        tmp = tempfile.mkdtemp(prefix="ytt-haas-vad-")
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        with mock.patch.object(E.HaasSpeechCpp, "COMMAND", FAKE), mock.patch.object(E, "fetch_file", return_value=os.path.join(tmp, "v.gguf")), \
                mock.patch.dict(os.environ, {"FAKE_SPEECH_VAD": "0.5-2.0,3.0-4.25"}):
            self.assertEqual(E.speech_vad(os.path.join(tmp, "a.wav"), tmp), [(0.5, 2.0), (3.0, 4.25)])
        with mock.patch.object(E.HaasSpeechCpp, "COMMAND", None):
            with self.assertRaises(E.EngineError):
                E.speech_vad(os.path.join(tmp, "a.wav"), tmp)

    def test_fill_after_rows_haas_skips_second_read(self):
        rows = [{"start": 0.0, "end": 1.0, "text": "あ"}]
        with mock.patch.object(fill, "fill_drop_silent", side_effect=lambda job, r, wav, rec, drop, snap: r[:0]) as ds:
            out, rec, read = fill.fill_after_rows({}, dict(HAAS, autoFill=True, dropSilent=False), list(rows), "a.wav", 1.0)
            self.assertEqual((out, rec, read), (rows, None, None))
            out, rec, read = fill.fill_after_rows({}, dict(HAAS, autoFill=True, dropSilent=True), list(rows), "a.wav", 1.0)
            self.assertEqual((out, read), ([], None))   # dropSilent は動く
            self.assertEqual(ds.call_count, 1)


if __name__ == "__main__":
    unittest.main()
