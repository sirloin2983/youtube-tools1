"""覚えた声を 1 行ずつ外してまとめ直す(src/human/proof/voicerebuild.py。10-25)。声の特徴は偽物(本物のモデルは使わない)。
外した行を除いて行の秒で混ぜ直す・ショート由来は重み半分・行ごとの特徴を控える(2 回目は取り直さない)・前の登録簿を写す・外した行は覚え直しの材料に数えない。
実行(リポジトリ直下から): py -3.12 -m unittest tests/human/proof/test_voicerebuild.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import diar  # noqa: E402
from human.check import voice as voice_mod  # noqa: E402
from human.proof import voicerebuild as VR  # noqa: E402

EMB = "campplus"
DOCS = {"aaaaaaaaaaa1": {"sourcePath": "D:/配信/a.mp4", "segments": [{"id": "s1", "start": 0.0, "end": 4.0}, {"id": "s2", "start": 5.0, "end": 7.0}]},
        "bbbbbbbbbbb1": {"sourcePath": "E:/学習用データ/みこ/b.mov", "segments": [{"id": "s9", "start": 1.0, "end": 5.0}]}}
VEC = {("aaaaaaaaaaa1", "s1"): [1.0, 0.0], ("aaaaaaaaaaa1", "s2"): [0.0, 1.0], ("bbbbbbbbbbb1", "s9"): [0.0, 1.0]}


class RebuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-rebuild-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.object(diar, "VOICES_DIR", self.tmp), mock.patch.object(VR.store, "read_transcript", lambda t: DOCS[t])):
            p.start()
            self.addCleanup(p.stop)
        diar.save_voices(EMB, {"みこ": {"vec": [0.6, 0.8], "rows": 3, "sec": 10.0,
                                        "learnedFrom": [{"doc": "aaaaaaaaaaa1", "rows": ["s1", "s2"]}, {"doc": "bbbbbbbbbbb1", "rows": ["s9"]}]}})
        self.calls = []

    def embed(self, emb, tid, rows):
        self.calls.append((tid, [r for r, _a, _b in rows]))
        return {r: VEC[(tid, r)] for r, _a, _b in rows}

    def test_exclude_and_reblend(self):
        got = VR.rebuild(EMB, "みこ", ["aaaaaaaaaaa1#s2"], embed=self.embed, now=1000)
        v = diar.load_voices(EMB)["みこ"]
        # s1 = 4 秒 × [1,0]・s9 = 4 秒 × 0.5(ショート)× [0,1] → [4, 2] を長さ 1 に
        self.assertAlmostEqual(v["vec"][0] / v["vec"][1], 2.0, places=3)
        self.assertEqual((got["rows"], v["sec"], v["excluded"], v["shortSec"]), (2, 8.0, ["aaaaaaaaaaa1#s2"], 4.0))
        self.assertEqual([x["rows"] for x in v["learnedFrom"]], [["s1"], ["s9"]])
        self.assertTrue(os.path.exists(got["backup"]))                            # 前の登録簿の写し
        with open(got["backup"], encoding="utf-8") as f:
            self.assertIn("aaaaaaaaaaa1", f.read())
        VR.rebuild(EMB, "みこ", [], embed=self.embed, now=2000)
        self.assertEqual(len(self.calls), 2)                                      # 行ごとの特徴は控えた = 2 回目は取り直さない
        self.assertEqual(diar.load_voices(EMB)["みこ"]["excluded"], ["aaaaaaaaaaa1#s2"])   # 外した行は外したまま
        with mock.patch.object(voice_mod, "registry", lambda emb, cache=None: diar.load_voices(EMB)):
            self.assertIn(("aaaaaaaaaaa1", "s2"), voice_mod._learned_rows(EMB, "みこ", None))   # 覚え直しの材料に数えない


if __name__ == "__main__":
    unittest.main()
