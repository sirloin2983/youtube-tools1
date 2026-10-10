# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 評価ドリルと定点の「あと何分」(マスタープラン Q4。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (c))。

2026-10-04 夜に作り直し(ユーザーの指摘): 行を 1 行ずつ直す別のページをやめ、**評価用の動画 1 本(30〜40 秒)を、いつもの編集の画面
(1 文字起こし の校正)で開いて全部聞いて直す**。行と行のすき間(抜け)・話していない所の行(幻覚)・結合・分割まで直せるので、
「全部聞いた」文書だけを定点の正解にする。画面は編集の index.html の `?doc=<id>&drill=1`(帯は app-learn.js の drill*)。
  GET  /api/drill/next?skip=<id,…>  次の 1 本(評価用・文字起こし済み・まだ確かめていない・直近 10 分に更新していない・処理中でない・動画がある)を乱数で
  POST /api/drill/reviewed          {id, baseUpdatedAt, via?} 「全部聞いて直した」印 evalReviewed を書き、残りの行を校正済みに(409 = 別の所で変わった)
  POST /api/drill/unreviewed        {id, baseUpdatedAt} 印を外す(印を付けたときに校正済みにした行も戻す)
  GET  /api/drill/status            定点(確かめ済みの評価用の動画の長さ 15 分)の残りと条件(話者・配信・重なり・BGM・呼び名。確かめ済みの動画の中で数える)
  GET  /api/drill/candidates?id=    話者の候補(この文書の覚えた声 → メンバーのフォルダ → 配信の文脈 → ほかの覚えた声・メンバー)。
                                    話者のカードの「全行をこの人に」(既存の 1人指定 = ed_speakers.single_speaker)が使う

文書の印 `evalReviewed = {"at", "rows", "durationSec", "via"?}`(drill_is_reviewed で判定):
  - 付けるのは drill_reviewed だけ。画面の保存(sanitize_transcript)は base から引き継ぐだけで書き換えられない。評価用を外すと消える
  - 行の文字・時刻・話者を人が後から直しても残す(直したのは人なので)。機械が行を書いたら外す(ed_jobs.record_rerun = 再認識・
    疑わしい所の認識し直し、ed_store.fill_doc = 行の無い文書への文字起こし)。以前の版に戻すと、その版の印のまま

名前は serve.py からも見える(serve.py の _ED_MODULES の最後。ほかの部品と重ならないよう、名前は drill_ / DRILL_ で始める)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import os
import random
import threading

from pipeline.transcribe import roster as _roster  # noqa: E402  (名簿の呼び名。隣の部品)
import ed_jobs  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_speakers  # noqa: E402,F401
import ed_state  # noqa: E402,F401
from ytt import tools as _tools  # noqa: E402   (動画と音声の小道具。RS3-0A に ed_state から移した)
import ed_store  # noqa: E402,F401
from ytt import fsio as _fsio  # noqa: E402
from ytt import settings as _settings  # noqa: E402   評価用のフォルダの判定 eval_dirs・in_eval_dir(RS3-1 に ed_relink から ytt/settings へ)

DRILL_RECENT_SEC = 600       # 直近これだけの間に更新した文書は選ばない(編集の画面で開いている可能性)
DRILL_GOAL_SEC = 900         # 定点 = 確かめ済みの評価用の動画 15 分(マスタープラン Q4)
DRILL_MAX_SKIP = 500         # 「飛ばした」として受け取る id の数の上限
DRILL_MAX_CANDIDATES = 16
# 定点の条件(q3-q4-design.md の (c))。数えるのは確かめ済みの評価用の文書の「校正済み・聞き取れない印なし」の行
DRILL_CONDS = (("speakers", "話者", 4, "人"), ("streams", "配信", 3, "本"), ("overlap", "声の重なり", 30, "秒"),
               ("bgm", "BGM", 30, "秒"), ("calls", "呼び名", 10, "行"))

_drill_cache = {}            # tid -> ((文書の要約の鍵, 名簿の版), 要約, 名簿によらない要約 drill_doc_summary)。文書が変わったときだけ文書を読む
_drill_cache_lock = threading.Lock()


