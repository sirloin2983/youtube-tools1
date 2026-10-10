#!/usr/bin/env python3
"""「編集」E4 パックのタブの確認(docs/design/edit-tool-design.md の 3・5・7)。入口に取り込んだ形(パックは cut2resolve の api/build)。

- カット(手で決めた区間。60fps の元の動画)のとおりにパックができる(Lua に埋め込んだ区間 = 編集の内容のフレーム)
- パックは最小限(④): 動画(直下)・Lua・雛形・登録用の ps1/bat だけ(手順書は画面の「Resolve での手順を見る」)。「予備も入れる」で EDL・予備の手順書・SRT
- 作る前の注意: とても短い区間・60fps の古い動画を 30fps のプロジェクトへ(Q1: 30fps の素材は fps の選択を出さず 30 固定)
- 作ったら「前回のパック」と packRev(一覧の API)
- 文字起こしの無い動画: Text+ なし(EDL と元の動画のコピー)のパック
- 作っている途中の「中止」

    python e2e_edit_pack.py
"""
import json
import os
import re
import sys
import time
import types
import zipfile

from playwright.sync_api import sync_playwright

from e2e_edit_common import wait_url_doc, Checks, Server, make_video, open_doc, read_pack_plan, wait_js

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
            cx = types.SimpleNamespace(**locals())   # 場面の関数(下の _scene_*)へ渡す値。場面で作って、あとの場面で使う値は場面が cx に戻す
            _scene_frame_step(cx)
            _scene_settings_drawer(cx)
            _scene_estimate(cx)
            _scene_thumb(cx)
            _scene_streamer_build(cx)
            _scene_deliver_diff(cx)
            _scene_sub_nosub_read(cx)
            _scene_backup_cancel_summary(cx)
            _scene_no_caption_30fps(cx)
            _scene_autorun(cx)

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


def _scene_frame_step(cx):
    """3-4: 1 文字起こし・2 カット の「1コマ」(, .)は素材の fps(60fps = 1/60 秒)"""
    check, pg = cx.check, cx.pg
    # ---- 段3 3-4(監査 15): 1 文字起こし の「1コマ」(, .)は素材の fps(60fps = 1/60 秒)。フレームの境目にそろい、2 カット と同じ位置に止まる
    pg.keyboard.press("Alt+1")
    wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'", 5000)
    if not pg.evaluate("document.querySelector('.app').classList.contains('menu-closed')"):
        pg.click("#menuScrim")   # 重ねて開いたメニューがあるとキーが効かない(3-1)
    ptime = "document.querySelector('#player').currentTime"
    wait_js(pg, "document.querySelector('#player').readyState >= 1", 15000)
    pg.evaluate("(() => { const p = document.querySelector('#player'); p.pause(); p.currentTime = 2; })()")
    wait_js(pg, "Math.abs(%s - 2) < 0.001" % ptime, 5000)
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Period")
    wait_js(pg, "%s > 2.001" % ptime, 3000)
    t1 = pg.evaluate(ptime)
    check(abs(t1 - (121 / FPS + 0.0005)) < 0.0003, "3-4: 1 文字起こし で . を1回 = 1/60 秒(121 コマ目の境目): %.5f" % t1)
    for _ in range(3):
        pg.keyboard.press("Period")
    pg.keyboard.press("Comma")
    t3 = pg.evaluate(ptime)
    check(abs(t3 - (123 / FPS + 0.0005)) < 0.0003, "3-4: . 3回・, 1回 で 123 コマ目(押し続けてもずれない): %.5f" % t3)
    check(pg.evaluate("document.querySelector('#player').paused"), "3-4: 1コマの移動では止まっている(2 カット と同じ)")
    pg.keyboard.press("Alt+2")
    wait_js(pg, "document.querySelectorAll('#tlVideo .tt-k').length > 0 && document.querySelector('#cutPlayer').readyState >= 1", 20000)
    wait_js(pg, "Math.abs(document.querySelector('#cutPlayer').currentTime - %s) < 0.01" % t3, 5000)
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Period")
    wait_js(pg, "document.querySelector('#cutPlayer').currentTime > %s" % (t3 + 0.001), 3000)
    tc = pg.evaluate("document.querySelector('#cutPlayer').currentTime")
    check(abs(tc - (124 / FPS + 0.0005)) < 0.0003, "3-4: 2 カット で続けて . = 124 コマ目(同じ1コマ): %.5f" % tc)
    pg.keyboard.press("Alt+2")
    wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'", 5000)


