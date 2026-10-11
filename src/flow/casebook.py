# -*- coding: utf-8 -*-
"""② 管理の層 flow: 案件の候補と採用のファイルの持ち主(RS8 B3-3。決定 3-37 の (r8j)〜(r8q)。下調べは WORKLOG の 10-11)。

スタジオの配信 1 本(data.json の videos の 1 つの形)を、案件のフォルダの 2 つのファイルに分けて持つための読み書きと、分ける・重ねるの関数。
**今の保存の経路にはまだ入れていない**(スタジオの Store を替えるのは B3-4)。

- `<案件>/作業用/候補.json`(CANDIDATES_SCHEMA。① の機械の候補): {schema, sources: {<スタジオの id>: {analysis, duration, auto: [手つかずの自動マーク]}}}
- `<案件>/作業用/採用.json`(ADOPTIONS_SCHEMA。③ の人の採用): {schema, sources: {<スタジオの id>: {kind, title, channel, fileName, path, rev,
  createdAt, updatedAt, live?, order?}}, marks: [マーク + source], rejected: [{source, id, start, end, at}], status, memo}。
  1 つの案件に配信が 2 本(ライブの録画 + アーカイブ)ありうるので sources で分け、マークは平らに置いて source を持たせる((r8k))。
  書き出しの結果の path と、file の配信の path は案件の根からの相対(区切りは /。根の外・正規化されていないパスは絶対のまま)((r8m))。
  order は画面の並びが時刻の順でないときだけ持つ(マークの id の並び)
- 分け方 `split`: 境目は今の Store.replace_auto と同じ(src auto で ytt/marks.touched が偽 = 候補・それ以外 = 採用)。
  重ねたときに見えなくなる候補(採用と same・rejected の印に当たる)は採用の側に残す = いつでも merge(*split(v)) == v
- 重ね方 `merge`: 画面 = 採用 ∪ (候補 − 採用と同じ id − 採用と ytt/marks.same で重なる物 − rejected の印に当たる物)。
  rejected の印は id か ytt/marks.similar(±5 秒・重なりの率)で当てる = 再解析で時刻が少しずれても外れない((r8l))
- 案件の引き方 `case_of`: 書き出したマークの path の親(作業用/ の中なら 1 つ上)で、作業用/.studio-id の持ち主がその配信のもの・
  書き出し先(outDir)の下・書き出し先が固定ディスク・ネットワーク上でない(flow/placement の doc_home と同じ規則)。
  1 つに決まらなければ None(題で探さない・勝手に直さない((r8o)))
- 読み書き `read`・`write`: 案件の根を受ける。書く順は 採用 → 候補・どちらも fsio.write_json で原子的・採用.json だけ .bak 1 世代
  (今の採用.json が読めるときだけ写す。読めなければ .broken-<日時> へ退けて .bak を守る)・パスごとのロック `lock(root)`。
  置き場所が見えない(ドライブが外れた・フォルダが消えた・ネットワーク上)ときは ytt/docloc と同じ 503 の形(code case_unseen)で断る
"""
import copy
import logging
import os
import shutil
import threading
import time

from ytt import datadir as _datadir, errors as _errors, fsio as _fsio, marks as _marks, names as _names, schemas as _schemas

log = logging.getLogger("ytt.flow.casebook")

CANDIDATES_NAME = "候補.json"
ADOPTIONS_NAME = "採用.json"
CANDIDATES_SCHEMA = "youtube-tools-candidates/v1"
ADOPTIONS_SCHEMA = "youtube-tools-adoptions/v1"
MAX_BYTES = 16 * 2**20          # 読むときの大きさの上限(data.json の配信 1 本ぶんより十分大きい)
MAX_REJECTED = _marks.MAX_MARKS  # 1 つの配信の消した印の上限(古い物から捨てる)
UNSEEN_CODE = "case_unseen"     # 置き場所が見えないときの ApiError の code(503。ytt/docloc の doc_unseen と同じ形)
BROKEN_CODE = "case_broken"     # 採用.json も .bak も読めないときの ApiError の code(500)
KINDS = ("youtube", "file", "live")
_VIDEO_OWN = ("id", "marks", "analysis", "duration")   # 配信の欄のうち 採用.json の sources に写さない物(id は鍵・残りは別の持ち主)

