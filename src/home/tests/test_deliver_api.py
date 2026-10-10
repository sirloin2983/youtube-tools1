"""入口の ytt_api("deliver") の受け渡し(src/home/launch.py の PortalServer.ytt_api)のテスト。deliver の本体のテストは src/human/friend/tests/test_deliver.py。

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
        import launch
        tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, tmp, True)
        pack = os.path.join(tmp, "p_pack")
        put(os.path.join(pack, "a.mp4"))
        os.makedirs(os.path.join(tmp, "Dropbox"))

        class Fake:
            ytt_api = launch.PortalServer.ytt_api
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


if __name__ == "__main__":
    unittest.main()
