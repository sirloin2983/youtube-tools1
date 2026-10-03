# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P1)の入口の側(home/live.py・prefs の節 live・launch.py の /live/…・「調子」の行)のテスト。

    py -3.10 -m unittest home/tests/test_live.py

確かめること:
  - 設定 live: 既定はオフ・形の検査・合言葉は空で送っても今の値を残す・画面へ返す設定に合言葉を出さない
  - オフ: /live/… は今までと同じ 404(GET・POST とも)・「調子」に live が出ない・見回りは何もしない
  - オン: 画面(CSP に media-src blob:・合言葉)・hls.js の同梱・録画元の一覧(合言葉を出さない)・中継(合言葉 Bearer と Host を付ける・
    Sec-Fetch-Site と入口の合言葉の検査・知らない録画元・パスの検査・思わぬ種類の応答・録画元が止まっている)・「調子」の行
  - 見回り: 手元の録画の部品(recorder/recorder.py)を切り離して起動する → 動いている → 古い版なら終わってもらって起動し直す
"""
import http.client
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
import live as LV  # noqa: E402
import prefs as P  # noqa: E402
from ytt_core import fsio  # noqa: E402

TOKEN = "t" * 40


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_for(fn, timeout=20.0, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class FakeRecorder:
    """録画元の代わり(合言葉と Host を確かめ、受けた要求を覚える)"""

    def __init__(self):
        self.seen = []
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, body=None):
                owner.seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                                   "host": self.headers.get("Host"), "origin": self.headers.get("Origin"), "body": body})
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, b'{"error":"token","message":"x"}', "application/json")
                if self.path == "/api/ping":
                    return self._out(200, b'{"app":"ytt-recorder","version":"0.0.1"}', "application/json")
                if self.path == "/live/list":
                    return self._out(200, json.dumps({"folder": "X:\\rec", "folderOk": True, "folderMessage": "", "freeBytes": 5 * 1024 ** 3,
                                                      "totalBytes": 9 * 1024 ** 3, "streamlink": True, "version": "0.0.1", "active": 1,
                                                      "recordings": [{"id": "20261004-000000-a", "title": "t", "state": "recording", "active": True,
                                                                      "segments": 3, "lastPdt": None, "message": ""}]}).encode(), "application/json")
                if self.path == "/live/20261004-000000-a/index.m3u8":
                    return self._out(200, b"#EXTM3U\n", "application/vnd.apple.mpegurl")
                if self.path == "/live/20261004-000000-a/session_001/seg_000000.ts":
                    return self._out(200, b"\x47" * 188 * 10, "video/mp2t")
                if self.path == "/live/html":
                    return self._out(200, b"<script>alert(1)</script>", "text/html")
                if self.path.startswith("/live/20261004-000000-a/status"):
                    return self._out(200, json.dumps({"path": self.path}).encode(), "application/json")
                return self._out(404, b'{"error":"not_found","message":"x"}', "application/json")

            def do_GET(self):
                self._handle()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._handle(json.loads(self.rfile.read(n).decode()) if n else None)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class PrefsLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-prefs-")
        self.p = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_off_and_validation(self):
        self.assertEqual(self.p.get(["live"])["live"], {"enabled": False, "folder": "", "recorders": []})
        v = self.p.patch("live", {"enabled": True, "folder": "E:\\Video\\live-rec"})
        self.assertEqual((v["enabled"], v["folder"]), (True, "E:\\Video\\live-rec"))
        for bad in ({"folder": "\\\\nas\\rec"}, {"folder": "rec"}, {"recorders": "x"}, {"recorders": [{"id": "Bad", "url": "http://a:8730"}]},
                    {"recorders": [{"id": "a", "url": "http://a:8730/path"}]}, {"recorders": [{"id": "a", "url": "https://a:8730"}]},
                    {"recorders": [{"id": "a", "url": "http://a:80"}]}, {"recorders": [{"id": "a", "url": "http://a:8730", "token": "short"}]},
                    {"recorders": [{"id": "a", "url": "http://a:8730"}, {"id": "a", "url": "http://b:8730"}]},
                    {"recorders": [{"id": "r%d" % i, "url": "http://a:8730"} for i in range(9)]}):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertTrue(self.p.get(["live"])["live"]["enabled"])   # 断ったときは変えない

    def test_token_is_kept_when_blank(self):
        self.p.patch("live", {"recorders": [{"id": "laptop", "name": "ノート PC", "url": "http://192.168.1.20:8730", "token": TOKEN}]})
        v = self.p.patch("live", {"recorders": [{"id": "laptop", "name": "ノート", "url": "http://192.168.1.20:8730", "token": ""}]})
        self.assertEqual(v["recorders"][0]["token"], TOKEN)
        self.assertEqual(v["recorders"][0]["name"], "ノート")
        v = self.p.patch("live", {"recorders": [{"id": "laptop", "name": "ノート", "url": "http://192.168.1.99:8730", "token": ""}]})
        self.assertEqual(v["recorders"][0]["token"], "")   # URL を変えたら前の合言葉は残さない(別の相手へ送らない)


class PortalLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-portal-")
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")})
        self.env.start()
        self.sup = L.Supervisor(self.tmp, only=[], log=lambda m: None, mounts=())
        self.srv, self.port = L.make_server(0, self.sup)
        self.sup.attach(self.srv)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.fake = FakeRecorder()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.fake.close()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, token=True, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Host": "127.0.0.1:%d" % self.port}
        data = None
        if method == "POST":
            data = json.dumps(body or {}).encode("utf-8")
            h["Content-Type"] = "application/json"
            h["Origin"] = "http://127.0.0.1:%d" % self.port
            if token:
                h["X-YTT-Token"] = self.srv.token
        h.update(headers or {})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), raw

    def jreq(self, *a, **kw):
        code, h, raw = self.req(*a, **kw)
        return code, json.loads(raw.decode("utf-8")) if h.get("content-type", "").startswith("application/json") else raw

    def enable(self, **extra):
        v = dict({"enabled": True, "recorders": [{"id": "fake", "name": "偽物", "url": self.fake.url, "token": TOKEN}]}, **extra)
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "patch", "section": "live", "value": v})
        self.assertEqual(code, 200, d)
        return d

    def test_off_is_unchanged(self):
        base = self.jreq("GET", "/no-such-thing")
        for path in ("/live", "/live/", "/live/live.js", "/live/hls.min.js", "/live/api/info", "/live/r/local/list"):
            self.assertEqual(self.jreq("GET", path), base, path)   # 今までと同じ 404
        base_post = self.jreq("POST", "/api/no-such", {})
        self.assertEqual(self.jreq("POST", "/live/r/local/start", {"url": "x"}), base_post)
        self.assertEqual(self.req("POST", "/live/r/local/start", {}, token=False)[0], 403)   # 合言葉の検査も今までどおり
        self.assertNotIn("live", self.jreq("GET", "/api/health")[1])
        self.assertEqual(self.srv.live.tick(), "off")   # 見回りは何もしない(録画の部品を起動しない)
        self.assertEqual(self.srv.live.health(), None)
        self.assertFalse(self.fake.seen)

    def test_on_page_and_relay(self):
        d = self.enable()
        self.assertEqual(d["value"]["recorders"][0]["token"], "")   # 画面へは合言葉を返さない
        self.assertTrue(d["value"]["recorders"][0]["hasToken"])
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "get", "sections": ["live"]})
        self.assertEqual(d["prefs"]["live"]["recorders"][0]["token"], "")
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "get"})   # 全部の節を読んでも同じ
        self.assertEqual(d["prefs"]["live"]["recorders"][0]["token"], "")
        # 画面
        self.assertEqual(self.req("GET", "/live")[0], 301)
        code, h, raw = self.req("GET", "/live/")
        self.assertEqual(code, 200)
        self.assertIn("media-src 'self' blob:", h["content-security-policy"])
        self.assertIn("script-src 'self';", h["content-security-policy"])
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode(), raw)
        code, h, raw = self.req("GET", "/live/hls.min.js")
        self.assertEqual((code, h["content-type"]), (200, "application/javascript; charset=utf-8"))
        self.assertGreater(len(raw), 100000)
        code, d = self.jreq("GET", "/live/api/info")
        self.assertEqual([r["id"] for r in d["recorders"]], ["fake"])
        self.assertNotIn(TOKEN, json.dumps(d))
        # 中継: 合言葉と Host を付ける。ブラウザの Origin は渡さない
        code, d = self.jreq("GET", "/live/r/fake/list")
        self.assertEqual(code, 200, d)
        self.assertEqual(d["active"], 1)
        last = self.fake.seen[-1]
        self.assertEqual((last["auth"], last["host"], last["path"]), ("Bearer " + TOKEN, "127.0.0.1:%d" % self.fake.port, "/live/list"))
        code, h, raw = self.req("GET", "/live/r/fake/20261004-000000-a/index.m3u8")
        self.assertEqual((code, h["content-type"], h["cache-control"]), (200, "application/vnd.apple.mpegurl", "no-cache"))
        code, h, raw = self.req("GET", "/live/r/fake/20261004-000000-a/session_001/seg_000000.ts")
        self.assertEqual((code, h["content-type"], len(raw)), (200, "video/mp2t", 1880))
        code, d = self.jreq("GET", "/live/r/fake/20261004-000000-a/status?since=5")
        self.assertEqual(d["path"], "/live/20261004-000000-a/status?since=5")
        code, d = self.jreq("POST", "/live/r/fake/start", {"url": "https://www.youtube.com/watch?v=x"})
        self.assertEqual(code, 404)   # 偽物は start を知らない(中継はそのまま返す)
        self.assertEqual(self.fake.seen[-1]["body"], {"url": "https://www.youtube.com/watch?v=x"})
        self.assertIsNone(self.fake.seen[-1]["origin"])
        # 検査
        n = len(self.fake.seen)
        self.assertEqual(self.req("GET", "/live/r/fake/list", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("GET", "/live/r/fake/list", headers={"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.req("POST", "/live/r/fake/start", {}, token=False)[0], 403)
        self.assertEqual(self.req("POST", "/live/r/fake/start", {}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.jreq("GET", "/live/r/nope/list")[0], 404)
        for bad in ("/live/r/fake/../x", "/live/r/fake/a//b", "/live/r/fake/%2e%2e/x", "/live/r/FAKE/list", "/live/x"):
            self.assertEqual(self.req("GET", bad)[0], 404, bad)
        self.assertEqual(len(self.fake.seen), n)   # 断った要求は録画元へ届かない
        self.assertEqual(self.jreq("GET", "/live/r/fake/html")[0], 502)   # 思わぬ種類(HTML)は返さない
        # 「調子」
        h = self.jreq("GET", "/api/health")[1]
        self.assertEqual(h["live"]["recorders"][0]["ok"], True)
        self.assertEqual(h["live"]["recorders"][0]["freeBytes"], 5 * 1024 ** 3)
        self.assertEqual(h["live"]["recorders"][0]["active"], 1)
        # 録画元が止まっている
        self.fake.close()
        code, d = self.jreq("GET", "/live/r/fake/list")
        self.assertEqual((code, d["error"]), (502, "recorder_down"))
        h = self.jreq("GET", "/api/health")[1]
        self.assertFalse(h["live"]["recorders"][0]["ok"])
        self.fake = FakeRecorder()   # tearDown で閉じる分

    def test_default_recorder_is_local(self):
        self.jreq("POST", "/api/ytt/prefs", {"op": "patch", "section": "live", "value": {"enabled": True}})
        code, d = self.jreq("GET", "/live/api/info")
        self.assertEqual(d["recorders"], [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:8730", "local": True}])
        self.assertEqual(d["defaultFolder"], "E:\\Video\\live-rec")


class SpawnTest(unittest.TestCase):
    """見回りが本物の録画の部品(recorder/recorder.py)を切り離して起動する"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-spawn-")
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.port = free_port()
        self.rec_folder = os.path.join(self.tmp, "live-rec")
        self.prefs.patch("live", {"enabled": True, "folder": self.rec_folder,
                                  "recorders": [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % self.port}]})
        self.logs = []
        self.live = LV.Live(self.prefs, REPO, os.path.join(self.tmp, "logs"), log=self.logs.append, data_dir=os.path.join(self.tmp, "recdata"))

    def tearDown(self):
        rc = self.live.find("local")
        if rc and self.live.ping(rc):
            self.live.call(rc, "POST", "/live/quit", {})
            wait_for(lambda: not self.live.ping(rc, 0.5), 15)
        if self.live.proc:
            try:
                self.live.proc.wait(10)
            except Exception:
                self.live.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_spawn_then_running_then_restart_old_version(self):
        self.assertEqual(self.live.tick(), "spawned", self.logs)
        rc = self.live.find("local")
        self.assertTrue(wait_for(lambda: self.live.ping(rc), 30), self.logs)
        self.assertTrue(self.live.local_token())   # 録画の部品が作った合言葉を読める
        rc = self.live.find("local")               # 合言葉は起動したあとにできる(読み直す)
        self.assertEqual(self.live.tick(), "running")
        code, d = self.live.call(rc, "GET", "/live/list")
        self.assertEqual(code, 200, d)
        self.assertEqual(os.path.normcase(d["folder"]), os.path.normcase(self.rec_folder))   # 設定の置き場所で起動した
        h = self.live.health()
        self.assertTrue(h["recorders"][0]["ok"])
        self.assertEqual(h["recorders"][0]["version"], h["recorders"][0]["expected"])
        # 置き場所を変えた → 見回りが伝える
        other = os.path.join(self.tmp, "other")
        self.prefs.patch("live", {"folder": other})
        self.assertEqual(self.live.tick(), "running")
        self.assertEqual(os.path.normcase(self.live.call(rc, "GET", "/live/config")[1]["folder"]), os.path.normcase(other))
        # コードの版が上がった → 録画中でなければ終わってもらって起動し直す
        old = self.live.proc
        with mock.patch.object(self.live, "expected_version", return_value="99.0.0"):
            self.assertEqual(self.live.tick(), "spawned", self.logs)
        self.assertIsNot(self.live.proc, old)
        self.assertEqual(old.wait(15), 0)
        self.assertTrue(wait_for(lambda: self.live.ping(rc), 30), self.logs)
        # オフにすると見回りは何もしない(録画の部品は止めない)
        self.prefs.patch("live", {"enabled": False})
        self.assertEqual(self.live.tick(), "off")
        self.assertTrue(self.live.ping(rc))


if __name__ == "__main__":
    unittest.main()