_locks = {}
_locks_guard = threading.Lock()


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


def _remote(p):
    return _fsio.is_network_path(p) or _fsio.is_remote_drive(p)


def problem(root):
    """案件の根として使えないなら理由の文字列、使えるなら None(絶対パス・ネットワーク上でない・フォルダが見える)。
    ネットワーク上のパスは名前だけで断る(存在を調べるだけで資格情報を送ってしまうため)"""
    if not isinstance(root, str) or not root or not os.path.isabs(root):
        return "絶対パスではない"
    if _remote(root):
        return "ネットワーク上のパス"
    if not os.path.isdir(root):
        return "フォルダが見えない"
    return None


def _need_root(root):
    why = problem(root)
    if why:
        raise _errors.ApiError(UNSEEN_CODE, "案件のフォルダが見えません(%s)。ドライブをつないでから、もう一度試してください" % why,
                               503, {"dir": str(root or ""), "reason": why})


def owners(video):
    """その配信の案件の持ち主の印(.studio-id)として認める値: スタジオの id・ライブなら配信の videoId と live-<録画 id>
    (ライブの書き出しの持ち主は videoId か live-<録画 id>。flow/live_export)"""
    got = {str(video.get("id") or "")}
    live = video.get("live") if isinstance(video.get("live"), dict) else None
    if video.get("kind") == "live" and live:
        if live.get("videoId"):
            got.add(str(live["videoId"]))
        if live.get("recording"):
            got.add("live-" + str(live["recording"]))
    got.discard("")
    return got


def case_of(video, out_dir=None):
    """スタジオの配信(data.json の形)-> 案件の根か None。書き出したマークの path の親(作業用/ の中なら 1 つ上)のうち、
    作業用/.studio-id の持ち主がこの配信(owners)・書き出し先 out_dir(None = スタジオの設定 = ytt.datadir.studio_out_dir)の下・
    書き出し先が固定ディスクでネットワーク上でない、を満たすものが 1 つだけのとき。読むだけ(作らない・書かない)。題で探さない"""
    try:
        out = out_dir or _datadir.studio_out_dir()
        if not isinstance(out, str) or not os.path.isabs(out) or _remote(out) or not _fsio.is_fixed_drive(out):
            return None
        want = owners(video)
        seen, good = set(), []
        for m in video.get("marks") or ():
            p = m.get("path") if isinstance(m, dict) and m.get("status") == "exported" else None
            if not isinstance(p, str) or not p or not os.path.isabs(p) or _remote(p):
                continue
            root = os.path.normpath(_schemas.media_folder(p))
            key = _fsio.norm_path(root)
            if key in seen:
                continue
            seen.add(key)
            if _fsio.is_inside(root, out, strict=True) and os.path.isdir(root) and _names.read_owner(root) in want:
                good.append(root)
        return good[0] if len(good) == 1 else None
    except Exception as e:   # 設定が読めない・パスが変 など = 引けない(案件にしない)
        log.info("案件を引けませんでした: %s %s", e.__class__.__name__, str(e)[:150])
        return None


# ---------------------------------------------------------------- パス(案件の根からの相対)
def _abs(path, root):
    """相対のパス(区切り /)-> 案件の根の下の絶対パス。根の外に出るなら None。root が無い・絶対パス・空ならそのまま"""
    if not root or not isinstance(path, str) or not path or os.path.isabs(path):
        return path
    p = os.path.normpath(os.path.join(root, path))
    return p if _fsio.is_inside(p, root, strict=True) else None


