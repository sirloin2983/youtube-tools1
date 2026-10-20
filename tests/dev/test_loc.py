"""dev/loc.py(コードの行数を数える道具)のテスト。小さな見本の文字列で、Python のコメント・空行・docstring の数え方と正味の差を確かめる"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import loc  # noqa: E402


class CountTest(unittest.TestCase):
    def check(self, ext, text, a, b):
        self.assertEqual(loc.count_text(text, ext), (a, b), ext)

    def test_python(self):
        src = ('"""モジュールの説明\n\n2 行目"""\n'
               "import os  # 後ろのコメント\n"
               "\n\n"
               "# 行のコメント\n"
               "def f():\n"
               "    '''関数の説明'''\n"
               "    s = '''複数行の\n"
               "# 文字列の中\n"
               "'''\n"
               "    return s\n"
               "class C:\n"
               '    """説明"""; x = 1\n')
        # 空行を除く 12 行。コメント = モジュールの docstring の 2 行・# の行・関数の説明 → コードは 8 行(1 行の docstring の後ろにコードがある行はコード)
        self.check(".py", src, 12, 8)


class ReportTest(unittest.TestCase):
    def test_net_diff_only(self):
        before = loc.tally([("src/app/a.py", "x = 1\ny = 2\n"), ("dev/t.py", "# c\nz = 3\n")])
        now = loc.tally([("src/app/a.py", "x = 1\n"), ("tests/app/test_a.py", "assert 1\n")])
        r = loc.report(now, before)
        self.assertEqual(r["diff"]["本体"], [-1, -1])
        self.assertEqual(r["diff"]["テスト"], [1, 1])
        self.assertEqual(r["diff"]["開発の道具"], [-2, -1])
        self.assertEqual(r["diff"]["合計"], [-2, -1])
        self.assertIn("合計 2 / 2", loc.one_line(r["now"]["totals"]).replace(",", ""))


class BlankRunRuleTest(unittest.TestCase):
    """lint の規則 R-12(dev/rule_checks.py): 空行が 3 行以上続いたら止める。2 行まではよい"""

    def test_two_ok_three_stops(self):
        import rule_checks
        self.assertEqual(rule_checks.blank_run_problems("a.py", "x\n\n\ny\n"), [])
        self.assertEqual(rule_checks.blank_run_problems("a.py", "x\n\n \n\t\ny\n\n\n\n"),
                         ["a.py:2 から空行が 3 行続く(2 行まで)", "a.py:6 から空行が 3 行続く(2 行まで)"])


if __name__ == "__main__":
    unittest.main()
