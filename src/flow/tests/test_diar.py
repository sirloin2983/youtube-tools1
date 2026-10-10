# -*- coding: utf-8 -*-
"""flow/diar(② 話者判別と声の段取り)のうち、行の選び方と照合のつなぎ・覚えた声の記録のテスト(RS7-1 1e)。

    py -3.10 -m unittest src/flow/tests/test_diar.py -v

- voice_learn_rows: 短い行・混声は ② が数え、校正済みか音のメモかは accept(③)に任せる。数える順は 1 秒未満 → 混ざる → accept の理由
- match_known_voices: 行 → 声の特徴 → 照合をつなぐ(特徴の取り出しと照合は差し替え)
- merge_voice: learnedFrom(同じ文書は重ねない・古い形も読める)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest
from unittest import mock

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

    def test_empty(self):
        self.assertEqual(diar.voice_learn_rows([], {}, lambda g: None), ({}, {"unproofed": 0, "tagged": 0, "mixed": 0, "short": 0}))


class TestMatchKnownVoices(unittest.TestCase):
    def test_chains_groups_embed_and_match(self):
        segs = [seg(0, 5, "s1"), seg(6, 9, "s2"), seg(10, 11.5, "")]
        seen = {}

        def fake_embed(job, spec, wav, groups, hints):
            seen["groups"] = groups
            return [[1.0], [0.0]]

        def fake_match(vecs, voices):
            seen["vecs"] = vecs
            return {"s1": ("A", 0.9)}, {"s1": {"top": "A"}}
        with mock.patch.object(diar, "embed", fake_embed), mock.patch.object(diar._calc, "match_voices_explain", fake_match):
            job = {}
            got = diar.match_known_voices(job, {"embedding": "voxceleb"}, "w.wav", segs, lambda g: g.get("speaker") or "", {"A": {}}, {"start": 0})
        self.assertEqual(got, ({"s1": ("A", 0.9)}, {"s1": {"top": "A"}}))
        self.assertEqual(seen["groups"], [[(0, 5)], [(6, 9)]])      # 話者が空の行は使わない
        self.assertEqual(seen["vecs"], {"s1": [1.0], "s2": [0.0]})
        self.assertEqual(job["phase"], "覚えている声と照らし合わせ中")

    def test_no_rows(self):
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


if __name__ == "__main__":
    unittest.main()
