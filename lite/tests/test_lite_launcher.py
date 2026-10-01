# -*- coding: utf-8 -*-
"""友人用 文字起こし簡易版の起動と自動更新(lite/lite_start.py・lite/lite_update.py)のテスト。ネットワーク・git は偽物に差し替える。
    python -m unittest lite/tests/test_lite_launcher.py"""
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

LITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(LITE)
sys.path.insert(0, LITE)
import lite_update as U  # noqa: E402
import lite_start as ST  # noqa: E402


def done(code=0, out=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr="")


class FakeGit:
    """git -C ROOT <args> の偽物。answers: 最初の引数 → (終了コード, 出力)"""

    def __init__(self, **answers):
        self.answers, self.calls = answers, []

    def __call__(self, cmd, **kw):
        args = cmd[3:]
        self.calls.append(args)
        key = args[0] if args[0] != "rev-parse" else "rev-parse:" + args[1]
        code, out = self.answers.get(key.replace("-", "_").replace(":", "_").replace("/", "_"), (0, ""))
        return done(code, out)


class Remote(unittest.TestCase):
    def test_norm_remote(self):
        for u in ("https://github.com/sirloin2983/youtube-tools1", "https://github.com/sirloin2983/youtube-tools1.git",
                  "git@github.com:sirloin2983/youtube-tools1.git", "https://github.com/Sirloin2983/youtube-tools1/"):
            self.assertEqual(U.norm_remote(u), U.norm_remote(U.REPO_URL), u)
        self.assertNotEqual(U.norm_remote("https://github.com/evil/youtube-tools1"), U.norm_remote(U.REPO_URL))

    def test_only_fixed_hosts(self):
        with self.assertRaises(ValueError):
            U._get("https://evil.example/x.zip", 10)
        with self.assertRaises(ValueError):
            U._get("http://api.github.com/repos/x", 10)


class Git(unittest.TestCase):
    def test_other_origin_is_not_updated(self):
        g = FakeGit(remote=(0, "https://github.com/someone/fork.git\n"))
        self.assertEqual(U.update_git(run=g)[0], "skip")
        self.assertFalse(any(c[0] in ("fetch", "merge") for c in g.calls))

    def test_dirty_tree_is_not_updated(self):
        g = FakeGit(remote=(0, U.REPO_URL + ".git\n"), status=(0, " M editor/app.js\n"))
        state, msg = U.update_git(run=g)
        self.assertEqual(state, "skip")
        self.assertIn("変更", msg)
        self.assertFalse(any(c[0] in ("fetch", "merge") for c in g.calls))

    def test_fast_forward(self):
        g = FakeGit(remote=(0, U.REPO_URL + "\n"), status=(0, ""), rev_parse_HEAD=(0, "a" * 40), rev_parse_origin_main=(0, "b" * 40))
        self.assertEqual(U.update_git(run=g)[0], "updated")
        self.assertIn(["merge", "--ff-only", "--quiet", "origin/main"], g.calls)

    def test_latest_and_offline(self):
        g = FakeGit(remote=(0, U.REPO_URL), rev_parse_HEAD=(0, "a" * 40), rev_parse_origin_main=(0, "a" * 40))
        self.assertEqual(U.update_git(run=g)[0], "latest")
        g = FakeGit(remote=(0, U.REPO_URL), fetch=(128, ""))
        self.assertEqual(U.update_git(run=g)[0], "skip")


