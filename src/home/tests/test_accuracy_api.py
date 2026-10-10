"""入口の API(GET api/accuracy・POST api/accuracy/run・調子の accuracy・設定の節)と、手が空いた判定のつなぎ。精度の自動測定の本体のテストは src/eval/drill/tests/test_accuracy.py。

実行(リポジトリ直下から): py -3.10 -m unittest src/home/tests/test_accuracy_api.py -v
"""
import http.client
import json
import os
import sys
import threading
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.drill import accuracy  # noqa: E402
from ytt import jobs  # noqa: E402
import launch as L  # noqa: E402
import test_launch as TL  # noqa: E402  (入口を一時フォルダで動かす道具を借りる。テストそのものは集めない)


class AccuracyApiTest(TL.Base):
    """入口の API(GET api/accuracy・POST api/accuracy/run・調子の accuracy・設定の節)と、手が空いた判定のつなぎ"""

    def setUp(self):
        super().setUp()
        self.srv, self.port = L.make_server(0, self.sup)
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.host = "127.0.0.1:%d" % self.port

    def tearDown(self):
        if not self.srv.closing.is_set():
            self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=body, headers=dict({"Host": self.host}, **(headers or {})))
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r, data

    def post(self, path, headers=None, body=b"{}"):
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": self.srv.token}
        h.update(headers or {})
        return self.req("POST", path, body, h)

    def test_api(self):
        r, body = self.req("GET", "/api/accuracy")
        j = json.loads(body)
        self.assertEqual((r.status, j["enabled"], j["state"], j["nightFrom"], j["nightTo"], j["heavyEnabled"]), (200, True, "idle", 1, 6, False))
        self.assertEqual([a["id"] for a in j["areas"]], ["asr", "marks", "speakers", "cut", "alt"])
        self.assertEqual(len(j["goals"]), len(accuracy.GOALS))   # 入口の条件(あと何本・何分)
        r, _ = self.req("GET", "/api/accuracy", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, body = self.req("GET", "/api/health")   # 調子にも同じものが入る
        self.assertEqual(json.loads(body)["accuracy"]["state"], "idle")
        r, _ = self.post("/api/accuracy/run", headers={"X-YTT-Token": "x"})   # 合言葉が要る
        self.assertEqual(r.status, 403)
        r, body = self.post("/api/accuracy/run")
        self.assertEqual((r.status, json.loads(body)["forced"]), (200, True))
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "accuracy", "value": {"enabled": False}}).encode())
        self.assertEqual((r.status, json.loads(body)["value"]["enabled"]), (200, False))
        r, body = self.post("/api/accuracy/run")
        self.assertEqual((r.status, json.loads(body)["error"]), (409, "off"))     # オフのときは受け付けない
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "accuracy", "value": {"nightFrom": 7, "nightTo": 7}}).encode())
        self.assertEqual(r.status, 400)
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "get", "sections": ["accuracy"]}).encode())
        self.assertEqual(json.loads(body)["prefs"]["accuracy"], {"enabled": False, "nightFrom": 1, "nightTo": 6})

    def test_busy_probe(self):
        self.assertIsNone(self.srv._accuracy_busy())          # 何も動いていない(編集も動いていない)
        with jobs.SLOTS.slot("studio", "テスト") as ok:
            self.assertTrue(ok)
            self.assertEqual(self.srv._accuracy_busy(), "重い処理")
        self.assertIsNone(self.srv._accuracy_busy())

    def test_last_edit_probe(self):
        self.assertIsNone(self.srv._accuracy_last_edit())      # 文書のフォルダが無い
        from manage.cases import cases as cases_mod
        d = cases_mod.locations(self.sup.root)["transcripts"]
        os.makedirs(d, exist_ok=True)
        for name, t in (("a.json", 1000.0), ("b.edit.json", 3000.0), ("c.diar.json", 2000.0)):
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write("{}")
            os.utime(p, (t, t))
        os.makedirs(os.path.join(d, ".hist"))                  # 履歴のフォルダは数えない
        self.assertEqual(self.srv._accuracy_last_edit(), 3000.0)


if __name__ == "__main__":
    unittest.main()
