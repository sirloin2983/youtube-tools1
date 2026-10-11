# -*- coding: utf-8 -*-
"""案件の 候補.json・採用.json の純粋な部分(RS8 B3-4a。flow/casebook から ytt へ下ろした。決定 3-37 の (r8j)〜(r8q))。

ytt/studiodata が data.json の行の `case`(案件の根)から配信を読む(=重ねる)ために、層の向き(ytt は flow を読めない)の都合で
ファイルの形・パスの相対 ⇔ 絶対・読み・重ね方・ロックをここに置く。**書く側(split・write・case_of)は flow/casebook**(ここを読む)。
形の説明は flow/casebook の説明文を見る。

- `read(root)`: 案件の (候補, 採用)。`read(root, cached=True)` は fsio.StampCache でファイルの更新日時と大きさが同じなら読み直さない
  (一覧のたびに読むスタジオの読み口 ytt/studiodata が使う。返すのは共有の中身 = 変えない。merge は複製を返す)
- `lock(root)`: 案件ごとの RLock。書く側は Store.lock のあとにこれを取る(逆の順は作らない)
"""
import copy
import logging
import os
import threading

from . import errors as _errors, fsio as _fsio, marks as _marks, schemas as _schemas

log = logging.getLogger("ytt.casefiles")

CANDIDATES_NAME = "候補.json"
ADOPTIONS_NAME = "採用.json"
CANDIDATES_SCHEMA = "youtube-tools-candidates/v1"
ADOPTIONS_SCHEMA = "youtube-tools-adoptions/v1"
MAX_BYTES = 16 * 2**20          # 読むときの大きさの上限(data.json の配信 1 本ぶんより十分大きい)
MAX_REJECTED = _marks.MAX_MARKS  # 1 つの配信の消した印の上限(古い物から捨てる)
UNSEEN_CODE = "case_unseen"     # 置き場所が見えないときの ApiError の code(503。ytt/docloc の doc_unseen と同じ形)
BROKEN_CODE = "case_broken"     # 採用.json も .bak も読めないときの ApiError の code(500)
KINDS = ("youtube", "file", "live")

_locks = {}
_locks_guard = threading.Lock()
_cand_cache = _fsio.StampCache()
_adopt_cache = _fsio.StampCache()


# ---------------------------------------------------------------- 置き場所
def work_path(root, name):
    """<案件の根>/作業用/<name>"""
    return os.path.join(root, _schemas.WORK_DIR, name)


def lock(root):
    """案件ごとのロック(同じプロセスの中。RLock なので read・write を包んで読み → 書きを 1 つにできる)"""
    key = _fsio.norm_path(root)
    with _locks_guard:
        lk = _locks.get(key)
        if lk is None:
            lk = _locks[key] = threading.RLock()
        return lk


def is_remote(p):
    return _fsio.is_network_path(p) or _fsio.is_remote_drive(p)


def problem(root):
    """案件の根として使えないなら理由の文字列、使えるなら None(絶対パス・ネットワーク上でない・フォルダが見える)。
    ネットワーク上のパスは名前だけで断る(存在を調べるだけで資格情報を送ってしまうため)"""
    if not isinstance(root, str) or not root or not os.path.isabs(root):
        return "絶対パスではない"
    if is_remote(root):
        return "ネットワーク上のパス"
    if not os.path.isdir(root):
        return "フォルダが見えない"
    return None


def need_root(root):
    why = problem(root)
    if why:
        raise _errors.ApiError(UNSEEN_CODE, "案件のフォルダが見えません(%s)。ドライブをつないでから、もう一度試してください" % why,
                               503, {"dir": str(root or ""), "reason": why})



# ---------------------------------------------------------------- パス(案件の根からの相対)
def abs_path(path, root):
    """相対のパス(区切り /)-> 案件の根の下の絶対パス。根の外に出るなら None。root が無い・絶対パス・空ならそのまま"""
    if not root or not isinstance(path, str) or not path or os.path.isabs(path):
        return path
    p = os.path.normpath(os.path.join(root, path))
    return p if _fsio.is_inside(p, root, strict=True) else None


def rel_path(path, root):
    """絶対パス -> 案件の根からの相対(区切り /)。根の下でない・正規化されていない・戻すと同じ文字にならないなら、そのまま(往復で変えない)"""
    if not root or not isinstance(path, str) or not path or not os.path.isabs(path) or os.path.normpath(path) != path:
        return path
    if not _fsio.is_inside(path, root, strict=True):
        return path
    try:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path
    return rel if not rel.startswith("..") and abs_path(rel, root) == path else path