def drill_is_reviewed(doc):
    """評価用で、動画を全部聞いて確かめた文書か(定点に数える判定。dev/eval_asr.py などの測る道具が「確かめ済みだけ」を選ぶときも、この条件で選ぶ)"""
    return isinstance(doc, dict) and doc.get("evalSet") is True and isinstance(doc.get("evalReviewed"), dict)


def drill_reviewed_sec(doc):
    """確かめ済みの文書の長さ(秒)= 印を付けたときの動画の長さ(durationSec)。無ければ今の文書の長さ(範囲 → 動画 → 最後の行の終わり)"""
    rv = doc.get("evalReviewed") if isinstance(doc.get("evalReviewed"), dict) else {}
    sec = ed_state.num(rv.get("durationSec"))
    return sec if sec is not None and sec > 0 else ed_store.doc_length(doc)


def drill_stream_key(doc):
    """配信の見分け: 元の配信の ID(切り抜きの clip)→ 無ければ動画の入ったフォルダ(メンバーのフォルダなら名前)"""
    clip = doc.get("clip") if isinstance(doc.get("clip"), dict) else {}
    src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
    vid = str(src.get("videoId") or clip.get("videoId") or "").strip()
    if vid:
        return "v:" + vid
    path = str(doc.get("sourcePath") or "")
    if not path:
        return ""
    folder = os.path.basename(os.path.dirname(path))
    m = ed_relink._EVAL_MEMBER_RE.match(folder) if folder != ed_relink.EVAL_STAGING else None
    return ("m:" + ed_relink._norm_member(m.group(1))) if m else ("d:" + os.path.normcase(os.path.dirname(path)))


def _drill_text_rows(segs):
    return [g for g in segs if str(g.get("text") or "").strip()]


def drill_doc_summary(doc):
    """文書 1 本のドリルの要約(評価用でなければ {"eval": False})。drill_docs が文書の要約(ed_store.transcript_summary)の鍵ごとに作って覚える。
    呼び名の行の数は名簿で変わるので、ここでは行の文字 callTexts だけを持ち、drill_docs が今の名簿で数える"""
    if doc.get("evalSet") is not True:
        return {"eval": False}
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    rows = _drill_text_rows(segs)
    rv = drill_is_reviewed(doc)
    good = [g for g in segs if ed_store.good_row(g)] if rv else []   # 条件は確かめ済みの文書の中だけで数える
    spk = {}
    for g in good:
        nm = names.get(g.get("speaker"), "").strip()
        if nm and not ed_speakers.is_generic_speaker_name(nm):
            spk.setdefault(ed_speakers._spk_name_key(nm), nm)
    ef = doc.get("effort") if isinstance(doc.get("effort"), dict) else {}
    return {"eval": True, "updatedAt": ed_state.plain_int(doc.get("updatedAt")) or 0, "lastAt": ed_state.plain_int(ef.get("lastAt")) or 0,
            "sourcePath": str(doc.get("sourcePath") or ""), "rows": len(rows),
            "spkRows": sum(1 for g in rows if g.get("speaker") and g.get("speaker") in names),   # 話者のある文字の行(自動の判別の後追い = ed_evalbatch が読む。v0.50.0)
            "reviewed": rv, "sec": round(drill_reviewed_sec(doc), 1) if rv else 0.0, "names": spk,
            "overlapSec": sum(ed_store.row_dur(g) for g in good if "overlap" in (g.get("tags") or [])),
            "bgmSec": sum(ed_store.row_dur(g) for g in good if "bgm" in (g.get("tags") or [])),
            "callTexts": [str(g.get("text") or "") for g in good],
            "stream": drill_stream_key(doc) if rv else ""}


def _with_calls(s):
    """ドリルの要約(callTexts)→ 呼び名の行の数 callRows(今の名簿で数える。名簿は良い行があるときだけ読む)"""
    if not s.get("eval"):
        return s
    out = {k: v for k, v in s.items() if k != "callTexts"}
    texts = s.get("callTexts") or []
    r = _roster.load(_roster.ROSTER) if texts else None
    out["callRows"] = sum(1 for t in texts if _roster.find_in_text(t, r)) if texts else 0
    return out


def _drill_part(path):
    """文書のファイル → ドリルの要約(drill_doc_summary)。読めない・形の崩れた文書は None(ドリルに数えない。一覧は止めない)"""
    d = ed_store._load_doc(path)
    if d is None:
        return None
    try:
        return drill_doc_summary(d)
    except Exception as e:   # 形の崩れた文書(手で書き換えたなど)でもドリルの一覧を止めない
        ed_state.log.warning("文書の要約(ドリル)を作れませんでした: %s", e.__class__.__name__)
        return None


