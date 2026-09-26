#!/usr/bin/env python3
"""「編集」E4 パックのタブの確認(docs/edit-tool-design.md の 3・5・7)。入口に取り込んだ形(パックは cut2resolve の api/build)。

- カット(手で決めた区間。60fps の元の動画)のとおりにパックができる(textplus-import.json の区間 = 編集の内容のフレーム)
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

from e2e_edit_common import Checks, Server, make_video, open_doc, wait_js

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
            with open(os.path.join(packdir, "textplus-import.json"), encoding="utf-8") as f:
                ip = json.load(f)
            got = [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip.get("cuts", [])]
            check(got == clips, "パックの区間 = カットのタブの区間(元の動画の 60fps のフレームのまま・短い区間も捨てない): %s" % got)
            check(ip.get("target") == {"fps": 30, "width": 1080, "height": 1920} and len(ip.get("captions", [])) == 3, "置き先 30fps・縦、字幕 3件: %s" % ip.get("target"))
            e = srv.get("/api/edit?id=" + tid)
            check(e["edit"]["packRev"] == e["rev"] == 1 and os.path.normcase(e["edit"]["pack"]["dir"]) == os.path.normcase(packdir) and not e["packStale"],
                  "作った記録(packRev = 作ったときのカットの rev・出力フォルダ)")
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
            check("字幕なし.edl" in files and "字幕なし.webm" in files and "textplus-import.json" not in files, "文字起こしの無い動画のパック: EDL と元の動画のコピー(Text+ なし): %s" % files)

            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
