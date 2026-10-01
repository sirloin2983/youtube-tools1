#!/usr/bin/env python3
"""友人用 文字起こし簡易版の起動(lite/start.bat が lite/.venv の Python で呼ぶ)。docs/plan/friend-lite-plan.md の L4。

  1. 更新を確かめる(lite_update.py。取得元は main に固定)。更新したら、新しいコードで起動し直す
  2. 部品を入れる(uv pip install。setup/requirements-lite.txt、NVIDIA の GPU があれば requirements-lite-gpu.txt も)。前と同じなら飛ばす
  3. ffmpeg を確かめる(無ければ winget で入れるかを聞く)
  4. 入口(home/launch.py)を「編集」だけ・簡易版の画面・Edge の窓で起動する。GPU は int8_float16(8GB の GPU に収める)

start.bat は ASCII だけにしたいので、日本語の案内はここで出す。失敗したら黒い画面を閉じずに待つ(読めるように)。
"""
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REQ = os.path.join(ROOT, "setup", "requirements-lite.txt")
REQ_GPU = os.path.join(ROOT, "setup", "requirements-lite-gpu.txt")
LAUNCH_ARGS = ["--only", "transcribe", "--open-path", "/transcribe/lite.html", "--app-window"]
WINGET_LINKS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")


def say(msg=""):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def ask(question):
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes", "はい")
    except EOFError:
        return False


def wait_exit(code):
    if code:
        say("")
        say("うまく起動できませんでした。上の文を読んで、分からなければこの画面の写真を送ってください。")
        try:
            input("Enter を押すと閉じます")
        except EOFError:
            pass
    return code


def has_nvidia(which=shutil.which):
    return bool(which("nvidia-smi"))


def find_uv(which=shutil.which):
    u = which("uv")
    if u:
        return u
    p = os.path.join(os.path.expanduser("~"), ".local", "bin", "uv.exe" if os.name == "nt" else "uv")
    return p if os.path.isfile(p) else None


def req_files(gpu):
    return [REQ] + ([REQ_GPU] if gpu else [])


def req_hash(files):
    h = hashlib.sha256()
    for p in files:
        with open(p, "rb") as f:
            h.update(f.read())
    h.update(sys.version.encode())
    return h.hexdigest()


def marker_path():
    return os.path.join(sys.prefix, ".lite-req-hash")


def install(gpu, run=subprocess.run, uv=None):
    """部品を入れる。前に入れたときと requirements が同じなら何もしない -> True(使える)/ False(失敗)"""
    files = req_files(gpu)
    want = req_hash(files)
    try:
        with open(marker_path(), encoding="ascii") as f:
            if f.read().strip() == want:
                return True
    except OSError:
        pass
    uv = uv or find_uv()
    say("文字起こしの部品を入れています(初めては数分〜十数分かかります%s)…" % ("。GPU 用の部品は約 1GB" if gpu else ""))
    if uv:
        cmd = [uv, "pip", "install", "--python", sys.executable]
    else:
        cmd = [sys.executable, "-m", "pip", "install"]
    for p in files:
        cmd += ["-r", p]
    r = run(cmd)
    if r.returncode != 0:
        say("部品を入れられませんでした。インターネットにつながっているか確かめて、もう一度 start.bat を開いてください。")
        return False
    with open(marker_path(), "w", encoding="ascii") as f:
        f.write(want)
    return True


def ensure_ffmpeg(which=shutil.which, run=subprocess.run, ask_fn=ask):
    """ffmpeg・ffprobe が使えるか。無ければ winget(Windows に入っている公式の入れる道具)で入れるかを聞く"""
    if WINGET_LINKS and os.path.isdir(WINGET_LINKS) and WINGET_LINKS not in os.environ.get("PATH", ""):
        os.environ["PATH"] = WINGET_LINKS + os.pathsep + os.environ.get("PATH", "")
    if which("ffmpeg") and which("ffprobe"):
        return True
    say("動画を読む部品(ffmpeg)が見つかりません。")
    if os.name == "nt" and which("winget") and ask_fn("winget で ffmpeg(Gyan.FFmpeg)を入れますか?"):
        r = run(["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--source", "winget"])
        os.environ["PATH"] = WINGET_LINKS + os.pathsep + os.environ.get("PATH", "")
        if r.returncode == 0 and which("ffmpeg") and which("ffprobe"):
            return True
    say("ffmpeg を入れてから、もう一度 start.bat を開いてください(https://www.gyan.dev/ffmpeg/builds/ など。入れたあと PATH を通す)。")
    return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    no_update = "--no-update" in argv
    argv = [a for a in argv if a != "--no-update"]
    if not no_update:
        sys.path.insert(0, HERE)
        import lite_update
        state, msg = lite_update.run()
        lite_update.say(msg)
        if state == "updated":   # 新しいコードで起動し直す(このプロセスは古いコードを読んだまま)
            return subprocess.call([sys.executable, os.path.abspath(__file__), "--no-update"] + argv)
    gpu = has_nvidia()
    if not install(gpu):
        return wait_exit(1)
    if not ensure_ffmpeg():
        return wait_exit(1)
    os.environ.setdefault("TRANSCRIBE_CUDA_COMPUTE", "int8_float16")   # 3060 の 8GB 版でも収まる(ブリーフの決定)
    if not gpu:
        say("NVIDIA の GPU が見つからないので、CPU で文字起こしします(時間がかかります)。")
    say("簡易版を開きます。この黒い画面は閉じないでください(閉じると止まります)。")
    sys.path.insert(0, os.path.join(ROOT, "home"))
    import launch
    try:
        code = launch.main(LAUNCH_ARGS + argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    return wait_exit(code or 0)


if __name__ == "__main__":
    sys.exit(main())
