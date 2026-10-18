"""作業データの置き場所(統合計画の段階4)。データはリポジトリの外に置く(Public のリポジトリに個人データを混ぜないため)。

置き場所(2026-09-26 ユーザー決定):
  Windows  … %LOCALAPPDATA%\\youtube-tools\\<ツールID>\\   (OneDrive で同期されない、アプリのデータの定番の場所)
  それ以外 … $XDG_DATA_HOME/youtube-tools/<ツールID>/(無ければ ~/.local/share/…)。macOS は ~/Library/Application Support/…
  環境変数 YTT_DATA_DIR があればそちらを使う(<YTT_DATA_DIR>\\<ツールID>)。
  YTT_DATA_DIR=inplace はリポジトリ直下の .data/<ツールID>/(テスト用。src はコードだけ。.runtime も .data の下。2026-10-16 ユーザー決定)。

以前の場所(各ツールのフォルダの中)からの写し(.migrated.json の印)は 2026-10-18 に消した(写す対象が 0。印が残っていても読まない)。

置き場所の求め方はここ1か所(2026-10-01 ユーザー決定。`notes:docs/spec/data.md` の「置き場所の求め方」):
  resolve(tool) の順番
    ① 登録された場所 … 各ツールが起動したときに実際に決めたフォルダ(prepare が登録する)。入口の中では、同じプロセスの
       他のツール(案件・まとめて実行・スタジオのセリフの表示など)がそれを読む(移せずに以前の場所のまま動いた・テストがツールを
       一時フォルダに写して動かした、でも読む場所がずれない)。env を渡したとき(テスト・明示の指定)は見ない
    ② ツールごとの環境変数(ENV_OVERRIDE。STUDIO_HOME・TRANSCRIBE_DATA_DIR。テスト用・以前からの指定)
    ③ tool_dir(YTT_DATA_DIR → %LOCALAPPDATA% など。inplace なら各ツールのフォルダの中)
  ツールの側(起動時): prepare(②があればそれを使う。無ければ新しい場所を作って register)。入口は locate + register
  読む側: resolve
"""
import os
import sys
import threading

from . import fsio, layout

APP_DIR_NAME = "youtube-tools"
INPLACE = "inplace"
# そのツールのデータのフォルダを直接決める環境変数(テスト用・以前からの指定・ワーカーへの受け渡し)。あれば YTT_DATA_DIR より先に使う
ENV_OVERRIDE = {"studio": "STUDIO_HOME", "transcribe": "TRANSCRIBE_DATA_DIR"}

_registered = {}          # ツールの ID -> 起動したツールが決めたフォルダ(register)
_reg_lock = threading.Lock()


def data_root(env=None, platform=None, home=None):
    """全ツールのデータの親フォルダ。YTT_DATA_DIR=inplace なら None(各ツールのフォルダの中を使う)。"""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = home or os.path.expanduser("~")
    d = (env.get("YTT_DATA_DIR") or "").strip()
    if d:
        return None if d.lower() == INPLACE else os.path.abspath(d)
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, APP_DIR_NAME)


def inplace_dir(tool, legacy_dir, root=None):
    """YTT_DATA_DIR=inplace のときのデータのフォルダ = <リポジトリ直下>/.data/<ツールの ID>(コードの src の中には作らない)。
    root = src とみなすフォルダ。無ければ legacy_dir(ツールのフォルダ)の 1 つ上。それが src でなければ(テストがツールを一時フォルダに
    写したとき)以前と同じ legacy_dir"""
    base = layout.inplace_root(root or os.path.dirname(os.path.abspath(legacy_dir)))
    return os.path.abspath(legacy_dir) if base is None else os.path.join(base, tool)


def tool_dir(tool, legacy_dir, env=None, root=None):
    """そのツールのデータのフォルダ(移行はしない。inplace なら <リポジトリ直下>/.data/<ID>。legacy_dir は root の既定を決めるだけ)。"""
    base = data_root(env)
    return inplace_dir(tool, legacy_dir, root) if base is None else os.path.join(base, tool)


