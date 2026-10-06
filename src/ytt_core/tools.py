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
