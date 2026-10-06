# -*- coding: utf-8 -*-
"""録画の部品(線 D: リアルタイム切り抜きの P1。plan/line-d-live-clipping.md の 0)。入口とは別のプロセスで動く。

    py -3.10 src/recorder/recorder.py [--port 8730] [--folder E:\\Video\\live-rec] [--host 127.0.0.1 --allow-host <ホスト:ポート>]
                                  [--data-dir <フォルダ>] [--source streamlink|direct]

1台のときはデスクトップで 127.0.0.1 だけで待ち受ける。2台(P5)のときはノート PC で同じプログラムを LAN で待ち受ける
(--host と --allow-host。合言葉と Host の検査は1台のときも同じコードを通る)。ブラウザからは直接使わない: 入口(home/live.py)が
/live/r/<録画元>/… を中継する(同じオリジン・CSP・合言葉の決まりのまま、CORS が要らない)。

API(/api/ping 以外は合言葉 `Authorization: Bearer <token>` が要る。token は <作業データ>/recorder/token.txt):
  GET  /api/ping                          {"app": "ytt-recorder", "version"}(合言葉なし。生きているかの確認)
  GET  /live/list                         置き場所・空き容量・streamlink の有無・録画の一覧
  POST /live/start  {url, quality?, title?}  録画を始める(配信の前でも、始まるまで待つ)。quality: best|1080p|720p(省略は 1080p)
  POST /live/<id>/stop  {}                 手で止める
  POST /live/<id>/delete  {}               録画のフォルダを消して一覧から外す(P4 の「録画を自動で消す」。入口の home/live_cleanup.py だけが呼ぶ。
                                           録画中・配信待ち・つなぎ直し中は 409・使用中のファイルが残ったら 409 = あとでまた呼べる)
  GET  /live/<id>/status?since=N           録画の状態・セッション・セグメント(N 個目から)
  GET  /live/<id>/segments?start=&end=    区間(UTC の時刻)にかかるセグメント(uri・pdt・dur)と欠け・録画済みの最後の時刻(P2 の書き出し)
  GET  /live/<id>/index.m3u8              全セッションをつないだ再生リスト(Cache-Control: no-cache)
  GET  /live/<id>/<session>/<seg>.ts       セグメント
  GET  /live/config ・ POST /live/config {folder}  録画の置き場所(録画中は変えられない)
  POST /live/quit  {}                      録画中でなければ終わる(録画中なら 409)

作業データ(%LOCALAPPDATA%\\youtube-tools\\recorder\\。YTT_DATA_DIR=inplace なら recorder\\data\\): token.txt・settings.json(置き場所)・logs\\recorder.log。
録画そのものは置き場所(既定 E:\\Video\\live-rec\\)。ドライブが無ければ作業データの中へ逃がさず、画面で案内する。
"""
import argparse
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.append(ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from ytt_core import datadir, fsio, httpsec  # noqa: E402
import rec_core  # noqa: E402

APP_ID = "ytt-recorder"
VERSION = "0.3.1"         # 録画の部品の版の正はここ1か所(README.txt の見出しもそろえる。入口の「調子」が動いている版と比べる)
DEFAULT_PORT = 8730       # 入口 8700〜・文字起こし 8775〜・スタジオ 8800〜・cut2resolve 8810〜 と重ならない。録画元の一覧の URL に書くので、使用中でも次の番号へずらさない
TOKEN_HEADER = "Authorization"
BODY_MAX = 16 * 1024
LOG_MAX = 1024 * 1024
LIVE_RE = re.compile(r"^/live/([^/]+)(?:/(.*))?\Z")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}\Z")


def data_dir(arg=None):
    """作業データの置き場所(token・設定・記録)。ytt_core.datadir の規則(YTT_DATA_DIR=inplace なら recorder\\data)"""
    if arg:
        return os.path.abspath(arg)
    return datadir.locate("recorder", legacy_dir=os.path.join(HERE, "data"))


