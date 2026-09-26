#!/usr/bin/env python3
"""文字起こしツールを入口(app/launch.py)に取り込んだ形の通し確認(統合計画の段階3-3)。

    python3 e2e_ui_mounted.py

本物の入口(app/launch.py --only transcribe,cut2resolve)を子プロセスとして起動し、http://localhost:<port>/transcribe/ で:
  - CSP(app/mount.py の MOUNTS["transcribe"]["csp"])の下で画面が動く・合言葉(<meta name="ytt-token">)が入る
  - 認識は別プロセスのワーカー(tx_worker.py。TRANSCRIBE_BACKEND=worker-fake でワーカーの中だけ偽のモデル)を通る
  - ワーカーを強制終了しても、入口・次の文字起こしは止まらない(次の要求で起動し直す)
  - 動画は /transcribe/media?... の下から読む
  - 書き込み系 API(PUT・POST)は合言葉(X-YTT-Token)が要る
  - 終了(SIGTERM)すると、ワーカーの子プロセスも .runtime/transcribe.json も残らない
  - v0.15.0: 履歴の一覧(配信ごとのまとまり・配信者・校正の進み具合・パック済み)と、校正画面の「カットとパック」
    (同じ入口の cut2resolve の API で計算・カット後の見え方で再生・パックを作る・上書きの確認・zip)
を確かめる。ffmpeg と Playwright の chromium が必要。
"""
import glob
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TP_LUA = "create_resolve_textplus_project.lua"

# app/test_launch.py の _copy_tool と同じ規則(実行時データ・秘密情報を写さない)
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.log", "data.json*", "feedback.jsonl*", "config.json", "settings*.json", "registry.json", "cache", "archive",
    "exports", "clips", "transcripts", "dataset", "models", "work", ".venv", "*.mp4", "resolve-ui-test", "node_modules", ".running.json")



def read_pack_plan(path):
    """パックの Lua に埋め込んだ計画(区間・字幕・置き先)。2026-09-26(④)から textplus-import.json は出さない"""
    d = os.path.join(REPO, "cut2resolve")
    if d not in sys.path:
        sys.path.append(d)   # 末尾に足す(同じ名前の serve.py などを隠さない)
    import resolve_textplus
    with open(path, encoding="utf-8") as f:
        return resolve_textplus.read_script_plan(f.read())

