"""外部プログラム(ffmpeg・ffprobe・yt-dlp)の場所と、子プロセスを動かすときの小道具。

- find_tool … 外部プログラムの場所(固有の環境変数 → YTT_ → PATH → winget。全部の部品がここで探す)。tool_version / tool_output … その版を調べる
- no_window_flags … creationflags(窓を出さない・別グループ・優先度)。python_exe … 子プロセスに使う python.exe
- run … 子プロセスを最後まで動かして出力を集める(取り消し・時間切れで止める)。run_progress … ffmpeg の -progress を読みながら動かす(取り消し・無出力で止める)
- kill_quiet … 止める(上げない)。kill_tree … 孫ごと止める。KillJob … 親が落ちても子を残さない
- process_memory_mb … このプロセスのメモリ。why … 例外 → 画面に出せる短い理由
- MEDIA_TYPES・find_ffmpeg・ffmpeg_info・duration_in・media_duration・check_source・probe_media … 編集の動画・音声のファイルの小道具(拡張子・ffmpeg の場所と -i の出力・長さ・元のファイルの検査・映像と音声の有無。RS3-0A に編集の ed_state・ed_store から)
"""
import collections
import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

from . import errors as _errors

PRIORITY = {"low": "BELOW_NORMAL_PRIORITY_CLASS", "high": "ABOVE_NORMAL_PRIORITY_CLASS"}   # no_window_flags の priority
KILL_TREE_TIMEOUT = 15   # taskkill /T /F を待つ秒数
OUT_TIME = re.compile(r"^out_time_(?:us|ms)=(\d+)$")    # ffmpeg の -progress の進み具合の行(us も ms もマイクロ秒)


def ytt_env(name):
    """外部プログラムの名前 → 共通の環境変数の名前(ffmpeg → YTT_FFMPEG・yt-dlp → YTT_YTDLP)"""
    return "YTT_" + name.upper().replace("-", "")


def _env_file(names):
    """環境変数の並び names のうち、実在するファイルが入っている最初の値(無ければ None)"""
    for var in names:
        env = os.environ.get(var) if var else None
        if env and os.path.isfile(env):
            return env
    return None


def find_tool(name, env_var=None):
    """外部プログラム(ffmpeg・ffprobe・yt-dlp など)の場所。すべての部品の探し方はこの 1 つ(OPT1。2026-10-11)。順:
    1. ツール固有の環境変数 env_var(STUDIO_FFMPEG・TRANSCRIBE_FFMPEG・TRANSCRIBE_YTDLP など。互換のため先に見る = 今までの指定がそのまま効く)
    2. 共通の環境変数 ytt_env(name)(YTT_FFMPEG・YTT_FFPROBE・YTT_YTDLP)
    3. ffprobe だけ: 1・2 の ffmpeg の環境変数(名前の FFPROBE を FFMPEG にした物)で決めた ffmpeg の隣
    4. PATH
    5. winget の場所(_winget_dirs。PATH に通っていない PC = winget だけで入れた友人の PC でも見つかる)
    環境変数は実在するファイルのときだけ効く(PATH を通していない場所の道具を使うため・テストで偽物に差し替えるため)。見つからなければ None"""
    envs = [env_var, ytt_env(name)]
    p = _env_file(envs)
    if p:
        return p
    if name == "ffprobe":
        ff = _env_file([v.replace("FFPROBE", "FFMPEG") for v in envs if v])
        p = _in_dirs(name, [os.path.dirname(ff)]) if ff else None
        if p:
            return p
    return shutil.which(name) or _in_dirs(name, _winget_dirs())


# ---------- 動画・音声のファイル(編集の文字起こし・波形・付け替え・保管が使う。RS3-0A に編集の ed_state・ed_store から移した) ----------
# 編集の部品は呼ぶたびに tools.名前 で読む(テストの S.find_ffmpeg = …・patch.object(S, "check_source", …) は編集の serve の名前の受付がここへ届ける)
MEDIA_TYPES = {   # 編集が受け付ける動画・音声の拡張子 → 配信する Content-Type(/media・check_source・フォルダの一括・付け替え)
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo", ".ts": "video/mp2t", ".flv": "video/x-flv",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".flac": "audio/flac",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wma": "audio/x-ms-wma",
}


