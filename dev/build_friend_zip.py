# -*- coding: utf-8 -*-
"""友人の PC に配る zip(新しいアプリ FriendApp + ② + ① の Python のコード + 埋め込み用 Python + 部品)を作る道具(設計 notes:docs/design/f1-build.md の 2・3 節)。

zip の中(アプリのフォルダ <任意>/FriendApp/ にそのまま展開する形。3 節 (f1i)):
    FriendApp.exe    友人のアプリの窓(friend-apps/launcher/build/。WebView2 の DLL 3 つ = Microsoft.Web.WebView2.Core.dll・.WinForms.dll・WebView2Loader.dll と一緒に直下)。
                     無い・launcher の C# より古ければ friend-apps/launcher/build.bat を流してから入れる
    members.json     配信者の名簿(friend-apps/holo-colors/members.json の写し。友人のアプリが places.py で直下から読んで YTT_HOLO_MEMBERS に渡す)
    FriendApp-はじめに.txt  入れ方とアプリのフォルダの説明(friend-apps/launcher/INSTALL.txt)
    python/        公式の埋め込み用 Python 3.10 + python310._pth(Lib/site-packages と ../src を足す)+ wheel を展開した部品(numpy・sherpa-onnx・streamlink と依存)
    src/           git が管理している src のファイルのうち friendapp・ytt・flow・pipeline・ui-kit の層と名簿 src/editor/hololive-roster.json(tests/・__pycache__ は外す。作業データ・追跡外のファイルは入らない)
    tools/whisper.cpp-<版>-vulkan/   ユーザーの PC で作った whisper.cpp(build.json の files と SHA-256 が合う物だけ)
    fetch.json     初回に取る物の表(モデル・llama.cpp・ffmpeg・yt-dlp・Deno)。モデルと llama.cpp は tx_engines・diarize の表を import して読むだけ
    manifest.json  全体の版・各ファイルの SHA-256
config.json(Dropbox の鍵)は入れない。--first --with-key のときだけ friend-apps/launcher/config.json(git の外)を zip の直下へ入れる(3 節 (f1g)。友人の PC もアプリのフォルダの直下の config.json を読む)。

出力:
    --out D: 出力先を D に(テスト・手元の確かめ。FriendApp-<版>.zip + latest.json を D に書く)
    --first: friend-apps/launcher/dist/FriendApp-<版>-first.zip(latest.json は書かない。手で渡す)
    --publish(--out なし): <ホームの設定の intake.folder>/更新/FriendApp-<版>.zip + latest.json(古い zip は 2 つ残して消す。(f1h))。
        intake.folder は Dropbox の中 = 友人のアプリが「更新」で取る場所。ユーザーの OK のあとだけ。--out も --first も無い呼び出しは断る。
        置く前に必ず配る前の検査(dev/friend_preflight.py = 友人の PC と同じ状態で通しで試す)を流し、落ちたら置かない(抜けるのは --skip-preflight の明示だけ)

Python の本体・wheel・ffmpeg などはキャッシュのフォルダ(--cache。既定 %LOCALAPPDATA%/youtube-tools/app/friend-build-cache)から読み、
無ければ取りに行く(https の固定の URL・wheel は pip download)。ffmpeg・yt-dlp・Deno・Python の本体は表に SHA-256 が無いので、
キャッシュに取った物の大きさと SHA-256 を fetch.json・manifest.json に書く(取ったときに 1 回だけ信じる。以後はキャッシュの記録と照らす)。

    py -3.12 dev/build_friend_zip.py [--out D | --publish] [--cache C] [--first [--with-key]] [--no-fetch]
終了コード 0 済み / 1 失敗 / 2 引数
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
DEV = os.path.dirname(os.path.abspath(__file__))
if DEV not in sys.path:
    sys.path.insert(0, DEV)
from ytt import datadir, version as _version, workdata  # noqa: E402
from pipeline.transcribe import diarize as _diarize, tx_engines as _tx  # noqa: E402  取る物の表の正(写さない)
import push_helper  # noqa: E402  個人データの名前の表を流用する

LAUNCHER_SRC = os.path.join(REPO, "friend-apps", "launcher")
LAUNCHER_BUILD = os.path.join(REPO, "friend-apps", "launcher", "build")
LAUNCHER_EXE = "FriendApp.exe"
LAUNCHER_DLLS = ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll")   # dev/fetch_webview2.py が取る物
SCHEMA = "youtube-tools-friend-zip/v1"
FETCH_SCHEMA = "youtube-tools-friend-fetch/v1"
TX_TOOL = "transcribe"   # 編集の作業データの ID(datadir。fetch の dest の頭)
KEEP_ZIPS = 2            # 更新の置き場所に残す zip の数(今回の物を含む)
WHEEL_NAMES = ("numpy", "sherpa-onnx", "streamlink")   # 決めたこと 12: Python の部品はこの 3 つだけ(版は setup/requirements*.txt から読む)
MEMBERS_SRC = os.path.join(REPO, "friend-apps", "holo-colors", "members.json")   # 配信者の名簿(zip の直下へ写す。places.py が直下から読む)
KEY_SRC = os.path.join(LAUNCHER_SRC, "config.json")    # Dropbox の鍵(git の外。dev/dropbox_auth.py が作る)。--first --with-key のときだけ zip の直下へ
INSTALL_NAME = "FriendApp-はじめに.txt"                 # zip の直下に置く入れ方(元は friend-apps/launcher/INSTALL.txt)
FOLDER_NAME = "FriendApp"                               # zip の中を包むフォルダの名前
ZIP_PREFIX = "FriendApp"                                # ふだんの zip の名前の頭(FriendApp-<版>.zip)
# 新しいアプリが動くのに要る src の物(git に入っていないと zip に入らない = 追跡し忘れの検査)
FRIEND_LAYERS = ("friendapp", "ytt", "flow", "pipeline", "ui-kit")   # zip に入れる src の層(許可リスト)。友人のアプリが読む層だけ。ここの層は外の層を読まない(dev/rule_imports.py の C-22)
FRIEND_FILES = ("src/editor/hololive-roster.json",)   # 許可リストの外の層から入れる物。編集のフォルダ(ytt/workdata の ROOT)は名簿を置く所で、認識ワーカーの cwd でもある(無いとワーカーが起きない)
REQUIRED_SRC = ("src/friendapp/server.py", "src/friendapp/streams.py", "src/friendapp/setup.py", "src/friendapp/places.py",
                "src/friendapp/ui/friend.html", "src/friendapp/ui/friend.js", "src/friendapp/ui/host.js", "src/friendapp/ui/setup.html",
                "src/friendapp/ui/setup.js", "src/friendapp/ui/guide.html") + FRIEND_FILES

# 公式の埋め込み用 Python(3.10 の Windows 向けの最後の版)。SHA-256 は表に無い = 取ったときの値をキャッシュに残して以後照らす
PY_EMBED = {"version": "3.10.11", "file": "python-3.10.11-embed-amd64.zip",
            "url": "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip"}
# アプリのフォルダの tools/ に置く道具(初回に取る。版はこの PC と同じ。SHA-256 はキャッシュに取った物から)
TOOLS = (
    {"name": "ffmpeg", "file": "ffmpeg-9.0.2-essentials_build.zip", "unzip": "zip", "dest": "tools/ffmpeg",
     "url": "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"},
    # yt-dlp: 今の安定版(GitHub の releases/latest の安定版。新しいのは nightly だけ)。大きさと SHA-256 は公式の SHA2-256SUMS の値
    # (この PC の winget の yt-dlp.exe も同じ値)。版を上げるときは url と一緒に size・sha256 も公式の値へ
    {"name": "yt-dlp", "file": "yt-dlp.exe", "unzip": None, "dest": "tools/yt-dlp",
     "url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.exe",
     "size": 17840399, "sha256": "66674953fe251b89f4d08c5f0e35e0728679bd67ab3d7d05c0562af101dd3e7a"},
    {"name": "deno", "file": "deno-x86_64-pc-windows-msvc.zip", "unzip": "zip", "dest": "tools/deno",
     "url": "https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-pc-windows-msvc.zip"},
)
TEXT_EXT = {".py", ".js", ".css", ".html", ".json", ".txt", ".md", ".bat", ".cmd"}


class BuildError(Exception):
    pass


def say(msg):
    print(msg, flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _rel(path):
    return path.replace("\\", "/").strip("/")


# ---------------------------------------------------------------- キャッシュ(取る・照らす)
def download(url, dest):
    """https の固定の URL を dest に取る(.part に書いてから名前を付ける)。テストは差し替える"""
    if not url.startswith("https://"):
        raise BuildError("取得先が https ではありません: %s" % url)
    say("取得します: %s" % url)
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(part, dest)


def cached(cache, sub, item, fetch, fetcher=download):
    """キャッシュの <sub>/<file> を返す。無ければ取り(fetch が偽なら BuildError)、大きさと SHA-256 を <file>.sha256.json に残す。
    あれば残した値と照らす(違えば BuildError = キャッシュが書き換わった)。
    記録の url が表と違う(版を上げた)ときは取り直す。表に sha256(公式の値)があれば、それとも照らす"""
    path = os.path.join(cache, sub, item["file"])
    rec = path + ".sha256.json"
    if os.path.isfile(path) and os.path.isfile(rec):
        try:
            with open(rec, encoding="utf-8") as f:
                old_url = json.load(f).get("url") or item["url"]   # url の無い古い記録は今の版とみなす
        except (OSError, ValueError):
            old_url = item["url"]
        if old_url != item["url"]:
            if not fetch:
                raise BuildError("キャッシュの %s は別の版です(--no-fetch)。%s" % (item["file"], item["url"]))
            os.remove(path)
    if not os.path.isfile(path):
        if not fetch:
            raise BuildError("キャッシュに %s がありません(--no-fetch)。%s" % (item["file"], item["url"]))
        fetcher(item["url"], path)
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({"url": item["url"], "size": os.path.getsize(path), "sha256": sha256_file(path)}, f)
    try:
        with open(rec, encoding="utf-8") as f:
            want = json.load(f)
    except (OSError, ValueError):
        raise BuildError("キャッシュの %s に記録(.sha256.json)がありません。消して取り直してください" % item["file"])
    got = {"size": os.path.getsize(path), "sha256": sha256_file(path)}
    if got["size"] != want.get("size") or got["sha256"] != want.get("sha256"):
        raise BuildError("キャッシュの %s が記録と違います。消して取り直してください" % item["file"])
    if item.get("sha256") and (got["sha256"] != item["sha256"] or got["size"] != item.get("size", got["size"])):
        raise BuildError("%s が公式の SHA-256 と違います(%s)。消して取り直してください" % (item["file"], item["url"]))
    return path, got


def wheel_pins(setup_dir=None):
    """setup/requirements*.txt から WHEEL_NAMES の「名前==版」を読む(版の正は requirements)"""
    setup_dir = setup_dir or os.path.join(REPO, "setup")
    pins = {}
    for n in sorted(os.listdir(setup_dir)):
        if not (n.startswith("requirements") and n.endswith(".txt")):
            continue
        with open(os.path.join(setup_dir, n), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s#;]+)", line)
                if m and m.group(1).lower() in WHEEL_NAMES:
                    pins[m.group(1).lower()] = "%s==%s" % (m.group(1).lower(), m.group(2))
    missing = [n for n in WHEEL_NAMES if n not in pins]
    if missing:
        raise BuildError("setup/requirements*.txt に版がありません: %s" % ", ".join(missing))
    return [pins[n] for n in WHEEL_NAMES]


def pip_download(reqs, folder):
    """Windows・Python 3.10 向けの wheel を依存ごと folder に取る(pip が PyPI の SHA-256 で確かめる)。テストは差し替える"""
    cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.10",
           "--implementation", "cp", "--no-cache-dir", "-d", folder] + list(reqs)
    say("> " + " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise BuildError("pip download が失敗しました(終了コード %d)" % r.returncode)


def wheels(cache, reqs, fetch, downloader=pip_download):
    """キャッシュの wheels/ の wheel の一覧。wheels.lock.json(要求と各ファイルの SHA-256)が要求と合わなければ取り直す"""
    folder = os.path.join(cache, "wheels")
    lock = os.path.join(folder, "wheels.lock.json")
    try:
        with open(lock, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        rec = {}
    if rec.get("requirements") != list(reqs):
        if not fetch:
            raise BuildError("キャッシュの wheel が %s と合いません(--no-fetch)" % " ".join(reqs))
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        os.makedirs(folder)
        downloader(reqs, folder)
        files = sorted(n for n in os.listdir(folder) if n.endswith(".whl"))
        rec = {"requirements": list(reqs), "files": {n: sha256_file(os.path.join(folder, n)) for n in files}}
        with open(lock, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    out = []
    for n, sha in sorted(rec.get("files", {}).items()):
        p = os.path.join(folder, n)
        if not os.path.isfile(p) or sha256_file(p) != sha:
            raise BuildError("キャッシュの wheel %s が記録と違います。wheels フォルダを消して取り直してください" % n)
        out.append(p)
    if not out:
        raise BuildError("キャッシュに wheel がありません")
    return out


# ---------------------------------------------------------------- 展開
def _safe_name(name):
    """zip の中の名前が展開先の外を指さないか(絶対パス・..・ドライブ)"""
    n = name.replace("\\", "/")
    return not (n.startswith("/") or ":" in n or ".." in n.split("/"))


def unzip_into(zip_path, folder, remap=None):
    """zip を folder に展開する。remap(name → 新しい名前 | None = 捨てる)で置き場所を変えられる"""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if not _safe_name(info.filename):
                raise BuildError("%s の中の名前が危ないので使いません: %s" % (os.path.basename(zip_path), info.filename[:80]))
            name = remap(info.filename) if remap else info.filename
            if not name:
                continue
            dest = os.path.join(folder, *name.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def _wheel_remap(name):
    """wheel の <pkg>.data/purelib|platlib/ は site-packages の直下へ。scripts・headers・data は捨てる"""
    parts = name.split("/")
    if len(parts) > 2 and parts[0].endswith(".data"):
        return "/".join(parts[2:]) if parts[1] in ("purelib", "platlib") else None
    return name


def lay_python(stage, embed_zip, wheel_files):
    """stage/python/ に埋め込み用 Python を置き、._pth に Lib/site-packages と ../src を足し、wheel を site-packages に展開する"""
    py = os.path.join(stage, "python")
    unzip_into(embed_zip, py)
    pths = [n for n in os.listdir(py) if re.match(r"python3\d+\._pth$", n)]
    if len(pths) != 1:
        raise BuildError("埋め込み用 Python の ._pth が見つかりません(%s)" % os.path.basename(embed_zip))
    pth = os.path.join(py, pths[0])
    with open(pth, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln not in ("import site", "#import site")]
    lines += ["Lib\\site-packages", "..\\src", "import site"]
    with open(pth, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    site = os.path.join(py, "Lib", "site-packages")
    os.makedirs(site, exist_ok=True)
    for w in wheel_files:
        unzip_into(w, site, _wheel_remap)
    return py


def src_files(repo=REPO):
    """git が管理している src のファイルのうち FRIEND_LAYERS の層の物と FRIEND_FILES(tests/・__pycache__ を外す)。追跡外の作業データ(src/pipeline/ingest/data など)は入らない"""
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z", "src"], capture_output=True)
    if r.returncode != 0:
        raise BuildError("git ls-files が失敗しました: %s" % r.stderr.decode("utf-8", "replace")[:200])
    out = []
    for f in r.stdout.decode("utf-8").split("\0"):
        parts = f.split("/")
        if not f or "tests" in parts or "__pycache__" in parts or f.endswith(".pyc") or len(parts) < 3 or (parts[1] not in FRIEND_LAYERS and f not in FRIEND_FILES):
            continue
        if os.path.isfile(os.path.join(repo, *parts)):   # 消したのにまだコミットしていない物は飛ばす
            out.append(f)
    return out


def lay_src(stage, repo=REPO):
    for f in src_files(repo):
        dest = os.path.join(stage, *f.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(repo, *f.split("/")), dest)


def _launcher_stale(launcher_build, launcher_src=LAUNCHER_SRC):
    """FriendApp.exe が無い、または launcher の C#(src/*.cs・build.bat・共通の ../common/*.cs)より古いか"""
    exe = os.path.join(launcher_build, LAUNCHER_EXE)
    if not os.path.isfile(exe):
        return True
    newest = 0
    for folder in (os.path.join(launcher_src, "src"), os.path.join(os.path.dirname(launcher_src), "common")):
        if os.path.isdir(folder):
            newest = max([newest] + [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder) if n.endswith(".cs")])
    return os.path.getmtime(exe) < newest


