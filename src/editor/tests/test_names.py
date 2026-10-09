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
from ytt import modfwd

_TESTS = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_JOB_KEYS = {
    "id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt",
    "errorDetail", "internal", "canRetry", "warnings", "hasClip", "into", "named", "learned", "auto", "autoSkipped",
    "redo", "redoOne", "redoSkipped", "vadNote", "normNote", "normOk", "kept", "emptyKept", "loose"}


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
            self.assertIn(m, S._ED_MODULES, m.__name__)
            self.assertLess(S._ED_MODULES.index(m), S._ED_MODULES.index(ed_jobs), m.__name__)
            both = [k for k, v in m.__dict__.items() if not k.startswith("__") and k in ed_jobs.__dict__ and not isinstance(v, type(os))]
            self.assertEqual(both, [], m.__name__)

    def test_public_job_keys(self):
        job = {"id": "j1", "title": "t", "state": "done", "phase": "完了", "progress": 1.0, "tid": "", "error": "", "segments": 0,
               "speakers": 0, "unsure": 0, "kind": "transcribe", "device": "cpu", "createdAt": 0, "spec": {}}
        self.assertEqual(set(ed_jobs.public_job(job)), _PUBLIC_JOB_KEYS)


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
