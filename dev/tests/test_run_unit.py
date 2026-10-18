"""dev/run_unit.py(層ごとに unittest を流す道具)の一覧の作り方と、1 本だけの実行。リポジトリ直下で:

    py -3.12 -m unittest dev/tests/test_run_unit.py
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/
sys.path.insert(0, HERE)
import run_unit as R  # noqa: E402


def touch(root, rel, text=""):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


FIXTURE = [
    "src/manage/keep/tests/test_backup.py",
    "src/manage/keep/tests/test_cleanup.py",
    "src/manage/keep/tests/e2e_keep.py",
    "src/manage/keep/tests/helper.py",
    "src/flow/tests/test_run.py",
    "src/editor/tests/test_metrics.py",
    "src/editor/tests/test_backend.py",
    "dev/tests/test_resolve_pack_contract.py",
    "dev/tests/test_lint.py",
    "dev/tests/e2e_pipeline.py",
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
        self.assertIn("src/manage/keep/tests/test_backup.py", got)
        self.assertIn("src/flow/tests/test_run.py", got)
        self.assertIn("dev/tests/test_lint.py", got)
        self.assertFalse(any("e2e_" in r or "helper" in r for r in got))

    def test_editor_runs_by_module_with_its_own_cwd(self):
        units = {u.rel: u for u in R.build_units(self.tmp.name) if u.rel.startswith("src/editor/")}
        self.assertEqual(sorted(units), ["src/editor/tests/test_backend.py", "src/editor/tests/test_metrics.py"])
        self.assertEqual(units["src/editor/tests/test_backend.py"].args, ["test_backend"])
        self.assertEqual(units["src/editor/tests/test_metrics.py"].args, ["test_metrics"])   # クラスが無ければモジュールごと
        self.assertTrue(all(u.cwd.replace(os.sep, "/").endswith("src/editor/tests") for u in units.values()))
        with open(os.path.join(self.tmp.name, "src/editor/tests/test_metrics.py"), "w", encoding="utf-8") as f:
            f.write("class TestPure(unittest.TestCase):\n    pass\nfrom test_backend import *\nclass TestX(unittest.TestCase):\n    pass\n")
        try:
            got = [u for u in R.build_units(self.tmp.name) if u.rel == "src/editor/tests/test_metrics.py"][0]
            self.assertEqual(got.args, ["test_metrics.TestPure", "test_metrics.TestX"])   # 星の import で読んだ物はそのモジュールの回で
        finally:
            open(os.path.join(self.tmp.name, "src/editor/tests/test_metrics.py"), "w").close()

    def test_contract_is_marked_solo(self):
        labels = {u.rel: u.label for u in R.build_units(self.tmp.name)}
        self.assertIn("単独", labels["dev/tests/test_resolve_pack_contract.py"])
        self.assertNotIn("単独", labels["dev/tests/test_lint.py"])

    def test_only_by_layer_folder_and_dev(self):
        self.assertEqual(sorted(set(r.split("/")[1] for r in self.rels(["manage"]))), ["manage"])
        self.assertEqual(self.rels(["src/manage/keep"]), ["src/manage/keep/tests/test_backup.py", "src/manage/keep/tests/test_cleanup.py"])
        self.assertEqual(self.rels(["editor"]), ["src/editor/tests/test_backend.py", "src/editor/tests/test_metrics.py"])
        self.assertTrue(all(r.startswith("dev/") for r in self.rels(["dev"])))
        self.assertEqual(self.rels(["manage", "flow"]), sorted(self.rels(["manage"]) + self.rels(["flow"])))

    def test_only_unknown_is_empty(self):
        self.assertEqual(self.rels(["nosuch"]), [])

    def test_run_one_tiny_real_test(self):
        with tempfile.TemporaryDirectory() as d:
            touch(d, "tests/test_tiny.py", "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
            r = R.run_one(R.Unit("tests/test_tiny.py", d, ["tests/test_tiny.py"], "tiny"))
            self.assertTrue(r.ok, r.err)
            self.assertEqual(r.count, 1)

    def test_cjs_runs_with_node_test(self):
        """.cjs(node --test)も一覧に入り、node で流す"""
        with tempfile.TemporaryDirectory() as d:
            touch(d, "src/app/tests/test_tiny.cjs",
                  "const { test } = require('node:test');\nconst assert = require('node:assert');\n"
                  "test('a', () => assert.ok(true));\ntest('b', () => assert.ok(true));\n")
            touch(d, "src/app/tests/helper.cjs")
            units = [u for u in R.build_units(d) if u.rel.endswith(".cjs")]
            self.assertEqual([u.rel for u in units], ["src/app/tests/test_tiny.cjs"])
            if not R.NODE:
                self.skipTest("node が無い")
            r = R.run_one(units[0])
            self.assertTrue(r.ok, r.err)
            self.assertEqual(r.count, 2)
            touch(d, "src/app/tests/test_tiny.cjs", "const { test } = require('node:test');\ntest('x', () => { throw new Error('落ちる'); });\n")
            self.assertFalse(R.run_one(units[0]).ok)


if __name__ == "__main__":
    unittest.main()
