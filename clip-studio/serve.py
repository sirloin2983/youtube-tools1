#!/usr/bin/env python3
"""切り抜きスタジオ(ローカルサーバー・標準ライブラリのみ。外部ツール: ffmpeg、YouTube には yt-dlp)。

    python3 serve.py [開始ポート] [--no-open]

  ① 探す(配信ランキング)→ ② 解析(切り抜き候補の自動選定・バッチ)→ ③ 確認・書き出し(クリップマーカー)。
  エンドポイントは API.md を参照。127.0.0.1 にのみバインドし、Host / Origin / Sec-Fetch-Site を検査する。
"""
import http.client
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze  # noqa: E402
import batch as batch_mod  # noqa: E402
import common  # noqa: E402
import exporter  # noqa: E402
import handoff  # noqa: E402
import rank  # noqa: E402
import store as store_mod  # noqa: E402
import txlink  # noqa: E402
from common import ApiError, VID_RE, MEDIA_EXT, find_tool, redact  # noqa: E402
from ytt_core import datadir, httpsec, runtime as ytt_runtime  # noqa: E402  (common が ytt_core を読めるようにしてある)

APP_ID = "clip-studio"
SERVER_VERSION = "0.5.0"  # core.js 側の APP_VERSION と揃える
TOOL_ID = "studio"        # docs/pipeline.md の 4 のツールID(.runtime/studio.json)
handoff.TOOL.update(name=APP_ID, version=SERVER_VERSION)   # .clip.json の tool
CODE_DIR = common.CODE_DIR
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.css": "app.css", "/core.js": "core.js", "/settings.js": "settings.js", "/rank.js": "rank.js", "/queue.js": "queue.js", "/review.js": "review.js", "/review.css": "review.css", "/collab.js": "collab.js", "/ui-kit.css": "ui-kit.css", "/ui-kit.js": "ui-kit.js"}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}
PORT = 8800
BASE_PATH = "/"   # 画面の場所。入口の統合サーバーに取り込まれたときは "/studio/"(app/mount.py が prepare() で入れる)
ALLOWED_HOSTS = set()
MAX_BODY = 4 * 1024 * 1024
SOCKET_TIMEOUT = float(os.environ.get("STUDIO_SOCKET_TIMEOUT") or 60)   # 読み取りが止まった接続を閉じるまでの秒数
MEDIA_TYPES = {".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm", ".mov": "video/quicktime", ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
               ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".aac": "audio/aac", ".ts": "video/mp2t", ".flv": "video/x-flv"}

STORE = None
BATCH = None


def init(home=None):
    """データ置き場・ストア・キューを用意する(main と、テストから呼ぶ)。"""
    global STORE, BATCH
    if home:
        common.set_home(home)
    common.load_out_dir()
    STORE = store_mod.Store(common.p("data.json"))
    BATCH = batch_mod.Batch(STORE)
    return STORE, BATCH


def busy():
    return BATCH.is_busy() or exporter.is_busy()


def fetch_title(vid):
    """oEmbed(公開エンドポイント・キー不要)でタイトルだけ取得する。失敗時は空文字。接続先は固定で、IDは検証済み。"""
    if common.fake():
        return "疑似タイトル(%s)" % vid
    target = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote("https://www.youtube.com/watch?v=" + vid, safe="")
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers={"Accept": "application/json"}), timeout=8) as r:
            return str(json.loads(r.read(200000).decode("utf-8", "replace")).get("title", ""))[:120]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""


