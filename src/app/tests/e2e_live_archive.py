#!/usr/bin/env python3
"""リアルタイム切り抜きのアーカイブ(録画に無い区間だけをアーカイブから書き出す・アーカイブ化を確かめて録画をごみ箱へ移す)の通しの確認。
入口にスタジオを取り込み、録画の部品を別のプロセスで立て、ブラウザでホームの「新しい案件」(/#new)の URL の欄から録画を始め、
案件の画面の候補のパネル(/cases?c=<録画 id>#cand。panels/cand.js がスタジオの review.js と LivePlayer を載せる)を操作する。本物の YouTube には繋がない。
案件の画面の帯は開いたときに入口の設定 live.autoDelete を読む。アーカイブから書き出すのは録画に無い区間だけで、いつも自動。
保存の形・API の拒否は下の層(test_live_archive.py・test_live_cleanup.py・test_live.py・test_cand_panel.cjs)で見る。
帯の案内の文(設定とジョブの状態で変わる)は画面が組み立てるだけで下の層に無いので、ここで見る。
録画を始めて案件の画面へ移る道・欠けの表示は e2e_live_studio.py が見るので、ここは前提として通るだけ。

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
  - 時間は縮める: アーカイブからの自動の書き出し(録画が終わって 8 秒・確かめる間隔 2 秒)・録画を消す見回り(毎回)・マークの無い録画(6 秒)・
    書き出しの録画待ちの見回り(0.5 秒)。9 の録画は最初に始めて 1〜7 の間に録る。「消さない」は決まった秒ではなく入口の見回りが回ったのを数えて見る

確かめること:
  1  /#new の URL → /cases?c=<録画 id>#cand → 候補のパネルでマーク(自動の書き出し)→ 録画から書き出した切り抜き(done)/ 欠け(つなぎ直しの間をまたぐマーク)→ 失敗・要アーカイブ / 欠けのあとのマーク
  2  止める → 帯の案内・「アーカイブから書き出す」/ 用意がまだ(post_live)→ 409 の文が帯に出る
  3  押す → スタジオが 409 busy の間は待つ → 対象は欠けのマーク B だけ(アーカイブから書き出して done・長さ・録画はアーカイブの途中から = ずれを照合で求めた)
  4  B だけに「アーカイブ」の札(候補のパネルの行)
  5  「録画を消す」がオフの間は録画が残る → オンにすると、アーカイブ化を確かめて録画をごみ箱(<録画の置き場所>\\ごみ箱\\<日付>\\録画\\<録画 id>)へ移し、
     帯とプレーヤーの所が LIVE_DELETED の文(開き直しても同じ)・マークと切り抜きは残る
  6  録画が終わる → アーカイブから書き出すものが無いので作り直しは起きない → アーカイブ化を確かめて録画を自動でごみ箱へ
  7  マークの無い録画: 終わって(縮めた)1 日 → 録画とスタジオの行が消える
  9  配信後の全自動(live.autoAfterStream): 人がマークしない録画 → 終わる → 録画とアーカイブの時刻を照合 → アーカイブを偽の解析(STUDIO_FAKE)
     → 上位 N を採用 → アーカイブから書き出し → まとめて実行へ「文字起こし → パック」で N 本渡る(人は触らない)・
     自動の切り抜きが済むまで録画を消さない(マークの無い録画の 1 日(縮めた)を過ぎても)→ 済んだら消す(ごみ箱)
  8  コンソールのエラー・404・CSP 違反なし(想定した 409・消した録画の 404 は理由を書いて除く)
"""
import json
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
sys.path.append(REPO)   # src(ytt の部品)
from ytt import testkit  # noqa: E402
os.environ["STUDIO_FAKE"] = "1"

YT1 = "https://www.youtube.com/watch?v=TESTarch001"   # 手で作り直す録画
YT2 = "https://www.youtube.com/watch?v=TESTarch002"   # 自動で作り直す録画
YT3 = "https://www.youtube.com/watch?v=TESTarch003"   # マークの無い録画
YT4 = "https://www.youtube.com/watch?v=TESTarch004"   # 配信後の全自動の録画
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
    return testkit.wait_js(pg, expr, timeout, step=0.15, ignore_errors=True)


def clip_len(job):
    """書き出したジョブの動画の長さの見込み: 余白つき(ジョブの clip {from, to})ならその長さ、無ければマークの長さ"""
    from flow import live_export as LX   # noqa: E402  (起動の順で src を sys.path に足したあと)
    c = job.get("clip") or {}
    if c.get("from") and c.get("to"):
        return LX.iso_epoch(c["to"]) - LX.iso_epoch(c["from"])
    return job["studio"]["end"] - job["studio"]["start"]


