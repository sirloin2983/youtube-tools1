#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""以前の場所(各ツールのフォルダの中)に残った作業データを片付ける(段階4。docs/data-location.md)。

作業データは 2026-09-26 から %LOCALAPPDATA%\\youtube-tools\\<ツールID>\\ にある。最初の起動でコピーし、元は残してある。
このスクリプトは、新しい場所で使えることを確かめた後に、元の方を**ごみ箱へ**移す(Windows。間違えても戻せる)。

消す前に確かめること(1つでも合わなければ、その項目は消さない):
  - 新しい場所にそのツールの .migrated.json があり、「どこから写したか」がこのリポジトリのフォルダである
  - 写したデータ(data.json・transcripts など)は、.migrated.json の写した一覧にあり、新しい場所にも同じ名前がある
  - ツールが動いていない(.runtime の記録に応答するツールがあれば、何もしないで終わる)
写さない一時的なもの(ログ・作業用の work・起動中の印)は、新しい場所が使われていれば消してよい。

使い方(リポジトリ直下):
  python tools/cleanup_legacy_data.py            消すものの一覧を見せ、y を押したらごみ箱へ
  python tools/cleanup_legacy_data.py --dry-run  一覧を見せるだけ
  (tools\\cleanup_legacy_data.bat をダブルクリックでも同じ)
