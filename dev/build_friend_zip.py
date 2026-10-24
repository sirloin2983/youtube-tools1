# -*- coding: utf-8 -*-
"""友人の PC に配る zip(新しいアプリ FriendApp + ② + ① の Python のコード + 埋め込み用 Python + 部品)を作る道具(設計 notes:docs/design/f1-build.md の 2・3 節)。

zip の中(アプリのフォルダ <任意>/FriendApp/ にそのまま展開する形。3 節 (f1i)):
    FriendApp.exe    友人のアプリの窓(friend-apps/launcher/build/。WebView2 の DLL 3 つ = Microsoft.Web.WebView2.Core.dll・.WinForms.dll・WebView2Loader.dll と一緒に直下)。
                     無い・launcher の C# より古ければ friend-apps/launcher/build.bat を流してから入れる
    members.json     配信者の名簿(friend-apps/holo-colors/members.json の写し。友人のアプリが places.py で直下から読んで YTT_HOLO_MEMBERS に渡す)
    FriendApp-はじめに.txt  入れ方とアプリのフォルダの説明(friend-apps/launcher/INSTALL.txt)
    python/        公式の埋め込み用 Python 3.12 + python312._pth(Lib/site-packages と ../src を足す)+ wheel を展開した部品(numpy・sherpa-onnx・streamlink と依存)
    src/           git が管理している src のファイルのうち friendapp・ytt・flow・pipeline・ui-kit の層(__pycache__ は外す。テストは src の外の tests/ なので入らない。作業データ・追跡外のファイルは入らない)
    tools/whisper.cpp-<版>-vulkan/   ユーザーの PC で作った whisper.cpp(build.json の files と SHA-256 が合う物だけ)
    fetch.json     初回に取る物の表(モデル・llama.cpp・ffmpeg・yt-dlp・Deno)。モデルと llama.cpp は tx_engines・diarize の表を import して読むだけ
    manifest.json  全体の版・各ファイルの SHA-256
config.json(Dropbox の鍵)は入れない。--first --with-key のときだけ friend-apps/launcher/config.json(git の外)を zip の直下へ入れる(3 節 (f1g)。友人の PC もアプリのフォルダの直下の config.json を読む)。

出力:
    --out D: 出力先を D に(テスト・手元の確かめ。FriendApp-<版>.zip + latest.json を D に書く)
    --first: friend-apps/launcher/dist/FriendApp-<版>-first.zip(latest.json は書かない。手で渡す)
    ふだんの出力(--first 以外)は FriendApp-<版>.zip(全部入り)に加えて FriendApp-<版>-light.zip(python/・tools/ を入れない軽い更新。manifest.json は同じ files + light = 真)を作り、
        latest.json に light {file, size, sha256} を足す(file は全部入りのまま。友人のアプリは light が写せなければ file を取る。src/friendapp/sync.py)。
    --publish(--out なし): <ホームの設定の intake.folder>/更新/ へ light → 全部入り → latest.json → versions.json の順(古い zip は全部入り 3 版・軽い 10 版を残して消す。(f1h))。
        台帳の行に配った時刻 publishedAt(ミリ秒。版の見張り human/friend/upwatch が「配って 24 時間」を数える)
    --queue --note "<直した一言>": 友人の zip を配る待ちの列に積むだけ(作らない・配らない。友人の zip はまとめて配る決め・10-25 ユーザー)。
        入口の見回り(human/friend/pubqueue)が 3 時間ごと(0・3・6・9・12・15・18・21 時)に、積まれていれば main の今の版を 1 回だけ
        --publish --from-queue で配る。子のセッション・AI はふだんこれを使う
    --publish はすぐ配る例外だけ: --from-queue(配る回)か、--important --fix-kind 4(起動しない・更新で壊れた)/ 2(録画そのものが動かない)。
        どちらも列に積んだ物を一緒に乗せ、積んだ一言の一覧を latest.json と台帳の changes(この版で直したこと)に入れて、配れたら列から外す。
        --from-queue で配れなかったら知らせの一覧(human/friend/upwatch の alerts.jsonl)へ書く
        --note の一言は友人のアプリの「最近の更新」にそのまま出る = 友人に見せる短い言葉で(「ユーザーの PC」・内部の名前・ファイル名を使わない)
    latest.json の history(--publish のとき): 最近の更新 [{v: 版, at: 配った時刻(ミリ秒), items: [一言]}](新しい順・HISTORY_MAX 版。台帳の changes から)・
        runtime(python/ の中身の印。友人のアプリが軽い zip で入れられるか = 今の python/ と同じかを先に知る)
    --rollback <版 か prev> [--why 文]: 友人の PC へ「この版に戻して」の印 <intake.folder>/診断/戻して/rollback-<ミリ秒>.rollback.json
        {v:1, id, at, to(版 か null = 友人の PC に残る確かに動いた版), why} を置く(問題 4・10-25。友人のアプリが戻して印を消し、
        結果を 診断/ の launcher__fail-<13 桁>.fail.json(kind rollback)で返す = 版の見張り human/friend/upwatch が最上の急ぎで知らせる)
    --withdraw <版>: 配布の取り消し。latest.json を前の良い版へ戻すとき cancel:[<版>] を付ける(友人のアプリは、取ってあってまだ入れていない
        その版を入れ替えずに捨てる。捨てたことは心拍の pending が null になることで分かる)
    --important・--fix-request <依頼 id>・--fix-kind <1〜7>: latest.json と台帳の行に「重要」の印 important と直す対象
        fixes {requests, kinds}(失敗の種類 = human/friend/bugs の KINDS)を付ける(友人のアプリの更新の決め・10-25。付けなければ欄を書かない)
        versions.json = 版の台帳(版・builtAt・notes・全部入りと light の file/size/sha256・python の印 runtime)を新しい順に 20 版。zip が消えた版は file/light を null にして行は残す
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
import time
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
DEV = os.path.dirname(os.path.abspath(__file__))
if DEV not in sys.path:
    sys.path.insert(0, DEV)
from ytt import datadir, fsio as _fsio, version as _version, workdata  # noqa: E402
from human.friend import pubqueue as _pubqueue, upwatch as _upwatch  # noqa: E402  配る待ちの列と知らせの一覧
from pipeline.transcribe import diarize as _diarize, separate as _separate, tx_engines as _tx  # noqa: E402  取る物の表の正(写さない)
import _common  # noqa: E402
import push_helper  # noqa: E402  個人データの名前の表を流用する

LAUNCHER_SRC = os.path.join(REPO, "friend-apps", "launcher")
LAUNCHER_BUILD = os.path.join(REPO, "friend-apps", "launcher", "build")
LAUNCHER_EXE = "FriendApp.exe"
LAUNCHER_DLLS = ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll", "WebView2Loader.dll")   # dev/fetch_webview2.py が取る物
SCHEMA = "youtube-tools-friend-zip/v1"
FETCH_SCHEMA = "youtube-tools-friend-fetch/v1"
TX_TOOL = "transcribe"   # 編集の作業データの ID(datadir。fetch の dest の頭)
KEEP_FULL = 3            # 更新の置き場所に残す全部入りの zip の版の数(今回の物を含む。約 70 MB ずつ。-first.zip は触らない)
KEEP_LIGHT = 10          # 同じく -light.zip(約 3 MB ずつ)
KEEP_ROWS = 20           # 更新/versions.json に残す版の行の数(zip が消えた版も行は残す)
VERSIONS_NAME = "versions.json"   # 更新の置き場所の版の台帳(作る側だけが書く。友人のアプリは読まない)
LIGHT_SKIP = ("python/", "tools/")   # 軽い更新の zip に入れない物(python は今の版から写す・tools は更新で使われない)
WHEEL_NAMES = ("numpy", "sherpa-onnx", "streamlink")   # 決めたこと 12: Python の部品はこの 3 つだけ(版は setup/requirements*.txt から読む)
MEMBERS_SRC = os.path.join(REPO, "friend-apps", "holo-colors", "members.json")   # 配信者の名簿(zip の直下へ写す。places.py が直下から読む)
KEY_SRC = os.path.join(LAUNCHER_SRC, "config.json")    # Dropbox の鍵(git の外。dev/dropbox_auth.py が作る)。--first --with-key のときだけ zip の直下へ
INSTALL_NAME = "FriendApp-はじめに.txt"                 # zip の直下に置く入れ方(元は friend-apps/launcher/INSTALL.txt)
FOLDER_NAME = "FriendApp"                               # zip の中を包むフォルダの名前
ZIP_PREFIX = "FriendApp"                                # ふだんの zip の名前の頭(FriendApp-<版>.zip)
# 新しいアプリが動くのに要る src の物(git に入っていないと zip に入らない = 追跡し忘れの検査)
FRIEND_LAYERS = ("friendapp", "ytt", "flow", "pipeline", "ui-kit")   # zip に入れる src の層(許可リスト)。友人のアプリが読む層だけ。ここの層は外の層を読まない(dev/rule_imports.py の C-22)
REQUIRED_SRC = ("src/friendapp/server.py", "src/friendapp/streams.py", "src/friendapp/setup.py", "src/friendapp/places.py",
                "src/friendapp/ui/friend.html", "src/friendapp/ui/friend.js", "src/friendapp/ui/host.js", "src/friendapp/ui/setup.html",
                "src/friendapp/ui/setup.js", "src/friendapp/ui/guide.html", "src/pipeline/transcribe/hololive-roster.json")   # 名簿 = 最初に作業データへ写す同梱の物

# 公式の埋め込み用 Python(3.12 の Windows 向けの最後の版 = この PC と同じ 3.12)。SHA-256 は表に無い = 取ったときの値をキャッシュに残して以後照らす
PY_EMBED = {"version": "3.12.10", "file": "python-3.12.10-embed-amd64.zip",
            "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"}
PY_TAG = ".".join(PY_EMBED["version"].split(".")[:2])   # wheel を取る Python の版(3.12)
# アプリのフォルダの tools/ に置く道具(初回に取る。版はこの PC と同じ。SHA-256 はキャッシュに取った物から)
TOOLS = (
    {"name": "ffmpeg", "file": "ffmpeg-9.0.2-essentials_build.zip", "unzip": "zip", "dest": "tools/ffmpeg",
     "url": "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"},
    # yt-dlp: 今の安定版(GitHub の releases/latest の安定版。新しいのは nightly だけ)。大きさと SHA-256 は公式の SHA2-256SUMS の値
    # (この PC の winget の yt-dlp.exe も同じ値)。版を上げるときは url と一緒に size・sha256 も公式の値へ
    {"name": "yt-dlp", "file": "yt-dlp.exe", "unzip": None, "dest": "tools/yt-dlp",
     "url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.21/yt-dlp.exe",   # 中の certifi 2026.10.19(認証局の一覧の急ぎの直し。10-23)
     "size": 17880111, "sha256": "33121d192d706e62f684a06f80918e3f3a8ba52ac3a65213b6951c39c7d9f555"},
    {"name": "deno", "file": "deno-x86_64-pc-windows-msvc.zip", "unzip": "zip", "dest": "tools/deno",
     "url": "https://github.com/denoland/deno/releases/download/v2.9.7/deno-x86_64-pc-windows-msvc.zip"},
)
TEXT_EXT = {".py", ".js", ".css", ".html", ".json", ".txt", ".md", ".bat", ".cmd"}


class BuildError(Exception):
    pass


def say(msg):
    print(msg, flush=True)


sha256_file = _fsio.sha256_file   # 写しを持たない(friend_preflight も bfz.sha256_file で呼ぶ)


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
    """Windows・埋め込みの Python(PY_TAG)向けの wheel を依存ごと folder に取る(pip が PyPI の SHA-256 で確かめる)。テストは差し替える"""
    cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--platform", "win_amd64", "--python-version", PY_TAG,
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
    if rec.get("requirements") != list(reqs) or rec.get("python", "3.10") != PY_TAG:   # Python の版が変わったら取り直す
        if not fetch:
            raise BuildError("キャッシュの wheel が %s と合いません(--no-fetch)" % " ".join(reqs))
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        os.makedirs(folder)
        downloader(reqs, folder)
        files = sorted(n for n in os.listdir(folder) if n.endswith(".whl"))
        rec = {"requirements": list(reqs), "python": PY_TAG, "files": {n: sha256_file(os.path.join(folder, n)) for n in files}}
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
    check_certifi(out)
    return out


# 認証局の一覧(certifi)の下限(10-23。eMudhra / emSign の認証局の問題で 2026.10.19 に出た急ぎの直し = Python 3.13〜3.15 の 10-21 の版と同じ)。
# streamlink の依存の requests が使う。版は pip download の時の最新(固定しない)なので、キャッシュが古いままだと古い一覧が入る = ここで止める
CERTIFI_MIN = (2026, 10, 19)


def check_certifi(files):
    """wheel の中の certifi が CERTIFI_MIN 以上か(無ければ何もしない)。古ければ BuildError(キャッシュの wheels を消して取り直す)"""
    for p in files:
        m = re.match(r"certifi-(\d+)\.(\d+)\.(\d+)-", os.path.basename(p))
        if m and tuple(int(x) for x in m.groups()) < CERTIFI_MIN:
            raise BuildError("certifi %s は古い認証局の一覧です(%d.%02d.%02d 以上が要る)。キャッシュの wheels フォルダを消して取り直してください" % (
                ".".join(m.groups()), *CERTIFI_MIN))


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
    tag = "cp" + pths[0][len("python"):-len("._pth")]   # python312._pth -> cp312
    wrong = sorted({m.group(1) for w in wheel_files for m in [re.search(r"-(cp3\d+)-cp3\d+-", os.path.basename(w))] if m and m.group(1) != tag})   # abi3(安定の ABI)の wheel は版を問わない
    if wrong:   # 埋め込みの Python と wheel の版が食い違うと、同梱の python で部品が読めない(0.99.92 = 3.10 と cp312)
        raise BuildError("wheel の版(%s)が埋め込みの Python(%s)と合いません。キャッシュの wheels を消して取り直してください" % (", ".join(wrong), tag))
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
    """git が管理している src のファイルのうち FRIEND_LAYERS の層の物(__pycache__ を外す。テストは src の外の tests/)。追跡外の作業データ(src/pipeline/ingest/data など)は入らない"""
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z", "src"], capture_output=True)
    if r.returncode != 0:
        raise BuildError("git ls-files が失敗しました: %s" % r.stderr.decode("utf-8", "replace")[:200])
    out = []
    for f in r.stdout.decode("utf-8").split("\0"):
        parts = f.split("/")
        if not f or "__pycache__" in parts or f.endswith(".pyc") or len(parts) < 3 or parts[1] not in FRIEND_LAYERS:
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
    extra = [f for f in r.stdout.decode("utf-8", "replace").split("\0") if f and "__pycache__" not in f]
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
    for name, s in _separate.SEP_MODELS.items():   # 声の分離(後処理の dropSilent。10-22)
        out.append({"name": "sep/" + name, "file": s["file"], "url": s["url"], "size": s["size"], "sha256": s["sha256"],
                    "base": "data", "dest": _data_dest(_separate.sep_model_dir("")), "unzip": "tar.bz2", "top": s["dir"], "parts": list(s["parts"])})
    diar = _diar_rel()
    if diar is None:
        raise BuildError("diarize.DIAR_DIR が上書きされています(置き場所を決められない)")
    embs = [_diarize.DIAR_EMB_DEFAULT] + ([_diarize.VOICE_EMB] if _diarize.VOICE_EMB in _diarize.DIAR_EMBS and _diarize.VOICE_EMB != _diarize.DIAR_EMB_DEFAULT else [])   # 判別と声の名前付けのモデル
    for key, s in [("segmentation", _diarize.DIAR_SEG)] + [(e, _diarize.DIAR_EMBS[e]) for e in embs]:
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


def write_zip(stage, path, skip=()):
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in file_hashes(stage):
            if rel.startswith(skip):
                continue
            z.write(os.path.join(stage, *rel.split("/")), rel)
    os.replace(tmp, path)


def _ver_key(name, prefix):
    m = re.match(re.escape(prefix) + r"-(\d+)\.(\d+)\.(\d+)(?:-light)?\.zip$", name)
    return tuple(int(x) for x in m.groups()) if m else None


def prune_plan(out_dir, keep_full=KEEP_FULL, keep_light=KEEP_LIGHT):
    """消す zip の名前 = 全部入りは新しい順に keep_full 版・-light は keep_light 版を超えた物。-first.zip・ほかの名前は入らない"""
    out = []
    for light, keep in ((False, keep_full), (True, keep_light)):
        zs = [n for n in os.listdir(out_dir) if _ver_key(n, ZIP_PREFIX) and n.endswith("-light.zip") == light]
        zs.sort(key=lambda n: _ver_key(n, ZIP_PREFIX), reverse=True)
        out += zs[keep:]
    return out


def prune(out_dir, keep_full=KEEP_FULL, keep_light=KEEP_LIGHT):
    """更新の置き場所の古い zip を消す(prune_plan)。消した名前を返す"""
    gone = prune_plan(out_dir, keep_full, keep_light)
    for n in gone:
        os.remove(os.path.join(out_dir, n))
        say("古い zip を消しました: %s" % n)
    return gone


def runtime_mark(files):
    """python/ の中身の印 = python/* の相対パスと SHA-256 を並べた SHA-256(軽い更新で python を写せるかの目安。版ごとに台帳へ)"""
    h = hashlib.sha256()
    for rel in sorted(k for k in files if k.startswith("python/")):
        h.update(("%s %s;" % (rel, files[rel])).encode("utf-8"))
    return h.hexdigest()


def update_versions(out_dir, row, plan=None):
    """versions.json に row(この版の行)を足して書く -> 行の一覧。新しい順に KEEP_ROWS 版・prune で消える zip(plan。無ければ prune_plan)の行は file/light を null に。
    読めない・形が違う台帳は作り直す(zip の置き場所の正は zip と latest.json)"""
    path = os.path.join(out_dir, VERSIONS_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("versions")
    except (OSError, ValueError, AttributeError):
        rows = None
    rows = [r for r in rows if isinstance(r, dict) and r.get("version") != row["version"]] if isinstance(rows, list) else []
    rows.append(row)
    rows = [r for r in rows if isinstance(r.get("version"), str) and re.fullmatch(r"\d+\.\d+\.\d+", r["version"])]
    rows.sort(key=lambda r: tuple(int(x) for x in r["version"].split(".")), reverse=True)
    rows = rows[:KEEP_ROWS]
    gone = set(prune_plan(out_dir) if plan is None else plan)

    def alive(n):
        return bool(n) and n not in gone and os.path.isfile(os.path.join(out_dir, n))

    for r in rows:
        if not alive(r.get("file")):
            r["file"] = None
        if not (isinstance(r.get("light"), dict) and alive(r["light"].get("file"))):
            r["light"] = None
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "versions": rows}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return rows


def withdraw(out_dir, version, keep_dir):
    """配った版を取り下げる: 更新の置き場所から その版の zip(全部入り・軽い)を keep_dir へ移し(消さない)、versions.json の行を消し、
    latest.json がその版なら台帳の前の良い版(zip が置き場所に残っている物)へ戻す(無ければ latest.json を keep_dir へ移す)。
    友人の版は下がらない(取り下げた版を取った友人は、次に配る版で進む)-> 戻した latest の版か None"""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        raise BuildError("版の形が違います: %s" % version)
    os.makedirs(keep_dir, exist_ok=True)
    moved = []
    for n in ("%s-%s.zip" % (ZIP_PREFIX, version), "%s-%s-light.zip" % (ZIP_PREFIX, version)):
        if os.path.isfile(os.path.join(out_dir, n)):
            shutil.move(os.path.join(out_dir, n), os.path.join(keep_dir, n))
            moved.append(n)
    path = os.path.join(out_dir, VERSIONS_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("versions")
    except (OSError, ValueError, AttributeError):
        rows = None
    rows = [r for r in rows if isinstance(r, dict) and r.get("version") != version] if isinstance(rows, list) else []
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump({"v": 1, "versions": rows}, f, ensure_ascii=False, indent=1)
    os.replace(path + ".part", path)
    latest_path = os.path.join(out_dir, "latest.json")
    try:
        with open(latest_path, encoding="utf-8") as f:
            latest = json.load(f)
    except (OSError, ValueError):
        latest = None
    back = None
    if isinstance(latest, dict) and latest.get("version") == version:
        prev = next((r for r in rows if r.get("file") and os.path.isfile(os.path.join(out_dir, r["file"]))
                     and tuple(int(x) for x in r["version"].split(".")) < tuple(int(x) for x in version.split("."))), None)
        if prev is None:
            shutil.move(latest_path, os.path.join(keep_dir, "latest-%s.json" % version))
        else:
            light = prev.get("light") if isinstance(prev.get("light"), dict) and os.path.isfile(os.path.join(out_dir, prev["light"].get("file") or "")) else None
            cancel = [v for v in (latest.get("cancel") or []) if isinstance(v, str)] + [version]   # 友人のアプリが取ってある取り下げた版を捨てる
            new = {"version": prev["version"], "file": prev["file"], "size": prev["size"], "sha256": prev["sha256"], "notes": prev.get("notes") or "", "light": light,
                   "cancel": sorted(set(cancel))}
            with open(latest_path + ".part", "w", encoding="utf-8") as f:
                json.dump(new, f, ensure_ascii=False, indent=1)
            os.replace(latest_path + ".part", latest_path)
            back = prev["version"]
    say("取り下げました: %s(移した zip: %s → %s。latest.json: %s)" % (version, ", ".join(moved) or "無し", keep_dir,
                                                                    "版 %s に戻した" % back if back else ("置き場所から外した" if latest and latest.get("version") == version else "そのまま")))
    return back


def rollback(sync_folder, to, why="", now=None):
    """友人の PC へ「この版に戻して」の印を置く -> 置いたファイルのパス。to = 版(X.Y.Z)か None(友人の PC に残る確かに動いた版)"""
    if to is not None and not re.fullmatch(r"\d+\.\d+\.\d+", to):
        raise BuildError("戻す版の形が違います: %s(X.Y.Z か prev)" % to)
    at = int((time.time() if now is None else now) * 1000)
    d = os.path.join(sync_folder, "診断", "戻して")
    os.makedirs(d, exist_ok=True)
    rid = "rollback-%d" % at
    path = os.path.join(d, rid + ".rollback.json")
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump({"v": 1, "id": rid, "at": at, "to": to, "why": str(why or "")[:300]}, f, ensure_ascii=False)
    os.replace(path + ".part", path)
    say("戻す印を置きました: %s(戻す版: %s)" % (path, to or "友人の PC に残る確かに動いた版"))
    return path


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
          launcher_build=LAUNCHER_BUILD, members_src=MEMBERS_SRC, key_src=KEY_SRC, mark=None):  # lint: long 一本の流れ(置く → 表 → 検査 → zip)
    """zip を作って {zip, size, sha256, files, light} を返す(light = 軽い更新の {zip, size, sha256}。--first は無し)。失敗は BuildError。
    mark = latest.json と台帳の行に足す {important, fixes}(update_mark。None = 足さない)"""
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
        light = None
        if not first:
            manifest["light"] = True
            with open(os.path.join(stage, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=1)
            light_name = "%s-%s-light.zip" % (ZIP_PREFIX, ver)
            write_zip(stage, os.path.join(out_dir, light_name), skip=LIGHT_SKIP)
            light = {"zip": os.path.join(out_dir, light_name), "size": os.path.getsize(os.path.join(out_dir, light_name)),
                     "sha256": sha256_file(os.path.join(out_dir, light_name))}
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    got = {"zip": path, "size": os.path.getsize(path), "sha256": sha256_file(path), "files": len(files) + 1, "light": light}
    if not first:
        light_entry = {"file": os.path.basename(light["zip"]), "size": light["size"], "sha256": light["sha256"]}
        latest = dict({"version": ver, "file": name, "size": got["size"], "sha256": got["sha256"], "notes": notes, "light": light_entry}, **(mark or {}))
        with open(os.path.join(out_dir, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=1)
        got["row"] = {"version": ver, "builtAt": manifest["builtAt"], "notes": notes, "file": name, "size": got["size"], "sha256": got["sha256"],
                      "light": light_entry, "runtime": runtime_mark(files), **(mark or {})}
        update_versions(out_dir, got["row"])
        prune(out_dir)
    return got


def update_mark(important=False, requests=None, kinds=None):
    """「重要」の印と直す対象 -> latest.json に足す欄({} = 足さない)。依頼 id の形・種類 1〜7 でなければ BuildError"""
    reqs, kinds = list(requests or []), list(kinds or [])
    bad = [r for r in reqs if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", r)] + [str(k) for k in kinds if k not in range(1, 8)]
    if bad:
        raise BuildError("直す対象の形が違います: %s(依頼 id は YYYYMMDD-HHMMSS-6 文字・種類は 1〜7)" % ", ".join(bad))
    out = {"important": True} if important else {}
    if reqs or kinds:
        out["fixes"] = {"requests": reqs, "kinds": sorted(set(kinds))}
    return out


def default_cache():
    """キャッシュの既定(%LOCALAPPDATA%/youtube-tools/app/friend-build-cache)"""
    return os.path.join(datadir.locate("app", SRC), "friend-build-cache")


def default_wcpp():
    """whisper.cpp の Vulkan 版の既定(作業データの transcribe/bin/whisper.cpp-<版>-vulkan)"""
    return _tx.wcpp_bin_dir(datadir.tool_dir(TX_TOOL, os.path.join(SRC, "editor")))


HISTORY_MAX = 10


def add_history(out_dir):
    """配った後: latest.json に history(台帳の changes のある版の最近の更新)と runtime(この版の python/ の印)を足して書き直す"""
    path = os.path.join(out_dir, "latest.json")
    with open(path, encoding="utf-8") as f:
        latest = json.load(f)
    try:
        with open(os.path.join(out_dir, VERSIONS_NAME), encoding="utf-8") as f:
            rows = json.load(f).get("versions") or []
    except (OSError, ValueError, AttributeError):
        rows = []
    rows = [r for r in rows if isinstance(r, dict)]
    latest["history"] = [{"v": r["version"], "at": r.get("publishedAt"), "items": [str(x) for x in r["changes"]]}
                         for r in rows if isinstance(r.get("changes"), list) and r["changes"]][:HISTORY_MAX]
    me = next((r for r in rows if r.get("version") == latest.get("version")), {})
    if me.get("runtime"):
        latest["runtime"] = me["runtime"]
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    os.replace(path + ".part", path)
    return latest


def publish(a, out):
    """--publish: 一時のフォルダに作り、配る前の検査(dev/friend_preflight.py)に通ったら更新の置き場所へ写す(light → 全部入り → latest.json → 古い zip を消す)。
    落ちたら置かない。検査を抜けるのは --skip-preflight の明示だけ -> build と同じ形"""
    tmp = tempfile.mkdtemp(prefix="friend-publish-")
    try:
        got = build(tmp, a.cache, a.wcpp, with_key=False, fetch=not a.no_fetch, mark=getattr(a, "mark", None))
        if a.skip_preflight:
            say("[警告] 配る前の検査を飛ばします(--skip-preflight)")
        else:
            import friend_preflight   # 読むのは置くときだけ(Playwright を使う)
            say("配る前の検査を流します(数分。窓は画面の外・音は出しません)…")
            if not friend_preflight.preflight_zip(got["zip"]):
                raise BuildError("配る前の検査に落ちたので、更新の置き場所には置きません(記録は上の不合格の行)")
        os.makedirs(out, exist_ok=True)
        name = os.path.basename(got["zip"])
        for z in (got["light"]["zip"], got["zip"]):   # light → 全部入り(友人のアプリは latest.json を見て取る = 2 つとも置けてから latest.json)
            n = os.path.basename(z)
            shutil.copy2(z, os.path.join(out, n + ".part"))
            os.replace(os.path.join(out, n + ".part"), os.path.join(out, n))
        shutil.copy2(os.path.join(tmp, "latest.json"), os.path.join(out, "latest.json"))
        update_versions(out, dict(got["row"], publishedAt=int(time.time() * 1000)))   # 台帳 → 古い zip を消す(消える zip の行は台帳で先に null にする)
        prune(out)
        add_history(out)   # 最近の更新(友人のアプリが見せる)と python/ の印
        got["zip"] = os.path.join(out, name)
        return got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    _common.console_utf8()   # 配る前の検査も同じプロセスで出力する
    ap = argparse.ArgumentParser(prog="build_friend_zip.py", description="友人の PC に配る zip を作る")
    ap.add_argument("--out", default="", help="出力先(一時のフォルダ。--first は既定 friend-apps/launcher/dist/)")
    ap.add_argument("--publish", action="store_true", help="--out なしで <intake.folder>/更新/ (Dropbox)へ置く。友人のアプリが取りに来る = ユーザーの OK のあとだけ")
    ap.add_argument("--cache", default="", help="Python の本体・wheel・道具のキャッシュ(既定 %%LOCALAPPDATA%%/youtube-tools/app/friend-build-cache)")
    ap.add_argument("--first", action="store_true", help="初回に手で渡す zip(dist に・latest.json を書かない)")
    ap.add_argument("--with-key", action="store_true", help="--first のときだけ: friend-apps/launcher/config.json(Dropbox の鍵)を入れる")
    ap.add_argument("--no-fetch", action="store_true", help="キャッシュに無い物を取りに行かない(無ければ失敗)")
    ap.add_argument("--withdraw", default="", help="配った版を取り下げる(更新の置き場所から zip を外して手元へ移す・台帳から消す・latest.json を前の良い版へ)")
    ap.add_argument("--queue", action="store_true", help="友人の zip を配る待ちの列に積むだけ(ふだんはこれ。3 時間ごとにまとめて配る)")
    ap.add_argument("--note", default="", help="--queue・--publish: この版で直した一言(友人のアプリの「最近の更新」にそのまま出る = 友人に見せる短い言葉で。"
                    "「ユーザーの PC」・内部の名前を使わない。200 字まで)")
    ap.add_argument("--from-queue", action="store_true", help="--publish のときだけ: 入口の配る回が使う(列の分を配る)")
    ap.add_argument("--rollback", default="", metavar="VER", help="友人の PC へ「この版に戻して」の印を置く(版 X.Y.Z か prev = 友人の PC に残る確かに動いた版)")
    ap.add_argument("--why", default="", help="--rollback の理由(300 字まで)")
    ap.add_argument("--important", action="store_true", help="latest.json に「重要」の印を付ける(友人のアプリの更新の決め)")
    ap.add_argument("--fix-request", action="append", default=[], metavar="RID", help="この版で直す依頼 id(何度でも)")
    ap.add_argument("--fix-kind", action="append", default=[], type=int, metavar="N", help="この版で直す失敗の種類 1〜7(何度でも)")
    ap.add_argument("--skip-preflight", action="store_true", help="--publish のときだけ: 配る前の検査(dev/friend_preflight.py)を飛ばす(明示のときだけ)")
    a = ap.parse_args(argv)
    if a.skip_preflight and not a.publish:
        ap.error("--skip-preflight は --publish のときだけ使えます")
    if a.with_key and not a.first:
        ap.error("--with-key は --first のときだけ使えます")
    if a.publish and (a.out or a.first):
        ap.error("--publish は --out・--first と一緒に使えません")
    if a.from_queue and not a.publish:
        ap.error("--from-queue は --publish のときだけ使えます")
    app = datadir.locate("app", SRC)
    if a.queue:
        if a.publish or a.first or a.out:
            ap.error("--queue は積むだけです(--publish・--first・--out と一緒に使えません)")
        if not a.note.strip():
            ap.error("--queue には --note \"<直した一言>\" が要ります")
        row = _pubqueue.add(app, a.note, _version.VERSION, by=os.environ.get("CLAUDE_SESSION_NAME", ""))
        say("配る待ちの列に積みました(版 %s・%s)。3 時間ごとの配る回でまとめて配ります(今の列: %d 件)" % (row["version"], row["note"], len(_pubqueue.items(app))))
        return 0
    if a.publish and not a.from_queue and not (a.important and set(a.fix_kind) & {2, 4}):
        ap.error("友人の zip はふだん --queue で積みます。すぐ配るのは --publish --important --fix-kind 4(起動しない・更新で壊れた)か 2(録画そのものが動かない)だけです")
    started = int(time.time() * 1000)
    try:
        if a.rollback:   # 戻す印: 置き場所は受付のフォルダ(Dropbox)の 診断/戻して/
            rollback(os.path.dirname(default_out(False, True)), None if a.rollback == "prev" else a.rollback, a.why)
            return 0
        if a.withdraw:   # 取り下げ: --out が無ければ更新の置き場所(Dropbox)・外した zip は作る PC の手元へ
            withdraw(a.out or default_out(False, True), a.withdraw, os.path.join(datadir.locate("app", SRC), "friend-withdrawn"))
            return 0
        a.mark = update_mark(a.important, a.fix_request, a.fix_kind)
        if a.publish:   # 列に積んだ物も一緒に乗せる(この版で直したこと)
            done = _pubqueue.changes([x for x in _pubqueue.items(app) if (x.get("at") or 0) <= started] + [{"note": a.note.strip()[:_pubqueue.NOTE_MAX]}])
            if done:
                a.mark["changes"] = done
        if a.mark and a.first:
            raise BuildError("--important・--fix-* は --first では使えません(latest.json を書かない)")
        out = a.out or default_out(a.first, a.publish)
        a.cache = a.cache or default_cache()
        a.wcpp = default_wcpp()
        if a.publish:
            got = publish(a, out)
        else:
            got = build(out, a.cache, a.wcpp, first=a.first, with_key=a.with_key, fetch=not a.no_fetch, mark=a.mark)
    except (BuildError, OSError) as e:
        say("[失敗] %s" % e)
        if a.from_queue:
            _upwatch.add_alert(app, "warn", "publish-fail:%d" % started, "まとめて配る回で友人の zip を配れませんでした(列は残しました・次の回にまた配ります): %s" % str(e)[:300])
        return 1
    if a.publish:
        _pubqueue.take(app, started)   # 配れた分を列から外す(配っている間に積んだ物は次の回へ)
    say("できました: %s(%.1f MB・%d ファイル)" % (got["zip"], got["size"] / 1e6, got["files"]))
    if got.get("light"):
        say("軽い更新: %s(%.1f MB)" % (got["light"]["zip"], got["light"]["size"] / 1e6))
    if a.with_key:
        say("鍵(config.json)が入っています。友人にだけ渡してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
