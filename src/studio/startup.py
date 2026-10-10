"""切り抜きスタジオの起動の小物(役割で組み直す RS5-B。2026-10-10。旧 common.py の殻を消して、残った起動の物だけここへ)。

- 読み込み: `import startup` が src を sys.path に足し(_load_core)、スタジオのフォルダを ytt/studio_env に知らせる。serve は最初にこれを読む
- 起動時の環境チェック(check_tools・start_env_check・env_state。/api/state の env)と、古いログの名前の付け替え(migrate_old_logs)
- 旧い名前 common.名前 の持ち主は ytt(studio_env・procs・mediainfo・apikey・textutil・errors・fsio)と pipeline/ingest/sources。ここへ足さない
"""
import datetime
import json
import os
import re
import shutil
import sys
import threading

CODE_DIR = os.path.dirname(os.path.abspath(__file__))   # コード・静的ファイル・seed.json の場所


def _load_core():
    """共通部品 ytt(src の直下)を読み込めるようにする。
    探す場所: 環境変数 YTT_CORE_DIR(ツールを一時フォルダに写して動かすテスト用)→ このフォルダの1つ上。
    sys.path の末尾に足す(このフォルダの同名のモジュールを隠さないため)。"""
    for d in (os.environ.get("YTT_CORE_DIR"), os.path.dirname(CODE_DIR)):
        if d and os.path.isfile(os.path.join(d, "ytt", "__init__.py")):
            if d not in sys.path:
                sys.path.append(d)
            return
    raise SystemExit("共通部品 ytt が見つかりません(%s の隣に ytt フォルダが必要です)。"
                     "リポジトリのフォルダの中身をまとめて置き直してください" % CODE_DIR)


_load_core()
from ytt import fsio as _fsio, studio_env as _studio_env, tools as _tools  # noqa: E402

_studio_env.set_code_dir(CODE_DIR)   # 既定のデータの置き場所 = このフォルダ(ytt から見たスタジオのフォルダは、テストが ytt を別の場所から読むとずれる)


def migrate_old_logs():
    """以前の版が作った studio.log.old / studio-errors.log.old を studio.old.log などへ改名する(起動時に1回。失敗しても無視)。"""
    for name in ("studio.log", "studio-errors.log", "studio.crash.log"):
        old = _studio_env.p(name + ".old")
        try:
            if os.path.isfile(old):
                _fsio.replace_retry(old, _studio_env.old_log_name(_studio_env.p(name)))
        except OSError:
            pass


# ---------- 起動時の環境チェック(/api/state の env) ----------
YTDLP_OLD_DAYS = 60              # yt-dlp の版(日付)がこれより古ければ更新を勧める(YouTube 側の変更で古い版は取得に失敗しやすい)
LOW_DISK_BYTES = 2 * 1024 ** 3   # 出力先の空きがこれ未満なら注意
_env = {"checked": False, "tools": {}}
_env_lock = threading.Lock()


def _tool_version(name, args, pattern, timeout=15):
    """{"found", "version"}(版を読めなければ ""。動かすのは ytt.tools.tool_version = 窓を出さない)"""
    exe = _studio_env.find_tool(name)
    if not exe:
        return {"found": False, "version": ""}
    return {"found": True, "version": _tools.tool_version(exe, args, pattern, timeout)}


def check_tools():
    """ffmpeg / ffprobe / yt-dlp の有無と版を調べて覚える(起動時に裏のスレッドで1回。数秒かかることがある)。"""
    fake = _studio_env.fake()
    tools = {"ffmpeg": _tool_version("ffmpeg", ["-hide_banner", "-version"], r"ffmpeg version (\S+)"),
             "ffprobe": {"found": bool(_studio_env.find_tool("ffprobe")), "version": ""}}
    tools["ytdlp"] = {"found": fake, "version": ""} if fake else _tool_version("yt-dlp", ["--version"], r"^\s*(\d{4}\.\d{2}\.\d{2}\S*)")
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", tools["ytdlp"]["version"])
    if m:
        try:
            tools["ytdlp"]["ageDays"] = (datetime.date.today() - datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
        except ValueError:
            pass
    with _env_lock:
        _env["tools"], _env["checked"] = tools, True
    return tools


def start_env_check():
    """check_tools を裏のスレッドで 1 回動かす(serve.prepare が呼ぶ)"""
    threading.Thread(target=check_tools, daemon=True, name="env-check").start()


def env_state():
    """{"checked", "python", "tools": {ffmpeg, ffprobe, ytdlp}, "outDirFree"(バイト or None), "warnings": [画面に出せる文]}。
    道具の版は起動時に調べた結果(調べ終わるまでは checked=false)。空き容量は毎回その場で調べる(速い)。"""
    with _env_lock:
        tools = json.loads(json.dumps(_env["tools"]))
        checked = _env["checked"]
    warnings = []
    free = None
    try:
        d = _studio_env.get_out_dir()
        while d and not os.path.isdir(d) and os.path.dirname(d) != d:   # まだ作っていない出力先は、存在する親で測る
            d = os.path.dirname(d)
        free = shutil.disk_usage(d).free
        if free < LOW_DISK_BYTES:
            warnings.append("書き出し先のドライブの空きが少なくなっています(残り %.1f GB)" % (free / 1024 ** 3))
    except OSError:
        pass
    if not _studio_env.find_tool("ffmpeg"):
        warnings.append("ffmpeg が見つかりません。解析・書き出しに必要です(README の準備手順を確認してください)")
    if not _studio_env.fake() and not _studio_env.find_tool("yt-dlp"):
        warnings.append("yt-dlp が見つかりません。YouTube の解析・書き出しに必要です(手元のファイルは使えます)")
    age = (tools.get("ytdlp") or {}).get("ageDays")
    if isinstance(age, int) and age > YTDLP_OLD_DAYS:
        warnings.append("yt-dlp が古い可能性があります(%s。%d日前の版)。取得に失敗するときは「yt-dlp -U」で更新してください"
                        % (tools["ytdlp"]["version"], age))
    return {"checked": checked, "python": sys.version.split()[0], "tools": tools, "outDirFree": free, "warnings": warnings}
