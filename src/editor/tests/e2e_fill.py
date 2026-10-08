#!/usr/bin/env python3
"""認識のあとの後処理(ed_fill。編集 0.60.0)の通し確認: 疑似の認識(主 = 「テスト文n」= 4 秒に 5 字 = 文字が少ない行)に、2 つ目の読み(TRANSCRIBE_FAKE_FILL)で埋める。
入口に取り込んだ形(CSP・合言葉)。
  - 文字起こし → 行が別の読みに置き換わり、fill(元の文字)と要確認の印が付く・記録 recognition.runs[].fill
  - 画面: 行の「別の読み」の札 → 押すと whisper の文字に戻り、札と印が消える → 保存される → 元に戻す(doUndo)で別の読みに戻る
  - 「認識の設定」の autoFill は既定オン・外すと設定に保存され、新規の文字起こしの要求に入る

    python src/editor/tests/e2e_fill.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
LONG = "これは別の読みで埋めた長い文です"           # 16 字 = 「テスト文n」(5 字)の 3 倍以上
os.environ["TRANSCRIBE_FAKE_FILL"] = LONG
from e2e_edit_common import Checks, Server, make_video, wait_js, wait_url_doc  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        video = make_video(os.path.join(srv.media, "別の読み.webm"), sec=12)
        tid = srv.transcribe(video, "別の読みのテスト")
        doc0 = srv.get("/api/transcript?id=" + tid)
        segs = doc0["segments"]
        check([g["text"] for g in segs] == [LONG] * 3, "文字の少ない行(3 行)が別の読みに置き換わる: %s" % [g["text"] for g in segs])
        check([g.get("fill") for g in segs] == [{"from": "テスト文%d" % i, "by": "sense-voice"} for i in (1, 2, 3)], "行に fill(元の文字): %s" % [g.get("fill") for g in segs])
        check(all(g["flag"].startswith("別の読みで埋めた") for g in segs), "要確認の印: %s" % [g["flag"] for g in segs])
        run = doc0["recognition"]["runs"][0]
        check(run.get("fill") == {"engine": "sense-voice", "windows": 3, "rows": 3, "added": 3, "dup": 0, "agree": 0} and doc0["params"].get("autoFill") is True,
              "記録 recognition.runs[].fill と params.autoFill: %s" % run.get("fill"))

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            bad_http = []
            pg.on("response", lambda r: bad_http.append("%d %s" % (r.status, r.url)) if r.status >= 400 else None)

            pg.goto(srv.base + "?doc=" + tid)
            wait_url_doc(pg)
            wait_js(pg, "S.docId === %s && document.querySelectorAll('#segs .seg').length === 3" % json.dumps(tid))
            check(pg.locator("#segs .seg .tt-fill").count() == 3, "行に「別の読み」の札が 3 つ")
            title = pg.locator("#segs .seg[data-i='0'] .tt-fill").get_attribute("title") or ""
            check("テスト文1" in title and "sense-voice" in title, "札のツールチップに whisper の文字: " + title)
            check(pg.locator("#segs .seg[data-i='0'] .fl").count() == 1, "要確認の札も出る")

            # ---- 押すと whisper の文字に戻る(札と印が消える)→ 保存される ----
            pg.click("#segs .seg[data-i='0'] .tt-fill")
            wait_js(pg, "document.querySelector('#segs .seg[data-i=\"0\"] textarea').value === 'テスト文1'")
            check(pg.locator("#segs .seg[data-i='0'] .tt-fill").count() == 0 and pg.locator("#segs .seg[data-i='0'] .fl").count() == 0, "戻すと「別の読み」の札と要確認の印が消える")
            check(pg.locator("#segs .seg[data-i='1'] .tt-fill").count() == 1, "ほかの行はそのまま")
            for _ in range(100):
                d = srv.get("/api/transcript?id=" + tid)
                if d["segments"][0]["text"] == "テスト文1":
                    break
                time.sleep(0.1)
            check(d["segments"][0]["text"] == "テスト文1" and "fill" not in d["segments"][0] and d["segments"][0]["flag"] == "" and d["segments"][1].get("fill"),
                  "戻した文字を保存(fill と印なし。ほかの行の fill は残る)")

            # ---- 元に戻す → 別の読みに戻る ----
            pg.evaluate("doUndo('tx')")
            wait_js(pg, "document.querySelector('#segs .seg[data-i=\"0\"] textarea').value === %s" % json.dumps(LONG))
            check(pg.locator("#segs .seg[data-i='0'] .tt-fill").count() == 1, "元に戻すで別の読みと札が戻る")

            # ---- 認識の設定 autoFill(既定オン)。外すと設定に保存され、要求にも入る ----
            pg.evaluate("for (let e = document.querySelector('#optAutoFill'); e; e = e.parentElement) if (e.tagName === 'DETAILS') e.open = true")
            check(pg.is_checked("#optAutoFill"), "「文字の少ない行を別のエンジンの読みで埋め…」は既定オン")
            pg.evaluate("const c = document.querySelector('#optAutoFill'); c.checked = false; c.dispatchEvent(new Event('change', { bubbles: true }))")
            for _ in range(80):
                if srv.get("/api/settings").get("autoFill") is False:
                    break
                time.sleep(0.1)
            check(srv.get("/api/settings").get("autoFill") is False, "外すと autoFill: false を設定に保存")
            check('"autoFill":false' in pg.evaluate("JSON.stringify(jobOpts())"), "新規の文字起こしの要求に autoFill が入る")
            tid2 = srv.transcribe(video, "後処理なし")
            d2 = srv.get("/api/transcript?id=" + tid2)
            check([g["text"] for g in d2["segments"]] == ["テスト文1", "テスト文2", "テスト文3"] and "fill" not in d2["recognition"]["runs"][0], "設定オフなら置き換えない")
            b.close()
        bad = [e for e in errors if "favicon" not in e and "ERR_ABORTED" not in e]
        check(not bad, "画面のエラーなし: %s" % bad[:3])
        bad_http = [x for x in bad_http if "favicon" not in x and not ("404" in x and "/api/eval-batch" in x) and not ("409" in x and "/api/archive" in x)]
        check(not bad_http, "読み込みの失敗なし: %s" % bad_http[:3])
    finally:
        srv.stop()
    print("\n結果:", "すべて成功" if check.ok else "失敗あり")
    sys.exit(0 if check.ok else 1)


if __name__ == "__main__":
    main()
