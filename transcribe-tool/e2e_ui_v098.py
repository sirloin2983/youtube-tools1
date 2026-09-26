#!/usr/bin/env python3
"""v0.9.8 の通し確認(Playwright + 疑似モード): 左メニューの開閉・行の追加(前後・すき間・N・＋行を追加)・
   元に戻す・行の▶単独再生・設定のポップオーバー・左手キー操作・空の文書。

    python3 e2e_ui_v098.py
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように


def call(port, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def t2s(s):
    """'1:02.5' のような表示を秒に直す"""
    v = 0.0
    for x in s.split(":"):
        v = v * 60 + float(x)
    return v


def main():
    tmp = tempfile.mkdtemp()
    for n in ("serve.py", "index.html", "app.js", "cut.js", "pack-tab.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):   # 受け渡しの API(pipeline_io)・Resolve 書き出しも使うので一緒に写す
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            shutil.copy(p, tmp)
    wav = os.path.join(tmp, "sample.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=24", wav], check=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, YTT_RUNTIME_DIR=os.path.join(tmp, ".runtime"), TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.01")
    proc = subprocess.Popen([sys.executable, os.path.join(tmp, "serve.py"), str(port), "--no-open"], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors, ok = [], True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    def make():
        j = call(port, "POST", "/api/transcribe", {"sourcePath": wav, "model": "small", "language": "ja"})
        for _ in range(200):
            jobs = call(port, "GET", "/api/jobs")["jobs"]
            job = next(x for x in jobs if x["id"] == j["id"])
            if job["state"] in ("done", "error"):
                return job["tid"]
            time.sleep(0.1)

    def set_segs(tid, title, segs, speakers=None):
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": title, "speakers": speakers or [], "segments": segs})

    def gap_segs():
        return [{"id": "a", "start": 0, "end": 2, "text": "一"}, {"id": "b", "start": 5, "end": 7, "text": "二"}, {"id": "c", "start": 7, "end": 9, "text": "三"}]

    try:
        for _ in range(100):
            try:
                call(port, "GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)

        # ---- 文書を用意(機能ごとに別の文書にして、状態が混ざらないようにする) ----
        tid3 = make(); set_segs(tid3, "すきま3-後ろに追加", gap_segs())
        tid4 = make(); set_segs(tid4, "すきま4-Nキー", gap_segs())
        tid5 = make(); set_segs(tid5, "すきま5-前に追加", gap_segs())
        tid6 = make(); set_segs(tid6, "すきま6-再生位置", gap_segs())
        tid_play = make()   # 4秒ずつ隙間なし(疑似認識のそのまま)
        play_doc = call(port, "GET", "/api/transcript?id=" + tid_play)
        set_segs(tid_play, "再生文書", play_doc["segments"])   # 行の中身は疑似認識のまま、タイトルだけ選びやすい名前に変える
        tid_menu = make(); set_segs(tid_menu, "メニュー文書", [{"id": "m%d" % i, "start": i * 3.0, "end": i * 3.0 + 2.5, "text": "行%d" % i} for i in range(6)])
        tid_empty = make(); set_segs(tid_empty, "空の文書", [])
        # ---- v0.9.8 レビュー修正分の追加確認用 ----
        tid_rel = make(); set_segs(tid_rel, "確実クリック文書", [{"id": "r%d" % i, "start": i * 3.0, "end": i * 3.0 + 2.5, "text": "行%d" % i} for i in range(8)])
        tid_sel = make(); set_segs(tid_sel, "選択文書", [{"id": "s%d" % i, "start": i * 3.0, "end": i * 3.0 + 2.5, "text": "行%d" % i} for i in range(4)])
        tid_z = make(); set_segs(tid_z, "Z文書", [{"id": "z%d" % i, "start": i * 3.0, "end": i * 3.0 + 2.5, "text": "行%d" % i} for i in range(3)])
        tid_ties = make(); set_segs(tid_ties, "重なり挿入文書", [
            {"id": "ta", "start": 0, "end": 2, "text": "一"}, {"id": "tb", "start": 2, "end": 4, "text": "二"},
            {"id": "tc", "start": 4, "end": 4.8, "text": "三"}, {"id": "td", "start": 4, "end": 6, "text": "四"}])
        tid_ovl1 = make(); set_segs(tid_ovl1, "重なり文書1", [{"id": "o0", "start": 0, "end": 3, "text": "A"}, {"id": "o1", "start": 2.5, "end": 5, "text": "B"}])
        tid_ovl2 = make(); set_segs(tid_ovl2, "重なり文書2", [{"id": "p0", "start": 0, "end": 3, "text": "C"}, {"id": "p1", "start": 2, "end": 5, "text": "D"}])
        tid_setnow = make(); set_segs(tid_setnow, "再生位置反映文書", [{"id": "n0", "start": 0, "end": 2, "text": "一"}, {"id": "n1", "start": 5, "end": 7, "text": "二"}])
        tid_stage1 = make(); set_segs(tid_stage1, "画面幅テスト1", [{"id": "w0", "start": 0, "end": 2, "text": "一"}, {"id": "w1", "start": 2, "end": 4, "text": "二"}])
        tid_stage2 = make(); set_segs(tid_stage2, "画面幅テスト2", [{"id": "v0", "start": 0, "end": 2, "text": "一"}, {"id": "v1", "start": 2, "end": 4, "text": "二"}])

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1500, "height": 1000})
            pg = ctx.new_page()
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は e2e_ui_v098.py で確認)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            def app_class():
                return pg.get_attribute(".app", "class") or ""

            def open_doc(title):
                if "menu-closed" in app_class():
                    pg.click("#btnMenu")
                pg.wait_for_selector("#txList .txi")
                pg.fill("#txSearch", title)   # v0.9.9: 一覧は最近の8件だけ表示なので、検索で絞ってから開く
                pg.locator("#txList .txi").filter(has_text=title).locator(".t").first.click()
                # 検索欄は値を消すだけ(開いた直後に画面が狭いとメニューが自動で閉じ、見えない欄への fill は待ち続けてしまうため)
                pg.evaluate("(() => { const q = document.querySelector('#txSearch'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); })()")
                # クリック直後は、前の文書の行がまだ #segs に残ったまま(非同期で読み込み中)のことがあるので、
                # タイトルがこの文書に変わるのを確認してから読む(でないと前の文書の内容を読んでしまう)
                pg.wait_for_function("document.querySelector('#docTitle') && document.querySelector('#docTitle').value === %s" % json.dumps(title), timeout=15000)
                pg.wait_for_selector("#segs .seg, #segs .empty")

            def rows_times():
                # 1回の evaluate でまとめて読む(1行ずつ locator を作ると、その間の再描画でずれることがあるため)
                return [tuple(x) for x in pg.evaluate(
                    "[...document.querySelectorAll('#segs .seg')].map(r => "
                    "[r.querySelector('input.t[data-f=start]').value, r.querySelector('input.t[data-f=end]').value])")]

            def select_row(i):
                pg.locator("#segs textarea").nth(i).click()
                pg.keyboard.press("Escape")

            def wait_saved():
                pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)

            pg.goto("http://localhost:%d/" % port)
            pg.wait_for_selector("#txList .txi")

            # ==================== 1) 左メニューの開閉 ====================
            check(pg.get_attribute("#btnMenu", "aria-expanded") == "true", "初期状態はメニューが開いている(aria-expanded=true)")
            check("menu-closed" not in app_class(), "初期状態は .app に menu-closed が付いていない")
            pg.click("#btnMenu")
            check("menu-closed" in app_class(), "btnMenu クリックでメニューが閉じる(menu-closed)")
            check(pg.get_attribute("#btnMenu", "aria-expanded") == "false", "閉じたら aria-expanded=false")
            pg.click("#btnMenu")
            check("menu-closed" not in app_class() and pg.get_attribute("#btnMenu", "aria-expanded") == "true", "もう一度押すと開く")
            # メニュー内の btnMenuClose(開いている状態からのみ押せる)
            pg.click("#btnMenuClose")
            check("menu-closed" in app_class(), "メニュー内の btnMenuClose でも閉じられる")
            # キー g(フォーカスは直前に押したボタン上。入力欄ではないので働く)
            pg.keyboard.press("g")
            check("menu-closed" not in app_class(), "キー g でメニューが開く")
            pg.keyboard.press("g")
            check("menu-closed" in app_class(), "もう一度 g で閉じる")
            # 再読み込みで状態が残る(localStorage)
            pg.reload()
            # メニューが閉じた状態で再読み込みされるので、"#txList .txi, #noDoc" のような複数候補セレクタは使わない
            # (menu-closed で #txList 側が非表示のままだと、そちらを待ち続けて止まることがある)
            pg.wait_for_selector("#noDoc")
            check("menu-closed" in app_class(), "再読み込みしても、閉じた状態が残る(localStorage)")
            check(pg.get_attribute("#btnMenu", "aria-expanded") == "false", "再読み込み後も aria-expanded=false")
            check(pg.is_visible("#noDoc"), "文書を開いていないので #noDoc が表示されている")
            check(pg.is_visible("#noDocMenu"), "メニューが閉じているとき、#noDoc の中に「メニューを開く」ボタンが見える")
            pg.click("#noDocMenu")
            check("menu-closed" not in app_class(), "#noDocMenu クリックでメニューが開く")
            check(not pg.is_visible("#noDocMenu"), "メニューが開いたら #noDocMenu は隠れる")

            # ---- 1続き: 文書を開いている状態でメニューを閉じても、#player(video)は表示されたまま ----
            # (回帰: 古い CSS `.app.focus aside{display:none}` は .app の子孫すべての aside を隠しており、
            #  動画を囲む <aside class="tx-stage"> まで消えていた。今は `.app.menu-closed>aside` と直下の子だけを対象にしている)
            open_doc("メニュー文書")
            check(pg.is_visible("#player"), "文書を開いている状態: 最初から #player は見える")
            pg.click("#btnMenu")
            check("menu-closed" in app_class(), "文書を開いた状態でもメニューを閉じられる")
            check(pg.is_visible("#player"), "メニューを閉じても #player(video)は表示されたまま(回帰: 古い .app.focus aside で全 aside が消えた不具合)")
            pg.keyboard.press("g")
            check("menu-closed" not in app_class(), "g でメニューを開き直す")
            check(pg.is_visible("#player"), "開いた状態でも #player は表示されている")

            # ==================== 2) 行ツール(.adj)の表示 ====================
            check(pg.locator("#segs .seg").count() == 6, "前提: 6行")
            adj0 = pg.locator("#segs .seg").nth(0).locator(".adj")
            adj1 = pg.locator("#segs .seg").nth(1).locator(".adj")
            check(not adj0.is_visible() and not adj1.is_visible(), "開いた直後はどの行も選んでいないので、.adj はどこにも出ていない")
            select_row(0)
            check(adj0.is_visible(), "0行目の textarea をクリックして選ぶと、その行の .adj が見える")
            check(not adj1.is_visible(), "選んでいない行の .adj は見えない")
            for act in ("addb", "adda", "split", "merge", "del"):
                check(adj0.locator("[data-act=%s]" % act).count() == 1, ".adj に %s ボタンがある" % act)
            pg.locator("#segs textarea").nth(1).focus()
            check(adj1.is_visible(), "1行目の textarea にフォーカスすると、その行の .adj も見える(focus-within)")
            check(not adj0.is_visible(), "フォーカスが移ると選択(nav)も移るので、0行目の .adj は隠れる")
            pg.keyboard.press("Escape")

            # ==================== 3) すき間に「＋後に行」(adda) ====================
            open_doc("すきま3-後ろに追加")
            select_row(0)
            pg.locator("#segs .seg").nth(0).locator("[data-act=adda]").click()
            check(pg.locator("#segs .seg").count() == 4, "adda で行が1つ増える")
            times = rows_times()
            check(times[1] == ("0:02.0", "0:05.0"), "新しい行は前後のすき間(2〜5秒)にぴったり収まる: %s" % (times[1],))
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[1]"), "新しい行の textarea に自動でフォーカスが移る")
            pg.keyboard.type("追加した行")
            pg.keyboard.press("Escape")
            wait_saved()
            d = call(port, "GET", "/api/transcript?id=" + tid3)
            newseg = next((x for x in d["segments"] if x["text"] == "追加した行"), None)
            check(newseg is not None and abs(newseg["start"] - 2.0) < 0.01 and abs(newseg["end"] - 5.0) < 0.01, "サーバー側にも start=2.0 end=5.0 の新しい行として保存される: %s" % newseg)
            starts_srv = [x["start"] for x in d["segments"]]
            check(starts_srv == sorted(starts_srv), "サーバー側も開始時刻順に並んでいる")
            dom_starts = [t2s(x[0]) for x in rows_times()]
            check(dom_starts == sorted(dom_starts), "画面側も開始時刻順に並んでいる: %s" % dom_starts)

            # ==================== 4) すき間なしで N キー(前後の行と重なる) ====================
            open_doc("すきま4-Nキー")
            select_row(1)   # 「二」(5〜7秒)
            check(pg.locator("#segs .seg").nth(1).locator("textarea").input_value() == "二", "前提: 1行目は「二」")
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("n")
            check(pg.locator("#segs .seg").count() == 4, "N で行が増える")
            times = rows_times()
            check(times[2] == ("0:07.0", "0:08.5"), "すき間が無いときは1.5秒の仮の長さ(7.0〜8.5秒)で足される: %s" % (times[2],))
            check("重なって" in pg.inner_text("#toast"), "前後の行と重なる旨のトーストが出る: " + pg.inner_text("#toast"))
            starts = [t2s(x[0]) for x in rows_times()]
            check(starts == sorted(starts), "重なっていても、開始時刻順の並びは保たれる")

            # ==================== 5) 先頭行の前に「＋前に行」(addb) ====================
            open_doc("すきま5-前に追加")
            times_before = rows_times()
            check(times_before[0] == ("0:00.0", "0:02.0"), "前提: 先頭行は 0:00.0〜0:02.0")
            select_row(0)
            pg.locator("#segs .seg").nth(0).locator("[data-act=addb]").click()
            check(pg.locator("#segs .seg").count() == 4, "addb で行が増える")
            times = rows_times()
            check(times[0][0] == "0:00.0", "先頭行の前に足すので、新しい行の開始は 0:00.0")
            starts = [t2s(x[0]) for x in rows_times()]
            check(starts == sorted(starts), "addb の後も開始時刻順")

            # ==================== 6) 再生位置に追加(#btnAddAt)・7) 元に戻す ====================
            open_doc("すきま6-再生位置")
            times = rows_times()
            check(times == [("0:00.0", "0:02.0"), ("0:05.0", "0:07.0"), ("0:07.0", "0:09.0")], "前提の並びが揃っている: %s" % times)
            pg.evaluate("document.querySelector('#player').currentTime = 3.5")
            pg.wait_for_function("document.querySelector('#player').currentTime >= 3.4", timeout=5000)
            check(pg.get_attribute("#btnUndo", "disabled") is not None, "前提: まだ元に戻す操作はない(btnUndo は無効)")
            pg.click("#btnAddAt")
            check(pg.locator("#segs .seg").count() == 4, "btnAddAt で、再生位置(3.5秒。開始2秒〜終了5秒のすき間の中)に行が増える")
            times = rows_times()
            newrow = next(tt for tt in times if tt not in (("0:00.0", "0:02.0"), ("0:05.0", "0:07.0"), ("0:07.0", "0:09.0")))
            s, e = t2s(newrow[0]), t2s(newrow[1])
            check(abs(s - 3.2) < 0.05, "開始は max(前の行の終わり=2.0, 再生位置-0.3=3.2) = 3.2秒付近: %s" % (newrow,))
            check(abs(e - 5.0) < 0.05, "終了は min(次の行の開始=5.0, 開始+3) = 5.0秒: %s" % (newrow,))
            check(pg.get_attribute("#btnUndo", "disabled") is None, "行を足すと btnUndo が使えるようになる")
            # 7) Ctrl+Z で元に戻す
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("Control+z")
            check(pg.locator("#segs .seg").count() == 3, "Ctrl+Z で、足した行が消える(元に戻る)")
            check(rows_times() == [("0:00.0", "0:02.0"), ("0:05.0", "0:07.0"), ("0:07.0", "0:09.0")], "元の3行に戻っている")
            # もう一度足して、今度は #btnUndo ボタンで戻す
            pg.evaluate("document.querySelector('#player').currentTime = 3.5")
            pg.click("#btnAddAt")
            check(pg.locator("#segs .seg").count() == 4, "前提: もう一度行を足す")
            pg.click("#btnUndo")
            check(pg.locator("#segs .seg").count() == 3, "#btnUndo クリックでも同じように元に戻せる")

            # ==================== 8) 行の▶は、その行だけ再生する ====================
            open_doc("再生文書")
            times = rows_times()
            check(times[0] == ("0:00.0", "0:04.0") and times[1] == ("0:04.0", "0:08.0"), "前提: 疑似認識は4秒ずつ隙間なし: %s" % times[:2])
            row0_end = t2s(times[0][1])
            pg.locator("#segs .seg").nth(0).locator("[data-act=play]").click()
            try:
                pg.wait_for_function(
                    "document.querySelector('#player').paused && document.querySelector('#player').currentTime >= %s - 0.4 && document.querySelector('#player').currentTime <= %s + 0.6"
                    % (row0_end, row0_end), timeout=8000)
                check(True, "0行目の▶を押すと、その行の終わり(%.1f秒)付近で自動的に止まる(次の行へ続かない)" % row0_end)
            except Exception:
                cur = pg.evaluate("document.querySelector('#player').currentTime")
                paused = pg.evaluate("document.querySelector('#player').paused")
                check(False, "0行目の▶を押しても、その行の終わり付近(%.1f秒)で止まらなかった(現在地=%.2f, 一時停止=%s)。ヘッドレス環境で自動再生がブロックされた可能性もある" % (row0_end, cur, paused))

            # ==================== 9) 設定のポップオーバー・キー b ====================
            open_doc("メニュー文書")
            check(not pg.is_visible("#follow"), "設定のポップオーバーは、開く前は中身(#follow など)が見えない")
            pg.click("#playSet summary")
            check(pg.is_visible("#follow") and pg.is_visible("#frameFollow") and pg.is_visible("#autoNext") and pg.is_visible("#adjStep"),
                  "⚙設定 を開くと #follow・#frameFollow・#autoNext・#adjStep が見える")
            before = pg.is_checked("#autoNext")
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("b")
            check(pg.is_checked("#autoNext") != before, "キー b で「移動したら自動で再生」(#autoNext)が切り替わる")
            pg.keyboard.press("b")
            check(pg.is_checked("#autoNext") == before, "もう一度 b で元に戻る")
            pg.keyboard.press("Escape")

            # ==================== 10) キー操作: Shift+文字は何もしない/s は次へ/Shift+Space は校正済み ====================
            select_row(0)
            navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
            check(navi() == 0, "前提: 0行目を選んでいる")
            pg.keyboard.press("Shift+S")
            check(navi() == 0, "入力欄の外で Shift+S を押しても、何も起きない(選んでいる行は変わらない)")
            pg.keyboard.press("s")
            check(navi() == 1, "s(Shift無し)なら次の行へ移る")
            check(not pg.locator("#segs .seg").nth(0).evaluate("e => e.classList.contains('proofed')"), "前提: 0行目はまだ校正済みでない")
            pg.keyboard.press("w")
            check(navi() == 0, "後片付け: w で0行目に戻す")
            pg.keyboard.press("Shift+Space")
            check(pg.locator("#segs .seg").nth(0).evaluate("e => e.classList.contains('proofed')") and navi() == 1,
                  "Shift+Space で選んでいた行が校正済みになり、次の行へ移る")

            # ==================== 11) 空の文書 ====================
            open_doc("空の文書")
            check(pg.locator("#segs .seg").count() == 0, "行が無い")
            check(pg.locator("#segs [data-act=addfirst]").is_visible(), "空のときは「＋行を追加(再生位置に)」ボタンが出る")
            pg.locator("#segs [data-act=addfirst]").click()
            check(pg.locator("#segs .seg").count() == 1, "addfirst を押すと行が1つ増える")

            # ==================== 12) 文言: ▶の title・#btnAddAt の文字・空行の placeholder ====================
            play_title = pg.locator("#segs .seg").nth(0).locator("[data-act=play]").get_attribute("title") or ""
            check("この行だけ再生" in play_title, "行の▶の title に「この行だけ再生」が含まれる: %s" % play_title)
            check(pg.inner_text("#btnAddAt").strip() == "＋再生位置に行", "#btnAddAt の文字は「＋再生位置に行」(v0.15.0 で短く): %s" % pg.inner_text("#btnAddAt"))
            ph = pg.locator("#segs .seg").nth(0).locator("textarea").get_attribute("placeholder") or ""
            check("空の行" in ph, "空の行の textarea には placeholder に「空の行」が含まれる: %s" % ph)

            # ==================== 13) Z は1.5秒以内に2回押さないと消えない ====================
            open_doc("Z文書")
            select_row(1)
            check(pg.locator("#segs .seg").count() == 3, "前提: 3行")
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == 3, "1回目の Z では、まだ消えない")
            check("もう一度 Z" in pg.inner_text("#toast"), "1回目の Z で「もう一度 Z」の案内が出る: " + pg.inner_text("#toast"))
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == 2, "1.5秒以内に2回目の Z を押すと削除される")
            select_row(0)
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == 2, "前提: もう一度、1回目の Z を押した状態")
            time.sleep(1.6)   # 1.5秒の期限切れを試すための、意図した待ち(誤操作での削除を防ぐ仕様そのものを確認するため)
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == 2, "1.5秒を過ぎてからの Z は、削除されず「1回目」からやり直しになる")
            check("もう一度 Z" in pg.inner_text("#toast"), "期限切れ後の Z も「もう一度 Z」の案内から")
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == 1, "改めて1.5秒以内に押せば、ちゃんと削除できる")

            # ==================== 14) .adj/.tg は .nav の行だけ(一括選択のチェックでは変わらない) ====================
            open_doc("選択文書")
            navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
            select_row(0)
            check(navi() == 0, "前提: 0行目を選んでいる")
            check(pg.locator("#segs .seg").nth(0).locator(".adj").is_visible(), "0行目(nav)の .adj(行の操作)が見える")
            check(pg.locator("#segs .seg").nth(0).locator(".tg").is_visible(), "0行目(nav)の .tg(音の状態のタグ)が見える")
            check(not pg.locator("#segs .seg").nth(3).locator(".adj").is_visible(), "3行目はまだ選んでいないので .adj は見えない")
            sel3 = pg.locator("#segs .seg").nth(3).locator("input.sel")
            sel3.click()
            check(sel3.is_checked(), "3行目の一括選択チェックがオンになる")
            check(navi() == 0, "チェックを押しても、選んでいる行(nav)は変わらない")
            check(not pg.locator("#segs .seg").nth(3).locator(".adj").is_visible(), "チェックしただけでは、3行目の .adj は出ない")
            check(not pg.locator("#segs .seg").nth(3).locator(".tg").is_visible(), "チェックしただけでは、3行目の .tg も出ない")
            check(pg.locator("#segs .seg").nth(0).locator(".adj").is_visible(), "0行目の .adj は引き続き見える")

            # ==================== 15) クリックの信頼性 ====================
            open_doc("確実クリック文書")
            check(pg.locator("#segs .seg").count() == 8, "前提: 8行")
            ta2 = pg.locator("#segs textarea").nth(2)
            ta2.click()   # 2行目を選ぶ(そのまま入力中のままにしておく。.adj が出て行が高くなる)
            check(pg.locator("#segs .seg").nth(2).locator(".adj").is_visible(), "2行目を選ぶと .adj が出て、その行が高くなる")
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[2]"), "前提: 2行目の textarea にフォーカスがある(入力中)")
            pf6 = pg.locator("#segs .seg").nth(6).locator(".pf")
            pf6.click()
            check(pg.locator("#segs .seg").nth(6).evaluate("e => e.classList.contains('proofed')"), "6行目の「校正済み」(.pf)を実クリックすると、その行が proofed になる")
            check(pg.locator("#segs .seg").nth(6).evaluate("e => e.classList.contains('nav')"), "6行目が、選んでいる行(nav)になる")
            check(pg.evaluate("document.activeElement !== document.querySelectorAll('#segs .seg')[6].querySelector('.pf')"),
                  "ボタンを押しても、そのボタンにフォーカスは残らない(mousedown でフォーカスを奪わないため)")
            check(pg.evaluate("document.activeElement !== document.querySelectorAll('#segs textarea')[2]"),
                  "2行目で入力中だった textarea は、他の行のボタンを押すとフォーカスが外れる(確定して抜ける)")
            select_row(1)
            check(navi() == 1, "前提: 1行目を選んでいる")
            t6 = rows_times()[6]
            pg.locator("#segs .seg").nth(6).locator("[data-act=play]").click()
            pg.wait_for_function("document.querySelector('#player').currentTime >= %s - 0.3" % t2s(t6[0]), timeout=5000)
            check(navi() == 6, "選んでいる行(1行目)とは別の、下の6行目の▶を押すと、その行が選ばれて再生が始まる")

            # ==================== 16) すき間ゼロでの挿入(次の行の終了でクランプ)・タイの安定ソート ====================
            open_doc("重なり挿入文書")
            times = rows_times()
            check(times == [("0:00.0", "0:02.0"), ("0:02.0", "0:04.0"), ("0:04.0", "0:04.8"), ("0:04.0", "0:06.0")],
                  "前提: 一(0-2)・二(2-4)・三(4-4.8)・四(4-6): %s" % times)
            select_row(1)   # 「二」
            check(pg.locator("#segs .seg").nth(1).locator("textarea").input_value() == "二", "前提: 1行目は「二」")
            pg.locator("#segs .seg").nth(1).locator("[data-act=adda]").click()
            check(pg.locator("#segs .seg").count() == 5, "adda で行が増える")
            times = rows_times()
            check(times[2] == ("0:04.0", "0:04.8"), "「二」の直後(index2)に、終了は次の行「三」の終了(4.8秒)でクランプされて入る: %s" % (times[2],))
            texts = pg.evaluate("[...document.querySelectorAll('#segs .seg textarea')].map(t => t.value)")
            check(texts == ["一", "二", "", "三", "四"], "新しい行(空)は「二」の直後・「三」の前に入る: %s" % texts)
            check(pg.locator("#segs .seg").nth(2).locator(".times").evaluate("e => e.classList.contains('ovl')"),
                  "新しい行の .times には、「三」と重なっている印 .ovl が付く")
            end4 = pg.locator("#segs .seg").nth(4).locator("input.t[data-f=end]")
            check(end4.input_value() == "0:06.0", "前提: 「四」の終了は 0:06.0")
            end4.fill("0:06.5")
            end4.evaluate("el => el.blur()")
            texts2 = pg.evaluate("[...document.querySelectorAll('#segs .seg textarea')].map(t => t.value)")
            check(texts2 == ["一", "二", "", "三", "四"],
                  "無関係な行(四)の時刻を書き換えて並べ替え(sortSegs)が走っても、新しい行は「三」の前のまま(開始だけの安定ソート): %s" % texts2)

            # ==================== 17) .times.ovl の付け外し ====================
            open_doc("重なり文書1")
            times = rows_times()
            check(times == [("0:00.0", "0:03.0"), ("0:02.5", "0:05.0")], "前提: A(0-3)・B(2.5-5)が重なっている: %s" % times)
            ovl0 = pg.locator("#segs .seg").nth(0).locator(".times")
            ovl1 = pg.locator("#segs .seg").nth(1).locator(".times")
            check(ovl0.evaluate("e => e.classList.contains('ovl')") and ovl1.evaluate("e => e.classList.contains('ovl')"),
                  "重なっている行どうしは、どちらの .times にも ovl が付く")
            select_row(0)
            end0 = pg.locator("#segs .seg").nth(0).locator('[data-act=adj][data-f=end][data-d="-1"]')
            for _ in range(8):
                if not ovl0.evaluate("e => e.classList.contains('ovl')"):
                    break
                end0.click()
            check(not ovl0.evaluate("e => e.classList.contains('ovl')") and not ovl1.evaluate("e => e.classList.contains('ovl')"),
                  "行の「終了 −」(adj)ボタンで重なりを解消すると、.ovl が外れる")

            open_doc("重なり文書2")
            times = rows_times()
            check(times == [("0:00.0", "0:03.0"), ("0:02.0", "0:05.0")], "前提: C(0-3)・D(2-5)が重なっている: %s" % times)
            c_end = pg.locator("#segs .seg").nth(0).locator("input.t[data-f=end]")
            check(pg.locator("#segs .seg").nth(0).locator(".times").evaluate("e => e.classList.contains('ovl')"), "前提: 重なっている")
            c_end.fill("0:01.5")
            c_end.evaluate("el => el.blur()")
            check(not pg.locator("#segs .seg").nth(0).locator(".times").evaluate("e => e.classList.contains('ovl')"),
                  "時刻の入力欄に直接入力して重なりを解消しても、.ovl が外れる")

            # ==================== 18) 「再生位置」ボタン(setnow) ====================
            open_doc("再生位置反映文書")
            select_row(1)   # 「二」(5-7)
            check(pg.locator("#segs .seg").nth(1).locator("textarea").input_value() == "二", "前提: 1行目は「二」")
            pg.evaluate("document.querySelector('#player').currentTime = 6.0")
            pg.wait_for_function("document.querySelector('#player').currentTime >= 5.9", timeout=5000)
            pg.locator("#segs .seg").nth(1).locator("[data-act=setnow][data-f=start]").click()
            idx_two = pg.evaluate("[...document.querySelectorAll('#segs .seg textarea')].findIndex(t => t.value === '二')")
            new_start = rows_times()[idx_two][0]
            check(new_start == "0:06.0", "再生位置(6.0秒)を「開始」の「再生位置」ボタンで反映できる: %s" % new_start)
            check("開始" in pg.inner_text("#toast") and "にしました" in pg.inner_text("#toast"), "反映すると案内が出る: " + pg.inner_text("#toast"))
            pg.evaluate("document.querySelector('#player').currentTime = 8.0")
            pg.wait_for_function("document.querySelector('#player').currentTime >= 7.9", timeout=5000)
            before_start = rows_times()[idx_two][0]
            pg.locator("#segs .seg").nth(idx_two).locator("[data-act=setnow][data-f=start]").click()
            check(rows_times()[idx_two][0] == before_start, "再生位置(8.0秒)がこの行の終了(7.0秒)より後だと、開始は変わらない")
            check("終了より後" in pg.inner_text("#toast"), "その旨のトーストが出る: " + pg.inner_text("#toast"))

            # ==================== 19) 画面幅による表示: 映像側パネルの縦スクロール・話者パネルへのスクロール・メニューの自動開閉 ====================
            if "menu-closed" in app_class():
                pg.click("#btnMenu")
            pg.set_viewport_size({"width": 1280, "height": 800})
            open_doc("画面幅テスト1")
            check("menu-closed" in app_class(), "画面が狭い(1280x800)ときは、文書を開くとメニューが自動で閉じる")
            check("☰" in pg.inner_text("#toast"), "その旨のトースト(☰で開けます)が出る: " + pg.inner_text("#toast"))
            style = pg.evaluate("(() => { const el = document.querySelector('aside.tx-stage'); const c = getComputedStyle(el); return {overflowY: c.overflowY, position: c.position}; })()")
            check(style["overflowY"] == "auto", "aside.tx-stage の overflow-y は auto: %s" % style)
            check(style["position"] == "sticky", "aside.tx-stage は sticky: %s" % style)
            header_bottom = pg.evaluate("document.querySelector('header.top').getBoundingClientRect().bottom")
            pg.click("#btnSpk")   # v0.15.0: 「道具 ▾」→「話者」
            pg.click("[data-jump=spDetails]")
            pg.wait_for_function("document.querySelector('#spDetails').open === true")
            pg.wait_for_function(
                "(() => { const s = document.querySelector('#spDetails summary'); if (!s) return false; const r = s.getBoundingClientRect(); return r.top >= %s && r.top < window.innerHeight; })()"
                % header_bottom, timeout=5000)
            check(True, "「道具 ▾」→「話者」を押すと details#spDetails が開き、スムーズスクロール後に見出しがヘッダーの下・画面内に収まる(映像パネルの裏に隠れない)")
            pg.set_viewport_size({"width": 1500, "height": 1000})
            if "menu-closed" in app_class():
                pg.click("#btnMenu")
            open_doc("画面幅テスト2")
            check("menu-closed" not in app_class(), "画面が広い(1500x1000)ときは、文書を開いてもメニューは開いたまま")

            # ==================== 20) v0.9.9: メニューのタブ(GPT 版の統合)・残す/カット済 ====================
            pg2 = b.new_page(viewport={"width": 1500, "height": 1000})   # テスト用のスタイル(全部のタブを表示)なしで確かめる
            pg2.goto("http://127.0.0.1:%d/" % port)
            pg2.wait_for_selector("[data-side-tab]")
            vis = lambda sel: pg2.is_visible(sel)
            pg2.click("[data-side-tab=start]")
            check(vis("#newBox") and vis("#jobsCard") and not vis("#txCard") and not vis("#accCard"), "タブ「新規」: 新しく文字起こし・処理状況だけが見える")
            pg2.click("[data-side-tab=files]")
            check(vis("#txCard") and not vis("#newBox"), "タブ「履歴」: 保存済みの文字起こしが見える")
            pg2.click("[data-side-tab=quality]")
            check(vis("#accCard") and vis("#goalCard") and not vis("#txCard"), "タブ「精度」: 精度の測定・進行度が見える")
            pg2.click("[data-side-tab=data]")
            check(vis("#learnCard") and not vis("#accCard"), "タブ「学習」: 修正から学習した候補が見える")
            pg2.click("#goalPill") if pg2.is_visible("#goalPill") else pg2.evaluate("document.querySelector('#goalPill').click()")
            check(vis("#goalCard"), "上の進行度の表示を押すと、メニューが開いて「精度」タブに切り替わる")
            pg2.reload(); pg2.wait_for_selector("[data-side-tab]")
            check(pg2.get_attribute("[data-side-tab=quality]", "aria-selected") == "true", "選んだタブは、開き直しても覚えている")
            pg2.click("#btnMenu")
            check(not vis("[data-side-tab=files]"), "☰ でタブごとメニューが閉じる")
            pg2.click("#btnMenu")
            pg2.click("[data-side-tab=files]")
            pg2.fill("#txSearch", "メニュー文書")
            pg2.locator("#txList .txi").filter(has_text="メニュー文書").locator(".t").first.click()
            pg2.wait_for_selector("#segs .seg")
            row = pg2.locator("#segs .seg").first
            check(row.locator(".ops [data-act=cut]").count() == 1 and row.locator(".ops .pf").count() == 1, "行の「残す/カット済」が「校正済み」の隣にある")
            row.locator("[data-act=cut]").click()
            check("cut" in (row.get_attribute("class") or "") and row.locator("[data-act=cut]").inner_text() == "カット済", "「残す」を押すとカット済になる(取り消し線)")
            check(pg2.locator(".row-more").count() == 0, "GPT 版の「…」メニューは使わない(操作は選んだ行の下の段)")
            pg2.close()

            b.close()

        # 409(保存の競合)は、短い間隔で連続して行を足す/戻すテスト(6・7)で自動保存どうしがぶつかると起きうる、
        # このツールの自動保存の仕様どおりの動き(e2e_ui_v08.py と同じ理由でここでも除外する)
        errors = [e for e in errors if "favicon" not in e and "409" not in e]
        check(not errors, "画面のエラーなし " + ("" if not errors else str(errors[:5])))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
