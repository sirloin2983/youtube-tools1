#!/usr/bin/env python3
"""切り抜き依頼(request-sender)の鍵を作る(ユーザーの PC で1回だけ。標準ライブラリだけ)。

    python dev/dropbox_auth.py <App key> [--out request-sender/config.json]

Dropbox の App console で作ったアプリ(Scoped access・App folder・権限は files.content.write・files.content.read・files.metadata.read)の App key を渡す。
(読みの2つは、友人のプログラムの「受け取る」が「/出力/」のパックを一覧にして取ってくるため。v1.1.0 から)
PKCE(secret を使わない OAuth の方式)で承認して refresh token を得て、config.json に {"appKey", "refreshToken"} を書く。
- 鍵の値は画面に出さない。config.json は .gitignore と dev/push_helper.py の検査でコミットされない
- 無効にするときは https://www.dropbox.com/account/connected_apps でアプリの接続を切る
手順の全体: request-sender/README.txt の「鍵を作る」。設計: docs/design/friend-intake.md の 4・7
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "request-sender", "config.json")
AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
# 要る権限(送る = write、受け取る = 一覧の metadata.read と中身の content.read)。承認の URL の scope に付けて頼む
WANTED_SCOPES = ("files.content.write", "files.content.read", "files.metadata.read")
# 承認のときに Dropbox が付けることのある、害の無い権限(アカウントの名前を読むだけ)
HARMLESS_SCOPES = {"account_info.read"}
_UNRESERVED = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_APP_KEY = re.compile(r"^[a-z0-9]{8,32}$")


def make_verifier():
    """RFC 7636 の code_verifier(43〜128 文字の unreserved)"""
    v = secrets.token_urlsafe(64)[:96]
    assert _UNRESERVED.match(v)
    return v


def challenge_for(verifier):
    """S256: BASE64URL(SHA256(verifier))、= なし"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(app_key, challenge):
    q = urllib.parse.urlencode({
        "client_id": app_key,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "token_access_type": "offline",   # refresh token をもらう
        "scope": " ".join(WANTED_SCOPES),   # 頼む権限(App console の Permissions にチェックが無いものは付かない)
    })
    return AUTHORIZE_URL + "?" + q


def token_request_body(app_key, code, verifier):
    return urllib.parse.urlencode({
        "code": code.strip(),
        "grant_type": "authorization_code",
        "code_verifier": verifier,
        "client_id": app_key,
    }).encode("ascii")


def exchange(app_key, code, verifier, urlopen=urllib.request.urlopen):
    """-> Dropbox の返事(dict)。失敗は RuntimeError(鍵の値は含めない)"""
    req = urllib.request.Request(TOKEN_URL, data=token_request_body(app_key, code, verifier),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            info = json.loads(e.read().decode("utf-8", "replace"))
            msg = "%s: %s" % (info.get("error", ""), info.get("error_description", ""))
        except (ValueError, OSError):
            msg = str(e)
        raise RuntimeError("Dropbox が断りました(%s)。コードは一度しか使えません。最初からやり直してください" % msg)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("Dropbox につながりません: %s" % e)
    if not isinstance(data, dict) or not data.get("refresh_token"):
        raise RuntimeError("Dropbox の返事に refresh_token がありません(token_access_type=offline が効いていない?)")
    return data


def extra_scopes(scope_text):
    """要る3つと害の無いもの以外の権限。-> 並べた list"""
    got = set((scope_text or "").split())
    return sorted(got - set(WANTED_SCOPES) - HARMLESS_SCOPES)


def missing_scopes(scope_text):
    """要る3つのうち付いていないもの。-> 要る順の list(返事に scope が無いときは確かめられないので空)"""
    if not scope_text:
        return []
    got = set(scope_text.split())
    return [x for x in WANTED_SCOPES if x not in got]


def write_config(path, app_key, refresh_token):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"appKey": app_key, "refreshToken": refresh_token}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None, input_fn=input, urlopen=urllib.request.urlopen, out=print):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="切り抜き依頼の鍵(config.json)を作る")
    ap.add_argument("app_key", help="Dropbox の App console の App key")
    ap.add_argument("--out", default=DEFAULT_OUT, help="書き出す config.json(既定: request-sender/config.json)")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    a = ap.parse_args(argv)
    app_key = a.app_key.strip()
    if not _APP_KEY.match(app_key):
        out("App key の形ではありません(英小文字と数字。App secret ではなく App key を渡してください)")
        return 2

    verifier = make_verifier()
    url = authorize_url(app_key, challenge_for(verifier))
    out("1. 次の URL をブラウザで開いて、Dropbox にログインして「許可」を押してください:")
    out("   " + url)
    if not a.no_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:   # 開けなくても URL を手で開けばよい
            pass
    code = input_fn("2. 表示されたコードを貼って Enter: ").strip()
    if not code:
        out("コードが空です。やめました")
        return 2
    try:
        data = exchange(app_key, code, verifier, urlopen=urlopen)
    except RuntimeError as e:
        out("[エラー] %s" % e)
        return 1
    extra = extra_scopes(data.get("scope"))
    if extra:
        out("[注意] 鍵に要らない権限が付いています: %s" % " ".join(extra))
        out("       App console の Permissions で %s だけにして、もう一度作ることをすすめます" % "・".join(WANTED_SCOPES))
    missing = missing_scopes(data.get("scope"))
    if missing:
        out("[注意] 鍵に足りない権限があります: %s" % " ".join(missing))
        out("       App console の Permissions でチェックして「Submit」を押してから、もう一度作ってください"
            "(このままでは友人のプログラムの「受け取る」が使えません)")
    write_config(a.out, app_key, data["refresh_token"])
    out("3. 書きました: %s(鍵の値は表示しません。人に見せない・コミットしない)" % a.out)
    out("   次は request-sender\\build.bat → dist\\RequestSender.zip を友人に渡す")
    return 0


if __name__ == "__main__":
    sys.exit(main())
