# -*- coding: utf-8 -*-
"""④ 前からあるスタジオの配信(data.json)と案件の状態(cases.json)を、案件の 候補.json・採用.json へ移す(RS8 B3-8。決定 3-37 の (r8o)・(r8p))。

入口が起動のとき(.flow.lock を取った直後・待ち受けの前・スタジオの取り込みの前 = スタジオの Store と同時に data.json を書かない)に run を 1 回呼ぶ。
自動で呼ぶのはこの PC の設定(flow/machine.py)の markMove が true のときだけ(既定 false。入口の move_marks が見る)。下のコマンドはスイッチに関係なく使える。
守りは manage/cases/docmove(B2-3)と同じ形: バックアップが 1 回済んでから・初めに data.json.pre-b3・cases.json.pre-b3 へ写す(前にあれば写さない =
いちばん初めの形を残す)・1 本ずつ `.part-<pid>` に書いて読み直す → 重ねると元の配信と一致したら改名 → 索引の行に・予算・冪等・--back・--resume・--now。

- 対象: data.json の配信のうち、まだ case(案件の根)を持たず、書き出したマークがあり、flow/casebook.case_of で根が 1 つに引ける物。
  形は human/review/store の初めての書き出し(Store._make_case)と同じ: split(配信, 根, prev = 今の案件)= 同じ案件のほかの配信は引き継ぐ・
  path は根からの相対・data.json の行は索引の行 {id, kind, title, channel, live?, rev, createdAt, updatedAt, case}
- cases.json のその配信の行(状態・メモ・状態の時刻・自動の確認)は、採用.json の上の段にまだ何も無ければそこへ(manage/cases の _edit_case と同じ引き継ぎ)。
  移した行は data.json を書いたあとで cases.json から消す。上の段に既に何かあれば(同じ案件のほかの配信の分)cases.json の行は残す(ログ)
- 1 本ずつ: 案件のロック(ytt/casefiles.lock)の中で 候補 → 採用 の順に `<名前>.part-<pid>` へ書き、読み直して重ねた形が元の配信と同じか確かめてから改名
  (採用.json がいちばん最後 = 重ねたときに配信が見えるのは 採用.json に入ってから。途中で落ちても data.json はまだ全部の形 = 正のまま)。
  採用.json は書く前に今の物を .bak へ 1 世代。案件の 採用.json が読めない(.bak で読んでいる)案件には移さない
- 2 回目: 案件に既にこの配信があり、重ねると data.json の行と同じなら(書いたあと data.json を書く前に落ちた)書かずに索引の行にする。
  違えば移さない(人の記録を上書きしない)。--back で戻した配信だけは(結果の backed)今の data.json の形で書き直す
- 残す: 書き出したフォルダが 2 つ以上(題が変わって割れた)・書き出し先の外・持ち主(.studio-id)が違う・フォルダが見えない・書き出し先が固定ディスクでない など
  (REASONS)。書き出したマークが無い配信は対象でない(数えない)
- 書き出し先を変えたとき((r8o)): 起動のたびに今の書き出し先を結果の outDirs に覚え、案件が見えない索引の行で、前の書き出し先の下の相対パスを
  今の書き出し先の下に付け替えたフォルダの .studio-id がその配信の物で、採用.json にその配信があるときだけ case を繋ぎ直す(題で探さない)。スイッチに関係なく
- 結果: <スタジオの作業データ>/.marks-moved.json(RESULT_NAME。移した本数・残した理由ごとの本数・時刻・paused・outDirs・backed)

コマンド(入口を終了してから。.flow.lock を取る):
    py -3.10 src/manage/cases/markmove.py --now [--dry-run]       バックアップを待たずに今すぐ移す(y/N。予算なし)。--dry-run は数えるだけ(何も書かない)
    py -3.10 src/manage/cases/markmove.py --back                  案件 → data.json の全部の形へ戻す(案件のファイルは残す)。自動の移行を止める(paused)
    py -3.10 src/manage/cases/markmove.py --resume                自動の移行を再開する
    py -3.10 src/manage/cases/markmove.py --relink <配信の id> <フォルダ>   索引の case を繋ぎ直す(.studio-id が一致して 採用.json にその配信があるときだけ)
"""
import argparse
import copy
import json
import os
import shutil
import sys
import time

