#!/usr/bin/env python3
"""serve の名前の受付と ed_jobs の転送(役割で組み直す RS2。2026-10-10)のテスト。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む

- 受付に並ぶ部品(serve.py の _ED_MODULES)どうしで同じ名前を持たない(重なると前の部品が黙って勝ち、S.名前 = … の差し替えが本体に届かない)
- RS2 の前に ed_jobs が持っていた名前(data_ed_jobs_names.txt)は、中身を移しても S.名前 と ed_jobs.名前 の両方で読める
- ed_jobs.名前 = … と mock.patch.object(ed_jobs, …) は移した先の本体に届く
- 画面が読むジョブの形(public_job の鍵)を変えない
- RS2-9 の前に ed_speakers が持っていた名前(data_ed_speakers_names.txt)は、pipeline/transcribe/diarize と human/proof/speakers に分けても
  S.名前 と ed_speakers.名前(転送だけの殻)の両方で読め、差し替えが持ち主に届く
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


class TestTxenvRegistered(unittest.TestCase):
    """serve が txenv に登録した RS2-8a の鍵(studio_stream・valid_model・pio)は、呼ぶたびに持ち主(ed_store・ed_state)を読む = S.名前 の差し替えが効く"""

    def test_keys_follow_serve_patches(self):
        from pipeline.transcribe import txenv
        txenv.check()
        for name in ("studio_stream", "valid_model", "pio"):
            fake = lambda *a, **k: ("fake", a, k)  # noqa: E731
            with mock.patch.object(S, name, fake):
                self.assertIs(txenv.get(name), fake, name)
            self.assertIsNot(txenv.get(name), fake, name)
        src = os.path.abspath(__file__)
        pio_calls = []
        with mock.patch.object(S, "check_source", lambda p: src), mock.patch.object(S, "media_duration", lambda p: 10.0), \
                mock.patch.object(S, "pio", lambda required=True: pio_calls.append(required)), \
                mock.patch.object(S, "valid_model", lambda m: False):
            with self.assertRaises(S.ApiError) as cm:
                ed_jobs.validate_job({"sourcePath": src, "model": "small"})   # ed_jobs は ed_state を読まずに txenv の口から読む
        self.assertEqual(cm.exception.code, "bad_model")
        self.assertEqual(pio_calls, [False])   # .clip.json 探しは無くても続けられる(required=False。None なら clip なし)


class TestDocJobsHooks(unittest.TestCase):
    """serve が doc_jobs.set_hooks に登録した口(評価用のフォルダ = ed_relink・評価用の作り直し = ed_evalbatch。RS2-8d)は全部埋まっていて、
    呼ぶたびに持ち主の属性を読む(S.名前 の差し替え・patch.object(ed_relink, …) が届く)"""

    def test_hooks_registered_and_follow_patches(self):
        from human.proof import doc_jobs
        doc_jobs.check_hooks()
        with mock.patch.object(S, "in_eval_dir", lambda path, dirs=None: "patched"):
            self.assertEqual(doc_jobs._hook("in_eval_dir")("x.mp4"), "patched")
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


if __name__ == "__main__":
    unittest.main()
