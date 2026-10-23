# -*- coding: utf-8 -*-
"""flow/deliveries.py(届けた記録・送らなかった記録の読み口)と flow/delivery.switched_off のうち、通しでは起こせない物:
前の版の行と壊れた行・読めない記録・開発機の守りのスイッチ。
届けた記録を書いて読む正しく動く道は tests/flow/test_deliver.py の DeliverRun。 py -3.12 -m unittest tests/flow/test_deliveries.py -v
(10-19 まではここに友人へ自動で送る判定 flow/sendpolicy の試しもあった = 判定ごと消した)"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import deliveries as D, delivery as DL  # noqa: E402


class FakeRun:
    def __init__(self, vid="VID1", rid=""):
        self.request_id, self.id, self.video_id, self.title = rid, "run0000001", vid, "題"


class TestDeliveries(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliv-")

    def test_overlaps_across_requests(self):
        """依頼をまたいだ区間のかぶり(新機能 E): 同じ配信のほかの実行で届けた区間と、短い方の半分以上重なれば知らせる。同じ実行・別の配信・重なりが少ない物は数えない"""
        rows = [{"at": 1, "zip": "r1__01_a.zip", "requestId": "r1", "runId": "A", "videoId": "VID1", "packs": [{"path": "a.mp4"}]},
                {"at": 2, "zip": "r2__01_b.zip", "requestId": "r2", "runId": "B", "videoId": "VID1", "packs": [{"path": "b.mp4"}]},
                {"at": 3, "zip": "r3__01_c.zip", "requestId": "r3", "runId": "C", "videoId": "VID2", "packs": [{"path": "c.mp4"}]}]
        with open(os.path.join(self.tmp, D.LOG), "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        ranges = {"a.mp4": (100.0, 160.0), "b.mp4": (150.0, 400.0), "c.mp4": (100.0, 160.0)}.get
        hit = D.overlaps(self.tmp, "VID1", (110.0, 170.0), run_id="NEW", ranges=ranges)
        self.assertEqual([(h["zip"], h["share"]) for h in hit], [("r1__01_a.zip", 0.83)])   # b は 20/60 = 1/3(半分未満)・c は別の配信
        self.assertEqual(D.overlaps(self.tmp, "VID1", (110.0, 170.0), run_id="A", ranges=ranges), [])   # 同じ実行(作り直し)は数えない
        D.OVERLAP_ON = False
        self.addCleanup(setattr, D, "OVERLAP_ON", True)
        self.assertEqual(D.overlaps(self.tmp, "VID1", (110.0, 170.0), ranges=ranges), [])

    def test_switched_off(self):
        self.assertTrue(DL.switched_off({"YTT_AUTO_SEND": " OFF "}))
        self.assertFalse(DL.switched_off({"YTT_AUTO_SEND": "on"}))
        self.assertFalse(DL.switched_off({}))

    def test_friend_feedback_is_thin_forward(self):
        from human.friend import friend_feedback as F
        self.assertEqual(F.DELIVERIES_LOG, D.LOG)
        row = F.record_delivery(self.tmp, "z.zip", FakeRun("V9", "r9"), ["d"], None, "auto")
        self.assertEqual((row["origin"], "endedAt" in row), ("auto", False))
        self.assertEqual(F.find_delivery(self.tmp, "z.zip")["videoId"], "V9")
        self.assertEqual(F.record_delivery(self.tmp, "y.zip", FakeRun(), [])["origin"], "request", "既定は request")

    def test_delivered_marks(self):
        """切り抜きごとの届けた(MARKS-3。案件の一覧と 3 日の片付けが引く): 配信とマークで・配信かマークの空の行はパックのフォルダの名前で・
        同じ切り抜きは新しい方・全文を読む(末尾の MAX_SCAN の外も)・変わったときだけ読み直す・無ければ空・読めなければ None・実行の形 mode"""
        self.assertEqual(D.delivered_marks(self.tmp), ({}, {}), "記録が無い = まだ何も届けていない")
        full = FakeRun("V1")
        full.mode = "full"
        D.record(self.tmp, "a.zip", full, ["x/p1_pack"], {"x/p1_pack": {"path": "p1.mp4", "markId": "m1"}}, "auto")
        self.assertEqual(D.rows(self.tmp)[0]["mode"], "full")
        self.assertEqual(D.record(self.tmp, "b.zip", FakeRun("V1"), ["x/P2_pack/"], None, "manual")["mode"], "", "実行の形が無い(手で届けた)は空")
        D.record(self.tmp, "c.zip", FakeRun("V1"), ["y/p1_pack"], {"y/p1_pack": {"path": "p1.mp4", "markId": "m1"}}, "manual")
        by_mark, by_pack = D.delivered_marks(self.tmp)
        self.assertEqual(set(by_mark), {("V1", "m1")})
        self.assertEqual((by_mark[("V1", "m1")]["zip"], by_mark[("V1", "m1")]["origin"], by_mark[("V1", "m1")]["mode"]), ("c.zip", "manual", ""), "二度届けたら新しい方")
        self.assertEqual(list(by_pack), [D.pack_name("p2_pack")], "配信とマークの分かる行はパックの名前に入れない")
        self.assertEqual((by_pack["p2_pack"]["videoId"], by_pack["p2_pack"]["markId"], by_pack["p2_pack"]["zip"]), ("V1", "", "b.zip"))
        self.assertIs(D.delivered_marks(self.tmp)[0], by_mark, "変わっていなければ覚えた物")
        with open(os.path.join(self.tmp, D.LOG), "a", encoding="utf-8") as f:
            f.write("ゴミ\n" + '{"at": 5, "zip": "z.zip", "videoId": "V2", "packs": [{"dir": "q_pack", "markId": "m9"}]}\n' + "x" * (D.MAX_SCAN + 10) + "\n")
        got = D.delivered_marks(self.tmp)[0]
        self.assertEqual((sorted(got), got[("V2", "m9")]["origin"], got[("V2", "m9")]["mode"]), ([("V1", "m1"), ("V2", "m9")], "auto", ""))
        self.assertIn(("V1", "m1"), got, "全文を読む(末尾の上限の外の行も)")
        from unittest import mock
        with mock.patch.object(D.os, "stat", side_effect=PermissionError("x")):
            self.assertIsNone(D.delivered_marks(self.tmp), "読めない = 届けたかが分からない")

    def test_not_sent_marks(self):
        """送らなかった記録(ds1): 同じ切り抜きは新しい方・壊れた行と配信 / マーク / 理由の無い行は読み飛ばす・無ければ {}"""
        self.assertEqual(D.not_sent_marks(self.tmp), {})
        self.assertEqual(D.not_sent_marks(None), {})
        D.record_not_sent(self.tmp, "v1", "m1", "stale", "古い", run_id="r1")
        with open(os.path.join(self.tmp, D.NOT_SENT_LOG), "a", encoding="utf-8") as f:
            f.write("{壊れた\n" + json.dumps({"at": 1, "videoId": "", "markId": "m2", "code": "x"}) + "\n" + json.dumps({"at": 1, "videoId": "v1", "markId": "m3"}) + "\n")
        D.record_not_sent(self.tmp, "v1", "m1", "expired", "切れた")
        got = D.not_sent_marks(self.tmp)
        self.assertEqual(list(got), [("v1", "m1")])
        self.assertEqual((got[("v1", "m1")]["code"], got[("v1", "m1")]["text"]), ("expired", "切れた"))


if __name__ == "__main__":
    unittest.main()
