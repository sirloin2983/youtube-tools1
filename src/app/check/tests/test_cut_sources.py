"""「確かめる」の自動カットのカードの出どころ(src/app/check/cut_sources.py)の単体テスト: スイッチが切れていれば空・評価用の文書は出ない・
たたき台の出どころ(rows・silence 以外)と残す区間が 2 つ未満は出ない・切れ目は頭・真ん中・末・消した所は 2 秒以上だけ・仕上がりは合計 120 秒以下だけ・
1 本 5 枚まで・id が読める。一時フォルダの文書と .edit.json だけを使う。

実行(リポジトリ直下から): py -3.10 -m unittest src/app/check/tests/test_cut_sources.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT

from app.check import cut_sources, lineup, sources  # noqa: E402
from human.check import apply, cutcard  # noqa: E402

DOC = "dddddddddddd"        # 3 切れ目・2 秒の消した所・仕上がり(120 秒以下)
SHORT = "ffffffffffff"      # 切れ目 1 つ・消した所は 1 秒・残しが 120 秒を超える
EVAL_DOC = "eeeeeeeeeeee"   # 評価用 = 出ない
MANUAL = "cccccccccccc"     # たたき台の出どころが rows・silence でない = 出ない
EDIT_SCHEMA = "youtube-tools-edit/v1"

KEEPS_DOC = [[0.0, 10.0], [10.5, 20.0], [22.0, 30.0], [31.0, 32.0]]   # 消した所 0.5・2.0・1.0 秒
KEEPS_SHORT = [[0.0, 100.0], [101.0, 200.0]]                         # 消した所 1.0 秒・合計 199 秒


write = kit.write


def edit(origin, keeps):
    return {"schema": EDIT_SCHEMA, "rev": 1, "updatedAt": 1, "sources": [], "clips": [],
            "draft": {"origin": origin, "settings": {}, "keepsSec": keeps, "at": 1}}


Ctx = kit.Ctx


class CutSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-cut-")
        self.env = {"YTT_DATA_DIR": self.tmp}
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        docs = ((DOC, 300, False, edit("rows", KEEPS_DOC)), (SHORT, 200, False, edit("silence", KEEPS_SHORT)),
                (EVAL_DOC, 400, True, edit("rows", KEEPS_DOC)), (MANUAL, 100, False, edit("manual", KEEPS_DOC)))
        for tid, upd, ev, ed in docs:
            d = {"title": "t", "updatedAt": upd, "segments": [{"id": "s1", "start": 0.0, "end": 1.0, "text": "あ"}]}
            if ev:
                d["evalSet"] = True
            write(os.path.join(tx, tid + ".json"), d)
            write(os.path.join(tx, tid + ".edit.json"), ed)
        self.ctx = Ctx(os.path.join(self.tmp, "app"), ROOT, env=self.env, eval_dirs=[])

    def view(self):
        return sources.View(self.ctx)

    def on(self):
        return mock.patch.dict(os.environ, {cutcard.SWITCH_ENV: "on"})

    def off(self):
        return mock.patch.dict(os.environ, {cutcard.SWITCH_ENV: ""}), mock.patch.object(cutcard._settings, "load_settings", return_value={cutcard.SETTING: False})

    def test_switch_off_gives_nothing(self):
        e, s = self.off()
        with e, s:
            for fn in (cut_sources.cut_edge, cut_sources.cut_gap, cut_sources.cut_whole):
                self.assertEqual(fn(self.view()), [])

    def test_settings_switch_on(self):
        with mock.patch.dict(os.environ, {cutcard.SWITCH_ENV: ""}), \
                mock.patch.object(cutcard._settings, "load_settings", return_value={}):   # 既定オン
            self.assertTrue(cutcard.enabled())
            self.assertTrue(cut_sources.cut_edge(self.view()))

    def test_edges_first_middle_last(self):
        with self.on():
            edges = [c for c in cut_sources.cut_edge(self.view()) if c["target"]["docId"] == DOC]
        self.assertEqual([c["target"]["cut"] for c in edges], [[10.0, 10.5], [20.0, 22.0], [30.0, 31.0]])
        self.assertEqual(edges[0]["media"]["start"], 8.0)   # 切れ目の前 2 秒
        self.assertEqual(edges[0]["media"]["end"], 12.5)    # 後ろ 2 秒
        self.assertEqual(edges[0]["options"], ["good", "early", "late", "keep"])

    def test_gap_only_when_two_seconds_or_more(self):
        with self.on():
            gaps = [c for c in cut_sources.cut_gap(self.view()) if c["target"]["docId"] == DOC]
            short = [c for c in cut_sources.cut_gap(self.view()) if c["target"]["docId"] == SHORT]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["target"]["cut"], [20.0, 22.0])
        self.assertEqual((gaps[0]["media"]["start"], gaps[0]["media"]["end"], gaps[0]["media"]["pad"]), (20.0, 22.0, 1.0))
        self.assertEqual(gaps[0]["options"], ["ok", "keep"])
        self.assertEqual(short, [])   # 1 秒の消した所だけ = 出ない

    def test_whole_only_when_total_within_120(self):
        with self.on():
            whole = [c for c in cut_sources.cut_whole(self.view()) if c["target"]["docId"] == DOC]
            none = [c for c in cut_sources.cut_whole(self.view()) if c["target"]["docId"] == SHORT]
        self.assertEqual(len(whole), 1)
        self.assertEqual(whole[0]["target"]["keeps"], [list(x) for x in KEEPS_DOC])
        self.assertEqual((whole[0]["media"]["start"], whole[0]["media"]["end"]), (0.0, 32.0))
        self.assertEqual(whole[0]["options"], ["good", "tempo", "unnatural"])
        self.assertEqual(none, [])

    def test_short_doc_gets_one_edge_only(self):
        with self.on():
            got = [c for c in cut_sources.cut_edge(self.view()) if c["target"]["docId"] == SHORT]
        self.assertEqual([c["target"]["cut"] for c in got], [[100.0, 101.0]])

    def test_eval_and_manual_origin_never_appear(self):
        with self.on():
            everything = []
            for fn in (cut_sources.cut_edge, cut_sources.cut_gap, cut_sources.cut_whole):
                everything += fn(self.view())
        self.assertFalse([c for c in everything if c["target"]["docId"] in (EVAL_DOC, MANUAL)])

    def test_at_most_five_per_doc_and_ids_parse(self):
        with self.on():
            everything = []
            for fn in (cut_sources.cut_edge, cut_sources.cut_gap, cut_sources.cut_whole):
                everything += fn(self.view())
        per = [c for c in everything if c["target"]["docId"] == DOC]
        self.assertLessEqual(len(per), 5)
        for c in everything:
            parsed = lineup.parse_id(c["id"])
            self.assertIsNotNone(parsed, c["id"])
            self.assertEqual(parsed[0], "cut")
            self.assertEqual(parsed[1], c["source"])
        self.assertTrue(all(lineup.parse_id(c["id"])[2].endswith("#w") for c in everything if c["source"] == "whole"))

    def test_order_newest_doc_first_then_edge_gap_whole(self):
        with self.on():
            cards = []
            for fn in (cut_sources.cut_edge, cut_sources.cut_gap, cut_sources.cut_whole):
                cards += fn(self.view())
        mine = sorted([c for c in cards if c["target"]["docId"] in (DOC, SHORT)], key=lambda c: c["_order"])
        self.assertEqual(mine[0]["target"]["docId"], DOC)   # 新しい文書が先
        kinds = [c["source"] for c in mine if c["target"]["docId"] == DOC]
        self.assertEqual(kinds, ["edge", "edge", "edge", "gap", "whole"])


if __name__ == "__main__":
    unittest.main()