def _winget_dirs():
    """winget が入れる場所(PATH に通っていなくても使えるように。LOCALAPPDATA が無ければ [])。
    Links(winget の道具の入口)→ Gyan.FFmpeg の bin(新しい版が先)→ yt-dlp.yt-dlp の入れ物(Links を作れなかった PC 用)"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    root = os.path.join(base, "Microsoft", "WinGet")
    pkgs = os.path.join(root, "Packages")
    return ([os.path.join(root, "Links")] + sorted(glob.glob(os.path.join(pkgs, "Gyan.FFmpeg*", "ffmpeg-*", "bin")), reverse=True)
            + sorted(glob.glob(os.path.join(pkgs, "yt-dlp.yt-dlp*")), reverse=True))


def _in_dirs(name, dirs):
    for d in dirs:
        p = shutil.which(name, path=d)
        if p:
            return p
    return None


def find_ffmpeg():
    """編集の ffmpeg(find_tool の決め方。固有の環境変数は TRANSCRIBE_FFMPEG)。無ければ None"""
    return find_tool("ffmpeg", "TRANSCRIBE_FFMPEG")


def media_tool(name):
    """ffmpeg / ffprobe の実行ファイルのパス(パックが呼ぶ。RS7-1 F-k)。find_tool の決め方で、固有の環境変数は TRANSCRIBE_<名前>
    (ffprobe は TRANSCRIBE_FFMPEG で決めた ffmpeg の隣も見る)。
    どこにも無ければ名前のまま(呼ぶと FileNotFoundError = 呼ぶ側の「見つかりません」の案内)"""
    return find_tool(name, "TRANSCRIBE_" + name.upper().replace("-", "")) or name


def ffmpeg_info(path, ff=None):
    """ffmpeg -i の出力(長さ・ストリームの行。probe_media も読む)。ffmpeg が無い・動かせなければ None"""
    ff = ff or find_ffmpeg()
    if not ff:
        return None
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout or ""


def duration_in(text):
    """ffmpeg -i の出力の Duration(秒)。無ければ None"""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def media_duration(path):
    """動画・音声の長さ(秒。ffmpeg -i の Duration)。ffmpeg が無い・読めなければ None"""
    out = ffmpeg_info(path)
    return duration_in(out) if out is not None else None


def check_source(path):
    """文字起こしの元のファイルのパス(前後の空白と引用符を外して絶対パスに)。無い・動画や音声の拡張子でなければ ApiError(400)"""
    p = os.path.abspath(str(path or "").strip().strip('"'))
    if not os.path.isfile(p):
        raise _errors.ApiError("no_file", "ファイルが見つかりません(パスを確認してください)", 400)
    if os.path.splitext(p)[1].lower() not in MEDIA_TYPES:
        raise _errors.ApiError("bad_ext", "動画・音声ファイルではないようです(対応: %s)" % " ".join(sorted(MEDIA_TYPES)), 400)
    return p


def probe_media(path):
    """ffmpeg -i で長さと、映像・音声の有無を調べる。-> (長さ秒 または None, 映像あり, 音声あり)。
    カバー画像(音声ファイルに付いた attached pic)は映像に数えない。ffmpeg が無ければ ApiError(400)"""
    ff = find_ffmpeg()
    if not ff:
        raise _errors.ApiError("no_ffmpeg", "ffmpeg が見つかりません(README の準備手順を確認してください)", 400)
    out = ffmpeg_info(path, ff)
    if out is None:
        return None, False, False
    dur = duration_in(out)
    streams = [l for l in out.splitlines() if re.match(r"\s*Stream #\d+:\d+", l)]
    has_v = any(": Video:" in l and "attached pic" not in l for l in streams)
    has_a = any(": Audio:" in l for l in streams)
    return dur, has_v, has_a


def no_window_flags(new_group=False, priority=None):
    """子プロセスの creationflags: Windows では黒い窓を出さない(CREATE_NO_WINDOW)。Windows 以外は 0。
    new_group=True は CREATE_NEW_PROCESS_GROUP も足す(Ctrl+C・CTRL_BREAK を親と分ける)。
    priority: None(親と同じ)・"low"(通常より下。書き出し・作り直し・文字起こしなど、画面の操作に CPU を譲る)・"high"(通常より上。録画)。
    それ以外の値は ValueError"""
    if priority is not None and priority not in PRIORITY:
        raise ValueError("priority は low か high です: %r" % (priority,))
    if os.name != "nt":
        return 0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if new_group else 0)
    return flags | (getattr(subprocess, PRIORITY[priority], 0) if priority else 0)


def python_exe(python=None):
    """子プロセスに使う Python(python、無ければこのプロセスの sys.executable)。窓の無い pythonw.exe は標準出力を返せないことがあるので、
    隣に python.exe があればそれにする(無ければそのまま)"""
    p = python or sys.executable
    if os.path.basename(p).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(p), "python.exe")
        if os.path.isfile(alt):
            return alt
    return p


def why(e):
    """例外 → 画面・記録に出せる短い理由(OSError は strerror。strerror の無いもの・ほかの例外は例外の名前)。
    パスや中身を出さない(e の文字列はパス・他人の書いた中身を含みうる)"""
    return getattr(e, "strerror", None) or e.__class__.__name__


def kill_quiet(proc):
    """子プロセスがまだ動いていれば止める(終わっていれば何もしない。止められなくても上げない)"""
    if proc.poll() is not None:
        return
    try:
        proc.kill()
    except OSError:
        pass


def kill_tree(proc, wait=None):
    """子プロセスを孫ごと止める(上げない)。yt-dlp(PyInstaller の 1 ファイルの exe)は起動すると子(本体)を作るので、親だけ止めると子が
    .part に書き続ける。Windows は System32 の taskkill /T /F(PATH を差し替えられても本物を呼ぶ)、ほかはプロセスグループに SIGKILL
    (起動するときに start_new_session=True にしておくこと。グループが無ければ子だけ止まる)。そのあと kill_quiet。
    proc が None・終わっていれば何もしない。本物のプロセス(Popen)でなければ(テストの偽物)kill_quiet だけ。
    wait(秒)を渡すと、止まるのをその秒数まで待つ(待ちきれなくても上げない)"""
    if proc is None:
        return
    if not isinstance(proc, subprocess.Popen):
        kill_quiet(proc)
        return
    if proc.poll() is not None:
        return
    if os.name == "nt":
        exe = os.path.join(os.environ.get("SystemRoot") or os.environ.get("windir") or "C:" + os.sep + "Windows", "System32", "taskkill.exe")
        try:
            subprocess.run([exe, "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=KILL_TREE_TIMEOUT, creationflags=no_window_flags())
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    kill_quiet(proc)
    if wait is not None:
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            pass


class RunResult(collections.namedtuple("RunResult", "code out err why")):
    """run の結果。code = 終了コード・out = 標準出力の bytes・err = 標準エラーの bytes・
    why = 止めた理由(None = 最後まで動いた・"cancel"・"timeout" のどれか)"""
    __slots__ = ()

    def err_lines(self, n=3):
        """標準エラーの空でない行の最後の n 行(前後の空白を除いた文字列。壊れた文字は置き換える)"""
        lines = [x.strip() for x in self.err.decode("utf-8", "replace").splitlines() if x.strip()]
        return lines[-n:] if n > 0 else []


def _drain(f, buf):
    """パイプを最後まで読んで buf(list か deque)に 1 行ずつ足す(読めなくなったら終わる)"""
    try:
        for line in f:
            buf.append(line)
    except (OSError, ValueError):
        pass


def run(cmd, timeout=None, cancelled=None, flags=None, stdout=True, err_tail=None, on_start=None, poll=0.3, **popen_kw):
    """子プロセスを 1 回、最後まで動かして出力を集める(シェルを通さない・標準入力なし)。取り消し・時間切れでは止める。-> RunResult
    - timeout: 秒(None = 待ち続ける)。過ぎたら止めて why = "timeout"
    - cancelled(): poll 秒ごとに見る。真なら止めて why = "cancel"。cancelled が例外を上げたら、子を止めてから上げ直す(中止を例外で伝える呼び出し側用)
    - flags: creationflags(既定 no_window_flags())。stdout=False なら標準出力は捨てる(out は b"")
    - err_tail: 標準エラーを最後の N 行だけ持つ(長く動く yt-dlp などでメモリを使い切らない)。None は全部
    - on_start(proc): 起動した直後に呼ぶ(呼ぶ側が「止める」ために proc を覚えるとき)
    - popen_kw: cwd・env・preexec_fn など、そのまま Popen へ
    起動できなければ OSError をそのまま上げる(呼ぶ側が自分の例外・文にする。理由の文は why(e))。
    止めるのは子だけ(kill)。孫ごと止めたいものは on_start で覚えて kill_tree を使う。止めたあと、出力のパイプは最大 5 秒で読み終える"""
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if stdout else subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=no_window_flags() if flags is None else flags, **popen_kw)
    out, err = [], (collections.deque(maxlen=err_tail) if err_tail else [])
    readers = [threading.Thread(target=_drain, args=(proc.stderr, err), daemon=True)]
    if stdout:
        readers.append(threading.Thread(target=_drain, args=(proc.stdout, out), daemon=True))
    for t in readers:
        t.start()
    end = None if timeout is None else time.monotonic() + timeout
    reason = None
    try:
        if on_start is not None:
            on_start(proc)
        while proc.poll() is None:
            if cancelled is not None and cancelled():
                reason = "cancel"
            elif end is not None and time.monotonic() > end:
                reason = "timeout"
            if reason:
                kill_quiet(proc)
                break
            try:
                proc.wait(poll)
            except subprocess.TimeoutExpired:
                pass
    except BaseException:
        kill_quiet(proc)
        raise
    finally:
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
        for t in readers:
            t.join(5)
        for f in (proc.stdout, proc.stderr):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
    return RunResult(proc.returncode, b"".join(out), b"".join(err), reason)


def run_progress(cmd, flags=None, cancelled=None, idle_sec=None, on_time=None, popen=None, tail=20):
    """ffmpeg を -progress pipe:1 つきで 1 回動かす(標準出力と標準エラーを 1 本で読む)。-> (終了コード, エラーの行の最後の tail 行, 止めた理由)
    止めた理由: None | "cancel"(cancelled() が真)| "idle"(idle_sec 秒なにも出力しなかった)。0.3 秒ごとに見る(取り消しが先)。
    - on_time(秒): 進み具合の行(out_time_us= / out_time_ms=。どちらもマイクロ秒)ごとに、出力した長さ(秒)で呼ぶ
    - エラーの行 = 進み具合の行と key=value の行(頭の 20 字に = がある)を除いた、空でない行
    - popen: 子プロセスの起動を差し替える(既定 subprocess.Popen)。flags: creationflags(既定 no_window_flags())
    起動できなければ OSError をそのまま上げる。on_time が上げた例外は、子を止めてから上げる"""
    lines = collections.deque(maxlen=tail)
    proc = (popen or subprocess.Popen)(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=no_window_flags() if flags is None else flags)
    state = {"last": time.time(), "why": None}
    done = threading.Event()

    def watchdog():
        while not done.wait(0.3):
            if cancelled is not None and cancelled():
                state["why"] = "cancel"
            elif idle_sec is not None and time.time() - state["last"] > idle_sec:
                state["why"] = "idle"
            else:
                continue
            kill_quiet(proc)
            return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        for raw in proc.stdout:
            state["last"] = time.time()
            line = raw.decode("utf-8", "replace").strip()
            m = OUT_TIME.match(line)
            if m:
                if on_time is not None:
                    on_time(int(m.group(1)) / 1e6)
                continue
            if line and "=" not in line[:20]:
                lines.append(line)
        proc.wait()
    finally:
        done.set()
        kill_quiet(proc)
        try:
            proc.stdout.close()
        except OSError:
            pass
    return proc.returncode, list(lines), state["why"]


def tool_output(path, args=("-version",), timeout=15):
    """外部プログラムを引数つきで動かした出力(標準出力 + 標準エラー。壊れた文字は置き換える)。動かせなければ ""。"""
    try:
        r = subprocess.run([path] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.decode("utf-8", "replace")


def tool_version(path, args=("-version",), pattern=r"version\s+(\S+)", timeout=15, first_line=False):
    """外部プログラムの版の文字(40 字まで)。出力(tool_output)から pattern の 1 つ目のかっこを抜く。見つからない・動かせなければ ""。
    first_line=True は出力の 1 行目だけを見て、見つからなければその行の先頭 60 字を返す(入口の「調子」の形)"""
    text = tool_output(path, args, timeout)
    if first_line:
        text = text.strip().splitlines()[0] if text.strip() else ""
    m = re.search(pattern, text)
    if m:
        return m.group(1)[:40]
    return text[:60] if first_line else ""


def process_memory_mb(peak=False):
    """このプロセスのメモリ(MB の float)。測れなければ None。
    Windows は WorkingSetSize(peak=True なら PeakWorkingSetSize)、ほかは /proc/self/statm の RSS(peak=True なら getrusage の ru_maxrss)"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):   # PROCESS_MEMORY_COUNTERS
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(c)
            k = ctypes.WinDLL("kernel32")   # 自分用の写し(argtypes を ctypes.windll の共有の物に付けない)
            psapi = ctypes.WinDLL("psapi")
            k.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
            if psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return (c.PeakWorkingSetSize if peak else c.WorkingSetSize) / 1048576.0
            return None
        if peak:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return r / (1048576.0 if sys.platform == "darwin" else 1024.0)
        with open("/proc/self/statm", "r") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576.0
    except Exception:
        return None