def _rel(path, root):
    """絶対パス -> 案件の根からの相対(区切り /)。根の下でない・正規化されていない・戻すと同じ文字にならないなら、そのまま(往復で変えない)"""
    if not root or not isinstance(path, str) or not path or not os.path.isabs(path) or os.path.normpath(path) != path:
        return path
    if not _fsio.is_inside(path, root, strict=True):
        return path
    try:
        rel = os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path
    return rel if not rel.startswith("..") and _abs(rel, root) == path else path


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


def _ordered(marks, order):
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
            p = _abs(a["path"], root)
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
        video["path"] = _abs(video["path"], root) or ""
    video["duration"] = cs.get("duration") or 0.0
    video["analysis"] = copy.deepcopy(cs.get("analysis"))
    video["marks"] = _ordered(adopted + shown, src.get("order"))
    return video


def _rejected_of(c, sid, at):
    return {"source": sid, "id": c["id"], "start": c["start"], "end": c["end"], "at": at}


def split(video, root=None, prev=None, keep_candidates=False, at=None):
    """スタジオの配信 1 本(data.json の形)-> (候補.json, 採用.json) の中身。いつでも merge(*split(v), v["id"], root) == v(並びも)。
    - prev = 今の (候補, 採用)(None = 無い)。ほかの配信(sources)・この配信の消した印・状態・メモはそのまま引き継ぐ
    - 境目は Store.replace_auto と同じ(src auto で touched でない = 候補)。重ねたとき見えなくなる候補は採用の側に残す
    - keep_candidates=True(人の保存。① の 候補.json を書き換えない道): 候補は prev のこの配信の物をそのまま使い、
      画面から消えた候補(id が配信に無く、まだ見えている物)に消した印を足す(at = 印の時刻。None = 今)
    - root(案件の根)を渡すと、書き出しの結果の path と file の配信の path を根からの相対にする"""
    sid = video["id"]
    pc, pa = prev or (None, None)
    cands = copy.deepcopy(pc) if pc else empty_candidates()
    adopts = copy.deepcopy(pa) if pa else empty_adoptions()
    rejected = [r for r in adopts["rejected"] if r.get("source") == sid]
    adopts["marks"] = [m for m in adopts["marks"] if m.get("source") != sid]
    adopts["rejected"] = [r for r in adopts["rejected"] if r.get("source") != sid]
    marks = copy.deepcopy(video.get("marks") or [])
    in_video = {m["id"] for m in marks}
    if keep_candidates:
        pool = copy.deepcopy((cands["sources"].get(sid) or {}).get("auto") or [])
        by_id = {c["id"]: c for c in pool}
        cand_ids = {m["id"] for m in marks if by_id.get(m["id"]) == m}
    else:
        pool = [m for m in marks if m.get("src") == "auto" and not _marks.touched(m)]
        cand_ids = {m["id"] for m in pool}
    stamp = at if _marks.pos_int(at) else _schemas.now_ms()
    while True:   # 見えなくなる候補を採用の側へ移す(移すと採用が増えて、ほかの候補が隠れることがあるので、変わらなくなるまで)
        adopted = [m for m in marks if m["id"] not in cand_ids]
        if keep_candidates:
            gone = {r["id"] for r in rejected if r.get("id")}
            rejected += [_rejected_of(c, sid, stamp) for c in visible(pool, adopted, rejected)
                         if c["id"] not in in_video and c["id"] not in gone]
        bad = cand_ids - {c["id"] for c in visible(pool, adopted, rejected)}
        if not bad:
            break
        cand_ids -= bad
    src = {k: copy.deepcopy(v) for k, v in video.items() if k not in _VIDEO_OWN}
    if src.get("path"):
        src["path"] = _rel(src["path"], root)
    shown = [c for c in pool if c["id"] in cand_ids]
    if [m["id"] for m in _ordered(adopted + shown, None)] != [m["id"] for m in marks]:
        src["order"] = [m["id"] for m in marks]
    for m in adopted:
        if m.get("path"):
            m["path"] = _rel(m["path"], root)
        m["source"] = sid
    adopts["sources"][sid] = src
    adopts["marks"] += adopted
    adopts["rejected"] += rejected[-MAX_REJECTED:]
    cands["sources"][sid] = {"analysis": copy.deepcopy(video.get("analysis")), "duration": video.get("duration") or 0.0,
                             "auto": pool if keep_candidates else shown}
    return cands, adopts


