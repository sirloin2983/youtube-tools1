"""送る欄の動画ファイル・ライブのテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_live.py

- ライブの設定の検査(長さ 10〜180 = A-5b の仮)と、依頼と録画の結びつき(② flow/live_rules.RequestBook を友人の PC の形 deliver=False で)
- ② のライブ係 FriendLive: 送る → ② の待ち行列(本物の flow/runqueue.Queue)の live の hook → 録画を始めて結びつける(長さは送った欄から)→
  切り抜きごとの実行が終わるたびに行にパック(1 本ずつの枠)→ 録画が終わったら行は「届いた」。録画中でも枠に入った物は決められる
- 終了: 録画中でも、この玄関が起こした録画の部品は止める・止めた本数(起動役の状態の窓)・配信後の追加の解析をスタジオなしの台帳へ・終わった録画を 3 日で消す
- 動画ファイル: 選んだ動画を id で覚える(パスは画面に出さない)→ 一時保管の 依頼/ へ写してから ② へ(元の動画は読むだけ)
録画の部品・streamlink・yt-dlp・本物のネットは使わない(録画元は偽物・配信中かは偽物)。
"""
import json
import os
import re
import sys
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import live_export as LX, live_rules, runqueue as Q  # noqa: E402
from friendapp import api as A, diag as D, engine as E, inbox as I, live as L, live_session as LS, progress as P, server as SV  # noqa: E402

VID = "abcdefghijk"
URL = "https://www.youtube.com/watch?v=" + VID
REC = "20261016-200000-" + VID
T0 = 1790000000.0
SETTINGS = {"sens": "low", "perHour": 8, "length": 150, "waitMin": 10, "pad": 5, "afterStream": False}


class FakeRecorder:
    """録画元の代わり(FriendLive.call に差し替える)。録画を始めると REC が録画中になる"""

    def __init__(self):
        self.recs, self.calls, self.quit_code, self.gone, self.kept = {}, [], 200, False, []

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
        m = re.match(r"^/live/([^/?]+)/(stop|delete|keep|status)", path)
        if m and m.group(1) in self.recs:
            if m.group(2) == "stop":
                self.end(m.group(1))
            elif m.group(2) == "delete":
                self.recs.pop(m.group(1))
                return 200, {"ok": True, "deleted": True}
            elif m.group(2) == "keep":   # 非公開の録画を 1 本につないで残す(つなぎ終えたら一覧から消える = ここではすぐ)
                self.kept.append((self.recs.pop(m.group(1))["id"], body["name"]))
                return 200, {"ok": True, "started": True}
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
        tmp = testkit.tempdir(self, "friend-livebook-")
        now = [T0]
        book = live_rules.RequestBook(os.path.join(tmp, "requests.json"), clock=lambda: now[0], deliver=False)
        item = book.put("local", REC, {"rid": "20261016-120000-abcdef", "deliverDir": "C:/x", "settings": SETTINGS, "videoTracks": 2})
        self.assertEqual((item["deliverDir"], item["settings"]["length"], item["videoTracks"]), ("", 150, 2))   # 友人の PC は届けない
        book2 = live_rules.RequestBook(os.path.join(tmp, "requests.json"))
        self.assertEqual(book2.get("local", REC)["settings"]["length"], 150)
        self.assertEqual(list(book2.all()), ["local/" + REC])
        now[0] += 4 * 86400
        self.assertEqual(book.prune(), 1)
        self.assertIsNone(book.get("local", REC))


class LiveFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "friend-live-")
        self.places = {"data": os.path.join(self.tmp, "data"), "friend": os.path.join(self.tmp, "data", "app", "friendapp"),
                       "cases": os.path.join(self.tmp, "作業"), "studio": None, "save": lambda: os.path.join(self.tmp, "save")}
        os.makedirs(self.places["friend"])
        os.makedirs(self.places["cases"])
        self.box = I.Inbox(os.path.join(self.places["friend"], "inbox.json"), os.path.join(self.tmp, "outbox"), self.places["save"],
                           lambda: self.places["cases"])
        for p in (mock.patch.object(E._preview, "pack_seconds", lambda d: 30.0), mock.patch.object(E._preview, "clip_preview", lambda d, log=None: None),
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
        """ライブを送る -> 行。送る欄の 2 つ(perHour・配信後の追加)は body・感度と待ちと余白は ⚙ の値(C-2-11)。長さはいつも自動(10-23)"""
        self.api.set_prefs({"liveSens": SETTINGS["sens"], "liveWait": SETTINGS["waitMin"], "livePad": SETTINGS["pad"]})
        live = {"perHour": SETTINGS["perHour"], "afterStream": SETTINGS["afterStream"]}
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
        item = self.eng.live.requests.get("local", REC)   # 結びつき = 受信箱の行の id・長さは自動(束の analyze に入れない)
        self.assertEqual((item["rid"], item["settings"]["lengthMode"], item["settings"]["sens"], item["settings"]["afterStream"], item["deliverDir"]),
                         (row["id"], "auto", "low", False, ""))
        b = self.eng.live.bundle("local", REC)
        self.assertEqual((b["adopt"]["perHour"], b["adopt"]["waitMin"], b["pack"]["videoTracks"]), (8, 10, 2))
        self.assertEqual(self.api.form()["live"], dict(SETTINGS, length=45, pad=5.0, lengthMode="auto"))   # 前回の値(A-5)
        self.assertEqual(self.eng.live.active_count(), 1)

    def worker_req(self):
        """検出のワーカーが読む依頼の設定(config.json の requests を ① の clean_requests で読んだ形)と、その録画の spec"""
        from pipeline.analyze import live_excite_worker as W
        self.eng.live.detector.write_config()
        with open(os.path.join(self.eng.live.detector.dir, "config.json"), encoding="utf-8") as f:
            req = W.clean_requests(json.load(f)["requests"])["local/" + REC]
        spec = W.request_spec(dict(W.SPEC_DEFAULT, lengthFrom="studio"), req)
        return req, spec, W.shape_of(spec)

    def test_length_always_auto_is_scene(self):
        """10-23: 長さはいつも自動 = 場面ごとの形・場面が取れないときは 150 秒(目安が無いとき。ワーカーの読み方まで)。古い画面の固定と秒は読まない"""
        row = self.send_live(live={"lengthMode": "fixed", "length": 9999})
        self.assertEqual(row["form"]["live"]["lengthMode"], "auto")
        item = self.eng.live.requests.get("local", REC)
        self.assertEqual(item["settings"]["lengthMode"], "auto")
        req, spec, shape = self.worker_req()
        self.assertEqual((req["lengthMode"], shape, spec["lengthFrom"], spec["length"]), ("auto", "scene", "friendScene", 150.0))
        self.assertIn("長さ 自動(場面ごと)", L.settings_label(item["settings"]))

    def test_old_fixed_request_stays_fixed(self):
        """lengthMode の無い前の形の依頼(ユーザーの PC に古い友人のアプリから来る物)は固定のまま"""
        old = L.clean_settings({"sens": "high", "perHour": 3, "length": 30})   # lengthMode の無い前の形の依頼
        self.assertNotIn("lengthMode", old)
        self.assertEqual(L.clean_settings(dict(old, lengthMode="weird")), old)

    def test_update_live_while_recording(self):
        """C-2-11: 録画中に 1 時間の枠・配信後の追加を変える → ② の結びつき(ワーカーの config.json まで)と行の form.live が変わる。
        長さはいつも自動(古い画面が固定を送っても読まない。10-23)"""
        rid = self.send_live(live={"afterStream": False})["id"]
        row = self.api.update_live(rid, {"id": rid, "perHour": 3, "lengthMode": "fixed", "length": 90, "afterStream": True})
        self.assertEqual(row["form"]["live"], {"sens": "low", "perHour": 3, "length": 45, "waitMin": 10, "pad": 5.0, "afterStream": True, "lengthMode": "auto"})
        self.assertEqual(self.box.row(rid)["form"]["live"]["lengthMode"], "auto")
        s = self.eng.live.requests.get("local", REC)["settings"]
        self.assertEqual((s["perHour"], s["afterStream"], s["lengthMode"], s["sens"]), (3, True, "auto", "low"))
        req, _spec, shape = self.worker_req()
        self.assertEqual((req["perHour"], req["lengthMode"], shape), (3, "auto", "scene"))
        self.assertTrue(self.eng.live.archiver._request_after("local", REC))   # 配信後の追加は配信が終わったときに今の値を読む
        with self.assertRaises(A.FormError) as cm:   # 値ごとの検査は SettingsTest.test_check_settings
            self.api.update_live(rid, {"perHour": 0})
        self.assertIn("1 時間の枠", str(cm.exception))
        self.assertEqual(self.eng.live.requests.get("local", REC)["settings"]["perHour"], 3)   # 断った値は入らない

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
        """録画が終わっても作る物・配信後の追加の待ちがあれば行は閉じない。そのとき途中の診断(kind live・stage ended)を 1 回、閉じたら close"""
        box = self.use_diag()
        rid = self.send_live(live={"afterStream": True})["id"]
        self.rec.end(REC)
        with mock.patch.object(self.eng.live, "busy_recording", lambda rc, rec: True):
            self.eng.live_tick()
        self.assertEqual((self.box.row(rid)["state"], self.box.row(rid)["live"]["phase"]), ("recording", "making"))
        self.assertEqual([(d["stage"], d["requestId"]) for d in self.diags(box)], [("ended", rid)])
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
        self.assertEqual([d["stage"] for d in self.diags(box)], ["ended", "close"])   # 途中の診断は 1 回だけ

    def use_diag(self):
        """本物の診断の係(送り返しの箱は一時フォルダ)-> 箱のパス"""
        box = os.path.join(self.tmp, "outbox-diag")
        self.eng.diag = D.Diag(dict(self.places, outbox=box, home=self.tmp), env={})
        return box

    def diags(self, box, kind="live"):
        out = []
        for n in sorted(os.listdir(box)) if os.path.isdir(box) else []:
            with open(os.path.join(box, n), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("kind") == kind:
                out.append(d)
        return out

    def write_peaks(self, **doc):
        det = self.eng.live.detector
        os.makedirs(det.folder("local", REC), exist_ok=True)
        with open(os.path.join(det.folder("local", REC), "peaks.json"), "w", encoding="utf-8") as f:
            json.dump(dict({"v": 1, "recorder": "local", "recording": REC, "seq": 1, "decN": 0, "peaks": [], "changes": []}, **doc), f)

    def test_blocked_recording_warns_row_and_diag_once(self):
        """録画元が YouTube に断られ続けて 3 分(blockedAt)= 友人の行に知らせ・診断 kind live stage blocked を 1 回。録れ始めたら消す"""
        box = self.use_diag()
        rid = self.send_live()["id"]
        self.rec.recs[REC]["blockedAt"] = int((time.time() - 60) * 1000)
        self.eng.live_tick()
        self.assertNotIn("warn", self.box.row(rid)["live"])   # まだ 1 分
        self.rec.recs[REC]["blockedAt"] = int((time.time() - E.BLOCKED_NOTICE - 5) * 1000)
        self.eng.live_tick()
        self.eng.live_tick()
        self.assertEqual(self.box.row(rid)["live"]["warn"], E.BLOCKED_WARN)
        self.assertEqual(next(v for v in self.box.view() if v["id"] == rid)["live"]["warn"], E.BLOCKED_WARN)   # 画面へ渡す行にも載る
        got = [d for d in self.diags(box) if d.get("stage") == "blocked"]
        self.assertEqual((len(got), got[0]["requestId"]), (1, rid))
        self.rec.recs[REC]["blockedAt"] = None
        self.eng.live_tick()
        self.assertNotIn("warn", self.box.row(rid)["live"])

    def test_recorder_not_answering_warns_row_and_diag_once(self):
        """録画元が答えない(一覧が None。10-23 の見回り: 行が録画中のまま何も出なかった)= 3 分で行に知らせ・診断 kind live stage lost を 1 回。
        行は閉じない(分からないので)。答えたら知らせは消える"""
        box = self.use_diag()
        rid = self.send_live()["id"]
        real = self.eng.live.recordings
        self.eng.live.recordings = lambda rc: None
        t = [time.time()]
        with mock.patch.object(E.time, "time", lambda: t[0]):
            self.eng.live_tick()
            self.assertNotIn("warn", self.box.row(rid)["live"])   # まだ
            t[0] += E.LOST_NOTICE + 5
            self.eng.live_tick()
            self.eng.live_tick()
        self.assertEqual(self.box.row(rid)["state"], "recording")
        self.assertEqual(self.box.row(rid)["live"]["warn"], E.LOST_WARN)
        got = [d for d in self.diags(box) if d.get("stage") == "lost"]
        self.assertEqual((len(got), got[0]["requestId"]), (1, rid))
        self.eng.live.recordings = real
        self.eng.live_tick()
        self.assertNotIn("warn", self.box.row(rid)["live"])

    def test_recording_row_shows_waiting_candidates(self):
        """録画中の行: 自動の採用を待っている候補があれば「候補 N 件・約 M 分後に切り抜きます」(live.hint)。無くなれば消す"""
        rid = self.send_live()["id"]
        det = self.eng.live.detector
        det.enabled = lambda: True
        now = time.time()
        for got, want in ((None, None), ({"count": 2, "dueAt": None}, "候補 2 件"),
                          ({"count": 2, "dueAt": now + 250}, "候補 2 件・約 4 分後に切り抜きます"),
                          ({"count": 1, "dueAt": now + 10}, "候補 1 件・まもなく切り抜きます"),
                          ({"capped": 3}, "自動で切り抜くのは 3 本まで(届きました)"), (None, None)):
            det.adopt_waiting = lambda _rc, _rec, g=got: g
            self.eng.live_tick()
            self.assertEqual(self.box.row(rid)["live"].get("hint"), want)
            shown = next(v for v in self.box.view() if v["id"] == rid)["live"]   # 画面へ渡す行にも載る(sent.js の 1 行)
            self.assertEqual(shown.get("hint"), want)

    def test_close_without_packs_writes_cause_and_diag_then_late_pack_revives(self):
        """パックが無いまま閉じた行: 理由は原因ごと(検出の記録が無い = 検出が動かない)・診断 kind live(録画の長さ・検出・ワーカー)・
        閉じたあとに届いたパックで「届いた」に戻る"""
        box = self.use_diag()
        rid = self.send_live()["id"]
        self.rec.end(REC)
        self.eng.live_tick()
        r = self.box.row(rid)
        self.assertEqual((r["state"], r["live"]["cause"]), ("failed", "liveNoDetect"))
        self.assertTrue(r["error"].startswith(P.LIVE_MARKS["liveNoDetect"]), r["error"])
        fail = next(x for x in self.api.view()["rows"] if x["id"] == rid)["fail"]
        self.assertEqual((fail["code"], fail["retrying"]), ("liveNoDetect", False))
        got = self.diags(box)
        self.assertEqual(len(got), 1)
        d = got[0]
        self.assertEqual((d["requestId"], d["code"], d["stage"], d["outcome"]["state"], d["outcome"]["packs"], d["outcome"]["cause"]),
                         (rid, "liveNoDetect", "close", "failed", 0, "liveNoDetect"))
        lv = d["live"]
        self.assertEqual((lv["peaksDoc"], lv["worker"]["running"], lv["recording"]["sec"], lv["settings"]["perHour"]), (None, False, 3600.0, 8))
        self.assertNotIn(URL, json.dumps(d, ensure_ascii=False))   # 配信の URL・題は入れない
        self.assertNotIn("配信の題", json.dumps(d, ensure_ascii=False))
        self.eng.live_tick()   # 閉じた行は見回らない = 診断は 1 回
        self.assertEqual(len(self.diags(box)), 1)
        self.eng.after_run(fake_run("late", "done", self.packs(1), rid))   # 閉じたあとに採用された切り抜きが届いた
        r = self.box.row(rid)
        self.assertEqual((r["state"], r["error"], len(r["groups"])), ("arrived", "", 1))

    def test_detect_hold_keeps_row_until_adoption_settles(self):
        """録画が終わっても、検出が帳簿を締める前・締めたあと採用待ちの候補がある間は閉じない(ワーカーが動いているときだけ・上限つき)。
        自動の採用を諦めたら閉じて、理由は「採用の失敗」"""
        box = self.use_diag()
        rid = self.send_live()["id"]
        det = self.eng.live.detector
        self.write_peaks(ended=False, measuredSec=1500, chat="ok")
        self.rec.end(REC)
        with mock.patch.object(det, "running", lambda hb=None: True), mock.patch.object(self.eng.live, "after_hold", lambda rc, raw: ""):   # 測り直し(EV-1)は待たない
            self.eng.live_tick()
            self.assertEqual((self.box.row(rid)["state"], self.box.row(rid)["live"]["phase"]), ("recording", "after"))
            pk = {"id": "p0-100", "start": 60.0, "end": 105.0, "peak": 100, "score": 2.5, "state": "frame", "endPending": False, "confirmedAt": 110, "hour": 0}
            self.write_peaks(ended=True, measuredSec=1800, chat="ok", peaks=[pk])
            self.eng.live_tick()   # 締めたが採用待ちの候補がある
            self.assertEqual(self.box.row(rid)["state"], "recording")
            self.assertIn("自動の採用を待っています", self.eng.live.detect_hold("local", self.rec.recs[REC]))
            det._give_up("local", REC, pk, "スタジオにつながりません")
            self.eng.live_tick()
        r = self.box.row(rid)
        self.assertEqual((r["state"], r["live"]["cause"]), ("failed", "liveAdopt"))
        self.assertIn("スタジオにつながりません", r["error"])
        d = self.diags(box)[-1]
        self.assertEqual((d["live"]["givenUp"][0]["message"], d["live"]["peaksDoc"]["peaks"], d["live"]["peaksDoc"]["chat"]),
                         ("スタジオにつながりません", 1, "ok"))

    def test_detect_hold_has_a_limit_and_no_chat_cause(self):
        rid = self.send_live()["id"]
        det = self.eng.live.detector
        self.write_peaks(ended=False, measuredSec=1800, chat="none", message="この配信はチャットを取れません")
        self.rec.end(REC, ago=SETTINGS["waitMin"] * 60 + LS.DETECT_HOLD_EXTRA + 60)   # 待ちの上限を過ぎた = 締めていなくても閉じる
        with mock.patch.object(det, "running", lambda hb=None: True), mock.patch.object(self.eng.live, "after_hold", lambda rc, raw: ""):
            self.assertEqual(self.eng.live.detect_hold("local", self.rec.recs[REC]), "")
            self.eng.live_tick()
        r = self.box.row(rid)
        self.assertEqual((r["state"], r["live"]["cause"]), ("failed", "liveNoChat"))
        self.assertIn("チャットを取れません", r["error"])
        self.assertEqual(self.api.classify(r)["message"], P.LIVE_MESSAGES["liveNoChat"])

    def test_live_cause_order(self):
        base = {"recording": {"sec": 1800.0}, "peaksDoc": {"measuredSec": 1800, "chat": "ok"}, "detect": {"frame": 0, "bench": 0, "adopted": 0}}
        cases = [({}, "boom", "error"), (dict(base, exportFailures=["01.mp4: 書き出しに失敗しました: x"]), "", "liveExport"),
                 (dict(base, givenUp=[{"message": "502"}]), "", "liveAdopt"), (dict(base, peaksDoc=None), "", "liveNoDetect"),
                 (dict(base, peaksDoc={"measuredSec": 0}), "", "liveNoDetect"), (dict(base, detect={"frame": 2}), "", "liveLate"),
                 (dict(base, peaksDoc={"measuredSec": 1800, "chat": "restarting"}), "", "liveNoChat"), (base, "", "liveNone"),
                 (dict(base, peaksDoc=None, recording={"sec": 600.0, "blocked": True}), "", "liveBlocked")]   # bot で止めた = 「検出が動かない」にしない
        for facts, err, code in cases:
            with self.subTest(code=code):
                got = E.live_cause(facts, err)
                self.assertEqual(got["code"], code)
                if code.startswith("live"):
                    self.assertEqual(P.classify(got["text"], "live")["code"], code)
        tail = E.live_cause(dict(base, afterStream={"state": "none", "message": "採用する候補がありませんでした"}))
        self.assertTrue(tail["text"].endswith("(配信後の追加: 採用する候補がありませんでした)"), tail["text"])
        self.assertEqual(E.live_cause(None)["code"], "liveNoDetect")

    def test_cancel_while_recording_writes_diag(self):
        """録画中に [取り消す](パック 0 本 = 行は消える): 消える前に診断 kind live(理由 cancelled・材料つき)"""
        box = self.use_diag()
        rid = self.send_live()["id"]
        self.api.cancel(rid)
        self.assertIsNone(self.box.row(rid))
        d = self.diags(box)
        self.assertEqual((len(d), d[0]["requestId"], d[0]["stage"], d[0]["outcome"]["packs"]), (1, rid, "close", 0))
        self.assertIn("[取り消す]", d[0]["summary"])
        self.assertIn("settings", d[0]["live"])

    def test_live_submit_failure_writes_diag(self):
        box = self.use_diag()
        self.eng.live.probe = lambda url: {"status": "was_live", "title": "", "channel": "", "message": ""}
        with self.assertRaises(A.FormError):
            self.send_live()
        d = self.diags(box)
        self.assertEqual((len(d), d[0]["stage"], d[0]["outcome"]["state"]), (1, "submit", "refused"))
        self.assertIn("配信中・配信前", d[0]["summary"])

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

    def test_clean_recordings_by_archive(self):
        """ユーザーの PC と同じ決まり(10-24): アーカイブ化を確かめた録画は消す・非公開と分かったら 1 本につないで名前に「非公開」・
        確かめられないまま 24 時間たった録画も同じ・それより前は待つ"""
        self.send_live()
        arch, priv, unk, late = "20261010-100000-arch", "20261010-110000-priv", "20261010-120000-unk", "20261010-130000-late"
        for rid, days in ((arch, 0.5), (priv, 0.1), (unk, 0.5), (late, 1.5)):
            self.rec.recs[rid] = {"id": rid, "url": URL, "state": "ended", "active": False, "title": "雑談", "endedAt": LX.epoch_iso(time.time() - days * 86400)}
        self.rec.end(REC, ago=3600)
        lv = self.eng.live
        lv.archiver.archived = lambda rc, r: "" if r["id"] == arch else "アーカイブ化をまだ確かめられていない(処理中)"
        lv.archiver.unavailable = lambda rc, r: "private" if r["id"] == priv else ""
        self.assertEqual(sorted(lv.clean_recordings(force=True)), sorted([arch, priv, late]))
        self.assertEqual(sorted(self.rec.recs), sorted([REC, unk]))
        self.assertEqual(sorted((r, n.endswith("_雑談_非公開")) for r, n in self.rec.kept), [(priv, True), (late, True)])

    def test_live_cfg_and_rec_folder(self):
        c = self.eng.live.cfg()
        self.assertEqual((c["enabled"], c["folder"]), (True, os.path.join(self.places["cases"], L.REC_FOLDER)))
        self.assertNotIn("autoArchive", c)   # 本番版への入れ替え(P4)の設定は 10-16 に無くした(残りかすを 10-24 に外した)
        self.assertTrue(self.eng.live.request_all)


class FileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "friend-file-")
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
        tmp = testkit.tempdir(self, "friend-app-live-")
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
