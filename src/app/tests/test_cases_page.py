# -*- coding: utf-8 -*-
"""案件の画面(/cases。src/app/ui/cases/。RS8 C1 = 殻)の配り方と、画面のファイルの決まりのテスト。  python -m unittest src/app/tests/test_cases_page.py -v

- 入口(src/app/server.py)が /cases・/cases.js・/cases.css・/cases-panels/<名前>.js を配る(URL の完全一致の表だけ。フォルダは配らない)
- /cases の CSP はスタジオと同じ(YouTube のプレイヤーだけ外のスクリプトを許す・インラインなし・枠に入らない)・合言葉の meta が入る・/cases/ は /cases へ
- 画面のファイル: インラインの script・on〇〇= が無い・パネル 3 本が同じ口(define・mount・update・unmount・keys・keybar)を持つ・
  パネルの中で document.getElementById / document.querySelector を使わない(殻とほかのパネルの id とぶつけない。notes:docs/design/rs8-cases-build.md 1-2)
- ホームの組み替え(RS8 C3): 新しい案件のパネル cases-panels/new.js・new.css と ホームの運用の中の portal-edit.js を配る・ホーム(/)の CSP は
  スクリプトを 'self' のままに画像(ytimg)とスタイルの属性だけ足す・新しい案件の引き出しの中の id(スタジオ ① の rank.js・queue.js が document.querySelector で引く物)は
  ホームの id とぶつからない
(名前は test_cases_page = manage/cases/tests/test_cases.py と重ねない)"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(SRC, "app"))
sys.path.insert(0, os.path.join(SRC, "app", "tests"))
if SRC not in sys.path:
    sys.path.append(SRC)
sys.path.insert(0, TESTS)   # 土台 _pagetest.py(入口を立てる共通の準備)
from _pagetest import PageServerTest, L  # noqa: E402

UI = os.path.join(SRC, "app", "ui", "cases")
PANELS = ("cand", "proof", "cut")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
        self.assertIn("動画編集ツール — 案件".encode("utf-8"), body)
        self.assertIn(b'name="ytt-token"', body)

    def test_parts_are_served(self):
        for path in ["/cases.js", "/cases-caselink.js", "/cases.css", "/cases-panels/cand.css", "/cases-panels/proof.css", "/cases-panels/machpick.js", "/cases-edhost.js"] + ["/cases-panels/%s.js" % n for n in PANELS]:
            r, body = self.req(path)
            self.assertEqual(r.status, 200, path)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff", path)
            self.assertIsNone(r.getheader("Content-Security-Policy"), path)   # CSP は画面(html)にだけ付ける
            self.assertGreater(len(body), 200, path)
        r, _ = self.req("/cases.js")
        self.assertTrue(r.getheader("Content-Type").startswith("application/javascript"))

    def test_home_parts_and_csp(self):
        for path in ("/cases-panels/new.js", "/cases-panels/new.css", "/portal-edit.js"):
            r, body = self.req(path)
            self.assertEqual(r.status, 200, path)
            self.assertGreater(len(body), 200, path)
            self.assertIsNone(r.getheader("Content-Security-Policy"), path)
        r, body = self.req("/")
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertEqual(csp, L.PAGE_CSP["/"])
        self.assertIn("script-src 'self';", csp)   # スクリプトは自分のファイルだけ(YouTube のプレイヤーはホームに無い)
        self.assertIn("img-src 'self' data: https://*.ytimg.com", csp)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        for needle in (b'id="newDrawer"', b'id="opsBox"', b'id="checkStart"', b'id="editOpsBox"', b'src="/portal-edit.js"'):
            self.assertIn(needle, body)

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
        r, _ = self.req("/cases.html")   # 以前の一覧のリンクの転送は棚卸し G5 で消した
        self.assertEqual(r.status, 404)

    def test_navigation_from_other_screens(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        r, _ = self.req("/cases?c=abc", headers=nav)   # ほかの画面のリンク・知らせから開ける
        self.assertEqual(r.status, 200)
        r, _ = self.req("/cases.js", headers={"Sec-Fetch-Site": "cross-site"})   # 部品は同じ画面からだけ
        self.assertEqual(r.status, 403)
        self.assertIn("/cases", L.NAV_PAGES)


if __name__ == "__main__":
    unittest.main()
