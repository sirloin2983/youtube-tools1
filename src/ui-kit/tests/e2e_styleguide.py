#!/usr/bin/env python3
"""見本(styleguide.html)の動作確認(Playwright・chromium・headless)。

    python src/ui-kit/tests/e2e_styleguide.py

ui-kit/ をそのまま python の http.server で1つのポートに乗せ、styleguide.html を開いて、画面の道(案件の画面などの e2e)では見えにくい部品の約束だけを確かめる:
合言葉(UIKit.http・homeApi: 合言葉を付ける先・ほかのオリジンに出さない)/
版の帯(UIKit.restart: 単体では案内だけ・合言葉があれば「起動し直す」→ 断られた理由・ping を待って読み込み直す・戻らなければ案内)/
録画中の札(UIKit.liveBadge: 合言葉の無いページでは問い合わせない)。
失敗の形・時間切れ・取り消し・raw・整形(fmt)・copy・問い合わせの間隔は test_uikit_stub.cjs。使う画面の細かい操作は画面の e2e と写真の関所 ui_audit が見る。
"""
import functools
import json
import http.server
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import sys
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ui-kit/(styleguide.html がある場所)

def start_static_server():
    handler_cls = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, th


def wait_js(page, expr, timeout=8000):
    try:
        page.wait_for_function(expr, timeout=timeout)
        return True
    except Exception:
        return False


def check_restart(browser, base, check):
    """版の帯(UIKit.restart): 単体では案内だけ / 合言葉があれば「起動し直す」→ 断られたら理由 → 頼めたら ping を待って読み込み直す / 戻らなければ案内"""
    st = {"calls": [], "mode": "refuse", "ping": 0, "ping_ok_after": 1}

    def on_restart(route):
        st["calls"].append(route.request.headers.get("x-ytt-token"))
        if st["mode"] == "refuse":
            route.fulfill(status=409, content_type="application/json",
                          body=json.dumps({"error": "busy", "message": "実行中の処理があります(文字起こし)。終わってから起動し直してください"}, ensure_ascii=False))
        else:   # まとめて実行の待ち・実行中は断らずに notice で知らせる
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "notice": "まとめて実行の待ち・実行中の 2 件は、起動し直したあとに続きから進めます"}, ensure_ascii=False))

    def on_ping(route):
        st["ping"] += 1
        if st["ping"] <= st["ping_ok_after"]:
            route.abort()   # 古い入口が終わって、新しい入口がまだ待ち受けていない間
        else:
            route.fulfill(status=200, content_type="application/json", body='{"app": "x", "version": "0.2.0"}')

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/api/ytt/restart-self", on_restart)
        pg.route("**/api/ping", on_ping)
        pg.goto(base + "styleguide.html")
        pg.wait_for_selector("#btnRestartBand")
        band = "#restartBandDemo"

        pg.click("#btnRestartBand")
        txt = pg.inner_text(band)
        check(pg.evaluate("!document.getElementById('restartBandDemo').hidden") and "v0.2.0" in txt and "v0.1.0" in txt and not pg.query_selector(band + " .ui-restart-btn"),
              "単体で開いた画面(合言葉なし)は版の案内だけで、「起動し直す」は出さない")

        # ホームから開いた画面(合言葉あり)
        pg.evaluate("const m = document.createElement('meta'); m.name = 'ytt-token'; m.content = 'tok-1'; document.head.appendChild(m);"
                    "window.__marker = 1; window.__texts = [];"
                    "new MutationObserver(() => window.__texts.push(document.getElementById('restartBandDemo').textContent))"
                    "  .observe(document.getElementById('restartBandDemo'), { childList: true, subtree: true, characterData: true });"
                    "window.__restartDemoOpts = { interval: 150, timeout: 6000, reload: () => { window.__reloaded = (window.__reloaded || 0) + 1; } };")
        pg.click("#btnRestartBand")
        check(pg.evaluate("UIKit.restart.available()") is True and pg.inner_text(band + " .ui-restart-btn") == "起動し直す",
              "合言葉があれば「起動し直す」のボタンが出る")

        pg.click(band + " .ui-restart-btn")
        check(wait_js(pg, "document.getElementById('restartBandDemo').getAttribute('data-ui-restart') === 'refused'"), "断られた(409)ら refused")
        check("実行中の処理があります(文字起こし)" in pg.inner_text(band), "断られた理由を帯に出す")
        check(pg.evaluate("!document.querySelector('#restartBandDemo .ui-restart-btn').disabled"), "断られたら、もう一度押せる")
        check(st["calls"] == ["tok-1"], "POST api/ytt/restart-self に合言葉(X-YTT-Token)を付ける: %s" % st["calls"])

        st["mode"], st["ping"] = "ok", 0
        pg.click(band + " .ui-restart-btn")
        check(wait_js(pg, "window.__reloaded === 1"), "頼めたら ping が戻るのを待って読み込み直す")
        check(pg.evaluate("window.__texts.some(t => t.includes('実行中の 2 件は、起動し直したあとに続きから進めます'))"),
              "待っている間の帯に、応答の notice(まとめて実行の続き)を出す")
        check(st["ping"] >= 2 and pg.get_attribute(band, "data-ui-restart") == "done", "一度答えなくなってから答えたら戻った扱い(ping %d 回)" % st["ping"])
        check(pg.evaluate("document.querySelector('#restartBandDemo .ui-restart-btn').disabled"), "起動し直している間はボタンを押せない")

        # 戻らなかった(ping がずっと答えない)
        st["ping"], st["ping_ok_after"] = 0, 10 ** 6
        pg.evaluate("window.__restartDemoOpts = { interval: 150, timeout: 700, reload: () => { window.__reloaded = 99; } }")
        pg.click("#btnRestartBand")
        pg.click(band + " .ui-restart-btn")
        check(wait_js(pg, "document.getElementById('restartBandDemo').getAttribute('data-ui-restart') === 'timeout'"), "決めた時間で戻らなければ timeout")
        check("start.bat" in pg.inner_text(band) and pg.evaluate("document.querySelector('#restartBandDemo .ui-restart-btn').hidden")
              and pg.evaluate("window.__reloaded") == 1, "戻らなければ start.bat の案内を出し、ボタンを隠す(読み込み直さない)")

        # 既定(location.reload)で本当に読み込み直す
        st["ping"], st["ping_ok_after"] = 0, 1
        pg.evaluate("window.__restartDemoOpts = { interval: 150, timeout: 6000 }")
        pg.click("#btnRestartBand")
        with pg.expect_navigation(timeout=10000):
            pg.click(band + " .ui-restart-btn")
        pg.wait_for_selector("#btnRestartBand")
        check(pg.evaluate("window.__marker") is None, "既定は location.reload で読み込み直す")
        check(not errs, "画面のエラーなし(版の帯): %s" % errs[:5])
    finally:
        ctx.close()


