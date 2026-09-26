# -*- coding: utf-8 -*-
"""段階7 のテスト: 窓で開く(app/appwindow.py)・画面のエラーの記録(app/clientlog.py)・入口の共通の API(api/ytt/…)。
    python -m unittest app/test_window.py -v

Edge は起動しない(起動のコマンドは偽の popen で受け取って確かめる)。取り込んだツールの画面からの api/ytt/… は app/test_mount.py。
"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import appwindow as W  # noqa: E402
import clientlog as C  # noqa: E402
import launch as L  # noqa: E402
from ytt_core import fsio  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class FakeSys:
    """偽の popen・ブラウザ・時計"""

    def __init__(self, exe=EDGE):
        self.exe, self.spawned, self.browsed, self.now = exe, [], [], 1000.0
        self.fail_spawn = False

    def popen(self, cmd, **kw):
        if self.fail_spawn:
            raise OSError("起動できない")
        self.spawned.append((cmd, kw))

    def browser_open(self, url):
        self.browsed.append(url)
        return True

    def find(self, env):
        return self.exe

    def clock(self):
        return self.now


def opener(tmp, fake):
    return W.Opener(tmp, fsio.atomic_write, popen=fake.popen, browser_open=fake.browser_open, find=fake.find, clock=fake.clock)


class TestFindEdge(unittest.TestCase):
    def test_env_override(self):
        self.assertEqual(W.find_edge({"YTT_APP_BROWSER": "/x/chrome"}, "win32", isfile=lambda p: p == "/x/chrome"), "/x/chrome")
        self.assertIsNone(W.find_edge({"YTT_APP_BROWSER": "/x/none"}, "win32", isfile=lambda p: False))   # 無い物は使わない(Edge に戻らない)

    def test_windows_candidates_and_registry(self):
        env = {"ProgramFiles(x86)": r"C:\PF86", "ProgramFiles": r"C:\PF", "LOCALAPPDATA": r"C:\U\AppData\Local"}
        want = os.path.join(r"C:\PF", W.EDGE_REL)
        self.assertEqual(W.find_edge(env, "win32", isfile=lambda p: p == want, reg=lambda: None), want)
        self.assertEqual(W.find_edge({}, "win32", isfile=lambda p: p == r"D:\edge.exe", reg=lambda: r"D:\edge.exe"), r"D:\edge.exe")
        self.assertIsNone(W.find_edge(env, "win32", isfile=lambda p: False, reg=lambda: None))

    def test_other_platforms(self):
        self.assertEqual(W.find_edge({}, "darwin", isfile=lambda p: p == W.MAC_EDGE), W.MAC_EDGE)
        self.assertEqual(W.find_edge({}, "linux", which=lambda n: "/usr/bin/" + n if n == "microsoft-edge" else None), "/usr/bin/microsoft-edge")
        self.assertIsNone(W.find_edge({}, "linux", which=lambda n: None))

    def test_command_has_no_debug_port(self):
        cmd = W.app_command(EDGE, "http://localhost:8700/", r"C:\data\app\browser-profile")
        self.assertEqual(cmd[:3], [EDGE, "--app=http://localhost:8700/", r"--user-data-dir=C:\data\app\browser-profile"])
        self.assertFalse(any("remote-debugging" in a for a in cmd))   # 開くと PC 上のどのプログラムでも窓を操作できる


class TestUrls(unittest.TestCase):
    P = ("/studio", "/transcribe", "/cut2resolve")

    def test_local_ok(self):
        for url, want in (("http://localhost:8700/", "http://localhost:8700/"),
                          ("http://127.0.0.1:8700/cases.html", "http://localhost:8700/cases.html"),
                          ("http://localhost:8700/studio/?url=https%3A%2F%2Fyoutu.be%2Fabc#x", "http://localhost:8700/studio/?url=https%3A%2F%2Fyoutu.be%2Fabc#x"),
                          ("http://localhost:8700/transcribe/?media=C%3A%5Cclip.mp4", "http://localhost:8700/transcribe/?media=C%3A%5Cclip.mp4"),
                          ("http://localhost:8801/", "http://localhost:8801/")):
            with self.subTest(url=url):
                self.assertEqual(W.local_url(url, 8700, [8801], self.P), want)

    def test_local_refused(self):
        bad = ("https://localhost:8700/", "http://evil.example:8700/", "http://localhost:9999/", "http://localhost:8700/api/shutdown",
               "http://localhost:8700/app/../api/x", "http://localhost:8700//studio/", "http://user:pw@localhost:8700/",
               'http://localhost:8700/" --remote-debugging-port=9222', "http://localhost:8700/ a", "http://localhost:8700/\nx",
               "javascript:alert(1)", "http://localhost:8801/api/state", "http://localhost:8700/" + "a" * 3000, "", None, 5,
               "http://localhost:99999/", "http://localhost:8700/studio")
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                W.local_url(url, 8700, [8801], self.P)

    def test_mount_prefixes_only_when_mounted(self):
        with self.assertRaises(ValueError):
            W.local_url("http://localhost:8700/studio/", 8700, [], ())

    def test_external(self):
        self.assertEqual(W.external_url("https://www.youtube.com/watch?v=abc&t=30s"), "https://www.youtube.com/watch?v=abc&t=30s")
        for url in ("javascript:alert(1)", "file:///C:/x", "data:text/html,x", "https://", "https://a b", "ftp://x", "https://u:p@x/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                W.external_url(url)


class TestOpener(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-win-")
        self.fake = FakeSys()
        self.o = opener(self.tmp, self.fake)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mode_setting(self):
        self.assertEqual(self.o.mode, "browser")   # 既定はブラウザのまま
        self.o.set_mode("app")
        self.assertEqual(W.Opener(self.tmp, fsio.atomic_write).mode, "app")   # ファイルに残る(次の起動で使う)
        with self.assertRaises(ValueError):
            self.o.set_mode("pywebview")
        with open(self.o.settings_path, "w", encoding="utf-8") as f:
            f.write("{壊れた")
        self.assertEqual(self.o.mode, "browser")   # 読めなければブラウザ

    def test_mode_keeps_other_keys(self):
        with open(self.o.settings_path, "w", encoding="utf-8") as f:
            json.dump({"other": 1}, f)
        self.o.set_mode("app")
        with open(self.o.settings_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"other": 1, "window": "app"})

    def test_open_start(self):
        self.assertEqual(self.o.open_start("http://localhost:8700/"), "browser")
        self.o.set_mode("app")
        self.assertEqual(self.o.open_start("http://localhost:8700/"), "app")
        cmd, kw = self.fake.spawned[-1]
        self.assertEqual(cmd, W.app_command(EDGE, "http://localhost:8700/", self.o.profile))
        self.assertTrue(os.path.isdir(self.o.profile))
        self.assertIsNone(kw.get("shell"))   # シェルを通さない
        self.fake.fail_spawn = True
        self.assertEqual(self.o.open_start("http://localhost:8700/"), "browser")   # 起動できなければブラウザ
        self.assertEqual(self.fake.browsed, ["http://localhost:8700/", "http://localhost:8700/"])

    def test_open_start_without_edge(self):
        fake = FakeSys(exe=None)
        o = opener(self.tmp, fake)
        o.set_mode("app")
        self.assertEqual(o.open_start("http://localhost:8700/"), "browser")
        self.assertEqual(o.status()["available"], False)
        with self.assertRaises(W.Unavailable):
            o.open_url("http://localhost:8700/", 8700)

    def test_rate_limit(self):
        for _ in range(W.RATE[0]):
            self.o.open_external("https://www.youtube.com/")
        with self.assertRaises(W.TooMany):
            self.o.open_url("http://localhost:8700/", 8700)
        self.fake.now += W.RATE[1] + 0.1
        self.o.open_url("http://localhost:8700/", 8700)
        self.assertEqual(self.fake.spawned[-1][0][1], "--app=http://localhost:8700/")


class TestClientLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-clog-")
        self.t = [1000.0]
        self.log = C.ClientLog(self.tmp, per_minute=3, max_bytes=400, clock=lambda: self.t[0])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lines(self, path=None):
        with open(path or self.log.path, encoding="utf-8") as f:
            return [json.loads(x) for x in f.read().splitlines()]

    def test_clean(self):
        e = C.clean({"kind": "evil", "message": "x" * 900, "stack": "s\n" * 2000, "line": 12, "col": True, "extra": "捨てる", "page": 5})
        self.assertEqual(e["kind"], "report")
        self.assertEqual(len(e["message"]), 500)
        self.assertEqual(len(e["stack"]), 2000)
        self.assertEqual(e["line"], 12)
        self.assertNotIn("col", e)
        self.assertNotIn("extra", e)
        self.assertNotIn("page", e)
        for bad in ({}, {"message": ""}, {"message": 3}, [], "x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                C.clean(bad)

    def test_one_line_per_entry_and_limit(self):
        self.log.max_bytes = 10 ** 6   # 回さない
        self.assertTrue(self.log.record("studio", {"kind": "error", "message": "a\n{\"tool\":\"fake\"}\r\nb"}, "0.7.0"))
        self.assertTrue(self.log.record("portal", {"message": "2"}))
        self.assertTrue(self.log.record("portal", {"message": "3"}))
        self.assertFalse(self.log.record("portal", {"message": "4"}))   # 1分に3件まで
        self.assertFalse(self.log.record("portal", {"message": "5"}))
        got = self.lines()
        self.assertEqual(len(got), 3)   # 改行を含むエラーの文でも1件は1行(偽の行を作れない)
        self.assertEqual((got[0]["tool"], got[0]["version"], got[0]["kind"]), ("studio", "0.7.0", "error"))
        self.assertIn("\n", got[0]["message"])
        self.t[0] += 61
        self.assertTrue(self.log.record("portal", {"message": "6"}))
        got = self.lines()
        self.assertEqual((got[3]["kind"], got[3]["count"]), ("dropped", 2))   # 書かなかった件数を残す
        self.assertEqual(got[4]["message"], "6")

    def test_rotation(self):
        for i in range(12):
            self.t[0] += 61
            self.log.record("portal", {"message": "m%d" % i + "x" * 60})
        self.assertTrue(os.path.exists(self.log.path + ".1"))
        self.assertLess(os.path.getsize(self.log.path), 400 + 200)


class TestPortalApi(unittest.TestCase):
    """入口の画面から: /api/ytt/…・/api/window・/api/status の window・/api/log?tool=client"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-winapi-")
        self.sup = L.Supervisor(self.tmp, only=["cut2resolve"], mounts=())
        self.srv, self.port = L.make_server(0, self.sup)
        self.fake = FakeSys()
        self.srv.window = opener(os.path.join(self.tmp, "app"), self.fake)
        self.sup.attach(self.srv)
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.host = "127.0.0.1:%d" % self.port

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, obj=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": self.host}
        if obj is not None or raw is not None:
            h.update({"Content-Type": "application/json", "X-YTT-Token": self.srv.token, "Origin": "http://" + self.host})
        h.update(headers or {})
        conn.request(method, path, body=raw if raw is not None else (json.dumps(obj).encode() if obj is not None else None), headers=h)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        try:
            return r.status, json.loads(body)
        except ValueError:
            return r.status, body

    def test_client_log(self):
        st, j = self.req("POST", "/api/ytt/client-log", {"kind": "error", "message": "boom", "source": "http://x/portal.js", "line": 3})
        self.assertEqual((st, j), (200, {"ok": True, "kept": True}))
        st, j = self.req("GET", "/api/log?tool=client&lines=5")
        self.assertEqual(st, 200)
        e = json.loads(j["lines"][-1])
        self.assertEqual((e["tool"], e["message"], e["line"], e["version"]), ("portal", "boom", 3, L.VERSION))
        self.assertEqual(self.req("POST", "/api/ytt/client-log", {"message": ""})[0], 400)

    def test_security_checks(self):
        body = {"message": "x"}
        self.assertEqual(self.req("POST", "/api/ytt/client-log", body, {"X-YTT-Token": "wrong"})[0], 403)
        self.assertEqual(self.req("POST", "/api/ytt/client-log", body, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/ytt/client-log", body, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("POST", "/api/ytt/client-log", body, {"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.req("POST", "/api/ytt/client-log", body, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("POST", "/api/ytt/client-log", raw=b"{" + b" " * (L.YTT_BODY_MAX + 1) + b"}")[0], 413)
        self.assertEqual(self.req("GET", "/api/ytt/client-log")[0], 404)   # GET では何もしない
        self.assertEqual(self.req("POST", "/api/ytt/nope", body)[0], 404)
        self.assertFalse(os.path.exists(self.srv.client_log.path))

    def test_window_setting_and_status(self):
        st, j = self.req("GET", "/api/status")
        self.assertEqual(j["window"]["mode"], "browser")
        self.assertTrue(j["window"]["available"])
        st, j = self.req("POST", "/api/window", {"mode": "app"})
        self.assertEqual((st, j["window"]["mode"]), (200, "app"))
        self.assertEqual(self.req("POST", "/api/window", {"mode": "x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/window", {"mode": "browser"}, {"X-YTT-Token": "wrong"})[0], 403)
        self.assertEqual(self.req("GET", "/api/status")[1]["window"]["mode"], "app")

    def test_open_window_and_external(self):
        st, j = self.req("POST", "/api/ytt/open-window", {"url": "http://localhost:%d/cases.html" % self.port})
        self.assertEqual(st, 200, j)
        self.assertEqual(self.fake.spawned[-1][0][1], "--app=http://localhost:%d/cases.html" % self.port)
        st, j = self.req("POST", "/api/ytt/open-window", {"url": "http://localhost:%d/studio/" % self.port})
        self.assertEqual(st, 400)   # 取り込んでいないツールの場所は開かない
        self.assertEqual(self.req("POST", "/api/ytt/open-window", {"url": "http://localhost:1/"})[0], 400)
        st, j = self.req("POST", "/api/ytt/open-external", {"url": "https://www.youtube.com/watch?v=abc"})
        self.assertEqual((st, self.fake.browsed), (200, ["https://www.youtube.com/watch?v=abc"]))
        self.assertEqual(self.req("POST", "/api/ytt/open-external", {"url": "file:///C:/Windows"})[0], 400)
        for _ in range(W.RATE[0]):
            self.req("POST", "/api/ytt/open-external", {"url": "https://example.com/"})
        self.assertEqual(self.req("POST", "/api/ytt/open-external", {"url": "https://example.com/"})[0], 429)

    def test_open_window_without_edge(self):
        self.srv.window = opener(os.path.join(self.tmp, "app"), FakeSys(exe=None))
        st, j = self.req("POST", "/api/ytt/open-window", {"url": "http://localhost:%d/" % self.port})
        self.assertEqual((st, j["error"]), (409, "unavailable"))


if __name__ == "__main__":
    unittest.main()
