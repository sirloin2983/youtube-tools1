#!/usr/bin/env python3
"""ui-kit v6(画面の全面見直し .design/ui-overhaul/ の段階1)の見本(styleguide.html)の動作確認(Playwright・chromium・headless)。

    python ui-kit/e2e_styleguide.py

ui-kit/ をそのまま python の http.server で1つのポートに乗せ、styleguide.html を開いて確かめる:
コンソール・画面のエラーが無いこと / 既定のテーマは明るい(localStorage が空のとき。v6 で OS の設定から変わった) / テーマの切り替え /
引き出し(UIKit.drawer: フォーカスの閉じ込め・Esc で閉じてフォーカスが戻る) / 確認ダイアログ(UIKit.dialog.confirm: ボタンと Esc) /
通知(UIKit.toast: 失敗は role=alert) / 下の帯(UIKit.keybar: set/flash・ytt:keybar=0 で消える) /
共通の再生キー(UIKit.keys.playback: Space/J/K/L/矢印/,/./I/O・入力欄では無視) / アイコン(UIKit.icon: 一覧すべて) /
設定の引き出し(UIKit.settings: 文字の大きさが html[data-fs] に効いて保存される)。
"""
import functools
import http.server
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import sys
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))

ICON_NAMES = [
    "play", "pause", "back", "forward", "frame-prev", "frame-next", "scissors", "split", "merge", "trash", "plus", "minus", "more",
    "gear", "menu", "close", "chevron-down", "chevron-right", "chevron-left", "folder", "download", "undo", "redo", "check", "alert", "info",
    "search", "home", "film", "text", "mic", "flag", "keyboard", "zoom-in", "zoom-out", "refresh", "external", "copy", "sun", "moon",
    "mark-in", "mark-out", "clock", "list", "layers", "wave", "user",
]


def start_static_server():
    handler_cls = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, th


