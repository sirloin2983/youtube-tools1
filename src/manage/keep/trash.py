# -*- coding: utf-8 -*-
"""④ データの keep: ごみ箱フォルダへ移す・戻すの 1 か所(OPT-M2。notes:plan/done/opt-manage.md の 7c-1・2c-1)。

片付けの move(manage/keep/cleanup.Cleanup)と案件の「要らない」(manage/cases/cases.discard_clip。友人の「要らない」も)が同じこれを呼ぶ。
置き場所は ごみ箱\\<日付>\\<種類>\\<名前>\\(作業用 の物は その中の 作業用\\)。どのごみ箱フォルダかは Cleanup.trash_for(動画と同じドライブ)。
移した物は <日付>\\manifest.jsonl に元の場所を 1 行ずつ残す(戻したいときに見る。TRASH_DAYS を過ぎると起動時の purge で日付のフォルダごと消える)。

戻すとき(設計原則の指摘 1): 戻せた物と戻せなかった物を分けて返し、**戻せずにごみ箱に残った物は必ず manifest に元の場所を書く**
(「片付けませんでした」と画面に出た物がごみ箱にあり、記録も無いまま 3 日で消える、を作らない)。戻したあとの空のフォルダは消す。
"""
import os
import shutil
import time

from ytt import fsio, schemas, tools, trashbin

# 名前と記録の形は ytt/trashbin の 1 か所(① の録画の部品も同じ物を使う。LD-1)
MANIFEST = trashbin.MANIFEST
free_path = trashbin.free_path
append_manifest = trashbin.append_manifest


def _size(p):
    try:
        return fsio.dir_size(p)[0]
    except OSError:
        return None


def to_trash(trash, files, kind, name=None, all_or_nothing=False, need_first=False, record=True, clock=time.time, log=None):
    """files(ファイルかフォルダのパス)を trash.trash_for(最初の物) の ごみ箱\\<日付>\\<kind>\\[<name>\\] へ移す。
    name が無ければ <kind>\\ の直下へ。作業用\\ の中の物は 移した先の 作業用\\ へ。
    all_or_nothing: 1 つでも移せなければ、移した物を戻して終わる(戻せなかった物は manifest に書く)。
    need_first: 最初の物が移せなければ、ほかは移さない(片付けの元動画)。record: 移した物を manifest に書く(False なら呼び手が record を呼ぶ)。
    -> {"moved": [(元, 先)], "failed": [(元, 理由)], "restored": [(元, 先)], "left": [(元, 先)], "dest": 移した先のフォルダ, "day": 日付のフォルダ,
        "kind": kind}。存在しない物は飛ばす。フォルダを作れないなど全体が失敗すれば failed に全部"""
    log = log or (lambda m: None)
    files = [p for p in files if p and os.path.lexists(p)]
    res = {"moved": [], "failed": [], "restored": [], "left": [], "dest": "", "day": "", "kind": kind, "clock": clock}
    if not files:
        return res
    root = trash.trash_for(files[0])
    res["day"] = os.path.join(root, trashbin.day_name(clock()))
    base = os.path.join(res["day"], kind)
    try:
        dest = free_path(os.path.join(base, name)) if name else base
        os.makedirs(dest, exist_ok=True)
    except OSError as e:
        res["failed"] = [(p, tools.why(e)) for p in files]
        return res
    res["dest"] = dest
    for i, p in enumerate(files):
        sub = schemas.WORK_DIR if os.path.basename(os.path.dirname(p.rstrip("\\/"))) == schemas.WORK_DIR and name else ""
        try:
            d = os.path.join(dest, sub) if sub else dest
            os.makedirs(d, exist_ok=True)
            to = free_path(os.path.join(d, os.path.basename(p.rstrip("\\/"))))
            shutil.move(p, to)   # 同じドライブなら改名、別のドライブなら写して消す
            res["moved"].append((p, to))
        except (OSError, shutil.Error) as e:
            res["failed"].append((p, tools.why(e)))
            log("ごみ箱: %s を移せませんでした: %r" % (p, e))
            if all_or_nothing:
                put_back(res, log=log)
                break
            if need_first and i == 0:
                break
    if res["moved"] or res["left"]:
        try:   # 作業データ・書き出し先の外のごみ箱フォルダも、起動時に消す一覧へ
            trash.remember_root(root)
        except OSError:
            pass
    if record and res["moved"]:
        _record(res, res["moved"])
    if not res["moved"] and not res["left"]:
        _prune(res)
    return res


def record(res):
    """移した物(res["moved"])を manifest に書く(to_trash(record=False) のあと、続きの仕事が済んでから)。書けなければログだけ"""
    if res.get("moved"):
        _record(res, res["moved"])


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
            os.makedirs(os.path.dirname(src), exist_ok=True)   # 元の 作業用\ が消えていても戻す(戻せない物を減らす)
            shutil.move(to, src)
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
            os.rmdir(d)
        except OSError:
            pass