def memory_label():
    """このプロセスのメモリの記録用の文字(「812MB」。測れなければ「?」。編集の ed_state._mem の正。RS2-1a)"""
    m = process_memory_mb()
    return "%dMB" % m if m is not None else "?"


class KillJob:
    """Windows: 子プロセスを「閉じたら中のプロセスを終わらせる」ジョブ(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)に入れる。
    ジョブは close() か、このプロセスが終わる(落ちた・強制終了されたときも)ときに閉じる = 親が落ちても子が残らない
    (録画の部品の ffmpeg・streamlink が同じフォルダへ書き続けない、文字起こしの llama-server が GPU を掴み続けない)。
    1 つのジョブに何個でも入れられる。他の OS・作れなかったときは何もしない(add は False)。
    使い方: job = KillJob() → job.add(subprocess.Popen(…))。ジョブを持っている間だけ有効(録画の部品は Recorder が、llama-server はエンジンが持つ)"""

    def __init__(self):
        self.h = self.k = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class Ext(ctypes.Structure):   # JOBOBJECT_EXTENDED_LIMIT_INFORMATION を平らにした物(使うのは LimitFlags だけ。並びと大きさは同じ: 64 bit で 144 バイト・LimitFlags は 16 バイト目)
                _fields_ = [("UserTimeLimits", ctypes.c_int64 * 2), ("LimitFlags", wintypes.DWORD), ("WorkingSet", ctypes.c_size_t * 2),
                            ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("Classes", wintypes.DWORD * 2),
                            ("IoCounters", ctypes.c_uint64 * 6), ("MemoryLimits", ctypes.c_size_t * 4)]
            k = ctypes.WinDLL("kernel32", use_last_error=True)   # 自分用の写し(argtypes を ctypes.windll の共有の物に付けない)
            k.CreateJobObjectW.restype = wintypes.HANDLE
            k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
            k.OpenProcess.restype = wintypes.HANDLE
            k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k.CloseHandle.argtypes = (wintypes.HANDLE,)
            h = k.CreateJobObjectW(None, None)
            if not h:
                return
            info = Ext()
            info.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):   # 9 = JobObjectExtendedLimitInformation
                k.CloseHandle(h)
                return
            self.k, self.h = k, h
        except Exception:
            self.h = None

    def add(self, proc):
        """proc(subprocess.Popen)をジョブに入れる -> 入れられたか。失敗しても上げない(子はジョブの外で普通に動く)。
        プロセスのハンドルは pid から開き直す(要る権限だけ。Popen の非公開の _handle に頼らない。Popen が終わりを見届けるまで pid は使い回されない)"""
        if not self.h:
            return False
        try:
            p = self.k.OpenProcess(0x0101, False, proc.pid)   # PROCESS_SET_QUOTA | PROCESS_TERMINATE
            if not p:
                return False
            try:
                return bool(self.k.AssignProcessToJobObject(self.h, p))
            finally:
                self.k.CloseHandle(p)
        except Exception:
            return False

    def close(self):
        """ジョブを閉じる(中にまだ動いている子は終わる)。何度呼んでもよい"""
        h, self.h = self.h, None
        if h:
            try:
                self.k.CloseHandle(h)
            except Exception:
                pass
