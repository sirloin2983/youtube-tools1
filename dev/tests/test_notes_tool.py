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
        put(self.v, "plan/data.js", '// docs: ["p.md", "../docs/spec/a.md"] 文 plan/p.md(説明)\n')
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
        self.assertEqual(get(self.v, "plan/data.js"), '// docs: ["done/p.md", "../docs/spec/a.md"] 文 plan/done/p.md(説明)\n')
        self.assertIn("notes:plan/done/p.md の 2 節", get(self.repo, "src/x.py"))
        self.assertEqual(notes_tool.check(), [])

    def test_drop_points_refs_to_git(self):
        put(self.v, "plan/data.js", '// docs: ["p.md"] 文 docs/spec/a.md(説明)\n')
        notes_tool.drop(["docs/spec"], "abc1234")
        self.assertIn("[`git:abc1234:docs/spec/a.md`]".strip("[]"), get(self.v, "plan/p.md"))
        self.assertNotIn("](../docs/spec/a.md)", get(self.v, "plan/p.md"))
        self.assertIn("文 git:abc1234:docs/spec/a.md(説明)", get(self.v, "plan/data.js"))
        self.assertIn("資料の git:abc1234:docs/spec/a.md", get(self.repo, "src/x.py"))
        subprocess.run(["git", "-C", self.v, "rm", "-rq", "docs/spec"], check=True)
        self.assertEqual(notes_tool.check(), [])   # 消したあと切れたパスは無い

    def test_unlink_prose_brackets_and_tags(self):
        self.assertEqual(notes_tool.unlink_prose("[送る](友人へ届ける)・[`x`](y)・`[a](b)`・[見る](`pollJobs`)\n"),
                         "[送る] (友人へ届ける)・[`x`] (y)・`[a](b)`・[見る] (`pollJobs`)\n")   # 先がコードのかっこ書きも
        self.assertEqual(notes_tool.unlink_prose("色 #7BDF0E・#タブ・`#ok`・見出しでない #12\n## 見出し\n```\n#x\n```\n"),
                         "色 `#7BDF0E`・`#タブ`・`#ok`・見出しでない #12\n## 見出し\n```\n#x\n```\n")
        self.assertEqual(notes_tool.unlink_prose("背景 #000・LIVE と #1・2\n"), "背景 `#000`・LIVE と `#1`・2\n")   # 数字の後ろに続く物があればタグ
        self.assertEqual(notes_tool.unlink_prose("URL の #tx/#cut・【#名前 ／#shorts】・[節](a.md#x)・http://h/#y・C#\n"),
                         "URL の `#tx`/`#cut`・【`#名前` ／`#shorts`】・[節](a.md#x)・http://h/#y・C#\n")   # 記号の後ろもタグ。リンク先・URL は触らない

    def test_data_js_missing_comma_stops_check(self):
        put(self.v, "plan/data.js", "window.PLAN = {\n  tasks: [\n    {id: 1}\n    {id: 2},\n  ],\n};\n")
        self.assertTrue(any(w == "plan/data.js" and "読めない" in p for w, _, p in notes_tool.check()))
        for node in (True, False):
            why = notes_tool.explain_data_js(get(self.v, "plan/data.js"), use_node=node)
            self.assertIn("4 行目", why)
            self.assertIn(">    4|     {id: 2},", why)


if __name__ == "__main__":
    unittest.main()
