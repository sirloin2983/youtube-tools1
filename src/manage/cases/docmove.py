# -*- coding: utf-8 -*-
"""④ 文字起こしの文書を案件の 作業用 へ移す(RS8 B2-3。決定は plan/rs8-cases-ui.md の「B-2 の移し方」)。

入口が起動のとき(.flow.lock を取った直後・待ち受けの前 = CLI・画面の書き込みとぶつからない)に run を 1 回呼ぶ。
データを失わない向きにいつも倒す: コピー → 確かめる → 改名 → 索引(ytt/docloc の place)→ 元は transcripts/.migrated/ へ改名して残す。上書きしない。

- 対象: transcripts/<id>.json のうち、元の動画(sourcePath)が書き出し先(スタジオの outDir)の下の案件にあり、その案件に
  作業用/.studio-id か 作業用/case.json がある物(_doc_home。評価用・動画が無い・ネットワーク上・outDir の外・固定ディスクでない は残す)。
  文書の clip.source.videoId と 作業用/.studio-id が食い違えば移さない(ログ)。clip の無い文書はパスの条件だけで通す
- 1 本ずつ: 文書と横のファイル(docloc.DOC_SUFFIXES)・.hist/<id>/・.bak/<id>.* を <作業用>/<名前>.part-<pid> へコピー
  (別のドライブでもコピー)→ 大きさと中身を比べる・本体は JSON として読めるか → 本来の名前へ改名(本体はいちばん最後)→ docloc.place →
  transcripts の元を transcripts/.migrated/ へ同じドライブの中で改名。作業用に同じ名前が既にあれば、同じ中身なら飛ばして先へ・違えばその文書は移さない
- 2 回目の規則: 索引が通る文書で transcripts に同じ名前が残っていれば(元を送る前に落ちた)、同じ中身なら .migrated へ送る・違えばログ。
  .migrated に同じ名前があれば、同じ中身なら上書き・違えば <名前>.<時刻>
- 前提: バックアップが 1 回済んでいる(入口の backup-state.json の ok)。済んでいなければ移さない(ログと入口の「調子」の 1 行)
- 予算: 1 回の起動で BUDGET_SEC 秒か BUDGET_DOCS 本まで。残りは次の起動に。途中で落ちて残った .part- は次に同じ文書を扱うときに消す
- 結果: <編集の作業データ>/.docs-moved.json(RESULT_NAME。移した本数・残した理由ごとの本数・時刻・paused)

コマンド(入口を終了してから。.flow.lock を取る):
    py -3.10 src/manage/cases/docmove.py --back [--dry-run]   作業用 → transcripts へ写し戻して索引を消す(上書きしない)。自動の移行を止める(paused)
    py -3.10 src/manage/cases/docmove.py --resume             自動の移行を再開する
    py -3.10 src/manage/cases/docmove.py --now                バックアップを待たずに今すぐ移す(y/N。予算なし)
    py -3.10 src/manage/cases/docmove.py --purge-migrated     transcripts/.migrated/ を消す(y/N。画面で本数が合うのを確かめてから)
"""
import argparse
import filecmp
import json
import os
import re
import shutil
import sys
import time

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # cases -> manage -> src
if _SRC not in sys.path:   # コマンドで単独に動かすときも ytt・flow を読めるように(入口から読むときは入っている)
    sys.path.insert(0, _SRC)
from flow import placement as _placement  # noqa: E402
from manage.keep import backup as _backup  # noqa: E402
from ytt import datadir as _datadir, docloc as _docloc, fsio as _fsio, names as _names, schemas as _schemas, settings as _settings  # noqa: E402

RESULT_NAME = ".docs-moved.json"   # <編集の作業データ>/.docs-moved.json
RESULT_VERSION = 1
MIGRATED_DIR = ".migrated"         # transcripts/.migrated/(移した元。--purge-migrated で消す)
PART_MARK = ".part-"               # コピーの途中の名前 <名前>.part-<pid>(バックアップも写さない)
PART_RE = re.compile(r"\.part-\d+$")
BUDGET_SEC = 20.0
BUDGET_DOCS = 50
DOC_MAX = 64 * 1024 * 1024         # 本体をこれより大きければ読まない(読めない扱い = 移さない)
DRIVE_FIXED = 3                    # Windows の GetDriveType の固定ディスク
# 残した理由(結果の kept の鍵)→ 画面とログの文
REASONS = {"eval": "評価用", "noSource": "元の動画が分からない", "noHome": "案件のフォルダでない(書き出し先の外・動画が無い・評価用のフォルダなど)",
           "owner": "案件の持ち主が違う", "conflict": "作業用に違う中身の同じ名前がある", "unseen": "索引はあるが置き場所が見えない",
           "leftover": "移したあとの残りが作業用と違う", "unreadable": "文書が読めない", "error": "移す途中で失敗した"}


