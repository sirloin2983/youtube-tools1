# -*- coding: utf-8 -*-
"""flow/livesession(ライブ係。役割で組み直す RS7-2 G2b)のテスト。  py -3.10 -m unittest src/flow/tests/test_livesession.py -v

- 入口の Live を使わず、偽の録画元・偽の まとめて実行で: ② の口(Queue.submit の kind live)→ submit → 録画を始める → live/bundles.json →
  束から検出の設定(config.json の bundles)・自動の採用の待ち・配信後の解析の設定・書き出したあとの設定
- 画面なしの形(どの封筒も依頼の決まり・D-13 なし・上限は束の adopt.top): 採用(LocalMarks)→ 書き出しのジョブ → まとめて実行へ
  封筒 kind file + 録画の束(submit。欄は以前の start_file と同じ実行)・書き出しの音量は束から
- 空き容量の下限(disk_min_gb)を下回ったら録画を始めない
- 起動し直し: 新しい LiveSession が bundles.json から束を戻す(形の違う行は束なし)・古い束は片付ける
- 入口の Live(app)の use_headless と、友人の依頼(intake の live_begin = submit_request)が封筒 + 束で submit を通る(requests.json は今の形のまま)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import re
import shutil
import sys
import tempfile
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "home"))   # 入口の Live(app)と設定(prefs)
from flow import live_adopt as LA, live_detect as D, live_export as LX, livesession as LS, run as R, runqueue as Q, spec as S  # noqa: E402
from pipeline.analyze import live_excite_worker as W  # noqa: E402
from ytt import fsio  # noqa: E402

VID = "abcdefghijk"
URL = "https://www.youtube.com/watch?v=" + VID
REC = "20261011-200000-" + VID
T0 = 1790000000.0
GB = LX.GB


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class FakeRecorder:
    """録画元の代わり(LiveSession.call に差し替える)。録画を始めると REC が録画中になる(1 時間録れている)"""

    def __init__(self):
        self.recs, self.calls, self.free = {}, [], 500 * GB

    def __call__(self, rc, method, path, body=None, timeout=3.0):
        self.calls.append((method, path))
        if method == "GET" and path == "/live/list":
            return 200, {"recordings": [dict(r) for r in self.recs.values()], "freeBytes": self.free, "active": len(self.recs)}
        if method == "POST" and path == "/live/start":
            r = {"id": REC, "url": body["url"], "title": body["title"], "state": "recording", "active": True,
                 "firstPdt": LX.epoch_iso(T0), "lastPdt": LX.epoch_iso(T0 + 3600)}
            self.recs[REC] = r
            return 200, {"recording": dict(r)}
        m = re.match(r"^/live/([^/?]+)/status", path)
        if method == "GET" and m and m.group(1) in self.recs:
            return 200, dict(self.recs[m.group(1)])
        return 404, {"message": "ありません"}

    def started(self):
        return [c for c in self.calls if c == ("POST", "/live/start")]


class FakeQueue:
    """まとめて実行の口の代わり(書き出した切り抜きの submit を覚える)"""

    def __init__(self):
        self.got = []

    def submit(self, env, spec=None, accept=False):
        self.got.append((env, spec, accept))
        return {"id": env["id"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-livesession-")
        self.cfg = {"enabled": True, "detect": {"enabled": True, "sens": "low", "perHour": 4}, "autoAdopt": {"enabled": True, "waitMin": 9}}
        self.logs = []
        self.queue = FakeQueue()
        self.rec = FakeRecorder()
        self.s = self.session()

    def session(self):
        s = LS.LiveSession(self.tmp, os.path.join(self.tmp, "logs"), cfg=lambda: self.cfg, log=self.logs.append, spawn=False,
                           store_dir=os.path.join(self.tmp, "live"), out_dir=lambda: os.path.join(self.tmp, "out"), runner=lambda: self.queue)
        s.call = self.rec
        s.probe = lambda url: {"status": "is_live", "title": "配信の題", "channel": "Ch", "message": ""}
        s.exporter.start = lambda: None   # 書き出しは動かさない(済んだ所はテストが _handoff を呼ぶ)
        return s

    def tearDown(self):
        self.s.detector.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def bundles_path(self):
        return os.path.join(self.tmp, "live", LS.BUNDLES_FILE)


class SubmitTest(Base):
    SPEC = {"analyze": {"length": 30, "wChat": 2.0, "preRatio": 0.5}, "adopt": {"sens": "high", "perHour": 12, "waitMin": 3, "top": 4},
            "export": {"loudness": None, "volume": 120}}

    def test_queue_hook_to_bundle_and_detect(self):
        """② の口(Queue.submit の kind live)→ 録画を始めて live/bundles.json に封筒 + 束 → 検出・採用の待ち・配信後の解析の設定は束から"""
        q = Q.Queue(None, poll=0.01, tools=object())
        q.set_live_hook(self.s.submit)
        out = q.submit({"id": "live000001", "kind": "live", "input": {"url": URL, "title": "配信"}}, self.SPEC)
        self.assertEqual(out, {"id": "live000001", "live": True, "recorder": "local", "recording": REC, "existing": False, "title": "配信の題"})
        self.assertEqual(len(self.rec.started()), 1)
        d = load(self.bundles_path)
        self.assertEqual(list(d), ["local/" + REC])
        item = d["local/" + REC]
        self.assertEqual((item["envelope"]["id"], item["envelope"]["kind"], item["spec"]["adopt"]["sens"], item["spec"]["export"]["volume"]),
                         ("live000001", "live", "high", 120))
        self.assertIsInstance(item["at"], float)
        self.assertEqual(self.s.requests.all(), {}, "requestId の無い封筒は依頼の結びつきを作らない(ユーザーの PC)")
        # 検出: config.json の bundles(ワーカーが新しく受け持つときの spec・感度・枠)。束の無い録画は今までどおり(spec・detect)
        self.s.detector.write_config()
        c = load(os.path.join(self.s.detector.dir, "config.json"))
        b = c["bundles"]["local/" + REC]
        self.assertEqual((b["sens"], b["perHour"], b["spec"]["length"], b["spec"]["wChat"], b["spec"]["preRatio"]), ("high", 12, 30.0, 2.0, 0.5))
        self.assertEqual(c["detect"], {"sens": "low", "perHour": 4})
        self.assertEqual(W.clean_bundles(c["bundles"])["local/" + REC]["spec"]["length"], 30.0)   # ワーカーが読む形
        self.assertEqual((self.s.detector.adopt_for(None, "local", REC), self.s.detector.adopt_for(None, "local", "20261011-210000-x")),
                         ({"enabled": True, "waitMin": 3}, {"enabled": True, "waitMin": 9}))
        # 配信後の全自動の解析の設定・書き出しの音量・書き出したあとの設定
        self.assertEqual(self.s.archiver.settings_for("local", REC)["length"], 30)
        self.assertIsNone(self.s.archiver.settings_for("local", "20261011-210000-x"))
        self.assertEqual(self.s.exporter._audio_cfg({"recorder": "local", "recording": REC}), (120, None))
        self.assertEqual(self.s.auto_cfg("local", REC), {"after": "check", "cut": "", "engine": "", "model": "", "pad": 2.0})
        # 同じ配信をもう一度: 録画中のものを返し、束は始めたときのまま
        out2 = self.s.submit({"id": "live000002", "kind": "live", "input": {"videoId": VID}}, {"adopt": {"sens": "low"}})
        self.assertEqual((out2["existing"], len(self.rec.started()), self.s.bundle("local", REC)["adopt"]["sens"]), (True, 1, "high"))

    def test_not_live_and_bad(self):
        self.s.probe = lambda url: {"status": "was_live", "title": "", "channel": "", "message": ""}
        self.assertEqual(self.s.submit({"id": "live000003", "kind": "live", "input": {"videoId": VID}}, None),
                         {"id": "live000003", "live": False, "status": "was_live"})
        self.assertFalse(os.path.isfile(self.bundles_path))
        for env in ({"id": "f1", "kind": "file", "input": {"path": "C:/x.mp4"}}, {"id": "l1", "kind": "live", "input": {"recorder": "nope", "videoId": VID}}):
            with self.assertRaises(ValueError):
                self.s.submit(env, None)
        self.cfg["enabled"] = False
        with self.assertRaises(LX.LiveError) as cm:
            self.s.submit({"id": "live000004", "kind": "live", "input": {"videoId": VID}}, None)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(self.rec.started(), [])

    def test_bundle_pins_to_auto_cfg(self):
        """束の run.pinned にあるエンジン・モデル・カット・余白だけが書き出したあとの設定に(録画を始めたときの値。決定 3-31 の仮 b3)"""
        spec = LS.cfg_bundle(None, {"auto": {"engine": "whisper.cpp", "model": "large-v3", "cut": "silence", "pad": 1.5},
                                    "detect": {"sens": "high", "perHour": 7}, "autoAdopt": {"waitMin": 4}})
        self.assertEqual((spec["adopt"]["sens"], spec["adopt"]["perHour"], spec["adopt"]["waitMin"], spec["adopt"]["pad"], sorted(spec["run"]["pinned"])),
                         ("high", 7, 4, 1.5, ["cut", "engine", "model"]))
        self.s.submit({"id": "live000005", "kind": "live", "input": {"videoId": VID}}, spec)
        self.cfg["auto"] = {"engine": "faster-whisper", "model": "small", "cut": "none", "pad": 0.5}   # 録画を始めたあとに変えても効かない
        self.assertEqual(self.s.auto_cfg("local", REC), {"after": "check", "cut": "silence", "engine": "whisper.cpp", "model": "large-v3", "pad": 1.5})
        self.assertEqual(self.s.auto_cfg(), {"after": "check", "cut": "none", "engine": "faster-whisper", "model": "small", "pad": 0.5})   # 束の無い録画


class HeadlessTest(Base):
    """画面なしの形(入口の Live.use_headless と同じ値をライブ係に置く): どの封筒も依頼の決まり・D-13 なし・上限は束の adopt.top"""

    SPEC = {"adopt": {"top": 2, "pad": 1.0, "waitMin": 2, "afterStream": False}, "analyze": {"length": 40},
            "pack": {"cut": "silence", "videoTracks": 3}, "run": {"pinned": ["cut", "videoTracks"]},
            "transcribe": {"diarize": 2}, "hints": {"people": [{"name": "兎田ぺこら", "color": "#FF0000"}]}, "export": {"volume": 90, "loudness": None}}

    def setUp(self):
        super().setUp()
        self.cfg = {"enabled": False}   # 設定はオフでも動く(画面なし = 送るアプリの依頼で動く)
        self.s.always_on = self.s.request_all = True
        self.s.auto_max = self.s.bundle_top

    def test_request_adopt_handoff(self):
        out = self.s.submit({"id": "live000010", "kind": "live", "input": {"videoId": VID, "title": "友人の配信"}, "requestId": "req-1"}, self.SPEC)
        self.assertEqual((out["live"], out["recording"], out["id"]), (True, REC, "live000010"))
        req = self.s.requests.get("local", REC)   # 依頼の結びつき(依頼の決まりで検出・採用・パックまで)
        self.assertEqual((req["rid"], req["deliverDir"], req["cut"], req["videoTracks"], req["streamer"]), ("req-1", "", "silence", 3, ""))
        self.assertEqual(req["settings"], {"sens": "normal", "perHour": 6, "length": 40, "waitMin": 2, "pad": 1.0, "afterStream": False})
        self.assertEqual(req["speakers"], {"count": 2, "names": ["兎田ぺこら"], "styles": {"兎田ぺこら": {"color": "#FF0000"}}})
        # D-13 なし: 未確認で休まない・上限は束の adopt.top
        self.assertEqual((self.s.detector.auto_max("local", REC), self.s.detector.paused_why()), (2, ""))
        self.assertEqual(self.s.detector.auto_max("local", "20261011-210000-x"), D.AUTO_MAX_PER_REC)   # 束の無い録画は今の上限
        # 採用(LocalMarks = スタジオなし)→ 書き出しのジョブ(依頼の録画 = after auto・余白は依頼の 1 秒)
        self.assertIsInstance(self.s.marks, LA.LocalMarks)
        res = self.s.adopt({"recorder": "local", "recording": REC, "start": 100.0, "end": 130.0, "origin": "auto"})
        job = res["job"]
        self.assertEqual((job["after"], job["studio"]["start"], job["studio"]["end"], job["request"]["rid"]), ("auto", 99.0, 131.0, "req-1"))
        self.assertEqual(self.s.exporter.marks.load("local", REC)["marks"][0]["status"], "adopted")
        # 書き出しが済んだ所から: まとめて実行へ 封筒 kind file + 録画の束(以前の start_file と同じ実行)
        media = os.path.join(self.tmp, "out", "友人の配信", "01_00h01m39s-00h02m11s.mp4")
        os.makedirs(os.path.dirname(media))
        open(media, "wb").close()
        job = next(j for j in self.s.exporter.jobs if j["id"] == job["id"])
        run_id, handoff, _warn = self.s.exporter._handoff(job, media, "auto")
        self.assertEqual(handoff, "")
        env, spec, accept = self.queue.got[-1]
        self.assertEqual((run_id, accept, env["kind"], env["input"]["path"], env["requestId"], env["deliver"]["dir"]),
                         (env["id"], True, "file", media, "req-1", None))   # 届け先の無い依頼(友人の PC)= 届ける段は「届け先がありません」で飛ばす
        run = R.Run.from_envelope(env, spec)
        self.assertEqual((run.mode, run.cut, run.video_tracks, run.source_path, run.request_id), ("file_auto", "silence", 3, media, "req-1"))
        self.assertEqual(run.speakers, {"count": 2, "names": ["兎田ぺこら"], "styles": {"兎田ぺこら": {"color": "#FF0000"}}})
        self.assertEqual((spec["export"]["volume"], spec["analyze"]["length"]), (90, 40))   # 束は録画の束
        self.assertEqual(self.s.exporter._audio_cfg(job), (90, None))   # 書き出しの音量も録画の束から
        self.assertEqual(self.s.exporter._studio_exported(job, media), "")   # 正本の採用の印を「書き出し済み」に
        self.assertEqual(self.s.exporter.marks.load("local", REC)["marks"][0]["status"], "exported")

    def test_disk_floor(self):
        """空き容量の下限(machine.json の diskMinGB)を下回ったら新しい録画を始めない(書き出し先・live\\work と録画の置き場所)"""
        self.s.disk_min_gb = 20
        self.s.disk_usage = lambda p: (5 * GB, 100 * GB)
        env = {"id": "live000011", "kind": "live", "input": {"videoId": VID}}
        with self.assertRaises(LX.LiveError) as cm:
            self.s.submit(env, None)
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("空き容量が下限の 20 GB", str(cm.exception))
        self.s.disk_usage = lambda p: (500 * GB, 1000 * GB)
        self.rec.free = 1 * GB   # 録画の置き場所(録画元の GET /live/list の freeBytes)
        with self.assertRaises(LX.LiveError) as cm:
            self.s.submit(env, None)
        self.assertIn("録画の置き場所", str(cm.exception))
        self.assertEqual(self.rec.started(), [])
        self.rec.free = 100 * GB
        self.assertTrue(self.s.submit(env, None)["live"])
        self.assertEqual(len(self.rec.started()), 1)

    def test_restart_restores_bundles(self):
        self.s.submit({"id": "live000012", "kind": "live", "input": {"videoId": VID}}, self.SPEC)
        want = self.s.bundle("local", REC)
        d = load(self.bundles_path)
        d["local/20261011-210000-x"] = {"envelope": None, "spec": {"adopt": {"sens": "どれでもない"}}, "at": 1}   # 形の違う束
        d["../x/y"] = {"envelope": None, "spec": {}, "at": 1}   # 形の違う鍵
        fsio.atomic_write(self.bundles_path, json.dumps(d).encode("utf-8"))
        s2 = self.session()
        try:
            self.assertEqual(s2.bundle("local", REC), want)
            self.assertEqual(s2.bundle_top("local", REC), 2)
            self.assertIsNone(s2.bundle("local", "20261011-210000-x"))
            self.assertEqual(list(s2.bundles.specs()), ["local/" + REC])
            self.assertTrue(any("束 2 件を読めなかった" in m for m in self.logs), self.logs)
            s2.bundles.clock = lambda: time.time() + (LS.BUNDLES_KEEP_DAYS + 1) * 86400
            self.assertEqual(s2.bundles.prune(), 1)
            self.assertEqual(load(self.bundles_path), {})
        finally:
            s2.detector.stop()


class LiveAppTest(unittest.TestCase):
    """入口の Live(app)の画面なしの形と、友人の依頼(intake の live_begin)の経路"""

    def setUp(self):
        import live as LV
        import prefs as P
        self.LV = LV
        self.tmp = tempfile.mkdtemp(prefix="ytt-livesession-app-")
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.live = LV.Live(self.prefs, self.tmp, os.path.join(self.tmp, "logs"), spawn=False, store_dir=os.path.join(self.tmp, "live"),
                            out_dir=lambda: os.path.join(self.tmp, "out"), runner=lambda: None)
        self.rec = FakeRecorder()
        self.live.call = self.rec
        self.live.probe = lambda url: {"status": "is_live", "title": "配信の題", "channel": "Ch", "message": ""}
        self.live.detector.wake = lambda: None   # 本物はワーカーを起こす

    def tearDown(self):
        self.live.detector.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_use_headless(self):
        lv = self.live
        steps = [w for w, _f in lv._watch_steps()]
        self.assertTrue(any("6" in w or "上限" in w for w in steps) and any("届け方" in w for w in steps), steps)   # 画面ありは D-13・届け方の見回りも
        self.assertIsInstance(lv.marks, LA.StudioMarks)
        self.assertFalse(lv.enabled())
        lv.use_headless(20)
        self.assertTrue(lv.enabled())   # 設定はオフのままでも動く
        self.assertIsInstance(lv.marks, LA.LocalMarks)
        self.assertEqual((lv.adopter.deliver_for, lv.unconfirmed, lv._request_limit(), lv.disk_min_gb, lv.request_all), (None, None, None, 20, True))
        self.assertEqual(lv.auto_max, lv.bundle_top)
        steps = [w for w, _f in lv._watch_steps()]
        self.assertFalse(any("上限" in w or "届け方" in w or "見ていない" in w for w in steps), steps)

    def test_friend_request_goes_through_submit(self):
        """友人のライブ配信の依頼(intake の live_begin = Live.submit_request): 封筒 + 束で submit を通る。requests.json は ctx のまま・
        束は自動の採用の上限 10(依頼の欄の既定)・依頼のカット・映像トラック・話す人を run.pinned に"""
        self.prefs.patch("live", {"enabled": True})
        ctx = {"rid": "20261011-200000-abc123", "deliverDir": os.path.join(self.tmp, "出力"), "url": URL, "title": "配信の題", "streamer": "兎田ぺこら",
               "speakers": {"count": 1, "names": ["兎田ぺこら"], "styles": {}}, "videoTracks": 2, "cut": "silence", "memo": "歌のところ",
               "settings": {"sens": "high", "perHour": 12, "length": 60, "waitMin": 3, "pad": 1.5, "afterStream": False}, "deliverBatch": 3}
        out = self.live.submit_request(URL, ctx)
        self.assertEqual(out, {"recorder": "local", "recording": REC, "existing": False})
        item = self.live.requests.get("local", REC)
        self.assertEqual({k: item[k] for k in ("rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut", "memo", "deliverBatch")},
                         {k: ctx[k] for k in ("rid", "deliverDir", "url", "title", "streamer", "speakers", "videoTracks", "cut", "memo", "deliverBatch")})
        self.assertEqual(item["settings"], ctx["settings"])
        b = self.live.bundles.get("local", REC)
        self.assertEqual((b["envelope"]["id"], b["envelope"]["requestId"], b["envelope"]["deliver"]["batch"], b["envelope"]["note"]),
                         (ctx["rid"], ctx["rid"], 3, "歌のところ"))
        sp = b["spec"]
        self.assertEqual((sp["adopt"]["top"], sp["adopt"]["sens"], sp["adopt"]["waitMin"], sp["adopt"]["afterStream"], sp["pack"]["cut"], sp["pack"]["videoTracks"],
                          sp["transcribe"]["diarize"], sp["hints"]["people"], sorted(sp["run"]["pinned"])),
                         (10, "high", 3, False, "silence", 2, 1, [{"name": "兎田ぺこら"}], ["cut", "videoTracks"]))
        self.assertEqual(sp["analyze"]["length"], S.DEFAULTS["analyze"]["length"], "依頼の長さは束の analyze に入れない(検出は requests.json の長さ)")
        self.assertEqual(LS.bundle_ctx(b["envelope"], sp, URL)["settings"], dict(ctx["settings"], length=S.DEFAULTS["analyze"]["length"]))
        # 自分の配信(スタジオの URL の欄)は束なし(今の読み方。6 節の時間の上限で切った)
        self.rec.recs.clear()
        self.assertTrue(self.live.begin(URL)["live"])
        self.assertEqual(self.live.bundle("local", REC)["adopt"]["top"], 10, "begin は録画中の録画の束を変えない")


if __name__ == "__main__":
    unittest.main()
