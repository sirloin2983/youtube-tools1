#!/usr/bin/env python3
"""リアルタイム切り抜き(線 D の P3。plan/line-d-live-clipping.md の 0-8)の通しの確認: 入口にスタジオを取り込み、録画の部品を別のプロセスで立て、
ブラウザでスタジオの画面を操作する。本物の YouTube には繋がない。

    py -3.10 src/home/tests/e2e_live_studio.py                 # 確かめる(終了コード 0 = すべて OK)
    py -3.10 src/home/tests/e2e_live_studio.py --shots DIR     # あわせて ③ などのスクリーンショットを DIR に残す
    py -3.10 src/home/tests/e2e_live_studio.py --chromium      # Edge があっても Playwright の chromium で(再生が要る確認は飛ばす)

作り(e2e_live.py と同じ部品):
  - 入口(launch.py)に studio を取り込む(src/studio/tests/e2e_ui.py の --mounted と同じ形。STUDIO_FAKE=1)。作業データ・書き出し先・録画の置き場所は全部一時フォルダ
    (YTT_DATA_DIR はこのテストの間だけ一時フォルダにする。先頭の setdefault は ytt_core のテストの決まり)
  - 録画の部品(src/recorder/recorder.py)は本物を --source direct で。ffmpeg の lavfi で作った H.264 の HLS を手元の HTTP サーバーで配信中のように出して録る
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
  15 書き出したあと(帯の select。設定 liveAfter)と配信者(字幕の色): begin のチャンネル名がスタジオの配信に入る・帯の「配信者」がチャンネル名から自動で入る・
     「全自動」にしてマーク → 入口がまとめて実行へ flow auto と配信者の名前を渡す・帯で名前を直すと次の書き出しに渡り、録画とチャンネルに覚える・
     見回りで select・欄が作り直されない(値も戻らない)・開き直しても選んだ値と直した名前
  L3(線 D。スタジオ 0.23.0)配信中の候補: LIVE の帯の一覧・見出し・タイムラインの印・グラフ・[再生]・[採用](本物の adopt)・[見送り]・控えも見る・[戻す]・p / z・
     見回りで作り直さない・マウスが乗っている行は入れ替えで外れても消さない・375px(本物の候補の API + 偽のワーカー tests/fake_excite_worker.py。_scene_peaks)
  D-11 案 b(入口 0.48.0・スタジオ 0.23.2)配信中の候補の文字起こし: 入口が候補に付けた文字が見回りで行に出る(80 字で切る・title に全文)・whisper.cpp の無い入口では
     見出しに「文字起こしなし(理由)」・⚙ の #liveTx で live.liveTx.enabled が変わる(_scene_peak_text・_scene_live_tx_switch)
  M1(線 D。入口 0.39.0)サーバー側の「マーク + 書き出し」POST /live/api/adopt: スタジオの画面を閉じたまま → 書き出しまで通る・スタジオの一覧にマークが出て
     「書き出し済み」(入口が自分で付ける)・.clip.json と live_feedback.jsonl に origin・同じ区間は二重に作らない・
     ホームの設定 live.auto(M2: cut・engine・model)がまとめて実行へ渡る・ホームの「試験中の機能」に設定の欄・「調子」に失敗の行(M3)
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
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
CHANNEL = "Pekora Ch. 兎田ぺこら"   # 偽の yt-dlp が返すチャンネル名(配信者の名前 = 字幕の色をここから決める)

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
    handed, handed_who, handed_kw = [], [], []

    class FakeRunner:   # 文字起こしへは偽のまとめて実行(渡った flow と配信者の名前を覚える。全自動の分は「パックの段を実行中」と答える)
        def start_file(self, path, title="", flow="check", streamer=None, **kw):
            handed.append((path, flow))
            handed_who.append(streamer)
            handed_kw.append(kw)   # 書き出したあとの設定(live.auto の cut・engine・model。M2)
            return {"id": "run-%d" % len(handed)}

        def snapshot(self):
            def steps(flow):
                if flow != "auto":
                    return [{"key": "transcribe", "label": "文字起こし", "state": "wait", "stateLabel": "待ち"}]
                return [{"key": "transcribe", "label": "文字起こし", "state": "done", "stateLabel": "済み"},
                        {"key": "pack", "label": "パック", "state": "run", "stateLabel": "実行中"},
                        {"key": "deliver", "label": "Dropbox へ届ける", "state": "wait", "stateLabel": "待ち"}]
            return {"runs": [{"id": "run-%d" % (i + 1), "state": "running" if h[1] == "auto" else "queued", "stateLabel": "実行中" if h[1] == "auto" else "待ち",
                              "steps": steps(h[1])} for i, h in enumerate(handed)]}
    fake_runner = FakeRunner()
    live.runner = lambda: fake_runner
    probes = []
    live.probe = lambda url: probes.append(url) or {"status": "is_live", "title": TITLE, "channel": CHANNEL, "message": ""}
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
    cx = types.SimpleNamespace()   # 場面の関数(下の _scene_*)と分け合う値
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

                cx.__dict__.update(locals())   # 場面の関数へ渡す値(この run の中の値。場面が作って、あとで使う値は場面が cx に戻す)
                _scene_off(cx)
                _scene_turn_on(cx)
                _scene_begin_and_play(cx)
                _scene_mark_and_export(cx)
                _scene_seek_and_leave(cx)
                _scene_gap(cx)
                _scene_settings_and_sound(cx)
                _scene_badge_stop(cx)
                _scene_after_end(cx)
                _scene_adopt_api(cx)
                _scene_peaks(cx)
                _scene_narrow_and_errors(cx)
            finally:
                browser.close()
    finally:
        for r in (getattr(cx, k, None) for k in ("rid", "rid2")):   # 場面の関数が録画を始めたら cx に入れる
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


def _scene_off(cx):
    """13. オフのとき"""
    check, ctx, errors, not_found, probes, studio_url, watch = cx.check, cx.ctx, cx.errors, cx.not_found, cx.probes, cx.studio_url, cx.watch
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
    cx.pg = pg


def _scene_turn_on(cx):
    """1. ホームでオンにする"""
    base, check, ctx, srv, watch = cx.base, cx.check, cx.ctx, cx.srv, cx.watch
    # ---------------- 1. ホームでオンにする ----------------
    pg = ctx.new_page()
    watch(pg, "home")
    pg.goto(base + "/")
    pg.click("[data-ui-settings]")   # 試験中の機能は ⚙ 設定の「ホーム」の節(UI の見直し M10。以前は「詳しく」の中)
    wait_js(pg, "!!document.getElementById('labBox') && !document.getElementById('labBox').hidden")
    pg.click("#liveEnabled")
    check(wait_js(pg, "document.getElementById('liveMsg').hidden === false") and srv.prefs.get(["live"])["live"]["enabled"] is True,
          "1 ホームの「試験中の機能」でオンにする")
    # M2: オンにすると「書き出したあとの自動の流れ」(live.auto)の欄が出て、選ぶと設定に入る
    check(wait_js(pg, "!document.getElementById('liveAutoBox').hidden", 5000), "M2 ホームの「試験中の機能」に「書き出したあとの自動の流れ」が出る")
    pg.evaluate("document.getElementById('liveAutoBox').open = true")
    pg.select_option("#liveAutoEngine", "whisper.cpp")
    pg.fill("#liveAutoModel", "large-v3")
    pg.press("#liveAutoModel", "Tab")
    check(wait_for(lambda: (lambda a: a["engine"] == "whisper.cpp" and a["model"] == "large-v3" and a)(srv.prefs.get(["live"])["live"]["auto"]), 8),
          "M2 エンジン・モデルを選ぶと live.auto に入る: %s" % srv.prefs.get(["live"])["live"]["auto"])
    # M7: 配信後の全自動のスイッチと 1 時間あたりの数(既定オフ・6)
    check(pg.evaluate("document.getElementById('liveAfterStream').checked") is False and pg.input_value("#liveAfterPerHour") == "6",
          "M7 「配信が終わったら、アーカイブの解析で自動で切り抜く」は既定オフ・1 時間あたり 6")
    pg.click("#liveAfterStream")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["autoAfterStream"] is True, 8), "M7 付けると live.autoAfterStream = true")
    pg.fill("#liveAfterPerHour", "8")
    pg.press("#liveAfterPerHour", "Tab")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["afterStreamPerHour"] == 8, 8), "M7 1 時間あたりを 8 に")
    pg.click("#liveAfterStream")   # 外す(この e2e の録画で配信後の全自動を動かさない)
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["autoAfterStream"] is False, 8), "M7 外すと live.autoAfterStream = false")
    pg.close()
    cx.pg = pg


def _scene_begin_and_play(cx):
    """2. ② の URL 欄から録画を始める / 3. 自動で再生・録画中・札"""
    LX, api, check, ctx, edge, shots, skip, starts = cx.LX, cx.api, cx.check, cx.ctx, cx.edge, cx.shots, cx.skip, cx.starts
    studio_url, watch = cx.studio_url, cx.watch
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
    rid = cx.rid = lv[0]["id"] if lv else None
    check(len(lv) == 1 and LX.REC_RE.match(rid or "") and lv[0]["live"]["url"] == YT1 and lv[0]["live"]["recorder"] == "local"
          and lv[0]["live"]["videoId"] == "TESTlive001", "2 スタジオの一覧に kind live の配信(id = 録画の id): %s" % (lv[:1],))
    check(lv and lv[0]["title"] == TITLE, "2 題は yt-dlp の題(HTML にしない): %s" % (lv[0]["title"] if lv else None))
    check(pg.evaluate("() => document.querySelector('#rvTitle').value") == TITLE and pg.evaluate("() => !document.querySelector('#rvTitle b')"),
          "2 ③ の題の欄に配信の題")
    check(starts and starts[0]["quality"] == "1080p" and starts[0]["title"] == TITLE, "2 録画元へ既定の画質 1080p と題で頼む: %s" % starts[:1])
    check(lv and lv[0].get("channel") == CHANNEL, "15 begin のチャンネル名がスタジオの配信の channel に入る: %s" % (lv[0].get("channel") if lv else None))

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
    # 15. 書き出したあと・配信者(帯)
    check(pg.input_value("#rvAfter") == "check" and pg.is_visible("#rvAfter"), "15 帯の「書き出したあと」は既定で「文字起こしまで」(今までの自動の文字起こしがオン)")
    check(wait_js(pg, "() => document.querySelector('#rvLiveWhoText').textContent === '配信者: 兎田ぺこら'", 8000),
          "15 帯の「配信者」はチャンネル名から自動で決まる: %s" % pg.text_content("#rvLiveWhoText"))
    pg.select_option("#rvAfter", "auto")
    check(wait_for(lambda: ((api("GET", "/studio/api/settings")[1] or {}).get("settings") or {}).get("review", {}).get("liveAfter") == "auto", 8),
          "15 「全自動」を選ぶとスタジオの設定 review.liveAfter に残る")
    if shots:
        pg.evaluate("window.scrollTo(0, 0)")
        pg.locator("#rvLiveBar").screenshot(path=os.path.join(shots, "live_00_band.png"))

    # 8. 見回りで作り直されないか(ここで要素を掴んでおく)
    pg.evaluate("""() => { window.__keep = ['#rvLiveBar', '#rvRecState', '#rvAutoExp', '#rvRecStop', '#rvLiveGuide', '#rvEdge', '#rvTitle',
                  '[data-ui-live] .ui-live-btn', '#rvAfter', '#rvLiveWho', '#rvLiveWhoIn', '#rvLiveWhoText'].map(s => [s, document.querySelector(s)]); }""")
    keep_at = time.time()
    cx.keep_at, cx.pg = keep_at, pg


def _scene_mark_and_export(cx):
    """4・5. I → O → 追加 → すぐ書き出す"""
    LX, api, check, edge, handed, handed_who, normalize, pg = cx.LX, cx.api, cx.check, cx.edge, cx.handed, cx.handed_who, cx.normalize, cx.pg
    rid, schemas, shots, skip = cx.rid, cx.schemas, cx.shots, cx.skip
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
        check(handed and handed[0] == (job["path"], "auto"), "15 帯で「全自動」→ 入口がまとめて実行へ flow auto で渡す: %s" % handed[:1])
        check(handed_who[:1] == ["兎田ぺこら"], "15 配信者の名前(チャンネル名から)もまとめて実行へ渡る: %s" % handed_who[:1])
        check(job.get("after") == "auto" and job.get("streamer") == "兎田ぺこら", "15 ジョブに after と streamer が残る: %s %s" % (job.get("after"), job.get("streamer")))
        check(wait_js(pg, "() => { const t = document.querySelector('#rvExpList').textContent; return t.includes('文字起こし → パック: 実行中(パック)'); }", 10000),
              "15 書き出しの行に、まとめて実行の進み具合(全自動: 文字起こし → パック)")
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


def _scene_seek_and_leave(cx):
    """6. シーク / 7. ③ を離れると止まる / 8. 作り直されない"""
    check, edge, keep_at, pg, skip = cx.check, cx.edge, cx.keep_at, cx.pg, cx.skip
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
    check(pg.input_value("#rvAfter") == "auto" and pg.text_content("#rvLiveWhoText") == "配信者: 兎田ぺこら",
          "15 見回りのあとも「書き出したあと」と配信者の値が戻らない: %s / %s" % (pg.input_value("#rvAfter"), pg.text_content("#rvLiveWhoText")))


def _scene_gap(cx):
    """欠け(繋ぎ直し)をまたぐ: 状態の表示・欠けの中への seek・欠けのあとのマークの位置"""
    LX, api, check, edge, live_src, normalize, pg, rid = cx.LX, cx.api, cx.check, cx.edge, cx.live_src, cx.normalize, cx.pg, cx.rid
    skip = cx.skip
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
    cx.n_jobs = n_jobs


def _scene_settings_and_sound(cx):
    """11. 設定の引き出し / 8b. ほかの窓(編集)で再生している間は、配信の音を下げる・消す"""
    base, check, ctx, edge, pg, rfolder, shots, srv = cx.base, cx.check, cx.ctx, cx.edge, cx.pg, cx.rfolder, cx.shots, cx.srv
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


def _scene_badge_stop(cx):
    """9. 札 → 一覧 → 停止(二度押し)"""
    base, check, edge, pg, rid, shots, skip = cx.base, cx.check, cx.edge, cx.pg, cx.rid, cx.shots, cx.skip
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


def _scene_after_end(cx):
    """10. 終わった録画でマークして「書き出す」 / 12. 読み込み直す / 11 の続き: 次の begin はその画質で"""
    api, check, edge, handed, handed_who, live, n_jobs, normalize = cx.api, cx.check, cx.edge, cx.handed, cx.handed_who, cx.live, cx.n_jobs, cx.normalize
    pg, probes, rid, shots, srv, starts, studio_url = cx.pg, cx.probes, cx.rid, cx.shots, cx.srv, cx.starts, cx.studio_url
    # ---------------- 10. 終わった録画でマークして「書き出す」 ----------------
    pg.click("#rvAutoExp")   # 「マークしたらすぐ書き出す」を外す(いつものスタジオと同じ: 採用 → 書き出す)
    check(not pg.is_checked("#rvAutoExp"), "10 「マークしたらすぐ書き出す」を外せる")
    # 15. 帯で配信者を直し、書き出したあとを「文字起こしまで」に → 次の(手動の)書き出しに渡る
    pg.select_option("#rvAfter", "check")
    pg.click("#rvLiveWho > summary")
    check(wait_js(pg, "() => document.querySelector('#rvLiveWho').open && !!document.querySelector('#rvLiveWhoIn').offsetParent", 3000), "15 「配信者」を押すと名前の欄が開く")
    if shots:
        pg.evaluate("window.scrollTo(0, 0)")
        pg.screenshot(path=os.path.join(shots, "live_00b_band_streamer.png"))
    pg.fill("#rvLiveWhoIn", "宝鐘マリン")
    pg.press("#rvLiveWhoIn", "Enter")
    check(wait_js(pg, "() => document.querySelector('#rvLiveWhoText').textContent === '配信者: 宝鐘マリン' && !document.querySelector('#rvLiveWho').open", 5000),
          "15 名前を直して Enter → 帯が「配信者: 宝鐘マリン」・欄は閉じる: %s" % pg.text_content("#rvLiveWhoText"))
    st_mem = wait_for(lambda: (lambda m: m if m["videos"].get(rid) == "宝鐘マリン" and m["channels"].get(CHANNEL) == "宝鐘マリン" else None)(srv.prefs.get(["streamer"])["streamer"]), 8)
    check(st_mem, "15 直した名前は、この録画とこのチャンネルに覚える(次からそれを使う): %s" % srv.prefs.get(["streamer"])["streamer"])
    n_handed = len(handed)
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
    check(len(handed) == n_handed + 1 and handed[-1][1] == "check" and handed_who[-1] == "宝鐘マリン",
          "15 直した配信者・「文字起こしまで」が次の書き出しに渡る: %s %s" % (handed[-1:], handed_who[-1:]))
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
    check(pg.input_value("#rvAfter") == "check" and wait_js(pg, "() => document.querySelector('#rvLiveWhoText').textContent === '配信者: 宝鐘マリン'", 8000),
          "15 開き直しても「書き出したあと」と直した配信者のまま: %s / %s" % (pg.input_value("#rvAfter"), pg.text_content("#rvLiveWhoText")))

    # ---------------- 11 の続き: 次の begin はその画質で ----------------
    # 画面の Studio.live.begin(① 探す の「録画する」と同じ呼び方)。yt-dlp がチャンネル名を返さないときは、呼んだ側の名前(① 探す の行)を入れる
    live.probe = lambda url: probes.append(url) or {"status": "is_live", "title": TITLE, "channel": "", "message": ""}
    b2 = pg.evaluate("async (u) => { const b = await Studio.live.begin(u, { channel: 'Marine Ch. 宝鐘マリン' }); return b && { id: b.video.id, channel: b.video.channel, rch: b.recording.channel }; }", YT2)
    rid2 = cx.rid2 = (b2 or {}).get("id")
    check(b2 and starts[-1]["quality"] == "720p" and starts[-1]["url"] == YT2,
          "11 次の begin は設定の画質 720p で録画元へ頼む: %s" % (starts[-1] if starts else None))
    check(b2 and b2["rch"] == "" and b2["channel"] == "Marine Ch. 宝鐘マリン",
          "15 begin がチャンネル名を返さないときは、呼んだ側(① 探す の行)の名前がスタジオの配信に入る: %s" % b2)
    if rid2:
        code, d = api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid2})
        check(code == 200 and d.get("ok"), "11 2本目を止める")


def _scene_adopt_api(cx):
    """M1. サーバー側の「マーク + 書き出し」(POST /live/api/adopt)・M3 の「調子」"""
    LX, api, check, handed, handed_kw, live, n_jobs, normalize = cx.LX, cx.api, cx.check, cx.handed, cx.handed_kw, cx.live, cx.n_jobs, cx.normalize
    pg, rid, schemas, studio_url = cx.pg, cx.rid, cx.schemas, cx.studio_url
    # ---------------- M1. サーバー側の「マーク + 書き出し」(POST /live/api/adopt。画面を閉じていても) ----------------
    pg.goto("about:blank")   # スタジオの画面を閉じる(③ でこの録画を開いていない = 画面は「書き出し済み」を付けない。入口が自分で付ける)
    n_handed = len(handed)

    def marks_of(v):
        return ((api("GET", "/studio/api/video?id=%s" % v)[1] or {}).get("video") or {}).get("marks") or []
    code, ad = api("POST", "/live/api/adopt", {"recorder": "local", "recording": rid, "start": 10.04, "end": 13.0, "label": "自動の山", "origin": "auto"})
    check(code == 200 and ad and ad["origin"] == "auto" and ad["existing"] is False and ad["job"]["after"] == "check",
          "M1 adopt を受け付ける(after は設定 live.auto.after = 既定の文字起こしまで): %s" % ((ad or {}).get("job") or ad,))
    jid = ((ad or {}).get("job") or {}).get("id")
    done3 = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(
        [j for j in (api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1] or {}).get("jobs") or [] if j["id"] == jid]), 90, 0.5)
    check(done3 and done3["state"] == "done", "M1 画面なしで書き出しまで通る: %s" % (((done3 or {}).get("state"), (done3 or {}).get("error")),))
    mk3 = wait_for(lambda: (lambda m: m if m and m["status"] == "exported" else None)(next((m for m in marks_of(rid) if m["id"] == (ad or {}).get("mark")), None)), 15)
    check(mk3 and mk3["start"] == 8.0 and mk3["end"] == 15.0 and done3 and os.path.normcase(mk3.get("path") or "") == os.path.normcase(done3["path"]),   # 自動の採用は前後に余白 2 秒(M8。ホーム 0.46.2)
          "M1 スタジオの一覧にマークが出て「書き出し済み」(入口が付けた。区間は前後 2 秒の余白つき・スタジオの丸め): %s" % (mk3,))
    if done3 and done3["state"] == "done":
        clip3, _w = schemas.load_clip_file(schemas.find_clip_path(done3["path"]))
        check(clip3 and clip3["source"]["live"]["origin"] == "auto" and clip3["mark"]["src"] == "auto" and clip3["source"]["live"]["studio"]["mark"] == mk3["id"],
              "M1 .clip.json に origin auto(mark.src も auto): %s" % ((clip3 or {}).get("mark"),))
        info3 = normalize.probe(done3["path"])
        check(normalize.is_30fps(info3) and abs(info3.get("duration", 0) - 7.0) <= 0.15, "M1 30fps・長さが区間(3 秒 + 余白 2 秒 × 2)と合う: %.2f 秒" % (info3 or {}).get("duration", 0))
    check(len(handed) == n_handed + 1 and handed[-1][1] == "check" and handed_kw[-1] == {"engine": "whisper.cpp", "model": "large-v3"},
          "M2 live.auto のエンジン・モデルがまとめて実行へ渡る: %s %s" % (handed[-1:], handed_kw[-1:]))
    try:
        with open(os.path.join(live.store_dir, LX.FEEDBACK), encoding="utf-8") as f:
            fb3 = [json.loads(x) for x in f if x.strip()]
    except OSError:
        fb3 = []
    check(fb3 and fb3[-1]["origin"] == "auto" and fb3[-1]["human"] is False and fb3[-1]["verdict"] is None and fb3[-1]["jobId"] == jid,
          "M1 live_feedback.jsonl に origin(自動は「良い」に数えない): %s" % fb3[-1:])
    code, ad2 = api("POST", "/live/api/adopt", {"recorder": "local", "recording": rid, "start": 10.0, "end": 13.0, "origin": "auto"})
    check(code == 200 and ad2["existing"] is True and ad2["job"]["id"] == jid and len(marks_of(rid)) == n_jobs + 2,
          "M1 同じ区間をもう一度 → 新しく作らない(マークもジョブも増えない)")
    code, bad = api("POST", "/live/api/adopt", {"recorder": "local", "recording": rid, "start": 1.0, "end": 3.0, "origin": "robot"})
    check(code == 400, "M1 origin は manual・auto・archive だけ: %s" % (code,))
    pg.goto(studio_url + "?video=" + rid)
    check(wait_js(pg, "() => Studio.step === 'review' && document.querySelectorAll('#rvList .rv-chip.exported').length === %d" % (n_jobs + 2), 15000),
          "M1 ③ で開くと、足したマークも「書き出し済み」")
    # M3: 「調子」にリアルタイム切り抜きの失敗の行(この通しでは失敗が無い = 「なし」)
    code, hh = api("GET", "/api/health")
    check(code == 200 and isinstance(((hh or {}).get("live") or {}).get("failures"), list), "M3 「調子」の live に failures: %s" % (((hh or {}).get("live") or {}).get("failures"),))


def _clock(s):
    """スタジオの時刻の表示(1:02:03.4・0:14.0)→ 秒"""
    t = 0.0
    for part in str(s).replace("/", "").strip().split(":"):
        t = t * 60 + float(part)
    return t


def _fmt_clock(t):
    """Studio.fmtTime と同じ形(0.1 秒まで)"""
    d = int(round(t * 10))
    h, m, sec = d // 36000, d % 36000 // 600, (d % 600) / 10
    return "%d:%02d:%04.1f" % (h, m, sec) if h else "%d:%04.1f" % (m, sec)


def _pw_wait(pg, fn, timeout=15.0, step=250):
    """Playwright の出来事(route の応答など)を回しながら待つ(time.sleep の間は route の関数が呼ばれない)"""
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        pg.wait_for_timeout(step)
    return fn()


def _scene_peaks(cx):
    """L2 + L3(線 D)配信中の候補: 本物の候補の API(入口の live_detect)と偽のワーカー(tests/fake_excite_worker.py = テストが置いた候補を本物と同じ形で
    peaks.json・worker.json に書き、decisions.json を本物と同じに当てる)で、帯の一覧・見出し・タイムラインの印・グラフ・[再生]・[採用](POST /live/api/peaks → M1 の adopt)・
    [見送り]・控えも見る・[戻す]・採用した候補の見送りは 409・p / z・見回りで作り直さない・⚙ の設定(live.detect / live.autoAdopt)・「調子」・375px。
    音・チャット・ffmpeg は使わない(ワーカーの計算は src/home/tests/test_live_detect.py)"""
    api, check, pg, rid, shots, studio_url, srv, live = cx.api, cx.check, cx.pg, cx.rid, cx.shots, cx.studio_url, cx.srv, cx.live
    det = live.detector
    det.worker, det.spawn_ok, det.python = os.path.join(TESTS, "fake_excite_worker.py"), True, sys.executable
    excite_dir = det.dir
    folder = os.path.join(excite_dir, "local", rid)

    # 候補(録画の長さの中に置く。録画が短いときは縮める)と series.jsonl(1 分 1 行)
    st = api("GET", "/live/r/local/%s/status?since=999999999" % rid)[1] or {}
    dur = float(st.get("seconds") or 0)
    k = 1.0 if dur >= 42 else max(0.3, (dur - 2) / 42.0)
    T = lambda x: round(x * k, 1)   # noqa: E731
    peaks = {}
    for pid, a, b, sc, why, state, pend in (("p1-14", 14, 18, 8.2, ["音量が急上昇"], "frame", False), ("p2-20", 20, 24, 6.5, ["チャットが急増"], "frame", False),
                                            ("p3-26", 26, 29, 4.1, ["音量が急上昇"], "bench", False), ("p4-30", 30, 36, 5.0, [], "frame", True)):
        peaks[pid] = {"id": pid, "start": T(a), "end": T(b), "peak": int(T(a + 2)), "score": sc, "parts": {"audio": 2.5, "chat": 1.0}, "reasons": why,
                      "confirmedAt": int(T(b)) + 12, "hour": 0, "state": state, "endPending": pend, "origin": None}
    n = int(max(dur, 10.0))
    tot = [round(1 + sum(4 * math.exp(-((i - p["peak"]) / 2.0) ** 2) for p in peaks.values()), 2) for i in range(n)]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "series.jsonl"), "w", encoding="utf-8") as f:
        for t0 in range(0, n, 60):
            seg = tot[t0:t0 + 60]
            f.write(json.dumps({"t0": t0, "total": seg, "audio": [round(x * 0.6, 2) for x in seg], "chat": [round(x * 0.4, 2) for x in seg]}) + "\n")
    control = {"recorder": "local", "recording": rid, "seq": 10, "peaks": list(peaks.values()), "worker": {"behindSec": 35, "chat": "ok", "memMB": 42}}
    ctl_path = os.path.join(excite_dir, "fake_control.json")
    os.makedirs(excite_dir, exist_ok=True)

    def write_ctl():
        with open(ctl_path, "w", encoding="utf-8") as f:
            json.dump(control, f, ensure_ascii=False)

    def dec_items():
        try:
            with open(os.path.join(folder, "decisions.json"), encoding="utf-8") as f:
                return json.load(f).get("items") or []
        except (OSError, ValueError):
            return []

    write_ctl()
    srv.prefs.patch("live", {"detect": {"enabled": True, "sens": "normal", "perHour": 6},
                             "autoAdopt": {"enabled": False, "waitMin": 5}})   # 0.46.3 から自動採用は既定オン。この場面は人の採用を見るので明示的にオフ
    check(det.tick() == "spawned", "L2 検出をオンにすると、見回りがワーカーを起動する(config.json を書いて)")
    check(wait_for(lambda: os.path.isfile(os.path.join(folder, "peaks.json")) and det.running(), 15), "L2 ワーカーが peaks.json と心拍(worker.json)を書く")
    g = api("GET", "/live/api/peaks?recorder=local&recording=%s" % rid)[1] or {}
    check(g.get("ok") is True and g.get("enabled") is True and len(g.get("peaks") or []) == 4 and (g.get("series") or {}).get("n") == n and g["worker"]["running"] is True,
          "L2 GET /live/api/peaks: 候補 4 件・series(%s 秒)・ワーカーの状態: %s" % (n, {x: g.get(x) for x in ("seq", "enabled", "hour", "autoAdopt")}))
    reqs = []
    pg.on("request", lambda r: reqs.append(r.url) if "/live/api/peaks" in r.url else None)
    pg.goto(studio_url + "?video=" + rid)
    row = lambda pid: '#rvPeakList .rv-peak[data-pid="%s"]' % pid   # noqa: E731
    live_rows = "() => [...document.querySelectorAll('#rvPeakList .rv-peak:not(.is-gone)')].map(x => x.dataset.pid)"
    check(wait_js(pg, "() => !document.querySelector('#rvPeaks').hidden && document.querySelectorAll('#rvPeakList .rv-peak').length === 3", 15000),
          "L3 帯に候補の行が出る(枠 2 件 + 終わり待ち 1 件。控えは出さない): %s" % pg.evaluate(live_rows))
    check(pg.evaluate(live_rows) == ["p1-14", "p2-20", "p4-30"], "L3 行は時刻の順: %s" % pg.evaluate(live_rows))
    check(reqs and "since=" not in reqs[0], "L3 最初は since 無し(全部 + series)で聞く: %s" % reqs[:1])
    count, info = pg.text_content("#rvPeakCount"), pg.text_content("#rvPeakInfo") or ""
    check(count == "候補 3 件(この 1 時間 3/6)" and "遅れ 35 秒" in info and "チャットを読んでいます" in info and "自動採用 オフ" in info,
          "L3 見出し: %s / %s" % (count, info))
    r1 = pg.evaluate("""(s) => { const r = document.querySelector(s); return r && { t: r.querySelector('[data-pf="time"]').textContent, sc: r.querySelector('[data-pf="score"]').textContent,
                      why: r.querySelector('[data-pf="why"]').textContent, pill: r.querySelector('[data-pf="pill"]').textContent }; }""", row("p1-14"))
    check(r1 and r1["sc"] == "8.2点" and "音量が急上昇" in r1["why"] and r1["pill"] == "枠", "L3 行: 時刻・点数・理由・札: %s" % r1)
    check(pg.evaluate("(s) => { const r = document.querySelector(s); return !r.querySelector('[data-pf=\"pend\"]').hidden && r.querySelector('[data-pact=\"adopt\"]').disabled; }", row("p4-30")),
          "L3 終わり待ちの候補は「終わり待ち」の札で、採用は押せない(理由つき)")
    check(pg.evaluate("() => document.querySelectorAll('#rvPeakSegs .rv-seg.cand').length") == 3, "L3 タイムラインに候補の印が 3 つ")
    check(pg.evaluate("() => !document.querySelector('#rvGraph').hidden && !!document.querySelector('#rvGSvg .rv-g-area')"), "L3 解析していない録画でも、候補の series(series.jsonl)でグラフが出る")
    if shots:
        pg.locator("#rvLiveBar").screenshot(path=os.path.join(shots, "live_10_peaks_band.png"))
    pg.evaluate("() => { window.__pkKeep = ['#rvPeaks', '#rvPeakList', '#rvPeakCount', '#rvPeakBench', '%s'].map(s => [s, document.querySelector(s)]); }" % row("p1-14"))
    n0 = pg.evaluate("() => document.querySelectorAll('#rvList .rv-mark-row').length")

    # [再生]: 5 秒前から(区間の終わりで止まる)・行が「再生中」
    p1 = peaks["p1-14"]
    pg.click(row("p1-14") + ' [data-pact="play"]')
    pg.wait_for_timeout(400)
    now = _clock(pg.input_value("#rvNow"))
    check(abs(now - max(0, p1["start"] - 5)) < 2.5, "L3 [再生] で再生位置が候補の 5 秒前へ: %.1f(候補 %.1f)" % (now, p1["start"]))
    check(wait_js(pg, "() => document.querySelector('%s').classList.contains('is-playing')" % row("p1-14"), 3000), "L3 再生中の候補の行に印")

    # [採用](二度押しでも 1 回)→ 本物の POST /live/api/peaks → M1 の adopt → decisions.json・マークの一覧・書き出し。配信者は録画に覚えた名前が入ってから
    wait_js(pg, "() => document.querySelector('#rvLiveWhoText').textContent === '配信者: 宝鐘マリン'", 8000)
    pg.evaluate("(s) => { const b = document.querySelector(s); b.click(); b.click(); }", row("p1-14") + ' [data-pact="adopt"]')
    check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length === %d" % (n0 + 1), 15000), "L3 [採用] でマークの一覧にマークが増える(%d → %d)" % (n0, n0 + 1))
    check(wait_for(lambda: [i for i in dec_items() if i.get("state") == "adopted" and i.get("id") == "p1-14" and i.get("markId") and i.get("jobId")], 10),
          "L2 採用が decisions.json に残る(markId・jobId つき): %s" % [(i.get("id"), i.get("state"), i.get("origin")) for i in dec_items()])
    check(len([i for i in dec_items() if i.get("state") == "adopted"]) == 1, "L3 二度押ししても採用は 1 回")
    j1 = next((j for j in (api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1] or {}).get("jobs") or [] if j.get("studio") and abs(j["studio"]["start"] - p1["start"]) < 0.06), None)
    check(j1 and j1.get("after") == "check" and j1.get("streamer") == "宝鐘マリン" and j1.get("origin") == "manual",
          "L2 採用の書き出しに帯の「書き出したあと」と配信者が入る(origin manual): %s" % {x: (j1 or {}).get(x) for x in ("after", "streamer", "origin")})
    check(wait_js(pg, "() => document.querySelector('%s [data-pf=\"pill\"]').textContent === '採用' && document.querySelector('%s [data-pact=\"adopt\"]').hidden"
                  % (row("p1-14"), row("p1-14")), 8000), "L3 採用した候補は「採用」の札だけ(ワーカーが decisions を当てたあとも)")
    t1 = _fmt_clock(p1["start"])
    check(wait_js(pg, "() => document.querySelector('#rvExpList').textContent.includes('%s')" % t1, 15000), "L3 書き出しの欄に採用した候補の行(%s〜)" % t1)
    check(pg.evaluate("() => document.querySelectorAll('#rvPeakSegs .rv-seg.cand').length") == 2, "L3 採用した候補はタイムラインの候補の印から外れる(マークの印になる)")
    code409, _b = api("POST", "/live/api/peaks", {"op": "dismiss", "recorder": "local", "recording": rid, "id": "p1-14"})
    check(code409 == 409, "L2 採用した候補の見送りは 409: %s" % code409)

    # マウスが乗っている行は、入れ替えで外れても消さない(離れてから薄くして消す)。入れ替えはワーカー(偽)が peaks.json の seq を進める
    pg.hover(row("p2-20") + " [data-pf=\"time\"]")
    control["set"] = {"p2-20": "bench"}
    write_ctl()
    check(wait_js(pg, "(s) => { const r = document.querySelector(s); return !!r && r.querySelector('[data-pf=\"pill\"]').textContent === '控え'; }", 15000, row("p2-20")) if False else
          _pw_wait(pg, lambda: pg.evaluate("(s) => { const r = document.querySelector(s); return !!r && !r.classList.contains('is-gone') && r.querySelector('[data-pf=\"pill\"]').textContent === '控え'; }", row("p2-20")), 15),
          "L3 マウスが乗っている行は、控えに外れても一覧に残す(札は「控え」)")
    pg.mouse.move(2, 2)
    check(wait_js(pg, "() => !document.querySelector('%s')" % row("p2-20"), 7000), "L3 マウスが離れたら、外れた行は薄くしてから消える")

    # [見送り] → decisions.json → 行が消える(知らせの「元に戻す」)→ 控えも見る で出る → [戻す]
    pg.click(row("p4-30") + ' [data-pact="dismiss"]')
    check(wait_for(lambda: any(i.get("state") == "dismissed" and i.get("id") == "p4-30" for i in dec_items()), 5), "L2 [見送り] が decisions.json に残る")
    check(wait_js(pg, "() => /を見送りました/.test(document.querySelector('#toast').textContent)", 4000), "L3 見送りの知らせ(元に戻す つき)")
    pg.evaluate("() => document.activeElement && document.activeElement.blur()")
    pg.mouse.move(2, 2)
    check(wait_js(pg, "() => !document.querySelector('%s')" % row("p4-30"), 7000), "L3 見送った行は一覧から消える")
    pg.click("#rvPeakBench")
    check(wait_js(pg, "() => document.querySelectorAll('#rvPeakList .rv-peak:not(.is-gone)').length === 4", 5000),
          "L3 「控えも見る」で控えと見送りも出る: %s" % pg.evaluate(live_rows))
    check(pg.evaluate("(s) => { const r = document.querySelector(s); return r.querySelector('[data-pf=\"pill\"]').textContent === '見送り' && !r.querySelector('[data-pact=\"restore\"]').hidden; }", row("p4-30")),
          "L3 見送った行は「見送り」の札と [戻す]")
    pg.click(row("p4-30") + ' [data-pact="restore"]')
    check(wait_for(lambda: any(i.get("state") == "restore" and i.get("id") == "p4-30" for i in dec_items()), 5), "L2 [戻す] が decisions.json に残る")
    check(wait_js(pg, "() => { const r = document.querySelector('%s'); return r.querySelector('[data-pf=\"pill\"]').textContent === '枠' && r.querySelector('[data-pact=\"restore\"]').hidden; }" % row("p4-30"), 8000),
          "L3 [戻す] で枠に戻る(ワーカーが当てる)")

    # p = 次の候補を再生・z = いまの候補を採用
    pg.evaluate("() => document.activeElement && document.activeElement.blur()")
    pg.mouse.move(2, 2)
    pg.keyboard.press("p")
    pg.wait_for_timeout(400)
    now = _clock(pg.input_value("#rvNow"))
    p2 = peaks["p2-20"]
    check(abs(now - max(0, p2["start"] - 5)) < 2.5 and wait_js(pg, "() => document.querySelector('%s').classList.contains('is-playing')" % row("p2-20"), 3000),
          "L3 p で次の候補(直前に再生した候補の次)を 5 秒前から再生: %.1f(候補 %.1f)" % (now, p2["start"]))
    pg.keyboard.press("z")
    check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length === %d" % (n0 + 2), 15000)
          and wait_for(lambda: len([i for i in dec_items() if i.get("state") == "adopted"]) == 2, 5),
          "L3 z でいま再生している候補を採用(マークが増える・decisions に 2 件目)")
    check(wait_js(pg, "() => document.querySelector('%s [data-pf=\"pill\"]').textContent === '採用'" % row("p2-20"), 8000), "L3 z で採用した候補は「採用」の札")
    pg.keyboard.press("p")
    pg.wait_for_timeout(400)
    now = _clock(pg.input_value("#rvNow"))
    check(abs(now - max(0, peaks["p3-26"]["start"] - 5)) < 2.5, "L3 もう一度 p で次の候補(控え): %.1f" % now)
    check(pg.evaluate("() => { const k = document.querySelector('.ui-keybar'); return !k || k.hidden || /次の候補/.test(k.textContent); }"),
          "L3 下のキーの帯に「次の候補」(帯を出しているとき)")

    # 3 秒の見回りで作り直さない(要素が同じ)・差分(since)で聞いている
    pg.evaluate("() => { window.__pkRows = [...document.querySelectorAll('#rvPeakList .rv-peak')]; }")
    g1 = len(reqs)
    _pw_wait(pg, lambda: len([u for u in reqs[g1:] if "since=" in u]) >= 2, 35)   # 録画が終わっていると見回りは 10 秒ごと
    gone = pg.evaluate("() => window.__pkKeep.filter(([s, el]) => !el || !el.isConnected || document.querySelector(s) !== el).map(([s]) => s)"
                       " .concat(window.__pkRows.filter(el => !el.isConnected).map(el => el.dataset.pid))")
    check(len([u for u in reqs[g1:] if "since=" in u]) >= 2 and not gone,
          "L3 見回り(since の差分 %d 回。録画が終わっていれば 10 秒ごと)で帯・候補の行が作り直されない: %s" % (len([u for u in reqs[g1:] if "since=" in u]), gone))
    _scene_peak_text(cx, row)

    # ⚙ の設定: 配信中の候補(live.detect)と自動採用(live.autoAdopt)→ 入口の設定に入り、帯の見出しに出る
    pg.click("#btnSettings")
    check(wait_js(pg, "() => { const s = document.querySelector('#liveDetect'); return s && s.offsetParent && s.checked; }", 8000), "L3 ⚙ に「配信中の候補」の群(オンになっている)")
    pg.fill("#liveDetectPerHour", "8")
    pg.keyboard.press("Tab")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["detect"]["perHour"] == 8 and srv.prefs.get(["live"])["live"]["detect"]["enabled"] is True, 8),
          "L2 1 時間の本数を変えると live.detect.perHour に入る(オンのまま): %s" % srv.prefs.get(["live"])["live"]["detect"])
    pg.fill("#liveAutoAdoptWait", "60")
    pg.keyboard.press("Tab")
    pg.check("#liveAutoAdopt")
    check(wait_for(lambda: (lambda a: a["enabled"] is True and a["waitMin"] == 60)(srv.prefs.get(["live"])["live"]["autoAdopt"]), 8),
          "L2 自動採用をオンにすると live.autoAdopt に入る: %s" % srv.prefs.get(["live"])["live"]["autoAdopt"])
    _scene_live_tx_switch(cx)
    pg.keyboard.press("Escape")
    check(wait_js(pg, "() => /自動採用 オン\\(60 分待ち\\)/.test(document.querySelector('#rvPeakInfo').textContent)", 12000), "L3 帯の見出しに「自動採用 オン(60 分待ち)」: %s" % pg.text_content("#rvPeakInfo"))
    srv.prefs.patch("live", {"autoAdopt": {"enabled": False, "waitMin": 5}})
    h = (api("GET", "/api/health")[1] or {}).get("live") or {}
    check((h.get("detect") or {}).get("running") is True, "L2 「調子」に検出のワーカー(動いている): %s" % {x: (h.get("detect") or {}).get(x) for x in ("running", "behindSec", "restarts")})

    # 採用した 2 本の書き出しが済む(入口の adopt の書き出し)
    def jobs():
        js = (api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1] or {}).get("jobs") or []
        mine = [j for j in js if j.get("studio") and any(abs(j["studio"]["start"] - peaks[x]["start"]) < 0.06 for x in ("p1-14", "p2-20"))]
        return mine if len(mine) == 2 and all(j["state"] in ("done", "error") for j in mine) else None
    done = _pw_wait(pg, jobs, 90, 500)
    check(done and all(j["state"] == "done" for j in done), "L3 採用した候補の書き出しが済む: %s" % [(j.get("state"), j.get("error")) for j in done or []])

    # 狭い画面
    pg.set_viewport_size({"width": 375, "height": 812})
    pg.wait_for_timeout(400)
    check(pg.evaluate(NO_HSCROLL_JS) and pg.evaluate("() => { const r = document.querySelector('#rvPeaks').getBoundingClientRect(); return r.width > 0 && r.left >= 0 && r.right <= innerWidth + 1; }"),
          "L3 375px で候補の一覧がはみ出さない")
    if shots:
        pg.locator("#rvLiveBar").screenshot(path=os.path.join(shots, "live_11_peaks_narrow.png"))
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.wait_for_timeout(300)

    # 後始末: 検出をオフ → 見回りがワーカーを止める → 帯の候補の部分は隠れる
    srv.prefs.patch("live", {"detect": {"enabled": False, "sens": "normal", "perHour": 6}})
    check(det.tick() == "off" and wait_for(lambda: det.proc is None or det.proc.poll() is not None, 10), "L2 検出をオフにすると、見回りがワーカーを止める")
    check(wait_js(pg, "() => document.querySelector('#rvPeaks').hidden", 15000), "L3 オフにすると帯の候補の部分が隠れる")


def _scene_peak_text(cx, row):
    """D-11 案 b(src/home/live_tx.py): 入口が候補に文字を付けると、見回り(since の差分 = 最近文字が付いた候補)で行の [data-pf="tx"] に出る
    (80 字で切る・title に全文)。whisper.cpp の無いテストの入口では準備が無いので、見出しに「文字起こしなし(理由)」"""
    check, pg, live, rid = cx.check, cx.pg, cx.live, cx.rid
    info = pg.text_content("#rvPeakInfo") or ""
    check("文字起こしなし(whisper.cpp がありません)" in info, "D-11 whisper.cpp が無いので、見出しに「文字起こしなし(whisper.cpp がありません)」: %s" % info)
    st = live.livetx.status()
    check(st["enabled"] is True and st["ready"] is False, "D-11 入口の状態: オン・準備なし: %s" % {k: st.get(k) for k in ("enabled", "ready", "message")})
    long_tx = "配信中の文字起こしのテストです。" * 7   # 112 字
    live.livetx.record("local", rid, "p4-30", long_tx)
    live.livetx.record("local", rid, "p1-14", "短い文字")
    tx = lambda pid: row(pid) + ' [data-pf="tx"]'   # noqa: E731
    want = "「" + long_tx[:80] + "…」"
    check(wait_js(pg, "() => { const e = document.querySelector('%s'); return !!e && !e.hidden && e.textContent === %s; }" % (tx("p4-30"), json.dumps(want)), 30000),
          "D-11 文字が付いた候補の行に文字が出る(80 字で切って「…」): %s" % pg.evaluate("(s) => { const e = document.querySelector(s); return e && [e.hidden, e.textContent]; }", tx("p4-30")))
    check(pg.evaluate("(s) => document.querySelector(s).getAttribute('title')", tx("p4-30")) == long_tx, "D-11 行の文字の title に全文")
    check(pg.evaluate("(s) => { const e = document.querySelector(s); return !e.hidden && e.textContent; }", tx("p1-14")) == "「短い文字」", "D-11 短い文字はそのまま(採用した候補にも出る)")
    check(pg.evaluate("(s) => { const e = document.querySelector(s); return e.hidden && !e.textContent && !e.hasAttribute('title'); }", tx("p2-20")),
          "D-11 文字の無い候補の行には出さない")
    g = cx.api("GET", "/live/api/peaks?recorder=local&recording=%s" % rid)[1] or {}
    by = {p["id"]: p for p in g.get("peaks") or []}
    check((by.get("p4-30") or {}).get("text") == long_tx and (g.get("tx") or {}).get("ready") is False, "D-11 GET /live/api/peaks の候補に text・応答に tx")


def _scene_live_tx_switch(cx):
    """D-11 案 b: ⚙ の「候補を文字起こしする」#liveTx(live.liveTx.enabled)。外すと見出しの「文字起こしなし」が消え、戻すと出る(設定の引き出しを開いたまま)"""
    check, pg, srv = cx.check, cx.pg, cx.srv
    has_note = "() => /文字起こしなし\\(/.test(document.querySelector('#rvPeakInfo').textContent)"
    check(wait_js(pg, "() => { const s = document.querySelector('#liveTx'); return !!s && !!s.offsetParent && s.checked && !s.closest('label').hidden; }", 8000),
          "D-11 ⚙ に「候補を文字起こしする」(既定オン)")
    pg.uncheck("#liveTx")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["liveTx"] == {"enabled": False, "model": "large-v3"}, 8),
          "D-11 #liveTx を外すと live.liveTx.enabled が False: %s" % srv.prefs.get(["live"])["live"]["liveTx"])
    check(wait_js(pg, "() => !(%s)()" % has_note, 25000), "D-11 オフにすると見出しの「文字起こしなし」が消える: %s" % pg.text_content("#rvPeakInfo"))
    pg.check("#liveTx")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["liveTx"] == {"enabled": True, "model": "large-v3"}, 8),
          "D-11 #liveTx を戻すと live.liveTx.enabled が True: %s" % srv.prefs.get(["live"])["live"]["liveTx"])
    check(wait_js(pg, has_note, 25000), "D-11 戻すと見出しに「文字起こしなし(…)」がまた出る: %s" % pg.text_content("#rvPeakInfo"))
    # 0.48.1: 自動の切り抜きを確認なしで友人へ届ける(live.autoDeliver。既定オン)
    check(wait_js(pg, "() => { const s = document.querySelector('#liveAutoDeliver'); return !!s && !!s.offsetParent && s.checked && !s.closest('label').hidden; }", 8000),
          "0.48.1 ⚙ に「自動の切り抜きを確認なしで友人へ届ける」(既定オン)")
    pg.uncheck("#liveAutoDeliver")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["autoDeliver"] is False, 8), "0.48.1 外すと live.autoDeliver が False")
    pg.check("#liveAutoDeliver")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["autoDeliver"] is True, 8), "0.48.1 戻すと live.autoDeliver が True")


def _scene_narrow_and_errors(cx):
    """14. 狭い画面・エラー"""
    check, errors, not_found, pg, shots = cx.check, cx.errors, cx.not_found, cx.pg, cx.shots
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


if __name__ == "__main__":
    sys.exit(main())