def api_state():
    key, source = common.get_api_key()
    fk = common.fake()
    d = {"hasKey": bool(key) or fk, "keySource": source, "fake": fk, "ffmpeg": bool(find_tool("ffmpeg")), "ytdlp": bool(find_tool("yt-dlp")) or fk,
         "outDir": common.get_out_dir(), "defaultOutDir": common.default_out_dir(), "dataDir": common.home(), "quota": rank.quota(),
         "env": common.env_state()}   # 起動時の環境チェック(道具の版・古い yt-dlp・出力先の空き容量など)。warnings は画面にそのまま出せる文
    warning, backup = STORE.take_warning()   # 起動時の data.json の問題は、最初の1回だけ知らせる
    if warning:
        d["dataWarning"], d["corruptBackup"] = warning, backup
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = "clip-studio"
    timeout = SOCKET_TIMEOUT

    # 安全検査の規則は ytt_core.httpsec に1か所(スタジオ・文字起こし・入口で共通)
    def _host_ok(self):          # DNS rebinding 対策
        return httpsec.host_ok(self.headers, ALLOWED_HOSTS)

    def _origin_ok(self):        # 他サイトからの書き込み(CSRF)対策。"http://" + 許可した Host と完全に一致するものだけ
        return httpsec.origin_ok(self.headers, ALLOWED_HOSTS)

    def _fetch_site_ok(self):    # 他サイトからのAPI消費(クォータ浪費)対策
        return httpsec.fetch_site_ok(self.headers)

    def _navigation_ok(self, path):
        """他のツールの画面のリンク(「他のツール」メニュー・?url=)でこの画面を開くのは許す。
        ポートが違うだけでもブラウザは Sec-Fetch-Site: same-site(localhost と 127.0.0.1 なら cross-site)を送るため、以前は 403 になっていた。
        画面を新しいタブで開くだけで、URL で処理は始まらない(docs/pipeline.md の 3)。API・静的ファイルは同じ画面からだけ。
        iframe への埋め込みは X-Frame-Options / frame-ancestors で拒否する(文字起こしツール・cut2resolve と同じ扱い)"""
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
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def _err(self, e):
        self._json(e.status, dict(e.extra or {}, error=e.code, message=e.message))

    def _read_json(self):
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._send(415, b"application/json only")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, b"bad length")
            return None
        if length <= 0 or length > MAX_BODY:
            self._send(413, b"invalid size")
            return None
        try:
            body = self.rfile.read(length)
        except OSError:   # 読み取りのタイムアウト・切断: 応答せずに閉じる
            self.close_connection = True
            return None
        try:
            obj = json.loads(body)
        except ValueError:
            self._send(400, b"invalid json")
            return None
        if not isinstance(obj, dict):
            self._send(400, b"object required")
            return None
        return obj

    def _guard(self, fn, *a):
        try:
            return fn(*a)
        except ApiError as e:
            return self._err(e)
        except OSError as e:   # 何が起きたかを具体的に返す(パスはローカルの画面にだけ出る)。詳細は studio-errors.log
            common.log_failure("API %s %s" % (self.command, self.path.split("?", 1)[0]), e)
            msg = common.permission_message(e) if isinstance(e, PermissionError) else \
                "ファイルの読み書きに失敗しました(%s)。ディスクの空き・ドライブの接続を確認してください" % (e.strerror or e.__class__.__name__)
            return self._json(500, {"error": "write", "message": msg})
        except Exception as e:   # 想定外でもサーバーは落とさない(詳細は伏せる)
            sys.stderr.write("internal error: %s %s\n" % (e.__class__.__name__, redact(str(e))[:200]))
            return self._json(500, {"error": "internal", "message": "内部エラーが発生しました"})

    # ---------- GET ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if not (self._host_ok() and (self._fetch_site_ok() or self._navigation_ok(u.path))):
            return self._send(403, b"forbidden")
        q = urllib.parse.parse_qs(u.query)
        arg = lambda k: (q.get(k) or [""])[0]
        if u.path in STATIC:
            fn = os.path.join(CODE_DIR, STATIC[u.path])
            try:
                with open(fn, "rb") as f:
                    body = f.read()
                page = fn.endswith(".html")
                return self._send(200, body, STATIC_TYPES[os.path.splitext(fn)[1]],
                                  httpsec.PAGE_HEADERS if page else None)
            except OSError:
                return self._send(404, b"not found")
        if u.path == "/media":
            return self._guard(self._media, arg("id"))
        routes = {
            "/api/ping": lambda: {"app": APP_ID, "version": SERVER_VERSION},
            "/api/siblings": lambda: handoff.siblings(TOOL_ID, PORT, self_path=BASE_PATH),
            "/api/state": api_state,
            "/api/settings": lambda: {"settings": STORE.get_ui()},
            "/api/rank/registry": rank.get_registry,
            "/api/rank/search": lambda: rank.get_search(arg("id")),
            "/api/queue": BATCH.snapshot,
            "/api/videos": lambda: {"videos": STORE.list()},
            "/api/video": lambda: self._video(arg("id")),
            "/api/transcripts": lambda: txlink.for_video(STORE.get(arg("id"))[0]),   # 書き出したマークのセリフ(文字起こしツールのデータを読むだけ)
            "/api/title": lambda: self._title(arg("v")),
            "/api/export": lambda: exporter.job_public(exporter.get_job(arg("id"))),
            "/api/collab/groups": lambda: {"groups": STORE.list_groups()},
            "/api/collab/group": lambda: {"group": STORE.get_group(arg("id"))},
        }
        fn = routes.get(u.path)
        if fn is None:
            return self._send(404, b"not found")
        try:
            return self._json(200, fn())
        except ApiError as e:
            return self._err(e)
        except Exception as e:
            sys.stderr.write("internal error: %s %s\n" % (e.__class__.__name__, redact(str(e))[:200]))
            return self._json(500, {"error": "internal", "message": "内部エラーが発生しました"})

    @staticmethod
    def _video(vid):
        v, series = STORE.get(vid)
        return {"video": v, "series": series}

    @staticmethod
    def _title(v):
        if not VID_RE.match(v):
            raise ApiError("bad_request", "動画IDが正しくありません", 400)
        return {"title": fetch_title(v)}

    def _media(self, vid):
        """登録済みの file 動画だけを Range 対応で配信する。クライアントからパスは受け取らない。"""
        path = STORE.media_path(vid)
        real = os.path.realpath(path) if path else ""
        ext = os.path.splitext(real)[1].lower()
        if not real or ext not in MEDIA_EXT or not os.path.isfile(real):
            return self._send(404, b"not found")
        size = os.path.getsize(real)
        a, b, code = 0, size - 1, 200
        m = re.match(r"^bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                a = int(m.group(1))
                b = int(m.group(2)) if m.group(2) else size - 1
            else:
                a = max(0, size - int(m.group(2)))
            b = min(b, size - 1)
            if a > b or a >= size:
                return self._send(416, b"", extra={"Content-Range": "bytes */%d" % size})
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", MEDIA_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(real, "rb") as f:
                f.seek(a)
                left = b - a + 1
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    # ---------- POST / PUT ----------
    def _write_guard(self):
        if not (self._host_ok() and self._fetch_site_ok() and self._origin_ok()):
            self._send(403, b"forbidden")
            return False
        return True

    def do_POST(self):
        if not self._write_guard():
            return
        path = self.path.split("?", 1)[0]
        if path not in POST_ROUTES:
            return self._send(404, b"not found")
        obj = self._read_json()
        if obj is None:
            return
        self._guard(lambda: self._json(200, POST_ROUTES[path](obj)))

    def do_PUT(self):
        if not self._write_guard():
            return
        path = self.path.split("?", 1)[0]
        if path not in PUT_ROUTES:
            return self._send(404, b"not found")
        obj = self._read_json()
        if obj is None:
            return
        self._guard(lambda: self._json(200, PUT_ROUTES[path](obj)))

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), redact(fmt % args)))


