#!/usr/bin/env python3
"""段階7(画面の形の準備と窓)の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、3つとも入口に取り込む)。

    python src/app/tests/e2e_window.py

  (RS8 C4: スタジオ・編集の画面は消えたので、ツールの画面の場面は案件の画面 /cases で確かめる。appnav の 4 項目と旧 URL の転送は e2e_portal.py)
  7-0 画面のエラーの記録: 案件の画面・設定の画面で起きたエラー(throw・Promise の失敗)が client-errors.jsonl に1行ずつ残る
  (7-1 解析の設定の引き継ぎ(localStorage → サーバー)は、欄を設定の画面へ移し引き継ぎの仕組みも消えたので 2026-10-10 に外した)
  7-2 離れた・戻った: 別の窓へ移った(blur)で「離れた」、埋め込み(iframe)にフォーカスがあるときは離れたことにしない、戻った(focus)
  7-3 窓: 入口の「窓で開く」の切り替え(2026-09-27 から既定で窓)。窓(display-mode: standalone)の中の「開く」は入口に頼んで Edge のアプリモードで開き
      (Edge の代わりに引数を記録する偽のプログラム。YTT_APP_BROWSER)、外のサイトはいつものブラウザ(偽の記録)で開く。
      普通のタブでは今までどおり新しいタブで開く(target=_blank のリンクを足して押す)。ホームの中身のリンク(target なし。入口 0.42.0 の S-15)は窓の中でも同じ窓で移り、
      Ctrl を押しながらのときだけ窓で開く(配信が無いときの空の表示のボタンで確かめる。S-13)

Edge の本物の窓(リンクの行き先・YouTube の埋め込み・閉じる操作)はクラウド(Linux)で再現できないので、実機で確かめる。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.request
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
HERE = os.path.dirname(TESTS)   # src/app(入口)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.append(os.path.dirname(HERE))   # src(app 層の import の根)
from ytt import appwindow as W  # noqa: E402
from app import server as L  # noqa: E402
from app import mount as M  # noqa: E402
from e2e_portal import wait_js, open_advanced  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports  # noqa: E402
from ytt import fsio  # noqa: E402

APP_MODE = """(() => {   // Edge のアプリモードの窓のふり(display-mode: standalone)
  const real = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q) ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : real(q);
})();"""


def fake_browser(tmp):
    """Edge の代わり: 渡された引数を1行の JSON で記録するだけのプログラム"""
    log = os.path.join(tmp, "fake-edge.jsonl")
    path = os.path.join(tmp, "fake-edge")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport json, sys\nwith open(%r, 'a', encoding='utf-8') as f:\n    f.write(json.dumps(sys.argv[1:]) + '\\n')\n" % (sys.executable, log))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    if os.name == "nt":   # Windows は #! のファイルを実行できないので、同じ Python で動かす .bat を挟む
        bat = path + ".bat"
        with open(bat, "w", encoding="ascii", newline="\r\n") as f:
            f.write('@"%s" "%s" %%*\n' % (sys.executable, path))
        return bat, log
    return path, log


def read_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f.read().splitlines() if x.strip()]
    except OSError:
        return []


def wait_until(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return fn()


PORTAL_LINK = 'a[data-ui-appnav-item="portal"]'   # ヘッダーの appnav の「ホーム」(data-ui-portal 付き。ui-kit v27)


def add_link(pg, el_id, href, blank):
    """画面に <a> を 1 つ足す(target=_blank のリンクの扱いを、ツールのカードに頼らずに確かめる)"""
    pg.evaluate("""([id, href, blank]) => { const a = document.createElement('a'); a.id = id; a.href = href; if (blank) { a.target = '_blank'; a.rel = 'noopener'; }
                    a.textContent = id; document.body.appendChild(a); }""",
                [el_id, href, blank])


def main():
    ok = True
    events = []

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-window-e2e-")
    exe, edge_log = fake_browser(tmp)
    env = {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake",
           "STUDIO_HOME": os.path.join(tmp, "studio-home"), "YTT_APP_BROWSER": exe}
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    srv = sup = th = None
    try:
        for s in L.TOOLS:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
        from ytt import layout as _layout
        _layout.copy_shared_code(tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        ports = dict(zip(L.TOOL_IDS, free_ports(3)))
        sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=ports, mounts=tuple(M.MOUNTS))
        srv, port = L.make_server(0, sup)
        browsed = []
        srv.window = W.Opener(os.path.join(tmp, "app"), fsio.atomic_write, browser_open=lambda u: browsed.append(u) or True, log=events.append)
        sup.attach(srv)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        sup.start_all()
        base = "http://127.0.0.1:%d/" % port
        clog = srv.client_log.path

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                errors = []
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base)
                check(wait_js(pg, "document.querySelectorAll('.pt-tool[data-state=running]').length === 2", 60000), "スタジオと編集がホームに取り込んで動作中(cut2resolve は部品なのでカードを出さない)")
                open_advanced(pg)   # 開くのリンクは「詳しく」の中(段階5)
                pg.click("[data-ui-settings]")   # 窓で開くは ⚙ 設定の「ホーム」の節(UI の見直し M10。以前は「詳しく」の中)

                # ---- 7-3 ホームの「窓で開く(試用)」 ----
                check(wait_js(pg, "!document.getElementById('winBox').hidden", 10000), "[7-3] ホームに「窓で開く」が出る")
                check(pg.is_checked("#winMode") is True and pg.is_enabled("#winMode"), "[7-3] 既定は窓(オン。2026-09-27 ユーザー決定)・Edge があるので切り替えられる")
                check(pg.is_visible("#btnWinNow"), "[7-3] 普通のタブでは「いま窓で開く」が出る")
                pg.click("#winMode")
                check(wait_js(pg, "document.querySelector('#toast').textContent.indexOf('いつものブラウザ') >= 0", 10000) and W.read_mode(srv.window.settings_path) == "browser",
                      "[7-3] オフにすると、次の起動からいつものブラウザ(設定に browser が残る)")
                pg.click("#winMode")
                check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('窓で開きます') >= 0)", 10000), "[7-3] オンに戻した(次の起動から)")
                check(W.read_mode(srv.window.settings_path) == "app", "[7-3] 設定が settings.json に残る: %s" % srv.window.settings_path)
                pg.click("#btnWinNow")
                got = wait_until(lambda: read_lines(edge_log))
                check(got and got[-1][0] == "--app=http://localhost:%d/" % port and got[-1][1].startswith("--user-data-dir=") and
                      got[-1][1].endswith(os.path.join("app", "browser-profile")), "[7-3] 「いま窓で開く」で Edge(偽)がアプリモード・専用のプロファイルで起動: %s" % got[-1:])
                check(not any("remote-debugging" in a for a in (got[-1] if got else [])), "[7-3] リモートデバッグのポートは開かない")
                pg.keyboard.press("Escape")   # ⚙ を閉じる(開いている間は後ろの画面を押せない)
                wait_js(pg, "document.getElementById('uiSettingsDrawer').hidden", 5000)
                # 普通のタブ: target=_blank のリンクは今までどおり新しいタブ(RS8 C4: ツールの画面が消えたので、案件の画面へのリンクを足して押す)
                add_link(pg, "blankLink", "/cases?c=x", True)
                with ctx.expect_page() as info:
                    pg.click("#blankLink")
                tab = info.value
                tab.wait_for_load_state()
                check("/cases?c=x" in tab.url, "[7-3] 普通のタブでは target=_blank のリンクは新しいタブ(今までどおり): %s" % tab.url)
                tab.close()

                # 窓の中(display-mode: standalone のふり)
                actx = browser.new_context(viewport={"width": 1200, "height": 850})
                actx.add_init_script(APP_MODE)
                win = actx.new_page()
                win.on("pageerror", lambda e: errors.append(str(e)))
                win.goto(base)
                check(wait_js(win, "document.querySelectorAll('.pt-tool[data-state=running]').length === 2", 30000), "[7-3] 窓の中のホーム")
                open_advanced(win)
                win.click("[data-ui-settings]")
                check(win.evaluate("UIKit.win.isApp()") is True and wait_js(win, "!document.getElementById('winBox').hidden", 10000) and not win.is_visible("#btnWinNow"),
                      "[7-3] 窓の中では「いま窓で開く」を出さない")
                win.keyboard.press("Escape")
                wait_js(win, "document.getElementById('uiSettingsDrawer').hidden", 5000)
                n0 = len(read_lines(edge_log))
                opened = []
                actx.on("page", lambda pg2: opened.append(pg2.url))
                add_link(win, "blankLink", "/cases?c=y", True)
                win.click("#blankLink")
                got = wait_until(lambda: read_lines(edge_log)[n0:])
                check(got and got[-1][0] == "--app=http://localhost:%d/cases?c=y" % port, "[7-3] 窓の中の target=_blank のリンクは Edge のアプリモードの窓で開く: %s" % got[-1:])
                time.sleep(0.5)
                check(not opened, "[7-3] 窓の中ではタブを増やさない: %s" % opened)
                win.evaluate("""() => { const a = document.createElement('a'); a.id = 'ext'; a.href = 'https://www.youtube.com/watch?v=abc123DEF45'; a.target = '_blank';
                                        a.rel = 'noopener'; a.textContent = 'yt'; document.body.appendChild(a); }""")
                win.click("#ext")
                check(wait_until(lambda: browsed) == ["https://www.youtube.com/watch?v=abc123DEF45"], "[7-3] 外のサイトはいつものブラウザで開く: %s" % browsed)
                # S-13・S-15(入口 0.42.0): 配信が無いときの空の表示の「新しい案件を始める」(RS8 C3 でリンクからボタンに変わった = 引き出しを開く。窓の中で Edge を新しく起動しない)。
                # 案件の画面へのリンクは、窓の中で普通に押すと同じ窓で移り、Ctrl を押しながらだと入口に頼んで窓で開く(UIKit.win)
                check(wait_js(win, "!!document.getElementById('emptyStudio') && !!document.getElementById('emptyIntake')", 15000),
                      "[S-13] 配信が無いときの空の表示に、次に押すボタン(新しい案件を始める・依頼の受付を設定する)")
                check(win.get_attribute("#emptyStudio", "target") is None and win.get_attribute("#emptyStudio", "href") is None,
                      "[S-15] 新しい案件のボタンはリンクではない(押すと引き出しが開く。窓も移らない)")
                n2 = len(read_lines(edge_log))
                win.click("#emptyStudio")
                check(wait_js(win, "!document.getElementById('newDrawer').hidden", 10000) and len(read_lines(edge_log)) == n2 and not opened,
                      "[S-15] 普通に押すと同じ窓の中で引き出しが開く(Edge を新しく起動しない・タブを増やさない)")
                win.keyboard.press("Escape")
                check(wait_js(win, "document.getElementById('newDrawer').hidden", 5000), "[S-15] Esc で閉じる")
                win.evaluate("""() => { const a = document.createElement('a'); a.id = 'csLink'; a.href = '/cases?c=x'; a.textContent = 'cs'; document.body.appendChild(a); }""")
                win.click("#csLink", modifiers=["Control"])
                got = wait_until(lambda: read_lines(edge_log)[n2:])
                check(got and got[-1][0] == "--app=http://localhost:%d/cases?c=x" % port, "[S-15] 窓の中で案件の画面へのリンクを Ctrl を押しながらだと、窓で開く: %s" % got[-1:])
                check("/cases" not in win.url, "[S-15] Ctrl のときは今の窓は移らない: %s" % win.url)
                n3 = len(read_lines(edge_log))
                win.click("#csLink")
                try:
                    win.wait_for_url(lambda u: "/cases" in u, timeout=15000)
                except Exception:
                    pass
                time.sleep(0.5)
                check("/cases" in win.url and len(read_lines(edge_log)) == n3 and not opened,
                      "[S-15] 普通に押すと同じ窓の中で案件の画面へ移る(Edge を新しく起動しない・タブを増やさない): %s" % win.url)
                # 窓の中の案件の画面: ui-appnav(ホーム / 案件 / 設定)は target=_blank を付けないので、同じ窓の中でその場所へ移るだけ(Edge を新しく起動しない)
                check(wait_js(win, "!!window.UIKit && !!document.querySelector('a[data-ui-appnav-item=\"settings\"]')", 30000), "[7-3] 窓の中の案件の画面")
                n1 = len(read_lines(edge_log))
                win.click('a[data-ui-appnav-item="settings"]')
                try:
                    win.wait_for_url(lambda u: "/settings" in u, timeout=15000)
                except Exception:
                    pass
                time.sleep(0.5)
                check("/settings" in win.url and len(read_lines(edge_log)) == n1 and not opened,
                      "[7-3] ui-appnav の切り替えでは Edge を新しく起動しない(同じ窓の中で移る): %s" % win.url)
                actx.close()
                pg.click("[data-ui-settings]")
                pg.click("#winMode")   # オフに戻す
                check(wait_js(pg, "document.querySelector('#toast').textContent.indexOf('いつものブラウザ') >= 0", 10000) and W.read_mode(srv.window.settings_path) == "browser",
                      "[7-3] オフに戻せる")

                # ---- 7-2 離れた・戻った(案件の画面で。RS8 C4 までスタジオの画面) ----
                st = ctx.new_page()
                st.on("pageerror", lambda e: errors.append(str(e)))
                st.goto(base + "cases")
                check(wait_js(st, "!!window.UIKit && !!UIKit.life", 30000), "[7-2] 案件の画面")
                st.evaluate("""() => { window.__ev = []; UIKit.life.onLeave(r => __ev.push('leave:' + r)); UIKit.life.onReturn(r => __ev.push('back:' + r));
                                       document.hasFocus = () => true; }""")
                st.evaluate("() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('blur')); }")
                time.sleep(0.4)
                check(st.evaluate("__ev") == [], "[7-2] フォーカスが画面の中(埋め込みの YouTube など)なら離れたことにしない: %s" % st.evaluate("__ev"))
                st.evaluate("() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }")
                time.sleep(0.4)
                st.evaluate("() => { window.dispatchEvent(new Event('blur')); }")
                time.sleep(0.4)
                st.evaluate("() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('focus')); }")
                st.evaluate("() => { window.dispatchEvent(new Event('pagehide')); }")
                check(st.evaluate("__ev") == ["leave:blur", "back:focus", "leave:pagehide"],
                      "[7-2] 別の窓へ → 1回だけ離れた、戻った → 1回だけ、閉じる直前 → 離れた: %s" % st.evaluate("__ev"))
                st.evaluate("""() => { __ev.length = 0; window.dispatchEvent(new Event('focus'));
                  const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
                  document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }""")
                time.sleep(0.4)
                st.evaluate("""() => { const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
                  set(true); document.dispatchEvent(new Event('visibilitychange')); document.dispatchEvent(new Event('visibilitychange'));
                  set(false); document.dispatchEvent(new Event('visibilitychange')); delete document.hidden; }""")
                check(st.evaluate("__ev") == ["back:focus", "leave:blur", "leave:hidden", "back:visible"],
                      "[7-2] 隣の窓へ移ったあと最小化・タブの切り替え → もう一度「離れた」(再生の停止などをさせる): %s" % st.evaluate("__ev"))

                # ---- 7-0 画面のエラーの記録(案件の画面と設定の画面。どちらも入口の画面なので tool は portal・page で分かれる) ----
                st.evaluate("() => { setTimeout(() => { throw new Error('e2e-boom-cases'); }, 0); }")
                tx = ctx.new_page()
                tx.goto(base + "settings")
                check(wait_js(tx, "!!window.UIKit && !!document.querySelector('[data-ui-appnav-item]')", 30000), "[7-0] 設定の画面")
                tx.evaluate("() => { Promise.reject(new Error('e2e-reject-settings')); }")
                tx.evaluate("() => { setTimeout(() => { throw new Error('e2e-boom-cases'); }, 0); }")   # 別の画面なら同じ文も記録する
                mine = lambda: [e for e in read_lines(clog) if "e2e-" in e.get("message", "")]
                got = wait_until(lambda: len(mine()) >= 3 and mine(), 10) or mine()
                by = {(e.get("page"), e["kind"]): e for e in got}
                s = by.get(("/cases", "error"))
                check(s and "e2e-boom-cases" in s["message"] and s["tool"] == "portal" and s.get("version"),
                      "[7-0] 案件の画面のエラーが記録された(画面・版・場所つき): %s" % s)
                t = by.get(("/settings", "rejection"))
                check(t and "e2e-reject-settings" in t["message"], "[7-0] 設定の画面の Promise の失敗も: %s" % t)
                check(("/settings", "error") in by, "[7-0] 画面ごとに記録(同じ文でも別の画面なら)")
                st.evaluate("() => { for (let i = 0; i < 3; i++) setTimeout(() => { throw new Error('e2e-boom-cases'); }, 0); }")
                time.sleep(1.0)
                n = len([e for e in read_lines(clog) if e.get("page") == "/cases" and "e2e-boom-cases" in e.get("message", "")])
                check(n == 1, "[7-0] 同じ画面の同じエラーは1回だけ送る: %d 件" % n)
                with urllib.request.urlopen(urllib.request.Request(base + "api/log?tool=client&lines=50", headers={"Host": "127.0.0.1:%d" % port}), timeout=10) as r:
                    lines = json.loads(r.read())["lines"]
                check(any("e2e-reject-settings" in x for x in lines), "[7-0] 入口の /api/log?tool=client で読める")

                # ---- ホームへ戻る(2026-09-27): ホームがほかのタブで開いていれば、案件の画面は移らずにホーム(サーバー)へ「前に出して」と頼む ----
                focused, focus_ok = [], [True]
                srv.window.focus = lambda title: focused.append(title) or focus_ok[0]   # 本物の窓は動かさない(テストを流す PC の画面を奪わない)
                sp = ctx.new_page()
                sp.on("pageerror", lambda e: errors.append(str(e)))
                sp.goto(base + "cases")
                check(wait_js(sp, "!!window.UIKit && !!document.querySelector('%s')" % PORTAL_LINK.replace("'", "\\'"), 30000), "[ホーム] 案件の画面のヘッダーに「ホーム」")
                sp.click(PORTAL_LINK)
                check(wait_until(lambda: focused, 5) == [L.PORTAL_TITLE] and "/cases" in sp.url,
                      "[ホーム] ホームが開いていれば、移らずにホームの窓を前に出すよう頼む(ホームが二つにならない): %s %s" % (focused, sp.url))
                focus_ok[0] = False
                n0 = len(focused)
                sp.click(PORTAL_LINK)
                check(wait_js(sp, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('ほかの窓') >= 0)", 5000) and "/cases" in sp.url
                      and len(focused) > n0, "[ホーム] 前に出せなかったら知らせる(画面はそのまま)")
                pg.close()                                                          # ホームのタブを閉じる → 答えが無いので、その場でホームへ移る
                sp.click(PORTAL_LINK)
                try:
                    sp.wait_for_url(base, timeout=15000)                            # 移っている間は evaluate できないので、URL で待つ
                except Exception:
                    pass
                check(sp.url == base and wait_js(sp, "!!document.getElementById('winBox')", 15000), "[ホーム] ホームが開いていなければ、その場でホームへ移る(今までどおり): %s" % sp.url)

                real = [e for e in errors if "e2e-" not in e]
                check(not real, "画面のエラーなし: %s" % real[:3])
                ctx.close()
            finally:
                browser.close()
    finally:
        if srv is not None:
            srv.shutdown()
            sup.close()
            sup.stop_all()
            sup.unmount_all()
            srv.server_close()
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(events[-30:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
