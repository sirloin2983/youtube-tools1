"""確かめるのカードの元の古い版の文書の作り直し(src/app/check/refresh.py)の単体テスト: 対象の選び方(古い版・動画がある・評価用は外す・
ソロの声の元を先に)・1 晩の本数・同じ文書の回数・頼む形。編集へは頼まない(call を差し替え)。一時フォルダの文書だけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_refresh.py -v
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import refresh, sources  # noqa: E402
from pipeline.transcribe import records  # noqa: E402

NIGHT = time.mktime((2026, 10, 25, 3, 0, 0, 0, 0, -1))


def doc(version, media=None, **kw):
    return dict({"title": "t", "updatedAt": 1, "segments": [{"id": "s1", "start": 0.0, "end": 4.0, "text": "話す"}],
                 "sourcePath": media or "", "recognition": {"runs": [{"engine": "whisper.cpp", "model": "large-v3", "post": {"version": version}}]}}, **kw)


def card(tid, kind="voice", source="diar"):
    return {"id": "x", "kind": kind, "source": source, "target": {"docId": tid}}


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-refresh-")
        self.tx = os.path.join(self.tmp, "transcribe", "transcripts")
        self.app = os.path.join(self.tmp, "app")
        evd = os.path.join(self.tmp, "eval")
        self.ctx = kit.Ctx(self.app, kit.ROOT, env={"YTT_DATA_DIR": self.tmp}, eval_dirs=[evd])
        self.video = os.path.join(self.tmp, "v.mp4")
        kit.write(self.video, {})
        evvid = os.path.join(evd, "e.mp4")
        kit.write(evvid, {})
        self.put("a00000000001", doc("0.61.0", self.video))                       # 古い・声の判別
        self.put("a00000000002", doc("0.56.0", self.video))                       # 古い・ソロの声 = 先
        self.put("a00000000003", doc(records.OUTPUT_SINCE, self.video))           # 今の版
        self.put("a00000000004", doc("0.61.0", os.path.join(self.tmp, "gone.mp4")))   # 動画が無い
        self.put("a00000000005", doc("0.61.0", self.video, evalSet=True))         # 評価用の印
        self.put("a00000000006", doc("0.61.0", evvid))                            # 評価用のフォルダの動画
        self.cards = [card("a0000000000%d" % i) for i in (1, 3, 4, 5, 6)] + [card("a00000000002", source="solo")]
        self.calls = []

    def put(self, tid, d):
        kit.write(os.path.join(self.tx, tid + ".json"), d)

    def collect(self, ctx, state=None):
        return self.cards, sources.View(ctx, state)

    def call(self, body):
        self.calls.append(body)
        return 200, {"id": "j"}

    def tick(self, now=NIGHT):
        return refresh.tick(self.ctx, self.call, self.app, now=now, collect=self.collect)

    def test_output_old(self):
        self.assertTrue(records.output_old(doc("0.99.18")))       # 数で比べる(0.99.18 < 0.99.159)
        self.assertFalse(records.output_old(doc("0.99.160")))
        self.assertTrue(records.output_old({"segments": []}))     # 版が分からない
        self.assertTrue(records.output_old(doc("9.0.0"), model="large-v3-turbo"))

    def test_targets_skip_current_missing_media_and_eval(self):
        _c, view = self.collect(self.ctx)
        self.assertEqual(refresh.targets(self.cards, view), ["a00000000002", "a00000000001"])

    def test_tick_one_at_a_time_with_limits(self):
        self.assertEqual(self.tick(), "a00000000002")
        self.assertEqual(self.calls, [{"tid": "a00000000002", "target": "whole", "refresh": True}])
        self.assertEqual(self.tick(), "a00000000001")             # 同じ晩に同じ文書は入れ直さない
        self.assertIsNone(self.tick())
        st = refresh.read_state(self.app)
        self.assertEqual((st["count"], [x["from"] for x in st["done"]]), (2, ["0.56.0", "0.61.0"]))
        self.assertEqual(self.tick(NIGHT + 86400), "a00000000002")   # 作り直せていなければ次の晩にもう一度
        self.assertEqual(self.tick(NIGHT + 86400), "a00000000001")
        self.assertIsNone(self.tick(NIGHT + 2 * 86400))              # MAX_TRIES 回まで
        self.assertEqual(len(self.calls), 4)

    def test_per_night_limit_and_refused(self):
        self.cards = [card("a00000000001"), card("a00000000002")]
        old = refresh.PER_NIGHT
        refresh.PER_NIGHT = 1
        self.addCleanup(setattr, refresh, "PER_NIGHT", old)
        self.assertIsNotNone(self.tick())
        self.assertIsNone(self.tick())                             # 1 晩の上限
        self.call = lambda body: (409, {"error": "busy"})
        self.assertIsNone(self.tick(NIGHT + 86400))                # 断られても止まらない(数えない)
        self.assertEqual(refresh.read_state(self.app)["count"], 0)


if __name__ == "__main__":
    unittest.main()
