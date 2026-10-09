#!/usr/bin/env python3
"""リアルタイム切り抜き P4(アーカイブで本番版に作り直す・録画を自動で消す。plan/line-d-live-clipping.md の 0-9)の通しの確認。
入口にスタジオを取り込み、録画の部品を別のプロセスで立て、ブラウザでスタジオの画面を操作する。本物の YouTube には繋がない。

    py -3.10 src/home/tests/e2e_live_archive.py                 # 確かめる(終了コード 0 = すべて OK)
    py -3.10 src/home/tests/e2e_live_archive.py --shots DIR     # あわせてスクリーンショットを DIR に残す
    py -3.10 src/home/tests/e2e_live_archive.py --chromium      # Edge があっても Playwright の chromium で

作り(e2e_live_studio.py と同じ形。全部一時フォルダ):
  - 「アーカイブ」= ffmpeg の lavfi で作った mp4(testsrc2 の 30fps + 時間で変わる音。照合できる音)。それを -c copy で 1 秒ごとの HLS にして、
    手元の HTTP サーバーで配信中のように出す(hls_fixture.LiveServer。最初から 30 本見えている = 録画はアーカイブの途中から始まる = ずれは 0 でない)
  - 録画の部品(src/recorder/recorder.py)は本物を --source direct で。入口 → 録画元の要求だけ、YouTube の形の URL を手元の HLS の URL に読み替える
  - yt-dlp の所だけ偽物(Live.archive_opts): 用意の確認 = was_live(手で post_live にもする)・開始時刻 = 録画の頭(firstPdt)・
    窓の音 = アーカイブの mp4 から ffmpeg で切る。照合は本物(src/home/live_align_worker.py)
  - スタジオの section(POST /studio/api/live/section)は本物: 疑似モード(STUDIO_FAKE=1)で STUDIO_FAKE_MEDIA = アーカイブの mp4 を切る
    (入口 → スタジオの API の呼び方・409 busy の待ち・path の検査が本物で通る)
  - 時間は縮める: 自動の作り直し(録画が終わって 8 秒・確かめる間隔 2 秒)・録画を消す見回り(毎回)・マークの無い録画(6 秒)・退避した速報版(40 秒)

確かめること:
  S  設定の引き出しの「自動で本番版に作り直す」「録画を消す」が本物の入口(live.autoArchive・live.autoDelete)に保存される
  1  録画 → ② でマーク(自動の書き出し)→ 速報版 / 欠け(つなぎ直しの間をまたぐマーク)→ 失敗・要差し替え / 欠けのあとのマーク
  2  止める → 帯の案内・「アーカイブで作り直す」/ 用意がまだ(post_live)→ 409 の文が帯に出る
  3  押す → 帯の進み具合(n/3 本・段)・スタジオが 409 busy の間は待つ → 速報版が同じ名前で本番版に入れ替わる(30fps・長さ・退避先に速報版・
     clip.json の source.live.archive・速報版との音のずれが 1 コマ以内)・欠けのマークは本番版で新しく書き出される(書き出し済み)
  4  マークに「本番版」の札(スタジオの /api/video の archived・② の行)・前に作った Resolve のパックの注意(無いので出ない)
  5  「録画を消す」がオフの間は録画が残る → オンにすると録画が消え、帯とプレーヤーの所が「録画は消しました…」(開き直しても同じ)・マークは残る
  6  自動: 録画が終わる → 見回りが本番版に作り直す(archive.auto)→ 入れ替えが全部済んだので録画を消す
  7  マークの無い録画: 終わって(縮めた)1 日 → 録画とスタジオの行が消える / 退避した速報版は(縮めた)7 日で消える
  9  配信後の全自動(線 D の M7。live.autoAfterStream): 人がマークしない録画 → 終わる → 録画とアーカイブの時刻を照合 → アーカイブを偽の解析(STUDIO_FAKE)
     → 上位 N を採用(origin archive)→ 書き出し → 本番版に入れ替え → まとめて実行へ「文字起こし → パック」で N 本渡る(人は触らない)・
     自動の切り抜きが済むまで録画を消さない(マークの無い録画の 1 日(縮めた)を過ぎても)→ 済んだら消す・
     スタジオの LIVE の帯に進み具合の 1 行(archiveInfo.afterStream.text。スタジオ 0.21.3)
  8  コンソールのエラー・404・CSP 違反なし(想定した 409・消した録画の 404 は理由を書いて除く)
"""
import json
import os
import re
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

YT1 = "https://www.youtube.com/watch?v=TESTarch001"   # 手で作り直す録画
YT2 = "https://www.youtube.com/watch?v=TESTarch002"   # 自動で作り直す録画
YT3 = "https://www.youtube.com/watch?v=TESTarch003"   # マークの無い録画
YT4 = "https://www.youtube.com/watch?v=TESTarch004"   # 配信後の全自動(M7)の録画
TITLE = "アーカイブのテスト<b>配信</b>"
ARC_SEC = 420
AUDIO = "0.4*sin(2*PI*t*(400+300*sin(2*PI*0.07*t)))*(0.6+0.4*sin(2*PI*1.3*t))+0.15*(2*random(0)-1)"   # src/home/tests/test_live_archive.py と同じ(照合できる音)
START_SEGS = 30           # 配信中のふりの HLS で最初から見えている本数(録画はアーカイブの 27 秒あたりから始まる)
FRAME_TOL = 0.034
INIT_JS = r"""
(() => {
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
})();
"""
VIDEO = "document.querySelector('#rvHost video')"


