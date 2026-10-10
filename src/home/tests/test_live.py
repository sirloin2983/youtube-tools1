# -*- coding: utf-8 -*-
"""リアルタイム切り抜き(線 D の P1)の入口の側(src/home/live.py・prefs の節 live・launch.py の /live/…・「調子」の行)のテスト。
② の部分は src/flow/tests に移した: 録画元まわり(probe・stop_recorder・見回りの起動)= test_live_recorder.py、マークと書き出し・採用・失敗の集約・ディスク・重い処理の枠 = test_live_export.py。

    py -3.10 -m unittest src/home/tests/test_live.py

確かめること:
  - 設定 live: 既定はオフ・形の検査・合言葉は空で送っても今の値を残す・画面へ返す設定に合言葉を出さない・配信中の候補の文字起こし liveTx(D-11 案 b)の検査
  - オフ: /live/… は今までと同じ 404(GET・POST とも)・「調子」に live が出ない・見回りは何もしない
  - オン: 以前の録画の画面 /live/ はスタジオへ 302(P3)・hls.js の同梱・録画元の一覧(合言葉を出さない)・中継(合言葉 Bearer と Host を付ける・
    Sec-Fetch-Site と入口の合言葉の検査・知らない録画元・パスの検査・思わぬ種類の応答・録画元が止まっている)・「調子」の行
  - 見回り: 手元の録画の部品(src/pipeline/ingest/recorder.py)を切り離して起動する → 動いている → 古い版なら終わってもらって起動し直す
  - P2 マークと書き出し(src/flow/live_export.py): マークの API(オフなら 404・検査・fsync した正本)・本物の録画の部品(--source direct)で
    録画中にマーク → 録画待ち → 届いたら取得 → 30fps(30/1・長さ)→ スタジオと同じ置き場所・名前・.clip.json(source.kind live)→
    文字起こしへ(偽のまとめて実行)・取り消し・録画が先に終わった(録れた所まで)・録画元が落ちた(失敗と理由)・欠け(要差し替え)・起動し直したらやり直す
  - P3 スタジオから: POST /live/api/begin(URL の検査・偽の yt-dlp で配信の状態・録画を始める・同じ配信は録画中のものを返す・画質の設定・
    録画元が止まっている)・POST /live/api/export の studio の形(録画の頭からの秒 → 絶対時刻・正本の id・値の検査・録画がまだ始まっていない)・
    api/ytt/live(status: オフなら録画元に聞かない・録画中 + 終わって 10 分以内・3 秒覚える / stop)・yt-dlp の呼び方(probe_live。偽の yt-dlp)
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "flow", "tests"))   # 共有の偽物 _livefix
import _livefix as LF  # noqa: E402
import launch as L  # noqa: E402
import live as LV  # noqa: E402
from flow import live_adopt as LA  # noqa: E402
from flow import livesession as LS  # noqa: E402
from flow import run as RunMod  # noqa: E402
from flow import live_export as LX  # noqa: E402
from human.friend import live_requests as LR  # noqa: E402
import prefs as P  # noqa: E402
from ytt import fsio, jobs, loudness, normalize, schemas, tools  # noqa: E402

TOKEN = LF.TOKEN
FakeRecorder = LF.FakeRecorder   # 録画元の偽物(flow/tests/_livefix.py。test_live_archive_api.py も借りる)
FakeStudio = LF.FakeStudio       # スタジオの偽物(同上)
free_port = LF.free_port


def wait_for(fn, timeout=20.0, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


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
                                                        "autoAdopt": {"enabled": True, "waitMin": 5},
                                                        "liveTx": {"enabled": True, "model": "large-v3"},   # 配信中の候補の文字起こし(D-11 案 b)は既定オン(部品が無ければ何もしない)
                                                        "autoDeliver": True})   # 自動の切り抜きを確認なしで友人へ届ける(0.48.1。10-08 ユーザー決定)
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

    def test_auto_deliver_setting(self):
        """live.autoDeliver(0.48.1): 真偽だけ・壊れた保存値は既定(オン)に戻る"""
        self.assertIs(self.p.patch("live", {"autoDeliver": False})["autoDeliver"], False)
        self.assertIs(self.p.get(["live"])["live"]["autoDeliver"], False)
        for bad in (1, "true", None, [True]):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", {"autoDeliver": bad})
        self.assertIs(self.p.get(["live"])["live"]["autoDeliver"], False)   # 断ったときは変えない
        self.assertIs(self.p.patch("live", {"autoDeliver": True})["autoDeliver"], True)
        path = os.path.join(self.tmp, "prefs.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        d["live"]["autoDeliver"] = "yes"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        self.assertIs(P.Prefs(path, fsio.atomic_write).get(["live"])["live"]["autoDeliver"], True)

    def test_live_tx_settings(self):
        """配信中の候補の文字起こし live.liveTx(D-11 案 b): 鍵ごとに直す・enabled は真偽・model は large-v3 / large-v3-turbo・壊れた保存値は既定に戻す"""
        self.assertEqual(self.p.patch("live", {"liveTx": {"enabled": False}})["liveTx"], {"enabled": False, "model": "large-v3"})
        self.assertEqual(self.p.patch("live", {"liveTx": {"model": "large-v3-turbo"}})["liveTx"], {"enabled": False, "model": "large-v3-turbo"})   # 鍵ごと
        self.assertEqual(self.p.patch("live", {"quality": "720p"})["liveTx"], {"enabled": False, "model": "large-v3-turbo"})   # ほかの鍵を直しても残る
        for bad in ({"liveTx": "on"}, {"liveTx": []}, {"liveTx": {"enabled": "yes"}}, {"liveTx": {"enabled": 1}}, {"liveTx": {"enabled": None}},
                    {"liveTx": {"model": "small"}}, {"liveTx": {"model": "../x"}}, {"liveTx": {"model": None}}):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertEqual(self.p.get(["live"])["live"]["liveTx"], {"enabled": False, "model": "large-v3-turbo"})   # 断ったときは変えない
        self.assertEqual(P.LIVE_TX_MODELS, ("large-v3", "large-v3-turbo"))
        path = os.path.join(self.tmp, "prefs.json")
        for stored, want in (({"enabled": "yes", "model": "small"}, {"enabled": True, "model": "large-v3"}),   # 壊れた値は読むときに既定へ(断らない)
                             ({"enabled": False, "model": 3}, {"enabled": False, "model": "large-v3"}),          # 壊れた鍵だけ
                             ("x", {"enabled": True, "model": "large-v3"})):                                      # 節が dict でない
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"live": {"enabled": True, "folder": "E:\\Video\\live-rec", "liveTx": stored}}, f)
            v = P.Prefs(path, fsio.atomic_write).get(["live"])["live"]
            self.assertEqual((v["liveTx"], v["enabled"], v["folder"]), (want, True, "E:\\Video\\live-rec"), stored)

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
        self.assertEqual((code, d.get("recorderKept"), d.get("notice")), (200, True, LS.KEPT_NOTE))
        self.assertTrue(wait_for(lambda: self.srv.live._stopped is not None, 20))
        self.assertEqual(self.srv.live._stopped, "kept")
        self.assertTrue(any(LS.KEPT_NOTE in m for m in logs), logs)
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
        self.assertEqual(d["recording"]["channel"], ("ch名" + "x" * 300)[:LS.CHANNEL_MAX])
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

    # ---------- 友人のライブ配信の依頼(docs/spec/friend-intake.md の 2-15) ----------
    def friend_ctx(self, **extra):
        """src/human/friend/intake.py の _handle_live_request が live_begin へ渡す ctx の形"""
        return dict({"rid": "20261008-200000-abc123", "deliverDir": os.path.join(self.tmp, "Dropbox", "切り抜き依頼", "出力"),
                     "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信の題", "streamer": "兎田ぺこら",
                     "speakers": {"count": 1, "names": ["兎田ぺこら"], "styles": {}}, "videoTracks": 2, "cut": "silence", "memo": "",
                     "settings": {"sens": "high", "pad": 0.5, "afterStream": False}}, **extra)

    def test_begin_request(self):
        """Live.begin_request: オフなら 409(yt-dlp も録画元も呼ばない)・配信中なら録画を始めて依頼に結びつけ、検出を起こす・
        同じ配信を録画中ならそれに結びつける(新しい依頼で置き換える)・配信中でなければ 409 で結びつけない・録画元が止まっていれば 502"""
        live = self.srv.live
        rec = {"id": "20261008-200000-abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信の題", "state": "waiting", "active": True}
        started = []
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": []})
        self.fake.routes[("POST", "/live/start")] = lambda b: (started.append(b), (200, {"recording": rec}))[1]
        calls = self.probe_as("is_live")
        ctx = self.friend_ctx()
        with mock.patch.object(live.detector, "wake") as wake:   # 本物はワーカーを起こす(テストでは子プロセスを作らない)
            with self.assertRaises(LX.LiveError) as cm:
                live.begin_request(rec["url"], ctx)
            self.assertEqual(cm.exception.code, 409)
            self.assertIn("オフ", str(cm.exception))
            self.assertEqual((calls, started, live.requests.all()), ([], [], {}))
            self.enable()
            self.assertEqual(live.begin_request(rec["url"], ctx), {"recorder": "fake", "recording": rec["id"], "existing": False})
            self.assertEqual([s["url"] for s in started], [rec["url"]])
            item = live.requests.get("fake", rec["id"])
            self.assertEqual({k: item[k] for k in ("rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut")},
                             {k: ctx[k] for k in ("rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut")})
            self.assertEqual(item["settings"], dict(LR.SETTINGS_DEFAULT, sens="high", pad=0.5, afterStream=False))   # 無い鍵は既定
            wake.assert_called_once_with()
            # 同じ配信を録画中 → それに結びつける(録画は始めない)。新しい依頼で置き換える
            self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [dict(rec, state="recording")]})
            out = live.begin_request(rec["url"], dict(ctx, rid="20261008-210000-def456"))
            self.assertEqual((out["existing"], len(started)), (True, 1))
            self.assertEqual(live.requests.get("fake", rec["id"])["rid"], "20261008-210000-def456")
            # 依頼の録画が上限(live_requests.MAX_ACTIVE)まで録画中なら、別の配信の依頼は 409(yt-dlp は呼ばない)。上限 1 のときの形で確かめる
            n = len(calls)
            with mock.patch.object(LR, "MAX_ACTIVE", 1), self.assertRaises(LX.LiveError) as cm:
                live.begin_request("https://www.youtube.com/watch?v=bbbbbbbbbbb", dict(ctx, rid="20261008-220000-aaa111"))
            self.assertEqual((cm.exception.code, len(calls)), (409, n))
            self.assertIn("同時に 1 本まで", str(cm.exception))
            self.assertIn("配信の題", str(cm.exception))
            # 既定は同時に 2 本(10-09 ユーザー決定): 録画中の依頼が 1 本なら別の配信も通る・2 本なら 409
            self.assertEqual(LR.MAX_ACTIVE, 2)
            self.assertEqual([r["id"] for r in live.active_requests("https://www.youtube.com/watch?v=bbbbbbbbbbb")], [rec["id"]])
            rec2 = dict(rec, id="20261008-201000-bbbbbbbbbbb", url="https://www.youtube.com/watch?v=bbbbbbbbbbb", title="二つ目", state="recording")
            live.requests.put("fake", rec2["id"], dict(ctx, rid="20261008-223000-bbb222"))
            self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [dict(rec, state="recording"), rec2]})
            with self.assertRaises(LX.LiveError) as cm:
                live.begin_request("https://www.youtube.com/watch?v=ccccccccccc", dict(ctx, rid="20261008-224000-ccc333"))
            self.assertEqual((cm.exception.code, len(calls)), (409, n))
            self.assertIn("同時に 2 本まで", str(cm.exception))
            live.requests.remove("fake", rec2["id"])
            self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [dict(rec, state="ended", active=False)]})   # 終わった → 次の依頼を通す
            # 配信中でない・調べられない → 409(結びつけない。受付が理由を友人へ返す)
            for st in ("was_live", "post_live", "NA"):
                self.probe_as(st)
                with self.assertRaises(LX.LiveError) as cm:
                    live.begin_request("https://www.youtube.com/watch?v=bbbbbbbbbbb", dict(ctx, rid="20261008-220000-aaa111"))
                self.assertEqual(cm.exception.code, 409, st)
                self.assertIn("配信中・配信前の配信ではありません", str(cm.exception))
            self.assertEqual(list(live.requests.all()), ["fake/" + rec["id"]])
            self.assertEqual(wake.call_count, 2)
        # 録画元が止まっている → 502
        self.probe_as("is_live")
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": []})
        self.fake.close()
        with self.assertRaises(LX.LiveError) as cm:
            live.begin_request("https://www.youtube.com/watch?v=ccccccccccc", ctx)
        self.assertEqual(cm.exception.code, 502)
        self.assertEqual(len(live.requests.all()), 1)
        self.fake = FakeRecorder()

    def _fake_recording(self, rec):
        """録画元の録画の状態(firstPdt・lastPdt = 1 時間録れている)と、まだ届いていないセグメント(書き出しは録画待ちのまま)"""
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        self.fake.routes[("GET", "/live/%s/status" % rec)] = lambda b: (200, {"id": rec, "url": url, "title": "配信の題",
                                                                           "firstPdt": "2026-10-08T11:00:00.000Z", "lastPdt": "2026-10-08T12:00:00.000Z"})
        self.fake.routes[("GET", "/live/%s/segments" % rec)] = lambda b: (200, {"url": url, "active": True, "state": "recording", "firstPdt": "2026-10-08T11:00:00.000Z",
                                                                             "lastPdt": "2026-10-08T11:00:05.000Z", "segments": [], "gaps": []})

    def test_adopt_and_export_with_friend_request(self):
        """結びついた録画の採用(Live.adopt)と人のマーク(export_studio): after は auto に固定・余白は依頼の pad・配信者は依頼のもの(本文の指定が先)・
        ジョブに request {rid, deliverDir, speakers, videoTracks, cut}。配信後のアーカイブからの追加(origin archive)は依頼の afterStream が真のときだけ結びつく。
        結びついていない録画はホームの設定のまま(after = live.auto.after・余白 = live.auto.pad)"""
        self.enable()
        live = self.srv.live
        studio = FakeStudio()
        live.studio_call = studio
        rec_a, rec_b, rec_c = "20261008-200000-abcdefghijk", "20261008-200000-bbbbbbbbbbb", "20261008-200000-ccccccccccc"
        for r in (rec_a, rec_b, rec_c):
            self._fake_recording(r)
        ctx_a = self.friend_ctx()                                                            # afterStream なし・余白 0.5 秒
        ctx_b = self.friend_ctx(rid="20261008-200000-abc456", streamer="", cut=None, settings={"pad": 0, "afterStream": True})
        live.requests.put("fake", rec_a, ctx_a)
        live.requests.put("fake", rec_b, ctx_b)
        want_a = {k: ctx_a[k] for k in ("rid", "deliverDir", "speakers", "videoTracks", "cut")}

        def adopt(rec, start, end, **body):
            res = live.adopt(dict({"recorder": "fake", "recording": rec, "start": start, "end": end, "label": "山"}, **body))
            self.assertFalse(res["existing"])
            return res["job"]
        # 配信中の検出の自動の採用(auto): 依頼の余白 0.5 秒・after auto・配信者は依頼のもの
        j = adopt(rec_a, 100.0, 140.0, origin="auto")
        self.assertEqual((j["origin"], j["after"], j["transcribe"], j["streamer"], j["request"]), ("auto", "auto", True, "兎田ぺこら", want_a))
        self.assertEqual((j["studio"]["start"], j["studio"]["end"]), (99.5, 140.5))
        # 人の採用(manual): 余白なし・本文の after none より依頼(届ける)が先・本文の配信者は使う
        j = adopt(rec_a, 200.0, 210.0, after="none", streamer="さくらみこ")
        self.assertEqual((j["origin"], j["after"], j["streamer"], j["request"]["rid"]), ("manual", "auto", "さくらみこ", ctx_a["rid"]))
        self.assertEqual((j["studio"]["start"], j["studio"]["end"]), (200.0, 210.0))
        # 配信後のアーカイブ(archive): afterStream なしの依頼には結びつかない = ホームの設定(after check・余白 2 秒)
        j = adopt(rec_a, 300.0, 330.0, origin="archive")
        self.assertEqual((j["origin"], j["after"], j["streamer"], "request" in j), ("archive", "check", "", False))
        self.assertEqual((j["studio"]["start"], j["studio"]["end"]), (298.0, 332.0))
        # afterStream ありの依頼には結びつく(余白 0・配信者が空なら ""・カットの指定なし)
        j = adopt(rec_b, 100.0, 130.0, origin="archive")
        self.assertEqual((j["after"], j["streamer"], j["request"]), ("auto", "", {"rid": ctx_b["rid"], "deliverDir": ctx_b["deliverDir"],
                                                                                  "speakers": ctx_b["speakers"], "videoTracks": 2, "cut": None}))
        self.assertEqual((j["studio"]["start"], j["studio"]["end"]), (100.0, 130.0))
        # 結びついていない録画: 今までどおり
        j = adopt(rec_c, 100.0, 140.0, origin="auto")
        self.assertEqual((j["after"], j["streamer"], "request" in j), ("check", "", False))
        self.assertEqual((j["studio"]["start"], j["studio"]["end"]), (98.0, 142.0))
        # 書き出しの記録(exports.json)にも request が残る(起動し直しても届け先が分かる)
        saved = fsio.read_json_file(os.path.join(live.store_dir, "exports.json"), 8 * 1024 * 1024)["jobs"]
        self.assertEqual(sorted(x["request"]["rid"] for x in saved if x.get("request")), sorted([ctx_a["rid"], ctx_a["rid"], ctx_b["rid"]]))

        # スタジオの画面の人のマーク(POST /live/api/export の studio): 結びついた録画は transcribe false でも届ける
        st = {"video": rec_a, "mark": "m1a2b3", "n": 1, "label": "人のマーク", "start": 10, "end": 22.5}
        code, d = self.jreq("POST", "/live/api/export", {"recorder": "fake", "recording": rec_a, "transcribe": False, "studio": st})
        self.assertEqual(code, 200, d)
        self.assertEqual((d["job"]["origin"], d["job"]["after"], d["job"]["transcribe"], d["job"]["streamer"], d["job"]["request"]),
                         ("manual", "auto", True, "兎田ぺこら", want_a))
        self.assertEqual((d["job"]["studio"]["start"], d["job"]["studio"]["end"]), (10.0, 22.5))   # 人の区間に余白は足さない
        code, d = self.jreq("POST", "/live/api/export", {"recorder": "fake", "recording": rec_c, "transcribe": False, "studio": dict(st, video=rec_c)})
        self.assertEqual(code, 200, d)
        self.assertEqual((d["job"]["after"], "request" in d["job"]), ("none", False))   # 結びついていない録画は今までどおり(transcribe false = 何もしない)
        for jj in self.jreq("GET", "/live/api/exports")[1]["jobs"]:
            self.jreq("POST", "/live/api/export/cancel", {"id": jj["id"]})

    def test_stop_long_requests(self):
        """D-13: 友人の依頼に結びついた録画は 1 依頼 live_requests.MAX_SEC(6 時間)まで。超えて録画中なら入口が録画元の stop を呼ぶ。
        止められなければ記録に 1 回(見回りのたびに書かない)"""
        live = self.srv.live
        logs = []
        live.log = logs.append
        rec = {"id": "20261008-200000-abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信の題", "state": "recording", "active": True}
        stops = []
        self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [rec]})
        self.fake.routes[("POST", "/live/%s/stop" % rec["id"])] = lambda b: (stops.append(1), (200, {"recording": dict(rec, state="stopped", active=False)}))[1]
        self.assertEqual(live.stop_long_requests(), [])   # 依頼が無い(録画元に聞かない)
        self.enable()
        live.requests.put("fake", rec["id"], self.friend_ctx())
        self.assertEqual((live.stop_long_requests(), stops), ([], []))   # まだ 6 時間たっていない
        live.requests.clock = lambda: time.time() - LR.MAX_SEC - 10
        live.requests.put("fake", rec["id"], self.friend_ctx(rid="20261008-010000-old111"))
        self.assertEqual((live.stop_long_requests(), stops), ([rec["id"]], [1]))
        self.assertTrue(any("6 時間を超えたので止めました" in m for m in logs), logs)
        rec.update(active=False, state="stopped")   # 止まった → もう呼ばない
        self.assertEqual((live.stop_long_requests(), stops), ([], [1]))
        rec.update(active=True, state="recording")   # 止められない(409)→ 記録に 1 回
        self.fake.routes[("POST", "/live/%s/stop" % rec["id"])] = lambda b: (409, {"message": "止められません"})
        self.assertEqual(live.stop_long_requests(), [])
        self.assertEqual(live.stop_long_requests(), [])
        self.assertEqual(sum(1 for m in logs if "止められませんでした" in m), 1)
        self.assertIn("HTTP 409: 止められません", [m for m in logs if "止められませんでした" in m][0])

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
        self.srv.live._recent = (time.time() - LS.STATUS_CACHE - 0.1, [])
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


class AutoDeliverTest(unittest.TestCase):
    """自分の配信の自動の切り抜きを確認なしで友人へ届ける(live.autoDeliver。0.48.1): Live._request_for が届ける依頼の形を返す"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-autodeliver-")
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.folder = os.path.join(self.tmp, "Dropbox", "切り抜き依頼")
        os.makedirs(self.folder)
        self.live = LV.Live(self.prefs, self.tmp, os.path.join(self.tmp, "logs"), store_dir=os.path.join(self.tmp, "live"), spawn=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_auto_and_archive_deliver_when_folder_is_set(self):
        self.prefs.patch("intake", {"folder": self.folder})
        for origin in ("auto", "archive"):
            req, after, who = self.live._request_for("local", "20261008-183154-dMVBWMfHdVQ", origin, "check", "")
            self.assertEqual((after, who), ("auto", ""), origin)
            self.assertEqual((req["deliverDir"], req["autoDeliver"]), (os.path.join(self.folder, "出力"), True), origin)
            self.assertRegex(req["rid"], r"^\d{8}-\d{6}-[0-9a-f]{6}$")   # 友人のアプリの依頼と同じ形(zip の名前の頭)
            self.assertNotIn("settings", req)   # 余白は live.auto.pad のまま(adopt は settings が無ければホームの設定)
        a, _b, _c = self.live._request_for("local", "r1", "auto", "check", "")
        b, _b2, _c2 = self.live._request_for("local", "r1", "auto", "check", "")
        self.assertNotEqual(a["rid"], b["rid"])   # 切り抜きごとに別の依頼 id = 1 本ずつ別の zip

    def test_manual_off_or_no_folder_does_not_deliver(self):
        self.prefs.patch("intake", {"folder": self.folder})
        self.assertEqual(self.live._request_for("local", "r1", "manual", "check", "x"), (None, "check", "x"))   # 人のマークは案件の [採用] で
        self.prefs.patch("live", {"autoDeliver": False})
        self.assertEqual(self.live._request_for("local", "r1", "auto", "check", ""), (None, "check", ""))
        self.prefs.patch("live", {"autoDeliver": True})
        self.prefs.patch("intake", {"folder": ""})
        self.assertEqual(self.live._request_for("local", "r1", "auto", "check", ""), (None, "check", ""))   # 届ける先が無い
        self.assertIsNone(self.live.deliver_dir())

    def test_friend_request_wins(self):
        """友人のライブ配信の依頼に結びついた録画は、その依頼の形(届け先は依頼の 出力)が先"""
        self.prefs.patch("intake", {"folder": self.folder})
        self.live.requests.put("local", "r2", {"rid": "20261008-120000-abcdef", "deliverDir": os.path.join(self.folder, "出力"), "settings": {"afterStream": False}})
        req, after, _w = self.live._request_for("local", "r2", "auto", "check", "")
        self.assertEqual((req["rid"], after), ("20261008-120000-abcdef", "auto"))
        req2, after2, _w2 = self.live._request_for("local", "r2", "archive", "check", "")   # 依頼が配信後の追加を要らないと言えば、自分の設定でも届けない
        self.assertEqual((req2, after2), (None, "check"))


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


if __name__ == "__main__":
    unittest.main()
