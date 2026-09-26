# -*- coding: utf-8 -*-
"""tools/push_helper.py(push.bat の補助: ファイルの削除・コミット前の検査)のテスト。一時フォルダの git リポジトリだけを使う。
実行(リポジトリ直下): python -m unittest tools/test_push_helper.py"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # サーバーは動かさないが、全テストの決まりに合わせる(ytt_core のテストが検査)
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import push_helper as P  # noqa: E402

FAKE_GOOGLE = "AIza" + "B" * 35          # 本物の形だが偽物(このファイルは検査の対象外)
FAKE_GH = "ghp_" + "a1" * 18


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.run_git("init", "-q")
        self.write("tools/push_helper.py", "x")
        self.write("clip-studio/start.bat", "@echo off")
        self.write("clip-studio/serve.py", "print(1)")
        self.write("keep.txt", "keep")
        self.run_git("add", "-A")
        self.run_git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
        self.p = mock.patch.object(P, "ROOT", self.root)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def run_git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def write(self, rel, text):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p


class TestRemovals(Repo):
    def removals(self, text):
        return self.write("tools/removals.txt", text)

    def test_removes_only_tracked_listed_files(self):
        self.write("untracked.txt", "作業データかもしれない")
        os.makedirs(os.path.join(self.root, "somedir"))
        path = self.removals("# 単独起動をやめる\nclip-studio/start.bat   # 起動ファイル\nuntracked.txt\nsomedir\nno/such/file.txt\n")
        logs = []
        done = P.apply_removals(path, log=logs.append)
        self.assertEqual(done, ["clip-studio/start.bat"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "clip-studio", "start.bat")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "untracked.txt")))       # git が管理していないものは消さない
        self.assertTrue(os.path.isdir(os.path.join(self.root, "somedir")))               # フォルダは消さない
        self.assertTrue(os.path.exists(os.path.join(self.root, "clip-studio", "serve.py")))
        self.assertTrue(any("管理していない" in x for x in logs) and any("フォルダ" in x for x in logs))
        staged = subprocess.run(["git", "diff", "--cached", "--name-status"], cwd=self.root, stdout=subprocess.PIPE).stdout.decode()
        self.assertIn("D\tclip-studio/start.bat", staged)                                # 削除がコミットに入る
        self.assertEqual(P.apply_removals(path, log=logs.append), [])                     # 2回目は何もしない

    def test_bad_lines_stop_everything(self):
        for bad in ("../outside.txt", "/etc/passwd", "C:\\Users\\x\\a.txt", "clip-studio/*.bat", "clip-studio//start.bat", "./keep.txt"):
            with self.subTest(bad=bad):
                path = self.removals("keep.txt\n" + bad + "\n")
                with self.assertRaises(ValueError):
                    P.apply_removals(path, log=lambda m: None)
                self.assertTrue(os.path.exists(os.path.join(self.root, "keep.txt")))    # 1行でも正しくなければ何も消さない

    def test_missing_list_is_noop(self):
        self.assertEqual(P.apply_removals(os.path.join(self.root, "none.txt"), log=lambda m: None), [])


class TestCheck(Repo):
    def test_problems(self):
        cases = {
            "app/config.json": b"{}", "clip-studio/data.json": b"{}", "app/cases.json": b"{}", "transcribe-tool/settings.json": b"{}",
            "x/feedback.jsonl": b"", "app/logs/launcher.log": b"", "app/logs/client-errors.jsonl": b"", "transcribe-tool/transcripts/abc.json": b"{}",
            "app/browser-profile/Default/History": b"",
            "clip-studio/cache/x.txt": b"", "a/clip.mp4": b"", "notes.md": FAKE_GOOGLE.encode(), "run.py": ("t='%s'" % FAKE_GH).encode(),
            "k.txt": b"-----BEGIN RSA PRIVATE KEY-----", "big.txt": b"x" * (P.MAX_BYTES + 1),
        }
        for path, data in cases.items():
            with self.subTest(path=path):
                self.assertTrue(P.problems_for(path, data), path)
        for path, data in {"clip-studio/serve.py": b"API_KEY_ENV = 'YOUTUBE_API_KEY'", "docs/data-location.md": b"config.json \xe3\x81\xae\xe8\xaa\xac\xe6\x98\x8e",
                           "cut2resolve/selection.example.json": b"{}", "transcribe-tool/hololive-roster.json": b"[]",
                           "tools/push_helper.py": FAKE_GOOGLE.encode(), "docs/pipeline.md": b"sk-short"}.items():
            with self.subTest(ok=path):
                self.assertEqual(P.problems_for(path, data), [], path)

    def test_staged_files_end_to_end(self):
        self.write("clip-studio/serve.py", "print(2)")
        self.write("app/config.json", '{"key": "%s"}' % FAKE_GOOGLE)
        self.run_git("add", "-A")
        logs = []
        self.assertEqual(P.check(log=logs.append), 1)
        self.assertTrue(any("app/config.json" in x and "秘密情報" in x for x in logs))
        self.run_git("reset", "-q")
        self.run_git("add", "clip-studio/serve.py")
        self.assertEqual(P.check(log=logs.append), 0)


class TestPushBat(unittest.TestCase):
    def test_order_in_push_bat(self):
        with open(os.path.join(os.path.dirname(HERE), "push.bat"), encoding="ascii") as f:
            s = f.read()   # ASCII だけ(cmd.exe が UTF-8 の長い行を読み違えるため)
        a, b, c = s.index("push_helper.py removals"), s.index("git add -A"), s.index("push_helper.py check")
        self.assertTrue(a < b < c, "削除 → git add → 検査 の順")
        self.assertIn("git reset -q", s[c:c + 400])   # 検査で止まったらコミットしない(git add を取り消す)


if __name__ == "__main__":
    unittest.main()
