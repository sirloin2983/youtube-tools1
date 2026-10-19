"""dev/plan_data.py(計画のデータ plan/data/ の 1 件 1 ファイルと data.js の生成・仮決めの自動の確定)のテスト。一時フォルダだけを使う"""
import datetime
import json
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import plan_artifact  # noqa: E402
import plan_data  # noqa: E402

DATA_JS = """/* 手書きのころ */
window.PLAN = {
  updated: "2026-10-18",
  summary: "全体の説明。",
  versions: [["全体(仮)", "0.0.1"], ["ui-kit", "v1"]],
  recent: [{ id: "①", name: "前" }, { id: "②", name: "次" }],
  lines: [{ id: "A", name: "線A", docs: ["x.md"] }],
  tasks: [
    { id: "T1", name: "仕事 1", line: "A", state: "done", pre: [] },
    { id: "統1", name: "仕事 2", line: "A", state: "next", pre: ["T1", "U1", "H1"] },
  ],
  userTasks: {
    notes: ["メモ"],
    ordered: [{ id: "U1", name: "やる", why: "x" }],
    later: [{ id: "U2", name: "あとで", why: "y" }],
    provisional: [
      { sec: "3-88", id: "(a)", date: "10-18", what: "軽い物", impact: "小" },
      { sec: "3-87", id: "(b)", date: "10-17", what: "重い物", impact: "大" },
    ],
  },
  history: [{ id: "H1", name: "済んだ", line: "A" }],
};
"""


class PlanDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plan = os.path.join(self.tmp.name, "plan")
        os.makedirs(self.plan)
        with open(os.path.join(self.plan, "data.js"), "w", encoding="utf-8") as f:
            f.write(DATA_JS)
        self.orig = plan_artifact.parse_plan_js(DATA_JS)
        plan_data.split(self.plan, weights={0: {"w": "軽"}, 1: {"w": "重", "why": ["データ"]}})
        plan_data.build(self.plan, version="9.9.9")

    def tearDown(self):
        self.tmp.cleanup()

    def built(self):
        with open(os.path.join(self.plan, "data.js"), encoding="utf-8") as f:
            text = f.read()
        return text, plan_artifact.parse_plan_js(text)

    def test_split_round_trip(self):
        text, back = self.built()
        self.assertTrue(text.startswith("/* plan/data.js — 自動で作る(dev/plan_data.py build)。手で直さない"))
        for k in ("updated", "summary", "recent", "lines", "tasks", "history"):
            self.assertEqual(back[k], self.orig[k], k)
        self.assertEqual(back["versions"], [["全体(仮)", "9.9.9"], ["ui-kit", "v1"]])
        ut = back["userTasks"]
        self.assertEqual(ut["ordered"], self.orig["userTasks"]["ordered"])
        self.assertEqual([p["id"] for p in ut["provisional"]], ["(b)", "(a)"])   # 重い物が先
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

    def test_sweep_confirms_only_light_old_unheld(self):
        pv = plan_data.new(self.plan, "provisional", "(c)", {"sec": "3-89", "what": "迷う物"})
        with open(pv, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["weight"], "重")   # 重さを書かない物は重い側
        self.assertEqual(plan_data.sweep(self.plan, datetime.date(2026, 10, 24)), 0)   # 7 日たっていない
        path = os.path.join(self.plan, "data", "provisional", "3-88-a.json")
        with open(path, encoding="utf-8") as f:
            it = json.load(f)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(it, hold=True), f, ensure_ascii=False)
        self.assertEqual(plan_data.sweep(self.plan, datetime.date(2026, 10, 25)), 0)   # 止めた物は確定しない
        with open(path, "w", encoding="utf-8") as f:
            json.dump(it, f, ensure_ascii=False)
        self.assertEqual(plan_data.sweep(self.plan, datetime.date(2026, 10, 25)), 1)   # 軽い (a) だけ
        self.assertEqual(os.listdir(os.path.join(self.plan, "data", "confirmed")), ["3-88-a.json"])
        _, back = self.built()
        self.assertEqual([p["id"] for p in back["userTasks"]["provisional"]], ["(c)", "(b)"])


if __name__ == "__main__":
    unittest.main()
