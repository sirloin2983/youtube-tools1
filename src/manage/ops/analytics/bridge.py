"""Apps Script の連携(gas/Code.gs のウェブアプリ)との通信。標準ライブラリだけ。

約束(gas/Code.gs の先頭と同じ): POST <URL> に JSON 文字列 {"secret", "op", ...}。応答は JSON。失敗は {"ok": false, "error", "message"}。
Apps Script のウェブアプリは POST に 302(googleusercontent.com へ)で応える。urllib は 302 を本文なしの GET でたどる(それが正しい受け取り方)。
- 合言葉を送る先は script.google.com の /macros/s/…/exec だけ(設定の間違いで別の所へ合言葉を送らない)
- 合言葉はログ・画面・例外の文に入れない
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

URL_RE = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]{20,200}/exec$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
MAX_RESPONSE = 32 * 1024 * 1024
REDIRECT_HOSTS = ("script.google.com", "script.googleusercontent.com")


class BridgeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def check_url(url):
    url = (url or "").strip()
    if not URL_RE.match(url):
        raise BridgeError("bad_url", "連携の URL は https://script.google.com/macros/s/…/exec の形で入れてください(デプロイの「ウェブアプリ」の URL)")
    return url


def check_secret(secret):
    secret = (secret or "").strip()
    if not SECRET_RE.match(secret):
        raise BridgeError("bad_secret", "合言葉は Apps Script の makeSecret が出した文字列(英数字・-・_ の 32 文字以上)を入れてください")
    return secret


class _Redirect(urllib.request.HTTPRedirectHandler):
    """302 は Google の決まった場所へだけたどる"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname or ""
        if not newurl.startswith("https://") or host not in REDIRECT_HOSTS:
            raise BridgeError("redirect", "連携の応答が知らない場所へ転送されました(%s)" % host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Bridge:
    def __init__(self, url, secret, timeout=90, opener=None):
        self.url, self.secret = check_url(url), check_secret(secret)
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(_Redirect())

    def call(self, op, **kw):
        body = json.dumps(dict(kw, secret=self.secret, op=op), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST", headers={"Content-Type": "text/plain; charset=utf-8"})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw = r.read(MAX_RESPONSE + 1)
        except BridgeError:
            raise
        except urllib.error.HTTPError as e:
            raise BridgeError("http", "連携が HTTP %d を返しました(デプロイのアクセスが「全員」か確かめてください)" % e.code)
        except (urllib.error.URLError, OSError) as e:
            raise BridgeError("network", "連携につながりません: %s" % (getattr(e, "reason", None) or e.__class__.__name__))
        if len(raw) > MAX_RESPONSE:
            raise BridgeError("too_big", "連携の応答が大きすぎます")
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            head = raw[:200].decode("utf-8", "replace")
            hint = "(Google のログイン画面が返りました。デプロイのアクセスを「全員」にしてください)" if "<html" in head.lower() else ""
            raise BridgeError("bad_response", "連携の応答が JSON ではありません%s" % hint)
        if not isinstance(obj, dict):
            raise BridgeError("bad_response", "連携の応答の形が違います")
        if obj.get("ok") is not True:
            raise BridgeError(str(obj.get("error") or "failed"), str(obj.get("message") or "連携が断りました"))
        return obj

    def ping(self):
        return self.call("ping")

    def list_raw(self, since=None):
        """since(ISO)より後に更新された raw の一覧を全部(60 件ずつ。境目の取りこぼしを避けて 1 秒前から重ねて取り、ID で重なりを除く)"""
        out, seen = [], set()
        cur = since
        for _ in range(100):
            files = self.call("list", since=cur).get("files") or []
            new = [f for f in files if isinstance(f, dict) and f.get("id") and (f["id"], f.get("updated")) not in seen]
            for f in new:
                seen.add((f["id"], f.get("updated")))
                out.append(f)
            if len(files) < 60 or not new:
                break
            cur = files[-1].get("updated")
        return out

    def get_raw(self, file_id):
        r = self.call("get", id=file_id)
        if not isinstance(r.get("content"), str):
            raise BridgeError("bad_response", "raw の中身がありません")
        return r

    def report(self, kind, date, text, html, source, notify=True):
        return self.call("report", kind=kind, date=date, text=text[:4500], html=html, source=source, notify=notify)
