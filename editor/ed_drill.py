# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 評価ドリルと定点の「あと何分」(マスタープラン Q4。docs/plan/q3-q4-design.md の (c))。

評価用(evalSet)の文書から、まだ校正していない行を乱数で 20 行ほど選び(同じ文書から 2 行まで)、別のページ drill.html で
1 行ずつ聞いて直す。編集の画面は 1 文書をまるごと保存する作りで、20 文書 × 1 行と相性が悪いため、保存は行ごと。
  GET  /api/drill/pick?n=&seed=   行を選ぶ(読むだけ)
  POST /api/drill/row             1 行を保存(保存のロックの中で読み、updatedAt が違えば 409・proofedAt・校正の手間・履歴・updatedAt を上げる)
  GET  /api/drill/status          定点(評価用の校正済み 15 分)の残りと条件(話者・配信・重なり・BGM・呼び名)
  GET  /api/drill/candidates?id=  話者の候補(この文書の覚えた声 → メンバーのフォルダ → 配信の文脈 → ほかの覚えた声・メンバー)。
                                  編集の話者のカードの「全行をこの人に」(既存の 1人指定 = ed_speakers.single_speaker)も使う

名前は serve.py からも見える(serve.py の _ED_MODULES の最後。ほかの部品と重ならないよう、名前は drill_ / DRILL_ で始める)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import json
import os
import random
import re
import threading
import time

import roster as _roster  # noqa: E402  (名簿の呼び名。隣の部品)
import ed_jobs  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_speakers  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
from ytt_core import fsio as _fsio  # noqa: E402

DRILL_ROWS = 20              # 1 回に出す行の数
DRILL_ROWS_MAX = 50
DRILL_PER_DOC = 2            # 同じ文書から選ぶ行の上限(1 本の配信に偏らないように)
DRILL_RECENT_SEC = 600       # 直近これだけの間に更新した文書は選ばない(編集の画面で開いている可能性)
DRILL_GOAL_SEC = 900         # 定点 = 評価用の校正済み 15 分(マスタープラン Q4)
DRILL_MAX_ROW_SEC = 600      # 1 行に足す校正の時間の上限(画面が数えた秒。離席したまま次へ進んだときに膨らまないように)
DRILL_MAX_CANDIDATES = 16
# 定点の条件(q3-q4-design.md の (c))。数えるのは評価用の文書の「校正済み・聞き取れない印なし」の行(= 15 分に数える行と同じ)
DRILL_CONDS = (("speakers", "話者", 4, "人"), ("streams", "配信", 3, "本"), ("overlap", "声の重なり", 30, "秒"),
               ("bgm", "BGM", 30, "秒"), ("calls", "呼び名", 10, "行"))

_drill_cache = {}            # tid -> ((更新日時ns, 大きさ, 名簿の版), 要約)
_drill_cache_lock = threading.Lock()


def _now_ms():
    return int(time.time() * 1000)


def _num(v):
    return ed_state.num(v, 0.0) or 0.0


def _dur(g):
    return max(0.0, _num(g.get("end")) - _num(g.get("start")))


def _roster_stamp():
    try:
        st = os.stat(ed_state.ROSTER)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _plain_int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


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


def _good(g):
    """定点に数える行(校正済み・聞き取れない印なし。progress_stats と同じ)"""
    return g.get("proofed") is True and "unclear" not in (g.get("tags") or [])


def _pickable(g):
    """ドリルに出せる行(文字あり・未校正・聞き取れない印なし・長さあり)"""
    return (g.get("proofed") is not True and str(g.get("text") or "").strip() and "unclear" not in (g.get("tags") or [])
            and isinstance(g.get("id"), str) and _num(g.get("end")) > _num(g.get("start")))


def _doc_summary(doc):
    if doc.get("evalSet") is not True:
        return {"eval": False}
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    good = [g for g in segs if _good(g)]
    r = _roster.load(ed_state.ROSTER)
    spk = {}
    for g in good:
        nm = names.get(g.get("speaker"), "").strip()
        if nm and not ed_speakers.is_generic_speaker_name(nm):
            spk.setdefault(ed_speakers._spk_name_key(nm), nm)
    ef = doc.get("effort") if isinstance(doc.get("effort"), dict) else {}
    return {"eval": True, "updatedAt": _plain_int(doc.get("updatedAt")) or 0, "lastAt": _plain_int(ef.get("lastAt")) or 0,
            "sourcePath": str(doc.get("sourcePath") or ""),
            "cand": [g["id"] for g in segs if _pickable(g)],
            "sec": sum(_dur(g) for g in good), "rows": len(good), "names": spk,
            "overlapSec": sum(_dur(g) for g in good if "overlap" in (g.get("tags") or [])),
            "bgmSec": sum(_dur(g) for g in good if "bgm" in (g.get("tags") or [])),
            "callRows": sum(1 for g in good if _roster.find_in_text(str(g.get("text") or ""), r)),
            "stream": drill_stream_key(doc) if good else ""}


