#!/usr/bin/env python3
"""入口の画面の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、空きポートだけを使う)。

    python app/e2e_portal.py [--shots <フォルダ>]

3つのカードが「動作中」になる → 開く(ツールの画面が新しいタブで開く)→ ログ(XSS にならない)→ 停止・起動 → 再起動 →
異常終了の表示 → テーマ → 切断の表示 → すべて終了(2回押し)で子が止まる、を確かめる。--shots で画面の写真を残す。
"""
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from unittest import mock

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launch as L  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    def wait_js(pg, expr, timeout=30000):
        """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
        end = time.time() + timeout / 1000
        while time.time() < end:
            if pg.evaluate(expr):
                return True
            time.sleep(0.1)
        return False

    def card_state(pg, tid):
        return pg.evaluate("id => { const c = document.querySelector('.pt-tool[data-tool=\"' + id + '\"]'); return c && c.getAttribute('data-state'); }", tid)

    def wait_card(pg, tid, state, timeout=40000):
        return wait_js(pg, "document.querySelector('.pt-tool[data-tool=\"%s\"]')?.getAttribute('data-state') === '%s'" % (tid, state), timeout)

    tmp = tempfile.mkdtemp(prefix="ytt-portal-e2e-")
    env = {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake"}
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    for s in L.TOOLS:
        _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
    shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))   # 共通部品(本物と同じ並び)
    ports = dict(zip(L.TOOL_IDS, free_ports(3)))
    events = []
    env["STUDIO_HOME"] = os.path.join(tmp, "studio-home")
    os.environ["STUDIO_HOME"] = env["STUDIO_HOME"]
    sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=ports, mounts=("studio",))   # 本番と同じくスタジオは取り込む
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/" % port
    errors = []
    try:
        sup.start_all()
        sup.start_monitor()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            pg = ctx.new_page()
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(base)

            # 1. 3つのカードが作業の順に並び、動作中になる
            check(wait_js(pg, "document.querySelectorAll('.pt-tool').length === 3", 10000), "カードが3枚")
            order = pg.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => e.getAttribute('data-tool'))")
            check(order == ["studio", "transcribe", "cut2resolve"], "作業の順(スタジオ→文字起こし→cut2resolve): %s" % order)
            for tid in L.TOOL_IDS:
                check(wait_card(pg, tid, "running"), "%s が動作中" % tid)
            check(pg.text_content("#ver") == "入口 v" + L.VERSION, "ヘッダーの版: %s" % pg.text_content("#ver"))
            check(pg.text_content("#conn") == "接続中", "接続中の表示")
            meta = pg.text_content(".pt-tool[data-tool=studio] .pt-meta")
            check(("ポート %d" % port) in meta and "v0.3.0" in meta and "入口に取り込み" in meta, "スタジオは入口に取り込み: %s" % meta)
            meta = pg.text_content(".pt-tool[data-tool=transcribe] .pt-meta")
            check(("ポート %d" % ports["transcribe"]) in meta, "文字起こしは別のプログラム: %s" % meta)
            check(pg.is_disabled(".pt-tool[data-tool=studio] .pt-toggle") and pg.is_disabled(".pt-tool[data-tool=studio] .pt-restart"),
                  "取り込んだスタジオは単独で止めない(停止・再起動は押せない)")
            if shots:
                os.makedirs(shots, exist_ok=True)
                pg.evaluate("UIKit.theme.set('light')")
                time.sleep(0.4)   # 色の切り替えのアニメーションが終わるまで
                pg.screenshot(path=os.path.join(shots, "portal-light.png"), full_page=True)

            # 2. 開く: 新しいタブでスタジオの画面が開く(入口のポートからのリンクをツールが 403 にしない)
            href = pg.get_attribute(".pt-tool[data-tool=studio] .pt-open", "href")
            check(href == "http://127.0.0.1:%d/studio/" % port, "開くのリンクは同じアドレスの /studio/: %s" % href)
            with ctx.expect_page() as info:
                pg.click(".pt-tool[data-tool=studio] .pt-open")
            tab = info.value
            tab.wait_for_load_state()
            check("切り抜きスタジオ" in (tab.title() + tab.content()), "スタジオの画面が開いた")
            check(wait_js(tab, "!!(window.Studio && Studio.state)", 20000), "スタジオの画面が /studio/ の下で API を読めた(CSP・相対パス)")
            check(tab.evaluate("Studio.base") == "/studio" and bool(tab.evaluate("Studio.token")), "スタジオは場所と合言葉を知っている")
            tab.click("#toolMenu summary")
            links = tab.eval_on_selector_all("#toolNav a", "els => els.map(a => a.getAttribute('href'))")
            check(any(h.endswith(":%d/" % ports["transcribe"]) for h in links) and "/studio/" in links, "スタジオの「他のツール」: 文字起こしは別のポート・自分は /studio/: %s" % links)
            u = tab.evaluate("UIKit.tools.url('studio', Studio.ports, '/?url=x')")
            check(u == "http://localhost:%d/studio/?url=x" % port, "他のツールから取り込んだスタジオへのリンク(ui-kit の paths): %s" % u)
            check(tab.evaluate("window.opener") is None, "開いたタブから入口を操作できない(noopener)")
            tab.close()

            # 3. ログ: 開くと末尾が出る。題名などに HTML が入っていても実行されない
            tx = sup.by_id["transcribe"]
            with open(tx.log_path, "a", encoding="utf-8") as f:
                f.write('題名 <img src=x onerror="window.__xss=1"> テスト\n')
            pg.click(".pt-tool[data-tool=transcribe] .pt-logbox summary")
            check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-log').textContent.includes('onerror')"), "ログが表示される")
            check(pg.evaluate("window.__xss") is None and pg.query_selector(".pt-log img") is None, "ログの HTML は文字として表示(XSS なし)")
            check("transcribe.log" in pg.text_content(".pt-tool[data-tool=transcribe] .pt-logpath"), "ログの場所の表示")

            # 4. 停止 → 起動
            pg.click(".pt-tool[data-tool=cut2resolve] .pt-toggle")
            check(wait_card(pg, "cut2resolve", "stopped"), "cut2resolve を停止")
            check(pg.get_attribute(".pt-tool[data-tool=cut2resolve] .pt-open", "aria-disabled") == "true", "停止中は「開く」が押せない")
            check(pg.text_content(".pt-tool[data-tool=cut2resolve] .pt-toggle") == "起動", "ボタンが「起動」になる")
            check(pg.is_disabled(".pt-tool[data-tool=cut2resolve] .pt-restart"), "停止中は再起動が押せない")
            pg.click(".pt-tool[data-tool=cut2resolve] .pt-toggle")
            check(wait_card(pg, "cut2resolve", "running"), "cut2resolve を起動")

            # 5. 再起動
            old_pid = sup.by_id["transcribe"].proc.pid
            pg.click(".pt-tool[data-tool=transcribe] .pt-restart")
            check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-pill').textContent.includes('再起動')", 5000)
                  or card_state(pg, "transcribe") in ("starting", "running"), "再起動中の表示")
            check(wait_for(lambda: sup.by_id["transcribe"].snapshot()["starts"] == 2, 30), "再起動した(起動の回数が2)")
            check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-pill').textContent === '動作中'"
                              " && document.querySelector('.pt-tool[data-tool=transcribe]').getAttribute('data-state') === 'running'"),
                  "文字起こしが再起動後に動作中")
            proc = sup.by_id["transcribe"].proc
            check(proc is not None and proc.pid != old_pid, "別のプロセスになった")

            # 6. 異常終了の表示(子を外から強制終了)
            os.kill(sup.by_id["cut2resolve"].proc.pid, signal.SIGKILL)
            check(wait_card(pg, "cut2resolve", "crashed"), "異常終了の表示")
            msg = pg.text_content(".pt-tool[data-tool=cut2resolve] .pt-msg")
            check("異常終了" in msg and not pg.is_hidden(".pt-tool[data-tool=cut2resolve] .pt-msg"), "異常終了のメッセージ: %s" % msg)
            check(pg.text_content(".pt-tool[data-tool=cut2resolve] .pt-toggle") == "起動", "異常終了のあと「起動」が押せる")
            if shots:
                pg.evaluate("UIKit.theme.set('dark')")
                time.sleep(0.4)
                pg.screenshot(path=os.path.join(shots, "portal-dark-crashed.png"), full_page=True)
            pg.click(".pt-tool[data-tool=cut2resolve] .pt-toggle")
            check(wait_card(pg, "cut2resolve", "running"), "起動し直せる")

            # 7. テーマ(ui-kit)
            before = pg.get_attribute("html", "data-theme")
            pg.click("[data-theme-toggle]")
            after = pg.get_attribute("html", "data-theme")
            check(before != after and after in ("light", "dark"), "テーマの切り替え %s → %s" % (before, after))

            # 8. 狭い画面(縦に並ぶ・横にはみ出さない)
            mob = ctx.new_page()
            mob.set_viewport_size({"width": 375, "height": 800})
            mob.goto(base)
            check(wait_js(mob, "document.querySelectorAll('.pt-tool[data-state=running]').length === 3"), "狭い画面でも表示")
            check(mob.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "狭い画面で横にはみ出さない")
            xs = mob.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => Math.round(e.getBoundingClientRect().left))")
            check(len(set(xs)) == 1, "狭い画面では縦に並ぶ: %s" % xs)
            if shots:
                mob.screenshot(path=os.path.join(shots, "portal-mobile.png"), full_page=True)

            # 9. すべて終了(2回押し)
            pg.click("#btnQuit")
            check(pg.text_content("#btnQuit") == "もう一度押すと終了します", "1回目は確認だけ")
            check(sup.by_id["transcribe"].proc is not None, "1回目ではまだ止まらない")
            procs = [t.proc for t in sup.tools if t.proc]
            pg.click("#btnQuit")
            check(wait_js(pg, "!document.getElementById('done').hidden", 5000), "終了中の表示")
            th.join(30)
            check(not th.is_alive(), "入口のサーバーが止まった")
            srv.server_close()   # launch.main() と同じく、待ち受けを閉じる
            check(wait_js(pg, "document.getElementById('doneTitle').textContent === 'すべて終了しました'", 20000), "終了の表示")
            check(all(pr.poll() is not None for pr in procs), "3つのツールが止まった")
            sup.unmount_all()   # launch.main() の終了処理と同じ(request_shutdown でも呼ばれる)
            check(not any(os.path.exists(os.path.join(env["YTT_RUNTIME_DIR"], t + ".json")) for t in L.TOOL_IDS), ".runtime が片付いた(取り込んだスタジオも)")

            # 10. 入口が止まったら、開いたままの別のタブに「接続できません」を出す
            check(wait_js(mob, "!document.getElementById('errbar').hidden", 15000), "切断の表示")
            check(mob.is_disabled(".pt-tool[data-tool=studio] .pt-toggle"), "切断中は操作できない")

            real_errors = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
            check(not real_errors, "画面のエラーなし(CSP 違反を含む): %s" % real_errors[:3])
            browser.close()
    finally:
        if not srv.closing.is_set():
            srv.shutdown()
        sup.close()
        sup.stop_all()
        srv.server_close()
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(events[-20:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