# ---------------------------------------------------------------- 読み書き
def _read_doc(path, parse):
    """(整えた中身か None, ファイルがあるか)"""
    if not os.path.exists(path):
        return None, False
    raw = _fsio.read_json_or(path, None, MAX_BYTES, kind=dict, allow_nan=True)
    return (parse(raw) if raw is not None else None), True


def read(root):
    """案件の (候補, 採用) を読む(無いファイルは空の形)。置き場所が見えなければ ApiError 503(case_unseen)。
    候補.json が壊れていれば空(ログに 1 行。① が作り直せる)。採用.json が壊れていれば .bak を使い(ログ)、.bak も読めなければ ApiError 500(case_broken)
    = 人の採用を空と取り違えて上書きしない"""
    with lock(root):
        _need_root(root)
        cp, ap = work_path(root, CANDIDATES_NAME), work_path(root, ADOPTIONS_NAME)
        cands, there = _read_doc(cp, parse_candidates)
        if cands is None:
            if there:
                log.warning("候補.json が読めないので空として扱います: %s", cp)
            cands = empty_candidates()
        adopts, there = _read_doc(ap, parse_adoptions)
        if adopts is None and there:
            adopts, _ = _read_doc(ap + ".bak", parse_adoptions)
            if adopts is None:
                raise _errors.ApiError(BROKEN_CODE, "案件の採用の記録(採用.json)が壊れていて、控え(.bak)も読めません", 500, {"path": ap})
            log.warning("採用.json が読めないので 1 つ前の控え(.bak)を使います: %s", ap)
        return cands, adopts or empty_adoptions()


def _set_aside(path):
    """読めない 採用.json を <名前>.broken-<日時> へ退ける(.bak を壊れた物で上書きしないため)。退けられなければ OSError"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    name, n = path + ".broken-" + ts, 0
    while os.path.exists(name):
        n += 1
        name = "%s.broken-%s-%d" % (path, ts, n)
    os.replace(path, name)
    log.warning("読めない 採用.json を退けました: %s", name)


def write(root, candidates=None, adoptions=None):
    """案件の 候補.json・採用.json を書く(None の側は書かない)。順は 採用 → 候補・どちらも原子的。
    採用.json は書く前に今の物を .bak へ 1 世代(今の物が読めるときだけ。読めなければ .broken-<日時> へ退ける)。
    形の名前が違えば ValueError。置き場所が見えなければ ApiError 503(case_unseen)・書けなければ ApiError 500(save_failed)"""
    for doc, schema in ((candidates, CANDIDATES_SCHEMA), (adoptions, ADOPTIONS_SCHEMA)):
        if doc is not None and (not isinstance(doc, dict) or doc.get("schema") != schema):
            raise ValueError("案件のファイルの形が違います(%s)" % schema)
    with lock(root):
        _need_root(root)
        try:
            if adoptions is not None:
                ap = work_path(root, ADOPTIONS_NAME)
                if os.path.exists(ap):
                    if _read_doc(ap, parse_adoptions)[0] is not None:
                        try:
                            shutil.copyfile(ap, ap + ".bak")   # 1 つ前の世代(できなくても保存は続ける)
                        except OSError as e:
                            log.info("採用.json の控えを作れませんでした: %s", e)
                    else:
                        _set_aside(ap)
                _fsio.write_json(ap, adoptions, indent=1, fsync_required=True)
            if candidates is not None:
                _fsio.write_json(work_path(root, CANDIDATES_NAME), candidates, indent=1)
        except OSError as e:
            log.warning("案件のファイルを書けませんでした: %s %s", root, e)
            raise _errors.ApiError("save_failed", "案件のファイルを保存できませんでした(ディスクの空きなど)", 500, {"dir": root})
