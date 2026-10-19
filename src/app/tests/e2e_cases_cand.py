"""案件の画面(/cases)の「候補」のパネル(src/app/ui/cases/panels/cand.js。RS8 C2a)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.12 src/app/tests/e2e_cases_cand.py
入口(app/server.py)にスタジオを取り込んで動かす(STUDIO_FAKE=1・生成した短い webm・一時フォルダだけ)。
④ の案件の一覧(cases_mod.snapshot)は見本に差し替え、案件の id = スタジオの配信の id にする。
見るもの: パネルが載る(配信の選択は出さない)・動画を再生できる・盛り上がりグラフ・採用 / 不採用がスタジオに保存される・
キー(y・n)は殻の keydown からパネルへ届く・書き出し → 済みの行と「編集で開く」のリンク・離れたら再生を止める・
別の行(切り抜き)へ移るとパネルを片付ける(キーが効かない・プレーヤーが消える)・戻ると作り直す・コンソールのエラーが無い。
外から来る文字列(題名・ラベル)が HTML にならない・開始 / 終了の時刻の欄(数字だけで確定・欄の中の ← → は再生位置を動かさない)・
まとめて実行(配信ごと・マークの「この後を ▸」)・採用が無いと「書き出す」は押せない・
書き出したマークのセリフ(元の配信の時刻・校正の進み具合・押すとその時刻へ)・一瞬をマーク(C)・つなげて1本に・前回の場所(開き直すと戻る)・
1720 では書き出しの引き出しを横に並べる・390 で重ねて開いている間は裏のキーが効かない・YouTube のプレーヤーが使えないとき(知らせの文は test_cand_panel.cjs)。
? の一覧・下の帯の文字・幅 390 のはみ出し・設定の保存の失敗の ⚙ の印は画面の道に入れない(写真の関所・ui_audit の A-20)。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
os.environ["STUDIO_FAKE"] = "1"   # YouTube へは接続しない
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
STUDIO = os.path.join(SRC, "studio")
sys.path.insert(0, STUDIO)
sys.path.insert(0, os.path.join(SRC, "app"))
if SRC not in sys.path:
    sys.path.append(SRC)
import startup  # noqa: E402,F401  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
from ytt import datadir, studio_env, testkit  # noqa: E402
import serve  # noqa: E402
from app import server as L  # noqa: E402
from app import mount  # noqa: E402

VID = "fqa00000001"
YT_ID = "ytCand00001"   # YouTube の配信(テストでは YouTube へ繋がない = プレーヤーが使えないときの確認用)
XSS_TITLE = '<img src=x onerror="window.__xss=1">配信<b>太字</b>'
XSS_LABEL = '<script>window.__xss=2</script><img src=x onerror="window.__xss=3">'


def counts_as_error(m):
    """コンソールのエラーのうち画面のエラーに数えるもの(読み込みの失敗は応答の 4xx / 5xx で別に見る・YouTube の中のエラーは数えない)"""
    if m.type != "error" or "ytimg" in m.text or "Failed to load resource" in m.text:
        return False
    return not ((m.location or {}).get("url") or "").startswith("https://www.youtube.com/")


wait_js = testkit.wait_js


def make_media(home):
    ffmpeg = studio_env.find_tool("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg が必要です")
    media = os.path.join(home, "sample.webm")   # Playwright の chromium は H.264 を再生できないので webm
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15:duration=40",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-shortest", "-c:v", "libvpx", "-b:v", "200k", "-deadline", "realtime",
                    "-c:a", "libopus", media], check=True)
    return media


def fixture(home):
    """スタジオの配信 1 本(手のマーク 2(1 本はラベルに HTML)+ 自動のマーク 3 + 盛り上がりのグラフ。題名にも HTML)と YouTube の配信 1 本"""
    media = make_media(home)
    os.environ["STUDIO_FAKE_MEDIA"] = media
    os.environ["TRANSCRIBE_DATA_DIR"] = os.path.join(home, "txdata")
    store, _ = serve.init(home)
    store.ensure({"kind": "file", "videoId": VID, "name": "sample.webm", "path": media}, XSS_TITLE)
    store.put_video(VID, XSS_TITLE, [{"id": "m1", "start": 2, "end": 7, "label": "確認用", "status": "adopted"},
                                     {"id": "x1", "start": 37, "end": 39, "label": XSS_LABEL, "status": ""}])
    store.ensure({"kind": "youtube", "videoId": YT_ID}, "埋め込みできない配信", "星見ルナ")
    store.put_video(YT_ID, "埋め込みできない配信", [{"id": "y%d" % i, "start": 60 + i * 60, "end": 90 + i * 60, "label": "", "status": ""} for i in range(3)])
    n = 40
    total = [0.2 + (2.5 if 10 <= i <= 14 else 0) + (1.6 if 24 <= i <= 27 else 0) + (i % 5) * 0.05 for i in range(n)]
    series = {"step": 1, "n": n, "total": total, "audio": [t * 0.6 for t in total], "chat": [t * 0.3 for t in total], "comments": [0.1] * n}
    cands = [{"start": 9.0, "end": 16.0, "peak": 12, "score": 6.4, "parts": {"audio": 3.1}, "reasons": ["音量が急上昇"]},
             {"start": 22.0, "end": 29.0, "peak": 25, "score": 4.2, "parts": {"chat": 1.5}, "reasons": ["チャットが増加"]},
             {"start": 31.0, "end": 36.0, "peak": 33, "score": 2.3, "parts": {"audio": 2.3}, "reasons": ["音量が急上昇"]}]
    store.replace_auto(VID, cands, {"at": int(time.time() * 1000), "signals": {}, "counts": {}, "warnings": [], "spec": {}, "type": None}, 40.0, series)
    return media


def cases_fixture():
    """④ GET /api/cases の見本: 案件 = スタジオの配信 1 本(候補 + 切り抜き 1 本)"""
    tx = {"id": "a0000000000a", "title": "切り抜き 1", "segments": 4, "proofed": 0, "cut": 0, "updatedAt": 1}
    c = {"id": VID, "kind": "", "caseKind": "stream", "root": "", "title": "雑談配信(案件の候補のテスト)", "channel": "配信者 A",
         "marks": {"total": 4, "adopted": 1, "exported": 0, "candidates": 3},
         "clips": [{"markId": "m9", "label": "切り抜き 1", "start": 100, "end": 130, "path": "", "exists": True, "transcript": tx, "transcripts": 1,
                    "transcriptIds": [tx["id"]], "pack": None, "auto": None, "state": "proofing"}]}
    yt = {"id": YT_ID, "kind": "", "caseKind": "stream", "root": "", "title": "埋め込みできない配信", "channel": "星見ルナ",
          "marks": {"total": 3, "adopted": 0, "exported": 0, "candidates": 3}, "clips": []}
    return {"cases": [c, yt], "virtual": [], "unlinked": [], "todoOrder": []}


def start_portal():
    """入口にスタジオを取り込む(fixture で使った serve をそのまま取り込ませる = データの置き場所が同じ)"""
    sys.modules[mount.MOUNTS["studio"]["alias"]] = serve
    sup = L.Supervisor(SRC, only=["studio"], mounts=("studio",), log=lambda m: None)
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sup.start("studio")
    if not sup.by_id["studio"].snapshot()["mounted"]:
        raise SystemExit("入口に取り込めませんでした")
    serve.Handler.log_message = lambda self, fmt, *a: None
    return srv, port


def studio_video(port, vid=VID):
    req = urllib.request.Request("http://127.0.0.1:%d/studio/api/video?id=%s" % (port, vid), headers={"Host": "127.0.0.1:%d" % port})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["video"]


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-cases-cand-")
    fixture(tmp)
    patches = [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")}),
               mock.patch.object(L.cases_mod, "snapshot", lambda _root, env=None: cases_fixture())]
    for p in patches:
        p.start()
    srv, port = start_portal()
    base = "http://127.0.0.1:%d/" % port
    errors, bad_status = [], []
    hp = os.path.join(datadir.locate("app", SRC), "prefs.json")   # inplace = .data/app/prefs.json
    had_prefs = os.path.isfile(hp)

    def marks():
        return studio_video(port)["marks"]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--mute-audio"])
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(m.text) if counts_as_error(m) else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: bad_status.append("%s %s" % (r.status, r.url)) if r.status >= 400 else None)
                sent_tx, runs = [], []

                def run_of(body):
                    return {"id": "r%d" % len(sent_tx), "kind": "video", "videoId": body.get("id"), "state": "queued", "mode": body.get("mode"),
                            "modeLabel": "文字起こしまで", "marks": body.get("marks"), "steps": [{"label": "書き出し", "state": "queued"}]}

                def fake_tx_start(route):   # 入口のまとめて実行(書き出しのあとの自動の文字起こし・まとめて実行)は頼んだ中身だけ見る
                    raw = json.loads(route.request.post_data or "{}")   # ② の口 {envelope, spec}(RV A1)-> 以前の形 {id, mode, marks} で覚える
                    env, run = raw.get("envelope") or {}, (raw.get("spec") or {}).get("run") or {}
                    mode = ("transcribe" if run.get("upto") == "transcribe" else "adopted") if run.get("from") == "export" else "full"
                    body = {"id": (env.get("input") or {}).get("videoId"), "mode": mode, "marks": (env.get("input") or {}).get("marks")}
                    sent_tx.append(body)
                    runs[:] = [run_of(body)]
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"run": runs[0]}))
                pg.route("**/api/flow/submit", fake_tx_start)
                pg.route("**/api/flow/estimate", lambda route: route.fulfill(status=200, content_type="application/json",
                                                                             body=json.dumps({"steps": [{"label": "書き出し", "count": 1}]})))
                pg.route("**/api/flow/runs", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"runs": runs})))

                # 1. 候補のパネルが載る(review.js を読んで、パネルの箱の中に作る)
                pg.goto(base + "cases?c=%s#cand" % VID)
                check(wait_js(pg, "!!document.querySelector('#csPane .cd-panel #rvList .rv-mark-row[data-id=\"m1\"]')", 20000), "候補のパネルにマークの一覧が出る")
                check(pg.evaluate("CasesShell.state().panel") == "cand" and pg.evaluate("location.search + location.hash") == "?c=%s#cand" % VID, "殻: 候補のタブ・URL")
                check(pg.evaluate("document.querySelectorAll('#csPane #rvList .rv-mark-row').length") == 5, "マーク 5 件(手 2 + 自動 3)")
                check(pg.is_hidden("[data-cd-status]"), "読み込めたら案内は消える")
                check(pg.evaluate("!!document.querySelector('script[src=\"studio/review.js\"]')"), "部品はスタジオの review.js(相対パス)を読む")
                # 1b. 外から来る文字列(題名・ラベル)は文字のまま
                check(pg.input_value("#rvTitle") == XSS_TITLE, "配信の題名は文字のまま")
                check(pg.input_value('#rvList .rv-mark-row[data-id="x1"] [data-f="label"]') == XSS_LABEL, "マークのラベルは文字のまま")

                # 2. 再生(webm)と盛り上がりグラフ
                check(wait_js(pg, "(() => { const v = document.querySelector('#rvHost video'); return !!v && v.readyState > 0; })()", 15000), "動画ファイルのプレーヤーが準備できる")
                check(pg.is_visible("#rvGraph") and pg.locator("#rvGSvg .rv-g-area").count() == 1, "盛り上がりグラフが出る")
                n_peaks = pg.locator("#rvGPeaks .rv-gpeak").count()
                check(1 <= n_peaks <= 5, "山の札: %d" % n_peaks)
                peak_t = float(pg.get_attribute("#rvGPeaks .rv-gpeak >> nth=0", "data-t"))
                pg.click("#rvGPeaks .rv-gpeak >> nth=0")
                check(wait_js(pg, "Math.abs(document.querySelector('#rvHost video').currentTime - %s) < 1.5" % max(0, peak_t - 5), 5000), "山の札で 5 秒前へ")

                # 3. 採用 / 不採用がスタジオに保存される
                first = pg.get_attribute("#rvList .rv-mark-row.auto", "data-id")
                row = '#rvList .rv-mark-row[data-id="%s"]' % first
                pg.click(row + ' [data-act="st"][data-st="adopted"]')
                check(wait_js(pg, "document.querySelector('#rvSave').dataset.k === 'saved'", 8000) and
                      next(m for m in marks() if m["id"] == first)["status"] == "adopted", "採用がスタジオに保存される")
                pg.click(row + ' [data-act="st"][data-st="rejected"]')
                wait_js(pg, "document.querySelector('#rvSave').dataset.k === 'saved'", 8000)
                time.sleep(0.3)
                check(next(m for m in marks() if m["id"] == first)["status"] == "rejected", "不採用もスタジオに保存される")

                # 3b. 開始・終了は時刻の欄(UIKit.timebox): 数字だけ打って Enter で確定 → 保存・欄の中の ← → は再生位置を動かさない(旧 check_review_timebox)
                M1 = '#rvList .rv-mark-row[data-id="m1"]'
                pg.evaluate("document.querySelector('#rvHost video').pause()")
                pg.click(M1 + " .rv-tc")
                pg.evaluate("document.querySelector('#rvHost video').pause()")
                pg.locator(M1 + ' [data-f="end"]').focus()
                pg.keyboard.type("000080")   # 0:00:08.0
                pg.keyboard.press("Enter")
                check(wait_js(pg, "(() => { const el = document.querySelector('%s [data-f=\"end\"]'); return UIKit.timebox.get(el) === 8 && document.activeElement === el; })()"
                              % M1.replace("'", "\\'"), 3000), "終了の欄に数字だけ → Enter で確定し、フォーカスは欄のまま")
                end = time.time() + 8
                while time.time() < end and next(m for m in marks() if m["id"] == "m1")["end"] != 8:
                    time.sleep(0.2)
                check(next(m for m in marks() if m["id"] == "m1")["end"] == 8, "時刻の欄の変更がスタジオに保存される")
                now0 = pg.input_value("#rvNow")
                pg.locator(M1 + ' [data-f="start"]').focus()
                pg.keyboard.press("ArrowRight")
                pg.keyboard.press("ArrowRight")
                time.sleep(0.3)
                check(pg.input_value("#rvNow") == now0, "時刻の欄の中の ← → は再生位置を動かさない(殻のキーとパネルのキーへ行かない): %s → %s" % (now0, pg.input_value("#rvNow")))
                pg.evaluate("document.activeElement && document.activeElement.blur()")

                # 4. キー: 殻の keydown 1 本からパネルへ(y = 採用・n = 今をマーク・? = キー操作の一覧)
                pg.evaluate("document.querySelector('#rvHost video').pause()")
                pg.click('#rvFilters [data-filter=""]')
                pg.click("#rvList .rv-mark-row.st-cand .rv-tc")
                sel = pg.evaluate("document.querySelector('#rvList .rv-mark-row.sel').dataset.id")
                pg.keyboard.press("y")
                time.sleep(0.2)
                check(pg.evaluate("id => !document.querySelector('#rvList .rv-mark-row[data-id=\"' + id + '\"]')", sel), "y キーで採用(候補の絞り込みから消える)")
                pg.click('#rvFilters [data-filter="all"]')
                pg.evaluate("document.activeElement && document.activeElement.blur()")
                n0 = pg.evaluate("document.querySelectorAll('#rvList .rv-mark-row').length")
                pg.keyboard.press("n")
                check(wait_js(pg, "document.querySelectorAll('#rvList .rv-mark-row').length === %d" % (n0 + 1), 3000), "n キーで今をマーク(殻のキーと重ならない)")
                end = time.time() + 8
                while time.time() < end and len(marks()) != n0 + 1:
                    time.sleep(0.2)
                check(len(marks()) == n0 + 1, "今をマークがスタジオに保存される")
                # ? のキー操作の一覧・キー配置の組み合わせ・下の帯の文字は画面の道に入れない(写真の関所で見る)

                # 4c. まとめて実行(入口の /api/flow/submit。偽物で頼んだ中身だけ見る): 配信ごと・マークの行の「この後を ▸」(旧 check_review_autorun)
                check(pg.is_visible("#rvAuto"), "「まとめて実行」が出る(入口の中)")
                pg.click("#rvAuto > summary")
                pg.click('#rvAuto [data-auto="transcribe"]')
                check(wait_js(pg, "!document.querySelector('#rvAutoBar').hidden && /文字起こしまで/.test(document.querySelector('#rvAutoBar').textContent)", 10000),
                      "始めると、同じパネルに進み具合の帯が出る: %s" % (pg.text_content("#rvAutoBar") or "")[:60])
                check(bool(sent_tx) and sent_tx[-1].get("id") == VID and sent_tx[-1].get("mode") == "transcribe" and not sent_tx[-1].get("marks"),
                      "この配信の「文字起こしまで」を入口に頼む: %s" % sent_tx[-1:])
                row_pop = M1 + " .rv-rowmore"
                check(pg.locator(row_pop).count() == 1, "採用したマークの行に「…」(その他の操作)")
                pg.click(row_pop + " > summary")
                pg.click(row_pop + " [data-act=auto1]")
                end = time.time() + 8
                while time.time() < end and len(sent_tx) < 2:
                    pg.wait_for_timeout(200)   # 同期版の route は Playwright を呼んでいる間しか動かない(time.sleep では届かない)
                check(len(sent_tx) == 2 and sent_tx[-1].get("marks") == ["m1"] and sent_tx[-1].get("mode") == "adopted",
                      "「この後を ▸」はこのマークだけ: %s" % sent_tx[-1:])
                runs[:] = []   # 帯は 10 分より前に終わった実行を出さない = 空にすれば消える
                sent_tx[:] = []

                # 5. 採用が無いと「書き出す」は押せず理由を出す → 書き出し → 済みの行・「編集で開く」(相対パス)・自動の文字起こしを頼む
                for m in pg.eval_on_selector_all("#rvList .rv-mark-row.st-adopted", "els => els.map(e => e.dataset.id)"):
                    pg.click('#rvList .rv-mark-row[data-id="%s"] [data-act="st"][data-st=""]' % m)
                wait_js(pg, "document.querySelector('#rvSave').dataset.k === 'saved'", 8000)
                check(not pg.is_enabled("#rvExpRun"), "採用が無いとき「書き出す」は押せない")
                pg.click('#rvList .rv-mark-row[data-id="m1"] [data-act="st"][data-st="adopted"]')
                wait_js(pg, "document.querySelector('#rvSave').dataset.k === 'saved'", 8000)
                check(pg.is_enabled("#rvExpRun"), "1 件採用すると押せる")
                pg.click('#rvJump [data-jump="export"]')
                check(wait_js(pg, "!document.querySelector('#rvExport').hidden", 3000), "書き出しの欄が開く")
                pg.click("#rvExpRun")
                check(wait_js(pg, "!!document.querySelector('#rvExpList .rv-ejob.st-ok')", 90000), "書き出しが済む")
                href = pg.get_attribute("#rvExpList .rv-ejob.st-ok a[data-edit-open]", "href") or ""
                path = urllib.parse.unquote(href.split("?v=", 1)[1].split("#", 1)[0]) if "?v=" in href else ""
                check(href.startswith("/cases?v=") and href.endswith("#proof") and os.path.isfile(path),
                      "「編集で開く」は案件の画面(/cases?v=…#proof)で、実在する mp4: %s" % href[:80])
                check(wait_js(pg, "!!document.querySelector('#rvList .rv-mark-row[data-id=\"m1\"].st-exported')", 10000), "書き出し済みの印")
                end = time.time() + 8
                while not sent_tx and time.time() < end:
                    pg.wait_for_timeout(200)
                check(bool(sent_tx) and sent_tx[0].get("mode") == "transcribe" and sent_tx[0].get("marks") == ["m1"], "書き出しのあと自動で文字起こしを頼む: %s" % sent_tx[:1])
                pg.keyboard.press("Escape")
                wait_js(pg, "document.querySelector('#rvExport').hidden", 3000)
                # 書き出した切り抜きを文字起こしした(文書を置く)→ 戻ってきたら、マークにセリフが元の配信の時刻で出る(旧 check_review_export の後半)
                txdir = os.path.join(os.environ["TRANSCRIBE_DATA_DIR"], "transcripts")
                os.makedirs(txdir, exist_ok=True)
                with open(os.path.join(txdir, "e2etx0000001.json"), "w", encoding="utf-8") as f:
                    json.dump({"id": "e2etx0000001", "title": "セリフ", "sourcePath": path, "updatedAt": 1, "speakers": [{"id": "S1", "name": "話者1"}],
                               "segments": [{"id": "s1", "start": 1.0, "end": 2.0, "text": "こんにちは", "speaker": "S1", "proofed": True},
                                            {"id": "s2", "start": 2.5, "end": 3.5, "text": XSS_LABEL, "cutState": "cut"}]}, f, ensure_ascii=False)

                # 6. 画面を離れたら再生を止める(殻の UIKit.life → パネルの leave)・戻ったら読み直す(パネルの back)
                pg.evaluate("document.querySelector('#rvHost video').play().catch(() => {})")
                wait_js(pg, "!document.querySelector('#rvHost video').paused", 3000)
                pg.evaluate("""() => { const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
                    set(true); document.dispatchEvent(new Event('visibilitychange')); }""")
                check(wait_js(pg, "document.querySelector('#rvHost video').paused", 3000), "離れたら再生を止める")
                pg.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
                    document.dispatchEvent(new Event('visibilitychange')); delete document.hidden; }""")
                TX = M1 + " .rv-tx"
                check(wait_js(pg, "document.querySelectorAll('%s-line').length === 2" % TX, 10000), "戻ると読み直して、書き出したマークにセリフ(文字起こし)が出る")
                check("校正 1/2" in (pg.text_content(TX + " summary") or ""), "セリフの行数と校正の進み具合")
                tcs = pg.eval_on_selector_all(TX + "-line", "els => els.map(e => e.dataset.t)")
                m1_start = next(m for m in marks() if m["id"] == "m1")["start"]
                check(len(tcs) == 2 and abs(float(tcs[0]) - (m1_start + 1.0)) < 0.01, "セリフの時刻は元の配信の時刻(切り抜きの開始 + 行の時刻): %s" % tcs)
                check(pg.evaluate("window.__xss === undefined") and pg.locator("#rvList .rv-tx img").count() == 0, "セリフ・題名・ラベルの HTML は実行・表示されない")
                pg.click(TX + " summary")
                pg.click(TX + "-line >> nth=0")
                check(wait_js(pg, "Math.abs(document.querySelector('#rvHost video').currentTime - %s) < 1.2" % float(tcs[0]) if tcs else "false", 5000),
                      "セリフの行を押すと、その時刻から再生する")
                pg.evaluate("document.querySelector('#rvHost video').pause()")

                # 6b. 一瞬をマーク(C。前・後の秒数は設定に保存)・つなげて1本に(旧 check_review_moment_join)
                pg.fill("#rvMomBefore", "1.5")
                pg.press("#rvMomBefore", "Tab")
                pg.evaluate("document.activeElement && document.activeElement.blur()")
                pg.evaluate("document.querySelector('#rvHost video').currentTime = 20")
                time.sleep(0.3)
                n_marks = len(marks())
                pg.keyboard.press("c")
                end = time.time() + 10
                while time.time() < end and not any(m.get("label") == "一瞬" for m in marks()):
                    time.sleep(0.2)
                mom = [m for m in marks() if m.get("label") == "一瞬"]
                check(len(marks()) == n_marks + 1 and len(mom) == 1 and abs((mom[0]["end"] - mom[0]["start"]) - 4.5) < 0.01 and mom[0]["status"] == "adopted",
                      "C でマーク「一瞬」(採用)が前 1.5 秒・後 3.0 秒でできる: %s" % [(m["start"], m["end"], m["status"]) for m in mom])
                end = time.time() + 5
                while time.time() < end and (serve.STORE.get_ui().get("review") or {}).get("momentBefore") != 1.5:
                    time.sleep(0.2)
                check((serve.STORE.get_ui().get("review") or {}).get("momentBefore") == 1.5, "前の秒数はスタジオの設定に保存される")
                if mom:
                    before_st = {m["id"]: m["status"] for m in marks()}
                    wait_js(pg, "!!document.querySelector('#rvList .rv-mark-row[data-id=\"%s\"]')" % mom[0]["id"], 5000)
                    for mid in ("m1", mom[0]["id"]):
                        pg.check('#rvList .rv-mark-row[data-id="%s"] .rv-join' % mid)
                    pg.click('#rvJump [data-jump="export"]')
                    wait_js(pg, "!document.querySelector('#rvExport').hidden", 3000)
                    check(pg.is_visible("#rvJoinRun") and pg.is_enabled("#rvJoinRun") and "2 件" in pg.inner_text("#rvJoinRun"), "2 件チェックすると「つなげて1本に」が押せる")
                    pg.click("#rvJoinRun")
                    check(wait_js(pg, "[...document.querySelectorAll('#rvExpList .rv-ejob.st-ok')].some(r => (r.textContent || '').includes('つないだ1本'))", 90000),
                          "つないだ1本ができる")
                    check({m["id"]: m["status"] for m in marks()} == before_st, "つないでも、マークの状態は変えない")
                    pg.keyboard.press("Escape")
                    wait_js(pg, "document.querySelector('#rvExport').hidden", 3000)

                # 7. 切り抜きの行へ移る = パネルを片付ける(キーが効かない・プレーヤーが無い)→ 戻ると作り直す・前回の場所(旧 check_review_place)に戻る
                pg.evaluate("document.querySelector('#rvHost video').pause()")
                pg.click(M1 + " .rv-tc")
                pg.evaluate("document.querySelector('#rvHost video').pause()")
                pg.fill("#rvNow", "0:21.5")
                pg.press("#rvNow", "Enter")
                wait_js(pg, "(() => { const p = JSON.parse(localStorage.getItem('ytt:studio.place') || '{}')['%s']; return !!p && Math.abs(p[0] - 21.5) < 0.3; })()" % VID, 6000)
                pg.click("#csRail [data-cs-key='d:a0000000000a']")
                check(wait_js(pg, "CasesShell.state().panel === 'proof' && !document.querySelector('#csPane .cd-panel')", 5000), "切り抜きを選ぶと候補のパネルは外れる")
                n1 = len(marks())
                pg.keyboard.press("n")
                time.sleep(1.2)
                check(len(marks()) == n1, "外れたパネルのキー(n)は効かない")
                check(not pg.evaluate("document.querySelector('.ui-keybar') && document.querySelector('.ui-keybar').textContent.includes('今をマーク')"), "下の帯から候補のキーが消える")
                pg.click("#csRail [data-cs-key='cand']")
                check(wait_js(pg, "!!document.querySelector('#csPane .cd-panel #rvList .rv-mark-row[data-id=\"m1\"].st-exported')", 15000), "戻ると作り直して、書き出し済みのまま出る")
                check(pg.evaluate("document.querySelectorAll('#csPane .cd-panel').length") == 1 and pg.evaluate("document.querySelectorAll('#rvHost video').length") == 1,
                      "箱もプレーヤーも 1 つだけ")
                check(wait_js(pg, "(() => { const v = document.querySelector('#rvHost video'); return !!v && v.readyState > 0 && Math.abs(v.currentTime - 21.5) < 0.6; })()", 8000)
                      and pg.evaluate("document.querySelector('#rvHost video').paused"), "開き直すと前の再生位置から(自動では再生しない): %s" % pg.input_value("#rvNow"))

                # 7b. 1720: 書き出しの引き出しは横に並べて開き(docked)、映像・マークに重ならない(旧 check_review_drawer)
                pg.set_viewport_size({"width": 1720, "height": 900})
                check(wait_js(pg, "!document.querySelector('#rvExport').hidden", 3000), "1720: 書き出しの引き出しはいつも開いている")
                geo = pg.evaluate("['#rvPlayerBox', '#rvClipbox', '#rvExport'].map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right]; })")
                check(geo[0][1] <= geo[2][0] + 1 and geo[1][1] <= geo[2][0] + 1, "1720: 引き出しは映像・マークに重ならない: %s" % geo)
                pg.set_viewport_size({"width": 1440, "height": 900})
                check(wait_js(pg, "document.querySelector('#rvExport').hidden", 3000), "1440 に戻すと、並べていた引き出しは閉じる")

                # 8. 幅 390: 重ねて開いた書き出しの欄の裏では、配信のキー(→・採用)が効かない(B-2。旧 check_narrow_contrast)。
                # 横にはみ出さないことは ui_audit の A-20 が見る
                pg.set_viewport_size({"width": 390, "height": 800})
                pg.goto(base + "cases?c=%s#cand" % VID)
                check(wait_js(pg, "!!document.querySelector('#rvList .rv-mark-row')", 20000), "390 でも開ける")
                time.sleep(0.5)
                check(pg.evaluate("document.querySelector('#rvJump').classList.contains('is-bar')"), "390: プレーヤー・マーク・書き出しへ飛ぶ案内")
                check(wait_js(pg, "(() => { const v = document.querySelector('#rvHost video'); return !!v && v.readyState > 0; })()", 10000), "390: プレーヤーの準備")
                pg.evaluate("document.querySelector('#rvHost video').pause()")
                pg.click('#rvJump [data-jump="export"]')
                check(wait_js(pg, "!document.querySelector('#rvExport').hidden", 3000) and pg.is_visible("#rvExpRun"), "390: 「書き出し」で引き出しが重ねて開く")
                n2, now2 = len(marks()), pg.input_value("#rvNow")
                pg.evaluate("document.activeElement && document.activeElement.blur()")
                pg.keyboard.press("ArrowRight")
                pg.keyboard.press("n")
                time.sleep(0.8)
                check(pg.input_value("#rvNow") == now2 and len(marks()) == n2, "重ねて開いている間は、裏の配信のキー(→・今をマーク)が効かない: %s → %s" % (now2, pg.input_value("#rvNow")))
                pg.click("#rvExpClose")
                check(wait_js(pg, "document.querySelector('#rvExport').hidden", 3000), "閉じるボタンで引き出しを閉じる")
                pg.set_viewport_size({"width": 1440, "height": 900})

                # 10. YouTube のプレーヤーが使えないとき: 1 か所に知らせる・判定は保存できる・自動では知らせず、自分で再生を押したときだけ(旧 check_player_unavailable)
                pg.route("https://www.youtube.com/**", lambda route: route.abort())
                pg.goto(base + "cases?c=%s#cand" % YT_ID)
                check(wait_js(pg, "!!document.querySelector('#rvList .rv-mark-row[data-id=\"y0\"]')", 20000), "YouTube の配信の案件を開ける")
                check(wait_js(pg, "!document.querySelector('#rvNotice').hidden && document.querySelector('#rvNotice').textContent.includes('再生できません')", 15000),
                      "プレーヤーが使えないことを、プレーヤーの下に 1 か所だけ出す")
                pg.click('#rvList .rv-mark-row[data-id="y0"] .rv-tc')
                for k in ("]", "[", "y"):
                    pg.keyboard.press(k)
                    time.sleep(0.12)
                end = time.time() + 8
                while time.time() < end and not any(m["status"] == "adopted" for m in studio_video(port, YT_ID)["marks"]):
                    time.sleep(0.2)
                check(any(m["status"] == "adopted" for m in studio_video(port, YT_ID)["marks"]), "プレーヤーが使えなくても判定は保存される")
                pg.unroute("https://www.youtube.com/**")

                check(not errors, "コンソールのエラーなし: %s" % errors[:3])
                check(not bad_status, "4xx / 5xx の応答なし: %s" % bad_status[:3])
            finally:
                browser.close()
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        for p in patches:
            p.stop()
        if not had_prefs and os.path.isfile(hp):   # 入口の設定(inplace = .data/app/prefs.json)は最初から無かったときだけ片付ける
            os.remove(hp)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
