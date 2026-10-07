#!/usr/bin/env python3
"""キーの一覧 = キー配置(UIKit.keymap。気が利く画面へ 段6)の通し確認。3ツールを疑似モードで一時フォルダに写し、入口に取り込んだ形で動かす。

    python src/home/tests/e2e_keymap.py

① 編集: 以前の編集の設定に入れた共通の再生キーを、ホームの設定へ移す(1回だけ)
② 編集の ? の一覧: キーのボタンで変える・Esc は取り消しだけ(一覧は閉じない)・変換中は受け取らない・派生キー(← + Shift)は断る(GPT-03)・
   重なりは「外しました [戻す]」・? をもう一度押すと閉じる
③ スタジオの ? の一覧: 共通の再生キーが編集と同じ・スタジオで変えると編集にも効く(S-27)
④ 編集で左のメニューを重ねて開いている間、メニューの中のキーは後ろの文書を動かさない(GPT-04)
⑤ 画面のエラー(CSP 違反を含む)が無い
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import launch as L  # noqa: E402
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports  # noqa: E402
from e2e_autorun import make_media, wait_js  # noqa: E402


def main():
    ok = True
    events = []

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-keymap-e2e-")
    env = {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0.01",
           "STUDIO_HOME": os.path.join(tmp, "studio-home"), "YTT_HOLO_MEMBERS": os.path.join(os.path.dirname(REPO), "friend-apps", "holo-colors", "members.json")}   # REPO = src(ツールの親)。ホロカラーはその1つ上の friend-apps
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    try:
        for s in L.TOOLS:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        media = os.path.join(tmp, "media", "キーの確認.mp4")
        os.makedirs(os.path.dirname(media))
        make_media(media, sec=20)

        sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=dict(zip(L.TOOL_IDS, free_ports(3))),
                           mounts=tuple(M.MOUNTS))
        srv, port = L.make_server(0, sup)
        sup.attach(srv)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        base = "http://localhost:%d" % port

        def call(method, path, body=None):
            h = {"Content-Type": "application/json", "X-YTT-Token": srv.token, "Origin": base}
            req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(), headers=h)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read() or b"null")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"null")

        def prefs_pb():
            return ((call("POST", "/api/ytt/prefs", {"op": "get", "sections": ["keymap"]})[1].get("prefs") or {}).get("keymap") or {}).get("playback") or {}

        def wait_prefs(fn, timeout=10):
            end = time.time() + timeout
            while time.time() < end:
                pb = prefs_pb()
                if fn(pb):
                    return pb
                time.sleep(0.2)
            return prefs_pb()

        try:
            sup.start_all()
            check(all(sup.by_id[t].snapshot()["state"] == "running" for t in L.TOOL_IDS), "3つとも入口に取り込んで動いた")
            # 文書を1つ(④ のため)
            st, j = call("POST", "/transcribe/api/transcribe", {"sourcePath": media, "model": "small", "language": "ja", "title": "キーの確認", "autoGloss": False})
            check(st == 200 and "id" in j, "文字起こしを始めた: %s" % st)
            tid = None
            end = time.time() + 120
            while time.time() < end and not tid:
                x = next((v for v in call("GET", "/transcribe/api/jobs")[1]["jobs"] if v["id"] == j["id"]), {})
                if x.get("state") == "done":
                    tid = x.get("tid")
                time.sleep(0.2)
            check(bool(tid), "文字起こしが終わった")
            # ① 以前の編集の設定(settings.keymap)に入れた共通の再生キー
            st, _ = call("POST", "/transcribe/api/settings/patch", {"values": {"keymap": {"playPause": "p", "rowNext": "s"}}})
            check(st == 200, "編集の設定の keymap は「送ったキーだけ直す」で保存できる")
            check(prefs_pb() == {}, "ホームの設定の共通の再生キーは、はじめは空")

            with sync_playwright() as p:
                browser = p.chromium.launch()
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                errors = []
                pg = ctx.new_page()
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base + "/transcribe/?doc=%s#tx" % tid)
                check(wait_js(pg, "document.querySelectorAll('#segs .seg').length > 0", 20000), "編集で文書を開いた")
                pb = wait_prefs(lambda x: x.get("playPause") == "p")
                check(pb.get("playPause") == "p" and pb.get("back1") == "j", "① 編集に保存していた再生キー(P)を、ホームの設定へ移した: %s" % pb)

                # ② ? の一覧
                diag = pg.evaluate("({a: document.activeElement && (document.activeElement.id || document.activeElement.tagName), d: [...document.querySelectorAll('dialog[open]')].map(x => x.id), dr: !!document.querySelector('.ui-drawer:not([hidden])')})")
                pg.keyboard.press("?")
                check(wait_js(pg, "document.querySelector('#keys').open", 5000), "? でキー操作の一覧が開く: %s" % diag)
                K = "#keysList .ui-km-key[data-km=%s]"
                ktext = lambda i: pg.inner_text(K % i).replace("\n", "").replace(" ", "")   # noqa: E731
                check(ktext("playPause") == "P" and ktext("rowNext") == "S", "一覧のキーはボタン(今の割り当て): 再生・停止 %s / 次の行 %s" % (ktext("playPause"), ktext("rowNext")))
                check(pg.locator("#keysList .ui-km-fixed .ui-km-lock").count() >= 5, "変えられないキーには錠(理由つき)")
                check("2 カット のタブ" in pg.inner_text("#keysList") and "前/次の区間を選ぶ" in pg.inner_text("#keysList"), "2 カット のタブのキーも一覧に(表から作る)")
                pg.click(K % "seekBack")
                check(pg.evaluate("UIKit.keymap.capturing()") and pg.inner_text(K % "seekBack") == "キーを押す…", "キーのボタンを押すと、次のキーを待つ")
                check("割り当てるキーを押してください" in pg.inner_text("#keysList .ui-km-note"), "待っている間の案内が一覧の中に出る(読み上げの場所)")
                pg.keyboard.press("Escape")
                time.sleep(0.3)
                check(pg.evaluate("document.querySelector('#keys').open") and not pg.evaluate("UIKit.keymap.capturing()"), "Esc は取り消しだけ(一覧は閉じない)")
                check(ktext("seekBack") == "←", "取り消したら元のまま")
                # 日本語の変換中のキーは受け取らない
                pg.click(K % "rowNext")
                pg.evaluate("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'm', isComposing: true, bubbles: true}))")
                check(pg.evaluate("UIKit.keymap.capturing()") and ktext("rowNext") == "キーを押す…", "変換中のキー(isComposing)は割り当てない")
                # GPT-03: ← + Shift(5秒戻る)は、ほかの操作に割り当てられない
                pg.keyboard.press("Shift+ArrowLeft")
                note = pg.inner_text("#keysList .ui-km-note")
                check(pg.evaluate("UIKit.keymap.capturing()") and "5 秒" in note, "Shift+← は「1秒戻る」+ Shift(5秒)なので断り、待つのを続ける: " + note)
                pg.keyboard.press("m")   # H は 2 カット の「I〜O を削る」に使う(ui-kit v23 で X → H)ので、どの画面でも空いている M で試す
                check(ktext("rowNext") == "M" and not pg.evaluate("UIKit.keymap.capturing()"), "別のキー(M)を押すと割り当てる")
                # 重なり → 「外しました」[戻す]
                pg.click(K % "replay")
                pg.keyboard.press("w")
                note = pg.inner_text("#keysList .ui-km-note")
                check(ktext("replay") == "W" and ktext("rowPrev") == "未設定" and "外しました" in note, "使っているキー(W)を選ぶと、そちらから外す: " + note)
                pg.click("#keysList [data-km-undo]")
                check(ktext("replay") == "R" and ktext("rowPrev") == "W", "[戻す] で両方とも元に戻る")
                check(pg.locator("#keysList [data-km-def=rowNext]").count() == 1 and pg.locator("#keysList [data-km-def=replay]").count() == 0,
                      "標準と違う行だけ「標準」ボタン")
                pg.click("#keysList [data-km-def=rowNext]")
                check(ktext("rowNext") == "S", "行の「標準」で標準のキーに戻す")
                # 共通の再生キーを変える → ホームの設定に保存
                pg.click(K % "frameBack")
                pg.keyboard.press("m")
                pb = wait_prefs(lambda x: x.get("frameBack") == "m")
                check(pb.get("frameBack") == "m", "共通の再生キー(1コマ戻る = M)はホームの設定に保存: %s" % pb.get("frameBack"))
                kb = pg.evaluate("[...document.querySelectorAll('.ui-keybar-item')].map(e => e.dataset.k)")
                check("R" in kb, "キーの帯は今の割り当てから: %s" % kb)
                pg.keyboard.press("?")
                check(wait_js(pg, "!document.querySelector('#keys').open", 3000), "? をもう一度押すと一覧を閉じる(スタジオと同じ)")
                check(pg.evaluate("document.querySelector('#segs button[data-act=play]').title").startswith("この行だけ再生(R)"), "行のボタンのツールチップも今の割り当てから")

                # ③ スタジオの ? の一覧
                ps = ctx.new_page()
                ps.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                ps.on("pageerror", lambda e: errors.append(str(e)))
                ps.goto(base + "/studio/")
                wait_js(ps, "!!(window.Studio && Studio.review && Studio.review.keymap)", 15000)
                wait_js(ps, "Studio.review.keymap.key('frameBack') === 'm'", 10000)
                ps.click("#btnKeys")
                check(wait_js(ps, "document.querySelector('#keyHelp').open", 5000), "スタジオの「キー操作」で一覧が開く")
                SK = "#keyHelpBody .ui-km-key[data-km=%s]"
                st_text = lambda i: ps.inner_text(SK % i).replace("\n", "").replace(" ", "")   # noqa: E731
                check(st_text("playPause") == "P" and st_text("frameBack") == "M", "スタジオでも共通の再生キーは編集と同じ(P・M)")
                check(st_text("adopt") == "Y" and "今をマーク①" in ps.inner_text("#keyHelpBody"), "スタジオのキー(採用 = Y)も同じ形の一覧に")
                ps.click("#keyHelpBody [data-km-def=playPause]")
                check(st_text("playPause") == "Space", "スタジオで共通の再生キーを標準に戻せる(S-27)")
                pb = wait_prefs(lambda x: x.get("playPause") == "Space")
                check(pb.get("playPause") == "Space", "スタジオで変えた再生キーもホームの設定に")
                ps.keyboard.press("?")
                check(wait_js(ps, "!document.querySelector('#keyHelp').open", 3000), "スタジオも ? で閉じる")
                ps.close()
                pg.goto(base + "/transcribe/?doc=%s#tx" % tid)
                pg.reload()   # 開いていた文書は URL の ?doc= に残るので(段2 監査 06)、上の goto は # だけの移動になり読み直さない。再読み込みで同じ文書が開く
                check(wait_js(pg, "document.querySelectorAll('#segs .seg').length > 0", 20000) and wait_js(pg, "UIKit && document.querySelector('#keysList .ui-km-key[data-km=playPause]') && document.querySelector('#keysList .ui-km-key[data-km=playPause]').textContent.indexOf('Space') >= 0", 10000),
                      "編集を開き直すと、スタジオで変えた再生キー(Space)が効いている")

                # ④ GPT-04: 重ねて開いた左のメニューの中のキーは、後ろの文書を動かさない
                pg.click("#segs .seg >> nth=0")
                pg.keyboard.press("Escape")
                navi = "[...document.querySelectorAll('#segs .seg')].findIndex(e => e.classList.contains('nav'))"
                n0 = pg.evaluate(navi)
                pg.click("#btnMenu")
                check(wait_js(pg, "document.querySelector('#menuPanel').contains(document.activeElement)", 3000), "1440px で文書を開いているとき、メニューは重ねて開き、中へフォーカスが移る")
                pg.keyboard.press("ArrowDown")
                pg.keyboard.press("s")
                check(pg.evaluate(navi) == n0, "メニューの中の ↓・S は後ろの文書の行を動かさない(GPT-04): %s → %s" % (n0, pg.evaluate(navi)))
                real = [e for e in errors if "Failed to load resource" not in e]
                check(not real, "画面のエラーなし(CSP 違反を含む): %s" % real[:3])
                browser.close()
        finally:
            srv.request_shutdown() if not srv.closing.is_set() else None
            th.join(30)
            sup.close()
            sup.stop_all()
            sup.unmount_all()
            srv.server_close()
    finally:
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("すべて OK" if ok else "失敗あり"))
    if not ok:
        print("\n".join(events[-30:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
