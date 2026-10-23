"""案件の画面(/cases)の「校正」のパネル(panels/proof.js・edhost.js・machpick.js)の通し確認(Playwright)。リポジトリ直下で:
    set PYTHONIOENCODING=utf-8
    py -3.12 tests/app/e2e_cases_proof.py
入口(app/server.py --only transcribe,cut2resolve)を疑似の文字起こしで動かす(tests/editor/e2e_edit_common.py の Server)。
層が正(機械の層 + 人の層)の一時の作業データで 3 択まで確かめる。スタジオの data.json に配信 1 本(切り抜き 3 本・うち 1 本は文字起こし前)を置く。
見るもの: 編集の欄が載る(左のメニュー・空の状態は出ない)/ 左手のキー(S・Shift+Space)・? の一覧 /
文字を直すと保存・離れたら(UIKit.life の pagehide)すぐ保存 / 別の切り抜きへ移ると保存してから開く・Shift+N で次の未校正 / カット・パックのタブの間は校正のキーが効かない /
保存の競合(409)の案内と読み直し / 文字起こし前の案内 / 小さい配信のプレーヤー(押したときだけ・前後 30 秒)/
3 択(札・比較欄・自分の直しのまま・今の機械にする・409 の案内・選んだら札と数が消える)/ 下の帯の Shift+C / コンソールのエラーなし。
タブを素早く切り替える(開いてすぐ閉じても画面のエラーが出ない・直した直後にカット・パックへ移っても直した文字で 409 にならない)。
仮の案件 orphan / eval の文書で: 行の移動と再生のキー・音のメモ・話者・⚙ の編集の節・自動で再生・Alt+Enter /
行を足す(＋後に・N・＋前に・再生位置に)・元に戻す・行の ▶ は行の終わりで止まる / つなぐ・分ける(Shift+M・M・Y)・Z の 2 回押し /
全行を校正済み → 「カット・パックへ」/ 評価用の確かめ済み・取り消し・全行をこの人に / 2 つ目のエンジンの候補 /
「別の読み」の札 / 声を覚える・同じ人ですか・評価用は覚えない・忘れる。"""
import json
import os
import re
import shutil
import sys
import time
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
os.environ["TRANSCRIBE_FAKE_ALT"] = "文=>分"   # 2 つ目のエンジン(疑似)は「テスト分n」と聞く(_scene_alt。alt のジョブだけが読む)

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # tests/app
SRC = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src")
sys.path.insert(0, os.path.join(os.path.dirname(SRC), "tests", "editor"))
from e2e_edit_common import Checks, Server, make_video  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402

VID = "AbCdEfGhIjK"   # YouTube の形の配信 id(11 字)


def wait_js(pg, expr, timeout=15000):
    return testkit.wait_js(pg, expr, timeout, ignore_errors=True)


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
        docs = _more_docs(srv)   # 行の編集・評価用・候補・声の場面の文書(配信に入れない = 仮の案件 orphan / eval)
        base = "http://localhost:%d/" % srv.port
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--mute-audio"])
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
                _scene_quick_tabs(ck, pg, srv, t2, errors, bad)
                _scene_conflict(ck, pg, srv, t2)
                _scene_no_transcript(ck, pg)
                _scene_stream_player(ck, pg)
                _scene_machpick(ck, pg, srv, base, t1)
                # 仮の案件の文書での編集の場面
                _scene_row_keys(ck, pg, srv, base, docs["keys"])
                _scene_row_tools(ck, pg, srv, base, docs["tools"])
                _scene_join_split_z(ck, pg, srv, base, docs["join"])
                _scene_proof_all(ck, pg, srv, base, docs["tools"])
                _scene_eval_doc(ck, pg, srv, base, docs["eval"])
                _scene_alt(ck, pg, srv, base, docs["alt"])
                _scene_fill(ck, pg, srv, base, docs["fill"])
                _scene_voices(ck, pg, srv, base, docs["voice"])
                bad[:] =[u for u in bad if "mach-changes/pick" not in u and not (u.startswith("409 ") and "/api/transcript?id=" in u)]   # わざと起こした 409(_scene_conflict・_scene_machpick)
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
    ck(pg.evaluate("!document.querySelector('#menuPanel') && !document.querySelector('#noDoc') && !!document.querySelector('#csPane #docTitle').offsetParent"),
       "左のメニュー・空の状態は出さず、題名の行は出す")
    ck(pg.input_value("#docTitle") == "切り抜き 1", "題名: %r" % pg.input_value("#docTitle"))
    ck(pg.evaluate("!!document.querySelector('#csPane #player') && document.querySelector('#player').src.includes('/transcribe/media?id=')"), "切り抜きの映像は編集の /transcribe/media")
    ck(pg.evaluate("location.search + location.hash") == "?c=%s&d=%s#proof" % (VID, t1), "URL は殻のまま(?doc= を足さない): %s" % pg.evaluate("location.search + location.hash"))
    ck(pg.evaluate("document.querySelector('#csPane .cs-ed-bar #saveState') !== null && !!document.querySelector('#csPane #btnKeys')"), "保存の状態とキー操作はパネルの上")


