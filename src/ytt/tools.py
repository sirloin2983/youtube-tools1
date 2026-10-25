"""外部プログラム(ffmpeg・ffprobe・yt-dlp)の場所と、子プロセスを動かすときの小道具。

- find_tool … 外部プログラムの場所(固有の環境変数 → YTT_ → PATH → winget。全部の部品がここで探す。ffmpeg は PATH が開発版なら winget の正式版 = pick_ffmpeg)。tool_version / tool_output … その版を調べる
- no_window_flags … creationflags(窓を出さない・別グループ・優先度)。python_exe … 子プロセスに使う python.exe
- start_logged … 常駐の子プロセスを、出力をログに足す形で起こす
- run … 子プロセスを最後まで動かして出力を集める(取り消し・時間切れで止める)。run_progress … ffmpeg・yt-dlp の出力(-progress の進み具合)を 1 行ずつ読みながら動かす(取り消し・時間切れ・無出力で止める。窓なし・優先度「低」。ffmpeg を動かす形はこの 1 つ)
- kill_quiet … 止める(上げない)。kill_tree … 孫ごと止める。KillJob … 親が落ちても子を残さない
- process_memory_mb … このプロセスのメモリ。why … 例外 → 画面に出せる短い理由
- remember・recent … run・run_progress・procs.run_short で動かした道具の名前・終了コード・秒・失敗の最後の数行(引数は持たない)を最近の 40 件だけ覚える(友人の診断 friendapp/diag が読む)
- MEDIA_TYPES・find_ffmpeg・ffmpeg_info・parse_ffmpeg_info・duration_in・media_duration・check_source・probe_media … 編集の動画・音声のファイルの小道具(拡張子・ffmpeg の場所と -i の出力・-i の読み方(parse_ffmpeg_info。mediainfo も使う)・長さ・元のファイルの検査・映像と音声の有無)
"""
import collections
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

from . import errors as _errors, fsio as _fsio, ytcookies as _ytcookies

PRIORITY = {"low": "BELOW_NORMAL_PRIORITY_CLASS", "high": "ABOVE_NORMAL_PRIORITY_CLASS", "idle": "IDLE_PRIORITY_CLASS"}   # no_window_flags の priority(idle = 後回しの仕事。PRIO)
KILL_TREE_TIMEOUT = 15   # taskkill /T /F を待つ秒数
OUT_TIME = re.compile(r"^out_time_(?:us|ms)=(\d+)$")    # ffmpeg の -progress の進み具合の行(us も ms もマイクロ秒)
PROGRESS_KV = re.compile(r"^(?:frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time|dup_frames|drop_frames|speed|progress)=[^=]*$")
# ↑ -progress の塊の 1 行(= が 1 つだけ。統計の行「frame=  1 fps=… time=…」は = が多いので入らない = yt-dlp の区間取得の進みは数える)
RECENT = collections.deque(maxlen=40)   # 最近動かした道具の記録(remember)
RECENT_TAIL = 8                         # 失敗したときに覚える最後の行数


def remember(cmd, code, lines, why, t0):
    """動かした道具を 1 件覚える: {name(exe の名前だけ。引数は持たない), code, why, at(終わったミリ秒), sec, tail(失敗のときだけ最後の数行)}。
    t0 = 始めた time.monotonic()。覚えられなくても呼んだ側は止めない"""
    try:
        name = os.path.splitext(os.path.basename(str(cmd[0] if isinstance(cmd, (list, tuple)) else cmd)))[0][:40] if cmd else "?"
        tail = []
        if code or why:
            for x in list(lines or [])[-RECENT_TAIL:]:
                tail.append((x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)).rstrip()[:300])
        RECENT.append({"name": name, "code": code, "why": why, "at": int(time.time() * 1000), "sec": round(time.monotonic() - t0, 1), "tail": tail})
        from . import ytledger   # YouTube への問い合わせの帳簿(yt-dlp なら 1 行。取得の列が読む = 製品が先・列が譲る。10-25 夜)
        ytledger.from_run(cmd, code, lines, why)
    except Exception:   # noqa: BLE001  (記録で道具の呼び出しを壊さない)
        pass


