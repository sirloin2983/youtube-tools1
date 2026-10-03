"""画面の通し確認(Playwright + 疑似データのサーバー)。

    python e2e_ui.py                 # 主要な操作を自動で確かめる(終了コード 0 = すべて OK)
    python e2e_ui.py --shots DIR     # あわせて各画面のスクリーンショットを DIR に保存(ダーク/ライト × 1440x900・1024x768・390幅)
    python e2e_ui.py --serve         # 疑似データのサーバーだけ立てて待つ(ブラウザで手で見る用。Ctrl+C で終了)
    python e2e_ui.py --mounted       # 入口の統合サーバーに取り込んだ形(http://localhost:<port>/studio/・CSP・合言葉あり)で同じ確認をする

STUDIO_FAKE=1(YouTube へは接続しない)で、生成した短い動画・専用の一時フォルダだけを使う。ポートは空きポート(他のテストと同時に走らせても衝突しない)。
必要: ffmpeg、playwright(chromium)。
確かめること: タブ切り替えと復元 / テーマ切り替えの保存(既定は明るい。OS がダークでも) / ダーク表示で入力欄が白くならない / マークの採用・不採用が保存される /
書き出しボタンの有効・無効 / 外から来る文字列(タイトル・ラベル)が HTML にならない / ?url= は欄に入れるだけ / ? でキー一覧(共通の再生キーが先頭) /
設定の引き出し(ui-kit) / ヘッダー左の ui-appnav(ホーム/スタジオ/編集) / 書き出し後の「編集で開く」リンク / 狭い画面で横にはみ出さない
v0.8.0(画面の全面見直し): ① 事務所を登録すると、触っていない事務所にチェックが入る・外した事務所は外れたまま / 結果の「全部まとめて」と「事務所ごと」/
② 失敗の説明(よくある原因と対処・元のメッセージ) / ③ 配信の選択(検索)・プレーヤーが使えないときに自動再生で通知を出さない・
どの表示でも「書き出し」への入口・狭い画面の移動・微調整のボタンが 28px 以上 / コラボ(設定の中): 配信の検索・絞り込み・枠の中でスクロール・メンバーの配信者名 / 入口へ戻るリンク
v0.9.0(画面の全面見直し 段階4): ③ 書き出しの引き出し(1680px 以上は docked・それ未満は overlay) / 盛り上がりの山の順位と理由・押すと5秒前へ /
書き出し後の自動で文字起こし(入口の中だけ) / 下のキーの帯(キーの帯) / ④ コラボはタブから設定(⚙)の節へ
"""
import json
import os
import re
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツールのフォルダ(studio/)
sys.path.insert(0, HERE)   # ツールのフォルダ
os.environ["STUDIO_FAKE"] = "1"

import common  # noqa: E402
import rank  # noqa: E402
import serve  # noqa: E402

XSS_TITLE = '<img src=x onerror="window.__xss=1">配信<b>太字</b>'
XSS_LABEL = '<script>window.__xss=2</script><img src=x onerror="window.__xss=3">'
YT_ID = "ytE2Etest01"


def make_media(home):
    ffmpeg = common.find_tool("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg が必要です(STUDIO_FFMPEG でも指定できます)")
    # webm(VP8/Opus): Playwright の chromium は H.264 を再生できないため(実際の Chrome / Edge は mp4 も再生できる)。書き出しは精密方式で mp4 になる
    media = os.path.join(home, "sample.webm")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=40",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-shortest",
                    "-c:v", "libvpx", "-b:v", "400k", "-deadline", "realtime", "-threads", "1", "-c:a", "libopus", media], check=True)   # 1スレッド(VP8/VP9 は複数スレッドで時々落ちる)
    return media


def fixture(home):
    """疑似データ: 動画2本(1本は自動マーク+グラフ付き、1本はタイトルとラベルに HTML を含む)、コラボのグループ、事務所の登録。"""
    media = make_media(home)
    os.environ["STUDIO_FAKE_MEDIA"] = media
    os.environ["TRANSCRIBE_DATA_DIR"] = os.path.join(home, "txdata")   # セリフの表示が読む文字起こしの置き場(本物のフォルダに書かない)
    store, _ = serve.init(home)
    a, b = "fqa00000001", "fqa00000002"
    store.ensure({"kind": "file", "videoId": a, "name": "sample.webm", "path": media}, "雑談配信 9/20(テスト動画 A)")
    store.put_video(a, "雑談配信 9/20(テスト動画 A)", [{"id": "m1", "start": 2, "end": 7, "label": "確認用", "status": "adopted"}])
    n = 40
    total = [0.2 + (2.5 if 10 <= i <= 14 else 0) + (1.6 if 24 <= i <= 27 else 0) + (i % 5) * 0.05 for i in range(n)]
    series = {"step": 1, "n": n, "total": total, "audio": [t * 0.6 for t in total], "chat": [t * 0.3 for t in total], "comments": [0.1] * n}
    cands = [{"start": 9.0, "end": 16.0, "peak": 12, "score": 6.4, "parts": {"audio": 3.1, "chat": 2.4, "comments": 0.9}, "reasons": ["音量が急上昇", "チャットが増加"]},
             {"start": 22.0, "end": 29.0, "peak": 25, "score": 4.2, "parts": {"audio": 2.2, "chat": 1.5}, "reasons": ["チャットが増加", "コメント欄の時刻"]},
             {"start": 31.0, "end": 36.0, "peak": 33, "score": 2.3, "parts": {"audio": 2.3}, "reasons": ["音量が急上昇"]}]
    analysis = {"at": int(time.time() * 1000), "signals": {}, "counts": {"chat": 120}, "warnings": [], "spec": {}, "type": None}
    store.replace_auto(a, cands, analysis, 40.0, series)
    store.ensure({"kind": "file", "videoId": b, "name": "sample.webm", "path": media}, XSS_TITLE)
    store.put_video(b, XSS_TITLE, [{"id": "x1", "start": 3, "end": 8, "label": XSS_LABEL, "status": ""}])
    store.create_group([a, b], "9/20 コラボ", a)
    # YouTube の配信(テストでは YouTube へ繋がないので、プレーヤーは使えない。自動再生で通知を出さないことの確認用)
    store.ensure({"kind": "youtube", "videoId": YT_ID}, "埋め込みできない配信", "星見ルナ")
    store.put_video(YT_ID, "埋め込みできない配信", [{"id": "y%d" % i, "start": 60 + i * 60, "end": 90 + i * 60, "label": "", "status": ""} for i in range(4)])
    for ag in ("hololive", "nijisanji"):
        rank.import_official_channels(ag)
        rank.resolve(ag)
    common.set_api_key("AIzaTESTKEY0123456789abcdefghij")   # 空欄で「保存」を押しても消えないことの確認用
    return {"media": media, "a": a, "b": b, "yt": YT_ID, "config": common.p("config.json")}


def tab_away_and_back(pg):
    """別のタブへ移って戻ってきた(document.hidden を true → false にして visibilitychange を2回)。
    画面を離れた・戻ったは ui-kit の UIKit.life が「離れた → 戻った」の組で知らせる(段階7-2)ので、戻っただけの合図では読み直さない"""
    pg.evaluate("""() => {
      const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
      set(true); document.dispatchEvent(new Event('visibilitychange'));
      set(false); document.dispatchEvent(new Event('visibilitychange'));
      delete document.hidden;
    }""")


def open_video(pg, vid):
    """③ の「配信」(選ぶ一覧)から配信を開く(v0.8.0 で <select> から、探せる一覧に変えた)"""
    if not pg.evaluate("document.querySelector('#rvPick').open"):
        pg.click("#rvPickBtn")
    row = '#rvPickList .rv-prow[data-vid="%s"]' % vid
    pg.wait_for_selector(row)
    pg.click(row)
    wait_js(pg, "() => !document.querySelector('#rvPick').open", 5000)


