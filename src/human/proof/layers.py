# -*- coding: utf-8 -*-
"""③ 文書を「機械の層 + 人の層」から組み立てる純粋な関数(O2-1。RS8・2026-10-11。決定 3-37 の (r8r)〜(r8u)・plan/rs8-cases-ui.md の決めたこと 3)。

ファイルも store も触らない(保存の経路から使うのは store.commit の影のモード = O2-2。機械の操作のあとの機械の層は advance_mach)。O1 の overrides(extract・apply)を一般にした物で、
対応づけの決まり(match・COVER_DROP・TEXT_DROP)は O1 と同じ値(O2-5 で O1 を消すのでここが持ち主)。

- 機械の層 mach = {schema, rev, keys{transcribe, post, diar}, rows[{id, start, end, text, flag, fill?, speaker?}], speakers}
  (① の後処理まで当てた行。rev は機械の行が変わるたびに上がる)
- 人の層 hum = {schema, rev, machRev, rows[人の行], dead[消す印], speakers[], spkMap{判別の鍵: {機械の話者: 人の話者}}, spkFresh?[],
  docFields{title・evalSet・evalReviewed・effort・diarNum・relinks・sourcePath}, order?[行 id], noSpeakers?(文書に話者の表の欄が無い)}
  - 人の行 = {id, start, end, text?, speaker?, flag? / flagOff?, fill? / fillOff?, tags?, proofed?, proofedAt?, cutState?, noSub?, draft?,
    covers[機械の行 id], base{rev, diar, rows[覆ったときの機械の行の写し]}}。
    text を持つ行(文字の行)は自分の時刻と文字で機械の行 covers を置き換える(直す・時刻を動かす・分ける・つなぐ・足す・校正済み)。
    text の無い行(属性の行)は機械の行 1 つに話者・印・音のメモなどを重ねる(文字と時刻は機械のまま)
  - 消す印 = {start, end, text, mid}(mid の機械の行が今も同じならそれだけ・変わっていれば中心が範囲に入る機械の行を消す。小さな印で長い行を消さない)
  - 話者 (r8r): 人の層の speakers[] が正。機械の話者 S… → 人の話者の対応表 spkMap を判別の鍵ごとに持つ。今の文書の話者の id はそのまま人の id にし
    (付け直さない)、判別し直して当たらない話者だけ新しい H…(assign_speakers)
- 案 A: 組み立てるとき、人の文字の行の base(覆ったときの機械)と今の機械の文字が違えば印 MACH_CHANGED。話者だけの変化は弱い印 SPK_CHANGED
  (人が話者を決めた行で機械の話者が前と変わったとき・自動で新しく作った話者の行。spkMap で自動に当たった行は印なし)
- 往復: compose(mach, diff(mach, doc), split_meta(doc)) == doc(compare_docs で比べる。測る道具は src/eval/tools/eval_layers.py)
"""
import bisect
import copy
import difflib
import re

from ytt import schemas as _ys

MACH_SCHEMA = _ys.MACH_SCHEMA   # 形の名前は ytt/schemas(② flow/tx も機械の層を書くため。RS8 O2-2)
HUM_SCHEMA = _ys.HUM_SCHEMA
MACH_CHANGED = "機械の結果が変わりました(前の機械・今の機械・あなたの直しを比べてください)"   # 案 A の印(O1 の STALE_FLAG を広げた物)
SPK_CHANGED = "話者の判別が変わりました"   # 弱い印(話者だけが変わった)
HALF = 0.5          # 重なりが短い方の長さのこの割合以上なら対応づける(overrides.HALF と同じ)
COVER_DROP = 0.5    # 機械の行は、人の文字の行が長さのこの割合以上を覆うか、
TEXT_DROP = 0.5     # 機械の文字のこの割合以上が人の行の文字に現れるときだけ人の行に置き換える(overrides と同じ)
FLAG_MAX = 100      # 行の印の文字数の上限(store.sanitize_transcript と同じ)
MAX_SPEAKERS = 20   # 組み込みの「ゲーム音声など」を除いた話者の上限(store.sanitize_transcript と同じ)
DOC_FIELDS = ("title", "evalSet", "evalReviewed", "effort", "diarNum", "relinks", "sourcePath")   # 人の層が持つ文書の欄
ROW_KEYS = ("id", "start", "end", "text", "speaker", "flag", "tags", "proofed", "proofedAt", "cutState", "noSub", "fill", "draft")   # 行の欄の並び(sanitize と同じ)
COPY_KEYS = ("tags", "proofed", "proofedAt", "cutState", "noSub", "draft")   # 人の行がそのまま持つ欄
BASE_KEYS = _ys.MACH_ROW_KEYS   # 機械の行の写しの欄("id", "start", "end", "text", "flag", "speaker", "fill")
H_PREFIX = "H"      # 人の層が新しく振る話者の id の頭
EPS = 1e-6          # 区間の候補を絞るときの小数の誤差(_near)
REASONS = {"rowCount": "行の数", "rowIds": "行の id", "order": "並び", "time": "時刻", "text": "文字", "speaker": "話者", "flag": "印",
           "rowFields": "そのほかの行の欄", "speakers": "話者の表", "docFields": "文書の欄"}


# ---------- 小道具 ----------
def _span(g):
    a, b = _ys.num_or(g.get("start")), _ys.num_or(g.get("end"))
    return (a, b) if a is not None and b is not None and b >= a else None


def _overlap(a, b):
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def _center(sp):
    return (sp[0] + sp[1]) / 2.0


