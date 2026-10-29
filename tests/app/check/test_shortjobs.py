"""ショートの文書から読み・「この行は声ですか」のカード(src/app/check/shortjobs.py と sources の shorts。10-25)。
下ごしらえ(判別 → 2 つ目のエンジン)を 1 本ずつ・2 度は頼まない・評価用の写しは頼まない / ショート 1 本から種類ごとに SHORT_CAP 枚まで /
判別で話者が分かれたショートの誰の声のカードは、行の多い話者の行だけ。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_shortjobs.py -v
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import shortjobs as SJ, sources, speech_sources, voice_solo, voicefill  # noqa: E402
from human.check import voice as voice_mod  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402

MIKO = "さくらみこ"


class State:
    def effective(self):
        return []


class ShortJobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-shortjobs-")
        self.tx = os.path.join(self.tmp, "transcribe", "transcripts")
        self.learn = os.path.join(self.tmp, "素材", voicefill.LEARN_NAME, MIKO)
        os.makedirs(self.learn)
        self.ctx = kit.Ctx(os.path.join(self.tmp, "app"), kit.ROOT, env={"YTT_DATA_DIR": self.tmp}, eval_dirs=[])
        for p in (mock.patch.object(roster, "ROSTER", roster.BUNDLED), mock.patch.object(voice_mod, "registry", lambda emb, cache=None: {}),
                  mock.patch.object(voice_mod, "_relearn_sec", lambda: 30.0)):
            p.start()
            self.addCleanup(p.stop)

    def short(self, tid, name, segs, diar=None):
        src = os.path.join(self.learn, name)
        open(src, "wb").close()
        kit.write(os.path.join(self.tx, tid + ".json"), {"title": os.path.splitext(name)[0], "updatedAt": 1, "sourcePath": src, "speakers": [], "segments": segs})
        if diar is not None:
            kit.write(os.path.join(self.tx, tid + ".diar.json"), {"schema": sources.DIAR_SCHEMA, "latest": diar, "history": []})

    def view(self):
        return sources.View(self.ctx, State())

    def test_jobs_once_each(self):
        segs = [{"id": "s0", "start": 0.0, "end": 4.0, "text": "話す", "speaker": ""}]
        self.short("aaaaaaaaaaa1", "26-01-01_%s.mov" % MIKO, segs)
        self.short("aaaaaaaaaaa2", "評価用データ1_%s.mov" % MIKO, segs)   # 評価用の写し = 頼まない
        calls, logs = [], []
        call = lambda path, body: calls.append((path, body)) or "j%d" % len(calls)   # noqa: E731
        for _ in range(4):
            SJ.tick(self.view(), self.ctx.app_dir, call, lambda: None, logs.append)
        self.assertEqual([p for p, _b in calls], ["/api/diarize", "/api/rerun"])   # 判別 → 2 つ目のエンジン・2 度は頼まない
        self.assertEqual((calls[0][1]["numSpeakers"], calls[0][1]["names"], calls[0][1]["recognize"]), (0, [MIKO], False))
        self.assertEqual((calls[1][1]["engine"], calls[1][1]["result"]), ("alt", "propose"))
        self.assertIsNone(SJ.tick(self.view(), self.ctx.app_dir, call, lambda: "処理中", logs.append))

    def test_short_cap_and_main_speaker(self):
        segs = [{"id": "s%d" % i, "start": i * 5.0, "end": i * 5.0 + 4, "text": "話す %d" % i, "speaker": "S1" if i < 4 else "S2",
                 "fill": {"from": "はなす %d" % i, "by": "fill"}} for i in range(6)]
        self.short("bbbbbbbbbbb1", "26-01-02_%s.mov" % MIKO, segs, diar={"turns": [{"start": 100.0, "end": 101.0}]})
        v = self.view()
        self.assertEqual(len(sources.read_fill(v)), sources.SHORT_CAP)            # 読み: ショート 1 本から 2 枚まで
        with mock.patch.object(speech_sources, "CARDS_ON", True):   # 声ですかは既定でオフ(10-29)
            self.assertEqual(len(speech_sources.speech_diar(v)), sources.SHORT_CAP)   # 声ですか: 同じく
        self.assertEqual(v.docs(), [])                                             # 普段の一覧(時刻など)には入れない
        cards = voice_solo.voice_solo(self.view())
        self.assertTrue(cards and all(c["target"]["row"] in ("s0", "s1", "s2", "s3") for c in cards))   # 行の多い話者 S1 の行だけ


if __name__ == "__main__":
    unittest.main()
