#!/usr/bin/env python3
"""リアルタイム切り抜き(試験中。線 D)の入口の側の通しの確認。本物の YouTube には繋がない。

    py -3.10 src/home/tests/e2e_live.py

入口(launch.py)は e2e_backup_ui.py と同じ形で動かす(ツールは起動しない)。録画の部品は本物(src/pipeline/ingest/recorder.py)を
--source direct で別のプロセスとして動かし、ffmpeg の lavfi で作った HLS を手元の HTTP サーバーで配信中のように出して録る。

P3(2026-10-05)で別ページ /live/(録画の画面)をやめてスタジオの中に入れたので、この確認は**入口の API で**行う
(ホームの画面はオン/オフのスイッチと案内の1行だけを Playwright で見る)。
**スタジオの画面を通した確認(URL の欄に入れる → ② で再生・マーク → すぐ書き出す・ヘッダーの札)は、まとめ役があとで足す**。

確かめること:
  1. オフ: ホームの「詳しく」の「試験中の機能」のスイッチ(オフ)・案内の1行・録画の画面へのリンクは無い・/live/ は 404・
     api/ytt/live の status は {enabled: false}
  2. スイッチでオンにする → 設定に残る・/live/ はスタジオへ 302・hls.js(スタジオが ../live/hls.min.js で読む)・録画元につながる(置き場所・空き容量)
  3. begin(偽の yt-dlp = is_live。テストの録画元は --source direct で手元の URL しか受けないので、入口の allow_local_urls をテストだけ立てる)
     → 録画が始まる・もう一度 begin → 録画中のものを返す(existing)・配信中でない(was_live)→ live: false
  4. api/ytt/live の status に録画中の録画(題は文字のまま)
  5. スタジオの形の書き出し(録画の頭からの秒)→ 録画待ち → 取得 → 30fps → 済み(30/1・長さ・.clip.json の source.kind live・
     source.live.studio)→ 文字起こしへ(偽のまとめて実行)・一覧の studio
  6. api/ytt/live の stop → 停止・札は「終わって 10 分以内」で残る・再生リストに終わりの印
  7. オフに戻す → status は {enabled: false}・ホームの画面にコンソールのエラーなし
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
from unittest import mock

from playwright.sync_api import sync_playwright

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "pipeline", "ingest", "tests"))
import launch as L  # noqa: E402
import hls_fixture as F  # noqa: E402
from pipeline.export import live_export as LX  # noqa: E402
from ytt_core import normalize, schemas  # noqa: E402
from test_launch import free_ports  # noqa: E402


def wait_js(pg, expr, timeout=20000):
    """page.wait_for_function は CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.15)
    return False