# ---------- 書き込み系のルート(引数は検査前の JSON オブジェクト) ----------
def _open_video(o):
    if o.get("kind") == "file":
        src = analyze.validate_source({"kind": "file", "path": o.get("path")})
        return {"video": STORE.ensure(src, probe=True)}
    src = analyze.validate_source({"kind": "youtube", "url": o.get("url")})
    return {"video": STORE.ensure(src)}


def _video_delete(o):
    vid = str(o.get("id") or "")
    if not STORE.has(vid):
        raise ApiError("not_found", "動画が見つかりません", 404)
    if exporter.is_busy_for(vid):
        raise ApiError("busy", "書き出し中は削除できません。終わってから削除してください", 409)
    if not BATCH.cancel_video(vid):   # 待ち item は取り除き、実行中の解析は中止してから削除
        raise ApiError("busy", "解析を中止しています。少し待ってからもう一度削除してください", 409)
    if not STORE.delete(vid):
        raise ApiError("not_found", "動画が見つかりません", 404)
    return {"ok": True}


def _put_video(o):
    return {"ok": True, "video": STORE.put_video(o.get("id"), o.get("title"), o.get("marks"), o.get("baseRev") if "baseRev" in o else None)}


def _outdir(o):
    return {"ok": True, "outDir": common.set_out_dir(o.get("path"), busy), "defaultOutDir": common.default_out_dir()}


