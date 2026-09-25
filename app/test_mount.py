# -*- coding: utf-8 -*-
"""入口への取り込み(app/mount.py・段階3)のテスト。  python -m unittest app/test_mount.py -v

本物の切り抜きスタジオ(疑似モード)を一時フォルダに写し、入口のサーバーに取り込んで確かめる:
/studio/ の画面・API・安全対策(CSP・合言葉・Host)、.runtime の場所、他のツールの /api/siblings、
別の画面で起動済みのときは取り込まないこと、取り込めないときは別のプログラムとして起動すること、
start.bat からの二重起動を防ぐこと、ツール間で部品の名前が重ならないこと。
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launch as L  # noqa: E402
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402

TOOL_DIRS = ("clip-studio", "cut2resolve", "transcribe-tool")


def _purge_studio_modules(tool_dir):
    """読み込んだスタジオの部品を sys.modules から外す(別の一時フォルダで読み込み直せるように・他のテストに残さないように)。"""
    sys.modules.pop(M.MOUNTS["studio"]["alias"], None)
    for name in M.tool_modules(tool_dir):
        m = sys.modules.get(name)
        if m is not None and os.path.dirname(os.path.abspath(getattr(m, "__file__", "") or "")) == os.path.abspath(tool_dir):
            sys.modules.pop(name, None)
    while tool_dir in sys.path:
        sys.path.remove(tool_dir)


class TestModuleNames(unittest.TestCase):
    def test_tools_do_not_share_module_names(self):
        """1つのプロセスに取り込むので、ツール間で同じ名前の部品を作らない(docs/integration-plan.md)"""
        seen = {}
        for d in TOOL_DIRS + ("app", "ytt_core"):
            path = os.path.join(REPO, d)
            if not os.path.isdir(path):
                continue
            for name in M.tool_modules(path):
                self.assertNotIn(name, seen, "%s が %s と %s の両方にある" % (name, seen.get(name), d))
                seen[name] = d

    def test_collision_is_refused_at_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "common.py"), "w") as f:
                f.write("")
            fake = types.ModuleType("common")
            fake.__file__ = os.path.join(REPO, "elsewhere", "common.py")
            with mock.patch.dict(sys.modules, {"common": fake}):
                with self.assertRaises(M.MountError):
                    M.check_no_collision(tmp)


class TestHelpers(unittest.TestCase):
    def test_inject_token(self):
        self.assertEqual(M.inject_token(b"<html><head><title>x</title></head>", "abc"),
                         b'<html><head><title>x</title><meta name="ytt-token" content="abc"></head>')
        self.assertTrue(M.inject_token(b"<p>no head</p>", "t").startswith(b'<meta name="ytt-token"'))

    def test_peek_path(self):
        a, b = socket.socketpair()
        try:
            a.sendall(b"GET /studio/api/state?x=1 HTTP/1.1\r\nHost: x\r\n\r\n")
            self.assertEqual(L.peek_path(b, 2), "/studio/api/state?x=1")
            self.assertEqual(b.recv(100)[:4], b"GET ")   # 覗いただけで、読み取ってはいない
        finally:
            a.close()
            b.close()
        a, b = socket.socketpair()
        a.close()
        try:
            self.assertIsNone(L.peek_path(b, 1))   # 何も送らずに切った接続
        finally:
            b.close()
        a, b = socket.socketpair()
        try:
            a.sendall(b"GARBAGE\r\n")
            self.assertIsNone(L.peek_path(b, 1))
        finally:
            a.close()
            b.close()


@unittest.skipUnless(os.path.isfile(os.path.join(REPO, "clip-studio", "serve.py")), "スタジオのフォルダが無い")
class TestStudioMounted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-mount-")
        _copy_tool(os.path.join(REPO, "clip-studio"), os.path.join(cls.tmp, "clip-studio"))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(cls.tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        cls.studio_dir = os.path.join(cls.tmp, "clip-studio")
        cls.rdir = os.path.join(cls.tmp, ".runtime")
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": cls.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(cls.tmp, "home")})
        cls.env.start()
        cls.events = []
        cls.sup = L.Supervisor(cls.tmp, only=["studio"], log=cls.events.append, mounts=("studio",), ports={"studio": free_ports(1)[0]})
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.sup.attach(cls.srv)
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()
        cls.sup.start("studio")
        cls.host = "127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.sup.unmount_all()
        cls.srv.server_close()
        cls.env.stop()
        _purge_studio_modules(cls.studio_dir)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.host}
        h.update(headers or {})
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r, data

    def test_mounted_state(self):
        snap = self.sup.by_id["studio"].snapshot()
        self.assertEqual((snap["state"], snap["mounted"], snap["port"], snap["path"]), ("running", True, self.port, "/studio/"), self.events)
        self.assertIsNone(self.sup.by_id["studio"].proc)   # 子プロセスではない
        self.sup.stop("studio")
        self.sup.restart("studio")
        self.assertEqual(self.sup.by_id["studio"].snapshot()["state"], "running")   # 入口と一緒にしか止まらない

    def test_page_assets_and_security_headers(self):
        r, body = self.req("GET", "/studio/")
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self' https://www.youtube.com", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode(), body)
        self.assertNotIn(b'src="/', body)   # 画面の部品は相対パス(/studio/ の下でも読める)
        for asset in ("core.js", "ui-kit.js", "ui-kit.css", "app.css", "review.js"):
            r, data = self.req("GET", "/studio/" + asset)
            self.assertEqual(r.status, 200, asset)
            self.assertIsNone(r.getheader("Content-Security-Policy"), asset)
        r, _ = self.req("GET", "/studio?url=abc")
        self.assertEqual((r.status, r.getheader("Location")), (301, "/studio/?url=abc"))
        r, body = self.req("GET", "/")   # 入口の画面はそのまま
        self.assertIn("作業の入口".encode("utf-8"), body)

    def test_api_and_token(self):
        r, body = self.req("GET", "/studio/api/ping")
        self.assertEqual(json.loads(body)["app"], "clip-studio")
        r, body = self.req("GET", "/studio/api/state")
        self.assertEqual(r.status, 200)
        self.assertIn("outDir", json.loads(body))
        put = {"Content-Type": "application/json", "Origin": "http://" + self.host}
        data = json.dumps({"settings": {"x": 1}}).encode()
        r, _ = self.req("PUT", "/studio/api/settings", data, put)
        self.assertEqual(r.status, 403)   # 合言葉なし
        r, _ = self.req("PUT", "/studio/api/settings", data, dict(put, **{"X-YTT-Token": "wrong"}))
        self.assertEqual(r.status, 403)
        r, _ = self.req("PUT", "/studio/api/settings", data, dict(put, **{"X-YTT-Token": self.srv.token}))
        self.assertEqual(r.status, 200)
        r, _ = self.req("PUT", "/studio/api/settings", data, {"Content-Type": "application/json", "Origin": "http://evil.example",
                                                               "X-YTT-Token": self.srv.token})
        self.assertEqual(r.status, 403)   # Origin の検査はスタジオの Handler がそのまま行う
        r, _ = self.req("GET", "/studio/api/state", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(r.status, 403)   # Host の検査も(入口のポートにそろえてある)
        r, _ = self.req("GET", "/studio/api/state", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/studio/nope")
        self.assertEqual(r.status, 404)

    def test_runtime_and_siblings(self):
        info = L.read_runtime(self.rdir, "studio")
        self.assertEqual((info["port"], info["path"]), (self.port, "/studio/"))
        r, body = self.req("GET", "/studio/api/siblings")
        self.assertEqual(json.loads(body), {"tools": {"studio": self.port}, "paths": {"studio": "/studio/"}})
        from ytt_core import runtime   # 他のツールから見た siblings(文字起こしは ytt_core を使う)
        self.assertEqual(runtime.siblings(self.rdir, "transcribe", 8775)["paths"], {"studio": "/studio/"})

    def test_standalone_start_opens_the_mounted_one(self):
        """取り込まれている間に start.bat からスタジオを起動しても、2つ目のサーバーは立てない(同じ data.json を取り合わないため)"""
        port = free_ports(1)[0]
        r = subprocess.run([sys.executable, os.path.join(self.studio_dir, "serve.py"), str(port), "--no-open"],
                           capture_output=True, text=True, timeout=60, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("入口の中ですでに起動しています", r.stdout)
        self.assertIn("/studio/", r.stdout)
        self.assertFalse(L.port_open(port))


@unittest.skipUnless(os.path.isfile(os.path.join(REPO, "clip-studio", "serve.py")), "スタジオのフォルダが無い")
class TestMountFallbacks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-mount-fb-")
        _copy_tool(os.path.join(REPO, "clip-studio"), os.path.join(self.tmp, "clip-studio"))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(self.tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        self.rdir = os.path.join(self.tmp, ".runtime")
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(self.tmp, "home")})
        self.env.start()
        self.events = []
        self.studio_port = free_ports(1)[0]
        self.sup = L.Supervisor(self.tmp, only=["studio"], log=self.events.append, mounts=("studio",), ports={"studio": self.studio_port},
                                poll=0.2, stop_timeout=5)
        self.srv, self.port = L.make_server(0, self.sup)
        self.sup.attach(self.srv)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.procs = []

    def tearDown(self):
        self.sup.close()
        self.sup.stop_all()
        self.sup.unmount_all()
        self.srv.shutdown()
        self.srv.server_close()
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
                p.wait(10)
        self.env.stop()
        _purge_studio_modules(os.path.join(self.tmp, "clip-studio"))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_external_studio_is_not_mounted(self):
        p = subprocess.Popen([sys.executable, os.path.join(self.tmp, "clip-studio", "serve.py"), str(self.studio_port), "--no-open"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))
        self.procs.append(p)
        self.assertTrue(wait_for(lambda: L.ping(self.studio_port) is not None, 30))
        self.sup.start("studio")
        snap = self.sup.by_id["studio"].snapshot()
        self.assertEqual((snap["state"], snap["mounted"]), ("external", False))
        self.assertEqual(self.srv.mounts, {})
        r = L.ping(self.port, path="/studio/")
        self.assertIsNone(r)

    def test_mount_failure_falls_back_to_process(self):
        fake = types.ModuleType("common")
        fake.__file__ = os.path.join(REPO, "elsewhere", "common.py")
        with mock.patch.dict(sys.modules, {"common": fake}):
            self.sup.start("studio")
        self.sup.start_monitor()
        self.assertTrue(any("取り込めませんでした" in e for e in self.events), self.events)
        self.assertTrue(wait_for(lambda: self.sup.by_id["studio"].snapshot()["state"] == "running", 40), self.events)
        snap = self.sup.by_id["studio"].snapshot()
        self.assertEqual((snap["mounted"], snap["port"], snap["path"]), (False, self.studio_port, "/"))
        self.assertIsNotNone(self.sup.by_id["studio"].proc)


if __name__ == "__main__":
    unittest.main()
