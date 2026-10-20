# -*- coding: utf-8 -*-
"""pipeline/transcribe の本物と疑似の差し込み口 backend のテスト(役割で組み直す RS2-2)。

    py -3.12 -m unittest src/pipeline/transcribe/tests/test_txbackend.py -v

編集の serve を読まずに動く(この層は app = serve・ed_state と ⑤ = eval を読まない)。serve の登録で S.backend_name に合わせて
切り替わることは src/editor/tests/test_names.py(test_metrics から)が確かめる。
置き場所は ytt/workdata、外の道具などは持ち主を直に読む(
持ち主が S の差し替えに従うことは test_names.py の TestOwnersFollowServePatches)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend  # noqa: E402


class TestBackend(unittest.TestCase):
    def tearDown(self):
        backend.set_selector(lambda: backend.REAL)

    def test_flags_mode_and_is_fake(self):
        """疑似の旗は backend の 1 か所: mode() は環境変数 TRANSCRIBE_BACKEND を呼ぶたびに読む・is_fake() は select() の Backend の名前(RS5-D)"""
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "worker-fake"}):
            self.assertEqual(backend.mode(), "worker-fake")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRANSCRIBE_BACKEND", None)
            self.assertEqual(backend.mode(), "")
        self.assertFalse(backend.is_fake())

        class Fake(backend.Backend):
            name = backend.FAKE_NAME
        backend.set_selector(lambda: Fake())
        self.assertTrue(backend.is_fake())

    def test_selector_reads_each_time(self):
        other = backend.Backend()
        flag = {"on": False}
        backend.set_selector(lambda: other if flag["on"] else backend.REAL)
        self.assertIs(backend.select(), backend.REAL)
        flag["on"] = True
        self.assertIs(backend.select(), other)


if __name__ == "__main__":
    unittest.main()
