#!/usr/bin/env python3
"""ホーム(src/app/ui/home/portal.html)の通し確認(Playwright。本物の3ツールを疑似モードで一時フォルダに写し、空きポートだけを使う)。

    python src/app/tests/e2e_portal.py [--shots <フォルダ>]

2つの形をそれぞれ確かめる:

  (A) 本番と同じ形(python src/app/server.py と同じ mounts=tuple(mount.MOUNTS)): 3つとも入口に取り込み。
      1 2枚のカードが「ホームに取り込み」で動作中・ヘッダーの appnav・「詳しく」の調子(始める条件)と片付け・確かめるの枠([始める] は /check)→
      2 カードの「開く」・/cases の引数なしで前の案件 → 2h 動画のパスで開く /cases?v=(文書の校正か新しい案件の欄)→
      2d 案件(配信ごと)の一覧 → 2e 処理の状況(実行中・待ち・失敗)と行の依頼・2f 単体の文字起こし → 2g 一覧の件数と「もっと見る」→
      2i 行は結果だけ(次の一手のボタンなし)・行を開いて案件の画面へ着く・依頼の受付の外の文字 →
      2j 新しい案件(引き出し・/?url=…#new・探す設定・① 配信を探す・URL から入れて「確認する」で案件の画面の候補へ)と運用の枠の精度と学習 →
      2k 自動でできた切り抜き(採用で届ける・要らない)→ 9 すべて終了(2回押し)→ 10 開いたままの別のタブに切断の表示、を確かめる。
      案件の画面の候補・校正・カットのパネルの中身は e2e_cases_cand・e2e_cases_proof・e2e_cases_cut、確かめる /check の中身は e2e_check が見る
      (ここは着くまで)。細かい操作(一覧の検索・並び替え・非表示・テーマ・狭い画面・空の表示・フォーカス・はみ出し)は画面の道に入れない(ui_audit)。
  (B) 文字起こしが子プロセスの形(--no-mount 相当・取り込めなかったときの落ち先。mounts=("studio", "cut2resolve")):
      文字起こしだけ黒い画面(別プロセス)で動く形で、子プロセスの管理(異常終了の表示・ログの表示と XSS 対策)を
      確かめる(「詳しく」の中)。異常終了のあとの起動し直しは test_launch の test_crash_is_reported_with_log が見る。

--shots で画面の写真を残す(A はホームと自動の切り抜き、B は異常終了。テーマ・幅ごとの写真は ui_audit)。
"""
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

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.append(os.path.dirname(HERE))   # src(app 層。入口本体は src/app/server.py)
from app import server as L  # noqa: E402
from app import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports  # noqa: E402
from ytt import layout, schemas, testkit  # noqa: E402


def wait_js(pg, expr, timeout=30000):
    return testkit.wait_js(pg, expr, timeout)


def card_state(pg, tid):
    return pg.evaluate("id => { const c = document.querySelector('.pt-tool[data-tool=\"' + id + '\"]'); return c && c.getAttribute('data-state'); }", tid)


def wait_card(pg, tid, state, timeout=40000):
    return wait_js(pg, "document.querySelector('.pt-tool[data-tool=\"%s\"]')?.getAttribute('data-state') === '%s'" % (tid, state), timeout)


def open_advanced(pg):
    """「詳しく」を開く(サーバーの管理の操作はクリックできる必要があるため)。既定で閉じていることを確かめてから開く"""
    ok = wait_js(pg, "document.getElementById('advancedBox') && document.getElementById('advancedBox').open === false", 10000)
    pg.evaluate("document.getElementById('opsBox').open = true; document.getElementById('advancedBox').open = true")   # 「詳しく」は運用の枠の中
    return ok


APPNAV_JS = ("[...document.querySelectorAll('[data-ui-appnav-item]')].map(a => [a.getAttribute('data-ui-appnav-item'), a.href,"
             " a.getAttribute('aria-current')])")


def check_appnav(check, pg, base):
    """ヘッダーの appnav(画面どうしで同じ部品。項目と行き先は e2e ではここだけで見る。ほかの画面の e2e は aria-current だけ): ホーム / 案件 / 確かめる / 設定 の 4 つ・行き先は入口の直下(/・/cases・/check・/settings)・
    今の画面(ホーム)の項目だけ aria-current="page"。href は入口の直下からの相対で作る(homeUrl)ので、解決した a.href で比べる"""
    want = [["portal", base], ["cases", base + "cases"], ["check", base + "check"], ["settings", base + "settings"]]
    wait_js(pg, "%s.length === 4" % APPNAV_JS, 10000)
    got = pg.evaluate(APPNAV_JS)
    check([g[:2] for g in got] == want and [g[0] for g in got if g[2] == "page"] == ["portal"],
          "[A] appnav は ホーム / 案件 / 確かめる / 設定 の 4 つ(/・/cases・/check・/settings)で、ホームが aria-current: %s" % got)


CASE_TITLE = "案件の通し確認<b>配信</b>"   # < を含めて、textContent で入れていること(画面を壊さない)も確かめる


def seed_cases(tmp, studio_home):
    """案件の一覧用: 書き出し済みのマーク1つを持つ配信と、その切り抜きの文字起こし(2行のうち1行を校正済み・パックはまだ)を置く"""
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
        json.dump({"id": "deadbeef0001", "title": "案件の字幕", "sourcePath": clip, "updatedAt": 1, "speakers": [],   # 保存した文書には必ずある(校正のパネルが読む)
                   "segments": [{"id": "s1", "start": 0.5, "end": 2.0, "text": "a", "proofed": True}, {"id": "s2", "start": 2.5, "end": 4.0, "text": "b"}]}, f, ensure_ascii=False)