def match(a, b):
    """2 つの区間を対応づけるか(O1 と同じ): 片方の中心が相手の区間に入る、か、重なりが短い方の長さの HALF 以上。
    O1 に足したこと: 同じ区間・長さ 0 の行(開始 = 終了)は、その点が相手の区間(両端を含む)に入れば対応づける"""
    if a == b:
        return True
    ca, cb = _center(a), _center(b)
    if b[0] <= ca < b[1] or a[0] <= cb < a[1]:
        return True
    if (a[0] == a[1] and b[0] <= ca <= b[1]) or (b[0] == b[1] and a[0] <= cb <= a[1]):
        return True
    short = min(a[1] - a[0], b[1] - b[0])
    return short > 0 and _overlap(a, b) >= HALF * short - 1e-9


def _norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def _contained(a, b):
    """文字 a のうち、文字 b に同じ並びで現れる文字の割合(空白は数えない。a が空なら 1.0)"""
    a, b = _norm(a), _norm(b)
    if not a:
        return 1.0
    blocks = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(x.size for x in blocks) / float(len(a))


def _hit(hsp, htext, msp, mtext):
    """人の文字の行(区間・文字)が機械の行に対応づくか: 時刻の決まり match か、重なっていて機械の文字の TEXT_DROP 以上が人の行に現れる"""
    return match(hsp, msp) or (_overlap(hsp, msp) > 0 and _contained(mtext, htext) >= TEXT_DROP - 1e-9)


def _near(a_spans, b_spans):
    """a の各区間 -> 端を含めて重なる b の区間の番号(小さい順)。match・_hit が真になる組はかならずここに入る(候補を絞るだけ。
    行の多い文書で全部の組を比べると保存のたびに数秒かかったため。RS8 O2-2)。None の区間は何とも重ならない"""
    order = sorted((k for k, s in enumerate(b_spans) if s is not None), key=lambda k: b_spans[k][0])
    starts = [b_spans[k][0] for k in order]
    longest = max([b_spans[k][1] - b_spans[k][0] for k in order] or [0.0])
    out = []
    for s in a_spans:
        if s is None:
            out.append([])
            continue
        lo, hi = bisect.bisect_left(starts, s[0] - longest - EPS), bisect.bisect_right(starts, s[1] + EPS)   # EPS = 小数の誤差で端の接する組を落とさない
        out.append(sorted(order[x] for x in range(lo, hi) if b_spans[order[x]][1] >= s[0] - EPS))
    return out


def _replaced(msp, mtext, hums):
    """機械の行を、対応づいた人の文字の行 hums [(区間, 文字)…] で置き換えるか(O1 と同じ): 長さの COVER_DROP 以上を覆う、
    か、機械の文字の TEXT_DROP 以上が人の行の文字に現れる。どちらでもなければ残す(長い機械の行の中の小さな人の行で、ほかの言葉を消さない)"""
    if not hums:
        return False
    length = msp[1] - msp[0]
    parts = [(max(sp[0], msp[0]), min(sp[1], msp[1])) for sp, _t in hums if _overlap(sp, msp) > 0]
    covered = sum(b - a for a, b in _ys.union_spans(parts))
    if length <= 0 or covered >= COVER_DROP * length - 1e-9:
        return True
    return _contained(mtext, "".join(t for _sp, t in sorted(hums, key=lambda x: x[0]))) >= TEXT_DROP - 1e-9


def join_flags(*flags):
    """印を「、」でつなぐ(同じ印は 1 つ・空は捨てる・FLAG_MAX 字まで)"""
    out = []
    for f in flags:
        for x in str(f or "").split("、"):
            if x and x not in out:
                out.append(x)
    return "、".join(out)[:FLAG_MAX]


def diar_key(mach):
    """機械の層の話者判別の鍵(spkMap の鍵)。keys.diar の hash か文字。無ければ ""(判別なし)"""
    k = ((mach or {}).get("keys") or {}).get("diar")
    if isinstance(k, dict):
        return str(k.get("hash") or "")
    return k if isinstance(k, str) else ""


def _mrows(mach):
    """機械の層の行(写し。時刻の読めない行は捨てる・id の無い行は m1, m2…)"""
    out = []
    for i, m in enumerate((mach or {}).get("rows") or []):
        if not isinstance(m, dict) or _span(m) is None:
            continue
        r = {k: copy.deepcopy(m[k]) for k in BASE_KEYS if k in m}
        r["id"] = str(m.get("id") or "m%d" % (i + 1))
        r["text"], r["flag"] = str(m.get("text") or ""), str(m.get("flag") or "")
        out.append(r)
    return out


def _base_row(m):
    return {k: copy.deepcopy(m[k]) for k in BASE_KEYS if k in m}


def _same_mach(a, b):
    """機械の行の写しと今の機械の行が同じか(時刻と文字)"""
    return a.get("start") == b.get("start") and a.get("end") == b.get("end") and str(a.get("text") or "") == str(b.get("text") or "")


def _joined(rows):
    return _norm("".join(str(r.get("text") or "") for r in rows))


def speaker_mapper(hum, key, hum_ids):
    """機械の話者 → 人の話者の関数(判別の鍵 key の spkMap。表に無い機械の話者は、同じ id の人の話者があればそれ、無ければ "")"""
    mp = ((hum or {}).get("spkMap") or {}).get(key) or {}

    def f(s):
        s = str(s or "")
        if not s:
            return ""
        if s in mp:
            return str(mp[s] or "")
        return s if s in hum_ids else ""
    return f