def wait_for(fn, timeout=30.0, step=0.3):
    return testkit.wait_for(fn, timeout, step)


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
    from ytt import normalize, trashbin  # noqa: E402
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
    for u in (YT1, YT2, YT3):   # YT4(9)は録画を始める直前に作る(配信中のふりの HLS がアーカイブの頭のほうから始まるように)
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
                             "detect": {"enabled": False, "sens": "normal", "perHour": 6}})   # 検出は既定オン(自動の採用はいつもオンで、検出がオフなら採用しない)。この通しはアーカイブの流れだけを見る(配信中の候補が自動で採用されると 9 の記録の数が合わない)
    live = srv.live
    live_logs = []
    live.log = lambda m: live_logs.append("%.1f %s" % (time.time(), m))   # 入口の記録(消したことの 1 行など。失敗したときに出す)
    live.spawn_ok = False
    live.store_dir = os.path.join(tmp, "live")
    live.out_dir = lambda: out_dir
    live.audio = lambda: {"volume": 100, "loudness": None}
    handed = []

    class FakeRunner:   # 文字起こしへは偽のまとめて実行(② の口 submit。渡った動画と flow を覚える)
        def submit(self, env, spec=None, accept=False):
            from flow import run as run_mod
            run = run_mod.Run.from_envelope(env, spec)
            handed.append((run.source_path, "auto" if run.mode == "file_auto" else "check"))
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
    live.cleanup_opts = {"interval": 0, "no_mark_sec": 6.0}
    live.watch_sec = 1.0   # 入口の見回り(録画を消す見回り・作り直しの自動)を 1 秒ごとに
    ticks = [0]
    real_tick = live.tick

    def counted_tick():   # 入口の見回りの回数(「消さない」を見るときに、見回りが回ったのを数える)
        ticks[0] += 1
        return real_tick()
    live.tick = counted_tick

    def watch_rounds(n):
        """入口の見回りが n 回まわり終わるまで待つ(いま途中の回は数えない)"""
        want = ticks[0] + n + 1
        return wait_for(lambda: ticks[0] >= want, 10 + 2 * n, 0.1)
    live.start()
    live.exporter.poll = 0.5   # 書き出しの録画待ちの見回り(既定 2 秒)

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
                    browser, edge = p.chromium.launch(channel="msedge", args=["--mute-audio"]), True
                except Exception as e:
                    print("(Edge を起動できませんでした: %s。Playwright の chromium で続けます)" % str(e).splitlines()[0])
            if browser is None:
                browser = p.chromium.launch(args=["--mute-audio"])
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
                _begin_after_stream(cx)
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
    """「録画を消す」(入口の設定 live.autoDelete。既定オン)を外した所から始める(5 で付ける)。帯は録画を開いたときに入口の設定を読む"""
    cx.srv.prefs.patch("live", {"autoDelete": False})


def _begin_after_stream(cx):
    """9 の録画(人はマークしない)を最初に始めて、1〜7 の間に録る(9 で録画の長さを待たない)。
    録画の束には始めたときのスタジオの解析の設定が入るので、設定は先に。配信後の全自動のスイッチは 9 で入れる(1〜7 の録画に効かせない)"""
    F, api, back, check, segs, srcs, tmp, url_map = cx.F, cx.api, cx.back, cx.check, cx.segs, cx.srcs, cx.tmp, cx.url_map
    code, _d = api("PUT", "/studio/api/settings", {"section": "analyze", "value": {"count": 30, "length": 10, "headSec": 0}})   # 短いアーカイブでも候補が録画の範囲に入るように
    check(code == 200, "9 スタジオの解析の設定(候補 30・長さ 10 秒・冒頭の減点なし): HTTP %s" % code)
    s4 = F.LiveServer(os.path.join(tmp, "src"), segs, start=START_SEGS, rate=1.0)
    s4.end = False
    srcs[YT4] = s4
    url_map[YT4], back[s4.url] = s4.url, YT4
    code, d = api("POST", "/live/api/begin", {"url": YT4})
    cx.rid4 = ((d or {}).get("recording") or {}).get("id")
    check(code == 200 and cx.rid4, "9 4 本目の録画(人はマークしない): %s" % cx.rid4)


