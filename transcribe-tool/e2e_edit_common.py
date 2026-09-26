#!/usr/bin/env python3
"""「編集」(docs/edit-tool-design.md)の画面のテスト(e2e_edit_*.py)の共通部分。

- ツールのフォルダの直下のファイルはまとめて一時フォルダへ写す(新しい cut.js などを足しても写し忘れで画面が真っ白にならない)
- 単体(serve.py の疑似モード)と、入口に取り込んだ形(app/launch.py --only transcribe,cut2resolve。パック作りは cut2resolve の API を呼ぶため)の両方を起動できる
- テスト用の動画は webm(VP9 + Opus)。Playwright の chromium は H.264 を再生できない
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.environ.setdefault("YTT_CORE_DIR", REPO)   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように
os.environ.setdefault("YTT_CUT2RESOLVE_DIR", os.path.join(REPO, "cut2resolve"))   # 単体で動かすとき、たたき台「行から」・zip が pack.py を見つけられるように


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def copy_tool(src, dst):
    """ツールのフォルダの直下のファイル(コード・画面・名簿・Text+ の型 .drb など)を全部写す(新しい部品の写し忘れが起きないように)。
    作業データ・キャッシュのフォルダ(サブフォルダ)と、大きなファイル(5MB 超)は写さない"""
    os.makedirs(dst, exist_ok=True)
    for n in os.listdir(src):
        p = os.path.join(src, n)
        if os.path.isfile(p) and os.path.getsize(p) <= 5 * 1024 * 1024:
            shutil.copy(p, dst)


def make_video(path, sec=12, fps=30, size="320x180", beeps=None, audio=True):
    """webm の動画。beeps = [(開始, 終了), ...] の間だけ音が鳴る(無音のたたき台・波形の確認用)。None なら鳴りっぱなし"""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=%s:rate=%s:duration=%s" % (size, fps, sec)]
    if audio:
        vol = "1" if beeps is None else "+".join("between(t,%s,%s)" % (a, b) for a, b in beeps) or "0"
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%s,volume='%s':eval=frame" % (sec, vol)]
    cmd += ["-shortest", "-pix_fmt", "yuv420p", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "200k"]   # 4:2:0(profile 0)でないとブラウザで再生できないことがある
    cmd += ["-c:a", "libopus"] if audio else ["-an"]
    subprocess.run(cmd + [path], check=True, timeout=120)
    return path


class Checks:
    def __init__(self):
        self.ok = True

    def __call__(self, cond, msg):
        print(("OK   " if cond else "FAIL ") + msg, flush=True)
        self.ok = self.ok and bool(cond)
        return bool(cond)


class Server:
    """疑似モードの文字起こし(= 編集)のサーバー。mounted=True なら入口(cut2resolve も取り込む)"""

    def __init__(self, mounted=False, backend="fake"):
        self.tmp = tempfile.mkdtemp(prefix="edit-e2e-")
        self.mounted, self.port, self.proc, self.token = mounted, free_port(), None, ""
        self.media = os.path.join(self.tmp, "media")
        os.makedirs(self.media)
        rt = os.path.join(self.tmp, ".runtime")
        env = dict(os.environ, YTT_RUNTIME_DIR=rt, TRANSCRIBE_BACKEND=backend, TRANSCRIBE_FAKE_DELAY="0.01",
                   TRANSCRIBE_STUDIO_DATA=os.path.join(self.tmp, "studio-data.json"))
        if mounted:
            for d in ("app", "transcribe-tool", "cut2resolve"):
                copy_tool(os.path.join(REPO, d), os.path.join(self.tmp, d))
            shutil.copytree(os.path.join(REPO, "ytt_core"), os.path.join(self.tmp, "ytt_core"), ignore=shutil.ignore_patterns("__pycache__"))
            self.base = "http://localhost:%d/transcribe/" % self.port
            self.api_prefix = "/transcribe"
            cmd = [sys.executable, os.path.join(self.tmp, "app", "launch.py"), "--port", str(self.port), "--no-open", "--only", "transcribe,cut2resolve"]
        else:
            copy_tool(HERE, self.tmp)
            self.base = "http://localhost:%d/" % self.port
            self.api_prefix = ""
            cmd = [sys.executable, os.path.join(self.tmp, "serve.py"), str(self.port), "--no-open"]
        self.proc = subprocess.Popen(cmd, cwd=self.tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        for _ in range(300):
            try:
                self.get("/api/ping")
                break
            except Exception:
                time.sleep(0.1)
        else:
            self.stop()
            raise RuntimeError("サーバーが起動しません")
        if mounted:   # 書き込み系の API の合言葉(入口が画面に入れる <meta name="ytt-token">)
            html = urllib.request.urlopen(self.base, timeout=10).read().decode("utf-8")
            import re
            m = re.search(r'name="ytt-token" content="([^"]+)"', html)
            self.token = m.group(1) if m else ""

    def call(self, method, path, body=None, prefix=None):
        h = {"Content-Type": "application/json", "Origin": "http://localhost:%d" % self.port}
        if self.token:
            h["X-YTT-Token"] = self.token
        url = "http://127.0.0.1:%d%s%s" % (self.port, self.api_prefix if prefix is None else prefix, path)
        h["Host"] = "localhost:%d" % self.port
        req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(), headers=h)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=60) as r:
                d = r.read()
                return json.loads(d) if d else {}
        except urllib.error.HTTPError as e:
            d = e.read()
            try:
                return dict(json.loads(d or b"{}"), _status=e.code)
            except ValueError:
                return {"_status": e.code}

    def get(self, path):
        return self.call("GET", path)

    def transcribe(self, path, title="", **extra):
        j = self.call("POST", "/api/transcribe", dict({"sourcePath": path, "model": "small", "language": "ja", "title": title, "autoGloss": False}, **extra))
        assert "id" in j, j
        for _ in range(600):
            x = next(v for v in self.get("/api/jobs")["jobs"] if v["id"] == j["id"])
            if x["state"] in ("done", "error", "cancelled"):
                assert x["state"] == "done", x
                return x["tid"]
            time.sleep(0.05)
        raise RuntimeError("文字起こしが終わりません")

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            if os.name == "nt":
                os.kill(self.proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        shutil.rmtree(self.tmp, ignore_errors=True)


def wait_js(pg, expr, timeout=15000):
    """page.wait_for_function は入口の CSP(unsafe-eval 不可)で動かないので、evaluate で待つ"""
    end = time.time() + timeout / 1000
    while time.time() < end:
        if pg.evaluate(expr):
            return True
        time.sleep(0.05)
    raise TimeoutError(expr)


def open_doc(pg, title):
    """左のメニューの「履歴」から題名で開く(カット・パックのタブでは細い帯の「履歴」から)"""
    cls = pg.get_attribute(".app", "class") or ""
    if "tab-wide" in cls:
        if "menu-overlay" not in cls:
            pg.click("[data-strip=files]")
    else:
        if "menu-closed" in cls:
            pg.click("#btnMenu")
        pg.click("[data-side-tab=files]")
    pg.fill("#txSearch", title)   # 検索すると、閉じているまとまりの中の文書も出る
    for _ in range(300):
        if pg.locator("#txList .txi").filter(has_text=title).count():
            break
        pg.evaluate("document.querySelectorAll('#txList details.ui-group:not([open])').forEach(d => { d.open = true; })")
        time.sleep(0.1)
    pg.locator("#txList .txi").filter(has_text=title).locator(".t").first.click()
    wait_js(pg, "document.querySelector('#docTitle').value === %s" % json.dumps(title), 15000)
    pg.evaluate("(() => { const q = document.querySelector('#txSearch'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); })()")
