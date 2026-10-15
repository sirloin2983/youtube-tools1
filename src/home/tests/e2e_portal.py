#!/usr/bin/env python3
"""ホーム(src/home/portal.html。段階5: 入口 + 案件を1つにした)の通し確認(Playwright。本物の3ツールを疑似モードで
一時フォルダに写し、空きポートだけを使う)。

    python src/home/tests/e2e_portal.py [--shots <フォルダ>]

いまは「文字起こし」も入口に取り込める(段階3-3。src/home/mount.py の MOUNTS)ので、2つの形をそれぞれ確かめる:

  (A) 本番と同じ形(python src/app/server.py と同じ mounts=tuple(mount.MOUNTS)): 3つとも入口に取り込み。
      2枚のカードが「ホームに取り込み」で動作中になる → ヘッダーの appnav(ホーム / 案件 / 確かめる / 設定)→ 案件の画面(/cases の候補・校正・
      カット。#ver・合言葉・appnav)→ 古い画面の URL の転送(RS8 C4 で /studio/・/transcribe/ の画面を消した。src/app/redirects.py の表・
      /cases.html・/live/・/cut2resolve/)→ 「次にやること」・案件(配信ごと)の一覧・単体の文字起こし → テーマ → 狭い画面 →
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
sys.path.append(os.path.dirname(HERE))   # src(app 層。入口本体は src/app/server.py)
from app import server as L  # noqa: E402
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports, wait_for  # noqa: E402
from ytt import layout, schemas  # noqa: E402


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
    pg.evaluate("document.getElementById('opsBox').open = true; document.getElementById('advancedBox').open = true")   # RS8 C3: 「詳しく」は運用の枠の中
    return ok


APPNAV_JS = ("[...document.querySelectorAll('[data-ui-appnav-item]')].map(a => [a.getAttribute('data-ui-appnav-item'), a.href,"
             " a.getAttribute('aria-current')])")


def check_appnav(check, pg, base, current, label):
    """ヘッダーの appnav(ui-kit v27 = RS8 C4・V1 確かめる V3 で確かめるを足した): ホーム / 案件 / 確かめる / 設定 の 4 つ・行き先は入口の直下(/・/cases・/check・/settings)・
    今の画面の項目だけ aria-current="page"。href は入口の直下からの相対で作る(homeUrl)ので、解決した a.href で比べる"""
    want = [["portal", base], ["cases", base + "cases"], ["check", base + "check"], ["settings", base + "settings"]]
    wait_js(pg, "%s.length === 4" % APPNAV_JS, 10000)
    got = pg.evaluate(APPNAV_JS)
    check([g[:2] for g in got] == want and [g[0] for g in got if g[2] == "page"] == [current],
          "[A] %s: appnav は ホーム / 案件 / 確かめる / 設定 の 4 つ(/・/cases・/check・/settings)で、%s が aria-current: %s" % (label, current, got))


def http_get(port, path):
    """入口へ転送を追わずに GET する -> (HTTP の番号, Location)。path は ASCII(日本語は % にしてから渡す)"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path, headers={"Host": "127.0.0.1:%d" % port})
        r = conn.getresponse()
        r.read()
        return r.status, r.getheader("Location")
    finally:
        conn.close()


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
        json.dump({"id": "deadbeef0001", "title": "案件の字幕", "sourcePath": clip, "updatedAt": 1, "speakers": [],   # 保存した文書には必ずある(校正のパネルが読む)
                   "segments": [{"id": "s1", "start": 0.5, "end": 2.0, "text": "a", "proofed": True}, {"id": "s2", "start": 2.5, "end": 4.0, "text": "b"}]}, f, ensure_ascii=False)


def seed_unlinked(tmp):
    """どの配信にも紐づかない文字起こし(「単体の文字起こし」・次にやることの校正待ちにも出る)"""
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


