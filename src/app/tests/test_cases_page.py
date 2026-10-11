# -*- coding: utf-8 -*-
"""案件の画面(/cases。src/app/ui/cases/。RS8 C1 = 殻)の配り方と、画面のファイルの決まりのテスト。  python -m unittest src/app/tests/test_cases_page.py -v

- 入口(src/app/server.py)が /cases・/cases.js・/cases.css・/cases-panels/<名前>.js を配る(URL の完全一致の表だけ。フォルダは配らない)
- /cases の CSP はスタジオと同じ(YouTube のプレイヤーだけ外のスクリプトを許す・インラインなし・枠に入らない)・合言葉の meta が入る・/cases/ は /cases へ
- 画面のファイル: インラインの script・on〇〇= が無い・パネル 3 本が同じ口(define・mount・update・unmount・keys・keybar)を持つ・
  パネルの中で document.getElementById / document.querySelector を使わない(殻とほかのパネルの id とぶつけない。docs/design/rs8-cases-build.md 1-2)
- ホームの組み替え(RS8 C3): 新しい案件のパネル cases-panels/new.js・new.css と ホームの運用の中の portal-edit.js を配る・ホーム(/)の CSP は
  スクリプトを 'self' のままに画像(ytimg)とスタイルの属性だけ足す・新しい案件の引き出しの中の id(スタジオ ① の rank.js・queue.js が document.querySelector で引く物)は
  ホームの id とぶつからない
(名前は test_cases_page = manage/cases/tests/test_cases.py と重ねない)"""
import http.client
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import re
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(SRC, "home"))
sys.path.insert(0, os.path.join(SRC, "home", "tests"))
if SRC not in sys.path:
    sys.path.append(SRC)
from app import server as L  # noqa: E402
from test_launch import free_ports  # noqa: E402

