#!/usr/bin/env python3
"""話者の声を覚える(A-3。docs/backlog-ui-2026-09-27.md)の画面の確認(疑似モード。声の特徴は偽の話者判別と同じ区切りで作る)。

    python e2e_edit_voices.py

名前を付ける前は「声を覚える」を押せない → 名前を付けて覚える → 判別し直すと、覚えた声の話者に名前が付く →
覚えている声の一覧から「忘れる」→ 判別し直しても名前は付かない、を確かめる。
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


def main():
    check = Checks()
    srv = Server(mounted=True)
    errors = []
    try:
        v = make_video(os.path.join(srv.media, "声の確認.webm"), sec=30)
        tid = srv.transcribe(v, "声の確認")
        j = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2})["id"])
        check(j["state"] == "done" and j["speakers"] == 2 and not j["named"], "(準備)話者を判別した(まだ声を覚えていないので名前は付かない)")

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
            wait_js(pg, "document.querySelector('#voiceCount').textContent.length > 0", 5000)
            check("まだ" in pg.inner_text("#voiceCount"), "覚えている声はまだ無い")
            # 話者1 に名前を付ける → 覚える
            name_in = pg.locator("#spList .sp-row").first.locator("input[type=text]")
            name_in.fill("兎田ぺこら")
            name_in.press("Enter")
            name_in.dispatch_event("change")
            wait_js(pg, "!document.querySelector('#voiceLearn').disabled", 5000)
            check("兎田ぺこら" in pg.inner_text("#voiceLearnHint"), "名前を付けると押せる(誰の声を覚えるか出る): " + pg.inner_text("#voiceLearnHint"))
            pg.click("#voiceLearn")
            wait_js(pg, "document.querySelector('#voiceCount').textContent.indexOf('1人') >= 0", 30000)
            check("兎田ぺこら" in (pg.text_content("#voiceList") or ""), "覚えている声の一覧に出る: " + (pg.text_content("#voiceList") or ""))
            saved = [os.path.join(r, n) for r, _, ns in os.walk(srv.tmp) for n in ns if n == "voxceleb.json"]
            check(len(saved) == 1 and os.path.basename(os.path.dirname(saved[0])) == "voices", "声の特徴は作業データの voices/ に保存する(判別モデルごと): %s" % saved)
            vs = srv.get("/api/voices")["voices"]
            check(vs.get("voxceleb", [{}])[0].get("name") == "兎田ぺこら" and "vec" not in vs["voxceleb"][0], "一覧の API は名前・行の数・秒だけ(特徴そのものは返さない)")
            # 判別し直す(名前は「話者n」に戻る)→ 覚えた声で名前が付く
            j = wait_job(srv, srv.call("POST", "/api/diarize", {"tid": tid, "numSpeakers": 2})["id"])
            check([x["name"] for x in j["named"]] == ["兎田ぺこら"], "判別し直すと、覚えた声の話者に名前が付く: %s" % j["named"])
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
