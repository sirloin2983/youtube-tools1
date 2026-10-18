"""dev/loc.py(コードの行数を数える道具)のテスト。小さな見本の文字列で、言語ごとのコメント・空行・docstring・コードの後ろのコメントと分け方を確かめる"""
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

    def test_python_syntax_error_falls_back_to_hash(self):
        self.check(".py", "def (:\n# c\nx\n", 3, 2)

    def test_js_and_cs(self):
        src = ("// 頭\n"
               "/* ブロック\n   の続き */\n"
               "const a = 1; // 後ろ\n"
               "const u = 'http://x'; /* 後ろ */\n"
               "const t = `複数行\n// 文字列の中\n`;\n"
               "/* 前 */ b();\n"
               "\n")
        for ext in (".js", ".cjs", ".mjs", ".gs", ".cs"):
            self.check(ext, src, 9, 6)

    def test_css_has_no_line_comment(self):
        self.check(".css", "/* 説明 */\na { background: url(//x/y.png); }\n\n/*\n*/\n", 4, 1)

    def test_html_with_script_and_style(self):
        src = ("<!-- 説明\n 続き -->\n"
               "<div>a</div> <!-- 後ろ -->\n"
               "<script>\n"
               "// JS のコメント\n"
               "let s = '<!-- 文字列 -->';\n"
               "</script>\n"
               "<style>\n/* CSS */\np{}\n</style>\n")
        self.check(".html", src, 11, 7)

    def test_bat(self):
        self.check(".bat", "@echo off\nREM 説明\n@rem 小文字\n:: 説明\nset X=1 & rem 後ろ\n:label\n\n", 6, 3)

    def test_ps1(self):
        self.check(".ps1", "# 説明\n<#\n 長い説明\n#>\n$x = 1 # 後ろ\n<# 1 行 #> Write-Host\n", 6, 2)

    def test_vbs(self):
        self.check(".vbs", "' 説明\nRem 説明\nDim x ' 後ろ\nremote = 1\n", 4, 2)

    def test_lua(self):
        self.check(".lua", "-- 説明\n--[[ 長い\n説明 ]]\nlocal x = 1 -- 後ろ\n\n", 4, 1)

    def test_blank_lines_with_spaces_are_blank(self):
        self.check(".py", "x = 1\n   \n\t\ny = 2\n", 2, 2)


class ClassifyTest(unittest.TestCase):
    def test_layers_and_kinds(self):
        cases = {
            "src/app/cards.py": ("src/app", "本体"),
            "src/app/tests/test_x.py": ("src/app", "テスト"),
            "src/flow/tests/helper.js": ("src/flow", "テスト"),
            "src/pipeline/e2e_run.py": ("src/pipeline", "テスト"),
            "dev/lint.py": ("dev", "開発の道具"),
            "dev/tests/test_lint.py": ("dev", "テスト"),
            "friend-apps/launcher/Launcher.cs": ("friend-apps/launcher", "本体"),
            "setup/install.bat": ("setup", "本体"),
            "push.bat": ("(直下)", "本体"),
        }
        for path, want in cases.items():
            self.assertEqual(loc.classify(path), want, path)

    def test_not_counted(self):
        for path in ("codemap/dev.md", "codemap/x.js", "src/app/ui/home/vendor/hls.min.js", "src/app/a.json", "README.md", "a.txt"):
            self.assertIsNone(loc.classify(path), path)


class ReportTest(unittest.TestCase):
    def test_net_diff_only(self):
        before = loc.tally([("src/app/a.py", "x = 1\ny = 2\n"), ("dev/t.py", "# c\nz = 3\n")])
        now = loc.tally([("src/app/a.py", "x = 1\n"), ("src/app/tests/test_a.py", "assert 1\n")])
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