"""
import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)
from ytt_core import datadir, runtime  # noqa: E402

# (ツールID, 以前の場所, 写したデータ(各 serve.py の DATA_ITEMS と同じ), 写さない一時的なもの)
TOOLS = (
    ("studio", "clip-studio",
     ("data.json", "data.json.bak", "feedback.jsonl", "feedback.jsonl.old", "registry.json", "config.json",
      "settings.json", "settings-ui.json", "cache", "archive"),
     ("studio.log", "studio.old.log", "studio-errors.log", "studio-errors.old.log", "studio.crash.log", "studio.crash.old.log", "work")),
    ("transcribe", "transcribe-tool",
     ("transcripts", "dataset", "evals", "models", "settings.json", "learn-feedback.json", "eval-baselines.json"),
     ("serve.log", "serve.log.1", "serve.log.2", "serve.crash.log", "worker.log", "worker.log.1", ".running.json")),
    ("cut2resolve", "cut2resolve", (), ("work",)),
    ("app", "app", (), ("logs",)),
)


def _size(path):
    try:
        return datadir._size(path)[0]
    except OSError:
        return 0


def plan(root=ROOT, env=None):
    """-> [{"tool", "path", "name", "bytes", "ok", "reason"}]。ok=False のものは消さない"""
    data_root = datadir.data_root(env)
    out = []
    for tool, folder, data_items, temp_items in TOOLS:
        legacy = os.path.join(root, folder)
        present = [(n, True) for n in data_items if os.path.lexists(os.path.join(legacy, n))] + \
                  [(n, False) for n in temp_items if os.path.lexists(os.path.join(legacy, n))]
        if not present:
            continue
        new = os.path.join(data_root, tool) if data_root else None
        marker = datadir.read_marker(new) if new else None
        same_src = bool(marker) and os.path.normcase(os.path.abspath(str(marker.get("from", "")))) == os.path.normcase(os.path.abspath(legacy))
        for name, is_data in present:
            item = {"tool": tool, "path": os.path.join(legacy, name), "name": name, "bytes": _size(os.path.join(legacy, name)),
                    "ok": False, "reason": ""}
            if data_root is None:
                item["reason"] = "YTT_DATA_DIR=inplace(以前の場所を使う設定)のため消さない"
            elif not is_data and os.path.isdir(new) and (not marker or same_src):
                item["ok"] = True   # 一時的なもの(ログなど)は、新しい場所が使われていれば消してよい(入口は .migrated.json を作らない)
            elif not marker:
                item["reason"] = "新しい場所に移し済みの印(.migrated.json)が無い"
            elif not same_src:
                item["reason"] = "移し済みの印が別のフォルダから写したものになっている(%s)" % marker.get("from")
            elif is_data and name not in (marker.get("items") or []):
                item["reason"] = "移したときの一覧に無い(移した後に以前の場所で作られた?)"
            elif is_data and not os.path.lexists(os.path.join(new, name)):
                item["reason"] = "新しい場所に同じ名前が無い"
            else:
                item["ok"] = True
            out.append(item)
    return out


def running_tools(root=ROOT):
    """.runtime の記録に応答するツール(動いているもの)の ID"""
    rdir = runtime.runtime_dir(os.path.join(root, "app"))
    live = []
    for tid, app in runtime.TOOL_APPS.items():
        info = runtime.read_runtime(rdir, tid)
        if info and runtime.ping_app(info["port"], 0.5, info["path"]) == app:
            live.append(tid)
    return live


def to_recycle_bin(path):
    """Windows のごみ箱へ(戻せる)。ごみ箱に入らないほど大きいと、Windows が確認を出す"""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_WANTNUKEWARNING = 3, 0x4, 0x10, 0x40, 0x4000
    op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_WANTNUKEWARNING, False, None, None)
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r != 0 or op.fAnyOperationsAborted:
        raise OSError("ごみ箱へ移せませんでした(コード %s)" % r)


def remove(path, trash_dir=None):
    """Windows はごみ箱へ。それ以外(テスト)は trash_dir へ移す"""
    if os.name == "nt" and trash_dir is None:
        to_recycle_bin(path)
        return
    trash_dir = trash_dir or os.path.join(os.path.expanduser("~"), ".local", "share", "Trash", "files")
    os.makedirs(trash_dir, exist_ok=True)
    dst = os.path.join(trash_dir, os.path.basename(path))
    n = 1
    while os.path.lexists(dst):
        n += 1
        dst = os.path.join(trash_dir, "%s.%d" % (os.path.basename(path), n))
    shutil.move(path, dst)


def main(argv=None, root=ROOT, env=None, ask=input, trash_dir=None):
    ap = argparse.ArgumentParser(description="以前の場所に残った作業データを、確かめてからごみ箱へ移す")
    ap.add_argument("--dry-run", action="store_true", help="一覧を見せるだけ")
    ap.add_argument("--yes", action="store_true", help="確認せずに進める")
    a = ap.parse_args(argv)
    live = running_tools(root)
    if live:
        print("動いているツールがあります(%s)。入口の「すべて終了」で止めてから、もう一度実行してください。" % "、".join(live))
        return 2
    items = plan(root, env)
    if not items:
        print("以前の場所に残っている作業データはありません。")
        return 0
    print("作業データの置き場所: %s" % datadir.data_root(env))
    ok = [i for i in items if i["ok"]]
    for i in items:
        print("  %s %-12s %8.1f MB  %s%s" % ("消す  " if i["ok"] else "残す  ", i["tool"], i["bytes"] / 2**20,
                                           os.path.relpath(i["path"], root), "" if i["ok"] else "(" + i["reason"] + ")"))
    print("消すもの: %d 件・約 %.1f MB(ごみ箱へ移します。戻すときはごみ箱から「元に戻す」)" % (len(ok), sum(i["bytes"] for i in ok) / 2**20))
    if not ok or a.dry_run:
        return 0
    if not a.yes and ask("ごみ箱へ移してよければ y を押して Enter: ").strip().lower() != "y":
        print("何もしませんでした。")
        return 1
    failed = 0
    for i in ok:
        try:
            remove(i["path"], trash_dir)
            print("  ごみ箱へ: %s" % os.path.relpath(i["path"], root))
        except OSError as e:
            failed += 1
            print("  失敗: %s(%s)" % (os.path.relpath(i["path"], root), e))
    print("終わりました。" if not failed else "%d 件は移せませんでした(ファイルを開いているプログラムを閉じて、もう一度実行してください)。" % failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
