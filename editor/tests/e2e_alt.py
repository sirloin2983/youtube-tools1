#!/usr/bin/env python3
"""2つ目のエンジンとの食い違いの候補(精度改善の計画 第2版 D1-b。editor/ed_alt.py・app-learn.js の renderAlt / sugHTML)の通し確認。
入口に取り込んだ形(CSP・合言葉)で、疑似の認識(主 = 「テスト文n」・2つ目 = TRANSCRIBE_FAKE_ALT で「文」→「分」)を使う。

    PYTHONIOENCODING=utf-8 py -3.10 editor/tests/e2e_alt.py

文字起こし → 開く →「文字をまとめて直す」の「別のエンジンの候補」で「別のエンジンでも聞く」→ 行に「別」の候補(聞いている間も編集できる)
→ 採用で行の文字が変わる → 却下で消える(読み直しても出ない)→ 保存した文書の updatedAt は聞いても動かない
→ 新規の「終わったら、別のエンジンでも聞いて…」(autoAlt)を保存 → 要求に無くても設定で自動で聞く → 文書を消すと alt.json も消える
"""
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
os.environ["TRANSCRIBE_FAKE_ALT"] = "文=>分"        # 2つ目のエンジン(疑似)は「テスト分n」と聞く
from e2e_edit_common import Checks, Server, make_video, wait_js, wait_url_doc  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        video = make_video(os.path.join(srv.media, "別のエンジン.webm"), sec=12)
        tid = srv.transcribe(video, "別のエンジンのテスト")
        doc0 = srv.get("/api/transcript?id=" + tid)
        n_rows = len(doc0["segments"])
        check(n_rows == 3 and doc0["segments"][0]["text"] == "テスト文1", "疑似の文字起こし: %s" % [g["text"] for g in doc0["segments"]])

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            bad_http = []
            pg.on("response", lambda r: bad_http.append("%d %s" % (r.status, r.url)) if r.status >= 400 else None)

            pg.goto(srv.base + "?doc=" + tid)
            wait_url_doc(pg)
            wait_js(pg, "S.docId === %s && document.querySelectorAll('#segs .seg').length === %d" % (json.dumps(tid), n_rows))
            pg.evaluate("document.querySelector('#fixDetails').open = true")
            wait_js(pg, "document.querySelector('#altEngine').options.length === 3")
            check(pg.input_value("#altEngine") == "llama.cpp", "2つ目のエンジンの既定は Qwen3-ASR(llama.cpp)")
            check("まだ別のエンジンで聞いていません" in pg.inner_text("#altMsg") and not pg.is_disabled("#altGo"), "まだ聞いていない: " + pg.inner_text("#altMsg"))
            check(pg.locator(".sg.tt-sg-alt").count() == 0, "聞く前は「別」の候補なし")

            # ---- エンジンを変えると設定(altEngine)に残る ----
            pg.select_option("#altEngine", "whisper.cpp")
            for _ in range(50):
                if srv.get("/api/settings").get("altEngine") == "whisper.cpp":
                    break
                time.sleep(0.1)
            check(srv.get("/api/settings").get("altEngine") == "whisper.cpp", "選んだエンジンを設定 altEngine に保存(api/settings/patch)")
            pg.select_option("#altEngine", "llama.cpp")

            # ---- 聞く → 候補が行に出る(聞いている間も編集できる = 行は止めない) ----
            pg.click("#altGo")
            check(not pg.evaluate("document.querySelector('#segs').inert"), "聞いている間も行は編集できる(編集を止めるジョブにしない)")
            wait_js(pg, "document.querySelectorAll('#segs .sg.tt-sg-alt').length === %d" % n_rows, 30000)
            chip = pg.locator("#segs .seg[data-i='0'] .sg.tt-sg-alt")
            txt = chip.inner_text()
            check("別" in txt and "「文」→「分」" in txt, "行に「別」の候補: " + txt.replace("\n", " "))
            check("別のエンジン" in (chip.get_attribute("title") or ""), "ツールチップ: " + (chip.get_attribute("title") or ""))
            wait_js(pg, "document.querySelector('#altMsg').textContent.includes('候補 %d 件')" % n_rows, 10000)
            check(True, "結果の 1 行: " + pg.inner_text("#altMsg"))
            alt_files = glob.glob(os.path.join(srv.tmp, "**", tid + ".alt.json"), recursive=True)
            check(len(alt_files) == 1, "transcripts/<id>.alt.json を書いた")
            check(srv.get("/api/transcript?id=" + tid)["updatedAt"] == doc0["updatedAt"], "聞いても文書の updatedAt は動かない")

            # ---- 採用 → 行の文字が変わる / 却下 → 消える ----
            pg.click("#segs .seg[data-i='0'] .sg.tt-sg-alt button[data-act=sgok]")
            check(pg.locator("#segs .seg[data-i='0'] textarea").input_value() == "テスト分1", "採用で行の文字を置き換える")
            pg.click("#segs .seg[data-i='1'] .sg.tt-sg-alt button[data-act=sgno]")
            check(pg.locator("#segs .seg[data-i='1'] .sg.tt-sg-alt").count() == 0, "却下で消える")
            for _ in range(100):
                d = srv.get("/api/transcript?id=" + tid)
                if d["segments"][0]["text"] == "テスト分1":
                    break
                time.sleep(0.1)
            check(d["segments"][0]["text"] == "テスト分1" and d["segments"][1]["text"] == "テスト文2", "採用した文字を保存(却下した行はそのまま)")
            sug = srv.get("/api/suggest?id=" + tid)
            alts = [(x["seg"], x["wrong"]) for x in sug["items"] if x["tier"] == "alt"]
            check(alts == [("s3", "文")] and sug["alt"]["count"] == 1, "読み直すと、採用した所・却下した所は出ない: %s" % alts)
            pg.reload()
            wait_url_doc(pg)
            wait_js(pg, "document.querySelectorAll('#segs .seg').length === %d && document.querySelectorAll('#segs .sg.tt-sg-alt').length === 1" % n_rows, 15000)
            check(True, "画面を読み直しても残りの候補は 1 件")

            # ---- 新規の「終わったら、別のエンジンでも聞いて…」(autoAlt) ----
            pg.evaluate("for (let e = document.querySelector('#optAutoAlt'); e; e = e.parentElement) if (e.tagName === 'DETAILS') e.open = true")
            pg.evaluate("const c = document.querySelector('#optAutoAlt'); c.checked = true; c.dispatchEvent(new Event('change', { bubbles: true }))")
            for _ in range(80):
                if srv.get("/api/settings").get("autoAlt") is True:
                    break
                time.sleep(0.1)
            check(srv.get("/api/settings").get("autoAlt") is True, "autoAlt を設定に保存")
            check("autoAlt" in pg.evaluate("JSON.stringify(jobOpts())"), "新規の文字起こしの要求に autoAlt が入る")
            tid2 = srv.transcribe(video, "自動で別のエンジン")   # 要求に autoAlt が無くても、保存した設定で聞く(まとめて実行と同じ)
            job = None
            for _ in range(300):
                job = next((j for j in srv.get("/api/jobs")["jobs"] if j["kind"] == "alt" and j["tid"] == tid2), None)
                if job and job["state"] in ("done", "error"):
                    break
                time.sleep(0.1)
            check(job is not None and job["state"] == "done", "文字起こしのあと自動で別のエンジンでも聞く: %s" % (job and job["state"]))
            check(srv.get("/api/suggest?id=" + tid2)["alt"]["count"] == n_rows, "自動で聞いた文書にも候補")

            # ---- 文書を消すと alt.json も消える ----
            r = srv.call("DELETE", "/api/transcript?id=" + tid)
            check(r.get("ok") is True and not os.path.exists(alt_files[0]), "文書を消すと alt.json も消える")
            b.close()
        bad = [e for e in errors if "favicon" not in e and "ERR_ABORTED" not in e]
        check(not bad, "画面のエラーなし: %s" % bad[:3])
        bad_http = [x for x in bad_http if "favicon" not in x and not ("404" in x and "/api/eval-batch" in x)
                    and not ("409" in x and "/api/archive" in x)]
        check(not bad_http, "読み込みの失敗なし: %s" % bad_http[:3])
    finally:
        srv.stop()
    print("\n結果:", "すべて成功" if check.ok else "失敗あり")
    sys.exit(0 if check.ok else 1)


if __name__ == "__main__":
    main()
