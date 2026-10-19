# -*- coding: utf-8 -*-
"""flow/sendpolicy.py(友人へ自動で送る判定。D-SEND の段 1)と flow/deliveries.py の読み口のうち、通しでは起こせない物:
時刻の境目(時計を差し替える)・配信の付加情報の形(ネットの相手)・前の版の行と壊れた行・読めない記録。
届けた記録を書いて読む正しく動く道は src/flow/tests/test_deliver.py の DeliverRun。 py -3.12 -m unittest src/flow/tests/test_sendpolicy.py -v"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from flow import deliveries as D, sendpolicy as P  # noqa: E402

NOW = 1_800_000_000.0
H = 3600


class TestDecide(unittest.TestCase):
    def test_decide(self):
        """送る・送らない・理由の全部(五つの道・境目の 48 時間と判定の順・依頼と手の出どころは必ず送る)"""
        fresh = NOW - 2 * H
        cases = [
            # (名前, origin, 終わった時刻, 依頼の有無, チェック済み, 答え)
            ("fresh_sends", "auto", fresh, False, True, (True, None)),
            ("unchecked", "auto", fresh, False, False, (False, "unchecked")),
            ("requested", "auto", fresh, True, True, (False, "requested")),
            ("unknown_end", "auto", None, False, True, (False, "unknown_end")),
            ("stale", "auto", NOW - 49 * H, False, True, (False, "stale")),
            ("exactly_48h_sends", "auto", NOW - P.FRESH_SEC, False, True, (True, None)),   # ちょうど 48 時間は送る
            ("48h_plus_1s_stale", "auto", NOW - P.FRESH_SEC - 1, False, True, (False, "stale")),
            ("future_is_fresh", "auto", NOW + 5, False, True, (True, None)),   # 未来は新しい扱い
            ("unchecked_first", "auto", NOW - 99 * H, True, False, (False, "unchecked")),   # チェックが先
            ("requested_before_stale", "auto", NOW - 99 * H, True, True, (False, "requested")),   # 依頼が古さより先
            ("end_zero", "auto", 0, False, True, (False, "unknown_end")),
            ("end_negative", "auto", -1, False, True, (False, "unknown_end")),
            ("end_bool", "auto", True, False, True, (False, "unknown_end")),
            ("end_str", "auto", "x", False, True, (False, "unknown_end")),
            ("request_none_end", "request", None, True, False, (True, None)),
            ("request_old", "request", NOW - 999 * H, True, False, (True, None)),
            ("manual_none_end", "manual", None, True, False, (True, None)),
            ("manual_old", "manual", NOW - 999 * H, True, False, (True, None)),
        ]
        for name, origin, ended, requested, checked, want in cases:
            with self.subTest(name):
                self.assertEqual(P.decide(origin, ended, NOW, requested, checked), want)
        # 送らなかった理由の文(経過時間が文に入る)・開発機の守りのスイッチ
        self.assertIn("50", P.reason_text("stale", hours=50))
        self.assertEqual(P.reason_text("unchecked"), P.REASONS["unchecked"])
        self.assertEqual(P.reason_text("zzz"), "zzz")
        self.assertEqual(P.hours_since(NOW - 50 * H - 30, NOW), 50)
        self.assertEqual(P.hours_since(NOW + 9, NOW), 0)
        for code in ("unchecked", "stale", "requested", "expired", "unknown_end"):
            self.assertIn(code, P.REASONS)
        self.assertTrue(P.switched_off({"YTT_AUTO_SEND": " OFF "}))
        self.assertFalse(P.switched_off({"YTT_AUTO_SEND": "on"}))
        self.assertFalse(P.switched_off({}))


class TestEndedAt(unittest.TestCase):
    def test_ended_at_of(self):
        good = {"releaseTs": 1000, "duration": 500}
        cases = [(st, dict(good, liveStatus=st), 1500.0) for st in ("was_live", "post_live")]
        cases += [(repr(a), a, None) for a in (
            None, "x", {}, {"liveStatus": "not_live", "releaseTs": 1000, "duration": 500},
            {"liveStatus": "is_live", "releaseTs": 1000, "duration": 500},
            {"liveStatus": "was_live", "duration": 500}, {"liveStatus": "was_live", "releaseTs": 1000},
            {"liveStatus": "was_live", "releaseTs": 0, "duration": 500}, {"liveStatus": "was_live", "releaseTs": 1000, "duration": 0},
            {"liveStatus": "was_live", "releaseTs": "1000", "duration": 500}, {"liveStatus": "was_live", "releaseTs": True, "duration": 500})]
        for name, a, want in cases:
            with self.subTest(name):
                self.assertEqual(P.ended_at_of(a), want)


class FakeRun:
    def __init__(self, vid="VID1", rid=""):
        self.request_id, self.id, self.video_id, self.title = rid, "run0000001", vid, "題"


class TestDeliveries(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliv-")

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