TX_VER = STUDIO_VER = "v" + tool_version("ytt/version.py", r'^VERSION = "([^"]+)"')   # 全体の版は 1 つ(RS5-E)
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
        _mounted_old_urls(cx)
        _mounted_cases_and_memo(cx)
        _mounted_todo_and_unlinked(cx)
        _mounted_list_tools(cx)
        _mounted_next_steps(cx)
        _mounted_new_case_and_ops(cx)
        _mounted_theme_narrow(cx)
        mob = cx.mob   # 8. の狭い画面のタブ(10. で使う)
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
    check_appnav(check, pg, cx.base, "portal", "ホーム")   # RS8 C4: 「スタジオ」「編集」の項目は無くなった(ホーム / 案件 / 設定)

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
    gt = pg.text_content("#accuracyGoals") if pg.query_selector("#accuracyGoals") else ""   # 畳んだ欄の中(RS8 C3)なので text_content
    check("始める条件(あと何本・何分)" in gt and "定点 15 分: 今 15.8 分 / 目標 15 分 / 届いた" in gt and "定点 30 分: 今 15.8 分 / 目標 30 分 / あと 14.2 分" in gt and "G1" not in gt and "G2" not in gt
          and "学習用の校正 3 時間: 今 0.17 時間 / 目標 3 時間 / あと 2.83 時間" in gt and "確かめ済みの話者の行 200: 今 120 行 / 目標 200 行 / あと 80 行" in gt
          and "採用の記録 配信 10 本: 未測定" in gt and "届いた 1 / 10・未測定 5" in gt,
          "[A] 入口の条件: 今 / 目標 / あと と 未測定: %s" % " / ".join(gt.split("\n"))[:600])
    # RS8 C3・V1 確かめる V3: 確かめるの枠 = 今いちばん効く確認 1 つ(入口の GET api/check/next?n=0 の goal。この見本では時刻の確認が未測定) + 届いた n / m。[始める] は /check へ
    cn = pg.text_content("#checkNow")
    check("行の時刻の判定" in cn and "まだ測っていません" in cn and "G1" not in cn and "届いた 1 / 10" in pg.text_content("#checkSub"),
          "[A] 確かめる: 今いちばん効く確認(入口の next の goal)と届いた数: %s / %s" % (cn, pg.text_content("#checkSub")))
    check(not pg.evaluate("document.getElementById('checkStart').disabled") and pg.evaluate("new URL(document.getElementById('checkStart').href).pathname") == "/check"
          and pg.evaluate("!document.getElementById('autoReview') && !document.getElementById('rvDrawer')"),
          "[A] 確かめる: [始める] は /check へのリンク。ホームの「続けて確認」の引き出しは無い(V1 確かめる V3)")
    check(pg.evaluate("!document.getElementById('checkAll').open") and pg.evaluate("document.getElementById('accuracyGoals').closest('#checkBox') !== null")
          and pg.evaluate("!document.querySelector('#healthList #accuracyGoals')"), "[A] 確かめる: すべての条件は畳んだ欄に(調子の中の行は無くなった)")
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
    """[A] 2. ツールのカードの「開く」・2b. 古い URL(/studio/?video=)をブラウザで開くと案件の画面の候補に着く・
    2c. 案件の画面の校正・カット(同じポートの /cases で、取り込んだスタジオ・編集の API を読める)"""
    base, check, ctx, pg, port = cx.base, cx.check, cx.ctx, cx.pg, cx.port
    # 2. 開く: 新しいタブで同じアドレスの画面が開く(noopener)。RS8 C4 でスタジオ・編集の画面を消したので、カードの「開く」(今も
    # /studio/・/transcribe/ を指す)は入口の転送でホームに戻る。行き先の中身(旧 Studio.state・APP_VERSION・ツール切り替え)は下の案件の画面で確かめる
    for tid in SHOWN:
        href = pg.get_attribute(".pt-tool[data-tool=%s] .pt-open" % tid, "href") or ""
        check(href.startswith("http://127.0.0.1:%d/" % port), "[A] %s の「開く」は同じアドレス: %s" % (tid, href))
    with ctx.expect_page() as info:
        pg.click(".pt-tool[data-tool=studio] .pt-open")
    tab = info.value
    tab.wait_for_load_state()
    check(tab.url.startswith(base) and tab.evaluate("location.pathname") in ("/", "/cases"),
          "[A] カードの「開く」は同じアドレスの画面に着く(古い /studio/ は転送でホームへ): %s" % tab.url)
    check(tab.evaluate("window.opener") is None, "[A] 開いたタブからホームを操作できない(noopener)")
    tab.close()

    # 2b. 古い URL をブラウザで開くと転送を追って、案件の画面の候補(#cand)に着く。候補のパネルは取り込んだスタジオの API を読む(CSP・相対パス)
    tab = ctx.new_page()
    tab.on("pageerror", lambda e: cx.errors.append(str(e)))
    tab.goto(base + "studio/?video=e2eCase0001")
    check(wait_js(tab, "typeof CasesShell === 'object' && CasesShell.state().caseId === 'e2eCase0001' && CasesShell.state().tab === 'cand'", 20000)
          and tab.url == base + "cases?c=e2eCase0001#cand",
          "[A] /studio/?video= をブラウザで開くと /cases?c=…#cand に着いて、その配信の候補が開く: %s" % tab.url)
    check(wait_js(tab, "!!document.querySelector('#csPane .cd-panel #rvList .rv-mark-row[data-id=\"m1\"]')", 25000),
          "[A] 候補のパネルが /studio/ の API を読めた(マークの一覧。旧 Studio.state の確かめ)")
    check(bool(tab.evaluate("(document.querySelector('meta[name=\"ytt-token\"]') || {}).content")), "[A] 案件の画面も合言葉(ytt-token)を受け取っている")
    check(wait_js(tab, "document.querySelector('#ver') && document.querySelector('#ver').textContent === '%s'" % TX_VER, 15000),
          "[A] 案件の画面の版(全体で 1 つ): %s" % tab.evaluate("document.querySelector('#ver') && document.querySelector('#ver').textContent"))
    check_appnav(check, tab, base, "cases", "案件の画面")

    # 2c. 校正(#proof)は取り込んだ編集の部品(edhost)が文書を読む・カット(#cut)へ切り替わる(旧 /transcribe/ の画面の確かめの代わり)
    tab.goto(base + "cases?d=deadbeef0001#proof")
    check(wait_js(tab, "CasesShell.state().caseId === 'e2eCase0001' && CasesShell.state().tab === 'proof' && CasesShell.state().sel === 'd:deadbeef0001'"
                       " && typeof S === 'object' && S.docId === 'deadbeef0001' && document.querySelectorAll('#csPane #segs .seg').length === 2", 30000),
          "[A] /cases?d=…#proof は文書から案件を引いて、校正のパネルが /transcribe/ の API で文書の 2 行を出す: %s"
          % tab.evaluate("[CasesShell.state(), typeof S === 'object' && S.docId, document.querySelectorAll('#csPane #segs .seg').length,"
                         " (document.querySelector('#csPane') || {}).textContent.slice(0, 200)]"))
    tab.goto(base + "cases?d=deadbeef0001#cut")
    check(wait_js(tab, "CasesShell.state().tab === 'cut' && CasesShell.state().panel === 'cut'", 20000),
          "[A] /cases?d=…#cut はカット・パックのパネル: %s" % tab.evaluate("CasesShell.state()"))
    tab.close()


