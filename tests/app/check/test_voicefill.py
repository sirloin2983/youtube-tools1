"""誰の声の材料を学習用データのショートから(src/app/check/voicefill.py。10-25)。
頼む順(頼んだ数の少ない人から 1 本ずつ)・手が空いていなければ頼まない・2 度は頼まない・名簿に無いフォルダは見ない・
学習用データの文書はほかの種類のカードに出さない(View.docs)が、誰の声のカードには出る。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voicefill.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import sources, voice_solo, voicefill as VF  # noqa: E402
from human.check import voice as voice_mod  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402


class State:
    def effective(self):
        return []


class VoiceFillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-voicefill-")
        self.learn = os.path.join(self.tmp, "素材", VF.LEARN_NAME)
        for who, n in (("さくらみこ", 3), ("兎田ぺこら", 1), ("知らない人", 2)):
            d = os.path.join(self.learn, who)
            os.makedirs(d)
            for i in range(n):
                open(os.path.join(d, "26-0%d-01_%s.mov" % (i + 1, who)), "wb").close()
        open(os.path.join(self.learn, "さくらみこ", "メモ.txt"), "wb").close()
        open(os.path.join(self.learn, "さくらみこ", "評価用データ37_さくらみこ_01_済.mkv"), "wb").close()   # 混ざった評価用の写しは頼まない(10-25)
        p = mock.patch.object(roster, "ROSTER", roster.BUNDLED)
        p.start()
        self.addCleanup(p.stop)
        self.app = os.path.join(self.tmp, "app")
        a = mock.patch.object(VF, "ASK_ON", True)   # 既定は止めてある(10-31)。戻したときの動き(Haas で頼む)の確かめは True で
        a.start()
        self.addCleanup(a.stop)

    def test_ask_off_asks_nothing(self):
        asked = []
        with mock.patch.object(VF, "ASK_ON", False):
            self.assertIsNone(VF.tick(self.app, lambda req: asked.append(req) or "j", lambda: None, lambda m: None, dirs=[self.learn]))
        self.assertEqual(asked, [])

    def test_round_robin_and_once(self):
        self.assertEqual(sorted({w for w, _p in VF.targets([self.learn])}), ["さくらみこ", "兎田ぺこら"])   # 名簿に無いフォルダ・動画でない物は見ない
        asked, logs = [], []
        start = lambda req: asked.append(req) or "j%d" % len(asked)   # noqa: E731
        self.assertIsNone(VF.tick(self.app, start, lambda: "文字起こしのジョブ", logs.append, dirs=[self.learn]))   # 手が空いていない
        for _ in range(5):
            VF.tick(self.app, start, lambda: None, logs.append, dirs=[self.learn])
        who = [os.path.basename(os.path.dirname(r["sourcePath"])) for r in asked]
        self.assertEqual(who[:2], ["さくらみこ", "兎田ぺこら"])                  # 頼んだ数の少ない人から回る
        self.assertEqual(len(asked), 4)                                          # 4 本で全部(評価用の写しは除く)。2 度は頼まない
        self.assertEqual(len({r["sourcePath"] for r in asked}), 4)
        self.assertEqual({(r["engine"], r["model"], r["device"]) for r in asked}, {("haas", "haas-ja-v1.0", "cpu")})   # 認識は Haas(10-31)
        self.assertIn("残り 0 本", logs[-1])
        with open(os.path.join(self.app, "check", VF.STATE_NAME), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 4)

    def test_failed_request_is_remembered(self):
        def boom(req):
            raise RuntimeError("動画が読めません")
        logs = []
        got = VF.tick(self.app, boom, lambda: None, logs.append, dirs=[self.learn])
        self.assertTrue(got and "頼めませんでした" in logs[-1])
        self.assertNotEqual(VF.tick(self.app, boom, lambda: None, logs.append, dirs=[self.learn]), got)   # 次の 1 本へ

    def test_learn_docs_only_for_voice_cards(self):
        ctx = kit.Ctx(os.path.join(self.tmp, "app2"), kit.ROOT, env={"YTT_DATA_DIR": self.tmp}, eval_dirs=[])
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        src = os.path.join(self.learn, "さくらみこ", "26-01-01_さくらみこ.mov")
        segs = [{"id": "s%d" % i, "start": i * 5.0, "end": i * 5.0 + 4, "text": "話す %d" % i, "speaker": "S1"} for i in range(4)]
        kit.write(os.path.join(tx, "aaaaaaaaaaa1.json"), {"title": "26-01-01_さくらみこ", "updatedAt": 1, "sourcePath": src, "speakers": [], "segments": segs})
        view = sources.View(ctx, State())
        self.assertEqual(view.docs(), [])                                         # ほかの種類のカードには出さない
        self.assertEqual([t for t, _p, _d in view.docs(need_media=False)], ["aaaaaaaaaaa1"])
        with mock.patch.object(voice_mod, "registry", lambda emb, cache=None: {}), mock.patch.object(voice_mod, "_relearn_sec", lambda: 30.0):
            cards = voice_solo.voice_solo(sources.View(ctx, State()))
        self.assertTrue(cards and {c["guess"]["name"] for c in cards} == {"さくらみこ"})   # 見立て = フォルダの名前の人
        self.assertTrue(all(c["media"]["url"].startswith("transcribe/media?id=") for c in cards))   # 動画があるので映像つき


if __name__ == "__main__":
    unittest.main()
