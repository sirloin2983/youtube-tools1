#!/usr/bin/env python3
"""評価ドリル(editor/drill.html・drill.js・ed_drill.py。マスタープラン Q4 = docs/plan/q3-q4-design.md の (c))と、
話者のカードの「全行をこの人に」の通し確認。入口に取り込んだ形(CSP・合言葉)で動かす。

    PYTHONIOENCODING=utf-8 py -3.10 editor/tests/e2e_drill.py

ドリル: 定点の「あと何分」と条件 → 始める → 20 行(同じ文書から 2 行まで)→ 自動で再生して行の終わりで止まる → 直して Enter で済み(保存・次へ)→
新しい名前の話者 → 飛ばす(D)→ 別の所で変わった文書は 409 の案内で飛ばす → 残りを Enter だけで済ませる → 終わり・あと何分が減る → 編集の進行度のカードにも出る。
全行をこの人に: 評価用で話者の無い行がある文書 → 候補(配信の文脈 = 題名の名簿の名前)→ 確認 → 全行がその人に(diar.json も)→ 欄が消える
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
N_DOCS = 12


def seg(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def tid_of(n):
    return "%012x" % (0xd0000 + n)


def write_doc(tx, n, video, segs, title, ev=True, updated=OLD, **over):
    d = {"schema": "transcribe/v1", "id": tid_of(n), "title": title, "sourcePath": video, "sourceName": os.path.basename(video),
         "start": 0, "end": 12.0, "duration": 12.0, "speakers": [], "segments": segs, "createdAt": 1, "updatedAt": updated}
    if ev:
        d["evalSet"] = True
    d.update(over)
    with open(os.path.join(tx, tid_of(n) + ".json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


def pos(pg):
    return pg.inner_text("#drPos")


def wait_pos(pg, text, timeout=10000):
    wait_js(pg, "document.querySelector('#drPos').textContent === %s || !document.querySelector('#drEnd').hidden" % json.dumps(text), timeout)


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        video = make_video(os.path.join(srv.media, "評価テスト.webm"), sec=12)
        tx = os.path.join(srv.tmp, _layout.TOOL_DIRS["transcribe"], "transcripts")
        os.makedirs(tx, exist_ok=True)
        titles = {}
        for n in range(1, N_DOCS + 1):   # 評価用 12 本 × 未校正 3 行(+ 校正済み 1 行)
            titles["評価テスト%02d" % n] = tid_of(n)
            write_doc(tx, n, video, [seg(1, 0.5, 2.5, "はじめ%d" % n), seg(2, 3.0, 5.0, "つぎ%d" % n), seg(3, 6.0, 8.0, "おわり%d" % n),
                                     seg(4, 8.5, 10.5, "済み%d" % n, proofed=True)], "評価テスト%02d" % n)
        write_doc(tx, 50, video, [seg(1, 0.5, 2.5, "学習用")], "学習用の文書", ev=False)
        # 全行をこの人に: 評価用・話者の無い行・題名に名簿の名前(配信の文脈)。直近に更新した = ドリルには出ない
        write_doc(tx, 60, video, [seg(1, 0.5, 2.5, "みこだよ"), seg(2, 3.0, 5.0, "にぇ", speaker="S1")], "さくらみこ 雑談",
                  updated=int(time.time() * 1000), speakers=[{"id": "S1", "name": "話者1", "color": "#2f62d6"}])

        with sync_playwright() as pw:
            b = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            bad_http = []   # 読み込みの失敗は URL で見る(409 はドリルの 409 の確かめで、わざと起こす)
            pg.on("response", lambda r: bad_http.append("%d %s" % (r.status, r.url)) if r.status >= 400 and not (r.status == 409 and "/api/drill/row" in r.url) else None)

            # ---- 定点の「あと何分」と条件 ----
            pg.goto(srv.base + "drill.html")
            wait_js(pg, "document.querySelector('#drConds').children.length >= 5")
            check("あと 15 分" in pg.inner_text("#drLeft"), "定点の「あと何分」: " + pg.inner_text("#drLeft"))
            check(pg.locator("#drConds li").count() == 5 and pg.locator("#drConds .pill.wait").count() == 5,
                  "条件 5 つ(話者・配信・重なり・BGM・呼び名)がまだ: " + pg.inner_text("#drConds").replace("\n", " "))
            check(pg.evaluate("getComputedStyle(document.querySelector('#drGo')).backgroundColor") not in ("", "rgba(0, 0, 0, 0)"),
                  "ui-kit の CSS(ui-kit.css = index.html から切り出し)が効いている")

            # ---- 始める: 20 行・同じ文書から 2 行まで ----
            left0 = pg.inner_text("#drLeft")
            pg.click("#drGo")
            wait_js(pg, "!document.querySelector('#drRun').hidden")
            check(pos(pg) == "1 / 20", "20 行を出す: " + pos(pg))
            rows = pg.evaluate("D.rows.map(r => r.id)")   # drill.js の状態(トップレベルの const は evaluate から見える)
            per = {t: rows.count(t) for t in set(rows)}
            check(len(rows) == 20 and max(per.values()) <= 2 and tid_of(50) not in per and tid_of(60) not in per,
                  "評価用だけ・同じ文書から 2 行まで・直近に更新した文書は除く: %s" % sorted(per.values()))

            # ---- 自動で再生して、行の終わりで止まる ----
            wait_js(pg, "(() => { const v = document.querySelector('#drVideo'); return v.currentTime > 0.3 && !v.paused; })()", 15000)
            check(True, "行を自動で再生する")
            wait_js(pg, "document.querySelector('#drVideo').paused", 8000)
            check(pg.evaluate("document.querySelector('#drVideo').currentTime") < 11, "行の終わりで止まる(動画の終わりまで流さない)")
            check(pg.evaluate("document.activeElement && document.activeElement.id") == "drText", "文字の欄にフォーカス(すぐ直せる)")

            def cur_tid():
                return titles.get(pg.inner_text("#drDoc").strip())

            # ---- 直して Enter で済み ----
            t1, text1 = cur_tid(), pg.input_value("#drText")
            pg.fill("#drText", text1 + "(直した)")
            pg.keyboard.press("Enter")
            wait_pos(pg, "2 / 20")
            d1 = srv.get("/api/transcript?id=" + t1)
            g1 = next(g for g in d1["segments"] if g["text"] == text1 + "(直した)")
            check(g1.get("proofed") is True and g1.get("proofedAt") and d1["updatedAt"] > OLD, "直して Enter = 行ごとに保存(校正済み・proofedAt・updatedAt が上がる)")
            check(d1.get("effort", {}).get("proofedRows") == 1, "校正の手間に数える")

            # ---- 新しい名前の話者 ----
            t2 = cur_tid()
            pg.select_option("#drSpk", "other")
            check(pg.is_visible("#drSpkNew"), "「ほかの名前を入れる…」で名前の欄が出る")
            pg.fill("#drSpkNew", "テスト花子")
            pg.click("#drDone")
            wait_pos(pg, "3 / 20")
            d2 = srv.get("/api/transcript?id=" + t2)
            sp = {s["id"]: s["name"] for s in d2["speakers"]}
            check("テスト花子" in sp.values() and any(sp.get(g["speaker"]) == "テスト花子" and g.get("proofed") for g in d2["segments"]),
                  "新しい名前は話者の一覧に足して、その行に付く")

            # ---- 飛ばす(D) ----
            t3 = cur_tid()
            pg.keyboard.press("Escape")   # 文字の欄を抜けると単体キーが効く
            pg.keyboard.press("d")
            wait_pos(pg, "4 / 20")
            d3 = srv.get("/api/transcript?id=" + t3)
            check(d3["updatedAt"] == OLD or t3 in (t1, t2), "飛ばすと保存しない(D)")

            # ---- 409: 別の所で変わった文書 ----
            t4 = cur_tid()
            doc = srv.get("/api/transcript?id=" + t4)
            proofed4 = {g["id"] for g in doc["segments"] if g.get("proofed")}   # 同じ文書の前の行を、先に済みにしていることがある
            doc["title"] = doc["title"]   # 中身はそのまま、別の画面からの保存で updatedAt だけ進める
            r = srv.call("PUT", "/api/transcript?id=" + t4, dict(doc, baseUpdatedAt=doc["updatedAt"]))
            check("_status" not in r, "(準備)別の画面から保存した")
            pg.click("#drDone")
            wait_js(pg, "!document.querySelector('#drNote').hidden", 8000)
            check("別の所" in pg.inner_text("#drNote") and pos(pg).startswith("5 / "), "409 は「別の所で変わった」と案内して飛ばす: " + pg.inner_text("#drNote")[:60])
            check({g["id"] for g in srv.get("/api/transcript?id=" + t4)["segments"] if g.get("proofed")} == proofed4, "409 の行は保存しない")

            # ---- 残りは Enter だけで ----
            for _ in range(25):
                if not pg.is_hidden("#drEnd"):
                    break
                before = pos(pg)
                pg.focus("#drText")
                pg.keyboard.press("Enter")
                wait_js(pg, "document.querySelector('#drPos').textContent !== %s || !document.querySelector('#drEnd').hidden" % json.dumps(before), 10000)
            wait_js(pg, "!document.querySelector('#drEnd').hidden", 10000)
            summ = pg.inner_text("#drSum").replace("\n", " ")
            check("済み" in summ and "飛ばした 1 行" in summ and "別の所で変わっていた" in summ, "終わりのまとめ: " + summ)
            wait_js(pg, "document.querySelector('#drLeft').textContent !== %s" % json.dumps(left0), 8000)
            check(True, "定点の校正済みが増えた: " + pg.inner_text("#drLeft"))
            st = srv.get("/api/drill/status")
            check(st["proofedSec"] > 20 and st["leftSec"] < 900, "あと何分(API)が減る: %s 秒" % st["leftSec"])

            # ---- 編集の進行度のカード(精度)にも出る・ドリルへのリンク ----
            pg.goto(srv.base + "#tx")
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            wait_js(pg, "document.querySelector('#drillLeft').textContent.includes('あと')", 10000)
            check("あと" in pg.inner_text("#drillLeft") and "話者" in pg.inner_text("#drillConds"),
                  "進行度のカードに定点のあと何分と条件: " + pg.inner_text("#drillLeft"))
            check(pg.get_attribute("#drillLink", "href") == "drill.html", "進行度のカードから評価ドリルへ(相対パス)")

            # ---- 全行をこの人に ----
            open_doc(pg, "さくらみこ 雑談")
            pg.wait_for_selector("#segs .seg")
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

            b.close()
        bad = [e for e in errors if "favicon" not in e and "ERR_ABORTED" not in e]
        check(not bad, "画面のエラーなし: %s" % bad[:3])
        bad_http = [x for x in bad_http if "favicon" not in x and not ("404" in x and "/api/eval-batch" in x)]   # まとめての文字起こしの状態(⚙)は、API が無ければ出さない作り
        check(not bad_http, "読み込みの失敗なし(わざと起こした 409 のほか): %s" % bad_http[:3])
    finally:
        srv.stop()
    print("\n結果:", "すべて成功" if check.ok else "失敗あり")
    sys.exit(0 if check.ok else 1)


if __name__ == "__main__":
    main()
