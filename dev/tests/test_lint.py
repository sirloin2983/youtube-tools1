"""dev/lint.py(コードの基準を測る道具)の部品のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_lint.py

2026-10-09 に「木をなめるのを 1 ファイル 1 回に」「窓のキーをハッシュからタプルに」変えた(出力は前後で同じ)ので、その境目を守る。
"""
import ast
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/
sys.path.insert(0, HERE)
import lint  # noqa: E402


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
        self.assertEqual(lint.dup_helpers("src/ytt_core/m.py", nodes_of(src), src), [])


class TestDupBlocks(unittest.TestCase):
    def test_same_block_in_two_files(self):
        lines = "".join("    value_%d = compute(%d)\n" % (i, i) for i in range(14))
        old_repo, old_src = lint.REPO, lint.SRC
        with tempfile.TemporaryDirectory() as repo:
            src = os.path.join(repo, "src")
            os.makedirs(os.path.join(src, "t"))
            os.makedirs(os.path.join(repo, "dev"))
            for n in ("a.py", "b.py"):
                with open(os.path.join(src, "t", n), "w", encoding="utf-8") as f:
                    f.write("def f():\n%s" % lines)
            try:
                lint.REPO, lint.SRC = repo, src
                groups = lint.dup_blocks(12, lint.Corpus())
            finally:
                lint.REPO, lint.SRC = old_repo, old_src
        self.assertTrue(groups)
        self.assertEqual({f for f, _ln in groups[0]}, {"src/t/a.py", "src/t/b.py"})
        self.assertEqual(lint.dup_blocks.__code__.co_argcount, 2)


if __name__ == "__main__":
    unittest.main()