_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # cases -> manage -> src
if _SRC not in sys.path:   # コマンドで単独に動かすときも ytt・flow・human を読めるように(入口から読むときは入っている)
    sys.path.insert(0, _SRC)
from flow import casebook as _casebook, placement as _placement  # noqa: E402
from human.review import store as _store  # noqa: E402  data.json の行の読み方(_load_video)と索引の行の形(_index_row)は Store と同じ物を使う
from manage.cases import cases as _cases, docmove as _docmove  # noqa: E402
from ytt import casefiles as _cf, datadir as _datadir, errors as _errors, fsio as _fsio, names as _names, schemas as _schemas  # noqa: E402

RESULT_NAME = ".marks-moved.json"   # <スタジオの作業データ>/.marks-moved.json(data.json の隣)
RESULT_VERSION = 1
PRE_SUFFIX = ".pre-b3"              # data.json.pre-b3・cases.json.pre-b3(移す前のいちばん初めの形)
PART_MARK = _docmove.PART_MARK      # <名前>.part-<pid>(バックアップも写さない)
BUDGET_SEC = 20.0
BUDGET_VIDEOS = 50
OUT_DIRS_KEEP = 5                   # 覚えておく書き出し先の数(新しい順)
DATA_MAX = 256 * 2**20              # data.json を読む上限
# 残した理由(結果の kept の鍵)→ 画面とログの文
REASONS = {"multi": "書き出したフォルダが 2 つ以上ある(題が変わって割れた)", "outside": "書き出したフォルダが書き出し先の外",
           "owner": "書き出したフォルダの持ち主(.studio-id)が違う・無い", "missing": "書き出したフォルダが見えない",
           "noPath": "書き出した動画の場所が分からない", "outDir": "書き出し先が固定ディスクでない・ネットワーク上",
           "caseHas": "案件に同じ配信の違う記録がある", "caseBroken": "案件の採用の記録(採用.json)が読めない",
           "verify": "書いて読み直すと元と合わない", "unreadable": "data.json の行が読めない", "error": "移す途中で失敗した"}


class _Kept(Exception):
    """この配信は移さない(args[0] = REASONS の鍵)"""


# ---------------------------------------------------------------- data.json・cases.json
def read_data(path):
    """data.json の中身(dict。videos が dict)か None(無い・読めない・形が違う)"""
    d = _fsio.read_json_or(path, None, DATA_MAX, kind=dict, allow_nan=True)
    return d if isinstance(d, dict) and isinstance(d.get("videos"), dict) else None


def _write_data(path, d):
    """data.json を書く(Store._save と同じ: 1 つ前を .bak へ・原子的・詰めて書く)"""
    if os.path.exists(path):
        try:
            shutil.copyfile(path, path + ".bak")
        except OSError:
            pass
    _fsio.atomic_write(path, json.dumps(d, ensure_ascii=False).encode("utf-8"), fsync_required=True)


def _pre_copy(path):
    """移す前の形を <名前>.pre-b3 へ写す(前にあれば写さない = いちばん初めの形を残す)"""
    pre = path + PRE_SUFFIX
    if os.path.isfile(path) and not os.path.exists(pre):
        shutil.copy2(path, pre)


def _saved(cases_path):
    return _cases.load_saved(cases_path) if cases_path else {}


def _write_saved(cases_path, saved):
    _fsio.write_json(cases_path, {"schema": _cases.SCHEMA, "cases": saved})


def _fields(rec):
    """cases.json の 1 件・採用.json の上の段 -> {status, memo, statusUpdatedAt, auto} のうち持っている物"""
    return {k: copy.deepcopy(rec[k]) for k in _cases.FIELDS if isinstance(rec, dict) and rec.get(k)}


# ---------------------------------------------------------------- 結果の記録
def result_path(data_path):
    return os.path.join(os.path.dirname(data_path), RESULT_NAME)


