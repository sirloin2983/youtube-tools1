# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P1)の入口の側(src/home/live.py・prefs の節 live・launch.py の /live/…・「調子」の行)のテスト。

    py -3.10 -m unittest src/home/tests/test_live.py

確かめること:
  - 設定 live: 既定はオフ・形の検査・合言葉は空で送っても今の値を残す・画面へ返す設定に合言葉を出さない
  - オフ: /live/… は今までと同じ 404(GET・POST とも)・「調子」に live が出ない・見回りは何もしない
  - オン: 以前の録画の画面 /live/ はスタジオへ 302(P3)・hls.js の同梱・録画元の一覧(合言葉を出さない)・中継(合言葉 Bearer と Host を付ける・
    Sec-Fetch-Site と入口の合言葉の検査・知らない録画元・パスの検査・思わぬ種類の応答・録画元が止まっている)・「調子」の行
  - 見回り: 手元の録画の部品(src/recorder/recorder.py)を切り離して起動する → 動いている → 古い版なら終わってもらって起動し直す
  - P2 マークと書き出し(src/home/live_export.py): マークの API(オフなら 404・検査・fsync した正本)・本物の録画の部品(--source direct)で
    録画中にマーク → 録画待ち → 届いたら取得 → 30fps(30/1・長さ)→ スタジオと同じ置き場所・名前・.clip.json(source.kind live)→
    文字起こしへ(偽のまとめて実行)・取り消し・録画が先に終わった(録れた所まで)・録画元が落ちた(失敗と理由)・欠け(要差し替え)・起動し直したらやり直す
  - P3 スタジオから: POST /live/api/begin(URL の検査・偽の yt-dlp で配信の状態・録画を始める・同じ配信は録画中のものを返す・画質の設定・
    録画元が止まっている)・POST /live/api/export の studio の形(録画の頭からの秒 → 絶対時刻・正本の id・値の検査・録画がまだ始まっていない)・
    api/ytt/live(status: オフなら録画元に聞かない・録画中 + 終わって 10 分以内・3 秒覚える / stop)・yt-dlp の呼び方(probe_live。偽の yt-dlp)