def _top_speaker(rows, sp, mapper):
    """区間 sp といちばん重なる機械の行の話者(人の話者に直して)。無ければ ""(重なりが同じなら先の行)"""
    best = None
    for m in rows:
        ov = _overlap(sp, _span(m))
        if best is None or ov > best[0]:
            best = (ov, m)
    return mapper(best[1].get("speaker")) if best else ""


def _ordered(row):
    return {k: row[k] for k in ROW_KEYS if k in row}


def _speakers_of(obj):
    return [copy.deepcopy(s) for s in (obj or {}).get("speakers") or [] if isinstance(s, dict)]


def machine_hum(mach):
    """人の層が無いとき(機械のまま)の人の層: 話者の表は機械の表・対応表は空(同じ id のまま)"""
    return {"schema": HUM_SCHEMA, "rev": 0, "machRev": (mach or {}).get("rev"), "rows": [], "dead": [], "speakers": _speakers_of(mach),
            "spkMap": {}, "docFields": {}}


# ---------- 組み立て ----------
def _resolve(h, M, by, fast):
    """人の行の covers が今の機械の行にそのまま当たるか -> (当たる, [機械の行の番号])。
    fast = 人の層を作ったあとで機械が変わっていない(rev が同じ)ときは id だけ・違えば base の写しと時刻・文字が同じか"""
    base = {str(b.get("id")): b for b in (h.get("base") or {}).get("rows") or [] if isinstance(b, dict)}
    js = []
    for cid in h.get("covers") or []:
        j = by.get(str(cid))
        if j is None:
            return False, []
        if not fast and (str(cid) not in base or not _same_mach(base[str(cid)], M[j])):
            return False, []
        js.append(j)
    if not js and not fast and (h.get("base") or {}).get("rows"):
        return False, []
    return True, js


def _centers(sp):
    """機械の行の中心の時刻の並び(小さい順) -> ([中心], [行の番号])(_dead_rows が範囲で引く)"""
    cs = sorted((_center(s), k) for k, s in enumerate(sp))
    return [c for c, _k in cs], [k for _c, k in cs]


def _dead_rows(hum, M, by, sp, cs=None):
    """消す印に当たる機械の行の番号: mid の行が今も同じならそれだけ、違えば中心が範囲に入る行。cs = _centers(sp)(何度も呼ぶ呼び手が先に作る)"""
    out = set()
    cs = cs or _centers(sp)
    for d in (hum or {}).get("dead") or []:
        if not isinstance(d, dict):
            continue
        j = by.get(str(d.get("mid")))
        if j is not None and _same_mach(d, M[j]):
            out.add(j)
            continue
        ds = _span(d)
        if ds is None:
            continue
        out.update(cs[1][bisect.bisect_left(cs[0], ds[0]):bisect.bisect_right(cs[0], ds[1])])
    return out


def _speaker_of(h, now_spk, base_spk, fresh):
    """行の話者と弱い印を出すか -> (話者, 印)。人が決めた話者(speaker を持つ)は人の値・機械の話者が前と変わって人の値とも違えば印。
    持たなければ機械の話者(人の話者に直した値)・自動で新しく作った話者なら印"""
    if "speaker" in h:
        spk = str(h.get("speaker") or "")
        return spk, now_spk != base_spk and now_spk != spk
    return now_spk, now_spk in fresh


def _row_flag(h, default):
    if "flag" in h:
        return str(h.get("flag") or "")
    return "" if h.get("flagOff") else default


def _human_row(h, start, end, text, flag, spk, fill):
    row = {"id": str(h.get("id")), "start": start, "end": end, "text": text, "speaker": spk, "flag": flag}
    for k in COPY_KEYS:
        if k in h:
            row[k] = copy.deepcopy(h[k])
    if fill is not None:
        row["fill"] = copy.deepcopy(fill)
    return _ordered(row)


def _text_row(h, cov, changed, ctx):
    """人の文字の行 -> 文書の行。cov = 今覆う機械の行・changed = 機械の文字が base と違う"""
    sp = _span(h)
    base = h.get("base") or {}
    brows = [b for b in base.get("rows") or [] if isinstance(b, dict) and _span(b)]
    now_spk = _top_speaker(cov, sp, ctx["mapper"])
    base_spk = _top_speaker(brows, sp, ctx["mapper_for"](str(base.get("diar") or "")))
    spk, weak = _speaker_of(h, now_spk, base_spk, ctx["fresh"])
    default = "" if h.get("proofed") is True else join_flags(*[m.get("flag") for m in cov])
    flag = _row_flag(h, default)
    if changed:
        flag = join_flags(flag, MACH_CHANGED)
        ctx["stats"]["machChanged"] += 1
    elif weak:
        flag = join_flags(flag, SPK_CHANGED)
        ctx["stats"]["spkChanged"] += 1
    return _human_row(h, h.get("start"), h.get("end"), str(h.get("text") or ""), flag, spk, h.get("fill"))


def _attr_row(h, m, ctx):
    """人の属性の行 + 機械の行 -> 文書の行(文字と時刻は機械・fillOff なら別の読みの前の文字)"""
    base = h.get("base") or {}
    brows = [b for b in base.get("rows") or [] if isinstance(b, dict)]
    now_spk = ctx["mapper"](m.get("speaker"))
    base_spk = ctx["mapper_for"](str(base.get("diar") or ""))(brows[0].get("speaker")) if brows else now_spk
    spk, weak = _speaker_of(h, now_spk, base_spk, ctx["fresh"])
    text, fill = m["text"], m.get("fill")
    if h.get("fillOff") and isinstance(fill, dict):
        text, fill = str(fill.get("from") or ""), None
    flag = _row_flag(h, m["flag"])
    if weak:
        flag = join_flags(flag, SPK_CHANGED)
        ctx["stats"]["spkChanged"] += 1
    return _human_row(h, m["start"], m["end"], text, flag, spk, fill)


