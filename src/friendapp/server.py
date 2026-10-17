# -*- coding: utf-8 -*-
"""友人の玄関(F2-1・F2-2。notes:plan/f1-friend-requirements.md の A-1・B)。友人の PC の 2 つ目の玄関(ユーザーの PC は src/app/server.py)。

    python src/friendapp/server.py [--port 8720] [--no-open]

- ② を同じプロセスで起こす(friendapp/engine.py。③ human・入口 app は読まない = 層の表 dev/layer_map.py の friendapp)
- 画面は /friend/(送る・受け取る)と /friend/setup.html(初回の準備だけ。済むまで /friend/ はこちらへ)。friendapp/ui/。ui-kit
- 窓は FriendApp.exe(friend-apps/launcher。C#・WebView2。F3-1 = notes:plan/f1-friend-requirements.md の C-1)が持つ。窓と画面の境目は friend-apps/launcher/README.txt:
  exe が空いている番号を選んで --port で渡す(ここでは他の番号へずらさない = 使えなければ終了コード 5)・合言葉は YTT_FRIEND_TOKEN で渡し、
  WebView2 が要求ごとに X-YTT-Token を足す(画面の meta ytt-token は中身 host の置き物 = 画面の JS は合言葉を知らない)。
  WebView2 の無い PC の逃げ道(YTT_FRIEND_HOST=edge)と開発の PC(exe なし)だけ meta に本物の合言葉を入れ、Edge のアプリの窓で開く
- 安全はユーザーの PC の入口と同じ: Host(DNS rebinding)・Origin・Sec-Fetch-Site の検査(ytt/httpsec)と、書き込み系の合言葉(起動ごと)
- 1 つの作業データに ② は 1 つ(flow/placement の .flow.lock)。もう動いていれば、その窓を開き直して終わる(終了コード 0)
- 古い部品(%LOCALAPPDATA%/youtube-tools のモデル)は、起動のあと裏で写して確かめ、古い方を消す(A-16。friendapp/oldcopy)。その間は送れない
- 閉じる・止めるの確認(作業中・預かりがあるときだけ)とスリープ止めは exe が GET /api/friend/state を見て決め、止めるときは POST /api/shutdown。
  exe なしで開発の PC から起こしたときは Ctrl+C か [すべて止めて終了] まで動く(待ちは残り、次に開いたとき続きから = 4-6)
- 環境変数(exe が渡す): YTT_FRIEND_TOKEN(合言葉。無ければ乱数)・YTT_FRIEND_HOST(webview2 / edge。無ければ開発の PC)・
  YTT_FRIEND_REC_PORT(録画の部品の番号。無ければ 8730)・YTT_FRIEND_ROLLBACK(起動できなかった新しい版 = 前の版で開いた知らせを 1 回出す)
- exe なしで、もう動いていれば標準出力に {"event":"already","port":…} を出して終了コード 0。起こせたら {"event":"ready","port":…,"pid":…}
口(書き込み系は合言葉。全部 JSON):
  GET  /api/ping                          {app, version}
  GET  /api/friend/state                  exe が見回る {making, recording, waiting, reserved, archiveWait, setup, undecided, awake, busy, label}(合言葉つき)
  GET  /api/friend/inbox                  受信箱の行・前回の値・保存先・空き容量で止めているか・準備中か・片付けの知らせ
  GET  /api/friend/peek?url=              配信の題・チャンネル名と配信者の推し
  GET  /api/friend/peek-live?url=         配信中・配信前か(F2-6。yt-dlp で数秒。ライブなら送る欄の下に 6 つの設定)
  GET  /api/friend/media?id=&n=           組のまとめ動画(Range つき)
  POST /api/friend/pick-file              Windows のファイルを選ぶ窓を開く(F2-6。画面からパスを打たせない)→ {file: {id, name, size, title, streamer, hex} | null}
  POST /api/friend/send                   送る(friendapp/api.py の欄。動画ファイルは fileId・ライブは kind live + live)
  POST /api/friend/decide {id, names, verdict: keep|reject}   受け取る / 要らない(names 空 = その行の決めていない物全部)
  POST /api/friend/retry {id}・remove {id}・cancel {id}        失敗の行の [もう一度送る]・[消す]・送った行を止める(録画中のライブの行は録画を止める)
  POST /api/friend/local {id}             ユーザーの PC に頼んだ依頼を [この PC でやり直す](F2-3。Dropbox の同期は friendapp/sync.py の裏の糸)
  POST /api/friend/open {what: saved}     受け取るの保存先をエクスプローラーで開く
  POST /api/friend/notice-seen            片付けの知らせを見た
  GET  /api/friend/setup                  初回の準備の進み具合(F3-5。friendapp/setup.py の view)
  POST /api/friend/setup/start・cancel・clean-old・skip-old   初回の準備を(もう一度)始める・やめる・前のアプリを片付ける / あとで
  POST /api/friend/palette {name: A〜D}  配色を覚える(画面へは meta ytt-palette。ui/palette.js)
  GET  /api/friend/streams                配信の一覧(F3-2。friendapp/streams.py の view + 各カードの送った物の印 sent)
  POST /api/friend/streams/refresh        一覧の [更新](断られて待っている間は {ok: false, waitSec})
  GET  /api/friend/settings               ⚙ の中身(F2-5。friendapp/settings.py。API キーは「入っている / 無い」だけ)
  POST /api/friend/settings {engine?, diskMinGB?, cut?, reset?: save|cases}   ⚙ を変える
  POST /api/friend/settings/key {key}     YouTube の API キーを確かめて保存(空 = 消す)
  POST /api/friend/pick-folder {what: save|cases}   Windows のフォルダを選ぶ窓を開いて、受け取るの保存先・一時保管を変える(画面からパスを打たせない)
  GET  /friend/guide.html                 説明(節 send・receive・settings・setup・close。画面の [?] が新しい窓で開く)
  POST /api/shutdown                      すべて止めて終了
  GET  /api/flow/status・POST /api/flow/submit・POST /api/flow/cancel   ② の口(ユーザーの PC の入口と同じ形)
  POST api/ytt/streamer-colors・client-log   ui-kit の共通の口(配信者の名簿・画面のエラーの記録)
"""
import argparse
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import placement as _placement, runqueue as _runqueue  # noqa: E402
from ytt import appwindow as _appwindow, colors as _colors, fsio as _fsio, httpsec, version as _version  # noqa: E402
from friendapp import api as _api, inbox as _inbox, oldcopy as _oldcopy, places as _places, settings as _settings, setup as _setup, streams as _streams, sync as _sync  # noqa: E402

