#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""今の URL -> /cases の転送の表(src/app/redirects.py。RS8 C0)のテスト。
実行(リポジトリ直下): py -3.10 -m unittest src/app/tests/test_redirects.py"""
import os
import sys
import unittest
import urllib.parse

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> app -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from app import redirects  # noqa: E402

TID = "0123456789ab"


def t(path, qs="", doc_for=None):
    return redirects.target(path, urllib.parse.parse_qs(qs), doc_for)


class TestTarget(unittest.TestCase):
    def test_no_switch_always_on(self):
        """RS8 C4: スイッチ YTT_CASES_REDIRECT は消した = 転送はいつも有効(環境変数に何があっても表は同じ)"""
        self.assertFalse(hasattr(redirects, "enabled"))
        self.assertFalse(hasattr(redirects, "ENV"))
        saved = os.environ.get("YTT_CASES_REDIRECT")
        try:
            os.environ["YTT_CASES_REDIRECT"] = "0"
            self.assertEqual(t("/studio/", "video=abc_1"), "/cases?c=abc_1#cand")
        finally:
            if saved is None:
                os.environ.pop("YTT_CASES_REDIRECT", None)
            else:
                os.environ["YTT_CASES_REDIRECT"] = saved

    def test_studio(self):
        self.assertEqual(t("/studio/", "video=abc_1"), "/cases?c=abc_1#cand")
        self.assertEqual(t("/studio", "video=abc_1"), "/cases?c=abc_1#cand")
        self.assertEqual(t("/studio/", "video=../x"), "/")   # 形の違う id は案件の画面へ渡さない
        self.assertEqual(t("/studio/", "step=rank"), "/#new")
        self.assertEqual(t("/studio/", "url=" + urllib.parse.quote("https://youtu.be/x?a=1&b=2", safe="")), "/#new?url=https%3A%2F%2Fyoutu.be%2Fx%3Fa%3D1%26b%3D2")
        self.assertEqual(t("/studio/"), "/")

    def test_editor(self):
        self.assertEqual(t("/transcribe/", "doc=" + TID), "/cases?d=" + TID)   # #tab は転送先に引き継がれる
        self.assertEqual(t("/transcribe/", "doc=zz"), "/")
        self.assertEqual(t("/transcribe/", "drill=1"), "/cases?c=eval#proof")
        self.assertEqual(t("/transcribe/", "list=all"), "/")
        self.assertEqual(t("/transcribe/"), "/")

    def test_editor_media_looks_up_doc(self):
        seen = []

        def found(p):
            seen.append(p)
            return TID
        self.assertEqual(t("/transcribe/", "media=" + urllib.parse.quote("C:/a b/x.mp4"), found), "/cases?d=%s#proof" % TID)
        self.assertEqual(seen, ["C:/a b/x.mp4"])
        self.assertEqual(t("/transcribe/", "clip=C%3A%2Fz.mp4", lambda p: ""), "/#new?media=C%3A%2Fz.mp4")   # 文書が無ければ新しい案件の欄へ
        self.assertEqual(t("/transcribe/", "media=C%3A%2Fz.mp4"), "/#new?media=C%3A%2Fz.mp4")

    def test_others_are_not_redirected(self):
        for p in ("/", "/studio/api/ping", "/studio/review.js", "/transcribe/api/jobs", "/cut2resolve/", "/settings"):
            self.assertIsNone(t(p), p)


if __name__ == "__main__":
    unittest.main()
