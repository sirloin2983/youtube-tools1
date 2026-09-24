"""外部プログラム(ffmpeg・ffprobe・yt-dlp)の場所。"""
import os
import shutil


def find_tool(name, env_var=None):
    """環境変数 env_var に実在するファイルが入っていればそれ、無ければ PATH から探す(見つからなければ None)。
    環境変数は、PATH を通していない場所の ffmpeg を使うため・テストで偽物に差し替えるため。"""
    env = os.environ.get(env_var) if env_var else None
    if env and os.path.isfile(env):
        return env
    return shutil.which(name)
