"""画面の通し確認(Playwright + 疑似データのサーバー)。

    python e2e_ui.py                 # 主要な操作を自動で確かめる(終了コード 0 = すべて OK)
    python e2e_ui.py --shots DIR     # あわせて各画面のスクリーンショットを DIR に保存(ダーク/ライト × 1440x900・1024x768・390幅)
    python e2e_ui.py --serve         # 疑似データのサーバーだけ立てて待つ(ブラウザで手で見る用。Ctrl+C で終了)
    python e2e_ui.py --mounted       # 入口の統合サーバーに取り込んだ形(http://localhost:<port>/studio/・CSP・合言葉あり)で同じ確認をする

STUDIO_FAKE=1(YouTube へは接続しない)で、生成した短い動画・専用の一時フォルダだけを使う。ポートは空きポート(他のテストと同時に走らせても衝突しない)。
必要: ffmpeg、playwright(chromium)。
確かめること: タブ切り替えと復元 / テーマ切り替えの保存 / ダーク表示で入力欄が白くならない / マークの採用・不採用が保存される /
書き出しボタンの有効・無効 / 外から来る文字列(タイトル・ラベル)が HTML にならない / ?url= は欄に入れるだけ / ? でキー一覧 /
設定の引き出し / 「他のツール」メニュー / 書き出し後の「編集で開く」リンク / 狭い画面で横にはみ出さない
v0.8.0(画面の全面見直し): ① 事務所を登録すると、触っていない事務所にチェックが入る・外した事務所は外れたまま / 結果の「全部まとめて」と「事務所ごと」/
② 失敗の説明(よくある原因と対処・元のメッセージ) / ③ 配信の選択(検索)・プレーヤーが使えないときに自動再生で通知を出さない・
どの表示でも「書き出し」への入口・狭い画面の移動・微調整のボタンが 28px 以上 / ④ 配信の検索・絞り込み・枠の中でスクロール・メンバーの配信者名 / 入口へ戻るリンク
"""
import json
import os
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
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
    """入口(app/launch.py)の統合サーバーにスタジオを取り込んで立てる。fixture で使った serve モジュールをそのまま取り込ませる
    (別に読み込むと、データの置き場所などの設定が別になるため)。"""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
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
        c.ok(pg.get_attribute("html", "data-theme") == "light", "初回は OS の設定(ライト)に合わせる")
        c.ok(pg.locator("#steps .ui-tab").count() == 4, "①〜④のタブがある")
        c.ok((pg.text_content("#ver") or "").startswith("v"), "版が表示される")
        c.ok("キー操作" in (pg.text_content("#btnKeys") or ""), "キーボードの近道のボタンは「キー操作」(用語集)")
        if MOUNT["prefix"]:
            c.ok(pg.is_visible("a.ui-home[data-ui-home]") and pg.get_attribute("a.ui-home", "href") == "/", "入口に取り込まれているときは、ヘッダーに入口へ戻るリンクが出る")
        else:
            c.ok(not pg.is_visible("a.ui-home[data-ui-home]"), "単独で動いているときは、入口へ戻るリンクを出さない")
        home_x = pg.evaluate("() => { const a = document.querySelector('a.ui-home'), m = document.querySelector('#toolMenu'); return a && m ? [a.compareDocumentPosition(m) & 4] : null; }")
        c.ok(home_x == [4], "入口へのリンクは「他のツール」の左")
        pg.click("#toolMenu summary")
        TOOL_LINKS = "#toolNav a:has(.ui-brand-mark:not([data-tool=portal]))"   # ui-kit v3: 入口に取り込まれているときは先頭に「入口」「案件の一覧」も入る
        links = pg.eval_on_selector_all(TOOL_LINKS, "els => els.map(a => a.getAttribute('href'))")
        c.ok(len(links) == 2 and any(":8775" in h for h in links) and not any(":8810" in h for h in links),
             "他のツール: /api/siblings が無いときは既定のポートでリンク(スタジオ・編集。cut2resolve は編集の部品なので出さない): %s" % links)
        home = pg.eval_on_selector_all("#toolNav a:has(.ui-brand-mark[data-tool=portal])", "els => els.map(a => a.getAttribute('href'))")
        c.ok(home == (["/", "/cases.html"] if MOUNT["prefix"] else []), "他のツール: 入口に取り込まれているときだけ、先頭に入口・案件の一覧: %s" % home)
        pg.keyboard.press("Escape")
        c.ok(not pg.evaluate("document.querySelector('#toolMenu').open"), "Esc で他のツールのメニューが閉じる")
        # /api/siblings があるサーバー(サーバー担当が実装中)の応答を模して、実際のポートと「起動していない」表示を確かめる
        pg2 = ctx.new_page()
        pg2.route("**/api/siblings", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tools": {"studio": port, "transcribe": 8779}})))
        pg2.goto(base); pg2.wait_for_selector("#rkCond")
        pg2.click("#toolMenu summary")
        links2 = pg2.eval_on_selector_all(TOOL_LINKS, "els => els.map(a => [a.getAttribute('href'), a.className])")
        c.ok(any(":8779" in h for h, _ in links2), "他のツール: /api/siblings のポートを使う")
        c.ok(pg2.evaluate("Studio.toolUrl('transcribe', '/?media=x')") == "http://localhost:8779/?media=x", "受け渡しのリンクも実際のポートを使う")
        pg2.close()
        pg3 = ctx.new_page()   # 編集が起動していないとき
        pg3.route("**/api/siblings", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tools": {"studio": port}})))
        pg3.goto(base); pg3.wait_for_selector("#rkCond")
        pg3.click("#toolMenu summary")
        links3 = pg3.eval_on_selector_all(TOOL_LINKS, "els => els.map(a => [a.getAttribute('href'), a.className])")
        c.ok(any(":8775" in h and "cs-tool-off" in k for h, k in links3), "他のツール: 起動していないツールはそう表示する: %s" % links3)
        pg3.close()
        for step, pane in (("queue", "#paneQueue"), ("review", "#paneReview"), ("collab", "#paneCollab"), ("rank", "#paneRank")):
            pg.click('#steps [data-step="%s"]' % step)
            c.ok(pg.is_visible(pane) and pg.get_attribute('#steps [data-step="%s"]' % step, "aria-pressed") == "true", "タブ切り替え: %s" % step)
        pg.click('#steps [data-step="collab"]')
        pg.reload(); pg.wait_for_selector("#clMake")
        c.ok(pg.is_visible("#paneCollab"), "再読み込みで最後のタブ(④)に戻る")

        print("[テーマ]")
        pg.click("[data-theme-toggle]")
        c.ok(pg.get_attribute("html", "data-theme") == "dark", "切り替えボタンでダークになる")
        pg.reload(); pg.wait_for_selector("#clMake")
        c.ok(pg.get_attribute("html", "data-theme") == "dark" and pg.evaluate("localStorage.getItem('ytt:theme')") == "dark", "テーマの選択が保存され、再読み込み後もダーク")

        print("[③ 確認・書き出し]")
        pg.click('#steps [data-step="review"]')
        pg.click("#rvPickBtn")
        c.ok(wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 3"), "③ 配信の選択: 一覧に全部の配信が出る")
        pg.fill("#rvPickQ", "テスト動画 A")
        wait_js(pg, "() => document.querySelectorAll('#rvPickList .rv-prow').length === 1")
        c.ok("1 / 3" in (pg.text_content("#rvPickN") or ""), "③ 配信の選択: 題名で探せる(件数も出る)")
        pg.fill("#rvPickQ", "")
        open_video(pg, fx["a"])
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="m1"]')
        c.ok("動画ファイル" in (pg.text_content("#rvChips") or ""), "③ 開いている配信の「だれの」(動画ファイル・配信者)を出す")
        if MOUNT["token"]:   # まとめて実行(docs/edit-tool-design.md の 12 ⑦(a)): 入口の中だけ。案件の画面と同じ API(入口の /api/autorun)
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
            ok = wait_js(pg, "() => /中止|止まりました|完了/.test(document.querySelector('#rvAutoBar .pill').textContent)", 20000)
            c.ok(ok, "③ 帯の「中止」で止められる(または終わっている): " + (pg.text_content("#rvAutoBar .pill") or ""))
        else:
            c.ok(pg.is_hidden("#rvAuto"), "③ 単体で開いたときは「まとめて実行」を出さない(入口の中だけ)")
        wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length >= 4")
        bg = pg.eval_on_selector(".rv-trow input", "el => getComputedStyle(el).backgroundColor")
        c.ok(luminance(rgb_of(bg)) < 0.2, "ダーク表示でマークの時刻の入力欄が暗い背景(以前は白): %s" % bg)
        bg2 = pg.eval_on_selector(".rv-labelrow input", "el => getComputedStyle(el).backgroundColor")
        c.ok(luminance(rgb_of(bg2)) < 0.2, "ダーク表示でラベルの入力欄が暗い背景: %s" % bg2)
        c.ok(pg.is_visible("#rvGraph") and pg.locator("#rvGSvg .rv-g-area").count() == 1, "盛り上がりグラフが出る")
        pg.check("#rvGLines")
        c.ok(pg.locator("#rvGSvg .rv-g-line").count() == 3, "材料ごとの線(音量・チャット・コメント)")
        line_colors = pg.eval_on_selector_all("#rvGSvg .rv-g-line", "els => els.map(e => getComputedStyle(e).stroke)")
        kit = pg.evaluate("['--c-audio','--c-chat','--c-com'].map(v => { const d = document.createElement('i'); d.style.color = 'var(' + v + ')'; document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove(); return c; })")
        c.ok(line_colors == kit, "グラフの線の色は ui-kit の --c-audio / --c-chat / --c-com")
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
        c.ok(pg.is_visible("#keyHelp") and "IN(開始)" in (pg.text_content("#keyHelpBody") or ""), "? キーでキー操作の一覧が開く(③のキーも載る)")
        if shots:
            for sc in ("dark",):
                pg.screenshot(path=os.path.join(shots, "cs_keyhelp_%s.png" % sc))
        pg.keyboard.press("Escape")
        c.ok(not pg.is_visible("#keyHelp"), "Esc で閉じる")
        pg.click("#btnSettings")
        c.ok(pg.is_visible("#settingsBox") and pg.is_visible("#setKey"), "設定の引き出しが開く")
        pg.evaluate("() => { const v = document.querySelector('#rvHost video'); if (v) v.pause(); }")   # y キーの「次の候補へ」で再生中のことがある
        pg.wait_for_timeout(300)
        now0 = pg.input_value("#rvNow")
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(200)
        c.ok(pg.input_value("#rvNow") == now0, "設定を開いている間は ③ のショートカットが効かない")
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
        c.ok(not pg.is_visible("#settingsBox"), "Esc で設定が閉じる")
        # 書き出し → 他のツールへのリンク
        wait_js(pg, "() => document.querySelector('#rvSave').dataset.k !== 'pending'")
        pg.click("#rvExpRun")
        pg.wait_for_selector("#rvExpList .rv-ejob.st-ok", timeout=60000)
        wait_js(pg, "() => !document.querySelector('#rvExpCancel') || document.querySelector('#rvExpCancel').hidden", 60000)
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
        pg.keyboard.press("k"); pg.wait_for_timeout(150)
        c.ok(any("再生できません" in t for t in pg.evaluate("window.__toasts")), "自分で再生を押したときは知らせる")
        pg.unroute("https://www.youtube.com/**")

        print("[外から来る文字列]")
        open_video(pg, fx["b"])
        pg.wait_for_selector('#rvList .rv-mark-row[data-id="x1"]')
        c.ok(pg.text_content("#rvCurLabel") == XSS_TITLE, "動画のタイトルは文字のまま表示される")
        c.ok(pg.input_value('#rvList [data-f="label"]') == XSS_LABEL, "ラベルは文字のまま")
        pg.click('#steps [data-step="collab"]')
        pg.wait_for_selector(".cl-group")
        c.ok(XSS_TITLE in (pg.text_content("#paneCollab") or ""), "④ でもタイトルは文字のまま")
        c.ok(pg.evaluate("window.__xss === undefined") and pg.locator("main img[src='x']").count() == 0, "タイトル・ラベルの HTML が実行・表示されない")

        print("[④ コラボ]")
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
            for step in ("rank", "queue", "review", "collab"):
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
        pg.click('#rvJump [data-jump="export"]'); pg.wait_for_timeout(900)
        c.ok(pg.evaluate("() => { const r = document.querySelector('#rvExport').getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight / 2; }"), "「書き出し」を押すと書き出しの欄へ移る")
        pg.click('#rvJump [data-jump="marks"]'); pg.wait_for_timeout(900)
        c.ok(pg.evaluate("() => { const r = document.querySelector('#rvClipbox').getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight / 2; }") and pg.is_visible("#rvJump"),
             "「マーク」を押すとマークの一覧へ移る(案内は上に残る)")
        small = pg.evaluate("() => [...document.querySelectorAll('#rvList .rv-nudges .btn, #rvList .rv-stgroup .btn, #rvList .rv-fold, #rvQuickSlots .rv-step')].filter(b => b.offsetParent && b.getBoundingClientRect().height < 27.5).length")
        c.ok(small == 0, "390px の ③: 微調整・判定・長さのボタンは 28px 以上(小さいもの %s 個)" % small)
        pg.evaluate("Studio.go('collab')")
        pg.select_option("#clF", "all"); pg.wait_for_timeout(200)
        c.ok(pg.evaluate("() => { const s = getComputedStyle(document.querySelector('#clVideoList')); return s.overflowY === 'auto' && s.maxHeight !== 'none'; }"),
             "390px の ④: 配信の一覧は枠の中でスクロールする(延々と続かない)")
        pg.select_option("#clF", "free")
        pg.set_viewport_size({"width": 1440, "height": 900})
        for theme in ("dark", "light"):
            pg.evaluate("t => UIKit.theme.set(t)", theme)
            for step in ("rank", "queue", "review", "collab"):
                pg.evaluate("s => Studio.go(s)", step)
                pg.wait_for_timeout(150)
                bad = pg.evaluate(CONTRAST_JS)
                c.ok(not bad, "%s の %s で読みにくい文字(コントラスト 3 未満)が無い %s" % (theme, step, json.dumps(bad, ensure_ascii=False)[:300] if bad else ""))
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
            pg.evaluate("Studio.go('collab')"); pg.wait_for_selector(".cl-group")
            pg.click('.cl-member:not(.is-base) [data-act="anchor"]')
            pg.screenshot(path=os.path.join(out, "cs_collab_%s_%s.png" % (scheme, tag)))
            pg.click("#btnSettings"); pg.wait_for_timeout(300)
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
