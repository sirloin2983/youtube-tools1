#!/usr/bin/env python3
"""「編集」E2 画面の骨組みの確認(docs/design/edit-tool-design.md の 3 と 7): 3つのタブ・Alt+1/2/3・URL の #tx/#cut/#pack・
題名の行の札・カット/パックのタブでの左のメニューの細い帯・文字起こしせずに開く・行の無い文書・狭い画面。

    python e2e_edit_tabs.py
"""
import json
import os
import urllib.parse
import sys

from playwright.sync_api import sync_playwright

from e2e_edit_common import Checks, Server, make_video, open_doc, wait_js


def main():
    check = Checks()
    srv = Server()
    errors = []
    try:
        v1 = make_video(os.path.join(srv.media, "一本目.webm"), sec=12)
        v2 = make_video(os.path.join(srv.media, "二本目.webm"), sec=8)
        v3 = make_video(os.path.join(srv.media, "文字なし.webm"), sec=6)
        srv.transcribe(v1, "一本目")
        srv.transcribe(v2, "二本目")
        n_jobs = len(srv.get("/api/jobs")["jobs"])

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(srv.base)
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")

            # ---- ヘッダー: ui-appnav(ホーム/スタジオ/編集)の「編集」・ブラウザのタブの題名・3つのタブ
            check(pg.title() == "編集", "ブラウザのタブの題名は「編集」")
            check(pg.inner_text('[data-ui-appnav-item="transcribe"]') == "編集" and pg.get_attribute('[data-ui-appnav-item="transcribe"]', "aria-current") == "page",
                  "ヘッダー左の ui-appnav に「編集」(いま開いている画面)")
            tabs = pg.locator("[data-edtab]")
            check(tabs.count() == 3 and ["".join(t.split()) for t in pg.locator("[data-edtab]").all_inner_texts()] == ["1文字起こし", "2カット", "3パック"],
                  "ヘッダーに 1 文字起こし / 2 カット / 3 パック のタブ: %s" % pg.locator("[data-edtab]").all_inner_texts())
            check(pg.get_attribute("[data-edtab=tx]", "aria-selected") == "true" and pg.evaluate("location.hash") == "", "最初は 1 文字起こし(URL に # は付けない)")

            # ---- 文書を開く・題名の行
            open_doc(pg, "一本目")
            wait_js(pg, "!document.querySelector('#pillProof').hidden")
            check(pg.is_visible("#docBar") and pg.input_value("#docTitle") == "一本目", "題名の行に題名(直せる入力欄)")
            check(pg.inner_text("#pillProof") == "校正 0 / 3行", "札「校正 n / m行」: " + pg.inner_text("#pillProof"))
            check("残す 1区間" in pg.inner_text("#pillCut") and "カット後 約0:12.00" in pg.inner_text("#pillCut"), "札「残す n区間 ・ カット後」(計算の前は約): " + pg.inner_text("#pillCut"))
            check("0:12" in pg.inner_text("#docMeta"), "題名の行に長さ: " + pg.inner_text("#docMeta"))
            check(pg.is_visible("#saveState") or pg.get_attribute("#saveState", "role") == "status", "保存の状態はヘッダーに")

            # ---- B-7: 1440px で文書を開いているとき、メニュー(履歴)は本文の上に重ねて開く(列を取らない = 字幕の行が細くならない)
            if "menu-closed" not in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            w_closed = pg.evaluate("document.querySelector('#segs').clientWidth")
            pg.click("#btnMenu")
            wait_js(pg, "!document.querySelector('.app').classList.contains('menu-closed')")
            pos = pg.evaluate("getComputedStyle(document.querySelector('#menuPanel')).position")
            w_open = pg.evaluate("document.querySelector('#segs').clientWidth")
            check(pos == "fixed" and w_open == w_closed, "1440px: メニューを開いても字幕の一覧の幅は変わらない(重ねて開く): %s %s→%s" % (pos, w_closed, w_open))
            check(pg.is_visible("#menuScrim"), "重ねて開いている間は後ろに暗い幕")
            pg.click("[data-side-tab=files]")
            pg.locator("#txList .txi").filter(has_text="一本目").first.locator(".t").click()
            wait_js(pg, "document.querySelector('.app').classList.contains('menu-closed')", 5000)
            check(True, "履歴から文書を選ぶと、重ねたメニューは閉じる")

            # ---- A-1: 一覧の上の「…」の選択肢が画面の外に出ない(右端にあるので、左へ開き直す)
            for w in (1440, 1280, 1024):
                pg.set_viewport_size({"width": w, "height": 900})
                pg.click("#btnSpk")
                box = pg.locator("#jumpMenu .ui-pop-body").bounding_box()
                check(bool(box) and box["x"] >= 0 and box["x"] + box["width"] <= w, "幅 %dpx:「…」の選択肢が画面の中に収まる: %s" % (w, box))
                pg.keyboard.press("Escape")
            pg.set_viewport_size({"width": 1440, "height": 900})

            # ---- 行の右クリックのメニュー(段2): .seg は content-visibility:auto なので、メニュー(position:fixed)は
            # document.body の直下に置く(.seg の中に置くと、画面の外にはみ出す前に切り取られる)。選ぶと閉じて、行に反映される
            row0 = pg.locator("#segs .seg").nth(0)
            row0.locator(".play").click(button="right")
            menu = pg.locator(".tt-ctxmenu")
            check(menu.count() == 1 and menu.get_attribute("role") == "menu", "行を右クリックするとメニューが出る")
            mbox, vp = menu.bounding_box(), pg.viewport_size
            check(bool(mbox) and mbox["x"] >= 0 and mbox["y"] >= 0 and mbox["x"] + mbox["width"] <= vp["width"] and mbox["y"] + mbox["height"] <= vp["height"],
                  "メニューは画面の中に収まる(content-visibility の親に切り取られない): %s / %s" % (mbox, vp))
            menu.locator('[data-act="proof"]').click()
            check(menu.count() == 0, "メニューの項目を選ぶと閉じる")
            check("proofed" in (row0.get_attribute("class") or ""), "選んだ操作(校正済みにする)が行に反映される")
            # B-3: メニューを開いている間の ↓ ↑ はメニューの中の移動(裏の行は動かない)。Enter で選ぶ・Esc で閉じる
            row0.locator(".play").click(button="right")
            nav0 = pg.evaluate("document.querySelector('#segs .seg.nav').dataset.i")
            pg.keyboard.press("ArrowDown"); pg.keyboard.press("s"); pg.keyboard.press("ArrowDown")
            check(pg.evaluate("document.querySelector('#segs .seg.nav').dataset.i") == nav0, "メニューを開いている間は ↓・S で裏の行が動かない(B-3)")
            check(pg.evaluate("document.activeElement.dataset.act") == "split", "↓ でメニューの中の項目を移る(3つ目 = 分割): %s" % pg.evaluate("document.activeElement.dataset.act"))
            pg.keyboard.press("ArrowUp"); pg.keyboard.press("ArrowUp")
            check(pg.evaluate("document.activeElement.dataset.act") == "proof", "↑ で戻る")
            pg.keyboard.press("Enter")
            check(menu.count() == 0 and "proofed" not in (row0.get_attribute("class") or ""), "Enter で選ぶと、右クリックした行に効く(校正済みを外す)")
            row0.locator(".play").click(button="right")
            pg.keyboard.press("Escape")
            check(menu.count() == 0, "Esc でメニューを閉じる")
            menu_row = row0
            menu_row.locator(".play").click(button="right"); menu.locator('[data-act="proof"]').click()   # 下の確かめのため、もう一度「校正済み」に戻す
            # B-9(段1): 文字の欄の上は、普通の右クリックはブラウザ既定(コピー・貼り付け)、Shift+右クリックで行のメニュー
            ta0 = row0.locator("textarea")
            ta0.click(button="right")
            check(menu.count() == 0, "文字の欄の上の普通の右クリックでは行のメニューを出さない(ブラウザ既定のまま)")
            ta0.click(button="right", modifiers=["Shift"])
            check(menu.count() == 1, "文字の欄の上で Shift+右クリックすると行のメニューが出る")
            menu.locator('[data-act="proof"]').click()
            check(menu.count() == 0 and "proofed" not in (row0.get_attribute("class") or ""), "Shift+右クリックのメニューの「校正済みを外す」が行に効く")
            ta0.click(button="right", modifiers=["Shift"])
            menu.locator('[data-act="proof"]').click()
            check("proofed" in (row0.get_attribute("class") or ""), "もう一度で校正済みに戻る")
            # キーボード(Shift+F10・アプリケーションキー)から開いたとき(位置が 0,0)は、欄の下に出す
            pg.evaluate("""() => { const t = document.querySelector('#segs .seg textarea');
                t.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, shiftKey: true, clientX: 0, clientY: 0 })); }""")
            tbox, mbox = ta0.bounding_box(), menu.bounding_box()
            check(menu.count() == 1 and bool(mbox) and abs(mbox["y"] - (tbox["y"] + tbox["height"] + 2)) < 3 and mbox["x"] > tbox["x"],
                  "キーボードから開いたときは欄の下に出る(左上の隅に出ない): %s / %s" % (mbox, tbox))
            pg.keyboard.press("Escape")
            check(menu.count() == 0, "(Esc で閉じる)")
            # 日本語の変換中は出さない(メニューへフォーカスが移ると変換中の文字が確定するため)
            pg.evaluate("document.querySelector('#segs .seg textarea').dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))")
            ta0.click(button="right", modifiers=["Shift"])
            check(menu.count() == 0, "変換中の Shift+右クリックでは行のメニューを出さない")
            pg.evaluate("document.querySelector('#segs .seg textarea').dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }))")
            ta0.click(button="right", modifiers=["Shift"])
            check(menu.count() == 1, "変換が終われば出る")
            pg.keyboard.press("Escape")
            check("proofed" in (row0.get_attribute("class") or ""), "(下の確かめのため、行0は校正済みのまま)")

            # ---- ⚙ 設定の引き出しが開いている間は、文書を操作するキーが効かない(item 6。上の右クリックで行0が「今の行」になっている)
            nav_before = pg.evaluate("document.querySelector('#segs .seg.nav').dataset.i")
            pg.click("[data-ui-settings]")
            wait_js(pg, "!document.querySelector('#uiSettingsDrawer').hidden")
            pg.keyboard.press("ArrowDown")
            pg.wait_for_timeout(150)
            check(pg.evaluate("document.querySelector('#segs .seg.nav').dataset.i") == nav_before, "⚙ 設定の引き出しが開いている間は ↓ で行が動かない")
            pg.keyboard.press("Alt+2")   # 監査01(段1): ⚙ 設定を開いている間は Alt+数字 でタブを変えない
            pg.wait_for_timeout(150)
            check(pg.get_attribute("[data-edtab=tx]", "aria-selected") == "true" and pg.evaluate("location.hash") != "#cut" and pg.is_visible("#uiSettingsDrawer"),
                  "⚙ 設定の引き出しが開いている間は Alt+2 でタブが変わらない")
            pg.keyboard.press("Escape")   # 開いている間は裏(ヘッダーの ⚙ も)が止まっているので、Esc で閉じる
            wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden")
            pg.keyboard.press("ArrowDown")
            check(pg.evaluate("document.querySelector('#segs .seg.nav').dataset.i") != nav_before, "引き出しを閉じれば ↓ で行が動く(前提の確認)")

            # ---- タブの切り替え(クリック・URL・キー)
            pg.click("[data-edtab=cut]")
            check(pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true" and pg.is_visible("#tabCut") and pg.is_hidden("#tabTx") and pg.is_hidden("#tabPack"),
                  "「2 カット」を押すとカットのタブだけが出る")
            check(pg.evaluate("location.hash") == "#cut", "今のタブは URL の #cut に残る")
            check(pg.is_visible("#docBar"), "題名の行はカットのタブにも出る")
            cls = pg.get_attribute(".app", "class")
            check("tab-wide" in cls and pg.is_visible("#menuStrip") and pg.is_hidden("#menuPanel"), "カットのタブでは、左のメニューを細い帯(☰・履歴・新規)に畳む")
            nav0 = pg.evaluate("document.querySelectorAll('#segs .seg.nav').length")
            pg.keyboard.press("ArrowDown")
            pg.keyboard.press("Shift+ArrowDown")
            check(pg.evaluate("document.querySelectorAll('#segs .seg.nav').length") == nav0, "カットのタブでは、校正のキー(↓・Shift+↓)で行が動かない")
            pg.keyboard.press("Alt+3")
            check(pg.get_attribute("[data-edtab=pack]", "aria-selected") == "true" and pg.is_visible("#tabPack") and pg.evaluate("location.hash") == "#pack",
                  "Alt+3 で 3 パック")
            check(pg.is_visible("#pkBuild") and pg.is_visible("#pkLen"), "パックのタブに「これから作るパック」と「パックを作る」がある")
            wait_js(pg, "!document.querySelector('#pkOff').hidden && document.querySelector('#pkOff').textContent.includes('入口(start.bat)から開いたとき')", 10000)
            check(pg.is_disabled("#pkBuild"), "単体で開いたときはパック作りは使えず、理由(入口から開いたときだけ)が出る")
            wait_js(pg, "document.querySelector('#pkCount').textContent === '1' && document.querySelector('#pkCaps').textContent === '3'", 15000)
            check(pg.inner_text("#pkLen") == "0:12.00", "これから作るパック(区間・長さ・字幕の数)は単体でも出る(サーバーの見積もり)")
            pg.keyboard.press("Alt+1")
            check(pg.get_attribute("[data-edtab=tx]", "aria-selected") == "true" and pg.is_visible("#tabTx") and "tab-wide" not in pg.get_attribute(".app", "class"),
                  "Alt+1 で 1 文字起こし(メニューも元に戻る)")
            pg.keyboard.press("Alt+2")
            check(pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true", "Alt+2 で 2 カット")
            pg.focus("[data-edtab=cut]")
            pg.keyboard.press("ArrowRight")
            check(pg.get_attribute("[data-edtab=pack]", "aria-selected") == "true" and pg.evaluate("document.activeElement.dataset.edtab") == "pack",
                  "タブの並びの中は → で次のタブへ(フォーカスも移る)")
            pg.keyboard.press("ArrowRight")
            check(pg.get_attribute("[data-edtab=tx]", "aria-selected") == "true", "最後のタブの次は最初へ")
            # 行の文字の入力中の Alt+数字 は話者(タブは変えない)
            pg.locator("#segs textarea").first.click()
            pg.keyboard.press("Alt+2")
            check(pg.get_attribute("[data-edtab=tx]", "aria-selected") == "true", "行の文字の入力中は Alt+2 でタブを変えない(Alt+数字 = 話者)")
            pg.keyboard.press("Escape")

            # ---- 再読み込み・URL の # でタブを開く
            pg.goto(srv.base + "#pack")
            wait_js(pg, "document.querySelector('[data-edtab=pack]').getAttribute('aria-selected') === 'true'")
            check(pg.is_hidden("#tabTx") and pg.evaluate("location.hash") == "#pack", "URL の #pack で開くと 3 パック のタブ(再読み込み・窓で開いても同じタブ)")
            pg.evaluate("location.hash = '#cut'")
            wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'")
            check(True, "URL の # を変えるとタブも変わる")

            # ---- 細い帯からメニューを開く(本文の上に重ねる)・閉じる
            pg.click("[data-strip=files]")
            cls = pg.get_attribute(".app", "class")
            check("menu-overlay" in cls and pg.is_visible("#menuPanel") and pg.get_attribute("[data-side-tab=files]", "aria-selected") == "true",
                  "帯の「履歴」で、メニューの履歴を本文の上に重ねて開く")
            box = pg.locator("#menuPanel").bounding_box()
            check(box and pg.evaluate("getComputedStyle(document.querySelector('#menuPanel')).position") == "fixed", "重ねて開く(タイムラインの幅を変えない)")
            pg.keyboard.press("Escape")
            check("menu-overlay" not in pg.get_attribute(".app", "class") and pg.is_hidden("#menuPanel"), "Esc で閉じる")
            pg.click("[data-strip=start]")
            check(pg.get_attribute("[data-side-tab=start]", "aria-selected") == "true" and pg.is_visible("#srcPath"), "帯の「新規」で新規を開く")
            pg.click("#menuScrim", position={"x": 1200, "y": 400})
            check(pg.is_hidden("#menuPanel"), "暗い幕を押すと閉じる")
            pg.keyboard.press("g")
            check("menu-overlay" in pg.get_attribute(".app", "class"), "G でも開く")
            pg.keyboard.press("g")
            check("menu-overlay" not in pg.get_attribute(".app", "class"), "G でもう一度押すと閉じる")
            open_doc(pg, "二本目")
            check("menu-overlay" not in pg.get_attribute(".app", "class") and pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true",
                  "重ねたメニューで文書を選ぶと、メニューを閉じてカットのタブのまま")
            check(pg.inner_text("#pillProof") == "校正 0 / 2行", "開いた文書の札に変わる: " + pg.inner_text("#pillProof"))

            # ---- 文字起こしせずに開く(新規)
            pg.click("[data-strip=start]")
            pg.click("#tabFile")
            pg.fill("#srcPath", v3)
            pg.click("#btnOpenVideo")
            wait_js(pg, "document.querySelector('#docTitle').value === '文字なし' && document.querySelector('#pillProof').hidden", 15000)   # 題名の行は次のフレームで描き直す
            check(pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true" and pg.is_hidden("#menuPanel"), "「文字起こしせずに開く」で文書ができ、カットのタブで開く")
            wait_js(pg, "!document.querySelector('#pillCut').hidden", 10000)
            check(pg.is_hidden("#pillProof") and "残す 1区間" in pg.inner_text("#pillCut") and "0:06" in pg.inner_text("#docMeta"),
                  "行の無い文書の題名の行: 校正の札は出さない・カットは動画全体(残す 1区間)・長さは出る: %s / %s" % (pg.inner_text("#pillCut"), pg.inner_text("#docMeta")))
            check(len(srv.get("/api/jobs")["jobs"]) == n_jobs, "文字起こしは始めない")
            pg.keyboard.press("Alt+1")
            check(pg.is_visible("#noRows") and "まだ文字起こししていません" in pg.inner_text("#noRows") and pg.is_enabled("#btnTxInto"),
                  "1 文字起こし のタブに「この動画を文字起こしする」")
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pg.click("[data-side-tab=start]")
            pg.fill("#srcPath", v3)
            pg.click("#btnOpenVideo")
            wait_js(pg, "document.querySelector('#toast').textContent.includes('前に開いています')", 10000)
            items = [i for i in srv.get("/api/transcripts")["items"] if i["title"] == "文字なし"]
            check(len(items) == 1, "同じ動画をもう一度「文字起こしせずに開く」と、同じ文書を開く(増やさない)")

            # ---- 字幕の文字数(12 ②): 新規の設定・「今の文書を分け直す」(保存してある単語の時刻で長い行を分ける)
            tid1 = next(i["id"] for i in srv.get("/api/transcripts")["items"] if i["title"] == "一本目")
            long1 = "きょうはいいてんきですねさんぽにいきましょうか"
            d1 = srv.get("/api/transcript?id=" + tid1)
            srv.call("PUT", "/api/transcript?id=" + tid1, {"title": d1["title"], "speakers": [], "baseUpdatedAt": d1["updatedAt"],
                                                           "segments": [{"id": "a", "start": 0.0, "end": 4.6, "text": long1}, {"id": "b", "start": 5.0, "end": 6.0, "text": "みじかい"}]})
            with open(os.path.join(srv.tmp, "transcripts", tid1 + ".words.json"), "w", encoding="utf-8") as f:
                json.dump({"schema": "youtube-tools-words/v1", "words": [[round(i * 0.2, 2), round((i + 1) * 0.2, 2), ch] for i, ch in enumerate(long1)]}, f, ensure_ascii=False)
            pg.keyboard.press("Alt+1")
            open_doc(pg, "一本目")
            wait_js(pg, "document.querySelectorAll('#segs .seg').length === 2", 10000)
            check(pg.input_value("#optMaxV") == "16" and pg.input_value("#optMaxH") == "28" and pg.input_value("#optWrapV") == "8" and pg.input_value("#optSubOrient") == "vertical",
                  "新規の設定に 字幕の向き(縦)・最大文字数 縦 16 / 横 28・改行 縦 8 / 横 14")
            check(not pg.evaluate("document.querySelector('#recogDetails').open") and "モデル:" in pg.evaluate("document.querySelector('#optSummary').textContent"),
                  "認識の設定は既定で閉じ、「始める」の上に要約が1行出る: %s" % pg.evaluate("document.querySelector('#optSummary').textContent"))
            opt = pg.evaluate("document.querySelector('#rsOrient').options[0].textContent")   # 閉じた欄の中なので textContent で見る
            check("最大 16 文字" in opt, "「分け直す」の向きに最大文字数が出る: %s" % opt)
            pg.evaluate("document.querySelector('#fixDetails').open = true")
            pg.click("#rsGo")
            wait_js(pg, "document.querySelectorAll('#segs .seg').length === 3", 10000)
            check("1 行を分けました" in pg.inner_text("#rsMsg"), "「今の文書を分け直す」で長い行が 2 つに(%s)" % pg.inner_text("#rsMsg"))
            check(srv.get("/api/history?id=" + tid1)["items"], "分ける前の版が「以前の版に戻す」にある")

            # ---- 疑わしい所だけ認識し直す(12 ③-2): 「長い区間に文字が少ない」の行を、良くなったときだけ置き換える
            # (機械の出力のある文書では、機械の出力と違う行 = 人が直した行は対象にしない。ここは機械の出力の無い「文字なし」の文書で確かめる)
            tid1 = next(i["id"] for i in srv.get("/api/transcripts")["items"] if i["title"] == "文字なし")
            d1 = srv.get("/api/transcript?id=" + tid1)
            F = "長い区間に文字が少ない(抜けの可能性)"
            srv.call("PUT", "/api/transcript?id=" + tid1, {"title": d1["title"], "speakers": [], "baseUpdatedAt": d1["updatedAt"],
                                                           "segments": [{"id": "x", "start": 0.5, "end": 5.5, "text": "黒", "flag": F}]})
            pg.reload()
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "文字なし")
            wait_js(pg, "document.querySelectorAll('#segs .seg').length === 1", 10000)
            check(pg.is_checked("#optAutoRedo") is False and pg.is_checked("#optRedoLarge"), "新規の設定: 疑わしい所を自動で認識し直す(既定オフ)・kotoba なら large-v3(既定オン)")
            pg.evaluate("document.querySelector('#fixDetails').open = true")
            pg.click("#redoGo")
            try:
                wait_js(pg, "[...document.querySelectorAll('#segs .seg textarea')].some(t => t.value.startsWith('認識し直した文'))", 20000)
            except TimeoutError:
                print("DIAG redoMsg=%r toast=%r jobs=%r doc=%r" % (pg.inner_text("#redoMsg"), pg.inner_text("#toast"),
                      [(j["kind"], j["state"], j.get("error"), j.get("phase")) for j in srv.get("/api/jobs")["jobs"]][-3:],
                      [(g["id"], g["text"], g.get("flag")) for g in srv.get("/api/transcript?id=" + tid1)["segments"]]))
                raise
            check(True, "「疑わしい所を認識し直す」で、文字が少なかった行が置き換わり、画面も読み直す")
            check(srv.get("/api/transcript?id=" + tid1).get("redo", {}).get("rows") == 1, "置き換えた記録が文書に残る")

            # ---- 動画全体の再認識(docs/design/whole-retranscribe-design.md の 3): 校正済みの行は残し、ほかを新しい行に(認識は疑似 = 3 秒ごとに「範囲再認識N」)
            tidw = next(i["id"] for i in srv.get("/api/transcripts")["items"] if i["title"] == "一本目")
            dw = srv.get("/api/transcript?id=" + tidw)
            segs_w = [dict(g, text="人が直した一行目", proofed=True) if n == 0 else g for n, g in enumerate(dw["segments"])]
            srv.call("PUT", "/api/transcript?id=" + tidw, {"title": dw["title"], "speakers": dw.get("speakers", []), "baseUpdatedAt": dw["updatedAt"], "segments": segs_w})
            pg.reload()
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "一本目")
            wait_js(pg, "document.querySelectorAll('#segs .seg').length === 3", 10000)
            pg.evaluate("document.querySelector('#fixDetails').open = true; const s = document.querySelector('#rtTarget'); s.value = 'whole'; s.dispatchEvent(new Event('change'))")
            hint = pg.inner_text("#rtHint")
            check("動画全体 0:00" in hint and "校正済みの 1 行は残し" in hint and "残り 2 行" in hint and not pg.is_disabled("#rtGo"),
                  "「対象」の「動画全体」: 範囲・残す行・差し替える行のヒント: %s" % hint)
            pg.click("#rtGo")
            check("校正済み以外の行が書き換わります" in pg.inner_text("#rtGo"), "1回目は押し直しの案内(何が起きるかを書く): %s" % pg.inner_text("#rtGo"))
            pg.click("#rtGo")
            wait_js(pg, "[...document.querySelectorAll('#segs .seg textarea')].some(t => t.value.startsWith('範囲再認識'))", 20000)
            texts = pg.evaluate("[...document.querySelectorAll('#segs .seg textarea')].map(t => t.value)")
            check(texts[0] == "人が直した一行目" and all(t.startswith("範囲再認識") for t in texts[1:]),
                  "終わると読み直し、校正済みの行は残って、ほかは新しい行: %s" % texts)
            check("校正済み 1 行は元のまま" in pg.inner_text("#toast") or "校正済み 1 行" in pg.inner_text("#toast"), "完了の知らせに残した行: %s" % pg.inner_text("#toast"))
            check("全体を再認識" in pg.inner_text("#docInfo"), "認識の設定の欄に「全体を再認識」: %s" % pg.inner_text("#docInfo")[-60:])

            # ---- キー操作の一覧・狭い画面
            pg.click("#btnKeys")
            check("タブ(文字起こし・カット・パック)を切り替える" in pg.inner_text("#keys"), "キー操作の一覧に Alt+1/2/3")
            pg.keyboard.press("Escape")
            pg.set_viewport_size({"width": 390, "height": 800})
            pg.keyboard.press("Alt+2")
            pg.wait_for_timeout(300)
            check(pg.evaluate("document.documentElement.scrollWidth") <= 392, "幅 390px で横にはみ出さない: %s" % pg.evaluate("document.documentElement.scrollWidth"))
            check(pg.is_visible("[data-edtab=pack]") and pg.is_visible("#menuStrip"), "幅 390px でもタブと帯が見える")

            # ---- B-1: ホームからは文書 ID で開く(?doc=)。同じ動画から作った別の文書(新しい方)ではなく、選んだ文書が開く
            pg.set_viewport_size({"width": 1440, "height": 900})
            old_id = next(i["id"] for i in srv.get("/api/transcripts")["items"] if i["title"] == "二本目")
            srv.transcribe(v2, "二本目のやり直し")   # 同じ動画からもう1つ(こちらが新しい)
            pg.goto(srv.base + "?doc=" + old_id + "&media=" + urllib.parse.quote(v2) + "#tx")
            wait_js(pg, "document.querySelector('#docTitle') && document.querySelector('#docTitle').value === '二本目'", 15000)
            check(pg.input_value("#docTitle") == "二本目", "?doc= で選んだ文書が開く(同じ動画の新しい文書ではない)")
            check("doc=" not in pg.url, "開いたあとは URL から ?doc= を外す(読み込み直しで開き直さない): %s" % pg.url)
            pg.goto(srv.base + "?doc=0123456789ab&media=" + urllib.parse.quote(v2) + "#tx")
            wait_js(pg, "document.querySelector('#docTitle') && document.querySelector('#docTitle').value === '二本目のやり直し'", 15000)
            check(True, "文書が見つからなければ、動画のパスで探して開く(予備)")

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
