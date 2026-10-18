#!/usr/bin/env python3
"""リアルタイム切り抜き LD-1(録画に無い区間だけをアーカイブから書き出す・アーカイブ化を確かめて録画をごみ箱へ移す。notes:plan/line-d-live-clipping.md の 0-9)の通しの確認。
入口にスタジオを取り込み、録画の部品を別のプロセスで立て、ブラウザでホームの「新しい案件」(/#new)の URL の欄から録画を始め、
案件の画面の候補のパネル(/cases?c=<録画 id>#cand。panels/cand.js がスタジオの review.js と LivePlayer を載せる)を操作する。本物の YouTube には繋がない。
(RS8 C4 でスタジオの画面のページと、その ⚙ の「ライブの録画」の欄を消した。案件の画面の帯は開いたときに入口の設定 live.autoDelete を読む。
 LD-1 で「速報版を本番版に入れ替える(P4)」と設定 live.autoArchive は無くなった = アーカイブから書き出すのは録画に無い区間だけで、いつも自動)

    py -3.12 src/app/tests/e2e_live_archive.py                 # 確かめる(終了コード 0 = すべて OK)
    py -3.12 src/app/tests/e2e_live_archive.py --shots DIR     # あわせてスクリーンショットを DIR に残す
    py -3.12 src/app/tests/e2e_live_archive.py --chromium      # Edge があっても Playwright の chromium で

作り(e2e_live_studio.py と同じ形。全部一時フォルダ):
  - 「アーカイブ」= ffmpeg の lavfi で作った mp4(testsrc2 の 30fps + 時間で変わる音。照合できる音)。それを -c copy で 1 秒ごとの HLS にして、
    手元の HTTP サーバーで配信中のように出す(hls_fixture.LiveServer。最初から 30 本見えている = 録画はアーカイブの途中から始まる = ずれは 0 でない)
  - 録画の部品(src/pipeline/ingest/recorder.py)は本物を --source direct で。入口 → 録画元の要求だけ、YouTube の形の URL を手元の HLS の URL に読み替える
  - yt-dlp の所だけ偽物(Live.archive_opts): 用意の確認 = was_live(手で post_live にもする)・開始時刻 = 録画の頭(firstPdt)・
    窓の音 = アーカイブの mp4 から ffmpeg で切る。照合は本物(src/pipeline/ingest/live_align_worker.py)
  - スタジオの区間の書き出し(部品 exporter.build_section_spec・_run_section)は本物: 疑似モード(STUDIO_FAKE=1)で STUDIO_FAKE_MEDIA = アーカイブの mp4 を切る
    (入口 → スタジオの API の呼び方・409 busy の待ち・path の検査が本物で通る)
  - 時間は縮める: アーカイブからの自動の書き出し(録画が終わって 8 秒・確かめる間隔 2 秒)・録画を消す見回り(毎回)・マークの無い録画(6 秒)

確かめること:
  S  「録画を消す」(live.autoDelete)は入口の既定(オン)のとおり・外すと入口の設定に残る(live.autoArchive は設定に無い)
     (スタジオの ⚙ の「ライブの録画」の確かめは、その引き出しと一緒に消えた)
  1  /#new の URL → /cases?c=<録画 id>#cand → 候補のパネルでマーク(自動の書き出し)→ 録画から書き出した切り抜き(done)/ 欠け(つなぎ直しの間をまたぐマーク)→ 失敗・要アーカイブ / 欠けのあとのマーク
  2  止める → 帯の案内・「アーカイブから書き出す」/ 用意がまだ(post_live)→ 409 の文が帯に出る
  3  押す → 帯の進み具合(n/1 本・段)・スタジオが 409 busy の間は待つ → 対象は欠けのマーク B だけ(アーカイブから書き出して done・30fps・長さ・
     clip.json の source.live.archive・export.from youtube-archive・ずれはマークの手前の録画の音で照合)。A・C は録画から書き出したまま(ファイルの ino も変わらない)
  4  B だけに「アーカイブ」の札(スタジオの /api/video の archived・候補のパネルの行)
  5  「録画を消す」がオフの間は録画が残る → オンにすると、アーカイブ化を確かめて録画をごみ箱(<録画の置き場所>\\ごみ箱\\<日付>\\録画\\<録画 id>)へ移し、
     帯とプレーヤーの所が LIVE_DELETED の文(開き直しても同じ)・マークと切り抜きは残る
  6  録画が終わる → アーカイブから書き出すものが無いので作り直しは起きない → アーカイブ化を確かめて録画を自動でごみ箱へ
  7  マークの無い録画: 終わって(縮めた)1 日 → 録画とスタジオの行が消える
  9  配信後の全自動(線 D の M7。live.autoAfterStream): 人がマークしない録画 → 終わる → 録画とアーカイブの時刻を照合 → アーカイブを偽の解析(STUDIO_FAKE)
     → 上位 N を採用(origin archive)→ アーカイブから書き出し → まとめて実行へ「文字起こし → パック」で N 本渡る(人は触らない)・
     自動の切り抜きが済むまで録画を消さない(マークの無い録画の 1 日(縮めた)を過ぎても)→ 済んだら消す(ごみ箱)・
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

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)。main で一時フォルダにする
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
STUDIO = os.path.join(REPO, "studio")
sys.path.insert(0, STUDIO)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "pipeline", "ingest", "tests"))
os.environ["STUDIO_FAKE"] = "1"

YT1 = "https://www.youtube.com/watch?v=TESTarch001"   # 手で作り直す録画
YT2 = "https://www.youtube.com/watch?v=TESTarch002"   # 自動で作り直す録画
YT3 = "https://www.youtube.com/watch?v=TESTarch003"   # マークの無い録画
YT4 = "https://www.youtube.com/watch?v=TESTarch004"   # 配信後の全自動(M7)の録画
TITLE = "アーカイブのテスト<b>配信</b>"
ARC_SEC = 420
AUDIO = "0.4*sin(2*PI*t*(400+300*sin(2*PI*0.07*t)))*(0.6+0.4*sin(2*PI*1.3*t))+0.15*(2*random(0)-1)"   # src/flow/tests/test_live_archive.py と同じ(照合できる音)
START_SEGS = 30           # 配信中のふりの HLS で最初から見えている本数(録画はアーカイブの 27 秒あたりから始まる)
FRAME_TOL = 0.034
INIT_JS = r"""
(() => {
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
})();
"""
VIDEO = "document.querySelector('#rvHost video')"
# 案件の画面の候補のパネル(panels/cand.js)に録画が開いて、LIVE の帯(録画の行)が出ている
CAND_LIVE = ("() => !!window.CasesShell && CasesShell.state().panel === 'cand' && !!document.querySelector('#csPane .cd-panel #rvLiveRec')"
             " && !document.querySelector('#rvLiveRec').hidden")
# ホームの「新しい案件」の引き出し(/#new)が開いて、URL の欄(スタジオ ① の queue.js)ができている
NEW_READY = "() => !document.getElementById('newDrawer').hidden && !!document.querySelector('#newDrawer #qUrls')"


def ff(*args):
    from ytt import tools
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


def clip_len(job):
    """書き出したジョブの動画の長さの見込み: 余白つき(LD-2f。ジョブの clip {from, to})ならその長さ、無ければマークの長さ"""
    from flow import live_export as LX   # noqa: E402  (起動の順で src を sys.path に足したあと)
    c = job.get("clip") or {}
    if c.get("from") and c.get("to"):
        return LX.iso_epoch(c["to"]) - LX.iso_epoch(c["from"])
    return job["studio"]["end"] - job["studio"]["start"]


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
    import startup  # noqa: E402  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
    from ytt import studio_env  # noqa: E402
    import serve   # noqa: E402  (studio)
    from app import server as L  # noqa: E402
    from app import mount  # noqa: E402
    import hls_fixture as F  # noqa: E402
    from flow import live_export as LX  # noqa: E402
    from flow import live_archive as LA  # noqa: E402
    from ytt import fsio, normalize, schemas, trashbin  # noqa: E402
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
    studio_env.set_out_dir(out_dir, lambda: False)
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

    def cases_url(r):
        return base + "/cases?c=%s#cand" % r

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
    rproc = subprocess.Popen([sys.executable, os.path.join(REPO, "pipeline", "ingest", "recorder.py"), "--port", str(rport), "--data-dir", rdata,
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
        def submit(self, env, spec=None, accept=False):   # ② の口(RS7-2 G2b: 書き出しの受け渡しは封筒 kind file + 束)= 以前の start_file の形で覚える
            from flow import run as run_mod
            run = run_mod.Run.from_envelope(env, spec)
            kw = {k: getattr(run, k) for k in ("cut", "engine", "model") if getattr(run, k)}
            return self.start_file(run.source_path, run.title, "auto" if run.mode == "file_auto" else "check", streamer=run.streamer, **kw)

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

    def fake_probe(vid):   # duration: release + ARC_SEC(420)が録画の終わり − 900 秒より後(アーカイブ化を確かめる条件。録画は 1〜2 分)になる大きさ
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

    def begin_from_home(pg, url):
        """ホームの「新しい案件」(/#new)の URL の欄 →「解析に追加」→ 録画が始まり、案件の画面の候補(/cases?c=<録画 id>#cand)へ移る。-> 移れたか"""
        pg.goto(base + "/#new")
        wait_js(pg, NEW_READY, 25000)
        pg.fill("#qUrls", url)
        pg.click("#qAdd")
        return wait_js(pg, CAND_LIVE, 40000)

    def here(pg):
        return pg.evaluate("() => location.pathname + location.search + location.hash")

    rid1 = rid2 = rid3 = rid4 = None
    errors, not_found = [], []
    deleted_rids = set()
    busy_vid = "TESTbusy001"   # 「ほかの書き出し」用に開くスタジオの YouTube の行(11 字の videoId)
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
    """S. 「録画を消す」(入口の設定)"""
    check, srv = cx.check, cx.srv
    # ---------------- S. 「録画を消す」(入口の設定)----------------
    # 0.25.0 から欄は設定の画面(prefs)。スタジオの ⚙ の「ライブの録画」(表示と「設定の画面で変える」のリンク)は C4 でスタジオの画面と一緒に消えた
    # (案件の画面の ⚙ はテーマなどだけ)ので、「⚙ に出る・開き直すと帯へ伝わる」の確かめは外した。帯は録画を開いたときに入口の設定を読む(1・6 で見る)
    from app import prefs as P  # noqa: E402  (home。既定の値)
    defs = P.DEFAULTS["live"]
    lv = srv.prefs.get(["live"])["live"]
    check("autoArchive" not in defs and "autoArchive" not in lv, "S 「自動で本番版に作り直す」(live.autoArchive)は設定に無い")
    check(lv["autoDelete"] == defs["autoDelete"] and lv["autoDelete"] is True, "S 「録画を消す」は入口の既定のとおり(オン): %s" % lv["autoDelete"])
    srv.prefs.patch("live", {"autoDelete": False})   # 外す(この e2e の録画で自動の削除を動かさない所から始める)
    check(srv.prefs.get(["live"])["live"]["autoDelete"] is False, "S 外すと入口の設定に残る")


def _scene_record_marks(cx):
    """1. 録画 → マーク(録画から書き出し)・欠け・欠けのあと"""
    LX, api, begin_from_home, check, here, jobs_of, mark, pg = cx.LX, cx.api, cx.begin_from_home, cx.check, cx.here, cx.jobs_of, cx.mark, cx.pg
    rec_len, rec_status, srcs = cx.rec_len, cx.rec_status, cx.srcs
    # ---------------- 1. 録画 → マーク(録画から書き出し)・欠け・欠けのあと ----------------
    check(begin_from_home(pg, YT1), "1 ホームの /#new で URL を入れると録画が始まり、案件の画面の候補で開く")
    code, vs = api("GET", "/studio/api/videos")
    rid1 = cx.rid1 = next((v["id"] for v in (vs or {}).get("videos") or [] if v.get("kind") == "live"), None)
    check(rid1 and LX.REC_RE.match(rid1), "1 録画の id: %s" % rid1)
    check(here(pg) == "/cases?c=%s#cand" % rid1, "1 移った先は /cases?c=<録画 id>#cand: %s" % here(pg))
    check(wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent)", 30000), "1 録画中")
    wait_for(lambda: rec_len(rid1) > 13, 40, 0.5)
    mark(pg, 3.0, 9.0)
    ja = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(jobs_of(rid1)), 90, 0.5)
    check(ja and ja["state"] == "done", "1 マーク A を自動で書き出した(録画から):%s %s" % ((ja or {}).get("state"), (ja or {}).get("error")))
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
    check(wait_js(pg, "() => /録画に欠けがあります。帯の「アーカイブから書き出す」で作れます/.test(document.querySelector('#rvExpList').textContent)", 10000),
          "1 書き出しの行に「アーカイブから書き出す」の案内")
    speed = {}
    for k in ("A", "C"):
        j = by.get(k) or {}
        if j.get("path") and os.path.isfile(j["path"]):
            speed[k] = (j["path"], os.path.getsize(j["path"]), os.stat(j["path"]).st_ino)   # ファイルの id(アーカイブから書き出しても変わらない)
    cx.base_t, cx.g0, cx.speed = base_t, g0, speed


