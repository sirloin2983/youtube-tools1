# -*- coding: utf-8 -*-
"""友人の PC の yt-dlp をいつも新しく(YouTube の bot 判定・仕様の変更に古い yt-dlp は当たりやすい。notes:docs/spec/friend.md の 13-13)。

1 日 1 回まで(記録 <friend>/ytdlp-update.json の checkedAt)、公式の GitHub の releases/latest を見て、今の版より新しければ取り替える:
  1. 公式の SHA2-256SUMS から yt-dlp.exe の SHA-256 を読み、yt-dlp.exe を <tools>/yt-dlp/yt-dlp.exe.new へ取る(大きさの上限つき)。SHA-256 が合わなければ捨てる
  2. 新しい物で --version(版が release の名前と同じ)と軽い問い合わせ(短い公開の動画の id を --simulate で 1 回)
     問い合わせが駄目でも、今の版でも同じく駄目なら(= bot 判定などで新しい版のせいではない)取り替える。今の版で通るなら取り替えない
  3. 今の物を yt-dlp.exe.old へ回して(動いている yt-dlp があっても名前は変えられる)新しい物を置く。置けなければ戻す。
     setup の「取り終えたか」(大きさが表と同じ)が取り直さないように、印 .replaced-yt-dlp.exe に大きさと SHA-256 を書く(setup.is_done が読む)
  取り替えた・駄目だった版と理由は記録へ(診断の yt.ytdlp = facts)。窓は出さない(ytt/tools.run)。
スイッチ: 環境変数 YTT_YTDLP_UPDATE=0 で見ない。ユーザーの PC(places.is_maker_data)では動かない(winget の yt-dlp を使う)。
"""
import json
import os
import re
import threading
import time
import urllib.request

from ytt import fsio as _fsio, tools as _tools, version as _version

SWITCH_ENV = "YTT_YTDLP_UPDATE"
RECORD = "ytdlp-update.json"
EXE = "yt-dlp.exe"
MARK = ".replaced-" + EXE
API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
DL = "https://github.com/yt-dlp/yt-dlp/releases/download/%s/%s"
EVERY = 24 * 3600
MAX_BYTES = 64 * 1024 * 1024
TIMEOUT = 60
RUN_TIMEOUT = 90
TAG_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}(?:\.\d+)?$")
SHA_RE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)$")
PROBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # 短い公開の動画(Me at the zoo)
PROBE_ID = "jNQXAC9IVRw"

_lock = threading.Lock()
_running = [False]


def _http(url, max_bytes):
    req = urllib.request.Request(url, headers={"User-Agent": "ytt-friend/%s" % _version.VERSION})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:   # noqa: S310  (固定の https)
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise OSError("想定より大きい")
    return data


def _run(cmd, timeout=RUN_TIMEOUT):
    r = _tools.run(cmd, timeout=timeout)
    return r.code, (r.out or b"").decode("utf-8", "replace").strip(), r.why


def record_path(friend_dir):
    return os.path.join(friend_dir, RECORD)


def ver_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def latest(http=_http):
    """-> (tag, sha256)。公式の release と SHA2-256SUMS"""
    tag = (json.loads(http(API, 1 << 20).decode("utf-8")).get("tag_name") or "").strip()
    if not TAG_RE.match(tag):
        raise ValueError("release の名前の形が違います")
    for line in http(DL % (tag, "SHA2-256SUMS"), 1 << 16).decode("utf-8", "replace").splitlines():
        m = SHA_RE.match(line.strip().lower())
        if m and m.group(2) == EXE:
            return tag, m.group(1)
    raise ValueError("SHA2-256SUMS に %s がありません" % EXE)


def probe(exe, run=_run):
    """軽い問い合わせ(--simulate で id を 1 回)-> 通ったか"""
    cmd = [exe, "--encoding", "utf-8", "--simulate", "--no-warnings", "--no-playlist", "--print", "id"] + _tools.ytdlp_auth_args() + ["--", PROBE_URL]
    try:
        code, text, why = run(cmd)
    except OSError:
        return False
    return code == 0 and not why and PROBE_ID in text


def version_of(exe, run=_run):
    try:
        code, text, why = run([exe, "--version"], 60)
    except OSError:
        return ""
    return text.splitlines()[0].strip()[:40] if code == 0 and not why and text else ""


