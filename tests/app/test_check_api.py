"""入口の「確かめる」の口(GET api/check/next・POST api/check/answer(undo も)・skip・flush。V1 の V0)のつなぎ。
待ち行列の中身のテストは tests/app/check/、記録と反映は tests/human/check/test_apply.py。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/test_check_api.py -v
"""
import http.client
import json
import os
import sys
import threading
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "app")
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

from app.check import deck, lineup, sources  # noqa: E402
from human.check import apply  # noqa: E402
from app import server as L  # noqa: E402
import test_launch as TL  # noqa: E402  (入口を一時フォルダで動かす道具を借りる。テストそのものは集めない)


def fake_cards(view):
    return [{"id": lineup.card_id("cut", "tst", "aaaaaaaaaaaa", r), "kind": "cut", "source": "tst", "case": {"id": "v1", "title": "t"},
             "target": {"docId": "aaaaaaaaaaaa", "row": r}, "media": {"url": "transcribe/media?id=aaaaaaaaaaaa", "start": 0, "end": 1, "pad": 0},
             "text": r, "guess": "1", "options": [], "score": None, "note": "", "_order": [i]} for i, r in enumerate(("s1", "s2"))]


class CheckApiTest(TL.Base):
    def setUp(self):
        super().setUp()
        self.applied = []
        sources.register("cut", "tst", fake_cards)
        apply.register("cut", "tst", lambda ctx, c, ans: self.applied.append(c["id"]) or {"n": len(self.applied)},
                       lambda ctx, row: self.applied.remove(row["card"]) or {"ok": True})
        self.addCleanup(sources._unregister, "cut", "tst")
        self.addCleanup(apply._unregister, "cut", "tst")
        deck.invalidate()
        self.srv, self.port = L.make_server(0, self.sup)
        self.th = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)   # 止めるのを待たない
        self.th.start()
        self.host = "127.0.0.1:%d" % self.port

    def tearDown(self):
        if not self.srv.closing.is_set():
            self.srv.shutdown()
        self.srv.server_close()
        deck.invalidate()
        super().tearDown()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=body, headers=dict({"Host": self.host}, **(headers or {})))
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, json.loads(data) if data[:1] == b"{" else data

    def post(self, path, obj, token=None):
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": token or self.srv.token}
        return self.req("POST", path, json.dumps(obj).encode(), h)

    def ids(self, **q):
        st, j = self.req("GET", "/api/check/next?" + "&".join("%s=%s" % kv for kv in q.items()))
        self.assertEqual(st, 200, j)
        return [c["id"] for c in j["cards"] if c["source"] == "tst"], j

    def test_next(self):
        got, j = self.ids(kind="cut", n=5)
        self.assertEqual(got, ["cut:tst:aaaaaaaaaaaa#s1", "cut:tst:aaaaaaaaaaaa#s2"])
        for k in ("rev", "counts", "goal", "goals", "total", "held", "failed", "errors"):
            self.assertIn(k, j)
        self.assertNotIn("_order", j["cards"][0])
        self.assertEqual(self.ids(n=0)[1]["cards"], [])
        self.assertEqual(self.ids(c="v9")[0], [])
        for bad in ("kind=talk", "n=51", "c=../x"):
            st, j = self.req("GET", "/api/check/next?" + bad)
            self.assertEqual((st, j["error"]), (400, "bad_request"), bad)
        st, _ = self.req("GET", "/api/check/next", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)

    def test_answer_undo_skip_flush(self):
        c1, c2 = "cut:tst:aaaaaaaaaaaa#s1", "cut:tst:aaaaaaaaaaaa#s2"
        st, _ = self.post("/api/check/answer", {"card": c1, "answer": "1"}, token="x")
        self.assertEqual(st, 403)
        st, j = self.post("/api/check/answer", {"card": c1, "answer": "1", "ms": 900})
        self.assertEqual((st, j["ok"], j["held"], j["next"]["id"], self.applied), (200, True, False, c2, [c1]), j)
        self.assertEqual(self.ids(kind="cut")[0], [c2])
        st, j2 = self.post("/api/check/answer", {"card": c1, "answer": "1"})
        self.assertEqual((st, j2["error"]), (409, "answered"))
        st, j3 = self.post("/api/check/answer", {"undo": j["answer"]})
        self.assertEqual((st, j3["card"], self.applied), (200, c1, []))
        self.assertEqual(self.ids(kind="cut")[0], [c1, c2])
        st, j4 = self.post("/api/check/answer", {"card": c1, "answer": "1", "skip": [c2]})
        self.assertEqual((st, j4["next"] is None or j4["next"]["id"] != c2), (200, True))
        self.assertEqual(self.post("/api/check/answer", {"card": "cut:tst:aaaaaaaaaaaa#s9", "answer": "1"})[1]["error"], "gone")
        self.assertEqual(self.post("/api/check/answer", {"card": "nope", "answer": "1"})[1]["error"], "bad_request")
        st, j5 = self.post("/api/check/skip", {"card": c2})
        self.assertEqual((st, j5["ok"]), (200, True))
        self.assertEqual(self.post("/api/check/skip", {"card": 3})[0], 400)
        st, j6 = self.post("/api/check/flush", {})
        self.assertEqual((st, j6["flushed"]), (200, []))
        st, j7 = self.post("/api/check/flush", {"page": "pABC123"})   # 画面の印つき(その画面の保留だけ確定。6b-1)
        self.assertEqual((st, j7["flushed"]), (200, []))

    def test_value_card_wiring(self):
        """価値のカードの反映が入口の hooks(auto_review・studio)につながっている(V2a)"""
        self.assertTrue(apply._registered("value", "auto") and apply._registered("value", "cand"))
        ctx = self.srv.check_ctx()
        code, j = ctx.hook("auto_review")({"op": "discard", "id": "abcdefghijk", "markId": "nope"})
        self.assertEqual((code, j["error"]), (404, "not_found"))   # 一覧に無い切り抜き = 今の POST /api/cases/auto と同じ答え
        orig = dict(sources._SOURCES)
        sources.register("value", "auto", lambda view: [{"id": "value:auto:abcdefghijk#a1", "kind": "value", "source": "auto", "case": {"id": "abcdefghijk", "title": "t"},
                                                         "target": {"videoId": "abcdefghijk", "markId": "a1", "docId": None, "row": None}, "media": {}, "text": "", "guess": None,
                                                         "options": ["good", "bad"], "score": 80, "note": "", "_order": [0]}])
        self.addCleanup(lambda: (sources._SOURCES.clear(), sources._SOURCES.update(orig), deck.invalidate()))
        deck.invalidate()
        st, j = self.post("/api/check/answer", {"card": "value:auto:abcdefghijk#a1", "answer": {"choice": "bad", "reason": "boring"}})
        self.assertEqual(st, 200)
        st, j = self.post("/api/check/flush", {})
        self.assertEqual((st, j["flushed"]), (200, []))

    def test_time_card_wired(self):
        """入口が time:row の反映を登録している(V2d)。同じ部品を別の出どころ名で試す: 形の違う答えは 400・文書が無ければ 409"""
        self.assertTrue(apply._registered("time", "row"))
        from human.check import timerow as check_time
        sources.register("time", "tst", lambda view: [dict(c, id=c["id"].replace("cut:", "time:"), kind="time") for c in fake_cards(view)])
        apply.register("time", "tst", check_time._apply_time, check_time._revert_time, check_time._check)
        self.addCleanup(sources._unregister, "time", "tst")
        self.addCleanup(apply._unregister, "time", "tst")
        deck.invalidate()
        cid = "time:tst:aaaaaaaaaaaa#s1"
        from ytt import workdata
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.TX_DIR = None
        st, j = self.post("/api/check/answer", {"card": cid, "answer": {"choice": "head", "dStart": -0.1}})
        self.assertEqual((st, j["error"]), (503, "unavailable"))
        workdata.set_data_dir(os.path.join(self.tmp, "wd"))
        os.makedirs(workdata.TX_DIR, exist_ok=True)
        st, j = self.post("/api/check/answer", {"card": cid, "answer": {"choice": "head", "dStart": -0.1}})
        self.assertEqual((st, j["error"]), (409, "no_doc"))


if __name__ == "__main__":
    unittest.main()
