#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""whisper.cpp を AMD などの GPU(Vulkan)用に、この PC で作る(精度改善の計画 段2-2。build-whisper-vulkan.bat から呼ぶ)。

公式の配布には Windows の Vulkan 版が無いので、公式のソース(github.com/ggml-org/whisper.cpp)を決まった版で取り、
そのコミットが決まったもの(src/editor/tx_engines.py の WHISPER_CPP)と一致するときだけ作る(2026-10-02 ユーザー決定)。

要るもの: Git・Visual Studio 2022(C++ によるデスクトップ開発。CMake はその中のものを使う)・Vulkan SDK(LunarG。winget install KhronosGroup.VulkanSDK)。
作った物: 作業データ(%LOCALAPPDATA%\\youtube-tools\\transcribe)の bin\\whisper.cpp-<版>-vulkan\\(whisper-cli.exe と DLL・build.json)。
ソースと途中のファイルは短い場所 C:\\ytt-build\\ に置き、できたら消す(MSBuild は 260 文字を超えるパスで失敗する。
シェーダーを作る部品が入れ子のプロジェクトで約 190 文字を足すので、作業データの下(約 90 文字)では作れなかった。2026-10-02)。

    python setup/build_whisper_vulkan.py [--force]
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")   # ツールと ytt_core の置き場所
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "editor"))
import tx_engines as E  # noqa: E402   版・コミット・置き場所の正(ネイティブの部品は読まない)
from ytt import datadir  # noqa: E402


def say(msg):
    print(msg, flush=True)


def fail(msg):
    say("")
    say("[失敗] " + msg)
    sys.exit(1)


def run(cmd, cwd=None, env=None):
    say("> " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode != 0:
        fail("コマンドが失敗しました(終了コード %d)" % r.returncode)


def find_cmake():
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        fail("Visual Studio 2022 が見つかりません(「C++ によるデスクトップ開発」を入れてください)")
    out = subprocess.run([vswhere, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                         capture_output=True, text=True).stdout.strip().splitlines()
    if not out:
        fail("Visual Studio の C++ の部品が見つかりません(Visual Studio Installer で「C++ によるデスクトップ開発」を入れてください)")
    cm = os.path.join(out[0], "Common7", "IDE", "CommonExtensions", "Microsoft", "CMake", "CMake", "bin", "cmake.exe")
    if os.path.isfile(cm):
        return cm
    cm = shutil.which("cmake")
    if not cm:
        fail("CMake が見つかりません(Visual Studio Installer で「Windows 用 C++ CMake ツール」を入れてください)")
    return cm


def find_vulkan_sdk():
    """VULKAN_SDK(入れたあとに開いた画面なら入っている)→ 既定の場所 C:\\VulkanSDK\\<版> の新しいもの。glslc.exe(シェーダーを作る)があること"""
    cands = [os.environ.get("VULKAN_SDK") or ""] + sorted(glob.glob(r"C:\VulkanSDK\*"), reverse=True)
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "Bin", "glslc.exe")):
            return d
    fail("Vulkan SDK が見つかりません。次を実行してから、新しい画面でもう一度このファイルを実行してください:\n"
         "    winget install --id KhronosGroup.VulkanSDK -e")


def rmtree_all(path):
    """読み取り専用のファイル(git の pack など)も消す"""
    import stat

    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="作ってあっても作り直す")
    a = ap.parse_args()
    if os.name != "nt":
        fail("このスクリプトは Windows 用です")
    data = datadir.resolve("transcribe")
    dest = E.wcpp_bin_dir(data)
    ok, _why = E.WhisperCpp.ready(data)
    if ok and not a.force:
        say("whisper.cpp %s(Vulkan)はもう作ってあります: %s" % (E.WHISPER_CPP["version"], dest))
        say("作り直すときは --force を付けてください")
        return 0
    git = shutil.which("git") or fail("Git が見つかりません(https://git-scm.com/)")
    cmake = find_cmake()
    sdk = find_vulkan_sdk()
    say("Vulkan SDK: %s" % sdk)
    say("CMake: %s" % cmake)
    ver, commit = E.WHISPER_CPP["version"], E.WHISPER_CPP["commit"]
    work = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "ytt-build")
    src = os.path.join(work, "whisper.cpp-%s" % ver)
    shutil.rmtree(os.path.join(data, "build"), ignore_errors=True)   # 以前の置き場所(パスが長くて作れなかった)
    if os.path.isdir(src):
        head = subprocess.run([git, "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head != commit:
            say("取ってあるソースのコミットが違うので取り直します(%s)" % head[:12])
            rmtree_all(src)
    if not os.path.isdir(src):
        os.makedirs(os.path.dirname(src), exist_ok=True)
        run([git, "-c", "advice.detachedHead=false", "clone", "--depth", "1", "--branch", ver, E.WHISPER_CPP["repo"], src])
    head = subprocess.run([git, "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != commit:   # 版の札が付け替えられていたら作らない(決めたコミットのソースだけを使う)
        rmtree_all(src)
        fail("取ったソースのコミットが想定と違います(%s ≠ %s)。作るのをやめました" % (head[:12], commit[:12]))
    say("ソース: %s(%s %s)" % (src, ver, commit[:12]))
    build = os.path.join(src, "b")
    env = dict(os.environ, VULKAN_SDK=sdk)
    run([cmake, "-S", src, "-B", build, "-G", "Visual Studio 17 2022", "-A", "x64", "-DGGML_VULKAN=ON", "-DWHISPER_BUILD_TESTS=OFF",
         "-DWHISPER_BUILD_EXAMPLES=ON", "-DWHISPER_SDL2=OFF"], env=env)
    run([cmake, "--build", build, "--config", "Release", "--target", "whisper-cli", "-j"], env=env)
    out = os.path.join(build, "bin", "Release")
    exe = os.path.join(out, E.WCPP_EXE)
    if not os.path.isfile(exe):
        fail("作った whisper-cli.exe が見つかりません: %s" % exe)
    tmp = dest + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    files = {}
    for p in [exe] + sorted(glob.glob(os.path.join(out, "*.dll"))):
        shutil.copy2(p, tmp)
        files[os.path.basename(p)] = sha256(p)
    r = subprocess.run([os.path.join(tmp, E.WCPP_EXE), "--help"], capture_output=True, text=True)
    if r.returncode != 0 or "--vad" not in (r.stdout + r.stderr):
        fail("作った whisper-cli.exe が動きませんでした(--help)")
    with open(os.path.join(tmp, "build.json"), "w", encoding="utf-8") as f:
        json.dump({"version": ver, "commit": commit, "backend": "vulkan", "vulkanSdk": os.path.basename(sdk),
                   "builtAt": datetime.datetime.now().isoformat(timespec="seconds"), "files": files}, f, ensure_ascii=False, indent=1)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    rmtree_all(work)   # ソースと途中のファイル(数百 MB)は要らない
    say("")
    say("できました: %s" % dest)
    say("「編集」で whisper.cpp を使うには、入口を「すべて終了」してから start.bat で起動し直してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
