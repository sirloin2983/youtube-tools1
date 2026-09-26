#!/usr/bin/env python3
"""まとめて実行(app/autorun.py)の通し確認。本物の3ツールを疑似モードで一時フォルダに写し、入口に取り込んだ形で動かす(空きポートだけを使う)。

    python app/e2e_autorun.py [--shots <フォルダ>]

① 案件の画面(/cases.html)で「採用後を全部」を押す → 書き出し → 文字起こし → Resolve パック(Text+)が順に進み、
   案件の画面に文字起こし・パックが出る。もう一度押すと、何も作り直さない(すべて「飛ばした」)
② API で「解析から全部」(未解析のファイルの動画 → 解析 → 自動マークの上位1件を採用 → … → パック)
③ 画面のエラー(CSP 違反を含む)が無い
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from unittest import mock

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launch as L  # noqa: E402
import mount as M  # noqa: E402
from test_launch import REPO, _copy_tool, free_ports  # noqa: E402


def make_media(path, sec=40, bursts=False):
    """合成動画。bursts=True なら、静かな音の中に大きな音の山を何度か入れる(解析で自動マークの候補ができるように)"""
    ff = shutil.which("ffmpeg")
    audio = ("aevalsrc='0.02*sin(2*PI*330*t)*(1+30*between(mod(t\\,60)\\,20\\,26))':s=44100:d=%d" % sec) if bursts else "sine=frequency=330:duration=%d" % sec
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=%d" % sec,
                    "-f", "lavfi", "-i", audio, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", path], check=True, stdin=subprocess.DEVNULL)


def wait_js(pg, expr, timeout=30000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.2)
    return False


def main():
    shots = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
    ok = True
    events = []

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-autorun-e2e-")
    env = {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime"), "STUDIO_FAKE": "1", "TRANSCRIBE_BACKEND": "fake",
           "STUDIO_HOME": os.path.join(tmp, "studio-home")}
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    try:
        for s in L.TOOLS:
            _copy_tool(os.path.join(REPO, s["dir"]), os.path.join(tmp, s["dir"]))
        shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
        media_a = os.path.join(tmp, "media", "配信A.mp4")
        media_b = os.path.join(tmp, "media", "配信B.mp4")
        os.makedirs(os.path.dirname(media_a))
        make_media(media_a)
        make_media(media_b, sec=240, bursts=True)

        sup = L.Supervisor(tmp, ready_timeout=60, stop_timeout=10, poll=0.2, log=events.append, ports=dict(zip(L.TOOL_IDS, free_ports(3))),
                           mounts=tuple(M.MOUNTS))
        srv, port = L.make_server(0, sup)
        sup.attach(srv)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        base = "http://127.0.0.1:%d" % port

        def call(method, path, body=None):
            h = {"Content-Type": "application/json", "X-YTT-Token": srv.token, "Origin": base}
            req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(), headers=h)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read() or b"null")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"null")

        def wait_run(run_id, timeout=240):
            end = time.time() + timeout
            while time.time() < end:
                runs = call("GET", "/api/autorun")[1]["runs"]
                r = next((x for x in runs if x["id"] == run_id), None)
                if r and r["state"] not in ("queued", "running"):
                    return r
                time.sleep(0.5)
            return r

        try:
            sup.start_all()
            check(all(sup.by_id[t].snapshot()["state"] == "running" for t in L.TOOL_IDS), "3つとも入口に取り込んで動いた")
            st, j = call("POST", "/studio/api/videos/open", {"kind": "file", "path": media_a})
            check(st == 200, "スタジオにファイルの動画を開いた: %s" % st)
            vid_a = j["video"]["id"]
            st, j = call("PUT", "/studio/api/video", {"id": vid_a, "marks": [{"id": "m1", "start": 3, "end": 9, "label": "見どころ", "status": "adopted"}]})
            check(st == 200, "マークを採用にした")

            # ① 画面から「採用後を全部」
            with sync_playwright() as p:
                browser = p.chromium.launch()
                pg = browser.new_page(viewport={"width": 1200, "height": 900})
                errors = []
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(base + "/cases.html")
                card = '.pt-case[data-id="%s"]' % vid_a
                check(wait_js(pg, "!!document.querySelector('%s .pt-auto-run')" % card.replace("'", "\\'"), 15000), "案件の画面に「まとめて実行」が出た")
                pg.select_option(card + " .pt-auto-mode", "adopted")
                check(pg.is_hidden(card + " .pt-auto-topbox"), "「採用後を全部」では採用する数の欄を出さない")
                pg.click(card + " .pt-auto-run")
                done_js = ("(() => { const m = document.querySelector('%s .pt-auto-msg'); return m && /完了|止まりました/.test(m.textContent); })()"
                           % card.replace("'", "\\'"))
                check(wait_js(pg, done_js, 240000), "まとめて実行が終わった: %s" % pg.text_content(card + " .pt-auto-msg"))
                pills = pg.eval_on_selector_all(card + " .pt-auto-step .pill", "els => els.map(e => e.textContent)")
                check(pills == ["書き出し 済み", "文字起こし 済み", "Resolve パック 済み"], "書き出し → 文字起こし → パック: %s" % pills)
                check(wait_js(pg, "document.querySelectorAll('%s .pt-clip').length === 1" % card.replace("'", "\\'"), 20000), "切り抜きが案件に出た")
                clip_pills = pg.eval_on_selector_all(card + " .pt-clip .pill", "els => els.map(e => e.textContent)")
                check(any(x.startswith("文字起こし 校正") for x in clip_pills) and any("パック" in x and "まだ" not in x for x in clip_pills),
                      "案件の画面に文字起こし・パックが出る(終わったら表示を新しくする): %s" % clip_pills)
                if shots:
                    os.makedirs(shots, exist_ok=True)
                    pg.screenshot(path=os.path.join(shots, "cases-autorun.png"), full_page=True)
                # もう一度押す → 何も作り直さない
                pg.click(card + " .pt-auto-run")
                time.sleep(1.0)
                check(wait_js(pg, done_js, 60000), "2回目も終わった")
                pills = pg.eval_on_selector_all(card + " .pt-auto-step .pill", "els => els.map(e => e.textContent)")
                check(pills == ["書き出し 飛ばした", "文字起こし 飛ばした", "Resolve パック 飛ばした"], "2回目は何も作り直さない: %s" % pills)
                real = [e for e in errors if "Failed to load resource" not in e]
                check(not real, "画面のエラーなし(CSP 違反を含む): %s" % real[:3])
                browser.close()

            v = call("GET", "/studio/api/video?id=" + vid_a)[1]["video"]
            clip = next(m for m in v["marks"] if m["id"] == "m1")
            check(clip["status"] == "exported" and os.path.isfile(clip["path"]), "書き出した mp4 がある")
            pack_dir = os.path.splitext(clip["path"])[0] + "_pack"
            check(os.path.isfile(os.path.join(pack_dir, "cut-plan.json")) and os.path.isfile(os.path.join(pack_dir, "textplus-import.json")),
                  "Text+ パックができた: %s" % (os.listdir(pack_dir) if os.path.isdir(pack_dir) else "無い"))
            check(os.path.isfile(os.path.splitext(clip["path"])[0] + ".transcript.json"), "文字起こしを動画の隣に保存した(transcript/v1)")

            # ② API で「解析から全部」(未解析の動画)
            st, j = call("POST", "/studio/api/videos/open", {"kind": "file", "path": media_b})
            vid_b = j["video"]["id"]
            st, j = call("POST", "/api/autorun/start", {"id": vid_b, "mode": "full", "top": 1})
            check(st == 200 and j["run"]["mode"] == "full", "「解析から全部」を始めた")
            st2, j2 = call("POST", "/api/autorun/start", {"id": vid_b, "mode": "adopted"})
            check(st2 == 400 and "すでに" in j2.get("message", ""), "同じ配信は2つ同時に入れない: %s" % j2)
            r = wait_run(j["run"]["id"])
            states = {s["key"]: s["state"] for s in r["steps"]}
            check(r["state"] == "done" and states == {"analyze": "done", "adopt": "done", "export": "done", "transcribe": "done", "pack": "done"},
                  "解析 → 採用 → 書き出し → 文字起こし → パック: %s %s" % (states, r.get("error")))
            v = call("GET", "/studio/api/video?id=" + vid_b)[1]["video"]
            check(sum(1 for m in v["marks"] if m["status"] == "exported") == 1, "採用する数(1)だけ書き出した")
            st, j = call("POST", "/api/autorun/start", {"id": "../x", "mode": "full"})
            check(st == 400, "正しくない配信の指定は断る")
            # 合言葉なしの操作は断る
            req = urllib.request.Request(base + "/api/autorun/start", method="POST", data=b'{"id":"x","mode":"full"}',
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=10)
                code = 200
            except urllib.error.HTTPError as e:
                code = e.code
            check(code == 403, "合言葉なしの まとめて実行 は断る: %s" % code)
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
