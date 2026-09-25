#!/usr/bin/env python3
"""3つのツールをつないだ通し確認(疑似モード・一時フォルダ・空きポート)。

    python tools/e2e_pipeline.py

① スタジオで切り抜きを書き出す(.clip.json ができる)→ ② 文字起こしツールで開く(clip を読む)→ 動画の隣に transcript/v1 を保存
→ ③ cut2resolve で読み込み・試算・パック作成。あわせて /api/siblings が3つを見つけること、他のツールの画面へのリンクで 403 にならないことを確かめる。
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
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("YTT_CORE_DIR", ROOT)   # 一時フォルダに写した文字起こしの serve.py が共通部品 ytt_core を見つけられるように


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, method, path, body=None, headers=None):
    h = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:%d" % port}
    h.update(headers or {})
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method,
                                 data=None if body is None else json.dumps(body).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def wait_ping(port):
    for _ in range(150):
        try:
            if call(port, "GET", "/api/ping")[0] == 200:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    raise SystemExit("起動しません: %d" % port)


def main():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    tmp = tempfile.mkdtemp(prefix="ytt-pipe-")
    rt = os.path.join(tmp, "runtime")
    procs = []
    try:
        # 元の配信の代わりの動画(40秒。10〜12秒と 20〜22 秒は無音)
        src = os.path.join(tmp, "stream.mp4")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=40",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-af", "volume='if(between(t,10,12)+between(t,20,22),0,1)':eval=frame",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src], check=True)
        # ---- ① スタジオ(データは一時フォルダ)
        studio_home = os.path.join(tmp, "studio")
        os.makedirs(studio_home)
        ps, pt, pc = free_port(), free_port(), free_port()
        env = dict(os.environ, YTT_RUNTIME_DIR=rt, STUDIO_HOME=studio_home, STUDIO_FAKE="1", TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.01")
        prep = ("import sys,json; sys.path.insert(0, %r); import serve; st,_=serve.init(%r); "
                "st.ensure({'kind':'file','videoId':'fqa00000001','name':'stream.mp4','path':%r}, '配信 <テスト>'); "
                "st.put_video('fqa00000001','配信 <テスト>',[{'id':'m1','start':5,'end':25,'label':'見どころ','status':'adopted'}])") % (
            os.path.join(ROOT, "clip-studio"), studio_home, src)
        subprocess.run([sys.executable, "-c", prep], env=env, check=True, cwd=os.path.join(ROOT, "clip-studio"))
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "clip-studio", "serve.py"), str(ps), "--no-open"], env=env,
                                      cwd=os.path.join(ROOT, "clip-studio"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        # ---- ② 文字起こし(一時フォルダに写して動かす: transcripts/ などを本物と混ぜない)
        tt = os.path.join(tmp, "transcribe-tool")
        os.makedirs(tt)
        for n in ("serve.py", "index.html", "app.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):
            shutil.copy(os.path.join(ROOT, "transcribe-tool", n), tt)
        for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
            p = os.path.join(ROOT, "transcribe-tool", n)
            if os.path.exists(p):
                shutil.copy(p, tt)
        procs.append(subprocess.Popen([sys.executable, os.path.join(tt, "serve.py"), str(pt), "--no-open"], env=env, cwd=tt,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        # ---- ③ cut2resolve
        procs.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "cut2resolve", "serve.py"), str(pc), "--no-open"], env=env,
                                      cwd=os.path.join(ROOT, "cut2resolve"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for p in (ps, pt, pc):
            wait_ping(p)
        time.sleep(0.5)

        # /api/siblings
        for name, port in (("studio", ps), ("transcribe", pt), ("cut2resolve", pc)):
            st, j = call(port, "GET", "/api/siblings")
            tools = (j or {}).get("tools", {})
            check(st == 200 and tools.get("studio") == ps and tools.get("transcribe") == pt and tools.get("cut2resolve") == pc,
                  "%s の /api/siblings が3つのツールの実際のポートを返す: %s" % (name, tools))

        # 他のツールの画面へのリンク(ブラウザの遷移と同じヘッダー)で 403 にならない。API は拒否
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        for name, port in (("studio", ps), ("transcribe", pt), ("cut2resolve", pc)):
            req = urllib.request.Request("http://localhost:%d/?media=x" % port, headers=nav)
            try:
                code = urllib.request.urlopen(req, timeout=10).status
            except urllib.error.HTTPError as e:
                code = e.code
            check(code == 200, "%s の画面を他のツールのリンクで開ける(%s)" % (name, code))
            check(call(port, "GET", "/api/siblings", headers={"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"})[0] == 403,
                  "%s の API は他のツールの画面からは使えない" % name)

        # ① 書き出し → .clip.json
        st, job = call(ps, "POST", "/api/export", {"id": "fqa00000001", "markIds": ["m1"], "precision": "accurate"})
        check(st == 200, "スタジオで書き出しを始める: %s" % st)
        item = None
        for _ in range(600):
            st, job = call(ps, "GET", "/api/export?id=" + urllib.parse.quote(job["id"]))
            if job.get("state") in ("done", "error", "cancelled"):
                break
            time.sleep(0.2)
        items = job.get("items") or job.get("files") or []
        item = next((x for x in items if x.get("status") == "done"), None)
        check(job.get("state") == "done" and item and os.path.exists(item.get("path", "")), "書き出しが終わり mp4 がある: %s" % job.get("state"))
        clip_mp4 = item["path"]
        manifest = item.get("manifest")
        check(manifest and os.path.exists(manifest), "隣に .clip.json ができる")
        clip = json.load(open(manifest, encoding="utf-8"))
        check(clip.get("schema") == "youtube-tools-clip/v1" and abs(clip["range"]["start"] - 5) < 0.05 and abs(clip["range"]["end"] - 25) < 0.05,
              "clip/v1 の range が元の配信の秒(5〜25): %s" % clip.get("range"))

        # ② 文字起こしツールが clip を読む → 文字起こし → 動画の隣に transcript/v1
        st, info = call(pt, "GET", "/api/clip-info?path=" + urllib.parse.quote(clip_mp4))
        check(st == 200 and (info.get("clip") or {}).get("source", {}).get("title") == "配信 <テスト>", "文字起こしツールが .clip.json を読む")
        st, j = call(pt, "POST", "/api/transcribe", {"sourcePath": clip_mp4, "model": "small", "language": "ja"})
        check(st == 200, "文字起こしを始める")
        for _ in range(300):
            jobs = call(pt, "GET", "/api/jobs")[1]["jobs"]
            tj = next(x for x in jobs if x["id"] == j["id"])
            if tj["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        tid = tj.get("tid")
        st, doc = call(pt, "GET", "/api/transcript?id=" + tid)
        check(st == 200 and doc.get("clip", {}).get("schema") == "youtube-tools-clip/v1" if isinstance(doc.get("clip"), dict) else False,
              "文字起こしの文書に clip が入る")
        segs = [{"id": "a", "start": 0.5, "end": 4.0, "text": "残す1"}, {"id": "b", "start": 4.0, "end": 9.0, "text": "カットする", "cutState": "cut"},
                {"id": "c", "start": 12.5, "end": 18.0, "text": "残す2"}]
        st, put = call(pt, "PUT", "/api/transcript?id=" + tid, {"title": "通し", "speakers": [], "segments": segs})
        check(st == 200, "行を編集して保存(カット済を含む)")
        st, doc = call(pt, "GET", "/api/transcript?id=" + tid)
        st, saved = call(pt, "POST", "/api/export-file", {"id": tid, "format": "transcript-v1", "baseUpdatedAt": doc.get("updatedAt")})
        tr_path = (saved or {}).get("path", "")
        check(st == 200 and tr_path.endswith(".transcript.json") and os.path.dirname(tr_path) == os.path.dirname(clip_mp4),
              "動画の隣に .transcript.json を保存: %s %s" % (st, saved))
        tr = json.load(open(tr_path, encoding="utf-8"))
        check(tr.get("schema") == "youtube-tools-transcript/v1" and [s["cut"] for s in tr["segments"]] == [False, True, False]
              and tr.get("clip", {}).get("range", {}).get("start") == clip["range"]["start"], "transcript/v1 の中身(cut・clip)")

        # ③ cut2resolve: 文字起こしの残す行で試算 → パック
        st, ins = call(pc, "POST", "/api/inspect", {"video": clip_mp4, "transcript": tr_path})
        check(st == 200, "cut2resolve が動画と文字起こしを読み込む: %s" % st)
        spec = {"video": clip_mp4, "transcript": tr_path, "mode": "keep", "keepSource": "transcript", "handles": 0}
        st, pj = call(pc, "POST", "/api/plan", {"spec": spec})
        res = None
        if st == 200:
            for _ in range(300):
                st2, pj2 = call(pc, "GET", "/api/job?id=" + urllib.parse.quote(pj["job"]["id"]))
                if pj2.get("state") in ("done", "error", "cancelled"):
                    res = pj2
                    break
                time.sleep(0.1)
        check(res and res.get("state") == "done", "試算が終わる: %s" % ((res or {}).get("error") or (res or {}).get("state") or pj))
        if res and res.get("state") == "done":
            r = res.get("result") or {}
            fps = r.get("fpsValue") or 30
            keeps = [[round(a / fps, 2), round(b / fps, 2)] for a, b in r.get("keeps", [])]
            check(len(keeps) == 2 and keeps[0][0] >= 0.4 and keeps[0][1] <= 4.1 and keeps[1][0] >= 12.4,
                  "残す区間は「残す」行の2つ(カット済の行・すき間は削る): %s" % keeps)
            out = os.path.join(tmp, "pack")
            st, bj = call(pc, "POST", "/api/build", {"spec": spec, "output": {"dir": out, "render": False, "copyVideo": False, "fcpxml": False, "force": False}})
            done = None
            for _ in range(300):
                st2, bj2 = call(pc, "GET", "/api/job?id=" + urllib.parse.quote(((bj or {}).get("job") or {}).get("id", "")))
                if (bj2 or {}).get("state") in ("done", "error", "cancelled"):
                    done = bj2
                    break
                time.sleep(0.1)
            check(done and done.get("state") == "done" and any(n.endswith(".edl") for n in os.listdir(out)),
                  "パック(EDL など)ができる: %s" % (os.listdir(out) if os.path.isdir(out) else done))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(5)
            except Exception:
                p.kill()
        left = os.listdir(rt) if os.path.isdir(rt) else []
        check(not [n for n in left if n.endswith(".json")], "正常終了で .runtime の記録が消える: %s" % left)
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
