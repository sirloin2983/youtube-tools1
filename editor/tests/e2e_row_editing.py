#!/usr/bin/env python3
"""行の編集の通し確認(Playwright + 疑似モード): 左メニューの開閉・行の追加(前後・すき間・N・＋行を追加)・
   元に戻す・行の▶単独再生・設定のポップオーバー・左手キー操作・空の文書。

    python3 editor/tests/e2e_row_editing.py
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

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツール(editor/)のフォルダ
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
    for n in ("serve.py", "index.html", "app.js", "cut.js", "pack-tab.js", "ui-kit.js", "hololive-roster.json", "roster.py", "pipeline_io.py", "resolve_export.py") + tuple(n for n in sorted(os.listdir(HERE)) if (n.startswith("ed_") and n.endswith(".py")) or (n.startswith("app-") and n.endswith(".js"))):   # 段10 で serve.py・app.js から分けた部品   # 受け渡しの API(pipeline_io)・Resolve 書き出しも使うので一緒に写す
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py", "tx_engines.py"):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
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
        tid_ovl3 = make(); set_segs(tid_ovl3, "丸め文書1", [{"id": "q0", "start": 45.6, "end": 47.35, "text": "前の前"}, {"id": "q1", "start": 47.35, "end": 48.94, "text": "時間ぐらい"}, {"id": "q2", "start": 49.04, "end": 50.0, "text": "あのー"}])   # 2026-10-04 の報告の形(最後の行が赤くなった)
        tid_ovl4 = make(); set_segs(tid_ovl4, "丸め文書2", [{"id": "u0", "start": 47.35, "end": 49.04, "text": "前"}, {"id": "u1", "start": 49.0, "end": 50.0, "text": "後"}])   # 0.1 秒に丸めると同じ時刻(0.01 秒だけ重なる)
        tid_ovl5 = make(); set_segs(tid_ovl5, "丸め文書3", [{"id": "k0", "start": 45.6, "end": 48.94, "text": "前"}, {"id": "k1", "start": 49.04, "end": 50.0, "text": "後"}])
        two_sp = [{"id": "S1", "name": "ぺこら", "color": "#2f62d6"}, {"id": "S2", "name": "みこ", "color": "#d9534f"}]
        tid_spk = make(); set_segs(tid_spk, "話者の重なり文書", [   # 2026-10-05: 重なりの赤は同じ話者どうし(か話者の無い行)だけ・重なる字幕は 2 段
            {"id": "x0", "start": 0, "end": 3, "text": "A", "speaker": "S1"}, {"id": "x1", "start": 2, "end": 5, "text": "B", "speaker": "S2"},
            {"id": "x2", "start": 6, "end": 9, "text": "C", "speaker": "S1"}, {"id": "x3", "start": 8.5, "end": 10, "text": "D", "speaker": "S1"},
            {"id": "x4", "start": 11, "end": 13, "text": "E", "speaker": ""}, {"id": "x5", "start": 12, "end": 14, "text": "F", "speaker": "S2"},
            {"id": "x6", "start": 15, "end": 18, "text": "G", "speaker": "S1"}, {"id": "x7", "start": 17.9, "end": 19, "text": "H", "speaker": "S2"}], two_sp)
        tid_other = make(); set_segs(tid_other, "ゲーム音声文書", [   # 組み込みの話者「ゲーム音声など」と「字幕に出さない」
            {"id": "y0", "start": 0, "end": 3, "text": "配信者", "speaker": "S1"}, {"id": "y1", "start": 2, "end": 5, "text": "NPC", "speaker": "S1"},
            {"id": "y2", "start": 6, "end": 8, "text": "次", "speaker": "S1"}], two_sp)
        # 重なりの所の空の行の下書き(2026-10-05): 判別の記録 diar.json を直接置く(疑似の判別は 10 秒ごとの入れ替わりで重なりを作らないため)。
        # 声の区間 = ラベル 0(ぺこら・主)0-20・ラベル 1(行の付かなかった声)3-5・ラベル 2(みこ)12-14 → 候補は 3-5(話者なし)と 12-14(みこ)
        ovd_rows = [{"id": "d0", "start": 0, "end": 10, "text": "主の話", "speaker": "S1"}, {"id": "d1", "start": 10, "end": 20, "text": "続き", "speaker": "S1"}]
        tid_ovd = make(); set_segs(tid_ovd, "重なり下書き文書", ovd_rows, two_sp)
        tid_ovd_ev = make()
        call(port, "PUT", "/api/transcript?id=" + tid_ovd_ev, {"title": "重なり下書き評価用", "evalSet": True, "speakers": two_sp, "segments": ovd_rows + [
            {"id": "d2", "start": 3, "end": 5, "text": "", "speaker": "", "tags": ["overlap"], "draft": "overlap"}]})
        # 抜けの所の空の行(why missing): 主(ぺこら)の声 0-20 のうち 8-11 にどの行も無い・みこの声 14-16 は重なり → 重なり 1 か所・抜け 1 か所
        tid_miss = make(); set_segs(tid_miss, "抜け下書き文書", [{"id": "m0", "start": 0, "end": 8, "text": "前半", "speaker": "S1"},
                                                             {"id": "m1", "start": 11, "end": 20, "text": "後半", "speaker": "S1"}], two_sp)
        txdir = os.path.join(tmp, "transcripts")
        with open(os.path.join(txdir, tid_miss + ".diar.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-diar/v1", "history": [], "latest": {
                "at": 1, "engine": {"name": "fake"}, "offset": 0.0, "labelMap": {"0": "S1", "2": "S2"}, "rows": {},
                "turns": [{"start": 0, "end": 20, "label": 0}, {"start": 14, "end": 16, "label": 2}], "overlaps": [[14, 16]]}}, f)
        check(os.path.isfile(os.path.join(txdir, tid_ovd + ".json")), "前提: 文書の置き場所 %s" % txdir)
        for t in (tid_ovd, tid_ovd_ev):
            with open(os.path.join(txdir, t + ".diar.json"), "w", encoding="utf-8") as f:
                json.dump({"schema": "youtube-tools-diar/v1", "history": [], "latest": {
                    "at": 1, "engine": {"name": "fake"}, "offset": 0.0, "labelMap": {"0": "S1", "2": "S2"}, "rows": {},
                    "turns": [{"start": 0, "end": 20, "label": 0}, {"start": 3, "end": 5, "label": 1}, {"start": 12, "end": 14, "label": 2}],
                    "overlaps": [[3, 5], [12, 14]]}}, f)
        tid_setnow = make(); set_segs(tid_setnow, "再生位置反映文書",[{"id": "n0", "start": 0, "end": 2, "text": "一"}, {"id": "n1", "start": 5, "end": 7, "text": "二"}])
        tid_stage1 = make(); set_segs(tid_stage1, "画面幅テスト1", [{"id": "w0", "start": 0, "end": 2, "text": "一"}, {"id": "w1", "start": 2, "end": 4, "text": "二"}])
        tid_stage2 = make(); set_segs(tid_stage2, "画面幅テスト2", [{"id": "v0", "start": 0, "end": 2, "text": "一"}, {"id": "v1", "start": 2, "end": 4, "text": "二"}])

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1920, "height": 1000})
            pg = ctx.new_page()
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は editor/tests/e2e_row_editing.py で確認)
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
                    "[r.querySelector('.t[data-f=start]').textContent, r.querySelector('.t[data-f=end]').textContent])")]

            def type_time(loc, digits):
                """時刻の欄(UIKit.timebox。分:秒.0.1秒)に数字だけで入れて、欄を離れて確定する"""
                loc.focus()
                pg.keyboard.type(digits)
                loc.evaluate("el => el.blur()")

            def select_row(i):
                pg.locator("#segs textarea").nth(i).click()
                pg.keyboard.press("Escape")

            def wait_js(pg, expr, timeout=5000):
                """式が真になるまで待つ -> 真になったか(時間切れは False。check で FAIL と出す)"""
                end = time.time() + timeout / 1000
                while time.time() < end:
                    if pg.evaluate(expr):
                        return True
                    time.sleep(0.05)
                return False

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
            # 再読み込みで状態が残る(localStorage)。開いた文書は URL の ?doc= で開き直すので(監査 06)、?doc= を外して読み込む
            pg.evaluate("history.replaceState(null, '', location.pathname + location.hash)")
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

            # ==================== 9) 再生・編集の設定のポップオーバー・設定の引き出し(段2: B キーはやめて設定の引き出しへ) ====================
            open_doc("メニュー文書")
            check(not pg.is_visible("#follow") and pg.locator("#playSet").count() == 0, "映像の下に2つ目の「設定」は無い(B-9: 設定は右上の ⚙ の1か所)")
            pg.click("[data-ui-settings]")
            check(pg.is_visible("#follow") and pg.is_visible("#frameFollow") and pg.is_visible("#adjStep"),
                  "右上の ⚙ 設定を開くと #follow・#frameFollow・#adjStep が見える")
            pg.keyboard.press("Escape")
            pg.click("[data-ui-settings]")
            pg.wait_for_selector("#autoNext", state="visible")
            before = pg.is_checked("#autoNext")
            pg.click("#autoNext")
            check(pg.is_checked("#autoNext") != before, "設定の引き出しで「移動したら自動で再生」(#autoNext)を切り替えられる")
            pg.click("#autoNext")
            check(pg.is_checked("#autoNext") == before, "もう一度で元に戻る")
            pg.keyboard.press("Escape")

            # ==================== 10) キー操作: Shift+文字は何もしない/↓ は次へ/Shift+Space は校正済み ====================
            select_row(0)
            navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
            check(navi() == 0, "前提: 0行目を選んでいる")
            pg.keyboard.press("Shift+F")
            check(navi() == 0, "入力欄の外で Shift+F を押しても、何も起きない(選んでいる行は変わらない)")
            pg.keyboard.press("ArrowDown")
            check(navi() == 1, "↓(Shift無し)なら次の行へ移る")
            check(not pg.locator("#segs .seg").nth(0).evaluate("e => e.classList.contains('proofed')"), "前提: 0行目はまだ校正済みでない")
            pg.keyboard.press("ArrowUp")
            check(navi() == 0, "後片付け: ↑ で0行目に戻す")
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
            end4 = pg.locator("#segs .seg").nth(4).locator(".t[data-f=end]")
            check(end4.text_content() == "0:06.0", "前提: 「四」の終了は 0:06.0: %r" % end4.text_content())
            type_time(end4, "0065")
            check(pg.locator("#segs .seg").nth(4).locator(".t[data-f=end]").text_content() == "0:06.5", "時刻の欄に 0065 → 0:06.5(「:」を打たない): %r" % pg.locator("#segs .seg").nth(4).locator(".t[data-f=end]").text_content())
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
            c_end = pg.locator("#segs .seg").nth(0).locator(".t[data-f=end]")
            check(pg.locator("#segs .seg").nth(0).locator(".times").evaluate("e => e.classList.contains('ovl')"), "前提: 重なっている")
            type_time(c_end, "0015")
            check(not pg.locator("#segs .seg").nth(0).locator(".times").evaluate("e => e.classList.contains('ovl')"),
                  "時刻の入力欄に直接入力して重なりを解消しても、.ovl が外れる")

            # ==================== 17b) 先頭・最後の行の .ovl(2026-10-04 の報告)と、0.1 秒の丸め・そろえ ====================
            # 原因: markOvl の classList.toggle(…, ovl(j)) に、前後に行の無い最後の行で undefined が渡り、「付け外しの反転」になっていた(押すたびに赤白)
            has_ovl = lambda i: pg.locator("#segs .seg").nth(i).locator(".times").evaluate("e => e.classList.contains('ovl')")
            segv = lambda: pg.evaluate("S.doc.segments.map(s => [s.start, s.end])")
            adj = lambda i, f, d: pg.locator("#segs .seg").nth(i).locator('[data-act=adj][data-f=%s][data-d="%d"]' % (f, d)).click()
            open_doc("丸め文書1")
            check(not any(has_ovl(i) for i in range(3)), "前提: 前の行 47.35-48.94・最後の行 49.04-50.0 は重なっていない(赤くない)")
            select_row(2)
            adj(2, "end", 1)
            check(segv()[2][1] == 50.1 and not has_ovl(2), "最後の行の「終了 ＋」で、最後の行が赤くならない(以前は undefined の toggle で反転して赤くなった): %s" % (segv()[2],))
            adj(2, "end", 1)
            check(not has_ovl(2), "もう一度押しても赤くならない(押すたびに反転しない)")
            adj(2, "end", -1); adj(2, "end", -1)
            check(not has_ovl(2), "「終了 −」でも赤くならない")
            adj(2, "start", -1)
            check(abs(segv()[2][0] - 48.94) < 1e-9 and not has_ovl(2) and not has_ovl(1), "最後の行の「開始 −」で前の行の終了 48.94 とぴったり = 重ならない(赤くならない)")
            adj(2, "start", -1)
            check(has_ovl(2) and has_ovl(1), "さらに 0.1 秒早めて本当に重なったら、最後の行も前の行も赤くなる(%s)" % (segv()[1:],))
            adj(2, "start", 1)
            check(not has_ovl(2) and not has_ovl(1), "戻すと、どちらの赤も外れる")
            select_row(0)
            adj(0, "start", -1); adj(0, "start", 1)
            check(not has_ovl(0), "先頭の行の微調整でも(前に行が無くても)赤くならない")
            pg.evaluate("document.activeElement && document.activeElement.blur()")
            pg.keyboard.press("Control+z")
            check(not any(has_ovl(i) for i in range(3)), "元に戻す(Z)のあとも赤い行は無い")

            open_doc("丸め文書2")
            check(segv() == [[47.35, 49.04], [49.0, 50.0]] and not has_ovl(0) and not has_ovl(1),
                  "前の行の終了 49.04・次の行の開始 49.0(どちらも表示は 0:49.0)は、見えている時刻で重なっていないので赤くしない: %s" % (segv(),))
            type_time(pg.locator("#segs .seg").nth(1).locator(".t[data-f=start]"), "0485")
            check(has_ovl(0) and has_ovl(1), "開始を 0:48.5 にすると、本当に重なるので赤くなる")
            type_time(pg.locator("#segs .seg").nth(1).locator(".t[data-f=start]"), "0490")
            check(segv()[1][0] == 49.04 and not has_ovl(0) and not has_ovl(1), "開始を 0:49.0 に直すと、前の行の終了(表示が同じ)の 49.04 にぴったりそろい、赤くならない: %s" % (segv(),))
            check(pg.locator("#segs .seg").nth(1).locator(".t[data-f=start]").text_content() == "0:49.0", "そろえたあとも欄の表示は 0:49.0")

            open_doc("丸め文書3")
            type_time(pg.locator("#segs .seg").nth(0).locator(".t[data-f=end]"), "0490")
            check(segv()[0][1] == 49.04 and not has_ovl(0) and not has_ovl(1), "前の行の終了を 0:49.0 にすると、次の行の開始(表示が同じ)の 49.04 にそろう: %s" % (segv(),))
            check(pg.locator("#segs .seg").nth(0).locator(".t[data-f=end]").text_content() == "0:49.0", "そろえたあとも欄の表示は 0:49.0")
            select_row(0)
            pg.evaluate("V.adjStep = '0.05'")
            adj(0, "end", -1)
            check(segv()[0][1] == 48.99, "隣から離れる向きの微調整(0.05 秒)では隣の値へ引き戻されない(49.04 → 48.99): %s" % (segv()[0],))
            check(not has_ovl(0) and not has_ovl(1), "離れたあとも赤くない")
            adj(0, "end", 1)
            check(segv()[0][1] == 49.04, "隣へ近づける向き(0.05 秒)で見える時刻が同じになったら、隣の 49.04 にそろう: %s" % (segv()[0],))
            pg.evaluate("V.adjStep = '0.1'")

            # ==================== 17c) 重なりの赤は同じ話者どうしだけ・重なる字幕は 2 段・ゲーム音声など と 字幕に出さない(2026-10-05) ====================
            open_doc("話者の重なり文書")
            check(not has_ovl(0) and not has_ovl(1), "別の話者どうしの重なり(ぺこら 0-3・みこ 2-5)は赤くしない(同時にしゃべっている = 正しい入力)")
            check(has_ovl(2) and has_ovl(3), "同じ話者どうしの重なりは今までどおり赤")
            check(has_ovl(4) and has_ovl(5), "どちらかに話者が無い重なりも赤")
            check("同じ話者" in (pg.locator("#segs .seg").nth(2).locator(".times").get_attribute("title") or ""), "赤い欄の説明は「同じ話者の行と…」")
            cap_lines = "[...document.querySelectorAll('#playerCaption .tt-cap-line')].map(e => e.textContent)"
            seek = lambda t: pg.evaluate("t => { const p = document.querySelector('#player'); p.pause(); p.currentTime = t; }", t)
            seek(2.5)
            check(wait_js(pg, "JSON.stringify(%s) === '[\"B\",\"A\"]'" % cap_lines, 5000),
                  "0.3 秒以上重なる 2 行は映像の上の字幕に両方(上下に積む・開始が早い A が下): %s" % pg.evaluate(cap_lines))
            seek(17.95)
            check(wait_js(pg, "document.querySelector('#playerCaption').textContent === 'H' && !document.querySelector('#playerCaption .tt-cap-line')", 5000),
                  "重なりが 0.3 秒未満(G 15-18・H 17.9-19)なら今までどおり後の行だけ: %s" % pg.evaluate("document.querySelector('#playerCaption').innerHTML"))
            # 話者ごとの字幕の色(# なしの 6 桁。貼り付けた # は外す)。映像の上の字幕の色に最優先で効く
            pg.evaluate("document.querySelector('#spDetails').open = true")
            sub_in = pg.locator("#spList input[data-f=sub]").nth(1)
            sub_in.fill("#ff8fdf")
            check(sub_in.input_value() == "FF8FDF", "字幕の色の欄は 16 進だけ・大文字に寄せる(# は外す): %s" % sub_in.input_value())
            sub_in.evaluate("e => e.blur()")
            check(wait_js(pg, "S.doc.speakers[1].sub && S.doc.speakers[1].sub.color === '#FF8FDF'", 3000), "確定すると文書の話者の sub.color に入る")
            seek(2.5)
            check(wait_js(pg, "(() => { const s = document.querySelector('#playerCaption .tt-cap-line'); return !!s && s.textContent === 'B' && s.style.getPropertyValue('--tt-cap-color').toUpperCase() === '#FF8FDF'; })()", 5000),
                  "みこの字幕(上の段)は指定の色")
            wait_saved()
            sv = call(port, "GET", "/api/transcript?id=" + tid_spk)
            check(sv["speakers"][1].get("sub") == {"color": "#FF8FDF"}, "保存される: %s" % sv["speakers"][1])
            sub_in = pg.locator("#spList input[data-f=sub]").nth(1)
            sub_in.fill("")
            sub_in.evaluate("e => e.blur()")
            check(wait_js(pg, "!S.doc.speakers[1].sub", 3000), "空にすると指定なし(sub ごと持たない)")

            open_doc("ゲーム音声文書")
            check(has_ovl(0) and has_ovl(1), "前提: 同じ話者(ぺこら)の行どうしが重なっていて赤い")
            sel1 = pg.locator("#segs .seg").nth(1).locator("select.spk")
            check(pg.evaluate("[...document.querySelectorAll('#segs .seg')[1].querySelector('select.spk').options].map(o => o.textContent)") == ["話者なし", "ゲーム音声など", "ぺこら", "みこ"],
                  "話者の候補に「ゲーム音声など」が常に出る(話者なしの次・文書の話者より前)")
            sel1.select_option("other")
            row1 = pg.locator("#segs .seg").nth(1)
            check("nosub" in (row1.get_attribute("class") or "") and row1.locator(".tt-nosub-pill").is_visible(), "「ゲーム音声など」を選ぶと行が薄くなり、札「字幕に出さない」が出る")
            check(row1.locator("[data-act=nosub]").get_attribute("aria-pressed") == "true", "行の「字幕に出さない」のボタンもオン")
            check(pg.evaluate("S.doc.speakers.map(s => s.id)") == ["S1", "S2", "other"], "文書の話者に組み込みの話者が 1 つだけ入る(最後): %s" % pg.evaluate("S.doc.speakers.map(s => s.id)"))
            check(not has_ovl(0) and not has_ovl(1), "字幕に出さない行との重なりは赤くしない")
            seek(2.5)
            check(wait_js(pg, "document.querySelector('#playerCaption').textContent === '配信者' && !document.querySelector('#playerCaption .tt-cap-line')", 5000),
                  "字幕に出さない行は映像の上の字幕に出ない(重なっていても 1 段)")
            check("1 行" in pg.text_content("#exNoSub") and not pg.locator("#exNoSub").get_attribute("hidden"), "書き出しのカードに「字幕に出さない行: 1 行」: %s" % pg.text_content("#exNoSub"))
            wait_saved()
            sv = call(port, "GET", "/api/transcript?id=" + tid_other)
            check(sv["segments"][1].get("noSub") is True and sv["segments"][1]["speaker"] == "other" and sv["speakers"][-1] == {"id": "other", "name": "ゲーム音声など", "color": "#8a8f98", "builtin": "other"},
                  "保存: 行の noSub と組み込みの話者(builtin)")
            select_row(1)
            pg.keyboard.press("2")   # 番号は組み込みを除いた並び(1 = ぺこら・2 = みこ)
            check(pg.evaluate("[S.doc.segments[1].speaker, !!S.doc.segments[1].noSub]") == ["S2", False], "別の話者へ変えると「字幕に出さない」が外れる(数字キーの番号は今までどおり)")
            check("nosub" not in (row1.get_attribute("class") or "") and not has_ovl(1), "薄い表示も外れ、別の話者どうしなので赤くない")
            select_row(2)
            btn = pg.locator("#segs .seg").nth(2).locator("[data-act=nosub]")
            btn.click()
            check(pg.evaluate("S.doc.segments[2].noSub === true && S.doc.segments[2].speaker === 'S1'") and "nosub" in (pg.locator("#segs .seg").nth(2).get_attribute("class") or ""),
                  "ほかの話者の行でも 1 クリックで「字幕に出さない」(話者はそのまま)")
            btn.click()
            check(pg.evaluate("!S.doc.segments[2].noSub"), "もう一度押すと字幕に出す")
            wait_saved()

            # ==================== 17-2) 重なりの所に空の行を置く(2026-10-05) ====================
            open_doc("重なり下書き文書")
            pg.evaluate("document.querySelector('#spDetails').open = true")
            check(wait_js(pg, "document.querySelector('#ovdCount').textContent.includes('2 か所')", 5000) and not pg.locator("#ovdGo").is_disabled(),
                  "話者のカードに「声があるのに行の無い所: 2 か所」・ボタンが押せる: %s" % pg.text_content("#ovdCount"))
            check(pg.locator("#ovdClear").is_hidden(), "空のままの下書きが無いうちは「消す」を出さない")
            pg.click("#ovdGo")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            check("2 か所に空の行を置きます" in pg.inner_text("dialog.ui-dialog[open]"), "置く前に確認する: %s" % pg.inner_text("dialog.ui-dialog[open]")[:80])
            pg.click("dialog.ui-dialog[open] .btn.primary")
            check(wait_js(pg, "S.doc.segments.length === 4", 5000), "確かめると 2 行が足される")
            drafts = pg.evaluate("S.doc.segments.map((g, i) => [i, g.start, g.end, g.speaker, g.text, (g.tags || []).join(), g.draft || '']).filter(x => x[6])")
            check([d[1:] for d in drafts] == [[3, 5, "", "", "overlap", "overlap"], [12, 14, "S2", "", "overlap", "overlap"]],
                  "足した行 = 時刻・候補の話者(分からなければ空)・文字なし・声が重なるのメモ・下書きの印: %s" % drafts)
            i1, i2 = drafts[0][0], drafts[1][0]
            r1 = pg.locator("#segs .seg").nth(i1)
            check("tt-draft" in (r1.get_attribute("class") or "") and r1.locator(".tt-draft-pill").is_visible() and "聞いて打って" in (r1.locator("textarea").get_attribute("placeholder") or ""),
                  "行に札「下書き(重なり)」と「聞いて打ってください」")
            check(not has_ovl(i1) and not has_ovl(i2) and not has_ovl(0), "空の下書きは重なりの赤にしない(話者なしでも)")
            seek(4.0)
            check(wait_js(pg, "document.querySelector('#playerCaption').textContent === '主の話' && !document.querySelector('#playerCaption .tt-cap-line')", 5000),
                  "空の下書きは映像の上の字幕に出ない")
            wait_saved()
            sv = call(port, "GET", "/api/transcript?id=" + tid_ovd)
            check([g.get("draft") for g in sv["segments"]].count("overlap") == 2, "保存される(印 draft)")
            v1 = call(port, "GET", "/api/transcript-v1?id=" + tid_ovd)
            check([g["id"] for g in v1["segments"]] == ["d0", "d1"], "パック・字幕へ渡す transcript/v1 に空の下書きは入らない: %s" % [g["id"] for g in v1["segments"]])
            check(wait_js(pg, "document.querySelector('#ovdCount').textContent.includes('ありません') && document.querySelector('#ovdGo').disabled", 5000),
                  "置いたあとは数え直して 0(2 回押しても増えない): %s" % pg.text_content("#ovdCount"))
            check(pg.text_content("#ovdClear") == "空のままの下書きを消す(2 行)", "「空のままの下書きを消す(2 行)」が出る: %s" % pg.text_content("#ovdClear"))
            pg.select_option("#flagKind", "draft")
            check(pg.evaluate("[...document.querySelectorAll('#segs .seg')].filter(r => !r.hidden).length") == 2, "絞り込み「重なりの下書きだけ」で 2 行")
            pg.select_option("#flagKind", "")
            r1.locator("textarea").click()
            pg.keyboard.type("うんうん")
            check(pg.evaluate("!S.doc.segments[%d].draft && S.doc.segments[%d].text === 'うんうん'" % (i1, i1)) and "tt-draft" not in (r1.get_attribute("class") or "") and r1.locator(".tt-draft-pill").count() == 0,
                  "文字を打つと下書きの印・札が外れる")
            check(has_ovl(i1), "打った行は普通の行(話者が無いので、主の行との重なりは赤 = 話者を付けるよう知らせる)")
            check(pg.text_content("#ovdClear") == "空のままの下書きを消す(1 行)", "空のままは 1 行: %s" % pg.text_content("#ovdClear"))
            pg.keyboard.press("Escape")
            wait_saved()
            check("draft" not in call(port, "GET", "/api/transcript?id=" + tid_ovd)["segments"][i1], "保存しても印は無い")
            pg.click("#btnUndo")
            check(wait_js(pg, "S.doc.segments.length === 2 && !S.doc.segments.some(g => g.draft || g.text === 'うんうん')", 5000), "元に戻す 1 回で、置いた行が全部消える(打った文字も)")
            check(wait_js(pg, "document.querySelector('#ovdCount').textContent.includes('2 か所')", 8000), "戻して保存すると、また 2 か所: %s" % pg.text_content("#ovdCount"))
            pg.click("#ovdGo")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            pg.click("dialog.ui-dialog[open] .btn.primary")
            check(wait_js(pg, "S.doc.segments.length === 4", 5000), "もう一度置く")
            pg.click("#ovdClear")
            check(wait_js(pg, "S.doc.segments.length === 2 && document.querySelector('#ovdClear').hidden", 5000), "「空のままの下書きを消す」で空のままの行だけ消える")
            wait_saved()
            check(len(call(port, "GET", "/api/transcript?id=" + tid_ovd)["segments"]) == 2, "消したことも保存される")

            # 評価用: 空のままの下書きが残っていたら「済みにする」の前に消すか確かめる・確かめ済みの文書には置けない
            open_doc("重なり下書き評価用")
            check(pg.evaluate("S.doc.segments.filter(g => g.draft === 'overlap').length") == 1, "前提: サーバーに保存した空の下書きが 1 行")
            pg.click("#evrMark")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            check("が 1 行あります。消して済みにしますか" in pg.inner_text("dialog.ui-dialog[open]"), "済みにする前に「空のままの下書きが 1 行あります。消して済みにしますか」: %s" % pg.inner_text("dialog.ui-dialog[open]")[:80])
            pg.click("dialog.ui-dialog[open] .btn.primary")
            check(wait_js(pg, "!!S.doc.evalReviewed", 8000), "消して済みにした")
            sv = call(port, "GET", "/api/transcript?id=" + tid_ovd_ev)
            check(sv.get("evalReviewed") and not any(g.get("draft") for g in sv["segments"]) and len(sv["segments"]) == 2, "保存: 下書きは消えて確かめ済み")
            pg.evaluate("document.querySelector('#spDetails').open = true")
            check(wait_js(pg, "document.querySelector('#ovdGo').disabled && document.querySelector('#ovdCount').textContent.includes('確かめ済み')", 5000),
                  "確かめ済みの文書には置けない(理由を出す): %s" % pg.text_content("#ovdCount"))

            # 17-2b) 抜けの所(主の話者も含めて、声があるのにどの行も無い所。印 draft "missing"・音のメモは付けない)と、置く所を選ぶ
            open_doc("抜け下書き文書")
            pg.evaluate("document.querySelector('#spDetails').open = true")
            check(wait_js(pg, "document.querySelector('#ovdCount').textContent.includes('重なり 1 か所・抜け 1 か所')", 5000),
                  "数を重なりと抜けに分けて出す: %s" % pg.text_content("#ovdCount"))
            pg.uncheck("#ovdKOvl")
            check(wait_js(pg, "OVD.items.length === 1 && OVD.items[0].why === 'missing' && !document.querySelector('#ovdGo').disabled", 5000), "「重なり」を外すと抜けだけ")
            pg.uncheck("#ovdKMiss")
            check(wait_js(pg, "document.querySelector('#ovdGo').disabled && document.querySelector('#ovdCount').textContent.includes('1 つ以上選んで')", 5000),
                  "どちらも外すと押せない(理由を出す): %s" % pg.text_content("#ovdCount"))
            pg.check("#ovdKMiss")
            check(wait_js(pg, "!document.querySelector('#ovdGo').disabled", 5000), "抜けを選び直すと押せる")
            pg.click("#ovdGo")
            pg.wait_for_selector("dialog.ui-dialog[open]")
            check("1 か所に空の行を置きます(重なり 0 か所・抜け 1 か所)" in pg.inner_text("dialog.ui-dialog[open]"), "確認でも分けて出す: %s" % pg.inner_text("dialog.ui-dialog[open]")[:80])
            pg.click("dialog.ui-dialog[open] .btn.primary")
            check(wait_js(pg, "S.doc.segments.length === 3", 5000), "抜けの 1 行だけ足される")
            dm = pg.evaluate("S.doc.segments.map((g, i) => [i, g.start, g.end, g.speaker, g.text, (g.tags || []).join(), g.draft || '']).filter(x => x[6])")
            check([d[1:] for d in dm] == [[8, 11, "S1", "", "", "missing"]], "抜けの行 = 時刻・主の話者・文字なし・音のメモなし・印 missing: %s" % dm)
            rm = pg.locator("#segs .seg").nth(dm[0][0])
            check(rm.locator(".tt-draft-pill").text_content().strip() == "下書き(抜け)" and "抜けの下書き" in (rm.locator("textarea").get_attribute("placeholder") or ""),
                  "札「下書き(抜け)」と案内: %s / %s" % (rm.locator(".tt-draft-pill").inner_text(), rm.locator("textarea").get_attribute("placeholder")))
            pg.select_option("#flagKind", "draft")
            check(pg.evaluate("[...document.querySelectorAll('#segs .seg')].filter(r => !r.hidden).length") == 1, "絞り込み「下書きだけ」に抜けの行も入る")
            pg.select_option("#flagKind", "")
            wait_saved()
            check([g.get("draft") for g in call(port, "GET", "/api/transcript?id=" + tid_miss)["segments"]] == [None, "missing", None], "保存される(印 missing)")
            check(wait_js(pg, "document.querySelector('#ovdCount').textContent.includes('重なり 1 か所・抜け 0 か所')", 5000),
                  "置いたあとは抜けが 0(重なりは残る): %s" % pg.text_content("#ovdCount"))
            rm.locator("textarea").click()
            pg.keyboard.type("抜けてた")
            check(pg.evaluate("!S.doc.segments[%d].draft" % dm[0][0]) and rm.locator(".tt-draft-pill").count() == 0, "文字を打つと抜けの印も外れる")
            pg.keyboard.press("Escape")
            pg.check("#ovdKOvl")
            wait_saved()

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
            # その旨のトーストは、この画面を開いている間に1回だけ(段3-3)。このテストではすでに前の段で出ているので、ここでは確かめない
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
            pg.set_viewport_size({"width": 1920, "height": 1000})
            if "menu-closed" in app_class():
                pg.click("#btnMenu")
            open_doc("画面幅テスト2")
            check("menu-closed" not in app_class(), "画面が広い(1500x1000)ときは、文書を開いてもメニューは開いたまま")

            # ==================== 20) v0.9.9: メニューのタブ(GPT 版の統合)・残す/カット済 ====================
            pg2 = b.new_page(viewport={"width": 1920, "height": 1000})   # テスト用のスタイル(全部のタブを表示)なしで確かめる
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
        # このツールの自動保存の仕様どおりの動き(e2e_proofread_keys.py と同じ理由でここでも除外する)
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
