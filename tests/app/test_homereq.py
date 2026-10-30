"""ホームの「友人の依頼」の行(src/app/homereq.py): 受付の記録と実行の記録を結んで、札・済んだ・案件の画面への道を決める。
実行(リポジトリ直下から): python -m unittest tests/app/test_homereq.py -v
"""
import io
import os
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import homereq as H  # noqa: E402

NOW = 2000000000000
DAY = 86400000


def req(rid, kind="url", state="accepted", runs=(), received=NOW - 3600000, **kw):
    return dict({"id": rid, "kind": kind, "title": "題 " + rid, "state": state, "received": received, "runIds": list(runs)}, **kw)


class RowsTest(unittest.TestCase):
    def test_states_and_links(self):
        runs = [{"id": "r1", "state": "running", "videoId": "vidAAAAAAAA"},
                {"id": "r2", "state": "done", "videoId": "vidBBBBBBBB", "steps": [{"key": "deliver", "state": "done"}]},
                {"id": "r3", "state": "done", "docId": "doc000000001"},
                {"id": "r4", "state": "error", "videoId": "vidCCCCCCCC"}]
        rows = H.rows([req("a", runs=["r1"]), req("b", runs=["r2"]), req("c", kind="video", runs=["r3"]), req("d", runs=["r4"]),
                       req("e"), req("f", state="rejected", reason="URL ではありません"), req("g", kind="feedback"),
                       req("h", runs=["r2"], received=NOW - 4 * DAY)], runs, NOW)
        by = {r["id"]: r for r in rows}
        self.assertNotIn("g", by)   # 友人の返事は依頼ではない
        self.assertEqual({k: by[k]["state"] for k in "abcdefh"},
                         {"a": "making", "b": "sent", "c": "done", "d": "error", "e": "received", "f": "rejected", "h": "sent"})
        self.assertEqual((by["a"]["link"], by["c"]["link"]), ({"c": "vidAAAAAAAA", "tab": "cand"}, {"d": "doc000000001", "tab": "proof"}))
        self.assertEqual((by["e"]["link"], by["e"]["why"], by["f"]["why"]), (None, "まだ実行が始まっていない", "断った依頼"))
        self.assertEqual([k for k in "abcdefh" if by[k]["done"]], ["h"])   # 済んだ = 送った・断ったなどで 3 日たった

    def test_live_link_from_record_and_book(self):
        rows = H.rows([req("n", kind="live", live={"recorder": "local", "recording": "20261024-120000-abcdefghijk"}),
                       req("o", kind="live", requestId="20261023-1"), req("p", kind="live", title="古い配信", received=NOW - 3600000),
                       req("q", kind="live")], [], NOW,
                      book={"local/20261023-170000-x": {"rid": "20261023-1", "title": "別の題"},
                            "local/20261023-180000-y": {"rid": "z", "title": "古い配信", "createdAt": (NOW - 3500000) / 1000}})
        by = {r["id"]: r for r in rows}
        self.assertEqual(by["n"]["link"], {"c": "20261024-120000-abcdefghijk", "tab": "cand", "live": True})
        self.assertEqual(by["o"]["link"]["c"], "20261023-170000-x")   # 依頼の id で引く
        self.assertEqual(by["p"]["link"]["c"], "20261023-180000-y")   # 古い依頼は題名と時刻の近さで
        self.assertEqual((by["q"]["link"], by["q"]["why"]), (None, "録画の記録が無い(古い依頼)"))
        self.assertEqual(by["n"]["state"], "live")

    def test_live_after_recording_ended(self):
        """録画が終わったら道は動画の id の案件へ・札は届けた記録で 送った / 候補なし(録画中は録画の案件・ライブのまま)"""
        rec = {"recorder": "local", "recording": "20261024-193147-N3z6TI4ED7o"}
        reqs = [req("s", kind="live", live=rec, requestId="20261024-193027-fe9dc7"), req("t", kind="live", live=rec, requestId="20261024-000000-aaaaaa")]
        on = {r["id"]: r for r in H.rows(reqs, [], NOW, active={"local/20261024-193147-N3z6TI4ED7o"})}
        self.assertEqual((on["s"]["state"], on["s"]["link"]["c"]), ("live", "20261024-193147-N3z6TI4ED7o"))
        off = {r["id"]: r for r in H.rows(reqs, [], NOW, active=set(), delivered={"20261024-193027-fe9dc7": 1.0})}
        self.assertEqual(off["s"]["link"], {"c": "N3z6TI4ED7o", "rec": "20261024-193147-N3z6TI4ED7o", "tab": "cand", "ended": True})
        self.assertEqual((off["s"]["state"], off["t"]["state"], off["t"]["label"]), ("sent", "nocand", "候補なし"))

    def test_ended_live_link_keeps_recording_id(self):
        """10-30 の不具合: 録画が終わっても案件の一覧は録画の id(<日付>-<時刻>-<動画 id>)のまま載ることがある。
        道に録画の id(rec)も持たせ、画面(portal.js の freqGo)は動画の id・録画の id の両方で照らす = どちらかにあれば開ける"""
        rec = {"recorder": "local", "recording": "20261030-171348-FI1HuollS5U"}
        row = H.rows([req("j", kind="live", live=rec, requestId="20261030-171200-abcdef")], [], NOW, active=set())[0]
        self.assertEqual((row["link"]["c"], row["link"]["rec"]), ("FI1HuollS5U", "20261030-171348-FI1HuollS5U"))
        js = io.open(os.path.join(os.path.dirname(H.__file__), "ui", "home", "portal.js"), encoding="utf-8").read()
        go = js[js.index("function freqGo("):js.index("function freqRow(")]
        self.assertIn("caseById(l.rec)", go)

    def test_failed_run_later_delivered_by_original_id(self):
        """実行は失敗でも、元の依頼 id で後から届けた(後追い・引き継ぎ)なら 送った"""
        reqs = [req("u", runs=("r1",), requestId="20261025-010203-abcdef")]
        runs = [{"id": "r1", "state": "error"}]
        self.assertEqual(H.rows(reqs, runs, NOW)[0]["state"], "error")
        self.assertEqual(H.rows(reqs, runs, NOW, delivered={"20261025-010203-abcdef": 1.0})[0]["state"], "sent")



class TestPortalWaits(unittest.TestCase):
    def test_slow_reads_wait_like_case_page(self):
        """10-30: 起き直した直後は案件の一覧・確かめるのカードが 8 秒を超え、ホームが「読めませんでした」のまま止まっていた。
        ホームはこの 2 つを案件の画面と同じ 60 秒まで待つ(既定の GET 8 秒に戻さない)"""
        js = io.open(os.path.join(os.path.dirname(H.__file__), "ui", "home", "portal.js"), encoding="utf-8").read()
        self.assertIn("var SLOW_GET_MS = 60000;", js)
        self.assertEqual(js.count("api(CASES_API, 'GET', null, { timeout: SLOW_GET_MS })"), 2)
        self.assertIn("api('api/check/next?n=0', 'GET', null, { timeout: SLOW_GET_MS })", js)
        self.assertNotIn("api(CASES_API)", js)

if __name__ == "__main__":
    unittest.main()