def _scene_keys_and_save(ck, pg, srv, t1):
    """配信の案件の文書で: 校正済みにすると自動で保存・? の一覧・離れたらすぐ保存(行の移動のキーの一式は _scene_row_keys)"""
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("s")
    ck(wait_js(pg, "S.navIdx === 0"), "S で最初の行へ: %s" % pg.evaluate("S.navIdx"))
    pg.keyboard.press("Shift+Space")
    ck(wait_js(pg, "S.doc.segments[0].proofed === true && S.navIdx === 1"), "Shift+Space で校正済みにして次へ")
    ck(wait_js(pg, "document.querySelector('#saveState').dataset.state === 'ok'", 8000), "自動で保存: %r" % pg.text_content("#saveState"))
    pg.keyboard.press("?")
    ck(wait_js(pg, "document.querySelector('#keys').open"), "? でキー操作の一覧")
    pg.keyboard.press("Escape")
    ck(wait_js(pg, "!document.querySelector('#keys').open"), "Esc で閉じる")
    # 文字を直して、すぐ窓を離れる(UIKit.life の pagehide)= 0.7 秒の待ちを待たずに保存
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
    # カット・パックのパネルが読み終わるまで待つ(閉じたあとに届く配信者の色の答えは pack-tab.js の disposed で捨てる。下のキーの確かめを読み込みの途中にしないため)
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


def _scene_quick_tabs(ck, pg, srv, t2, errors, bad):
    """タブを素早く切り替える(閉じたパネルへ遅れて届く答えを捨てる・閉じる側の保存を開く側が待つ)"""
    n_err = len(errors)
    pg.click("[data-cs-tab='cut']")
    pg.click("[data-cs-tab='proof']")   # カット・パックを開いてすぐ閉じる(配信者の色の照らし合わせの答えはまだ)
    pg.click("[data-cs-tab='cut']")
    pg.keyboard.press("Alt+1")
    ck(wait_js(pg, "CasesShell.state().tab === 'proof' && EditHost.active && !!document.querySelector('#csPane #segs .seg')"), "カット・パックを開いてすぐ校正へ戻れる")
    time.sleep(2.5)   # 閉じたパネルへ答えが遅れて届くまで待つ
    ck(len(errors) == n_err, "開いてすぐ閉じても画面のエラーが出ない(pkLookName など): %s" % errors[n_err:n_err + 3])
    # 校正で文字を直した直後(0.7 秒の保存のまとめを待たず)にカット・パックのタブへ = 直した文字のまま・409 にならない
    n_bad = len(bad)
    pg.click("#segs .seg[data-i='1'] textarea")
    pg.keyboard.press("End")
    pg.keyboard.type("タブ越し")
    pg.click("[data-cs-tab='cut']")
    ck(wait_js(pg, "CasesShell.state().tab === 'cut' && ((document.querySelector('#cutSubs .tt-csub[data-i=\"1\"] .tx') || {}).textContent || '').endsWith('タブ越し')", 30000),
       "直してすぐ開いたカットの字幕の一覧が直した文字: %r" % pg.evaluate("((document.querySelector('#cutSubs .tt-csub[data-i=\"1\"] .tx') || {}).textContent || '')"))
    ck(srv.get("/api/transcript?id=" + t2)["segments"][1]["text"].endswith("タブ越し"), "閉じる前に保存された")
    pg.keyboard.press("Alt+1")
    ck(wait_js(pg, "CasesShell.state().tab === 'proof' && EditHost.active && S.doc.segments[1].text.endsWith('タブ越し')"), "校正へ戻っても直した文字")
    time.sleep(0.5)
    ck(pg.evaluate("document.querySelector('#conflictBar').hidden") and not [u for u in bad[n_bad:] if u.startswith("409 ")],
       "保存の競合(409)にならない: %s" % bad[n_bad:n_bad + 3])


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
    _mach_edit(srv, t1, 1, "もういちど変わった読み")
    pg.evaluate("openDoc(S.docId, true)")   # 機械が書き換えたあとの読み直し(ジョブの終わりと同じ)
    ck(wait_js(pg, "!!document.querySelector('#segs [data-mc-tag]')"), "読み直すと数え直す")
    pg.evaluate("document.querySelector('#segs [data-mc-tag]').click()")
    pg.click("#segs [data-mc-pick=machine]")
    ck(wait_js(pg, "!document.querySelector('#segs [data-mc-tag]') && S.doc.segments[1].text === 'もういちど変わった読み'"), "今の機械にする = 行が今の機械の文字に")


# ======== 仮の案件の文書での編集の場面 ========

GAP_SEGS = [{"id": "a", "start": 0, "end": 2, "text": "一"}, {"id": "b", "start": 5, "end": 7, "text": "二"}, {"id": "c", "start": 7, "end": 9, "text": "三"}]
JOIN_SEGS = [{"id": "j0", "start": 0, "end": 2, "text": "ちょっとびっく"}, {"id": "j1", "start": 2, "end": 4, "text": "りした"},
             {"id": "j2", "start": 4, "end": 6, "text": "けど大丈夫"}, {"id": "j3", "start": 6, "end": 9, "text": "次の話"}]
