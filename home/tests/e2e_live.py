#!/usr/bin/env python3
"""リアルタイム切り抜き(試験中。線 D の P1)の画面の確認(Playwright)。本物の YouTube には繋がない。

    py -3.10 home/tests/e2e_live.py [--shots <フォルダ>]

入口(launch.py)は e2e_backup_ui.py と同じ形で動かす(ツールは起動しない)。録画の部品は本物(recorder/recorder.py)を
--source direct で別のプロセスとして動かし、ffmpeg の lavfi で作った HLS を手元の HTTP サーバーで配信中のように出して録る。

確かめること:
  1. オフ: ホームの「詳しく」に「試験中の機能」のスイッチ(オフ)があり、録画の画面へのリンクは出ない・/live/ は 404
  2. オンにする → リンクが出る → 録画の画面: 録画元につながる・置き場所と空き容量
  3. 録画を始める → 一覧に「録画中」→ 再生(hls.js): 再生リストを読めた・セグメントを読めた・致命的なエラーなし。
     Edge(H.264 を再生できる)があれば、実際に再生が進む・シークできることまで(Playwright 同梱の chromium は H.264 を再生できない)
  4. 停止(確認の窓)→「停止」・終わった録画も再生できる
  5. 置き場所を無いドライブにする → 案内が出て「録画を始める」は押せない
  6. 狭い画面で横にはみ出さない・コンソールのエラーなし
"""
import argparse
import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "recorder", "tests"))
import launch as L  # noqa: E402
import hls_fixture as F  # noqa: E402
from test_launch import free_ports  # noqa: E402


