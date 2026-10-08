#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows の cmd・pip がシステムの文字コード(日本語の Windows では cp932)で読むファイルが ASCII だけか・.bat が CRLF かのテスト。
2026-10-08: setup/requirements.txt の 1 行目に日本語が入り、pip install -r が UnicodeDecodeError で落ちる形になっていた(054c3ec で混入)。
実行(リポジトリ直下): python -m unittest dev/tests/test_setup_ascii.py"""
import fnmatch
import glob
import os
import unittest

TOP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # リポジトリ直下
SKIP_DIRS = {".git", "node_modules", "dist", "bin", "obj", "__pycache__"}


def repo_files(pattern):
    """リポジトリの中の pattern(fnmatch の形)に合うファイル(作られる物の置き場所は除く)"""
    out = []
    for d, dirs, names in os.walk(TOP):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        out += [os.path.join(d, n) for n in fnmatch.filter(names, pattern)]
    return sorted(out)


def non_ascii_lines(path):
    with open(path, "rb") as f:
        return [i for i, line in enumerate(f.read().split(b"\n"), 1) if any(c > 0x7F for c in line)]


class TestSetupAscii(unittest.TestCase):
    def test_bat_ascii_crlf(self):
        bats = repo_files("*.bat")
        self.assertTrue(any(p.endswith(os.path.join("setup", "install.bat")) for p in bats), "setup/install.bat が見つからない")
        for p in bats:
            rel = os.path.relpath(p, TOP)
            self.assertEqual(non_ascii_lines(p), [], rel + " に ASCII 以外の文字(行番号)")
            with open(p, "rb") as f:
                b = f.read()
            self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), rel + " に CRLF でない改行")

    def test_requirements_ascii(self):
        reqs = glob.glob(os.path.join(TOP, "setup", "requirements*.txt"))
        self.assertTrue(reqs, "setup/requirements*.txt が見つからない")
        for p in reqs:
            rel = os.path.relpath(p, TOP)
            self.assertEqual(non_ascii_lines(p), [], rel + " に ASCII 以外の文字(行番号)")
            with open(p, "rb") as f:
                f.read().decode("cp932")      # pip が日本語の Windows で読むときと同じ


if __name__ == "__main__":
    unittest.main()
