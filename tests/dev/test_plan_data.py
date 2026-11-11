"""dev/plan_data.py(計画のデータ plan/data/ の 1 件 1 ファイルと data.js の生成)のテスト。一時フォルダだけを使う"""
import json
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import plan_data  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_fixture import lay  # noqa: E402

PLAN = {
    "updated": "2026-10-18",
    "summary": "全体の説明。",
    "versions": [["全体(仮)", "0.0.1"], ["ui-kit", "v1"]],
    "recent": [{"id": "①", "name": "前"}, {"id": "②", "name": "次"}],
    "lines": [{"id": "A", "name": "線A", "docs": ["x.md"]}],
    "tasks": [
        {"id": "T1", "name": "仕事 1", "line": "A", "state": "done", "pre": []},
        {"id": "統1", "name": "仕事 2", "line": "A", "state": "next", "pre": ["T1", "U1", "H1"]},
    ],
    "userTasks": {
        "notes": ["メモ"],
        "ordered": [{"id": "U1", "name": "やる", "why": "x"}],
        "later": [{"id": "U2", "name": "あとで", "why": "y"}],
    },
    "history": [{"id": "H1", "name": "済んだ", "line": "A"}],
}


class PlanDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = os.path.join(self.tmp.name, "plan")
        os.makedirs(self.plan)
        self.orig = PLAN
        lay(self.plan, PLAN)
        plan_data.build(self.plan, version="9.9.9")

    def tearDown(self):
        self.tmp.cleanup()

    def built(self):
        with open(os.path.join(self.plan, "data.js"), encoding="utf-8") as f:
            text = f.read()
        return text, plan_data.load(self.plan, version="9.9.9")

    def test_build_round_trip(self):
        text, back = self.built()
        self.assertTrue(text.startswith("/* plan/data.js — 自動で作る(dev/plan_data.py build)。手で直さない"))
        for k in ("updated", "summary", "recent", "lines", "tasks", "history"):
            self.assertEqual(back[k], self.orig[k], k)
        self.assertEqual(back["versions"], [["全体(仮)", "9.9.9"], ["ui-kit", "v1"]])
        ut = back["userTasks"]
        self.assertEqual(ut["ordered"], self.orig["userTasks"]["ordered"])
        self.assertEqual(ut["later"], self.orig["userTasks"]["later"])
        self.assertEqual(plan_data.slug("CON"), "con_")   # Windows の予約名はファイルにできない
        self.assertNotEqual(plan_data.slug("統1"), plan_data.slug("統2"))
        self.assertEqual(plan_data.check(self.plan), [])
        self.assertEqual(plan_data.build(self.plan, version="9.9.9"), (False, []))   # 同じなら書かない

    def test_check_finds_problems_and_build_keeps_old(self):
        tasks = os.path.join(self.plan, "data", "tasks")
        with open(os.path.join(tasks, "t1.json"), "w", encoding="utf-8") as f:
            f.write('{"id": "T1", "name": "x", "state": "done",}')
        with open(os.path.join(tasks, "zz.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "T9", "name": "x", "pre": ["NO"]}, f)
        msgs = [m for _f, _l, m in plan_data.check(self.plan)]
        self.assertTrue(any(m.startswith("読めない(JSON)") for m in msgs))
        self.assertIn("欄が無い: state", msgs)
        self.assertIn("ファイル名が id と合わない(t9.json にする)", msgs)
        self.assertIn("pre の NO が tasks・history・user のどれにも無い", msgs)
        before, _ = self.built()
        wrote, probs = plan_data.build(self.plan, version="1.0.0")
        self.assertFalse(wrote)
        self.assertTrue(probs)
        self.assertEqual(self.built()[0], before)


if __name__ == "__main__":
    unittest.main()
