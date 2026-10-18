#!/usr/bin/env python3
"""友人のアプリの「送る」画面の通し確認(Playwright の chromium・headless・音なし)。玄関を一時フォルダに起こし(friend_e2e_kit.py)、
画面(/friend/)を実際に操作する。リポジトリ直下で:

    set PYTHONIOENCODING=utf-8
    py -3.12 src/friendapp/tests/e2e_friend_send.py

流れ: 偽の配信の一覧のカードを押す → 区間 2 つ(数字だけで打つ・Enter で次の欄・[+30秒])→ [送る] → 送った物の行(順番待ち → 進み具合)→
      [取り消す](確認の窓)/ URL を貼って送る / 失敗(上の段 = 友人の言葉・下の段 = 詳しく)→ [もう一度送る] →
      録画中の配信のカード = 「録画しています」と [録画を取り消す](録画の部品は偽物)/ Esc で送る欄を閉じる
外に作用する口は全部偽物(配信の一覧・oEmbed・配信中か・窓・フォルダ・Dropbox・exe)。待ちは「表示されるまで待つ」。
"""
import time

from playwright.sync_api import expect, sync_playwright

from friend_e2e_kit import CHANNEL, WAIT, Rig, check, wait_until

V_ARCH, V_LIVE, V_URL = "e2eArchive1", "e2eLiveNow1", "e2eUrlPaste"
T_ARCH, T_LIVE, T_URL = "テストの配信(アーカイブ)", "テストの配信(ライブ中)", "貼った URL の配信"


def card(vid, title, state, **kw):
    now = int(time.time() * 1000)
    it = {"videoId": vid, "url": "https://www.youtube.com/watch?v=" + vid, "title": title, "channelId": "UC" + "a" * 22, "streamer": CHANNEL, "hex": "#3366cc",
          "thumb": "", "state": state, "startAt": now - 3600 * 1000, "endAt": None, "duration": 3600 if state != "live" else None}
    it.update(kw)
    return it


def fake_oembed(vid):
    return {"title": T_URL, "channel": CHANNEL}


