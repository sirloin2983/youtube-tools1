"""切り抜きスタジオ: 共通ユーティリティ(標準ライブラリのみ)。

ApiError / Cancelled は全モジュール共通(Handler は ApiError だけを捕まえればよい)。
データの置き場所は set_home() で変えられる(既定は studio/ フォルダ。環境変数 STUDIO_HOME でも指定可)。
"""
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse

CODE_DIR = os.path.dirname(os.path.abspath(__file__))   # コード・静的ファイル・seed.json の場所
_home = os.path.abspath(os.environ.get("STUDIO_HOME") or CODE_DIR)   # data.json などの置き場所

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}\Z")
VID_RE = re.compile(r"^[\w-]{11}\Z", re.ASCII)   # ASCII のみ・末尾の改行も不可
MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".aac", ".ts", ".flv"}


class ApiError(Exception):
    def __init__(self, code, message, status=400, extra=None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra


class Cancelled(Exception):
    pass


def set_home(d):
    global _home
    _home = os.path.abspath(d)
    os.makedirs(_home, exist_ok=True)
    reset_out_dir()


def home():
    return _home


def p(*parts):
    """データ置き場の中のパス。"""
    return os.path.join(_home, *parts)


def fake():
    """疑似モード(テスト用)。"""
    return os.environ.get("STUDIO_FAKE") == "1"


def find_tool(name):
    env = os.environ.get("STUDIO_" + name.upper().replace("-", ""))
    if env and os.path.isfile(env):
        return env
    return shutil.which(name)


def atomic_write(path, data: bytes, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())   # 電源断などに備える(できなければ無視)
            except OSError:
                pass
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------- ログ・表示用 ----------
_URL_RE = re.compile(r"https?://\S+")


def redact(line):
    """署名つきURLなどはログ・画面に出さない。"""
    return _URL_RE.sub("<URL>", str(line))


def tail_reason(err, n=2):
    keep = [redact(l)[:220] for l in err if l.strip()]
    key = [l for l in keep if re.search(r"error|fail|forbidden|denied|invalid|not found|unable|HTTP|403|404|private|unavailable|Sign in", l, re.I)]
    return " / ".join((key or keep)[-n:])


def fmt_ts(t):
    t = max(0.0, float(t))
    return "%02d:%02d:%06.3f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


def fmt_ms(t):
    t = int(max(0, t))
    return "%d:%02d" % (t // 60, t % 60)


def num(v, lo, hi, default):
    if isinstance(v, bool):
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(x) else max(lo, min(hi, x))


# ---------- APIキー ----------
def get_api_key():
    """(キー, "env"|"file"|None)。環境変数 YOUTUBE_API_KEY が優先。"""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        return key, "env"
    try:
        with open(p("config.json"), encoding="utf-8") as f:
            key = str(json.load(f).get("apiKey", "")).strip()
        if key:
            return key, "file"
    except (OSError, ValueError, AttributeError):
        pass
    return "", None


def set_api_key(raw):
    key = str(raw or "").strip()
    if key and not KEY_RE.match(key):
        raise ApiError("key_format", "APIキーの形式が正しくありません", 400)
    if key:
        atomic_write(p("config.json"), json.dumps({"apiKey": key}).encode("utf-8"), 0o600)
    elif os.path.exists(p("config.json")):
        os.unlink(p("config.json"))
    return bool(get_api_key()[0])


# ---------- 入力の検査 ----------
def parse_video_id(text):
    """YouTube の URL(watch / youtu.be / live / shorts / embed)または11文字のID → 動画ID。"""
    raw = str(text or "")
    if VID_RE.match(raw.strip(" \t")):   # 素のID(改行などは不可)
        return raw.strip(" \t")
    t = raw.strip()
    try:
        u = urllib.parse.urlsplit(t if "://" in t else "https://" + t)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host in ("youtu.be",):
        cand = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        parts = [x for x in u.path.split("/") if x]
        if u.path.startswith("/watch"):
            cand = (urllib.parse.parse_qs(u.query).get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("live", "shorts", "embed", "v"):
            cand = parts[1]
        else:
            return None
    else:
        return None
    return cand if VID_RE.match(cand) else None


def check_media_path(raw):
    """手元の動画・音声ファイルのパスを検査して絶対パスを返す。"""
    s = str(raw or "").strip().strip('"')
    if not s or "\x00" in s or len(s) > 1000 or not os.path.isfile(s) or os.path.splitext(s)[1].lower() not in MEDIA_EXT:
        raise ApiError("bad_source", "ファイルが見つかりません(動画・音声ファイルのパスを指定してください)", 400)
    return os.path.abspath(s)


def file_video_id(path):
    """file 動画の id: "f" + sha1(絶対パス) の先頭10桁(11文字)。"""
    return "f" + hashlib.sha1(os.path.abspath(path).encode("utf-8", "surrogatepass")).hexdigest()[:10]


# ---------- ffmpeg でメディア情報 ----------
def media_info(path):
    """(長さ秒 or None, 映像あり, 音声あり, 映像ストリームの行)。ffprobe がなくても動く。"""
    ff = find_tool("ffmpeg")
    if not ff:
        return None, False, False, ""
    try:
        pr = subprocess.run([ff, "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, False, False, ""
    out = pr.stdout or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    vm = re.search(r"Stream #.*Video:.*", out)
    return dur, bool(vm), bool(re.search(r"Stream #.*Audio:", out)), (vm.group(0).strip()[:300] if vm else "")


def media_duration(path):
    d, has_v, _a, _l = media_info(path)
    return d, has_v


def has_audio_stream(path):
    d, _v, a, _l = media_info(path)
    return a if find_tool("ffmpeg") else True


# ---------- 外部コマンド(中止・時間切れ対応。子プロセスも含めて止める) ----------
KILL_GRACE = 3.0   # SIGTERM のあと、この秒数で終わらなければ SIGKILL


def spawn(cmd, **kw):
    """外部コマンドを起動する。POSIX では新しいセッション(=プロセスグループ)にして、孫プロセスごと止められるようにする。"""
    if os.name != "nt":
        kw["start_new_session"] = True
    else:   # 別のプロセスグループにして、黒い画面への Ctrl+C / Ctrl+Break を子に流さない・子の終了で画面が巻き込まれないようにする
        kw["creationflags"] = kw.get("creationflags", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(cmd, **kw)


def _signal_tree(proc, sig):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            os.killpg(proc.pid, sig)   # グループID = 起動したプロセスのPID
    except (OSError, subprocess.SubprocessError):
        try:
            proc.send_signal(sig) if os.name != "nt" else proc.kill()
        except (OSError, ValueError):
            pass


def hard_kill(proc):
    if proc is None:
        return
    _signal_tree(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
    try:
        proc.kill()
    except OSError:
        pass


def terminate(proc, grace=None):
    """止める依頼(待たない): 子プロセスごと SIGTERM(Windows は taskkill /T /F)。猶予のあと残っていれば SIGKILL。"""
    if not proc or proc.poll() is not None:
        return
    _signal_tree(proc, signal.SIGTERM)
    if os.name == "nt":
        return

    def escalate():
        time.sleep(KILL_GRACE if grace is None else grace)
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # 残っていれば(孫プロセスを含む)強制終了。なければ何もしない
        except OSError:
            pass
    threading.Thread(target=escalate, daemon=True).start()


def idle_message(what, sec):
    return "%sが%s、出力がなかったため中止しました" % (what, ("%d分間" % max(1, round(sec / 60))) if sec >= 60 else ("%d秒間" % max(1, round(sec))))


def run_capture(job, cmd, on_line=None, timeout=None, slot="proc", idle_timeout=None, what="処理"):
    """コマンドを実行し、標準出力を1行ずつ on_line に渡す。(終了コード, 標準エラーの末尾) を返す。中止に対応。
    job は {"cancel": bool, <slot>: Popen} を持つ辞書。idle_timeout 秒のあいだ出力(標準出力・標準エラー)が無ければ止めて ApiError("timeout")。"""
    p_ = spawn(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1)
    job[slot] = p_
    err = []
    last = [time.time()]
    idle = [False]

    def drain():
        for l in p_.stderr:
            last[0] = time.time()
            err.append(l.rstrip())
            del err[:-40]
    th = threading.Thread(target=drain, daemon=True)
    th.start()
    t0 = time.time()
    done = threading.Event()

    def watchdog():   # 出力が止まっていても、中止・時間切れで確実に止める
        while not done.wait(0.5):
            now = time.time()
            if job["cancel"] or (timeout and now - t0 > timeout):
                terminate(p_)
                return
            if idle_timeout and now - last[0] > idle_timeout:
                idle[0] = True
                terminate(p_)
                return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        for line in p_.stdout:
            last[0] = time.time()
            if job["cancel"] or (timeout and time.time() - t0 > timeout):
                terminate(p_)
                break
            if on_line:
                on_line(line.rstrip("\n"))
        try:
            p_.wait(timeout=30)
        except subprocess.TimeoutExpired:
            hard_kill(p_)
            try:
                p_.wait(5)
            except subprocess.TimeoutExpired:
                pass
        th.join(2)
    finally:
        done.set()
        job[slot] = None
        if p_.poll() is None:
            hard_kill(p_)
    if job["cancel"]:
        raise Cancelled()
    if idle[0]:
        raise ApiError("timeout", idle_message(what, idle_timeout), 504)
    return p_.returncode, err


# ---------- 出力先フォルダ(settings.json の outDir) ----------
_out_dir = None   # None = 標準


def default_out_dir():
    return p("exports")


def reset_out_dir():
    global _out_dir
    _out_dir = None


def get_out_dir():
    return _out_dir or default_out_dir()


def check_out_dir(raw):
    """入力された保存先を検査して、絶対パスにして返す(空なら標準に戻す)。作れない・書き込めないときは ApiError。"""
    s = str(raw or "").strip().strip('"')
    if not s:
        return default_out_dir()
    if "\x00" in s or len(s) > 400:
        raise ApiError("bad_dir", "保存先のパスが正しくありません", 400)
    if "%" in s:
        raise ApiError("bad_dir", "保存先に「%」は使えません(yt-dlp の出力指定と衝突するため)。別のフォルダを指定してください", 400)
    s = os.path.expanduser(s)
    if not os.path.isabs(s):
        raise ApiError("bad_dir", "保存先は、C:\\Users\\… や /Users/… のようにフルパスで指定してください", 400)
    s = os.path.abspath(s)
    if os.path.dirname(s) == s:
        raise ApiError("bad_dir", "ドライブの直下ではなく、その中のフォルダ(例: D:\\clips)を指定してください", 400)
    try:
        os.makedirs(s, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=s, prefix=".write-test-"):
            pass
    except OSError as e:
        raise ApiError("bad_dir", "そのフォルダを作れない、または書き込めません: " + str(e.strerror or e)[:120], 400)
    return s


def load_out_dir():
    global _out_dir
    _out_dir = None
    try:
        with open(p("settings.json"), encoding="utf-8") as f:
            v = json.load(f).get("outDir")
        if v:
            _out_dir = check_out_dir(v)
            if _out_dir == default_out_dir():
                _out_dir = None
    except (OSError, ValueError, ApiError, AttributeError):
        _out_dir = None   # 消えた・書き込めなくなったときは標準に戻す(画面に出るパスで分かる)


_out_lock = threading.Lock()
BUSY_MSG = "処理の実行中は出力先を変えられません。終わってから変更してください"


def set_out_dir(raw, busy):
    """busy: 実行中の処理があるかを返す関数。実行中は 409。"""
    global _out_dir
    if busy():   # フォルダを作る前に判定(拒否したときに空フォルダを残さない)
        raise ApiError("busy", BUSY_MSG, 409)
    new = check_out_dir(raw)
    with _out_lock:
        if busy():
            raise ApiError("busy", BUSY_MSG, 409)
        if new == default_out_dir():
            if os.path.exists(p("settings.json")):
                os.unlink(p("settings.json"))
            _out_dir = None
        else:
            atomic_write(p("settings.json"), json.dumps({"outDir": new}, ensure_ascii=False).encode("utf-8"))
            _out_dir = new
    return new
