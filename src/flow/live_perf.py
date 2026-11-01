# -*- coding: utf-8 -*-
"""ライブの重さの測り(11-01 ライブを軽くする案の 0。notes:plan/ライブを軽くする案-1101.md)。記録だけ = 何も止めない・変えない。

録画中だけ(録画の部品の子に ffmpeg がいる間)、SAMPLE_SEC ごとに 1 行を live/perf/YYYYMMDD.jsonl に足す:
  {"at": ISO, "sec": 前の測りからの秒, "cpus": 論理 CPU の数, "sysCpu": PC 全体の CPU %, "gpu": {"util": %, "memMB": MB} か None,
   "procs": [{"pid", "ppid", "name", "group": 入口|録画の部品|検出のワーカー, "cpu": PC 全体に対する %(最初の測りは None), "memMB": 作業セット, "gpuMB": NVIDIA の GPU のメモリ(分かった物だけ)}]}
測る相手 = 入口(このプロセス)・録画の部品(running.json の pid)・検出のワーカー(心拍の pid)と、その子孫(ffmpeg・streamlink・yt-dlp・speech など)。
GPU は nvidia-smi が PATH にあるときだけ(窓なし・GPU_TIMEOUT 秒)。KEEP_DAYS より古い日のファイルは消す。
スイッチ: 環境変数 YTT_LIVE_PERF=off で測らない(既定はオン = 次の配信で自動に取る)。Windows 以外では何もしない。
"""
import datetime
import json
import os
import shutil
import subprocess
import time

from ytt import tools

SWITCH_ENV = "YTT_LIVE_PERF"
SAMPLE_SEC = 60.0     # 測る間(秒。見回りの 30 秒ごとに呼ばれて、間が空いたときだけ測る)
KEEP_DAYS = 3         # 残す日数(片付けの基準 = 3 日)
GPU_TIMEOUT = 5       # nvidia-smi の時間切れ(秒)
DIR_NAME = "perf"
REC_CHILD = "ffmpeg"  # 録画の部品の子にこれがいれば録画中


def enabled(env=None):
    return (os.environ if env is None else env).get(SWITCH_ENV, "").strip().lower() not in ("off", "0", "false")


