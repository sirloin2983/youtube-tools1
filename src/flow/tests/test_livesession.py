# -*- coding: utf-8 -*-
"""flow/livesession(ライブ係)のテスト。  py -3.12 -m unittest src/flow/tests/test_livesession.py -v

- 入口の Live を使わず、偽の録画元・偽の まとめて実行で: ② の口(Queue.submit の kind live)→ submit → 録画を始める → live/bundles.json →
  束から検出の設定(config.json の bundles)・自動の採用の待ち・配信後の解析の設定・書き出したあとの設定
- 画面なしの形(どの封筒も依頼の決まり・6 時間の見回りなし・上限は束の adopt.top): 採用(LocalMarks)→ 書き出しのジョブ → まとめて実行へ
  封筒 kind file + 録画の束(submit。動画ファイルの実行と同じ)・書き出しの音量は束から
- 自分の配信(begin_own): 録画を始めたときに束を組み(ホームの設定 + スタジオの解析の設定・書き出しの音量)、録画中に設定を変えても束の値
- 空き容量の下限(disk_min_gb)を下回ったら録画を始めない
- 起動し直し: 新しい LiveSession が bundles.json から束を戻す(形の違う行は束なし)・古い束は片付ける
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import re
import shutil
import sys
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from flow import live_adopt as LA, live_detect as D, live_export as LX, livesession as LS, run as R, runqueue as Q, spec as S  # noqa: E402
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

    def submit(self, env, spec=None):
        self.got.append((env, spec))
        return {"id": env["id"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-livesession-")
        self.cfg = {"enabled": True, "detect": {"enabled": True, "sens": "low", "perHour": 4}, "autoAdopt": {"waitMin": 9}}
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


class ChatRetryWatchTest(Base):
    def test_patrol_calls_runner_chat_retry(self):
        """見回りの 1 つ = まとめて実行の chat_retry_tick(チャットのリプレイが無かった配信の取り直し)。持たない待ち行列なら何もしない"""
        steps = dict(self.s._watch_steps())
        fn = steps["チャットの取り直しの見回りでエラー"]
        self.assertIsNone(fn())   # FakeQueue は持たない
        self.queue.chat_retry_tick = lambda: 2
        self.assertEqual(fn(), 2)


class SubmitTest(Base):
    SPEC ={"analyze": {"length": 30, "wChat": 2.0, "preRatio": 0.5}, "adopt": {"sens": "high", "perHour": 12, "waitMin": 3, "top": 4},
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
        self.assertEqual((self.s.detector.adopt_for(None, "local", REC), self.s.detector.adopt_for(None, "local", "20261011-210000-x")),
                         ({"waitMin": 3}, {"waitMin": 9}))
        # 配信後の全自動の解析の設定・書き出しの音量・書き出したあとの設定
        self.assertEqual(self.s.archiver.settings_for("local", REC)["length"], 30)
        self.assertIsNone(self.s.archiver.settings_for("local", "20261011-210000-x"))
        self.assertEqual(self.s.exporter._audio_cfg({"recorder": "local", "recording": REC}), (120, None))
        self.assertEqual(self.s.auto_cfg("local", REC), {"after": "auto", "cut": "", "engine": "", "model": "", "pad": 2.0})
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
        """束の run.requested にあるエンジン・モデル・カット・余白だけが書き出したあとの設定に(録画を始めたときの値。決定 3-31 の仮 b3)"""
        spec = LS.cfg_bundle(None, {"auto": {"engine": "whisper.cpp", "model": "large-v3", "cut": "silence", "pad": 1.5},
                                    "detect": {"sens": "high", "perHour": 7}, "autoAdopt": {"waitMin": 4}})
        self.assertEqual((spec["adopt"]["sens"], spec["adopt"]["perHour"], spec["adopt"]["waitMin"], spec["adopt"]["pad"], sorted(spec["run"]["requested"])),
                         ("high", 7, 4, 1.5, ["cut", "engine", "model"]))
        self.s.submit({"id": "live000005", "kind": "live", "input": {"videoId": VID}}, spec)
        self.cfg["auto"] = {"engine": "faster-whisper", "model": "small", "cut": "none", "pad": 0.5}   # 録画を始めたあとに変えても効かない
        self.assertEqual(self.s.auto_cfg("local", REC), {"after": "auto", "cut": "silence", "engine": "whisper.cpp", "model": "large-v3", "pad": 1.5})
        self.assertEqual(self.s.auto_cfg(), {"after": "auto", "cut": "none", "engine": "faster-whisper", "model": "small", "pad": 0.5})   # 束の無い録画


class OwnStreamTest(Base):
    """自分の配信(スタジオの URL の欄 → begin_own): 録画を始めたときに束を組み、録画中に設定を変えても束の値を使う(決定 3-31 の b1・b2)"""

    def setUp(self):
        super().setUp()
        self.cfg["auto"] = {"engine": "whisper.cpp", "model": "large-v3", "pad": 1.0}
        self.analyze = {"length": 20, "headSec": 0, "count": 12, "wChat": 2.5, "nope": 1}
        self.audio = {"volume": 100, "loudness": -16.0}   # studio_audio の形(LUFS は小数)
        self.s.studio_call = lambda method, path, body=None: (200, {"settings": {"analyze": dict(self.analyze)}}) if path == "/api/settings" else (None, {})
        self.s.audio = lambda: dict(self.audio)

    def test_bundle_fixed_while_recording(self):
        out = self.s.begin_own("https://youtu.be/%s?t=5" % VID)
        self.assertEqual((out["live"], out["recording"]["id"], out["existing"]), (True, REC, False))
        item = self.s.bundles.get("local", REC)
        self.assertEqual((item["envelope"]["kind"], item["envelope"]["input"]["url"], item["envelope"]["requestId"]), ("live", URL, None))
        sp = item["spec"]
        self.assertEqual((sp["adopt"]["sens"], sp["adopt"]["perHour"], sp["adopt"]["waitMin"], sp["adopt"]["pad"]), ("low", 4, 9, 1.0))
        self.assertEqual((sp["analyze"]["length"], sp["analyze"]["headSec"], sp["analyze"]["count"], sp["analyze"]["wChat"]), (20, 0, 12, 2.5))
        self.assertNotIn("nope", sp["analyze"])
        self.assertEqual(sp["export"], {"volume": 100, "loudness": -16, "margin": 10.0})   # 余白(LD-2f)は束の既定
        self.assertEqual(sorted(sp["run"]["requested"]), ["engine", "model"])
        self.assertEqual(self.s.requests.all(), {}, "自分の配信は依頼の結びつきを作らない")
        # 録画中に設定を変える(ホームの設定・スタジオの解析の設定・書き出しの音量)
        self.cfg.update(detect={"enabled": True, "sens": "high", "perHour": 20}, autoAdopt={"waitMin": 60},
                        auto={"engine": "whisper.cpp", "model": "large-v3", "cut": "silence", "pad": 3.0})
        self.analyze.update(length=90, headSec=300)
        self.audio.update(volume=50, loudness=None)
        other = "20261011-210000-x"   # 束の無い録画は今の値
        self.assertEqual((self.s.detector.adopt_for(None, "local", REC), self.s.detector.adopt_for(None, "local", other)),
                         ({"waitMin": 9}, {"waitMin": 60}))
        b = self.s.detector.bundles_cfg()["local/" + REC]
        self.assertEqual((b["sens"], b["perHour"], b["spec"]["length"], b["spec"]["headSec"]), ("low", 4, 20.0, 0.0))
        self.assertEqual((self.s.archiver.settings_for("local", REC)["length"], self.s.archiver.settings_for("local", REC)["headSec"]), (20, 0))
        self.assertEqual((self.s.exporter._audio_cfg({"recorder": "local", "recording": REC}), self.s.exporter._audio_cfg({"recorder": "local", "recording": other})),
                         ((100, -16), (50, None)))
        self.assertEqual(self.s.auto_cfg("local", REC), {"after": "auto", "cut": "", "engine": "whisper.cpp", "model": "large-v3", "pad": 1.0})
        self.assertEqual(self.s.auto_cfg("local", other)["pad"], 3.0)
        # 同じ配信をもう一度: 録画中のものを返し、束は始めたときのまま
        out2 = self.s.begin_own(URL)
        self.assertEqual((out2["existing"], len(self.rec.started()), self.s.bundle("local", REC)["adopt"]["waitMin"]), (True, 1, 9))

    def test_not_live_and_local(self):
        self.s.probe = lambda url: {"status": "was_live", "title": "", "channel": "", "message": ""}
        self.assertEqual(self.s.begin_own(URL), {"live": False, "status": "was_live"})
        self.assertFalse(os.path.isfile(self.bundles_path))
        with self.assertRaises(LX.LiveError):
            self.s.begin_own("https://example.com/watch?v=" + VID)
        # 封筒にできない URL(テストの手元の録画元)は束なし
        self.s.probe = lambda url: {"status": "is_live", "title": "手元", "channel": "", "message": ""}
        self.s.allow_local_urls = True
        out = self.s.begin_own("http://127.0.0.1:9/live.m3u8")
        self.assertTrue(out["live"])
        self.assertIsNone(self.s.bundle("local", REC))
        self.assertFalse(os.path.isfile(self.bundles_path))

    def test_studio_unreachable(self):
        """スタジオに聞けない(画面なしの芯・スタジオが動いていない)ときは土台の解析の設定のまま"""
        self.s.studio_call = lambda method, path, body=None: (None, {"message": "切り抜きスタジオがありません"})
        self.s.audio = None
        self.s.begin_own(URL)
        sp = self.s.bundle("local", REC)
        self.assertEqual((sp["analyze"], sp["export"]), (S.DEFAULTS["analyze"], S.DEFAULTS["export"]))
        self.assertEqual(LS.now_bundle(None, {"length": 5, "count": True}, {"volume": 0, "loudness": -15}), S.validate(S.merge(None)), "範囲の外は束のまま")


class HeadlessTest(Base):
    """画面なしの形(入口の Live.use_headless と同じ値をライブ係に置く): どの封筒も依頼の決まり・6 時間の見回りなし・上限は束の adopt.top"""

    SPEC = {"adopt": {"top": 2, "pad": 1.0, "waitMin": 2, "afterStream": False}, "analyze": {"length": 40},
            "pack": {"cut": "silence", "videoTracks": 3}, "run": {"pinned": ["cut", "videoTracks"]},
            "transcribe": {"diarize": 2}, "hints": {"people": [{"name": "兎田ぺこら", "color": "#FF0000"}]}, "export": {"volume": 90, "loudness": None}}

    def setUp(self):
        super().setUp()
        self.cfg = {"enabled": False}   # 設定はオフでも動く(画面なし = 友人の依頼で動く)
        self.s.always_on = self.s.request_all = True
        self.s.auto_max = self.s.bundle_top

    def test_request_adopt_handoff(self):
        out = self.s.submit({"id": "live000010", "kind": "live", "input": {"videoId": VID, "title": "友人の配信"}, "requestId": "req-1"}, self.SPEC)
        self.assertEqual((out["live"], out["recording"], out["id"]), (True, REC, "live000010"))
        req = self.s.requests.get("local", REC)   # 依頼の結びつき(依頼の決まりで検出・採用・パックまで)
        self.assertEqual((req["rid"], req["deliverDir"], req["cut"], req["videoTracks"], req["streamer"]), ("req-1", "", "silence", 3, ""))
        self.assertEqual(req["settings"], {"sens": "normal", "perHour": 6, "length": 40, "waitMin": 2, "pad": 1.0, "afterStream": False})
        self.assertEqual(req["speakers"], {"count": 2, "names": ["兎田ぺこら"], "styles": {"兎田ぺこら": {"color": "#FF0000"}}})
        # 上限は束の adopt.top
        self.assertEqual(self.s.detector.auto_max("local", REC), 2)
        self.assertEqual(self.s.detector.auto_max("local", "20261011-210000-x"), D.AUTO_MAX_PER_REC)   # 束の無い録画は今の上限
        # 採用(LocalMarks = スタジオなし)→ 書き出しのジョブ(依頼の録画 = after auto・余白は依頼の 1 秒)
        self.assertIsInstance(self.s.marks, LA.LocalMarks)
        res = self.s.adopt({"recorder": "local", "recording": REC, "start": 100.0, "end": 130.0, "origin": "auto"})
        job = res["job"]
        self.assertEqual((job["after"], job["studio"]["start"], job["studio"]["end"], job["request"]["rid"]), ("auto", 99.0, 131.0, "req-1"))
        self.assertEqual(self.s.exporter.marks.load("local", REC)["marks"][0]["status"], "adopted")
        # 書き出しが済んだ所から: まとめて実行へ 封筒 kind file + 録画の束
        media = os.path.join(self.tmp, "out", "友人の配信", "01_00h01m39s-00h02m11s.mp4")
        os.makedirs(os.path.dirname(media))
        open(media, "wb").close()
        job = next(j for j in self.s.exporter.jobs if j["id"] == job["id"])
        run_id, handoff, _warn = self.s.exporter._handoff(job, media, "auto")
        self.assertEqual(handoff, "")
        env, spec = self.queue.got[-1]   # 受けたときに決める物は submit が必ず hook の _accept で
        self.assertEqual((run_id, env["specVersion"], env["kind"], env["input"]["path"], env["requestId"], env["deliver"]["dir"]),
                         (env["id"], 2, "file", media, "req-1", None))   # 届け先の無い依頼(友人の PC)= 届ける段は「届け先がありません」で飛ばす
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

    def test_old_bundles_file_reads(self):
        """古い形の live/bundles.json(封筒に deliver.batch・note・束の run.pinned)を固定の見本にして読む。batch・note は読んで捨てる。
        legacy つきの封筒は封筒だけ無しにして束は読む。配信者は束の hints.streamer・cut・engine・model は書き出したあとの設定に・
        ファイルは読むだけでは書き換えない"""
        old = {"local/" + REC: {"envelope": {"id": "lv-0123456789ab", "kind": "live", "input": {"title": "", "videoId": VID, "url": URL, "recorder": None},
                                             "requestId": None, "deliver": {"dir": None, "batch": None, "pool": None, "origin": None, "tag": None}, "note": "",
                                             "createdAt": 1790000000000, "specVersion": 2},
                                "spec": {"pack": {"cut": "silence"}, "transcribe": {"engine": "whisper.cpp", "model": "large-v3"}, "hints": {"streamer": "兎田ぺこら"},
                                         "run": {"pinned": ["cut", "engine", "model"]}, "adopt": {"pad": 1.5}}, "at": T0},
               "local/20261011-210000-" + VID: {"envelope": {"id": "lv-0123456789ac", "kind": "live", "input": {"videoId": VID}, "specVersion": 1,
                                              "legacy": {"streamer": "兎田ぺこら"}}, "spec": {"adopt": {"pad": 1.5}}, "at": T0}}
        os.makedirs(os.path.dirname(self.bundles_path), exist_ok=True)
        raw = json.dumps(old, ensure_ascii=False).encode("utf-8")
        fsio.atomic_write(self.bundles_path, raw)
        s2 = self.session()
        try:
            b = s2.bundle("local", REC)
            self.assertEqual((b["hints"]["streamer"], sorted(b["run"]["requested"])), ("兎田ぺこら", ["cut", "engine", "model"]))
            self.assertNotIn("pinned", b["run"])
            self.assertEqual(s2.auto_cfg("local", REC), {"after": "auto", "cut": "silence", "engine": "whisper.cpp", "model": "large-v3", "pad": 1.5})
            got = s2.bundles.get("local", REC)["envelope"]
            self.assertEqual((got["specVersion"], "note" in got, "batch" in got["deliver"]), (2, False, False))
            self.assertIsNone(s2.bundles.get("local", "20261011-210000-" + VID)["envelope"], "前の版の封筒は無しに(束は残す)")
            with open(self.bundles_path, "rb") as f:
                self.assertEqual(f.read(), raw, "読むだけでは書き換えない")
        finally:
            s2.detector.stop()

    def test_streamer_to_request(self):
        """束の hints.streamer は、依頼の結びつきの配信者に"""
        out = self.s.submit({"id": "live000013", "kind": "live", "input": {"videoId": VID}, "requestId": "req-2", "specVersion": 2},
                            dict(self.SPEC, hints={"streamer": "兎田ぺこら"}))
        self.assertTrue(out["live"])
        self.assertEqual(self.s.requests.get("local", REC)["streamer"], "兎田ぺこら")


class BeginTest(Base):
    """録画を始める芯 begin の分かれ道(録画元の 409・画質・配信前・調べられない・チャンネル名の掃除)。入口の POST /live/api/begin の形と安全の境目は src/app/tests/test_live.py"""

    def recorder(self, lists, start):
        """録画元の偽物: /live/list は lists を順に返し(尽きたら空)、/live/start は start(body) -> (code, dict)。-> 録画を始める body の記録"""
        started = []

        def call(rc, method, path, body=None, timeout=3.0):
            if (method, path) == ("GET", "/live/list"):
                return 200, lists.pop(0) if lists else {"recordings": []}
            if (method, path) == ("POST", "/live/start"):
                started.append(body)
                return start(body)
            return 404, {}
        self.s.call = call
        return started

    def test_channel_is_cleaned(self):
        """チャンネル名は制御文字を落として長さを切る・分からなければ空"""
        self.s.probe = lambda url: {"status": "is_live", "title": "題", "channel": "ch\x07\n名" + "x" * 300, "message": ""}
        self.assertEqual(self.s.begin(URL)["recording"]["channel"], ("ch名" + "x" * 300)[:LS.CHANNEL_MAX])
        self.rec.recs.clear()
        self.s.probe = lambda url: {"status": "is_live", "title": "題", "channel": None, "message": ""}
        self.assertEqual(self.s.begin(URL)["recording"]["channel"], "")

    def test_start_conflict(self):
        """録画元が「もう録画しています」(409)なら一覧から探して返す(最初の一覧には無かった)。ほかの 409 は理由つきで断る"""
        rec = {"id": REC, "url": URL, "title": "配信の題", "state": "recording", "active": True}
        self.recorder([{"recordings": []}, {"recordings": [rec]}], lambda b: (409, {"message": "その配信はもう録画しています"}))
        out = self.s.begin(URL)
        self.assertEqual((out["live"], out["existing"], out["recording"]["id"]), (True, True, REC))
        self.recorder([], lambda b: (409, {"message": "streamlink が入っていません"}))
        with self.assertRaises(LX.LiveError) as cm:
            self.s.begin(URL)
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("streamlink", str(cm.exception))

    def test_quality_and_upcoming(self):
        """画質は設定のとおり・配信前も録画する(題が分からなければ空で渡す = 録画の部品が付ける)"""
        started = self.recorder([], lambda b: (200, {"recording": {"id": REC, "url": b["url"], "title": b["title"], "state": "waiting"}}))
        self.cfg["quality"] = "720p"
        self.s.probe = lambda url: {"status": "is_upcoming", "title": "", "channel": "", "message": ""}
        self.assertTrue(self.s.begin(URL)["live"])
        self.assertEqual((started[-1]["quality"], started[-1]["title"]), ("720p", ""))

    def test_not_started_when_status_unknown(self):
        """調べられない(NA・調べる部品の例外)は live: false の unknown(録画元には頼まない)。理由があれば 300 字まで付ける"""
        started = self.recorder([], lambda b: (200, {"recording": {}}))
        self.s.probe = lambda url: {"status": "NA", "title": "", "channel": "", "message": "調べられませんでした(ERROR: x)"}
        self.assertEqual(self.s.begin(URL), {"live": False, "status": "unknown", "message": "調べられませんでした(ERROR: x)"})

        def boom(url):
            raise RuntimeError("壊れた")
        self.s.probe = boom
        self.assertEqual(self.s.begin(URL), {"live": False, "status": "unknown"})
        self.assertEqual(started, [])


class RecentTest(Base):
    """ヘッダーの札の一覧 recent: 録画中 + 終わって RECENT_SEC 以内だけ・形の違う id は出さない・STATUS_CACHE 秒は録画元に聞き直さない"""

    def test_window_bad_id_and_cache(self):
        now = time.time()
        recs = [{"id": REC, "url": URL, "title": "配信中", "state": "recording", "active": True, "seconds": 12.5, "endedAt": None},
                {"id": "20261011-170000-bbbbbbbbbbb", "state": "stopped", "active": False, "seconds": 300, "endedAt": LX.epoch_iso(now - 120)},
                {"id": "20261011-120000-ccccccccccc", "state": "ended", "active": False, "seconds": 9, "endedAt": LX.epoch_iso(now - LS.RECENT_SEC - 60)},
                {"id": "../evil", "state": "recording", "active": True}]
        lists = []
        self.s.call = lambda rc, method, path, body=None, timeout=3.0: (lists.append(1), (200, {"recordings": recs}))[1]
        got = self.s.recent()
        self.assertEqual([(r["recorder"], r["id"], r["active"], r["state"]) for r in got],
                         [("local", REC, True, "recording"), ("local", "20261011-170000-bbbbbbbbbbb", False, "stopped")])
        self.assertEqual((got[0]["seconds"], got[0]["title"], got[1]["endedAt"]), (12.5, "配信中", recs[1]["endedAt"]))
        self.assertEqual(self.s.recent(), got)   # 覚えた結果(録画元に聞かない)
        self.assertEqual(len(lists), 1)
        self.s._recent = (time.time() - LS.STATUS_CACHE - 0.1, [])
        self.s.recent()
        self.assertEqual(len(lists), 2)


if __name__ == "__main__":
    unittest.main()