class _Conflict(Exception):
    """写す先に違う中身の同じ名前がある(上書きしない)"""


# ---------------------------------------------------------------- 置き場所の判定(B2-2 が入ったら寄せる)
def _fixed_drive(path):
    """path のドライブが固定ディスクか(Windows の GetDriveType。それ以外の OS は真)。ネットワーク上のパスは偽"""
    if os.name != "nt":
        return True
    if _fsio.is_network_path(path):
        return False
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(drive + os.sep) == DRIVE_FIXED
    except (AttributeError, OSError, ValueError):
        return False


def _eval_dirs(data_dir):
    """編集の設定 <data_dir>/settings.json の評価用のフォルダ(入口の起動のときは workdata.SETTINGS がまだ無いので直に読む)"""
    v = _fsio.read_json_or(os.path.join(data_dir, "settings.json"), {}, kind=dict).get("evalDirs")
    return [os.path.abspath(p) for p in v if isinstance(p, str) and os.path.isabs(p) and not _fsio.is_network_path(p)] if isinstance(v, list) else []


def _doc_home(source_path, out_dir=None, eval_dirs=()):
    """元の動画 → 文書を置く <案件>/作業用 か None(transcripts のまま)。
    B2-2 が入ったら寄せる(flow/placement.doc_home と同じ規則の仮の写し): 動画がある・ネットワーク上でない・案件の根が書き出し先の下・
    その案件に 作業用/.studio-id か 作業用/case.json がある・書き出し先が固定ディスク・評価用のフォルダの外"""
    if not isinstance(source_path, str) or not os.path.isabs(source_path) or _fsio.is_network_path(source_path) or _fsio.is_remote_drive(source_path):
        return None
    out_dir = out_dir or _datadir.studio_out_dir()
    if not out_dir or not os.path.isdir(out_dir) or not _fixed_drive(out_dir) or not os.path.isfile(source_path):
        return None
    root = _placement.case_root({"kind": "file", "path": source_path})
    if not root or not _fsio.is_inside(root, out_dir, strict=True):
        return None
    work = os.path.join(root, _schemas.WORK_DIR)
    if not (os.path.isfile(os.path.join(work, _names.OWNER_FILE)) or os.path.isfile(_placement.case_path(root))):
        return None
    if _settings.in_eval_dir(source_path, list(eval_dirs)):
        return None
    return work


def _unseen_why(folder):
    if not isinstance(folder, str) or not os.path.isabs(folder):
        return "索引が読めない"
    if _fsio.is_network_path(folder) or _fsio.is_remote_drive(folder):
        return "ネットワーク上のパス"
    return "フォルダが見えない" if not os.path.isdir(folder) else "文書が無い"


def _unseen(data_dir=None):
    """索引はあるが見えない文書の数と理由 -> {"count", "reasons": {理由: 数}}。B2-2 が入ったら docloc.unseen に寄せる"""
    root = _docloc.tx_root(data_dir)
    out = {"count": 0, "reasons": {}}
    try:
        names = sorted(os.listdir(root)) if root else []
    except OSError:
        return out
    for n in names:
        tid = n[:-len(_docloc.LOC_SUFFIX)] if n.endswith(_docloc.LOC_SUFFIX) else ""
        if not _schemas.TID_RE.match(tid) or _docloc.placed(tid, data_dir):
            continue
        d = _fsio.read_json_or(os.path.join(root, n), None, _docloc.LOC_MAX_BYTES, kind=dict)
        why = _unseen_why(d.get("dir") if d else None)
        out["count"] += 1
        out["reasons"][why] = out["reasons"].get(why, 0) + 1
    return out


