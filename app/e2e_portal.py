#!/usr/bin/env python3
"""入口の画面の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、空きポートだけを使う)。

    python app/e2e_portal.py [--shots <フォルダ>]

いまは「文字起こし」も入口に取り込める(段階3-3。app/mount.py の MOUNTS)ので、2つの形をそれぞれ確かめる:

  (A) 本番と同じ形(python app/launch.py と同じ mounts=tuple(mount.MOUNTS)): 3つとも入口に取り込み。
      3枚のカードが「入口に取り込み」で動作中になる → 開く(3つとも同じポートの /studio/・/transcribe/・/cut2resolve/ で
      新しいタブが開く。文字起こしの画面も #ver・合言葉・「他のツール」メニューを確かめる)→ 取り込んだものは
      停止・再起動が押せない → テーマ → 狭い画面 → すべて終了(2回押し)→ 切断の表示、を確かめる。
  (B) 文字起こしが子プロセスの形(--no-mount 相当・取り込めなかったときの落ち先。mounts=("studio", "cut2resolve")):
      文字起こしだけ黒い画面(別プロセス)で動く形で、子プロセスの管理(停止・起動・再起動・異常終了の表示・
      異常終了後の起動し直し・ログの表示と XSS 対策)を確かめる。studio・cut2resolve は (A) と同じく取り込み。

どちらも --shots で画面の写真を残す(A は明るいテーマと狭い画面、B は異常終了時の暗いテーマ)。
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
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402


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


def run_mounted_phase(browser, tmp, shots, check, events):
    """(A) 本番と同じ形: studio・transcribe・cut2resolve をすべて入口に取り込む。"""
    ports = dict(zip(L.TOOL_IDS, free_ports(3)))
    sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=ports, mounts=tuple(M.MOUNTS))
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/" % port
    errors = []
    try:
        sup.start_all()
        sup.start_monitor()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base)

        # 1. 3つのカードが作業の順に並び、動作中になる(3つとも入口に取り込み)
        check(wait_js(pg, "document.querySelectorAll('.pt-tool').length === 3", 10000), "[A] カードが3枚")
        order = pg.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => e.getAttribute('data-tool'))")
        check(order == ["studio", "transcribe", "cut2resolve"], "[A] 作業の順(スタジオ→文字起こし→cut2resolve): %s" % order)
        for tid in L.TOOL_IDS:
            check(wait_card(pg, tid, "running"), "[A] %s が動作中" % tid)
        check(pg.text_content("#ver") == "入口 v" + L.VERSION, "[A] ヘッダーの版: %s" % pg.text_content("#ver"))
        check(pg.text_content("#conn") == "接続中", "[A] 接続中の表示")

        for tid, verfrag in (("studio", "v0.3.0"), ("cut2resolve", None), ("transcribe", "v0.12.0")):
            meta = pg.text_content(".pt-tool[data-tool=%s] .pt-meta" % tid)
            good = ("ポート %d" % port) in meta and "入口に取り込み" in meta and (verfrag is None or verfrag in meta)
            check(good, "[A] %s は入口に取り込み(同じポート): %s" % (tid, meta))
            check(pg.is_disabled(".pt-tool[data-tool=%s] .pt-toggle" % tid) and pg.is_disabled(".pt-tool[data-tool=%s] .pt-restart" % tid),
                  "[A] 取り込んだ%sは単独で止めない(停止・再起動は押せない)" % tid)

        if shots:
            os.makedirs(shots, exist_ok=True)
            pg.evaluate("UIKit.theme.set('light')")
            time.sleep(0.4)   # 色の切り替えのアニメーションが終わるまで
            pg.screenshot(path=os.path.join(shots, "portal-light.png"), full_page=True)

        # 2. 開く: 新しいタブでスタジオの画面が開く(入口のポートからのリンクをツールが 403 にしない)
        href = pg.get_attribute(".pt-tool[data-tool=studio] .pt-open", "href")
        check(href == "http://127.0.0.1:%d/studio/" % port, "[A] 開くのリンクは同じアドレスの /studio/: %s" % href)
        with ctx.expect_page() as info:
            pg.click(".pt-tool[data-tool=studio] .pt-open")
        tab = info.value
        tab.wait_for_load_state()
        check("切り抜きスタジオ" in (tab.title() + tab.content()), "[A] スタジオの画面が開いた")
        check(wait_js(tab, "!!(window.Studio && Studio.state)", 20000), "[A] スタジオの画面が /studio/ の下で API を読めた(CSP・相対パス)")
        check(tab.evaluate("Studio.base") == "/studio" and bool(tab.evaluate("Studio.token")), "[A] スタジオは場所と合言葉を知っている")
        tab.click("#toolMenu summary")
        links = tab.eval_on_selector_all("#toolNav a", "els => els.map(a => a.getAttribute('href'))")
        check(any(h.endswith(":%d/transcribe/" % port) for h in links) and "/studio/" in links and any(h.endswith(":%d/cut2resolve/" % port) for h in links),
              "[A] スタジオの「他のツール」: 3つとも同じポートに取り込み済み: %s" % links)
        u = tab.evaluate("UIKit.tools.url('studio', Studio.ports, '/?url=x')")
        check(u == "http://localhost:%d/studio/?url=x" % port, "[A] 他のツールから取り込んだスタジオへのリンク(ui-kit の paths): %s" % u)
        check(tab.evaluate("window.opener") is None, "[A] 開いたタブから入口を操作できない(noopener)")
        tab.close()

        # 2b. cut2resolve も同じアドレスの /cut2resolve/ で開ける
        href = pg.get_attribute(".pt-tool[data-tool=cut2resolve] .pt-open", "href")
        check(href == "http://127.0.0.1:%d/cut2resolve/" % port, "[A] cut2resolve の開くのリンク: %s" % href)
        with ctx.expect_page() as info:
            pg.click(".pt-tool[data-tool=cut2resolve] .pt-open")
        tab = info.value
        tab.wait_for_load_state()
        check(wait_js(tab, "document.querySelectorAll('#toolNav a').length === 3 || document.querySelectorAll('[data-ui-toolnav] a').length === 3", 20000),
              "[A] cut2resolve の画面が /cut2resolve/ の下で API を読めた")
        links = tab.eval_on_selector_all("[data-ui-toolnav] a", "els => els.map(a => a.getAttribute('href'))")
        check(any(h.endswith(":%d/studio/" % port) for h in links) and any(h.endswith(":%d/transcribe/" % port) for h in links),
              "[A] cut2resolve の「他のツール」からスタジオ・文字起こしとも同じポートへ: %s" % links)
        tab.close()

        # 2c. 文字起こしも同じアドレスの /transcribe/ で開ける(段階3-3。認識自体は別プロセスの tx_worker.py)
        href = pg.get_attribute(".pt-tool[data-tool=transcribe] .pt-open", "href")
        check(href == "http://127.0.0.1:%d/transcribe/" % port, "[A] 文字起こしの開くのリンク: %s" % href)
        with ctx.expect_page() as info:
            pg.click(".pt-tool[data-tool=transcribe] .pt-open")
        tab = info.value
        tab.wait_for_load_state()
        check(wait_js(tab, "document.querySelector('#ver') && document.querySelector('#ver').textContent === 'v0.12.0'", 20000),
              "[A] 文字起こしの画面が /transcribe/ の下で読み込めた(app.js の APP_VERSION): %s"
              % tab.evaluate("document.querySelector('#ver') && document.querySelector('#ver').textContent"))
        check(bool(tab.evaluate("(document.querySelector('meta[name=\"ytt-token\"]') || {}).content")), "[A] 文字起こしの画面も合言葉(ytt-token)を受け取っている")
        tab.click("#toolMenu summary")
        check(wait_js(tab, "document.querySelectorAll('#toolNav a').length >= 2", 10000), "[A] 文字起こしの「他のツール」メニューが開いた")
        links = tab.eval_on_selector_all("#toolNav a", "els => els.map(a => a.getAttribute('href'))")
        check(any(h.endswith(":%d/studio/" % port) for h in links) and any(h.endswith(":%d/cut2resolve/" % port) for h in links),
              "[A] 文字起こしの「他のツール」: スタジオ・cut2resolve とも同じポートに取り込み済み: %s" % links)
        check(tab.evaluate("window.opener") is None, "[A] 文字起こしのタブからも入口を操作できない(noopener)")
        tab.close()

        # 7. テーマ(ui-kit)
        before = pg.get_attribute("html", "data-theme")
        pg.click("[data-theme-toggle]")
        after = pg.get_attribute("html", "data-theme")
        check(before != after and after in ("light", "dark"), "[A] テーマの切り替え %s → %s" % (before, after))

        # 8. 狭い画面(縦に並ぶ・横にはみ出さない)
        mob = ctx.new_page()
        mob.set_viewport_size({"width": 375, "height": 800})
        mob.goto(base)
        check(wait_js(mob, "document.querySelectorAll('.pt-tool[data-state=running]').length === 3"), "[A] 狭い画面でも表示")
        check(mob.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "[A] 狭い画面で横にはみ出さない")
        xs = mob.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => Math.round(e.getBoundingClientRect().left))")
        check(len(set(xs)) == 1, "[A] 狭い画面では縦に並ぶ: %s" % xs)
        if shots:
            mob.screenshot(path=os.path.join(shots, "portal-mobile.png"), full_page=True)

        # 9. すべて終了(2回押し)。3つとも取り込みなので、この形には子プロセスは無い
        pg.click("#btnQuit")
        check(pg.text_content("#btnQuit") == "もう一度押すと終了します", "[A] 1回目は確認だけ")
        pg.click("#btnQuit")
        check(wait_js(pg, "!document.getElementById('done').hidden", 5000), "[A] 終了中の表示")
        th.join(30)
        check(not th.is_alive(), "[A] 入口のサーバーが止まった")
        srv.server_close()   # launch.main() と同じく、待ち受けを閉じる
        check(wait_js(pg, "document.getElementById('doneTitle').textContent === 'すべて終了しました'", 20000), "[A] 終了の表示")
        sup.unmount_all()   # launch.main() の終了処理と同じ(request_shutdown でも呼ばれる)
        check(not any(os.path.exists(os.path.join(sup.rdir, t + ".json")) for t in L.TOOL_IDS), "[A] .runtime が片付いた(3つとも取り込みでも)")

        # 10. 入口が止まったら、開いたままの別のタブに「接続できません」を出す
        check(wait_js(mob, "!document.getElementById('errbar').hidden", 15000), "[A] 切断の表示")
        check(mob.is_disabled(".pt-tool[data-tool=studio] .pt-toggle"), "[A] 切断中は操作できない")

        real_errors = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
        check(not real_errors, "[A] 画面のエラーなし(CSP 違反を含む): %s" % real_errors[:3])
        ctx.close()
    finally:
        if not srv.closing.is_set():
            srv.shutdown()
        sup.close()
        sup.stop_all()   # 念のため(3つとも取り込みならここで止める子プロセスは無い)
        sup.unmount_all()
        srv.server_close()


def run_child_process_phase(browser, tmp, shots, check, events):
    """(B) 文字起こしが子プロセスの形(--no-mount 相当・取り込めなかったときの落ち先)。
    停止・起動、再起動、異常終了の表示と起動し直し、ログの表示(XSS 対策)を、子プロセスとして確かめる。"""
    ports = dict(zip(L.TOOL_IDS, free_ports(3)))
    sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=ports, mounts=("studio", "cut2resolve"))
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/" % port
    errors = []
    try:
        sup.start_all()
        sup.start_monitor()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base)

        check(wait_js(pg, "document.querySelectorAll('.pt-tool').length === 3", 10000), "[B] カードが3枚")
        for tid in L.TOOL_IDS:
            check(wait_card(pg, tid, "running"), "[B] %s が動作中" % tid)

        for tid in ("studio", "cut2resolve"):
            meta = pg.text_content(".pt-tool[data-tool=%s] .pt-meta" % tid)
            check(("ポート %d" % port) in meta and "入口に取り込み" in meta, "[B] %s は入口に取り込み: %s" % (tid, meta))
            check(pg.is_disabled(".pt-tool[data-tool=%s] .pt-toggle" % tid) and pg.is_disabled(".pt-tool[data-tool=%s] .pt-restart" % tid),
                  "[B] 取り込んだ%sは単独で止めない" % tid)
        meta = pg.text_content(".pt-tool[data-tool=transcribe] .pt-meta")
        check(("ポート %d" % ports["transcribe"]) in meta and "v0.12.0" in meta and "入口に取り込み" not in meta,
              "[B] 文字起こしは別のプログラム(子プロセス): %s" % meta)
        check(not pg.is_disabled(".pt-tool[data-tool=transcribe] .pt-toggle") and not pg.is_disabled(".pt-tool[data-tool=transcribe] .pt-restart"),
              "[B] 子プロセスの文字起こしは停止・再起動が押せる")

        # 3. ログ: 開くと末尾が出る。題名などに HTML が入っていても実行されない
        tx = sup.by_id["transcribe"]
        with open(tx.log_path, "a", encoding="utf-8") as f:
            f.write('題名 <img src=x onerror="window.__xss=1"> テスト\n')
        pg.click(".pt-tool[data-tool=transcribe] .pt-logbox summary")
        check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-log').textContent.includes('onerror')"), "[B] ログが表示される")
        check(pg.evaluate("window.__xss") is None and pg.query_selector(".pt-log img") is None, "[B] ログの HTML は文字として表示(XSS なし)")
        check("transcribe.log" in pg.text_content(".pt-tool[data-tool=transcribe] .pt-logpath"), "[B] ログの場所の表示")

        # 4. 停止 → 起動(この形で子プロセスなのは文字起こしだけ)
        pg.click(".pt-tool[data-tool=transcribe] .pt-toggle")
        check(wait_card(pg, "transcribe", "stopped"), "[B] 文字起こしを停止")
        check(pg.get_attribute(".pt-tool[data-tool=transcribe] .pt-open", "aria-disabled") == "true", "[B] 停止中は「開く」が押せない")
        check(pg.text_content(".pt-tool[data-tool=transcribe] .pt-toggle") == "起動", "[B] ボタンが「起動」になる")
        check(pg.is_disabled(".pt-tool[data-tool=transcribe] .pt-restart"), "[B] 停止中は再起動が押せない")
        pg.click(".pt-tool[data-tool=transcribe] .pt-toggle")
        check(wait_card(pg, "transcribe", "running"), "[B] 文字起こしを起動")

        # 5. 再起動
        old_pid = sup.by_id["transcribe"].proc.pid
        pg.click(".pt-tool[data-tool=transcribe] .pt-restart")
        check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-pill').textContent.includes('再起動')", 5000)
              or card_state(pg, "transcribe") in ("starting", "running"), "[B] 再起動中の表示")
        check(wait_for(lambda: sup.by_id["transcribe"].snapshot()["starts"] == 3, 30), "[B] 再起動した(停止→起動のあとなので起動の回数が3)")
        check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-pill').textContent === '動作中'"
                          " && document.querySelector('.pt-tool[data-tool=transcribe]').getAttribute('data-state') === 'running'"),
              "[B] 文字起こしが再起動後に動作中")
        proc = sup.by_id["transcribe"].proc
        check(proc is not None and proc.pid != old_pid, "[B] 別のプロセスになった")

        # 6. 異常終了の表示(子を外から強制終了)
        os.kill(sup.by_id["transcribe"].proc.pid, signal.SIGKILL)
        check(wait_card(pg, "transcribe", "crashed"), "[B] 異常終了の表示")
        msg = pg.text_content(".pt-tool[data-tool=transcribe] .pt-msg")
        check("異常終了" in msg and not pg.is_hidden(".pt-tool[data-tool=transcribe] .pt-msg"), "[B] 異常終了のメッセージ: %s" % msg)
        check(pg.text_content(".pt-tool[data-tool=transcribe] .pt-toggle") == "起動", "[B] 異常終了のあと「起動」が押せる")
        if shots:
            os.makedirs(shots, exist_ok=True)
            pg.evaluate("UIKit.theme.set('dark')")
            time.sleep(0.4)
            pg.screenshot(path=os.path.join(shots, "portal-dark-crashed.png"), full_page=True)
        pg.click(".pt-tool[data-tool=transcribe] .pt-toggle")
        check(wait_card(pg, "transcribe", "running"), "[B] 起動し直せる")

        # 9. すべて終了(2回押し)。今度は文字起こしだけが止めるべき子プロセス
        procs = [t.proc for t in sup.tools if t.proc]
        pg.click("#btnQuit")
        check(pg.text_content("#btnQuit") == "もう一度押すと終了します", "[B] 1回目は確認だけ")
        check(sup.by_id["transcribe"].proc is not None, "[B] 1回目ではまだ止まらない")
        pg.click("#btnQuit")
        check(wait_js(pg, "!document.getElementById('done').hidden", 5000), "[B] 終了中の表示")
        th.join(30)
        check(not th.is_alive(), "[B] 入口のサーバーが止まった")
        srv.server_close()
        check(wait_js(pg, "document.getElementById('doneTitle').textContent === 'すべて終了しました'", 20000), "[B] 終了の表示")
        check(all(pr.poll() is not None for pr in procs), "[B] 子プロセスの文字起こしが止まった")
        sup.unmount_all()
        check(not any(os.path.exists(os.path.join(sup.rdir, t + ".json")) for t in L.TOOL_IDS), "[B] .runtime が片付いた")

        real_errors = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
        check(not real_errors, "[B] 画面のエラーなし(CSP 違反を含む): %s" % real_errors[:3])
        ctx.close()
    finally:
        if not srv.closing.is_set():
            srv.shutdown()
        sup.close()
        sup.stop_all()   # 文字起こしが子プロセスのまま残っていれば、ここで止める
        sup.unmount_all()
        srv.server_close()


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    ok = True
    events = []

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-portal-e2e-")
    env = {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake"}
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    try:
        for s in L.TOOLS:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))   # 共通部品(本物と同じ並び)
        env["STUDIO_HOME"] = os.path.join(tmp, "studio-home")
        os.environ["STUDIO_HOME"] = env["STUDIO_HOME"]

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                run_mounted_phase(browser, tmp, shots, check, events)          # (A) 本番と同じ形(3つとも取り込み)
                run_child_process_phase(browser, tmp, shots, check, events)    # (B) 文字起こしが子プロセスの形
            finally:
                browser.close()
    finally:
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(events[-30:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
