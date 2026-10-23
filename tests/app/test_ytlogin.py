"""ユーザーの PC の YouTube のログイン(src/app/ytlogin.py)。本物の YouTube・本物の cookie・本物の窓は使わない(偽の cookie と偽の起動)。リポジトリ直下で:
    python -m unittest tests/app/test_ytlogin.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))
from app import ytlogin as Y  # noqa: E402
from ytt import tools as T, ytcookies as C  # noqa: E402

FAKE = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tLOGIN_INFO\tfake\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSAPISID\tfake\n"


class FakeProc:
    def __init__(self, cmd, **kw):
        self.cmd, self.kw, self.returncode = cmd, kw, None

    def poll(self):
        return self.returncode


class YtLoginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = os.path.join(self.tmp.name, "app")
        self.repo = os.path.join(self.tmp.name, "repo")
        self.env = {}
        self.procs = []

    def make(self, with_exe=True):
        if with_exe:
            exe = os.path.join(self.repo, Y.EXE_REL)
            os.makedirs(os.path.dirname(exe), exist_ok=True)
            open(exe, "wb").close()
        Y.apply_env(self.app, self.env)
        return Y.YtLogin(self.app, self.repo, env=self.env, popen=lambda cmd, **kw: self.procs.append(FakeProc(cmd, **kw)) or self.procs[-1])

    def test_apply_env_keeps_given_path(self):
        """入口の起動: 空なら作業データの secrets の下・外から入れた物はそのまま"""
        env = {}
        self.assertEqual(Y.apply_env(self.app, env), os.path.join(self.app, "secrets", "youtube-cookies.txt"))
        env = {T.COOKIES_ENV: "X:\\given.txt"}
        self.assertEqual(Y.apply_env(self.app, env), "X:\\given.txt")

    def test_not_logged_in_passes_nothing_to_ytdlp(self):
        """ログインしていない = cookie のファイルが無い = yt-dlp に何も足さない(今までどおり)"""
        y = self.make()
        st = y.status()
        self.assertEqual((st["state"], st["at"], st["running"], st["canLogin"]), ("none", 0, False, True))
        self.assertEqual(T.ytdlp_auth_args(self.env), [])

    def test_login_opens_window_then_ok_and_ytdlp_gets_copy(self):
        """[YouTube にログイン]: 小窓(FriendApp.exe --yt-login <置き場所>)を 1 つだけ起こす。書かれたら ok・yt-dlp には写しを渡す・ログアウトで消える"""
        y = self.make()
        st = y.login()
        self.assertTrue(st["running"])
        y.login()   # 開いている間は 2 つ目を起こさない
        self.assertEqual(len(self.procs), 1)
        cmd = self.procs[0].cmd
        self.assertEqual(cmd[1:], [Y.LOGIN_ARG, self.app])
        src = self.env[T.COOKIES_ENV]
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w", encoding="utf-8") as f:   # 小窓が書いた(偽の cookie)
            f.write(FAKE)
        self.procs[0].returncode = 0
        st = y.status()
        self.assertEqual((st["state"], st["running"], st["message"]), ("ok", False, "YouTube にログインしました"))
        self.assertGreater(st["at"], 0)
        args = T.ytdlp_auth_args(self.env)
        self.assertEqual(args[0], "--cookies")
        self.assertTrue(args[1].startswith(os.path.join(os.path.dirname(src), C.RUN)))   # 写しを渡す
        st = y.logout()
        self.assertEqual((st["state"], st["message"]), ("none", "ログアウトしました"))
        self.assertFalse(os.path.exists(src))
        self.assertEqual(os.listdir(os.path.join(os.path.dirname(src), C.RUN)), [])   # 写しも消す
        self.assertEqual(T.ytdlp_auth_args(self.env), [])

    def test_cancelled_login(self):
        y = self.make()
        y.login()
        self.procs[0].returncode = 1
        st = y.status()
        self.assertEqual((st["state"], st["message"]), ("none", "ログインを途中でやめました"))

    def test_expired_when_login_cookie_lost(self):
        """yt-dlp の書き戻しでログインの cookie が消えた(ytcookies の lostAt)= expired(友人のアプリと同じ言い方の「切れた可能性」)"""
        y = self.make()
        src = self.env[T.COOKIES_ENV]
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w", encoding="utf-8") as f:
            f.write(FAKE)
        at = C.login_at(src)
        C._write_state(src, dict(C.read_state(src), lostAt=at + 1000))
        self.assertEqual(y.status()["state"], "expired")

    def test_no_exe(self):
        y = self.make(with_exe=False)
        st = y.status()
        self.assertFalse(st["canLogin"])
        self.assertIn("build.bat", st["why"])
        with self.assertRaises(ValueError):
            y.login()


if __name__ == "__main__":
    unittest.main()