FILL_LONG = "これは別の読みで埋めた長い文です"
NAV = "[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))"
TOASTS = "[...document.querySelectorAll('.ui-toast')].map(t => t.textContent).join(' / ')"
TIMES = "[...document.querySelectorAll('#segs .seg')].map(r => [r.querySelector('.t[data-f=start]').textContent, r.querySelector('.t[data-f=end]').textContent])"
TEXTS = "[...document.querySelectorAll('#segs .seg textarea')].map(t => t.value)"


def _put(srv, tid, title, segs, speakers=None, **extra):
    r = srv.call("PUT", "/api/transcript?id=" + tid, dict({"title": title, "speakers": speakers or [], "segments": segs}, **extra))
    assert "_status" not in r, r
    return r


def _wait_job(srv, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = next((x for x in srv.get("/api/jobs")["jobs"] if x["id"] == jid), None)
        if j and j["state"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.1)
    raise RuntimeError("ジョブが終わりません: %s" % jid)


def _more_docs(srv):
    """場面ごとの文書(どれもスタジオの配信に入れない = 左の一覧は仮の案件)。12 秒の動画は 1 本作って名前を変えて写す(文書は動画のパスで分かれる)"""
    v24 = make_video(os.path.join(srv.media, "rows24.webm"), sec=24)
    keys = srv.transcribe(v24, title="キーの確認")   # 疑似は 4 秒で 1 行 = 6 行
    d = srv.get("/api/transcript?id=" + keys)
    d["segments"][1]["flag"] = "認識が不確か"
    d["segments"][0]["proofed"] = True
    _put(srv, keys, "キーの確認", d["segments"], [{"id": "S1", "name": "トワ", "color": "#2f62d6"}])
    v12 = make_video(os.path.join(srv.media, "tools.webm"), sec=12)

    def v12_as(name):
        p = os.path.join(srv.media, name)
        shutil.copyfile(v12, p)
        return p
    tools = srv.transcribe(v12, title="行の道具")
    _put(srv, tools, "行の道具", GAP_SEGS)
    join = srv.transcribe(v12_as("join.webm"), title="つなぐ分ける")
    _put(srv, join, "つなぐ分ける", JOIN_SEGS)
    ev = srv.transcribe(v12_as("eval.webm"), title="さくらみこ 雑談")
    d = srv.get("/api/transcript?id=" + ev)
    _put(srv, ev, "さくらみこ 雑談", [dict(g, speaker="", proofed=False) for g in d["segments"]], evalSet=True)
    alt = srv.transcribe(v12_as("alt.webm"), title="別のエンジン")
    fill = srv.transcribe(v12_as("fill.webm"), title="別の読み")
    d = srv.get("/api/transcript?id=" + fill)
    _put(srv, fill, "別の読み", [dict(g, text=FILL_LONG, fill={"from": g["text"], "by": "sense-voice"}, flag="別の読みで埋めた行です") for g in d["segments"]])
    voice = srv.transcribe(make_video(os.path.join(srv.media, "voice.webm"), sec=30), title="声の確認")
    j = _wait_job(srv, srv.call("POST", "/api/diarize", {"tid": voice, "numSpeakers": 2})["id"])
    assert j["state"] == "done" and j["speakers"] == 2, j
    return {"keys": keys, "tools": tools, "join": join, "eval": ev, "alt": alt, "fill": fill, "voice": voice}


def _open(pg, base, tid, timeout=30000):
    """切り抜きの文書を校正のパネルで開く(前の文書の保存が済んでから移る)"""
    wait_js(pg, "typeof S !== 'object' || (!S.dirty && !S.saving)", 10000)
    pg.goto(base + "cases?d=%s#proof" % tid)
    return wait_js(pg, "typeof S === 'object' && S.docId === %s && !!document.querySelector('#csPane #segs .seg')" % json.dumps(tid), timeout)


def _saved(pg, timeout=10000):
    return wait_js(pg, "!S.dirty && !S.saving && document.querySelector('#saveState').dataset.state === 'ok'", timeout)


def _reset(pg, srv, tid, title, segs):
    """文書の行を置き直して読み直す(場面の中で前提をそろえる)"""
    _saved(pg)
    _put(srv, tid, title, segs)
    pg.evaluate("openDoc(S.docId, true)")
    return wait_js(pg, "S.doc.segments.length === %d && document.querySelectorAll('#segs .seg').length === %d" % (len(segs), len(segs)))


def _select_row(pg, i):
    pg.locator("#segs textarea").nth(i).click()
    pg.keyboard.press("Escape")


def _scene_row_keys(ck, pg, srv, base, tid):
    """行の移動と再生のキー・音の状態・話者・入力欄・自動で再生・Alt+Enter"""
    ck(_open(pg, base, tid), "キーの確認の文書を開く(仮の案件)")
    st = pg.evaluate("CasesShell.state()")
    n = pg.evaluate("S.doc.segments.length")
    ck("校正 1 / %d" % n in pg.text_content("#pillProof"), "題名の行の札「校正 1 / %d行」: %r" % (n, pg.text_content("#pillProof")))
    navi = lambda: pg.evaluate(NAV)   # noqa: E731
    pg.locator("#segs textarea").nth(0).focus()
    pg.keyboard.press("Escape")
    ck(pg.evaluate("document.activeElement === document.body") and navi() == 0, "Esc で入力欄から抜けても選んでいる行は残る")
    pg.keyboard.press("ArrowDown")
    ck(navi() == 1, "↓ で次の行")
    pg.keyboard.press("ArrowUp")
    ck(navi() == 0, "↑ で前の行")
    pg.keyboard.press("Shift+ArrowDown")
    ck(navi() == 1, "Shift+↓ で次の未校正へ(1 行目は校正済み)")
    pg.keyboard.press("f")
    ck(navi() == 4, "F で次の要確認へ: %d" % navi())
    pg.keyboard.press("f")
    ck(navi() == 4 and "要確認" in pg.evaluate(TOASTS), "これより後に要確認が無ければ移らず案内: %s" % pg.evaluate(TOASTS)[-60:])
    pg.keyboard.press("Shift+ArrowUp")
    ck(navi() == 3, "Shift+↑ で前の未校正へ")
    pg.keyboard.press("w")
    ck(navi() == 2, "W で前の行")
    pg.keyboard.press("s")
    ck(navi() == 3, "S で次の行")
    pg.keyboard.press("a")
    na = navi()
    pg.keyboard.press("d")
    ck(0 < na < 3 and navi() > na, "A / D で前・次の未校正へ: %d → %d" % (na, navi()))
    while navi() != 3:
        pg.keyboard.press("s" if navi() < 3 else "w")
    pg.evaluate("(() => { const p = document.querySelector('#player'); p.pause(); p.currentTime = 5; })()")
    pg.keyboard.press("e")
    ck(wait_js(pg, "Math.abs(document.querySelector('#player').currentTime - 8) < 0.3", 3000), "E で 3 秒進む")
    pg.keyboard.press("q")
    ck(wait_js(pg, "Math.abs(document.querySelector('#player').currentTime - 5) < 0.3", 3000), "Q で 3 秒戻る")
    pg.keyboard.press("Space")
    time.sleep(0.3)
    ck(not pg.evaluate("document.querySelector('#player').paused"), "Space 1 回で再生(すぐ止まらない)")
    pg.keyboard.press("Space")
    ck(pg.evaluate("document.querySelector('#player').paused"), "もう一度 Space で止まる")
    pg.keyboard.press("b")
    ck(not pg.is_checked("#autoNext"), "B のキーは 10-24 に外した(「移動したら自動で再生」は ⚙ の欄だけで切り替える)")
    pg.keyboard.press("Tab")
    ck(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "Tab で選んだ行の入力欄へ")
    pg.keyboard.press("Tab")
    ck(pg.evaluate("document.activeElement === document.body") and navi() == 3, "入力中の Tab で入力欄から抜ける")
    # 音の状態のメモ・話者・入力欄
    pg.keyboard.press("x")
    ck(pg.locator("#segs .seg").nth(3).evaluate("e => e.classList.contains('tagged')"), "X で「聞き取れない」")
    pg.keyboard.press("x")
    pg.keyboard.press("c")
    pg.keyboard.press("1")
    ck(pg.locator("#segs .spk").nth(3).input_value() == "S1", "C(声が重なる)のあと 1 で話者")
    pg.keyboard.press("t")
    ck(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "T で行の文字を直す(入力欄へ)")
    before = pg.locator("#segs textarea").nth(3).input_value()
    pg.keyboard.press("Shift+F")
    ck(pg.locator("#segs textarea").nth(3).input_value() == before + "F" and navi() == 3, "入力中の Shift+F は大文字の F が入るだけ")
    pg.keyboard.press("Backspace")
    pg.keyboard.press("Escape")
    ck(_saved(pg), "保存")
    g3 = srv.get("/api/transcript?id=" + tid)["segments"][3]
    ck(g3.get("tags") == ["overlap"] and g3.get("speaker") == "S1", "音のメモと話者がサーバーに保存: %s" % {k: g3.get(k) for k in ("tags", "speaker")})
    # ⚙ の引き出しに編集の節(移動したら自動で再生・評価用のフォルダ)= 案件の画面の設定の唯一の入口
    pg.click("[data-ui-settings]")
    ck(wait_js(pg, "!!document.querySelector('#autoNext') && !!document.querySelector('#autoNext').offsetParent", 5000), "⚙ の引き出しに「移動したら自動で再生」")
    ck(pg.locator("#evDirs").count() == 1 and pg.locator("#follow").count() == 1, "⚙ に評価用のフォルダ・再生に合わせて追いかける の欄")
    pg.check("#autoNext")
    pg.keyboard.press("Escape")
    pg.keyboard.press("ArrowUp")
    pg.keyboard.press("Shift+Space")
    d = srv.get("/api/transcript?id=" + tid)
    ck(navi() == 3 and pg.locator("#segs .seg").nth(2).evaluate("e => e.classList.contains('proofed')"), "Shift+Space で校正済みにして次の行へ")
    ck(wait_js(pg, "document.querySelector('#player').currentTime >= %s - 0.05" % d["segments"][3]["start"], 5000), "移った行が自動で再生される")
    p0 = pg.locator("#segs .seg.proofed").count()
    pg.locator("#segs textarea").nth(4).focus()
    pg.keyboard.press("Alt+Enter")
    ck(wait_js(pg, "document.activeElement === document.querySelectorAll('#segs textarea')[5]", 3000) and pg.locator("#segs .seg.proofed").count() == p0 + 1,
       "入力中の Alt+Enter で校正済みにして次の行の入力欄へ")
    ck("今回 +" in pg.text_content("#sessStat"), "今回の校正数: %r" % pg.text_content("#sessStat"))
    pg.keyboard.press("Escape")
    pg.evaluate("document.querySelector('#player').pause()")
    pg.click("[data-ui-settings]")
    pg.uncheck("#autoNext")
    pg.keyboard.press("Escape")
    now = pg.evaluate("CasesShell.state()")
    ck((now["tab"], now["docId"]) == (st["tab"], st["docId"]), "編集のキーは殻のタブ・文書を動かさない: %s" % now)


def _scene_row_tools(ck, pg, srv, base, tid):
    """行を足す(＋後に行・N・＋前に行・再生位置に)と元に戻す・行の道具は選んだ行だけ"""
    ck(_open(pg, base, tid), "行の道具の文書を開く")
    adj = lambda i: pg.locator("#segs .seg").nth(i).locator(".adj")   # noqa: E731
    ck(not adj(0).is_visible(), "開いた直後は行の道具(.adj)が出ていない")
    _select_row(pg, 0)
    ck(adj(0).is_visible() and not adj(1).is_visible(), "選んだ行だけに行の道具")
    pg.locator("#segs .seg").nth(0).locator("[data-act=adda]").click()
    ck(pg.evaluate(TIMES)[1] == ["0:02.0", "0:05.0"] and pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[1]"),
       "＋後に行 = 前後のすき間(2〜5 秒)に入り、入力欄へ: %s" % pg.evaluate(TIMES))
    pg.keyboard.type("追加した行")
    pg.keyboard.press("Escape")
    ck(_saved(pg), "保存")
    new = next((g for g in srv.get("/api/transcript?id=" + tid)["segments"] if g["text"] == "追加した行"), None)
    ck(new is not None and abs(new["start"] - 2.0) < 0.01 and abs(new["end"] - 5.0) < 0.01, "サーバーにも 2.0〜5.0 の行: %s" % new)
    # N(すき間なし)= 1.5 秒の仮の長さ・重なりの案内
    ck(_reset(pg, srv, tid, "行の道具", GAP_SEGS), "前提をそろえる")
    _select_row(pg, 1)
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("n")
    ck(pg.evaluate(TIMES)[2] == ["0:07.0", "0:08.5"] and "重なって" in pg.evaluate(TOASTS), "N: すき間が無ければ 1.5 秒の仮の長さで、重なりを知らせる: %s" % pg.evaluate(TIMES))
    # ＋前に行
    ck(_reset(pg, srv, tid, "行の道具", GAP_SEGS), "前提をそろえる")
    _select_row(pg, 0)
    pg.locator("#segs .seg").nth(0).locator("[data-act=addb]").click()
    ck(len(pg.evaluate(TIMES)) == 4 and pg.evaluate(TIMES)[0][0] == "0:00.0", "＋前に行は先頭行の前(0:00.0 から)")
    # 再生位置に行・元に戻す(Ctrl+Z と ↶)
    ck(_reset(pg, srv, tid, "行の道具", GAP_SEGS), "前提をそろえる")
    pg.evaluate("document.querySelector('#player').currentTime = 3.5")
    wait_js(pg, "document.querySelector('#player').currentTime >= 3.4", 5000)
    pg.click("#btnAddAt")
    t = pg.evaluate(TIMES)
    ck(len(t) == 4 and ["0:03.2", "0:05.0"] in t and pg.get_attribute("#btnUndo", "disabled") is None, "＋再生位置に行(3.2〜5.0)・元に戻すが押せる: %s" % t)
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Control+z")
    ck(pg.evaluate(TIMES) == [["0:00.0", "0:02.0"], ["0:05.0", "0:07.0"], ["0:07.0", "0:09.0"]], "Ctrl+Z で足した行が消える")
    pg.click("#btnAddAt")
    pg.click("#btnUndo")
    ck(len(pg.evaluate(TIMES)) == 3, "元に戻す(↶)のボタンでも戻る")
    pg.locator("#segs .seg").nth(0).locator("[data-act=play]").click()
    ck(wait_js(pg, "document.querySelector('#player').paused && document.querySelector('#player').currentTime >= 1.6 && document.querySelector('#player').currentTime <= 2.6", 8000),
       "行の ▶ はその行の終わり(2 秒)で止まる: %s" % pg.evaluate("document.querySelector('#player').currentTime"))
    ck(_saved(pg), "保存")


def _scene_join_split_z(ck, pg, srv, base, tid):
    """つなぐ(Shift+M・M)・分ける(Y)・Ctrl+Z・Z の 2 回押し"""
    ck(_open(pg, base, tid), "つなぐ分けるの文書を開く")
    _select_row(pg, 1)
    pg.keyboard.press("Shift+M")
    ck(pg.evaluate(TEXTS) == ["ちょっとびっくりした", "けど大丈夫", "次の話"] and pg.evaluate(TIMES)[0] == ["0:00.0", "0:04.0"] and pg.evaluate(NAV) == 0,
       "Shift+M で前の行とつなぐ: %s" % pg.evaluate(TEXTS))
    ck("前の行とつなぎました" in pg.evaluate(TOASTS) and wait_js(pg, "!document.querySelector('#player').paused", 5000), "知らせて、つないだ行を頭から聞き直す")
    pg.evaluate("document.querySelector('#player').pause()")
    pg.keyboard.press("m")
    ck(pg.evaluate(TEXTS) == ["ちょっとびっくりしたけど大丈夫", "次の話"], "M で次の行とつなぐ")
    pg.evaluate("document.querySelector('#player').pause()")
    pg.keyboard.press("Control+z")
    ck(pg.evaluate(TEXTS) == ["ちょっとびっくりした", "けど大丈夫", "次の話"], "Ctrl+Z で 1 つ前に戻る")
    pg.evaluate("(() => { const p = document.querySelector('#player'); p.pause(); p.currentTime = 1.0; })()")
    wait_js(pg, "Math.abs(document.querySelector('#player').currentTime - 1.0) < 0.05", 5000)
    pg.keyboard.press("y")
    ck(pg.evaluate(TEXTS) == ["ちょっ", "とびっくりした", "けど大丈夫", "次の話"] and pg.evaluate(TIMES)[:2] == [["0:00.0", "0:01.0"], ["0:01.0", "0:04.0"]],
       "Y で再生位置で分ける(文字は割合の所): %s" % pg.evaluate(TEXTS))
    pg.evaluate("document.querySelector('#player').currentTime = 8.5")
    wait_js(pg, "document.querySelector('#player').currentTime > 8.4", 5000)
    pg.keyboard.press("y")
    ck(len(pg.evaluate(TEXTS)) == 4 and "行の中にありません" in pg.evaluate(TOASTS), "再生位置が行の外なら分けない")
    ck(_saved(pg), "保存")
    ck([g["text"] for g in srv.get("/api/transcript?id=" + tid)["segments"]] == ["ちょっ", "とびっくりした", "けど大丈夫", "次の話"], "サーバーにも保存(層が正でも)")
    # Z は 1.5 秒以内の 2 回押しで消す
    _select_row(pg, 1)
    pg.keyboard.press("z")
    ck(len(pg.evaluate(TEXTS)) == 4 and "もう一度 Z" in pg.evaluate(TOASTS), "1 回目の Z ではまだ消えない")
    pg.keyboard.press("z")
    ck(len(pg.evaluate(TEXTS)) == 3, "1.5 秒以内の 2 回目で消える")
    _select_row(pg, 0)
    pg.keyboard.press("z")
    # 期限切れ(誤操作で消さない仕様そのもの)。1.6 秒待つ代わりに画面の時計(Date.now)を 1.6 秒進める(戻さない = 時計は前にだけ進む)
    pg.evaluate("(() => { const now = Date.now.bind(Date); Date.now = () => now() + 1600; })()")
    pg.keyboard.press("z")
    ck(len(pg.evaluate(TEXTS)) == 3, "1.5 秒を過ぎた Z は 1 回目からやり直し")
    pg.evaluate("document.activeElement && document.activeElement.blur()")
    pg.keyboard.press("Escape")
    ck(_saved(pg), "保存")


def _scene_proof_all(ck, pg, srv, base, tid):
    """「まとめて」の全行を校正済みに → 知らせの「カット・パックへ」で殻のカット・パックのタブへ(EditHost.tab の橋渡し)"""
    ck(_open(pg, base, tid), "行の道具の文書を開く")
    pg.click("#moreTools summary")
    pg.click("#btnProofAll")
    if wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 1500):
        pg.click("dialog.ui-dialog[open] .btn.primary")
    ck(wait_js(pg, "S.doc.segments.every(g => g.proofed || !String(g.text || '').trim())", 5000), "全行が校正済み")
    ck(wait_js(pg, "[...document.querySelectorAll('.ui-toast-act')].some(b => b.textContent.includes('カット・パックへ'))", 5000), "知らせに次の一手「カット・パックへ」: %s" % pg.evaluate(TOASTS)[-80:])
    pg.evaluate("[...document.querySelectorAll('.ui-toast-act')].find(b => b.textContent.includes('カット・パックへ')).click()")
    ck(wait_js(pg, "CasesShell.state().tab === 'cut'", 10000), "押すとカット・パックのタブへ(殻のタブ)")
    ck(all(g.get("proofed") for g in srv.get("/api/transcript?id=" + tid)["segments"] if g["text"].strip()), "サーバーにも校正済み")
    pg.keyboard.press("Alt+1")
    wait_js(pg, "CasesShell.state().tab === 'proof' && EditHost.active", 10000)


