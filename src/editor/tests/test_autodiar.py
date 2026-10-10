#!/usr/bin/env python3
"""文字起こしのあとの話者の自動判別(v0.50.0。ed_speakers の autodiar_*・eval/drill/evalbatch の後追い)のテスト。

    py -3.10 -m unittest src/editor/tests/test_metrics.py    # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest src/editor/tests/test_autodiar.py   # これだけ
ffmpeg が必要(小さな動画を lavfi で作る)。ワーカーのスレッドは動かさず、待機列のジョブをテストがその場で動かす(疑似の認識・疑似の話者判別
diarize_fake = 10 秒ごとに入れ替わる・声の特徴 embed_fake = 同じ入れ替わり)。
評価用の文書: 文字起こしのあと判別のジョブが足される → 覚えた声 → 名前の候補(suggest)をいちばん長く話した人に → diar.json に by: context。
人が付けた話者・確かめ済みは触らない・評価用でない文書は設定 autoDiarize のときだけ・部品が無ければ黙って飛ばす・
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
import serve as S  # noqa: E402
from eval.drill import drill as ed_drill  # noqa: E402   (RS4-2 に editor/ed_drill.py から)
from eval.drill import evalbatch as EB  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from human.proof import speakers as proof_speakers  # noqa: E402
from human.proof import store  # noqa: E402
from flow import jobs  # noqa: E402
from eval.drill import folders as EF  # noqa: E402   評価用のフォルダの整理(RS3-E7 に ed_relink から)
from test_evalbatch import FFMPEG, MEMBER, _make_video  # noqa: E402

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
        self.tmp = tempfile.mkdtemp()
        self.ev = tempfile.mkdtemp()
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.VOICES_DIR)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = os.path.join(self.tmp, "transcripts"), os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")
        S.VOICES_DIR = os.path.join(self.tmp, "voices")
        os.makedirs(S.TX_DIR)
        self.old_jobs = (dict(jobs._jobs), list(jobs._order))
        jobs._jobs.clear()
        jobs._order.clear()
        self.drain()
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
        EB.eb_shutdown()
        self.env.stop()
        self.drain()
        jobs._jobs.clear()
        jobs._jobs.update(self.old_jobs[0])
        jobs._order[:] = self.old_jobs[1]
        S.TX_DIR, S.TMP_DIR, S.SETTINGS, S.VOICES_DIR = self.saved
        ed_drill._drill_cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.ev, ignore_errors=True)

    # -- 道具
    def drain(self):
        while not jobs._queue.empty():
            jobs._queue.get_nowait()

    def settings(self, d):
        with open(S.SETTINGS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

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
        return S.read_diar(tid)["latest"]

    def age(self, tid, at=OLD):
        """人が直したのは 10 分より前のこと、にする(直近に直した文書は後回し・ドリルに出さない、を外す)"""
        d = self.doc(tid)
        d["updatedAt"] = at
        S.atomic_write(S.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))

    def learn_voice(self, name, idx):
        """覚えた声(embed_fake と同じ向き: idx = 0 は 1 人目・1 は 2 人目)"""
        v = [0.1] * 8
        v[idx] = 1.0
        S.save_voices(S.DIAR_EMB_DEFAULT, {name: {"vec": S._unit(v), "rows": 3, "sec": 30.0, "updatedAt": 1}})

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
        self.assertTrue(S.drill_candidates(tid)["noSpeaker"] == 0)

    def test_two_speakers_longest_gets_the_name(self):
        tid, _ = self.transcribe(self.put(self.mem, "b.mp4", long=True))
        self.run_one(self.diar_jobs(tid)[0])
        self.assertEqual(self.names(tid), {"S1": "ときのそら", "S2": "話者2"})   # 話した秒がいちばん長い 1 人目に・ほかは仮の名前のまま
        self.assertEqual(self.diar(tid)["voices"]["speakers"]["S2"].get("by"), None)
        self.assertTrue(all(g["speaker"] in ("S1", "S2") for g in self.text_rows(tid)))   # 仮の名前でも「全行に話者」

    def test_learned_voice_wins_and_name_is_not_reused(self):
        self.learn_voice("ときのそら", 0)   # 1 人目の声 = ときのそら(覚えた声)。候補も「ときのそら」→ もう使われているので付けない
        tid, _ = self.transcribe(self.put(self.mem, "c.mp4", long=True))
        self.run_one(self.diar_jobs(tid)[0])
        self.assertEqual(self.names(tid), {"S1": "ときのそら", "S2": "話者2"})
        v = self.diar(tid)["voices"]
        self.assertEqual(v["speakers"]["S1"]["by"], "threshold")
        self.assertEqual(v["context"], {"name": "ときのそら", "speaker": None, "reason": "name_in_use"})

    def test_learned_voice_and_context_name_for_the_other(self):
        self.learn_voice("白上フブキ", 0)   # 1 人目は覚えた声で白上フブキ → まだ仮の名前の 2 人目に候補の名前
        tid, _ = self.transcribe(self.put(self.mem, "d.mp4", long=True))
        self.run_one(self.diar_jobs(tid)[0])
        self.assertEqual(self.names(tid), {"S1": "白上フブキ", "S2": "ときのそら"})
        v = self.diar(tid)["voices"]["speakers"]
        self.assertEqual((v["S1"]["by"], v["S2"]["by"], v["S2"]["label"]), ("threshold", "context", 1))

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

    def test_doc_with_speakers_is_not_touched(self):
        tid, _ = self.transcribe(self.put(self.mem, "f.mp4"))
        (dj,) = self.diar_jobs(tid)
        d = self.doc(tid)   # 待っている間に人が 1 行だけ話者を付けた
        d["speakers"] = [{"id": "A", "name": "人が付けた", "color": "#888"}]
        d["segments"][0]["speaker"] = "A"
        S.atomic_write(S.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))
        self.run_one(dj)
        self.assertEqual(dj["autoSkipped"], "has_speakers")
        self.assertEqual(self.names(tid), {"A": "人が付けた"})
        self.assertEqual(self.doc(tid)["segments"][0]["speaker"], "A")
        self.assertIsNone(S.read_diar(tid))
        self.assertEqual(S.autodiar_enqueue(tid), {"skipped": "has_speakers"})

    def test_all_rows_with_speakers_is_not_touched(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_AUTO_DIARIZE": "off"}):
            tid, _ = self.transcribe(self.put(self.mem, "g.mp4"))
        self.assertEqual(self.diar_jobs(tid), [])
        S.single_speaker(tid, "星街すいせい")   # 人が「全行をこの人に」
        self.assertEqual(S.autodiar_enqueue(tid), {"skipped": "has_speakers"})
        self.assertEqual(self.diar_jobs(tid), [])

    def test_reviewed_is_not_touched(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_AUTO_DIARIZE": "off"}):
            tid, _ = self.transcribe(self.put(self.mem, "h.mp4"))
        d = self.doc(tid)
        d["evalReviewed"] = {"at": 5, "rows": 1, "durationSec": 2.0}
        S.atomic_write(S.tx_path(tid), json.dumps(d, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(S.autodiar_enqueue(tid), {"skipped": "reviewed"})

    def test_non_eval_only_with_setting(self):
        other = os.path.join(self.src, "other.mp4")   # 評価用のフォルダの外
        shutil.copy2(self.short, other)
        tid, _ = self.transcribe(other)
        self.assertEqual(self.diar_jobs(tid), [])   # 既定はオフ
        self.settings({"evalDirs": [self.ev], "autoDiarize": True})
        tid2, _ = self.transcribe(other)
        (dj,) = self.diar_jobs(tid2)
        self.assertEqual((dj["spec"]["autoEval"], dj["spec"]["contextName"]), (False, None))   # 名前の候補は評価用だけ
        self.run_one(dj)
        self.assertEqual(self.names(tid2), {"S1": "話者1"})
        self.assertNotIn("evalSet", self.doc(tid2))
        tid3, _ = self.transcribe(other, autoDiarize=False)   # 要求が優先
        self.assertEqual(self.diar_jobs(tid3), [])
        self.assertIs(doc_jobs.validate_job({"sourcePath": other, "model": "small"})["autoDiarize"], True)
        os.unlink(other)

    def test_no_sherpa_skips_silently_for_eval(self):
        with mock.patch.object(proof_speakers, "autodiar_ready", return_value=False):
            tid, tj = self.transcribe(self.put(self.mem, "j.mp4"))
            self.assertEqual(self.diar_jobs(tid), [])
            self.assertFalse(tj.get("warnings"))   # 評価用: 黙って飛ばす(人が「全行をこの人に」)
            other = os.path.join(self.src, "other2.mp4")
            shutil.copy2(self.short, other)
            _tid2, tj2 = self.transcribe(other, autoDiarize=True)
            self.assertTrue(any("sherpa-onnx" in w for w in tj2.get("warnings") or []))   # 設定でオンにした人には知らせる
            os.unlink(other)
        self.assertEqual(self.doc(tid).get("evalSet"), True)

    def test_enqueue_failure_keeps_transcription(self):
        with mock.patch.object(proof_speakers, "autodiar_enqueue", side_effect=S.ApiError("busy", "待機中のジョブが多すぎます", 429)):
            tid, tj = self.transcribe(self.put(self.mem, "k.mp4"))
        self.assertEqual(tj["state"], "done")   # 文字起こしは成功のまま・注意だけ
        self.assertTrue(any("話者の自動判別を始められませんでした" in w for w in doc_jobs.public_job(tj)["warnings"]))
        self.assertTrue(self.text_rows(tid))

    # -- ドリル
    def test_waiting_doc_is_not_in_drill(self):
        tid, _ = self.transcribe(self.put(self.mem, "l.mp4"))
        self.age(tid)
        (dj,) = self.diar_jobs(tid)
        r = S.drill_next()
        self.assertEqual((r["id"], r["counts"]["busy"]), (None, 1), r)   # 判別の待ちの文書は出さない
        self.run_one(dj)
        self.age(tid)
        self.assertEqual(S.drill_next()["id"], tid)   # 判別が済めば出る(話者付き)

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
        with mock.patch.dict(os.environ, {"TRANSCRIBE_AUTO_DIARIZE": "off"}):   # 以前の版で文字起こしした文書(話者なし・判別したことが無い)
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
        S.single_speaker(tid, "ときのそら")
        self.age(tid)
        other = os.path.join(self.src, "other3.mp4")
        shutil.copy2(self.short, other)
        tid2, _ = self.transcribe(other)   # 評価用でない(話者なし)
        self.age(tid2)
        ready, recent = EB.eb_diar_candidates(set())
        self.assertEqual((ready, recent), ([], 0))
        os.unlink(other)

    def test_backlog_off_without_sherpa(self):
        tid = self._old_doc_without_diar("r.mp4")
        self.age(tid)
        EB.eval_batch_start()
        with mock.patch.object(proof_speakers, "autodiar_ready", return_value=False):
            r = EB.eb_tick("test")
        self.assertEqual(r.get("diarAdded"), 0, r)
        self.assertEqual(self.diar_jobs(tid), [])
        self.assertEqual(EB.eb_read()["diar"], {})


if __name__ == "__main__":
    unittest.main()
