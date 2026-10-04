# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P1)の入口の側(home/live.py・prefs の節 live・launch.py の /live/…・「調子」の行)のテスト。

    py -3.10 -m unittest home/tests/test_live.py

確かめること:
  - 設定 live: 既定はオフ・形の検査・合言葉は空で送っても今の値を残す・画面へ返す設定に合言葉を出さない
  - オフ: /live/… は今までと同じ 404(GET・POST とも)・「調子」に live が出ない・見回りは何もしない
  - オン: 画面(CSP に media-src blob:・合言葉)・hls.js の同梱・録画元の一覧(合言葉を出さない)・中継(合言葉 Bearer と Host を付ける・
    Sec-Fetch-Site と入口の合言葉の検査・知らない録画元・パスの検査・思わぬ種類の応答・録画元が止まっている)・「調子」の行
  - 見回り: 手元の録画の部品(recorder/recorder.py)を切り離して起動する → 動いている → 古い版なら終わってもらって起動し直す
  - P2 マークと書き出し(home/live_export.py): マークの API(オフなら 404・検査・fsync した正本)・本物の録画の部品(--source direct)で
    録画中にマーク → 録画待ち → 届いたら取得 → 30fps(30/1・長さ)→ スタジオと同じ置き場所・名前・.clip.json(source.kind live)→
    文字起こしへ(偽のまとめて実行)・取り消し・録画が先に終わった(録れた所まで)・録画元が落ちた(失敗と理由)・欠け(要差し替え)・起動し直したらやり直す
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
import live as LV  # noqa: E402
import live_export as LX  # noqa: E402
import prefs as P  # noqa: E402
from ytt_core import fsio, loudness, normalize, schemas, tools  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "recorder", "tests"))
import hls_fixture as F  # noqa: E402

TOKEN = "t" * 40


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_for(fn, timeout=20.0, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class FakeRecorder:
    """録画元の代わり(合言葉と Host を確かめ、受けた要求を覚える)"""

    def __init__(self):
        self.seen = []
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _out(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, body=None):
                owner.seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"),
                                   "host": self.headers.get("Host"), "origin": self.headers.get("Origin"), "body": body})
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self._out(403, b'{"error":"token","message":"x"}', "application/json")
                if self.path == "/api/ping":
                    return self._out(200, b'{"app":"ytt-recorder","version":"0.0.1"}', "application/json")
                if self.path == "/live/list":
                    return self._out(200, json.dumps({"folder": "X:\\rec", "folderOk": True, "folderMessage": "", "freeBytes": 5 * 1024 ** 3,
                                                      "totalBytes": 9 * 1024 ** 3, "streamlink": True, "version": "0.0.1", "active": 1,
                                                      "recordings": [{"id": "20261004-000000-a", "title": "t", "state": "recording", "active": True,
                                                                      "segments": 3, "lastPdt": None, "message": ""}]}).encode(), "application/json")
                if self.path == "/live/20261004-000000-a/index.m3u8":
                    return self._out(200, b"#EXTM3U\n", "application/vnd.apple.mpegurl")
                if self.path == "/live/20261004-000000-a/session_001/seg_000000.ts":
                    return self._out(200, b"\x47" * 188 * 10, "video/mp2t")
                if self.path == "/live/html":
                    return self._out(200, b"<script>alert(1)</script>", "text/html")
                if self.path.startswith("/live/20261004-000000-a/status"):
                    return self._out(200, json.dumps({"path": self.path}).encode(), "application/json")
                return self._out(404, b'{"error":"not_found","message":"x"}', "application/json")

            def do_GET(self):
                self._handle()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._handle(json.loads(self.rfile.read(n).decode()) if n else None)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class PrefsLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-prefs-")
        self.p = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_off_and_validation(self):
        self.assertEqual(self.p.get(["live"])["live"], {"enabled": False, "folder": "", "recorders": []})
        v = self.p.patch("live", {"enabled": True, "folder": "E:\\Video\\live-rec"})
        self.assertEqual((v["enabled"], v["folder"]), (True, "E:\\Video\\live-rec"))
        for bad in ({"folder": "\\\\nas\\rec"}, {"folder": "rec"}, {"recorders": "x"}, {"recorders": [{"id": "Bad", "url": "http://a:8730"}]},
                    {"recorders": [{"id": "a", "url": "http://a:8730/path"}]}, {"recorders": [{"id": "a", "url": "https://a:8730"}]},
                    {"recorders": [{"id": "a", "url": "http://a:80"}]}, {"recorders": [{"id": "a", "url": "http://a:8730", "token": "short"}]},
                    {"recorders": [{"id": "a", "url": "http://a:8730"}, {"id": "a", "url": "http://b:8730"}]},
                    {"recorders": [{"id": "r%d" % i, "url": "http://a:8730"} for i in range(9)]}):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertTrue(self.p.get(["live"])["live"]["enabled"])   # 断ったときは変えない

    def test_token_is_kept_when_blank(self):
        self.p.patch("live", {"recorders": [{"id": "laptop", "name": "ノート PC", "url": "http://192.168.1.20:8730", "token": TOKEN}]})
        v = self.p.patch("live", {"recorders": [{"id": "laptop", "name": "ノート", "url": "http://192.168.1.20:8730", "token": ""}]})
        self.assertEqual(v["recorders"][0]["token"], TOKEN)
        self.assertEqual(v["recorders"][0]["name"], "ノート")
        v = self.p.patch("live", {"recorders": [{"id": "laptop", "name": "ノート", "url": "http://192.168.1.99:8730", "token": ""}]})
        self.assertEqual(v["recorders"][0]["token"], "")   # URL を変えたら前の合言葉は残さない(別の相手へ送らない)


class PortalLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-portal-")
        self.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(self.tmp, ".runtime")})
        self.env.start()
        self.sup = L.Supervisor(self.tmp, only=[], log=lambda m: None, mounts=())
        self.srv, self.port = L.make_server(0, self.sup)
        self.sup.attach(self.srv)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.srv.live.store_dir = os.path.join(self.tmp, "live")   # マークと書き出しの記録(テストはリポジトリの中に書かない)
        self.srv.live.out_dir = lambda: os.path.join(self.tmp, "out")
        self.fake = FakeRecorder()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.fake.close()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, token=True, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Host": "127.0.0.1:%d" % self.port}
        data = None
        if method == "POST":
            data = json.dumps(body or {}).encode("utf-8")
            h["Content-Type"] = "application/json"
            h["Origin"] = "http://127.0.0.1:%d" % self.port
            if token:
                h["X-YTT-Token"] = self.srv.token
        h.update(headers or {})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), raw

    def jreq(self, *a, **kw):
        code, h, raw = self.req(*a, **kw)
        return code, json.loads(raw.decode("utf-8")) if h.get("content-type", "").startswith("application/json") else raw

    def enable(self, **extra):
        v = dict({"enabled": True, "recorders": [{"id": "fake", "name": "偽物", "url": self.fake.url, "token": TOKEN}]}, **extra)
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "patch", "section": "live", "value": v})
        self.assertEqual(code, 200, d)
        return d

    def test_off_is_unchanged(self):
        base = self.jreq("GET", "/no-such-thing")
        for path in ("/live", "/live/", "/live/live.js", "/live/hls.min.js", "/live/api/info", "/live/r/local/list",
                     "/live/api/marks?recorder=local&recording=20261004-000000-a", "/live/api/exports"):
            self.assertEqual(self.jreq("GET", path), base, path)   # 今までと同じ 404
        base_post = self.jreq("POST", "/api/no-such", {})
        self.assertEqual(self.jreq("POST", "/live/r/local/start", {"url": "x"}), base_post)
        for path in ("/live/api/marks", "/live/api/export", "/live/api/export/cancel"):
            self.assertEqual(self.jreq("POST", path, {"op": "add"}), base_post, path)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "live")))   # オフの間は作業データに何も作らない
        self.assertEqual(self.req("POST", "/live/r/local/start", {}, token=False)[0], 403)   # 合言葉の検査も今までどおり
        self.assertNotIn("live", self.jreq("GET", "/api/health")[1])
        self.assertEqual(self.srv.live.tick(), "off")   # 見回りは何もしない(録画の部品を起動しない)
        self.assertEqual(self.srv.live.health(), None)
        self.assertFalse(self.fake.seen)

    def test_on_page_and_relay(self):
        d = self.enable()
        self.assertEqual(d["value"]["recorders"][0]["token"], "")   # 画面へは合言葉を返さない
        self.assertTrue(d["value"]["recorders"][0]["hasToken"])
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "get", "sections": ["live"]})
        self.assertEqual(d["prefs"]["live"]["recorders"][0]["token"], "")
        code, d = self.jreq("POST", "/api/ytt/prefs", {"op": "get"})   # 全部の節を読んでも同じ
        self.assertEqual(d["prefs"]["live"]["recorders"][0]["token"], "")
        # 画面
        self.assertEqual(self.req("GET", "/live")[0], 301)
        code, h, raw = self.req("GET", "/live/")
        self.assertEqual(code, 200)
        self.assertIn("media-src 'self' blob:", h["content-security-policy"])
        self.assertIn("script-src 'self';", h["content-security-policy"])
        self.assertIn(('<meta name="ytt-token" content="%s">' % self.srv.token).encode(), raw)
        code, h, raw = self.req("GET", "/live/hls.min.js")
        self.assertEqual((code, h["content-type"]), (200, "application/javascript; charset=utf-8"))
        self.assertGreater(len(raw), 100000)
        code, d = self.jreq("GET", "/live/api/info")
        self.assertEqual([r["id"] for r in d["recorders"]], ["fake"])
        self.assertEqual(sorted(d["audio"]), ["loudness", "volume"])   # 書き出しの音量(スタジオと同じ設定)・開始の補正の最初の値
        self.assertIn(d["lag"], (0, 2, 3, 5))
        self.assertNotIn(TOKEN, json.dumps(d))
        # 中継: 合言葉と Host を付ける。ブラウザの Origin は渡さない
        code, d = self.jreq("GET", "/live/r/fake/list")
        self.assertEqual(code, 200, d)
        self.assertEqual(d["active"], 1)
        last = self.fake.seen[-1]
        self.assertEqual((last["auth"], last["host"], last["path"]), ("Bearer " + TOKEN, "127.0.0.1:%d" % self.fake.port, "/live/list"))
        code, h, raw = self.req("GET", "/live/r/fake/20261004-000000-a/index.m3u8")
        self.assertEqual((code, h["content-type"], h["cache-control"]), (200, "application/vnd.apple.mpegurl", "no-cache"))
        code, h, raw = self.req("GET", "/live/r/fake/20261004-000000-a/session_001/seg_000000.ts")
        self.assertEqual((code, h["content-type"], len(raw)), (200, "video/mp2t", 1880))
        code, d = self.jreq("GET", "/live/r/fake/20261004-000000-a/status?since=5")
        self.assertEqual(d["path"], "/live/20261004-000000-a/status?since=5")
        code, d = self.jreq("POST", "/live/r/fake/start", {"url": "https://www.youtube.com/watch?v=x"})
        self.assertEqual(code, 404)   # 偽物は start を知らない(中継はそのまま返す)
        self.assertEqual(self.fake.seen[-1]["body"], {"url": "https://www.youtube.com/watch?v=x"})
        self.assertIsNone(self.fake.seen[-1]["origin"])
        # 検査
        n = len(self.fake.seen)
        self.assertEqual(self.req("GET", "/live/r/fake/list", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("GET", "/live/r/fake/list", headers={"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.req("POST", "/live/r/fake/start", {}, token=False)[0], 403)
        self.assertEqual(self.req("POST", "/live/r/fake/start", {}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.jreq("GET", "/live/r/nope/list")[0], 404)
        for bad in ("/live/r/fake/../x", "/live/r/fake/a//b", "/live/r/fake/%2e%2e/x", "/live/r/FAKE/list", "/live/x"):
            self.assertEqual(self.req("GET", bad)[0], 404, bad)
        self.assertEqual(len(self.fake.seen), n)   # 断った要求は録画元へ届かない
        self.assertEqual(self.jreq("GET", "/live/r/fake/html")[0], 502)   # 思わぬ種類(HTML)は返さない
        # 「調子」
        h = self.jreq("GET", "/api/health")[1]
        self.assertEqual(h["live"]["recorders"][0]["ok"], True)
        self.assertEqual(h["live"]["recorders"][0]["freeBytes"], 5 * 1024 ** 3)
        self.assertEqual(h["live"]["recorders"][0]["active"], 1)
        # 録画元が止まっている
        self.fake.close()
        code, d = self.jreq("GET", "/live/r/fake/list")
        self.assertEqual((code, d["error"]), (502, "recorder_down"))
        h = self.jreq("GET", "/api/health")[1]
        self.assertFalse(h["live"]["recorders"][0]["ok"])
        self.fake = FakeRecorder()   # tearDown で閉じる分

    def test_marks_api(self):
        self.enable()
        rec = "20261004-000000-a"
        q = "/live/api/marks?recorder=fake&recording=" + rec
        code, d = self.jreq("GET", q)
        self.assertEqual((code, d["marks"], d["exports"]), (200, [], []))
        code, d = self.jreq("POST", "/live/api/marks", {"op": "add", "recorder": "fake", "recording": rec, "start": "2026-10-04T06:00:00.000Z",
                                                        "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信<b>"})
        self.assertEqual(code, 200, d)
        m = d["mark"]
        self.assertEqual((m["n"], m["start"], m["end"]), (1, "2026-10-04T06:00:00.000Z", None))
        path = os.path.join(self.tmp, "live", "marks", "fake__%s.json" % rec)
        with open(path, encoding="utf-8") as f:   # 正本(押すたびに置き換える)
            saved = json.load(f)
        self.assertEqual((saved["schema"], saved["title"], len(saved["marks"])), (LX.MARKS_SCHEMA, "配信<b>", 1))
        code, d = self.jreq("POST", "/live/api/export", {"recorder": "fake", "recording": rec, "markId": m["id"]})
        self.assertEqual(code, 400)   # 終了が無いと書き出せない
        for bad in ({"op": "update", "id": m["id"], "end": "2026-10-04T05:59:59.000Z"},     # 開始より前
                    {"op": "update", "id": m["id"], "end": "2026-10-04T07:00:01.000Z"},     # 1 時間を超える
                    {"op": "update", "id": m["id"], "end": "x"}, {"op": "add"}, {"op": "add", "start": "2026-13-01T00:00:00Z"},
                    {"op": "nope"}):
            code, d = self.jreq("POST", "/live/api/marks", dict(bad, recorder="fake", recording=rec))
            self.assertEqual(code, 400, (bad, d))
        self.assertEqual(self.jreq("POST", "/live/api/marks", {"op": "update", "id": "lm-0000000000", "recorder": "fake", "recording": rec,
                                                               "label": "x"})[0], 404)
        self.assertEqual(self.jreq("POST", "/live/api/marks", {"op": "add", "recorder": "nope", "recording": rec, "start": m["start"]})[0], 404)
        self.assertEqual(self.jreq("POST", "/live/api/marks", {"op": "add", "recorder": "fake", "recording": "../x", "start": m["start"]})[0], 400)
        code, d = self.jreq("POST", "/live/api/marks", {"op": "update", "id": m["id"], "recorder": "fake", "recording": rec,
                                                        "end": "2026-10-04T06:00:30.5Z", "label": "見どころ\n"})
        self.assertEqual((code, d["mark"]["end"], d["mark"]["label"]), (200, "2026-10-04T06:00:30.500Z", "見どころ"), d)
        self.assertEqual(self.req("POST", "/live/api/marks", {"op": "delete", "id": m["id"], "recorder": "fake", "recording": rec}, token=False)[0], 403)
        code, d = self.jreq("POST", "/live/api/marks", {"op": "delete", "id": m["id"], "recorder": "fake", "recording": rec})
        self.assertEqual((code, d["marks"]), (200, []))
        code, d = self.jreq("GET", "/live/api/exports")
        self.assertEqual((code, d["jobs"]), (200, []))
        self.assertEqual(self.jreq("POST", "/live/api/export/cancel", {"id": "lx-0000000000"})[0], 404)

    def test_default_recorder_is_local(self):
        self.jreq("POST", "/api/ytt/prefs", {"op": "patch", "section": "live", "value": {"enabled": True}})
        code, d = self.jreq("GET", "/live/api/info")
        self.assertEqual(d["recorders"], [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:8730", "local": True}])
        self.assertEqual(d["defaultFolder"], "E:\\Video\\live-rec")


class SpawnTest(unittest.TestCase):
    """見回りが本物の録画の部品(recorder/recorder.py)を切り離して起動する"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-spawn-")
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.port = free_port()
        self.rec_folder = os.path.join(self.tmp, "live-rec")
        self.prefs.patch("live", {"enabled": True, "folder": self.rec_folder,
                                  "recorders": [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % self.port}]})
        self.logs = []
        self.live = LV.Live(self.prefs, REPO, os.path.join(self.tmp, "logs"), log=self.logs.append, data_dir=os.path.join(self.tmp, "recdata"))

    def tearDown(self):
        rc = self.live.find("local")
        if rc and self.live.ping(rc):
            self.live.call(rc, "POST", "/live/quit", {})
            wait_for(lambda: not self.live.ping(rc, 0.5), 15)
        if self.live.proc:
            try:
                self.live.proc.wait(10)
            except Exception:
                self.live.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_spawn_then_running_then_restart_old_version(self):
        self.assertEqual(self.live.tick(), "spawned", self.logs)
        rc = self.live.find("local")
        self.assertTrue(wait_for(lambda: self.live.ping(rc), 30), self.logs)
        self.assertTrue(self.live.local_token())   # 録画の部品が作った合言葉を読める
        rc = self.live.find("local")               # 合言葉は起動したあとにできる(読み直す)
        self.assertEqual(self.live.tick(), "running")
        code, d = self.live.call(rc, "GET", "/live/list")
        self.assertEqual(code, 200, d)
        self.assertEqual(os.path.normcase(d["folder"]), os.path.normcase(self.rec_folder))   # 設定の置き場所で起動した
        h = self.live.health()
        self.assertTrue(h["recorders"][0]["ok"])
        self.assertEqual(h["recorders"][0]["version"], h["recorders"][0]["expected"])
        # 置き場所を変えた → 見回りが伝える
        other = os.path.join(self.tmp, "other")
        self.prefs.patch("live", {"folder": other})
        self.assertEqual(self.live.tick(), "running")
        self.assertEqual(os.path.normcase(self.live.call(rc, "GET", "/live/config")[1]["folder"]), os.path.normcase(other))
        # コードの版が上がった → 録画中でなければ終わってもらって起動し直す
        old = self.live.proc
        with mock.patch.object(self.live, "expected_version", return_value="99.0.0"):
            self.assertEqual(self.live.tick(), "spawned", self.logs)
        self.assertIsNot(self.live.proc, old)
        self.assertEqual(old.wait(15), 0)
        self.assertTrue(wait_for(lambda: self.live.ping(rc), 30), self.logs)
        # オフにすると見回りは何もしない(録画の部品は止めない)
        self.prefs.patch("live", {"enabled": False})
        self.assertEqual(self.live.tick(), "off")
        self.assertTrue(self.live.ping(rc))


class FakeRunner:
    """まとめて実行の代わり(文字起こしへ渡した動画を覚える)"""

    def __init__(self):
        self.files = []

    def start_file(self, path, title="", flow="check", **kw):
        self.files.append((path, title, flow))
        return {"id": "run-%d" % len(self.files)}

    def snapshot(self):
        return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち"} for i in range(len(self.files))]}


_SRC = {}


def source(seconds=60):
    if seconds not in _SRC:
        d = tempfile.mkdtemp(prefix="ytt-live-src-")
        _SRC[seconds] = (d, F.make_source(d, seconds))
    return _SRC[seconds]


class ExportTest(unittest.TestCase):
    """本物の録画の部品(--source direct)で配信中のふりの HLS を録り、マーク → 書き出す"""

    @classmethod
    def setUpClass(cls):
        cls.src_dir, cls.segs = source(60)

    @classmethod
    def tearDownClass(cls):
        for d, _ in _SRC.values():
            shutil.rmtree(d, ignore_errors=True)
        _SRC.clear()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-export-")
        self.src = F.LiveServer(self.src_dir, self.segs, start=3, rate=1.0)
        self.src.end = False
        self.port = free_port()
        self.rdata = os.path.join(self.tmp, "recdata")
        self.proc = subprocess.Popen([sys.executable, os.path.join(REPO, "recorder", "recorder.py"), "--port", str(self.port), "--data-dir", self.rdata,
                                      "--folder", os.path.join(self.tmp, "live-rec"), "--source", "direct", "--hls-time", "1", "--quiet"],
                                     env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.assertTrue(wait_for(lambda: os.path.isfile(os.path.join(self.rdata, "token.txt")), 20))
        time.sleep(0.2)
        with open(os.path.join(self.rdata, "token.txt"), encoding="ascii") as f:
            token = f.read().strip()
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.prefs.patch("live", {"enabled": True, "recorders": [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % self.port, "token": token}]})
        self.runner = FakeRunner()
        self.out = os.path.join(self.tmp, "out")
        self.audio = {"volume": 100, "loudness": None}   # 既定の書き出しは音量そのまま(音量の確認は test_audio_like_studio)
        self.live = LV.Live(self.prefs, REPO, os.path.join(self.tmp, "logs"), store_dir=os.path.join(self.tmp, "live"),
                            out_dir=lambda: self.out, runner=lambda: self.runner, spawn=False, audio=lambda: self.audio)
        self.rc = self.live.find("local")
        self.assertTrue(wait_for(lambda: self.live.ping(self.rc), 20))
        self.ex = self.live.exporter
        self.ex.poll, self.ex.down_sec = 0.3, 3.0

    def tearDown(self):
        self.live.close()
        try:
            for r in (self.live.call(self.rc, "GET", "/live/list")[1] or {}).get("recordings") or []:
                if r.get("active"):
                    self.live.call(self.rc, "POST", "/live/%s/stop" % r["id"], {}, timeout=40)
            self.live.call(self.rc, "POST", "/live/quit", {})
            self.proc.wait(20)
        except Exception:
            self.proc.kill()
        self.src.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start_rec(self, n=4):
        code, d = self.live.call(self.rc, "POST", "/live/start", {"url": self.src.url, "title": "テストの配信"}, timeout=10)
        self.assertEqual(code, 200, d)
        rid = d["recording"]["id"]
        self.assertTrue(wait_for(lambda: (self.live.call(self.rc, "GET", "/live/%s/status" % rid)[1] or {}).get("segments", 0) >= n, 40))
        return rid

    def status(self, rid):
        return self.live.call(self.rc, "GET", "/live/%s/status" % rid)[1]

    def mark(self, rid, start, end, label=""):
        m, _ = self.ex.marks.apply("local", rid, {"op": "add", "start": LX.epoch_iso(start), "end": LX.epoch_iso(end), "label": label,
                                                  "url": self.src.url, "title": "テストの配信"})
        return m

    def job(self, jid):
        return next(j for j in self.ex.snapshot() if j["id"] == jid)

    def wait_state(self, jid, states, timeout=60):
        return wait_for(lambda: self.job(jid)["state"] in states and self.job(jid), timeout, 0.3)

    def test_mark_wait_export_transcribe_cancel(self):
        rid = self.start_rec()
        st = self.status(rid)
        first, last = LX.iso_epoch(st["firstPdt"]), LX.iso_epoch(st["lastPdt"])
        # 録画中: 終わりがまだ録れていない所までのマーク → 録画待ち → 届いたら書き出す
        a, b = first + 1.5, last + 3.0
        m = self.mark(rid, a, b, "見どころ: 1")
        j = self.ex.add("local", rid, m["id"], transcribe=True)
        self.assertEqual(j["state"], "wait")
        self.assertTrue(wait_for(lambda: "待っています" in (self.job(j["id"]).get("message") or "") or self.job(j["id"])["state"] != "wait", 10))
        done = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(done["state"], "done", done)
        path = done["path"]
        self.assertTrue(os.path.isfile(path), path)
        self.assertEqual(os.path.dirname(os.path.dirname(path)), self.out)   # 書き出し先\<配信の名前>\
        self.assertEqual(os.path.basename(os.path.dirname(path)), "テストの配信")
        self.assertRegex(os.path.basename(path), r"^01_00h00m0\ds-00h00m\d\ds_見どころ_ 1\.mp4$")
        info = normalize.probe(path)
        self.assertTrue(normalize.is_30fps(info), info)
        self.assertAlmostEqual(info["duration"], b - a, delta=0.1)
        self.assertFalse([n for n in os.listdir(os.path.dirname(path)) if ".partial" in n])   # 書きかけは残さない
        clip, warn = schemas.load_clip_file(schemas.find_clip_path(path))
        self.assertIsNone(warn)
        self.assertEqual(clip["source"]["kind"], "live")
        self.assertIsNone(clip["source"]["url"])
        self.assertEqual((clip["source"]["live"]["recording"], clip["source"]["live"]["recorder"]), (rid, "local"))
        self.assertEqual(clip["source"]["live"]["start"], LX.epoch_iso(a))
        self.assertAlmostEqual(clip["range"]["start"], a - LX.iso_epoch(clip["source"]["live"]["base"]), delta=0.01)
        self.assertAlmostEqual(clip["range"]["end"] - clip["range"]["start"], b - a, delta=0.01)
        self.assertEqual((clip["mark"]["id"], clip["mark"]["label"], clip["export"]["mode"]), (m["id"], "見どころ: 1", "precise"))
        self.assertEqual(self.runner.files, [(path, os.path.splitext(os.path.basename(path))[0], "check")])   # 文字起こしへ(まとめて実行の文字起こしだけ)
        self.assertEqual(done["runId"], "run-1")
        self.assertEqual(self.job(j["id"])["tx"]["state"], "queued")
        self.assertFalse(os.listdir(os.path.join(self.tmp, "live", "work")))   # 取ったセグメントは片付ける
        # 文字起こしなし・同じマークをもう一度 → 別の名前
        j2 = self.ex.add("local", rid, m["id"], transcribe=False)
        d2 = self.wait_state(j2["id"], ("done", "error"), 90)
        self.assertEqual(d2["state"], "done", d2)
        self.assertNotEqual(d2["path"], path)
        self.assertEqual(len(self.runner.files), 1)
        # 取り消し(録画待ちの間)
        far = self.mark(rid, last + 100, last + 110)
        j3 = self.ex.add("local", rid, far["id"])
        with self.assertRaises(LX.LiveError):
            self.ex.add("local", rid, far["id"])   # 同じマークは途中のものがあれば断る
        self.assertEqual(self.ex.cancel(j3["id"])["state"], "cancelled")
        # 記録は exports.json に残る(起動し直しても見える)
        again = LX.Exporter(self.live, os.path.join(self.tmp, "live"), lambda: self.out)
        self.assertEqual({x["id"]: x["state"] for x in again.jobs}, {j["id"]: "done", j2["id"]: "done", j3["id"]: "cancelled"})

    def loud_of(self, path):
        """書き出した動画の聞こえ方の音量(LUFS)とピーク(dBTP)。ffmpeg の loudnorm で測るだけ"""
        r = subprocess.run([tools.find_tool("ffmpeg", "YTT_FFMPEG"), "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "loudnorm=print_format=json",
                            "-f", "null", "-"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return loudness.parse(r.stdout.decode("utf-8", "replace"))

    def test_audio_like_studio(self):
        """書き出しの音量はスタジオと同じ扱い: ラウドネスをそろえる(測って音声だけ作り直し・.clip.json に結果)/ 音量(%)/ 変えない。30fps・長さはそのまま"""
        rid = self.start_rec(10)
        first = LX.iso_epoch(self.status(rid)["firstPdt"])
        a, b = first + 1.0, first + 7.0
        m = self.mark(rid, a, b)

        def run(audio):
            self.audio = audio
            j = self.ex.add("local", rid, m["id"], transcribe=False)
            d = self.wait_state(j["id"], ("done", "error"), 90)
            self.assertEqual(d["state"], "done", d)
            info = normalize.probe(d["path"])
            self.assertTrue(normalize.is_30fps(info), info)
            self.assertAlmostEqual(info["duration"], b - a, delta=0.2)
            self.assertEqual(info["acodec"], "aac")
            self.assertFalse([n for n in os.listdir(os.path.dirname(d["path"])) if ".partial" in n or ".vol" in n])
            return d["path"], schemas.load_clip_file(schemas.find_clip_path(d["path"]))[0]["export"]
        p0, ex0 = run({"volume": 100, "loudness": None})
        self.assertEqual(ex0["volume"], 100)
        base_i, _tp = self.loud_of(p0)
        p1, ex1 = run({"volume": 50, "loudness": None})   # 50% = -6 dB
        self.assertEqual((ex1["volume"], "loudness" in ex1), (50, False))
        self.assertAlmostEqual(self.loud_of(p1)[0], base_i - 6.02, delta=0.6)
        p2, ex2 = run({"volume": 75, "loudness": -14.0})   # ラウドネスがあるときは音量(%)は使わない
        self.assertNotIn("volume", ex2)
        self.assertEqual(ex2["loudness"]["target"], -14.0)
        self.assertAlmostEqual(ex2["loudness"]["measured"], base_i, delta=0.6)   # 測った値 = そろえる前の聞こえ方
        self.assertAlmostEqual(ex2["loudness"]["gainDb"], -14.0 - base_i, delta=0.6)
        self.assertAlmostEqual(self.loud_of(p2)[0], -14.0, delta=1.0)             # そろった
        self.assertEqual(os.path.dirname(p0), os.path.dirname(p2))

    def test_cancel_while_encoding(self):
        rid = self.start_rec(12)
        st = self.status(rid)
        first = LX.iso_epoch(st["firstPdt"])
        m = self.mark(rid, first + 0.5, first + 10.0)
        real = normalize.encode_args
        with mock.patch.object(normalize, "encode_args", lambda *a, **k: [x if x != "veryfast" else "veryslow" for x in real(*a, **k)]):
            j = self.ex.add("local", rid, m["id"])
            self.assertTrue(self.wait_state(j["id"], ("encode", "done", "error"), 60))
            self.ex.cancel(j["id"])
            got = self.wait_state(j["id"], ("cancelled", "done", "error"), 30)
        self.assertEqual(got["state"], "cancelled", got)
        folder = os.path.join(self.out, "テストの配信")
        self.assertFalse([n for n in os.listdir(folder) if n.endswith(".mp4")] if os.path.isdir(folder) else [])   # 書きかけも残さない

    def test_recording_ended_and_recorder_down(self):
        rid = self.start_rec()
        self.live.call(self.rc, "POST", "/live/%s/stop" % rid, {}, timeout=40)
        st = self.status(rid)
        first, last = LX.iso_epoch(st["firstPdt"]), LX.iso_epoch(st["lastPdt"])
        # 録画が先に終わった: 録れた所までで切る
        m = self.mark(rid, first + 0.5, last + 20)
        j = self.ex.add("local", rid, m["id"], transcribe=False)
        d = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(d["state"], "done", d)
        self.assertIn("録画の終わり", d["warning"])
        self.assertAlmostEqual(normalize.probe(d["path"])["duration"], last - (first + 0.5), delta=0.15)
        # 区間に録画が無い(録画より後)→ 失敗と理由
        m2 = self.mark(rid, last + 30, last + 40)
        j2 = self.ex.add("local", rid, m2["id"])
        d2 = self.wait_state(j2["id"], ("done", "error"), 30)
        self.assertEqual(d2["state"], "error")
        self.assertIn("届きませんでした", d2["error"])
        # 録画元が落ちた → 録画待ちのまま down_sec 秒 → 失敗と理由
        self.live.call(self.rc, "POST", "/live/quit", {})
        self.proc.wait(20)
        m3 = self.mark(rid, first + 1, first + 3)
        j3 = self.ex.add("local", rid, m3["id"])
        d3 = self.wait_state(j3["id"], ("done", "error"), 30)
        self.assertEqual(d3["state"], "error", d3)
        self.assertIn("つながりませんでした", d3["error"])


class StudioSettingsTest(unittest.TestCase):
    """書き出しの音量・反応の遅れ補正はスタジオの設定(settings-ui.json の review)に合わせる。読めないときはスタジオの既定(75% ・ -14 LUFS ・ なし)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-studio-")
        self.patch = mock.patch.object(LV.datadir, "resolve", lambda tool, root=None, **kw: self.tmp)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, review):
        with open(os.path.join(self.tmp, "settings-ui.json"), "w", encoding="utf-8") as f:
            json.dump({"review": review, "other": {}}, f)

    def test_defaults_when_unreadable(self):
        self.assertEqual(LV.studio_audio(REPO), {"volume": 75, "loudness": -14.0})   # studio/review.js の DEFAULT_SETTINGS と同じ
        self.assertEqual(LV.studio_lag(REPO), 0)
        with open(os.path.join(self.tmp, "settings-ui.json"), "w", encoding="utf-8") as f:
            f.write("{ broken")
        self.assertEqual(LV.studio_audio(REPO), {"volume": 75, "loudness": -14.0})
        self.put({})
        self.assertEqual((LV.studio_audio(REPO), LV.studio_lag(REPO)), ({"volume": 75, "loudness": -14.0}, 0))

    def test_follows_studio_settings(self):
        self.put({"exportVolume": 90, "exportLoudness": 0, "lag": 3})   # 0 = そろえない(音量 % を使う)
        self.assertEqual(LV.studio_audio(REPO), {"volume": 90, "loudness": None})
        self.assertEqual(LV.studio_lag(REPO), 3)
        self.put({"exportVolume": 120.4, "exportLoudness": -16, "lag": 5})
        self.assertEqual(LV.studio_audio(REPO), {"volume": 120, "loudness": -16.0})
        self.assertEqual(LV.studio_lag(REPO), 5)

    def test_bad_values_fall_back_like_studio(self):
        self.put({"exportVolume": 9999, "exportLoudness": -99, "lag": 7})
        self.assertEqual(LV.studio_audio(REPO), {"volume": 200, "loudness": -14.0})   # 範囲に丸める・選べない値は既定
        self.assertEqual(LV.studio_lag(REPO), 0)
        self.put({"exportVolume": "x", "exportLoudness": None, "lag": None})
        self.assertEqual((LV.studio_audio(REPO), LV.studio_lag(REPO)), ({"volume": 75, "loudness": -14.0}, 0))
        self.put({"exportVolume": -5, "exportLoudness": "abc", "lag": [1]})
        self.assertEqual((LV.studio_audio(REPO), LV.studio_lag(REPO)), ({"volume": 1, "loudness": -14.0}, 0))

    def test_exporter_ignores_bad_audio(self):
        for bad, want in ((None, (100, None)), ({"volume": 50, "loudness": None}, (50, None)), ({"volume": 75, "loudness": -14}, (75, -14.0)),
                          ({"volume": 999, "loudness": -3}, (100, None)), ("x", (100, None))):
            ex = LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: self.tmp, audio=(lambda b=bad: b) if bad is not None else None)
            self.assertEqual(ex._audio_cfg(), want, bad)
        self.assertEqual(LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: self.tmp, audio=mock.Mock(side_effect=OSError))._audio_cfg(), (100, None))


class ExportPiecesTest(unittest.TestCase):
    tearDownClass = ExportTest.tearDownClass   # lavfi の HLS(source)を片付ける

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-pieces-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_names_like_studio(self):
        self.assertEqual(LX.compact_ts(3725.9), "01h02m05s")
        self.assertEqual(LX.safe_name('a/b:c*?"<>|%d', 30), "a_b_c_d")
        self.assertEqual(LX.video_id_of("https://www.youtube.com/watch?v=abcdefghijk"), "abcdefghijk")
        self.assertEqual(LX.video_id_of("https://youtu.be/abcdefghij-"), "abcdefghij-")
        self.assertEqual(LX.video_id_of("https://www.youtube.com/@x/live", "20261004-000000-ab-defghijk"), "ab-defghijk")
        self.assertEqual(LX.video_id_of("http://127.0.0.1:1/live.m3u8", "20261004-000000-a1b2c3"), "")
        root = os.path.join(self.tmp, "out")
        os.makedirs(root)
        p1 = LX.pick_folder(root, "配信:1", "abcdefghijk")
        self.assertEqual(os.path.basename(p1), "配信_1")
        self.assertEqual(LX.pick_folder(root, "配信:1", "abcdefghijk"), p1)        # 同じ配信は同じフォルダ
        self.assertEqual(os.path.basename(LX.pick_folder(root, "配信:1", "live-x")), "配信_1_2")   # 同じ名前の別の配信とは混ぜない
        with open(os.path.join(p1, schemas.WORK_DIR, ".studio-id"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "abcdefghijk")   # スタジオと同じ持ち主の印
        open(os.path.join(p1, "01_x.mp4"), "wb").close()
        os.makedirs(os.path.join(p1, schemas.WORK_DIR), exist_ok=True)
        open(os.path.join(p1, schemas.WORK_DIR, "01_x_2_edit.mp4"), "wb").close()
        self.assertEqual(LX.unique_base("01_x", p1), "01_x_3")

    def test_restart_resets_running_jobs(self):
        folder = os.path.join(self.tmp, "live")
        os.makedirs(os.path.join(folder, "work", "lx-0123456789"))
        jobs_ = [{"id": "lx-0123456789", "state": "encode", "recorder": "local", "recording": "20261004-000000-a", "markId": "lm-0123456789"},
                 {"id": "lx-9876543210", "state": "done", "recorder": "local", "recording": "20261004-000000-a", "markId": "lm-0123456789"},
                 {"id": "bad", "state": "wait"}]
        fsio.write_json(os.path.join(folder, "exports.json"), {"schema": LX.JOBS_SCHEMA, "jobs": jobs_})
        ex = LX.Exporter(mock.Mock(), folder, lambda: self.tmp)
        self.assertEqual([(j["id"], j["state"]) for j in ex.jobs], [("lx-0123456789", "wait"), ("lx-9876543210", "done")])
        self.assertIn("やり直します", ex.jobs[0]["message"])
        self.assertFalse(os.path.exists(os.path.join(folder, "work")))   # 前回の取りかけは消す
        self.assertTrue(ex.pending())

    def test_encode_across_sessions(self):
        """繋ぎ直しをまたぐ(欠けは無い)区間: セッションごとのファイルを concat でつないで、区間の長さ・30/1 で書き出す"""
        src_dir, segs = source(60)
        folder = os.path.join(self.tmp, "live")
        ex = LX.Exporter(mock.Mock(), folder, lambda: os.path.join(self.tmp, "out"))
        wdir = os.path.join(folder, "work", "lx-0000000001")
        os.makedirs(wdir)
        files = []
        for k, part in enumerate((segs[2:5], segs[5:9])):
            p = os.path.join(wdir, "part_%02d.ts" % k)
            with open(p, "wb") as f:
                for name, _ in part:
                    with open(os.path.join(src_dir, name), "rb") as g:
                        f.write(g.read())
            files.append((p, "session_%03d" % (k + 1)))
        a = LX.iso_epoch("2026-10-04T06:00:00Z")
        seg_list = [{"uri": "session_001/seg_000000.ts", "session": "session_001", "pdt": LX.epoch_iso(a - 0.5), "dur": 1.0}]
        job = {"id": "lx-0000000001", "n": 3, "label": "", "recorder": "local", "recording": "20261004-000000-a"}
        d = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "またぐ", "firstPdt": LX.epoch_iso(a - 60)}
        out, tmp = ex._encode(job, {"id": "local"}, job["recording"], d, seg_list, files, a, a + 5.0, wdir)
        self.assertIsNone(tmp)
        self.assertTrue(normalize.is_30fps(out))
        self.assertAlmostEqual(out["duration"], 5.0, delta=0.1)
        self.assertEqual(os.path.basename(out["path"]), "03_00h01m00s-00h01m05s.mp4")   # 名前の時刻は録画の頭(firstPdt)からの秒
        self.assertEqual(os.path.basename(os.path.dirname(out["path"])), "またぐ")

    def test_gap_means_needs_archive(self):
        """区間に欠け(繋ぎ直しの間)があれば、書き出さずに「要差し替え」"""
        folder = os.path.join(self.tmp, "live")
        live = mock.Mock()
        live.find.return_value = {"id": "local", "name": "この PC"}
        live.recorders.return_value = [{"id": "local", "name": "この PC"}]
        ex = LX.Exporter(live, folder, lambda: os.path.join(self.tmp, "out"))
        m, _ = ex.marks.apply("local", "20261004-000000-a", {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:20Z"})
        job = ex.add("local", "20261004-000000-a", m["id"])
        ex.close()   # 見回りは止めて、ここで1本だけ動かす
        ex._halt.clear()
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "state": "recording", "active": True, "lastPdt": "2026-10-04T06:10:00.000Z",
               "firstPdt": "2026-10-04T05:00:00.000Z", "segments": [{"uri": "session_001/seg_000000.ts", "session": "session_001",
                                                                     "pdt": "2026-10-04T05:59:58.000Z", "dur": 4.0}],
               "gaps": [{"from": "2026-10-04T06:00:02.000Z", "to": "2026-10-04T06:00:12.000Z", "sec": 10.0}]}
        with mock.patch.object(ex, "_query", return_value=(200, ans)):
            j = ex.jobs[0]
            self.assertIs(ex._next_ready(), j)
            ex._process(j)
        self.assertEqual(j["state"], "error")
        self.assertTrue(j["needsArchive"])
        self.assertIn("要差し替え", j["error"])
        self.assertIn("06:00:02", j["error"])
        live.request.assert_not_called()   # 欠けのある録画は取りに行かない
        self.assertEqual(job["id"], j["id"])


if __name__ == "__main__":
    unittest.main()
