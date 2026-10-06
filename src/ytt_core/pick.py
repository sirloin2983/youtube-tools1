"""PC の標準の「ファイルを選ぶ」「フォルダを選ぶ」の窓(画面の「参照…」。2026-10-01)。

ブラウザからはファイルの実際のパスを知れないので、ローカルのサーバーが窓を開いて、選んだパスを返す。
窓は別のプロセス(同じ Python の tkinter)で開く: サーバーのスレッドで Tk を動かすと、ほかの要求のスレッドと
取り合って固まることがあるため。窓は一度に1つだけ(2つ目は PickBusy)。ファイルの中身は読まない(パスを返すだけ)。
"""
import json
import os
import subprocess
import sys
import threading

from . import fsio as _fsio, tools as _tools

TIMEOUT = 600   # 窓を開いたまま放っておかれたら、この秒数で閉じる

_lock = threading.Lock()

_SCRIPT = r"""
import json, sys
a = json.loads(sys.argv[1])
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)   # ブラウザの窓の後ろに隠れないように
root.update()
kw = {"parent": root, "title": a["title"]}
if a.get("initial"):
    kw["initialdir"] = a["initial"]
if a["kind"] == "dir":
    p = filedialog.askdirectory(mustexist=True, **kw)
else:
    p = filedialog.askopenfilename(filetypes=[tuple(t) for t in a["types"]], **kw)
root.destroy()
sys.stdout.write(json.dumps({"path": p or ""}))
"""


class PickError(Exception):
    """窓を開けなかった(tkinter が無い・途中で落ちた)"""


class PickBusy(Exception):
    """すでに窓が開いている"""


def initial_dir(hint):
    """窓を最初に開くフォルダ。hint(元のパスなど)から、存在するいちばん近いフォルダ。
    ネットワーク上のパスには触らない(存在を確かめるだけで資格情報を送るため)。見つからなければ ""(窓の既定)"""
    s = str(hint or "").strip().strip('"')
    if not s or _fsio.is_network_path(s) or not os.path.isabs(s):
        return ""
    p = os.path.abspath(s)
    for _ in range(40):
        try:
            if os.path.isdir(p):
                return p
        except (OSError, ValueError):
            return ""
        up = os.path.dirname(p)
        if up == p:
            return ""
        p = up
    return ""


def _types(exts):
    exts = sorted({e.lower() for e in exts or () if isinstance(e, str) and e.startswith(".")})
    pat = " ".join("*" + e for e in exts)
    return ([["動画・音声", pat]] if pat else []) + [["すべてのファイル", "*.*"]]


def pick(kind="file", title="", hint="", exts=()):
    """窓を開いて、選んだパスを返す(やめたら "")。kind = "file" | "dir"。exts = 選べる拡張子(".mp4" など)"""
    kind = "dir" if kind == "dir" else "file"
    if not _lock.acquire(blocking=False):
        raise PickBusy("ファイルを選ぶ窓がすでに開いています(タスクバーを確認してください)")
    try:
        arg = json.dumps({"kind": kind, "title": str(title or ("フォルダを選ぶ" if kind == "dir" else "ファイルを選ぶ"))[:100],
                          "initial": initial_dir(hint), "types": _types(exts)}, ensure_ascii=False)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            r = subprocess.run([sys.executable, "-c", _SCRIPT, arg], capture_output=True, timeout=TIMEOUT,
                               env=env, creationflags=_tools.no_window_flags())
        except subprocess.TimeoutExpired:
            return ""
        except OSError as e:
            raise PickError("ファイルを選ぶ窓を開けませんでした(%s)" % e)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise PickError("ファイルを選ぶ窓を開けませんでした(%s)" % (err[-1][:200] if err else "returncode %d" % r.returncode))
        try:
            p = json.loads(r.stdout.decode("utf-8", "replace") or "{}").get("path") or ""
        except ValueError:
            raise PickError("ファイルを選ぶ窓の結果を読めませんでした")
        return os.path.normpath(p) if p else ""
    finally:
        _lock.release()