def _config(o):
    return {"ok": True, "hasKey": bool(common.set_api_key(o.get("apiKey")) or common.fake())}


def _settings(o):
    if "section" in o:   # {section, value}: 1つの節だけ(画面はこちらを使う)。{settings}: 全体の置き換え(従来どおり)
        STORE.set_ui_section(o.get("section"), o.get("value"))
    else:
        STORE.set_ui(o.get("settings"))
    return {"ok": True}


def _put_registry(o):
    return rank.put_registry(o)


def _export(o):
    spec = exporter.build_spec(STORE, o)
    return exporter.job_public(exporter.start_job(spec, STORE.mark_exported))


def _export_cancel(o):
    exporter.cancel(o.get("id"))
    return {"ok": True}


def _collab_create(o):
    return {"group": STORE.create_group(o.get("videoIds"), o.get("name"), o.get("base"))}


def _collab_add(o):
    return {"group": STORE.add_members(o.get("id"), o.get("videoIds"))}


def _collab_remove(o):
    g = STORE.remove_member(o.get("id"), o.get("videoId"))
    return {"group": g, "deleted": g is None}


def _collab_delete(o):
    return {"ok": STORE.delete_group(o.get("id"))}


def _collab_anchor(o):
    return {"group": STORE.set_anchor(o.get("id"), o.get("videoId"), o.get("points"))}


POST_ROUTES = {
    "/api/rank/resolve": lambda o: rank.resolve(o.get("agency")),
    "/api/rank/import-official": lambda o: rank.import_official_channels(o.get("agency")),
    "/api/rank/search": rank.start_search,
    "/api/rank/search/cancel": lambda o: {"ok": rank.cancel_search(o.get("id"))},
    "/api/queue/add": lambda o: BATCH.add(o.get("items"), o.get("settings")),
    "/api/queue/cancel": lambda o: {"ok": BATCH.cancel(o.get("qid"))},
    "/api/queue/skipchat": lambda o: {"ok": BATCH.skipchat(o.get("qid"))},
    "/api/queue/retry": lambda o: {"ok": True, "qid": BATCH.retry(o.get("qid"))},
    "/api/queue/clear": lambda o: {"ok": True, "removed": BATCH.clear()},
    "/api/videos/open": _open_video,
    "/api/video/delete": _video_delete,
    "/api/export": _export,
    "/api/export/cancel": _export_cancel,
    "/api/collab/group": _collab_create,
    "/api/collab/group/add": _collab_add,
    "/api/collab/group/remove": _collab_remove,
    "/api/collab/group/delete": _collab_delete,
    "/api/collab/anchor": _collab_anchor,
}
PUT_ROUTES = {
    "/api/config": _config,
    "/api/outdir": _outdir,
    "/api/settings": _settings,
    "/api/rank/registry": _put_registry,
    "/api/video": _put_video,
}


