#!/usr/bin/env python3
"""serve の名前の受付と ed_jobs の転送(役割で組み直す RS2。2026-10-10)のテスト。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む

- 受付に並ぶ部品(serve.py の _ED_MODULES)どうしで同じ名前を持たない(重なると前の部品が黙って勝ち、S.名前 = … の差し替えが本体に届かない)
- RS2 の前に ed_jobs が持っていた名前(data_ed_jobs_names.txt)は、中身を移しても S.名前 と ed_jobs.名前 の両方で読める
- ed_jobs.名前 = … と mock.patch.object(ed_jobs, …) は移した先の本体に届く
- 画面が読むジョブの形(public_job の鍵)を変えない
- RS2-9 の前に ed_speakers が持っていた名前(data_ed_speakers_names.txt)は、pipeline/transcribe/diarize と human/proof/speakers に分けても
  S.名前 と ed_speakers.名前(転送だけの殻)の両方で読め、差し替えが持ち主に届く
- RS3-0A の前に ed_state が持っていた名前(data_ed_state_names.txt)は、置き場所・動きのある関数を持ち主へ移しても S.名前 で読める
- RS3-E5c の前に ed_learn が持っていた名前(data_ed_learn_names.txt)は、replace・learn・metrics に分けても S.名前 と ed_learn.名前(殻)で読める
- RS3-E5a の前に ed_store が持っていた名前(data_ed_store_names.txt)は、human/proof/store と manage/cases/doclist に分けても
  S.名前 と ed_store.名前(転送だけの殻)の両方で読め、差し替えが持ち主に届く
- RS3-E6 の前に ed_alt・ed_ytcap・ed_retime が持っていた名前(data_ed_alt_names.txt ほか)は、human/proof の alt・ytcap・retime へ移しても
  S.名前 と 殻の名前の両方で読め、差し替えが持ち主に届く(疑似の行 _alt_fake は eval/fake/fake_asr)
- RS3-E7 の前に ed_relink・ed_misc が持っていた名前(data_ed_relink_names.txt・data_ed_misc_names.txt)は、manage/cases/relink・eval/drill/folders と
  manage/cases/handoff_io・human/proof/batch に分けても S.名前 と殻の名前で読める(進行度 progress は 0.69.0 で消した)
- RS4-2 の前に ed_drill・ed_evalbatch が持っていた名前(data_ed_drill_names.txt・data_ed_evalbatch_names.txt)は、eval/drill の drill・evalbatch へ
  殻なしで移しても S.名前 で読め、差し替えが持ち主に届く
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
from unittest import mock

from test_backend import S  # noqa: F401  (S = serve)
import ed_alt
import ed_jobs
import ed_retime
import ed_speakers
import ed_store
import ed_ytcap
from pipeline.transcribe import txbase
from ytt import modfwd

_TESTS = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_JOB_KEYS = {
    "id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt",
    "errorDetail", "internal", "canRetry", "warnings", "hasClip", "into", "named", "learned", "auto", "autoSkipped",
    "redo", "redoOne", "redoSkipped", "vadNote", "normNote", "normOk", "kept", "emptyKept", "loose"}
_ALIAS_OWNERS = (txbase,)   # ed_jobs の転送にだけ入れる持ち主(serve では ed_state の別名で読む。RS2-8a)


def _old_names(name="data_ed_jobs_names.txt"):
    with open(os.path.join(_TESTS, name), encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


class TestNames(unittest.TestCase):
    def test_no_duplicate_names_across_parts(self):
        self.assertEqual(modfwd.duplicates(S._ED_MODULES), {})

    def test_old_ed_jobs_names_still_resolve(self):
        names = _old_names()
        self.assertGreater(len(names), 200)
        missing = [n for n in names if not hasattr(S, n) or not hasattr(ed_jobs, n)]
        self.assertEqual(missing, [])

    def test_moved_names_are_owned_by_one_module(self):
        """移した名前は ed_jobs に残さない(残すと S.名前 = … の差し替えが ed_jobs 側の別名に当たる)"""
        for m in ed_jobs._MOVED:
            both = [k for k, v in m.__dict__.items() if not k.startswith("__") and k in ed_jobs.__dict__ and not isinstance(v, type(os))]
            self.assertEqual(both, [], m.__name__)
            if m in _ALIAS_OWNERS:
                continue
            self.assertIn(m, S._ED_MODULES, m.__name__)
            self.assertLess(S._ED_MODULES.index(m), S._ED_MODULES.index(ed_jobs), m.__name__)

    def test_alias_owners_reach_serve_as_same_object(self):
        """txbase(RS2-8a の SPK_FLAGS)は ed_jobs の転送にだけ入れ、serve の受付には並べない(ed_state の別名と重なるため)。
        S で読める名前は ed_state の別名 = 同じ物(差し替えない名前だけを別名にしている。RS2-1a・RS2-8a)"""
        for m in _ALIAS_OWNERS:
            self.assertIn(m, ed_jobs._MOVED, m.__name__)
            self.assertNotIn(m, S._ED_MODULES, m.__name__)
            for k, v in vars(m).items():
                if k.startswith("_") or isinstance(v, type(os)) or not hasattr(S, k):
                    continue
                self.assertIs(getattr(S, k), v, k)
        self.assertIs(ed_jobs.SPK_FLAGS, S.SPK_FLAGS)

    def test_shell_owns_only_forwarding_names(self):
        """殻(editor/ed_jobs.py)はモジュールの import と転送の口だけを持つ(中身は human/proof/doc_jobs ほか。RS2-8b)"""
        own = sorted(k for k, v in vars(ed_jobs).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["_MOVED", "_add_moved", "_moved_owner"])

    def test_public_job_keys(self):
        job = {"id": "j1", "title": "t", "state": "done", "phase": "完了", "progress": 1.0, "tid": "", "error": "", "segments": 0,
               "speakers": 0, "unsure": 0, "kind": "transcribe", "device": "cpu", "createdAt": 0, "spec": {}}
        self.assertEqual(set(ed_jobs.public_job(job)), _PUBLIC_JOB_KEYS)


class TestBackendSelect(unittest.TestCase):
    """本物と疑似の差し込み口(RS2-2): serve の登録は呼ぶたびに S.backend_name を読む・疑似の旧い名前は fake_asr へ転送"""

    def test_selector_follows_backend_name(self):
        from eval.fake import fake_asr
        from pipeline.transcribe import backend
        with mock.patch.object(S, "backend_name", lambda: "fake"):
            self.assertIs(backend.select(), fake_asr.FAKE)
        with mock.patch.object(S, "backend_name", lambda: "faster-whisper"):
            self.assertIs(backend.select(), backend.REAL)

    def test_fake_names_forward_to_fake_asr(self):
        from eval.fake import fake_asr
        self.assertIs(ed_jobs.transcribe_fake, fake_asr.transcribe_fake)
        self.assertIs(S.transcribe_fake, fake_asr.transcribe_fake)
        self.assertNotIn("transcribe_fake", vars(ed_jobs))
        called = []
        with mock.patch.object(ed_jobs, "transcribe_fake", lambda *a: called.append(a) or iter(())):   # FakeBackend は呼ぶたびに読む
            list(fake_asr.FAKE.transcribe({}, {}, "w", 1.0, None))
        self.assertEqual(len(called), 1)


class TestOwnersFollowServePatches(unittest.TestCase):
    """RS3-0A: 一時の口 txenv を消し、置き場所(ytt/workdata)・動画と音声の小道具(ytt/tools)・ワーカーと GPU とモデル名の検査(worker_client)・
    名簿のファイル(roster)・スタジオの配信の情報(ytt/studiodata)は、下の層の部品が持ち主を呼ぶたびに直に読む。
    S.名前 = …・patch.object(S, …) は持ち主へ届き、ed_state・ed_store に同じ名前は残っていない(残すと差し替えが別名に当たって届かない)"""
    MOVED = (("workdata", ("ROOT", "DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK", "MARKER_DATA", "STUDIO_DATA")),
             ("tools", ("MEDIA_TYPES", "find_ffmpeg", "ffmpeg_info", "duration_in", "media_duration", "check_source", "probe_media")),
             ("worker_client", ("nvidia_gpu", "has_faster_whisper", "worker_python", "worker_has", "gpu_ready", "worker_fake", "valid_model", "MODEL_RE")),
             ("studiodata", ("studio_videos", "studio_stream")),
             ("roster", ("ROSTER",)))

    @staticmethod
    def owners():
        from pipeline.transcribe import roster, worker_client
        from ytt import studiodata, tools, workdata
        return {"workdata": workdata, "tools": tools, "worker_client": worker_client, "studiodata": studiodata, "roster": roster}

    def test_patches_reach_owner_and_no_alias_is_left(self):
        import ed_state
        import ed_store
        own = self.owners()
        sentinel = object()
        for key, names in self.MOVED:
            for name in names:
                self.assertIs(getattr(S, name), getattr(own[key], name), name)
                self.assertNotIn(name, vars(ed_state), name)
                self.assertNotIn(name, vars(ed_store), name)
                with mock.patch.object(S, name, sentinel):
                    self.assertIs(getattr(own[key], name), sentinel, name)
                self.assertIsNot(getattr(own[key], name), sentinel, name)
        self.assertEqual(own["workdata"].SERVER_VERSION, S.SERVER_VERSION)   # 部品が読む版(正は serve.py の SERVER_VERSION)
        with self.assertRaises(ImportError):
            __import__("pipeline.transcribe.txenv")

    def test_validate_job_reads_owners(self):
        """文字起こしの受付(human/proof/doc_jobs)は元のファイルの検査・長さ・モデル名を持ち主から呼ぶたびに読む(S の差し替えが届く)"""
        src = os.path.abspath(__file__)
        with mock.patch.object(S, "check_source", lambda p: src), mock.patch.object(S, "media_duration", lambda p: 10.0), \
                mock.patch.object(S, "valid_model", lambda m: False):
            with self.assertRaises(S.ApiError) as cm:
                ed_jobs.validate_job({"sourcePath": src, "model": "small"})
        self.assertEqual(cm.exception.code, "bad_model")


class TestDocJobsHooks(unittest.TestCase):
    """serve が doc_jobs.set_hooks に登録した口(評価用の作り直し = eval/drill/evalbatch(RS4-2 まで ed_evalbatch)・30fps = manage/cases/relink。RS2-8d)は全部埋まっていて、
    呼ぶたびに持ち主の属性を読む(S.名前 の差し替えが届く)。評価用のフォルダの判定は RS3-1 から口でなく ytt/settings を直に読む"""

    def test_hooks_registered_and_follow_patches(self):
        from human.proof import doc_jobs
        doc_jobs.check_hooks()
        src = os.path.abspath(__file__)
        with mock.patch.object(S, "in_eval_dir", lambda path, dirs=None: True), mock.patch.object(S, "check_source", lambda p: src), \
                mock.patch.object(S, "media_duration", lambda p: 10.0):
            spec = doc_jobs.validate_job({"sourcePath": src})
            self.assertIs(spec.get("evalSet"), True)   # 差し替えは ytt/settings に届き、validate_job が呼ぶたびに読む
        with mock.patch.object(S, "eb_redo_skip_at_start", lambda job: "skip"):
            self.assertEqual(doc_jobs._hook("redo_skip")({}), "skip")


class TestEdSpeakersShell(unittest.TestCase):
    """ed_speakers を pipeline/transcribe/diarize と human/proof/speakers に分けた(RS2-9)。旧い名前は殻と serve で読め、差し替えは持ち主に届く"""

    def test_old_ed_speakers_names_still_resolve(self):
        names = _old_names("data_ed_speakers_names.txt")
        self.assertEqual(len(names), 125)
        missing = [n for n in names if not hasattr(S, n) or not hasattr(ed_speakers, n)]
        self.assertEqual(missing, [])

    def test_shell_owns_only_forwarding_names(self):
        own = sorted(k for k, v in vars(ed_speakers).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["_MOVED", "_add_moved", "_moved_owner"])
        self.assertNotIn(ed_speakers, S._ED_MODULES)   # ed_jobs の殻と同じ 3 つの名前を持つので、serve の受付には並べない

    def test_moved_owners(self):
        from eval.fake import fake_asr
        from human.proof import speakers
        from pipeline.transcribe import diarize
        self.assertEqual(ed_speakers._MOVED, (diarize, speakers, fake_asr))   # fake_asr は serve が _add_moved で足す(殻は eval を読まない)
        for m in (diarize, speakers):
            self.assertIn(m, S._ED_MODULES, m.__name__)
        self.assertIs(ed_speakers.diarize_fake, fake_asr.diarize_fake)
        self.assertIs(S.embed_fake, fake_asr.embed_fake)
        self.assertIs(ed_speakers.run_diarize, speakers.run_diarize)
        self.assertIs(S.assign_speakers, diarize.assign_speakers)

    def test_patches_reach_owner(self):
        """殻・S の差し替えは持ち主に届き、speakers は呼ぶたびに diarize.名前 を読む(テストの patch.object(S, "has_sherpa") などの形)"""
        from human.proof import speakers
        from pipeline.transcribe import diarize
        with mock.patch.object(ed_speakers, "has_sherpa", lambda: "patched"):
            self.assertEqual(diarize.has_sherpa(), "patched")
            self.assertEqual(S.has_sherpa(), "patched")
        self.assertNotIn("has_sherpa", vars(ed_speakers))
        with mock.patch.object(S, "autodiar_enabled", lambda: True), mock.patch.object(ed_speakers, "autodiar_ready", lambda: False):
            self.assertEqual(speakers.autodiar_enqueue("0123456789ab"), {"skipped": "no_sherpa"})   # 同じモジュールの名前も差し替えが届く(test_autodiar の形)
        saved = diarize.DIAR_DIR
        try:
            ed_speakers.DIAR_DIR = os.path.join("x", "diar")   # dev/eval_speakers の形(S.ed_speakers.DIAR_DIR = d)
            self.assertEqual(diarize.diar_models_dir(), os.path.join("x", "diar"))
        finally:
            ed_speakers.DIAR_DIR = saved
        self.assertNotIn("DIAR_DIR", vars(ed_speakers))

    def test_context_namer_follows_patches(self):
        """serve が set_context_namer に登録した口(eval/drill/drill.drill_candidates の suggest)は呼ぶたびに持ち主を読む"""
        from human.proof import speakers
        speakers.check_context_namer()
        with mock.patch.object(S, "drill_candidates", lambda tid: {"suggest": "名前" + tid}):
            self.assertEqual(speakers._context_name("t1"), "名前t1")

    def test_places_follow_data_dir(self):
        """判別のモデル・覚えた声の置き場所は呼ぶたびに作業データ(S.DATA_DIR)から(RS2-9。覚えた声は以前 set_data_dir に付いてこなかった)"""
        saved = (S.DATA_DIR, S.VOICES_DIR, S.DIAR_DIR)
        try:
            S.DATA_DIR, S.VOICES_DIR, S.DIAR_DIR = os.path.join("d", "data"), None, None
            self.assertEqual(S.voices_dir(), os.path.join("d", "data", "voices"))
            self.assertEqual(S.diar_models_dir(), os.path.join("d", "data", "models", "diar"))
        finally:
            S.DATA_DIR, S.VOICES_DIR, S.DIAR_DIR = saved


class TestEdStoreShell(unittest.TestCase):
    """ed_store を human/proof/store(文書の置き場)と manage/cases/doclist(一覧と元の動画・パックの有無・前回のパックの手順)に分けた(RS3-E5a)。
    旧い名前は殻と serve で読め、差し替えは持ち主に届く。store は編集の ed_state・評価の ed_drill・③ の txindex を読まない"""

    @staticmethod
    def owners():
        from human.proof import store
        from manage.cases import doclist
        return store, doclist

    def test_old_ed_store_names_still_resolve(self):
        names = _old_names("data_ed_store_names.txt")
        self.assertEqual(len(names), 79)   # 0.69.0 で進行度の要約 _prog_of・_part を消した
        missing = [n for n in names if not hasattr(S, n) or not hasattr(ed_store, n)]
        self.assertEqual(missing, [])

    def test_shell_owns_only_forwarding_names(self):
        own = sorted(k for k, v in vars(ed_store).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["_MOVED", "_add_moved", "_moved_owner"])
        self.assertNotIn(ed_store, S._ED_MODULES)   # ed_jobs の殻と同じ 3 つの名前を持つので、serve の受付には並べない

    def test_moved_owners(self):
        store, doclist = self.owners()
        self.assertEqual(ed_store._MOVED, (store, doclist))   # doclist は serve が _add_moved で足す(殻は層 human = manage を読まない)
        for m in (store, doclist):
            self.assertIn(m, S._ED_MODULES, m.__name__)
        self.assertIs(S.list_transcripts, doclist.list_transcripts)
        self.assertIs(ed_store.pack_readme, doclist.pack_readme)
        self.assertIs(ed_store.read_transcript, store.read_transcript)
        for name in ("ed_state", "ed_drill", "ed_jobs", "txindex", "_studiodata"):
            self.assertNotIn(name, vars(store), name)

    def test_patches_reach_owner(self):
        store, doclist = self.owners()
        with mock.patch.object(ed_store, "read_transcript", lambda tid: {"id": tid}):
            self.assertEqual(store.read_transcript("a"), {"id": "a"})
            self.assertEqual(S.read_transcript("b"), {"id": "b"})
        self.assertNotIn("read_transcript", vars(ed_store))
        saved = doclist.PACK_CHECK_BUDGET
        try:
            S.PACK_CHECK_BUDGET = -1   # test_backend の形
            self.assertEqual(doclist.PACK_CHECK_BUDGET, -1)
            ed_store.PACK_CHECK_BUDGET = 3
            self.assertEqual(doclist.PACK_CHECK_BUDGET, 3)
        finally:
            doclist.PACK_CHECK_BUDGET = saved
        self.assertNotIn("PACK_CHECK_BUDGET", vars(ed_store))

    def test_summary_leaves_drill_to_drill(self):
        """文書の要約(②)に評価ドリルの要約を入れない。ドリルは eval/drill/drill.drill_docs が自前で作る(決定 3-25 #8)"""
        import inspect
        store, _doclist = self.owners()
        self.assertNotIn('"_drill"', inspect.getsource(store.transcript_summary))


class TestEdAltYtcapRetimeShell(unittest.TestCase):
    """ed_alt・ed_ytcap・ed_retime を human/proof の alt・ytcap・retime へ移した(RS3-E6)。旧い名前は殻と serve で読め、差し替えは持ち主に届く。
    alt・ytcap・retime は編集の ed_state・ed_jobs・ed_store・ed_relink・ed_learn を読まない(疑似の行は Backend.alt_rows)"""

    @staticmethod
    def owners():
        from human.proof import alt, retime, ytcap
        return alt, ytcap, retime

    def test_old_names_still_resolve(self):
        for shell, fname, n in ((ed_alt, "data_ed_alt_names.txt", 31), (ed_ytcap, "data_ed_ytcap_names.txt", 51), (ed_retime, "data_ed_retime_names.txt", 2)):
            names = _old_names(fname)
            self.assertEqual(len(names), n, fname)
            missing = [k for k in names if not hasattr(S, k) or not hasattr(shell, k)]
            self.assertEqual(missing, [], fname)

    def test_shells_own_only_forwarding_names(self):
        for shell, extra in ((ed_alt, ["_add_moved"]), (ed_ytcap, []), (ed_retime, [])):
            own = sorted(k for k, v in vars(shell).items() if not k.startswith("__") and not isinstance(v, type(os)))
            self.assertEqual(own, sorted(["_MOVED", "_moved_owner"] + extra), shell.__name__)
            self.assertNotIn(shell, S._ED_MODULES)   # ed_jobs の殻と同じ名前を持つので、serve の受付には並べない

    def test_moved_owners(self):
        alt, ytcap, retime = self.owners()
        from eval.fake import fake_asr
        self.assertEqual(ed_alt._MOVED, (alt, fake_asr))   # fake_asr は serve が _add_moved で足す(殻は層 human = eval を読まない)
        self.assertEqual(ed_ytcap._MOVED, (ytcap,))
        self.assertEqual(ed_retime._MOVED, (retime,))
        for m in (alt, ytcap, retime):
            self.assertIn(m, S._ED_MODULES, m.__name__)
        self.assertIs(ed_alt.alt_diffs, alt.alt_diffs)
        self.assertIs(ed_alt._alt_fake, fake_asr._alt_fake)
        self.assertIs(S.ytcap_diffs, ytcap.ytcap_diffs)
        self.assertIs(S.retime_doc, retime.retime_doc)

    def test_owners_do_not_read_editor_parts(self):
        for m in self.owners():
            for name in ("ed_state", "ed_jobs", "ed_store", "ed_relink", "ed_learn", "ed_alt"):
                self.assertNotIn(name, vars(m), "%s.%s" % (m.__name__, name))

    def test_retime_wrapper_keeps_only_the_wrapper(self):
        _alt, _ytcap, retime = self.owners()
        own = sorted(k for k, v in vars(retime).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["retime_doc", "retime_engine"])

    def test_patches_reach_owner(self):
        alt, ytcap, _retime = self.owners()
        with mock.patch.object(ed_alt, "alt_spec", lambda tid, req=None: {"tid": tid}):
            self.assertEqual(alt.alt_spec("a"), {"tid": "a"})
            self.assertEqual(S.alt_spec("b"), {"tid": "b"})
        self.assertNotIn("alt_spec", vars(ed_alt))
        saved = ytcap.YTCAP_TIMEOUT_SEC
        try:
            ed_ytcap.YTCAP_TIMEOUT_SEC = 7
            self.assertEqual(ytcap.YTCAP_TIMEOUT_SEC, 7)
            S.YTCAP_TIMEOUT_SEC = 8
            self.assertEqual(ytcap.YTCAP_TIMEOUT_SEC, 8)
        finally:
            ytcap.YTCAP_TIMEOUT_SEC = saved
        self.assertNotIn("YTCAP_TIMEOUT_SEC", vars(ed_ytcap))

    def test_fake_rows_come_from_the_backend_slot(self):
        """疑似の行は Backend.alt_rows(疑似は eval/fake/fake_asr)。本物の Backend は real をそのまま呼ぶ"""
        from eval.fake import fake_asr
        from pipeline.transcribe import backend
        self.assertEqual(list(backend.REAL.alt_rows({}, {}, "w", 1, lambda *a: iter([a]))), [({}, {}, "w", 1)])
        self.assertTrue(hasattr(fake_asr.FAKE, "alt_rows"))
        self.assertEqual(fake_asr.FAKE.name, "fake")


class TestEdRelinkShell(unittest.TestCase):
    """ed_relink を manage/cases/relink(付け替え・まとめて付け替える・30fps)と eval/drill/folders(評価用のフォルダの整理)に分けた(RS3-E7)。
    旧い名前は殻と serve で読め、差し替えは持ち主に届き、folders は付け替えの書き込みを relink から呼ぶたびに読む(④ → ③)"""

    @staticmethod
    def owners():
        from eval.drill import folders
        from manage.cases import relink
        return relink, folders

    def test_old_ed_relink_names_still_resolve(self):
        import ed_relink
        names = _old_names("data_ed_relink_names.txt")
        self.assertEqual(len(names), 68)
        missing = [n for n in names if not hasattr(S, n) or not hasattr(ed_relink, n)]
        self.assertEqual(missing, [])

    def test_shell_owns_only_forwarding_names(self):
        import ed_relink
        own = sorted(k for k, v in vars(ed_relink).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["_MOVED", "_add_moved", "_moved_owner"])
        self.assertNotIn(ed_relink, S._ED_MODULES)   # ed_jobs の殻と同じ 3 つの名前を持つので、serve の受付には並べない

    def test_moved_owners(self):
        import ed_relink
        relink, folders = self.owners()
        self.assertEqual(ed_relink._MOVED, (relink, folders))   # folders は serve が _add_moved で足す(殻は層 manage = eval を読まない)
        for m in (relink, folders):
            self.assertIn(m, S._ED_MODULES, m.__name__)
        self.assertIs(S.relink_doc, relink.relink_doc)
        self.assertIs(ed_relink.eval_organize, folders.eval_organize)
        self.assertIs(ed_relink._evalorg_lock, folders._evalorg_lock)
        for name in ("ed_state", "ed_jobs", "ed_store", "folders", "_evfolders"):
            self.assertNotIn(name, vars(relink), name)   # relink は ④ と編集の app・殻を読まない

    def test_patches_reach_owner(self):
        import ed_relink
        relink, folders = self.owners()
        calls = []
        with mock.patch.object(S, "_relink_write", lambda *a, **k: calls.append(a) or 1):
            self.assertEqual(relink._relink_write("t", {}, "p", 0.0), 1)   # S の差し替えは relink に届き、folders は呼ぶたびに _relink._relink_write を読む
        self.assertEqual(len(calls), 1)
        saved = relink.FIND_MAX_DEPTH
        try:
            ed_relink.FIND_MAX_DEPTH = 2   # test_edit の形(S.FIND_MAX_DEPTH = 1)
            self.assertEqual(relink.FIND_MAX_DEPTH, 2)
        finally:
            relink.FIND_MAX_DEPTH = saved
        self.assertNotIn("FIND_MAX_DEPTH", vars(ed_relink))

    def test_norm_after_hook_points_to_relink(self):
        """doc_jobs の口 norm_after は relink.norm_after_transcribe を呼ぶたびに読む(S の差し替えが届く)"""
        from human.proof import doc_jobs
        doc_jobs.check_hooks()
        with mock.patch.object(S, "norm_after_transcribe", lambda job, spec, tid: "norm:" + tid):
            self.assertEqual(doc_jobs._hook("norm_after")({}, {}, "t1"), "norm:t1")


class TestEdMiscShell(unittest.TestCase):
    """ed_misc を manage/cases/handoff_io(clip-marker・受け渡し)・human/proof/batch(フォルダの一括・文字起こし済みの範囲)
    に分けた(RS3-E7。進行度 human/proof/progress は 0.69.0 で消した)。.runtime の置き場所 runtime_path_dir は app の ed_state(serve の名前だけ)"""

    @staticmethod
    def owners():
        from human.proof import batch
        from manage.cases import handoff_io
        return handoff_io, batch

    def test_old_ed_misc_names_still_resolve(self):
        import ed_misc
        names = _old_names("data_ed_misc_names.txt")
        self.assertEqual(len(names), 17)
        self.assertEqual([n for n in names if not hasattr(S, n)], [])
        self.assertEqual([n for n in names if not hasattr(ed_misc, n)], ["runtime_path_dir"])   # app に残した名前は殻からは読まない

    def test_shell_owns_only_forwarding_names(self):
        import ed_misc
        own = sorted(k for k, v in vars(ed_misc).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["_MOVED", "_add_moved", "_moved_owner"])
        self.assertNotIn(ed_misc, S._ED_MODULES)

    def test_moved_owners(self):
        import ed_misc
        import ed_state
        owners = self.owners()
        self.assertEqual(ed_misc._MOVED, owners)
        for m in owners:
            self.assertIn(m, S._ED_MODULES, m.__name__)
        handoff_io, batch = owners
        self.assertIs(S.clip_info, handoff_io.clip_info)
        self.assertIs(ed_misc.scan_common, batch.scan_common)
        self.assertFalse(hasattr(S, "progress_stats"))   # 0.69.0(段 D2)で消した
        self.assertIs(S.runtime_path_dir, ed_state.runtime_path_dir)

    def test_transcribed_ranges_patch_reaches_marker_and_batch(self):
        """S.transcribed_ranges の差し替え(test_backend・test_metrics の形)はフォルダの一括とマーカーの読みの両方に届く"""
        handoff_io, batch = self.owners()
        with mock.patch.object(S, "transcribed_ranges", lambda: [{"path": "k", "start": 0.0, "end": None, "whole": True, "tid": "t1"}]):
            self.assertEqual(batch._done_and_active()[0], {"k": "t1"})
            self.assertIn("transcribed_ranges", vars(batch))
        self.assertNotIn("transcribed_ranges", vars(handoff_io))   # マーカーは _batch.transcribed_ranges を呼ぶたびに読む


class TestEdStateNames(unittest.TestCase):
    """RS3-0A: ed_state の置き場所(ytt/workdata)と動きのある関数(ytt/tools・worker_client・ytt/studiodata・roster)を持ち主へ移しても、
    旧い名前は S で読める(ed_state に殻は置かない = 読むのは serve の名前の受付だけ)"""

    def test_old_ed_state_names_still_resolve(self):
        names = _old_names("data_ed_state_names.txt")
        self.assertGreater(len(names), 90)
        missing = [n for n in names if not hasattr(S, n)]
        self.assertEqual(missing, [])


class TestPipelineMovedWithoutShell(unittest.TestCase):
    """RS2-9c: ed_fill・ed_llm は pipeline/transcribe の fill・llm へ、ed_retime の計算は retime へ移した(殻・別名なし)。
    S.名前 で読め、S.名前 = … の差し替えが持ち主に届く(ed_retime の包みは RS3-E6 から human/proof/retime。殻の検査は TestEdAltYtcapRetimeShell)"""

    def test_moved_names_read_through_serve(self):
        from pipeline.transcribe import fill, llm, retime
        for mod, names in ((fill, ("fill_apply", "fill_strip_names", "fill_clean_turns", "FILL_FLAG")),
                           (llm, ("llm_run", "llm_path", "read_llm", "LLM_FLAG")),
                           (retime, ("subread_mark", "SUBREAD_FAST_CPS", "retime_candidates", "RETIME_PAD"))):
            for n in names:
                self.assertIs(getattr(S, n), getattr(mod, n), n)
        self.assertIs(S.retime_doc, ed_retime.retime_doc)

    def test_patch_reaches_owner(self):
        from pipeline.transcribe import llm, retime
        with mock.patch.object(S, "LLM_MIN_CONF", 0.9), mock.patch.object(S, "RETIME_PAD", 0.5):
            self.assertEqual((llm.LLM_MIN_CONF, retime.RETIME_PAD), (0.9, 0.5))
        self.assertEqual((llm.LLM_MIN_CONF, retime.RETIME_PAD), (0.5, 1.5))

    def test_old_shells_do_not_exist(self):
        for name in ("ed_fill", "ed_llm"):
            with self.assertRaises(ImportError):
                __import__(name)


class TestDrillEvalbatchMovedWithoutShell(unittest.TestCase):
    """RS4-2: ed_drill・ed_evalbatch は eval/drill の drill・evalbatch へ殻なしで移した(決定 3-25 #7)。
    移す前の名前(data_ed_drill_names.txt・data_ed_evalbatch_names.txt)は S.名前 で読め(持ち主と同じ物)、S.名前 = … の差し替えが持ち主に届く。
    持ち主は編集(app)の部品を読まない。serve が登録する口(set_hooks の redo_skip・redo_fill・set_context_namer)は新しい持ち主を呼ぶ"""

    @staticmethod
    def owners():
        from eval.drill import drill, evalbatch
        return drill, evalbatch

    def test_old_names_read_through_serve(self):
        drill, evalbatch = self.owners()
        for mod, fname, n in ((drill, "data_ed_drill_names.txt", 32), (evalbatch, "data_ed_evalbatch_names.txt", 58)):
            names = _old_names(fname)
            self.assertEqual(len(names), n, fname)
            self.assertIn(mod, S._ED_MODULES, fname)
            wrong = [k for k in names if getattr(S, k, None) is not getattr(mod, k)]
            self.assertEqual(wrong, [], fname)

    def test_old_shells_do_not_exist(self):
        for name in ("ed_drill", "ed_evalbatch"):
            with self.assertRaises(ImportError):
                __import__(name)

    def test_owners_do_not_read_editor_parts(self):
        import types
        for m in self.owners():
            mods = {k for k, v in vars(m).items() if isinstance(v, types.ModuleType)}
            self.assertEqual(sorted(k for k in mods if k.startswith("ed_") or k == "serve"), [], m.__name__)

    def test_patches_reach_owner(self):
        drill, evalbatch = self.owners()
        with mock.patch.object(S, "DRILL_RECENT_SEC", 5), mock.patch.object(S, "EB_MAX_WAIT", 7):
            self.assertEqual((drill.DRILL_RECENT_SEC, evalbatch.EB_MAX_WAIT), (5, 7))
        self.assertEqual((drill.DRILL_RECENT_SEC, evalbatch.EB_MAX_WAIT), (600, 2))
        with mock.patch.object(S, "_busy_tids", lambda: {"x"}):
            self.assertEqual(drill._busy_tids(), {"x"})   # evalbatch は呼ぶたびに _drill._busy_tids を読む

    def test_hooks_point_to_new_owners(self):
        from human.proof import doc_jobs, speakers
        doc_jobs.check_hooks()
        speakers.check_context_namer()
        with mock.patch.object(S, "eb_redo_fill", lambda job, spec, fields: "filled"):
            self.assertEqual(doc_jobs._hook("redo_fill")({}, {}, {}), "filled")
        with mock.patch.object(S, "drill_candidates", lambda tid: {"suggest": "n" + tid}):
            self.assertEqual(speakers._context_name("t"), "nt")


class TestEdJobsForwarding(unittest.TestCase):
    """ed_jobs の転送の口(ytt/modfwd.py)。移した先に見立てた部品で、読み・書き・削除・patch.object が本体に届くか"""

    def setUp(self):
        import types
        self.part = types.ModuleType("rs2_fake_part")
        self.part.RS2_PROBE = 1
        self.part.rs2_probe_fn = lambda: self.part.RS2_PROBE
        self.saved = ed_jobs._MOVED
        ed_jobs._MOVED = (self.part,)
        self.find = modfwd.install(vars(ed_jobs), ed_jobs._MOVED, "ed_jobs")

    def tearDown(self):
        ed_jobs._MOVED = self.saved
        modfwd.install(vars(ed_jobs), ed_jobs._MOVED, "ed_jobs")

    def test_read_write_delete_and_patch_reach_owner(self):
        self.assertEqual(ed_jobs.RS2_PROBE, 1)
        ed_jobs.RS2_PROBE = 5
        self.assertEqual(self.part.rs2_probe_fn(), 5)
        self.assertNotIn("RS2_PROBE", vars(ed_jobs))
        with mock.patch.object(ed_jobs, "RS2_PROBE", 9):
            self.assertEqual(self.part.rs2_probe_fn(), 9)
        self.assertEqual(self.part.RS2_PROBE, 5)
        del ed_jobs.RS2_PROBE
        self.assertFalse(hasattr(self.part, "RS2_PROBE"))

    def test_own_names_stay_local(self):
        """殻が自分で持つ名前(_add_moved など。RS2-8b から殻の名前はこれと _MOVED・_moved_owner だけ)は、持ち主に同じ名前があっても殻のまま"""
        before = ed_jobs._add_moved
        self.part._add_moved = "other"
        try:
            self.assertIs(ed_jobs._add_moved, before)
        finally:
            del self.part._add_moved


class TestSettingsMoved(unittest.TestCase):
    """編集の設定の読み書きと鍵の検査を ed_learn から、評価用のフォルダの判定を ed_relink から ytt/settings へ移した(RS3-1)。S.名前 で読め、
    差し替えは ytt/settings に届き、ed_learn・ed_relink に別名が残っていない。鍵の検査は持ち主が登録する(altEngine = human/proof/alt)"""
    MOVED = ("SETTINGS_MAX", "load_settings", "SETTINGS_PATCH_KEYS", "CUT_SILENCE_RANGE", "patch_settings", "merge_settings", "replace_settings",
             "register_patch_key", "_settings_file", "_settings_lock", "_keymap_ok", "_cut_silence_ok", "_settings_error",
             "EVAL_DIRS_MAX", "EVAL_NAME_WORD", "_eval_dirs_ok", "eval_dirs", "in_eval_dir", "eval_name_guard")

    def test_owner_and_no_alias(self):
        import ed_learn
        import ed_relink
        from ytt import settings
        for n in self.MOVED:
            self.assertIs(S._ed_owner(n), settings, n)
            self.assertNotIn(n, vars(ed_learn), n)
            self.assertNotIn(n, vars(ed_relink), n)
        for n in ("_remote_drive", "_same_drive", "_move"):   # ytt/fsio の is_remote_drive・same_drive・move_file へ
            self.assertNotIn(n, vars(ed_relink), n)

    def test_patch_reaches_owner(self):
        import ed_learn  # noqa: F401
        from ytt import settings
        with mock.patch.object(S, "load_settings", lambda: {"diarSmooth": True}):
            self.assertEqual(settings.load_settings(), {"diarSmooth": True})
            from human.proof import speakers
            self.assertTrue(speakers.diar_smooth_setting())   # 読み手は呼ぶたびに ytt/settings の名前を読む

    def test_owner_registered_keys(self):
        self.assertTrue(S.SETTINGS_PATCH_KEYS["altEngine"](S.ALT_DEFAULT))
        self.assertFalse(S.SETTINGS_PATCH_KEYS["altEngine"]("bad"))
        self.assertIn("evalDirs", S.SETTINGS_PATCH_KEYS)

    def test_eval_dir_patch_reaches_readers(self):
        import tempfile
        import ed_store
        ev = os.path.join(tempfile.gettempdir(), "rs3-eval-probe")
        video = os.path.join(ev, "a.mp4")
        with mock.patch.object(S, "eval_dirs", lambda: [ev]):
            self.assertTrue(S.in_eval_dir(video))   # in_eval_dir は呼ぶたびに同じ部品の eval_dirs を読む
            self.assertIs(ed_store.sanitize_transcript({"segments": []}, {"sourcePath": video}).get("evalSet"), True)   # 読み手(ed_store)も
        self.assertIsNot(ed_store.sanitize_transcript({"segments": []}, {"sourcePath": video}).get("evalSet"), True)


class TestEdLearnShell(unittest.TestCase):
    """ed_learn の残りを pipeline/transcribe/replace(置換辞書)・human/proof/learn(学習と提案)・eval/drill/metrics(精度と基準)に分けた(RS3-E5c)。
    旧い名前は殻と serve で読め、差し替えは持ち主に届き、learn は metrics を読まない(② から ④ を読まない)"""

    def test_old_ed_learn_names_still_resolve(self):
        import ed_learn
        names = _old_names("data_ed_learn_names.txt")
        self.assertEqual(len(names), 60)
        missing = [n for n in names if not hasattr(S, n) or not hasattr(ed_learn, n)]
        self.assertEqual(missing, [])

    def test_shell_owns_only_forwarding_names(self):
        import ed_learn
        own = sorted(k for k, v in vars(ed_learn).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["_MOVED", "_add_moved", "_moved_owner"])
        self.assertNotIn(ed_learn, S._ED_MODULES)   # ed_jobs の殻と同じ 3 つの名前を持つので、serve の受付には並べない

    def test_moved_owners(self):
        import ed_learn
        from eval.drill import metrics
        from human.proof import learn
        from pipeline.transcribe import replace
        self.assertEqual(ed_learn._MOVED, (replace, learn, metrics))   # metrics は serve が _add_moved で足す(殻は eval を読まない)
        for m in (replace, learn, metrics):
            self.assertIn(m, S._ED_MODULES, m.__name__)
        self.assertIs(S.apply_replacements, replace.apply_replacements)
        self.assertIs(ed_learn.learn_rules, learn.learn_rules)
        self.assertIs(ed_learn.doc_metrics, metrics.doc_metrics)
        self.assertIs(S._groups, learn._groups)   # dev/eval_asr・eval_alt が S._groups・S.split_nosub で読む
        self.assertNotIn("metrics", vars(learn))   # learn は metrics を読まない

    def test_patches_reach_owner(self):
        import ed_learn
        from eval.drill import metrics
        saved = metrics.MAX_LEV_CELLS
        try:
            S.MAX_LEV_CELLS = 10   # test_metrics の形
            self.assertEqual(metrics.MAX_LEV_CELLS, 10)
        finally:
            S.MAX_LEV_CELLS = saved
        self.assertNotIn("MAX_LEV_CELLS", vars(S))
        from human.proof import learn
        with mock.patch.object(ed_learn, "_bounded", lambda text, k, w: False):
            self.assertEqual(learn._spans("トル様", "トル", "ポル"), [])   # learn は呼ぶたびに replace._bounded を読む
        self.assertEqual(learn._spans("トル様", "トル", "ポル"), [0])


if __name__ == "__main__":
    unittest.main()
