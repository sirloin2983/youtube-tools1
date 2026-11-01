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
                self.assertEqual((diar.learn_embedding("voxceleb"), diar.match_embedding("voxceleb")), ("voxceleb", "voxceleb"))


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

    def test_short_material_weight_and_provisional(self):
        """ショート由来(学習用データ)の材料は重み半分・ショートだけの声は仮。仮の声に配信の材料が来たら上書きに近い(10-25)"""
        v = diar.merge_voice(None, [1.0, 0.0], 3, 10.0, "s1", short=True)
        self.assertEqual((v.get("provisional"), v["shortSec"], v["sec"]), (True, 10.0, 10.0))
        v = diar.merge_voice(v, [0.0, 1.0], 3, 10.0, "d1")              # 配信の材料: 前の重み 10 × 0.1 = 1 対 10
        self.assertNotIn("provisional", v)
        self.assertGreater(v["vec"][1], 0.99)                            # ほぼ配信の声
        self.assertEqual((v["sec"], v["shortSec"]), (20.0, 10.0))
        w = diar.merge_voice(v, [1.0, 0.0], 3, 20.0, "s2", short=True)  # 仮でない声にショート: 重み半分(前 20 − 10×0.5 = 15 対 20×0.5 = 10)
        x, y = 15.0 * v["vec"][0] + 10.0, 15.0 * v["vec"][1]
        self.assertAlmostEqual(w["vec"][0] / w["vec"][1], x / y, places=3)
        self.assertNotIn("provisional", w)
        self.assertEqual(w["shortSec"], 30.0)
        p = diar.merge_voice(None, [1.0, 0.0], 3, 10.0, "d1")              # 配信だけの声は印なし(今までの形)
        self.assertEqual(("provisional" in p, "shortSec" in p), (False, False))

    def test_first_provisional_from_stream(self):
        """まだ声が無い人を配信の材料 10 秒で覚えた仮の声: 30 秒に届くまで仮・前の重みは薄めない(別の文書の続きの材料と普通に混ぜる)"""
        v = diar.merge_voice(None, [1.0, 0.0], 2, 10.0, "d1", provisional=True)
        self.assertEqual((v.get("provisional"), "shortSec" in v), (True, False))
        w = diar.merge_voice(v, [0.0, 1.0], 2, 10.0, "d2")
        self.assertAlmostEqual(w["vec"][0], w["vec"][1], places=3)       # 10 対 10(薄めない)
        self.assertTrue(w.get("provisional"))                             # 20 秒 < 30 = まだ仮
        x = diar.merge_voice(w, [0.0, 1.0], 2, 15.0, "d3")
        self.assertNotIn("provisional", x)                                # 35 秒 = 仮でなくなる

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


class TestMinorLabels(unittest.TestCase):
    """話す時間の短い番号(合計の MINOR_SHARE 未満・いちばん長い番号は外さない)を、声の一番近い残りの番号へ移す(11-01 予備3 の 12 章)"""

    def test_picks_and_moves_by_voice(self):
        from unittest import mock
        # 0 = 60 秒・1 = 30 秒・2 = 2 秒(2.1%)・3 = 2 秒(0 の声の割れた片方)
        turns = [(0, 60, 0), (60, 90, 1), (90, 92, 2), (92.5, 94.5, 3), (59, 61, 1)]
        minor, secs = diar.minor_labels(turns)
        self.assertEqual((sorted(minor), round(secs[0])), ([2, 3], 60))
        self.assertEqual(diar.minor_labels([(0, 1, 5)])[0], {})                       # 1 人なら外さない
        self.assertEqual(diar.minor_labels([(0, 1, 1), (1, 100, 0)])[0], {1: 1})       # 一番長い番号は外さない・短い方だけ
        spans = diar._label_spans(turns)
        self.assertEqual(spans[0], [(0, 59)])                                          # ほかの番号と重なる所を除く
        self.assertEqual(spans[1], [(60, 61), (60, 90)])                               # 1 秒以上の切れ端は残す
        vecs = {0: [1.0, 0.0], 1: [0.0, 1.0], 2: [0.1, 0.99], 3: [0.98, 0.2]}
        seen = []

        def emb(job, spec, wav, groups, hints):
            seen.append((spec["embedding"], groups, hints))
            return [vecs[k] for k in (0, 1, 2, 3)]
        with mock.patch.object(diar, "embed", emb):
            out, info = diar.merge_minor({}, "a.wav", turns, 100.0)
        self.assertEqual(seen[0][0], diar.learn_embedding(diar.default_embedding()))  # 声の名前付けのモデル
        self.assertEqual((seen[0][1][0], seen[0][2]), ([(100.0, 159.0)], {"start": 100.0}))   # 元の動画の秒
        self.assertEqual([k for _, _, k in out], [0, 1, 1, 0, 1])                      # 2 → 1・3 → 0(行は捨てない)
        self.assertEqual((info["share"], info["labels"]["3"]["to"], info["labels"]["3"]["by"]), (diar.MINOR_SHARE, 0, "voice"))
        with mock.patch.object(diar, "embed", side_effect=RuntimeError("no sherpa")):
            out, info = diar.merge_minor({}, "a.wav", turns, 0.0)
        self.assertEqual([k for _, _, k in out], [0, 1, 0, 0, 1])                      # 声が取れなければ一番長く話す番号へ
        self.assertEqual(info["labels"]["2"]["by"], "longest")
        self.assertEqual(diar.merge_minor({}, "a.wav", [(0, 10, 0), (10, 15, 1)], 0.0), ([(0, 10, 0), (10, 15, 1)], None))   # 外す番号が無い


if __name__ == "__main__":
    unittest.main()