def main():
    ok = True
    with Rig("ytt-friend-send-e2e-", oembed=fake_oembed) as rig:
        rig.sections = [{"key": "live", "label": "ライブ中・これから", "count": 1, "items": [card(V_LIVE, T_LIVE, "live")]},
                        {"key": "today", "label": "今日", "count": 1, "items": [card(V_ARCH, T_ARCH, "ended")]}]
        q = rig.queue
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--mute-audio"])
            try:
                pg = browser.new_page(viewport={"width": 1100, "height": 850})
                errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(rig.base)
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                expect(pg.locator(".fr-card")).to_have_count(2, timeout=WAIT)
                ok &= check(True, "偽の配信の一覧に 2 枚のカードが出る(ライブ中・今日)")

                # 1. アーカイブのカードを押す → 区間 2 つ → 送る
                pg.locator('.fr-card[data-vid="%s"]' % V_ARCH).click()
                expect(pg.locator("#headTitle")).to_have_text(T_ARCH, timeout=WAIT)
                expect(pg.locator("#btnSend")).to_be_enabled(timeout=WAIT)
                ok &= check(pg.locator('.fr-card[data-vid="%s"]' % V_ARCH).get_attribute("aria-pressed") == "true", "カードを押すと送る欄にその配信が開き、カードが選んだ印になる")
                pg.locator(".fr-range .ui-time").nth(0).click()
                pg.keyboard.type("01230")
                pg.keyboard.press("Enter")   # 次の欄へ
                pg.keyboard.type("01500")
                expect(pg.locator(".fr-range-said").first).to_contain_text("12分30秒 〜 15分00秒(2分30秒)", timeout=WAIT)
                ok &= check(pg.locator("#topLine").is_hidden(), "区間を数字だけで打つ(Enter で次の欄)と読み取った結果が出て、本数の欄が消える")
                pg.locator(".fr-range").first.get_by_role("button", name="+30秒").click()
                expect(pg.locator(".fr-range-said").first).to_contain_text("12分30秒 〜 13分00秒(30秒)", timeout=WAIT)
                ok &= check(True, "[+30秒] で終わりが始まりの 30 秒後になる")
                pg.click("#btnRange")   # 2 つめの区間
                expect(pg.locator(".fr-range")).to_have_count(2, timeout=WAIT)
                pg.locator(".fr-range").nth(1).locator(".ui-time").nth(0).click()
                pg.keyboard.type("02000")
                pg.keyboard.press("Enter")
                pg.keyboard.type("02130")
                expect(pg.locator(".fr-range-said").nth(1)).to_contain_text("20分00秒 〜 21分30秒", timeout=WAIT)
                pg.click("#btnSend")
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                row = pg.locator(".fr-sent-row", has_text=T_ARCH).first
                expect(row).to_be_visible(timeout=WAIT)
                sent = rig.app.inbox.rows[0]["form"]
                ok &= check([list(x) for x in sent["ranges"]] == [[750.0, 780.0], [1200.0, 1290.0]] and sent["top"] is None, "区間 2 つが依頼に入る: %s" % sent["ranges"])
                expect(row.locator(".fr-sent-line")).to_contain_text("順番", timeout=WAIT)
                ok &= check(True, "[送る] の後、送る欄が閉じて「送った物」に行が出て、順番待ちと出る")
                expect(pg.locator('.fr-card[data-vid="%s"] .fr-badge-sent' % V_ARCH)).to_have_text("順番待ち", timeout=WAIT)
                ok &= check(True, "一覧のカードにも「順番待ち」の印が付く")

                # 2. 作り始める → 進み具合 → 取り消す(確認の窓)
                rid1 = q.latest()
                q.start(rid1)
                row = pg.locator(".fr-sent-row", has_text=T_ARCH).first
                expect(row.locator(".fr-sent-line")).to_contain_text("切り抜き", timeout=WAIT)
                expect(row.locator(".bar")).to_be_visible(timeout=WAIT)
                ok &= check("/" in row.locator(".fr-sent-line").text_content(), "作り始めると進み具合の行(○/○ 切り抜き)と棒が出る: %s" % row.locator(".fr-sent-line").text_content())
                row.get_by_role("button", name="取り消す").click()
                dlg = pg.locator("dialog[open]")
                expect(dlg).to_be_visible(timeout=WAIT)
                dlg.get_by_role("button", name="続ける").click()
                expect(dlg).to_have_count(0, timeout=WAIT)
                ok &= check(pg.locator(".fr-sent-row", has_text=T_ARCH).count() == 1, "確認の窓の [続ける] では取り消さない")
                pg.locator(".fr-sent-row", has_text=T_ARCH).first.get_by_role("button", name="取り消す").click()
                pg.locator("dialog[open]").get_by_role("button", name="取り消す").click()
                expect(pg.locator(".fr-sent-row", has_text=T_ARCH)).to_have_count(0, timeout=WAIT)
                ok &= check(rig.app.inbox.row(rid1) is None, "作っている途中の [取り消す] は確認の窓 → 行が消える")

                # 3. URL を貼って送る → 失敗(2 段)→ [もう一度送る] → 届く
                pg.fill("#url", "https://www.youtube.com/watch?v=" + V_URL)
                pg.press("#url", "Enter")
                expect(pg.locator("#headTitle")).to_have_text(T_URL, timeout=WAIT)
                expect(pg.locator("#btnSend")).to_be_enabled(timeout=WAIT)
                ok &= check(pg.locator("#topLine").is_visible(), "URL を貼ると一覧に無い配信でも題が出て、区間なしなら本数の欄が出る")
                pg.click("#btnSend")
                row = pg.locator(".fr-sent-row", has_text=T_URL).first
                expect(row).to_be_visible(timeout=WAIT)
                rid2 = q.latest()
                q.start(rid2)
                q.fail(rid2, "この動画は非公開です(テストの偽物)")
                expect(row.locator(".fr-fail-top")).to_be_visible(timeout=WAIT)
                ok &= check("見られません" in row.locator(".fr-fail-top").text_content(), "失敗は友人の言葉で次にすることを 1 つ(上の段)")
                row.locator("summary").click()
                expect(row.locator(".fr-fail-detail")).to_contain_text("非公開です", timeout=WAIT)
                ok &= check(True, "下の段 [詳しく] に元の文が出る")
                row.get_by_role("button", name="もう一度送る").click()
                rid3 = wait_until(lambda: q.latest() if q.latest() != rid2 else None, what="もう一度送った依頼")
                q.start(rid3)
                q.finish(rid3, packs=2)
                expect(pg.locator("#tabN")).to_have_text("2", timeout=WAIT)
                expect(pg.locator(".fr-sent-row", has_text=T_URL)).to_have_count(0, timeout=WAIT)
                ok &= check(True, "[もう一度送る] で作り直され、届くと送った物から消えて [受け取る] に ●2")

                # 4. 録画中の配信: カードを押して「録画を頼む」→ もう一度押すと「録画しています」と [録画を取り消す]
                pg.locator('.fr-card[data-vid="%s"]' % V_LIVE).click()
                expect(pg.locator("#liveBox")).to_be_visible(timeout=WAIT)
                expect(pg.locator("#btnSend")).to_have_text("録画を頼む", timeout=WAIT)
                pg.click("#btnSend")
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                row = pg.locator(".fr-sent-row", has_text=T_LIVE).first
                expect(row.locator(".fr-sent-line")).to_contain_text("録画中", timeout=WAIT)
                ok &= check(True, "ライブ中の配信は [録画を頼む] で送った物に「録画中」の行が出る")
                pg.locator('.fr-card[data-vid="%s"]' % V_LIVE).click()
                expect(pg.locator("#liveLead")).to_contain_text("録画しています", timeout=WAIT)
                expect(pg.locator("#btnSend")).to_have_text("録画を取り消す", timeout=WAIT)
                ok &= check(True, "録画中の配信を押すと「録画しています」と [録画を取り消す] が出る")
                pg.click("#btnSend")
                dlg = pg.locator("dialog[open]")
                expect(dlg).to_contain_text("録画を取り消します", timeout=WAIT)
                dlg.get_by_role("button", name="取り消す").click()
                expect(pg.locator(".fr-sent-row", has_text=T_LIVE)).to_have_count(0, timeout=WAIT)
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                ok &= check(len(rig.live.stopped) == 1, "[録画を取り消す] → 確認の窓 → 録画の部品に止める依頼が行き、行が消える(偽物): %s" % rig.live.stopped)

                # 5. Esc で送る欄を閉じる
                pg.locator('.fr-card[data-vid="%s"]' % V_ARCH).click()
                expect(pg.locator("#formStream")).to_be_visible(timeout=WAIT)
                pg.locator("#headTitle").click()
                pg.keyboard.press("Escape")
                expect(pg.locator("#formEmpty")).to_be_visible(timeout=WAIT)
                ok &= check(True, "Esc で送る欄を閉じる")

                # 6. 動画ファイルを落とす: 1 回で 1 つ・同じ物をもう一度でも 1 つのまま(落とす所が入れ子でも二重にならない)
                drop_js = """(n) => {
                    const dt = new DataTransfer();
                    dt.items.add(new File([new Uint8Array(5)], 'ドロップ試験.mp4', { type: 'video/mp4' }));
                    document.getElementById(n).dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
                }"""
                pg.evaluate(drop_js, "dropZone")
                expect(pg.locator("#fileList li")).to_have_count(1, timeout=WAIT)
                time.sleep(0.8)
                ok &= check(pg.locator("#fileList li").count() == 1, "動画を 1 回落とすと欄に 1 つだけ入る")
                pg.evaluate(drop_js, "dropMore")
                time.sleep(0.8)
                ok &= check(pg.locator("#fileList li").count() == 1, "同じ物(同じ名前・大きさ)をもう一度落としても 1 つのまま")

                ok &= check(not rig.opened, "フォルダ・窓は開いていない(偽物の口に呼びが無い)")
                ok &= check(not errors, "画面にエラー(pageerror)が出ていない%s" % ("" if not errors else ": " + errors[0][:120]))
            finally:
                browser.close()
    print("OK" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
