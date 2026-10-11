"""src/eval/tools/eval_layers.py(機械の層 + 人の層の往復を作業データで確かめる道具。RS8 O2-1)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_eval_layers.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。道具が何も書かないことも確かめる。
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools
REPO = os.path.dirname(os.path.dirname(HERE))   # src
sys.path.insert(0, REPO)
from eval.tools import eval_layers as E  # noqa: E402

GOOD = "aaaaaaaaaaa1"
OLD = "aaaaaaaaaaa2"
BROKEN = "aaaaaaaaaaa3"


def good_doc():
    orig = [{"start": 0.0, "end": 2.0, "text": "こんにちは"}, {"start": 2.0, "end": 4.0, "text": "天気"}, {"start": 4.0, "end": 6.0, "text": "消す行"}]
    segs = [{"id": "s1", "start": 0.0, "end": 2.0, "text": "こんにちは", "speaker": "S1", "flag": ""},
            {"id": "s2", "start": 2.0, "end": 4.0, "text": "いい天気", "speaker": "", "flag": "", "proofed": True, "proofedAt": 5}]
    return {"schema": "youtube-tools-transcript/v1", "id": GOOD, "title": "良い", "speakers": [{"id": "S1", "name": "ぺこら", "color": "#39f"}],
            "segments": segs, "original": orig, "updatedAt": 9}


def old_doc():
    """行に speaker の欄が無い古い形(組み立てると欄が足される = 合わない)"""
    return {"id": OLD, "title": "古い", "speakers": [], "segments": [{"id": "s1", "start": 0.0, "end": 1.0, "text": "あ", "flag": ""}],
            "original": [{"start": 0.0, "end": 1.0, "text": "あ"}]}


class EvalLayersTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="evlayers-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.tdir = os.path.join(self.root, "transcribe", "transcripts")
        os.makedirs(self.tdir)
        for tid, d in ((GOOD, good_doc()), (OLD, old_doc())):
            with open(os.path.join(self.tdir, tid + ".json"), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        with open(os.path.join(self.tdir, BROKEN + ".json"), "w", encoding="utf-8") as f:
            f.write("{壊れた")

    def snapshot(self):
        out = {}
        for d, _dirs, files in os.walk(self.root):
            for n in files:
                p = os.path.join(d, n)
                out[p] = os.path.getmtime(p)
        return out

    def test_evaluate(self):
        before = self.snapshot()
        res = E.evaluate(self.root)
        self.assertEqual(self.snapshot(), before)   # 読むだけ
        self.assertEqual((res["docs"], res["ok"], res["ng"], res["unreadable"]), (2, 1, 1, 1))
        self.assertEqual(res["reasons"], {"speaker": 1})
        self.assertEqual(res["examples"][0]["id"], OLD)
        self.assertEqual(res["size"], {"rows": 3, "kept": 1, "attr": 1, "text": 1, "dead": 1})   # s1 は話者の属性の行・s2 は校正済みの文字の行・3 行目は消す印
        self.assertEqual(res["rebuiltNg"], [OLD])
        self.assertEqual(res["machChanged"], 0)

    def test_ids_and_report(self):
        res = E.evaluate(self.root, ids=[GOOD])
        self.assertEqual((res["docs"], res["ok"]), (1, 1))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(E.evaluate(self.root))
        self.assertIn("合った 1 本・合わない 1 本", buf.getvalue())
        self.assertIn("話者", buf.getvalue())

    def test_main_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(E.main(["--data-dir", self.root, "--json", "--ids", GOOD]), 0)
        res = json.loads(buf.getvalue())
        self.assertEqual((res["schema"], res["ok"], res["ng"]), (E.SCHEMA, 1, 0))
        self.assertFalse(os.path.isdir(os.path.join(self.root, "transcribe", "evals")))   # --json もファイルに書かない


if __name__ == "__main__":
    unittest.main()
