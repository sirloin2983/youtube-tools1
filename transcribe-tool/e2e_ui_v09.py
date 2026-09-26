#!/usr/bin/env python3
"""v0.9.4 の通し確認(Playwright + 疑似モード): フォルダ一括・スタジオのマーク読み込み・範囲の再認識・Tab の切り替え・時刻の微調整・枠の表示。"""
import json
import os
import re
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


def app_version():
    """画面の版(app.js の APP_VERSION)。版を上げるたびにテストを書き換えなくて済むように、固定の文字列ではなくここから読む"""
    with open(os.path.join(HERE, "app.js"), encoding="utf-8") as f:
        m = re.search(r"const APP_VERSION = '([^']+)'", f.read())
    assert m, "app.js に APP_VERSION が見つからない"
    return "v" + m.group(1)


def call(port, method, path, body=None, raw=False):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if raw:
            return {"status": e.code, **json.loads(e.read() or b"{}")}
        raise


def main():
    tmp = tempfile.mkdtemp()
    for n in ("serve.py", "index.html", "app.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):   # 受け渡しの API(pipeline_io)・Resolve 書き出しも使うので一緒に写す
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            shutil.copy(p, tmp)
    fd = os.path.join(tmp, "clips")
    os.makedirs(os.path.join(fd, "video1"))
    for rel in ("a.wav", "b.wav", os.path.join("video1", "c.wav")):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8", os.path.join(fd, rel)], check=True)
    open(os.path.join(fd, "memo.txt"), "w").write("x")
    studio = os.path.join(tmp, "studio")
    os.makedirs(studio)
    with open(os.path.join(studio, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"videos": [{"videoId": "vid1", "title": "テスト配信", "marks": [{"id": "m1", "start": 10, "end": 30, "label": "面白い所", "status": "exported", "file": "video1/c.wav"},
                                                                          {"id": "m2", "start": 5, "end": 4}]}]}, f)
    with open(os.path.join(studio, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"outDir": fd}, f)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, YTT_RUNTIME_DIR=os.path.join(tmp, ".runtime"), TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.01", TRANSCRIBE_STUDIO_DATA=os.path.join(studio, "data.json"),
               TRANSCRIBE_MARKER_DATA=os.path.join(tmp, "none.json"))
    proc = subprocess.Popen([sys.executable, os.path.join(tmp, "serve.py"), str(port), "--no-open"], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors, ok = [], True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    def wait_jobs():
        for _ in range(300):
            jobs = call(port, "GET", "/api/jobs")["jobs"]
            if all(j["state"] in ("done", "error", "cancelled") for j in jobs):
                return jobs
            time.sleep(0.1)

    try:
        for _ in range(100):
            try:
                call(port, "GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)
        # ---- フォルダ一括 ----
        r = call(port, "POST", "/api/scan-folder", {"path": fd})
        check([f["name"] for f in r["files"]] == ["a.wav", "b.wav"], "フォルダ直下の動画・音声だけ(txt と下のフォルダは除く)")
        r2 = call(port, "POST", "/api/scan-folder", {"path": fd, "recursive": True})
        check(len(r2["files"]) == 3 and any(f["rel"].startswith("video1") for f in r2["files"]), "下のフォルダも探すと3本")
        check(call(port, "POST", "/api/scan-folder", {"path": os.path.join(fd, "nothing")}, raw=True).get("status") == 400, "存在しないフォルダは400")
        b = call(port, "POST", "/api/transcribe-batch", {"paths": [f["path"] for f in r2["files"]], "model": "small", "language": "ja"})
        check(len(b["added"]) == 3, "3本が別々のジョブになる")
        jobs = wait_jobs()
        check(len({j["tid"] for j in jobs if j["state"] == "done"}) == 3, "動画ごとに別の文字起こしができる")
        r3 = call(port, "POST", "/api/scan-folder", {"path": fd, "recursive": True})
        check(all(f["doneTid"] for f in r3["files"]), "文字起こし済みが印付きで返る")
        b2 = call(port, "POST", "/api/transcribe-batch", {"paths": [f["path"] for f in r3["files"]], "model": "small"})
        check(len(b2["added"]) == 0 and len(b2["skipped"]) == 3, "済みはスキップ(追加0・スキップ3)")
        b3 = call(port, "POST", "/api/transcribe-batch", {"paths": [r3["files"][0]["path"]], "skipDone": False, "model": "small"})
        check(len(b3["added"]) == 1, "スキップ解除なら、済みでも追加できる")
        wait_jobs()
        # ---- スタジオのマーク ----
        m = call(port, "GET", "/api/marker")
        v = m["videos"][0] if m["videos"] else {}
        check(m["found"] and v.get("videoId") == "vid1" and v.get("from") == "studio" and len(v.get("clips", [])) == 1, "スタジオの data.json(一覧形式・marks)を読める。不正な区間は除く")
        check(v["clips"][0]["title"] == "面白い所" and v["clips"][0]["file"] == "video1/c.wav", "label が title に、file も取れる")
        check(v["clips"][0].get("fileAbs") == os.path.realpath(os.path.join(fd, "video1", "c.wav")), "書き出し済みの mp4(相対パス)が実在すれば絶対パスが付く")
        check(m["outDir"] == fd, "スタジオの書き出し先(settings.json の outDir)を読む")
        check(bool(v["clips"][0].get("doneTid")), "書き出し済みの mp4 がすでに文字起こし済みなら、印(doneTid)が付く")
        rng = call(port, "GET", "/api/transcribed-ranges")
        check(any(os.path.normcase(os.path.realpath(os.path.join(fd, "video1", "c.wav"))) == os.path.normcase(r["path"]) and r["whole"] for r in rng["items"]), "/api/transcribed-ranges に、動画ごとの範囲が出る")
        # ---- 範囲の再認識 ----
        tid = next(j["tid"] for j in wait_jobs() if j["state"] == "done")
        d = call(port, "GET", "/api/transcript?id=" + tid)
        segs = [{"id": "x%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": "行%d" % i, "speaker": "S1" if i in (2, 3) else "", "flag": "", "proofed": True, "tags": ["bgm"]} for i in range(4)]
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": d["title"], "speakers": [{"id": "S1", "name": "話者", "color": "#2f62d6"}], "segments": segs})
        rt = call(port, "POST", "/api/retranscribe", {"tid": tid, "ids": ["x1", "x3"], "mode": "range", "model": "small"})
        wait_jobs()
        d2 = call(port, "GET", "/api/transcript?id=" + tid)
        texts = [s["text"] for s in d2["segments"]]
        check(texts[0] == "行0" and all(x.startswith("範囲再認識") for x in texts[1:]), "範囲(x1〜x3の間の行も含む)が新しい行に差し替わり、範囲外は残る: %s" % texts)
        check(d2["segments"][0].get("proofed") and not any(s.get("proofed") for s in d2["segments"][1:]), "差し替えた行は未校正、範囲外の校正済みは残る")
        check(all("tags" not in s for s in d2["segments"][1:]), "差し替えた行は音の状態のメモを引き継がない")
        check(any(s["speaker"] == "S1" for s in d2["segments"][1:]), "話者は、重なっていた元の行から引き継ぐ")
        check(min(s["start"] for s in d2["segments"][1:]) >= 2.0 - 1e-6 and max(s["end"] for s in d2["segments"]) <= 7.8 + 1e-6, "新しい行は範囲の内側に収まる")
        starts = [s["start"] for s in d2["segments"]]
        check(starts == sorted(starts) and len({s["id"] for s in d2["segments"]}) == len(d2["segments"]), "時刻順・id は重複しない")
        check(os.path.isfile(os.path.join(tmp, "transcripts", ".bak", tid + ".pre-retranscribe.json")), "実行前の状態を退避")
        far = [{"id": "y0", "start": 0, "end": 1, "text": "a"}, {"id": "y1", "start": 1000, "end": 1001, "text": "b"}]
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": "t", "speakers": [], "segments": far})
        e = call(port, "POST", "/api/retranscribe", {"tid": tid, "ids": ["y0", "y1"], "mode": "range"}, raw=True)
        check(e.get("status") == 400 and "長すぎ" in json.dumps(e, ensure_ascii=False), "15分を超える範囲は断る: %s" % e)
        # ---- 画面 ----
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": "画面用", "speakers": [{"id": "S1", "name": "話者", "color": "#2f62d6"}],
                                                        "segments": [{"id": "z%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": "行%d" % i, "speaker": "", "flag": "", **({"proofed": True} if i < 5 else {}), **({"tags": ["unclear"]} if i == 4 else {})} for i in range(6)]})
        pr = call(port, "GET", "/api/progress")
        check(pr["proofedLines"] == 4 and abs(pr["proofedSec"] - 7.2) < 0.01, "進行度: 校正済みの秒数(聞き取れない行は除く): %s" % pr)
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_context(viewport={"width": 1400, "height": 900}).new_page()
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は e2e_ui_v098.py で確認)
            pg.on("pageerror", lambda e_: errors.append(str(e_)))
            pg.on("console", lambda m_: errors.append(m_.text) if m_.type == "error" else None)
            pg.goto("http://localhost:%d/" % port)
            pg.wait_for_selector("#txList .txi")
            check(pg.inner_text("#ver") == app_version(), "版が app.js の APP_VERSION(%s)と同じ: %s" % (app_version(), pg.inner_text("#ver")))
            # フォルダ画面
            pg.click("#tabFolder")
            pg.fill("#fdPath", fd)
            pg.click("#fdScan")
            pg.wait_for_selector("#fdList label")
            check(pg.locator("#fdList label").count() == 2 and pg.locator("#fdList input:checked").count() == 0, "済みの2本は最初から選ばれない: " + pg.inner_text("#fdCount"))
            pg.uncheck("#fdSkip")
            check(pg.locator("#fdList input:checked").count() == 2, "スキップを外すと選ばれる")
            check(pg.is_visible("#fdStudio"), "スタジオの書き出し先ボタンが出る")
            pg.click("#fdStudio")
            pg.wait_for_function("document.querySelectorAll('#fdList label').length === 3")
            check(pg.input_value("#fdPath") == fd and pg.is_checked("#fdRec"), "書き出し先を入れて、下のフォルダも探す")
            pg.wait_for_function("!document.querySelector('#goalPill').hidden")
            check("校正 7秒" in pg.inner_text("#goalPill") and "5時間" in pg.inner_text("#goalPill"), "上の帯に進行度が出る: " + pg.inner_text("#goalPill"))
            check("7秒" in pg.inner_text("#goalText") and "・4行" in pg.inner_text("#goalText"), "進行度カード: " + pg.inner_text("#goalText"))
            check(pg.locator("#goalMs .ms").count() == 4, "節目が並ぶ(30分・1時間・3時間・目標)")
            pg.fill("#goalHours", "1"); pg.dispatch_event("#goalHours", "change")
            check("1時間" in pg.inner_text("#goalPill") and pg.locator("#goalMs .ms").count() == 2, "目標を1時間にすると、帯も節目も変わる(30分と目標の2つ)")
            # 折りたたみ
            check(pg.locator("aside details.card").count() >= 7, "左のカードがすべて折りたためる")
            pg.evaluate("document.querySelector('#txCard').open = false")
            pg.wait_for_timeout(200)
            pg.reload(); pg.wait_for_selector("#txList .txi", state="attached")
            check(not pg.evaluate("document.querySelector('#txCard').open") and pg.evaluate("document.querySelector('#jobsCard').open"), "折りたたみは開き直しても覚えている")
            check("件)" in pg.inner_text("#txCard > summary"), "折りたたんでも件数が見える: " + pg.inner_text("#txCard > summary"))
            pg.evaluate("document.querySelector('#txCard').open = true")
            # スタジオのマークの取得元
            pg.click("#tabMarker")
            pg.wait_for_selector("#mSources .src")
            srcs = pg.inner_text("#mSources")
            check("スタジオ" in srcs and "data.json" in srcs and "書き出し先" in srcs, "取得元(スタジオ・data.json のパス・書き出し先)が出る")
            check("[スタジオ]" in pg.inner_text("#mVideo"), "動画の選択肢に取得元が付く")
            check("mp4あり" in pg.inner_text("#mClips") and "書き出し済み" in pg.inner_text("#mClips"), "マークの行に状態と mp4あり が出る: " + pg.inner_text("#mClips"))
            check("文字起こし済み" in pg.inner_text("#mClips"), "マークの行に「文字起こし済み」の印: " + pg.inner_text("#mClips"))
            check(pg.is_checked("#mSkip") and not pg.locator("#mClips input[type=checkbox]").first.is_checked(), "済みのポイントは、既定でチェックが外れる")
            pg.uncheck("#mSkip")
            check(pg.locator("#mClips input[type=checkbox]").first.is_checked(), "スキップをオフにすると、済みのポイントも選ばれる")
            pg.check("#mSkip")
            if os.environ.get("SHOT2"): pg.evaluate("window.scrollTo(0,0)"); pg.screenshot(path=os.environ["SHOT2"])
            pg.click("#tabFolder")
            # 文書を開く
            pg.locator("#txList .txi").filter(has_text="画面用").locator(".t").click()
            pg.wait_for_selector("#segs .seg")
            navi = lambda: pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('nav'))")
            # Tab の切り替え
            pg.locator("#segs textarea").nth(1).focus()
            pg.keyboard.press("Tab")
            check(pg.evaluate("document.activeElement === document.body") and navi() == 1, "入力中に Tab で入力欄を抜ける(選んだ行は残る)")
            pg.keyboard.press("s")
            check(navi() == 2, "抜けたあとは S が使える")
            pg.keyboard.press("Tab")
            check(pg.evaluate("document.activeElement === document.querySelectorAll('#segs textarea')[2]"), "入力欄の外で Tab → 選んだ行の入力欄に入る")
            pg.keyboard.press("Tab")
            check(pg.evaluate("document.activeElement === document.body"), "もう一度 Tab で抜ける(切り替え式)")
            pg.keyboard.press("Shift+Tab")
            check(pg.evaluate("document.activeElement !== document.querySelectorAll('#segs textarea')[2]"), "Shift+Tab は、ふつうの動き(入力欄には入らない)")
            # 枠
            css = pg.evaluate("""() => { const r = document.querySelectorAll('#segs .seg')[4]; r.classList.add('cur'); const a = getComputedStyle(r).outlineStyle; r.classList.remove('cur');
                const n = document.querySelectorAll('#segs .seg')[navi_i]; return [a, getComputedStyle(n).outlineStyle, getComputedStyle(n).outlineWidth]; }""".replace("navi_i", str(navi())))
            check(css[0] == "none" and css[1] == "solid" and css[2] == "3px", "再生中の行は太枠にならず、選んだ行だけが太枠: %s" % css)
            check(not pg.is_checked("#frameFollow"), "太枠を再生に合わせるのは、標準でオフ")
            # 時刻の微調整
            pg.keyboard.press("s")
            row = pg.locator("#segs .seg").nth(navi())
            row.locator("input[data-f=start]").scroll_into_view_if_needed()
            before = row.locator("input[data-f=end]").input_value()
            check(row.locator(".adj").is_visible(), "選んだ行に、微調整のボタンが出る")
            row.locator("[data-act=adj][data-f=end][data-d='1']").click()
            after = pg.locator("#segs .seg").nth(navi()).locator("input[data-f=end]").input_value()
            st = pg.evaluate("document.querySelectorAll('#segs .seg')[%d].querySelector('input[data-f=start]').value" % navi())
            check(after != before, "終了の＋で終了時刻が動く: %s → %s" % (before, after))
            pg.click("#playSet summary"); pg.select_option("#adjStep", "0.5"); pg.click("#playSet summary")   # v0.9.8: 「⚙設定」の中
            pg.locator("#segs .seg").nth(navi()).locator("[data-act=adj][data-f=start][data-d='-1']").click()
            check(pg.evaluate("document.querySelectorAll('#segs .seg')[%d].querySelector('input[data-f=start]').value" % navi()) != st, "幅を変えて、開始の−で開始が動く")
            pg.keyboard.press("Control+z")
            check(pg.evaluate("document.querySelectorAll('#segs .seg')[%d].querySelector('input[data-f=start]').value" % navi()) == st, "Ctrl+Z で元に戻る")
            pg.locator("#segs .seg").nth(navi()).locator("[data-act=adj][data-f=start][data-d='1']").click()
            for _ in range(20):
                pg.locator("#segs .seg").nth(navi()).locator("[data-act=adj][data-f=start][data-d='1']").click()
            vals = pg.evaluate("(() => { const t = document.querySelectorAll('#segs .seg')[%d].querySelectorAll('input.t'); return [t[0].value, t[1].value] })()" % navi())
            tsec = lambda x: sum(float(p_) * m_ for p_, m_ in zip(reversed(x.split(":")), (1, 60, 3600)))
            check(tsec(vals[0]) < tsec(vals[1]), "開始は終了を超えない(通り越さない): %s" % vals)
            # 太枠は、標準では再生に合わせて動かない / オンなら動く
            n0 = navi()
            pg.evaluate("const p = document.querySelector('video'); Object.defineProperty(p, 'currentTime', { value: 0.5, configurable: true, writable: true }); p.dispatchEvent(new Event('timeupdate'))")
            pg.evaluate("Object.defineProperty(document.querySelector('video'), 'currentTime', { value: 8.5, configurable: true, writable: true }); document.querySelector('video').dispatchEvent(new Event('timeupdate'))")
            cur = pg.evaluate("[...document.querySelectorAll('#segs .seg')].findIndex(r => r.classList.contains('cur'))")
            check(cur == 4 and navi() == n0, "再生が進んでも、太枠(選んだ行)は動かない(再生中の行: %d)" % cur)
            pg.evaluate("document.querySelector('#frameFollow').click()")
            pg.evaluate("Object.defineProperty(document.querySelector('video'), 'currentTime', { value: 2.5, configurable: true, writable: true }); document.querySelector('video').dispatchEvent(new Event('timeupdate'))")
            check(navi() == 1, "「太枠も再生に合わせる」をオンにすると動く")
            pg.evaluate("document.querySelector('#frameFollow').click()")
            # 範囲の再認識(画面)
            pg.evaluate("document.querySelector('#fixDetails').open = true; const s = document.querySelector('#rtTarget'); s.value = 'range'; s.dispatchEvent(new Event('change'))")
            pg.wait_for_timeout(800)
            pg.evaluate("document.querySelectorAll('#segs .seg .sel')[1].click()")
            pg.evaluate("document.querySelectorAll('#segs .seg .sel')[3].click()")
            check("範囲:" in pg.inner_text("#rtHint") and "3行" in pg.inner_text("#rtHint"), "範囲の説明が出る: " + pg.inner_text("#rtHint"))
            if os.environ.get("SHOT"):
                pg.evaluate("window.scrollTo(0,0)"); pg.evaluate("document.querySelectorAll('#segs .seg')[4].classList.add('cur')"); pg.screenshot(path=os.environ["SHOT"])
            br.close()
        check(not errors, "画面のエラーなし " + ("" if not errors else str(errors[:3])))
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
