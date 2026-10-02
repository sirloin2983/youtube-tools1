#!/usr/bin/env python3
"""ui-kit v6(画面の全面見直し .design/ui-overhaul/ の段階1)の見本(styleguide.html)の動作確認(Playwright・chromium・headless)。

    python ui-kit/tests/e2e_styleguide.py

ui-kit/ をそのまま python の http.server で1つのポートに乗せ、styleguide.html を開いて確かめる:
コンソール・画面のエラーが無いこと / 既定のテーマは明るい(localStorage が空のとき。v6 で OS の設定から変わった) / テーマの切り替え /
引き出し(UIKit.drawer: フォーカスの閉じ込め・Esc で閉じてフォーカスが戻る) / 確認ダイアログ(UIKit.dialog.confirm: ボタンと Esc) /
通知(UIKit.toast: 失敗は role=alert) / 下の帯(UIKit.keybar: set/flash・ytt:keybar=0 で消える) /
共通の再生キー(UIKit.keys.playback: Space/J/K/L/矢印/,/./I/O・入力欄では無視) / アイコン(UIKit.icon: 一覧すべて) /
設定の引き出し(UIKit.settings: 文字の大きさが html[data-fs] に効いて保存される) /
版の帯(UIKit.restart。v10: 単体では案内だけ・合言葉があれば「起動し直す」→ 断られた理由・ping を待って読み込み直す・戻らなければ案内)/
時刻の欄(UIKit.timebox。v11: 数字だけで 時 → 分 → 秒・← →・↑ ↓・BackSpace・Delete・貼り付け・0.1 秒・YouTube の URL は指定した欄だけ・上限・使えない欄)。
"""
import functools
import json
import http.server
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import sys
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ui-kit/(styleguide.html がある場所)

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


