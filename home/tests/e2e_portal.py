#!/usr/bin/env python3
"""ホーム(home/portal.html。段階5: 入口 + 案件を1つにした)の通し確認(Playwright。本物の3ツールを疑似モードで
一時フォルダに写し、空きポートだけを使う)。

    python home/tests/e2e_portal.py [--shots <フォルダ>]

いまは「文字起こし」も入口に取り込める(段階3-3。home/mount.py の MOUNTS)ので、2つの形をそれぞれ確かめる:

  (A) 本番と同じ形(python home/launch.py と同じ mounts=tuple(mount.MOUNTS)): 3つとも入口に取り込み。
      2枚のカードが「ホームに取り込み」で動作中になる → 「次にやること」・案件(配信ごと)の一覧・単体の文字起こし →
      開く(3つとも同じポートの /studio/・/transcribe/・/cut2resolve/ で新しいタブが開く。文字起こしの画面も #ver・
      合言葉・他のツールへのリンクを確かめる)→ /cases.html は #cases へ転送 → テーマ → 狭い画面 →
      すべて終了(2回押し)→ 切断の表示、を確かめる。
  (B) 文字起こしが子プロセスの形(--no-mount 相当・取り込めなかったときの落ち先。mounts=("studio", "cut2resolve")):
      文字起こしだけ黒い画面(別プロセス)で動く形で、子プロセスの管理(停止・起動・再起動・異常終了の表示・
      異常終了後の起動し直し・ログの表示と XSS 対策)を確かめる(「詳しく」の中)。studio・cut2resolve は (A) と同じく取り込み。

どちらも --shots で画面の写真を残す(A は明るいテーマと狭い画面、B は異常終了時の暗いテーマ)。
"""
import http.client
import json
import os
import re
import urllib.parse
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import signal
import sys
import tempfile
import threading
import time
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402
from ytt_core import layout  # noqa: E402


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


def open_advanced(pg):
    """「詳しく」を開く(サーバーの管理の操作はクリックできる必要があるため)。既定で閉じていることを確かめてから開く"""
    ok = wait_js(pg, "document.getElementById('advancedBox') && document.getElementById('advancedBox').open === false", 10000)
    pg.evaluate("document.getElementById('advancedBox').open = true")
    return ok


def appnav_links(pg):
    """studio・編集の画面のツール切り替えのリンク一覧 -> ("appnav"|"toolmenu", {id: href})。新(ui-appnav。他の AI が画面を
    直している途中に対応)を先に見て、無ければ旧(#toolMenu の details・#toolNav)を開いて読む。
    新の方は、まだ画面側で UIKit.tools.setPaths() を呼ぶ前に描かれて href が確定していないことがある(ui-kit 側の
    既知の制約。appnav に再描画の仕組みが無いため)。href の中身までは新のときは厳しく求めない(下の呼び出し側で分岐)"""
    if pg.query_selector('[data-ui-appnav-item]'):
        items = pg.eval_on_selector_all("[data-ui-appnav-item]", "els => els.map(e => [e.getAttribute('data-ui-appnav-item'), e.getAttribute('href')])")
        return "appnav", dict(items)
    if pg.query_selector("#toolMenu summary"):
        pg.click("#toolMenu summary")
        wait_js(pg, "document.querySelectorAll('#toolNav a').length >= 1", 10000)
        hrefs = pg.eval_on_selector_all("#toolNav a", "els => els.map(a => a.getAttribute('href'))")
        out = {}
        for h in hrefs:
            if "/transcribe/" in h:
                out["transcribe"] = h
            elif "/studio/" in h:
                out["studio"] = h
        return "toolmenu", out
    return "none", {}


