# -*- coding: utf-8 -*-
"""案件の画面(/cases。src/app/ui/cases/)とホーム(/)の配り方の安全の境目のテスト。  python -m unittest tests/app/test_cases_page.py -v

- 入口(src/app/server.py)は URL の完全一致の表だけを配る(フォルダは配らない)・部品は nosniff で CSP なし・同じ画面からだけ
- /cases の CSP はスタジオと同じ(YouTube のプレイヤーだけ外のスクリプトを許す・インラインなし・枠に入らない)・合言葉の meta が入る・/cases/ は /cases へ
- ホーム(/)の CSP はスクリプトを 'self' のままに画像(ytimg)とスタイルの属性だけ足す
部品が全部届いて画面が動くこと(404・コンソールのエラー)は e2e_portal.py・e2e_cases_*.py。
画面のファイルの決まり(インラインの script・パネルの口・id のぶつかり)は dev/ui_audit.py(test_rule_checks が見張る)。"""
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

class CasesPageHttpTest(PageServerTest):
    TMP_PREFIX = "ytt-cases-page-"

    def test_page_csp_and_token(self):
        r, body = self.req("/cases?c=abc&d=t1")
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertEqual(csp, L.PAGE_CSP["/cases"])
        self.assertIn("script-src 'self' https://www.youtube.com https://s.ytimg.com;", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn(b'name="ytt-token"', body)

    def test_parts_headers(self):
        for path in ("/cases.js", "/cases-panels/cand.css", "/cases-panels/new.css"):
            r, _ = self.req(path)
            self.assertEqual((r.status, r.getheader("X-Content-Type-Options")), (200, "nosniff"), path)
            self.assertIsNone(r.getheader("Content-Security-Policy"), path)   # CSP は画面(html)にだけ付ける

    def test_home_csp(self):
        r, _ = self.req("/")
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertEqual(csp, L.PAGE_CSP["/"])
        self.assertIn("script-src 'self';", csp)   # スクリプトは自分のファイルだけ(YouTube のプレイヤーはホームに無い)
        self.assertIn("img-src 'self' data: https://*.ytimg.com", csp)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_only_exact_paths(self):
        for path in ("/cases/cases.js", "/cases-panels/x.js", "/cases-panels/../cases.js", "/cases/index.html.bak", "/app/ui/cases/index.html", "/cases-panels/"):
            r, _ = self.req(path)
            self.assertIn(r.status, (302, 404), path)
            self.assertNotEqual(r.status, 200, path)

    def test_folder_redirect_keeps_query(self):
        r, _ = self.req("/cases/?c=abc#x")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/cases?c=abc"))
        r, _ = self.req("/cases/")
        self.assertEqual((r.status, r.getheader("Location")), (302, "/cases"))
        r, _ = self.req("/cases.html")   # 古い一覧のリンクは転送しない
        self.assertEqual(r.status, 404)

    def test_navigation_from_other_screens(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        r, _ = self.req("/cases?c=abc", headers=nav)   # ほかの画面のリンク・知らせから開ける
        self.assertEqual(r.status, 200)
        r, _ = self.req("/cases.js", headers={"Sec-Fetch-Site": "cross-site"})   # 部品は同じ画面からだけ
        self.assertEqual(r.status, 403)


if __name__ == "__main__":
    unittest.main()