def recent(since_ms=0):
    """覚えた道具の記録のうち at が since_ms 以降の物(古い順の写し)"""
    return [dict(r) for r in list(RECENT) if r.get("at", 0) >= since_ms]


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
    """外部プログラム(ffmpeg・ffprobe・yt-dlp など)の場所。すべての部品の探し方はこの 1 つ(OPT1)。順:
    1. 引数 env_var で渡した環境変数(省くと見ない)
    2. 共通の環境変数 ytt_env(name)(YTT_FFMPEG・YTT_FFPROBE・YTT_YTDLP)
    3. ffprobe だけ: 1・2 の ffmpeg の環境変数(名前の FFPROBE を FFMPEG にした物)で決めた ffmpeg の隣
    4. ffmpeg・ffprobe: pick_ffmpeg で決めた ffmpeg(PATH の物が開発版で、winget の Gyan に正式版があれば正式版)とその隣の ffprobe
    5. PATH
    6. winget の場所(_winget_dirs。PATH に通っていない PC = winget だけで入れた友人の PC でも見つかる)
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
    if name in ("ffmpeg", "ffprobe"):
        ff = pick_ffmpeg()
        p = ff if name == "ffmpeg" else (_in_dirs(name, [os.path.dirname(ff)]) if ff else None)
        if p:
            return p
    return shutil.which(name) or _in_dirs(name, _winget_dirs())


_VERSIONS = {}   # (パス, 更新時刻) → ffmpeg -version の版の文字(find_tool のたびに動かさない)


def _ffmpeg_version(path):
    try:
        key = (os.path.normcase(os.path.abspath(path)), os.stat(path).st_mtime_ns)
    except OSError:
        return ""
    if key not in _VERSIONS:
        _VERSIONS[key] = tool_version(path)
    return _VERSIONS[key]


def is_dev_build(path):
    """ffmpeg の開発版(-version の版の文字が N- で始まる。毎晩の版 = 新しい符号化器が止まることがある。10-24 の N-126374 の aac)"""
    return _ffmpeg_version(path).startswith("N-")


def pick_ffmpeg():
    """環境変数の指定が無いときの ffmpeg: PATH の物。ただしそれが開発版で、winget の Gyan(_release_dirs)に正式版があれば正式版。
    PATH に無ければ winget の場所。見つからなければ None"""
    ff = shutil.which("ffmpeg")
    if ff and is_dev_build(ff):
        for d in _release_dirs():
            rel = _in_dirs("ffmpeg", [d])
            if rel and not is_dev_build(rel) and _ffmpeg_version(rel):
                return rel
    return ff or _in_dirs("ffmpeg", _winget_dirs())


def _release_dirs():
    """正式版の ffmpeg がありそうな場所(winget の Gyan.FFmpeg の bin。新しい版が先)"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    return sorted(glob.glob(os.path.join(base, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "ffmpeg-*", "bin")), reverse=True)


# ---------- 動画・音声のファイル(編集の文字起こし・波形・付け替え・保管が使う) ----------
# 編集の部品は呼ぶたびに tools.名前 で読む(テストは tools の名前を差し替える)
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
    return ([os.path.join(root, "Links")] + _release_dirs()
            + sorted(glob.glob(os.path.join(pkgs, "yt-dlp.yt-dlp*")), reverse=True))


def _in_dirs(name, dirs):
    for d in dirs:
        p = shutil.which(name, path=d)
        if p:
            return p
    return None


def find_ffmpeg():
    """編集の ffmpeg(find_tool の決め方)。無ければ None"""
    return find_tool("ffmpeg")


def media_tool(name):
    """ffmpeg / ffprobe の実行ファイルのパス(パックが呼ぶ。RS7-1 F-k)。find_tool の決め方(ffprobe は YTT_FFMPEG で決めた ffmpeg の隣も見る)。
    どこにも無ければ名前のまま(呼ぶと FileNotFoundError = 呼ぶ側の「見つかりません」の案内)"""
    return find_tool(name) or name


def ffmpeg_info(path, ff=None):
    """ffmpeg -i の出力(長さ・ストリームの行。probe_media も読む)。ffmpeg が無い・動かせなければ None"""
    ff = ff or find_ffmpeg()
    if not ff:
        return None
    try:
        p = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=30,
                           creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout or ""


def parse_ffmpeg_info(text):
    """ffmpeg -i の出力の読み方(ここが 1 か所。ffmpeg は動かさない)。-> (長さ秒 or None, 映像あり, 音声あり, 映像ストリームの行)。
    映像はカバー画像(音声ファイルに付いた attached pic)を数えない。映像の行はカバー画像でない最初の Video の行(前後の空白を除いて 300 字まで。無ければ "")"""
    text = text or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    streams = [l for l in text.splitlines() if re.match(r"\s*Stream #\d+:\d+", l)]
    vline = next((l.strip()[:300] for l in streams if ": Video:" in l and "attached pic" not in l), "")
    return dur, bool(vline), any(": Audio:" in l for l in streams), vline