APP_ID = "ytt-friend"
DEFAULT_PORT = 8720
PORT_TRIES = 20
MAX_BODY = 256 * 1024
TOKEN_HEADER = "X-YTT-Token"
TOKEN_FAIL = {"error": "token", "message": "画面を開き直してから、もう一度操作してください(合言葉が違います)"}
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UIKIT_DIR = os.path.join(SRC, "ui-kit")
STATIC = {"/friend/": ("friend.html", UI_DIR), "/friend/index.html": ("friend.html", UI_DIR), "/friend/friend.js": ("friend.js", UI_DIR), "/friend/send-list.js": ("send-list.js", UI_DIR), "/friend/send-form.js": ("send-form.js", UI_DIR),
          "/friend/sent.js": ("sent.js", UI_DIR), "/friend/receive.js": ("receive.js", UI_DIR), "/friend/palette.js": ("palette.js", UI_DIR),
          "/friend/friend.css": ("friend.css", UI_DIR), "/friend/ui-kit.js": ("ui-kit.js", UIKIT_DIR), "/friend/ui-kit.css": ("ui-kit.css", UIKIT_DIR),
          "/friend/guide.html": ("guide.html", UI_DIR),   # 説明(F2-5 の [?]。本体は別の段が書く = 無ければ 404)
          "/friend/setup.html": ("setup.html", UI_DIR), "/friend/setup.js": ("setup.js", UI_DIR), "/friend/host.js": ("host.js", UI_DIR),
          "/friend/settings.js": ("settings.js", UI_DIR), "/friend/settings.css": ("settings.css", UI_DIR)}   # F3-1・F3-5(窓と画面の境目)
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
PAGES = ("/", "/friend/", "/friend/index.html", "/friend/guide.html", "/friend/setup.html")
SETUP_PAGE = "/friend/setup.html"
MAIN_PAGES = ("/friend/", "/friend/index.html")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://i.ytimg.com; media-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SOON_MS = 30 * 60 * 1000              # 予約の配信がこれより近ければスリープを止める(C-5-4)
PALETTES = ("A", "B", "C", "D")       # 配色(前の送るアプリと同じ 4 つ。色の組は ui-kit のトークン = ui/palette.js)
PALETTE_NAME = "palette.json"
STREAMS_NAME = "streams.json"         # 配信の一覧の写し(開いた瞬間は前回の一覧 = C-2-5)
TOKEN_ENV = "YTT_FRIEND_TOKEN"        # exe が渡す合言葉(無ければ乱数)
HOST_ENV = "YTT_FRIEND_HOST"          # exe の窓の種類(webview2 = 合言葉は WebView2 が足す / edge = 逃げ道 / 無し = 開発の PC)
PORT_BUSY_EXIT = 5                    # exe が渡した番号を使えなかった(exe が選び直す)
ROLLBACK_ENV = "YTT_FRIEND_ROLLBACK"  # exe が前の版へ戻したとき、起動できなかった版
SWEEP_EVERY = 3600        # 受信箱の 3 日の片付けを見る間隔(秒)
SAVE_DEFAULT = _settings.SAVE_DEFAULT   # 受け取るの保存先の既定(%USERPROFILE% の下。⚙ で選ぶ = F2-5)
SAVE_FILE = _settings.SAVE_FILE
CLIENT_LOG_MAX = 512 * 1024
SYNC_KICK = ("/api/friend/send", "/api/friend/decide", "/api/friend/undo", "/api/friend/retry", "/api/friend/local", "/api/friend/report")   # 押したあと同期を起こす口(F2-3)


def save_dir(friend_dir, env=None):
    """受け取るの保存先(<玄関>/save-dir.json の dir か、%USERPROFILE%/Videos/受け取ったパック)"""
    d = _fsio.read_json_or(os.path.join(friend_dir, SAVE_FILE), {}, kind=dict).get("dir")
    if isinstance(d, str) and os.path.isabs(d):
        return d
    env = os.environ if env is None else env
    return os.path.join(env.get("USERPROFILE") or os.path.expanduser("~"), *SAVE_DEFAULT)