def seed_unlinked(tmp):
    """どの配信にも紐づかない文字起こし(「単体の文字起こし」)"""
    tx = os.path.join(tmp, layout.TOOL_DIRS["transcribe"], "transcripts")
    os.makedirs(tx, exist_ok=True)
    solo = os.path.join(tmp, "solo.mp4")
    with open(os.path.join(tx, "deadbeef0002.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "deadbeef0002", "title": "単体の字幕", "sourcePath": solo, "updatedAt": 2, "speakers": [],
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


TX_VER = STUDIO_VER = "v" + tool_version("ytt/version.py", r'^VERSION = "([^"]+)"')   # 全体の版は 1 つ
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
        _mounted_media_urls(cx)
        _mounted_cases(cx)
        _mounted_todo_and_unlinked(cx)
        _mounted_list_tools(cx)
        _mounted_next_steps(cx)
        _mounted_new_case_and_ops(cx)
        _mounted_second_tab(cx)
        mob = cx.mob   # 8. の別のタブ(10. で使う)
        _mounted_auto_clips(cx)   # スタジオの data.json を書き直すので最後に(前の場面が足した配信はスタジオが知らないので消える)

        # 9. すべて終了(2回押し)。3つとも取り込みなので、この形には子プロセスは無い
        pg.click("#btnQuit")
        check(pg.text_content("#btnQuit").startswith("もう一度押すと終了します"), "[A] 1回目は確認だけ(UIKit.confirmTwice): %s" % pg.text_content("#btnQuit"))
        pg.click("#btnQuit")
        check(wait_js(pg, "!document.getElementById('done').hidden", 5000), "[A] 終了中の表示")
        th.join(30)
        check(not th.is_alive(), "[A] ホームのサーバーが止まった")
        srv.server_close()   # server.main() と同じく、待ち受けを閉じる
        check(wait_js(pg, "document.getElementById('doneTitle').textContent === 'すべて終了しました'", 20000), "[A] 終了の表示")
        sup.unmount_all()   # server.main() の終了処理と同じ(request_shutdown でも呼ばれる)
        check(not any(os.path.exists(os.path.join(sup.rdir, t + ".json")) for t in L.TOOL_IDS), "[A] .runtime が片付いた(3つとも取り込みでも)")

        # 10. ホームが止まったら、開いたままの別のタブに「接続できません」を出す
        check(wait_js(mob, "!document.getElementById('errbar').hidden", 15000), "[A] 切断の表示")

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
    """[A] 1. カード・appnav・1b. 「詳しく」の「調子」(始める条件)・確かめるの枠(/check へ着くまで)・「片付け」・取り込みの表示"""
    check, pg, port, shots = cx.check, cx.pg, cx.port, cx.shots
    # 1. カードは2枚(① 切り抜きスタジオ → ② 編集)。cut2resolve は「編集」の部品として取り込まれて動くが、カードは出さない
    for tid in SHOWN:
        check(wait_card(pg, tid, "running"), "[A] %s が動作中" % tid)
    order = pg.evaluate("[...document.querySelectorAll('.pt-tool')].map(e => e.getAttribute('data-tool'))")
    check(order == ["studio", "transcribe"], "[A] カードは作業の順に2枚(スタジオ → 編集。cut2resolve は出さない): %s" % order)
    check(pg.text_content(".pt-tool[data-tool=transcribe] .pt-name") == "編集", "[A] 文字起こしのカードは「編集」")
    check(pg.text_content("#ver") == "ホーム v" + L.VERSION, "[A] ヘッダーの版: %s" % pg.text_content("#ver"))
    check(pg.is_hidden("#conn") and pg.text_content("#conn") == "接続済み", "[A] つながったあとは「接続」の札を出さない(切れたときだけ「切断」): %s" % pg.text_content("#conn"))
    check_appnav(check, pg, cx.base)

    # 1b. 「詳しく」は既定で閉じている。テストのため開く(サーバーの管理の操作をクリックできるように)
    check(open_advanced(pg), "[A] 「詳しく」は既定で閉じている")
    # 「調子」(版・認識ワーカー・外部プログラム・空き容量・作業データ・エラーの件数)が「詳しく」の先頭に出る
    check(wait_js(pg, "[...document.querySelectorAll('#healthList > li')].length >= 6", 20000), "[A] 「調子」が出る(6 項目以上): %d" % pg.locator("#healthList > li").count())
    check(wait_js(pg, "document.querySelector('#healthList').textContent.indexOf('作業データ ') >= 0 && document.querySelector('#healthList').textContent.indexOf('数えています') < 0", 20000), "[A] 作業データの大きさは別のスレッドで数えて、終わったら出る")
    # 入口の条件(あと何本・何分)。前回の測定の記録から「今 / 目標 / あと」を 1 行ずつ・無いものは「未測定」
    check(wait_js(pg, "!!document.getElementById('accuracyGoals')", 20000), "[A] 調子に「始める条件(あと何本・何分)」が出る")
    gt = pg.text_content("#accuracyGoals") if pg.query_selector("#accuracyGoals") else ""   # 畳んだ欄の中なので text_content
    check("始める条件(あと何本・何分)" in gt and "定点 15 分: 今 15.8 分 / 目標 15 分 / 届いた" in gt and "定点 30 分: 今 15.8 分 / 目標 30 分 / あと 14.2 分" in gt and "G1" not in gt and "G2" not in gt
          and "学習用の校正 3 時間: 今 0.17 時間 / 目標 3 時間 / あと 2.83 時間" in gt and "確かめ済みの話者の行 200: 今 120 行 / 目標 200 行 / あと 80 行" in gt
          and "採用の記録 配信 10 本: 未測定" in gt and "届いた 1 / 10・未測定 5" in gt,
          "[A] 入口の条件: 今 / 目標 / あと と 未測定: %s" % " / ".join(gt.split("\n"))[:600])
    # 確かめるの枠 = 今いちばん効く確認 1 つ(入口の GET api/check/next?n=0 の goal。この見本では時刻の確認が未測定) + 届いた n / m。[始める] は /check へ
    cn = pg.text_content("#checkNow")
    check("行の時刻の判定" in cn and "まだ測っていません" in cn and "G1" not in cn and "届いた 1 / 10" in pg.text_content("#checkSub"),
          "[A] 確かめる: 今いちばん効く確認(入口の next の goal)と届いた数: %s / %s" % (cn, pg.text_content("#checkSub")))
    check(not pg.evaluate("document.getElementById('checkStart').disabled") and pg.evaluate("new URL(document.getElementById('checkStart').href).pathname") == "/check",
          "[A] 確かめる: [始める] は /check へのリンク")
    pg.click("#btnHealthRefresh")
    check(wait_js(pg, "document.querySelector('#healthWhen').textContent.indexOf('数えた') >= 0", 20000), "[A] 「数え直す」で数え直して、いつ数えたかが出る: %s" % pg.text_content("#healthWhen"))
    # 「片付け」の節。候補を探すと種類ごと(6 種類)に出て、何も選ばなければ移せない
    pg.click("#btnCleanFind")
    check(wait_js(pg, "document.querySelectorAll('#cleanKinds details').length === 6", 20000), "[A] 「片付け」の候補が種類ごとに出る: %d" % pg.locator("#cleanKinds details").count())
    check(pg.is_disabled("#btnCleanMove") and "候補" in pg.text_content("#cleanWhen"), "[A] 何も選んでいなければ「ごみ箱フォルダへ移す」は押せない")

    for tid, verfrag in (("studio", STUDIO_VER), ("transcribe", TX_VER)):
        meta = pg.text_content(".pt-tool[data-tool=%s] .pt-meta" % tid)
        good = ("ポート %d" % port) in meta and "ホームに取り込み" in meta and (verfrag is None or verfrag in meta)
        check(good, "[A] %s はホームに取り込み(同じポート): %s" % (tid, meta))

    if shots:
        os.makedirs(shots, exist_ok=True)
        pg.screenshot(path=os.path.join(shots, "portal.png"), full_page=True)


def _mounted_open_tools(cx):
    """[A] 2. ツールのカードの「開く」・2b. /cases(引数なし)は前に開いた案件。
    候補・校正・カットのパネルの中身は e2e_cases_cand・e2e_cases_proof・e2e_cases_cut(d だけの URL を c つきに直す・#cut も)"""
    base, check, ctx, pg, port = cx.base, cx.check, cx.ctx, cx.pg, cx.port
    # 2. 開く: 新しいタブで同じアドレスの画面が開く(noopener)。カードの「開く」は
    # その仕事をする画面(スタジオ = /#new・編集 = /cases)を指す。行き先の中身は下の案件の画面で確かめる
    for tid in SHOWN:
        href = pg.get_attribute(".pt-tool[data-tool=%s] .pt-open" % tid, "href") or ""
        check(href.startswith("http://127.0.0.1:%d/" % port), "[A] %s の「開く」は同じアドレス: %s" % (tid, href))
    with ctx.expect_page() as info:
        pg.click(".pt-tool[data-tool=studio] .pt-open")
    tab = info.value
    tab.wait_for_load_state()
    check(tab.url.startswith(base) and tab.evaluate("location.pathname") in ("/", "/cases"),
          "[A] カードの「開く」は同じアドレスの画面に着く(スタジオは新しい案件 /#new): %s" % tab.url)
    check(tab.evaluate("window.opener") is None, "[A] 開いたタブからホームを操作できない(noopener)")
    tab.close()

    # 2b. 引数なし(ヘッダーの「案件」)は、このブラウザで前に開いた案件を開く
    tab = ctx.new_page()
    tab.on("pageerror", lambda e: cx.errors.append(str(e)))
    tab.goto(base + "cases?c=e2eCase0001#cand")
    check(wait_js(tab, "typeof CasesShell === 'object' && CasesShell.state().caseId === 'e2eCase0001' && CasesShell.state().tab === 'cand'"
                       " && localStorage.getItem('ytt-cases-last') === 'e2eCase0001'", 20000),
          "[A] /cases?c=…#cand でその配信の候補が開く(開いた案件を覚える): %s" % tab.url)
    tab.goto(base + "cases")
    check(wait_js(tab, "typeof CasesShell === 'object' && CasesShell.state().caseId === 'e2eCase0001'", 20000),
          "[A] /cases(引数なし)は前に開いた案件を開く: %s" % tab.evaluate("typeof CasesShell === 'object' && CasesShell.state()"))
    tab.close()


def _mounted_media_urls(cx):
    """[A] 2h. 動画のパスで案件の画面を開く(/cases?v=<動画のパス>。スタジオ ② の「編集で開く」)。
    文書のある動画はその文書の校正・文書の無い動画はホームの新しい案件の欄"""
    base, check, ctx = cx.base, cx.check, cx.ctx
    q = lambda s: urllib.parse.quote(s, safe="")
    missing = "C:\\x\\無い動画.mp4"
    clip = os.path.join(cx.tmp, "exports", "01_案件.mp4")   # seed_cases の文書 deadbeef0001 の元の動画
    tab = ctx.new_page()
    tab.on("pageerror", lambda e: cx.errors.append(str(e)))
    tab.goto(base + "cases?v=" + q(clip) + "#proof")
    check(wait_js(tab, "typeof CasesShell === 'object' && CasesShell.state().caseId === 'e2eCase0001' && CasesShell.state().tab === 'proof'"
                       " && CasesShell.state().sel === 'd:deadbeef0001' && location.search + location.hash === '?c=e2eCase0001&d=deadbeef0001#proof'", 30000),
          "[A] /cases?v=<文書のある動画>#proof はその文書の校正を開き、URL を ?c=&d= に直す: %s"
          % tab.evaluate("[typeof CasesShell === 'object' && CasesShell.state(), location.search + location.hash]"))
    tab.goto(base + "cases?v=" + q(missing) + "#proof")
    check(wait_js(tab, "location.pathname === '/' && location.hash.indexOf('#new?media=') === 0 && !document.getElementById('newDrawer').hidden"
                       " && !!document.getElementById('qPath') && document.getElementById('qPath').value.endsWith('無い動画.mp4')", 25000),
          "[A] /cases?v=<文書の無い動画> はホームの新しい案件の引き出しを開き、動画のパスが欄に入る: %s" % tab.url)
    tab.close()


def _mounted_cases(cx):
    """[A] 2d. 案件の一覧(配信 1 本 = 1 行・開くと切り抜き・まとめて実行)・2d-2. 保存していない配信者の入力は離れて戻っても残る"""
    check, pg = cx.check, cx.pg
    # 2d. 案件(配信ごと)の一覧はホーム(/)。スタジオ・文字起こしのデータから紐づけを組み立てる
    check(wait_js(pg, "document.querySelectorAll('.pt-case').length === 1", 15000), "[A] 案件の一覧に配信が1本出た")
    check(pg.text_content(".pt-case-title") == CASE_TITLE, "[A] 案件のタイトル: %s" % pg.text_content(".pt-case-title"))
    check(pg.evaluate("document.querySelector('.pt-case').open") is False, "[A] 行は既定で閉じている(1件1行。開くまで中身を描かない分だけ軽い)")
    pills = pg.eval_on_selector_all(".pt-clip .pill", "els => els.map(e => e.textContent)")
    check(any(t.startswith("文字起こし") for t in pills) and any(t.startswith("パック") for t in pills), "[A] 閉じていても中身は組み立ててある(文字起こしとパックの札): %s" % pills)
    pg.click(".pt-case .pt-case-row")
    check(wait_js(pg, "document.querySelector('.pt-case').open === true", 5000), "[A] 行を開くと切り抜き・まとめて実行が出る")
    acts = pg.eval_on_selector_all(".pt-clip a", "els => els.map(a => [a.textContent, a.getAttribute('href')])")
    check(any(t == "校正で開く" and h.startswith("/cases?c=e2eCase0001&d=") and h.endswith("#proof") for t, h in acts),
          "[A] 切り抜きの操作は「校正で開く」(案件の画面へ。同じ動画の別の文書が開かないように文書 ID で校正のタブ): %s" % acts)
    case_doc = [h for t, h in acts if t == "校正で開く" and "e2eCase0001" in h][0].split("&d=")[1].split("#")[0]
    # 案件の行から、その配信を案件の画面の候補で開く(押して同じタブで移るのは 2i の「校正 1本」のボタンで見る)
    sh = pg.eval_on_selector_all(".pt-case-studio a", "els => els.map(a => [a.textContent, a.getAttribute('href'), a.getAttribute('target')])")
    check(sh == [["案件の画面で開く", "/cases?c=e2eCase0001#cand", None]],
          "[A] 案件の行に「案件の画面で開く」(/cases?c= に案件の id・同じ窓で移る): %s" % sh)
    # 2d-2. 保存していない配信者の入力(まとめて実行の欄)は、alt-tab で離れて戻ったとき(UIKit.life の blur→focus → refreshCases)の
    # 再描画でも消えない。blur→focus は document.hasFocus を差し替えて window の blur・focus を送る(UIKit.life の blurTimer より長く待つ)
    if not pg.evaluate("document.querySelector('.pt-case').open"):
        pg.click(".pt-case .pt-case-row")
    check(wait_js(pg, "document.querySelector('.pt-case').open === true", 5000), "[A] 下書きを試すため行を開く")
    draft = "書きかけの配信者"
    pg.fill(".pt-case .pt-auto-streamer", draft)   # 実行は押さない(保存していない入力のまま)
    pg.evaluate("document.querySelector('.pt-case .pt-auto-streamer').focus()")
    pg.evaluate("() => { document.hasFocus = () => false; window.dispatchEvent(new Event('blur')); }")
    time.sleep(0.4)   # UIKit.life の blurTimer(150ms)より長く待つ
    pg.evaluate("() => { document.hasFocus = () => true; window.dispatchEvent(new Event('focus')); }")
    check(wait_js(pg, "document.querySelector('.pt-case') && document.querySelector('.pt-case').open === true", 10000),
          "[A] 離れて戻った再描画のあとも行は開いたまま")
    check(wait_js(pg, "document.querySelector('.pt-case .pt-auto-streamer') && document.querySelector('.pt-case .pt-auto-streamer').value === %s" % json.dumps(draft), 10000),
          "[A] 保存していない配信者の入力が、戻ったときの再描画(refreshCases)でも消えない: %s"
          % pg.evaluate("document.querySelector('.pt-case .pt-auto-streamer') && document.querySelector('.pt-case .pt-auto-streamer').value"))
    check(pg.evaluate("document.activeElement === document.querySelector('.pt-case .pt-auto-streamer')"),
          "[A] フォーカスも(再描画で作り直された)配信者の欄に戻る")
    pg.fill(".pt-case .pt-auto-streamer", "")   # 後の確認のため空に戻す
    # 下書きは、作り直す前の欄の change で配信(e2eCase0001)とチャンネル(ch)に覚えられている(UIKit.streamer の「手で直したら覚える」)。
    # 空(色なし)を覚え直さないと、あとの場面で自動で入る名前が下書きになり、「見つからない名前」の確かめが出て実行が止まる。
    # 作り直した欄は下書きから値を入れるだけで覚える配線が無いので、欄の change ではなくホームの設定へ直接送る
    st = pg.evaluate("Promise.all([UIKit.prefs.remember('videos', 'e2eCase0001', ''), UIKit.prefs.remember('channels', 'ch', '')]).then(r => r[1])")
    check(st and st.get("videos", {}).get("e2eCase0001") == "" and st.get("channels", {}).get("ch") == "",
          "[A] あとの場面のため、配信者の記憶を空(色なし)に戻した: %s" % st)
    cx.case_doc = case_doc


def _status_runs(now):
    """2e 用のまとめて実行の偽の答え(GET api/flow/runs): 友人の依頼の実行中・自分の待ち・前回の起動の失敗"""
    def step(label, st):
        return {"label": label, "state": st}
    run = {"id": "e2erunA", "kind": "video", "videoId": "e2eCase0001", "docId": None, "title": "案件の通し確認", "mode": "full", "modeLabel": "解析から全部",
           "requestId": "20261019-100000-abc123", "state": "running", "created": now - 60000, "finished": None, "error": None,
           "steps": [step("解析", "done"), step("文字起こし", "run"), step("パック", "wait")]}
    wait = dict(run, id="e2erunB", videoId="e2eWait0001", title="待ちの配信", requestId=None, state="queued", created=now - 30000,
                steps=[step("解析", "wait"), step("文字起こし", "wait"), step("パック", "wait")])
    fail = {"id": "e2erunC", "kind": "video", "videoId": "e2eFail0001", "title": "失敗の配信", "mode": "full", "modeLabel": "解析から全部", "state": "error",
            "error": "動画が見つかりません", "created": now - 7200000, "finished": now - 3600000,
            "steps": [step("解析", "done"), step("書き出し", "error"), step("文字起こし", "wait")]}
    return {"runs": [run, wait], "past": [fail]}


def _mounted_todo_and_unlinked(cx):
    """[A] 2e. 処理の状況と行の依頼・2f. 単体の文字起こし"""
    check, ctx, pg = cx.check, cx.ctx, cx.pg
    # 2e. 処理の状況: まとめて実行の実行中(今の段・全体)・待ち・失敗だけ。採用・校正・パックの残りは出さない。まとめて実行の答えは偽物(別のタブ)
    p = ctx.new_page()
    p.on("pageerror", lambda e: cx.errors.append(str(e)))
    p.route("**/api/flow/runs", lambda route: route.fulfill(json=_status_runs(int(time.time() * 1000))))
    p.goto(cx.base)
    check(wait_js(p, "document.querySelectorAll('#todoList .pt-todo-item').length >= 3", 15000) and p.text_content("#todoBox h2") == "処理の状況",
          "[A] 処理の状況に項目が出た: %s" % p.text_content("#todoBox"))
    rows = p.eval_on_selector_all("#todoList .pt-todo-item", "els => els.map(e => [e.querySelector('.pt-todo-pill').textContent, "
                                  "e.querySelector('.pt-todo-title').textContent, e.querySelector('.pt-todo-sub').textContent, e.querySelector('.pt-todo-link').getAttribute('href')])")
    check([r[0] for r in rows[:3]] == ["実行中", "待ち", "失敗"] and all(r[0] in ("実行中", "待ち", "失敗") for r in rows),
          "[A] 並びは実行中 → 待ち → 失敗で、採用待ち・校正待ち・パック待ちは出ない: %s" % rows)
    check("友人の依頼" in rows[0][2] and "今: 文字起こし(2/3 段)" in rows[0][2] and "全体 33%" in rows[0][2] and rows[0][3] == "#case-e2eCase0001",
          "[A] 実行中は誰の依頼か・今の段・全体の進み。押すと案件の行へ: %s" % rows[0])
    check("自分" in rows[1][2] and "1 番目" in rows[1][2], "[A] 待ちは順番: %s" % rows[1])
    check("書き出しで失敗: 動画が見つかりません" in rows[2][2], "[A] 失敗は段と理由(前回の起動の結果も): %s" % rows[2])
    check(wait_js(p, "(document.querySelector('#case-e2eCase0001 .pt-case-sub') || {}).textContent.indexOf('友人の依頼 ・ 解析から全部') >= 0", 10000)
          and p.evaluate("document.getElementById('case-e2eCase0001').open") is False,
          "[A] 行の 2 行目に依頼の内容。実行中でも行は勝手に開かない: %s" % p.text_content("#case-e2eCase0001 .pt-case-sub"))
    p.close()

    # 2f. 単体の文字起こし(どの配信にも紐づかない文字起こし)。「編集」の文書の一覧と突き合わせて詳しく見せる
    check(wait_js(pg, "!document.getElementById('unlinkedGroup').hidden && !document.getElementById('unlinkedHead').hidden", 10000), "[A] 単体の文字起こしの1行とまとまりが出た")
    check(pg.text_content("#unlinkedCount").strip() == "1件", "[A] 単体の文字起こしの件数(ホームの数): %s" % pg.text_content("#unlinkedCount"))
    link = pg.get_attribute("#unlinkedOpen", "href")
    check(link == "/cases?c=orphan#proof", "[A] 「案件の画面で見る」は仮の案件「どの案件にも入らない文字起こし」を開く: %s" % link)
    check(pg.evaluate("document.getElementById('unlinkedGroup').open") is False, "[A] 単体の文字起こしのまとまりは既定で閉じている")
    pg.click("#unlinkedGroup summary")
    check(wait_js(pg, "!!document.querySelector('.pt-doc')", 10000), "[A] 単体の文字起こしの行が出た")
    docTx = pg.text_content(".pt-doc-tx")
    check("校正" in docTx and "パック" in docTx, "[A] 単体の文字起こしも校正・パックの進み具合を見せる: %s" % docTx)
    open_href = pg.get_attribute(".pt-doc-open", "href")
    check(bool(open_href) and open_href.startswith("/cases?d=") and open_href.endswith("#proof"), "[A] 単体の文字起こしも「校正で開く」(案件の画面へ文書 ID で): %s" % open_href)
    pg.check(".pt-doc-check")
    check(wait_js(pg, "!document.getElementById('docRunBtn').disabled", 5000), "[A] 選ぶと「まとめて実行」が押せる")
    pg.uncheck(".pt-doc-check")
    check(pg.is_disabled("#docRunBtn"), "[A] 選びを外すとまた押せない")


def _mounted_list_tools(cx):
    """[A] 2g. 一覧の件数と「もっと見る」"""
    check, errors, pg = cx.check, cx.errors, cx.pg
    # 2g. 一覧の件数と「もっと見る」。配信をたくさんに増やして確かめる(後の場面 2i もこの配信を使う)。
    # 検索・並び替え・まとめ方・非表示の細かい操作は画面の道に入れない(写真の関所 ui_audit で見る)
    studio_home = os.environ["STUDIO_HOME"]
    seed_more_cases(os.path.join(studio_home, "data.json"), n=34)
    pg.click("#btnReload")
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 30", 15000),
          "[A] 配信が35本でも、最初は30件だけ描く(絞り込んだ分だけ描く): %s"
          % pg.evaluate("document.querySelectorAll('#list .pt-case').length"))
    check("35" in pg.text_content("#count"), "[A] 件数の表示に全体の件数が出る: %s" % pg.text_content("#count"))
    pg.click("#btnMore")
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length === 35", 10000), "[A] 「もっと見る」で残りも描く")

    real = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
    check(not real, "[A] 一覧の道具を操作しても画面のエラーなし: %s" % real[:3])


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


def _mounted_next_steps(cx):
    """[A] 2i. 処理の状況に残りを出さない・単体の文字起こしの副題・案件の行は結果だけ・リンクの開き方・依頼の受付の外の文字。
    空の表示・消えた配信・フォーカスと Enter の細かい場面は画面の道に入れない"""
    check, pg = cx.check, cx.pg
    seed_next_cases(os.path.join(os.environ["STUDIO_HOME"], "data.json"), cx.tmp)
    pg.click("#btnReload")
    check(wait_js(pg, "!!document.getElementById('case-e2eNext0002')", 15000), "[A] 2i: 足した配信が一覧に出た")
    _next_todo(cx)
    _next_case_buttons(cx)
    _intake_untrusted_text(cx)


def _mounted_new_case_and_ops(cx):
    """[A] 2j. 新しい案件の引き出し(スタジオ ① のつなぎ cases-panels/new.js・開いたときに初めて読む)・/?url=…#new・
    運用の枠(中の欄が開けば枠も開く)と、その中の編集の精度と学習(portal-edit.js・開いたときに初めて読む)"""
    check, ctx = cx.check, cx.ctx
    p = ctx.new_page()
    p.on("pageerror", lambda e: cx.errors.append(str(e)))
    p.on("console", lambda m: cx.errors.append(m.text) if m.type == "error" else None)   # CSP の違反もここに入る
    p.goto(cx.base)
    check(wait_js(p, "!!document.getElementById('newCaseBtn') && !!document.getElementById('opsBox')", 15000), "[A] 2j: ホームに「新しい案件」と運用の枠")
    check(p.evaluate("document.getElementById('newDrawer').hidden && typeof window.NewCasePanel === 'undefined' && !document.querySelector('#newDrawer #rkCond')"),
          "[A] 2j: 新しい案件の引き出しは閉じていて、部品はまだ読んでいない(開いたときに初めて読む)")
    p.click("#newCaseBtn")
    check(wait_js(p, "!document.getElementById('newDrawer').hidden && !!document.querySelector('#newDrawer #rkCond') && !!document.querySelector('#newDrawer #qUrls') "
                     "&& !!document.querySelector('#newDrawer #qList') && !!document.querySelector('#newDrawer #btnGo')", 25000),
          "[A] 2j: 「新しい案件」で引き出しが開き、スタジオ ① の中身(配信を探す・URL から入れる・解析の順番待ち)が出た: %s" % p.evaluate("document.getElementById('newBody').textContent.slice(0, 120)"))
    check(p.evaluate("typeof window.Studio === 'undefined' && typeof window.NewCasePanel === 'object'"), "[A] 2j: 読み込みのあと window.Studio は残さない(ホームの名前を汚さない)")
    check(p.is_disabled("#qAdd") and "入れる" in (p.get_attribute("#qAdd", "title") or ""), "[A] 2j: 欄が空のうちは「解析に追加」は押せない(理由つき)")
    p.fill("#qUrls", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    check(wait_js(p, "!document.getElementById('qAdd').disabled", 5000), "[A] 2j: URL を入れると押せる(押さない = 解析は始めない)")
    check(wait_js(p, "document.getElementById('btnGo').disabled && !!document.getElementById('btnGo').getAttribute('data-ui-why')", 10000),
          "[A] 2j: 「検索する」はキー・事務所が無いうちは押せない + 理由: %s" % p.get_attribute("#btnGo", "data-ui-why"))
    check(p.evaluate("getComputedStyle(document.getElementById('newDrawer')).display !== 'none' && document.getElementById('newDrawer').getBoundingClientRect().width > 700"),
          "[A] 2j: 引き出しは配信の一覧が読める広さ(700px 以上)")
    p.keyboard.press("Escape")
    check(wait_js(p, "document.getElementById('newDrawer').hidden", 5000), "[A] 2j: Esc で閉じる")
    p.click("#newCaseBtn")
    check(wait_js(p, "!document.getElementById('newDrawer').hidden && document.getElementById('qUrls').value.indexOf('dQw4w9WgXcQ') >= 0", 5000), "[A] 2j: 開き直しても入れた URL が残る(作り直さない)")
    p.close()
    _new_case_search_settings(cx)

    # ?url= を付けた /#new は引き出しを開いて、欄に入れるだけ(解析は押すまで始めない)
    q = ctx.new_page()
    q.on("pageerror", lambda e: cx.errors.append(str(e)))
    q.goto(cx.base + "?url=https%3A%2F%2Fyoutu.be%2FdQw4w9WgXcQ#new")
    check(wait_js(q, "!document.getElementById('newDrawer').hidden && !!document.getElementById('qUrls') && document.getElementById('qUrls').value.indexOf('dQw4w9WgXcQ') >= 0", 25000),
          "[A] 2j: /?url=…#new は引き出しを開いて URL を欄に入れる: %s" % q.evaluate("[location.href, document.getElementById('qUrls') && document.getElementById('qUrls').value]"))
    check(q.evaluate("!document.getElementById('qParam').hidden") and q.evaluate("document.querySelectorAll('#qList .q-item').length") == 0, "[A] 2j: 受け取った案内が出て、解析はまだ始めていない")
    q.close()

    # 運用の枠: 既定で閉じている・中の欄が開けば枠も開く・編集の精度と学習は開いたときに初めて読む
    r = ctx.new_page()
    r.on("pageerror", lambda e: cx.errors.append(str(e)))
    r.goto(cx.base)
    check(wait_js(r, "!!document.getElementById('editOpsBox')", 15000), "[A] 2j: 運用の中に「編集の精度と学習」")
    check(r.evaluate("document.getElementById('opsBox').open === false && document.getElementById('editOpsBox').open === false"), "[A] 2j: 運用の枠は既定で畳んである")
    check(r.evaluate("document.getElementById('accOut').textContent === '' && document.getElementById('lnList').textContent === ''"), "[A] 2j: 精度と学習は開くまで読まない")
    r.evaluate("document.getElementById('editOpsBox').open = true")
    check(wait_js(r, "document.getElementById('opsBox').open === true", 5000), "[A] 2j: 中の欄を開くと運用の枠も開く")
    check(wait_js(r, "/校正済みの行がまだありません|文字誤り率/.test(document.getElementById('accOut').textContent)"
                     " && /候補はありません|学習します|誤/.test(document.getElementById('lnList').textContent) && !document.querySelector('#editOpsBox .pt-edit-err')", 20000),
          "[A] 2j: 認識精度の測定・修正から学習した候補が読めた: %s" % r.evaluate("[document.getElementById('accOut').textContent.slice(0, 60), document.getElementById('lnList').textContent.slice(0, 60)]"))
    r.select_option("#accScope", "eval")
    check(wait_js(r, "/校正済みの行がまだありません|文字誤り率/.test(document.getElementById('accOut').textContent) && !document.querySelector('#editOpsBox .pt-edit-err')", 10000), "[A] 2j: 対象を変えて測り直せる")
    r.close()

    _new_case_rank(cx)
    _new_case_queue(cx)   # 解析の順番待ちに 1 本入れるので最後に(上の ?url= の場面は順番待ちが空のことを見る)


def _new_case_search_settings(cx):
    """[A] 2j-2. 新しい案件の末尾の「探す設定」: API キーの保存と削除(札が変わる)・事務所の登録(rank.js の
    mountRegistry)・コラボ(studio/collab.js を開いたときに読む)・/#new?set=reg で事務所の登録まで開く・画面のエラーの記録(client-errors.jsonl)が増えない"""
    check, ctx = cx.check, cx.ctx
    log = os.path.join(cx.sup.logs_dir, "client-errors.jsonl")
    size0 = os.path.getsize(log) if os.path.exists(log) else 0
    errs = []
    p = ctx.new_page()
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)   # CSP の違反もここに入る
    p.goto(cx.base + "#new")
    check(wait_js(p, "!!document.querySelector('#newDrawer #nwSet') && document.getElementById('nwKeyState').textContent !== ''", 25000),
          "[A] 2j-2: 新しい案件の末尾に「探す設定」とキーの札: %s" % p.evaluate("(document.getElementById('nwKeyState') || {}).textContent"))
    st0 = p.text_content("#nwKeyState")
    check(st0 == "疑似モード(キー不要)" and p.evaluate("!document.getElementById('nwSet').open") and p.is_hidden("#nwToolNotice"),
          "[A] 2j-2: 探す設定は既定で畳んである・疑似のスタジオはキー不要の札・ffmpeg と yt-dlp の案内は出さない: %s" % st0)
    p.click("#nwSet > summary")
    p.fill("#nwKeyIn", "AIza" + "e2eTestKey" * 3)
    p.click("#nwKeySave")
    check(wait_js(p, "document.getElementById('nwKeyMsg').textContent === '保存しました' && document.getElementById('nwKeyState').textContent === 'キー: 設定済み'"
                     " && document.getElementById('nwKeyIn').value === ''", 10000),
          "[A] 2j-2: API キーを保存すると札が「キー: 設定済み」に変わり、欄は空に戻る: %s / %s" % (p.text_content("#nwKeyMsg"), p.text_content("#nwKeyState")))
    p.click("#nwKeyDel")   # キーがあるので確かめのダイアログ(取り消せない)
    check(wait_js(p, "!!document.querySelector('dialog[open] .btn.danger')", 5000), "[A] 2j-2: 「キーを削除」は確かめのダイアログを出す")
    p.click("dialog[open] .btn.danger")
    check(wait_js(p, "document.getElementById('nwKeyMsg').textContent === '削除しました' && document.getElementById('nwKeyState').textContent === %s" % json.dumps(st0), 10000),
          "[A] 2j-2: 削除すると札が元に戻る: %s / %s" % (p.text_content("#nwKeyMsg"), p.text_content("#nwKeyState")))
    p.click("#nwSetReg > summary")
    check(wait_js(p, "!!document.querySelector('#nwRegHost.reg-host') && document.getElementById('nwRegHost').textContent.indexOf('各事務所に所属するチャンネル') >= 0", 10000),
          "[A] 2j-2: 事務所の登録を開くと rank.js の登録の欄が描かれる")
    p.click("#nwSetCollab > summary")
    check(wait_js(p, "!!document.querySelector('#nwCollabHost #clMake')", 15000), "[A] 2j-2: コラボを開くと studio/collab.js を読んで描く(#clMake)")
    check(p.evaluate("typeof window.Studio === 'undefined'"), "[A] 2j-2: コラボを読んだあとも window.Studio は残さない")
    p.close()
    r = ctx.new_page()
    r.on("pageerror", lambda e: errs.append(str(e)))
    r.goto(cx.base + "#new?set=reg")
    check(wait_js(r, "!document.getElementById('newDrawer').hidden && !!document.getElementById('nwSet') && document.getElementById('nwSet').open"
                     " && document.getElementById('nwSetReg').open && !!document.querySelector('#nwRegHost.reg-host')", 25000),
          "[A] 2j-2: /#new?set=reg は引き出しを開いて、探す設定の事務所の登録まで開く")
    r.close()
    real = [e for e in errs if "Failed to load resource" not in e]
    check(not real, "[A] 2j-2: 探す設定を操作しても画面のエラーなし(CSP 違反を含む): %s" % real[:3])
    time.sleep(0.5)   # 記録の送信(api/ytt/client-log)が届くまで
    size1 = os.path.getsize(log) if os.path.exists(log) else 0
    check(size1 == size0, "[A] 2j-2: 画面のエラーの記録(client-errors.jsonl)が増えない: %d → %d" % (size0, size1))


AGC_JS = "[...document.querySelectorAll('#newDrawer #agChecks .agc')].map(e => [e.value, e.checked])"


def _watch_errors(p, errs):
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)   # CSP の違反もここに入る


