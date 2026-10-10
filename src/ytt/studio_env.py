"""スタジオの環境: データの置き場所・書き出し先・疑似の旗・外部の道具・失敗の記録(役割で組み直す RS3-4。2026-10-10 にスタジオの common.py から移した)。

スタジオの部品(serve・store・rank・handoff・txlink)と、① に移る部品(解析 analyze・書き出し pipeline/export/exporter)が同じ状態を読む。
状態はこのモジュールに 1 つ(serve.init・prepare が set_home・load_out_dir を呼ぶ)。設定ファイルの決まり(ytt/settings)とは別。
- 置き場所: `set_home(d)`・`home()`・`p(*parts)`(既定はスタジオのフォルダ。環境変数 STUDIO_HOME の規則は ytt.datadir の 1 か所)
- スタジオのフォルダ: `code_dir()`。スタジオの common.py が読み込みのときに `set_code_dir(自分のフォルダ)` で知らせる
  (ここ ytt から見た `layout.tool_dir("studio")` は、テストが共通部品 YTT_CORE_DIR を別の場所から読むとずれるため。知らされるまでは layout の値)
- 疑似の旗: `fake()`(STUDIO_FAKE=1)・`fake_media()`(STUDIO_FAKE_MEDIA)。登録の口への置き換えは RS5
- 外部の道具: `find_tool(name)`(環境変数 STUDIO_<名前> → PATH)
- 失敗の記録: `log_failure(context, error)`(<置き場所>/studio-errors.log)・`rotate_log`・`old_log_name`
- 書き出し先(settings.json の outDir): `get_out_dir`・`default_out_dir`・`set_out_dir`・`load_out_dir`・`check_out_dir`・`is_inside_out_dir`・`_out_lock`
読む側は `studio_env.名前` を呼ぶたびに読む(テストの `common.get_out_dir` などの差し替えは、スタジオの common.py の転送がここへ届ける。RS5 で消す)。
"""
import json
import os
import tempfile
import threading
import time
import traceback

from . import datadir as _datadir, errors, fsio as _fsio, layout as _layout, textutil as _textutil, tools as _tools

_code_dir = _layout.tool_dir("studio")   # スタジオのフォルダ(コード・静的ファイル)。スタジオの startup.py が set_code_dir で正しい場所を入れる
_home = None   # data.json などの置き場所。None = 呼ばれたときに決める(home())。読み込みの時点で決めると、入口が置き場所の設定(YTT_DATA_DIR など)を
#                済ませる前に読み込まれたとき(RS5-D で intake が読むようになった)古い置き場所で固まる
_out_dir = None   # 書き出し先。None = 標準(<置き場所>/exports)


def set_code_dir(d):
    """スタジオのフォルダを知らせる(スタジオの startup.py が読み込みのときに 1 回)。置き場所を set_home で決めていなければ、既定の置き場所もここになる(home())"""
    global _code_dir
    _code_dir = os.path.abspath(d)


def code_dir():
    """スタジオのフォルダ(<src>/studio。.runtime・文字起こしの根はこの 1 つ上)"""
    return _code_dir


def set_home(d):
    """データの置き場所を変える(serve.init・テスト)。書き出し先は標準に戻す"""
    global _home
    _home = os.path.abspath(d)
    os.makedirs(_home, exist_ok=True)
    reset_out_dir()


def home():
    """データの置き場所"""
    if _home is not None:
        return _home
    return _datadir.override("studio") or os.path.abspath(_code_dir)


def p(*parts):
    """データ置き場の中のパス。"""
    return os.path.join(home(), *parts)


def fake():
    """疑似モード(テスト用)。"""
    return os.environ.get("STUDIO_FAKE") == "1"


def fake_media():
    """疑似モードで YouTube の動画の代わりに使う手元のファイル(環境変数 STUDIO_FAKE_MEDIA)。無ければ ApiError 500"""
    path = os.environ.get("STUDIO_FAKE_MEDIA", "")
    if not os.path.isfile(path):
        raise errors.ApiError("fake", "STUDIO_FAKE_MEDIA が指定されていません", 500)
    return path


def find_tool(name):
    """環境変数 STUDIO_<名前>(例 STUDIO_FFMPEG・STUDIO_YTDLP)があればそれ、無ければ PATH から。"""
    return _tools.find_tool(name, "STUDIO_" + name.upper().replace("-", ""))


# ---------- 失敗の記録 ----------
_error_log_lock = threading.Lock()