def wait_js(pg, expr, timeout=20000):
    """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.15)
    return False


def missing_drive():
    used = {d for d in string.ascii_uppercase if os.path.exists(d + ":\\")}
    return next((d for d in "QRSTUVWXYZ" if d not in used), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-live-ui-")
    patch = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")})
    patch.start()
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=lambda m: None, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % port

    # 録画の部品(本物。direct)と、配信中のふりをする HLS
    src_dir = os.path.join(tmp, "src")
    segs = F.make_source(src_dir, 60)
    live_src = F.LiveServer(src_dir, segs, start=4, rate=1.0)
    live_src.end = False
    rport = free_ports(1)[0]
    rdata, rfolder = os.path.join(tmp, "recdata"), os.path.join(tmp, "live-rec")
    rproc = subprocess.Popen([sys.executable, os.path.join(REPO, "recorder", "recorder.py"), "--port", str(rport), "--data-dir", rdata,
                              "--folder", rfolder, "--source", "direct", "--hls-time", "1", "--quiet"],
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    tok = os.path.join(rdata, "token.txt")
    end = time.time() + 20
    while time.time() < end and not os.path.isfile(tok):
        time.sleep(0.2)
    with open(tok, encoding="ascii") as f:
        rtoken = f.read().strip()
    # 録画元の一覧(この部品だけ。オンにするのは画面のスイッチで)
    srv.prefs.patch("live", {"recorders": [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % rport, "token": rtoken}]})

    errors, notfound = [], []
    try:
        with sync_playwright() as p:
            try:
                browser, edge = p.chromium.launch(channel="msedge"), True
            except Exception:
                browser, edge = p.chromium.launch(), False
            print("ブラウザ: %s" % ("Edge(H.264 の再生まで確かめる)" if edge else "Playwright の chromium(再生は読み込みまで)"), flush=True)
            try:
                ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: notfound.append(r.url) if r.status == 404 else None)
                pg.on("dialog", lambda d: d.accept())

                # 1. オフ
                pg.goto(base)
                pg.evaluate("document.getElementById('advancedBox').open = true")
                check(wait_js(pg, "!!document.getElementById('labBox') && !document.getElementById('labBox').hidden"), "「試験中の機能」が出る")
                check(pg.evaluate("document.getElementById('liveEnabled').checked") is False, "既定はオフ")
                check(pg.evaluate("document.getElementById('liveLink').hidden") is True, "オフの間は録画の画面へのリンクを出さない")
                try:
                    urllib.request.urlopen(base + "live/", timeout=5)
                    check(False, "オフの間は /live/ が 404")
                except urllib.error.HTTPError as e:
                    check(e.code == 404, "オフの間は /live/ が 404: %s" % e.code)
                check(not [u for u in notfound if "/live" in u], "ホームの画面は /live/ を読みに行かない: %s" % notfound)
                notfound.clear()

                # 2. オンにする
                pg.click("#liveEnabled")
                check(wait_js(pg, "document.getElementById('liveLink').hidden === false"), "オンにするとリンクが出る")
                check(srv.prefs.get(["live"])["live"]["enabled"] is True, "設定に残る")
                pg.click("#liveLink")
                check(wait_js(pg, "location.pathname === '/live/'"), "録画の画面へ移る")
                check(wait_js(pg, "document.getElementById('recState').textContent.indexOf('つながっています') === 0", 15000),
                      "録画元につながる: %s" % pg.text_content("#recState"))
                check(os.path.normcase(pg.text_content("#recFolder")) == os.path.normcase(rfolder), "置き場所: %s" % pg.text_content("#recFolder"))
                check("GB" in pg.text_content("#recFree") or "MB" in pg.text_content("#recFree"), "空き容量: %s" % pg.text_content("#recFree"))
                check(pg.evaluate("document.getElementById('startBtn').disabled") is False, "録画を始められる")

                # 3. 録画 → 再生
                pg.fill("#startUrl", live_src.url)
                pg.fill("#startTitle", "テストの配信<b>")
                pg.click("#startBtn")
                check(wait_js(pg, "document.querySelector('.lv-item[data-state=\"recording\"]') !== null", 30000),
                      "一覧に「録画中」: %s" % pg.evaluate("document.getElementById('list').textContent"))
                check(pg.evaluate("document.querySelector('.lv-item b').textContent") == "テストの配信<b>", "名前は文字のまま(HTML にしない)")
                time.sleep(4)   # 数セグメント録る
                pg.click(".lv-item[data-state=\"recording\"] button:has-text('再生')")
                check(wait_js(pg, "document.getElementById('player').getAttribute('data-manifest') === '1'", 20000), "hls.js が再生リストを読めた")
                check(wait_js(pg, "Number(document.getElementById('player').getAttribute('data-frags') || 0) >= 1", 20000), "セグメントを読めた")
                if edge:
                    check(wait_js(pg, "document.getElementById('player').currentTime > 0.5", 20000), "再生が進む(Edge)")
                    pg.evaluate("(() => { const v = document.getElementById('player'); v.currentTime = Math.max(0, v.seekable.start(0) + 0.5); })()")
                    check(wait_js(pg, "(() => { const v = document.getElementById('player'); return !v.seeking && v.currentTime < 3; })()", 15000),
                          "頭へシークできる(Edge): %s" % pg.evaluate("document.getElementById('player').currentTime"))
                    check(wait_js(pg, "/再生位置の時刻 /.test(document.getElementById('playerClock').textContent)", 10000),
                          "再生位置の時刻(受信時刻)を出す: %s" % pg.text_content("#playerClock"))
                    pg.click("#playerLive")
                    check(wait_js(pg, "document.getElementById('player').currentTime > 3", 10000), "ライブに戻る(Edge)")
                    check(not pg.evaluate("document.getElementById('player').getAttribute('data-error')"),
                          "致命的なエラーなし: %s" % pg.evaluate("document.getElementById('player').getAttribute('data-error')"))
                else:
                    err = pg.evaluate("document.getElementById('player').getAttribute('data-error')") or ""
                    check(not err or "codec" in err.lower() or "buffer" in err.lower(), "致命的なエラーは H.264 を再生できないことだけ: %s" % err)
                if a.shots:
                    os.makedirs(a.shots, exist_ok=True)
                    pg.screenshot(path=os.path.join(a.shots, "live-recording.png"), full_page=True)

                # 4. 停止
                pg.click(".lv-item[data-state=\"recording\"] button:has-text('停止')")
                check(wait_js(pg, "document.querySelector('.lv-item[data-state=\"stopped\"]') !== null", 30000), "停止できる")
                pg.click(".lv-item[data-state=\"stopped\"] button:has-text('再生')")
                check(wait_js(pg, "document.getElementById('player').getAttribute('data-manifest') === '1'", 20000), "終わった録画も読める")
                if edge:
                    check(wait_js(pg, "isFinite(document.getElementById('player').duration) && document.getElementById('player').duration > 3", 20000),
                          "終わった録画は長さが決まる: %s" % pg.evaluate("document.getElementById('player').duration"))
                pg.click("#playerClose")

                # 5. 無いドライブ
                d = missing_drive()
                if d:
                    pg.click(".lv-folder summary")
                    pg.fill("#folderInput", d + ":\\Video\\live-rec")
                    pg.click("#folderSave")
                    check(wait_js(pg, "/保存しました/.test(document.getElementById('folderMsg').textContent)"), "置き場所を保存: %s" % pg.text_content("#folderMsg"))
                    check(srv.live.tick() == "running", "見回りが録画の部品に置き場所を伝える")
                    check(wait_js(pg, "document.getElementById('recGuide').hidden === false && document.getElementById('recGuide').textContent.indexOf('%s:') >= 0" % d, 15000),
                          "無いドライブの案内: %s" % pg.text_content("#recGuide"))
                    check(pg.evaluate("document.getElementById('startBtn').disabled") is True, "無いドライブでは始められない")

                # 6. 狭い画面
                pg.set_viewport_size({"width": 375, "height": 800})
                time.sleep(0.5)
                check(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
                      "狭い画面で横にはみ出さない: %s" % pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]"))
                if a.shots:
                    pg.screenshot(path=os.path.join(a.shots, "live-narrow.png"), full_page=True)
                bad = [e for e in errors if "404" not in e]   # 404 は下で URL ごとに見る(ホームはツールを取り込んでいないテストなので、ツールの API の 404 は想定内)
                check(not bad, "コンソールのエラーなし: %s" % bad[:5])
                check(not [u for u in notfound if "favicon" not in u], "録画の画面に 404 なし: %s" % notfound[:5])
            finally:
                browser.close()
    finally:
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/live/quit" % rport, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + rtoken})
            urllib.request.urlopen(req, timeout=5)
            rproc.wait(20)
        except Exception:
            rproc.kill()
        live_src.close()
        srv.shutdown()
        srv.server_close()
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
