# -*- coding: utf-8 -*-
"""flow/diar(② 話者判別と声の段取り)のうち、行の選び方と照合のつなぎ・覚えた声の記録のテスト(RS7-1 1e)。

    py -3.12 -m unittest src/flow/tests/test_diar.py -v

- voice_learn_rows: 短い行・混声は ② が数え、校正済みか音のメモかは accept(③)に任せる。数える順は 1 秒未満 → 混ざる → accept の理由
- merge_voice: learnedFrom(文書の指定が無い・古い形・確かめるの声のカードの行の控え)
行 → 声の特徴 → 照合のつなぎ(match_known_voices)と、同じ文書から 2 回覚える形は、本物の判別の通し(src/editor/tests/test_voices.py の TestDiarRealRun)が確かめる。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import diar  # noqa: E402
from ytt import txbase  # noqa: E402


def seg(a, b, sp, **kw):
    return dict({"start": a, "end": b, "speaker": sp}, **kw)


class TestLearnGroups(unittest.TestCase):
    def test_counts_in_order_and_hands_accepted_rows_on(self):
        segs = [seg(0, 0.5, "s1"),                                   # 短い
                seg(1, 4, "s1", flag=txbase.MIXED_FLAG),              # 混声
                seg(5, 9, "s1", tags=["bgm"]),                        # accept が断る
                seg(10, 14, "s1"),                                    # 未校正
                seg(15, 20, "s1", proofed=True),                      # 通る
                seg(21, 23, "s2", proofed=True),                      # who に無い話者
                seg(24, 25, "s1", proofed=True, tags=["bgm"], flag=txbase.MIXED_FLAG)]   # 混声が先

        def accept(g):
            if "bgm" in (g.get("tags") or []):
                return "tagged"
            return None if g.get("proofed") is True else "unproofed"
        groups, skipped = diar.voice_learn_rows(segs, {"s1": "A"}, accept)
        self.assertEqual(skipped, {"unproofed": 1, "tagged": 1, "mixed": 2, "short": 1})
        self.assertEqual(groups, {"A": ([(15, 20)], 5)})
        self.assertEqual(diar.voice_learn_rows([], {}, lambda g: None), ({}, {"unproofed": 0, "tagged": 0, "mixed": 0, "short": 0}))   # 空の入力
        self.assertEqual(diar.match_known_voices({}, {}, "w", [], lambda g: "x", {}, {}), ({}, {}))


class TestMergeVoice(unittest.TestCase):
    def test_learned_from(self):
        v = diar.merge_voice(None, [1.0, 0.0], 3, 10.0)
        self.assertNotIn("learnedFrom", v)                           # 文書の指定が無ければ足さない
        v = diar.merge_voice(v, [1.0, 0.0], 3, 10.0, "d1")           # 古い形(learnedFrom 無し)に足す
        self.assertEqual([x["doc"] for x in v["learnedFrom"]], ["d1"])
        v = diar.merge_voice(v, [1.0, 0.0], 3, 10.0, "d2")
        v = diar.merge_voice(v, [1.0, 0.0], 3, 10.0, "d1")           # 同じ文書は重ねない
        self.assertEqual(sorted(x["doc"] for x in v["learnedFrom"]), ["d1", "d2"])
        self.assertEqual(v["rows"], 12)

    def test_learned_rows_from_check(self):
        """確かめるの声のカード(V2c): by と使った行の id を控え、同じ文書は行を合わせて秒を足す。普通の「声を覚える」でも控えは消さない"""
        v = diar.merge_voice(None, [1.0, 0.0], 2, 12.0, "d1", by="check", row_ids=["s1", "s2"])
        self.assertEqual(v["learnedFrom"][0]["rows"], ["s1", "s2"])
        self.assertEqual((v["learnedFrom"][0]["by"], v["learnedFrom"][0]["sec"]), ("check", 12.0))
        v = diar.merge_voice(v, [1.0, 0.0], 2, 20.0, "d1", by="check", row_ids=["s2", "s3"])
        e = v["learnedFrom"][0]
        self.assertEqual((e["rows"], e["sec"], len(v["learnedFrom"])), (["s1", "s2", "s3"], 32.0, 1))
        v = diar.merge_voice(v, [1.0, 0.0], 5, 40.0, "d1")   # 普通の「声を覚える」(校正済みの行)
        self.assertEqual(v["learnedFrom"][0]["rows"], ["s1", "s2", "s3"])


if __name__ == "__main__":
    unittest.main()