def _scene_rebuild_by_hand(cx):
    """2. 止める → 帯 → 用意がまだ / 3. 押す → 進み具合 → アーカイブから書き出し(欠けのマークだけ)"""
    LA, LX, api, base_t, busy_vid, check, first, fsio = cx.LA, cx.LX, cx.api, cx.base_t, cx.busy_vid, cx.check, cx.first, cx.fsio
    g0, jobs_of, normalize, out_dir, pg, probe, rid1, schemas = cx.g0, cx.jobs_of, cx.normalize, cx.out_dir, cx.pg, cx.probe, cx.rid1, cx.schemas
    serve, shots, speed, tmp = cx.serve, cx.shots, cx.speed, cx.tmp
    # ---------------- 2. 止める → 帯 → 用意がまだ ----------------
    code, d = api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid1})
    check(code == 200 and d.get("ok"), "2 録画を止める")
    first["TESTarch001"] = base_t
    check(wait_js(pg, "() => /録画は終わりました/.test(document.querySelector('#rvLiveGuide').textContent) && !document.querySelector('#rvArch').hidden", 20000),
          "2 終わった録画の帯に「アーカイブから書き出す」: %s" % pg.text_content("#rvLiveGuide"))
    guide = pg.text_content("#rvLiveGuide") or ""
    check("録画に無い区間のマークは、アーカイブが用意できたら自動でアーカイブから書き出します" in guide and "ごみ箱" not in guide,
          "2 帯の案内(録画に無い区間はアーカイブから書き出す・消す設定がオフなので「ごみ箱へ移します」は出さない): %s" % guide)
    check(wait_js(pg, "() => !document.querySelector('#rvArchRun').disabled", 10000), "2 「アーカイブから書き出す」が押せる")
    probe["status"] = "post_live"
    pg.click("#rvArchRun")
    check(wait_js(pg, "() => /処理中/.test(document.querySelector('#rvArchMsg').textContent)", 15000),
          "2 用意がまだ(post_live)→ 入口の 409 の文が帯に出る: %s" % pg.text_content("#rvArchMsg"))
    check(all(not j.get("archive") for j in jobs_of(rid1)), "2 用意がまだのときは何も始めない")

    # ---------------- 3. 押す → 進み具合 → アーカイブから書き出し(欠けのマーク B だけ)----------------
    seen_msgs, seen_band, busy = [], [], {"cancelled": False}
    stop_poll = threading.Event()
    # 押す前に、スタジオでほかの書き出し(POST /studio/api/export)を始めておく(スタジオは同時に 1 本だけ = 区間の書き出しは 409 busy になる)。
    # 入口が「待っています」と出したのを見てから、その書き出しを取り消す(確実に重なる)
    sx = serve.exporter
    real_cut = sx.run_ffmpeg

    def held_cut(ctl, spec, it, base):   # この書き出しだけ、取り消されるまで終わらない(重なりを確実にする。ほかは本物のまま)
        if spec.get("videoId") == busy_vid:
            while not ctl.cancelled:   # OPT2 の J2 から 1 つ目は ytt/jobs.Ctl
                time.sleep(0.1)
            raise sx.ExportError("取り消しました")
        return real_cut(ctl, spec, it, base)
    sx.run_ffmpeg = held_cut
    api("POST", "/studio/api/videos/open", {"kind": "youtube", "url": "https://youtu.be/" + busy_vid})
    api("PUT", "/studio/api/video", {"id": busy_vid, "marks": [{"id": "bm1", "start": 0, "end": 30, "status": "adopted"}]})
    code, bj = api("POST", "/studio/api/export", {"id": busy_vid, "markIds": ["bm1"], "precision": "accurate", "volume": 100})
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
    probe["status"] = "was_live"   # 用意ができた(busy の書き出しを始めたあとに。見回りが先に始めて待ちを見逃さないように)
    pg.click("#rvArchRun")
    shot_taken = False
    deadline = time.time() + 300
    while time.time() < deadline:
        t = pg.text_content("#rvArchMsg") or ""
        if t and (not seen_band or seen_band[-1] != t):
            seen_band.append(t)
        if shots and not shot_taken and "アーカイブから書き出しています" in t:
            pg.evaluate("window.scrollTo(0, 0)")
            pg.screenshot(path=os.path.join(shots, "p4_01_rebuilding.png"))
            shot_taken = True
        if "アーカイブから書き出しました 1/1 本" in t:
            break
        time.sleep(0.2)
    stop_poll.set()
    poller.join(5)
    js1 = jobs_of(rid1)
    arcs = {j["id"]: j.get("archive") or {} for j in js1 if j.get("archive")}
    check(len(arcs) == 1 and all(a.get("state") == "done" for a in arcs.values()),
          "3 アーカイブから書き出すのは欠けの 1 本だけ: %s" % [(a.get("state"), a.get("message")) for a in arcs.values()])
    check(any(re.match(r"^アーカイブから書き出しています 0/1 本(.+)$", x) for x in seen_band),
          "3 帯の進み具合(0/1 本と段。帯は 5 秒ごとに読み直す): %s" % " → ".join(seen_band[:12]))
    states = [m.split(":", 1)[0] for m in seen_msgs]
    check(all(s in states for s in ("align", "fetch", "done")),   # probe・verify は一瞬(偽の yt-dlp・入れ替えが無い)・待ちは見回りが先に拾うと見えないことがある
          "3 ジョブの段: 待ち → 確かめ → 照合 → 取得 → 検証 → 書き出し済み(%s)" % "・".join(dict.fromkeys(states)))
    check(seen_band and seen_band[-1].startswith("アーカイブから書き出しました 1/1 本"), "3 帯の最後: %s" % (seen_band[-1] if seen_band else ""))
    check(busy["code"] == 200 and any("スタジオの書き出しが終わるのを待っています" in m for m in seen_msgs),
          "3 スタジオがほかの書き出しで 409 busy の間は、失敗にせず待つ(busy の書き出し HTTP %s)" % busy["code"])
    code, bd = api("GET", "/studio/api/export?id=%s" % busy["id"])
    check(busy["cancelled"] and code == 200 and (bd or {}).get("state") == "cancelled",
          "3 先に始めた書き出しを取り消すと、待っていたアーカイブからの書き出しが進む(取り消した書き出しは cancelled): %s" % (bd or {}).get("state"))
    api("POST", "/studio/api/video/delete", {"id": busy_vid})
    try:   # 区間の書き出しの path は書き出し先の中だけ(本物の検査。HTTP の口は無いので部品を直に呼ぶ)
        sx.build_section_spec({"videoId": "TESTarch001", "start": 0, "end": 5, "path": os.path.join(tmp, "outside.mp4")})
        msg = ""
    except Exception as e:
        msg = getattr(e, "message", "") or str(e)
    check("書き出し先" in msg, "3 section の path は書き出し先の中だけ(本物の検査): %s" % msg)
    js1 = jobs_of(rid1)
    by = {}
    for j in js1:
        by["A" if abs(j["studio"]["start"] - 3.0) < 0.5 else "B" if j["studio"]["start"] < g0 else "C"] = j
    for k in ("A", "C"):   # 録画から書き出した切り抜きはそのまま(アーカイブの対象でない = 照合もしない)
        j = by.get(k) or {}
        if k not in speed:
            check(False, "3 %s の録画から書き出した切り抜きが無い" % k)
            continue
        path, size0, ino0 = speed[k]
        check(j.get("state") == "done" and j.get("path") == path and os.path.isfile(path) and os.stat(path).st_ino == ino0 and os.path.getsize(path) == size0
              and not j.get("archive"),
              "3 %s: 録画から書き出した切り抜きはそのまま(path・ino・大きさが同じ・archive なし): %s" % (k, os.path.basename(path)))
    b = by.get("B") or {}
    ba = b.get("archive") or {}
    info = normalize.probe(b.get("path") or "") if b.get("path") else None
    check(b.get("state") == "done" and not b.get("needsArchive") and info and normalize.is_30fps(info)
          and abs(info.get("duration", 0) - clip_len(b)) <= LX.LEN_TOL,
          "3 欠けのマーク B はアーカイブから新しく書き出した(done・30fps・長さ): %s" % ((b.get("path") or "")[-60:]))
    check(ba.get("state") == "done" and ba.get("aligned") and ba.get("offsetFrom") == "マークの手前の録画の音を照合" and isinstance(ba.get("offset"), (int, float)),
          "3 B のずれはマークの手前の録画の音で照合した(archive.aligned・offsetFrom): %s / %s" % (ba.get("aligned"), ba.get("offsetFrom")))
    off = ba.get("archiveStart", 0) - (b.get("studio") or {}).get("start", 0)
    check(off > 5, "3 B: 録画はアーカイブの途中から(ずれ %.2f 秒)= 照合で求めた" % off)
    clip, _w = schemas.load_clip_file(schemas.find_clip_path(b["path"])) if b.get("path") else (None, None)
    ca = (((clip or {}).get("source") or {}).get("live") or {}).get("archive") or {}
    check(clip and clip["source"]["kind"] == "live" and ca.get("videoId") == "TESTarch001" and abs(ca.get("start", -1) - ba.get("archiveStart", -2)) < 0.01
          and clip["export"]["from"] == "youtube-archive", "3 B の .clip.json の source.live.archive・export.from youtube-archive: %s" % ca)
    check(not any(os.path.isdir(os.path.join(r_, d_)) for r_, ds, _f in os.walk(out_dir) for d_ in ds if d_ == LA.BUILD_DIR), "3 作りかけのフォルダは残らない")