def duration_in(text):
    """ffmpeg -i の出力の Duration(秒)。無ければ None(読み方は parse_ffmpeg_info)"""
    return parse_ffmpeg_info(text)[0]


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
    dur, has_v, has_a, _line = parse_ffmpeg_info(out)
    return dur, has_v, has_a


def no_window_flags(new_group=False, priority=None):
    """子プロセスの creationflags: Windows では黒い窓を出さない(CREATE_NO_WINDOW)。Windows 以外は 0。
    new_group=True は CREATE_NEW_PROCESS_GROUP も足す(Ctrl+C・CTRL_BREAK を親と分ける)。
    priority: None(親と同じ)・"low"(通常より下。書き出し・作り直し・文字起こしなど、画面の操作に CPU を譲る)・"high"(通常より上。録画)・
    "idle"(アイドル。後回しの仕事 = ② の flow/prio.py の表)。それ以外の値は ValueError"""
    if priority is not None and priority not in PRIORITY:
        raise ValueError("priority は low・high・idle のどれかです: %r" % (priority,))
    if os.name != "nt":
        return 0
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if new_group else 0)
    return flags | (getattr(subprocess, PRIORITY[priority], 0) if priority else 0)


def ffprobe_json(ffprobe, args, timeout=60):
    """ffprobe を JSON の出力で 1 回動かして辞書(か配列)にする(窓なし・標準入力なし)。ffprobe = 実行ファイルのパス、args = 足す引数
    (["-show_streams", "-show_format", パス] など。-v error と -of json はここで足す)。
    実行ファイルが無い = FileNotFoundError(OSError)・時間切れ = subprocess.TimeoutExpired・終了コード 0 でない = subprocess.CalledProcessError
    (stderr に標準エラーの文字)・JSON でない = ValueError。呼ぶ側が落ち先(None にする・ToolError にする)を決める"""
    cmd = [ffprobe, "-v", "error", "-of", "json"] + list(args)
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                       creationflags=no_window_flags(new_group=True))
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8", "replace") or "{}")


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
    t0 = time.monotonic()
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
    remember(cmd, proc.returncode, err, reason, t0)
    return RunResult(proc.returncode, b"".join(out), b"".join(err), reason)


