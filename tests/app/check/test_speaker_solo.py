"""「確かめる」のソロから声を覚えるカード(speaker:solo・src/app/check/speaker_solo.py。11-02 話者の物差し 14 章 ①)の単体テスト:
一覧の読み・声がいちばん多い 10 秒・カードの形(コラボの 10 秒と同じ画面)・答えで覚えるか(配信者 1 人だけ・印なしだけ)・
見回り(覚えるジョブ voice-learn-clips の中身・Z で戻した分を外す voice-unlearn・失敗は 1 日待つ)・
覚える本体と外す本体(human/proof/speakers。声の特徴は偽物)。一時フォルダの作業データだけを使う。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_speaker_solo.py -v
"""
import io
import json
import os
import struct
import sys
import types
import unittest
import wave
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import deck, lineup, sources, speaker_solo as SS, voice_unknown  # noqa: E402
from flow import diar as _diar, jobs as _heavy  # noqa: E402
from human.check import apply  # noqa: E402
from human.proof import speakers as _speakers  # noqa: E402
from pipeline.transcribe import diarize as transcribe_diarize, recognize as _recognize  # noqa: E402

EMB = _diar.learn_embedding("")


class State:
    def effective(self):
        return []


def solo(key, video, who="大空スバル", speech=((2.0, 4.0), (20.0, 30.0), (31.0, 33.0))):
    return {"key": key, "video": video, "title": "配信 " + video, "who": who, "at": 1200.0, "sec": 48.0, "speech": [list(x) for x in speech]}


class SpeakerSoloTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-check-solo-")
        os.makedirs(os.path.join(self.app, "check", SS.DIR_NAME))
        cards = [solo("ka", "AAAAAAAAAAA"), solo("kb", "AAAAAAAAAAA", speech=()), solo("kc", "BBBBBBBBBBB", who="白上フブキ"),
                 solo("kz", "CCCCCCCCCCC"), {"key": "BAD", "video": "x"}]
        with open(os.path.join(self.app, "check", SS.NAME), "w", encoding="utf-8") as f:
            json.dump({"cards": cards}, f, ensure_ascii=False)
        for k in ("ka", "kb", "kc"):   # kz は音が無い = カードにしない
            open(os.path.join(self.app, "check", SS.DIR_NAME, k + ".wav"), "wb").close()
        self.ctx = apply.Context(self.app)
        self.jobs, self.logs = [], []

        def add_job(spec, kind):
            self.jobs.append((kind, spec))
            return {"id": "job%d" % len(self.jobs)}
        for p in (mock.patch.object(_diar, "VOICES_DIR", os.path.join(self.app, "voices")),
                  mock.patch.dict(_heavy.JOB_RUNNERS, {"voice-learn-clips": lambda job: None, "voice-unlearn": lambda job: None}),
                  mock.patch.object(_diar, "voice_ready", return_value=True), mock.patch.object(_heavy, "add_job", side_effect=add_job),
                  mock.patch.object(_heavy, "active_jobs", return_value=[])):
            p.start()
            self.addCleanup(p.stop)

    def cards(self):
        return {c["target"]["solo"]: c for c in SS.speaker_solo(sources.View(types.SimpleNamespace(root=None, env=None, app_dir=self.app), State()))}

    def tick(self, now=1000.0):
        return SS.tick(self.app, lambda: None, self.logs.append, now=now)

    def answer(self, key, a):
        return apply.answer(self.ctx, self.cards()[key], {"answer": a})

    def test_cards_and_piece(self):
        got = self.cards()
        self.assertEqual(sorted(got), ["ka", "kb", "kc"])   # 形の違う物・音の無い物は出さない
        c = got["ka"]
        self.assertEqual(lineup.parse_id(c["id"])[:2], ("speaker", "solo"))
        self.assertEqual((c["target"]["piece"], c["media"]["start"], c["media"]["end"]), ([20.0, 30.0], 0.0, 10.0))   # 声がいちばん多い 10 秒・音はその 10 秒だけ
        self.assertFalse(c["_first"])
        self.assertEqual((c["media"]["url"], c["cast"], c["people"], c["who"]), ("api/check/voicesolo?key=ka", ["大空スバル"], ["大空スバル"], "大空スバル"))
        self.assertNotIn("大空スバル", c["pick"])
        self.assertEqual(got["kb"]["target"]["piece"], [19.0, 29.0])   # speech が無ければ真ん中
        self.assertEqual(SS.piece(6.0, [(1.0, 2.0)]), (0.0, 6.0))
        self.assertIn("speaker", deck.KIND_GROUP["voice"])

    def test_first_people_and_clip_piece(self):
        with open(os.path.join(self.app, "check", SS.NAME), "w", encoding="utf-8") as f:
            json.dump({"cards": [solo("ka", "AAAAAAAAAAA", who="博衣こより"), solo("kb", "BBBBBBBBBBB")]}, f, ensure_ascii=False)
        rate = 16000
        with wave.open(os.path.join(self.app, "check", SS.DIR_NAME, "ka.wav"), "wb") as w:   # 48 秒・1 秒ごとに値の違う音
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(struct.pack("<h", sec) * rate for sec in range(48)))
        got = self.cards()
        self.assertEqual((got["ka"]["_first"], got["kb"]["_first"]), (True, False))   # 優先の人(FIRST_PEOPLE)は先頭に出す印
        data = SS.clip_piece(self.app, "ka")
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.readframes(w.getnframes())
            self.assertEqual((w.getnframes(), w.getframerate()), (10 * rate, rate))   # 10 秒だけ
        self.assertEqual((struct.unpack("<h", frames[:2])[0], struct.unpack("<h", frames[-2:])[0]), (20, 29))   # 20〜30 秒
        self.assertIsNone(SS.clip_piece(self.app, "kz"))
        self.assertIsNone(SS.clip_piece(self.app, "kb"))   # 空の音 = 読めない

    def test_unknown_keeps_audio_and_listing(self):
        """[分からない] = 音(ソロは選んだ 10 秒だけ)と位置を控え、一覧に出す。Z で戻すと一覧から外れる。声は覚えない(11-02)"""
        rate = 8000
        with wave.open(os.path.join(self.app, "check", SS.DIR_NAME, "ka.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"".join(struct.pack("<h", sec) * rate for sec in range(48)))
        u = apply.unknown(self.ctx, self.cards()["ka"])
        got = voice_unknown.listing(self.app)
        self.assertEqual([(r["id"], r["card"], r["kind"], r["source"], r["key"], r["piece"]) for r in got], [(u["answer"], self.cards()["ka"]["id"], "speaker", "solo", "ka", [20.0, 30.0])])
        with wave.open(got[0]["file"], "rb") as w:
            self.assertEqual(w.getnframes(), 10 * rate)
        self.assertIsNone(self.tick())   # 声は覚えない
        apply.undo(self.ctx, u["answer"])
        self.assertEqual(voice_unknown.listing(self.app), [])
        self.assertTrue(os.path.isfile(got[0]["file"]))   # 音の控えは残す

    def test_answers_learn_only_streamer_alone(self):
        a = self.answer("ka", {"names": ["大空スバル"]})
        self.assertEqual(a["applied"]["learn"], {"name": "大空スバル", "start": 20.0, "end": 30.0, "sec": 10.0})
        self.assertEqual(a["applied"]["piece"], [20.0, 30.0])
        apply.undo(self.ctx, a["answer"])
        for ans in ({"names": ["大空スバル"], "bgm": True}, {"names": ["大空スバル"], "alt": True}, {"names": ["大空スバル", "白上フブキ"]},
                    {"names": ["ゲームの声"]}, {"names": ["その他の人"]}, {"choice": "other"}):
            r = self.answer("ka", ans)
            self.assertIsNone(r["applied"]["learn"], ans)
            apply.undo(self.ctx, r["answer"])
        with self.assertRaises(apply.Refused):
            self.answer("ka", {"names": []})

    def test_tick_learn_and_unlearn_on_undo(self):
        self.assertIsNone(self.tick())   # 答えが無い = 何も入れない(人が確かめていない物は入れない)
        a = self.answer("ka", {"names": ["大空スバル"]})
        self.answer("kc", {"names": ["白上フブキ"], "bgm": True})   # 印あり = 覚えない
        self.assertEqual(self.tick(), "voice-learn-clips")
        kind, spec = self.jobs[0]
        self.assertEqual(spec["clips"], [{"doc": "solo:ka", "clip": SS.clip_path(self.app, "ka"), "names": ["大空スバル"], "groups": {"大空スバル": [[20.0, 30.0]]},
                                          "rowIds": {"大空スバル": ["w"]}, "sure": True, "by": "check"}])
        self.assertEqual(SS.read_state(self.app)["asked"], {"solo:ka": {"job": "job1", "at": 1000000}})
        # ジョブが終わったのに入っていない = 失敗(1 日待つ)
        self.assertIsNone(self.tick(now=2000.0))
        self.assertEqual(sorted(SS.read_state(self.app)["failed"]), ["solo:ka"])
        self.assertEqual(self.tick(now=2000.0 + SS.RETRY_SEC), "voice-learn-clips")
        with _diar.voices_edit(EMB) as v:   # 入った
            v["大空スバル"] = _diar.merge_voice(None, [1.0, 0.0], 1, 10.0, "solo:ka", row_ids=["w"])
        self.jobs.clear()
        self.assertIsNone(self.tick(now=3000.0 + SS.RETRY_SEC))
        self.assertEqual(SS.read_state(self.app), {"asked": {}, "failed": {}})
        apply.undo(self.ctx, a["answer"])   # Z = 登録簿からも外す
        self.assertEqual(self.tick(now=4000.0 + SS.RETRY_SEC), "voice-unlearn")
        self.assertEqual((self.jobs[0][1]["name"], self.jobs[0][1]["docs"]), ("大空スバル", ["solo:ka"]))
        with mock.patch.object(SS.voice_mod, "RELEARN_PAUSED", True):
            self.assertIsNone(self.tick(now=5000.0 + SS.RETRY_SEC))   # 覚え直しの一時止めの間は休む

    def test_tick_batch_small_while_recording(self):
        """録画中は入口が batch = LIVE_BATCH を渡し、1 つのジョブを小さくする(編集のジョブは 1 本ずつ = 録画の文字起こしを長く待たせない。11-02)"""
        self.answer("ka", {"names": ["大空スバル"]})
        self.answer("kb", {"names": ["大空スバル"]})
        self.assertEqual(SS.tick(self.app, lambda: None, self.logs.append, now=1000.0, batch=1), "voice-learn-clips")
        self.assertEqual([c["doc"] for c in self.jobs[0][1]["clips"]], ["solo:ka"])
        self.assertIsNone(SS.tick(self.app, lambda: "CPU 55%", self.logs.append, now=1000.0, batch=1))   # 入口の busy が理由を返せば始めない

    def test_run_learn_clips_and_unlearn(self):
        tmp = os.path.join(self.app, "tmp")
        clip = SS.clip_path(self.app, "ka")
        spec = {"embedding": EMB, "by": "check", "title": "t", "clips": [
            {"doc": "solo:ka", "clip": clip, "names": ["大空スバル"], "groups": {"大空スバル": [[20.0, 30.0]]}, "rowIds": {"大空スバル": ["w"]}, "sure": True, "by": "check"},
            {"doc": "solo:kz", "clip": os.path.join(self.app, "nope.wav"), "names": ["大空スバル"], "groups": {"大空スバル": [[0.0, 10.0]]}, "rowIds": {"大空スバル": ["w"]}, "sure": True},
            {"doc": "solo:kb", "clip": clip, "names": ["大空スバル"], "groups": {"大空スバル": [[19.0, 29.0]]}, "rowIds": {"大空スバル": ["w"]}, "sure": True, "by": "check"}]}
        job = {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}
        with mock.patch.dict(_heavy._conf, {"tmp_dir": lambda: tmp}), mock.patch.object(_recognize, "extract_audio", lambda *a: None), \
                mock.patch.object(transcribe_diarize, "has_sherpa", lambda: True), mock.patch.object(transcribe_diarize, "ensure_diar_models", lambda *a: None), \
                mock.patch.object(transcribe_diarize, "embed_groups", lambda job, wav, e, groups, off: [transcribe_diarize._unit([1.0, 0.0, 0.0]) for _ in groups]):
            _speakers.run_voice_learn_clips(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual((job["learned"], list(job["failed"])), (["solo:ka", "solo:kb"], ["solo:kz"]))   # 音の無い物は飛ばして続ける
        v = _diar.load_voices(EMB)["大空スバル"]
        self.assertEqual([(x["doc"], x["sure"], x["by"], x["rows"]) for x in v["learnedFrom"]], [("solo:ka", True, "check", ["w"]), ("solo:kb", True, "check", ["w"])])
        with open(_diar.row_vectors_path(EMB), encoding="utf-8") as f:
            cache = json.load(f)
        self.assertEqual(sorted(cache["大空スバル"]), ["solo:ka#w", "solo:kb#w"])
        cache["大空スバル"]["solo:kb#w"]["vec"] = [0.0, 1.0, 0.0]
        with open(_diar.row_vectors_path(EMB), "w", encoding="utf-8") as f:
            json.dump(cache, f)
        un = {"id": "j2", "spec": {"embedding": EMB, "name": "大空スバル", "docs": ["solo:kb"], "title": "t"}, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}
        _speakers.run_voice_unlearn(un)   # 控えの特徴からまとめ直す(音は取り直さない)
        self.assertEqual(un["state"], "done", un.get("error"))
        v = _diar.load_voices(EMB)["大空スバル"]
        self.assertEqual(([x["doc"] for x in v["learnedFrom"]], v["vec"], v["excluded"]), (["solo:ka"], [1.0, 0.0, 0.0], ["solo:kb#w"]))
        _speakers.run_voice_unlearn(dict(un, id="j3", state="queued", spec=dict(un["spec"], docs=["solo:ka"])))   # 何も残らない = その人の声を消す
        self.assertNotIn("大空スバル", _diar.load_voices(EMB))


if __name__ == "__main__":
    unittest.main()
