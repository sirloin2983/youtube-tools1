#!/usr/bin/env python3
"""話者の声を覚える(A-3。docs/archive/backlog-ui-2026-09-27.md)の画面の確認(疑似モード。声の特徴は偽の話者判別と同じ区切りで作る)。

    python e2e_edit_voices.py

名前を付ける前は「声を覚える」を押せない → 名前を付けて覚える → 判別し直すと、覚えた声の話者に名前が付く →
覚えている声の一覧から「忘れる」→ 判別し直しても名前は付かない、を確かめる。
段1(監査02・17・18): 校正済みの行だけを使う・覚える前の確認(人・行・秒・覚えない名前)・一般的な名前は覚えない・
既にある名前は「同じ人ですか」・評価用はボタンが押せず理由が出る・API へ直接送っても評価用は 400。
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

from e2e_edit_common import Checks, Server, make_video, open_doc, wait_js


def wait_job(srv, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = next((x for x in srv.get("/api/jobs")["jobs"] if x["id"] == jid), None)
        if j and j["state"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.1)
    raise RuntimeError("ジョブが終わりません: %s" % jid)


def wait_until(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.1)
    return False


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        v = make_video(os.path.join(srv.media, "声の確認.webm"), sec=30)
        tid = srv.transcribe(v, "声の確認")
        j = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2})["id"])
        check(j["state"] == "done" and j["speakers"] == 2 and not j["named"], "(準備)話者を判別した(まだ声を覚えていないので名前は付かない)")
        check("smoothed" not in srv.get("/api/transcript?id=" + tid)["diarization"], "細切れをならすは既定でオフ(文書の diarization に smoothed が無い)")
        js = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2, "smooth": True})["id"])
        check(js["state"] == "done" and srv.get("/api/transcript?id=" + tid)["diarization"].get("smoothed") == 0,
              "API: smooth: true で判別すると文書の diarization に smoothed(ならした行の数)が付く(疑似の判別には、ならす行は無い)")

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_context(viewport={"width": 1440, "height": 950}).new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(srv.base + "#tx")
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "声の確認")
            pg.wait_for_selector("#segs .seg")
            pg.click("#btnSpk")
            pg.click("[data-jump=spDetails]")
            wait_js(pg, "document.querySelector('#spDetails').open === true")
            wait_js(pg, "document.querySelector('#voiceLearnHint').textContent.length > 0", 5000)
            check(pg.is_disabled("#voiceLearn") and "名前を付けて" in pg.inner_text("#voiceLearnHint"),
                  "仮の名前(話者1・話者2)のままでは「声を覚える」を押せない: " + pg.inner_text("#voiceLearnHint"))
            check(pg.is_checked("#diarRecog"), "「判別したら、覚えている声と比べて名前を付ける」は既定でオン")
            # 話者の細切れをならす(S2。試験中・既定オフ・設定 diarSmooth = api/settings/patch)
            check(not pg.is_checked("#diarSmooth") and srv.get("/api/settings").get("diarSmooth") is None, "「短い 1 行だけ別の人になるのをならす」は既定でオフ")
            pg.click("#diarSmooth")
            check(wait_until(lambda: srv.get("/api/settings").get("diarSmooth") is True, 5), "押すと設定 diarSmooth が保存される")
            pg.click("#diarSmooth")
            check(wait_until(lambda: srv.get("/api/settings").get("diarSmooth") is False, 5), "もう一度押すとオフ")
            wait_js(pg, "document.querySelector('#voiceCount').textContent.length > 0", 5000)
            check("まだ" in pg.inner_text("#voiceCount"), "覚えている声はまだ無い")
            # 話者1 に名前を付ける・話者2 は一般的な名前(本人)にする
            for k, nm in ((0, "兎田ぺこら"), (1, "本人")):
                name_in = pg.locator("#spList .sp-row").nth(k).locator("input[type=text]")
                name_in.fill(nm)
                name_in.press("Enter")
                name_in.dispatch_event("change")
            wait_js(pg, "!document.querySelector('#voiceLearn').disabled", 5000)
            check("兎田ぺこら" in pg.inner_text("#voiceLearnHint"), "名前を付けると押せる(誰の声を覚えるか出る): " + pg.inner_text("#voiceLearnHint"))
            # 監査17: まだ校正していないので、覚えられる行が無い(ジョブを作らずに理由を出す)
            jobs0 = len(srv.get("/api/jobs")["jobs"])
            pg.click("#voiceLearn")
            check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('覚えられる話者がいません') >= 0 && t.textContent.indexOf('未校正') >= 0)", 10000),
                  "校正済みの行が無いと覚えない(知らせに「未校正」の数)")
            check(len(srv.get("/api/jobs")["jobs"]) == jobs0 and pg.evaluate("!document.querySelector('#dlgConfirm').open"), "そのときはジョブも確認のダイアログも出ない")
            # 行を全部「校正済み」にする(行の右のボタン)
            n_rows = pg.locator("#segs .seg .pf[aria-pressed=false]").count()
            for _ in range(n_rows):
                pg.locator("#segs .seg .pf[aria-pressed=false]").first.click()
            check(pg.locator("#segs .seg .pf[aria-pressed=true]").count() == n_rows > 0, "(準備)行を %d 行とも校正済みにした" % n_rows)
            pg.click("#voiceLearn")
            pg.wait_for_selector("#dlgConfirm[open]", timeout=15000)
            txt = pg.inner_text("#cfText")
            check("兎田ぺこら" in txt and "行・" in txt and "秒" in txt, "覚える前に、誰の声を何行・何秒で覚えるかが出る: " + txt.replace("\n", " / "))
            check("本人" in txt and "一般的な名前" in txt, "一般的な名前(本人)は覚えないと出る: " + txt.replace("\n", " / "))
            pg.click("#cfOk")
            wait_js(pg, "document.querySelector('#voiceCount').textContent.indexOf('1人') >= 0", 30000)
            check("兎田ぺこら" in (pg.text_content("#voiceList") or ""), "覚えている声の一覧に出る: " + (pg.text_content("#voiceList") or ""))
            vs = srv.get("/api/voices")["voices"]
            check([x["name"] for x in vs.get("voxceleb", [])] == ["兎田ぺこら"], "一般的な名前(本人)の声は覚えていない: %s" % vs)
            rows1 = vs["voxceleb"][0]["rows"]
            # 監査18: 2回目は「同じ人ですか」。やめると覚えない・「同じ人」なら前の声に足す
            pg.click("#voiceLearn")
            pg.wait_for_selector("#dlgConfirm[open]", timeout=15000)
            check("もう覚えている" in pg.inner_text("#cfText"), "既にある名前は確認の中で知らせる: " + pg.inner_text("#cfText").replace("\n", " / "))
            pg.click("#cfOk")
            wait_js(pg, "document.querySelector('#dlgConfirm').open && document.querySelector('#cfT').textContent === '同じ人ですか'", 5000)
            check("兎田ぺこら" in pg.inner_text("#cfText") and "行" in pg.inner_text("#cfText"), "「同じ人ですか」に前に覚えた行・長さが出る: " + pg.inner_text("#cfText").replace("\n", " / "))
            pg.click("#cfCancel")
            check(wait_js(pg, "[...document.querySelectorAll('.ui-toast')].some(t => t.textContent.indexOf('覚える人がいないので') >= 0)", 5000), "「同じ人ですか」をやめると覚えない")
            pg.click("#voiceLearn")
            pg.wait_for_selector("#dlgConfirm[open]", timeout=15000)
            pg.click("#cfOk")
            wait_js(pg, "document.querySelector('#dlgConfirm').open && document.querySelector('#cfT').textContent === '同じ人ですか'", 5000)
            pg.click("#cfOk")
            end = time.time() + 30
            while time.time() < end and srv.get("/api/voices")["voices"]["voxceleb"][0]["rows"] == rows1:
                time.sleep(0.2)
            check(srv.get("/api/voices")["voices"]["voxceleb"][0]["rows"] == rows1 * 2, "「同じ人」なら前の声に足す(行の数が増える)")
            r = srv.call("POST", "/api/voices/learn", {"tid": tid, "embedding": "voxceleb", "names": ["兎田ぺこら"]})
            check(r.get("_status") == 409 and r.get("error") == "confirm_same" and r.get("names") == ["兎田ぺこら"], "API: 既にある名前を確かめずに送ると 409: %s" % r)
            r = srv.call("POST", "/api/voices/learn", {"tid": tid, "embedding": "voxceleb"})
            check(r.get("_status") == 400, "API: 覚える人の指定(names)が無い古い形は 400: %s" % r)
            # 監査02: 評価用にすると押せず、理由が出る。API へ直接送っても 400
            pg.check("#evalSet")
            wait_js(pg, "document.querySelector('#voiceLearn').disabled", 5000)
            check(pg.is_disabled("#voiceLearn") and "評価用" in pg.inner_text("#voiceLearnHint"), "評価用にすると押せず、理由が出る: " + pg.inner_text("#voiceLearnHint"))
            end = time.time() + 15
            while time.time() < end and srv.get("/api/transcript?id=" + tid).get("evalSet") is not True:
                time.sleep(0.2)
            r = srv.call("POST", "/api/voices/learn", {"tid": tid, "embedding": "voxceleb", "names": ["兎田ぺこら"], "confirmSame": ["兎田ぺこら"]})
            check(r.get("_status") == 400 and r.get("error") == "eval_set", "API: 評価用の文書で覚えようとすると 400(画面だけで止めていない): %s" % r)
            check(srv.get("/api/voices/preview?tid=" + tid + "&embedding=voxceleb").get("evalSet") is True, "確認の API も評価用を返す")
            pg.uncheck("#evalSet")
            wait_js(pg, "!document.querySelector('#voiceLearn').disabled", 5000)
            end = time.time() + 15
            while time.time() < end and srv.get("/api/transcript?id=" + tid).get("evalSet") is True:
                time.sleep(0.2)
            saved = [os.path.join(r, n) for r, _, ns in os.walk(srv.tmp) for n in ns if n == "voxceleb.json"]
            check(len(saved) == 1 and os.path.basename(os.path.dirname(saved[0])) == "voices", "声の特徴は作業データの voices/ に保存する(判別モデルごと): %s" % saved)
            vs = srv.get("/api/voices")["voices"]
            check(vs.get("voxceleb", [{}])[0].get("name") == "兎田ぺこら" and "vec" not in vs["voxceleb"][0], "一覧の API は名前・行の数・秒だけ(特徴そのものは返さない)")
            # 判別し直す(名前は「話者n」に戻る)→ 覚えた声で名前が付く
            j = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2})["id"])
            check([x["name"] for x in j["named"]] == ["兎田ぺこら"], "判別し直すと、覚えた声の話者に名前が付く(照らし合わせは校正の有無を問わない): %s" % j["named"])
            d = srv.get("/api/transcript?id=" + tid)
            check([s["name"] for s in d["speakers"]] == ["兎田ぺこら", "話者2"], "文書の話者の名前: %s" % [s["name"] for s in d["speakers"]])
            # 照らし合わせをしない指定
            j = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2, "recognize": False})["id"])
            check(not j["named"], "recognize: false なら名前を付けない(「話者n」のまま)")
            # 忘れる(2回押し)
            pg.reload()
            wait_js(pg, "document.querySelector('#ver').textContent.startsWith('v')")
            open_doc(pg, "声の確認")
            pg.click("#btnSpk")
            pg.click("[data-jump=spDetails]")
            wait_js(pg, "document.querySelector('#voiceCount').textContent.indexOf('1人') >= 0", 10000)
            pg.click("#voiceBox summary")
            btn = pg.locator("#voiceList [data-act=vdel]").first
            btn.click()
            btn.click()
            wait_js(pg, "document.querySelector('#voiceCount').textContent.indexOf('まだ') >= 0", 10000)
            check(srv.get("/api/voices")["voices"] == {}, "「忘れる」(2回押し)で覚えた声を消す")
            j = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2})["id"])
            check(not j["named"], "忘れたあとは、判別しても名前は付かない")
            check(not errors, "画面のエラー・コンソールのエラーが無い: %s" % errors[:5])
            b.close()
    finally:
        srv.stop()
    print("ALL PASSED" if check.ok else "SOME FAILED")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
