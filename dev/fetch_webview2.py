# -*- coding: utf-8 -*-
"""友人のアプリ FriendApp.exe が使う WebView2 の部品(DLL 3 つ)を NuGet の公式パッケージから取る(F3-1。notes:plan/f1-friend-requirements.md の C-1-1)。

    py -3.12 dev/fetch_webview2.py [--out friend-apps/launcher/lib]

- 版と SHA-256 はここに固定(変えるときは両方)。違えば置かない
- 置く物: Microsoft.Web.WebView2.Core.dll・Microsoft.Web.WebView2.WinForms.dll(lib/net462)・WebView2Loader.dll(runtimes/win-x64/native)
- 置き場所は git に入れない(.gitignore の friend-apps/launcher/lib/)。friend-apps/launcher/build.bat が流し、dev/build_friend_zip.py が exe の隣へ写す
- もう同じ版があれば取らない(lib/VERSION の中身が版と同じ)
"""
import argparse
import hashlib
import io
import os
import sys
import urllib.request
import zipfile

VERSION = "1.0.4022.49"
SHA256 = "ee9de67e5bb9ef3a96c5689b2efc8188e2df160a0e79234c0404243782fde5fb"
URL = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/%s/microsoft.web.webview2.%s.nupkg" % (VERSION, VERSION)
MEMBERS = {"lib/net462/Microsoft.Web.WebView2.Core.dll": "Microsoft.Web.WebView2.Core.dll",
           "lib/net462/Microsoft.Web.WebView2.WinForms.dll": "Microsoft.Web.WebView2.WinForms.dll",
           "runtimes/win-x64/native/WebView2Loader.dll": "WebView2Loader.dll"}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO, "friend-apps", "launcher", "lib")


def have(out):
    try:
        with open(os.path.join(out, "VERSION"), encoding="ascii") as f:
            ok = f.read().strip() == VERSION
    except OSError:
        return False
    return ok and all(os.path.isfile(os.path.join(out, n)) for n in MEMBERS.values())


def extract(data, out):
    """パッケージ(zip)から 3 つだけ書く。-> 書いた名前"""
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("WebView2 のパッケージの SHA-256 が違います(版 %s)" % VERSION)
    os.makedirs(out, exist_ok=True)
    got = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member, name in MEMBERS.items():
            with z.open(member) as src, open(os.path.join(out, name), "wb") as dst:
                dst.write(src.read())
            got.append(name)
    with open(os.path.join(out, "VERSION"), "w", encoding="ascii") as f:
        f.write(VERSION)
    return got


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    if have(a.out):
        print("WebView2 %s はもうあります: %s" % (VERSION, a.out))
        return 0
    print("WebView2 %s を取ります: %s" % (VERSION, URL))
    with urllib.request.urlopen(URL, timeout=120) as r:   # noqa: S310  (固定の https の URL)
        data = r.read()
    try:
        names = extract(data, a.out)
    except ValueError as e:
        print(e)
        return 1
    print("置きました: %s" % "・".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