def wait_js(page, expr, timeout=8000):
    try:
        page.wait_for_function(expr, timeout=timeout)
        return True
    except Exception:
        return False


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    httpd, th = start_static_server()
    base = "http://127.0.0.1:%d/" % httpd.server_address[1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                errors = []
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("console", lambda m: (m.type == "error" and "favicon" not in m.text) and errors.append(m.text))
                pg.goto(base + "styleguide.html")
                pg.wait_for_selector("#iconGrid .ui-icon svg", timeout=10000)

                # ---- 既定のテーマ(v6: 保存が無いときは明るい) ----
                check(pg.evaluate("localStorage.getItem('ytt:theme')") is None, "見本を開いた直後、localStorage は空")
                check(pg.get_attribute("html", "data-theme") == "light", "保存が無いときの既定は明るい(以前は OS の設定)")

                # ---- テーマの切り替え ----
                pg.click("[data-theme-toggle]")
                check(pg.get_attribute("html", "data-theme") == "dark", "切り替えボタンでダークになる")
                check(pg.evaluate("localStorage.getItem('ytt:theme')") == "dark", "選んだ値が保存される")
                pg.click("[data-theme-toggle]")
                check(pg.get_attribute("html", "data-theme") == "light", "もう一度でライトに戻る")

                # ---- 引き出し(UIKit.drawer) ----
                pg.click("#btnDrawerModal")
                check(pg.evaluate("!document.getElementById('drawerModalDemo').hidden"), "引き出しが開く")
                check(pg.evaluate("document.querySelector('header.ui-header').inert === true"), "裏(ヘッダー)が inert になる")
                check(wait_js(pg, "document.getElementById('drawerModalDemo').contains(document.activeElement)"), "開いたらフォーカスが中に入る")
                for _ in range(8):
                    pg.keyboard.press("Tab")
                check(pg.evaluate("document.getElementById('drawerModalDemo').contains(document.activeElement)"),
                      "Tab を繰り返してもフォーカスが外へ出ない(裏が inert)")
                pg.keyboard.press("Escape")
                check(pg.evaluate("document.getElementById('drawerModalDemo').hidden"), "Esc で閉じる")
                check(pg.evaluate("document.activeElement && document.activeElement.id") == "btnDrawerModal",
                      "閉じたら開いたボタン(opener)へフォーカスが戻る")
                check(pg.evaluate("document.querySelector('header.ui-header').inert") is False, "裏の inert が解ける")

                # ---- ダイアログ(UIKit.dialog.confirm) ----
                pg.click("#btnConfirm")
                pg.wait_for_selector("dialog.ui-dialog[open]")
                pg.click("dialog.ui-dialog[open] .ui-dlg-actions button.ghost")   # キャンセル
                check(wait_js(pg, "!document.querySelector('dialog.ui-dialog[open]')"), "キャンセルのボタンで閉じる")
                check(wait_js(pg, "[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('キャンセルしました'))"),
                      "confirm が false で解決された(案内から確認)")

                pg.click("#btnConfirm")
                pg.wait_for_selector("dialog.ui-dialog[open]")
                pg.keyboard.press("Escape")
                check(wait_js(pg, "!document.querySelector('dialog.ui-dialog[open]')"), "Esc でも閉じる")
                check(wait_js(pg, "[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('キャンセルしました'))"),
                      "Esc も confirm が false で解決される")

                pg.click("#btnConfirm")
                pg.wait_for_selector("dialog.ui-dialog[open]")
                pg.click("dialog.ui-dialog[open] .ui-dlg-actions button.danger")   # 削除する(OK)
                check(wait_js(pg, "[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('削除しました'))"),
                      "OK のボタンで confirm が true で解決される")

                # ---- 通知(UIKit.toast) ----
                pg.click("#btnToastErr")
                check(pg.evaluate("!!document.querySelector('#toast .ui-toast.err[role=alert]')"), "失敗のトーストは role=alert")
                check("失敗しました" in pg.inner_text("#toast"), "#toast のテキストに本文が入る(e2e が読む想定と一致)")
                # v7(気が利く画面へ 段1): ms: 0 は消えない・ボタン1つ・閉じる
                pg.evaluate("window.__acted = 0; window.__t = UIKit.toast('ずっと出る知らせ', { ms: 0, action: { label: 'やる', fn: () => { window.__acted++; } } })")
                pg.wait_for_timeout(3000)
                check(pg.evaluate("[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('ずっと出る知らせ'))"),
                      "ms: 0 の知らせは 3 秒たっても消えない(以前は既定の 2.5 秒に戻っていた)")
                pg.evaluate("[...document.querySelectorAll('#toast .ui-toast')].find(t => t.textContent.includes('ずっと出る知らせ')).querySelector('.ui-toast-msg').click()")
                check(pg.evaluate("[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('ずっと出る知らせ'))"),
                      "ボタンのある知らせは、本文を押しても閉じない")
                pg.click("#toast .ui-toast-act")
                check(pg.evaluate("window.__acted") == 1 and not pg.evaluate("[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('ずっと出る知らせ'))"),
                      "ボタンを押すと fn を呼んで閉じる")
                pg.evaluate("UIKit.toast('閉じる知らせ', { ms: 0 })")
                pg.click("#toast .ui-toast:last-child .ui-toast-x")
                check(not pg.evaluate("[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('閉じる知らせ'))"), "× で閉じる")
                # 二度押しの確認(UIKit.confirmTwice)
                pg.evaluate("window.__runs = 0; const b = document.createElement('button'); b.id = 'twice'; b.className = 'btn'; b.textContent = '消す'; "
                            "b.onclick = () => UIKit.confirmTwice(b, () => { window.__runs++; }, 'もう一度押すと消します'); document.body.appendChild(b)")
                pg.click("#twice")
                check(pg.inner_text("#twice") == "もう一度押すと消します" and pg.evaluate("window.__runs") == 0, "1回目は文字が変わるだけ")
                pg.click("#twice")
                check(pg.evaluate("window.__runs") == 1 and pg.inner_text("#twice") == "消す", "2回目で実行して元に戻る")

                # ---- 下の帯(UIKit.keybar) ----
                pg.click("#btnKeybarSet")
                check(pg.evaluate("!document.querySelector('.ui-keybar').hidden"), "keybar.set で帯が出る")
                check(pg.evaluate("document.documentElement.hasAttribute('data-keybar')"), "表示中は html[data-keybar]")
                pg.click("#btnKeybarFlash")
                check(wait_js(pg, "!!document.querySelector('.ui-keybar-item.flash')"), "flash で光る(class=flash)")
                pg.evaluate("localStorage.setItem('ytt:keybar', '0')")
                pg.click("#btnKeybarSet")
                check(pg.evaluate("document.querySelector('.ui-keybar').hidden"), "ytt:keybar=0 だと帯が出ない")
                check(pg.evaluate("!document.documentElement.hasAttribute('data-keybar')"), "html[data-keybar] も外れる")
                pg.evaluate("localStorage.removeItem('ytt:keybar')")

                # ---- 共通の再生キー(UIKit.keys.playback) ----
                pg.click("#btnKeybarClear")
                pg.click("#keysHelpBox")   # 直前のダイアログ操作でボタンにあるフォーカスを外す
                pg.keyboard.press("Space")
                check(wait_js(pg, "document.getElementById('fakeRate').textContent === '1.0'"), "Space で再生(rate=1)")
                pg.keyboard.press("l")
                check(wait_js(pg, "document.getElementById('fakeRate').textContent === '1.5'"), "L で 1.5 倍")
                pg.keyboard.press("l")
                check(wait_js(pg, "document.getElementById('fakeRate').textContent === '2.0'"), "もう一度 L で 2 倍")
                pg.keyboard.press("k")
                check(wait_js(pg, "document.getElementById('fakeRate').textContent === '1.0'"), "K で止めて速さが1倍に戻る")
                pg.keyboard.press("ArrowRight")
                check(wait_js(pg, "document.getElementById('fakeTime').textContent === '1.00'"), "→ で1秒進む")
                pg.keyboard.down("Shift")
                pg.keyboard.press("ArrowRight")
                pg.keyboard.up("Shift")
                check(wait_js(pg, "document.getElementById('fakeTime').textContent === '6.00'"), "Shift+→ で5秒進む")
                pg.keyboard.press("j")
                check(wait_js(pg, "document.getElementById('fakeTime').textContent === '5.00'"), "J で1秒戻る")
                pg.keyboard.press(",")
                check(wait_js(pg, "document.getElementById('fakeTime').textContent === '%.2f'" % (5.0 - 1.0 / 30)),
                      "コマ送り(,)。fps 既定30")
                pg.keyboard.press("i")
                check(wait_js(pg, "[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('始まりの印'))"), "I で onIn")
                pg.keyboard.press("o")
                check(wait_js(pg, "[...document.querySelectorAll('#toast .ui-toast')].some(t => t.textContent.includes('終わりの印'))"), "O で onOut")

                pg.click("#keysDemoFocus")
                before = pg.inner_text("#fakeTime")
                pg.keyboard.press("Space")
                pg.keyboard.press("j")
                after = pg.inner_text("#fakeTime")
                check(before == after, "入力欄にフォーカス中はキーを無視する: %s -> %s" % (before, after))
                pg.keyboard.press("Escape")

                # ---- アイコン(UIKit.icon。一覧のすべての名前) ----
                res = pg.evaluate("(names) => names.map((n) => UIKit.icon(n))", ICON_NAMES)

                def no_shape(svg):
                    return "<path" not in svg and "<circle" not in svg and "<rect" not in svg

                bad = [n for n, svg in zip(ICON_NAMES, res) if not svg.startswith("<svg") or no_shape(svg)]
                check(not bad, "UIKit.icon がすべての名前で中身のある svg を返す: %s" % bad)

                # ---- 設定の引き出し(UIKit.settings。文字の大きさ) ----
                pg.click("#btnSettings")
                pg.wait_for_selector("#uiSettingsDrawer:not([hidden])")
                selects = pg.query_selector_all("#uiSettingsDrawer select")
                check(len(selects) >= 2, "設定に select が2つ(テーマ・文字の大きさ)以上ある: %d" % len(selects))
                selects[1].select_option("lg")
                check(wait_js(pg, "document.documentElement.getAttribute('data-fs') === 'lg'"), "文字の大きさ「大きい」が html[data-fs] に効く")
                check(pg.evaluate("localStorage.getItem('ytt:fs')") == "lg", "localStorage['ytt:fs'] に保存される")
                pg.reload()
                pg.wait_for_selector("#iconGrid .ui-icon svg", timeout=10000)
                check(pg.evaluate("document.documentElement.getAttribute('data-fs') === 'lg'"), "読み込み直しても保持される(永続化)")

                check(not errors, "コンソール・画面のエラーなし: %s" % errors[:5])
                ctx.close()
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        th.join(timeout=5)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