def read_result(data_path):
    return _fsio.read_json_or(result_path(data_path), {}, 256 * 1024, kind=dict)


def _update_result(data_path, **kw):
    d = dict(read_result(data_path), **kw)
    d["version"] = RESULT_VERSION
    _fsio.write_json(result_path(data_path), d)
    return d


def set_paused(data_path, paused):
    return _update_result(data_path, paused=bool(paused), pausedAt=int(time.time() * 1000) if paused else None)


# ---------------------------------------------------------------- 案件を引けない理由
def why_no_case(v, out_dir):
    """casebook.case_of が None の配信 -> 残した理由(REASONS の鍵)。case_of と同じ規則を 1 つずつ見る(読むだけ)"""
    if not isinstance(out_dir, str) or not os.path.isabs(out_dir) or _cf.is_remote(out_dir) or not _fsio.is_fixed_drive(out_dir):
        return "outDir"
    folders = []
    for m in v.get("marks") or ():
        p = m.get("path") if m.get("status") == "exported" else None
        if isinstance(p, str) and p and os.path.isabs(p) and not _cf.is_remote(p):
            root = os.path.normpath(_schemas.media_folder(p))
            if all(_fsio.norm_path(root) != _fsio.norm_path(x) for x in folders):
                folders.append(root)
    if not folders:
        return "noPath"
    inside = [r for r in folders if _fsio.is_inside(r, out_dir, strict=True)]
    seen = [r for r in inside if os.path.isdir(r)]
    good = [r for r in seen if _names.read_owner(r) in _casebook.owners(v)]
    if len(good) > 1:
        return "multi"
    if not inside:
        return "outside"
    return "owner" if seen else "missing"


# ---------------------------------------------------------------- 1 本ずつ
def _clean_parts(root):
    """前に落ちて残った 候補.json・採用.json の書きかけ(<名前>.part-<pid>)を消す"""
    work = os.path.dirname(_cf.work_path(root, _cf.ADOPTIONS_NAME))
    try:
        names = os.listdir(work)
    except OSError:
        return
    for n in names:
        if _docmove.PART_RE.search(n) and n.split(PART_MARK)[0] in (_cf.CANDIDATES_NAME, _cf.ADOPTIONS_NAME):
            _fsio.unlink_quiet(os.path.join(work, n))


def _same_video(cands, adopts, v, root):
    return _cf.merge(cands, adopts, v["id"], root) == v


def _plan(v, root, prev, rec, backed):
    """移す中身を組む -> (候補(書かないなら None), 採用(書かないなら None), 引き継いだ cases.json の欄 or None)。移せなければ _Kept"""
    have = _cf.merge(*prev, v["id"], root)
    if have is not None and have != v and v["id"] not in backed:
        raise _Kept("caseHas")
    cands, adopts = _casebook.split(v, root, prev=prev)
    took, want = None, _fields(rec)
    if want and not _fields(adopts):
        took = want
        adopts.update(took)
    elif want and all(adopts.get(k) == x for k, x in want.items()):
        took = want   # 前の回に写したあと cases.json の行を消す前に落ちた = 行を消してよい
    if not _same_video(_cf.parse_candidates(_roundtrip(cands)), _cf.parse_adoptions(_roundtrip(adopts)), v, root):
        raise _Kept("verify")
    return (cands if cands != prev[0] else None), (adopts if adopts != prev[1] else None), took


def _roundtrip(doc):
    return json.loads(json.dumps(doc, ensure_ascii=False))


