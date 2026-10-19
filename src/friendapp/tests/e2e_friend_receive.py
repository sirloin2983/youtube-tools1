#!/usr/bin/env python3
"""友人のアプリの「受け取る」画面の通し確認(Playwright の chromium・headless・音なし)。玄関を一時フォルダに起こし(friend_e2e_kit.py)、
画面(/friend/)を実際に操作する。リポジトリ直下で:

    set PYTHONIOENCODING=utf-8
    py -3.12 src/friendapp/tests/e2e_friend_receive.py

準備: 偽の ② で 1 配信 3 本のパックを作って「届いた」にする。#1 #2 には短い確認用の動画(ffmpeg で作る。作れなければ全部「確認用の動画なし」の形)・#3 は動画なし。
流れ: 段の見出し・通し番号 → 再生画面 → 速度と音量を変える(値で確かめる = 音は出さない)→ 読み直しても覚えている →
      [受け取る](保存先の形・フォルダを開く)→ 自動で次 → [見送る] → 動画なしの形 → 知らせの [戻す] → チェックでまとめて見送る → 判断の記録 v2
外に作用する口は全部偽物(フォルダを開く・ファイルを選ぶ・ネット・Dropbox・exe)。待ちは「表示されるまで待つ」。
"""
import json
import os

from playwright.sync_api import expect, sync_playwright

from friend_e2e_kit import WAIT, Rig, check, make_mp4, wait_until

TITLE = "受け取りのテスト配信"
URL = "https://www.youtube.com/watch?v=e2eReceive1"
PACKS = 3
RATE, VOL = 1.5, 0.7


