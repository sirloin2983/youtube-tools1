# -*- coding: utf-8 -*-
"""確かめる(/check。src/app/ui/check/)の配り方の安全の境目のテスト。  python -m unittest tests/app/test_check_page.py -v

- 入口(src/app/server.py)は URL の完全一致の表だけを配る(フォルダは配らない)・部品は nosniff で CSP なし・同じ画面からだけ
- /check の CSP は案件の画面と同じ(YouTube のプレイヤーだけ外のスクリプトを許す・インラインなし・枠に入らない)・合言葉の meta が入る・/check/ は /check へ
- ほかの画面のリンクで開ける・窓の中のホームの画面(L.appwindow_mod.PORTAL_PAGES)
部品(カード 7 種・再生の部品)が全部届いて画面が動くことは e2e_check.py(コンソールのエラー)。
画面のファイルの決まり(インラインの script・カードの登録・id のぶつかり)は dev/ui_audit.py(test_rule_checks が見張る)。"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))   # tests/app
SRC = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src")
sys.path.insert(0, os.path.join(SRC, "app"))
sys.path.insert(0, os.path.join(os.path.dirname(SRC), "tests", "app"))
if SRC not in sys.path:
    sys.path.append(SRC)
sys.path.insert(0, TESTS)   # 土台 _pagetest.py(入口を立てる共通の準備)
from _pagetest import PageServerTest, L  # noqa: E402

class CheckPageHttpTest(PageServerTest):
    TMP_PREFIX = "ytt-check-page-"

    def test_page_csp_and_token(self):
        r, body = self.req("/check?c=abc&kind=voice&back=cases")
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertEqual(csp, L.PAGE_CSP["/check"])
        self.assertEqual(csp, L.PAGE_CSP["/cases"])
        self.assertIn("script-src 'self' https://www.youtube.com https://s.ytimg.com;", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn(b'name="ytt-token"', body)

    def test_parts_headers(self):
        for path in ("/check.js", "/check-cards/value.js"):
            r, _ = self.req(path)
            self.assertEqual((r.status, r.getheader("X-Content-Type-Options")), (200, "nosniff"), path)
            self.assertIsNone(r.getheader("Content-Security-Policy"), path)   # CSP は画面(html)にだけ付ける

    def test_only_exact_paths(self):
        for path in ("/check/check.js", "/check-cards/x.js", "/check-cards/../check.js", "/check-cards/", "/app/ui/check/index.html",
                     "/check-cards/value.js.bak", "/check/player.js", "/check-cards/heavy.js"):
            r, _ = self.req(path)
            self.assertIn(r.status, (302, 404), path)
            self.assertNotEqual(r.status, 200, path)

    def test_folder_redirect_keeps_query(self):
        r, _ = self.req("/check/?c=abc&kind=read")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/check?c=abc&kind=read"))
        r, _ = self.req("/check/index.html")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/check"))

    def test_navigation_from_other_screens(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        r, _ = self.req("/check?kind=value", headers=nav)   # ホームの [始める]・案件の画面のリンクから開ける
        self.assertEqual(r.status, 200)
        r, _ = self.req("/check.js", headers={"Sec-Fetch-Site": "cross-site"})   # 部品は同じ画面からだけ
        self.assertEqual(r.status, 403)
        self.assertIn("/check", L.appwindow_mod.PORTAL_PAGES)


if __name__ == "__main__":
    unittest.main()
