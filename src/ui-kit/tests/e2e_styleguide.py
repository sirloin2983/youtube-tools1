#!/usr/bin/env python3
"""ui-kit v6(画面の全面見直し notes:docs/design/briefs/ui-overhaul/ の段階1)の見本(styleguide.html)の動作確認(Playwright・chromium・headless)。

    python src/ui-kit/tests/e2e_styleguide.py

ui-kit/ をそのまま python の http.server で1つのポートに乗せ、styleguide.html を開いて、画面の道(案件の画面などの e2e)では見えにくい部品の約束だけを確かめる:
合言葉と失敗の形(UIKit.http・homeApi: 合言葉を付ける先・ほかのオリジンに出さない・失敗の code / status / body・時間切れ・取り消し・raw)/
版の帯(UIKit.restart。v10: 単体では案内だけ・合言葉があれば「起動し直す」→ 断られた理由・ping を待って読み込み直す・戻らなければ案内)/
録画中の札(UIKit.liveBadge。合言葉の無いページでは問い合わせない・問い合わせの間隔と隠れたタブ)/ 時間・日付の整形(UIKit.fmt)と UIKit.copy。
テーマ・引き出し・確認ダイアログ・通知・下の帯・共通の再生キー・アイコン・時刻の欄・札の一覧の細かい操作は外した(テストの見直し 10-18。
使う画面の e2e と写真の関所 ui_audit が見る)。
"""
import functools
import json
import http.server
import os
import re
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
    """版の帯(UIKit.restart。v10・段9 9-3): 単体では案内だけ / 合言葉があれば「起動し直す」→ 断られたら理由 → 頼めたら ping を待って読み込み直す / 戻らなければ案内"""
    st = {"calls": [], "mode": "refuse", "ping": 0, "ping_ok_after": 1}

    def on_restart(route):
        st["calls"].append(route.request.headers.get("x-ytt-token"))
        if st["mode"] == "refuse":
            route.fulfill(status=409, content_type="application/json",
                          body=json.dumps({"error": "busy", "message": "実行中の処理があります(文字起こし)。終わってから起動し直してください"}, ensure_ascii=False))
        else:   # v20: まとめて実行の待ち・実行中は断らずに notice で知らせる(入口 0.41.0)
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
        check(pg.evaluate("!document.getElementById('restartBandDemo').hidden") and "版が違います" in txt and "v0.2.0" in txt and "v0.1.0" in txt,
              "版の帯: 画面とサーバーの版を出す")
        check("黒い画面を閉じて" in txt and not pg.query_selector(band + " .ui-restart-btn"),
              "単体で開いた画面(合言葉なし)は今までの案内だけで、「起動し直す」は出さない")
        check(pg.evaluate("UIKit.restart.check(document.createElement('div'), '1.0', '1.0')") is False, "check: 版が同じなら何もしない(false)")

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
        check(pg.evaluate("window.__texts.some(t => t.includes('起動し直しています'))"), "待っている間は「起動し直しています…」")
        check(pg.evaluate("window.__texts.some(t => t.includes('起動し直しています') && t.includes('実行中の 2 件は、起動し直したあとに続きから進めます'))"),
              "v20: 応答の notice(まとめて実行の続き)も待つ間の帯に出す")
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


def live_rec(rid="20261005-185300-U972n0ncl4k", **kw):
    r = {"recorder": "r1", "id": rid, "title": "<b>テスト</b> 配信", "state": "recording", "active": True, "seconds": 100, "endedAt": None, "url": "https://www.youtube.com/watch?v=U972n0ncl4k"}
    r.update(kw)
    return r


