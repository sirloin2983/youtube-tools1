"""実行中のポートの共有(docs/pipeline.md の 4)。スタジオの handoff.py・文字起こしの pipeline_io.py・入口の launch.py にあった同じ処理を1つにしたもの。

- <リポジトリ直下>/.runtime/<ツールID>.json … 起動時に {"tool", "port", "version", "startedAt", "pid"} を書き、正常終了時に消す
- /api/ping に問い合わせて、本当にそのツールが応答するかを確かめる(.runtime のファイルは誰でも書けるので信用しない)
- 生きているかを pid では確かめない(Windows の os.kill(pid, 0) はプロセスを終了させてしまうため)。pid は「自分が書いた記録か」の確認だけに使う
"""
import http.client   # ping は http.client.HTTPConnection を属性として引く(テストが差し替えるため。from import にしない)
import json
import os
import re
import socket
import threading
import time

from . import fsio
from .schemas import iso_now

# ツールID → /api/ping の app。/api/siblings で問い合わせるのはこの3つだけ(.runtime に置かれた他のファイルは読まない)
TOOL_APPS = {"studio": "clip-studio", "transcribe": "transcribe-tool", "cut2resolve": "cut2resolve"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")   # 記録のファイル名に使う ID(入口の portal も書く)。../ などを入れさせない
PATH_RE = re.compile(r"^/(?:[a-z0-9][a-z0-9-]{0,31}/)?\Z")   # 画面の場所: "/"(自分のポートの直下)か、統合サーバーに取り込まれたツールの "/studio/" など
MAX_BYTES = 4096        # .runtime/*.json はこれより大きければ読まない
PING_TIMEOUT = 0.3


def valid_port(p):
    """1024〜65535 の整数だけ(真偽値・小数・文字列は不可)。"""
    return type(p) is int and 1024 <= p <= 65535


def runtime_dir(tool_dir):
    """<ツールのフォルダの1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)。"""
    d = os.environ.get("YTT_RUNTIME_DIR")
    return os.path.abspath(d) if d else os.path.join(os.path.dirname(os.path.abspath(tool_dir)), ".runtime")


def runtime_path(rdir, tool):
    if not isinstance(tool, str) or not ID_RE.match(tool):
        raise ValueError("unknown tool id")
    return os.path.join(rdir, tool + ".json")


def valid_path(p):
    return isinstance(p, str) and bool(PATH_RE.match(p))


def write_runtime(rdir, tool, port, version, path="/"):
    """起動時に <rdir>/<tool>.json を書いてそのファイルのパスを返す。書けなくても起動は続ける(None を返す)。
    path は画面の場所(統合サーバーに取り込まれたツールは "/studio/" など。自分のポートの直下なら "/" で、記録には書かない)。"""
    try:
        f = runtime_path(rdir, tool)
        if not valid_path(path):
            raise ValueError("bad path")
        info = {"tool": tool, "port": int(port), "version": str(version), "startedAt": iso_now(), "pid": os.getpid()}
        if path != "/":
            info["path"] = path
        fsio.write_json(f, info)
        return f
    except (OSError, ValueError, TypeError):
        return None


def read_runtime(rdir, tool):
    """<rdir>/<tool>.json → {"port", "version", "pid", "mtime", "path"}。無い・壊れている・tool が違う・ポートが範囲外なら None。
    path が無い・形が違うときは "/"(以前の記録・他人が書いた値で、別の場所へ向けさせない)。
    mtime はファイルの更新時刻(入口が「今回起動した子が書いた記録か」を見分けるため)。"""
    try:
        path = runtime_path(rdir, tool)
        d = fsio.read_json_file(path, MAX_BYTES)
        mtime = os.stat(path).st_mtime
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("tool") != tool or not valid_port(d.get("port")):
        return None
    pid = d.get("pid")
    path = d.get("path") if valid_path(d.get("path")) else "/"
    return {"port": d["port"], "version": str(d.get("version", ""))[:40], "pid": pid if type(pid) is int else None, "mtime": mtime, "path": path}


def read_runtime_port(rdir, tool):
    info = read_runtime(rdir, tool)
    return info["port"] if info else None


def remove_runtime(rdir, tool, port):
    """正常終了時に消す。自分が書いたもの(同じポート・同じプロセス)のときだけ(後から別のポートで起動した同じツールの記録を消さないため)。"""
    try:
        path = runtime_path(rdir, tool)
        d = fsio.read_json_file(path, MAX_BYTES)
    except (OSError, UnicodeError, ValueError):
        return False
    if not isinstance(d, dict) or d.get("port") != port or d.get("pid") != os.getpid():
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def ping(port, timeout=PING_TIMEOUT, path="/"):
    """http://127.0.0.1:<port><path>api/ping → {"app", "version"}(応答が無い・形が違えば None)。
    path は統合サーバーに取り込まれたツールの場所("/studio/" なら /studio/api/ping)。
    問い合わせ先は 127.0.0.1 に固定(ファイルの中身で別のホストへ向けさせない)。urllib ではなく http.client を使うのは、
    環境変数や Windows のプロキシ設定で 127.0.0.1 宛てがプロキシに回るのを避けるため。"""
    if not valid_port(port) or not valid_path(path):
        return None
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path + "api/ping", headers={"Host": "127.0.0.1:%d" % port, "Accept": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            return None
        d = json.loads(r.read(MAX_BYTES).decode("utf-8", "replace"))
        if not isinstance(d, dict) or not isinstance(d.get("app"), str):
            return None
        return {"app": d["app"], "version": str(d.get("version", ""))[:40]}
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def ping_app(port, timeout=PING_TIMEOUT, path="/"):
    r = ping(port, timeout, path)
    return r["app"] if r else None


def port_open(port, timeout=0.3):
    """そのポートで何かが待ち受けているか(つないで、要求を送らずにすぐ切る)。
    要求を送らない接続は各ツールの http.server でアクセスとして記録されないので、定期的な確認に使える。"""
    if not valid_port(port):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def siblings(rdir, self_tool=None, self_port=None, timeout=PING_TIMEOUT, self_path="/"):
    """{"tools": {"studio": 8800, ...}}。.runtime の記録の場所に /api/ping を問い合わせ、app が一致したものだけ。
    統合サーバーに取り込まれたツール(path が "/" 以外)があれば {"paths": {"studio": "/studio/"}} も付ける(無ければ付けない)。
    自分自身は問い合わせずに含める。問い合わせは並行して行い、全体でも timeout を少し超える程度で返す(応答しないポートを待たない)。"""
    found, paths = {}, {}
    if self_tool in TOOL_APPS and valid_port(self_port):
        found[self_tool] = self_port
        if valid_path(self_path) and self_path != "/":
            paths[self_tool] = self_path
    todo = []
    for tid, app in TOOL_APPS.items():
        info = read_runtime(rdir, tid) if tid != self_tool else None
        if info and not (info["port"] == self_port and info["path"] == (self_path if valid_path(self_path) else "/")):
            todo.append((tid, app, info["port"], info["path"]))
    lock = threading.Lock()

    def one(tid, app, port, path):
        if ping_app(port, timeout, path) == app:
            with lock:
                found[tid] = port
                if path != "/":
                    paths[tid] = path
    ths = [threading.Thread(target=one, args=t, daemon=True, name="ping-" + t[0]) for t in todo]
    for th in ths:
        th.start()
    deadline = timeout + 0.2   # 各段階(接続・送受信)は timeout で打ち切られる。遅い PC での余裕を少し足した全体の上限
    t0 = time.monotonic()
    for th in ths:
        th.join(max(0.0, deadline - (time.monotonic() - t0)))
    with lock:
        out = {"tools": {k: found[k] for k in TOOL_APPS if k in found}}
        if paths:
            out["paths"] = {k: paths[k] for k in TOOL_APPS if k in paths}
        return out