def _scene_record_marks(cx):
    """1. 録画 → マーク(録画から書き出し)・欠け・欠けのあと"""
    LX, api, begin_from_home, check, jobs_of, mark, pg = cx.LX, cx.api, cx.begin_from_home, cx.check, cx.jobs_of, cx.mark, cx.pg
    rec_len, rec_status, srcs = cx.rec_len, cx.rec_status, cx.srcs
    # ---------------- 1. 録画 → マーク(録画から書き出し)・欠け・欠けのあと ----------------
    check(begin_from_home(pg, YT1) and wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent)", 30000),
          "1 ホームの /#new で URL を入れると録画が始まり、案件の画面の候補で「録画中」")
    code, vs = api("GET", "/studio/api/videos")
    rid1 = cx.rid1 = next((v["id"] for v in (vs or {}).get("videos") or [] if v.get("kind") == "live"), None)
    wait_for(lambda: rec_len(rid1) > 13, 40, 0.5)
    mark(pg, 3.0, 9.0)
    ja = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(jobs_of(rid1)), 90, 0.5)
    check(ja and ja["state"] == "done", "1 マーク A を自動で書き出した(録画から):%s %s" % ((ja or {}).get("state"), (ja or {}).get("error")))
    # 欠け(つなぎ直し)
    srcs[YT1].down = True
    cut = wait_for(lambda: (rec_status(rid1)[1] or {}).get("state") == "reconnecting", 30, 0.3)
    time.sleep(3)
    srcs[YT1].down = False
    check(cut and wait_for(lambda: (lambda s: s.get("state") == "recording" and s.get("sessions", 0) >= 2)(rec_status(rid1)[1] or {}), 45, 0.5),
          "1 欠けを作る: 配信が切れて「つなぎ直し中」→ つなぎ直して録画を続ける")
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
    wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row').length === 2", 5000)
    mark(pg, g1 + 4.0, g1 + 8.0)   # 欠けのあとのマーク C
    js1 = wait_for(lambda: (lambda js: len(js) == 3 and all(j["state"] in ("done", "error") for j in js) and js)(jobs_of(rid1)), 120, 0.5) or jobs_of(rid1)
    by = {}
    for j in js1:
        by["A" if abs(j["studio"]["start"] - 3.0) < 0.5 else "B" if j["studio"]["start"] < g0 else "C"] = j
    check(set(by) == {"A", "B", "C"}, "1 マーク 3 つの書き出しのジョブ: %s" % [(j["studio"]["start"], j["state"]) for j in js1])
    jb, jc = by.get("B") or {}, by.get("C") or {}
    check(jb.get("state") == "error" and jb.get("needsArchive") is True, "1 欠けをまたぐマーク B は失敗・要差し替え: %s" % jb.get("error"))
    check(jc.get("state") == "done", "1 欠けのあとのマーク C は書き出せる: %s" % jc.get("error"))
    cx.base_t, cx.g0 = base_t, g0


def _scene_rebuild_by_hand(cx):
    """2. 止める → 帯 → 用意がまだ / 3. 押す → 進み具合 → アーカイブから書き出し(欠けのマークだけ)"""
    LX, api, base_t, busy_vid, check, first = cx.LX, cx.api, cx.base_t, cx.busy_vid, cx.check, cx.first
    g0, jobs_of, normalize, pg, probe, rid1, serve, shots = cx.g0, cx.jobs_of, cx.normalize, cx.pg, cx.probe, cx.rid1, cx.serve, cx.shots
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

    def held_cut(ctl, spec, it, base):   # この書き出しだけ、取り消されるまで終わらない(重なりを確実にする。ほかは本物のまま。ctl は ytt/jobs.Ctl)
        if spec.get("videoId") == busy_vid:
            while not ctl.cancelled:
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
    check(seen_band and seen_band[-1].startswith("アーカイブから書き出しました 1/1 本"), "3 帯の最後: %s" % (seen_band[-1] if seen_band else ""))
    check(busy["code"] == 200 and any("スタジオの書き出しが終わるのを待っています" in m for m in seen_msgs),
          "3 スタジオがほかの書き出しで 409 busy の間は、失敗にせず待つ(busy の書き出し HTTP %s)" % busy["code"])
    code, bd = api("GET", "/studio/api/export?id=%s" % busy["id"])
    check(busy["cancelled"] and code == 200 and (bd or {}).get("state") == "cancelled",
          "3 先に始めた書き出しを取り消すと、待っていたアーカイブからの書き出しが進む(取り消した書き出しは cancelled): %s" % (bd or {}).get("state"))
    api("POST", "/studio/api/video/delete", {"id": busy_vid})
    b = next((j for j in jobs_of(rid1) if j["studio"]["start"] < g0 and abs(j["studio"]["start"] - 3.0) >= 0.5), {})
    ba = b.get("archive") or {}
    dur = (normalize.probe(b["path"]) or {}).get("duration", 0) if b.get("path") else 0
    check(b.get("state") == "done" and not b.get("needsArchive") and abs(dur - clip_len(b)) <= LX.LEN_TOL,
          "3 欠けのマーク B はアーカイブから新しく書き出した(done・長さ %.2f 秒): %s" % (dur, (b.get("path") or "")[-60:]))
    off = ba.get("archiveStart", 0) - (b.get("studio") or {}).get("start", 0)
    check(ba.get("aligned") and off > 5, "3 B: 録画はアーカイブの途中から(ずれ %.2f 秒)= 照合で求めた" % off)


