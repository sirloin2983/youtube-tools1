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
  3b. P2 マークと書き出し: 再生しながら I → O(Edge。chromium では API でマーク)→「終了をマークしたら書き出す」で
     録画待ち → 取得 → 30fps → 済み(30/1・長さ・.clip.json の source.kind live)→ 文字起こしへ(偽のまとめて実行)・N(直前の秒数)・
     ラベルの変更・録画待ちの取り消し・マークの削除
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
from ytt_core import normalize, schemas  # noqa: E402
from test_launch import free_ports  # noqa: E402


def wait_js(pg, expr, timeout=20000):
    """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.15)
    return False


def datetime_of(iso):
    from datetime import datetime
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()


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
    # 書き出し(P2): 記録・書き出し先は一時フォルダ・文字起こしへは偽のまとめて実行
    out_dir = os.path.join(tmp, "out")
    srv.live.store_dir = os.path.join(tmp, "live")
    srv.live.out_dir = lambda: out_dir
    handed = []

    class FakeRunner:
        def start_file(self, path, title="", flow="check", **kw):
            handed.append((path, flow))
            return {"id": "run-%d" % len(handed)}

        def snapshot(self):
            return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち"} for i in range(len(handed))]}
    fake_runner = FakeRunner()
    srv.live.runner = lambda: fake_runner

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
                # 3b. マークと書き出し(P2)
                check(pg.evaluate("document.getElementById('marksBox').hidden") is False, "再生するとマークの欄が出る")
                check(pg.evaluate("document.getElementById('autoExport').checked && document.getElementById('autoTx').checked"),
                      "既定: 終了をマークしたら書き出す・文字起こしへ")
                if edge:
                    pg.evaluate("document.activeElement && document.activeElement.blur(); document.getElementById('player').play().catch(() => {})")   # 入力欄の外で・再生しながら
                    pg.keyboard.press("i")
                    check(wait_js(pg, "document.querySelectorAll('#marks .lv-mark').length === 1", 10000), "I で開始のマーク: %s" % pg.text_content("#markMsg"))
                    check("終了待ち" in pg.text_content("#marks"), "開始だけのマークは「終了待ち」")
                    time.sleep(3)
                    pg.keyboard.press("o")
                else:   # chromium は H.264 を再生できない(再生位置の時刻が取れない)ので、録画の時刻で API から付けて「書き出す」を押す
                    rec_id = pg.evaluate("document.querySelector('.lv-item[data-state=\"recording\"]').getAttribute('data-rec')")
                    st = json.loads(urllib.request.urlopen(urllib.request.Request(
                        "http://127.0.0.1:%d/live/%s/status" % (rport, rec_id), headers={"Authorization": "Bearer " + rtoken}), timeout=5).read())
                    from datetime import datetime, timedelta
                    t0 = datetime.strptime(st["firstPdt"], "%Y-%m-%dT%H:%M:%S.%fZ")
                    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)
                    pg.evaluate("""([rec, a, b]) => fetch('api/marks', {method: 'POST', headers: {'Content-Type': 'application/json',
                        'X-YTT-Token': document.querySelector('meta[name="ytt-token"]').content},
                        body: JSON.stringify({op: 'add', recorder: 'local', recording: rec, start: a, end: b})}).then(r => r.status)""",
                                [rec_id, iso(t0 + timedelta(seconds=0.5)), iso(t0 + timedelta(seconds=3.5))])
                    check(wait_js(pg, "document.querySelectorAll('#marks .lv-mark').length === 1", 10000), "マークが一覧に出る")
                    pg.click("#marks .lv-mark button:has-text('書き出す')")
                check(wait_js(pg, "(() => { const li = document.querySelector('#marks .lv-mark'); return li && li.getAttribute('data-export') === 'done'; })()", 90000),
                      "録画待ち → 取得 → 30fps → 済み: %s / %s" % (pg.evaluate("(document.querySelector('#marks .lv-mark') || {}).textContent"),
                                                              pg.text_content("#markMsg")))
                if not srv.live.exporter.jobs:
                    raise SystemExit("書き出しのジョブができませんでした")
                jobs = srv.live.exporter.snapshot()
                done = [j for j in jobs if j["state"] == "done"]
                if done:
                    info = normalize.probe(done[0]["path"])
                    check(normalize.is_30fps(info), "書き出した動画は 30/1: %s" % (info or {}).get("r_frame_rate"))
                    want = (datetime_of(done[0]["end"]) - datetime_of(done[0]["start"]))
                    check(abs((info or {}).get("duration", 0) - want) <= 0.1, "長さが区間と同じ: %s / %s" % ((info or {}).get("duration"), want))
                    clip, warn = schemas.load_clip_file(schemas.find_clip_path(done[0]["path"]))
                    check(clip and clip["source"]["kind"] == "live", ".clip.json の source.kind は live: %s" % warn)
                    check(os.path.dirname(os.path.dirname(done[0]["path"])) == out_dir, "スタジオの書き出し先の配信の名前のフォルダ: %s" % done[0]["path"])
                    check(handed == [(done[0]["path"], "check")], "文字起こしへ渡した(まとめて実行の文字起こしだけ): %s" % handed)
                    check(wait_js(pg, "/文字起こし: 待ち/.test(document.getElementById('marks').textContent)", 10000), "画面に文字起こしの状態")
                pg.fill("#marks .lv-mark .lv-label", "見どころ")
                pg.press("#marks .lv-mark .lv-label", "Enter")
                time.sleep(0.8)
                labels = [m.get("label") for m in srv.live.exporter.marks.load("local", srv.live.exporter.jobs[0]["recording"])["marks"]]
                check(labels == ["見どころ"], "ラベルを保存: %s" % labels)
                if edge:   # N = 直前の秒数(自動で書き出さないようにして)
                    pg.click("#autoExport")
                    pg.evaluate("document.activeElement && document.activeElement.blur(); document.getElementById('player').play().catch(() => {})")
                    pg.keyboard.press("n")
                    check(wait_js(pg, "document.querySelectorAll('#marks .lv-mark').length === 2", 10000), "N で直前の秒数のマーク: %s" % pg.text_content("#markMsg"))
                    pg.click("#autoExport")
                    pg.click("#marks .lv-mark[data-export=''] button:has-text('削除')")
                    check(wait_js(pg, "document.querySelectorAll('#marks .lv-mark').length === 1", 10000), "マークを消せる")
                # 録画待ちの取り消し(まだ録れていない先の時刻のマークを API で付けて、画面で取り消す)
                rec_id = srv.live.exporter.jobs[0]["recording"]
                far, _ = srv.live.exporter.marks.apply("local", rec_id, {"op": "add", "start": "2099-01-01T00:00:00Z", "end": "2099-01-01T00:00:10Z"})
                srv.live.exporter.add("local", rec_id, far["id"], transcribe=False)
                check(wait_js(pg, "!!document.querySelector('#marks .lv-mark[data-export=\"wait\"]')", 10000), "録画待ちの札")
                pg.click("#marks .lv-mark[data-export=\"wait\"] button:has-text('取り消し')")
                check(wait_js(pg, "!!document.querySelector('#marks .lv-mark[data-export=\"cancelled\"]')", 10000), "取り消せる")
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
        srv.live.close()
        srv.shutdown()
        srv.server_close()
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
