"""友人の PC の古い作業データ(old_root)から、初回の取得の表(fetch.json)に載った物を新しい作業データ(new_root)へ写す。

写して確かめた物だけ古い方を消す。表に無い物(友人の案件・設定など)には触らない。
展開する物(unzip あり)と base が app の物は対象外。

手順:
  1. plan() で写す候補を決める(古い方がある・大きさが合う・新しい方がまだ無い)
  2. migrate() で候補ごとに、古い方のハッシュ → 一時の名前(.part)へ写す → 写した物のハッシュ → 置き換え → 目録に足す
  3. 全部終えたら、目録の物のうち古い方が写したときのまま(大きさと更新時刻)の物だけ古い方を消し、空になったフォルダを片付ける
     (F3-5: 友人のアプリは写すだけ(remove_old 偽)にして、写し終えたあと 1 回だけ聞く = pending で空く大きさを出し、
     [片付ける] なら clean・[あとで] なら skip(もう聞かない。⚙ からは後で片付けられる)。目録の物だけ消す = 目録に無い物(案件・設定)には触らない)
"""
import hashlib
import json
import os
import shutil
import time

CHUNK = 1 << 20
CATALOG_VERSION = 1
HEX = "0123456789abcdefABCDEF"


def _sha256_file(path):
    """ファイルの sha256 を 16 進の文字列で返す。1MB ずつ読む。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _is_int(v):
    """True/False を除いた整数か。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _good_dest(dest):
    """dest が / 区切りの安全な相対パスか。絶対パス・ドライブ名・.. ・空の区切りは不可。"""
    if not isinstance(dest, str) or not dest:
        return False
    if "\\" in dest or ":" in dest or dest.startswith("/"):
        return False
    return all(part not in ("", ".", "..") for part in dest.split("/"))


def _good_file(name):
    """file が 1 つのファイル名か。/ と \\ を含まない。"""
    return isinstance(name, str) and name not in ("", ".", "..") and "/" not in name and "\\" not in name


def _row(item):
    """表の 1 行を検べ、正しければ使う形に整えて返す。だめなら None。"""
    if not isinstance(item, dict):
        return None
    name, file_, dest, sha = item.get("name"), item.get("file"), item.get("dest"), item.get("sha256")
    size, max_bytes = item.get("size"), item.get("maxBytes")
    if not isinstance(name, str) or not name or not _good_file(file_) or not _good_dest(dest):
        return None
    if item.get("base") != "data" or item.get("unzip") is not None:
        return None
    if not (isinstance(sha, str) and len(sha) == 64 and all(c in HEX for c in sha)):
        return None
    if size is not None and (not _is_int(size) or size < 0):
        return None
    if max_bytes is not None and (not _is_int(max_bytes) or max_bytes < 0):
        return None
    return {"name": name, "file": file_, "dest": dest, "size": size, "maxBytes": max_bytes, "sha256": sha.lower()}