class LiveFake:
    """入口の api/ytt/live の偽物(page.route に渡す)と、見本の HTML に合言葉を差し込む route。
    st: mode(off / on / abort / 404)・recs(返す録画の一覧)・calls(届いた問い合わせ)・stops(届いた停止)"""

    def __init__(self):
        self.st = {"mode": "off", "recs": [], "calls": [], "stops": []}

    def on_html(self, route):
        resp = route.fetch()
        body = resp.text().replace("</head>", '<meta name="ytt-token" content="tok-live"></head>', 1)
        body = re.sub(r'<section class="card" id="liveBadgeDemo">.*?</section>', "", body, flags=re.S)   # 見本の静的な札は、本物の札と同じ class なので外す
        route.fulfill(response=resp, body=body)

    def on_api(self, route):
        st = self.st
        req = route.request
        if not req.url.endswith("/api/ytt/live"):
            route.fulfill(status=404, content_type="application/json", body="{}")
            return
        body = json.loads(req.post_data or "{}")
        if body.get("op") == "stop":
            st["stops"].append((req.headers.get("x-ytt-token"), body))
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
            return
        st["calls"].append((req.headers.get("x-ytt-token"), body, req.method))
        if st["mode"] == "abort":
            route.abort()
        elif st["mode"] == "404":
            route.fulfill(status=404, content_type="application/json", body='{"error": "not found"}')
        elif st["mode"] == "off":
            route.fulfill(status=200, content_type="application/json", body='{"enabled": false}')
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"enabled": True, "recordings": st["recs"]}, ensure_ascii=False))


def live_no_token(ctx, base, check):
    """単体で開いた見本(合言葉なし)では、問い合わせも札もない"""
    pg2 = ctx.new_page()
    calls0 = []
    pg2.route("**/api/ytt/**", lambda r: (calls0.append(r.request.url), r.fulfill(status=404, body="{}")))
    pg2.goto(base + "styleguide.html")
    pg2.wait_for_selector("#iconGrid .ui-icon svg")
    pg2.wait_for_timeout(300)
    check(not calls0 and pg2.query_selector(".ui-header-actions .ui-live") is None and pg2.evaluate("UIKit.liveBadge.get()") is None,
          "合言葉の無いページでは問い合わせも札もない: %s" % calls0)
    pg2.close()


def live_interval(ctx, base, fake, check):
    """問い合わせの間隔(10 秒 / オフは 60 秒)と、隠れているタブでは問い合わせない(偽の時計で進める)"""
    st = fake.st
    import datetime
    pg4 = ctx.new_page()
    pg4.route("**/styleguide.html", fake.on_html)
    pg4.route("**/api/ytt/**", fake.on_api)
    st["mode"], st["recs"], st["calls"] = "off", [], []
    pg4.clock.install()
    pg4.goto(base + "styleguide.html")
    pg4.wait_for_selector("#iconGrid .ui-icon svg")
    check(wait_js(pg4, "UIKit.liveBadge.get() !== null"), "(時計) 最初の答え")
    pg4.clock.pause_at(datetime.datetime.now() + datetime.timedelta(seconds=1))
    n0 = len(st["calls"])
    pg4.clock.run_for(56000)
    pg4.wait_for_timeout(150)
    check(len(st["calls"]) == n0, "オフのときは 60 秒たつまで問い合わせない(約 57 秒: %d → %d)" % (n0, len(st["calls"])))
    pg4.clock.run_for(4000)
    pg4.wait_for_timeout(250)
    check(len(st["calls"]) == n0 + 1, "オフは 60 秒後に問い合わせる: %d → %d" % (n0, len(st["calls"])))
    st["mode"], st["recs"] = "on", [live_rec()]
    pg4.clock.run_for(61000)
    pg4.wait_for_timeout(250)
    check(pg4.query_selector(".ui-live:not([hidden])") is not None, "(時計) 60 秒後の問い合わせでオンになり、札が出る")
    n1 = len(st["calls"])
    pg4.clock.run_for(10500)
    pg4.wait_for_timeout(250)
    check(len(st["calls"]) == n1 + 1, "オンのときは 10 秒ごと: %d → %d" % (n1, len(st["calls"])))
    pg4.evaluate("Object.defineProperty(document, 'hidden', {get: () => true, configurable: true})")
    n2 = len(st["calls"])
    pg4.clock.run_for(35000)
    pg4.wait_for_timeout(150)
    check(len(st["calls"]) == n2, "隠れているタブは問い合わせない: %d → %d" % (n2, len(st["calls"])))
    pg4.evaluate("delete document.hidden")
    pg4.clock.run_for(10500)
    pg4.wait_for_timeout(250)
    check(len(st["calls"]) > n2, "見えるようになったら問い合わせを再開する: %d → %d" % (n2, len(st["calls"])))
    pg4.close()