def _new_case_rank(cx):
    """[A] 2j-3. 新しい案件の ① 配信を探す(引き出しの中): 登録した事務所だけにチェック・外したのは残る /
    期間の早見「昨日0時〜今」と「10分以上の動画だけ」(minDur 600)/ 検索の結果(疑似の YouTube API)/ まとめて実行(入口の start-new は偽物)"""
    check, ctx = cx.check, cx.ctx
    from human.find import rank as _rank   # 取り込んだスタジオと同じ部品(同じプロセス・置き場所は疑似のスタジオの STUDIO_HOME)
    from ytt import apikey as _apikey
    for ag in ("hololive", "nijisanji"):   # 疑似のスタジオ(STUDIO_FAKE)なので YouTube へは繋がない
        _rank.import_official_channels(ag)
        _rank.resolve(ag)
    _apikey.set_api_key("AIzaTESTKEY0123456789abcdefghij")
    errs = []
    p = ctx.new_page()
    _watch_errors(p, errs)
    p.goto(cx.base + "#new")
    check(wait_js(p, "%s.length === 2" % AGC_JS, 25000), "[A] 2j-3: 事務所の選び方が出る(ホロライブとその他。既定の選び方は test_cand_panel.cjs): %s" % p.evaluate(AGC_JS))
    p.check('#agChecks .agc[value="other"]')
    p.reload()
    check(wait_js(p, "%s.length === 2" % AGC_JS, 25000) and dict(p.evaluate(AGC_JS)) == {"hololive": True, "other": True},
          "[A] 2j-3: 自分で入れた事務所は、読み込み直しても入ったまま: %s" % p.evaluate(AGC_JS))
    p.check('#agChecks .agc[value="other"]')
    # 期間の早見と「10分以上の動画だけ」
    check(p.evaluate("document.querySelector('#rkCond .cs-quick .btn').hasAttribute('data-yday')"), "[A] 2j-3: 期間の早見の先頭は「昨日0時〜今」")
    p.click("#rkCond [data-yday]")
    days = p.evaluate("""() => { const f = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
        const e = new Date(), s = new Date(); s.setDate(s.getDate() - 1); return [f(s), f(e)]; }""")
    check([p.input_value("#dStart"), p.input_value("#dEnd")] == days, "[A] 2j-3: 「昨日0時〜今」で 開始 = 昨日・終了 = 今日: %s" % days)
    check(p.is_checked("#minDur10") and "10分以上" in (p.text_content("#rkAdvSum") or ""), "[A] 2j-3: 「10分以上の動画だけ」は既定でオン(閉じた見出しの要約にも出る)")
    p.click('#rkCond [data-days="30"]')
    check(wait_js(p, "!document.getElementById('btnGo').disabled", 10000), "[A] 2j-3: 事務所を登録すると「検索する」が押せる")
    with p.expect_request(lambda r: r.url.endswith("/api/rank/search") and r.method == "POST") as rq:
        p.click("#btnGo")
    check(json.loads(rq.value.post_data or "{}").get("minDur") == 600, "[A] 2j-3: 検索の条件に最低の再生時間 600 秒を送る: %s" % rq.value.post_data)
    _rank_results(cx, p)
    _rank_autorun(cx, p)
    p.close()
    check(not errs, "[A] 2j-3: ① を操作しても画面のエラーなし(CSP 違反を含む): %s" % errs[:3])


