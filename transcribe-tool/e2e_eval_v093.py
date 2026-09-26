#!/usr/bin/env python3
"""v0.9.4: 評価用(evalSet)を守る仕組みの通し確認(疑似モード)。学習・辞書・書き出し・再認識・保管・進行度・測定・基準の記録・画面。"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように


def call(port, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


def main():
    tmp = tempfile.mkdtemp()
    for n in ("serve.py", "index.html", "app.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):   # 受け渡しの API(pipeline_io)・Resolve 書き出しも使うので一緒に写す
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            shutil.copy(p, tmp)
    wav = os.path.join(tmp, "s.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12", wav], check=True)
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
        j = call(port, "POST", "/api/transcribe", {"sourcePath": wav, "model": "small", "language": "ja", "autoGloss": False})
        for _ in range(200):
            job = next(x for x in call(port, "GET", "/api/jobs")["jobs"] if x["id"] == j["id"])
            if job["state"] in ("done", "error"):
                return job["tid"]
            time.sleep(0.1)

    def fix(tid, extra=None, proofed=True):
        """全行を、末尾に『ホロ』を足した文に直して校正済みにする(学習の候補ができる)。"""
        d = call(port, "GET", "/api/transcript?id=" + tid)
        segs = [{**g, "text": g["text"].replace("テスト", "テスタ"), **({"proofed": True} if proofed else {})} for g in d["segments"]]
        call(port, "PUT", "/api/transcript?id=" + tid, {"title": d["title"], "speakers": d.get("speakers", []), "segments": segs, **(extra or {})})
        return segs

    try:
        for _ in range(100):
            try:
                call(port, "GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)
        train, ev = make(), make()
        fix(train)
        segs = fix(ev, {"evalSet": True})
        d = call(port, "GET", "/api/transcript?id=" + ev)
        check(d.get("evalSet") is True, "evalSet が保存される")
        call(port, "PUT", "/api/transcript?id=" + ev, {"title": d["title"], "speakers": [], "segments": d["segments"]})   # 古い画面(evalSet のキー無し)からの保存
        check(call(port, "GET", "/api/transcript?id=" + ev).get("evalSet") is True, "キーが無い保存では、評価用の印が外れない")
        check(any(x["id"] == ev and x["evalSet"] for x in call(port, "GET", "/api/transcripts")["items"]), "一覧に印が出る")
        # 学習からの除外
        lr = call(port, "GET", "/api/learned?min=1")
        check(lr["docs"] == 1, "修正から学習: 評価用は数えない(対象 %s 件)" % lr["docs"])
        # 評価用だけ直して、学習用は直さない場合
        train2 = make()
        fix(train2, proofed=False)
        d2 = call(port, "GET", "/api/transcript?id=" + train2)
        lr2 = call(port, "GET", "/api/learned?min=1")
        check(any(i["wrong"] == "テスト" for i in lr2["items"]) and lr2["docs"] == 2, "学習用(train・train2)の修正は学習される")
        # 評価用の修正だけでは候補が出ない
        for t_ in (train, train2):
            call(port, "DELETE", "/api/transcript?id=" + t_)
        lr3 = call(port, "GET", "/api/learned?min=1")
        check(lr3["docs"] == 0 and not lr3["items"], "評価用の修正だけでは、学習の候補が出ない: %s" % lr3)
        # 再認識・書き出しの拒否
        e1 = call(port, "POST", "/api/retranscribe", {"tid": ev, "ids": [segs[0]["id"]], "model": "small"})
        check(e1.get("status") == 400 and "評価用" in json.dumps(e1, ensure_ascii=False), "評価用は再認識できない")
        e2 = call(port, "POST", "/api/export-corrections", {"tid": ev, "audio": False, "scope": "proofed"})
        check(e2.get("status") == 400 and "評価用" in json.dumps(e2, ensure_ascii=False), "評価用は修正データとして書き出せない(個別指定)")
        tr = make(); fix(tr)
        req = urllib.request.Request("http://127.0.0.1:%d/api/export-corrections" % port, method="POST", data=json.dumps({"audio": False, "scope": "proofed"}).encode(), headers={"Content-Type": "application/json"})
        import io, zipfile
        with urllib.request.urlopen(req, timeout=60) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        rows = [json.loads(x) for x in z.read("corrections.jsonl").decode().splitlines() if x.strip()]
        check(rows and all(r_["doc"] == tr for r_ in rows), "全体の書き出しに、評価用の行は入らない(%d行)" % len(rows))
        # 進行度・測定
        pg_ = call(port, "GET", "/api/progress")
        check(pg_["evalDocs"] == 1 and pg_["evalProofedLines"] == len(segs) and pg_["proofedLines"] == len(segs) and pg_["evalDocsDone"] == 1, "進行度: 学習用と評価用を分けて数える: %s" % pg_)
        me = call(port, "GET", "/api/metrics?scope=eval")
        mt = call(port, "GET", "/api/metrics?scope=train")
        check(me["docs"] == 1 and mt["docs"] == 1 and me["byDoc"][0]["id"] == ev, "測定の対象(評価用のみ / 学習用のみ)")
        # 保管
        for t_ in (ev, tr):
            call(port, "POST", "/api/archive", {"tid": t_, "full": False})
            for _ in range(100):
                ds = call(port, "GET", "/api/dataset")
                if not ds["running"] and any(d_["tid"] == t_ for d_ in ds["docs"]):
                    break
                time.sleep(0.1)
        lines = [json.loads(x) for x in open(os.path.join(tmp, "dataset", "docs", ev, "lines.jsonl"), encoding="utf-8") if x.strip()]
        lines_t = [json.loads(x) for x in open(os.path.join(tmp, "dataset", "docs", tr, "lines.jsonl"), encoding="utf-8") if x.strip()]
        check(lines and all(x["split"] == "eval" for x in lines) and all(x["split"] == "train" for x in lines_t), "保管データの各行に split(eval/train)が付く")
        check(ds["totals"]["evalSec"] > 0 and ds["totals"]["positive"] == len([x for x in lines_t if x["role"] == "positive"]), "保管の量: 評価用は学習に使える量に入らない: %s" % ds["totals"])
        # 基準の記録
        b0 = call(port, "POST", "/api/eval-baseline", {"label": "基準"})
        check("cer" in b0 and call(port, "GET", "/api/eval-baselines")["items"][-1]["label"] == "基準", "基準を記録できる: CER %s" % b0.get("cer"))
        call(port, "PUT", "/api/transcript?id=" + ev, {"title": "x", "evalSet": False, "speakers": [], "segments": call(port, "GET", "/api/transcript?id=" + ev)["segments"]})
        e3 = call(port, "POST", "/api/eval-baseline", {"label": "x"})
        check(e3.get("status") == 400, "評価用が無いと記録を断る")
        call(port, "PUT", "/api/transcript?id=" + ev, {"title": "評価動画", "evalSet": True, "speakers": [], "segments": call(port, "GET", "/api/transcript?id=" + ev)["segments"]})
        # 画面
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_context(viewport={"width": 1400, "height": 900}).new_page()
            pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = '[data-side-pane][hidden]{display:block !important}'; document.head.appendChild(st); })")   # v0.9.9: メニューのタブで隠れるカードも操作できるように(タブ自体は e2e_ui_v098.py で確認)
            pg.on("pageerror", lambda e_: errors.append(str(e_)))
            pg.on("console", lambda m_: errors.append(m_.text) if m_.type == "error" else None)
            pg.goto("http://localhost:%d/" % port)
            pg.wait_for_selector("#txList .txi")
            check("評価用" in pg.inner_text("#txList"), "一覧に「評価用」の印")
            check("評価用(学習に使わない" in pg.inner_text("#evalStat") and "1</b>本" in pg.inner_html("#evalStat"), "進行度カードに評価用の状況: " + pg.inner_text("#evalStat"))
            pg.locator("#txList .txi").filter(has_text="評価用").locator(".t").first.click()
            pg.wait_for_selector("#segs .seg")
            check(pg.is_checked("#evalSet") and pg.is_visible("#evalBanner"), "開くと、チェックと帯が出る")
            pg.evaluate("document.querySelector('#fixDetails').open = true")   # v0.15.0: 置換は「文字をまとめて直す」のカード
            pg.fill("#repFrom", "テスタ"); pg.fill("#repTo", "テスト")
            before = pg.evaluate("[...document.querySelectorAll('#segs textarea')].map(x => x.value).join('|')")
            pg.evaluate("document.querySelector('#repGo').click()")
            after = pg.evaluate("[...document.querySelectorAll('#segs textarea')].map(x => x.value).join('|')")
            check(before == after and "使えません" in pg.inner_text("#toast"), "評価用では一括置換が止まる")
            pg.evaluate("document.querySelector('#evalSet').click()")
            check(not pg.is_visible("#evalBanner"), "チェックを外すと帯が消える")
            pg.evaluate("document.querySelector('#evalSet').click()")
            pg.wait_for_function("document.body.innerText.includes('保存しました')", timeout=15000)
            pg.evaluate("document.querySelector('#accCard').open = true")
            pg.select_option("#accScope", "eval")
            pg.fill("#blLabel", "画面から")
            pg.click("#blGo")
            pg.wait_for_function("document.querySelectorAll('#blOut tr').length >= 3", timeout=10000)
            check("画面から" in pg.inner_text("#blOut"), "基準の記録が表に出る")
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
