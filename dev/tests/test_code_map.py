"""dev/code_map.py(コードの地図と言葉の索引を作る道具)の部品のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_code_map.py
"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 本物の作業データに触らない(test_ytt_core の「serve の語があるテストは YTT_DATA_DIR」)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import code_map  # noqa: E402


class CodeMapTest(unittest.TestCase):
    def test_comment_head(self):
        self.assertEqual(code_map.comment_head("'use strict';\n// 送る画面の欄\n// 2 行目\nfunction a() {}\n"), "送る画面の欄")
        self.assertEqual(code_map.comment_head("/**\n * 受け取る画面\n */\nconst x = 1;\n"), "受け取る画面")
        self.assertEqual(code_map.comment_head("using System;\n// 起動\nclass A {}\n"), "起動")
        self.assertEqual(code_map.comment_head("function a() {}\n// 後ろのコメント\n"), "")

    def test_one_line_cuts_before_notes_path(self):
        tag = "no" + "tes:"   # 資料のパスの形をそのまま書くと notes_tool check が切れたパスと読む
        long = "あ" * 140 + " " + tag + "docs/spec/very-long-name.md の話"
        got = code_map.one_line(long)
        self.assertTrue(got.endswith("…"))
        self.assertNotIn(tag, got)

    def test_py_routes(self):
        src = ('"""口の見本"""\n'
               'def do_GET(u):\n'
               '    if u.path == "/api/ping":\n'
               '        return 1\n'
               '    call("GET", "/api/jobs")\n'
               'ROUTES = {"/api/cases": 1}\n')
        head, syms, serve, call = code_map.py_info("x.py", src)
        self.assertEqual(head, "口の見本")
        self.assertEqual([s[0] for s in syms], ["do_GET"])
        self.assertEqual(sorted(r for r, _ in serve), ["/api/cases", "/api/ping"])
        self.assertEqual([r for r, _ in call], ["/api/jobs"])

    def test_norm_route(self):
        self.assertEqual(code_map.norm_route("friend/api/friend/send"), "/api/friend/send")
        self.assertEqual(code_map.norm_route("/api/x/"), "/api/x")

    def test_stale(self):
        with tempfile.TemporaryDirectory() as d:
            old = code_map.OUT
            code_map.OUT = d
            try:
                pages = {"index.md": "a\n", "x.md": "b\n"}
                self.assertEqual(code_map.stale(pages), ["index.md", "x.md"])
                code_map.write(pages)
                self.assertEqual(code_map.stale(pages), [])
                with open(os.path.join(d, "gone.md"), "w") as f:
                    f.write("z")
                self.assertEqual(code_map.stale(pages), ["gone.md"])
                self.assertEqual(code_map.stale({"index.md": "a\n", "x.md": "c\n"}), ["gone.md", "x.md"])
            finally:
                code_map.OUT = old


if __name__ == "__main__":
    unittest.main()
