#!/usr/bin/env python3
"""「編集」E4 パックのタブの確認(docs/edit-tool-design.md の 3・5・7)。入口に取り込んだ形(パックは cut2resolve の api/build)。

- カット(手で決めた区間。60fps の元の動画)のとおりにパックができる(Lua に埋め込んだ区間 = 編集の内容のフレーム)
- パックは最小限(④): 動画(直下)・Lua・雛形・登録用の ps1/bat だけ(手順書は画面の「Resolve での手順を見る」)。「予備も入れる」で EDL・予備の手順書・SRT
- 作る前の注意: とても短い区間・60fps の動画を 30fps のプロジェクトへ
- 作ったら「前回のパック」と packRev(一覧の API)
- 文字起こしの無い動画: Text+ なし(EDL と元の動画のコピー)のパック
- 作っている途中の「中止」

    python e2e_edit_pack.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

from e2e_edit_common import Checks, Server, make_video, open_doc, read_pack_plan, wait_js

FPS = 60


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        v1 = make_video(os.path.join(srv.media, "パックの確認.webm"), sec=8, fps=FPS)
        tid = srv.transcribe(v1, "パックの確認")
        doc = srv.get("/api/transcript?id=" + tid)
        rows = [(0.5, 2.0, "一つめ"), (2.5, 2.8, "短い"), (4.0, 7.5, "三つめ")]
        srv.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [{"id": "S1", "name": "みこ"}],   # A-2: 1行目だけ話者「みこ」(= さくらみこ)
                                                      "segments": [dict({"id": "r%d" % i, "start": a, "end": b, "text": t}, **({"speaker": "S1"} if i == 0 else {}))
                                                                   for i, (a, b, t) in enumerate(rows)]})
        # カット(手で決めた区間): 60fps のフレームの境目。2つめは 0.3 秒(とても短い)・3つめは行より 3 フレーム長い
        clips = [(30, 120), (150, 168), (240, 453)]
        r = srv.call("PUT", "/api/edit?id=" + tid, {"baseRev": 0, "edit": {"sources": [{"fps": [FPS, 1], "duration": 8.0}],
                                                                           "clips": [{"src": 0, "in": round(a / FPS, 3), "out": round(b / FPS, 3)} for a, b in clips]}})
        check(r.get("rev") == 1, "(準備)カットを保存: %s" % r)
        v2 = make_video(os.path.join(srv.media, "字幕なし.webm"), sec=4, fps=30)

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1440, "height": 950})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(srv.base + "#pack")
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "パックの確認")
            wait_js(pg, "document.querySelector('#pkCount').textContent === '3' && document.querySelector('#pkCaps').textContent === '3'", 30000)
            check(pg.inner_text("#pkLen") == "0:05.35", "これから作るパック: 3区間・カット後 0:05.35(=321フレーム)・字幕 3: " + pg.inner_text("#pkLen"))
            wait_js(pg, "!document.querySelector('#pkWarn').hidden", 10000)
            check("0.5 秒より短い区間が 1 か所" in pg.inner_text("#pkWarn"), "作る前の注意に、とても短い区間(0.3 秒): " + pg.inner_text("#pkWarn"))
            # 段3: 詳しい設定(fps・大きさ・入れるもの・出力先)は「設定を変える」で開く右の欄
            check("30fps" in pg.inner_text("#pkSummaryText"), "前回の設定の要約が出る(既定は 30fps): " + pg.inner_text("#pkSummaryText"))
            pg.click("#pkSettingsBtn")
            pg.wait_for_selector("#pkSettingsDrawer:not([hidden])", state="visible")
            check(pg.is_visible("#pkFpsWarn") and "60fps" in pg.inner_text("#pkFpsWarn"), "60fps の元の動画を 30fps のプロジェクトに入れるときの注意: " + pg.inner_text("#pkFpsWarn"))
            pg.click("#pkFps [data-v='60']")
            wait_js(pg, "document.querySelector('#pkFpsWarn').hidden", 3000)
            check(True, "置き先を 60fps にすると注意は消える")
            pg.click("#pkFps [data-v='30']")
            pg.click("#pkSize [data-v='1080x1920']")
            # パックの音量(2026-09-29): 既定は -14 LUFS。「音量を % で決める」を選ぶと % の欄が出て、編集の設定(送ったキーだけ)に残る
            check(pg.input_value("#pkLoud") == "-14" and pg.is_hidden("#pkVolBox"), "音量の既定は -14 LUFS(% の欄は隠れている)")
            pg.select_option("#pkLoud", "0")
            wait_js(pg, "!document.querySelector('#pkVolBox').hidden", 5000)
            pg.fill("#pkVol", "70"); pg.press("#pkVol", "Tab")
            check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('音量 70%') >= 0", 5000), "要約に「音量 70%」: " + pg.inner_text("#pkSummaryText"))
            st = srv.get("/api/settings")
            check((st.get("packLoudness"), st.get("packVolume")) == (0, 70), "編集の設定に残る: %s" % ((st.get("packLoudness"), st.get("packVolume")),))
            pg.select_option("#pkLoud", "-14")
            check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('音量 -14 LUFS') >= 0", 5000), "LUFS に戻すと要約も戻る")
            pg.click("#pkSettingsClose")
            wait_js(pg, "document.querySelector('#pkSettingsDrawer').hidden === true")
            check("縦 1080" in pg.inner_text("#pkSummaryText"), "設定を変えると要約も変わる: " + pg.inner_text("#pkSummaryText"))
            # 配信者の名前(字幕の色。docs/followup-2026-09-27.md の 4): 候補・色の見本・字幕の見本の色。パックの Lua の見た目もその色(pkWho は主画面にいつも見える)
            pg.fill("#pkWho", "ぺこら")
            wait_js(pg, "document.querySelector('#pkWho').dataset.color === '#7EC2FE'", 10000)
            check("兎田ぺこら" in pg.inner_text(".tt-pk-who .ui-streamer-hint") and "兎田ぺこらの色の文字" in pg.inner_text("#pkLookName") and
                  pg.evaluate("getComputedStyle(document.querySelectorAll('#pkSamples .tt-pk-cap')[1]).color") == "rgb(126, 194, 254)",   # 2行目(話者なし)の見本。1行目は話者「みこ」の色(段2)
                  "配信者の名前 → メンバーカラーの見本・字幕の見本の色: %s" % pg.inner_text(".tt-pk-who .ui-streamer-hint"))
            check(pg.evaluate("document.querySelectorAll('#ui-streamer-list option').length") > 50, "名前の候補(ホロカラーの一覧)")
            check(wait_js(pg, "!document.querySelector('#pkSummarySw').hidden && getComputedStyle(document.querySelector('#pkSummarySw')).backgroundColor === 'rgb(126, 194, 254)'", 5000),
                  "「前回の設定」の要約にも配信者の色の丸が出る(pkWho の色と同じ)")
            # A-2: 話者の名前がメンバーと合えば、その話者の字幕をその色に(既定オン)。どの話者が何色かを見せる
            check(pg.is_checked("#pkSpk"), "「話者の名前がメンバーと合えば…」は既定でオン")
            wait_js(pg, "document.querySelector('#pkSpkList').textContent.indexOf('さくらみこの色') >= 0", 10000)
            check(True, "話者「みこ」→ さくらみこの色、と見せる: " + pg.inner_text("#pkSpkList"))
            phone = "getComputedStyle(document.querySelector('#pkPhoneCap')).color"
            check(wait_js(pg, "%s === 'rgb(255, 143, 223)'" % phone, 10000), "字幕の見本(電話の形)も、1行目の話者「みこ」の色(GPT-12・段2): %s" % pg.evaluate(phone))
            # 段3: 設定の引き出しを開かずに(主画面だけで)「パックを作る」を1クリックで作れる(ワンクリック)
            check(pg.evaluate("document.querySelector('#pkSettingsDrawer').hidden") is True, "「作る」を押す前に、設定の引き出しは閉じている")
            pg.click("#pkBuild")
            wait_js(pg, "(!document.querySelector('#pkLast').hidden || !document.querySelector('#pkErr').hidden) && document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 120000)
            check(pg.is_hidden("#pkErr"), "パックができる(エラーが出ない): " + pg.inner_text("#pkErr"))
            check("音量:" in pg.inner_text("#toast"), "作ったあとの知らせに音量の結果(LUFS と %): " + pg.inner_text("#toast"))
            packdir = os.path.splitext(v1)[0] + "_pack"
            ip = read_pack_plan(os.path.join(packdir, "create_resolve_textplus_project.lua"))
            got = [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip.get("cuts", [])]
            names = sorted(os.path.relpath(os.path.join(r, n), packdir).replace(os.sep, "/") for r, _, ns in os.walk(packdir) for n in ns)
            check(names == sorted(["ResolveにText+スクリプトを登録.bat", "create_resolve_textplus_project.lua", "install_resolve_textplus_script.ps1",
                                   os.path.basename(v1), "textplus-template.drb"]),
                  "パックは最小限(動画は直下・Lua・雛形・登録用の ps1/bat。EDL・SRT・cut-plan.json・.json・友人へ.txt は入れない): %s" % names)
            check(got == clips, "パックの区間 = カットのタブの区間(元の動画の 60fps のフレームのまま・短い区間も捨てない): %s" % got)
            check(ip.get("target") == {"fps": 30, "width": 1080, "height": 1920} and len(ip.get("captions", [])) == 3, "置き先 30fps・縦、字幕 3件: %s" % ip.get("target"))
            check("兎田ぺこらの色の文字(#7EC2FE)" in ip.get("style", {}).get("name", ""), "パックの字幕の文字はメンバーカラー: %s" % ip.get("style", {}).get("name"))
            fills = [c.get("fill") for c in ip.get("captions", [])]
            check(fills[0] == [1.0, 0.5608, 0.8745, 1.0] and fills[1] is None and fills[2] is None,
                  "話者「みこ」の字幕だけ さくらみこの色、ほかは配信者の色のまま(A-2): %s" % fills)
            check(pg.evaluate("JSON.parse(localStorage.getItem('tx.streamer.v1') || '{}')[%s]" % json.dumps(tid)) == "ぺこら", "配信者の名前は文書ごとに覚える")
            # 1 文字起こし の映像の上の字幕も、話者「みこ」の行は さくらみこの色・ほかは配信者(ぺこら)の色(パックと同じ規則)
            pg.keyboard.press("Alt+1")
            wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
            cap_color = "getComputedStyle(document.querySelector('#playerCaption')).color"
            if pg.is_visible("#menuScrim"):
                pg.click("#menuScrim")   # 1600px 未満では左のメニューが本文の上に重なって開いている(B-7)ので閉じる
            pick = lambda i: pg.locator("#segs .seg").nth(i).locator("textarea").first.click()   # 行を選ぶ(止まっているときは選んだ行が字幕に出る)
            pick(0)
            check(wait_js(pg, "%s === 'rgb(255, 143, 223)'" % cap_color, 10000), "映像の上の字幕: 話者「みこ」の行は さくらみこの色: %s" % pg.evaluate(cap_color))
            pick(2)
            check(wait_js(pg, "%s === 'rgb(126, 194, 254)'" % cap_color, 5000), "話者の無い行は配信者の色のまま: %s" % pg.evaluate(cap_color))
            line = "getComputedStyle(document.querySelectorAll('#segs .seg')[0]).getPropertyValue('--sp').trim().toLowerCase()"
            check(pg.evaluate(line) == "#ff8fdf", "行の左端の線も さくらみこの色(話者の色は1つの関数。段2): %s" % pg.evaluate(line))
            # スイッチ(編集の設定 speakerColors。以前はこのブラウザの tx.pk.speakerColors)を切ると、全部の場所から消え、設定に残る
            pg.keyboard.press("Escape")          # 行の文字の入力中の Alt+数字 は話者なので、タブは押して戻る
            pg.click("[data-edtab=pack]")
            wait_js(pg, "document.querySelector('[data-edtab=pack]').getAttribute('aria-selected') === 'true'")
            pg.uncheck("#pkSpk")
            check(wait_js(pg, "%s !== 'rgb(255, 143, 223)'" % phone, 5000), "切ると字幕の見本もメンバーの色ではなくなる")
            deadline = time.time() + 10
            while time.time() < deadline and srv.get("/api/settings").get("speakerColors") is not False:
                time.sleep(0.2)
            check(srv.get("/api/settings").get("speakerColors") is False, "スイッチは編集の設定(サーバー)に残る(まとめて実行も同じ値を読む)")
            pg.click("[data-edtab=tx]")
            wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
            pick(0)
            check(wait_js(pg, "%s === 'rgb(126, 194, 254)'" % cap_color, 5000), "切っていれば、映像の上の字幕でも出さない(配信者の色)")
            check(pg.evaluate(line) != "#ff8fdf", "行の左端の線も自動の色に戻る: %s" % pg.evaluate(line))
            pg.keyboard.press("Escape")
            pg.click("[data-edtab=pack]")
            wait_js(pg, "document.querySelector('[data-edtab=pack]').getAttribute('aria-selected') === 'true'")
            pg.check("#pkSpk")
            pg.click("[data-edtab=tx]")
            wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
            pg.keyboard.press("Escape")
            pg.click("[data-edtab=pack]")
            wait_js(pg, "document.querySelector('[data-edtab=pack]').getAttribute('aria-selected') === 'true'")
            e = srv.get("/api/edit?id=" + tid)
            check(e["edit"]["packRev"] == e["rev"] == 1 and os.path.normcase(e["edit"]["pack"]["dir"]) == os.path.normcase(packdir) and not e["packStale"],
                  "作った記録(packRev = 作ったときのカットの rev・出力フォルダ)")
            # 「予備も入れる」→ EDL・予備の手順書・SRT も(上書きの確認のあと)
            pg.click("#pkSettingsBtn")
            pg.wait_for_selector("#pkBackup", state="visible")
            pg.check("#pkBackup")
            pg.click("#pkSettingsClose")
            wait_js(pg, "document.querySelector('#pkSettingsDrawer').hidden === true")
            pg.click("#pkBuild")
            wait_js(pg, "document.querySelector('#dlgOverwrite').open", 20000)
            pg.click("#owOk")
            wait_js(pg, "document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled && document.querySelector('#pkLastPill').textContent === '前回のパック'", 120000)
            names2 = set(os.listdir(packdir))
            stem = os.path.splitext(os.path.basename(v1))[0]
            check({stem + ".edl", stem + "_cut.srt", "予備_EDLで開く手順.txt"} <= names2 and "cut-plan.json" not in names2,
                  "「予備も入れる」で EDL・予備_EDLで開く手順.txt・SRT も入る: %s" % sorted(names2))
            pg.click("#pkSettingsBtn")
            pg.wait_for_selector("#pkBackup", state="visible")
            pg.uncheck("#pkBackup")
            # 作っている途中の「中止」(粗編集の動画も作る。間に合わず終わってしまったときは、そのことを出す)
            pg.check("#pkRender")
            pg.click("#pkSettingsClose")
            wait_js(pg, "document.querySelector('#pkSettingsDrawer').hidden === true")
            pg.click("#pkBuild")
            wait_js(pg, "document.querySelector('#dlgOverwrite').open", 20000)
            pg.click("#owOk")
            errors[:] = [e for e in errors if "409" not in e]   # 前のパックがあるときの 409(上書きの確認)はブラウザがエラーとして記録する(想定どおり)
            wait_js(pg, "!document.querySelector('#pkJob').hidden || !document.querySelector('#pkBuild').disabled", 20000)
            if pg.is_visible("#pkJob [data-act=pkcancel]"):
                pg.click("#pkJob [data-act=pkcancel]")
                wait_js(pg, "document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 60000)
                t = pg.inner_text("#toast")
                check("中止" in t or "パックを作りました" in t, "作っている途中の「中止」: %s" % t)
            else:
                check(True, "(中止を押す前に作り終わった)")
            pg.click("#pkSettingsBtn")
            pg.wait_for_selector("#pkRender", state="visible")
            pg.uncheck("#pkRender")
            pg.click("#pkSettingsClose")
            wait_js(pg, "document.querySelector('#pkSettingsDrawer').hidden === true")
            # 文字起こしの無い動画: Text+ なしのパック
            pg.click("[data-strip=start]")
            pg.click("#tabFile")
            pg.fill("#srcPath", v2)
            pg.click("#btnOpenVideo")
            wait_js(pg, "document.querySelector('#docTitle').value === '字幕なし'", 15000)
            pg.keyboard.press("Alt+3")
            wait_js(pg, "document.querySelector('#pkCount').textContent === '1' && !document.querySelector('#pkBuild').disabled", 30000)
            check("Text+ は作りません" in pg.inner_text("#pkBuildHint") and pg.inner_text("#pkCaps") == "0", "字幕が無いときは Text+ を作らないと知らせる: " + pg.inner_text("#pkBuildHint"))
            pg.click("#pkBuild")
            wait_js(pg, "!document.querySelector('#pkLast').hidden && document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 120000)
            pd2 = os.path.splitext(v2)[0] + "_pack"
            files = sorted(os.listdir(pd2))
            check(files == sorted(["字幕なし.edl", "字幕なし.webm"]), "文字起こしの無い動画のパック: EDL・元の動画のコピー(Text+ なし。cut-plan.json・友人へ.txt は入れない): %s" % files)
            check(pg.is_disabled("#pkBackup") and pg.is_checked("#pkBackup"), "字幕が無いパックでは「予備も入れる」は選べない(EDL が本体)")

            # ---- 選んだ文書をまとめて「文字起こし → パック」(12 ⑦(b)。入口の /api/autorun/start-docs)
            v3 = make_video(os.path.join(srv.media, "まとめて.webm"), sec=6, fps=30)
            tid3 = srv.call("POST", "/api/open-video", {"path": v3})["id"]   # 行の無い文書(文字起こしせずに開いた)
            pg.reload()
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            pg.keyboard.press("Alt+1")
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pg.click("[data-side-tab=files]")
            check(pg.is_visible("#txBatchBox"), "入口から開くと、履歴に「選んで、まとめて実行」が出る")
            pg.check("#txPick")
            pg.select_option("#txGroup", "none")
            pg.fill("#txSearch", "まとめて")
            pg.locator("#txList .txi").filter(has_text="まとめて").locator(".txi-pick").check()
            check("1 本を選んでいます" in pg.inner_text("#txPickN") and pg.is_enabled("#txBatchGo"), "文書を選ぶと、まとめて実行を押せる")
            pg.click("#txBatchGo")
            wait_js(pg, "[...document.querySelectorAll('#txRuns .tt-run .pill')].some(p => p.textContent === '済み')", 120000)   # 実行の札(段の「済み」ではなく)。状態の言葉は共通(段4: 完了 → 済み)
            run_txt = pg.inner_text("#txRuns")
            check("文字起こし: 済" in run_txt and "Resolve パック: 済" in run_txt, "行の無い文書を、文字起こし → パックまで進める: %s" % run_txt[:160])
            d3 = srv.get("/api/transcript?id=" + tid3)
            check(len(d3["segments"]) > 0 and os.path.isfile(os.path.join(os.path.splitext(v3)[0] + "_pack", "create_resolve_textplus_project.lua")),
                  "同じ文書に文字起こしが入り(intoDoc)、動画の隣にパックができる")
            wait_js(pg, "/パック済み/.test(document.querySelector('#txList').textContent)", 15000)
            check(True, "終わると一覧が「パック済み」になる")
            pg.uncheck("#txPick")
            pg.fill("#txSearch", "")

            # ---- 今の文書を最後まで(題名の行の「まとめて実行 ▾」。docs/followup-2026-09-27.md の 3)
            v4 = make_video(os.path.join(srv.media, "今の文書.webm"), sec=6, fps=30)
            tid4 = srv.call("POST", "/api/open-video", {"path": v4})["id"]
            pg.reload()
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pg.click("[data-side-tab=files]")
            pg.select_option("#txGroup", "none")
            pg.fill("#txSearch", "今の文書")
            pg.locator("#txList .txi").filter(has_text="今の文書").first.click()
            wait_js(pg, "document.querySelector('#docTitle').value === '今の文書'", 15000)
            check(pg.is_visible("#docAuto"), "入口から開くと、題名の行に「まとめて実行」が出る")
            pg.click("#docAuto summary")
            pg.fill("#docAutoWho", "ぺこら")
            wait_js(pg, "document.querySelector('#docAutoWho').dataset.color === '#7EC2FE'", 10000)
            pg.click("#docAutoGo")
            wait_js(pg, "/済み|失敗/.test(document.querySelector('#pillAuto').textContent)", 120000)
            check("済み" in pg.inner_text("#pillAuto"), "題名の行の札に進み具合が出て、済みになる: %s" % pg.inner_text("#pillAuto"))
            lua4 = os.path.join(os.path.splitext(v4)[0] + "_pack", "create_resolve_textplus_project.lua")
            check(os.path.isfile(lua4) and len(srv.get("/api/transcript?id=" + tid4)["segments"]) > 0,
                  "今の文書を 文字起こし → パックまで進める")
            with open(lua4, encoding="utf-8") as f:
                check("兎田ぺこらの色の文字" in f.read(), "題名の行のまとめて実行でも、配信者の色がパックの字幕に入る")

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