def snapshot():
    """動いているプロセスの一覧 {pid: (ppid, 名前)}(Windows の Toolhelp32。Windows 以外・読めないときは {})"""
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PE))
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    out = {}
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[int(e.th32ProcessID)] = (int(e.th32ParentProcessID), e.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def proc_usage(pid):
    """(CPU の秒 = カーネル + ユーザー, 作業セットの MB) か None(終わった・権限が無い)"""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                           "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        ft = [wintypes.FILETIME() for _ in range(4)]
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        if not k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
            return None
        cpu = sum((f.dwHighDateTime << 32 | f.dwLowDateTime) for f in ft[2:]) / 1e7
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
        mem = c.WorkingSetSize / 1048576.0 if k32.K32GetProcessMemoryInfo(h, ctypes.byref(c), c.cb) else None
        return cpu, mem
    finally:
        k32.CloseHandle(h)


def system_times():
    """(使っていない秒, 全体の秒)(GetSystemTimes。kernel は idle を含む)か None"""
    import ctypes
    from ctypes import wintypes
    ft = [wintypes.FILETIME() for _ in range(3)]
    if not ctypes.windll.kernel32.GetSystemTimes(*[ctypes.byref(f) for f in ft]):
        return None
    idle, kern, user = [(f.dwHighDateTime << 32 | f.dwLowDateTime) / 1e7 for f in ft]
    return idle, kern + user


def gpu_sample(exe=None):
    """NVIDIA の GPU -> ({"util", "memMB"} か None, {pid: MB})。nvidia-smi が無い・読めない = (None, {})"""
    exe = exe or shutil.which("nvidia-smi")
    if not exe:
        return None, {}
    flags = tools.no_window_flags()

    def ask(args):
        try:
            r = subprocess.run([exe] + args + ["--format=csv,noheader,nounits"], capture_output=True, text=True,
                               timeout=GPU_TIMEOUT, creationflags=flags)
        except (OSError, subprocess.SubprocessError):
            return []
        return [[x.strip() for x in ln.split(",")] for ln in (r.stdout or "").splitlines() if ln.strip()] if r.returncode == 0 else []

    gpu = None
    rows = ask(["--query-gpu=utilization.gpu,memory.used"])
    try:
        if rows:
            gpu = {"util": sum(float(r[0]) for r in rows) / len(rows), "memMB": sum(float(r[1]) for r in rows)}
    except (ValueError, IndexError):
        gpu = None
    per = {}
    for r in ask(["--query-compute-apps=pid,used_memory"]):
        try:
            per[int(r[0])] = per.get(int(r[0]), 0.0) + float(r[1])
        except (ValueError, IndexError):
            continue
    return gpu, per


def descendants(procs, root):
    """root とその子孫の pid の集合(root が一覧に無ければ空)"""
    if root not in procs:
        return set()
    kids = {}
    for pid, (ppid, _n) in procs.items():
        if pid != ppid:
            kids.setdefault(ppid, []).append(pid)
    out, todo = set(), [root]
    while todo:
        p = todo.pop()
        if p not in out:
            out.add(p)
            todo.extend(kids.get(p, ()))
    return out


class PerfLog:
    """roots() -> {グループ名: pid}(入口・録画の部品・検出のワーカー。無い物は入れない)。tick() を見回りから呼ぶ"""

    def __init__(self, store_dir, roots, clock=time.time, snap=snapshot, usage=proc_usage, sys_times=system_times, gpu=gpu_sample,
                 sample_sec=SAMPLE_SEC, env=None, log=None):
        self.dir = os.path.join(store_dir, DIR_NAME)
        self.roots, self.clock, self.snap, self.usage, self.sys_times, self.gpu = roots, clock, snap, usage, sys_times, gpu
        self.sample_sec, self.env, self.log = sample_sec, env, log or (lambda m: None)
        self._last = None      # (時刻, {pid: CPU の秒}, (idle, 全体))
        self._pruned = None    # 片付けた日

    def tick(self):
        """測れば書いた行(dict)、測らなければ None"""
        if not enabled(self.env) or (os.name != "nt" and self.snap is snapshot):
            return None
        now = self.clock()
        if self._last is not None and now - self._last[0] < self.sample_sec:
            return None
        roots = self.roots() or {}
        if roots.get("録画の部品") is None:
            self._last = None
            return None
        procs = self.snap()
        groups = {}
        for name, pid in roots.items():
            for p in descendants(procs, pid) if isinstance(pid, int) else ():
                groups.setdefault(p, name)
        rec_pid = roots.get("録画の部品")
        if not any(procs[p][1].lower().startswith(REC_CHILD) for p in descendants(procs, rec_pid) if p != rec_pid):
            self._last = None   # 録画していない = 測らない(次の録画の最初の測りは CPU なし)
            return None
        cpu_now, rows = {}, []
        st = self.sys_times()
        prev = self._last
        sec = now - prev[0] if prev else None
        ncpu = os.cpu_count() or 1
        gpu, per_gpu = self.gpu()
        for pid in sorted(groups):
            u = self.usage(pid)
            if u is None:
                continue
            cpu_now[pid] = u[0]
            cpu = None
            if prev and sec and pid in prev[1]:
                cpu = round(max(0.0, u[0] - prev[1][pid]) / (sec * ncpu) * 100, 2)
            row = {"pid": pid, "ppid": procs[pid][0], "name": procs[pid][1], "group": groups[pid], "cpu": cpu,
                   "memMB": None if u[1] is None else round(u[1], 1)}
            if pid in per_gpu:
                row["gpuMB"] = per_gpu[pid]
            rows.append(row)
        sys_cpu = None
        if st and prev and prev[2] and st[1] > prev[2][1]:
            sys_cpu = round((1 - (st[0] - prev[2][0]) / (st[1] - prev[2][1])) * 100, 1)
        self._last = (now, cpu_now, st)
        doc = {"at": datetime.datetime.fromtimestamp(now).isoformat(timespec="seconds"), "sec": None if sec is None else round(sec, 1),
               "cpus": ncpu, "sysCpu": sys_cpu, "gpu": gpu, "procs": rows}
        self._write(now, doc)
        return doc

    def _write(self, now, doc):
        day = datetime.datetime.fromtimestamp(now).strftime("%Y%m%d")
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(os.path.join(self.dir, day + ".jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")
        except OSError as e:
            self.log("ライブの重さの測りを書けませんでした: %s" % (tools.why(e),))
        if self._pruned != day:
            self._pruned = day
            self.prune(now)

    def prune(self, now=None):
        """KEEP_DAYS より古い日のファイルを消す -> 消した数"""
        edge = datetime.datetime.fromtimestamp((now or self.clock()) - KEEP_DAYS * 86400).strftime("%Y%m%d")
        n = 0
        for name in os.listdir(self.dir) if os.path.isdir(self.dir) else ():
            if name.endswith(".jsonl") and name[:8].isdigit() and name[:8] < edge:
                try:
                    os.remove(os.path.join(self.dir, name))
                    n += 1
                except OSError:
                    pass
        return n
