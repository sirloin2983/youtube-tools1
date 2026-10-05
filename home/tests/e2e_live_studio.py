#!/usr/bin/env python3
"""リアルタイム切り抜き(線 D の P3。docs/plan/live-clipping-plan.md の 0-8)の通しの確認: 入口にスタジオを取り込み、録画の部品を別のプロセスで立て、
ブラウザでスタジオの画面を操作する。本物の YouTube には繋がない。

    py -3.10 home/tests/e2e_live_studio.py                 # 確かめる(終了コード 0 = すべて OK)
    py -3.10 home/tests/e2e_live_studio.py --shots DIR     # あわせて ③ などのスクリーンショットを DIR に残す
    py -3.10 home/tests/e2e_live_studio.py --chromium      # Edge があっても Playwright の chromium で(再生が要る確認は飛ばす)

作り(e2e_live.py と同じ部品):
  - 入口(launch.py)に studio を取り込む(studio/tests/e2e_ui.py の --mounted と同じ形。STUDIO_FAKE=1)。作業データ・書き出し先・録画の置き場所は全部一時フォルダ
    (YTT_DATA_DIR はこのテストの間だけ一時フォルダにする。先頭の setdefault は ytt_core のテストの決まり)
  - 録画の部品(recorder/recorder.py)は本物を --source direct で。ffmpeg の lavfi で作った H.264 の HLS を手元の HTTP サーバーで配信中のように出して録る
  - 配信の状態は偽の yt-dlp(Live.probe)。URL はスタジオの登録の検査(YouTube の https だけ)を通すため、画面には YouTube の形の URL を入れ、
    入口から録画元への要求(Live.call)だけをテストの中で手元の HLS の URL に読み替える(本番の検査は緩めない。画面・API からは変えられない)
  - ブラウザは Edge(channel="msedge"。H.264 を再生できる)を先に試す。無ければ Playwright の chromium(再生は読み込みまで。再生が要る確認は飛ばす)
  - hls.js の再生位置の受信時刻(hls.playingDate)は、テストの init script で window.Hls を包んで読む(画面のコードには手を入れない)

確かめること(番号は依頼の 1〜14):
  13 オフ: URL を入れても begin に進まず /api/queue/add(今までどおりの解析)・ヘッダーに札が出ない
  1 ホームの「試験中の機能」でオン → 2 ② の URL 欄 →「解析に追加」→ 録画が始まり ③ へ移ってその録画が開く・一覧に kind live
  3 自動で再生(currentTime が進む)・LIVE の帯・「録画中」・ヘッダーの札「録画中 1」
  4 I → O → 追加 → すぐ書き出す → 書き出しの欄に状態 → 済み・30fps・長さ・.clip.json の source.kind live・スタジオのマークが「書き出し済み」
  5 書き出した区間の絶対時刻 = マークした時点の hls.playingDate ± 0.3 秒
  6 タイムラインで頭へ → 「ライブ端へ」  7 ② へ移ると止まる・戻ると続きから  8 見回りで要素が作り直されない
  9 札 → 一覧 →「停止」二度押し → 帯「録画は終わりました…」・札「録画終了」・duration が有限・最後まで再生
  10 終わった録画でマーク → 採用 →「書き出す」  11 設定の引き出しの「ライブの録画」(置き場所・空き・画質 → live.quality → 次の begin)
  12 ?video=<id> で開き直すとマークが残っている  14 コンソールのエラー・404・CSP 違反なし・375px で横にはみ出さない
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)。main で一時フォルダにする
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
STUDIO = os.path.join(REPO, "studio")
sys.path.insert(0, STUDIO)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "recorder", "tests"))
os.environ["STUDIO_FAKE"] = "1"

YT1 = "https://www.youtube.com/watch?v=TESTlive001"   # 画面に入れる配信の URL(録画元へは手元の HLS に読み替える)
YT2 = "https://www.youtube.com/watch?v=TESTlive002"   # 画質の確認用の2本目
TITLE = "テストの配信<b>太字</b>"

# hls.js(../live/hls.min.js を画面が読む)を包んで、作られた Hls を window.__hls に覚える。CSP の違反も数える。画面のコードには手を入れない
INIT_JS = r"""
(() => {
  let H;
  Object.defineProperty(window, 'Hls', { configurable: true, get(){ return H; }, set(v){
    H = typeof v === 'function' ? new Proxy(v, { construct(t, a, nt){ const o = Reflect.construct(t, a, nt); window.__hls = o; return o; } }) : v;
  } });
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
})();
"""
NO_HSCROLL_JS = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
VIDEO = "document.querySelector('#rvHost video')"


def wait_js(pg, expr, timeout=20000):
    """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        try:
            if pg.evaluate(expr):
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def wait_for(fn, timeout=30.0, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


def main():
    args = sys.argv[1:]
    shots = os.path.abspath(args[args.index("--shots") + 1]) if "--shots" in args else None
    if shots:
        os.makedirs(shots, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ytt-live-studio-")
    env = mock.patch.dict(os.environ, {"YTT_DATA_DIR": os.path.join(tmp, "data"), "YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"),
                                       "TRANSCRIBE_DATA_DIR": os.path.join(tmp, "txdata")})
    env.start()
    try:
        return run(tmp, shots, "--chromium" in args)
    finally:
        env.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp, shots, force_chromium):
    import common  # noqa: E402  (studio)
    import serve   # noqa: E402  (studio)
    import launch as L  # noqa: E402
    import mount  # noqa: E402
    import hls_fixture as F  # noqa: E402
    import live_export as LX  # noqa: E402
    from ytt_core import normalize, schemas  # noqa: E402
    from test_launch import free_ports  # noqa: E402

    ok = True
    results = []

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        results.append(bool(cond))
        ok = ok and bool(cond)
        return bool(cond)

    def skip(msg):
        print("SKIP " + msg, flush=True)

    # --- スタジオ(作業データ・書き出し先は一時フォルダ)を入口に取り込む ---
    out_dir = os.path.join(tmp, "out")
    os.makedirs(out_dir)
    serve.init(os.path.join(tmp, "studio-home"))
    common.set_out_dir(out_dir, lambda: False)
    sys.modules[mount.MOUNTS["studio"]["alias"]] = serve   # init した serve をそのまま取り込ませる(e2e_ui.py の --mounted と同じ)
    sup = L.Supervisor(REPO, only=["studio"], mounts=("studio",), log=lambda m: None, ports=dict(zip(["studio"], free_ports(1))))
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sup.start("studio")
    if not sup.by_id["studio"].snapshot()["mounted"]:
        print("FAIL 入口にスタジオを取り込めませんでした: %s" % sup.by_id["studio"].snapshot())
        return 1
    serve.Handler.log_message = lambda self, fmt, *a: None
    base = "http://127.0.0.1:%d" % port
    studio_url = base + "/studio/"

    def api(method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        h = {"Origin": base, "X-YTT-Token": srv.token}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8") or "null")
            except ValueError:
                return e.code, None

    # --- 録画の部品(本物。direct)と、配信中のふりをする HLS(2本。2本目は画質の確認用) ---
    src_dir = os.path.join(tmp, "src")
    segs = F.make_source(src_dir, 420)
    live_src = F.LiveServer(src_dir, segs, start=4, rate=1.0)
    live_src.end = False
    live_src2 = F.LiveServer(src_dir, segs, start=4, rate=1.0)
    live_src2.end = False
    rport = free_ports(1)[0]
    rdata, rfolder = os.path.join(tmp, "recdata"), os.path.join(tmp, "live-rec")
    rproc = subprocess.Popen([sys.executable, os.path.join(REPO, "recorder", "recorder.py"), "--port", str(rport), "--data-dir", rdata,
                              "--folder", rfolder, "--source", "direct", "--hls-time", "1", "--backoff", "1,2", "--stall-sec", "4", "--quiet"],
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    tok = os.path.join(rdata, "token.txt")
    end = time.time() + 20
    while time.time() < end and not os.path.isfile(tok):
        time.sleep(0.2)
    time.sleep(0.2)
    with open(tok, encoding="ascii") as f:
        rtoken = f.read().strip()
    srv.prefs.patch("live", {"recorders": [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % rport, "token": rtoken}]})
    live = srv.live
    live.spawn_ok = False                     # 見回りが本物の録画の部品(8730)を起こさない
    live.store_dir = os.path.join(tmp, "live")
    live.out_dir = lambda: out_dir            # スタジオの書き出し先と同じ(/api/live/exported は書き出し先の中の mp4 だけ受ける)
    live.audio = lambda: {"volume": 100, "loudness": None}
    handed = []

    class FakeRunner:   # 文字起こしへは偽のまとめて実行
        def start_file(self, path, title="", flow="check", **kw):
            handed.append((path, flow))
            return {"id": "run-%d" % len(handed)}

        def snapshot(self):
            return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち"} for i in range(len(handed))]}
    fake_runner = FakeRunner()
    live.runner = lambda: fake_runner
    probes = []
    live.probe = lambda url: probes.append(url) or {"status": "is_live", "title": TITLE, "message": ""}
    # 入口 → 録画元の要求だけ、YouTube の形の URL を手元の HLS に読み替える(返ってきた値は YouTube の形に戻す)
    url_map = {YT1: live_src.url, YT2: live_src2.url}
    back = {v: k for k, v in url_map.items()}
    starts = []
    orig_call = live.call

    def swap(o):
        if isinstance(o, str):
            return back.get(o, o)
        if isinstance(o, list):
            return [swap(x) for x in o]
        if isinstance(o, dict):
            return {k: swap(v) for k, v in o.items()}
        return o

    def call(rc, method, path, body=None, timeout=3.0):
        if path == "/live/start" and isinstance(body, dict):
            starts.append(dict(body))
            body = dict(body, url=url_map.get(body.get("url"), body.get("url")))
        code, d = orig_call(rc, method, path, body, timeout)
        return code, swap(d)
    live.call = call

    rid = rid2 = None
    errors, not_found = [], []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, edge = None, False
            if not force_chromium:
                try:
                    browser, edge = p.chromium.launch(channel="msedge"), True
                except Exception as e:
                    print("(Edge を起動できませんでした: %s。Playwright の chromium で続けます)" % str(e).splitlines()[0])
            if browser is None:
                browser = p.chromium.launch()
            print("ブラウザ: %s" % ("Edge(H.264 を再生できる)" if edge else "Playwright の chromium(再生が要る確認は飛ばす)"), flush=True)
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
                ctx.add_init_script(INIT_JS)

                def watch(pg, name):
                    pg.on("console", lambda m: errors.append("%s: %s (%s)" % (name, m.text, (m.location or {}).get("url", ""))) if m.type == "error" else None)
                    pg.on("pageerror", lambda e: errors.append("%s: %s" % (name, e)))
                    pg.on("response", lambda r: not_found.append("%s: %s" % (name, r.url)) if r.status == 404 else None)

                # ---------------- 13. オフのとき ----------------
                pg = ctx.new_page()
                watch(pg, "off")
                queued = []

                def fake_queue(route):
                    queued.append(route.request.post_data_json)
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"added": [], "rejected": []}))
                pg.route("**/studio/api/queue/add", fake_queue)
                begins = []
                pg.on("request", lambda r: begins.append(r.url) if "/live/api/begin" in r.url else None)
                pg.goto(studio_url)
                wait_js(pg, "() => !!(window.Studio && Studio.ready)", 20000)
                pg.click('#steps [data-step="queue"]')
                pg.fill("#qUrls", YT1)
                pg.click("#qAdd")
                check(wait_for(lambda: queued, 10), "13 オフ: URL を入れて「解析に追加」→ 今までどおり /api/queue/add: %s" % queued[:1])
                check(not begins and not probes, "13 オフ: begin に進まない(配信の状態も調べない)")
                pg.wait_for_timeout(500)
                check(pg.evaluate("() => { const b = document.querySelector('[data-ui-live]'); return !b || b.hidden; }"), "13 オフ: ヘッダーに録画の札が出ない")
                pg.close()
                # オフのときの 404(入口の ../live/api/info は機能がオフなら 404 = 画面が「使えない」と知る手段)は想定内
                not_found[:] = [x for x in not_found if not x.startswith("off: ") or not x.endswith("/live/api/info")]
                errors[:] = [x for x in errors if not (x.startswith("off: ") and "404" in x)]

                # ---------------- 1. ホームでオンにする ----------------
                pg = ctx.new_page()
                watch(pg, "home")
                pg.goto(base + "/")
                pg.evaluate("document.getElementById('advancedBox').open = true")
                wait_js(pg, "!!document.getElementById('labBox') && !document.getElementById('labBox').hidden")
                pg.click("#liveEnabled")
                check(wait_js(pg, "document.getElementById('liveMsg').hidden === false") and srv.prefs.get(["live"])["live"]["enabled"] is True,
                      "1 ホームの「試験中の機能」でオンにする")
                pg.close()

                # ---------------- 2. ② の URL 欄から録画を始める ----------------
                pg = ctx.new_page()
                watch(pg, "studio")
                pg.goto(studio_url)
                wait_js(pg, "() => !!(window.Studio && Studio.ready)", 20000)
                wait_js(pg, "() => !document.querySelector('#rvOpenForm .rv-openlive').hidden", 8000)
                pg.click('#steps [data-step="queue"]')
                pg.fill("#qUrls", YT1)
                pg.click("#qAdd")
                check(wait_js(pg, "() => Studio.step === 'review' && !document.querySelector('#rvLiveRec').hidden", 30000),
                      "2 録画が始まり、自動で ③ 確認・書き出しへ移って LIVE の帯(録画の行)が出る")
                code, vs = api("GET", "/studio/api/videos")
                lv = [v for v in (vs or {}).get("videos") or [] if v.get("kind") == "live"]
                rid = lv[0]["id"] if lv else None
                check(len(lv) == 1 and LX.REC_RE.match(rid or "") and lv[0]["live"]["url"] == YT1 and lv[0]["live"]["recorder"] == "local"
                      and lv[0]["live"]["videoId"] == "TESTlive001", "2 スタジオの一覧に kind live の配信(id = 録画の id): %s" % (lv[:1],))
                check(lv and lv[0]["title"] == TITLE, "2 題は yt-dlp の題(HTML にしない): %s" % (lv[0]["title"] if lv else None))
                check(pg.evaluate("() => document.querySelector('#rvTitle').value") == TITLE and pg.evaluate("() => !document.querySelector('#rvTitle b')"),
                      "2 ③ の題の欄に配信の題")
                check(starts and starts[0]["quality"] == "1080p" and starts[0]["title"] == TITLE, "2 録画元へ既定の画質 1080p と題で頼む: %s" % starts[:1])

                # ---------------- 3. 自動で再生・録画中・札 ----------------
                check(wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent)", 20000),
                      "3 録画の状態が「録画中」: %s" % pg.text_content("#rvRecState"))
                check(pg.is_visible("#rvLiveBar") and pg.text_content("#rvLiveBadge") == "LIVE", "3 LIVE の帯が出る")
                if edge:
                    check(wait_js(pg, "() => { const v = %s; return v && !v.paused && v.currentTime > 0.5; }" % VIDEO, 25000), "3 数秒で再生が自動で始まる(Edge)")
                    t1 = pg.evaluate("() => %s.currentTime" % VIDEO)
                    pg.wait_for_timeout(1500)
                    t2 = pg.evaluate("() => %s.currentTime" % VIDEO)
                    check(t2 > t1 + 0.8, "3 再生位置が進む: %.2f → %.2f" % (t1, t2))
                    check(pg.evaluate("() => !!window.__hls && !!window.__hls.playingDate"), "3 hls.js で再生している(playingDate がある)")
                else:
                    check(wait_js(pg, "() => !!%s" % VIDEO, 20000), "3 録画のプレーヤーができる(chromium: H.264 は再生できないので読み込みまで)")
                    skip("3 自動再生(chromium は H.264 を再生できない)")
                check(wait_js(pg, "() => { const b = document.querySelector('[data-ui-live]'); return b && !b.hidden && /録画中 1/.test(b.textContent); }", 15000),
                      "3 ヘッダーに「録画中 1」の札")
                guide = pg.text_content("#rvLiveGuide") or ""
                check("マーク" in guide and pg.is_visible("#rvLiveGuide"), "3 次にすることの案内: %s" % guide)

                # 8. 見回りで作り直されないか(ここで要素を掴んでおく)
                pg.evaluate("""() => { window.__keep = ['#rvLiveBar', '#rvRecState', '#rvAutoExp', '#rvRecStop', '#rvLiveGuide', '#rvEdge', '#rvTitle',
                  '[data-ui-live] .ui-live-btn'].map(s => [s, document.querySelector(s)]); }""")
                keep_at = time.time()

                # ---------------- 4・5. I → O → 追加 → すぐ書き出す ----------------
                check(pg.is_checked("#rvAutoExp"), "4 「マークしたらすぐ書き出す」は既定オン")
                if edge:
                    wait_js(pg, "() => %s.currentTime > 3" % VIDEO, 15000)
                at_in = pg.evaluate("() => { const pd = window.__hls && window.__hls.playingDate; document.querySelector('#rvIn').click(); return pd ? pd.getTime() : null; }")
                pg.wait_for_timeout(3200)
                at_out = pg.evaluate("() => { const pd = window.__hls && window.__hls.playingDate; document.querySelector('#rvOut').click(); return pd ? pd.getTime() : null; }")
                pg.evaluate("() => document.querySelector('#rvAdd').click()")
                check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length === 1", 5000), "4 マークが1つ付く")
                seen = []
                deadline = time.time() + 120
                while time.time() < deadline:
                    t = pg.evaluate("() => [...document.querySelectorAll('#rvExpList .rv-ejob .pill')].map(x => x.textContent.trim()).join('|')")
                    if t and (not seen or seen[-1] != t):
                        seen.append(t)
                    if "済み" in t or "失敗" in t:
                        break
                    time.sleep(0.15)
                check(seen and "済み" in seen[-1], "4 書き出しの欄の状態: %s" % " → ".join(seen))
                check(any(s.startswith(("録画待ち", "取得中", "作り直し中")) for s in seen), "4 途中の状態(録画待ち・取得中・作り直し中)が欄に出る")
                code, jj = api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)
                jobs = (jj or {}).get("jobs") or []
                job = next((j for j in jobs if j.get("studio")), None)
                check(code == 200 and len(jobs) == 1 and job and job["state"] == "done", "4 入口の書き出しのジョブ(この録画で絞った一覧): %s" % [(j.get("id"), j.get("state")) for j in jobs])
                code, other = api("GET", "/live/api/exports?recorder=local&recording=20991231-000000")
                check(code == 200 and other.get("jobs") == [], "4 別の録画で絞ると空")
                code, vv = api("GET", "/studio/api/video?id=%s" % rid)
                mk = ((vv or {}).get("video") or {}).get("marks") or []
                if job and job["state"] == "done":
                    info = normalize.probe(job["path"])
                    want = mk[0]["end"] - mk[0]["start"] if mk else 0
                    check(normalize.is_30fps(info), "4 書き出した mp4 は 30fps: %s" % (info or {}).get("r_frame_rate"))
                    check(abs((info or {}).get("duration", 0) - want) <= 0.15, "4 長さが区間と合う: %.2f 秒(区間 %.2f 秒)" % ((info or {}).get("duration", 0), want))
                    clip, warn = schemas.load_clip_file(schemas.find_clip_path(job["path"]))
                    check(clip and clip["source"]["kind"] == "live" and clip["source"]["live"]["studio"]["video"] == rid and clip["source"]["live"]["url"] == YT1,
                          "4 .clip.json の source.kind は live(スタジオの配信・配信の URL): %s" % ((clip or {}).get("source"), ))
                    check(clip and clip["source"].get("title") == TITLE, "4 .clip.json の題は配信の題: %s(%s)" % ((clip or {}).get("source", {}).get("title"), job["path"]))
                    check(handed and handed[0] == (job["path"], "check"), "4 文字起こしへ渡した(偽のまとめて実行)")
                    ok_exp = wait_for(lambda: (lambda m: m and m[0]["status"] == "exported" and os.path.normcase(m[0].get("path") or "") == os.path.normcase(job["path"]))(
                        ((api("GET", "/studio/api/video?id=%s" % rid)[1] or {}).get("video") or {}).get("marks")), 15)
                    check(ok_exp, "4 スタジオのマークが「書き出し済み」(path は書き出した mp4)")
                    check(wait_js(pg, "() => !!document.querySelector('#rvList .rv-mark-row .rv-chip.exported')", 8000), "4 ③ のマークの行に「書き出し済み」")
                    # 5. マークの位置(書き出しの絶対時刻とマークした時点の hls.playingDate)
                    if edge and at_in and at_out:
                        d_in = LX.iso_epoch(job["start"]) - at_in / 1000
                        d_out = LX.iso_epoch(job["end"]) - at_out / 1000
                        check(abs(d_in) <= 0.3 and abs(d_out) <= 0.3, "5 書き出した区間の絶対時刻 = マークした時点の playingDate ± 0.3 秒(開始 %+.3f 秒・終了 %+.3f 秒)" % (d_in, d_out))
                    else:
                        skip("5 マークの位置(再生できないので playingDate が無い)")
                if shots:
                    pg.evaluate("window.scrollTo(0, 0)")
                    pg.screenshot(path=os.path.join(shots, "live_01_recording_marked_exported.png"))
                    pg.click('#rvJump [data-jump="export"]')
                    pg.wait_for_timeout(400)
                    pg.screenshot(path=os.path.join(shots, "live_02_export_drawer.png"))
                    pg.click("#rvExpClose")
                    pg.wait_for_timeout(300)

                # ---------------- 6. シーク ----------------
                if edge:
                    before = pg.evaluate("() => %s.currentTime" % VIDEO)
                    box = pg.locator("#rvTl").bounding_box()
                    pg.mouse.click(box["x"] + 3, box["y"] + box["height"] / 2)
                    check(wait_js(pg, "() => %s.currentTime < 3" % VIDEO, 5000), "6 タイムラインの頭を押すと頭へ戻る: %.1f → %.1f" % (before, pg.evaluate("() => %s.currentTime" % VIDEO)))
                    pg.click("#rvEdge")
                    check(wait_js(pg, "() => %s.currentTime > %f" % (VIDEO, before - 4), 5000), "6 「ライブ端へ」で端へ戻る: %.1f" % pg.evaluate("() => %s.currentTime" % VIDEO))
                else:
                    skip("6 シーク(再生できない)")

                # ---------------- 7. ③ を離れると止まる ----------------
                if edge:
                    wait_js(pg, "() => !%s.paused" % VIDEO, 5000)
                    pg.click('#steps [data-step="queue"]')
                    check(wait_js(pg, "() => %s.paused" % VIDEO, 3000), "7 ② へ移ると再生が止まる")
                    pos = pg.evaluate("() => %s.currentTime" % VIDEO)
                    pg.wait_for_timeout(1200)
                    pg.click('#steps [data-step="review"]')
                    check(wait_js(pg, "() => !!%s && Math.abs(%s.currentTime - %f) < 0.5" % (VIDEO, VIDEO, pos)) and not pg.is_hidden("#rvLiveRec"),
                          "7 戻ると同じ録画が開いていて、止めた位置から")
                    pg.evaluate("() => document.activeElement && document.activeElement.blur()")
                    pg.keyboard.press("Space")   # 再生・停止(共通の再生キー)
                    check(wait_js(pg, "() => !%s.paused" % VIDEO, 3000), "7 戻ってから再生を続けられる")
                else:
                    skip("7 離れると止まる(再生できない)")

                # ---------------- 8. 作り直されない ----------------
                rest = 10 - (time.time() - keep_at)
                if rest > 0:
                    pg.wait_for_timeout(int(rest * 1000))
                pg.evaluate("() => { window.__keepRow = document.querySelector('#rvExpList .rv-ejob'); }")
                pg.wait_for_timeout(4000)
                gone = pg.evaluate("() => window.__keep.filter(([s, el]) => !el || !el.isConnected).map(([s]) => s).concat(window.__keepRow && window.__keepRow.isConnected ? [] : ['#rvExpList .rv-ejob'])")
                check(not gone, "8 見回り(10 秒余り)で帯・札・書き出しの行が作り直されない: %s" % gone)

                # ---------------- 欠け(繋ぎ直し)をまたぐ: 状態の表示・欠けの中への seek・欠けのあとのマークの位置 ----------------
                live_src.down = True
                check(wait_js(pg, "() => /つなぎ直し中/.test(document.querySelector('#rvRecState').textContent)", 30000),
                      "欠け: 配信が切れると「つなぎ直し中」: %s" % pg.text_content("#rvRecState"))
                pg.wait_for_timeout(3000)
                live_src.down = False
                check(wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent) && /つなぎ直し 1 回/.test(document.querySelector('#rvRecMsg').textContent)", 45000),
                      "欠け: 戻ると「録画中」と「つなぎ直し 1 回」: %s %s" % (pg.text_content("#rvRecState"), pg.text_content("#rvRecMsg")))
                n_jobs = 1
                if edge:
                    GAP_JS = """() => { const h = window.__hls; const lv = h && h.levels && h.levels[Math.max(0, h.currentLevel)]; const fr = lv && lv.details ? lv.details.fragments : [];
                      if (fr.length < 2) return null; const base = fr[0].programDateTime;
                      for (let i = 0; i + 1 < fr.length; i++){ const e = fr[i].programDateTime + fr[i].duration * 1000, n = fr[i + 1].programDateTime;
                        if (n - e > 1500) return { from: (e - base) / 1000, to: (n - base) / 1000, media: fr[i + 1].start, last: (fr[fr.length - 1].programDateTime - base) / 1000 }; }
                      return null; }"""
                    gap = None
                    end = time.time() + 30
                    while time.time() < end:
                        gap = pg.evaluate(GAP_JS)
                        if gap and gap["last"] > gap["to"] + 4:
                            break
                        time.sleep(0.5)
                    check(gap, "欠け: 再生リストの受信時刻に欠けがある: %s" % gap)
                    if gap:
                        mid = (gap["from"] + gap["to"]) / 2
                        pg.evaluate("() => %s.pause()" % VIDEO)   # 止めてから移す(再生を続けると位置が進んで比べられない)
                        pg.wait_for_timeout(300)
                        pg.fill("#rvNow", "%d:%04.1f" % (int(mid // 60), mid % 60))
                        pg.press("#rvNow", "Enter")
                        pg.wait_for_timeout(800)
                        ct = pg.evaluate("() => %s.currentTime" % VIDEO)
                        now = pg.input_value("#rvNow")
                        mm, ss = now.split(":")[-2:]
                        now_s = int(mm) * 60 + float(ss)
                        check(abs(ct - gap["media"]) < 0.6 and now_s >= gap["to"] - 0.3,
                              "欠け: 欠けの中(%.1f 秒)へ移ると、欠けのあとの頭(%.1f 秒・メディア %.2f)から: currentTime %.2f・時刻の欄 %s"
                              % (mid, gap["to"], gap["media"], ct, now))
                        dur_shown = pg.text_content("#rvDur") or ""
                        check(abs(float(dur_shown.split(":")[-1]) + 60 * int(dur_shown.replace("/", "").strip().split(":")[-2]) - gap["last"]) < 4,
                              "欠け: 録画の長さは欠けの間も進む(受信時刻の幅): 表示 %s・最後のセグメント %.1f 秒" % (dur_shown, gap["last"]))
                        # 欠けのあとでマーク(ライブ端の近く)→ 書き出しの絶対時刻 = playingDate
                        pg.click("#rvEdge")
                        pg.wait_for_timeout(2500)
                        a_in = pg.evaluate("() => { const pd = window.__hls.playingDate; document.querySelector('#rvIn').click(); return pd ? pd.getTime() : null; }")
                        pg.wait_for_timeout(2500)
                        a_out = pg.evaluate("() => { const pd = window.__hls.playingDate; document.querySelector('#rvOut').click(); document.querySelector('#rvAdd').click(); return pd ? pd.getTime() : null; }")
                        n_jobs = 2
                        jobs = wait_for(lambda: (lambda js: len(js) == 2 and all(j["state"] in ("done", "error") for j in js) and js)(
                            (api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1] or {}).get("jobs") or []), 90, 0.5)
                        jg = jobs and max(jobs, key=lambda j: j["studio"]["start"])
                        check(jg and jg["state"] == "done", "欠け: 欠けのあとのマークも書き出せる: %s %s" % ((jg or {}).get("state"), (jg or {}).get("error")))
                        if jg and jg["state"] == "done" and a_in and a_out:
                            d_in, d_out = LX.iso_epoch(jg["start"]) - a_in / 1000, LX.iso_epoch(jg["end"]) - a_out / 1000
                            check(abs(d_in) <= 0.3 and abs(d_out) <= 0.3, "5 欠けのあとでも、書き出した区間の絶対時刻 = playingDate ± 0.3 秒(開始 %+.3f 秒・終了 %+.3f 秒)" % (d_in, d_out))
                            info = normalize.probe(jg["path"])
                            check(normalize.is_30fps(info) and abs(info.get("duration", 0) - (jg["studio"]["end"] - jg["studio"]["start"])) <= 0.15,
                                  "欠け: 欠けのあとの書き出しも 30fps・長さが区間と合う: %.2f 秒" % info.get("duration", 0))
                else:
                    skip("欠けをまたぐ seek・欠けのあとのマークの位置(再生できない)")

                # ---------------- 11. 設定の引き出し ----------------
                pg.click("#btnSettings")
                check(wait_js(pg, "() => { const s = document.querySelector('#setLive'); return s && !s.hidden && s.offsetParent; }", 8000), "11 設定の引き出しに「ライブの録画」")
                check(wait_js(pg, "() => /空き/.test(document.querySelector('#liveFree').textContent) && document.querySelector('#liveFolderNow').textContent.toLowerCase() === %s"
                              % json.dumps(rfolder.lower()), 8000),
                      "11 置き場所と空き: %s / %s" % (pg.text_content("#liveFolderNow"), pg.text_content("#liveFree")))
                check(wait_js(pg, "() => document.querySelector('#liveFolderSave').disabled", 5000), "11 録画中は置き場所を変えられない")
                check(pg.input_value("#liveQuality") == "1080p", "11 画質の既定は 1080p")
                pg.select_option("#liveQuality", "720p")
                check(wait_for(lambda: srv.prefs.get(["live"])["live"]["quality"] == "720p", 5), "11 画質を変えると設定 live.quality に残る")
                if shots:
                    pg.screenshot(path=os.path.join(shots, "live_03_settings.png"))
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(300)

                # ---------------- 8b. ほかの窓(編集)で再生している間は、配信の音を下げる・消す(UIKit.sound。2026-10-05) ----------------
                other = ctx.new_page()
                other.goto(base + "/")
                other.evaluate("() => { window.__got = []; window.__ch = new BroadcastChannel('ytt-sound'); window.__ch.onmessage = e => window.__got.push(e.data); }")
                say = "(on) => window.__ch.postMessage({ id: 'e2e-editor', tool: 'transcribe', playing: on })"
                check(pg.evaluate("() => document.querySelector('#rvDuck').value") == "low" and pg.is_hidden("#rvDuckNote"), "8b 既定は「音を下げる」・鳴っていなければ案内なし")
                if edge:
                    pg.evaluate("() => { const v = %s; v.muted = false; v.play().catch(() => {}); }" % VIDEO)
                    vol0 = pg.evaluate("() => %s.volume" % VIDEO)
                    check(wait_js(other, "() => window.__got.some(d => d.tool === 'studio' && d.playing === true)", 8000), "8b スタジオの配信が鳴っている間、ほかの窓へ知らせる")
                    other.evaluate(say, True)
                    check(wait_js(pg, "() => Math.abs(%s.volume - %s * 0.2) < 0.02 && !%s.muted && !document.querySelector('#rvDuckNote').hidden" % (VIDEO, vol0, VIDEO), 5000),
                          "8b 編集で再生中: 配信の音を 2 割に下げて、案内を出す: %s" % pg.evaluate("() => %s.volume" % VIDEO))
                    pg.select_option("#rvDuck", "mute")
                    check(wait_js(pg, "() => %s.muted" % VIDEO, 3000) and "消しています" in (pg.text_content("#rvDuckNote") or ""), "8b 「音を消す」に切り替えると消音")
                    check(pg.evaluate("() => document.querySelector('#rvMute').checked") is False, "8b 設定の消音そのものは変えない")
                    other.evaluate(say, False)
                    check(wait_js(pg, "() => !%s.muted && Math.abs(%s.volume - %s) < 0.02 && document.querySelector('#rvDuckNote').hidden" % (VIDEO, VIDEO, vol0), 5000), "8b 編集の再生が止まると元の音に戻る")
                    other.evaluate(say, True)
                    check(wait_js(pg, "() => %s.muted" % VIDEO, 3000), "8b もう一度鳴ると消音")
                    check(wait_js(pg, "() => !%s.muted" % VIDEO, 12000), "8b 知らせが 6 秒来なければ(窓を閉じた)元に戻る")
                    pg.select_option("#rvDuck", "low")
                other.close()

                # ---------------- 9. 札 → 一覧 → 停止(二度押し) ----------------
                pg.click("[data-ui-live] .ui-live-btn")
                check(wait_js(pg, "() => !document.querySelector('.ui-live-panel').hidden", 3000), "9 札を押すと録画の一覧")
                row_title = pg.text_content(".ui-live-row .ui-live-title") or ""
                check(row_title == TITLE, "9 一覧の題(文字のまま): %s" % row_title)
                if shots:
                    pg.screenshot(path=os.path.join(shots, "live_04_badge_panel.png"))
                stop = pg.locator(".ui-live-row .btn.danger")
                stop.click()
                pg.wait_for_timeout(300)
                check(pg.evaluate("() => /録画中/.test(document.querySelector('#rvRecState').textContent)"), "9 停止は一度押しただけでは止まらない")
                stop.click()
                check(wait_js(pg, "() => /停止|終了/.test(document.querySelector('#rvRecState').textContent)", 45000), "9 二度押しで録画が止まる: %s" % pg.text_content("#rvRecState"))
                check(wait_js(pg, "() => /録画は終わりました/.test(document.querySelector('#rvLiveGuide').textContent)", 10000),
                      "9 帯が「録画は終わりました…」に変わる: %s" % pg.text_content("#rvLiveGuide"))
                check(pg.evaluate("() => document.querySelector('#rvLiveBar').classList.contains('is-ended') && document.querySelector('#rvLiveBadge').textContent === '録画'")
                      and pg.is_hidden("#rvRecStop") and pg.is_hidden("#rvEdge"), "9 帯は終わった見た目(LIVE → 録画・停止とライブ端へは消える)")
                check(wait_js(pg, "() => /録画終了/.test(document.querySelector('[data-ui-live]').textContent)", 15000),
                      "9 札が「録画終了」になる: %s" % pg.text_content("[data-ui-live] .ui-live-btn"))
                # 2026-10-05 の直し 4 点: 止めたら札の一覧は閉じる・「停止」の札に「停止しました」を重ねない・録画ではマークの「ライブ」の印と件数を出さない・標準のコントロールを出さない
                check(pg.evaluate("() => document.querySelector('.ui-live-panel').hidden"), "9 止めたら札の一覧は閉じる")
                check("停止しました" not in (pg.text_content("#rvRecMsg") or ""), "9 「停止」の札の横に「停止しました」を重ねない: %s" % pg.text_content("#rvRecMsg"))
                check(pg.evaluate("() => !document.querySelector('#rvMarkList .rv-chip.live, .rv-mark-row .rv-chip.live') && document.querySelector('#rvLiveMarks').hidden"),
                      "9 録画ではマークの「ライブ」の印と件数を出さない")
                check(pg.evaluate("() => { const v = document.querySelector('#rvHost video'); return !!v && v.controls === false; }"), "9 録画のプレイヤーは標準のコントロールを出さない")
                code, pl = 0, b""
                try:
                    with urllib.request.urlopen(base + "/live/r/local/%s/index.m3u8" % rid, timeout=10) as r:
                        pl = r.read()
                except urllib.error.URLError:
                    pass
                check(b"#EXT-X-ENDLIST" in pl, "9 再生リストに終わりの印")
                if edge:
                    check(wait_js(pg, "() => isFinite(%s.duration) && %s.duration > 10" % (VIDEO, VIDEO), 20000),
                          "9 終わった録画の duration が有限: %s" % pg.evaluate("() => %s.duration" % VIDEO))
                    pg.evaluate("() => { const v = %s; v.currentTime = Math.max(0, v.duration - 2); v.play(); }" % VIDEO)
                    check(wait_js(pg, "() => %s.ended || %s.currentTime >= %s.duration - 0.3" % (VIDEO, VIDEO, VIDEO), 10000), "9 最後まで再生できる")
                else:
                    skip("9 最後まで再生(再生できない)")
                if shots:
                    pg.evaluate("window.scrollTo(0, 0)")
                    pg.screenshot(path=os.path.join(shots, "live_05_ended.png"))

                # ---------------- 10. 終わった録画でマークして「書き出す」 ----------------
                pg.click("#rvAutoExp")   # 「マークしたらすぐ書き出す」を外す(いつものスタジオと同じ: 採用 → 書き出す)
                check(not pg.is_checked("#rvAutoExp"), "10 「マークしたらすぐ書き出す」を外せる")
                if edge:
                    pg.evaluate("() => { const v = %s; v.pause(); v.currentTime = 5; }" % VIDEO)
                else:
                    pg.fill("#rvNow", "0:05.0"); pg.keyboard.press("Enter")
                pg.wait_for_timeout(500)
                pg.evaluate("() => document.querySelector('#rvIn').click()")
                if edge:
                    pg.evaluate("() => { %s.currentTime = 8; }" % VIDEO)
                else:
                    pg.fill("#rvNow", "0:08.0"); pg.keyboard.press("Enter")
                pg.wait_for_timeout(500)
                pg.evaluate("() => { document.querySelector('#rvOut').click(); document.querySelector('#rvAdd').click(); }")
                check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length === %d" % (n_jobs + 1), 5000), "10 終わった録画にマークを足せる")
                check(wait_js(pg, "() => !!document.querySelector('#rvList .rv-mark-row.st-cand')", 3000), "10 スイッチを外すとマークは候補のまま(すぐ書き出さない)")
                pg.click('#rvList .rv-mark-row.st-cand [data-act="st"][data-st="adopted"]')
                pg.click('#rvJump [data-jump="export"]')
                pg.wait_for_timeout(400)
                check(wait_js(pg, "() => !document.querySelector('#rvExpRun').disabled && /1件を書き出す/.test(document.querySelector('#rvExpRun').textContent)", 5000),
                      "10 「1件を書き出す」が押せる: %s" % pg.text_content("#rvExpRun"))
                pg.click("#rvExpRun")
                done2 = wait_for(lambda: (lambda js: len(js) == n_jobs + 1 and all(j["state"] == "done" for j in js) and js)(
                    (api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1] or {}).get("jobs") or []), 90, 0.5)
                check(done2, "10 終わった録画でも「書き出す」で書き出せる")
                check(wait_for(lambda: [m["status"] for m in ((api("GET", "/studio/api/video?id=%s" % rid)[1] or {}).get("video") or {}).get("marks") or []] == ["exported"] * (n_jobs + 1), 15),
                      "10 2つ目のマークも「書き出し済み」")
                if done2:
                    j2 = next(j for j in done2 if abs(j["studio"]["start"] - 5) < 1)
                    info = normalize.probe(j2["path"])
                    check(normalize.is_30fps(info) and abs(info.get("duration", 0) - (j2["studio"]["end"] - j2["studio"]["start"])) <= 0.15,
                          "10 2本目も 30fps・長さが区間と合う: %.2f 秒" % (info or {}).get("duration", 0))
                pg.click("#rvExpClose")

                # ---------------- 12. 読み込み直す ----------------
                pg.goto(studio_url + "?video=" + rid)
                check(wait_js(pg, "() => Studio.step === 'review' && !document.querySelector('#rvLiveRec').hidden && document.querySelectorAll('#rvList .rv-mark-row').length === %d" % (n_jobs + 1), 15000),
                      "12 ?video=<id> で開き直すと、その録画が開いてマークが残っている")
                check(wait_js(pg, "() => /停止|終了/.test(document.querySelector('#rvRecState').textContent)", 10000), "12 開き直しても録画の状態は「停止」")
                check(pg.evaluate("() => document.querySelectorAll('#rvList .rv-chip.exported').length") == n_jobs + 1, "12 マークは全部「書き出し済み」")

                # ---------------- 11 の続き: 次の begin はその画質で ----------------
                code, d = api("POST", "/live/api/begin", {"url": YT2})
                rid2 = ((d or {}).get("recording") or {}).get("id")
                check(code == 200 and d.get("live") is True and starts[-1]["quality"] == "720p" and starts[-1]["url"] == YT2,
                      "11 次の begin は設定の画質 720p で録画元へ頼む: %s" % (starts[-1] if starts else None))
                if rid2:
                    code, d = api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid2})
                    check(code == 200 and d.get("ok"), "11 2本目を止める")

                # ---------------- 14. 狭い画面・エラー ----------------
                pg.set_viewport_size({"width": 375, "height": 812})
                pg.wait_for_timeout(400)
                check(pg.evaluate(NO_HSCROLL_JS), "14 375px の ③(録画を開いている)で横にはみ出さない")
                wait_js(pg, "() => { const b = document.querySelector('[data-ui-live]'); return b && !b.hidden; }", 15000)
                if pg.evaluate("() => { const b = document.querySelector('[data-ui-live]'); return !!b && !b.hidden; }"):
                    pg.click("[data-ui-live] .ui-live-btn")
                    pg.wait_for_timeout(300)
                    check(pg.evaluate(NO_HSCROLL_JS) and pg.evaluate("() => { const r = document.querySelector('.ui-live-panel').getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 1; }"),
                          "14 375px で札の一覧が画面に収まる")
                    if shots:
                        pg.screenshot(path=os.path.join(shots, "live_06_narrow_badge.png"))
                    pg.keyboard.press("Escape")
                if shots:
                    pg.evaluate("window.scrollTo(0, 0)")
                    pg.screenshot(path=os.path.join(shots, "live_07_narrow.png"), full_page=True)
                # 想定内: ホームの画面は「編集」の /transcribe/api/transcripts を読むが、このテストはスタジオだけを取り込む(編集は無い)ので 404
                # 想定内: Edge は /favicon.ico を自分で読みに行く(どのツールの画面にもアイコンは無い。画面のコードの要求ではない)
                not_found[:] = [x for x in not_found if not (x.startswith("home: ") and "/transcribe/" in x) and not x.endswith("/favicon.ico")]
                errors[:] = [x for x in errors if not ("404" in x and ((x.startswith("home: ") and "/transcribe/" in x) or "/favicon.ico" in x))]
                csp = pg.evaluate("() => window.__csp")
                check(not csp, "14 CSP の違反なし: %s" % csp)
                check(not errors, "14 コンソールのエラーなし: %s" % errors[:6])
                check(not not_found, "14 404 なし: %s" % not_found[:6])
            finally:
                browser.close()
    finally:
        for r in (rid, rid2):
            if not r:
                continue
            try:
                req = urllib.request.Request("http://127.0.0.1:%d/live/%s/stop" % (rport, r), data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + rtoken})
                urllib.request.urlopen(req, timeout=40)
            except Exception:
                pass
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/live/quit" % rport, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + rtoken})
            urllib.request.urlopen(req, timeout=5)
            rproc.wait(20)
        except Exception:
            rproc.kill()
        live_src.close()
        live_src2.close()
        live.close()
        srv.shutdown()
        sup.unmount_all()
        srv.server_close()
    print("結果: %d 件中 %d 件 OK" % (len(results), sum(results)))
    print("ALL OK" if ok else "SOME FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