# ---------- 起動 ----------
class StudioServer(ThreadingHTTPServer):
    """Windows では SO_REUSEADDR を付けると「他のアプリが使用中のポート」にも bind できてしまい、どちらに繋がるか分からなくなる
    (例: 8810 の cut2resolve と同じポートで起動してしまう)。Windows では使わず、代わりに SO_EXCLUSIVEADDRUSE で独占する。"""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def probe(port):
    """そのポートで動いているスタジオの版(スタジオでなければ None)。
    urllib ではなく http.client: 環境変数・Windows のプロキシ設定で 127.0.0.1 宛てがプロキシに回るのを避ける。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/api/ping", headers={"Host": "127.0.0.1:%d" % port})
        r = conn.getresponse()
        j = json.loads(r.read(4096).decode("utf-8", "replace")) if r.status == 200 else {}
        return str(j.get("version", "")) if isinstance(j, dict) and j.get("app") == APP_ID else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def _bound(srv):
    global PORT, ALLOWED_HOSTS
    p = srv.server_address[1]
    PORT = p
    ALLOWED_HOSTS = httpsec.allowed_hosts(p)
    return srv, p


def make_server(start_port):
    """start_port から20個のうち空いているポートで待ち受ける。同じ版が動いていれば (None, そのポート)。
    start_port=0 は OS に空きポートを選ばせる(テスト用: 他のテストと同時に走らせてもぶつからない)。"""
    if start_port == 0:
        return _bound(StudioServer(("127.0.0.1", 0), Handler))
    for p in range(start_port, start_port + 20):
        ver = probe(p)
        if ver == SERVER_VERSION:
            return None, p
        if ver is not None:
            print("※ ポート%d では古い版のサーバーが動いています。その黒い画面を閉じてください。" % p)
            continue
        try:
            srv = StudioServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
        return _bound(srv)
    raise SystemExit("空いているポートが見つかりません(%d〜%d)" % (start_port, start_port + 19))


LOG_MAX = 1024 * 1024
_log_lock = threading.Lock()


def _log(msg):
    """studio.log に1行追記(終了の原因調べ用。失敗しても何もしない。1MBを超えたら studio.old.log に回す)。"""
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with _log_lock:
            path = common.p("studio.log")
            common.rotate_log(path, LOG_MAX)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def _setup_diagnostics():
    """途中で終了したとき原因が分かるように、終了・例外・シグナルを studio.log と画面に残す。"""
    import atexit
    import faulthandler
    import signal
    import traceback
    try:
        crash = common.p("studio.crash.log")
        common.rotate_log(crash, LOG_MAX)   # 追記し続けて大きくならないよう、起動時に回す
        faulthandler.enable(open(crash, "a", encoding="utf-8"), all_threads=True)   # 内部クラッシュ時のスタック
    except Exception:
        pass

    def on_exc(t, v, tb):
        _log("未処理の例外(メインスレッド): " + "".join(traceback.format_exception(t, v, tb)).strip())
        sys.__excepthook__(t, v, tb)
    sys.excepthook = on_exc

    def on_thread_exc(a):
        _log("未処理の例外(スレッド %s): %s" % (getattr(a.thread, "name", "?"), "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)).strip()))
    threading.excepthook = on_thread_exc

    def on_signal(signum, frame):
        name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        _log("シグナル %s を受け取りました" % name)
        print("\nシグナル %s を受け取ったので終了します(studio.log に記録)" % name)
        raise SystemExit(0) if signum != signal.SIGINT else KeyboardInterrupt()
    for n in ("SIGTERM", "SIGHUP", "SIGBREAK"):   # 黒い画面の×ボタン(Windows は SIGBREAK)・kill など
        if hasattr(signal, n):
            try:
                signal.signal(getattr(signal, n), on_signal)
            except (ValueError, OSError):
                pass
    atexit.register(lambda: _log("プロセス終了"))


# 以前の場所(このフォルダ)から新しい置き場へ写す名前(段階4。ytt_core.datadir)。ログ・作業用の work は写さない
DATA_ITEMS = ("data.json", "data.json.bak", "feedback.jsonl", "feedback.jsonl.old", "registry.json", "config.json",
              "settings.json", "settings-ui.json", "cache", "archive")
DATA_STATE = None   # 起動時の datadir.prepare の結果(画面・入口に置き場所を出す用)


def _data_home():
    """データの置き場所。環境変数 STUDIO_HOME があればそれ(テスト用・以前からの指定)。
    無ければ %LOCALAPPDATA%\\youtube-tools\\studio(最初の起動で、このフォルダにある以前のデータをコピーする)"""
    global DATA_STATE
    if os.environ.get("STUDIO_HOME"):
        return os.environ["STUDIO_HOME"]
    r = datadir.prepare(TOOL_ID, CODE_DIR, DATA_ITEMS, log=lambda m: print(m, flush=True))
    DATA_STATE = r
    for w in r["warnings"]:
        print("※ " + w, flush=True)
    if r["state"] == "migrated":
        _keep_legacy_exports(r)
    return r["dir"]


def _keep_legacy_exports(r):
    """以前の既定の書き出し先(このフォルダの exports)に動画があり、書き出し先を変えていなかったなら、そこを使い続ける
    (置き場所を移したことで、既定の書き出し先が新しい置き場の exports に変わり、動画が2か所に分かれるのを防ぐ)"""
    old = os.path.join(r["legacy"], "exports")
    settings = os.path.join(r["dir"], "settings.json")
    if not os.path.isdir(old) or os.path.exists(settings):
        return
    try:
        common.atomic_write(settings, json.dumps({"outDir": old}, ensure_ascii=False).encode("utf-8"))
    except OSError:
        pass


def prepare(port, base_path="/"):
    """サーバーの待ち受け以外の起動の準備(データの読み込み・ログ・前回の作業ファイルの片付け・.runtime・環境チェック)。
    main() と、入口の統合サーバー(app/mount.py)の両方から呼ぶ。戻り値は .runtime の記録のパス(書けなければ None)。
    シグナルの受け取りは main() だけで行う(統合サーバーでは入口が受け取るため)。"""
    global PORT, BASE_PATH, ALLOWED_HOSTS
    PORT, BASE_PATH = port, base_path
    if not ALLOWED_HOSTS:
        ALLOWED_HOSTS = httpsec.allowed_hosts(port)
    # 置き場所を決めるのは、まだ既定(このフォルダ)のときだけ。テスト・入口が先に init(home) / STUDIO_HOME で決めていれば、それを使う
    default = os.path.normcase(common.home()) == os.path.normcase(os.path.abspath(CODE_DIR))
    init(_data_home() if default else None)
    common.migrate_old_logs()   # 以前の studio.log.old などは .gitignore に掛からないので、*.log の名前に直す(公開リポジトリに載せない)
    _log("起動 v%s port=%d%s pid=%d python=%s" % (SERVER_VERSION, port, "" if base_path == "/" else " path=" + base_path, os.getpid(), sys.version.split()[0]))
    shutil.rmtree(analyze.work_dir(), ignore_errors=True)   # 前回の途中で残った作業ファイルを消す
    runtime = handoff.write_runtime(TOOL_ID, port, SERVER_VERSION, base_path)   # 他のツールの「他のツール」メニュー用。書けなくても続ける
    common.start_env_check()   # 道具の版などは裏で調べる(yt-dlp --version は数秒かかることがある)
    return runtime


def finish():
    """終了の後始末(.runtime の記録を消す)。自分が書いた記録のときだけ消える。"""
    handoff.remove_runtime(TOOL_ID, PORT)


def mounted_elsewhere():
    """入口(start-all.bat)の統合サーバーの中でスタジオが動いていれば、その URL。
    同じ data.json を2つのサーバーで取り合わないよう、start.bat からの起動はそちらを開くだけにする。"""
    info = ytt_runtime.read_runtime(handoff.runtime_dir(), TOOL_ID)
    if info and info["path"] != "/" and ytt_runtime.ping_app(info["port"], 1, info["path"]) == APP_ID:
        return "http://localhost:%d%s" % (info["port"], info["path"])
    return None


def main():
    live = mounted_elsewhere()
    if live:
        print("入口の中ですでに起動しています。ブラウザで開きます:", live)
        if "--no-open" not in sys.argv:
            webbrowser.open(live)
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    srv, port = make_server(int(args[0]) if args else 8800)
    url = "http://localhost:%d" % port
    if srv is None:
        print("すでに起動しています。ブラウザで開きます:", url)
        if "--no-open" not in sys.argv:
            webbrowser.open(url)
        return
    _setup_diagnostics()
    runtime = prepare(port)
    print("切り抜きスタジオ:", url, "(終了は Ctrl+C またはこの画面を閉じる)")
    print("書き出し先:", common.get_out_dir())
    print("ログ:", common.p("studio.log"))
    if not find_tool("ffmpeg"):
        print("※ ffmpeg が見つかりません(README の準備手順を確認してください)")
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
        _log("serve_forever が終了しました")
    except KeyboardInterrupt:
        _log("Ctrl+C(KeyboardInterrupt)で終了")
        print("\nCtrl+C を受け取ったので終了します")
        if BATCH.is_busy() or exporter.is_busy():
            _log("解析または書き出しの実行中でした")
            print("(解析・書き出しの途中でした)")
        return 130
    finally:   # シグナル(SystemExit)で抜けるときもここを通る
        if runtime:
            finish()


if __name__ == "__main__":
    sys.exit(main() or 0)