def _scene_chips_and_delete(cx):
    """4. アーカイブの札 / 5. 消す設定オフ → 残る / オン → ごみ箱へ"""
    api, cases_url, check, deleted_rids, gone_from_list, jobs_of, pg = cx.api, cx.cases_url, cx.check, cx.deleted_rids, cx.gone_from_list, cx.jobs_of, cx.pg
    rec_ids, rfolder, rid1, shots, smarks, srv = cx.rec_ids, cx.rfolder, cx.rid1, cx.shots, cx.smarks, cx.srv
    probes, trashbin = cx.probes, cx.trashbin
    # ---------------- 4. アーカイブの札 ----------------
    ms = wait_for(lambda: (lambda m: m and len([x for x in m if x.get("archived")]) == 1 and m)(smarks(rid1)), 30, 0.5)
    check(ms and len(ms) == 3 and all(x["status"] == "exported" for x in ms) and len([x for x in ms if x.get("archived")]) == 1,
          "4 スタジオのマーク 3 つが書き出し済みで、archived は欠けの B の 1 つだけ(/api/video の archived): %s"
          % [(x.get("status"), x.get("archived")) for x in (smarks(rid1) or [])])
    check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row .rv-chip.arch').length === 1", 15000), "4 候補のパネルのマークの行に「アーカイブ」の札が 1 つ")
    code, vs = api("GET", "/studio/api/videos")
    row = next((v for v in (vs or {}).get("videos") or [] if v["id"] == rid1), {})
    check(row.get("archived") == 1, "4 一覧の行の archived の数: %s" % row.get("archived"))
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
    check(rid1 in (rec_ids() or []) and os.path.isdir(os.path.join(rfolder, rid1)), "5 「録画を消す」がオフの間は、書き出しが済んでも録画は残る")
    srv.prefs.patch("live", {"autoDelete": True})   # 設定の画面(prefs)で付ける(帯の案内は録画を開いたときに読む = 6 で見る)
    check(srv.prefs.get(["live"])["live"]["autoDelete"] is True, "5 「録画を消す」を付けると live.autoDelete = true")
    n_probe = len(probes)
    gone = wait_for(lambda: gone_from_list(rid1), 30, 0.5)
    if gone:
        deleted_rids.add(rid1)
    trashed = os.path.join(rfolder, "ごみ箱", trashbin.day_name(), "録画", rid1)
    check(gone and not os.path.exists(os.path.join(rfolder, rid1)) and os.path.isfile(os.path.join(trashed, "recording.json")),
          "5 全部書き出した録画を、アーカイブ化を確かめて、ごみ箱(<置き場所>\\ごみ箱\\<今日>\\録画\\<録画 id>)へ移した(一覧と元のフォルダから消えた): 一覧 %s・元のフォルダ %s・ごみ箱 %s"
          % (rid1 in (rec_ids() or []), os.path.isdir(os.path.join(rfolder, rid1)), os.path.isfile(os.path.join(trashed, "recording.json"))))
    check(len(probes) > n_probe, "5 消す直前にアーカイブ化を確かめた(偽の yt-dlp %d 回 → %d 回)" % (n_probe, len(probes)))
    check(all(j.get("recordingDeleted") for j in jobs_of(rid1)), "5 ジョブに消した印 recordingDeleted")
    check(wait_js(pg, "() => document.querySelector('#rvLiveGuide').textContent.includes('録画は消しました(ごみ箱へ移しました)。マークと書き出した切り抜きはそのまま使えます')", 40000),
          "5 帯が「録画は消しました…」(LIVE_DELETED): %s" % pg.text_content("#rvLiveGuide"))
    check(pg.text_content("#rvRecState") == "録画を消しました" and "err" not in (pg.get_attribute("#rvRecState", "class") or ""), "5 状態の札はエラーにしない: %s" % pg.text_content("#rvRecState"))
    check(pg.evaluate("() => { const n = document.querySelector('#rvNotice'); return !n.hidden && /録画は消しました/.test(n.textContent) && !n.querySelector('[data-act=ytretry]'); }"),
          "5 プレーヤーの所にも同じ案内(「もう一度試す」は出さない)")
    check(pg.is_hidden("#rvArch") and pg.is_hidden('label[for="rvAutoExp"]'), "5 「アーカイブから書き出す」「マークしたらすぐ書き出す」は出さない")
    check(len(smarks(rid1) or []) == 3 and all(os.path.isfile(j["path"]) for j in jobs_of(rid1)), "5 マークと切り抜きはそのまま")
    if shots:
        pg.evaluate("window.scrollTo(0, 0)")
        pg.screenshot(path=os.path.join(shots, "p4_03_recording_deleted.png"))
    pg.goto("about:blank")   # 今も同じ URL(/cases?c=<id>#cand)を開いている。同じ URL への goto は # だけの移動で読み込み直さないので、いったん離れる
    pg.goto(cases_url(rid1))
    check(wait_js(pg, "() => !!window.CasesShell && CasesShell.state().panel === 'cand' && !!document.querySelector('#csPane .cd-panel #rvLiveGuide')"
                      " && /録画は消しました/.test(document.querySelector('#rvLiveGuide').textContent) && !document.querySelector('#rvNotice').hidden", 20000)
          and "見つかりません" not in (pg.text_content("#rvRecState") or ""), "5 開き直しても「録画は消しました」(「録画が見つかりません」にしない)")
    check(pg.evaluate("() => document.querySelectorAll('#rvList .rv-chip.arch').length") == 1, "5 開き直しても「アーカイブ」の札(B の 1 つ)")
    code, d = api("POST", "/live/r/local/%s/delete" % rid1, {})
    check(code == 404, "5 画面からの中継では録画を消せない(POST …/delete は 404): HTTP %s" % code)