def check_tool_nav(check, pg, other_id, port, label):
    """スタジオ・編集の画面から、もう一方のツールへのリンクが出ていて cut2resolve(部品)が出ないことを確かめる。
    新(ui-appnav)は href の中身まで厳しく求めない(まだ移行の途中の画面があるため。report で orchestrator に伝える)"""
    kind, links = appnav_links(pg)
    if kind == "toolmenu":
        check(other_id in links and links[other_id].endswith(":%d/%s/" % (port, other_id)) and "cut2resolve" not in links,
              "[A] %s: 編集/スタジオは同じポートに取り込み済み・cut2resolve(部品)は出さない: %s" % (label, links))
    else:
        check(other_id in links and "cut2resolve" not in links,
              "[A] %s: ツール切り替えに項目が出て、cut2resolve(部品)は出さない(ui-appnav。href の中身は移行の途中のため緩め): %s" % (label, links))


CASE_TITLE = "案件の通し確認<b>配信</b>"   # < を含めて、textContent で入れていること(画面を壊さない)も確かめる


def seed_cases(tmp, studio_home):
    """案件の一覧・次にやること用: 書き出し済みのマーク1つを持つ配信と、その切り抜きの文字起こし(2行のうち1行を校正済み・パックはまだ)を置く"""
    clip = os.path.join(tmp, "exports", "01_案件.mp4")
    os.makedirs(os.path.dirname(clip), exist_ok=True)
    with open(clip, "wb") as f:
        f.write(b"x")
    os.makedirs(studio_home, exist_ok=True)
    mark = {"id": "m1", "start": 10.0, "end": 40.0, "label": "見どころ", "status": "exported", "file": "01_案件.mp4", "path": clip}
    with open(os.path.join(studio_home, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "clip-studio/v1", "groups": {}, "videos": {"e2eCase0001": {
            "id": "e2eCase0001", "kind": "youtube", "title": CASE_TITLE, "channel": "ch", "duration": 100, "marks": [mark]}}}, f, ensure_ascii=False)
    tx = os.path.join(tmp, layout.TOOL_DIRS["transcribe"], "transcripts")
    os.makedirs(tx, exist_ok=True)
    # 文字起こしの文書 id は editor/serve.py の TID_RE(12文字の16進)を満たす必要がある(ytt_core.txindex は緩いが、
    # /transcribe/api/transcripts はこちらの規則で一覧する)
    with open(os.path.join(tx, "deadbeef0001.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "deadbeef0001", "title": "案件の字幕", "sourcePath": clip, "updatedAt": 1,
                   "segments": [{"id": "s1", "start": 0.5, "end": 2.0, "text": "a", "proofed": True}, {"id": "s2", "start": 2.5, "end": 4.0, "text": "b"}]}, f, ensure_ascii=False)


def seed_unlinked(tmp):
    """どの配信にも紐づかない文字起こし(「単体の文字起こし」・次にやることの校正待ちにも出る)"""
    tx = os.path.join(tmp, layout.TOOL_DIRS["transcribe"], "transcripts")
    os.makedirs(tx, exist_ok=True)
    solo = os.path.join(tmp, "solo.mp4")
    with open(os.path.join(tx, "deadbeef0002.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "deadbeef0002", "title": "単体の字幕", "sourcePath": solo, "updatedAt": 2,
                   "segments": [{"id": "s1", "start": 0.0, "end": 1.5, "text": "c"}]}, f, ensure_ascii=False)


