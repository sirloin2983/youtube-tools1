# -*- coding: utf-8 -*-
"""人の判断の記録(human/judgments)のテスト: 書いて読む・壊れた行・key の重複・fold の 3 レーンと retract と時刻順・.old・知らない what"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests → human → src
from human import judgments as J  # noqa: E402
from ytt import testkit  # noqa: E402


class JudgmentsTest(unittest.TestCase):
    def setUp(self):
        self.d = testkit.tempdir(self, "jdg-")

    def rec(self, key, what="adopt", at=1000, **kw):
        base = {"videoId": "v1", "markId": "m1", "origin": "manual", "via": "review", "key": key, "at": at, "what": what}
        base.update(kw)
        return J.record(self.d, **base)

    def test_write_and_read(self):
        r = self.rec("k1", start=1.5, end=9, ref={"zip": "a.zip", "x": 1})
        self.assertEqual((r["v"], r["who"], r["ref"]), (1, "self", {"zip": "a.zip"}))
        self.assertRegex(r["id"], r"^j\d{13}-[0-9a-f]{6}$")
        self.assertEqual(J.rows(self.d), [r])
        self.assertEqual(J.keys(self.d), {"k1"})
        self.assertEqual(self.rec("k2", "made_video")["who"], "friend")

    def test_rejects(self):
        for args, kw in ((("k", "like"), {}), (("k", "made_video"), {"who": "self"}), (("k", "quality_good"), {"who": "friend"}),
                         (("k", "adopt"), {"reason": "boring"}), (("k", "retract"), {}), (("k",), {"via": "nowhere"})):
            with self.subTest(args=args, kw=kw), self.assertRaises(ValueError):
                self.rec(*args, **kw)
        self.assertEqual(J.rows(self.d), [])

    def test_broken_lines_skipped(self):
        self.rec("k1")
        with open(J.path(self.d), "ab") as f:
            f.write(b'{"what": "adopt", "bro\n\xff\xfe\n[1]\n')
        self.rec("k2", at=2000)
        self.assertEqual([r["key"] for r in J.rows(self.d)], ["k1", "k2"])

    def test_duplicate_key(self):
        a = self.rec("k1", at=1000)
        self.rec("k1", "reject", at=2000)
        self.assertEqual(J.rows(self.d), [a])

    def test_old_file(self):
        o = self.rec("k1", at=1000)
        os.replace(J.path(self.d), J.path(self.d) + ".old")
        n = self.rec("k2", at=2000)
        self.assertEqual(J.rows(self.d), [o, n])

    def test_spill_to_old(self):
        self.rec("k1")
        saved = J.MAX_BYTES
        J.MAX_BYTES = 10
        self.addCleanup(setattr, J, "MAX_BYTES", saved)
        self.rec("k2", at=2000)
        self.assertTrue(os.path.exists(J.path(self.d) + ".old"))
        self.assertEqual(len(J.rows(self.d)), 2)

    def test_fold_lanes_and_order(self):
        a1 = self.rec("a1", "adopt", at=3000)
        self.rec("a0", "reject", at=1000)        # 古い方が後から書かれても時刻順
        q = self.rec("q", "quality_bad", at=2000, reason="boring")
        f = self.rec("f", "made_video", at=2500)
        other = J.record(self.d, videoId="v2", markId="m9", what="reject", origin="auto", via="review", key="o", at=10)
        t = J.fold(J.rows(self.d))
        self.assertEqual(t[("v1", "m1")], {"adopt": a1, "quality": q, "friend": f})
        self.assertEqual(t[("v2", "m9")]["adopt"], other)
        self.assertIsNone(t[("v2", "m9")]["friend"])

    def test_fold_retract(self):
        a = self.rec("a", "adopt", at=1000)
        q = self.rec("q", "quality_good", at=1100)
        self.rec("r", "retract", at=2000, of=a["id"])
        t = J.fold(J.rows(self.d))[("v1", "m1")]
        self.assertEqual((t["adopt"], t["quality"]), (None, q))
        b = self.rec("b", "reject", at=3000)
        self.rec("r2", "retract", at=4000, of=a["id"])   # 古い行の取り消しは新しい判断を消さない
        self.assertEqual(J.fold(J.rows(self.d))[("v1", "m1")]["adopt"], b)
        fr = self.rec("f", "adopt", at=5000, who="friend")
        self.rec("r3", "retract", at=6000, of=fr["id"])
        t = J.fold(J.rows(self.d))[("v1", "m1")]
        self.assertEqual((t["friend"], t["adopt"]), (None, b))

    def test_friend_value_maps_old_and_new(self):
        f = lambda what: {"who": "friend", "what": what}   # noqa: E731
        self.assertEqual([J.friend_value(f(w)) for w in ("good", "bad", "unknown", "adopt", "made_video", "reject")],
                         ["good", "bad", "unknown", "good", "good", "unknown"])
        self.assertIsNone(J.friend_value({"who": "self", "what": "adopt"}))
        self.assertIsNone(J.friend_value(None))

    def test_friend_bad_reason_and_unknown_by_auto(self):
        b = self.rec("b", "bad", at=1000, who="friend", origin="request", via="friend_verdict", reason="boring", ref={"pack": "p1"})
        self.assertEqual((b["reason"], J.friend_value(b)), ("boring", "bad"))
        c = self.rec("c", "bad", at=1100, who="friend", origin="request", via="friend_verdict", reason="cut", markId="m2")
        self.assertEqual(c["reason"], "cut")
        u = self.rec("u", "unknown", at=1200, who="friend", origin="auto", via="friend_verdict", by="auto", markId="m3")
        self.assertEqual((u["by"], J.friend_value(u)), ("auto", "unknown"))
        with self.assertRaises(ValueError):
            self.rec("x", "good", who="friend", reason="boring")   # reason は bad だけ
        with self.assertRaises(ValueError):
            self.rec("y", "unknown", who="friend", by="self")   # by は auto だけ
        with self.assertRaises(ValueError):
            self.rec("z", "unknown", who="friend", origin="request", via="friend_verdict", of="x")   # of は retract だけ

    def test_quality_unknown_lane(self):
        q = self.rec("qu", "quality_unknown", at=1000)
        self.assertEqual((q["what"], q["who"]), ("quality_unknown", "self"))
        self.assertEqual(J.fold(J.rows(self.d))[("v1", "m1")]["quality"], q)
        g = self.rec("qg", "quality_good", at=2000)
        self.assertEqual(J.fold(J.rows(self.d))[("v1", "m1")]["quality"], g)   # 後の答えが勝つ
        with self.assertRaises(ValueError):
            self.rec("qx", "quality_unknown", who="friend")


if __name__ == "__main__":
    unittest.main()
