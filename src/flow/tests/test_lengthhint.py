# -*- coding: utf-8 -*-
"""flow/lengthhint(長さの目安を ② でその場で数える。OPT-E2 7f-1)のテスト。作業データは一時フォルダに作る。

    py -3.12 -m unittest src/flow/tests/test_lengthhint.py -v

- 見本 = 実行記録の ranges(同じ区間は 1 つ・外れ値は数だけ)・長さは中央値を 10〜300 秒に丸める(上限 300 = LD-2d。10-16 まで 180)
- 山の前の割合は区間の中の自動の候補の山(data.json のマーク・archive の候補)から・見本 10 個未満なら出さない
- enough(20 個・5 本)・同じ入力は覚えた結果・入力が変われば数え直す・usable / change / describe
"""
import gzip
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない。ほかのテストとそろえる
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from flow import lengthhint as LH  # noqa: E402


def run(vid, ranges, i=0):
    return {"v": 1, "id": "r%d" % i, "state": "done", "steps": [], "kind": "video", "videoId": vid, "ranges": ranges}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "lh_")
        self.studio = os.path.join(self.tmp, "studio")
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(self.studio, "archive"))
        os.makedirs(os.path.join(self.app, "logs"))
        self.videos = {}
        LH._CACHE.clear()

    def write(self, records):
        testkit.write_json(os.path.join(self.studio, "data.json"), {"schema": "x", "videos": self.videos})
        testkit.write_text(os.path.join(self.app, "logs", "autorun-runs.jsonl"), "".join(json.dumps(r) + "\n" for r in records))


class TestCompute(Base):
    def test_median_and_cap_300(self):
        recs = [run("v%d" % (i % 5), [[i * 1000.0, i * 1000.0 + 150.0 + i]], i) for i in range(20)]
        self.write(recs)
        h = LH.compute(self.studio, self.app)
        self.assertEqual((h["samples"], h["videos"], h["enough"]), (20, 5, True))
        self.assertEqual(h["length"], 160)   # 150〜169 の中央値 159.5 → 160
        self.write([run("v%d" % (i % 5), [[0.0, 400.0 + i]], i) for i in range(20)])
        self.assertEqual(LH.compute(self.studio, self.app)["length"], 300)   # 上限 300 で切る
        self.write([run("a", [[0.0, 3.0]], 0), run("a", [[10.0, 700.0]], 1)])
        h = LH.compute(self.studio, self.app)
        self.assertEqual((h["samples"], h["outliers"], h["length"], h["enough"]), (0, 2, None, False))

    def test_dedup_same_range(self):
        self.write([run("a", [[10.0, 70.0], [10.3, 70.2]], 0), run("a", [[10.0, 70.0]], 1), run("b", [[10.0, 70.0]], 2)])
        h = LH.compute(self.studio, self.app)
        self.assertEqual((h["samples"], h["videos"]), (3 - 1, 2))

    def test_pre_ratio_from_candidates(self):
        recs = []
        for i in range(10):
            vid = "v%d" % i
            # 区間 100〜200 の中に山 125 の自動マーク(peak)と、archive の点数の低い候補(山 175)
            self.videos[vid] = {"marks": [{"src": "auto", "start": 110.0, "end": 140.0, "score": 5, "peak": 125.0}]}
            with gzip.open(os.path.join(self.studio, "archive", vid + ".json.gz"), "wt", encoding="utf-8") as f:
                json.dump({"v": 1, "runs": [{"type": "game", "candidates": [{"start": 170.0, "end": 180.0, "score": 1, "peak": 175.0}]}]}, f)
            recs.append(run(vid, [[100.0, 200.0]], i))
        self.write(recs)
        h = LH.compute(self.studio, self.app, by_type=True)
        self.assertEqual((h["preRatio"], h["preSamples"]), (0.3, 10))   # 0.25 → 下限 0.3
        self.assertIn("game", h["byType"])
        self.videos["v0"]["marks"] = []   # 山が無い = 見本 9 個 → 出さない
        os.remove(os.path.join(self.studio, "archive", "v0.json.gz"))
        self.write(recs)
        self.assertIsNone(LH.compute(self.studio, self.app)["preRatio"])

    def test_peak_from_auto0_and_pre(self):
        cands, pre = LH.candidates({"analysis": {"spec": {"preRatio": 0.5}}, "marks": [{"src": "manual", "start": 0, "end": 9, "auto0": [10, 30]}]}, None)
        self.assertEqual(pre, 0.5)
        self.assertEqual(LH.peak_ratio(0.0, 40.0, cands, pre), 0.5)   # 山 = 10 + 20 × 0.5 = 20
        self.assertIsNone(LH.peak_ratio(30.0, 40.0, cands, pre))

    def test_cache_and_reread(self):
        self.write([run("a", [[0.0, 60.0]], 0)])
        a = LH.compute(self.studio, self.app)
        a["length"] = 999   # 写しを返す
        self.assertEqual(LH.compute(self.studio, self.app)["length"], 60)
        self.write([run("a", [[0.0, 60.0]], 0), run("b", [[0.0, 90.0]], 1)])
        self.assertEqual(LH.compute(self.studio, self.app)["samples"], 2)

    def test_missing_files(self):
        h = LH.compute(self.studio, self.app)
        self.assertEqual((h["samples"], h["enough"], h["length"]), (0, False, None))


class TestUse(unittest.TestCase):
    def test_usable_change_describe(self):
        h = {"length": 150, "preRatio": 0.4, "samples": 21, "videos": 20, "enough": True}
        self.assertEqual(LH.usable(h), {"length": 150, "preRatio": 0.4})
        self.assertIsNone(LH.usable(dict(h, enough=False)))
        self.assertEqual(LH.change(None, h), (True, {"length": 150, "preRatio": 0.4}))
        self.assertEqual(LH.change({"length": 150, "preRatio": 0.4}, h)[0], False)
        self.assertIn("150 秒", LH.describe(h))
        self.assertIn("まだ少ない", LH.describe(dict(h, enough=False)))
        self.assertIn("数えられません", LH.describe(None))


if __name__ == "__main__":
    unittest.main()
