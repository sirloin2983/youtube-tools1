# -*- coding: utf-8 -*-
"""確かめる(/check。src/app/ui/check/。RS8 V1 = 殻)の配り方と、画面のファイルの決まりのテスト。  python -m unittest src/app/tests/test_check_page.py -v

- 入口(src/app/server.py)が /check・/check.js・/check.css・/check-player.js・/check-cards/<種類>.js を配る(URL の完全一致の表だけ。フォルダは配らない)
- /check の CSP は案件の画面と同じ(YouTube のプレイヤーだけ外のスクリプトを許す・インラインなし・枠に入らない)・合言葉の meta が入る・/check/ は /check へ
- ほかの画面のリンクで開ける(NAV_PAGES)・窓の中のホームの画面(L.appwindow_mod.PORTAL_PAGES)
- 画面のファイル: インラインの script・on〇〇= が無い・相対パス・カード 4 本が殻のあとに読まれ CheckCards.define で登録する・
  カードの中で document.getElementById / document.querySelector を使わない(殻の id とぶつけない)
(名前は test_check_page = 案件の画面の test_cases_page と同じ形)"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import re
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(SRC, "home"))
sys.path.insert(0, os.path.join(SRC, "home", "tests"))
if SRC not in sys.path:
    sys.path.append(SRC)
sys.path.insert(0, TESTS)   # 土台 _pagetest.py(入口を立てる共通の準備)
from _pagetest import PageServerTest, L  # noqa: E402

UI = os.path.join(SRC, "app", "ui", "check")
CARDS = ("value", "read", "voice", "time")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
        self.assertIn("動画編集ツール — 確かめる".encode("utf-8"), body)
        self.assertIn(b'name="ytt-token"', body)

    def test_parts_are_served(self):
        for path in ["/check.js", "/check.css", "/check-player.js"] + ["/check-cards/%s.js" % n for n in CARDS]:
            r, body = self.req(path)
            self.assertEqual(r.status, 200, path)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff", path)
            self.assertIsNone(r.getheader("Content-Security-Policy"), path)   # CSP は画面(html)にだけ付ける
            self.assertGreater(len(body), 200, path)
        r, _ = self.req("/check.js")
        self.assertTrue(r.getheader("Content-Type").startswith("application/javascript"))
        r, _ = self.req("/check.css")
        self.assertTrue(r.getheader("Content-Type").startswith("text/css"))

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
        self.assertIn("/check", L.NAV_PAGES)
        self.assertIn("/check", L.appwindow_mod.PORTAL_PAGES)


class CheckPageFilesTest(unittest.TestCase):
    def test_no_inline_script_or_handlers(self):
        html = read(os.path.join(UI, "index.html"))
        for m in re.finditer(r"<script\b([^>]*)>", html):
            self.assertIn("src=", m.group(1), "インラインの script は CSP で動かない: " + m.group(0))
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", html), "on〇〇= は CSP で動かない")
        self.assertNotRegex(html, r"(src|href)=\"/", "画面の部品は相対パスで読む")
        shell = html.index('src="check.js"')
        self.assertLess(shell, html.index('src="check-player.js"'))
        for n in CARDS:   # カードは殻(check.js)のあとに読む(CheckCards.define を使うため)
            self.assertLess(shell, html.index('src="check-cards/%s.js"' % n), n)
        self.assertEqual(sorted(L.CHECK_CARDS), sorted(CARDS))

    def test_cards_share_the_contract(self):
        for n in CARDS:
            js = read(os.path.join(UI, "cards", n + ".js"))
            self.assertIn("CheckCards.define('%s'" % n, js)
            self.assertNotRegex(js, r"document\.(getElementById|querySelector)", "%s: カードの中の要素は el.querySelector で引く" % n)
            self.assertNotRegex(js, r"\son[a-z]+=", n)
        shell = read(os.path.join(UI, "check.js"))
        for key in ("render(card, el, ctx)", "keys(e, card)", "keybar(card)", "unmount()", "typingKeys"):   # 口の説明(V2 への申し送り)が殻の先頭にある
            self.assertIn(key, shell, key)
        for path in ("check.js", "player.js") + tuple("cards/%s.js" % n for n in CARDS):
            code = read(os.path.join(UI, path))
            self.assertNotRegex(code, r"""(?:fetch|URL|http)\(\s*['"]/(?!/)""", "%s: 絶対パスを書かない" % path)
            self.assertNotRegex(code, r"\b(confirm|alert|prompt)\(", path)
            self.assertNotIn("visibilitychange", code, path)   # 離れた・戻ったは UIKit.life

    def test_held_send_is_confirmed_by_this_page_only(self):
        """6b-1(決定 Q12 (a)): 保留の [送る] は別の窓へ移っただけ(blur)では確定しない・答え / 飛ばす / flush は画面の印 page を送る"""
        shell = read(os.path.join(UI, "check.js"))
        leave = shell[shell.index("UIKit.life.onLeave"):]
        leave = leave[:leave.index("});")]
        self.assertRegex(leave, r"if \(reason !== 'blur'\) \{.*\n\s*flush\(\);", "flush は blur の外だけ")
        for api in ("api/check/flush', { body: { page: PAGE }", "api/check/skip', { body: { card: card.id, page: PAGE }", "page: PAGE };"):
            self.assertIn(api, shell, api)


if __name__ == "__main__":
    unittest.main()
