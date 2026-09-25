# -*- coding: utf-8 -*-
"""統合サーバーへのツールの取り込み(統合計画の段階3。docs/integration-plan.md)。

入口のサーバー(app/launch.py の PortalServer)が、ツールの serve.py を別名のモジュールとして読み込み、
同じポートの /studio/ などで画面と API を受け持つ。ファイルは動かさない(各ツールの start.bat もそのまま動く)。

- 読み込み: ツールのフォルダの serve.py を "ytt_tool_<ID>" という名前で読み込む(3つとも serve.py なので、名前をそろえると取り違える)。
  ツールの中の部品(common.py・store.py など)は、そのツールのフォルダから名前で読み込まれる。
  別のツールの同じ名前の部品がすでに読み込まれていたら、取り違えを避けるため取り込まない(MountError)
- 受け持ち: /studio/... への要求は、先頭の /studio を外してツールの Handler にそのまま渡す(ツールの API・安全検査はそのまま動く)
- 同じアドレス(オリジン)になる分の安全対策(AGENTS.md の「統合作業のリスク」):
  ① 画面に CSP(script-src は自分と YouTube のプレイヤーだけ。インラインのスクリプトは動かない)
  ② 書き込み系(GET・HEAD 以外)の要求は、合言葉(CSRF トークン。起動ごとに作る)の一致を求める。画面には <meta name="ytt-token"> で渡す
  ③ Host・Origin・Sec-Fetch の検査はツールの Handler がそのまま行う(許可するホストは入口のポートにそろえる)
"""
import hmac
import importlib.util
import os
import sys
import threading
import time
import urllib.parse

# 取り込めるツール。prefix は画面の場所(/studio/)。順番は スタジオ → cut2resolve → 文字起こし(段階3 の決定)。
# csp が None のツールは、ツール自身の CSP(serve.py の CSP。script-src 'self' で外部・インラインのスクリプトなし)をそのまま使う
MOUNTS = {
    "studio": {"dir": "clip-studio", "prefix": "/studio", "alias": "ytt_tool_studio",
               # YouTube のプレイヤー(iframe_api)だけ外部のスクリプトを許す。スタイルの属性は画面が使うので制限しない
               "csp": ("script-src 'self' https://www.youtube.com https://s.ytimg.com; object-src 'none'; base-uri 'none'; "
                       "form-action 'none'; frame-ancestors 'none'")},
    "cut2resolve": {"dir": "cut2resolve", "prefix": "/cut2resolve", "alias": "ytt_tool_cut2resolve", "csp": None},
}
TOKEN_HEADER = "X-YTT-Token"
SAFE_METHODS = ("GET", "HEAD")


class MountError(Exception):
    pass


def tool_modules(tool_dir):
    """ツールのフォルダにある部品の名前(serve・テスト・e2e を除く)。"""
    out = set()
    for n in os.listdir(tool_dir):
        name, ext = os.path.splitext(n)
        if ext == ".py" and name != "serve" and not name.startswith(("test_", "e2e_", "_")):
            out.add(name)
    return out


def check_no_collision(tool_dir):
    """別の場所から同じ名前の部品がすでに読み込まれていれば MountError(ツール間で同じ名前の部品を作らない約束の実行時の確認)。"""
    tool_dir = os.path.normcase(os.path.abspath(tool_dir))
    for name in sorted(tool_modules(tool_dir)):
        m = sys.modules.get(name)
        f = getattr(m, "__file__", None) if m else None
        if f and os.path.normcase(os.path.dirname(os.path.abspath(f))) != tool_dir:
            raise MountError("部品の名前 %s が %s と重なっています" % (name, f))


def load_serve(root, tool_id):
    """ツールの serve.py を別名で読み込んで返す(2回目以降は読み込み済みのものを返す)。"""
    spec = MOUNTS[tool_id]
    if spec["alias"] in sys.modules:
        return sys.modules[spec["alias"]]
    d = os.path.join(root, spec["dir"])
    path = os.path.join(d, "serve.py")
    if not os.path.isfile(path):
        raise MountError("%s が見つかりません" % path)
    check_no_collision(d)
    if d not in sys.path:
        sys.path.insert(0, d)   # ツールの部品(common.py など)を名前で読み込めるように(serve.py 自身も同じことをする)
    ms = importlib.util.spec_from_file_location(spec["alias"], path)
    mod = importlib.util.module_from_spec(ms)
    sys.modules[spec["alias"]] = mod
    try:
        ms.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec["alias"], None)
        raise
    for need in ("Handler", "prepare", "finish", "SERVER_VERSION"):
        if not hasattr(mod, need):
            sys.modules.pop(spec["alias"], None)
            raise MountError("%s は取り込みに対応していません(%s がありません)" % (path, need))
    return mod


