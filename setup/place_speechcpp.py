#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""speech.cpp(Haas-ja の主の文字起こしの実行ファイル)を作業データに置く(11-01・保管庫 plan/Haas に替える時の変更の一覧.md の段 1)。

実行ファイルは手元の直しの版(トークンの確率を出す直し = C:\\dev\\speech-cpp\\local-conf-1031.patch。公式の配布には無い)なので取得せず、
作ってあるフォルダ(speech.exe と speech.dll)を写す。作り方は C:\\dev\\speech-cpp\\build.ps1(-Src work -Out conf)。
置き場所: 作業データ(%LOCALAPPDATA%\\youtube-tools\\transcribe)の bin\\speech.cpp-<版>-<直しの名前>\\(speech.exe・speech.dll・build.json)。
写したあと `speech --version` で版を確かめる(版が ytt/txbase.SPEECH_CPP_VERSION と違えば置かない)。

    python setup/place_speechcpp.py [<作ってあるフォルダ>] [--force]
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
sys.path.insert(0, SRC)
from ytt import datadir, tools, txbase  # noqa: E402   版・置き場所の正

DEFAULT_FROM = r"C:\dev\speech-cpp\bin-conf"
FILES = (txbase.SPEECH_EXE, "speech.dll" if os.name == "nt" else "libspeech.so")


def say(msg):
    print(msg, flush=True)


def fail(msg):
    say("")
    say("[失敗] " + msg)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default=DEFAULT_FROM, help="作ってある speech.exe・speech.dll のフォルダ(既定 %s)" % DEFAULT_FROM)
    ap.add_argument("--force", action="store_true", help="置いてあっても置き直す")
    a = ap.parse_args()
    data = datadir.resolve("transcribe")
    dest = txbase.speech_bin_dir(data)
    if os.path.isfile(os.path.join(dest, txbase.SPEECH_EXE)) and not a.force:
        say("speech.cpp はもう置いてあります: %s" % dest)
        say("置き直すときは --force を付けてください")
        return 0
    for f in FILES:
        if not os.path.isfile(os.path.join(a.src, f)):
            fail("%s が見つかりません: %s" % (f, a.src))
    tmp = dest + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    files = {}
    for f in FILES:
        shutil.copy2(os.path.join(a.src, f), tmp)
        files[f] = sha256(os.path.join(tmp, f))
    r = subprocess.run([os.path.join(tmp, txbase.SPEECH_EXE), "--version"], capture_output=True, text=True,
                       env=dict(os.environ, SPEECH_NO_UPDATE_CHECK="1"), creationflags=tools.no_window_flags())
    if r.returncode != 0 or txbase.SPEECH_CPP_VERSION not in (r.stdout + r.stderr):
        shutil.rmtree(tmp, ignore_errors=True)
        fail("写した speech.exe の版が %s ではありませんでした: %s" % (txbase.SPEECH_CPP_VERSION, (r.stdout + r.stderr).strip()[:200]))
    with open(os.path.join(tmp, "build.json"), "w", encoding="utf-8") as fp:
        json.dump({"version": txbase.SPEECH_CPP_VERSION, "flavor": txbase.SPEECH_CPP_FLAVOR, "from": a.src,
                   "placedAt": datetime.datetime.now().isoformat(timespec="seconds"), "files": files}, fp, ensure_ascii=False, indent=1)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    say("置きました: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