def _rank_results(cx, p):
    """2j-3 の検索の結果: 既定「全部まとめて」上位 30 本・各行に事務所名・「事務所ごと」・結果の絞り込みと空の案内・チェックで選択数"""
    check = cx.check
    check(wait_js(p, "document.querySelectorAll('#results .rk-table tr[data-vid]').length > 5", 30000), "[A] 2j-3: 検索の結果が並ぶ")
    views = p.eval_on_selector_all("#results tr[data-vid] td.n.num:not(.hide-s)", "els => els.map(e => Number(e.textContent.replace(/,/g, '')))")
    check(p.locator("#results .rk-table").count() == 1 and views == sorted(views, reverse=True) and 5 < len(views) <= 30,
          "[A] 2j-3: 既定は「全部まとめて」= 全事務所を 1 つの表に再生数の多い順(上位 30 本): %d 本" % len(views))
    check(p.locator("#results tr[data-vid] .rk-ag-name").count() == len(views), "[A] 2j-3: 全部まとめて: 各行に事務所名")
    p.click('#results [data-view="ag"]')
    check(wait_js(p, "document.querySelectorAll('#results details.rk-ag').length === 2", 5000), "[A] 2j-3: 「事務所ごと」で事務所ごとのまとまり(選んだ 2 事務所)")
    p.click('#results [data-view="all"]')
    p.fill("#rkQ", "zzzz-no-hit")
    check(wait_js(p, "document.querySelectorAll('#results tr[data-vid]').length === 0 && document.querySelectorAll('#rkBody .empty').length === 1", 5000),
          "[A] 2j-3: 結果の中を絞り込める(合わないときは空の案内)")
    p.fill("#rkQ", "")
    p.check("#results tr[data-vid] .pk >> nth=0")
    check(p.text_content("#pickN") == "1" and p.is_enabled("#pickGo"), "[A] 2j-3: チェックすると選択数が増え、追加ボタンが押せる")


