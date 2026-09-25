#!/usr/bin/env python3
"""文字起こしツールを入口(app/launch.py)に取り込んだ形の通し確認(統合計画の段階3-3)。

    python3 e2e_ui_mounted.py

本物の入口(app/launch.py --only transcribe)を子プロセスとして起動し、http://localhost:<port>/transcribe/ で:
  - CSP(app/mount.py の MOUNTS["transcribe"]["csp"])の下で画面が動く・合言葉(<meta name="ytt-token">)が入る
  - 認識は別プロセスのワーカー(tx_worker.py。TRANSCRIBE_BACKEND=worker-fake でワーカーの中だけ偽のモデル)を通る
  - ワーカーを強制終了しても、入口・次の文字起こしは止まらない(次の要求で起動し直す)
  - 動画は /transcribe/media?... の下から読む
  - 書き込み系 API(PUT・POST)は合言葉(X-YTT-Token)が要る
  - 終了(SIGTERM)すると、ワーカーの子プロセスも .runtime/transcribe.json も残らない
を確かめる。ffmpeg と Playwright の chromium が必要。
"""
import glob
import json
import os
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

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# app/test_launch.py の _copy_tool と同じ規則(実行時データ・秘密情報を写さない)
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.log", "data.json*", "feedback.jsonl*", "config.json", "settings*.json", "registry.json", "cache", "archive",
    "exports", "clips", "transcripts", "dataset", "models", "work", ".venv", "*.mp4", "resolve-ui-test", "node_modules", ".running.json")


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
    """/proc を見て、この確認が起動した tx_worker.py(一時フォルダの下のもの)の pid を探す。"""
    needle = os.path.join(tmp, "transcribe-tool", "tx_worker.py").encode()
    pids = []
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
        # clip-studio・cut2resolve は写さない(--only transcribe なら Supervisor はそのツールの Tool を作らないので不要。app/launch.py 参照)

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

        port = free_port()
        env = dict(os.environ, YTT_RUNTIME_DIR=rt, TRANSCRIBE_BACKEND="worker-fake", TRANSCRIBE_FAKE_DELAY="0.05")
        proc = subprocess.Popen([sys.executable, os.path.join(tmp, "app", "launch.py"), "--port", str(port), "--no-open", "--only", "transcribe"],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

            # ==================== 4) 認識ワーカーの異常終了からの立ち直り ====================
            pids_before = find_worker_pids(tmp)
            check(len(pids_before) == 1, "認識ワーカー(tx_worker.py)が1本だけ動いている: %s" % pids_before)
            if pids_before:
                os.kill(pids_before[0], signal.SIGKILL)
            time.sleep(0.5)
            st, status = call(port, "GET", "/api/status", prefix="")
            check(st == 200 and any(t["id"] == "transcribe" for t in status.get("tools", [])), "ワーカーを落としても入口の /api/status は動く")
            check(proc.poll() is None, "入口のプロセスは動いたまま(ワーカーが落ちても道連れにならない)")

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
            proc.terminate()   # Linux なので SIGTERM(app/launch.py はこれで後始末してから終わる)
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
            check(proc.returncode is not None, "SIGTERM で入口のプロセスが終わる")
            remaining = find_worker_pids(tmp)
            check(not remaining, "入口を終えると認識ワーカーの子プロセスも残らない: %s" % remaining)
            check(not os.path.exists(os.path.join(rt, "transcribe.json")), "入口を終えると .runtime/transcribe.json が消える")
        shutil.rmtree(tmp, ignore_errors=True)

    print("ALL PASSED" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