def ff(*args):
    from ytt_core import tools
    exe = tools.find_tool("ffmpeg", "YTT_FFMPEG") or "ffmpeg"
    subprocess.run([exe, "-hide_banner", "-nostdin", "-y", "-v", "error"] + list(args), check=True, stdin=subprocess.DEVNULL, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def make_archive(folder):
    """アーカイブの mp4 と、それを -c copy で切った 1 秒ごとの HLS(src_000.ts …)-> (mp4 のパス, [(名前, 長さ)])"""
    os.makedirs(folder, exist_ok=True)
    arc = os.path.join(folder, "archive.mp4")
    ff("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:d=%d" % ARC_SEC, "-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=%d" % (AUDIO, ARC_SEC),
       "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
       "-c:a", "aac", "-b:a", "96k", "-shortest", arc)
    ff("-i", arc, "-c", "copy", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
       "-hls_segment_filename", os.path.join(folder, "src_%03d.ts"), os.path.join(folder, "src.m3u8"))
    out, dur = [], None
    with open(os.path.join(folder, "src.m3u8"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#EXTINF:"):
                dur = float(line[8:].split(",")[0])
            elif line and not line.startswith("#"):
                out.append((line, dur))
    return arc, out


def wait_js(pg, expr, timeout=20000):
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
    tmp = tempfile.mkdtemp(prefix="ytt-live-arch-")
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
    import live_archive as LA  # noqa: E402
    from ytt_core import fsio, normalize, schemas  # noqa: E402
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

    t0 = time.time()
    arc, segs = make_archive(os.path.join(tmp, "src"))
    os.environ["STUDIO_FAKE_MEDIA"] = arc   # スタジオの section(疑似モード)が切る元 = アーカイブ
    print("アーカイブと HLS を作りました(%d 本・%.1f 秒)" % (len(segs), time.time() - t0), flush=True)

    # --- スタジオを入口に取り込む(e2e_live_studio.py と同じ) ---
    out_dir = os.path.join(tmp, "out")
    os.makedirs(out_dir)
    serve.init(os.path.join(tmp, "studio-home"))
    common.set_out_dir(out_dir, lambda: False)
    sys.modules[mount.MOUNTS["studio"]["alias"]] = serve
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

    # --- 録画の部品(本物。direct)と、配信中のふりをする HLS(3 本) ---
    srcs = {}
    for u in (YT1, YT2, YT3):   # YT4(9)は 9 で作る(配信中のふりの HLS がアーカイブの頭のほうから始まるように)
        s = F.LiveServer(os.path.join(tmp, "src"), segs, start=START_SEGS, rate=1.0)
        s.end = False
        srcs[u] = s
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
    rc_local = {"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % rport, "token": rtoken}
    srv.prefs.patch("live", {"enabled": True, "recorders": [rc_local],
                             "detect": {"enabled": False, "sens": "normal", "perHour": 6}, "autoAdopt": {"enabled": False, "waitMin": 5}})   # 0.46.3 から既定オン。この通しはアーカイブの流れだけを見る(配信中の候補が自動で採用されると 9 の記録の数が合わない)
    live = srv.live
    live_logs = []
    live.log = lambda m: live_logs.append("%.1f %s" % (time.time(), m))   # 入口の記録(消したことの 1 行など。失敗したときに出す)
    live.spawn_ok = False
    live.store_dir = os.path.join(tmp, "live")
    live.out_dir = lambda: out_dir
    live.audio = lambda: {"volume": 100, "loudness": None}
    handed = []
    handed_ino = {}   # 渡したときの動画のファイルの id(M7: 本番版に入れ替えてから渡したか)

    class FakeRunner:   # 文字起こしへは偽のまとめて実行
        def start_file(self, path, title="", flow="check", **kw):
            handed.append((path, flow))
            try:
                handed_ino[path] = os.stat(path).st_ino
            except OSError:
                handed_ino[path] = None
            return {"id": "run-%d" % len(handed)}

        def snapshot(self):
            return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち"} for i in range(len(handed))]}
    fake_runner = FakeRunner()
    live.runner = lambda: fake_runner
    live.probe = lambda url: {"status": "is_live", "title": TITLE, "message": ""}
    url_map = {u: s.url for u, s in srcs.items()}
    back = {v: k for k, v in url_map.items()}
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
            body = dict(body, url=url_map.get(body.get("url"), body.get("url")))
        code, d = orig_call(rc, method, path, body, timeout)
        return code, swap(d)
    live.call = call

    # --- yt-dlp の所だけ偽物(アーカイブの用意・開始時刻・窓の音)---
    probe = {"status": "was_live"}
    probes, fetches = [], []
    first = {}   # 動画の id -> 録画の頭の受信時刻(epoch。偽の開始時刻)

    def fake_probe(vid):
        probes.append(vid)
        return {"status": probe["status"], "release": first.get(vid), "timestamp": None, "duration": ARC_SEC, "availability": "public", "message": ""}

    def fake_audio(vid, folder, cancelled=None):   # 配信の丸ごとの音(作業用に m4a で置く = 本物と同じく使い回し・済んだら消す)
        fetches.append(vid)
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, "full.m4a")
        ff("-i", arc, "-vn", "-c:a", "aac", "-b:a", "128k", p)
        return p
    live.archive_opts = {"probe": fake_probe, "audio": fake_audio, "first_delay": 8.0, "interval": 2.0, "poll": 1.0, "retry_sec": 2.0, "step": 0.5}
    live.cleanup_opts = {"interval": 0, "no_mark_sec": 6.0, "keep_sec": 40.0}
    live.watch_sec = 1.0   # 入口の見回り(録画を消す見回り・作り直しの自動)を 1 秒ごとに
    live.start()

    def rec_status(rid):
        return api("GET", "/live/r/local/%s/status" % rid)

    def rec_ids():
        code, d = api("GET", "/live/r/local/list")
        return [r["id"] for r in (d or {}).get("recordings") or []] if code == 200 else None

    def gone_from_list(rid):
        ids = rec_ids()
        return ids is not None and rid not in ids   # 読めないときは「消えた」にしない(空の一覧は消えた)

    def jobs_of(rid):
        return (api("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1] or {}).get("jobs") or []

    def smarks(rid):
        code, d = api("GET", "/studio/api/video?id=%s" % rid)
        return ((d or {}).get("video") or {}).get("marks") if code == 200 else None

    def rec_len(rid):
        code, st = rec_status(rid)
        a, b = LX.iso_epoch((st or {}).get("firstPdt")), LX.iso_epoch((st or {}).get("lastPdt"))
        return (b - a) if a is not None and b is not None else 0.0

    def fmt_t(sec):
        return "%d:%04.1f" % (int(sec // 60), sec % 60)

    def mark(pg, a, b):
        """② の時刻の欄で a 秒 → I、b 秒 → O → 追加(「マークしたらすぐ書き出す」がオンなら自動で書き出す)"""
        pg.evaluate("() => { const v = %s; if (v) v.pause(); }" % VIDEO)
        for t, btn in ((a, "#rvIn"), (b, "#rvOut")):
            pg.fill("#rvNow", fmt_t(t))
            pg.press("#rvNow", "Enter")
            pg.wait_for_timeout(600)
            pg.evaluate("() => document.querySelector('%s').click()" % btn)
            pg.wait_for_timeout(200)
        pg.evaluate("() => document.querySelector('#rvAdd').click()")

    def open_settings(pg):
        pg.click("#btnSettings")
        return wait_js(pg, "() => { const s = document.querySelector('#setLive'); return s && !s.hidden && s.offsetParent && /空き/.test(document.querySelector('#liveFree').textContent); }", 10000)

    def close_settings(pg):
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

    rid1 = rid2 = rid3 = rid4 = None
    errors, not_found = [], []
    deleted_rids = set()
    busy_path = os.path.join(out_dir, "busy", "busy.mp4")
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
            print("ブラウザ: %s" % ("Edge" if edge else "Playwright の chromium"), flush=True)
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
                ctx.add_init_script(INIT_JS)
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append("%s (%s)" % (m.text, (m.location or {}).get("url", ""))) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
                pg.on("response", lambda r: not_found.append(r.url) if r.status == 404 else None)
                pg.goto(studio_url)
                wait_js(pg, "() => !!(window.Studio && Studio.ready)", 20000)
                wait_js(pg, "() => !document.querySelector('#rvOpenForm .rv-openlive').hidden", 10000)

                cx.__dict__.update(locals())   # 場面の関数へ渡す値(この run の中の値。場面が作って、あとで使う値は場面が cx に戻す)
                _scene_settings(cx)
                _scene_record_marks(cx)
                _scene_rebuild_by_hand(cx)
                _scene_chips_and_delete(cx)
                _scene_auto_rebuild(cx)
                _scene_after_stream(cx)
                _scene_errors(cx)
            finally:
                browser.close()
    finally:
        for r in (getattr(cx, k, None) for k in ("rid1", "rid2", "rid3", "rid4")):   # 場面の関数が録画を始めたら cx に入れる
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
        for s in srcs.values():
            s.close()
        live.close()
        srv.shutdown()
        sup.unmount_all()
        srv.server_close()
    if not ok:
        print("--- 入口の記録(リアルタイム切り抜き)---\n" + "\n".join(live_logs[-40:]))
    print("結果: %d 件中 %d 件 OK" % (len(results), sum(results)))
    print("ALL OK" if ok else "SOME FAILED", flush=True)
    return 0 if ok else 1


def _scene_settings(cx):
    """S. 設定の引き出しのチェック 2 つ(本物の入口に保存)"""
    check, close_settings, open_settings, pg, srv = cx.check, cx.close_settings, cx.open_settings, cx.pg, cx.srv
    # ---------------- S. 設定の引き出しのチェック 2 つ(本物の入口に保存)----------------
    check(open_settings(pg), "S 設定の引き出しに「ライブの録画」")
    import prefs as P  # noqa: E402  (home。既定の値)
    defs = P.DEFAULTS["live"]
    check(pg.is_checked("#liveAutoArch") == defs["autoArchive"] and pg.is_checked("#liveAutoDel") == defs["autoDelete"],
          "S チェック 2 つは入口の既定のとおり(自動で作り直す %s・録画を消す %s)" % (defs["autoArchive"], defs["autoDelete"]))
    check("1 日" in (pg.text_content("label[for=liveAutoDel]") or ""), "S チェックの文: %s" % pg.text_content("label[for=liveAutoDel]"))
    for sel, key in (("#liveAutoArch", "autoArchive"), ("#liveAutoDel", "autoDelete")):   # 付ける・外すの両方を本物の入口に保存(最後は外す)
        for want in ([False] if pg.is_checked(sel) else [True, False]):
            pg.click(sel)
            check(wait_for(lambda: srv.prefs.get(["live"])["live"][key] is want, 5), "S %s を%s と live.%s = %s" % (sel, "付ける" if want else "外す", key, want))
    check(wait_js(pg, "() => /自動では消しません/.test(document.querySelector('#liveMsg').textContent)", 3000), "S 外したことの知らせ: %s" % pg.text_content("#liveMsg"))
    close_settings(pg)
    check(open_settings(pg) and not pg.is_checked("#liveAutoArch") and not pg.is_checked("#liveAutoDel"), "S 開き直しても外れたまま(入口から読み直す)")
    close_settings(pg)


def _scene_record_marks(cx):
    """1. 録画 → マーク(速報版)・欠け・欠けのあと"""
    LX, api, check, jobs_of, mark, pg, rec_len, rec_status = cx.LX, cx.api, cx.check, cx.jobs_of, cx.mark, cx.pg, cx.rec_len, cx.rec_status
    srcs = cx.srcs
    # ---------------- 1. 録画 → マーク(速報版)・欠け・欠けのあと ----------------
    pg.click('#steps [data-step="rank"]')   # URL の欄は ① の先頭(0.24.0)
    pg.fill("#qUrls", YT1)
    pg.click("#qAdd")
    check(wait_js(pg, "() => Studio.step === 'review' && !document.querySelector('#rvLiveRec').hidden", 30000), "1 URL を入れると録画が始まり ② で開く")
    code, vs = api("GET", "/studio/api/videos")
    rid1 = cx.rid1 = next((v["id"] for v in (vs or {}).get("videos") or [] if v.get("kind") == "live"), None)
    check(rid1 and LX.REC_RE.match(rid1), "1 録画の id: %s" % rid1)
    check(wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent)", 30000), "1 録画中")
    wait_for(lambda: rec_len(rid1) > 13, 40, 0.5)
    mark(pg, 3.0, 9.0)
    ja = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(jobs_of(rid1)), 90, 0.5)
    check(ja and ja["state"] == "done", "1 マーク A を自動で書き出した(速報版): %s %s" % ((ja or {}).get("state"), (ja or {}).get("error")))
    # 欠け(つなぎ直し)
    srcs[YT1].down = True
    check(wait_for(lambda: (rec_status(rid1)[1] or {}).get("state") == "reconnecting", 30, 0.3), "1 配信が切れると「つなぎ直し中」")
    time.sleep(3)
    srcs[YT1].down = False
    check(wait_for(lambda: (lambda s: s.get("state") == "recording" and s.get("sessions", 0) >= 2)(rec_status(rid1)[1] or {}), 45, 0.5), "1 つなぎ直して録画を続ける")
    code, st = api("GET", "/live/r/local/%s/status?since=0" % rid1)
    base_t = LX.iso_epoch(st["firstPdt"])
    gap = None
    sl = st.get("segmentList") or []
    for x, y in zip(sl, sl[1:]):
        e = LX.iso_epoch(x["pdt"]) + x["dur"]
        if LX.iso_epoch(y["pdt"]) - e > 1.5:
            gap = (e - base_t, LX.iso_epoch(y["pdt"]) - base_t)
    check(gap, "1 録画の受信時刻に欠けがある: %s" % (gap,))
    g0, g1 = gap or (20.0, 25.0)
    wait_for(lambda: rec_len(rid1) > g1 + 11, 40, 0.5)
    mark(pg, g0 - 2.0, g1 + 2.0)   # 欠けをまたぐマーク B
    pg.wait_for_timeout(1500)
    mark(pg, g1 + 4.0, g1 + 8.0)   # 欠けのあとのマーク C
    js1 = wait_for(lambda: (lambda js: len(js) == 3 and all(j["state"] in ("done", "error") for j in js) and js)(jobs_of(rid1)), 120, 0.5) or jobs_of(rid1)
    by = {}
    for j in js1:
        by["A" if abs(j["studio"]["start"] - 3.0) < 0.5 else "B" if j["studio"]["start"] < g0 else "C"] = j
    check(set(by) == {"A", "B", "C"}, "1 マーク 3 つの書き出しのジョブ: %s" % [(j["studio"]["start"], j["state"]) for j in js1])
    jb, jc = by.get("B") or {}, by.get("C") or {}
    check(jb.get("state") == "error" and jb.get("needsArchive") is True, "1 欠けをまたぐマーク B は失敗・要差し替え: %s" % jb.get("error"))
    check(jc.get("state") == "done", "1 欠けのあとのマーク C は書き出せる: %s" % jc.get("error"))
    check(wait_js(pg, "() => /録画に欠けがあります。帯の「アーカイブで作り直す」で作れます/.test(document.querySelector('#rvExpList').textContent)", 10000),
          "1 書き出しの行に「アーカイブで作り直す」の案内")
    speed = {}
    for k in ("A", "C"):
        j = by.get(k) or {}
        if j.get("path") and os.path.isfile(j["path"]):
            speed[k] = (j["path"], os.path.getsize(j["path"]), os.stat(j["path"]).st_ino)   # ファイルの id(入れ替えで変わる・退避しても同じ)
    cx.base_t, cx.g0, cx.speed = base_t, g0, speed


def _scene_rebuild_by_hand(cx):
    """2. 止める → 帯 → 用意がまだ / 3. 押す → 進み具合 → 入れ替え"""
    LA, LX, api, base_t, busy_path, check, first, fsio = cx.LA, cx.LX, cx.api, cx.base_t, cx.busy_path, cx.check, cx.first, cx.fsio
    g0, jobs_of, normalize, out_dir, pg, probe, rid1, schemas = cx.g0, cx.jobs_of, cx.normalize, cx.out_dir, cx.pg, cx.probe, cx.rid1, cx.schemas
    serve, shots, speed, tmp = cx.serve, cx.shots, cx.speed, cx.tmp
    # ---------------- 2. 止める → 帯 → 用意がまだ ----------------
    code, d = api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid1})
    check(code == 200 and d.get("ok"), "2 録画を止める")
    first["TESTarch001"] = base_t
    check(wait_js(pg, "() => /録画は終わりました/.test(document.querySelector('#rvLiveGuide').textContent) && !document.querySelector('#rvArch').hidden", 20000),
          "2 終わった録画の帯に「アーカイブで作り直す」: %s" % pg.text_content("#rvLiveGuide"))
    guide = pg.text_content("#rvLiveGuide") or ""
    check("本番の画質に作り直せます(自動: オフ)" in guide and "録画は消します" not in guide, "2 帯の案内(自動: オフ・消す設定がオフなので「録画は消します」は出さない): %s" % guide)
    check(wait_js(pg, "() => !document.querySelector('#rvArchRun').disabled", 10000), "2 「アーカイブで作り直す」が押せる")
    probe["status"] = "post_live"
    pg.click("#rvArchRun")
    check(wait_js(pg, "() => /処理中/.test(document.querySelector('#rvArchMsg').textContent)", 15000),
          "2 用意がまだ(post_live)→ 入口の 409 の文が帯に出る: %s" % pg.text_content("#rvArchMsg"))
    check(all(not j.get("archive") for j in jobs_of(rid1)), "2 用意がまだのときは何も始めない")

    # ---------------- 3. 押す → 進み具合 → 入れ替え ----------------
    probe["status"] = "was_live"
    seen_msgs, seen_band, busy = [], [], {"cancelled": False}
    stop_poll = threading.Event()
    # 押す前に、スタジオでほかの書き出しを始めておく(スタジオは同時に 1 本だけ = 入口の section は 409 busy になる)。
    # 入口が「待っています」と出したのを見てから、その書き出しを取り消す(確実に重なる)
    os.makedirs(os.path.dirname(busy_path), exist_ok=True)
    sx = serve.exporter
    real_cut = sx.run_ffmpeg

    def held_cut(job, spec, it, base):   # この書き出しだけ、取り消されるまで終わらない(重なりを確実にする。ほかは本物のまま)
        if spec.get("finalPath") == busy_path:
            while not job["cancel"]:
                time.sleep(0.1)
            raise sx.ExportError("取り消しました")
        return real_cut(job, spec, it, base)
    sx.run_ffmpeg = held_cut
    code, bj = api("POST", "/studio/api/live/section", {"videoId": "TESTarch001", "start": 0, "end": 60, "path": busy_path,
                                                        "volume": 100, "precision": "accurate"})
    busy.update(code=code, id=(bj or {}).get("id"))

    def poll_jobs():
        while not stop_poll.is_set():
            for j in jobs_of(rid1):
                a = j.get("archive") or {}
                m = "%s:%s" % (a.get("state"), a.get("message"))
                if a and (not seen_msgs or seen_msgs[-1] != m):
                    seen_msgs.append(m)
                if "スタジオの書き出しが終わるのを待っています" in (a.get("message") or "") and not busy["cancelled"] and busy.get("id"):
                    busy["cancelled"] = True
                    api("POST", "/studio/api/export/cancel", {"id": busy["id"]})
            time.sleep(0.15)
    poller = threading.Thread(target=poll_jobs, daemon=True)
    poller.start()
    pg.click("#rvArchRun")
    shot_taken = False
    deadline = time.time() + 300
    while time.time() < deadline:
        t = pg.text_content("#rvArchMsg") or ""
        if t and (not seen_band or seen_band[-1] != t):
            seen_band.append(t)
        if shots and not shot_taken and "作り直しています" in t:
            pg.evaluate("window.scrollTo(0, 0)")
            pg.screenshot(path=os.path.join(shots, "p4_01_rebuilding.png"))
            shot_taken = True
        if "入れ替えました 3/3" in t:
            break
        time.sleep(0.2)
    stop_poll.set()
    poller.join(5)
    js1 = jobs_of(rid1)
    arcs = {j["id"]: j.get("archive") or {} for j in js1}
    check(all(a.get("state") == "done" for a in arcs.values()) and len(arcs) == 3,
          "3 3 本とも本番版に: %s" % [(a.get("state"), a.get("message")) for a in arcs.values()])
    check(any(re.match(r"^本番版に作り直しています [0-2]/3 本(.+)$", x) for x in seen_band),
          "3 帯の進み具合(n/3 本と段。帯は 5 秒ごとに読み直す): %s" % " → ".join(seen_band[:12]))
    states = [m.split(":", 1)[0] for m in seen_msgs]
    check(all(s in states for s in ("wait", "align", "fetch", "verify", "done")),   # probe は一瞬(偽の yt-dlp)なので見えないことがある
          "3 ジョブの段: 待ち → 確かめ → 照合 → 取得 → 検証 → 本番版(%s)" % "・".join(dict.fromkeys(states)))
    check(seen_band and seen_band[-1].startswith("本番版に入れ替えました 3/3 本"), "3 帯の最後: %s" % (seen_band[-1] if seen_band else ""))
    check(busy["code"] == 200 and any("スタジオの書き出しが終わるのを待っています" in m for m in seen_msgs),
          "3 スタジオがほかの書き出しで 409 busy の間は、失敗にせず待つ(busy の書き出し HTTP %s)" % busy["code"])
    check(busy["cancelled"] and not os.path.exists(busy_path), "3 先に始めた書き出しを取り消すと、待っていた作り直しが進む(書きかけは残らない)")
    code, d = api("POST", "/studio/api/live/section", {"videoId": "TESTarch001", "start": 0, "end": 5, "path": os.path.join(tmp, "outside.mp4")})
    check(code == 400 and "書き出し先" in (d or {}).get("message", ""), "3 section の path は書き出し先の中だけ(本物の検査): %s" % (d or {}).get("message"))
    js1 = jobs_of(rid1)
    by = {}
    for j in js1:
        by["A" if abs(j["studio"]["start"] - 3.0) < 0.5 else "B" if j["studio"]["start"] < g0 else "C"] = j
    for k in ("A", "C"):
        j = by.get(k) or {}
        a = j.get("archive") or {}
        if k not in speed:
            check(False, "3 %s の速報版が無い" % k)
            continue
        path, size0, ino0 = speed[k]
        kept = a.get("keep") or ""
        check(j.get("path") == path and os.path.isfile(path) and os.stat(path).st_ino != ino0,
              "3 %s: 同じ名前のまま本番版に入れ替わった: %s" % (k, os.path.basename(path)))
        check(kept and os.path.isfile(kept) and os.stat(kept).st_ino == ino0 and os.path.getsize(kept) == size0 and os.path.basename(kept) == os.path.basename(path)
              and os.path.basename(os.path.dirname(kept)) == LA.SPEED_DIR and os.path.basename(os.path.dirname(os.path.dirname(kept))) == schemas.WORK_DIR,
              "3 %s: 速報版は 作業用\\速報版\\ に同じ名前で退避: %s" % (k, kept))
        info = normalize.probe(path)
        want = j["studio"]["end"] - j["studio"]["start"]
        check(normalize.is_30fps(info) and abs((info or {}).get("duration", 0) - want) <= LX.LEN_TOL,
              "3 %s: 本番版は 30fps・長さが区間と合う(%.2f 秒 / 区間 %.2f 秒)" % (k, (info or {}).get("duration", 0), want))
        res = a.get("residual")
        check(isinstance(res, (int, float)) and abs(res) <= FRAME_TOL, "3 %s: 速報版との音のずれが 1 コマ以内: %s 秒" % (k, res))
        off = a.get("archiveStart", 0) - j["studio"]["start"]
        check(off > 5, "3 %s: 録画はアーカイブの途中から(ずれ %.2f 秒)= 照合で求めた" % (k, off))
        clip, _w = schemas.load_clip_file(schemas.find_clip_path(path))
        ca = (((clip or {}).get("source") or {}).get("live") or {}).get("archive") or {}
        check(ca.get("videoId") == "TESTarch001" and abs(ca.get("start", -1) - a.get("archiveStart", -2)) < 0.01 and clip["export"]["from"] == "youtube-archive",
              "3 %s: .clip.json の source.live.archive・export.from: %s" % (k, ca))
        check(not a.get("packOld"), "3 %s: Resolve のパックは作っていないので注意は無い" % k)
    b = by.get("B") or {}
    info = normalize.probe(b.get("path") or "") if b.get("path") else None
    check(b.get("state") == "done" and not b.get("needsArchive") and info and normalize.is_30fps(info)
          and abs(info.get("duration", 0) - (b["studio"]["end"] - b["studio"]["start"])) <= LX.LEN_TOL,
          "3 欠けのマーク B は本番版で新しく書き出した(done・30fps・長さ): %s" % ((b.get("path") or "")[-60:]))
    oa, ob = ((by.get("A") or {}).get("archive") or {}).get("offset"), (b.get("archive") or {}).get("offset")
    check(isinstance(oa, (int, float)) and isinstance(ob, (int, float)) and abs(oa - ob) < 0.002,
          "3 欠けのマーク B は、頭と同じセッション(欠けの前)のマーク A のずれを使う: A %s / B %s" % (oa, ob))
    if b.get("manifest"):
        clip = fsio.read_json_file(b["manifest"], 1 << 20)
        check(clip["source"]["kind"] == "live" and clip["source"]["live"]["archive"]["videoId"] == "TESTarch001", "3 B の .clip.json に archive")
    check(not any(os.path.isdir(os.path.join(r_, d_)) for r_, ds, _f in os.walk(out_dir) for d_ in ds if d_ == LA.BUILD_DIR), "3 作りかけのフォルダは残らない")


def _scene_chips_and_delete(cx):
    """4. 本番版の札 / 5. 消す設定オフ → 残る / オン → 消える"""
    api, check, close_settings, deleted_rids, gone_from_list, jobs_of, open_settings, pg = cx.api, cx.check, cx.close_settings, cx.deleted_rids, cx.gone_from_list, cx.jobs_of, cx.open_settings, cx.pg
    rec_ids, rfolder, rid1, shots, smarks, srv, studio_url = cx.rec_ids, cx.rfolder, cx.rid1, cx.shots, cx.smarks, cx.srv, cx.studio_url
    # ---------------- 4. 本番版の札 ----------------
    ms = wait_for(lambda: (lambda m: m and len([x for x in m if x.get("archived")]) == 3 and m)(smarks(rid1)), 30, 0.5)
    check(ms and all(x["status"] == "exported" and x.get("archived") for x in ms),
          "4 スタジオのマーク 3 つが書き出し済み + 本番版(/api/video の archived): %s" % [(x.get("status"), x.get("archived")) for x in (smarks(rid1) or [])])
    check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row .rv-chip.arch').length === 3", 15000), "4 ② のマークの行に「本番版」の札が 3 つ")
    code, vs = api("GET", "/studio/api/videos")
    row = next((v for v in (vs or {}).get("videos") or [] if v["id"] == rid1), {})
    check(row.get("archived") == 3, "4 一覧の行の本番版の数: %s" % row.get("archived"))
    if shots:
        pg.evaluate("window.scrollTo(0, 0)")
        pg.screenshot(path=os.path.join(shots, "p4_02_archived_chips.png"))
        pg.click('#rvJump [data-jump="export"]')
        pg.wait_for_timeout(500)
        pg.screenshot(path=os.path.join(shots, "p4_02b_export_rows.png"))
        pg.click("#rvExpClose")
        pg.wait_for_timeout(300)

    # ---------------- 5. 消す設定オフ → 残る / オン → 消える ----------------
    time.sleep(3)   # 入口の見回り(1 秒ごと)が何回か回る
    check(rid1 in (rec_ids() or []) and os.path.isdir(os.path.join(rfolder, rid1)), "5 「録画を消す」がオフの間は、入れ替えが済んでも録画は残る")
    check(open_settings(pg), "5 設定を開く")
    pg.click("#liveAutoDel")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["autoDelete"] is True, 5), "5 「録画を消す」を付けると live.autoDelete = true")
    close_settings(pg)
    gone = wait_for(lambda: gone_from_list(rid1), 30, 0.5)
    if gone:
        deleted_rids.add(rid1)
    check(gone and not os.path.exists(os.path.join(rfolder, rid1)), "5 入れ替えが全部済んだ録画を消した(録画元の一覧と置き場所から): 一覧 %s・フォルダ %s"
          % (rid1 in (rec_ids() or []), os.listdir(os.path.join(rfolder, rid1)) if os.path.isdir(os.path.join(rfolder, rid1)) else "なし"))
    check(all(j.get("recordingDeleted") for j in jobs_of(rid1)), "5 ジョブに消した印 recordingDeleted")
    check(wait_js(pg, "() => document.querySelector('#rvLiveGuide').textContent.includes('録画は消しました(本番版に入れ替え済み)。マークと本番版はそのまま使えます')", 40000),
          "5 帯が「録画は消しました…」: %s" % pg.text_content("#rvLiveGuide"))
    check(pg.text_content("#rvRecState") == "録画を消しました" and "err" not in (pg.get_attribute("#rvRecState", "class") or ""), "5 状態の札はエラーにしない: %s" % pg.text_content("#rvRecState"))
    check(pg.evaluate("() => { const n = document.querySelector('#rvNotice'); return !n.hidden && /録画は消しました/.test(n.textContent) && !n.querySelector('[data-act=ytretry]'); }"),
          "5 プレーヤーの所にも同じ案内(「もう一度試す」は出さない)")
    check(pg.is_hidden("#rvArch") and pg.is_hidden('label[for="rvAutoExp"]'), "5 「アーカイブで作り直す」「マークしたらすぐ書き出す」は出さない")
    check(len(smarks(rid1) or []) == 3 and all(os.path.isfile(j["path"]) for j in jobs_of(rid1)), "5 マークと本番版はそのまま")
    if shots:
        pg.evaluate("window.scrollTo(0, 0)")
        pg.screenshot(path=os.path.join(shots, "p4_03_recording_deleted.png"))
    pg.goto(studio_url + "?video=" + rid1)
    check(wait_js(pg, "() => /録画は消しました/.test(document.querySelector('#rvLiveGuide').textContent) && !document.querySelector('#rvNotice').hidden", 20000)
          and "見つかりません" not in (pg.text_content("#rvRecState") or ""), "5 開き直しても「録画は消しました」(「録画が見つかりません」にしない)")
    check(pg.evaluate("() => document.querySelectorAll('#rvList .rv-chip.arch').length") == 3, "5 開き直しても本番版の札")
    code, d = api("POST", "/live/r/local/%s/delete" % rid1, {})
    check(code == 404, "5 画面からの中継では録画を消せない(POST …/delete は 404): HTTP %s" % code)


def _scene_auto_rebuild(cx):
    """6. 自動: 録画が終わる → 作り直す → 消す / 7. マークの無い録画 / 退避した速報版"""
    LX, api, check, close_settings, deleted_rids, fetches, first, gone_from_list = cx.LX, cx.api, cx.check, cx.close_settings, cx.deleted_rids, cx.fetches, cx.first, cx.gone_from_list
    jobs_of, mark, open_settings, pg, probes, rec_ids, rec_len, rec_status = cx.jobs_of, cx.mark, cx.open_settings, cx.pg, cx.probes, cx.rec_ids, cx.rec_len, cx.rec_status
    rfolder, rid1, smarks, srv = cx.rfolder, cx.rid1, cx.smarks, cx.srv
    # ---------------- 6. 自動: 録画が終わる → 作り直す → 消す ----------------
    check(open_settings(pg), "6 設定を開く")
    pg.click("#liveAutoArch")
    check(wait_for(lambda: srv.prefs.get(["live"])["live"]["autoArchive"] is True, 5), "6 「自動で本番版に作り直す」を付けると live.autoArchive = true")
    close_settings(pg)
    pg.click('#steps [data-step="rank"]')   # URL の欄は ① の先頭(0.24.0)
    pg.fill("#qUrls", YT2)
    pg.click("#qAdd")
    check(wait_js(pg, "() => Studio.step === 'review' && !document.querySelector('#rvLiveRec').hidden && /録画中/.test(document.querySelector('#rvRecState').textContent)", 40000),
          "6 2 本目の録画が始まる")
    code, vs = api("GET", "/studio/api/videos")
    rid2 = cx.rid2 = next((v["id"] for v in (vs or {}).get("videos") or [] if v.get("kind") == "live" and v["id"] != rid1), None)
    wait_for(lambda: rec_len(rid2) > 12, 40, 0.5)
    mark(pg, 3.0, 8.0)
    jd = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(jobs_of(rid2)), 90, 0.5)
    check(jd and jd["state"] == "done", "6 マーク D を書き出した(速報版)")
    d_path, d_ino = (jd or {}).get("path"), os.stat(jd["path"]).st_ino if jd and jd.get("path") else 0
    first["TESTarch002"] = LX.iso_epoch((rec_status(rid2)[1] or {}).get("firstPdt"))
    guide = pg.text_content("#rvLiveGuide") or ""
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid2})
    check(wait_js(pg, "() => /本番版に入れ替えたら、録画は消します/.test(document.querySelector('#rvLiveGuide').textContent)", 20000),
          "6 終わった録画の帯の案内に「本番版に入れ替えたら、録画は消します」: %s" % pg.text_content("#rvLiveGuide"))
    stopped_at = time.time()
    jd = wait_for(lambda: (lambda js: js and (js[0].get("archive") or {}).get("state") in ("done", "error") and js[0])(jobs_of(rid2)), 180, 0.5)
    a = (jd or {}).get("archive") or {}
    check(a.get("state") == "done" and a.get("auto") is True, "6 録画が終わって(縮めた)30 分後に、見回りが自動で本番版に作り直した(%.0f 秒後): %s %s"
          % (time.time() - stopped_at, a.get("state"), a.get("message")))
    check(d_path and os.path.isfile(d_path) and os.stat(d_path).st_ino != d_ino and os.path.isfile(a.get("keep") or ""), "6 同じ名前で入れ替え・速報版は退避")
    gone2 = wait_for(lambda: gone_from_list(rid2), 30, 0.5)
    if gone2:
        deleted_rids.add(rid2)
    check(gone2 and not os.path.exists(os.path.join(rfolder, rid2)), "6 入れ替えが全部済んだので、録画を消した(自動)")
    check(wait_js(pg, "() => /録画は消しました/.test(document.querySelector('#rvLiveGuide').textContent)", 40000), "6 開いている画面の帯も「録画は消しました」")
    check(len(probes) >= 2 and fetches, "6 アーカイブの用意を確かめて(偽の yt-dlp %d 回)、窓の音を取った(%d 回)" % (len(probes), len(fetches)))

    # ---------------- 7. マークの無い録画 / 退避した速報版 ----------------
    code, d = api("POST", "/live/api/begin", {"url": YT3})
    rid3 = cx.rid3 = ((d or {}).get("recording") or {}).get("id")
    code, _v = api("POST", "/studio/api/videos/open", {"kind": "live", "recorder": "local", "recording": rid3, "url": YT3, "title": "マークなし"})
    check(rid3 and code == 200, "7 マークの無い録画を始めてスタジオに登録: %s" % rid3)
    wait_for(lambda: rec_len(rid3) > 3, 30, 0.5)
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid3})
    time.sleep(2)
    check(rid3 in (rec_ids() or []) and smarks(rid3) == [], "7 終わってすぐ(縮めた 1 日の前)は消さない")
    gone3 = wait_for(lambda: gone_from_list(rid3), 40, 0.5)
    if gone3:
        deleted_rids.add(rid3)
    check(gone3 and api("GET", "/studio/api/video?id=%s" % rid3)[0] == 404, "7 マークが無いまま(縮めた)1 日たった録画とスタジオの行を消した")
    keeps = [(j.get("archive") or {}).get("keep") for j in jobs_of(rid1) + jobs_of(rid2) if (j.get("archive") or {}).get("keep")]
    done_keeps = wait_for(lambda: (lambda js: all((j.get("archive") or {}).get("keepDeleted") for j in js if (j.get("archive") or {}).get("keep")) and js)(
        jobs_of(rid1) + jobs_of(rid2)), 90, 1.0)
    check(done_keeps and keeps and not any(os.path.exists(k) for k in keeps), "7 退避した速報版は入れ替えから(縮めた)7 日で消した: %d 本" % len(keeps))
    check(all(os.path.isfile(j["path"]) for j in jobs_of(rid1) + jobs_of(rid2)), "7 本番版はそのまま")


