# -*- coding: utf-8 -*-
"""ytt_core のテスト。  python -m unittest ytt_core/test_ytt_core.py -v
ネットワークは 127.0.0.1 の空きポートだけを使う。"""
import ast
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from ytt_core import datadir, fsio, httpsec, jobs, runtime, schemas, tools, txindex  # noqa: E402


def locked(winerror=32):
    e = PermissionError(13, "in use", "x")
    e.winerror = winerror
    return e


class PingServer:
    """/api/ping に app で答える小さなサーバー(hang=True なら答えるまで2秒待つ)。"""

    def __init__(self, app, hang=False, status=200, body=None, routes=None):
        """routes: {"/studio/api/ping": "clip-studio", ...} を渡すと、その場所だけ答える(統合サーバーの模擬)"""
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if hang:
                    time.sleep(2)
                if routes is not None:
                    who = routes.get(self.path)
                    data = json.dumps({"app": who, "version": "9"}).encode() if who else b"{}"
                    self.send_response(200 if who else 404)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = body if body is not None else json.dumps({"app": app, "version": "1.2.3"}).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def dead_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestFsio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_atomic_write_and_no_temp_left(self):
        p = os.path.join(self.tmp, "sub", "a.json")
        fsio.atomic_write(p, b"one")
        fsio.atomic_write(p, b"two")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"two")
        self.assertEqual(os.listdir(os.path.dirname(p)), ["a.json"])

    def test_windows_lock_is_retried_then_succeeds(self):
        p = os.path.join(self.tmp, "a.json")
        real, calls = os.replace, []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) < 3:
                raise locked()
            real(src, dst)
        with mock.patch.object(fsio.os, "replace", side_effect=flaky), mock.patch.object(fsio.time, "sleep") as sl:
            fsio.atomic_write(p, b"x")
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sl.call_args_list], [0.1, 0.2])

    def test_permanent_lock_keeps_original(self):
        p = os.path.join(self.tmp, "a.json")
        fsio.atomic_write(p, b"original")
        with mock.patch.object(fsio.os, "replace", side_effect=locked(5)) as rep, mock.patch.object(fsio.time, "sleep"):
            with self.assertRaises(PermissionError):
                fsio.atomic_write(p, b"changed")
        self.assertEqual(rep.call_count, fsio.REPLACE_ATTEMPTS)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"original")
        self.assertEqual(os.listdir(self.tmp), ["a.json"])

    def test_other_permission_errors_are_not_retried(self):
        for err in (PermissionError(), locked(1314)):
            with mock.patch.object(fsio.os, "replace", side_effect=err) as rep:
                with self.assertRaises(PermissionError):
                    fsio.replace_retry("a", "b")
            self.assertEqual(rep.call_count, 1)

    def test_fsync_required(self):
        p = os.path.join(self.tmp, "a.json")
        with mock.patch.object(fsio.os, "fsync", side_effect=OSError("no fsync")):
            fsio.atomic_write(p, b"ok")   # 既定は続ける
            with self.assertRaises(OSError):
                fsio.atomic_write(p, b"strict", fsync_required=True)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"ok")
        self.assertEqual(os.listdir(self.tmp), ["a.json"])

    def test_cleanup_failure_does_not_hide_error(self):
        original = PermissionError("replace failed")
        with mock.patch.object(fsio.os, "replace", side_effect=original), mock.patch.object(fsio.os, "unlink", side_effect=OSError("x")):
            with self.assertRaises(PermissionError) as cm:
                fsio.atomic_write(os.path.join(self.tmp, "a.json"), b"d")
        self.assertIs(cm.exception, original)

    def test_create_new_never_overwrites(self):
        p = os.path.join(self.tmp, "a.srt")
        self.assertTrue(fsio.create_new(p, b"first"))
        self.assertFalse(fsio.create_new(p, b"second"))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"first")
        with mock.patch.object(fsio.os, "link", side_effect=OSError("no hardlink")):   # exFAT など
            q = os.path.join(self.tmp, "b.srt")
            self.assertTrue(fsio.create_new(q, b"1"))
            self.assertFalse(fsio.create_new(q, b"2"))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["a.srt", "b.srt"])

    def test_read_json_file_limits(self):
        p = os.path.join(self.tmp, "a.json")
        with open(p, "wb") as f:
            f.write(b'\xef\xbb\xbf{"a": 1}')
        self.assertEqual(fsio.read_json_file(p, 100), {"a": 1})
        with open(p, "wb") as f:
            f.write(b'{"a": NaN}')
        with self.assertRaises(ValueError):
            fsio.read_json_file(p, 100)
        with open(p, "wb") as f:
            f.write(b"[" + b"1," * 100 + b"1]")
        with self.assertRaises(ValueError):
            fsio.read_json_file(p, 50)

    def test_write_json_is_utf8_without_bom(self):
        p = os.path.join(self.tmp, "a.json")
        fsio.write_json(p, {"名前": "動画"})
        with open(p, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("動画".encode("utf-8"), raw)

    def test_is_network_path(self):
        for p in ("\\\\host\\share\\x.mp4", "//host/x.mp4", "\\\\?\\UNC\\host\\x"):
            self.assertTrue(fsio.is_network_path(p), p)
        for p in ("C:\\x.mp4", "/home/x.mp4", "Z:/x.mp4", "", None):
            self.assertFalse(fsio.is_network_path(p), p)


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def server(self, app, **kw):
        s = PingServer(app, **kw)
        self.servers.append(s)
        return s

    def put(self, tool, obj, raw=None):
        with open(os.path.join(self.dir, tool + ".json"), "wb") as f:
            f.write(raw if raw is not None else json.dumps(obj).encode())

    def test_runtime_dir(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YTT_RUNTIME_DIR", None)
            self.assertEqual(runtime.runtime_dir("/a/b/clip-studio"), os.path.join(os.path.abspath("/a/b"), ".runtime"))
            os.environ["YTT_RUNTIME_DIR"] = "rel"
            self.assertEqual(runtime.runtime_dir("/a/b/clip-studio"), os.path.abspath("rel"))

    def test_write_read_remove_only_own(self):
        p = runtime.write_runtime(self.dir, "studio", 8801, "0.2.0")
        info = runtime.read_runtime(self.dir, "studio")
        self.assertEqual((info["port"], info["version"], info["pid"]), (8801, "0.2.0", os.getpid()))
        self.assertFalse(runtime.remove_runtime(self.dir, "studio", 8802))   # 別のポート
        self.put("studio", {"tool": "studio", "port": 8801, "pid": os.getpid() + 1})
        self.assertFalse(runtime.remove_runtime(self.dir, "studio", 8801))   # 別のプロセス
        runtime.write_runtime(self.dir, "studio", 8801, "0.2.0")
        self.assertTrue(runtime.remove_runtime(self.dir, "studio", 8801))
        self.assertFalse(os.path.exists(p))

    def test_ids_and_unwritable(self):
        for bad in ("../evil", "Studio", "", "a/b", None, "x" * 40):
            self.assertIsNone(runtime.write_runtime(self.dir, bad, 8800, "v"), bad)
            self.assertIsNone(runtime.read_runtime_port(self.dir, bad), bad)
        self.assertIsNotNone(runtime.write_runtime(self.dir, "portal", 8700, "v"))   # 入口も書ける
        self.assertIsNone(runtime.write_runtime(os.path.join(self.dir, "x\0y"), "studio", 8800, "v"))

    def test_read_validation(self):
        cases = [({"tool": "transcribe", "port": 8775}, 8775), ({"tool": "studio", "port": 8775}, None),
                 ({"tool": "transcribe", "port": "8775"}, None), ({"tool": "transcribe", "port": True}, None),
                 ({"tool": "transcribe", "port": 80}, None), ({"tool": "transcribe", "port": 70000}, None), ([1], None)]
        for obj, want in cases:
            self.put("transcribe", obj)
            self.assertEqual(runtime.read_runtime_port(self.dir, "transcribe"), want, obj)
        self.put("transcribe", None, b'\xef\xbb\xbf{"tool": "transcribe", "port": 1024}')
        self.assertEqual(runtime.read_runtime_port(self.dir, "transcribe"), 1024)
        self.put("transcribe", None, b'{"tool": "transcribe", "port": 8775, "x": "' + b"a" * 5000 + b'"}')
        self.assertIsNone(runtime.read_runtime_port(self.dir, "transcribe"))

    def test_valid_port(self):
        for ok in (1024, 8800, 65535):
            self.assertTrue(runtime.valid_port(ok))
        for bad in (0, 80, 1023, 65536, True, 8.5, "8800", None, -1):
            self.assertFalse(runtime.valid_port(bad), bad)

    def test_ping(self):
        s = self.server("clip-studio")
        self.assertEqual(runtime.ping(s.port), {"app": "clip-studio", "version": "1.2.3"})
        self.assertEqual(runtime.ping_app(s.port), "clip-studio")
        self.assertIsNone(runtime.ping(dead_port()))
        self.assertIsNone(runtime.ping(self.server("x", status=500).port))
        self.assertIsNone(runtime.ping(self.server("x", body=b"not json").port))
        self.assertIsNone(runtime.ping(self.server("x", body=b'{"app": 1}').port))

    def test_ping_bad_ports_do_not_connect(self):
        with mock.patch.object(runtime.http.client, "HTTPConnection") as conn:
            for p in (0, 80, 70000, True, "8800", None):
                self.assertIsNone(runtime.ping(p))
            conn.assert_not_called()

    def test_ping_ignores_proxy_env(self):
        s = self.server("transcribe-tool")
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:%d" % dead_port(), "HTTP_PROXY": "http://127.0.0.1:1", "no_proxy": "", "NO_PROXY": ""}):
            self.assertEqual(runtime.ping_app(s.port), "transcribe-tool")

    def test_port_open_is_silent(self):
        s = self.server("clip-studio")
        self.assertTrue(runtime.port_open(s.port))
        self.assertFalse(runtime.port_open(dead_port()))
        self.assertFalse(runtime.port_open(80))   # 範囲外のポートにはつながない

    def test_siblings(self):
        tt = self.server("transcribe-tool")
        wrong = self.server("something-else")
        self.put("transcribe", {"tool": "transcribe", "port": tt.port})
        self.put("cut2resolve", {"tool": "cut2resolve", "port": wrong.port})   # app が違う → 入れない
        self.put("evil", {"tool": "evil", "port": tt.port})                   # 知らない ID は読まない
        self.assertEqual(runtime.siblings(self.dir, "studio", 8800), {"tools": {"studio": 8800, "transcribe": tt.port}})
        self.assertEqual(runtime.siblings(self.dir, None, None), {"tools": {"transcribe": tt.port}})
        self.assertEqual(runtime.siblings(os.path.join(self.dir, "none"), "studio", 8800), {"tools": {"studio": 8800}})

    def test_siblings_does_not_wait_for_hung_server(self):
        hung = self.server("transcribe-tool", hang=True)
        self.put("transcribe", {"tool": "transcribe", "port": hung.port})
        t0 = time.monotonic()
        r = runtime.siblings(self.dir, "studio", 8800, timeout=0.3)
        self.assertLess(time.monotonic() - t0, 1.2)
        self.assertEqual(r, {"tools": {"studio": 8800}})

    def test_paths_for_mounted_tools(self):
        """統合サーバーに取り込まれたツールは、同じポートの /studio/ などにいる。記録・問い合わせ・siblings が場所を扱える"""
        unified = self.server(None, routes={"/api/ping": "ytt-launcher", "/studio/api/ping": "clip-studio"})
        p = runtime.write_runtime(self.dir, "studio", unified.port, "0.3.0", path="/studio/")
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["path"], "/studio/")
        self.assertEqual(runtime.read_runtime(self.dir, "studio")["path"], "/studio/")
        self.assertEqual(runtime.ping_app(unified.port), "ytt-launcher")
        self.assertEqual(runtime.ping_app(unified.port, path="/studio/"), "clip-studio")
        tt = self.server("transcribe-tool")
        self.put("transcribe", {"tool": "transcribe", "port": tt.port})
        r = runtime.siblings(self.dir, "transcribe", tt.port)
        self.assertEqual(r, {"tools": {"studio": unified.port, "transcribe": tt.port}, "paths": {"studio": "/studio/"}})
        # 取り込まれたツール自身から見ても(自分の場所を付ける)
        r = runtime.siblings(self.dir, "studio", unified.port, self_path="/studio/")
        self.assertEqual(r, {"tools": {"studio": unified.port, "transcribe": tt.port}, "paths": {"studio": "/studio/"}})
        # 同じポートの別の場所にいる別のツールは、ポートが同じでも問い合わせる(ポートだけで自分と見なさない)
        self.put("cut2resolve", {"tool": "cut2resolve", "port": unified.port, "path": "/cut/"})
        r = runtime.siblings(self.dir, "studio", unified.port, self_path="/studio/")
        self.assertNotIn("cut2resolve", r["tools"])   # /cut/api/ping は答えない
        self.put("cut2resolve", {"tool": "cut2resolve", "port": unified.port, "path": "/studio/"})
        self.assertNotIn("cut2resolve", runtime.siblings(self.dir, "studio", unified.port, self_path="/studio/")["tools"])

    def test_path_validation(self):
        for bad in ("studio/", "/studio", "//evil.example/", "/../", "/Studio/", "/a/b/", "http://x/", None, 1, "/" + "a" * 40 + "/"):
            self.assertFalse(runtime.valid_path(bad), bad)
            self.assertIsNone(runtime.write_runtime(self.dir, "studio", 8800, "v", path=bad), bad)
            self.assertIsNone(runtime.ping(8800, path=bad), bad)
        for ok in ("/", "/studio/", "/cut2resolve/"):
            self.assertTrue(runtime.valid_path(ok), ok)
        self.put("studio", {"tool": "studio", "port": 8800, "path": "//evil.example/"})
        self.assertEqual(runtime.read_runtime(self.dir, "studio")["path"], "/")   # 形の違う場所は使わない
        runtime.write_runtime(self.dir, "studio", 8800, "v")
        with open(os.path.join(self.dir, "studio.json"), encoding="utf-8") as f:
            self.assertNotIn("path", json.load(f))   # 直下のときは書かない(以前の形のまま)

    def test_cut2resolve_uses_ytt_core(self):
        """cut2resolve も 2026-09-26 から ytt_core.runtime を使う(自分の写しを持たない)。TOOL_APPS を自分で書き直していないこと"""
        path = os.path.join(REPO, "cut2resolve", "serve.py")
        if not os.path.isfile(path):
            self.skipTest("cut2resolve が無い")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = [node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TOOL_APPS" for t in node.targets)]
        self.assertEqual([ast.unparse(v) for v in found], ["_runtime.TOOL_APPS"])


class TestSchemas(unittest.TestCase):
    def test_build_and_validate_clip(self):
        d = schemas.build_clip(os.path.join("x", "動画_0012.mp4"), 45.2345,
                               {"kind": "youtube", "videoId": "abcdefghijk", "title": "配信", "path": "/secret"},
                               (1234.5678, 1279.7), {"id": "m1", "label": "見どころ", "status": "exported", "src": "evil"},
                               {"mode": "fast", "actualStart": 1231.0}, {"name": "clip-studio", "version": "0.2.0"})
        self.assertEqual(d["schema"], schemas.CLIP_SCHEMA)
        self.assertEqual(d["media"]["durationSec"], 45.234)
        self.assertEqual(d["range"], {"start": 1234.568, "end": 1279.7})
        self.assertIsNone(d["source"]["path"])            # youtube のときはパスを入れない
        self.assertEqual(d["mark"]["src"], "manual")      # 知らない src は manual に
        self.assertEqual(d["tool"], {"name": "clip-studio", "version": "0.2.0"})
        clip, warn = schemas.validate_clip(json.loads(json.dumps(d)))
        self.assertIsNone(warn)
        self.assertEqual(schemas.clip_offset(clip), 1231.0)
        clip["range"]["start"] = 0
        self.assertEqual(d["range"]["start"], 1234.568)   # 複製なので元に響かない

    def test_validate_rejects(self):
        base = {"schema": schemas.CLIP_SCHEMA, "range": {"start": 10, "end": 20}}
        self.assertIsNotNone(schemas.validate_clip(base)[0])
        bad = [None, [], dict(base, schema="youtube-tools-clip/v2"), dict(base, schema="x"), dict(base, range={"start": 20, "end": 10}),
               dict(base, range={"start": -1, "end": 10}), dict(base, range={"start": True, "end": 10}), dict(base, media="x"),
               dict(base, export={"actualStart": -3}), dict(base, range={"start": float("nan"), "end": 10})]
        for obj in bad:
            self.assertIsNone(schemas.validate_clip(obj)[0], obj)
        self.assertIn("未対応の版", schemas.validate_clip(dict(base, schema="youtube-tools-clip/v2"))[1])

    def test_paths_and_load(self):
        self.assertEqual(schemas.clip_path_for(os.path.join("x", "a.b.mp4")), os.path.join("x", "a.b.clip.json"))
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "a.clip.json")
            self.assertIsNone(schemas.load_clip_file(p)[0])
            with open(p, "w") as f:
                f.write(" " * (schemas.MAX_CLIP_BYTES + 1))
            self.assertIn("大きすぎ", schemas.load_clip_file(p)[1])


class TestHttpsec(unittest.TestCase):
    def test_checks(self):
        allowed = httpsec.allowed_hosts(8800)
        self.assertTrue(httpsec.host_ok({"Host": "127.0.0.1:8800"}, allowed))
        self.assertTrue(httpsec.host_ok({"Host": "localhost:8800"}, allowed))
        for h in ("evil.example:8800", "127.0.0.1:8801", "", None):
            self.assertFalse(httpsec.host_ok({"Host": h} if h is not None else {}, allowed), h)
        self.assertTrue(httpsec.origin_ok({}, allowed))
        self.assertTrue(httpsec.origin_ok({"Origin": "http://localhost:8800"}, allowed))
        for o in ("http://evil.example", "http://localhost:8801", "https://localhost:8800", "null", "localhost:8800"):
            self.assertFalse(httpsec.origin_ok({"Origin": o}, allowed), o)
        for s in (None, "same-origin", "none"):
            self.assertTrue(httpsec.fetch_site_ok({"Sec-Fetch-Site": s} if s else {}), s)
        for s in ("same-site", "cross-site"):
            self.assertFalse(httpsec.fetch_site_ok({"Sec-Fetch-Site": s}), s)
        nav = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        self.assertTrue(httpsec.navigation_ok(nav, "/"))
        self.assertTrue(httpsec.navigation_ok({"Sec-Fetch-Mode": "navigate"}, "/index.html"))
        self.assertFalse(httpsec.navigation_ok(nav, "/api/state"))
        self.assertFalse(httpsec.navigation_ok(dict(nav, **{"Sec-Fetch-Dest": "iframe"}), "/"))
        self.assertFalse(httpsec.navigation_ok({"Sec-Fetch-Mode": "cors"}, "/"))
        self.assertEqual(httpsec.PAGE_HEADERS["X-Frame-Options"], "DENY")


class TestTools(unittest.TestCase):
    def test_find_tool_env_override(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            fake = f.name
        try:
            with mock.patch.dict(os.environ, {"X_FFMPEG": fake}):
                self.assertEqual(tools.find_tool("ffmpeg", "X_FFMPEG"), fake)
            with mock.patch.dict(os.environ, {"X_FFMPEG": fake + ".missing"}), mock.patch.object(tools.shutil, "which", return_value="/p/ffmpeg"):
                self.assertEqual(tools.find_tool("ffmpeg", "X_FFMPEG"), "/p/ffmpeg")
        finally:
            os.unlink(fake)


class TestDatadir(unittest.TestCase):
    """作業データの置き場所と、以前の場所からのコピー(段階4)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.legacy = os.path.join(self.tmp, "repo", "transcribe-tool")
        os.makedirs(os.path.join(self.legacy, "transcripts", ".hist", "a"))
        for rel, body in (("transcripts/a.json", "{}"), ("transcripts/.hist/a/1.json", "old"), ("settings.json", '{"x": 1}')):
            with open(os.path.join(self.legacy, rel), "w", encoding="utf-8") as f:
                f.write(body)
        self.env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        self.new = os.path.join(self.tmp, "data", "transcribe")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_root(self):
        self.assertEqual(datadir.data_root({"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}, "win32"),
                         os.path.join(r"C:\Users\u\AppData\Local", "youtube-tools"))
        self.assertEqual(datadir.data_root({}, "win32", "/h"), os.path.join("/h", "AppData", "Local", "youtube-tools"))
        self.assertEqual(datadir.data_root({}, "linux", "/h"), os.path.join("/h", ".local", "share", "youtube-tools"))
        self.assertEqual(datadir.data_root({"XDG_DATA_HOME": "/x"}, "linux", "/h"), os.path.join("/x", "youtube-tools"))
        self.assertEqual(datadir.data_root({}, "darwin", "/h"), os.path.join("/h", "Library", "Application Support", "youtube-tools"))
        self.assertIsNone(datadir.data_root({"YTT_DATA_DIR": "InPlace"}, "win32"))
        self.assertEqual(datadir.tool_dir("studio", "/r/clip-studio", {"YTT_DATA_DIR": "inplace"}), os.path.abspath("/r/clip-studio"))

    def test_copy_once_and_keep_original(self):
        logs = []
        r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json", "dataset"], self.env, logs.append)
        self.assertEqual((r["state"], r["dir"], r["migrated"]), ("migrated", self.new, ["transcripts", "settings.json"]))
        with open(os.path.join(self.new, "transcripts", ".hist", "a", "1.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "old")                                   # 隠しフォルダの中も写す
        self.assertTrue(os.path.isfile(os.path.join(self.legacy, "settings.json")))   # 元は消さない
        self.assertTrue(logs and "消しません" in logs[0])
        self.assertEqual(datadir.read_marker(self.new)["items"], ["transcripts", "settings.json"])
        # 2回目は写さない(以前の場所が変わっても、新しい場所が正)
        with open(os.path.join(self.legacy, "settings.json"), "w", encoding="utf-8") as f:
            f.write("changed")
        with open(os.path.join(self.new, "settings.json"), "w", encoding="utf-8") as f:
            f.write("new")
        self.assertEqual(datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)["state"], "done")
        with open(os.path.join(self.new, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def test_existing_items_are_not_overwritten(self):
        os.makedirs(self.new)
        with open(os.path.join(self.new, "settings.json"), "w", encoding="utf-8") as f:
            f.write("mine")
        r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)
        self.assertEqual(r["migrated"], ["transcripts"])
        with open(os.path.join(self.new, "settings.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "mine")

    def test_nothing_to_copy(self):
        r = datadir.prepare("studio", os.path.join(self.tmp, "empty"), ["data.json"], self.env)
        self.assertEqual((r["state"], r["dir"]), ("new", os.path.join(self.tmp, "data", "studio")))

    def test_inplace(self):
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], {"YTT_DATA_DIR": "inplace"})
        self.assertEqual((r["state"], r["dir"]), ("inplace", os.path.abspath(self.legacy)))
        self.assertFalse(os.path.exists(self.new))

    def test_not_enough_space_keeps_legacy(self):
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env, free_bytes=1024)
        self.assertEqual((r["state"], r["dir"]), ("failed", os.path.abspath(self.legacy)))
        self.assertIn("空き容量", r["warnings"][0])
        self.assertFalse(os.path.exists(os.path.join(self.new, "transcripts")))
        self.assertIsNone(datadir.read_marker(self.new))   # 次の起動でもう一度試す

    def test_copy_failure_keeps_legacy_and_removes_partial(self):
        real = datadir._copy_item
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if src.endswith("settings.json"):
                raise OSError("disk error")
            return real(src, dst)
        with mock.patch.object(datadir, "_copy_item", flaky):
            r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)
        self.assertEqual((r["state"], r["dir"]), ("failed", os.path.abspath(self.legacy)))
        self.assertIn("disk error", r["warnings"][0])
        self.assertFalse(os.path.exists(os.path.join(self.new, "transcripts")))   # 途中まで写した分も消す(古くなるため)
        self.assertEqual(os.listdir(self.new), [])
        r = datadir.prepare("transcribe", self.legacy, ["transcripts", "settings.json"], self.env)   # 次の起動で写し直す
        self.assertEqual(r["state"], "migrated")

    def test_size_mismatch_is_a_failure_and_leaves_no_part(self):
        real_size = datadir._size
        with mock.patch.object(datadir, "_size", side_effect=lambda p: (0, 0) if datadir.PART in p else real_size(p)):
            r = datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertEqual(r["state"], "failed")
        self.assertEqual([n for n in os.listdir(self.new) if datadir.PART in n], [])

    def test_leftover_part_is_cleaned(self):
        os.makedirs(os.path.join(self.new, "transcripts" + datadir.PART + "123"))
        r = datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertEqual(r["state"], "migrated")
        self.assertEqual(sorted(os.listdir(self.new)), [datadir.MARKER, "transcripts"])

    @unittest.skipIf(os.name == "nt", "シンボリックリンクの作成に権限が要る")
    def test_links_are_not_followed(self):
        outside = os.path.join(self.tmp, "secret.txt")
        with open(outside, "w") as f:
            f.write("s")
        os.symlink(outside, os.path.join(self.legacy, "transcripts", "link.json"))
        datadir.prepare("transcribe", self.legacy, ["transcripts"], self.env)
        self.assertFalse(os.path.lexists(os.path.join(self.new, "transcripts", "link.json")))

    def test_every_server_test_isolates_data_dir(self):
        """サーバー(serve.py・入口)を動かすテストは、必ず YTT_DATA_DIR を指定する。忘れると、移し済みの PC で
        テストのサーバーが本物の作業データ(AppData\\youtube-tools)を読み書きしてしまう"""
        import glob
        import re
        bad = []
        for f in sorted(glob.glob(os.path.join(REPO, "*", "test_*.py")) + glob.glob(os.path.join(REPO, "*", "e2e_*.py"))):
            with open(f, encoding="utf-8") as fp:
                src = fp.read()
            if re.search(r"\bserve\b|launch\.py|import launch|import mount", src) and "YTT_DATA_DIR" not in src:
                bad.append(os.path.relpath(f, REPO))
        self.assertEqual(bad, [])


class TestHeavySlots(unittest.TestCase):
    """重い処理の同時実行数の上限(ytt_core.jobs)"""

    def test_limit_from_env(self):
        self.assertEqual(jobs.limit_from_env({}), 2)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "3"}), 3)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "0"}), 1)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "99"}), jobs.MAX_LIMIT)
        self.assertEqual(jobs.limit_from_env({"YTT_MAX_HEAVY_JOBS": "x"}), 2)

    def test_limit_and_fifo(self):
        s = jobs.HeavySlots(1)
        order, waits = [], []
        first = s.acquire("studio", "a")
        started = threading.Event()

        def run(name):
            with s.slot(name, name, on_wait=lambda: waits.append(name), poll=0.01) as ok:
                order.append((name, ok))
        t1 = threading.Thread(target=run, args=("transcribe",))
        t1.start()
        time.sleep(0.1)
        t2 = threading.Thread(target=run, args=("cut2resolve",))
        t2.start()
        time.sleep(0.1)
        snap = s.snapshot()
        self.assertEqual([a["tool"] for a in snap["active"]], ["studio"])
        self.assertEqual([w["tool"] for w in snap["waiting"]], ["transcribe", "cut2resolve"])   # 先に来た順
        self.assertEqual(order, [])
        s.release(first)
        t1.join(5)
        t2.join(5)
        self.assertEqual(order, [("transcribe", True), ("cut2resolve", True)])
        self.assertEqual(sorted(waits), ["cut2resolve", "transcribe"])   # 待ち始めに1回ずつ
        self.assertEqual(s.snapshot(), {"limit": 1, "active": [], "waiting": []})
        started.set()

    def test_two_at_once_by_default(self):
        s = jobs.HeavySlots(2)
        a, b = s.acquire("x"), s.acquire("y")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        flag = []
        self.assertIsNone(s.acquire("z", cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 3つ目は待つ → 取り消し
        s.release(a)
        self.assertIsNotNone(s.acquire("z"))

    def test_cancel_while_waiting_frees_the_queue(self):
        s = jobs.HeavySlots(1)
        held = s.acquire("studio")
        cancel = threading.Event()
        res = []
        t = threading.Thread(target=lambda: res.append(s.acquire("transcribe", cancelled=cancel.is_set, poll=0.01)))
        t.start()
        time.sleep(0.05)
        cancel.set()
        t.join(5)
        self.assertEqual(res, [None])
        s.release(held)
        self.assertIsNotNone(s.acquire("cut2resolve", poll=0.01))   # 取り消した人が列を塞がない

    def test_exception_releases(self):
        s = jobs.HeavySlots(1)
        with self.assertRaises(RuntimeError):
            with s.slot("x"):
                raise RuntimeError("boom")
        self.assertEqual(s.snapshot()["active"], [])


class TestTxIndex(unittest.TestCase):
    """文字起こしの文書を他のツールから読む(入口の案件・スタジオのセリフの表示で共通の紐づけの規則)"""
    VID = "abcdefghijk"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.dir)
        self.clip = os.path.join(self.tmp, "exports", "01_a.mp4")
        os.makedirs(os.path.dirname(self.clip))
        with open(self.clip, "wb") as f:
            f.write(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pack_info(self):
        """パックの有無の規則(入口の案件・文字起こしの一覧で共通): 切り抜きの隣の <名前>_pack に cut-plan.json があれば「あり」"""
        from ytt_core import txindex
        self.assertIsNone(txindex.pack_info(self.clip))
        self.assertIsNone(txindex.pack_info(""))
        d = os.path.join(os.path.dirname(self.clip), "01_a_pack")
        os.makedirs(d)
        self.assertIsNone(txindex.pack_info(self.clip))   # フォルダだけでは「あり」にしない(作りかけ)
        with open(os.path.join(d, "cut-plan.json"), "w") as f:
            f.write("{}")
        p = txindex.pack_info(self.clip)
        self.assertEqual((p["dir"], p["textplus"]), (d, False))
        self.assertGreater(p["updatedAt"], 0)
        with open(os.path.join(d, "textplus-import.json"), "w") as f:
            f.write("{}")
        self.assertTrue(txindex.pack_info(self.clip)["textplus"])
        self.assertFalse(txindex.is_pack_dir(d))   # 以前のパックでも、cut2resolve の書いた cut-plan.json でなければ「フォルダを開く」は許さない
        with open(os.path.join(d, "cut-plan.json"), "w") as f:
            json.dump({"schema": "youtube-tools-cut-plan/v1", "tool": {"name": "cut2resolve"}}, f)
        self.assertTrue(txindex.is_pack_dir(d))

    def test_pack_record(self):
        """2026-09-26(④)から: パックに cut-plan.json を置かず、cut2resolve の作業データ packs/ の記録で「パック済み」を決める"""
        import json as _json
        from ytt_core import txindex
        env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}
        d = txindex.pack_dir(self.clip)
        os.makedirs(os.path.join(d, "media"))
        rec_dir = txindex.packs_dir(env)
        self.assertEqual(rec_dir, os.path.join(self.tmp, "data", "cut2resolve", "packs"))
        os.makedirs(rec_dir)
        rec = {"schema": txindex.PACK_RECORD_SCHEMA, "dir": d.upper() if os.name == "nt" else d, "textplus": True, "builtAt": 1790000000000,
               "files": ["create_resolve_textplus_project.lua", "media/01_a.mp4"]}
        with open(os.path.join(rec_dir, txindex.pack_key(d)), "w", encoding="utf-8") as f:
            _json.dump(rec, f)
        self.assertIsNone(txindex.pack_info(self.clip, env))                 # 記録したファイルがフォルダに無い(消した・作りかけ)
        self.assertFalse(txindex.is_pack_dir(d, env))
        with open(os.path.join(d, "media", "01_a.mp4"), "w") as f:
            f.write("x")
        self.assertEqual(txindex.pack_info(self.clip, env), {"dir": d, "textplus": True, "updatedAt": 1790000000000})
        self.assertTrue(txindex.is_pack_dir(d, env))
        self.assertIsNone(txindex.pack_info(self.clip, {"YTT_DATA_DIR": os.path.join(self.tmp, "other")}))   # 別の置き場所には無い
        for bad in ({"schema": "x"}, dict(rec, dir=os.path.join(self.tmp, "else")), dict(rec, files=["../../x"]), [1]):
            with open(os.path.join(rec_dir, txindex.pack_key(d)), "w", encoding="utf-8") as f:
                _json.dump(bad, f)
            self.assertIsNone(txindex.pack_info(self.clip, env), bad)
        self.assertNotEqual(txindex.pack_key(d), txindex.pack_key(d + "2"))

    def doc(self, tid, source="", clip=None, updated=1, segs=None, speakers=None):
        d = {"id": tid, "title": "t" + tid, "sourcePath": source, "updatedAt": updated, "speakers": speakers or [],
             "segments": segs if segs is not None else [{"id": "s1", "start": 1.0, "end": 2.5, "text": "こんにちは", "proofed": True},
                                                        {"id": "s2", "start": 3.0, "end": 4.0, "text": "切る", "cutState": "cut"}]}
        if clip:
            d["clip"] = clip
        with open(os.path.join(self.dir, tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def clipobj(self, vid=None, mid="m1", start=100.0, actual=None):
        ex = {"mode": "fast"}
        if actual is not None:
            ex["actualStart"] = actual
        return schemas.build_clip(self.clip, 30, {"kind": "youtube", "videoId": vid or self.VID}, (start, start + 30), {"id": mid}, ex, {"name": "t"})

    def test_load_parse_and_skip_broken(self):
        self.doc("aaaaaaaaaaaa", self.clip, speakers=[{"id": "S1", "name": "話者A"}],
                 segs=[{"start": 1, "end": 2, "text": "x", "speaker": "S1"}, {"start": -1, "end": 2, "text": "負"}, {"start": 3, "end": 2}, "壊れた行"])
        with open(os.path.join(self.dir, "bbbbbbbbbbbb.json"), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        with open(os.path.join(self.dir, "notatranscript.json"), "w", encoding="utf-8") as f:
            f.write("{}")   # 名前の長さが違うものは読まない
        docs = txindex.load(self.dir)
        self.assertEqual([d["id"] for d in docs], ["aaaaaaaaaaaa"])
        self.assertEqual([(s["text"], s["speaker"]) for s in docs[0]["segments"]], [("x", "話者A")])
        self.assertEqual(txindex.load(os.path.join(self.tmp, "無い")), [])

    def test_cache_rereads_changed_files_and_forgets_removed(self):
        self.doc("aaaaaaaaaaaa", self.clip)
        first = txindex.load(self.dir)[0]
        self.assertIs(txindex.load(self.dir)[0], first)   # 変わっていなければ読み直さない
        self.doc("aaaaaaaaaaaa", self.clip, segs=[{"start": 0, "end": 1, "text": "新しい行が長くなった"}])
        p = os.path.join(self.dir, "aaaaaaaaaaaa.json")
        os.utime(p, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
        self.assertEqual(txindex.load(self.dir)[0]["segments"][0]["text"], "新しい行が長くなった")
        os.remove(p)
        self.assertEqual(txindex.load(self.dir), [])
        self.assertFalse(any(k == p for k in txindex._cache))

    def test_match_by_path_or_clip_and_newest_wins(self):
        self.doc("aaaaaaaaaaaa", self.clip, updated=1)
        self.doc("bbbbbbbbbbbb", os.path.join(self.tmp, "moved.mp4"), clip=self.clipobj(), updated=5)   # 動画を動かしても .clip.json で
        self.doc("cccccccccccc", os.path.join(self.tmp, "moved.mp4"), clip=self.clipobj(mid="m9"), updated=9)   # 別のマーク
        docs = txindex.load(self.dir)
        best, n, ids = txindex.pick(docs, self.VID, "m1", self.clip)
        self.assertEqual((best["id"], n, sorted(ids)), ("bbbbbbbbbbbb", 2, ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]))
        self.assertEqual(txindex.pick(docs, "zzzzzzzzzzz", "m1", "")[:2], (None, 0))
        self.assertEqual(txindex.summary(best), {"id": "bbbbbbbbbbbb", "title": "tbbbbbbbbbbbb", "segments": 2, "proofed": 1, "cut": 1, "updatedAt": 5})

    def test_offset_sources(self):
        self.doc("aaaaaaaaaaaa", self.clip, clip=self.clipobj(start=100.0, actual=98.5))
        self.doc("bbbbbbbbbbbb", self.clip, clip=self.clipobj(vid="zzzzzzzzzzz", start=500.0))   # 別の配信の .clip.json は使わない
        self.doc("cccccccccccc", self.clip)
        d = {x["id"]: x for x in txindex.load(self.dir)}
        self.assertEqual(txindex.offset(d["aaaaaaaaaaaa"], self.VID, self.clip, 10), (98.5, "clip"))   # export.actualStart を優先
        self.assertEqual(txindex.offset(d["bbbbbbbbbbbb"], self.VID, self.clip, 10), (10.0, "mark"))
        self.assertEqual(txindex.offset(d["cccccccccccc"], self.VID, self.clip, 10), (10.0, "mark"))
        fsio.write_json(schemas.clip_path_for(self.clip), self.clipobj(start=200.0))   # mp4 の隣の .clip.json
        self.assertEqual(txindex.offset(d["cccccccccccc"], self.VID, self.clip, 10), (200.0, "sidecar"))
        with mock.patch.object(schemas, "load_clip_file", side_effect=AssertionError("触らない")):
            self.assertEqual(txindex.offset(d["cccccccccccc"], self.VID, r"\\server\share\a.mp4", 7), (7.0, "mark"))
        ln = txindex.lines(d["aaaaaaaaaaaa"], 98.5)
        self.assertEqual([(x["start"], x["end"], x["proofed"], x["cut"]) for x in ln], [(99.5, 101.0, True, False), (101.5, 102.5, False, True)])
        self.assertEqual(d["aaaaaaaaaaaa"]["segments"][0]["start"], 1.0)   # キャッシュの中身は変えない

    def test_folder_follows_transcribe_rules(self):
        self.assertEqual(txindex.folder("/r", {"TRANSCRIBE_DATA_DIR": "/d"}), os.path.join("/d", "transcripts"))
        self.assertEqual(txindex.folder("/r", {"YTT_DATA_DIR": "inplace"}), os.path.join(os.path.abspath("/r/transcribe-tool"), "transcripts"))
        self.assertEqual(txindex.folder("/r", {"YTT_DATA_DIR": "/x"}), os.path.join(os.path.abspath("/x"), "transcribe", "transcripts"))


if __name__ == "__main__":
    unittest.main()
