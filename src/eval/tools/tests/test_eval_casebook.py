"""src/eval/tools/eval_casebook.py(スタジオの配信を候補 + 採用に分けて重ね直す往復を作業データで確かめる道具。RS8 B3-3)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_eval_casebook.py

作業データと書き出し先は一時フォルダに作る(本物の作業データは読まない・書かない)。道具が何も書かないことも確かめる。
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools
REPO = os.path.dirname(os.path.dirname(HERE))   # src
sys.path.insert(0, REPO)
from eval.tools import eval_casebook as E  # noqa: E402
from flow import casebook  # noqa: E402
from ytt import names  # noqa: E402

VID = "vidAAAAAAAA"
REC = "20261011-120000"
OTHER = "vidBBBBBBBB"


def mark(mid, s, e, **kw):
    d = {"id": mid, "start": s, "end": e, "label": "", "src": "manual", "score": None, "reasons": [], "parts": {}, "peak": None, "live": False,
         "status": "", "file": "", "createdAt": 1700000000000}
    d.update(kw)
    return d


def auto(mid, s, e, **kw):
    return mark(mid, s, e, src="auto", score=3.0, auto0=[s, e], **kw)


def video(vid, marks, **kw):
    v = {"id": vid, "kind": "youtube", "title": "題", "channel": "ch", "duration": 3600.0, "fileName": "", "path": "", "marks": marks,
         "analysis": {"at": 1}, "rev": 2, "createdAt": 1700000000000, "updatedAt": 1700000000500}
    v.update(kw)
    return v


class EvalCasebookTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="evcasebook-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = os.path.join(self.root, "out")
        case = os.path.join(self.out, "題")
        names.write_owner(case, VID)
        clip = os.path.join(case, "01_x.mp4")
        live = {"recorder": "rec1", "recording": REC, "url": "https://www.youtube.com/watch?v=" + VID, "videoId": VID}
        videos = {
            VID: video(VID, [mark("m2", 900, 920), auto("a1", 10, 40), mark("m1", 50, 80, status="exported", file="題/01_x.mp4", path=clip)]),
            REC: video(REC, [mark("m9", 50, 80, status="exported", file="題/01_x.mp4", path=clip, live=True)], kind="live", live=live,
                       analysis=None, duration=0.0),
            OTHER: video(OTHER, [auto("a1", 10, 40), mark("m1", 50, 80, status="adopted")]),
            "brokenAAAAA": {"id": "brokenAAAAA", "kind": "nope"},
        }
        sdir = os.path.join(self.root, "studio")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "data.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/v1", "videos": videos, "groups": {}}, f, ensure_ascii=False)
        with open(os.path.join(sdir, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"outDir": self.out}, f)
        p = mock.patch.object(casebook._fsio, "is_fixed_drive", return_value=True)
        p.start()
        self.addCleanup(p.stop)

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
        self.assertEqual(self.snapshot(), before)   # 読むだけ(案件のファイルも作らない)
        self.assertEqual(res["outDir"], self.out)   # 書き出し先は作業データのスタジオの設定から
        self.assertEqual((res["videos"], res["broken"], res["ok"], res["ng"]), (3, 1, 3, 0))
        self.assertEqual((res["withCase"], res["cases"], res["sharedCases"]), (2, 1, 1))   # 録画とアーカイブが 1 つの案件
        self.assertEqual((res["candidateMarks"], res["ordered"], res["relPaths"]), (2, 1, 2))

    def test_diff_reasons(self):
        v = video(VID, [mark("m1", 1, 2), mark("m2", 3, 4)])
        self.assertEqual(E.diff_reasons(v, json.loads(json.dumps(v))), [])
        self.assertEqual(E.diff_reasons(v, None), [("missing", "")])
        w = json.loads(json.dumps(v))
        w["title"] = "x"
        w["marks"].reverse()
        self.assertEqual([c for c, _ in E.diff_reasons(v, w)], ["fields", "order"])
        w = json.loads(json.dumps(v))
        w["marks"][1]["label"] = "x"
        self.assertEqual(E.diff_reasons(v, w), [("marks", "m2: label")])
        w["marks"].pop()
        self.assertEqual([c for c, _ in E.diff_reasons(v, w)], ["count"])

    def test_report_and_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(E.evaluate(self.root, ids=[OTHER]))
        self.assertIn("合った 1 本・合わない 0 本", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(E.main(["--data-dir", self.root, "--json", "--out-dir", self.out]), 0)
        res = json.loads(buf.getvalue())
        self.assertEqual((res["schema"], res["ok"]), (E.SCHEMA, 3))

    def test_unreadable(self):
        with open(os.path.join(self.root, "studio", "data.json"), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(E.main(["--data-dir", self.root]), 1)
        self.assertIn("読めません", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
