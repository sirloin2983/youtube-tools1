"""評価のレーンの区間カードの出どころ(src/app/check/eval_sources.py。C-EVAL)の単体テスト: 区切り方・行の持ち主・スイッチ・
評価用の文書だけ・答えた区間の続きから・普段のレーンに出ない・確かめ済みは出さない。一時フォルダの文書だけを使う。

実行(リポジトリ直下から): py -3.10 -m unittest src/app/check/tests/test_eval_sources.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT

from app.check import deck, eval_sources, lineup, sources  # noqa: E402
from human.check import apply, section  # noqa: E402

EVAL_DOC, DOC, DONE_DOC = "eeeeeeeeeeee", "dddddddddddd", "cccccccccccc"


write = kit.write


def row(rid, a, b, text="あ"):
    return {"id": rid, "start": a, "end": b, "text": text, "speaker": "S1"}


# 0〜100 秒。すき間: 9〜12(3 秒・真ん中 10.5)・29〜33(4 秒・31)・35〜36(1 秒・35.5)・58〜60(2 秒・59)
ROWS = [row("r1", 1.0, 9.0), row("r2", 12.0, 29.0), row("r3", 33.0, 35.0), row("r4", 36.0, 58.0), row("r5", 60.0, 80.0), row("r6", 82.0, 95.0)]


class CutTest(unittest.TestCase):
    def test_longest_gap_in_window(self):
        self.assertEqual(eval_sources.cut_after(ROWS, 0.0, 100.0), (31.0, False))   # 20〜40 秒の間でいちばん長いすき間の真ん中

    def test_no_gap_in_window_extends_to_next_gap(self):
        self.assertEqual(eval_sources.cut_after(ROWS, 31.0, 100.0), (59.0, False))   # 51〜71 に無い → 71 のあとの最初は 81
        rows = [row("a", 0.0, 50.0), row("b", 50.0, 70.0), row("c", 72.0, 120.0)]
        self.assertEqual(eval_sources.cut_after(rows, 0.0, 200.0), (71.0, False))

    def test_short_tail_is_last(self):
        self.assertEqual(eval_sources.cut_after(ROWS, 59.0, 100.0), (100.0, True))   # 残り 41 秒 ≤ 40 + 10
        self.assertEqual(eval_sources.cut_after([row("a", 0.0, 95.0)], 0.0, 100.0), (100.0, True))


class SectionSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-eval-")
        self.env = {"YTT_DATA_DIR": self.tmp}
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        base = {"title": "t", "start": 0.0, "end": 100.0, "updatedAt": 200, "speakers": [{"id": "S1", "name": "話者 1"}], "segments": ROWS}
        write(os.path.join(tx, EVAL_DOC + ".json"), dict(base, evalSet=True))
        write(os.path.join(tx, DOC + ".json"), base)
        write(os.path.join(tx, DONE_DOC + ".json"), dict(base, evalSet=True, evalReviewed={"at": 1}))
        self.ctx = apply.Context(os.path.join(self.tmp, "app"), ROOT, env=self.env, eval_dirs=[])
        p = mock.patch.dict(os.environ, {section.SWITCH_ENV: "on"})
        p.start()
        self.addCleanup(p.stop)
        for m, name, val in ((eval_sources._drill, "_all_members", lambda dirs: ["兎田ぺこら", "さくらみこ"]), (eval_sources._check_doc, "busy", lambda tid: False)):
            q = mock.patch.object(m, name, val)
            q.start()
            self.addCleanup(q.stop)

    def view(self, answered=()):
        v = sources.View(self.ctx)
        v.answered = lambda kind=None: [r for r in answered if kind is None or r["kind"] == kind]
        return v

    def test_first_card_of_eval_doc_only(self):
        cards = eval_sources.section_eval(self.view())
        self.assertEqual([c["target"]["docId"] for c in cards], [EVAL_DOC])   # 普段の文書・確かめ済みは出さない
        c = cards[0]
        self.assertEqual((c["id"], c["target"]["from"], c["target"]["to"], c["target"]["rows"], c["target"]["last"], c["target"]["index"]),
                         ("section:eval:%s#0" % EVAL_DOC, 0.0, 31.0, ["r1", "r2"], False, 0))
        self.assertEqual(c["options"], ["兎田ぺこら", "さくらみこ"])   # メンバーのフォルダの名前だけ
        self.assertIsNotNone(lineup.parse_id(c["id"]))
        self.assertEqual([(r["id"], r["owned"]) for r in c["rows"]], [("r1", True), ("r2", True)])

    def test_continues_after_answered_sections(self):
        ans = [{"kind": "section", "applied": {"docId": EVAL_DOC, "to": 31.0}}, {"kind": "section", "applied": {"docId": EVAL_DOC, "to": 59.0}}]
        c = eval_sources.section_eval(self.view(ans))[0]
        self.assertEqual((c["target"]["from"], c["target"]["to"], c["target"]["rows"], c["target"]["last"], c["target"]["index"]),
                         (59.0, 100.0, ["r5", "r6"], True, 2))
        self.assertEqual([(r["id"], r["owned"]) for r in c["rows"]], [("r4", False), ("r5", True), ("r6", True)])   # 区間にかかる前の区間の行は灰色(持ち主は中心の区間)

    def test_switch_off(self):
        with mock.patch.dict(os.environ, {section.SWITCH_ENV: ""}), mock.patch.object(section._settings, "load_settings", return_value={section.SETTING: False}):
            self.assertEqual(eval_sources.section_eval(self.view()), [])

    def test_lanes_do_not_mix(self):
        normal = deck.next_cards(self.ctx, n=50)
        self.assertFalse([c for c in normal["cards"] if c["kind"] == "section"])
        self.assertNotIn("section", normal["counts"]["perKind"])
        ev = deck.next_cards(self.ctx, n=50, lane="eval")
        self.assertEqual([c["kind"] for c in ev["cards"]], ["section"])
        self.assertEqual(ev["lane"], "eval")
        with self.assertRaises(ValueError):
            deck.next_cards(self.ctx, n=1, lane="eval", kind="voice")
        with self.assertRaises(ValueError):
            deck.next_cards(self.ctx, n=1, lane="x")


if __name__ == "__main__":
    unittest.main()
