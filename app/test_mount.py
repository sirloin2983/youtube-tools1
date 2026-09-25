# -*- coding: utf-8 -*-
"""入口への取り込み(app/mount.py・段階3)のテスト。  python -m unittest app/test_mount.py -v

本物の切り抜きスタジオ(疑似モード)・cut2resolve を一時フォルダに写し、入口のサーバーに取り込んで確かめる:
/studio/・/cut2resolve/ の画面・API・安全対策(CSP・合言葉・Host)、.runtime の場所、他のツールの /api/siblings、
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


def _purge_studio_modules(tool_dir, tool_id="studio"):
    """読み込んだツールの部品を sys.modules から外す(別の一時フォルダで読み込み直せるように・他のテストに残さないように)。"""
    sys.modules.pop(M.MOUNTS[tool_id]["alias"], None)
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


@unittest.skipUnless(all(os.path.isfile(os.path.join(REPO, d, "serve.py")) for d in ("clip-studio", "cut2resolve")), "ツールのフォルダが無い")
class TestCut2ResolveMounted(unittest.TestCase):
    """スタジオと cut2resolve を両方取り込んだ入口(start-all.bat の既定と同じ形)。段階3-2"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-mount-c2r-")
        for d in ("clip-studio", "cut2resolve"):
            _copy_tool(os.path.join(REPO, d), os.path.join(cls.tmp, d))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(cls.tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        cls.c2r_dir = os.path.join(cls.tmp, "cut2resolve")
        cls.studio_dir = os.path.join(cls.tmp, "clip-studio")
        cls.rdir = os.path.join(cls.tmp, ".runtime")
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": cls.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(cls.tmp, "home")})
        cls.env.start()
        cls.events = []
        cls.sup = L.Supervisor(cls.tmp, only=["studio", "cut2resolve"], log=cls.events.append, mounts=("studio", "cut2resolve"),
                               ports=dict(zip(("studio", "cut2resolve"), free_ports(2))))
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.sup.attach(cls.srv)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.sup.start("studio")
        cls.sup.start("cut2resolve")
        cls.host = "127.0.0.1:%d" % cls.port
        cls.mod = sys.modules[M.MOUNTS["cut2resolve"]["alias"]]
        cls.video = None
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            cls.video = os.path.join(cls.tmp, "in.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=30:duration=1", "-pix_fmt", "yuv420p",
                            "-y", cls.video], check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.sup.unmount_all()
        cls.srv.server_close()
        cls.env.stop()
        _purge_studio_modules(cls.c2r_dir, "cut2resolve")
        _purge_studio_modules(cls.studio_dir, "studio")
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

    def post(self, path, obj, token=True, extra=None):
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host}
        if token:
            h["X-YTT-Token"] = self.srv.token
        h.update(extra or {})
        return self.req("POST", path, json.dumps(obj).encode(), h)

    def test_mounted_state(self):
        snaps = {i: self.sup.by_id[i].snapshot() for i in ("studio", "cut2resolve")}
        self.assertEqual({i: (s["state"], s["mounted"], s["port"], s["path"]) for i, s in snaps.items()},
                         {"studio": ("running", True, self.port, "/studio/"), "cut2resolve": ("running", True, self.port, "/cut2resolve/")},
                         self.events)
        self.assertEqual(snaps["cut2resolve"]["version"], self.mod.SERVER_VERSION)
        self.assertIsNone(self.sup.by_id["cut2resolve"].proc)

    def test_page_assets_and_security_headers(self):
        r, body = self.req("GET", "/cut2resolve/")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Security-Policy"), self.mod.CSP)   # ツール自身の厳しい CSP のまま(YouTube も許さない)
        self.assertIn("script-src 'self';", self.mod.CSP)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode(), body)
        self.assertNotIn(b'src="/', body)
        self.assertNotIn(b'href="/', body)
        self.assertNotIn(b"__APP_VERSION__", body)
        for asset in ("app.js", "app.css", "ui-kit.js", "ui-kit.css"):
            r, _ = self.req("GET", "/cut2resolve/" + asset)
            self.assertEqual(r.status, 200, asset)
        r, _ = self.req("GET", "/cut2resolve?video=C%3A%5Ca.mp4")
        self.assertEqual((r.status, r.getheader("Location")), (301, "/cut2resolve/?video=C%3A%5Ca.mp4"))
        r, _ = self.req("GET", "/cut2resolvex/api/ping")   # 前方一致の取り違えがない(入口の 404)
        self.assertEqual(r.status, 404)
        r, _ = self.req("GET", "/studio/")   # スタジオも並んで動く
        self.assertEqual(r.status, 200)

    def test_api_token_and_guards(self):
        r, body = self.req("GET", "/cut2resolve/api/ping")
        self.assertEqual(json.loads(body), {"app": "cut2resolve", "version": self.mod.SERVER_VERSION})
        r, body = self.req("GET", "/cut2resolve/api/state")
        self.assertEqual((r.status, json.loads(body)["app"]), (200, "cut2resolve"))
        r, body = self.post("/cut2resolve/api/inspect", {}, token=False)
        self.assertEqual((r.status, json.loads(body)["error"]), (403, "token"))
        r, _ = self.post("/cut2resolve/api/inspect", {}, extra={"X-YTT-Token": "x" * len(self.srv.token)})
        self.assertEqual(r.status, 403)
        r, body = self.post("/cut2resolve/api/inspect", {})
        self.assertEqual(r.status, 200, body)
        r, _ = self.post("/cut2resolve/api/inspect", {}, extra={"Origin": "http://localhost:8810"})
        self.assertEqual(r.status, 403)   # 単独で動くときの cut2resolve のアドレスからも受け付けない(入口のポートだけ)
        r, _ = self.req("GET", "/cut2resolve/api/state", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/cut2resolve/api/state", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, _ = self.req("POST", "/cut2resolve/api/upload?kind=srt&name=a.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhi\n",
                        {"Content-Type": "application/octet-stream", "X-YTT-Token": self.srv.token})
        self.assertEqual(r.status, 200)
        r, body = self.req("POST", "/cut2resolve/api/job/cancel", b"{}", {"Content-Type": "application/json"})
        self.assertEqual(r.status, 403)   # 合言葉のないものは、ツールの処理まで届かない
        r, _ = self.req("POST", "/api/tools/cut2resolve/stop", b"{}", {"Content-Type": "application/json"})
        self.assertEqual(r.status, 403)   # 入口の API も合言葉が要る

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg が無い")
    def test_media_under_prefix(self):
        r, body = self.post("/cut2resolve/api/inspect", {"video": self.video})
        self.assertEqual(r.status, 200, body)
        url = json.loads(body)["inputs"]["video"]["mediaUrl"]
        self.assertTrue(url.startswith("/media/"), url)   # 画面は BASE を前に付けて使う(app.js の mediaSrc)
        r, data = self.req("GET", "/cut2resolve" + url, headers={"Range": "bytes=0-9"})
        self.assertEqual((r.status, len(data)), (206, 10))
        self.assertEqual(r.getheader("Content-Security-Policy"), "default-src 'none'; sandbox")
        r, _ = self.req("GET", url)   # 入口の直下には無い
        self.assertEqual(r.status, 404)

    def test_runtime_and_siblings(self):
        info = L.read_runtime(self.rdir, "cut2resolve")
        self.assertEqual((info["port"], info["path"]), (self.port, "/cut2resolve/"))
        want = {"tools": {"studio": self.port, "cut2resolve": self.port}, "paths": {"studio": "/studio/", "cut2resolve": "/cut2resolve/"}}
        r, body = self.req("GET", "/cut2resolve/api/siblings")
        self.assertEqual(json.loads(body), want)
        r, body = self.req("GET", "/studio/api/siblings")
        self.assertEqual(json.loads(body), want)
        from ytt_core import runtime
        self.assertEqual(runtime.siblings(self.rdir, "transcribe", 8775)["paths"], want["paths"])

    def test_standalone_start_opens_the_mounted_one(self):
        port = free_ports(1)[0]
        r = subprocess.run([sys.executable, os.path.join(self.c2r_dir, "serve.py"), str(port), "--no-open"],
                           capture_output=True, text=True, timeout=60, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("入口の中ですでに起動しています", r.stdout)
        self.assertIn("/cut2resolve/", r.stdout)
        self.assertFalse(L.port_open(port))

    def test_finish_cancels_job_and_removes_runtime(self):
        """入口の終了で呼ぶ finish(): 動いているジョブを取り消す・自分の .runtime を消す(別のテストの後始末に影響しないよう、記録は書き戻す)"""
        started, gate = threading.Event(), threading.Event()
        job = self.mod.MOUNT.app.start_job("build", lambda task: (started.set(), gate.wait(5), {})[2])
        self.assertTrue(started.wait(5))
        self.assertTrue(self.mod.busy())
        with mock.patch.object(job.task, "cancel") as cancel:
            self.mod.finish()
            cancel.assert_called_once()
        gate.set()
        self.assertIsNone(L.read_runtime(self.rdir, "cut2resolve"))
        self.assertTrue(wait_for(lambda: not self.mod.busy(), 5))
        self.mod.write_runtime(self.port, "/cut2resolve/")


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
