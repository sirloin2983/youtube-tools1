#!/usr/bin/env python3
"""「編集」E2 画面の骨組みの確認(docs/edit-tool-design.md の 3 と 7): 3つのタブ・Alt+1/2/3・URL の #tx/#cut/#pack・
題名の行の札・カット/パックのタブでの左のメニューの細い帯・文字起こしせずに開く・行の無い文書・狭い画面。

    python e2e_edit_tabs.py
"""
import os
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

            # ---- ヘッダー: ブランド「編集」・3つのタブ
            check(pg.inner_text(".tt-brand-name") == "編集" and pg.title() == "編集", "ブランドとブラウザのタブの題名は「編集」")
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

            # ---- タブの切り替え(クリック・URL・キー)
            pg.click("[data-edtab=cut]")
            check(pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true" and pg.is_visible("#tabCut") and pg.is_hidden("#tabTx") and pg.is_hidden("#tabPack"),
                  "「2 カット」を押すとカットのタブだけが出る")
            check(pg.evaluate("location.hash") == "#cut", "今のタブは URL の #cut に残る")
            check(pg.is_visible("#docBar"), "題名の行はカットのタブにも出る")
            cls = pg.get_attribute(".app", "class")
            check("tab-wide" in cls and pg.is_visible("#menuStrip") and pg.is_hidden("#menuPanel"), "カットのタブでは、左のメニューを細い帯(☰・履歴・新規)に畳む")
            nav0 = pg.evaluate("document.querySelectorAll('#segs .seg.nav').length")
            pg.keyboard.press("s")
            pg.keyboard.press("d")
            check(pg.evaluate("document.querySelectorAll('#segs .seg.nav').length") == nav0, "カットのタブでは、校正のキー(S・D)で行が動かない")
            pg.keyboard.press("Alt+3")
            check(pg.get_attribute("[data-edtab=pack]", "aria-selected") == "true" and pg.is_visible("#tabPack") and pg.evaluate("location.hash") == "#pack",
                  "Alt+3 で 3 パック")
            check(pg.is_visible("#cutPack"), "パックのタブに「パックを作る」の欄がある(E4 で作り直す)")
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
            check(pg.is_hidden("#pillProof") and pg.is_hidden("#pillCut") and "0:06" in pg.inner_text("#docMeta"),
                  "行の無い文書の題名の行: 札は出さず、長さは出る: " + pg.inner_text("#docMeta"))
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

            # ---- キー操作の一覧・狭い画面
            pg.click("#btnKeys")
            check("タブ(文字起こし・カット・パック)を切り替える" in pg.inner_text("#keys"), "キー操作の一覧に Alt+1/2/3")
            pg.keyboard.press("Escape")
            pg.set_viewport_size({"width": 390, "height": 800})
            pg.keyboard.press("Alt+2")
            pg.wait_for_timeout(300)
            check(pg.evaluate("document.documentElement.scrollWidth") <= 392, "幅 390px で横にはみ出さない: %s" % pg.evaluate("document.documentElement.scrollWidth"))
            check(pg.is_visible("[data-edtab=pack]") and pg.is_visible("#menuStrip"), "幅 390px でもタブと帯が見える")

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
