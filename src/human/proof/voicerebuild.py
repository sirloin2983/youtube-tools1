"""覚えた声を 1 行ずつ外してまとめ直す(10-25 ユーザーとまとめ役が 1 行ずつ聞いて確かめた結果。資料の git:before-1028-cleanup:plan/間違った正解のリスク-1025.md の 6)。

登録簿(flow/diar の voices/<モデル>.json)の 1 人分は、混ぜた声の特徴 1 つと learnedFrom(どの文書のどの行から覚えたか)しか持たないので、
行を外すには、learnedFrom の行を 1 行ずつ声の特徴にし直して、外す行を除いて混ぜ直す:
  - 行の音: 元の動画があれば動画から、無ければ切り出して残した行の音(human/proof/voiceclips.timeline_wav)から(覚えるジョブと同じ)
  - 行ごとの特徴は voices/<モデル>.rows.json({名前: {"文書#行": {"vec", "sec", "short"}}})に控える(次からは取り直さない)
  - 混ぜ方: 行の秒で重み・ショート由来(学習用データ)は flow/diar.SHORT_WEIGHT 倍。learnedFrom の rows に行の id が無い文書(画面の「声を覚える」)は、
    今の文書の声の材料の決まり(speakers.voice_learn_plan)の行をその人の行として使う
  - 外した行はその人の excluded("文書#行")に覚える = 覚え直しを再開しても材料に数えない(human/check/voice._learned_rows)
  - まとめ直す前の登録簿は voices/<モデル>.json.bak-<時刻> に写す(戻すときはこれを元の名前に)
声を覚えるジョブ(voice-learn)と同時に動かさない(呼び手 = dev/voice_rebuild.py は、覚え直しの一時止め RELEARN_PAUSED の間に流す)。
"""
import math
import os
import shutil
import time

from flow import diar as _diar, jobs as _heavy, voicematerial as _vm
from ytt import errors as _errors, fsio, schemas as _yschemas, tools as _tools
from . import speakers as _speakers, store, voiceclips as _voiceclips


def rows_path(emb):
    return _diar.row_vectors_path(emb)


def _unit(v):
    s = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / s for x in v]


def _doc_rows(doc, name, ids):
    """文書のその人の声の材料の行 [(行 id, 開始, 終了)](ids があればその行・無ければ今の決まりの行)"""
    if ids:
        segs = {str(g.get("id")): g for g in doc.get("segments") or () if isinstance(g, dict)}
        out = []
        for r in ids:
            g = segs.get(str(r))
            a, b = (_yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))) if g else (None, None)
            if a is not None and b is not None and b > a:
                out.append((str(r), a, b))
        return out
    plan = _speakers.voice_learn_plan(doc)
    return _doc_rows(doc, name, plan["rowIds"].get(name)) if plan["rowIds"].get(name) else []


def row_vectors(emb, tid, rows, job=None):
    """文書 1 本の行ごとの声の特徴 -> {行 id: 特徴}(取れなかった行は入れない)"""
    doc = store.read_transcript(tid)
    job = job if job is not None else {"id": "voice-rebuild-%d" % int(time.time() * 1000), "state": "running", "progress": 0.0}
    with _heavy.job_temp_wav(job) as wav:
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        try:
            src = _tools.check_source(doc.get("sourcePath"))
            hints = {"sourcePath": src, "start": start, "end": end}
        except _errors.ApiError:
            if not _voiceclips.timeline_wav(tid, wav, start, end):
                return {}
            hints = {"start": start, "wavReady": True}
        vecs = _diar.embed(job, {"embedding": emb}, wav, [[(a, b)] for _r, a, b in rows], hints)
    return {r: v for (r, _a, _b), v in zip(rows, vecs) if v}


