# -*- coding: utf-8 -*-
"""入口(ランチャー)— 3つのツールのサーバーをまとめて起動・終了し、入口の画面を出す。

    python app/launch.py [--no-open] [--port 8700] [--only studio,transcribe,cut2resolve]

統合計画の段階1(docs/integration-plan.md)。ツールのコードは変えず、各ツールのフォルダで
`serve.py <既定のポート> --no-open` を子プロセスとして起動する。ツール間の受け渡し・ポートの共有は従来どおり(docs/pipeline.md)。

  GET  /                                  入口の画面(portal.html)
  GET  /api/ping                          {"app": "ytt-launcher", "version"}
  GET  /api/status                        {"app", "version", "tools": [...]}(ツールごとの状態)
  GET  /api/log?tool=<ID>&lines=N         ツールの出力(app/logs/<ID>.log)の末尾
  POST /api/tools/<ID>/start|stop|restart {} → {"tool": {...}}
  POST /api/shutdown                      {} → この入口から起動したツールを止めて、入口も終わる

設計の要点
- 子プロセスの出力は app/logs/<ID>.log に書く(1つの黒い画面に3つのツールの出力が混ざらないように)
- ツールが準備できたかは、ツールが書く .runtime/<ID>.json のポートに /api/ping を問い合わせて確かめる。
  pid では確かめない(Windows の os.kill(pid, 0) はプロセスを終了させてしまう。docs/pipeline.md の 4)
- すでに別の黒い画面で動いているツールは「別の画面で起動済み」として扱い、起動も停止もしない(二重起動で data.json を取り合わないため)
- 止めるときは、Windows は Ctrl+Break(子を別のプロセスグループで起動しておく)、Mac/Linux は SIGTERM を送る。
  どちらも各ツールが .runtime を消してから終わる合図。一定時間で終わらなければ強制終了する
"""
import argparse
import hmac
import json
import os
import queue
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(CODE_DIR)
if ROOT not in sys.path:   # 共通部品 ytt_core(リポジトリ直下)
    sys.path.append(ROOT)
from ytt_core import httpsec, runtime  # noqa: E402
import mount as mount_mod  # noqa: E402  (app/mount.py: 統合サーバーへのツールの取り込み)

APP_ID = "ytt-launcher"
VERSION = "0.2.0"          # 入口の版の正はここ1か所(画面は /api/status の version を表示する。README.txt の見出しもそろえる)
TOOL_ID = "portal"         # .runtime/portal.json。各ツールの /api/siblings は3つのツールIDしか読まないので影響しない
DEFAULT_PORT = 8700        # 8700〜8719。文字起こし(8775〜8794)・スタジオ(8800〜)・cut2resolve(8810〜)の範囲と重ならない
PORT_RANGE = 20
UI_KIT_DIR = os.path.join(ROOT, "ui-kit")   # 共通の見た目は正本をそのまま配る(写しを作らない)
LOG_MAX = 1024 * 1024
PING_TIMEOUT = 0.5
MAX_BODY = 4096

# 作業の順番どおり。port は各ツールの既定(使用中ならツール自身が次の番号を選ぶ)
TOOLS = (
    {"id": "studio", "app": "clip-studio", "name": "切り抜きスタジオ", "sub": "配信を探す・切り抜く区間を選ぶ・書き出す",
     "dir": "clip-studio", "port": 8800, "version_file": "serve.py", "version_re": r'^SERVER_VERSION\s*=\s*"([^"]+)"'},
    {"id": "transcribe", "app": "transcribe-tool", "name": "文字起こしツール", "sub": "字幕を作る・校正する",
     "dir": "transcribe-tool", "port": 8775, "version_file": "serve.py", "version_re": r'^SERVER_VERSION\s*=\s*"([^"]+)"',
     "venv": True},
    {"id": "cut2resolve", "app": "cut2resolve", "name": "cut2resolve", "sub": "カットと字幕を Resolve へ渡す",
     "dir": "cut2resolve", "port": 8810, "version_file": "cut2resolve_core.py", "version_re": r'^VERSION\s*=\s*"([^"]+)"'},
)
TOOL_IDS = tuple(t["id"] for t in TOOLS)
STATES = ("stopped", "starting", "running", "external", "stopping", "crashed", "missing")