def _write_case(root, cands, adopts, v, took, pid):
    """候補 → 採用 の順に .part- へ書き、読み直して重ねた形が v と同じ・引き継いだ欄が読めるか確かめてから改名(採用.json がいちばん最後)。
    合わなければ書きかけを消して _Kept("verify")"""
    items = [(n, d, p) for n, d, p in ((_cf.CANDIDATES_NAME, cands, _cf.parse_candidates), (_cf.ADOPTIONS_NAME, adopts, _cf.parse_adoptions))
             if d is not None]
    staged = []
    try:
        got = {}
        for name, doc, parse in items:
            final = _cf.work_path(root, name)
            part = final + PART_MARK + str(pid)
            staged.append((part, final))
            _fsio.write_json(part, doc, indent=1, fsync_required=True)
            got[name] = _cf.read_doc(part, parse)[0]
        c, a = _cf.read(root)
        c, a = got.get(_cf.CANDIDATES_NAME, c), got.get(_cf.ADOPTIONS_NAME, a)
        if c is None or a is None or not _same_video(c, a, v, root) or (took and _fields(a) != _fields(_cf.parse_adoptions(_roundtrip(adopts)))):
            raise _Kept("verify")
        for part, final in staged:
            if final.endswith(_cf.ADOPTIONS_NAME) and os.path.exists(final):
                shutil.copyfile(final, final + ".bak")   # 1 つ前の世代(読めることは確かめてある)
            _fsio.replace_retry(part, final)
    except BaseException:
        for part, _final in staged:
            _fsio.unlink_quiet(part)
        raise
    finally:
        _cf.forget(root)


def _move_one(ctx, vid, raw):
    """配信 1 本 -> ("moved", 索引の行, 引き継いだ欄 or None) か (残した理由, None, None) か None(対象でない)"""
    try:
        v = _store.Store._load_video(vid, raw)
    except (ValueError, TypeError, KeyError, AttributeError):
        return "unreadable", None, None
    if not any(m.get("status") == "exported" for m in v["marks"]):
        return None
    root = _casebook.case_of(v, ctx["out_dir"])
    if not root:
        return why_no_case(v, ctx["out_dir"]), None, None
    rec = ctx["saved"].get(vid)
    with _cf.lock(root):
        if not ctx["dry_run"]:   # 数えるだけのときは案件のフォルダに何もしない
            _clean_parts(root)
        if _cf.read_doc(_cf.work_path(root, _cf.ADOPTIONS_NAME), _cf.parse_adoptions) == (None, True):
            return "caseBroken", None, None
        try:
            cands, adopts, took = _plan(v, root, _cf.read(root), rec, ctx["backed"])
            if not ctx["dry_run"] and (cands is not None or adopts is not None):
                _write_case(root, cands, adopts, v, took, ctx["pid"])
        except _Kept as e:
            ctx["log"]("配信 %s を案件へ移しません(%s): %s" % (vid, REASONS[e.args[0]], root))
            return e.args[0], None, None
    if rec is not None and not took and _fields(rec):
        ctx["log"]("配信 %s: 案件に状態・メモが既にあるので cases.json の行は残します: %s" % (vid, root))
    return "moved", _store._index_row(v, root), took


