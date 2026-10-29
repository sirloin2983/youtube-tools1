# -*- coding: utf-8 -*-
"""友人の玄関の Dropbox の部品(資料の git:before-1028-cleanup:docs/design/friend-history.md の 7 章・docs/spec/friend.md の 2-17・4 章)。

標準ライブラリだけ。使い方・やり直しの規則:
- 鍵: <home>/config.json の appKey + refreshToken(PKCE で得た物。secret は使わない)-> /oauth2/token で短い期間の access token
- 通信の失敗・429・5xx は少し待ってやり直す(2 秒 x 回数の 2 乗)。401 は鍵を取り直して 1 回だけやり直す(権限が足りない 401 はそのまま)
- 150MB 以下は files/upload・それより大きい物は upload_session(8MB ずつ。やり直しの前の回が実は届いていたら Dropbox の正しい位置で先へ)
- download は通信が切れたら続きから(Range。やり直しは 6 回)。rev を渡せば、やり直しの間に置き換わっていないかを確かめる
- status が負の DropboxError は、このプログラムが見つけた問題(やり直さない)
接続先は下の固定の URL だけ。鍵・access token はログ・例外の文・画面に出さない(Config の repr も伏せる)。
"""
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
RPC_BASE = "https://api.dropboxapi.com/2/"
CONTENT_BASE = "https://content.dropboxapi.com/2/"
NOTIFY_BASE = "https://notify.dropboxapi.com/2/"   # 変化を長く待つ口(files/list_folder/longpoll。鍵を付けない)
LONGPOLL_EXTRA = 120          # 長く待つ口の通信の時間切れ = 待つ秒 + これ(Dropbox は最大 90 秒遅れて返す)
CONFIG_NAME = "config.json"
RETRIES = 4
DOWNLOAD_RETRIES = 6          # 数 GB のパックは途中で切れることがある。続きから取るので多め
SINGLE_LIMIT = 150 * 1024 * 1024
CHUNK = 8 * 1024 * 1024
HASH_BLOCK = 4 * 1024 * 1024  # Dropbox の content_hash の塊
MAX_PAGES = 50                # list_folder の続きの上限(1 回 500 件 x 50)
ERROR_BODY_MAX = 64 * 1024
READ_STEP = 256 * 1024
# 友人のアプリが消してよい物(安全面の直し 7・10-29。鍵は 2 台で同じなので、コードの中で消す対象を自分の物に限る):
# 直下の依頼 <依頼 id>.request.json と上げた動画 <依頼 id>__<名前>・/出力/ のファイル・/診断/ の中のファイル。/更新/・/学習/・フォルダは消さない
DELETE_OK = re.compile(r"^/(?:[0-9A-Za-z_-]{1,64}(?:\.request\.json|__[^/]+)|出力/[^/]+|診断/(?:[^/]+/)?[^/]+)\Z")
RPC_TIMEOUT, CONTENT_TIMEOUT, DOWNLOAD_TIMEOUT = 60, 600, 300


class DropboxError(Exception):
    """Dropbox の呼び出しの失敗。status 0 = 通信が切れた(やり直せる)・負 = このプログラムが見つけた問題。文は画面に出してよい日本語(鍵は入れない)"""

    def __init__(self, message, status=0, body=""):
        super().__init__(message)
        self.status, self.body = status, body or ""

    @property
    def not_found(self):
        return is_not_found(self.status, self.body)

    @property
    def retryable(self):
        return self.status == 0 or self.status == 429 or self.status >= 500


class Cancelled(Exception):
    """止めた(玄関を閉じる)"""


class Config:
    """config.json の鍵(appKey + refreshToken)。repr に鍵を出さない"""

    def __init__(self, app_key, refresh_token):
        self.app_key, self.refresh_token = app_key, refresh_token

    def __repr__(self):
        return "Config(appKey=***, refreshToken=***)"

    def __eq__(self, other):
        return isinstance(other, Config) and (self.app_key, self.refresh_token) == (other.app_key, other.refresh_token)

    def __hash__(self):
        return hash((self.app_key, self.refresh_token))


