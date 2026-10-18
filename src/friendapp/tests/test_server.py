"""src/friendapp/server.py と api.py の HTTP の口のテスト(本物のソケットで 127.0.0.1 のポート 0 に起こす。② は偽の engine)。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_server.py"""
import datetime
import http.client
import json
import os
import shutil
import sys
import threading
import types
import unittest
import urllib.parse
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from friendapp import server as S  # noqa: E402
from friendapp import api as _api  # noqa: E402
from friendapp import api as A  # noqa: E402
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
        self.runs = []            # ② の待ちにある実行(submit で足す。テストが state・steps を書き換えて進み具合を作る)
        self.blocked = None

    def status(self):
        return {"idle": not self.runs, "runs": self.runs, "blocked": self.blocked}

    def submit(self, env, spec=None):
        if self.fail is not None:
            raise self.fail
        self.submitted.append((env, spec))
        self.runs.append({"id": env["id"], "state": "queued", "stateLabel": "順番待ち", "message": "順番を待っています", "steps": [],
                          "requestId": env.get("requestId")})
        return {"id": env["id"], "state": "queued", "message": "順番を待っています", "steps": []}

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        for x in self.runs:
            if x["id"] == run_id:
                x["state"] = "cancelled"
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
        st = self.queue.status()
        return {r["id"]: r for r in st["runs"]}, st

    def close(self):
        self.closed = True


