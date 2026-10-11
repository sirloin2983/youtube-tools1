#!/usr/bin/env python3
"""ホームの「作業データのバックアップ」(src/manage/keep/backup.py。docs/spec/data-location.md の「バックアップ」)の画面の確認(Playwright)。

    python src/home/tests/e2e_backup_ui.py

入口(server.py)は e2e_intake_ui.py と同じ形で動かす(ツールは起動しない)。バックエンドは本物:
作業データの代わりの一時フォルダを srv.backup.source に入れ、画面から 先を決める → オンにする → 写る → 今すぐ写す を通す。
確かめること: まだ決めていないときは開いて見せる / フォルダが空ではオンにできない / 作業データの中は断って「止まっています」/
正しい先なら保存 → すぐ1回写る(ファイルができる・キャッシュは写さない)/ 「今すぐ写す」/ 読み直しても設定が残る / コンソールのエラーなし。
"""
import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.append(os.path.dirname(HERE))   # src(app 層。入口本体は src/app/server.py)
from app import server as L  # noqa: E402
from test_launch import free_ports  # noqa: E402


def wait_js(pg, expr, timeout=15000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.1)
    return False


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-backup-ui-")
    patch = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")})
    patch.start()
    events = []
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=events.append, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    data = os.path.join(tmp, "作業データ")
    dest = os.path.join(tmp, "別のドライブ", "backup")
    put(os.path.join(data, "transcribe", "transcripts", "a.json"), "文書")
    put(os.path.join(data, "studio", "data.json"), "{}")
    put(os.path.join(data, "studio", "cache", "chat.json"), "x" * 50)
    srv.backup.source = data          # inplace のテストでは None(写さない)なので、一時フォルダを作業データに見立てる
    srv.backup.first_wait = 0.2
    srv.backup.start()
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/" % port
    out = os.path.join(dest, "youtube-tools-data")

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
                pg.goto(base)

                # 1. まだ決めていない: オフの札・開いて見せる・「今すぐ写す」は押せない
                check(wait_js(pg, "document.getElementById('backupState')?.textContent === 'オフ'"), "オフの札が出る: %s" % pg.text_content("#backupState"))
                check(pg.evaluate("document.getElementById('backupBox').open") is True, "まだ決めていないときは開いて見せる")
                check("フォルダを決めて" in pg.text_content("#backupMsg"), "案内が出る: %s" % pg.text_content("#backupMsg"))
                check(pg.is_disabled("#backupRunBtn"), "オフのときは「今すぐ写す」を押せない")
                check("未設定" in (pg.text_content("#backupFolderNow") or "") and (pg.get_attribute("#backupSettingsLink", "href") or "").endswith("settings#uiSetGroup-backup"),
                      "写す先は未設定と出て、「設定を変える」は設定の画面のバックアップの節へ(0.54.0: 欄は設定の画面)")

                # 2. フォルダが空ではオンにできない(送らない・スイッチは戻る)
                pg.click("#backupEnabled")
                check(wait_js(pg, "document.getElementById('backupSaveMsg').textContent.includes('写す先のフォルダ')"), "フォルダが空だと理由を出す: %s" % pg.text_content("#backupSaveMsg"))
                check(pg.is_checked("#backupEnabled") is False, "スイッチは元に戻る")

                # 3. 作業データの中は断る(保存はできるが、写すときに止まって理由を出す)
                srv.prefs.patch("backup", {"folder": os.path.join(data, "studio")})   # 0.54.0: 写す先は設定の画面(prefs)で
                pg.click("#backupEnabled")
                check(wait_js(pg, "document.getElementById('backupState').textContent === '止まっています'"), "作業データの中を選ぶと「止まっています」: %s" % pg.text_content("#backupState"))
                check("作業データの中" in pg.text_content("#backupMsg"), "理由が出る: %s" % pg.text_content("#backupMsg"))
                check(not os.path.exists(os.path.join(data, "studio", "youtube-tools-data", "studio")), "作業データの中には写していない")

                # 4. 正しい先: 保存 → すぐ1回写る
                srv.prefs.patch("backup", {"enabled": False, "folder": dest, "everyHours": 6})   # 写す先と間隔は設定の画面(prefs)で
                check(wait_js(pg, "!document.getElementById('backupEnabled').checked", 20000), "写す先を変えて止めた状態が画面に出る")
                pg.click("#backupEnabled")   # オンにする(スイッチだけを送る)
                check(wait_js(pg, "document.getElementById('backupEnabled').checked && document.getElementById('backupSaveMsg').textContent === ''", 10000), "オンにできる")
                check(wait_js(pg, "document.getElementById('backupLast').textContent.includes('最後に写した')", 20000), "写したあと「最後に写した」が出る: %s" % pg.text_content("#backupLast"))
                check(pg.text_content("#backupState") == "動いています", "札は「動いています」: %s" % pg.text_content("#backupState"))
                check("2 個" in pg.text_content("#backupLast"), "写した数が出る(キャッシュは数えない): %s" % pg.text_content("#backupLast"))
                check(os.path.isfile(os.path.join(out, "transcribe", "transcripts", "a.json")) and os.path.isfile(os.path.join(out, "studio", "data.json")), "ファイルが写っている")
                check(not os.path.exists(os.path.join(out, "studio", "cache")), "キャッシュは写さない")

                # 5. 今すぐ写す(増えた分だけ)
                put(os.path.join(data, "transcribe", "transcripts", "b.json"), "文書 2")
                pg.click("#backupRunBtn")
                end = time.time() + 15
                while time.time() < end and not os.path.isfile(os.path.join(out, "transcribe", "transcripts", "b.json")):
                    time.sleep(0.2)
                check(os.path.isfile(os.path.join(out, "transcribe", "transcripts", "b.json")), "「今すぐ写す」で増えた分が写る")

                # 6. 読み直しても設定が残る・動いているときは閉じたまま
                pg.reload()
                check(wait_js(pg, "document.getElementById('backupState')?.textContent === '動いています'"), "読み直しても「動いています」")
                check(pg.evaluate("document.getElementById('backupBox').open") is False, "動いているときは閉じたまま")
                pg.evaluate("document.getElementById('backupBox').open = true")
                check(dest in (pg.text_content("#backupFolderNow") or "") and "6 時間" in (pg.text_content("#backupFolderNow") or "") and pg.is_checked("#backupEnabled"), "設定が残っている: %s" % pg.text_content("#backupFolderNow"))
                bad = [e for e in errors if "404" not in e and "400" not in e]   # 400 = フォルダが空のままオンにして入口が断った(わざと起こしている)
                bad += ["404: " + u for u in notfound if "favicon" not in u and "/transcribe/api/" not in u]   # 編集は取り込んでいないテストなので 404 は想定内
                check(not bad, "コンソールのエラーなし: %s" % bad[:3])
            finally:
                browser.close()
    finally:
        try:
            srv.backup.close()
            srv.shutdown()
        except Exception:
            pass
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(str(e) for e in events[-20:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
