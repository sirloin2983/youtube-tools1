"""パックを友人へ届ける(src/home/deliver.py・入口の api/ytt/deliver)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_deliver.py -v
"""
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import deliver  # noqa: E402


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


class ZipPackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"), b"v" * 1000)
        put(os.path.join(self.pack, "sub", "textplus-import.json"), b"{}")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)

    def test_zip_has_top_folder_and_no_temp_left(self):
        dest = deliver.zip_pack(self.pack, self.out, "20261004-120000-abcdef__題名")
        self.assertEqual(os.path.basename(dest), "20261004-120000-abcdef__題名.zip")
        with zipfile.ZipFile(dest) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
            self.assertEqual(names, ["clip_pack/clip.mp4", "clip_pack/sub/textplus-import.json"])
            self.assertEqual(z.getinfo([n for n in z.namelist() if n.endswith(".mp4")][0]).compress_type, zipfile.ZIP_STORED)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])

    def test_same_name_does_not_overwrite(self):
        a = deliver.zip_pack(self.pack, self.out, "n")
        b = deliver.zip_pack(self.pack, self.out, "n")
        self.assertNotEqual(a, b)
        self.assertEqual(len(os.listdir(self.out)), 2)

    def test_check_stops_and_cleans_temp(self):
        class Stop(Exception):
            pass

        def check():
            raise Stop()
        with self.assertRaises(Stop):
            deliver.zip_pack(self.pack, self.out, "n", check=check)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])
        self.assertEqual(os.listdir(self.out), [])

    def test_request_id_matches_friend_app(self):
        # friend-apps/request-sender/src/Core.cs の NameRx と同じ形(アプリが先頭の id を除いて題名を出す)
        self.assertRegex(deliver.request_id(), r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class DeliveriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"))
        self.folder = os.path.join(self.tmp, "Dropbox")
        os.makedirs(self.folder)
        self.cfg = {"folder": self.folder}
        self.packs = {os.path.normpath(self.pack)}
        self.logs = []
        self.dl = deliver.Deliveries(lambda: self.cfg["folder"], lambda d: os.path.normpath(d) in self.packs, log=self.logs.append)

    def test_start_and_done(self):
        j = wait(self.dl, self.dl.start(self.pack, "【雑談】校正済み/1"))
        self.assertEqual(j["state"], "done")
        self.assertRegex(j["name"], r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}__【雑談】校正済み_1\.zip$")
        self.assertEqual(os.listdir(os.path.join(self.folder, deliver.OUT_DIR)), [j["name"]])
        self.assertTrue(self.logs)

    def test_title_falls_back_to_folder_name(self):
        j = wait(self.dl, self.dl.start(self.pack, ""))
        self.assertTrue(re.search(r"__clip\.zip$", j["name"]), j["name"])

    def test_refuses_non_pack_folder(self):
        other = os.path.join(self.tmp, "secret")
        put(os.path.join(other, "a.txt"))
        for d in (other, "", None, 3, "x" * 2000):
            with self.assertRaises(ValueError):
                self.dl.start(d, "t")
        self.assertFalse(os.path.exists(os.path.join(self.folder, deliver.OUT_DIR)))

    def test_refuses_without_intake_folder(self):
        self.cfg["folder"] = ""
        with self.assertRaisesRegex(ValueError, "決まっていません"):
            self.dl.start(self.pack, "t")
        self.cfg["folder"] = os.path.join(self.tmp, "nope")
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            self.dl.start(self.pack, "t")

    def test_status_unknown(self):
        self.assertIsNone(self.dl.status("nope"))
        self.assertIsNone(self.dl.status(None))

    def test_error_is_reported(self):
        orig = deliver.zip_pack

        def boom(*a, **k):
            raise OSError(28, "No space left on device")
        deliver.zip_pack = boom
        self.addCleanup(setattr, deliver, "zip_pack", orig)
        j = wait(self.dl, self.dl.start(self.pack, "t"))
        self.assertEqual(j["state"], "error")
        self.assertIn("No space left", j["message"])


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
