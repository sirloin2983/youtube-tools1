import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import land  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def g(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    if r.returncode:
        raise AssertionError(r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8", "replace")


def put(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def get(root, rel):
    with open(os.path.join(root, *rel.split("/")), "rb") as f:
        return f.read().decode("utf-8")


class LandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.main)
        g(self.main, "init", "-q", "-b", "main")
        g(self.main, "config", "user.email", "t@example.com")
        g(self.main, "config", "user.name", "t")
        g(self.main, "config", "core.autocrlf", "false")
        put(self.main, "src/ytt/version.py", '"""版"""\r\nVERSION = "0.99.18"\r\n')
        put(self.main, "README.txt", "=====\r\n  ツール  v0.99.18(仮)  はじめに\r\n=====\r\n本文\r\n")
        put(self.main, "src/a.py", "a = 1\n")
        g(self.main, "add", "-A")
        g(self.main, "commit", "-q", "-m", "init")
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def branch(self, name, files):
        wt = os.path.join(self.tmp.name, name)
        g(self.main, "worktree", "add", "-q", "-b", name, wt)
        for rel, text in files.items():
            put(wt, rel, text)
        g(wt, "add", "-A")
        g(wt, "commit", "-q", "-m", "work " + name)
        return wt

    def land(self, branch, wt, **kw):
        return land.land(branch, cwd=wt, wait=5, log=self.logs.append, **kw)

    def test_two_branches_get_different_versions(self):
        a = self.branch("a", {"src/a.py": "a = 2\n"})
        b = self.branch("b", {"src/b.py": "b = 1\n"})
        self.assertEqual(self.land("a", a), "0.99.19")
        self.assertEqual(self.land("b", b), "0.99.20")
        self.assertIn('VERSION = "0.99.20"\r\n', get(self.main, "src/ytt/version.py"))   # 改行はそのまま
        self.assertIn("  ツール  v0.99.20(仮)  はじめに\r\n", get(self.main, "README.txt"))
        log = g(self.main, "log", "--format=%s", "-5")
        self.assertIn("[Claude] 版を 0.99.20 に(b を取り込んだ)", log)
        self.assertEqual(self.land("b", b), "0.99.20")   # もう入っている = 何もしない
        self.assertFalse(os.path.exists(os.path.join(g(self.main, "rev-parse", "--git-common-dir").strip(), land.LOCK_NAME)))

    def test_docs_or_tests_only_do_not_bump(self):
        a = self.branch("a", {"dev/tool.py": "x\n", "src/tests/test_x.py": "y\n"})
        self.assertEqual(self.land("a", a), "0.99.18")
        self.assertIn('"0.99.18"', get(self.main, "src/ytt/version.py"))

    def test_branch_that_bumped_itself_is_recounted_from_main(self):
        a = self.branch("a", {"src/a.py": "a = 3\n", "src/ytt/version.py": '"""版"""\r\nVERSION = "0.99.25"\r\n'})
        b = self.branch("b", {"src/b.py": "b = 1\n", "src/ytt/version.py": '"""版"""\r\nVERSION = "0.99.19"\r\n'})
        self.assertEqual(self.land("a", a), "0.99.19")
        self.assertEqual(self.land("b", b), "0.99.20")   # 版の行のぶつかりは main の側を取って数え直す
        self.assertIn('"0.99.20"', get(self.main, "src/ytt/version.py"))

    def test_minor_and_dirty_main(self):
        a = self.branch("a", {"src/a.py": "a = 4\n"})
        put(self.main, "src/a.py", "a = 9\n")   # main の作業フォルダに誰かの途中の変更
        with self.assertRaises(land.Stop):
            self.land("a", a, mode="minor")
        g(self.main, "checkout", "--", "src/a.py")
        self.assertEqual(self.land("a", a, mode="minor"), "0.100.0")

    def test_conflict_aborts(self):
        a = self.branch("a", {"src/a.py": "a = 5\n"})
        put(self.main, "src/a.py", "a = 6\n")
        g(self.main, "commit", "-qam", "main side")
        with self.assertRaises(land.Stop):
            self.land("a", a)
        self.assertEqual(g(self.main, "status", "--porcelain", "--untracked-files=no").strip(), "")

    def test_repair_bumps_forgotten(self):
        put(self.main, "src/a.py", "a = 7\n")
        g(self.main, "commit", "-qam", "direct")
        self.assertEqual(self.land(None, self.main), "0.99.19")

    def test_dead_lock_is_taken(self):
        a = self.branch("a", {"src/a.py": "a = 8\n"})
        common = os.path.join(self.main, ".git")
        with open(os.path.join(common, land.LOCK_NAME), "w", encoding="utf-8") as f:
            f.write('{"pid": 999999, "at": 0}')
        self.assertEqual(self.land("a", a), "0.99.19")


if __name__ == "__main__":
    unittest.main()