def load_items(fetch_path):
    """fetch.json の対象の行を返す。対象は base が data で unzip が無い行だけ。形の悪い行・危ない dest・file の / や \\・sha256 の形違いは外す。
    ファイルが読めない・形が違うときは空のリスト。"""
    try:
        with open(fetch_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    rows = data.get("items") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for item in rows:
        row = _row(item)
        if row is not None:
            out.append(row)
    return out


def _norm(path):
    """比べるための正規化した絶対パス。"""
    return os.path.normcase(os.path.abspath(path))


def _within(child, parent):
    """child が parent と同じか、その中か。両方とも _norm 済みの前提。"""
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def _nested_or_same(a, b):
    """a と b が同じか、どちらかがもう片方の中か。"""
    na, nb = _norm(a), _norm(b)
    return _within(na, nb) or _within(nb, na)


def plan(items, old_root, new_root):
    """写す候補 [{"name", "old", "new", "size", "sha256"}] を返す。

    候補は次の全部を満たす物: 古い方がファイルとしてある・大きさが合う(size が数なら同じ。null なら 0 < 大きさ <= maxBytes)・
    新しい方のパスがまだ無い。新しい方があれば、大きさが違っても写さない(新しい方の物は壊さない)。
    old_root と new_root が同じ、または片方がもう片方の中なら何もせず空を返す(例外にはしない)。"""
    if _nested_or_same(old_root, new_root):
        return []
    out = []
    for item in items:
        parts = item["dest"].split("/")
        old = os.path.join(old_root, *parts, item["file"])
        new = os.path.join(new_root, *parts, item["file"])
        if os.path.lexists(new) or not os.path.isfile(old):
            continue
        size = os.path.getsize(old)
        if item["size"] is not None:
            if size != item["size"]:
                continue
        elif item["maxBytes"] is None or not (0 < size <= item["maxBytes"]):
            continue
        out.append({"name": item["name"], "old": old, "new": new, "size": size, "sha256": item["sha256"]})
    return out


def _empty_catalog():
    """目録の空の形。"""
    return {"v": CATALOG_VERSION, "files": [], "notice": {"bytes": 0, "shown": False}, "asked": False}


def _load_catalog(path):
    """目録を読む。無い・壊れているときは空の目録(壊れた物は次に書くとき置き換わる。古い方は消されないので安全側)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _empty_catalog()
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return _empty_catalog()
    notice = data.get("notice")
    if not isinstance(notice, dict) or not _is_int(notice.get("bytes")):
        notice = {"bytes": 0, "shown": False}
    return {"v": CATALOG_VERSION,
            "files": [e for e in data["files"] if isinstance(e, dict)],
            "notice": {"bytes": notice["bytes"], "shown": bool(notice.get("shown"))}, "asked": bool(data.get("asked"))}


def _save_catalog(path, data):
    """目録を一時の名前に書いてから置き換える(途中で止まっても壊れた目録にならない)。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def notice(catalog_path):
    """まだ見せていない片付けの知らせ {"bytes": 消した合計} を返す。無ければ None。"""
    n = _load_catalog(catalog_path)["notice"]
    if n["bytes"] > 0 and not n["shown"]:
        return {"bytes": n["bytes"]}
    return None


def pending(catalog_path, old_root):
    """写して同じと確かめた物のうち、まだ古い方が残っている物 -> {"bytes": 消すと空く大きさ, "count": 件数, "asked": もう聞いたか}。
    old_root の外・写したときから変わった物は数えない(clean が消さない物と同じ見方)"""
    cat = _load_catalog(catalog_path)
    root = _norm(old_root) if old_root else None
    n = size = 0
    for e in cat["files"]:
        old, new, sz = e.get("old"), e.get("new"), e.get("size")
        if root is None or not (isinstance(old, str) and isinstance(new, str) and _is_int(sz)):
            continue
        path = _norm(old)
        if path == root or not _within(path, root) or not os.path.isfile(old) or not _unchanged(e, old, new, sz):
            continue
        n += 1
        size += sz
    return {"bytes": size, "count": n, "asked": cat["asked"]}


def clean(catalog_path, old_root, log=None):
    """[片付ける]: 目録の物(写して同じと確かめた物)の古い方だけ消す。-> {"deleted", "freed"}。聞いたことにする"""
    say = log if log is not None else (lambda msg: None)
    cat = _load_catalog(catalog_path)
    deleted, freed = _finish_old(cat, old_root, say) if old_root else (0, 0)
    cat["asked"] = True
    _save_catalog(catalog_path, cat)
    return {"deleted": deleted, "freed": freed}


def skip(catalog_path):
    """[あとで]: もう聞かない(目録が無ければ何もしない。古い方は消さない)"""
    if not os.path.exists(catalog_path):
        return
    cat = _load_catalog(catalog_path)
    cat["asked"] = True
    _save_catalog(catalog_path, cat)


def mark_notice_shown(catalog_path):
    """知らせを見せ済みにする。目録が無ければ何もしない。"""
    if not os.path.exists(catalog_path):
        return
    data = _load_catalog(catalog_path)
    data["notice"]["shown"] = True
    _save_catalog(catalog_path, data)


def _remove_quiet(path):
    """ファイルを消す。無ければ何もしない。"""
    try:
        os.remove(path)
    except OSError:
        pass


def _skip(result, name, reason, say):
    """写さなかった物を結果に残す。"""
    result["skipped"].append({"name": name, "reason": reason})
    say(f"写さない: {name}({reason})")


def _copy_one(cand, check, catalog_path, catalog, result, say):
    """候補 1 つを写す。古い方のハッシュが合い、写した物のハッシュも合ったときだけ置き換えて目録に足す。"""
    old, new, name = cand["old"], cand["new"], cand["name"]
    try:
        st = os.stat(old)
        if check(old) != cand["sha256"]:
            _skip(result, name, "hash-mismatch", say)
            return
    except OSError:
        _skip(result, name, "read-error", say)
        return
    part = new + ".part"
    try:
        os.makedirs(os.path.dirname(new), exist_ok=True)
        with open(old, "rb") as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst, CHUNK)
    except OSError:
        _remove_quiet(part)
        _skip(result, name, "copy-error", say)
        return
    if check(part) != cand["sha256"]:
        _remove_quiet(part)
        _skip(result, name, "copy-mismatch", say)
        return
    try:
        os.replace(part, new)
    except OSError:
        _remove_quiet(part)
        _skip(result, name, "replace-error", say)
        return
    size = os.path.getsize(new)
    catalog["files"] = [e for e in catalog["files"] if e.get("new") != new]
    catalog["files"].append({"name": name, "old": old, "new": new, "size": size, "sha256": cand["sha256"],
                             "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "old_mtime": st.st_mtime})
    _save_catalog(catalog_path, catalog)
    result["copied"] += 1
    result["bytes"] += size
    say(f"写した: {name}({size} バイト)")


def _unchanged(entry, old, new, size):
    """古い方が写したときのまま(大きさと更新時刻)で、新しい方も同じ大きさで在るか。"""
    if not (os.path.isfile(new) and os.path.getsize(new) == size and os.path.getsize(old) == size):
        return False
    return os.path.getmtime(old) == entry.get("old_mtime")


def _drop_empty_folders(folder, root):
    """folder から上へ、空のフォルダを root の手前まで消す。root そのものは消さない。"""
    folder = _norm(folder)
    while folder != root and _within(folder, root):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)


def _finish_old(catalog, old_root, say):
    """目録の物のうち、写したときのままで新しい方もある古い方だけ消す。消した物は目録から外す。
    古い方が old_root の外、または確かめられないときは消さずに目録に残す。"""
    deleted = freed = 0
    keep = []
    root = _norm(old_root)
    for entry in catalog["files"]:
        old, new, size = entry.get("old"), entry.get("new"), entry.get("size")
        if not (isinstance(old, str) and isinstance(new, str) and _is_int(size)):
            continue
        path = _norm(old)
        if path == root or not _within(path, root):
            keep.append(entry)
            continue
        if not os.path.isfile(old):
            continue
        if not _unchanged(entry, old, new, size):
            keep.append(entry)
            continue
        try:
            os.remove(old)
        except OSError:
            keep.append(entry)
            continue
        deleted += 1
        freed += size
        say(f"古い方を消した: {entry.get('name')}({size} バイト)")
        _drop_empty_folders(os.path.dirname(old), root)
    catalog["files"] = keep
    return deleted, freed


def migrate(fetch_path, old_root, new_root, catalog_path, log=None, cancelled=None, hasher=None, remove_old=True):
    """古い作業データから表の対象を新しい作業データへ写し、写して確かめた物の古い方を消す。

    結果は {"copied", "bytes", "deleted", "freed", "skipped": [{"name", "reason"}]}。
    cancelled() が真になったら次の候補へ進まず、そこまでの結果を返す(消す段は写し終えて目録にある物だけ)。
    old_root と new_root が同じ・入れ子なら何もしない。2 回目は写す物も消す物も無いので何もしない。
    hasher(path) は sha256 の 16 進を返す(既定は _sha256_file)。log(文) は進みの知らせ。
    remove_old が偽なら古い方は消さない(目録には残る = あとで真にして呼べば、そのとき消す)。
    目録は各 1 件写すたびに書き、消した物は目録から外し、消した合計を notice に足す(その回は見せていない扱いに戻す)。"""
    say = log if log is not None else (lambda msg: None)
    stop = cancelled if cancelled is not None else (lambda: False)
    check = hasher if hasher is not None else _sha256_file
    result = {"copied": 0, "bytes": 0, "deleted": 0, "freed": 0, "skipped": []}
    if _nested_or_same(old_root, new_root):
        return result
    catalog = _load_catalog(catalog_path)
    before = json.dumps(catalog, sort_keys=True)
    for cand in plan(load_items(fetch_path), old_root, new_root):
        if stop():
            say("途中で止めた")
            break
        _copy_one(cand, check, catalog_path, catalog, result, say)
    deleted, freed = _finish_old(catalog, old_root, say) if remove_old else (0, 0)   # remove_old 偽 = 写すだけ(古いアプリと並べて使う間)
    result["deleted"], result["freed"] = deleted, freed
    if freed:
        catalog["notice"]["bytes"] += freed
        catalog["notice"]["shown"] = False
    if json.dumps(catalog, sort_keys=True) != before:
        _save_catalog(catalog_path, catalog)
    return result