def drill_docs():
    """[(tid, 要約)](評価用でない文書は {"eval": False})。文書が変わったか(文書の要約 ed_store.transcript_summary の鍵 = パス・更新日時・大きさ)で決め、
    変わったときだけ文書を読んでドリルの要約を作る(RS3-E5a まで文書の要約が _drill として一緒に作っていた = ② が ④ を読んでいた。決定 3-25 #8 で自前に)。
    呼び名の行の数は、文書の鍵と名簿の版が同じなら前の結果(_drill_cache)"""
    out, seen, rs = [], set(), ed_state.file_stamp(_roster.ROSTER)
    for tid in sorted(ed_store._tids()):
        seen.add(tid)
        sm = ed_store.transcript_summary(tid)
        if not sm:
            continue
        key = (sm["_key"], rs)
        with _drill_cache_lock:
            hit = _drill_cache.get(tid)
        if hit and hit[0] == key:
            out.append((tid, hit[1]))
            continue
        raw = hit[2] if hit and hit[0][0] == sm["_key"] else _drill_part(sm["_key"][0])   # 名簿だけ変わったときは文書を読み直さない
        if raw is None:
            continue
        s = _with_calls(raw)
        with _drill_cache_lock:
            _drill_cache[tid] = (key, s, raw)
        out.append((tid, s))
    ed_store.prune_cache(_drill_cache, seen, _drill_cache_lock)
    return out


# ---------- 定点の「あと何分」と条件 ----------
def drill_status():
    """GET /api/drill/status -> {"goalSec", "reviewedSec", "leftSec", "docs"(評価用), "reviewedDocs", "pendingDocs"(文字起こし済み・まだ),
    "untranscribed"(評価用で文字のある行が無い・まだ), "conds": [{key, label, have, need, unit, ok, items?}], "ready"}。
    定点 = 確かめ済み(evalReviewed)の評価用の動画の長さの合計。条件も確かめ済みの動画の中で数える(すき間まで聞いたものだけが正解になる)"""
    sec, docs, rdocs, pend, untx, names, streams, ov, bgm, calls = 0.0, 0, 0, 0, 0, {}, set(), 0.0, 0.0, 0
    for _tid, s in drill_docs():
        if not s.get("eval"):
            continue
        docs += 1
        if not s["reviewed"]:
            if s["rows"]:
                pend += 1
            else:
                untx += 1
            continue
        rdocs += 1
        sec += s["sec"]
        for k, nm in s["names"].items():
            names.setdefault(k, nm)
        if s["stream"]:
            streams.add(s["stream"])
        ov += s["overlapSec"]
        bgm += s["bgmSec"]
        calls += s["callRows"]
    have = {"speakers": len(names), "streams": len(streams), "overlap": int(ov), "bgm": int(bgm), "calls": calls}
    conds = []
    for key, label, need, unit in DRILL_CONDS:
        c = {"key": key, "label": label, "have": have[key], "need": need, "unit": unit, "ok": have[key] >= need}
        if key == "speakers":
            c["items"] = sorted(names.values())[:12]
        conds.append(c)
    return {"goalSec": DRILL_GOAL_SEC, "reviewedSec": round(sec, 1), "leftSec": round(max(0.0, DRILL_GOAL_SEC - sec), 1),
            "docs": docs, "reviewedDocs": rdocs, "pendingDocs": pend, "untranscribed": untx,
            "conds": conds, "ready": sec >= DRILL_GOAL_SEC and all(c["ok"] for c in conds)}


# ---------- 次の 1 本 ----------
def _drill_skip_ids(skip):
    if isinstance(skip, str):
        skip = skip.split(",")
    return {str(x).strip() for x in list(skip or [])[:DRILL_MAX_SKIP] if ed_state.TID_RE.match(str(x).strip())}


