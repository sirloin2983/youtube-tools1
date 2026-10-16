# -*- coding: utf-8 -*-
"""友人の玄関(F2-1・F2-2。notes:plan/f1-friend-requirements.md の A-1・B)。友人の PC の 2 つ目の玄関(ユーザーの PC は src/app/server.py)。

    python src/friendapp/server.py [--port 8720] [--no-open]

- ② を同じプロセスで起こす(friendapp/engine.py。③ human・入口 app は読まない = 層の表 dev/layer_map.py の friendapp)
- 画面は /friend/ の受信箱 1 枚(friendapp/ui/。ui-kit)。窓 = Edge のアプリの形(ytt/appwindow。無ければ既定のブラウザ)
- 安全はユーザーの PC の入口と同じ: Host(DNS rebinding)・Origin・Sec-Fetch-Site の検査(ytt/httpsec)と、書き込み系の合言葉(起動ごと。画面へは meta ytt-token)
- 1 つの作業データに ② は 1 つ(flow/placement の .flow.lock)。もう動いていれば、その窓を開き直して終わる(終了コード 0)
- 古い部品(%LOCALAPPDATA%/youtube-tools のモデル)は、起動のあと裏で写して確かめ、古い方を消す(A-16。friendapp/oldcopy)。その間は送れない
- 窓を閉じても仕事は続ける。画面からの問い合わせが CLOSE_IDLE 秒来ず、② の待ち・実行中が 0 になったら自分で終わる(A-13 の一時の形。
  状態の窓・縮小版のツールバーは F2-4 の起動役)。[すべて止めて終了] は確認なしですぐ止める(待ちは残り、次に開いたとき続きから = 4-6)
口(書き込み系は合言葉。全部 JSON):
  GET  /api/ping                          {app, version}
  GET  /api/friend/inbox                  受信箱の行・前回の値・保存先・空き容量で止めているか・準備中か・片付けの知らせ
  GET  /api/friend/peek?url=              配信の題・チャンネル名と配信者の推し
  GET  /api/friend/media?id=&n=           組のまとめ動画(Range つき)
  POST /api/friend/send                   送る(friendapp/api.py の欄)
  POST /api/friend/decide {id, names, verdict: keep|reject}   受け取る / 要らない(names 空 = その行の決めていない物全部)
  POST /api/friend/retry {id}・remove {id}・cancel {id}        失敗の行の [もう一度送る]・[消す]・送った行を止める
  POST /api/friend/open {what: saved}     受け取るの保存先をエクスプローラーで開く
  POST /api/friend/notice-seen            片付けの知らせを見た
  POST /api/shutdown                      すべて止めて終了
  GET  /api/flow/status・POST /api/flow/submit・POST /api/flow/cancel   ② の口(ユーザーの PC の入口と同じ形)
  POST api/ytt/streamer-colors・client-log   ui-kit の共通の口(配信者の名簿・画面のエラーの記録)
"""
import argparse
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import placement as _placement, runqueue as _runqueue  # noqa: E402
from ytt import appwindow as _appwindow, colors as _colors, fsio as _fsio, httpsec, version as _version  # noqa: E402
from friendapp import api as _api, inbox as _inbox, oldcopy as _oldcopy, places as _places  # noqa: E402

APP_ID = "ytt-friend"
DEFAULT_PORT = 8720
PORT_TRIES = 20
MAX_BODY = 256 * 1024
TOKEN_HEADER = "X-YTT-Token"
TOKEN_FAIL = {"error": "token", "message": "画面を開き直してから、もう一度操作してください(合言葉が違います)"}
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UIKIT_DIR = os.path.join(SRC, "ui-kit")
STATIC = {"/friend/": ("friend.html", UI_DIR), "/friend/index.html": ("friend.html", UI_DIR), "/friend/friend.js": ("friend.js", UI_DIR),
          "/friend/friend.css": ("friend.css", UI_DIR), "/friend/ui-kit.js": ("ui-kit.js", UIKIT_DIR), "/friend/ui-kit.css": ("ui-kit.css", UIKIT_DIR)}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
PAGES = ("/", "/friend/", "/friend/index.html")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://i.ytimg.com; media-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CLOSE_IDLE = 120          # 画面からの問い合わせがこの秒数来ず、仕事も無ければ自分で終わる(窓を閉じた = A-13 の一時の形)
SWEEP_EVERY = 3600        # 受信箱の 3 日の片付けを見る間隔(秒)
SAVE_DEFAULT = ("Videos", "受け取ったパック")   # 受け取るの保存先の既定(%USERPROFILE% の下。⚙ で選ぶのは F2-5)
SAVE_FILE = "save-dir.json"
# 写したあと古い部品を消すか(A-16)。今の送るアプリ(C#)が F2-7 まで同じ古い作業データのモデルを使うので、それまでは写すだけ(仮・AI。F2-7 で True)
REMOVE_OLD = False
CLIENT_LOG_MAX = 512 * 1024