def run_progress(cmd, flags=None, cancelled=None, idle_sec=None, on_time=None, popen=None, tail=20, *,
                 timeout=None, split=False, on_line=None, spawn=False, cwd=None, on_start=None):
    """ffmpeg など(yt-dlp も)を 1 回動かし、出力を 1 行ずつ読む。進み具合・取り消し・無出力・時間切れつきで子プロセスを動かす形はこの 1 つ
    (OPT2。exporter._pump・cut2resolve_core._ffmpeg_stream・procs.run_capture・recognize.extract_audio・
    live_excite_worker.measure_levels が使う)。シェルを通さない・標準入力なし・文字は UTF-8(壊れた文字は置き換える。行の区切りは改行と CR)。
    -> (終了コード, 行, 止めた理由)。止めた理由: None | "cancel"(cancelled() が真)| "timeout"(timeout 秒を過ぎた)|
    "idle"(idle_sec 秒なにも出力しなかった。-progress の塊は out_time が進んだときだけ出力に数える = 10-24 この PC の ffmpeg N-126374 の
    aac は無音→音で止まり、同じ時刻の塊を出し続けた)。0.3 秒ごとにこの順で見る。timeout・idle_sec は 0・None なら見ない。
    - 行(2 つ目): split=False(既定)は標準出力と標準エラーを 1 本で読み、進み具合の行と key=value の行(頭の 20 字に = がある)を除いた
      空でない行(前後の空白を除く)。split=True は標準エラーを別に読み、その行をそのまま(行末の空白を除く。空の行も)。
      どちらも最後の tail 行だけ持つ(tail=None は全部)
    - on_time(秒): 進み具合の行(out_time_us= / out_time_ms=。どちらもマイクロ秒)ごとに、出力した長さ(秒)で呼ぶ
    - on_line(行): 進み具合の行のほかの、読んだ 1 行ずつ(前後の空白を除く。空の行も)。split=True なら標準出力の行だけ
    - flags: creationflags(既定 no_window_flags(priority="low") = 窓を出さない・優先度「低」)。popen: 起動を差し替える(既定 subprocess.Popen)
    - spawn=True: procs.spawn で起動する(スタジオの終了の流れ procs.stop_children で止められる一覧に載せる。別グループ)。
      止めるのは procs.terminate(孫ごと)、終わったら一覧から外す。spawn=False は子だけ kill
    - cwd: 子の作業フォルダ。on_start(proc): 起動した直後に呼ぶ(呼ぶ側が外から止めるために覚えるとき)
    起動できなければ OSError をそのまま上げる。on_time・on_line・on_start が上げた例外は、子を止めてから上げる。
    出力が閉じたあと 30 秒で終わらなければ止める"""
    procs = None
    if spawn:
        from . import procs   # procs が tools を読むので、使うときに読む
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE if split else subprocess.STDOUT,
              text=True, encoding="utf-8", errors="replace", creationflags=no_window_flags(priority="low") if flags is None else flags)
    if cwd is not None:
        kw["cwd"] = cwd
    proc = (popen or (procs.spawn if spawn else subprocess.Popen))(cmd, **kw)
    lines = collections.deque(maxlen=tail) if tail is not None else []
    t0 = time.monotonic()
    state = {"last": t0, "why": None, "t": -1}
    done = threading.Event()

    def stop():
        if procs is not None:
            procs.terminate(proc)
        else:
            kill_quiet(proc)

    def watchdog():
        while not done.wait(0.3):
            now = time.monotonic()
            if cancelled is not None and cancelled():
                state["why"] = "cancel"
            elif timeout and now - t0 > timeout:
                state["why"] = "timeout"
            elif idle_sec and now - state["last"] > idle_sec:
                state["why"] = "idle"
            else:
                continue
            stop()
            return

    def drain_err():
        try:
            for raw in proc.stderr:
                state["last"] = time.monotonic()
                lines.append(raw.rstrip())
        except (OSError, ValueError):
            pass
    reader = threading.Thread(target=drain_err, daemon=True) if split else None
    if reader is not None:
        reader.start()
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        if on_start is not None:
            on_start(proc)
        for raw in proc.stdout:
            line = raw.strip()
            m = OUT_TIME.match(line)
            if m:
                us = int(m.group(1))
                if us > state["t"]:   # 進んだときだけ「出力あり」(止まった ffmpeg も -progress の塊は 0.5 秒ごとに同じ時刻で出し続ける)
                    state["t"], state["last"] = us, time.monotonic()
                if on_time is not None:
                    on_time(us / 1e6)
                continue
            if not PROGRESS_KV.match(line):   # -progress の塊のほかの行(frame=・progress=continue など)は「出力あり」に数えない
                state["last"] = time.monotonic()
            if on_line is not None:
                on_line(line)
            if not split and line and "=" not in line[:20]:
                lines.append(line)
        try:
            proc.wait(30)
        except subprocess.TimeoutExpired:
            stop()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
    finally:
        done.set()
        if proc.poll() is None:
            if procs is not None:
                kill_tree(proc)
            else:
                kill_quiet(proc)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        if reader is not None:
            reader.join(5)
        for f in (proc.stdout, proc.stderr):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        if procs is not None:
            procs.forget(proc)
    remember(cmd, proc.returncode, lines, state["why"], t0)
    return proc.returncode, list(lines), state["why"]


def ytdlp_print_cmd(yd, url, template):
    """yt-dlp で URL を 1 回調べる(ダウンロードしない)コマンド。template = --print の書式(項目はタブで区切る)。
    配信の前(予約)は形式が無くてエラーになるが live_status は出してほしいので --ignore-no-formats-error。URL は -- の後(オプションとして読ませない)。
    動かすのは呼ぶ側(run = シェルを通さない・窓を出さない・時間の上限)。配信中か(flow/livesession.probe_live)とアーカイブの状態(flow/live_archive)が使う(OPT1)"""
    return [yd, "--encoding", "utf-8", "--skip-download", "--no-warnings", "--no-playlist", "--ignore-no-formats-error"] + ytdlp_auth_args() + \
        ["--print", template, "--", url]


# ---------- YouTube のログイン(友人の PC。notes:docs/spec/friend.md の 13-13)----------
COOKIES_ENV = "YTT_YTDLP_COOKIES"   # yt-dlp に渡す cookies.txt(Netscape 形式)。友人のアプリ(friendapp/places)とユーザーの PC の入口(app/ytlogin。10-23)が入れる。無ければ今までどおり
COOKIES_RUN = _ytcookies.RUN        # 呼ぶたびの写しを置く、cookies.txt の隣のフォルダ(名前の正は ytt/ytcookies。書き戻しが同じ所を見る)
COOKIES_RUN_KEEP = 24 * 3600        # 写しを消すまでの秒(長い取得の途中の物は消さない)


