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
"""
import json
import os
import shutil
import sys
import time

APP_DIR_NAME = "youtube-tools"
INPLACE = "inplace"
MARKER = ".migrated.json"
PART = ".part-"          # コピー中の一時的な名前の印(次の起動で消す)
SPACE_MARGIN = 256 * 1024 * 1024   # 空き容量の余裕(コピーする量 + これ)


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


def _size(path):
    """(バイト数, ファイル数)。フォルダは中身の合計。リンクはたどらない。"""
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
    if os.path.lexists(tmp):
        shutil.rmtree(tmp, ignore_errors=True) if os.path.isdir(tmp) else os.remove(tmp)
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
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        elif os.path.lexists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def _try_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _clean_parts(d):
    try:
        for n in os.listdir(d):
            if PART in n:
                p = os.path.join(d, n)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    except OSError:
        pass


def read_marker(d):
    try:
        with open(os.path.join(d, MARKER), encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else None
    except (OSError, ValueError):
        return None


def prepare(tool, legacy_dir, items, env=None, log=None, free_bytes=None):
    """データのフォルダを決め、必要なら以前の場所から写す。起動時に1回呼ぶ。
    items: 以前の場所から写す名前(ファイル・フォルダ。ツールのフォルダの中の相対名。無いものは飛ばす)。
    -> {"dir": 使うフォルダ, "legacy": 以前の場所, "migrated": [写した名前], "warnings": [...], "state": "inplace"|"new"|"migrated"|"done"|"failed"}
    state: inplace = 以前と同じ場所 / new = 以前のデータが無い / migrated = 今回写した / done = 前に写し済み / failed = 写せず以前の場所のまま"""
    say = log or (lambda m: None)
    legacy_dir = os.path.abspath(legacy_dir)
    root = data_root(env)
    if root is None:
        return {"dir": legacy_dir, "legacy": legacy_dir, "migrated": [], "warnings": [], "state": "inplace"}
    new = os.path.join(root, tool)
    out = {"dir": new, "legacy": legacy_dir, "migrated": [], "warnings": [], "state": "done"}
    if os.path.normcase(new) == os.path.normcase(legacy_dir):
        out["state"] = "inplace"
        return out
    try:
        os.makedirs(new, exist_ok=True)
    except OSError as e:
        out.update(dir=legacy_dir, state="failed")
        out["warnings"].append("データのフォルダ %s を作れないため、以前の場所(%s)を使います: %s" % (new, legacy_dir, e))
        return out
    _clean_parts(new)
    if read_marker(new):
        return out
    todo = [n for n in items if os.path.lexists(os.path.join(legacy_dir, n)) and not os.path.lexists(os.path.join(new, n))]
    if not todo:
        out["state"] = "new" if not any(os.path.lexists(os.path.join(legacy_dir, n)) for n in items) else "done"
        _write_marker(new, legacy_dir, [], 0)
        return out
    need = sum(_size(os.path.join(legacy_dir, n))[0] for n in todo)
    try:
        free = shutil.disk_usage(new).free if free_bytes is None else free_bytes
    except OSError:
        free = None
    if free is not None and free < need + SPACE_MARGIN:
        out.update(dir=legacy_dir, state="failed")
        out["warnings"].append("空き容量が足りないため、データを %s へ移せませんでした(必要 約%dMB・空き 約%dMB)。以前の場所(%s)のまま動きます"
                               % (new, (need + SPACE_MARGIN) // 2**20, free // 2**20, legacy_dir))
        return out
    say("作業データを %s へコピーしています(約%dMB。元の %s は消しません)…" % (new, need // 2**20, legacy_dir))
    copied, total = [], 0
    for n in todo:
        try:
            b, _ = _copy_item(os.path.join(legacy_dir, n), os.path.join(new, n))
        except (OSError, shutil.Error) as e:
            # 今回写した分は消す(以前の場所のまま動く間に古くなるので、次に写すときに新しい方を写し直す)
            for c in copied:
                p = os.path.join(new, c)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else _try_remove(p)
            out.update(dir=legacy_dir, state="failed")
            out["warnings"].append("データのコピーに失敗したため、以前の場所(%s)のまま動きます(%s: %s)" % (legacy_dir, n, e))
            return out
        copied.append(n)
        total += b
    _write_marker(new, legacy_dir, copied, total)
    out.update(state="migrated", migrated=copied)
    say("コピーしました: %s(元のデータは %s に残っています。確かめてから消してください)" % (", ".join(copied), legacy_dir))
    return out


def _write_marker(d, legacy, items, total):
    m = {"from": legacy, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "items": items, "bytes": total}
    tmp = os.path.join(d, MARKER + PART + "%d" % os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(d, MARKER))
