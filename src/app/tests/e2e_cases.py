"""案件の画面(/cases。部品は src/app/ui/cases/。RS8 C1 = 殻)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.10 src/app/tests/e2e_cases.py
入口(server.py)は e2e_settings.py と同じ形で動かす(ツールは取り込まない)。④ の案件の一覧(cases_mod.snapshot)は見本のデータに差し替え、
② の掲示板(srv.board)には本物の口(upsert)でジョブを載せる。
見るもの: 引数なし・見つからない・読めないときの空の状態 / 左の一覧(候補 + 切り抜き 1 本 1 行・進み具合の札)/ タブ(候補 | 校正・カット・パック)と URL(?c=&d=#tab・#tx #pack の読み替え・d だけで開く)/
Alt+1・Alt+2・Shift+N(次の未校正の切り抜き。入力中は効かない)/ ② の status の問い合わせ(動いていれば 2 秒・止まれば 15 秒・札)/ 仮の案件 eval /
ヘッダー(appnav・版・設定)/ 幅 390 で横にはみ出さない / コンソールにエラーが無い。"""
import os
import re
import sys
import tempfile
import threading
import time
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(SRC, "home"))
sys.path.insert(0, os.path.join(SRC, "home", "tests"))
if SRC not in sys.path:
    sys.path.append(SRC)
from app import server as L  # noqa: E402
from test_launch import free_ports  # noqa: E402


def wait_js(pg, expr, timeout=15000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.1)
    return False


def tx(tid, segs, proofed, title=""):
    return {"id": tid, "title": title or tid, "segments": segs, "proofed": proofed, "cut": 0, "updatedAt": 1}