def _sort_rows(items, order):
    """(行, 出した順) を時刻の順に。同じ時刻の行は人の層の order の順 → 出した順"""
    pos = {str(x): i for i, x in enumerate(order or [])}
    big = len(pos)
    items.sort(key=lambda x: (x[0]["start"], x[0]["end"], pos.get(x[0]["id"], big), x[1]))
    return [r for r, _n in items]


def compose_rows(mach, hum):
    """機械の層 + 人の層 -> (文書の行, stats)。stats = {kept: 機械のままの行, human: 人の文字の行, attr: 属性を重ねた行, dead: 消した機械の行,
    dropped: 当たる機械の行が無くて捨てた属性の行, machChanged: 印 MACH_CHANGED, spkChanged: 印 SPK_CHANGED}"""
    hum = hum if isinstance(hum, dict) else machine_hum(mach)
    M = _mrows(mach)
    by = {m["id"]: j for j, m in enumerate(M)}
    sp = [_span(m) for m in M]
    hum_ids = {str(s.get("id")) for s in hum.get("speakers") or [] if isinstance(s, dict)}
    rev = (mach or {}).get("rev")
    fast = rev is not None and rev == hum.get("machRev")
    stats = {"kept": 0, "human": 0, "attr": 0, "dead": 0, "dropped": 0, "machChanged": 0, "spkChanged": 0}
    ctx = {"mapper": speaker_mapper(hum, diar_key(mach), hum_ids), "mapper_for": lambda k: speaker_mapper(hum, k, hum_ids),
           "fresh": {str(x) for x in hum.get("spkFresh") or []}, "stats": stats}
    taken = {j: "dead" for j in _dead_rows(hum, M, by, sp)}
    stats["dead"] = len(taken)
    H = [h for h in hum.get("rows") or [] if isinstance(h, dict) and _span(h) and h.get("id") is not None]
    text_i = [i for i, h in enumerate(H) if "text" in h]
    attr_i = [i for i, h in enumerate(H) if "text" not in h]
    cover, changed, attr_at, loose_text, loose_attr = {}, {}, {}, [], []
    for i in text_i:   # 1 覆った機械の行が今もそのままの文字の行
        ok, js = _resolve(H[i], M, by, fast)
        if ok:
            cover[i] = js
            brows = (H[i].get("base") or {}).get("rows") or []
            changed[i] = _joined(brows) != _joined([M[j] for j in js])   # 前から続く印(機械が変わったのを人がまだ選んでいない)
            for j in js:
                taken.setdefault(j, "text")
        else:
            loose_text.append(i)
    for i in attr_i:   # 2 機械の行がそのままの属性の行
        ok, js = _resolve(H[i], M, by, fast)
        if ok and len(js) == 1 and js[0] not in taken:
            attr_at[i] = js[0]
            taken[js[0]] = "attr"
        else:
            loose_attr.append(i)
    free = [j for j in range(len(M)) if j not in taken]
    free_set = set(free)
    cands = [i for i in loose_text if _norm(H[i].get("text"))]   # 3 機械が変わった文字の行: 時刻の重なりで(O1 の apply と同じ決まり。空の行は覆わない)
    near = _near([_span(H[i]) for i in cands], sp)
    hits = {i: [j for j in near[n] if j in free_set and _hit(_span(H[i]), H[i].get("text"), sp[j], M[j]["text"])] for n, i in enumerate(cands)}
    by_m = {}
    for i in cands:
        for j in hits[i]:
            by_m.setdefault(j, []).append(i)
    drop = {j for j in free if _replaced(sp[j], M[j]["text"], [(_span(H[i]), str(H[i].get("text") or "")) for i in by_m.get(j, [])])}
    for i in loose_text:
        cover[i] = [j for j in hits.get(i, []) if j in drop]
        changed[i] = _joined((H[i].get("base") or {}).get("rows") or []) != _joined([M[j] for j in cover[i]])
    for j in drop:
        taken[j] = "text"
    near_attr = _near([_span(H[i]) for i in loose_attr], sp)
    for n, i in enumerate(loose_attr):   # 4 機械が変わった属性の行: 残りの機械の行でいちばん重なる行(当たらなければ捨てる)
        hs, best = _span(H[i]), None
        for j in near_attr[n]:
            if j in taken or not match(hs, sp[j]):
                continue
            score = (_overlap(hs, sp[j]), -abs(_center(hs) - _center(sp[j])))
            if best is None or score > best[0]:
                best = (score, j)
        if best is None:
            stats["dropped"] += 1
        else:
            attr_at[i] = best[1]
            taken[best[1]] = "attr"
    used = {str(h.get("id")) for h in H}
    items = []
    for j, m in enumerate(M):   # 5 出す: 機械のままの行・属性を重ねた行・人の文字の行
        if j in taken:
            continue
        rid = m["id"]
        while rid in used:   # 人の行と同じ id(機械が作り直された)は付け替える
            rid += "x"
        used.add(rid)
        spk = ctx["mapper"](m.get("speaker"))
        row = {"id": rid, "start": m["start"], "end": m["end"], "text": m["text"], "speaker": spk,
               "flag": join_flags(m["flag"], SPK_CHANGED) if spk in ctx["fresh"] else m["flag"]}
        if spk in ctx["fresh"]:
            stats["spkChanged"] += 1
        if isinstance(m.get("fill"), dict):
            row["fill"] = copy.deepcopy(m["fill"])
        items.append((_ordered(row), len(items)))
        stats["kept"] += 1
    for i in sorted(attr_at):
        items.append((_attr_row(H[i], M[attr_at[i]], ctx), len(items)))
        stats["attr"] += 1
    for i in text_i:
        items.append((_text_row(H[i], [M[j] for j in cover[i]], changed[i], ctx), len(items)))
        stats["human"] += 1
    return _sort_rows(items, hum.get("order")), stats


