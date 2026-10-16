# -*- coding: utf-8 -*-
"""友人の PC に配る zip(送るアプリ + ② + ① の Python のコード + 埋め込み用 Python + 部品)を作る道具(F1 の F4a。設計 notes:docs/design/f1-build.md の 2・3 節)。

zip の中(アプリのフォルダ <任意>/RequestSender/ にそのまま展開する形。3 節 (f1i)):
    RequestSender.exe・members.json・README.txt(friend-apps/request-sender/build/ と README。build.bat で作ってから)
    FriendInbox.exe  友人の受信箱の起動役(friend-apps/launcher/build/。そちらの build.bat で作ってから。F2-4。直下 = 今の RequestSender.exe と並べる)
    friend-defaults.json・guide.html(friend-apps/request-sender/ にあれば。F5・(f1f) の物)
    python/        公式の埋め込み用 Python 3.10 + python310._pth(Lib/site-packages と ../src を足す)+ wheel を展開した部品(numpy・sherpa-onnx・streamlink と依存)
    src/           git が管理している src のファイル(tests/・__pycache__ は外す。作業データ・追跡外のファイルは入らない)
    tools/whisper.cpp-<版>-vulkan/   ユーザーの PC で作った whisper.cpp(build.json の files と SHA-256 が合う物だけ)
    fetch.json     初回に取る物の表(モデル・llama.cpp・ffmpeg・yt-dlp・Deno)。モデルと llama.cpp は tx_engines・diarize の表を import して読むだけ
    manifest.json  全体の版・各ファイルの SHA-256
config.json(Dropbox の鍵)は入れない。--first --with-key のときだけ friend-apps/request-sender/config.json を入れる(3 節 (f1g))。

出力:
    既定(更新の zip): <ホームの設定の intake.folder>/更新/RequestSender-<版>.zip + latest.json(古い zip は 2 つ残して消す。(f1h))
    --first: friend-apps/request-sender/dist/RequestSender-<版>-first.zip(latest.json は書かない。手で渡す)
    --out D: 出力先を D に(テスト・手元の確かめ)

Python の本体・wheel・ffmpeg などはキャッシュのフォルダ(--cache。既定 %LOCALAPPDATA%/youtube-tools/app/friend-build-cache)から読み、
無ければ取りに行く(https の固定の URL・wheel は pip download)。ffmpeg・yt-dlp・Deno・Python の本体は表に SHA-256 が無いので、
キャッシュに取った物の大きさと SHA-256 を fetch.json・manifest.json に書く(取ったときに 1 回だけ信じる。以後はキャッシュの記録と照らす)。

    py -3.10 dev/build_friend_zip.py [--out D] [--cache C] [--wcpp-dir W] [--app-build B] [--first [--with-key]] [--no-fetch]
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

APP_SRC = os.path.join(REPO, "friend-apps", "request-sender")
LAUNCHER_BUILD = os.path.join(REPO, "friend-apps", "launcher", "build")
LAUNCHER_EXE = "FriendInbox.exe"
SCHEMA = "youtube-tools-friend-zip/v1"
FETCH_SCHEMA = "youtube-tools-friend-fetch/v1"
TX_TOOL = "transcribe"   # 編集の作業データの ID(datadir。fetch の dest の頭)
KEEP_ZIPS = 2            # 更新の置き場所に残す zip の数(今回の物を含む)
WHEEL_NAMES = ("numpy", "sherpa-onnx", "streamlink")   # 決めたこと 12: Python の部品はこの 3 つだけ(版は setup/requirements*.txt から読む)
APP_FILES = ("RequestSender.exe", "members.json")      # build.bat が build/ に作る物
APP_OPTIONAL = ("friend-defaults.json", "guide.html")  # あれば入れる(friend-apps/request-sender/ の直下)

# 公式の埋め込み用 Python(3.10 の Windows 向けの最後の版)。SHA-256 は表に無い = 取ったときの値をキャッシュに残して以後照らす
PY_EMBED = {"version": "3.10.11", "file": "python-3.10.11-embed-amd64.zip",
            "url": "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip"}
# アプリのフォルダの tools/ に置く道具(初回に取る。版はこの PC と同じ。SHA-256 はキャッシュに取った物から)
TOOLS = (
    {"name": "ffmpeg", "file": "ffmpeg-9.0.2-essentials_build.zip", "unzip": "zip", "dest": "tools/ffmpeg",
     "url": "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"},
    {"name": "yt-dlp", "file": "yt-dlp.exe", "unzip": None, "dest": "tools/yt-dlp",
     "url": "https://github.com/yt-dlp/yt-dlp/releases/download/2026.08.19/yt-dlp.exe"},
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
    あれば残した値と照らす(違えば BuildError = キャッシュが書き換わった)"""
    path = os.path.join(cache, sub, item["file"])
    rec = path + ".sha256.json"
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
    """git が管理している src のファイル(tests/・__pycache__ を外す)。追跡外の作業データ(src/pipeline/ingest/data など)は入らない"""
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z", "src"], capture_output=True)
    if r.returncode != 0:
        raise BuildError("git ls-files が失敗しました: %s" % r.stderr.decode("utf-8", "replace")[:200])
    out = []
    for f in r.stdout.decode("utf-8").split("\0"):
        parts = f.split("/")
        if not f or "tests" in parts or "__pycache__" in parts or f.endswith(".pyc"):
            continue
        if os.path.isfile(os.path.join(repo, *parts)):   # 消したのにまだコミットしていない物は飛ばす
            out.append(f)
    return out


