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


CASE_TITLE = "案件の通し確認<b>配信</b>"   # < を含めて、textContent で入れていること(画面を壊さない)も確かめる


def seed_cases(tmp, studio_home):
    """案件の画面用: 書き出し済みのマーク1つを持つ配信と、その切り抜きの文字起こし(2行のうち1行を校正済み)を置く"""
    clip = os.path.join(tmp, "exports", "01_案件.mp4")
    os.makedirs(os.path.dirname(clip), exist_ok=True)
    with open(clip, "wb") as f:
        f.write(b"x")
    os.makedirs(studio_home, exist_ok=True)
    mark = {"id": "m1", "start": 10.0, "end": 40.0, "label": "見どころ", "status": "exported", "file": "01_案件.mp4", "path": clip}
    with open(os.path.join(studio_home, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "clip-studio/v1", "groups": {}, "videos": {"e2eCase0001": {
            "id": "e2eCase0001", "kind": "youtube", "title": CASE_TITLE, "channel": "ch", "duration": 100, "marks": [mark]}}}, f, ensure_ascii=False)
    tx = os.path.join(tmp, "transcribe-tool", "transcripts")
    os.makedirs(tx, exist_ok=True)
    with open(os.path.join(tx, "e2ecase00001.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "e2ecase00001", "title": "案件の字幕", "sourcePath": clip, "updatedAt": 1,
                   "segments": [{"id": "s1", "start": 0.5, "end": 2.0, "text": "a", "proofed": True}, {"id": "s2", "start": 2.5, "end": 4.0, "text": "b"}]}, f, ensure_ascii=False)


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


