# -*- coding: utf-8 -*-
"""ごみ箱フォルダの 1 か所(形と、移す・戻す・古い日付を消す動作)。どの層からも使う(① の録画の部品・④ の片付けと「要らない」・友人のアプリ)ので ytt に置く。

ごみ箱フォルダの中は <YYYY-MM-DD>/<種類>/... の日付のフォルダ。移した物は <日付>/manifest.jsonl に元の場所を 1 行ずつ残す(戻したいときに見る)。
何日で消すかは ② の flow/retention.KEEP_DAYS(呼ぶ側が渡す)。どのごみ箱フォルダへ移すか(動画と同じドライブなど)も呼ぶ側が決める。

戻すとき: 戻せた物と戻せなかった物を分けて返し、**戻せずにごみ箱に残った物は必ず manifest に元の場所を書く**
(「片付けませんでした」と画面に出た物がごみ箱にあり、記録も無いまま日数で消える、を作らない)。戻したあとの空のフォルダは消す。
OS を呼ぶ所は fsio.long_path で包む(260 文字を超えるパスも動かす)。記録と戻り値は元のパスのまま。
"""
import json
import os
import re
import shutil
import time

from . import fsio, schemas, tools

MANIFEST = "manifest.jsonl"
TRASH_DIR = "ごみ箱"     # ごみ箱フォルダの名前(作業データ・書き出し先・録画の置き場所・友人のアプリの一時保管と home の直下)
_DAY8 = re.compile(r"\d{8}")


def day_name(now=None):
    """日付のフォルダの名前(手元の時刻の YYYY-MM-DD)"""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))


def _exists(p):
    return os.path.lexists(fsio.long_path(p))


def free_path(dest, first=1, check=None):
    """同じ名前があれば (1) (2) … を付ける。first = 最初に付ける番号・check = 「ある」の判定(既定は長いパスでも見る lexists)"""
    check = check or _exists
    k, (base, ext) = first, os.path.splitext(dest)
    while check(dest):
        dest = "%s (%d)%s" % (base, k, ext)
        k += 1
    return dest