def _scene_eval_doc(ck, pg, srv, base, tid):
    """評価用の文書: 確かめ済みにする・取り消す・全行をこの人に(評価ドリルの帯は案件の画面に無い)"""
    ck(_open(pg, base, tid), "評価用の文書を開く")
    ck(pg.evaluate("CasesShell.state().caseId") == "eval", "評価用の文書は仮の案件「評価用」に入る: %s" % pg.evaluate("CasesShell.state().caseId"))
    ck(wait_js(pg, "!document.querySelector('#evrBox').hidden && document.querySelector('#evalSet').checked", 10000), "評価用の印と確かめ済みの欄")
    ck("まだ確かめていない" in pg.text_content("#evrPill") and not pg.is_disabled("#evrRedo"), "まだ確かめていない・作り直すが押せる")
    pg.locator("#segs textarea").nth(0).fill("直してすぐ済み")
    pg.click("#evrMark")
    ck(wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 5000), "話者の無い行がある = 確認")
    pg.click("dialog.ui-dialog[open] .btn.primary")
    ck(wait_js(pg, "document.querySelector('#evrPill').textContent === '確かめ済み'", 10000), "確かめ済みになる")
    d = srv.get("/api/transcript?id=" + tid)
    ck(isinstance(d.get("evalReviewed"), dict) and all(g.get("proofed") for g in d["segments"]) and d["segments"][0]["text"] == "直してすぐ済み",
       "サーバーに印(via editor)・全行が校正済み・直した文字も保存してから")
    ck(pg.is_disabled("#evrRedo") and "確かめ済みを取り消して" in (pg.get_attribute("#evrRedo", "title") or ""), "確かめ済みでは作り直せず理由")
    pg.click("#evrUndo")
    wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 5000)
    pg.click("dialog.ui-dialog[open] .btn.primary")
    ck(wait_js(pg, "document.querySelector('#evrPill').textContent === 'まだ確かめていない'", 10000), "取り消すと戻る")
    d = srv.get("/api/transcript?id=" + tid)
    ck("evalReviewed" not in d and not any(g.get("proofed") for g in d["segments"]), "印と、印が校正済みにした行が戻る")
    pg.click("#btnSpk")
    pg.click("[data-jump=spDetails]")
    ck(wait_js(pg, "!document.querySelector('#spAllBox').hidden && document.querySelector('#spAllName').value === 'さくらみこ'", 10000), "全行をこの人に(候補は配信の文脈 = 題名から)")
    pg.click("#spAllGo")
    wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 5000)
    ck("さくらみこ" in pg.text_content("dialog.ui-dialog[open]"), "確認のダイアログ: %s" % pg.text_content("dialog.ui-dialog[open]")[:160])
    pg.click("dialog.ui-dialog[open] .btn.primary")
    end = time.time() + 10
    while time.time() < end and [s["name"] for s in srv.get("/api/transcript?id=" + tid)["speakers"]] != ["さくらみこ"]:
        time.sleep(0.1)
    d = srv.get("/api/transcript?id=" + tid)
    ck([s["name"] for s in d["speakers"]] == ["さくらみこ"] and all(g["speaker"] == "S1" for g in d["segments"]) and find_file(srv.tmp, tid + ".diar.json"),
       "全行がその人に・話者判別の記録も書く")
    ck(wait_js(pg, "document.querySelector('#spAllBox').hidden", 10000), "全行に話者が付くと欄は消える")