def drill_docs():
    """[(tid, 要約)](評価用でない文書は {"eval": False})。更新日時と大きさ(と名簿の版)が同じなら読み直さない"""
    out, seen, rs = [], set(), _roster_stamp()
    if not os.path.isdir(ed_state.TX_DIR):
        return out
    for name in sorted(os.listdir(ed_state.TX_DIR)):
        tid = name[:-5]
        if not name.endswith(".json") or not ed_state.TID_RE.match(tid):
            continue
        seen.add(tid)
        try:
            st = os.stat(ed_store.tx_path(tid))
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size, rs)
        with _drill_cache_lock:
            hit = _drill_cache.get(tid)
        if hit and hit[0] == key:
            out.append((tid, hit[1]))
            continue
        try:
            with open(ed_store.tx_path(tid), "r", encoding="utf-8") as f:
                s = _doc_summary(json.load(f))
        except (OSError, ValueError):
            continue
        with _drill_cache_lock:
            _drill_cache[tid] = (key, s)
        out.append((tid, s))
    with _drill_cache_lock:
        for k in [k for k in _drill_cache if k not in seen]:
            _drill_cache.pop(k, None)
    return out


# ---------- 定点の「あと何分」と条件 ----------
def drill_status():
    """GET /api/drill/status -> {"goalSec", "proofedSec", "leftSec", "rows", "docs", "pendingRows", "conds": [{key, label, have, need, unit, ok, items?}], "ready"}"""
    sec, rows, docs, pend, names, streams, ov, bgm, calls = 0.0, 0, 0, 0, {}, set(), 0.0, 0.0, 0
    for _tid, s in drill_docs():
        if not s.get("eval"):
            continue
        docs += 1
        sec += s["sec"]
        rows += s["rows"]
        pend += len(s["cand"])
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
    return {"goalSec": DRILL_GOAL_SEC, "proofedSec": round(sec, 1), "leftSec": round(max(0.0, DRILL_GOAL_SEC - sec), 1), "rows": rows,
            "docs": docs, "pendingRows": pend, "conds": conds, "ready": sec >= DRILL_GOAL_SEC and all(c["ok"] for c in conds)}


# ---------- 話者の候補 ----------
def _member_name(folder):
    b = os.path.basename(folder.rstrip("\\/"))
    if b == ed_relink.EVAL_STAGING:
        return ""
    m = ed_relink._EVAL_MEMBER_RE.match(b)
    return m.group(1).strip() if m else ""


def _own_member(path, dirs):
    """動画の入ったフォルダから評価用のフォルダまでさかのぼって、最初の「…数字_名前」のフォルダの名前(評価用のフォルダの中だけ)"""
    if not path or not ed_relink.in_eval_dir(path, dirs):
        return ""
    roots = [os.path.normcase(os.path.abspath(d)) for d in dirs]
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
    dirs = ed_relink.eval_dirs() if dirs is None else dirs

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


# ---------- 行を選ぶ ----------
def _busy_tids():
    with ed_jobs._jobs_lock:
        return {str((j.get("spec") or {}).get("tid") or j.get("tid") or "") for j in ed_jobs._jobs.values() if j.get("state") in ed_jobs.ACTIVE_STATES}


def _media_ok(path):
    if not path or _fsio.is_network_path(path):   # ネットワーク上のパスには触らない(資格情報を送らない)
        return False
    try:
        ed_state.check_source(path)
        return True
    except ed_state.ApiError:
        return False


def _public_row(tid, g):
    return {"id": tid, "rowId": g["id"], "start": round(_num(g.get("start")), 2), "end": round(_num(g.get("end")), 2),
            "text": str(g.get("text") or ""), "speaker": str(g.get("speaker") or ""), "tags": [t for t in ed_state.TAGS if t in (g.get("tags") or [])],
            "flag": str(g.get("flag") or "")}


