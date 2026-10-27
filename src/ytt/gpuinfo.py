"""この PC の GPU の名前と VRAM を調べる(F1 F0-2。資料の git:before-1028-cleanup:docs/design/f1-build.md の 2 の F0-2・3 の (f1b))。標準ライブラリと ytt だけ。

info() -> {"name", "vramGB"(数か None), "vendor"(nvidia・amd・intel・other)} か None(GPU が見つからない・調べに失敗)。
調べる順:
  1. nvidia-smi --query-gpu=name,memory.total(NVIDIA。PATH にあるときだけ)
  2. Windows のレジストリの表示アダプタの組(HardwareInformation.qwMemorySize = 64 bit の VRAM。子プロセスなし)
  3. PowerShell の Get-CimInstance Win32_VideoController(名前だけ確か。AdapterRAM は 32 bit で 4GB の頭打ち = 4GB 以上らしい値は None)
子プロセスは ytt/procs.run_short(窓を出さない = CREATE_NO_WINDOW・時間切れで止める)。結果はプロセスの中で覚える(refresh=True で調べ直す)。
GPU が複数あるときは VRAM の大きい物(分からない物は後ろ)。VRAM の GB は 2^30 で割って小数 1 桁。
読む所: flow/machine の llmModel の既定(VRAM で決める)・② の状態(F0-1 の status の machine.gpu)。
"""
import json
import os
import shutil
import subprocess
import threading

from . import procs

TIMEOUT = 8                     # 子プロセス 1 本の上限(秒)
ADAPTER_RAM_CAP = 0xFFF00000    # Win32_VideoController.AdapterRAM の頭打ちの値(4GB - 1MB)。これ以上は本当の値が分からない
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_SKIP = ("microsoft basic", "remote display", "parsec", "virtual")   # 本物の GPU でない表示アダプタ
_cache = {}
_lock = threading.Lock()


def vendor_of(name, compat=""):
    s = ("%s %s" % (name or "", compat or "")).lower()
    for key, v in (("nvidia", "nvidia"), ("geforce", "nvidia"), ("quadro", "nvidia"), ("amd", "amd"), ("radeon", "amd"),
                   ("advanced micro devices", "amd"), ("intel", "intel")):
        if key in s:
            return v
    return "other"


def gb(nbytes):
    """バイト数 -> GB(2^30。小数 1 桁)。0 以下・数でない物は None"""
    try:
        n = float(nbytes)
    except (TypeError, ValueError):
        return None
    return round(n / (1 << 30), 1) if n > 0 else None


def parse_nvidia_smi(text):
    """nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits の出力(1 行 1 枚。MiB)-> [{name, vramGB, vendor}]"""
    out = []
    for line in str(text or "").splitlines():
        name, _, mem = line.rpartition(",")
        name = name.strip()
        if not name:
            continue
        try:
            vram = round(float(mem.strip()) / 1024, 1)
        except ValueError:
            vram = None
        out.append({"name": name, "vramGB": vram, "vendor": "nvidia"})
    return out


def parse_cim(text):
    """ConvertTo-Json の Win32_VideoController(Name・AdapterRAM・AdapterCompatibility。1 枚なら dict・複数なら list)-> [{name, vramGB, vendor}]。
    AdapterRAM が頭打ち(4GB 近く)・0・無いときの VRAM は None"""
    try:
        d = json.loads(text or "null")
    except ValueError:
        return []
    out = []
    for x in d if isinstance(d, list) else [d] if isinstance(d, dict) else []:
        name = str(x.get("Name") or "").strip() if isinstance(x, dict) else ""
        if not name:
            continue
        ram = x.get("AdapterRAM")
        vram = gb(ram) if isinstance(ram, (int, float)) and not isinstance(ram, bool) and 0 < ram < ADAPTER_RAM_CAP else None
        out.append({"name": name, "vramGB": vram, "vendor": vendor_of(name, x.get("AdapterCompatibility"))})
    return out


def pick(gpus):
    """本物の GPU のうち VRAM の大きい物(VRAM の分からない物は後ろ。同じなら先の物)-> 1 枚か None"""
    real = [g for g in gpus if g.get("name") and not any(s in g["name"].lower() for s in _SKIP)]
    if not real:
        return None
    best = max(enumerate(real), key=lambda iv: (iv[1].get("vramGB") is not None, iv[1].get("vramGB") or 0, -iv[0]))
    return dict(best[1])


def _run(cmd):
    try:
        r = procs.run_short(cmd, TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def from_nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    return parse_nvidia_smi(_run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]))


def from_registry():
    """Windows のレジストリの表示アダプタ(DriverDesc・HardwareInformation.qwMemorySize)-> [{name, vramGB, vendor}]。Windows 以外・読めなければ []"""
    if os.name != "nt":
        return []
    try:
        import winreg
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS)
    except OSError:
        return []
    out = []
    with root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, sub) as k:
                    name = str(winreg.QueryValueEx(k, "DriverDesc")[0] or "").strip()
                    try:
                        mem = winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0]
                    except OSError:
                        mem = None
            except OSError:
                continue
            if name:
                out.append({"name": name, "vramGB": gb(mem) if isinstance(mem, int) else None, "vendor": vendor_of(name)})
    return out


def from_cim():
    if os.name != "nt":
        return []
    ps = shutil.which("powershell") or "powershell"
    return parse_cim(_run([ps, "-NoProfile", "-NonInteractive", "-Command",
                           "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,AdapterCompatibility | ConvertTo-Json -Compress"]))


def probe():
    """調べる(覚えない)-> {name, vramGB, vendor} か None。nvidia-smi → レジストリ → CIM の順で、VRAM の分かった物が出た所で止める"""
    first = None
    for source in (from_nvidia_smi, from_registry, from_cim):
        try:
            g = pick(source())
        except Exception:   # noqa: BLE001  (調べは補助。何が起きても次の調べ方へ)
            g = None
        if g and g.get("vramGB") is not None:
            return g
        first = first or g
    return first


def info(refresh=False):
    """覚えた結果(初回か refresh=True のときだけ調べる)-> {name, vramGB, vendor} か None"""
    with _lock:
        if refresh or "v" not in _cache:
            _cache["v"] = probe()
        v = _cache["v"]
    return dict(v) if v else None