# ---------------------------------------------------------------- ファイルの小道具
def _same(a, b):
    try:
        return os.path.isfile(a) and os.path.isfile(b) and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _items(root, tid):
    """文書 tid のファイル(root からの相対パス): 横のファイル・.hist/<id>/ の中・.bak/<id>.*、最後に本体 <id>.json。途中の .part- は入れない"""
    main = tid + ".json"
    out = [tid + s for s in _docloc.DOC_SUFFIXES if tid + s != main and os.path.isfile(os.path.join(root, tid + s))]
    for d, dirs, files in os.walk(os.path.join(root, _docloc.HIST_DIR, tid)):
        dirs[:] = sorted(x for x in dirs if not os.path.islink(os.path.join(d, x)))
        out += [os.path.relpath(os.path.join(d, n), root) for n in sorted(files)
                if not PART_RE.search(n) and not os.path.islink(os.path.join(d, n))]
    bak = os.path.join(root, _docloc.BAK_DIR)
    try:
        names = sorted(os.listdir(bak))
    except OSError:
        names = []
    out += [os.path.join(_docloc.BAK_DIR, n) for n in names if n.startswith(tid + ".") and not PART_RE.search(n) and os.path.isfile(os.path.join(bak, n))]
    if os.path.isfile(os.path.join(root, main)):
        out.append(main)
    return out


def _clean_parts(folder, tid):
    """前に落ちて残った tid のコピーの途中(<名前>.part-<pid>)を消す -> 消した数"""
    n = 0
    for d in (folder, os.path.join(folder, _docloc.BAK_DIR)):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for x in names:
            if x.startswith(tid + ".") and PART_RE.search(x):
                _fsio.unlink_quiet(os.path.join(d, x))
                n += 1
    for d, _dirs, files in os.walk(os.path.join(folder, _docloc.HIST_DIR, tid)):
        for x in files:
            if PART_RE.search(x):
                _fsio.unlink_quiet(os.path.join(d, x))
                n += 1
    return n


def _rename_new(src, dst):
    """src を dst へ改名(同じフォルダの中)。dst が既にあれば上げる(上書きしない)"""
    if os.path.lexists(dst):
        raise FileExistsError(dst)
    os.rename(src, dst)


def _check_json(path):
    with open(path, "rb") as f:
        json.loads(f.read().decode("utf-8-sig"))


