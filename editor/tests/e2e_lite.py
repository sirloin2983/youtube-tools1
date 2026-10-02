#!/usr/bin/env python3
"""友人用 文字起こし簡易版の画面(editor/lite.html・lite.js)の通し確認。入口に取り込んだ形(CSP・合言葉)で、疑似の文字起こしを使う。

    python editor/tests/e2e_lite.py

読み込み(ドロップ)→ 文字起こし中 → 校正(Enter で確認して次へ・話者・時刻の制限・取り消し・保存)→ 書き出し(送る用 zip と Resolve 用ファイル)→ 開き直すと続きから
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = tempfile.mkdtemp(prefix="lite-out-")
os.environ["LITE_OUT_DIR"] = OUT          # 書き出しの置き場所(本物のドキュメントに書かない)
os.environ["LITE_MODEL"] = "small"
os.environ["LITE_NO_OPEN"] = "1"          # エクスプローラーを開かない
from e2e_edit_common import Checks, Server, make_video, wait_js, REPO  # noqa: E402
sys.path.insert(0, REPO)
from ytt_core import evaldata as EV  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def drop_file(pg, path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    pg.evaluate("""([b64, name]) => {
        const bin = atob(b64); const u8 = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
        const dt = new DataTransfer(); dt.items.add(new File([u8], name, { type: 'video/webm' }));
        document.querySelector('#ltDrop').dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
    }""", [b64, os.path.basename(path)])


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        video = make_video(os.path.join(srv.media, "配信テスト.webm"), sec=12)
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            pg = ctx.new_page()
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(srv.base + "lite.html")
            wait_js(pg, "!document.querySelector('#stLoad').hidden")
            check(pg.locator(".lt-steps button[aria-current=step]").inner_text().endswith("読み込み"), "1 読み込み から始まる")
            check(pg.locator("#ltStart").is_disabled(), "動画を選ぶまで始められない")
            check(pg.locator("#ltRuleList li").count() == 4, "書き方のルール 4 つ")

            # 1 読み込み: ドロップ = アップロード → 長さ
            drop_file(pg, video)
            wait_js(pg, "!document.querySelector('#ltFile').hidden", 30000)
            check("配信テスト" in pg.inner_text("#ltFileName"), "ドロップした動画の名前")
            check("0:12" in pg.inner_text("#ltFileLen"), "動画の長さ")
            pg.fill("#ltStreamer", "")
            check(pg.locator("#ltStart").is_disabled(), "配信者が空なら始められない")
            pg.fill("#ltStreamer", "兎田ぺこら")
            pg.fill("#ltWorker", "友人A")
            pg.locator("#ltWorker").dispatch_event("change")
            pg.fill("#ltUrl", "https://www.youtube.com/watch?v=abc")
            pg.click("#ltStart")

            # 2 → 3: 疑似の文字起こしが終わると校正へ
            wait_js(pg, "!document.querySelector('#stProof').hidden", 60000)
            check(pg.locator(".lt-row").count() == 3, "行が 3 つ(疑似は 4 秒ごと)")
            check(pg.inner_text("#ltCount") == "確認済み 0/3 行", "確認済みの数を出す")
            check(pg.locator("#ltSpk input").first.input_value() == "兎田ぺこら", "既定の話者 = 配信者")
            check(pg.evaluate("document.querySelector('#ltVideo').src").find("/transcribe/media?id=") >= 0, "動画は apiUrl から")

            # 文字を直して Enter → 確認済み・次の行の文字へ
            ta0 = pg.locator(".lt-row").nth(0).locator("textarea")
            ta0.click()
            ta0.fill("えー [笑] こんにちは")
            ta0.press("Enter")
            check("ok" in (pg.locator(".lt-row").nth(0).get_attribute("class") or ""), "Enter で確認済み")
            check(pg.evaluate("document.activeElement === document.querySelectorAll('.lt-row')[1].querySelector('textarea')"), "次の行の文字へ進む")
            check(pg.inner_text("#ltCount") == "確認済み 1/3 行", "確認済み 1/3")
            check(pg.locator(".lt-row").nth(0).locator(".lt-state").inner_text() == "確認済み", "色だけでなく文字でも確認済み")

            # 話者を足して数字キーで付ける
            pg.keyboard.press("Escape")
            pg.fill("#ltSpkNew", "さくらみこ")
            pg.click("#ltSpkAdd")
            check(pg.locator("#ltSpk input").count() == 2, "話者を足せる")
            pg.locator(".lt-row").nth(1).locator(".lt-time").click()
            pg.keyboard.press("2")
            check(pg.locator(".lt-row").nth(1).locator("select").input_value() == "B", "数字キーで話者")

            # 時刻: 前の行と重ならない・取り消し
            t1 = lambda: pg.locator(".lt-row").nth(1).locator(".lt-time b").inner_text()
            before = t1()
            pg.keyboard.press("x")
            check(t1() != before, "X で開始を 0.1 秒遅く")
            pg.keyboard.press("Control+z")
            check(t1() == before, "Ctrl+Z で取り消し")
            for _ in range(5):
                pg.keyboard.press("z")
            row0_end = pg.locator(".lt-row").nth(0).locator(".lt-time span").inner_text().replace("〜 ", "")
            check(t1() == row0_end, "開始は前の行の終わりより前にならない(%s / %s)" % (t1(), row0_end))
            pg.keyboard.press("Enter")   # 2 行目を確認済み(再生せずに確定 = 記録だけ)

            # 保存
            wait_js(pg, "document.querySelector('#ltSave').dataset.state === 'ok'", 10000)
            tid = pg.evaluate("localStorage.getItem('lite.doc')")
            doc = srv.get("/api/transcript?id=" + tid)
            check(doc["segments"][0]["text"] == "えー [笑] こんにちは" and doc["segments"][0].get("proofed") is True, "保存した文書")
            check(doc["segments"][1]["speaker"] == "B" and doc["speakers"][1]["name"] == "さくらみこ", "話者も保存")
            check(doc["lite"]["streamer"] == "兎田ぺこら", "簡易版の印")

            # 4 書き出し
            pg.click("#ltToExport")
            check("まだ確認していない 1 行" in pg.inner_text("#ltExSummary"), "未確認の行数を出す(止めない)")
            check(pg.input_value("#ltTracks") == "1" and "V2 に字幕" in pg.inner_text("#ltTracksHint"), "映像トラックの数の既定 1")
            pg.select_option("#ltTracks", "3")
            check("V4(一番上)に字幕" in pg.inner_text("#ltTracksHint"), "映像トラックの数を選ぶと案内が変わる")
            pg.screenshot(path=os.path.join(tempfile.gettempdir(), "e2e_lite_export.png"), full_page=False)
            pg.click("#ltExport")
            wait_js(pg, "!document.querySelector('#ltDone').hidden", 60000)
            name = pg.inner_text("#ltZipName")
            check(name.endswith("_" + tid + ".zip") and "兎田ぺこら" in name, "zip の名前 = 日付_配信者_作業ID")
            zpath = os.path.join(OUT, name[:-4], "送る用ファイル", name)
            check(os.path.isfile(zpath) and EV.check_zip(zpath)[1] == [], "送る用 zip ができて検証を通る")
            with zipfile.ZipFile(zpath) as z:
                meta = json.loads(z.read("meta.json"))
                edits = EV.read_edits(z.read("edits.jsonl"))
            check(meta["worker"] == "友人A" and meta["sourceUrl"].endswith("v=abc"), "作業者の名前と元の URL")
            check(any(e["op"] == "confirm" for e in edits) and any(e["op"] == "time" for e in edits), "作業の記録(確定・時刻)")
            check(meta["notes"]["confirmedWithoutListening"] >= 1, "聞かずに確定を記録")
            lua_path = os.path.join(OUT, name[:-4], "Resolve用ファイル", "create_resolve_textplus_project.lua")
            check(os.path.isfile(lua_path), "Resolve 用ファイル")
            with open(lua_path, encoding="utf-8") as f:
                check('["videoTracks"]=3' in f.read(), "選んだ映像トラックの数が Resolve 用ファイルに入る")
            check(srv.get("/api/lite/state")["settings"]["videoTracks"] == 3, "映像トラックの数を覚える")
            check(pg.locator("#ltExport").inner_text() == "もう一度書き出す", "書き出しは何度でも")

            # 開き直すと続きから(書き出しの段)
            pg.reload()
            wait_js(pg, "!document.querySelector('#stExport').hidden", 15000)
            check(True, "開き直すと続きから")
            pg.click(".lt-steps button[data-step=load]")
            check(pg.locator(".lt-work").count() == 1, "読み込みの段に「続きから」の一覧")
            pg.click(".lt-work")
            wait_js(pg, "!document.querySelector('#stProof').hidden")
            check(pg.inner_text("#ltCount") == "確認済み 2/3 行", "一覧から開いて校正に戻る")

            # 狭い画面でも横にはみ出さない
            pg.set_viewport_size({"width": 800, "height": 900})
            check(pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "800px で横にはみ出さない")
            pg.screenshot(path=os.path.join(tempfile.gettempdir(), "e2e_lite_proof.png"), full_page=False)
            b.close()
        check(not [e for e in errors if "favicon" not in e], "画面のエラーなし: %s" % errors[:3])
    finally:
        srv.stop()
        shutil.rmtree(OUT, ignore_errors=True)
    print("ALL OK" if check.ok else "FAILED")
    sys.exit(0 if check.ok else 1)


if __name__ == "__main__":
    main()
