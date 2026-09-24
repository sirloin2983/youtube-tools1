"""ツール間の受け渡し(docs/pipeline.md の 2.1・4・6)。標準ライブラリのみ。

- 切り抜き1本の素性 `youtube-tools-clip/v1`(書き出した mp4 の隣の `<名前>.clip.json`)を作って原子的に書く
- 実行中のポートの共有: `<リポジトリ直下>/.runtime/studio.json` の読み書きと、`GET /api/siblings` の中身
将来1つのアプリに統合するときに、他のツールからもそのまま使えるよう、スタジオ固有の値(ツール名・版)は TOOL に入れて外から渡す。
"""
import datetime
import http.client
import json
import os
import threading
import time

import common

CLIP_SCHEMA = "youtube-tools-clip/v1"
TOOL = {"name": "clip-studio", "version": ""}   # 版は serve.py が SERVER_VERSION を入れる(版の正は serve.py のまま)
# ツールID → /api/ping の app(docs/pipeline.md の 4)。問い合わせ先はこの3つに限る(.runtime に置かれた他のファイルは読まない)
TOOL_APPS = {"studio": "clip-studio", "transcribe": "transcribe-tool", "cut2resolve": "cut2resolve"}
PING_TIMEOUT = 0.3
RUNTIME_MAX_BYTES = 4096   # .runtime/*.json はこれより大きければ読まない(信用しないファイルなので)


