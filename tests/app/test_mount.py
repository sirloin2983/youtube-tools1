# -*- coding: utf-8 -*-
"""入口への取り込み(src/app/mount.py)のテスト。  python -m unittest tests/app/test_mount.py -v

本物の切り抜きスタジオ(疑似モード)・cut2resolve を一時フォルダに写し、入口のサーバーに取り込んで確かめる:
/studio/・/cut2resolve/ の画面・API・安全対策(CSP・合言葉・Host)、.runtime の場所、他のツールの /api/siblings、
別の画面で起動済みのときは取り込まないこと、取り込めないときは別のプログラムとして起動すること、
serve.py の直接起動による二重起動を防ぐこと、ツール間で部品の名前が重ならないこと。
"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))   # tests/app
HERE = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src", "app")   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.append(os.path.dirname(HERE))   # src(app 層。入口本体は src/app/server.py)
from app import server as L  # noqa: E402
from app import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402
from pipeline.transcribe import worker_client as _worker_client  # noqa: E402
from ytt import httpsec, layout  # noqa: E402

STUDIO_DIR, TX_DIR = layout.TOOL_DIRS["studio"], layout.TOOL_DIRS["transcribe"]   # リポジトリの中のフォルダ名
TOOL_DIRS = (STUDIO_DIR, layout.TOOL_DIRS["cut2resolve"], TX_DIR)


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
        self.assertEqual(httpsec.inject_token(b"<html><head><title>x</title></head>", "abc"),
                         b'<html><head><title>x</title><meta name="ytt-token" content="abc"></head>')
        self.assertTrue(httpsec.inject_token(b"<p>no head</p>", "t").startswith(b'<meta name="ytt-token"'))

    def test_inject_version_meta(self):
        """版を渡すと meta ytt-version も入る(画面の APP_VERSION の元)。変な文字の版は入れない"""
        self.assertEqual(httpsec.inject_token(b"<head></head>", "abc", "0.56.0"),
                         b'<head><meta name="ytt-token" content="abc"><meta name="ytt-version" content="0.56.0"></head>')
        self.assertNotIn(b"ytt-version", httpsec.inject_token(b"<head></head>", "abc", '"><script>'))
        self.assertNotIn(b"ytt-version", httpsec.inject_token(b"<head></head>", "abc"))

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


@unittest.skipUnless(os.path.isfile(os.path.join(REPO, STUDIO_DIR, "serve.py")), "スタジオのフォルダが無い")
class TestStudioMounted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-mount-")
        _copy_tool(os.path.join(REPO, STUDIO_DIR), os.path.join(cls.tmp, STUDIO_DIR))
        from ytt import layout as _layout
        _layout.copy_shared_code(cls.tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        cls.studio_dir = os.path.join(cls.tmp, STUDIO_DIR)
        cls.rdir = os.path.join(cls.tmp, ".runtime")
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": cls.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(cls.tmp, "home")})
        cls.env.start()
        cls.events = []
        cls.sup = L.Supervisor(cls.tmp, only=["studio"], log=cls.events.append, mounts=("studio",), ports={"studio": free_ports(1)[0]})
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.sup.attach(cls.srv)
        cls.th = threading.Thread(target=cls.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
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
        self.sup.start("studio")
        self.assertEqual(self.sup.by_id["studio"].snapshot()["state"], "running")   # 入口と一緒にしか止まらない

    def test_page_assets_and_security_headers(self):
        r, _ = self.req("GET", "/studio?url=abc")   # 末尾の / を足す 301 は取り込みの決まりのまま
        self.assertEqual((r.status, r.getheader("Location")), (301, "/studio/?url=abc"))
        # 取り込み(MOUNTS)の CSP(script-src にインラインを許さない・YouTube のプレイヤーだけ外部。起動のとき Mount.start が検査する)
        csp = M.MOUNTS["studio"]["csp"]
        self.assertIn("script-src 'self' https://www.youtube.com", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        for asset in ("rank.js", "queue.js", "review.js", "collab.js"):   # 案件の画面が読む部品だけ配る(スタジオの serve.py の STATIC)
            r, data = self.req("GET", "/studio/" + asset)
            self.assertEqual(r.status, 200, asset)
            self.assertIsNone(r.getheader("Content-Security-Policy"), asset)
        r, body = self.req("GET", "/")   # ホームの画面はそのまま
        self.assertIn("動画編集ツール — ホーム".encode("utf-8"), body)

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

    def test_shared_api_goes_to_portal(self):
        """取り込んだツールの画面の api/ytt/…(画面のエラーの記録など)は、ツールではなく入口が受け持つ"""
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "X-YTT-Token": self.srv.token}
        data = json.dumps({"kind": "error", "message": "studio で落ちた", "source": "http://%s/studio/review.js" % self.host, "line": 9}).encode()
        r, body = self.req("POST", "/studio/api/ytt/client-log", data, h)
        self.assertEqual((r.status, json.loads(body)), (200, {"ok": True, "kept": True}))
        with open(self.srv.client_log.path, encoding="utf-8") as f:
            e = json.loads(f.read().splitlines()[-1])
        self.assertEqual((e["tool"], e["message"], e["line"]), ("studio", "studio で落ちた", 9))
        self.assertEqual(e["version"], self.sup.by_id["studio"].snapshot()["version"])
        r, _ = self.req("POST", "/studio/api/ytt/client-log", data, dict(h, **{"X-YTT-Token": "wrong"}))
        self.assertEqual(r.status, 403)
        r, _ = self.req("POST", "/studio/api/ytt/client-log", data, dict(h, Origin="http://evil.example"))
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/studio/api/ytt/client-log")
        self.assertEqual(r.status, 405)
        r, body = self.req("POST", "/studio/api/ytt/open-window", json.dumps({"url": "http://localhost:1/"}).encode(), h)
        self.assertEqual(r.status, 400)   # 開ける先の検査は入口と同じ
        r, body = self.req("POST", "/studio/api/ytt/live", json.dumps({"op": "status"}).encode(), h)   # ヘッダーの録画の札。既定はオフ
        self.assertEqual((r.status, json.loads(body)), (200, {"enabled": False}))
        r, _ = self.req("POST", "/studio/api/ytt/live", json.dumps({"op": "status"}).encode(), dict(h, **{"X-YTT-Token": "wrong"}))
        self.assertEqual(r.status, 403)

    def test_runtime_and_siblings(self):
        info = L.read_runtime(self.rdir, "studio")
        self.assertEqual((info["port"], info["path"]), (self.port, "/studio/"))

    def test_standalone_start_opens_the_mounted_one(self):
        """取り込まれている間に serve.py を直接起動しても、2つ目のサーバーは立てない(同じ data.json を取り合わないため)"""
        port = free_ports(1)[0]
        r = subprocess.run([sys.executable, os.path.join(self.studio_dir, "serve.py"), str(port), "--no-open"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("入口の中ですでに起動しています", r.stdout)
        self.assertIn("/studio/", r.stdout)
        self.assertFalse(L.port_open(port))


@unittest.skipUnless(all(os.path.isfile(os.path.join(REPO, d, "serve.py")) for d in (STUDIO_DIR, "cut2resolve")), "ツールのフォルダが無い")
class TestCut2ResolveMounted(unittest.TestCase):
    """スタジオと cut2resolve を両方取り込んだ入口(start.bat の既定と同じ形)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-mount-c2r-")
        for d in (STUDIO_DIR, "cut2resolve"):
            _copy_tool(os.path.join(REPO, d), os.path.join(cls.tmp, d))
        from ytt import layout as _layout
        _layout.copy_shared_code(cls.tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        cls.c2r_dir = os.path.join(cls.tmp, "cut2resolve")
        cls.studio_dir = os.path.join(cls.tmp, STUDIO_DIR)
        cls.rdir = os.path.join(cls.tmp, ".runtime")
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": cls.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(cls.tmp, "home")})
        cls.env.start()
        cls.events = []
        cls.sup = L.Supervisor(cls.tmp, only=["studio", "cut2resolve"], log=cls.events.append, mounts=("studio", "cut2resolve"),
                               ports=dict(zip(("studio", "cut2resolve"), free_ports(2))))
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.sup.attach(cls.srv)
        threading.Thread(target=cls.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        cls.sup.start("studio")
        cls.sup.start("cut2resolve")
        cls.host = "127.0.0.1:%d" % cls.port
        cls.mod = sys.modules[M.MOUNTS["cut2resolve"]["alias"]]

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

    def test_page_assets_and_security_headers(self):
        r, body = self.req("GET", "/cut2resolve/")
        self.assertEqual(r.status, 200)   # 画面は「編集」の中。ここは案内だけ
        self.assertEqual(r.getheader("Content-Security-Policy"), self.mod.CSP)   # ツール自身の厳しい CSP のまま(YouTube も許さない)
        self.assertIn("script-src 'self';", self.mod.CSP)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertNotIn(b"<script", body)
        r, _ = self.req("GET", "/cut2resolve?video=C%3A%5Ca.mp4")
        self.assertEqual((r.status, r.getheader("Location")), (301, "/cut2resolve/?video=C%3A%5Ca.mp4"))
        r, _ = self.req("GET", "/cut2resolvex/api/ping")   # 前方一致の取り違えがない(入口の 404)
        self.assertEqual(r.status, 404)
        r, _ = self.req("GET", "/studio/api/ping")   # スタジオも並んで動く
        self.assertEqual(r.status, 200)

    def test_api_token_and_guards(self):
        r, body = self.req("GET", "/cut2resolve/api/ping")
        self.assertEqual(json.loads(body), {"app": "cut2resolve", "version": self.mod.SERVER_VERSION})
        r, body = self.req("GET", "/cut2resolve/api/siblings")
        self.assertEqual((r.status, json.loads(body)["tools"]["cut2resolve"]), (200, self.port))
        r, body = self.post("/cut2resolve/api/plan", {}, token=False)
        self.assertEqual((r.status, json.loads(body)["error"]), (403, "token"))
        r, _ = self.post("/cut2resolve/api/plan", {}, extra={"X-YTT-Token": "x" * len(self.srv.token)})
        self.assertEqual(r.status, 403)
        r, body = self.post("/cut2resolve/api/plan", {})
        self.assertEqual((r.status, json.loads(body)["error"]), (400, "bad_request"), body)   # 合言葉が通り、ツールの指定の検査まで届く
        r, _ = self.post("/cut2resolve/api/plan", {}, extra={"Origin": "http://localhost:8810"})
        self.assertEqual(r.status, 403)   # 単独で動くときの cut2resolve のアドレスからも受け付けない(入口のポートだけ)
        r, _ = self.req("GET", "/cut2resolve/api/siblings", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/cut2resolve/api/siblings", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, body = self.req("POST", "/cut2resolve/api/job/cancel", b"{}", {"Content-Type": "application/json"})
        self.assertEqual(r.status, 403)   # 合言葉のないものは、ツールの処理まで届かない
        r, _ = self.req("POST", "/api/cases/auto", b"{}", {"Content-Type": "application/json"})
        self.assertEqual(r.status, 403)   # 入口の API も合言葉が要る

    def test_mounted_state_runtime_and_siblings(self):
        snaps = {i: self.sup.by_id[i].snapshot() for i in ("studio", "cut2resolve")}
        self.assertEqual({i: (s["state"], s["mounted"], s["port"], s["path"]) for i, s in snaps.items()},
                         {"studio": ("running", True, self.port, "/studio/"), "cut2resolve": ("running", True, self.port, "/cut2resolve/")},
                         self.events)
        self.assertEqual(snaps["cut2resolve"]["version"], self.mod.SERVER_VERSION)
        self.assertIsNone(self.sup.by_id["cut2resolve"].proc)
        info = L.read_runtime(self.rdir, "cut2resolve")
        self.assertEqual((info["port"], info["path"]), (self.port, "/cut2resolve/"))
        want = {"tools": {"studio": self.port, "cut2resolve": self.port}, "paths": {"studio": "/studio/", "cut2resolve": "/cut2resolve/"}}
        r, body = self.req("GET", "/cut2resolve/api/siblings")
        self.assertEqual(json.loads(body), want)
        r, body = self.req("GET", "/studio/api/siblings")
        self.assertEqual(json.loads(body), want)
        from ytt import runtime
        self.assertEqual(runtime.siblings(self.rdir, "transcribe", 8775)["paths"], want["paths"])

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
        self.mod._runtime.write_runtime(self.mod.runtime_dir(), self.mod.TOOL_ID, self.port, self.mod.SERVER_VERSION, "/cut2resolve/")


@unittest.skipUnless(all(os.path.isfile(os.path.join(REPO, d, "serve.py")) for d in (STUDIO_DIR, TX_DIR)) and shutil.which("ffmpeg"),
                     "ツールのフォルダか ffmpeg が無い")
class TestTranscribeMounted(unittest.TestCase):
    """文字起こしを取り込んだ入口。認識は別プロセスのワーカー(pipeline/transcribe/worker.py)で動き、ワーカーが落ちても入口は止まらない。
    faster-whisper の無い環境でも確かめられるよう TRANSCRIBE_BACKEND=worker-fake(ワーカーの中だけ偽のモデル)で動かす。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-mount-tx-")
        for d in (STUDIO_DIR, TX_DIR):
            _copy_tool(os.path.join(REPO, d), os.path.join(cls.tmp, d))
        from ytt import layout as _layout
        _layout.copy_shared_code(cls.tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        cls.tx_dir = os.path.join(cls.tmp, TX_DIR)
        cls.studio_dir = os.path.join(cls.tmp, STUDIO_DIR)
        cls.rdir = os.path.join(cls.tmp, ".runtime")
        cls.media = os.path.join(cls.tmp, "voice.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-c:a", "aac", cls.media],
                       check=True, timeout=60)
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": cls.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(cls.tmp, "home"),
                                               "TRANSCRIBE_BACKEND": "worker-fake", "TRANSCRIBE_FAKE_DELAY": "0.01"})
        cls.env.start()
        cls.events = []
        cls.sup = L.Supervisor(cls.tmp, only=["studio", "transcribe"], log=cls.events.append, mounts=("studio", "transcribe"),
                               ports=dict(zip(("studio", "transcribe"), free_ports(2))))
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.sup.attach(cls.srv)
        threading.Thread(target=cls.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        cls.sup.start("studio")
        cls.sup.start("transcribe")
        cls.host = "127.0.0.1:%d" % cls.port
        cls.mod = sys.modules[M.MOUNTS["transcribe"]["alias"]]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.sup.unmount_all()
        cls.srv.server_close()
        cls.env.stop()
        _purge_studio_modules(cls.tx_dir, "transcribe")
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

    def post(self, path, obj, token=True):
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host}
        if token:
            h["X-YTT-Token"] = self.srv.token
        return self.req("POST", path, json.dumps(obj).encode(), h)

    def run_job(self, **req):
        r, body = self.post("/transcribe/api/transcribe", dict({"sourcePath": self.media, "model": "small"}, **req))
        self.assertEqual(r.status, 200, body)
        jid = json.loads(body)["id"]
        box = {}

        def done():
            _, b = self.req("GET", "/transcribe/api/jobs")
            box["j"] = next(j for j in json.loads(b)["jobs"] if j["id"] == jid)
            return box["j"]["state"] in ("done", "error", "cancelled")
        self.assertTrue(wait_for(done, 60), box)
        return box["j"]

    def test_mounted_state_and_page(self):
        snap = self.sup.by_id["transcribe"].snapshot()
        self.assertEqual((snap["state"], snap["mounted"], snap["path"]), ("running", True, "/transcribe/"), self.events)
        self.assertIsNone(self.sup.by_id["transcribe"].proc)
        csp = M.MOUNTS["transcribe"]["csp"]   # 取り込みの CSP(インラインのスクリプトを許さない)
        self.assertIn("script-src 'self';", csp)
        self.assertNotIn("unsafe-inline", csp)
        for asset in ("app.js", "proof.css", "app-tpl.js", "doc-kit.js", "cut.js", "pack-tab.js"):   # 案件の画面の校正のパネルが読む部品は配る
            r, _ = self.req("GET", "/transcribe/" + asset)
            self.assertEqual(r.status, 200, asset)

    def test_token_and_guards(self):
        r, body = self.post("/transcribe/api/transcribe", {"sourcePath": self.media}, token=False)
        self.assertEqual((r.status, json.loads(body)["error"]), (403, "token"))
        r, _ = self.req("GET", "/transcribe/api/tools", headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/transcribe/api/tools", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, body = self.req("GET", "/transcribe/api/tools")
        self.assertEqual(r.status, 200)
        self.assertFalse(json.loads(body)["cuda"])

    def test_transcribe_runs_in_worker_process(self):
        j = self.run_job()
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(j["segments"], 3)
        w = _worker_client.WORKER
        self.assertTrue(w.alive())
        self.assertNotEqual(w.proc.pid, os.getpid())          # 認識は入口とは別のプロセス
        for m in ("faster_whisper", "ctranslate2", "sherpa_onnx"):
            self.assertNotIn(m, sys.modules)                  # 入口のプロセスには読み込まれない

    def test_worker_crash_does_not_take_down_portal(self):
        """ワーカーが落ちても、そのジョブが失敗になるだけ。入口・スタジオはそのまま動き、次の文字起こしでワーカーを起動し直す。"""
        _worker_client.WORKER.stop()   # 次の要求で、落ちる設定のワーカーが起動する
        os.environ["TRANSCRIBE_WORKER_CRASH"] = "1"
        try:
            j = self.run_job()
        finally:
            del os.environ["TRANSCRIBE_WORKER_CRASH"]
        self.assertEqual(j["state"], "error", j)
        r, _ = self.req("GET", "/studio/api/state")
        self.assertEqual(r.status, 200)                        # スタジオは影響を受けない
        r, body = self.req("GET", "/api/status")
        self.assertEqual({t["id"]: t["state"] for t in json.loads(body)["tools"] if t["id"] != "cut2resolve"},
                         {"studio": "running", "transcribe": "running"})
        self.assertEqual(self.run_job()["state"], "done")      # 次は起動し直して成功する

    def test_runtime_siblings_and_standalone_start(self):
        port = free_ports(1)[0]
        env = dict(os.environ, YTT_CORE_DIR=self.tmp)
        r = subprocess.run([sys.executable, os.path.join(self.tx_dir, "serve.py"), str(port), "--no-open"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=dict(env, PYTHONIOENCODING="utf-8"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("入口の中ですでに起動しています", r.stdout)
        self.assertIn("/transcribe/", r.stdout)
        self.assertFalse(L.port_open(port))

    def test_zz_finish_stops_worker_and_runtime(self):
        """入口の終了(finish): 待っているジョブを取り消し、ワーカーを終わらせ、.runtime を消す(記録は書き戻す)"""
        self.assertEqual(self.run_job()["state"], "done")
        p = _worker_client.WORKER.proc
        self.mod.finish()
        self.assertIsNotNone(p.poll())
        self.assertIsNone(L.read_runtime(self.rdir, "transcribe"))
        _worker_client.WORKER.closed = False
        self.mod._runtime.write_runtime(self.mod.ed_state.runtime_path_dir(), "transcribe", self.port, self.mod.SERVER_VERSION, "/transcribe/")


@unittest.skipUnless(os.path.isfile(os.path.join(REPO, STUDIO_DIR, "serve.py")), "スタジオのフォルダが無い")
class TestMountFallbacks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-mount-fb-")
        _copy_tool(os.path.join(REPO, STUDIO_DIR), os.path.join(self.tmp, STUDIO_DIR))
        from ytt import layout as _layout
        _layout.copy_shared_code(self.tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        self.rdir = os.path.join(self.tmp, ".runtime")
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.rdir, "STUDIO_FAKE": "1", "STUDIO_HOME": os.path.join(self.tmp, "home")})
        self.env.start()
        self.events = []
        self.studio_port = free_ports(1)[0]
        self.sup = L.Supervisor(self.tmp, only=["studio"], log=self.events.append, mounts=("studio",), ports={"studio": self.studio_port},
                                poll=0.2, stop_timeout=5)
        self.srv, self.port = L.make_server(0, self.sup)
        self.sup.attach(self.srv)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
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
        _purge_studio_modules(os.path.join(self.tmp, STUDIO_DIR))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_external_studio_is_not_mounted(self):
        p = subprocess.Popen([sys.executable, os.path.join(self.tmp, STUDIO_DIR, "serve.py"), str(self.studio_port), "--no-open"],
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
        fake = types.ModuleType("startup")
        fake.__file__ = os.path.join(REPO, "elsewhere", "startup.py")
        with mock.patch.dict(sys.modules, {"startup": fake}):
            self.sup.start("studio")
        self.sup.start_monitor()
        self.assertTrue(any("取り込めませんでした" in e for e in self.events), self.events)
        self.assertTrue(wait_for(lambda: self.sup.by_id["studio"].snapshot()["state"] == "running", 40), self.events)
        snap = self.sup.by_id["studio"].snapshot()
        self.assertEqual((snap["mounted"], snap["port"], snap["path"]), (False, self.studio_port, "/"))
        self.assertIsNotNone(self.sup.by_id["studio"].proc)


if __name__ == "__main__":
    unittest.main()