def mark_ok(fold, size):
    """setup.is_done が読む: 取り替えた印の大きさが今のファイルと同じか"""
    m = _fsio.read_json_or(os.path.join(fold, MARK), {})
    return isinstance(m, dict) and m.get("size") == size


def update(exe, friend_dir, now=None, http=_http, run=_run, force=False, log=print):
    """1 回見る(上の説明)-> 記録の dict。1 日 1 回まで(force で無視)"""
    now = time.time() if now is None else now
    rp = record_path(friend_dir)
    rec = _fsio.read_json_or(rp, {})
    rec = rec if isinstance(rec, dict) else {}
    if not force and now - float(rec.get("checkedAt") or 0) / 1000 < EVERY:
        return rec
    rec["checkedAt"] = int(now * 1000)
    rec.pop("error", None)
    fold = os.path.dirname(exe)
    new, old = exe + ".new", exe + ".old"
    _fsio.unlink_quiet(old)   # 前の回の物(動いていて消せなければ次の回)
    try:
        cur = version_of(exe, run)
        rec["version"] = cur or rec.get("version")
        tag, sha = latest(http)
        rec["latest"] = tag
        if cur and ver_key(tag) <= ver_key(cur):
            return _save(rp, rec)
        data = http(DL % (tag, EXE), MAX_BYTES)
        _fsio.atomic_write(new, data)
        if _fsio.sha256_file(new) != sha:
            raise ValueError("SHA-256 が合いません")
        got = version_of(new, run)
        if ver_key(got) != ver_key(tag):
            raise ValueError("新しい物の --version が %s でした" % (got or "空"))
        if not probe(new, run) and probe(exe, run):
            raise ValueError("新しい物だけ問い合わせが通りません")
        _fsio.replace_retry(exe, old)
        try:
            _fsio.replace_retry(new, exe)
        except OSError:
            _fsio.replace_retry(old, exe)
            raise
        _fsio.write_json(os.path.join(fold, MARK), {"size": os.path.getsize(exe), "sha256": sha, "version": tag, "at": int(now * 1000)})
        rec.update(prev=cur, version=tag, updatedAt=int(now * 1000))
        log("yt-dlp を %s から %s に取り替えました" % (cur or "?", tag))
    except (OSError, ValueError) as e:
        rec["error"] = (str(e) or e.__class__.__name__)[:200]
        log("yt-dlp の取り替えを見送りました: %s" % rec["error"])
    finally:
        _fsio.unlink_quiet(new)
    return _save(rp, rec)


def _save(rp, rec):
    try:
        _fsio.write_json(rp, rec)
    except OSError:
        pass
    return rec


def enabled(env, maker=False):
    return not maker and (env.get(SWITCH_ENV) or "").strip() != "0"


def maybe_start(env, friend_dir, tools_dir, log=print, maker=False):
    """見回りから呼ぶ: 期限が来ていて動いていなければ別の糸で update -> 始めたか。
    取り替えるのはアプリの tools/ の下の yt-dlp.exe だけ(PATH の winget の物・開発の PC の物は触らない)"""
    exe = (env.get("YTT_YTDLP") or "").strip()
    if not enabled(env, maker) or not exe or os.path.basename(exe).lower() != EXE or not os.path.isfile(exe) \
            or not _fsio.is_inside(exe, tools_dir, strict=True):
        return False
    rec = _fsio.read_json_or(record_path(friend_dir), {})
    if isinstance(rec, dict) and time.time() - float(rec.get("checkedAt") or 0) / 1000 < EVERY:
        return False
    with _lock:
        if _running[0]:
            return False
        _running[0] = True

    def job():
        try:
            update(exe, friend_dir, log=log)
        finally:
            _running[0] = False
    threading.Thread(target=job, name="friend-ytdlp-update", daemon=True).start()
    return True


def facts(env):
    """診断に入れる物: 版・前の版・取り替えた時刻・見た時刻・最後の理由(記録から)"""
    from . import places as _places
    rec = _fsio.read_json_or(record_path(_places.friend_dir(env)), {})
    if not isinstance(rec, dict) or not rec:
        return None
    return {k: rec[k] for k in ("version", "prev", "updatedAt", "checkedAt", "latest", "error") if rec.get(k) is not None}