def _scene_alt(ck, pg, srv, base, tid):
    """2 つ目のエンジンの候補: 聞く → 行に「別」の候補 → 採用・却下(API の規則は test_alt)"""
    ck(_open(pg, base, tid), "別のエンジンの文書を開く")
    n = pg.evaluate("S.doc.segments.length")
    pg.evaluate("document.querySelector('#fixDetails').open = true")
    ck(wait_js(pg, "document.querySelector('#altEngine').options.length === 1 && document.querySelector('#altMsg').textContent.includes('まだ別のエンジンで聞いていません')", 10000)
       and not pg.is_disabled("#altGo"), "「別のエンジンでも聞く」: まだ聞いていない")
    pg.click("#altGo")
    ck(not pg.evaluate("document.querySelector('#segs').inert"), "聞いている間も行は直せる")
    ck(wait_js(pg, "document.querySelectorAll('#segs .sg.tt-sg-alt').length === %d" % n, 30000), "行に「別」の候補")
    chip = pg.locator("#segs .seg[data-i='0'] .sg.tt-sg-alt")
    ck("「文」→「分」" in chip.inner_text() and "別のエンジン" in (chip.get_attribute("title") or ""), "候補の文字とツールチップ: %s" % chip.inner_text().replace("\n", " "))
    pg.click("#segs .seg[data-i='0'] .sg.tt-sg-alt button[data-act=sgok]")
    ck(pg.locator("#segs .seg[data-i='0'] textarea").input_value() == "テスト分1", "採用で行の文字を置き換える")
    pg.click("#segs .seg[data-i='1'] .sg.tt-sg-alt button[data-act=sgno]")
    ck(pg.locator("#segs .seg[data-i='1'] .sg.tt-sg-alt").count() == 0, "却下で消える")
    ck(_saved(pg), "保存")
    d = srv.get("/api/transcript?id=" + tid)
    ck(d["segments"][0]["text"] == "テスト分1" and d["segments"][1]["text"] == "テスト文2", "採用した文字を保存(却下した行はそのまま)")


