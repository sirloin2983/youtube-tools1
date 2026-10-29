"""「確かめる」の「この行は声ですか?」の出どころ(src/app/check/speech_sources.py)の単体テスト: 声の区間との重なりの割合・除外(校正済み・noSub・短い・空)・
評価用の文書は出ない・diar が無い文書は出ない・低い割合の順。一時フォルダの文書と .diar.json だけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_speech_sources.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT

from app.check import sources, speech_sources  # noqa: E402
from human.check import apply  # noqa: E402

DOC, EVAL_DOC, NODIAR_DOC = "dddddddddddd", "eeeeeeeeeeee", "ffffffffffff"
TURNS = [{"start": 0.0, "end": 10.0, "label": "S1"}, {"start": 20.0, "end": 30.0, "label": "S2"}]


write = kit.write


Ctx = kit.Ctx


def rows():
    def r(rid, a, b, text, **kw):
        return dict({"id": rid, "start": a, "end": b, "text": text, "speaker": "S1"}, **kw)
    return [r("r1", 0.0, 2.0, "声の行"),                       # 全部が声の区間の中 = 候補にしない
            r("r2", 12.0, 14.0, "声の無い行"),                 # 重なり 0 = 候補(一番低い)
            r("r3", 9.0, 11.0, "半分だけ"),                    # 重なり 0.5 = 候補にしない(0.3 以上)
            r("r4", 9.0, 19.0, "少しだけ重なる"),              # 重なり 0.1 = 候補
            r("r5", 27.0, 28.4, "声の中"),                     # 全部が声 = 候補にしない
            r("r6", 12.0, 14.0, "校正済み", proofed=True),      # 校正済み = 候補にしない
            r("r7", 12.0, 14.0, "字幕に出さない", noSub=True),  # noSub = 候補にしない
            r("r8", 40.0, 40.2, "短い"),                       # 0.3 秒未満 = 候補にしない
            r("r9", 15.0, 16.0, "   ")]                         # 空の文字 = 候補にしない


class SpeechSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-speech-")
        kit.media_present(self)
        self.env = {"YTT_DATA_DIR": self.tmp}
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        for tid, ev in ((DOC, False), (EVAL_DOC, True), (NODIAR_DOC, False)):
            d = {"title": "t", "updatedAt": 200, "speakers": [{"id": "S1", "name": "あ"}], "segments": rows()}
            if ev:
                d["evalSet"] = True
            write(os.path.join(tx, tid + ".json"), d)
        for tid in (DOC, EVAL_DOC):
            write(os.path.join(tx, tid + ".diar.json"), {"schema": sources.DIAR_SCHEMA, "latest": {"rows": {}, "turns": TURNS}, "history": []})
        self.ctx = Ctx(os.path.join(self.tmp, "app"), ROOT, env=self.env, eval_dirs=[])
        on = mock.patch.object(speech_sources, "CARDS_ON", True)   # 既定はオフ(10-29)。作り方はスイッチを入れて見る
        on.start()
        self.addCleanup(on.stop)

    def test_off_by_default(self):
        """既定はオフ(10-29 ユーザー「止めていい」): 判別の記録があってもカードを作らない"""
        with mock.patch.object(speech_sources, "CARDS_ON", False):
            self.assertEqual(self.cards(), [])
        self.assertTrue(self.cards())

    def cards(self):
        return speech_sources.speech_diar(sources.View(self.ctx))

    def test_candidates_and_exclusions(self):
        ids = [c["target"]["row"] for c in self.cards() if c["target"]["docId"] == DOC]
        self.assertEqual(ids, ["r2", "r4"])   # 重なりの低い順(0 → 0.1)

    def test_single_speaker_record_is_skipped(self):
        """1 人指定(判別していない = 声の区間が空)の記録の文書は出さない(全部の行が候補になってしまう)"""
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        write(os.path.join(tx, NODIAR_DOC + ".diar.json"), {"schema": sources.DIAR_SCHEMA, "latest": {"engine": {"name": "single"}, "rows": {}, "turns": []}, "history": []})
        self.assertFalse([c for c in self.cards() if c["target"]["docId"] == NODIAR_DOC])

    def test_eval_doc_and_no_diar_never_appear(self):
        cards = self.cards()
        self.assertTrue(cards)
        for c in cards:
            self.assertEqual(c["target"]["docId"], DOC)
            self.assertNotIn(EVAL_DOC, c["id"])
            self.assertNotIn(NODIAR_DOC, c["id"])

    def test_card_shape_and_order(self):
        by = {c["target"]["row"]: c for c in self.cards() if c["target"]["docId"] == DOC}
        c = by["r2"]
        self.assertEqual(c["id"], "speech:diar:%s#r2" % DOC)
        self.assertEqual((c["kind"], c["source"]), ("speech", "diar"))
        self.assertEqual(c["options"], ["keep", "drop"])
        self.assertEqual(c["media"]["pad"], speech_sources.PAD)
        self.assertLess(c["_order"][0], by["r4"]["_order"][0])

    def test_threshold_is_ratio(self):
        self.assertEqual(speech_sources.VOICE_MIN_RATIO, 0.3)
        turns = speech_sources._turns({"turns": TURNS})
        self.assertAlmostEqual(speech_sources._overlap(turns, 9.0, 11.0), 1.0)   # 2 秒の行の 1 秒
        self.assertAlmostEqual(speech_sources._overlap(turns, 5.0, 25.0), 10.0)   # 2 つの区間の合計(行の長さを超えない)
        self.assertEqual(speech_sources._overlap(turns, 40.0, 50.0), 0.0)


if __name__ == "__main__":
    unittest.main()