def live_no_token(ctx, base, check):
    """単体で開いた見本(合言葉なし)では、問い合わせも札もない"""
    pg2 = ctx.new_page()
    calls0 = []
    pg2.route("**/api/ytt/**", lambda r: (calls0.append(r.request.url), r.fulfill(status=404, body="{}")))
    pg2.goto(base + "styleguide.html")
    pg2.wait_for_selector("#iconGrid .ui-icon svg")
    pg2.wait_for_timeout(200)   # 問い合わせが来ないことは待たないと見えない
    check(not calls0 and pg2.query_selector(".ui-header-actions .ui-live") is None and pg2.evaluate("UIKit.liveBadge.get()") is None,
          "合言葉の無いページでは問い合わせも札もない: %s" % calls0)
    pg2.close()


def check_live(browser, base, check):
    """ヘッダーの「録画中」の札(UIKit.liveBadge)。合言葉の無いページでは問い合わせない(合言葉の漏れ止め)だけを見る。
    問い合わせの間隔は test_uikit_stub.cjs・札・一覧・停止の道は e2e_live_studio の _scene_badge_stop"""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        live_no_token(ctx, base, check)
    finally:
        ctx.close()


HTTP_JS = """async () => {
  const out = {};
  const run = async f => { try { const v = await f(); return { ok: v instanceof Response ? { response: v.status, text: await v.text() } : v }; }
    catch (e) { return { err: { isErr: e instanceof Error, message: e.message, code: e.code, status: e.status, body: e.body, same: e.data === e.body,
                                reason: e.reason, detail: e.detail } }; } };
  out.noToken = await run(() => UIKit.http('fake-api/ok', { method: 'POST', body: {}, needToken: true }));
  const m = document.createElement('meta'); m.name = 'ytt-token'; m.content = 'tok-h'; document.head.appendChild(m);
  out.get = await run(() => UIKit.http('fake-api/ok'));
  out.post = await run(() => UIKit.http('fake-api/ok', { body: { a: [1, 'あ'] } }));
  out.put = await run(() => UIKit.http('fake-api/ok', { method: 'put', body: { b: 2 } }));
  out.noTok = await run(() => UIKit.http('fake-api/ok', { body: { c: 3 }, token: false }));
  out.ownTok = await run(() => UIKit.http('fake-api/ok', { body: { d: 4 }, token: 'tok-own' }));
  out.cross = await run(() => UIKit.http('http://other.invalid/x', { method: 'POST' }));
  out.home = await run(() => UIKit.homeApi('fake-api/ok', { body: { e: 5 } }));
  out.homeUrl = [UIKit.homeUrl('api/ytt/prefs'), UIKit.homeUrl('/api/ytt/prefs'), UIKit.homeUrl('live/api/info')];
  return out;
}"""


