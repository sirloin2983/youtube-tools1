# -*- coding: utf-8 -*-
"""配信中の盛り上がりの検出の入口 home の側(app の殻 Live の GET|POST /live/api/peaks の振り分け・ホームの設定 prefs の検査)のテスト。
Detector の中身(api_get・採用・自動の採用など)は ② の tests/flow/test_live_detect.py、ワーカーは tests/pipeline/analyze/test_live_excite_worker.py。

    py -3.12 -m unittest tests/app/test_live_detect_api.py

  - Live.handle_get / handle_post の振り分け(入口の合言葉・Origin の検査は server.py が先に済ませる)・オフなら 404
  - 設定 detect・autoAdopt の検査(既定・範囲・壊れた値は既定へ)
作業データはテストの一時フォルダだけ(YTT_DATA_DIR=inplace)。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src", "app")
SRC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(SRC), "tests", "flow"))   # 共有の偽物 _livefix
if SRC not in sys.path:   # src(層のパッケージ。server.py と同じく後ろに)
    sys.path.append(SRC)
import _livefix as LF  # noqa: E402
from app import live as LV  # noqa: E402
from app import prefs as P  # noqa: E402
from ytt import fsio  # noqa: E402

TOKEN = "k" * 40
VID = "abcdefghijk"
REC = "20261007-200000-" + VID


class Handler:
    """server.py の PortalHandler の代わり(Live.handle_get / handle_post が呼ぶ口だけ)"""

    def __init__(self):
        self.out, self.server = None, None

    def _json(self, code, obj):
        self.out = (code, obj)

    def _fail(self, code, err, msg):
        self.out = (code, {"error": err, "message": msg})


class DetectRouteTest(unittest.TestCase):
    """入口の Live(app)を通す分。ワーカーは起動しない(peaks.json はテストが置く)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-route-")
        self.prefs = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)
        self.prefs.patch("live", {"enabled": True, "recorders": [{"id": "fake", "name": "偽物", "url": "http://127.0.0.1:9999", "token": TOKEN}],
                                  "detect": {"enabled": True}})
        self.live = LV.Live(self.prefs, self.tmp, os.path.join(self.tmp, "logs"), spawn=False,
                            store_dir=os.path.join(self.tmp, "live"), out_dir=lambda: os.path.join(self.tmp, "out"))
        self.det = self.live.detector
        self.folder = os.path.join(self.tmp, "live", "excite", "fake", REC)
        self.put_peaks([self.peak("p0-302", 272, 302, "frame"), self.peak("p1-903", 870, 903, "frame"), self.peak("p2-1002", 973, 1002, "bench")], seq=5,
                       changes=[[1, "p0-302", "frame"], [2, "p1-903", "frame"], [3, "p2-1002", "frame"], [4, "p2-1002", "bench"], [5, "p1-903", "frame"]])

    def tearDown(self):
        self.det.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def peak(pid, start, pk, state):
        return {"id": pid, "start": float(start), "end": float(start + 45), "peak": pk, "score": 9.0, "parts": {"audio": 3.0, "chat": 2.0},
                "reasons": ["音量が急上昇"], "confirmedAt": pk + 30, "hour": 0, "state": state, "endPending": False, "origin": None, "seq": 0}

    def put_peaks(self, peaks, seq, changes):
        doc = {"v": 1, "recorder": "fake", "recording": REC, "seq": seq, "decN": 0, "perHour": 6, "counts": {"0": 2}, "lag": 9, "chat": "ok",
               "behindSec": 4.0, "at": "2026-10-07T20:00:00Z", "message": "", "peaks": peaks,
               "changes": [{"seq": a, "id": b, "state": c} for a, b, c in changes]}
        os.makedirs(self.folder, exist_ok=True)
        fsio.atomic_write(os.path.join(self.folder, "peaks.json"), json.dumps(doc).encode("utf-8"))

    def test_routes_through_live(self):
        """Live.handle_get / handle_post の振り分け(入口の合言葉・Origin の検査は server.py が先に済ませる)"""
        h = Handler()
        self.assertTrue(self.live.handle_get(h, urllib.parse.urlsplit("/live/api/peaks?recorder=fake&recording=%s&since=4" % REC)))
        self.assertEqual(h.out[0], 200)
        self.assertTrue(self.live.handle_get(h, urllib.parse.urlsplit("/live/api/peaks?recorder=fake&recording=bad")))
        self.assertEqual((h.out[0], h.out[1]["error"]), (400, "bad_request"))
        self.live.handle_post(h, urllib.parse.urlsplit("/live/api/peaks"), {"op": "dismiss", "recorder": "fake", "recording": REC, "id": "p1-903"})
        self.assertEqual((h.out[0], h.out[1]["peak"]["state"]), (200, "dismissed"))
        self.prefs.patch("live", {"enabled": False})
        self.assertFalse(self.live.handle_get(h, urllib.parse.urlsplit("/live/api/peaks?recorder=fake&recording=%s" % REC)))   # オフ = 今までどおり 404
        self.prefs.patch("live", {"enabled": True, "detect": {"enabled": False}})
        self.assertTrue(self.live.handle_get(h, urllib.parse.urlsplit("/live/api/peaks?recorder=fake&recording=%s" % REC)))
        self.assertIs(h.out[1]["enabled"], False)   # 検出がオフでも、残っている候補は読める


class PrefsDetectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-detect-prefs-")
        self.p = P.Prefs(os.path.join(self.tmp, "prefs.json"), fsio.atomic_write)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detect_and_auto_adopt(self):
        v = self.p.get(["live"])["live"]
        self.assertEqual((v["detect"], v["autoAdopt"]), ({"enabled": True, "sens": "normal", "perHour": 6, "fill": True}, {"waitMin": 5}))   # 検出は既定オン・自動の採用はいつもオン(待つ分だけ)
        v = self.p.patch("live", {"detect": {"enabled": True, "sens": "low"}})
        self.assertEqual(v["detect"], {"enabled": True, "sens": "low", "perHour": 6, "fill": True})
        self.assertEqual(self.p.patch("live", {"detect": {"perHour": 30}})["detect"], {"enabled": True, "sens": "low", "perHour": 30, "fill": True})   # 鍵ごと
        self.assertIs(self.p.patch("live", {"detect": {"fill": False}})["detect"]["fill"], False)   # 本数の埋めのスイッチ
        self.p.patch("live", {"detect": {"fill": True}})
        self.assertEqual(self.p.patch("live", {"autoAdopt": {"waitMin": 60}})["autoAdopt"], {"waitMin": 60})
        self.assertEqual(self.p.patch("live", {"autoAdopt": {"enabled": False}})["autoAdopt"], {"waitMin": 60})   # オフのスイッチは無い(古い画面が送っても黙って捨てる)
        for bad in ({"detect": "on"}, {"detect": {"enabled": "yes"}}, {"detect": {"sens": "max"}}, {"detect": {"perHour": True}}, {"detect": {"fill": "on"}},   # 範囲の端は test_settings_schema.py
                    {"autoAdopt": []}, {"autoAdopt": {"waitMin": "5"}}):
            with self.assertRaises(P.PrefsError, msg=repr(bad)):
                self.p.patch("live", bad)
        self.assertEqual(self.p.patch("live", {"quality": "720p"})["detect"]["perHour"], 30)   # ほかの鍵を直しても残る
        with open(os.path.join(self.tmp, "prefs.json"), encoding="utf-8") as f:
            d = json.load(f)
        d["live"]["detect"] = {"enabled": "yes", "sens": "max", "perHour": 99}   # 壊れた値は読むときに既定へ(断らない)
        d["live"]["autoAdopt"] = "x"
        with open(os.path.join(self.tmp, "prefs.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)
        v = self.p.get(["live"])["live"]
        self.assertEqual((v["detect"], v["autoAdopt"]), ({"enabled": True, "sens": "normal", "perHour": 6, "fill": True}, {"waitMin": 5}))


if __name__ == "__main__":
    unittest.main()
