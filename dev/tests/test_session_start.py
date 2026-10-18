"""dev/session_start.py(セッションの入口の要約・子への指示文の下書き)のテスト。一時フォルダの git と偽の保管庫だけを使う"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import session_start as ss  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # サーバーは動かさないが、test_ytt_core の見張り(serve の語を含むテスト)に合わせる


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
                   + list(args), cwd=cwd, check=True, capture_output=True, creationflags=NOWIN)


def snapshot(root):
    """-> {相対パス: (大きさ, 更新の時刻)}(.git の中も含む = 読むだけを確かめる)"""
    out = {}
    for d, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            st = os.stat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns)
    return out


class SessionStartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = mock.patch.dict(os.environ, {"APPDATA": os.path.join(self.tmp.name, "appdata")})   # 本物の共有メモを読まない
        env.start()
        self.addCleanup(env.stop)
        base = self.tmp.name
        self.repo = os.path.join(base, "repo")
        self.notes = os.path.join(base, "notes")
        # リポジトリ: main に 1 コミット・作業の枝(worktree)に 1 コミットと未コミット
        write(os.path.join(self.repo, "src", "ytt", "version.py"), 'VERSION = "1.2.3"\n')
        write(os.path.join(self.repo, "src", "friendapp", "api.py"), "# 口\n")
        write(os.path.join(self.repo, "codemap", "index.md"), "# 目次\n")
        write(os.path.join(self.repo, "codemap", "friendapp.md"),
              "# 地図\n\n## src/friendapp/\n\n- **api.py** (1 行) — 口\n- **server.py** (1 行) — 玄関\n")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "最初")
        self.wt = os.path.join(base, "wt-friend")
        git(self.repo, "worktree", "add", "-q", "-b", "claude/friend", self.wt)
        write(os.path.join(self.wt, "src", "friendapp", "api.py"), "# 口を直した\n")
        git(self.wt, "commit", "-q", "-am", "友人の口を直す")
        write(os.path.join(self.wt, "src", "friendapp", "server.py"), "# 作業中\n")
        # 偽の保管庫
        write(os.path.join(self.notes, "AGENTS.md"),
              "# 決まり\n\n## 何を触るときに何を読むか\n| 触る物 | 読む物 |\n| --- | --- |\n"
              "| 友人の依頼・友人の PC | [`docs/spec/friend.md`](docs/spec/friend.md) |\n"
              "| 案件の画面 | [`docs/spec/cases.md`](docs/spec/cases.md) |\n\n## 次の節\n| 友人 | 当たらない |\n")
        write(os.path.join(self.notes, "docs", "spec", "friend.md"), "# 友人\n")
        write(os.path.join(self.notes, "docs", "spec", "cases.md"), "# 案件\n")
        write(os.path.join(self.notes, "docs", "子への指示文の雛形.md"),
              "# 雛形\n\n説明\n\n```\n**決まり**\n- 日本語で。\n\n**完了の条件(いつもの)**\n- lint 0。\n```\n\n後書き\n")
        write(os.path.join(self.notes, "plan", "仮決めの一覧.md"),
              "# 一覧\n\n## まだの重い物(2 件)\n\n1. **3-1 (a)** — 一つ目\n2. **3-2 (b)** — 二つ目\n\n## 軽い物\n3. 当たらない\n")
        for name, item in {"a1": {"id": "A1", "name": "済んだ", "state": "done", "order": 1},
                           "a2": {"id": "A2", "name": "作っている", "state": "doing", "who": "AI", "order": 2},
                           "a3": {"id": "A3", "name": "あとで", "state": "todo", "order": 3}}.items():
            write(os.path.join(self.notes, "plan", "data", "tasks", name + ".json"), json.dumps(item, ensure_ascii=False))
        write(os.path.join(self.notes, "plan", "data", "user", "u1.json"),
              json.dumps({"id": "U1", "name": "答える", "list": "ordered", "state": "next"}, ensure_ascii=False))
        write(os.path.join(self.notes, "plan", "data", "user", "u2.json"),
              json.dumps({"id": "U2", "name": "あとで", "list": "later", "state": "wait"}, ensure_ascii=False))
        write(os.path.join(self.notes, "docs", "worklog", "2026-10-12週", "2026-10-18-code-map.md"),
              "---\nまとめ: 地図を作った\n---\n# 10-18 地図\n")
        write(os.path.join(self.notes, "docs", "worklog", "2026-10-12週", "2026-10-17-old.md"),
              "---\nまとめ: (1 行で。週のまとめに出る)\n---\n# 10-17 前\n")
        write(os.path.join(self.notes, "shared", "境目-friend.md"), "# 境目: 友人の口\n- 決めた\n")
        git(self.notes, "init", "-q", "-b", "main")
        git(self.notes, "add", "-A")
        git(self.notes, "commit", "-q", "-m", "資料")

    def tearDown(self):
        subprocess.run(["git", "worktree", "remove", "--force", self.wt], cwd=self.repo, capture_output=True,
                       creationflags=NOWIN)
        self.tmp.cleanup()

    def test_summary_reads_every_source_and_writes_nothing(self):
        before = snapshot(self.tmp.name)
        t0 = time.time()
        text = ss.summary("friendapp", self.repo, self.notes, datetime.date(2026, 10, 18))
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(snapshot(self.tmp.name), before)   # 読むだけ
        self.assertLessEqual(len(text.split("\n")), 150)
        self.assertIn("版: main 1.2.3 / ここ 1.2.3", text)
        self.assertIn("最初", text)
        self.assertIn("10-18 code-map: 地図を作った", text)
        self.assertIn("10-17 old: (まとめ未記入)", text)
        self.assertIn("境目-friend.md — 境目: 友人の口", text)
        self.assertIn("[進行中] A2 作っている(AI)", text)
        self.assertNotIn("済んだ", text)
        self.assertIn("1-1 今できる 1 件・1-2 あとで 1 件", text)
        self.assertIn("[次] U1 答える", text)
        self.assertIn("まだ 2 件", text)
        self.assertIn("1. **3-1 (a)** — 一つ目", text)
        self.assertNotIn("当たらない", text)
        self.assertIn("wt-friend [claude/friend] +1・未コミット 1 友人の口を直す", text)
        self.assertIn("重なる: src/friendapp/api.py・src/friendapp/server.py", text)
        self.assertIn("- 地図: codemap/friendapp.md", text)
        self.assertIn("- spec: docs/spec/friend.md", text)
        self.assertNotIn("cases.md", text)

    def test_heavy_count_accepts_both_parens(self):
        self.assertEqual(ss.HEAVY_RE.search("## まだの重い物(3 件)").group(1), "3")
        self.assertEqual(ss.HEAVY_RE.search("## まだの重い物(4 件)").group(1), "4")

    def test_brief_uses_template_and_marks_overlap(self):
        text = ss.brief("friendapp", "友人の口を足す", self.repo, self.notes)
        self.assertTrue(text.startswith("Task:\n友人の口を足す\n"))
        self.assertIn("**決まり**\n- 日本語で。", text)
        self.assertIn("- lint 0。", text)
        self.assertNotIn("後書き", text)
        self.assertIn("- 地図: `codemap/friendapp.md`", text)
        self.assertIn("- spec: `docs/spec/friend.md`", text)
        self.assertIn("claude/friend — 友人の口を直す:重なる src/friendapp/api.py・src/friendapp/server.py", text)

    def test_unknown_domain_falls_back(self):
        cmap, spec, rows = ss.domain_refs("zzz", self.repo, self.notes)
        self.assertEqual((cmap, spec, rows), ([], [], []))
        self.assertIn("codemap/index.md", ss.brief("zzz", "何か", self.repo, self.notes, act=[]))

    def test_merged_branch_is_not_active(self):
        git(self.repo, "merge", "-q", "--no-edit", "claude/friend")
        act, total, _stale = ss.active_worktrees(self.repo)
        self.assertEqual(total, 1)
        self.assertEqual([r["ahead"] for r in act], [0])   # 未コミットがあるので出るが、先のコミットは無い

    def test_codemap_files(self):
        self.assertEqual(ss.codemap_files(os.path.join(self.repo, "codemap", "friendapp.md")),
                         ["src/friendapp/api.py", "src/friendapp/server.py"])


if __name__ == "__main__":
    unittest.main()