def run_launcher_build(launcher_src=LAUNCHER_SRC):
    """friend-apps/launcher/build.bat を窓なしで流す(WebView2 の DLL の取得・コンパイル・テスト)。失敗は BuildError"""
    say("友人のアプリの窓 FriendApp.exe を作り直します(launcher/build.bat)…")
    r = subprocess.run(["cmd", "/c", ".\\build.bat", "--no-pause"], cwd=launcher_src, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).decode("cp932", "replace").strip().splitlines()[-5:]
        raise BuildError("launcher の build.bat が失敗しました:\n" + "\n".join(tail))


def lay_launcher(stage, launcher_build=LAUNCHER_BUILD, launcher_src=LAUNCHER_SRC, rebuild=None):
    """友人のアプリの窓 FriendApp.exe と WebView2 の DLL を zip の直下に置く。
    既定の置き場所で、無い・C# より古いときは build.bat を流し直す(rebuild を渡すとそれを呼ぶ。テスト用)。それでも無ければ作るよう促して止まる"""
    default = os.path.normcase(os.path.abspath(launcher_build)) == os.path.normcase(os.path.abspath(os.path.join(launcher_src, "build")))
    if default and _launcher_stale(launcher_build, launcher_src):
        (rebuild or run_launcher_build)(launcher_src)
    for name in (LAUNCHER_EXE,) + LAUNCHER_DLLS:
        p = os.path.join(launcher_build, name)
        if not os.path.isfile(p):
            raise BuildError("%s がありません(friend-apps/launcher/build.bat を流してから)" % p)
    for name in (LAUNCHER_EXE,) + LAUNCHER_DLLS:
        shutil.copy2(os.path.join(launcher_build, name), stage)


