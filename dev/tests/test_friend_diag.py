"""dev/friend_diag.py(届いた診断を読む道具)のテスト。一時フォルダだけ(本物の Dropbox は読まない)。
リポジトリ直下で: py -3.12 -m unittest dev/tests/test_friend_diag.py"""
import contextlib
import io
import json
import os
import sys
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(REPO, "dev"), os.path.join(REPO, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import friend_diag as F  # noqa: E402
from friendapp import diag as G  # noqa: E402
from ytt import testkit  # noqa: E402

RID = "20261018-100000-abcdef"
NOW_MS = int(time.time() * 1000)


class FakeRun:
    id, request_id, state, error = "r1", RID, "done", ""

    def __init__(self):
        t = NOW_MS - 600000
        self.steps = [{"key": "normalize", "startedAt": t, "finishedAt": t + 60000, "state": "done"},
                      {"key": "transcribe", "startedAt": t + 60000, "finishedAt": t + 360000, "state": "done"}]

    def all_packs(self):
        return ["a"]


class FriendDiagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "frienddiagtool-")
        self.dir = os.path.join(self.tmp, "診断")
        places = {"home": self.tmp, "data": os.path.join(self.tmp, "data"), "outbox": self.dir}
        d = G.Diag(places, env={}, gpu_fn=lambda: {"name": "RTX 3060"})
        d.run(FakeRun(), {"id": RID, "kind": "url", "form": {}}, [])
        d.write("sync", summary="同期の 送り返し: つながりません timed out")
        testkit.write_json(os.path.join(self.dir, "launcher__diag-%013d.diag.json" % (NOW_MS - 5000)),
                           {"v": 1, "kind": "start", "source": "exe", "at": NOW_MS - 5000, "summary": "起きませんでした", "exitCode": 1,
                            "tail": ["Traceback", "ImportError: x"], "app": {"version": "0.99.18"}, "pc": {"windows": "Windows 11"}})
        self.old = "app__diag-%013d.diag.json" % (NOW_MS - 4 * 86400 * 1000)
        testkit.write_text(os.path.join(self.dir, self.old), "{}")
        testkit.write_text(os.path.join(self.dir, "app__diag-%013d.diag.json" % (NOW_MS - 9000)), "{壊れ")

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = F.main(["--dir", self.dir] + list(args))
        return code, err.getvalue() + out.getvalue()

    def test_list_prunes_old_and_shows_stages(self):
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("3 日より前の診断を 1 件消しました", out)
        self.assertNotIn(self.old, os.listdir(self.dir))
        self.assertIn("normalize 60秒・transcribe 300秒", out)
        self.assertIn("計 360秒", out)
        self.assertIn("ImportError: x", out)
        self.assertIn("読めません", out)
        self.assertIn("RTX 3060", out)

    def test_keep_errors_id_json(self):
        _code, out = self.run_main("--keep", "--errors")
        self.assertIn(self.old, os.listdir(self.dir))
        self.assertNotIn("normalize", out)   # うまくいった実行は出さない
        self.assertIn("sync", out)
        out_io = io.StringIO()
        with contextlib.redirect_stdout(out_io):
            F.main(["--dir", self.dir, "--id", RID, "--json"])
        got = json.loads(out_io.getvalue())
        self.assertEqual([(g["kind"], g["requestId"]) for g in got], [("run", RID)])
        _code, out = self.run_main("-n", "1")
        self.assertEqual(out.count("要約:") + out.count("読めません"), 1)

    def test_missing_folder(self):
        out_io = io.StringIO()
        with contextlib.redirect_stdout(out_io):
            code = F.main(["--dir", os.path.join(self.tmp, "無い")])
        self.assertEqual(code, 0)
        self.assertIn("まだ診断が届いていません", out_io.getvalue())


if __name__ == "__main__":
    unittest.main()