def _scene_chips_and_delete(cx):
    """4. アーカイブの札 / 5. 消す設定オフ → 残る / オン → ごみ箱へ"""
    cases_url, check, deleted_rids, gone_from_list, jobs_of, pg = cx.cases_url, cx.check, cx.deleted_rids, cx.gone_from_list, cx.jobs_of, cx.pg
    rec_ids, rfolder, rid1, shots, smarks, srv = cx.rec_ids, cx.rfolder, cx.rid1, cx.shots, cx.smarks, cx.srv
    probes, trashbin, watch_rounds = cx.probes, cx.trashbin, cx.watch_rounds
    # ---------------- 4. アーカイブの札 ----------------
    check(wait_js(pg, "() => document.querySelectorAll('#rvList .rv-mark-row .rv-chip.arch').length === 1", 30000), "4 候補のパネルのマークの行に「アーカイブ」の札が 1 つ")
    if shots:
        pg.evaluate("window.scrollTo(0, 0)")
        pg.screenshot(path=os.path.join(shots, "p4_02_archived_chips.png"))
        pg.click('#rvJump [data-jump="export"]')
        pg.wait_for_timeout(500)
        pg.screenshot(path=os.path.join(shots, "p4_02b_export_rows.png"))
        pg.click("#rvExpClose")
        pg.wait_for_timeout(300)

    # ---------------- 5. 消す設定オフ → 残る / オン → 消える ----------------
    watch_rounds(2)
    check(rid1 in (rec_ids() or []) and os.path.isdir(os.path.join(rfolder, rid1)), "5 「録画を消す」がオフの間は、書き出しが済んでも録画は残る")
    srv.prefs.patch("live", {"autoDelete": True})   # 設定の画面(prefs)で付ける(帯の案内は録画を開いたときに読む = 6 で見る)
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