def check_http(browser, base, check):
    """UIKit.http / homeApi(偽の API = page.route)。合言葉を付ける先・ほかのオリジンに出さない・homeApi・homeUrl。
    失敗の形(code / status / body)・時間切れ・取り消し・raw は test_uikit_stub.cjs"""
    seen = []

    def on_api(route):
        req = route.request
        seen.append({"name": req.url.split("/")[-1], "url": req.url, "method": req.method, "token": req.headers.get("x-ytt-token"),
                     "ctype": req.headers.get("content-type"), "body": req.post_data})
        route.fulfill(status=200, content_type="application/json", body='{"a": 1}')

    def on_other(route):
        req = route.request
        seen.append({"name": "cross", "url": req.url, "method": req.method, "token": req.headers.get("x-ytt-token")})
        route.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"}, body='{"cross": 1}')

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/fake-api/**", on_api)
        pg.route("http://other.invalid/**", on_other)
        pg.goto(base + "styleguide.html")
        pg.wait_for_selector("#iconGrid .ui-icon svg")
        r = pg.evaluate(HTTP_JS)
        by = {}
        for s in seen:
            by.setdefault(s["name"], []).append(s)
        oks = by.get("ok", [])

        check((r["noToken"].get("err") or {}).get("code") == "no_token" and oks and oks[0]["method"] == "GET",
              "needToken: 合言葉が無ければ送らずに code 'no_token': %s" % r["noToken"])
        check(r["get"].get("ok") == {"a": 1} and oks[0]["method"] == "GET" and oks[0]["token"] is None and oks[0]["body"] is None,
              "GET: 応答の JSON を返し、合言葉・本文は付けない: %s" % oks[:1])
        check(oks[1]["method"] == "POST" and oks[1]["token"] == "tok-h" and (oks[1]["ctype"] or "").startswith("application/json")
              and json.loads(oks[1]["body"]) == {"a": [1, "あ"]}, "body があれば POST・JSON・合言葉(meta ytt-token)を付ける: %s" % oks[1:2])
        check(oks[3]["token"] is None and oks[4]["token"] == "tok-own", "token: false なら付けない・文字列ならその値")
        cross = by.get("cross", [])
        check(r["cross"].get("ok") == {"cross": 1} and cross and all(c["token"] is None and c["method"] == "POST" for c in cross),
              "ほかのオリジンには合言葉を付けない(預けた合言葉を外へ出さない): %s" % cross)
        check(r["home"].get("ok") == {"a": 1} and oks[-1]["url"] == base + "fake-api/ok" and oks[-1]["token"] == "tok-h",
              "homeApi: 画面の 1 つ上(入口の直下)へ送る")
        check(r["homeUrl"] == [base + "api/ytt/prefs", base + "api/ytt/prefs", base + "live/api/info"], "homeUrl: 先頭の / は外して入口の直下: %s" % r["homeUrl"])
        check(not errs, "画面のエラーなし(http): %s" % errs[:5])
    finally:
        ctx.close()


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    httpd, th = start_static_server()
    base = "http://127.0.0.1:%d/" % httpd.server_address[1]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--mute-audio"])
            try:
                # 版の帯(UIKit.restart)。入口の API は偽物(page.route)。409 などはコンソールに出るので、別の窓(context)で確かめる
                check_restart(browser, base, check)

                # ヘッダーの録画中の札(UIKit.liveBadge)
                check_live(browser, base, check)

                # UIKit.http / homeApi。API は偽物(page.route)
                check_http(browser, base, check)
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        th.join(timeout=5)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
