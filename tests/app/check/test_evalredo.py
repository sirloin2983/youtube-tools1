"""評価用にした文書を評価用の決まりで作り直す(src/app/check/evalredo.py。10-25)。評価用のフォルダへ取り込まれた物だけ・1 本ずつ・頼んだ物は外す。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_evalredo.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import evalredo as ER  # noqa: E402


class EvalRedoTest(unittest.TestCase):
    def test_one_at_a_time_after_intake(self):
        app = kit.tempdir(self, "ytt-evalredo-")
        kit.write(os.path.join(app, "check", ER.NAME), {"tids": ["a1", "a2"]})
        docs = {"a1": {"evalSet": True, "sourcePath": "E:/学習用データ/x.mov", "updatedAt": 1},   # まだ取り込まれていない
                "a2": {"evalSet": True, "sourcePath": "E:/評価用データ/y.mov", "updatedAt": 2}}
        calls, logs = [], []
        with mock.patch.object(ER._settings, "in_eval_dir", lambda p: "評価用データ" in str(p)):
            self.assertEqual(ER.tick(app, docs.get, lambda p, b: calls.append((p, b)), lambda: None, logs.append), "a2")
            self.assertIsNone(ER.tick(app, docs.get, lambda p, b: calls.append((p, b)), lambda: None, logs.append))   # a1 は待つ
        self.assertEqual(calls, [("/api/eval-batch/redo-one", {"id": "a2", "baseUpdatedAt": 2})])
        with open(os.path.join(app, "check", ER.NAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["tids"], ["a1"])


if __name__ == "__main__":
    unittest.main()
