"""dev/plan_artifact.py(計画のページ plan/ を 1 枚の公開用 HTML に組む道具)のテスト。目次と Artifact 用の 1 枚・ホームの自動の部分・版と参照・図を見る。"""
import json
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
  summary: "一文目。二文目(括弧の。中)。三文目。四文目。",
  url: "https://example.com/x",   // 末尾コメント
  lines: [
    { id: "A", name: "線A", pct: 10, next: "次の物", aim: "docs/spec/a.md を読む", docs: ["x.md", "../docs/spec/a.md"], },
    { id: "B", name: "線B", pct: 20, next: "docs/spec/none.md は無い" },
  ],
  userTasks: { provisional: [{ id: "p1" }, { id: "p2" }] },
  tasks: [
    { id: "T1", name: "仕事 1(plan/x.md)", line: "A", state: "done" },
    { id: "T2", name: "仕事 2", line: "A・B", state: "doing" },
    { id: "T3", name: "どこにも無い線", line: "Z", state: "wait" },
  ],
};
"""

HTML = ('<!doctype html><html><head><title>t</title><link rel="stylesheet" href="plan.css"></head>'
        '<body><script src="data.js"></script><script src="plan.js"></script><p>hi</p></body></html>')

HAND_BEGIN = "<!-- 自動: ここから(dev/plan_artifact.py が書く。手で直さない) -->\n"
HAND_END = "<!-- 自動: ここまで -->\n"
LINKS = "[r](../design/r.md#a) [w](2026-10-05週.md) [u](https://x.jp/a) [o](../../../外.md) [p](#まとめ)"


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


def read(plan, rel):
    with open(os.path.normpath(os.path.join(plan, rel)), "rb") as f:
        raw = f.read()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8")


class PlanArtifactTest(unittest.TestCase):
    def test_index_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_vault(os.path.join(tmp, "vault"))
            out = os.path.join(tmp, "out")
            r = run(plan, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = read(plan, "計画の索引.md")
            self.assertTrue(text.startswith("---\n種類: 索引\n状態: 有効\n---\n"))
            self.assertIn("2026-10-12", text)
            self.assertIn("[線 A 線A](線A.md)(進み 10%)", text)
            a = read(plan, "線A.md")
            self.assertIn("[`docs/spec/a.md`](../docs/spec/a.md)", a)
            self.assertIn("T1 仕事 1", a)
            self.assertIn("T3 どこにも無い線", read(plan, "線その他.md"))
            self.assertIn("無い資料: docs/spec/none.md(線 B)", r.stderr)
            self.assertNotIn("無い資料: docs/spec/a.md", r.stderr)
            with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
                self.assertIn("window.PLAN_NO_MD", f.read())
            # 同じ data.js なら同じ中身
            home = read(plan, "../ホーム.md")
            r2 = run(plan, out)
            self.assertEqual(read(plan, "計画の索引.md"), text)
            self.assertEqual(read(plan, "線A.md"), a)
            self.assertEqual(read(plan, "../ホーム.md"), home)
            self.assertEqual(r2.stderr, r.stderr)

    def test_home_relinks_week_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_vault(os.path.join(tmp, "vault"))
            wl = os.path.join(tmp, "vault", "docs", "worklog")
            os.makedirs(wl)
            for name, body in (("2026-10-05週.md", "# 古い\n## まとめ\n古い話\n"),
                               ("2026-10-12週.md", "# 新\n## まとめ\n新しい話 " + LINKS + "\n- 点\n\n---\n後ろ\n")):
                with open(os.path.join(wl, name), "w", encoding="utf-8", newline="") as f:
                    f.write(body)
            self.assertEqual(run(plan, os.path.join(tmp, "out")).returncode, 0)
            home = read(plan, "../ホーム.md")
            # 週の記録からの相対リンクを、ホーム(保管庫の直下)から見たパスに直して転記する
            self.assertIn("新しい話 [r](docs/design/r.md#a) [w](docs/worklog/2026-10-05週.md) "
                          "[u](https://x.jp/a) [o](../../../外.md) [p](#まとめ)\n- 点", home)
            self.assertNotIn("古い話", home)
            self.assertNotIn("後ろ", home)

    def test_version_and_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_vault(os.path.join(tmp, "vault"))
            js = os.path.join(plan, "data.js")
            with open(js, encoding="utf-8") as f:
                body = f.read()
            body = body.replace('updated: "2026-10-12",',
                                'updated: "2026-10-12",\r\n  versions: [\r\n    ["全体(仮)", "0.0.1"], ["ui-kit", "v1"]\r\n  ],')
            body = body.replace('summary: "一文目。', 'summary: "仮決め 9 件。消した git:cbe1a64:docs/spec/gone.md を読む。一文目。')
            body = body.replace('docs: ["x.md", "../docs/spec/a.md"]', 'docs: ["x.md", "../docs/spec/a.md", "../dev/plan_artifact.py"]')
            with open(js, "w", encoding="utf-8", newline="") as f:
                f.write(body)
            r = run(plan, os.path.join(tmp, "out"))
            self.assertEqual(r.returncode, 0, r.stderr)
            sys.path.insert(0, os.path.join(REPO, "src"))
            from ytt.version import VERSION
            with open(js, encoding="utf-8", newline="") as f:
                after = f.read()
            self.assertIn('["全体(仮)", "%s"], ["ui-kit", "v1"]' % VERSION, after)   # 全体の版だけ version.py から
            self.assertIn("\r\n  versions:", after)   # 改行は変えない
            self.assertIn("「仮決め 9 件」が provisional の数 2 と違う", r.stderr)
            self.assertNotIn("gone.md", r.stderr)   # git:<コミット>: の後ろは消した資料 = 警告しない
            self.assertNotIn("plan_artifact.py", r.stderr)
            self.assertIn("`dev/plan_artifact.py`(リポジトリ)", read(plan, "線A.md"))

    def test_home_keeps_hand_written_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = make_vault(os.path.join(tmp, "vault"))
            home_path = os.path.join(tmp, "vault", "ホーム.md")
            with open(home_path, "w", encoding="utf-8", newline="") as f:
                f.write("手書き 1\n" + HAND_BEGIN + "古い\n" + HAND_END + "手書き 2\n")
            self.assertEqual(run(plan, os.path.join(tmp, "out")).returncode, 0)
            home = read(plan, "../ホーム.md")
            self.assertTrue(home.startswith("手書き 1\n" + HAND_BEGIN))
            self.assertTrue(home.endswith(HAND_END + "手書き 2\n"))
            self.assertNotIn("古い\n", home)
            self.assertIn("## 今の状況", home)
            self.assertEqual(home.count("自動: ここから"), 1)
            # 印が無いときは末尾に足す
            with open(home_path, "w", encoding="utf-8", newline="") as f:
                f.write("手書きだけ\n")
            self.assertEqual(run(plan, os.path.join(tmp, "out")).returncode, 0)
            home = read(plan, "../ホーム.md")
            self.assertTrue(home.startswith("手書きだけ\n\n" + HAND_BEGIN))
            self.assertTrue(home.endswith(HAND_END))

    def test_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = os.path.join(tmp, "保管庫", "proj")
            plan = make_vault(vault)
            gdir = os.path.join(tmp, "保管庫", ".obsidian")
            os.makedirs(gdir)
            with open(os.path.join(gdir, "graph.json"), "w", encoding="utf-8") as f:
                json.dump({"search": "", "scale": 2, "colorGroups": []}, f)
            self.assertEqual(run(plan, os.path.join(tmp, "out")).returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(tmp, "保管庫", "ホーム.md")))  # --graph なしでは触らない
            self.assertEqual(run(plan, os.path.join(tmp, "out"), "--graph").returncode, 0)
            with open(os.path.join(gdir, "graph.json"), encoding="utf-8") as f:
                g = json.load(f)
            self.assertEqual(g["scale"], 2)
            self.assertEqual(g["search"], "-[状態:済み] -[状態:置き換え済み] -[状態:取り下げ]")
            root_home = os.path.join(tmp, "保管庫", "ホーム.md")
            with open(root_home, encoding="utf-8") as f:
                self.assertIn("](proj/ホーム.md)", f.read())
            with open(root_home, "w", encoding="utf-8") as f:  # 手で直した物は上書きしない
                f.write("mine")
            run(plan, os.path.join(tmp, "out"), "--graph")
            with open(root_home, encoding="utf-8") as f:
                self.assertEqual(f.read(), "mine")


if __name__ == "__main__":
    unittest.main()
