"""ホームの「友人の依頼」の行(src/app/homereq.py): 受付の記録と実行の記録を結んで、札・済んだ・案件の画面への道を決める。
実行(リポジトリ直下から): python -m unittest tests/app/test_homereq.py -v
"""
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


if __name__ == "__main__":
    unittest.main()
