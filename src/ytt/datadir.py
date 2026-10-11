"""作業データの置き場所(統合計画の段階4)。データはリポジトリの外に置く(Public のリポジトリに個人データを混ぜないため)。

置き場所(2026-09-26 ユーザー決定):
  Windows  … %LOCALAPPDATA%\\youtube-tools\\<ツールID>\\   (OneDrive で同期されない、アプリのデータの定番の場所)
  それ以外 … $XDG_DATA_HOME/youtube-tools/<ツールID>/(無ければ ~/.local/share/…)。macOS は ~/Library/Application Support/…
  環境変数 YTT_DATA_DIR があればそちらを使う(<YTT_DATA_DIR>\\<ツールID>)。
  YTT_DATA_DIR=inplace は以前と同じ「各ツールのフォルダの中」(テスト・元に戻したいとき用)。

以前の場所(各ツールのフォルダの中)にデータがあれば、最初の起動で新しい場所へ**コピー**する(元は消さない。消すのはユーザーが確かめてから)。
  - 項目ごとに「一時的な名前へコピー → 大きさと数を確かめる → 本来の名前へ改名」。途中で止まっても、半端なものを本物として使わない
  - 新しい場所にすでにある項目は上書きしない(手で写した・前回の途中まで写したもの)
  - 空き容量が足りない・コピーに失敗したときは移さず、そのツールは以前の場所のまま動く(警告を返す)
  - 全部終わったら .migrated.json に記録する。次からは写さない

置き場所の求め方はここ1か所(2026-10-01 ユーザー決定。`docs/spec/data-location.md` の「置き場所の求め方」):
  resolve(tool) の順番
    ① 登録された場所 … 各ツールが起動したときに実際に決めたフォルダ(prepare が登録する)。入口の中では、同じプロセスの
       他のツール(案件・まとめて実行・スタジオのセリフの表示など)がそれを読む(移せずに以前の場所のまま動いた・テストがツールを
       一時フォルダに写して動かした、でも読む場所がずれない)。env を渡したとき(テスト・明示の指定)は見ない
    ② ツールごとの環境変数(ENV_OVERRIDE。STUDIO_HOME・TRANSCRIBE_DATA_DIR。テスト用・以前からの指定)
    ③ tool_dir(YTT_DATA_DIR → %LOCALAPPDATA% など。inplace なら各ツールのフォルダの中)
  ツールの側(起動時): prepare(移行もする。②があればそれを使い、写さない)。移行の要らないもの(入口)は locate + register
  読む側: resolve
"""
import os
import shutil
import sys
import threading
import time

from . import fsio, layout

APP_DIR_NAME = "youtube-tools"
INPLACE = "inplace"
MARKER = ".migrated.json"
MARKER_MAX = 64 * 1024   # 移した記録はこれより大きければ読まない(中身は名前の一覧と数だけ)
PART = ".part-"          # コピー中の一時的な名前の印(次の起動で消す)
SPACE_MARGIN = 256 * 1024 * 1024   # 空き容量の余裕(コピーする量 + これ)
# そのツールのデータのフォルダを直接決める環境変数(テスト用・以前からの指定)。あれば YTT_DATA_DIR より先に使い、移行はしない
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


def tool_dir(tool, legacy_dir, env=None):
    """そのツールのデータのフォルダ(移行はしない。inplace なら legacy_dir)。"""
    root = data_root(env)
    return os.path.abspath(legacy_dir) if root is None else os.path.join(root, tool)


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
    return tool_dir(tool, legacy_dir or layout.tool_dir(tool, repo_root), env)


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


def _size(path):
    """(バイト数, ファイル数)。フォルダは中身の合計。リンクはたどらない。
    fsio.dir_size と違い、大きさを調べられないファイルがあれば OSError を上げる(コピーの確かめに使うので、数え漏れを「同じ」にしない)"""
    if os.path.isfile(path):
        return os.path.getsize(path), 1
    total = count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for n in filenames:
            fp = os.path.join(dirpath, n)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
                count += 1
    return total, count


def _ignore_links(src, names):
    return [n for n in names if os.path.islink(os.path.join(src, n))]


def _copy_item(src, dst):
    """src を dst へ(一時的な名前 → 確かめる → 改名)。-> (バイト数, ファイル数)。失敗したら一時的なものを消して例外"""
    tmp = dst + PART + "%d" % os.getpid()
    _remove_any(tmp)
    try:
        if os.path.isdir(src):
            shutil.copytree(src, tmp, ignore=_ignore_links)
        else:
            shutil.copy2(src, tmp)
        want, got = _size(src), _size(tmp)
        if want != got:
            raise OSError("コピーした大きさ・数が元と違います(%s: %s → %s)" % (os.path.basename(src), want, got))
        os.replace(tmp, dst)
        return got
    except BaseException:
        _remove_any(tmp)
        raise