def config_path(home):
    """鍵の場所(アプリのフォルダの直下の config.json)"""
    return os.path.join(home, CONFIG_NAME)


def load_config(home):
    """<home>/config.json -> Config か None(無い・読めない・appKey か refreshToken が無い)"""
    try:
        with open(config_path(home), "rb") as f:
            d = json.loads(f.read(64 * 1024).decode("utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    key, tok = str(d.get("appKey") or "").strip(), str(d.get("refreshToken") or "").strip()
    return Config(key, tok) if key and tok else None


# ------------------------------------------------------------ 返事の読み方
def missing_scope(body):
    b = (body or "").lower()
    return "missing_scope" in b or "insufficient_scope" in b or "insufficient scope" in b


def is_not_found(status, body):
    return status == 409 and "not_found" in (body or "")


def error_text(status, body):
    """Dropbox のエラーを日本語に(鍵は入れない)"""
    summary = ""
    try:
        d = json.loads(body or "")
        summary = str(d.get("error_summary") or d.get("error") or "") if isinstance(d, dict) else ""
    except ValueError:
        pass
    low = ("%s %s" % (summary, body or "")).lower()
    if missing_scope(body):
        return "Dropbox の鍵に権限が足りません。ユーザーに新しい config.json を作ってもらってください"
    if "invalid_grant" in low or "invalid_access_token" in low or "expired_access_token" in low:
        return "Dropbox の鍵が使えなくなっています(取り消された可能性があります)。ユーザーに新しい config.json をもらってください"
    if "invalid_client" in low or "app_key" in low:
        return "config.json の appKey が正しくありません。ユーザーに伝えてください"
    if "insufficient_space" in low:
        return "Dropbox の空きが足りません。ユーザーに伝えてください"
    if is_not_found(status, body):
        return "Dropbox にもうありません"
    if status == 429 or "too_many" in low:
        return "Dropbox が混んでいます。少し待つと続きから進めます"
    if status >= 500:
        return "Dropbox の側で問題が起きています(%d)。少し待つと続きから進めます" % status
    return "Dropbox からエラーが返りました(%d%s)" % (status, (": " + summary[:80]) if summary else "")


def arg_header(obj):
    """Dropbox-API-Arg のヘッダーの JSON(ASCII だけ。日本語は JSON の u の 4 桁の形にする)"""
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).replace("\x7f", "\\u007f")


def commit_arg(path, overwrite=False):
    if overwrite:   # いつも同じ場所の 1 つのファイル(依頼の JSON の送り直し)
        return {"path": path, "mode": "overwrite", "autorename": False, "mute": True}
    return {"path": path, "mode": "add", "autorename": True, "mute": False}


def content_hash(path, progress=None):
    """Dropbox の content_hash(4MB ずつの SHA-256 をつないで、もう一度 SHA-256)。受け取った物が壊れていないかを確かめる"""
    outer = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        while True:
            block = f.read(HASH_BLOCK)
            if not block:
                break
            outer.update(hashlib.sha256(block).digest())
            done += len(block)
            if progress:
                progress(done)
            if len(block) < HASH_BLOCK:
                break
    return outer.hexdigest()


def _correct_offset(body):
    try:
        d = json.loads(body or "")
        err = d.get("error") if isinstance(d, dict) else None
        inc = err.get("incorrect_offset") if isinstance(err, dict) and isinstance(err.get("incorrect_offset"), dict) else err
        v = inc.get("correct_offset") if isinstance(inc, dict) else None
        return v if isinstance(v, int) else -1
    except ValueError:
        return -1


def urlopen_transport(url, headers, body, timeout):
    """本物の通信(urllib)-> (status, {ヘッダーの名前の小文字: 値}, 読む口)。返事の来ない失敗は DropboxError(status 0)"""
    if not (url == TOKEN_URL or url.startswith(RPC_BASE) or url.startswith(CONTENT_BASE) or url.startswith(NOTIFY_BASE)):
        raise DropboxError("決まった Dropbox の場所の外へはつなぎません", -1)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        r = e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise DropboxError("インターネットにつながりません(%s)" % e.__class__.__name__, 0)
    status = getattr(r, "status", None) or r.getcode()
    return status, {k.lower(): v for k, v in (r.headers.items() if r.headers else [])}, r


class Client:
    """Dropbox の API(アプリのフォルダの中だけ)。transport はテストで差し替える。cancelled() が真になったら Cancelled"""

    def __init__(self, config, transport=None, log=None, cancelled=None, sleep=time.sleep):
        self.config = config
        self.transport = transport or urlopen_transport
        self.log = log or (lambda msg: None)
        self.cancelled = cancelled or (lambda: False)
        self.sleep = sleep
        self._token = None

    # ------------------------------------------------------------ 鍵
    def refresh(self):
        form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": self.config.refresh_token,
                                       "client_id": self.config.app_key}).encode("ascii")
        status, _h, r = self._open(TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, form, RPC_TIMEOUT)
        try:
            d = json.loads(self._read_all(r).decode("utf-8", "replace") or "{}")
        except ValueError:
            d = {}
        tok = d.get("access_token") if isinstance(d, dict) else None
        if not isinstance(tok, str) or not tok:
            raise DropboxError("鍵の返事に access_token がありません", -1)
        self._token = tok

    # ------------------------------------------------------------ 通信の 1 回
    def _check(self):
        if self.cancelled():
            raise Cancelled()

    @staticmethod
    def _read_all(r, cap=None):
        try:
            data = r.read() if cap is None else r.read(cap)
        except OSError as e:
            raise DropboxError("通信が切れました(%s)" % e.__class__.__name__, 0)
        finally:
            _close(r)
        return data

    def _open(self, url, headers, body, timeout):
        """1 回の POST -> (status, headers, 読む口)。2xx でなければ本文を読んで DropboxError"""
        status, h, r = self.transport(url, headers, body, timeout)
        if status in (200, 206):
            return status, h, r
        try:
            text = self._read_all(r, ERROR_BODY_MAX).decode("utf-8", "replace")
        except DropboxError:
            text = ""
        raise DropboxError(error_text(status, text), status, text)

    def _auth(self, extra):
        h = {"Authorization": "Bearer " + self._token}
        h.update(extra)
        return h

    def _with_retry(self, endpoint, attempts, once):
        if self._token is None:
            self.refresh()
        refreshed = False
        attempt = 0
        while True:
            attempt += 1
            self._check()
            try:
                return once()
            except DropboxError as e:
                if e.status == 401 and not refreshed and not missing_scope(e.body):
                    refreshed = True
                    self.refresh()
                    continue
                if not e.retryable or attempt >= attempts:
                    raise
                self.log("Dropbox: %s がうまくいきませんでした(%d)。やり直します %d" % (endpoint, e.status, attempt))
                self._wait(attempt)

    def _wait(self, attempt):
        ms = 2000 * attempt * attempt
        for _ in range(0, ms, 200):
            self._check()
            self.sleep(0.2)

    # ------------------------------------------------------------ RPC(本文が JSON)
    def rpc(self, endpoint, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")

        def once():
            _s, _h, r = self._open(RPC_BASE + endpoint, self._auth({"Content-Type": "application/json"}), body, RPC_TIMEOUT)
            return _parse(self._read_all(r))
        return self._with_retry(endpoint, RETRIES, once)

    def list_folder(self, path):
        """フォルダの直下の一覧(続きも)-> entries のリストか None(フォルダが無い)"""
        try:
            d = self.rpc("files/list_folder", {"path": path, "recursive": False, "include_deleted": False, "limit": 500})
        except DropboxError as e:
            if e.not_found:
                return None
            raise
        out = []
        for _page in range(MAX_PAGES):
            out += [e for e in (d.get("entries") or []) if isinstance(e, dict)]
            cur = d.get("cursor")
            if not (d.get("has_more") and isinstance(cur, str) and cur):
                break
            d = self.rpc("files/list_folder/continue", {"cursor": cur})
        return out

    def latest_cursor(self, path=""):
        """path より下(下のフォルダも)の今の位置(一覧は読まない)-> カーソルの文字列"""
        d = self.rpc("files/list_folder/get_latest_cursor", {"path": path, "recursive": True, "include_deleted": True})
        cur = d.get("cursor") if isinstance(d, dict) else None
        if not isinstance(cur, str) or not cur:
            raise DropboxError("位置の返事にカーソルがありません", -1)
        return cur

    def longpoll(self, cursor, timeout):
        """カーソルの後に変化があるまで最大 timeout 秒待つ(1 回だけ。やり直しは呼ぶ側)-> {"changes": bool, "backoff": 秒か None}。
        鍵を付けない口(Dropbox の決まり)。API の回数の上限にほぼ数えられない"""
        self._check()
        body = json.dumps({"cursor": cursor, "timeout": int(timeout)}).encode("utf-8")
        _s, _h, r = self._open(NOTIFY_BASE + "files/list_folder/longpoll", {"Content-Type": "application/json"}, body, int(timeout) + LONGPOLL_EXTRA)
        d = _parse(self._read_all(r))
        back = d.get("backoff") if isinstance(d, dict) else None
        return {"changes": bool(isinstance(d, dict) and d.get("changes")), "backoff": back if isinstance(back, int) and back > 0 else None}

    def get_metadata(self, path):
        """1 つのファイルの情報か None(無い)"""
        try:
            return self.rpc("files/get_metadata", {"path": path})
        except DropboxError as e:
            if e.not_found:
                return None
            raise

    def delete(self, path):
        """消す -> True(消した)/ False(もう無い = 消えているのと同じ)。DELETE_OK の外は DropboxError(負の status = このプログラムが断った)"""
        if not isinstance(path, str) or not DELETE_OK.match(path) or "/../" in path + "/" or "/./" in path + "/":
            raise DropboxError("消してよい場所ではありません: %s" % str(path)[:80], -1)
        try:
            self.rpc("files/delete_v2", {"path": path})
            return True
        except DropboxError as e:
            if e.not_found:
                return False
            raise

    # ------------------------------------------------------------ 上げる
    def _content(self, endpoint, arg, data):
        def once():
            h = self._auth({"Dropbox-API-Arg": arg_header(arg), "Content-Type": "application/octet-stream"})
            _s, _h, r = self._open(CONTENT_BASE + endpoint, h, data, CONTENT_TIMEOUT)
            return _parse(self._read_all(r))
        return self._with_retry(endpoint, RETRIES, once)

    def upload_bytes(self, data, path, overwrite=False):
        """小さい物を上げる -> Dropbox に置かれた名前(autorename で変わることがある)"""
        d = self._content("files/upload", commit_arg(path, overwrite), bytes(data))
        return d.get("name") or path.rsplit("/", 1)[-1]

    def upload(self, local, path, overwrite=False, progress=None):
        """ファイルを上げる(150MB を超えたら session で 8MB ずつ)-> 置かれた名前"""
        size = os.path.getsize(local)
        with open(local, "rb") as f:
            if size <= SINGLE_LIMIT:
                d = self._content("files/upload", commit_arg(path, overwrite), f.read())
                if progress:
                    progress(size)
                return d.get("name") or path.rsplit("/", 1)[-1]
            sid, off = None, 0
            while off < size:
                f.seek(off)
                buf = f.read(min(CHUNK, size - off))
                if not buf:
                    raise DropboxError("ファイルを最後まで読めませんでした(上げる途中で変わった可能性があります)", -1)
                if sid is None:
                    sid = self._content("files/upload_session/start", {"close": False}, buf).get("session_id")
                    if not sid:
                        raise DropboxError("upload_session/start の返事に session_id がありません", -1)
                else:
                    try:
                        self._content("files/upload_session/append_v2", {"cursor": {"session_id": sid, "offset": off}, "close": False}, buf)
                    except DropboxError as e:
                        if _correct_offset(e.body) != off + len(buf):   # やり直しの前の回が実は届いていた = そのまま先へ
                            raise
                off += len(buf)
                if progress:
                    progress(off)
            d = self._content("files/upload_session/finish", {"cursor": {"session_id": sid, "offset": size}, "commit": commit_arg(path, overwrite)}, b"")
            return d.get("name") or path.rsplit("/", 1)[-1]

    # ------------------------------------------------------------ 取る
    def _download_request(self, path, start):
        h = self._auth({"Dropbox-API-Arg": arg_header({"path": path}), "Content-Type": "application/octet-stream"})
        if start > 0:
            h["Range"] = "bytes=%d-" % start
        return self._open(CONTENT_BASE + "files/download", h, b"", DOWNLOAD_TIMEOUT)

    def read_small(self, path, cap=1024 * 1024):
        """小さい物を先頭から cap バイトまで -> (中身, cap を超えていたか)か None(無い)"""
        def once():
            _s, _h, r = self._download_request(path, 0)
            data = self._read_all(r, cap + 1)
            return (data[:cap], len(data) > cap)
        try:
            return self._with_retry("files/download", RETRIES, once)
        except DropboxError as e:
            if e.not_found:
                return None
            raise

    def download(self, path, part, rev=None, progress=None):
        """大きい物を part へ(切れたら続きから)-> True か False(無い)。rev が違えば DropboxError(-1 = 置き換わった)"""
        if os.path.exists(part):
            os.remove(part)

        def once():
            have = os.path.getsize(part) if os.path.exists(part) else 0
            status, h, r = self._download_request(path, have)
            try:
                meta = _parse(h.get("dropbox-api-result", "").encode("utf-8")) or {}
                got_rev = meta.get("rev")
                if rev and got_rev and got_rev != rev:
                    raise DropboxError("受け取っている間に、Dropbox の側で作り直されました。もう一度 [受け取る] を押してください", -1)
                resume = have > 0 and status == 206
                done = have if resume else 0
                with open(part, "ab" if resume else "wb") as out:
                    while True:
                        self._check()
                        try:
                            buf = r.read(READ_STEP)
                        except (OSError, http.client.HTTPException) as e:   # IncompleteRead は OSError ではない
                            raise DropboxError("通信が切れました(%s)" % e.__class__.__name__, 0)
                        if not buf:
                            break
                        out.write(buf)
                        done += len(buf)
                        if progress:
                            progress(done)
            finally:
                _close(r)
            size = meta.get("size")
            if isinstance(size, int) and not isinstance(size, bool) and done < size:   # 途中で切れて読みが短く終わった(10-23: 欠けた物を済みにしていた)= 続きから取り直す
                raise DropboxError("通信が切れました(%d / %d バイトで終わりました)" % (done, size), 0)
            return True
        try:
            return self._with_retry("files/download", DOWNLOAD_RETRIES, once)
        except DropboxError as e:
            if os.path.exists(part):
                os.remove(part)
            if e.not_found:
                return False
            raise
        except Cancelled:
            if os.path.exists(part):
                os.remove(part)
            raise


def _parse(raw):
    text = (raw or b"").decode("utf-8", "replace").strip()
    if not text or text == "null":
        return {}
    try:
        d = json.loads(text)
    except ValueError:
        raise DropboxError("Dropbox の返事が読めません", -1)
    return d if isinstance(d, dict) else {}


def _close(r):
    try:
        r.close()
    except Exception:   # 閉じられなくても止めない
        pass
