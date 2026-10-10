#!/usr/bin/env python3
"""ホーム(src/home/portal.html。段階5: 入口 + 案件を1つにした)の通し確認(Playwright。本物の3ツールを疑似モードで
一時フォルダに写し、空きポートだけを使う)。

    python src/home/tests/e2e_portal.py [--shots <フォルダ>]

いまは「文字起こし」も入口に取り込める(段階3-3。src/home/mount.py の MOUNTS)ので、2つの形をそれぞれ確かめる:

  (A) 本番と同じ形(python src/home/launch.py と同じ mounts=tuple(mount.MOUNTS)): 3つとも入口に取り込み。
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
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402
from ytt_core import layout, schemas  # noqa: E402


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
    # 文字起こしの文書 id は src/editor/serve.py の TID_RE(12文字の16進)を満たす必要がある(manage.cases.txindex は緩いが、
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


def seed_accuracy(app_dir):
    """精度の自動測定の記録(src/eval/drill/accuracy.py の accuracy-state.json)に、定点 950 秒・話者の行 120・普段 600 秒を置く(ほかの領域は未測定のまま)"""
    os.makedirs(app_dir, exist_ok=True)
    at = int(time.time() * 1000) - 3600 * 1000
    st = {"day": "2000-01-01", "areas": {
        "asr": {"latest": {"at": at, "file": "20260101-000001_auto.json", "summary": {"label": "CER", "value": 0.093, "docs": 22, "unit": "文書", "better": "lower",
                                                                             "few": False, "lowData": False, "extra": [], "reviewedSec": 950.0}}},
        "speakers": {"latest": {"at": at, "file": "20260101-000001.json", "summary": {"label": "行ごとの話者の正しさ", "value": 0.86, "docs": 5, "unit": "文書",
                                                                               "better": "higher", "few": True, "lowData": True, "extra": [], "rows": 120.0}}}},
        "daily": {"sec": 600.0, "docs": 2, "lines": 40, "at": at}}
    with open(os.path.join(app_dir, "accuracy-state.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


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
    seed_accuracy(os.path.dirname(sup.logs_dir))   # 入口の条件(あと何本・何分)を出すための前回の測定の記録(入口が起動時に読む)
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

        cx = types.SimpleNamespace(**locals())   # 場面の関数(下の _mounted_*)へ渡す値。場面が作って、あとで使う値は場面が cx に戻す
        _mounted_cards_and_health(cx)
        _mounted_open_tools(cx)
        _mounted_cases_and_memo(cx)
        _mounted_todo_and_unlinked(cx)
        _mounted_list_tools(cx)
        _mounted_next_steps(cx)
        _mounted_redirect_theme_narrow(cx)
        mob = cx.mob   # 8. の狭い画面のタブ(10. で使う)
        _mounted_auto_clips(cx)   # スタジオの data.json を書き直すので最後に(前の場面が足した配信はスタジオが知らないので消える)

        # 9. すべて終了(2回押し)。3つとも取り込みなので、この形には子プロセスは無い
        pg.click("#btnQuit")
        check(pg.text_content("#btnQuit").startswith("もう一度押すと終了します"), "[A] 1回目は確認だけ(UIKit.confirmTwice): %s" % pg.text_content("#btnQuit"))
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


def _mounted_cards_and_health(cx):
    """[A] 1. カード・1b. 「詳しく」の「調子」と「片付け」・取り込みの表示"""
    check, pg, port, shots = cx.check, cx.pg, cx.port, cx.shots
    # 1. カードは2枚(① 切り抜きスタジオ → ② 編集)。cut2resolve は「編集」の部品として取り込まれて動くが、カードは出さない
    for tid in SHOWN:
        check(wait_card(pg, tid, "running"), "[A] %s が動作中" % tid)
    order = pg.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => e.getAttribute('data-tool'))")
    check(order == ["studio", "transcribe"], "[A] カードは作業の順に2枚(スタジオ → 編集): %s" % order)
    check(pg.text_content(".pt-tool[data-tool=transcribe] .pt-name") == "編集", "[A] 文字起こしのカードは「編集」")
    c2r = next(t for t in pg.evaluate("fetch('/api/status', {cache: 'no-store'}).then(r => r.json())")["tools"] if t["id"] == "cut2resolve")
    check(c2r["state"] == "running" and c2r["mounted"] and c2r["hidden"], "[A] cut2resolve はホームに取り込まれて動いている(カードは出さない): %s" % {k: c2r[k] for k in ("state", "mounted", "hidden")})
    check(pg.text_content("#ver") == "ホーム v" + L.VERSION, "[A] ヘッダーの版: %s" % pg.text_content("#ver"))
    check(pg.is_hidden("#conn") and pg.text_content("#conn") == "接続済み", "[A] つながったあとは「接続」の札を出さない(切れたときだけ「切断」。S12): %s" % pg.text_content("#conn"))
    check(wait_js(pg, "document.querySelector('[data-ui-appnav-item=\"studio\"]')?.getAttribute('href') === '/studio/'"
                      " && document.querySelector('[data-ui-appnav-item=\"transcribe\"]')?.getAttribute('href') === '/transcribe/'", 10000),
          "[A] ホームの ui-appnav の「スタジオ」「編集」は、取り込みが分かってから正しい場所に直る: %s"
          % pg.eval_on_selector_all("[data-ui-appnav-item]", "els => els.map(e => [e.getAttribute('data-ui-appnav-item'), e.getAttribute('href')])"))

    # 1b. 「詳しく」は既定で閉じている。テストのため開く(サーバーの管理の操作をクリックできるように)
    check(open_advanced(pg), "[A] 「詳しく」は既定で閉じている")
    # 段9 9-1: 「調子」(版・認識ワーカー・外部プログラム・空き容量・作業データ・エラーの件数)が「詳しく」の先頭に出る
    check(wait_js(pg, "[...document.querySelectorAll('#healthList > li')].length >= 6", 20000), "[A] 「調子」が出る(6 項目以上): %d" % pg.locator("#healthList > li").count())
    ht = pg.inner_text("#healthList")
    check("版" in ht and "文字起こしの処理" in ht and "認識ワーカー" not in ht and "空き容量" in ht and "画面のエラー" in ht and "まとめて実行の失敗" in ht and "pid" not in ht,
          "[A] 調子の項目: 版・文字起こしの処理(内部の言葉・pid は本文に出さない)・空き容量・エラーの件数: %s" % " / ".join(ht.split())[:160])
    check("良い" not in ht and "悪い" not in ht and ("問題なし" in ht or "要対応" in ht) and "YTT_FFMPEG" not in ht, "[A] S13・S9: 調子の札は 問題なし・注意・要対応・測定。環境変数名は本文に出さない: %s" % " / ".join(ht.split())[:120])
    check(wait_js(pg, "document.querySelector('#healthList').textContent.indexOf('作業データ ') >= 0 && document.querySelector('#healthList').textContent.indexOf('数えています') < 0", 20000), "[A] 作業データの大きさは別のスレッドで数えて、終わったら出る")
    # 入口 0.38.0: 入口の条件(あと何本・何分)。前回の測定の記録から「今 / 目標 / あと」を 1 行ずつ・無いものは「未測定」
    check(wait_js(pg, "!!document.getElementById('accuracyGoals')", 20000), "[A] 調子に「始める条件(あと何本・何分)」が出る")
    gt = pg.inner_text("#accuracyGoals") if pg.query_selector("#accuracyGoals") else ""
    check("始める条件(あと何本・何分)" in gt and "定点 15 分: 今 15.8 分 / 目標 15 分 / 届いた" in gt and "定点 30 分: 今 15.8 分 / 目標 30 分 / あと 14.2 分" in gt and "G1" not in gt and "G2" not in gt
          and "学習用の校正 3 時間: 今 0.17 時間 / 目標 3 時間 / あと 2.83 時間" in gt and "確かめ済みの話者の行 200: 今 120 行 / 目標 200 行 / あと 80 行" in gt
          and "採用の記録 配信 10 本: 未測定" in gt and "届いた 1 / 8・未測定 3" in gt,
          "[A] 入口の条件: 今 / 目標 / あと と 未測定: %s" % " / ".join(gt.split("\n"))[:600])
    pg.click("#btnHealthRefresh")
    check(wait_js(pg, "document.querySelector('#healthWhen').textContent.indexOf('数えた') >= 0", 20000), "[A] 「数え直す」で数え直して、いつ数えたかが出る: %s" % pg.text_content("#healthWhen"))
    # 段9 9-2: 「片付け」の節。候補を探すと種類ごと(5 種類)に出て、何も選ばなければ移せない
    pg.click("#btnCleanFind")
    check(wait_js(pg, "document.querySelectorAll('#cleanKinds details').length === 5", 20000), "[A] 「片付け」の候補が種類ごとに出る: %d" % pg.locator("#cleanKinds details").count())
    check(pg.is_disabled("#btnCleanMove") and "候補" in pg.text_content("#cleanWhen"), "[A] 何も選んでいなければ「ごみ箱フォルダへ移す」は押せない")

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


def _mounted_open_tools(cx):
    """[A] 2. スタジオを開く・2b. /cut2resolve/ の転送・2c. 編集を開く"""
    base, check, ctx, pg, port = cx.base, cx.check, cx.ctx, cx.pg, cx.port
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
    # 2c. 編集(文字起こし)も同じアドレスの /transcribe/ で開ける(段階3-3。認識自体は別プロセスの pipeline/transcribe/worker.py)
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


def _mounted_cases_and_memo(cx):
    """[A] 2d. 案件の一覧・2d-2. 離れて戻ってもメモの下書きが残る・2d-3. メモの保存の応答待ち"""
    check, ctx, pg = cx.check, cx.ctx, cx.pg
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
    # B-8(段1): 案件の行から、その配信をスタジオの ② 確認で開く。S-15(入口 0.42.0): 同じ窓で移る(target を付けない = 窓・タブを増やさない)
    sh = pg.eval_on_selector_all(".pt-case-studio a", "els => els.map(a => [a.textContent, a.getAttribute('href'), a.getAttribute('target')])")
    check(sh == [["スタジオで開く", "/studio/?video=e2eCase0001", None]],
          "[A] 案件の行に「スタジオで開く」(?video= に案件の id・同じ窓で移る): %s" % sh)
    tab = ctx.new_page()   # この画面(pg)は下の確認で使うので、同じホームを別のタブで開いて押す
    tab.goto(cx.base)
    check(wait_js(tab, "!!document.querySelector('.pt-case-studio a')", 15000), "[A] 別のタブのホーム")
    tab.evaluate("document.querySelector('.pt-case').open = true")
    n_pages = len(ctx.pages)
    tab.click(".pt-case-studio a")
    tab.wait_for_url(lambda u: "/studio/" in u, timeout=20000)
    check(wait_js(tab, "!!(window.Studio && Studio.ready) && Studio.params.video === 'e2eCase0001' && Studio.step === 'review'", 20000),
          "[A] 「スタジオで開く」でスタジオがその配信を ② 確認で開いた: %s"
          % tab.evaluate("window.Studio && [Studio.params, Studio.step]"))
    check(len(ctx.pages) == n_pages, "[A] S-15: 「スタジオで開く」は同じタブで移る(新しいタブを開かない): %d → %d" % (n_pages, len(ctx.pages)))
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
    # 再描画でも消えない(E2 finding 1)。blur→focus の起こし方は src/home/tests/e2e_window.py の「7-2 離れた・戻った」と同じ
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

    # 2d-3. 監査 14(段2): メモの保存の応答を待つ間に書き足した分は消さない・「保存しました」は保存した内容のときだけ・二度押しは最後の値。
    # 応答を遅らせるのは画面の fetch を包んで行う(要求はすぐサーバーへ送り、応答だけを __release() まで止める。
    # page.route の同期版は、止めている間 Playwright の操作も止まるので使わない)
    pg.evaluate("""() => {
            const orig = window.fetch.bind(window);
            window.__origFetch = orig; window.__held = []; window.__memoSent = [];
            window.fetch = (url, init) => {
                let body = null;
                try { body = init && init.body ? JSON.parse(init.body) : null; } catch (e) { body = null; }
                if (String(url).indexOf('/api/cases/update') >= 0 && body && body.memo != null) {
                    window.__memoSent.push(body.memo);
                    const p = orig(url, init);
                    return new Promise((res, rej) => window.__held.push(() => p.then(res, rej)));
                }
                return orig(url, init);
            };
            window.__release = () => { const h = window.__held.shift(); if (h) h(); return !!h; };
        }""")
    server_memo = lambda: pg.evaluate("window.__origFetch('/api/cases', {cache: 'no-store'}).then(r => r.json()).then(j => j.cases[0].memo)")
    memo_msg = lambda: pg.evaluate("document.querySelector('.pt-case .pt-memo-msg').textContent")
    pg.fill(".pt-case textarea", "メモA")
    pg.click(".pt-case .pt-memo-save")
    check(wait_js(pg, "window.__memoSent.length === 1", 5000) and pg.text_content(".pt-case .pt-memo-save") == "保存中…",
          "[A] メモの保存中はボタンが「保存中…」: %s" % pg.text_content(".pt-case .pt-memo-save"))
    pg.fill(".pt-case textarea", "メモA\n追記B")   # 応答の前に書き足す
    pg.evaluate("document.querySelector('.pt-case').__old = true")
    pg.evaluate("() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }")   # 応答を待つ間に行が作り直される
    time.sleep(0.4)
    pg.evaluate("() => { document.hasFocus = () => true; window.dispatchEvent(new Event('focus')); }")
    check(wait_js(pg, "document.querySelector('.pt-case') && !document.querySelector('.pt-case').__old", 10000)
          and pg.text_content(".pt-case .pt-memo-save") == "保存中…", "[A] 保存中に行が作り直されても「保存中…」のまま")
    pg.evaluate("window.__release()")
    check(wait_js(pg, "document.querySelector('.pt-case .pt-memo-msg').textContent === '保存しました(そのあとの入力はまだ保存していません)'", 10000),
          "[A] 保存の応答のあとも、書き足した分はまだ保存していないと出す(作り直した行に): %s" % memo_msg())
    check(pg.input_value(".pt-case textarea") == "メモA\n追記B" and server_memo() == "メモA",
          "[A] 書き足した入力は消えない・サーバーは送った分(A)だけ: %r / %r" % (pg.input_value(".pt-case textarea"), server_memo()))
    check(pg.text_content(".pt-case .pt-memo-save") == "メモを保存", "[A] 応答のあとはボタンが元に戻る")
    pg.click(".pt-case .pt-memo-save")
    wait_js(pg, "window.__memoSent.length === 2", 5000)
    pg.evaluate("window.__release()")
    check(wait_js(pg, "document.querySelector('.pt-case .pt-memo-msg').textContent === '保存しました'", 10000) and server_memo() == "メモA\n追記B",
          "[A] もう一度保存すると、書き足した分もサーバーに入って「保存しました」: %s / %r" % (memo_msg(), server_memo()))
    pg.fill(".pt-case textarea", "メモC1")   # 二度押し: 送っている間の押し直しは、応答のあとに今の下書きを1回だけ送る
    check(memo_msg() == "", "[A] 書き足したら前の「保存しました」は消える: %s" % memo_msg())
    pg.click(".pt-case .pt-memo-save")
    wait_js(pg, "window.__memoSent.length === 3", 5000)
    pg.fill(".pt-case textarea", "メモC2")
    pg.click(".pt-case .pt-memo-save")
    pg.click(".pt-case .pt-memo-save")
    time.sleep(0.3)
    check(pg.evaluate("window.__memoSent.length") == 3, "[A] 送っている間の押し直しでは、すぐには送らない(応答の順が入れ替わらない)")
    pg.evaluate("window.__release()")
    check(wait_js(pg, "window.__memoSent.length === 4", 5000) and pg.evaluate("window.__memoSent[3]") == "メモC2"
          and memo_msg() == "" and pg.text_content(".pt-case .pt-memo-save") == "保存中…",
          "[A] 応答のあとで今の下書き(C2)を1回だけ送る(まだ「保存しました」と言わない): %s / %s" % (pg.evaluate("window.__memoSent"), memo_msg()))
    pg.evaluate("window.__release()")
    check(wait_js(pg, "document.querySelector('.pt-case .pt-memo-msg').textContent === '保存しました'", 10000) and server_memo() == "メモC2"
          and pg.evaluate("window.__memoSent.length") == 4, "[A] 二度押しでは最後の値(C2)が残る: %r" % server_memo())
    pg.fill(".pt-case textarea", "")   # 後の確認のためにメモを空に戻す
    pg.click(".pt-case .pt-memo-save")
    wait_js(pg, "window.__memoSent.length === 5", 5000)
    pg.evaluate("window.__release()")
    wait_js(pg, "document.querySelector('.pt-case .pt-memo-msg').textContent === '保存しました'", 10000)
    pg.evaluate("window.fetch = window.__origFetch")
    cx.case_doc = case_doc


def _mounted_todo_and_unlinked(cx):
    """[A] 2e. 次にやること・2f. 単体の文字起こし"""
    case_doc, check, pg = cx.case_doc, cx.check, cx.pg
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
    check(wait_js(pg, "!document.getElementById('unlinkedGroup').hidden && !document.getElementById('unlinkedHead').hidden", 10000), "[A] 単体の文字起こしの1行とまとまりが出た")
    check(pg.text_content("#unlinkedCount").strip() == "1件", "[A] 単体の文字起こしの件数(ホームの数): %s" % pg.text_content("#unlinkedCount"))
    link = pg.get_attribute("#unlinkedOpen", "href")
    check(bool(link) and link.startswith("/transcribe/?list=other"), "[A] 「編集の履歴で見る」は編集の履歴を「それ以外」で開く(段5 5-1・B-5): %s" % link)
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


def _mounted_list_tools(cx):
    """[A] 2g. 一覧の道具・2g-2. 一覧の非表示"""
    check, errors, pg = cx.check, cx.errors, cx.pg
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

    # 2g-2. 一覧の非表示(UIKit.hide。2026-10-04): 案件を隠す → 消える → 読み込み直しても隠れたまま → 「非表示 n件を表示」で薄く出る → 戻す
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case .pt-hide').length >= 1 && document.getElementById('casesHidden').hidden", 10000),
          "[A] 非表示: 案件の行に「非表示にする」があり、隠したものが無いときは切り替えを出さない")
    hid_id = pg.evaluate("document.querySelector('#list .pt-case').dataset.id")
    pg.evaluate("document.querySelector('#list .pt-case .pt-hide').click()")
    check(wait_js(pg, "!document.getElementById('case-' + %r) && !document.getElementById('casesHidden').hidden" % hid_id, 10000),
          "[A] 非表示: 隠した案件が一覧から消え、「非表示 n件を表示」が出る")
    check(pg.text_content("#casesHidden").strip() == "非表示 1件を表示" and "非表示 1 本" in pg.text_content("#summary"),
          "[A] 非表示: 切り替えと要約に隠した数: %s / %s" % (pg.text_content("#casesHidden"), pg.text_content("#summary")))
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast-msg')].some(e => e.textContent.indexOf('非表示にしました') >= 0)", 5000),
          "[A] 非表示: 知らせ(元に戻す つき)が出る")
    pg.reload()
    pg.evaluate("document.getElementById('advancedBox').open = true")   # あとの「すべて終了」のため(読み込み直すと閉じる)
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length >= 1 && !document.getElementById('case-' + %r) && !document.getElementById('casesHidden').hidden" % hid_id, 15000),
          "[A] 非表示: 読み込み直しても隠れたまま(ホームの設定に覚えている)")
    pg.click("#casesHidden")
    check(wait_js(pg, "!!document.getElementById('case-' + %r) && document.getElementById('case-' + %r).classList.contains('ui-hidden-item')" % (hid_id, hid_id), 10000),
          "[A] 非表示: 「非表示 n件を表示」で薄く出る")
    check(pg.evaluate("document.querySelector('#case-' + CSS.escape(%r) + ' .pt-hide').textContent" % hid_id) == "表示に戻す", "[A] 非表示: 出した行のボタンは「表示に戻す」")
    pg.evaluate("document.querySelector('#case-' + CSS.escape(%r) + ' .pt-hide').click()" % hid_id)
    check(wait_js(pg, "!document.getElementById('case-' + %r).classList.contains('ui-hidden-item')" % hid_id, 10000), "[A] 非表示: 「表示に戻す」で戻る")
    pg.click("#casesHidden")   # 「非表示のものを隠す」→ 隠したものが無いので切り替えは消える
    check(wait_js(pg, "document.getElementById('casesHidden').hidden", 5000), "[A] 非表示: 隠したものが無くなれば切り替えも消える")
    # 次にやること: 1行を隠す → 「元に戻す」で戻る(書き出し待ちが増えて 5 件を超えるので、先に「すべて見る」。入口 0.42.0)
    if pg.is_visible("#todoMore") and pg.text_content("#todoMore").startswith("すべて見る"):
        pg.click("#todoMore")
    n_todo = pg.evaluate("document.querySelectorAll('#todoList .pt-todo-hide').length")
    if n_todo:
        pg.evaluate("document.querySelector('#todoList .pt-todo-hide').click()")
        check(wait_js(pg, "document.querySelectorAll('#todoList .pt-todo-hide').length === %d && !document.getElementById('todoHidden').hidden" % (n_todo - 1), 10000),
              "[A] 非表示: 次にやることの1行を隠せる")
        wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('非表示にしました') >= 0 && t.querySelector('.ui-toast-act'))", 5000)   # 知らせは送ったあとに出る
        pg.evaluate("[...document.querySelectorAll('.ui-toast')].reverse().find(t => t.textContent.indexOf('非表示にしました') >= 0).querySelector('.ui-toast-act').click()")
        check(wait_js(pg, "document.querySelectorAll('#todoList .pt-todo-hide').length === %d && document.getElementById('todoHidden').hidden" % n_todo, 10000),
              "[A] 非表示: 知らせの「元に戻す」で戻る")
    else:
        check(False, "[A] 非表示: 次にやることに隠せる行が無い(見本のデータを確かめる)")
    real = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
    check(not real, "[A] 一覧の道具を操作しても画面のエラーなし: %s" % real[:3])


NEXT_KINDS = {"校正待ち": 0, "パック待ち": 1, "作り直し": 1, "文字起こし待ち": 2, "書き出し待ち": 3, "候補の確認待ち": 4}   # 次にやることの並び(仕上げに近い順)


def seed_next_cases(studio_json, tmp):
    """2i 用: 確認前の候補だけの配信(候補 3・見送り 1)と、書き出したが文字起こしが無い配信を足す(書き出し待ちは seed_more_cases の採用)"""
    clip = os.path.join(tmp, "exports", "02_次テスト.mp4")
    with open(clip, "wb") as f:
        f.write(b"x")
    with open(studio_json, encoding="utf-8") as f:
        doc = json.load(f)
    now = int(time.time() * 1000)

    def cand(mid, st=""):
        return {"id": mid, "start": 10.0, "end": 40.0, "label": "候補", "status": st, "src": "auto"}
    doc["videos"]["e2eNext0001"] = {"id": "e2eNext0001", "kind": "youtube", "title": "次テスト 候補", "channel": "chNext", "duration": 100,
                                    "analysis": {"uploadDate": "20260101"}, "createdAt": now, "updatedAt": now,
                                    "marks": [cand("m1"), cand("m2"), cand("m3"), cand("m4", "rejected")]}
    doc["videos"]["e2eNext0002"] = {"id": "e2eNext0002", "kind": "youtube", "title": "次テスト 文字起こし", "channel": "chNext", "duration": 100,
                                    "createdAt": now - 1000, "updatedAt": now - 1000,
                                    "marks": [{"id": "m1", "start": 10.0, "end": 40.0, "label": "見どころ", "status": "exported",
                                               "file": os.path.basename(clip), "path": clip}]}
    with open(studio_json, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def wait_routed(pg, fn, timeout):
    """page.route の偽物の応答を待つ(同期版の Playwright は、ページの操作の間にだけ route の関数を呼ぶので、待つ間も wait_for_timeout で回す)"""
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        pg.wait_for_timeout(100)
    return bool(fn())


def _mounted_next_steps(cx):
    """[A] 2i. 気が利く画面へ 段 7〜8(入口 0.42.0): 次にやることの種類と並び(S-6)・同じ題名の副題(S-26)・案件の行のボタン(S-18)・
    リンクの開き方(S-15)・配信が無いときの空の表示(S-13)・消えた配信のまとめて実行(S-25)・フォーカスと Enter(S-24)"""
    check, pg = cx.check, cx.pg
    seed_next_cases(os.path.join(os.environ["STUDIO_HOME"], "data.json"), cx.tmp)
    pg.click("#btnReload")
    check(wait_js(pg, "!!document.getElementById('case-e2eNext0002')", 15000), "[A] 2i: 足した配信が一覧に出た")
    _next_todo(cx)
    _next_case_buttons(cx)
    _next_empty_state(cx)
    _next_gone_case(cx)
    _next_focus_and_enter(cx)
    _ui_review_checks(cx)


def _next_todo(cx):
    """S-6: 次にやることに 文字起こし待ち・書き出し待ち・確認前の候補(スタジオの ② へ)と並び / S-26: 紐づかない文書の副題"""
    check, pg = cx.check, cx.pg
    if pg.is_visible("#todoMore") and pg.text_content("#todoMore").startswith("すべて見る"):
        pg.click("#todoMore")
    check(wait_js(pg, "[...document.querySelectorAll('.pt-todo-pill')].some(p => p.textContent === '候補の確認待ち')", 15000), "[A] S-6: 次にやることに候補の確認待ちが出た")
    todo = pg.eval_on_selector_all("#todoList .pt-todo-item", "els => els.map(e => [e.querySelector('.pt-todo-pill').textContent, "
                                   "e.querySelector('.pt-todo-link').getAttribute('href'), e.querySelector('.pt-todo-sub').textContent])")
    check(any(p == "候補の確認待ち" and h == "/studio/?video=e2eNext0001" and "候補 3個" in s and "chNext" in s for p, h, s in todo),
          "[A] S-6: 候補の確認待ち(見送りは数えない)・スタジオの ② でその配信を開く: %s" % todo)
    check(any(p == "文字起こし待ち" and h == "/studio/?video=e2eNext0002" and "文字起こし 1本" in s for p, h, s in todo), "[A] S-6: 文字起こし待ち: %s" % todo)
    check(any(p == "書き出し待ち" and h == "/studio/?video=e2eList0000" and "書き出し 1本" in s for p, h, s in todo), "[A] S-6: 書き出し待ち(採用したマーク): %s" % todo)
    order_api = pg.evaluate("fetch('/api/cases', {cache: 'no-store'}).then(r => r.json()).then(j => j.todoOrder)")
    check(order_api == ["proof", "pack", "transcribe", "export", "review"],
          "[A] M1: 案件の一覧が並びの表(todoOrder)を返す = 上の一覧と案件の行のボタンが同じ順(cases.py の TODO_ORDER): %s" % order_api)
    ranks = [NEXT_KINDS[p] for p, h, s in todo if p in NEXT_KINDS]
    check(ranks == sorted(ranks), "[A] S-6: 並びは 校正 → パック → 文字起こし → 書き出し → 候補の確認: %s" % [p for p, h, s in todo])
    solo = [s for p, h, s in todo if "doc=deadbeef0002" in h]
    check(bool(solo) and "solo.mp4" in solo[0] and "ytt-portal-e2e" not in solo[0] and "更新 " in solo[0],
          "[A] S-26: 紐づかない文書の行に元のファイル名(フォルダは出さない)と更新日時: %s" % solo)
    check(wait_js(pg, "!!document.querySelector('.pt-doc-sub') && document.querySelector('.pt-doc-sub').textContent.indexOf('solo.mp4') >= 0", 10000)
          and "更新 " in pg.text_content(".pt-doc-sub") and "ytt-portal-e2e" not in pg.text_content(".pt-doc-sub")
          and "solo.mp4" in (pg.get_attribute(".pt-doc-sub", "title") or ""),
          "[A] S-26: 単体の文字起こしの行にも副題(ファイル名だけ。フルパスは title): %s" % pg.text_content(".pt-doc-sub"))


def _next_case_buttons(cx):
    """S-18: 案件の行の「→ 書き出し 2本」などは押せるボタン / S-15: 中身のリンクは同じ窓(target なし)・ボタンで同じタブのまま移る"""
    check, ctx, pg = cx.check, cx.ctx, cx.pg
    if pg.is_visible("#btnMore"):   # 一覧の 31 件目より後(e2eCase0001)も見る
        pg.click("#btnMore")
    nx_js = ("id => { const a = document.querySelector('#case-' + id + ' .pt-case-next');"
             " return a && [a.tagName, a.className, a.getAttribute('href'), a.textContent, a.hidden, a.getAttribute('target')]; }")
    got = {vid: pg.evaluate(nx_js, vid) for vid in ("e2eNext0001", "e2eNext0002", "e2eList0000", "e2eCase0001")}
    check(got["e2eNext0001"] == ["A", "btn small ui-next-btn pt-case-next", "/studio/?video=e2eNext0001", "候補の確認 3個", False, None],
          "[A] S-18: 候補の確認のボタン: %s" % got["e2eNext0001"])
    check(got["e2eNext0002"] and got["e2eNext0002"][2:4] == ["/studio/?video=e2eNext0002", "文字起こし 1本"], "[A] S-18: 文字起こしのボタン: %s" % got["e2eNext0002"])
    check(got["e2eList0000"] and got["e2eList0000"][2:4] == ["/studio/?video=e2eList0000", "書き出し 1本"], "[A] S-18: 書き出しのボタン: %s" % got["e2eList0000"])
    c0 = got["e2eCase0001"]
    check(bool(c0) and c0[1] == "btn small ui-next-btn pt-case-next" and (c0[2] or "").startswith("/transcribe/?doc=deadbeef0001") and (c0[2] or "").endswith("#tx")
          and c0[3] == "校正 1本", "[A] S-18: 校正のボタンは編集の校正のタブへ(文書 ID で): %s" % c0)
    tg = pg.evaluate("""() => ({ content: [...document.querySelectorAll('.pt-clip a, .pt-case-studio a, .pt-case-next[href], #unlinkedOpen, .pt-doc-open, .pt-todo-link')]
                                      .filter(a => a.hasAttribute('target')).map(a => a.textContent),
                                 open: [...document.querySelectorAll('.pt-tool .pt-open')].map(a => a.target) })""")
    check(tg["content"] == [] and tg["open"] and all(t == "_blank" for t in tg["open"]),
          "[A] S-15: 中身のリンクは同じ窓(target なし)・「詳しく」の「開く」(サーバーの管理)だけ新しい窓: %s" % tg)
    p2 = ctx.new_page()
    p2.on("pageerror", lambda e: cx.errors.append(str(e)))
    p2.goto(cx.base)
    check(wait_js(p2, "!!document.getElementById('case-e2eNext0002')", 15000), "[A] S-18: 別のタブのホーム")
    p2.fill("#fText", "案件の通し確認")
    check(wait_js(p2, "!!document.querySelector('#case-e2eCase0001 .pt-case-next[href]')", 10000), "[A] S-18: 絞り込んで校正のボタンが出た")
    n_pages = len(ctx.pages)
    p2.click("#case-e2eCase0001 .pt-case-next")
    p2.wait_for_url(lambda u: "/transcribe/" in u, timeout=20000)
    check(len(ctx.pages) == n_pages, "[A] S-18・S-15: ボタンを押すと同じタブのまま編集へ移る: %s" % p2.url)
    p2.close()


def _next_empty_state(cx):
    """S-13: 配信が 1 本も無いときの空の表示に、次に押すボタン(案件の一覧の応答を空にした別のタブ)"""
    check, ctx = cx.check, cx.ctx
    p3 = ctx.new_page()
    p3.on("pageerror", lambda e: cx.errors.append(str(e)))
    p3.route("**/api/cases", lambda route: route.fulfill(json={"cases": [], "unlinked": [], "casesFile": ""}))
    p3.route("**/transcribe/api/transcripts", lambda route: route.fulfill(json={"items": []}))   # 次にやることを空にする(文書ごとの校正待ちも無し)
    p3.goto(cx.base)
    check(wait_js(p3, "!!document.getElementById('emptyStudio')", 15000), "[A] S-13: 配信が無いときの空の表示")
    et = p3.text_content("#list .empty")
    check("まだ配信はありません" in et and "ここに出ます" in et, "[A] S-13: 空の表示は 2 文(何が無い + どうすると出る): %s" % et)
    check(p3.get_attribute("#emptyStudio", "href") == "/studio/?step=rank" and p3.get_attribute("#emptyStudio", "target") is None,
          "[A] S-13: 「スタジオで配信を探す」はスタジオの ① 探す へ(?step=rank。同じ窓)")
    check(wait_js(p3, "!document.getElementById('intakeBox').hidden && !!document.getElementById('emptyIntake')", 10000), "[A] S-13: 「依頼の受付を設定する」が出る")
    check(wait_js(p3, "!document.getElementById('todoEmpty').hidden && document.getElementById('todoEmptyBtn').getAttribute('href') === '/studio/?step=rank'", 10000)
          and "ここに出ます" in p3.text_content("#todoEmpty"), "[A] M5: 次にやることが 0 件のときも 2 文 + [スタジオで配信を探す]: %s" % p3.text_content("#todoEmpty"))
    p3.click("#emptyIntake")
    check(wait_js(p3, "document.getElementById('intakeBox').open && document.activeElement && document.activeElement.id === 'intakeEnabled'", 5000),
          "[A] S-13: 押すと依頼の受付が開き、オン/オフのスイッチへフォーカス(0.54.0: フォルダの欄は設定の画面): %s" % p3.evaluate("document.activeElement && document.activeElement.id"))
    p3.close()


def _next_gone_case(cx):
    """S-25: スタジオから消えた配信は、まとめて実行を隠さずに押せなくして理由を出す(案件の一覧の応答の e2eCase0001 を gone に)"""
    check, ctx = cx.check, cx.ctx

    def gone_cases(route):
        resp = route.fetch()
        j = resp.json()
        for c in j.get("cases", []):
            if c.get("id") == "e2eCase0001":
                c["gone"] = True
        route.fulfill(response=resp, json=j)
    p4 = ctx.new_page()
    p4.on("pageerror", lambda e: cx.errors.append(str(e)))
    p4.route("**/api/cases", gone_cases)
    p4.goto(cx.base)
    check(wait_js(p4, "!!document.getElementById('case-e2eNext0002')", 15000), "[A] S-25: ホーム")
    p4.fill("#fText", "案件の通し確認")
    check(wait_js(p4, "!!document.getElementById('case-e2eCase0001')", 10000), "[A] S-25: 消えた配信の行")
    time.sleep(1.0)   # まとめて実行の読み込み(renderAuto)のあとも押せないまま
    g = p4.evaluate("""() => { const n = document.getElementById('case-e2eCase0001'); if (!n) return null;
        const box = n.querySelector('.pt-auto'), run = n.querySelector('.pt-auto-run'), why = n.querySelector('.pt-auto-why');
        return [box.hidden, run.disabled, why.hidden, why.textContent, run.getAttribute('aria-describedby') === why.id,
                n.querySelector('.pt-auto-streamer').disabled, !!n.querySelector('.pt-case-studio a')]; }""")
    check(g and g[0] is False and g[1] is True and g[2] is False and "スタジオから消えた配信" in g[3] and "入れ直す" in g[3] and g[4] and g[5] and not g[6],
          "[A] S-25: まとめて実行の欄は出したまま押せない・理由と戻し方を出す: %s" % g)
    p4.close()


def _next_focus_and_enter(cx):
    """S-24: 実行を押したら中止へフォーカス・終わったら実行へ戻す・配信者の欄の Enter で実行(まとめて実行の API は偽物)"""
    check, ctx = cx.check, cx.ctx
    st = {"state": None, "starts": []}

    def fake_run():
        return {"id": "e2erun00001", "kind": "video", "videoId": "e2eCase0001", "docId": None, "mode": "adopted", "modeLabel": "採用後を全部",
                "title": CASE_TITLE, "state": st["state"], "created": int(time.time() * 1000), "finished": None, "message": "", "error": "",
                "steps": [{"key": "pack", "label": "パック", "state": "run" if st["state"] == "running" else "done", "detail": ""}]}

    def fake_start(route):
        st["starts"].append(route.request.post_data_json)
        st["state"] = "running"
        route.fulfill(json={"run": fake_run()})
    p5 = ctx.new_page()
    p5.on("pageerror", lambda e: cx.errors.append(str(e)))
    p5.route("**/api/autorun/estimate", lambda route: route.fulfill(json={"steps": [{"label": "パック", "count": 1}], "nothing": False}))
    p5.route("**/api/autorun/start", fake_start)
    p5.route("**/api/autorun", lambda route: route.fulfill(json={"runs": [fake_run()] if st["state"] else [], "past": [], "modes": {}}))
    p5.goto(cx.base)
    check(wait_js(p5, "!!document.getElementById('case-e2eNext0002')", 15000), "[A] S-24: ホーム")
    p5.fill("#fText", "案件の通し確認")
    check(wait_js(p5, "!!document.getElementById('case-e2eCase0001')", 10000), "[A] S-24: 案件の行")
    p5.click("#case-e2eCase0001 .pt-case-title")   # 人と同じく行を押して開く
    check(wait_js(p5, "document.getElementById('case-e2eCase0001').open === true", 5000), "[A] S-24: 行を開いた")
    who = "#case-e2eCase0001 .pt-auto-streamer"
    p5.fill(who, "")   # 色なし(見つからない名前の確かめを出さない)
    p5.evaluate("s => document.querySelector(s).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }))", who)
    time.sleep(0.5)
    check(not st["starts"], "[A] S-24: かな漢字変換を確定する Enter では実行しない")
    p5.press(who, "Enter")
    check(wait_routed(p5, lambda: len(st["starts"]) == 1, 10) and (st["starts"][0] or {}).get("id") == "e2eCase0001",
          "[A] S-24: 配信者の欄の Enter で実行した: %s" % st["starts"])
    check(wait_js(p5, "document.activeElement === document.querySelector('#case-e2eCase0001 .pt-auto-cancel')", 10000),
          "[A] S-24: 実行を押したらフォーカスは中止へ: %s" % p5.evaluate("document.activeElement && document.activeElement.className"))
    st["state"] = "done"
    check(wait_js(p5, "document.querySelector('#case-e2eCase0001 .pt-auto-cancel').hidden"
                      " && document.activeElement === document.querySelector('#case-e2eCase0001 .pt-auto-run')", 20000),
          "[A] S-24: 終わったら中止は消えて、フォーカスは実行へ戻る: %s" % p5.evaluate("document.activeElement && document.activeElement.className"))
    p5.close()


def _ui_review_checks(cx):
    """[A] 2j. UI の見直し 1 周目(B の指摘 M2・M5〜M10・S10・S12): やることが無いときの次の一手・空の表示・フォーカス・札の色・中止・⚙ の「ホーム」の節・失敗の文"""
    check, ctx, pg = cx.check, cx.ctx, cx.pg
    # M7: 回る輪の札(run)は本当に動いているときだけ(案件の状態「作業中」・切り抜きの校正の途中には使わない)
    check(pg.evaluate("document.querySelectorAll('.pt-case-statuspill.run, .pt-clip-steps .pill.run').length") == 0, "[A] M7: 作業中・校正の途中の札に回る輪(run)を使わない")
    # M8: 中止は取り消せる(済んだ段は残る)ので danger にしない
    check(pg.evaluate("[...document.querySelectorAll('.pt-auto-cancel')].every(b => !b.classList.contains('danger') && b.title.indexOf('続きから') >= 0)"),
          "[A] M8: 中止は danger でなく、済んだ段が残ることを title に")
    # S10: すべて見る ⇄ 少なく表示
    if pg.is_visible("#todoMore"):
        t0 = pg.text_content("#todoMore")
        n0 = pg.evaluate("document.querySelectorAll('#todoList .pt-todo-item').length")
        if t0.startswith("すべて見る"):
            pg.click("#todoMore")
            check(pg.text_content("#todoMore") == "少なく表示" and pg.evaluate("document.querySelectorAll('#todoList .pt-todo-item').length") > n0
                  and pg.evaluate("document.activeElement.classList.contains('pt-todo-link')"), "[A] S10・M6: すべて見る → 最初に増えた行へフォーカス・「少なく表示」に変わる")
            pg.click("#todoMore")
            check(pg.text_content("#todoMore").startswith("すべて見る") and pg.evaluate("document.querySelectorAll('#todoList .pt-todo-item').length") == n0,
                  "[A] S10: 少なく表示で戻る")
    # M6: 非表示にしたあとフォーカスは次の行へ(body に落ちない)
    if pg.evaluate("document.querySelectorAll('#todoList .pt-todo-hide').length"):
        pg.focus("#todoList .pt-todo-hide")
        pg.keyboard.press("Enter")
        check(wait_js(pg, "!!document.activeElement && !!document.activeElement.closest('#todoBox')", 5000),
              "[A] M6: 非表示にしたあと、フォーカスは一覧の中に残る: %s" % pg.evaluate("document.activeElement && document.activeElement.className"))
        wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.querySelector('.ui-toast-act'))", 5000)
        pg.evaluate("[...document.querySelectorAll('.ui-toast')].reverse().find(t => t.textContent.indexOf('非表示にしました') >= 0).querySelector('.ui-toast-act').click()")
    # M5: 絞り込みで 0 件 → 2 文 + [絞り込みを消す]
    pg.fill("#fText", "存在しない配信の名前zzzz")
    check(wait_js(pg, "!!document.querySelector('#list .empty button')", 5000) and "全部の配信が出ます" in pg.text_content("#list .empty"),
          "[A] M5: 絞り込みで 0 件のとき 2 文とボタン: %s" % pg.text_content("#list .empty"))
    check("0 / " in pg.text_content("#count"), "[A] S5: 件数の分母は全体の数: %s" % pg.text_content("#count"))
    pg.click("#list .empty button")
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length > 0 && document.getElementById('fText').value === ''", 5000), "[A] M5: 絞り込みを消すと戻る")
    # M10: ⚙ の「ホーム」の節(窓で開く・まとめて実行の既定・試験中の機能)。「詳しく」の中には無い
    check(pg.evaluate("!document.querySelector('#advancedBox #winBox, #advancedBox #labBox')"), "[A] M10: 窓で開く・試験中の機能は「詳しく」から ⚙ の「ホーム」の節へ移った(二重にしない)")
    pg.click("[data-ui-settings]")
    check(wait_js(pg, "!!document.querySelector('#uiSettingsDrawer #homeSettings #winBox') && !!document.querySelector('#uiSettingsDrawer #homeSettings #setGoPage')", 5000)
          and pg.evaluate("document.querySelector('#uiSettingsDrawer #homeSettings > h3').textContent") == "ホーム"
          and pg.evaluate("!document.querySelector('#homeSettings #labBox, #homeSettings .ui-ar-sum, #homeSettings #setAutorun')"),
          "[A] M10: ⚙ に「ホーム」の節(窓で開く と 設定の画面へのリンク。0.54.0: まとめて実行の既定・試験中の機能の欄は設定の画面へ)")
    check((pg.get_attribute("#setGoBackup", "href") or "").endswith("settings#uiSetGroup-backup") and (pg.get_attribute("#setGoPage", "href") or "").endswith("settings#sec-home"),
          "[A] M10: ⚙ の「バックアップ」「設定の画面を開く」は設定の画面の節へのリンク")
    pg.click("#uiSettingsDrawer .ui-drawer-head button[aria-label=閉じる]")   # 閉じる(開いたままだと後の場面でキーが届かない)
    check(wait_js(pg, "!document.getElementById('uiSettingsDrawer').classList.contains('in')", 5000), "[A] M10: ⚙ を閉じる")
    # M2: 候補だけの配信で [実行] → やることが無い。理由だけでなく次の一手のボタンを出す
    p6 = ctx.new_page()
    p6.on("pageerror", lambda e: cx.errors.append(str(e)))
    p6.route("**/api/autorun/estimate", lambda route: route.fulfill(json={"steps": [{"label": "書き出し", "count": 0, "note": "採用したマークがありません"}],
                                                                           "nothing": True, "reason": "採用したマークがありません"}))
    p6.goto(cx.base)
    check(wait_js(p6, "document.querySelectorAll('.pt-case').length > 0", 15000), "[A] M2: ホーム")
    p6.fill("#fText", "次テスト 候補")
    check(wait_js(p6, "!!document.getElementById('case-e2eNext0001')", 10000), "[A] M2: 候補だけの配信の行")
    p6.click("#case-e2eNext0001 .pt-case-title")
    p6.fill("#case-e2eNext0001 .pt-auto-streamer", "")
    p6.click("#case-e2eNext0001 .pt-auto-run")
    check(wait_js(p6, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('やることがありません') >= 0 && t.textContent.indexOf('候補を採用') >= 0"
                      " && t.querySelector('.ui-toast-act') && t.querySelector('.ui-toast-act').textContent === '候補の確認へ')", 10000),
          "[A] M2: やることが無いとき、理由 + 次の一歩 + [候補の確認へ]: %s" % p6.evaluate("[...document.querySelectorAll('.ui-toast')].map(t => t.textContent)"))
    p6.evaluate("document.querySelector('.ui-toast-act').click()")
    p6.wait_for_url(lambda u: "/studio/" in u and "video=e2eNext0001" in u, timeout=20000)
    check(True, "[A] M2: [候補の確認へ] はスタジオの ② でその配信を開く: %s" % p6.url)
    p6.close()
    # M9: 状態の保存が失敗したとき: 「何が」+「どうすれば」・HTTP の番号は本文に出さない・[もう一度]
    p7 = ctx.new_page()
    p7.on("pageerror", lambda e: cx.errors.append(str(e)))
    p7.route("**/api/cases/update", lambda route: route.fulfill(status=500, json={}))
    p7.goto(cx.base)
    check(wait_js(p7, "document.querySelectorAll('.pt-case').length > 0", 15000), "[A] M9: ホーム")
    p7.fill("#fText", "次テスト 候補")
    check(wait_js(p7, "!!document.getElementById('case-e2eNext0001')", 10000), "[A] M9: 候補だけの配信の行")
    p7.click("#case-e2eNext0001 .pt-case-title")
    p7.select_option("#case-e2eNext0001 .pt-case-status", "working")
    check(wait_js(p7, "[...document.querySelectorAll('.ui-toast.err')].some(t => t.textContent.indexOf('状態を保存できませんでした') >= 0)", 10000), "[A] M9: 状態の保存の失敗の知らせ")
    msg = p7.evaluate("[...document.querySelectorAll('.ui-toast.err')].map(t => t.querySelector('.ui-toast-msg').textContent).join('|')")
    check("HTTP" not in msg and "もう一度" in msg, "[A] M9: 本文に HTTP の番号を出さず、次の一歩(もう一度選ぶ)を書く: %s" % msg)
    check(p7.evaluate("!!document.querySelector('.ui-toast.err .ui-toast-act') && document.querySelector('.ui-toast.err .ui-toast-detail').textContent.indexOf('HTTP 500') >= 0"),
          "[A] M9: 知らせに [もう一度]・原文(HTTP 500)は「詳しく」の中")
    p7.close()
    # M9: 案件の一覧を読めなかったとき: 欄の中に 2 文 + [読み込み直す](赤い帯は接続の文だけ。接続の確認で消えない)・次にやることも帯を指さない
    fail = {"on": True}
    p8 = ctx.new_page()
    p8.on("pageerror", lambda e: cx.errors.append(str(e)))
    p8.route("**/api/cases", lambda route: route.fulfill(status=500, json={}) if fail["on"] else route.continue_())
    p8.goto(cx.base)
    check(wait_js(p8, "!!document.querySelector('#list .empty button')", 15000), "[A] M9: 一覧を読めないとき、欄の中に 2 文とボタンが出る")
    time.sleep(3.5)   # 接続の確認(/api/status)が何度か回っても、一覧の文は消えない
    et = p8.text_content("#list .empty")
    check("案件の一覧を読めませんでした" in et and "読み込み直す" in et and "HTTP" not in et and p8.is_hidden("#errbar"),
          "[A] M9: 一覧の失敗の文は欄に残り(何が + どうすれば)、本文に HTTP の番号を出さず、赤い帯は出さない: %s" % et)
    check("案件の一覧の欄" in p8.text_content("#todoEmpty") and "上の赤い帯" not in p8.text_content("#todoEmpty"), "[A] M9: 次にやることは存在しない帯を指さない: %s" % p8.text_content("#todoEmpty"))
    fail["on"] = False
    p8.click("#list .empty button")
    check(wait_js(p8, "document.querySelectorAll('#list .pt-case').length > 0", 15000), "[A] M9: [読み込み直す] で一覧が戻る")
    # N1: 案件の行の「パックの音量」は出さない(「設定を変える」の中だけ。1 行に 2 か所にしない)
    check(p8.evaluate("document.querySelectorAll('.pt-auto-loud, .pt-auto-loudsel').length") == 0, "[A] N1: 案件の行にパックの音量の欄を二重に出さない")
    p8.close()


def _mounted_redirect_theme_narrow(cx):
    """[A] 2h. /cases.html の転送・7. テーマ・8. 狭い画面"""
    base, check, ctx, pg, port, shots = cx.base, cx.check, cx.ctx, cx.pg, cx.port, cx.shots
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
    check(pg.locator("[data-theme-toggle]").count() == 0, "[A] ヘッダーに明暗の切り替えボタンは無い(⚙ 設定のテーマで選ぶ)")
    want = "dark" if before != "dark" else "light"
    pg.click("[data-ui-settings]")
    theme_sel = "#uiSettingsDrawer .ui-settings-row:has-text('テーマ') select"
    pg.wait_for_selector(theme_sel, state="visible")
    pg.select_option(theme_sel, want)
    after = pg.get_attribute("html", "data-theme")
    check(before != after and after == want, "[A] ⚙ 設定のテーマで切り替え %s → %s" % (before, after))
    pg.keyboard.press("Escape")

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
    cx.mob = mob


AUTO_REC_A, AUTO_REC_B = "20261007-100000", "20261007-110000"   # ライブの録画(スタジオの配信の id = 録画の id)
# 画面から取り込んだスタジオの API を呼ぶ(合言葉はホームと同じ。-> [HTTP の番号, JSON])
STUDIO_CALL = """async ([method, path, body]) => {
  const t = document.querySelector('meta[name="ytt-token"]').content;
  const r = await fetch('/studio' + path, {method, cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-YTT-Token': t},
                                           body: body == null ? undefined : JSON.stringify(body)});
  return [r.status, await r.json().catch(() => ({}))];
}"""
YTT_PREFS = """async (value) => {
  const t = document.querySelector('meta[name="ytt-token"]').content;
  const r = await fetch('api/ytt/prefs', {method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-YTT-Token': t},
                                         body: JSON.stringify({op: 'patch', section: 'intake', value})});
  return r.status;
}"""


def _live_clip(out_dir, name, origin, video=None, **live):
    """ライブの書き出し(src/pipeline/export/live_export.py の _finish)と同じ形の .clip.json を 作業用 に置いた切り抜き(動画の中身は要らない。
    video = 写す本物の動画(続けて確認で再生するとき))"""
    media = os.path.join(out_dir, "e2e ライブ", name)
    os.makedirs(os.path.dirname(media), exist_ok=True)
    if video:
        shutil.copyfile(video, media)
    else:
        with open(media, "wb") as f:
            f.write(b"x")
    clip = schemas.build_clip(media, 30.0, {"kind": "youtube", "videoId": "", "title": "e2e ライブ"}, (10.0, 40.0),
                              {"id": "lm-x", "label": "", "status": "exported", "src": "manual" if origin == "manual" else "auto"},
                              {"mode": "precise", "fps": "30/1"}, {"name": "ytt-live", "version": "0.1.0"})
    clip["source"] = {"kind": "live", "videoId": "", "url": None, "title": "e2e ライブ", "path": None,
                      "live": dict({"recorder": "local", "recording": "", "markId": "lm-%s" % name[:2], "origin": origin}, **live)}
    os.makedirs(os.path.dirname(schemas.clip_path_for(media)), exist_ok=True)
    with open(schemas.clip_path_for(media), "w", encoding="utf-8") as f:
        json.dump(clip, f, ensure_ascii=False)
    return media


def seed_auto_clips(cx):
    """自動でできた切り抜き(線 D の M9)の見本: 録画 A に自動の切り抜き 2 本(配信中の候補 + パックあり / 配信後の解析 + 控え)、録画 B に人の切り抜き 1 本。
    スタジオには画面と同じ API で登録して書き出し済みにする(スタジオが覚えている配信でないと「要らない」の不採用が通らない)。-> {A の 1 本目・2 本目・B の動画}"""
    check, pg = cx.check, cx.pg
    out_dir = pg.evaluate("fetch('/studio/api/state', {cache: 'no-store'}).then(r => r.json()).then(j => j.outDir)")
    clips = {"a1": _live_clip(out_dir, "01_自動.mp4", "auto", recording=AUTO_REC_A), "a2": _live_clip(out_dir, "02_解析.mp4", "archive", recording=AUTO_REC_A, bench=True),
             "b1": _live_clip(out_dir, "03_人.mp4", "manual", recording=AUTO_REC_B)}
    pack = os.path.join(os.path.dirname(clips["a1"]), "01_自動_pack")   # cut2resolve が作ったパック(以前の形: 中の cut-plan.json)
    os.makedirs(pack, exist_ok=True)
    with open(os.path.join(pack, "cut-plan.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": schemas.CUT_PLAN_SCHEMA, "tool": {"name": "cut2resolve"}}, f)
    for rec, keys in ((AUTO_REC_A, ("a1", "a2")), (AUTO_REC_B, ("b1",))):
        st, _v = pg.evaluate(STUDIO_CALL, ["POST", "/api/videos/open", {"kind": "live", "recorder": "local", "recording": rec,
                                                                         "url": "https://www.youtube.com/watch?v=e2eLiveAAAA", "title": "e2e ライブ " + rec[-6:]}])
        st2, v = pg.evaluate(STUDIO_CALL, ["GET", "/api/video?id=" + rec, None])
        marks = [{"start": 10.0 + 60 * i, "end": 40.0 + 60 * i, "label": "", "status": "adopted"} for i in range(len(keys))]
        st3, v = pg.evaluate(STUDIO_CALL, ["PUT", "/api/video", {"id": rec, "marks": marks, "baseRev": v["video"]["rev"]}])
        got = sorted(v.get("video", {}).get("marks") or [], key=lambda m: m["start"])
        ok = [pg.evaluate(STUDIO_CALL, ["POST", "/api/live/exported", {"id": rec, "markId": m["id"], "path": clips[k]}])[0] for m, k in zip(got, keys)]
        check((st, st2, st3, ok) == (200, 200, 200, [200] * len(keys)), "[A] M9: 見本のライブの録画 %s をスタジオに登録して書き出し済みに: %s" % (rec, (st, st2, st3, ok)))
    return clips


def _mounted_auto_clips(cx):
    """[A] 2j. 自動でできた切り抜きの確認(線 D の M9・M12。入口 0.43.1): 札・絞り込み・未見 → 見た・[採用](パック・届ける先が無いと押せない → 届ける)・
    [要らない](ごみ箱フォルダへ・スタジオのマークを不採用・誤検出の記録)"""
    check, pg = cx.check, cx.pg
    clips = seed_auto_clips(cx)
    pg.reload()
    check(wait_js(pg, "!document.getElementById('autoFilter').hidden && document.getElementById('autoFilter').textContent === '自動の切り抜き: 未確認 2 件'", 15000),
          "[A] M9: 一覧の上に「自動の切り抜き: 未確認 2 件」: %s" % pg.text_content("#autoFilter"))
    check(pg.text_content("#case-%s .pt-case-autopill" % AUTO_REC_A) == "自動 未確認 2本" and pg.is_hidden("#case-%s .pt-case-autopill" % AUTO_REC_B),
          "[A] M9: 閉じた行にも「自動 未確認 n本」(人の切り抜きだけの配信には出さない)")
    pg.click("#autoFilter")
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 1 && !!document.getElementById('case-%s') && document.getElementById('case-%s').open"
                      " && document.getElementById('autoFilter').getAttribute('aria-pressed') === 'true'" % (AUTO_REC_A, AUTO_REC_A), 10000),
          "[A] M9: 絞り込むと未確認がある配信だけ・行を開く: %s" % pg.evaluate("[...document.querySelectorAll('#list .pt-case')].map(n => n.dataset.id)"))
    row = "#case-%s .pt-ac" % AUTO_REC_A
    texts = pg.eval_on_selector_all(row, "els => els.map(e => e.querySelector('.row').textContent)")
    check(len(texts) == 2 and "自動" in texts[0] and "配信中の候補" in texts[0] and "未見" in texts[0] and "配信後の解析" in texts[1] and "控え" in texts[1],
          "[A] M9: 自動の札・出どころ・未見・控え: %s" % texts)
    sizes = pg.evaluate("[...document.querySelectorAll('#autoFilter, %s .pt-ac-deliver, %s .pt-ac-discard')].map(b => Math.round(b.getBoundingClientRect().height))" % (row, row))
    check(len(sizes) == 5 and min(sizes) >= 28, "[A] M9: 絞り込み・採用・要らない は 28px 以上: %s" % sizes)
    if cx.shots:
        pg.screenshot(path=os.path.join(cx.shots, "portal-auto-clips.png"), full_page=True)
    # 届ける先(依頼の受付の Dropbox のフォルダ)が無い・パックが無いときは押せず、理由を出す
    check(wait_js(pg, "(() => { const b = document.querySelectorAll('%s .pt-ac-deliver'); return b.length === 2 && b[0].disabled && b[1].disabled"
                      " && document.querySelectorAll('%s .pt-ac-msg')[0].textContent.indexOf('届ける先が決まっていません') >= 0; })()" % (row, row), 15000)
          and "パックがまだありません" in pg.eval_on_selector_all(row + " .pt-ac-msg", "els => els[1].textContent"),
          "[A] M12: パックが無い・届ける先が無いと「採用」は押せず、理由を出す: %s" % pg.eval_on_selector_all(row + " .pt-ac-msg", "els => els.map(e => e.textContent)"))
    # 「編集で開く」で開いたら「見た」(開くのは止めない = 送るだけ。ここは移らないように中クリックの合図だけを送る)
    pg.evaluate("document.querySelector('%s a').dispatchEvent(new MouseEvent('auxclick', {button: 1}))" % row)
    time.sleep(0.5)
    pg.click("#btnReload")
    check(wait_js(pg, "document.getElementById('autoFilter').textContent === '自動の切り抜き: 未確認 1 件' && !!document.querySelector('%s .pt-ac-seen')" % row, 10000),
          "[A] M9: 開いたら「見た」になり、未確認が 1 件に: %s" % pg.text_content("#autoFilter"))
    _auto_deliver(cx, row)
    _auto_discard(cx, row, clips)
    _auto_review(cx)
    pg.evaluate("document.getElementById('advancedBox').open = true")   # あとの「すべて終了」のため(読み込み直すと閉じる)


def _auto_deliver(cx, row):
    """M12: 届ける先を決めると押せる → 二度押しで zip を Dropbox の 出力 へ → 「届けた」・live_feedback.jsonl に人の「良い」"""
    check, pg = cx.check, cx.pg
    box = os.path.join(cx.tmp, "Dropbox")
    os.makedirs(box, exist_ok=True)
    check(pg.evaluate(YTT_PREFS, {"folder": box}) == 200, "[A] M12: 依頼の受付の Dropbox のフォルダを決めた")
    check(wait_js(pg, "(() => { const b = document.querySelector('%s .pt-ac-deliver'); return b && !b.disabled; })()" % row, 20000),
          "[A] M12: 届ける先が決まると「採用」が押せる(パックのある 1 本目だけ): %s" % pg.eval_on_selector_all(row + " .pt-ac-deliver", "els => els.map(e => e.disabled)"))
    check(pg.eval_on_selector_all(row + " .pt-ac-deliver", "els => els[1].disabled"), "[A] M12: パックの無い 2 本目は押せないまま")
    btn = row + " .pt-ac-deliver"
    pg.click(btn)
    check(pg.text_content(btn) == "もう一度押すと届けます", "[A] M12: 1 回目は確認だけ(UIKit.confirmTwice): %s" % pg.text_content(btn))
    pg.click(btn)
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('友人へ届けました') >= 0)", 20000), "[A] M12: 届けたと知らせる")
    out = os.path.join(box, "出力")
    zips = os.listdir(out) if os.path.isdir(out) else []
    check(len(zips) == 1 and zips[0].endswith("__01_自動.zip"), "[A] M12: zip が Dropbox の 出力 に置かれた: %s" % zips)
    check(wait_js(pg, "!!document.querySelector('%s .pt-ac-done') && document.querySelectorAll('%s .pt-ac-deliver').length === 1" % (row, row), 10000),
          "[A] M12: 届けた切り抜きは「届けた」の札になり、「採用」は消える(二度は届けない)")
    fb = _live_feedback(cx)
    check([(x.get("event"), x.get("origin"), x.get("human"), x.get("verdict")) for x in fb] == [("deliver", "auto", True, "good")],
          "[A] M12: live_feedback.jsonl に人の「良い」(event deliver): %s" % fb)


def _auto_discard(cx, row, clips):
    """M9: 要らない = 二度押しで ごみ箱フォルダへ・スタジオのマークを不採用・誤検出の記録 → 未確認が 0 になると絞り込みが空 → 全部に戻す"""
    check, pg = cx.check, cx.pg
    btn = "#case-%s .pt-ac:nth-child(2) .pt-ac-discard" % AUTO_REC_A
    pg.click(btn)
    check(pg.text_content(btn) == "もう一度押すとごみ箱へ", "[A] M9: 要らない も二度押し: %s" % pg.text_content(btn))
    pg.click(btn)
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('ごみ箱フォルダへ移して') >= 0)", 15000), "[A] M9: 片付けたと知らせる")
    check(not os.path.exists(clips["a2"]) and not os.path.exists(schemas.clip_path_for(clips["a2"])) and os.path.isfile(clips["a1"]),
          "[A] M9: 要らない にした切り抜きの動画と .clip.json だけが動いた")
    _st, v = pg.evaluate(STUDIO_CALL, ["GET", "/api/video?id=" + AUTO_REC_A, None])
    check(sorted(m["status"] for m in v["video"]["marks"]) == ["exported", "rejected"], "[A] M9: スタジオのマークは不採用: %s" % [m["status"] for m in v["video"]["marks"]])
    fb = _live_feedback(cx)
    check([(x.get("event"), x.get("origin"), x.get("human"), x.get("verdict")) for x in fb][-1:] == [("reject", "archive", True, "bad")],
          "[A] M9: live_feedback.jsonl に誤検出(event reject・人の「悪い」): %s" % fb[-1:])
    check(wait_js(pg, "document.getElementById('autoFilter').textContent === '自動の切り抜き: 未確認 0 件' && !document.getElementById('case-%s')"
                      " && document.querySelector('#list .pt-empty b').textContent === '未確認の自動の切り抜きはありません'"
                      " && document.activeElement === document.getElementById('autoFilter')" % AUTO_REC_A, 10000),
          "[A] M9: 未確認が無くなると絞り込みは空の表示・フォーカスは絞り込みのボタンへ: %s / %s"
          % (pg.text_content("#autoFilter"), pg.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.className)")))
    pg.click("#list .pt-empty button")
    check(wait_js(pg, "document.getElementById('autoFilter').getAttribute('aria-pressed') === 'false' && !!document.getElementById('case-%s')"
                      " && document.querySelector('#case-%s .pt-case-autopill').textContent === '自動 1本'" % (AUTO_REC_A, AUTO_REC_A), 10000),
          "[A] M9: 「全部の配信に戻す」で戻る(届けた 1 本は 自動 1本)")


AUTO_REC_C = "20261007-120000"   # 続けて確認(A5)の見本の録画
REVIEW_CAP = "続けて確認の字幕"


def seed_review_clips(cx):
    """続けて確認(A5)の見本: 録画 C に本物の webm の自動の切り抜き 2 本(1 本目はパックと字幕の文書つき・2 本目は文書だけ)。-> [動画 2 本]"""
    check, pg = cx.check, cx.pg
    src = os.path.join(cx.tmp, "review-src.mp4")   # スタジオは .mp4 だけ受け付ける。chromium は H.264 を再生できないので VP9 + Opus の mp4
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libvpx-vp9",
                    "-deadline", "realtime", "-cpu-used", "8", "-b:v", "200k", "-c:a", "libopus", src], check=True, timeout=120)
    out_dir = pg.evaluate("fetch('/studio/api/state', {cache: 'no-store'}).then(r => r.json()).then(j => j.outDir)")
    vids = [_live_clip(out_dir, "1%d_続け.mp4" % i, "auto", video=src, recording=AUTO_REC_C) for i in (1, 2)]
    pack = os.path.join(os.path.dirname(vids[0]), "11_続け_pack")
    os.makedirs(pack, exist_ok=True)
    with open(os.path.join(pack, "cut-plan.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": schemas.CUT_PLAN_SCHEMA, "tool": {"name": "cut2resolve"}}, f)
    tx = os.path.join(cx.tmp, layout.TOOL_DIRS["transcribe"], "transcripts")
    os.makedirs(tx, exist_ok=True)
    for i, v in enumerate(vids):
        tid = "beefcafe%04d" % (i + 1)
        segs = [{"id": "s1", "start": 0.0, "end": 5.5, "text": REVIEW_CAP}] if i == 0 else []
        with open(os.path.join(tx, tid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": tid, "title": "続け %d" % (i + 1), "sourcePath": v, "updatedAt": 1, "segments": segs}, f, ensure_ascii=False)
    st, _v = pg.evaluate(STUDIO_CALL, ["POST", "/api/videos/open", {"kind": "live", "recorder": "local", "recording": AUTO_REC_C,
                                                                     "url": "https://www.youtube.com/watch?v=e2eLiveCCCC", "title": "e2e 続けて確認"}])
    _st2, v = pg.evaluate(STUDIO_CALL, ["GET", "/api/video?id=" + AUTO_REC_C, None])
    marks = [{"start": 10.0 + 60 * i, "end": 16.0 + 60 * i, "label": "", "status": "adopted"} for i in range(2)]
    _st3, v = pg.evaluate(STUDIO_CALL, ["PUT", "/api/video", {"id": AUTO_REC_C, "marks": marks, "baseRev": v["video"]["rev"]}])
    got = sorted(v.get("video", {}).get("marks") or [], key=lambda m: m["start"])
    ok = [pg.evaluate(STUDIO_CALL, ["POST", "/api/live/exported", {"id": AUTO_REC_C, "markId": m["id"], "path": p}])[0] for m, p in zip(got, vids)]
    check(st == 200 and ok == [200, 200], "[A] A5: 見本の録画 C を登録して書き出し済みに: %s %s" % (st, ok))
    return vids


def _auto_review(cx):
    """[A] 2k. 続けて確認(A5。ホーム 0.51.0): 一覧の上のボタン → 引き出しで再生・字幕 → A を 2 回で届ける → 次へ進む → X を 2 回で要らない
    (再生していた動画を外してからごみ箱へ = Windows でもファイルを移せる)→ 残っていない表示 → Esc で閉じてフォーカスは一覧の欄へ"""
    check, pg = cx.check, cx.pg
    vids = seed_review_clips(cx)
    pg.reload()
    check(wait_js(pg, "!document.getElementById('autoReview').hidden && document.getElementById('autoReview').textContent === '続けて確認 2 本'", 15000),
          "[A] A5: まだ届けていない自動の切り抜きの数(届けた・要らないは数えない): %s" % pg.text_content("#autoReview"))
    pg.click("#autoReview")
    check(wait_js(pg, "!document.getElementById('rvDrawer').hidden && document.getElementById('rvCount').textContent === '1 / 2 本'"
                      " && document.getElementById('rvVideo').getAttribute('src').indexOf('/transcribe/media?id=beefcafe0001') === 0", 10000),
          "[A] A5: 引き出しが開き、1 本目の動画(編集の /transcribe/media): %s" % pg.evaluate("document.getElementById('rvVideo').getAttribute('src')"))
    check(wait_js(pg, "(() => { const v = document.getElementById('rvVideo'); return !v.paused && v.currentTime > 0.3; })()", 15000),
          "[A] A5: 開いたらすぐ再生: %s" % pg.evaluate("(() => { const v = document.getElementById('rvVideo'); return [v.paused, v.currentTime, v.readyState, v.error && v.error.code]; })()"))
    check(wait_js(pg, "document.getElementById('rvCap').textContent === '%s'" % REVIEW_CAP, 10000), "[A] A5: 文書の行を字幕に出す: %s" % pg.text_content("#rvCap"))
    check(pg.evaluate("document.getElementById('rvDrawer').contains(document.activeElement)"), "[A] A5: フォーカスは引き出しの中")
    if cx.shots:
        pg.screenshot(path=os.path.join(cx.shots, "portal-auto-review.png"))
    pg.keyboard.press("a")
    check(pg.text_content("#rvDeliver") == "もう一度押すと届けます(A)", "[A] A5: A の 1 回目は確認だけ: %s" % pg.text_content("#rvDeliver"))
    pg.keyboard.press("a")
    check(wait_js(pg, "document.getElementById('rvCount').textContent === '2 / 2 本'"
                      " && document.getElementById('rvVideo').getAttribute('src').indexOf('beefcafe0002') >= 0", 10000),
          "[A] A5: 届けると、すぐ次の切り抜きへ: %s" % pg.text_content("#rvCount"))
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('友人へ届けました') >= 0)", 20000), "[A] A5: 裏で届けて知らせる")
    check(wait_js(pg, "(() => { const v = document.getElementById('rvVideo'); return !v.paused && v.currentTime > 0.3; })()", 15000), "[A] A5: 次の切り抜きも続けて再生")
    pg.keyboard.press("x")
    pg.keyboard.press("x")
    check(wait_js(pg, "!document.getElementById('rvEmpty').hidden && document.getElementById('rvCur').hidden && document.activeElement === document.getElementById('rvDone')", 10000),
          "[A] A5: 全部決めると「残っていません」(フォーカスは閉じるボタン)")
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('ごみ箱フォルダへ移して') >= 0)", 15000),
          "[A] A5: 要らない を片付けたと知らせる")
    check(not os.path.exists(vids[1]) and os.path.isfile(vids[0]),
          "[A] A5: 再生していた動画を外してからごみ箱へ移せた(Windows でも)・届けた動画は残る: %s" % [os.path.exists(v) for v in vids])
    states = pg.eval_on_selector_all("#rvList .pt-rv-st", "els => els.map(e => e.textContent)")
    check(wait_js(pg, "[...document.querySelectorAll('#rvList .pt-rv-st')].map(e => e.textContent).join() === '届けた,要らない'", 10000),
          "[A] A5: 並びの札(届けた・要らない): %s" % states)
    out = os.path.join(cx.tmp, "Dropbox", "出力")
    check(any(z.endswith("__11_続け.zip") for z in os.listdir(out)), "[A] A5: 1 本目の zip を届けた: %s" % os.listdir(out))
    _st, v = pg.evaluate(STUDIO_CALL, ["GET", "/api/video?id=" + AUTO_REC_C, None])
    check(sorted(m["status"] for m in v["video"]["marks"]) == ["exported", "rejected"], "[A] A5: 2 本目のマークは不採用: %s" % [m["status"] for m in v["video"]["marks"]])
    pg.keyboard.press("Escape")
    check(wait_js(pg, "document.getElementById('rvDrawer').hidden && document.getElementById('autoReview').hidden && document.activeElement === document.getElementById('fText')"
                      " && !document.getElementById('rvVideo').getAttribute('src')", 10000),
          "[A] A5: Esc で閉じる・続けて確認のボタンは消え、フォーカスは一覧の欄へ・動画は外す: %s"
          % pg.evaluate("document.activeElement && (document.activeElement.id || document.activeElement.tagName)"))


def _live_feedback(cx):
    p = os.path.join(cx.srv.live.store_dir, "live_feedback.jsonl")
    try:
        with open(p, encoding="utf-8") as f:
            return [json.loads(x) for x in f.read().splitlines() if x.strip()]
    except OSError:
        return []


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
        check(pg.text_content("#btnQuit").startswith("もう一度押すと終了します"), "[B] 1回目は確認だけ(UIKit.confirmTwice): %s" % pg.text_content("#btnQuit"))
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
        from ytt_core import layout as _layout
        _layout.copy_shared_code(tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
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