# ---------- 小さな道具 ----------
def runtime_dir(root):
    """<リポジトリ直下>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(各ツールと同じ規則。ytt_core.runtime)。"""
    return runtime.runtime_dir(os.path.join(root, "app"))


# .runtime の読み書き・/api/ping・接続の確認は ytt_core.runtime(各ツールと同じ規則)
valid_port = runtime.valid_port
read_runtime = runtime.read_runtime     # (rdir, tool) → {"port", "version", "pid", "mtime"} / None。誰でも書けるファイルなので検証して読む


def ping(port, timeout=PING_TIMEOUT, path="/"):
    """127.0.0.1:port の <path>api/ping → {"app", "version"} / None(プロキシを通さない)。"""
    return runtime.ping(port, timeout, path)


def port_open(port, timeout=0.3):
    """そのポートで何かが待ち受けているか(つないですぐ切る)。動作中の確認はこれで行う:
    /api/ping を数秒ごとに送ると、アクセスを記録するツール(文字起こし)の黒い画面・ログが埋まるため。"""
    return runtime.port_open(port, timeout)


def rotate(path, limit=LOG_MAX):
    """limit を超えたログを <名前>.old.log に回す(*.log は .gitignore 済み)。使用中などで回せなければそのまま追記する。"""
    try:
        if os.path.getsize(path) > limit:
            os.replace(path, path[:-4] + ".old.log" if path.endswith(".log") else path + ".old")
    except OSError:
        pass


