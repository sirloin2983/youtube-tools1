"""受け渡し(docs/spec/pipeline.md の 2.1・4・6)のテスト: .clip.json・.runtime/studio.json・/api/siblings。
ネットワークは 127.0.0.1 の空きポートだけを使う(他のテストと同時に走らせてもぶつからない)。 実行: python3 test_handoff.py"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ツールのフォルダ(studio/)
import common
import handoff
import serve
from pipeline.export import manifest  # noqa: E402  (common が src を sys.path に足してある。.clip.json の tool は serve が入れる)
from ytt import runtime  # noqa: E402


class FakeTool:
    """/api/ping に決まった app を返すだけのサーバー(他のツールの代わり)。hang=True なら接続を受けても何も返さない。"""

    def __init__(self, app="transcribe-tool", status=200, body=None, hang=False):
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hosts.append(self.headers.get("Host"))
                if hang:
                    time.sleep(2)
                    return
                data = body if body is not None else json.dumps({"app": app, "version": "9.9"}).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.hosts = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def dead_port():
    """いま誰も待ち受けていないポート(一度 bind して閉じる)。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class RuntimeDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rt = os.path.join(self.tmp, ".runtime")
        self.env = patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.rt})
        self.env.start()
        common.set_home(os.path.join(self.tmp, "home"))
        self.fakes = []

    def tearDown(self):
        self.env.stop()
        for f in self.fakes:
            f.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, tool, obj=None, raw=None):
        os.makedirs(self.rt, exist_ok=True)
        with open(os.path.join(self.rt, tool + ".json"), "wb") as f:
            f.write(raw if raw is not None else json.dumps(obj).encode("utf-8"))

    def fake(self, **kw):
        f = FakeTool(**kw)
        self.fakes.append(f)
        return f


class TestRuntimeFile(RuntimeDir):
    def test_runtime_dir_default_is_parent_of_tool_folder(self):
        with patch.dict(os.environ, {"YTT_RUNTIME_DIR": ""}):
            self.assertEqual(handoff.runtime_dir(), os.path.join(os.path.dirname(common.CODE_DIR), ".runtime"))
        self.assertEqual(handoff.runtime_dir(), os.path.abspath(self.rt))   # 環境変数が優先

    def test_write_and_remove_own_file(self):
        path = handoff.write_runtime("studio", 8801, "0.1.8")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["tool"], d["port"], d["version"]), ("studio", 8801, "0.1.8"))
        self.assertRegex(d["startedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")   # ISO 8601・時差付き
        self.assertEqual([n for n in os.listdir(self.rt)], ["studio.json"])   # 一時ファイルが残らない
        self.assertTrue(handoff.remove_runtime("studio", 8801))
        self.assertFalse(os.path.exists(path))

    def test_remove_keeps_file_written_by_another_process(self):
        self.put("studio", {"tool": "studio", "port": 8801, "pid": os.getpid() + 1})
        self.assertFalse(handoff.remove_runtime("studio", 8801))   # 別のプロセスのもの(pid 違い)
        self.put("studio", {"tool": "studio", "port": 8802, "pid": os.getpid()})
        self.assertFalse(handoff.remove_runtime("studio", 8801))   # 別のポートで起動し直したもの
        self.assertTrue(os.path.exists(os.path.join(self.rt, "studio.json")))

    def test_write_failure_does_not_raise(self):
        with open(os.path.join(self.tmp, "blocker"), "w") as f:
            f.write("x")
        with patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, "blocker", "sub")}):
            self.assertIsNone(handoff.write_runtime("studio", 8800, "v"))   # 書けなくても起動は続ける

    def test_unknown_tool_id_is_refused(self):
        self.assertIsNone(handoff.write_runtime("../evil", 8800, "v"))


class TestSiblings(RuntimeDir):
    def test_only_matching_apps_are_listed(self):
        tt = self.fake(app="transcribe-tool")
        wrong = self.fake(app="something-else")   # cut2resolve.json が別のアプリのポートを指している
        self.put("transcribe", {"tool": "transcribe", "port": tt.port})
        self.put("cut2resolve", {"tool": "cut2resolve", "port": wrong.port})
        r = handoff.siblings("studio", 8800)
        self.assertEqual(r, {"tools": {"studio": 8800, "transcribe": tt.port}})
        self.assertEqual(tt.hosts, ["127.0.0.1:%d" % tt.port])   # 相手の Host 検査を通る形で問い合わせる

    def test_stale_file_and_errors_are_ignored(self):
        bad_status = self.fake(app="cut2resolve", status=500)
        self.put("transcribe", {"tool": "transcribe", "port": dead_port()})   # 異常終了して残ったファイル
        self.put("cut2resolve", {"tool": "cut2resolve", "port": bad_status.port})
        self.assertEqual(handoff.siblings("studio", 8800), {"tools": {"studio": 8800}})

    def test_garbage_response_is_ignored(self):
        g = self.fake(body=b"<html>not json")
        self.put("transcribe", {"tool": "transcribe", "port": g.port})
        self.assertEqual(handoff.siblings("studio", 8800)["tools"], {"studio": 8800})

    def test_hung_tool_does_not_block_long(self):
        h = self.fake(hang=True)
        ok = self.fake(app="cut2resolve")
        self.put("transcribe", {"tool": "transcribe", "port": h.port})
        self.put("cut2resolve", {"tool": "cut2resolve", "port": ok.port})
        t0 = time.monotonic()
        r = handoff.siblings("studio", 8800)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(r["tools"], {"studio": 8800, "cut2resolve": ok.port})

    def test_no_runtime_dir(self):
        self.assertEqual(handoff.siblings("studio", 8800), {"tools": {"studio": 8800}})
        self.assertEqual(handoff.siblings(None, None), {"tools": {}})


class TestSiblingsApi(RuntimeDir):
    def setUp(self):
        super().setUp()
        serve.init(os.path.join(self.tmp, "home"))
        self.srv, self.port = serve.make_server(0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def get(self, path, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path, headers=dict({"Host": host or "127.0.0.1:%d" % self.port}, **(headers or {})))
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_api_siblings(self):
        tt = self.fake(app="transcribe-tool")
        self.put("transcribe", {"tool": "transcribe", "port": tt.port})
        st, data = self.get("/api/siblings")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(data), {"tools": {"studio": self.port, "transcribe": tt.port}})

    def test_api_siblings_is_guarded(self):
        self.assertEqual(self.get("/api/siblings", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(self.get("/api/siblings", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_studio_answers_ping_from_other_tool(self):
        # 他のツールの /api/siblings から問い合わせられたときに、スタジオとして応答する
        self.assertEqual(runtime.ping_app(self.port), "clip-studio")


class ToolIdentityTests(unittest.TestCase):
    """ツールの識別子(/api/ping の app・.clip.json の tool.name)は ytt_core.runtime.TOOL_APPS が正。写しが食い違っていない(値は互換のため固定)"""

    def test_same_as_runtime_table(self):
        self.assertEqual(runtime.TOOL_APPS["studio"], "clip-studio")
        self.assertEqual(serve.APP_ID, runtime.TOOL_APPS["studio"])
        self.assertEqual(serve.Handler.server_version, runtime.TOOL_APPS["studio"])
        self.assertEqual(manifest.TOOL["name"], runtime.TOOL_APPS["studio"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
