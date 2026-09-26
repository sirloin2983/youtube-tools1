#!/usr/bin/env python3
"""段階7(画面の形の準備と窓)の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、3つとも入口に取り込む)。

    python app/e2e_window.py

  7-0 画面のエラーの記録: スタジオ・文字起こしの画面で起きたエラー(throw・Promise の失敗)が client-errors.jsonl に1行ずつ残る
  7-1 解析の設定: 以前のブラウザの保存(localStorage)がサーバーへ1回だけ引き継がれ、以後はサーバーの値が勝つ。変えた直後に離れても送られる
  7-2 離れた・戻った: 別の窓へ移った(blur)で「離れた」、埋め込み(iframe)にフォーカスがあるときは離れたことにしない、戻った(focus)
  7-3 窓: 入口の「窓で開く(試用)」の切り替え。窓(display-mode: standalone)の中の「開く」は入口に頼んで Edge のアプリモードで開き
      (Edge の代わりに引数を記録する偽のプログラム。YTT_APP_BROWSER)、外のサイトはいつものブラウザ(偽の記録)で開く。
      普通のタブでは今までどおり新しいタブで開く

Edge の本物の窓(リンクの行き先・YouTube の埋め込み・閉じる操作)はクラウド(Linux)で再現できないので、実機で確かめる。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.request
from unittest import mock

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import appwindow as W  # noqa: E402
import launch as L  # noqa: E402
import mount as M  # noqa: E402
from e2e_portal import wait_js  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports  # noqa: E402
from ytt_core import fsio  # noqa: E402

APP_MODE = """(() => {   // Edge のアプリモードの窓のふり(display-mode: standalone)
  const real = window.matchMedia.bind(window);
  window.matchMedia = q => /display-mode:\\s*standalone/.test(q) ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : real(q);
})();"""


def fake_browser(tmp):
    """Edge の代わり: 渡された引数を1行の JSON で記録するだけのプログラム"""
    log = os.path.join(tmp, "fake-edge.jsonl")
    path = os.path.join(tmp, "fake-edge")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\nimport json, sys\nwith open(%r, 'a', encoding='utf-8') as f:\n    f.write(json.dumps(sys.argv[1:]) + '\\n')\n" % (sys.executable, log))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    if os.name == "nt":   # Windows は #! のファイルを実行できないので、同じ Python で動かす .bat を挟む
        bat = path + ".bat"
        with open(bat, "w", encoding="ascii", newline="\r\n") as f:
            f.write('@"%s" "%s" %%*\n' % (sys.executable, path))
        return bat, log
    return path, log


def read_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f.read().splitlines() if x.strip()]
    except OSError:
        return []


def wait_until(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return fn()


def main():
    ok = True
    events = []

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-window-e2e-")
    exe, edge_log = fake_browser(tmp)
    env = {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake",
           "STUDIO_HOME": os.path.join(tmp, "studio-home"), "YTT_APP_BROWSER": exe}
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    srv = sup = th = None
    try:
        for s in L.TOOLS:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        ports = dict(zip(L.TOOL_IDS, free_ports(3)))
        sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=ports, mounts=tuple(M.MOUNTS))
        srv, port = L.make_server(0, sup)
        browsed = []
        srv.window = W.Opener(os.path.join(tmp, "app"), fsio.atomic_write, browser_open=lambda u: browsed.append(u) or True, log=events.append)
        sup.attach(srv)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        sup.start_all()
        base = "http://127.0.0.1:%d/" % port
        clog = srv.client_log.path

        def studio_settings():
            with urllib.request.urlopen(urllib.request.Request(base + "studio/api/settings", headers={"Host": "127.0.0.1:%d" % port}), timeout=10) as r:
                return json.loads(r.read())["settings"]

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                errors = []
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                # 以前のブラウザの保存(解析の設定)。ページを開くたびに入れ直す(サーバーに保存した後は無視されることも確かめる)
                ctx.add_init_script("try { localStorage.setItem('clipstudio:queue:opts', JSON.stringify({count: '12', sens: 'low', useChat: false})); } catch (e) {}")
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base)
                check(wait_js(pg, "document.querySelectorAll('.pt-tool[data-state=running]').length === 2", 60000), "スタジオと編集が入口に取り込んで動作中(cut2resolve は部品なのでカードを出さない)")

                # ---- 7-3 入口の「窓で開く(試用)」 ----
                check(wait_js(pg, "!document.getElementById('winBox').hidden", 10000), "[7-3] 入口に「窓で開く(試用)」が出る")
                check(pg.is_checked("#winMode") is False and pg.is_enabled("#winMode"), "[7-3] 既定はブラウザのまま(オフ)・Edge があるので切り替えられる")
                check(pg.is_visible("#btnWinNow"), "[7-3] 普通のタブでは「いま窓で開く」が出る")
                pg.click("#winMode")
                check(wait_js(pg, "document.querySelector('#toast').textContent.indexOf('窓で開きます') >= 0", 10000), "[7-3] オンにした(次の起動から)")
                check(W.read_mode(srv.window.settings_path) == "app", "[7-3] 設定が settings.json に残る: %s" % srv.window.settings_path)
                pg.click("#btnWinNow")
                got = wait_until(lambda: read_lines(edge_log))
                check(got and got[-1][0] == "--app=http://localhost:%d/" % port and got[-1][1].startswith("--user-data-dir=") and
                      got[-1][1].endswith(os.path.join("app", "browser-profile")), "[7-3] 「いま窓で開く」で Edge(偽)がアプリモード・専用のプロファイルで起動: %s" % got[-1:])
                check(not any("remote-debugging" in a for a in (got[-1] if got else [])), "[7-3] リモートデバッグのポートは開かない")
                # 普通のタブ: 開くは今までどおり新しいタブ
                with ctx.expect_page() as info:
                    pg.click(".pt-tool[data-tool=transcribe] .pt-open")
                tab = info.value
                tab.wait_for_load_state()
                check("/transcribe/" in tab.url, "[7-3] 普通のタブでは「開く」は新しいタブ(今までどおり)")
                tab.close()

                # 窓の中(display-mode: standalone のふり)
                actx = browser.new_context(viewport={"width": 1200, "height": 850})
                actx.add_init_script(APP_MODE)
                win = actx.new_page()
                win.on("pageerror", lambda e: errors.append(str(e)))
                win.goto(base)
                check(wait_js(win, "document.querySelectorAll('.pt-tool[data-state=running]').length === 2", 30000), "[7-3] 窓の中の入口")
                check(win.evaluate("UIKit.win.isApp()") is True and not win.is_visible("#btnWinNow"), "[7-3] 窓の中では「いま窓で開く」を出さない")
                n0 = len(read_lines(edge_log))
                opened = []
                actx.on("page", lambda pg2: opened.append(pg2.url))
                win.click(".pt-tool[data-tool=studio] .pt-open")
                got = wait_until(lambda: read_lines(edge_log)[n0:])
                check(got and got[-1][0] == "--app=http://localhost:%d/studio/" % port, "[7-3] 窓の中の「開く」は Edge のアプリモードの窓で開く: %s" % got[-1:])
                time.sleep(0.5)
                check(not opened, "[7-3] 窓の中ではタブを増やさない: %s" % opened)
                win.evaluate("""() => { const a = document.createElement('a'); a.id = 'ext'; a.href = 'https://www.youtube.com/watch?v=abc123DEF45'; a.target = '_blank';
                                        a.rel = 'noopener'; a.textContent = 'yt'; document.body.appendChild(a); }""")
                win.click("#ext")
                check(wait_until(lambda: browsed) == ["https://www.youtube.com/watch?v=abc123DEF45"], "[7-3] 外のサイトはいつものブラウザで開く: %s" % browsed)
                # 窓の中のスタジオ: 「他のツール」のリンクも窓で
                win.goto(base + "studio/")
                check(wait_js(win, "!!(window.Studio && Studio.state)", 30000), "[7-3] 窓の中のスタジオ")
                win.click("#toolMenu summary")
                n1 = len(read_lines(edge_log))
                win.click("#toolNav a[href*='/transcribe/']")
                got = wait_until(lambda: read_lines(edge_log)[n1:])
                check(got and got[-1][0] == "--app=http://localhost:%d/transcribe/" % port, "[7-3] 取り込んだツールの画面からも窓で開く(/studio/api/ytt/… → 入口): %s" % got[-1:])
                actx.close()
                pg.click("#winMode")   # オフに戻す
                check(wait_js(pg, "document.querySelector('#toast').textContent.indexOf('いつものブラウザ') >= 0", 10000) and W.read_mode(srv.window.settings_path) == "browser",
                      "[7-3] オフに戻せる")

                # ---- 7-1 解析の設定 ----
                st = ctx.new_page()
                st.on("pageerror", lambda e: errors.append(str(e)))
                st.goto(base + "studio/")
                check(wait_js(st, "!!document.getElementById('count')", 30000), "[7-1] スタジオの ② の設定")
                saved = wait_until(lambda: studio_settings().get("analyze"))
                check(saved and saved.get("count") == 12 and saved.get("sensitivity") == "low" and saved.get("useChat") is False and "noCache" not in saved,
                      "[7-1] 以前のブラウザの保存を1回だけサーバーへ引き継いだ: %s" % saved)
                check(st.evaluate("document.getElementById('count').value") == "12" and st.evaluate("document.getElementById('sens').value") == "low",
                      "[7-1] 欄にも入った")
                st.evaluate("() => { const e = document.getElementById('count'); e.value = '5'; e.dispatchEvent(new Event('change')); }")
                st.evaluate("() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }")   # すぐ別の窓へ(0.4秒待たずに送る)
                check(wait_until(lambda: studio_settings().get("analyze", {}).get("count") == 5, 3), "[7-1][7-2] 変えた直後に窓を離れても保存された")
                st.reload()
                check(wait_js(st, "document.getElementById('count') && document.getElementById('count').value === '5'", 20000),
                      "[7-1] 読み込み直すとサーバーの値(localStorage の古い値 12 ではない): %s" % st.evaluate("document.getElementById('count') && document.getElementById('count').value"))
                check(studio_settings()["analyze"]["count"] == 5, "[7-1] 引き継ぎは1回だけ(サーバーの値を上書きしない)")

                # ---- 7-2 離れた・戻った ----
                st.evaluate("""() => { window.__ev = []; UIKit.life.onLeave(r => __ev.push('leave:' + r)); UIKit.life.onReturn(r => __ev.push('back:' + r));
                                       document.hasFocus = () => true; }""")
                st.evaluate("() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('blur')); }")
                time.sleep(0.4)
                check(st.evaluate("__ev") == [], "[7-2] フォーカスが画面の中(埋め込みの YouTube など)なら離れたことにしない: %s" % st.evaluate("__ev"))
                st.evaluate("() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }")
                time.sleep(0.4)
                st.evaluate("() => { window.dispatchEvent(new Event('blur')); }")
                time.sleep(0.4)
                st.evaluate("() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('focus')); }")
                st.evaluate("() => { window.dispatchEvent(new Event('pagehide')); }")
                check(st.evaluate("__ev") == ["leave:blur", "back:focus", "leave:pagehide"],
                      "[7-2] 別の窓へ → 1回だけ離れた、戻った → 1回だけ、閉じる直前 → 離れた: %s" % st.evaluate("__ev"))
                st.evaluate("""() => { __ev.length = 0; window.dispatchEvent(new Event('focus'));
                  const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
                  document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }""")
                time.sleep(0.4)
                st.evaluate("""() => { const set = v => Object.defineProperty(document, 'hidden', { configurable: true, get: () => v });
                  set(true); document.dispatchEvent(new Event('visibilitychange')); document.dispatchEvent(new Event('visibilitychange'));
                  set(false); document.dispatchEvent(new Event('visibilitychange')); delete document.hidden; }""")
                check(st.evaluate("__ev") == ["back:focus", "leave:blur", "leave:hidden", "back:visible"],
                      "[7-2] 隣の窓へ移ったあと最小化・タブの切り替え → もう一度「離れた」(再生の停止などをさせる): %s" % st.evaluate("__ev"))

                # ---- 7-0 画面のエラーの記録 ----
                st.evaluate("() => { setTimeout(() => { throw new Error('e2e-boom-studio'); }, 0); }")
                tx = ctx.new_page()
                tx.goto(base + "transcribe/")
                check(wait_js(tx, "!!document.querySelector('#ver')", 30000), "[7-0] 文字起こしの画面")
                tx.evaluate("() => { Promise.reject(new Error('e2e-reject-transcribe')); }")
                tx.evaluate("() => { setTimeout(() => { throw new Error('e2e-boom-studio'); }, 0); }")   # 別の画面なら同じ文も記録する
                mine = lambda: [e for e in read_lines(clog) if "e2e-" in e.get("message", "")]
                got = wait_until(lambda: len(mine()) >= 3 and mine(), 10) or mine()
                by = {(e["tool"], e["kind"]): e for e in got}
                s = by.get(("studio", "error"))
                check(s and "e2e-boom-studio" in s["message"] and s.get("page") == "/studio/" and s.get("version") == sup.by_id["studio"].snapshot()["version"],
                      "[7-0] スタジオの画面のエラーが記録された(画面・版・場所つき): %s" % s)
                t = by.get(("transcribe", "rejection"))
                check(t and "e2e-reject-transcribe" in t["message"] and t.get("page") == "/transcribe/", "[7-0] 文字起こしの Promise の失敗も: %s" % t)
                check(("transcribe", "error") in by, "[7-0] 画面ごとに記録(同じ文でも別の画面なら)")
                st.evaluate("() => { for (let i = 0; i < 3; i++) setTimeout(() => { throw new Error('e2e-boom-studio'); }, 0); }")
                time.sleep(1.0)
                n = len([e for e in read_lines(clog) if e["tool"] == "studio" and "e2e-boom-studio" in e.get("message", "")])
                check(n == 1, "[7-0] 同じ画面の同じエラーは1回だけ送る: %d 件" % n)
                with urllib.request.urlopen(urllib.request.Request(base + "api/log?tool=client&lines=50", headers={"Host": "127.0.0.1:%d" % port}), timeout=10) as r:
                    lines = json.loads(r.read())["lines"]
                check(any("e2e-reject-transcribe" in x for x in lines), "[7-0] 入口の /api/log?tool=client で読める")

                real = [e for e in errors if "e2e-" not in e]
                check(not real, "画面のエラーなし: %s" % real[:3])
                ctx.close()
            finally:
                browser.close()
    finally:
        if srv is not None:
            srv.shutdown()
            sup.close()
            sup.stop_all()
            sup.unmount_all()
            srv.server_close()
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(events[-30:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
