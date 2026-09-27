#!/usr/bin/env python3
"""「編集」E3 カットのタブの確認(docs/edit-tool-design.md の 7 の「E3 の e2e で確かめること」)。入口に取り込んだ形(cut2resolve の api/plan を使う)。

- 開いただけでは保存しない(行からの下書き)・波形が出る
- 区間の端のドラッグで1フレームずつ動く(Alt で吸い付かない)・吸い付く・, . で1フレーム
- S で分割・Del で削る/戻す(隣とつながる)・I/O/X・元に戻す/やり直す
- 保存して読み直すと同じ・2つのタブで同時に直すと 409 と「読み直す」
- カット後の再生で削る区間を飛ばす(webm)
- 1 文字起こし で行を「削る」→ カットの帯に出る・その逆(字幕の一覧の「削る」→ 1 文字起こし の行がカット済)
- 文字起こしの無い動画(無音のたたき台)・動画が見つからない文書は理由を出す

    python e2e_edit_cut.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

from e2e_edit_common import Checks, Server, make_video, open_doc, wait_js

FPS = 30
ROWS = [(0.5, 3.2), (4.0, 6.5), (7.0, 9.8), (11.0, 14.5), (15.2, 19.0)]


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        v1 = make_video(os.path.join(srv.media, "カットの確認.webm"), sec=20, fps=FPS, beeps=ROWS)
        tid = srv.transcribe(v1, "カットの確認")
        doc = srv.get("/api/transcript?id=" + tid)
        segs = [{"id": "r%d" % (i + 1), "start": a, "end": b, "text": "行%d" % (i + 1)} for i, (a, b) in enumerate(ROWS)]
        srv.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [], "segments": segs})
        v2 = make_video(os.path.join(srv.media, "文字起こしなし.webm"), sec=10, fps=FPS, beeps=[(1.0, 3.0), (5.0, 8.0)])
        v3 = make_video(os.path.join(srv.media, "消える動画.webm"), sec=4, fps=FPS)

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1440, "height": 950})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(srv.base)
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "カットの確認")
            pg.keyboard.press("Alt+2")
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5", 20000)

            def clips():   # 画面の区間(title の「残す区間 0:00.50〜0:03.20」)ではなく、保存・パックと同じ形の秒で比べる
                return pg.evaluate("[...document.querySelectorAll('#tlVideo .tt-k')].map(k => k.title)")

            def server_clips():
                e = srv.get("/api/edit?id=" + tid)["edit"]
                return None if e is None else [(c["in"], c["out"]) for c in e["clips"]]

            def wait_saved(rev=None):
                wait_js(pg, "document.querySelector('#cutSaveSt').textContent === 'カットを保存しました'", 10000)
                if rev is not None:
                    for _ in range(50):
                        if srv.get("/api/edit?id=" + tid)["rev"] >= rev:
                            break
                        time.sleep(0.1)

            check("文字起こしの行から作った下書き" in pg.inner_text("#cutStatus") and server_clips() is None,
                  "開いたときは「行から」の下書き(5区間)。開いただけでは保存しない")
            check("残す 5区間" in pg.inner_text("#cutStatus") and "カット後" in pg.inner_text("#cutStatus"), "下の行に残す区間の数とカット後の長さ: " + pg.inner_text("#cutStatus"))
            # 波形(音の鳴っている 1.0 秒あたりに線がある)
            wait_js(pg, """(() => { const c = document.querySelector('#tlWave'), sc = document.querySelector('#tlScroll');
              const pps = sc.scrollWidth / 20, x = Math.round((1.0 * pps - sc.scrollLeft) * (window.devicePixelRatio || 1));
              const d = c.getContext('2d').getImageData(x, 0, 1, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n > 10; })()""", 20000)
            check(True, "音の波形が出る(サーバーの /api/peaks)")

            # ---- 段3: ホイールで拡大縮小(Ctrl 不要・マウスの位置が中心)・Shift+ホイールで横移動・ミニマップ
            pg.click("#cutZoomFit")
            pg.wait_for_timeout(100)
            sc_box = pg.locator("#tlScroll").bounding_box()
            mx, my = sc_box["x"] + sc_box["width"] * 0.3, sc_box["y"] + sc_box["height"] / 2
            t_before = (pg.evaluate("document.querySelector('#tlScroll').scrollLeft") + (mx - sc_box["x"])) / pg.evaluate("document.querySelector('#tlScroll').scrollWidth / 20")
            pg.mouse.move(mx, my)
            pg.mouse.wheel(0, -600)   # Ctrl は押さない。上(deltaY<0)で広げる
            pg.wait_for_timeout(150)
            pps_zoomed = pg.evaluate("document.querySelector('#tlScroll').scrollWidth / 20")
            t_after = (pg.evaluate("document.querySelector('#tlScroll').scrollLeft") + (mx - sc_box["x"])) / pps_zoomed
            check(pps_zoomed > 20, "ホイール(Ctrl 不要)で拡大できる: 1秒 %.1f 点" % pps_zoomed)
            check(abs(t_after - t_before) < 0.4, "マウスの位置の時刻が拡大の前後でだいたい変わらない(その場所が中心): %.2f → %.2f" % (t_before, t_after))
            sl_before = pg.evaluate("document.querySelector('#tlScroll').scrollLeft")
            pg.keyboard.down("Shift")
            pg.mouse.wheel(0, 240)
            pg.keyboard.up("Shift")
            pg.wait_for_timeout(150)
            sl_after = pg.evaluate("document.querySelector('#tlScroll').scrollLeft")
            check(sl_after > sl_before, "Shift+ホイールで横に移動する: %s → %s" % (sl_before, sl_after))
            # ミニマップ: 見ている範囲の枠(拡大しているので全体より狭い)・ドラッグで見る範囲を移動できる
            mini_box = pg.locator("#tlMini").bounding_box()
            view_box = pg.locator("#tlMiniView").bounding_box()
            check(pg.is_visible("#tlMini") and 0 < view_box["width"] < mini_box["width"] * 0.9, "ミニマップに、見ている範囲より狭い枠が出る(拡大しているので): %.0f / %.0f" % (view_box["width"], mini_box["width"]))
            sl_before2 = pg.evaluate("document.querySelector('#tlScroll').scrollLeft")
            vx, vy = view_box["x"] + view_box["width"] / 2, view_box["y"] + view_box["height"] / 2
            pg.mouse.move(vx, vy)
            pg.mouse.down()
            pg.mouse.move(vx - mini_box["width"] * 0.2, vy, steps=4)   # 左へ(すでに右へ寄せてあるので、詰まらない向きへ動かす)
            pg.mouse.up()
            pg.wait_for_timeout(150)
            sl_after2 = pg.evaluate("document.querySelector('#tlScroll').scrollLeft")
            check(sl_after2 != sl_before2, "ミニマップの枠をドラッグすると、見る範囲が移る: %s → %s" % (sl_before2, sl_after2))
            # ミニマップの枠の端(右)をドラッグすると、その端だけ動いて拡大縮小する(左端は固定)
            view_box3 = pg.locator("#tlMiniView").bounding_box()
            pps_before_h = pg.evaluate("document.querySelector('#tlScroll').scrollWidth / 20")
            hx3, hy3 = view_box3["x"] + view_box3["width"], view_box3["y"] + view_box3["height"] / 2
            pg.mouse.move(hx3, hy3)
            pg.mouse.down()
            pg.mouse.move(hx3 - max(6, view_box3["width"] * 0.4), hy3, steps=4)
            pg.mouse.up()
            pg.wait_for_timeout(150)
            pps_after_h = pg.evaluate("document.querySelector('#tlScroll').scrollWidth / 20")
            check(pps_after_h > pps_before_h, "ミニマップの枠の端をドラッグすると拡大縮小する(右端を左へ引くと狭くなる=拡大): %.1f → %.1f" % (pps_before_h, pps_after_h))
            pg.click("#cutZoomFit")

            # ---- 端のドラッグ(1フレーム単位・Alt で吸い付かない)
            pg.locator("#tlVideo .tt-k[data-i='1']").click()
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k[data-i=\"1\"] .tt-h').length === 2", 3000)
            check(True, "区間を押すと選ばれて、両端につまみが出る")

            # ---- 段3: 画面の下の帯(UIKit.keybar)。端を選ぶ/外す・タブを離れるで場面が変わる
            def keybar_keys():
                return pg.evaluate("[...document.querySelectorAll('.ui-keybar .ui-keybar-item')].map(e => e.dataset.k)")
            pg.locator("#tlVideo .tt-k[data-i='1'] .tt-h.out").click()   # 区間の本体を押しただけでは端は選ばない(つまみを押したときだけ)
            wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.out.on')", 3000)
            check(pg.evaluate("document.querySelector('.ui-keybar').hidden") is False and {",", "."} <= set(keybar_keys()),
                  "端を選ぶと、下の帯が「, . 1コマ」の場面になる: %s" % keybar_keys())
            pg.keyboard.press("Escape")
            wait_js(pg, "!document.querySelector('#tlVideo .tt-k.sel')", 3000)
            check("S" in keybar_keys() and "," not in keybar_keys(), "選択を外す(Esc)と、下の帯は通常のカットの場面(S・Del など)に戻る: %s" % keybar_keys())
            pg.keyboard.press("Alt+1")
            wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
            check("↓" in keybar_keys() and "S" not in keybar_keys(), "1 文字起こし のタブへ移ると、下の帯もそのタブの場面に変わる(カットの場面が残らない): %s" % keybar_keys())
            pg.keyboard.press("Alt+2")
            wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'")
            check("S" in keybar_keys(), "2 カット のタブへ戻ると、下の帯もカットの場面に戻る: %s" % keybar_keys())
            pg.keyboard.press("Alt+3")
            wait_js(pg, "document.querySelector('[data-edtab=pack]').getAttribute('aria-selected') === 'true'")
            check(len(keybar_keys()) == 0, "3 パック のタブには帯の場面が無いので、カットの場面は残らず消える: %s" % keybar_keys())
            pg.keyboard.press("Alt+2")
            wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'")
            check("S" in keybar_keys(), "カットのタブへ戻ると、下の帯もまた出る: %s" % keybar_keys())
            # 上の帯の確かめで Esc で選択を外したので、端のドラッグの前にもう一度区間を選ぶ
            pg.locator("#tlVideo .tt-k[data-i='1']").click()
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k[data-i=\"1\"] .tt-h').length === 2", 3000)

            for _ in range(12):
                pg.click("#cutZoomIn")
            pg.evaluate("document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.out').scrollIntoView({inline: 'center', block: 'nearest'})")
            pg.wait_for_timeout(200)
            h = pg.locator("#tlVideo .tt-k[data-i='1'] .tt-h.out").bounding_box()
            pps = pg.evaluate("document.querySelector('#tlScroll').scrollWidth / 20")
            px_per_frame = pps / FPS
            check(abs(px_per_frame - 14) < 0.6, "いちばん広げると1フレームが 14 点: %.2f" % px_per_frame)
            x0, y0 = h["x"] + h["width"] / 2, h["y"] + h["height"] / 2
            pg.keyboard.down("Alt")
            pg.mouse.move(x0, y0)
            pg.mouse.down()
            pg.mouse.move(x0 + px_per_frame, y0, steps=3)
            pg.mouse.move(x0 + px_per_frame * 2, y0, steps=3)
            tip = pg.inner_text("#tlTip")
            pg.mouse.up()
            pg.keyboard.up("Alt")
            check("終わり 0:06.57" in tip and "(+2フレーム)" in tip, "ドラッグ中は黒い札に「終わり 0:06.57(+2フレーム)」: " + tip)
            wait_saved()
            sc = server_clips()
            check(sc is not None and abs(sc[1][1] - (6.5 + 2 / FPS)) < 1e-3 and sc[1][1] == round((195 + 2) / FPS, 3),
                  "区間の端が2フレーム動いて保存される(元の動画のフレームの境目の秒): %s" % ((sc[1] if sc else None),))
            pg.keyboard.press(".")
            pg.keyboard.press(".")
            pg.keyboard.press(",")
            wait_saved()
            check(server_clips()[1][1] == round(198 / FPS, 3), ". . , で選んだ端が1フレームずつ動く: %s" % (server_clips()[1],))

            # ---- 段3: 端の当たり判定は見た目の外側 6px まで(区間そのものの右端の少し外を掴んでもドラッグできる)
            pg.evaluate("document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.out').scrollIntoView({inline: 'center', block: 'nearest'})")   # 端を画面の中へ
            pg.wait_for_timeout(200)
            k_box = pg.locator("#tlVideo .tt-k[data-i='1']").bounding_box()
            hh_box = pg.locator("#tlVideo .tt-k[data-i='1'] .tt-h.out").bounding_box()
            hx = (k_box["x"] + k_box["width"] + hh_box["x"] + hh_box["width"]) / 2   # 見た目の区間の外側・つまみの外端の間(見た目の外だけをつかむ)
            hy = hh_box["y"] + hh_box["height"] / 2
            before_end = server_clips()[1][1]
            pg.keyboard.down("Alt")   # 端は再生位置(直前の , . で端と同じ所)に吸い付くので、Alt で吸い付きを止めて当たり判定だけを確かめる
            pg.mouse.move(hx, hy)
            pg.mouse.down()
            pg.mouse.move(hx + px_per_frame * 3, hy, steps=3)
            pg.mouse.up()
            pg.keyboard.up("Alt")
            wait_saved()
            after_end = server_clips()[1][1]
            check(after_end != before_end, "区間の端は、見た目の外側(数点)を掴んでもドラッグできる(当たり判定が広い): %s → %s" % (before_end, after_end))
            pg.keyboard.press("Control+z")   # この確かめのドラッグを取り消して、下の「元に戻す」の確かめを前と同じ状態から始める
            wait_saved()
            check(server_clips()[1][1] == before_end, "当たり判定の確かめのドラッグは Ctrl+Z で戻る: %s" % (server_clips()[1],))

            # ---- 吸い付く(再生位置)・Alt で吸い付かない
            pg.click("#cutZoomFit")
            pg.evaluate("(() => { const v = document.querySelector('#cutPlayer'); v.currentTime = 5.5; })()")
            wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 5.5) < 0.01")
            pg.locator("#tlVideo .tt-k[data-i='1']").click()
            wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.out')", 3000)
            h = pg.locator("#tlVideo .tt-k[data-i='1'] .tt-h.out").bounding_box()
            box = pg.locator("#tlContent").bounding_box()
            pps = pg.evaluate("document.querySelector('#tlScroll').scrollWidth / 20")
            target_x = box["x"] + 5.5 * pps + 4   # 再生位置の 4 点右で離す
            x0, y0 = h["x"] + h["width"] / 2, h["y"] + h["height"] / 2
            pg.mouse.move(x0, y0)
            pg.mouse.down()
            pg.mouse.move(target_x, y0, steps=6)
            snap_shown = pg.is_visible("#tlSnap")
            pg.mouse.up()
            wait_saved()
            check(server_clips()[1][1] == 5.5 and snap_shown, "再生位置の近くで離すと、再生位置に吸い付く(点線が出る): %s" % (server_clips()[1],))
            pg.keyboard.press("Control+z")
            wait_saved()
            pg.locator("#tlVideo .tt-k[data-i='1']").click()
            wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"1\"] .tt-h.out')", 3000)
            h = pg.locator("#tlVideo .tt-k[data-i='1'] .tt-h.out").bounding_box()
            x0 = h["x"] + h["width"] / 2
            pg.keyboard.down("Alt")
            pg.mouse.move(x0, y0)
            pg.mouse.down()
            pg.mouse.move(target_x, y0, steps=6)
            pg.mouse.up()
            pg.keyboard.up("Alt")
            wait_saved()
            got = server_clips()[1][1]
            check(got != 5.5 and abs(got - 5.5) < 0.12, "Alt を押していると吸い付かない: %.3f" % got)
            pg.keyboard.press("Control+z")
            wait_saved()
            check(server_clips()[1][1] == round(198 / FPS, 3), "元に戻す(Ctrl+Z)で、ドラッグの前に戻る: %s" % (server_clips()[1],))

            # ---- 分割・削る・戻す
            pg.evaluate("document.querySelector('#cutPlayer').currentTime = 12.5")
            wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 12.5) < 0.01")
            pg.focus("#tlScroll")
            pg.keyboard.press("s")
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 6")
            check(True, "S で再生位置の所を分割する(5 → 6区間)")
            check("残す 5区間" in pg.inner_text("#cutStatus"), "分割しただけの所は、区間の数では1つに数える(パックでも1つ): " + pg.inner_text("#cutStatus"))
            pg.locator("#tlVideo .tt-k[data-i='4']").click()
            wait_js(pg, "!!document.querySelector('#tlVideo .tt-k[data-i=\"4\"].sel')", 3000)
            pg.keyboard.press("Delete")
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 5")
            wait_saved()
            check(server_clips()[3] == (11.0, 12.5), "選んだ区間を Del で削る(12.5〜14.5 が削る区間に): %s" % (server_clips()[3],))
            pg.evaluate("""(() => { const x = [...document.querySelectorAll('#tlVideo .tt-x')].find(e => Number(e.dataset.a) === 375);
              x.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, clientX: x.getBoundingClientRect().left + 3 })); })()""")
            pg.keyboard.press("Delete")
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 4")
            wait_saved()
            # 行5 の終わり(19.0)は「行から」で声の止まる所まで広がる(音の止まり目は webm の符号化で 1〜2 フレーム後ろになる)
            c3 = server_clips()[3]
            check(c3[0] == 11.0 and 19.0 <= c3[1] <= 19.07, "削る区間を選んで Del で戻すと、隣の残す区間とつながる: %s" % (c3,))

            # ---- I / O / X
            pg.evaluate("document.querySelector('#cutPlayer').currentTime = 1.0")
            wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 1.0) < 0.01")
            pg.focus("#tlScroll")
            pg.keyboard.press("i")
            pg.evaluate("document.querySelector('#cutPlayer').currentTime = 2.0")
            wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 2.0) < 0.01")
            pg.keyboard.press("o")
            wait_js(pg, "!document.querySelector('#tlIO').hidden && !document.querySelector('#cutIO').disabled", 3000)
            check(True, "I と O で範囲が出る(黄色の点線)")
            pg.keyboard.press("x")
            wait_saved()
            sc = server_clips()
            check(sc[0] == (0.5, 1.0) and sc[1] == (2.0, 3.2), "X で I〜O を削る: %s" % (sc[:2],))
            pg.keyboard.press("Control+z")
            wait_saved()
            check(server_clips()[0] == (0.5, 3.2), "元に戻す: %s" % (server_clips()[0],))
            pg.keyboard.press("Control+Shift+z")
            wait_saved()
            check(server_clips()[:2] == [(0.5, 1.0), (2.0, 3.2)], "やり直す(Ctrl+Shift+Z): %s" % (server_clips()[:2],))

            # ---- 1 文字起こし のタブの行の「削る」⇄ カットの帯
            before = server_clips()
            pg.keyboard.press("Alt+1")
            row = pg.locator("#segs .seg").nth(2)   # 行3(7.0〜9.8)
            row.locator("[data-act=cut]").click()
            wait_js(pg, "document.querySelectorAll('#segs .seg')[2].classList.contains('cut')")
            pg.keyboard.press("Alt+2")
            wait_saved()
            sc = server_clips()
            check(not any(a < 9.8 and b > 7.0 for a, b in sc) and len(sc) == len(before) - 1, "1 文字起こし で行を「削る」→ その行の時間が削る区間になる: %s" % sc)
            check(not any(9.8 <= a and b <= 10.3 for a, b in sc), "行の後ろの切れ端(「行から」で広げた分)も一緒に削る: %s" % sc)
            check(pg.locator("#cutSubs .tt-csub[data-i='2']").get_attribute("class").find("cut") >= 0 and pg.locator("#tlSubs .tt-s.cut").count() >= 1,
                  "カットのタブの字幕の一覧・字幕の帯にも出る(薄く・取り消し線)")
            pg.locator("#cutSubs .tt-csub[data-i='4'] [data-act=cutrow]").click()   # 字幕の一覧の「削る」(行5)
            wait_saved()
            pg.keyboard.press("Alt+1")
            wait_js(pg, "document.querySelectorAll('#segs .seg')[4].classList.contains('cut')")
            d = srv.get("/api/transcript?id=" + tid)
            check([g.get("cutState") for g in d["segments"]] == [None, None, "cut", None, "cut"],
                  "字幕の一覧の「削る」→ 1 文字起こし の行もカット済。文書の行の印もサーバーで合わせてある: %s" % [g.get("cutState") for g in d["segments"]])

            # ---- 保存して読み直すと同じ
            shown = clips()
            pg.reload()   # 同じ URL への goto は読み直さない(# だけの移動になる)
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "カットの確認")
            check(pg.evaluate("location.hash") == "#tx", "読み直すと、直前のタブ(#tx)で開く")
            pg.keyboard.press("Alt+2")
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === %d" % len(shown), 20000)
            check(clips() == shown and "下書き" not in pg.inner_text("#cutStatus"), "保存して読み直すと同じ区間(下書きではない)")

            # ---- カット後の再生(削る区間を飛ばす)
            pg.click("#cutModeCut")
            pg.evaluate("""(() => { const v = document.querySelector('#cutPlayer'); window.__t = []; v.muted = true;
              v.addEventListener('timeupdate', () => window.__t.push(v.currentTime)); v.currentTime = 0.8; })()""")
            wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 0.8) < 0.01")
            pg.click("#cutPlay")
            wait_js(pg, "document.querySelector('#cutPlayer').currentTime > 2.3", 10000)
            pg.evaluate("document.querySelector('#cutPlayer').pause()")
            ts = pg.evaluate("window.__t")
            check(not any(1.05 < t < 1.95 for t in ts), "カット後の見え方では、削る区間(1.0〜2.0)を飛ばして再生する: %s" % [round(t, 2) for t in ts[:12]])
            check("カット後" in pg.inner_text(".tt-cut-time"), "時刻は元とカット後の両方を出す")

            # ---- 2つのタブで同時に直す → 409 と「読み直す」
            pg2 = ctx.new_page()
            pg2.on("pageerror", lambda e: errors.append(str(e)))
            pg2.goto(srv.base + "#cut")
            wait_js(pg2, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg2, "カットの確認")
            wait_js(pg2, "document.querySelectorAll('#tlVideo .tt-k').length === %d" % len(shown), 20000)
            pg2.evaluate("document.querySelector('#cutPlayer').currentTime = 12.0")
            wait_js(pg2, "Math.abs(document.querySelector('#cutPlayer').currentTime - 12.0) < 0.01")
            pg2.focus("#tlScroll")
            pg2.keyboard.press("s")
            wait_js(pg2, "document.querySelector('#cutSaveSt').textContent === 'カットを保存しました'", 10000)
            n2 = pg2.evaluate("document.querySelectorAll('#tlVideo .tt-k').length")
            pg.bring_to_front()
            pg.evaluate("document.querySelector('#cutPlayer').currentTime = 13.0")
            wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - 13.0) < 0.01")
            pg.focus("#tlScroll")
            pg.keyboard.press("s")
            wait_js(pg, "!document.querySelector('#cutConflict').hidden", 10000)
            check("競合" in pg.inner_text("#cutSaveSt"), "別のタブで先に保存されていると 409 → 黙って上書きしない(案内を出す)")
            errors[:] = [e for e in errors if "409" not in e]   # わざと起こした 409 はブラウザがエラーとして記録する(想定どおり)
            pg.click("#cutReload")
            wait_js(pg, "document.querySelector('#cutConflict').hidden && document.querySelectorAll('#tlVideo .tt-k').length === %d" % n2, 10000)
            check(True, "「読み直す」で、先に保存された内容になる")
            pg2.close()

            # ---- 「行から ▾」の設定(行の端を声の止まる所まで広げる。サーバーの設定 rowEdge = zip・まとめて実行も同じ)
            pg.click("#cutRowEdge summary")
            check(pg.is_checked("#cutEdgeOn") and pg.input_value("#cutEdgeAfter") == "0.5", "「行から ▾」: 既定は広げる(終わり 0.5 秒・始まり 0.3 秒まで)")
            pg.uncheck("#cutEdgeOn")
            pg.click("#cutEdgeGo")
            # 段3: confirmReplace は UIKit.dialog.confirm(動的に <dialog class="ui-dialog"> を作る。旧 #dlgConfirm ではない)
            pg.wait_for_selector("dialog.ui-dialog[open]")
            pg.click("dialog.ui-dialog .ui-dlg-actions button:has-text('置き換える')")   # 手で直したカットがあるので置き換えの確認
            wait_js(pg, "document.querySelector('#cutSaveSt').textContent === 'カットを保存しました' && !document.querySelector('#cutRowEdge').open", 15000)
            sc = server_clips()
            check(srv.get("/api/settings").get("rowEdge", {}).get("on") is False and sc == [(0.5, 3.2), (4.0, 6.5), (11.0, 14.5)],
                  "広げない設定で「行から」: 残す行(行3・行5 はカット済)の時間のまま。設定はサーバーに保存: %s" % sc)
            pg.click("#cutRowEdge summary")
            pg.check("#cutEdgeOn")
            pg.click("#cutRowEdge summary")
            wait_js(pg, "!document.querySelector('#cutRowEdge').open")
            for _ in range(30):
                if srv.get("/api/settings").get("rowEdge", {}).get("on") is True:
                    break
                time.sleep(0.1)
            check(srv.get("/api/settings").get("rowEdge", {}).get("on") is True, "設定を戻す(チェックを変えただけでも保存する)")

            # ---- 文字起こしの無い動画: 全部残す → 無音のたたき台(cut2resolve)
            pg.click("[data-strip=start]")
            pg.click("#tabFile")
            pg.fill("#srcPath", v2)
            pg.click("#btnOpenVideo")
            wait_js(pg, "document.querySelector('#docTitle').value === '文字起こしなし' && document.querySelectorAll('#tlVideo .tt-k').length === 1", 20000)
            check("動画全体の下書き" in pg.inner_text("#cutStatus"), "文字起こしの無い動画は、動画全体を残す下書き")
            pg.click("#cutDraftSilence summary")
            pg.fill("#cutSilMin", "0.5")
            pg.click("#cutDraftSilenceGo")
            wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length === 2", 30000)
            titles = clips()
            import re
            nums = [[int(m[0]) * 60 + float(m[1]) for m in re.findall(r"(\d+):(\d+\.\d+)", t)[:2]] for t in titles]
            check(len(nums) == 2 and 0.6 < nums[0][0] < 1.0 and 3.0 < nums[0][1] < 3.4 and 4.6 < nums[1][0] < 5.0 and 8.0 < nums[1][1] < 8.4,
                  "無音のたたき台(cut2resolve の api/plan): 音の鳴っている所(1〜3秒・5〜8秒)だけ残る: %s" % nums)

            # ---- 動画の長さが変わった(同じパスの動画を書き出し直した): 後ろの区間は切って知らせる
            v4 = make_video(os.path.join(srv.media, "縮む動画.webm"), sec=6, fps=FPS)
            tid4 = srv.call("POST", "/api/open-video", {"path": v4})["id"]
            r4 = srv.call("PUT", "/api/edit?id=" + tid4, {"baseRev": 0, "edit": {"sources": [{"fps": [FPS, 1], "duration": 6.0}],
                                                                             "clips": [{"src": 0, "in": 0.5, "out": 2.0}, {"src": 0, "in": 3.0, "out": 5.5}]}})
            check(r4.get("rev") == 1, "(準備)6秒の動画のカットを保存")
            make_video(v4, sec=4, fps=FPS)   # 同じ名前で 4 秒の動画に書き出し直す
            pg.reload()
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "縮む動画")
            pg.keyboard.press("Alt+2")
            wait_js(pg, "document.querySelector('#toast').textContent.includes('長さ')", 15000)
            for _ in range(50):
                e4 = srv.get("/api/edit?id=" + tid4)
                if e4["rev"] >= 2:
                    break
                time.sleep(0.2)
            c4 = [(c["in"], c["out"]) for c in e4["edit"]["clips"]]
            check(e4["rev"] >= 2 and c4[0] == (0.5, 2.0) and c4[-1][1] <= 4.01, "動画が短くなったら、後ろの区間を切って知らせ、保存し直す: %s" % c4)

            # ---- 動画が見つからない文書
            r3 = srv.call("POST", "/api/open-video", {"path": v3})
            check("id" in r3, "(準備)動画の文書を作る: %s" % r3)
            os.remove(v3)
            n_err = len(errors)
            pg.reload()   # 同じ URL への goto は読み直さない(# だけの移動になる)
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "消える動画")
            wait_js(pg, "!document.querySelector('#cutOff').hidden", 10000)
            check("見つかりません" in pg.inner_text("#cutOff") and pg.locator("#tlVideo .tt-k").count() == 0 and pg.is_disabled("#cutSplit"),
                  "動画が見つからない文書は、カットのタブに理由を出して使えなくする: " + pg.inner_text("#cutOff"))
            del errors[n_err:]   # 見つからない動画・下書きの 404 はブラウザがエラーとして記録する(想定どおり)

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
