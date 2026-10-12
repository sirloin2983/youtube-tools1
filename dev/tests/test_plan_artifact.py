import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "dev", "plan_artifact.py")

DATA_JS = """/* コメント */
window.PLAN = {
  updated: "2026-10-12",
  url: "https://example.com/x",   // 末尾コメント
  lines: [
    { id: "A", name: "線A", pct: 10, aim: "docs/spec/a.md を読む", docs: ["x.md", "../docs/spec/a.md"], },
    { id: "B", name: "線B", pct: 20, next: "docs/spec/none.md は無い" },
  ],
  tasks: [
    { id: "T1", name: "仕事 1(plan/x.md)", line: "A", state: "done" },
    { id: "T2", name: "仕事 2", line: "A・B", state: "doing" },
    { id: "T3", name: "どこにも無い線", line: "Z", state: "wait" },
  ],
};
"""

HTML = ('<!doctype html><html><head><title>t</title><link rel="stylesheet" href="plan.css"></head>'
        '<body><script src="data.js"></script><script src="plan.js"></script><p>hi</p></body></html>')


def make_vault(root):
    plan = os.path.join(root, "plan")
    os.makedirs(plan)
    os.makedirs(os.path.join(root, "docs", "spec"))
    files = {"plan/data.js": DATA_JS, "plan/plan.css": "p{}", "plan/plan.js": "var a=1;",
             "plan/index.html": HTML, "plan/user-tasks.html": HTML,
             "plan/x.md": "x", "docs/spec/a.md": "a"}
    for rel, body in files.items():
        with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8", newline="") as f:
            f.write(body)
    return plan


def run(plan, out, *extra):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, SCRIPT, "--plan", plan, "--out", out, *extra],
                          capture_output=True, text=True, encoding="utf-8", env=env)


class PlanArtifactTest(unittest.TestCase):
    def test_index_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_vault(os.path.join(tmp, "vault"))
            out = os.path.join(tmp, "out")
            r = run(plan, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(plan, "計画の索引.md"), "rb") as f:
                raw = f.read()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r", raw)
            text = raw.decode("utf-8")
            self.assertIn("状態: 自動で作る", text)
            self.assertIn("2026-10-12", text)
            self.assertIn("[index.html](index.html)", text)
            self.assertIn("[`docs/spec/a.md`](../docs/spec/a.md)", text)
            self.assertIn("[`plan/x.md`](x.md)", text)
            self.assertIn("[`x.md`](x.md)", text)
            self.assertIn("T1 仕事 1", text)
            self.assertIn("(済み)", text)
            self.assertIn("(進行中)", text)
            self.assertIn("## その他", text)
            self.assertIn("docs/spec/none.md は無い", text)
            self.assertNotIn("](../docs/spec/none.md)", text)
            self.assertIn("無い資料: docs/spec/none.md(線 B)", r.stderr)
            self.assertNotIn("無い資料: docs/spec/a.md", r.stderr)
            # Artifact の出力は今まで通り
            self.assertTrue(os.path.isfile(os.path.join(out, "index.html")))
            self.assertTrue(os.path.isfile(os.path.join(out, "user-tasks.html")))
            with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
                self.assertIn("window.PLAN_NO_MD", f.read())
            # 同じ data.js なら同じ中身
            r2 = run(plan, out)
            with open(os.path.join(plan, "計画の索引.md"), "rb") as f:
                self.assertEqual(f.read(), raw)
            self.assertEqual(r2.stderr, r.stderr)

    def test_no_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_vault(os.path.join(tmp, "vault"))
            r = run(plan, os.path.join(tmp, "out"), "--no-index")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(os.path.exists(os.path.join(plan, "計画の索引.md")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "out", "index.html")))


if __name__ == "__main__":
    unittest.main()