TX_VER = "v" + tool_version("transcribe-tool/app.js", r"const APP_VERSION = '([^']+)'")
STUDIO_VER = "v" + tool_version("clip-studio/core.js", r"const APP_VERSION = '([^']+)'")
SHOWN = ("studio", "transcribe")   # 入口のカード(cut2resolve は「編集」の部品。動いている間はカードを出さない)


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

        # 1. カードは作業の順に2枚(① 切り抜きスタジオ → ② 編集)。cut2resolve は「編集」の部品として取り込まれて動くが、カードは出さない
        for tid in SHOWN:
            check(wait_card(pg, tid, "running"), "[A] %s が動作中" % tid)
        order = pg.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => e.getAttribute('data-tool'))")
        check(order == ["studio", "transcribe"], "[A] カードは作業の順に2枚(スタジオ → 編集): %s" % order)
        check(pg.text_content(".pt-tool[data-tool=transcribe] .pt-name") == "編集" and [pg.text_content(".pt-tool[data-tool=%s] .pt-step" % t) for t in SHOWN] == ["1", "2"],
              "[A] 文字起こしのカードは「編集」(② の段)")
        c2r = next(t for t in pg.evaluate("fetch('/api/status', {cache: 'no-store'}).then(r => r.json())")["tools"] if t["id"] == "cut2resolve")
        check(c2r["state"] == "running" and c2r["mounted"] and c2r["hidden"], "[A] cut2resolve は入口に取り込まれて動いている(カードは出さない): %s" % {k: c2r[k] for k in ("state", "mounted", "hidden")})
        check(pg.text_content("#ver") == "入口 v" + L.VERSION, "[A] ヘッダーの版: %s" % pg.text_content("#ver"))
        check(pg.text_content("#conn") == "接続中", "[A] 接続中の表示")

        for tid, verfrag in (("studio", STUDIO_VER), ("transcribe", TX_VER)):
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
        check(any(h.endswith(":%d/transcribe/" % port) for h in links) and "/studio/" in links and not any("/cut2resolve/" in h for h in links),
              "[A] スタジオの「他のツール」: 編集は同じポートに取り込み済み・cut2resolve(部品)は出さない: %s" % links)
        check("編集" in tab.text_content("#toolNav"), "[A] 「他のツール」のツール名は「編集」")
        u = tab.evaluate("UIKit.tools.url('studio', Studio.ports, '/?url=x')")
        check(u == "http://localhost:%d/studio/?url=x" % port, "[A] 他のツールから取り込んだスタジオへのリンク(ui-kit の paths): %s" % u)
        check(tab.evaluate("window.opener") is None, "[A] 開いたタブから入口を操作できない(noopener)")
        tab.close()

        # 2b. cut2resolve の画面(/cut2resolve/)は「編集」へ転送する(?video= → ?media=)。前の画面は ?classic=1 のときだけ
        tab = ctx.new_page()
        tab.goto(base + "cut2resolve/?video=" + urllib.parse.quote("C:\\x\\無い動画.mp4"))
        check(wait_js(tab, "location.pathname === '/transcribe/' && document.querySelector('#srcPath') && document.querySelector('#srcPath').value.endsWith('無い動画.mp4')", 20000),
              "[A] /cut2resolve/ を開くと「編集」(/transcribe/)へ転送し、?video= の動画を ?media= で渡す")
        tab.close()
        tab = ctx.new_page()
        tab.goto(base + "cut2resolve/?classic=1")
        tab.wait_for_load_state()
        tools_q = "a .ui-brand-mark:not([data-tool=portal])"   # 「他のツール」の3ツール(ui-kit v3 から先頭に「入口」「案件の一覧」も並ぶ)
        check(wait_js(tab, "document.querySelectorAll('#toolNav %s').length === 3 || document.querySelectorAll('[data-ui-toolnav] %s').length === 3" % (tools_q, tools_q), 20000),
              "[A] ?classic=1 なら前の cut2resolve の画面が /cut2resolve/ の下で API を読めた")
        homes = tab.eval_on_selector_all("[data-ui-toolnav] a", "els => els.map(a => a.getAttribute('href'))")
        check(homes[:2] == ["/", "/cases.html"], "[A] 「他のツール」の先頭に入口・案件の一覧へ戻るリンク(ui-kit v3): %s" % homes[:2])
        check(tab.is_visible("[data-ui-home]") and tab.get_attribute("[data-ui-home]", "href") == "/", "[A] ヘッダーに入口へ戻るリンク(入口に取り込まれているとき)")
        links = tab.eval_on_selector_all("[data-ui-toolnav] a", "els => els.map(a => a.getAttribute('href'))")
        check(any(h.endswith(":%d/studio/" % port) for h in links) and any(h.endswith(":%d/transcribe/" % port) for h in links),
              "[A] cut2resolve の「他のツール」からスタジオ・文字起こしとも同じポートへ: %s" % links)
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
        tab.click("#toolMenu summary")
        check(wait_js(tab, "document.querySelectorAll('#toolNav a').length >= 2", 10000), "[A] 文字起こしの「他のツール」メニューが開いた")
        links = tab.eval_on_selector_all("#toolNav a", "els => els.map(a => a.getAttribute('href'))")
        check(any(h.endswith(":%d/studio/" % port) for h in links) and not any("/cut2resolve/" in h for h in links),
              "[A] 編集の「他のツール」: スタジオは同じポートに取り込み済み・cut2resolve は出さない: %s" % links)
        check(tab.evaluate("window.opener") is None, "[A] 文字起こしのタブからも入口を操作できない(noopener)")
        tab.close()

        # 2d. 案件(配信ごと)の画面: スタジオ・文字起こしのデータから紐づけを組み立て、状態を付けて保存できる(段階4)。
        #     一覧は 1件1行(details。閉じている)で、開くと切り抜き・まとめて実行・メモが出る(2026-09-26 画面の見直し)
        check(pg.get_attribute("#casesLink", "href") == "/cases.html", "[A] 入口から案件の画面へのリンク")
        tab = ctx.new_page()
        tab.goto(base + "cases.html")
        tab.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        tab.on("pageerror", lambda e: errors.append(str(e)))
        tab.wait_for_load_state()
        check(wait_js(tab, "document.querySelectorAll('.pt-case').length === 1", 15000), "[A] 案件の画面に配信が1本出た")
        check(tab.text_content(".pt-case-title") == CASE_TITLE, "[A] 案件のタイトル: %s" % tab.text_content(".pt-case-title"))
        check(tab.evaluate("document.querySelector('.pt-case').open") is False, "[A] 行は既定で閉じている(1件1行。開くまで中身を描かない分だけ軽い)")
        pills = tab.eval_on_selector_all(".pt-clip .pill", "els => els.map(e => e.textContent)")
        check("文字起こし 校正 1/2行" in pills and "パック まだ" in pills, "[A] 閉じていても中身は組み立ててある(文字起こしの進み具合とパックの有無): %s" % pills)
        tab.click(".pt-case .pt-case-row")
        check(wait_js(tab, "document.querySelector('.pt-case').open === true", 5000), "[A] 行を開くと切り抜き・まとめて実行・メモが出る")
        acts = tab.eval_on_selector_all(".pt-clip a", "els => els.map(a => [a.textContent, a.getAttribute('href')])")
        check([a[0] for a in acts].count("編集で開く") == 1 and all(t != "cut2resolve で開く" and t != "文字起こしで開く" for t, _ in acts)
              and any(t == "編集で開く" and h.startswith("/transcribe/?media=") for t, h in acts),
              "[A] 切り抜きの操作は「編集で開く」の1つ(文字起こし・cut2resolve で開くはまとめた): %s" % acts)
        tab.select_option(".pt-case-status", "posted")
        check(wait_js(tab, "document.querySelector('#toast').textContent.indexOf('投稿済み') >= 0", 10000), "[A] 状態を保存した(合言葉つきの POST)")
        tab.reload()
        check(wait_js(tab, "document.querySelector('.pt-case-status') && document.querySelector('.pt-case-status').value === 'posted'", 15000),
              "[A] 読み込み直しても状態が残る(案件ファイル)")
        cf = tab.text_content("#casesFile")
        check(cf.endswith(os.path.join("app", "cases.json")) and os.path.isfile(os.path.join(tmp, "app", "cases.json")), "[A] 案件ファイルの場所: %s" % cf)

        # 2e. 一覧の道具(検索・絞り込み・並び替え・まとめ方・件数・「もっと見る」)。配信をたくさんに増やして確かめる
        studio_home = os.environ["STUDIO_HOME"]
        seed_more_cases(os.path.join(studio_home, "data.json"), n=34)
        tab.click("#btnReload")
        check(wait_js(tab, "document.querySelectorAll('#list .pt-case').length === 30", 15000),
              "[A] 配信が35本でも、最初は30件だけ描く(絞り込んだ分だけ描く): %s"
              % tab.evaluate("document.querySelectorAll('#list .pt-case').length"))
        check("35" in tab.text_content("#count"), "[A] 件数の表示に全体の件数が出る: %s" % tab.text_content("#count"))
        tab.click("#btnMore")
        check(wait_js(tab, "document.querySelectorAll('#list .pt-case').length === 35", 10000), "[A] 「もっと見る」で残りも描く")

        tab.fill("#fText", "一覧テスト 0")
        check(wait_js(tab, "document.querySelectorAll('#list .pt-case').length === 10", 10000),
              "[A] 検索(題名・配信者)で絞り込む: %s" % tab.evaluate("document.querySelectorAll('#list .pt-case').length"))
        tab.fill("#fText", "")
        check(wait_js(tab, "document.querySelectorAll('#list .pt-case').length === 30", 10000), "[A] 検索を消すと絞り込みも戻る(もっと見るは30件から)")

        # 並び替えを先に「配信者順」にしてから まとめる(既定の並び替え「新しい順」だと、最初の30件に配信者 "ch" の1件が
        # 入らず、まとまりが3つしか出ないため。配信者順なら "ch" は名前がいちばん短く先頭に来る)
        tab.select_option("#fSort", "channel")
        check(wait_js(tab, "document.querySelector('#list .pt-case .pt-case-sub').textContent.indexOf('ch ') === 0", 5000),
              "[A] 配信者順の並び替え(いちばん短い配信者名 ch が先頭): %s" % tab.text_content("#list .pt-case .pt-case-sub"))

        tab.select_option("#fGroup", "channel")
        check(wait_js(tab, "document.querySelectorAll('#list .ui-group').length === 4", 10000),
              "[A] 配信者ごとにまとめる(配信者4人ぶんの見出し): %s" % tab.evaluate("document.querySelectorAll('#list .ui-group').length"))
        check(tab.evaluate("[...document.querySelectorAll('#list .ui-group')].every(g => !g.open)"),
              "[A] まとまりは既定で閉じている(まとめて実行が動いている配信は無いので)")
        tab.click("#list .ui-group:first-child summary")
        check(wait_js(tab, "document.querySelector('#list .ui-group').open === true", 5000), "[A] まとまりをクリックで開ける")
        tab.reload()
        check(wait_js(tab, "document.querySelector('#fGroup').value === 'channel' && document.querySelector('#fSort').value === 'channel'", 10000),
              "[A] 並び替え・まとめ方はブラウザに覚えている(読み込み直しても)")
        tab.select_option("#fGroup", "")
        tab.select_option("#fSort", "new")
        real = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
        check(not real, "[A] 一覧の道具を操作しても画面のエラーなし: %s" % real[:3])
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
        check(wait_js(mob, "document.querySelectorAll('.pt-tool[data-state=running]').length === 2"), "[A] 狭い画面でも表示")
        check(mob.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "[A] 狭い画面で横にはみ出さない")
        xs = mob.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => Math.round(e.getBoundingClientRect().left))")
        check(len(set(xs)) == 1, "[A] 狭い画面では縦に並ぶ: %s" % xs)
        if shots:
            mob.screenshot(path=os.path.join(shots, "portal-mobile.png"), full_page=True)

        # 9. すべて終了(2回押し)。3つとも取り込みなので、この形には子プロセスは無い
        pg.click("#btnQuit")
        check(pg.text_content("#btnQuit").startswith("もう一度押すと終了します"), "[A] 1回目は確認だけ(残り秒数を見せる): %s" % pg.text_content("#btnQuit"))
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

        for tid in SHOWN:
            check(wait_card(pg, tid, "running"), "[B] %s が動作中" % tid)
        check(pg.evaluate("document.querySelectorAll('.pt-tool').length") == 2, "[B] カードは2枚(cut2resolve は動いている間は出さない)")

        for tid in ("studio",):
            meta = pg.text_content(".pt-tool[data-tool=%s] .pt-meta" % tid)
            check(("ポート %d" % port) in meta and "入口に取り込み" in meta, "[B] %s は入口に取り込み: %s" % (tid, meta))
            check(pg.is_disabled(".pt-tool[data-tool=%s] .pt-toggle" % tid) and pg.is_disabled(".pt-tool[data-tool=%s] .pt-restart" % tid),
                  "[B] 取り込んだ%sは単独で止めない" % tid)
        meta = pg.text_content(".pt-tool[data-tool=transcribe] .pt-meta")
        check(("ポート %d" % ports["transcribe"]) in meta and TX_VER in meta and "入口に取り込み" not in meta,
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
        seed_cases(tmp, env["STUDIO_HOME"])

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