def compose(mach, hum, meta=None):
    """機械の層 + 人の層 -> 今の文書の形(meta = 文書の機械の側の欄 schema・id・original・recognition など。split_meta)。
    人の層が無ければ機械のまま(meta の文書の欄はそのまま)。人の層があれば文書の欄 DOC_FIELDS は人の層の docFields だけ"""
    doc = copy.deepcopy(meta) if isinstance(meta, dict) else {}
    rows, _stats = compose_rows(mach, hum)
    if isinstance(hum, dict):
        fields = hum.get("docFields") or {}
        for k in DOC_FIELDS:
            if k in fields:
                doc[k] = copy.deepcopy(fields[k])
            else:
                doc.pop(k, None)
        if not hum.get("noSpeakers"):   # 話者の表の欄の無い文書(古いテストの文書など)は欄を作らない
            doc["speakers"] = _speakers_of(hum)
    else:
        doc["speakers"] = _speakers_of(mach)
    doc["segments"] = rows
    return doc


def split_meta(doc):
    """文書 -> 機械の側の欄(人の層の文書の欄・話者の表・行を除いた写し。compose の meta)"""
    return {k: copy.deepcopy(v) for k, v in (doc or {}).items() if k not in DOC_FIELDS and k not in ("speakers", "segments")}


# ---------- 差分 ----------
def _compat(g, m):
    """文書の行が機械の行そのまま(属性の行にできる)か: 校正済みでも下書きでもなく、時刻が同じで、
    文字と別の読みが機械と同じ・か、別の読みを戻した(機械の fill があって文書に無く、文字が fill.from)"""
    if g.get("proofed") is True or g.get("draft") or g.get("start") != m["start"] or g.get("end") != m["end"]:
        return False
    text = str(g.get("text") or "")
    if text == m["text"] and g.get("fill") == m.get("fill"):
        return True
    return isinstance(m.get("fill"), dict) and g.get("fill") is None and text == str(m["fill"].get("from") or "")


def _flag_over(out, flag, default):
    if flag != default:
        if flag:
            out["flag"] = flag
        else:
            out["flagOff"] = True


def _attr_over(g, m, mapper):
    """機械の行に重ねる人の値(機械と違う物だけ)"""
    o = {}
    if str(g.get("text") or "") != m["text"]:
        o["fillOff"] = True
    if str(g.get("speaker") or "") != mapper(m.get("speaker")):
        o["speaker"] = str(g.get("speaker") or "")
    _flag_over(o, str(g.get("flag") or ""), m["flag"])
    for k in COPY_KEYS:
        if k in g:
            o[k] = copy.deepcopy(g[k])
    return o


def _link(segs, M, by):
    """文書の行 → 機械の行の番号(機械の行そのままの文書の行だけ。同じ id を先に・次に同じ時刻の行)"""
    link, used = {}, set()
    for gi, g in enumerate(segs):
        j = by.get(str(g.get("id")))
        if j is not None and j not in used and _compat(g, M[j]):
            link[gi] = j
            used.add(j)
    at = {}
    for j, m in enumerate(M):
        at.setdefault((m["start"], m["end"]), []).append(j)
    for gi, g in enumerate(segs):
        if gi in link:
            continue
        for j in at.get((g.get("start"), g.get("end")), []):
            if j not in used and _compat(g, M[j]):
                link[gi] = j
                used.add(j)
                break
    return link


def _keep_base(g, prev_rows):
    """人がまだ選んでいない印(MACH_CHANGED・SPK_CHANGED)の行は、前の人の層の base(前の機械)を引き継ぐ"""
    flag = str(g.get("flag") or "")
    p = prev_rows.get(str(g.get("id")))
    if p and isinstance(p.get("base"), dict) and (MACH_CHANGED in flag or SPK_CHANGED in flag):
        return copy.deepcopy(p["base"])
    return None


def _prev_dead(prev, M, by, sp, keep_js, have):
    """前の人の層の消す印のうち、今の文書に残っている行を消さない物(機械の行が無い時間帯の印も残す = 作り直しても出さない)"""
    out = []
    cs = _centers(sp)
    for d in (prev or {}).get("dead") or []:
        if not isinstance(d, dict) or str(d.get("mid")) in have or _span(d) is None:
            continue
        if _dead_rows({"dead": [d]}, M, by, sp, cs) & keep_js:
            continue
        out.append(copy.deepcopy(d))
    return out


