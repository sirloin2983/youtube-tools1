"""案件の画面(/cases)の「校正」のパネル(RS8 C2b。panels/proof.js・edhost.js・machpick.js)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.10 src/app/tests/e2e_cases_proof.py
入口(app/server.py --only transcribe,cut2resolve)を疑似の文字起こしで動かす(src/editor/tests/e2e_edit_common.py の Server)。
層が正(TRANSCRIBE_LAYERS=primary)の一時の作業データで 3 択まで確かめる。スタジオの data.json に配信 1 本(切り抜き 3 本・うち 1 本は文字起こし前)を置く。
見るもの(旧 e2e_proofread_keys・e2e_row_editing の要点): 編集の欄が載る(左のメニュー・空の状態は出ない)/ 左手のキー(S・Shift+Space)・? の一覧 /
文字を直すと保存・離れたら(UIKit.life の blur)すぐ保存 / 別の切り抜きへ移ると保存してから開く / カット・パックのタブの間は校正のキーが効かない /
保存の競合(409)の案内と読み直し / 文字起こし前の案内 / 小さい配信のプレーヤー(押したときだけ・前後 30 秒)/
3 択(札・比較欄・自分の直しのまま・今の機械にする・409 の案内・層が正でなければ札を出さない)/ 下の帯 / コンソールのエラーなし。"""
import json
import os
import re
import shutil
import sys
import time
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
os.environ["TRANSCRIBE_LAYERS"] = "primary"   # 3 択は層が正のときだけ(サーバーの子プロセスへ渡る)

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/app/tests
SRC = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(SRC, "editor", "tests"))
from e2e_edit_common import Checks, Server, make_video  # noqa: E402

VID = "AbCdEfGhIjK"   # YouTube の形の配信 id(11 字)


