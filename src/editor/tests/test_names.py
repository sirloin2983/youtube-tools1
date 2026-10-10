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
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
from unittest import mock

from test_backend import S  # noqa: F401  (S = serve)
import ed_jobs
import ed_speakers
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
    MOVED = (("workdata", ("ROOT", "DATA_DIR", "TX_DIR", "TMP_DIR", "DATASET_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK", "MARKER_DATA", "STUDIO_DATA")),
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
    """serve が doc_jobs.set_hooks に登録した口(評価用の作り直し = ed_evalbatch・30fps = ed_relink。RS2-8d)は全部埋まっていて、
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
        """serve が set_context_namer に登録した口(eval の ed_drill.drill_candidates の suggest)は呼ぶたびに持ち主を読む"""
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
    S.名前 で読め、S.名前 = … の差し替えが持ち主に届き、ed_retime には文書を読む包みの 2 つの名前だけが残る"""

    def test_moved_names_read_through_serve(self):
        from pipeline.transcribe import fill, llm, retime
        for mod, names in ((fill, ("fill_apply", "fill_strip_names", "fill_clean_turns", "FILL_FLAG")),
                           (llm, ("llm_run", "llm_path", "read_llm", "LLM_FLAG")),
                           (retime, ("subread_mark", "SUBREAD_FAST_CPS", "retime_candidates", "RETIME_PAD"))):
            for n in names:
                self.assertIs(getattr(S, n), getattr(mod, n), n)
        self.assertIs(S.retime_doc, __import__("ed_retime").retime_doc)

    def test_patch_reaches_owner(self):
        from pipeline.transcribe import llm, retime
        with mock.patch.object(S, "LLM_MIN_CONF", 0.9), mock.patch.object(S, "RETIME_PAD", 0.5):
            self.assertEqual((llm.LLM_MIN_CONF, retime.RETIME_PAD), (0.9, 0.5))
        self.assertEqual((llm.LLM_MIN_CONF, retime.RETIME_PAD), (0.5, 1.5))

    def test_ed_retime_keeps_only_the_wrapper(self):
        import ed_retime
        own = sorted(k for k, v in vars(ed_retime).items() if not k.startswith("__") and not isinstance(v, type(os)))
        self.assertEqual(own, ["retime_doc", "retime_engine"])

    def test_old_shells_do_not_exist(self):
        for name in ("ed_fill", "ed_llm"):
            with self.assertRaises(ImportError):
                __import__(name)


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
    差し替えは ytt/settings に届き、ed_learn・ed_relink に別名が残っていない。鍵の検査は持ち主が登録する(altEngine = ed_alt)"""
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


if __name__ == "__main__":
    unittest.main()
