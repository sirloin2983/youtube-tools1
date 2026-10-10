#!/usr/bin/env python3
"""2つ目のエンジンとの食い違いの候補(精度改善の計画 第2版 D1-b。editor/ed_alt.py・app-learn.js の renderAlt / sugHTML)の通し確認。
入口に取り込んだ形(CSP・合言葉)で、疑似の認識(主 = 「テスト文n」・2つ目 = TRANSCRIBE_FAKE_ALT で「文」→「分」)を使う。

    PYTHONIOENCODING=utf-8 py -3.10 src/editor/tests/e2e_alt.py

文字起こし → 開く →「文字をまとめて直す」の「別のエンジンの候補」で「別のエンジンでも聞く」→ 行に「別」の候補(聞いている間も編集できる)
→ 採用で行の文字が変わる → 却下で消える(読み直しても出ない)→ 保存した文書の updatedAt は聞いても動かない
→ 新規の「終わったら、別のエンジンでも聞いて…」(autoAlt)を保存 → 要求に無くても設定で自動で聞く → 文書を消すと alt.json も消える
続き(元の配信の YouTube の字幕の候補。案 A1。editor/ed_ytcap.py・app-learn.js の renderYtcap。偽の yt-dlp tests/fake_ytdlp.py = 通信しない):
元の配信が分からない文書では押せない → スタジオの切り抜き(作業用/<名前>.clip.json)を文字起こし → 「字幕を取って比べる」→ 行に「YT」と、
別のエンジンと同じ直しは「別・YT」にまとめて 1 つ → 採用・却下 → 新規の「終わったら、元の配信の YouTube の字幕と比べて…」(autoYtcap)→
同じ配信の字幕は取り直さない・元の配信が分からない動画は黙って飛ばす → 文書を消すと ytcap.json も消える
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
os.environ["TRANSCRIBE_FAKE_ALT"] = "文=>分"        # 2つ目のエンジン(疑似)は「テスト分n」と聞く
YT_FILES = tempfile.mkdtemp(prefix="ytcap-e2e-")
os.environ["TRANSCRIBE_YTDLP"] = os.path.join(HERE, "fake_ytdlp.py")   # 偽の yt-dlp(通信しない。字幕は FAKE_YTDLP_JSON3)
os.environ["FAKE_YTDLP_LOG"] = os.path.join(YT_FILES, "calls.jsonl")
os.environ["FAKE_YTDLP_JSON3"] = os.path.join(YT_FILES, "auto.json3")
YT_VID = "e2eYtCap_01"
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
            pg.evaluate("S.settings.autoAlt = true; putSettingsNow()")   # 0.66.0: チェックは設定の画面へ(ここでは保存した設定を直接)
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

            # ---- 元の配信の YouTube の字幕の候補(A1) ----
            pg.goto(srv.base + "?doc=" + tid2)
            wait_url_doc(pg)
            wait_js(pg, "S.docId === %s" % json.dumps(tid2))
            pg.evaluate("document.querySelector('#fixDetails').open = true")
            wait_js(pg, "document.querySelector('#ytcapMsg').textContent.includes('元の配信が分からない')")
            check(pg.is_disabled("#ytcapGo"), "元の配信が分からない文書では押せない: " + pg.inner_text("#ytcapMsg"))
            # 配信の字幕(配信の 100 秒目から切り抜いた 12 秒。1 行目 = 別のエンジンと同じ直し・2 行目 = YouTube だけの直し・3 行目 = 同じ)
            ev = lambda t, *ws: {"tStartMs": t, "dDurationMs": 3000, "segs": [dict({"utf8": w}, **({"tOffsetMs": o} if o else {})) for o, w in ws]}
            with open(os.environ["FAKE_YTDLP_JSON3"], "w", encoding="utf-8") as f:
                json.dump({"events": [ev(95000, (0, "前の話")), ev(100500, (0, "テスト"), (500, "分"), (700, "1")), ev(104500, (0, "テスド"), (500, "文"), (700, "2")),
                                      ev(108500, (0, "テスト"), (500, "文"), (700, "3")), ev(112500, (0, "次の話"))]}, f, ensure_ascii=False)
            yv = make_video(os.path.join(srv.media, "字幕の配信.webm"), sec=12)
            os.makedirs(os.path.join(srv.media, "作業用"), exist_ok=True)
            with open(os.path.join(srv.media, "作業用", "字幕の配信.clip.json"), "w", encoding="utf-8") as f:
                json.dump({"schema": "youtube-tools-clip/v1", "tool": {"name": "clip-studio", "version": "test"}, "createdAt": "2026-10-05T12:00:00+09:00",
                           "media": {"path": yv, "name": "字幕の配信.webm", "durationSec": 12.0},
                           "source": {"kind": "youtube", "videoId": YT_VID, "url": "https://www.youtube.com/watch?v=" + YT_VID, "title": "配信", "path": None},
                           "range": {"start": 100.0, "end": 112.0}, "mark": {"id": "m1", "label": "", "status": "exported", "src": "manual"},
                           "export": {"mode": "precise"}}, f, ensure_ascii=False)
            tid3 = srv.transcribe(yv, "YouTube の字幕のテスト")   # autoAlt はオンのまま = 別のエンジンでも聞く
            for _ in range(300):
                j3 = next((j for j in srv.get("/api/jobs")["jobs"] if j["kind"] == "alt" and j["tid"] == tid3), None)
                if j3 and j3["state"] in ("done", "error"):
                    break
                time.sleep(0.1)
            pg.goto(srv.base + "?doc=" + tid3)
            wait_url_doc(pg)
            wait_js(pg, "S.docId === %s && document.querySelectorAll('#segs .seg').length === 3" % json.dumps(tid3))
            pg.evaluate("document.querySelector('#fixDetails').open = true")
            wait_js(pg, "!document.querySelector('#ytcapGo').disabled")
            check("まだ字幕を取っていません" in pg.inner_text("#ytcapMsg"), "切り抜きなら押せる: " + pg.inner_text("#ytcapMsg"))
            pg.click("#ytcapGo")
            check(not pg.evaluate("document.querySelector('#segs').inert"), "字幕を取っている間も行は編集できる")
            wait_js(pg, "document.querySelectorAll('#segs .sg.tt-sg-yt').length === 1 && document.querySelectorAll('#segs .sg.tt-sg-both').length === 1", 30000)
            both = pg.locator("#segs .seg[data-i='0'] .sg")
            check(both.count() == 1 and "別・YT" in both.inner_text() and "「文」→「分」" in both.inner_text(), "別のエンジンと同じ直しは 1 つにまとめて「別・YT」: " + both.first.inner_text().replace("\n", " "))
            check("両方" in (both.first.get_attribute("title") or ""), "ツールチップ(2 つが一致): " + (both.first.get_attribute("title") or ""))
            yt = pg.locator("#segs .seg[data-i='1'] .sg.tt-sg-yt")
            check("YT" in yt.inner_text() and "「ト」→「ド」" in yt.inner_text() and "YouTube の自動字幕" in (yt.get_attribute("title") or ""),
                  "YouTube だけの直しは「YT」: " + yt.inner_text().replace("\n", " ") + " / " + (yt.get_attribute("title") or ""))
            check(pg.locator("#segs .seg[data-i='1'] .sg.tt-sg-alt").count() == 1, "同じ行の別の所の「別」の候補はそのまま")
            wait_js(pg, "document.querySelector('#ytcapMsg').textContent.includes('候補 2 件')", 10000)
            check("一致 1 件" in pg.inner_text("#ytcapMsg") and "自動字幕" in pg.inner_text("#ytcapMsg"), "結果の 1 行: " + pg.inner_text("#ytcapMsg"))
            yt_files = glob.glob(os.path.join(srv.tmp, "**", tid3 + ".ytcap.json"), recursive=True)
            cache_files = glob.glob(os.path.join(srv.tmp, "**", "ytcaps", YT_VID + ".json"), recursive=True)
            check(len(yt_files) == 1 and len(cache_files) == 1, "transcripts/<id>.ytcap.json と ytcaps/<配信>.json を書いた")
            d3 = srv.get("/api/transcript?id=" + tid3)
            pg.click("#segs .seg[data-i='1'] .sg.tt-sg-yt button[data-act=sgok]")
            check(pg.locator("#segs .seg[data-i='1'] textarea").input_value() == "テスド文2", "「YT」の採用で行の文字を置き換える")
            pg.click("#segs .seg[data-i='0'] .sg.tt-sg-both button[data-act=sgno]")
            check(pg.locator("#segs .seg[data-i='0'] .sg").count() == 0, "「別・YT」の却下で消える(両方)")
            for _ in range(100):
                d = srv.get("/api/transcript?id=" + tid3)
                if d["segments"][1]["text"] == "テスド文2":
                    break
                time.sleep(0.1)
            check(d["segments"][1]["text"] == "テスド文2" and d3["updatedAt"] != d["updatedAt"], "採用した文字を保存")
            sug = srv.get("/api/suggest?id=" + tid3)
            check(sug["yt"]["count"] == 0 and sorted({x["seg"] for x in sug["items"]}) == ["s2", "s3"] and all(x["tier"] == "alt" for x in sug["items"]), "読み直すと、採用・却下した所は出ない: %s" % [(x["seg"], x["tier"]) for x in sug["items"]])

            # ---- 新規の「終わったら、元の配信の YouTube の字幕と比べて…」(autoYtcap) ----
            pg.evaluate("S.settings.autoYtcap = true; putSettingsNow()")   # 0.66.0: チェックは設定の画面へ
            for _ in range(80):
                if srv.get("/api/settings").get("autoYtcap") is True:
                    break
                time.sleep(0.1)
            check(srv.get("/api/settings").get("autoYtcap") is True, "autoYtcap を設定に保存")
            check('"autoYtcap":true' in pg.evaluate("JSON.stringify(jobOpts())"), "新規の文字起こしの要求に autoYtcap が入る")
            tid4 = srv.transcribe(yv, "自動で YouTube の字幕")
            job = None
            for _ in range(300):
                job = next((j for j in srv.get("/api/jobs")["jobs"] if j["kind"] == "ytcap" and j["tid"] == tid4), None)
                if job and job["state"] in ("done", "error"):
                    break
                time.sleep(0.1)
            check(job is not None and job["state"] == "done" and "取ってあった字幕" in job["phase"], "文字起こしのあと自動で字幕と比べる(取ってあった字幕を使う): %s" % (job and job["phase"]))
            with open(os.environ["FAKE_YTDLP_LOG"], encoding="utf-8") as f:
                calls = [l for l in f if l.strip()]
            check(len(calls) == 1, "同じ配信の字幕は取り直さない(yt-dlp を動かしたのは %d 回)" % len(calls))
            check(srv.get("/api/suggest?id=" + tid4)["yt"]["count"] >= 1, "自動で比べた文書にも候補")
            tid5 = srv.transcribe(video, "元の配信が分からない")
            time.sleep(1.0)
            jobs = srv.get("/api/jobs")["jobs"]
            tx5 = next(j for j in jobs if j["kind"] == "transcribe" and j["tid"] == tid5)
            check(not any(j["kind"] == "ytcap" and j["tid"] == tid5 for j in jobs) and not any("YouTube" in w for w in tx5["warnings"]),
                  "元の配信が分からない動画は黙って飛ばす")

            # ---- 文書を消すと ytcap.json も消える(配信ごとの字幕は残す = 別の切り抜きで使い回す) ----
            r = srv.call("DELETE", "/api/transcript?id=" + tid3)
            check(r.get("ok") is True and not os.path.exists(yt_files[0]) and os.path.exists(cache_files[0]), "文書を消すと ytcap.json も消える(配信ごとの字幕は残る)")

            # ---- 文書を消すと alt.json も消える ----
            r = srv.call("DELETE", "/api/transcript?id=" + tid)
            check(r.get("ok") is True and not os.path.exists(alt_files[0]), "文書を消すと alt.json も消える")
            b.close()
        bad = [e for e in errors if "favicon" not in e and "ERR_ABORTED" not in e]
        check(not bad, "画面のエラーなし: %s" % bad[:3])
        bad_http = [x for x in bad_http if "favicon" not in x and not ("404" in x and "/api/eval-batch" in x)]
        check(not bad_http, "読み込みの失敗なし: %s" % bad_http[:3])
    finally:
        srv.stop()
        shutil.rmtree(YT_FILES, ignore_errors=True)
    print("\n結果:", "すべて成功" if check.ok else "失敗あり")
    sys.exit(0 if check.ok else 1)


if __name__ == "__main__":
    main()
