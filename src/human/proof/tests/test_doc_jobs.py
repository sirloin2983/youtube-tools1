# -*- coding: utf-8 -*-
"""human/proof/doc_jobs の、serve が登録する口(set_hooks・check_hooks。役割で組み直す RS2-8d)のテスト。

    py -3.10 -m unittest src/human/proof/tests/test_doc_jobs.py -v

doc_jobs は editor の部品を裸の名前(import ed_store など)で読むので、src と src/editor を sys.path に足す。編集の serve は読まない
(serve の登録で口が埋まり、評価用の作り直しの差し替えが本体に届くことは src/editor/tests/test_evalbatch.py・test_names.py が確かめる)。
"""
import contextlib
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> proof -> human -> src
EDITOR = os.path.join(SRC, "editor")
for _p in (EDITOR, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import doc_jobs, overrides  # noqa: E402


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.saved = dict(doc_jobs._hooks)
        doc_jobs._hooks.clear()

    def tearDown(self):
        doc_jobs._hooks.clear()
        doc_jobs._hooks.update(self.saved)

    def test_unregistered_hook_raises(self):
        with self.assertRaises(RuntimeError) as cm:
            doc_jobs._hook("redo_skip")
        self.assertIn("redo_skip", str(cm.exception))
        self.assertIn("serve.py", str(cm.exception))

    def test_check_hooks_names_missing_keys(self):
        doc_jobs.set_hooks(redo_skip=lambda job: False)
        with self.assertRaises(RuntimeError) as cm:
            doc_jobs.check_hooks()
        msg = str(cm.exception)
        for k in ("redo_fill", "norm_after"):
            self.assertIn(k, msg)
        self.assertNotIn("redo_skip", msg)
        doc_jobs.check_hooks(("redo_skip",))   # 登録した鍵だけなら通る

    def test_set_hooks_rejects_unknown_and_non_callable(self):
        with self.assertRaises(TypeError):
            doc_jobs.set_hooks(not_a_hook=lambda: None)
        with self.assertRaises(TypeError):
            doc_jobs.set_hooks(redo_skip=True)
        self.assertEqual(doc_jobs._hooks, {})   # 断ったときは何も入れない

    def test_hook_is_looked_up_at_call_time(self):
        calls = []
        doc_jobs.set_hooks(norm_after=lambda job, spec, tid: calls.append(("a", tid)))
        doc_jobs._hook("norm_after")({}, {}, "t1")
        doc_jobs.set_hooks(norm_after=lambda job, spec, tid: calls.append(("b", tid)))   # 登録し直すと次の呼び出しから新しい方
        doc_jobs._hook("norm_after")({}, {}, "t2")
        self.assertEqual(calls, [("a", "t1"), ("b", "t2")])
        doc_jobs.set_hooks(redo_skip=lambda j: False, redo_fill=lambda j, s, f: None)
        doc_jobs.check_hooks()

    def test_eval_dir_hooks_are_gone(self):
        """評価用のフォルダの判定は口でなく ytt/settings を直に読む(RS3-1。口は redo_skip・redo_fill・norm_after の 3 本)"""
        self.assertEqual(doc_jobs._HOOK_KEYS, ("redo_skip", "redo_fill", "norm_after"))
        with self.assertRaises(TypeError):
            doc_jobs.set_hooks(in_eval_dir=lambda path: False)

    def test_does_not_import_manage_or_eval_parts(self):
        """評価用のフォルダ(manage の ed_relink)と評価用の作り直し(eval の ed_evalbatch)はモジュールとして持たない(口を通す)"""
        for name in ("ed_relink", "ed_evalbatch", "ed_state"):
            self.assertNotIn(name, vars(doc_jobs), name)


class TestImportWithoutServe(unittest.TestCase):
    def test_import_without_serve(self):
        """doc_jobs は編集の serve を読まずに import できる(口は空のまま = 使う前に serve が登録する)"""
        code = ("import os, sys; os.environ.setdefault('YTT_DATA_DIR', 'inplace'); sys.path[:0] = [%r, %r]; "
                "from human.proof import doc_jobs; "
                "ok = 'serve' not in sys.modules and doc_jobs._hooks == {}; "
                "print(sorted(m for m in sys.modules if m == 'serve')); sys.exit(0 if ok else 1)") % (SRC, EDITOR)
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestCarryOverrides(unittest.TestCase):
    """同じ動画の文書を作り直す(force の再文字起こし・エンジンを変えた再実行)と、前の文書の人の行が新しい文書に引き継がれる(RS6 b-O1)。
    認識(② flow/tx.transcribe_clip)と続きの処理は差し替えて、run_job の ③ の分だけを動かす"""
    OLD = "0123456789ab"

    def setUp(self):
        from ytt import workdata
        from human.proof import store
        self.workdata, self.store = workdata, store
        self.tmp = tempfile.mkdtemp(prefix="ytt-carry-")
        self.saved = (workdata.TX_DIR, workdata.SETTINGS, dict(doc_jobs._hooks))
        workdata.TX_DIR = os.path.join(self.tmp, "transcripts")
        workdata.SETTINGS = os.path.join(self.tmp, "settings.json")
        os.makedirs(workdata.TX_DIR)
        store._summary_cache.clear()
        doc_jobs.set_hooks(norm_after=lambda job, spec, tid: None)
        self.src = os.path.join(self.tmp, "clip_0001.mp4")
        self.spec = {"sourcePath": self.src, "sourceName": "clip_0001.mp4", "title": "t", "start": 0.0, "end": 20.0, "evalSet": False}

    def tearDown(self):
        self.workdata.TX_DIR, self.workdata.SETTINGS, hooks = self.saved
        doc_jobs._hooks.clear()
        doc_jobs._hooks.update(hooks)
        self.store._summary_cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_new(self, segs, spec=None):
        """新しい機械の行 segs で文字起こしのジョブを 1 本動かす -> (新しい文書, ジョブ)"""
        fields = {"start": 0.0, "end": 20.0, "whole": True, "duration": 20.0, "model": "small", "language": "ja", "params": {}, "speakers": [],
                  "segments": segs, "original": [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in segs], "updatedAt": 5000,
                  "recognition": {"runs": [{"engine": "fake"}]}}
        clip = {"fields": fields, "segs": segs, "sparseLp": {}}

        @contextlib.contextmanager
        def wav(job):
            yield os.path.join(self.tmp, "x.wav")
        job = {"id": "j1", "kind": "transcribe", "spec": dict(self.spec, **(spec or {}))}
        with mock.patch.object(doc_jobs._heavy, "job_temp_wav", wav), \
                mock.patch.object(doc_jobs._flowtx, "dict_pairs", lambda spec: []), \
                mock.patch.object(doc_jobs._flowtx, "transcribe_clip", lambda *a, **k: clip), \
                mock.patch.object(doc_jobs._flowtx, "write_clip_records", lambda *a, **k: None), \
                mock.patch.object(doc_jobs.speakers, "autodiar_after_transcribe", lambda *a: None), \
                mock.patch.object(doc_jobs.alt, "alt_after_transcribe", lambda *a: None), \
                mock.patch.object(doc_jobs.ytcap, "ytcap_after_transcribe", lambda *a: None):
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
        self.assertIn(overrides.STALE_FLAG, segs[3]["flag"])                       # 対応する行が無い人の行は印つきで残す
        self.assertEqual([s["id"] for s in doc["speakers"]], ["A"])
        st = doc["recognition"]["runs"][-1]["override"]
        self.assertEqual((st["matched"], st["stale"], st["total"], st["from"]), (2, 1, 3, self.OLD))
        self.assertEqual([g["text"] for g in doc["original"]], ["こんばんは(新)", "まってて", "えー(新)"])   # 機械の出力は新しい認識のまま
        self.assertTrue(any("引き継ぎました" in w for w in job.get("warnings") or []))
        self.assertEqual(overrides.read(doc["id"])["at"], doc["updatedAt"])          # 新しい文書の控えも書く
        old = self.store.read_transcript(self.OLD)
        self.assertEqual(old["segments"][1]["text"], "待って")                      # 前の文書はそのまま

    def test_no_carry_into_eval_doc(self):
        self.put_old()
        doc, _job = self.run_new([{"id": "s1", "start": 2.5, "end": 4.0, "text": "まって", "speaker": "", "flag": ""}], {"evalSet": True})
        self.assertEqual([g["text"] for g in doc["segments"]], ["まって"])   # 評価用には当てない
        self.assertNotIn("override", doc["recognition"]["runs"][-1])

    def test_switch_off(self):
        self.put_old()
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CARRY_OVERRIDES": "off"}):
            doc, _job = self.run_new([{"id": "s1", "start": 2.5, "end": 4.0, "text": "まって", "speaker": "", "flag": ""}])
        self.assertEqual([g["text"] for g in doc["segments"]], ["まって"])

    def test_no_carry_from_eval_doc(self):
        self.put_old(evalSet=True)
        doc, _job = self.run_new([{"id": "s1", "start": 2.5, "end": 4.0, "text": "まって", "speaker": "", "flag": ""}])
        self.assertEqual([g["text"] for g in doc["segments"]], ["まって"])   # 前の文書が評価用でも当てない

    def test_new_doc_goes_to_case_work_dir(self):
        """新しい文書は ② placement.doc_home が返す 作業用 に置く(索引は TX_DIR)。引き継いだ人の行の控えも同じ場所(RS8 B2-2)"""
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
        self.assertTrue(os.path.isfile(os.path.join(wd, tid + ".over.json")))   # 引き継いだので控えも案件へ
        self.assertEqual(doc["segments"][0]["text"], "待って")

    def test_eval_doc_asks_with_eval_flag(self):
        calls = []
        with mock.patch.object(doc_jobs._placement, "doc_home", lambda src, out_dir=None, eval_set=False: calls.append(eval_set)):
            _doc, job = self.run_new([{"id": "s1", "start": 0.0, "end": 1.0, "text": "a", "speaker": "", "flag": ""}], {"evalSet": True})
        self.assertEqual(calls, [True])
        self.assertTrue(os.path.isfile(os.path.join(self.workdata.TX_DIR, job["tid"] + ".json")))   # None = TX_DIR


if __name__ == "__main__":
    unittest.main()