def drill_pick(n=DRILL_ROWS, seed=None):
    """GET /api/drill/pick -> {"rows": [行], "docs": {tid: {title, updatedAt, speakers, candidates}}, "pool", "recent", "status"}。
    評価用の文書だけ・文字あり・未校正・聞き取れない印なし・直近 10 分に更新した文書(と話者判別・再認識などの最中の文書)は除く・
    乱数で n 行・同じ文書から最大 2 行。動画の無い文書は聞けないので除く"""
    n = max(1, min(DRILL_ROWS_MAX, int(n or DRILL_ROWS)))
    now, busy, pool, recent, src = _now_ms(), _busy_tids(), [], 0, {}
    for tid, s in drill_docs():
        if not s.get("eval") or not s["cand"]:
            continue
        if now - max(s["updatedAt"], s["lastAt"]) < DRILL_RECENT_SEC * 1000:
            recent += 1
            continue
        if tid in busy:
            continue
        src[tid] = s["sourcePath"]
        pool += [(tid, rid) for rid in s["cand"]]
    rnd = random.Random(seed)
    rnd.shuffle(pool)
    chosen, per, media = [], {}, {}
    for tid, rid in pool:
        if per.get(tid, 0) >= DRILL_PER_DOC:
            continue
        if tid not in media:
            media[tid] = _media_ok(src[tid])
        if not media[tid]:
            continue
        per[tid] = per.get(tid, 0) + 1
        chosen.append((tid, rid))
        if len(chosen) >= n:
            break
    rows, docs, dirs, voices = [], {}, ed_relink.eval_dirs(), _learned_voices()
    for tid, rid in chosen:
        if tid not in docs:
            try:
                d = ed_store.read_transcript(tid)
            except ed_state.ApiError:
                docs[tid] = None
                continue
            docs[tid] = {"doc": d, "pub": {"title": str(d.get("title") or d.get("sourceName") or "")[:120], "sourceName": str(d.get("sourceName") or "")[:200],
                                           "updatedAt": d.get("updatedAt"),
                                           "speakers": [{"id": s.get("id"), "name": str(s.get("name") or ""), "color": str(s.get("color") or "")}
                                                        for s in d.get("speakers") or [] if isinstance(s, dict)],
                                           "candidates": drill_candidates_for(tid, d, dirs, voices)}}
        if not docs[tid]:
            continue
        g = next((x for x in docs[tid]["doc"].get("segments") or [] if isinstance(x, dict) and x.get("id") == rid), None)
        if g is not None and _pickable(g) and docs[tid]["doc"].get("evalSet") is True:   # 読み直すまでの間に変わった行は出さない
            rows.append(_public_row(tid, g))
    return {"rows": rows, "docs": {t: v["pub"] for t, v in docs.items() if v}, "pool": len(pool), "recent": recent, "status": drill_status()}


# ---------- 1 行の保存 ----------
_NAME_BAD = re.compile(r"[\x00-\x1f\x7f]")


def _speaker_for(speakers, obj):
    """要求の speaker(既にある話者の id。"" = なし)/ speakerName(名前。無ければ話者の一覧に足す)-> (話者の id, 足したか)。どちらも無ければ None"""
    if "speakerName" in obj and obj.get("speakerName") not in (None, ""):
        nm = str(obj.get("speakerName") or "").strip()
        if not nm or len(nm) > 30 or _NAME_BAD.search(nm):
            raise ed_state.ApiError("bad_request", "話者の名前は 1〜30 文字にしてください", 400)
        k = ed_speakers._spk_name_key(nm)
        for s in speakers:
            if ed_speakers._spk_name_key(s.get("name")) == k:
                return s["id"], False
        if len(speakers) >= 20:
            raise ed_state.ApiError("too_many", "話者が多すぎます(20 人まで)。編集の画面で話者をまとめてください", 400)
        used = {s.get("id") for s in speakers}
        i = 1
        while "S%d" % i in used:
            i += 1
        speakers.append({"id": "S%d" % i, "name": nm, "color": ed_speakers.SPK_COLORS[len(speakers) % len(ed_speakers.SPK_COLORS)]})
        return "S%d" % i, True
    if "speaker" in obj:
        sid = str(obj.get("speaker") or "")
        if sid and sid not in {s.get("id") for s in speakers}:
            raise ed_state.ApiError("bad_request", "その話者はこの文書にありません(読み込み直してください)", 400)
        return sid, False
    return None


