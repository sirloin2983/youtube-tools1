"""案件の画面(/cases)の「候補」のパネル(src/app/ui/cases/panels/cand.js。RS8 C2a)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.10 src/app/tests/e2e_cases_cand.py
入口(app/server.py)にスタジオを取り込んで動かす(スタジオの e2e_ui.py --mounted と同じ形。STUDIO_FAKE=1・生成した短い webm・一時フォルダだけ)。
④ の案件の一覧(cases_mod.snapshot)は見本に差し替え、案件の id = スタジオの配信の id にする。
見るもの(旧 e2e_ui.py の ② の場面から): パネルが載る(配信の選択は出さない)・動画を再生できる・盛り上がりグラフ・採用 / 不採用がスタジオに保存される・
キー(y・n・?)は殻の keydown からパネルへ届く・下の帯にパネルのキーと殻のキー・書き出し → 済みの行と「編集で開く」・離れたら再生を止める・
別の行(切り抜き)へ移るとパネルを片付ける(キーが効かない・プレーヤーが消える)・戻ると作り直す・幅 390 ではみ出さない・コンソールのエラーが無い。"""
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
sys.path.insert(0, os.path.join(SRC, "home"))
if SRC not in sys.path:
    sys.path.append(SRC)
import startup  # noqa: E402,F401  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
from ytt import studio_env  # noqa: E402
import serve  # noqa: E402
from app import server as L  # noqa: E402
import mount  # noqa: E402

VID = "fqa00000001"