def _scene_auto_rebuild(cx):
    """6. 録画が終わる → 作り直しは起きない → 録画を自動でごみ箱へ / 7. マークの無い録画"""
    LX, api, begin_from_home, check, deleted_rids, fetches, first, gone_from_list = cx.LX, cx.api, cx.begin_from_home, cx.check, cx.deleted_rids, cx.fetches, cx.first, cx.gone_from_list
    jobs_of, mark, pg, probes, rec_ids, rec_len, rec_status = cx.jobs_of, cx.mark, cx.pg, cx.probes, cx.rec_ids, cx.rec_len, cx.rec_status
    probe, rfolder, rid1, smarks, srv, trashbin = cx.probe, cx.rfolder, cx.rid1, cx.smarks, cx.srv, cx.trashbin
    # ---------------- 6. 録画が終わる → 作り直しは起きない → 録画を自動でごみ箱へ ----------------
    check(srv.prefs.get(["live"])["live"]["autoDelete"] is True, "6 「録画を消す」は付いたまま(5 で付けた)")
    check(begin_from_home(pg, YT2) and wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent)", 40000),
          "6 2 本目の録画が始まる(ホームの /#new → 案件の画面の候補)")
    code, vs = api("GET", "/studio/api/videos")
    rid2 = cx.rid2 = next((v["id"] for v in (vs or {}).get("videos") or [] if v.get("kind") == "live" and v["id"] != rid1), None)
    wait_for(lambda: rec_len(rid2) > 12, 40, 0.5)
    mark(pg, 3.0, 8.0)
    jd = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(jobs_of(rid2)), 90, 0.5)
    check(jd and jd["state"] == "done", "6 マーク D を書き出した(録画から)")
    d_path, d_ino = (jd or {}).get("path"), os.stat(jd["path"]).st_ino if jd and jd.get("path") else 0
    first["TESTarch002"] = LX.iso_epoch((rec_status(rid2)[1] or {}).get("firstPdt"))
    n_probe = len(probes)
    probe["status"] = "post_live"   # 止めた直後はアーカイブ化を確かめられない = 録画はまだ消えない(帯の案内を見るため。あとで was_live に戻す)
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid2})
    check(wait_js(pg, "() => /全部書き出して、アーカイブになったと確かめたら、録画はごみ箱へ移します/.test(document.querySelector('#rvLiveGuide').textContent)", 20000),
          "6 終わった録画の帯の案内に「全部書き出して、アーカイブになったと確かめたら、録画はごみ箱へ移します」: %s" % pg.text_content("#rvLiveGuide"))
    guide = pg.text_content("#rvLiveGuide") or ""
    check("アーカイブが用意できたら自動でアーカイブから書き出します" not in guide, "6 アーカイブから書き出すものが無いので、その案内は出ない: %s" % guide)
    time.sleep(3)   # 入口の見回り(1 秒ごと)が何回か回る
    check(rid2 in (rec_ids() or []) and os.path.isdir(os.path.join(rfolder, rid2)), "6 アーカイブ化を確かめられない間(post_live)は録画を消さない")
    probe["status"] = "was_live"
    stopped_at = time.time()
    gone2 = wait_for(lambda: gone_from_list(rid2), 60, 0.5)
    if gone2:
        deleted_rids.add(rid2)
    trashed = os.path.join(rfolder, "ごみ箱", trashbin.day_name(), "録画", rid2)
    check(gone2 and not os.path.exists(os.path.join(rfolder, rid2)) and os.path.isfile(os.path.join(trashed, "recording.json")),
          "6 アーカイブ化を確かめて、録画を自動でごみ箱へ移した(%.0f 秒後)" % (time.time() - stopped_at))
    jd = (jobs_of(rid2) or [{}])[0]
    check(not jd.get("archive") and jd.get("state") == "done" and jd.get("path") == d_path and os.path.isfile(d_path or "") and os.stat(d_path).st_ino == d_ino,
          "6 アーカイブから書き出すものは無いので作り直しは起きない(D の path・ino は同じ・archive なし)")
    check(wait_js(pg, "() => /録画は消しました/.test(document.querySelector('#rvLiveGuide').textContent)", 40000), "6 開いている画面の帯も「録画は消しました」")
    check(len(probes) > n_probe, "6 消す直前にアーカイブ化を確かめた(偽の yt-dlp %d 回。丸ごとの音の取得は %d 回)" % (len(probes) - n_probe, len(fetches)))

    # ---------------- 7. マークの無い録画 ----------------
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
    check(all(os.path.isfile(j["path"]) for j in jobs_of(rid1) + jobs_of(rid2)), "7 切り抜きはそのまま")


