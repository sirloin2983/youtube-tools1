"""src/eval/tools/eval_friend.py(友人の送り返しを並べて数える道具。F1 の F2)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_eval_friend.py

作業データは一時フォルダに作る(本物は読まない・書かない)。
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
from eval.tools import eval_friend as F  # noqa: E402


def put(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


class TestEvalFriend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-evfr-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        base = os.path.join(self.tmp, "app", "friend-returns", "2026-10", "rq1")
        run = os.path.join(base, "r1")
        put(os.path.join(run, "manifest.json"), {"schema": "youtube-tools-outbox/v1", "at": 1760000000000})
        put(os.path.join(run, "run.json"), {"state": "done", "at": 1760000000000, "packs": ["C:/x/packA", "C:/x/packB"]})
        put(os.path.join(run, "keys", "transcribe", "1-k.json"), {"inputs": {"engine": "whisper", "model": "large-v3", "device": "cuda"}})
        put(os.path.join(base, "verdicts", "packA.verdict.json"), {"verdict": "made_video", "at": 1})
        put(os.path.join(base, "verdicts", "stray.verdict.json"), {"verdict": "reject", "at": 2})
        put(os.path.join(self.tmp, "app", "friend-returns", "2026-10", "rq2", "verdicts", "p.verdict.json"), {"verdict": "keep", "at": 3})

    def test_counts(self):
        res = F.evaluate(self.tmp)
        t = res["total"]
        self.assertEqual((t["requests"], t["runs"]), (2, 1))
        self.assertEqual(t["verdicts"], {"keep": 1, "reject": 1, "made_video": 1, "unknown": 1})   # packB は答えなし
        self.assertEqual(t["devices"], {"whisper/large-v3/cuda": 1})
        self.assertEqual(t["states"], {"done": 1})

    def test_period_filters_runs(self):
        res = F.evaluate(self.tmp, since="2030-01-01")
        self.assertEqual(res["total"]["runs"], 0)

    def test_empty_and_report(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(F.main(["--data-dir", self.tmp, "--json"]), 0)
            self.assertEqual(F.main(["--data-dir", os.path.join(self.tmp, "none")]), 0)
        text = out.getvalue()
        self.assertIn("依頼 2 件", text)
        self.assertIn("動画にした", text)
        self.assertIn("まだ届いていません", text)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "app", "evals", "friend")))


if __name__ == "__main__":
    unittest.main()