def copy_dir(src, dst):
    shutil.copytree(src, dst, ignore=IGNORE)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, method, path, body=None, token=None, prefix="/transcribe"):
    """入口(127.0.0.1:<port>)への1回の要求。urllib は自動で Host: 127.0.0.1:<port> を付ける。"""
    headers, data = {}, None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token and method not in ("GET", "HEAD"):
        headers["X-YTT-Token"] = token
    req = urllib.request.Request("http://127.0.0.1:%d%s%s" % (port, prefix, path), data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def find_worker_pids(tmp):
    """この確認が起動した tx_worker.py(一時フォルダの下のもの)の pid を探す。Linux は /proc、Windows は PowerShell(Win32_Process のコマンドライン)"""
    needle = os.path.join(tmp, "transcribe-tool", "tx_worker.py").encode()
    pids = []
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60).stdout
        for line in out.decode("utf-8", "replace").splitlines():
            pid, _, cmd = line.partition("	")
            if needle.decode().lower() in cmd.lower() and pid.strip().isdigit():
                pids.append(int(pid))
        return pids
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if needle in data:
            try:
                pids.append(int(p.split("/")[2]))
            except (IndexError, ValueError):
                pass
    return pids


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="tx-mounted-e2e-")
    rt = os.path.join(tmp, "rt")
    proc = None
    try:
        copy_dir(os.path.join(REPO, "app"), os.path.join(tmp, "app"))
        copy_dir(os.path.join(REPO, "transcribe-tool"), os.path.join(tmp, "transcribe-tool"))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        # clip-studio は写さない(--only なら Supervisor はそのツールの Tool を作らないので不要。app/launch.py 参照)。
        # cut2resolve も入口に取り込む(v0.15.0: 校正画面の「カットとパック」が同じ入口の /cut2resolve/api/... を呼ぶ。zip も cut2resolve/pack.py で作る)
        copy_dir(os.path.join(REPO, "cut2resolve"), os.path.join(tmp, "cut2resolve"))

        # CSP・版はハードコードせず、写した本物の app/mount.py・app.js から読む
        sys.path.insert(0, os.path.join(tmp, "app"))
        import mount as tx_mount  # noqa: E402
        csp = tx_mount.MOUNTS["transcribe"]["csp"]
        with open(os.path.join(tmp, "transcribe-tool", "app.js"), encoding="utf-8") as f:
            app_version = re.search(r"const APP_VERSION = '([^']+)'", f.read()).group(1)

        media = os.path.join(tmp, "テスト 用の 素材 動画.webm")   # 日本語・スペースを含む名前
        # Playwright の chromium(オープンソース版)は H.264 を再生できないので、VP9 + Opus の webm にする
        # (実際の動画編集では mp4/H.264 も普通に使われるが、ここは「動画を読み込める」確認が目的なので、
        #  ヘッドレス chromium で再生できる形式を選ぶ。文字起こし自体はワーカーが ffmpeg で音声を取り出すので形式を問わない)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=20",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                        "-shortest", "-c:v", "libvpx-vp9", "-b:v", "300k", "-c:a", "libopus", media],
                       check=True, timeout=60)
        # 切り抜きスタジオが書き出した切り抜きのふり: 隣の .clip.json(元の配信)と、スタジオの data.json(配信者。文字起こしは読むだけ)
        sys.path.insert(0, tmp)
        from ytt_core import schemas as yschemas  # noqa: E402
        clip = yschemas.build_clip(media, 20.0, {"kind": "youtube", "videoId": "vidE2E00001", "title": "【雑談】テストの配信"}, (600.0, 620.0),
                                   {"id": "m1", "label": "見どころ", "status": "exported", "src": "manual"}, {"mode": "precise"}, {"name": "clip-studio", "version": "e2e"})
        with open(yschemas.clip_path_for(media), "w", encoding="utf-8") as f:
            json.dump(clip, f, ensure_ascii=False)
        studio_data = os.path.join(tmp, "studio-data.json")
        with open(studio_data, "w", encoding="utf-8") as f:
            json.dump({"videos": {"vidE2E00001": {"title": "【雑談】テストの配信", "channel": "テスト配信者", "marks": []}}}, f, ensure_ascii=False)

        port = free_port()
        env = dict(os.environ, YTT_RUNTIME_DIR=rt, TRANSCRIBE_BACKEND="worker-fake", TRANSCRIBE_FAKE_DELAY="0.05", TRANSCRIBE_STUDIO_DATA=studio_data)
        proc = subprocess.Popen([sys.executable, os.path.join(tmp, "app", "launch.py"), "--port", str(port), "--no-open", "--only", "transcribe,cut2resolve"],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))   # Windows: Ctrl+Break を入口にだけ送るため

        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/transcribe/api/ping" % port, timeout=1).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("入口(取り込んだ文字起こし)が起動しませんでした")

        errors = []

        def wait_js(pg, expr, timeout=30000):
            """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ(cut2resolve/e2e_ui.py と同じ)。"""
            end = time.time() + timeout / 1000
            while time.time() < end:
                if pg.evaluate(expr):
                    return True
                time.sleep(0.1)
            raise TimeoutError(expr)

        def open_doc(pg, title):
            wait_js(pg, "document.querySelector('#txList') && document.querySelector('#txList').textContent.includes(%s)" % json.dumps(title), 60000)
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pg.click("[data-side-tab=files]")
            pg.fill("#txSearch", title)
            pg.locator("#txList .txi").filter(has_text=title).locator(".t").first.click()
            pg.evaluate("(() => { const q = document.querySelector('#txSearch'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); })()")
            wait_js(pg, "document.querySelector('#docTitle').value === %s" % json.dumps(title))
            pg.wait_for_selector("#segs .seg")

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1500, "height": 1000})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            # 想定内の 403(合言葉なしの確認は別途 Python から行う)以外のコンソールエラーだけ数える
            pg.on("console", lambda m: (m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append("console: " + m.text)))

            # ==================== 1) CSP・版・合言葉・?media= の受け渡し ====================
            resp = pg.goto("http://localhost:%d/transcribe/?media=%s" % (port, urllib.parse.quote(media)))
            check(resp is not None and resp.header_value("content-security-policy") == csp, "CSP ヘッダーが app/mount.py の設定どおり")
            wait_js(pg, "document.querySelector('#srcPath') && document.querySelector('#srcPath').value !== ''", 15000)
            check(pg.inner_text("#ver").strip() == "v" + app_version, "#ver に app.js の版が出る: " + pg.inner_text("#ver"))
            check(pg.evaluate("!!document.querySelector('meta[name=\"ytt-token\"]')"), "入口が合言葉を画面に入れている(<meta name=ytt-token>)")
            check(pg.evaluate("location.pathname") == "/transcribe/", "画面の場所は /transcribe/")
            check(pg.input_value("#srcPath") == media, "?media= の値が新規文字起こしのファイル欄に入る")

            # ==================== 2) 1本目の文字起こし(ワーカー経由)→ 終わると自動で開く ====================
            pg.click("#btnStart")
            wait_js(pg, "document.querySelector('#doc') && !document.querySelector('#doc').hidden && document.querySelectorAll('#segs textarea').length > 0", 60000)
            texts = pg.evaluate("[...document.querySelectorAll('#segs textarea')].map(e => e.value)")
            check(len(texts) == 5 and texts[:2] == ["テスト文1", "テスト文2"], "文字起こしの結果(ワーカー経由)を一覧に表示する: %s" % texts)
            media_src = pg.evaluate("document.querySelector('#player').getAttribute('src')")
            check(bool(media_src) and media_src.startswith("/transcribe/media?"), "動画の src は /transcribe/media の下: %s" % media_src)
            wait_js(pg, "document.querySelector('#player').readyState > 0", 20000)
            check(True, "動画を読み込める(readyState > 0)")
            tid1 = urllib.parse.parse_qs(urllib.parse.urlsplit(media_src).query).get("id", [None])[0]
            check(bool(tid1), "開いた文書の id を取り出せる: %s" % tid1)

            # ==================== 3) 行を直す → 自動保存(PUT + X-YTT-Token)→ サーバー側で確認 ====================
            pg.locator("#segs textarea").nth(0).fill("直した文1")
            wait_js(pg, "document.querySelector('#saveState').getAttribute('data-state') === 'ok'", 10000)
            st, doc1 = call(port, "GET", "/api/transcript?id=" + urllib.parse.quote(tid1))
            check(st == 200 and doc1.get("segments", [{}])[0].get("text") == "直した文1",
                  "編集した行がサーバーに保存されている(Python から GET で確認): %s" % (doc1.get("segments", [{}])[0].get("text") if st == 200 else (st, doc1)))

            # ==================== 3b) 履歴の一覧(v0.15.0): 配信ごとのまとまり・配信者・校正の進み具合 ====================
            st, lst = call(port, "GET", "/api/transcripts")
            it1 = next((x for x in lst.get("items", []) if x["id"] == tid1), {})
            check(st == 200 and it1.get("videoId") == "vidE2E00001" and it1.get("channel") == "テスト配信者" and it1.get("clipTitle") == "【雑談】テストの配信"
                  and it1.get("rows") == 5 and it1.get("mediaOk") is True and it1.get("pack") is None and it1.get("durationSec") == 20.0,
                  "一覧の API に、元の配信・配信者(スタジオの data.json)・行数・長さ・動画の有無・パックが入る: %s" % {k: it1.get(k) for k in ("videoId", "channel", "rows", "mediaOk", "pack", "durationSec")})
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pg.click("[data-side-tab=files]")
            pg.select_option("#txGroup", "stream")
            head = pg.inner_text("#txList details.ui-group summary")
            check("【雑談】テストの配信" in head and "テスト配信者" in head, "配信ごとのまとまりの見出しに、配信の題名と配信者が出る: %s" % head)
            check(pg.evaluate("document.querySelector('#txList .txi.cur .txi-menu summary').textContent.trim()") == "⋮", "操作のメニューは「⋮」(題名の省略の「…」と紛らわしくない)")
            pg.select_option("#txState", "done")
            check("条件に合う文字起こしはありません" in pg.inner_text("#txList") and "0 / 1件" in pg.inner_text("#txCount"), "状態「校正済み」で絞り込める(まだ無い): " + pg.inner_text("#txCount"))
            pg.select_option("#txState", "all")

            # ==================== 3c) パック(「編集」E4: 3 パック のタブ。区間は 2 カット のタブのとおり = cut2resolve の spec.keeps) ====================
            pg.click("[data-edtab=pack]")
            pk_is = lambda cnt, ln, caps: "document.querySelector('#pkCount').textContent === '%s' && document.querySelector('#pkLen').textContent === '%s' && document.querySelector('#pkCaps').textContent === '%s'" % (cnt, ln, caps)   # noqa: E731
            wait_js(pg, pk_is(1, "0:20.00", 5), 30000)
            wait_js(pg, "!document.querySelector('#pkBuild').disabled", 15000)   # cut2resolve の確認(他のツールの問い合わせ)が終わるまで待つ
            check(pg.is_hidden("#pkOff") and pg.is_enabled("#pkBuild") and pg.inner_text("#pkBuild") == "パックを作る",
                  "3 パック のタブは入口の中では使える・これから作るパック(1区間・カット後 0:20.00・Text+ 字幕 5)")
            tr_beside = os.path.splitext(media)[0] + ".transcript.json"
            time.sleep(1.0)
            check(not os.path.isfile(tr_beside) and call(port, "GET", "/api/edit?id=" + tid1)[1]["edit"] is None,
                  "開いただけでは、動画の隣に .transcript.json を書き出さない・カットも保存しない(見積もりは一時フォルダで)")
            pg.click("[data-edtab=tx]")
            pg.locator("#segs .seg").nth(1).locator("[data-act=cut]").click()   # 2行目(4〜8秒)を削る
            pg.click("[data-edtab=pack]")
            wait_js(pg, pk_is(2, "0:16.00", 4), 30000)
            check(True, "行を削ると、これから作るパックも変わる(2区間・0:16.00・字幕 4)")
            check(pg.locator("#pkMap i").count() == 2, "区間の略図が出る")
            # パックを作る(置き先の fps・画面の大きさ)
            pg.click("#pkFps [data-v='30']")
            pg.click("#pkSize [data-v='1920x1080']")
            wait_js(pg, "document.querySelector('#pkSize [data-v=\"1920x1080\"]').getAttribute('aria-pressed') === 'true'", 3000)
            check(True, "画面の大きさを選べる(横)")
            pg.click("#pkBuild")
            wait_js(pg, "!document.querySelector('#pkLast').hidden && document.querySelector('#pkBuild').textContent === 'パックを作り直す' && document.querySelector('#pkJob').hidden", 120000)
            packdir = os.path.splitext(media)[0] + "_pack"
            ip = read_pack_plan(os.path.join(packdir, TP_LUA))
            caps = json.dumps(ip.get("captions"), ensure_ascii=False)
            check(ip.get("target") == {"fps": 30, "width": 1920, "height": 1080} and [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip.get("cuts", [])] == [(0, 96), (192, 480)]
                  and "テスト文3" in caps and "テスト文2" not in caps,
                  "パック(Text+)ができる: 選んだ fps・大きさ、カットのとおりの区間(24fps の 0〜4秒・8〜20秒)、削った行の字幕は入らない: %s" % {"target": ip.get("target"), "cuts": ip.get("cuts", [])[:3]})
            check(packdir in pg.inner_text("#pkLastDir") and pg.inner_text("#pkLastPill") == "前回のパック" and TP_LUA in pg.inner_text("#pkLastFiles"),
                  "「前回のパック」に出力フォルダと中身が出る")
            st, lst = call(port, "GET", "/api/transcripts")
            it1 = next((x for x in lst["items"] if x["id"] == tid1), {})
            check(it1.get("pack", {}).get("textplus") is True and it1.get("packRev", 0) >= 1 and it1.get("packStale") is False, "一覧の API もパックあり・作り直しは要らない")
            pg.click("#pkReadme")
            wait_js(pg, "!document.querySelector('#pkReadmeText').hidden && document.querySelector('#pkReadmeText').textContent.length > 20", 10000)
            check("Resolve" in pg.inner_text("#pkReadmeText"), "「友人へ.txt を見る」で手順書が出る")
            # カットを変えると「作り直しが要る」
            pg.click("[data-edtab=tx]")
            pg.locator("#segs .seg").nth(3).locator("[data-act=cut]").click()   # 4行目(12〜16秒)も削る
            pg.click("[data-edtab=pack]")
            wait_js(pg, pk_is(3, "0:12.00", 3) + " && document.querySelector('#pkLastPill').textContent === '作り直しが要る'", 30000)
            check("作り直し" in pg.inner_text("#pkLastWhen"), "カットが変わったら「作り直しが要る」と知らせる: " + pg.inner_text("#pkLastWhen"))
            # 作り直す → 上書きの確認(やめる → 何もしない / 上書き → 作り直す)
            pg.click("#pkBuild")
            wait_js(pg, "document.querySelector('#dlgOverwrite').open", 20000)
            check(TP_LUA in pg.inner_text("#owFiles") and packdir in pg.inner_text("#owDir"), "前に作ったパックがあると、上書きの確認に出力先とファイルが出る")
            pg.click("#owCancel")
            wait_js(pg, "!document.querySelector('#dlgOverwrite').open && !document.querySelector('#pkBuild').disabled", 10000)
            check(pg.is_hidden("#pkJob") and pg.inner_text("#pkLastPill") == "作り直しが要る", "「やめる」なら作らない")
            mt = os.path.getmtime(os.path.join(packdir, TP_LUA))
            pg.click("#pkBuild")
            wait_js(pg, "document.querySelector('#dlgOverwrite').open", 20000)
            pg.click("#owOk")
            wait_js(pg, "!document.querySelector('#pkBuild').disabled && document.querySelector('#pkJob').hidden && document.querySelector('#pkLastPill').textContent === '前回のパック'", 120000)
            ip2 = read_pack_plan(os.path.join(packdir, TP_LUA))
            check(os.path.getmtime(os.path.join(packdir, TP_LUA)) > mt and len(ip2.get("cuts", [])) == 3, "「上書きして作り直す」で今のカット(3区間)で作り直す")
            menu_open = "menu-closed" not in (pg.get_attribute(".app", "class") or "")
            pg.click("[data-strip=files]")
            wait_js(pg, "/パック済み/.test(document.querySelector('#txList .txi.cur').textContent)", 10000)
            check(True, "履歴の一覧の行に「パック済み」が出る")
            pg.keyboard.press("Escape")

            # ==================== 3d) zip でダウンロード(詳しい設定。中身は同じ cut2resolve の Text+ パック・同じ区間) ====================
            pg.evaluate("document.querySelector('#pkMore').open = true")
            with pg.expect_download(timeout=60000) as dl_info:
                pg.click("#pkZip")
            zpath = os.path.join(tmp, "dl-resolve.zip")
            dl_info.value.save_as(zpath)
            with zipfile.ZipFile(zpath) as z:
                names = z.namelist()
                ip_name = next((n for n in names if n.endswith("/" + TP_LUA)), None)
                if ip_name:
                    lua_path = os.path.join(tmp, "zip-" + TP_LUA)
                    with open(lua_path, "wb") as f:
                        f.write(z.read(ip_name))
                ipz = read_pack_plan(lua_path) if ip_name else {}
            check(any(n.endswith("/media/" + os.path.basename(media)) for n in names) and ip_name is not None and not any(n.endswith(".edl") for n in names),
                  "「zip でダウンロード」で Text+ パック(動画・Lua。最小限)をダウンロードできる: %s" % names[:4])
            check(ipz.get("target") == {"fps": 30, "width": 1920, "height": 1080} and ipz.get("cuts") == ip2.get("cuts") and ipz.get("captions"),
                  "zip にも選んだ fps・大きさと、パックと同じ区間(カットのとおり)が入る: %s" % {k: ipz.get(k) for k in ("target",)})
            wait_js(pg, "[...document.querySelectorAll('.toast, [role=status]')].some(e => /パック\\(zip\\)を作成しました/.test(e.textContent))", 10000)
            check(True, "作成できたことを画面に知らせる")

            # ==================== 4) 認識ワーカーの異常終了からの立ち直り ====================
            pids_before = find_worker_pids(tmp)
            check(len(pids_before) == 1, "認識ワーカー(tx_worker.py)が1本だけ動いている: %s" % pids_before)
            if pids_before:
                os.kill(pids_before[0], getattr(signal, "SIGKILL", signal.SIGTERM))   # Windows は SIGTERM = 強制終了(TerminateProcess)
            time.sleep(0.5)
            st, status = call(port, "GET", "/api/status", prefix="")
            check(st == 200 and any(t["id"] == "transcribe" for t in status.get("tools", [])), "ワーカーを落としても入口の /api/status は動く")
            check(proc.poll() is None, "入口のプロセスは動いたまま(ワーカーが落ちても道連れにならない)")

            pg.click("[data-edtab=tx]")   # 左のメニューは 1 文字起こし のタブで開いている(カット・パックのタブでは細い帯)
            if "menu-closed" in (pg.get_attribute(".app", "class") or ""):
                pg.click("#btnMenu")
            pg.click("[data-side-tab=start]")
            pg.fill("#srcPath", media)
            pg.fill("#jTitle", "ワーカー再起動後")
            pg.click("#btnStart")
            open_doc(pg, "ワーカー再起動後")
            texts2 = pg.evaluate("[...document.querySelectorAll('#segs textarea')].map(e => e.value)")
            check(texts2[:2] == ["テスト文1", "テスト文2"], "ワーカーを強制終了したあとの文字起こしも成功する(次の要求で起動し直す): %s" % texts2)
            pids_after = find_worker_pids(tmp)
            check(len(pids_after) == 1 and pids_after != pids_before, "新しい認識ワーカー(別プロセス)が起動している: %s → %s" % (pids_before, pids_after))

            check(not errors, "画面のエラー・コンソールエラーが無い: %s" % errors[:5])
            b.close()

        # ==================== 5) 合言葉なしの書き込みは 403 ====================
        st, body = call(port, "POST", "/api/transcribe", body={"sourcePath": media})
        check(st == 403 and body.get("error") == "token", "合言葉(X-YTT-Token)なしの POST は 403: %s %s" % (st, body))
    finally:
        if proc is not None:
            if os.name == "nt":   # Windows は黒い画面の×・Ctrl+Break と同じ SIGBREAK(app/launch.py はこれで後始末してから終わる)
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()   # Linux は SIGTERM
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
            check(proc.returncode is not None, "終了の合図(SIGTERM / Windows は SIGBREAK)で入口のプロセスが終わる")
            remaining = find_worker_pids(tmp)
            check(not remaining, "入口を終えると認識ワーカーの子プロセスも残らない: %s" % remaining)
            check(not os.path.exists(os.path.join(rt, "transcribe.json")), "入口を終えると .runtime/transcribe.json が消える")
        shutil.rmtree(tmp, ignore_errors=True)

    print("ALL PASSED" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