def _scene_fill(ck, pg, srv, base, tid):
    """認識のあとの後処理の「別の読み」の札: 押すと元の文字へ・保存・元に戻す(後処理の本体は test_fill)"""
    ck(_open(pg, base, tid), "別の読みの文書を開く")
    n = pg.evaluate("S.doc.segments.length")
    ck(pg.locator("#segs .seg .tt-fill").count() == n, "行に「別の読み」の札が %d つ" % n)
    title = pg.locator("#segs .seg[data-i='0'] .tt-fill").get_attribute("title") or ""
    ck("テスト文1" in title and "sense-voice" in title and pg.locator("#segs .seg[data-i='0'] .fl").count() == 1, "札のツールチップに元の文字・要確認の札: %s" % title)
    pg.click("#segs .seg[data-i='0'] .tt-fill")
    ck(wait_js(pg, "document.querySelector('#segs .seg[data-i=\"0\"] textarea').value === 'テスト文1'")
       and pg.locator("#segs .seg[data-i='0'] .tt-fill").count() == 0 and pg.locator("#segs .seg[data-i='0'] .fl").count() == 0, "押すと元の文字に戻り、札と要確認の印が消える")
    ck(_saved(pg), "保存")
    d = srv.get("/api/transcript?id=" + tid)
    ck(d["segments"][0]["text"] == "テスト文1" and "fill" not in d["segments"][0] and not d["segments"][0].get("flag") and d["segments"][1].get("fill"), "戻した文字を保存(ほかの行の fill は残る)")
    pg.evaluate("doUndo('tx')")
    ck(wait_js(pg, "document.querySelector('#segs .seg[data-i=\"0\"] textarea').value === %s" % json.dumps(FILL_LONG)) and pg.locator("#segs .seg[data-i='0'] .tt-fill").count() == 1,
       "元に戻すで別の読みと札が戻る")
    ck(_saved(pg), "保存")