def _scene_after_stream(cx):
    """9. 配信後の全自動(M7): 人は触らない"""
    F, LX, api, back, check, deleted_rids, first, gone_from_list = cx.F, cx.LX, cx.api, cx.back, cx.check, cx.deleted_rids, cx.first, cx.gone_from_list
    handed, handed_ino, jobs_of, live, rec_ids, rec_len, rec_status, schemas = cx.handed, cx.handed_ino, cx.jobs_of, cx.live, cx.rec_ids, cx.rec_len, cx.rec_status, cx.schemas
    segs, srcs, srv, tmp, url_map = cx.segs, cx.srcs, cx.srv, cx.tmp, cx.url_map
    pg, studio_url = cx.pg, cx.studio_url
    # ---------------- 9. 配信後の全自動(M7): 人は触らない ----------------
    code, _d = api("PUT", "/studio/api/settings", {"section": "analyze", "value": {"count": 30, "length": 10, "headSec": 0}})   # 短いアーカイブでも候補が録画の範囲に入るように
    check(code == 200, "9 スタジオの解析の設定(候補 30・長さ 10 秒・冒頭の減点なし): HTTP %s" % code)
    chat = os.path.join(tmp, "chat.jsonl")   # 偽のチャット(25 秒ごとに 4 秒の盛り上がり = アーカイブの全体に 25 秒おきの山。合成の音だけでは山が立たない)
    rnd = __import__("random").Random(1)
    with open(chat, "w", encoding="utf-8") as f:
        for t in range(ARC_SEC):
            n = 2 + rnd.randint(0, 2) + (40 if t % 25 < 4 else 0)
            for k in range(n):
                f.write(json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(t * 1000 + k * 10), "actions": [{"addChatItemAction": {
                    "item": {"liveChatTextMessageRenderer": {"message": {"runs": [{"text": "草" if k % 3 == 0 else "はい"}]}}}}}]}}) + chr(10))
    os.environ["STUDIO_FAKE_CHAT"] = chat
    v = srv.prefs.patch("live", {"autoAfterStream": True, "afterStreamPerHour": 30})
    check(v["autoAfterStream"] is True and v["afterStreamPerHour"] == 30, "9 「配信が終わったら、アーカイブの解析で自動で切り抜く」をオン(live.autoAfterStream)")
    live.archiver.per_hour = lambda: 200   # テストの録画は 1 分ほど = 1 時間あたりを大きくして N を数本に(本物は設定の値)
    n_handed = len(handed)
    s4 = F.LiveServer(os.path.join(tmp, "src"), segs, start=START_SEGS, rate=1.0)
    s4.end = False
    srcs[YT4] = s4
    url_map[YT4], back[s4.url] = s4.url, YT4
    code, d = api("POST", "/live/api/begin", {"url": YT4})
    rid4 = cx.rid4 = ((d or {}).get("recording") or {}).get("id")
    check(code == 200 and rid4, "9 4 本目の録画(人はマークしない): %s" % rid4)
    wait_for(lambda: rec_len(rid4) > 2, 30, 0.5)
    # 見るだけ(マークしない): スタジオに登録して ② で開いておく(採用のときに入口が同じ登録をする = 結果は同じ)。帯の進み具合の 1 行を見る
    api("POST", "/studio/api/videos/open", {"kind": "live", "recorder": "local", "recording": rid4, "url": YT4, "title": "配信後の全自動"})
    pg.goto(studio_url + "?video=" + rid4)
    wait_js(pg, "() => !document.querySelector('#rvLiveRec').hidden", 20000)
    first["TESTarch004"] = LX.iso_epoch((rec_status(rid4)[1] or {}).get("firstPdt"))
    wait_for(lambda: rec_len(rid4) > 75, 120, 0.5)
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid4})
    stopped_at = time.time()

    def after_state():
        return ((api("GET", "/live/api/exports?recorder=local&recording=%s" % rid4)[1] or {}).get("archiveInfo") or {}).get("afterStream") or {}
    seen_after, band = [], []

    def watch():
        a = after_state()
        s = "%s:%s" % (a.get("state"), a.get("message"))
        if a and (not seen_after or seen_after[-1] != s):
            seen_after.append(s)
        t = pg.evaluate("() => { const e = document.querySelector('#rvAfterStream'); return e && !e.hidden ? e.textContent : ''; }")
        if t and (not band or band[-1] != t):
            band.append(t)
        return a if a.get("state") in ("done", "none", "error") else None
    time.sleep(12)   # 縮めた「マークの無い録画は 1 日で消す」(6 秒)を過ぎても、自動の切り抜きが済むまで消さない
    check(rid4 in (rec_ids() or []), "9 マークが無いまま(縮めた)1 日を過ぎても、配信後の自動の切り抜きが済むまで録画を消さない")
    got = wait_for(watch, 420, 1.0)
    check(got and got.get("state") == "done", "9 録画が終わって %.0f 秒で、人が触らずに配信後の自動の切り抜きが済んだ: %s / %s"
          % (time.time() - stopped_at, (got or {}).get("message"), " → ".join(seen_after[-8:])))
    check(any(x.startswith("analyze:") for x in seen_after) and any(x.startswith("export:") for x in seen_after),
          "9 段: アーカイブを解析 → 書き出し → 本番版 → パック(%s)" % "・".join(dict.fromkeys(x.split(":", 1)[0] for x in seen_after)))
    done_band = wait_js(pg, "() => { const e = document.querySelector('#rvAfterStream'), t = e.textContent;"
                            " return !e.hidden && t.startsWith('配信後の自動の切り抜き: 済み') && t.includes('本のうち 書き出し'); }", 40000)
    check(done_band and all(t.startswith("配信後の自動の切り抜き: ") for t in band),
          "9 スタジオの LIVE の帯に進み具合の 1 行(archiveInfo.afterStream.text。途中 %d 通り → %s)"
          % (len(band), pg.text_content("#rvAfterStream")))
    js4 = jobs_of(rid4)
    check(len(js4) >= 2 and len(js4) == (got or {}).get("jobs"), "9 上位 N を採用した: %d 本(N = %s)" % (len(js4), (got or {}).get("n")))
    check(js4 and all(j.get("origin") == "archive" and j.get("holdFor") == "archive" and j["state"] == "done" for j in js4),
          "9 採用の出どころ archive・本番版を待ってから渡す: %s" % [(j.get("origin"), j.get("state"), j.get("error")) for j in js4])
    check(js4 and all((j.get("archive") or {}).get("state") == "done" and (j.get("archive") or {}).get("auto") for j in js4),
          "9 全部を本番版に入れ替えた(「自動で本番版に作り直す」の設定に関係なく): %s" % [(j.get("archive") or {}).get("message") for j in js4])
    h4 = handed[n_handed:]
    check(js4 and sorted(p for p, _f in h4) == sorted(j["path"] for j in js4) and all(f == "auto" for _p, f in h4) and all(j.get("runId") for j in js4),
          "9 N 本ともまとめて実行へ「文字起こし → パック」(after = auto)で渡した: %s" % [(os.path.basename(p), f) for p, f in h4])
    check(js4 and all(handed_ino.get(j["path"]) == os.stat(j["path"]).st_ino and os.path.isfile((j.get("archive") or {}).get("keep") or "") for j in js4),
          "9 渡したのは本番版に入れ替えたあと(速報版は退避)= パックは本番版")
    ok_clips = bool(js4)
    for j in js4:
        clip, _w = schemas.load_clip_file(schemas.find_clip_path(j["path"]))
        live_src = ((clip or {}).get("source") or {}).get("live") or {}
        ok_clips = ok_clips and live_src.get("origin") == "archive" and (clip or {}).get("mark", {}).get("src") == "auto" \
            and (live_src.get("archive") or {}).get("videoId") == "TESTarch004"
    check(ok_clips, "9 .clip.json に origin archive・mark.src auto・本番版(source.live.archive)")
    try:
        with open(os.path.join(live.store_dir, LX.FEEDBACK), encoding="utf-8") as f:
            fb = [json.loads(x) for x in f if x.strip()]
    except OSError:
        fb = []
    fb4 = [x for x in fb if x.get("recording") == rid4]
    check(js4 and len(fb4) == len(js4) and all(x["origin"] == "archive" and x["human"] is False and x["verdict"] is None for x in fb4),
          "9 live_feedback.jsonl に採用の記録(自動は「良い」に数えない): %d 行" % len(fb4))
    code, av = api("GET", "/studio/api/video?id=TESTarch004")
    check(code == 200 and ((av or {}).get("video") or {}).get("analysis"), "9 アーカイブはスタジオの今の解析にかけた(YouTube の配信 TESTarch004)")
    gone4 = wait_for(lambda: gone_from_list(rid4), 40, 0.5)
    if gone4:
        deleted_rids.add(rid4)
    check(gone4, "9 自動の切り抜きが済み、全部入れ替わったので録画を消した")
    lf = ((api("GET", "/api/health")[1] or {}).get("live") or {})
    check(lf.get("disk") and lf["disk"].get("state") in ("ok", "warn", "low") and lf["disk"].get("rows"), "9 「調子」に空き容量(M4): %s"
          % [(r.get("label"), r.get("state")) for r in (lf.get("disk") or {}).get("rows") or []])