def check_restart(browser, base, check):
    """版の帯(UIKit.restart。v10・段9 9-3): 単体では案内だけ / 合言葉があれば「起動し直す」→ 断られたら理由 → 頼めたら ping を待って読み込み直す / 戻らなければ案内"""
    st = {"calls": [], "mode": "refuse", "ping": 0, "ping_ok_after": 1}

    def on_restart(route):
        st["calls"].append(route.request.headers.get("x-ytt-token"))
        if st["mode"] == "refuse":
            route.fulfill(status=409, content_type="application/json",
                          body=json.dumps({"error": "busy", "message": "実行中の処理があります(文字起こし)。終わってから起動し直してください"}, ensure_ascii=False))
        else:
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    def on_ping(route):
        st["ping"] += 1
        if st["ping"] <= st["ping_ok_after"]:
            route.abort()   # 古い入口が終わって、新しい入口がまだ待ち受けていない間
        else:
            route.fulfill(status=200, content_type="application/json", body='{"app": "x", "version": "0.2.0"}')

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/api/ytt/restart-self", on_restart)
        pg.route("**/api/ping", on_ping)
        pg.goto(base + "styleguide.html")
        pg.wait_for_selector("#btnRestartBand")
        band = "#restartBandDemo"

        pg.click("#btnRestartBand")
        txt = pg.inner_text(band)
        check(pg.evaluate("!document.getElementById('restartBandDemo').hidden") and "版が違います" in txt and "v0.2.0" in txt and "v0.1.0" in txt,
              "版の帯: 画面とサーバーの版を出す")
        check("黒い画面を閉じて" in txt and not pg.query_selector(band + " .ui-restart-btn"),
              "単体で開いた画面(合言葉なし)は今までの案内だけで、「起動し直す」は出さない")
        check(pg.evaluate("UIKit.restart.check(document.createElement('div'), '1.0', '1.0')") is False, "check: 版が同じなら何もしない(false)")

        # ホームから開いた画面(合言葉あり)
        pg.evaluate("const m = document.createElement('meta'); m.name = 'ytt-token'; m.content = 'tok-1'; document.head.appendChild(m);"
                    "window.__marker = 1; window.__texts = [];"
                    "new MutationObserver(() => window.__texts.push(document.getElementById('restartBandDemo').textContent))"
                    "  .observe(document.getElementById('restartBandDemo'), { childList: true, subtree: true, characterData: true });"
                    "window.__restartDemoOpts = { interval: 150, timeout: 6000, reload: () => { window.__reloaded = (window.__reloaded || 0) + 1; } };")
        pg.click("#btnRestartBand")
        check(pg.evaluate("UIKit.restart.available()") is True and pg.inner_text(band + " .ui-restart-btn") == "起動し直す",
              "合言葉があれば「起動し直す」のボタンが出る")

        pg.click(band + " .ui-restart-btn")
        check(wait_js(pg, "document.getElementById('restartBandDemo').getAttribute('data-ui-restart') === 'refused'"), "断られた(409)ら refused")
        check("実行中の処理があります(文字起こし)" in pg.inner_text(band), "断られた理由を帯に出す")
        check(pg.evaluate("!document.querySelector('#restartBandDemo .ui-restart-btn').disabled"), "断られたら、もう一度押せる")
        check(st["calls"] == ["tok-1"], "POST api/ytt/restart-self に合言葉(X-YTT-Token)を付ける: %s" % st["calls"])

        st["mode"], st["ping"] = "ok", 0
        pg.click(band + " .ui-restart-btn")
        check(wait_js(pg, "window.__reloaded === 1"), "頼めたら ping が戻るのを待って読み込み直す")
        check(pg.evaluate("window.__texts.some(t => t.includes('起動し直しています'))"), "待っている間は「起動し直しています…」")
        check(st["ping"] >= 2 and pg.get_attribute(band, "data-ui-restart") == "done", "一度答えなくなってから答えたら戻った扱い(ping %d 回)" % st["ping"])
        check(pg.evaluate("document.querySelector('#restartBandDemo .ui-restart-btn').disabled"), "起動し直している間はボタンを押せない")

        # 戻らなかった(ping がずっと答えない)
        st["ping"], st["ping_ok_after"] = 0, 10 ** 6
        pg.evaluate("window.__restartDemoOpts = { interval: 150, timeout: 700, reload: () => { window.__reloaded = 99; } }")
        pg.click("#btnRestartBand")
        pg.click(band + " .ui-restart-btn")
        check(wait_js(pg, "document.getElementById('restartBandDemo').getAttribute('data-ui-restart') === 'timeout'"), "決めた時間で戻らなければ timeout")
        check("start.bat" in pg.inner_text(band) and pg.evaluate("document.querySelector('#restartBandDemo .ui-restart-btn').hidden")
              and pg.evaluate("window.__reloaded") == 1, "戻らなければ start.bat の案内を出し、ボタンを隠す(読み込み直さない)")

        # 既定(location.reload)で本当に読み込み直す
        st["ping"], st["ping_ok_after"] = 0, 1
        pg.evaluate("window.__restartDemoOpts = { interval: 150, timeout: 6000 }")
        pg.click("#btnRestartBand")
        with pg.expect_navigation(timeout=10000):
            pg.click(band + " .ui-restart-btn")
        pg.wait_for_selector("#btnRestartBand")
        check(pg.evaluate("window.__marker") is None, "既定は location.reload で読み込み直す")
        check(not errs, "画面のエラーなし(版の帯): %s" % errs[:5])
    finally:
        ctx.close()


