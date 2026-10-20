"""入口の ytt_api("deliver") の受け渡し(src/app/server.py の PortalServer.ytt_api)のテスト。deliver の本体のテストは tests/flow/test_deliver.py。

実行(リポジトリ直下から): python -m unittest tests/app/test_deliver_api.py -v
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "app")
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from flow import deliver  # noqa: E402


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
        code, _ = srv.ytt_api("deliver", {"op": "status", "job": "nope"})
        self.assertEqual(code, 404)


class AutoSendApiTest(unittest.TestCase):
    """受付は POST /api/flow/submit {envelope, spec} の 1 本・見積もりは同じ本文で /api/flow/estimate(届け先は画面が封筒の deliver に入れる)と、
    受付の見回りの終わりの送り直し(PortalServer.flush_sends)"""

    def setUp(self):
        from app import server
        import types
        calls = self.calls = []

        class AR:
            def submit(self, env, spec=None):
                calls.append(("submit", env, spec))
                if env == "bad":
                    raise ValueError("封筒 は {項目: 値} の形にしてください")
                return {"id": "r1"}

            def estimate(self, env, spec=None):
                calls.append(("estimate", env, spec))
                return {"steps": [], "nothing": True}

            def pools(self):
                return {"k": {}}

            def flush_pools(self, is_done):
                calls.append(("flush", is_done({})))
                return 2
        self.ar = AR()

        class H:
            _post_flow_submit = server.PortalHandler._post_flow_submit

            def _json(self, code, obj):
                self.out = (code, obj)

            def _fail(self, code, err, msg):
                self.out = (code, {"error": err, "message": msg})
        self.h = H()
        self.h.server = types.SimpleNamespace(autorun=self.ar)
        self.server = server

    def test_submit_and_estimate(self):
        env = {"id": "0123456789", "kind": "url", "input": {"videoId": "abcdefghijk"}, "deliver": {"origin": "auto", "dir": "D:/out"}, "specVersion": 2}
        self.h._post_flow_submit("/api/flow/submit", {"envelope": env, "spec": {"run": {"upto": "pack"}}})
        self.assertEqual((self.calls[-1], self.h.out), (("submit", env, {"run": {"upto": "pack"}}), (200, {"run": {"id": "r1"}})))
        self.h._post_flow_submit("/api/flow/estimate", {"envelope": env})
        self.assertEqual((self.calls[-1], self.h.out), (("estimate", env, None), (200, {"steps": [], "nothing": True})))
        self.h._post_flow_submit("/api/flow/submit", {"envelope": "bad"})
        self.assertEqual(self.h.out[0], 400)

    def test_flush_sends(self):
        import types
        srv = types.SimpleNamespace(autorun=self.ar)
        self.assertEqual(self.server.PortalServer.flush_sends(srv), 2)
        self.assertEqual(self.calls[-1], ("flush", False), "ライブの組は録画が終わったかを live の見回りが決める")


if __name__ == "__main__":
    unittest.main()
