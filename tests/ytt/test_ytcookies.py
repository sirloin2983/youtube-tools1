"""src/ytt/ytcookies.py(yt-dlp が書き戻した cookie を元へ戻す)のテスト。偽の cookie だけ(値は fake-*)。
リポジトリ直下で: py -3.12 -m unittest tests/ytt/test_ytcookies.py"""
import os
import sys
import time
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from ytt import tools, ytcookies as C  # noqa: E402

FAR = 4102444800   # 2100 年


def line(name, value, exp=FAR, domain=".youtube.com", http_only=False):
    return ("#HttpOnly_" if http_only else "") + "\t".join((domain, "TRUE", "/", "TRUE", str(exp), name, value))


def text(*lines):
    return "# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n"


LOGIN = [line("SID", "fake-sid"), line("SAPISID", "fake-sap"), line("__Secure-1PSID", "fake-p1", http_only=True)]


class MergeBackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytcookies-")
        self.src = os.path.join(self.tmp, "secrets", "youtube-cookies.txt")
        os.makedirs(os.path.dirname(self.src))
        self.write(self.src, text(*LOGIN, line("SIDCC", "fake-old", exp=FAR - 100)))
        self.env = {tools.COOKIES_ENV: self.src}

    def write(self, p, s, mt=None):
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
        if mt is not None:
            os.utime(p, (mt, mt))

    def read(self, p):
        with open(p, encoding="utf-8") as f:
            return f.read()

    def copy(self, body, age=10):
        """yt-dlp を偽る: 写しをもらって、書き戻した(作ってから age 秒後に書いた・今は 3 秒止まっている)"""
        dst = tools.ytdlp_auth_args(dict(self.env, **{C.SWITCH_ENV: "0"}))[1]   # 写すだけ(ほかの写しはまだ戻さない)
        t = time.time()
        os.utime(dst, (t - age, t - age))
        newname = os.path.join(os.path.dirname(dst), "%d%s" % (int((t - age) * 1000), os.path.basename(dst)[13:]))
        os.replace(dst, newname)
        self.write(newname, body, mt=t - 3)
        return newname

    def test_rotated_value_goes_back_and_login_time_stays(self):
        at = tools.ytdlp_login_at(self.env)
        p = self.copy(text(*LOGIN, line("SIDCC", "fake-new"), line("VISITOR_INFO1_LIVE", "fake-v")))
        tools.ytdlp_auth_args(self.env)   # 次に呼ぶ前に戻す
        s = self.read(self.src)
        self.assertIn("fake-new", s)
        self.assertNotIn("fake-old", s)
        self.assertIn("VISITOR_INFO1_LIVE", s)
        self.assertIn("#HttpOnly_.youtube.com", s)   # 行の形はそのまま
        self.assertFalse(os.path.exists(p))   # 戻した写しは消す
        self.assertEqual(tools.ytdlp_login_at(self.env), at)   # 書き替えてもログインの時刻のまま
        f = C.facts(self.src)
        self.assertEqual((f["merged"], f["loginAt"]), (1, at))
        self.assertNotIn("fake", repr(f))   # 診断に値は入らない

    def test_login_cookie_loss_is_not_written_back(self):
        before = self.read(self.src)
        self.copy(text(line("SIDCC", "fake-new"), line("SAPISID", "fake-sap")))   # SID・1PSID が消えた = ログインが切れた
        tools.ytdlp_auth_args(self.env)
        self.assertEqual(self.read(self.src), before)
        f = C.facts(self.src)
        self.assertEqual(f["rejectedWhy"], "lost")
        self.assertGreater(f["lostAt"], 0)

    def test_broken_copy_is_dropped(self):
        before = self.read(self.src)
        p = self.copy("garbage\twithout\tfields\n")
        tools.ytdlp_auth_args(self.env)
        self.assertEqual(self.read(self.src), before)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(C.facts(self.src)["rejectedWhy"], "broken")

    def test_copy_from_before_relogin_is_stale(self):
        p = self.copy(text(*LOGIN, line("SIDCC", "fake-new")))
        t = time.time() + 5
        self.write(self.src, text(*[line(n, "fake-relogin") for n in ("SID", "SAPISID", "__Secure-1PSID")]), mt=t)   # ログインし直した
        C.merge_back(self.src, now=t + 10)
        self.assertNotIn("fake-new", self.read(self.src))
        self.assertFalse(os.path.exists(p))
        s = C.read_state(self.src)
        self.assertEqual((s["rejectedWhy"], C.login_at(self.src)), ("stale", int(t * 1000)))

    def test_running_copy_is_left_alone_and_lock_skips(self):
        dst = tools.ytdlp_auth_args(self.env)[1]   # まだ書き戻していない
        C.merge_back(self.src)
        self.assertTrue(os.path.exists(dst))
        p = self.copy(text(*LOGIN, line("SIDCC", "fake-new")))
        lock = C._fsio.try_lock(os.path.join(os.path.dirname(dst), C.LOCK))   # ほかのプロセスが戻している
        try:
            self.assertTrue(C.merge_back(self.src)["busy"])
            self.assertTrue(os.path.exists(p))
        finally:
            C._fsio.unlock(lock)
        self.assertEqual(C.merge_back(self.src)["merged"], 1)

    def test_switch_off_keeps_old_behavior(self):
        p = self.copy(text(*LOGIN, line("SIDCC", "fake-new")))
        self.assertEqual(C.merge_back(self.src, env={C.SWITCH_ENV: "0"})["merged"], 0)
        self.assertTrue(os.path.exists(p))
        self.assertNotIn("fake-new", self.read(self.src))

    def test_older_expiry_from_older_base_does_not_win(self):
        a = self.copy(text(*LOGIN, line("SIDCC", "fake-a", exp=FAR)))
        b = self.copy(text(*LOGIN, line("SIDCC", "fake-b", exp=FAR - 50)), age=20)   # 同じ元から・期限が前
        os.utime(b, (time.time() - 5, time.time() - 5))   # b を先に戻す
        C.merge_back(self.src)
        s = self.read(self.src)
        self.assertIn("fake-a", s)   # a は b の後に戻る・期限が後なので勝つ
        self.assertFalse(os.path.exists(a) or os.path.exists(b))


if __name__ == "__main__":
    unittest.main()