def drill_next(skip=(), seed=None):
    """GET /api/drill/next?skip= -> {"id": 次の文書 | None, "title", "reason"(無いとき), "counts"}。
    評価用・文字起こし済み(文字のある行がある)・まだ確かめていない・直近 10 分に更新していない(updatedAt と校正の時間の lastAt の新しい方)・
    処理中(話者判別など)でない・今回のドリルで飛ばしていない文書から、動画の単位で乱数で 1 本(自信の低いものを選ぶと数字が悪い側に偏るため)。
    動画の無い文書(ネットワーク上は調べずに除く)は聞けないので除く"""
    skip = _drill_skip_ids(skip)
    now, busy = ed_state.now_ms(), _busy_tids()
    n = {"eval": 0, "reviewed": 0, "untranscribed": 0, "skipped": 0, "recent": 0, "busy": 0, "noMedia": 0}
    pool = []
    for tid, s in drill_docs():
        if not s.get("eval"):
            continue
        n["eval"] += 1
        if s["reviewed"]:
            n["reviewed"] += 1
        elif not s["rows"]:
            n["untranscribed"] += 1
        elif tid in skip:
            n["skipped"] += 1
        elif now - max(s["updatedAt"], s["lastAt"]) < DRILL_RECENT_SEC * 1000:
            n["recent"] += 1
        elif tid in busy:
            n["busy"] += 1
        else:
            pool.append((tid, s["sourcePath"]))
    random.Random(seed).shuffle(pool)
    for tid, src in pool:
        if not _media_ok(src):
            n["noMedia"] += 1
            continue
        try:
            d = ed_store.read_transcript(tid)
        except ed_state.ApiError:
            continue
        return {"id": tid, "title": str(d.get("title") or d.get("sourceName") or "")[:120], "counts": n}
    return {"id": None, "reason": _drill_why_none(n), "counts": n}


def _drill_why_none(n):
    if not n["eval"]:
        return "評価用の文字起こしがまだありません(⚙ の「評価用のフォルダ」の「仮置きをまとめて文字起こし」で作れます)"
    parts = [(n["reviewed"], "確かめ済み"), (n["untranscribed"], "まだ文字起こししていない"), (n["skipped"], "このドリルで飛ばした"),
             (n["recent"], "直近 10 分に直した"), (n["busy"], "処理中の"), (n["noMedia"], "動画が見つからない")]
    return "次に出せる評価用の動画がありません(%s)" % "・".join("%s %d 本" % (lb, c) for c, lb in parts if c)


# ---------- 確かめ済みの印 ----------
def _drill_check(base, obj):
    if base.get("evalSet") is not True:
        raise ed_state.ApiError("not_eval", "評価用の文字起こしではありません(確かめ済みの印は評価用の文字起こしだけに付けます)", 400)
    b = obj.get("baseUpdatedAt")
    if ed_state.plain_int(b) is None:
        raise ed_state.ApiError("bad_request", "baseUpdatedAt(読み込んだときの版)を付けてください", 400)
    if b != base.get("updatedAt"):
        raise ed_state.ApiError("conflict", "この文字起こしは別の所(別の画面・再認識・話者判別など)で先に変わりました。読み込み直してから、もう一度押してください", 409)


def _drill_write(tid, base, doc):
    if (ed_state.plain_int(base.get("updatedAt")) or 0) >= doc["updatedAt"]:   # 必ず前より大きく(開いている編集の画面の次の保存を、既存の 409 の案内に乗せる)
        doc["updatedAt"] = (ed_state.plain_int(base.get("updatedAt")) or 0) + 1
    ed_store.effort_rows(base, doc)   # 校正済みにした行・外した行の数(校正の手間。Q2)
    ed_store.apply_edit_cuts(tid, doc)
    ed_store.snapshot(tid, False)   # 履歴が残せなくても保存は止めない
    ed_store.write_doc(tid, doc)