def wait_js(pg, js, timeout=10000):
    """pg.wait_for_function は画面の CSP(unsafe-eval なし)で動かないので、evaluate を繰り返して待つ"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(js):
            return True
        time.sleep(0.05)
    raise TimeoutError("待ちきれませんでした: " + js)


def start_server():
    serve.Handler.log_message = lambda self, fmt, *a: None   # アクセスログは出さない(結果を読みやすく)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    port = srv.server_address[1]
    serve.PORT = port
    serve.ALLOWED_HOSTS = {"localhost:%d" % port, "127.0.0.1:%d" % port}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


MOUNT = {"prefix": "", "token": ""}   # --mounted のとき: 画面の場所 /studio と書き込み系の合言葉


def start_mounted():
    """入口(home/launch.py)の統合サーバーにスタジオを取り込んで立てる。fixture で使った serve モジュールをそのまま取り込ませる
    (別に読み込むと、データの置き場所などの設定が別になるため)。"""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "home"))
    import launch
    import mount
    sys.modules[mount.MOUNTS["studio"]["alias"]] = serve
    root = os.path.dirname(HERE)
    sup = launch.Supervisor(root, only=["studio"], mounts=("studio",), log=lambda m: None)
    srv, port = launch.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sup.start("studio")
    t = sup.by_id["studio"].snapshot()
    if not t["mounted"]:
        raise SystemExit("入口に取り込めませんでした: %s" % t)
    serve.Handler.log_message = lambda self, fmt, *a: None
    MOUNT.update(prefix="/studio", token=srv.token, sup=sup)
    return srv, port


def api(port, method, path, body=None):
    headers = {"Content-Type": "application/json", "Host": "127.0.0.1:%d" % port}
    if MOUNT["token"] and method != "GET":
        headers["X-YTT-Token"] = MOUNT["token"]
    req = urllib.request.Request("http://127.0.0.1:%d%s%s" % (port, MOUNT["prefix"], path), method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


class Checker:
    def __init__(self):
        self.fails, self.n = [], 0

    def ok(self, cond, name):
        self.n += 1
        print(("  OK   " if cond else "  NG   ") + name, flush=True)
        if not cond:
            self.fails.append(name)
        return cond


def luminance(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def rgb_of(css):
    nums = css[css.index("(") + 1:css.index(")")].replace("/", ",").split(",")
    return [float(x) for x in nums[:3]]


# 見えている文字の、文字色と背景(祖先をたどって最初の不透明な背景)のコントラスト比を調べる。3.0 未満の要素を返す(大きな問題の検出用)
CONTRAST_JS = r"""
() => {
  const parse = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = el => { const stack = []; for (let e = el; e; e = e.parentElement){ const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0){ stack.push(c); if (c.a >= 0.95) break; } }
    let out = { r: 255, g: 255, b: 255 }; const root = parse(getComputedStyle(document.body).backgroundColor); if (root) out = root;
    for (let i = stack.length - 1; i >= 0; i--){ const c = stack[i]; out = { r: c.r * c.a + out.r * (1 - c.a), g: c.g * c.a + out.g * (1 - c.a), b: c.b * c.a + out.b * (1 - c.a) }; } return out; };
  const bad = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()){
    const t = walker.currentNode; if (!t.textContent.trim()) continue;
    const el = t.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    const r = el.getBoundingClientRect(); if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || Number(cs.opacity) < 0.6) continue;
    if (el.closest('[hidden],[disabled],button:disabled,.toast,.rv-player,option,[aria-hidden=true]')) continue;
    let op = 1; for (let e = el; e; e = e.parentElement){ op *= Number(getComputedStyle(e).opacity); } if (op < 0.6) continue;
    const fg = parse(cs.color); if (!fg) continue; const bg = bgOf(el);
    const L1 = lum(fg), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    if (ratio < 3.0) bad.push({ text: t.textContent.trim().slice(0, 30), ratio: Math.round(ratio * 100) / 100, cls: (el.className && el.className.baseVal === undefined ? el.className : '') + ' <' + el.tagName.toLowerCase() + '>' });
  }
  return bad.slice(0, 20);
}
"""

NO_HSCROLL_JS = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"


def run_checks(port, fx, shots=None):
    from playwright.sync_api import sync_playwright
    c = Checker()
    base = "http://localhost:%d%s/" % (port, MOUNT["prefix"])
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "ytimg" not in m.text and "Failed to load resource" not in m.text else None)
        pg.goto(base)
        pg.wait_for_selector("#rkCond")
        print("[ヘッダー・タブ]")
        c.ok(pg.get_attribute("html", "data-theme") == "light", "保存が無ければ既定は明るい(v6)")
        pg_dark = ctx.new_page(); pg_dark.emulate_media(color_scheme="dark")
        pg_dark.goto(base); pg_dark.wait_for_selector("#rkCond")
        c.ok(pg_dark.get_attribute("html", "data-theme") == "light", "OS がダークでも、保存が無ければ既定は明るい(以前は OS の設定に従っていた)")
        pg_dark.close()
        c.ok(pg.locator("#steps .ui-tab").count() == 3, "①〜③のタブがある(④ コラボはタブから設定(⚙)へ移った)")
        c.ok((pg.text_content("#ver") or "").startswith("v"), "版が表示される")
        c.ok("キー操作" in (pg.text_content("#btnKeys") or ""), "キーボードの近道のボタンは「キー操作」(用語集)")
        # ヘッダー左の ui-appnav(ホーム/スタジオ/編集。「他のツール」メニュー・「入口」リンクの代わり)
        items = pg.eval_on_selector_all("[data-ui-appnav] a[data-ui-appnav-item]", "els => els.map(a => a.getAttribute('data-ui-appnav-item'))")
        c.ok(("portal" in items) == bool(MOUNT["prefix"]), "appnav の「ホーム」は入口に取り込まれているときだけ出る: %s" % items)
        c.ok("studio" in items and "transcribe" in items, "appnav に「スタジオ」「編集」がある: %s" % items)
        c.ok(pg.get_attribute('[data-ui-appnav-item="studio"]', "aria-current") == "page", "appnav の今の場所(スタジオ)に aria-current")
        if MOUNT["prefix"]:
            c.ok(pg.get_attribute('[data-ui-appnav-item="portal"]', "href") == "/" and pg.get_attribute('[data-ui-appnav-item="portal"]', "data-ui-portal") is not None,
                 "appnav の「ホーム」は / で、入口を前に出す仕組み(data-ui-portal)がつく")
        for step, pane in (("queue", "#paneQueue"), ("rank", "#paneRank"), ("review", "#paneReview")):
            pg.click('#steps [data-step="%s"]' % step)
            c.ok(pg.is_visible(pane) and pg.get_attribute('#steps [data-step="%s"]' % step, "aria-pressed") == "true", "タブ切り替え: %s" % step)
        pg.reload(); pg.wait_for_selector("#rvPickBtn")
        c.ok(pg.is_visible("#paneReview"), "再読み込みで最後のタブ(③)に戻る")
        # 他のツールへの受け渡しリンク(実際のポートは /api/siblings。appnav 自体はポートを見ないので、リンクを作る関数 Studio.toolUrl だけ確かめる)
        pg2 = ctx.new_page()
        pg2.route("**/api/siblings", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tools": {"studio": port, "transcribe": 8779}})))
        pg2.goto(base); wait_js(pg2, "() => window.Studio && Studio.ready")
        c.ok(pg2.evaluate("Studio.toolUrl('transcribe', '/?media=x')") == "http://localhost:8779/?media=x", "受け渡しのリンクは /api/siblings で分かった実際のポートを使う")
        pg2.close()
        # 段1: Studio.toast(msg, 0, kind) の 0 は昔の「既定の秒数」。ui-kit v7 の「消えない」(ms: 0)として渡さない。消えない知らせはオブジェクトで明示する
        seen = pg.evaluate("""() => { const o = UIKit.toast, seen = []; UIKit.toast = (m, opt) => { seen.push(opt); return o(m, opt); };
            try { Studio.toast('e2e-ok', 0, 'ok'); Studio.toast('e2e-err', 0, 'err'); Studio.toast('e2e-ms', 1200); Studio.toast('e2e-keep', { ms: 0, kind: 'err' }); } finally { UIKit.toast = o; }
            return seen.map(x => [x.ms === undefined ? null : x.ms, x.kind || null]); }""")
        c.ok(seen == [[None, "ok"], [None, "err"], [1200, None], [0, "err"]], "Studio.toast: 0 は既定の秒数・数字はその秒数・オブジェクトはそのまま(ms: 0 = 消えない): %s" % seen)
        pg.evaluate("document.querySelectorAll('.ui-toast').forEach(t => t.remove()); Studio.toast('e2e-ok', 0, 'ok'); Studio.toast('e2e-keep', { ms: 0, kind: 'err' })")
        c.ok(wait_js(pg, "() => ![...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('e2e-ok') >= 0)", 6000),
             "Studio.toast(msg, 0, 'ok') の知らせは既定の秒数で消える(× を押すまで残らない)")
        c.ok(pg.evaluate("[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('e2e-keep') >= 0)"), "オブジェクトで ms: 0 を渡した知らせは残る")
        pg.evaluate("document.querySelectorAll('.ui-toast').forEach(t => t.remove())")

        print("[テーマ]")
        # ヘッダーの明るい/暗いの切り替えボタンは消した(2026-10-04。配色は ⚙ 設定の「テーマ」の4種類から選ぶ)
        c.ok(pg.locator("[data-theme-toggle]").count() == 0, "ヘッダーに明るい/暗いの切り替えボタンが無い(配色は設定の4種類から選ぶ)")
        pg.evaluate("UIKit.theme.set('dark')")
        c.ok(pg.get_attribute("html", "data-theme") == "dark", "UIKit.theme.set('dark') でダークになる")
        pg.reload(); pg.wait_for_selector("#rvPickBtn")
        c.ok(pg.get_attribute("html", "data-theme") == "dark" and pg.evaluate("localStorage.getItem('ytt:theme')") == "dark", "テーマの選択が保存され、再読み込み後もダーク")

        print("[③ 確認・書き出し]")
        pg.click('#steps [data-step="review"]')
        pg.click("#rvPickBtn")
        c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 3"), "③ 配信の選択: 一覧に全部の配信が出る")
        pg.fill("#rvPickQ", "テスト動画 A")
        wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 1")
        c.ok("1 / 3" in (pg.text_content("#rvPickN") or ""), "③ 配信の選択: 題名で探せる(件数も出る)")
        pg.fill("#rvPickQ", "")
        # 配信の非表示(UIKit.hide。入口から開いたときだけ。覚える場所はホームの設定): 隠す → 消える → 「非表示 n件を表示」で出る(札つき) → 戻す
        HAD_PREFS = os.path.isfile(os.path.join(os.path.dirname(HERE), "home", "prefs.json"))
        if MOUNT["token"]:
            c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow-hide').length === 3"), "③ 配信の非表示: 入口から開いたときは各行に「隠す」が出る")
            c.ok(pg.evaluate("document.getElementById('rvPickHidden').hidden"), "③ 配信の非表示: 隠したものが無いうちは切り替えボタンを出さない")
            pg.click('#rvPickList [data-hide-vid="%s"]' % fx["a"])
            c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 2"), "③ 配信の非表示: 隠した配信は一覧から消える")
            c.ok(wait_js(pg, "() => { const b = document.getElementById('rvPickHidden'); return !b.hidden && b.textContent.indexOf('非表示 1件') >= 0; }"), "③ 配信の非表示: 「非表示 1件を表示」が出る")
            c.ok(pg.evaluate("document.querySelectorAll('#rvPickList .rv-prow[data-vid=\"%s\"]').length" % fx["a"]) == 0, "③ 配信の非表示: 隠したのは選んだ配信")
            pg.click("#rvPickHidden")
            c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 3 && document.querySelectorAll('#rvPickList .ui-hidden-tag').length === 1"), "③ 配信の非表示: 切り替えで出る(「非表示」の札つき)")
            c.ok(pg.evaluate("document.querySelector('#rvPickList .ui-hidden-item .rv-prow-hide').textContent") == "戻す", "③ 配信の非表示: 隠した行の操作は「戻す」")
            pg.click('#rvPickList [data-hide-vid="%s"]' % fx["a"])
            c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .ui-hidden-tag').length === 0"), "③ 配信の非表示: 戻すと札が消える")
            pg.click("#rvPickHidden")   # 表示中の切り替えは「非表示のものを隠す」。押すと元の(隠す側の)状態に戻り、隠したものが無いのでボタンも消える
            c.ok(wait_js(pg, "() => document.getElementById('rvPickHidden').hidden"), "③ 配信の非表示: 切り替えを戻すと、隠したものが無いのでボタンも消える")
            c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 3"), "③ 配信の非表示: 戻した配信が一覧にある")
            hp = os.path.join(os.path.dirname(HERE), "home", "prefs.json")   # 取り込みの試験は inplace なので、入口の設定の置き場所はリポジトリの home/。最初から無かったファイルだけ後片付けで消す
            if not HAD_PREFS and os.path.isfile(hp): os.remove(hp)
        else:
            c.ok(pg.evaluate("document.querySelectorAll('#rvPickList .rv-prow-hide').length === 0 && document.getElementById('rvPickHidden').hidden"), "③ 配信の非表示: 入口から開かないときは操作も切り替えも出ない")
        open_video(pg, fx["a"])
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="m1"]')
        c.ok("動画ファイル" in (pg.text_content("#rvChips") or ""), "③ 開いている配信の「だれの」(動画ファイル・配信者)を出す")
        # B-11: 微調整のボタンは選んだマークにだけ(一覧では時刻・長さ・ラベル・判定を比べやすく)
        rows = pg.evaluate("""[...document.querySelectorAll('#rvList .rv-mark-row:not(.folded)')].map(r => [r.classList.contains('sel'), r.querySelector('.rv-nudges') ? getComputedStyle(r.querySelector('.rv-nudges')).display : 'x'])""")
        c.ok(all((d != "none") == sel for sel, d in rows if d != "x") and any(not sel for sel, _ in rows), "微調整のボタンは選んだマークにだけ出る: %s" % rows[:4])
        other = pg.locator("#rvList .rv-mark-row:not(.sel):not(.folded)").first
        if other.count():
            other.locator('[data-f="label"]').focus()
            c.ok(wait_js(pg, "() => { const r = document.activeElement.closest('.rv-mark-row'); return r && r.classList.contains('sel') && getComputedStyle(r.querySelector('.rv-nudges')).display !== 'none'; }", 3000),
                 "別のマークの欄に入ると、そのマークが選ばれて微調整のボタンが出る")
            pg.evaluate("document.activeElement.blur()")
        # 開始・終了は時刻の欄(UIKit.timebox。時:分:秒.0.1秒): 「:」を打たずに数字だけ・Enter で確定・開始 → Tab で次へ進める・おかしな時刻は元に戻す
        M1 = "document.querySelector('#rvList .rv-mark-row[data-id=\\\"m1\\\"]')"

        def soon(js, ms=3000):
            try:
                return wait_js(pg, js, ms)
            except TimeoutError:
                return False

        def tb(f):
            return pg.evaluate("(() => { const el = %s.querySelector('[data-f=\\\"%s\\\"]'); return [el.classList.contains('ui-time'), el.textContent, UIKit.timebox.get(el)]; })()" % (M1, f))

        s0, e0 = tb("start"), tb("end")
        c.ok(s0[0] and e0[0] and s0[1].count(":") == 2 and "." in s0[1], "マークの開始・終了は時刻の欄(0:00:00.0 の形): %s %s" % (s0, e0))
        pg.locator('#rvList .rv-mark-row[data-id="m1"] [data-f="end"]').focus()
        new_end = round(s0[2] + 3.5, 1)
        digits = "%d%02d%02d%d" % (int(new_end // 3600), int(new_end % 3600 // 60), int(new_end % 60), int(round(new_end * 10)) % 10)
        pg.keyboard.type(digits)
        pg.keyboard.press("Enter")
        c.ok(soon("(() => { const el = %s.querySelector('[data-f=\\\"end\\\"]'); return el && UIKit.timebox.get(el) === %s && document.activeElement === el; })()" % (M1, new_end)),
             "終了の欄に数字だけ(%s)→ Enter で確定し、フォーカスはその欄のまま: %s" % (digits, tb("end")))
        pg.locator('#rvList .rv-mark-row[data-id="m1"] [data-f="start"]').focus()
        for _ in range(3):
            pg.keyboard.press("ArrowRight")
        pg.keyboard.press("ArrowUp")
        pg.keyboard.press("Tab")
        c.ok(soon("(() => { const r = %s, el = r.querySelector('[data-f=\\\"start\\\"]'); return Math.abs(UIKit.timebox.get(el) - %s) < 0.01 && document.activeElement !== el && r.contains(document.activeElement); })()" % (M1, round(s0[2] + 0.1, 1))),
             "開始を ↑ で 0.1 秒動かして Tab → 確定し、フォーカスは次の部品へ進む(開始の欄に奪い返さない): %s" % tb("start"))
        pg.locator('#rvList .rv-mark-row[data-id="m1"] [data-f="end"]').focus()
        pg.keyboard.press("Delete")
        pg.keyboard.press("Enter")
        c.ok(soon("UIKit.timebox.get(%s.querySelector('[data-f=\\\"end\\\"]')) === %s" % (M1, new_end)), "空にして確定しても、元の時刻に戻る: %s" % tb("end"))
        now_before = pg.input_value("#rvNow")
        pg.locator('#rvList .rv-mark-row[data-id="m1"] [data-f="start"]').focus()
        pg.keyboard.press("ArrowRight")
        c.ok(pg.input_value("#rvNow") == now_before, "時刻の欄の中の ← → は、配信の再生位置を動かさない")
        pg.evaluate("document.activeElement.blur()")
        # 書き出しの引き出し: 1680px 以上は docked(主画面(映像・マーク)が右を空け、重ならない)。1440px は既定で閉じて、押すと重ねる(2026-09-27。並べるとマークの一覧が細くなりすぎたため)
        c.ok(pg.evaluate("() => document.querySelector('#rvExport').hidden"), "1440px: 書き出しの引き出しは既定で閉じている(マークの一覧を広く)")
        pg.set_viewport_size({"width": 1720, "height": 900})
        wait_js(pg, "() => !document.querySelector('#rvExport').hidden", 3000)
        c.ok(pg.evaluate("() => !document.querySelector('#rvExport').hidden"), "1720px: 書き出しの引き出しはいつも開いている(docked)")
        player_right = pg.eval_on_selector("#rvPlayerBox", "e => e.getBoundingClientRect().right")
        clips_right = pg.eval_on_selector("#rvClipbox", "e => e.getBoundingClientRect().right")
        drawer_left = pg.eval_on_selector("#rvExport", "e => e.getBoundingClientRect().left")
        c.ok(player_right <= drawer_left and clips_right <= drawer_left, "1720px: 書き出しの引き出しは映像・マークに重ならない(主画面が右を空けている): player=%s clips=%s drawer=%s" % (player_right, clips_right, drawer_left))
        pg.set_viewport_size({"width": 1440, "height": 900})
        wait_js(pg, "() => document.querySelector('#rvExport').hidden", 3000)
        c.ok(pg.evaluate("() => document.querySelector('#rvExport').hidden"), "1440px に戻すと、並べていた引き出しは閉じる")
        pg.set_viewport_size({"width": 1720, "height": 900})   # 以下の書き出しの欄の確かめは、並べて開いている幅で行う
        wait_js(pg, "() => !document.querySelector('#rvExport').hidden", 3000)
        # 下のキーの帯(共通の再生キー。UIKit.keybar。IMPLEMENTATION.md 4)
        c.ok(pg.evaluate("document.documentElement.hasAttribute('data-keybar')") and pg.locator(".ui-keybar .ui-keybar-item").count() > 0,
             "③ で配信を開くと、下のキーの帯にいま使えるキーが並ぶ")
        c.ok("Space" in (pg.text_content(".ui-keybar") or ""), "キーの帯に共通の再生キー(Space)がある")
        pg.click('#steps [data-step="rank"]')
        c.ok(not pg.evaluate("document.documentElement.hasAttribute('data-keybar')"), "① へ移るとキーの帯は消える(場面が変わったので)")
        pg.click('#steps [data-step="review"]')
        pg.wait_for_timeout(150)
        if MOUNT["token"]:   # まとめて実行(docs/design/edit-tool-design.md の 12 ⑦(a)): 入口の中だけ。案件の画面と同じ API(入口の /api/autorun)
            c.ok(pg.is_visible("#rvAuto"), "③ 入口の中では「まとめて実行」が出る")
            pg.click("#rvAuto > summary")
            pg.click('#rvAuto [data-auto="transcribe"]')
            ok = wait_js(pg, "() => !document.querySelector('#rvAutoBar').hidden && /文字起こしまで/.test(document.querySelector('#rvAutoBar').textContent)", 10000)
            c.ok(ok, "③ 「まとめて実行」を始めると、同じ画面に進み具合の帯が出る: " + (pg.text_content("#rvAutoBar") or "")[:80])
            req = urllib.request.Request("http://127.0.0.1:%d/api/autorun" % port, headers={"Host": "127.0.0.1:%d" % port})
            with urllib.request.urlopen(req, timeout=10) as r:
                runs = json.loads(r.read())["runs"]
            c.ok(runs and runs[0]["videoId"] == fx["a"] and runs[0]["mode"] == "transcribe", "③ 入口のまとめて実行に、この配信が入る(案件の画面と同じ)")
            if pg.is_visible("#rvAutoBar [data-act=autocancel]"):
                pg.click("#rvAutoBar [data-act=autocancel]")
            ok = wait_js(pg, "() => /中止|失敗|済み|やることがありませんでした/.test(document.querySelector('#rvAutoBar .pill').textContent)", 20000)
            c.ok(ok, "③ 帯の「中止」で止められる(または終わっている): " + (pg.text_content("#rvAutoBar .pill") or ""))
            # 1つのマークだけ(マークの行の「…」の中の「この後を ▸」。docs/archive/followup-2026-09-27.md の 3・段階4の決定0)
            row_pop = '#rvList .rv-mark-row[data-id="m1"] .rv-rowmore'
            c.ok(pg.locator(row_pop).count() == 1, "③ 採用したマークの行に「…」(その他の操作)が出る")
            pg.click(row_pop + " > summary")
            btn = row_pop + " [data-act=auto1]"
            c.ok(pg.is_visible(btn), "③ 「…」の中に「この後を ▸」がある")
            pg.click(btn)
            ok = wait_js(pg, "() => !document.querySelector('#rvAutoBar').hidden && /1本/.test(document.querySelector('#rvAutoBar').textContent)", 10000)
            c.ok(ok, "③ 「この後を ▸」で、このマークだけのまとめて実行が始まる: " + (pg.text_content("#rvAutoBar") or "")[:80])
            with urllib.request.urlopen(req, timeout=10) as r:
                runs = json.loads(r.read())["runs"]
            c.ok(runs and runs[0]["marks"] == ["m1"] and runs[0]["mode"] == "adopted", "③ 入口のまとめて実行に、このマークだけが入る: %s" % (runs[0].get("marks") if runs else None))
            if pg.is_visible("#rvAutoBar [data-act=autocancel]"):
                pg.click("#rvAutoBar [data-act=autocancel]")
            wait_js(pg, "() => /中止|失敗|済み|やることがありませんでした/.test(document.querySelector('#rvAutoBar .pill').textContent)", 20000)
        else:
            c.ok(pg.is_hidden("#rvAuto"), "③ 単体で開いたときは「まとめて実行」を出さない(入口の中だけ)")
            c.ok(pg.locator("#rvList [data-act=auto1]").count() == 0, "③ 単体で開いたときは「この後を ▸」も出さない")
        wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length >= 4")
        bg = pg.eval_on_selector(".rv-trow .ui-time", "el => getComputedStyle(el).backgroundColor")   # 時刻の欄(UIKit.timebox)
        c.ok(luminance(rgb_of(bg)) < 0.2, "ダーク表示でマークの時刻の入力欄が暗い背景(以前は白): %s" % bg)
        bg2 = pg.eval_on_selector(".rv-labelrow input", "el => getComputedStyle(el).backgroundColor")
        c.ok(luminance(rgb_of(bg2)) < 0.2, "ダーク表示でラベルの入力欄が暗い背景: %s" % bg2)
        c.ok(pg.is_visible("#rvGraph") and pg.locator("#rvGSvg .rv-g-area").count() == 1, "盛り上がりグラフが出る")
        pg.check("#rvGLines")
        c.ok(pg.locator("#rvGSvg .rv-g-line").count() == 3, "材料ごとの線(音量・チャット・コメント)")
        line_colors = pg.eval_on_selector_all("#rvGSvg .rv-g-line", "els => els.map(e => getComputedStyle(e).stroke)")
        kit = pg.evaluate("['--c-audio','--c-chat','--c-com'].map(v => { const d = document.createElement('i'); d.style.color = 'var(' + v + ')'; document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove(); return c; })")
        c.ok(line_colors == kit, "グラフの線の色は ui-kit の --c-audio / --c-chat / --c-com")
        # 山の順位と理由(画面の側で S.series から計算。IMPLEMENTATION.md 4)
        n_peaks = pg.locator("#rvGPeaks .rv-gpeak").count()
        c.ok(1 <= n_peaks <= 5, "盛り上がりの山に順位の札が出る(最大5件): %d件" % n_peaks)
        first_label = (pg.text_content("#rvGPeaks .rv-gpeak >> nth=0") or "").strip()
        c.ok(first_label.startswith("1"), "いちばん高い山の札は「1」から始まる: %s" % first_label)
        c.ok("声" in first_label or "笑い" in first_label, "理由が付く(この見本データは音量の山なので「声・笑い」): %s" % first_label)
        # グラフを見やすく(2026-10-04): 時間の目盛り・状態の色の帯・山の点と線・札が重ならない・マウスの位置の時刻
        g = pg.evaluate("""() => {
          const r = el => el.getBoundingClientRect(), pk = [...document.querySelectorAll('#rvGPeaks .rv-gpeak')].map(r);
          let overlap = 0;
          for (let i = 0; i < pk.length; i++) for (let j = i + 1; j < pk.length; j++){ const a = pk[i], b = pk[j];
            if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) overlap++; }
          const box = r(document.querySelector('#rvGraph')), out = pk.filter(a => a.left < box.left - 1 || a.right > box.right + 1).length;
          return { ticks: [...document.querySelectorAll('#rvGTicks .rv-gtick')].map(e => e.textContent), grid: document.querySelectorAll('#rvGSvg .rv-g-grid').length,
            bands: [...document.querySelectorAll('#rvGSvg .rv-g-band')].map(e => e.getAttribute('class')),
            dots: document.querySelectorAll('#rvGPeaks .rv-gpk-dot').length, stems: document.querySelectorAll('#rvGPeaks .rv-gpk-stem').length,
            peaks: pk.length, overlap, out, h: box.height }; }""")
        c.ok(len(g["ticks"]) >= 2 and g["grid"] == len(g["ticks"]) and all(":" in t for t in g["ticks"]), "グラフに時間の目盛り(文字と縦の補助線): %s" % g["ticks"])
        c.ok(g["bands"] and all("st-" in b for b in g["bands"]) and any("st-cand" in b for b in g["bands"]), "マークの帯に状態の印(候補 = st-cand など): %s" % g["bands"])
        c.ok(g["dots"] == g["peaks"] and g["stems"] == g["peaks"], "山ごとに点と縦の線: %s" % g)
        c.ok(g["overlap"] == 0 and g["out"] == 0, "山の札どうしが重ならず、グラフの外にはみ出さない: %s" % g)
        c.ok(g["h"] >= 140, "グラフの高さ(以前の 104px より高く): %.0f" % g["h"])
        gb = pg.locator("#rvGraph").bounding_box()
        pg.mouse.move(gb["x"] + gb["width"] * 0.5, gb["y"] + gb["height"] - 30)
        c.ok(pg.is_visible("#rvGHover") and ":" in (pg.text_content("#rvGHover") or ""), "グラフの上ではマウスの位置の時刻が出る: %s" % pg.text_content("#rvGHover"))
        pg.mouse.move(gb["x"] + gb["width"] * 0.5, gb["y"] + gb["height"] + 200)
        c.ok(pg.is_hidden("#rvGHover"), "グラフから出ると時刻は消える")
        before = pg.evaluate("() => document.querySelector('#rvHost video').currentTime")
        peak_t = float(pg.get_attribute("#rvGPeaks .rv-gpeak >> nth=0", "data-t"))
        pg.click("#rvGPeaks .rv-gpeak >> nth=0")
        pg.wait_for_timeout(300)
        after = pg.evaluate("() => document.querySelector('#rvHost video').currentTime")
        c.ok(abs(after - max(0, peak_t - 5)) < 1.5 and after != before, "山の札を押すと、その5秒前へ移る(押す前 %.1f → %.1f。山 %.1f秒)" % (before, after, peak_t))
        if shots:
            pg.wait_for_timeout(300)
        # 採用 / 不採用
        row = '#rvList .rv-mark-row.auto'
        first = pg.get_attribute(row, "data-id")
        pg.click('#rvList .rv-mark-row[data-id="%s"] [data-act="st"][data-st="adopted"]' % first)
        sel = '#rvList .rv-mark-row[data-id="%s"]' % first
        c.ok("st-adopted" in (pg.get_attribute(sel, "class") or "") and pg.get_attribute(sel + ' [data-st="adopted"]', "aria-pressed") == "true", "採用ボタンで行が採用になる")
        wait_js(pg, "() => document.querySelector('#rvSave').dataset.k === 'saved'", 5000)
        v = api(port, "GET", "/api/video?id=" + fx["a"])["video"]
        c.ok(next(m for m in v["marks"] if m["id"] == first)["status"] == "adopted", "採用がサーバーに保存される")
        c.ok(pg.locator('#rvGSvg .rv-g-band.st-adopted[data-id="%s"]' % first).count() == 1, "採用すると、グラフの帯も採用の色になる")
        pg.click(sel + ' [data-act="st"][data-st="rejected"]')
        wait_js(pg, "() => document.querySelector('#rvSave').dataset.k === 'saved'", 5000)
        pg.wait_for_timeout(200)
        v = api(port, "GET", "/api/video?id=" + fx["a"])["video"]
        c.ok(next(m for m in v["marks"] if m["id"] == first)["status"] == "rejected", "不採用がサーバーに保存される")
        # キー操作(y / u)
        pg.click('#rvFilters [data-filter=""]')
        pg.click('#rvList .rv-mark-row.st-cand .rv-tc')
        selid = pg.evaluate("document.querySelector('#rvList .rv-mark-row.sel') && document.querySelector('#rvList .rv-mark-row.sel').dataset.id")
        pg.keyboard.press("y")
        pg.wait_for_timeout(100)
        c.ok(selid and pg.evaluate("id => !document.querySelector('#rvList .rv-mark-row[data-id=\"' + id + '\"]')", selid), "y キーで採用(候補の絞り込みから消える)")
        pg.click('#rvFilters [data-filter="all"]')
        # 書き出しボタン
        c.ok(pg.is_enabled("#rvExpRun"), "採用があるとき「書き出す」は押せる")
        for m in pg.eval_on_selector_all("#rvList .rv-mark-row.st-adopted", "els => els.map(e => e.dataset.id)"):
            pg.click('#rvList .rv-mark-row[data-id="%s"] [data-act="st"][data-st=""]' % m)
        c.ok(not pg.is_enabled("#rvExpRun"), "採用が無い(対象0件)とき「書き出す」は押せない")
        c.ok("候補を「採用」にすると" in (pg.text_content("#rvExpCount") or ""), "書き出せないときは、どうすれば書き出せるかを出す")
        pg.click("#rvExpSet summary")   # 書き出しの設定は閉じてある(見出しの横に今の設定が出る)
        c.ok("採用のみ" in (pg.text_content("#rvExpSetSum") or ""), "閉じた「書き出しの設定」の横に今の設定を出す")
        pg.select_option("#rvExpTarget", "pending")
        c.ok(pg.is_enabled("#rvExpRun"), "対象を「採用 + 候補」にすると押せる")
        pg.select_option("#rvExpTarget", "adopted")
        pg.click('#rvList .rv-mark-row[data-id="m1"] [data-act="st"][data-st="adopted"]')
        c.ok(pg.is_enabled("#rvExpRun"), "1件採用すると再び押せる")
        # キー一覧・設定の引き出し
        pg.click("#rvList .rv-mark-row[data-id='m1'] .rv-tc")
        pg.keyboard.press("?")
        c.ok(pg.is_visible("#keyHelp") and "今をマーク①" in (pg.text_content("#keyHelpBody") or ""), "? キーでキー操作の一覧が開く(③のキーも載る)")
        kh = pg.text_content("#keyHelpBody") or ""
        c.ok("Space" in kh and "共通の再生キー" in kh and kh.index("共通の再生キー") < kh.index("マーク追加"), "共通の再生キー(Space など)が一覧の先頭に出る: %s" % kh[:40])
        if shots:
            for sc in ("dark",):
                pg.screenshot(path=os.path.join(shots, "cs_keyhelp_%s.png" % sc))
        c.ok(pg.is_visible("#keyPresetRow #rvKeyPreset") and pg.evaluate("document.querySelector('#rvKeyPreset').value") == "standard",
             "? の一覧の上に、キー配置の組み合わせ(標準・左手だけ)の選択がある")
        pg.keyboard.press("Escape")
        c.ok(not pg.is_visible("#keyHelp"), "Esc で閉じる")
        # キー配置を変える場所は ? の一覧の1か所(2026-10-04): ③ の「操作の設定」には一覧を置かず、同じ一覧を開くボタンだけ
        c.ok(pg.locator("#rvRoot .ui-km").count() == 0 and pg.locator("#rvKeysOpen").count() == 1, "③ の操作の設定にはキー配置の一覧が無く、「キー配置を変える(?)」のボタンだけ")
        pg.evaluate("document.querySelector('#rvKeysOpen').click()")
        c.ok(pg.is_visible("#keyHelp") and pg.locator("#keyHelpBody .ui-km-key").count() > 5, "「キー配置を変える(?)」で ? の一覧が開く")
        pg.select_option("#rvKeyPreset", "left")
        c.ok(wait_js(pg, "() => document.querySelector('#rvKeyPreset').value === 'left'"), "一覧の上で「左手だけ」を選べる")
        pg.select_option("#rvKeyPreset", "standard")
        c.ok(wait_js(pg, "() => document.querySelector('#rvKeyPreset').value === 'standard'"), "「標準」に戻せる")
        pg.click("#keyHelpClose")
        pg.click("#btnSettings")
        c.ok(pg.is_visible("#uiSettingsDrawer") and pg.is_visible("#setKey"), "設定の引き出しが開く")
        if MOUNT["token"]:
            c.ok(pg.is_checked("#setAutoTx"), "設定の「書き出し」節: 「書き出しのあと自動で文字起こし」は既定オン")
        else:
            c.ok(pg.locator("#setAutoTx").count() == 0, "単体で開いたときは、自動で文字起こしの設定を出さない(入口の仕組みが無いため)")
        pg.evaluate("() => { const v = document.querySelector('#rvHost video'); if (v) v.pause(); }")   # y キーの「次の候補へ」で再生中のことがある
        pg.wait_for_timeout(300)
        now0 = pg.input_value("#rvNow")
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(200)
        now1 = pg.input_value("#rvNow")
        # → は 1 秒進める。止めた直後の表示の更新(0.1 秒ほど)で文字がずれることがあるので、1 秒の移動が無いことを見る(段1: 表示の一致だけだと不定に落ちた)
        sec = lambda t: sum(float(x) * 60 ** i for i, x in enumerate(reversed(t.split(":"))))
        c.ok(abs(sec(now1) - sec(now0)) < 0.5, "設定を開いている間は ③ のショートカットが効かない: %s → %s" % (now0, now1))
        pg.click("#keySave")
        c.ok("入力してください" in (pg.text_content("#keyMsg") or "") and os.path.isfile(fx["config"]), "API キーの欄が空のまま「保存」を押しても、保存済みのキーは消えない")
        pg.click("#setReg summary")
        pg.click('#setReg .ag[data-key="hololive"] > summary')
        pg.fill('#setReg .ag[data-key="hololive"] .paste', "@kakikake")
        pg.click('#setReg .ag[data-key="hololive"] .off')
        pg.keyboard.press("End")
        pg.keyboard.type(" @abc")
        pg.wait_for_timeout(1300)   # 0.5 秒後の自動保存 → 作り直し を待つ
        c.ok(pg.input_value('#setReg .ag[data-key="hololive"] .paste') == "@kakikake", "事務所の登録: 自動保存のあとも「チャンネルを追加」欄の書きかけが残る")
        c.ok(pg.evaluate("() => document.activeElement && document.activeElement.classList.contains('off')") and pg.input_value('#setReg .ag[data-key="hololive"] .off').endswith("@abc"),
             "事務所の登録: 自動保存のあとも「公式チャンネル」欄の入力中のカーソルが残る")
        c.ok(pg.evaluate("() => document.querySelector('#setReg .ag[data-key=\"hololive\"]').open"), "事務所の登録: 開いていた事務所は開いたまま")
        pg.keyboard.press("Escape")
        c.ok(not pg.is_visible("#uiSettingsDrawer"), "Esc で設定が閉じる")
        # 書き出し → 他のツールへのリンク・書き出しのあと自動で文字起こし(入口の中だけ。IMPLEMENTATION.md 4)
        sent_tx = []
        if MOUNT["token"]:
            def fake_tx_start(route):
                sent_tx.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"run": {"id": "txauto", "state": "queued"}}))
            pg.route("**/api/autorun/start", fake_tx_start)
        wait_js(pg, "() => document.querySelector('#rvSave').dataset.k !== 'pending'")
        pg.click("#rvExpRun")
        pg.wait_for_selector("#rvExpList .rv-ejob.st-ok", timeout=60000)
        wait_js(pg, "() => !document.querySelector('#rvExpCancel') || document.querySelector('#rvExpCancel').hidden", 60000)
        if MOUNT["token"]:
            end = time.time() + 8
            while not sent_tx and time.time() < end:
                pg.wait_for_timeout(200)
            c.ok(bool(sent_tx) and sent_tx[0].get("mode") == "transcribe" and sent_tx[0].get("id") == fx["a"] and sent_tx[0].get("marks") == ["m1"],
                 "書き出しのあと、入口から開いていれば自動で文字起こしを始める(api/autorun/start mode=transcribe): %s" % (sent_tx[:1],))
            pg.unroute("**/api/autorun/start")
        href = pg.get_attribute("#rvExpList .rv-ejob.st-ok a[href*='?media=']", "href") or ""
        path = urllib.parse.unquote(href.split("?media=", 1)[1]) if "?media=" in href else ""
        c.ok(":8775/?media=" in href and os.path.isfile(path), "書き出し後「編集で開く」のリンク(実在する mp4 の絶対パス): %s" % path)
        c.ok(pg.locator("#rvExpList .rv-ejob.st-ok a[href*='?video=']").count() == 0 and "編集で開く" in pg.inner_text("#rvExpList .rv-ejob.st-ok .rv-ejob-a"),
             "「文字起こしで開く」「Resolve 用に渡す」は「編集で開く」の1つにまとめた(cut2resolve へのリンクは出さない)")
        c.ok(pg.locator('#rvList .rv-mark-row[data-id="m1"].st-exported').count() == 1, "書き出し済みの印が付く")
        # 書き出した切り抜きを文字起こしツールで文字にした → ③ のマークにセリフが元の配信の時刻で出る(行を押すとその行を再生)
        txdir = os.path.join(os.environ["TRANSCRIBE_DATA_DIR"], "transcripts")
        os.makedirs(txdir, exist_ok=True)
        with open(os.path.join(txdir, "e2etx0000001.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "e2etx0000001", "title": "セリフ", "sourcePath": path, "updatedAt": 1, "speakers": [{"id": "S1", "name": "話者1"}],
                       "segments": [{"id": "s1", "start": 1.0, "end": 2.0, "text": "こんにちは", "speaker": "S1", "proofed": True},
                                    {"id": "s2", "start": 2.5, "end": 3.5, "text": XSS_LABEL, "cutState": "cut"}]}, f, ensure_ascii=False)
        tab_away_and_back(pg)   # 文字起こしのタブから戻ってきたとき
        c.ok(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row[data-id=\"m1\"] .rv-tx-line').length === 2", 10000),
             "書き出したマークにセリフ(文字起こし)が出る")
        c.ok("校正 1/2" in (pg.text_content('#rvList .rv-mark-row[data-id="m1"] .rv-tx summary') or ""), "セリフの行数と校正の進み具合")
        tcs = pg.eval_on_selector_all('#rvList .rv-mark-row[data-id="m1"] .rv-tx-line', "els => els.map(e => e.dataset.t)")
        exp_start = next(m["start"] for m in serve.STORE.internal(fx["a"])["marks"] if m["id"] == "m1")
        c.ok(len(tcs) == 2 and abs(float(tcs[0]) - float(tcs[1]) + 1.5) < 0.01 and float(tcs[0]) >= 2.0, "セリフの時刻は元の配信の時刻(切り抜きの開始 + 行の時刻): %s(マークの開始 %s)" % (tcs, exp_start))
        c.ok(pg.locator('#rvList .rv-mark-row[data-id="m1"] .rv-tx-line.cut').count() == 1, "文字起こしでカットにした行は線を引いて出す")
        # 一瞬をマーク(2026-09-28): 前・後の秒数はあらかじめ決めておき(0.1 秒単位)、C かボタン1つでマーク「一瞬」(採用)になる
        n_marks = len(serve.STORE.internal(fx["a"])["marks"])
        c.ok(pg.input_value("#rvMomBefore") == "2.0" and pg.input_value("#rvMomAfter") == "3.0", "一瞬の前・後の秒数の既定は 2.0・3.0")
        pg.fill("#rvMomBefore", "1.5"); pg.press("#rvMomBefore", "Tab")
        pg.fill("#rvMomAfter", "2.3"); pg.press("#rvMomAfter", "Tab")
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("c")
        end_t = time.time() + 10   # 画面は少し待ってから保存する(マークのラベルは入力欄の値なので、行の文字では待てない)
        while time.time() < end_t and not any(m.get("label") == "一瞬" for m in serve.STORE.internal(fx["a"])["marks"]):
            time.sleep(0.2)
        mom = [m for m in serve.STORE.internal(fx["a"])["marks"] if m.get("label") == "一瞬"]
        c.ok(len(serve.STORE.internal(fx["a"])["marks"]) == n_marks + 1 and len(mom) == 1 and abs((mom[0]["end"] - mom[0]["start"]) - 3.8) < 0.01 and mom[0]["status"] == "adopted",
             "C でマーク「一瞬」(採用)が前 1.5 秒・後 2.3 秒(計 3.8 秒)でできる: %s" % [(m["start"], m["end"], m["status"]) for m in mom])
        end_t = time.time() + 5
        while time.time() < end_t and (serve.STORE.get_ui().get("review") or {}).get("momentAfter") != 2.3:
            time.sleep(0.2)
        rv = serve.STORE.get_ui().get("review") or {}
        c.ok((rv.get("momentBefore"), rv.get("momentAfter")) == (1.5, 2.3), "前・後の秒数は設定に保存される: %s" % ((rv.get("momentBefore"), rv.get("momentAfter")),))
        # つなげて1本に(2026-09-28): 2 件チェック → 時刻の順につないだ mp4 が1本。部品は消す・マークの状態は変えない・.clip.json は書かない
        ms = sorted(serve.STORE.internal(fx["a"])["marks"], key=lambda m: m["start"])
        pick2 = [ms[0], next(m for m in ms if m.get("label") == "一瞬")]
        before_st = {m["id"]: m["status"] for m in ms}
        for m in pick2:
            pg.check('#rvList .rv-mark-row[data-id="%s"] .rv-join' % m["id"])
        c.ok(pg.is_visible("#rvJoinRun") and pg.is_enabled("#rvJoinRun") and "2 件" in pg.inner_text("#rvJoinRun"), "2 件チェックすると「つなげて1本に」が押せる: %s" % pg.inner_text("#rvJoinRun"))
        pg.click("#rvJoinRun")
        c.ok(wait_js(pg, "() => [...document.querySelectorAll('#rvExpList .rv-ejob.st-ok')].some(r => (r.textContent || '').includes('つないだ1本'))", 90000), "つないだ1本ができる")
        wait_js(pg, "() => !document.querySelector('#rvExpCancel') || document.querySelector('#rvExpCancel').hidden", 30000)
        href = pg.evaluate("() => { const r = [...document.querySelectorAll('#rvExpList .rv-ejob.st-ok')].find(r => (r.textContent || '').includes('つないだ1本')); const a = r && r.querySelector(\"a[href*='?media=']\"); return a ? a.getAttribute('href') : ''; }")
        jpath = urllib.parse.unquote(href.split("?media=", 1)[1]) if "?media=" in href else ""
        want = sum(m["end"] - m["start"] for m in pick2)
        got = common.media_info(jpath)[0] if jpath and os.path.isfile(jpath) else None
        c.ok(got is not None and abs(got - want) < 1.0 and "つなぎ_" in os.path.basename(jpath), "つないだ mp4 の長さ = 選んだマークの合計(%s 秒 / %s 秒): %s" % (got, round(want, 1), jpath))
        work = os.path.join(os.path.dirname(jpath), "作業用") if jpath else ""
        c.ok(jpath and not [n for n in (os.listdir(work) if os.path.isdir(work) else []) if n.startswith("つなぐ_")] and not os.path.exists(os.path.splitext(jpath)[0] + ".clip.json"),
             "部品は消え、つないだ動画に .clip.json は書かない")
        c.ok({m["id"]: m["status"] for m in serve.STORE.internal(fx["a"])["marks"]} == before_st, "つないでも、マークの状態(書き出し済みなど)は変えない")
        c.ok(not pg.is_checked('#rvList .rv-mark-row[data-id="%s"] .rv-join' % pick2[0]["id"]) and pg.is_hidden("#rvJoinRun"), "始めたらチェックは外れる")
        c.ok(pg.evaluate("window.__xss === undefined") and pg.locator("#rvList .rv-tx img").count() == 0, "セリフの文字は HTML として実行・表示されない")
        pg.click('#rvList .rv-mark-row[data-id="m1"] .rv-tx summary')
        c.ok(pg.evaluate("() => document.querySelector('#rvList .rv-mark-row[data-id=\"m1\"] .rv-tx').open"), "セリフを開ける")
        pg.click('#rvList .rv-mark-row[data-id="m1"] .rv-tx-line >> nth=0')
        c.ok(wait_js(pg, "() => Math.abs(parseFloat(document.querySelector('#rvHost video') ? document.querySelector('#rvHost video').currentTime : -1) - %s) < 1.2" % float(tcs[0]), 5000),
             "セリフの行を押すと、その時刻から再生する")
        pg.evaluate("() => { const v = document.querySelector('#rvHost video'); if (v) v.pause(); }")
        tab_away_and_back(pg)
        pg.wait_for_timeout(500)
        c.ok(pg.evaluate("() => document.querySelector('#rvList .rv-mark-row[data-id=\"m1\"] .rv-tx').open"), "読み込み直してもセリフは開いたまま")
        if shots:
            pg.screenshot(path=os.path.join(shots, "cs_review_exported_dark.png"))

        print("[③ プレーヤーが使えないとき(不具合2)・書き出しへの入口]")
        c.ok(pg.is_visible('#rvJump [data-jump="export"]'), "広い画面: 上の行に「書き出し」への入口がある")
        pg.click("#rvTheater"); pg.wait_for_timeout(300)
        ex, pl = pg.eval_on_selector("#rvExport", "e => e.getBoundingClientRect().left"), pg.eval_on_selector("#rvPlayerBox", "e => e.getBoundingClientRect().right")
        c.ok(ex > pl and pg.is_visible("#rvExpRun") and pg.eval_on_selector("#rvExport", "e => e.getBoundingClientRect().top") < 400,
             "シアター表示でも「書き出し」は右の列の上(見える場所)にある")
        pg.click("#rvTheater"); pg.wait_for_timeout(200)
        pg.route("https://www.youtube.com/**", lambda route: route.abort())   # YouTube に繋がらない(埋め込みできない)状態
        pg.reload(); pg.wait_for_selector("#rvList")   # インターネットに繋がる PC では、前に読み込んだ YouTube の部品が残るので読み直す
        pg.evaluate("() => { window.__toasts = []; const o = Studio.toast; Studio.toast = (m, ms, k) => { window.__toasts.push(String(m)); return o(m, ms, k); }; }")
        open_video(pg, fx["yt"])
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="y0"]')
        c.ok(wait_js(pg, "() => !document.querySelector('#rvNotice').hidden", 15000) and "再生できません" in (pg.text_content("#rvNotice") or ""),
             "プレーヤーが使えないことを、プレーヤーの下に1か所だけ出す")
        pg.click('#rvList .rv-mark-row[data-id="y0"] .rv-tc')
        for k in ("]", "]", "[", "y", "u"):
            pg.keyboard.press(k); pg.wait_for_timeout(120)
        c.ok(not any("再生" in t for t in pg.evaluate("window.__toasts")), "自動再生・採用/不採用で次へ のまま キー操作で判定しても、再生できない通知を出さない: %s" % pg.evaluate("window.__toasts"))
        v = api(port, "GET", "/api/video?id=" + fx["yt"])["video"] if wait_js(pg, "() => document.querySelector('#rvSave').dataset.k === 'saved'", 5000) else {"marks": []}
        c.ok(sorted(m["status"] for m in v["marks"]) == ["", "", "adopted", "rejected"], "プレーヤーが使えなくても判定は保存される")
        pg.keyboard.press("Space"); pg.wait_for_timeout(150)   # 共通の再生キー: Space が再生・停止(v6。以前は k)
        c.ok(any("再生できません" in t for t in pg.evaluate("window.__toasts")), "自分で再生を押したときは知らせる")
        pg.unroute("https://www.youtube.com/**")

        print("[③ YouTube のプレーヤーの準備が終わらないとき(監査20)]")
        # iframe_api は読めるが、YT.Player が onReady も onError も呼ばない(回線・埋め込みの制限で止まる)偽物
        fake_api = ("window.__ytCtor = (window.__ytCtor || 0); "
                    "window.YT = { Player: function (el, opts) { window.__ytCtor++; this.destroy = function () {}; }, "
                    "PlayerState: { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 } }; "
                    "if (window.onYouTubeIframeAPIReady) window.onYouTubeIframeAPIReady();")
        api_hits = []
        def fake_iframe_api(route):
            api_hits.append(1)
            route.fulfill(status=200, content_type="application/javascript", body=fake_api)
        pg.route("https://www.youtube.com/iframe_api", fake_iframe_api)
        pg.reload(); pg.wait_for_selector("#rvList")
        pg.evaluate("Studio.review.setYtReadyMs(500)")   # 既定は 20 秒。テストでは短くする
        open_video(pg, fx["a"])   # 読み直しで自動で開いた配信と区別するため、一度ほかの配信へ移してから開く(開くたびにプレーヤーを作り直す)
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="m1"]')
        pg.evaluate("window.__ytCtor = 0")   # 読み直しで自動で開いた配信の分を数えない
        open_video(pg, fx["yt"])
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="y0"]')
        c.ok(wait_js(pg, "() => window.__ytCtor === 1", 8000), "偽の YT.Player が作られる(準備待ちが始まる)")
        c.ok(wait_js(pg, "() => !document.querySelector('#rvNotice').hidden && document.querySelector('#rvNotice').textContent.includes('準備が終わりません')", 8000),
             "準備が終わらないと、時間切れの案内が出る")
        nt = pg.text_content("#rvNotice") or ""
        c.ok("時刻の手入力でマークは続けられます" in nt and "回線・埋め込みの制限" in nt, "案内に、原因の見当と、手入力で続けられることがある: %s" % nt)
        c.ok(pg.locator('#rvNotice [data-act="ytretry"]').count() == 1 and "もう一度試す" in (pg.text_content('#rvNotice [data-act="ytretry"]') or ""), "「もう一度試す」のボタンがある")
        c.ok(pg.locator("#rvNotice a[data-yt-now]").count() == 1, "「YouTube で開く」のリンクも残る")
        c.ok(not pg.evaluate("document.querySelector('#rvPhMsg') ? !document.querySelector('#rvPhMsg').hidden : false"), "「準備しています…」の表示は消える")
        pg.click('#rvNotice [data-act="ytretry"]')
        c.ok(wait_js(pg, "() => window.__ytCtor === 2", 5000), "「もう一度試す」で、もう一度プレーヤーを準備する(作り直しは1回だけ)")
        c.ok(wait_js(pg, "() => !document.querySelector('#rvNotice').hidden && document.querySelector('#rvNotice').textContent.includes('準備が終わりません')", 8000),
             "また終わらなければ、もう一度時間切れの案内が出る(自動の再試行はしない)")
        pg.wait_for_timeout(1200)
        c.ok(pg.evaluate("window.__ytCtor") == 2 and len(api_hits) == 1, "自動では再試行せず、iframe_api も読み直さない: 作成 %s 回・読み込み %s 回" % (pg.evaluate("window.__ytCtor"), len(api_hits)))
        pg.unroute("https://www.youtube.com/iframe_api")
        pg.reload(); pg.wait_for_selector("#rvList")

        print("[外から来る文字列]")
        open_video(pg, fx["b"])
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="x1"]')
        c.ok(pg.text_content("#rvCurLabel") == XSS_TITLE, "動画のタイトルは文字のまま表示される")
        c.ok(pg.input_value('#rvList [data-f="label"]') == XSS_LABEL, "ラベルは文字のまま")
        # v6: ④ コラボ はタブから設定(⚙)の「コラボ」節へ移った
        pg.click("#btnSettings")
        c.ok(pg.is_visible("#uiSettingsDrawer") and pg.is_visible("#setCollab"), "コラボは設定の引き出しの節になっている")
        pg.click("#setCollab summary")
        pg.wait_for_selector(".cl-group")
        c.ok(XSS_TITLE in (pg.text_content("#collabHost") or ""), "設定の「コラボ」節でもタイトルは文字のまま")
        c.ok(pg.evaluate("window.__xss === undefined") and pg.locator("main img[src='x']").count() == 0, "タイトル・ラベルの HTML が実行・表示されない")

        print("[コラボ(設定の中)]")
        badge_text = pg.text_content("#collabBadge") or ""
        c.ok(not pg.is_hidden("#collabBadge") and "1" in badge_text, "「コラボ」節の見出しにズレ未設定の件数の札: %s" % badge_text)
        c.ok(pg.locator(".cl-member").count() == 2, "グループの配信が並ぶ")
        c.ok(pg.locator(".cl-member .cl-mmeta").count() == 2 and "動画ファイル" in (pg.text_content(".cl-member .cl-mmeta") or ""),
             "グループのメンバーの行に、だれの(配信者・動画ファイル)といつの を出す")
        c.ok(pg.locator("#clVideoList .cl-video").count() == 1 and "1 / 3" in (pg.text_content("#clCount") or ""), "配信の選択: 既定はグループに入っていない配信だけ(件数つき)")
        pg.select_option("#clF", "all")
        c.ok(pg.locator("#clVideoList .cl-vg").count() == 2 and pg.locator("#clVideoList .cl-video").count() == 3, "「すべての配信」で、配信者ごとのまとまりに分けて出す")
        pg.fill("#clQ", "埋め込み"); pg.wait_for_timeout(300)
        c.ok(pg.locator("#clVideoList .cl-video").count() == 1, "配信の選択: 題名で探せる")
        pg.fill("#clQ", ""); pg.select_option("#clF", "free"); pg.wait_for_timeout(300)
        pg.click('.cl-member:not(.is-base) [data-act="removeMember"]')
        c.ok(pg.locator(".cl-member").count() == 2 and "もう一度" in (pg.text_content('.cl-member:not(.is-base) [data-act="removeMember"]') or ""), "「グループから外す」は2回押しで確認する")
        pg.click('.cl-member:not(.is-base) [data-act="anchor"]')
        c.ok(pg.is_visible("#clA1this") and pg.evaluate("document.activeElement.id") == "clA1this", "アンカーの入力欄が開き、フォーカスが移る")
        # 合わせる時刻は時刻の欄(UIKit.timebox。時:分:秒.0.1秒): 数字だけで入る・入れていなければ保存の前に知らせる
        c.ok(pg.evaluate("document.getElementById('clA1this').classList.contains('ui-time')") and (pg.text_content("#clA1this") or "") == "0:00:00.0", "合わせる時刻は時刻の欄: %s" % pg.text_content("#clA1this"))
        pg.keyboard.type("001235")
        c.ok(pg.evaluate("UIKit.timebox.get(document.getElementById('clA1this'))") == 83.5 and (pg.text_content("#clA1this") or "") == "0:01:23.5", "001235 → 0:01:23.5: %s" % pg.text_content("#clA1this"))
        if os.environ.get("SHOT_ANCHOR"):   # 見た目の確認用(合わせる時刻の欄)
            pg.screenshot(path=os.environ["SHOT_ANCHOR"])
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(300)
        c.ok("点1の時刻" in (pg.text_content("#clAnchorMsg") or "") and pg.evaluate("document.activeElement.id") == "clA1ref",
             "基準の時刻が空のまま Enter(保存)→ 理由を出して、空の欄へ移る: %s" % pg.text_content("#clAnchorMsg"))
        pg.keyboard.press("Escape")
        c.ok(not pg.is_visible("#uiSettingsDrawer"), "Esc で設定(コラボを含む)を閉じる")

        print("[① 探す: 事務所のチェック(不具合1)]")
        pg.click('#steps [data-step="rank"]')
        checks = lambda: dict(pg.eval_on_selector_all("#agChecks .agc", "els => els.map(e => [e.value, e.checked])"))
        c.ok(checks() == {"hololive": True, "nijisanji": True, "vspo": False, "neoporte": False}, "チャンネルを登録した事務所だけにチェックが入る: %s" % checks())
        pg.click("#btnSettings")
        if not pg.evaluate("document.querySelector('#setReg').open"):
            pg.click("#setReg summary")
        pg.click('#setReg .ag[data-key="vspo"] > summary')
        pg.click('#setReg .ag[data-key="vspo"] [data-act="imp"]')
        wait_js(pg, "() => document.querySelectorAll('#setReg .ag[data-key=\"vspo\"] .ch .st.ok').length > 0 && !document.querySelector('#setReg .ag[data-key=\"vspo\"] .pill.run')", 20000)
        pg.keyboard.press("Escape")
        c.ok(checks() == {"hololive": True, "nijisanji": True, "vspo": True, "neoporte": False}, "設定で事務所を登録して ① に戻ると、その事務所にもチェックが入る(以前は全部外れた): %s" % checks())
        pg.uncheck('#agChecks .agc[value="nijisanji"]')
        pg.reload(); pg.wait_for_selector("#agChecks .agc")
        wait_js(pg, "() => document.querySelectorAll('#agChecks .agc').length === 4")
        c.ok(checks() == {"hololive": True, "nijisanji": False, "vspo": True, "neoporte": False}, "自分で外した事務所は、読み込み直しても外れたまま: %s" % checks())

        print("[① 探す: 期間の早見「昨日0時〜今」と「10分以上の動画だけ」(2026-10-04)]")
        c.ok(pg.evaluate("document.querySelector('#rkCond .cs-quick .btn').hasAttribute('data-yday')"), "期間の早見の先頭は「昨日0時〜今」")
        pg.click("#rkCond [data-yday]")
        want = pg.evaluate("""() => { const f = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
            const e = new Date(), s = new Date(); s.setDate(s.getDate() - 1); return [f(s), f(e)]; }""")
        c.ok([pg.input_value("#dStart"), pg.input_value("#dEnd")] == want, "「昨日0時〜今」で 開始 = 昨日・終了 = 今日 になる: %s" % want)
        c.ok(pg.is_checked("#minDur10") and "10分以上" in (pg.text_content("#rkAdvSum") or ""), "「10分以上の動画だけ」は既定でオン(閉じた見出しの要約にも出る)")
        pg.click("#rkCond [data-days=\"30\"]")
        with pg.expect_request(lambda r: r.url.endswith("/api/rank/search") and r.method == "POST") as rq:
            pg.click("#btnGo")
        body = json.loads(rq.value.post_data or "{}")
        c.ok(body.get("minDur") == 600, "検索の条件に最低の再生時間 600 秒を送る: %s" % body.get("minDur"))
        pg.wait_for_selector("#results .rk-table", timeout=30000)
        pg.evaluate("document.querySelector('#rkAdv').open = true")
        pg.uncheck("#minDur10")
        c.ok("10分以上" not in (pg.text_content("#rkAdvSum") or ""), "オフにすると要約から消える")
        pg.reload(); pg.wait_for_selector("#minDur10", state="attached")
        c.ok(not pg.is_checked("#minDur10"), "「10分以上の動画だけ」のオフは読み込み直しても残る")
        pg.evaluate("document.querySelector('#rkAdv').open = true")
        pg.check("#minDur10")
        pg.evaluate("document.querySelector('#rkAdv').open = false")

        print("[① 探す(疑似の YouTube API)]")
        pg.click("#btnGo")
        pg.wait_for_selector("#results .rk-table", timeout=30000)
        c.ok(pg.locator("#results tr[data-vid]").count() > 5, "検索結果が並ぶ")
        views = pg.eval_on_selector_all("#results tr[data-vid] td.n.num:not(.hide-s)", "els => els.map(e => Number(e.textContent.replace(/,/g, '')))")
        c.ok(pg.locator("#results .rk-table").count() == 1 and views == sorted(views, reverse=True) and len(views) <= 30,
             "既定は「全部まとめて」: 全事務所の結果を1つの表に再生数の多い順(上位30本)")
        c.ok(pg.locator("#results tr[data-vid] .rk-ag-name").count() == len(views), "全部まとめて: 各行に事務所名")
        pg.click('#results [data-view="ag"]')
        c.ok(pg.locator("#results details.rk-ag").count() == 2, "「事務所ごと」に切り替えると、事務所ごとのまとまり(選んだ2事務所)")
        pg.click('#results [data-view="all"]')
        pg.fill("#rkQ", "zzzz-no-hit")
        c.ok(pg.locator("#results tr[data-vid]").count() == 0 and pg.locator("#rkBody .empty").count() == 1, "結果の中を絞り込める(合わないときは空の案内)")
        pg.fill("#rkQ", "")
        pg.check("#results tr[data-vid] .pk >> nth=0")
        c.ok(pg.text_content("#pickN") == "1" and pg.is_enabled("#pickGo"), "チェックすると選択数が増え、追加ボタンが押せる")
        if MOUNT["token"]:   # まとめて実行(docs/archive/followup-2026-09-27.md の 5): 入口の中だけ。入口の API は偽物に差し替えて、送る中身と行の印を確かめる
            c.ok(pg.is_visible("#rkAuto"), "① 入口の中では、選んだ配信の「まとめて実行」が出る")
            vid = pg.get_attribute("#results tr[data-vid] .pk >> nth=0", "data-id")
            sent = []
            fake_run = lambda: [{"id": "r1", "videoId": vid, "kind": "video", "state": "queued", "mode": "full"}]

            def fake_start(route):
                sent.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"runs": fake_run(), "skipped": []}))
            pg.route("**/api/autorun/start-new", fake_start)
            pg.route("**/api/autorun", lambda route: route.fulfill(status=200, content_type="application/json",
                                                                   body=json.dumps({"runs": fake_run() if sent else []})))
            pg.click("#rkAuto > summary")
            c.ok(pg.is_enabled("#rkAutoGo") and "1 本" in (pg.text_content("#rkAutoGo") or ""), "① 選んだ本数が「まとめて実行」のボタンに出る")
            pg.fill("#rkAutoTop", "2")
            pg.click("#rkAutoGo")
            ok = wait_js(pg, "() => /まとめて実行の順番待ち/.test(document.querySelector('#results tr[data-vid=\"%s\"] .chip').textContent)" % vid, 10000)
            c.ok(ok, "① 始めた配信の行に「まとめて実行の順番待ち」の印が出る")
            it = (sent[0].get("items") or [{}])[0] if sent else {}
            c.ok(it.get("id") == vid and it.get("title") and sent[0].get("top") == 2 and "streamer" not in sent[0],
                 "① 選んだ配信(題名・配信者つき)と採用する数を入口に送る(配信者の名前は入れたときだけ): %s" % (sent[:1],))
            c.ok(pg.text_content("#pickN") == "0" and pg.is_disabled('#results tr[data-vid="%s"] .pk' % vid) and pg.is_hidden("#rkAuto .rk-autopop"),
                 "① 始めた配信は選択から外れ、順番待ちの間はチェックできない・メニューは閉じる")
            pg.unroute("**/api/autorun/start-new")
            pg.unroute("**/api/autorun")
            req = urllib.request.Request("http://127.0.0.1:%d/api/autorun/start-new" % port, method="POST", data=json.dumps({"items": []}).encode(),
                                         headers={"Host": "127.0.0.1:%d" % port, "Content-Type": "application/json", "X-YTT-Token": MOUNT["token"]})
            try:
                urllib.request.urlopen(req, timeout=10)
                st, msg = 200, ""
            except urllib.error.HTTPError as e:
                st, msg = e.code, json.loads(e.read()).get("message", "")
            c.ok(st == 400 and "配信は" in msg, "入口の /api/autorun/start-new: 配信を選んでいなければ断る(%s %s)" % (st, msg))
        else:
            c.ok(pg.is_hidden("#rkAuto"), "① 単体で開いたときは「まとめて実行」を出さない(入口の中だけ)")

        print("[?video=(B-6: 「編集」から戻る)]")
        pg.goto(base + "?video=" + fx["a"] + "&url=" + urllib.parse.quote("https://youtu.be/abcdefghijk"))
        wait_js(pg, "() => !document.querySelector('#paneReview').hidden && document.querySelectorAll('#rvList .rv-mark-row').length > 0", 15000)
        want = sorted(m["id"] for m in api(port, "GET", "/api/video?id=" + fx["a"])["video"]["marks"])
        got = sorted(pg.eval_on_selector_all("#rvList .rv-mark-row", "els => els.map(e => e.dataset.id)"))
        c.ok(pg.is_visible("#paneReview") and got == want, "?video= の配信が保存済みなら、③ の確認画面でその配信を開く: %s / %s" % (got[:5], want[:5]))
        c.ok(pg.input_value("#qUrls") == "", "そのときは ?url= を解析の欄に入れない(再解析を求めているように見せない)")
        c.ok("video=" not in pg.url and "url=" not in pg.url, "受け取ったあと、アドレスから ?video= ?url= を消す")
        pg.goto(base + "?video=nosuchvideo&url=" + urllib.parse.quote("https://youtu.be/abcdefghijk"))
        pg.wait_for_selector("#qEntry")
        c.ok(pg.is_visible("#paneQueue") and pg.input_value("#qUrls") == "https://youtu.be/abcdefghijk", "保存されていない配信なら、これまでどおり ?url= を解析の欄に入れる")
        pg.fill("#qUrls", "")

        print("[② 解析 と ?url=]")
        pg.goto(base + "?url=" + urllib.parse.quote("https://youtu.be/abcdefghijk"))
        pg.wait_for_selector("#qEntry")
        c.ok(pg.is_visible("#paneQueue") and pg.input_value("#qUrls") == "https://youtu.be/abcdefghijk" and pg.is_visible("#qParam"), "?url= は ② の URL 欄に入る")
        c.ok(len(api(port, "GET", "/api/queue")["items"]) == 0, "?url= だけでは解析を始めない")
        c.ok("?url=" not in pg.url, "受け取ったあと、アドレスから ?url= を消す(再読み込みで二重に入れない)")
        pg.click("#qAdd")
        pg.wait_for_selector("#qList .q-item", timeout=10000)
        c.ok(len(api(port, "GET", "/api/queue")["items"]) == 1 and pg.input_value("#qUrls") == "", "「解析に追加」でキューに入り、欄が空になる")
        wait_js(pg, "() => { const i = document.querySelector('#qList .q-item'); return i && ['done', 'error'].includes(i.dataset.status); }", 90000)
        st = pg.get_attribute("#qList .q-item", "data-status")
        c.ok(st == "done" and pg.locator('#qList [data-act="review"]').count() == 1, "疑似の解析が終わり「確認する」が出る(状態: %s)" % st)
        c.ok(pg.is_visible("#qNext") and "確認する" in (pg.text_content("#qNext") or ""), "次にやること: 解析が終わった配信を確認する")
        raw = "音声を取得できませんでした: ERROR: [youtube] abcdefghijk: Sign in to confirm your age"
        pg.route("**/api/queue", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"items": [{"qid": "e1", "videoId": "abcdefghijk", "kind": "youtube", "title": "失敗した配信", "channel": "星見ルナ", "status": "error", "phase": "失敗",
                        "progress": 0, "error": raw, "chat": None, "marks": 0, "finishedAt": int(time.time() * 1000)}], "running": False, "max": 10})))
        pg.evaluate("Studio.queue.refresh()")
        pg.wait_for_selector('#qList .q-item[data-status="error"]')
        c.ok("年齢制限" in (pg.text_content("#qList .q-err b") or "") and pg.is_visible("#qList .q-how"),
             "② 解析の失敗は「何が起きたか」+「どうすればいいか」で出す: %s" % pg.text_content("#qList .q-err b"))
        c.ok(pg.text_content("#qList .q-raw code") == raw and not pg.is_visible("#qList .q-raw code"), "元のメッセージは閉じた欄に小さく残す")
        pg.unroute("**/api/queue")

        print("[狭い画面・コントラスト]")
        for w in (390, 1024):
            pg.set_viewport_size({"width": w, "height": 800})
            for step in ("rank", "queue", "review"):
                pg.evaluate("s => Studio.go(s)", step)
                pg.wait_for_timeout(150)
                c.ok(pg.evaluate(NO_HSCROLL_JS), "%dpx 幅の %s で横にはみ出さない" % (w, step))
        pg.set_viewport_size({"width": 390, "height": 800})
        pg.evaluate("Studio.go('review')")
        pg.evaluate("window.scrollTo(0, 0)")
        open_video(pg, fx["a"])   # 狭い画面でも配信を選べる
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="m1"]')
        c.ok(pg.evaluate("document.querySelector('#rvJump').classList.contains('is-bar')") and pg.is_visible('#rvJump [data-jump="marks"]'),
             "390px の ③: プレーヤー・マーク・書き出しへ飛ぶ案内を出す")
        c.ok(pg.evaluate("() => document.querySelector('#rvExport').hidden"), "390px(1680px 未満): 書き出しの引き出しは既定で閉じている(docked ではない)")
        pg.click('#rvJump [data-jump="export"]'); pg.wait_for_timeout(400)
        c.ok(pg.evaluate("() => !document.querySelector('#rvExport').hidden") and pg.is_visible("#rvExpRun"), "「書き出し」を押すと書き出しの引き出しが開く(重ねて)")
        pg.evaluate("() => { const v = document.querySelector('#rvHost video'); if (v) v.pause(); }")
        now0 = pg.input_value("#rvNow")
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")   # 欄の外にフォーカスがあっても(重ねている間は)効かない
        pg.keyboard.press("ArrowRight"); pg.keyboard.press("y")
        pg.wait_for_timeout(200)
        c.ok(pg.input_value("#rvNow") == now0, "書き出しの欄を重ねて開いている間は、裏の配信のキー(→・採用など)が効かない(B-2)")
        c.ok(pg.evaluate(NO_HSCROLL_JS), "390px: 書き出しの引き出しを開いても横にはみ出さない")
        pg.click("#rvExpClose"); pg.wait_for_timeout(300)
        c.ok(pg.evaluate("() => document.querySelector('#rvExport').hidden"), "閉じるボタンで書き出しの引き出しを閉じられる")
        pg.click('#rvJump [data-jump="marks"]'); pg.wait_for_timeout(900)
        c.ok(pg.evaluate("() => { const r = document.querySelector('#rvClipbox').getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight / 2; }") and pg.is_visible("#rvJump"),
             "「マーク」を押すとマークの一覧へ移る(案内は上に残る)")
        small = pg.evaluate("() => [...document.querySelectorAll('#rvList .rv-nudges .btn, #rvList .rv-stgroup .btn, #rvList .rv-fold, #rvQuickSlots .rv-step')].filter(b => b.offsetParent && b.getBoundingClientRect().height < 27.5).length")
        c.ok(small == 0, "390px の ③: 微調整・判定・長さのボタンは 28px 以上(小さいもの %s 個)" % small)
        pg.click("#btnSettings"); pg.wait_for_timeout(200)
        c.ok(pg.evaluate(NO_HSCROLL_JS), "390px: 設定の引き出しを開いても横にはみ出さない")
        pg.click("#setCollab summary"); pg.wait_for_selector(".cl-group")
        pg.select_option("#clF", "all"); pg.wait_for_timeout(200)
        c.ok(pg.evaluate("() => { const s = getComputedStyle(document.querySelector('#clVideoList')); return s.overflowY === 'auto' && s.maxHeight !== 'none'; }"),
             "390px: 設定の「コラボ」節でも、配信の一覧は枠の中でスクロールする(延々と続かない)")
        pg.select_option("#clF", "free")
        pg.keyboard.press("Escape")
        pg.set_viewport_size({"width": 1440, "height": 900})
        for theme in ("dark", "light"):
            pg.evaluate("t => UIKit.theme.set(t)", theme)
            for step in ("rank", "queue", "review"):
                pg.evaluate("s => Studio.go(s)", step)
                pg.wait_for_timeout(150)
                bad = pg.evaluate(CONTRAST_JS)
                c.ok(not bad, "%s の %s で読みにくい文字(コントラスト 3 未満)が無い %s" % (theme, step, json.dumps(bad, ensure_ascii=False)[:300] if bad else ""))
        # ---- 段2 監査 11: ③ 確認の設定の保存・読み込みの失敗を出す(⚙ の印と引き出しの先頭の再試行)・読めないまま既定値で上書きしない
        print("[設定の保存・読み込みの失敗(監査 11)]")
        pg.evaluate("Studio.go('review')"); pg.wait_for_timeout(200)
        sfail = {"put": True, "get": False, "puts": 0}

        def st_route(route):
            if route.request.method == "PUT":
                sfail["puts"] += 1
            if (route.request.method == "PUT" and sfail["put"]) or (route.request.method == "GET" and sfail["get"]):
                route.fulfill(status=500, content_type="application/json", body=json.dumps({"error": "boom", "message": "テストで失敗させた"}))
            else:
                route.continue_()

        def wait_page(expr, ms=10000):   # 同期版の route は Playwright を呼んでいる間しか動かないので、time.sleep ではなく画面の側で待つ
            for _ in range(ms // 100):
                if pg.evaluate(expr):
                    return True
                pg.wait_for_timeout(100)
            return False
        spat = re.compile(r".*/api/settings$")
        pg.route(spat, st_route)
        was = bool((serve.STORE.get_ui().get("review") or {}).get("muted"))
        toggle = "(v => { const e = document.querySelector('#rvMute'); e.checked = v; e.dispatchEvent(new Event('change', { bubbles: true })); })(%s)"
        pg.evaluate(toggle % ("false" if was else "true"))
        c.ok(wait_page("() => document.querySelector('#btnSettings').getAttribute('data-ui-status') === 'err'")
             and "テストで失敗させた" in (pg.get_attribute("#btnSettings", "title") or ""), "保存の失敗: ⚙ に印と理由")
        pg.click("#btnSettings")
        c.ok(wait_page("() => !document.querySelector('.ui-settings-status').hidden", 5000) and "設定を保存できていません" in pg.inner_text(".ui-settings-status"),
             "設定の引き出しの先頭に理由と「もう一度」")
        sfail["put"] = False
        pg.click(".ui-settings-status button")
        c.ok(wait_page("() => document.querySelector('.ui-settings-status').hidden && !document.querySelector('#btnSettings').hasAttribute('data-ui-status')")
             and bool((serve.STORE.get_ui().get("review") or {}).get("muted")) == (not was), "「もう一度」で保存でき、印が消える")
        pg.keyboard.press("Escape")
        sfail["get"] = True
        pg.reload(); pg.wait_for_selector("#btnSettings")   # ① の条件の欄(#rkCond)も設定から作るので、読めないときは待たない
        c.ok(wait_page("() => document.querySelector('#btnSettings').getAttribute('data-ui-status') === 'err'")
             and "読み込めませんでした" in (pg.get_attribute("#btnSettings", "title") or ""), "読み込みの失敗: ⚙ に印と理由")
        puts = sfail["puts"]
        pg.evaluate(toggle % ("true" if was else "false"))
        pg.wait_for_timeout(1200)
        c.ok(sfail["puts"] == puts and bool((serve.STORE.get_ui().get("review") or {}).get("muted")) == (not was), "読めないまま変えても保存しない(既定値で上書きしない)")
        sfail["get"] = False
        pg.click("#btnSettings")
        wait_page("() => !document.querySelector('.ui-settings-status').hidden", 5000)
        c.ok("読み直す" in pg.inner_text(".ui-settings-status button"), "引き出しに「読み直す」")
        pg.click(".ui-settings-status button")
        c.ok(wait_page("() => document.querySelector('.ui-settings-status').hidden && document.querySelector('#rvMute').checked === %s" % ("false" if was else "true")),
             "「読み直す」で保存済みの設定が入り、印が消える")
        pg.keyboard.press("Escape")
        pg.unroute(spat)
        c.ok(not errors, "画面のエラーが出ていない %s" % errors[:3])
        ctx.close()

        if shots:
            take_shots(br, base, fx, shots)
        br.close()
    return c


def take_shots(br, base, fx, out):
    os.makedirs(out, exist_ok=True)
    sizes = [("1440", {"width": 1440, "height": 900}), ("1024", {"width": 1024, "height": 768}), ("390", {"width": 390, "height": 844})]
    for scheme in ("light", "dark"):
        for tag, vp in sizes:
            ctx = br.new_context(viewport=vp, color_scheme=scheme)
            pg = ctx.new_page()
            pg.goto(base); pg.wait_for_selector("#rkCond")
            pg.evaluate("Studio.go('rank')")
            pg.click("#btnGo"); pg.wait_for_selector("#results .rk-table", timeout=30000)
            pg.check("#results tr[data-vid] .pk >> nth=1")
            pg.screenshot(path=os.path.join(out, "cs_rank_%s_%s.png" % (scheme, tag)))
            pg.evaluate("Studio.go('queue')"); pg.wait_for_timeout(500)
            pg.screenshot(path=os.path.join(out, "cs_queue_%s_%s.png" % (scheme, tag)))
            pg.evaluate("Studio.go('review')")
            wait_js(pg, "() => window.Studio && document.querySelector('#rvPickBtn')")
            open_video(pg, fx["a"]); pg.wait_for_selector('#rvList .rv-mark-row[data-id="m1"]'); pg.wait_for_timeout(700)
            pg.screenshot(path=os.path.join(out, "cs_review_%s_%s.png" % (scheme, tag)))
            if tag == "1440":
                pg.screenshot(path=os.path.join(out, "cs_review_full_%s.png" % scheme), full_page=True)
                pg.click("#rvTheater"); pg.wait_for_timeout(400)
                pg.screenshot(path=os.path.join(out, "cs_review_theater_%s.png" % scheme))
                pg.click("#rvTheater")
            pg.click("#btnSettings"); pg.wait_for_timeout(300)
            pg.click("#setCollab summary"); pg.wait_for_selector(".cl-group")
            pg.click('.cl-member:not(.is-base) [data-act="anchor"]')
            pg.screenshot(path=os.path.join(out, "cs_collab_%s_%s.png" % (scheme, tag)))
            pg.click("#setCollab summary")   # コラボの節を閉じ、事務所の登録を開く
            pg.click("#setReg summary"); pg.wait_for_timeout(200)
            pg.screenshot(path=os.path.join(out, "cs_settings_%s_%s.png" % (scheme, tag)))
            ctx.close()


def main():
    args = sys.argv[1:]
    shots = None
    if "--shots" in args:
        shots = os.path.abspath(args[args.index("--shots") + 1])
    home = tempfile.mkdtemp(prefix="clip-studio-ui-")
    try:
        mounted = "--mounted" in args
        # .runtime は一時フォルダに(取り込むと書く。単独でも、同時に動いている他のテストのツールの .runtime を「起動中の他のツール」と読まないように)
        os.environ["YTT_RUNTIME_DIR"] = os.path.join(home, ".runtime")
        fx = fixture(home)
        srv, port = start_mounted() if mounted else start_server()
        if "--serve" in args:
            print("Preview: http://localhost:%d/" % port, flush=True)
            print("Fixture: " + home, flush=True)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                return 0
        c = run_checks(port, fx, shots)
        srv.shutdown()
        if mounted:
            MOUNT["sup"].unmount_all()
        print("結果: %d 件中 %d 件 OK" % (c.n, c.n - len(c.fails)))
        if c.fails:
            print("NG:\n  " + "\n  ".join(c.fails))
        return 1 if c.fails else 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
