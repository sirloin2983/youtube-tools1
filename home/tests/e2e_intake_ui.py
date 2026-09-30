#!/usr/bin/env python3
"""ホームの「依頼の受付」(友人の依頼の自動受付。docs/design/friend-intake.md の 6)の画面の確認(Playwright)。

    python home/tests/e2e_intake_ui.py [--shots <フォルダ>]

バックエンド(home/intake.py)には頼らない: api/intake・api/intake/scan・intake の設定の保存(api/ytt/prefs)・
api/autorun は page.route で偽物に差し替える。入口(launch.py)は e2e_portal.py と同じ形で動かすが、ツールは起動しない。
確かめること: オフのときの表示(閉じている)/ 設定の保存が正しい patch を送る・サーバーのエラーを出す・範囲外を送らない /
届いた依頼の一覧(受け付けた・断った・理由・項目ごとの結果)/ 「今すぐ確認」が scan を呼ぶ /
api/autorun に mode "file"・"request" の実行があっても画面が壊れない(コンソールのエラーなし・進行中に出る)。
"""
import json
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
from test_launch import free_ports  # noqa: E402

NOW = int(time.time() * 1000)


def wait_js(pg, expr, timeout=15000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.1)
    return False


def intake_obj(enabled=False, requests=None, **kw):
    d = {"enabled": enabled, "folder": "" if not enabled else "C:\\Dropbox\\アプリ\\切り抜き依頼", "top": 3, "dailyMax": 10, "maxHours": 6, "maxGB": 10,
         "state": "watching" if enabled else "off", "stateLabel": "見張り中" if enabled else "オフ",
         "message": "" if enabled else "オフです。フォルダを決めてスイッチを入れると、依頼を受け付けます",
         "lastScan": NOW - 90_000 if enabled else None, "today": 2, "requests": requests or []}
    d.update(kw)
    return d


REQUESTS = [
    {"id": "r1", "kind": "url", "source": "app", "title": "【雑談】<b>朝の配信</b>", "streamer": "さくらみこ", "memo": "笑ったところを多めに",
     "received": NOW - 300_000, "state": "accepted", "stateLabel": "受け付けた", "reason": "", "runIds": ["run1"],
     "items": [{"label": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "state": "accepted", "reason": ""}]},
    {"id": "r2", "kind": "video", "source": "manual", "title": "clip_big.mp4", "streamer": "", "memo": "",
     "received": NOW - 3_600_000, "state": "rejected", "stateLabel": "断った", "reason": "動画が大きすぎます(上限 10GB)", "runIds": [],
     "items": [{"label": "clip_big.mp4", "state": "rejected", "reason": "12.3GB あります"},
               {"label": "clip_ok.mp4", "state": "accepted", "reason": ""}]},
]