def _rank_autorun(cx, p):
    """2j-3 のまとめて実行: 入口の ② の口(api/flow/submit・runs)は偽物。送る中身(封筒の videoId と題名・束の adopt.top)・始めた行の印・チェックできない"""
    check = cx.check
    check(p.is_visible("#rkAuto"), "[A] 2j-3: 選んだ配信の「まとめて実行」が出る(ホームの中)")
    vid = p.get_attribute("#results tr[data-vid] .pk >> nth=0", "data-id")
    sent = []

    def fake_runs():
        return [{"id": "e2erun00002", "kind": "video", "videoId": vid, "docId": None, "mode": "full", "modeLabel": "全部", "title": "検索の配信", "state": "queued",
                 "created": int(time.time() * 1000), "finished": None, "message": "", "error": "", "steps": []}] if sent else []

    def fake_start(route):
        sent.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(json={"run": fake_runs()[0]})
    p.route("**/api/flow/submit", fake_start)
    p.route("**/api/flow/runs", lambda route: route.fulfill(json={"runs": fake_runs(), "past": [], "modes": {}}))
    p.click("#rkAuto > summary")
    check(p.is_enabled("#rkAutoGo") and "1 本" in (p.text_content("#rkAutoGo") or ""), "[A] 2j-3: 選んだ本数が「まとめて実行」のボタンに出る: %s" % p.text_content("#rkAutoGo"))
    p.fill("#rkAutoTop", "2")
    p.click("#rkAutoGo")
    check(wait_js(p, "/まとめて実行の順番待ち/.test((document.querySelector('#results tr[data-vid=\"%s\"] .chip') || {}).textContent || '')" % vid, 10000),
          "[A] 2j-3: 始めた配信の行に「まとめて実行の順番待ち」の印")
    it = ((sent[0].get("envelope") or {}).get("input") or {}) if sent else {}
    check(it.get("videoId") == vid and it.get("title") and it.get("fresh") and ((sent[0].get("spec") or {}).get("adopt") or {}).get("top") == 2,
          "[A] 2j-3: 選んだ配信(封筒の videoId と題名・まだスタジオに無い印 fresh)と採用する数(束の adopt.top)を入口に送る: %s" % (sent[:1],))
    check(p.text_content("#pickN") == "0" and p.is_disabled('#results tr[data-vid="%s"] .pk' % vid), "[A] 2j-3: 始めた配信は選択から外れ、順番待ちの間はチェックできない")
    p.unroute("**/api/flow/submit")
    p.unroute("**/api/flow/runs")


