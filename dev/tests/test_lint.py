"""dev/lint.py(コードの基準を測る道具)の部品のテスト。リポジトリ直下で:

    py -3.12 -m unittest dev/tests/test_lint.py

2026-10-09 に「木をなめるのを 1 ファイル 1 回に」「窓のキーをハッシュからタプルに」変えた(出力は前後で同じ)ので、その境目を守る。
"""
import ast
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
import lint  # noqa: E402
from ytt import testkit  # noqa: E402


def nodes_of(src):
    return list(ast.walk(ast.parse(src)))


class TestUnusedImports(unittest.TestCase):
    def check(self, src, name="m.py"):
        return lint.unused_imports(name, nodes_of(src), src)

    def test_used_by_name_attribute_and_text(self):
        src = "import os\nimport re\nimport json\nimport sys as system\nfrom a import b, c\nos.path.join(1)\nprint(b)\n're を文字で書いた'\n"
        self.assertEqual(sorted(n for _l, n in self.check(src)), ["c", "json", "system"])

    def test_noqa_future_star_and_init(self):
        src = "from __future__ import annotations\nimport os  # noqa: E402\nfrom x import *\nimport a.b.c\n"
        self.assertEqual(self.check(src), [(4, "a")])
        self.assertEqual(self.check("import os\n", "__init__.py"), [])

    def test_later_import_overwrites_line(self):
        self.assertEqual(self.check("import os\nimport os\n"), [(2, "os")])


class TestLongFunctions(unittest.TestCase):
    def test_limit_and_mark(self):
        body = "".join("    x = %d\n" % i for i in range(10))
        src = "def a():\n%s\n# lint: long 理由\ndef b():\n%s\ndef c():\n    pass\n" % (body, body)
        got = lint.long_functions("m.py", nodes_of(src), src, 5)
        self.assertEqual([(name, n) for _l, name, n in got], [("a", 10 + 1)])


class TestDupHelpers(unittest.TestCase):
    def test_names_and_keep_mark(self):
        src = "def _unlink(p):\n    pass\n\n\ndef ok():\n    pass\n\n\nNO_WINDOW = 1\n# lint: keep 理由\n_no_window = 2\n"
        got = lint.dup_helpers("src/x/m.py", nodes_of(src), src)
        self.assertEqual(sorted(n for _l, n, _h in got), ["NO_WINDOW", "_unlink"])
        self.assertEqual(lint.dup_helpers("src/ytt/m.py", nodes_of(src), src), [])


class TestDupBlocks(unittest.TestCase):
    def test_same_block_in_two_files(self):
        lines = "".join("    value_%d = compute(%d)\n" % (i, i) for i in range(14))
        repo = testkit.tempdir(self)
        src = os.path.join(repo, "src")
        os.makedirs(os.path.join(repo, "dev"))
        for n in ("a.py", "b.py"):
            testkit.write_text(os.path.join(src, "t", n), "def f():\n%s" % lines)
        with mock.patch.object(lint, "REPO", repo), mock.patch.object(lint, "SRC", src):
            groups = lint.dup_blocks(12, lint.Corpus())
        self.assertTrue(groups)
        self.assertEqual({f for f, _ln in groups[0]}, {"src/t/a.py", "src/t/b.py"})
        self.assertEqual(lint.dup_blocks.__code__.co_argcount, 2)


class TestStaleRefs(unittest.TestCase):
    def refs(self, src, path):
        return [(k, n) for _l, k, n in lint.stale_refs(os.path.join(lint.REPO, path), ast.parse(src), src)]

    def test_path_exists_or_not(self):
        src = '"""x。実在 src/ytt/fsio.py と flow/jobs.py・無い src/ytt/nothing_here.py と flow/nothing.py"""\n# git:ab/cd.py は見ない\n'
        self.assertEqual(self.refs(src, "src/ytt/m.py"), [("ref-path", "flow/nothing.py"), ("ref-path", "src/ytt/nothing_here.py")])

    def test_gone_names_and_ref_mark(self):
        src = '"""x"""\n# ed_alt を呼ぶ\n# 旧 ed_store(経緯)  lint: ref 経緯\nx = "ed_jobs"\n# my_ed_alt2 は別の名前\n'
        self.assertEqual(self.refs(src, "src/ytt/m.py"), [("ref-gone", "ed_alt")])

    def test_layer_number_matches_folder(self):
        self.assertEqual(self.refs('"""② 人の操作。x"""\n', "src/human/m.py"), [("ref-layer", "②(human は ③)")])
        self.assertEqual(self.refs('"""③ 人の操作。x"""\n', "src/human/m.py"), [])
        self.assertEqual(self.refs('"""② 管理(③ 人の操作を読まない)"""\n', "src/flow/m.py"), [])

    def test_tests_are_skipped(self):
        self.assertEqual(self.refs('"""ed_alt"""\n', "src/human/tests/test_x.py"), [])


if __name__ == "__main__":
    unittest.main()
