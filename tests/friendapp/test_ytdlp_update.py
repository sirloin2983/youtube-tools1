"""src/friendapp/ytdlp_update.py(yt-dlp をいつも新しく)のテスト。ネットと yt-dlp は偽物(偽の http・偽の run)。
リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_ytdlp_update.py"""
import hashlib
import json
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from friendapp import setup as S, ytdlp_update as U  # noqa: E402

NEW = b"fake-yt-dlp-new" * 100


class Fake:
    """偽のネット(release・SHA2-256SUMS・exe)と偽の yt-dlp(ファイルの中身で版と問い合わせの結果を決める)"""
    def __init__(self, tag="2026.10.20", body=NEW, sha=None, probe_new=True, probe_old=True):
        self.tag, self.body, self.sha = tag, body, sha or hashlib.sha256(body).hexdigest()
        self.probe = {"new": probe_new, "old": probe_old}
        self.calls = []

    def http(self, url, max_bytes):
        self.calls.append(url)
        if url == U.API:
            return json.dumps({"tag_name": self.tag}).encode()
        if url.endswith("SHA2-256SUMS"):
            return ("%s  yt-dlp.exe\n%s  yt-dlp_linux\n" % (self.sha, "0" * 64)).encode()
        return self.body

    def run(self, cmd, timeout=60):
        with open(cmd[0], "rb") as f:
            who = "new" if f.read() == NEW else "old"
        if cmd[1] == "--version":
            return 0, (self.tag if who == "new" else "2026.08.19"), None
        return (0, "jNQXAC9IVRw", None) if self.probe[who] else (1, "ERROR: Sign in to confirm you're not a bot", None)


class UpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = testkit.tempdir(self, "ytdlp-update-")
        self.fold = os.path.join(tmp, "tools", "yt-dlp")
        self.friend = os.path.join(tmp, "friend")
        os.makedirs(self.fold)
        self.exe = os.path.join(self.fold, "yt-dlp.exe")
        with open(self.exe, "wb") as f:
            f.write(b"fake-yt-dlp-old")
        self.logs = []

    def update(self, fake, **kw):
        return U.update(self.exe, self.friend, http=fake.http, run=fake.run, log=self.logs.append, **kw)

    def body(self):
        with open(self.exe, "rb") as f:
            return f.read()

    def test_replaces_and_marks_for_setup(self):
        rec = self.update(Fake())
        self.assertEqual((self.body(), rec["version"], rec["prev"]), (NEW, "2026.10.20", "2026.08.19"))
        self.assertFalse(os.path.exists(self.exe + ".new"))
        home = os.path.dirname(os.path.dirname(self.fold))
        it = {"name": "yt-dlp", "file": "yt-dlp.exe", "unzip": None, "size": 17840399, "maxBytes": 0, "base": "app", "dest": "tools/yt-dlp"}
        self.assertTrue(S.is_done(it, "", home))   # 表の大きさと違っても取り替えた印があれば初回の準備は取り直さない
        with open(self.exe, "ab") as f:
            f.write(b"x")
        self.assertFalse(S.is_done(it, "", home))

    def test_once_a_day(self):
        fake = Fake()
        self.update(fake)
        n = len(fake.calls)
        self.update(fake)
        self.assertEqual(len(fake.calls), n)

    def test_bad_sha_keeps_old(self):
        rec = self.update(Fake(sha="1" * 64))
        self.assertEqual(self.body(), b"fake-yt-dlp-old")
        self.assertIn("SHA-256", rec["error"])

    def test_new_fails_only_new_keeps_old(self):
        rec = self.update(Fake(probe_new=False))
        self.assertEqual(self.body(), b"fake-yt-dlp-old")
        self.assertIn("新しい物だけ", rec["error"])

    def test_both_fail_probe_still_replaces(self):
        self.update(Fake(probe_new=False, probe_old=False))   # bot 判定など = 新しい版のせいではない
        self.assertEqual(self.body(), NEW)

    def test_same_version_does_nothing(self):
        fake = Fake(tag="2026.08.19")
        self.update(fake)
        self.assertEqual(self.body(), b"fake-yt-dlp-old")
        self.assertFalse(any(c.endswith("/yt-dlp.exe") for c in fake.calls))

    def test_maybe_start_only_app_tools(self):
        env = {"YTT_YTDLP": self.exe}
        other = os.path.join(os.path.dirname(self.fold), "..", "elsewhere")
        self.assertFalse(U.maybe_start(env, self.friend, other))   # PATH の yt-dlp(winget など)は触らない
        self.assertFalse(U.maybe_start(env, self.friend, os.path.dirname(self.fold), maker=True))   # ユーザーの PC
        self.assertFalse(U.maybe_start(dict(env, **{U.SWITCH_ENV: "0"}), self.friend, os.path.dirname(self.fold)))


if __name__ == "__main__":
    unittest.main()