def inject_token(body, token):
    """画面(HTML)の </head> の直前に合言葉を入れる。token は英数字・-・_ だけ(secrets.token_urlsafe)なので、そのまま入れても HTML は壊れない。"""
    tag = ('<meta name="ytt-token" content="%s">' % token).encode("ascii")
    i = body.find(b"</head>")
    return body[:i] + tag + body[i:] if i >= 0 else tag + body


def make_handler(mod, prefix, token, csp, access_log=None):
    """ツールの Handler を、/prefix の下で動くように包んだクラス。"""
    base = mod.Handler

    class Mounted(base):
        def log_message(self, fmt, *args):   # アクセスの記録は入口の黒い画面ではなく app/logs/<ID>.log へ
            if access_log:
                access_log("%s - %s" % (self.address_string(), fmt % args))

        def parse_request(self):
            if not super().parse_request():
                return False
            self.close_connection = True   # 1つの接続に1つの要求(接続ごとに受け持ちを決めるため)
            u = urllib.parse.urlsplit(self.path)
            if u.path == prefix:   # /studio → /studio/(画面の中の相対パスが正しく解決されるように)
                self.send_response(301)
                self.send_header("Location", prefix + "/" + ("?" + u.query if u.query else ""))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            if not u.path.startswith(prefix + "/"):
                self._json(404, {"error": "not_found", "message": "その場所はありません"})
                return False
            self.path = self.path[len(prefix):]
            if self.command not in SAFE_METHODS and not hmac.compare_digest(self.headers.get(TOKEN_HEADER) or "", token):
                self._json(403, {"error": "token", "message": "画面を開き直してから、もう一度操作してください(合言葉が違います)"})
                return False
            return True

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
            if ctype.startswith("text/html") and code == 200 and body:
                extra = dict(extra or {})
                extra["Content-Security-Policy"] = csp
                body = inject_token(body, token)
            return super()._send(code, body, ctype, extra)

    Mounted.__name__ = "Mounted_" + base.__name__
    return Mounted


class Mount:
    """取り込んだツール1つ。start() で準備して Handler を返し、stop() で後始末(.runtime を消す)。"""

    def __init__(self, root, tool_id, logs_dir):
        self.root, self.id = root, tool_id
        self.spec = MOUNTS[tool_id]
        self.prefix = self.spec["prefix"]
        self.path = self.prefix + "/"
        self.log_path = os.path.join(logs_dir, tool_id + ".log")
        self.mod = None
        self.handler = None
        self._lock = threading.Lock()

    def _access_log(self, line):
        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
            except OSError:
                pass

    def start(self, port, allowed_hosts, token):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._access_log("==== 入口に取り込んで起動(%s) ====" % self.path)
        self.mod = load_serve(self.root, self.id)
        csp = self.spec["csp"] or getattr(self.mod, "CSP", None)
        if not isinstance(csp, str) or "script-src" not in csp or "'unsafe-inline'" in csp.split("script-src", 1)[1].split(";", 1)[0]:
            raise MountError("%s の CSP が取り込みの条件(script-src にインラインを許さない)を満たしません" % self.id)
        self.mod.ALLOWED_HOSTS = set(allowed_hosts)
        self.mod.prepare(port, self.path)
        self.handler = make_handler(self.mod, self.prefix, token, csp, self._access_log)
        return self.handler

    def version(self):
        return str(getattr(self.mod, "SERVER_VERSION", "")) if self.mod else ""

    def busy(self):
        try:
            return bool(self.mod and hasattr(self.mod, "busy") and self.mod.busy())
        except Exception:
            return False

    def stop(self):
        if self.mod:
            try:
                self.mod.finish()
            except Exception:
                pass