def _scene_after_stream(cx):
    """9. 配信後の全自動(M7): 人は触らない"""
    F, LX, api, back, check, deleted_rids, first, gone_from_list = cx.F, cx.LX, cx.api, cx.back, cx.check, cx.deleted_rids, cx.first, cx.gone_from_list
    handed, handed_ino, jobs_of, live, rec_ids, rec_len, rec_status, schemas = cx.handed, cx.handed_ino, cx.jobs_of, cx.live, cx.rec_ids, cx.rec_len, cx.rec_status, cx.schemas
    segs, srcs, srv, tmp, url_map = cx.segs, cx.srcs, cx.srv, cx.tmp, cx.url_map
    cases_url, pg = cx.cases_url, cx.pg
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
    # 見るだけ(マークしない): スタジオに登録して案件の画面の候補で開いておく(採用のときに入口が同じ登録をする = 結果は同じ)。帯の進み具合の 1 行を見る
    api("POST", "/studio/api/videos/open", {"kind": "live", "recorder": "local", "recording": rid4, "url": YT4, "title": "配信後の全自動"})
    pg.goto(cases_url(rid4))
    check(wait_js(pg, CAND_LIVE, 20000), "9 登録した録画を案件の画面の候補(/cases?c=<録画 id>#cand)で開ける")
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
          "9 段: アーカイブを解析 → アーカイブから書き出し → パック(%s)" % "・".join(dict.fromkeys(x.split(":", 1)[0] for x in seen_after)))
    done_band = wait_js(pg, "() => { const e = document.querySelector('#rvAfterStream'), t = e.textContent;"
                            " return !e.hidden && t.startsWith('配信後の自動の切り抜き: 済み') && t.includes('本のうち アーカイブから書き出し'); }", 40000)
    check(done_band and all(t.startswith("配信後の自動の切り抜き: ") for t in band),
          "9 スタジオの LIVE の帯に進み具合の 1 行(archiveInfo.afterStream.text。途中 %d 通り → %s)"
          % (len(band), pg.text_content("#rvAfterStream")))
    js4 = jobs_of(rid4)
    check(len(js4) >= 2 and len(js4) == (got or {}).get("jobs"), "9 上位 N を採用した: %d 本(N = %s)" % (len(js4), (got or {}).get("n")))
    check(js4 and all(j.get("origin") == "archive" and j.get("from") == "archive" and not j.get("holdFor") and j["state"] == "done" for j in js4),
          "9 採用の出どころ archive・from archive・holdFor なし・done: %s" % [(j.get("origin"), j.get("from"), j.get("holdFor"), j.get("state"), j.get("error")) for j in js4])
    check(js4 and all((j.get("archive") or {}).get("state") == "done" and (j.get("archive") or {}).get("auto") for j in js4),
          "9 全部をアーカイブから書き出した(archive.state done・auto): %s" % [(j.get("archive") or {}).get("message") for j in js4])
    h4 = handed[n_handed:]
    check(js4 and sorted(p for p, _f in h4) == sorted(j["path"] for j in js4) and all(f == "auto" for _p, f in h4) and all(j.get("runId") for j in js4),
          "9 N 本ともまとめて実行へ「文字起こし → パック」(after = auto)で渡した: %s" % [(os.path.basename(p), f) for p, f in h4])
    check(js4 and all(handed_ino.get(j["path"]) == os.stat(j["path"]).st_ino and not (j.get("archive") or {}).get("keep") for j in js4),
          "9 渡したのは今の path と同じファイル(アーカイブから書き出した物。退避は無い)")
    ok_clips = bool(js4)
    for j in js4:
        clip, _w = schemas.load_clip_file(schemas.find_clip_path(j["path"]))
        live_src = ((clip or {}).get("source") or {}).get("live") or {}
        ok_clips = ok_clips and live_src.get("origin") == "archive" and (clip or {}).get("mark", {}).get("src") == "auto" \
            and (live_src.get("archive") or {}).get("videoId") == "TESTarch004"
    check(ok_clips, "9 .clip.json に origin archive・mark.src auto・source.live.archive")
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
    check(gone4, "9 自動の切り抜きが済み、全部書き出したので、録画を消した(ごみ箱)")
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
    # 想定内: ホームの画面(/#new で録画を始めるとき)は「編集」の /transcribe/api/… を読むが、このテストはスタジオだけを取り込む(編集は無い)ので 404
    pg.wait_for_timeout(500)   # 画面を触らなかった間(9)のコンソール・応答のできごとを、選り分ける前に受け取る(Playwright は次の操作のときに届ける)
    deleted_rids.update(r for r in (rid1, rid2, rid3, rid4) if r and not os.path.exists(os.path.join(rfolder, r)))

    def expected(x):
        if "/favicon.ico" in x:
            return True
        if "/transcribe/api/" in x and (x.startswith("http") or "404" in x):
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