def main():
    ok = True
    with Rig("ytt-friend-recv-e2e-", oembed=lambda vid: {"title": TITLE, "channel": "テストちゃんねる"}) as rig:
        app, q, places = rig.app, rig.queue, rig.places
        # 準備: 送る(API)→ ② の偽物が 3 本作って届ける → 確認用の動画を #1 #2 に付ける
        row = app.api.send({"source": "url", "kind": "url", "url": URL, "title": TITLE, "ranges": [[10, 50]], "streamer": "テストちゃんねる"})["rows"][0]
        rid = row["id"]
        q.start(q.latest())
        q.finish(q.latest(), packs=PACKS, seconds=40)
        pv_dir = os.path.join(places["friend"], "previews")
        os.makedirs(pv_dir, exist_ok=True)
        videos = 0
        for n in (1, 2):
            path = os.path.join(pv_dir, "%s-%d.mp4" % (rid, n))
            if make_mp4(path):
                app.inbox.set_preview(rid, n, path)
                videos += 1
        have_video = videos == 2
        print("INFO 確認用の動画: %s" % ("2 本(ffmpeg で作った短い動画)" if have_video else "作れなかった = 全部「確認用の動画なし」の形"), flush=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--mute-audio"])
            try:
                pg = browser.new_page(viewport={"width": 1100, "height": 850})
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(rig.base)
                expect(pg.locator("#tabN")).to_have_text(str(PACKS), timeout=WAIT)
                pg.click("#tabReceive")
                sec = pg.locator(".fr-rsec", has_text=TITLE).first
                expect(sec.locator(".fr-rcard")).to_have_count(PACKS, timeout=WAIT)
                ok &= check("テストちゃんねる" in sec.locator(".fr-rsec-meta").text_content() and "%d 本" % PACKS in sec.locator(".fr-rsec-meta").text_content(),
                            "段の見出しに配信者と本数: %s" % sec.locator(".fr-rsec-meta").text_content())
                nums = [t.strip().split(" ")[0] for t in sec.locator(".fr-num-badge").all_text_contents()]
                ok &= check(nums == ["#1", "#2", "#3"], "通し番号 #1 #2 #3 が並ぶ: %s" % nums)

                # 再生画面 → 速度と音量(値で確かめる)→ 読み直しても覚えている
                sec.locator(".fr-rcard-btn").first.click()
                expect(pg.locator("#playerTitle")).to_contain_text("#1", timeout=WAIT)
                if have_video:
                    expect(pg.locator("#playerVideo")).to_be_visible(timeout=WAIT)
                    pg.wait_for_function("() => document.getElementById('playerVideo').readyState >= 1", timeout=WAIT)
                    ok &= check(pg.locator("#playerNoVideo").is_hidden() and pg.locator("#pbar").is_visible(), "確認用の動画がある物は再生画面に動画と操作の帯が出る")
                    pg.select_option("#pRate", str(RATE))
                    pg.locator("#playerTitle").click()
                    pg.keyboard.press("ArrowDown")
                    pg.keyboard.press("ArrowDown")
                    pg.keyboard.press("ArrowDown")
                    wait_until(lambda: abs(app.player()["rate"] - RATE) < 1e-6 and abs(app.player()["volume"] - VOL) < 0.011, what="速度と音量が玄関に覚えられる")
                    ok &= check(True, "速度 %s・音量 %s を変えると玄関が覚える: %s" % (RATE, VOL, app.player()))
                    pg.reload()
                    expect(pg.locator("#tabN")).to_have_text(str(PACKS), timeout=WAIT)
                    pg.click("#tabReceive")
                    pg.locator(".fr-rsec", has_text=TITLE).first.locator(".fr-rcard-btn").first.click()
                    pg.wait_for_function("() => { const v = document.getElementById('playerVideo'); return v.readyState >= 1 && v.playbackRate === %s; }" % RATE, timeout=WAIT)
                    got = pg.evaluate("() => { const v = document.getElementById('playerVideo'); return [v.playbackRate, v.volume, document.getElementById('pRate').value]; }")
                    ok &= check(got[0] == RATE and abs(got[1] - VOL) < 0.011 and float(got[2]) == RATE, "読み直しても速度と音量を覚えている(値): %s" % got)
                    pg.keyboard.press("Escape")
                    expect(pg.locator("#rcvList")).to_be_visible(timeout=WAIT)
                    sec = pg.locator(".fr-rsec", has_text=TITLE).first
                    sec.locator(".fr-rcard-btn").first.click()
                    expect(pg.locator("#playerTitle")).to_contain_text("#1", timeout=WAIT)

                # [受け取る](保存先の形)→ 自動で次
                pg.click("#btnKeep")
                expect(pg.locator("#playerTitle")).to_contain_text("#2", timeout=WAIT)
                ok &= check(True, "[受け取る] で自動で #2 へ進む")
                pg.locator("#toast").get_by_role("button", name="フォルダを開く").click()
                wait_until(lambda: rig.opened, what="フォルダを開く口(偽物)が呼ばれる")
                ok &= check(len(rig.opened) == 1 and TITLE in rig.opened[0], "知らせの [フォルダを開く] は偽物の口に届く(本物のエクスプローラーは開かない)")

                # [見送る] → 動画なしの #3 → [戻す]
                pg.click("#btnSkip")
                expect(pg.locator("#playerTitle")).to_contain_text("#3", timeout=WAIT)
                ok &= check(pg.locator("#playerNoVideo").is_visible() and pg.locator("#playerVideo").is_hidden() and pg.locator("#pbar").is_hidden(),
                            "確認用の動画がない物は「確認用の動画はまだありません」の形(動画も帯も出ない)")
                pg.locator("#toast").get_by_role("button", name="戻す").click()
                expect(pg.locator("#playerList .fr-rcard")).to_have_count(2, timeout=WAIT)
                ok &= check(True, "[見送る] で #3 へ・知らせの [戻す] で #2 が戻る")
                pg.keyboard.press("Escape")
                expect(pg.locator("#rcvList")).to_be_visible(timeout=WAIT)

                # チェックでまとめて見送る
                sec = pg.locator(".fr-rsec", has_text=TITLE).first
                for cb in sec.locator(".fr-pick").all():
                    cb.check()
                expect(pg.locator("#bulkBar")).to_be_visible(timeout=WAIT)
                expect(pg.locator("#bulkCount")).to_contain_text("2 本", timeout=WAIT)
                pg.click("#bulkSkip")
                expect(pg.locator(".fr-rsec", has_text=TITLE)).to_have_count(0, timeout=WAIT)
                expect(pg.locator("#rcvSkipList li")).to_have_count(2, timeout=WAIT)
                ok &= check(pg.locator("#tabN").is_hidden(), "まとめて見送ると段が消え、見送った物に 2 本・●が消える")

                judges = []
                for n in sorted(os.listdir(places["outbox"])):
                    if n.endswith(".verdict.json"):
                        with open(os.path.join(places["outbox"], n), encoding="utf-8") as f:
                            d = json.load(f)
                        judges.append(d["judge"] if d.get("v") == 2 else "v1")
                ok &= check(sorted(judges) == ["good", "retract", "unknown", "unknown", "unknown"], "判断の記録 v2(受け取る 1・見送る 3・戻す 1): %s" % judges)

                ok &= check(not errors, "画面にエラー(pageerror)が出ていない%s" % ("" if not errors else ": " + errors[0][:120]))
            finally:
                browser.close()
    print("OK" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