def _stage(src_root, dst_root, rels, pid):
    """rels を dst_root へ <名前>.part-<pid> の名前でコピーして確かめる -> [(途中の名前, 本来の名前)]。
    dst_root に同じ中身が既にある物は入れない(飛ばす)。違う中身があれば何も写さずに _Conflict。確かめで落ちたら途中の物を消して上げる"""
    todo = []
    for rel in rels:
        dst = os.path.join(dst_root, rel)
        if os.path.lexists(dst):
            if not _same(os.path.join(src_root, rel), dst):
                raise _Conflict(rel)
            continue
        todo.append(rel)
    staged = []
    try:
        for rel in todo:
            src, dst = os.path.join(src_root, rel), os.path.join(dst_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            part = dst + PART_MARK + str(pid)
            staged.append((part, dst))
            shutil.copy2(src, part)
            if os.path.getsize(part) != os.path.getsize(src) or not _same(src, part):
                raise OSError("コピーの中身が合いません: %s" % rel)
            if rel.endswith(".json") and _schemas.TID_RE.match(rel[:-5]):   # 本体は JSON として読めること
                _check_json(part)
        if sum(1 for p, _ in staged if os.path.isfile(p)) != len(todo):
            raise OSError("コピーの本数が合いません")
    except BaseException:
        for p, _ in staged:
            _fsio.unlink_quiet(p)
        raise
    return staged


def _commit(staged):
    """途中の名前を本来の名前へ(並びのとおり = 本体がいちばん最後)。落ちたら残りの途中の物を消して上げる"""
    for i, (part, dst) in enumerate(staged):
        try:
            _rename_new(part, dst)
        except BaseException:
            for p, _ in staged[i:]:
                _fsio.unlink_quiet(p)
            raise


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def _retire_one(root, rel):
    """transcripts/<rel> を transcripts/.migrated/<rel> へ改名(同じドライブ)。同じ中身が既にあれば上書き・違えば <名前>.<時刻>"""
    src = os.path.join(root, rel)
    dst = os.path.join(root, MIGRATED_DIR, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst) and not _same(src, dst):
        base, n = dst + "." + _stamp(), 1
        dst = base
        while os.path.lexists(dst):
            n += 1
            dst = "%s-%d" % (base, n)
    _fsio.replace_retry(src, dst)


def _drop_empty_hist(root, tid):
    for d, _dirs, _files in os.walk(os.path.join(root, _docloc.HIST_DIR, tid), topdown=False):
        try:
            os.rmdir(d)
        except OSError:
            pass


def _retire(root, tid, rels):
    for rel in rels:   # 本体がいちばん最後(本体が残っていれば次の起動で 2 回目の規則が拾う)
        _retire_one(root, rel)
    _drop_empty_hist(root, tid)


# ---------------------------------------------------------------- 1 本ずつ
def _leftover(ctx, tid, work):
    """索引が通る文書で transcripts に残った物: 作業用と同じ中身なら .migrated へ・違えば残してログ -> "cleaned" か "leftover" """
    root = ctx["root"]
    _clean_parts(work, tid)
    rels = _items(root, tid)
    same = [r for r in rels if _same(os.path.join(root, r), os.path.join(work, r))]
    diff = [r for r in rels if r not in same]
    _retire(root, tid, same)
    if diff:
        ctx["log"]("文書 %s: 案件のフォルダと中身の違う物が transcripts に残っています(動かしません): %s" % (tid, "・".join(diff[:5])))
        return "leftover"
    return "cleaned"


def _read_doc(path):
    d = _fsio.read_json_or(path, None, DOC_MAX, kind=dict)
    return d if isinstance(d, dict) else None


def _owner_ok(doc, work):
    vid = ((doc.get("clip") or {}).get("source") or {}).get("videoId") if isinstance(doc.get("clip"), dict) else None
    owner = _names.read_owner(os.path.dirname(work))
    return not (isinstance(vid, str) and vid and owner and owner != vid)


def _move_one(ctx, tid):
    """文書 1 本 -> "moved"・"cleaned" か残した理由(REASONS の鍵)"""
    root, data_dir = ctx["root"], ctx["data_dir"]
    if os.path.isfile(_docloc.loc_path(tid, data_dir)):
        work = _docloc.placed(tid, data_dir)
        return _leftover(ctx, tid, work) if work else "unseen"
    doc = _read_doc(os.path.join(root, tid + ".json"))
    if doc is None:
        return "unreadable"
    if doc.get("evalSet") is True:
        return "eval"
    if not isinstance(doc.get("sourcePath"), str) or not doc["sourcePath"]:
        return "noSource"
    work = ctx["home"](doc["sourcePath"], ctx["out_dir"], ctx["eval_dirs"])
    if not work:
        return "noHome"
    if not _owner_ok(doc, work):
        ctx["log"]("文書 %s: 案件の持ち主(%s)と文書の配信が違うので移しません" % (tid, os.path.dirname(work)))
        return "owner"
    _clean_parts(work, tid)
    rels = _items(root, tid)
    try:
        staged = _stage(root, work, rels, ctx["pid"])
    except _Conflict as e:
        ctx["log"]("文書 %s: 案件の作業用に違う中身の %s があるので移しません" % (tid, e))
        return "conflict"
    _commit(staged)
    _docloc.place(tid, work, data_dir)
    _retire(root, tid, rels)
    ctx["log"]("文書 %s を案件のフォルダへ移しました(%d 個): %s" % (tid, len(rels), work))
    return "moved"


# ---------------------------------------------------------------- 結果の記録
def result_path(data_dir):
    return os.path.join(data_dir, RESULT_NAME)


def read_result(data_dir):
    return _fsio.read_json_or(result_path(data_dir), {}, 64 * 1024, kind=dict)


def _write_result(data_dir, d):
    try:
        _fsio.write_json(result_path(data_dir), d)
    except OSError as e:
        return str(e)
    return None


def set_paused(data_dir, paused):
    d = dict(read_result(data_dir), version=RESULT_VERSION, paused=bool(paused), pausedAt=int(time.time() * 1000) if paused else None)
    _fsio.write_json(result_path(data_dir), d)
    return d


def backup_done(state):
    """入口のバックアップの記録(backup-state.json の中身)で 1 回写し終えたか"""
    return isinstance(state, dict) and isinstance(state.get("ok"), (int, float)) and not isinstance(state.get("ok"), bool)


def _candidates(root):
    try:
        names = os.listdir(root) if root else []
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and _schemas.TID_RE.match(n[:-5]))


