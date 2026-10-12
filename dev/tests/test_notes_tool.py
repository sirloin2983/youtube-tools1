"""dev/notes_tool.py(資料のフォルダのパスの検査と、資料を動かす道具)のテスト。一時フォルダの資料のフォルダと git で確かめる"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

DEV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DEV)
import notes_tool  # noqa: E402


def put(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))


def get(root, rel):
    with open(os.path.join(root, rel), "rb") as f:
        return f.read().decode("utf-8")


class NotesToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.v = os.path.join(self.tmp, "vault")
        self.repo = os.path.join(self.tmp, "repo")
        put(self.v, "docs/spec/a.md", "[`plan/p.md`](../../plan/p.md) と [送る] (友人へ届ける)\n")
        put(self.v, "plan/p.md", "[`docs/spec/a.md`](../docs/spec/a.md)・[外](https://example.com)\n")
        put(self.v, "plan/data.js", 'docs: ["p.md", "../docs/spec/a.md"] 文 plan/p.md(説明)\n')
        put(self.repo, "src/x.py", '"""設計 notes:plan/p.md の 2 節・notes:docs/spec/a.md"""\n')
        subprocess.run(["git", "init", "-q", self.v], check=True)
        subprocess.run(["git", "-C", self.v, "config", "core.autocrlf", "false"], check=True)
        subprocess.run(["git", "-C", self.v, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.v, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True)
        self.old = (os.environ.get("YTT_NOTES_DIR"), notes_tool.REPO)
        os.environ["YTT_NOTES_DIR"] = self.v
        notes_tool.REPO = self.repo

    def tearDown(self):
        env, notes_tool.REPO = self.old
        if env is None:
            os.environ.pop("YTT_NOTES_DIR", None)
        else:
            os.environ["YTT_NOTES_DIR"] = env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_finds_only_broken(self):
        self.assertEqual(notes_tool.check(), [])   # 本文のかっこ・外の URL は数えない
        os.remove(os.path.join(self.v, "plan", "p.md"))
        where = sorted(w for w, _, _ in notes_tool.check())
        self.assertEqual(where, ["docs/spec/a.md", "plan/data.js", "plan/data.js", "src/x.py"])

    def test_mv_fixes_links_data_and_notes_refs(self):
        notes_tool.mv([("plan/p.md", "plan/done/p.md")])
        self.assertEqual(get(self.v, "docs/spec/a.md"), "[`plan/done/p.md`](../../plan/done/p.md) と [送る] (友人へ届ける)\n")
        self.assertIn("[`docs/spec/a.md`](../../docs/spec/a.md)", get(self.v, "plan/done/p.md"))   # 動かした文書の中のリンク
        self.assertEqual(get(self.v, "plan/data.js"), 'docs: ["done/p.md", "../docs/spec/a.md"] 文 plan/done/p.md(説明)\n')
        self.assertIn("notes:plan/done/p.md の 2 節", get(self.repo, "src/x.py"))
        self.assertEqual(notes_tool.check(), [])

    def test_mv_folder(self):
        notes_tool.mv([("docs/spec", "docs/old/spec")])
        self.assertIn("(../../../plan/p.md)", get(self.v, "docs/old/spec/a.md"))
        self.assertIn("notes:docs/old/spec/a.md", get(self.repo, "src/x.py"))
        self.assertEqual(notes_tool.check(), [])

    def test_prose_brackets(self):
        put(self.v, "docs/b.md", "[送る](友人へ届ける)・[`x`](y)・`[a](b)`・[外](https://e.com)\n```\n[c](d)\n```\n[見る](`pollJobs`)\n")
        self.assertEqual([p for w, _, p in notes_tool.check() if w == "docs/b.md"][0][-12:], "[送る](友人へ届ける)")
        fixed = notes_tool.unlink_prose(get(self.v, "docs/b.md"))
        self.assertEqual(fixed, "[送る] (友人へ届ける)・[`x`] (y)・`[a](b)`・[外](https://e.com)\n```\n[c](d)\n```\n[見る] (`pollJobs`)\n")

    def test_relink_text(self):
        old, new = os.path.join(self.v, "docs", "W.md"), os.path.join(self.v, "docs", "worklog", "w1.md")
        out = notes_tool.relink_text("[`docs/spec/a.md`](spec/a.md#2)・[u](http://x)", old, new)
        self.assertEqual(out, "[`docs/spec/a.md`](../spec/a.md#2)・[u](http://x)")


if __name__ == "__main__":
    unittest.main()