def iso_now():
    """ISO 8601(時差付き・秒まで)。例: 2026-09-24T12:00:00+09:00"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, obj):
    """UTF-8(BOM なし)で、一時ファイルに書いてから置き換える(書きかけを他のツールに読ませない)。"""
    common.atomic_write(path, (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# ---------- youtube-tools-clip/v1 ----------
def manifest_path(media_path):
    """動画_0012.mp4 → 動画_0012.clip.json(拡張子を置き換える)。"""
    return os.path.splitext(media_path)[0] + ".clip.json"


def _r3(x):
    return None if x is None else round(float(x), 3)


def clip_manifest(media_path, duration, source, rng, mark, export):
    """1本ぶんの youtube-tools-clip/v1 を組み立てる。
    source: {"kind": "youtube"|"file", "videoId", "title", "path"(file のときだけ元のファイル)}
    rng: (元の配信での開始秒, 終了秒)。mark: {"id","label","status","src"}。export: {"mode": "precise"|"fast", ...}。
    API キーなどの秘密や、元動画以外の個人のパスは入れない(ここに渡さない)。"""
    kind = "file" if source.get("kind") == "file" else "youtube"
    vid = str(source.get("videoId") or "")
    src = {"kind": kind, "videoId": vid,
           "url": ("https://www.youtube.com/watch?v=" + vid) if kind == "youtube" and vid else None,
           "title": str(source.get("title") or ""), "path": source.get("path") if kind == "file" else None}
    return {"schema": CLIP_SCHEMA, "tool": {"name": TOOL["name"], "version": TOOL["version"]}, "createdAt": iso_now(),
            "media": {"path": os.path.abspath(media_path), "name": os.path.basename(media_path), "durationSec": _r3(duration)},
            "source": src,
            "range": {"start": _r3(rng[0]), "end": _r3(rng[1])},
            "mark": {"id": str(mark.get("id") or ""), "label": str(mark.get("label") or ""), "status": str(mark.get("status") or ""),
                     "src": mark.get("src") if mark.get("src") in ("auto", "manual", "collab") else "manual"},
            "export": dict(export)}


def write_clip_manifest(media_path, **kw):
    """mp4 の隣に .clip.json を書いて、そのパスを返す。失敗したら OSError(呼び出し側で警告にする)。"""
    path = manifest_path(media_path)
    write_json(path, clip_manifest(media_path, **kw))
    return path


# ---------- 実行中のポートの共有(.runtime) ----------
def runtime_dir():
    """<clip-studio の1つ上>/.runtime。環境変数 YTT_RUNTIME_DIR があればそちら(テスト用)。"""
    d = os.environ.get("YTT_RUNTIME_DIR")
    return os.path.abspath(d) if d else os.path.join(os.path.dirname(common.CODE_DIR), ".runtime")


def runtime_path(tool):
    if tool not in TOOL_APPS:   # ファイル名に使うので、決まったIDだけ
        raise ValueError("unknown tool id")
    return os.path.join(runtime_dir(), tool + ".json")


def valid_port(p):
    """1024〜65535 の整数だけ(真偽値・小数・文字列は不可)。"""
    return type(p) is int and 1024 <= p <= 65535


def write_runtime(tool, port, version):
    """起動時に <runtime>/<tool>.json を書く。書けなくても起動は続ける(戻り値 None)。
    pid は「自分が書いたファイルか」を消すときに確かめるためだけに使う(生きているかの確認には使わない。
    Windows の os.kill(pid, 0) はプロセスを終了させてしまうため)。"""
    try:
        path = runtime_path(tool)
        write_json(path, {"tool": tool, "port": int(port), "version": str(version), "startedAt": iso_now(), "pid": os.getpid()})
        return path
    except (OSError, ValueError) as e:
        common.log_failure(".runtime の書き込み", e)
        return None


def remove_runtime(tool, port):
    """正常終了時に消す。別のプロセスが書き直したファイル(port・pid が違う)は消さない。"""
    try:
        path = runtime_path(tool)
        d = _read_small_json(path)
        if isinstance(d, dict) and d.get("port") == port and d.get("pid") == os.getpid():
            os.remove(path)
            return True
    except (OSError, ValueError):
        pass
    return False


def _read_small_json(path):
    with open(path, "rb") as f:
        raw = f.read(RUNTIME_MAX_BYTES + 1)
    if len(raw) > RUNTIME_MAX_BYTES:
        return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def read_runtime_port(tool):
    """<runtime>/<tool>.json のポート。無い・壊れている・tool が違う・範囲外なら None(このファイルは信用しない)。"""
    try:
        d = _read_small_json(runtime_path(tool))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("tool") != tool:
        return None
    port = d.get("port")
    return port if valid_port(port) else None


def ping_app(port, timeout=PING_TIMEOUT):
    """127.0.0.1:<port> の /api/ping の app(応答が無い・形が違えば None)。
    urllib ではなく http.client を使う: 環境変数や Windows のプロキシ設定で 127.0.0.1 宛てがプロキシに回るのを避けるため。"""
    if not valid_port(port):
        return None
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/api/ping", headers={"Host": "127.0.0.1:%d" % port, "Accept": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            return None
        d = json.loads(r.read(RUNTIME_MAX_BYTES).decode("utf-8", "replace"))
        app = d.get("app") if isinstance(d, dict) else None
        return app if isinstance(app, str) else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def siblings(self_tool=None, self_port=None, timeout=PING_TIMEOUT):
    """{"tools": {"studio": 8800, ...}}。.runtime のポートに /api/ping を問い合わせ、app が一致したものだけ(自分自身は問い合わせずに含める)。
    問い合わせは並行して行い、全体でも timeout を少し超える程度で返す(応答しないポートを待たない)。"""
    found = {}
    if self_tool in TOOL_APPS and valid_port(self_port):
        found[self_tool] = self_port
    todo = [(tid, app, read_runtime_port(tid)) for tid, app in TOOL_APPS.items() if tid != self_tool]
    todo = [(tid, app, port) for tid, app, port in todo if port is not None and port != self_port]
    lock = threading.Lock()

    def one(tid, app, port):
        if ping_app(port, timeout) == app:
            with lock:
                found[tid] = port
    ths = [threading.Thread(target=one, args=t, daemon=True, name="ping-" + t[0]) for t in todo]
    for th in ths:
        th.start()
    deadline = timeout + 0.2   # 各段階(接続・送受信)は timeout で打ち切られる。遅いPCでの余裕を少し足した全体の上限
    t0 = time.monotonic()
    for th in ths:
        th.join(max(0.0, deadline - (time.monotonic() - t0)))
    with lock:
        return {"tools": {k: found[k] for k in TOOL_APPS if k in found}}