def _new_case_queue(cx):
    """[A] 2j-4. 新しい案件の「URL から入れる」: 「解析に追加」で順番待ち → 疑似の解析が終わると「確認する」→
    案件の画面の候補へ (失敗の文は test_cand_panel.cjs。?url= を欄に入れるだけは 2j で確かめた)"""
    check, ctx = cx.check, cx.ctx
    media = os.path.join(cx.tmp, "fake-media.webm")   # 疑似のスタジオの解析が「取ってきた」ことにする見本の動画(STUDIO_FAKE_MEDIA。main の環境の patch が戻す)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15:duration=40",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-shortest", "-c:v", "libvpx", "-b:v", "200k", "-deadline", "realtime",
                    "-c:a", "libopus", media], check=True, timeout=120)
    os.environ["STUDIO_FAKE_MEDIA"] = media
    errs = []
    p = ctx.new_page()
    _watch_errors(p, errs)
    p.goto(cx.base + "#new")
    check(wait_js(p, "!!document.querySelector('#newDrawer #qUrls')", 25000), "[A] 2j-4: 新しい案件の引き出し")
    p.fill("#qUrls", "https://youtu.be/abcdefghijk")
    p.click("#qAdd")
    check(wait_js(p, "!!document.querySelector('#qList .q-item') && document.getElementById('qUrls').value === ''", 10000), "[A] 2j-4: 「解析に追加」で順番待ちに入り、欄が空になる")
    wait_js(p, "(() => { const i = document.querySelector('#qList .q-item'); return !!i && ['done', 'error'].includes(i.dataset.status); })()", 90000)
    check(p.get_attribute("#qList .q-item", "data-status") == "done" and p.locator('#qList [data-act="review"]').count() == 1
          and "確認する" in (p.text_content("#qNext") or ""), "[A] 2j-4: 疑似の解析が終わり「確認する」と次にやることが出る: %s" % p.get_attribute("#qList .q-item", "data-status"))
    p.click('#qList [data-act="review"]')
    p.wait_for_url(lambda u: "/cases?c=abcdefghijk" in u and u.endswith("#cand"), timeout=20000)
    check(True, "[A] 2j-4: 「確認する」は案件の画面の候補(/cases?c=…#cand)へ: %s" % p.url)
    p.close()
    check(not errs, "[A] 2j-4: URL から入れても画面のエラーなし: %s" % errs[:3])


def _next_todo(cx):
    """処理の状況に採用待ち(確認前の候補)を出さない / 紐づかない文書の副題"""
    check, pg = cx.check, cx.pg
    check(not pg.eval_on_selector_all(".pt-todo-pill", "els => els.filter(p => /待ち$/.test(p.textContent) && p.textContent !== '待ち').length"),
          "[A] 確認前の候補の配信があっても、処理の状況に採用待ち・校正待ちは出ない")
    check(wait_js(pg, "!!document.querySelector('.pt-doc-sub') && document.querySelector('.pt-doc-sub').textContent.indexOf('solo.mp4') >= 0", 10000)
          and "更新 " in pg.text_content(".pt-doc-sub") and "ytt-portal-e2e" not in pg.text_content(".pt-doc-sub")
          and "solo.mp4" in (pg.get_attribute(".pt-doc-sub", "title") or ""),
          "[A] 単体の文字起こしの行にも副題(ファイル名だけ。フルパスは title): %s" % pg.text_content(".pt-doc-sub"))