def old_log_name(path):
    """studio.log → studio.old.log。*.log のまま回すのは、.gitignore の *.log に掛けるため
    (以前の studio.log.old は掛からず、push.bat の git add -A で公開リポジトリに載るおそれがあった)。"""
    root, ext = os.path.splitext(path)
    return root + ".old" + ext


def rotate_log(path, limit):
    """path が limit バイトを超えていたら、1世代だけ <名前>.old.<拡張子> に回す(前の .old は上書き)。"""
    if os.path.exists(path) and os.path.getsize(path) > limit:
        _fsio.replace_retry(path, old_log_name(path))


def log_failure(context, error):
    """握りつぶしていた処理エラーも、原因と失敗箇所をローカルに残す。"""
    try:
        with _error_log_lock:
            path = p("studio-errors.log")
            rotate_log(path, 1024 * 1024)
            with open(path, "a", encoding="utf-8") as f:
                detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                f.write("[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), context, _textutil.redact(detail)))
    except OSError:
        pass


# ---------- 出力先フォルダ(settings.json の outDir) ----------
def default_out_dir():
    """標準の書き出し先(<置き場所>/exports)"""
    return p("exports")


def reset_out_dir():
    """書き出し先を標準に戻す(覚えている値だけ。settings.json は触らない)"""
    global _out_dir
    _out_dir = None


def get_out_dir():
    """今の書き出し先"""
    return _out_dir or default_out_dir()


def is_inside_out_dir(raw):
    """raw(絶対パス)が書き出し先(get_out_dir)の中のもの(書き出し先そのものは含まない)か。realpath で比べる(.. やリンクで外へ出られない)。
    ファイルがまだ無くてもよい(親のリンクは解決される)"""
    real, root = os.path.realpath(raw), os.path.realpath(get_out_dir())
    try:
        return os.path.commonpath([os.path.normcase(real), os.path.normcase(root)]) == os.path.normcase(root) and os.path.normcase(real) != os.path.normcase(root)
    except ValueError:   # 別のドライブ
        return False


def check_out_dir(raw):
    """入力された保存先を検査して、絶対パスにして返す(空なら標準に戻す)。作れない・書き込めないときは ApiError。"""
    bad = lambda m: errors.ApiError("bad_dir", m, 400)
    s = str(raw or "").strip().strip('"')
    if not s:
        return default_out_dir()
    if "\x00" in s or len(s) > 400:
        raise bad("保存先のパスが正しくありません")
    if "%" in s:
        raise bad("保存先に「%」は使えません(yt-dlp の出力指定と衝突するため)。別のフォルダを指定してください")
    s = os.path.expanduser(s)
    if not os.path.isabs(s):
        raise bad("保存先は、C:\\Users\\… や /Users/… のようにフルパスで指定してください")
    s = os.path.abspath(s)
    if os.path.dirname(s) == s:
        raise bad("ドライブの直下ではなく、その中のフォルダ(例: D:\\clips)を指定してください")
    try:
        os.makedirs(s, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=s, prefix=".write-test-"):
            pass
    except OSError as e:
        raise bad("そのフォルダを作れない、または書き込めません: " + str(e.strerror or e)[:120])
    return s


def load_out_dir():
    """settings.json の outDir を読み直す(消えた・書き込めなくなったときは標準に戻す)"""
    global _out_dir
    _out_dir = None
    try:
        v = _fsio.read_json_or(p("settings.json"), {}, kind=dict).get("outDir")
        if v:
            _out_dir = check_out_dir(v)
            if _out_dir == default_out_dir():
                _out_dir = None
    except errors.ApiError:
        _out_dir = None   # 消えた・書き込めなくなったときは標準に戻す(画面に出るパスで分かる)


_out_lock = threading.Lock()
BUSY_MSG = "処理の実行中は出力先を変えられません。終わってから変更してください"


def set_out_dir(raw, busy):
    """busy: 実行中の処理があるかを返す関数。実行中は 409。"""
    global _out_dir
    if busy():   # フォルダを作る前に判定(拒否したときに空フォルダを残さない)
        raise errors.ApiError("busy", BUSY_MSG, 409)
    new = check_out_dir(raw)
    with _out_lock:
        if busy():
            raise errors.ApiError("busy", BUSY_MSG, 409)
        if new == default_out_dir():
            if os.path.exists(p("settings.json")):
                os.unlink(p("settings.json"))
            _out_dir = None
        else:
            _fsio.atomic_write(p("settings.json"), json.dumps({"outDir": new}, ensure_ascii=False).encode("utf-8"))
            _out_dir = new
    return new