# ---------------------------------------------------------------- 形
def empty_candidates():
    return {"schema": CANDIDATES_SCHEMA, "sources": {}}


def empty_adoptions():
    return {"schema": ADOPTIONS_SCHEMA, "sources": {}, "marks": [], "rejected": [], "status": "", "memo": ""}


def _sid_ok(sid):
    return isinstance(sid, str) and bool(_marks.ID_RE.match(sid))


def parse_candidates(d):
    """読んだ 候補.json -> 整えた形か None(形が違う)。壊れたマーク・id の形が違う配信は読み飛ばす(ytt/marks.load_marks)"""
    if not isinstance(d, dict) or d.get("schema") != CANDIDATES_SCHEMA or not isinstance(d.get("sources"), dict):
        return None
    out = empty_candidates()
    for sid, s in d["sources"].items():
        if not _sid_ok(sid) or not isinstance(s, dict):
            continue
        dur = _marks.fnum(s.get("duration"))
        an = s.get("analysis")
        out["sources"][sid] = {"analysis": an if isinstance(an, dict) else None, "duration": dur if dur is not None and dur >= 0 else 0.0,
                               "auto": _marks.load_marks(s.get("auto"))}
    return out


def _rejected_entry(r):
    """消した印 1 件を整える。形が違えば None"""
    if not isinstance(r, dict) or not _sid_ok(r.get("source")):
        return None
    s, e = _marks.fnum(r.get("start")), _marks.fnum(r.get("end"))
    if s is None or e is None or e <= s:
        return None
    out = {"source": r["source"], "id": r["id"] if _sid_ok(r.get("id")) else "", "start": round(s, 1), "end": round(e, 1),
           "at": _marks.ms_or_now(r.get("at"))}
    return out


def parse_adoptions(d):
    """読んだ 採用.json -> 整えた形か None(形が違う)。sources にない配信のマーク・壊れたマーク・壊れた印は読み飛ばす"""
    if not isinstance(d, dict) or d.get("schema") != ADOPTIONS_SCHEMA or not isinstance(d.get("sources"), dict) \
            or not isinstance(d.get("marks"), list):
        return None
    out = empty_adoptions()
    for sid, s in d["sources"].items():
        if not _sid_ok(sid) or not isinstance(s, dict) or s.get("kind") not in KINDS:
            continue
        src = copy.deepcopy(s)
        order = src.get("order")
        if order is not None and not (isinstance(order, list) and all(isinstance(x, str) for x in order)):
            src.pop("order")
        out["sources"][sid] = src
    by_src = {}
    for m in d["marks"]:
        if isinstance(m, dict) and m.get("source") in out["sources"]:
            by_src.setdefault(m["source"], []).append({k: v for k, v in m.items() if k != "source"})
    for sid, ms in by_src.items():
        out["marks"] += [dict(m, source=sid) for m in _marks.load_marks(ms)]
    rej = d.get("rejected") if isinstance(d.get("rejected"), list) else []
    out["rejected"] = [r for r in map(_rejected_entry, rej) if r is not None and r["source"] in out["sources"]]
    out["status"] = d["status"][:40] if isinstance(d.get("status"), str) else ""
    out["memo"] = d["memo"][:4000] if isinstance(d.get("memo"), str) else ""
    return out


# ---------------------------------------------------------------- 重ねる・分ける
def _hidden_by(c, adopted, adopted_ids, rejected):
    """候補 c が画面に出ないか(採用と同じ id・採用と same・消した印の id か similar)"""
    if c["id"] in adopted_ids or any(_marks.same(c, a) for a in adopted):
        return True
    return any((r.get("id") and r["id"] == c["id"]) or _marks.similar(c, r) for r in rejected)


def visible(pool, adopted, rejected):
    """候補 pool のうち画面に出る物(pool の並びのまま)"""
    ids = {a["id"] for a in adopted}
    return [c for c in pool if not _hidden_by(c, adopted, ids, rejected)]


def ordered(marks, order):
    """画面の並び: order(id の並び)があればその順・order に無い id は後ろに時刻の順。無ければ時刻の順(同じ時刻は元の並び)"""
    if not order:
        return sorted(marks, key=_marks.by_time)
    idx = {mid: i for i, mid in enumerate(order)}
    known = sorted((m for m in marks if m["id"] in idx), key=lambda m: idx[m["id"]])
    return known + sorted((m for m in marks if m["id"] not in idx), key=_marks.by_time)