def fixture(root):
    """④ GET /api/cases の見本(C0 の形: caseKind・root・切り抜きの state・virtual = 仮の案件)"""
    clip = lambda mid, start, end, t, state, pack=None: {"markId": mid, "label": "笑い", "start": start, "end": end, "path": os.path.join(root, mid + ".mp4"),
                                                         "exists": True, "transcript": t, "transcripts": 1 if t else 0, "transcriptIds": [t["id"]] if t else [],
                                                         "pack": pack, "auto": None, "state": state}
    v1 = {"id": "v1", "kind": "", "caseKind": "stream", "root": root, "title": "【雑談】テストの配信", "channel": "配信者 A", "streamedAt": 1760000000000,
          "marks": {"total": 8, "adopted": 1, "exported": 4, "candidates": 3},
          "clips": [clip("m1", 760, 812, tx("a0000000000a", 10, 10), "packed", {"textplus": True, "updatedAt": 1}),
                    clip("m2", 2285, 2332, tx("a0000000000b", 10, 4), "proofing"),
                    clip("m3", 3771, 3829, tx("a0000000000c", 8, 0), "proofing"),
                    clip("m4", 4814, 4855, None, "none")]}
    v2 = {"id": "v2", "kind": "", "caseKind": "stream", "root": "", "title": "まだ切り抜きの無い配信", "marks": {"total": 2, "candidates": 2}, "clips": []}
    ev = {"id": "eval", "kind": "", "caseKind": "eval", "root": "", "title": "評価用",
          "clips": [{"markId": "", "label": "評価 01", "start": None, "end": None, "transcript": tx("e0000000000a", 5, 5, "評価 01"), "state": "proofed"},
                    {"markId": "", "label": "評価 02", "start": None, "end": None, "transcript": tx("e0000000000b", 5, 0, "評価 02"), "state": "proofing"}]}
    orphan = {"id": "orphan", "kind": "", "caseKind": "orphan", "root": "", "title": "どの案件にも入らない文字起こし", "clips": []}
    return {"cases": [v1, v2], "virtual": [ev, orphan], "unlinked": [], "todoOrder": []}


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-cases-ui-")
    root = os.path.join(tmp, "案件1")
    os.makedirs(root)
    broken = {"on": False}

    def snapshot(_root, env=None):
        if broken["on"]:
            raise RuntimeError("読めない(テスト)")
        return fixture(root)

    patches = [mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")}), mock.patch.object(L.cases_mod, "snapshot", snapshot)]
    for p in patches:
        p.start()
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=lambda m: None, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % port
    errors, bad_status = [], []

    def st():
        return pg.evaluate("CasesShell.state()")

    def rail_keys():
        return pg.evaluate("[...document.querySelectorAll('#csRail [data-cs-key]')].map(b => b.dataset.csKey)")

    def pill(key):
        return pg.evaluate("(document.querySelector('#csRail [data-cs-key=\"%s\"] .pill')||{}).textContent || ''" % key)

    def tabs():
        return pg.evaluate("[...document.querySelectorAll('#csTabs [data-cs-tab]')].map(b => b.dataset.csTab + (b.getAttribute('aria-selected') === 'true' ? '*' : ''))")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                pg = ctx.new_page()
                # カット・パックのパネル(C2c)は /transcribe/ の cut.js・pack-tab.js と編集の API を読みに行く。この確かめは編集を載せないので空で返す(404 を出さない)
                ctx.route(re.compile(r'.*/(transcribe|cut2resolve)/.*'), lambda route: route.fulfill(
                    status=200, content_type='application/javascript' if route.request.url.split('?')[0].endswith('.js') else 'application/json',
                    body='' if route.request.url.split('?')[0].endswith('.js') else '{}'))
                # 確かめると効く物 n 件(V1 確かめる V3): 入口の GET api/check/next?c=<案件>&n=0 の total を、この確かめの中では見本で返す
                nx_urls = []
                ctx.route(re.compile(r'.*/api/check/next.*'), lambda route: (nx_urls.append(route.request.url), route.fulfill(
                    status=200, content_type='application/json', body='{"total": 3, "cards": [], "goal": null, "goals": {}}'))[1])
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.on("response", lambda r: bad_status.append("%s %s" % (r.status, r.url)) if r.status >= 400 else None)

                # 1. 引数なし: 空の状態(2 文 + ホームへのボタン)・ヘッダー
                pg.goto(base + "cases")
                check(wait_js(pg, "!document.querySelector('#csEmpty').hidden"), "引数なしは空の状態")
                check("案件が選ばれていません" in pg.text_content("#csEmpty") and pg.get_attribute("#csEmpty a.btn", "href") == "./", "空の状態の文とホームへのボタン")
                check(wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')"), "版が出る: %r" % pg.text_content("#ver"))
                check(pg.evaluate("!!document.querySelector('.ui-header nav[data-ui-appnav]') && !!document.querySelector('.ui-header-actions [data-ui-settings]')"), "ヘッダーに appnav と設定")
                check(pg.is_disabled("#csNext") and bool(pg.get_attribute("#csNext", "title")), "案件が無いとき「次の未校正の切り抜き」は押せない + 理由")

                # 2. ?c=v1#proof: 左の一覧・最初の未校正・タブ・URL
                pg.goto(base + "cases?c=v1#proof")
                check(wait_js(pg, "document.querySelectorAll('#csRail [data-cs-key]').length === 5"), "左の一覧は 候補 + 切り抜き 4 本: %s" % rail_keys())
                check(wait_js(pg, "!document.querySelector('#csCheck').hidden && document.querySelector('#csCheck').textContent === '確かめると効く物 3 件'"), "案件の頭に「確かめると効く物 3 件」: %s" % pg.text_content("#csCheck"))
                check(pg.get_attribute("#csCheck", "href") == "check?c=v1&back=cases" and any("c=v1" in u and "n=0" in u for u in nx_urls), "押すと /check?c=<案件>&back=cases・数は next?c=&n=0 から: %s %s" % (pg.get_attribute("#csCheck", "href"), nx_urls[:2]))
                check(rail_keys() == ["cand", "d:a0000000000a", "d:a0000000000b", "d:a0000000000c", "m:m4"], "並び: %s" % rail_keys())
                check(pg.text_content("#csTitle") == "【雑談】テストの配信" and pg.title() == "動画編集ツール — 【雑談】テストの配信", "題名")
                s = st()
                check(s["sel"] == "d:a0000000000b" and s["tab"] == "proof" and s["panel"] == "proof", "#proof は最初の未校正の切り抜き(a0000000000b)の校正: %s" % s)
                check(pg.evaluate("location.search + location.hash") == "?c=v1&d=a0000000000b#proof", "URL に c・d・#proof: %s" % pg.evaluate("location.search + location.hash"))
                check(tabs() == ["proof*", "cut"], "切り抜きのタブは 校正・カット・パック: %s" % tabs())
                check(pill("d:a0000000000a") == "パック済み" and pill("d:a0000000000b").startswith("校正中") and pill("d:a0000000000c") == "未校正" and pill("m:m4") == "文字起こし前",
                      "札: %s / %s / %s / %s" % (pill("d:a0000000000a"), pill("d:a0000000000b"), pill("d:a0000000000c"), pill("m:m4")))
                check(pg.evaluate("document.querySelector('#csRail [aria-current=\"true\"]').dataset.csKey") == "d:a0000000000b", "選んだ行に aria-current")
                # 校正のパネル(C2b)は編集の部品を transcribe/ から読む。この入口は編集を取り込まないので、何が / 次に + もう一度(中身の確かめは e2e_cases_proof.py)
                check(wait_js(pg, "!!document.querySelector('#csPane [data-pf-fail] [data-pf-retry]')") and "取り込まれていません" in pg.text_content("#csPane [data-pf-fail]"), "校正のパネル: 編集が無いときは案内ともう一度")
                check(wait_js(pg, "['Alt+1', 'Alt+2', 'Shift+N'].every(k => !!document.querySelector('.ui-keybar [data-k=\"' + k + '\"]'))"), "下の帯に殻のキー")

                # 3. キー: Alt+2 / Alt+1 / Shift+N(入力中は効かない)
                pg.keyboard.press("Alt+2")
                check(wait_js(pg, "CasesShell.state().tab === 'cut'") and pg.evaluate("location.hash") == "#cut" and st()["panel"] == "cut", "Alt+2 でカット・パック: %s" % st())
                pg.keyboard.press("Alt+1")
                check(wait_js(pg, "CasesShell.state().tab === 'proof'"), "Alt+1 で校正")
                pg.keyboard.press("Shift+N")
                check(wait_js(pg, "CasesShell.state().sel === 'd:a0000000000c'") and pg.evaluate("location.search") == "?c=v1&d=a0000000000c", "Shift+N で次の未校正(a0000000000c): %s" % st())
                pg.click("#csNext")
                check(wait_js(pg, "CasesShell.state().sel === 'd:a0000000000b'"), "ボタンでも次へ(末尾から先頭へ回る): %s" % st())
                pg.evaluate("(() => { const i = document.createElement('input'); i.id = 'tmpIn'; i.setAttribute('aria-label', 'test'); document.querySelector('#main').appendChild(i); i.focus(); })()")
                pg.keyboard.press("Shift+N")
                time.sleep(0.3)
                check(st()["sel"] == "d:a0000000000b", "入力中の Shift+N は効かない")
                pg.evaluate("document.querySelector('#tmpIn').remove()")

                # 4. 候補を選ぶ: タブは 候補だけ・URL に d が無い
                pg.click("#csRail [data-cs-key=cand]")
                check(wait_js(pg, "CasesShell.state().tab === 'cand'") and tabs() == ["cand*"], "候補のタブ: %s" % tabs())
                check(pg.evaluate("location.search + location.hash") == "?c=v1#cand", "URL: %s" % pg.evaluate("location.search + location.hash"))
                # 候補のパネル(C2a)はスタジオの studio/review.js を読む。この入口はスタジオを取り込まないので、読めない案内(何が / 次に + もう一度)が出る
                # (中身の確かめは e2e_cases_cand.py)。この 404 は最後に除く
                check(wait_js(pg, "!!document.querySelector('#csPane [data-cd-status] [data-cd-retry]')"), "候補のパネル: 部品を読めないときは案内ともう一度")
                pg.click("#csRail [data-cs-key='m:m4']")
                check(wait_js(pg, "CasesShell.state().sel === 'm:m4'") and pg.evaluate("location.search") == "?c=v1&m=m4", "文字起こし前の切り抜きは m=: %s" % pg.evaluate("location.search"))

                # 5. ② の status: 動いているジョブの札・2 秒 → 終われば 15 秒・終わったら ④ を読み直す
                check(wait_js(pg, "document.body.dataset.csPoll === '15000'"), "止まっている間は 15 秒ごと: %s" % pg.evaluate("document.body.dataset.csPoll"))
                pg.click("#csRail [data-cs-key='d:a0000000000c']")
                job = {"id": "tx:job1", "kind": "transcribe", "state": "running", "case": root, "target": {"docId": "a0000000000c"}, "progress": 0.4,
                       "title": "文字起こし", "phase": "認識中", "canCancel": True}
                srv.board.upsert(job)
                other = dict(job, id="tx:job2", case=os.path.join(tmp, "ほかの案件"), target={"docId": "a0000000000b"})
                srv.board.upsert(other)
                pg.evaluate("CasesShell.poll()")   # 15 秒を待たずに今問い合わせる(画面に戻ったときと同じ)
                check(wait_js(pg, "((document.querySelector('#csRail [data-cs-key=\"d:a0000000000c\"] .pill')||{}).textContent||'').includes('40%')", 20000), "動いているジョブの札: %r" % pill("d:a0000000000c"))
                check(not pill("d:a0000000000b").startswith("文字起こし"), "ほかの案件のジョブは載らない: %r" % pill("d:a0000000000b"))
                check(wait_js(pg, "document.body.dataset.csPoll === '2000'"), "動いている間は 2 秒ごと: %s" % pg.evaluate("document.body.dataset.csPoll"))
                srv.board.upsert(dict(job, state="done", progress=1.0, canCancel=False, finishedAt=int(time.time() * 1000)))
                check(wait_js(pg, "document.body.dataset.csPoll === '15000'", 10000), "終わったら 15 秒へ戻る")
                check(pill("d:a0000000000c") == "未校正", "終わったら進み具合の札へ戻る: %r" % pill("d:a0000000000c"))

                # 6. d だけ・#tx・#pack の読み替え
                pg.goto(base + "cases?d=a0000000000c#tx")
                check(wait_js(pg, "CasesShell.state().sel === 'd:a0000000000c'") and st()["caseId"] == "v1" and st()["tab"] == "proof", "d だけで案件を引く・#tx は校正: %s" % st())
                check(pg.evaluate("location.search + location.hash") == "?c=v1&d=a0000000000c#proof", "URL を c つきに直す: %s" % pg.evaluate("location.search + location.hash"))
                pg.goto(base + "cases?c=v1&d=a0000000000a#pack")
                check(wait_js(pg, "CasesShell.state().tab === 'cut'") and st()["sel"] == "d:a0000000000a", "#pack はカット・パック: %s" % st())
                pg.goto(base + "cases?c=v1")
                check(wait_js(pg, "CasesShell.state().sel === 'cand'") and st()["tab"] == "cand", "タブの指定が無ければ一覧の先頭(候補): %s" % st())

                # 7. 仮の案件 eval(候補なし)・切り抜きの無い案件・見つからない
                pg.goto(base + "cases?c=eval")
                check(wait_js(pg, "CasesShell.state().caseId === 'eval'") and rail_keys() == ["d:e0000000000a", "d:e0000000000b"] and tabs() == ["proof*", "cut"], "eval は候補なし・文書 2 本: %s %s" % (rail_keys(), tabs()))
                check("仮の案件" in pg.text_content("#csSub"), "仮の案件と分かる: %r" % pg.text_content("#csSub"))
                pg.click("#csRail [data-cs-key='d:e0000000000b']")
                check(wait_js(pg, "document.querySelector('#csNext').disabled") and "ほかの未校正" in pg.get_attribute("#csNext", "title"), "ほかに未校正が無ければ押せない + 理由")
                pg.goto(base + "cases?c=v2")
                check(wait_js(pg, "CasesShell.state().sel === 'cand'") and "まだ書き出した切り抜きはありません" in pg.text_content("#csRail"), "切り抜きの無い配信は候補だけ + 案内")
                pg.goto(base + "cases?c=nope")
                check(wait_js(pg, "!document.querySelector('#csEmpty').hidden") and "見つかりません" in pg.text_content("#csEmpty"), "見つからない案件")

                # 8. 読めない(④ が 500)→ 何が・次に + もう一度
                broken["on"] = True
                pg.goto(base + "cases?c=v1")
                check(wait_js(pg, "!!document.querySelector('[data-cs-fail]')") and pg.is_visible("#csRetry"), "読めないときは失敗の文ともう一度")
                broken["on"] = False
                pg.click("#csRetry")
                check(wait_js(pg, "CasesShell.state().caseId === 'v1'"), "もう一度で開ける")
                bad_status[:] = [u for u in bad_status if not u.startswith("500 ") or "/api/cases" not in u]   # わざと起こした 500
                errors[:] = [e for e in errors if "status of 500" not in e]

                # 9. 候補を開いているときに #proof へ(同じ文書の中の移動)= 最初の未校正の切り抜き
                pg.goto(base + "cases?c=v1#proof")
                check(wait_js(pg, "CasesShell.state().sel === 'd:a0000000000b' && CasesShell.state().tab === 'proof'"), "#cand → #proof で最初の未校正へ: %s" % st())
                # 9b. 引数なし(ヘッダーの「案件」)は、このブラウザで前に開いた案件を開く(RS8 C4。localStorage 'ytt-cases-last')
                pg.goto(base + "cases")
                check(wait_js(pg, "CasesShell.state().caseId === 'v1'"), "引数なしは前に開いた案件(v1): %s" % st())
                check(pg.evaluate("document.querySelector('a[data-ui-appnav-item=\"cases\"]').getAttribute('aria-current')") == "page",
                      "ヘッダーの appnav は「案件」が今の場所")

                # 10. 幅 390: 横にはみ出さない(左の一覧は上に積む)
                pg.set_viewport_size({"width": 390, "height": 800})
                pg.goto(base + "cases?c=v1&d=a0000000000b#proof")
                check(wait_js(pg, "CasesShell.state().sel === 'd:a0000000000b'"), "390 でも開ける")
                check(pg.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth + 1"), "390 で横にはみ出さない: %s" % pg.evaluate("[document.scrollingElement.scrollWidth, document.scrollingElement.clientWidth]"))

                studio_js = "/studio/review.js"   # スタジオを取り込まない入口で候補のパネルを開いたときの 404(上の 4)
                bad_status[:] = [u for u in bad_status if not (u.startswith("404 ") and u.endswith(studio_js))]
                errors[:] = [e for e in errors if studio_js not in e and "status of 404" not in e]
                check(not errors, "コンソールのエラーなし: %s" % errors[:3])
                check(not bad_status, "4xx / 5xx の応答なし: %s" % bad_status[:3])
            finally:
                browser.close()
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        for p in patches:
            p.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