def _new_hum(mach, doc, prev):
    speakers = _speakers_of(doc)
    hum_ids = {str(s.get("id")) for s in speakers}
    spk_map = copy.deepcopy(prev.get("spkMap") or {})
    key = diar_key(mach)
    if key not in spk_map:
        ident = {}
        for m in _mrows(mach):
            s = str(m.get("speaker") or "")
            if s and s in hum_ids:
                ident[s] = s
        if ident:
            spk_map[key] = ident
    hum = {"schema": HUM_SCHEMA, "rev": (_ys.plain_int(prev.get("rev")) or 0) + 1, "machRev": (mach or {}).get("rev"), "rows": [], "dead": [],
           "speakers": speakers, "spkMap": spk_map, "docFields": {k: copy.deepcopy(doc[k]) for k in DOC_FIELDS if k in doc}}
    fresh = [x for x in prev.get("spkFresh") or [] if x in hum_ids]
    if fresh:
        hum["spkFresh"] = fresh
    if "speakers" not in (doc or {}):
        hum["noSpeakers"] = True
    return hum


def diff(mach, doc, prev_hum=None):
    """文書と機械の層の差 -> 人の層(O1 の extract を一般にした物)。prev_hum = 前の人の層(消す印・話者の対応表・まだ選んでいない印の base を引き継ぐ)。
    - 機械の行そのままの行(同じ id・時刻・文字・印・話者)は人の層に入れない
    - 時刻と文字が機械の行と同じで、話者・印・音のメモ・id などだけ違う行 = 属性の行(text なし。covers は 1 つ)
    - それ以外の行 = 文字の行(直した・時刻を動かした・分けた・つないだ・足した・校正済み)。covers = 時刻の決まりで対応づき、
      置き換えの決まり(COVER_DROP・TEXT_DROP)にも当たる、文書に無い機械の行(組み立てで機械が変わったときと同じ決まり)
    - 文書に無く、covers にならない機械の行 = 消す印 {start, end, text, mid}
    - 印: 機械(文字の行は覆った機械の行の印をつないだ物・校正済みなら空)と違えば flag、空にしたなら flagOff
    - 同じ時刻の行の並びが組み立てと違えば order"""
    prev = prev_hum if isinstance(prev_hum, dict) else {}
    M = _mrows(mach)
    by = {m["id"]: j for j, m in enumerate(M)}
    sp = [_span(m) for m in M]
    hum = _new_hum(mach, doc, prev)
    mapper = speaker_mapper(hum, diar_key(mach), {str(s.get("id")) for s in hum["speakers"]})
    rev, key = (mach or {}).get("rev"), diar_key(mach)
    prev_rows = {str(h.get("id")): h for h in prev.get("rows") or [] if isinstance(h, dict)}
    segs = [g for g in (doc or {}).get("segments") or [] if isinstance(g, dict) and _span(g)]
    link = _link(segs, M, by)
    out = {}
    for gi, j in link.items():   # 属性の行
        m, g = M[j], segs[gi]
        o = _attr_over(g, m, mapper)
        if str(g.get("id")) == m["id"] and not o:
            continue
        out[gi] = dict({"id": str(g.get("id")), "start": g["start"], "end": g["end"]}, **o,
                       covers=[m["id"]], base=_keep_base(g, prev_rows) or {"rev": rev, "diar": key, "rows": [_base_row(m)]})
    loose = [gi for gi in range(len(segs)) if gi not in link]
    covers = {gi: [] for gi in loose}
    linked = set(link.values())
    near = _near(sp, [_span(segs[gi]) for gi in loose])   # 機械の行 -> 時刻の重なる文字の行(loose の中の番号)
    for j, m in enumerate(M):   # 文書に無い機械の行: 対応づく文字の行が覆う・無ければ消す印
        if j in linked:
            continue
        hit = [loose[x] for x in near[j] if _norm(segs[loose[x]].get("text")) and _hit(_span(segs[loose[x]]), segs[loose[x]].get("text"), sp[j], m["text"])]
        if hit and _replaced(sp[j], m["text"], [(_span(segs[gi]), str(segs[gi].get("text") or "")) for gi in hit]):
            for gi in hit:
                covers[gi].append(j)
        else:   # 対応づいても置き換えの決まりに当たらない行も消す印に(機械が作り直されても組み立てで同じ行を出さない)
            hum["dead"].append({"start": m["start"], "end": m["end"], "text": m["text"], "mid": m["id"]})
    for gi in loose:   # 文字の行
        g, cov = segs[gi], [M[j] for j in covers[gi]]
        r = {"id": str(g.get("id")), "start": g["start"], "end": g["end"], "text": str(g.get("text") or "")}
        kept = _keep_base(g, prev_rows)
        default_spk = _top_speaker(cov, _span(g), mapper)
        if str(g.get("speaker") or "") != default_spk or kept:
            r["speaker"] = str(g.get("speaker") or "")
        default_flag = "" if g.get("proofed") is True else join_flags(*[m.get("flag") for m in cov])
        if kept:   # 前の機械を引き継ぐ行は印を決まった値で持つ(組み立てで印を付け直しても同じ文字になるように)
            r["flag"] = str(g.get("flag") or "")
        else:
            _flag_over(r, str(g.get("flag") or ""), default_flag)
        for k in COPY_KEYS:
            if k in g:
                r[k] = copy.deepcopy(g[k])
        if isinstance(g.get("fill"), dict):
            r["fill"] = copy.deepcopy(g["fill"])
        r["covers"] = [m["id"] for m in cov]
        r["base"] = kept or {"rev": rev, "diar": key, "rows": [_base_row(m) for m in cov]}
        out[gi] = r
    hum["rows"] = [out[gi] for gi in sorted(out)]
    hum["dead"].extend(_prev_dead(prev, M, by, sp, linked, {d["mid"] for d in hum["dead"]}))
    rows, _st = compose_rows(mach, hum)
    want = [str(g.get("id")) for g in segs]
    if [r["id"] for r in rows] != want:   # 同じ時刻の行の並び
        spans = {}
        for g in segs:
            spans.setdefault((g["start"], g["end"]), []).append(str(g.get("id")))
        tied = [str(g.get("id")) for g in segs if len(spans[(g["start"], g["end"])]) > 1]
        if tied:
            hum["order"] = tied
    return hum