def check_timebox(pg, check):
    """時刻の欄(UIKit.timebox。v11): 本物のキー入力で確かめる。貼り付けは paste イベント(クリップボードは使わない)"""
    def text(sel):
        return pg.evaluate("s => document.querySelector(s).textContent", sel)

    def value(sel):
        return pg.evaluate("s => UIKit.timebox.get(document.querySelector(s))", sel)

    def paste(sel, s):
        pg.evaluate("""([sel, s]) => { const el = document.querySelector(sel); el.focus(); const dt = new DataTransfer(); dt.setData('text/plain', s);
            el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); }""", [sel, s])

    check(pg.evaluate("UIKit.version") == 11, "UIKit.version は 11")
    check((text("#tbStart"), value("#tbStart")) == ("-:--:--", None), "入っていない欄は -:--:--(値は null): %s" % text("#tbStart"))
    pg.focus("#tbStart")
    check(text("#tbStart") == "0:00:00" and pg.evaluate("document.querySelector('#tbStart .ui-time-seg.on').dataset.seg") == "0", "欄に入ると 0:00:00 で「時」が選ばれる")
    pg.keyboard.type("12345")
    check((text("#tbStart"), value("#tbStart")) == ("1:23:45", 5025), "12345 → 1:23:45(時 1 桁 → 分 2 桁 → 秒 2 桁): %s" % text("#tbStart"))
    check(pg.evaluate("window.__tbLast") == {"id": "tbStart", "value": 5025}, "変わるたびに ui-time(detail.value)")
    pg.keyboard.type(":a ")
    check(text("#tbStart") == "1:23:45", "「:」や文字は入らない")
    pg.keyboard.press("ArrowLeft")
    pg.keyboard.press("ArrowUp")
    check(text("#tbStart") == "1:24:45", "← で分を選んで ↑")
    pg.keyboard.press("Shift+ArrowDown")
    check(text("#tbStart") == "1:14:45", "Shift+↓ は 10 ずつ")
    pg.keyboard.press("Backspace")
    check(text("#tbStart") == "1:00:45", "BackSpace は選んだ所を 0 に")
    pg.keyboard.type("78")
    check(text("#tbStart") == "1:07:08", "分・秒で 6〜9 を最初に打ったら1桁で次へ: %s" % text("#tbStart"))
    pg.keyboard.press("ArrowDown")
    for _ in range(8):
        pg.keyboard.press("ArrowDown")
    check(text("#tbStart") == "1:06:59", "↓ で繰り下がる: %s" % text("#tbStart"))
    check(pg.evaluate("document.getElementById('fakeTime').textContent") == "0.00", "欄のキーは画面の再生キーに渡らない(矢印で 1 秒など)")
    pg.click("#tbStart .ui-time-seg[data-seg='0']")
    pg.keyboard.type("0")
    check(text("#tbStart") == "0:06:59" and pg.evaluate("document.querySelector('#tbStart .ui-time-seg.on').dataset.seg") == "1", "クリックで「時」を選んで打ち直す → 分へ進む")

    # 終了: +30秒・開始より前は使う画面が誤りにする
    pg.click("#tbPlus30")
    check((text("#tbEnd"), text("#tbLen")) == ("0:07:29", "長さ 0:30"), "set で入れる(+30秒): %s %s" % (text("#tbEnd"), text("#tbLen")))
    pg.focus("#tbEnd")
    pg.keyboard.type("00100")
    check(pg.get_attribute("#tbEnd", "aria-invalid") == "true" and "終了が開始より前" in text("#tbMsg"), "終了 ≤ 開始は、画面が aria-invalid と理由を出す")
    pg.keyboard.press("Delete")
    check((text("#tbEnd"), value("#tbEnd"), pg.get_attribute("#tbEnd", "aria-invalid")) == ("0:00:00", None, None), "Delete で空に(フォーカス中は 0:00:00)")
    pg.keyboard.press("Tab")
    check(text("#tbEnd") == "-:--:--", "離れたら -:--:--")

    # 貼り付け: 1:23:45 / 83:45 / 1h23m45s。URL は「YouTube の URL も」の欄だけ
    for src, want in (("1:23:45", 5025), (" 83:45 ", 5025), ("1h23m45s", 5025), ("2m", 120)):
        paste("#tbEnd", src)
        check(value("#tbEnd") == want, "貼り付け %s → %s" % (src, want))
    pg.evaluate("window.__tbReject = null")
    paste("#tbEnd", "https://youtu.be/dQw4w9WgXcQ?t=7000")
    check(value("#tbEnd") == 120 and (pg.evaluate("window.__tbReject") or {}).get("id") == "tbEnd", "ふつうの欄は YouTube の URL を読まない(ui-time-reject)")
    paste("#tbEnd", "5025")
    check(value("#tbEnd") == 120, "数字だけの貼り付けは読まない(秒か 時分秒 か決められない)")
    paste("#tbYoutube", "https://youtu.be/dQw4w9WgXcQ?t=5025")
    check((text("#tbYoutube"), value("#tbYoutube")) == ("1:23:45", 5025), "YouTube の URL も の欄は t= を読む")
    paste("#tbYoutube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1h2m3s")
    check(value("#tbYoutube") == 3723, "t=1h2m3s")
    paste("#tbYoutube", "https://youtu.be/dQw4w9WgXcQ")
    check(value("#tbYoutube") == 3723 and "YouTube" in (pg.evaluate("window.__tbReject") or {}).get("reason", ""), "時刻の無い URL は読まない(理由に YouTube の案内)")

    # 0.1 秒・上限・使えない欄・コピー
    check((text("#tbTenths"), value("#tbTenths")) == ("0:01:23.5", 83.5), "0.1 秒までの欄(data-ui-time=83.5): %s" % text("#tbTenths"))
    pg.focus("#tbTenths")
    pg.keyboard.type("012345")
    pg.keyboard.type("6")
    check((text("#tbTenths"), value("#tbTenths")) == ("0:12:34.6", 754.6), "0.1 秒の桁まで進む・最後の桁は打ち直し: %s" % text("#tbTenths"))
    pg.keyboard.press("ArrowUp")
    check(value("#tbTenths") == 754.7, "0.1 秒の桁で ↑ は 0.1 秒")
    paste("#tbTenths", "1:23.5")
    check(value("#tbTenths") == 83.5, "貼り付け 1:23.5")
    pg.focus("#tbMax")
    pg.keyboard.type("15959")
    check((text("#tbMax"), value("#tbMax")) == ("0:10:00", 600), "上限(data-ui-time-max=600)を超えない: %s" % text("#tbMax"))
    pg.click("#tbOff", force=True)
    pg.keyboard.type("9")
    check((text("#tbOff"), value("#tbOff")) == ("1:23:45", 5025), "使えない欄(aria-disabled)は変わらない")
    check(pg.evaluate("UIKit.keys.isTyping(document.getElementById('tbStart'))") is True, "UIKit.keys.isTyping は時刻の欄を入力中と数える")
    check(pg.evaluate("[UIKit.timebox.format(5025), UIKit.timebox.format(83.5, true), UIKit.timebox.parse('1:23:45'), UIKit.timebox.parse('x'), UIKit.timebox.parse('https://youtu.be/a?t=9'), UIKit.timebox.parse('https://youtu.be/a?t=9', {youtube: true})]")
          == ["1:23:45", "0:01:23.5", 5025, None, None, 9], "format / parse")
    made = pg.evaluate("(() => { const el = UIKit.timebox.create({value: 61, label: '作った欄'}); document.body.appendChild(el); const r = [el.textContent, el.getAttribute('aria-label'), el.getAttribute('role'), UIKit.timebox.get(el)]; el.remove(); return r; })()")
    check(made == ["0:01:01", "作った欄", "spinbutton", 61], "create(あとから作る): %s" % made)


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

                # ---- v11: 時刻の欄(UIKit.timebox) ----
                check_timebox(pg, check)

                check(not errors, "コンソール・画面のエラーなし: %s" % errors[:5])
                ctx.close()

                # ---- v10: 版の帯(UIKit.restart)。入口の API は偽物(page.route)。409 などはコンソールに出るので、別の窓(context)で確かめる ----
                check_restart(browser, base, check)
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        th.join(timeout=5)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
