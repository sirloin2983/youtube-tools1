"""F2-6 送る欄を広げる(動画ファイル・ライブ)のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_live.py

- ライブの設定の検査(長さ 10〜180 = A-5b の仮)と、依頼と録画の結びつき RequestBook(③ の live_requests を読まない)
- ② のライブ係 FriendLive: 送る → ② の待ち行列(本物の flow/runqueue.Queue)の live の hook → 録画を始めて結びつける(長さは送った欄から)→
  切り抜きごとの実行が終わるたびに行にパック → 届け方の n 本ごとに組 → 録画が終わったら残りを 1 組・行は「届いた」。録画中でも組になった物は決められる
- 終了: 録画中でも、この玄関が起こした録画の部品は止める・止めた本数(起動役の状態の窓)・配信後の追加の解析をスタジオなしの台帳へ・終わった録画を 3 日で消す
- 動画ファイル: 選んだ動画を id で覚える(パスは画面に出さない)→ 一時保管の 依頼/ へ写してから ② へ(元の動画は読むだけ)
録画の部品・streamlink・yt-dlp・本物のネットは使わない(録画元は偽物・配信中かは偽物)。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import live_export as LX, runqueue as Q  # noqa: E402
from friendapp import api as A, engine as E, inbox as I, live as L, live_session as LS, server as SV  # noqa: E402

VID = "abcdefghijk"
URL = "https://www.youtube.com/watch?v=" + VID
REC = "20261016-200000-" + VID
T0 = 1790000000.0
SETTINGS = {"sens": "low", "perHour": 8, "length": 150, "waitMin": 10, "pad": 5, "afterStream": False}


class FakeRecorder:
    """録画元の代わり(FriendLive.call に差し替える)。録画を始めると REC が録画中になる"""

    def __init__(self):
        self.recs, self.calls, self.quit_code, self.gone = {}, [], 200, False

    def __call__(self, rc, method, path, body=None, timeout=3.0):
        self.calls.append((method, path))
        if self.gone:
            return None, None
        if method == "POST" and path == "/live/quit":
            self.gone = self.quit_code == 200   # 静かに終わった
            return self.quit_code, {"message": "録画中"}
        if path == "/api/ping":
            return 200, {"app": "ytt-recorder", "version": "x"}
        if method == "GET" and path == "/live/list":
            return 200, {"recordings": [dict(r) for r in self.recs.values()], "freeBytes": 500 * LX.GB, "active": 0}
        if method == "POST" and path == "/live/start":
            r = {"id": REC, "url": body["url"], "title": body["title"], "state": "recording", "active": True,
                 "firstPdt": LX.epoch_iso(T0), "lastPdt": LX.epoch_iso(T0 + 3600)}
            self.recs[REC] = r
            return 200, {"recording": dict(r)}
        m = re.match(r"^/live/([^/?]+)/(stop|delete|status)", path)
        if m and m.group(1) in self.recs:
            if m.group(2) == "stop":
                self.end(m.group(1))
            elif m.group(2) == "delete":
                self.recs.pop(m.group(1))
                return 200, {"ok": True, "deleted": True}
            return 200, dict(self.recs.get(m.group(1)) or {})
        return 404, {"message": "ありません"}

    def end(self, rec, ago=0.0):
        r = self.recs[rec]
        r.update(state="ended", active=False, endedAt=LX.epoch_iso(time.time() - ago))


def fake_run(run_id, state, packs, request_id, phase="live", error=""):
    return types.SimpleNamespace(id=run_id, state=state, error=error, result_path=None, all_packs=lambda: list(packs), request_id=request_id,
                                 pool={"key": "x", "meta": {"phase": phase}})


class SettingsTest(unittest.TestCase):
    def test_check_settings(self):
        self.assertEqual(L.check_settings(dict(SETTINGS, length=180)), dict(SETTINGS, length=180, pad=5.0))
        bad = [({"length": 181}, "長さは 10〜180"), ({"length": 9}, "長さ"), ({"sens": "x"}, "感度"), ({"perHour": 0}, "1 時間の枠"),
               ({"waitMin": 61}, "待ち"), ({"pad": 6}, "余白"), ({"afterStream": 1}, "配信後"), ({"length": 30.5}, "長さ")]
        for kw, why in bad:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError) as cm:
                    L.check_settings(dict(SETTINGS, **kw))
                self.assertIn(why, str(cm.exception))
        self.assertEqual(L.clean_settings({"length": 180, "sens": "high"})["length"], 180)
        self.assertEqual(L.clean_settings({"length": 999}), L.SETTINGS_DEFAULT)
        self.assertIn("長さ 150 秒", L.settings_label(L.clean_settings(SETTINGS)))
        self.assertEqual(L.clean_settings(dict(SETTINGS, lengthMode="auto"))["lengthMode"], "auto")   # 自動(場面ごと)だけ残す(C-2-11)

    def test_request_book(self):
        tmp = tempfile.mkdtemp(prefix="friend-livebook-")
        self.addCleanup(shutil.rmtree, tmp, True)
        now = [T0]
        book = L.RequestBook(os.path.join(tmp, "requests.json"), clock=lambda: now[0])
        item = book.put("local", REC, {"rid": "20261016-120000-abcdef", "deliverDir": "C:/x", "settings": SETTINGS, "videoTracks": 2, "deliverBatch": 5})
        self.assertEqual((item["deliverDir"], item["settings"]["length"], item["videoTracks"]), ("", 150, 2))   # 友人の PC は届けない
        book2 = L.RequestBook(os.path.join(tmp, "requests.json"))
        self.assertEqual(book2.get("local", REC)["settings"]["length"], 150)
        self.assertEqual(list(book2.all()), ["local/" + REC])
        now[0] += 4 * 86400
        self.assertEqual(book.prune(), 1)
        self.assertIsNone(book.get("local", REC))


class LiveFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friend-live-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.places = {"data": os.path.join(self.tmp, "data"), "friend": os.path.join(self.tmp, "data", "app", "friendapp"),
                       "cases": os.path.join(self.tmp, "作業"), "studio": None, "save": lambda: os.path.join(self.tmp, "save")}
        os.makedirs(self.places["friend"])
        os.makedirs(self.places["cases"])
        self.box = I.Inbox(os.path.join(self.places["friend"], "inbox.json"), os.path.join(self.tmp, "outbox"), self.places["save"],
                           lambda: self.places["cases"])
        for p in (mock.patch.object(E._preview, "clip_seconds", lambda ds: [30.0] * len(ds)), mock.patch.object(E._preview, "batch_preview", lambda ds, log=None: None),
                  mock.patch.object(E._outbox, "build", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        self.rec = FakeRecorder()
        self.eng = E.Engine(self.places, self.box, queue_factory=self.queue, live_factory=self.live)
        self.addCleanup(self.close)
        self.api = A.Api(self.places, self.box, lambda: self.eng, fetch=lambda vid: {"title": "配信の題", "channel": "Ch"},
                         probe=lambda url: {"status": "is_live", "message": ""})

    def queue(self, book, log_dir, log=None):
        return Q.Queue(None, poll=0.01, tools=types.SimpleNamespace(studio=None))

    def live(self, places, queue_fn, log):
        lv = LS.FriendLive(places, queue_fn, log=log, spawn=False)
        lv.call = self.rec
        lv.probe = lambda url: {"status": "is_live", "title": "配信の題", "channel": "Ch", "message": ""}
        lv.exporter.start = lambda: None
        return lv

    def close(self):
        self.eng.live.detector.stop()
        self.eng.close()

    def send_live(self, **kw):
        """ライブを送る -> 行。送る欄の 3 つ(perHour・長さ・配信後の追加)は body・感度と待ちと余白は ⚙ の値(C-2-11)"""
        self.api.set_prefs({"liveSens": SETTINGS["sens"], "liveWait": SETTINGS["waitMin"], "livePad": SETTINGS["pad"]})
        live = {"perHour": SETTINGS["perHour"], "lengthMode": "fixed", "length": SETTINGS["length"], "afterStream": SETTINGS["afterStream"]}
        live.update(kw.pop("live", {}))
        body = {"source": "url", "kind": "live", "url": URL, "title": "配信の題", "channel": "Ch", "streamer": "", "people": [],
                "videoTracks": 2, "live": live}
        body.update(kw)
        return self.api.send(body)["rows"][0]

    def packs(self, n, start=0):
        out = []
        for i in range(start, start + n):
            d = os.path.join(self.places["cases"], "配信の題", "%02d_clip_pack" % i)
            os.makedirs(d)
            out.append(d)
        return out

    def test_send_live_records_and_links_request(self):
        row = self.send_live()
        self.assertEqual((row["state"], row["kind"], row["live"]["recorder"], row["live"]["recording"]), ("recording", "live", "local", REC))
        item = self.eng.live.requests.get("local", REC)   # 結びつき = 受信箱の行の id・長さは送った欄(束の analyze に入れない)
        self.assertEqual((item["rid"], item["settings"]["length"], item["settings"]["sens"], item["settings"]["afterStream"], item["deliverDir"]),
                         (row["id"], 150, "low", False, ""))
        b = self.eng.live.bundle("local", REC)
        self.assertEqual((b["adopt"]["perHour"], b["adopt"]["waitMin"], b["pack"]["videoTracks"]), (8, 10, 2))
        self.assertEqual(self.api.form()["live"], dict(SETTINGS, pad=5.0, lengthMode="fixed"))   # 前回の値(A-5)
        self.assertEqual(self.eng.live.active_count(), 1)

    def worker_req(self):
        """検出のワーカーが読む依頼の設定(config.json の requests を ① の clean_requests で読んだ形)と、その録画の spec"""
        from pipeline.analyze import live_excite_worker as W
        self.eng.live.detector.write_config()
        with open(os.path.join(self.eng.live.detector.dir, "config.json"), encoding="utf-8") as f:
            req = W.clean_requests(json.load(f)["requests"])["local/" + REC]
        spec = W.request_spec(dict(W.SPEC_DEFAULT, lengthFrom="studio"), req)
        return req, spec, W.shape_of(spec)

    def test_length_auto_is_scene_and_fixed_is_seconds(self):
        """C-2-11: 長さ「自動(場面ごと)」は場面ごとの形(長さは場面が取れないときの長さ)・固定は送った秒(ワーカーの読み方まで)"""
        row = self.send_live(live={"lengthMode": "auto", "length": 9999})
        self.assertEqual(row["form"]["live"]["lengthMode"], "auto")
        item = self.eng.live.requests.get("local", REC)
        self.assertEqual((item["settings"]["lengthMode"], item["settings"]["length"]), ("auto", 45))   # 長さは前回の値(初め 45。送る欄の 9999 は読まない)= 場面が取れないときの長さ
        req, spec, shape = self.worker_req()
        self.assertEqual((req["lengthMode"], shape, spec["lengthFrom"], spec["length"]), ("auto", "scene", "friendScene", 45.0))
        self.assertIn("長さ 自動(場面ごと)", L.settings_label(item["settings"]))

    def test_length_fixed_and_old_request_stay_fixed(self):
        self.send_live(live={"lengthMode": "fixed", "length": 60})
        item = self.eng.live.requests.get("local", REC)
        self.assertNotIn("lengthMode", item["settings"])   # 無い = 固定(前の形の依頼と同じ)
        req, spec, shape = self.worker_req()
        self.assertEqual((req.get("lengthMode"), shape, spec["lengthFrom"], spec["length"]), (None, "fixed", "friend", 60.0))
        old = L.clean_settings({"sens": "high", "perHour": 3, "length": 30})   # lengthMode の無い前の形の依頼
        self.assertNotIn("lengthMode", old)
        self.assertEqual(L.clean_settings(dict(old, lengthMode="weird")), old)

    def test_update_live_while_recording(self):
        """C-2-11: 録画中に 1 時間の枠・長さ・配信後の追加を変える → ② の結びつき(ワーカーの config.json まで)と行の form.live が変わる"""
        rid = self.send_live(live={"lengthMode": "fixed", "length": 60, "afterStream": False})["id"]
        row = self.api.update_live(rid, {"id": rid, "perHour": 3, "lengthMode": "auto", "length": 9999, "afterStream": True})
        self.assertEqual(row["form"]["live"], {"sens": "low", "perHour": 3, "length": 60, "waitMin": 10, "pad": 5.0, "afterStream": True, "lengthMode": "auto"})
        self.assertEqual(self.box.row(rid)["form"]["live"]["lengthMode"], "auto")
        s = self.eng.live.requests.get("local", REC)["settings"]
        self.assertEqual((s["perHour"], s["afterStream"], s["lengthMode"], s["length"], s["sens"]), (3, True, "auto", 60, "low"))
        req, _spec, shape = self.worker_req()
        self.assertEqual((req["perHour"], req["lengthMode"], shape), (3, "auto", "scene"))
        self.assertTrue(self.eng.live.archiver._request_after("local", REC))   # 配信後の追加は配信が終わったときに今の値を読む
        # 固定に戻す(長さだけ送らなければ今の長さ)・別の長さ
        row = self.api.update_live(rid, {"lengthMode": "fixed", "length": 90})
        s = self.eng.live.requests.get("local", REC)["settings"]
        self.assertEqual((row["form"]["live"]["lengthMode"], row["form"]["live"]["length"], s["length"], s.get("lengthMode")), ("fixed", 90, 90, None))
        self.assertEqual(self.worker_req()[2], "fixed")
        for bad, why in (({"perHour": 0}, "1 時間の枠"), ({"length": 181}, "長さは 10〜180"), ({"lengthMode": "x"}, "自動"), ({"afterStream": "yes"}, "配信後")):
            with self.subTest(bad=bad):
                with self.assertRaises(A.FormError) as cm:
                    self.api.update_live(rid, bad)
                self.assertIn(why, str(cm.exception))
        self.assertEqual(self.eng.live.requests.get("local", REC)["settings"]["length"], 90)   # 断った値は入らない

    def test_update_live_refuses_user_pc_and_not_recording_rows(self):
        rid = self.send_live()["id"]
        self.rec.end(REC)
        self.eng.live_tick()   # 録画が終わった
        with self.assertRaises(A.FormError) as cm:
            self.api.update_live(rid, {"perHour": 3})
        self.assertIn("録画中の行だけ", str(cm.exception))
        user = self.box.add("20261017-120000-abcdef", {"kind": "live", "live": dict(SETTINGS, lengthMode="auto")}, {"url": URL}, pc="user", kind="live")
        with self.assertRaises(A.FormError) as cm:
            self.api.update_live(user["id"], {"perHour": 3})
        self.assertEqual(str(cm.exception), "作る人の PC で録画している依頼は、ここから変えられません")
        with self.assertRaises(KeyError):
            self.api.update_live("nope", {"perHour": 3})

    def test_send_live_not_live_refused(self):
        self.eng.live.probe = lambda url: {"status": "was_live", "title": "", "channel": "", "message": ""}
        with self.assertRaises(A.FormError) as cm:
            self.send_live()
        self.assertIn("配信中・配信前", str(cm.exception))
        self.assertEqual(self.box.rows, [])

    def test_clips_group_while_recording_then_close(self):
        rid = self.send_live()["id"]
        for i, d in enumerate(self.packs(6)):
            self.eng.after_run(fake_run("c%d" % i, "done", [d], rid))
        self.eng.after_run(fake_run("c0", "done", [], rid))   # 同じ実行の 2 回目は数えない
        self.eng.after_run(fake_run("bad", "error", [], rid, error="書き出せませんでした"))
        v = self.box.view()[0]
        self.assertEqual((v["state"], len(v["groups"]), v["undecided"], v["live"]["errors"]), ("recording", 6, 6, 1))   # 1 本ずつ(C-3-1)= 待たされる本数は無い
        self.assertEqual([p["num"] for p in v["packs"]], [1, 2, 3, 4, 5, 6])
        got = self.box.decide(rid, [p["name"] for p in v["packs"][:5]], "keep")   # 録画中でも決められる
        self.assertEqual((len(got["done"]), self.box.row(rid)["state"]), (5, "recording"))
        self.eng.live_tick()   # まだ録画中
        self.assertEqual(self.box.row(rid)["state"], "recording")
        self.rec.end(REC)
        self.eng.live_tick()   # 録画が終わって作る物が無い = 残りを 1 組・行は「届いた」
        r = self.box.row(rid)
        self.assertEqual((r["state"], [len(g["names"]) for g in r["groups"]], r["live"]["phase"]), ("arrived", [1] * 6, "done"))
        self.box.decide(rid, [], "skip")
        self.assertEqual(self.box.row(rid)["state"], "done")
        self.eng.after_run(fake_run("late", "done", self.packs(1, 10), rid, phase="archive"))   # 閉じたあとに届いた(配信後の追加)
        r = self.box.row(rid)
        self.assertEqual((r["state"], r["packs"][-1]["phase"]), ("arrived", "archive"))
        self.eng.live_tick()
        self.assertEqual(self.box.row(rid)["groups"][-1]["label"], "配信後")

    def test_busy_or_after_stream_keeps_recording_row(self):
        rid = self.send_live(live={"afterStream": True})["id"]
        self.rec.end(REC)
        with mock.patch.object(self.eng.live, "busy_recording", lambda rc, rec: True):
            self.eng.live_tick()
        self.assertEqual((self.box.row(rid)["state"], self.box.row(rid)["live"]["phase"]), ("recording", "making"))
        with mock.patch.object(self.eng.live, "after_hold", lambda rc, raw: "配信後の追加を待っています"):
            self.eng.live_tick()
        self.assertEqual((self.box.row(rid)["state"], self.box.row(rid)["live"]["phase"]), ("recording", "after"))
        self.eng.live_tick()   # 本物の配信後の追加(afterStream が真)は、まだ待つ
        self.assertEqual(self.box.row(rid)["live"]["phase"], "after")
        with mock.patch.object(self.eng.live, "after_hold", lambda rc, raw: ""):
            self.eng.live_tick()   # 配信後の追加も済んだ・パックが 1 本も無い = 失敗
        r = self.box.row(rid)
        self.assertEqual(r["state"], "failed")
        self.assertIn("パックができませんでした", r["error"])

    def test_recorder_unreachable_skips(self):
        rid = self.send_live()["id"]
        self.eng.live.call = lambda *a, **k: (None, None)
        self.eng.live_tick()
        self.assertEqual(self.box.row(rid)["state"], "recording")
        self.assertEqual(self.eng.live.active_count(), 0)

    def test_stale_recording_row_closes_in_sweep(self):
        rid = self.send_live()["id"]
        self.eng.after_run(fake_run("c1", "done", self.packs(1), rid))
        self.box.clock = lambda: time.time() + I.LIVE_STALE + 60
        self.assertEqual(self.box.sweep(), 1)   # 閉じて、決めないまま 3 日たった 1 本は自動で見送る
        r = self.box.row(rid)
        self.assertEqual((r["state"], len(r["groups"]), r["packs"][0]["verdict"], r["packs"][0]["by"]), ("done", 1, "skip", "auto"))

    def test_close_with_everything_decided_marks_row_done(self):
        """録画が終わった時に、組になった物を全部決めていれば、行は「決めた」(録画中のまま残さない)"""
        rid = self.send_live()["id"]
        self.eng.after_run(fake_run("c0", "done", self.packs(2), rid))
        self.box.decide(rid, [], "keep")
        self.assertEqual(self.box.row(rid)["state"], "recording")
        self.rec.end(REC)
        self.eng.live_tick()
        self.assertEqual(self.box.row(rid)["state"], "done")

    def test_cancel_stops_recording(self):
        rid = self.send_live()["id"]
        self.assertEqual(self.api.cancel(rid), {"id": rid, "state": "cancelled"})
        self.assertIn(("POST", "/live/%s/stop" % REC), self.rec.calls)
        self.assertEqual(self.eng.live.active_count(), 0)
        self.assertIsNone(self.box.row(rid))   # 届いた物が無ければ行ごと消す(C-2-14)

    def test_cancel_recording_keeps_clips_already_arrived(self):
        rid = self.send_live()["id"]
        self.eng.after_run(fake_run("c0", "done", self.packs(2), rid))
        self.assertEqual(self.api.cancel(rid), {"id": rid, "state": "cancelled"})
        r = self.box.row(rid)   # 届いた物は受け取るに残す・送った物の一覧からは外す
        self.assertEqual((r["state"], r["cancelled"], len(r["packs"]), r["live"]["phase"]), ("arrived", True, 2, "done"))

    def test_close_kills_own_recorder_even_while_recording(self):
        lv = self.eng.live
        self.rec.quit_code = 409   # 録画中 = 録画の部品は quit を断る
        lv.proc = types.SimpleNamespace(poll=lambda: None)
        killed = []
        with mock.patch.object(LS.tools, "kill_tree", lambda p, wait=None: killed.append(p)):
            self.assertEqual(lv._stop_recorder(), "killed")
            lv.proc = None
            self.assertEqual(lv._stop_recorder(), "kept")   # この玄関が起こしていない部品は止められない
        self.assertEqual(len(killed), 1)

    def test_studio_call_goes_to_local_studio(self):
        seen = []
        studio = types.SimpleNamespace(video=lambda vid: (200, {"video": {"id": vid}}), analyze_add=lambda item, s: seen.append((item, s)) or {"added": [{"qid": "q1"}]},
                                       analyze_items=lambda: [{"qid": "q1", "status": "done"}],
                                       batch=types.SimpleNamespace(snapshot=lambda: {"items": [{"qid": "q1"}]}))
        self.eng.queue.tools.studio = studio
        lv = self.eng.live
        self.assertEqual(lv.studio_call("GET", "/api/video?id=" + VID), (200, {"video": {"id": VID}}))
        self.assertEqual(lv.studio_call("POST", "/api/queue/add", {"items": [{"videoId": VID}], "settings": {"count": 6}}), (200, {"added": [{"qid": "q1"}]}))
        self.assertEqual(seen, [({"videoId": VID}, {"count": 6})])
        self.assertEqual(lv.studio_call("GET", "/api/queue"), (200, {"items": [{"qid": "q1", "status": "done"}]}))
        self.assertEqual(lv.studio_queue(), {"items": [{"qid": "q1"}]})
        self.assertIsNone(lv.studio_call("GET", "/api/settings")[0])

    def test_clean_recordings_after_three_days(self):
        self.send_live()
        self.rec.recs["20261010-100000-old"] = {"id": "20261010-100000-old", "url": URL, "state": "ended", "active": False,
                                                 "endedAt": LX.epoch_iso(time.time() - 4 * 86400)}
        self.rec.end(REC, ago=3600)
        self.assertEqual(self.eng.live.clean_recordings(force=True), ["20261010-100000-old"])
        self.assertIn(REC, self.rec.recs)

    def test_live_cfg_and_rec_folder(self):
        c = self.eng.live.cfg()
        self.assertEqual((c["enabled"], c["autoArchive"], c["folder"]), (True, False, os.path.join(self.places["cases"], L.REC_FOLDER)))
        self.assertTrue(self.eng.live.request_all)


class FileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friend-file-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.places = {"data": os.path.join(self.tmp, "data"), "friend": os.path.join(self.tmp, "friend"), "cases": os.path.join(self.tmp, "作業"),
                       "save": lambda: os.path.join(self.tmp, "save")}
        for k in ("friend", "cases"):
            os.makedirs(self.places[k])
        self.box = I.Inbox(os.path.join(self.tmp, "inbox.json"), os.path.join(self.tmp, "outbox"), self.places["save"], lambda: self.places["cases"])
        self.submitted = []
        self.eng = types.SimpleNamespace(queue=types.SimpleNamespace(submit=lambda env, spec=None: self.submitted.append((env, spec)) or {"id": env["id"]}))
        self.api = A.Api(self.places, self.box, lambda: self.eng)
        self.src = os.path.join(self.tmp, "元", "【兎田ぺこら】歌ってみた.mp4")
        os.makedirs(os.path.dirname(self.src))
        with open(self.src, "wb") as f:
            f.write(b"v" * 3000)

    def wait_copy(self, rid):
        end = time.time() + 10
        while time.time() < end and self.api.copying():
            time.sleep(0.02)
        return self.box.row(rid)

    def test_remember_file_and_refuse_others(self):
        got = self.api.remember_file(self.src)
        self.assertEqual((got["name"], got["size"], got["title"], got["streamer"]), ("【兎田ぺこら】歌ってみた.mp4", 3000, "歌ってみた", "兎田ぺこら"))   # 題の元は頭の【】を除く
        self.assertNotIn("path", got)
        txt = os.path.join(self.tmp, "a.txt")
        open(txt, "w").close()
        for bad in (txt, os.path.join(self.tmp, "nope.mp4"), "relative.mp4", None):
            with self.assertRaises(A.FormError):
                self.api.remember_file(bad)
        self.assertIsNone(A.guess_streamer("名前なし.mp4"))

    def test_send_file_copies_then_submits(self):
        fid = self.api.remember_file(self.src)["id"]
        got = self.api.send({"source": "files", "files": [{"fileId": fid, "streamer": "兎田ぺこら"}], "people": [], "videoTracks": 2,
                             "ranges": [[1, 2]], "top": 99, "useWeights": True, "weights": {"wAudio": 9}})   # 区間・本数・重みは動画ファイルでは使わない
        self.assertEqual(got["skipped"], [])
        row = got["rows"][0]
        self.assertEqual((row["kind"], row["state"]), ("file", "sent"))
        r = self.wait_copy(row["id"])
        env, spec = self.submitted[0]
        copy = r["form"]["file"]["copy"]
        self.assertEqual((env["kind"], env["input"]["path"], env["input"]["normalize"], env["requestId"], r["runId"]), ("file", copy, True, row["id"], env["id"]))
        self.assertTrue(copy.startswith(os.path.join(self.places["cases"], "依頼")))
        with open(copy, "rb") as f:
            self.assertEqual(f.read(), b"v" * 3000)
        self.assertTrue(os.path.isfile(self.src), "元の動画は読むだけ")
        self.assertEqual((spec["pack"]["videoTracks"], spec["hints"]["streamer"]), (2, "兎田ぺこら"))
        self.assertNotIn("ranges", spec.get("hints", {}))
        v = self.box.view()[0]
        self.assertEqual(v["form"]["file"], {"name": "【兎田ぺこら】歌ってみた.mp4", "size": 3000})   # パスは画面に出さない
        self.assertEqual(v["source"]["fileName"], "【兎田ぺこら】歌ってみた.mp4")
        f = self.api.form()
        self.assertFalse(f["useWeights"])   # 動画ファイルの送りでは重みを覚えない

    def test_send_file_needs_known_id_and_retry_reuses_copy(self):
        with self.assertRaises(A.FormError) as cm:
            self.api.send({"source": "files", "files": [{"fileId": "nope"}], "videoTracks": 1})
        self.assertIn("選び直して", str(cm.exception))
        fid = self.api.remember_file(self.src)["id"]
        self.eng.queue.submit = lambda env, spec=None: (_ for _ in ()).throw(ValueError("待ちが多すぎます"))
        row = self.api.send({"source": "files", "files": [{"fileId": fid}], "videoTracks": 1})["rows"][0]
        r = self.wait_copy(row["id"])
        self.assertEqual((r["state"], r["error"]), ("failed", "待ちが多すぎます"))
        copy = r["form"]["file"]["copy"]   # 写しは行が覚えている(一時保管の依頼のフォルダ)
        self.eng.queue.submit = lambda env, spec=None: self.submitted.append((env, spec)) or {"id": env["id"]}
        os.remove(self.src)   # 元の動画を動かしても、写しがあれば [もう一度送る] で送れる
        self.api.retry(row["id"])
        r = self.wait_copy(row["id"])
        self.assertEqual((r["state"], self.submitted[-1][0]["input"]["path"]), ("sent", copy))
        os.remove(copy)   # 写しも元も無い = 理由つきの失敗
        self.box.fail(row["id"], "x")
        self.api.retry(row["id"])
        r = self.wait_copy(row["id"])
        self.assertEqual(r["state"], "failed")
        self.assertIn("見つかりません", r["error"])

    def test_cancel_file_row_while_copying_removes_row(self):
        """動画を写している途中(② に積む前)で取り消す: 行を消す。写し終えた糸が行を見失っても何も積まない"""
        fid = self.api.remember_file(self.src)["id"]
        with mock.patch.object(self.api, "_start_copy"):   # 写す糸は起こさない(途中の形を作る)
            row = self.api.send({"source": "files", "files": [{"fileId": fid}], "videoTracks": 1})["rows"][0]
        self.assertEqual((row["state"], row["runId"]), ("sent", None))
        self.assertEqual(self.api.cancel(row["id"]), {"id": row["id"], "state": "cancelled"})
        self.assertIsNone(self.box.row(row["id"]))
        self.api._copy_and_submit(row["id"])   # 遅れて動き出した写す糸
        self.assertEqual(self.submitted, [])

    def test_copy_stops_when_closing(self):
        fid = self.api.remember_file(self.src)["id"]
        self.api.stopping = lambda: True
        row = self.api.send({"source": "files", "files": [{"fileId": fid}], "videoTracks": 1})["rows"][0]
        r = self.wait_copy(row["id"])
        self.assertEqual(r["state"], "failed")
        self.assertEqual(self.submitted, [])
        self.assertFalse([n for _d, _s, fs in os.walk(self.places["cases"]) for n in fs], "書きかけの写しを残さない")

    def test_reconcile_fails_row_without_run(self):
        self.box.add("20261016-100000-ffffff", {"kind": "file"}, {}, kind="file")
        q = types.SimpleNamespace(set_finished_hook=lambda fn: None, status=lambda: {"idle": True, "runs": []}, history=lambda n: {"runs": []}, close=lambda: None)
        eng = E.Engine({"data": self.tmp, "friend": self.places["friend"], "studio": None}, self.box, queue_factory=lambda *a, **k: q)
        self.addCleanup(eng.close)
        r = self.box.row("20261016-100000-ffffff")
        self.assertEqual(r["state"], "failed")
        self.assertIn("途中で止まりました", r["error"])


class AppTest(unittest.TestCase):
    def test_recording_count_from_live(self):
        tmp = tempfile.mkdtemp(prefix="friend-app-live-")
        self.addCleanup(shutil.rmtree, tmp, True)
        places = {"home": tmp, "data": tmp, "friend": os.path.join(tmp, "friend"), "outbox": os.path.join(tmp, "outbox"), "cases": tmp,
                  "save": lambda: os.path.join(tmp, "save")}
        os.makedirs(places["friend"])
        app = SV.FriendApp(places)
        self.assertEqual(app.recording_count(), 0)
        app.engine = types.SimpleNamespace(live=types.SimpleNamespace(active_count=lambda: 2))
        self.assertEqual(app.recording_count(), 2)
        self.assertIsNone(SV.pick_file_dialog(env={"YTT_DATA_DIR": "inplace"}), "テストの作業データでは本物の窓を開かない")


if __name__ == "__main__":
    unittest.main()
