"""「確かめる」の行ごとの話者のカード(lines:seg)の答えで、製品の声の登録簿を覚え直す(11-02)の単体テスト:
答えの材料(名前で答えた 1 秒以上の行・ほかの人と声なしは除く)・初めての人は 10 秒で仮・ジョブ voice-learn-clip の中身(かけらの音と行の時刻)・
Z で材料から外れる・覚えたら learnedFrom の行は数えない・かけらから覚える本体(human/proof/speakers.run_voice_learn_clip。声の特徴は偽物)。
一時フォルダの作業データだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voice_lines_learn.py -v
"""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import sources, voice_lines as VL  # noqa: E402
from flow import diar as _diar, jobs as _heavy  # noqa: E402
from human.check import apply, voice as voice_mod  # noqa: E402
from human.proof import speakers as _speakers  # noqa: E402
from pipeline.transcribe import diarize as transcribe_diarize, recognize as _recognize  # noqa: E402

EMB = _diar.learn_embedding("")


def row(i, a, b, who):
    return {"id": "r%d" % i, "start": a, "end": b, "text": "行%d" % i, "guess": [{"name": who, "score": 0.8}]}


class State:
    def effective(self):
        return []


class LinesLearnTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-check-lines-learn-")
        os.makedirs(os.path.join(self.app, "check", VL.DIR_NAME))
        cards = [{"key": "k1", "video": "AAAAAAAAAAA", "title": "配信", "who": "大空スバル", "at": 0, "sec": 48.0,
                  "rows": [row(0, 0.0, 5.5, "大空スバル"), row(1, 6.0, 11.5, "大空スバル"), row(2, 12.0, 12.5, "大空スバル"), row(3, 13.0, 17.0, "白上フブキ")]}]
        with open(os.path.join(self.app, "check", VL.NAME), "w", encoding="utf-8") as f:
            json.dump({"cards": cards}, f, ensure_ascii=False)
        self.clip = os.path.join(self.app, "check", VL.DIR_NAME, "k1.wav")
        open(self.clip, "wb").close()
        self.ctx = apply.Context(self.app)
        self.jobs = []

        def add_job(spec, kind):
            self.jobs.append((kind, spec))
            return {"id": "job%d" % len(self.jobs)}
        for p in (mock.patch.object(_diar, "VOICES_DIR", os.path.join(self.app, "voices")), mock.patch.dict(_heavy.JOB_RUNNERS, {"voice-learn": lambda job: None, "voice-learn-clip": lambda job: None}),
                  mock.patch.object(_diar, "voice_ready", return_value=True), mock.patch.object(_heavy, "add_job", side_effect=add_job),
                  mock.patch.object(voice_mod, "RELEARN_PAUSED", False)):
            p.start()
            self.addCleanup(p.stop)

    def cards(self):
        return VL.voice_lines(sources.View(types.SimpleNamespace(root=None, env=None, app_dir=self.app), State()))

    def test_learn_from_answers(self):
        c0, c1, c2 = self.cards()   # 一切れ: [r0] [r1 r2] [r3]
        a = apply.answer(self.ctx, c0, {"answer": {}})                                      # スバル 5.5 秒(予想どおり)= 10 秒に届かない
        self.assertEqual(self.jobs, [])
        self.assertEqual([(x["row"], x["name"], x["sec"]) for x in a["applied"]["learn"]], [("r0", "大空スバル", 5.5)])
        apply.answer(self.ctx, c2, {"answer": {"rows": [{"id": "r3", "speaker": "ほかの人"}]}})   # ほかの人 = 覚えない
        self.assertEqual(self.jobs, [])
        b = apply.answer(self.ctx, c1, {"answer": {}})                                      # + 5.5 秒(r2 は 1 秒未満)= 11 秒 ≥ 10(初めての人)
        self.assertEqual([x["row"] for x in b["applied"]["learn"]], ["r1"])
        self.assertEqual(len(self.jobs), 1)
        kind, spec = self.jobs[0]
        self.assertEqual((kind, spec["doc"], spec["clip"], spec["names"], spec["rowIds"], spec["groups"], spec["by"], spec["provisional"], spec["embedding"]),
                         ("voice-learn-clip", "lines:k1", self.clip, ["大空スバル"], {"大空スバル": ["r0", "r1"]}, {"大空スバル": [[0.0, 5.5], [6.0, 11.5]]},
                          "check", ["大空スバル"], EMB))
        self.assertEqual(b["applied"]["relearn"][0]["job"], "job1")
        # 動いている間は数えない → 覚えたら learnedFrom の行は数えない
        with mock.patch.dict(_heavy._jobs, {"j": {"kind": "voice-learn-clip", "state": "running", "spec": dict(spec)}}):
            self.assertEqual(voice_mod._pending(self.ctx), {})
        with _diar.voices_edit(EMB) as v:
            v["大空スバル"] = _diar.merge_voice(None, [1.0, 0.0], 2, 11.0, "lines:k1", by="check", row_ids=["r0", "r1"])
        self.assertEqual(voice_mod._pending(self.ctx), {})

    def test_undo_drops_material_and_none_rows(self):
        c0, c1, _c2 = self.cards()
        a = apply.answer(self.ctx, c0, {"answer": {}})
        apply.undo(self.ctx, a["answer"])                                                   # Z = 材料から外れる
        b = apply.answer(self.ctx, c1, {"answer": {"rows": [{"id": "r1", "none": True}]}})  # 声なし = 覚えない
        self.assertEqual((b["applied"]["learn"], self.jobs, voice_mod._pending(self.ctx)), ([], [], {}))

    def test_run_voice_learn_clip(self):
        """かけらの音から覚える本体: 登録簿に仮の声・learnedFrom に行・行ごとの特徴の控え"""
        tmp = os.path.join(self.app, "tmp")

        def emb(job, wav, e, groups, off):
            return [transcribe_diarize._unit([1.0, 0.0, 0.0]) for _ in groups]
        spec = {"doc": "lines:k1", "clip": self.clip, "embedding": EMB, "names": ["大空スバル"], "groups": {"大空スバル": [[0.0, 5.5], [6.0, 11.5]]},
                "rowIds": {"大空スバル": ["r0", "r1"]}, "rows": ["r0", "r1"], "by": "check", "provisional": ["大空スバル"], "title": "t"}
        job = {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}
        with mock.patch.dict(_heavy._conf, {"tmp_dir": lambda: tmp}), mock.patch.object(_recognize, "extract_audio", lambda *a: None), \
                mock.patch.object(transcribe_diarize, "has_sherpa", lambda: True), mock.patch.object(transcribe_diarize, "ensure_diar_models", lambda *a: None), \
                mock.patch.object(transcribe_diarize, "embed_groups", emb):
            _speakers.run_voice_learn_clip(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        v = _diar.load_voices(EMB)["大空スバル"]
        self.assertTrue(v["provisional"])
        self.assertEqual((v["sec"], v["learnedFrom"][0]["doc"], v["learnedFrom"][0]["rows"], v["learnedFrom"][0]["by"]), (11.0, "lines:k1", ["r0", "r1"], "check"))
        with open(_diar.row_vectors_path(EMB), encoding="utf-8") as f:
            self.assertEqual(sorted(json.load(f)["大空スバル"]), ["lines:k1#r0", "lines:k1#r1"])


if __name__ == "__main__":
    unittest.main()
