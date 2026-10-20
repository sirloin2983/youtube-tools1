"""/api/siblings(他のツールの .runtime を読んで返す口)のテスト。
ネットワークは 127.0.0.1 の空きポートだけを使う(他のテストと同時に走らせてもぶつからない)。 実行: python3 test_handoff.py"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "studio"))   # ツールのフォルダ(studio/)
import startup  # noqa: E402  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
from ytt import studio_env  # noqa: E402
import serve


class FakeTool:
    """/api/ping に決まった app を返すだけのサーバー(他のツールの代わり)。hang=True なら接続を受けても何も返さない。"""

    def __init__(self, app="transcribe-tool"):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                data = json.dumps({"app": app, "version": "9.9"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class RuntimeDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rt = os.path.join(self.tmp, ".runtime")
        self.env = patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.rt})
        self.env.start()
        studio_env.set_home(os.path.join(self.tmp, "home"))
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
