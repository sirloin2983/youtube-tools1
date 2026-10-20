# -*- coding: utf-8 -*-
"""dev/ の道具が共通で使う小物(標準ライブラリだけ)。guard_hook.py・push_helper.py は単独で動く条件なので、ここを読まない。"""
import os
import shutil
import subprocess
import sys


def console_utf8():
    """標準出力・標準エラーを UTF-8 にし、出せない字は置き換える(cp932 のコンソールで ⚙ などを出して落ちないため)"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def find_node():
    """node(PATH に無ければ Playwright に入っている node.exe)。無ければ None"""
    n = shutil.which("node")
    if n:
        return n
    try:
        import playwright
    except ImportError:
        return None
    p = os.path.join(os.path.dirname(playwright.__file__), "driver", "node.exe" if os.name == "nt" else "node")
    return p if os.path.isfile(p) else None


def read_utf8(path):
    """UTF-8 のテキストをバイトのまま読む(改行を変えない。読めなければ UnicodeDecodeError)"""
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def write_utf8(path, text):
    """UTF-8 のテキストをバイトのまま書く(改行を変えない)"""
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def tracked_files(repo):
    """git が管理しているファイルのパス(リポジトリ直下からの相対・/ 区切り)の一覧"""
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z"], stdout=subprocess.PIPE, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]