def run(data_dir, out_dir=None, backup_ok=False, log=None, budget_sec=BUDGET_SEC, budget_docs=BUDGET_DOCS, clock=time.monotonic, home=None):
    """transcripts の文書を案件の 作業用 へ移す(予算まで)。-> 結果(dict。state = done・partial・waitBackup・paused・empty)。
    data_dir = 編集の作業データ(<data_dir>/transcripts が文書の根)・out_dir = スタジオの書き出し先(None = 設定)・
    budget_docs = 1 回に移す本数の上限(None = なし)・home = 置き場所の判定(テスト用。既定 _doc_home)"""
    log = log or (lambda msg: None)
    prev = read_result(data_dir)
    if prev.get("paused"):
        return dict(prev, state="paused")
    root = _docloc.tx_root(data_dir)
    tids = _candidates(root)
    if not tids:
        return {"state": "empty", "moved": 0}
    if not backup_ok:
        log("文書を案件のフォルダへ移すのは、バックアップが 1 回済んでからにします(今回は移しません。transcripts の文書 %d 本)" % len(tids))
        return {"state": "waitBackup", "moved": 0, "docs": len(tids)}
    ctx = {"root": root, "data_dir": data_dir, "out_dir": out_dir or _datadir.studio_out_dir(), "eval_dirs": _eval_dirs(data_dir),
           "pid": os.getpid(), "log": log, "home": home or _doc_home}
    t0, kept, moved, cleaned, remaining = clock(), {}, 0, 0, 0
    for i, tid in enumerate(tids):
        if clock() - t0 > budget_sec or (budget_docs is not None and moved >= budget_docs):
            remaining = len(tids) - i
            break
        try:
            r = _move_one(ctx, tid)
        except Exception as e:   # 1 本の失敗で止めない(元は transcripts に残っている)
            log("文書 %s を移せませんでした: %s %s" % (tid, e.__class__.__name__, str(e)[:200]))
            r = "error"
        if r == "moved":
            moved += 1
        elif r == "cleaned":
            cleaned += 1
        else:
            kept[r] = kept.get(r, 0) + 1
    out = {"version": RESULT_VERSION, "at": int(time.time() * 1000), "state": "partial" if remaining else "done", "paused": False,
           "moved": moved, "movedTotal": int(prev.get("movedTotal") or 0) + moved, "cleaned": cleaned, "kept": kept,
           "remaining": remaining, "seconds": round(clock() - t0, 1)}
    err = _write_result(data_dir, out)
    log("文書の移行: 案件のフォルダへ %d 本・残り物を片付けた %d 本・残した %d 本%s%s" % (
        moved, cleaned, sum(kept.values()), "(%s)" % "・".join("%s %d" % (REASONS.get(k, k), v) for k, v in sorted(kept.items())) if kept else "",
        "。続きの %d 本は次の起動で" % remaining if remaining else ""))
    if err:
        log("文書の移行: 結果を書けませんでした(%s)" % err)
    return out


def status(data_dir, last=None):
    """入口の「調子」の 1 行の材料。何も無ければ None(行を出さない)"""
    d = read_result(data_dir)
    unseen = _unseen(data_dir)
    last = last if isinstance(last, dict) else {}
    if not d and not unseen["count"] and last.get("state") != "waitBackup":
        return None
    state = "paused" if d.get("paused") else last.get("state") if last.get("state") == "waitBackup" else d.get("state") or "done"
    return {"state": state, "moved": int(d.get("movedTotal") or 0), "movedNow": int(last.get("moved") or 0), "kept": dict(d.get("kept") or {}),
            "remaining": int(d.get("remaining") or 0), "at": d.get("at"), "unseen": unseen,
            "reasons": {k: REASONS[k] for k in REASONS}, "docs": last.get("docs")}


