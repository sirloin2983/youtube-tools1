"""ユーザーの PC の YouTube のログイン(10-23 ユーザー「ログインできる形にしといて」)。友人のアプリと同じ作り(notes:docs/spec/friend.md の 13-13)。

- 置き場所: 入口の作業データの secrets\\youtube-cookies.txt(%LOCALAPPDATA%\\youtube-tools\\app\\secrets。リポジトリと Dropbox の外)。
  入口は起動のとき環境変数 YTT_YTDLP_COOKIES にこのパスを入れる(apply_env)= 入口が起こすツール(スタジオ・編集・まとめて実行・ライブ)の
  yt-dlp に ytt/tools.ytdlp_auth_args が写しで渡す。ファイルが無ければ(ログインしていない)今までどおり何も渡さない
- ログイン: 友人のアプリの小窓(friend-apps/launcher の FriendApp.exe --yt-login <置き場所>。WebView2 で Google にログインして cookie を書く)を起こす。
  exe は friend-apps/launcher/build.bat で作る(配る zip を作るときにも作られる)
- 状態: none(ログインしていない)・ok(ログインした日)・expired(yt-dlp の書き戻しでログインの cookie が消えた = ytt/ytcookies の lostAt)
- cookie の値は読まない・ログに出さない(パスと時刻だけ)
"""
import os
import subprocess
import threading

from ytt import tools as _tools, ytcookies as _ytcookies

SECRETS = "secrets"
COOKIES_NAME = "youtube-cookies.txt"   # friend-apps/launcher/src/YtLogin.cs の CookiesPath と同じ名前
EXE_REL = os.path.join("friend-apps", "launcher", "build", "FriendApp.exe")
LOGIN_ARG = "--yt-login"               # friend-apps/launcher/src/Launcher.cs の YtLoginArg


def cookies_path(app_dir):
    return os.path.join(app_dir, SECRETS, COOKIES_NAME)


def apply_env(app_dir, env=None):
    """入口の起動のとき: YTT_YTDLP_COOKIES が空なら、この PC の置き場所を入れる(外から入れた物はそのまま)-> 入れたパス"""
    env = os.environ if env is None else env
    if not (env.get(_tools.COOKIES_ENV) or "").strip():
        env[_tools.COOKIES_ENV] = cookies_path(app_dir)
    return env[_tools.COOKIES_ENV]


class YtLogin:
    """ホームの設定の「YouTube のログイン」の口(入口の api/ytt/ytlogin)。repo = リポジトリの直下(exe を探す)。popen = テストで差し替える"""

    def __init__(self, app_dir, repo, env=None, popen=None, log=None):
        self.app_dir, self.repo = app_dir, repo
        self.env = os.environ if env is None else env
        self.popen = popen or subprocess.Popen
        self.log = log or (lambda m: None)
        self.proc = None
        self.last = ""   # 最後のログインの結果の文(画面のトースト)
        self.lock = threading.Lock()

    def src(self):
        return (self.env.get(_tools.COOKIES_ENV) or "").strip()

    def exe(self):
        p = os.path.join(self.repo, EXE_REL)
        return p if os.path.isfile(p) else None

    def running(self):
        with self.lock:
            if self.proc is not None and self.proc.poll() is not None:
                self.last = "YouTube にログインしました" if self.proc.returncode == 0 else "ログインを途中でやめました"
                self.log("YouTube のログイン: %s" % self.last)
                self.proc = None
            return self.proc is not None

    def status(self):
        """{state: none|ok|expired, at: ログインした ms, running: 小窓が開いているか, canLogin, why, message}"""
        running = self.running()
        src = self.src()
        at = _ytcookies.login_at(src)
        facts = _ytcookies.facts(src) or {}
        state = "none" if not at else "expired" if facts.get("lostAt") else "ok"
        exe = self.exe()
        return {"state": state, "at": at, "running": running, "canLogin": bool(exe and src),
                "why": "" if exe else "ログインの小窓(FriendApp.exe)がありません。friend-apps\\launcher\\build.bat で作ってください",
                "message": self.last}

    def login(self):
        """小窓を起こす(開いていればそのまま)-> status"""
        exe, src = self.exe(), self.src()
        if not exe or not src:
            raise ValueError(self.status()["why"] or "ログインの置き場所が決まっていません")
        if not self.running():
            dir_ = os.path.dirname(os.path.dirname(src))   # <置き場所>\secrets\youtube-cookies.txt の <置き場所>
            os.makedirs(dir_, exist_ok=True)
            with self.lock:
                self.last = ""
                self.proc = self.popen([exe, LOGIN_ARG, dir_], cwd=os.path.dirname(exe), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log("YouTube のログインの小窓を開きました")
        return self.status()

    def logout(self):
        """-> status(message にログアウトしたか)"""
        had = _ytcookies.logout(self.src())
        self.last = "ログアウトしました" if had else "ログインしていませんでした"
        self.log("YouTube のログイン: %s" % self.last)
        return self.status()