def _scene_auto_rebuild(cx):
    """6. 録画が終わる → 作り直しは起きない → 録画を自動でごみ箱へ / 7. マークの無い録画"""
    LX, api, begin_from_home, check, deleted_rids, fetches, first, gone_from_list = cx.LX, cx.api, cx.begin_from_home, cx.check, cx.deleted_rids, cx.fetches, cx.first, cx.gone_from_list
    jobs_of, mark, pg, probes, rec_ids, rec_len, rec_status = cx.jobs_of, cx.mark, cx.pg, cx.probes, cx.rec_ids, cx.rec_len, cx.rec_status
    probe, rfolder, rid1, smarks, trashbin, watch_rounds = cx.probe, cx.rfolder, cx.rid1, cx.smarks, cx.trashbin, cx.watch_rounds
    # ---------------- 6. 録画が終わる → 作り直しは起きない → 録画を自動でごみ箱へ ----------------
    check(begin_from_home(pg, YT2) and wait_js(pg, "() => /録画中/.test(document.querySelector('#rvRecState').textContent)", 40000),
          "6 2 本目の録画が始まる(ホームの /#new → 案件の画面の候補)")
    code, vs = api("GET", "/studio/api/videos")
    rid2 = cx.rid2 = next((v["id"] for v in (vs or {}).get("videos") or [] if v.get("kind") == "live" and v["id"] != rid1), None)
    wait_for(lambda: rec_len(rid2) > 12, 40, 0.5)
    mark(pg, 3.0, 8.0)
    jd = wait_for(lambda: (lambda js: js and js[0]["state"] in ("done", "error") and js[0])(jobs_of(rid2)), 90, 0.5)
    check(jd and jd["state"] == "done", "6 マーク D を書き出した(録画から)")
    first["TESTarch002"] = LX.iso_epoch((rec_status(rid2)[1] or {}).get("firstPdt"))
    n_probe = len(probes)
    probe["status"] = "post_live"   # 止めた直後はアーカイブ化を確かめられない = 録画はまだ消えない(帯の案内を見るため。あとで was_live に戻す)
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid2})
    check(wait_js(pg, "() => /全部書き出して、アーカイブになったと確かめたら、録画はごみ箱へ移します/.test(document.querySelector('#rvLiveGuide').textContent)", 20000),
          "6 終わった録画の帯の案内に「全部書き出して、アーカイブになったと確かめたら、録画はごみ箱へ移します」: %s" % pg.text_content("#rvLiveGuide"))
    guide = pg.text_content("#rvLiveGuide") or ""
    check("アーカイブが用意できたら自動でアーカイブから書き出します" not in guide, "6 アーカイブから書き出すものが無いので、その案内は出ない: %s" % guide)
    watch_rounds(2)
    check(rid2 in (rec_ids() or []) and os.path.isdir(os.path.join(rfolder, rid2)), "6 アーカイブ化を確かめられない間(post_live)は録画を消さない")
    probe["status"] = "was_live"
    stopped_at = time.time()
    gone2 = wait_for(lambda: gone_from_list(rid2), 60, 0.5)
    if gone2:
        deleted_rids.add(rid2)
    trashed = os.path.join(rfolder, "ごみ箱", trashbin.day_name(), "録画", rid2)
    check(gone2 and not os.path.exists(os.path.join(rfolder, rid2)) and os.path.isfile(os.path.join(trashed, "recording.json")),
          "6 アーカイブ化を確かめて、録画を自動でごみ箱へ移した(%.0f 秒後)" % (time.time() - stopped_at))
    check((jobs_of(rid2) or [{}])[0].get("state") == "done", "6 アーカイブから書き出すものは無いので作り直しは起きない(D は done のまま)")
    check(wait_js(pg, "() => /録画は消しました/.test(document.querySelector('#rvLiveGuide').textContent)", 40000), "6 開いている画面の帯も「録画は消しました」")
    check(len(probes) > n_probe, "6 消す直前にアーカイブ化を確かめた(偽の yt-dlp %d 回。丸ごとの音の取得は %d 回)" % (len(probes) - n_probe, len(fetches)))

    # ---------------- 7. マークの無い録画 ----------------
    code, d = api("POST", "/live/api/begin", {"url": YT3})
    rid3 = cx.rid3 = ((d or {}).get("recording") or {}).get("id")
    code, _v = api("POST", "/studio/api/videos/open", {"kind": "live", "recorder": "local", "recording": rid3, "url": YT3, "title": "マークなし"})
    check(rid3 and code == 200, "7 マークの無い録画を始めてスタジオに登録: %s" % rid3)
    wait_for(lambda: rec_len(rid3) > 3, 30, 0.5)
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid3})
    watch_rounds(1)
    check(rid3 in (rec_ids() or []) and smarks(rid3) == [], "7 終わってすぐ(縮めた 1 日の前)は消さない")
    gone3 = wait_for(lambda: gone_from_list(rid3), 40, 0.5)
    if gone3:
        deleted_rids.add(rid3)
    check(gone3 and api("GET", "/studio/api/video?id=%s" % rid3)[0] == 404, "7 マークが無いまま(縮めた)1 日たった録画とスタジオの行を消した")
    check(all(os.path.isfile(j["path"]) for j in jobs_of(rid1) + jobs_of(rid2)), "7 切り抜きはそのまま")