# ---------- 話者の対応表 (r8r) ----------
def _new_hid(ids):
    n = 1
    while "%s%d" % (H_PREFIX, n) in ids:
        n += 1
    return "%s%d" % (H_PREFIX, n)


def assign_speakers(mach, hum, rows):
    """判別し直した機械の層 mach の話者 S… を人の話者に当てる -> 新しい人の層(写し。hum は書き換えない)。
    rows = 今の文書の行(人の話者が付いた行)。機械の話者ごとに、その話者の機械の行と人の話者の行の重なり時間を足し、いちばん長い人の話者に当てる
    (同じなら表の先の話者。組み込みの「ゲーム音声など」には当てない)。重ならない機械の話者は新しい H… を表に足し、spkFresh に入れる
    (その話者の行に弱い印 SPK_CHANGED)。同じ判別の鍵が spkMap に既にあれば何もしない"""
    out = copy.deepcopy(hum) if isinstance(hum, dict) else machine_hum(mach)
    key = diar_key(mach)
    spk_map = out.setdefault("spkMap", {})
    if key in spk_map:
        return out
    speakers = out.setdefault("speakers", [])
    order = [str(s.get("id")) for s in speakers if isinstance(s, dict)]
    ids = set(order)
    targets = [g for g in rows or [] if isinstance(g, dict) and _span(g) and str(g.get("speaker") or "") in ids
               and str(g.get("speaker")) != _ys.OTHER_SPK_ID]
    mspk = {str(s.get("id")): s for s in (mach or {}).get("speakers") or [] if isinstance(s, dict)}
    tally, seen = {}, []
    for m in _mrows(mach):
        s = str(m.get("speaker") or "")
        if not s:
            continue
        if s not in tally:
            tally[s] = {}
            seen.append(s)
        for g in targets:
            ov = _overlap(_span(m), _span(g))
            if ov > 0:
                tally[s][str(g["speaker"])] = tally[s].get(str(g["speaker"]), 0.0) + ov
    mp, fresh = {}, list(out.get("spkFresh") or [])
    for s in seen:
        if tally[s]:
            mp[s] = max(tally[s], key=lambda h: (tally[s][h], -order.index(h)))
            continue
        if sum(1 for x in ids if x != _ys.OTHER_SPK_ID) >= MAX_SPEAKERS:
            mp[s] = ""   # 表がいっぱい: 話者なし
            continue
        hid = _new_hid(ids)
        ids.add(hid)
        src = mspk.get(s) or {}
        speakers.append({"id": hid, "name": str(src.get("name") or hid)[:30], "color": str(src.get("color") or "")})
        fresh.append(hid)
        mp[s] = hid
    spk_map[key] = mp
    if fresh:
        out["spkFresh"] = fresh
    return out


# ---------- 移行と往復の検査 ----------
def mach_from_doc(doc, rev=1):
    """今の文書から機械の層を作る(移行と往復の検査用): 機械の出力 original の各行(id は作ったときの行と同じ s1, s2…)+
    同じ id・同じ時刻の今の行の印と別の読み。話者は持たない(今の文書の話者は人の層に入る)"""
    segs = {str(g.get("id")): g for g in (doc or {}).get("segments") or [] if isinstance(g, dict)}
    rows = []
    for i, o in enumerate((doc or {}).get("original") or []):
        if not isinstance(o, dict) or _span(o) is None:
            continue
        r = {"id": "s%d" % (i + 1), "start": o["start"], "end": o["end"], "text": str(o.get("text") or ""), "flag": ""}
        g = segs.get(r["id"])
        if g and g.get("start") == r["start"] and g.get("end") == r["end"]:
            r["flag"] = str(g.get("flag") or "")
            if isinstance(g.get("fill"), dict):
                r["fill"] = copy.deepcopy(g["fill"])
        rows.append(r)
    return {"schema": MACH_SCHEMA, "rev": rev, "keys": {}, "rows": rows, "speakers": []}


def _row_key(g):
    return (g.get("start"), g.get("end"), str(g.get("text") or ""))


def _speaker_rows(rows, segs):
    """機械の行の話者を文書の行の話者に(同じ id で同じ時刻の行・無ければ同じ時刻の行。文字は見ない = 人が直した行も話者は判別の結果)"""
    by_id = {str(g.get("id")): g for g in segs}
    at = {}
    for g in segs:
        at.setdefault(_span(g), g)
    for m in rows:
        g = by_id.get(m["id"])
        if g is None or _span(g) != _span(m):
            g = at.get(_span(m))
        if g is None:
            continue
        spk = str(g.get("speaker") or "")
        if spk:
            m["speaker"] = spk
        else:
            m.pop("speaker", None)