def wait_for(fn, timeout=30.0, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class Client:
    """入口の API を画面と同じ形で呼ぶ(Host・Origin・合言葉 X-YTT-Token)"""

    def __init__(self, port, token):
        self.base, self.token = "http://127.0.0.1:%d" % port, token

    def call(self, method, path, body=None, redirect=True):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        h = {"Origin": self.base, "X-YTT-Token": self.token}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        opener = urllib.request.build_opener(*([] if redirect else [NoRedirect()]))
        try:
            r = opener.open(req, timeout=60)
            code, ctype, raw, loc = r.status, r.headers.get("Content-Type") or "", r.read(), r.headers.get("Location")
        except urllib.error.HTTPError as e:
            code, ctype, raw, loc = e.code, e.headers.get("Content-Type") or "", e.read(), e.headers.get("Location")
        obj = json.loads(raw.decode("utf-8")) if ctype.startswith("application/json") else raw
        return code, obj, ctype, loc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-live-e2e-")
    patch = mock.patch.dict(os.environ, {"YTT_RUNTIME_DIR": os.path.join(tmp, ".runtime")})
    patch.start()
    sup = L.Supervisor(tmp, ready_timeout=5, stop_timeout=5, poll=0.5, log=lambda m: None, ports=dict(zip(L.TOOL_IDS, free_ports(3))), mounts=())
    srv, port = L.make_server(0, sup)
    sup.attach(srv)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % port
    api = Client(port, srv.token)

    # 録画の部品(本物。direct)と、配信中のふりをする HLS
    src_dir = os.path.join(tmp, "src")
    segs = F.make_source(src_dir, 60)
    live_src = F.LiveServer(src_dir, segs, start=4, rate=1.0)
    live_src.end = False
    rport = free_ports(1)[0]
    rdata, rfolder = os.path.join(tmp, "recdata"), os.path.join(tmp, "live-rec")
    rproc = subprocess.Popen([sys.executable, os.path.join(REPO, "pipeline", "ingest", "recorder.py"), "--port", str(rport), "--data-dir", rdata,
                              "--folder", rfolder, "--source", "direct", "--hls-time", "1", "--quiet"],
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    tok = os.path.join(rdata, "token.txt")
    end = time.time() + 20
    while time.time() < end and not os.path.isfile(tok):
        time.sleep(0.2)
    time.sleep(0.2)
    with open(tok, encoding="ascii") as f:
        rtoken = f.read().strip()
    # 録画元の一覧(この部品だけ。オンにするのは画面のスイッチで)
    srv.prefs.patch("live", {"recorders": [{"id": "local", "name": "この PC", "url": "http://127.0.0.1:%d" % rport, "token": rtoken}]})
    # 書き出し: 記録・書き出し先は一時フォルダ・文字起こしへは偽のまとめて実行
    out_dir = os.path.join(tmp, "out")
    srv.live.store_dir = os.path.join(tmp, "live")
    srv.live.out_dir = lambda: out_dir
    srv.live.audio = lambda: {"volume": 100, "loudness": None}
    handed = []

    class FakeRunner:
        def start_file(self, path, title="", flow="check", **kw):
            handed.append((path, flow))
            return {"id": "run-%d" % len(handed)}

        def snapshot(self):
            return {"runs": [{"id": "run-%d" % (i + 1), "state": "queued", "stateLabel": "待ち"} for i in range(len(handed))]}
    fake_runner = FakeRunner()
    srv.live.runner = lambda: fake_runner
    # 配信の状態は偽の yt-dlp(本物の YouTube へは繋がない)。テストの録画元は手元の URL だけを受けるので、begin でも手元の URL を通す
    probe = {"status": "is_live", "title": "テストの配信<b>", "message": ""}
    srv.live.probe = lambda url: dict(probe)
    srv.live.allow_local_urls = True

    errors = []
    rid = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                pg = browser.new_context(viewport={"width": 1280, "height": 1000}).new_page()
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "404" not in m.text else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))

                # 1. オフ
                pg.goto(base + "settings")   # 0.54.0: リアルタイム切り抜きの欄はホームの ⚙ から設定の画面へ(docs/spec/settings.md の 6)
                check(wait_js(pg, "!!document.querySelector('#sec-live [data-ui-set-key]')"), "設定の画面に「リアルタイム切り抜き」の節が出る")
                check(pg.evaluate("document.getElementById('uiSet-live_enabled').checked") is False, "既定はオフ")
                check(pg.evaluate("document.getElementById('liveLink')") is None, "録画の画面へのリンクは無い(スタジオに統合した)")
                check("スタジオの URL の欄に配信中の URL を入れるだけで録画します" in (pg.text_content("[data-ui-set-key='live.enabled'] .ui-set-hint") or ""),
                      "案内の1行: %s" % pg.text_content("[data-ui-set-key='live.enabled'] .ui-set-hint"))
                check(api.call("GET", "/live/")[0] == 404, "オフの間は /live/ が 404")
                check(api.call("POST", "/api/ytt/live", {"op": "status"})[1] == {"enabled": False}, "オフの間は札の status が {enabled: false}")

                # 2. スイッチでオンにする
                pg.click("#uiSet-live_enabled")
                check(wait_js(pg, "(document.querySelector('[data-ui-set-key=\"live.enabled\"] .ui-set-mark')||{}).textContent === '保存しました'"), "設定の画面で「保存しました」")
                check(srv.prefs.get(["live"])["live"]["enabled"] is True, "設定に残る")
                code, _, _, loc = api.call("GET", "/live/", redirect=False)
                check((code, loc) == (302, "/studio/"), "/live/ はスタジオへ 302: %s %s" % (code, loc))
                code, raw, ctype, _ = api.call("GET", "/live/hls.min.js")
                check(code == 200 and ctype.startswith("application/javascript") and len(raw) > 100000, "hls.js(../live/hls.min.js)")
                code, info, _, _ = api.call("GET", "/live/api/info")
                check(code == 200 and [r["id"] for r in info["recorders"]] == ["local"] and rtoken not in json.dumps(info), "録画元の一覧(合言葉は出さない)")
                code, lst, _, _ = api.call("GET", "/live/r/local/list")
                check(code == 200 and lst.get("folderOk") is True and os.path.normcase(lst["folder"]) == os.path.normcase(rfolder),
                      "録画元につながる・置き場所: %s" % (lst if code != 200 else lst["folder"]))
                check(code == 200 and (lst.get("freeBytes") or 0) > 0, "空き容量")

                # 3. begin → 録画が始まる
                code, d, _, _ = api.call("POST", "/live/api/begin", {"url": live_src.url})
                check(code == 200 and d.get("live") is True and d.get("existing") is False and d.get("recorder") == "local",
                      "begin(配信中)→ 録画が始まる: %s" % d)
                rid = (d.get("recording") or {}).get("id")
                check(bool(rid) and LX.REC_RE.match(rid) and d["recording"]["title"] == "テストの配信<b>", "録画の id と題(yt-dlp の題): %s" % d.get("recording"))
                code, d2, _, _ = api.call("POST", "/live/api/begin", {"url": live_src.url})
                check(code == 200 and d2.get("existing") is True and (d2.get("recording") or {}).get("id") == rid, "もう一度 begin → 録画中のものを返す: %s" % d2)
                probe["status"] = "was_live"
                check(api.call("POST", "/live/api/begin", {"url": live_src.url})[1] == {"live": False, "status": "was_live"}, "配信中でない → live: false")
                probe["status"] = "is_live"
                status = lambda: api.call("GET", "/live/r/local/%s/status?since=999999999" % rid)[1]   # noqa: E731
                check(wait_for(lambda: (status() or {}).get("segments", 0) >= 5, 40), "録画が進む: %s" % status())
                code, pl, ctype, _ = api.call("GET", "/live/r/local/%s/index.m3u8" % rid)
                check(code == 200 and ctype == "application/vnd.apple.mpegurl" and b"#EXT-X-ENDLIST" not in pl, "再生リスト(中継)")

                # 4. ヘッダーの札
                code, st, _, _ = api.call("POST", "/api/ytt/live", {"op": "status"})
                row = next((r for r in (st or {}).get("recordings") or [] if r["id"] == rid), None)
                check(code == 200 and st.get("enabled") is True and row and row["active"] is True and row["recorder"] == "local"
                      and row["title"] == "テストの配信<b>" and row["url"] == live_src.url, "札の status に録画中の録画: %s" % st)

                # 5. スタジオの形の書き出し(録画の頭からの秒)
                first = LX.iso_epoch(status()["firstPdt"])
                studio = {"video": rid, "mark": "m0123abcd", "n": 1, "label": "見どころ", "start": 0.5, "end": 3.5}
                code, d, _, _ = api.call("POST", "/live/api/export", {"recorder": "local", "recording": rid, "title": "テストの配信<b>", "url": live_src.url,
                                                                       "transcribe": True, "studio": studio})
                check(code == 200 and d["job"]["studio"] == {"video": rid, "mark": "m0123abcd", "start": 0.5, "end": 3.5}, "書き出しを頼む: %s" % d)
                jid = d["job"]["id"]
                check(d["job"]["start"] == LX.epoch_iso(first + 0.5) and d["job"]["markId"] == LX.studio_mark_id("m0123abcd"), "絶対時刻 = firstPdt + 秒・正本の id")
                code, d, _, _ = api.call("POST", "/live/api/export", {"recorder": "local", "recording": rid, "studio": studio})
                check(code == 409 or d.get("job", {}).get("id") != jid, "同じマークが途中なら 409: %s" % code)
                job = lambda: next((j for j in api.call("GET", "/live/api/exports?recorder=local&recording=%s" % rid)[1]["jobs"] if j["id"] == jid), {})   # noqa: E731
                got = wait_for(lambda: job().get("state") in ("done", "error") and job(), 90)
                check(got and got["state"] == "done", "録画待ち → 取得 → 30fps → 済み: %s" % got)
                if got and got["state"] == "done":
                    info = normalize.probe(got["path"])
                    check(normalize.is_30fps(info), "書き出した動画は 30/1: %s" % (info or {}).get("r_frame_rate"))
                    check(abs((info or {}).get("duration", 0) - 3.0) <= 0.15, "長さが区間と同じ: %s" % (info or {}).get("duration"))
                    clip, warn = schemas.load_clip_file(schemas.find_clip_path(got["path"]))
                    check(clip and clip["source"]["kind"] == "live", ".clip.json の source.kind は live: %s" % warn)
                    check(clip and clip["source"]["live"].get("studio") == {"video": rid, "mark": "m0123abcd"}, ".clip.json にスタジオの配信とマーク")
                    check(clip and abs(clip["range"]["start"] - 0.5) < 0.01, ".clip.json の range は録画の頭からの秒: %s" % (clip or {}).get("range"))
                    check(os.path.dirname(os.path.dirname(got["path"])) == out_dir, "スタジオの書き出し先の配信の名前のフォルダ: %s" % got["path"])
                    check(handed == [(got["path"], "check")], "文字起こしへ渡した(まとめて実行の文字起こしだけ): %s" % handed)
                    check(got["studio"]["mark"] == "m0123abcd", "一覧のジョブに studio")

                # 6. 札の「停止」
                code, d, _, _ = api.call("POST", "/api/ytt/live", {"op": "stop", "recorder": "local", "recording": rid})
                check(code == 200 and d.get("ok") is True and d["recording"]["state"] == "stopped", "札の stop で止まる: %s" % d)
                code, st, _, _ = api.call("POST", "/api/ytt/live", {"op": "status"})
                row = next((r for r in (st or {}).get("recordings") or [] if r["id"] == rid), None)
                check(row and row["active"] is False and row["state"] == "stopped" and row["endedAt"], "止めた録画は終わって 10 分は札に残る: %s" % row)
                check(b"#EXT-X-ENDLIST" in api.call("GET", "/live/r/local/%s/index.m3u8" % rid)[1], "再生リストに終わりの印")

                # 7. オフに戻す
                pg.goto(base + "settings")
                check(wait_js(pg, "!!document.getElementById('uiSet-live_enabled') && document.getElementById('uiSet-live_enabled').checked"), "設定の画面はオン")
                pg.click("#uiSet-live_enabled")
                check(wait_js(pg, "(document.querySelector('[data-ui-set-key=\"live.enabled\"] .ui-set-mark')||{}).textContent === '保存しました'") and srv.prefs.get(["live"])["live"]["enabled"] is False, "オフに戻す")
                check(api.call("POST", "/api/ytt/live", {"op": "status"})[1] == {"enabled": False}, "オフなら札の status は {enabled: false}")
                check(not errors, "ホームの画面にコンソールのエラーなし: %s" % errors[:5])
            finally:
                browser.close()
    finally:
        try:
            if rid:
                req = urllib.request.Request("http://127.0.0.1:%d/live/%s/stop" % (rport, rid), data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + rtoken})
                urllib.request.urlopen(req, timeout=40)
        except Exception:
            pass
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/live/quit" % rport, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + rtoken})
            urllib.request.urlopen(req, timeout=5)
            rproc.wait(20)
        except Exception:
            rproc.kill()
        live_src.close()
        srv.live.close()
        srv.shutdown()
        srv.server_close()
        patch.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL OK" if ok else "SOME FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