def merge(candidates, adoptions, source_id, root=None):
    """2 つを重ねて data.json の配信 1 本の形に戻す。採用.json に source_id が無ければ None。
    root(案件の根)を渡すと、相対の path を絶対に戻す(根の外を指す path は外す)"""
    adoptions = adoptions or empty_adoptions()
    src = adoptions["sources"].get(source_id)
    if src is None:
        return None
    cs = (candidates or empty_candidates())["sources"].get(source_id) or {}
    adopted = []
    for m in adoptions["marks"]:
        if m.get("source") != source_id:
            continue
        a = {k: copy.deepcopy(v) for k, v in m.items() if k != "source"}
        if "path" in a:
            p = abs_path(a["path"], root)
            if p is None:
                a.pop("path")
            else:
                a["path"] = p
        adopted.append(a)
    rejected = [r for r in adoptions.get("rejected") or () if r.get("source") == source_id]
    shown = copy.deepcopy(visible(cs.get("auto") or [], adopted, rejected))
    video = {k: copy.deepcopy(v) for k, v in src.items() if k != "order"}
    video["id"] = source_id
    if video.get("path"):
        video["path"] = abs_path(video["path"], root) or ""
    video["duration"] = cs.get("duration") or 0.0
    video["analysis"] = copy.deepcopy(cs.get("analysis"))
    video["marks"] = ordered(adopted + shown, src.get("order"))
    return video


# ---------------------------------------------------------------- 読み書き
def read_doc(path, parse):
    """(整えた中身か None, ファイルがあるか)"""
    if not os.path.exists(path):
        return None, False
    raw = _fsio.read_json_or(path, None, MAX_BYTES, kind=dict, allow_nan=True)
    return (parse(raw) if raw is not None else None), True



def forget(root):
    """この案件のファイルの覚えた中身を捨てる(書く側 flow/casebook.write が書いたあと lock(root) の中で呼ぶ。
    同じ時刻の刻みで同じ大きさに書き直したとき、更新日時と大きさのキャッシュが古い中身を返し続けないため)"""
    folder = os.path.dirname(work_path(root, CANDIDATES_NAME))
    _cand_cache.prune((), folder)
    _adopt_cache.prune((), folder)


def _read_doc_cached(path, parse, cache):
    """_read_doc の StampCache つき(更新日時と大きさが同じなら読み直さない)。無いファイルは (None, False)"""
    if not os.path.exists(path):
        return None, False
    v = cache.get(path, lambda p: parse(_fsio.read_json_or(p, None, MAX_BYTES, kind=dict, allow_nan=True)))
    return v, True


def read(root, cached=False):
    """案件の (候補, 採用) を読む(無いファイルは空の形)。置き場所が見えなければ ApiError 503(case_unseen)。
    候補.json が壊れていれば空(ログに 1 行。① が作り直せる)。採用.json が壊れていれば .bak を使い(ログ)、.bak も読めなければ ApiError 500(case_broken)
    = 人の採用を空と取り違えて上書きしない。cached=True なら更新日時と大きさが同じファイルは読み直さない(返すのは共有の中身。変えない)"""
    with lock(root):
        need_root(root)
        cp, ap = work_path(root, CANDIDATES_NAME), work_path(root, ADOPTIONS_NAME)
        if cached:
            cands, there = _read_doc_cached(cp, parse_candidates, _cand_cache)
        else:
            cands, there = read_doc(cp, parse_candidates)
        if cands is None:
            if there:
                log.warning("候補.json が読めないので空として扱います: %s", cp)
            cands = empty_candidates()
        if cached:
            adopts, there = _read_doc_cached(ap, parse_adoptions, _adopt_cache)
        else:
            adopts, there = read_doc(ap, parse_adoptions)
        if adopts is None and there:
            adopts, _ = read_doc(ap + ".bak", parse_adoptions)
            if adopts is None:
                raise _errors.ApiError(BROKEN_CODE, "案件の採用の記録(採用.json)が壊れていて、控え(.bak)も読めません", 500, {"path": ap})
            log.warning("採用.json が読めないので 1 つ前の控え(.bak)を使います: %s", ap)
        return cands, adopts or empty_adoptions()