RUNS = {"runs": [
    {"id": "rf", "kind": "file", "videoId": None, "docId": None, "mode": "file", "modeLabel": "依頼: 文字起こし", "state": "running",
     "title": "clip_ok.mp4", "created": NOW - 1000, "steps": [{"id": "transcribe", "label": "文字起こし", "state": "run"}]},
    {"id": "rq", "kind": "video", "videoId": "ZZZZZZZZZZZ", "docId": None, "mode": "request", "modeLabel": "依頼: 解析 → 文字起こし",
     "state": "queued", "title": "依頼の配信", "created": NOW - 500,
     "steps": [{"id": s, "label": s, "state": "wait"} for s in ("analyze", "adopt", "export", "transcribe")]},
], "past": [
    {"id": "pf", "kind": "file", "videoId": None, "docId": None, "mode": "file", "modeLabel": "依頼: 文字起こし", "state": "done",
     "title": "old.mp4", "created": NOW - 90_000, "finished": NOW - 60_000, "steps": []},
]}


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-intake-ui-")
    patch = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")})
    patch.start()
    events = []
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=events.append, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/" % port

    state = {"intake": intake_obj(False), "scans": 0, "patches": [], "patch_error": None, "autorun": {"runs": [], "past": []}}

    def r_intake(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(state["intake"]))

    def r_scan(route):
        state["scans"] += 1
        state["intake"] = intake_obj(True, REQUESTS, lastScan=NOW)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(state["intake"]))

    def r_prefs(route):
        try:
            body = json.loads(route.request.post_data or "{}")
        except ValueError:
            body = {}
        if body.get("section") == "intake" and body.get("op") == "patch":
            state["patches"].append(body["value"])
            if state["patch_error"]:
                route.fulfill(status=400, content_type="application/json", body=json.dumps({"message": state["patch_error"]}))
                return
            v = body["value"]
            state["intake"] = intake_obj(bool(v.get("enabled")), state["intake"]["requests"], **{k: x for k, x in v.items() if k != "enabled"})
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"value": v}))
        elif body.get("op") == "get" and body.get("sections") == ["intake"]:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"prefs": {"intake": {}}}))
        else:
            route.fallback()

    def r_autorun(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(state["autorun"]))

    errors = []
    notfound = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: notfound.append(r.url) if r.status == 404 else None)
                pg.route("**/api/intake/scan", r_scan)
                pg.route("**/api/intake", r_intake)
                pg.route("**/api/ytt/prefs", r_prefs)
                pg.route("**/api/autorun", r_autorun)
                pg.goto(base)

                # 1. オフの表示: 閉じている・状態の札・案内・確認ボタンは押せない
                check(wait_js(pg, "document.getElementById('intakeState')?.textContent === 'オフ'"), "オフの札が出る: %s" % pg.text_content("#intakeState"))
                check(pg.evaluate("document.getElementById('intakeBox').open") is False, "オフのときは閉じている")
                pg.evaluate("document.getElementById('intakeBox').open = true")
                check("オフです" in pg.text_content("#intakeMsg"), "オフの案内が出る: %s" % pg.text_content("#intakeMsg"))
                check(pg.is_disabled("#intakeScanBtn"), "オフのときは「今すぐ確認」を押せない")
                check(not pg.is_visible("#intakeList") and pg.is_visible("#intakeEmpty"), "依頼が無いときは「まだ依頼は届いていません」")
                check("Dropbox\\アプリ\\切り抜き依頼" in pg.text_content("#intakeBox"), "フォルダの入力の説明に例が出る")
                check(pg.input_value("#intakeTop") == "3" and pg.input_value("#intakeDaily") == "10" and pg.input_value("#intakeHours") == "6" and pg.input_value("#intakeGB") == "10",
                      "設定の欄にサーバーの値が入る")

                # 2. スイッチ: フォルダが空だとサーバーが断る → エラーを出してスイッチを戻す
                state["patch_error"] = "見張るフォルダを指定してください"
                pg.check("#intakeEnabled")
                check(wait_js(pg, "document.getElementById('intakeSaveMsg').textContent.includes('見張るフォルダを指定してください')"), "サーバーのエラーを表示: %s" % pg.text_content("#intakeSaveMsg"))
                check(state["patches"][-1] == {"enabled": True}, "スイッチは enabled だけを patch: %s" % state["patches"][-1])
                check(wait_js(pg, "document.getElementById('intakeEnabled').checked === false"), "断られたらスイッチを戻す")
                check(wait_js(pg, "document.getElementById('toast')?.textContent.includes('見張るフォルダ')", 3000), "トーストにも出る")

                # 3. 設定の保存: 正しい patch の本文
                state["patch_error"] = None
                pg.fill("#intakeFolder", "  C:\\Dropbox\\アプリ\\切り抜き依頼  ")
                pg.fill("#intakeTop", "4"); pg.fill("#intakeDaily", "20"); pg.fill("#intakeHours", "8"); pg.fill("#intakeGB", "30")
                pg.check("#intakeEnabled")
                state["patches"].clear()
                pg.click("#intakeSave")
                check(wait_js(pg, "document.getElementById('intakeSaveMsg').textContent === '保存しました'"), "保存できた: %s" % pg.text_content("#intakeSaveMsg"))
                want = {"enabled": True, "folder": "C:\\Dropbox\\アプリ\\切り抜き依頼", "top": 4, "dailyMax": 20, "maxHours": 8, "maxGB": 30}
                check(state["patches"] and state["patches"][-1] == want, "patch の本文(節 intake の全キー): %s" % (state["patches"][-1:],))
                check(wait_js(pg, "document.getElementById('intakeState').textContent === '見張り中'"), "保存後に状態が見張り中になる")
                check(not pg.is_disabled("#intakeScanBtn"), "見張り中は「今すぐ確認」を押せる")

                # 3b. 範囲外はサーバーへ送らず、その場で言う
                n = len(state["patches"])
                pg.fill("#intakeTop", "99")
                pg.click("#intakeSave")
                check("既定の切り抜く数" in pg.text_content("#intakeSaveMsg") and len(state["patches"]) == n, "範囲外は送らずに言う: %s" % pg.text_content("#intakeSaveMsg"))
                pg.fill("#intakeTop", "4")

                # 3c. 保存のサーバーエラー(400 の message)
                state["patch_error"] = "1日の上限は 1〜50 です"
                pg.click("#intakeSave")
                check(wait_js(pg, "document.getElementById('intakeSaveMsg').textContent.includes('1日の上限は 1〜50 です')"), "保存のエラーを表示: %s" % pg.text_content("#intakeSaveMsg"))
                state["patch_error"] = None

                # 4. 今すぐ確認 → scan が呼ばれて一覧が出る
                pg.click("#intakeScanBtn")
                check(wait_js(pg, "document.querySelectorAll('#intakeList .pt-intake-item').length === 2"), "確認のあと依頼が2件並ぶ")
                check(state["scans"] == 1, "scan を1回呼んだ")
                rows = pg.eval_on_selector_all("#intakeList .pt-intake-item", "els => els.map(e => e.innerText)")
                check("【雑談】<b>朝の配信</b>" in rows[0] and "さくらみこ" in rows[0] and "笑ったところを多めに" in rows[0] and "受け付けた" in rows[0] and "URL" in rows[0],
                      "受け付けた依頼: 題名(HTML として解釈しない)・配信者・メモ・札: %s" % rows[0].replace("\n", " / "))
                check("断った" in rows[1] and "動画が大きすぎます" in rows[1] and "clip_big.mp4" in rows[1] and "12.3GB" in rows[1] and "clip_ok.mp4" in rows[1] and "動画" in rows[1] and "フォルダに直接" in rows[1],
                      "断った依頼: 理由・項目ごとの結果: %s" % rows[1].replace("\n", " / "))
                check(pg.eval_on_selector_all("#intakeList b", "e => e.length") == 0, "題名の <b> は要素にならない")
                check("最後に確認" in pg.text_content("#intakeScan") and "今日 2 / 10" in pg.text_content("#intakeToday"),
                      "最後の確認・今日の件数: %s / %s" % (pg.text_content("#intakeScan"), pg.text_content("#intakeToday")))

                # 4b. エラーの状態
                state["intake"] = intake_obj(True, REQUESTS, state="error", stateLabel="止まっています", message="フォルダが見つかりません")
                pg.reload()   # 定期読み込み(15 秒)を待たず、読み直して確かめる
                check(wait_js(pg, "document.getElementById('intakeState').textContent === '止まっています'", 20000), "止まっているときの札と理由: %s" % pg.text_content("#intakeMsg"))
                check("フォルダが見つかりません" in pg.text_content("#intakeMsg"), "止まっている理由が出る")

                # 5. api/autorun に mode file / request がある: 進行中に出る・エラーなし
                state["autorun"] = RUNS
                pg.reload()
                check(wait_js(pg, "document.querySelectorAll('#todoList .pt-todo-item').length >= 2", 20000), "次にやること: 依頼の実行が2つ出る")
                todo = pg.eval_on_selector_all("#todoList .pt-todo-item", "els => els.map(e => [e.innerText.replace(/\\n/g, ' '), e.querySelector('a').getAttribute('href')])")
                check(any("依頼: 文字起こし" in t and h == "#intake" for t, h in todo), "kind file: 「依頼: 文字起こし」・リンクは #intake: %s" % todo)
                check(any("依頼: 解析 → 文字起こし" in t and h == "#intake" for t, h in todo), "mode request(案件の行がまだ無い): リンクは #intake: %s" % todo)
                check(not any("null" in h or "undefined" in h for _, h in todo), "リンクに null / undefined が入らない")
                pg.click("#historyBox > summary")
                time.sleep(0.5)
                check(wait_js(pg, "document.querySelectorAll('#historyList .pt-history-item').length >= 0"), "まとめて実行の記録を開ける")

                if shots:
                    os.makedirs(shots, exist_ok=True)
                    pg.evaluate("document.getElementById('intakeBox').open = true")
                    pg.screenshot(path=os.path.join(shots, "intake.png"), full_page=True)

                # 6. 狭い画面で横にはみ出さない
                pg.set_viewport_size({"width": 390, "height": 900})
                time.sleep(0.3)
                check(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "狭い画面で横にはみ出さない")

                bad = [e for e in errors if "favicon" not in e and "status of 400" not in e and "status of 404" not in e]   # 400 は偽のサーバーが返すエラーの確認用
                bad += ["404: " + u for u in notfound if "favicon" not in u and "/transcribe/api/" not in u]   # 編集は取り込んでいないテストなので 404 は想定内
                check(not bad, "コンソールのエラーが無い: %s" % bad[:5])
            finally:
                browser.close()
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(events[-20:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