def run(data_path, cases_path=None, out_dir=None, backup_ok=False, log=None, budget_sec=BUDGET_SEC, budget_videos=BUDGET_VIDEOS,
        clock=time.monotonic, dry_run=False):
    """data.json の配信を案件へ移す(予算まで)。-> 結果(dict。state = done・partial・waitBackup・paused・empty)。
    data_path = スタジオの data.json・cases_path = 入口の cases.json(None = 引き継がない)・out_dir = 書き出し先(None = スタジオの設定)・
    budget_videos = 1 回に移す本数の上限(None = なし)・dry_run = 何も書かずに数えるだけ(結果の記録も書かない)"""
    log = log or (lambda msg: None)
    prev = read_result(data_path)
    if prev.get("paused") and not dry_run:
        return dict(prev, state="paused")
    d = read_data(data_path)
    todo = [vid for vid, raw in (d or {}).get("videos", {}).items() if isinstance(raw, dict) and not raw.get("case")] if d else []
    if not todo:
        return {"state": "empty", "moved": 0}
    if not backup_ok:
        log("配信の記録を案件へ移すのは、バックアップが 1 回済んでからにします(今回は移しません。data.json の配信 %d 本)" % len(todo))
        return {"state": "waitBackup", "moved": 0, "videos": len(todo)}
    if not dry_run:
        _pre_copy(data_path)
        if cases_path:
            _pre_copy(cases_path)
    saved = _saved(cases_path)
    backed = dict(prev.get("backed") or {})
    ctx = {"out_dir": out_dir or _datadir.studio_out_dir(), "saved": saved, "backed": backed, "pid": os.getpid(), "log": log, "dry_run": dry_run}
    t0, kept, moved, remaining, rows, took_from = clock(), {}, 0, 0, {}, []
    for i, vid in enumerate(todo):
        if clock() - t0 > budget_sec or (budget_videos is not None and moved >= budget_videos):
            remaining = len(todo) - i
            break
        try:
            r = _move_one(ctx, vid, d["videos"][vid])
        except Exception as e:   # 1 本の失敗で止めない(data.json はまだ全部の形 = 正のまま)
            log("配信 %s を案件へ移せませんでした: %s %s" % (vid, e.__class__.__name__, str(e)[:200]))
            r = ("error", None, None)
        if r is None:
            continue
        if r[0] == "moved":
            moved += 1
            rows[vid] = r[1]
            backed.pop(vid, None)
            if r[2]:
                took_from.append(vid)
        else:
            kept[r[0]] = kept.get(r[0], 0) + 1
    out = {"version": RESULT_VERSION, "at": int(time.time() * 1000), "state": "partial" if remaining else "done", "paused": False,
           "moved": moved, "movedTotal": int(prev.get("movedTotal") or 0) + moved, "kept": kept, "remaining": remaining,
           "seconds": round(clock() - t0, 1), "dryRun": bool(dry_run)}
    if not dry_run:
        _commit_index(data_path, d, rows, cases_path, took_from, log)
        _update_result(data_path, **dict(out, backed=backed))
    log("配信の記録の移行%s: 案件へ %d 本・残した %d 本%s%s" % (
        "(数えるだけ)" if dry_run else "", moved, sum(kept.values()),
        "(%s)" % "・".join("%s %d" % (REASONS.get(k, k), v) for k, v in sorted(kept.items())) if kept else "",
        "。続きの %d 本は次の起動で" % remaining if remaining else ""))
    return out


def _commit_index(data_path, d, rows, cases_path, took_from, log):
    """移した配信の data.json の行を索引の行にして書き、そのあと cases.json から引き継いだ行を消す(この順 = 途中で落ちても状態を失わない)"""
    if not rows:
        return
    d["videos"] = {vid: rows.get(vid, raw) for vid, raw in d["videos"].items()}
    _write_data(data_path, d)
    if took_from and cases_path:
        saved = _saved(cases_path)
        if any(saved.pop(vid, None) is not None for vid in list(took_from)):
            _write_saved(cases_path, saved)
    log("data.json の配信 %d 本を案件の索引の行にしました" % len(rows))


# ---------------------------------------------------------------- 繋ぎ直す((r8o))
def relink_problem(row, folder):
    """索引の行 row を folder に繋ぎ直せないなら理由の文、繋げるなら None(.studio-id がその配信の物・採用.json にその配信がある)"""
    why = _cf.problem(folder)
    if why:
        return why
    if _names.read_owner(folder) not in _casebook.owners(row):
        return "フォルダの持ち主(作業用/.studio-id)がこの配信の物でない"
    try:
        adopts = _cf.read(folder)[1]
    except _errors.ApiError as e:
        return e.message
    return None if row.get("id") in adopts["sources"] else "案件の採用の記録(採用.json)にこの配信が無い"


def relink(data_path, vid, folder, log=None):
    """索引の行 vid の case を folder にする(relink_problem が None のときだけ)。-> None(繋いだ)か理由の文"""
    log = log or print
    d = read_data(data_path)
    row = (d or {}).get("videos", {}).get(vid) if d else None
    if not isinstance(row, dict) or not row.get("case"):
        return "data.json に案件にした配信 %s がありません" % vid
    folder = os.path.normpath(os.path.abspath(folder))
    why = relink_problem(row, folder)
    if why:
        return why
    d["videos"][vid] = dict(row, case=folder)
    _write_data(data_path, d)
    log("配信 %s の案件を繋ぎ直しました: %s → %s" % (vid, row["case"], folder))
    return None