def override(tool, env=None):
    """ツールごとの環境変数(ENV_OVERRIDE)で決めたフォルダ(絶対パス)か None"""
    env = os.environ if env is None else env
    name = ENV_OVERRIDE.get(tool)
    d = (env.get(name) or "").strip() if name else ""
    return os.path.abspath(d) if d else None


def register(tool, path):
    """起動したツールが実際に使うフォルダを知らせる(同じプロセスの他のツールが resolve で読む)。None で取り消す。-> 登録したパス"""
    with _reg_lock:
        if path:
            _registered[tool] = os.path.abspath(path)
        else:
            _registered.pop(tool, None)
        return _registered.get(tool)


def registered(tool):
    """登録されたフォルダか None"""
    with _reg_lock:
        return _registered.get(tool)


def locate(tool, repo_root=None, env=None, legacy_dir=None):
    """登録を見ない置き場所: ツールごとの環境変数(ENV_OVERRIDE)→ tool_dir(YTT_DATA_DIR → 既定。inplace ならツールのフォルダ)。
    legacy_dir: 以前の場所(ツールのフォルダ)。無ければ <repo_root>/<layout のフォルダ名>(repo_root が無ければこのリポジトリ)"""
    o = override(tool, env)
    if o:
        return o
    return tool_dir(tool, legacy_dir or layout.tool_dir(tool, repo_root), env, repo_root)


def resolve(tool, repo_root=None, env=None, legacy_dir=None):
    """そのツールの作業データのフォルダ(他のツールから読むとき)。① 登録された場所(env を渡したときは見ない)→ locate"""
    if env is None:
        r = registered(tool)
        if r:
            return r
    return locate(tool, repo_root, env, legacy_dir)


def studio_out_dir(repo_root=None, env=None):
    """スタジオの書き出し先(他のツールから読むだけ。2026-10-09 に入口の live.py・server.py の写しから移した)。
    スタジオの作業データ(resolve)の settings.json の outDir が空でない絶対パスならそれ、無い・読めない・形が違えば <スタジオの作業データ>/exports"""
    sdir = resolve("studio", repo_root, env)
    st = fsio.read_json_or(os.path.join(sdir, "settings.json"), None, kind=dict)
    out = st.get("outDir") if st else None
    return out if isinstance(out, str) and out and os.path.isabs(out) else os.path.join(sdir, "exports")


def prepare(tool, legacy_dir, env=None):
    """データのフォルダを決める。起動時に1回呼ぶ。legacy_dir = ツールのフォルダ(inplace のときの置き場所を決めるだけ)。
    -> {"dir": 使うフォルダ, "warnings": [...], "state": "override"|"inplace"|"new"|"failed"}
    state: override = ツールごとの環境変数(ENV_OVERRIDE)で決めた / inplace = YTT_DATA_DIR=inplace(またはツールのフォルダと同じ場所)
           / new = 新しい場所(無ければ作る) / failed = 新しい場所を作れず、ツールのフォルダのまま
    env を渡さない(本物の起動)ときは、決めたフォルダを register する(env を渡すテストは、プロセス全体の登録を変えない)"""
    out = _prepare(tool, os.path.abspath(legacy_dir), env)
    if env is None:
        register(tool, out["dir"])
    return out


def _prepare(tool, legacy_dir, env):
    def result(d, state, warning=None):
        return {"dir": d, "warnings": [warning] if warning else [], "state": state}
    o = override(tool, env)
    if o:
        return result(o, "override")
    root = data_root(env)
    if root is None:
        return result(inplace_dir(tool, legacy_dir), "inplace")
    new = os.path.join(root, tool)
    if os.path.normcase(new) == os.path.normcase(legacy_dir):
        return result(new, "inplace")
    try:
        os.makedirs(new, exist_ok=True)
    except OSError as e:
        return result(legacy_dir, "failed", "データのフォルダ %s を作れないため、ツールのフォルダ(%s)を使います: %s" % (new, legacy_dir, e))
    return result(new, "new")
