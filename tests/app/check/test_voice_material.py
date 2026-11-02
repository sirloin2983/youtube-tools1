"""「確かめる」の声の材料の確かめ(material:solo・src/app/check/voice_material.py。11-02 話者の物差し 13 章 カード ア)の単体テスト:
カードは配信ごとに 1 枚・外した配信は出さない・答え 5 つの反映(確か・配信ごと外す・かけらだけ外す・変えない)と Z・
見回り(仮で入れるジョブ voice-learn-material の中身・外すジョブ voice-unlearn・確かの印・失敗は 1 日待つ)・
入れる本体と外す本体(human/proof/speakers。声の特徴は偽物)。一時フォルダの作業データだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_voice_material.py -v
"""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import deck, lineup, sources, voice_lines as VL, voice_material as VM  # noqa: E402
from flow import diar as _diar, jobs as _heavy  # noqa: E402
from human.check import apply  # noqa: E402
from human.proof import speakers as _speakers  # noqa: E402
from pipeline.transcribe import diarize as transcribe_diarize, recognize as _recognize  # noqa: E402

EMB = _diar.learn_embedding("")


class State:
    def effective(self):
        return []


def mat(key, video, part, who="大空スバル", material=True):
    return {"key": key, "video": video, "title": "配信 " + video, "who": who, "at": 100.0, "sec": 48.0, "part": part, "material": material,
            "rows": [{"id": "r0", "start": 0.5, "end": 3.0, "text": "はい", "guess": []}, {"id": "r1", "start": 3.2, "end": 3.8, "text": "ん", "guess": []},
                     {"id": "r2", "start": 10.0, "end": 14.0, "text": "長い行", "guess": []}]}


class MaterialTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-check-material-")
        os.makedirs(os.path.join(self.app, "check", VL.DIR_NAME))
        cards = [mat("ka", "AAAAAAAAAAA", "head"), mat("kb", "AAAAAAAAAAA", "tail"), mat("kc", "BBBBBBBBBBB", "mid1"), mat("kd", "CCCCCCCCCCC", "head", material=False)]
        with open(os.path.join(self.app, "check", VL.NAME), "w", encoding="utf-8") as f:
            json.dump({"cards": cards}, f, ensure_ascii=False)
        for c in cards:
            open(os.path.join(self.app, "check", VL.DIR_NAME, c["key"] + ".wav"), "wb").close()
        self.ctx = apply.Context(self.app)
        self.jobs, self.logs = [], []

        def add_job(spec, kind):
            self.jobs.append((kind, spec))
            return {"id": "job%d" % len(self.jobs)}
        for p in (mock.patch.object(_diar, "VOICES_DIR", os.path.join(self.app, "voices")),
                  mock.patch.dict(_heavy.JOB_RUNNERS, {"voice-learn-material": lambda job: None, "voice-unlearn": lambda job: None}),
                  mock.patch.object(_diar, "voice_ready", return_value=True), mock.patch.object(_heavy, "add_job", side_effect=add_job),
                  mock.patch.object(_heavy, "active_jobs", return_value=[])):
            p.start()
            self.addCleanup(p.stop)

    def cards(self):
        return VM.material_cards(sources.View(types.SimpleNamespace(root=None, env=None, app_dir=self.app), State()))

    def tick(self, now=1000.0):
        return VM.tick(self.app, lambda: None, self.logs.append, now=now)

    def test_cards_one_per_video(self):
        got = self.cards()
        self.assertEqual(sorted(c["target"]["videoId"] for c in got), ["AAAAAAAAAAA", "BBBBBBBBBBB"])   # 材料でないかけらは出さない
        c = next(c for c in got if c["target"]["videoId"] == "BBBBBBBBBBB")
        self.assertEqual(lineup.parse_id(c["id"])[:2], ("material", "solo"))
        self.assertEqual((c["media"]["start"], c["media"]["end"]), (9.7, 14.3))   # 話す時間がいちばん長い一切れ
        self.assertEqual(c["near"], [4.7, 19.3])
        self.assertEqual([a[0] for a in c["answers"]], ["only", "not", "mixed", "unusual", "unknown"])
        self.assertIn("material", lineup.NORMAL_KINDS)
        self.assertIn("material", deck.KIND_GROUP["voice"])

    def test_answers_and_undo(self):
        cards = {c["target"]["videoId"]: c for c in self.cards()}
        for bad in ({}, {"answer": "x"}, {"answer": "only", "x": 1}):
            with self.assertRaises(apply.Refused):
                apply.answer(self.ctx, cards["BBBBBBBBBBB"], {"answer": bad})
        a = apply.answer(self.ctx, cards["BBBBBBBBBBB"], {"answer": {"answer": "only"}})
        self.assertEqual((a["applied"]["answer"], a["applied"]["keys"]), ("only", ["kc"]))
        self.assertIn("kc", VM.read_state(self.app)["sure"])
        b = apply.answer(self.ctx, cards["AAAAAAAAAAA"], {"answer": {"answer": "mixed"}})   # 配信ごと外す
        self.assertEqual(sorted(b["applied"]["keys"]), ["ka", "kb"])
        self.assertEqual(sorted(VM.read_state(self.app)["dropped"]), ["ka", "kb"])
        self.assertEqual([c["target"]["videoId"] for c in self.cards()], ["BBBBBBBBBBB"])   # 外した配信は出さない
        apply.undo(self.ctx, b["answer"])
        self.assertEqual(VM.read_state(self.app)["dropped"], {})
        u = apply.answer(self.ctx, cards["AAAAAAAAAAA"], {"answer": {"answer": "unusual"}})   # かけらだけ外す
        self.assertEqual(u["applied"]["keys"], [cards["AAAAAAAAAAA"]["target"]["material"]])
        apply.undo(self.ctx, a["answer"])
        self.assertEqual(VM.read_state(self.app)["sure"], {})
        n = apply.answer(self.ctx, cards["BBBBBBBBBBB"], {"answer": {"answer": "unknown"}})
        self.assertEqual(n["applied"]["keys"], [])

    def test_tick_ingest_drop_sure(self):
        self.assertEqual(self.tick(), "voice-learn-material")
        kind, spec = self.jobs[0]
        self.assertEqual([c["doc"] for c in spec["clips"]], ["material:ka", "material:kb", "material:kc"])
        one = spec["clips"][0]
        self.assertEqual((one["names"], one["groups"], one["rowIds"], one["sure"]), (["大空スバル"], {"大空スバル": [[0.5, 3.0], [10.0, 14.0]]}, {"大空スバル": ["r0", "r2"]}, False))
        self.assertEqual(sorted(VM.read_state(self.app)["asked"]), ["ka", "kb", "kc"])
        # ジョブが終わって ka・kb だけ入った = kc は失敗(1 日待つ)
        with _diar.voices_edit(EMB) as v:
            v["大空スバル"] = _diar.merge_voice(None, [1.0, 0.0], 2, 6.5, "material:ka", row_ids=["r0", "r2"])
            v["大空スバル"] = _diar.merge_voice(v["大空スバル"], [1.0, 0.0], 2, 6.5, "material:kb", row_ids=["r0", "r2"])
            v["大空スバル"]["learnedFrom"][0]["sure"] = False
        self.assertIsNone(self.tick(now=2000.0))
        st = VM.read_state(self.app)
        self.assertEqual((st["asked"], sorted(st["failed"])), ({}, ["kc"]))
        self.assertEqual(self.tick(now=2000.0 + VM.RETRY_SEC), "voice-learn-material")   # 1 日たったら試し直す
        # 確かの印 → 登録簿へ
        with VM._lock:
            st = VM.read_state(self.app)
            st["sure"]["ka"] = {"by": "x", "at": 1}
            st["asked"] = {}
            VM._write_state(self.app, st)
        self.jobs.clear()
        self.tick(now=3000.0)
        lf = {x["doc"]: x for x in _diar.load_voices(EMB)["大空スバル"]["learnedFrom"]}
        self.assertTrue(lf["material:ka"]["sure"])
        # 外す答え → voice-unlearn を先に
        with VM._lock:
            st = VM.read_state(self.app)
            st["dropped"]["kb"] = {"why": "unusual", "by": "x", "video": "AAAAAAAAAAA", "at": 1}
            VM._write_state(self.app, st)
        self.jobs.clear()
        self.assertEqual(self.tick(now=4000.0), "voice-unlearn")
        self.assertEqual((self.jobs[0][1]["name"], self.jobs[0][1]["docs"]), ("大空スバル", ["material:kb"]))
        with mock.patch.object(VM.voice_mod, "RELEARN_PAUSED", True):
            self.assertIsNone(self.tick(now=5000.0))   # 覚え直しの一時止めの間は休む

    def test_run_learn_material_and_unlearn(self):
        tmp = os.path.join(self.app, "tmp")
        clip = os.path.join(self.app, "check", VL.DIR_NAME, "ka.wav")
        spec = {"embedding": EMB, "by": "material", "title": "t", "clips": [
            {"doc": "material:ka", "clip": clip, "names": ["大空スバル"], "groups": {"大空スバル": [[0.5, 3.0], [10.0, 14.0]]}, "rowIds": {"大空スバル": ["r0", "r2"]}, "sure": False, "by": "material"},
            {"doc": "material:kz", "clip": os.path.join(self.app, "nope.wav"), "names": ["大空スバル"], "groups": {"大空スバル": [[0.5, 3.0]]}, "rowIds": {"大空スバル": ["r0"]}, "sure": False},
            {"doc": "material:kb", "clip": clip, "names": ["大空スバル"], "groups": {"大空スバル": [[0.5, 3.0], [10.0, 14.0]]}, "rowIds": {"大空スバル": ["r0", "r2"]}, "sure": True, "by": "material"}]}
        job = {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}
        with mock.patch.dict(_heavy._conf, {"tmp_dir": lambda: tmp}), mock.patch.object(_recognize, "extract_audio", lambda *a: None), \
                mock.patch.object(transcribe_diarize, "has_sherpa", lambda: True), mock.patch.object(transcribe_diarize, "ensure_diar_models", lambda *a: None), \
                mock.patch.object(transcribe_diarize, "embed_groups", lambda job, wav, e, groups, off: [transcribe_diarize._unit([1.0, 0.0, 0.0]) for _ in groups]):
            _speakers.run_voice_learn_material(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual((job["learned"], list(job["failed"])), (["material:ka", "material:kb"], ["material:kz"]))   # 音の無いかけらは飛ばして続ける
        v = _diar.load_voices(EMB)["大空スバル"]
        self.assertEqual([(x["doc"], x["sure"], x["by"], x["rows"]) for x in v["learnedFrom"]], [("material:ka", False, "material", ["r0", "r2"]), ("material:kb", True, "material", ["r0", "r2"])])
        self.assertNotIn("provisional", v)   # 13 秒 = 人の声の仮(30 秒まで)ではない形は merge_voice のまま
        with open(_diar.row_vectors_path(EMB), encoding="utf-8") as f:
            cache = json.load(f)
        self.assertEqual(sorted(cache["大空スバル"]), ["material:ka#r0", "material:ka#r2", "material:kb#r0", "material:kb#r2"])
        # かけら kb を外してまとめ直す(控えの特徴から・音は取り直さない)
        cache["大空スバル"]["material:kb#r0"]["vec"] = [0.0, 1.0, 0.0]
        cache["大空スバル"]["material:kb#r2"]["vec"] = [0.0, 1.0, 0.0]
        with open(_diar.row_vectors_path(EMB), "w", encoding="utf-8") as f:
            json.dump(cache, f)
        un = {"id": "j2", "spec": {"embedding": EMB, "name": "大空スバル", "docs": ["material:kb"], "title": "t"}, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}
        _speakers.run_voice_unlearn(un)
        self.assertEqual(un["state"], "done", un.get("error"))
        v = _diar.load_voices(EMB)["大空スバル"]
        self.assertEqual([x["doc"] for x in v["learnedFrom"]], ["material:ka"])
        self.assertEqual(v["vec"], [1.0, 0.0, 0.0])
        self.assertEqual(sorted(v["excluded"]), ["material:kb#r0", "material:kb#r2"])
        un2 = dict(un, id="j3", state="queued", spec=dict(un["spec"], docs=["material:ka"]))
        _speakers.run_voice_unlearn(un2)   # 何も残らない = その人の声を消す
        self.assertNotIn("大空スバル", _diar.load_voices(EMB))


if __name__ == "__main__":
    unittest.main()
