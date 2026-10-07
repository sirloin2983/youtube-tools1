"""外部プログラム(ffmpeg・ffprobe・yt-dlp)の場所と、子プロセスを動かすときの小道具。"""
import os
import shutil
import subprocess


def find_tool(name, env_var=None):
    """環境変数 env_var に実在するファイルが入っていればそれ、無ければ PATH から探す(見つからなければ None)。
    環境変数は、PATH を通していない場所の ffmpeg を使うため・テストで偽物に差し替えるため。"""
    env = os.environ.get(env_var) if env_var else None
    if env and os.path.isfile(env):
        return env
    return shutil.which(name)


def no_window_flags(new_group=False):
    """子プロセスの creationflags: Windows では黒い窓を出さない(CREATE_NO_WINDOW)。Windows 以外は 0。
    new_group=True は CREATE_NEW_PROCESS_GROUP も足す(Ctrl+C・CTRL_BREAK を親と分ける)"""
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if new_group else 0)


def kill_quiet(proc):
    """子プロセスがまだ動いていれば止める(終わっていれば何もしない。止められなくても上げない)"""
    if proc.poll() is not None:
        return
    try:
        proc.kill()
    except OSError:
        pass


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
