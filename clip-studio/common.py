"""切り抜きスタジオ: 共通ユーティリティ(標準ライブラリのみ)。

ApiError / Cancelled は全モジュール共通(Handler は ApiError だけを捕まえればよい)。
データの置き場所は set_home() で変えられる(既定は studio/ フォルダ。環境変数 STUDIO_HOME でも指定可)。
"""
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
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


def replace_file(source, target):
    """Windows の一時的な共有違反だけ、短く待って再試行する。"""
    for attempt in range(4):
        try:
            os.replace(source, target)
            return
        except PermissionError as e:
            if getattr(e, "winerror", None) not in (5, 32, 33) or attempt == 3:
                raise
            time.sleep(0.1 * 2 ** attempt)


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
        replace_file(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # 後片付けの失敗で、本来の保存エラーを隠さない
        raise


# ---------- ログ・表示用 ----------
_URL_RE = re.compile(r"https?://\S+")


def redact(line):
    """署名つきURLなどはログ・画面に出さない。"""
    return _URL_RE.sub("<URL>", str(line))


_error_log_lock = threading.Lock()


def old_log_name(path):
    """studio.log → studio.old.log。*.log のまま回すのは、.gitignore の *.log に掛けるため
    (以前の studio.log.old は掛からず、push.bat の git add -A で公開リポジトリに載るおそれがあった)。"""
    root, ext = os.path.splitext(path)
    return root + ".old" + ext


def rotate_log(path, limit):
    """path が limit バイトを超えていたら、1世代だけ <名前>.old.<拡張子> に回す(前の .old は上書き)。"""
    if os.path.exists(path) and os.path.getsize(path) > limit:
        replace_file(path, old_log_name(path))


def migrate_old_logs():
    """以前の版が作った studio.log.old / studio-errors.log.old を studio.old.log などへ改名する(起動時に1回。失敗しても無視)。"""
    for name in ("studio.log", "studio-errors.log", "studio.crash.log"):
        old = p(name + ".old")
        try:
            if os.path.isfile(old):
                replace_file(old, old_log_name(p(name)))
        except OSError:
            pass


def log_failure(context, error):
    """握りつぶしていた処理エラーも、原因と失敗箇所をローカルに残す。"""
    try:
        with _error_log_lock:
            path = p("studio-errors.log")
            rotate_log(path, 1024 * 1024)
            with open(path, "a", encoding="utf-8") as f:
                detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                f.write("[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), context, redact(detail)))
    except OSError:
        pass


def permission_message(error):
    path = getattr(error, "filename2", None) or getattr(error, "filename", None)
    detail = " 対象: %s" % path if path else ""
    return ("ファイルへのアクセスが拒否されました。対象ファイルを再生・編集中のアプリを閉じ、"
            "保存先の書き込み権限とドライブの接続を確認してください。" + detail)


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


def ytdlp_out(folder, name_tmpl):
    """yt-dlp の -o(出力テンプレート)。テンプレートは % 書式なので、フォルダ側の % は %% にする
    (出力先の設定では % を断っているが、既定の exports/ や work/ はこのフォルダの場所しだいで % を含みうる)。
    name_tmpl はこちらで決めた名前(%(ext)s など)で、利用者の文字列は入れない(safe_name で % を除いている)。"""
    return os.path.join(str(folder).replace("%", "%%"), name_tmpl)


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


# ---------- 起動時の環境チェック(/api/state の env) ----------
YTDLP_OLD_DAYS = 60              # yt-dlp の版(日付)がこれより古ければ更新を勧める(YouTube 側の変更で古い版は取得に失敗しやすい)
LOW_DISK_BYTES = 2 * 1024 ** 3   # 出力先の空きがこれ未満なら注意
_env = {"checked": False, "tools": {}}
_env_lock = threading.Lock()


def _tool_version(name, args, pattern, timeout=15):
    exe = find_tool(name)
    if not exe:
        return {"found": False, "version": ""}
    try:
        r = subprocess.run([exe] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        m = re.search(pattern, r.stdout or "")
        return {"found": True, "version": m.group(1)[:40] if m else ""}
    except (OSError, subprocess.SubprocessError):
        return {"found": True, "version": ""}


def check_tools():
    """ffmpeg / ffprobe / yt-dlp の有無と版を調べて覚える(起動時に裏のスレッドで1回。数秒かかることがある)。"""
    tools = {"ffmpeg": _tool_version("ffmpeg", ["-hide_banner", "-version"], r"ffmpeg version (\S+)"),
             "ffprobe": {"found": bool(find_tool("ffprobe")), "version": ""}}
    tools["ytdlp"] = {"found": fake(), "version": ""} if fake() else _tool_version("yt-dlp", ["--version"], r"^\s*(\d{4}\.\d{2}\.\d{2}\S*)")
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", tools["ytdlp"]["version"])
    if m:
        try:
            tools["ytdlp"]["ageDays"] = (datetime.date.today() - datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
        except ValueError:
            pass
    with _env_lock:
        _env["tools"], _env["checked"] = tools, True
    return tools


def start_env_check():
    threading.Thread(target=check_tools, daemon=True, name="env-check").start()


def env_state():
    """{"checked", "python", "tools": {ffmpeg, ffprobe, ytdlp}, "outDirFree"(バイト or None), "warnings": [画面に出せる文]}。
    道具の版は起動時に調べた結果(調べ終わるまでは checked=false)。空き容量は毎回その場で調べる(速い)。"""
    with _env_lock:
        tools = json.loads(json.dumps(_env["tools"]))
        checked = _env["checked"]
    warnings = []
    free = None
    try:
        d = get_out_dir()
        while d and not os.path.isdir(d) and os.path.dirname(d) != d:   # まだ作っていない出力先は、存在する親で測る
            d = os.path.dirname(d)
        free = shutil.disk_usage(d).free
        if free < LOW_DISK_BYTES:
            warnings.append("書き出し先のドライブの空きが少なくなっています(残り %.1f GB)" % (free / 1024 ** 3))
    except OSError:
        pass
    if not find_tool("ffmpeg"):
        warnings.append("ffmpeg が見つかりません。解析・書き出しに必要です(README の準備手順を確認してください)")
    if not fake() and not find_tool("yt-dlp"):
        warnings.append("yt-dlp が見つかりません。YouTube の解析・書き出しに必要です(手元のファイルは使えます)")
    age = (tools.get("ytdlp") or {}).get("ageDays")
    if isinstance(age, int) and age > YTDLP_OLD_DAYS:
        warnings.append("yt-dlp が古い可能性があります(%s。%d日前の版)。取得に失敗するときは「yt-dlp -U」で更新してください"
                        % (tools["ytdlp"]["version"], age))
    return {"checked": checked, "python": sys.version.split()[0], "tools": tools, "outDirFree": free, "warnings": warnings}