def check_live(browser, base, check):
    """ヘッダーの「録画中」の札(UIKit.liveBadge。v16・線 D の P3)。入口の API(api/ytt/live)は偽物(page.route)。
    合言葉の無いページでは問い合わせない(合言葉の漏れ止め)・問い合わせの間隔(偽の時計)だけを見る。札・一覧・停止の道は e2e_live_studio の _scene_badge_stop"""
    fake = LiveFake()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        live_no_token(ctx, base, check)
        live_interval(ctx, base, fake, check)
    finally:
        ctx.close()


def check_v24_fmt_copy(pg, base, check):
    """v24: fmt.day・fmt.dur の opt(floor・tenths・noHours)と UIKit.copy(クリップボード。写せなければ execCommand の予備・知らせ)"""
    got = pg.evaluate("""() => [UIKit.fmt.dur(59.6), UIKit.fmt.dur(59.6, { floor: true }), UIKit.fmt.dur(83.44, { tenths: true }),
        UIKit.fmt.dur(3723.96, { tenths: true }), UIKit.fmt.dur(3723, { noHours: true }), UIKit.fmt.dur(3723.7, { floor: true }), UIKit.fmt.dur(-5),
        UIKit.fmt.day(new Date(2020, 0, 2, 3, 4).getTime()), UIKit.fmt.day(0)]""")
    check(got == ["1:00", "0:59", "1:23.4", "1:02:04.0", "62:03", "1:02:03", "0:00", "2020/1/2", ""],
          "v24: fmt.dur は省略なら四捨五入のまま・floor = 切り捨て・tenths = 0.1 秒まで・noHours = 時を出さない、fmt.day = 日付だけ: %s" % got)
    try:
        pg.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base.rstrip("/"))
    except Exception:
        pass
    res = pg.evaluate("""async () => {
        const ok = await UIKit.copy('コピーのテスト 1', { ok: '写しました(テスト)' });
        let back = null; try { back = await navigator.clipboard.readText(); } catch (e) { back = null; }
        const toast = [...document.querySelectorAll('.ui-toast')].some(t => t.textContent.includes('写しました(テスト)'));
        const orig = navigator.clipboard.writeText, ex = document.execCommand;
        navigator.clipboard.writeText = () => Promise.reject(new Error('denied')); document.execCommand = () => false;
        const ng = await UIKit.copy('x', { fail: '写せませんでした(テスト)' });
        navigator.clipboard.writeText = orig; document.execCommand = ex;
        const toastNg = [...document.querySelectorAll('.ui-toast.err')].some(t => t.textContent.includes('写せませんでした(テスト)'));
        const bare = await UIKit.copy('知らせなし');
        return { ok, back, toast, ng, toastNg, bare, left: !!document.querySelector('body > textarea') };
    }""")
    check(res["ok"] is True and res["toast"] and (res["back"] is None or res["back"] == "コピーのテスト 1"),
          "v24: UIKit.copy は写せたら true と ok の知らせ(読み戻せれば同じ文字): %s" % res)
    check(res["ng"] is False and res["toastNg"], "v24: UIKit.copy は写せなければ false(reject しない)と fail の知らせ: %s" % res)
    check(isinstance(res["bare"], bool) and not res["left"], "v24: 知らせの文が無ければ真偽値だけ・予備の textarea を残さない")
    pg.evaluate("document.querySelectorAll('.ui-toast').forEach(t => t.remove())")


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
  out.conflict = await run(() => UIKit.http('fake-api/conflict', { body: {} }));
  out.broken = await run(() => UIKit.http('fake-api/broken'));
  out.brokenStr = await run(() => UIKit.http('fake-api/broken', { fail: '壊れています(テスト)' }));
  out.brokenFn = await run(() => UIKit.http('fake-api/missing', { fail: st => 'HTTP ' + st }));
  out.empty = await run(() => UIKit.http('fake-api/empty'));
  out.down = await run(() => UIKit.http('fake-api/down', { offline: 'つながりません(テスト)' }));
  out.downDefault = await run(() => UIKit.http('fake-api/down'));
  out.slow = await run(() => UIKit.http('fake-api/slow', { timeout: 300, slow: '遅れています(テスト)' }));
  const c1 = new AbortController(); setTimeout(() => c1.abort(), 100);
  out.abort = await run(() => UIKit.http('fake-api/slow', { signal: c1.signal }));
  const c2 = new AbortController(); setTimeout(() => c2.abort(), 100);
  out.abortT = await run(() => UIKit.http('fake-api/slow', { signal: c2.signal, timeout: 5000 }));
  out.raw = await run(() => UIKit.http('fake-api/file', { body: {}, raw: true }));
  out.rawErr = await run(() => UIKit.http('fake-api/conflict', { body: {}, raw: true }));
  out.cross = await run(() => UIKit.http('http://other.invalid/x', { method: 'POST' }));
  out.home = await run(() => UIKit.homeApi('fake-api/ok', { body: { e: 5 } }));
  out.homeUrl = [UIKit.homeUrl('api/ytt/prefs'), UIKit.homeUrl('/api/ytt/prefs'), UIKit.homeUrl('live/api/info')];
  return out;
}"""


def check_http(browser, base, check):
    """v24: UIKit.http / homeApi(偽の API = page.route)。合言葉・失敗の形(e.status / e.body)・時間切れ・取り消し・raw・ほかのオリジン。
    409 などはコンソールに出るので、別の窓(context)で確かめる"""
    seen, held = [], []

    def on_api(route):
        req = route.request
        name = req.url.split("/")[-1]
        seen.append({"name": name, "url": req.url, "method": req.method, "token": req.headers.get("x-ytt-token"),
                     "ctype": req.headers.get("content-type"), "body": req.post_data})
        if name == "ok":
            route.fulfill(status=200, content_type="application/json", body='{"a": 1}')
        elif name == "conflict":
            route.fulfill(status=409, content_type="application/json",
                          body=json.dumps({"error": "conflict", "message": "先に保存されています(テスト)", "rev": 3}, ensure_ascii=False))
        elif name == "broken":
            route.fulfill(status=500, content_type="text/plain", body="oops")
        elif name == "missing":
            route.fulfill(status=404, content_type="application/json", body="{}")
        elif name == "empty":
            route.fulfill(status=200, content_type="text/plain", body="")
        elif name == "down":
            route.abort()
        elif name == "slow":
            held.append(route)   # 答えない(時間切れ・取り消しを確かめる)
        elif name == "file":
            route.fulfill(status=200, content_type="application/zip", body="PK-zip")
        else:
            route.fulfill(status=404, body="")

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
        for h in held:
            try:
                h.abort()
            except Exception:
                pass
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
        check(oks[2]["method"] == "PUT" and oks[2]["token"] == "tok-h", "method は大文字にそろえ、PUT にも合言葉")
        check(oks[3]["token"] is None and oks[4]["token"] == "tok-own", "token: false なら付けない・文字列ならその値")
        e = r["conflict"].get("err") or {}
        check(e.get("isErr") and e.get("status") == 409 and e.get("code") == "conflict" and e.get("message") == "先に保存されています(テスト)"
              and (e.get("body") or {}).get("rev") == 3 and e.get("same") and e.get("reason") == "先に保存されています(テスト)" and e.get("detail") == "HTTP 409",
              "失敗の形: message・code(サーバーの error)・status・body(= data)・reason・detail: %s" % e)
        e = r["broken"].get("err") or {}
        check(e.get("status") == 500 and e.get("code") == "http" and e.get("body") == {} and e.get("reason") == ""
              and "サーバーで問題が起きました" in (e.get("message") or "") and "500" not in (e.get("message") or ""),
              "JSON でない 500: code 'http'・body {}・本文に HTTP の番号を出さない既定の文: %s" % e)
        check((r["brokenStr"].get("err") or {}).get("message") == "壊れています(テスト)"
              and (r["brokenFn"].get("err") or {}).get("message") == "HTTP 404", "fail: 文字列か function(status) で文を決められる")
        check(r["empty"].get("ok") == {}, "成功で JSON でなければ {}")
        e = r["down"].get("err") or {}
        check(e.get("code") == "network" and e.get("status") == 0 and e.get("message") == "つながりません(テスト)" and e.get("body") == {} and e.get("detail"),
              "つながらない: code 'network'・status 0・offline の文・detail に原文: %s" % e)
        check("start.bat" in ((r["downDefault"].get("err") or {}).get("message") or ""), "offline を省略すると start.bat の案内の文")
        e = r["slow"].get("err") or {}
        check(e.get("code") == "timeout" and e.get("message") == "遅れています(テスト)", "timeout: 時間切れは code 'timeout' と slow の文: %s" % e)
        check((r["abort"].get("err") or {}).get("code") == "abort" and (r["abortT"].get("err") or {}).get("code") == "abort",
              "signal: 呼ぶ側の取り消しは code 'abort'(timeout と一緒でも)")
        check(r["raw"].get("ok") == {"response": 200, "text": "PK-zip"} and by.get("file", [{}])[0].get("token") == "tok-h",
              "raw: 成功なら Response を返す(zip の受け取り)")
        check((r["rawErr"].get("err") or {}).get("status") == 409 and (r["rawErr"].get("err") or {}).get("code") == "conflict", "raw でも失敗は同じ形")
        cross = by.get("cross", [])
        check(r["cross"].get("ok") == {"cross": 1} and cross and all(c["token"] is None and c["method"] == "POST" for c in cross),
              "ほかのオリジンには合言葉を付けない(預けた合言葉を外へ出さない): %s" % cross)
        check(r["home"].get("ok") == {"a": 1} and oks[-1]["url"] == base + "fake-api/ok" and oks[-1]["token"] == "tok-h",
              "homeApi: 画面の 1 つ上(入口の直下)へ送る")
        check(r["homeUrl"] == [base + "api/ytt/prefs", base + "api/ytt/prefs", base + "live/api/info"], "homeUrl: 先頭の / は外して入口の直下: %s" % r["homeUrl"])
        check(not errs, "画面のエラーなし(http): %s" % errs[:5])
    finally:
        ctx.close()


def check_page(browser, base, check):
    """見本(styleguide.html)を開いて、時間・日付の整形と UIKit.copy を確かめる(コンソール・画面のエラーが無いことも)"""
    errors = []
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: (m.type == "error" and "favicon" not in m.text) and errors.append(m.text))
    pg.goto(base + "styleguide.html")
    pg.wait_for_selector("#iconGrid .ui-icon svg", timeout=10000)
    check_v24_fmt_copy(pg, base, check)
    check(not errors, "コンソール・画面のエラーなし: %s" % errors[:5])
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
            browser = p.chromium.launch()
            try:
                check_page(browser, base, check)

                # ---- v10: 版の帯(UIKit.restart)。入口の API は偽物(page.route)。409 などはコンソールに出るので、別の窓(context)で確かめる ----
                check_restart(browser, base, check)

                # ---- v16: ヘッダーの録画中の札(UIKit.liveBadge)。入口の API は偽物(page.route) ----
                check_live(browser, base, check)

                # ---- v24: UIKit.http / homeApi(fetch の包みを 1 本に)。API は偽物(page.route) ----
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
