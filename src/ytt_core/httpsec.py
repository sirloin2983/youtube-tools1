"""ローカルサーバー(127.0.0.1)の安全検査。スタジオ・文字起こし・入口で同じ規則を1か所に持つ。

- Host      … DNS rebinding 対策。「localhost:<port>」「127.0.0.1:<port>」だけ
- Origin    … 他サイトからの書き込み(CSRF)対策。送られてきたら「http://」+ 許可した Host と完全に一致するものだけ
- Sec-Fetch-Site … 他サイトからの読み取り・API の消費を断る(同じ画面からの same-origin と、アドレス欄からの none だけ)
- 画面への移動 … 他のツールの画面のリンクで、画面(/ と /index.html)を新しいタブで開くのだけは許す。
  ポートが違うだけでもブラウザは same-site(localhost と 127.0.0.1 なら cross-site)を送るため。URL で処理は始まらない(docs/spec/pipeline.md の 3)。
  埋め込み(iframe)は Sec-Fetch-Dest と PAGE_HEADERS(X-Frame-Options / frame-ancestors)で断る
- 応答 …… send / send_head: どの応答にも no-store(古い内容を見せない)と nosniff(型を推測させない)を付ける。
  スタジオ・編集・入口の Handler._send と、スタジオの動画(_media)の見出しがこれを使う(見出しの順番もここで決まる)

各サーバーにあった定型(2026-10-09。docs/design/code-review-simplify-2026-10-08.md の T6):
- read_json_body … 書き込み系の要求の JSON の本文(Content-Type・大きさの検査。断る理由は BodyError の kind。文は呼ぶ側)
- drain_body …… 断る要求の本文を読み捨てる(読まずに閉じると Windows では応答が届かないことがある)
- token_ok ……… 合言葉の比べ方(時間で漏れない比べ方・文字の種類で落ちない)
- send_file …… 動画を Range つきで返す(パスの検査は呼ぶ側)
- ExclusiveServer / bind_opts … 使用中のポートに bind しないサーバー(Windows は SO_EXCLUSIVEADDRUSE)
"""
import hmac
import json
import os
import re
import socket
from http.server import ThreadingHTTPServer

PAGES = ("/", "/index.html")
PAGE_HEADERS = {"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'", "Referrer-Policy": "same-origin"}


def allowed_hosts(port):
    return {"localhost:%d" % port, "127.0.0.1:%d" % port}


def host_ok(headers, allowed):
    return (headers.get("Host") or "") in allowed


def origin_ok(headers, allowed):
    o = headers.get("Origin")
    return o is None or o in {"http://" + h for h in allowed}


def fetch_site_ok(headers):
    return headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")


def navigation_ok(headers, path, pages=PAGES):
    return (path in pages and headers.get("Sec-Fetch-Mode") == "navigate"
            and headers.get("Sec-Fetch-Dest", "document") == "document")


def send_head(handler, code, ctype, length, extra=None, cache="no-store"):
    """応答の見出しを書く(handler = BaseHTTPRequestHandler)。Content-Type・Content-Length・Cache-Control(cache。既定 no-store)・nosniff の順で、
    extra は後ろに足す"""
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Cache-Control", cache)
    handler.send_header("X-Content-Type-Options", "nosniff")
    for k, v in (extra or {}).items():
        handler.send_header(k, v)
    handler.end_headers()


def send(handler, code, body=b"", ctype="text/plain; charset=utf-8", extra=None, cache="no-store"):
    """応答を書く(見出しは send_head。HEAD の要求には本文を書かない)。各サーバーの Handler._send はこれを呼ぶだけ
    (入口の取り込み src/home/mount.py は _send を上書きして CSP と合言葉を足すので、Handler._send という名前は残す)"""
    send_head(handler, code, ctype, len(body), extra, cache)
    if handler.command != "HEAD":
        handler.wfile.write(body)


# ---------- 各サーバーにあった定型(2026-10-09) ----------
DRAIN_MAX = 1024 * 1024   # 断る要求の本文を読み捨てる上限(これより大きい本文は読まずに閉じる)
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class BodyError(ValueError):
    """read_json_body が断った理由。kind と、既定の HTTP の状態 status を持つ(文は呼ぶ側が kind ごとに決める = 画面の文を変えない)。
    kind: "type"(Content-Type が違う。415)・"length"(Content-Length が数でない。400)・"size"(空か上限より大きい。413)・
          "read"(本文を読めなかった = 切断・時間切れ。400。応答せずに閉じてもよい)・"short"(途中で切れた。400)・
          "json"(JSON として読めない・NaN / Infinity。400)・"object"(JSON のオブジェクトでない。400)"""
    STATUS = {"type": 415, "length": 400, "size": 413, "read": 400, "short": 400, "json": 400, "object": 400}

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind
        self.status = self.STATUS[kind]


def drain_body(headers, rfile, limit=DRAIN_MAX):
    """断る要求の本文を読み捨てる(中身は見ない。limit まで。上げない)。読まずに接続を閉じると、Windows では受け取っていない本文が残っているために
    接続ごと切られ(RST)、相手に 403 などの応答が届かないことがある(2026-10-03。入口の mount.drain_body と同じ)"""
    try:
        length = int(headers.get("Content-Length") or 0)
        if 0 < length <= limit:
            rfile.read(length)
    except (OSError, ValueError):
        pass