UI = os.path.join(SRC, "app", "ui", "cases")
PANELS = ("cand", "proof", "cut")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class CasesPageHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ytt-cases-page-")
        cls.env = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(cls.tmp, ".runtime")})
        cls.env.start()
        cls.sup = L.Supervisor(cls.tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=lambda m: None,
                               ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
        cls.srv, cls.port = L.make_server(0, cls.sup)
        cls.sup.attach(cls.srv)
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()
        cls.host = "127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.sup.close()
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.host}
        h.update(headers or {})
        conn.request("GET", path, headers=h)
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body

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
        for path in ["/cases.js", "/cases.css", "/cases-panels/cand.css", "/cases-panels/proof.css", "/cases-panels/machpick.js", "/cases-edhost.js"] + ["/cases-panels/%s.js" % n for n in PANELS]:
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
        r, _ = self.req("/cases.html")   # 以前の一覧のリンクはホームへ(C4 で /#cases から / に)
        self.assertEqual((r.status, r.getheader("Location")), (302, "/"))

    def test_navigation_from_other_screens(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        r, _ = self.req("/cases?c=abc", headers=nav)   # ほかの画面のリンク・知らせから開ける
        self.assertEqual(r.status, 200)
        r, _ = self.req("/cases.js", headers={"Sec-Fetch-Site": "cross-site"})   # 部品は同じ画面からだけ
        self.assertEqual(r.status, 403)
        self.assertIn("/cases", L.NAV_PAGES)


class CasesPageFilesTest(unittest.TestCase):
    def test_no_inline_script_or_handlers(self):
        html = read(os.path.join(UI, "index.html"))
        for m in re.finditer(r"<script\b([^>]*)>", html):
            self.assertIn("src=", m.group(1), "インラインの script は CSP で動かない: " + m.group(0))
        self.assertIsNone(re.search(r"\son[a-z]+\s*=", html), "on〇〇= は CSP で動かない")
        self.assertNotRegex(html, r"(src|href)=\"/", "画面の部品は相対パスで読む")
        for n in PANELS:   # パネルは殻(cases.js)のあとに読む(CasesPanels.define を使うため)
            self.assertLess(html.index('src="cases.js"'), html.index('src="cases-panels/%s.js"' % n), n)

    def test_panels_share_the_contract(self):
        for n in PANELS:
            js = read(os.path.join(UI, "panels", n + ".js"))
            self.assertIn("CasesPanels.define('%s'" % n, js)
            for key in ("mount:", "update:", "unmount:", "keys:", "keybar:"):
                self.assertIn(key, js, "%s に %s が無い" % (n, key))
            self.assertNotRegex(js, r"document\.(getElementById|querySelector(All)?)\(",
                                "%s: パネルの中は root.querySelector で引く(殻・ほかのパネルの id とぶつけない)" % n)
            self.assertNotRegex(js, r"addEventListener\(\s*['\"]visibilitychange", "UIKit.life を使う")

    def test_proof_panel_parts(self):
        """校正のパネル(C2b): 3 択の部品もパネルと同じ決まり・編集の部品は transcribe/ の相対パスで読む・殻より後・パネルより前に読む"""
        js = read(os.path.join(UI, "panels", "machpick.js"))
        self.assertNotRegex(js, r"document\.(getElementById|querySelector(All)?)\(")
        host = read(os.path.join(UI, "edhost.js"))
        self.assertIn("'transcribe/' + n", host)
        self.assertNotRegex(host, r"['\"]/(api|transcribe)/", "相対パスで読む")
        self.assertIn("window.EditHost", host)
        html = read(os.path.join(UI, "index.html"))
        self.assertLess(html.index('src="cases.js"'), html.index('src="cases-edhost.js"'))
        self.assertLess(html.index('src="cases-edhost.js"'), html.index('src="cases-panels/proof.js"'))
        self.assertLess(html.index('src="cases-panels/machpick.js"'), html.index('src="cases-panels/proof.js"'))
        self.assertIn('class="ui-header top"', html, "編集の app.js が .top の高さを見る")
        for name in ("app.js", "app-core.js", "app-rows.js"):   # 古い編集の画面の動きは変えない口(window.EditHost が無ければ今までどおり)
            self.assertIn("EDIT_HOST", read(os.path.join(SRC, "editor", name)), name)

    def test_shell_uses_life_and_one_keydown(self):
        js = read(os.path.join(UI, "cases.js"))
        self.assertEqual(len(re.findall(r"addEventListener\(\s*'keydown'", js)), 1, "keydown は殻の 1 本")
        self.assertIn("UIKit.life.onLeave", js)
        self.assertNotIn("visibilitychange", js)
        self.assertNotRegex(js, r"['\"]/(api|studio|transcribe|cut2resolve)/", "API は相対パス(api() の 1 か所)")

    def test_home_new_panel_shape(self):
        js = read(os.path.join(UI, "panels", "new.js"))
        self.assertIn("window.NewCasePanel", js)
        self.assertIn("CasesPanels.define('new'", js)
        for key in ("mount:", "update:", "unmount:", "setVisible:"):
            self.assertIn(key, js)
        self.assertNotRegex(js, r"document\.(getElementById|querySelector(All)?)\(")
        self.assertNotIn("visibilitychange", js)

    def test_home_ids_do_not_collide_with_new_panel(self):
        """rank.js・queue.js は document.querySelector('#id') で引くので、引き出しの中の id はホームの id と重ならないこと"""
        ids = lambda text: set(re.findall(r'\bid="([A-Za-z][\w-]*)"', text))
        home = ids(read(os.path.join(SRC, "home", "portal.html")))
        mine = set()
        for name in ("rank.js", "queue.js"):
            mine |= ids(read(os.path.join(SRC, "studio", name)))
        mine |= {"paneRank"}
        self.assertGreater(len(mine), 40)   # 取り損ねていない
        self.assertEqual(sorted(home & mine), [])

    def test_static_table_points_to_files(self):
        for url, (name, base) in L.STATIC.items():
            if url.startswith("/cases") or url == "/portal-edit.js":
                self.assertTrue(os.path.isfile(os.path.join(base, name)), url)


if __name__ == "__main__":
    unittest.main()