def drill_reviewed(obj):
    """POST /api/drill/reviewed {id, baseUpdatedAt, via?: "drill" | "editor"} -> {"ok", "updatedAt", "evalReviewed", "proofed", "noSpeaker"}。
    「動画を全部聞いて直した」: 文書に evalReviewed = {at, rows, durationSec, via?} を書き、まだ校正済みでない(文字のある)行を校正済みにする(proofedAt = 今)。
    **画面は編集中の内容を保存し終えてから呼ぶ**(ここは保存済みの内容に印を付けるだけ)。保存のロックの中で読み、baseUpdatedAt が違えば 409・
    updatedAt を上げる・履歴を残す。行が 0 の動画(本当に無音)でも、文字起こし済みなら付けられる。もう付いていれば付け直す(時刻・長さを今に)"""
    tid = str(obj.get("id") or "")
    with ed_store._save_lock:
        base = ed_store.read_transcript(tid)
        _drill_check(base, obj)
        if tid in _busy_tids():
            raise ed_state.ApiError("busy", "この文字起こしは処理中です(話者判別などが終わってから、もう一度押してください)", 409)
        segs = [dict(g) for g in base.get("segments") or [] if isinstance(g, dict)]
        if not base.get("model") and not _drill_text_rows(segs):
            raise ed_state.ApiError("not_transcribed", "まだ文字起こししていません(文字起こししてから、全部聞いて確かめてください)", 400)
        n = 0
        for g in _drill_text_rows(segs):
            if g.get("proofed") is not True:
                g["proofed"] = True
                n += 1
        doc = ed_store.sanitize_transcript({"title": base.get("title", ""), "speakers": base.get("speakers") or [], "segments": segs}, base)
        rows = _drill_text_rows(doc["segments"])
        ids = {s["id"] for s in doc["speakers"]}
        # at = 校正済みにした行の proofedAt と同じ時刻(sanitize の「今」)。取り消しで、この印が校正済みにした行だけを戻すのに使う
        rv = {"at": doc["updatedAt"], "rows": len(rows), "durationSec": round(ed_store.doc_length(doc), 1)}
        if obj.get("via") in ("drill", "editor"):
            rv["via"] = obj["via"]
        doc["evalReviewed"] = rv
        _drill_write(tid, base, doc)
    return {"ok": True, "updatedAt": doc["updatedAt"], "evalReviewed": rv, "proofed": n, "noSpeaker": sum(1 for g in rows if g.get("speaker") not in ids)}


def drill_unreviewed(obj):
    """POST /api/drill/unreviewed {id, baseUpdatedAt} -> {"ok", "updatedAt", "unproofed"}。確かめ済みの印を外す(取り消し)。
    印を付けたときに校正済みにした行(proofedAt が印の時刻と同じ = その後に外して付け直していない行)は、校正済みも戻す。
    それより前から校正済みだった行はそのまま。印が無ければ何もしない"""
    tid = str(obj.get("id") or "")
    with ed_store._save_lock:
        base = ed_store.read_transcript(tid)
        _drill_check(base, obj)
        rv = base.get("evalReviewed")
        if not isinstance(rv, dict):
            return {"ok": True, "updatedAt": base.get("updatedAt"), "unproofed": 0}
        at = ed_state.plain_int(rv.get("at"))
        segs, n = [dict(g) for g in base.get("segments") or [] if isinstance(g, dict)], 0
        for g in segs:
            if at and g.get("proofed") is True and g.get("proofedAt") == at:
                g.pop("proofed", None)
                g.pop("proofedAt", None)
                n += 1
        doc = ed_store.sanitize_transcript({"title": base.get("title", ""), "speakers": base.get("speakers") or [], "segments": segs}, base)
        doc.pop("evalReviewed", None)
        _drill_write(tid, base, doc)
    return {"ok": True, "updatedAt": doc["updatedAt"], "unproofed": n}


# ---------- 話者の候補 ----------
def _member_name(folder):
    b = os.path.basename(folder.rstrip("\\/"))
    if b == ed_relink.EVAL_STAGING:
        return ""
    m = ed_relink._EVAL_MEMBER_RE.match(b)
    return m.group(1).strip() if m else ""


def _own_member(path, dirs):
    """動画の入ったフォルダから評価用のフォルダまでさかのぼって、最初の「…数字_名前」のフォルダの名前(評価用のフォルダの中だけ)"""
    if not path or not _settings.in_eval_dir(path, dirs):
        return ""
    roots = [ed_state.norm_path(d) for d in dirs]
    cur = os.path.dirname(os.path.abspath(path))
    for _ in range(ed_relink.EVAL_WALK_DEPTH + 1):
        if os.path.normcase(cur) in roots:
            return ""
        nm = _member_name(cur)
        if nm:
            return nm
        up = os.path.dirname(cur)
        if up == cur:
            break
        cur = up
    return ""