def relink_out_dir(data_path, out_dir, log=None):
    """起動のとき: 今の書き出し先を結果の outDirs に覚え、案件が見えない索引の行を、前の書き出し先の下の相対パスで今の書き出し先の下に
    繋ぎ直せれば繋ぐ((r8o)。題で探さない)。-> 繋ぎ直した本数。data.json が無ければ何もしない"""
    log = log or (lambda msg: None)
    d = read_data(data_path)
    if d is None or not isinstance(out_dir, str) or not os.path.isabs(out_dir):
        return 0
    cur = os.path.normpath(out_dir)
    prev = [x for x in (read_result(data_path).get("outDirs") or []) if isinstance(x, str) and os.path.isabs(x)]
    olds = [x for x in prev if _fsio.norm_path(x) != _fsio.norm_path(cur)]
    n = 0
    for vid, row in d["videos"].items():
        root = row.get("case") if isinstance(row, dict) else None
        if not isinstance(root, str) or not root or not _cf.problem(root):
            continue
        for old in olds:
            if not _under(root, old):
                continue
            new = os.path.normpath(os.path.join(cur, os.path.relpath(root, old)))
            if relink_problem(row, new) is None:
                d["videos"][vid] = dict(row, case=new)
                n += 1
                log("書き出し先が変わったので、配信 %s の案件を繋ぎ直しました: %s → %s" % (vid, root, new))
                break
    if n:
        _write_data(data_path, d)
    keep = [cur] + [x for x in prev if _fsio.norm_path(x) != _fsio.norm_path(cur)]
    if keep[:OUT_DIRS_KEEP] != prev[:OUT_DIRS_KEEP] or n:
        r = read_result(data_path)
        _update_result(data_path, outDirs=keep[:OUT_DIRS_KEEP], relinkedTotal=int(r.get("relinkedTotal") or 0) + n)
    return n


def _under(path, base):
    """path が base の下か(文字で比べる = 見えないドライブ・ネットワーク上のパスを調べない)"""
    p, b = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(base))
    return p.startswith(b.rstrip("\\/") + os.sep)


# ---------------------------------------------------------------- 戻す
def back(data_path, cases_path=None, log=None):
    """案件にした配信を data.json の全部の形へ戻す(案件のファイルは残す)。先に paused を書く(自動の移行を止める)。
    採用.json の上の段(状態・メモ)は、cases.json にその配信の行が無ければ写す。-> {"back": 戻した本数, "kept": {理由: 数}}"""
    log = log or print
    set_paused(data_path, True)
    d = read_data(data_path)
    out = {"back": 0, "kept": {}}
    if d is None:
        return out
    _pre_copy(data_path)
    saved, saved_changed, backed = _saved(cases_path), False, dict(read_result(data_path).get("backed") or {})
    for vid, row in list(d["videos"].items()):
        root = row.get("case") if isinstance(row, dict) else None
        if not isinstance(root, str) or not root:
            continue
        try:
            cands, adopts = _cf.read(root)
            v = _cf.merge(cands, adopts, vid, root)
        except _errors.ApiError as e:
            v, adopts = None, None
            log("配信 %s を戻せません(%s): %s" % (vid, e.message, root))
        if v is None:
            out["kept"]["unseen"] = out["kept"].get("unseen", 0) + 1
            continue
        d["videos"][vid] = v
        backed[vid] = root
        if cases_path and _fields(adopts) and vid not in saved:
            saved[vid] = _fields(adopts)
            saved_changed = True
        out["back"] += 1
        log("配信 %s を data.json の全部の形へ戻しました(案件のファイルは残します): %s" % (vid, root))
    if out["back"]:
        _write_data(data_path, d)
        if saved_changed:
            _write_saved(cases_path, saved)
    _update_result(data_path, backed=backed)
    return out


# ---------------------------------------------------------------- 入口の「調子」
_data_cache = _fsio.StampCache()


