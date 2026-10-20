"""「確かめる」の待ち行列の順と数え方(src/app/check/lineup.py・goals.py)の単体テスト。純粋な関数だけ。

実行(リポジトリ直下から): py -3.12 -m unittest src/app/check/tests/test_lineup.py -v
"""
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> eval -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eval.check import goals  # noqa: E402
from app.check import lineup  # noqa: E402
from eval.drill import accuracy  # noqa: E402


def card(kind, key, order=(0,), source="x"):
    return {"id": lineup.card_id(kind, source, key), "kind": kind, "source": source, "_order": list(order)}


def goal(gid, now, target, reached=None):
    left = None if now is None else max(0, target - now)
    return {"id": gid, "now": now, "target": target, "left": left, "reached": (now is not None and now >= target) if reached is None else reached}


class CardIdTest(unittest.TestCase):
    def test_round_trip(self):
        cid = lineup.card_id("voice", "diar", "0123456789ab", "s12")
        self.assertEqual(cid, "voice:diar:0123456789ab#s12")
        self.assertEqual(lineup.parse_id(cid), ("voice", "diar", "0123456789ab#s12"))

    def test_bad_ids(self):
        for bad in (None, 3, "", "talk:diar:x", "voice:Diar:x", "voice:diar:", "voice:diar:a/b", "voice:diar:" + "x" * 161, "voice:diar:a b"):
            self.assertIsNone(lineup.parse_id(bad), bad)

    def test_check_n(self):
        self.assertEqual(lineup.check_n(None), 10)
        self.assertEqual(lineup.check_n("0"), 0)
        self.assertEqual(lineup.check_n(50), 50)
        for bad in ("-1", "51", "x", 1.5j):
            with self.assertRaises(ValueError):
                lineup.check_n(bad)


class OrderTest(unittest.TestCase):
    def test_nearest_goal_first_reached_last(self):
        cards = [card("value", "a"), card("read", "b"), card("voice", "c"), card("time", "d")]
        gk = {"value": goal("marks", 1, 10), "read": goal("fill", 27, 30), "voice": goal("speakers", 200, 200), "time": goal("timing", None, 100)}
        got = [c["kind"] for c in lineup.order(cards, gk)]
        self.assertEqual(got, ["read", "value", "time", "voice"])   # あと 10% → 90% → 未測定 → 届いた

    def test_light_first_on_tie_and_inner_order(self):
        cards = [card("time", "t"), card("read", "r2", (5,)), card("read", "r1", (1,)), card("value", "v")]
        got = [c["id"] for c in lineup.order(cards, {})]
        self.assertEqual(got, ["value:x:v", "read:x:r1", "read:x:r2", "time:x:t"])

    def test_skipped_go_last_in_skip_order(self):
        cards = [card("value", "a"), card("value", "b"), card("read", "c")]
        got = [c["id"] for c in lineup.order(cards, {}, later=["value:x:b", "value:x:a"])]
        self.assertEqual(got, ["read:x:c", "value:x:b", "value:x:a"])

    def test_bad_order_values_do_not_break(self):
        cards = [card("read", "a", (float("nan"),)), card("read", "b", ("x",)), {"id": "read:x:c", "kind": "read"}]
        self.assertEqual(len(lineup.order(cards, {"read": "not a goal"})), 3)

    def test_per_kind_and_public(self):
        self.assertEqual(lineup.per_kind([card("read", "a"), card("read", "b"), card("time", "c")]), {"value": 0, "read": 2, "voice": 0, "time": 1, "speech": 0, "cut": 0})
        self.assertEqual(lineup.per_kind([card("section", "a")], lineup.EVAL_KINDS), {"section": 1})   # 評価のレーン(C-EVAL)
        self.assertNotIn("_order", lineup.public(card("read", "a")))

    def test_first_is_the_head_of_order(self):
        """件数だけの問い合わせは並べずに先頭だけ(O14)= order の先頭と同じ"""
        cards = [card("time", "t"), card("read", "r2", (2,)), card("read", "r1", (1,)), card("value", "v")]
        for later in ((), ("value:x:v",)):
            self.assertEqual(lineup.first(cards, {}, later), lineup.order(cards, {}, later)[0])
        self.assertIsNone(lineup.first([]))


class GoalsTest(unittest.TestCase):
    def rows(self):
        return [{"kind": "value", "source": "auto", "case": "v1", "at": 100}, {"kind": "value", "source": "cand", "case": "v1", "at": 300},
                {"kind": "value", "source": "cand", "case": "v2", "at": 300}, {"kind": "read", "source": "fill", "at": 50},
                {"kind": "read", "source": "fill", "at": 500}, {"kind": "voice", "source": "diar", "at": 10}, {"kind": "time", "source": "row", "at": 10}]

    def test_counts(self):
        f = goals.extra_counter(self.rows())
        self.assertEqual(f("marks", None), 2)       # 配信の単位(v1・v2)
        self.assertEqual(f("marks", 200), 2)        # 測定より後: v1(300)・v2
        self.assertEqual(f("marks", 400), 0)
        self.assertEqual(f("fill", 100), 1)         # 測定より後の 1 件だけ(道具が前の分を数える)
        self.assertEqual(f("speakers", 10 ** 15), 1)   # all = 道具が数えない → 全部
        self.assertEqual(f("timing", None), 1)
        self.assertEqual(f("alt", None), 0)

    def test_goals_of_adds_check(self):
        last = {"areas": {"fill": {"latest": {"at": 100, "summary": {"judged": 10}}}}}
        got = {g["id"]: g for g in accuracy.goals_of(last, extra=goals.extra_counter(self.rows()))}
        self.assertEqual((got["fill"]["now"], got["fill"]["check"], got["fill"]["left"]), (11, 1, 19))
        self.assertEqual((got["timing"]["now"], got["timing"]["check"]), (1, 1))   # 未測定でも答えがあれば数える
        self.assertEqual((got["alt"]["now"], got["alt"]["check"]), (None, 0))
        plain = {g["id"]: g for g in accuracy.goals_of(last)}
        self.assertEqual((plain["fill"]["now"], plain["fill"]["check"]), (10, 0))

    def test_every_kind_has_a_goal(self):
        ids = {g["id"] for g in accuracy.GOALS}
        for kind in ("value", "read", "voice", "time"):
            self.assertIn(goals.goal_of(kind), ids)
        for kind in ("speech", "cut", "section"):   # 目標の無い種類(C-EVAL。並びは目標の無い種類の場所)
            self.assertIsNone(goals.goal_of(kind))
        for (_k, _s), gid in goals.KIND_GOAL.items():
            self.assertIn(gid, ids)
            self.assertIn(gid, goals.COUNT)

    def test_view_and_by_kind(self):
        gl = [dict(goal("fill", 3, 30), label="L", opens="O", unit="行"), goal("marks", 1, 10)]
        bk = goals.by_kind(gl)
        self.assertEqual(sorted(bk), ["read", "value"])
        v = goals.view(bk["read"], "read")
        self.assertEqual((v["kind"], v["id"], v["left"], v["label"], v["reached"]), ("read", "fill", 27, "L", False))
        self.assertIsNone(goals.view(None, "time"))


if __name__ == "__main__":
    unittest.main()
