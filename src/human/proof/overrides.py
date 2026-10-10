# -*- coding: utf-8 -*-
"""③ 校正の上書きの第 1 版(O1。役割で組み直す RS6 b-O1・2026-10-10。決定 3-29 Q5・plan/role-restructure.md 5-5 の F-3)。

人が触った行(上書き)を文書から取り出し(extract)、同じ動画の文書を作り直したとき(force の再文字起こし・エンジンを変えた再実行など)に、
② から受け取った新しい機械の行へ時刻の重なりで重ねる(apply)。人が触っていない行だけ新しくなる。対応づかない人の文字の行は
印 STALE_FLAG(古い認識を元にした直し)を付けて行として残す。取り出した上書きは文書の横の <id>.over.json(派生の控え)にも置く(write・read)。

- 上書きは行の単位(行 id は作り直すと変わるので、時刻の重なりで対応づける)。対応づけの決まり match: 片方の行の中心が相手の区間に入る、か、
  重なりが短い方の長さの HALF 以上
- 人の行 = 校正済み(proofed)・文字が機械の出力 original の同じ時刻の行と違う・話者・noSub・tags のいずれかを持つ行。
  文字(text)を持つのは「人の文字の行」(校正済みか、文字が機械と違う)だけ。話者・noSub・tags だけの行は文字を上書きしない
  (話者の自動判別で全部の行に話者が付いても、機械の文字を古い文字で戻さない)
- 後処理が埋めた行(印 fill)は、校正済みでなければ文字を人の直しに数えない(learn.learn_events と同じ扱い)
- 再認識(each・range)は上書きを見ない(rerun.py の proofed の扱いと守る区間はそのまま)。② は上書きを見ない(③ の物)
"""
import difflib
import json
import os
import re

from ytt import fsio as _fsio, schemas as _yschemas, txbase as _txbase, workdata as _workdata  # noqa: E402

OVER_SCHEMA = "youtube-tools-over/v1"
OVER_SUFFIX = ".over.json"
STALE_FLAG = "古い認識を元にした直し(作り直した文字起こしに対応する行がありません)"   # 対応づかない人の文字の行に付ける要確認の印
HALF = 0.5          # 重なりが短い方の長さのこの割合以上なら対応づける(中心が入らなくても)
COVER_DROP = 0.5    # 新しい機械の行は、対応づいた人の文字の行が長さのこの割合以上を覆うか、
TEXT_DROP = 0.5     # 機械の文字のこの割合以上が人の行の文字に現れるときだけ人の行に置き換える(小さな人の行で長い機械の行のほかの言葉を消さない)
FLAG_MAX = 100      # 行の印の文字数の上限(store.sanitize_transcript と同じ)


def _span(g):
    a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
    if a is None or b is None or b < a:
        return None
    return a, b


def _overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def match(a, b):
    """2 つの区間 (開始, 終了) を対応づけるか: 片方の中心が相手の区間に入る、か、重なりが短い方の長さの HALF 以上"""
    ca, cb = (a[0] + a[1]) / 2.0, (b[0] + b[1]) / 2.0
    if b[0] <= ca < b[1] or a[0] <= cb < a[1]:
        return True
    short = min(a[1] - a[0], b[1] - b[0])
    return short > 0 and _overlap(a, b) >= HALF * short - 1e-9


