"""src/eval/tools/clipfit.py(自動の区間が友人の区間にどれだけ合うかの物差し)のテスト。リポジトリ直下で:

    py -3.12 -m unittest src/eval/tools/tests/test_clipfit.py -v

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。
"""
import gzip
import json
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品の置き場所)
sys.path.insert(0, REPO)
from eval.tools import clipfit as K  # noqa: E402
from ytt import testkit  # noqa: E402

VID = "v1aaaaaaaaa"
OTHER = "v2bbbbbbbbb"
N = 600


def material_obj(n=N):
    """音量は -30 の平ら・300〜319 秒だけ -5 の大きな音。コメントは 310 秒に 1 つ"""
    full = [-30.0] * n
    for i in range(300, 320):
        full[i] = -5.0
    return {"v": 1, "n": n, "full": full, "band": list(full), "chat": {"act": [0] * n},
            "stamps": [[310, 5, 1, "草"]],
            "runs": [{"spec": {"wAudio": 1.0, "wChat": 1.0, "wComments": 0.7, "headSec": 0, "sensitivity": "normal", "lag": 8},
                      "lagUsed": 5, "signals": {"audio": True, "chat": True, "comments": True}}]}


class Env(unittest.TestCase):
    """一時フォルダの作業データ: <root>/studio/archive/"""

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.studio = os.path.join(self.tmp, "studio")
        self.archive = os.path.join(self.studio, "archive")
        os.makedirs(self.archive)

    def write_gz(self, vid, obj):
        self.write_raw(vid, json.dumps(obj).encode("utf-8"))

    def write_raw(self, vid, raw):
        with gzip.open(os.path.join(self.archive, vid + ".json.gz"), "wb") as f:
            f.write(raw)


class FitTest(unittest.TestCase):
    def test_cover_and_extra(self):
        r = K.fit((100, 200), [{"start": 90, "end": 210, "peak": 150, "score": 3}])
        self.assertEqual(r["cover"], 1.0)
        self.assertEqual(r["extra"], 20.0)

    def test_no_peak_inside_is_none(self):
        self.assertIsNone(K.fit((100, 200), [{"start": 0, "end": 50, "peak": 20, "score": 9}]))

    def test_picks_highest_score_inside(self):
        cands = [{"start": 110, "end": 170, "peak": 120, "score": 2},
                 {"start": 150, "end": 210, "peak": 180, "score": 5}]
        r = K.fit((100, 200), cands)
        self.assertEqual(r["peak"], 180)
        self.assertEqual(r["cover"], 0.5)
        self.assertEqual(r["extra"], 10.0)


class SummarizeTest(unittest.TestCase):
    def test_counts(self):
        r1 = K.fit((100, 200), [{"start": 90, "end": 210, "peak": 150, "score": 3}])
        r2 = K.fit((100, 200), [{"start": 150, "end": 190, "peak": 160, "score": 2, "shape": "scene"}])
        s = K.summarize([r1, None, r2])
        self.assertEqual(s["ranges"], 3)
        self.assertEqual(s["counted"], 2)
        self.assertEqual(s["fullCover"], 1)
        self.assertEqual(s["fallback"], 1)
        self.assertEqual(s["cover"]["n"], 2)

    def test_empty(self):
        s = K.summarize([None])
        self.assertEqual((s["ranges"], s["counted"], s["fullCover"], s["fallback"]), (1, 0, 0, 0))
        self.assertIsNone(s["coverMean"])


class MaterialTest(Env):
    def test_load_and_rebuild(self):
        self.write_gz(VID, material_obj())
        m = K.load_material(self.studio, VID)
        self.assertIsNotNone(m)
        self.assertEqual(m["n"], N)
        self.assertEqual(len(m["full"]), N)
        self.assertEqual(m["lag"], 5)
        self.assertTrue(m["signals"]["audio"])
        total, full = K.rebuild(m)
        self.assertEqual(len(total), N)
        self.assertEqual(len(full), N)
        peak = max(range(N), key=lambda i: total[i])
        self.assertTrue(300 <= peak < 320, peak)

    def test_unreadable_material_is_none(self):
        """材料が読めないときは None: 壊れた gz・無いファイル・危ない ID(../x は存在しても読まない)"""
        self.write_raw(VID, b"not json at all")
        self.write_gz("x", material_obj())
        for case, vid in [("壊れた gz", VID), ("無いファイル", OTHER), ("危ない ID", "../x")]:
            with self.subTest(case):
                self.assertIsNone(K.load_material(self.studio, vid))


class EvaluateTest(Env):
    def test_evaluate_counts_one_range(self):
        self.write_gz(VID, material_obj())
        variants = [{"name": "fixed", "shape": "fixed", "length": 60, "pre": 0.5},
                    {"name": "scene", "shape": "scene", "length": 60, "pre": 0.5}]
        records = [{"videoId": VID, "ranges": [[280, 360]]}]
        res = K.evaluate(self.studio, self.tmp, variants, records=records, hint={})
        self.assertEqual(len(res["variants"]), 2)
        self.assertEqual(res["ranges"], 1)
        self.assertEqual(res["withMaterial"], 1)
        for v in res["variants"]:
            for k in ("all", "A", "B"):
                self.assertIn(k, v)
            self.assertEqual(v["all"]["ranges"], 1)
            self.assertEqual(v["all"]["counted"], 1)
            c = v["all"]["cover"]["median"]
            self.assertTrue(0.0 <= c <= 1.0, c)
            self.assertGreaterEqual(v["all"]["extra"]["median"], 0)

    def test_range_without_material_not_counted(self):
        self.write_gz(VID, material_obj())
        variants = [{"name": "fixed", "shape": "fixed", "length": 60, "pre": 0.5}]
        records = [{"videoId": VID, "ranges": [[280, 360]]},
                   {"videoId": OTHER, "ranges": [[100, 200]]}]
        res = K.evaluate(self.studio, self.tmp, variants, records=records, hint={})
        self.assertEqual(res["ranges"], 2)
        self.assertEqual(res["withMaterial"], 1)
        self.assertEqual(res["videos"], 1)
        self.assertEqual(res["variants"][0]["all"]["ranges"], 1)


if __name__ == "__main__":
    unittest.main()
