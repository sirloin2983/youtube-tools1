#!/usr/bin/env python3
"""評価用の文書の文字起こしのあとの話者の自動判別(human/proof/speakers の autodiar_*・eval/drill/evalbatch の後追い)のテスト。

    py -3.12 -m unittest src/editor/tests/test_metrics.py    # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest src/editor/tests/test_autodiar.py   # これだけ
ffmpeg が必要(小さな動画を lavfi で作る)。ワーカーのスレッドは動かさず、待機列のジョブをテストがその場で動かす(疑似の認識・疑似の話者判別
diarize_fake = 10 秒ごとに入れ替わる・声の特徴 embed_fake = 同じ入れ替わり)。
評価用の文書: 文字起こしのあと判別のジョブが足される → 覚えた声 → 名前の候補(suggest)をいちばん長く話した人に → diar.json に by: context。
人が付けた話者・確かめ済みは触らない・評価用でない文書は判別しない・部品が無ければ黙って飛ばす・
まとめての文字起こしの後追いは文書ごとに 1 回・直近に直した文書は後回し・判別の待ちの文書はドリルに出ない。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import serve  # noqa: E402
import ed_state  # noqa: E402
from flow import diar as _diar  # noqa: E402
from pipeline.transcribe import diarize as _diarize  # noqa: E402
from ytt import workdata as _workdata  # noqa: E402
from eval.drill import drill as ed_drill  # noqa: E402 
from eval.drill import evalbatch as EB  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from human.proof import speakers as proof_speakers  # noqa: E402
from human.proof import store  # noqa: E402
from flow import jobs  # noqa: E402
from manage.keep import evalfolders as EF  # noqa: E402
from test_evalbatch import FFMPEG, MEMBER, _make_video, stop_batch  # noqa: E402
from ytt.tests import testkit  # noqa: E402

OLD = 1000   # 10 分より前に直した、の updatedAt(ミリ秒)


@unittest.skipUnless(FFMPEG, "ffmpeg が必要")
class TestAutoDiar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = tempfile.mkdtemp()
        cls.short = os.path.join(cls.src, "short.mp4")
        cls.long = os.path.join(cls.src, "long.mp4")
        _make_video(cls.short, 2)    # 偽の判別で 1 人
        _make_video(cls.long, 25)    # 偽の判別で 2 人(0〜10・20〜25 秒 = 15 秒が 1 人目、10〜20 秒が 2 人目)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.ev = testkit.tempdir(self)
        self.saved = (_workdata.TX_DIR, _workdata.TMP_DIR, _workdata.SETTINGS, _diar.VOICES_DIR)
        _workdata.TX_DIR, _workdata.TMP_DIR, _workdata.SETTINGS = os.path.join(self.tmp, "transcripts"), os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")
        _diar.VOICES_DIR = os.path.join(self.tmp, "voices")
        os.makedirs(_workdata.TX_DIR)
        self.old_jobs = dict(jobs._jobs)
        jobs._jobs.clear()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off",
                                                "TRANSCRIBE_EVAL_BATCH": "off", "TRANSCRIBE_AUTO_DIARIZE": ""})
        self.env.start()
        self.stg = os.path.join(self.ev, EF.EVAL_STAGING)
        self.mem = os.path.join(self.ev, "1_JP", MEMBER)   # メンバーのフォルダ「評価用データ01_ときのそら」= 名前の候補「ときのそら」
        os.makedirs(self.stg)
        os.makedirs(self.mem)
        self.settings({"evalDirs": [self.ev]})
        ed_drill._drill_cache.clear()

    def tearDown(self):
        stop_batch()
        self.env.stop()
        jobs._jobs.clear()
        jobs._jobs.update(self.old_jobs)
        _workdata.TX_DIR, _workdata.TMP_DIR, _workdata.SETTINGS, _diar.VOICES_DIR = self.saved
        ed_drill._drill_cache.clear()

    # -- 道具
    def settings(self, d):
        testkit.write_json(_workdata.SETTINGS, d)

    def put(self, folder, name, long=False):
        p = os.path.join(folder, name)
        shutil.copy2(self.long if long else self.short, p)
        return p

    def run_one(self, job):   # 偽のワーカー
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def transcribe(self, path, **req):
        job = self.run_one(jobs.add_job(doc_jobs.validate_job(dict({"sourcePath": path, "model": "small"}, **req))))
        return job["tid"], job

    def diar_jobs(self, tid=None, states=jobs.ACTIVE_STATES):
        return [j for j in jobs._jobs.values() if j.get("kind") == "diarize" and (tid is None or j.get("tid") == tid) and j["state"] in states]

    def doc(self, tid):
        return store.read_transcript(tid)

    def names(self, tid):
        return {s["id"]: s["name"] for s in self.doc(tid).get("speakers") or []}

    def diar(self, tid):
        return _diarize.read_diar(tid)["latest"]

    def age(self, tid, at=OLD):
        """人が直したのは 10 分より前のこと、にする(直近に直した文書は後回し・ドリルに出さない、を外す)"""
        d = self.doc(tid)
        d["updatedAt"] = at
        ed_state.atomic_write(store.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))

    def learn_voice(self, name, idx):
        """覚えた声(embed_fake と同じ向き: idx = 0 は 1 人目・1 は 2 人目)"""
        v = [0.1] * 8
        v[idx] = 1.0
        _diar.save_voices(_diarize.DIAR_EMB_DEFAULT, {name: {"vec": _diarize._unit(v), "rows": 3, "sec": 30.0, "updatedAt": 1}})

    def text_rows(self, tid):
        return [g for g in self.doc(tid)["segments"] if g["text"].strip()]

    # -- 評価用の文字起こしのあと
    def test_eval_transcribe_adds_diarize_and_names_single_speaker(self):
        tid, tj = self.transcribe(self.put(self.mem, "a.mp4"))
        (dj,) = self.diar_jobs(tid)
        sp = dj["spec"]
        self.assertEqual((sp["auto"], sp["autoEval"], sp["contextName"], sp["numSpeakers"], sp["recognize"]), (True, True, "ときのそら", 0, True))
        self.assertFalse(tj.get("warnings"))
        self.assertTrue(doc_jobs.public_job(dj)["auto"])
        self.run_one(dj)
        self.assertEqual(self.names(tid), {"S1": "ときのそら"})   # 1 人だけ → その人に
        self.assertTrue(all(g["speaker"] == "S1" for g in self.text_rows(tid)))
        dz = self.doc(tid)["diarization"]
        self.assertEqual((dz["auto"], dz["contextName"]), (True, "ときのそら"))
        run = self.diar(tid)
        self.assertEqual(run["auto"], {"eval": True, "contextName": "ときのそら"})
        self.assertEqual((run["voices"]["speakers"]["S1"]["decided"], run["voices"]["speakers"]["S1"]["by"]), ("ときのそら", "context"))
        self.assertEqual(run["voices"]["context"], {"name": "ときのそら", "speaker": "S1", "reason": None})
        self.assertEqual([(x["name"], x["by"]) for x in dj["named"]], [("ときのそら", "context")])
        self.assertTrue(ed_drill.drill_candidates(tid)["noSpeaker"] == 0)

    def test_two_speakers_names(self):
        """2 人の動画(候補の名前 = ときのそら)。覚えた声が無ければ話した秒が長い 1 人目に・覚えた声が候補と同じ名前ならその人が先で候補は使われている
        ので付けない・覚えた声が別の名前なら 2 人目に候補の名前"""
        talk = {"S1": "ときのそら", "S2": "話者2"}
        for voice, names, by, context in (
                (None, talk, {"S2": None}, None),
                ("ときのそら", talk, {"S1": "threshold"}, {"name": "ときのそら", "speaker": None, "reason": "name_in_use"}),
                ("白上フブキ", {"S1": "白上フブキ", "S2": "ときのそら"}, {"S1": "threshold", "S2": "context"}, None)):
            with self.subTest(voice=voice):
                if voice:
                    self.learn_voice(voice, 0)   # 1 人目の声 = 覚えた声
                tid, _ = self.transcribe(self.put(self.mem, "b%s.mp4" % (voice or ""), long=True))
                self.run_one(self.diar_jobs(tid)[0])
                self.assertEqual(self.names(tid), names)
                v = self.diar(tid)["voices"]
                self.assertEqual({k: v["speakers"][k].get("by") for k in by}, by)
                if context:
                    self.assertEqual(v["context"], context)
                if by.get("S2") == "context":
                    self.assertEqual(v["speakers"]["S2"]["label"], 1)   # 2 人目の声に付く
                self.assertTrue(all(g["speaker"] in ("S1", "S2") for g in self.text_rows(tid)))   # 仮の名前でも「全行に話者」

    def test_no_suggest_keeps_default_names(self):
        tid, _ = self.transcribe(self.put(self.stg, "e.mp4"))   # 仮置き: メンバーのフォルダも配信の手がかりも無い
        (dj,) = self.diar_jobs(tid)
        self.assertIsNone(dj["spec"]["contextName"])
        self.run_one(dj)
        self.assertEqual(self.names(tid), {"S1": "話者1"})
        run = self.diar(tid)
        self.assertEqual(run["auto"], {"eval": True, "contextName": None})
        self.assertNotIn("context", run["voices"])
        self.assertTrue(self.doc(tid)["diarization"]["auto"])

    def test_human_touched_docs_are_not_touched(self):
        """待っている間に人が話者を付けた文書・確かめ済みの文書は判別しない"""
        tid, _ = self.transcribe(self.put(self.mem, "f.mp4"))
        (dj,) = self.diar_jobs(tid)
        d = self.doc(tid)   # 待っている間に人が 1 行だけ話者を付けた
        d["speakers"] = [{"id": "A", "name": "人が付けた", "color": "#888"}]
        d["segments"][0]["speaker"] = "A"
        ed_state.atomic_write(store.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))
        self.run_one(dj)
        self.assertEqual(dj["autoSkipped"], "has_speakers")
        self.assertEqual(self.names(tid), {"A": "人が付けた"})
        self.assertEqual(self.doc(tid)["segments"][0]["speaker"], "A")
        self.assertIsNone(_diarize.read_diar(tid))
        self.assertEqual(proof_speakers.autodiar_enqueue(tid), {"skipped": "has_speakers"})
        d = self.doc(tid)
        d["segments"][0]["speaker"] = ""
        d["evalReviewed"] = {"at": 5, "rows": 1, "durationSec": 2.0}
        ed_state.atomic_write(store.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(proof_speakers.autodiar_enqueue(tid), {"skipped": "reviewed"})

    def test_non_eval_is_never_diarized(self):
        """評価用でない文書は、保存した設定・要求の autoDiarize があっても判別しない"""
        other = os.path.join(self.src, "other.mp4")   # 評価用のフォルダの外
        shutil.copy2(self.short, other)
        tid, _ = self.transcribe(other)
        self.assertEqual(self.diar_jobs(tid), [])
        self.settings({"evalDirs": [self.ev], "autoDiarize": True})   # 前に保存した設定が残っていても効かない
        tid2, _ = self.transcribe(other)
        self.assertEqual(self.diar_jobs(tid2), [])
        tid3, _ = self.transcribe(other, autoDiarize=True)
        self.assertEqual(self.diar_jobs(tid3), [])
        os.unlink(other)

    def test_no_sherpa_skips_silently(self):
        """部品が無ければ、評価用の文字起こしのあとも・まとめての後追いも、黙って飛ばす(人が「全行をこの人に」)"""
        with mock.patch.object(proof_speakers, "autodiar_ready", return_value=False):
            tid, tj = self.transcribe(self.put(self.mem, "j.mp4"))
            self.assertEqual(self.diar_jobs(tid), [])
            self.assertFalse(tj.get("warnings"))
        self.assertEqual(self.doc(tid).get("evalSet"), True)
        tid = self._old_doc_without_diar("r.mp4")
        self.age(tid)
        EB.eval_batch_start()
        with mock.patch.object(proof_speakers, "autodiar_ready", return_value=False):
            r = EB.eb_tick("test")
        self.assertEqual(r.get("diarAdded"), 0, r)
        self.assertEqual(self.diar_jobs(tid), [])
        self.assertEqual(EB.eb_read()["diar"], {})

    def test_enqueue_failure_keeps_transcription(self):
        with mock.patch.object(proof_speakers, "autodiar_enqueue", side_effect=ed_state.ApiError("busy", "待機中のジョブが多すぎます", 429)):
            tid, tj = self.transcribe(self.put(self.mem, "k.mp4"))
        self.assertEqual(tj["state"], "done")   # 文字起こしは成功のまま・注意だけ
        self.assertTrue(any("話者の自動判別を始められませんでした" in w for w in doc_jobs.public_job(tj)["warnings"]))
        self.assertTrue(self.text_rows(tid))

    # -- 評価用の作業の対象
    def test_waiting_doc_is_busy(self):
        tid, _ = self.transcribe(self.put(self.mem, "l.mp4"))
        (dj,) = self.diar_jobs(tid)
        self.assertIn(tid, ed_drill._busy_tids())   # 判別の待ちの文書は、ほかの評価用の作業の対象にしない
        self.run_one(dj)
        self.assertNotIn(tid, ed_drill._busy_tids())   # 判別が済めば対象になる

    # -- まとめての文字起こし(後追い)
    def test_batch_transcription_adds_marked_diarize(self):
        self.put(self.stg, "m.mp4")
        EB.eval_batch_start()
        EB.eb_tick("test")
        (tj,) = [j for j in jobs._jobs.values() if j.get("kind") == "transcribe"]
        self.run_one(tj)
        (dj,) = self.diar_jobs(tj["tid"])
        self.assertTrue(dj["spec"]["evalBatch"])   # 自分の印つき = 待ちの数に入る・ほかのジョブとして止まらない
        s = EB.eval_batch_status()
        self.assertEqual((s["diarActive"], s["diarWaiting"], s["active"]), (1, 1, 1), s)
        self.assertEqual(EB.eb_tick("test")["added"], 0)   # 文字起こしの残りは無い・判別の待ちがある間は終わらない
        self.assertTrue(EB.eval_batch_status()["enabled"])
        self.run_one(dj)
        EB.eb_tick("test")
        s = EB.eval_batch_status()
        self.assertEqual((s["enabled"], s["finished"], s["diarWaiting"], s["diarTried"]), (False, True, 0, 1), s)
        self.assertEqual(EB.eb_read()["diar"][tj["tid"]]["state"], "done")

    def _old_doc_without_diar(self, name, folder=None):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_AUTO_DIARIZE": "off"}):   # 話者なし・判別したことが無い文書
            tid, _ = self.transcribe(self.put(folder or self.mem, name))
        self.assertEqual(self.diar_jobs(tid), [])
        return tid

    def test_backlog_once_per_doc(self):
        tid = self._old_doc_without_diar("n.mp4")
        self.age(tid)
        EB.eval_batch_start()
        r = EB.eb_tick("test")
        self.assertEqual(r.get("diarAdded"), 1, r)
        (dj,) = self.diar_jobs(tid)
        self.assertTrue(dj["spec"]["evalBatch"] and dj["spec"]["auto"])
        self.assertEqual(dj["spec"]["contextName"], "ときのそら")
        self.assertEqual(EB.eval_batch_status()["diarWaiting"], 1)
        dj["state"], dj["error"] = "error", "テストの失敗"   # 失敗した(diar.json も無いまま)
        r = EB.eb_tick("test")
        self.assertEqual(r.get("diarAdded"), 0, r)   # もう一度は入れない
        self.assertEqual(self.diar_jobs(tid), [])
        st = EB.eb_read()["diar"][tid]
        self.assertEqual((st["via"], st["state"], st["error"]), ("backlog", "error", "テストの失敗"))
        s = EB.eval_batch_status()
        self.assertEqual((s["enabled"], s["finished"], s["diarTried"]), (False, True, 1), s)

    def test_backlog_runs_and_names(self):
        tid = self._old_doc_without_diar("o.mp4")
        self.age(tid)
        EB.eval_batch_start()
        EB.eb_tick("test")
        self.run_one(self.diar_jobs(tid)[0])
        self.assertEqual(self.names(tid), {"S1": "ときのそら"})
        self.age(tid)
        self.assertEqual(EB.eb_tick("test").get("diarAdded"), 0)   # 判別した(diar.json がある)文書は入れない

    def test_backlog_defers_recently_edited(self):
        tid = self._old_doc_without_diar("p.mp4")   # updatedAt = 今(直近に直した = 開いているかもしれない)
        EB.eval_batch_start()
        r = EB.eb_tick("test")
        self.assertEqual(r.get("diarAdded"), 0, r)
        s = EB.eval_batch_status()
        self.assertEqual((s["diarWaiting"], s["enabled"]), (1, True), s)   # 後回し(終わりにしない)
        self.age(tid)
        self.assertEqual(EB.eb_tick("test").get("diarAdded"), 1)

    def test_backlog_skips_docs_with_speakers_and_non_eval(self):
        tid = self._old_doc_without_diar("q.mp4")
        proof_speakers.single_speaker(tid, "ときのそら")
        self.age(tid)
        other = os.path.join(self.src, "other3.mp4")
        shutil.copy2(self.short, other)
        tid2, _ = self.transcribe(other)   # 評価用でない(話者なし)
        self.age(tid2)
        ready, recent = EB.eb_diar_candidates(set())
        self.assertEqual((ready, recent), ([], 0))
        os.unlink(other)


if __name__ == "__main__":
    unittest.main()