"""
import contextlib
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
import live_failures as LF  # noqa: E402
import prefs as P  # noqa: E402
from ytt_core import fsio, jobs, loudness, normalize, schemas, tools  # noqa: E402
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
        self.routes = {}   # (method, path) -> fn(body) -> (HTTP の番号, JSON)。path は ? の前まで。無ければ下の決まった応答
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
                fn = owner.routes.get((self.command, self.path.split("?")[0]))
                if fn is not None:
                    code, obj = fn(body)
                    return self._out(code, json.dumps(obj).encode(), "application/json")
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

    def test_stored_live_keeps_good_keys_when_one_is_broken(self):
        """保存してある live の節に壊れた値が 1 つあっても、その鍵だけ既定に戻す(録画元の一覧・置き場所・オンは残す。10-08。前は節ごと既定に戻った)"""
        path = os.path.join(self.tmp, "prefs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"live": {"enabled": True, "folder": "E:\\Video\\live-rec", "quality": "4k", "autoAfterStream": True, "afterStreamPerHour": "6",
                                "recorders": [{"id": "local", "url": "http://127.0.0.1:8720", "token": ""}],
                                "auto": {"after": "auto", "pad": 99}, "autoAdopt": {"enabled": True, "waitMin": 0}, "detect": "x"}}, f)
        v = P.Prefs(path, fsio.atomic_write).get(["live"])["live"]
        self.assertEqual((v["enabled"], v["folder"], v["quality"], v["autoAfterStream"], v["afterStreamPerHour"], [r["id"] for r in v["recorders"]]),
                         (True, "E:\\Video\\live-rec", "1080p", True, 6, ["local"]))
        self.assertEqual((v["auto"]["after"], v["auto"]["pad"], v["autoAdopt"], v["detect"]["enabled"]), ("auto", 2, {"enabled": True, "waitMin": 5}, True))
        with open(path, "w", encoding="utf-8") as f:   # 節そのものが dict でなければ既定
            json.dump({"live": [1, 2]}, f)
        self.assertEqual(P.Prefs(path, fsio.atomic_write).get(["live"])["live"], P.DEFAULTS["live"])

    def test_default_off_and_validation(self):
        self.assertEqual(self.p.get(["live"])["live"], {"enabled": False, "folder": "", "recorders": [], "quality": "1080p", "autoArchive": True,
                                                        "autoDelete": P.DEFAULTS["live"]["autoDelete"],
                                                        "auto": {"after": "check", "cut": "", "engine": "", "model": "", "pad": 2},   # pad = 自動・アーカイブの採用の前後の余白(M8)
                                                        "autoAfterStream": False, "afterStreamPerHour": 6,   # 配信後の全自動(M7)は既定オフ
                                                        "detect": {"enabled": True, "sens": "normal", "perHour": 6},   # 配信中の検出(L2)・自動の採用(M11)は既定オン(0.46.3。リアルタイム切り抜きがオンのときだけ動く)
                                                        "autoAdopt": {"enabled": True, "waitMin": 5}})
        self.assertIsInstance(P.DEFAULTS["live"]["autoDelete"], bool)
        self.assertEqual(self.p.patch("live", {"auto": {"pad": 0}})["auto"]["pad"], 0)   # 余白は 0〜5 秒(小数も可)。ほかの鍵はそのまま
        self.assertEqual(self.p.patch("live", {"auto": {"pad": 3.5}})["auto"], {"after": "check", "cut": "", "engine": "", "model": "", "pad": 3.5})
        for bad in (-1, 6, True, "2", None):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", {"auto": {"pad": bad}})
        self.p.patch("live", {"auto": {"pad": 2}})
        v = self.p.patch("live", {"enabled": True, "folder": "E:\\Video\\live-rec"})
        self.assertEqual((v["enabled"], v["folder"]), (True, "E:\\Video\\live-rec"))
        for bad in ({"folder": "\\\\nas\\rec"}, {"folder": "rec"}, {"recorders": "x"}, {"recorders": [{"id": "Bad", "url": "http://a:8730"}]},
                    {"recorders": [{"id": "a", "url": "http://a:8730/path"}]}, {"recorders": [{"id": "a", "url": "https://a:8730"}]},
                    {"recorders": [{"id": "a", "url": "http://a:80"}]}, {"recorders": [{"id": "a", "url": "http://a:8730", "token": "short"}]},
                    {"recorders": [{"id": "a", "url": "http://a:8730"}, {"id": "a", "url": "http://b:8730"}]},
                    {"recorders": [{"id": "r%d" % i, "url": "http://a:8730"} for i in range(9)]}, {"quality": "4k"}, {"quality": None}, {"quality": ["720p"]}):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertTrue(self.p.get(["live"])["live"]["enabled"])   # 断ったときは変えない
        for q in ("720p", "best", "1080p"):   # 録画の画質(スタジオの URL の欄から始める録画)
            self.assertEqual(self.p.patch("live", {"quality": q})["quality"], q)
        self.assertEqual(self.p.patch("live", {"enabled": False})["quality"], "1080p")   # ほかのキーを直しても残る
        for bad in ({"autoArchive": "no"}, {"autoArchive": 0}, {"autoArchive": None}):   # 自動で本番版に作り直す(P4)
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertIs(self.p.patch("live", {"autoArchive": False})["autoArchive"], False)
        self.assertIs(self.p.patch("live", {"quality": "720p"})["autoArchive"], False)   # ほかのキーを直しても残る
        self.assertIs(self.p.patch("live", {"autoArchive": True})["autoArchive"], True)
        for bad in ({"autoDelete": "no"}, {"autoDelete": 1}, {"autoDelete": None}):   # 本番版に入れ替えたら録画を消す(P4)
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertIs(self.p.patch("live", {"autoDelete": False})["autoDelete"], False)
        self.assertIs(self.p.patch("live", {"autoArchive": False})["autoDelete"], False)   # ほかのキーを直しても残る
        self.assertIs(self.p.patch("live", {"autoDelete": True})["autoDelete"], True)
        for bad in ({"autoAfterStream": "yes"}, {"autoAfterStream": 1}, {"afterStreamPerHour": 0}, {"afterStreamPerHour": 31},
                    {"afterStreamPerHour": 2.5}, {"afterStreamPerHour": True}, {"afterStreamPerHour": "6"}):   # 配信後の全自動(M7)
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        v = self.p.patch("live", {"autoAfterStream": True, "afterStreamPerHour": 10})
        self.assertEqual((v["autoAfterStream"], v["afterStreamPerHour"]), (True, 10))
        self.assertEqual(self.p.patch("live", {"quality": "720p"})["afterStreamPerHour"], 10)   # ほかのキーを直しても残る
        self.assertIs(self.p.patch("live", {"autoAfterStream": False})["autoAfterStream"], False)
        # 録画を消すのは、オンで live.autoDelete が明示的に true のときだけ(戻せないので)
        class FP:
            def __init__(self, v):
                self.v = v

            def get(self, keys):
                return {"live": self.v}
        for v, want in (({"enabled": True}, False), ({"enabled": True, "autoDelete": "yes"}, False), ({"enabled": False, "autoDelete": True}, False),
                        ({"enabled": True, "autoDelete": True}, True)):
            self.assertIs(LV.Live(FP(v), self.tmp, os.path.join(self.tmp, "logs")).auto_delete(), want, v)

    def test_live_auto_settings(self):
        """書き出したあとの自動の流れ live.auto(M2): 鍵ごとに直す・形の違う値は断る・ほかの鍵を直しても残る"""
        v = self.p.patch("live", {"auto": {"after": "auto", "engine": "whisper.cpp"}})
        self.assertEqual(v["auto"], {"after": "auto", "cut": "", "engine": "whisper.cpp", "model": "", "pad": 2})
        v = self.p.patch("live", {"auto": {"cut": "silence", "model": "large-v3"}})
        self.assertEqual(v["auto"], {"after": "auto", "cut": "silence", "engine": "whisper.cpp", "model": "large-v3", "pad": 2})
        for bad in ({"auto": "x"}, {"auto": {"after": "all"}}, {"auto": {"cut": "rows"}}, {"auto": {"engine": "openai"}},
                    {"auto": {"model": "../x"}}, {"auto": {"model": "a" * 61}}, {"auto": {"engine": None}}):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertEqual(self.p.patch("live", {"enabled": True})["auto"]["model"], "large-v3")   # ほかの鍵を直しても残る
        self.assertEqual(self.p.patch("live", {"auto": {"engine": "", "model": ""}})["auto"], {"after": "auto", "cut": "silence", "engine": "", "model": "", "pad": 2})

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

    def test_shutdown_quits_the_recorder_when_not_recording(self):
        """入口の「すべて終了」で録画の部品にも quit を送る(録画中でなければ静かに終わる。入口 0.38.1)"""
        self.enable()
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"active": 0, "recordings": [{"id": "20261004-000000-a", "active": False}]})

        def quit_(_b):
            self.fake.routes[("GET", "/api/ping")] = lambda b: (503, {"error": "gone"})   # 終わった(待ち受けをやめた)ことにする
            return 200, {"ok": True}
        self.fake.routes[("POST", "/live/quit")] = quit_
        code, d = self.jreq("POST", "/api/shutdown", {})
        self.assertEqual((code, d), (200, {"ok": True}))                     # 録画中でなければ知らせは無い
        self.assertTrue(wait_for(lambda: self.srv.live._stopped is not None, 20))
        self.assertEqual(self.srv.live._stopped, "quit")
        quits = [s for s in self.fake.seen if s["method"] == "POST" and s["path"] == "/live/quit"]
        self.assertEqual(len(quits), 1)
        self.assertEqual(quits[0]["auth"], "Bearer " + TOKEN)                 # 合言葉つき
        self.assertEqual(self.srv.live.stop_recorder(), "quit")              # 2 回目(main の後始末)は何も送らない
        self.assertEqual(len([s for s in self.fake.seen if s["path"] == "/live/quit"]), 1)

    def test_shutdown_keeps_the_recorder_while_recording(self):
        """録画中(quit が 409)なら録画の部品は止めずに残し、「すべて終了」の応答と記録に知らせる"""
        logs = []
        self.srv.live.log = logs.append
        self.enable()
        self.fake.routes[("POST", "/live/quit")] = lambda b: (409, {"error": "busy", "message": "録画中なので終わりません(録画を止めてから)"})
        code, d = self.jreq("POST", "/api/shutdown", {})                     # 偽物の /live/list は録画中 1 本
        self.assertEqual((code, d.get("recorderKept"), d.get("notice")), (200, True, LV.KEPT_NOTE))
        self.assertTrue(wait_for(lambda: self.srv.live._stopped is not None, 20))
        self.assertEqual(self.srv.live._stopped, "kept")
        self.assertTrue(any(LV.KEPT_NOTE in m for m in logs), logs)
        self.assertTrue(self.srv.live.ping(self.srv.live.find("fake")))      # 録画の部品は動いたまま

    def test_off_is_unchanged(self):
        base = self.jreq("GET", "/no-such-thing")
        for path in ("/live", "/live/", "/live/live.js", "/live/hls.min.js", "/live/api/info", "/live/r/local/list",
                     "/live/api/marks?recorder=local&recording=20261004-000000-a", "/live/api/exports"):
            self.assertEqual(self.jreq("GET", path), base, path)   # 今までと同じ 404
        base_post = self.jreq("POST", "/api/no-such", {})
        self.assertEqual(self.jreq("POST", "/live/r/local/start", {"url": "x"}), base_post)
        for path in ("/live/api/marks", "/live/api/export", "/live/api/export/cancel", "/live/api/begin"):
            self.assertEqual(self.jreq("POST", path, {"op": "add", "url": "https://www.youtube.com/watch?v=abcdefghijk"}), base_post, path)
        self.assertEqual(self.jreq("POST", "/api/ytt/live", {"op": "status"}), (200, {"enabled": False}))   # ヘッダーの札: オフなら録画元に聞かない
        self.assertEqual(self.jreq("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": "20261004-000000-a"})[0], 409)
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
        # 以前の録画の画面はスタジオへ(P3。別ページはやめた)
        for path in ("/live", "/live/", "/live/index.html"):
            code, h, raw = self.req("GET", path)
            self.assertEqual((code, h.get("location")), (302, "/studio/"), path)
        for path in ("/live/live.js", "/live/live.css", "/live/live.html"):
            self.assertEqual(self.req("GET", path)[0], 404, path)
        self.assertFalse([n for n in ("live.html", "live.js", "live.css") if os.path.exists(os.path.join(HERE, n))])
        code, h, raw = self.req("GET", "/live/hls.min.js")   # スタジオの画面が ../live/hls.min.js で読む
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
        code, d = self.jreq("POST", "/live/r/fake/20261004-000000-a/stop", {"x": 1})
        self.assertEqual(code, 404)   # 偽物は stop を知らない(中継はそのまま返す)
        self.assertEqual((self.fake.seen[-1]["path"], self.fake.seen[-1]["body"]), ("/live/20261004-000000-a/stop", {"x": 1}))
        self.assertIsNone(self.fake.seen[-1]["origin"])
        # 検査
        n = len(self.fake.seen)
        # POST で中継するのは <録画>/stop だけ(録画を消す delete・start・quit・config は画面から録画元へ届かない。P4)
        for path in ("/live/r/fake/20261004-000000-a/delete", "/live/r/fake/start", "/live/r/fake/quit", "/live/r/fake/config",
                     "/live/r/fake/20261004-000000-a/stop/x", "/live/r/fake/x/stop", "/live/r/fake/20261004-000000-a/delete?x=stop"):
            self.assertEqual(self.jreq("POST", path, {})[0], 404, path)
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

    # ---------- P3: スタジオから ----------
    def probe_as(self, status, title="配信の題", message="", channel="Pekora Ch. 兎田ぺこら"):
        calls = []

        def probe(url):
            calls.append(url)
            return {"status": status, "title": title, "channel": channel, "message": message}
        self.srv.live.probe = probe
        return calls

    def test_begin(self):
        self.enable()
        calls = self.probe_as("is_live")
        started, listed = [], {"recordings": []}
        rec = {"id": "20261005-185300-abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信の題",
               "state": "waiting", "active": True, "segments": 0}
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, listed)
        self.fake.routes[("POST", "/live/start")] = lambda b: (started.append(b), (200, {"recording": rec}))[1]
        # URL の検査(yt-dlp も録画元も呼ばない)
        n = len(self.fake.seen)
        for bad in ("http://www.youtube.com/watch?v=abcdefghijk", "https://evil.example/watch?v=abcdefghijk", "https://youtube.com.evil.example/x",
                    "https://u@www.youtube.com/x", "file:///C:/x", "javascript:alert(1)", "https://www.youtube.com/a b", "http://127.0.0.1:1/x.m3u8",
                    "", None, 5, "https://www.youtube.com/" + "x" * 600):
            code, d = self.jreq("POST", "/live/api/begin", {"url": bad})
            self.assertEqual((code, d.get("error")), (400, "bad_request"), bad)
        self.assertEqual((calls, len(self.fake.seen)), ([], n))
        self.assertEqual(self.req("POST", "/live/api/begin", {"url": rec["url"]}, token=False)[0], 403)
        # 配信中 → 録画を始める(書き方の違う URL はそろえる・画質は設定・題は yt-dlp の題)
        code, d = self.jreq("POST", "/live/api/begin", {"url": "https://youtu.be/abcdefghijk?t=5"})
        self.assertEqual(code, 200, d)
        self.assertEqual(d, {"live": True, "recorder": "fake", "existing": False,
                             "recording": {"id": rec["id"], "url": rec["url"], "title": "配信の題", "state": "waiting", "channel": "Pekora Ch. 兎田ぺこら"}})
        self.assertEqual(calls, ["https://www.youtube.com/watch?v=abcdefghijk"])
        self.assertEqual(started, [{"url": "https://www.youtube.com/watch?v=abcdefghijk", "quality": "1080p", "title": "配信の題"}])
        # 同じ配信を録画中 → それを返す(始めない)
        listed["recordings"] = [dict(rec, state="recording")]
        code, d = self.jreq("POST", "/live/api/begin", {"url": "https://www.youtube.com/live/abcdefghijk"})
        self.assertEqual((code, d["existing"], d["recording"]["id"], d["recording"]["state"]), (200, True, rec["id"], "recording"))
        self.assertEqual(d["recording"]["channel"], "Pekora Ch. 兎田ぺこら")   # 録画中だったときも分かれば付ける
        self.assertEqual(len(started), 1)
        # チャンネル名の掃除(制御文字を落とす・長さを切る)・分からなければ空
        self.probe_as("is_live", channel="ch\x07\n名" + "x" * 300)
        d = self.jreq("POST", "/live/api/begin", {"url": rec["url"]})[1]
        self.assertEqual(d["recording"]["channel"], ("ch名" + "x" * 300)[:LV.CHANNEL_MAX])
        self.probe_as("is_live", channel=None)
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": rec["url"]})[1]["recording"]["channel"], "")
        self.probe_as("is_live")
        # 録画元が「もう録画しています」(409)→ 一覧から探して返す(一覧を先に読んだときには無かった)
        seq = [{"recordings": []}, {"recordings": [dict(rec, state="recording")]}]
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, seq.pop(0) if seq else {"recordings": []})
        self.fake.routes[("POST", "/live/start")] = lambda b: (409, {"error": "conflict", "message": "その配信はもう録画しています"})
        code, d = self.jreq("POST", "/live/api/begin", {"url": rec["url"]})
        self.assertEqual((code, d.get("existing")), (200, True), d)
        # 409 で同じ配信が無い(streamlink が無いなど)→ 409 と理由
        self.fake.routes[("POST", "/live/start")] = lambda b: (409, {"error": "conflict", "message": "streamlink が入っていません"})
        code, d = self.jreq("POST", "/live/api/begin", {"url": rec["url"]})
        self.assertEqual((code, d["error"]), (409, "conflict"))
        self.assertIn("streamlink", d["message"])
        # 画質の設定
        self.jreq("POST", "/api/ytt/prefs", {"op": "patch", "section": "live", "value": {"quality": "720p"}})
        self.fake.routes[("POST", "/live/start")] = lambda b: (started.append(b), (200, {"recording": rec}))[1]
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": rec["url"]})[0], 200)
        self.assertEqual(started[-1]["quality"], "720p")
        # 配信前も録画する
        self.probe_as("is_upcoming", title="")
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": rec["url"]})[1]["live"], True)
        self.assertEqual(started[-1]["title"], "")   # 題が分からなければ録画の部品が oEmbed で付ける
        # 配信中でない・調べられない → live: false(画面は今までどおりの解析へ)。録画元には頼まない
        n_start = len(started)
        for st in ("was_live", "not_live", "post_live"):
            self.probe_as(st)
            self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": rec["url"]}), (200, {"live": False, "status": st}))
        self.probe_as("NA", message="配信の状態を調べられませんでした(ERROR: x)")
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": rec["url"]}),
                         (200, {"live": False, "status": "unknown", "message": "配信の状態を調べられませんでした(ERROR: x)"}))
        self.srv.live.probe = mock.Mock(side_effect=RuntimeError("壊れた"))
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": rec["url"]}), (200, {"live": False, "status": "unknown"}))
        self.assertEqual(len(started), n_start)
        # 録画元が止まっている
        self.probe_as("is_live")
        self.fake.close()
        code, d = self.jreq("POST", "/live/api/begin", {"url": rec["url"]})
        self.assertEqual((code, d["error"]), (502, "recorder_down"))
        self.fake = FakeRecorder()

    def test_begin_local_url_only_for_tests(self):
        """手元の URL(テストの録画元 --source direct)は allow_local_urls のときだけ。そのときもそろえない"""
        self.enable()
        self.probe_as("is_live")
        got = []
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": []})
        self.fake.routes[("POST", "/live/start")] = lambda b: (got.append(b), (200, {"recording": {"id": "20261005-000000-x", "url": b["url"], "state": "waiting"}}))[1]
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": "http://127.0.0.1:9/live.m3u8"})[0], 400)
        self.srv.live.allow_local_urls = True
        code, d = self.jreq("POST", "/live/api/begin", {"url": "http://127.0.0.1:9/live.m3u8"})
        self.assertEqual((code, got[-1]["url"]), (200, "http://127.0.0.1:9/live.m3u8"), d)
        self.assertEqual(self.jreq("POST", "/live/api/begin", {"url": "http://192.168.1.2:9/live.m3u8"})[0], 400)   # 手元だけ

    def test_export_studio(self):
        self.enable()
        rec = "20261005-185300-abcdefghijk"
        self.fake.routes[("GET", "/live/%s/status" % rec)] = lambda b: (200, {"id": rec, "firstPdt": "2026-10-05T09:53:00.000Z", "segmentList": []})
        self.fake.routes[("GET", "/live/%s/segments" % rec)] = lambda b: (200, {"url": "https://www.youtube.com/watch?v=abcdefghijk", "active": True, "state": "recording",
                                                                             "firstPdt": "2026-10-05T09:53:00.000Z", "lastPdt": "2026-10-05T09:53:05.000Z",
                                                                             "segments": [], "gaps": []})   # まだ届いていない = 録画待ちのまま
        st = {"video": rec, "mark": "m1a2b3", "n": 4, "label": "見どころ\n", "start": 10, "end": 22.5}
        body = {"recorder": "fake", "recording": rec, "title": "配信<b>", "url": "https://www.youtube.com/watch?v=abcdefghijk", "transcribe": False, "studio": st}
        code, d = self.jreq("POST", "/live/api/export", body)
        self.assertEqual(code, 200, d)
        j = d["job"]
        mid = "lm-" + __import__("hashlib").sha1(b"m1a2b3").hexdigest()[:12]
        self.assertEqual((j["markId"], j["state"], j["n"], j["label"], j["transcribe"]), (mid, "wait", 4, "見どころ", False))
        self.assertEqual((j["after"], j["streamer"]), ("none", ""))   # 以前の transcribe: false = 何もしない
        self.assertEqual(j["studio"], {"video": rec, "mark": "m1a2b3", "start": 10.0, "end": 22.5})
        self.assertEqual((j["start"], j["end"]), ("2026-10-05T09:53:10.000Z", "2026-10-05T09:53:22.500Z"))   # firstPdt + 秒
        self.assertIn("/live/%s/status?since=999999999" % rec, [x["path"] for x in self.fake.seen])   # セグメントの一覧は要らない
        d2 = self.jreq("GET", "/live/api/marks?recorder=fake&recording=" + rec)[1]
        self.assertEqual([(m["id"], m["n"], m["start"], m["end"], m["label"]) for m in d2["marks"]],
                         [(mid, 4, "2026-10-05T09:53:10.000Z", "2026-10-05T09:53:22.500Z", "見どころ")])   # マークの正本(fsync)
        self.assertEqual((d2["title"], d2["url"]), ("配信<b>", "https://www.youtube.com/watch?v=abcdefghijk"))
        # 同じマークが途中 → 409(正本は書き換えない)
        code, d = self.jreq("POST", "/live/api/export", dict(body, studio=dict(st, start=0, end=5)))
        self.assertEqual((code, d["error"]), (409, "conflict"))
        self.assertEqual(self.jreq("GET", "/live/api/marks?recorder=fake&recording=" + rec)[1]["marks"][0]["start"], "2026-10-05T09:53:10.000Z")
        # 書き出しの一覧(録画1本に絞る・studio を含む)
        jobs = self.jreq("GET", "/live/api/exports?recorder=fake&recording=" + rec)[1]["jobs"]
        self.assertEqual([(x["id"], x["studio"]["mark"]) for x in jobs], [(j["id"], "m1a2b3")])
        self.assertEqual(self.jreq("GET", "/live/api/exports?recorder=fake&recording=20261005-000000-other")[1]["jobs"], [])
        self.assertEqual(len(self.jreq("GET", "/live/api/exports")[1]["jobs"]), 1)
        # 取り消してから、区間を変えてもう一度 → 同じ正本の1件を更新
        self.assertEqual(self.jreq("POST", "/live/api/export/cancel", {"id": j["id"]})[1]["job"]["state"], "cancelled")
        code, d = self.jreq("POST", "/live/api/export", dict(body, studio=dict(st, n=5, start=1, end=3, label="")))
        self.assertEqual(code, 200, d)
        marks = self.jreq("GET", "/live/api/marks?recorder=fake&recording=" + rec)[1]["marks"]
        self.assertEqual([(m["id"], m["n"], m["start"], m["end"], m["label"]) for m in marks], [(mid, 5, "2026-10-05T09:53:01.000Z", "2026-10-05T09:53:03.000Z", "")])
        self.jreq("POST", "/live/api/export/cancel", {"id": d["job"]["id"]})
        # 値の検査
        for bad in ({"video": "../x"}, {"video": ""}, {"mark": "a b"}, {"mark": "x" * 41}, {"mark": 5}, {"mark": "日本語"},
                    {"start": -1}, {"start": 5, "end": 5}, {"start": 6, "end": 5}, {"start": 0, "end": 3600.5}, {"start": float("nan")},
                    {"end": float("inf")}, {"start": "10"}, {"start": True}, {"start": None}, {"n": -1}, {"n": "1"}, {"n": 1.5}):
            code, d = self.jreq("POST", "/live/api/export", dict(body, studio=dict(st, **bad)))
            self.assertEqual((code, d.get("error")), (400, "bad_request"), bad)
        self.assertEqual(self.jreq("POST", "/live/api/export", dict(body, studio="x"))[0], 400)
        # 書き出したあと(after)と配信者の名前(streamer)
        nb = {k: v for k, v in body.items() if k != "transcribe"}
        for extra, want in (({}, ("check", True, "")), ({"transcribe": True}, ("check", True, "")), ({"after": "none"}, ("none", False, "")),
                            ({"after": "auto", "transcribe": False, "streamer": " 兎田ぺこら "}, ("auto", True, "兎田ぺこら")),
                            ({"after": "check", "streamer": ""}, ("check", True, "")), ({"after": "check", "streamer": None}, ("check", True, ""))):
            code, d = self.jreq("POST", "/live/api/export", dict(nb, studio=dict(st, mark="after1"), **extra))
            self.assertEqual(code, 200, (extra, d))
            self.assertEqual((d["job"]["after"], d["job"]["transcribe"], d["job"]["streamer"]), want, extra)
            self.jreq("POST", "/live/api/export/cancel", {"id": d["job"]["id"]})
        for extra in ({"after": "full"}, {"after": ""}, {"after": True}, {"after": ["auto"]}, {"streamer": 5}, {"streamer": "a\nb"},
                      {"streamer": "x" * 61}, {"streamer": ["兎田ぺこら"]}):
            code, d = self.jreq("POST", "/live/api/export", dict(nb, studio=dict(st, mark="after2"), **extra))
            self.assertEqual((code, d.get("error")), (400, "bad_request"), extra)
        self.assertFalse([x for x in self.jreq("GET", "/live/api/exports")[1]["jobs"] if x["studio"]["mark"] == "after2"])   # 断ったものはジョブを作らない
        self.assertEqual(self.jreq("POST", "/live/api/export", dict(body, studio=dict(st, start=0.2, end=0.5)))[0], 400)   # 0.5 秒より短い(正本の決まり)
        for b2, want in (({"recorder": "../x"}, 400), ({"recording": "../x"}, 400), ({"recording": None}, 400), ({"recorder": "nope"}, 404),
                         ({"recording": "20261005-000000-unknown"}, 404)):
            code, d = self.jreq("POST", "/live/api/export", dict(body, **b2))
            self.assertEqual(code, want, (b2, d))
        # 録画がまだ始まっていない(最初のセグメントが無い)
        rec2 = "20261005-190000-abcdefghijk"
        self.fake.routes[("GET", "/live/%s/status" % rec2)] = lambda b: (200, {"id": rec2, "firstPdt": None})
        code, d = self.jreq("POST", "/live/api/export", dict(body, recording=rec2, studio=dict(st, video=rec2)))
        self.assertEqual((code, d["error"]), (409, "conflict"))
        self.assertIn("まだ始まっていません", d["message"])
        self.assertFalse(self.jreq("GET", "/live/api/marks?recorder=fake&recording=" + rec2)[1]["marks"])
        self.assertEqual(self.req("POST", "/live/api/export", body, token=False)[0], 403)

    def test_ytt_live_status_and_stop(self):
        self.enable()
        now = time.time()
        rid_a, rid_b = "20261005-185300-abcdefghijk", "20261005-170000-bbbbbbbbbbb"
        recs = [{"id": rid_a, "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信中", "state": "recording", "active": True, "seconds": 12.5, "endedAt": None},
                {"id": rid_b, "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "title": "", "state": "stopped", "active": False, "seconds": 300,
                 "endedAt": LX.epoch_iso(now - 120)},                                                      # 終わって 2 分
                {"id": "20261005-120000-ccccccccccc", "state": "ended", "active": False, "seconds": 9, "endedAt": LX.epoch_iso(now - 1200)},   # 20 分前 = 出さない
                {"id": "../evil", "state": "recording", "active": True}]                                  # 形の違う id は出さない
        lists = []
        self.fake.routes[("GET", "/live/list")] = lambda b: (lists.append(1), (200, {"recordings": recs}))[1]
        code, d = self.jreq("POST", "/api/ytt/live", {"op": "status"})
        self.assertEqual(code, 200, d)
        self.assertEqual(d["enabled"], True)
        self.assertEqual([(r["recorder"], r["id"], r["active"], r["state"]) for r in d["recordings"]], [("fake", rid_a, True, "recording"), ("fake", rid_b, False, "stopped")])
        self.assertEqual(sorted(d["recordings"][0]), ["active", "endedAt", "id", "recorder", "seconds", "state", "title", "url"])
        self.assertEqual((d["recordings"][0]["seconds"], d["recordings"][0]["title"], d["recordings"][1]["endedAt"]), (12.5, "配信中", recs[1]["endedAt"]))
        self.assertEqual(self.jreq("POST", "/api/ytt/live", {"op": "status"})[1], d)   # 3 秒は覚えた結果(録画元に聞かない)
        self.assertEqual(len(lists), 1)
        self.srv.live._recent = (time.time() - LV.STATUS_CACHE - 0.1, [])
        self.jreq("POST", "/api/ytt/live", {"op": "status"})
        self.assertEqual(len(lists), 2)
        # 停止
        stops = []
        self.fake.routes[("POST", "/live/%s/stop" % rid_a)] = lambda b: (stops.append(b), (200, {"recording": dict(recs[0], state="stopped", active=False)}))[1]
        code, d = self.jreq("POST", "/api/ytt/live", {"op": "stop", "recorder": "fake", "recording": rid_a})
        self.assertEqual((code, d), (200, {"ok": True, "recording": {"id": rid_a, "url": recs[0]["url"], "title": "配信中", "state": "stopped"}}))
        self.assertEqual(stops, [{}])
        self.assertIsNone(self.srv.live._recent)   # 止めたら札をすぐ読み直す
        for bad, want in (({"recorder": "fake", "recording": "../x"}, 400), ({"recorder": "FAKE", "recording": rid_a}, 400), ({"recorder": "fake"}, 400),
                          ({"recorder": "nope", "recording": rid_a}, 404), ({"recorder": "fake", "recording": "20261005-000000-unknown"}, 404)):
            code, d = self.jreq("POST", "/api/ytt/live", dict(bad, op="stop"))
            self.assertEqual(code, want, (bad, d))
        self.assertEqual(self.jreq("POST", "/api/ytt/live", {"op": "nope"})[0], 400)
        self.assertEqual(self.req("POST", "/api/ytt/live", {"op": "stop", "recorder": "fake", "recording": rid_a}, token=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/ytt/live", {"op": "status"}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(len(stops), 1)
        # 録画元が止まっている: 札は空(待たせない)
        self.fake.close()
        self.srv.live._recent = None
        t = time.time()
        self.assertEqual(self.jreq("POST", "/api/ytt/live", {"op": "status"})[1], {"enabled": True, "recordings": []})
        self.assertLess(time.time() - t, 5)
        self.assertEqual(self.jreq("POST", "/api/ytt/live", {"op": "stop", "recorder": "fake", "recording": rid_a})[0], 502)
        self.fake = FakeRecorder()


class ProbeTest(unittest.TestCase):
    """yt-dlp の呼び方(probe_live)。偽の yt-dlp(この Python で動く小さなスクリプト)で、本物の YouTube へは繋がない"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-probe-")
        self.args = os.path.join(self.tmp, "args.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, out="", err="", code=0, sleep=0):
        """find_tool が返す yt-dlp を、この Python で動くスクリプトに置き換える(.bat を通すと cmd が引数の % を読むので、実行の直前で差し替える)"""
        script = os.path.join(self.tmp, "fake_ytdlp.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import json, sys, time\njson.dump(sys.argv[1:], open(%r, 'w'))\ntime.sleep(%r)\n"
                    "sys.stdout.buffer.write(%r.encode('utf-8'))\nsys.stderr.buffer.write(%r.encode('utf-8'))\nsys.exit(%d)\n"
                    % (self.args, sleep, out, err, code))
        real = subprocess.run

        def run(cmd, *a, **kw):
            self.assertIsInstance(cmd, list)              # シェルを通さない(引数のリスト)
            self.assertNotIn("shell", kw)
            self.assertEqual(cmd[0], "FAKE-YT-DLP")
            return real([sys.executable, script] + cmd[1:], *a, **kw)
        stack = __import__("contextlib").ExitStack()
        stack.enter_context(mock.patch.object(LV.tools, "find_tool", lambda name, *a, **k: "FAKE-YT-DLP" if name == "yt-dlp" else None))
        stack.enter_context(mock.patch.object(LV.subprocess, "run", run))
        return stack

    def test_live_status_and_title(self):
        with self.fake(out="is_live\tPekora Ch. 兎田ぺこら\x07\t【雑談】配信の題\tつづき\x07\n"):
            r = LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(r, {"status": "is_live", "title": "【雑談】配信の題つづき", "channel": "Pekora Ch. 兎田ぺこら", "message": ""})   # 題のタブは崩さない
        with open(self.args, encoding="utf-8") as f:
            args = json.load(f)
        self.assertEqual(args[-2:], ["--", "https://www.youtube.com/watch?v=abcdefghijk"])   # URL は1つの引数・オプションとして読ませない
        for flag in ("--skip-download", "--no-playlist", "--ignore-no-formats-error"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--print") + 1], "%(live_status)s\t%(channel,uploader)s\t%(title)s")

    def test_other_states(self):
        with self.fake(out="was_live\tNA\tNA\n"):
            self.assertEqual(LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk"), {"status": "was_live", "title": "", "channel": "", "message": ""})
        with self.fake(out="", err="ERROR: [youtube] x: This live event will begin in 3 hours.\n", code=1):
            self.assertEqual(LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk")["status"], "is_upcoming")
        with self.fake(out="", err="ERROR: Video unavailable\n", code=1):
            r = LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(r["status"], "unknown")
        self.assertIn("Video unavailable", r["message"])
        with self.fake(out="NA\tNA\tNA\n"):
            self.assertEqual(LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk")["status"], "unknown")
        with self.fake(out="is_live\tc\tx\n", sleep=3):
            r = LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk", timeout=0.5)
        self.assertEqual(r["status"], "unknown")
        self.assertIn("秒で調べられませんでした", r["message"])
        with mock.patch.object(LV.tools, "find_tool", lambda *a, **k: None):
            self.assertIn("yt-dlp が見つからない", LV.probe_live("https://www.youtube.com/watch?v=abcdefghijk")["message"])

    def test_validate_url(self):
        self.assertEqual(LV.validate_url(" https://youtu.be/abcdefghijk "), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(LV.validate_url("https://m.youtube.com/watch?v=abcdefghijk&t=1"), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(LV.validate_url("https://www.youtube.com/@channel/live"), "https://www.youtube.com/@channel/live")   # id の無い形はそのまま
        for bad in ("https://www.youtube.com:8443/x", "https://user:pw@www.youtube.com/x", "ftp://www.youtube.com/x", "https://www.youtube.com/\x00"):
            with self.assertRaises(LX.LiveError, msg=bad):
                LV.validate_url(bad)


class StopRecorderTest(unittest.TestCase):
    """入口の終了で録画の部品を止める(src/home/live.py の stop_recorder。入口 0.38.1)。止める相手・応答が無いとき・終わらないとき"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-stop-")
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.logs = []
        self.fake = FakeRecorder()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait(5)
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def live(self, enabled=True, url=None):
        self.prefs.patch("live", {"enabled": enabled, "recorders": [{"id": "local", "name": "この PC", "url": url or self.fake.url, "token": TOKEN}]})
        return LV.Live(self.prefs, REPO, os.path.join(self.tmp, "logs"), log=self.logs.append, data_dir=os.path.join(self.tmp, "recdata"), spawn=False)

    def sleeper(self):
        """この入口が起動した録画の部品の代わり(応答しない・終わらないプロセス)"""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.procs.append(p)
        return p

    def test_off_and_not_spawned_is_left_alone(self):
        lv = self.live(enabled=False)
        lv.close()
        self.assertEqual(lv.stop_recorder(), "none")
        self.assertFalse(self.fake.seen)                                    # オフで、人が別に起動したものは触らない
        self.assertIs(lv.local_recording(), False)

    def test_not_running_is_none(self):
        lv = self.live(url="http://127.0.0.1:%d" % free_port())
        self.assertEqual(lv.stop_recorder(), "none")                        # つながらない・この入口が起動したものでもない

    def test_unresponsive_own_process_is_killed(self):
        lv = self.live(enabled=False, url="http://127.0.0.1:%d" % free_port())
        lv.proc = self.sleeper()                                            # オフでも、この入口が起動したものは止める
        self.assertEqual(lv.stop_recorder(), "killed")
        self.assertIsNotNone(lv.proc.poll())
        self.assertTrue(any("応答しない" in m for m in self.logs), self.logs)

    def test_quit_accepted_but_own_process_does_not_exit_is_killed(self):
        lv = self.live()
        lv.proc = self.sleeper()
        self.fake.routes[("POST", "/live/quit")] = lambda b: (200, {"ok": True})
        with mock.patch.object(LV, "QUIT_WAIT", 0.6):
            self.assertEqual(lv.stop_recorder(), "killed")
        self.assertIsNotNone(lv.proc.poll())

    def test_refused_is_left_and_spawn_stops_after_close(self):
        lv = self.live()
        self.fake.routes[("POST", "/live/quit")] = lambda b: (500, {"message": "壊れた"})
        lv.close()
        self.assertEqual(lv.stop_recorder(), "failed")                      # 断られたら(録画中かもしれないので)止めない
        self.assertTrue(any("壊れた" in m for m in self.logs), self.logs)
        self.assertIs(lv.local_recording(), True)                           # 偽物の /live/list は録画中 1 本
        self.assertFalse(lv.spawn(lv.find("local")))                        # 終了の途中は見回りが起こし直さない


class FailuresTest(unittest.TestCase):
    """M3: 失敗の集約(src/home/live_failures.py)。書き出し・まとめて実行へ渡す・文字起こし・パックの失敗を 1 つの関数で文にして、
    LIVE の帯(GET /live/api/exports のジョブ)と「調子」(Live.health の failures)に同じ文で出す。exports.json と autorun-runs.jsonl を読むだけ"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-fail-")
        self.fake = FakeRecorder()
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.prefs.patch("live", {"enabled": True, "recorders": [{"id": "local", "name": "この PC", "url": self.fake.url, "token": TOKEN}]})
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)
        now = LX.now_iso()
        old = LX.epoch_iso(time.time() - 8 * 86400)

        def job(i, **kw):
            return dict({"id": "lx-%010d" % i, "recorder": "local", "recording": "20261004-000000-a", "markId": "lm-%012d" % i, "n": i, "label": "",
                         "start": now, "end": now, "state": "done", "message": "", "error": "", "warning": "", "path": "", "runId": "",
                         "created": now, "updated": now}, **kw)
        jobs = [job(1, state="error", error="録画が区間まで届きませんでした(録画は「ended」です)", label="山1"),
                job(2, path=os.path.join(self.tmp, "out", "02_渡せない.mp4"), handoffError="パックへ渡せませんでした: まとめて実行が使えません"),
                job(3, path=os.path.join(self.tmp, "out", "03_パック.mp4"), runId="r-pack"),
                job(4, path=os.path.join(self.tmp, "out", "04_文字.mp4"), runId="r-tx", warning="録画の終わりまでで切りました"),
                job(5, path=os.path.join(self.tmp, "out", "05_ok.mp4"), runId="r-ok"),
                job(6, state="cancelled", message="取り消しました"),
                job(7, state="error", error="古い失敗", updated=old, created=old)]   # 7 日より前は「調子」に出さない
        os.makedirs(os.path.join(self.tmp, "live"))
        with open(os.path.join(self.tmp, "live", "exports.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": LX.JOBS_SCHEMA, "jobs": jobs}, f, ensure_ascii=False)

        def run(rid, state, steps, error=""):
            return {"v": 1, "id": rid, "kind": "file", "sourcePath": "x.mp4", "state": state, "error": error, "created": 1, "mode": "file_auto",
                    "steps": [{"key": k, "label": k, "state": s, "detail": ""} for k, s in steps]}
        with open(os.path.join(self.logs, "autorun-runs.jsonl"), "w", encoding="utf-8") as f:
            for r in (run("r-pack", "error", [("transcribe", "done"), ("pack", "error")], "パックを作れませんでした: 字幕がありません"),
                      run("r-tx", "error", [("transcribe", "error"), ("pack", "wait")], "文字起こしに失敗しました: モデルがありません"),
                      run("r-ok", "done", [("transcribe", "done"), ("pack", "done")])):
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.live = LV.Live(self.prefs, REPO, self.logs, store_dir=os.path.join(self.tmp, "live"), out_dir=lambda: os.path.join(self.tmp, "out"), spawn=False)

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_text_in_band_and_health(self):
        snap = {j["id"]: j for j in self.live.exporter.snapshot()}
        f = {jid: (j.get("failure") or {}) for jid, j in snap.items()}
        self.assertEqual({jid: x.get("kind") for jid, x in f.items() if x},
                         {"lx-0000000001": "export", "lx-0000000002": "handoff", "lx-0000000003": "pack", "lx-0000000004": "transcribe", "lx-0000000007": "export"})
        self.assertEqual(f["lx-0000000001"]["text"], "「山1」: 書き出しに失敗しました: 録画が区間まで届きませんでした(録画は「ended」です)")
        self.assertEqual(f["lx-0000000002"]["text"], "02_渡せない.mp4: パックへ渡せませんでした: まとめて実行が使えません")
        self.assertEqual(f["lx-0000000003"]["text"], "03_パック.mp4: パックを作れませんでした: 字幕がありません")   # 理由が段の名前で始まるなら重ねない
        self.assertEqual(f["lx-0000000004"]["text"], "04_文字.mp4: 文字起こしに失敗しました: モデルがありません")
        self.assertEqual(LF.failure_of({"state": "done", "label": "x", "runId": "r"}, {"state": "error", "error": "つながりません", "steps": [{"key": "pack", "state": "error"}]})["text"],
                         "「x」: パックに失敗しました: つながりません")
        self.assertIsNone(LF.failure_of({"state": "done", "runId": "r"}, {"state": "cancelled", "steps": []}))   # 人の中止は失敗ではない
        # 帯が出す欄に同じ文: 書き出しの失敗は error、それ以外は warning(前からの警告は残す)
        self.assertEqual(snap["lx-0000000001"]["error"], f["lx-0000000001"]["text"])
        self.assertEqual(snap["lx-0000000004"]["warning"], "録画の終わりまでで切りました / " + f["lx-0000000004"]["text"])
        for jid in ("lx-0000000002", "lx-0000000003"):
            self.assertEqual(snap[jid]["warning"], f[jid]["text"])
        # 「調子」: 7 日より前・取り消し・成功は出さない。文は帯と同じ
        h = self.live.health()
        self.assertEqual(sorted(x["text"] for x in h["failures"]), sorted(f[jid]["text"] for jid in ("lx-0000000001", "lx-0000000002", "lx-0000000003", "lx-0000000004")))
        self.assertEqual({x["kind"] for x in h["failures"]}, {"export", "handoff", "pack", "transcribe"})
        # 書き出しの記録は書き換えない(読むだけ)
        with open(os.path.join(self.tmp, "live", "exports.json"), encoding="utf-8") as fh:
            self.assertNotIn("failure", fh.read())

    def test_off_has_no_failures_and_portal_health(self):
        self.prefs.patch("live", {"enabled": False})
        self.assertIsNone(self.live.health())                                # オフなら「調子」に出さない(今までどおり)

    def test_health_has_disk(self):
        """M4: 「調子」に書き出し先・パック・live\\work の空き(state・行・しきい値)"""
        self.live.exporter.disk_usage = lambda p: (4 * LX.GB, 100 * LX.GB)
        self.live.exporter.disk_poll = 0
        d = self.live.health()["disk"]
        self.assertEqual((d["state"], d["lowBytes"], d["warnBytes"]), ("low", 5 * LX.GB, 20 * LX.GB))
        self.assertTrue(d["rows"] and all(r["state"] == "low" and r["freeBytes"] == 4 * LX.GB for r in d["rows"]))
        self.assertIn("5 GB 以上空くと続けます", d["message"])


class SpawnTest(unittest.TestCase):
    """見回りが本物の録画の部品(src/recorder/recorder.py)を切り離して起動する"""

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
        self.streamers = []   # start_file に渡った配信者の名前(files と同じ順)

    def start_file(self, path, title="", flow="check", streamer=None, **kw):
        if getattr(self, "fail", None):
            raise ValueError(self.fail)
        self.files.append((path, title, flow))
        self.streamers.append(streamer)
        self.kws = getattr(self, "kws", []) + [kw]   # 書き出したあとの設定(live.auto の cut・engine・model。M2)
        return {"id": "run-%d" % len(self.files)}

    def snapshot(self):
        return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち",
                          "steps": [{"key": "transcribe", "label": "文字起こし", "state": "wait", "stateLabel": "待ち", "detail": ""}]}
                         for i in range(len(self.files))]}


class FakeStudio:
    """取り込んだスタジオの API の代わり(Live.studio_call に差し替える。M1): 配信の登録・読む・マークの保存(baseRev)・書き出し済み"""

    def __init__(self):
        self.videos = {}
        self.calls = []
        self.conflicts = 0     # この回数だけ PUT を 409(画面の保存とぶつかった)にする
        self.seq = 0

    def __call__(self, method, path, body=None):
        self.calls.append((method, path.split("?")[0], json.loads(json.dumps(body)) if body is not None else None))
        if method == "POST" and path == "/api/videos/open":
            v = self.videos.setdefault(body["recording"], {"id": body["recording"], "kind": "live", "rev": 1, "marks": [], "title": body.get("title") or ""})
            return 200, {"video": json.loads(json.dumps(v))}
        if method == "GET" and path.startswith("/api/video?id="):
            v = self.videos.get(path.split("=", 1)[1])
            return (200, {"video": json.loads(json.dumps(v))}) if v else (404, {"message": "無い"})
        if method == "PUT" and path == "/api/video":
            v = self.videos[body["id"]]
            if self.conflicts:
                self.conflicts -= 1
                v["rev"] += 1
                return 409, {"message": "ぶつかった"}
            if body.get("baseRev") != v["rev"]:
                return 409, {"message": "古い"}
            marks = []
            for m in body["marks"]:
                m = dict(m)
                if not m.get("id"):
                    self.seq += 1
                    m["id"] = "m%d" % self.seq
                    m.setdefault("src", "manual")
                m["start"], m["end"] = round(m["start"], 1), round(m["end"], 1)   # スタジオは小数 1 桁に丸める
                marks.append(m)
            v["marks"], v["rev"] = marks, v["rev"] + 1
            return 200, {"video": json.loads(json.dumps(v))}
        if method == "POST" and path == "/api/live/exported":
            v = self.videos[body["id"]]
            m = next((x for x in v["marks"] if x["id"] == body["markId"]), None)
            if m is None:
                return 200, {"ok": False}
            m.update(status="exported", path=body["path"])
            return 200, {"ok": True}
        return 404, {"message": "なし"}


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
        self.assertEqual(self.runner.streamers, [None])   # 配信者の名前が無い = まとめて実行が自動で決める
        self.assertEqual((done["runId"], done["after"], done["streamer"]), ("run-1", "check", ""))
        self.assertEqual(self.job(j["id"])["tx"]["state"], "queued")
        self.assertEqual([x["key"] for x in self.job(j["id"])["tx"]["steps"]], ["transcribe"])   # 段ごとの進み具合も(画面が全自動の進み具合を出す)
        self.assertFalse(os.listdir(os.path.join(self.tmp, "live", "work")))   # 取ったセグメントは片付ける
        # 文字起こしなし・同じマークをもう一度 → 別の名前
        j2 = self.ex.add("local", rid, m["id"], transcribe=False)
        d2 = self.wait_state(j2["id"], ("done", "error"), 90)
        self.assertEqual(d2["state"], "done", d2)
        self.assertNotEqual(d2["path"], path)
        self.assertEqual(len(self.runner.files), 1)
        self.assertEqual(d2["after"], "none")   # transcribe=False は「何もしない」
        # 全自動(文字起こし → パック)+ 配信者の名前(照らし合わせて渡す)
        j4 = self.ex.add("local", rid, m["id"], after="auto", streamer="ぺこら")
        d4 = self.wait_state(j4["id"], ("done", "error"), 90)
        self.assertEqual((d4["state"], d4["after"], d4["transcribe"], d4["streamer"]), ("done", "auto", True, "ぺこら"), d4)
        self.assertEqual(self.runner.files[-1][2], "auto")
        self.assertEqual(self.runner.streamers[-1], "兎田ぺこら")   # 色の一覧の名前にそろえて渡す
        self.assertIn("パック", d4["message"])
        # 色の一覧に合わない名前: 書き出しは止めず、色なし(None)で渡して知らせる
        j5 = self.ex.add("local", rid, m["id"], after="check", streamer="だれでもない人")
        d5 = self.wait_state(j5["id"], ("done", "error"), 90)
        self.assertEqual((d5["state"], self.runner.files[-1][2], self.runner.streamers[-1]), ("done", "check", None), d5)
        self.assertIn("字幕の色なし", d5["warning"])
        # 取り消し(録画待ちの間)
        far = self.mark(rid, last + 100, last + 110)
        j3 = self.ex.add("local", rid, far["id"])
        with self.assertRaises(LX.LiveError):
            self.ex.add("local", rid, far["id"])   # 同じマークは途中のものがあれば断る
        self.assertEqual(self.ex.cancel(j3["id"])["state"], "cancelled")
        # 記録は exports.json に残る(起動し直しても見える)
        again = LX.Exporter(self.live, os.path.join(self.tmp, "live"), lambda: self.out)
        self.assertEqual({x["id"]: x["state"] for x in again.jobs}, {j["id"]: "done", j2["id"]: "done", j3["id"]: "cancelled", j4["id"]: "done", j5["id"]: "done"})

    def test_pad_secs(self):
        """M8: 自動・アーカイブの採用の区間を前後 pad 秒だけ広げる。0 より前・録れている範囲(lastPdt)の外・1 つのマークの上限の外へは広げない"""
        first = 1_700_000_000.0
        st = lambda rel: {"lastPdt": LX.epoch_iso(first + rel)}
        self.assertEqual(LV.Live._pad_secs(10.0, 20.0, 2, st(100), first), (8.0, 22.0))
        self.assertEqual(LV.Live._pad_secs(1.0, 20.0, 2, st(21), first), (0.0, 21.0))      # 頭は 0 まで・後ろは録れている所まで
        self.assertEqual(LV.Live._pad_secs(10.0, 20.0, 2, st(19), first), (8.0, 20.0))     # 終わりがまだ録れていない = 後ろは足さない
        self.assertEqual(LV.Live._pad_secs(10.0, 20.0, 1.5, {}, first), (8.5, 21.5))     # lastPdt が無ければ両側に
        self.assertEqual(LV.Live._pad_secs(0.0, LX.MAX_MARK_SEC, 2, {}, first), (0.0, float(LX.MAX_MARK_SEC)))

    def test_adopt_server_side(self):
        """M1: POST /live/api/adopt の中身(Live.adopt)。画面なしで スタジオのマーク(採用)→ 正本 → 書き出し → スタジオのマークを「書き出し済み」。
        origin を .clip.json と live_feedback.jsonl に残す・同じ区間は二重に作らない・live.auto(M2)をまとめて実行へ渡す"""
        studio = FakeStudio()
        studio.conflicts = 1                                                  # 1 回目の保存は画面の保存とぶつかる → 読み直して入れる
        self.live.studio_call = studio
        self.prefs.patch("live", {"auto": {"after": "auto", "cut": "silence", "engine": "whisper.cpp", "model": "large-v3"}})
        rid = self.start_rec(8)
        first = LX.iso_epoch(self.status(rid)["firstPdt"])
        res = self.live.adopt({"recorder": "local", "recording": rid, "start": 1.04, "end": 4.0, "label": "自動の山", "origin": "auto"})
        self.assertEqual((res["video"], res["origin"], res["existing"]), (rid, "auto", False))
        j = res["job"]
        self.assertEqual((j["origin"], j["after"], j["auto"], j["studio"]["mark"], j["studio"]["start"]),
                         ("auto", "auto", {"cut": "silence", "engine": "whisper.cpp", "model": "large-v3"}, res["mark"], 0.0))   # 自動の採用は前後に余白 2 秒(M8。0 より前には広げない)。区間はスタジオが丸めた値
        v = studio.videos[rid]
        self.assertEqual([(m["status"], m["label"], m["start"], m["end"]) for m in v["marks"]], [("adopted", "自動の山", 0.0, 6.0)])   # 1.04 − 2 → 0・4 + 2 = 6(録画は 8 秒以上ある)
        d = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(d["state"], "done", d)
        self.assertEqual(self.runner.files[-1][2], "auto")
        self.assertEqual(self.runner.kws[-1], {"cut": "silence", "engine": "whisper.cpp", "model": "large-v3"})   # M2: live.auto をまとめて実行へ
        self.assertTrue(wait_for(lambda: v["marks"][0]["status"] == "exported", 5))   # 入口が自分で「書き出し済み」にする(画面なし)
        self.assertEqual(os.path.normcase(v["marks"][0]["path"]), os.path.normcase(d["path"]))
        clip, _w = schemas.load_clip_file(schemas.find_clip_path(d["path"]))
        self.assertEqual((clip["source"]["live"]["origin"], clip["mark"]["src"]), ("auto", "auto"))
        self.assertAlmostEqual(LX.iso_epoch(clip["source"]["live"]["start"]) - first, 0.0, delta=0.01)   # 秒は録画の頭(firstPdt)から
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            fb = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([(x["event"], x["origin"], x["human"], x["verdict"], x["jobId"]) for x in fb], [("adopt", "auto", False, None, j["id"])])   # 自動は「良い」に数えない
        # 同じ区間をもう一度(余白を足しても同じマーク)→ 済んでいるので新しく作らない(スタジオのマークも増やさない)
        again = self.live.adopt({"recorder": "local", "recording": rid, "start": 1.0, "end": 4.02, "origin": "auto"})
        self.assertEqual((again["existing"], again["job"]["id"], len(v["marks"])), (True, j["id"], 1))
        # 絶対時刻(UTC の文字列)でも頼める・人の採用(manual)は「良い」・after を指定すれば設定より優先
        m2 = self.live.adopt({"recorder": "local", "recording": rid, "start": LX.epoch_iso(first + 5.0), "end": LX.epoch_iso(first + 7.0), "after": "none"})
        self.assertEqual((m2["origin"], m2["job"]["after"], m2["job"]["studio"]["start"]), ("manual", "none", 5.0))
        self.assertEqual(self.wait_state(m2["job"]["id"], ("done", "error"), 90)["state"], "done")
        with open(os.path.join(self.tmp, "live", LX.FEEDBACK), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read().strip().splitlines()[-1])["verdict"], "good")
        for bad in ({"origin": "robot"}, {"start": 5.0, "end": 5.2}, {"start": -1, "end": 3}, {"start": "きのう", "end": 3}, {"start": True, "end": 3},
                    {"after": "all"}, {"recording": "../x"}):
            with self.assertRaises(LX.LiveError, msg=repr(bad)):
                self.live.adopt(dict({"recorder": "local", "recording": rid, "start": 10.0, "end": 12.0}, **bad))
        studio_down = lambda m, p, b=None: (None, {"message": "スタジオが動いていません"})
        self.live.studio_call = studio_down
        with self.assertRaises(LX.LiveError) as cm:
            self.live.adopt({"recorder": "local", "recording": rid, "start": 10.0, "end": 12.0})
        self.assertEqual(cm.exception.code, 502)

    def test_handoff_failure_is_collected(self):
        """M3: まとめて実行へ渡せなかった失敗が、LIVE の帯(ジョブの warning と failure)と「調子」(health の failures)に同じ文で出る"""
        self.runner.fail = "順番待ちが多すぎます(20本まで)"
        rid = self.start_rec()
        first = LX.iso_epoch(self.status(rid)["firstPdt"])
        m = self.mark(rid, first + 0.5, first + 2.5, "失敗する")
        j = self.ex.add("local", rid, m["id"], after="check")
        d = self.wait_state(j["id"], ("done", "error"), 90)
        self.assertEqual(d["state"], "done", d)
        f = d["failure"]
        self.assertEqual(f["kind"], "handoff")
        self.assertIn("文字起こしへ渡せませんでした: 順番待ちが多すぎます", f["text"])
        self.assertIn(os.path.basename(d["path"]), f["text"])
        self.assertIn(f["text"], d["warning"])                               # 帯は warning の行に出す(今の画面のまま)
        h = self.live.health()
        self.assertEqual([x["text"] for x in h["failures"]], [f["text"]])     # 「調子」に同じ文
        self.assertEqual(h["failures"][0]["jobId"], j["id"])

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
        self.assertEqual(LV.studio_audio(REPO), {"volume": 75, "loudness": -14.0})   # src/studio/review.js の DEFAULT_SETTINGS と同じ
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

    def _pieces_exporter(self, free, runner=None, slots=None):
        """録画元に繋がない Exporter(録画元の答えは _query を差し替える)。free: {"v": 空きのバイト数}"""
        live = mock.Mock()
        live.find.return_value = {"id": "local", "name": "この PC"}
        live.recorders.return_value = [{"id": "local", "name": "この PC"}]
        live.studio_call = None
        logs = []
        ex = LX.Exporter(live, os.path.join(self.tmp, "live"), lambda: os.path.join(self.tmp, "out"), runner=(lambda: runner) if runner else None,
                         log=logs.append, slots=slots, disk_usage=lambda p: (free["v"], 200 * LX.GB), disk_poll=0)
        ex.close()   # 見回りは止めて、ここで 1 本ずつ動かす
        ex._halt.clear()
        return ex, logs

    def test_disk_low_waits_then_resumes(self):
        """M4: 書き出し先・live\\work の空きが 5 GB 未満なら、新しい書き出しを「空き待ち」にして録画元にも問い合わせない。空くと続ける。
        書き出しが済んだあとの まとめて実行への受け渡しも空くまで待つ(済んだら渡す)。20 GB 未満は注意だけ。変わったときだけ記録する"""
        free = {"v": 3 * LX.GB}
        runner = FakeRunner()
        ex, logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        m, _ = ex.marks.apply("local", rec, {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:05Z"})
        ex.add("local", rec, m["id"], after="check")
        j = ex.jobs[0]
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "state": "recording", "active": True, "lastPdt": "2026-10-04T06:10:00.000Z",
               "firstPdt": "2026-10-04T05:00:00.000Z", "segments": [], "gaps": []}
        with mock.patch.object(ex, "_query", return_value=(200, ans)) as q:
            self.assertIsNone(ex._next_ready())
            q.assert_not_called()                                            # 空き待ちの間は録画元に問い合わせない
            self.assertTrue(j["diskWait"])
            self.assertIn("空き容量が少ないので、新しい書き出し・文字起こしを止めて待っています", j["message"])
            self.assertIn("3.0 GB", j["message"])
            d = ex.disk()
            self.assertEqual((d["state"], d["lowBytes"], d["warnBytes"]), ("low", 5 * LX.GB, 20 * LX.GB))
            self.assertEqual(len(d["rows"]), 1)                              # 書き出し先と live\work は同じドライブ = 1 行
            self.assertIn("書き出し先・パック", d["rows"][0]["label"])
            self.assertIn("作業用", d["rows"][0]["label"])
            self.assertIs(ex._next_ready(), None)
            free["v"] = 12 * LX.GB                                           # 空いた(20 GB 未満 = 注意だけ)
            self.assertIs(ex._next_ready(), j)
            self.assertNotIn("diskWait", j)
        self.assertEqual(ex.disk()["state"], "warn")
        self.assertEqual(len([x for x in logs if "空き容量が少ない" in x]), 1)   # 変わったときだけ記録する
        self.assertTrue(any("20 GB を切りました" in x for x in logs), logs)
        # 書き出しが済んだが空きが少ない → まとめて実行へは渡さずに待つ → 空いたら渡す
        free["v"] = 1 * LX.GB
        media = os.path.join(self.tmp, "out", "01_x.mp4")
        os.makedirs(os.path.dirname(media))
        with open(media, "wb") as f:
            f.write(b"x")
        a, b = LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"])
        ex._finish(j, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, a, b)
        self.assertEqual((j["state"], j["handoffWait"], j["runId"], runner.files), ("done", "disk", "", []))
        self.assertIn("空き容量が少ないので、空くまで文字起こしへ渡すのを待っています", j["message"])
        self.assertIsNone(LX.live_failures.failure_of(j))                    # 待ちは失敗ではない
        self.assertTrue(ex.pending())                                        # 起動し直したら見回りが続ける
        self.assertEqual(ex._retry_handoffs(), 0)
        free["v"] = 30 * LX.GB
        self.assertEqual(ex._retry_handoffs(), 1)
        self.assertEqual((j["handoffWait"], j["runId"], runner.files[0][0], runner.files[0][2]), ("", "run-1", media, "check"))
        self.assertIn("文字起こしの順番に入れました", j["message"])
        self.assertFalse(ex.pending())
        self.assertEqual(ex.disk()["state"], "ok")
        again = LX.Exporter(mock.Mock(), os.path.join(self.tmp, "live"), lambda: os.path.join(self.tmp, "out"))   # 記録に残る
        self.assertEqual((again.jobs[0]["handoffWait"], again.jobs[0]["runId"]), ("", "run-1"))

    def test_hold_for_archive_then_release(self):
        """M7: holdFor archive のジョブは、書き出したあと まとめて実行へすぐ渡さず、本番版にしてから(release_hold)渡す。空きが少なければ空き待ちに"""
        free = {"v": 50 * LX.GB}
        runner = FakeRunner()
        ex, _logs = self._pieces_exporter(free, runner)
        rec = "20261004-000000-a"
        m, _ = ex.marks.apply("local", rec, {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:05Z"})
        ex.add("local", rec, m["id"], after="auto", hold="archive")

        j = ex.jobs[0]
        self.assertEqual(j["holdFor"], "archive")
        media = os.path.join(self.tmp, "out", "02_y.mp4")
        os.makedirs(os.path.dirname(media))
        with open(media, "wb") as f:
            f.write(b"x")
        ans = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "firstPdt": "2026-10-04T05:00:00.000Z"}
        a, b = LX.iso_epoch(j["start"]), LX.iso_epoch(j["end"])
        ex._finish(j, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, a, b)
        self.assertEqual((j["handoffWait"], runner.files), ("archive", []))
        self.assertIn("本番版に入れ替えてから、文字起こし → パックへ渡します", j["message"])
        self.assertFalse(ex.pending())                                       # 本番版の待ちは Archiver が受け持つ
        free["v"] = 1 * LX.GB
        self.assertEqual(ex.release_hold(j), "")                             # 空きが少ない → 空き待ちへ
        self.assertEqual(j["handoffWait"], "disk")
        self.assertEqual(ex.release_hold(j), "")                             # もう本番版の待ちではない
        free["v"] = 50 * LX.GB
        ex._retry_handoffs()
        self.assertEqual((j["handoffWait"], j["runId"], runner.files[-1][2]), ("", "run-1", "auto"))
        # アーカイブから作った本番版(欠けのマーク)はすぐ渡す
        j2 = dict(j, id="lx-00000000b2", handoffWait="", runId="")
        ex.jobs.append(j2)
        ex._finish(j2, {"id": "local"}, rec, ans, {"path": media, "duration": 5.0, "title": "配信"}, a, b, archive={"videoId": "abcdefghijk"})
        self.assertEqual((j2["handoffWait"], j2["runId"]), ("", "run-2"))

    def test_reserved_slot_while_recording(self):
        """M6: 録画中のライブの書き出しは用途つきの枠も使う = 文字起こし 2 本で上限が埋まっていても待たない。録画が終わったあとは普通の枠で待つ"""
        slots = jobs.HeavySlots(2)
        held = [slots.acquire("transcribe", "文字起こし 1"), slots.acquire("transcribe", "文字起こし 2")]
        free = {"v": 50 * LX.GB}
        ex, _logs = self._pieces_exporter(free, slots=slots)
        rec = "20261004-000000-a"
        seen = []

        def encode(job, rc, rec_, d, segs, files, a, b, wdir):
            seen.append(slots.snapshot())
            return {"path": os.path.join(self.tmp, "x.mp4"), "duration": b - a, "title": "t"}, None

        stack = contextlib.ExitStack()   # 待っている書き出しのスレッドが終わるまで、差し替えを戻さない
        self.addCleanup(stack.close)
        ans = {"active": True}
        stack.enter_context(mock.patch.object(ex, "_sources", side_effect=lambda job, a, b: [({"id": "local", "name": "この PC"}, rec, dict(ans))]))
        stack.enter_context(mock.patch.object(ex, "_fetch", return_value=[("part.ts", "session_001")]))
        stack.enter_context(mock.patch.object(ex, "_encode", side_effect=encode))
        stack.enter_context(mock.patch.object(ex, "_finish", side_effect=lambda job, *a, **k: ex._set(job, state="done")))

        def run(active):
            m, _ = ex.marks.apply("local", rec, {"op": "add", "start": "2026-10-04T06:00:00Z", "end": "2026-10-04T06:00:05Z"})
            job = ex.add("local", rec, m["id"], after="none")
            j = next(x for x in ex.jobs if x["id"] == job["id"])
            ans.clear()
            ans.update({"active": active, "firstPdt": "2026-10-04T05:00:00.000Z", "gaps": [],
                        "segments": [{"uri": "session_001/seg_000000.ts", "session": "session_001", "pdt": "2026-10-04T05:59:58.000Z", "dur": 8.0}]})
            t = threading.Thread(target=ex._process, args=(j,), daemon=True)
            t.start()
            t.join(1.0)
            return t, j
        t, j = run(True)
        self.assertFalse(t.is_alive())
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(sorted((x["tool"], x.get("extra", False)) for x in seen[0]["active"]), [("live", True), ("transcribe", False), ("transcribe", False)])
        self.assertEqual([(x["tool"], x.get("extra", False)) for x in slots.snapshot()["active"]], [("transcribe", False), ("transcribe", False)])   # 枠は返した
        # 録画が終わったあと: 用途つきの枠は使わない(普通の枠が空くまで待つ)
        t, j = run(False)
        self.assertTrue(t.is_alive())
        self.assertIn("ほかの重い処理", j["message"])
        self.assertEqual(len(seen), 1)
        slots.release(held[0])
        t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(j["state"], "done")
        self.assertEqual(sorted((x["tool"], x.get("extra", False)) for x in seen[1]["active"]), [("live", False), ("transcribe", False)])
        slots.release(held[1])

    def test_reserved_slots_rules(self):
        """ytt_core.jobs の用途つきの枠(M6): 普通の枠が埋まっているときだけ・同じ用途の中では先に来た順・reserved を渡さない人は使えない・数は RESERVED"""
        self.assertEqual(jobs.RESERVED, {"live": 1})
        s = jobs.HeavySlots(1)
        a = s.acquire("transcribe")
        flag = []
        self.assertIsNone(s.acquire("live", cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # reserved なし = 待つ
        b = s.acquire("live", reserved=True)                                  # 用途つきの枠
        self.assertEqual([x.get("extra", False) for x in s.snapshot()["active"]], [False, True])
        flag.clear()
        self.assertIsNone(s.acquire("live", reserved=True, cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 用途つきの枠は 1 つだけ
        flag.clear()
        self.assertIsNone(s.acquire("transcribe", reserved=True, cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 用途の違う人は使えない
        s.release(b)
        got = []
        t = threading.Thread(target=lambda: got.append(s.acquire("transcribe", poll=0.01)))
        t.start()
        time.sleep(0.05)
        c = s.acquire("live", reserved=True, poll=0.01)                       # 前で待つ人がいても、用途つきの枠はすぐ使える
        self.assertIsNotNone(c)
        self.assertEqual(got, [])
        s.release(a)
        t.join(5)
        self.assertEqual(len(got), 1)                                          # 普通の枠は先に来た順のまま
        s.release(c)
        s.release(got[0])
        self.assertEqual(s.snapshot(), {"limit": 1, "active": [], "waiting": []})
        none = jobs.HeavySlots(1, reserved={})
        h = none.acquire("x")
        flag.clear()
        self.assertIsNone(none.acquire("live", reserved=True, cancelled=lambda: bool(flag.append(1)) or len(flag) > 2, poll=0.01))   # 枠を持たない
        none.release(h)

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