def open_folder(d, env=None):
    """フォルダをエクスプローラーで開く(玄関が決めた保存先だけ。画面からパスは受け取らない)。
    テストの作業データ(inplace)と一時フォルダの下は開かない(テストでユーザーの画面を取らない守り)。-> 開いたか"""
    env = os.environ if env is None else env
    if (env.get("YTT_DATA_DIR") or "").strip().lower() == "inplace" or _fsio.is_inside(d, tempfile.gettempdir()):
        return False
    if not hasattr(os, "startfile"):
        return False
    os.startfile(d)   # noqa: S606
    return True


PICK_TITLE = "送る動画ファイルを選ぶ"
PICK_FILTER = "動画(*.mp4;*.mkv;*.mov;*.webm;*.ts;*.m4v;*.flv;*.avi)\0*.mp4;*.mkv;*.mov;*.webm;*.ts;*.m4v;*.flv;*.avi\0すべてのファイル(*.*)\0*.*\0\0"


def pick_file_dialog(env=None):
    """Windows のファイルを選ぶ窓(comdlg32 の GetOpenFileNameW。tkinter の無い埋め込みの Python でも動く)-> 選んだパスか None(やめた)。
    窓は今いちばん前の窓(受信箱の Edge の窓)の上に出す。テストの作業データ(inplace)では開かない(テストでユーザーの画面を取らない守り)"""
    env = os.environ if env is None else env
    if (env.get("YTT_DATA_DIR") or "").strip().lower() == "inplace" or os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE), ("lpstrFilter", ctypes.c_void_p),
                    ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD), ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", ctypes.c_void_p), ("nMaxFile", wintypes.DWORD), ("lpstrFileTitle", wintypes.LPWSTR), ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR), ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD), ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD), ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", wintypes.LPARAM), ("lpfnHook", ctypes.c_void_p),
                    ("lpTemplateName", wintypes.LPCWSTR), ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD), ("FlagsEx", wintypes.DWORD)]
    ole32 = ctypes.windll.ole32
    inited = ole32.CoInitializeEx(None, 0x2) in (0, 1)   # COINIT_APARTMENTTHREADED(シェルの窓が要る)
    try:
        buf = ctypes.create_unicode_buffer(4096)
        filt = ctypes.create_unicode_buffer(PICK_FILTER, len(PICK_FILTER) + 1)
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = ctypes.windll.user32.GetForegroundWindow()
        ofn.lpstrFilter = ctypes.addressof(filt)
        ofn.nFilterIndex = 1
        ofn.lpstrFile = ctypes.addressof(buf)
        ofn.nMaxFile = len(buf)
        ofn.lpstrTitle = PICK_TITLE
        ofn.Flags = 0x00001000 | 0x00000800 | 0x00000004 | 0x00000008 | 0x00080000   # FILEMUSTEXIST・PATHMUSTEXIST・HIDEREADONLY・NOCHANGEDIR・EXPLORER
        ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
        return buf.value if ok and buf.value else None
    finally:
        if inited:
            ole32.CoUninitialize()


FOLDER_TITLES = {"save": "受け取ったパックを置くフォルダを選ぶ", "cases": "一時保管のフォルダを選ぶ(作っている途中の物・録画を置きます)"}


def pick_folder_dialog(what, env=None):
    """Windows のフォルダを選ぶ窓(shell32 の SHBrowseForFolderW。tkinter の無い埋め込みの Python でも動く)-> 選んだパスか None(やめた)。
    窓は今いちばん前の窓(受信箱の Edge の窓)の上に出す。テストの作業データ(inplace)では開かない(テストでユーザーの画面を取らない守り)"""
    env = os.environ if env is None else env
    if (env.get("YTT_DATA_DIR") or "").strip().lower() == "inplace" or os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p), ("pszDisplayName", wintypes.LPWSTR), ("lpszTitle", wintypes.LPCWSTR),
                    ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p), ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]
    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    inited = ole32.CoInitializeEx(None, 0x2) in (0, 1)   # COINIT_APARTMENTTHREADED(新しい形の窓が要る)
    try:
        name = ctypes.create_unicode_buffer(260)
        bi = BROWSEINFOW()
        bi.hwndOwner = ctypes.windll.user32.GetForegroundWindow()
        bi.pszDisplayName = ctypes.cast(name, wintypes.LPWSTR)
        bi.lpszTitle = FOLDER_TITLES.get(what, "フォルダを選ぶ")
        bi.ulFlags = 0x0001 | 0x0040   # BIF_RETURNONLYFSDIRS・BIF_NEWDIALOGSTYLE(フォルダを作れる)
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            return buf.value if shell32.SHGetPathFromIDListW(pidl, buf) and buf.value else None
        finally:
            ole32.CoTaskMemFree(pidl)
    finally:
        if inited:
            ole32.CoUninitialize()


def page_token(token, env=None):
    """画面の meta ytt-token に入れる値: exe の WebView2 の窓なら置き物 host(本物は WebView2 が要求ごとに足す = 画面の JS は知らない)・
    逃げ道の Edge の窓と開発の PC は本物"""
    env = os.environ if env is None else env
    return "host" if (env.get(HOST_ENV) or "").strip() == "webview2" else token