def load_token(ddir):
    """合言葉(無ければ作る)。入口は同じファイルを読む(home/live.py)"""
    p = os.path.join(ddir, "token.txt")
    try:
        with open(p, "r", encoding="ascii") as f:
            t = f.read().strip()
        if TOKEN_RE.match(t):
            return t
    except (OSError, UnicodeError):
        pass
    t = secrets.token_urlsafe(32)
    fsio.atomic_write(p, t.encode("ascii"))
    return t


def read_settings(ddir):
    try:
        with open(os.path.join(ddir, "settings.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_folder(ddir, folder):
    """置き場所を設定(settings.json)に覚える(次の起動でも同じ置き場所)"""
    s = read_settings(ddir)
    s["folder"] = folder
    fsio.atomic_write(os.path.join(ddir, "settings.json"), json.dumps(s, ensure_ascii=False, indent=1).encode("utf-8"))


def clean_folder(f):
    """置き場所: PC の中の絶対パスだけ(ネットワークのパスは断る)。-> 整えたパス(RecError)"""
    if not isinstance(f, str):
        raise rec_core.RecError("置き場所は文字で指定してください")
    f = f.strip().strip('"').strip()
    if not f or len(f) > 260 or any(ord(c) < 32 for c in f):
        raise rec_core.RecError("置き場所の指定が正しくありません")
    if fsio.is_network_path(f):
        raise rec_core.RecError("ネットワーク上のフォルダは選べません(この PC のドライブのフォルダを指定してください)")
    if not os.path.isabs(f) or (os.name == "nt" and not re.match(r"^[A-Za-z]:[\\/]", f)):
        raise rec_core.RecError("置き場所は E:\\… のような絶対パスで指定してください")
    return os.path.normpath(f)


def make_logger(path, echo=True):
    lock = threading.Lock()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.getsize(path) > LOG_MAX:
            os.replace(path, path[:-4] + ".old.log")
    except OSError:
        pass

    def log(msg):
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        with lock:
            if echo:
                try:
                    print(line, flush=True)
                except (OSError, ValueError):
                    pass
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
    return log


def raise_priority():
    """この部品(HTTP の応答も含む)を「通常より上」に。子(ffmpeg・streamlink)は起動するときに指定する(rec_core.PRIORITY)"""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00008000)   # ABOVE_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "ytt-recorder"
    timeout = 30

    def log_message(self, fmt, *args):   # アクセスは記録しない(再生中は数秒ごとに来る)
        pass

    def _head(self, code, ctype, size, cache):
        """応答の見出し。-> 本文を送るか(HEAD なら送らない)"""
        self.send_response(code)
        for k, v in (("Content-Type", ctype), ("Content-Length", str(size)), ("X-Content-Type-Options", "nosniff"), ("Cache-Control", cache)):
            self.send_header(k, v)
        self.end_headers()
        return self.command != "HEAD"

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", cache="no-store"):
        if self._head(code, ctype, len(body), cache):
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _fail(self, code, err, msg):
        self._json(code, {"error": err, "message": msg})

    def _missing(self, msg="その場所はありません"):
        self._fail(404, "not_found", msg)

    def _drain(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= 1024 * 1024:
                self.rfile.read(n)
        except (OSError, ValueError):
            pass

    def _guard(self, path):
        """Host(DNS rebinding)・ブラウザからの直接の要求・合言葉。通らなければ応答して False"""
        h = self.headers
        if not httpsec.host_ok(h, self.server.allowed_hosts):
            err = ("host", "forbidden")
        elif h.get("Origin") is not None or h.get("Sec-Fetch-Site") is not None:   # ブラウザは入口を通す
            err = ("browser", "録画の部品はブラウザから直接は使えません(ホームの画面から使ってください)")
        elif path == "/api/ping" or hmac.compare_digest((h.get(TOKEN_HEADER) or "").encode("utf-8", "replace"),
                                                        ("Bearer " + self.server.token).encode("ascii")):
            return True
        else:
            err = ("token", "合言葉が違います")
        self._drain()
        self._fail(403, *err)
        return False

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._guard(u.path):
            return
        rec = self.server.rec
        if u.path == "/api/ping":
            return self._json(200, {"app": APP_ID, "version": VERSION})
        if u.path == "/live/list":
            return self._json(200, dict(rec.overview(), version=VERSION))
        if u.path == "/live/config":
            return self._json(200, {"folder": rec.folder, "version": VERSION})
        m = LIVE_RE.match(u.path)
        if not m:
            return self._missing()
        rest = m.group(2) or ""
        q = urllib.parse.parse_qs(u.query)
        try:
            r = rec.get(m.group(1))
            if rest == "status":
                return self._json(200, r.summary(detail=True, since=(q.get("since") or ["0"])[0]))
            if rest == "segments":   # 区間にかかるセグメントと欠け(入口の書き出しの「録画待ち」と「取得」。P2)
                return self._json(200, r.segments_in((q.get("start") or [""])[0], (q.get("end") or [""])[0]))
        except rec_core.RecError as e:
            return self._fail(e.code, e.kind, str(e))
        if rest == "index.m3u8":
            return self._send(200, r.playlist().encode("utf-8"), "application/vnd.apple.mpegurl", "no-cache")
        p = r.segment_path(*rest.split("/")) if rest.count("/") == 1 else None
        return self._file(p) if p else self._missing()

    def _file(self, path):
        try:
            f = open(path, "rb")
        except OSError:
            return self._missing()
        with f:
            if self._head(200, "video/mp2t", os.fstat(f.fileno()).st_size, "private, max-age=86400"):   # 書き終えたセグメントは変わらない
                try:
                    shutil.copyfileobj(f, self.wfile, 256 * 1024)
                except OSError:   # 見る側が切った(ConnectionError も OSError)
                    pass

    do_HEAD = do_GET

    def _body(self):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self._drain()
            self._fail(415, "content_type", "application/json だけを受け付けます")
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > BODY_MAX:
            self._drain()
            self._fail(413, "size", "本文の大きさが正しくありません")
            return None
        try:
            obj = json.loads((self.rfile.read(n) if n else b"{}").decode("utf-8"))
        except (OSError, ValueError, UnicodeError):
            self._fail(400, "json", "JSON が読めません")
            return None
        if not isinstance(obj, dict):
            self._fail(400, "json", "JSON のオブジェクトを送ってください")
            return None
        return obj

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if not self._guard(u.path):
            return
        body = self._body()
        if body is None:
            return
        rec = self.server.rec
        try:
            if u.path == "/live/start":
                return self._json(200, {"recording": rec.start(body.get("url"), body.get("quality") or rec_core.DEFAULT_QUALITY, body.get("title") or "")})
            if u.path == "/live/config":
                folder = clean_folder(body.get("folder"))
                if os.path.normcase(folder) != os.path.normcase(rec.folder or ""):
                    rec.set_folder(folder)
                    save_folder(self.server.ddir, folder)
                    rec.log("録画の置き場所を %s にしました" % folder)
                return self._json(200, {"folder": rec.folder, "version": VERSION})
            if u.path == "/live/quit":
                if rec.busy():
                    return self._fail(409, "busy", "録画中なので終わりません(録画を止めてから)")
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.request_quit, daemon=True).start()
                return
            m = LIVE_RE.match(u.path)
            if m and m.group(2) == "stop":
                return self._json(200, {"recording": rec.stop(m.group(1))})
            if m and m.group(2) == "delete":   # P4 の「録画を自動で消す」(入口の中の処理だけが呼ぶ。入口の中継は通さない)
                return self._json(200, {"ok": True, "deleted": rec.delete(m.group(1))})
        except rec_core.RecError as e:
            return self._fail(e.code, e.kind, str(e))
        except OSError as e:
            return self._fail(500, "write", "書けませんでした: %s" % (e.strerror or e.__class__.__name__))
        return self._missing("その操作はありません")


class Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def __init__(self, addr, rec, token, ddir, allowed_hosts):
        super().__init__(addr, Handler)
        self.rec, self.token, self.ddir = rec, token, ddir
        self.allowed_hosts = set(allowed_hosts)

    def server_bind(self):   # Windows は使用中のポートにも bind できてしまうので独占する(入口と同じ)
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def request_quit(self):
        time.sleep(0.2)
        self.shutdown()


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="recorder.py", description="配信を HLS で録画する部品(線 D)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1", help="待ち受けるアドレス(1台のときは 127.0.0.1 のまま。2台のときは LAN のアドレス)")
    ap.add_argument("--allow-host", action="append", default=[], help="Host ヘッダーで許す名前(例 192.168.1.20:8730。2台のとき)")
    ap.add_argument("--folder", default="", help="録画の置き場所(指定すると設定に覚える。既定 %s)" % rec_core.DEFAULT_FOLDER)
    ap.add_argument("--data-dir", default="", help="作業データ(token・設定・記録)の場所(テスト用)")
    ap.add_argument("--source", default=os.environ.get("YTT_RECORDER_SOURCE") or "streamlink", choices=("streamlink", "direct"),
                    help="取得のしかた(direct = HLS の URL を直接 ffmpeg に渡す。テスト用)")
    ap.add_argument("--hls-time", type=int, default=rec_core.HLS_TIME)
    ap.add_argument("--backoff", default="", help="繋ぎ直すまでの秒(例 5,10,30。テスト用)")
    ap.add_argument("--idle-end", type=int, default=rec_core.IDLE_END)
    ap.add_argument("--stall-sec", type=int, default=rec_core.STALL_SEC)
    ap.add_argument("--quiet", action="store_true", help="黒い画面に記録を出さない")
    a = ap.parse_args(argv)
    if not 1024 <= a.port <= 65535:
        ap.error("--port は 1024〜65535")
    return a


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    a = parse_args(sys.argv[1:] if argv is None else argv)
    ddir = data_dir(a.data_dir)
    os.makedirs(ddir, exist_ok=True)
    log = make_logger(os.path.join(ddir, "logs", "recorder.log"), echo=not a.quiet)
    saved = read_settings(ddir).get("folder")
    try:
        folder = clean_folder(a.folder or saved or rec_core.DEFAULT_FOLDER)
    except rec_core.RecError as e:
        log("置き場所の指定が正しくないので既定を使います: %s" % e)
        folder = rec_core.DEFAULT_FOLDER
    if a.folder and saved != folder:
        try:
            save_folder(ddir, folder)
        except OSError:
            pass
    backoff = tuple(int(x) for x in a.backoff.split(",") if x.strip().isdigit())   # 空なら既定(rec_core.BACKOFF)
    rec = rec_core.Recorder(folder, source=a.source, hls_time=a.hls_time, backoff=backoff,
                            idle_end=a.idle_end, stall_sec=a.stall_sec, log=log)
    token = load_token(ddir)
    allowed = httpsec.allowed_hosts(a.port) | set(a.allow_host)
    try:
        srv = Server((a.host, a.port), rec, token, ddir, allowed)
    except OSError as e:
        log("ポート %d で待ち受けられません(録画の部品がもう動いているかもしれません): %s" % (a.port, e))
        return 2
    raise_priority()
    log("録画の部品 v%s: http://%s:%d/(置き場所 %s・取得 %s)" % (VERSION, a.host, a.port, folder, a.source))
    fs = rec_core.folder_state(folder)
    if not fs["ok"]:
        log("※ " + fs["message"])
    if not rec.streamlink_ok():
        log("※ streamlink が見つかりません(setup\\install.bat で入れてください)")
    resumed = rec.load()   # 起動時の復旧(録画中だった物は新しいセッションで続ける)
    if resumed:
        log("前回の録画を %d 本続けます" % len(resumed))

    def stop(_sig, _frame):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, stop)
            except (OSError, ValueError):
                pass
    th = threading.Thread(target=srv.serve_forever, daemon=True, name="recorder-http")
    th.start()
    try:
        while th.is_alive():
            th.join(0.5)
    except KeyboardInterrupt:
        srv.shutdown()
    finally:
        rec.close()   # 録画中の物は状態をそのままに止める(次の起動で続ける)
        srv.server_close()
        log("録画の部品を終了しました")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