def lay_src(stage, repo=REPO):
    for f in src_files(repo):
        dest = os.path.join(stage, *f.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(repo, *f.split("/")), dest)


def lay_launcher(stage, launcher_build=LAUNCHER_BUILD):
    """受信箱の起動役 FriendInbox.exe を zip の直下に置く(今の送るアプリ RequestSender.exe と並べる = F2-7 まで両方使える)。無ければ作るよう促して止まる"""
    p = os.path.join(launcher_build, LAUNCHER_EXE)
    if not os.path.isfile(p):
        raise BuildError("%s がありません(friend-apps/launcher/build.bat を流してから)" % p)
    shutil.copy2(p, stage)


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


def _built_version(app_build):
    try:
        with open(os.path.join(app_build, "version.txt"), encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return ""


def run_app_build(app_src=APP_SRC):
    """build.bat を窓なしで流す(コンパイルとテスト)。失敗は BuildError"""
    print("送るアプリを作り直します(build.bat)…")
    r = subprocess.run(["cmd", "/c", "build.bat", "--no-pause"], cwd=app_src, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).decode("cp932", "replace").strip().splitlines()[-5:]
        raise BuildError("build.bat が失敗しました:\n" + "\n".join(tail))


def lay_app(stage, app_build, with_key, app_src=APP_SRC, rebuild=None):
    """送るアプリ(build.bat が作った exe・members.json)と README・任意の 2 つ・(--with-key のときだけ)config.json。
    版が全体の版と違えば build.bat を流し直してから(rebuild を渡すとそれを呼ぶ。テスト用)"""
    ver = _version.VERSION
    built = _built_version(app_build)
    if built != ver and os.path.normcase(os.path.abspath(app_build)) == os.path.normcase(os.path.join(app_src, "build")):
        (rebuild or run_app_build)(app_src)
        built = _built_version(app_build)
    if built != ver:
        raise BuildError("アプリの版(%s の version.txt = %r)が全体の版 %s と違います。friend-apps/request-sender/build.bat を流し直してください"
                         % (app_build, built, ver))
    for n in APP_FILES:
        p = os.path.join(app_build, n)
        if not os.path.isfile(p):
            raise BuildError("%s がありません(build.bat を流してから)" % p)
        shutil.copy2(p, stage)
    shutil.copy2(os.path.join(app_src, "README.txt"), stage)
    for n in APP_OPTIONAL:
        p = os.path.join(app_src, n)
        if os.path.isfile(p):
            shutil.copy2(p, stage)
    if with_key:
        key = os.path.join(app_src, "config.json")
        if not os.path.isfile(key):
            raise BuildError("--with-key ですが %s がありません(python dev/dropbox_auth.py で作ってから)" % key)
        shutil.copy2(key, stage)   # 中身は読まない(写すだけ)


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
    """個人データ・鍵・個人のパスが無いか。見つけた物の一覧(空なら合格)。src と直下だけ見る(python/ は公式の配布物)"""
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


def _ver_key(name):
    m = re.match(r"RequestSender-(\d+)\.(\d+)\.(\d+)\.zip$", name)
    return tuple(int(x) for x in m.groups()) if m else None


def prune(out_dir, keep=KEEP_ZIPS):
    """更新の置き場所の古い RequestSender-<版>.zip を keep 個まで残して消す(版の新しい順)"""
    zs = sorted((n for n in os.listdir(out_dir) if _ver_key(n)), key=_ver_key, reverse=True)
    for n in zs[keep:]:
        os.remove(os.path.join(out_dir, n))
        say("古い zip を消しました: %s" % n)


def default_out(first):
    if first:
        return os.path.join(APP_SRC, "dist")
    prefs = os.path.join(datadir.locate("app", SRC), "prefs.json")
    try:
        with open(prefs, encoding="utf-8") as f:
            folder = (json.load(f).get("intake") or {}).get("folder") or ""
    except (OSError, ValueError):
        folder = ""
    if not folder:
        raise BuildError("依頼の受付のフォルダ(ホームの設定 intake.folder)が決まっていません。--out で出力先を渡してください")
    return os.path.join(folder, "更新")


def build(out_dir, cache, wcpp_dir, app_build, first=False, with_key=False, fetch=True, notes="", fetcher=download, downloader=pip_download, app_src=APP_SRC,
          launcher_build=LAUNCHER_BUILD):  # lint: long 一本の流れ(置く → 表 → 検査 → zip)
    """zip を作って {zip, size, sha256, files} を返す。失敗は BuildError"""
    if with_key and not first:
        raise BuildError("--with-key は --first のときだけ(更新の zip に鍵を入れない)")
    ver = _version.VERSION
    os.makedirs(out_dir, exist_ok=True)
    stage_root = tempfile.mkdtemp(prefix="friend-zip-")
    try:
        stage = os.path.join(stage_root, "RequestSender")
        os.makedirs(stage)
        lay_app(stage, app_build, with_key, app_src)
        embed, embed_got = cached(cache, "python", PY_EMBED, fetch, fetcher)
        reqs = wheel_pins()
        wfiles = wheels(cache, reqs, fetch, downloader)
        lay_python(stage, embed, wfiles)
        lay_src(stage)
        wcpp = lay_wcpp(stage, wcpp_dir)
        lay_launcher(stage, launcher_build)
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
        name = "RequestSender-%s%s.zip" % (ver, "-first" if first else "")
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="build_friend_zip.py", description="友人の PC に配る zip を作る(F1 の F4a)")
    ap.add_argument("--out", default="", help="出力先(既定: 更新の zip = <intake.folder>/更新/・--first = friend-apps/request-sender/dist/)")
    ap.add_argument("--cache", default="", help="Python の本体・wheel・道具のキャッシュ(既定 %%LOCALAPPDATA%%/youtube-tools/app/friend-build-cache)")
    ap.add_argument("--wcpp-dir", default="", help="whisper.cpp の Vulkan 版のフォルダ(既定: 作業データの transcribe/bin/whisper.cpp-<版>-vulkan)")
    ap.add_argument("--app-build", default=os.path.join(APP_SRC, "build"), help="build.bat が作った exe の置き場所")
    ap.add_argument("--launcher-build", default=LAUNCHER_BUILD, help="friend-apps/launcher/build.bat が作った FriendInbox.exe の置き場所")
    ap.add_argument("--first", action="store_true", help="初回に手で渡す zip(dist に・latest.json を書かない)")
    ap.add_argument("--with-key", action="store_true", help="--first のときだけ: config.json(Dropbox の鍵)を入れる")
    ap.add_argument("--no-fetch", action="store_true", help="キャッシュに無い物を取りに行かない(無ければ失敗)")
    ap.add_argument("--notes", default="", help="latest.json の notes(更新の説明)")
    a = ap.parse_args(argv)
    if a.with_key and not a.first:
        ap.error("--with-key は --first のときだけ使えます")
    try:
        out = a.out or default_out(a.first)
        cache = a.cache or os.path.join(datadir.locate("app", SRC), "friend-build-cache")
        wcpp = a.wcpp_dir or _tx.wcpp_bin_dir(datadir.tool_dir(TX_TOOL, os.path.join(SRC, "editor")))
        got = build(out, cache, wcpp, a.app_build, first=a.first, with_key=a.with_key, fetch=not a.no_fetch, notes=a.notes,
                    launcher_build=a.launcher_build)
    except (BuildError, OSError) as e:
        say("[失敗] %s" % e)
        return 1
    say("できました: %s(%.1f MB・%d ファイル)" % (got["zip"], got["size"] / 1e6, got["files"]))
    if a.with_key:
        say("鍵(config.json)が入っています。友人にだけ渡してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