def backfill(emb, name, log=None, embed=None):
    """その人の learnedFrom の行のうち、音(元の動画か行の音)がまだ残っていて控えに無い行の特徴を取って控える(登録簿は変えない)-> 足した行の数"""
    log = log or (lambda m: None)
    embed = embed or row_vectors
    v = _diar.load_voices(emb).get(name)
    if not isinstance(v, dict):
        return 0
    have = fsio.read_json_or(rows_path(emb), {}, kind=dict).get(name) or {}
    n = 0
    for lf in v.get("learnedFrom") or ():
        if not isinstance(lf, dict) or not lf.get("doc"):
            continue
        tid = str(lf["doc"])
        try:
            doc = store.read_transcript(tid)
        except _errors.ApiError:
            continue
        need = [(r, a, b) for r, a, b in _doc_rows(doc, name, lf.get("rows")) if "%s#%s" % (tid, r) not in have]
        if not need:
            continue
        try:
            got = embed(emb, tid, need)
        except _errors.ApiError:
            got = {}
        short = _vm.is_short(doc.get("sourcePath"))
        items = {"%s#%s" % (tid, r): {"vec": [round(x, 6) for x in got[r]], "sec": round(b - a, 2), "short": bool(short)} for r, a, b in need if r in got}
        _diar.save_row_vectors(emb, name, items)
        n += len(items)
    log("行ごとの特徴の控え: %s に %d 行を足しました" % (name, n))
    return n


def rebuild(emb, name, exclude=(), log=None, embed=None, now=None):
    """その人の声を、外す行(exclude = ["文書#行"])を除いてまとめ直す -> {"rows", "excluded", "sec", "backup"}。
    embed(emb, tid, rows) -> {行 id: 特徴}(テストの差し替え。既定 row_vectors)"""
    log = log or (lambda m: None)
    embed = embed or row_vectors
    now = time.time() if now is None else now
    voices = _diar.load_voices(emb)
    v = voices.get(name)
    if not isinstance(v, dict):
        raise _errors.ApiError("not_found", "登録簿にその人がいません: %s" % name, 404)
    excluded = sorted(set(v.get("excluded") or ()) | {str(x) for x in exclude})
    cache = fsio.read_json_or(rows_path(emb), {}, kind=dict)
    mine = cache.setdefault(name, {})
    total, acc, used, short_sec = 0.0, None, [], 0.0
    learned = []
    for lf in v.get("learnedFrom") or ():
        if not isinstance(lf, dict) or not lf.get("doc"):
            continue
        tid = str(lf["doc"])
        try:
            doc = store.read_transcript(tid)
        except _errors.ApiError:
            log("まとめ直し: %s の文書 %s が読めないので飛ばしました" % (name, tid))
            continue
        rows = _doc_rows(doc, name, lf.get("rows"))
        short = _vm.is_short(doc.get("sourcePath"))
        need = [(r, a, b) for r, a, b in rows if "%s#%s" % (tid, r) not in mine]
        if need:
            got = embed(emb, tid, need)
            for r, a, b in need:
                if r in got:
                    mine["%s#%s" % (tid, r)] = {"vec": [round(x, 6) for x in got[r]], "sec": round(b - a, 2), "short": bool(short)}
        keep = []
        for r, a, b in rows:
            key = "%s#%s" % (tid, r)
            it = mine.get(key)
            if key in excluded or not it:
                continue
            w = float(it["sec"]) * (_diar.SHORT_WEIGHT if it.get("short") else 1.0)
            acc = [w * x for x in it["vec"]] if acc is None else [p + w * x for p, x in zip(acc, it["vec"])]
            total += float(it["sec"])
            short_sec += float(it["sec"]) if it.get("short") else 0.0
            keep.append(r)
            used.append(key)
        if keep:
            learned.append(dict(lf, rows=keep, sec=round(sum(float(mine["%s#%s" % (tid, r)]["sec"]) for r in keep), 1)))
    if acc is None:
        raise _errors.ApiError("no_rows", "まとめ直せる行がありません(%s)" % name, 400)
    backup = _diar.voices_path(emb) + ".bak-%d" % int(now)
    shutil.copyfile(_diar.voices_path(emb), backup)
    with _diar.voices_edit(emb) as cur:
        e = dict(cur.get(name) or {})
        e.update(vec=[round(x, 6) for x in _unit(acc)], rows=len(used), sec=round(total, 1), learnedFrom=learned, excluded=excluded,
                 updatedAt=int(now * 1000), rebuiltAt=int(now * 1000))
        if short_sec:
            e["shortSec"] = round(short_sec, 1)
        else:
            e.pop("shortSec", None)
        cur[name] = e
    fsio.write_json(rows_path(emb), cache, indent=None)
    log("まとめ直し: %s を %d 行(%.1f 秒)でまとめ直しました(外した行 %d・前の登録簿の写し %s)" % (name, len(used), total, len(excluded), os.path.basename(backup)))
    return {"rows": len(used), "excluded": excluded, "sec": round(total, 1), "backup": backup}
