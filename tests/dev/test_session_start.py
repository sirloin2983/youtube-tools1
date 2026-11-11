"""dev/session_start.py(セッションの入口の要約・子への指示文の下書き)のテスト。一時フォルダの git と偽の保管庫だけを使う"""
import datetime
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
              "| 友人の依頼・友人の PC | [`今の道具の仕様/友人まわり.md`](今の道具の仕様/友人まわり.md) |\n"
              "| 案件の画面 | [`今の道具の仕様/案件と確かめる.md`](今の道具の仕様/案件と確かめる.md) |\n\n## 次の節\n| 友人 | 当たらない |\n")
        write(os.path.join(self.notes, "今の道具の仕様", "友人まわり.md"), "# 友人\n")
        write(os.path.join(self.notes, "今の道具の仕様", "案件と確かめる.md"), "# 案件\n")
        write(os.path.join(self.notes, "docs", "子への指示文の雛形.md"),
              "# 雛形\n\n説明\n\n```\n**決まり**\n- 日本語で。\n\n**完了の条件(いつもの)**\n- lint 0。\n```\n\n後書き\n")
        write(os.path.join(self.notes, "やること.md"),
              "---\n種類: 計画\n---\n# やること\n\n## 今の仕事と次\n- 作っている(AI)\n\n## ユーザーの番\n- 答える\n")
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
        self.assertIn("版: main 1.2.3 / ここ 1.2.3", text)
        self.assertIn("10-18 code-map: 地図を作った", text)
        self.assertIn("## やること(やること.md", text)
        self.assertIn("- 作っている(AI)", text)
        self.assertIn("- 答える", text)
        self.assertNotIn("種類: 計画", text)
        self.assertNotIn("仮決め", text)
        self.assertIn("wt-friend [claude/friend] +1・未コミット 1 友人の口を直す", text)
        self.assertIn("重なる: src/friendapp/api.py・src/friendapp/server.py", text)
        self.assertIn("- 仕様: 今の道具の仕様/友人まわり.md", text)
        self.assertNotIn("案件と確かめる.md", text)

    def test_tidy_moves_old_weeks_and_done_drafts(self):
        arc = os.path.join(self.tmp.name, "archive")
        env = mock.patch.dict(os.environ, {"YTT_NOTES_ARCHIVE": arc})
        env.start()
        self.addCleanup(env.stop)
        wl = os.path.join(self.notes, "docs", "worklog")
        write(os.path.join(wl, "2026-10-12週", "2026-10-16-left.md"),
              "---\nまとめ: 残り\n---\n# 前\n- 本物ではまだ確かめていない物: 友人の PC で見る\n- ユーザーがすること: なし\n")
        write(os.path.join(wl, "2026-10-12週.md"), "# 週\n")
        write(os.path.join(wl, "2026-10-19週", "2026-10-19-now.md"), "---\nまとめ: 今週\n---\n# 今\n")
        write(os.path.join(wl, "README.md"), "# 記録\n\n## 週のファイル(新しい週が上)\n- [2026-10-19週](2026-10-19週.md)(10-19〜)\n"
                                              "- [2026-10-12週](2026-10-12週.md)(10-12〜)\n")
        write(os.path.join(self.notes, "途中", "済んだ調べ.md"), "状態: 済み\n# 調べ\n")
        write(os.path.join(self.notes, "途中", "続く調べ.md"), "終わり: 2026-12-01\n# 続く\n")
        write(os.path.join(self.notes, "途中", "終わりの無い案.md"), "# 案\n")
        write(os.path.join(self.notes, "置き場の外.md"), "x\n")
        lines = "\n".join(ss.tidy(self.notes, datetime.date(2026, 10, 20), with_links=False))
        self.assertIn("前の週を控えへ移した: 2026-10-12週。済んでいない行 1", lines)
        self.assertIn("2026-10-12週/2026-10-16-left.md 本物ではまだ確かめていない物: 友人の PC で見る", lines)
        self.assertTrue(os.path.isfile(os.path.join(arc, "docs", "worklog", "2026-10-12週", "2026-10-16-left.md")))
        self.assertTrue(os.path.isfile(os.path.join(arc, "docs", "worklog", "2026-10-12週.md")))
        self.assertFalse(os.path.exists(os.path.join(wl, "2026-10-12週")))
        self.assertTrue(os.path.isfile(os.path.join(wl, "2026-10-19週", "2026-10-19-now.md")))   # 今週は残す
        with open(os.path.join(wl, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("2026-10-19週", readme)
        self.assertNotIn("2026-10-12週", readme)
        self.assertTrue(os.path.isfile(os.path.join(arc, "途中", "済んだ調べ.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.notes, "途中", "続く調べ.md")))
        self.assertIn("「終わり:」の無い物: 途中/終わりの無い案.md", lines)
        self.assertIn("決まった置き場の外: shared・置き場の外.md", lines)
        self.assertEqual(ss.tidy(self.notes, datetime.date(2026, 10, 20), with_links=False)[1:2],
                         ["- 途中/ に「終わり:」の無い物: 途中/終わりの無い案.md(まとめ役が片付ける)"])   # 2 回目は移す物が無い

    def test_brief_uses_template_and_marks_overlap(self):
        text = ss.brief("friendapp", "友人の口を足す", self.repo, self.notes)
        self.assertTrue(text.startswith("Task:\n友人の口を足す\n"))
        self.assertIn("**決まり**\n- 日本語で。", text)
        self.assertNotIn("後書き", text)
        self.assertIn("claude/friend — 友人の口を直す:重なる src/friendapp/api.py・src/friendapp/server.py", text)


if __name__ == "__main__":
    unittest.main()
