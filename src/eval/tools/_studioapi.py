"""測る道具から、動いているスタジオの API を呼ぶ小道具(eval_marks.py --analyze-missing。役割で組み直す計画 RS4 で「あとから解析」の代わりに作った)。

- find_studio(): src/.runtime/studio.json(環境変数 YTT_RUNTIME_DIR があればそちら)の場所に /api/ping を問い合わせ、
  app が "clip-studio" のときだけ {"port", "path"} を返す(.runtime は誰でも書けるので信用しない = ytt.runtime の規則のまま)。
  ホームに取り込まれたスタジオは path が "/studio/"、単独で動くスタジオは "/"
- token_of(port, path): 画面(GET <path>)の HTML の <meta name="ytt-token"> から合言葉を読む。取り込み形の書き込み系(POST)は
  合言葉(X-YTT-Token)が要る(src/home/mount.py)。ブラウザと同じ受け取り方で、同じ利用者のローカルのプロセスは今でも画面を GET すれば読めるので、
  守りは弱くならない。単独のスタジオ(合言葉の無い画面)なら None(見出しを付けない)
- call(ep, method, path, body): 127.0.0.1 に http.client で(urllib だとプロキシの設定で 127.0.0.1 宛てがプロキシに回ることがある)。
  Host 見出しを付ける(Host / Origin の検査 ytt.httpsec を通る)。入口の ToolClient(src/home/autorun.py)と同じ形の写しで、入口(app)は読まない
"""
import http.client   # HTTPConnection は属性として引く(テストが差し替えられるように。from import にしない)
import json
import os
import re

from ytt import runtime

HERE = os.path.dirname(os.path.abspath(__file__))   # src/eval/tools
SRC = os.path.dirname(os.path.dirname(HERE))       # src(.runtime はこの下 = layout.src_root)
APP = "clip-studio"                                # スタジオの /api/ping の app(runtime.TOOL_APPS["studio"])
TOKEN_RE = re.compile(rb'<meta\s+name="ytt-token"\s+content="([A-Za-z0-9_-]{1,200})"\s*/?>')
PAGE_MAX = 2 * 1024 * 1024     # 画面の HTML を読む上限
BODY_MAX = 16 * 1024 * 1024    # API の応答を読む上限
TIMEOUT = 30


class StudioError(Exception):
    """スタジオにつながらない・応答が壊れている(文は利用者に見せる)"""


def runtime_dir():
    """src/.runtime(YTT_RUNTIME_DIR があればそちら)。スタジオのフォルダの 1 つ上 = runtime.runtime_dir の規則"""
    return runtime.runtime_dir(os.path.join(SRC, "studio"))


def find_studio(rdir=None, timeout=1.0):
    """-> {"port", "path", "token"} か None(記録が無い・応答しない・別のアプリ)。token は token_of の結果(None もある)"""
    info = runtime.read_runtime(rdir or runtime_dir(), "studio")
    if not info or runtime.ping_app(info["port"], timeout, info["path"]) != APP:
        return None
    ep = {"port": info["port"], "path": info["path"]}
    ep["token"] = token_of(ep["port"], ep["path"])
    return ep


def _request(port, method, url, body=None, token=None, limit=BODY_MAX):
    headers = {"Host": "127.0.0.1:%d" % port}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if method != "GET" and token:
        headers["X-YTT-Token"] = token
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT)
    try:
        conn.request(method, url, body=data, headers=headers)
        r = conn.getresponse()
        return r.status, r.read(limit)
    except (OSError, http.client.HTTPException) as e:
        raise StudioError("スタジオにつながりませんでした(%s)。ホームが動いているか確かめてください" % e.__class__.__name__)
    finally:
        conn.close()


def token_of(port, path="/"):
    """画面の HTML から合言葉を読む。無ければ None(単独のスタジオ・読めない)"""
    if not runtime.valid_port(port) or not runtime.valid_path(path):
        return None
    try:
        st, raw = _request(port, "GET", path, limit=PAGE_MAX)
    except StudioError:
        return None
    m = TOKEN_RE.search(raw) if st == 200 else None
    return m.group(1).decode("ascii") if m else None


def call(ep, method, api, body=None):
    """ep = find_studio() の結果・api = "api/video?id=…" のような場所(頭の / なし)-> (HTTP の状態, JSON の辞書)。
    つながらないときは StudioError。応答が JSON の辞書でなければ {}"""
    st, raw = _request(ep["port"], method, ep["path"] + api.lstrip("/"), body, ep.get("token"))
    try:
        obj = json.loads(raw.decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        obj = {}
    return st, obj if isinstance(obj, dict) else {}
