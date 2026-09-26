# -*- coding: utf-8 -*-
"""画面を「窓」(Edge のアプリモード)で開く(統合計画の段階7-3。試用。既定はブラウザのまま)。

- 設定: 作業データの置き場所の app\\settings.json の "window"("browser" | "app")。入口の画面の「窓で開く(試用)」で切り替える
- 窓: Edge を `--app=<URL> --user-data-dir=<専用のプロファイル>` で起動する。
  専用のプロファイル(作業データの置き場所の app\\browser-profile)なので、いつものブラウザの拡張機能・履歴と混ざらない。
  同じプロファイルの Edge がもう動いていれば、Edge がそちらに窓を足して、起動したプロセスはすぐ終わる
- 窓の中の「新しいタブで開く」リンクは、画面(ui-kit の UIKit.win)が入口に頼む:
  このパソコンの画面 → 同じ形の窓(open_url)、外のサイト(YouTube など)→ いつものブラウザ(open_external)
- やらないこと: リモートデバッグのポートは開けない(開くと PC 上のどのプログラムでも窓を操作でき、合言葉も読めるため)。
  窓を閉じても入口は終わらない(閉じる直前の保存より先にサーバーが止まる危険を持ち込まない。終わるのは「すべて終了」)

安全: 窓で開けるのは入口と、動いているツールのポートの画面だけ(スキーム・ホスト・ポート・パスを検査)。
外のサイトは http / https だけ。どちらも短い時間に開ける数に上限(画面の XSS で窓を大量に開かれないように)。
コマンドは引数のリストで渡す(シェルを通さない)。URL は空白・引用符・制御文字を含むものを断るので、Edge の別の引数に化けない。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

MODES = ("browser", "app")
PROFILE_NAME = "browser-profile"
SETTINGS_NAME = "settings.json"
EDGE_REL = os.path.join("Microsoft", "Edge", "Application", "msedge.exe")
MAC_EDGE = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
URL_MAX = 2048
RATE = (8, 10.0)   # 10 秒に 8 回まで(窓とブラウザを合わせて)
PORTAL_PAGES = ("/", "/index.html", "/cases.html")
TOOL_PAGES = ("/", "/index.html")
BAD_CHARS = set(' "\'<>\\^`{|}')


class Unavailable(Exception):
    """窓を開くのに使うブラウザ(Edge)が見つからない"""


class TooMany(Exception):
    """短い時間に開きすぎ"""


def find_edge(env=None, platform=None, isfile=os.path.isfile, which=shutil.which, reg=None):
    """Edge(Chromium 系)の実行ファイル。環境変数 YTT_APP_BROWSER があればそれ(Chrome を使いたいとき・テスト)。見つからなければ None"""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    own = (env.get("YTT_APP_BROWSER") or "").strip()
    if own:
        return own if isfile(own) else None
    if platform.startswith("win"):
        for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = env.get(key)
            if base and isfile(os.path.join(base, EDGE_REL)):
                return os.path.join(base, EDGE_REL)
        path = (reg or _edge_from_registry)()
        return path if path and isfile(path) else None
    if platform == "darwin":
        return MAC_EDGE if isfile(MAC_EDGE) else None
    for name in ("microsoft-edge", "microsoft-edge-stable"):
        p = which(name)
        if p:
            return p
    return None


def _edge_from_registry():
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as k:
                return winreg.QueryValue(k, None)
        except OSError:
            continue
    return None


def app_command(exe, url, profile):
    """Edge をアプリモードで起動するコマンド(引数のリスト。シェルを通さない)"""
    return [exe, "--app=" + url, "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check"]


def _clean(url):
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        raise ValueError("URL が正しくありません")
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in url) or any(c in BAD_CHARS for c in url):
        raise ValueError("URL に使えない文字があります")
    return urllib.parse.urlsplit(url)


def local_url(url, portal_port, tool_ports=(), prefixes=("/studio", "/transcribe", "/cut2resolve")):
    """窓で開いてよい URL か確かめて、正規の形(http://localhost:<port><path>)で返す。だめなら ValueError。
    入口のポート: 入口の画面と、取り込んだツールの画面(/studio/ など。prefixes)。ツールのポート(別のプログラムとして動いているもの): その画面だけ"""
    u = _clean(url)
    if u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1") or u.username or u.password:
        raise ValueError("このパソコンの画面ではありません")
    try:
        port = u.port
    except ValueError:
        raise ValueError("ポートが正しくありません")
    path = u.path or "/"
    if port == portal_port:
        ok = path in PORTAL_PAGES or any(path.startswith(p + "/") for p in prefixes)
    elif port in set(tool_ports):
        ok = path in TOOL_PAGES
    else:
        raise ValueError("動いていないポートです")
    if not ok or "/../" in path + "/" or "//" in path:
        raise ValueError("開けない場所です")
    return urllib.parse.urlunsplit(("http", "localhost:%d" % port, path, u.query, u.fragment))



def external_url(url):
    u = _clean(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("開けるのは http / https のページだけです")
    return url


def read_mode(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return "browser"
    m = d.get("window") if isinstance(d, dict) else None
    return m if m in MODES else "browser"


def write_mode(path, mode, atomic_write):
    if mode not in MODES:
        raise ValueError("mode は browser か app です")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d["window"] = mode
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write(path, json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
    return mode


class Opener:
    """窓・いつものブラウザで開く係(入口に1つ)。data_dir は作業データの置き場所の app フォルダ"""

    def __init__(self, data_dir, atomic_write, env=None, popen=subprocess.Popen, browser_open=webbrowser.open,
                 find=find_edge, clock=time.monotonic, log=None):
        self.settings_path = os.path.join(data_dir, SETTINGS_NAME)
        self.profile = os.path.join(data_dir, PROFILE_NAME)
        self._atomic_write, self._popen, self._browser_open = atomic_write, popen, browser_open
        self._find, self._env, self._clock, self._log = find, env, clock, log or (lambda msg: None)
        self._lock = threading.Lock()
        self._times = []
        self._exe = None
        self._looked = False

    @property
    def mode(self):
        return read_mode(self.settings_path)

    def set_mode(self, mode):
        return write_mode(self.settings_path, mode, self._atomic_write)

    def exe(self):
        if not self._looked:   # 一度だけ探す(Edge の場所は起動中に変わらない)
            self._exe, self._looked = self._find(self._env), True
        return self._exe

    def status(self):
        exe = self.exe()
        return {"mode": self.mode, "available": bool(exe), "browser": os.path.basename(exe) if exe else "", "profile": self.profile}

    def _rate(self):
        with self._lock:
            now = self._clock()
            self._times = [t for t in self._times if now - t < RATE[1]]
            if len(self._times) >= RATE[0]:
                raise TooMany("短い時間に開きすぎです。少し待ってからもう一度押してください")
            self._times.append(now)

    def _spawn(self, url):
        exe = self.exe()
        if not exe:
            raise Unavailable("窓で開くのに使う Microsoft Edge が見つかりません")
        flags = 0
        if os.name == "nt":   # 入口の黒い画面の Ctrl+C・Ctrl+Break(終了の合図)を Edge に伝えない
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        os.makedirs(self.profile, exist_ok=True)
        self._popen(app_command(exe, url, self.profile), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)

    def open_start(self, url):
        """起動したときに入口の画面を開く。窓の設定で Edge があれば窓、無い・失敗したらいつものブラウザ。-> 開いた形"""
        if self.mode == "app":
            try:
                self._spawn(url)
                return "app"
            except (Unavailable, OSError) as e:
                self._log("窓で開けなかったので、ブラウザで開きます(%s)" % e)
        self._browser_open(url)
        return "browser"

    def open_url(self, url, portal_port, tool_ports=(), prefixes=()):
        """画面のリンクから: このパソコンの画面を窓で開く(URL は local_url で検査)"""
        target = local_url(url, portal_port, tool_ports, prefixes)
        self._rate()
        self._spawn(target)
        return target

    def open_external(self, url):
        """画面のリンクから: 外のサイトをいつものブラウザで開く"""
        target = external_url(url)
        self._rate()
        if not self._browser_open(target):
            raise OSError("ブラウザを開けませんでした")
        return target