def wait_js(pg, expr, timeout=15000):
    """page.wait_for_function は入口の CSP で動かないので evaluate で待つ。待てなければ False"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        try:
            if pg.evaluate(expr):
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def find_file(root, name):
    for d, _dirs, files in os.walk(root):
        if name in files:
            return os.path.join(d, name)
    return None


def studio_data(srv, clips):
    """スタジオの data.json に配信 1 本(書き出した切り抜き = clips の (マーク id, 開始, 終了, パス))"""
    from manage.cases import cases as cm   # e2e_edit_common が src を sys.path に足してある
    path = cm.locations(srv.tmp)["studio"]
    marks = [{"id": mid, "start": a, "end": b, "status": "exported", "label": "笑い", "path": p, "file": os.path.basename(p),
              "createdAt": 1760000000000 + i} for i, (mid, a, b, p) in enumerate(clips)]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schema": "clip-studio/v1", "videos": {VID: {"id": VID, "kind": "youtube", "title": "【雑談】校正のテストの配信", "channel": "配信者 A",
                                                                 "duration": 7200, "marks": marks, "createdAt": 1760000000000, "updatedAt": 1760000000000}}},
                  f, ensure_ascii=False)
    return path


def main():
    ck = Checks()
    srv = Server(mounted=True)
    errors, bad = [], []
    try:
        shutil.copytree(os.path.join(SRC, "ui-kit"), os.path.join(srv.tmp, "ui-kit"))   # 入口は共通の見た目を src/ui-kit から直に配る(一時フォルダには写っていない)
        v1 = make_video(os.path.join(srv.media, "clip1.webm"), sec=12)
        v2 = make_video(os.path.join(srv.media, "clip2.webm"), sec=10)
        t1 = srv.transcribe(v1, title="切り抜き 1")
        t2 = srv.transcribe(v2, title="切り抜き 2")
        studio_data(srv, [("m1", 600, 612, v1), ("m2", 1800, 1810, v2), ("m3", 3000, 3010, os.path.join(srv.media, "clip3.webm"))])
        base = "http://localhost:%d/" % srv.port
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                ctx.route(re.compile(r"https://www\.youtube-nocookie\.com/.*"), lambda r: r.fulfill(status=200, content_type="text/html", body="<!doctype html><title>yt</title>"))
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append("%s @%s" % (m.text, m.location)) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append("%s %s" % (e, (e.stack or '')[:300])))
                pg.on("response", lambda r: bad.append("%s %s" % (r.status, r.url)) if r.status >= 400 else None)
                _scene_open(ck, pg, base, t1, t2)
                _scene_keys_and_save(ck, pg, srv, t1)
                _scene_switch(ck, pg, srv, t1, t2)
                _scene_cut_tab_gates_keys(ck, pg)
                _scene_conflict(ck, pg, srv, t2)
                _scene_no_transcript(ck, pg)
                _scene_stream_player(ck, pg)
                _scene_machpick(ck, pg, srv, base, t1)
                _scene_not_primary(ck, pg, base, t1)
                bad[:] = [u for u in bad if "mach-changes/pick" not in u and not (u.startswith("409 ") and "/api/transcript?id=" in u)]   # わざと起こした 409(_scene_conflict・_scene_machpick)
                errors[:] = [e for e in errors if "status of 409" not in e]
                ck(not errors, "コンソールのエラーなし: %s" % errors[:3])
                ck(not bad, "4xx / 5xx の応答なし: %s" % bad[:3])
            finally:
                browser.close()
    finally:
        srv.stop()
    print("ALL OK" if ck.ok else "SOME FAILED")
    return 0 if ck.ok else 1


def _scene_open(ck, pg, base, t1, t2):
    pg.goto(base + "cases?d=%s#proof" % t1)
    ck(wait_js(pg, "typeof S === 'object' && S.docId === %s && document.querySelectorAll('#csPane #segs .seg').length > 0" % json.dumps(t1), 30000),
       "d だけで開くと校正のパネルに編集の行が載る")
    st = pg.evaluate("CasesShell.state()")
    ck(st["caseId"] == VID and st["tab"] == "proof" and st["docId"] == t1, "案件・タブ・文書: %s" % st)
    rail = pg.evaluate("[...document.querySelectorAll('#csRail [data-cs-key]')].map(b => b.dataset.csKey)")
    ck(rail == ["cand", "d:" + t1, "d:" + t2, "m:m3"], "左の一覧は 候補 + 切り抜き 3 本: %s" % rail)
    ck(pg.evaluate("!document.querySelector('#menuPanel').offsetParent && !document.querySelector('#noDoc').offsetParent && !!document.querySelector('#csPane #docTitle').offsetParent"),
       "左のメニュー・空の状態は出さず、題名の行は出す")
    ck(pg.input_value("#docTitle") == "切り抜き 1", "題名: %r" % pg.input_value("#docTitle"))
    ck(pg.evaluate("!!document.querySelector('#csPane #player') && document.querySelector('#player').src.includes('/transcribe/media?id=')"), "切り抜きの映像は編集の /transcribe/media")
    ck(pg.evaluate("location.search + location.hash") == "?c=%s&d=%s#proof" % (VID, t1), "URL は殻のまま(?doc= を足さない): %s" % pg.evaluate("location.search + location.hash"))
    ck(wait_js(pg, "['Shift+N', 'Alt+2', '?'].every(k => !!document.querySelector('.ui-keybar [data-k=\"' + k + '\"]'))"), "下の帯に殻のキーと編集のキー")
    ck(pg.evaluate("document.querySelector('#csPane .cs-ed-bar #saveState') !== null && !!document.querySelector('#csPane #btnKeys')"), "保存の状態とキー操作はパネルの上")


def _scene_keys_and_save(ck, pg, srv, t1):
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("s")
    ck(wait_js(pg, "S.navIdx === 0"), "S で最初の行へ: %s" % pg.evaluate("S.navIdx"))
    pg.keyboard.press("s")
    ck(wait_js(pg, "S.navIdx === 1"), "S で次の行へ")
    pg.keyboard.press("w")
    ck(wait_js(pg, "S.navIdx === 0"), "W で前の行へ")
    pg.keyboard.press("Shift+Space")
    ck(wait_js(pg, "S.doc.segments[0].proofed === true && S.navIdx === 1"), "Shift+Space で校正済みにして次へ")
    ck(wait_js(pg, "document.querySelector('#saveState').dataset.state === 'ok'", 8000), "自動で保存: %r" % pg.text_content("#saveState"))
    pg.keyboard.press("?")
    ck(wait_js(pg, "document.querySelector('#keys').open"), "? でキー操作の一覧")
    pg.keyboard.press("Escape")
    ck(wait_js(pg, "!document.querySelector('#keys').open"), "Esc で閉じる")
    # 文字を直して、すぐ窓を離れる(UIKit.life の blur)= 0.7 秒の待ちを待たずに保存
    pg.click("#segs .seg[data-i='1'] textarea")
    pg.keyboard.press("End")
    pg.keyboard.type("テスト一")
    pg.evaluate("window.dispatchEvent(new Event('pagehide'))")   # 窓を閉じる直前と同じ(UIKit.life の pagehide)
    time.sleep(0.45)
    d = srv.get("/api/transcript?id=" + t1)
    ck(d["segments"][1]["text"].endswith("テスト一"), "離れたら(pagehide)0.7 秒を待たずに保存: %r" % d["segments"][1]["text"])
    pg.evaluate("window.dispatchEvent(new Event('pageshow'))")
    pg.keyboard.press("Escape")


def _scene_switch(ck, pg, srv, t1, t2):
    pg.click("#segs .seg[data-i='1'] textarea")
    pg.keyboard.press("End")
    pg.keyboard.type("二")
    pg.click("#csRail [data-cs-key='d:%s']" % t2)
    ck(wait_js(pg, "S.docId === %s && document.querySelector('#docTitle').value === '切り抜き 2'" % json.dumps(t2)), "左の一覧で次の切り抜きを開く")
    d = srv.get("/api/transcript?id=" + t1)
    ck(d["segments"][1]["text"].endswith("テスト一二"), "移る前に前の切り抜きを保存: %r" % d["segments"][1]["text"])
    ck(pg.evaluate("location.search") == "?c=%s&d=%s" % (VID, t2), "URL: %s" % pg.evaluate("location.search"))
    pg.keyboard.press("Shift+N")
    ck(wait_js(pg, "S.docId === %s" % json.dumps(t1)), "Shift+N で次の未校正の切り抜き(殻のキー)")
    pg.click("#csRail [data-cs-key='d:%s']" % t2)
    ck(wait_js(pg, "S.docId === %s" % json.dumps(t2)), "戻る")


def _scene_cut_tab_gates_keys(ck, pg):
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("s")
    ck(wait_js(pg, "S.navIdx >= 0"), "校正のタブでは S が効く")
    before = pg.evaluate("S.navIdx")
    pg.keyboard.press("Alt+2")
    ck(wait_js(pg, "CasesShell.state().tab === 'cut' && !EditHost.active"), "Alt+2 でカット・パック(校正の欄は隠し場所へ)")
    ck(pg.evaluate("document.querySelector('#player').paused"), "離れたら切り抜きの映像は止まる")
    # カット・パックのパネルが読み終わるまで待つ(配信者の色の照らし合わせの答えがパネルを閉じたあとに届くと pack-tab.js が消えた欄に書いて落ちる = C2c の側の件。まとめ役に報告)
    wait_js(pg, "((document.querySelector('#csPane #pkLookName') || {}).textContent || '').includes('けいふぉんと')", 15000)
    time.sleep(1.5)
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("w")
    pg.keyboard.press("?")
    time.sleep(0.3)
    ck(pg.evaluate("S.navIdx") == before and not pg.evaluate("document.querySelector('#keys').open"), "カット・パックのタブでは校正のキーが効かない")
    pg.keyboard.press("Alt+1")
    ck(wait_js(pg, "CasesShell.state().tab === 'proof' && EditHost.active && !!document.querySelector('#csPane #segs .seg')"), "Alt+1 で校正へ戻る(欄が戻る)")
    ck(wait_js(pg, "S.navIdx === %d" % before), "選んでいた行のまま: %s" % pg.evaluate("S.navIdx"))


def _scene_conflict(ck, pg, srv, t2):
    d = srv.get("/api/transcript?id=" + t2)   # 別の所(ほかの窓)で先に保存した
    body = {"title": d["title"], "speakers": d["speakers"], "segments": d["segments"], "baseUpdatedAt": d["updatedAt"]}
    body["segments"][0]["text"] = "ほかの窓の直し"
    r = srv.call("PUT", "/api/transcript?id=" + t2, body)
    ck("_status" not in r, "テスト: ほかの窓の保存 %s" % r.get("_status"))
    pg.click("#segs .seg[data-i='0'] textarea")
    pg.keyboard.press("End")
    pg.keyboard.type("こちら")
    ck(wait_js(pg, "!document.querySelector('#conflictBar').hidden", 8000), "保存の競合(409)は映像の上の案内")
    pg.keyboard.press("Escape")
    pg.click("#cfReload")
    ck(wait_js(pg, "document.querySelector('#conflictBar').hidden && S.doc.segments[0].text === 'ほかの窓の直し'"), "読み直すと保存済みの内容")


def _scene_no_transcript(ck, pg):
    pg.click("#csRail [data-cs-key='m:m3']")
    ck(wait_js(pg, "!!document.querySelector('#csPane [data-pf-none]') && !document.querySelector('#csPane #segs')"), "文字起こし前の切り抜きは案内(編集の欄は出さない)")
    ck(not pg.evaluate("EditHost.active"), "その間は編集のキーも止まる")


def _scene_stream_player(ck, pg):
    pg.click("#csRail [data-cs-key^='d:']")
    ck(wait_js(pg, "!!document.querySelector('#csPane [data-pf-stream]:not([hidden])')"), "配信のプレーヤーのボタン(YouTube の配信の切り抜き)")
    ck(not pg.evaluate("!!document.querySelector('#csPane iframe')"), "押すまでは読まない")
    pg.click("#csPane [data-pf-stream]")
    ck(wait_js(pg, "!!document.querySelector('#csPane .tx-stage [data-pf-streambox] iframe')"), "押すと映像の列に小さく出す")
    src = pg.get_attribute("#csPane [data-pf-streambox] iframe", "src")
    ck(src.startswith("https://www.youtube-nocookie.com/embed/%s?start=570&end=642" % VID), "前後 30 秒(570〜642): %s" % src)
    ck(pg.get_attribute("#csPane [data-pf-streambox] iframe", "referrerpolicy") == "strict-origin-when-cross-origin" and "allow-scripts" in pg.get_attribute("#csPane [data-pf-streambox] iframe", "sandbox"),
       "埋め込みは sandbox・referrerpolicy つき")
    pg.click("#csPane [data-pf-stream]")
    ck(wait_js(pg, "!document.querySelector('#csPane [data-pf-streambox]')"), "もう一度押すと隠す(枠ごと外して再生を止める)")


def _mach_edit(srv, tid, idx, text):
    """② が機械の層だけを作り直した(行 idx の文字を text に・rev を上げる)"""
    d = srv.get("/api/transcript?id=" + tid)
    rid = d["segments"][idx]["id"]
    mp = find_file(srv.tmp, tid + ".mach.json")
    with open(mp, encoding="utf-8") as f:
        m = json.load(f)
    row = next((r for r in m["rows"] if r["id"] == rid), m["rows"][idx])
    row["text"] = text
    m["rev"] += 1
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    return rid


def _scene_machpick(ck, pg, srv, base, t1):
    _mach_edit(srv, t1, 1, "きかいの新しい読み")
    pg.goto(base + "cases?d=%s#proof" % t1)
    ck(wait_js(pg, "!!document.querySelector('#csPane [data-pf-mc]')", 30000), "案件の頭に「機械が変わった行」")
    ck("1" in pg.text_content("#csPane [data-pf-mc]") and "1 行" in pg.text_content("#csHint"), "数: %r / %r" % (pg.text_content("#csPane [data-pf-mc]"), pg.text_content("#csHint")))
    ck(pg.evaluate("document.querySelectorAll('#segs [data-mc-tag]').length") == 1 and pg.evaluate("!!document.querySelector('#segs .seg[data-i=\"1\"] [data-mc-tag]')"), "印の行に札 1 つ")
    ck(wait_js(pg, "!!document.querySelector('.ui-keybar [data-k=\"Shift+C\"]')"), "下の帯に Shift+C")
    pg.click("#csPane [data-pf-mc]")
    ck(wait_js(pg, "!!document.querySelector('#segs .seg[data-i=\"1\"] [data-mc-box]') && S.navIdx === 1"), "押すとその行へ移り比較欄が開く")
    box = pg.text_content("#segs [data-mc-box]")
    ck("前の機械" in box and "今の機械" in box and "あなたの直し" in box and "きかいの新しい読み" in box and "テスト一二" in box, "3 本を並べる: %r" % box[:200])
    pg.evaluate("document.querySelector('#segs [data-mc-tag]').click()")
    ck(wait_js(pg, "!document.querySelector('#segs [data-mc-box]')"), "札をもう一度押すと閉じる")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Shift+C")
    ck(wait_js(pg, "!!document.querySelector('#segs [data-mc-box]')"), "Shift+C で選んだ行の比較欄")
    pg.evaluate("document.querySelector('#segs [data-mc-tag]').scrollIntoView()")
    # 409(別の所で変わった)は欄の中に何が・次に
    pg.route(re.compile(r".*/transcribe/api/mach-changes/pick$"), lambda r: r.fulfill(status=409, content_type="application/json",
                                                                                     body=json.dumps({"error": "conflict", "message": "別の場所で先に更新されています"})))
    pg.click("#segs [data-mc-pick=mine]")
    ck(wait_js(pg, "!!document.querySelector('#segs [data-mc-box] .cs-mc-err')") and "読み込み直す" in pg.text_content("#segs [data-mc-box]"), "409 の案内と読み込み直す")
    pg.unroute(re.compile(r".*/transcribe/api/mach-changes/pick$"))
    pg.click("#segs [data-mc-pick=mine]")
    ck(wait_js(pg, "!document.querySelector('#segs [data-mc-tag]') && !document.querySelector('#csPane [data-pf-mc]')"), "自分の直しのまま = 札と数が消える")
    d = srv.get("/api/transcript?id=" + t1)
    ck(d["segments"][1]["text"].endswith("テスト一二"), "自分の直しが残る: %r" % d["segments"][1]["text"])
    ck(srv.get("/api/mach-changes?id=" + t1)["rows"] == [], "サーバーの印も消える")
    _mach_edit(srv, t1, 1, "もういちど変わった読み")
    pg.evaluate("openDoc(S.docId, true)")   # 機械が書き換えたあとの読み直し(ジョブの終わりと同じ)
    ck(wait_js(pg, "!!document.querySelector('#segs [data-mc-tag]')"), "読み直すと数え直す")
    pg.evaluate("document.querySelector('#segs [data-mc-tag]').click()")
    pg.click("#segs [data-mc-pick=machine]")
    ck(wait_js(pg, "!document.querySelector('#segs [data-mc-tag]') && S.doc.segments[1].text === 'もういちど変わった読み'"), "今の機械にする = 行が今の機械の文字に")


def _scene_not_primary(ck, pg, base, t1):
    """層が正でなければ(今の既定 shadow)、行があっても札も数も出さない"""
    fake = {"layers": "shadow", "updatedAt": 1, "rows": [{"id": "x", "human": {"text": "a"}, "before": [], "now": []}]}
    pg.route(re.compile(r".*/transcribe/api/mach-changes\?.*"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(fake)))
    pg.goto(base + "cases?d=%s#proof" % t1)
    ck(wait_js(pg, "typeof S === 'object' && S.docId === %s && !!document.querySelector('#csPane #segs .seg')" % json.dumps(t1), 30000), "開く")
    time.sleep(0.5)
    ck(not pg.evaluate("!!document.querySelector('#csPane [data-pf-mc]') || !!document.querySelector('#segs [data-mc-tag]')"), "shadow では札も数も出さない")
    pg.set_viewport_size({"width": 390, "height": 800})
    time.sleep(0.5)
    ck(pg.evaluate("document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth + 1"),
       "幅 390 で横にはみ出さない: %s" % pg.evaluate("[document.scrollingElement.scrollWidth, document.scrollingElement.clientWidth]"))
    pg.set_viewport_size({"width": 1440, "height": 900})


if __name__ == "__main__":
    sys.exit(main())
