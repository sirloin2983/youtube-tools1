# -*- coding: utf-8 -*-
"""配る前の検査(dev/friend_preflight.py)の通信の差し替え。検査が、展開した写しの python/Lib/site-packages/sitecustomize.py として置く
(配る zip には入らない。検査は zip に sitecustomize.py が無いことも確かめる)。標準ライブラリだけ。

環境変数 YTT_PREFLIGHT_SHIM(設定の JSON のパス)があるときだけ、urllib の https と http をここで受ける:
  - mirror = {URL: この PC のファイル}: 初回の準備の取得(fetch.json の URL)を、検査が用意したファイルから返す(Range つき = 続きからも本物と同じ)
  - dropbox = 一時フォルダ: Dropbox の API(鍵・list_folder・get_latest_cursor・longpoll・get_metadata・delete_v2・upload・upload_session・download)を
    そのフォルダの読み書きで返す(本物の Dropbox へは書かない。フォルダの中 = Dropbox のアプリのフォルダの中と同じ形)
  - それ以外の https と、127.0.0.1・localhost 以外の http は断る(URLError)。つないだ先は log(1 行 1 件の JSON)に残す
  - net = 真(--youtube)なら、それ以外の https は本物へ通す(Dropbox は偽物のまま)
アプリのコードは変えない(差し替えるのは urllib の口だけ = アプリの取得・同期・更新の流れはそのまま動く)。
"""
import email.message
import hashlib
import io
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.response

ENV = "YTT_PREFLIGHT_SHIM"
DBX_HOSTS = ("api.dropboxapi.com", "content.dropboxapi.com", "notify.dropboxapi.com")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
HASH_BLOCK = 4 * 1024 * 1024


def _load():
    p = os.environ.get(ENV)
    if not p:
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


