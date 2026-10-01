#!/usr/bin/env python3
"""友人用 文字起こし簡易版の自動更新(lite/start.bat が起動の前に呼ぶ。標準ライブラリだけ)。

取得元は **このリポジトリの main に固定**(ブリーフのセキュリティ)。ほかの場所からは取らない:
  - git で clone したフォルダ: origin が REPO_URL のときだけ `git fetch origin main` → `git merge --ff-only origin/main`。
    手元に変更があるとき・origin が違うときは更新しない(友人の手元の変更を消さない・知らない場所から取らない)
  - zip で配ったフォルダ: GitHub の API で main の最新のコミットを調べ、そのコミットの zip(codeload)を取る。
    展開する前に名前を確かめる(1つの上のフォルダの中だけ・../・絶対パス・リンクは断る)。上書きするのはコードだけ(PROTECTED は触らない)
失敗しても起動は止めない(更新できなかったと知らせるだけ)。`--check` は確かめるだけ、環境変数 LITE_NO_UPDATE=1 で何もしない。
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = "sirloin2983/youtube-tools1"
BRANCH = "main"
REPO_URL = "https://github.com/%s" % REPO
API_URL = "https://api.github.com/repos/%s/commits/%s" % (REPO, BRANCH)
ZIP_URL = "https://codeload.github.com/%s/zip/%s"          # % (REPO, コミット)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "lite", ".installed.json")
MAX_ZIP = 200 * 1024 * 1024
MAX_FILES = 5000
PROTECTED = (".git", "lite/.venv", "lite/.installed.json", "lite/.update", "editor/.venv")   # 上書きしない(友人の環境と記録)
TIMEOUT = 20


def say(msg):
    try:
        print("[更新] " + msg, flush=True)
    except UnicodeEncodeError:
        print("[update] " + msg.encode("ascii", "replace").decode("ascii"), flush=True)


def norm_remote(url):
    """git の origin の URL -> 比べる形(https://github.com/owner/repo。.git・末尾の / を取る・git@ も https に)"""
    u = str(url or "").strip()
    m = re.match(r"^git@github\.com:(.+)$", u)
    if m:
        u = "https://github.com/" + m.group(1)
    u = re.sub(r"\.git$", "", u.rstrip("/"))
    return u.lower()


def _git(args, run=subprocess.run):
    return run(["git", "-C", ROOT] + args, capture_output=True, text=True, timeout=120)


def update_git(run=subprocess.run, check_only=False):
    """git で clone したフォルダの更新 -> 結果の文(更新した・最新・しない理由)"""
    r = _git(["remote", "get-url", "origin"], run)
    if r.returncode != 0 or norm_remote(r.stdout) != norm_remote(REPO_URL):
        return "skip", "取得元が決まった場所(%s)ではないので、更新しません" % REPO_URL
    r = _git(["status", "--porcelain", "--untracked-files=no"], run)
    if r.returncode != 0:
        return "skip", "git の状態を読めませんでした"
    if r.stdout.strip():
        return "skip", "手元に変更があるので、更新しません(変更を残すため)"
    r = _git(["fetch", "--quiet", "origin", BRANCH], run)
    if r.returncode != 0:
        return "skip", "更新を確かめられませんでした(インターネットにつながっているか確かめてください)"
    head = _git(["rev-parse", "HEAD"], run).stdout.strip()
    new = _git(["rev-parse", "origin/" + BRANCH], run).stdout.strip()
    if not new or head == new:
        return "latest", "最新です"
    if check_only:
        return "available", "新しい版があります"
    r = _git(["merge", "--ff-only", "--quiet", "origin/" + BRANCH], run)
    if r.returncode != 0:
        return "skip", "更新できませんでした(手元の版が分かれています)"
    return "updated", "新しい版にしました(%s → %s)" % (head[:7], new[:7])


def _get(url, limit, opener=urllib.request.urlopen):
    if not url.startswith(("https://api.github.com/", "https://codeload.github.com/")):   # 決まった取得元だけ
        raise ValueError("取得元が違います: " + url)
    req = urllib.request.Request(url, headers={"User-Agent": "youtube-tools-lite", "Accept": "application/vnd.github+json"})
    with opener(req, timeout=TIMEOUT) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("大きすぎます")
    return data


def latest_sha(opener=urllib.request.urlopen):
    d = json.loads(_get(API_URL, 1024 * 1024, opener).decode("utf-8"))
    sha = str(d.get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("コミットの形が違います")
    return sha


def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def zip_members(zf):
    """codeload の zip の中身 -> [(ZipInfo, 上のフォルダを除いたパス)]。形が違えば ValueError(1つでも危ない名前があれば全部断る)"""
    infos = zf.infolist()
    if not infos or len(infos) > MAX_FILES:
        raise ValueError("中身の数が想定と違います")
    top = infos[0].filename.split("/")[0]
    if not top or not re.fullmatch(r"[A-Za-z0-9._-]+", top):
        raise ValueError("上のフォルダの名前が想定と違います")
    out = []
    for i in infos:
        n = i.filename
        if "\\" in n or n.startswith("/") or re.match(r"^[A-Za-z]:", n) or ".." in n.split("/") or not n.startswith(top + "/"):
            raise ValueError("危ない名前: %r" % n[:120])
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ValueError("リンクは受け付けません: %r" % n[:120])
        rel = n[len(top) + 1:]
        if not rel or n.endswith("/"):
            continue
        out.append((i, rel))
    return out


def protected(rel):
    rel = rel.replace("\\", "/")
    return any(rel == p or rel.startswith(p + "/") for p in PROTECTED)


def apply_zip(path, root=None):
    """取った zip を root(既定 = ROOT。呼ぶときに読む)に上書きする(PROTECTED は飛ばす)。-> 書いた数"""
    root = root or ROOT
    n = 0
    with zipfile.ZipFile(path) as zf:
        members = zip_members(zf)
        total = sum(i.file_size for i, _ in members)
        if total > MAX_ZIP * 3:
            raise ValueError("展開すると大きすぎます")
        for info, rel in members:
            if protected(rel):
                continue
            dst = os.path.join(root, *rel.split("/"))
            if not os.path.abspath(dst).startswith(os.path.abspath(root) + os.sep):
                raise ValueError("危ない名前: %r" % rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".lite-update.part"
            with zf.open(info) as src, open(tmp, "wb") as f:
                shutil.copyfileobj(src, f)
            os.replace(tmp, dst)
            n += 1
    return n


def update_zip(opener=urllib.request.urlopen, check_only=False):
    """zip で配ったフォルダの更新"""
    try:
        sha = latest_sha(opener)
    except Exception as e:   # 通信できない・非公開・API の上限など。起動は止めない
        return "skip", "更新を確かめられませんでした(%s)" % str(e)[:80]
    if read_state().get("sha") == sha:
        return "latest", "最新です"
    if check_only:
        return "available", "新しい版があります"
    tmpd = tempfile.mkdtemp(prefix="lite-update-")
    try:
        zpath = os.path.join(tmpd, "src.zip")
        with open(zpath, "wb") as f:
            f.write(_get(ZIP_URL % (REPO, sha), MAX_ZIP, opener))
        n = apply_zip(zpath)
        with open(STATE + ".part", "w", encoding="utf-8") as f:
            json.dump({"sha": sha, "repo": REPO, "branch": BRANCH}, f)
        os.replace(STATE + ".part", STATE)
        return "updated", "新しい版にしました(%s。%d 個のファイル)" % (sha[:7], n)
    except Exception as e:
        return "skip", "更新できませんでした(%s)" % str(e)[:120]
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def run(check_only=False):
    if os.environ.get("LITE_NO_UPDATE"):
        return "skip", "更新は止めてあります(LITE_NO_UPDATE)"
    if os.path.isdir(os.path.join(ROOT, ".git")) and shutil.which("git"):
        return update_git(check_only=check_only)
    return update_zip(check_only=check_only)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    state, msg = run(check_only="--check" in argv)
    say(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
