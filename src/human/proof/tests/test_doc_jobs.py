# -*- coding: utf-8 -*-
"""human/proof/doc_jobs のテスト(差し込みの口 set_hooks は X-RERUN で消した・serve なしで読める・人の行の引き継ぎ)。

    py -3.12 -m unittest src/human/proof/tests/test_doc_jobs.py -v

doc_jobs は editor の部品を裸の名前(import ed_store など)で読むので、src と src/editor を sys.path に足す。編集の serve は読まない
(serve の登録で口が埋まり、評価用の作り直しの差し替えが本体に届くことは src/editor/tests/test_evalbatch.py・test_names.py が確かめる)。
"""
import contextlib
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> proof -> human -> src
EDITOR = os.path.join(SRC, "editor")
for _p in (EDITOR, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import doc_jobs, layers  # noqa: E402


class TestCarryOverrides(unittest.TestCase):
    """同じ動画の文書を作り直す(force の再文字起こし・エンジンを変えた再実行)と、前の文書の人の行が新しい文書に引き継がれる(RS6 b-O1。
    10-18 から重ね方は層の組み立て layers.carry・控え <id>.over.json は書かない・読まない)。
    認識(② flow/tx.transcribe_clip)と続きの処理は差し替えて、run_job の ③ の分だけを動かす"""
    OLD = "0123456789ab"

    def setUp(self):
        from ytt import workdata
        from human.proof import store
        self.workdata, self.store = workdata, store
        self.tmp = tempfile.mkdtemp(prefix="ytt-carry-")
        self.saved = (workdata.TX_DIR, workdata.SETTINGS)
        workdata.TX_DIR = os.path.join(self.tmp, "transcripts")
        workdata.SETTINGS = os.path.join(self.tmp, "settings.json")
        os.makedirs(workdata.TX_DIR)
        store._summary_cache.clear()
        self.src = os.path.join(self.tmp, "clip_0001.mp4")
        self.spec = {"sourcePath": self.src, "sourceName": "clip_0001.mp4", "title": "t", "start": 0.0, "end": 20.0, "evalSet": False}

    def tearDown(self):
        self.workdata.TX_DIR, self.workdata.SETTINGS = self.saved
        self.store._summary_cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_new(self, segs, spec=None):
        """新しい機械の行 segs で文字起こしのジョブを 1 本動かす -> (新しい文書, ジョブ)"""
        fields = {"start": 0.0, "end": 20.0, "whole": True, "duration": 20.0, "model": "small", "language": "ja", "params": {}, "speakers": [],
                  "segments": segs, "original": [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in segs], "updatedAt": 5000,
                  "recognition": {"runs": [{"engine": "fake"}]}}
        clip = {"fields": fields, "segs": segs}

        @contextlib.contextmanager
        def wav(job):
            yield os.path.join(self.tmp, "x.wav")
        job = {"id": "j1", "kind": "transcribe", "spec": dict(self.spec, **(spec or {}))}
        with mock.patch.object(doc_jobs._heavy, "job_temp_wav", wav), \
                mock.patch.object(doc_jobs._flowtx, "dict_pairs", lambda spec: []), \
                mock.patch.object(doc_jobs._flowtx, "transcribe_clip", lambda *a, **k: clip), \
                mock.patch.object(doc_jobs._flowtx, "write_clip_records", lambda *a, **k: None), \
                mock.patch.object(doc_jobs.speakers, "autodiar_after_transcribe", lambda *a: None), \
                mock.patch.object(doc_jobs.alt, "alt_after_transcribe", lambda *a: None):
            doc_jobs.run_job(job)
        self.store._summary_cache.clear()
        return self.store.read_transcript(job["tid"]), job

    def put_old(self, **over):
        old = {"schema": "transcribe/v1", "id": self.OLD, "title": "t", "sourcePath": self.src, "sourceName": "clip_0001.mp4",
               "speakers": [{"id": "A", "name": "ぺこら", "color": "#112233"}], "updatedAt": 1000,
               "original": [{"start": 0.0, "end": 2.0, "text": "こんばんわ"}, {"start": 2.5, "end": 4.0, "text": "まって"}, {"start": 5.0, "end": 6.0, "text": "えー"}],
               "segments": [{"id": "s1", "start": 0.0, "end": 2.0, "text": "こんばんわ", "speaker": "", "flag": ""},
                            {"id": "s2", "start": 2.5, "end": 4.0, "text": "待って", "speaker": "A", "flag": "", "proofed": True, "proofedAt": 900},
                            {"id": "s3", "start": 5.0, "end": 6.0, "text": "えーと", "speaker": "", "flag": ""},
                            {"id": "s4", "start": 9.0, "end": 10.0, "text": "人が足した行", "speaker": "", "flag": "", "proofed": True}]}
        old.update(over)
        self.store.write_doc(self.OLD, old)

    def test_human_rows_are_carried_to_new_doc(self):
        self.put_old()
        new_segs = [{"id": "s1", "start": 0.0, "end": 2.0, "text": "こんばんは(新)", "speaker": "", "flag": ""},
                    {"id": "s2", "start": 2.4, "end": 4.1, "text": "まってて", "speaker": "", "flag": "要確認"},
                    {"id": "s3", "start": 5.0, "end": 6.0, "text": "えー(新)", "speaker": "", "flag": ""}]
        doc, job = self.run_new(new_segs)
        self.assertNotEqual(doc["id"], self.OLD)
        segs = doc["segments"]
        self.assertEqual([g["text"] for g in segs], ["こんばんは(新)", "待って", "えーと", "人が足した行"])   # 触っていない行だけ新しい
        self.assertEqual((segs[1]["proofed"], segs[1]["proofedAt"], segs[1]["speaker"]), (True, 900, "A"))
        self.assertIn(layers.STALE_FLAG, segs[3]["flag"])                       # 対応する行が無い人の行は印つきで残す
        self.assertEqual([s["id"] for s in doc["speakers"]], ["A"])
        st = doc["recognition"]["runs"][-1]["override"]
        self.assertEqual((st["matched"], st["stale"], st["total"], st["from"]), (2, 1, 3, self.OLD))
        self.assertEqual([g["text"] for g in doc["original"]], ["こんばんは(新)", "まってて", "えー(新)"])   # 機械の出力は新しい認識のまま
        self.assertTrue(any("引き継ぎました" in w for w in job.get("warnings") or []))
        self.assertFalse(os.path.exists(os.path.join(self.workdata.TX_DIR, doc["id"] + ".over.json")))   # 控えはもう書かない
        old = self.store.read_transcript(self.OLD)
        self.assertEqual(old["segments"][1]["text"], "待って")                      # 前の文書はそのまま

    def test_carry_from_layered_doc(self):
        """層のある文書(人の層・機械の層)からも引き継ぐ: 機械の層と同じ文字の校正済みの行(人の層では属性の行)も、文字ごと残す。
        話者だけの行は新しい機械の行に話者を重ね、作り直した範囲の外の行は数えない"""
        self.put_old()
        old = self.store.read_transcript(self.OLD)
        self.store.commit(self.OLD, old, why="save")   # 層を書く(機械の層は original から)
        old = self.store.read_transcript(self.OLD)
        old["segments"][0].update(proofed=True)         # 機械と同じ文字で校正済み
        old["segments"][2].update(text="えー", speaker="A")   # 文字は機械に戻して話者だけ
        old["segments"].append({"id": "s9", "start": 30.0, "end": 31.0, "text": "範囲の外", "speaker": "", "flag": "", "proofed": True})
        self.store.commit(self.OLD, old, why="save")
        self.assertTrue(os.path.isfile(os.path.join(self.workdata.TX_DIR, self.OLD + ".hum.json")))
        doc, _job = self.run_new([{"id": "s1", "start": 0.0, "end": 2.0, "text": "こんばんは(新)", "speaker": "", "flag": ""},
                                  {"id": "s2", "start": 5.0, "end": 6.0, "text": "えー(新)", "speaker": "", "flag": "要確認"}])
        segs = doc["segments"]
        self.assertEqual([g["text"] for g in segs], ["こんばんわ", "待って", "えー(新)", "人が足した行"])
        self.assertTrue(segs[0].get("proofed"))
        self.assertEqual((segs[2]["speaker"], segs[2]["flag"]), ("A", "要確認"))   # 話者だけ重ね、文字と印は新しい機械
        self.assertIn(layers.STALE_FLAG, segs[1]["flag"])   # 新しい機械に対応する行が無い
        st = doc["recognition"]["runs"][-1]["override"]
        self.assertEqual((st["total"], st["outside"]), (4, 1))
        self.assertNotIn("範囲の外", [g["text"] for g in segs])
        again = self.store.read_transcript(doc["id"])   # 新しい文書の層も書けている(開き直しても同じ)
        self.assertEqual([g["text"] for g in again["segments"]], [g["text"] for g in segs])

    def test_no_carry(self):
        """評価用の文書へ・環境変数でオフにしたとき・前の文書が評価用のときは引き継がない"""
        new = [{"id": "s1", "start": 2.5, "end": 4.0, "text": "まって", "speaker": "", "flag": ""}]
        self.put_old()
        doc, _job = self.run_new(new, {"evalSet": True})
        self.assertEqual([g["text"] for g in doc["segments"]], ["まって"])   # 評価用には当てない
        self.assertNotIn("override", doc["recognition"]["runs"][-1])
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CARRY_OVERRIDES": "off"}):
            doc, _job = self.run_new(new)
        self.assertEqual([g["text"] for g in doc["segments"]], ["まって"])
        self.put_old(evalSet=True)
        doc, _job = self.run_new(new)
        self.assertEqual([g["text"] for g in doc["segments"]], ["まって"])   # 前の文書が評価用でも当てない

    def test_run_warnings_move_from_spec_to_job(self):
        """走っている間に指定 spec へ足された注意(入れる文書が変わっていた)は、終わったら job の注意へ移る = [やり直す] が前の回の注意を引き継がない(3c-3)"""
        self.put_old()
        doc, job = self.run_new([{"id": "s1", "start": 0.0, "end": 2.0, "text": "あ", "speaker": "", "flag": ""}],
                                {"intoDoc": self.OLD, "warnings": ["受付の注意"]})
        self.assertNotEqual(doc["id"], self.OLD)   # 行のある文書には入れない(新しい文書)
        self.assertEqual(job["spec"]["warnings"], ["受付の注意"])
        self.assertTrue(any("入れる文書が変わっていた" in w for w in job["warnings"]), job["warnings"])
        pub = doc_jobs.public_job(dict(job, title="t", state="done", phase="", progress=1.0, error="", segments=0, speakers=0, unsure=0, device="", createdAt=0))
        self.assertEqual(pub["warnings"][0], "受付の注意")
        self.assertTrue(any("入れる文書が変わっていた" in w for w in pub["warnings"]))

    def test_new_doc_goes_to_case_work_dir(self):
        """新しい文書は ② placement.doc_home が返す 作業用 に置く(索引は TX_DIR)。層も同じ場所(RS8 B2-2)"""
        from ytt import docloc, schemas
        wd = os.path.join(self.tmp, "out", "題名", schemas.WORK_DIR)
        os.makedirs(os.path.dirname(wd))
        self.put_old()
        calls = []

        def home(src, out_dir=None, eval_set=False):
            calls.append((src, eval_set))
            return wd
        with mock.patch.object(doc_jobs._placement, "doc_home", home):
            doc, job = self.run_new([{"id": "s1", "start": 2.5, "end": 4.0, "text": "まって", "speaker": "", "flag": ""}])
        tid = job["tid"]
        self.assertEqual(calls, [(self.src, False)])
        self.assertTrue(os.path.isfile(os.path.join(wd, tid + ".json")))
        self.assertFalse(os.path.exists(os.path.join(self.workdata.TX_DIR, tid + ".json")))
        self.assertEqual(docloc.placed(tid), os.path.normpath(wd))
        self.assertFalse(os.path.exists(os.path.join(wd, tid + ".over.json")))   # 控えはもう書かない
        self.assertEqual(doc["segments"][0]["text"], "待って")
        # 層(RS8 O2-2)も文書と同じ 作業用 に。機械の層は引き継ぐ前の機械の行・引き継いだ人の直しは人の層
        for sfx in (".mach.json", ".hum.json"):
            self.assertTrue(os.path.isfile(os.path.join(wd, tid + sfx)), sfx)
            self.assertFalse(os.path.exists(os.path.join(self.workdata.TX_DIR, tid + sfx)), sfx)
        with open(os.path.join(wd, tid + ".mach.json"), encoding="utf-8") as f:
            self.assertEqual([r["text"] for r in json.load(f)["rows"]], ["まって"])
        with open(os.path.join(wd, tid + ".hum.json"), encoding="utf-8") as f:
            self.assertIn("待って", [h.get("text") for h in json.load(f)["rows"]])

    def test_eval_doc_asks_with_eval_flag(self):
        calls = []
        with mock.patch.object(doc_jobs._placement, "doc_home", lambda src, out_dir=None, eval_set=False: calls.append(eval_set)):
            _doc, job = self.run_new([{"id": "s1", "start": 0.0, "end": 1.0, "text": "a", "speaker": "", "flag": ""}], {"evalSet": True})
        self.assertEqual(calls, [True])
        self.assertTrue(os.path.isfile(os.path.join(self.workdata.TX_DIR, job["tid"] + ".json")))   # None = TX_DIR


if __name__ == "__main__":
    unittest.main()