def _scene_errors(cx):
    """8. エラー(コンソール・404・CSP)"""
    check, deleted_rids, errors, not_found, pg, rfolder, rid1, rid2 = cx.check, cx.deleted_rids, cx.errors, cx.not_found, cx.pg, cx.rfolder, cx.rid1, cx.rid2
    rid3, rid4 = cx.rid3, cx.rid4
    # ---------------- 8. エラー ----------------
    # 想定内: 用意がまだのときの POST ../live/api/archive の 409(帯に入口の文を出す。2 の確認)
    # 想定内: 消した録画の状態・再生リスト・セグメントの 404(録画を消した = 5・6。画面はこれを見て「録画は消しました」にする)
    # 想定内: Edge は /favicon.ico を自分で読みに行く
    pg.wait_for_timeout(500)   # 画面を触らなかった間(9)のコンソール・応答のできごとを、選り分ける前に受け取る(Playwright は次の操作のときに届ける)
    deleted_rids.update(r for r in (rid1, rid2, rid3, rid4) if r and not os.path.exists(os.path.join(rfolder, r)))

    def expected(x):
        if "/favicon.ico" in x:
            return True
        if "409" in x and "/live/api/archive" in x:
            return True
        return "404" in x and any("/live/r/local/%s/" % r in x for r in deleted_rids) or (x.startswith("http") and any("/live/r/local/%s/" % r in x for r in deleted_rids))
    errors[:] = [x for x in errors if not expected(x)]
    not_found[:] = [x for x in not_found if not expected(x)]
    csp = pg.evaluate("() => window.__csp")
    check(not csp, "8 CSP の違反なし: %s" % csp)
    check(not errors, "8 コンソールのエラーなし: %s" % errors[:6])
    check(not not_found, "8 404 なし: %s" % not_found[:6])


if __name__ == "__main__":
    sys.exit(main())