def _all_members(dirs):
    """評価用のフォルダの下のメンバーのフォルダの名前(「1_JP」「01_0期生」のような上の段のまとまりは除く = 中に別のメンバーのフォルダがあるもの)"""
    folders = []
    for d in dirs:
        try:
            folders += list(ed_relink._eval_members(d).values())
        except OSError:
            continue
    keys = [os.path.normcase(f).rstrip("\\/") + os.sep for f in folders]
    out = []
    for f, k in zip(folders, keys):
        if any(o != k and o.startswith(k) for o in keys):
            continue
        nm = _member_name(f)
        if nm and nm not in out:
            out.append(nm)
    return sorted(out)


def _diar_voices(tid):
    """この文書の話者判別の記録で、覚えた声と近かった名前(付けた名前 → 点数の高い順)"""
    d = ed_speakers.read_diar(tid) or {}
    sp = (((d.get("latest") or {}).get("voices") or {}).get("speakers") or {}) if isinstance(d, dict) else {}
    items = [v for v in sp.values() if isinstance(v, dict)]
    items.sort(key=lambda v: (0 if v.get("decided") else 1, -(v.get("score") or 0)))
    out = []
    for v in items:
        for nm in (v.get("decided"), v.get("top")):
            if isinstance(nm, str) and nm.strip() and nm not in out:
                out.append(nm.strip())
    return out


def drill_candidates_for(tid, doc, dirs=None, voices=None):
    """[{"name", "from": voice|folder|stream, "near": この文書の手がかりか}](近いものから。一般的な名前は除く)"""
    out, seen = [], set()
    dirs = _settings.eval_dirs() if dirs is None else dirs

    def add(name, src, near):
        nm = str(name or "").strip()[:30]
        k = ed_speakers._spk_name_key(nm)
        if not nm or k in seen or ed_speakers.is_generic_speaker_name(nm) or len(out) >= DRILL_MAX_CANDIDATES:
            return
        seen.add(k)
        out.append({"name": nm, "from": src, "near": near})

    for nm in _diar_voices(tid):                                  # 1 覚えた声(この文書の話者判別で近かった声)
        add(nm, "voice", True)
    add(_own_member(str(doc.get("sourcePath") or ""), dirs), "folder", True)   # 2 メンバーのフォルダ(動画の入ったフォルダ)
    try:
        ctx = ed_jobs.stream_context(doc)                         # 3 配信の文脈(チャンネル名・コラボ相手・題名から名簿で)
    except Exception as e:   # 他のツールのデータ・名簿が読めなくても候補を出す
        ed_state.log.info("配信の文脈を読めませんでした: %s", str(e)[:120])
        ctx = {"members": []}
    for m in ctx.get("members") or []:
        add(m.get("name"), "stream", True)
    for v in sorted(voices if voices is not None else _learned_voices(), key=lambda x: -x[1]):   # ほかの覚えた声(使った秒の長い順)
        add(v[0], "voice", False)
    for nm in _all_members(dirs):                                  # ほかのメンバーのフォルダ
        add(nm, "folder", False)
    return out


def _learned_voices():
    agg = {}
    for xs in ed_speakers.voices_summary().values():
        for x in xs:
            if not x.get("generic"):
                agg[x["name"]] = agg.get(x["name"], 0.0) + float(x.get("sec") or 0.0)
    return list(agg.items())


def drill_candidates(tid):
    """GET /api/drill/candidates?id= -> {"candidates", "eval", "rows", "noSpeaker", "suggest"}(読むだけ)"""
    doc = ed_store.read_transcript(tid)
    ids = {s.get("id") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()]
    cands = drill_candidates_for(tid, doc)
    near = [c for c in cands if c["near"]]
    return {"candidates": cands, "eval": doc.get("evalSet") is True, "rows": len(rows),
            "noSpeaker": sum(1 for g in rows if g.get("speaker") not in ids), "suggest": near[0]["name"] if near else ""}


# ---------- 処理中・動画 ----------
def _busy_tids():
    with ed_jobs._jobs_lock:
        return {str((j.get("spec") or {}).get("tid") or j.get("tid") or "") for j in ed_jobs._jobs.values() if j.get("state") in ed_jobs.ACTIVE_STATES}


def _media_ok(path):
    if not path or _fsio.is_network_path(path):   # ネットワーク上のパスには触らない(資格情報を送らない)
        return False
    try:
        _tools.check_source(path)
        return True
    except ed_state.ApiError:
        return False