class Zip(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.root = os.path.join(self.d, "root")
        os.makedirs(os.path.join(self.root, "lite", ".venv"))
        with open(os.path.join(self.root, "lite", ".venv", "keep.txt"), "w") as f:
            f.write("mine")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def make(self, names, top="youtube-tools1-" + "a" * 40):
        p = os.path.join(self.d, "src.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(top + "/", b"")
            for n in names:
                if isinstance(n, zipfile.ZipInfo):
                    z.writestr(n, b"x")
                else:
                    z.writestr(n if n.startswith(top) or n.startswith(("/", "..", "C:", "other-top")) else top + "/" + n, b"new")
        return p

    def test_apply_overwrites_code_but_not_protected(self):
        p = self.make(["editor/lite.js", "lite/.venv/keep.txt", "lite/.installed.json", ".git/config", "README.txt"])
        n = U.apply_zip(p, self.root)
        self.assertEqual(n, 2)
        with open(os.path.join(self.root, "editor", "lite.js"), "rb") as f:
            self.assertEqual(f.read(), b"new")
        with open(os.path.join(self.root, "lite", ".venv", "keep.txt")) as f:
            self.assertEqual(f.read(), "mine")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".git")))

    def test_rejects_evil_names(self):
        top = "youtube-tools1-" + "a" * 40
        for evil in ("../evil.txt", top + "/../evil.txt", "/abs.txt", "C:/x.txt", "other-top/x.txt"):
            p = self.make(["ok.txt", evil])
            with self.assertRaises(ValueError, msg=evil):
                U.apply_zip(p, self.root)
            self.assertFalse(os.path.exists(os.path.join(self.d, "evil.txt")))
            self.assertFalse(os.path.exists(os.path.join(self.root, "ok.txt")))   # 1つでも危なければ何も書かない
        info = zipfile.ZipInfo(top + "/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            U.apply_zip(self.make([info]), self.root)

    def test_update_zip_flow(self):
        sha = "c" * 40
        zbytes = io.BytesIO()
        with zipfile.ZipFile(zbytes, "w") as z:
            z.writestr("youtube-tools1-%s/editor/x.txt" % sha, b"hello")

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        urls = []

        def opener(req, timeout=None):
            urls.append(req.full_url)
            if req.full_url == U.API_URL:
                return Resp(json.dumps({"sha": sha}).encode())
            return Resp(zbytes.getvalue())
        with mock.patch.object(U, "ROOT", self.root), mock.patch.object(U, "STATE", os.path.join(self.root, "lite", ".installed.json")):   # apply_zip は呼ぶときに ROOT を読む
            self.assertEqual(U.update_zip(opener)[0], "updated")
            self.assertEqual(urls, [U.API_URL, U.ZIP_URL % (U.REPO, sha)])   # 調べたコミットの zip だけ
            self.assertEqual(U.update_zip(opener)[0], "latest")
        with open(os.path.join(self.root, "editor", "x.txt"), "rb") as f:
            self.assertEqual(f.read(), b"hello")

    def test_update_zip_offline_does_not_fail(self):
        def opener(req, timeout=None):
            raise OSError("no network")
        self.assertEqual(U.update_zip(opener)[0], "skip")


class Start(unittest.TestCase):
    def test_bat_is_ascii_and_exits_on_same_line(self):
        with open(os.path.join(LITE, "start.bat"), "rb") as f:
            data = f.read()
        data.decode("ascii")   # 日本語を入れない(cmd が文字化けする)
        line = [l for l in data.decode().splitlines() if "lite_start.py" in l and not l.startswith("rem")][0]
        self.assertTrue(line.rstrip().endswith("& exit /b"), line)   # 更新で書き換わっても続きを読まない
        for p in ("requirements-lite.txt", "requirements-lite-gpu.txt"):
            with open(os.path.join(REPO, "setup", p), "rb") as f:
                f.read().decode("ascii")

    def test_launch_args(self):
        self.assertEqual(ST.LAUNCH_ARGS, ["--only", "transcribe", "--open-path", "/transcribe/lite.html", "--app-window"])
        sys.path.insert(0, os.path.join(REPO, "home"))
        import launch
        a = launch.parse_args(ST.LAUNCH_ARGS)
        self.assertEqual((a.only, a.open_path, a.app_window), (["transcribe"], "/transcribe/lite.html", True))

    def test_install_skips_when_same(self):
        tmp = tempfile.mkdtemp()
        try:
            calls = []
            with mock.patch.object(ST, "marker_path", lambda: os.path.join(tmp, "m")):
                self.assertTrue(ST.install(False, run=lambda c: calls.append(c) or done(0), uv="uv"))
                self.assertTrue(ST.install(False, run=lambda c: calls.append(c) or done(0), uv="uv"))
                self.assertEqual(len(calls), 1)
                self.assertIn(ST.REQ, calls[0])
                self.assertNotIn(ST.REQ_GPU, calls[0])
                self.assertTrue(ST.install(True, run=lambda c: calls.append(c) or done(0), uv="uv"))   # GPU のときは足す
                self.assertIn(ST.REQ_GPU, calls[-1])
                os.unlink(os.path.join(tmp, "m"))
                self.assertFalse(ST.install(False, run=lambda c: done(1), uv="uv"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ffmpeg_missing_asks(self):
        asked = []
        ok = ST.ensure_ffmpeg(which=lambda n: None, run=lambda c: done(1), ask_fn=lambda q: asked.append(q) or False)
        self.assertFalse(ok)
        self.assertTrue(ST.ensure_ffmpeg(which=lambda n: "C:/x/" + n, run=lambda c: done(0), ask_fn=lambda q: False))


if __name__ == "__main__":
    unittest.main()