def tail(path, lines=200, max_bytes=256 * 1024):
    """ファイルの末尾 lines 行(読めなければ None)。大きなログでも末尾 max_bytes だけ読む。文字コードが崩れた所は置き換える。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return None
    if start > 0:   # 途中から読んだ最初の行は欠けているので捨てる
        nl = data.find(b"\n")
        data = data[nl + 1:] if nl >= 0 else b""
    text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    out = text.split("\n")
    if out and out[-1] == "":
        out.pop()
    return out[-lines:] if lines > 0 else []


def expected_version(spec, root):
    """フォルダの中のコードの版(読めなければ None)。別の画面で古い版が動いているのを見分けるため。"""
    try:
        with open(os.path.join(root, spec["dir"], spec["version_file"]), "r", encoding="utf-8") as f:
            m = re.search(spec["version_re"], f.read(), re.M)
        return m.group(1) if m else None
    except (OSError, UnicodeError):
        return None


def tool_python(tool_dir, spec):
    """子を起動する Python。各ツールの start.bat / start.command と同じものを使う:
    Windows は入口と同じ(py -3 / python)、Mac/Linux の文字起こしは .venv があればそちら。"""
    if os.name != "nt" and spec.get("venv"):
        v = os.path.join(tool_dir, ".venv", "bin", "python")
        if os.access(v, os.X_OK):
            return v
    return sys.executable


def signal_stop(proc):
    """終わってほしい合図を送る(強制終了はしない)。Windows は子のプロセスグループへの Ctrl+Break(SIGBREAK)、
    それ以外は SIGTERM。どちらも各ツールが .runtime を消してから終わる処理につながっている。"""
    try:
        if os.name == "nt":
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
    except (OSError, ValueError):
        pass


# ---------- ツール1つの状態 ----------
class Tool:
    """1つのツールのサーバー(子プロセス)の状態。値の変更は lock の中で行う。
    state: stopped 停止 / starting 起動中 / running 動作中 / external 別の画面で起動済み / stopping 停止中 /
           crashed 異常終了 / missing フォルダ・serve.py が無い
    mounted = True は、子プロセスではなく入口のサーバーの中に取り込んで動かしているもの(段階3。app/mount.py)"""

    def __init__(self, spec, root, logs_dir):
        self.spec = spec
        self.id = spec["id"]
        self.app = spec["app"]
        self.root = root
        self.dir = os.path.join(root, spec["dir"])
        self.script = os.path.join(self.dir, "serve.py")
        self.log_path = os.path.join(logs_dir, self.id + ".log")
        self.default_port = spec["port"]
        self.lock = threading.RLock()
        self.state = "stopped"
        self.message = ""
        self.since = time.time()
        self.proc = None
        self.managed = False      # この入口が起動した子プロセスか(別の画面で起動したものは止めない)
        self.port = None
        self.version = ""
        self.expected = None
        self.exit_code = None
        self.spawned_at = 0.0
        self.starts = 0
        self.last_ping = 0.0
        self.fail_pings = 0
        self.mounted = False
        self.mount = None
        self.path = "/"

    def set_state(self, state, message=""):
        self.state = state
        self.message = message
        self.since = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id, "name": self.spec["name"], "sub": self.spec["sub"], "state": self.state, "message": self.message,
                "since": round(self.since, 3), "port": self.port, "version": self.version, "expectedVersion": self.expected,
                "managed": self.managed, "exitCode": self.exit_code, "starts": self.starts, "mounted": self.mounted, "path": self.path,
                "log": os.path.relpath(self.log_path, self.root), "hasLog": os.path.exists(self.log_path),
            }


# ---------- まとめて管理 ----------
class Supervisor:
    def __init__(self, root=ROOT, only=None, ready_timeout=90.0, stop_timeout=8.0, poll=0.5, log=None, ports=None, mounts=()):
        """ports: {"studio": 18800, ...} 既定のポートを変える(テスト用。本物のツールとぶつからないように)
        mounts: 入口のサーバーに取り込むツール("studio" など。app/mount.py の MOUNTS にあるもの)。attach() でサーバーを渡してから start する"""
        self.root = os.path.abspath(root)
        self.rdir = runtime_dir(self.root)
        self.logs_dir = os.path.join(self.root, "app", "logs")
        self.tools = [Tool(s, self.root, self.logs_dir) for s in TOOLS if not only or s["id"] in only]
        for t in self.tools:
            t.default_port = int((ports or {}).get(t.id) or t.default_port)
        self.by_id = {t.id: t for t in self.tools}
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.poll = poll
        self.log = log or (lambda msg: None)
        self._halt = threading.Event()
        self._thread = None
        self.mounts = tuple(m for m in mounts if m in mount_mod.MOUNTS)
        self.server = None

    def attach(self, server):
        """入口のサーバー(PortalServer)を渡す。取り込むツールはこのサーバーの中で動く。"""
        self.server = server

    # --- 状態 ---
    def status(self):
        return {"app": APP_ID, "version": VERSION, "tools": [t.snapshot() for t in self.tools]}

    def _find_external(self, t, scan=False):
        """別の画面で動いている同じツール (port, version)。.runtime のポートと既定のポートを問い合わせる
        (scan=True なら既定から20個。子が「すでに起動しています」で終わったとき用)。"""
        cands = []
        info = read_runtime(self.rdir, t.id)
        if info and not (self.server and info["port"] == self.server.server_address[1]):   # 自分(この入口)の記録は問い合わせない
            cands.append((info["port"], info["path"]))
        base = t.default_port
        cands += [(p, "/") for p in (range(base, base + PORT_RANGE) if scan else [base])]
        seen = set()
        for p, path in cands:
            if (p, path) in seen:
                continue
            seen.add((p, path))
            r = ping(p, 0.3 if scan else PING_TIMEOUT, path)
            if r and r["app"] == t.app:
                return p, r["version"]
        return None

    # --- 起動 ---
    def start(self, tid):
        t = self.by_id[tid]
        with t.lock:
            if t.state in ("starting", "running", "stopping", "external"):
                return t.snapshot()
            t.expected = expected_version(t.spec, self.root)
            if not os.path.isfile(t.script):
                t.proc, t.managed, t.port = None, False, None
                t.set_state("missing", "%s が見つかりません" % os.path.relpath(t.script, self.root))
                self.log("× %s: %s" % (t.spec["name"], t.message))
                return t.snapshot()
            ext = self._find_external(t)
            if ext:
                self._mark_external(t, *ext)
                return t.snapshot()
            if t.id in self.mounts and self.server is not None and self._mount(t):
                return t.snapshot()
            self._spawn(t)
            return t.snapshot()

    def _mount(self, t):
        """入口のサーバーの中に取り込んで動かす。できなければ False(従来どおり子プロセスで起動する)。"""
        m = mount_mod.Mount(self.root, t.id, self.logs_dir)
        try:
            handler = m.start(self.server.server_address[1], self.server.allowed_hosts, self.server.token)
        except Exception as e:   # 取り込めなくても使えるように、子プロセスに切り替える
            self.log("※ %s を入口に取り込めませんでした(%s: %s)。別のプログラムとして起動します" % (t.spec["name"], e.__class__.__name__, e))
            return False
        self.server.mounts[m.prefix] = handler
        t.proc, t.managed, t.mounted, t.mount, t.fail_pings = None, True, True, m, 0
        t.port, t.path, t.version = self.server.server_address[1], m.path, m.version()
        t.starts += 1
        t.set_state("running")
        self.log("○ %s: http://localhost:%d%s (v%s・入口に取り込み)" % (t.spec["name"], t.port, t.path, t.version))
        return True

    def unmount_all(self):
        """終了の後始末(取り込んだツールの .runtime を消す)。"""
        for t in self.tools:
            if t.mounted and t.mount:
                t.mount.stop()

    def _mark_external(self, t, port, version):
        t.proc, t.managed, t.port, t.version, t.fail_pings = None, False, port, version, 0
        msg = ""
        if t.expected and version and version != t.expected:
            msg = "古い版(v%s)が別の黒い画面で動いています。その画面を閉じてから「起動」を押すと、v%s で起動します" % (version, t.expected)
        t.set_state("external", msg)
        self.log("○ %s: 別の画面で起動済み http://localhost:%d/ (v%s)%s" % (t.spec["name"], port, version, "  ※" + msg if msg else ""))

    def _spawn(self, t):
        os.makedirs(self.logs_dir, exist_ok=True)
        rotate(t.log_path)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")   # ファイルへの出力で cp932 に無い文字(絵文字の題名など)で落ちないように
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [tool_python(t.dir, t.spec), "-u", t.script, str(t.default_port), "--no-open"]
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        try:
            with open(t.log_path, "ab") as logf:
                logf.write(("\n==== %s 入口から起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
                logf.flush()
                proc = subprocess.Popen(cmd, cwd=t.dir, env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            t.proc, t.managed = None, False
            t.set_state("crashed", "起動できませんでした(%s)" % (e.strerror or e.__class__.__name__))
            self.log("× %s: %s" % (t.spec["name"], t.message))
            return
        t.proc, t.managed, t.port, t.version, t.exit_code, t.fail_pings = proc, True, None, "", None, 0
        t.spawned_at = time.time()
        t.starts += 1
        t.set_state("starting")
        self.log("… %s を起動しています" % t.spec["name"])

    def start_all(self):
        for t in self.tools:
            self.start(t.id)

    # --- 停止 ---
    def stop(self, tid):
        t = self.by_id[tid]
        with t.lock:
            if t.state == "external":   # 別の画面で起動したものは止めない(その画面で作業中かもしれない)
                return t.snapshot()
            if t.mounted:   # 入口のサーバーの中で動いているので、単独では止めない(入口と一緒に終わる)
                return t.snapshot()
            proc = t.proc
            if proc is None:
                if t.state not in ("crashed", "missing"):
                    t.set_state("stopped")
                return t.snapshot()
            t.set_state("stopping")
            signal_stop(proc)
        try:   # 待つ間は lock を持たない(画面の状態表示を止めないため)
            proc.wait(self.stop_timeout)
        except subprocess.TimeoutExpired:
            self.log("※ %s が %d 秒で終わらないので強制終了します" % (t.spec["name"], self.stop_timeout))
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        with t.lock:
            if t.proc is proc:
                self._finish(t, proc.returncode, "stopped", "")
                self.log("■ %s を止めました" % t.spec["name"])
            return t.snapshot()

    def restart(self, tid):
        self.stop(tid)
        return self.start(tid)

    def stop_all(self):
        ths = [threading.Thread(target=self.stop, args=(t.id,), daemon=True) for t in self.tools if t.proc is not None]
        for th in ths:
            th.start()
        for th in ths:
            th.join(self.stop_timeout + 7)

    def _finish(self, t, code, state, message):
        t.proc, t.exit_code = None, code
        t.set_state(state, message)
        self._cleanup_runtime(t)
        t.port = None

    def _cleanup_runtime(self, t):
        """強制終了などで子が消せなかった .runtime/<ID>.json を消す。今回起動した子が書いたもの(起動より後の更新時刻)で、
        そのポートが応答しないときだけ(別の画面で起動したツールの記録は消さない)。"""
        if not t.managed:
            return
        info = read_runtime(self.rdir, t.id)
        if not info or info["mtime"] < t.spawned_at - 2:
            return
        r = ping(info["port"], 0.3)
        if r and r["app"] == t.app:
            return
        try:
            os.unlink(os.path.join(self.rdir, t.id + ".json"))
        except OSError:
            pass

    # --- 監視 ---
    def _tick(self, t):
        with t.lock:
            if t.mounted:   # 入口のサーバーの中で動いている(見張る子プロセスは無い)
                return
            now = time.time()
            if t.proc is not None:
                code = t.proc.poll()
                if code is not None:
                    return self._on_exit(t, code)
            if t.state == "starting":
                info = read_runtime(self.rdir, t.id)
                if info and info["mtime"] >= t.spawned_at - 2:   # 前回の古い記録は使わない
                    r = ping(info["port"])
                    if r and r["app"] == t.app:
                        t.port, t.version = info["port"], r["version"]
                        t.set_state("running")
                        t.last_ping = now
                        self.log("○ %s: http://localhost:%d/ (v%s)" % (t.spec["name"], t.port, t.version))
                        return
                if now - t.spawned_at > self.ready_timeout and not t.message:
                    t.message = "起動に時間がかかっています。下のログを確認してください"
            elif t.state in ("running", "external") and now - t.last_ping >= 3:
                t.last_ping = now
                if port_open(t.port):   # 誰のサーバーかは起動・検出のときに /api/ping で確かめ済み
                    t.fail_pings = 0
                    if t.state == "running" and t.message.startswith("応答"):
                        t.message = ""
                    return
                t.fail_pings += 1
                if t.state == "external" and t.fail_pings >= 2:
                    t.port = None
                    t.set_state("stopped", "別の画面で動いていたサーバーが終了しました")
                    self.log("■ %s: 別の画面のサーバーが終了しました" % t.spec["name"])
                elif t.state == "running" and t.fail_pings >= 3 and not t.message:
                    t.message = "応答がありません(重い処理の途中の可能性があります)"

    def _on_exit(self, t, code):
        """子プロセスが終わっていた。止めた最中なら停止、そうでなければ異常終了(または別の画面で起動済みだった)。"""
        if t.state == "stopping":   # 停止の合図で終わった(stop() の待ちより先に監視が気づいた)
            self._finish(t, code, "stopped", "")
            self.log("■ %s を止めました" % t.spec["name"])
            return
        if code == 0:   # 「すでに起動しています」で終わった(起動直前に別の画面で起動された)など
            ext = self._find_external(t, scan=True)
            if ext:
                t.proc, t.exit_code = None, code
                self._mark_external(t, *ext)
                return
            self._finish(t, code, "stopped", "終了しました")
            self.log("■ %s が終了しました" % t.spec["name"])
            return
        self._finish(t, code, "crashed", "異常終了しました(終了コード %s)。下のログを確認して、「起動」で起動し直せます" % code)
        last = tail(t.log_path, 5) or []
        self.log("× %s が異常終了しました(終了コード %s)。ログ: %s" % (t.spec["name"], code, os.path.relpath(t.log_path, self.root))
                 + "".join("\n    " + ln for ln in last))

    def _monitor(self):
        while not self._halt.wait(self.poll):
            for t in self.tools:
                try:
                    self._tick(t)
                except Exception as e:   # 監視は止めない
                    self.log("※ 監視中のエラー(%s): %s" % (t.id, e.__class__.__name__))

    def start_monitor(self):
        self._thread = threading.Thread(target=self._monitor, daemon=True, name="launcher-monitor")
        self._thread.start()

    def close(self):
        self._halt.set()
        if self._thread:
            self._thread.join(2)


# ---------- 入口の画面(HTTP) ----------
STATIC = {"/": ("portal.html", CODE_DIR), "/index.html": ("portal.html", CODE_DIR), "/portal.js": ("portal.js", CODE_DIR),
          "/portal.css": ("portal.css", CODE_DIR), "/ui-kit.css": ("ui-kit.css", UI_KIT_DIR), "/ui-kit.js": ("ui-kit.js", UI_KIT_DIR)}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
ACTION_RE = re.compile(r"/api/tools/([a-z0-9]{1,20})/(start|stop|restart)")


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "ytt-launcher"
    timeout = 30

    def log_message(self, fmt, *args):   # アクセスのたびに黒い画面へ出さない(状態の変化だけを出す)
        pass

    def _host_ok(self):          # DNS rebinding 対策
        return httpsec.host_ok(self.headers, self.server.allowed_hosts)

    def _origin_ok(self):        # 他サイトからの操作(CSRF)対策
        return httpsec.origin_ok(self.headers, self.server.allowed_hosts)

    def _site_ok(self):
        return httpsec.fetch_site_ok(self.headers)

    def _navigation_ok(self, path):
        """他のツールの画面のリンクで入口を開くのは許す(画面を開くだけで、URL で処理は始まらない)。API は同じ画面からだけ"""
        return httpsec.navigation_ok(self.headers, path)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, code, err, message):
        self._json(code, {"error": err, "message": message})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if not (self._host_ok() and (self._site_ok() or self._navigation_ok(u.path))):
            return self._send(403, b"forbidden")
        if u.path in STATIC:
            name, base = STATIC[u.path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._send(404, b"not found")
            page = name.endswith(".html")
            if page:   # 書き込み系の API の合言葉(CSRF トークン)を画面に渡す。取り込んだツールと同じ合言葉
                body = mount_mod.inject_token(body, self.server.token)
            return self._send(200, body, STATIC_TYPES[os.path.splitext(name)[1]],
                              {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"} if page else None)
        sup = self.server.sup
        if u.path == "/api/ping":
            return self._json(200, {"app": APP_ID, "version": VERSION})
        if u.path == "/api/status":
            return self._json(200, sup.status())
        if u.path == "/api/log":
            q = urllib.parse.parse_qs(u.query)
            tid = (q.get("tool") or [""])[0]
            if tid not in sup.by_id:   # 決まったIDだけ。パスは受け取らない
                return self._fail(404, "unknown_tool", "そのツールはありません")
            try:
                n = min(1000, max(1, int((q.get("lines") or ["200"])[0])))
            except ValueError:
                n = 200
            t = sup.by_id[tid]
            lines = tail(t.log_path, n)
            return self._json(200, {"tool": tid, "exists": lines is not None, "lines": lines or [],
                                    "log": os.path.relpath(t.log_path, sup.root)})
        return self._fail(404, "not_found", "その操作はありません")

    def _read_json(self):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self._fail(415, "content_type", "application/json だけを受け付けます")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._fail(413, "size", "本文の大きさが正しくありません")
            return None
        try:
            raw = self.rfile.read(length) if length else b"{}"
            obj = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, UnicodeError):
            self._fail(400, "json", "JSON が読めません")
            return None
        if not isinstance(obj, dict):
            self._fail(400, "json", "JSON のオブジェクトを送ってください")
            return None
        return obj

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if not (self._host_ok() and self._origin_ok() and self._site_ok()):
            return self._send(403, b"forbidden")
        if not hmac.compare_digest(self.headers.get(mount_mod.TOKEN_HEADER) or "", self.server.token):
            return self._fail(403, "token", "画面を開き直してから、もう一度操作してください(合言葉が違います)")
        if self._read_json() is None:
            return
        sup = self.server.sup
        m = ACTION_RE.fullmatch(u.path)
        if m:
            tid, action = m.groups()
            if tid not in sup.by_id:
                return self._fail(404, "unknown_tool", "そのツールはありません")
            if self.server.closing.is_set():
                return self._fail(409, "closing", "終了の途中です")
            return self._json(200, {"tool": getattr(sup, action)(tid)})
        if u.path == "/api/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=self.server.request_shutdown, daemon=True).start()
            return
        return self._fail(404, "not_found", "その操作はありません")


def peek_path(sock, timeout=10.0):
    """接続の最初の行(GET /studio/... HTTP/1.1)を、読み取らずに覗いてパスを返す(無い・壊れていれば None)。
    どのツールの Handler に渡すかを、要求を読み始める前に決めるため。つないですぐ切る接続(入口の動作確認)は None。"""
    end = time.monotonic() + timeout
    data = b""
    try:
        sock.settimeout(timeout)
        while True:
            data = sock.recv(8192, socket.MSG_PEEK)
            if not data or b"\r\n" in data or len(data) >= 8192 or time.monotonic() > end:
                break
            time.sleep(0.01)   # 続きがまだ届いていない(覗くだけなので同じ内容がすぐ返る)
    except OSError:
        return None
    line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = line.split(" ")
    return parts[1] if len(parts) >= 3 else None


class PortalServer(ThreadingHTTPServer):
    """入口のサーバー。取り込んだツール(mounts: {"/studio": Handler})の要求は、そのツールの Handler に渡す。
    Windows では SO_REUSEADDR だと使用中のポートにも bind できてしまうので、代わりに SO_EXCLUSIVEADDRUSE で独占する(切り抜きスタジオと同じ)。"""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def __init__(self, addr, sup):
        super().__init__(addr, PortalHandler)
        self.sup = sup
        p = self.server_address[1]
        self.allowed_hosts = httpsec.allowed_hosts(p)
        self.closing = threading.Event()
        self.token = secrets.token_urlsafe(24)   # 書き込み系の API の合言葉(CSRF トークン)。起動ごとに変わる
        self.mounts = {}

    def handler_for(self, path):
        if path and self.mounts:
            p = urllib.parse.urlsplit(path).path
            for prefix, handler in self.mounts.items():
                if p == prefix or p.startswith(prefix + "/"):
                    return handler
        return PortalHandler

    def finish_request(self, request, client_address):
        # 覗けなかった(何も送らずに切った接続・壊れた要求の行)ときは入口の Handler に任せる(読んで静かに終わる)
        self.handler_for(peek_path(request))(request, client_address, self)

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def request_shutdown(self):
        """画面の「すべて終了」。この入口から起動したツールを止めてから、待ち受けを終える(serve_forever が戻る)。"""
        if self.closing.is_set():
            return
        self.closing.set()
        self.sup.log("画面から「すべて終了」が押されました")
        self.sup.stop_all()
        self.sup.unmount_all()
        self.shutdown()


def make_server(start_port, sup):
    """start_port から20個のうち空いているポートで待ち受ける。入口がすでに動いていれば (None, そのポート)。
    start_port=0 は OS に空きポートを選ばせる(テスト用)。"""
    if start_port == 0:
        srv = PortalServer(("127.0.0.1", 0), sup)
        return srv, srv.server_address[1]
    for p in range(start_port, start_port + PORT_RANGE):
        r = ping(p)
        if r and r["app"] == APP_ID:
            return None, p
        if r is not None:   # 他のツールが使っている
            continue
        try:
            srv = PortalServer(("127.0.0.1", p), sup)
        except OSError:
            continue
        return srv, p
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + PORT_RANGE - 1))


# ---------- 起動 ----------
def make_logger(path):
    """黒い画面と app/logs/launcher.log に1行ずつ出す。
    黒い画面への表示は専用のスレッドに任せる: Windows の黒い画面は、文字を選択している間(簡易編集モード)は表示の書き込みが止まるので、
    監視や画面の API がその待ちに巻き込まれて固まらないように。"""
    lock = threading.Lock()
    q = queue.Queue(maxsize=1000)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rotate(path)
    except OSError:
        pass

    def printer():
        while True:
            msg = q.get()
            try:
                print(msg, flush=True)
            except (OSError, ValueError):
                pass
    threading.Thread(target=printer, daemon=True, name="launcher-console").start()

    def log(msg):
        try:
            q.put_nowait(msg)
        except queue.Full:   # 表示が長く止まっている。ファイルには残す
            pass
        with lock:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
            except OSError:
                pass

    def flush(timeout=1.0):
        """終了の直前に、表示待ちの行を出し切る(黒い画面が止まっていれば待たない)"""
        end = time.time() + timeout
        while not q.empty() and time.time() < end:
            time.sleep(0.02)
    log.flush = flush
    return log


STOP_SIGNALS = ("SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP")
_stop_requested = threading.Event()


def _set_stop_handlers(handler):
    for name in STOP_SIGNALS:
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError, RuntimeError):
                pass


def install_stop_signals():
    """Ctrl+C・黒い画面の×(Windows は SIGBREAK)・SIGTERM・SIGHUP で、子を止めて portal.json を消してから終わる。
    合図は1回だけ受け取る: 2回目(Ctrl+C の連打・×と同時の合図など)で後始末の途中に止まり、子が残るのを防ぐ。
    Windows は×で閉じてから約5秒で強制終了されるが、同じ画面の子にも同じ合図が届くので、子は自分で後始末する。"""
    def stop(_sig, _frame):
        if _stop_requested.is_set():
            return
        _stop_requested.set()
        raise KeyboardInterrupt()
    _set_stop_handlers(stop)


def ignore_stop_signals():
    """後始末の間は、追加の合図で中断されないようにする。"""
    _stop_requested.set()
    _set_stop_handlers(signal.SIG_IGN)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="launch.py", description="3つのツールをまとめて起動し、入口の画面を開く")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="入口の画面のポート(既定 %d。使用中なら次の番号)" % DEFAULT_PORT)
    ap.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    ap.add_argument("--only", default="", help="起動するツールを絞る(例: studio,transcribe)")
    ap.add_argument("--no-mount", action="store_true",
                    help="ツールを入口に取り込まず、以前と同じく別のプログラムとして起動する(取り込みで問題が出たときの戻し方)")
    a = ap.parse_args(argv)
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    bad = [x for x in only if x not in TOOL_IDS]
    if bad:
        ap.error("--only に使えるのは %s です(%s は不明)" % (", ".join(TOOL_IDS), ", ".join(bad)))
    a.only = only
    return a


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    log = make_logger(os.path.join(ROOT, "app", "logs", "launcher.log"))
    sup = Supervisor(ROOT, only=opts.only, log=log, mounts=() if opts.no_mount else tuple(mount_mod.MOUNTS))
    srv, port = make_server(opts.port, sup)
    url = "http://localhost:%d/" % port
    if srv is None:
        print("入口はすでに起動しています。ブラウザで開きます:", url)
        if not opts.no_open:
            webbrowser.open(url)
        return 0
    http_thread = None
    try:
        install_stop_signals()
        runtime.write_runtime(sup.rdir, TOOL_ID, port, VERSION)   # 書けなくても続ける(使う人はまだいない)
        log("入口 v%s: %s (終了は画面の「すべて終了」・Ctrl+C・この黒い画面を閉じる)" % (VERSION, url))
        log("各ツールの出力: %s" % os.path.relpath(sup.logs_dir, ROOT))
        sup.attach(srv)
        served = threading.Event()

        def serve():
            try:
                srv.serve_forever()
            finally:
                served.set()
        http_thread = threading.Thread(target=serve, daemon=True, name="portal-http")
        http_thread.start()   # 取り込みの準備中も画面を開けるように、先に待ち受ける
        sup.start_all()
        sup.start_monitor()
        if not opts.no_open:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        while not served.wait(0.5):   # 待ち受けは別のスレッド。ここは Ctrl+C などの合図を受け取るために待つ
            pass
    except KeyboardInterrupt:
        ignore_stop_signals()
        log("終了の合図を受け取りました。この入口から起動したツールを止めています…")
    finally:
        ignore_stop_signals()
        srv.closing.set()
        sup.close()
        sup.stop_all()
        sup.unmount_all()
        if http_thread is not None and http_thread.is_alive():
            srv.shutdown()
        runtime.remove_runtime(sup.rdir, TOOL_ID, port)   # 自分が書いた記録のときだけ消す(別の入口が書き直したものは残す)
        srv.server_close()
        log("入口を終了しました")
        log.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