def drill_row(obj):
    """POST /api/drill/row {id, rowId, baseUpdatedAt, text, speaker | speakerName, tags, proofed: true, activeSec?, newSession?}
    -> {"ok", "updatedAt", "row", "speakers", "added"}。保存のロックの中で読み、updatedAt が違えば 409(ドリルは「別の所で変わった」と飛ばす)。
    行だけ差し替えて、編集の画面の保存と同じ道(sanitize_transcript = proofedAt・effort_rows = 校正した行の数・apply_edit_cuts・履歴)を通す。
    updatedAt は必ず上げる(開いている編集の画面の次の保存を、既存の 409 の案内に乗せる。上げないと古い保存で消える)"""
    tid, rid = str(obj.get("id") or ""), str(obj.get("rowId") or "")
    if not isinstance(obj.get("text", ""), str):
        raise ed_state.ApiError("bad_request", "text は文字にしてください", 400)
    sec = _plain_int(obj.get("activeSec", 0))
    if sec is None or not 0 <= sec <= ed_store.MAX_EFFORT_SEC:
        raise ed_state.ApiError("bad_request", "activeSec は 0〜%d 秒の整数にしてください" % ed_store.MAX_EFFORT_SEC, 400)
    with ed_store._save_lock:
        base = ed_store.read_transcript(tid)
        if base.get("evalSet") is not True:
            raise ed_state.ApiError("not_eval", "評価用の文書ではありません(ドリルは評価用の文書だけを直します)", 400)
        if obj.get("baseUpdatedAt") != base.get("updatedAt"):
            raise ed_state.ApiError("conflict", "この文書は別の所(編集の画面・再認識など)で先に変わりました。この行は飛ばします", 409)
        segs = [dict(g) for g in base.get("segments") or [] if isinstance(g, dict)]
        g = next((x for x in segs if x.get("id") == rid), None)
        if g is None:
            raise ed_state.ApiError("not_found", "その行は見つかりません(消された可能性があります)", 404)
        speakers = [dict(s) for s in base.get("speakers") or [] if isinstance(s, dict)]
        spk = _speaker_for(speakers, obj)
        if "text" in obj:
            g["text"] = obj["text"].replace("\r", "").replace("\n", " ").strip()[:ed_state.MAX_TEXT]
        if spk is not None:
            g["speaker"] = spk[0]
            flags = (ed_state.MIXED_FLAG, ed_state.WEAK_FLAG, ed_state.NONE_FLAG)   # 人が聞いて話者を選んだので、判別の「話者が不確か」などの印は外す
            g["flag"] = "、".join(x for x in str(g.get("flag", "")).split("、") if x and x not in flags)[:100]
        if isinstance(obj.get("tags"), list):
            tg = [t for t in ed_state.TAGS if t in obj["tags"]]
            if tg:
                g["tags"] = tg
            else:
                g.pop("tags", None)
        g["proofed"] = obj.get("proofed", True) is True
        doc = ed_store.sanitize_transcript({"title": base.get("title", ""), "speakers": speakers, "segments": segs}, base)
        if (_plain_int(base.get("updatedAt")) or 0) >= doc["updatedAt"]:
            doc["updatedAt"] = (_plain_int(base.get("updatedAt")) or 0) + 1
        ed_store.effort_rows(base, doc)   # 校正済みにした行の数(校正の手間。Q2)
        if sec or obj.get("newSession") is True:   # 聞いて直した時間(画面が数えた秒)。updatedAt は上の保存の分だけ
            ef = ed_store._effort_of(doc)
            ef["activeSec"] += min(sec, DRILL_MAX_ROW_SEC)
            ef["sessions"] += 1 if obj.get("newSession") is True else 0
            ef["lastAt"] = _now_ms()
            doc["effort"] = ef
        ed_store.apply_edit_cuts(tid, doc)
        try:
            ed_store.hist_snapshot(tid)
        except OSError:
            pass    # 履歴が残せなくても保存は止めない
        ed_state.atomic_write(ed_store.tx_path(tid), json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
    row = next((x for x in doc["segments"] if x["id"] == rid), None)
    return {"ok": True, "updatedAt": doc["updatedAt"], "row": _public_row(tid, row) if row else None,
            "speakers": [{"id": s["id"], "name": s["name"], "color": s.get("color", "")} for s in doc["speakers"]], "added": bool(spk and spk[1])}


# ---------- 画面の CSS(ui-kit) ----------
_drill_css = {}


def drill_kit_css():
    """ui-kit の CSS(index.html の /* ui-kit:css:begin */ 〜 end の間 = dev/sync_ui_kit.py が正本から写したもの)。
    drill.html に 3 つ目の写しを作らない(写す先を増やさない)ため、index.html から切り出して配る"""
    try:
        st = os.stat(ed_state.INDEX)
    except OSError:
        return b""
    key = (st.st_mtime_ns, st.st_size)
    hit = _drill_css.get("kit")
    if hit and hit[0] == key:
        return hit[1]
    with open(ed_state.INDEX, "r", encoding="utf-8") as f:
        html = f.read()
    a, b = html.find("/* ui-kit:css:begin */"), html.find("/* ui-kit:css:end */")
    body = html[a:b + len("/* ui-kit:css:end */")].encode("utf-8") if 0 <= a < b else b""
    _drill_css["kit"] = (key, body)
    return body