def seed_more_cases(studio_json, n=34, base_ts=None):
    """案件の一覧(1件1行)の道具(検索・絞り込み・並び替え・まとめ方・「もっと見る」)を確かめるため、配信を n 本足す。
    実物の動画ファイルは要らない(マークを「採用」までにしておけば、案件には出るが書き出しは要らない)"""
    with open(studio_json, encoding="utf-8") as f:
        doc = json.load(f)
    base_ts = base_ts or int(time.time() * 1000)
    channels = ["chAAA", "chBBB", "chCCC"]   # seed_cases() の配信者 "ch" より長い名前(配信者順の並び替えで区別するため)
    for i in range(n):
        vid = "e2eList%04d" % i
        marks = [{"id": "m1", "start": 1.0, "end": 5.0, "label": "見どころ", "status": "adopted"}] if i % 5 == 0 else []
        doc["videos"]["e2eList%04d" % i] = {"id": vid, "kind": "youtube", "title": "一覧テスト %02d" % i,
                                             "channel": channels[i % len(channels)], "duration": 100, "marks": marks,
                                             "createdAt": base_ts - i * 3600000, "updatedAt": base_ts - i * 3600000}
    with open(studio_json, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def tool_version(rel, pattern):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return re.search(pattern, f.read(), re.M).group(1)


TX_VER = "v" + tool_version(layout.TOOL_DIRS["transcribe"] + "/app.js", r"const APP_VERSION = '([^']+)'")
STUDIO_VER = "v" + tool_version(layout.TOOL_DIRS["studio"] + "/core.js", r"const APP_VERSION = '([^']+)'")
SHOWN = ("studio", "transcribe")   # ホームのカード(cut2resolve は「編集」の部品。動いている間はカードを出さない)


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

        # 1. カードは2枚(① 切り抜きスタジオ → ② 編集)。cut2resolve は「編集」の部品として取り込まれて動くが、カードは出さない
        for tid in SHOWN:
            check(wait_card(pg, tid, "running"), "[A] %s が動作中" % tid)
        order = pg.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => e.getAttribute('data-tool'))")
        check(order == ["studio", "transcribe"], "[A] カードは作業の順に2枚(スタジオ → 編集): %s" % order)
        check(pg.text_content(".pt-tool[data-tool=transcribe] .pt-name") == "編集", "[A] 文字起こしのカードは「編集」")
        c2r = next(t for t in pg.evaluate("fetch('/api/status', {cache: 'no-store'}).then(r => r.json())")["tools"] if t["id"] == "cut2resolve")
        check(c2r["state"] == "running" and c2r["mounted"] and c2r["hidden"], "[A] cut2resolve はホームに取り込まれて動いている(カードは出さない): %s" % {k: c2r[k] for k in ("state", "mounted", "hidden")})
        check(pg.text_content("#ver") == "ホーム v" + L.VERSION, "[A] ヘッダーの版: %s" % pg.text_content("#ver"))
        check(pg.text_content("#conn") == "接続中", "[A] 接続中の表示")
        check(wait_js(pg, "document.querySelector('[data-ui-appnav-item=\"studio\"]')?.getAttribute('href') === '/studio/'"
                          " && document.querySelector('[data-ui-appnav-item=\"transcribe\"]')?.getAttribute('href') === '/transcribe/'", 10000),
              "[A] ホームの ui-appnav の「スタジオ」「編集」は、取り込みが分かってから正しい場所に直る: %s"
              % pg.eval_on_selector_all("[data-ui-appnav-item]", "els => els.map(e => [e.getAttribute('data-ui-appnav-item'), e.getAttribute('href')])"))

        # 1b. 「詳しく」は既定で閉じている。テストのため開く(サーバーの管理の操作をクリックできるように)
        check(open_advanced(pg), "[A] 「詳しく」は既定で閉じている")

        for tid, verfrag in (("studio", STUDIO_VER), ("transcribe", TX_VER)):
            meta = pg.text_content(".pt-tool[data-tool=%s] .pt-meta" % tid)
            good = ("ポート %d" % port) in meta and "ホームに取り込み" in meta and (verfrag is None or verfrag in meta)
            check(good, "[A] %s はホームに取り込み(同じポート): %s" % (tid, meta))
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
        check_tool_nav(check, tab, "transcribe", port, "スタジオのツール切り替え")
        u = tab.evaluate("UIKit.tools.url('studio', Studio.ports, '/?url=x')")
        check(u == "http://localhost:%d/studio/?url=x" % port, "[A] 他のツールから取り込んだスタジオへのリンク(ui-kit の paths): %s" % u)
        check(tab.evaluate("window.opener") is None, "[A] 開いたタブからホームを操作できない(noopener)")
        tab.close()

        # 2b. cut2resolve の画面(/cut2resolve/)は「編集」に統合して消したので、「編集」へ転送する(?video= → ?media=)
        tab = ctx.new_page()
        tab.goto(base + "cut2resolve/?video=" + urllib.parse.quote("C:\\x\\無い動画.mp4"))
        check(wait_js(tab, "location.pathname === '/transcribe/' && document.querySelector('#srcPath') && document.querySelector('#srcPath').value.endsWith('無い動画.mp4')", 20000),
              "[A] /cut2resolve/ を開くと「編集」(/transcribe/)へ転送し、?video= の動画を ?media= で渡す")
        tab.close()
        # 2c. 編集(文字起こし)も同じアドレスの /transcribe/ で開ける(段階3-3。認識自体は別プロセスの tx_worker.py)
        href = pg.get_attribute(".pt-tool[data-tool=transcribe] .pt-open", "href")
        check(href == "http://127.0.0.1:%d/transcribe/" % port, "[A] 文字起こしの開くのリンク: %s" % href)
        with ctx.expect_page() as info:
            pg.click(".pt-tool[data-tool=transcribe] .pt-open")
        tab = info.value
        tab.wait_for_load_state()
        check(wait_js(tab, "document.querySelector('#ver') && document.querySelector('#ver').textContent === '%s'" % TX_VER, 20000),
              "[A] 文字起こしの画面が /transcribe/ の下で読み込めた(app.js の APP_VERSION): %s"
              % tab.evaluate("document.querySelector('#ver') && document.querySelector('#ver').textContent"))
        check(bool(tab.evaluate("(document.querySelector('meta[name=\"ytt-token\"]') || {}).content")), "[A] 文字起こしの画面も合言葉(ytt-token)を受け取っている")
        check_tool_nav(check, tab, "studio", port, "編集のツール切り替え")
        check(tab.evaluate("window.opener") is None, "[A] 文字起こしのタブからもホームを操作できない(noopener)")
        tab.close()

        # 2d. 案件(配信ごと)の画面はホーム(/)にまとめた(段階5)。スタジオ・文字起こしのデータから紐づけを組み立て、状態を付けて保存できる
        check(wait_js(pg, "document.querySelectorAll('.pt-case').length === 1", 15000), "[A] 案件の一覧に配信が1本出た")
        check(pg.text_content(".pt-case-title") == CASE_TITLE, "[A] 案件のタイトル: %s" % pg.text_content(".pt-case-title"))
        check(pg.evaluate("document.querySelector('.pt-case').open") is False, "[A] 行は既定で閉じている(1件1行。開くまで中身を描かない分だけ軽い)")
        pills = pg.eval_on_selector_all(".pt-clip .pill", "els => els.map(e => e.textContent)")
        check("文字起こし 校正 1/2行" in pills and "パック まだ" in pills, "[A] 閉じていても中身は組み立ててある(文字起こしの進み具合とパックの有無): %s" % pills)
        pg.click(".pt-case .pt-case-row")
        check(wait_js(pg, "document.querySelector('.pt-case').open === true", 5000), "[A] 行を開くと切り抜き・まとめて実行・メモが出る")
        acts = pg.eval_on_selector_all(".pt-clip a", "els => els.map(a => [a.textContent, a.getAttribute('href')])")
        check(any(t == "編集で開く" and h.startswith("/transcribe/?doc=") and "&media=" in h and h.endswith("#tx") for t, h in acts),
              "[A] 切り抜きの操作は「編集で開く」(文書 ID で校正のタブへ。B-1: 同じ動画の別の文書が開かないように): %s" % acts)
        case_doc = [h for t, h in acts if t == "編集で開く"][0].split("doc=")[1].split("&")[0]
        # B-8(段1): 案件の行から、その配信をスタジオの ③ 確認で開く(新しいタブ・noopener)
        sh = pg.eval_on_selector_all(".pt-case-studio a", "els => els.map(a => [a.textContent, a.getAttribute('href'), a.target, a.rel])")
        check(sh == [["スタジオで開く", "/studio/?video=e2eCase0001", "_blank", "noopener"]],
              "[A] 案件の行に「スタジオで開く」(?video= に案件の id・新しいタブ): %s" % sh)
        with ctx.expect_page() as info:
            pg.click(".pt-case-studio a")
        tab = info.value
        tab.wait_for_load_state()
        check(wait_js(tab, "!!(window.Studio && Studio.ready) && Studio.params.video === 'e2eCase0001' && Studio.step === 'review'", 20000),
              "[A] 「スタジオで開く」でスタジオがその配信を ③ 確認で開いた: %s"
              % tab.evaluate("window.Studio && [Studio.params, Studio.step]"))
        check(tab.evaluate("window.opener") is None, "[A] スタジオのタブからホームを操作できない(noopener)")
        tab.close()
        pg.select_option(".pt-case-status", "posted")
        check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('投稿済み') >= 0)", 10000), "[A] 状態を保存した(合言葉つきの POST)")
        pg.reload()
        check(wait_js(pg, "document.querySelector('.pt-case-status') && document.querySelector('.pt-case-status').value === 'posted'", 15000),
              "[A] 読み込み直しても状態が残る(案件ファイル)")
        # B-4: 投稿済み・見送りの案件は「次にやること」に出さない
        time.sleep(1.0)
        todo_hrefs = pg.eval_on_selector_all(".pt-todo-item .pt-todo-link", "els => els.map(a => a.getAttribute('href'))")
        check(not any(("doc=" + case_doc) in h for h in todo_hrefs), "[A] 投稿済みの案件の文書は「次にやること」に出ない: %s" % todo_hrefs)
        if not pg.evaluate("document.querySelector('.pt-case').open"):
            pg.click(".pt-case .pt-case-row")
        pg.select_option(".pt-case-status", "")
        check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('未設定') >= 0)", 10000), "[A] 状態を「未設定」に戻した")
        if pg.evaluate("document.querySelector('.pt-case').open"):
            pg.click(".pt-case .pt-case-row")   # 下の確認は閉じた行を開くところから始まる
        # reload で advancedBox が既定に戻るので、また開く
        pg.evaluate("document.getElementById('advancedBox').open = true")

        # 2d-2. 未保存のメモ・フォーカスは、alt-tab で離れて戻ったとき(UIKit.life の blur→focus → refreshCases)の
        # 再描画でも消えない(E2 finding 1)。blur→focus の起こし方は home/tests/e2e_window.py の「7-2 離れた・戻った」と同じ
        pg.click(".pt-case .pt-case-row")
        check(wait_js(pg, "document.querySelector('.pt-case').open === true", 5000), "[A] 下書きを試すため行を開く")
        pg.evaluate("document.querySelector('.pt-case .pt-case-memo').open = true")   # メモの <details> も開く(空だと既定で閉じている)
        draft = "書きかけの下書き"
        pg.fill(".pt-case textarea", draft)   # 「メモを保存」は押さない(保存前の下書きのまま)
        pg.evaluate("document.querySelector('.pt-case textarea').focus()")
        pg.evaluate("() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }")
        time.sleep(0.4)   # UIKit.life の blurTimer(150ms)より長く待つ
        pg.evaluate("() => { document.hasFocus = () => true; window.dispatchEvent(new Event('focus')); }")
        check(wait_js(pg, "document.querySelector('.pt-case') && document.querySelector('.pt-case').open === true", 10000),
              "[A] 離れて戻った再描画のあとも行は開いたまま")
        check(wait_js(pg, "document.querySelector('.pt-case textarea') && document.querySelector('.pt-case textarea').value === %s" % json.dumps(draft), 10000),
              "[A] 保存前のメモが、戻ったときの再描画(refreshCases)でも消えない: %s"
              % pg.evaluate("document.querySelector('.pt-case textarea') && document.querySelector('.pt-case textarea').value"))
        check(pg.evaluate("document.activeElement === document.querySelector('.pt-case textarea')"),
              "[A] フォーカスも(再描画で作り直された)メモ欄に戻る")

        # 2e. 次にやること: 校正待ち・パック待ちが、案件の一覧・「編集」の文書の一覧から組み立たっている
        check(wait_js(pg, "!!document.querySelectorAll('.pt-todo-item').length", 15000), "[A] 「次にやること」に項目が出た")
        todo = pg.eval_on_selector_all(".pt-todo-item .pt-todo-link", "els => els.map(a => [a.querySelector('.pt-todo-pill').textContent, a.getAttribute('href')])")
        check(wait_js(pg, "[...document.querySelectorAll('.pt-todo-item .pt-todo-link')].some(a => a.getAttribute('href').indexOf('doc=%s') >= 0)" % case_doc, 15000),
              "[A] 状態を戻すと、また「次にやること」に出る")
        todo = pg.eval_on_selector_all(".pt-todo-item .pt-todo-link", "els => els.map(a => [a.querySelector('.pt-todo-pill').textContent, a.getAttribute('href')])")
        check(any(p == '校正待ち' and h.startswith('/transcribe/?doc=' + case_doc) and h.endswith('#tx') for p, h in todo),
              "[A] 次にやることに校正待ち(1/2行のまま)が出て、文書 ID で校正のタブへ直接リンクする: %s" % todo)
        subs = pg.eval_on_selector_all(".pt-todo-item", "els => els.map(e => e.querySelector('.pt-todo-sub').textContent)")
        check(any("の配信" in x or "・" in x for x in subs), "[A] 次にやることに配信者・配信日が添えられる(B-5): %s" % subs)
        # E2 finding 2: 校正がまだ済んでいない(proofed < rows)文書は、パックの有無に関わらず「パック待ち」を重ねて出さない
        # (以前は !it.pack だけで判定していて、校正中の文書にも重複して出ていた)
        check(not any(p in ('パック待ち', '作り直し') for p, h in todo),
              "[A] 校正がまだ済んでいない文書は「パック待ち」を二重に出さない: %s" % todo)

        # 2f. 単体の文字起こし(どの配信にも紐づかない文字起こし)。「編集」の文書の一覧と突き合わせて詳しく見せる
        check(wait_js(pg, "!document.getElementById('unlinkedGroup').hidden", 10000), "[A] 単体の文字起こしのまとまりが出た")
        check(pg.evaluate("document.getElementById('unlinkedGroup').open") is False, "[A] 単体の文字起こしのまとまりは既定で閉じている")
        pg.click("#unlinkedGroup summary")
        check(wait_js(pg, "!!document.querySelector('.pt-doc')", 10000), "[A] 単体の文字起こしの行が出た")
        docTx = pg.text_content(".pt-doc-tx")
        check("校正 0/1行" in docTx and "パック まだ" in docTx, "[A] 単体の文字起こしも校正・パックの進み具合を見せる: %s" % docTx)
        open_href = pg.get_attribute(".pt-doc-open", "href")
        check(bool(open_href) and open_href.startswith("/transcribe/?doc=") and open_href.endswith("#tx"), "[A] 単体の文字起こしも「編集で開く」(文書 ID で): %s" % open_href)
        pg.check(".pt-doc-check")
        check(wait_js(pg, "!document.getElementById('docRunBtn').disabled", 5000), "[A] 選ぶと「まとめて実行」が押せる")
        pg.uncheck(".pt-doc-check")
        check(pg.is_disabled("#docRunBtn"), "[A] 選びを外すとまた押せない")

        # 2g. 一覧の道具(検索・絞り込み・並び替え・まとめ方・件数・「もっと見る」)。配信をたくさんに増やして確かめる
        studio_home = os.environ["STUDIO_HOME"]
        seed_more_cases(os.path.join(studio_home, "data.json"), n=34)
        pg.click("#btnReload")
        check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 30", 15000),
              "[A] 配信が35本でも、最初は30件だけ描く(絞り込んだ分だけ描く): %s"
              % pg.evaluate("document.querySelectorAll('#list .pt-case').length"))
        check("35" in pg.text_content("#count"), "[A] 件数の表示に全体の件数が出る: %s" % pg.text_content("#count"))
        pg.click("#btnMore")
        check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 35", 10000), "[A] 「もっと見る」で残りも描く")

        pg.fill("#fText", "一覧テスト 0")
        check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 10", 10000),
              "[A] 検索(題名・配信者)で絞り込む: %s" % pg.evaluate("document.querySelectorAll('#list .pt-case').length"))
        pg.fill("#fText", "")
        check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 30", 10000), "[A] 検索を消すと絞り込みも戻る(もっと見るは30件から)")

        pg.select_option("#fSort", "channel")
        check(wait_js(pg, "document.querySelector('#list .pt-case .pt-case-sub').textContent.indexOf('ch ') === 0", 5000),
              "[A] 配信者順の並び替え(いちばん短い配信者名 ch が先頭): %s" % pg.text_content("#list .pt-case .pt-case-sub"))

        pg.select_option("#fGroup", "channel")
        check(wait_js(pg, "document.querySelectorAll('#list .ui-group').length === 4", 10000),
              "[A] 配信者ごとにまとめる(配信者4人ぶんの見出し): %s" % pg.evaluate("document.querySelectorAll('#list .ui-group').length"))
        check(pg.evaluate("[...document.querySelectorAll('#list .ui-group')].every(g => !g.open)"),
              "[A] まとまりは既定で閉じている(まとめて実行が動いている配信は無いので)")
        pg.click("#list .ui-group:first-child summary")
        check(wait_js(pg, "document.querySelector('#list .ui-group').open === true", 5000), "[A] まとまりをクリックで開ける")
        pg.reload()
        pg.evaluate("document.getElementById('advancedBox').open = true")
        check(wait_js(pg, "document.querySelector('#fGroup').value === 'channel' && document.querySelector('#fSort').value === 'channel'", 10000),
              "[A] 並び替え・まとめ方はブラウザに覚えている(読み込み直しても)")
        pg.select_option("#fGroup", "")
        pg.select_option("#fSort", "new")
        real = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
        check(not real, "[A] 一覧の道具を操作しても画面のエラーなし: %s" % real[:3])

        # 2h. /cases.html は以前のリンク・ブックマークのために残す(ホームの案件の一覧へ転送)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/cases.html", headers={"Host": "127.0.0.1:%d" % port})
        r = conn.getresponse()
        r.read()
        conn.close()
        check((r.status, r.getheader("Location")) == (302, "/#cases"), "[A] /cases.html はホームの案件の一覧(#cases)へ 302: %s %s" % (r.status, r.getheader("Location")))
        rtab = ctx.new_page()
        rtab.goto(base + "cases.html")
        check(wait_js(rtab, "!!document.querySelector('.pt-case')", 15000) and rtab.url == base + "#cases",
              "[A] ブラウザで開いても、ホームの案件の一覧に移って表示される: %s" % rtab.url)
        rtab.close()

        # 7. テーマ(ui-kit)
        before = pg.get_attribute("html", "data-theme")
        pg.click("[data-theme-toggle]")
        after = pg.get_attribute("html", "data-theme")
        check(before != after and after in ("light", "dark"), "[A] テーマの切り替え %s → %s" % (before, after))

        # 8. 狭い画面(縦に並ぶ・横にはみ出さない)。案件の一覧(いまの主役)で確かめる
        mob = ctx.new_page()
        mob.set_viewport_size({"width": 375, "height": 800})
        mob.goto(base)
        check(wait_js(mob, "document.querySelectorAll('.pt-case').length >= 2"), "[A] 狭い画面でも案件の一覧が出る")
        check(mob.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "[A] 狭い画面で横にはみ出さない")
        xs = mob.evaluate("[...document.querySelectorAll('#list .pt-case')].slice(0, 3).map(e => Math.round(e.getBoundingClientRect().left))")
        check(len(set(xs)) == 1, "[A] 狭い画面では縦に並ぶ: %s" % xs)
        if shots:
            mob.screenshot(path=os.path.join(shots, "portal-mobile.png"), full_page=True)

        # 9. すべて終了(2回押し)。3つとも取り込みなので、この形には子プロセスは無い
        pg.click("#btnQuit")
        check(pg.text_content("#btnQuit").startswith("もう一度押すと終了します"), "[A] 1回目は確認だけ(残り秒数を見せる): %s" % pg.text_content("#btnQuit"))
        pg.click("#btnQuit")
        check(wait_js(pg, "!document.getElementById('done').hidden", 5000), "[A] 終了中の表示")
        th.join(30)
        check(not th.is_alive(), "[A] ホームのサーバーが止まった")
        srv.server_close()   # launch.main() と同じく、待ち受けを閉じる
        check(wait_js(pg, "document.getElementById('doneTitle').textContent === 'すべて終了しました'", 20000), "[A] 終了の表示")
        sup.unmount_all()   # launch.main() の終了処理と同じ(request_shutdown でも呼ばれる)
        check(not any(os.path.exists(os.path.join(sup.rdir, t + ".json")) for t in L.TOOL_IDS), "[A] .runtime が片付いた(3つとも取り込みでも)")

        # 10. ホームが止まったら、開いたままの別のタブに「接続できません」を出す
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
    停止・起動、再起動、異常終了の表示と起動し直し、ログの表示(XSS 対策)を、子プロセスとして確かめる(「詳しく」の中)。"""
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

        for tid in SHOWN:
            check(wait_card(pg, tid, "running"), "[B] %s が動作中" % tid)
        check(pg.evaluate("document.querySelectorAll('.pt-tool').length") == 2, "[B] カードは2枚(cut2resolve は動いている間は出さない)")
        open_advanced(pg)

        for tid in ("studio",):
            meta = pg.text_content(".pt-tool[data-tool=%s] .pt-meta" % tid)
            check(("ポート %d" % port) in meta and "ホームに取り込み" in meta, "[B] %s はホームに取り込み: %s" % (tid, meta))
            check(pg.is_disabled(".pt-tool[data-tool=%s] .pt-toggle" % tid) and pg.is_disabled(".pt-tool[data-tool=%s] .pt-restart" % tid),
                  "[B] 取り込んだ%sは単独で止めない" % tid)
        meta = pg.text_content(".pt-tool[data-tool=transcribe] .pt-meta")
        check(("ポート %d" % ports["transcribe"]) in meta and TX_VER in meta and "ホームに取り込み" not in meta,
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
        os.kill(sup.by_id["transcribe"].proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))   # Windows は SIGTERM = 強制終了(TerminateProcess)
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
        check(pg.text_content("#btnQuit").startswith("もう一度押すと終了します"), "[B] 1回目は確認だけ(残り秒数を見せる): %s" % pg.text_content("#btnQuit"))
        check(sup.by_id["transcribe"].proc is not None, "[B] 1回目ではまだ止まらない")
        pg.click("#btnQuit")
        check(wait_js(pg, "!document.getElementById('done').hidden", 5000), "[B] 終了中の表示")
        th.join(30)
        check(not th.is_alive(), "[B] ホームのサーバーが止まった")
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
        seed_cases(tmp, env["STUDIO_HOME"])
        seed_unlinked(tmp)

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