def _reject_constant(name):
    raise ValueError("NaN / Infinity は JSON として受け付けません: %s" % name)


def read_json_body(handler, max_bytes, empty_ok=False, allow_nan=False, drain=True):
    """書き込み系の要求の本文(application/json)を読む -> dict。だめなら BodyError(kind・status)を上げる(応答は呼ぶ側)。
    - Content-Type は application/json だけ(;charset=… は可。大文字小文字は問わない。他サイトのフォームはこの形を作れない)
    - Content-Length が 1〜max_bytes(empty_ok=True なら 0 も可 = {} を返す)。途中で切れたものは断る
    - UTF-8(BOM なし)の JSON のオブジェクト。NaN / Infinity は断る(保存すると画面の JSON.parse が壊れる。allow_nan=True で許す)
    - drain=True なら、Content-Type・大きさで断るときに本文を読み捨てる(drain_body)"""
    h = handler.headers
    if (h.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
        if drain:
            drain_body(h, handler.rfile)
        raise BodyError("type")
    try:
        length = int(h.get("Content-Length") or 0)
    except ValueError:
        if drain:
            drain_body(h, handler.rfile)
        raise BodyError("length")
    if length < 0 or length > max_bytes or (length == 0 and not empty_ok):
        if drain:
            drain_body(h, handler.rfile)
        raise BodyError("size")
    if length == 0:
        return {}
    try:
        raw = handler.rfile.read(length)
    except OSError:
        raise BodyError("read")
    if len(raw) != length:
        raise BodyError("short")
    try:
        obj = json.loads(raw.decode("utf-8"), **({} if allow_nan else {"parse_constant": _reject_constant}))
    except (UnicodeError, ValueError, RecursionError):
        raise BodyError("json")
    if not isinstance(obj, dict):
        raise BodyError("object")
    return obj


def token_ok(headers, token, header="X-YTT-Token", prefix=""):
    """要求の見出し header が prefix + token と同じか(書き込み系の API の合言葉)。比べるのは hmac.compare_digest(かかる時間で中身を漏らさない)。
    bytes にしてから比べる(見出しに ASCII 以外の文字があっても TypeError で落ちない)。token が空なら常に False(合言葉の無いサーバーを開けっ放しにしない)。
    録画の部品は header="Authorization"・prefix="Bearer " で使う"""
    if not token:
        return False
    got = (headers.get(header) or "").encode("utf-8", "replace")
    return hmac.compare_digest(got, (prefix + token).encode("utf-8", "replace"))


def byte_range(range_header, size):
    """Range の見出し(bytes=a-b・bytes=a-・bytes=-n の 1 つだけ)-> (開始, 終わり(含む), 206 か)。見出しが無い・読めない形なら全体 (0, size-1, False)。
    範囲が外れていれば None(416 を返す)"""
    m = _RANGE.match(range_header or "")
    if not (m and (m.group(1) or m.group(2))):
        return 0, size - 1, False
    if m.group(1):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else size - 1
    else:
        a, b = max(0, size - int(m.group(2))), size - 1
    b = min(b, size - 1)
    if a > b or a >= size:
        return None
    return a, b, True


def send_file(handler, path, ctype, extra=None, chunk=65536):
    """ファイルを Range つきで返す(動画の再生・シーク用)。path は呼ぶ側が検査したもの(許可した場所の中・種類)。
    見出しは send_head(Accept-Ranges・Content-Range・extra は後ろに足す)。範囲が外れていれば handler._send(416, Content-Range: bytes */大きさ)。
    HEAD は見出しだけ。送っている途中の切断(ブラウザのシーク)は上げない。ファイルの大きさを調べられなければ OSError を上げる(呼ぶ側で 404 などに)"""
    size = os.path.getsize(path)
    r = byte_range(handler.headers.get("Range"), size)
    if r is None:
        return handler._send(416, b"", extra={"Content-Range": "bytes */%d" % size})
    a, b, partial = r
    head = {"Accept-Ranges": "bytes"}
    if partial:
        head["Content-Range"] = "bytes %d-%d/%d" % (a, b, size)
    head.update(extra or {})
    send_head(handler, 206 if partial else 200, ctype, b - a + 1, head)
    if handler.command == "HEAD":
        return None
    try:
        with open(path, "rb") as f:
            f.seek(a)
            left = b - a + 1
            while left > 0:
                data = f.read(min(chunk, left))
                if not data:
                    break
                handler.wfile.write(data)
                left -= len(data)
    except OSError:   # BrokenPipeError・ConnectionError も OSError(シークで切られた)
        pass
    return None


def bind_opts(sock):
    """待ち受けのソケットの設定: Windows は SO_EXCLUSIVEADDRUSE(使用中のポートに bind できてしまうのを防ぐ)、ほかは SO_REUSEADDR"""
    if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


class ExclusiveServer(ThreadingHTTPServer):
    """各ツールのサーバーの土台。Windows では SO_REUSEADDR を付けると「他のアプリが使用中のポート」にも bind できてしまい、
    どちらに繋がるか分からなくなる(例: 8810 の cut2resolve と同じポートで起動してしまう)。Windows では使わず、SO_EXCLUSIVEADDRUSE で独占する。
    要求ごとのスレッドは daemon(終了を待たせない)"""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()