def save_dir(friend_dir, env=None):
    """受け取るの保存先(<玄関>/save-dir.json の dir か、%USERPROFILE%/Videos/受け取ったパック)"""
    d = _fsio.read_json_or(os.path.join(friend_dir, SAVE_FILE), {}, kind=dict).get("dir")
    if isinstance(d, str) and os.path.isabs(d):
        return d
    env = os.environ if env is None else env
    return os.path.join(env.get("USERPROFILE") or os.path.expanduser("~"), *SAVE_DEFAULT)


def inject_meta(body, token):
    tag = ('<meta name="ytt-token" content="%s"><meta name="ytt-version" content="%s">' % (token, _version.VERSION)).encode("ascii")
    i = body.find(b"</head>")
    return body[:i] + tag + body[i:] if i >= 0 else tag + body


class Handler(BaseHTTPRequestHandler):
    server_version = APP_ID
    timeout = 30

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        httpsec.send(self, code, body, ctype, extra)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, code, err, message):
        self._json(code, {"error": err, "message": message})

    def _host_ok(self):
        return httpsec.host_ok(self.headers, self.server.allowed_hosts)

    # ------------------------------------------------------------ GET
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        path = u.path
        if not (self._host_ok() and (httpsec.fetch_site_ok(self.headers) or httpsec.navigation_ok(self.headers, path, PAGES))):
            return self._send(403, b"forbidden")
        if path in ("/", "/friend"):
            return self._send(302, b"", extra={"Location": "/friend/"})
        if path in STATIC:
            name, base = STATIC[path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._send(404, b"not found")
            page = name.endswith(".html")
            if page:
                body = inject_meta(body, self.server.token)
            return self._send(200, body, TYPES[os.path.splitext(name)[1]],
                              {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"} if page else None)
        q = urllib.parse.parse_qs(u.query)
        path = path[len("/friend"):] if path.startswith("/friend/api/") else path
        app = self.server.app
        if path == "/api/ping":
            return self._json(200, {"app": APP_ID, "version": _version.VERSION})
        if path == "/api/friend/inbox":
            app.seen = time.time()
            out = app.api.view()
            out.update(prep=app.prep, notice=app.notice())
            return self._json(200, out)
        if path == "/api/friend/peek":
            try:
                return self._json(200, app.api.peek((q.get("url") or [""])[0][:300]))
            except _api.FormError as e:
                return self._fail(400, "bad_url", str(e))
        if path == "/api/friend/media":
            r = app.inbox.row((q.get("id") or [""])[0])
            try:
                n = int((q.get("n") or ["0"])[0])
            except ValueError:
                n = 0
            g = next((g for g in (r or {}).get("groups") or [] if g["n"] == n), None)
            p = g and g.get("preview")
            if not p or not os.path.isfile(p) or not _fsio.is_inside(p, app.places["friend"]):
                return self._fail(404, "not_found", "まとめ動画がまだありません")
            try:
                return httpsec.send_file(self, p, "video/mp4")
            except OSError:
                return self._fail(404, "not_found", "まとめ動画を読めませんでした")
        if path == "/api/flow/status":
            eng = app.engine
            return self._json(200, eng.queue.status() if eng else {"idle": True, "runs": [], "preparing": True})
        return self._fail(404, "not_found", "その操作はありません")

    # ------------------------------------------------------------ POST
    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        h = self.headers
        if not (self._host_ok() and httpsec.origin_ok(h, self.server.allowed_hosts) and httpsec.fetch_site_ok(h)):
            httpsec.drain_body(h, self.rfile)
            return self._send(403, b"forbidden")
        if not httpsec.token_ok(h, self.server.token, TOKEN_HEADER):
            httpsec.drain_body(h, self.rfile)
            return self._json(403, TOKEN_FAIL)
        try:
            body = httpsec.read_json_body(self, MAX_BODY, empty_ok=True)
        except httpsec.BodyError:
            return self._fail(400, "json", "JSON が読めません")
        path = u.path[len("/friend"):] if u.path.startswith("/friend/api/") else u.path
        try:
            return self._post(path, body)
        except _api.FormError as e:
            return self._fail(400, "bad_request", str(e))
        except KeyError:
            return self._fail(404, "not_found", "その行はもうありません(画面を読み込み直してください)")
        except ValueError as e:
            return self._fail(409, "refused", str(e))

    def _post(self, path, body):
        app = self.server.app
        if path == "/api/friend/send":
            return self._json(200, {"ok": True, "row": app.api.send(body)})
        if path == "/api/friend/decide":
            got = app.inbox.decide(str(body.get("id") or ""), [n for n in body.get("names") or [] if isinstance(n, str)], body.get("verdict"))
            return self._json(200, {"ok": not got["errors"], "done": got["done"], "errors": got["errors"]})
        if path == "/api/friend/retry":
            return self._json(200, {"ok": True, "row": app.api.retry(str(body.get("id") or ""))})
        if path == "/api/friend/remove":
            app.inbox.remove(str(body.get("id") or ""))
            return self._json(200, {"ok": True})
        if path == "/api/friend/cancel":
            return self._json(200, {"ok": True, "result": app.api.cancel(str(body.get("id") or ""))})
        if path == "/api/friend/open":
            d = app.places["save"]()
            os.makedirs(d, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(d)   # noqa: S606(玄関が決めた保存先だけ。画面からパスは受け取らない)
            return self._json(200, {"ok": True, "dir": d})
        if path == "/api/friend/notice-seen":
            if app.catalog:
                _oldcopy.mark_notice_shown(app.catalog)
            return self._json(200, {"ok": True})
        if path == "/api/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=app.shutdown, name="friend-shutdown", daemon=True).start()
            return None
        if path == "/api/flow/submit":
            if app.engine is None:
                return self._fail(409, "preparing", "準備中です")
            try:
                return self._json(200, {"run": app.engine.queue.submit(body.get("envelope"), body.get("spec"))})
            except _runqueue.SpecVersionError as e:
                return self._fail(400, "spec_version", str(e))
            except _runqueue.BadSpecError as e:
                return self._fail(400, "bad_spec", str(e))
        if path == "/api/flow/cancel":
            if app.engine is None:
                return self._fail(409, "preparing", "準備中です")
            return self._json(200, {"result": app.engine.queue.cancel(str(body.get("id") or ""))})
        if path == "/api/ytt/streamer-colors":
            return self._json(200, streamer_colors(body))
        if path == "/api/ytt/client-log":
            _fsio.append_line(os.path.join(app.places["friend"], "logs", "client-errors.jsonl"),
                              json.dumps(body, ensure_ascii=False)[:4000], CLIENT_LOG_MAX)
            return self._json(200, {"ok": True})
        return self._fail(404, "not_found", "その操作はありません")


def _entry(e):
    return {k: e[k] for k in ("name", "en", "hex", "group", "mine")}


def streamer_colors(body):
    """ui-kit の配信者の欄(UIKit.streamer)の口。形はユーザーの PC の入口(src/app/server.py の streamer_colors)と同じ"""
    entries = _colors.load()
    if isinstance(body.get("names"), list):
        names = list(dict.fromkeys(n.strip()[:_colors.NAME_MAX] for n in body["names"][:60] if isinstance(n, str) and n.strip()))
        return {"ok": True, "matches": {n: (_entry(m) if m else None) for n, m in ((n, _colors.lookup(n, entries)["match"]) for n in names)}}
    q = body.get("q") if isinstance(body.get("q"), str) else ""
    r = _colors.lookup(q[:_colors.NAME_MAX], entries)
    return {"ok": True, "match": _entry(r["match"]) if r["match"] else None, "candidates": [_entry(e) for e in r["candidates"]],
            "items": [_entry(e) for e in entries] if body.get("all") is True else []}


class Server(httpsec.ExclusiveServer):
    def __init__(self, addr, app):
        super().__init__(addr, Handler)
        self.app = app
        self.token = secrets.token_urlsafe(24)
        self.allowed_hosts = httpsec.allowed_hosts(self.server_address[1])


class FriendApp:
    """玄関の中身(サーバーと別に作れる = テストは make_engine を差し替える)"""

    def __init__(self, places, log=None, make_engine=None, clock=time.time):
        self.places, self.clock = places, clock
        self.log = log or (lambda msg: None)
        self.inbox = _inbox.Inbox(os.path.join(places["friend"], "inbox.json"), places["outbox"], places["save"],
                                  lambda: places["cases"], clock=clock, log=self.log)
        self.engine = None
        self.prep = {"state": "starting", "message": "準備しています"}
        self.api = _api.Api(places, self.inbox, lambda: self.engine, clock=clock)
        self.make_engine = make_engine
        self.catalog = os.path.join(places["friend"], "old-copy.json")
        self.seen = clock()
        self.closing = threading.Event()
        self.server = None

    def notice(self):
        n = _oldcopy.notice(self.catalog) if os.path.isfile(self.catalog) else None
        return {"freedGB": round(n["bytes"] / 1e9, 1)} if n and n.get("bytes") else None

    def prepare(self, old_root=None):
        """裏の糸: 古い部品を写す(A-16)→ ② を起こす"""
        try:
            fetch = self.places.get("fetch")
            if old_root and fetch and os.path.isfile(fetch) and os.path.isdir(old_root):
                self.prep = {"state": "copying", "message": "前のアプリの部品(モデルなど)を写しています。終わるまで送れません"}
                got = _oldcopy.migrate(fetch, old_root, self.places["data"], self.catalog, log=self.log, cancelled=self.closing.is_set,
                                       remove_old=REMOVE_OLD)
                self.log("古い部品: 写した %d 件・消した %d 件(%.1f GB)" % (got["copied"], got["deleted"], got["freed"] / 1e9))
            if self.closing.is_set():
                return
            self.engine = self.make_engine(self.places, self.inbox, self.log)
            self.prep = {"state": "ready", "message": ""}
        except Exception as e:   # 起こせなくても画面は出す(理由を見せる)
            self.log("② を起こせませんでした: %s %s" % (e.__class__.__name__, str(e)[:300]))
            self.prep = {"state": "error", "message": "処理の部品を起動できませんでした(%s)。アプリを開き直してください" % e.__class__.__name__}

    def busy(self):
        eng = self.engine
        if eng is None:
            return self.prep["state"] in ("starting", "copying")
        st = eng.queue.status()
        return not st["idle"] or bool(eng._previews)

    def watch(self):
        """3 日の片付け(SWEEP_EVERY ごと)と、窓を閉じて仕事も無くなったら終わる(CLOSE_IDLE)"""
        last_sweep = 0
        while not self.closing.wait(10):
            now = self.clock()
            if now - last_sweep >= SWEEP_EVERY and self.engine is not None:
                last_sweep = now
                try:
                    n = self.inbox.sweep()
                    if n:
                        self.log("3 日決めなかった %d 本を自動で要らないにしました" % n)
                except Exception as e:   # 片付けで玄関を止めない
                    self.log("受信箱の片付けに失敗しました: %s" % e.__class__.__name__)
            if now - self.seen >= CLOSE_IDLE and not self.busy():
                self.log("窓が閉じていて仕事も無いので終わります")
                self.shutdown()
                return

    def shutdown(self):
        if self.closing.is_set():
            return
        self.closing.set()
        if self.engine is not None:
            self.engine.close()
        if self.server is not None:
            self.server.shutdown()


def make_logger(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = threading.Lock()

    def log(msg):
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        with lock:
            _fsio.append_line(path, line, 2 * 1024 * 1024)
    return log


def _default_engine(places, inbox, log):
    from friendapp import engine as _engine   # ② の部品は起動のあとに(画面を先に出す)
    return _engine.Engine(places, inbox, log=log)


def say(msg, log=None):
    """標準出力へ 1 行(pythonw で起こしたときは標準出力が無い = ログだけ)"""
    if log:
        log(msg)
    if sys.stdout is not None:
        print(msg, flush=True)


def open_window(friend_dir, url, log):
    op = _appwindow.Opener(friend_dir, _fsio.atomic_write, log=log)
    op.force_mode = "app"
    return op.open_start(url)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="friendapp/server.py", description="友人の受信箱(送る → 作っている → 届く → 決める)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-open", action="store_true", help="窓を開かない")
    a = ap.parse_args(argv)
    pl = _places.setup()
    pl["save"] = lambda: save_dir(pl["friend"])
    log = make_logger(os.path.join(pl["friend"], "logs", "friendapp.log"))
    info = _placement.lock_info(pl["data"])
    if info and info.get("port"):   # もう動いている = その窓を開き直して終わる
        url = "http://localhost:%d/friend/" % info["port"]
        if not a.no_open:
            open_window(pl["friend"], url, log)
        say("もう動いています: %s" % url)
        return 0
    app = FriendApp(pl, log=log, make_engine=_default_engine)
    srv = None
    for p in range(a.port, a.port + PORT_TRIES):
        try:
            srv = Server(("127.0.0.1", p), app)
            break
        except OSError:
            continue
    if srv is None:
        say("使えるポートがありません(%d〜%d)" % (a.port, a.port + PORT_TRIES - 1), log)
        return 1
    port = srv.server_address[1]
    try:
        handle = _placement.acquire(port=port, data_root=pl["data"])
    except _placement.LockBusy as e:
        srv.server_close()
        say("ほかの処理(%s)が同じ作業データを使っています。閉じてから開き直してください" % (getattr(e, "info", None) or {}).get("pid"), log)
        return 4
    app.server = srv
    url = "http://localhost:%d/friend/" % port
    log("友人の玄関 v%s: %s(作業データ %s)" % (_version.VERSION, url, pl["data"]))
    threading.Thread(target=app.prepare, args=(_places.old_data_root(),), name="friend-prepare", daemon=True).start()
    threading.Thread(target=app.watch, name="friend-watch", daemon=True).start()
    if not a.no_open:
        open_window(pl["friend"], url, log)
    say(json.dumps({"event": "ready", "port": port, "pid": os.getpid()}))
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
        srv.server_close()
        _placement.release(handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
