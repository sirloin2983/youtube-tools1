#!/usr/bin/env python3
"""v0.8.0 の画面の通し確認(Playwright + 疑似モード): 集中モード・表示設定・左手だけのキー操作(Shift+キー)・タグ・保管・自動再生・進み具合の帯・用語挿入・
続きから・履歴・保存の競合・数千行での速さ。

    python3 e2e_ui_v071.py [スクリーンショットの保存先フォルダ]
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
SHOTS = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
BIG = 4000
QS = "?nofs=1" if "--nofs" in sys.argv else ""


def call(port, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    tmp = tempfile.mkdtemp()
    for n in ("serve.py", "index.html", "app.js", "cut.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):   # 受け渡しの API(pipeline_io)・Resolve 書き出しも使うので一緒に写す
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            shutil.copy(p, tmp)
    wav = os.path.join(tmp, "sample.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=24", wav], check=True)
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"glossary": "ホロライブ\nトワ", "model": "small", "language": "ja"}, f)
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

    try:
        for _ in range(100):
            try:
                call(port, "GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)

        def make():
            j = call(port, "POST", "/api/transcribe", {"sourcePath": wav, "model": "small", "language": "ja", "glossary": "ホロライブ\nトワ", "autoGloss": False})
            for _ in range(200):
                jobs = call(port, "GET", "/api/jobs")["jobs"]
                job = next(x for x in jobs if x["id"] == j["id"])
                if job["state"] in ("done", "error"):
                    return job["tid"]
                time.sleep(0.1)

        tid = make()
        d = call(port, "GET", "/api/transcript?id=" + tid)
        # 校正の流れ用: 2行目を要確認に、1行目を校正済みに
        d["segments"][1]["flag"] = "認識が不確か"
        d["segments"][0]["proofed"] = True
        SPK = [{"id": "S1", "name": "トワ", "color": "#2f62d6"}]
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": d["title"], "speakers": SPK, "segments": d["segments"]})
        n = len(d["segments"])
        # 数千行の文字起こし(別の文書)
        tid2 = make()
        d2 = call(port, "GET", "/api/transcript?id=" + tid2)
        big = [{"id": "b%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": "これは%d行目のテスト文です。トワ様のホロライブの話をしています" % i, "speaker": "",
                "flag": "認識が不確か" if i % 50 == 7 else "", **({"proofed": True} if i % 3 == 0 else {})} for i in range(BIG)]
        call(port, "PUT", "/api/transcript?id=" + tid2, {"title": "大きい文書", "speakers": [], "segments": big})

        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 1500, "height": 1000}, permissions=[])
            pg = ctx.new_page()
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は e2e_ui_v098.py で確認)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto("http://localhost:%d/%s" % (port, QS))
            pg.wait_for_selector("#txList .txi")
            # ---- 小さい文書 ----
            items = pg.locator("#txList .txi")
            idx = [i for i in range(items.count()) if "大きい文書" not in items.nth(i).inner_text()][0]
            items.nth(idx).locator(".t").click()
            pg.wait_for_selector("#segs .seg")
            check(pg.locator("#segs .seg").count() == n, "小さい文書を開いた")
            check("未校正 %d行" % (n - 1) in pg.inner_text("#sessStat"), "未校正の残りが出る: " + pg.inner_text("#sessStat"))
            # キー操作(キー単体。入力欄の外で使う。v0.9.7 で Shift+キー から Shift 不要に変更、例外は Space だけ)
            active_body = "document.activeElement === document.body"
            navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
            pg.locator("#segs textarea").nth(0).focus()
            pg.keyboard.press("Escape")
            check(pg.evaluate(active_body) and navi() == 0, "Esc で入力欄から抜けても、選んでいる行(枠)は残る")
            pg.keyboard.press("s")
            check(navi() == 1 and pg.evaluate(active_body), "S で次の行(入力欄には入らない)")
            pg.keyboard.press("w")
            check(navi() == 0, "W で前の行")
            pg.keyboard.press("d")
            check(navi() == 1, "D で次の未校正へ(1行目は校正済みなのでとばす)")
            pg.keyboard.press("f")
            check(navi() == 4, "F で次の要確認へ(2行目 → 5行目)")
            pg.keyboard.press("f")
            check(navi() == 4 and "要確認" in pg.inner_text("#toast"), "F: これより後に要確認が無ければ移動せず、案内が出る")
            pg.keyboard.press("a")
            check(navi() == 3, "A で前の未校正へ")
            # タグ(聞き取れない・声が重なる・BGM)と話者
            pg.keyboard.press("x")
            check(pg.locator("#segs .seg").nth(3).evaluate("e => e.classList.contains('tagged')"), "X で「聞き取れない」")
            pg.keyboard.press("x")
            check(not pg.locator("#segs .seg").nth(3).evaluate("e => e.classList.contains('tagged')"), "もう一度で外れる")
            pg.keyboard.press("c")
            pg.keyboard.press("1")
            check(pg.locator("#segs .spk").nth(3).input_value() == "S1", "1 で話者を割り当て")
            # 入力欄の中では、Shift+文字は普通に入力できる(操作キーは働かない)
            pg.keyboard.press("t")
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "T で行の文字を直す(入力欄へ)")
            before = pg.locator("#segs textarea").nth(3).input_value()
            pg.keyboard.press("Shift+S")
            check(pg.locator("#segs textarea").nth(3).input_value() == before + "S" and navi() == 3, "入力中の Shift+S は、大文字の S が入るだけ")
            pg.keyboard.press("Backspace")
            pg.keyboard.press("Escape")
            # Shift+Space だけは例外(Space 単体は再生・停止のため): 校正済みにして次へ(自動再生あり)
            pg.keyboard.press("w")
            pg.keyboard.press("b")
            check(pg.is_checked("#autoNext"), "B で「移動したら自動で再生」")
            pg.keyboard.press("Shift+Space")
            check(navi() == 3 and pg.locator("#segs .seg").nth(2).evaluate("e => e.classList.contains('proofed')"), "Shift+Space で校正済みにして次の行へ")
            pg.wait_for_function("document.querySelector('#player').currentTime >= %s - 0.05" % d["segments"][3]["start"], timeout=5000)
            check(True, "次の行が自動で再生される")
            pg.keyboard.press("Shift+Space")
            pg.keyboard.press("b")
            check(not pg.is_checked("#autoNext"), "B でオフ")
            # 自動再生
            pg.click("#playSet summary"); pg.check("#autoNext"); pg.click("#playSet summary")   # v0.9.8: 「⚙設定」の中に移した
            pg.locator("#segs textarea").nth(1).focus()
            pg.keyboard.press("Alt+Enter")
            pg.wait_for_function("document.querySelector('#player').currentTime >= %s - 0.05" % d["segments"][2]["start"], timeout=5000)
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[2]"), "Alt+Enter で次の行へ移動し、自動再生の位置に飛ぶ")
            check(pg.locator("#segs .seg.proofed").count() == 4, "Alt+Enter でも校正済みになる(入力中)")
            check("今回 +3行" in pg.inner_text("#sessStat"), "今回の校正数が増える: " + pg.inner_text("#sessStat"))
            pg.click("#playSet summary"); pg.uncheck("#autoNext"); pg.click("#playSet summary")
            # 再生速度・±3秒
            pg.keyboard.press("Escape")
            pg.select_option("#rate", "1.5")
            check(pg.evaluate("document.querySelector('#player').playbackRate") == 1.5, "再生速度が変わる")
            pg.select_option("#rate", "1")
            pg.evaluate("document.querySelector('#player').currentTime = 10")
            pg.click("#seekFwd")
            check(abs(pg.evaluate("document.querySelector('#player').currentTime") - 13) < 0.3, "+3秒")
            # 用語の挿入
            check(pg.locator("#terms .chip").count() == 2, "用語のボタンが出る(用語集の2語)")
            ta = pg.locator("#segs textarea").nth(3)
            ta.fill("これは")
            ta.focus()
            pg.keyboard.press("End")
            pg.click("#terms .chip[data-t=トワ]")
            check(ta.input_value() == "これはトワ", "用語をカーソル位置に挿入: " + ta.input_value())
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[3]"), "挿入後も入力欄にフォーカスが残る")
            # 進み具合の帯
            box = pg.locator("#strip").bounding_box()
            pg.mouse.click(box["x"] + box["width"] * 0.9, box["y"] + 5)
            check(pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))") == n - 1, "帯をクリックすると、その位置の行へ移動")
            has_ink = pg.evaluate("""() => { const c = document.querySelector('#strip'), x = c.getContext('2d'); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; }""")
            check(has_ink > 100, "帯に色が描かれている")
            # 表示設定
            pg.click("#viewMenu summary")
            pg.select_option("#vFs", "20")
            check(pg.evaluate("getComputedStyle(document.querySelector('#segs textarea')).fontSize") == "20px", "文字の大きさ: 特大")
            pg.select_option("#vTheme", "dark")
            check(pg.evaluate("document.documentElement.dataset.theme") == "dark", "画面の色: 暗い")
            pg.check("#vDense")
            check(pg.evaluate("document.documentElement.classList.contains('dense')"), "行の間隔を詰める")
            pg.select_option("#vVid", "a")
            check(pg.evaluate("document.querySelector('#player').getBoundingClientRect().height") < 70, "音声だけ聞く: 映像が小さくなる")
            pg.mouse.click(5, 500)
            check(not pg.evaluate("document.querySelector('#viewMenu').open"), "外をクリックでメニューが閉じる")
            pg.click("#btnMenu")
            check(pg.is_hidden("#menuPanel") and pg.is_visible("#player"), "メニューを閉じる: 左のメニューだけ隠れる(映像は残る)")
            pg.keyboard.press("Escape")
            pg.keyboard.press("g")
            check(pg.is_visible("#menuPanel"), "G でメニューを開く")
            pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)   # 再読み込みの前に、保存を待つ
            pg.goto("http://localhost:%d/%s" % (port, QS))
            pg.wait_for_selector("#txList .txi")
            check(pg.is_visible("#menuPanel") and pg.evaluate("document.documentElement.dataset.theme") == "dark" and pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--fs').trim()") == "20px", "表示の設定(文字・色・メニューの開閉)が残る")
            # 続きから
            items = pg.locator("#txList .txi")
            idx = [i for i in range(items.count()) if "大きい文書" not in items.nth(i).inner_text()][0]
            items.nth(idx).locator(".t").click()
            pg.wait_for_selector("#segs .seg")
            pg.wait_for_function("document.querySelector('#toast').textContent.includes('前回の続き')", timeout=5000)
            check(True, "開き直すと「前回の続き」へ移動する")
            pg.click("#btnMenu")
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                pg.screenshot(path=os.path.join(SHOTS, "v071_focus_dark.png"))
            pg.click("#btnMenu")
            # キー一覧
            pg.click("#btnKeys")
            check(pg.is_visible("#keys") and "Shift+Space" in pg.inner_text("#keys") or "校正済みにして次へ" in pg.inner_text("#keys"), "操作キーの一覧が開く")
            pg.keyboard.press("Escape")
            check(pg.is_hidden("#keys"), "Esc で閉じる")
            # ---- 履歴と競合 ----
            pg.locator("#segs textarea").nth(4).fill("履歴用の編集")
            pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)
            sv = call(port, "GET", "/api/transcript?id=" + tid)["segments"][3]
            check(sv.get("tags") == ["overlap"] and sv.get("speaker") == "S1", "タグと話者がサーバーに保存された: %s" % ({k: sv.get(k) for k in ("tags", "speaker")},))
            # 保管(dataset/)
            pg.click("#arcNow")
            pg.wait_for_function("document.querySelector('#arcOut').textContent.includes('保管した文字起こし 1件')", timeout=30000)
            check("正解の行" in pg.inner_text("#arcOut") and "トワ" in pg.text_content("#arcOut"), "保管カードに、正解の量・話者ごとの量が出る")
            check(os.path.isfile(os.path.join(tmp, "dataset", "index.jsonl")) and os.path.getsize(os.path.join(tmp, "dataset", "index.jsonl")) > 100, "dataset/index.jsonl ができている")
            check("保管: 済" in pg.inner_text("#arcStat"), "保管の状況が出る: " + pg.inner_text("#arcStat"))
            pg.click("#btnSpk")   # v0.15.0: 「道具 ▾」→「以前の版に戻す」(自動バックアップ。旧「履歴」)
            pg.click("[data-jump=hiDetails]")
            pg.wait_for_function("document.querySelectorAll('#hiList [data-act=hirest]').length >= 1", timeout=8000)
            check(True, "以前の版(自動バックアップ)の一覧が出る(件数: %d)" % pg.locator("#hiList [data-act=hirest]").count())
            # 別の場所(API)が先に更新 → 画面側の保存は競合になる
            cur = call(port, "GET", "/api/transcript?id=" + tid)
            cur["segments"][5]["text"] = "別のタブで直した"
            call(port, "PUT", "/api/transcript?id=" + tid, {"title": cur["title"], "speakers": SPK, "segments": cur["segments"]})
            pg.locator("#segs textarea").nth(0).fill("画面で直した")
            pg.wait_for_function("!document.querySelector('#conflictBar').hidden", timeout=8000)
            check("競合" in pg.inner_text("#saveState"), "競合の案内が出て、自動保存が止まる")
            check(call(port, "GET", "/api/transcript?id=" + tid)["segments"][5]["text"] == "別のタブで直した", "サーバー側の内容は上書きされていない")
            pg.click("#cfReload")
            pg.wait_for_function("document.querySelector('#conflictBar').hidden")
            check(pg.locator("#segs textarea").nth(5).input_value() == "別のタブで直した", "読み込み直すと、先に保存された内容になる")
            pg.locator("#segs textarea").nth(0).fill("読み込み直してから直した")
            pg.wait_for_function("document.querySelector('#saveState').textContent.includes('保存しました')", timeout=8000)
            check(call(port, "GET", "/api/transcript?id=" + tid)["segments"][0]["text"] == "読み込み直してから直した", "読み込み直したあとは通常どおり保存できる")
            # 履歴から戻す
            hs = call(port, "GET", "/api/history?id=" + tid)["items"]
            pg.click("#hiRefresh")
            pg.wait_for_function("document.querySelectorAll('#hiList [data-act=hirest]').length == %d" % len(hs))
            last = pg.locator("#hiList [data-act=hirest]").last
            last.click()
            last.click()
            pg.wait_for_function("document.querySelector('#toast').textContent.includes('戻しました')", timeout=8000)
            check(len(call(port, "GET", "/api/history?id=" + tid)["items"]) == len(hs) + 1, "戻すと、戻す前の状態も履歴に残る")

            # ---- 数千行 ----
            items = pg.locator("#txList .txi")
            idx = [i for i in range(items.count()) if "大きい文書" in items.nth(i).inner_text()][0]
            t0 = time.time()
            items.nth(idx).locator(".t").click()
            pg.wait_for_function("document.querySelectorAll('#segs .seg').length === %d" % BIG, timeout=60000)
            t_open = time.time() - t0
            check(t_open < 4.0, "%d行を開くまで %.2f 秒" % (BIG, t_open))
            # 入力の引っかかり(1文字入力 → 反映までの時間)
            pg.locator("#segs textarea").nth(2000).scroll_into_view_if_needed()
            ms = pg.evaluate("""async () => {
              const ta = document.querySelectorAll('#segs textarea')[2000]; ta.focus(); const out = [];
              for (let i = 0; i < 20; i++){ const t = performance.now(); ta.value += 'あ'; ta.dispatchEvent(new Event('input', { bubbles: true })); await new Promise(r => requestAnimationFrame(() => r())); out.push(performance.now() - t); }
              out.sort((a, b) => a - b); return out[Math.floor(out.length * 0.9)]; }""")
            check(ms < 60, "%d行での入力の反応(90%%点) %.1f ms" % (BIG, ms))
            t0 = time.time()
            pg.keyboard.press("Escape")
            pg.locator("#segs textarea").nth(2000).focus()
            pg.keyboard.press("Alt+Enter")
            pg.wait_for_function("document.activeElement === document.querySelectorAll('#segs textarea')[2001]")
            t_proof = time.time() - t0
            check(t_proof < 0.5, "%d行での Alt+Enter(入力中)→ 次の行 %.3f 秒" % (BIG, t_proof))
            t0 = time.time()
            pg.select_option("#flagKind", "unproofed")
            t_f = time.time() - t0
            check(t_f < 2.0, "絞り込み(未校正)にかかる時間 %.2f 秒" % t_f)
            pg.select_option("#flagKind", "")
            t0 = time.time()
            pg.select_option("#vFs", "17") if pg.is_visible("#vFs") else pg.evaluate("document.querySelector('#vFs').value='17'; document.querySelector('#vFs').dispatchEvent(new Event('change'))")
            pg.wait_for_timeout(600)
            check(time.time() - t0 < 3.0, "文字サイズ変更の再計算 %.2f 秒" % (time.time() - t0))
            pg.keyboard.press("Escape")
            pg.keyboard.press("d")
            check(pg.evaluate("(() => { const i = [...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav')); return i > 2001; })()"), "大きい文書でも D で次の未校正へ")
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == BIG, "Z を1回押しただけでは消えない(v0.9.8: 2回押し)")
            pg.keyboard.press("z")
            check(pg.locator("#segs .seg").count() == BIG - 1, "Z をもう一度で行を削除")
            pg.keyboard.press("Control+z")
            check(pg.locator("#segs .seg").count() == BIG, "Ctrl+Z で削除を元に戻せる")
            if SHOTS:
                pg.screenshot(path=os.path.join(SHOTS, "v071_big.png"))
            b.close()
        errors = [e for e in errors if "409" not in e]   # 競合の試験で、わざと409を起こしている
        check(not errors, "画面のエラーなし " + ("" if not errors else str(errors[:3])))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
