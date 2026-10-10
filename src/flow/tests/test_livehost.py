# -*- coding: utf-8 -*-
"""flow/livehost(ライブの親の口。役割で組み直す RS7-2 G0)のテスト。  py -3.10 -m unittest src/flow/tests/test_livehost.py -v

- 偽の親(FakeHost。Live を使わない)で Detector・LiveTx・Reporter・Exporter を作り、主な見回り・API が動く。
  それぞれの子には「口に並べた名前だけを通す」包み(Strict)を渡す = 子が口に無い物を親に求めたら落ちる(口と実際の使い方がずれない)
- 本物の Live(src/home/live.py)が口(LiveHost)の名前を全部持ち、メソッドの引数を受けられる
- Live.close の順: 終わりの印 → 検出 → 配信中の文字起こし → 作り直し → 書き出し → 録画の部品(G2b で Live を割るときに変えない)
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import inspect
import json
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "home"))   # 本物の Live(app)と設定(prefs)
from flow import livehost as H  # noqa: E402
from flow import live_detect as D, live_export as LX, live_report as RP, live_tx as TX  # noqa: E402
from ytt import datadir, fsio, schemas  # noqa: E402

VID = "abcdefghijk"
REC = "20261011-200000-" + VID
REC2 = "20261011-200005-" + VID
URL = "https://www.youtube.com/watch?v=" + VID
T0 = 1790000000.0


def iso(t):
    return LX.epoch_iso(t)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def peak(pid, start, state, confirmed):
    return {"id": pid, "start": float(start), "end": float(start + 45), "peak": start + 30, "score": 9.0, "parts": {"audio": 3.0, "chat": 2.0},
            "reasons": ["音量が急上昇"], "confirmedAt": confirmed, "hour": 0, "state": state, "endPending": False, "origin": None, "seq": 0}


class Book:
    """友人の依頼の結びつき(live_requests.Store の形だけ)"""

    def get(self, rc, rec):
        return None

    def all(self):
        return {}


class Strict:
    """口(Protocol)に並べた名前だけを親から通す。口に無い名前は落として記録する(OPTIONAL の名前は黙って無いことにする = getattr の既定に落ちる)"""

    def __init__(self, proto, target, optional=()):
        object.__setattr__(self, "_ok", set(H.names(proto)))
        object.__setattr__(self, "_opt", set(optional))
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "bad", [])

    def __getattr__(self, name):
        if name not in self._ok:
            if name not in self._opt:
                self.bad.append(name)
            raise AttributeError("口に無い名前: %s" % name)
        return getattr(self._t, name)


class FakeHost:
    """Live の代わり(LiveHost の名前を全部持つ)。録画元 2 つ(fake・spare)が同じ配信を録っている"""

    def __init__(self, tmp, clock):
        self.root = tmp
        self.store_dir = os.path.join(tmp, "live")
        self.logs_dir = os.path.join(tmp, "logs")
        self.logs, self.notes, self.adopted, self.calls, self.studio = [], [], [], [], []
        self.log = self.logs.append
        self.requests = Book()
        self._halt = threading.Event()
        self.unconfirmed = None
        self.clock = clock
        self._cfg = {"enabled": True, "detect": {"enabled": True}, "autoAdopt": {"enabled": True, "waitMin": 1}, "liveTx": {"enabled": True}}
        self.detector = self.livetx = self.exporter = None   # 子は下で作る(子が親を持つ)

    def cfg(self):
        return self._cfg

    def enabled(self):
        return self._cfg.get("enabled") is True

    def recorders(self, cfg=None):
        return [{"id": "fake", "name": "偽物", "url": "http://127.0.0.1:9", "token": "t"},
                {"id": "spare", "name": "予備", "url": "http://127.0.0.1:9", "token": "t"}]

    def find(self, rid):
        return next((r for r in self.recorders() if r["id"] == rid), None)

    def call(self, rc, method, path, body=None, timeout=3.0):
        self.calls.append((rc["id"], method, path))
        if path == "/live/list":
            return 200, {"recordings": [{"id": REC if rc["id"] == "fake" else REC2, "url": URL}]}
        if "/segments?" in path:
            return 200, {"url": URL, "segments": []}
        return 404, {"message": "なし"}

    def request(self, rc, method, path, body=None, timeout=10.0):
        raise OSError("このテストはセグメントを取らない")

    def studio_call(self, method, path, body=None):
        self.studio.append((method, path, body))
        return None, {"message": "スタジオは動いていません"}

    def list_recordings(self):
        now = self.clock()
        return [{"recorder": "fake", "id": REC, "url": URL, "title": "テスト配信", "active": True, "endedAt": None,
                 "firstPdt": now - 1500.0, "lastPdt": now}]

    def _ids(self, rc_id, rec):
        if not schemas.ids_ok(rc_id, rec):
            raise LX.LiveError("録画元か録画の指定が正しくありません")
        rc = self.find(rc_id)
        if rc is None:
            raise LX.LiveError("その録画元はありません", 404)
        return rc

    def adopt(self, body, hold=None):
        self.adopted.append(dict(body))
        return {"job": {"id": "lx-%010x" % len(self.adopted), "origin": body.get("origin")}, "video": REC, "mark": "m%d" % len(self.adopted),
                "existing": False, "origin": body.get("origin")}

    def note(self, msg):
        self.notes.append(msg)


class FakeHostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-livehost-")
        env = {k: v for k, v in os.environ.items() if k != "TRANSCRIBE_DATA_DIR"}   # 編集の作業データ = <root>/editor(datadir の inplace)
        env["YTT_DATA_DIR"] = "inplace"
        for p in (mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(datadir._registered, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        self.t = [T0]
        clock = lambda: self.t[0]   # noqa: E731
        self.host = h = FakeHost(self.tmp, clock)
        self.views = {"det": Strict(H.DetectHost, h, H.OPTIONAL["Detector"]), "tx": Strict(H.TxHost, h),
                      "rep": Strict(H.ReportHost, h), "ex": Strict(H.ExportHost, h, H.OPTIONAL["Exporter"])}
        h.detector = D.Detector(self.views["det"], spawn=False, clock=clock)
        h.detector.stale_sec = 10 ** 9
        h.livetx = TX.LiveTx(self.views["tx"], log=h.log, clock=clock, run=lambda *a: {"ok": True, "text": "x"}, ffmpeg="ffmpeg-fake")
        h.livetx.start = lambda: None   # 裏のスレッドは動かさない(列に入るまでを見る)
        h.exporter = LX.Exporter(self.views["ex"], h.store_dir, lambda: os.path.join(self.tmp, "out"), log=h.log)
        h.exporter.start = lambda: None   # 書き出しは動かさない(ジョブは「録画待ち」のまま)
        self.rep = RP.Reporter(self.views["rep"], clock=clock)
        self.folder = h.detector.folder("fake", REC)

    def tearDown(self):
        self.host.livetx.close()
        self.host.detector.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def no_strays(self):
        """子が口に無い名前を親に求めていない(例外を握りつぶす所でも bad に残る)"""
        for k, v in self.views.items():
            self.assertEqual(v.bad, [], k)
        self.assertFalse([n for n in self.host.notes if "口に無い" in n], self.host.notes)

    def put_peaks(self, peaks):
        doc = {"v": 1, "recorder": "fake", "recording": REC, "seq": 2, "decN": 0, "perHour": 6, "counts": {"0": 2}, "lag": 9, "chat": "ok",
               "behindSec": 4.0, "at": iso(self.t[0]), "message": "", "peaks": peaks, "changes": [{"seq": 1, "id": "p0-302", "state": "frame"}]}
        os.makedirs(self.folder, exist_ok=True)
        fsio.atomic_write(os.path.join(self.folder, "peaks.json"), json.dumps(doc).encode("utf-8"))
        hb = {"v": 1, "pid": 99999, "at": iso(self.t[0]), "behindSec": 4.0, "memMB": 50.0, "chatRestarts": 0,
              "recordings": [{"recorder": "fake", "id": REC, "behindSec": 4.0, "chat": "ok"}], "message": "1 本の録画を見ています", "error": ""}
        fsio.atomic_write(os.path.join(self.host.detector.dir, "worker.json"), json.dumps(hb).encode("utf-8"))

    def test_fake_host_has_every_name(self):
        """偽の親も口を全部持つ(口を足したら偽の親にも足す)。包み Strict は口に無い名前を落として残す"""
        for name in H.names(H.LiveHost):
            self.assertTrue(hasattr(self.host, name), name)
        s = Strict(H.ExportHost, self.host, H.OPTIONAL["Exporter"])
        self.assertIsNone(getattr(s, "studio_call", None))   # OPTIONAL は無いことにするだけ
        with self.assertRaises(AttributeError):
            s.cfg()
        self.assertEqual(s.bad, ["cfg"])

    def test_detect_tx_report_without_live(self):
        h = self.host
        self.put_peaks([peak("p0-302", 272, "frame", 336), peak("p1-903", 870, "bench", 930)])
        h.livetx.record("fake", REC, "p0-302", "ここで大きな声", sec=3.0)
        # 検出の見回り: 設定を書き、最初に見た候補は待つ(waitMin 1 分)
        self.assertEqual(h.detector.tick(), "nospawn")
        self.assertTrue(os.path.isfile(os.path.join(h.detector.dir, "config.json")))
        self.assertEqual([r["id"] for r in load(os.path.join(h.detector.dir, "config.json"))["recorders"]], ["fake", "spare"])
        self.assertEqual(h.adopted, [])
        self.assertEqual(h.studio[0][:2], ("GET", "/api/settings"))   # 解析の設定はスタジオに聞く(動いていなければ既定)
        self.t[0] += 61
        h.detector.tick()
        self.assertEqual([(b["origin"], b["start"], b.get("text"), b.get("after")) for b in h.adopted], [("auto", 272.0, "ここで大きな声", "auto")])
        dec = load(os.path.join(self.folder, "decisions.json"))["items"]
        self.assertEqual([(x["id"], x["state"], x["origin"], x["markId"]) for x in dec], [("p0-302", "adopted", "auto", "m1")])
        # 候補の API(画面): 親の _ids・livetx・requests を通る
        g = h.detector.api_get({"recorder": ["fake"], "recording": [REC]})
        self.assertEqual([(p["id"], p["state"], p.get("text")) for p in g["peaks"]], [("p0-302", "adopted", "ここで大きな声"), ("p1-903", "bench", None)])
        self.assertTrue(g["tx"]["enabled"])
        with self.assertRaises(LX.LiveError) as cm:
            h.detector.api_get({"recorder": ["nope"], "recording": [REC]})
        self.assertEqual(cm.exception.code, 404)
        r = h.detector.api_post({"op": "dismiss", "recorder": "fake", "recording": REC, "id": "p1-903"})
        self.assertEqual(r["peak"]["state"], "dismissed")
        # 配信中の文字起こし: 準備があれば、文字の無い候補だけ列に入る
        self.assertEqual(h.livetx.tick(), 0)   # whisper.cpp が無い
        edir = h.livetx.data_dir()
        self.assertTrue(os.path.abspath(edir).startswith(os.path.abspath(self.tmp)), edir)   # 一時フォルダの中だけに置く
        for p in (h.livetx.paths()["exe"], h.livetx.paths()["model"]):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").close()
        h.detector.api_post({"op": "restore", "recorder": "fake", "recording": REC, "id": "p1-903"})
        self.assertEqual(h.livetx.tick(), 1)
        self.assertEqual([(rc, rec, pk["id"]) for rc, rec, pk, _f in h.livetx.queue], [("fake", REC, "p1-903")])
        h.livetx._one("nope", REC, {"id": "p1-903", "start": 870.0, "end": 915.0}, T0)   # 録画元が無い(親の find)
        self.assertIn("error", h.livetx.items("nope", REC)["p1-903"])
        # 配信ごとの結果の記録
        self.assertEqual(self.rep.tick(force=True), 1)
        rep = self.rep.load("fake", REC)
        self.assertEqual((rep["state"], rep["detect"]["adoptedAuto"], rep["detect"]["bench"], rep["tx"]["ok"], rep["request"]),
                         ("recording", 1, 1, 1, None))
        h._cfg["enabled"] = False
        self.assertEqual((h.detector.tick(), self.rep.tick(force=True), h.livetx.tick()), ("off", 0, 0))
        self.no_strays()

    def test_exporter_without_live(self):
        h, ex = self.host, self.host.exporter
        mid = LX.studio_mark_id("mk1")
        a, b = T0 - 600, T0 - 555
        ex.marks.upsert("fake", REC, mid, 1, iso(a), iso(b), "見せ場", url=URL, title="テスト配信")
        job = ex.add("fake", REC, mid, transcribe=False)
        self.assertEqual((job["state"], job["after"], job["recorder"]), ("wait", "none", "fake"))
        with self.assertRaises(LX.LiveError) as cm:
            ex.add("nope", REC, mid)
        self.assertEqual(cm.exception.code, 404)
        src = ex._sources(job, a, b)   # 主の録画元 + 同じ配信を録っている予備(親の find・call・recorders)
        self.assertEqual([(rc["id"], rec) for rc, rec, _d in src], [("fake", REC), ("spare", REC2)])
        self.assertIn(("spare", "GET", "/live/list"), h.calls)
        # スタジオのマークを「書き出し済み」に: 口の ExportHost に studio_call は無い = 黙って飛ばす(OPTIONAL)
        self.assertEqual(ex._studio_exported({"studio": {"video": REC, "mark": "mk1"}}, "x.mp4"), "")
        self.assertEqual(h.studio, [])
        full = LX.Exporter(h, os.path.join(self.tmp, "live2"), lambda: os.path.join(self.tmp, "out"))   # 親が持っていれば呼ぶ
        self.assertEqual(full._studio_exported({"studio": {"video": REC, "mark": "mk1"}}, "x.mp4"), "")
        self.assertEqual(h.studio, [("POST", "/api/live/exported", {"id": REC, "markId": "mk1", "path": "x.mp4"})])
        self.no_strays()


class LiveTest(unittest.TestCase):
    """本物の Live(app。src/home/live.py)"""

    def setUp(self):
        import live as LV
        import prefs as P
        self.tmp = tempfile.mkdtemp(prefix="ytt-livehost-live-")
        self.logs = []
        pr = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.live = LV.Live(pr, self.tmp, os.path.join(self.tmp, "logs"), log=self.logs.append, spawn=False,
                            store_dir=os.path.join(self.tmp, "live"), out_dir=lambda: os.path.join(self.tmp, "out"))

    def tearDown(self):
        self.live.detector.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_live_has_every_name(self):
        """Live が口の名前を全部持つ(property の exporter は作らずに確かめる)・メソッドは口の引数を受けられる"""
        lv = self.live
        for name in H.names(H.LiveHost):
            self.assertTrue(name in vars(lv) or hasattr(type(lv), name), name)
        for proto in (H.DetectHost, H.TxHost, H.ReportHost, H.ExportHost, H.LiveHost):
            for name in H.names(proto):
                want = getattr(proto, name, None)
                if not callable(want) or name not in vars(type(lv)) or isinstance(vars(type(lv))[name], property):
                    continue
                got = inspect.signature(getattr(lv, name)).parameters
                for p in list(inspect.signature(want).parameters)[1:]:
                    self.assertIn(p, got, "%s.%s(%s)" % (proto.__name__, name, p))
        self.assertIsNone(lv._exporter)   # 名前を調べても書き出しの部品は作らない
        self.assertEqual(sorted(H.names(H.LiveHost)),
                         sorted(set(H.names(H.DetectHost)) | set(H.names(H.TxHost)) | set(H.names(H.ReportHost)) | set(H.names(H.ExportHost))
                                | {"_halt", "unconfirmed"}))

    def test_children_hold_live_as_host(self):
        lv = self.live
        self.assertIs(lv.detector.host, lv)
        self.assertIs(lv.livetx.host, lv)
        self.assertIs(lv.reporter.host, lv)
        self.assertIs(lv.exporter.host, lv)

    def test_close_order(self):
        """入口の終了: 終わりの印 → 検出 → 配信中の文字起こし → 作り直し → 書き出し → 録画の部品"""
        lv, calls = self.live, []

        class Closer:
            def __init__(self, name):
                self.name = name

            def close(self):
                calls.append(self.name)

        lv.detector.stop = lambda: calls.append(("detector", lv._halt.is_set(), lv.wake.is_set()))
        lv.livetx.close = lambda: calls.append("livetx")
        lv._archiver, lv._exporter = Closer("archiver"), Closer("exporter")
        lv.stop_recorder = lambda: calls.append("recorder")
        lv.close()
        self.assertEqual(calls, [("detector", True, True), "livetx", "archiver", "exporter", "recorder"])

    def test_close_order_unused_parts(self):
        """作り直し・書き出しを使っていなければ作らずに飛ばす。録画の部品を止める途中の不具合で終了を止めない"""
        lv, calls = self.live, []
        lv.detector.stop = lambda: calls.append("detector")
        lv.livetx.close = lambda: calls.append("livetx")

        def boom():
            calls.append("recorder")
            raise RuntimeError("止められない")
        lv.stop_recorder = boom
        lv.close()
        self.assertEqual(calls, ["detector", "livetx", "recorder"])
        self.assertIsNone(lv._exporter)
        self.assertIsNone(lv._archiver)
        self.assertTrue(any("録画の部品を止める途中でエラー" in m for m in self.logs), self.logs)


if __name__ == "__main__":
    unittest.main()