def _scene_settings_drawer(cx):
    """設定の引き出し: fps の選択と注意・行の後の余白・開始タイムコード・音量・引き出しを開いたままのタブの移動"""
    check, pg, srv = cx.check, cx.pg, cx.srv
    # 段3: 詳しい設定(fps・大きさ・入れるもの・出力先)は「設定を変える」で開く右の欄
    check("30fps" in pg.inner_text("#pkSummaryText"), "前回の設定の要約が出る(既定は 30fps): " + pg.inner_text("#pkSummaryText"))
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#uiSettingsDrawer:not([hidden])", state="visible")
    # 60fps の古い素材(30fps でない入れ直し前の文書)なら、今までどおり選択と 60↔30 の注意が出る(Q1。30fps の素材は下で選択を出さないことを確かめる)
    check(pg.is_visible("#pkFpsRow") and pg.is_hidden("#pkFpsFixedRow") and pg.evaluate("!document.querySelector('#pkFpsOtherFld').hidden"),"60fps の古い素材: フレームレートの選択(30/60・その他)が出る")
    check(pg.is_visible("#pkFpsWarn") and "60fps" in pg.inner_text("#pkFpsWarn"), "60fps の元の動画を 30fps のプロジェクトに入れるときの注意: " + pg.inner_text("#pkFpsWarn"))
    pg.click("#pkFps [data-v='60']")
    wait_js(pg, "document.querySelector('#pkFpsWarn').hidden", 3000)
    check(True, "置き先を 60fps にすると注意は消える")
    pg.click("#pkFps [data-v='30']")
    pg.click("#pkSize [data-v='1080x1920']")
    # ---- 段6 6-2(B-1): ⚙ の「パック」の「行の後の余白」→ 設定 rowEdge.padAfter に保存。手で直したカットには効かない(案内)。要約には既定と違うときだけ
    check(pg.input_value("#pkPadAfter") == "0.2", "行の後の余白の既定は 0.2 秒: " + pg.input_value("#pkPadAfter"))
    pg.fill("#pkPadAfter", "0.5")
    pg.press("#pkPadAfter", "Tab")
    deadline = time.time() + 10
    while time.time() < deadline and (srv.get("/api/settings").get("rowEdge") or {}).get("padAfter") != 0.5:
        time.sleep(0.2)
    check((srv.get("/api/settings").get("rowEdge") or {}).get("padAfter") == 0.5, "6-2: 設定 rowEdge.padAfter に保存される: %s" % srv.get("/api/settings").get("rowEdge"))
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('行の後の余白 0.5秒') >= 0", 5000), "要約に「行の後の余白 0.5秒」(既定と違うときだけ): " + pg.inner_text("#pkSummaryText"))
    check("手で直したカットには効きません" in pg.text_content("#pkPadAfterNote"), "手で決めたカットの文書では、効かないと案内する: " + pg.text_content("#pkPadAfterNote"))
    pg.fill("#pkPadAfter", "0.2")
    pg.press("#pkPadAfter", "Tab")
    deadline = time.time() + 10
    while time.time() < deadline and (srv.get("/api/settings").get("rowEdge") or {}).get("padAfter") != 0.2:
        time.sleep(0.2)
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('行の後の余白') < 0", 5000), "既定に戻すと要約から消える")
    # パックの音量(2026-09-29): 「音量を % で決める」を選ぶと % の欄が出て、編集の設定(送ったキーだけ)に残る。既定は 0.26.1(2026-10-01)から「% で決める・30%」(以前は -14 LUFS)
    check(pg.input_value("#pkLoud") == "0" and pg.is_visible("#pkVolBox") and pg.input_value("#pkVol") == "30", "音量の既定は「%% で決める」・30%%(0.26.1): %s / %s" % (pg.input_value("#pkLoud"), pg.input_value("#pkVol")))
    pg.select_option("#pkLoud", "0")
    wait_js(pg, "!document.querySelector('#pkVolBox').hidden", 5000)
    pg.fill("#pkVol", "70"); pg.press("#pkVol", "Tab")
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('音量 70%') >= 0", 5000), "要約に「音量 70%」: " + pg.inner_text("#pkSummaryText"))
    for _ in range(50):   # 保存(api/settings/patch)は要約の描き直しより少し遅れることがあるので待つ
        st = srv.get("/api/settings")
        if (st.get("packLoudness"), st.get("packVolume")) == (0, 70):
            break
        time.sleep(0.1)
    check((st.get("packLoudness"), st.get("packVolume")) == (0, 70), "編集の設定に残る: %s" % ((st.get("packLoudness"), st.get("packVolume")),))
    pg.select_option("#pkLoud", "-14")
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('音量 -14 LUFS') >= 0", 5000), "LUFS に戻すと要約も戻る")
    # 監査01(段1): 引き出しを開いたまま Alt+1 → タブは 2 カット のまま・引き出しも開いたまま(ダイアログと同じ扱い)
    pg.keyboard.press("Alt+1")
    pg.wait_for_timeout(150)
    check(pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true" and pg.is_visible("#uiSettingsDrawer"),
          "パックの設定(⚙)を開いたまま Alt+1 を押しても、タブは 2 カット のまま・引き出しも開いたまま")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    # 0.62.0: パックの設定は ⚙ の設定の引き出し。開いたまま # を変えて(戻る・# のリンクと同じ)タブを移ると、以前のパックの引き出しと同じく閉じ、裏の inert を残さない
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#uiSettingsDrawer:not([hidden])", state="visible")
    check(pg.evaluate("!!document.querySelector('[inert]')"), "(前提)⚙ の設定は modal で裏が inert")
    check(pg.evaluate("document.querySelector('#edSetPack').getBoundingClientRect().top < window.innerHeight"), "「設定を変える」で ⚙ の「パック」の節が見える所に出る")
    pg.evaluate("location.hash = '#tx'")
    check(wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true' && document.querySelector('#uiSettingsDrawer').hidden && !document.querySelector('[inert]') && !document.querySelector('.ui-drawer-scrim')", 5000),
          "開いたまま # で 1 文字起こし へ移ると、⚙ の引き出しが閉じて inert・幕が残らない")
    check(pg.evaluate("document.activeElement === document.querySelector('[data-edtab=tx]')"), "フォーカスは移った先のタブのボタン: %s" % pg.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.outerHTML.slice(0, 80))"))
    pg.click("[data-edtab=cut]")   # 裏が操作できる(クリックが通る)ことの確かめを兼ねる
    check(wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'", 3000), "ヘッダーのタブのボタンが押せる(操作不能になっていない)")
    check("縦 1080" in pg.inner_text("#pkSummaryText"), "設定を変えると要約も変わる: " + pg.inner_text("#pkSummaryText"))
    # ---- 段9-5: 開始タイムコードに ; を入れるとドロップフレームの注意が欄の下に出る(消せば消える)。0.62.0: 作るときの値なのでカードの「詳しく」(⚙ ではない)
    pg.evaluate("document.querySelector('#pkMore').open = true")
    for _id in ("pkSrcTc", "pkRecTc"):
        check(pg.evaluate("document.querySelector('#%sHint').hidden" % _id), "9-5: %s の注意は最初は出ていない" % _id)
        pg.fill("#" + _id, "01:00:00;00")
        check(wait_js(pg, "!document.querySelector('#%sHint').hidden" % _id, 2000), "9-5: %s に ; を入れると注意が出る" % _id)
        check("ノンドロップとして扱います" in pg.text_content("#" + _id + "Hint"), "9-5: 注意の文: " + pg.text_content("#" + _id + "Hint"))
        pg.fill("#" + _id, "01:00:00:00")
        check(wait_js(pg, "document.querySelector('#%sHint').hidden" % _id, 2000), "9-5: : に直すと注意は消える")
        pg.fill("#" + _id, "")
    pg.evaluate("document.querySelector('#pkMore').open = false")


def _scene_estimate(cx):
    """4-1: 置き先を変えると見積もりを出し直す・見積もりの失敗と「もう一度」"""
    check, errors, pg = cx.check, cx.errors, cx.pg
    # ---- 段4 4-1(監査 07): 置き先(縦横 = 字幕の1段の文字数)を変えると、タブを移らずに見積もりを出し直す(字幕数が「…」のままにならない・注意が戻る)
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#uiSettingsDrawer:not([hidden])", state="visible")
    pg.click("#pkSize [data-v='1920x1080']")
    check(wait_js(pg, "document.querySelector('#pkCaps').textContent === '3' && document.querySelector('#pkSummaryText').textContent.indexOf('横 1920') >= 0 && !document.querySelector('#pkWarn').hidden && !document.querySelector('#pkWarn').classList.contains('old') && document.querySelector('#pkPvState').hidden", 15000),
          "4-1: 縦 → 横 で字幕数が数字に戻り、注意も新しい見積もりで出る: " + pg.inner_text("#pkCaps") + " / " + pg.inner_text("#pkWarn"))
    # 見積もりの API を止めると、失敗の理由と「もう一度」が出て、前の注意は薄く残る(黙って「…」のままにしない)
    pg.route("**/api/edit/preview", lambda r: r.fulfill(status=500, content_type="application/json", body='{"error": "x", "message": "わざと失敗"}'))
    pg.click("#pkSize [data-v='1080x1920']")
    check(wait_js(pg, "!document.querySelector('#pkPvState').hidden && document.querySelector('#pkPvState').textContent.indexOf('見積もりを出せませんでした') >= 0 && !document.querySelector('#pkPvRetry').hidden && !document.querySelector('#pkWarn').hidden && document.querySelector('#pkWarn').classList.contains('old')", 15000),
          "4-1: 見積もりの失敗が見える(理由・「もう一度」・前の設定での注意は薄く残す): " + pg.inner_text("#pkPvState"))
    check(pg.inner_text("#pkCaps") == "…", "失敗している間は字幕数は「…」: " + pg.inner_text("#pkCaps"))
    pg.unroute("**/api/edit/preview")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    check(pg.inner_text("#pkPvState").find("見積もりを出せませんでした") >= 0, "(前提)引き出しを閉じても失敗のまま(同じ設定では自動で出し直さない)")
    pg.click("#pkPvRetry")
    check(wait_js(pg, "document.querySelector('#pkPvState').hidden && document.querySelector('#pkCaps').textContent === '3' && !document.querySelector('#pkWarn').classList.contains('old')", 15000), "4-1: 「もう一度」で出し直して最新になる")
    errors[:] = [e for e in errors if "500" not in e and "preview" not in e]   # わざと失敗させた 500 はブラウザがエラーとして記録する(想定どおり)


def _scene_thumb(cx):
    """サムネの案(提案 P5。0.64.0): カードが出る → 切り取りを選ぶと設定に覚える → 作る → 画像が出る・作業用 に png と json(案 6 つ・選んだ切り取り)"""
    check, pg, srv = cx.check, cx.pg, cx.srv
    check(wait_js(pg, "!document.querySelector('#thCard').hidden && !document.querySelector('#thGo').disabled"
                      " && document.querySelector('#thMsg').textContent === 'まだ作っていません'", 15000),
          "サムネの案のカードが出て、まだ作っていない: %s" % pg.inner_text("#thMsg"))
    pg.select_option("#thCrop", "center")
    end = time.time() + 10
    while time.time() < end and srv.get("/api/settings").get("thumbCrop") != "center":
        time.sleep(0.1)
    check(srv.get("/api/settings").get("thumbCrop") == "center", "切り取りを選ぶと設定 thumbCrop に覚える")
    pg.click("#thGo")
    check(wait_js(pg, "(() => { const i = document.querySelector('#thImg'); return !document.querySelector('#thLink').hidden && i.complete && i.naturalWidth > 500"
                      " && document.querySelector('#thGo').textContent === 'サムネの案を作り直す'; })()", 90000),
          "作ると画像が出て、ボタンは「作り直す」に: %s" % pg.inner_text("#thMsg"))
    png = os.path.join(srv.media, "作業用", "パックの確認_thumb-ideas.png")
    rec = {}
    if os.path.isfile(os.path.splitext(png)[0] + ".json"):
        with open(os.path.splitext(png)[0] + ".json", encoding="utf-8") as f:
            rec = json.load(f)
    check(os.path.isfile(png) and [c.get("crop") for c in rec.get("cards", [])] == ["center"] * 6,
          "動画のフォルダの 作業用 に png と json(案 6 つ・切り取りは全部中央): %s" % [c.get("crop") for c in rec.get("cards", [])])
    check("作業用" in pg.inner_text("#thMsg"), "作った時刻と置き場所を出す: " + pg.inner_text("#thMsg"))


def _scene_streamer_build(cx):
    """配信者の名前とメンバーカラー・話者の色・パックを作る(最小限)・映像の上の字幕の色・作った記録"""
    check, clips, pg, srv, tid, v1 = cx.check, cx.clips, cx.pg, cx.srv, cx.tid, cx.v1
    # 配信者の名前(字幕の色。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4): 候補・色の見本・字幕の見本の色。パックの Lua の見た目もその色(pkWho は主画面にいつも見える)
    # 0.62.0: 配信者の欄は見せない(文書に覚えている名前をそのまま使う)。題名の行の「まとめて実行 ▾」の配信者の欄で直した形 = 隠した欄に名前を入れて change
    pg.evaluate("const i = document.querySelector('#pkWho'); i.value = 'ぺこら'; i.dispatchEvent(new Event('change'))")
    wait_js(pg, "document.querySelector('#pkWho').dataset.color === '#65BAEA'", 10000)
    check("兎田ぺこら" in pg.text_content("#pkWhoNote") and "兎田ぺこらの色の文字" in pg.inner_text("#pkLookName") and
          pg.evaluate("getComputedStyle(document.querySelectorAll('#pkSamples .tt-pk-cap')[1]).color") == "rgb(101, 186, 234)",   # 2行目(話者なし)の見本。1行目は話者「みこ」の色(段2)
          "配信者の名前 → メンバーカラーの見本・字幕の見本の色(配信者の 1 行): %s" % pg.text_content("#pkWhoNote"))
    check(pg.evaluate("document.querySelectorAll('#ui-streamer-list option').length") > 50, "名前の候補(ホロカラーの一覧)")
    check(wait_js(pg, "!document.querySelector('#pkSummarySw').hidden && getComputedStyle(document.querySelector('#pkSummarySw')).backgroundColor === 'rgb(101, 186, 234)'", 5000),
          "「前回の設定」の要約にも配信者の色の丸が出る(pkWho の色と同じ)")
    # A-2: 話者の名前がメンバーと合えば、その話者の字幕をその色に(既定オン)。どの話者が何色かを見せる
    check(pg.evaluate("document.querySelector('#pkSpk').checked"), "「話者の名前がメンバーと合えば…」は既定でオン(⚙ の「パック」の節)")
    wait_js(pg, "document.querySelector('#pkSpkList').textContent.indexOf('さくらみこの色') >= 0", 10000)
    check(True, "話者「みこ」→ さくらみこの色、と見せる: " + pg.inner_text("#pkSpkList"))
    phone = "getComputedStyle(document.querySelector('#pkPhoneCap')).color"
    check(wait_js(pg, "%s === 'rgb(254, 75, 116)'" % phone, 10000), "字幕の見本(電話の形)も、1行目の話者「みこ」の色(GPT-12・段2): %s" % pg.evaluate(phone))
    check(wait_js(pg, "getComputedStyle(document.querySelectorAll('#pkSamples .tt-pk-cap')[0]).color === 'rgb(254, 75, 116)' && document.querySelector('#pkCaps').textContent === '3'", 10000),
          "4-5(監査 12): 見積もりができたあとの見本の1つ目(話者「みこ」の字幕。sampleSpeakers = pack.py の cue_speakers)も さくらみこの色")
    # 段3: 設定の引き出しを開かずに(主画面だけで)「パックを作る」を1クリックで作れる(ワンクリック)
    check(pg.evaluate("document.querySelector('#uiSettingsDrawer').hidden") is True, "「作る」を押す前に、設定の引き出しは閉じている")
    pg.click("#pkBuild")
    wait_js(pg, "(!document.querySelector('#pkLast').hidden || !document.querySelector('#pkErr').hidden) && document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 120000)
    check(pg.is_hidden("#pkErr"), "パックができる(エラーが出ない): " + pg.inner_text("#pkErr"))
    check("音量:" in pg.inner_text("#toast"), "作ったあとの知らせに音量の結果(LUFS と %): " + pg.inner_text("#toast"))
    # 段7 E-11・E-15: 次の一手 = 知らせに [フォルダを開く]・フォーカスは「前回のパック」の「フォルダを開く」・ボタンは「作り直す(上書き)」
    check(pg.evaluate("[...document.querySelectorAll('#toast .ui-toast')].some(t => /パックを作りました/.test(t.textContent) && [...t.querySelectorAll('.ui-toast-act')].some(b => b.textContent === 'フォルダを開く'))"),
          "作り終えた知らせに [フォルダを開く](段7 E-11)")
    check(wait_js(pg, "document.activeElement === document.querySelector('#pkOpen')", 5000), "作り終えたらフォーカスは「フォルダを開く」へ(段7 E-11)")
    check(pg.inner_text("#pkBuild") == "同じ内容で作り直す" and "primary" not in pg.get_attribute("#pkBuild", "class") and "primary" in pg.get_attribute("#pkReadme", "class"),
          "作ったばかり(作り直しが要らない)なら、ボタンは普通の「同じ内容で作り直す」・主は「Resolve での手順を見る」(UI の見直し S2): " + pg.inner_text("#pkBuild"))
    packdir = os.path.splitext(v1)[0] + "_pack"
    ip = read_pack_plan(os.path.join(packdir, "create_resolve_textplus_project.lua"))
    got = [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip.get("cuts", [])]
    names = sorted(os.path.relpath(os.path.join(r, n), packdir).replace(os.sep, "/") for r, _, ns in os.walk(packdir) for n in ns)
    check(names == sorted(["ResolveにText+スクリプトを登録.bat", "create_resolve_textplus_project.lua", "install_resolve_textplus_script.ps1",
                           os.path.basename(v1), "textplus-template.drb", "pack.key.json"]),
          "パックは最小限(動画は直下・Lua・雛形・登録用の ps1/bat。EDL・SRT・cut-plan.json・.json・友人へ.txt は入れない。RS6 の鍵 pack.key.json だけ増えた): %s" % names)
    check(got == clips, "パックの区間 = カットのタブの区間(元の動画の 60fps のフレームのまま・短い区間も捨てない): %s" % got)
    check(ip.get("target") == {"fps": 30, "width": 1080, "height": 1920} and len(ip.get("captions", [])) == 3, "置き先 30fps・縦、字幕 3件: %s" % ip.get("target"))
    check("兎田ぺこらの色の文字(#65BAEA)" in ip.get("style", {}).get("name", ""), "パックの字幕の文字はメンバーカラー: %s" % ip.get("style", {}).get("name"))
    fills = [c.get("fill") for c in ip.get("captions", [])]
    check(fills[0] == [0.9961, 0.2941, 0.4549, 1.0] and fills[1] is None and fills[2] is None,
          "話者「みこ」の字幕だけ さくらみこの色、ほかは配信者の色のまま(A-2): %s" % fills)
    check(pg.evaluate("UIKit.prefs.get(['streamer']).then(p => p.streamer.docs[%s])" % json.dumps(tid)) == "ぺこら",
          "配信者の名前は文書ごとに覚える(ホームの設定。段5。以前はこのブラウザの tx.streamer.v1)")
    # 1 文字起こし の映像の上の字幕も、話者「みこ」の行は さくらみこの色・ほかは配信者(ぺこら)の色(パックと同じ規則)
    pg.keyboard.press("Alt+1")
    wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
    cap_color = "getComputedStyle(document.querySelector('#playerCaption')).color"
    if pg.is_visible("#menuScrim"):
        pg.click("#menuScrim")   # 1600px 未満では左のメニューが本文の上に重なって開いている(B-7)ので閉じる
    pick = lambda i: pg.locator("#segs .seg").nth(i).locator("textarea").first.click()   # 行を選ぶ(止まっているときは選んだ行が字幕に出る)
    pick(0)
    check(wait_js(pg, "%s === 'rgb(254, 75, 116)'" % cap_color, 10000), "映像の上の字幕: 話者「みこ」の行は さくらみこの色: %s" % pg.evaluate(cap_color))
    pick(2)
    check(wait_js(pg, "%s === 'rgb(101, 186, 234)'" % cap_color, 5000), "話者の無い行は配信者の色のまま: %s" % pg.evaluate(cap_color))
    line = "getComputedStyle(document.querySelectorAll('#segs .seg')[0]).getPropertyValue('--sp').trim().toLowerCase()"
    check(pg.evaluate(line) == "#fe4b74", "行の左端の線も さくらみこの色(話者の色は1つの関数。段2): %s" % pg.evaluate(line))
    # スイッチ(編集の設定 speakerColors。以前はこのブラウザの tx.pk.speakerColors)を切ると、全部の場所から消え、設定に残る
    pg.keyboard.press("Escape")          # 行の文字の入力中の Alt+数字 は話者なので、タブは押して戻る
    pg.click("[data-edtab=cut]")
    wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'")
    pg.click("#pkSettingsBtn")   # 0.62.0: スイッチは ⚙ の「パック」の節
    pg.wait_for_selector("#pkSpk", state="visible")
    pg.uncheck("#pkSpk")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    check(wait_js(pg, "%s !== 'rgb(254, 75, 116)'" % phone, 5000), "切ると字幕の見本もメンバーの色ではなくなる")
    deadline = time.time() + 10
    while time.time() < deadline and srv.get("/api/settings").get("speakerColors") is not False:
        time.sleep(0.2)
    check(srv.get("/api/settings").get("speakerColors") is False, "スイッチは編集の設定(サーバー)に残る(まとめて実行も同じ値を読む)")
    pg.click("[data-edtab=tx]")
    wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
    pick(0)
    check(wait_js(pg, "%s === 'rgb(101, 186, 234)'" % cap_color, 5000), "切っていれば、映像の上の字幕でも出さない(配信者の色)")
    check(pg.evaluate(line) != "#fe4b74", "行の左端の線も自動の色に戻る: %s" % pg.evaluate(line))
    pg.keyboard.press("Escape")
    pg.click("[data-edtab=cut]")
    wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'")
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#pkSpk", state="visible")
    pg.check("#pkSpk")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    pg.click("[data-edtab=tx]")
    wait_js(pg, "document.querySelector('[data-edtab=tx]').getAttribute('aria-selected') === 'true'")
    pg.keyboard.press("Escape")
    pg.click("[data-edtab=cut]")
    wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'")
    e = srv.get("/api/edit?id=" + tid)
    check(e["edit"]["packRev"] == e["rev"] == 1 and os.path.normcase(e["edit"]["pack"]["dir"]) == os.path.normcase(packdir) and not e["packStale"],
          "作った記録(packRev = 作ったときのカットの rev・出力フォルダ)")
    # ---- 段4 4-3(監査 08): 作ったときの出力の設定を記録し、今の設定との違いを出す(ファイルは作ったときのまま、と書く)
    out = e["edit"]["pack"].get("output") or {}
    check(out.get("fps") == "30" and out.get("size") == "1080x1920" and out.get("streamer") == "ぺこら" and out.get("render") is False and out.get("loudness") == -14,
          "作った記録に出力の設定(output): %s" % out)
    check(pg.is_hidden("#pkLastDiff") and pg.inner_text("#pkLastPill") == "前回のパック", "設定が作ったときと同じなら、違いは出ない")
    cx.packdir, cx.phone = packdir, phone


def _scene_deliver_diff(cx):
    """友人へ届ける・前回のパックとの設定の違い・zip に渡らない設定"""
    check, packdir, pg, srv = cx.check, cx.packdir, cx.pg, cx.srv
    # ---- 友人へ届ける(編集 0.42.0・入口の api/ytt/deliver → home/deliver.py): 依頼の受付のフォルダの 出力 に zip を置く
    check(pg.is_visible("#pkDeliver"), "入口から開くと「友人へ届ける」が出る")
    r = srv.call("POST", "/api/ytt/deliver", {"op": "start", "dir": packdir, "title": "x"})   # 画面から押すと 400 がコンソールのエラーに出るので API で
    check(r.get("error") == "bad_request" and "決まっていません" in r.get("message", ""), "受付のフォルダが無ければ断る: %s" % r)
    dbx = os.path.join(srv.tmp, "Dropbox")
    os.makedirs(dbx)
    r = srv.call("POST", "/api/ytt/prefs", {"op": "patch", "section": "intake", "value": {"folder": dbx}})
    check(r.get("ok"), "(準備)受付のフォルダを決める: %s" % r)
    pg.click("#pkDeliver")
    pg.wait_for_selector("dialog.ui-dialog[open]")
    pg.click("dialog.ui-dialog .ui-dlg-actions button:has-text('届ける')")
    check(wait_js(pg, "document.querySelector('#pkDeliverMsg').classList.contains('tt-pk-dl-ok')", 60000), "届けた: " + pg.inner_text("#pkDeliverMsg"))
    outs = os.listdir(os.path.join(dbx, "出力"))
    check(len(outs) == 1 and re.match(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}__.+\.zip$", outs[0]), "出力 に友人のアプリが読む名前の zip: %s" % outs)
    with zipfile.ZipFile(os.path.join(dbx, "出力", outs[0])) as z:
        names = [n.replace("\\", "/") for n in z.namelist()]
    check(names and all(n.startswith(os.path.basename(packdir) + "/") for n in names) and any(n.endswith(".webm") for n in names),
          "zip の中はパックのフォルダごと: %s" % names[:5])
    r = srv.call("POST", "/api/ytt/deliver", {"op": "start", "dir": srv.media, "title": "x"})
    check(r.get("error") == "bad_request", "パックではないフォルダは断る: %s" % r)
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#uiSettingsDrawer:not([hidden])", state="visible")
    pg.click("#pkFps [data-v='60']")
    check(wait_js(pg, "document.querySelector('#pkLastPill').textContent === '設定が違う' && document.querySelector('#pkLastDiff').textContent.indexOf('フレームレート: 30fps → 60fps') >= 0 && document.querySelector('#pkLastDiff').textContent.indexOf('作ったときのまま') >= 0", 10000),
          "4-3: 60fps に変えると「設定が違う」・違いの中身・ファイルは作ったときのまま: " + pg.inner_text("#pkLastDiff"))
    pg.check("#pkRender")
    check(wait_js(pg, "document.querySelector('#pkLastDiff').textContent.indexOf('粗編集の動画: なし → あり') >= 0", 10000), "粗編集の動画をオンにすると違いに足される: " + pg.inner_text("#pkLastDiff"))
    # ---- 4-4(監査 10): zip に渡らない設定を画面に書く(zip の中身は変えない。dev/tests/test_resolve_pack_contract.py の ZipSkipsContract が固定)
    check(wait_js(pg, "!document.querySelector('#pkZipWarn').hidden && document.querySelector('#pkZipWarn').textContent.indexOf('粗編集の動画') >= 0", 5000), "4-4: 粗編集オンのとき zip の横に「zip に入りません」: " + pg.text_content("#pkZipWarn"))
    check("粗編集の動画" in pg.text_content("#pkZipNote") and "zip には入りません" in pg.text_content("#pkZipNote"), "zip の説明に、渡らない設定が書いてある: " + pg.text_content("#pkZipNote"))
    pg.uncheck("#pkRender")
    pg.click("#pkFps [data-v='30']")
    check(wait_js(pg, "document.querySelector('#pkLastPill').textContent === '前回のパック' && document.querySelector('#pkLastDiff').hidden", 10000), "設定を戻すと違いが消える")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")


def _scene_sub_nosub_read(cx):
    """話者ごとの字幕の色・字幕に出さない行・読みにくい字幕"""
    check, pg, phone = cx.check, cx.pg, cx.phone
    # ---- 2026-10-05: 話者ごとの字幕の色(文書の話者の sub)と、字幕に出さない行(noSub)
    pg.evaluate("setSubColor(S.doc.speakers[0], '#123456'); markDirty(); onSpeakerColors();")
    check(wait_js(pg, "document.querySelector('#pkSpkList').textContent.indexOf('指定の色(#123456)') >= 0", 5000), "話者の欄: みこ → 指定の色: " + pg.inner_text("#pkSpkList"))
    check(wait_js(pg, "getComputedStyle(document.querySelector('#pkPhoneCap')).color === 'rgb(18, 52, 86)'", 10000), "字幕の見本も指定の色(メンバーの色より優先): %s" % pg.evaluate(phone))
    check(wait_js(pg, "document.querySelector('#pkLastDiff').textContent.indexOf('話者ごとの字幕の色: なし → みこ #123456') >= 0", 10000),
          "前回のパックとの違いに話者ごとの字幕の色: " + pg.inner_text("#pkLastDiff"))
    pg.evaluate("S.doc.segments[2].noSub = true; renderDoc(); markDirty();")
    check(wait_js(pg, "!document.querySelector('#pkNoSub').hidden && document.querySelector('#pkNoSub').textContent.indexOf('字幕に出さない行: 1 行') >= 0 && document.querySelector('#pkCaps').textContent === '2'", 20000),
          "これから作るパック: 字幕に出さない行 1 行・字幕は 1 つ減る(区間はそのまま): %s / 字幕 %s / 区間 %s" % (pg.text_content("#pkNoSub"), pg.inner_text("#pkCaps"), pg.inner_text("#pkCount")))
    check(pg.inner_text("#pkCount") == "3", "字幕に出さない行があっても残す区間は同じ")
    pg.evaluate("delete S.doc.segments[2].noSub; renderDoc(); markDirty();")
    check(wait_js(pg, "document.querySelector('#pkNoSub').hidden && document.querySelector('#pkCaps').textContent === '3'", 20000), "印を外すと字幕に戻る")
    # 読みにくい字幕(2026-10-05。画面の側で数える・0 なら出さない・パックは変えない)
    check(wait_js(pg, "!document.querySelector('#pkRead').hidden && document.querySelector('#pkRead').textContent.indexOf('読みにくい字幕: 1 行') >= 0", 20000),
          "これから作るパック: 読みにくい字幕 1 行(0.3 秒の「短い」): %s" % pg.text_content("#pkRead"))
    txts = pg.evaluate("S.doc.segments.map(g => g.text)")
    pg.evaluate("S.doc.segments[1].text = '短'; renderDoc(); markDirty();")   # 1 文字の行は数えない
    check(wait_js(pg, "document.querySelector('#pkRead').hidden", 20000), "読みにくい字幕が無ければ出さない: %s" % pg.text_content("#pkRead"))
    pg.evaluate("S.doc.segments[0].text = 'あ'.repeat(40); renderDoc(); markDirty();")   # 1.5 秒に 40 文字 = 速い
    check(wait_js(pg, "!document.querySelector('#pkRead').hidden && document.querySelector('#pkRead').textContent.indexOf('読みにくい字幕: 1 行') >= 0", 20000),
          "速い行も数える: %s" % pg.text_content("#pkRead"))
    pg.evaluate("S.doc.segments.forEach((g, i) => { g.text = %s[i]; }); renderDoc(); markDirty();" % json.dumps(txts))
    check(wait_js(pg, "document.querySelector('#pkRead').textContent.indexOf('読みにくい字幕: 1 行') >= 0", 20000), "戻すと 1 行")


def _scene_backup_cancel_summary(cx):
    """「予備も入れる」・作っている途中の「中止」・「前回の設定」の要約(再読み込みの前後)"""
    check, errors, packdir, pg, srv, tid, v1 = cx.check, cx.errors, cx.packdir, cx.pg, cx.srv, cx.tid, cx.v1
    # 「予備も入れる」→ EDL・予備の手順書・SRT も(前回と同じ場所への作り直しは、上書きの確認を出さない。段7 E-15)
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#pkBackup", state="visible")
    pg.check("#pkBackup")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    pg.click("#pkBuild")
    check(wait_js(pg, "document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled && document.querySelector('#pkLastPill').textContent === '前回のパック' && !document.querySelector('dialog.ui-dialog[open]')", 120000),
          "前回と同じ場所への作り直しは、上書きの確認を出さずに作る(段7 E-15)")
    # cut2resolve の案内(warningLevels が info。同じ動画のコピーを飛ばした)は知らせに積まず「前回のパック」の欄に(知らせが「中止」を隠していた)
    check("コピーを飛ばしました" in pg.inner_text("#pkLastNotes") and "コピーを飛ばしました" not in pg.inner_text("#toast") and "案内 1 件" in pg.inner_text("#toast"),
          "info の案内は知らせに積まず「前回のパック」の欄に: %s / %s" % (pg.inner_text("#pkLastNotes"), pg.inner_text("#toast")))
    names2 = set(os.listdir(packdir))
    stem = os.path.splitext(os.path.basename(v1))[0]
    check({stem + ".edl", stem + "_cut.srt", "予備_EDLで開く手順.txt"} <= names2 and "cut-plan.json" not in names2,
          "「予備も入れる」で EDL・予備_EDLで開く手順.txt・SRT も入る: %s" % sorted(names2))
    out2 = (srv.get("/api/edit?id=" + tid)["edit"]["pack"].get("output") or {})
    check(out2.get("speakerStyles") == {"みこ": {"color": "#123456"}}, "作った記録に話者ごとの字幕の色(speakerStyles): %s" % out2.get("speakerStyles"))
    fills2 = [c.get("fill") for c in read_pack_plan(os.path.join(packdir, "create_resolve_textplus_project.lua")).get("captions", [])]
    check(fills2 and fills2[0] == [0.0706, 0.2039, 0.3373, 1.0], "パックの字幕も指定の色(output.speakerStyles。cut2resolve が最優先にする): %s" % fills2[:1])
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#pkBackup", state="visible")
    pg.uncheck("#pkBackup")
    # 作っている途中の「中止」(粗編集の動画も作る。間に合わず終わってしまったときは、そのことを出す)
    pg.check("#pkRender")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    pg.click("#pkBuild")
    wait_js(pg, "document.querySelector('#pkBuild').disabled", 5000)   # 作り始めた(確認のダイアログが無くなったので、押した直後はまだ前の状態のことがある)
    wait_js(pg, "!document.querySelector('#pkJob').hidden || !document.querySelector('#pkBuild').disabled", 20000)
    if pg.is_visible("#pkJob [data-act=pkcancel]"):
        # 前のパックの完了の知らせ([フォルダを開く] つきで消えない)が下の中央に残っていると、Linux の字の高さでは [中止] に重なってクリックを遮る → 先に閉じる
        pg.evaluate("document.querySelectorAll('#toast .ui-toast-x').forEach(b => b.click())")
        pg.click("#pkJob [data-act=pkcancel]")
        wait_js(pg, "document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 60000)
        t = pg.inner_text("#toast")
        check("中止" in t or "パックを作りました" in t, "作っている途中の「中止」: %s" % t)
    else:
        check(True, "(中止を押す前に作り終わった)")
    errors[:] = [e for e in errors if "409" not in e]   # 前のパックがあるときの 409(同じ場所なら確認なしで force で作り直す)はブラウザがエラーとして記録する(想定どおり)
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#pkRender", state="visible")
    pg.uncheck("#pkRender")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    # ---- 段4 4-2(監査 09): 「前回の設定」の要約は覚えている物だけ(再読み込みの前後で同じ)。粗編集・予備は覚える、出力先は覚えない(作る場所の行で毎回どこかが分かる)
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#pkRender", state="visible")
    pg.check("#pkRender")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    pg.evaluate("document.querySelector('#pkMore').open = true")   # 0.62.0: 出力先は「パックを作る」の「詳しく」
    pg.fill("#pkDir", "C:\\tmp\\別の場所")
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('粗編集の動画つき') >= 0 && document.querySelector('#pkSummaryText').textContent.indexOf('出力先') < 0 && document.querySelector('#pkPlace').textContent.indexOf('別の場所') >= 0", 5000),
          "要約に粗編集の動画つき・出力先は要約に出さず「作る場所」の行に: " + pg.inner_text("#pkSummaryText") + " / " + pg.inner_text("#pkPlace"))
    deadline = time.time() + 10
    while time.time() < deadline and srv.get("/api/settings").get("packRender") is not True:
        time.sleep(0.2)
    check(srv.get("/api/settings").get("packRender") is True, "粗編集の動画つきは編集の設定(サーバー)に残る")
    pg.reload()
    wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
    wait_url_doc(pg)
    pg.keyboard.press("Alt+2")
    wait_js(pg, "document.querySelector('[data-edtab=cut]').getAttribute('aria-selected') === 'true'", 5000)
    check(wait_js(pg, "document.querySelector('#pkSummaryText').textContent.indexOf('粗編集の動画つき') >= 0 && document.querySelector('#pkRender').checked && document.querySelector('#pkDir').value === '' && document.querySelector('#pkPlace').textContent.indexOf('_pack') >= 0 && document.querySelector('#pkPlace').textContent.indexOf('別の場所') < 0", 15000),
          "再読み込みしても要約は同じ(粗編集つき・チェックも戻る)。出力先は空欄に戻り、作る場所は動画の隣: " + pg.inner_text("#pkSummaryText") + " / " + pg.inner_text("#pkPlace"))
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#pkRender", state="visible")
    pg.uncheck("#pkRender")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")


def _scene_no_caption_30fps(cx):
    """文字起こしの無い動画のパック・Q1: 30fps の素材は fps を選ばせない"""
    check, pg, srv, v2 = cx.check, cx.pg, cx.srv, cx.v2
    # 文字起こしの無い動画: Text+ なしのパック
    pg.click("[data-strip=start]")
    pg.click("#tabFile")
    pg.fill("#srcPath", v2)
    pg.click("#btnOpenVideo")
    wait_js(pg, "document.querySelector('#docTitle').value === '字幕なし'", 15000)
    pg.keyboard.press("Alt+2")
    wait_js(pg, "document.querySelector('#pkCount').textContent === '1' && !document.querySelector('#pkBuild').disabled", 30000)
    check("Text+ は作りません" in pg.inner_text("#pkBuildHint") and pg.inner_text("#pkCaps") == "0", "字幕が無いときは Text+ を作らないと知らせる: " + pg.inner_text("#pkBuildHint"))
    pg.click("#pkBuild")
    wait_js(pg, "!document.querySelector('#pkLast').hidden && document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 120000)
    pd2 = os.path.splitext(v2)[0] + "_pack"
    files = sorted(os.listdir(pd2))
    check(files == sorted(["字幕なし.edl", "字幕なし.webm", "pack.key.json"]), "文字起こしの無い動画のパック: EDL・元の動画のコピー(Text+ なし。cut-plan.json・友人へ.txt は入れない): %s" % files)
    check(pg.is_disabled("#pkBackup") and pg.is_checked("#pkBackup"), "字幕が無いパックでは「予備も入れる」は選べない(EDL が本体)")

    # ---- Q1: 素材が 30fps なら、プロジェクトの fps は 30 固定で選択を出さない(保存してある packFps = 60 は使わない・消さない)
    r = srv.call("POST", "/api/settings/patch", {"values": {"packFps": "60"}})
    check(srv.get("/api/settings").get("packFps") == "60", "(準備)保存してある設定を packFps = 60 にする: %s" % r)
    pg.reload()
    wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
    wait_url_doc(pg)
    pg.keyboard.press("Alt+2")
    wait_js(pg, "document.querySelector('#pkCount').textContent === '1' && !document.querySelector('#pkBuild').disabled", 30000)
    check("30fps" in pg.inner_text("#pkSummaryText") and "60fps" not in pg.inner_text("#pkSummaryText"), "30fps の素材: 設定が 60 でも要約は 30fps: " + pg.inner_text("#pkSummaryText"))
    pg.click("#pkSettingsBtn")
    pg.wait_for_selector("#uiSettingsDrawer:not([hidden])", state="visible")
    check(pg.is_hidden("#pkFpsRow") and pg.evaluate("document.querySelector('#pkFpsOtherFld').hidden") and pg.is_visible("#pkFpsFixedRow"), "30fps の素材: フレームレートの選択は出さない")
    check(pg.inner_text("#pkFpsFixed") == "素材とプロジェクトは 30fps" and pg.is_hidden("#pkFpsWarn"), "30fps の素材: 1行の説明だけ・60↔30 の注意は出ない: " + pg.inner_text("#pkFpsFixed"))
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")
    wait_js(pg, "document.querySelector('#uiSettingsDrawer').hidden === true")
    check(srv.get("/api/settings").get("packFps") == "60", "保存してある設定 packFps は消さない")
    srv.call("POST", "/api/settings/patch", {"values": {"packFps": "30"}})


def _scene_autorun(cx):
    """選んだ文書をまとめて「文字起こし → パック」・今の文書を最後まで(入口のまとめて実行)"""
    check, pg, srv = cx.check, cx.pg, cx.srv
    # ---- 選んだ文書をまとめて「文字起こし → パック」(12 ⑦(b)。入口の /api/autorun/start-docs)
    v3 = make_video(os.path.join(srv.media, "まとめて.webm"), sec=6, fps=30)
    tid3 = srv.call("POST", "/api/open-video", {"path": v3})["id"]   # 行の無い文書(文字起こしせずに開いた)
    pg.reload()
    wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
    wait_url_doc(pg)   # 開いていた文書が URL の ?doc= で開き直るのを待つ(監査 06)
    pg.keyboard.press("Alt+1")
    if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
        pg.click("#btnMenu")
    pg.click("[data-side-tab=files]")
    check(pg.is_visible("#txBatchBox"), "入口から開くと、履歴に「選んで、まとめて実行」が出る")
    pg.check("#txPick")
    pg.select_option("#txGroup", "none")
    pg.fill("#txSearch", "まとめて")
    pg.click("#txPickNoPack")   # パックが無いものだけ選ぶ(段4d。絞り込みで出ている「まとめて」の1本)
    check(pg.locator("#txList .txi").filter(has_text="まとめて").locator(".txi-pick").is_checked(), "「パックが無いものだけ選ぶ」で、表示中のパックの無い文書が選ばれる")
    pg.locator("#txList .txi").filter(has_text="まとめて").locator(".txi-pick").check()
    check("1 本を選んでいます" in pg.inner_text("#txPickN") and pg.is_enabled("#txBatchGo"), "文書を選ぶと、まとめて実行を押せる")
    pg.click("#txBatchGo")
    wait_js(pg, "[...document.querySelectorAll('#txRuns .tt-run .pill')].some(p => p.textContent === '済み')", 120000)   # 実行の札(段の「済み」ではなく)。状態の言葉は共通(段4: 完了 → 済み)
    run_txt = pg.inner_text("#txRuns")
    check("文字起こし: 済" in run_txt and "パック: 済" in run_txt, "行の無い文書を、文字起こし → パックまで進める: %s" % run_txt[:160])
    d3 = srv.get("/api/transcript?id=" + tid3)
    check(len(d3["segments"]) > 0 and os.path.isfile(os.path.join(os.path.splitext(v3)[0] + "_pack", "create_resolve_textplus_project.lua")),
          "同じ文書に文字起こしが入り(intoDoc)、動画の隣にパックができる")
    wait_js(pg, "/パック済み/.test(document.querySelector('#txList').textContent)", 15000)
    check(True, "終わると一覧が「パック済み」になる")
    pg.uncheck("#txPick")
    pg.fill("#txSearch", "")

    # ---- 今の文書を最後まで(題名の行の「まとめて実行 ▾」。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 3)
    v4 = make_video(os.path.join(srv.media, "今の文書.webm"), sec=6, fps=30)
    tid4 = srv.call("POST", "/api/open-video", {"path": v4})["id"]
    pg.reload()
    wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
    wait_url_doc(pg)   # 開いていた文書が URL の ?doc= で開き直るのを待つ(監査 06)
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
    wait_js(pg, "document.querySelector('#docAutoWho').dataset.color === '#65BAEA'", 10000)
    pg.click("#docAutoGo")
    wait_js(pg, "/済み|失敗/.test(document.querySelector('#pillAuto').textContent)", 120000)
    check("済み" in pg.inner_text("#pillAuto"), "題名の行の札に進み具合が出て、済みになる: %s" % pg.inner_text("#pillAuto"))
    lua4 = os.path.join(os.path.splitext(v4)[0] + "_pack", "create_resolve_textplus_project.lua")
    check(os.path.isfile(lua4) and len(srv.get("/api/transcript?id=" + tid4)["segments"]) > 0,
          "今の文書を 文字起こし → パックまで進める")
    with open(lua4, encoding="utf-8") as f:
        check("兎田ぺこらの色の文字" in f.read(), "題名の行のまとめて実行でも、配信者の色がパックの字幕に入る")


if __name__ == "__main__":
    sys.exit(main())
