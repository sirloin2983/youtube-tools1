# -*- coding: utf-8 -*-
"""友人のライブ配信の依頼(docs/spec/friend-intake.md の 2-15)の ② の側: ライブ係 flow/livesession.LiveSession の begin_request(録画を始めて依頼に結びつける)と、
結びついた録画の採用(adopt。after は auto に固定・余白は依頼の pad・配信者は依頼のもの・アーカイブは afterStream が真のときだけ)。
入口 home の Live は使わない(同時の上限 _request_limit は入口の物 = 本テストでは差し替える。入口の既定は src/home/tests/test_live.py)。

    py -3.10 -m unittest src/flow/tests/test_live_request.py

偽の録画元(HTTP。合言葉)・偽の yt-dlp(probe の差し替え)・偽のスタジオで、本物の YouTube へは繋がない。
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import _livefix as FIX  # noqa: E402
from flow import live_export as LX  # noqa: E402
from ytt import fsio  # noqa: E402

TOKEN = FIX.TOKEN


class FriendRequestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-request-")
        self.fake = FIX.FakeRecorder()
        self.cfg = FIX.recorder_cfg(self.fake.url, TOKEN, enabled=False)
        self.limit = [None]   # 同時に録画する依頼の上限(入口は live_requests.MAX_ACTIVE。None = 上限なし)
        self.live = FIX.new_session(self.tmp, self.cfg)
        self.live._request_limit = lambda: self.limit[0]
        self.live.detector.wake = lambda: None   # 本物はワーカーを起こす
        self.live.exporter.start = lambda: None   # 書き出しは動かさない(ジョブは「録画待ち」のまま)

    def tearDown(self):
        self.live.detector.stop()
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def probe_as(self, status, title="配信の題", message="", channel="Pekora Ch. 兎田ぺこら"):
        calls = []

        def probe(url):
            calls.append(url)
            return {"status": status, "title": title, "channel": channel, "message": message}
        self.live.probe = probe
        return calls

    def friend_ctx(self, **extra):
        """src/human/friend/intake.py の _handle_live_request が live_begin へ渡す ctx の形"""
        return dict({"rid": "20261008-200000-abc123", "deliverDir": os.path.join(self.tmp, "Dropbox", "切り抜き依頼", "出力"),
                     "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信の題", "streamer": "兎田ぺこら",
                     "speakers": {"count": 1, "names": ["兎田ぺこら"], "styles": {}}, "videoTracks": 2, "cut": "silence", "memo": "",
                     "settings": {"sens": "high", "pad": 0.5, "afterStream": False}}, **extra)


    def test_begin_request(self):
        """Live.begin_request: オフなら 409(yt-dlp も録画元も呼ばない)・配信中なら録画を始めて依頼に結びつけ、検出を起こす・
        同じ配信を録画中ならそれに結びつける(新しい依頼で置き換える)・配信中でなければ 409 で結びつけない・録画元が止まっていれば 502"""
        live = self.live
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
            self.cfg["enabled"] = True
            self.assertEqual(live.begin_request(rec["url"], ctx), {"recorder": "fake", "recording": rec["id"], "existing": False})
            self.assertEqual([s["url"] for s in started], [rec["url"]])
            item = live.requests.get("fake", rec["id"])
            self.assertEqual({k: item[k] for k in ("rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut")},
                             {k: ctx[k] for k in ("rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut")})
            self.assertEqual(item["settings"], dict({"sens": "normal", "perHour": 6, "length": 45, "waitMin": 5, "pad": 2.0, "afterStream": True}, sens="high", pad=0.5, afterStream=False))   # 無い鍵は既定
            wake.assert_called_once_with()
            # 同じ配信を録画中 → それに結びつける(録画は始めない)。新しい依頼で置き換える
            self.fake.routes[("GET", "/live/list")] = lambda b: (200, {"recordings": [dict(rec, state="recording")]})
            out = live.begin_request(rec["url"], dict(ctx, rid="20261008-210000-def456"))
            self.assertEqual((out["existing"], len(started)), (True, 1))
            self.assertEqual(live.requests.get("fake", rec["id"])["rid"], "20261008-210000-def456")
            # 依頼の録画が上限(live_requests.MAX_ACTIVE)まで録画中なら、別の配信の依頼は 409(yt-dlp は呼ばない)。上限 1 のときの形で確かめる
            n = len(calls)
            self.limit[0] = 1
            with self.assertRaises(LX.LiveError) as cm:
                live.begin_request("https://www.youtube.com/watch?v=bbbbbbbbbbb", dict(ctx, rid="20261008-220000-aaa111"))
            self.assertEqual((cm.exception.code, len(calls)), (409, n))
            self.assertIn("同時に 1 本まで", str(cm.exception))
            self.assertIn("配信の題", str(cm.exception))
            # 同時に 2 本(入口の既定。10-09 ユーザー決定): 録画中の依頼が 1 本なら別の配信も通る・2 本なら 409
            self.limit[0] = 2
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
        self.fake = FIX.FakeRecorder()

    def _fake_recording(self, rec):
        """録画元の録画の状態(firstPdt・lastPdt = 1 時間録れている)と、まだ届いていないセグメント(書き出しは録画待ちのまま)"""
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        self.fake.routes[("GET", "/live/%s/status" % rec)] = lambda b: (200, {"id": rec, "url": url, "title": "配信の題",
                                                                           "firstPdt": "2026-10-08T11:00:00.000Z", "lastPdt": "2026-10-08T12:00:00.000Z"})
        self.fake.routes[("GET", "/live/%s/segments" % rec)] = lambda b: (200, {"url": url, "active": True, "state": "recording", "firstPdt": "2026-10-08T11:00:00.000Z",
                                                                             "lastPdt": "2026-10-08T11:00:05.000Z", "segments": [], "gaps": []})

    def test_adopt_with_friend_request(self):
        """結びついた録画の採用(LiveSession.adopt。人のマークの HTTP は src/home/tests/test_live.py の test_export_studio_with_friend_request): after は auto に固定・余白は依頼の pad・配信者は依頼のもの(本文の指定が先)・
        ジョブに request {rid, deliverDir, speakers, videoTracks, cut}。配信後のアーカイブからの追加(origin archive)は依頼の afterStream が真のときだけ結びつく。
        結びついていない録画はホームの設定のまま(after = live.auto.after・余白 = live.auto.pad)"""
        live = self.live
        studio = FIX.FakeStudio()
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


if __name__ == "__main__":
    unittest.main()