def _norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def extract(doc):
    """文書の人の行 -> {"rows": [{start, end, text?, proofed?, proofedAt?, speaker?, noSub?, tags?}…], "speakers": [行が使う話者…]}。
    text は人の文字の行(校正済みか、文字が機械の出力 original の同じ時刻の行と違う)だけが持つ。original の無い古い文書は校正済みの行だけを文字の行に数える。
    空のままの下書き(印 draft・文字なし)の行は入れない"""
    orig = []
    for o in doc.get("original") or []:
        sp = _span(o) if isinstance(o, dict) else None
        if sp:
            orig.append((sp, _norm(o.get("text"))))
    orig.sort(key=lambda x: x[0])
    rows, used = [], set()
    for g in doc.get("segments") or []:
        if not isinstance(g, dict) or _yschemas.blank_draft_row(g):
            continue
        sp = _span(g)
        if sp is None:
            continue
        proofed = g.get("proofed") is True
        edited = False
        if orig and not proofed and not isinstance(g.get("fill"), dict):
            edited = _norm(g.get("text")) != "".join(t for osp, t in orig if match(sp, osp))
        speaker = str(g.get("speaker") or "")
        tags = [t for t in (g.get("tags") or []) if t in _yschemas.ROW_TAGS] if isinstance(g.get("tags"), list) else []
        nosub = g.get("noSub") is True
        if not (proofed or edited or speaker or tags or nosub):
            continue
        one = {"start": round(sp[0], 2), "end": round(sp[1], 2)}
        if proofed or edited:
            one["text"] = str(g.get("text") or "")
        if proofed:
            one["proofed"] = True
            if (_yschemas.plain_int(g.get("proofedAt")) or 0) > 0:
                one["proofedAt"] = g["proofedAt"]
        if speaker:
            one["speaker"] = speaker
            used.add(speaker)
        if nosub:
            one["noSub"] = True
        if tags:
            one["tags"] = tags
        rows.append(one)
    sps = [dict(s) for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id") in used]
    return {"rows": rows, "speakers": sps}


def _contained(a, b):
    """文字 a のうち、文字 b に同じ並びで現れる文字の割合(空白は数えない。a が空なら 1.0)"""
    a, b = _norm(a), _norm(b)
    if not a:
        return 1.0
    return sum(x.size for x in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()) / float(len(a))


def _replaced(m, mtext, hums):
    """機械の行(区間 m・文字 mtext)を、対応づいた人の文字の行 hums [(区間, 行)…] で置き換えるか:
    人の行が長さの COVER_DROP 以上を覆う、か、機械の文字の TEXT_DROP 以上が人の行の文字に現れる(人が時刻を詰めた行)。
    どちらでもなければ残す(長い機械の行の中の小さな人の行で、ほかの言葉を消さない)"""
    if not hums:
        return False
    length = m[1] - m[0]
    covered = sum(b - a for a, b in _yschemas.union_spans((max(sp[0], m[0]), min(sp[1], m[1])) for sp, _h in hums if _overlap(sp, m) > 0))
    if length <= 0 or covered >= COVER_DROP * length - 1e-9:
        return True
    return _contained(mtext, "".join(str(h.get("text") or "") for _sp, h in sorted(hums, key=lambda x: x[0]))) >= TEXT_DROP - 1e-9


def _join_flags(*flags):
    out = []
    for f in flags:
        for x in str(f or "").split("、"):
            if x and x not in out:
                out.append(x)
    return "、".join(out)[:FLAG_MAX]


def _fresh_id(used, n=0):
    while True:
        n += 1
        sid = "o%d" % n
        if sid not in used:
            used.add(sid)
            return sid, n


def apply(rows, over, span=None):
    """新しい機械の行 rows に上書き over(extract の形)を時刻の重なりで重ねる -> (行, stats)。rows は書き換えない(写しを返す)。
    - 人の文字の行: 対応づいた機械の行(時刻の決まり match か、重なっていて機械の文字の TEXT_DROP 以上が人の行に現れる)のうち、
      _replaced(長さの COVER_DROP 以上を覆う・文字の TEXT_DROP 以上が人の行に現れる)ものを人の行に置き換える(文字・校正済み・話者・noSub・tags は人の値。
      時刻も人の行。校正済みでなければ覆った機械の行の印を引き継ぐ)。どの機械の行とも対応づかない人の文字の行は印 STALE_FLAG を付けて残す
    - 話者・noSub・tags だけの行: 残った機械の行ごとに、いちばん重なる行の値を重ねる(文字は機械のまま)。対応づかなければ捨てる(dropped)
    - span = (開始, 終了 か None): 作り直した文書の範囲。中心が範囲の外の人の行は数えない(outside)
    行は時刻の順。人の行の id は o1, o2…(機械の行の id と重ならない)。
    stats = {"matched": 対応づいた人の行, "stale": 印を付けて残した人の文字の行, "dropped": 捨てた話者などだけの行, "total": 数えた人の行,
             "replaced": 人の行に置き換えた機械の行, "outside": 範囲の外で数えなかった人の行}"""
    machine = [dict(g) for g in rows or [] if isinstance(g, dict)]
    msp = [_span(g) for g in machine]
    hum, outside = [], 0
    for h in (over or {}).get("rows") or []:
        sp = _span(h) if isinstance(h, dict) else None
        if sp is None:
            continue
        if span is not None:
            c = (sp[0] + sp[1]) / 2.0
            if c < span[0] or (span[1] is not None and c > span[1]):
                outside += 1
                continue
        hum.append((sp, h))
    text_rows = [(sp, h) for sp, h in hum if "text" in h]
    attr_rows = [(sp, h) for sp, h in hum if "text" not in h]
    # 人の文字の行と機械の行の対応づけ(時刻の決まり match か、重なっていて機械の文字の TEXT_DROP 以上が人の行の文字に現れる = 人が時刻を大きく直した行)
    hits = [[j for j, m in enumerate(msp) if m and (match(sp, m) or (_overlap(sp, m) > 0 and _contained(machine[j].get("text"), h.get("text")) >= TEXT_DROP - 1e-9))]
            for sp, h in text_rows]
    drop = {j for j, m in enumerate(msp) if m and _replaced(m, machine[j].get("text"), [(sp, h) for (sp, h), hs in zip(text_rows, hits) if j in hs])}
    used = {str(g.get("id")) for g in machine}
    out, n = [], 0
    stats = {"matched": 0, "stale": 0, "dropped": 0, "total": len(hum), "replaced": len(drop), "outside": outside}
    for (sp, h), hs in zip(text_rows, hits):
        sid, n = _fresh_id(used, n)
        one = {"id": sid, "start": round(sp[0], 2), "end": round(sp[1], 2), "text": str(h.get("text") or ""), "speaker": str(h.get("speaker") or ""), "flag": ""}
        if h.get("proofed") is True:
            one["proofed"] = True
            if (_yschemas.plain_int(h.get("proofedAt")) or 0) > 0:
                one["proofedAt"] = h["proofedAt"]
        else:
            one["flag"] = _join_flags(*[machine[j].get("flag") for j in hs if j in drop])
        if h.get("noSub") is True:
            one["noSub"] = True
        if h.get("tags"):
            one["tags"] = list(h["tags"])
        if hs:
            stats["matched"] += 1
        else:
            one["flag"] = _join_flags(STALE_FLAG, one["flag"])
            stats["stale"] += 1
        out.append(one)
    attr_hit = set()
    for j, g in enumerate(machine):
        if j in drop:
            continue
        m = msp[j]
        if m:
            best = None
            for k, (sp, h) in enumerate(attr_rows):
                if match(sp, m):
                    score = (_overlap(sp, m), -abs((sp[0] + sp[1]) - (m[0] + m[1])))
                    if best is None or score > best[0]:
                        best = (score, k)
            if best is not None:
                h = attr_rows[best[1]][1]
                attr_hit.add(best[1])
                if h.get("speaker"):
                    g["speaker"] = str(h["speaker"])
                if h.get("noSub") is True:
                    g["noSub"] = True
                if h.get("tags"):
                    g["tags"] = list(h["tags"])
        out.append(g)
    stats["matched"] += len(attr_hit)
    stats["dropped"] = len(attr_rows) - len(attr_hit)
    out.sort(key=lambda g: (_yschemas.num_or(g.get("start"), 0.0) or 0.0, _yschemas.num_or(g.get("end"), 0.0) or 0.0))
    return out, stats


def merge_speakers(speakers, over, rows):
    """新しい文書の話者の一覧 speakers に、行 rows が使う上書きの話者を足す(同じ id があれば足さない)-> 一覧"""
    have = [dict(s) for s in speakers or [] if isinstance(s, dict)]
    ids = {s.get("id") for s in have}
    need = {g.get("speaker") for g in rows if isinstance(g, dict) and g.get("speaker")}
    for s in (over or {}).get("speakers") or []:
        if isinstance(s, dict) and s.get("id") in need and s.get("id") not in ids:
            have.append(dict(s))
            ids.add(s.get("id"))
    return have


# ---------- <id>.over.json(派生の控え) ----------
def over_path(tid):
    """上書きの控え transcripts/<id>.over.json(文書を消すときは一緒に消す)"""
    return os.path.join(_workdata.TX_DIR, tid + OVER_SUFFIX)


def clip_key_of(source_path):
    """切り抜きの横の書き出しの鍵(作業用/<名前>.export.key.json)の hash。無い・読めない・正しくなければ None"""
    p = str(source_path or "")
    if not p or p.replace("\\", "/").startswith("//"):   # ネットワーク上のパスは調べない(保存のたびに待たせない・資格情報を送らない)
        return None
    try:
        kp = _yschemas.key_path(p, "export")
        if not os.path.isfile(kp):
            return None
        with open(kp, "r", encoding="utf-8") as f:
            key, _warn = _yschemas.validate_key(json.load(f))
    except (OSError, ValueError):
        return None
    return key["hash"] if key else None


def write(tid, over, clip_key=None, at=None):
    """上書きを <id>.over.json に書く({schema, clipKey, rows, speakers, at})。at = 元にした文書の updatedAt(無ければ今)"""
    if not _yschemas.TID_RE.match(str(tid or "")):
        raise ValueError("文書の id が正しくありません")
    body = {"schema": OVER_SCHEMA, "clipKey": clip_key, "rows": list((over or {}).get("rows") or []),
            "speakers": list((over or {}).get("speakers") or []), "at": at or _yschemas.now_ms()}
    _fsio.atomic_write(over_path(tid), json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8"))
    return body


def read(tid):
    """<id>.over.json -> {schema, clipKey, rows, speakers, at} か None(無い・読めない・別の形)"""
    if not _yschemas.TID_RE.match(str(tid or "")):
        return None
    try:
        with open(over_path(tid), "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("schema") != OVER_SCHEMA or not isinstance(d.get("rows"), list):
        return None
    return d


def save_after(tid, doc):
    """文書を保存したあとの控え(store.save_transcript が保存のロックの中で呼ぶ)。書けなくても保存は成功のまま(False)"""
    try:
        write(tid, extract(doc), clip_key_of(doc.get("sourcePath")), at=doc.get("updatedAt"))
        return True
    except (OSError, ValueError, TypeError) as e:
        _txbase.log.warning("上書きの控えを書けませんでした: %s %s", tid, e)
        return False


def current(tid, doc):
    """文書 doc(id tid)の今の上書き: 控えが文書と同じ版(at が updatedAt 以上)ならそれ、無い・古ければ文書から取り出す。
    (再認識・話者の反映などは控えを書かないので、文書のほうが新しいことがある)"""
    over = read(tid)
    if over and (_yschemas.plain_int(over.get("at")) or 0) >= (_yschemas.plain_int(doc.get("updatedAt")) or 0):
        return over
    return extract(doc)
