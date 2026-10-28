"""dev/run_unit.py(層ごとに unittest を流す道具)の一覧の作り方と、1 本だけの実行。リポジトリ直下で:

    py -3.12 -m unittest tests/dev/test_run_unit.py
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import tempfile
import unittest

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dev")   # dev/
sys.path.insert(0, HERE)
import run_unit as R  # noqa: E402


def touch(root, rel, text=""):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


FIXTURE = [
    "tests/manage/keep/test_backup.py",
    "tests/manage/keep/test_cleanup.py",
    "tests/manage/keep/e2e_keep.py",
    "tests/manage/keep/helper.py",
    "tests/flow/test_run.py",
    "tests/editor/test_backend.py",
    "tests/dev/test_lint.py",
    "tests/dev/e2e_pipeline.py",
    "tests/testkit.py",
    "src/flow/tests/test_old_place.py",   # src の中のテストは探さない
]


class TestBuildUnits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for rel in FIXTURE:
            touch(cls.tmp.name, rel)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rels(self, only=None):
        return [u.rel for u in R.build_units(self.tmp.name, only)]

    def test_all_files_and_no_e2e_or_helper(self):
        got = self.rels()
        self.assertIn("tests/manage/keep/test_backup.py", got)
        self.assertIn("tests/flow/test_run.py", got)
        self.assertIn("tests/dev/test_lint.py", got)
        self.assertFalse(any("e2e_" in r or "helper" in r or "testkit" in r or r.startswith("src/") for r in got))

    def test_py_runs_by_discover_in_its_own_folder(self):
        """.py は discover でそのフォルダを sys.path の先頭に(同じフォルダの道具を読める)。cwd はリポジトリ直下"""
        u = [u for u in R.build_units(self.tmp.name) if u.rel == "tests/editor/test_backend.py"][0]
        self.assertEqual(u.args, ["discover", "-s", "tests/editor", "-p", "test_backend.py", "-t", "tests/editor"])
        self.assertEqual(u.cwd, self.tmp.name)

    def test_only_by_layer_folder_and_dev(self):
        keep = ["tests/manage/keep/test_backup.py", "tests/manage/keep/test_cleanup.py"]
        self.assertEqual(self.rels(["manage/keep"]), keep)
        self.assertEqual(self.rels(["src/manage/keep"]), keep)     # 頭の src/・tests/ は無くてよい
        self.assertEqual(self.rels(["tests/manage/keep"]), keep)
        self.assertTrue(all(r.startswith("tests/dev/") for r in self.rels(["dev"])))
        self.assertEqual(self.rels(["manage", "flow"]), sorted(self.rels(["manage"]) + self.rels(["flow"])))

    def test_run_one_tiny_real_test(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "tests/x/_kit.py", "VALUE = 1\n")
            touch(d, "tests/x/test_tiny.py", "import unittest\nimport _kit\n\nclass T(unittest.TestCase):\n"
                  "    def test_ok(self):\n        self.assertEqual(_kit.VALUE, 1)\n"
                  "    def test_skip(self):\n        self.skipTest('部品が無い')\n")
            units = R.build_units(d)
            self.assertEqual([u.rel for u in units], ["tests/x/test_tiny.py"])
            r = R.run_one(units[0])
            self.assertTrue(r.ok, r.err)
            self.assertEqual((r.count, r.skipped), (2, 1))   # 飛ばした件数はまとめに出す

    def test_run_one_times_out_and_kills(self):
        """固まったテストは timeout で止めて落ちた扱い(関所が終わらないのを防ぐ)"""
        with tempfile.TemporaryDirectory() as d:
            touch(d, "tests/x/test_hang.py", "import time, unittest\n\nclass T(unittest.TestCase):\n    def test_hang(self):\n        time.sleep(30)\n")
            r = R.run_one(R.build_units(d)[0], timeout=2)
            self.assertFalse(r.ok)
            self.assertIn("時間切れ", r.err)
            self.assertLess(r.secs, 25)

    def test_cjs_runs_with_node_test(self):
        """.cjs(node --test)も一覧に入り、node で流す"""
        with tempfile.TemporaryDirectory() as d:
            touch(d, "tests/app/test_tiny.cjs",
                  "const { test } = require('node:test');\nconst assert = require('node:assert');\n"
                  "test('a', () => assert.ok(true));\ntest('b', () => assert.ok(true));\n")
            touch(d, "tests/app/helper.cjs")
            units = [u for u in R.build_units(d) if u.rel.endswith(".cjs")]
            self.assertEqual([u.rel for u in units], ["tests/app/test_tiny.cjs"])
            if not R.NODE:
                self.skipTest("node が無い")
            r = R.run_one(units[0])
            self.assertTrue(r.ok, r.err)
            self.assertEqual(r.count, 2)
            touch(d, "tests/app/test_tiny.cjs", "const { test } = require('node:test');\ntest('x', () => { throw new Error('落ちる'); });\n")
            self.assertFalse(R.run_one(units[0]).ok)


if __name__ == "__main__":
    unittest.main()
