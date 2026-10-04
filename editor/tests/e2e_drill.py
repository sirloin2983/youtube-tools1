#!/usr/bin/env python3
"""評価ドリル(動画 1 本ずつ・編集の画面で。editor/ed_drill.py・app-learn.js の drill*。マスタープラン Q4 = docs/plan/q3-q4-design.md の (c))と、
評価用の文書の「確かめ済み」(ドリルの外)・話者のカードの「全行をこの人に」の通し確認。入口に取り込んだ形(CSP・合言葉)で動かす。

    PYTHONIOENCODING=utf-8 py -3.10 editor/tests/e2e_drill.py

ドリル: 進行度のカードの「評価ドリルを始める →」→ 帯(定点まであと何分・条件)と ?doc=&drill=1 → 1 行直してすぐ「済みにして次へ」(未保存の変更も保存してから)
→ 次の文書が開く(画面の再読み込みなし)・定点の残りが減る → 飛ばす(Shift+N)→ 直してすぐ Shift+D → 再読み込みしても続く → 話者の無い行の確認(やめる / このまま)
→ 次が無い → ドリルを終える。行の結合・追加などは既存の e2e(e2e_row_editing ほか)で確かめ済みなので、ここでは 1 行直すだけ。
ドリルの外: 評価用の文書を開くと「まだ確かめていない」と「全部聞いて直したので済みにする」→ 確かめ済み → 取り消す。全行をこの人に: 候補 → 確認 → 全行がその人に。
話者の自動判別(v0.50.0): 評価用として文字起こし → 続けて話者の判別のジョブ(自動)→ 名前の候補(配信の文脈)がいちばん長く話した人に → ドリルで開くと話者付きで、帯に「自動で付けてあります」
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
from e2e_edit_common import Checks, Server, make_video, open_doc, wait_js  # noqa: E402
from ytt_core import layout as _layout  # noqa: E402  (e2e_edit_common がリポジトリ直下を sys.path に足している)
from playwright.sync_api import sync_playwright  # noqa: E402

OLD = int(time.time() * 1000) - 3600 * 1000   # 1 時間前(ドリルは直近 10 分に更新した文書を選ばない)
N_DRILL = 4
SPK = [{"id": "S1", "name": "テスト花子", "color": "#2f62d6"}]


def seg(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def tid_of(n):
    return "%012x" % (0xd0000 + n)


def write_doc(tx, n, video, segs, title, ev=True, updated=OLD, **over):
    d = {"schema": "transcribe/v1", "id": tid_of(n), "title": title, "sourcePath": video, "sourceName": os.path.basename(video), "model": "small",
         "start": 0, "end": 12.0, "duration": 12.0, "speakers": [], "segments": segs, "createdAt": 1, "updatedAt": updated}
    if ev:
        d["evalSet"] = True
    d.update(over)
    with open(os.path.join(tx, tid_of(n) + ".json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        video = make_video(os.path.join(srv.media, "評価テスト.webm"), sec=12)
        tx = os.path.join(srv.tmp, _layout.TOOL_DIRS["transcribe"], "transcripts")
        os.makedirs(tx, exist_ok=True)
        drill_ids = {tid_of(n) for n in range(1, N_DRILL + 1)}
        for n in range(1, N_DRILL + 1):   # ドリルに出る評価用 4 本(全行に話者・未校正)
            write_doc(tx, n, video, [seg(1, 0.5, 2.5, "はじめ%d" % n, speaker="S1"), seg(2, 3.0, 5.0, "つぎ%d" % n, speaker="S1"),
                                     seg(3, 6.0, 8.0, "おわり%d" % n, speaker="S1")], "評価テスト%02d" % n, speakers=SPK)
        write_doc(tx, 50, video, [seg(1, 0.5, 2.5, "学習用")], "学習用の文書", ev=False)                          # 評価用でない
        write_doc(tx, 51, video, [seg(1, 0.5, 2.5, "済み", speaker="S1", proofed=True)], "確かめ済みの文書", speakers=SPK,
                  evalReviewed={"at": OLD, "rows": 1, "durationSec": 12.0})                                       # もう確かめ済み
        # ドリルの外(確かめ済みのボタン)と全行をこの人に: 評価用・話者の無い行・題名に名簿の名前(配信の文脈)。直近に更新した = ドリルには出ない
        write_doc(tx, 60, video, [seg(1, 0.5, 2.5, "みこだよ"), seg(2, 3.0, 5.0, "にぇ", speaker="S1")], "さくらみこ 雑談",
                  updated=int(time.time() * 1000), speakers=[{"id": "S1", "name": "話者1", "color": "#2f62d6"}])

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            bad_http = []   # 読み込みの失敗は URL で見る
            pg.on("response", lambda r: bad_http.append("%d %s" % (r.status, r.url)) if r.status >= 400 else None)

            def doc_id():
                return pg.evaluate("S.docId")   # app.js の状態(トップレベルの const は evaluate から見える)

            def url_q():
                return pg.evaluate("Object.fromEntries(new URLSearchParams(location.search))")

            def wait_next(prev):
                wait_js(pg, "S.docId && S.docId !== %s && !document.querySelector('#doc').hidden && !DR.busy && document.querySelectorAll('#segs .seg').length > 0" % json.dumps(prev), 15000)
                return doc_id()

            # ---- 進行度のカードから始める ----
            pg.goto(srv.base + "#tx")
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            wait_js(pg, "document.querySelector('#drillLeft').textContent.includes('あと 15 分')", 10000)
            check("確かめ済み 1 本" in pg.inner_text("#drillLeft") and "まだ 5 本" in pg.inner_text("#drillLeft"),
                  "進行度のカードに定点(確かめ済みの動画)のあと何分: " + pg.inner_text("#drillLeft"))
            check("話者" in pg.inner_text("#drillConds") and "呼び名" in pg.inner_text("#drillConds"), "条件(話者・配信・重なり・BGM・呼び名)")
            check("目安" not in pg.inner_text("#evalStat") and "20分" not in pg.inner_text("#evalStat"), "以前の「目安 20 分」は出さない: " + pg.inner_text("#evalStat")[:80])
            pg.evaluate("window.__noReload = 1")   # ドリルの間に画面を読み直していないことの印
            pg.evaluate("setSideTab('quality')")
            pg.click("#drillGo")
            wait_js(pg, "!document.querySelector('#drillBar').hidden && S.docId && document.querySelectorAll('#segs .seg').length > 0 && !DR.busy", 15000)
            t1 = doc_id()
            pg.evaluate("toggleMenu(false)")   # 重ねて開くメニューの間はキーが文書に届かないので閉じる(下のキーの確かめのため)
            q = url_q()
            check(t1 in drill_ids and q.get("drill") == "1" and q.get("doc") == t1, "評価用の動画 1 本を開き、URL は ?doc=&drill=1: %s" % q)
            check("あと 15 分" in pg.inner_text("#drLeft") and "この動画: まだ" in pg.inner_text("#drPill") and "0 本済み" in pg.inner_text("#drCount"),
                  "帯: 定点まであと何分・この動画の状態・済ませた本数: %s / %s" % (pg.inner_text("#drLeft"), pg.inner_text("#drCount")))
            check("Shift" in pg.inner_text("#drDone") and "D" in pg.inner_text("#drDoneKey"), "「済みにして次へ」にキー(Shift+D): " + pg.inner_text("#drDone"))
            left0 = pg.inner_text("#drLeft")

            # ---- 行だけ再生は行の終わりで止まる(timeupdate だと平均 0.1 秒過ぎて、次の行の頭の言葉が聞こえた。EndGuard = app-core.js の stopAtEnd) ----
            if os.environ.get("YTT_E2E_NOGUARD"):
                pg.evaluate("window.armPlayEnd = () => {}")   # 測り比べ用(以前の止め方 = timeupdate だけ)
            pg.evaluate("document.querySelector('#player').muted = true")   # 音は出さない(音が無くても currentTime は進む)
            wait_js(pg, "document.querySelector('#player').readyState >= 3", 20000)
            overs = []
            for rate in (1, 1.5, 0.75):
                for i in (0, 1, 2):
                    r = pg.evaluate("""async ([i, rate]) => {
                      const p = document.querySelector('#player'), s = S.doc.segments[i];
                      p.playbackRate = rate; playSeg(s, true);
                      const t0 = performance.now();
                      while (!p.paused && performance.now() - t0 < 6000) await new Promise(r => setTimeout(r, 5));
                      await new Promise(r => setTimeout(r, 400));   // pause のあとに timeupdate などで動かないか
                      return { paused: p.paused, t: p.currentTime, end: s.end, start: s.start, playEnd: S.playEnd };
                    }""", [i, rate])
                    overs.append(round(r["t"] - r["end"], 3))
                    check(r["paused"] and r["playEnd"] is None and r["t"] > r["start"] + 0.5 and abs(r["t"] - r["end"]) <= 0.05,
                          "行 %d を %s× で再生 → 行の終わり %.2f に対し止まった位置 %.3f(差 %+.3f 秒。±0.05 以内)" % (i, rate, r["end"], r["t"], r["t"] - r["end"]))
            print("     止まる位置の差(秒): " + " ".join("%+.3f" % d for d in overs) + "  最大 %.3f" % max(abs(d) for d in overs), flush=True)
            pg.evaluate("document.querySelector('#player').playbackRate = 1")
            # 再生の途中で別の行の再生に替えても、前の行の終わりでは止まらない
            r = pg.evaluate("""async () => {
              const p = document.querySelector('#player'), a = S.doc.segments[0], b = S.doc.segments[2];
              playSeg(a, true); await new Promise(r => setTimeout(r, 600)); playSeg(b, true);
              const t0 = performance.now(); while (!p.paused && performance.now() - t0 < 6000) await new Promise(r => setTimeout(r, 5));
              return { t: p.currentTime, end: b.end };
            }""")
            check(abs(r["t"] - r["end"]) <= 0.05, "再生の途中で別の行に替えると、新しい行の終わりで止まる: %.3f / %.2f" % (r["t"], r["end"]))
            # 行だけ再生のあと、表示部の再生ボタンで再開したら止まらずに続く(S.playEnd が残らない)
            r = pg.evaluate("""async () => {
              const p = document.querySelector('#player'); p.currentTime = 6.5; S.playEnd = null; p.play().catch(() => {});
              await new Promise(r => setTimeout(r, 2500)); const out = { paused: p.paused, t: p.currentTime }; p.pause(); return out;
            }""")
            check(not r["paused"] and r["t"] > 8.5, "ふつうの再生は行の終わりで止まらない: %.2f" % r["t"])

            # ---- 1 行直して、すぐ「済みにして次へ」(自動保存を待たない = 未保存の変更も保存してから済みにする) ----
            ta = pg.locator("#segs .seg textarea").first
            old_text = ta.input_value()
            ta.fill(old_text + "(直した)")
            pg.click("#drDone")
            t2 = wait_next(t1)
            d1 = srv.get("/api/transcript?id=" + t1)
            check(any(g["text"] == old_text + "(直した)" for g in d1["segments"]), "直した文字は保存されている(済みにする前に保存)")
            check(isinstance(d1.get("evalReviewed"), dict) and all(g.get("proofed") and g.get("proofedAt") for g in d1["segments"]),
                  "確かめ済みの印と、全行が校正済み(proofedAt): %s" % d1.get("evalReviewed"))
            q = url_q()
            check(t2 in drill_ids and q.get("doc") == t2 and q.get("drill") == "1" and pg.evaluate("window.__noReload === 1"),
                  "次の文書が開く(画面の再読み込みなし・URL の doc が変わる・drill は残る)")
            wait_js(pg, "document.querySelector('#drLeft').textContent !== %s" % json.dumps(left0), 10000)
            check("24秒" in pg.inner_text("#drLeft") and "1 本済み" in pg.inner_text("#drCount"),
                  "定点の残りが減る・済ませた本数: %s / %s" % (pg.inner_text("#drLeft"), pg.inner_text("#drCount")))
            st = srv.get("/api/drill/status")
            check(st["reviewedSec"] == 24 and st["leftSec"] == 876, "あと何分(API): 確かめ済み %s 秒" % st["reviewedSec"])

            # ---- 飛ばす(Shift+N) ----
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("Shift+N")
            t3 = wait_next(t2)
            d2 = srv.get("/api/transcript?id=" + t2)
            check("evalReviewed" not in d2 and not any(g.get("proofed") for g in d2["segments"]), "飛ばすと済みにしない(Shift+N)")
            check("飛ばした 1 本" in pg.inner_text("#drCount"), "飛ばした数: " + pg.inner_text("#drCount"))

            # ---- 直してすぐ Shift+D(キー)。未保存の変更を失わない ----
            ta = pg.locator("#segs .seg textarea").nth(1)
            old3 = ta.input_value()
            ta.fill(old3 + "(キーで)")
            pg.keyboard.press("Escape")   # 文字の欄を抜けるとキーが効く
            pg.keyboard.press("Shift+D")
            t4 = wait_next(t3)
            d3 = srv.get("/api/transcript?id=" + t3)
            check(any(g["text"] == old3 + "(キーで)" for g in d3["segments"]) and isinstance(d3.get("evalReviewed"), dict),
                  "Shift+D でも、直した文字を保存してから済みにする")
            check(t4 != t2, "飛ばした文書は、このドリルでは出さない")

            # ---- 再読み込みしても続く(?doc=&drill=1・済ませた本数) ----
            pg.reload()
            wait_js(pg, "!document.querySelector('#drillBar').hidden && S.docId === %s && document.querySelectorAll('#segs .seg').length > 0" % json.dumps(t4), 15000)
            check("2 本済み" in pg.inner_text("#drCount"), "再読み込みしても、同じ文書と帯(済ませた本数)が続く: " + pg.inner_text("#drCount"))

            # ---- 話者の無い行の確認(やめる → このまま) ----
            check("全行に付いています" in pg.inner_text("#drSpkHint"), "帯: 話者が全行に付いている: " + pg.inner_text("#drSpkHint"))
            pg.locator("#segs .seg select.spk").first.select_option("")
            wait_js(pg, "document.querySelector('#drSpkHint').textContent.includes('話者の無い行 1 行')")
            check(True, "帯: 話者を外すと「話者の無い行 1 行」: " + pg.inner_text("#drSpkHint"))
            pg.click("#drSpk")
            wait_js(pg, "document.querySelector('#spDetails').open && !document.querySelector('#spDetails').hidden")
            check(pg.is_visible("#diarGo"), "帯の「話者を付ける…」で話者のカード(自動判別・全行をこの人に)が開く")
            pg.click("#drDone")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            dlg = pg.inner_text("dialog.ui-dialog[open]")
            check("話者が無い行が 1 行" in dlg and "評価用のフォルダへ移すには全行に話者が要ります" in dlg, "話者の無い行があると確かめる: " + dlg[:60].replace("\n", " "))
            pg.click("dialog.ui-dialog[open] .btn.ghost")
            wait_js(pg, "!document.querySelector('dialog.ui-dialog[open]') && !DR.busy")
            check(doc_id() == t4 and "evalReviewed" not in srv.get("/api/transcript?id=" + t4), "やめると済みにしない(同じ文書のまま)")
            pg.click("#drDone")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            pg.click("dialog.ui-dialog[open] .btn.primary")
            wait_js(pg, "!DR.busy && !document.querySelector('#drNone').hidden", 15000)   # 4 本のうち 1 本は飛ばしたので、次が無い
            d4 = srv.get("/api/transcript?id=" + t4)
            check(isinstance(d4.get("evalReviewed"), dict) and d4["segments"][0]["speaker"] == "", "このまま済みにする(話者の無い行も保存してから)")
            check("次に出せる評価用の動画がありません" in pg.inner_text("#drNone") and "飛ばした 1 本" in pg.inner_text("#drNone"),
                  "次が無いときは帯に理由: " + pg.inner_text("#drNone")[:80])
            check(doc_id() == t4 and "確かめ済み" in pg.inner_text("#drPill"), "次が無ければ今の文書のまま(確かめ済みの表示)")

            # ---- ドリルを終える ----
            pg.click("#drEnd")
            wait_js(pg, "document.querySelector('#drillBar').hidden")
            q = url_q()
            check("drill" not in q and q.get("doc") == t4, "終えると帯が消え、URL の drill も消える: %s" % q)
            check(not pg.is_hidden("#evrBox") and "確かめ済み" in pg.inner_text("#evrPill"), "ドリルの外では校正の画面に「確かめ済み」")
            check(pg.is_disabled("#evrRedo") and "確かめ済みを取り消して" in (pg.get_attribute("#evrRedo", "title") or ""),
                  "確かめ済みの文書では「この動画を作り直す」を押せず、理由を出す: " + (pg.get_attribute("#evrRedo", "title") or ""))
            wait_js(pg, "document.querySelector('#drillLeft').textContent.includes('確かめ済み 4 本')", 10000)
            check(True, "進行度のカードも増えた: " + pg.inner_text("#drillLeft"))

            # ---- ドリルの外: 評価用の文書の「全部聞いて直したので済みにする」と取り消し ----
            open_doc(pg, "さくらみこ 雑談")
            wait_js(pg, "S.docId === %s && !document.querySelector('#evrBox').hidden" % json.dumps(tid_of(60)), 10000)
            check("まだ確かめていない" in pg.inner_text("#evrPill") and pg.is_visible("#evrMark"), "評価用の文書を開くと「まだ確かめていない」とボタン")
            check(pg.is_visible("#evrRedo") and not pg.is_disabled("#evrRedo"), "ドリルの外の欄にも「この動画を作り直す(今の設定で)」")
            pg.click("#evrMark")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            pg.click("dialog.ui-dialog[open] .btn.primary")   # 話者の無い行がある → このまま
            wait_js(pg, "document.querySelector('#evrPill').textContent === '確かめ済み'", 10000)
            d60 = srv.get("/api/transcript?id=" + tid_of(60))
            check(isinstance(d60.get("evalReviewed"), dict) and d60["evalReviewed"].get("via") == "editor" and all(g.get("proofed") for g in d60["segments"]),
                  "ドリルの外でも同じ印を付けられる(残りの行も校正済み)")
            check(pg.locator("#segs .seg.proofed").count() == 2, "画面の行も校正済みに(読み直し)")
            pg.click("#evrUndo")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            pg.click("dialog.ui-dialog[open] .btn.primary")
            wait_js(pg, "document.querySelector('#evrPill').textContent === 'まだ確かめていない'", 10000)
            d60 = srv.get("/api/transcript?id=" + tid_of(60))
            check("evalReviewed" not in d60 and not any(g.get("proofed") for g in d60["segments"]), "取り消すと印と、印が校正済みにした行も戻る")

            # ---- 全行をこの人に ----
            pg.click("#btnSpk")
            pg.click("[data-jump=spDetails]")
            wait_js(pg, "document.querySelector('#spDetails').open === true")
            wait_js(pg, "!document.querySelector('#spAllBox').hidden && document.querySelector('#spAllName').value === 'さくらみこ'", 10000)
            check("1 行" in pg.inner_text("#spAllHint"), "評価用で話者の無い行があると「全行をこの人に」が出て、候補(配信の文脈)を選んである: " + pg.inner_text("#spAllHint")[:40])
            labels = pg.evaluate("[...document.querySelectorAll('#spAllName option')].map(o => o.textContent)")
            check(any("配信の文脈" in x for x in labels) and labels[-1].startswith("ほかの名前"), "候補にどこから出たかを書く: %s" % labels[:3])
            pg.click("#spAllGo")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            check("さくらみこ" in pg.inner_text("dialog.ui-dialog[open]") and "置き換わります" in pg.inner_text("dialog.ui-dialog[open]"), "確認のダイアログ(今の話者も置き換わる)")
            pg.click("dialog.ui-dialog[open] .btn.primary")
            for _ in range(100):
                d = srv.get("/api/transcript?id=" + tid_of(60))
                if [s["name"] for s in d["speakers"]] == ["さくらみこ"]:
                    break
                time.sleep(0.1)
            check([s["name"] for s in d["speakers"]] == ["さくらみこ"] and all(g["speaker"] == "S1" for g in d["segments"]), "全行がその人に(既存の 1人指定)")
            check(os.path.isfile(os.path.join(tx, tid_of(60) + ".diar.json")), "話者判別の記録(diar.json)も書く")
            wait_js(pg, "document.querySelector('#spAllBox').hidden", 10000)
            check(True, "全行に話者が付いたら欄は消える")

            # ---- キーの一覧(?)に評価ドリルのキー ----
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("?")
            pg.wait_for_selector("#keys[open]")
            kl = pg.inner_text("#keysList")
            check("評価ドリル" in kl and "済みにして次へ" in kl and "飛ばして次へ" in kl, "キーの一覧に評価ドリルのキー")

            # ---- 評価用の文字起こしのあと、話者を自動で判別して名前まで付ける(v0.50.0) ----
            v2 = make_video(os.path.join(srv.media, "自動の話者.webm"), sec=12)
            ta_id = srv.transcribe(v2, title="さくらみこ 雑談 自動", evalSet=True)
            dj = None
            for _ in range(300):   # 文字起こしの続きで足された判別のジョブ(自動)が終わるまで
                js = [x for x in srv.get("/api/jobs")["jobs"] if x["kind"] == "diarize" and x["tid"] == ta_id]
                if js and js[0]["state"] in ("done", "error", "cancelled"):
                    dj = js[0]
                    break
                time.sleep(0.1)
            check(dj is not None and dj["state"] == "done" and dj.get("auto") is True, "評価用の文字起こしのあと、話者の判別のジョブが自動で足されて終わる: %s" % (dj and dj["state"]))
            da = srv.get("/api/transcript?id=" + ta_id)
            names = {s["id"]: s["name"] for s in da.get("speakers") or []}
            check(names.get("S1") == "さくらみこ" and all(g["speaker"] in names for g in da["segments"] if g["text"].strip()),
                  "いちばん長く話した人に名前の候補(配信の文脈)・全行に話者: %s" % names)
            check((da.get("diarization") or {}).get("auto") is True and (da.get("diarization") or {}).get("contextName") == "さくらみこ", "文書に自動で付けた印")
            with open(os.path.join(tx, ta_id + ".diar.json"), encoding="utf-8") as f:
                dv = json.load(f)["latest"]["voices"]
            check(dv["speakers"]["S1"]["by"] == "context" and dv["context"]["name"] == "さくらみこ", "diar.json に誰が付けたか(by: context)")
            pg.goto(srv.base + "?doc=%s&drill=1#tx" % ta_id)
            wait_js(pg, "!document.querySelector('#drillBar').hidden && S.docId === %s && document.querySelectorAll('#segs .seg').length > 0" % json.dumps(ta_id), 15000)
            wait_js(pg, "!document.querySelector('#drAutoSpk').hidden", 10000)
            check("自動で付けてあります" in pg.inner_text("#drAutoSpk") and "さくらみこ" in pg.inner_text("#drAutoSpk"),
                  "ドリルで開くと話者付き・帯に「自動で付けてあります」: " + pg.inner_text("#drAutoSpk"))
            check("全行に付いています" in pg.inner_text("#drSpkHint"), "帯: 話者が全行に付いている: " + pg.inner_text("#drSpkHint"))
            check(pg.locator("#segs .seg select.spk").first.input_value() == "S1", "行の話者の欄も付いている")

            # ---- この動画を作り直す(今の設定で。1 本ずつ。2026-10-05): 帯のボタン → 手を入れた行の確認 → 作り直り → 文書を読み直す ----
            wait_js(pg, "!lockJob() && !S.jobs.some(j => ACTIVE.has(j.state))", 15000)
            check(pg.is_visible("#drRedo") and not pg.is_disabled("#drRedo"), "帯に「この動画を作り直す(今の設定で)」")
            pg.evaluate("window.__noReload = 2")
            ta = pg.locator("#segs .seg textarea").first
            ta.fill(ta.input_value() + "(作り直し前に直した)")   # 自動保存を待たずに押す = 押したときに保存してから送る
            pg.click("#drRedo")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            dlg = pg.inner_text("dialog.ui-dialog[open]")
            check("直した 1 行" in dlg and "置き換わります" in dlg and "以前の版に戻す" in dlg, "手を入れた文書は確認する(直した行の数): " + dlg[:90].replace("\n", " "))
            check(any("(作り直し前に直した)" in g["text"] for g in srv.get("/api/transcript?id=" + ta_id)["segments"]), "押したときに未保存の変更を保存してから送る")
            check(not [j for j in srv.get("/api/jobs")["jobs"] if j.get("redoOne")], "確認の前にはジョブを足さない")
            pg.click("dialog.ui-dialog[open] .btn.primary")
            wait_js(pg, "!lockJob() && S.doc && (S.doc.recognition || {}).runs && S.doc.recognition.runs.some(r => r.kind === 'evalRedo')"
                    " && !S.doc.segments.some(s => s.text.includes('作り直し前'))", 30000)
            dr = srv.get("/api/transcript?id=" + ta_id)
            rj = [j for j in srv.get("/api/jobs")["jobs"] if j.get("redoOne")]
            check(len(rj) == 1 and rj[0]["state"] == "done" and not rj[0]["redoSkipped"] and rj[0]["tid"] == ta_id, "作り直しのジョブ(1 本ずつ)が終わる: %s" % [(j["state"], j["redoSkipped"]) for j in rj])
            check(not any("作り直し前" in g["text"] for g in dr["segments"]) and sum(1 for r_ in dr["recognition"]["runs"] if r_.get("kind") == "evalRedo") == 1,
                  "文書が今の設定の文字起こしに置き換わり、前の機械の出力は記録に残る")
            check(pg.evaluate("window.__noReload === 2") and pg.evaluate("S.docId") == ta_id, "画面は読み直さず、同じ文書を開き直す")
            hist = srv.get("/api/history?id=" + ta_id)
            check(bool(hist.get("items") if isinstance(hist, dict) else hist), "前の版は「以前の版に戻す」に残る")
            # 作り直しの間は編集を止める(疑似の認識はすぐ終わるので、作り直しのジョブを画面の状態に置いて確かめる)
            lk = pg.evaluate("""() => { const keep = S.jobs;
              S.jobs = [{ id: 'x', kind: 'transcribe', state: 'running', phase: '認識中', progress: 0.5, tid: null, into: S.docId, redo: true, redoOne: true }];
              applyLock(); const out = { lock: !!lockJob(), inert: document.querySelector('#segs').inert, banner: document.querySelector('#diarBanner').textContent,
                hidden: document.querySelector('#diarBanner').hidden, dis: document.querySelector('#drRedo').disabled, done: document.querySelector('#drDone').disabled };
              renderDrillBar(); out.done = document.querySelector('#drDone').disabled;
              S.jobs = keep; applyLock(); renderDrillBar(); return out; }""")
            check(lk["lock"] and lk["inert"] and not lk["hidden"] and "作り直" in lk["banner"] and lk["dis"] and lk["done"],
                  "作り直しの間は編集できない(行の一覧を止め、帯で知らせる・作り直す/済みにするは押せない): %s" % lk["banner"][:50])
            check(not pg.evaluate("document.querySelector('#segs').inert"), "終われば編集できる")
            b.close()
        bad = [e for e in errors if "favicon" not in e and "ERR_ABORTED" not in e]
        check(not bad, "画面のエラーなし: %s" % bad[:3])
        bad_http = [x for x in bad_http if "favicon" not in x and not ("404" in x and "/api/eval-batch" in x)   # まとめての文字起こしの状態(⚙)は、API が無ければ出さない作り
                    and not ("409" in x and "/api/archive" in x)   # 文書を続けて切り替えると、前の文書の自動の保管が「別の保管の最中」で飛ばされる(黙って次の機会に)
                    and not ("409" in x and "/api/eval-batch/redo-one" in x)]   # 手を入れた文書の作り直し: まず 409 touched を受けて確認する作り
        check(not bad_http, "読み込みの失敗なし: %s" % bad_http[:3])
    finally:
        srv.stop()
    print("\n結果:", "すべて成功" if check.ok else "失敗あり")
    sys.exit(0 if check.ok else 1)


if __name__ == "__main__":
    main()