def _next_case_buttons(cx):
    """案件の行は結果だけ(次の一手のボタンなし)/ 中身のリンクは同じ窓(target なし)・行を開いて同じタブのまま案件の画面へ"""
    check, ctx, pg = cx.check, cx.ctx, cx.pg
    if pg.is_visible("#btnMore"):   # 一覧の 31 件目より後(e2eCase0001)も見る
        pg.click("#btnMore")
    check(pg.eval_on_selector_all(".pt-case-next", "e => e.length") == 0 and "校正 1/2行" in (pg.text_content("#case-e2eCase0001 .pt-case-row") or ""),
          "[A] 行に次の一手のボタンは無く、結果(校正の済み具合)だけ: %s" % pg.text_content("#case-e2eCase0001 .pt-case-row"))
    tg = pg.evaluate("""() => ({ content: [...document.querySelectorAll('.pt-clip a, .pt-case-studio a, #unlinkedOpen, .pt-doc-open, .pt-todo-link')]
                                      .filter(a => a.hasAttribute('target')).map(a => a.textContent),
                                 open: [...document.querySelectorAll('.pt-tool .pt-open')].map(a => a.target) })""")
    check(tg["content"] == [] and tg["open"] and all(t == "_blank" for t in tg["open"]),
          "[A] 中身のリンクは同じ窓(target なし)・「詳しく」の「開く」(サーバーの管理)だけ新しい窓: %s" % tg)
    p2 = ctx.new_page()
    p2.on("pageerror", lambda e: cx.errors.append(str(e)))
    p2.goto(cx.base)
    check(wait_js(p2, "!!document.getElementById('case-e2eNext0002')", 15000), "[A] 別のタブのホーム")
    p2.fill("#fText", "案件の通し確認")
    check(wait_js(p2, "!!document.querySelector('#case-e2eCase0001 .pt-case-row')", 10000), "[A] 絞り込んで行が出た")
    p2.click("#case-e2eCase0001 .pt-case-row")
    n_pages = len(ctx.pages)
    p2.click("#case-e2eCase0001 .pt-clip a:has-text('校正で開く')")
    p2.wait_for_url(lambda u: "/cases" in u, timeout=20000)
    check(wait_js(p2, "new URLSearchParams(location.search).get('c') === 'e2eCase0001' && !!document.getElementById('csRail')", 20000)
          and len(ctx.pages) == n_pages, "[A] 行を開いて「校正で開く」を押すと同じタブのまま案件の画面がその配信を開く: %s" % p2.url)
    check(wait_js(p2, "document.querySelectorAll('#csPane #segs .seg').length === 2", 20000),
          "[A] 着いた先の校正のパネルが文書の 2 行を出す(編集の API が文書を返す): %s" % p2.evaluate("document.querySelectorAll('#csPane #segs .seg').length"))
    p2.close()


def _intake_untrusted_text(cx):
    """依頼の受付の一覧(ホームの運用の枠)で、外から来る題名・知らせの題は文字のまま(HTML として解釈しない)。
    友人の依頼の題名は YouTube の題名 = 外の文字。受付の API は偽物"""
    check, ctx = cx.check, cx.ctx
    now = int(time.time() * 1000)
    intake = {"enabled": True, "folder": "C:\\Dropbox\\アプリ\\切り抜き依頼", "top": 3, "maxHours": 6, "maxGB": 10, "state": "watching", "stateLabel": "見張り中",
              "message": "", "lastScan": now - 90000, "today": 1,
              "requests": [{"id": "r1", "kind": "url", "source": "app", "title": "【雑談】<b>朝の配信</b>", "streamer": "さくらみこ", "memo": "",
                            "received": now - 300000, "state": "accepted", "stateLabel": "受け付けた", "reason": "", "runIds": [],
                            "items": [{"label": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "state": "accepted", "reason": ""}]}],
              "notices": [{"at": now - 600000, "receivedAt": now - 60000, "requestId": "r1", "title": "さくらみこ|<i>朝の配信</i>", "message": "直りませんでした",
                           "detail": "", "code": "transcribe", "appVersion": "1.0.0", "hasLog": False}]}
    p = ctx.new_page()
    p.on("pageerror", lambda e: cx.errors.append(str(e)))
    p.route("**/api/intake", lambda route: route.fulfill(json=intake))
    p.goto(cx.base)
    p.evaluate("document.getElementById('opsBox').open = true; document.getElementById('intakeBox').open = true")
    check(wait_js(p, "document.querySelectorAll('#intakeList .pt-intake-item').length === 1 && !document.getElementById('intakeNotices').hidden", 15000),
          "[A] 依頼の受付: 依頼の一覧と友人からの知らせが出る: %s" % p.evaluate("(document.getElementById('intakeList') || {}).textContent"))
    check("【雑談】<b>朝の配信</b>" in (p.inner_text("#intakeList") or "") and p.eval_on_selector_all("#intakeList b", "e => e.length") == 0
          and "<i>朝の配信</i>" in (p.text_content("#intakeNoticeList") or "") and p.eval_on_selector_all("#intakeNoticeList i", "e => e.length") == 0,
          "[A] 依頼の題名・知らせの題の HTML は要素にならない(文字のまま)")
    p.close()


