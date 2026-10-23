# -*- coding: utf-8 -*-
"""flow/diar(② 話者判別と声の段取り)のうち、行の選び方と照合のつなぎ・覚えた声の記録のテスト(RS7-1 1e)。

    py -3.12 -m unittest tests/flow/test_diar.py -v

- voice_learn_rows: 短い行・混声は ② が数え、校正済みか音のメモかは accept(③)に任せる。数える順は 1 秒未満 → 混ざる → accept の理由
- merge_voice: learnedFrom(文書の指定が無い・古い形・確かめるの声のカードの行の控え)
行 → 声の特徴 → 照合のつなぎ(match_known_voices)と、同じ文書から 2 回覚える形は、本物の判別の通し(tests/human/proof/test_voices.py の TestDiarRealRun)が確かめる。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
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


class TestVoiceEmbedding(unittest.TestCase):
    def test_learn_and_match_model(self):
        """声の名前付けのモデル(① VOICE_EMB。10-22): 覚えるのはいつも VOICE_EMB・照らすのは VOICE_EMB の声が 0 人で判別のモデルの声があるときだけ判別のモデル。
        VOICE_EMB を空にすると判別と同じ(前の形)"""
        import tempfile
        from unittest import mock
        from pipeline.transcribe import diarize as D
        tmp = tempfile.mkdtemp()
        with mock.patch.object(diar, "VOICES_DIR", tmp):
            self.assertEqual((diar.learn_embedding("voxceleb"), diar.match_embedding("voxceleb")), ("campplus", "campplus"))   # 声がどちらにも無い
            diar.save_voices("voxceleb", {"A": {"vec": [1.0, 0.0]}})
            self.assertEqual((diar.learn_embedding("voxceleb"), diar.match_embedding("voxceleb")), ("campplus", "voxceleb"))   # 前に覚えた声で照らす
            diar.save_voices("campplus", {"B": {"vec": [0.0, 1.0]}})
            self.assertEqual(diar.match_embedding("voxceleb"), "campplus")
            with mock.patch.object(D, "VOICE_EMB", ""):
                self.assertEqual((diar.learn_embedding("voxceleb"), diar.match_embedding("x")), ("voxceleb", "voxceleb"))


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


class TestRowVoices(unittest.TestCase):
    """覚えた声で 1 行ずつ話者を当てる(row_voices): 出る人が 2 人以上・全員の声が帳にあるときだけ。差が小さい行・短い行は配信者(先頭)。
    字幕に出さない行・話者の付いた行は変えない"""
    VOICES = {"A": {"vec": [1.0, 0.0, 0.0]}, "B": {"vec": [0.0, 1.0, 0.0]}, "C": {"vec": [0.0, 0.0, 1.0]}}

    def run_rv(self, people, segs, vecs, voices=None):
        import tempfile
        from unittest import mock
        tmp = tempfile.mkdtemp()
        got = {}

        def fake_embed(job, spec, wav, groups, hints):
            got["groups"], got["emb"] = groups, spec["embedding"]
            return vecs[:len(groups)]
        with mock.patch.object(diar, "VOICES_DIR", tmp), mock.patch.object(diar, "embed", fake_embed):
            diar.save_voices(diar.learn_embedding(diar.default_embedding()), self.VOICES if voices is None else voices)
            return diar.row_voices({}, {"people": people, "start": 0.0}, "x.wav", segs), got

    def test_assigns_rows_to_nearest_of_the_people(self):
        segs = [seg(0, 2, "", text="あ", id="r1"), seg(2, 4, "", text="い", id="r2"), seg(4, 6, "", text="う", id="r3"),
                seg(6, 6.3, "", text="え", id="r4"),                                  # 短い -> 配信者
                seg(7, 9, "", text="お", id="r5", noSub=True),                        # 字幕に出さない -> 変えない
                seg(9, 11, "S9", text="か", id="r6")]                                 # 話者の付いた行 -> 変えない
        vecs = [[0.1, 0.9, 0.0], [0.6, 0.58, 0.0], [0.0, 0.2, 0.95], None]          # B / 差 0.02(配信者) / C / 短い
        rv, got = self.run_rv(["A", "B", "C"], segs, vecs)
        self.assertEqual([g["speaker"] for g in segs], ["S2", "S1", "S3", "S1", "", "S9"])
        self.assertEqual(got["groups"], [[(0, 2)], [(2, 4)], [(4, 6)], []])
        self.assertEqual([s["name"] for s in rv["speakers"]], ["A", "B", "C"])
        d = rv["diarization"]
        self.assertEqual((d["speakerBy"], d["voice"], d["low"], d["short"]), ("rowvoice", 2, 1, 1))
        self.assertEqual([r["top"] for r in rv["record"]["rows"]], ["B", "A", "C"])

    def test_does_nothing_unless_all_people_are_in_the_book(self):
        segs = [seg(0, 2, "", text="あ")]
        self.assertIsNone(self.run_rv(["A", "Z"], segs, [[1.0, 0.0, 0.0]])[0])     # Z の声が無い
        self.assertIsNone(self.run_rv(["A"], segs, [[1.0, 0.0, 0.0]])[0])          # 1 人
        self.assertIsNone(self.run_rv([], segs, [[1.0, 0.0, 0.0]])[0])
        self.assertEqual(segs[0]["speaker"], "")
        from unittest import mock
        with mock.patch.object(diar, "ROWVOICE", False):                           # スイッチ
            self.assertIsNone(self.run_rv(["A", "B"], segs, [[1.0, 0.0, 0.0]])[0])


if __name__ == "__main__":
    unittest.main()