def inject_meta(body, token, palette=None):
    """合言葉・版・配色の meta を <head> の頭に(配色は palette.js が <head> の中で読む = 描く前に色を決める)"""
    tag = ('<meta name="ytt-token" content="%s"><meta name="ytt-version" content="%s">' % (page_token(token), _version.VERSION)).encode("ascii")
    if palette in PALETTES:
        tag += ('<meta name="ytt-palette" content="%s">' % palette).encode("ascii")
    i = body.find(b"<head>")
    return body[:i + 6] + tag + body[i + 6:] if i >= 0 else tag + body


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
        if path in MAIN_PAGES and not self.server.app.setup_done():   # 初回の準備が済むまでは準備だけの画面(C-5-1)
            return self._send(302, b"", extra={"Location": SETUP_PAGE})
        if path in STATIC:
            name, base = STATIC[path]
            try:
                with open(os.path.join(base, name), "rb") as f:
                    body = f.read()
            except OSError:
                return self._send(404, b"not found")
            page = name.endswith(".html")
            if page:
                body = inject_meta(body, self.server.token, self.server.app.palette())
            return self._send(200, body, TYPES[os.path.splitext(name)[1]],
                              {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"} if page else None)
        q = urllib.parse.parse_qs(u.query)
        path = path[len("/friend"):] if path.startswith("/friend/api/") else path
        app = self.server.app
        if path == "/api/ping":
            return self._json(200, {"app": APP_ID, "version": _version.VERSION})
        if path == "/api/friend/inbox":
            out = app.api.view()
            out.update(prep=app.prep, notice=app.notice(), rollback=app.rollback_notice(), sync=app.sync.status(), setup=app.setup.view())
            return self._json(200, out)
        if path == "/api/friend/setup":   # 初回の準備の進み具合(F3-5)
            return self._json(200, {"ok": True, "setup": app.setup.view(), "done": app.setup_done()})
        if path == "/api/friend/state":   # exe の見回り(GET でも合言葉を要る = 画面を開いていない人に仕事の中身を見せない)
            if not httpsec.token_ok(self.headers, self.server.token, TOKEN_HEADER):
                return self._json(403, TOKEN_FAIL)
            return self._json(200, app.state())
        if path == "/api/friend/peek":
            try:
                return self._json(200, app.api.peek((q.get("url") or [""])[0][:300]))
            except _api.FormError as e:
                return self._fail(400, "bad_url", str(e))
        if path == "/api/friend/peek-live":   # 配信中・配信前か(F2-6。数秒かかる = 画面は題と別に問い合わせる)
            try:
                return self._json(200, app.api.peek_live((q.get("url") or [""])[0][:300]))
            except _api.FormError as e:
                return self._fail(400, "bad_url", str(e))
        if path == "/api/friend/receive":   # 受け取る画面(F3-4。配信ごとの段・見送った物・まだ決めていない本数)
            app.seen = time.time()
            return self._json(200, app.inbox.receive_view())
        if path == "/api/friend/media":   # 1 本の確認用の動画(id + name。F3-4)・前の形の組のまとめ動画(id + n)
            rid = (q.get("id") or [""])[0]
            if q.get("name"):
                p = app.inbox.pack_preview(rid, (q.get("name") or [""])[0])
            else:
                r = app.inbox.row(rid)
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
        if path == "/api/friend/settings":   # ⚙(F2-5)
            return self._json(200, {"ok": True, "settings": app.settings.view()})
        if path == "/api/friend/streams":   # 配信の一覧(F3-2。friendapp/streams.py の写し + 送った物の印)
            return self._json(200, app.streams_view())
        if path == "/api/flow/status":
            eng = app.engine
            return self._json(200, eng.queue.status() if eng else {"idle": True, "runs": [], "preparing": True})
        return self._fail(404, "not_found", "その操作はありません")

    # ------------------------------------------------------------ PUT(画面に落とした動画を受け取る。F3-3 = C-2-13)
    def do_PUT(self):
        u = urllib.parse.urlsplit(self.path)
        h = self.headers
        path = u.path[len("/friend"):] if u.path.startswith("/friend/api/") else u.path
        self.close_connection = True   # 本文を読まずに断ったときに、残りを次の要求として読まない
        if not (self._host_ok() and httpsec.origin_ok(h, self.server.allowed_hosts) and httpsec.fetch_site_ok(h)):
            return self._send(403, b"forbidden")
        if not httpsec.token_ok(h, self.server.token, TOKEN_HEADER):
            return self._json(403, TOKEN_FAIL)
        if path != "/api/friend/upload":
            return self._fail(404, "not_found", "その操作はありません")
        q = urllib.parse.parse_qs(u.query)
        try:
            size = int(h.get("Content-Length") or "-1")
        except ValueError:
            size = -1
        try:
            got = self.server.app.api.upload_file((q.get("name") or [""])[0], size, self.rfile.read)
        except _api.FormError as e:
            return self._fail(400, "bad_request", str(e))
        except OSError as e:
            return self._fail(500, "io", "動画を受け取れませんでした(%s)" % e.__class__.__name__)
        return self._json(200, {"ok": True, "file": got})

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
        except _settings.SettingsError as e:
            return self._fail(400, "bad_request", str(e))
        except ValueError as e:
            return self._fail(409, "refused", str(e))
        finally:
            if path in SYNC_KICK:   # 画面の操作のあとに Dropbox の同期を 1 回(F2-3)
                self.server.app.sync.kick()

    def _post(self, path, body):
        app = self.server.app
        if path == "/api/friend/send":   # F3-3: {rows, skipped}(row = 先頭の行。前の形の呼び手のため)
            got = app.api.send(body)
            return self._json(200, {"ok": True, "row": got["rows"][0], "rows": got["rows"], "skipped": got["skipped"]})
        if path == "/api/friend/pick-file":   # ファイルを選ぶ窓(F2-6)。1 つずつ(開いている間の 2 つ目は断る)
            if not app.pick_lock.acquire(blocking=False):
                return self._fail(409, "busy", "ファイルを選ぶ窓はもう開いています")
            try:
                chosen = app.pick_file()
            finally:
                app.pick_lock.release()
            return self._json(200, {"ok": True, "file": app.api.remember_file(chosen) if chosen else None})
        if path == "/api/friend/decide":   # F3-4: {items: [{id, name}], verdict: keep|skip|bad, reason?: boring|cut}(前の形 {id, names} も受ける)
            return self._json(200, app.decide(body))
        if path == "/api/friend/undo":   # [戻す](C-3-6){items: [{id, name}]}
            return self._json(200, app.undo(body))
        if path == "/api/friend/palette":   # 配色を覚える(画面はもう塗り替えている。次に開いたとき meta ytt-palette で同じ色)
            return self._json(200, {"ok": True, "palette": app.set_palette(body.get("name"))})
        if path == "/api/friend/files":   # 落とした動画(exe が本物のパスを読んで送る = F3-1 の host.js の sendFiles。画面からパスは送らない)
            return self._json(200, app.dropped_files(body.get("paths")))
        if path == "/api/friend/report":   # [作る人に知らせる](C-2-16)
            return self._json(200, {"ok": True, "row": app.api.report(str(body.get("id") or ""))})
        if path == "/api/friend/prefs":   # ⚙ の処理する PC・解析の重み・ライブの感度・待ち・余白(C-2-19・C-2-11)
            msgs = app.api.set_prefs({k: body[k] for k in ("pc", "useWeights", "weights", "liveSens", "liveWait", "livePad") if k in body})
            return self._json(200, {"ok": True, "message": "。".join(msgs) or "変えるものがありません", "form": app.api.form()})
        if path == "/api/friend/retry":
            return self._json(200, {"ok": True, "row": app.api.retry(str(body.get("id") or ""))})
        if path == "/api/friend/remove":
            app.inbox.remove(str(body.get("id") or ""))
            return self._json(200, {"ok": True})
        if path == "/api/friend/cancel":
            return self._json(200, {"ok": True, "result": app.api.cancel(str(body.get("id") or ""))})
        if path == "/api/friend/local":   # [この PC でやり直す](A-2。F2-3)
            return self._json(200, {"ok": True, "row": app.api.local(str(body.get("id") or ""))})
        if path == "/api/friend/open" and body.get("id"):   # 受け取った物のフォルダ([フォルダを開く]。C-3-8)
            d = app.inbox.saved_dir(str(body.get("id")), str(body.get("name") or ""))
            if not d:
                return self._fail(404, "not_found", "保存先のフォルダが見つかりません")
            app.open_folder(d)
            return self._json(200, {"ok": True})
        if path == "/api/friend/open":
            d = app.places["save"]()
            os.makedirs(d, exist_ok=True)
            app.open_folder(d)
            return self._json(200, {"ok": True, "dir": d})
        if path.startswith("/api/friend/setup/"):   # 初回の取得(F2-5。9-1)
            return self._setup(path[len("/api/friend/setup/"):])
        if path == "/api/friend/streams/refresh":   # 一覧の [更新](F3-2)
            return self._json(200, app.streams.refresh())
        if path == "/api/friend/settings":
            if body.get("reset") is not None:
                msg = app.settings.reset_folder(body.get("reset"))
            else:
                msg = app.settings.update({k: body[k] for k in ("engine", "diskMinGB", "cut", "processing", "weights", "live", "cleanOld") if k in body})["message"]
            return self._json(200, {"ok": True, "message": msg, "settings": app.settings.view()})
        if path == "/api/friend/settings/key":
            ok, msg = app.settings.set_key(body.get("key") if isinstance(body.get("key"), str) else "")
            if not ok:
                return self._fail(400, "key", msg)
            return self._json(200, {"ok": True, "message": msg, "settings": app.settings.view()})
        if path == "/api/friend/pick-folder":   # フォルダを選ぶ窓(F2-5)。1 つずつ(開いている間の 2 つ目は断る)
            what = body.get("what")
            if what not in ("save", "cases"):
                return self._fail(400, "bad_request", "変えられる場所ではありません")
            if not app.pick_lock.acquire(blocking=False):
                return self._fail(409, "busy", "選ぶ窓はもう開いています")
            try:
                chosen = app.pick_folder(what)
            finally:
                app.pick_lock.release()
            msg = app.settings.set_folder(what, chosen) if chosen else ""
            return self._json(200, {"ok": True, "chosen": bool(chosen), "message": msg, "settings": app.settings.view()})
        if path == "/api/friend/notice-seen":
            if body.get("what") == "cleaned":   # 「3 日たった n 本を片付けました」を見た(C-3-7)
                app.inbox.notice_seen()
                return self._json(200, {"ok": True})
            app.rollback_seen = True
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


    def _setup(self, what):
        app = self.server.app
        st = app.setup
        if what == "start":       # 失敗のあとの [もう一度](取れた分は .part に残り、続きから)
            st.start()
        elif what == "cancel":
            st.cancel()
        elif what == "clean-old":  # 前のアプリを片付ける(写して同じと確かめた物だけ = C-1-2)
            st.clean_old()
        elif what == "skip-old":   # [あとで](もう聞かない。⚙ から片付けられる)
            st.skip_old()
        else:
            return self._fail(404, "not_found", "その操作はありません")
        return self._json(200, {"ok": True, "setup": st.view(), "done": app.setup_done()})


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
        self.token = os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(24)
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
        self.closing = threading.Event()
        self.server = None
        self.rollback = (os.environ.get(ROLLBACK_ENV) or "").strip()   # exe が前の版へ戻した = 起動できなかった版
        self.rollback_seen = False
        self.open_folder = open_folder   # エクスプローラーで開く口(テストは差し替える = 画面を取らない)
        self.pick_file = pick_file_dialog   # ファイルを選ぶ窓の口(F2-6。テストは差し替える = 本物の窓を出さない)
        self.pick_lock = threading.Lock()
        self.api.stopping = self.closing.is_set   # 終わる途中なら動画を写すのを止める
        # Dropbox の同期(F2-3)。糸を起こすのは main だけ(テストは run_once を直に呼ぶ・偽の口を client_factory に)
        self.sync = _sync.Sync(places, self.inbox, self.api.form, engine_fn=lambda: self.engine, clock=clock, log=self.log)
        self.api.sync = self.sync
        # 初回の取得(F2-5。fetch.json が無ければ何もしない)と ⚙
        self.setup = _setup.Setup(places.get("fetch"), places["data"], places.get("home") or os.path.dirname(places["data"]), places["friend"],
                                  device=_machine_device, log=self.log, after=self.after_setup)
        self.api.parts_missing = self.setup.block_reason
        self.settings = _settings.Settings(places, self.api, self.setup, engine_fn=lambda: self.engine, log=self.log)
        self.pick_folder = pick_folder_dialog   # フォルダを選ぶ窓の口(F2-5。テストと見本は差し替える = 本物の窓を出さない)
        # 配信の一覧(F3-2。キー無し = 名簿の channel・RSS・動画のページ)。糸を起こすのは main だけ(テストと見本は fetch を差し替える)
        self.streams = _streams.Streams(os.path.join(places["friend"], STREAMS_NAME), clock=clock, log=self.log)
        self.inbox.stream_info = lambda vid: self.streams.lookup(vid)   # 受け取った物の置き場所の日付・段の見出し(C-3-8)

    def decide(self, body):
        """[受け取る] / [見送る] / 届かなくてよかった(1 本でもまとめてでも。行ごとに受信箱へ)"""
        items = body.get("items")
        if not isinstance(items, list):   # 前の形 {id, names}
            items = [{"id": body.get("id"), "name": n} for n in body.get("names") or [None]]
        by_row = {}
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("id"), str):
                by_row.setdefault(it["id"], []).extend([it["name"]] if isinstance(it.get("name"), str) else [])
        done, pending, errors = [], [], []
        for rid, names in by_row.items():
            try:
                got = self.inbox.decide(rid, names, body.get("verdict"), reason=body.get("reason"))
            except ValueError as e:
                raise _api.FormError(str(e))
            done += [{"id": rid, "name": n} for n in got["done"]]
            pending += [{"id": rid, "name": n} for n in got["pending"]]
            errors += [dict(e, id=rid) for e in got["errors"]]
        if done or pending:
            self.sync.kick()
        return {"ok": not errors, "done": done, "pending": pending, "errors": errors}

    def palette(self):
        """選んだ配色 A〜D(無ければ A = ネオンシアン。前の送るアプリの初めと同じ)"""
        got = _fsio.read_json_or(os.path.join(self.places["friend"], PALETTE_NAME), {}, kind=dict).get("name")
        return got if got in PALETTES else "A"

    def set_palette(self, name):
        if name not in PALETTES:
            raise _api.FormError("配色は A〜D のどれかです")
        _fsio.write_json(os.path.join(self.places["friend"], PALETTE_NAME), {"name": name})
        return name

    def dropped_files(self, paths):
        """exe の窓に落とした動画のパス -> {"ok", "files": [remember_file の形], "skipped": [{"name", "message"}]}(動画でない物はその 1 本だけ外す)"""
        files, skipped = [], []
        for p in (paths if isinstance(paths, list) else [])[:_api.FILES_MAX_SEND]:
            try:
                files.append(self.api.remember_file(p))
            except _api.FormError as e:
                skipped.append({"name": os.path.basename(str(p or ""))[:200], "message": str(e)})
        return {"ok": bool(files), "files": files, "skipped": skipped}

    def undo(self, body):
        by_row = {}
        for it in body.get("items") if isinstance(body.get("items"), list) else []:
            if isinstance(it, dict) and isinstance(it.get("id"), str) and isinstance(it.get("name"), str):
                by_row.setdefault(it["id"], []).append(it["name"])
        done, errors = [], []
        for rid, names in by_row.items():
            got = self.inbox.undo(rid, names)
            done += [{"id": rid, "name": n} for n in got["done"]]
            errors += [dict(e, id=rid) for e in got["errors"]]
        if done:
            self.sync.kick()
        return {"ok": not errors, "done": done, "errors": errors}

    def streams_view(self):
        """配信の一覧 + 各カードの送った物の印(同じ配信の一番新しい依頼の行の状態 = C-2-4)。
        状態は送った物の行と同じ読み方(api.view = ② の実行中なら making・待ちなら queued)= 一覧の印と送った物の行が食い違わない"""
        v = self.streams.view()
        sent = {}
        for r in self.api.view()["rows"]:
            vid = (r.get("source") or {}).get("videoId")
            if not vid or vid in sent or r.get("cancelled"):   # 行は新しい順・取り消した行は印にしない
                continue
            st = r["state"]
            if st == "sent" and (r.get("run") or {}).get("state") == "queued":
                st = "queued"
            sent[vid] = {"state": st, "id": r["id"]}
        for sec in v.get("sections") or []:
            for it in sec.get("items") or []:
                if it.get("videoId") in sent:
                    it["sent"] = sent[it["videoId"]]
        return v

    def after_setup(self, result):
        """初回の取得のあと: 取った道具(<home>/tools の ffmpeg など)の場所を ② に教え直す。② は起こし直さない
        (道具は使うたびに環境変数と PATH から探す = ytt/tools.find_tool・モデルは読み込むときに作業データから読む)"""
        home = self.places.get("home")
        if home:
            got = _places.tool_env(os.path.join(home, _places.TOOLS_NAME))
            self.log("取った道具の場所を教え直しました: %s" % "・".join(sorted(k for k in got if k != "PATH")))

    def rollback_notice(self):
        """前の版で開いた知らせ(exe から戻ったと聞いたとき、閉じるまで 1 回)"""
        return "新しい版 %s を起動できなかったので、前の版で開きました" % self.rollback[:40] if self.rollback and not self.rollback_seen else None

    def setup_done(self):
        """初回の準備が済んだか(済むまで /friend/ は準備だけの画面へ。fetch.json の無い開発の PC は済み扱い)"""
        return bool(getattr(self.setup, "done", True))

    def recording_count(self):
        """録画中の本数(F2-6 のライブ係が録画元に聞く。exe の確認の窓とアイコンの文に出す)"""
        live = getattr(self.engine, "live", None)
        return live.active_count() if live is not None else 0

    def holdings(self):
        """作っている物のほかの預かり(F3-3): {reserved: 予約の数(まだ始まっていない配信の録画), archiveWait: アーカイブ待ちの数,
        soon: 30 分以内に始まる予約があるか(スリープを止める = C-5-4)}"""
        now = self.clock() * 1000
        reserved, wait, soon = 0, 0, False
        for r in self.inbox.view():
            if r.get("cancelled"):
                continue
            if r["state"] == "waiting":
                wait += 1
            start = (r.get("form") or {}).get("startAt")
            if r["state"] == "recording" and r.get("kind") == "live" and isinstance(start, int) and start > now and not r["packs"]:
                reserved += 1
                soon = soon or start - now <= SOON_MS
        return {"reserved": reserved, "archiveWait": wait, "soon": soon}

    def undecided(self):
        """受け取るの ●n = まだ決めていない本数(窓のタイトルとタスクバー。C-3-9)"""
        try:
            return int(self.inbox.receive_view()["undecided"])   # 受け取る画面の ●n と同じ数(受け取っている途中の物は数えない)
        except Exception as e:   # noqa: BLE001  (数えられなくても見回りは止めない)
            self.log("決めていない本数を数えられませんでした: %s" % e.__class__.__name__)
            return 0

    def state(self):
        """exe の見回り用(窓と画面の境目 = friend-apps/launcher/README.txt): 作業中と預かりの数・準備中・●n・スリープを止めるか"""
        rec = self.recording_count()
        making = waiting = 0
        eng = self.engine
        if eng is not None:
            for r in eng.queue.status().get("runs") or []:
                if r.get("state") == "running":
                    making += 1
                elif r.get("state") == "queued":
                    waiting += 1
        hold = self.holdings()
        setup = self.setup.awake()
        busy = self.busy() or rec > 0
        parts = (["録画中 %d 本" % rec] if rec else []) + (["作っている %d 本" % making] if making else []) + (["待ち %d 本" % waiting] if waiting else [])
        return {"busy": busy, "recording": rec, "making": making, "waiting": waiting, "reserved": hold["reserved"], "archiveWait": hold["archiveWait"],
                "setup": bool(setup), "undecided": self.undecided(),
                "awake": bool(rec or making or waiting or setup or hold["archiveWait"] or hold["soon"]),
                "label": "・".join(parts) if parts else ("準備しています" if busy else "")}

    def notice(self):
        n = _oldcopy.notice(self.catalog) if os.path.isfile(self.catalog) else None
        return {"freedGB": round(n["bytes"] / 1e9, 1)} if n and n.get("bytes") else None

    def prepare(self, old_root=None):
        """裏の糸: 初回の準備(F3-5。前のアプリの部品を写す → 取る → 浅く置く → 全部の道具を動かして確かめる。済んでいれば確かめず済み)を
        確認なしで始め、進んでいる間は待つ → ② を起こす(待ちの記録の続きを、道具がそろう前に始めない)。準備が失敗しても ② は起こす
        (画面は準備だけの画面で理由と [もう一度] を出す)"""
        try:
            self.setup.start(old_root)
            while self.setup.awake() and not self.closing.wait(0.5):
                pass
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
        return not st["idle"] or bool(eng._previews) or self.sync.busy() or self.api.copying()

    def watch(self):
        """3 日の片付け(SWEEP_EVERY ごと)。終わるかどうかは exe が決める(ここでは終わらない)"""
        last_sweep = 0
        while not self.closing.wait(10):
            now = self.clock()
            if self.engine is not None:
                try:
                    self.api.tick()   # アーカイブ待ち・失敗の自動のやり直し・落とした動画の片付け(F3-3)
                except Exception as e:   # 見回りで玄関を止めない
                    self.log("送った物の見回りに失敗しました: %s" % e.__class__.__name__)
            if now - last_sweep >= SWEEP_EVERY and self.engine is not None:
                last_sweep = now
                try:
                    n = self.inbox.sweep()
                    if n:
                        self.log("3 日決めなかった %d 本を自動で見送りました" % n)
                except Exception as e:   # 片付けで玄関を止めない
                    self.log("受信箱の片付けに失敗しました: %s" % e.__class__.__name__)

    def shutdown(self):
        if self.closing.is_set():
            return
        self.closing.set()
        if (os.environ.get(HOST_ENV) or "").strip():   # exe に「止めてと言われて終わる」と知らせる(起こし直さない。窓の外から止めたときも)
            say(json.dumps({"event": "bye"}))
        self.setup.cancel()   # 取っている途中なら止める(取れた分は .part に残り、次は続きから)
        self.sync.stop()
        self.streams.stop()
        if self.engine is not None:
            self.engine.close()
        if self.server is not None:
            self.server.shutdown()


def _machine_device():
    """今の文字起こしの機器(この PC の設定 machine.json の device。読めなければ vulkan)"""
    from flow import machine as _machine
    try:
        return _machine.get("device")
    except (OSError, ValueError):
        return "vulkan"


def make_logger(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = threading.Lock()

    def log(msg):
        line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        with lock:
            _fsio.append_line(path, line, 2 * 1024 * 1024)
    return log


def _make_live(places, queue_fn, log):
    """② のライブ係(F2-6。friendapp/live_session.FriendLive)。空き容量の下限はこの PC の設定 machine.json の diskMinGB"""
    from flow import machine as _machine
    from friendapp import live_session as _live_session
    try:
        floor = _machine.get("diskMinGB")
    except (OSError, ValueError):
        floor = _machine.DISK_MIN_GB
    return _live_session.FriendLive(places, queue_fn, log=log, disk_min_gb=floor)


def _default_engine(places, inbox, log):
    from friendapp import engine as _engine   # ② の部品は起動のあとに(画面を先に出す)
    eng = _engine.Engine(places, inbox, log=log, live_factory=_make_live)
    eng.live.start()   # 見回り(録画の部品を起こす・前回の録画の続き・依頼の録画の検出と書き出し・受信箱の行を進める)
    return eng


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
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="exe から起こすときはこの番号だけを使う(ずらさない)")
    ap.add_argument("--no-open", action="store_true", help="窓を開かない")
    a = ap.parse_args(argv)
    pl = _places.setup()
    pl["save"] = lambda: save_dir(pl["friend"])
    log = make_logger(os.path.join(pl["friend"], "logs", "friendapp.log"))
    hosted = bool((os.environ.get(HOST_ENV) or "").strip())   # exe から起こした(番号は exe が選んだ物だけ・窓は exe)
    info = _placement.lock_info(pl["data"])
    if hosted and info and info.get("port"):   # exe は 1 つだけ起こすので、別の処理が同じ作業データを使っている
        say("ほかの処理(%s)が同じ作業データを使っています" % info.get("pid"), log)
        return 4
    if info and info.get("port"):   # もう動いている = その窓を開き直して終わる
        url = "http://localhost:%d/friend/" % info["port"]
        if not a.no_open:
            open_window(pl["friend"], url, log)
        say(json.dumps({"event": "already", "port": info["port"]}))
        return 0
    app = FriendApp(pl, log=log, make_engine=_default_engine)
    srv = None
    for p in ([a.port] if hosted else range(a.port, a.port + PORT_TRIES)):
        try:
            srv = Server(("127.0.0.1", p), app)
            break
        except OSError:
            continue
    if srv is None:
        if hosted:
            say("番号 %d を使えません(exe が選び直します)" % a.port, log)
            return PORT_BUSY_EXIT
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
    url = "http://127.0.0.1:%d/friend/" % port
    log("友人の玄関 v%s: %s(作業データ %s)" % (_version.VERSION, url, pl["data"]))
    threading.Thread(target=app.prepare, args=(_places.old_data_root(),), name="friend-prepare", daemon=True).start()
    threading.Thread(target=app.watch, name="friend-watch", daemon=True).start()
    threading.Thread(target=app.sync.loop, name="friend-sync", daemon=True).start()   # Dropbox の同期(F2-3。鍵が無ければ何もしない)
    app.streams.start()   # 配信の一覧(F3-2)
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
