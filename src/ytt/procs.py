"""外部コマンドの子プロセスの管理(役割で組み直す RS3-4。2026-10-10 にスタジオの common.py から移した。標準ライブラリだけ)。

起動した子を覚えておき、中止・時間切れ・終了の流れで孫ごと止める。使う所: スタジオの解析(pipeline の analyze)・書き出し(pipeline/export/exporter)・
メディア情報(ytt/mediainfo)・スタジオの serve の終了の流れ(stop_children)。
- `spawn(cmd, **kw)`: 別のプロセスグループ・窓なしで起動して覚える。終わりを見届けたら `forget`。動いている子は `children()`
- `stop_children(wait)`: 終了の流れで、動いている子を孫ごと止める
- `run_short(cmd, timeout)`: すぐ終わる情報の読み取り(subprocess.run の代わり。spawn を通す)
- `run_capture(job, cmd, …)`: 1 行ずつ読みながら実行し、job の cancel・時間切れ・出力が止まったときに止める(中止は errors.Cancelled・出力なしは ApiError("timeout"))
- `terminate`(止める依頼。待たない)・`hard_kill`(孫ごと強制終了)・`idle_message`(出力が止まったときの文)
- `pid_alive(pid)`: 自分の子でないプロセスが動いているか(flow/placement の .flow.lock の取り残しの見分け。RS6 b-B0)
テストは `common.spawn` などの旧い名前でも読み書きできる(スタジオの common.py の転送。RS5 で消す)。読む側は `procs.名前` を呼ぶたびに読む。
"""
import os
import signal
import subprocess
import threading
import time

from . import errors, tools as _tools

KILL_GRACE = 3.0   # SIGTERM のあと、この秒数で終わらなければ SIGKILL
STOP_WAIT = 3.0    # 終了の流れ(stop_children)で、止める依頼のあと子プロセスが終わるのを待つ秒数。過ぎたら強制終了
_children = set()  # spawn で起動して、まだ見届けていない子プロセス(終了の流れで止めるため。2026-09-30)
_children_lock = threading.Lock()


def spawn(cmd, **kw):
    """外部コマンドを起動する。POSIX では新しいセッション(=プロセスグループ)にして、孫プロセスごと止められるようにする。
    起動した子は _children に覚える(終わりを見届けた側が forget で外す。外し忘れても children() が終わったものを除く)。
    Windows では別のプロセスグループ・窓なしなので、親が終わっても子は残る → 終了の流れで stop_children() を呼ぶ"""
    if os.name != "nt":
        kw["start_new_session"] = True
    else:   # 別のプロセスグループにして、黒い画面への Ctrl+C / Ctrl+Break を子に流さない・子の終了で画面が巻き込まれないようにする
        kw["creationflags"] = kw.get("creationflags", 0) | _tools.no_window_flags(new_group=True)
    proc = subprocess.Popen(cmd, **kw)
    with _children_lock:
        _children.add(proc)
    return proc


def forget(proc):
    """終わりを見届けた子プロセスを一覧から外す。"""
    with _children_lock:
        _children.discard(proc)


def children():
    """まだ動いている子プロセス(終わったものは一覧から外す)。"""
    with _children_lock:
        for proc in [x for x in _children if x.poll() is not None]:
            _children.discard(proc)
        return list(_children)


def stop_children(wait=None):
    """動いている子プロセスを孫ごと止める(終了の流れ用)。止めた数を返す。子が無ければ待たずにすぐ戻る。
    止め方: POSIX は SIGTERM(穏やかに)→ wait 秒のうちに終わらなければ SIGKILL。
    Windows は窓なし・別グループの子に穏やかな合図(Ctrl+Break・WM_CLOSE)が届かないので、taskkill /T /F で孫ごと止める
    (書き出しは一時の名前に書いているので、途中で止めても完成品と同じ名前の壊れたファイルは残らない)"""
    live = children()
    if not live:
        return 0
    wait = STOP_WAIT if wait is None else wait
    for proc in live:
        terminate(proc, grace=wait)
    deadline = time.time() + wait
    for proc in live:
        try:
            proc.wait(max(0.05, deadline - time.time()))
        except subprocess.TimeoutExpired:
            pass
    for proc in live:
        if proc.poll() is None:
            hard_kill(proc)
            try:
                proc.wait(2)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is not None:
            forget(proc)
    return len(live)


def run_short(cmd, timeout, merge_stderr=False):
    """すぐ終わる外部コマンド(情報を読むだけ: ffmpeg -i・ffprobe・yt-dlp -g)。subprocess.run の代わりに spawn を通す
    (終了の流れで止められる・窓を出さない)。時間切れは孫ごと止めて subprocess.TimeoutExpired。戻り値は CompletedProcess"""
    proc = spawn(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
                 text=True, encoding="utf-8", errors="replace")
    try:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            hard_kill(proc)
            try:
                proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, ValueError, OSError):
                pass
            raise
    finally:
        if proc.poll() is None:
            hard_kill(proc)
        forget(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, out or "", err or "")


def hard_kill(proc):
    """孫ごと強制終了する(ytt.tools.kill_tree: Windows は System32 の taskkill /T /F・ほかはプロセスグループに SIGKILL)。
    名前はテストが呼ぶので残す"""
    _tools.kill_tree(proc)


def terminate(proc, grace=None):
    """止める依頼(待たない): 子プロセスごと SIGTERM(Windows は窓なし・別グループの子に穏やかな合図が届かないので kill_tree)。
    猶予のあと残っていれば SIGKILL。"""
    if not proc or proc.poll() is not None:
        return
    if os.name == "nt":
        _tools.kill_tree(proc)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)   # グループID = 起動したプロセスのPID
    except OSError:
        try:
            proc.send_signal(signal.SIGTERM)
        except (OSError, ValueError):
            pass

    def escalate():
        time.sleep(KILL_GRACE if grace is None else grace)
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # 残っていれば(孫プロセスを含む)強制終了。なければ何もしない
        except OSError:
            pass
    threading.Thread(target=escalate, daemon=True).start()


def pid_alive(pid):
    """プロセス pid が動いているか(自分の子でなくてよい)。pid が正の整数でなければ False。権限が無い・調べられないときは True
    (動いているほうに倒す)。Windows では os.kill(pid, 0) がプロセスを終わらせるので使わない(OpenProcess と待ちの 0 秒で見る)"""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = k32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 5   # 5 = 権限が無い(動いている)。87 などは無い
        try:
            return k32.WaitForSingleObject(handle, 0) == 0x102   # WAIT_TIMEOUT = まだ終わっていない
        finally:
            k32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return True


def idle_message(what, sec):
    """出力が止まって中止したときの文(sec が 60 以上なら分で)"""
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
        forget(p_)
    if job["cancel"]:
        raise errors.Cancelled()
    if idle[0]:
        raise errors.ApiError("timeout", idle_message(what, idle_timeout), 504)
    return p_.returncode, err