def advance_mach(mach, old_doc, new_doc, speakers=False):
    """機械の操作(再認識・疑わしい所・分け直し・話者の判別など)のあとの機械の層 -> (新しい機械の層, 変わったか)(RS8 O2-2 の影のモード)。
    old_doc = 操作の前の文書・new_doc = 操作のあとの文書。mach は書き換えない。操作が書いた行だけを機械の層で入れ替える:
    - 機械が書いた行 = 新しい文書の行のうち、前の文書に同じ id が無いか、同じ id の行と時刻か文字が違う行(印・話者・校正済みなどだけの違いは人の層へ)
    - 書き換えた範囲(機械が書いた行と、消えた・書き換えられた前の行の区間)に match で当たる機械の行は捨てる。
      ただし、そのまま残った文書の行と同じ id か同じ区間の機械の行は残す(隣の行の小さな重なりで消さない)
    - 機械が書いた行は文書の行の写し(id も同じ。残した機械の行と同じ id なら末尾に x)
    - speakers=True(話者の判別): 機械の行の話者を文書の行の話者に(_speaker_rows)・話者の表を文書の表に
    rev は中身(行・話者の表)が変わったときだけ 1 上げる"""
    base = _mrows(mach)
    old_by = {}
    for g in (old_doc or {}).get("segments") or []:
        if isinstance(g, dict) and _span(g):
            old_by.setdefault(str(g.get("id")), g)
    segs = [g for g in (new_doc or {}).get("segments") or [] if isinstance(g, dict) and _span(g)]
    wrote, same_ids, same_spans = [], set(), set()
    for g in segs:
        o = old_by.get(str(g.get("id")))
        if o is not None and _row_key(o) == _row_key(g):
            same_ids.add(str(g.get("id")))
            same_spans.add(_span(g))
        else:
            wrote.append(g)
    wrote_ids = {str(g.get("id")) for g in wrote}
    new_ids = {str(g.get("id")) for g in segs}
    hit = [_span(g) for g in wrote] + [_span(o) for i, o in old_by.items() if i not in new_ids or i in wrote_ids]
    near = _near([_span(m) for m in base], hit)
    rows = [m for k, m in enumerate(base) if m["id"] in same_ids or _span(m) in same_spans or not any(match(_span(m), hit[x]) for x in near[k])]
    used = {m["id"] for m in rows}
    for g in wrote:
        r = _ys.mach_row(g)
        while r["id"] in used:
            r["id"] += "x"
        used.add(r["id"])
        rows.append(r)
    if wrote or len(rows) != len(base):
        rows.sort(key=lambda m: (m["start"], m["end"]))
    table = _speakers_of(mach)
    if speakers:
        _speaker_rows(rows, segs)
        table = _speakers_of(new_doc)
    changed = rows != _mrows(mach) or table != _speakers_of(mach)   # base は _speaker_rows が書き換えた行と同じ物なので、作り直して比べる
    out = {"schema": MACH_SCHEMA, "rev": (_ys.plain_int((mach or {}).get("rev")) or 0) + (1 if changed else 0),
           "keys": copy.deepcopy((mach or {}).get("keys") or {}), "rows": rows, "speakers": table}
    return out, changed


def _row_diff(a, b, loose=False):
    """同じ id の 2 つの行の違う所 -> 理由の名前の一覧。loose = 話者・印の欄が無いのと空の文字を同じに数える
    (読み手はどれも g.get(…) or "" で読む。組み立ては欄をいつも書く。影のモードの比べ方 = store.commit。O2-2)"""
    out = []
    if (a.get("start"), a.get("end")) != (b.get("start"), b.get("end")):
        out.append("time")
    for k in ("text", "speaker", "flag"):
        if loose and k != "text":
            if (a.get(k) or "") != (b.get(k) or ""):
                out.append(k)
        elif a.get(k) != b.get(k) or (k in a) != (k in b):
            out.append(k)
    rest = set(a) | set(b)
    if any(a.get(k) != b.get(k) or (k in a) != (k in b) for k in rest - {"id", "start", "end", "text", "speaker", "flag"}):
        out.append("rowFields")
    return out


def compare_docs(want, got, loose=False):
    """2 つの文書の違い -> [(理由の名前, 最初の例)…](同じなら空。理由の名前は REASONS)。loose = 行の話者・印の欄が無いのと空を同じに(_row_diff)"""
    found = {}

    def add(code, detail):
        found.setdefault(code, detail)
    keys = (set(want) | set(got)) - {"segments", "speakers"}
    for k in sorted(keys):
        if want.get(k) != got.get(k) or (k in want) != (k in got):
            add("docFields", k)
    if want.get("speakers") != got.get("speakers"):
        add("speakers", "")
    wa, ga = [g for g in want.get("segments") or []], [g for g in got.get("segments") or []]
    if len(wa) != len(ga):
        add("rowCount", "%d → %d" % (len(wa), len(ga)))
    wid = [str(g.get("id")) if isinstance(g, dict) else None for g in wa]
    gid = [str(g.get("id")) for g in ga]
    if sorted(x for x in wid if x) != sorted(gid):
        add("rowIds", ",".join(sorted(set(x for x in wid if x) ^ set(gid)))[:120])
    elif wid != gid:
        add("order", next((x for x, y in zip(wid, gid) if x != y), ""))
    gby = {r["id"]: r for r in ga}
    for g in wa:
        if isinstance(g, dict) and str(g.get("id")) in gby:
            for code in _row_diff(g, gby[str(g.get("id"))], loose):
                add(code, str(g.get("id")))
    return [(k, found[k]) for k in REASONS if k in found]


def roundtrip(mach, doc, prev_hum=None, loose=False):
    """往復の検査: compose(mach, diff(mach, doc), split_meta(doc)) と doc の違い -> (人の層, [(理由, 例)…])。loose は compare_docs と同じ"""
    hum = diff(mach, doc, prev_hum)
    return hum, compare_docs(doc, compose(mach, hum, split_meta(doc)), loose)