def _scene_after_stream(cx):
    """9. 配信後の全自動: 人は触らない(録画は _begin_after_stream が最初に始めた。採用の出どころ・.clip.json・記録・帯の 1 行は test_live_archive.py の AfterStreamTest と test_cand_panel.cjs)"""
    LX, api, check, deleted_rids, first, gone_from_list = cx.LX, cx.api, cx.check, cx.deleted_rids, cx.first, cx.gone_from_list
    handed, jobs_of, live, rec_ids, rec_len, rec_status = cx.handed, cx.jobs_of, cx.live, cx.rec_ids, cx.rec_len, cx.rec_status
    rid4, srv, tmp = cx.rid4, cx.srv, cx.tmp
    cases_url, pg = cx.cases_url, cx.pg
    # ---------------- 9. 配信後の全自動: 人は触らない ----------------
    chat = os.path.join(tmp, "chat.jsonl")   # 偽のチャット(25 秒ごとに 4 秒の盛り上がり = アーカイブの全体に 25 秒おきの山。合成の音だけでは山が立たない)
    rnd = __import__("random").Random(1)
    with open(chat, "w", encoding="utf-8") as f:
        for t in range(ARC_SEC):
            n = 2 + rnd.randint(0, 2) + (40 if t % 25 < 4 else 0)
            for k in range(n):
                f.write(json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": str(t * 1000 + k * 10), "actions": [{"addChatItemAction": {
                    "item": {"liveChatTextMessageRenderer": {"message": {"runs": [{"text": "草" if k % 3 == 0 else "はい"}]}}}}}]}}) + chr(10))
    os.environ["STUDIO_FAKE_CHAT"] = chat
    srv.prefs.patch("live", {"autoAfterStream": True, "afterStreamPerHour": 30})   # 「配信が終わったら、アーカイブの解析で自動で切り抜く」
    n_handed = len(handed)
    # 見るだけ(マークしない): スタジオに登録して案件の画面の候補で開いておく(採用のときに入口が同じ登録をする = 結果は同じ)
    api("POST", "/studio/api/videos/open", {"kind": "live", "recorder": "local", "recording": rid4, "url": YT4, "title": "配信後の全自動"})
    pg.goto(cases_url(rid4))
    check(wait_js(pg, CAND_LIVE, 20000), "9 登録した録画を案件の画面の候補(/cases?c=<録画 id>#cand)で開ける")
    first["TESTarch004"] = LX.iso_epoch((rec_status(rid4)[1] or {}).get("firstPdt"))
    wait_for(lambda: rec_len(rid4) > 75, 120, 0.5)   # ふつうは 1〜7 の間に録れている
    rec_sec = max(rec_len(rid4), 1.0)
    live.archiver.per_hour = lambda: max(1, int(round(4 * 3600.0 / rec_sec)))   # 1 時間あたりを録画の長さ(1〜7 にかかった時間で変わる)から決めて N = 4(本物は設定の値)
    api("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid4})
    stopped_at = time.time()

    def after_state():
        return ((api("GET", "/live/api/exports?recorder=local&recording=%s" % rid4)[1] or {}).get("archiveInfo") or {}).get("afterStream") or {}
    seen_after, kept = [], {}

    def watch():
        if "rec" not in kept and time.time() - stopped_at > 10:   # 縮めた「マークの無い録画は 1 日で消す」(6 秒)と見回り(1 秒)を過ぎた所で 1 回見る
            kept["rec"] = rid4 in (rec_ids() or [])
        a = after_state()
        s = "%s:%s" % (a.get("state"), a.get("message"))
        if a and (not seen_after or seen_after[-1] != s):
            seen_after.append(s)
        if a.get("state") in ("done", "none", "error"):
            kept.setdefault("rec", None)   # 10 秒より前に済んだ(見られなかった)
            return a
        return None
    got = wait_for(watch, 420, 1.0)
    check(kept.get("rec") is True, "9 マークが無いまま(縮めた)1 日を過ぎても、配信後の自動の切り抜きが済むまで録画を消さない: %s" % kept.get("rec"))
    check(got and got.get("state") == "done", "9 録画が終わって %.0f 秒で、人が触らずに配信後の自動の切り抜きが済んだ: %s / %s"
          % (time.time() - stopped_at, (got or {}).get("message"), " → ".join(seen_after[-8:])))
    check(any(x.startswith("analyze:") for x in seen_after) and any(x.startswith("export:") for x in seen_after),
          "9 段: アーカイブを解析 → アーカイブから書き出し → パック(%s)" % "・".join(dict.fromkeys(x.split(":", 1)[0] for x in seen_after)))
    js4 = jobs_of(rid4)
    check(len(js4) >= 2 and len(js4) == (got or {}).get("jobs"), "9 上位 N を採用した: %d 本(N = %s)" % (len(js4), (got or {}).get("n")))
    h4 = handed[n_handed:]
    check(js4 and sorted(p for p, _f in h4) == sorted(j["path"] for j in js4) and all(f == "auto" for _p, f in h4) and all(j.get("runId") for j in js4),
          "9 N 本ともまとめて実行へ「文字起こし → パック」(after = auto)で渡した: %s" % [(os.path.basename(p), f) for p, f in h4])
    gone4 = wait_for(lambda: gone_from_list(rid4), 40, 0.5)
    if gone4:
        deleted_rids.add(rid4)
    check(gone4, "9 自動の切り抜きが済み、全部書き出したので、録画を消した(ごみ箱)")


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
