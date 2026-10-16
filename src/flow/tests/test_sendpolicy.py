# -*- coding: utf-8 -*-
"""flow/sendpolicy.py(友人へ自動で送る判定。D-SEND の段 1)と flow/deliveries.py の書き口・読み口のテスト。
py -3.10 -m unittest src/flow/tests/test_sendpolicy.py -v"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import shutil
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from flow import deliveries as D, sendpolicy as P  # noqa: E402

NOW = 1_800_000_000.0
H = 3600


class TestDecide(unittest.TestCase):
    def test_five_ways(self):
        fresh = NOW - 2 * H
        self.assertEqual(P.decide("auto", fresh, NOW, False, True), (True, None))
        self.assertEqual(P.decide("auto", fresh, NOW, False, False), (False, "unchecked"))
        self.assertEqual(P.decide("auto", fresh, NOW, True, True), (False, "requested"))
        self.assertEqual(P.decide("auto", None, NOW, False, True), (False, "unknown_end"))
        self.assertEqual(P.decide("auto", NOW - 49 * H, NOW, False, True), (False, "stale"))

    def test_boundary_and_order(self):
        self.assertEqual(P.decide("auto", NOW - P.FRESH_SEC, NOW, False, True), (True, None), "ちょうど 48 時間は送る")
        self.assertEqual(P.decide("auto", NOW - P.FRESH_SEC - 1, NOW, False, True), (False, "stale"))
        self.assertEqual(P.decide("auto", NOW + 5, NOW, False, True), (True, None), "未来は新しい扱い")
        self.assertEqual(P.decide("auto", NOW - 99 * H, NOW, True, False), (False, "unchecked"), "チェックが先")
        self.assertEqual(P.decide("auto", NOW - 99 * H, NOW, True, True), (False, "requested"), "依頼が古さより先")
        for bad in (0, -1, True, "x"):
            self.assertEqual(P.decide("auto", bad, NOW, False, True), (False, "unknown_end"), bad)

    def test_request_and_manual_always_send(self):
        for origin in ("request", "manual"):
            self.assertEqual(P.decide(origin, None, NOW, True, False), (True, None))
            self.assertEqual(P.decide(origin, NOW - 999 * H, NOW, True, False), (True, None))

    def test_reason_text(self):
        self.assertEqual(P.reason_text("stale", hours=50), "古い配信なので送りません(終わってから 50 時間)")
        self.assertEqual(P.reason_text("requested"), "友人の依頼があるので送りません")
        self.assertEqual(P.reason_text("unchecked"), P.REASONS["unchecked"])
        self.assertEqual(P.reason_text("zzz"), "zzz")
        self.assertEqual(P.hours_since(NOW - 50 * H - 30, NOW), 50)
        self.assertEqual(P.hours_since(NOW + 9, NOW), 0)
        for code in ("unchecked", "stale", "requested", "expired", "unknown_end"):
            self.assertIn(code, P.REASONS)

    def test_switch(self):
        self.assertTrue(P.switched_off({"YTT_AUTO_SEND": " OFF "}))
        self.assertFalse(P.switched_off({"YTT_AUTO_SEND": "on"}))
        self.assertFalse(P.switched_off({}))


class TestEndedAt(unittest.TestCase):
    def test_was_live_and_post_live(self):
        for st in ("was_live", "post_live"):
            self.assertEqual(P.ended_at_of({"liveStatus": st, "releaseTs": 1000, "duration": 500}), 1500.0)

    def test_unknown_is_none(self):
        for a in (None, "x", {}, {"liveStatus": "not_live", "releaseTs": 1000, "duration": 500},
                  {"liveStatus": "is_live", "releaseTs": 1000, "duration": 500},
                  {"liveStatus": "was_live", "duration": 500}, {"liveStatus": "was_live", "releaseTs": 1000},
                  {"liveStatus": "was_live", "releaseTs": 0, "duration": 500}, {"liveStatus": "was_live", "releaseTs": 1000, "duration": 0},
                  {"liveStatus": "was_live", "releaseTs": "1000", "duration": 500}, {"liveStatus": "was_live", "releaseTs": True, "duration": 500}):
            self.assertIsNone(P.ended_at_of(a), a)


class FakeRun:
    def __init__(self, vid="VID1", rid=""):
        self.request_id, self.id, self.video_id, self.title = rid, "run0000001", vid, "題"


class TestDeliveries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliv-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_record_and_read(self):
        row = D.record(self.tmp, os.path.join("x", "a.zip"), FakeRun("V1", "rid1"), ["p1"], {"p1": {"path": "c.mp4", "markId": "m1"}}, "request", 1500.0)
        self.assertEqual((row["zip"], row["origin"], row["endedAt"], row["requestId"], row["packs"]), ("a.zip", "request", 1500000, "rid1", [{"dir": "p1", "path": "c.mp4", "markId": "m1"}]))
        D.record(self.tmp, "b.zip", FakeRun("V2"), ["p2"], origin="auto")
        D.record(self.tmp, "c.zip", FakeRun("V3"), [], origin="manual", ended_at=2000)
        self.assertEqual(D.rows(self.tmp)[1]["endedAt"], 0)
        self.assertEqual(sorted(D.delivered_videos(self.tmp)), ["V1", "V2", "V3"])
        self.assertEqual(sorted(D.delivered_videos(self.tmp, "auto")), ["V2"])
        self.assertEqual(sorted(D.delivered_videos(self.tmp, "request")), ["V1"])
        self.assertEqual(sorted(D.delivered_requests(self.tmp)), ["rid1"], "既存の読み口はそのまま")
        self.assertTrue(all(v > 0 for v in D.delivered_videos(self.tmp).values()))

    def test_old_rows_and_unreadable(self):
        self.assertIsNone(D.delivered_videos(self.tmp), "記録が無い = 分からない")
        with open(os.path.join(self.tmp, D.LOG), "w", encoding="utf-8") as f:
            f.write('{"at": 3000, "zip": "o.zip", "requestId": "r", "videoId": "A"}\n{"at": 4000, "zip": "p.zip", "videoId": "B"}\n'
                    'ゴミ\n{"at": 9, "videoId": "A", "origin": "manual"}\n{"videoId": 5}\n')
        self.assertEqual(D.delivered_videos(self.tmp), {"A": 3.0, "B": 4.0})
        self.assertEqual(D.delivered_videos(self.tmp, "request"), {"A": 3.0}, "origin の鍵が無い行は依頼の id があれば request")
        self.assertEqual(D.delivered_videos(self.tmp, "auto"), {"B": 4.0}, "無ければ auto")
        self.assertEqual(D.delivered_videos(self.tmp, "manual"), {"A": 0.009})

    def test_friend_feedback_is_thin_forward(self):
        from human.friend import friend_feedback as F
        self.assertEqual(F.DELIVERIES_LOG, D.LOG)
        row = F.record_delivery(self.tmp, "z.zip", FakeRun("V9", "r9"), ["d"], None, "auto", 1000)
        self.assertEqual((row["origin"], row["endedAt"]), ("auto", 1000000))
        self.assertEqual(F.find_delivery(self.tmp, "z.zip")["videoId"], "V9")
        self.assertEqual(F.record_delivery(self.tmp, "y.zip", FakeRun(), [])["origin"], "request", "既定は今までどおり")


if __name__ == "__main__":
    unittest.main()