def _scene_voices(ck, pg, srv, base, tid):
    """話者の声を覚える・同じ人ですか・評価用は覚えない・忘れる(鎖と API の規則は test_voices・test_proof_api)"""
    ck(_open(pg, base, tid), "声の確認の文書を開く")
    pg.click("#btnSpk")
    pg.click("[data-jump=spDetails]")
    ck(wait_js(pg, "document.querySelector('#spDetails').open && document.querySelector('#voiceLearnHint').textContent.length > 0", 5000)
       and pg.is_disabled("#voiceLearn") and "名前を付けて" in pg.text_content("#voiceLearnHint"), "仮の名前のままでは「声を覚える」を押せない")
    for k, nm in ((0, "兎田ぺこら"), (1, "本人")):
        box = pg.locator("#spList .sp-row").nth(k).locator("input[type=text]")
        box.fill(nm)
        box.press("Enter")
        box.dispatch_event("change")
    ck(wait_js(pg, "!document.querySelector('#voiceLearn').disabled", 5000) and "兎田ぺこら" in pg.text_content("#voiceLearnHint"), "名前を付けると押せる")
    pg.click("#voiceLearn")
    ck(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.includes('覚えられる話者がいません') && t.textContent.includes('未校正'))", 10000),
       "校正済みの行が無いと覚えない")
    for _ in range(pg.locator("#segs .seg .pf[aria-pressed=false]").count()):
        pg.locator("#segs .seg .pf[aria-pressed=false]").first.click()
    pg.click("#voiceLearn")
    ck(wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 15000), "覚える前の確認")
    txt = pg.text_content("dialog.ui-dialog[open] .ui-dlg-body")
    ck("兎田ぺこら" in txt and "秒" in txt and "一般的な名前" in txt, "誰の声を何秒で覚えるか・一般的な名前(本人)は覚えない: %s" % txt[:120])
    pg.click("dialog.ui-dialog[open] .ui-dlg-actions button:last-child")
    ck(wait_js(pg, "document.querySelector('#voiceCount').textContent.includes('1人')", 30000), "覚えた声 1 人")
    pg.click("#voiceLearn")
    wait_js(pg, "!!document.querySelector('dialog.ui-dialog[open]')", 15000)
    ck("もう覚えている" in pg.text_content("dialog.ui-dialog[open] .ui-dlg-body"), "2 回目は「もう覚えている」と知らせる")
    pg.click("dialog.ui-dialog[open] .ui-dlg-actions button:last-child")
    ck(wait_js(pg, "(document.querySelector('dialog.ui-dialog[open] h2') || {}).textContent === '同じ人ですか'", 5000), "「同じ人ですか」")
    pg.click("dialog.ui-dialog[open] .ui-dlg-actions button:first-child")
    ck(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.includes('覚える人がいないので'))", 5000), "やめると覚えない")
    pg.check("#evalSet")
    ck(wait_js(pg, "document.querySelector('#voiceLearn').disabled", 5000) and "評価用" in pg.text_content("#voiceLearnHint"), "評価用にすると押せず理由")
    pg.uncheck("#evalSet")
    ck(wait_js(pg, "!document.querySelector('#voiceLearn').disabled", 5000), "外すと戻る")
    pg.click("#voiceBox summary")
    btn = pg.locator("#voiceList [data-act=vdel]").first
    btn.click()
    btn.click()
    ck(wait_js(pg, "document.querySelector('#voiceCount').textContent.includes('まだ')", 10000) and srv.get("/api/voices")["voices"] == {}, "忘れる(2 回押し)")
    ck(_saved(pg), "保存")


if __name__ == "__main__":
    sys.exit(main())