def _mounted_old_urls(cx):
    """[A] 2h. 古い画面の URL の転送(RS8 C4。表は src/app/redirects.py・/cases.html と /live/ は入口・/cut2resolve/ は取り込みの page_to)。
    転送を追わずに GET して 302 と Location を見る + /cut2resolve/?video= をブラウザで追って新しい案件の欄に入るところまで"""
    base, check, ctx, port = cx.base, cx.check, cx.ctx, cx.port
    q = lambda s: urllib.parse.quote(s, safe="")
    yt, missing = "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "C:\\x\\無い動画.mp4"
    clip = os.path.join(cx.tmp, "exports", "01_案件.mp4")   # seed_cases の文書 deadbeef0001 の元の動画
    table = [("/studio/?video=e2eCase0001", "/cases?c=e2eCase0001#cand"),
             ("/studio/?video=" + q("../x"), "/"),   # 案件の id の形でなければホーム
             ("/studio/?step=rank", "/#new"),
             ("/studio/?url=" + q(yt), "/#new?url=" + q(yt)),
             ("/studio/", "/"),
             ("/studio/index.html", "/"),
             ("/transcribe/?doc=deadbeef0001", "/cases?d=deadbeef0001"),
             ("/transcribe/?doc=" + q("../x"), "/"),
             ("/transcribe/?drill=1", "/cases?c=eval#proof"),
             ("/transcribe/?media=" + q(missing), "/#new?media=" + q(missing)),   # 文書の無い動画は新しい案件の欄へ
             ("/transcribe/?clip=" + q(clip), "/cases?d=deadbeef0001#proof"),   # 文書のある動画はその文書の校正へ
             ("/transcribe/", "/"),
             ("/cases.html", "/"),
             ("/cut2resolve/?video=" + q(missing), "/#new?media=" + q(missing)),   # ?video= は入口が 1 回で(引数なしは取り込みの page_to)
             ("/cut2resolve/", "/transcribe/")]
    got = [(path, http_get(port, path)) for path, _want in table]
    bad = [(path, res, want) for (path, res), (_p, want) in zip(got, table) if res != (302, want)]
    check(not bad, "[A] 古い URL はどれも 302 で表の行き先へ(%d 行): %s" % (len(table), bad))
    # /live/ は線 D の設定がオンのときだけ入口が受け持つ(オフは今までどおり 404)。オンをこの 1 回の要求の糸だけに見せて確かめる(見回りの糸には見せない)
    check(http_get(port, "/live/")[0] == 404, "[A] /live/ は線 D がオフなら 404")
    on_req = lambda: "process_request" in threading.current_thread().name
    with mock.patch.object(cx.srv.live, "enabled", on_req):
        live = [http_get(port, p) for p in ("/live/", "/live")]
    check(live == [(302, "/")] * 2, "[A] /live/ は線 D がオンならホームへ 302(以前の録画の画面): %s" % live)
    # ブラウザで転送を追う: /cut2resolve/?video= → /#new?media= = 新しい案件の引き出しが開いて、動画のパスが欄に入る
    tab = ctx.new_page()
    tab.on("pageerror", lambda e: cx.errors.append(str(e)))
    tab.goto(base + "cut2resolve/?video=" + q(missing))
    check(wait_js(tab, "location.pathname === '/' && location.hash.indexOf('#new?media=') === 0 && !document.getElementById('newDrawer').hidden"
                       " && !!document.getElementById('qPath') && document.getElementById('qPath').value.endsWith('無い動画.mp4')", 25000),
          "[A] /cut2resolve/?video= をブラウザで開くと新しい案件の引き出しが開き、動画のパスが欄に入る: %s" % tab.url)
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
    check(any(t == "校正で開く" and h.startswith("/cases?c=e2eCase0001&d=") and h.endswith("#proof") for t, h in acts),
          "[A] 切り抜きの操作は「校正で開く」(案件の画面へ。文書 ID で校正のタブ。B-1: 同じ動画の別の文書が開かないように): %s" % acts)
    case_doc = [h for t, h in acts if t == "校正で開く" and "e2eCase0001" in h][0].split("&d=")[1].split("#")[0]
    cols = pg.eval_on_selector_all(".pt-case-clips, .pt-case-tx, .pt-case-pack", "els => els.map(e => [e.className.split(' ').pop(), e.textContent])")
    check(any(c == "pt-case-clips" and t.startswith("切り抜き ") for c, t in cols) and any(c == "pt-case-tx" and t.startswith("校正 ") for c, t in cols),
          "[A] RS8 C3: 案件の行の列は 切り抜き / 校正 / パック: %s" % cols)
    # B-8(段1): 案件の行から、その配信をスタジオの ② 確認で開く。S-15(入口 0.42.0): 同じ窓で移る(target を付けない = 窓・タブを増やさない)
    sh = pg.eval_on_selector_all(".pt-case-studio a", "els => els.map(a => [a.textContent, a.getAttribute('href'), a.getAttribute('target')])")
    check(sh == [["案件の画面で開く", "/cases?c=e2eCase0001#cand", None]],
          "[A] 案件の行に「案件の画面で開く」(/cases?c= に案件の id・同じ窓で移る): %s" % sh)
    tab = ctx.new_page()   # この画面(pg)は下の確認で使うので、同じホームを別のタブで開いて押す
    tab.goto(cx.base)
    check(wait_js(tab, "!!document.querySelector('.pt-case-studio a')", 15000), "[A] 別のタブのホーム")
    tab.evaluate("document.querySelector('.pt-case').open = true")
    n_pages = len(ctx.pages)
    tab.click(".pt-case-studio a")
    tab.wait_for_url(lambda u: "/cases" in u, timeout=20000)
    check(wait_js(tab, "location.pathname === '/cases' && new URLSearchParams(location.search).get('c') === 'e2eCase0001' && !!document.getElementById('csRail')", 20000),
          "[A] 「案件の画面で開く」で案件の画面がその配信を開いた: %s" % tab.evaluate("[location.pathname, location.search, location.hash]"))
    check(len(ctx.pages) == n_pages, "[A] S-15: 「案件の画面で開く」は同じタブで移る(新しいタブを開かない): %d → %d" % (n_pages, len(ctx.pages)))
    tab.close()
    pg.select_option(".pt-case-status", "posted")
    check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('投稿済み') >= 0)", 10000), "[A] 状態を保存した(合言葉つきの POST)")
    pg.reload()
    check(wait_js(pg, "document.querySelector('.pt-case-status') && document.querySelector('.pt-case-status').value === 'posted'", 15000),
          "[A] 読み込み直しても状態が残る(案件ファイル)")
    # B-4: 投稿済み・見送りの案件は「次にやること」に出さない
    time.sleep(1.0)
    todo_hrefs = pg.eval_on_selector_all(".pt-todo-item .pt-todo-link", "els => els.map(a => a.getAttribute('href'))")
    check(not any(("d=" + case_doc) in h for h in todo_hrefs), "[A] 投稿済みの案件の文書は「やること」に出ない: %s" % todo_hrefs)
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
    check(wait_js(pg, "[...document.querySelectorAll('.pt-todo-item .pt-todo-link')].some(a => a.getAttribute('href').indexOf('d=%s') >= 0)" % case_doc, 15000),
          "[A] 状態を戻すと、また「やること」に出る")
    todo = pg.eval_on_selector_all(".pt-todo-item .pt-todo-link", "els => els.map(a => [a.querySelector('.pt-todo-pill').textContent, a.getAttribute('href')])")
    check(any(p == '校正待ち' and h.startswith('/cases?c=e2eCase0001&d=' + case_doc) and h.endswith('#proof') for p, h in todo),
          "[A] やることに校正待ち(1/2行のまま)が出て、案件の画面の校正のタブへ文書 ID で直接リンクする: %s" % todo)
    subs = pg.eval_on_selector_all(".pt-todo-item", "els => els.map(e => [e.querySelector('.pt-todo-title').textContent, e.querySelector('.pt-todo-sub').textContent])")
    check(any(t.startswith("校正待ち ") and "校正 " in s for t, s in subs), "[A] やることは種類ごとの件数(校正待ち n 本): %s" % subs)
    # E2 finding 2: 校正がまだ済んでいない(proofed < rows)文書は、パックの有無に関わらず「パック待ち」を重ねて出さない
    # (以前は !it.pack だけで判定していて、校正中の文書にも重複して出ていた)
    check(not any(p in ('パック待ち', '作り直し') for p, h in todo),
          "[A] 校正がまだ済んでいない文書は「パック待ち」を二重に出さない: %s" % todo)

    # 2f. 単体の文字起こし(どの配信にも紐づかない文字起こし)。「編集」の文書の一覧と突き合わせて詳しく見せる
    check(wait_js(pg, "!document.getElementById('unlinkedGroup').hidden && !document.getElementById('unlinkedHead').hidden", 10000), "[A] 単体の文字起こしの1行とまとまりが出た")
    check(pg.text_content("#unlinkedCount").strip() == "1件", "[A] 単体の文字起こしの件数(ホームの数): %s" % pg.text_content("#unlinkedCount"))
    link = pg.get_attribute("#unlinkedOpen", "href")
    check(link == "/cases?c=orphan#proof", "[A] 「案件の画面で見る」は仮の案件「どの案件にも入らない文字起こし」を開く(段5 5-1・B-5 → RS8 C3): %s" % link)
    check(pg.evaluate("document.getElementById('unlinkedGroup').open") is False, "[A] 単体の文字起こしのまとまりは既定で閉じている")
    pg.click("#unlinkedGroup summary")
    check(wait_js(pg, "!!document.querySelector('.pt-doc')", 10000), "[A] 単体の文字起こしの行が出た")
    docTx = pg.text_content(".pt-doc-tx")
    check("校正 0/1行" in docTx and "パック まだ" in docTx, "[A] 単体の文字起こしも校正・パックの進み具合を見せる: %s" % docTx)
    open_href = pg.get_attribute(".pt-doc-open", "href")
    check(bool(open_href) and open_href.startswith("/cases?d=") and open_href.endswith("#proof"), "[A] 単体の文字起こしも「校正で開く」(案件の画面へ文書 ID で): %s" % open_href)
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
    check(wait_js(pg, "/^ch(\\s|$)/.test(document.querySelector('#list .pt-case .pt-case-sub').textContent)", 5000),
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
    # RS8 C3: やることは種類ごとの件数なので、行を個別には隠さない(隠した案件・見送りの案件は数えない = 案件の非表示がそのまま効く)
    check(pg.evaluate("document.querySelectorAll('#todoList .pt-todo-hide').length") == 0 and pg.evaluate("document.getElementById('todoHidden').hidden"),
          "[A] 非表示: やることの件数の行に隠すボタンは無い(案件を隠すと件数から外れる)")
    real = [e for e in errors if "Failed to load resource" not in e and "ERR_CONNECTION_REFUSED" not in e]
    check(not real, "[A] 一覧の道具を操作しても画面のエラーなし: %s" % real[:3])


NEXT_KINDS = {"採用待ち": 0, "校正待ち": 1, "パック待ち": 2, "失敗": 3}   # やることの並び(RS8 C3。brief 2-1)


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


def _mounted_new_case_and_ops(cx):
    """[A] 2j. RS8 C3: 新しい案件の引き出し(スタジオ ① のつなぎ cases-panels/new.js・開いたときに初めて読む)・/?url=…#new・
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
    check(r.evaluate("document.querySelectorAll('#opsBox > .pt-ops-body > details').length") == 5, "[A] 2j: 運用の枠の中は 受付・バックアップ・記録・編集の精度と学習・詳しく の 5 つ")
    check(r.evaluate("document.getElementById('accOut').textContent === '' && document.getElementById('lnList').textContent === ''"), "[A] 2j: 精度と学習は開くまで読まない")
    r.evaluate("document.getElementById('editOpsBox').open = true")
    check(wait_js(r, "document.getElementById('opsBox').open === true", 5000), "[A] 2j: 中の欄を開くと運用の枠も開く")
    check(wait_js(r, "/校正済みの行がまだありません|文字誤り率/.test(document.getElementById('accOut').textContent)"
                     " && /候補はありません|学習します|誤/.test(document.getElementById('lnList').textContent) && !document.querySelector('#editOpsBox .pt-edit-err')", 20000),
          "[A] 2j: 認識精度の測定・修正から学習した候補が読めた: %s" % r.evaluate("[document.getElementById('accOut').textContent.slice(0, 60), document.getElementById('lnList').textContent.slice(0, 60)]"))
    r.select_option("#accScope", "eval")
    check(wait_js(r, "/校正済みの行がまだありません|文字誤り率/.test(document.getElementById('accOut').textContent) && !document.querySelector('#editOpsBox .pt-edit-err')", 10000), "[A] 2j: 対象を変えて測り直せる")
    r.close()

    # 学習した候補の「登録」: 置換辞書(replacements)に「|誤|=>正」の 1 行・用語集(glossary)に正を足す。保存は最上位のキーだけの patch(別の窓の変更を消さない)
    s = ctx.new_page()
    s.on("pageerror", lambda e: cx.errors.append(str(e)))
    puts = []

    def settings_route(route):
        if route.request.method == "PUT":
            puts.append(json.loads(route.request.post_data or "{}"))
            return route.fulfill(json={"ok": True})
        return route.fulfill(json={"replacements": "", "glossary": "既存", "learnIgnore": []})
    s.route("**/transcribe/api/learned*", lambda route: route.fulfill(json={"items": [{"wrong": "ホシミ", "right": "星見", "count": 3}], "docs": 1, "lines": 3}))
    s.route("**/transcribe/api/settings", settings_route)
    s.goto(cx.base)
    s.evaluate("document.getElementById('editOpsBox').open = true")
    check(wait_js(s, "!!document.querySelector('#lnList .ln [data-act=lnadd]')", 15000), "[A] 2j: 学習した候補の行が出る")
    s.click("#lnList [data-act=lnadd]")
    check(wait_js(s, "true", 100) and wait_routed(s, lambda: len(puts) == 1, 10), "[A] 2j: 「登録」で設定を 1 回だけ保存する: %s" % puts)
    patch = (puts[0] if puts else {}).get("patch") or {}
    check(list(puts[0].keys()) == ["patch"] and patch.get("replacements") == "|ホシミ|=>星見" and patch.get("glossary") == "既存\n星見" and "learnIgnore" not in patch,
          "[A] 2j: 置換辞書に「|誤|=>正」(カタカナの語は単語の途中に当てない形)・用語集に正・patch の形: %s" % puts)
    s.close()
    _new_case_rank(cx)
    _new_case_queue_narrow(cx)   # 解析の順番待ちに 1 本入れるので最後に(上の ?url= の場面は順番待ちが空のことを見る)


def _new_case_search_settings(cx):
    """[A] 2j-2. 新しい案件の末尾の「探す設定」(RS8 C4。スタジオの ⚙ から移した): API キーの保存と削除(札が変わる)・事務所の登録(rank.js の
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
NO_HSCROLL_JS = ("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
                 " && document.getElementById('newDrawer').scrollWidth <= document.getElementById('newDrawer').clientWidth + 1")


def _watch_errors(p, errs):
    p.on("pageerror", lambda e: errs.append(str(e)))
    p.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)   # CSP の違反もここに入る


def _new_case_rank(cx):
    """[A] 2j-3. 新しい案件の ① 配信を探す(旧スタジオ e2e_ui.py の ① の要点。RS8 C4 で引き出しへ): 登録した事務所だけにチェック・外したのは残る /
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
    want = {"hololive": True, "nijisanji": True, "vspo": False, "neoporte": False}
    check(wait_js(p, "%s.length === 4" % AGC_JS, 25000) and dict(p.evaluate(AGC_JS)) == want,
          "[A] 2j-3: チャンネルを登録した事務所だけにチェックが入る: %s" % p.evaluate(AGC_JS))
    p.uncheck('#agChecks .agc[value="nijisanji"]')
    p.reload()
    check(wait_js(p, "%s.length === 4" % AGC_JS, 25000) and dict(p.evaluate(AGC_JS)) == dict(want, nijisanji=False),
          "[A] 2j-3: 自分で外した事務所は、読み込み直しても外れたまま: %s" % p.evaluate(AGC_JS))
    p.check('#agChecks .agc[value="nijisanji"]')
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
    """2j-3 のまとめて実行: 入口の start-new・autorun は偽物。送る中身(items の id と題名・top)・始めた行の印・チェックできない"""
    check = cx.check
    check(p.is_visible("#rkAuto"), "[A] 2j-3: 選んだ配信の「まとめて実行」が出る(ホームの中)")
    vid = p.get_attribute("#results tr[data-vid] .pk >> nth=0", "data-id")
    sent = []

    def fake_runs():
        return [{"id": "e2erun00002", "kind": "video", "videoId": vid, "docId": None, "mode": "full", "modeLabel": "全部", "title": "検索の配信", "state": "queued",
                 "created": int(time.time() * 1000), "finished": None, "message": "", "error": "", "steps": []}] if sent else []

    def fake_start(route):
        sent.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(json={"runs": fake_runs(), "skipped": []})
    p.route("**/api/autorun/start-new", fake_start)
    p.route("**/api/autorun", lambda route: route.fulfill(json={"runs": fake_runs(), "past": [], "modes": {}}))
    p.click("#rkAuto > summary")
    check(p.is_enabled("#rkAutoGo") and "1 本" in (p.text_content("#rkAutoGo") or ""), "[A] 2j-3: 選んだ本数が「まとめて実行」のボタンに出る: %s" % p.text_content("#rkAutoGo"))
    p.fill("#rkAutoTop", "2")
    p.click("#rkAutoGo")
    check(wait_js(p, "/まとめて実行の順番待ち/.test((document.querySelector('#results tr[data-vid=\"%s\"] .chip') || {}).textContent || '')" % vid, 10000),
          "[A] 2j-3: 始めた配信の行に「まとめて実行の順番待ち」の印")
    it = (sent[0].get("items") or [{}])[0] if sent else {}
    check(it.get("id") == vid and it.get("title") and sent[0].get("top") == 2, "[A] 2j-3: 選んだ配信(id と題名)と採用する数(top)を入口に送る: %s" % (sent[:1],))
    check(p.text_content("#pickN") == "0" and p.is_disabled('#results tr[data-vid="%s"] .pk' % vid), "[A] 2j-3: 始めた配信は選択から外れ、順番待ちの間はチェックできない")
    p.unroute("**/api/autorun/start-new")
    p.unroute("**/api/autorun")


def _new_case_queue_narrow(cx):
    """[A] 2j-4. 新しい案件の「URL から入れる」(旧スタジオ e2e_ui.py の check_queue の要点): 「解析に追加」で順番待ち → 疑似の解析が終わると「確認する」→
    案件の画面の候補へ / 失敗は「何が起きたか + どうすればいいか」/ 幅 390 で ① が横にはみ出さない(?url= を欄に入れるだけは 2j で確かめた)"""
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
    raw = "音声を取得できませんでした: ERROR: [youtube] abcdefghijk: Sign in to confirm your age"
    p.route("**/api/queue", lambda route: route.fulfill(json={"items": [{"qid": "e1", "videoId": "abcdefghijk", "kind": "youtube", "title": "失敗した配信", "channel": "星見ルナ",
                                                                         "status": "error", "phase": "失敗", "progress": 0, "error": raw, "chat": None, "marks": 0,
                                                                         "finishedAt": int(time.time() * 1000)}], "running": False, "max": 10}))
    check(wait_js(p, "!!document.querySelector('#qList .q-item[data-status=\"error\"]') && /年齢制限/.test(document.querySelector('#qList .q-err b').textContent)", 15000)
          and "年齢制限" in (p.text_content("#qList .q-err b") or "")
          and p.is_visible("#qList .q-how") and p.text_content("#qList .q-raw code") == raw and not p.is_visible("#qList .q-raw code"),
          "[A] 2j-4: 解析の失敗は「何が起きたか」+「どうすればいいか」・元のメッセージは閉じた欄に: %s" % p.text_content("#qList .q-err"))
    p.unroute("**/api/queue")
    check(wait_js(p, "!!document.querySelector('#qList [data-act=\"review\"]')", 15000), "[A] 2j-4: 偽物を外すと終わった解析の「確認する」に戻る")
    p.click('#qList [data-act="review"]')
    p.wait_for_url(lambda u: "/cases?c=abcdefghijk" in u and u.endswith("#cand"), timeout=20000)
    check(True, "[A] 2j-4: 「確認する」は案件の画面の候補(/cases?c=…#cand)へ: %s" % p.url)
    p.close()
    m = ctx.new_page()
    _watch_errors(m, errs)
    m.set_viewport_size({"width": 390, "height": 844})
    m.goto(cx.base + "#new")
    check(wait_js(m, "!!document.querySelector('#newDrawer #rkCond') && !!document.querySelector('#newDrawer #qUrls')", 25000) and wait_js(m, NO_HSCROLL_JS, 3000),
          "[A] 2j-4: 幅 390 で新しい案件の ① が横にはみ出さない: %s" % m.evaluate("[document.documentElement.scrollWidth, document.getElementById('newDrawer').scrollWidth,"
                                                                   " document.getElementById('newDrawer').clientWidth]"))
    m.close()
    check(not errs, "[A] 2j-4: URL から入れる・狭い幅で画面のエラーなし: %s" % errs[:3])


def _next_todo(cx):
    """S-6: 次にやることに 文字起こし待ち・書き出し待ち・確認前の候補(スタジオの ② へ)と並び / S-26: 紐づかない文書の副題"""
    check, pg = cx.check, cx.pg
    if pg.is_visible("#todoMore") and pg.text_content("#todoMore").startswith("すべて見る"):
        pg.click("#todoMore")
    check(wait_js(pg, "[...document.querySelectorAll('.pt-todo-pill')].some(p => p.textContent === '採用待ち')", 15000), "[A] RS8 C3: やることに採用待ちが出た")
    todo = pg.eval_on_selector_all("#todoList .pt-todo-item", "els => els.map(e => [e.querySelector('.pt-todo-pill').textContent, "
                                   "e.querySelector('.pt-todo-link').getAttribute('href'), e.querySelector('.pt-todo-sub').textContent])")
    # 採用待ち = 候補の確認前の配信(見送りは数えない)。押すと、いちばん古い 1 件の案件の画面の候補(#cand)へ。件数は案件の todoSum の合計(画面で数えない)
    cases_api = pg.evaluate("fetch('/api/cases', {cache: 'no-store'}).then(r => r.json())")
    first_adopt = (cases_api.get("todoFirst") or {}).get("adopt") or {}
    check(any(p == "採用待ち" and h == "/cases?c=%s#cand" % first_adopt.get("case") and "候補" in s for p, h, s in todo) and first_adopt.get("case"),
          "[A] RS8 C3: 採用待ち → いちばん古い配信の案件の画面の候補へ(todoFirst): %s / %s" % (todo, first_adopt))
    adopt_n = sum(c.get("todoSum", {}).get("adopt", 0) for c in cases_api["cases"] if c.get("status") not in ("posted", "skipped") and not c.get("gone"))
    check(any(p == "採用待ち" and ("%d 個" % adopt_n) in pg.evaluate("[...document.querySelectorAll('.pt-todo-item')].find(e => e.querySelector('.pt-todo-pill').textContent === '採用待ち').querySelector('.pt-todo-title').textContent") for p, h, s in todo),
          "[A] RS8 C3: 採用待ちの件数 = 案件の todoSum の合計(%d)" % adopt_n)
    order_api = pg.evaluate("fetch('/api/cases', {cache: 'no-store'}).then(r => r.json()).then(j => j.todoOrder)")
    check(order_api == ["proof", "pack", "transcribe", "export", "review"],
          "[A] M1: 案件の一覧が並びの表(todoOrder)を返す = 上の一覧と案件の行のボタンが同じ順(cases.py の TODO_ORDER): %s" % order_api)
    ranks = [NEXT_KINDS[p] for p, h, s in todo if p in NEXT_KINDS]
    check(ranks == sorted(ranks), "[A] RS8 C3: 並びは 採用待ち → 校正待ち → パック待ち → 失敗: %s" % [p for p, h, s in todo])
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
    check(got["e2eNext0001"] == ["A", "btn small ui-next-btn pt-case-next", "/cases?c=e2eNext0001#cand", "候補の確認 3個", False, None],
          "[A] S-18: 候補の確認のボタン(案件の画面の候補へ): %s" % got["e2eNext0001"])
    check(got["e2eNext0002"] and got["e2eNext0002"][2:4] == ["/cases?c=e2eNext0002#cand", "文字起こし 1本"], "[A] S-18: 文字起こしのボタン: %s" % got["e2eNext0002"])
    check(got["e2eList0000"] and got["e2eList0000"][2:4] == ["/cases?c=e2eList0000#cand", "書き出し 1本"], "[A] S-18: 書き出しのボタン: %s" % got["e2eList0000"])
    c0 = got["e2eCase0001"]
    check(bool(c0) and c0[1] == "btn small ui-next-btn pt-case-next" and (c0[2] or "").startswith("/cases?c=e2eCase0001&d=deadbeef0001") and (c0[2] or "").endswith("#proof")
          and c0[3] == "校正 1本", "[A] S-18: 校正のボタンは案件の画面の校正のタブへ(文書 ID で): %s" % c0)
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
    p2.wait_for_url(lambda u: "/cases" in u, timeout=20000)
    check(len(ctx.pages) == n_pages, "[A] S-18・S-15: ボタンを押すと同じタブのまま案件の画面へ移る: %s" % p2.url)
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
    check(p3.text_content("#emptyStudio") == "新しい案件を始める" and p3.get_attribute("#emptyStudio", "href") is None,
          "[A] S-13: 「新しい案件を始める」(引き出しで配信を探す・URL から入れる。RS8 C3)")
    check(wait_js(p3, "!document.getElementById('intakeBox').hidden && !!document.getElementById('emptyIntake')", 10000), "[A] S-13: 「依頼の受付を設定する」が出る")
    check(wait_js(p3, "!document.getElementById('todoEmpty').hidden && document.getElementById('todoEmptyBtn').textContent === '新しい案件を始める'", 10000)
          and "ここに出ます" in p3.text_content("#todoEmpty"), "[A] M5: やることが 0 件のときも 2 文 + [新しい案件を始める]: %s" % p3.text_content("#todoEmpty"))
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
    check(g and g[0] is False and g[1] is True and g[2] is False and "スタジオから消えた配信" in g[3] and "入れ直す" in g[3] and g[4] and g[5] and g[6],   # RS8 C3: 案件の画面の校正・パックは開けるので、リンクは消えた配信にも出す
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
    p6.wait_for_url(lambda u: "/cases" in u and "c=e2eNext0001" in u and u.endswith("#cand"), timeout=20000)
    check(True, "[A] M2: [候補の確認へ] は案件の画面の候補でその配信を開く: %s" % p6.url)
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


def _mounted_theme_narrow(cx):
    """[A] 7. テーマ・8. 狭い画面(/cases.html の転送は 2h の表へ移した)"""
    base, check, ctx, pg, shots = cx.base, cx.check, cx.ctx, cx.pg, cx.shots
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
        from ytt import layout as _layout
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