def wait_js(pg, expr, timeout=15000):
    """CSP の画面では wait_for_function が動かないので evaluate を繰り返す"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.1)
    return False


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
    """スタジオの配信 1 本(手のマーク 1 + 自動のマーク 3 + 盛り上がりのグラフ)"""
    media = make_media(home)
    os.environ["STUDIO_FAKE_MEDIA"] = media
    os.environ["TRANSCRIBE_DATA_DIR"] = os.path.join(home, "txdata")
    store, _ = serve.init(home)
    store.ensure({"kind": "file", "videoId": VID, "name": "sample.webm", "path": media}, "雑談配信(案件の候補のテスト)")
    store.put_video(VID, "雑談配信(案件の候補のテスト)", [{"id": "m1", "start": 2, "end": 7, "label": "確認用", "status": "adopted"}])
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
    return {"cases": [c], "virtual": [], "unlinked": [], "todoOrder": []}


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


def studio_video(port):
    req = urllib.request.Request("http://127.0.0.1:%d/studio/api/video?id=%s" % (port, VID), headers={"Host": "127.0.0.1:%d" % port})
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
    hp = os.path.join(SRC, "home", "prefs.json")
    had_prefs = os.path.isfile(hp)

    def marks():
        return studio_video(port)["marks"]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: bad_status.append("%s %s" % (r.status, r.url)) if r.status >= 400 else None)
                sent_tx = []

                def fake_tx_start(route):   # 書き出しのあとの自動の文字起こし(入口のまとめて実行)は頼んだかだけ見る
                    sent_tx.append(json.loads(route.request.post_data or "{}"))
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"run": {"id": "txauto", "state": "queued"}}))
                pg.route("**/api/autorun/start", fake_tx_start)

                # 1. 候補のパネルが載る(review.js を読んで、パネルの箱の中に作る)
                pg.goto(base + "cases?c=%s#cand" % VID)
                check(wait_js(pg, "!!document.querySelector('#csPane .cd-panel #rvList .rv-mark-row[data-id=\"m1\"]')", 20000), "候補のパネルにマークの一覧が出る")
                check(pg.evaluate("CasesShell.state().panel") == "cand" and pg.evaluate("location.search + location.hash") == "?c=%s#cand" % VID, "殻: 候補のタブ・URL")
                check(pg.evaluate("document.querySelectorAll('#csPane #rvList .rv-mark-row').length") == 4, "マーク 4 件(手 1 + 自動 3)")
                check(pg.evaluate("getComputedStyle(document.querySelector('#rvPick')).display") == "none", "配信の選択(探す一覧)は出さない(案件は左の一覧で選ぶ)")
                check(pg.is_hidden("[data-cd-status]"), "読み込めたら案内は消える")
                check(pg.evaluate("!!document.querySelector('script[src=\"studio/review.js\"]')"), "部品はスタジオの review.js(相対パス)を読む")

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
                pg.keyboard.press("?")
                check(wait_js(pg, "document.querySelector('#keyHelp').open", 3000) and "今をマーク①" in (pg.text_content("#keyHelpBody") or ""), "? でキー操作の一覧(パネルの中のダイアログ)")
                pg.keyboard.press("Escape")
                check(wait_js(pg, "!document.querySelector('#keyHelp').open", 3000), "Esc で閉じる")
                kb = pg.text_content(".ui-keybar") or ""
                check("今をマーク①" in kb and "Space" in kb and "Shift+N" in kb, "下の帯にパネルのキーと殻のキー(Shift+N): %s" % kb[:120])

                # 5. 書き出し → 済みの行・「編集で開く」(相対パス)・自動の文字起こしを頼む
                pg.click('#rvList .rv-mark-row[data-id="m1"] [data-act="st"][data-st="adopted"]')
                for m in pg.eval_on_selector_all("#rvList .rv-mark-row.st-adopted", "els => els.map(e => e.dataset.id)"):
                    if m != "m1":
                        pg.click('#rvList .rv-mark-row[data-id="%s"] [data-act="st"][data-st=""]' % m)
                wait_js(pg, "document.querySelector('#rvSave').dataset.k === 'saved'", 8000)
                pg.click('#rvJump [data-jump="export"]')
                check(wait_js(pg, "!document.querySelector('#rvExport').hidden", 3000), "書き出しの欄が開く")
                pg.click("#rvExpRun")
                check(wait_js(pg, "!!document.querySelector('#rvExpList .rv-ejob.st-ok')", 90000), "書き出しが済む")
                href = pg.get_attribute("#rvExpList .rv-ejob.st-ok a[data-edit-open]", "href") or ""
                path = urllib.parse.unquote(href.split("?media=", 1)[1]) if "?media=" in href else ""
                check(href.startswith("transcribe/?media=") and os.path.isfile(path), "「編集で開く」は相対パスで、実在する mp4: %s" % href[:80])
                check(wait_js(pg, "!!document.querySelector('#rvList .rv-mark-row[data-id=\"m1\"].st-exported')", 10000), "書き出し済みの印")
                end = time.time() + 8
                while not sent_tx and time.time() < end:
                    time.sleep(0.2)
                check(bool(sent_tx) and sent_tx[0].get("mode") == "transcribe" and sent_tx[0].get("marks") == ["m1"], "書き出しのあと自動で文字起こしを頼む: %s" % sent_tx[:1])
                pg.keyboard.press("Escape")
                wait_js(pg, "document.querySelector('#rvExport').hidden", 3000)

                # 6. 画面を離れたら再生を止める(殻の UIKit.life → パネルの leave)
                pg.evaluate("document.querySelector('#rvHost video').play().catch(() => {})")
                wait_js(pg, "!document.querySelector('#rvHost video').paused", 3000)
                pg.evaluate("""() => { const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
                    set(true); document.dispatchEvent(new Event('visibilitychange')); }""")
                check(wait_js(pg, "document.querySelector('#rvHost video').paused", 3000), "離れたら再生を止める")
                pg.evaluate("""() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
                    document.dispatchEvent(new Event('visibilitychange')); delete document.hidden; }""")

                # 7. 切り抜きの行へ移る = パネルを片付ける(キーが効かない・プレーヤーが無い)→ 戻ると作り直す
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

                # 8. 幅 390: 横にはみ出さない
                pg.set_viewport_size({"width": 390, "height": 800})
                pg.goto(base + "cases?c=%s#cand" % VID)
                check(wait_js(pg, "!!document.querySelector('#rvList .rv-mark-row')", 20000), "390 でも開ける")
                time.sleep(0.5)
                check(pg.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth + 1"),
                      "390 で横にはみ出さない: %s" % pg.evaluate("[document.scrollingElement.scrollWidth, document.scrollingElement.clientWidth]"))

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
        if not had_prefs and os.path.isfile(hp):   # 入口の設定(inplace = src/home/prefs.json)は最初から無かったときだけ片付ける
            os.remove(hp)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
