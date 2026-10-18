# -*- coding: utf-8 -*-
"""3 択の口(human/proof/machpick と layers.mach_changes・pick。RS8 O2-4)のテスト。

    py -3.12 -m unittest src/human/proof/tests/test_machpick.py -v

機械の結果が変わって人の直しと食い違う行(印 MACH_CHANGED)の 前の機械・今の機械・人の直しを返す・[自分の直しのまま] / [今の機械にする] を選ぶ。
"""
import copy
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import layers as L, machpick, store  # noqa: E402
from ytt import errors, workdata  # noqa: E402
from human.tests._workdata import temporary_workdata  # noqa: E402
from ytt import testkit  # noqa: E402

TID = "0123456789ab"
META = {"schema": "transcribe/v1", "id": TID, "title": "t", "updatedAt": 1}


def mrow(i, a, text, flag=""):
    return {"id": "s%d" % i, "start": a, "end": a + 1.0, "text": text, "flag": flag}


def machine(rows, rev=1):
    return {"schema": L.MACH_SCHEMA, "rev": rev, "keys": {}, "rows": rows, "speakers": []}


M1 = machine([mrow(1, 0.0, "あ"), mrow(2, 2.0, "い"), mrow(3, 4.0, "う")])


def edited():
    d = L.compose(M1, None, META)
    d["segments"][1].update(text="いー", proofed=True)
    return d, L.diff(M1, d)


class LayersPickTest(unittest.TestCase):
    def test_changes_lists_before_now_human(self):
        d, hum = edited()
        self.assertEqual(L.mach_changes(M1, hum), [])   # 機械が変わっていない
        m2 = copy.deepcopy(M1)
        m2["rev"] = 2
        m2["rows"][1]["text"] = "いい"
        got = L.mach_changes(m2, hum)
        self.assertEqual(len(got), 1)
        x = got[0]
        self.assertEqual((x["id"], x["human"]["text"], x["human"]["proofed"]), ("s2", "いー", True))
        self.assertEqual([r["text"] for r in x["before"]], ["い"])
        self.assertEqual([r["text"] for r in x["now"]], ["いい"])
        self.assertEqual(L.mach_changes(m2, hum, "s1"), [])

    def test_pick_mine_and_machine(self):
        d, hum = edited()
        m2 = copy.deepcopy(M1)
        m2["rev"] = 2
        m2["rows"][1]["text"] = "いい"
        mine = L.pick(m2, hum, "s2", "mine")
        out = L.compose(m2, mine, META)
        g = out["segments"][1]
        self.assertEqual((g["text"], g["flag"]), ("いー", ""))   # 自分の直しのまま・印は外れる
        self.assertEqual(L.mach_changes(m2, mine), [])
        self.assertEqual(hum["rows"][0]["base"]["rows"][0]["text"], "い")   # 元の人の層は書き換えない
        m3 = copy.deepcopy(m2)   # 次に機械が変わればまた印
        m3["rev"] = 3
        m3["rows"][1]["text"] = "いいい"
        self.assertEqual([x["id"] for x in L.mach_changes(m3, mine)], ["s2"])
        mach = L.pick(m2, hum, "s2", "machine")
        out = L.compose(m2, mach, META)
        self.assertEqual([g["text"] for g in out["segments"]], ["あ", "いい", "う"])   # 今の機械
        self.assertNotIn("proofed", out["segments"][1])
        self.assertEqual(mach["rows"], [])
        with self.assertRaises(KeyError):
            L.pick(m2, hum, "s1", "mine")
        with self.assertRaises(ValueError):
            L.pick(m2, hum, "s2", "both")
        # 前の機械を引き継いだ行(保存し直しても印が残る = flag に印を持つ)も、自分の直しのまま で印が外れる
        out = L.compose(m2, hum, META)
        hum2 = L.diff(m2, out, hum)   # 印を残したまま保存した
        self.assertIn(L.MACH_CHANGED, next(h for h in hum2["rows"] if h["id"] == "s2")["flag"])
        mine = L.pick(m2, hum2, "s2", "mine")
        self.assertEqual(L.compose(m2, mine, META)["segments"][1]["flag"], "")


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import serve   # 読み込むときに作業データの場所を決めるので、setUp の差し替えより前に
        cls.S = serve

    def setUp(self):
        self.tmp = temporary_workdata(self, "machpick-")
        d = L.compose(M1, None, META)
        store.commit(TID, d, why="whole")
        d = store.read_transcript(TID)
        d["segments"][1].update(text="いー", proofed=True)
        store.commit(TID, d, why="save")
        mp = os.path.join(workdata.TX_DIR, TID + ".mach.json")   # ② が機械の層だけを書き換えた
        m = testkit.read_json(mp)
        m["rev"] += 1
        m["rows"][1]["text"] = "いい"
        testkit.write_json(mp, m)

    def test_changes_and_pick_mine(self):
        r = machpick.changes(TID)
        self.assertEqual([x["id"] for x in r["rows"]], ["s2"])
        self.assertNotIn("layers", r)   # 層のモードは無くなった(10-18 決定 3-61 pp2 = B)
        self.assertEqual(r["rows"][0]["now"][0]["text"], "いい")
        self.assertEqual(machpick.changes(TID, "s1")["rows"], [])
        with self.assertRaises(errors.ApiError) as cm:
            machpick.pick({"id": TID, "row": "s2", "pick": "mine", "baseUpdatedAt": 1})
        self.assertEqual(cm.exception.status, 409)
        out = machpick.pick({"id": TID, "row": "s2", "pick": "mine", "baseUpdatedAt": r["updatedAt"]})
        self.assertEqual((out["ok"], out["pick"]), (True, "mine"))
        d = store.read_transcript(TID)
        self.assertEqual((d["segments"][1]["text"], d["segments"][1]["flag"]), ("いー", ""))
        self.assertEqual(machpick.changes(TID)["rows"], [])
        with self.assertRaises(errors.ApiError) as cm:
            machpick.pick({"id": TID, "row": "s2", "pick": "mine"})
        self.assertEqual(cm.exception.status, 404)

    def test_pick_machine(self):
        with mock.patch.object(store, "snapshot", wraps=store.snapshot) as snap:
            machpick.pick({"id": TID, "row": "s2", "pick": "machine"})
        snap.assert_called_once_with(TID, True)   # 前の履歴から 10 分経っていなくても必ず残す(P-PRIMARY = 1f-3。人の直しを丸ごと外すため)
        d = store.read_transcript(TID)
        self.assertEqual([g["text"] for g in d["segments"]], ["あ", "いい", "う"])
        self.assertNotIn("proofed", d["segments"][1])
        self.assertEqual(d["composedFrom"]["mach"], 2)

    def test_bad_request(self):
        for bad in ({"id": TID, "row": "s2", "pick": "x"}, {"id": TID, "pick": "mine"}):
            with self.assertRaises(errors.ApiError) as cm:
                machpick.pick(bad)
            self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(errors.ApiError) as cm:   # 印の無い行
            machpick.pick({"id": TID, "row": "s1", "pick": "mine"})
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "not_changed"))

    def test_routes(self):
        S = self.S
        self.assertIn("/api/mach-changes", S.GET_API)
        self.assertIn("/api/mach-changes/pick", S.POST_API)
        self.assertEqual([x["id"] for x in S.GET_API["/api/mach-changes"](lambda k, d=None: {"id": TID}.get(k, d))["rows"]], ["s2"])


if __name__ == "__main__":
    unittest.main()
