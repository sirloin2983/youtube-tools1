#!/usr/bin/env python3
"""serve の名前の受付と ed_jobs の転送(役割で組み直す RS2。2026-10-10)のテスト。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む

- 受付に並ぶ部品(serve.py の _ED_MODULES)どうしで同じ名前を持たない(重なると前の部品が黙って勝ち、S.名前 = … の差し替えが本体に届かない)
- RS2 の前に ed_jobs が持っていた名前(data_ed_jobs_names.txt)は、中身を移しても S.名前 と ed_jobs.名前 の両方で読める
- ed_jobs.名前 = … と mock.patch.object(ed_jobs, …) は移した先の本体に届く
- 画面が読むジョブの形(public_job の鍵)を変えない
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
from unittest import mock

from test_backend import S  # noqa: F401  (S = serve)
import ed_jobs
from pipeline.transcribe import txbase
from ytt import modfwd

_TESTS = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_JOB_KEYS = {
    "id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt",
    "errorDetail", "internal", "canRetry", "warnings", "hasClip", "into", "named", "learned", "auto", "autoSkipped",
    "redo", "redoOne", "redoSkipped", "vadNote", "normNote", "normOk", "kept", "emptyKept", "loose"}
_ALIAS_OWNERS = (txbase,)   # ed_jobs の転送にだけ入れる持ち主(serve では ed_state の別名で読む。RS2-8a)


def _old_names():
    with open(os.path.join(_TESTS, "data_ed_jobs_names.txt"), encoding="utf-8") as f:
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
        before = ed_jobs.public_job
        self.part.public_job = "other"
        try:
            self.assertIs(ed_jobs.public_job, before)
        finally:
            del self.part.public_job


if __name__ == "__main__":
    unittest.main()