class FakeDropbox:
    """Dropbox の口の偽物(friendapp/dropbox.Client と同じ名前の関数。つながない)"""

    def __init__(self):
        self.files = {}

    def upload_bytes(self, data, path, overwrite=False):
        self.files[path] = bytes(data)
        return path.rsplit("/", 1)[1]

    def upload(self, local, path, overwrite=False, progress=None):
        with open(local, "rb") as f:
            return self.upload_bytes(f.read(), path)

    def get_metadata(self, path):
        return {"name": path} if path in self.files else None

    def delete(self, path):
        return self.files.pop(path, None) is not None

    def list_folder(self, path):
        return None

    def read_small(self, path, cap=1024 * 1024):
        return None

    def download(self, path, part, rev=None, progress=None):
        return False


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "friendsrv-")
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
        d = {"url": URL, "top": 3, "streamer": "", "people": [], "videoTracks": 1, "title": "題", "channel": "チャンネル"}
        d.update(kw)
        return d

    def send(self, **kw):
        st, _h, p = self.post("/api/friend/send", self.form_body(**kw))
        return st, self.js(p)

    def prefs(self, **kw):
        """⚙ の値(処理する PC・解析の重み・ライブの感度・待ち・余白)を POST -> (状態, 応答)"""
        st, _h, p = self.post("/api/friend/prefs", kw)
        return st, self.js(p)

    def make_arrived(self, rid, names, vid=VID, title="題", streamer=""):
        """受信箱に届いた行を直に作る(② は通さない)-> 案件フォルダ・パックのフォルダ"""
        inbox = self.app.inbox
        inbox.add(rid, {"url": URL, "videoId": vid, "streamer": streamer}, {"url": URL, "videoId": vid, "title": title, "channel": ""}, run_id="run-" + rid)
        case = os.path.join(self.places["cases"], "案件-" + rid)
        dirs = []
        for n in names:
            d = os.path.join(case, "パック", n)
            os.makedirs(d)
            dirs.append(d)
        inbox.finished("run-" + rid, "done", "", [{"dir": d, "seconds": 3} for d in dirs], 5, case=case)
        return case, dirs

    def saved_folder(self, title="題", streamer=""):
        """受け取った物の置き場所(<保存先>/<届いた日>_<配信者>_<題>)。届いた日 = 今日"""
        day = datetime.date.today().isoformat()
        return os.path.join(self.tmp, "save", "_".join([x for x in (day, streamer, title) if x]))

    def verdict_docs(self, rid=None):
        """送り返し(outbox)の判断の記録 -> [dict](名前順)"""
        box = self.places["outbox"]
        out = []
        for n in sorted(os.listdir(box)) if os.path.isdir(box) else []:
            if n.endswith(".verdict.json") and (rid is None or n.startswith(rid + "__")):
                with open(os.path.join(box, n), encoding="utf-8") as f:
                    out.append(dict(json.load(f), _name=n))
        return out

    def wait_until(self, fn, secs=10):
        for _ in range(int(secs / 0.02)):
            if fn():
                return True
            threading.Event().wait(0.02)
        return False

    # ------------------------------------------------------------ 配信の一覧(F3-2)
    def test_streams_view_marks_sent_and_refresh(self):
        class FakeStreams:
            refreshed = 0

            def view(self):
                return {"updatedAt": 1, "busy": False, "first": False, "error": None, "sections": [
                    {"key": "today", "label": "今日", "count": 2, "items": [{"videoId": VID, "title": "a"}, {"videoId": "zzzzzzzzzzz", "title": "b"}]}]}

            def refresh(self):
                FakeStreams.refreshed += 1
                return {"ok": True}

            def stop(self):
                pass
        self.app.streams = FakeStreams()
        self.make_arrived("20261017-100000-aaaa01", ["p1_pack"])
        st, _h, p = self.get("/api/friend/streams")
        self.assertEqual(st, 200)
        items = self.js(p)["sections"][0]["items"]
        self.assertEqual(items[0]["sent"], {"state": "arrived", "id": "20261017-100000-aaaa01"})
        self.assertNotIn("sent", items[1])
        st, _h, p = self.post("/api/friend/streams/refresh", {})
        self.assertEqual((st, self.js(p), FakeStreams.refreshed), (200, {"ok": True}, 1))
        self.assertEqual(self.post("/api/friend/streams/refresh", {}, headers={TOKEN: None})[0], 403)
        # ここから: 一覧の印は送った物の行と同じ読み方(② の待ち = queued・実行中 = making)
        class FakeStreams:
            def view(self):
                return {"updatedAt": 1, "busy": False, "first": False, "error": None, "sections": [
                    {"key": "today", "label": "今日", "count": 1, "items": [{"videoId": VID, "title": "a"}]}]}

            def stop(self):
                pass
        self.app.streams = FakeStreams()
        st, d = self.send()
        self.assertEqual(st, 200)
        run_id = d["row"]["runId"]
        self.engine.status_map = lambda: ({run_id: {"id": run_id, "state": "queued"}}, {"blocked": None})
        self.assertEqual(self.js(self.get("/api/friend/streams")[2])["sections"][0]["items"][0]["sent"]["state"], "queued")
        self.engine.status_map = lambda: ({run_id: {"id": run_id, "state": "running", "steps": []}}, {"blocked": None})
        self.assertEqual(self.js(self.get("/api/friend/streams")[2])["sections"][0]["items"][0]["sent"]["state"], "making")

    def test_send_list_script_is_served(self):
        st, h, p = self.get("/friend/send-list.js")
        self.assertEqual(st, 200)
        self.assertIn("FRList", p.decode("utf-8"))

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
        # ---- test_root_redirects_to_friend
        st, h, p = self.get("/")
        self.assertEqual(st, 302)
        self.assertEqual(h["location"], "/friend/")
        # ---- test_post_with_text_body_is_400
        st, _h, p = self.request("POST", "/api/friend/send", body=None, headers={TOKEN: self.srv.token, "Content-Type": "text/plain"})
        self.assertEqual(st, 400)
        self.assertEqual(self.js(p)["error"], "json")

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
        self.assertEqual(d["partsWhy"], "")   # 部品がそろっている = [送る] を止めない
        self.app.setup.block_reason = lambda: "処理の部品を取っています"
        self.assertEqual(self.js(self.get("/api/friend/inbox")[2])["partsWhy"], "処理の部品を取っています")   # 画面が [送る] を先に止める(C-5-1)
        self.assertEqual(d["form"]["top"], 5)   # 本数の初め(C-2-8)
        self.assertNotIn("deliverBatch", d["form"])   # 届け方(5 本ずつ)はやめた
        self.assertEqual((d["form"]["pc"], d["form"]["useWeights"], d["form"]["cut"]), ("this", False, "none"))
        self.assertEqual(d["form"]["live"]["lengthMode"], "auto")
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
        self.assertEqual(self.prefs(useWeights=True, weights={"wAudio": 2, "wChat": 2, "wComments": 2})[0], 200)   # 重みは ⚙ の値
        st, d = self.send(top=9, ranges=[[10, 20], [30, 45]])
        self.assertEqual(st, 200)
        env, spec = self.engine.queue.submitted[0]
        self.assertEqual(spec["adopt"]["top"], 2)
        self.assertEqual(len(spec["hints"]["ranges"]), 2)
        self.assertEqual(spec["hints"]["ranges"][0][0], 10)
        self.assertNotIn("analyze", spec)
        self.assertEqual(d["row"]["form"]["useWeights"], False)

    def test_send_long_range_has_no_length_limit(self):
        """区間 1 つの長さは上限なし(C-2-7・C-5-5。前は ② の 60 分で断っていた): 3 時間の区間もそのまま束の hints.ranges へ"""
        st, d = self.send(top=None, ranges=[[600, 600 + 3 * 3600], [0, 3601]])
        self.assertEqual(st, 200, d)
        env, spec = self.engine.queue.submitted[-1]
        self.assertEqual([list(r) for r in spec["hints"]["ranges"]], [[600.0, 11400.0], [0.0, 3601.0]])
        st, d = self.send(top=None, ranges=[[100, 50]])   # 開始 < 終了は今のまま断る(理由つき)
        self.assertEqual(st, 400)
        self.assertIn("終了が開始より前", json.dumps(d, ensure_ascii=False))

    def test_send_with_weights_uses_them(self):
        st, d = self.prefs(useWeights=True, weights={"wAudio": 0, "wChat": 2, "wComments": 3})
        self.assertEqual(st, 200)
        st, d = self.send(useWeights=True, weights={"wAudio": 3, "wChat": 3, "wComments": 3})   # 送る欄の重みは読まない(⚙ の値を使う)
        self.assertEqual(st, 200)
        env, spec = self.engine.queue.submitted[0]
        self.assertEqual(spec["analyze"], {"wAudio": 0, "wChat": 2, "wComments": 3})
        self.prefs(useWeights=False)
        self.send()
        self.assertNotIn("analyze", self.engine.queue.submitted[1][1])

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
            (dict(top=0), "本数は 1〜20"),
            (dict(top=21), "本数は 1〜20"),
            (dict(top=True), "本数は 1〜20"),
            (dict(top=None), "本数は 1〜20"),
            (dict(top=3.5), "本数は 1〜20"),
            (dict(ranges=[[5, 1]]), "区間"),
            (dict(ranges=[[i * 100, i * 100 + 20] for i in range(6)]), "区間は 5 つまで"),
            (dict(ranges="x"), "区間は 5 つまで"),
            (dict(videoTracks=9), "映像トラックの数"),
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
        self.prefs(useWeights=True, weights={"wAudio": 2, "wChat": 0, "wComments": 3})
        st, _d = self.send(top=7, videoTracks=3)
        self.assertEqual(st, 200)
        form_path = os.path.join(self.places["friend"], "form.json")
        self.assertTrue(os.path.isfile(form_path))
        f = self.app.api.form()
        self.assertEqual(f["top"], 7)
        self.assertEqual(f["videoTracks"], 3)
        self.assertTrue(f["useWeights"])
        self.assertEqual(f["weights"], {"wAudio": 2, "wChat": 0, "wComments": 3})
        # 区間のある送りでは本数は覚えず、前の本数が残る
        self.send(top=None, ranges=[[1, 5]], videoTracks=2)
        f2 = self.app.api.form()
        self.assertEqual(f2["top"], 7)
        self.assertEqual(f2["videoTracks"], 2)
        # アーカイブ待ちの送りも本数を覚える(アーカイブの送りと同じ)
        self.send(kind="wait", top=12)
        self.assertEqual(self.app.api.form()["top"], 12)
        # 本数は 20 まで(1 つ上は断る・上限は覚えられる)
        self.send(top=20)
        self.assertEqual(self.app.api.form()["top"], 20)
        # 壊れた値は既定に戻る(他の値は残す)
        testkit.write_json(form_path, {"top": 99, "deliverBatch": 1, "videoTracks": 0, "pc": "x"})
        f3 = self.app.api.form()
        self.assertEqual(f3["top"], 5)
        self.assertNotIn("deliverBatch", f3)
        self.assertEqual((f3["videoTracks"], f3["pc"]), (1, "this"))
        st3, _h, p3 = self.get("/api/friend/inbox")
        self.assertEqual(self.js(p3)["form"]["top"], 5)

    def test_send_accepts_up_to_five_ranges_and_twenty_top(self):
        st, d = self.send(ranges=[[i * 100, i * 100 + 30] for i in range(5)])
        self.assertEqual(st, 200)
        self.assertEqual(self.engine.queue.submitted[-1][1]["adopt"]["top"], 5)   # 区間があれば本数は区間の数
        st, d = self.send(top=20)
        self.assertEqual(st, 200)
        self.assertEqual(self.engine.queue.submitted[-1][1]["adopt"]["top"], 20)
        st, d = self.send(top=1)
        self.assertEqual(st, 200)

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
        # 前の形 {id, names} も受ける(names が空 = 決めていない物の全部)
        st, _h, p = self.post("/api/friend/decide", {"id": rid, "names": [], "verdict": "keep"})
        d = self.js(p)
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(sorted(x["name"] for x in d["done"]), ["a_pack", "b_pack"])
        self.assertEqual({x["id"] for x in d["done"]}, {rid})
        self.assertEqual(d["errors"], [])
        folder = self.saved_folder()
        self.assertTrue(os.path.isdir(os.path.join(folder, "#1")))   # 保存先 = <日付>_<題>/#番号
        self.assertTrue(os.path.isdir(os.path.join(folder, "#2")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "save", "a_pack")))
        self.assertEqual(self.app.inbox.row(rid)["state"], "done")
        self.assertEqual({v["judge"] for v in self.verdict_docs(rid)}, {"good"})
        # ここから: items 形で複数の行・見送る(ごみ箱)
        r1, r2 = "20250615-130010-aaaaaa", "20250615-130011-aaaaaa"
        _c1, dirs1 = self.make_arrived(r1, ["a_pack", "b_pack"], vid="aaaaaaaaaaa", title="配信A")
        _c2, dirs2 = self.make_arrived(r2, ["c_pack"], vid="bbbbbbbbbbb", title="配信B")
        st, _h, p = self.post("/api/friend/decide", {"items": [{"id": r1, "name": "a_pack"}, {"id": r2, "name": "c_pack"}], "verdict": "keep"})
        d = self.js(p)
        self.assertEqual((st, d["ok"]), (200, True))
        self.assertEqual(sorted((x["id"], x["name"]) for x in d["done"]), [(r1, "a_pack"), (r2, "c_pack")])
        self.assertTrue(os.path.isdir(os.path.join(self.saved_folder("配信A"), "#1")))
        self.assertTrue(os.path.isdir(os.path.join(self.saved_folder("配信B"), "#1")))
        # 見送る = ごみ箱(戻せる)
        st, _h, p = self.post("/api/friend/decide", {"items": [{"id": r1, "name": "b_pack"}], "verdict": "skip"})
        self.assertEqual(self.js(p)["done"], [{"id": r1, "name": "b_pack"}])
        self.assertFalse(os.path.exists(dirs1[1]))
        pk = self.app.inbox.row(r1)["packs"][1]
        self.assertTrue(os.path.isdir(pk["trash"]))
        self.assertEqual(self.app.inbox.row(r1)["state"], "done")
        self.assertEqual(sorted(v["judge"] for v in self.verdict_docs(r1)), ["good", "unknown"])

    def test_decide_bad_with_reason(self):
        rid = "20250615-130020-aaaaaa"
        self.make_arrived(rid, ["a_pack", "b_pack"])
        for body in ({"verdict": "bad"}, {"verdict": "bad", "reason": "other"}):
            st, _h, p = self.post("/api/friend/decide", dict(body, items=[{"id": rid, "name": "a_pack"}]))
            self.assertEqual((st, self.js(p)["error"]), (400, "bad_request"))
        self.assertEqual(self.verdict_docs(rid), [])
        st, _h, p = self.post("/api/friend/decide", {"items": [{"id": rid, "name": "a_pack"}], "verdict": "bad", "reason": "boring"})
        self.assertEqual((st, self.js(p)["done"]), (200, [{"id": rid, "name": "a_pack"}]))
        st, _h, p = self.post("/api/friend/decide", {"items": [{"id": rid, "name": "b_pack"}], "verdict": "bad", "reason": "cut"})
        docs = {d["zip"]: d for d in self.verdict_docs(rid)}
        self.assertEqual((docs["a_pack"]["judge"], docs["a_pack"]["reason"]), ("bad", "boring"))
        self.assertEqual((docs["b_pack"]["judge"], docs["b_pack"]["reason"]), ("bad", "cut"))
        self.assertEqual(docs["a_pack"]["v"], 2)

    def test_decide_reports_move_error_as_not_ok(self):
        rid = "20250615-130100-aaaaaa"
        self.make_arrived(rid, ["a_pack"])
        with mock.patch("friendapp.inbox.shutil.move", side_effect=OSError("busy")):
            st, _h, p = self.post("/api/friend/decide", {"id": rid, "names": ["a_pack"], "verdict": "reject"})   # 前の言葉 reject = 見送る
        d = self.js(p)
        self.assertEqual(st, 200)
        self.assertFalse(d["ok"])
        self.assertEqual(d["done"], [])
        self.assertEqual(d["errors"][0]["name"], "a_pack")
        self.assertEqual(d["errors"][0]["id"], rid)
        self.assertEqual(self.app.inbox.row(rid)["state"], "arrived")

    def test_decide_errors(self):
        rid = "20250615-130200-aaaaaa"
        self.make_arrived(rid, ["a_pack"])
        st, _h, p = self.post("/api/friend/decide", {"items": [{"id": rid, "name": "a_pack"}], "verdict": "video"})
        self.assertEqual(st, 400)
        self.assertEqual(self.js(p)["error"], "bad_request")
        st2, _h, p2 = self.post("/api/friend/decide", {"items": [{"id": "no-such-row", "name": "x"}], "verdict": "keep"})
        self.assertEqual(st2, 404)
        self.assertEqual(self.js(p2)["error"], "not_found")
        self.assertEqual(self.app.inbox.row(rid)["packs"][0]["verdict"], None)

    def test_undo_over_http(self):
        rid = "20250615-130210-aaaaaa"
        _case, dirs = self.make_arrived(rid, ["a_pack"])
        self.post("/api/friend/decide", {"items": [{"id": rid, "name": "a_pack"}], "verdict": "skip"})
        self.assertFalse(os.path.exists(dirs[0]))
        st, _h, p = self.post("/api/friend/undo", {"items": [{"id": rid, "name": "a_pack"}, {"id": rid, "name": "zzz"}, "x", {"id": 3, "name": "a_pack"}]})
        d = self.js(p)
        self.assertEqual((st, d["ok"], d["done"], d["errors"]), (200, True, [{"id": rid, "name": "a_pack"}], []))
        self.assertTrue(os.path.isdir(dirs[0]))   # ごみ箱から元の場所へ
        self.assertEqual(self.app.inbox.row(rid)["state"], "arrived")
        self.assertEqual(sorted(v["judge"] for v in self.verdict_docs(rid)), ["retract", "unknown"])
        self.assertEqual(self.post("/api/friend/undo", {"items": []})[0], 200)
        self.assertEqual(self.post("/api/friend/undo", {"items": [{"id": "nope", "name": "a"}]})[0], 404)
        self.assertEqual(self.post("/api/friend/undo", {"items": [{"id": rid, "name": "a_pack"}]}, headers={TOKEN: None})[0], 403)

    def test_receive_over_http(self):
        r1, r2 = "20250615-130220-aaaaaa", "20250615-130221-aaaaaa"
        self.make_arrived(r1, ["a_pack", "b_pack"], vid="aaaaaaaaaaa", title="配信A", streamer="ぺこら")
        self.make_arrived(r2, ["c_pack"], vid="bbbbbbbbbbb", title="配信B")
        self.app.inbox.row(r1)["packs"][0]["arrivedAt"] -= 5000   # 配信 A が先(最後に届いた時刻は B の方が新しい)
        st, _h, p = self.get("/api/friend/receive")
        d = self.js(p)
        self.assertEqual(st, 200)
        self.assertEqual([s["videoId"] for s in d["sections"]], ["bbbbbbbbbbb", "aaaaaaaaaaa"])
        a = d["sections"][1]
        self.assertEqual((a["title"], a["streamer"], [i["num"] for i in a["items"]]), ("配信A", "ぺこら", [1, 2]))
        self.assertEqual((d["undecided"], d["skipped"], d["notice"]), (3, [], None))
        self.assertNotIn(self.tmp, json.dumps(d, ensure_ascii=False))   # 手元のパスを画面に返さない
        self.post("/api/friend/decide", {"items": [{"id": r1, "name": "a_pack"}], "verdict": "skip"})
        d = self.js(self.get("/api/friend/receive")[2])
        self.assertEqual([(i["name"], i["verdict"]) for i in d["skipped"]], [("a_pack", "skip")])
        self.assertEqual(d["undecided"], 2)
        self.assertEqual(self.get("/api/friend/receive", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_cleaned_notice_over_http(self):
        self.app.inbox.notice = {"n": 2, "at": 1}
        self.assertEqual(self.js(self.get("/api/friend/receive")[2])["notice"], {"n": 2, "at": 1})
        st, _h, p = self.post("/api/friend/notice-seen", {"what": "cleaned"})
        self.assertEqual((st, self.js(p)), (200, {"ok": True}))
        self.assertIsNone(self.js(self.get("/api/friend/receive")[2])["notice"])
        self.assertFalse(self.app.rollback_seen)   # 別の知らせの「見た」は動かさない
        self.assertEqual(self.post("/api/friend/notice-seen", {"what": "cleaned"}, headers={TOKEN: None})[0], 403)

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
        """失敗の行の [消す] は cancel の口 1 つ(remove の口はやめた = 確認を抜ける道を作らない)。受信箱の remove は失敗の行だけを消す"""
        st, d = self.send()
        rid, run = d["row"]["id"], d["row"]["runId"]
        self.assertEqual(self.post("/api/friend/remove", {"id": rid})[0], 404)   # 口は無い
        with self.assertRaises(KeyError):
            self.app.inbox.remove(rid)   # 失敗していない行は消さない
        self.app.inbox.finished(run, "error", "切り抜く所が見つかりません", [], 5)
        st3, _h, p3 = self.post("/api/friend/cancel", {"id": rid})
        self.assertEqual(st3, 200)
        self.assertEqual(self.js(p3)["result"], {"id": rid, "state": "cancelled"})
        self.assertIsNone(self.app.inbox.row(rid))

    def test_cancel_sent_row_removes_it_and_stops_the_run(self):
        st, d = self.send()
        rid, run = d["row"]["id"], d["row"]["runId"]
        st2, _h, p2 = self.post("/api/friend/cancel", {"id": rid})
        self.assertEqual(st2, 200)
        self.assertEqual(self.js(p2)["result"], {"id": rid, "state": "cancelled"})
        self.assertEqual(self.engine.queue.cancelled, [run])
        self.assertIsNone(self.app.inbox.row(rid))   # 届いた物が無ければ行ごと消える(C-2-14)
        rid2 = "20250615-130300-aaaaaa"
        self.make_arrived(rid2, ["a_pack"])
        st3, _h, p3 = self.post("/api/friend/cancel", {"id": rid2})   # 届いた(作り終えた)行は取り消せない
        self.assertEqual(st3, 400)
        self.assertIn("取り消せる行ではありません", self.js(p3)["message"])
        self.assertEqual(self.post("/api/friend/cancel", {"id": "nope"})[0], 404)
        # ---- test_cancel_waiting_row_drops_it_without_queueing
        n_sub, n_can = len(self.engine.queue.submitted), len(self.engine.queue.cancelled)   # 上の送りの分
        st, d = self.send(kind="wait", top=4)
        self.assertEqual((st, d["row"]["state"], d["row"]["runId"], d["row"]["kind"]), (200, "waiting", None, "url"))
        rid = d["row"]["id"]
        self.assertEqual(len(self.engine.queue.submitted), n_sub)   # アーカイブ待ちは ② に積まない
        st, _h, p = self.post("/api/friend/cancel", {"id": rid})
        self.assertEqual((st, self.js(p)["result"]), (200, {"id": rid, "state": "cancelled"}))
        self.assertIsNone(self.app.inbox.row(rid))
        self.assertEqual(len(self.engine.queue.cancelled), n_can)

    def test_cancel_making_row_with_arrived_packs_keeps_them(self):
        """作っている途中で 1 本届いていた: ② の実行を止め、行は「届いた」で cancelled(送った物の一覧から外れ、届いた物は受け取るに残る)"""
        st, d = self.send()
        rid, run = d["row"]["id"], d["row"]["runId"]
        case = os.path.join(self.places["cases"], "案件-" + rid)
        pack = os.path.join(case, "パック", "a_pack")
        os.makedirs(pack)
        row = self.app.inbox.row(rid)
        row["packs"].append({"name": "a_pack", "dir": pack, "title": "a", "seconds": 3, "verdict": None, "at": None, "by": None, "arrivedAt": 1})
        self.app.inbox._number(row, row["packs"][0])
        row["state"] = "making"
        st, _h, p = self.post("/api/friend/cancel", {"id": rid})
        self.assertEqual((st, self.js(p)["result"]), (200, {"id": rid, "state": "cancelled"}))
        self.assertEqual(self.engine.queue.cancelled, [run])
        r = self.app.inbox.row(rid)
        self.assertEqual((r["state"], r["cancelled"]), ("arrived", True))
        shown = self.js(self.get("/api/friend/inbox")[2])["rows"][0]
        self.assertTrue(shown["cancelled"])   # 画面はこの印で送った物から外す
        self.assertEqual(self.js(self.get("/api/friend/receive")[2])["undecided"], 1)   # 届いた物は受け取るに残る

    def test_cancel_recording_stops_recording_and_clips(self):
        """録画中: 録画を止め、同じ requestId の待ち・実行中の切り抜きを取り消す(別の依頼の物は止めない)。届いた物が無ければ行が消える"""
        rid = "20250615-130310-aaaaaa"
        stopped = []
        self.engine.live = types.SimpleNamespace(stop_recording=lambda rc, rec: stopped.append((rc, rec)) or True)
        self.app.inbox.add(rid, {"url": URL, "kind": "live"}, {"url": URL, "videoId": VID, "title": "題", "channel": ""}, kind="live")
        self.app.inbox.live_started(rid, "local", "rec-1")
        q = self.engine.queue
        q.runs += [{"id": "c1", "state": "queued", "requestId": rid}, {"id": "c2", "state": "running", "requestId": rid},
                   {"id": "c3", "state": "done", "requestId": rid}, {"id": "other", "state": "queued", "requestId": "20250615-130311-bbbbbb"}]
        st, _h, p = self.post("/api/friend/cancel", {"id": rid})
        self.assertEqual((st, self.js(p)["result"]), (200, {"id": rid, "state": "cancelled"}))
        self.assertEqual(stopped, [("local", "rec-1")])
        self.assertEqual(q.cancelled, ["c1", "c2"])
        self.assertIsNone(self.app.inbox.row(rid))

    def test_cancel_user_pc_row(self):
        """ユーザーの PC に頼んだ行: まだ上げていない / 上げた(直下にある)なら Dropbox から消して行も消す。受け付けられた後はこの画面から外すだけ"""
        dbx = self.use_fake_dropbox()
        self.assertEqual(self.prefs(pc="user")[0], 200)
        rid1 = self.send()[1]["row"]["id"]
        self.assertEqual(self.post("/api/friend/cancel", {"id": rid1})[0], 200)   # 上げる前
        self.assertIsNone(self.app.inbox.row(rid1))
        rid2 = self.send()[1]["row"]["id"]
        self.app.sync.run_once()
        self.assertIn("/%s.request.json" % rid2, dbx.files)
        self.assertEqual(self.post("/api/friend/cancel", {"id": rid2})[0], 200)   # 上げた後(受付がまだ読んでいない)
        self.assertNotIn("/%s.request.json" % rid2, dbx.files)
        self.assertIsNone(self.app.inbox.row(rid2))
        rid3 = self.send()[1]["row"]["id"]
        self.app.sync.run_once()
        del dbx.files["/%s.request.json" % rid3]   # 受付済みへ移った
        self.app.sync.run_once()
        self.assertEqual(self.app.inbox.row(rid3)["state"], "making")
        self.assertEqual(self.post("/api/friend/cancel", {"id": rid3})[0], 200)   # もう受け付けられた = 画面から外すだけ
        self.assertIsNone(self.app.inbox.row(rid3))
        self.assertEqual(self.engine.queue.submitted, [])

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
        self.make_arrived(rid, ["a_pack", "b_pack"])
        st, _h, p = self.get("/api/friend/media?id=%s&n=1" % rid)
        self.assertEqual(st, 404)
        self.assertEqual(self.js(p)["error"], "not_found")
        st2, _h, _p = self.get("/api/friend/media?id=nope&n=1")
        self.assertEqual(st2, 404)
        st3, _h, _p = self.get("/api/friend/media?id=%s&n=abc" % rid)
        self.assertEqual(st3, 404)
        self.assertEqual(self.get("/api/friend/media?id=%s&name=a_pack" % rid)[0], 404)
        self.assertEqual(self.get("/api/friend/media?id=%s&name=zzz" % rid)[0], 404)
        self.assertEqual(self.get("/api/friend/media?id=nope&name=a_pack")[0], 404)

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

    def test_media_serves_pack_preview_by_name_and_refuses_outside(self):
        """パックの確認用の動画(id + name。F3-4)。玄関の外のパスは断る"""
        rid = "20250615-130510-aaaaaa"
        self.make_arrived(rid, ["a_pack", "b_pack"])
        pdir = os.path.join(self.places["friend"], "previews")
        os.makedirs(pdir)
        inside = os.path.join(pdir, "%s-1.mp4" % rid)
        with open(inside, "wb") as f:
            f.write(b"0123456789")
        self.app.inbox.set_preview(rid, 1, inside)   # 1 本ずつの組 = そのパックの確認用の動画
        st, h, p = self.get("/api/friend/media?id=%s&name=a_pack" % rid)
        self.assertEqual((st, p, h["content-type"]), (200, b"0123456789", "video/mp4"))
        st2, h2, p2 = self.get("/api/friend/media?id=%s&name=a_pack" % rid, headers={"Range": "bytes=2-4"})
        self.assertEqual((st2, p2, h2["content-range"]), (206, b"234", "bytes 2-4/10"))
        self.assertEqual(self.get("/api/friend/media?id=%s&name=b_pack" % rid)[0], 404)   # b の動画はまだ無い
        outside = os.path.join(self.tmp, "outside.mp4")
        with open(outside, "wb") as f:
            f.write(b"xx")
        self.app.inbox.row(rid)["packs"][1]["preview"] = outside
        self.assertEqual(self.get("/api/friend/media?id=%s&name=b_pack" % rid)[0], 404)
        self.app.inbox.row(rid)["packs"][1]["preview"] = os.path.join(pdir, "..", "outside.mp4")   # .. で外へ出る名前も断る
        self.assertEqual(self.get("/api/friend/media?id=%s&name=b_pack" % rid)[0], 404)

    def test_open_pack_folder_after_keep(self):
        """受け取った物のフォルダを開く(偽の open_folder。保存先に無い物は 404)"""
        rid = "20250615-130520-aaaaaa"
        self.make_arrived(rid, ["a_pack", "b_pack"])
        self.assertEqual(self.post("/api/friend/open", {"id": rid, "name": "a_pack"})[0], 404)   # まだ受け取っていない
        self.post("/api/friend/decide", {"items": [{"id": rid, "name": "a_pack"}], "verdict": "keep"})
        st, _h, p = self.post("/api/friend/open", {"id": rid, "name": "a_pack"})
        self.assertEqual((st, self.js(p)), (200, {"ok": True}))
        self.assertEqual(self.opened, [os.path.join(self.saved_folder(), "#1")])
        self.assertEqual(self.post("/api/friend/open", {"id": rid, "name": "b_pack"})[0], 404)
        self.assertEqual(self.post("/api/friend/open", {"id": "nope", "name": "a_pack"})[0], 404)
        self.assertEqual(len(self.opened), 1)

    # ------------------------------------------------------------ 止める・保存先・合言葉の口
    def test_open_saved_dir_creates_it(self):
        st, _h, p = self.post("/api/friend/open", {"what": "saved"})
        self.assertEqual(st, 200)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "save")))
        self.assertEqual(self.js(p)["dir"], os.path.join(self.tmp, "save"))
        self.assertEqual(self.opened, [os.path.join(self.tmp, "save")])

    # ------------------------------------------------------------ ユーザーの PC に頼む(F2-3。A-2)
    def use_fake_dropbox(self):
        os.makedirs(self.places["home"], exist_ok=True)
        testkit.write_json(os.path.join(self.places["home"], "config.json"), {"appKey": "k", "refreshToken": "r"})
        dbx = FakeDropbox()
        self.app.sync.client_factory = lambda cfg, cancelled: dbx
        return dbx

    def test_prefs_pc_user_needs_key(self):
        st, d = self.prefs(pc="user")
        self.assertEqual(st, 400)
        self.assertIn("Dropbox の鍵", d["message"])
        self.assertEqual(self.app.api.form()["pc"], "this")   # 書かない
        st, _h, p = self.get("/api/friend/inbox")
        self.assertFalse(self.js(p)["sync"]["key"])
        self.assertEqual(self.prefs(pc="other")[0], 400)
        self.assertEqual(self.app.api.form()["pc"], "this")

    def test_send_to_user_pc_without_key_after_form_says_user(self):
        """前回の値が user のまま鍵が無くなっても、送ると鍵の理由で断る(行は残さない)"""
        cur = self.app.api.form()
        cur["pc"] = "user"
        self.app.api._write_form(cur)
        st, d = self.send()
        self.assertEqual(st, 400)
        self.assertIn("Dropbox の鍵", d["message"])
        self.assertEqual(self.app.inbox.rows, [])
        self.assertEqual(self.engine.queue.submitted, [])

    def test_send_pc_in_body_is_ignored(self):
        """処理する PC は ⚙ の値。送る欄の pc は読まない"""
        self.use_fake_dropbox()
        st, d = self.send(pc="user")
        self.assertEqual((st, d["row"]["pc"], len(self.engine.queue.submitted)), (200, "this", 1))

    def test_send_to_user_pc_then_back_to_this_pc(self):
        dbx = self.use_fake_dropbox()
        st, d = self.prefs(pc="user")
        self.assertEqual((st, d["form"]["pc"]), (200, "user"))
        self.assertIn("依頼する", d["message"])
        st, d = self.send()
        self.assertEqual(st, 200)
        row = d["row"]
        self.assertEqual((row["pc"], row["state"], row["runId"]), ("user", "sent", None))
        self.assertEqual(self.engine.queue.submitted, [])   # この PC の ② には積まない
        st, _h, p = self.get("/api/friend/inbox")
        j = self.js(p)
        self.assertEqual((j["form"]["pc"], j["sync"]["key"]), ("user", True))
        self.app.sync.run_once()
        path = "/%s.request.json" % row["id"]
        self.assertIn(path, dbx.files)
        self.assertEqual(json.loads(dbx.files[path])["items"][0]["url"], URL)
        st, _h, p = self.post("/api/friend/local", {"id": row["id"]})
        self.assertEqual(st, 200)
        self.assertNotIn(path, dbx.files)   # 直下の依頼を消してから
        self.assertEqual(len(self.engine.queue.submitted), 1)
        r = self.app.inbox.row(row["id"])
        self.assertEqual((r["pc"], r["state"], r["runId"]), ("this", "sent", self.engine.queue.submitted[0][0]["id"]))

    def test_local_refused_after_user_pc_accepted(self):
        self.use_fake_dropbox()
        self.prefs(pc="user")
        _st, d = self.send()
        rid = d["row"]["id"]
        self.app.sync.run_once()
        self.app.inbox.remote_mark(rid, "accepted")
        st, _h, p = self.post("/api/friend/local", {"id": rid})
        self.assertEqual(st, 400)
        self.assertIn("受け付けました", self.js(p)["message"])
        self.assertEqual(self.engine.queue.submitted, [])

    # ------------------------------------------------------------ 動画ファイル・ライブ(F2-6)
    def test_pick_file_uses_hook_and_remembers_by_id(self):
        clip = os.path.join(self.tmp, "【兎田ぺこら】切り抜き.mp4")
        with open(clip, "wb") as f:
            f.write(b"v" * 10)
        picked = []
        self.app.pick_file = lambda: picked.append(1) or clip   # 本物のファイルを選ぶ窓は出さない
        st, _h, p = self.post("/api/friend/pick-file", {})
        d = self.js(p)
        self.assertEqual((st, d["file"]["name"], d["file"]["size"], d["file"]["streamer"], picked), (200, "【兎田ぺこら】切り抜き.mp4", 10, "兎田ぺこら", [1]))
        self.assertNotIn(self.tmp, json.dumps(d, ensure_ascii=False))   # パスは画面に返さない
        self.app.pick_file = lambda: None   # 窓でやめた
        self.assertIsNone(self.js(self.post("/api/friend/pick-file", {})[2])["file"])
        self.assertEqual(self.post("/api/friend/pick-file", {}, headers={TOKEN: None})[0], 403)
        st, d2 = self.send(source="files", files=[{"fileId": d["file"]["id"], "streamer": "兎田ぺこら"}], url=None)
        self.assertEqual((st, d2["row"]["kind"], d2["row"]["source"]["fileName"]), (200, "file", "【兎田ぺこら】切り抜き.mp4"))
        self.assertEqual((len(d2["rows"]), d2["skipped"], d2["rows"][0]["id"]), (1, [], d2["row"]["id"]))
        self.assertTrue(self.wait_until(lambda: self.engine.queue.submitted))   # 写し終えて ② へ(裏の糸)
        env, _spec = self.engine.queue.submitted[0]
        self.assertEqual((env["kind"], env["requestId"]), ("file", d2["row"]["id"]))
        self.assertTrue(env["input"]["path"].startswith(self.places["cases"]))

    def test_palette_is_remembered_and_put_in_meta_at_head_top(self):
        """配色(前の送るアプリの A〜D): 覚えて次に開いたとき meta ytt-palette に(palette.js が <head> の中で読む = meta は <head> の頭)"""
        page = self.get("/friend/")[2].decode("utf-8")
        self.assertIn('<meta name="ytt-palette" content="A">', page)   # 初めは A(ネオンシアン)
        self.assertLess(page.index('name="ytt-palette"'), page.index('src="palette.js"'))
        st, _h, p = self.post("/api/friend/palette", {"name": "C"})
        self.assertEqual((st, self.js(p)["palette"]), (200, "C"))
        self.assertIn('<meta name="ytt-palette" content="C">', self.get("/friend/")[2].decode("utf-8"))
        self.assertEqual(self.post("/api/friend/palette", {"name": "Z"})[0], 400)
        self.assertEqual(self.post("/api/friend/palette", {"name": "B"}, headers={TOKEN: None})[0], 403)
        self.assertEqual(self.get("/friend/palette.js")[0], 200)

    def test_player_prefs_remembered(self):
        """再生画面の音量・消音・速度(前回の値。YouTube と同じ速度の段だけ)"""
        self.assertEqual(self.js(self.get("/api/friend/player")[2])["player"], {"volume": 1.0, "muted": False, "rate": 1})
        st, _h, p = self.post("/api/friend/player", {"volume": 0.35, "muted": True, "rate": 1.5})
        self.assertEqual((st, self.js(p)["player"]), (200, {"volume": 0.35, "muted": True, "rate": 1.5}))
        self.assertEqual(self.js(self.get("/api/friend/player")[2])["player"]["rate"], 1.5)
        for bad in ({"rate": 3}, {"volume": 2}, {"muted": "yes"}):
            self.assertEqual(self.post("/api/friend/player", bad)[0], 400)
        self.assertEqual(self.post("/api/friend/player", {"rate": 1}, headers={TOKEN: None})[0], 403)

    def test_dropped_files_from_window(self):
        """exe の窓に落とした動画(F3-1 の host.js sendFiles = exe が本物のパスを POST /api/friend/files)。動画でない物はその 1 本だけ外す"""
        clip = os.path.join(self.tmp, "【兎田ぺこら】落とした.mp4")
        with open(clip, "wb") as f:
            f.write(b"v" * 7)
        txt = os.path.join(self.tmp, "メモ.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write("x")
        st, _h, p = self.post("/api/friend/files", {"paths": [clip, txt, os.path.join(self.tmp, "無い.mp4")]})
        d = self.js(p)
        self.assertEqual((st, [x["name"] for x in d["files"]], d["files"][0]["streamer"]), (200, ["【兎田ぺこら】落とした.mp4"], "兎田ぺこら"))
        self.assertEqual([x["name"] for x in d["skipped"]], ["メモ.txt", "無い.mp4"])
        self.assertNotIn(self.tmp, json.dumps(d["files"], ensure_ascii=False))   # パスは画面に返さない
        self.assertEqual(self.post("/api/friend/files", {"paths": [clip]}, headers={TOKEN: None})[0], 403)
        # 同じ物をもう一度落としても重ならない(同じパス・大きさ・更新時刻 = 同じ id)
        d2 = self.js(self.post("/api/friend/files", {"paths": [clip, clip]})[2])
        self.assertEqual({x["id"] for x in d2["files"]}, {d["files"][0]["id"]})
        self.assertEqual(len(self.app.api._files), 1)

    def test_holdings_count_reserved_and_archive_wait(self):
        """exe の見回りの預かり(F3-1 の state): 予約 = まだ始まっていない配信の録画・アーカイブ待ち・30 分以内の予約はスリープを止める"""
        ib = self.app.inbox
        now = int(self.app.clock() * 1000)
        ib.add("20261017-200000-aaaaaa", {"url": URL, "startAt": now + 3600 * 1000}, {"url": URL, "videoId": VID, "title": "予約"}, kind="live")
        ib.live_started("20261017-200000-aaaaaa", "local", "rec1")
        ib.add("20261017-200100-bbbbbb", {"url": URL}, {"url": URL, "videoId": VID, "title": "待ち"}, state="waiting")
        self.assertEqual(self.app.holdings(), {"reserved": 1, "archiveWait": 1, "soon": False})
        ib.row("20261017-200000-aaaaaa")["form"]["startAt"] = now + 10 * 60 * 1000
        self.assertTrue(self.app.holdings()["soon"])

    def make_videos(self, names):
        out = []
        for n in names:
            p = os.path.join(self.tmp, n)
            with open(p, "wb") as f:
                f.write(b"v" * 10)
            out.append(self.app.api.remember_file(p) if n.endswith(".mp4") else p)
        return out

    def test_send_files_many_makes_one_row_each_and_skips_bad(self):
        """複数の動画ファイル(source files): 1 本 = 1 行。選び直しが要る物(覚えに無い・消えた)は理由つきで skipped"""
        vids = self.make_videos(["a.mp4", "b.mp4", "c.mp4"])
        gone = vids[2]
        os.remove(os.path.join(self.tmp, "c.mp4"))
        files = [{"fileId": vids[0]["id"], "streamer": "A"}, {"fileId": "nope"}, {"fileId": vids[1]["id"]}, {"fileId": gone["id"]}]
        st, d = self.send(source="files", files=files, url=None)
        self.assertEqual(st, 200)
        self.assertEqual(len(d["rows"]), 2)
        self.assertEqual([r["source"]["fileName"] for r in d["rows"]], ["a.mp4", "b.mp4"])
        self.assertEqual(len({r["id"] for r in d["rows"]}), 2)
        self.assertEqual([s["fileId"] for s in d["skipped"]], ["nope", gone["id"]])
        self.assertTrue(all("選び直して" in s["message"] for s in d["skipped"]))
        self.assertTrue(self.wait_until(lambda: len(self.engine.queue.submitted) == 2))
        self.assertEqual({(spec.get("hints") or {}).get("streamer") for _e, spec in self.engine.queue.submitted}, {"A", ""})   # 配信者は 1 本ずつ
        # 送った物は覚えから外す(同じ物を 2 回送らない)
        st, d = self.send(source="files", files=[{"fileId": vids[0]["id"]}], url=None)
        self.assertEqual(st, 400)
        self.assertIn("選び直して", d["message"])

    def test_send_files_limits(self):
        st, d = self.send(source="files", files=[], url=None)
        self.assertEqual((st, "動画ファイルを選んでください" in d["message"]), (400, True))
        st, d = self.send(source="files", files=[{"fileId": "x%d" % i} for i in range(21)], url=None)
        self.assertEqual(st, 400)
        self.assertIn("20 本まで", d["message"])
        self.assertEqual(self.app.inbox.rows, [])

    def test_send_files_skips_non_video(self):
        """動画でない物は覚えに入れる時点で断る(remember_file)。pick-file も同じ"""
        txt = os.path.join(self.tmp, "memo.txt")
        with open(txt, "w") as f:
            f.write("x")
        self.app.pick_file = lambda: txt
        st, _h, p = self.post("/api/friend/pick-file", {})
        self.assertEqual(st, 400)
        self.assertIn("動画ファイル", self.js(p)["message"])
        self.assertEqual(self.app.api._files, {})

    # ------------------------------------------------------------ 画面に落とした動画(PUT。C-2-13)
    def put(self, name, data, token=True, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port, "Content-Length": str(len(data))}
        if token:
            h[TOKEN] = self.srv.token
        h.update(extra or {})
        try:
            conn.request("PUT", "/api/friend/upload?name=" + urllib.parse.quote(name), body=data, headers=h)
            r = conn.getresponse()
            body = r.read()
            return r.status, self.js(body) if body.startswith(b"{") else body
        finally:
            conn.close()

    def test_upload_needs_token_and_video_name(self):
        self.assertEqual(self.put("a.mp4", b"vvvv", token=False)[0], 403)
        self.assertEqual(self.put("a.mp4", b"vvvv", extra={"Host": "evil.example"})[0], 403)
        st, d = self.put("memo.txt", b"vvvv")
        self.assertEqual(st, 400)
        self.assertIn("動画ファイル", d["message"])
        st, d = self.put("", b"vvvv")
        self.assertEqual(st, 400)
        st, d = self.put("a.mp4", b"")   # 空の本文 = 大きさが分からない
        self.assertEqual(st, 400)
        self.assertFalse(os.path.isdir(self.app.api.upload_dir()) and os.listdir(self.app.api.upload_dir()))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)   # PUT の別の道は 404
        try:
            conn.request("PUT", "/api/friend/inbox", body=b"x", headers={"Host": "127.0.0.1:%d" % self.port, TOKEN: self.srv.token, "Content-Length": "1"})
            self.assertEqual(conn.getresponse().status, 404)
        finally:
            conn.close()

    def test_upload_receives_video_and_send_moves_it(self):
        st, d = self.put("【兎田ぺこら】歌:ってみた.mp4", b"v" * 3000)
        self.assertEqual(st, 200)
        f = d["file"]
        self.assertEqual((f["name"], f["size"], f["title"], f["streamer"]), ("【兎田ぺこら】歌_ってみた.mp4", 3000, "歌_ってみた", "兎田ぺこら"))
        self.assertNotIn(self.tmp, json.dumps(d, ensure_ascii=False))   # パスは返さない
        up = self.app.api.upload_dir()
        self.assertEqual(up, os.path.join(self.places["cases"], "受け取った動画"))
        kept = os.listdir(up)
        self.assertEqual(len(kept), 1)
        with open(os.path.join(up, kept[0]), "rb") as fh:
            self.assertEqual(fh.read(), b"v" * 3000)
        st, d2 = self.send(source="files", files=[{"fileId": f["id"]}], url=None)
        self.assertEqual(st, 200)
        rid = d2["row"]["id"]
        self.assertTrue(self.wait_until(lambda: self.engine.queue.submitted))
        env, _spec = self.engine.queue.submitted[0]
        path = env["input"]["path"]
        self.assertTrue(os.path.isfile(path))
        self.assertNotEqual(os.path.dirname(path), up)   # 依頼のフォルダへ移した(写し直さない)
        self.assertEqual(os.listdir(up), [])
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), b"v" * 3000)
        self.assertEqual(self.app.inbox.row(rid)["form"]["file"]["copy"], path)

    def test_upload_not_sent_is_swept_after_a_day(self):
        st, d = self.put("a.mp4", b"v" * 100)
        self.assertEqual(st, 200)
        up = self.app.api.upload_dir()
        path = os.path.join(up, os.listdir(up)[0])
        now = [os.path.getmtime(path)]
        self.app.api.clock = lambda: now[0]
        stray = os.path.join(up, "stray.mp4")   # アプリを開き直す前に落とした物(画面の覚えに無い)
        with open(stray, "wb") as fh:
            fh.write(b"x")
        os.utime(stray, (now[0] - 2 * 86400, now[0] - 2 * 86400))
        now[0] += 86400 - 10
        self.app.api.sweep_uploads()
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(stray))
        now[0] += 20
        self.app.api.sweep_uploads()
        self.assertTrue(os.path.isfile(path))   # 画面がまだ覚えている間は送れるので残す
        self.app.api._files.clear()   # アプリを開き直した = 覚えが無い
        self.app.api.sweep_uploads()
        self.assertEqual(os.listdir(up), [])   # 送らなかった物は 1 日で消える

    def test_pick_file_busy(self):
        self.app.pick_lock.acquire()
        try:
            st, _h, p = self.post("/api/friend/pick-file", {})
        finally:
            self.app.pick_lock.release()
        self.assertEqual((st, self.js(p)["error"]), (409, "busy"))

    def test_peek_live(self):
        seen = []
        self.app.api.probe = lambda url: seen.append(url) or {"status": "is_upcoming", "message": ""}
        d = self.js(self.get("/api/friend/peek-live?url=" + URL)[2])
        self.assertEqual((d["videoId"], d["status"], d["live"]), (VID, "is_upcoming", True))
        self.get("/api/friend/peek-live?url=" + URL)
        self.assertEqual(seen, [URL])   # 少しのあいだ覚える
        self.app.api.probe = lambda url: {"status": "post_live"}
        self.app.api._live_peek.clear()
        d = self.js(self.get("/api/friend/peek-live?url=" + URL)[2])
        self.assertFalse(d["live"])
        self.assertEqual((d["status"], d["message"]), ("post_live", "配信が終わったばかりです。送ると、アーカイブが出たら自動で作り始めます"))   # アーカイブ待ちで送れる
        self.assertEqual(self.get("/api/friend/peek-live?url=x")[0], 400)

    def test_peek_live_members_only_and_probe_failure(self):
        self.app.api.probe = lambda url: {"status": "unknown", "message": "Join this channel to get access to members-only content"}
        d = self.js(self.get("/api/friend/peek-live?url=" + URL)[2])
        self.assertEqual((d["status"], d["live"], d["message"]), ("members", False, "メンバー限定の配信は切り抜けません"))
        self.app.api._live_peek.clear()

        def boom(url):
            raise RuntimeError("yt-dlp が無い")
        self.app.api.probe = boom   # 調べる部品の不具合でも送る欄は使える
        d = self.js(self.get("/api/friend/peek-live?url=" + URL)[2])
        self.assertEqual((d["status"], d["live"]), ("unknown", False))
        self.assertIn("RuntimeError", d["message"])

    def test_send_live_without_recorder_is_400(self):
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "fixed", "length": 45, "afterStream": True})
        self.assertEqual(st, 400)
        self.assertIn("録画できません", d["message"])
        self.assertEqual(self.app.inbox.rows, [])
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "fixed", "length": 200, "afterStream": True})
        self.assertIn("長さは 10〜180", d["message"])
        st, d = self.send(kind="live", live={"perHour": 0, "lengthMode": "auto", "afterStream": True})
        self.assertIn("1 時間の枠", d["message"])
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "fixed", "afterStream": "yes"})   # fixed で長さ無し・配信後の追加が真偽でない
        self.assertEqual(st, 400)

    def test_send_live_to_user_pc_mixes_form_and_prefs(self):
        """ライブの送る欄の 3 つ(1 時間の枠・長さ・配信後の追加)+ ⚙ の感度・待ち・余白(C-2-11)"""
        dbx = self.use_fake_dropbox()
        self.assertEqual(self.prefs(pc="user", liveSens="high", liveWait=9, livePad=3.5)[0], 200)
        live = {"perHour": 12, "lengthMode": "fixed", "length": 180, "afterStream": False, "sens": "low", "waitMin": 1, "pad": 0}   # 感度・待ち・余白は送る欄から読まない
        st, d = self.send(kind="live", live=live, top=None, ranges=[[1, 5]])
        self.assertEqual((st, d["row"]["kind"], d["row"]["pc"]), (200, "live", "user"))
        self.app.sync.run_once()
        doc = json.loads(dbx.files["/%s.request.json" % d["row"]["id"]])
        self.assertEqual(doc["kind"], "live")
        self.assertEqual(doc["live"], {"sens": "high", "perHour": 12, "length": 180, "waitMin": 9, "pad": 3.5, "afterStream": False, "lengthMode": "fixed"})   # 長さの自動か固定も(C-2-11)
        f = self.app.api.form()
        self.assertEqual(f["live"], {"sens": "high", "perHour": 12, "length": 180, "waitMin": 9, "pad": 3.5, "afterStream": False, "lengthMode": "fixed"})
        self.assertEqual(f["top"], 5)   # ライブは本数を持たない = 前の本数のまま

    def test_send_live_length_only_when_fixed(self):
        """lengthMode が auto の間は送る欄の length を読まない(fixed のときだけ length を検査して使う)"""
        self.use_fake_dropbox()
        self.prefs(pc="user")
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "auto", "length": 9999, "afterStream": True})
        self.assertEqual(st, 200)
        self.assertEqual(d["row"]["form"]["live"]["lengthMode"], "auto")
        self.assertNotEqual(d["row"]["form"]["live"]["length"], 9999)
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "fixed", "length": 9999, "afterStream": True})
        self.assertEqual(st, 400)
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "weird", "length": 9999, "afterStream": True})   # 知らない値は auto
        self.assertEqual((st, d["row"]["form"]["live"]["lengthMode"]), (200, "auto"))

    def test_send_wait_kind_makes_waiting_row(self):
        """kind wait(終わったばかり = アーカイブ待ち): 行は waiting・② にも Dropbox にも積まない。区間も送る欄どおり"""
        dbx = self.use_fake_dropbox()
        st, d = self.send(kind="wait", top=4)
        row = d["row"]
        self.assertEqual((st, row["state"], row["kind"], row["runId"], row["pc"]), (200, "waiting", "url", None, "this"))
        self.assertEqual(self.engine.queue.submitted, [])
        self.assertEqual(row["form"]["top"], 4)
        self.prefs(pc="user")
        st, d = self.send(kind="wait", top=None, ranges=[[10, 40]])
        self.assertEqual((st, d["row"]["state"], d["row"]["pc"]), (200, "waiting", "user"))
        self.assertNotIn("remote", d["row"])
        self.app.sync.run_once()
        self.assertEqual(dbx.files, {})   # アーカイブが出るまで上げない
        st, d = self.send(kind="wait", top=None)
        self.assertEqual(st, 400)

    def test_send_wait_does_not_need_parts_or_engine(self):
        """待つだけの行は部品が足りなくても受け付ける(作り始めるときに断る)"""
        self.app.engine = None
        st, d = self.send(kind="wait", top=3)
        self.assertEqual((st, d["row"]["state"]), (200, "waiting"))

    def test_live_settings_refuses_user_pc_and_other_rows(self):
        """POST /api/friend/live-settings(C-2-11。録画中の行の変え方は test_live の test_update_live_while_recording):
        ユーザーの PC に頼んだ行・ライブでない行・録画中でない行は 400(理由)・無い行は 404・合言葉が要る"""
        self.use_fake_dropbox()
        self.prefs(pc="user")
        st, d = self.send(kind="live", live={"perHour": 6, "lengthMode": "auto", "afterStream": True})
        rid = d["row"]["id"]
        st, _h, p = self.post("/api/friend/live-settings", {"id": rid, "perHour": 3})
        self.assertEqual((st, self.js(p)["message"]), (400, "作る人の PC で録画している依頼は、ここから変えられません"))
        self.assertEqual(self.app.inbox.row(rid)["form"]["live"]["perHour"], 6)
        self.prefs(pc="this")
        self.app.inbox.add("20261017-130000-abcdef", {"kind": "live", "live": {}}, {"url": URL}, kind="live")   # 送っただけ(録画を始める前)
        st, _h, p = self.post("/api/friend/live-settings", {"id": "20261017-130000-abcdef", "perHour": 3})
        self.assertEqual(st, 400)
        self.assertIn("録画中の行だけ", self.js(p)["message"])
        st, d = self.send(kind="url", top=2)
        st, _h, p = self.post("/api/friend/live-settings", {"id": d["row"]["id"], "perHour": 3})
        self.assertEqual((st, self.js(p)["message"]), (400, "ライブの行ではありません"))
        self.assertEqual(self.post("/api/friend/live-settings", {"id": "nope", "perHour": 3})[0], 404)
        self.assertEqual(self.post("/api/friend/live-settings", {"id": rid}, headers={TOKEN: None})[0], 403)

    # ------------------------------------------------------------ ⚙ の値(prefs。C-2-19)
    def test_prefs_sets_each_value_and_writes_form_json(self):
        st, d = self.prefs(useWeights=True, weights={"wAudio": 3, "wChat": 0, "wComments": 1}, liveSens="low", liveWait=20, livePad=4)
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"])
        for word in ("解析の重みを使う", "解析の重みを変えました", "ライブの設定を変えました"):
            self.assertIn(word, d["message"])
        f = d["form"]
        self.assertEqual((f["useWeights"], f["weights"]), (True, {"wAudio": 3, "wChat": 0, "wComments": 1}))
        self.assertEqual((f["live"]["sens"], f["live"]["waitMin"], f["live"]["pad"]), ("low", 20, 4.0))
        with open(os.path.join(self.places["friend"], "form.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["live"]["waitMin"], 20)
        st, d = self.prefs(useWeights=False)
        self.assertIn("使わない", d["message"])
        self.assertEqual(self.app.api.form()["weights"], {"wAudio": 3, "wChat": 0, "wComments": 1})   # 重みの値は残す
        st, d = self.prefs()
        self.assertEqual((st, d["message"]), (200, "変えるものがありません"))
        st, d = self.prefs(liveSens="low")   # 同じ値 = 変わらない
        self.assertEqual(d["message"], "変えるものがありません")
        st, d = self.prefs(unknown=1, pc="this")
        self.assertIn("この PC で処理する", d["message"])

    def test_prefs_bad_values_are_400_and_write_nothing(self):
        before = self.app.api.form()
        bad = [(dict(pc="other"), "処理する PC"), (dict(useWeights="yes"), "オンかオフ"), (dict(useWeights=1), "オンかオフ"),
               (dict(weights={"wAudio": 9, "wChat": 1, "wComments": 1}), "重みは 0〜3"), (dict(weights={"wAudio": 1}), "重みは 0〜3"),
               (dict(weights=3), "重みは 0〜3"), (dict(weights={"wAudio": 1, "wChat": 1, "wComments": True}), "重みは 0〜3"),
               (dict(liveSens="max"), "感度"), (dict(liveWait=0), "待ち"), (dict(liveWait=61), "待ち"), (dict(livePad=6), "余白"),
               (dict(livePad="1"), "余白"), (dict(liveWait=2.5), "待ち")]
        for kw, why in bad:
            with self.subTest(kw=kw):
                st, d = self.prefs(**kw)
                self.assertEqual((st, d["error"]), (400, "bad_request"))
                self.assertIn(why, d["message"])
        # 1 つでも違えば、同じ呼びの正しい値も書かない
        st, d = self.prefs(useWeights=True, liveSens="max")
        self.assertEqual(st, 400)
        self.assertEqual(self.app.api.form(), before)
        self.assertFalse(os.path.exists(os.path.join(self.places["friend"], "form.json")))
        self.assertEqual(self.post("/api/friend/prefs", {"useWeights": True}, headers={TOKEN: None})[0], 403)

    # ------------------------------------------------------------ アーカイブ待ち(tick。C-2-12)
    def fake_clock(self, t0=1_800_000_000.0):
        """玄関の API と受信箱の時計を同じ偽物に(秒)-> [秒](書き換えて進める)"""
        t = [t0]
        self.app.api.clock = lambda: t[0]
        self.app.inbox.clock = lambda: t[0]
        return t

    def test_tick_waits_for_archive_then_queues(self):
        t = self.fake_clock()
        probed = []
        status = ["post_live"]
        self.app.api.probe = lambda url: probed.append(url) or {"status": status[0]}
        st, d = self.send(kind="wait", top=4)
        rid = d["row"]["id"]
        self.app.api.tick()
        self.assertEqual((probed, self.app.inbox.row(rid)["state"], self.engine.queue.submitted), ([URL], "waiting", []))   # 調べて post_live のままなら待つ
        self.assertEqual(self.app.inbox.row(rid)["checkedAt"], int(t[0] * 1000))
        self.app.api.tick()
        t[0] += A.WAIT_EVERY - 1
        self.app.api.tick()
        self.assertEqual(len(probed), 1)   # WAIT_EVERY より早くは調べ直さない
        t[0] += 1
        self.app.api.tick()
        self.assertEqual((len(probed), self.app.inbox.row(rid)["state"]), (2, "waiting"))
        t[0] += A.WAIT_EVERY
        status[0] = "was_live"   # アーカイブが出た
        self.app.api.tick()
        r = self.app.inbox.row(rid)
        self.assertEqual((r["state"], r["kind"], r["form"]["kind"], r["waited"]), ("sent", "url", "url", True))
        self.assertEqual(len(self.engine.queue.submitted), 1)
        env, spec = self.engine.queue.submitted[0]
        self.assertEqual((env["kind"], env["requestId"], env["input"]["videoId"], spec["adopt"]["top"], r["runId"]), ("url", rid, VID, 4, env["id"]))
        t[0] += 5 * A.WAIT_EVERY
        self.app.api.tick()
        self.assertEqual((len(probed), len(self.engine.queue.submitted)), (3, 1))   # 作り始めた行はもう調べない・二重に積まない

    def test_tick_not_live_status_also_starts_and_probe_error_waits_again(self):
        t = self.fake_clock()
        outcomes = [RuntimeError("yt-dlp"), {"status": "not_live"}]

        def probe(url):
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return o
        self.app.api.probe = probe
        rid = self.send(kind="wait", top=2)[1]["row"]["id"]
        self.app.api.tick()   # 調べられない = 次の回にもう一度
        self.assertEqual(self.app.inbox.row(rid)["state"], "waiting")
        t[0] += A.WAIT_EVERY
        self.app.api.tick()
        self.assertEqual(self.app.inbox.row(rid)["state"], "sent")   # 配信ではない(アーカイブとして見られる)ので作り始める

    def test_tick_waiting_row_for_user_pc_goes_to_dropbox(self):
        dbx = self.use_fake_dropbox()
        t = self.fake_clock()
        self.prefs(pc="user")
        self.app.api.probe = lambda url: {"status": "was_live"}
        rid = self.send(kind="wait", top=None, ranges=[[10, 40]])[1]["row"]["id"]
        self.app.sync.run_once()
        self.assertEqual(dbx.files, {})
        self.app.api.tick()
        r = self.app.inbox.row(rid)
        self.assertEqual((r["state"], r["pc"], r["remote"]["state"], r["kind"]), ("sent", "user", "pending", "url"))
        self.assertEqual(self.engine.queue.submitted, [])
        self.app.sync.run_once()
        doc = json.loads(dbx.files["/%s.request.json" % rid])
        self.assertEqual((doc["kind"], doc["items"][0]["url"], doc["items"][0]["ranges"]), ("url", URL, [{"start": 10.0, "end": 40.0}]))

    def test_tick_gives_up_after_a_day(self):
        t = self.fake_clock()
        probed = []
        self.app.api.probe = lambda url: probed.append(url) or {"status": "post_live"}
        rid = self.send(kind="wait", top=4)[1]["row"]["id"]
        t[0] += A.WAIT_GIVE_UP
        self.app.api.tick()
        r = self.app.inbox.row(rid)
        self.assertEqual((r["state"], probed), ("failed", []))   # もう調べない
        self.assertIn("アーカイブが出ませんでした", r["error"])
        fail = self.js(self.get("/api/friend/inbox")[2])["rows"][0]["fail"]
        self.assertEqual((fail["code"], fail["retrying"], fail["repeat"]), ("noArchive", False, False))
        t[0] += 10 * A.RETRY_EVERY
        self.app.api.tick()
        self.assertEqual(self.engine.queue.submitted, [])   # 自動で作り直さない

    # ------------------------------------------------------------ 失敗の言葉・自動のやり直し・知らせる(C-2-16)
    def failing_row(self, text="ネットにつながりませんでした"):
        """送って、その実行を失敗にした行の id"""
        row = self.send()[1]["row"]
        self.app.inbox.finished(row["runId"], "error", text, [], 5)
        return row["id"]

    def view_row(self, rid):
        return next(r for r in self.js(self.get("/api/friend/inbox")[2])["rows"] if r["id"] == rid)

    def fail_again(self, rid, text="ネットにつながりませんでした"):
        self.app.inbox.finished(self.app.inbox.row(rid)["runId"], "error", text, [], 5)

    def test_failure_words_and_auto_retry_up_to_max(self):
        t = self.fake_clock()
        rid = self.failing_row()
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["code"], f["retrying"], f["repeat"], f["reported"]), ("net", True, False, False))
        self.assertIn("ネットにつながりませんでした", f["message"])
        self.assertIn("もう一度送る", f["message"])
        self.assertEqual(f["detail"], "ネットにつながりませんでした")
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 1)   # RETRY_EVERY までは待つ
        for i in range(1, A.RETRY_MAX + 1):
            t[0] += A.RETRY_EVERY - 1
            self.app.api.tick()
            self.assertEqual(len(self.engine.queue.submitted), i)
            t[0] += 1
            self.app.api.tick()
            self.assertEqual(len(self.engine.queue.submitted), i + 1)   # RETRY_EVERY ごとに 1 回
            r = self.app.inbox.row(rid)
            self.assertEqual((r["state"], r["autoRetries"], r["runId"]), ("sent", i, self.engine.queue.submitted[-1][0]["id"]))
            self.assertEqual(self.engine.queue.submitted[-1][0]["requestId"], rid)
            self.fail_again(rid)
            f = self.view_row(rid)["fail"]
            self.assertEqual(f["retrying"], i < A.RETRY_MAX)   # 使い切るまでは「やり直しています」
            self.assertFalse(f["repeat"])
        t[0] += 10 * A.RETRY_EVERY
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 1 + A.RETRY_MAX)   # 使い切ったら自動ではやり直さない
        self.assertEqual(self.app.inbox.row(rid)["state"], "failed")

    def test_failure_repeat_after_friend_resends_and_fails_the_same_way(self):
        t = self.fake_clock()
        rid = self.failing_row()
        for _ in range(A.RETRY_MAX):   # 自動のやり直しを使い切る
            t[0] += A.RETRY_EVERY
            self.app.api.tick()
            self.fail_again(rid)
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["retrying"], f["repeat"]), (False, False))   # 1 回目の失敗(数え始め)
        st, _h, p = self.post("/api/friend/retry", {"id": rid})   # 友人が [もう一度送る]
        self.assertEqual(st, 200)
        self.assertEqual(self.js(p)["row"]["autoRetries"], 0)
        self.fail_again(rid)
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["retrying"], f["repeat"]), (True, False))   # また自動のやり直しが始まる(数え直し)
        for _ in range(A.RETRY_MAX):
            t[0] += A.RETRY_EVERY
            self.app.api.tick()
            self.fail_again(rid)
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["retrying"], f["repeat"]), (False, True))   # 同じ失敗がもう一度 = [作る人に知らせる]

    BOT = "書き出しに失敗しました(1 本): 方法1(区間取得): ERROR: [youtube] poERFwoVxxE: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication.【全角】「'」"

    def test_failure_bot_retries_once_after_a_long_wait(self):
        """YouTube の bot 判定: 友人の言葉は「一時的に止められました」・自動のやり直しは間を空けて 1 回だけ・[もう一度送る] は出せる(10-18)"""
        t = self.fake_clock()
        rid = self.failing_row(self.BOT)
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["code"], f["retrying"], f["repeat"]), ("bot", True, False))
        self.assertIn("YouTube に一時的に止められました", f["message"])
        self.assertIn("処理する PC", f["message"])
        self.assertEqual(f["detail"], self.BOT)   # 詳しく・[コピー] の元 = ’ や全角の記号がそのまま
        t[0] += A.RETRY_EVERY   # 普通の失敗の間隔では、まだやり直さない
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 1)
        t[0] += 1800 - A.RETRY_EVERY
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 2)   # 30 分あとに 1 回
        self.fail_again(rid, self.BOT)
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["retrying"], f["repeat"]), (False, False))
        t[0] += 10 * 1800
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 2)   # 2 回目は無い
        st, _h, p = self.post("/api/friend/report", {"id": rid})   # 送り返しの知らせも化けない
        self.assertEqual(st, 200)
        notes = [n for n in os.listdir(self.places["outbox"]) if n.endswith(".notice.json")]
        with open(os.path.join(self.places["outbox"], notes[0]), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["code"], doc["detail"]), ("bot", self.BOT))

    def test_failure_not_fixable_is_not_retrying_at_once(self):
        t = self.fake_clock()
        rid = self.failing_row("メンバー限定の配信です(Join this channel)")
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["code"], f["retrying"], f["repeat"]), ("members", False, False))
        self.assertIn("メンバー限定の配信は切り抜けません", f["message"])
        t[0] += 10 * A.RETRY_EVERY
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 1)   # 自動ではやり直さない
        self.post("/api/friend/retry", {"id": rid})   # 友人が送り直して、同じ失敗がもう一度
        self.fail_again(rid, "メンバー限定の配信です(Join this channel)")
        f = self.view_row(rid)["fail"]
        self.assertEqual((f["retrying"], f["repeat"]), (False, True))

    def test_failure_other_codes_and_unknown(self):
        cases = [("この配信は非公開です", "unavailable", False), ("空き容量が足りません", "disk", True), ("ffmpeg が落ちました", "unknown", True),
                 ("切り抜く所が見つからず、パックができませんでした", "noHighlights", False)]
        for text, code, retry in cases:
            with self.subTest(text=text):
                f = self.view_row(self.failing_row(text))["fail"]
                self.assertEqual((f["code"], f["retrying"]), (code, retry))
                self.assertEqual(f["detail"], text)

    def test_tick_does_not_retry_cancelled_or_formless_rows(self):
        t = self.fake_clock()
        rid = self.failing_row()
        self.app.inbox.row(rid)["cancelled"] = True
        t[0] += 10 * A.RETRY_EVERY
        self.app.api.tick()
        self.assertEqual(len(self.engine.queue.submitted), 1)

    def test_report_writes_notice_to_outbox(self):
        t = self.fake_clock(1_800_000_000.0)
        rid = self.failing_row("ネットにつながりませんでした")
        log = self.app.api.log_path
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w", encoding="utf-8", newline="") as fh:
            fh.write("".join("ログの行 %d\n" % i for i in range(20000)))   # 128KB より大きい
        st, _h, p = self.post("/api/friend/report", {"id": rid})
        self.assertEqual(st, 200)
        row = self.js(p)["row"]
        self.assertEqual(row["reportedAt"], int(t[0] * 1000))
        files = [n for n in os.listdir(self.places["outbox"]) if n.endswith(".notice.json")]
        self.assertEqual(files, ["%s__notice-%013d.notice.json" % (rid, int(t[0] * 1000))])
        path = os.path.join(self.places["outbox"], files[0])
        self.assertLess(os.path.getsize(path), 256 * 1024)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(sorted(doc), sorted(["v", "kind", "requestId", "title", "code", "message", "detail", "appVersion", "at", "log"]))
        self.assertEqual((doc["v"], doc["kind"], doc["requestId"], doc["title"], doc["code"]), (1, "failure", rid, "題", "net"))
        self.assertEqual((doc["detail"], doc["appVersion"], doc["at"]), ("ネットにつながりませんでした", _version.VERSION, int(t[0] * 1000)))
        self.assertIn("ネットにつながりませんでした", doc["message"])
        self.assertTrue(doc["log"].endswith("ログの行 19999\n"))   # ログの末尾
        self.assertLessEqual(len(doc["log"].encode("utf-8")), 120 * 1024)
        self.assertTrue(doc["log"].startswith("ログの行 "))   # 行の途中から始めない
        self.assertTrue(self.view_row(rid)["fail"]["reported"])
        self.assertEqual(self.post("/api/friend/report", {"id": "nope"})[0], 404)
        self.assertEqual(self.post("/api/friend/report", {"id": rid}, headers={TOKEN: None})[0], 403)

    def test_report_without_log_and_trims_big_notice(self):
        self.fake_clock()
        rid = self.failing_row()
        self.app.api.report(rid)
        with open(os.path.join(self.places["outbox"], os.listdir(self.places["outbox"])[0]), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["log"], "")   # ログが無くても知らせられる
        rid2 = self.failing_row()
        log = self.app.api.log_path
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w", encoding="utf-8", newline="") as fh:
            fh.write("\x01" * (120 * 1024))   # JSON にすると 1 文字 6 バイト → 256KB を超える
        self.app.api.clock = lambda: 1_800_000_100.0
        self.app.api.report(rid2)
        path = os.path.join(self.places["outbox"], [n for n in os.listdir(self.places["outbox"]) if n.startswith(rid2)][0])
        self.assertLess(os.path.getsize(path), 256 * 1024)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertTrue(0 < len(doc["log"]) < 120 * 1024)
        self.assertEqual(set(doc["log"]), {"\x01"})

    def test_resend_clears_reported_mark(self):
        self.fake_clock()
        rid = self.failing_row()
        self.app.api.report(rid)
        self.assertIsNotNone(self.app.inbox.row(rid)["reportedAt"])
        self.post("/api/friend/retry", {"id": rid})
        self.assertIsNone(self.app.inbox.row(rid)["reportedAt"])

    # ------------------------------------------------------------ 進み具合(steps。C-2-15)
    def test_steps_queue_position_and_blocked(self):
        self.fake_clock()
        r1 = self.send()[1]["row"]["id"]
        r2 = self.send()[1]["row"]["id"]
        rows = {r["id"]: r for r in self.js(self.get("/api/friend/inbox")[2])["rows"]}
        self.assertEqual(rows[r1]["steps"]["text"], "順番を待っています(次に始まります)")
        self.assertEqual(rows[r2]["steps"]["text"], "順番を待っています(2 番目)")
        self.assertEqual((rows[r1]["steps"]["index"], rows[r1]["steps"]["total"]), (0, 0))
        self.engine.queue.blocked = {"freeGB": 5.0, "minGB": 20}   # 空き不足
        d = self.js(self.get("/api/friend/inbox")[2])
        self.assertEqual(d["blocked"], {"freeGB": 5.0, "minGB": 20})
        self.assertEqual({r["steps"]["text"] for r in d["rows"]}, {"パソコンの空きが少ないので待っています(あと 15 GB 空けると始まります)"})

    def run_of(self, rid):
        return next(x for x in self.engine.queue.runs if x["id"] == self.app.inbox.row(rid)["runId"])

    def test_steps_stage_reading_eta_slow_and_stage_stats(self):
        t = self.fake_clock()
        self.app.inbox.record_stage("文字起こし", 60)
        self.app.inbox.record_stage("仕上げ", 30)
        rid = self.send()[1]["row"]["id"]
        run = self.run_of(rid)
        run.update(state="running", steps=[{"key": "analyze", "state": "done", "detail": ""}, {"key": "adopt", "state": "done", "detail": ""},
                                           {"key": "export", "state": "done", "detail": ""}, {"key": "transcribe", "state": "run", "detail": "3/5"},
                                           {"key": "pack", "state": "wait", "detail": ""}])
        row = self.view_row(rid)
        self.assertEqual(row["state"], "making")   # 実行が動いていれば「作っている」
        self.assertEqual(row["steps"], {"text": "3/4 文字起こし・3/5 本・あと約 1 分", "index": 3, "total": 4, "label": "文字起こし"})   # 見どころ(analyze・adopt)は 1 段
        self.assertEqual(self.app.inbox.stage_stats()["文字起こし"], [60.0])
        t[0] += 100   # 平均 60 秒を過ぎた = 残りは後ろの段だけ(30 秒)
        self.assertEqual(self.view_row(rid)["steps"]["text"], "3/4 文字起こし・3/5 本・あと 1 分ほど")
        t[0] += 600   # 10 分進みが無い
        self.assertEqual(self.view_row(rid)["steps"]["text"], "3/4 文字起こし・3/5 本・あと 1 分ほど・時間がかかっています")
        run["steps"][3]["detail"] = "4/5"   # 進んだ = 遅いの印は消える
        self.assertEqual(self.view_row(rid)["steps"]["text"], "3/4 文字起こし・4/5 本・あと 1 分ほど")
        t[0] += 50
        run["steps"][3]["state"] = "done"
        run["steps"][4]["state"] = "run"   # 次の段へ = 前の段にかかった秒を覚える
        row = self.view_row(rid)
        self.assertEqual((row["steps"]["label"], row["steps"]["index"]), ("仕上げ", 4))
        self.assertEqual(self.app.inbox.stage_stats()["文字起こし"], [750.0, 60.0])

    def test_steps_show_in_stage_progress_and_slow_only_when_stuck(self):
        """段の中の進み(30fps にそろえています(42%)・解析 42%・待ち)を行に出す。進んでいる間は「時間がかかっています」を出さない(10-18)"""
        t = self.fake_clock()
        rid = self.send()[1]["row"]["id"]
        run = self.run_of(rid)
        run.update(state="running", steps=[{"key": "analyze", "state": "run", "detail": "解析 42%"}, {"key": "transcribe", "state": "wait", "detail": ""}])
        self.assertIn("1/2 見どころを探す・解析 42%", self.view_row(rid)["steps"]["text"])
        t[0] += 700
        run["steps"][0]["detail"] = "解析 43%"   # 10 分のうちに進んだ
        self.assertNotIn("時間がかかっています", self.view_row(rid)["steps"]["text"])
        t[0] += 700   # 進みが止まった
        self.assertIn("時間がかかっています", self.view_row(rid)["steps"]["text"])
        run["steps"][0]["detail"] = "重い処理の枠が空くのを待っています"
        self.assertIn("・重い処理の枠が空くのを待っています", self.view_row(rid)["steps"]["text"])

    def test_steps_transcribe_reads_live_job_progress(self):
        """文字起こしは段の detail が動かない(同じ糸で回る)ので、玄関の認識のジョブの進みを行に出す"""
        t = self.fake_clock()
        rid = self.send()[1]["row"]["id"]
        run = self.run_of(rid)
        run.update(state="running", steps=[{"key": "transcribe", "state": "run", "detail": ""}])
        self.engine.transcribe_progress = lambda: "17%"
        self.assertIn("文字起こし・17%", self.view_row(rid)["steps"]["text"])
        t[0] += 700
        self.engine.transcribe_progress = lambda: "18%"
        self.assertNotIn("時間がかかっています", self.view_row(rid)["steps"]["text"])

    def test_steps_vanish_when_row_arrives(self):
        self.fake_clock()
        rid = self.send()[1]["row"]["id"]
        run = self.run_of(rid)
        run.update(state="running", steps=[{"key": "export", "state": "run", "detail": ""}])
        self.view_row(rid)
        self.assertIn(rid, self.app.api._stages)
        pack = os.path.join(self.places["cases"], "案件", "a_pack")
        os.makedirs(pack)
        self.app.inbox.finished(run["id"], "done", "", [{"dir": pack}], 5)
        self.js(self.get("/api/friend/inbox")[2])
        self.assertNotIn(rid, self.app.api._stages)   # 作っていない行の段の覚えを捨てる
        self.assertNotIn("steps", self.view_row(rid))

    def test_steps_when_run_has_no_known_stage(self):
        self.fake_clock()
        rid = self.send()[1]["row"]["id"]
        self.run_of(rid).update(state="running", steps=[{"key": "something", "state": "run", "detail": ""}])
        self.assertEqual(self.view_row(rid)["steps"]["text"], "仕上げています")
        # ---- test_steps_for_ranged_url_skip_the_search_stage
        self.fake_clock()
        rid = self.send(top=None, ranges=[[1, 30]])[1]["row"]["id"]
        self.run_of(rid).update(state="running", steps=[{"key": "analyze", "state": "done", "detail": ""}, {"key": "export", "state": "run", "detail": ""},
                                                         {"key": "transcribe", "state": "wait", "detail": ""}])
        s = self.view_row(rid)["steps"]
        self.assertEqual((s["label"], s["index"], s["total"]), ("切り抜き", 1, 2))   # 区間があれば「見どころを探す」を数えない

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

    def test_state_idle(self):
        st, _h, p = self.get("/api/friend/state", headers={TOKEN: self.srv.token})
        self.assertEqual(st, 200)
        d = self.js(p)
        self.assertNotIn("windowAgo", d)   # 窓の推測はやめた(F3-1。窓は exe が持つ)
        self.assertEqual({k: d[k] for k in ("busy", "recording", "making", "waiting", "reserved", "archiveWait", "setup", "undecided", "awake", "label")},
                         {"busy": False, "recording": 0, "making": 0, "waiting": 0, "reserved": 0, "archiveWait": 0, "setup": False,
                          "undecided": 0, "awake": False, "label": ""})

    def test_state_holdings_undecided_and_awake(self):
        self.app.holdings = lambda: {"reserved": 2, "archiveWait": 1, "soon": False}
        self.app.inbox.receive_view = lambda: {"sections": [], "skipped": [], "undecided": 5, "notice": None}   # ●n = 受け取る画面と同じ数(F3-4)
        d = self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])
        self.assertEqual((d["reserved"], d["archiveWait"], d["undecided"]), (2, 1, 5))
        self.assertTrue(d["awake"])   # アーカイブ待ちの間はスリープを止める
        self.app.holdings = lambda: {"reserved": 1, "archiveWait": 0, "soon": False}
        self.assertFalse(self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])["awake"])   # 予約だけ(30 分より前)は止めない
        self.app.holdings = lambda: {"reserved": 1, "archiveWait": 0, "soon": True}
        self.assertTrue(self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])["awake"])

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

    def make_version(self, ver):
        d = os.path.join(self.places["home"], "app-" + ver)
        os.makedirs(os.path.join(d, "src", "friendapp"), exist_ok=True)
        os.makedirs(os.path.join(d, "python"), exist_ok=True)
        open(os.path.join(d, "src", "friendapp", "server.py"), "w").close()
        open(os.path.join(d, "python", "python.exe"), "w").close()

    def test_update_band_and_apply(self):
        """入れてある新しい版 → 帯の 1 行(GET /api/friend/update)→ [更新する] → exe が見る state の update・updateRequested"""
        st, _h, p = self.get("/api/friend/update")
        self.assertEqual(self.js(p)["available"], False)
        self.assertEqual(self.post("/api/friend/update/apply", {})[0], 409)   # 新しい版が無い
        self.make_version("0.0.1")       # 今より古い版は出さない
        self.make_version("999.0.0")
        self.make_version("999.1.0")
        testkit.write_json(os.path.join(self.places["home"], "app-versions.json"), {"v": 1, "bad": ["999.1.0"]})   # 起動できなかった版は出さない
        u = self.js(self.get("/api/friend/update")[2])
        self.assertEqual((u["available"], u["version"], u["requested"]), (True, "999.0.0", False))
        d = self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])
        self.assertEqual((d["update"], d["updateRequested"]), ("999.0.0", False))
        self.assertEqual(self.post("/api/friend/update/apply", {}, headers={TOKEN: None})[0], 403)   # 合言葉が要る
        st, _h, p = self.post("/api/friend/update/apply", {})
        self.assertEqual(st, 200)
        self.assertTrue(self.js(p)["update"]["requested"])
        d = self.js(self.get("/api/friend/state", headers={TOKEN: self.srv.token})[2])
        self.assertTrue(d["updateRequested"])
        self.engine.queue.status = lambda: {"idle": False, "runs": [{"state": "running"}]}
        u = self.js(self.get("/api/friend/update")[2])
        self.assertTrue(u["waiting"])   # 作っている間は待つ
        self.assertIn("作っている", u["label"])

    def test_tidy_routes(self):
        """フォルダの整理の口: GET の形・調べる・片付ける物が無ければ 409・あとで・ごみ箱が無ければ 404・合言葉"""
        st, _h, p = self.get("/api/friend/tidy")
        self.assertEqual(st, 200)
        v = self.js(p)
        for k in ("state", "ask", "askCount", "askBytes", "items", "unknownCount", "autoDone", "last", "blocked", "trash"):
            self.assertIn(k, v)
        st, _h, p = self.post("/api/friend/tidy/scan", {})
        self.assertEqual(st, 200)
        self.assertEqual(self.post("/api/friend/tidy/apply", {})[0], 409)   # 片付ける物が無い
        self.assertEqual(self.post("/api/friend/tidy/later", {})[0], 200)
        self.assertEqual(self.post("/api/friend/tidy/open-trash", {})[0], 404)
        self.assertEqual(self.post("/api/friend/tidy/scan", {}, headers={TOKEN: None})[0], 403)
        self.assertEqual(self.opened, [])   # エクスプローラーは開いていない

    def test_page_token_is_placeholder_in_webview2(self):
        with mock.patch.dict(os.environ, {S.HOST_ENV: "webview2"}):
            st, _h, p = self.get("/friend/")
        self.assertEqual(st, 200)
        self.assertIn(b'<meta name="ytt-token" content="host">', p)   # 本物は WebView2 が要求ごとに足す
        self.assertNotIn(self.srv.token.encode("ascii"), p)
        with mock.patch.dict(os.environ, {S.HOST_ENV: "edge"}):
            p = self.get("/friend/")[2]
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode("ascii"), p)   # 逃げ道の Edge の窓は本物

    def test_main_page_goes_to_setup_until_done(self):
        self.app.setup_done = lambda: False
        st, h, _p = self.get("/friend/")
        self.assertEqual((st, h["location"]), (302, "/friend/setup.html"))
        st, _h, p = self.get("/friend/setup.html")
        self.assertEqual(st, 200)
        self.assertIn(b"setup.js", p)
        self.app.setup_done = lambda: True
        self.assertEqual(self.get("/friend/")[0], 200)

    def test_host_files_are_served(self):
        for name in ("host.js", "settings.js", "settings.css", "setup.js"):
            self.assertEqual(self.get("/friend/" + name)[0], 200, name)

    def test_shutdown_says_bye_only_under_exe(self):
        with mock.patch.object(S, "say") as said:
            self.app.shutdown()
        said.assert_not_called()
        app = S.FriendApp(self.places, make_engine=FakeEngine)
        with mock.patch.dict(os.environ, {S.HOST_ENV: "webview2"}), mock.patch.object(S, "say") as said:
            app.shutdown()
        said.assert_called_once_with('{"event": "bye"}')

    def test_watch_does_not_end_by_itself(self):
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