def _remove_any(p):
    """ファイルかフォルダを消す(無い・消せなくても上げない)"""
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
    else:
        fsio.unlink_quiet(p)


def _clean_parts(d):
    """前回のコピーの途中で止まった一時的なもの(名前に PART)を消す"""
    try:
        names = os.listdir(d)
    except OSError:
        return
    for n in names:
        if PART in n:
            _remove_any(os.path.join(d, n))


def read_marker(d):
    """移した記録(.migrated.json)-> dict か None(無い・壊れている・64KB より大きい)"""
    return fsio.read_json_or(os.path.join(d, MARKER), None, MARKER_MAX, dict)


def prepare(tool, legacy_dir, items, env=None, log=None, free_bytes=None):
    """データのフォルダを決め、必要なら以前の場所から写す。起動時に1回呼ぶ。
    items: 以前の場所から写す名前(ファイル・フォルダ。ツールのフォルダの中の相対名。無いものは飛ばす)。
    -> {"dir": 使うフォルダ, "legacy": 以前の場所, "migrated": [写した名前], "warnings": [...], "state": "inplace"|"new"|"migrated"|"done"|"failed"}
    state: inplace = 以前と同じ場所 / new = 以前のデータが無い / migrated = 今回写した / done = 前に写し済み / failed = 写せず以前の場所のまま
           / override = ツールごとの環境変数(ENV_OVERRIDE)で決めた(写さない)
    env を渡さない(本物の起動)ときは、決めたフォルダを register する(env を渡すテストは、プロセス全体の登録を変えない)"""
    out = _prepare(tool, legacy_dir, items, env, log, free_bytes)
    if env is None:
        register(tool, out["dir"])
    return out


def _prepare(tool, legacy_dir, items, env, log, free_bytes):
    say = log or (lambda m: None)
    legacy_dir = os.path.abspath(legacy_dir)

    def result(d, state, warning=None, migrated=()):
        return {"dir": d, "legacy": legacy_dir, "migrated": list(migrated), "warnings": [warning] if warning else [], "state": state}
    o = override(tool, env)
    if o:
        return result(o, "override")
    root = data_root(env)
    if root is None:
        return result(legacy_dir, "inplace")
    new = os.path.join(root, tool)
    if os.path.normcase(new) == os.path.normcase(legacy_dir):
        return result(new, "inplace")
    try:
        os.makedirs(new, exist_ok=True)
    except OSError as e:
        return result(legacy_dir, "failed", "データのフォルダ %s を作れないため、以前の場所(%s)を使います: %s" % (new, legacy_dir, e))
    _clean_parts(new)
    if read_marker(new):
        return result(new, "done")
    present = [n for n in items if os.path.lexists(os.path.join(legacy_dir, n))]   # 以前の場所にあるもの
    todo = [n for n in present if not os.path.lexists(os.path.join(new, n))]
    if not todo:
        state = "done" if present else "new"
        _write_marker(new, legacy_dir, [], 0)
        return result(new, state)
    need = sum(_size(os.path.join(legacy_dir, n))[0] for n in todo)
    try:
        free = shutil.disk_usage(new).free if free_bytes is None else free_bytes
    except OSError:
        free = None
    if free is not None and free < need + SPACE_MARGIN:
        return result(legacy_dir, "failed", "空き容量が足りないため、データを %s へ移せませんでした(必要 約%dMB・空き 約%dMB)。以前の場所(%s)のまま動きます"
                      % (new, (need + SPACE_MARGIN) // 2**20, free // 2**20, legacy_dir))
    say("作業データを %s へコピーしています(約%dMB。元の %s は消しません)…" % (new, need // 2**20, legacy_dir))
    copied, total = [], 0
    for n in todo:
        try:
            b, _ = _copy_item(os.path.join(legacy_dir, n), os.path.join(new, n))
        except (OSError, shutil.Error) as e:
            for c in copied:   # 今回写した分は消す(以前の場所のまま動く間に古くなるので、次に写すときに新しい方を写し直す)
                _remove_any(os.path.join(new, c))
            return result(legacy_dir, "failed", "データのコピーに失敗したため、以前の場所(%s)のまま動きます(%s: %s)" % (legacy_dir, n, e))
        copied.append(n)
        total += b
    _write_marker(new, legacy_dir, copied, total)
    say("コピーしました: %s(元のデータは %s に残っています。確かめてから消してください)" % (", ".join(copied), legacy_dir))
    return result(new, "migrated", migrated=copied)


def _write_marker(d, legacy, items, total):
    fsio.write_json(os.path.join(d, MARKER), {"from": legacy, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "items": items, "bytes": total})
