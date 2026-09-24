"""ローカルサーバー(127.0.0.1)の安全検査。スタジオ・文字起こし・入口で同じ規則を1か所に持つ。

- Host      … DNS rebinding 対策。「localhost:<port>」「127.0.0.1:<port>」だけ
- Origin    … 他サイトからの書き込み(CSRF)対策。送られてきたら「http://」+ 許可した Host と完全に一致するものだけ
- Sec-Fetch-Site … 他サイトからの読み取り・API の消費を断る(同じ画面からの same-origin と、アドレス欄からの none だけ)
- 画面への移動 … 他のツールの画面のリンクで、画面(/ と /index.html)を新しいタブで開くのだけは許す。
  ポートが違うだけでもブラウザは same-site(localhost と 127.0.0.1 なら cross-site)を送るため。URL で処理は始まらない(docs/pipeline.md の 3)。
  埋め込み(iframe)は Sec-Fetch-Dest と PAGE_HEADERS(X-Frame-Options / frame-ancestors)で断る
"""

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