# ---------------------------------------------------------------- 戻す
def back(data_dir, dry_run=False, log=None):
    """作業用 → transcripts へ写し戻して索引を消す(上書きしない。作業用の写しは残す)。先に paused を書く(自動の移行を止める)。
    log = 1 行ずつ書く先(None = print)。-> {"back": 戻した本数, "kept": {理由: 数}}"""
    log = log or print
    root = _docloc.tx_root(data_dir)
    if not dry_run:
        set_paused(data_dir, True)
    out = {"back": 0, "kept": {}}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    pid = os.getpid()
    for n in names:
        tid = n[:-len(_docloc.LOC_SUFFIX)] if n.endswith(_docloc.LOC_SUFFIX) else ""
        if not _schemas.TID_RE.match(tid):
            continue
        work = _docloc.placed(tid, data_dir)
        why = None
        if not work:
            why = "unseen"
        else:
            rels = _items(work, tid)
            try:
                staged = [] if dry_run else _stage(work, root, rels, pid)
                if dry_run and any(os.path.lexists(os.path.join(root, r)) and not _same(os.path.join(work, r), os.path.join(root, r)) for r in rels):
                    raise _Conflict("")
            except _Conflict:
                why = "conflict"
            except OSError as e:
                log("文書 %s を戻せませんでした: %s" % (tid, e))
                why = "error"
        if why:
            out["kept"][why] = out["kept"].get(why, 0) + 1
            log("文書 %s は戻しません(%s)" % (tid, REASONS[why]))
            continue
        if not dry_run:
            _commit(staged)
            _docloc.unplace(tid, data_dir)
        out["back"] += 1
        log("文書 %s を transcripts へ%s(%d 個): %s" % (tid, "戻せます" if dry_run else "戻しました", len(rels), work))
    return out


def purge_migrated(data_dir):
    """transcripts/.migrated/ を消す -> 消したファイルの数(無ければ 0)"""
    d = os.path.join(_docloc.tx_root(data_dir), MIGRATED_DIR)
    if not os.path.isdir(d):
        return 0
    n = _fsio.dir_size(d)[1]
    shutil.rmtree(d)
    return n


# ---------------------------------------------------------------- コマンド
def _ask(prompt, ask):
    try:
        return ask(prompt + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _backup_state():
    return _fsio.read_json_or(os.path.join(_datadir.resolve("app"), _backup.STATE_FILE), {}, _backup.STATE_MAX, kind=dict)


def main(argv=None, ask=input):
    ap = argparse.ArgumentParser(prog="docmove.py", description="文字起こしの文書を案件のフォルダ(作業用)へ移す・戻す(入口を終了してから)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--back", action="store_true", help="作業用 → transcripts へ写し戻して索引を消す(上書きしない)。自動の移行を止める")
    g.add_argument("--resume", action="store_true", help="止めた自動の移行を再開する")
    g.add_argument("--now", action="store_true", help="バックアップを待たずに今すぐ移す(予算なし)")
    g.add_argument("--purge-migrated", action="store_true", help="transcripts/.migrated/(移した元)を消す")
    ap.add_argument("--dry-run", action="store_true", help="--back で、何を戻すかだけ表示する")
    a = ap.parse_args(argv)
    data_dir = _datadir.resolve("transcribe")
    try:
        lock = _placement.acquire(None)
    except _placement.LockBusy as e:
        print("入口(または別のコマンド)が同じ作業データを使っています(pid %s)。入口を「すべて終了」してから流してください" % e.info.get("pid"))
        return 4
    try:
        return _main(a, data_dir, ask)
    finally:
        _placement.release(lock)


def _main(a, data_dir, ask):
    print("編集の作業データ: %s" % data_dir)
    if a.resume:
        set_paused(data_dir, False)
        print("自動の移行を再開します(次の入口の起動から)")
        return 0
    if a.back:
        r = back(data_dir, dry_run=a.dry_run)
        print("%s %d 本・戻さない %d 本%s" % ("戻せる" if a.dry_run else "戻した", r["back"], sum(r["kept"].values()),
                                          "" if a.dry_run else "。自動の移行は止めました(再開は --resume)"))
        return 0
    if a.purge_migrated:
        d = os.path.join(_docloc.tx_root(data_dir), MIGRATED_DIR)
        n = _fsio.dir_size(d)[1] if os.path.isdir(d) else 0
        if not n or not _ask("%s のファイル %d 個を消します。画面で文書の本数が合うのを確かめましたか" % (d, n), ask):
            print("消しませんでした")
            return 0
        print("消しました: %d 個" % purge_migrated(data_dir))
        return 0
    if read_result(data_dir).get("paused"):
        print("自動の移行は止めてあります。先に --resume で再開してください")
        return 1
    note = "" if backup_done(_backup_state()) else "(バックアップがまだ 1 回も済んでいません)"
    if not _ask("transcripts の文書を案件のフォルダ(作業用)へ今すぐ移します%s。よいですか" % note, ask):
        print("移しませんでした")
        return 0
    r = run(data_dir, backup_ok=True, log=print, budget_sec=float("inf"), budget_docs=None)
    print("移した %d 本・残した %d 本" % (r.get("moved", 0), sum((r.get("kept") or {}).values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