def ytdlp_auth_args(env=None):
    """yt-dlp に足す ["--cookies", <写し>](COOKIES_ENV のファイルがあるときだけ。無ければ [])。
    写しを渡す: yt-dlp は終わると cookie のファイルに書き戻すので、同時に動く複数の yt-dlp が 1 つのファイルを壊さないように。
    書き戻された写し(YouTube が回した新しい値)は、写す前に ytt/ytcookies.merge_back が 1 つずつ元へ戻す(cookie を長持ちさせる)。
    中身は読まない・ログに出さない(パスだけ)。古い写しはここで消す"""
    env = os.environ if env is None else env
    src = (env.get(COOKIES_ENV) or "").strip()
    try:
        if not src or os.path.getsize(src) <= 0:
            return []
    except OSError:
        return []
    run = os.path.join(os.path.dirname(src), COOKIES_RUN)
    _ytcookies.merge_back(src, env=env)
    try:
        os.makedirs(run, exist_ok=True)
        now = time.time()
        _fsio.prune_older(run, "*", COOKIES_RUN_KEEP, now)
        dst = os.path.join(run, _ytcookies.copy_name(now, os.stat(src).st_mtime_ns))
        shutil.copyfile(src, dst)
    except OSError:
        return ["--cookies", src]   # 写せないとき(空きが無いなど)は元を渡す
    return ["--cookies", dst]


# ---------- 取得の冗長化(10-23。表は保管庫 plan/人の作業なしの候補-1023.md の 6 番)----------
# いつものクライアントで googlevideo に 403・形式が無いと断られたとき、別のクライアント(player_client)で 1 回だけ取り直す。
# tv・mweb は 2026.08.19 の yt-dlp で 360p の 1 本(18)しか出さない(10-23 に本物で確かめた)= 画質の要らない取得(解析の音声)だけに使う。
# 書き出し(映像)には使わない(画質が落ちる。一部が下がる案)。環境変数 YTT_YTDLP_ALT_CLIENT で変える・空で使わない
ALT_CLIENT_ENV = "YTT_YTDLP_ALT_CLIENT"
ALT_CLIENT = "tv,mweb"
ALT_WORDS = ("http error 403", "403 forbidden", "no video formats found", "requested format is not available")   # 小文字で照らす


def ytdlp_alt_args(env=None):
    """別のクライアントで取り直すときに足す引数(使わなければ [])"""
    env = os.environ if env is None else env
    c = env.get(ALT_CLIENT_ENV, ALT_CLIENT).strip()
    return ["--extractor-args", "youtube:player_client=" + c] if c else []


def ytdlp_alt_worth(text):
    """yt-dlp の失敗の文が、別のクライアントで取り直す価値のある物か(403・形式なし。bot 判定・非公開などは違う)"""
    low = str(text or "").lower()
    return any(w in low for w in ALT_WORDS)


def ytdlp_login_at(env=None):
    """YouTube にログインした時刻(ミリ秒)か 0(ログインしていない)。書き戻しで cookie を書き替えてもログインの時刻のまま(ytt/ytcookies)"""
    env = os.environ if env is None else env
    return _ytcookies.login_at((env.get(COOKIES_ENV) or "").strip())


def start_logged(cmd, log_path, cwd, flags, rotate=None):
    """入口が起こす常駐の子プロセス(録画の部品・検出のワーカー)を、標準出力と標準エラーをログに足す形で起動する -> Popen。
    見出しの行(起動の時刻)・PYTHONIOENCODING(無ければ)・PYTHONUNBUFFERED を付ける。rotate(バイト数)を渡すと、超えていたら起動の前に .old.log へ回す。
    flags: creationflags か、その候補の並び(先頭から試し、起動できなければ次。最後もだめなら OSError)。
    子プロセスの起こし方はここ(② の基盤の使い忘れを防ぐ)"""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8:backslashreplace")
    env["PYTHONUNBUFFERED"] = "1"
    if rotate is not None:
        _fsio.rotate(log_path, rotate)
    tries = list(flags) if isinstance(flags, (list, tuple)) else [flags]
    with open(log_path, "ab") as logf:
        logf.write(("\n==== %s ホームから起動 ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
        logf.flush()
        for i, f in enumerate(tries):
            try:
                return subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, creationflags=f)
            except OSError:
                if i == len(tries) - 1:
                    raise


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
