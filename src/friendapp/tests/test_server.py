"""src/friendapp/server.py と api.py の HTTP の口のテスト(本物のソケットで 127.0.0.1 のポート 0 に起こす。② は偽の engine)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_server.py"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from friendapp import server as S  # noqa: E402
from friendapp import api as _api  # noqa: E402
from ytt import version as _version  # noqa: E402

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VID = "dQw4w9WgXcQ"
TOKEN = S.TOKEN_HEADER


class FakeQueue:
    """② の待ち行列の偽物。submit は積むだけ・cancel は記録するだけ"""

    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.fail = None

    def status(self):
        return {"idle": True, "runs": [], "blocked": None}

    def submit(self, env, spec=None):
        if self.fail is not None:
            raise self.fail
        self.submitted.append((env, spec))
        return {"id": env["id"], "state": "queued", "message": "順番を待っています", "steps": []}

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        return {"id": run_id, "state": "cancelled"}

    def history(self, limit=None):
        return {"runs": []}

    def close(self):
        pass


class FakeEngine:
    """② の偽物(make_engine に渡す)。queue・_previews・status_map・close を持つ"""

    def __init__(self, places, inbox, log=None):
        self.queue = FakeQueue()
        self._previews = []
        self.closed = False

    def status_map(self):
        return {}, self.queue.status()

    def close(self):
        self.closed = True


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friendsrv-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.places = {
            "home": os.path.join(self.tmp, "home"),
            "data": os.path.join(self.tmp, "data"),
            "friend": os.path.join(self.tmp, "data", "app", "friendapp"),
            "outbox": os.path.join(self.tmp, "data", "app", "outbox"),
            "cases": os.path.join(self.tmp, "作業"),
            "save": lambda: os.path.join(self.tmp, "save"),
        }
        os.makedirs(self.places["friend"])
        os.makedirs(self.places["cases"])
        self.app = S.FriendApp(self.places, make_engine=FakeEngine)
        self.opened = []
        self.app.open_folder = self.opened.append   # 本物のエクスプローラーを開かない(画面を取らない)
        self.app.prepare()
        self.app.api.fetch = self.fake_fetch
        self.fetched = []
        self.srv = S.Server(("127.0.0.1", 0), self.app)
        self.app.server = self.srv
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.srv.shutdown()
        self.thread.join(10)
        self.srv.server_close()

    @property
    def engine(self):
        return self.app.engine

    def fake_fetch(self, vid):
        self.fetched.append(vid)
        return {"title": "テストの配信", "channel": "テストちゃんねる"}

    # ------------------------------------------------------------ 呼び方
    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        try:
            conn.request(method, path, body=data, headers=h)
            r = conn.getresponse()
            payload = r.read()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, payload
        finally:
            conn.close()

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)

    def post(self, path, body=None, headers=None):
        """書き込み系: 合言葉(X-YTT-Token)を付ける。headers で None を渡すと外せる"""
        hd = {TOKEN: self.srv.token}
        hd.update(headers or {})
        return self.request("POST", path, body=body, headers=hd)

    @staticmethod
    def js(payload):
        return json.loads(payload.decode("utf-8"))

    def form_body(self, **kw):
        d = {"url": URL, "top": 3, "streamer": "", "people": [], "videoTracks": 1, "deliverBatch": 5,
             "useWeights": False, "title": "題", "channel": "チャンネル"}
        d.update(kw)
        return d

    def send(self, **kw):
        st, _h, p = self.post("/api/friend/send", self.form_body(**kw))
        return st, self.js(p)

    def make_arrived(self, rid, names, batch=5):
        """受信箱に届いた行を直に作る(② は通さない)-> 案件フォルダ・パックのフォルダ"""
        inbox = self.app.inbox
        inbox.add(rid, {"url": URL}, {"url": URL, "videoId": VID, "title": "題", "channel": "c"}, run_id="run-" + rid)
        case = os.path.join(self.places["cases"], "案件-" + rid)
        dirs = []
        for n in names:
            d = os.path.join(case, "パック", n)
            os.makedirs(d)
            dirs.append(d)
        inbox.finished("run-" + rid, "done", "", [{"dir": d, "seconds": 3} for d in dirs], batch, case=case)
        return case, dirs

    # ------------------------------------------------------------ 口の基本・安全
    def test_ping(self):
        st, h, p = self.get("/api/ping")
        self.assertEqual(st, 200)
        self.assertEqual(self.js(p), {"app": "ytt-friend", "version": _version.VERSION})

    def test_friend_page_has_token_meta_and_csp(self):
        st, h, p = self.get("/friend/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", h["content-type"])
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode("ascii"), p)
        self.assertIn("default-src 'self'", h["content-security-policy"])
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertEqual(h["cache-control"], "no-store")

    def test_root_redirects_to_friend(self):
        st, h, p = self.get("/")
        self.assertEqual(st, 302)
        self.assertEqual(h["location"], "/friend/")

    def test_token_differs_per_server(self):
        other = S.Server(("127.0.0.1", 0), self.app)
        try:
            self.assertNotEqual(other.token, self.srv.token)
        finally:
            other.server_close()

    def test_bad_host_is_403(self):
        st, _h, p = self.get("/api/ping", headers={"Host": "evil.example"})
        self.assertEqual(st, 403)
        st2, _h, _p = self.get("/api/ping", headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(st2, 200)
        st3, _h, _p = self.post("/api/friend/send", self.form_body(), headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(st3, 403)
        self.assertEqual(self.app.inbox.rows, [])

    def test_cross_site_fetch_is_403(self):
        st, _h, _p = self.get("/api/friend/inbox", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(st, 403)
        st2, _h, _p = self.get("/api/friend/inbox", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(st2, 200)

    def test_post_without_token_is_403(self):
        st, _h, p = self.post("/api/friend/send", self.form_body(), headers={TOKEN: None})
        self.assertEqual(st, 403)
        self.assertEqual(self.js(p)["error"], "token")
        st2, _h, p2 = self.post("/api/friend/send", self.form_body(), headers={TOKEN: "wrong-token"})
        self.assertEqual(st2, 403)
        self.assertEqual(self.js(p2)["error"], "token")
        self.assertEqual(self.app.inbox.rows, [])
        self.assertEqual(self.engine.queue.submitted, [])

    def test_post_from_other_origin_is_403(self):
        st, _h, _p = self.post("/api/ytt/client-log", {"msg": "x"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        st2, _h, _p = self.post("/api/ytt/client-log", {"msg": "x"}, headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(st2, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.places["friend"], "logs", "client-errors.jsonl")))

    def test_post_with_text_body_is_400(self):
        st, _h, p = self.request("POST", "/api/friend/send", body=None, headers={TOKEN: self.srv.token, "Content-Type": "text/plain"})
        self.assertEqual(st, 400)
        self.assertEqual(self.js(p)["error"], "json")

    def test_friend_api_prefix_is_same_route(self):
        st, _h, p = self.get("/friend/api/friend/inbox")
        self.assertEqual(st, 200)
        self.assertIn("rows", self.js(p))
        st2, _h, p2 = self.post("/friend/api/friend/send", self.form_body())
        self.assertEqual(st2, 200)
        self.assertEqual(len(self.engine.queue.submitted), 1)

    def test_unknown_routes_are_404(self):
        st, _h, p = self.get("/api/nope")
        self.assertEqual(st, 404)
        self.assertEqual(self.js(p)["error"], "not_found")
        st2, _h, _p = self.post("/api/nope", {})
        self.assertEqual(st2, 404)

    # ------------------------------------------------------------ 受信箱・送る
    def test_inbox_empty_shows_defaults(self):
        st, _h, p = self.get("/api/friend/inbox")
        d = self.js(p)
        self.assertEqual(st, 200)
        self.assertEqual(d["rows"], [])
        self.assertTrue(d["ready"])
        self.assertIsNone(d["blocked"])
        self.assertIsNone(d["notice"])
        self.assertEqual(d["prep"], {"state": "ready", "message": ""})
        self.assertEqual(d["form"]["top"], 10)
        self.assertEqual(d["form"]["deliverBatch"], 5)
        self.assertEqual(d["saveDir"], os.path.join(self.tmp, "save"))

    def test_send_makes_row_and_queues_envelope(self):
        st, d = self.send(title="見出し", channel="局")
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"])
        row = d["row"]
        self.assertEqual(row["state"], "sent")
        self.assertEqual(row["source"]["videoId"], VID)
        self.assertEqual(len(self.engine.queue.submitted), 1)
        env, spec = self.engine.queue.submitted[0]
        self.assertEqual(env["id"], row["runId"])
        self.assertEqual(env["kind"], "url")
        self.assertEqual(env["input"]["videoId"], VID)
        self.assertEqual(env["requestId"], row["id"])
        self.assertEqual(spec["adopt"]["top"], 3)
        self.assertNotIn("people", spec.get("hints", {}))
        self.assertEqual(self.app.inbox.row(row["id"])["state"], "sent")

    def test_send_with_ranges_uses_count_and_ignores_top_and_weights(self):
        st, d = self.send(top=9, ranges=[[10, 20], [30, 45]], useWeights=True, weights={"wAudio": 2, "wChat": 2, "wComments": 2})
        self.assertEqual(st, 200)
        env, spec = self.engine.queue.submitted[0]
        self.assertEqual(spec["adopt"]["top"], 2)
        self.assertEqual(len(spec["hints"]["ranges"]), 2)
        self.assertEqual(spec["hints"]["ranges"][0][0], 10)
        self.assertNotIn("analyze", spec)

    def test_send_with_weights_uses_them(self):
        st, d = self.send(useWeights=True, weights={"wAudio": 0, "wChat": 2, "wComments": 3})
        self.assertEqual(st, 200)
        env, spec = self.engine.queue.submitted[0]
        self.assertEqual(spec["analyze"], {"wAudio": 0, "wChat": 2, "wComments": 3})

    def test_send_people_becomes_hints_only_with_two_or_more(self):
        st, _d = self.send(streamer="配信者A", people=["コラボB", "配信者A"])
        self.assertEqual(st, 200)
        env, spec = self.engine.queue.submitted[-1]
        self.assertEqual(spec["hints"]["people"], [{"name": "配信者A"}, {"name": "コラボB"}])
        st2, _d2 = self.send(streamer="", people=["ひとり"])
        self.assertEqual(st2, 200)
        env2, spec2 = self.engine.queue.submitted[-1]
        self.assertNotIn("people", spec2.get("hints", {}))

    def test_send_bad_form_is_400_with_reason(self):
        cases = [
            (dict(url="nope"), "YouTube の配信の URL"),
            (dict(top=0), "本数は 1〜30"),
            (dict(top=31), "本数は 1〜30"),
            (dict(top=True), "本数は 1〜30"),
            (dict(ranges=[[5, 1]]), "区間"),
            (dict(videoTracks=9), "映像トラックの数"),
            (dict(deliverBatch=3), "届け方"),
            (dict(useWeights=True, weights={"wAudio": 9, "wChat": 1, "wComments": 1}), "重みは 0〜3"),
        ]
        for kw, why in cases:
            with self.subTest(kw=kw):
                st, d = self.send(**kw)
                self.assertEqual(st, 400)
                self.assertEqual(d["error"], "bad_request")
                self.assertIn(why, d["message"])
        self.assertEqual(self.engine.queue.submitted, [])
        self.assertEqual(self.app.inbox.rows, [])

    def test_send_refused_by_queue_removes_row(self):
        self.engine.queue.fail = ValueError("待ちが多すぎます")
        st, d = self.send()
        self.assertEqual(st, 400)
        self.assertIn("待ちが多すぎます", d["message"])
        self.assertEqual(self.app.inbox.rows, [])

    def test_send_while_preparing_is_400(self):
        self.app.engine = None
        st, d = self.send()
        self.assertEqual(st, 400)
        self.assertIn("準備中", d["message"])
        st2, _h, p = self.get("/api/friend/inbox")
        self.assertFalse(self.js(p)["ready"])

    def test_form_remembers_last_values_in_form_json(self):
        st, _d = self.send(top=7, deliverBatch=1, videoTracks=3, useWeights=True, weights={"wAudio": 2, "wChat": 0, "wComments": 3})
        self.assertEqual(st, 200)
        form_path = os.path.join(self.places["friend"], "form.json")
        self.assertTrue(os.path.isfile(form_path))
        f = self.app.api.form()
        self.assertEqual(f["top"], 7)
        self.assertEqual(f["deliverBatch"], 1)
        self.assertEqual(f["videoTracks"], 3)
        self.assertTrue(f["useWeights"])
        self.assertEqual(f["weights"], {"wAudio": 2, "wChat": 0, "wComments": 3})
        # 区間のある送りでは本数は覚えず、前の本数が残る
        self.send(top=None, ranges=[[1, 5]], videoTracks=2)
        f2 = self.app.api.form()
        self.assertEqual(f2["top"], 7)
        self.assertEqual(f2["videoTracks"], 2)
        # 壊れた値は既定に戻る(他の値は残す)
        with open(form_path, "w", encoding="utf-8") as fh:
            json.dump({"top": 99, "deliverBatch": 1, "videoTracks": 0}, fh)
        f3 = self.app.api.form()
        self.assertEqual(f3["top"], 10)
        self.assertEqual(f3["deliverBatch"], 1)
        self.assertEqual(f3["videoTracks"], 1)
        st3, _h, p3 = self.get("/api/friend/inbox")
        self.assertEqual(self.js(p3)["form"]["top"], 10)

    def test_peek_returns_title_and_caches(self):
        st, h, p = self.get("/api/friend/peek?url=" + URL)
        self.assertEqual(st, 200)
        d = self.js(p)
        self.assertEqual(d["videoId"], VID)
        self.assertEqual(d["title"], "テストの配信")
        self.assertEqual(d["channel"], "テストちゃんねる")
        self.assertEqual(d["streamer"], "")
        self.assertIsNone(d["hex"])
        self.get("/api/friend/peek?url=" + URL)
        self.assertEqual(self.fetched, [VID])

    def test_peek_bad_url_is_400(self):
        st, _h, p = self.get("/api/friend/peek?url=https%3A%2F%2Fexample.com%2F")
        self.assertEqual(st, 400)
        self.assertEqual(self.js(p)["error"], "bad_url")
        self.assertEqual(self.fetched, [])

    # ------------------------------------------------------------ 決める・やり直し・止める・消す
    def test_decide_keep_over_http(self):
        rid = "20250615-130000-aaaaaa"
        case, dirs = self.make_arrived(rid, ["a_pack", "b_pack"])
        st, _h, p = self.post("/api/friend/decide", {"id": rid, "names": [], "verdict": "keep"})
        d = self.js(p)
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(sorted(d["done"]), ["a_pack", "b_pack"])
        self.assertEqual(d["errors"], [])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "save", "a_pack")))
        self.assertEqual(self.app.inbox.row(rid)["state"], "done")

    def test_decide_reports_move_error_as_not_ok(self):
        rid = "20250615-130100-aaaaaa"
        self.make_arrived(rid, ["a_pack"])
        with mock.patch("friendapp.inbox.shutil.move", side_effect=OSError("busy")):
            st, _h, p = self.post("/api/friend/decide", {"id": rid, "names": ["a_pack"], "verdict": "reject"})
        d = self.js(p)
        self.assertEqual(st, 200)
        self.assertFalse(d["ok"])
        self.assertEqual(d["done"], [])
        self.assertEqual(d["errors"][0]["name"], "a_pack")
        self.assertEqual(self.app.inbox.row(rid)["state"], "arrived")

    def test_decide_errors(self):
        rid = "20250615-130200-aaaaaa"
        self.make_arrived(rid, ["a_pack"])
        st, _h, p = self.post("/api/friend/decide", {"id": rid, "names": [], "verdict": "video"})
        self.assertEqual(st, 409)
        self.assertEqual(self.js(p)["error"], "refused")
        st2, _h, p2 = self.post("/api/friend/decide", {"id": "no-such-row", "names": [], "verdict": "keep"})
        self.assertEqual(st2, 404)
        self.assertEqual(self.js(p2)["error"], "not_found")

    def test_retry_resends_failed_row(self):
        st, d = self.send()
        rid, old_run = d["row"]["id"], d["row"]["runId"]
        self.app.inbox.finished(old_run, "error", "取り出せませんでした", [], 5)
        self.assertEqual(self.app.inbox.row(rid)["state"], "failed")
        st2, _h, p = self.post("/api/friend/retry", {"id": rid})
        self.assertEqual(st2, 200)
        new_row = self.js(p)["row"]
        self.assertEqual(new_row["state"], "sent")
        self.assertNotEqual(new_row["runId"], old_run)
        self.assertEqual(len(self.engine.queue.submitted), 2)
        self.assertEqual(self.engine.queue.submitted[1][0]["id"], new_row["runId"])
        self.assertEqual(self.engine.queue.submitted[1][0]["requestId"], rid)
        # 送った行はもう一度送れない
        st3, _h, p3 = self.post("/api/friend/retry", {"id": rid})
        self.assertEqual(st3, 400)
        self.assertIn("もう一度送れる行ではありません", self.js(p3)["message"])
        st4, _h, _p4 = self.post("/api/friend/retry", {"id": "nope"})
        self.assertEqual(st4, 400)

    def test_remove_failed_row_and_refuse_others(self):
        st, d = self.send()
        rid, run = d["row"]["id"], d["row"]["runId"]
        st2, _h, p2 = self.post("/api/friend/remove", {"id": rid})
        self.assertEqual(st2, 404)
        self.app.inbox.finished(run, "cancelled", "", [], 5)
        st3, _h, p3 = self.post("/api/friend/remove", {"id": rid})
        self.assertEqual(st3, 200)
        self.assertTrue(self.js(p3)["ok"])
        self.assertIsNone(self.app.inbox.row(rid))

    def test_cancel_sent_row_and_refuse_arrived(self):
        st, d = self.send()
        rid, run = d["row"]["id"], d["row"]["runId"]
        st2, _h, p2 = self.post("/api/friend/cancel", {"id": rid})
        self.assertEqual(st2, 200)
        self.assertEqual(self.js(p2)["result"], {"id": run, "state": "cancelled"})
        self.assertEqual(self.engine.queue.cancelled, [run])
        rid2 = "20250615-130300-aaaaaa"
        self.make_arrived(rid2, ["a_pack"])
        st3, _h, p3 = self.post("/api/friend/cancel", {"id": rid2})
        self.assertEqual(st3, 400)
        self.assertIn("止められる行ではありません", self.js(p3)["message"])

    def test_flow_submit_and_cancel_go_to_queue(self):
        env = {"id": "envx", "kind": "url"}
        st, _h, p = self.post("/api/flow/submit", {"envelope": env, "spec": {"adopt": {"top": 1}}})
        self.assertEqual(st, 200)
        self.assertEqual(self.js(p)["run"]["id"], "envx")
        self.assertEqual(self.engine.queue.submitted[-1][0], env)
        st2, _h, p2 = self.post("/api/flow/cancel", {"id": "envx"})
        self.assertEqual(self.js(p2)["result"]["state"], "cancelled")

    def test_flow_status_while_preparing(self):
        self.app.engine = None
        st, _h, p = self.get("/api/flow/status")
        self.assertEqual(self.js(p), {"idle": True, "runs": [], "preparing": True})
        st2, _h, p2 = self.post("/api/flow/cancel", {"id": "x"})
        self.assertEqual(st2, 409)

    # ------------------------------------------------------------ まとめ動画
    def test_media_404_until_preview_exists(self):
        rid = "20250615-130400-aaaaaa"
        self.make_arrived(rid, ["a_pack", "b_pack"], batch=1)
        st, _h, p = self.get("/api/friend/media?id=%s&n=1" % rid)
        self.assertEqual(st, 404)
        self.assertEqual(self.js(p)["error"], "not_found")
        st2, _h, _p = self.get("/api/friend/media?id=nope&n=1")
        self.assertEqual(st2, 404)
        st3, _h, _p = self.get("/api/friend/media?id=%s&n=abc" % rid)
        self.assertEqual(st3, 404)

    def test_media_serves_preview_with_range_and_refuses_outside(self):
        rid = "20250615-130500-aaaaaa"
        self.make_arrived(rid, ["a_pack"])
        pdir = os.path.join(self.places["friend"], "previews")
        os.makedirs(pdir)
        inside = os.path.join(pdir, "g1.mp4")
        with open(inside, "wb") as f:
            f.write(b"0123456789")
        self.app.inbox.set_preview(rid, 1, inside)
        st, h, p = self.get("/api/friend/media?id=%s&n=1" % rid)
        self.assertEqual(st, 200)
        self.assertEqual(p, b"0123456789")
        self.assertEqual(h["content-type"], "video/mp4")
        st2, h2, p2 = self.get("/api/friend/media?id=%s&n=1" % rid, headers={"Range": "bytes=2-4"})
        self.assertEqual(st2, 206)
        self.assertEqual(p2, b"234")
        self.assertEqual(h2["content-range"], "bytes 2-4/10")
        outside = os.path.join(self.tmp, "outside.mp4")
        with open(outside, "wb") as f:
            f.write(b"xx")
        self.app.inbox.set_preview(rid, 1, outside)
        st3, _h, _p3 = self.get("/api/friend/media?id=%s&n=1" % rid)
        self.assertEqual(st3, 404)

    # ------------------------------------------------------------ 止める・保存先・合言葉の口
    def test_open_saved_dir_creates_it(self):
        st, _h, p = self.post("/api/friend/open", {"what": "saved"})
        self.assertEqual(st, 200)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "save")))
        self.assertEqual(self.js(p)["dir"], os.path.join(self.tmp, "save"))
        self.assertEqual(self.opened, [os.path.join(self.tmp, "save")])

    def test_open_folder_guard_skips_test_places(self):
        """守り: inplace の作業データ・一時フォルダの下は開かない(本物の os.startfile まで行かない)"""
        self.assertFalse(S.open_folder(os.path.join(self.tmp, "save"), env={}))
        self.assertFalse(S.open_folder("C:\\somewhere", env={"YTT_DATA_DIR": "inplace"}))

    def test_shutdown_stops_server_and_engine(self):
        st, _h, p = self.post("/api/shutdown", {})
        self.assertEqual(st, 200)
        self.assertTrue(self.js(p)["ok"])
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(self.app.closing.is_set())
        self.assertTrue(self.engine.closed)

    def test_shutdown_needs_token(self):
        st, _h, _p = self.post("/api/shutdown", {}, headers={TOKEN: None})
        self.assertEqual(st, 403)
        self.assertTrue(self.thread.is_alive())

    # ------------------------------------------------------------ 起動役(F2-4)の口
    def test_state_needs_token(self):
        st, _h, _p = self.get("/api/friend/state")
        self.assertEqual(st, 403)
        st, _h, _p = self.get("/api/friend/state", headers={TOKEN: "x"})
        self.assertEqual(st, 403)

    def test_state_idle_and_window_ago(self):
        now = [1000.0]
        self.app.clock = lambda: now[0]
        self.app.seen = 990.0
        st, _h, p = self.get("/api/friend/state", headers={TOKEN: self.srv.token})
        self.assertEqual(st, 200)
        d = self.js(p)
        self.assertEqual((d["windowAgo"], d["busy"], d["recording"], d["making"], d["waiting"], d["label"]), (10.0, False, 0, 0, 0, ""))

    def test_state_counts_runs_and_recording(self):
        self.engine.queue.status = lambda: {"idle": False, "runs": [{"state": "running"}, {"state": "queued"}, {"state": "queued"}, {"state": "done"}]}
        self.app.recording_count = lambda: 1
        d = self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])
        self.assertTrue(d["busy"])
        self.assertEqual((d["recording"], d["making"], d["waiting"]), (1, 1, 2))
        self.assertEqual(d["label"], "録画中 1 本・作っている 1 本・待ち 2 本")

    def test_recording_alone_is_busy(self):
        self.app.recording_count = lambda: 2
        d = self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])
        self.assertTrue(d["busy"])
        self.assertEqual(d["label"], "録画中 2 本")

    def test_window_post_resets_seen_and_opens(self):
        opened = []
        self.app.open_window = opened.append
        self.app.seen = 0.0
        st, _h, p = self.post("/api/friend/window", {})
        self.assertEqual(st, 200)
        self.assertTrue(self.js(p)["ok"])
        self.assertEqual(opened, ["http://localhost:%d/friend/" % self.port])
        self.assertLess(self.app.clock() - self.app.seen, 5)
        self.assertEqual(self.post("/api/friend/window", {}, headers={TOKEN: None})[0], 403)

    def test_watch_does_not_end_by_itself(self):
        self.app.seen = 0.0   # 窓を閉じて長い = 前は 120 秒で自分で終わった
        t = threading.Thread(target=self.app.watch, daemon=True)
        with mock.patch.object(self.app.closing, "wait", side_effect=[False, False, True]):
            t.start()
            t.join(5)
        self.assertFalse(t.is_alive())
        self.assertFalse(self.app.closing.is_set())

    def test_token_from_environment(self):
        with mock.patch.dict(os.environ, {S.TOKEN_ENV: "launcher-secret"}):
            srv = S.Server(("127.0.0.1", 0), self.app)
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.token, "launcher-secret")

    def test_rollback_notice_once(self):
        self.assertIsNone(self.js(self.get("/api/friend/inbox")[2])["rollback"])
        with mock.patch.dict(os.environ, {S.ROLLBACK_ENV: "0.90.0"}):
            app = S.FriendApp(self.places, make_engine=FakeEngine)
        self.assertIn("0.90.0", app.rollback_notice())
        self.assertIn("前の版", app.rollback_notice())
        app.rollback_seen = True
        self.assertIsNone(app.rollback_notice())

    def test_notice_seen_without_catalog_is_ok(self):
        st, _h, p = self.post("/api/friend/notice-seen", {})
        self.assertEqual(st, 200)
        self.assertTrue(self.js(p)["ok"])


if __name__ == "__main__":
    unittest.main()
