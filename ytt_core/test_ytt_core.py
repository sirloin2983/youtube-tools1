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
from ytt_core import fsio, httpsec, runtime, schemas, tools  # noqa: E402


def locked(winerror=32):
    e = PermissionError(13, "in use", "x")
    e.winerror = winerror
    return e


class PingServer:
    """/api/ping に app で答える小さなサーバー(hang=True なら答えるまで2秒待つ)。"""

    def __init__(self, app, hang=False, status=200, body=None):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if hang:
                    time.sleep(2)
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

    def test_cut2resolve_keeps_same_tool_ids(self):
        """cut2resolve は統合の対象外で自分の写しを持つ。ツールID と app の対応がずれていないことだけ確かめる"""
        path = os.path.join(REPO, "cut2resolve", "serve.py")
        if not os.path.isfile(path):
            self.skipTest("cut2resolve が無い")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TOOL_APPS" for t in node.targets):
                found = ast.literal_eval(node.value)
        self.assertEqual(found, runtime.TOOL_APPS)


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


if __name__ == "__main__":
    unittest.main()