def _unseen_count(data_path):
    def load(p):
        d = read_data(p)
        return [row["case"] for row in (d or {}).get("videos", {}).values() if isinstance(row, dict) and isinstance(row.get("case"), str) and row["case"]] \
            if d else []
    roots = _data_cache.get(data_path, load) or []
    return sum(1 for r in roots if _cf.problem(r))


def status(data_path, last=None):
    """入口の「調子」の 1 行の材料。last = 今回の起動の結果(state が off = スイッチ markMove がオフ・waitBackup ならそれを先に出す)。何も無ければ None"""
    d = read_result(data_path)
    unseen = _unseen_count(data_path)
    last = last if isinstance(last, dict) else {}
    now = last.get("state") if last.get("state") in ("off", "waitBackup") else None
    if not d.get("at") and not d.get("paused") and not unseen and not now and not d.get("relinkedTotal"):
        return None
    state = now or ("paused" if d.get("paused") else d.get("state") or "done")
    return {"state": state, "moved": int(d.get("movedTotal") or 0), "movedNow": int(last.get("moved") or 0), "kept": dict(d.get("kept") or {}),
            "remaining": int(d.get("remaining") or 0), "at": d.get("at"), "unseen": unseen, "relinked": int(d.get("relinkedTotal") or 0),
            "relinkedNow": int(last.get("relinked") or 0), "reasons": dict(REASONS), "videos": last.get("videos")}


# ---------------------------------------------------------------- コマンド
def main(argv=None, ask=input):
    ap = argparse.ArgumentParser(prog="markmove.py", description="スタジオの配信の記録(data.json)と案件の状態(cases.json)を案件のフォルダへ移す・戻す(入口を終了してから)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--now", action="store_true", help="バックアップを待たずに今すぐ移す(予算なし)")
    g.add_argument("--back", action="store_true", help="案件 → data.json の全部の形へ戻す(案件のファイルは残す)。自動の移行を止める")
    g.add_argument("--resume", action="store_true", help="止めた自動の移行を再開する")
    g.add_argument("--relink", nargs=2, metavar=("配信のid", "フォルダ"), help="索引の case を繋ぎ直す(.studio-id が一致するときだけ)")
    ap.add_argument("--dry-run", action="store_true", help="--now で、何も書かずに移せる本数・残す理由を数える")
    a = ap.parse_args(argv)
    try:
        lock = _placement.acquire(None)
    except _placement.LockBusy as e:
        print("入口(または別のコマンド)が同じ作業データを使っています(pid %s)。入口を「すべて終了」してから流してください" % e.info.get("pid"))
        return 4
    try:
        return _main(a, _placement.studio_data(), _cases.locations(None)["cases"], ask)
    finally:
        _placement.release(lock)


def _main(a, data_path, cases_path, ask):
    print("スタジオの data.json: %s" % data_path)
    if a.resume:
        set_paused(data_path, False)
        print("自動の移行を再開します(次の入口の起動から)")
        return 0
    if a.back:
        r = back(data_path, cases_path)
        print("戻した %d 本・戻さない %d 本。自動の移行は止めました(再開は --resume)" % (r["back"], sum(r["kept"].values())))
        return 0
    if a.relink:
        why = relink(data_path, a.relink[0], a.relink[1])
        print("繋ぎ直しました" if why is None else "繋ぎ直しませんでした: %s" % why)
        return 0 if why is None else 1
    if read_result(data_path).get("paused") and not a.dry_run:
        print("自動の移行は止めてあります。先に --resume で再開してください")
        return 1
    if not a.dry_run:
        note = "" if _docmove.backup_done(_docmove._backup_state()) else "(バックアップがまだ 1 回も済んでいません)"
        if not _docmove._ask("data.json の配信の記録と cases.json の状態を案件のフォルダへ今すぐ移します%s。よいですか" % note, ask):
            print("移しませんでした")
            return 0
    r = run(data_path, cases_path, backup_ok=True, log=print, budget_sec=float("inf"), budget_videos=None, dry_run=a.dry_run)
    print("%s %d 本・残した %d 本" % ("移せる" if a.dry_run else "移した", r.get("moved", 0), sum((r.get("kept") or {}).values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
