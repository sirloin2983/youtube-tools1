"""入口の ytt_api("deliver") の受け渡し(src/app/server.py の PortalServer.ytt_api)のテスト。deliver の本体のテストは src/human/friend/tests/test_deliver.py。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_deliver_api.py -v
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from human.friend import deliver  # noqa: E402


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def wait(dl, job, limit=10):
    end = time.time() + limit
    while time.time() < end:
        j = dl.status(job["id"])
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("終わらない: %r" % dl.status(job["id"]))


class ApiTest(unittest.TestCase):
    """入口の ytt_api("deliver") の受け渡し(HTTP の検査は test_window の api/ytt と同じ ytt_request)"""

    def test_api(self):
        from app import server
        tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, tmp, True)
        pack = os.path.join(tmp, "p_pack")
        put(os.path.join(pack, "a.mp4"))
        os.makedirs(os.path.join(tmp, "Dropbox"))

        class Fake:
            ytt_api = server.PortalServer.ytt_api
        srv = Fake()
        srv.deliveries = deliver.Deliveries(lambda: os.path.join(tmp, "Dropbox"), lambda d: d == os.path.normpath(pack))
        code, obj = srv.ytt_api("deliver", {"op": "start", "dir": os.path.join(tmp, "nope"), "title": "t"})
        self.assertEqual(code, 400)
        code, obj = srv.ytt_api("deliver", {"op": "start", "dir": pack, "title": "t"})
        self.assertEqual(code, 200)
        j = wait(srv.deliveries, obj["job"])
        self.assertEqual(j["state"], "done")
        code, obj = srv.ytt_api("deliver", {"op": "status", "job": j["id"]})
        self.assertEqual((code, obj["job"]["state"]), (200, "done"))
        code, _ = srv.ytt_api("deliver", {"op": "status", "job": "nope"})
        self.assertEqual(code, 404)


class AutoSendApiTest(unittest.TestCase):
    """D-SEND: /api/autorun/<start|start-new|estimate> の autoSend の受け渡し(既定 = 無ければ None = autorun が mode full ならオン)と、
    受付の見回りの終わりの送り直し(PortalServer.flush_sends)"""

    def setUp(self):
        from app import server
        import types
        calls = self.calls = []

        class AR:
            folder = "D:/Dropbox/切り抜き依頼"

            def send_folder(self):
                return self.folder

            def start(self, *a, **k):
                calls.append(("start", a, k))
                return {"id": "r1"}

            def start_new(self, *a, **k):
                calls.append(("start_new", a, k))
                return {"runs": [], "skipped": []}

            def start_docs(self, *a, **k):
                calls.append(("start_docs", a, k))
                return {"runs": [], "skipped": []}

            def estimate(self, *a, **k):
                calls.append(("estimate", a, k))
                return {"steps": []}

            def pools(self):
                return {"k": {}}

            def flush_pools(self, is_done):
                calls.append(("flush", is_done({})))
                return 2
        self.ar = AR()

        class H:
            _post_autorun = server.PortalHandler._post_autorun

            def _json(self, code, obj):
                self.out = (code, obj)

            def _fail(self, code, err, msg):
                self.out = (code, {"error": err, "message": msg})
        self.h = H()
        self.h.server = types.SimpleNamespace(autorun=self.ar)
        self.server = server

    def post(self, op, body):
        self.h._post_autorun("/api/autorun/" + op, body)
        return self.calls[-1]

    def test_auto_send_passes_through(self):
        self.assertIsNone(self.post("start", {"id": "abcdefghijk", "mode": "full"})[2]["auto_send"])   # 無ければ既定(autorun が決める)
        self.assertIs(self.post("start", {"id": "abcdefghijk", "mode": "full", "autoSend": False})[2]["auto_send"], False)
        self.assertIsNone(self.post("start", {"id": "abcdefghijk", "mode": "full", "autoSend": "yes"})[2]["auto_send"], "bool でない値は無視")
        self.assertIs(self.post("start-new", {"items": [], "autoSend": True})[2]["auto_send"], True)
        self.assertNotIn("auto_send", self.post("start-docs", {"ids": ["x"], "autoSend": True})[2], "文書単位は送らない")

    def test_estimate_deliver(self):
        self.assertIs(self.post("estimate", {"id": "abcdefghijk", "mode": "full"})[2]["deliver"], True)
        self.assertIs(self.post("estimate", {"id": "abcdefghijk", "mode": "full", "autoSend": False})[2]["deliver"], False)
        self.assertIs(self.post("estimate", {"id": "abcdefghijk", "mode": "adopted", "autoSend": True})[2]["deliver"], False)
        self.ar.folder = ""
        self.assertIs(self.post("estimate", {"id": "abcdefghijk", "mode": "full"})[2]["deliver"], False, "受付のフォルダが無ければ届けない")

    def test_flush_sends(self):
        import types
        srv = types.SimpleNamespace(headless=False, autorun=self.ar)
        self.assertEqual(self.server.PortalServer.flush_sends(srv), 2)
        self.assertEqual(self.calls[-1], ("flush", False), "ライブの組は録画が終わったかを live の見回りが決める")
        srv.headless = True
        self.assertEqual(self.server.PortalServer.flush_sends(srv), 0, "画面なし(友人の PC)では届けない")


if __name__ == "__main__":
    unittest.main()
