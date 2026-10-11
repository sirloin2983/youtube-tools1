"""設定の画面(/settings。部品は src/home/settings/。設定を 1 つに S5)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    python src/home/tests/e2e_settings.py
入口(server.py)は e2e_backup_ui.py と同じ形で動かす(ツールは取り込まない = スタジオ・編集・分析の節は「動いていません」になる)。
見るもの: スキーマから節が描かれる・値を変えるとホームの設定(prefs)に保存され「保存しました」が出る・範囲の外は断って保存しない・
「標準に戻す」・when(リアルタイム切り抜きをオンにすると下の欄が出る)・検索・動いていないツールの節は無効・コンソールにエラーが無い。"""
import os
import sys
import tempfile
import threading
import time
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
from unittest import mock

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from app import server as L  # noqa: E402
from test_launch import free_ports  # noqa: E402


def wait_js(pg, expr, timeout=15000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.1)
    return False


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-settings-ui-")
    patch = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")})
    patch.start()
    events = []
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=events.append, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/" % port
    errors, notfound = [], []

    def mark(key):
        return pg.text_content('[data-ui-set-key="%s"] .ui-set-mark' % key) or ""

    def wait_mark(key, text, timeout=8000):
        return wait_js(pg, "(document.querySelector('[data-ui-set-key=\"%s\"] .ui-set-mark')||{}).textContent === %r" % (key, text), timeout)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={"width": 1280, "height": 1000})
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: notfound.append(r.url) if r.status == 404 else None)

                # 1. /settings/ → /settings に送られ、スキーマから節が描かれる
                pg.goto(base + "settings/")
                check(pg.url.endswith("/settings"), "/settings/ は /settings へ: %s" % pg.url)
                check(wait_js(pg, "!!document.querySelector('#sec-home [data-ui-set-key]')"), "ホームの節が描かれる")
                check(pg.evaluate("document.querySelectorAll('#stNav a').length") == 8, "左の目次は 8 節: %s" % pg.evaluate("document.querySelectorAll('#stNav a').length"))
                check(pg.evaluate("!!document.querySelector('#sec-general #uiSetTheme')"), "「全体」の節にテーマの欄(ui-kit の節をそのまま)")
                check(pg.evaluate("document.querySelectorAll('[data-ui-set-key]').length") > 80, "項目が 80 以上: %s" % pg.evaluate("document.querySelectorAll('[data-ui-set-key]').length"))

                # 2. 動いていないツールの節: 札と無効
                check(pg.text_content("#sec-studio h2").find("動いていません") >= 0, "スタジオの節に「動いていません」")
                check(pg.evaluate("[...document.querySelectorAll('#sec-studio input, #sec-studio select')].every(e => e.disabled)"), "スタジオの欄は無効")
                check(pg.evaluate("document.querySelectorAll('#sec-studio .ui-set-reset:not([hidden])').length") == 0, "無効の節に「標準に戻す」は出ない")
                check(pg.evaluate("document.querySelector('#stNav a[data-st-nav=\"studio\"]').classList.contains('st-nav-off')"), "目次でも薄く")

                # 3. 値を変える → 保存 → prefs に入る → 「標準に戻す」が出る
                top = "#" + pg.evaluate("UIKit.settingsForm.id('intake.top')")
                check(pg.input_value(top) == "3", "既定の 3 が入っている: %s" % pg.input_value(top))
                check(pg.evaluate("document.querySelector('[data-ui-set-key=\"intake.top\"] .ui-set-reset').hidden"), "既定のうちは「標準に戻す」を出さない")
                pg.fill(top, "5"); pg.dispatch_event(top, "change")
                check(wait_mark("intake.top", "保存しました"), "「保存しました」が出る: %r" % mark("intake.top"))
                check(srv.prefs.get(["intake"])["intake"]["top"] == 5, "prefs.json に 5 が入る: %s" % srv.prefs.get(["intake"])["intake"]["top"])
                check(not pg.evaluate("document.querySelector('[data-ui-set-key=\"intake.top\"] .ui-set-reset').hidden"), "既定と違うので「標準に戻す」が出る")
                check(wait_js(pg, "(document.querySelector('[data-ui-set-key=\"intake.top\"] .ui-set-mark')||{}).textContent === ''", 5000), "印は 2 秒で消える")

                # 4. 範囲の外は断る(保存しない)
                pg.fill(top, "99"); pg.dispatch_event(top, "change")
                check(wait_js(pg, "(document.querySelector('[data-ui-set-key=\"intake.top\"] .ui-set-mark')||{}).textContent.includes('数で入れてください')"), "範囲の外は理由を出す: %r" % mark("intake.top"))
                check(srv.prefs.get(["intake"])["intake"]["top"] == 5, "断ったときは保存しない")

                # 5. 標準に戻す
                pg.click('[data-ui-set-key="intake.top"] .ui-set-reset')
                check(wait_mark("intake.top", "保存しました"), "標準に戻すと保存される")
                check(srv.prefs.get(["intake"])["intake"]["top"] == 3 and pg.input_value(top) == "3", "3 に戻る")

                # 6. 入れ子の鍵(live.auto.after)と when(リアルタイム切り抜きをオンにすると下の欄が出る)
                check(pg.evaluate("document.querySelector('[data-ui-set-key=\"live.auto.after\"]').hidden"), "オフの間は「書き出したあと」の欄を隠す")
                pg.check("#" + pg.evaluate("UIKit.settingsForm.id('live.enabled')"))
                check(wait_mark("live.enabled", "保存しました"), "スイッチも保存される")
                check(wait_js(pg, "!document.querySelector('[data-ui-set-key=\"live.auto.after\"]').hidden"), "オンにすると欄が出る")
                after = "#" + pg.evaluate("UIKit.settingsForm.id('live.auto.after')")
                pg.select_option(after, "auto")
                check(wait_mark("live.auto.after", "保存しました"), "入れ子の鍵も保存される")
                lv = srv.prefs.get(["live"])["live"]
                check(lv["enabled"] is True and lv["auto"]["after"] == "auto" and lv["auto"]["cut"] == "", "prefs の live.auto.after だけが変わり、ほかは既定のまま: %s" % lv["auto"])

                # 7. 検索
                pg.fill("#stSearch", "バックアップ")
                check(wait_js(pg, "document.querySelector('#sec-home').classList.contains('st-nomatch') === false && document.querySelector('#sec-live').classList.contains('st-nomatch')"), "一致しない節は隠れる")
                n = pg.evaluate("document.querySelectorAll('[data-ui-set-key]:not(.ui-set-nomatch):not([hidden])').length")
                check(0 < n <= 4 and "件" in pg.text_content("#stCount"), "一致した項目だけ残る: %s(%s)" % (n, pg.text_content("#stCount")))
                pg.fill("#stSearch", "")
                check(wait_js(pg, "!document.querySelector('#sec-live').classList.contains('st-nomatch')"), "空にすると戻る")

                # 8. 読み直しても値が残る・コンソールにエラーが無い
                pg.reload()
                check(wait_js(pg, "!!document.querySelector('#sec-home [data-ui-set-key]')"), "読み直せる")
                check(pg.is_checked("#" + pg.evaluate("UIKit.settingsForm.id('live.enabled')")), "値が残っている")
                bad = [e for e in errors if "404" not in e]
                bad += ["404: " + u for u in notfound if "favicon" not in u and "/studio/" not in u and "/transcribe/" not in u and "/analytics/" not in u]   # ツールは取り込んでいないので 404 は想定内
                check(not bad, "コンソールのエラーなし: %s" % bad[:3])
            finally:
                browser.close()
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