def append_manifest(day_dir, rows):
    """ごみ箱フォルダの <日付>/manifest.jsonl に、移した物の元の場所を 1 行ずつ足す(rows = [{from, to, at, kind, ...}]。戻したいときに見る)。
    書けなければ OSError"""
    with open(fsio.long_path(os.path.join(day_dir, MANIFEST)), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _day_of(name):
    """日付のフォルダの名前 → その日の 0 時(epoch)か None。YYYY-MM-DD(頭 10 文字)と YYYYMMDD(友人のアプリの古い置き方)を読む"""
    for text, fmt in ((name[:10], "%Y-%m-%d"), (name if _DAY8.fullmatch(name) else "", "%Y%m%d")):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    return None


def old_day_dirs(root, days, now):
    """root の直下の日付のフォルダのうち、その日が終わってから days 日たったもの -> [(名前, パス)](その日の最後に入れた物も days 日は残る)。
    root を読めなければ []。日付でない名前・ファイルは飛ばす(受付済み と ごみ箱フォルダの両方の決まり)"""
    try:
        names = os.listdir(fsio.long_path(root))
    except OSError:
        return []
    out = []
    for name in names:
        p = os.path.join(root, name)
        if not os.path.isdir(fsio.long_path(p)):
            continue
        day = _day_of(name)
        if day is not None and now - (day + 86400) >= days * 86400:
            out.append((name, p))
    return out


def purge(root, days, now=None, log=None):
    """root(ごみ箱フォルダ)の days 日を過ぎた日付のフォルダを丸ごと消す。root がリンクなら触らない。-> 消した日付のフォルダの名前の一覧"""
    if not root or fsio.is_link(root):
        return []
    gone = []
    for name, p in old_day_dirs(root, days, time.time() if now is None else now):
        shutil.rmtree(fsio.long_path(p), ignore_errors=True)
        if not os.path.isdir(fsio.long_path(p)):
            gone.append(name)
            if log:
                log("ごみ箱フォルダの %s を消しました(%d 日を過ぎた)" % (name, days))
    return gone


def _size(p):
    try:
        return fsio.dir_size(p)[0]
    except OSError:
        return None


def to_trash(trash, files, kind, name=None, all_or_nothing=False, need_first=False, record=True, clock=time.time, log=None):
    """files(ファイルかフォルダのパス)を ごみ箱\\<日付>\\<kind>\\[<name>\\] へ移す。
    trash = ごみ箱フォルダのパス(文字列)か、trash_for(最初の物) でそれを答える物(remember_root(根) があれば、移したあとに呼ぶ = 起動時に消す一覧へ)。
    kind は "整理\\古い版" のように区切りを含んでよい。name が無ければ <kind>\\ の直下へ。作業用\\ の中の物は 移した先の 作業用\\ へ。
    all_or_nothing: 1 つでも移せなければ、移した物を戻して終わる(戻せなかった物は manifest に書く)。
    need_first: 最初の物が移せなければ、ほかは移さない(片付けの元動画)。record: 移した物を manifest に書く(False なら呼び手が record を呼ぶ)。
    -> {"moved": [(元, 先)], "failed": [(元, 理由)], "restored": [(元, 先)], "left": [(元, 先)], "dest": 移した先のフォルダ, "day": 日付のフォルダ,
        "kind": kind}。存在しない物は飛ばす。フォルダを作れないなど全体が失敗すれば failed に全部"""
    log = log or (lambda m: None)
    files = [p for p in files if p and _exists(p)]
    res = {"moved": [], "failed": [], "restored": [], "left": [], "dest": "", "day": "", "kind": kind, "clock": clock}
    if not files:
        return res
    root = trash if isinstance(trash, str) else trash.trash_for(files[0])
    res["day"] = os.path.join(root, day_name(clock()))
    base = os.path.join(res["day"], kind)
    try:
        dest = free_path(os.path.join(base, name)) if name else base
        os.makedirs(fsio.long_path(dest), exist_ok=True)
    except OSError as e:
        res["failed"] = [(p, tools.why(e)) for p in files]
        return res
    res["dest"] = dest
    for i, p in enumerate(files):
        sub = schemas.WORK_DIR if os.path.basename(os.path.dirname(p.rstrip("\\/"))) == schemas.WORK_DIR and name else ""
        try:
            d = os.path.join(dest, sub) if sub else dest
            os.makedirs(fsio.long_path(d), exist_ok=True)
            to = free_path(os.path.join(d, os.path.basename(p.rstrip("\\/"))))
            shutil.move(fsio.long_path(p), fsio.long_path(to))   # 同じドライブなら改名、別のドライブなら写して消す
            res["moved"].append((p, to))
        except (OSError, shutil.Error) as e:
            res["failed"].append((p, tools.why(e)))
            log("ごみ箱: %s を移せませんでした: %r" % (p, e))
            if all_or_nothing:
                put_back(res, log=log)
                break
            if need_first and i == 0:
                break
    if (res["moved"] or res["left"]) and hasattr(trash, "remember_root"):
        try:   # 作業データ・書き出し先の外のごみ箱フォルダも、起動時に消す一覧へ
            trash.remember_root(root)
        except OSError:
            pass
    if record and res["moved"]:
        _record(res, res["moved"])
    if not res["moved"] and not res["left"]:
        _prune(res)
    return res


def record(res, **extra):
    """移した物(res["moved"])を manifest に書く(to_trash(record=False) のあと、続きの仕事が済んでから)。書けなければログだけ"""
    if res.get("moved"):
        _record(res, res["moved"], **extra)


def _record(res, pairs, **extra):
    at = int(res["clock"]() * 1000)
    try:
        append_manifest(res["day"], [dict({"from": src, "to": to, "at": at, "kind": res["kind"], "bytes": _size(to)}, **extra) for src, to in pairs])
        return True
    except OSError:   # 書けなくても、移した物は ごみ箱フォルダ の中にある
        return False


def put_back(res, log=None):
    """移した物(res["moved"])を元の場所へ戻す(新しい順に)。戻せた物は res["restored"]・戻せなかった物は res["left"] へ(moved は空に)。
    戻せなかった物は manifest に元の場所を必ず書く(leftBehind: true)。戻したあとの空のフォルダは消す。-> res"""
    log = log or (lambda m: None)
    for src, to in reversed(res["moved"]):
        try:
            os.makedirs(fsio.long_path(os.path.dirname(src)), exist_ok=True)   # 元の 作業用\ が消えていても戻す(戻せない物を減らす)
            shutil.move(fsio.long_path(to), fsio.long_path(src))
            res["restored"].append((src, to))
        except (OSError, shutil.Error) as e:
            res["left"].append((src, to))
            log("ごみ箱: %s を元へ戻せませんでした(ごみ箱の %s に残っています): %r" % (src, to, e))
    res["moved"] = []
    if res["left"] and not _record(res, res["left"], leftBehind=True):
        log("ごみ箱: 戻せなかった物の元の場所を manifest に書けませんでした: %s" % ", ".join(src for src, _to in res["left"]))
    _prune(res)
    return res


def _prune(res):
    """移した先のフォルダが空なら消す(作業用\\ → 名前のフォルダ。種類・日付のフォルダは他の物と共有なので残す)"""
    dest = res.get("dest")
    if not dest or os.path.normcase(dest) == os.path.normcase(os.path.join(res.get("day") or "", res.get("kind") or "")):
        return
    for d in (os.path.join(dest, schemas.WORK_DIR), dest):
        try:
            os.rmdir(fsio.long_path(d))
        except OSError:
            pass
