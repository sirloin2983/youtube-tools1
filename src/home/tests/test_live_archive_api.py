# -*- coding: utf-8 -*-
"""アーカイブで本番版に作り直す(線 D の P4)の入口 home を通す分: POST /live/api/archive・…/cancel・GET /live/api/exports の archiveInfo(server.py を通して)と、
入口のプロセスで numpy を import しない検査。本体(照合・入れ替え・自動の見回り)は ② の src/flow/tests/test_live_archive.py。

    py -3.10 -m unittest src/home/tests/test_live_archive_api.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)    # ytt(このファイルだけを流しても読めるように)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "flow", "tests"))   # 共有の偽物 _livefix
import _livefix as LF  # noqa: E402
from flow import live_archive as A  # noqa: E402
from flow import live_export as LX  # noqa: E402

RELEASE = 1790000000.0            # 配信の開始時刻(偽の yt-dlp の release_timestamp)
VID = "abcdefghijk"


class NoNumpyTest(unittest.TestCase):
    def test_no_numpy_in_portal(self):
        code = "import sys; sys.path[:0] = [%r, %r]; import live; from app import server; import flow.live_archive, flow.live_export; print('numpy' in sys.modules)" % (HERE, REPO)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=60, env=dict(os.environ, YTT_DATA_DIR="inplace"))
        self.assertEqual(r.stdout.decode().strip().splitlines()[-1], "False", r.stderr.decode("utf-8", "replace"))


class ApiTest(unittest.TestCase):
    """POST /live/api/archive・…/cancel・GET /live/api/exports の archiveInfo(入口の server.py を通して)"""

    def setUp(self):
        from app import server as L
        import test_live as TL   # 同じ home/tests の FakeRecorder・PortalLiveTest.jreq/req を借りる
        self.TL = TL
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-arc-api-")
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")})
        self.env.start()
        self.sup = L.Supervisor(self.tmp, only=[], log=lambda m: None, mounts=())
        self.srv, self.port = L.make_server(0, self.sup)
        self.sup.attach(self.srv)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.srv.live.store_dir = os.path.join(self.tmp, "live")
        self.srv.live.out_dir = lambda: os.path.join(self.tmp, "out")
        self.status = "post_live"
        self.studio = LF.ArchiveStudio("unused", block=True)
        self.srv.live.archive_opts = {"probe": lambda vid: {"status": self.status, "release": RELEASE}, "studio": self.studio,
                                      "audio": lambda *a, **k: (_ for _ in ()).throw(A.ArchiveError("偽: 取らない")), "poll": 0.1}
        self.fake = TL.FakeRecorder()

    def tearDown(self):
        self.srv.live.close()
        self.srv.shutdown()
        self.srv.server_close()
        self.fake.close()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def jreq(self, method, path, body=None):
        return self.TL.PortalLiveTest.jreq(self, method, path, body)

    def req(self, *a, **kw):
        return self.TL.PortalLiveTest.req(self, *a, **kw)

    def test_api(self):
        rec = "20261004-000000-a"
        q = "/live/api/exports?recorder=fake&recording=" + rec
        base_post = self.jreq("POST", "/api/no-such", {})
        self.assertEqual(self.jreq("POST", "/live/api/archive", {"recorder": "fake", "recording": rec}), base_post)   # オフ: 今までどおりの 404
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "patch", "section": "live", "value": {
            "enabled": True, "recorders": [{"id": "fake", "name": "偽物", "url": self.fake.url, "token": self.TL.TOKEN}]}})
        self.assertEqual(code, 200, d)
        self.assertTrue(d["value"]["autoArchive"])
        self.assertEqual(self.req("POST", "/live/api/archive", {"recorder": "fake", "recording": rec}, token=False)[0], 403)   # 合言葉
        self.assertEqual(self.jreq("POST", "/live/api/archive", {"recorder": "fake", "recording": "../x"})[0], 400)
        self.assertEqual(self.jreq("POST", "/live/api/archive", {"recorder": "nope", "recording": rec})[0], 404)
        code, d = self.jreq("POST", "/live/api/archive", {"recorder": "fake", "recording": rec})
        self.assertEqual((code, d.get("error")), (409, "conflict"), d)
        self.assertIn("作り直すものがありません", d["message"])
        ex = self.srv.live.exporter
        ex.marks.upsert("fake", rec, "lm-0000000000aa", 1, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 5), url="https://www.youtube.com/watch?v=" + VID)
        ex.jobs.append({"id": "lx-00000000aa", "recorder": "fake", "recording": rec, "markId": "lm-0000000000aa", "n": 1, "label": "",
                        "start": LX.epoch_iso(RELEASE), "end": LX.epoch_iso(RELEASE + 5), "state": "error", "needsArchive": True,
                        "created": LX.now_iso(), "updated": LX.now_iso(), "path": "", "error": "欠け"})
        code, d = self.jreq("POST", "/live/api/archive", {"recorder": "fake", "recording": rec})
        self.assertEqual(code, 409)
        self.assertIn("処理中", d["message"])   # 用意がまだ
        code, d = self.jreq("GET", q)
        self.assertEqual(d["archiveInfo"]["ready"], False)
        self.assertTrue(d["archiveInfo"]["checkedAt"])
        self.assertNotIn("archiveInfo", self.jreq("GET", "/live/api/exports")[1])   # 録画を指定したときだけ
        self.status = "was_live"
        code, d = self.jreq("POST", "/live/api/archive", {"recorder": "fake", "recording": rec})
        self.assertEqual((code, d["ok"], d["queued"]), (200, True, 1), d)
        code, d = self.jreq("POST", "/live/api/archive/cancel", {"recorder": "fake", "recording": rec})
        self.assertEqual((code, d["ok"]), (200, True), d)
        job = LF.wait_for(lambda: next((j for j in self.jreq("GET", q)[1]["jobs"] if j["archive"]["state"] in ("cancelled", "error")), None), 30)
        self.assertTrue(job, self.jreq("GET", q)[1])
        self.assertTrue(self.jreq("GET", q)[1]["archiveInfo"]["ready"])


if __name__ == "__main__":
    unittest.main()
