# -*- coding: utf-8 -*-
"""flow/wire の入口なしの準備(setup_places・setup_headless。OPT-E2 1c-1・設計原則のレビューの指摘 4)のテスト。編集の serve は読まない。

    py -3.10 -m unittest src/flow/tests/test_wire_setup.py -v

- 置き場所・スタジオの data.json・名簿を持ち主(ytt/workdata・① roster.ROSTER)へ明示して入れる・省いたものは set_root の既定
- setup_headless は install も呼び(疑似の選び方)、in_process なら ① worker_client.IN_WORKER。環境変数 TRANSCRIBE_DATA_DIR は書き換えない
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない。ほかのテストとそろえる
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import jobs, wire  # noqa: E402
from pipeline.transcribe import backend, models, roster, worker_client  # noqa: E402
from ytt import layout, workdata  # noqa: E402


class TestSetup(unittest.TestCase):
    def setUp(self):
        saved = {}
        for obj, names in ((workdata, ("ROOT", "DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK", "STUDIO_DATA", "MARKER_DATA")),
                           (roster, ("ROSTER",)), (worker_client, ("IN_WORKER", "FAKES_MODULE", "WORKER_LOG")), (backend, ("_selector",)),
                           (jobs, ("_conf",))):
            for n in names:
                saved[(obj, n)] = getattr(obj, n)
        self.addCleanup(lambda: [setattr(o, n, v) for (o, n), v in saved.items()])
        self.tmp = tempfile.mkdtemp(prefix="wire_setup_")

    def test_places_explicit(self):
        wire.setup_places(data_dir=self.tmp, studio_data=os.path.join(self.tmp, "s.json"), roster=os.path.join(self.tmp, "r.json"))
        self.assertEqual(workdata.DATA_DIR, os.path.abspath(self.tmp))
        self.assertEqual(workdata.TX_DIR, os.path.join(os.path.abspath(self.tmp), "transcripts"))
        self.assertEqual(workdata.ROOT, layout.tool_dir("transcribe"))
        self.assertEqual(workdata.STUDIO_DATA, os.path.join(self.tmp, "s.json"))
        self.assertEqual(roster.ROSTER, os.path.join(self.tmp, "r.json"))

    def test_places_defaults(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_DATA_DIR": self.tmp}):
            wire.setup_places(root=self.tmp)
        self.assertEqual(workdata.DATA_DIR, self.tmp)
        self.assertEqual(roster.ROSTER, os.path.join(self.tmp, wire.ROSTER_FILE))

    def test_headless(self):
        fake = mock.Mock(name="fake")
        before = os.environ.get("TRANSCRIBE_DATA_DIR")
        with mock.patch.object(models, "setup_cuda_paths") as cuda:
            wire.setup_headless(data_dir=self.tmp, in_process=True, backend_name=lambda: "fake", fake_backend=fake, fake_worker_module="x.y")
        self.assertEqual(os.environ.get("TRANSCRIBE_DATA_DIR"), before)
        self.assertIs(backend.select(), fake)
        self.assertTrue(worker_client.IN_WORKER)
        self.assertEqual(worker_client.FAKES_MODULE, "x.y")
        self.assertEqual(worker_client.WORKER_LOG, os.path.join(os.path.abspath(self.tmp), "worker.log"))
        cuda.assert_called_once_with()
        worker_client.IN_WORKER = False
        wire.setup_headless(data_dir=self.tmp)
        self.assertFalse(worker_client.IN_WORKER)


if __name__ == "__main__":
    unittest.main()