def lay_install(stage, launcher_src=LAUNCHER_SRC):
    """入れ方(launcher/INSTALL.txt)を FriendApp-はじめに.txt として直下に"""
    p = os.path.join(launcher_src, "INSTALL.txt")
    if not os.path.isfile(p):
        raise BuildError("%s がありません" % p)
    shutil.copy2(p, os.path.join(stage, INSTALL_NAME))


def check_src(repo=REPO):
    """新しいアプリの src の必須の物が git に入っているか(入っていない = zip に入らない)。追跡外の物は警告だけ(作業中は普通にある)"""
    have = set(src_files(repo))
    miss = [p for p in REQUIRED_SRC if p not in have]
    if miss:
        raise BuildError("友人のアプリに要る物が git の管理に入っていません(zip に入りません): " + ", ".join(miss))
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--others", "--exclude-standard", "src/friendapp"], capture_output=True)
    extra = [f for f in r.stdout.decode("utf-8", "replace").split("\0") if f and "/tests/" not in f and "__pycache__" not in f]
    for f in extra:
        say("[警告] git に入れていない友人のアプリの物は zip に入りません: " + f)


def lay_wcpp(stage, wcpp_dir):
    """whisper.cpp の Vulkan 版を tools/ に。build.json の版・コミットが tx_engines の WHISPER_CPP と合い、files の SHA-256 が合う物だけ"""
    try:
        with open(os.path.join(wcpp_dir, "build.json"), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        raise BuildError("whisper.cpp の build.json が読めません: %s(setup/build-whisper-vulkan.bat で作ってから)" % wcpp_dir)
    want = _tx.WHISPER_CPP
    if info.get("version") != want["version"] or info.get("commit") != want["commit"] or info.get("backend") != "vulkan":
        raise BuildError("whisper.cpp の版・コミットが表(tx_engines.WHISPER_CPP)と違います: %s" % wcpp_dir)
    files = info.get("files") or {}
    if _tx.WCPP_EXE not in files:
        raise BuildError("whisper.cpp の build.json に %s がありません" % _tx.WCPP_EXE)
    sub = os.path.basename(_tx.wcpp_bin_dir(""))
    dest = os.path.join(stage, "tools", sub)
    os.makedirs(dest)
    for name, sha in sorted(files.items()):
        p = os.path.join(wcpp_dir, name)
        if os.path.basename(name) != name or not os.path.isfile(p) or sha256_file(p) != sha:
            raise BuildError("whisper.cpp の %s が build.json と違います" % name)
        shutil.copy2(p, dest)
    shutil.copy2(os.path.join(wcpp_dir, "build.json"), dest)
    return "tools/" + sub


def lay_members(stage, members_src=MEMBERS_SRC):
    """配信者の名簿 members.json(ホロカラーと同じ一覧)を zip の直下に。友人のアプリが places.py で直下から読む"""
    if not os.path.isfile(members_src):
        raise BuildError("%s がありません" % members_src)
    shutil.copy2(members_src, os.path.join(stage, "members.json"))


def lay_key(stage, with_key, key_src=KEY_SRC):
    """(--first --with-key のときだけ)Dropbox の鍵 config.json を zip の直下に。中身は読まない(写すだけ)"""
    if not with_key:
        return
    if not os.path.isfile(key_src):
        raise BuildError("--with-key ですが %s がありません(python dev/dropbox_auth.py で作ってから)" % key_src)
    shutil.copy2(key_src, os.path.join(stage, "config.json"))


# ---------------------------------------------------------------- fetch.json(取る物の表を読むだけ)
def _data_dest(rel_dir):
    """作業データの中の置き場所(tx_engines・diarize の関数に空の data_dir を渡して得た相対)→ data からの相対"""
    return TX_TOOL + "/" + _rel(rel_dir)


def _diar_rel():
    old = workdata.DATA_DIR
    workdata.DATA_DIR = ""
    try:
        return _rel(_diarize.diar_models_dir()) if _diarize.DIAR_DIR is None else None
    finally:
        workdata.DATA_DIR = old


def model_entries():
    """モデルと llama.cpp の行(tx_engines・diarize の表をそのまま読む。決めたこと 12: large-v3・SenseVoice・Qwen3-8B・話者の判別)"""
    out = []
    for name, s in _tx.WCPP_MODELS.items():
        out.append({"name": "whisper.cpp/" + name, "file": s["file"], "url": s["url"], "size": s["size"], "sha256": s["sha256"],
                    "base": "data", "dest": _data_dest(_tx.wcpp_model_dir("")), "unzip": None})
    c = _tx.LLAMA_CPP
    out.append({"name": "llama.cpp/" + c["version"], "file": c["file"], "url": c["url"], "size": c["size"], "sha256": c["sha256"],
                "base": "data", "dest": _data_dest(_tx.llama_bin_dir("")), "unzip": "zip"})
    for name, s in _tx.LLAMA_TEXT_MODELS.items():
        m = s["model"]
        out.append({"name": "llm/" + name, "file": m["file"], "url": m["url"], "size": m["size"], "sha256": m["sha256"],
                    "base": "data", "dest": _data_dest("models/" + _tx.LlamaText.MODEL_SUBDIR), "unzip": None})
    for name, s in _tx.SENSE_VOICE_MODELS.items():
        out.append({"name": "sensevoice/" + name, "file": s["file"], "url": s["url"], "size": s["size"], "sha256": s["sha256"],
                    "base": "data", "dest": _data_dest(_tx.sv_model_dir("")), "unzip": "tar.bz2", "top": s["dir"], "parts": list(s["parts"])})
    diar = _diar_rel()
    if diar is None:
        raise BuildError("diarize.DIAR_DIR が上書きされています(置き場所を決められない)")
    for key, s in (("segmentation", _diarize.DIAR_SEG), (_diarize.DIAR_EMB_DEFAULT, _diarize.DIAR_EMBS[_diarize.DIAR_EMB_DEFAULT])):
        # 判別のモデルの表は大きさを持たない(上限 max だけ)= size は null・maxBytes で守る。tar.bz2 は member の 1 つだけを file の名前で置く
        out.append({"name": "diar/" + key, "file": s["file"], "url": s["url"], "size": None, "maxBytes": s["max"], "sha256": s["sha256"],
                    "base": "data", "dest": _data_dest(diar), "unzip": "tar.bz2-member" if s["member"] else None, "member": s["member"]})
    return out


def tool_entries(cache, fetch, fetcher=download):
    out = []
    for t in TOOLS:
        _, got = cached(cache, "tools", t, fetch, fetcher)
        out.append({"name": t["name"], "file": t["file"], "url": t["url"], "size": got["size"], "sha256": got["sha256"],
                    "base": "app", "dest": t["dest"], "unzip": t["unzip"], "pinnedBy": "build"})
    return out


# ---------------------------------------------------------------- 検査・zip・置き場所
def audit(stage, with_key, home=None, user=None):
    """個人データ・鍵・個人のパス・消した道具の名前(dev/spec_check.GONE = 前の友人のアプリ)が無いか。見つけた物の一覧(空なら合格)。
    src と直下だけ見る(python/ は公式の配布物)"""
    import spec_check
    home = (home or os.path.expanduser("~")).replace("\\", "/").lower().rstrip("/")
    user = (user if user is not None else getpass.getuser()).lower()
    pats = [home, home.replace("/", "\\")]
    if user:
        pats += ["/users/" + user + "/", "\\users\\" + user + "\\"]
    bad = []
    for dp, _dns, fns in os.walk(stage):
        rel = _rel(os.path.relpath(dp, stage))
        if rel.split("/")[0] in ("python", "tools"):
            continue
        for n in fns:
            p = _rel(rel + "/" + n) if rel != "." else n
            if with_key and p == "config.json":
                continue   # --first --with-key の鍵だけは入れてよい(中身は読まない)
            parts = p.split("/")
            if n in push_helper.BAD_NAMES or push_helper.BAD_NAME_RE.search(n) or set(parts[:-1]) & push_helper.BAD_DIRS:
                bad.append("個人データ・鍵の名前: " + p)
                continue
            if os.path.splitext(n)[1].lower() in TEXT_EXT:
                with open(os.path.join(dp, n), "rb") as f:
                    text = f.read().decode("utf-8", "replace").lower().replace("\\\\", "\\")
                if any(s and s in text for s in pats):
                    bad.append("個人のパス: " + p)
                if spec_check.GONE.search(text):
                    bad.append("消した道具の名前: " + p)
    return bad


def file_hashes(stage):
    out = {}
    for dp, _dns, fns in os.walk(stage):
        for n in fns:
            p = os.path.join(dp, n)
            out[_rel(os.path.relpath(p, stage))] = sha256_file(p)
    return dict(sorted(out.items()))


def write_zip(stage, path):
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in file_hashes(stage):
            z.write(os.path.join(stage, *rel.split("/")), rel)
    os.replace(tmp, path)


def _ver_key(name, prefix):
    m = re.match(re.escape(prefix) + r"-(\d+)\.(\d+)\.(\d+)\.zip$", name)
    return tuple(int(x) for x in m.groups()) if m else None


def prune(out_dir, keep=KEEP_ZIPS):
    """更新の置き場所の古い FriendApp-<版>.zip を keep 個まで残して消す(版の新しい順)。-first.zip・ほかの名前は触らない"""
    zs = sorted((n for n in os.listdir(out_dir) if _ver_key(n, ZIP_PREFIX)), key=lambda n: _ver_key(n, ZIP_PREFIX), reverse=True)
    for n in zs[keep:]:
        os.remove(os.path.join(out_dir, n))
        say("古い zip を消しました: %s" % n)


def default_out(first, publish=False):
    if first:
        return os.path.join(LAUNCHER_SRC, "dist")
    if not publish:
        raise BuildError("出力先がありません。--out で一時のフォルダを渡してください(Dropbox の 更新\\ へ置くのはユーザーの OK のあと --publish で)")
    prefs = os.path.join(datadir.locate("app", SRC), "prefs.json")
    try:
        with open(prefs, encoding="utf-8") as f:
            folder = (json.load(f).get("intake") or {}).get("folder") or ""
    except (OSError, ValueError):
        folder = ""
    if not folder:
        raise BuildError("依頼の受付のフォルダ(ホームの設定 intake.folder)が決まっていません。--out で出力先を渡してください")
    return os.path.join(folder, "更新")


def build(out_dir, cache, wcpp_dir, first=False, with_key=False, fetch=True, notes="", fetcher=download, downloader=pip_download,
          launcher_build=LAUNCHER_BUILD, members_src=MEMBERS_SRC, key_src=KEY_SRC):  # lint: long 一本の流れ(置く → 表 → 検査 → zip)
    """zip を作って {zip, size, sha256, files} を返す。失敗は BuildError"""
    if with_key and not first:
        raise BuildError("--with-key は --first のときだけ(更新の zip に鍵を入れない)")
    ver = _version.VERSION
    os.makedirs(out_dir, exist_ok=True)
    stage_root = tempfile.mkdtemp(prefix="friend-zip-")
    try:
        stage = os.path.join(stage_root, FOLDER_NAME)
        os.makedirs(stage)
        lay_members(stage, members_src)
        lay_key(stage, with_key, key_src)
        embed, embed_got = cached(cache, "python", PY_EMBED, fetch, fetcher)
        reqs = wheel_pins()
        wfiles = wheels(cache, reqs, fetch, downloader)
        lay_python(stage, embed, wfiles)
        check_src()
        lay_src(stage)
        wcpp = lay_wcpp(stage, wcpp_dir)
        lay_launcher(stage, launcher_build)
        lay_install(stage)
        fetch_doc = {"schema": FETCH_SCHEMA, "version": ver, "items": model_entries() + tool_entries(cache, fetch, fetcher)}
        with open(os.path.join(stage, "fetch.json"), "w", encoding="utf-8") as f:
            json.dump(fetch_doc, f, ensure_ascii=False, indent=1)
        bad = audit(stage, with_key)
        if bad:
            raise BuildError("zip に入れてはいけない物があります:\n  " + "\n  ".join(bad[:20]))
        files = file_hashes(stage)
        manifest = {"schema": SCHEMA, "version": ver, "builtAt": datetime.datetime.now().isoformat(timespec="seconds"), "first": bool(first),
                    "withKey": bool(with_key), "python": {"version": PY_EMBED["version"], "file": PY_EMBED["file"], "sha256": embed_got["sha256"]},
                    "requirements": reqs, "wheels": [os.path.basename(w) for w in wfiles], "whisperCpp": {"dir": wcpp, "version": _tx.WHISPER_CPP["version"]},
                    "files": files}
        with open(os.path.join(stage, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        name = "%s-%s%s.zip" % (ZIP_PREFIX, ver, "-first" if first else "")
        path = os.path.join(out_dir, name)
        write_zip(stage, path)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    got = {"zip": path, "size": os.path.getsize(path), "sha256": sha256_file(path), "files": len(files) + 1}
    if not first:
        latest = {"version": ver, "file": name, "size": got["size"], "sha256": got["sha256"], "notes": notes}
        with open(os.path.join(out_dir, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=1)
        prune(out_dir)
    return got


def default_cache():
    """キャッシュの既定(%LOCALAPPDATA%/youtube-tools/app/friend-build-cache)"""
    return os.path.join(datadir.locate("app", SRC), "friend-build-cache")


def default_wcpp():
    """whisper.cpp の Vulkan 版の既定(作業データの transcribe/bin/whisper.cpp-<版>-vulkan)"""
    return _tx.wcpp_bin_dir(datadir.tool_dir(TX_TOOL, os.path.join(SRC, "editor")))


def publish(a, out):
    """--publish: 一時のフォルダに作り、配る前の検査(dev/friend_preflight.py)に通ったら更新の置き場所へ写す(zip → latest.json → 古い zip を消す)。
    落ちたら置かない。検査を抜けるのは --skip-preflight の明示だけ -> build と同じ形"""
    tmp = tempfile.mkdtemp(prefix="friend-publish-")
    try:
        got = build(tmp, a.cache, a.wcpp, with_key=False, fetch=not a.no_fetch)
        if a.skip_preflight:
            say("[警告] 配る前の検査を飛ばします(--skip-preflight)")
        else:
            import friend_preflight   # 読むのは置くときだけ(Playwright を使う)
            say("配る前の検査を流します(数分。窓は画面の外・音は出しません)…")
            if not friend_preflight.preflight_zip(got["zip"]):
                raise BuildError("配る前の検査に落ちたので、更新の置き場所には置きません(記録は上の不合格の行)")
        os.makedirs(out, exist_ok=True)
        name = os.path.basename(got["zip"])
        shutil.copy2(got["zip"], os.path.join(out, name + ".part"))
        os.replace(os.path.join(out, name + ".part"), os.path.join(out, name))
        shutil.copy2(os.path.join(tmp, "latest.json"), os.path.join(out, "latest.json"))   # zip が置けてから(友人のアプリは latest.json を見て取る)
        prune(out)
        got["zip"] = os.path.join(out, name)
        return got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_friend_zip.py", description="友人の PC に配る zip を作る")
    ap.add_argument("--out", default="", help="出力先(一時のフォルダ。--first は既定 friend-apps/launcher/dist/)")
    ap.add_argument("--publish", action="store_true", help="--out なしで <intake.folder>/更新/ (Dropbox)へ置く。友人のアプリが取りに来る = ユーザーの OK のあとだけ")
    ap.add_argument("--cache", default="", help="Python の本体・wheel・道具のキャッシュ(既定 %%LOCALAPPDATA%%/youtube-tools/app/friend-build-cache)")
    ap.add_argument("--first", action="store_true", help="初回に手で渡す zip(dist に・latest.json を書かない)")
    ap.add_argument("--with-key", action="store_true", help="--first のときだけ: friend-apps/launcher/config.json(Dropbox の鍵)を入れる")
    ap.add_argument("--no-fetch", action="store_true", help="キャッシュに無い物を取りに行かない(無ければ失敗)")
    ap.add_argument("--skip-preflight", action="store_true", help="--publish のときだけ: 配る前の検査(dev/friend_preflight.py)を飛ばす(明示のときだけ)")
    a = ap.parse_args(argv)
    if a.skip_preflight and not a.publish:
        ap.error("--skip-preflight は --publish のときだけ使えます")
    if a.with_key and not a.first:
        ap.error("--with-key は --first のときだけ使えます")
    if a.publish and (a.out or a.first):
        ap.error("--publish は --out・--first と一緒に使えません")
    try:
        out = a.out or default_out(a.first, a.publish)
        a.cache = a.cache or default_cache()
        a.wcpp = default_wcpp()
        if a.publish:
            got = publish(a, out)
        else:
            got = build(out, a.cache, a.wcpp, first=a.first, with_key=a.with_key, fetch=not a.no_fetch)
    except (BuildError, OSError) as e:
        say("[失敗] %s" % e)
        return 1
    say("できました: %s(%.1f MB・%d ファイル)" % (got["zip"], got["size"] / 1e6, got["files"]))
    if a.with_key:
        say("鍵(config.json)が入っています。友人にだけ渡してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
