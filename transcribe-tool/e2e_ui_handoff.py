#!/usr/bin/env python3
"""画面の刷新(2026-09-24)の通し確認(Playwright + 疑似モード):
   受け渡し(?media= / ?clip= の受け取り・元の配信の表示・動画の隣に保存・cut2resolve へのリンク・409)、
   テーマの保存の1本化(ヘッダーのボタンと「表示」の設定・古い保存の引き継ぎ)、「他のツール」メニュー、
   直した不具合(保存中に開いている文書を消す・前の文書の動画の読み込み待ち・時刻の直しで今の行・結合の終了・
   キーの押しっぱなし・話者の色の CSS 差し込み・元の配信の文字のエスケープ)。

    python3 e2e_ui_handoff.py
"""
import http.server
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CUT2RESOLVE_DIR", os.path.join(os.path.dirname(HERE), "cut2resolve"))   # 単体で動かすサーバーが pack.py(カットの下書き・見積もり・zip)を見つけられるように
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように


def call(port, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeC2R(http.server.BaseHTTPRequestHandler):
    """cut2resolve のふり(/api/ping に app=cut2resolve で答えるだけ)。/api/siblings が「起動中」と判断するため"""
    def do_GET(self):
        body = json.dumps({"app": "cut2resolve", "version": "0.0.0"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def clip_json(media, title, url, start=1234.5, end=1279.7):
    return {"schema": "youtube-tools-clip/v1", "tool": {"name": "clip-studio", "version": "0.2.0"}, "createdAt": "2026-09-24T12:00:00+09:00",
            "media": {"path": media, "name": os.path.basename(media), "durationSec": 12},
            "source": {"kind": "youtube", "videoId": "abcdefghijk", "url": url, "title": title, "path": None},
            "range": {"start": start, "end": end}, "mark": {"id": "m12", "label": "見どころ<b>", "status": "exported", "src": "manual"}, "export": {"mode": "precise"}}


def main():
    tmp = tempfile.mkdtemp()
    for n in ("serve.py", "index.html", "app.js", "cut.js", "pack-tab.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            shutil.copy(p, tmp)
    vids = os.path.join(tmp, "videos")
    os.makedirs(vids)

    def make_wav(name, dur=12):
        p = os.path.join(vids, name)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % dur, p], check=True)
        return p

    clipv = make_wav("clip_0012.wav")
    evil = '<img src=x onerror="window.__xss=1">配信'
    with open(os.path.join(vids, "clip_0012.clip.json"), "w", encoding="utf-8") as f:
        json.dump(clip_json(clipv, evil, "https://www.youtube.com/watch?v=abcdefghijk"), f, ensure_ascii=False)
    newv = make_wav("clip_0013.wav")   # 「編集」: まだ文書の無い切り抜き(?media= で「文字起こしする / せずに開く」を選ばせる)
    with open(os.path.join(vids, "clip_0013.clip.json"), "w", encoding="utf-8") as f:
        json.dump(clip_json(newv, evil, "https://www.youtube.com/watch?v=abcdefghijk"), f, ensure_ascii=False)
    jsv = make_wav("jsurl.wav")
    with open(os.path.join(vids, "jsurl.clip.json"), "w", encoding="utf-8") as f:
        json.dump(clip_json(jsv, '<b id="evil2">太字</b>リンクにしない配信', "javascript:window.__xss=2"), f, ensure_ascii=False)
    plain = make_wav("plain.wav")
    gone = make_wav("gone.wav")

    rt = os.path.join(tmp, ".runtime")
    os.makedirs(rt)
    c2r_port = free_port()
    c2r = http.server.ThreadingHTTPServer(("127.0.0.1", c2r_port), FakeC2R)
    threading.Thread(target=c2r.serve_forever, daemon=True).start()
    with open(os.path.join(rt, "cut2resolve.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": "cut2resolve", "port": c2r_port, "version": "0.0.0", "startedAt": "2026-09-24T12:00:00+09:00"}, f)

    port = free_port()
    env = dict(os.environ, YTT_RUNTIME_DIR=rt, TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.01")
    proc = subprocess.Popen([sys.executable, os.path.join(tmp, "serve.py"), str(port), "--no-open"], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors, ok = [], True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    def make(path, title):
        j = call(port, "POST", "/api/transcribe", {"sourcePath": path, "model": "small", "language": "ja", "title": title})
        for _ in range(200):
            job = next(x for x in call(port, "GET", "/api/jobs")["jobs"] if x["id"] == j["id"])
            if job["state"] in ("done", "error"):
                return job["tid"]
            time.sleep(0.1)

    try:
        for _ in range(100):
            try:
                call(port, "GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)
        tid_clip = make(clipv, "切り抜き文書")
        tid_plain = make(plain, "普通の文書")
        tid_del = make(plain, "消す文書")
        tid_keep = make(plain, "残る文書")
        tid_gone = make(gone, "動画のない文書")
        tid_rows = make(plain, "行の文書")
        call(port, "PUT", "/api/transcript?id=" + tid_rows, {"title": "行の文書", "speakers": [{"id": "S1", "name": "悪い色", "color": "red;background-image:url(http://127.0.0.1:1/leak.png)"}],
                                                          "segments": [{"id": "a", "start": 0, "end": 5, "text": "一", "speaker": "S1"}, {"id": "b", "start": 1, "end": 3, "text": "二", "speaker": "S1"},
                                                                       {"id": "c", "start": 6, "end": 7, "text": "三"}, {"id": "d", "start": 8, "end": 9, "text": "四"}]})
        # サーバーの保存(PUT)は色を整えるので、手で直した文書・古い版の文書を想定して、ファイルを直接書き換える
        rp = os.path.join(tmp, "transcripts", tid_rows + ".json")
        with open(rp, encoding="utf-8") as f:
            rd = json.load(f)
        rd["speakers"][0]["color"] = "red;background-image:url(http://127.0.0.1:1/leak.png)"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(rd, f, ensure_ascii=False)
        # 動画のない文書: 途中の行に「前回の続き」を置いてから、動画を消す(読み込みに失敗して loadedmetadata が来ない文書)
        gdoc = call(port, "GET", "/api/transcript?id=" + tid_gone)
        os.remove(gone)
        n_jobs = len(call(port, "GET", "/api/jobs")["jobs"])

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1500, "height": 1000})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            base = "http://localhost:%d/" % port

            def open_doc(title):
                if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                    pg.click("#btnMenu")
                pg.click("[data-side-tab=files]")
                pg.fill("#txSearch", title)
                pg.locator("#txList .txi").filter(has_text=title).locator(".t").first.click()
                # 検索欄は値を消すだけ(開いた直後に画面が狭いとメニューが自動で閉じ、見えない欄への fill は待ち続けてしまうため)
                pg.evaluate("(() => { const q = document.querySelector('#txSearch'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); })()")
                pg.wait_for_function("document.querySelector('#docTitle').value === %s" % json.dumps(title), timeout=15000)
                pg.wait_for_selector("#segs .seg")

            # ==================== 1) ?media= の受け取り ====================
            pg.goto(base + "?nofs=1&media=" + urllib.parse.quote(clipv) + "#cut")   # 「編集」: 文書のある動画 → その文書を開く(タブは URL のまま)
            pg.wait_for_function("document.querySelector('#docTitle').value === '切り抜き文書'", timeout=10000)
            check(pg.evaluate("location.search") == "?nofs=1" and pg.evaluate("location.hash") == "#cut" and pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true",
                  "?media= で文書のある動画は、その文書を開く(URL から media を消す・タブは #cut のまま): %s" % pg.evaluate("[location.search, location.hash, document.querySelector('[data-edtab=cut]').getAttribute('aria-selected')]"))
            check(len(call(port, "GET", "/api/jobs")["jobs"]) == n_jobs, "文書のある動画を開いても、文字起こしは始めない")
            pg.goto(base + "?nofs=1&media=" + urllib.parse.quote(newv) + "#tx")
            pg.wait_for_selector("#srcClip:not([hidden])", timeout=10000)
            check(pg.input_value("#srcPath") == newv, "?media= の値が、新規文字起こしのファイル欄に入る")
            check(pg.is_visible("#mediaChoice") and pg.is_visible("#mcTx") and pg.is_visible("#mcOpen"), "まだ文書の無い動画は「文字起こしをする / 文字起こしせずに開く」を選ばせる")
            check(pg.evaluate("location.search") == "?nofs=1", "読んだら URL から media を消す(ほかの値は残す): %s" % pg.evaluate("location.search"))
            check(pg.get_attribute("[data-side-tab=start]", "aria-selected") == "true" and pg.is_visible("#srcPath"), "メニューの「新規」が開いて、ファイル欄が見える")
            time.sleep(0.5)
            check(len(call(port, "GET", "/api/jobs")["jobs"]) == n_jobs, "URL だけでは文字起こしを始めない(ジョブが増えない)")
            txt = pg.inner_text("#srcClip")
            check("元の配信" in txt and "20:34〜21:19" in txt and "見どころ<b>" in txt, "隣の .clip.json から「元の配信: タイトル 20:34〜21:19」が出る: %s" % txt)
            check("<img" in txt and pg.locator("#srcClip img").count() == 0 and pg.locator("#srcClip b b").count() == 0 and not pg.evaluate("window.__xss"),
                  "配信タイトル・マーク名の中の HTML は、文字としてそのまま出る(タグとして働かない)")
            href = pg.get_attribute("#srcClip a", "href") or ""
            check(href.startswith("https://www.youtube.com/watch?v=abcdefghijk") and "t=1234s" in href and pg.get_attribute("#srcClip a", "rel") == "noopener noreferrer",
                  "YouTube の URL は、元の配信のその位置へのリンクになる: %s" % href)
            check("自動では始めません" in pg.inner_text("#toast"), "自動では始めない旨の案内: " + pg.inner_text("#toast"))
            pg.click("#mcOpen")   # 文字起こしせずに開く → 行の無い文書ができて、カットのタブが開く
            pg.wait_for_function("document.querySelector('#docTitle').value === 'clip_0013'", timeout=10000)
            check(pg.get_attribute("[data-edtab=cut]", "aria-selected") == "true" and pg.evaluate("location.hash") == "#cut" and not pg.is_visible("#mediaChoice"),
                  "「文字起こしせずに開く」で文書ができ、カットのタブが開く: %s" % pg.evaluate("[location.hash, document.querySelector('[data-edtab=cut]').getAttribute('aria-selected'), !document.querySelector('#mediaChoice').hidden]"))
            check(len(call(port, "GET", "/api/jobs")["jobs"]) == n_jobs, "文字起こしせずに開いたときは、文字起こしを始めない")
            pg.click("[data-edtab=tx]")
            check(pg.is_visible("#noRows") and pg.is_visible("#btnTxInto") and pg.locator("#segs .seg").count() == 0,
                  "行の無い文書の 1 文字起こし のタブには「この動画を文字起こしする」が出る")
            pg.click("#btnTxInto")
            pg.wait_for_function("document.querySelectorAll('#segs .seg').length > 0", timeout=20000)
            check(pg.input_value("#docTitle") == "clip_0013" and pg.is_hidden("#noRows"), "文字起こしが、同じ文書に入る(題名はそのまま・案内は消える)")
            n_jobs = len(call(port, "GET", "/api/jobs")["jobs"])

            # ==================== 2) ?clip= の受け取り・リンクにしない URL・見つからない動画 ====================
            pg.goto(base + "?clip=" + urllib.parse.quote(os.path.join(vids, "clip_0012.clip.json")))
            pg.wait_for_function("document.querySelector('#srcPath').value !== ''", timeout=10000)
            check(pg.input_value("#srcPath") == clipv, "?clip= のときは、.clip.json が指す動画がファイル欄に入る: %s" % pg.input_value("#srcPath"))
            check(pg.evaluate("location.search") == "" and "元の配信" in pg.inner_text("#srcClip"), "URL から clip が消え、元の配信が出る")
            pg.goto(base + "?media=" + urllib.parse.quote(jsv))
            pg.wait_for_selector("#srcClip:not([hidden])")
            check(pg.locator("#srcClip a").count() == 0 and "リンクにしない配信" in pg.inner_text("#srcClip"), "https://www.youtube.com/ で始まらない URL(javascript: など)はリンクにしない")
            check(pg.locator("#evil2").count() == 0 and '<b id="evil2">' in pg.inner_text("#srcClip"), "リンクにしないときのタイトルも、HTML は文字のまま")
            pg.goto(base + "?media=" + urllib.parse.quote(os.path.join(vids, "nothing.mp4")))
            pg.wait_for_selector("#srcClip.warn:not([hidden])")
            check("見つかりません" in pg.inner_text("#srcClip"), "動画が見つからないときは、その旨を出す(例外にしない): " + pg.inner_text("#srcClip"))
            pg.fill("#srcPath", plain)
            pg.dispatch_event("#srcPath", "change")
            pg.wait_for_selector("#srcClip", state="hidden")
            check(True, "手で入れたパス(.clip.json なし)では、元の配信の欄は消える")

            # ==================== 3) 開いた文書の「元の配信」・動画の隣に保存・cut2resolve へのリンク ====================
            open_doc("切り抜き文書")
            check(pg.is_visible("#docClip") and "元の配信" in pg.inner_text("#docClip") and pg.locator("#docClip img").count() == 0, "clip のある文書は、編集画面にも「元の配信」が出る")
            if not pg.evaluate("document.querySelector('#exDetails').open"):   # v0.15.0: 「道具 ▾」から「書き出し」のカードへ
                pg.click("#btnSpk")
                pg.click("[data-jump=exDetails]")
            # 保存を1.2秒遅らせて、「保存がまだ終わっていないうちに押した」状態を必ず作る
            pg.evaluate("""() => { const of = window.fetch; window.__slowput = true;
              window.fetch = (u, init) => (window.__slowput && init && init.method === 'PUT' && String(u).includes('/api/transcript?')) ? new Promise(r => setTimeout(r, 1200)).then(() => of(u, init)) : of(u, init); }""")
            pg.locator("#segs textarea").nth(0).fill("直してすぐ保存")
            pg.click("[data-beside=transcript-v1]")   # 自動保存を待たずに押す → 先に保存(の完了を待って)から書き出す
            pg.wait_for_selector("#handoffOut:not([hidden])", timeout=10000)
            tpath = os.path.join(vids, "clip_0012.transcript.json")
            check(os.path.isfile(tpath), "動画の隣に clip_0012.transcript.json ができる")
            with open(tpath, encoding="utf-8") as f:
                tv = json.load(f)
            check(tv.get("schema") == "youtube-tools-transcript/v1" and tv["segments"][0]["text"] == "直してすぐ保存" and isinstance(tv.get("clip"), dict),
                  "書き出した中身は、押す直前の編集を含む(保存してから書き出す)・clip も入る")
            check(tpath in pg.inner_text("#handoffOut"), "保存したパスが表示される")
            pg.evaluate("window.__slowput = false")
            pg.wait_for_function("document.querySelector('#openC2R') && document.querySelector('#openC2R').href.includes(':%d/')" % c2r_port, timeout=5000)
            h = pg.get_attribute("#openC2R", "href")
            want = "http://localhost:%d/?video=%s&transcript=%s" % (c2r_port, urllib.parse.quote(clipv, safe=""), urllib.parse.quote(tpath, safe=""))
            check(h == want, "「cut2resolve で開く」は、/api/siblings のポートで動画と文字起こしを渡す: %s" % h)
            pg.click("[data-beside=srt]")
            pg.wait_for_function("document.querySelector('#handoffOut').textContent.includes('.srt')", timeout=10000)
            check(os.path.isfile(os.path.join(vids, "clip_0012.srt")), "字幕(.srt)も動画の隣に保存できる")
            # 別の場所で先に更新 → 409 は「保存が追いついていない」
            cur = call(port, "GET", "/api/transcript?id=" + tid_clip)
            call(port, "PUT", "/api/transcript?id=" + tid_clip, {"title": cur["title"], "speakers": cur["speakers"], "segments": cur["segments"]})
            pg.click("[data-beside=transcript-v1]")
            pg.wait_for_function("document.querySelector('#toast').textContent.includes('追いついていません')", timeout=10000)
            check(True, "保存済みの版と違うとき(409)は、「保存が追いついていません」と出して再試行を促す")

            # ==================== 4) 他のツールのメニュー ====================
            pg.click("#toolMenu summary")
            pg.wait_for_function("document.querySelectorAll('#toolNav a').length === 3")
            links = pg.evaluate("[...document.querySelectorAll('#toolNav a')].map(a => [a.getAttribute('href'), a.getAttribute('aria-current'), a.className])")
            check(links[1][1] == "page" and links[1][0] == "/", "文字起こしツール自身は「いま開いている画面」: %s" % (links[1],))
            check(links[2][0] == "http://localhost:%d/" % c2r_port and "tt-tool-off" not in links[2][2], "起動中の cut2resolve は、実際のポートへのリンク: %s" % (links[2],))
            check("tt-tool-off" in links[0][2], "起動していないスタジオは、灰色にして知らせる: %s" % (links[0],))
            pg.mouse.click(700, 600)
            check(not pg.evaluate("document.querySelector('#toolMenu').open"), "外をクリックするとメニューが閉じる")

            # ==================== 5) テーマ: ヘッダーのボタンと「表示」の設定は1つ ====================
            before = pg.evaluate("document.documentElement.dataset.theme")
            pg.click("[data-theme-toggle]")
            after = pg.evaluate("document.documentElement.dataset.theme")
            check(after != before and pg.evaluate("localStorage.getItem('ytt:theme')") == after, "ヘッダーの切り替えボタンで色が変わり、ui-kit の保存場所(ytt:theme)に残る")
            check(pg.input_value("#vTheme") == after, "「表示」の設定の選択肢も同じ値になる: %s" % pg.input_value("#vTheme"))
            pg.click("#viewMenu summary")
            pg.select_option("#vTheme", "auto")
            check(pg.evaluate("localStorage.getItem('ytt:theme')") is None and pg.evaluate("document.documentElement.dataset.themePref") == "system", "「パソコンの設定に合わせる」で保存を消す(OS に合わせる)")
            pg.select_option("#vTheme", "dark")
            check(pg.evaluate("localStorage.getItem('ytt:theme')") == "dark" and "theme" not in json.loads(pg.evaluate("localStorage.getItem('tx.view.v1')") or "{}"),
                  "「表示」で選んでも ytt:theme に保存し、tx.view.v1 には色を保存しない(保存は1か所)")
            pg.keyboard.press("Escape")
            ctx2 = b.new_context(viewport={"width": 1200, "height": 800}, color_scheme="light")
            ctx2.add_init_script("if (!sessionStorage.getItem('seeded')) { localStorage.setItem('tx.view.v1', JSON.stringify({ theme: 'dark', fs: '17' })); sessionStorage.setItem('seeded', '1'); }")
            p2 = ctx2.new_page()
            p2.goto(base)
            p2.wait_for_selector("#txList .txi", state="attached")
            check(p2.evaluate("document.documentElement.dataset.theme") == "dark" and p2.evaluate("localStorage.getItem('ytt:theme')") == "dark",
                  "以前の版が tx.view.v1 に保存した「暗い」を引き継ぐ(OS がライトでも)")
            v = json.loads(p2.evaluate("localStorage.getItem('tx.view.v1')") or "{}")
            check("theme" not in v and v.get("fs") == "17", "引き継いだら tx.view.v1 から theme を消す(ほかの表示の設定は残る): %s" % v)
            p2.reload()
            p2.wait_for_selector("#txList .txi", state="attached")
            check(p2.evaluate("document.documentElement.dataset.theme") == "dark" and p2.input_value("#vTheme") == "dark", "開き直しても残る")
            ctx2.close()

            # ==================== 6) 話者の色の CSS 差し込み・時刻の直しで今の行・結合の終了・キーの押しっぱなし ====================
            open_doc("行の文書")
            st = pg.evaluate("[...document.querySelectorAll('#segs .seg')].map(r => [r.getAttribute('style') || '', getComputedStyle(r).backgroundImage])")
            check(all("background" not in s_ and bi == "none" for s_, bi in st), "話者の色に CSS を書かれても、行の style に入らない(外への通信をさせない): %s" % st[:2])
            navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
            # 結合: 次の行(二: 1〜3)が先に終わっても、終了は遅い方(5)
            pg.locator("#segs textarea").nth(0).click(); pg.keyboard.press("Escape")
            pg.locator("#segs .seg").nth(0).locator("[data-act=merge]").click()
            times0 = pg.evaluate("[...document.querySelectorAll('#segs .seg')[0].querySelectorAll('input.t')].map(x => x.value)")
            check(pg.locator("#segs .seg").count() == 3 and times0 == ["0:00.0", "0:05.0"], "次の行と結合しても、終了が縮まない(遅い方): %s" % times0)
            # 時刻を直して並びが変わっても、今の行は直した行のまま
            set_time = lambda i, f, val: pg.evaluate("([i, f, v]) => { const el = document.querySelectorAll('#segs .seg')[i].querySelector('input.t[data-f=' + f + ']'); el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); }", [i, f, val])
            set_time(1, "end", "0:09.9")
            set_time(1, "start", "0:09.5")
            texts = pg.evaluate("[...document.querySelectorAll('#segs textarea')].map(t => t.value)")
            nv = navi()
            check(texts == ["一二", "四", "三"] and nv == 2, "時刻を直して行が後ろへ動いても、今の行(太枠)は直した行(三)についていく: %s nav=%s" % (texts, nv))
            # Z の押しっぱなし(キーの自動の繰り返し)では消えない
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("w")
            n0 = pg.locator("#segs .seg").count()
            pg.keyboard.press("z")
            pg.evaluate("window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyZ', key: 'z', repeat: true, bubbles: true }))")
            check(pg.locator("#segs .seg").count() == n0, "Z を押しっぱなしにしても(自動の繰り返し)、2回押しの削除にならない")
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == n0 - 1, "離してもう一度 Z なら削除できる")
            pg.keyboard.press("Control+z")
            # Esc で検索欄・速さの欄から抜けると、すぐに操作キーが使える
            pg.fill("#q", "")
            pg.focus("#q")
            pg.keyboard.press("Escape")
            n1 = navi()
            pg.keyboard.press("w")
            check(pg.evaluate("document.activeElement === document.body") and n1 > 0 and navi() == n1 - 1, "検索欄で Esc → 抜けて、W で前の行へ(取りこぼさない): %s → %s" % (n1, navi()))
            pg.focus("#rate")
            pg.keyboard.press("Escape")
            pg.keyboard.press("s")
            check(navi() == n1, "速さの欄でも Esc で抜けて、S が効く")

            # ==================== 7) 保存の途中で、開いている文書を消す ====================
            open_doc("消す文書")
            pg.evaluate("""() => { const of = window.fetch; window.__slow = true;
              window.fetch = (u, init) => (window.__slow && init && init.method === 'PUT' && String(u).includes('/api/transcript?')) ? new Promise(r => setTimeout(r, 1500)).then(() => of(u, init)) : of(u, init); }""")
            pg.locator("#segs textarea").nth(0).fill("消す前の編集")
            pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存中')", timeout=5000)   # 保存を送っている途中(1.5秒遅らせている)
            pg.click("[data-side-tab=files]")
            pg.fill("#txSearch", "消す文書")
            row = pg.locator("#txList .txi").filter(has_text="消す文書").first
            row.locator(".txi-menu summary").click()
            row.locator("[data-act=del]").click()
            row.locator("[data-act=del]").click()
            pg.wait_for_selector("#noDoc:not([hidden])", timeout=10000)
            pg.evaluate("window.__slow = false")
            pg.fill("#txSearch", "")
            pg.wait_for_timeout(300)
            open_doc("残る文書")
            check(pg.input_value("#docTitle") == "残る文書", "保存の途中で開いている文書を消しても、ほかの文書を開ける(「未保存」が残らない)")
            check("保存に失敗" not in pg.inner_text("#toast"), "消した文書の保存の失敗を出さない: " + pg.inner_text("#toast"))

            # ==================== 8) 動画を読めなかった文書のあとに開いた文書は、その文書の位置で始まる ====================
            pg.evaluate("localStorage.setItem('tx.pos.%s', JSON.stringify({ id: %s, t: 8 }))" % (tid_gone, json.dumps(gdoc["segments"][-1]["id"])))
            open_doc("動画のない文書")
            pg.wait_for_selector("#playerMsg:not([hidden])", timeout=10000)
            open_doc("普通の文書")
            pg.wait_for_function("document.querySelector('#player').readyState >= 1", timeout=10000)
            pg.wait_for_timeout(300)
            t = pg.evaluate("document.querySelector('#player').currentTime")
            check(t < 0.5, "前に開いた(動画を読めなかった)文書の「前回の続き」の位置へ飛ばない: currentTime=%.2f" % t)

            # ==================== 9) v0.15.0 の見直し(単体で開いたとき): カットとパック・キー操作・履歴の一覧・狭い画面の引き出し ====================
            check(pg.inner_text("#btnKeys").strip() == "キー操作" and pg.is_hidden("[data-ui-home]"), "ヘッダーのボタン名は「キー操作」・入口へのリンクは入口の外では出ない")
            pg.click("[data-edtab=pack]")   # 「編集」E4: パックは 3 パック のタブ(この文書は音声だけ(wav)なので、カットとパックには使えない)
            pg.wait_for_function("!document.querySelector('#pkOff').hidden && document.querySelector('#pkOff').textContent.includes('音声だけ')", timeout=15000)
            check(pg.is_disabled("#pkBuild"), "音声だけのファイルは、パックのタブに理由を出して作れなくする: " + pg.inner_text("#pkOff"))
            pg.click("[data-edtab=tx]")
            pg.evaluate("document.querySelectorAll('#segs .seg .sel')[0].click()")
            pg.click("#moreTools summary")   # 「編集」E2: 選んだ行のカット/残すは 1 文字起こし のタブの「まとめて ▾」の中
            pg.wait_for_function("!document.querySelector('#cutSelected').disabled", timeout=3000)   # 表示はフレームごとにまとめて描き直す
            check(pg.is_enabled("#cutSelected"), "行をチェックで選ぶと「選んだ行をカット」が使える")
            pg.click("#cutSelected")
            pg.wait_for_function("document.querySelectorAll('#segs .seg.cut').length === 1", timeout=5000)
            pg.wait_for_function("document.querySelector('#pillCut').textContent.includes('約0:08.00')", timeout=5000)   # 題名の行はフレームごとに描き直す
            check("約0:08.00" in pg.inner_text("#pillCut"), "カットの使えない文書では、以前どおり行の印だけを変える(題名の行の札は目安): " + pg.inner_text("#pillCut"))
            pg.click("#keepSelected")
            pg.wait_for_function("document.querySelectorAll('#segs .seg.cut').length === 0", timeout=5000)
            check(True, "「選んだ行を残す」で戻る")
            pg.evaluate("document.querySelectorAll('#segs .seg .sel')[0].click()")
            open_doc("動画のない文書")
            pg.click("[data-edtab=pack]")
            pg.wait_for_function("!document.querySelector('#pkOff').hidden && document.querySelector('#pkOff').textContent.includes('見つかりません')", timeout=10000)
            check(pg.is_disabled("#pkBuild"), "動画が見つからない文書では、パックのタブに理由を出す: " + pg.inner_text("#pkOff"))
            pg.click("[data-edtab=tx]")
            pg.click("[data-side-tab=files]")
            pg.fill("#txSearch", "動画のない文書")
            check("動画なし" in pg.inner_text("#txList .txi.cur"), "履歴の一覧の行にも「動画なし」の札が出る")
            pg.fill("#txSearch", "")
            # キー操作の手がかり(閉じたら覚える・「キー操作」の一覧から戻せる・? で一覧)
            check(pg.is_visible("#keyHint") and "校正済みにして次へ" in pg.inner_text("#keyHint"), "行の一覧の上に、主なキー操作の手がかりが出る")
            pg.click("#keyHintClose")
            check(pg.is_hidden("#keyHint") and pg.evaluate("localStorage.getItem('tx.keyhint')") == "0", "手がかりを閉じると、閉じたことを覚える")
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("Shift+Slash")
            check(pg.evaluate("document.querySelector('#keys').open"), "? でキー操作の一覧が開く")
            pg.check("#keyHintOn")
            pg.keyboard.press("Escape")
            check(pg.is_visible("#keyHint"), "一覧の「手がかりを出す」で、また出る")
            # 狭い画面(390px): 左のメニューは重ねて出す引き出し。外を押すと閉じる・文字起こしを開くと自動で閉じる
            pg.set_viewport_size({"width": 390, "height": 844})
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pos = pg.evaluate("getComputedStyle(document.querySelector('#menuPanel')).position")
            check(pos == "fixed" and pg.is_visible("#menuScrim"), "390px ではメニューは本文の上に重ねて出す(本文を押しのけない): %s" % pos)
            check(pg.evaluate("document.documentElement.scrollWidth") <= 390, "横にはみ出さない")
            pg.click("#menuScrim", position={"x": 380, "y": 400})
            check("menu-closed" in (pg.get_attribute(".app", "class") or ""), "外(暗い幕)を押すと閉じる")
            pg.click("#btnMenu")
            pg.click("[data-side-tab=files]")
            pg.locator("#txList .txi").filter(has_text="普通の文書").locator(".t").first.click()
            pg.wait_for_function("document.querySelector('#docTitle').value === '普通の文書'", timeout=15000)
            check("menu-closed" in (pg.get_attribute(".app", "class") or ""), "引き出しから文字起こしを開くと、引き出しは自動で閉じる")
            seg_top = pg.evaluate("document.querySelector('#segs .seg').getBoundingClientRect().top")
            check(seg_top < 844, "390px でも、開いた文字起こしの行が1画面目に見える(映像だけで埋まらない): top=%d" % seg_top)
            pg.set_viewport_size({"width": 1500, "height": 1000})

            b.close()
        errors = [e for e in errors if "409" not in e and "404" not in e and "favicon" not in e and "Failed to load resource" not in e]   # 409/404 はこの試験でわざと起こしている
        check(not errors, "画面のエラーなし " + ("" if not errors else str(errors[:5])))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        c2r.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