def _mounted_second_tab(cx):
    """[A] 8. ホームの別のタブを開いておく(10. の切断の表示に使う)"""
    mob = cx.ctx.new_page()
    mob.goto(cx.base)
    cx.check(wait_js(mob, "document.querySelectorAll('.pt-case').length >= 2"), "[A] 別のタブでも案件の一覧が出る")
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
    """ライブの書き出し(src/flow/live_export.py の _finish)と同じ形の .clip.json を 作業用 に置いた切り抜き(動画の中身は要らない。
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
    """自動でできた切り抜きの見本: 録画 A に自動の切り抜き 2 本(配信中の候補 + パックあり / 配信後の解析 + 控え)、録画 B に人の切り抜き 1 本。
    スタジオには画面と同じ API で登録して書き出し済みにする(スタジオが覚えている配信でないと「要らない」の不採用が通らない)。-> {A の 1 本目・2 本目・B の動画}"""
    check, pg = cx.check, cx.pg
    out_dir = pg.evaluate("fetch('/studio/api/state', {cache: 'no-store'}).then(r => r.json()).then(j => j.outDir)")
    clips = {"a1": _live_clip(out_dir, "01_自動.mp4", "auto", recording=AUTO_REC_A), "a2": _live_clip(out_dir, "02_解析.mp4", "archive", recording=AUTO_REC_A, bench=True),
             "b1": _live_clip(out_dir, "03_人.mp4", "manual", recording=AUTO_REC_B)}
    pack = os.path.join(os.path.dirname(clips["a1"]), "01_自動_pack")   # cut2resolve が作ったパック(パックを作った記録 = flow/packrec と中身の動画)
    os.makedirs(pack, exist_ok=True)
    video = os.path.join(pack, "01_自動.mp4")
    with open(video, "wb") as f:
        f.write(b"x")
    from flow import packrec
    packrec.write_record({"out_dir": pack, "files": [("video", video)]}, clips["a1"], False)   # 取り込んだ cut2resolve が登録した置き場所(同じプロセス)
    for rec, keys in ((AUTO_REC_A, ("a1", "a2")), (AUTO_REC_B, ("b1",))):
        st, _v = pg.evaluate(STUDIO_CALL, ["POST", "/api/videos/open", {"kind": "live", "recorder": "local", "recording": rec,
                                                                         "url": "https://www.youtube.com/watch?v=e2eLiveAAAA", "title": "e2e ライブ " + rec[-6:]}])
        st2, v = pg.evaluate(STUDIO_CALL, ["GET", "/api/video?id=" + rec, None])
        marks = [{"start": 10.0 + 60 * i, "end": 40.0 + 60 * i, "label": "", "status": "adopted"} for i in range(len(keys))]
        st3, v = pg.evaluate(STUDIO_CALL, ["PUT", "/api/video", {"id": rec, "marks": marks, "baseRev": v["video"]["rev"]}])
        got = sorted(v.get("video", {}).get("marks") or [], key=lambda m: m["start"])
        ok = [pg.evaluate(STUDIO_CALL, ["POST", "/api/live/exported", {"id": rec, "markId": m["id"], "path": clips[k]}])[0] for m, k in zip(got, keys)]
        check((st, st2, st3, ok) == (200, 200, 200, [200] * len(keys)), "[A] 見本のライブの録画 %s をスタジオに登録して書き出し済みに: %s" % (rec, (st, st2, st3, ok)))
    return clips


def _open_auto_row(cx):
    """読み込み直して、録画 A の行を開く(自動の切り抜きは開いた行の中)"""
    check, pg = cx.check, cx.pg
    pg.reload()
    check(wait_js(pg, "!!document.querySelector('#case-%s .pt-case-row')" % AUTO_REC_A, 15000), "[A] 2k: 一覧に録画 A の行が出た")
    pg.click("#case-%s .pt-case-row" % AUTO_REC_A)
    return wait_js(pg, "document.getElementById('case-%s').open === true" % AUTO_REC_A, 10000)


def _mounted_auto_clips(cx):
    """[A] 2k. 自動でできた切り抜きの確認: 札・出どころ・[採用](パック・届ける先が無いと押せない → 届ける)・
    [要らない](ごみ箱フォルダへ・スタジオのマークを不採用)"""
    check, pg = cx.check, cx.pg
    seed_auto_clips(cx)
    pg.reload()
    check(wait_js(pg, "document.querySelectorAll('#list .pt-case').length > 0", 15000), "[A] 2k: 一覧が出た")
    check(pg.text_content("#case-%s .pt-case-autopill" % AUTO_REC_A) == "自動 2本" and pg.is_hidden("#case-%s .pt-case-autopill" % AUTO_REC_B),
          "[A] 2k: 閉じた行にも「自動 n本」(人の切り抜きだけの配信には出さない)")
    pg.click("#case-%s .pt-case-row" % AUTO_REC_A)
    check(wait_js(pg, "document.getElementById('case-%s').open === true" % AUTO_REC_A, 10000), "[A] 2k: 行を開くと自動の切り抜きが見える")
    row = "#case-%s .pt-ac" % AUTO_REC_A
    texts = pg.eval_on_selector_all(row, "els => els.map(e => e.querySelector('.row').textContent)")
    check(len(texts) == 2 and "自動" in texts[0] and "配信中の候補" in texts[0] and "配信後の解析" in texts[1] and "控え" in texts[1],
          "[A] 2k: 自動の札・出どころ・控え: %s" % texts)
    sizes = pg.evaluate("[...document.querySelectorAll('%s .pt-ac-deliver, %s .pt-ac-discard')].map(b => Math.round(b.getBoundingClientRect().height))" % (row, row))
    check(len(sizes) == 4 and min(sizes) >= 28, "[A] 2k: 採用・要らない は 28px 以上: %s" % sizes)
    if cx.shots:
        pg.screenshot(path=os.path.join(cx.shots, "portal-auto-clips.png"), full_page=True)
    # 届ける先(依頼の受付の Dropbox のフォルダ)が無い・パックが無いときは押せず、理由を出す
    check(wait_js(pg, "(() => { const b = document.querySelectorAll('%s .pt-ac-deliver'); return b.length === 2 && b[0].disabled && b[1].disabled"
                      " && document.querySelectorAll('%s .pt-ac-msg')[0].textContent.indexOf('届ける先が決まっていません') >= 0; })()" % (row, row), 15000)
          and "パックがまだありません" in pg.eval_on_selector_all(row + " .pt-ac-msg", "els => els[1].textContent"),
          "[A] パックが無い・届ける先が無いと「採用」は押せず、理由を出す: %s" % pg.eval_on_selector_all(row + " .pt-ac-msg", "els => els.map(e => e.textContent)"))
    _auto_deliver(cx, row)
    _auto_discard(cx)
    pg.evaluate("document.getElementById('advancedBox').open = true")   # あとの「すべて終了」のため(読み込み直すと閉じる)


def _auto_deliver(cx, row):
    """届ける先を決めると押せる → 二度押しで届ける → 「届けた」。
    zip の置き場所・記録は src/manage/cases の test_deliver_puts_zip_in_output_and_records_it、二度押しの時計は test_uikit_stub.cjs"""
    check, pg = cx.check, cx.pg
    box = os.path.join(cx.tmp, "Dropbox")
    os.makedirs(box, exist_ok=True)
    check(pg.evaluate(YTT_PREFS, {"folder": box}) == 200, "[A] 依頼の受付の Dropbox のフォルダを決めた")
    # フォルダは設定の画面で決めてホームへ戻る = ホームを開き直す(開いたままだと依頼の受付を読み直す 15 秒の周期まで変わらない)
    check(_open_auto_row(cx), "[A] ホームを開き直して録画 A の行を開いた")
    check(wait_js(pg, "(() => { const b = document.querySelector('%s .pt-ac-deliver'); return b && !b.disabled; })()" % row, 20000),
          "[A] 届ける先が決まると「採用」が押せる(パックのある 1 本目だけ): %s" % pg.eval_on_selector_all(row + " .pt-ac-deliver", "els => els.map(e => e.disabled)"))
    check(pg.eval_on_selector_all(row + " .pt-ac-deliver", "els => els[1].disabled"), "[A] パックの無い 2 本目は押せないまま")
    btn = row + " .pt-ac-deliver"
    pg.click(btn)
    pg.click(btn)
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('友人へ届けました') >= 0)", 20000), "[A] 二度押しで届けて、届けたと知らせる")
    check(wait_js(pg, "!!document.querySelector('%s .pt-ac-done') && document.querySelectorAll('%s .pt-ac-deliver').length === 1" % (row, row), 10000),
          "[A] 届けた切り抜きは「届けた」の札になり、「採用」は消える(二度は届けない)")


def _auto_discard(cx):
    """要らない = 二度押しで ごみ箱フォルダへ・スタジオ(取り込んだ本物)のマークを不採用 → 行の自動の札は残りの本数。
    動かすファイル・人の判断の記録は src/manage/cases の test_discard_moves_files_to_trash_rejects_mark_and_records"""
    check, pg = cx.check, cx.pg
    btn = "#case-%s .pt-ac:nth-child(2) .pt-ac-discard" % AUTO_REC_A
    pg.click(btn)
    pg.click(btn)
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('ごみ箱フォルダへ移して') >= 0)", 15000), "[A] 二度押しで片付けて、知らせる")
    _st, v = pg.evaluate(STUDIO_CALL, ["GET", "/api/video?id=" + AUTO_REC_A, None])
    check(sorted(m["status"] for m in v["video"]["marks"]) == ["exported", "rejected"], "[A] スタジオのマークは不採用: %s" % [m["status"] for m in v["video"]["marks"]])
    check(wait_js(pg, "document.querySelector('#case-%s .pt-case-autopill').textContent === '自動 1本'" % AUTO_REC_A, 10000),
          "[A] 2k: 要らないにしたあとも、行の自動の札は 自動 1本(届けた 1 本)")


def run_child_process_phase(browser, tmp, shots, check, events):
    """(B) 文字起こしが子プロセスの形(--no-mount 相当・取り込めなかったときの落ち先)。
    異常終了の表示、ログの表示(XSS 対策)を、子プロセスとして確かめる(「詳しく」の中)。起動し直せることは test_launch の test_crash_is_reported_with_log"""
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

        meta = pg.text_content(".pt-tool[data-tool=transcribe] .pt-meta")
        check(("ポート %d" % ports["transcribe"]) in meta and TX_VER in meta and "ホームに取り込み" not in meta,
              "[B] 文字起こしは別のプログラム(子プロセス): %s" % meta)

        # 3. ログ: 開くと末尾が出る。題名などに HTML が入っていても実行されない
        tx = sup.by_id["transcribe"]
        with open(tx.log_path, "a", encoding="utf-8") as f:
            f.write('題名 <img src=x onerror="window.__xss=1"> テスト\n')
        pg.click(".pt-tool[data-tool=transcribe] .pt-logbox summary")
        check(wait_js(pg, "document.querySelector('.pt-tool[data-tool=transcribe] .pt-log').textContent.includes('onerror')"), "[B] ログが表示される")
        check(pg.evaluate("window.__xss") is None and pg.query_selector(".pt-log img") is None, "[B] ログの HTML は文字として表示(XSS なし)")
        check("transcribe.log" in pg.text_content(".pt-tool[data-tool=transcribe] .pt-logpath"), "[B] ログの場所の表示")

        # 4. 異常終了の表示(子を外から強制終了)
        os.kill(sup.by_id["transcribe"].proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))   # Windows は SIGTERM = 強制終了(TerminateProcess)
        check(wait_card(pg, "transcribe", "crashed"), "[B] 異常終了の表示")
        msg = pg.text_content(".pt-tool[data-tool=transcribe] .pt-msg")
        check("異常終了" in msg and not pg.is_hidden(".pt-tool[data-tool=transcribe] .pt-msg"), "[B] 異常終了のメッセージ: %s" % msg)
        if shots:
            os.makedirs(shots, exist_ok=True)
            pg.screenshot(path=os.path.join(shots, "portal-crashed.png"), full_page=True)

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
        from ytt import layout as _layout
        _layout.copy_shared_code(tmp, ignore=shutil.ignore_patterns("__pycache__"), root=REPO)   # 共通のコード(ytt と役割の層 = layout.SHARED_CODE_DIRS。本物と同じ並び)
        env["STUDIO_HOME"] = os.path.join(tmp, "studio-home")
        os.environ["STUDIO_HOME"] = env["STUDIO_HOME"]
        seed_cases(tmp, env["STUDIO_HOME"])
        seed_unlinked(tmp)

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--mute-audio"])
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