class _Shim:
    def __init__(self, conf):
        self.mirror = dict(conf.get("mirror") or {})
        self.root = conf.get("dropbox") or ""
        self.log_path = conf.get("log") or ""
        self.net = bool(conf.get("net"))   # 本物の YouTube で試す形: Dropbox と取得元のほかは本物へ通す
        self.real_https = None
        self.lock = threading.RLock()   # 記録(note)は Dropbox の口の中からも呼ぶ
        self.sessions = {}
        self.hashes = {}

    # ---- 記録
    def note(self, kind, url, extra=None):
        if not self.log_path:
            return
        d = {"at": round(time.time(), 3), "kind": kind, "url": url}
        d.update(extra or {})
        with self.lock, open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    # ---- 返事
    @staticmethod
    def resp(url, code, body=b"", headers=None, fp=None):
        msg = email.message.Message()
        for k, v in (headers or {}).items():
            msg[k] = v
        if fp is None:
            fp = io.BytesIO(body)
            msg["Content-Length"] = str(len(body))
        r = urllib.response.addinfourl(fp, msg, url, code)
        r.msg = "OK" if code < 400 else "Error"
        return r

    def json_resp(self, url, obj, code=200, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self.resp(url, code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), h)

    def error(self, req, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        raise urllib.error.HTTPError(req.full_url, code, "Error", email.message.Message(), io.BytesIO(body))

    # ---- 取得(mirror)
    def https(self, req):
        url = req.full_url
        host = urllib.parse.urlsplit(url).hostname or ""
        if url in self.mirror:
            return self.serve_file(req, self.mirror[url])
        if host in DBX_HOSTS:
            return self.dropbox(req)
        if self.net:
            self.note("net", url)
            return self.real_https(req)
        self.note("blocked", url)
        raise urllib.error.URLError("配る前の検査: ネットにはつなぎません(%s)" % host)

    def serve_file(self, req, path, headers=None):
        size = os.path.getsize(path)
        start = _range_start(req.get_header("Range"))
        h = dict(headers or {})
        h["Content-Type"] = h.get("Content-Type", "application/octet-stream")
        if start >= size and start > 0:
            self.note("mirror-416", req.full_url)
            self.error(req, 416, {"error": "range"})
        f = open(path, "rb")
        f.seek(start)
        h["Content-Length"] = str(size - start)
        if start:
            h["Content-Range"] = "bytes %d-%d/%d" % (start, size - 1, size)
        self.note("mirror" if req.full_url in self.mirror else "dropbox-download", req.full_url, {"from": start})
        return self.resp(req.full_url, 206 if start else 200, headers=h, fp=f)

    # ---- Dropbox(フォルダで代わりに)
    def local(self, path):
        parts = [p for p in str(path or "").replace("\\", "/").split("/") if p]
        if any(p in (".", "..") or ":" in p for p in parts):
            raise ValueError("bad path")
        return os.path.join(self.root, *parts), "/" + "/".join(parts)

    def meta(self, p, disp):
        name = disp.rsplit("/", 1)[-1]
        ident = "id:" + hashlib.sha1(disp.lower().encode("utf-8")).hexdigest()[:16]
        if os.path.isdir(p):
            return {".tag": "folder", "name": name, "path_display": disp, "path_lower": disp.lower(), "id": ident}
        st = os.stat(p)
        mod = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
        return {".tag": "file", "name": name, "path_display": disp, "path_lower": disp.lower(), "id": ident, "size": st.st_size,
                "rev": "%015x" % (st.st_mtime_ns // 1000), "server_modified": mod, "client_modified": mod, "content_hash": self.chash(p, st)}

    def chash(self, p, st):
        key = (p, st.st_size, st.st_mtime_ns)
        if key not in self.hashes:
            outer = hashlib.sha256()
            with open(p, "rb") as f:
                for b in iter(lambda: f.read(HASH_BLOCK), b""):
                    outer.update(hashlib.sha256(b).digest())
            self.hashes[key] = outer.hexdigest()
        return self.hashes[key]

    def snapshot(self):
        """フォルダ全体の今の形(名前・大きさ・更新時刻)-> カーソルの代わりの文字列"""
        h = hashlib.sha1()
        for d, _ds, fs in sorted(os.walk(self.root)):
            for n in sorted(fs):
                if not n.endswith(".shim-part"):
                    try:
                        st = os.stat(os.path.join(d, n))
                    except OSError:
                        continue
                    h.update(("%s|%s|%d|%d\n" % (os.path.relpath(d, self.root), n, st.st_size, st.st_mtime_ns)).encode("utf-8"))
        return h.hexdigest()

    def not_found(self, req):
        self.error(req, 409, {"error_summary": "path/not_found/..", "error": {".tag": "path", "path": {".tag": "not_found"}}})

    def dropbox(self, req):
        url = req.full_url
        ep = urllib.parse.urlsplit(url).path.lstrip("/")
        if ep == "oauth2/token":
            self.note("dropbox", url)
            return self.json_resp(url, {"access_token": "preflight", "token_type": "bearer", "expires_in": 14400})
        if not ep.startswith("2/"):
            self.note("blocked", url)
            raise urllib.error.URLError("配る前の検査: 知らない Dropbox の口です")
        ep = ep[2:]
        data = req.data or b""
        if "content.dropboxapi.com" in url:
            arg = json.loads(req.get_header("Dropbox-api-arg") or "{}")
        else:
            arg = json.loads(data.decode("utf-8") or "{}") if data else {}
        self.note("dropbox", url, {"endpoint": ep, "path": arg.get("path") or arg.get("from_path") or ""})
        if ep == "files/list_folder/get_latest_cursor":
            return self.json_resp(url, {"cursor": self.snapshot()})
        if ep == "files/list_folder/longpoll":   # 鍵の口の lock を持たずに待つ(待つ間もほかの口は動く)
            end = time.time() + min(int(arg.get("timeout") or 30), 480)
            while time.time() < end and self.snapshot() == arg.get("cursor"):
                time.sleep(0.5)
            return self.json_resp(url, {"changes": self.snapshot() != arg.get("cursor")})
        with self.lock:
            return self.dropbox_call(req, ep, arg, data)

    def dropbox_call(self, req, ep, arg, data):  # lint: long Dropbox の口ごとの分かれ道(1 か所で読めるように)
        url = req.full_url
        if ep == "files/list_folder":
            p, _disp = self.local(arg.get("path"))
            if not os.path.isdir(p):
                self.not_found(req)
            ents = [self.meta(os.path.join(p, n), (_disp.rstrip("/") + "/" + n)) for n in sorted(os.listdir(p))]
            return self.json_resp(url, {"entries": ents, "cursor": "preflight", "has_more": False})
        if ep == "files/list_folder/continue":
            return self.json_resp(url, {"entries": [], "cursor": "preflight", "has_more": False})
        if ep == "files/get_metadata":
            p, disp = self.local(arg.get("path"))
            if not os.path.exists(p):
                self.not_found(req)
            return self.json_resp(url, self.meta(p, disp))
        if ep == "files/delete_v2":
            p, disp = self.local(arg.get("path"))
            if not os.path.exists(p):
                self.not_found(req)
            m = self.meta(p, disp)
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            return self.json_resp(url, {"metadata": m})
        if ep == "files/upload":
            return self.json_resp(url, self.commit(arg, data))
        if ep == "files/upload_session/start":
            sid = "s%d" % (len(self.sessions) + 1)
            self.sessions[sid] = bytearray(data)
            return self.json_resp(url, {"session_id": sid})
        if ep == "files/upload_session/append_v2":
            cur = arg.get("cursor") or {}
            buf = self.sessions.get(cur.get("session_id"))
            if buf is None:
                self.error(req, 409, {"error_summary": "not_found/..", "error": {".tag": "not_found"}})
            if cur.get("offset") != len(buf):
                self.error(req, 409, {"error_summary": "incorrect_offset/..", "error": {".tag": "incorrect_offset", "correct_offset": len(buf)}})
            buf.extend(data)
            return self.json_resp(url, {})
        if ep == "files/upload_session/finish":
            cur = arg.get("cursor") or {}
            buf = self.sessions.pop(cur.get("session_id"), None)
            if buf is None:
                self.error(req, 409, {"error_summary": "not_found/..", "error": {".tag": "not_found"}})
            return self.json_resp(url, self.commit(arg.get("commit") or {}, bytes(buf)))
        if ep == "files/download":
            p, disp = self.local(arg.get("path"))
            if not os.path.isfile(p):
                self.not_found(req)
            res = json.dumps(self.meta(p, disp), ensure_ascii=True)
            return self.serve_file(req, p, {"Dropbox-API-Result": res})
        self.note("blocked", url)
        raise urllib.error.URLError("配る前の検査: 知らない Dropbox の口です(%s)" % ep)

    def commit(self, arg, data):
        p, disp = self.local(arg.get("path"))
        if os.path.exists(p) and arg.get("mode") != "overwrite":
            stem, ext = os.path.splitext(p)
            n = 1
            while os.path.exists("%s (%d)%s" % (stem, n, ext)):
                n += 1
            p = "%s (%d)%s" % (stem, n, ext)
            disp = disp.rsplit("/", 1)[0] + "/" + os.path.basename(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".shim-part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        return self.meta(p, disp)


def _range_start(h):
    if not h or not str(h).startswith("bytes="):
        return 0
    try:
        return max(0, int(str(h)[6:].split("-", 1)[0] or 0))
    except ValueError:
        return 0


def install():
    conf = _load()
    if conf is None:
        return None
    shim = _Shim(conf)
    orig_http, orig_https = urllib.request.HTTPHandler.http_open, urllib.request.HTTPSHandler.https_open
    shim.real_https = lambda req: orig_https(urllib.request.HTTPSHandler(), req)

    def https_open(self, req):
        return shim.https(req)

    def http_open(self, req):
        host = urllib.parse.urlsplit(req.full_url).hostname or ""
        if host in LOCAL_HOSTS:
            return orig_http(self, req)
        shim.note("blocked", req.full_url)
        raise urllib.error.URLError("配る前の検査: ネットにはつなぎません(%s)" % host)

    urllib.request.HTTPSHandler.https_open = https_open
    urllib.request.HTTPHandler.http_open = http_open
    shim.note("installed", "", {"pid": os.getpid()})
    return shim


install()
