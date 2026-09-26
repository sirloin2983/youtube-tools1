#!/usr/bin/env python3
"""「編集」E4 パックのタブの確認(docs/edit-tool-design.md の 3・5・7)。入口に取り込んだ形(パックは cut2resolve の api/build)。

- カット(手で決めた区間。60fps の元の動画)のとおりにパックができる(Lua に埋め込んだ区間 = 編集の内容のフレーム)
- パックは最小限(④): 動画・Lua・雛形・登録用の ps1/bat・友人へ.txt だけ。「予備も入れる」で EDL・予備の手順書・SRT
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
        srv.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [],
                                                      "segments": [{"id": "r%d" % i, "start": a, "end": b, "text": t} for i, (a, b, t) in enumerate(rows)]})
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
            check(pg.is_visible("#pkFpsWarn") and "60fps" in pg.inner_text("#pkFpsWarn"), "60fps の元の動画を 30fps のプロジェクトに入れるときの注意: " + pg.inner_text("#pkFpsWarn"))
            pg.click("#pkFps [data-v='60']")
            wait_js(pg, "document.querySelector('#pkFpsWarn').hidden", 3000)
            check(True, "置き先を 60fps にすると注意は消える")
            pg.click("#pkFps [data-v='30']")
            pg.click("#pkSize [data-v='1080x1920']")
            pg.click("#pkBuild")
            wait_js(pg, "(!document.querySelector('#pkLast').hidden || !document.querySelector('#pkErr').hidden) && document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled", 120000)
            check(pg.is_hidden("#pkErr"), "パックができる(エラーが出ない): " + pg.inner_text("#pkErr"))
            packdir = os.path.splitext(v1)[0] + "_pack"
            ip = read_pack_plan(os.path.join(packdir, "create_resolve_textplus_project.lua"))
            got = [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip.get("cuts", [])]
            names = sorted(os.path.relpath(os.path.join(r, n), packdir).replace(os.sep, "/") for r, _, ns in os.walk(packdir) for n in ns)
            check(names == sorted(["ResolveにText+スクリプトを登録.bat", "create_resolve_textplus_project.lua", "install_resolve_textplus_script.ps1",
                                   "media/" + os.path.basename(v1), "textplus-template.drb", "友人へ.txt"]),
                  "パックは最小限(動画・Lua・雛形・登録用の ps1/bat・友人へ.txt。EDL・SRT・cut-plan.json・.json は入れない): %s" % names)
            check(got == clips, "パックの区間 = カットのタブの区間(元の動画の 60fps のフレームのまま・短い区間も捨てない): %s" % got)
            check(ip.get("target") == {"fps": 30, "width": 1080, "height": 1920} and len(ip.get("captions", [])) == 3, "置き先 30fps・縦、字幕 3件: %s" % ip.get("target"))
            e = srv.get("/api/edit?id=" + tid)
            check(e["edit"]["packRev"] == e["rev"] == 1 and os.path.normcase(e["edit"]["pack"]["dir"]) == os.path.normcase(packdir) and not e["packStale"],
                  "作った記録(packRev = 作ったときのカットの rev・出力フォルダ)")
            # 「予備も入れる」→ EDL・予備の手順書・SRT も(上書きの確認のあと)
            pg.check("#pkBackup")
            pg.click("#pkBuild")
            wait_js(pg, "document.querySelector('#dlgOverwrite').open", 20000)
            pg.click("#owOk")
            wait_js(pg, "document.querySelector('#pkJob').hidden && !document.querySelector('#pkBuild').disabled && document.querySelector('#pkLastPill').textContent === '前回のパック'", 120000)
            names2 = set(os.listdir(packdir))
            stem = os.path.splitext(os.path.basename(v1))[0]
            check({stem + ".edl", stem + "_cut.srt", "予備_EDLで開く手順.txt"} <= names2 and "cut-plan.json" not in names2,
                  "「予備も入れる」で EDL・予備_EDLで開く手順.txt・SRT も入る: %s" % sorted(names2))
            pg.uncheck("#pkBackup")
            # 作っている途中の「中止」(粗編集の動画も作る。間に合わず終わってしまったときは、そのことを出す)
            pg.check("#pkRender")
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
            pg.uncheck("#pkRender")
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
            check(files == sorted(["字幕なし.edl", "字幕なし.webm", "友人へ.txt"]), "文字起こしの無い動画のパック: EDL・友人へ.txt・元の動画のコピー(Text+ なし。cut-plan.json は入れない): %s" % files)
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
            wait_js(pg, "[...document.querySelectorAll('#txRuns .tt-run')].some(r => r.textContent.includes('完了'))", 120000)
            run_txt = pg.inner_text("#txRuns")
            check("文字起こし: 済" in run_txt and "Resolve パック: 済" in run_txt, "行の無い文書を、文字起こし → パックまで進める: %s" % run_txt[:160])
            d3 = srv.get("/api/transcript?id=" + tid3)
            check(len(d3["segments"]) > 0 and os.path.isfile(os.path.join(os.path.splitext(v3)[0] + "_pack", "create_resolve_textplus_project.lua")),
                  "同じ文書に文字起こしが入り(intoDoc)、動画の隣にパックができる")
            wait_js(pg, "/パック済み/.test(document.querySelector('#txList').textContent)", 15000)
            check(True, "終わると一覧が「パック済み」になる")
            pg.uncheck("#txPick")
            pg.fill("#txSearch", "")

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
