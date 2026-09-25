#!/usr/bin/env python3
"""cut2resolve の画面の通し確認(Playwright + ffmpeg。空きポート・一時フォルダだけを使う)。

    python e2e_ui.py
    python e2e_ui.py --mounted       # 入口(app/launch.py)の統合サーバーに取り込んだ形(http://localhost:<port>/cut2resolve/・合言葉あり)で同じ確認をする

入力(URL で埋める)→ 読み込み → 試算(無音カット)→ パック作成 → 上書きの確認 → 結果の表示、テーマの保存、XSS を確かめる。
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mounted = "--mounted" in argv
    prefix = "/cut2resolve" if mounted else ""
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="c2r-e2e-")
    video = os.path.join(tmp, "サンプル 動画 & 'テスト'.mp4")   # 日本語・スペース・記号を含む名前(Windows で使える記号だけ)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-af", "volume='if(between(t,3,5)+between(t,8,9.5),0,1)':eval=frame",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
    srt = os.path.join(tmp, "subs.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,500 --> 00:00:02,500\n<img src=x onerror=alert(1)>こんにちは\n\n2\n00:00:06,000 --> 00:00:07,500\n二行目\n")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rt = os.path.join(tmp, "rt")
    env = dict(os.environ, YTT_RUNTIME_DIR=rt)
    if mounted:   # 本物の入口を起動する(start-all.bat と同じ。cut2resolve だけ)
        cmd = [sys.executable, os.path.join(os.path.dirname(HERE), "app", "launch.py"), "--port", str(port), "--no-open", "--only", "cut2resolve"]
    else:
        cmd = [sys.executable, os.path.join(HERE, "serve.py"), str(port), "--no-open"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors = []

    def wait_js(pg, expr, timeout=20000):
        """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
        end = time.time() + timeout / 1000
        while time.time() < end:
            if pg.evaluate(expr):
                return True
            time.sleep(0.1)
        raise TimeoutError(expr)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d%s/api/ping" % (port, prefix), timeout=1).read()
                break
            except Exception:
                time.sleep(0.1)
        q = "?video=" + urllib.parse.quote(video) + "&srt=" + urllib.parse.quote(srt)
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            # CSP の違反はコンソールに出る(上書きの確認の 409 などの「Failed to load resource」は想定内なので数えない)
            pg.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and errors.append("console: " + m.text))
            pg.on("dialog", lambda d: (errors.append("dialog: " + d.message), d.dismiss()))
            pg.goto("http://localhost:%d%s/%s" % (port, prefix, q))
            pg.wait_for_timeout(600)
            check(pg.input_value("#inVideo") == video, "URL の ?video= で動画の欄が埋まる")
            check(pg.input_value("#inSrt") == srt, "URL の ?srt= で字幕の欄が埋まる")
            check("video=" not in pg.url, "読んだあと URL から値を消す")
            check(pg.is_visible("#linkNotice"), "リンクから開いたことを知らせる(自動では読み込まない)")
            check(pg.inner_text("#ver").strip().startswith("v"), "ヘッダーに版が出る")
            if mounted:
                check(pg.evaluate("!!document.querySelector('meta[name=\"ytt-token\"]')"), "入口が合言葉を画面に入れている")
                check(pg.evaluate("location.pathname.startsWith('/cut2resolve/')"), "画面の場所は /cut2resolve/")

            # テーマの切り替えが保存される
            before = pg.evaluate("document.documentElement.dataset.theme")
            pg.click("[data-theme-toggle]")
            after = pg.evaluate("document.documentElement.dataset.theme")
            check(before != after, "テーマ切り替えのボタンで見た目が変わる")
            pg.reload()
            pg.wait_for_timeout(400)
            check(pg.evaluate("document.documentElement.dataset.theme") == after, "テーマの選択が再読み込み後も残る")

            # 読み込み → 試算
            pg.fill("#inVideo", video)
            pg.fill("#inSrt", srt)
            pg.click("#btnInspect")
            wait_js(pg, "document.querySelector('#stVideo').textContent.includes('fps')", 20000)
            check("320×180" in pg.inner_text("#stVideo") or "320x180" in pg.inner_text("#stVideo"), "動画の情報(解像度・fps)を表示する")
            pg.click("#btnPlan")
            wait_js(pg, "!document.querySelector('#stats').hidden && document.querySelector('#stats').textContent.includes('残す')", 60000)
            stats = pg.inner_text("#stats")
            check("区間" in stats, "試算の結果(残す・削る・区間)を表示する: " + stats.replace("\n", " ")[:80])
            check(pg.locator("#laneCut > *").count() >= 2, "タイムラインに残す/削る区間の帯が出る")
            check(pg.evaluate("document.querySelectorAll('img').length") == 0 and not errors, "字幕の中の HTML は実行されない(エスケープ)")

            # パック作成 → もう一度作ると上書きの確認 → 取り消し → 上書き
            pg.click("#btnBuild")
            pg.wait_for_selector("#result:not([hidden])", timeout=60000)
            files = pg.inner_text("#resFiles")
            check(".edl" in files and "友人へ" in files, "パックのファイル一覧を表示する")
            out_dir = pg.inner_text("#resDir").strip()
            check(os.path.isdir(out_dir) and any(n.endswith(".edl") for n in os.listdir(out_dir)), "実際に EDL が作られる")
            check(pg.is_visible("#resReadme") or pg.locator("#readmeBox").count() == 1, "友人へ.txt の中身を見られる")
            pg.click("#btnBuild")
            pg.wait_for_selector("#dlgOverwrite[open]", timeout=20000)
            check(pg.is_visible("#owFiles"), "既存の出力があると上書きの確認を出す")
            pg.click("#owCancel")
            check(not pg.evaluate("document.querySelector('#dlgOverwrite').open"), "取り消すと閉じる")
            edl = [n for n in os.listdir(out_dir) if n.endswith(".edl")][0]
            m0 = os.path.getmtime(os.path.join(out_dir, edl))
            time.sleep(1.1)
            pg.click("#btnBuild")
            pg.wait_for_selector("#dlgOverwrite[open]", timeout=20000)
            pg.click("#owOk")
            wait_js(pg, "!document.querySelector('#dlgOverwrite').open", 20000)
            pg.wait_for_timeout(2500)
            check(os.path.getmtime(os.path.join(out_dir, edl)) > m0, "確認して上書きすると作り直す")

            # 狭い画面ではみ出さない
            pg.set_viewport_size({"width": 390, "height": 800})
            pg.wait_for_timeout(300)
            check(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "390 幅で横にはみ出さない")
            if mounted:
                src = pg.evaluate("document.querySelector('video') && document.querySelector('video').getAttribute('src') || ''")
                check(src.startswith("/cut2resolve/media/"), "プレビューの動画も /cut2resolve/ の下から読む: " + src[:40])
            check(not errors, "画面のエラーが無い: %s" % errors[:3])
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(15 if mounted else 5)
        except Exception:
            proc.kill()
        if mounted:
            check(not os.path.exists(os.path.join(rt, "cut2resolve.json")), "入口を終えると .runtime の記録が消える")
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
