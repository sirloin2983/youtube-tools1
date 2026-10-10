# -*- coding: utf-8 -*-
"""② 人の操作の層 human/proof: 人が直した内容からの学習(機械の出力と人の行の対応づけ・「誤=>正」の統計・確度)と、行への修正の提案・
提案の採用と却下の記録・確度「高」の自動置換・用語の自動追加・同梱の名簿(画面の「名簿から追加」)。

役割で組み直す RS3-E5c(2026-10-10)に編集の ed_learn(段10 で editor/serve.py から分けた部品)から移した(中身は同じ)。
置換辞書の読み方と当て方は pipeline/transcribe/replace.py、認識精度の測定(CER)と評価用の基準の記録は eval/drill/metrics.py(metrics → learn の一方向 =
ここは metrics を読まない。機械と人の行の対応づけ _groups・_prep・split_nosub・_norm は metrics もここから読む)。
設定(settings.json)の読み書きは ytt/settings(RS3-1)。ed_state は読まない(文書の形の小道具は ytt/schemas・エラーは ytt/errors・書き込みは ytt/fsio)。
旧い名前 ed_learn.名前・S.名前 は editor/ed_learn.py(転送だけの殻。RS5 で消す)と serve の受付がここへ回す(テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前`・`replace.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
2つ目のエンジンの候補 alt・YouTube の字幕の候補 ytcap は隣(RS3-E6 に editor の ed_alt・ed_ytcap から)。文書の置き場は隣の store(RS3-E5a)。
"""
import difflib
import json
import os
import re
import threading

from ytt import errors as _errors, fsio as _fsio, schemas as _yschemas, settings as _settings, workdata as _workdata  # noqa: E402
from pipeline.transcribe import replace  # noqa: E402   置換辞書の読み方と当て方(RS3-E5c。呼ぶたびに replace.名前 で読む)
from pipeline.transcribe import roster as _roster  # noqa: E402   (名簿のファイルの場所 ROSTER の持ち主。RS3-0A に ed_state から)
from pipeline.transcribe import txbase as _txbase  # noqa: E402   文字の種類 char_class(RS2-4b に _cc を移した)
from . import alt, ytcap  # noqa: E402   2つ目のエンジンの候補(suggest_for_doc の alt。D1-b)・YouTube の字幕の候補(suggest_for_doc の yt。案 A1)(RS3-E6 に editor/ed_alt・ed_ytcap から隣へ。呼ぶたびに alt.名前・ytcap.名前 で読む)
from . import store  # noqa: E402   文書の一覧と読み(_tids・tx_path・read_transcript。RS3-E5a に editor/ed_store から隣へ。呼ぶたびに store.名前 で読む)


PUNCT_ONLY = re.compile(r"^[\s、。,.!?！？…・「」『』()（）ー〜~-]*$")


def _groups(orig, segs):
    """機械の出力(orig)と修正後(segs)を、時刻が重なるまとまりごとに対応づける(分割・結合・時刻の微調整があっても比べられる)。"""
    items = sorted([(o["start"], o["end"], 0, i) for i, o in enumerate(orig)] + [(g["start"], g["end"], 1, i) for i, g in enumerate(segs)])
    groups, cur, cur_end = [], None, -1.0
    for a, b, k, i in items:
        if cur is not None and a < cur_end - 0.05:
            cur[k].append(i)
            cur_end = max(cur_end, b)
        else:
            if cur is not None:
                groups.append(cur)
            cur = ([], [])
            cur[k].append(i)
            cur_end = b
    if cur is not None:
        groups.append(cur)
    return groups


def _prep(doc):
    orig = sorted([o for o in (doc.get("original") or []) if isinstance(o, dict) and _yschemas.num_or(o.get("start")) is not None and _yschemas.num_or(o.get("end")) is not None],
                  key=lambda o: o["start"])
    # 空のままの下書き(印 draft・文字なし。重なりの所に置いた空の行)は数えない: 残っている間、重なる校正済みのまとまりを丸ごと数から外してしまうため
    segs = sorted([g for g in (doc.get("segments") or []) if isinstance(g, dict) and not _yschemas.blank_draft_row(g)], key=lambda g: g["start"])
    return orig, segs


# ---------- 「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり) ----------
# 行の印 noSub: true = 字幕に出さない(ゲームのキャラ・NPC の声など)。行は消えず、機械の出力 original も変わらない。
# 学習・辞書・提案・保管の材料にはしない。精度の数え方では、人の行のうち noSub の行を正解に入れず、その時間に機械が書いた文字も本体から外して別に数える
# (確かめ済みの文書で「何も話していない所の機械の文字 = 余分」に数えられないように)。計画: plan/line-b-overlap.md の 2-1・6-2 の 5
NOSUB_IN = 0.5        # 機械の行のうち、noSub の行の時間に入る長さの割合がこれ以上なら、noSub の時間の文字として本体から外す


def is_nosub(g):
    return isinstance(g, dict) and g.get("noSub") is True


def split_nosub(orig, segs):
    """(機械の行, 人の行) -> (本体の機械の行, 本体の人の行, noSub の時間の機械の行, noSub の人の行)。
    noSub の人の行は本体から外す。機械の行は、半分以上(NOSUB_IN)が noSub の行の時間に入るものを外す。noSub の行が無ければ、渡した 2 つのリストをそのまま返す"""
    ns = [g for g in segs if is_nosub(g)]
    if not ns:
        return orig, segs, [], []
    span = _yschemas.union_spans((g["start"], g["end"]) for g in ns if _yschemas.num_or(g.get("start")) is not None and _yschemas.num_or(g.get("end")) is not None)   # noSub の行の時間をつなげた区間
    m_main, m_ns = [], []
    for o in orig:
        dur = o["end"] - o["start"]
        inside = sum(max(0.0, min(o["end"], b) - max(o["start"], a)) for a, b in span)
        if dur > 0 and inside / dur >= NOSUB_IN - 1e-9 or dur <= 0 and any(a <= o["start"] <= b for a, b in span):
            m_ns.append(o)
        else:
            m_main.append(o)
    return m_main, [g for g in segs if not is_nosub(g)], m_ns, ns


def _prep_main(doc):
    """_prep から noSub の行(とその時間の機械の行)を外したもの。学習・提案・保管・精度の測定の本体が読む"""
    orig, segs = _prep(doc)
    o, s, _no, _ns = split_nosub(orig, segs)
    return o, s


def _norm(items, idx):
    return re.sub(r"\s+", "", "".join(str(items[i].get("text", "")) for i in idx))


def learn_events(doc):
    """1件の文字起こしから、「機械の出力 → 人が直した文章」を (誤, 正, 前後1文字を足したか, 誤の直前2文字, 誤の直後2文字) で取り出す。
    noSub(字幕に出さない)の行とその時間の機械の行は材料にしない。"""
    orig, segs = _prep_main(doc)
    if not orig or not segs:
        return []
    out = []
    for go, ge in _groups(orig, segs):
        if not go or not ge:
            continue   # 片方にしかない(行の追加・削除)は、置換ではないので対象外
        if any(isinstance(segs[j].get("fill"), dict) for j in ge):
            continue   # 後処理(ed_fill の A・D・ed_llm)が直した行は機械の直し。「人の直し」として覚えると自己強化になる(plan/llm-postfix.md の 3)
        a, b = _norm(orig, go), _norm(segs, ge)
        if a == b or len(a) > 600 or len(b) > 600:
            continue
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag != "replace":
                continue
            w, r = a[i1:i2], b[j1:j2]
            if PUNCT_ONLY.match(w) or PUNCT_ONLY.match(r) or len(w) > 12 or len(r) > 12:
                continue   # 句読点だけの違い・言い回しごと書き換えた箇所は、辞書向きでない
            # 語の途中だけ(「ーイ→ワ」など)にならないよう、同じ種類の文字(カタカナ・漢字・英数字)が続く分は語の全体まで広げる
            while i1 > 0 and j1 > 0 and a[i1 - 1] == b[j1 - 1] and _txbase.char_class(a[i1 - 1]) and _txbase.char_class(a[i1 - 1]) == _txbase.char_class(a[i1]) == _txbase.char_class(b[j1]):
                i1 -= 1; j1 -= 1
            while i2 < len(a) and j2 < len(b) and a[i2] == b[j2] and _txbase.char_class(a[i2]) and _txbase.char_class(a[i2]) == _txbase.char_class(a[i2 - 1]) == _txbase.char_class(b[j2 - 1]):
                i2 += 1; j2 += 1
            w, r = a[i1:i2], b[j1:j2]
            if len(w) > 12 or len(r) > 12:
                continue
            ctx = False
            si, ei = i1, i2
            if len(w) < 2 and len(r) < 2:   # 1文字だけの違いは、前後1文字を足して誤爆を減らす
                ctx = True
                lc = a[i1 - 1] if i1 > 0 and j1 > 0 and a[i1 - 1] == b[j1 - 1] else ""
                rc = a[i2] if i2 < len(a) and j2 < len(b) and a[i2] == b[j2] else ""
                w, r = lc + w + rc, lc + r + rc
                si, ei = i1 - len(lc), i2 + len(rc)
            if len(w) >= 2 and w != r:
                out.append((w, r, ctx, a[max(0, si - 2):si], a[ei:ei + 2]))
    return out


def learn_groups(doc):
    """人が直した行(まとまり)を [{start,end,original,text}] で返す(学習の材料の行の数え方)。
    noSub(字幕に出さない)の行とその時間の機械の行は返さない。校正済みの行すべてを返す scope="proofed"(修正データの書き出し用)は 0.68.0 で書き出しと一緒に消した"""
    orig, segs = _prep_main(doc)
    out = []
    if not orig or not segs:
        return out
    for go, ge in _groups(orig, segs):
        if not go or not ge:
            continue
        a, b = _norm(orig, go), _norm(segs, ge)
        if a == b or not b:
            continue
        st, en = min(segs[i]["start"] for i in ge), max(segs[i]["end"] for i in ge)
        out.append({"start": st, "end": en, "original": a, "text": b})
    return out


_info_cache = {}


def _doc_info(tid):
    """文字起こし1件の学習用の情報(修正の一覧・各行の文章・修正した行数)。更新日時でキャッシュする。"""
    mt = os.stat(store.tx_path(tid)).st_mtime_ns
    hit = _info_cache.get(tid)
    if hit and hit[0] == mt:
        return hit[1]
    with open(store.tx_path(tid), "r", encoding="utf-8") as f:
        d = json.load(f)
    if d.get("evalSet") is True:
        info = None   # 評価用は、辞書・提案・用語の自動追加の元にしない(答えを見てから測ることになるため)
    elif d.get("original"):
        ev = learn_events(d)
        info = {"events": ev, "lines": len(learn_groups(d)),
                "texts": [re.sub(r"\s+", "", str(g.get("text", ""))) for g in (d.get("segments") or []) if isinstance(g, dict) and not is_nosub(g)]}
    else:
        info = None   # v0.5 より前の文字起こしは、機械の出力が残っていないので学習できない
    _info_cache[tid] = (mt, info)
    return info


def _all_infos():
    out = []
    for tid in sorted(store._tids()):
        try:
            info = _doc_info(tid)
        except (OSError, ValueError):
            continue
        if info is not None:
            out.append((tid, info))
    return out


def learned_candidates(min_count=1):
    settings = _settings.load_settings()
    have = {(replace.wb_split(w)[0], r) for w, r in replace.parse_replacements(settings.get("replacements"))}
    ignore = {str(x) for x in (settings.get("learnIgnore") or [])[:1000]}
    counts, docs, ctxs, used, lines = {}, {}, {}, 0, 0
    for tid, info in _all_infos():
        used += 1
        lines += info["lines"]
        for w, r, ctx, _l, _r in info["events"]:
            pr = (w, r)
            counts[pr] = counts.get(pr, 0) + 1
            docs.setdefault(pr, set()).add(tid)
            ctxs[pr] = ctx
    items = [{"wrong": w, "right": r, "count": c, "docs": len(docs[(w, r)]), "ctx": ctxs[(w, r)]} for (w, r), c in counts.items()
             if c >= min_count and (w, r) not in have and "%s=>%s" % (w, r) not in ignore]
    items.sort(key=lambda x: (-x["count"], -len(x["wrong"]), x["wrong"]))
    return {"items": items[:100], "docs": used, "lines": lines}


# ---------- 文脈つきの統計 → 修正の提案 / 自動置換 / 用語集 ----------
# 「直された回数」と「同じ語をそのまま残した回数」を数え、確度で3段階に分ける。
#   高: 3回以上・2件以上の文字起こしで直され、そのまま残した例が1つもない → 自動置換の対象(設定でオン時のみ)
#   中: 直した例が多く、そのまま残した例(と却下)より優勢 → 行に「候補」として出すだけ
#   低: 何も出さない
HIGH_POS, HIGH_DOCS, MID_RATIO, REJECT_WEIGHT = 3, 2, 0.6, 2
MAX_RULES = 300
_rules_cache = {"key": None, "val": None}
_fb_lock = threading.Lock()


def load_feedback():
    d = _fsio.read_json_or(_workdata.FEEDBACK, None, kind=dict)
    if d is None:
        return {"stat": {}, "dismissed": {}}
    out = {"stat": d.get("stat") if isinstance(d.get("stat"), dict) else {}, "dismissed": d.get("dismissed") if isinstance(d.get("dismissed"), dict) else {}}
    for src in ("alt", "yt"):   # 2つ目のエンジン(D1-b)・YouTube の字幕(案 A1)の候補の採用・却下の数(学習の統計とは別)
        a = d.get(src)
        if isinstance(a, dict):
            out[src] = {k: int(a[k]) if isinstance(a.get(k), int) and not isinstance(a.get(k), bool) and a[k] >= 0 else 0 for k in ("acc", "rej")}
    return out


def record_feedback(obj):
    tid = str(obj.get("tid") or "")
    action = obj.get("action")
    if action not in ("accept", "reject") or not _yschemas.TID_RE.match(tid):
        raise _errors.ApiError("bad_request", "記録の内容が正しくありません", 400)
    items = []
    for x in (obj.get("items") or [])[:500]:
        if isinstance(x, dict) and all(isinstance(x.get(k), str) and 0 < len(x[k]) <= 60 for k in ("wrong", "right")):
            # 候補の出どころ: tier "alt"(2つ目のエンジン)・"yt"(YouTube の字幕)と、2 つが一致してまとめた候補の also(例: alt の項目に ["yt"])
            raw = [x.get("tier")] + (list(x["also"])[:4] if isinstance(x.get("also"), list) else [])
            srcs = [t for t in dict.fromkeys(t for t in raw if isinstance(t, str)) if t in ("alt", "yt")]
            items.append((re.sub(r"[^\w-]", "", str(x.get("seg", "")))[:16], x["wrong"], x["right"], srcs))
    with _fb_lock:
        fb = load_feedback()
        for seg, w, r, srcs in items:
            # 2つ目のエンジン(tier "alt")・YouTube の字幕(tier "yt")の候補は学習の統計に入れない(学習の規則の確度を汚さない)。数だけ fb["alt"]・fb["yt"] に(当たり率を測る。D1-b・A1)
            for st in [fb.setdefault(t, {"acc": 0, "rej": 0}) for t in srcs] or [fb["stat"].setdefault("%s=>%s" % (w, r), {"acc": 0, "rej": 0})]:
                st["acc" if action == "accept" else "rej"] += 1
            if action == "reject" and seg:
                lst = fb["dismissed"].setdefault(tid, [])
                key = "%s|%s=>%s" % (seg, w, r)
                if key not in lst:
                    lst.append(key)
                del lst[:-2000]
        if len(fb["stat"]) > 5000:
            fb["stat"] = dict(list(fb["stat"].items())[-5000:])
        _fsio.atomic_write(_workdata.FEEDBACK, json.dumps(fb, ensure_ascii=False).encode("utf-8"), fsync_required=True)
    return len(items)


def _spans(text, w, r):
    """text の中で w がある位置(r の一部になっている箇所は除く)。"""
    rs = []
    if r:
        k = text.find(r)
        while k >= 0:
            rs.append((k, k + len(r)))
            k = text.find(r, k + 1)
    out, k = [], text.find(w)
    while k >= 0:
        if not any(a <= k and k + len(w) <= b for a, b in rs) and replace._bounded(text, k, w):   # 単語の途中には当てない(トル→ポル が「トルコ」に当たらない)
            out.append(k)
        k = text.find(w, k + 1)
    return out


def learn_rules(settings=None):
    """全文字起こしの修正から、{(誤,正): {pos, docs, pctx, neg(そのまま残した例の前後), ctx}} を作る。settings = 読んである設定(無ければ読む)"""
    settings = settings if settings is not None else _settings.load_settings()
    have = {(replace.wb_split(w)[0], r) for w, r in replace.parse_replacements(settings.get("replacements"))}
    ignore = {str(x) for x in (settings.get("learnIgnore") or [])[:1000]}
    infos = _all_infos()
    key = (tuple((t, _info_cache[t][0]) for t, _ in infos), tuple(sorted(have)), tuple(sorted(ignore)))
    if _rules_cache["key"] == key:
        return _rules_cache["val"]
    rules = {}
    for tid, info in infos:
        for w, r, ctx, l, rr in info["events"]:
            if (w, r) in have or "%s=>%s" % (w, r) in ignore:
                continue
            x = rules.setdefault((w, r), {"pos": 0, "docs": set(), "pctx": [], "neg": [], "ctx": False})
            x["pos"] += 1
            x["docs"].add(tid)
            x["pctx"].append((l, rr))
            x["ctx"] = x["ctx"] or ctx
    top = sorted(rules.items(), key=lambda kv: -kv[1]["pos"])[:MAX_RULES]
    rules = dict(top)
    for tid, info in infos:
        if not info["events"]:
            continue   # 1か所も直していない文字起こしは、見直していない可能性があるので「そのまま残した例」に数えない
        for text in info["texts"]:
            for (w, r), x in rules.items():
                if w in text:
                    for k in _spans(text, w, r):
                        x["neg"].append((text[max(0, k - 2):k], text[k + len(w):k + len(w) + 2]))
    _rules_cache["key"], _rules_cache["val"] = key, rules
    return rules


def _match(cl, cr, L, R):
    return bool((cl[-1:] and cl[-1:] == L[-1:]) or (cr[:1] and cr[:1] == R[:1]))


def _tier(x, L, R, st):
    """確度('high' / 'mid' / None)と、判断に使った (直した例, そのまま残した例)。"""
    acc, rej = st.get("acc", 0), st.get("rej", 0)
    pm, nm = x["pos"], 0
    if x["neg"]:
        pm = sum(1 for cl, cr in x["pctx"] if _match(cl, cr, L, R))
        nm = sum(1 for cl, cr in x["neg"] if _match(cl, cr, L, R))
        if pm + nm == 0:   # 前後の文字では判断できないときは、全体の比率で見る
            pm, nm = x["pos"], len(x["neg"])
    p, n = pm + acc, nm + REJECT_WEIGHT * rej
    if not x["neg"] and rej == 0 and x["pos"] >= HIGH_POS and len(x["docs"]) >= HIGH_DOCS:
        return "high", x["pos"], 0
    if p >= 1 and p / (p + n) >= MID_RATIO:
        return "mid", pm, nm
    return None, pm, nm


def find_suggestions(text, rules, fb, skip=(), only_high=False):
    """1行の文章への提案 [{i, wrong, right, tier, pos, neg}]。長い誤りを優先し、重なる提案は出さない。"""
    cands = []
    for (w, r), x in rules.items():
        if w not in text:
            continue
        st = fb["stat"].get("%s=>%s" % (w, r), {})
        for k in _spans(text, w, r):
            t, pm, nm = _tier(x, text[max(0, k - 2):k], text[k + len(w):k + len(w) + 2], st)
            if t and (t == "high" or not only_high):
                cands.append((k, w, r, t, pm, nm))
    cands.sort(key=lambda c: (-len(c[1]), c[0]))
    used, out = [], []
    for k, w, r, t, pm, nm in cands:
        if any(k < b and a < k + len(w) for a, b in used) or ("%s=>%s" % (w, r)) in skip:
            continue
        used.append((k, k + len(w)))
        out.append({"i": k, "wrong": w, "right": r, "tier": t, "pos": pm, "neg": nm})
    out.sort(key=lambda c: c["i"])
    return out


def suggest_for_doc(tid):
    """行ごとの提案(学習の統計)+ 2つ目のエンジンとの食い違いの候補(tier "alt"。同じ行・同じ位置では学習の提案を優先。alt.alt_suggest)。
    応答の alt = 2つ目のエンジンの結果の情報 {engine, model, label, at, count, skipped}(無い・評価用は null)"""
    doc = store.read_transcript(tid)
    rules, fb = learn_rules(), load_feedback()
    dismissed = set(fb["dismissed"].get(tid, []))
    items = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict) or len(items) >= 1000:
            continue
        text = str(g.get("text", ""))
        skip = {d.split("|", 1)[1] for d in dismissed if d.split("|", 1)[0] == g.get("id") and "|" in d}
        for sug in find_suggestions(text, rules, fb, skip):
            sug["seg"] = g.get("id")
            items.append(sug)
            if len(items) >= 1000:
                break
    alt_items, alt_info = alt.alt_suggest(tid, doc, dismissed, items)
    alt_items = alt_items[:max(0, 1000 - len(items))]
    learned = list(items)
    items += alt_items
    if alt_info:
        alt_info["count"] = len(alt_items)
    # YouTube の字幕の候補(tier "yt"。案 A1): 学習 → alt → yt の順に優先。alt と同じ直しは alt の項目に also: ["yt"] を付けてまとめる(ytcap.ytcap_suggest)
    yt_items, yt = ytcap.ytcap_suggest(tid, doc, dismissed, learned, alt_items)
    yt_items = yt_items[:max(0, 1000 - len(items))]
    items += yt_items
    if yt:
        yt["count"] = len(yt_items) + yt["agree"]
    return {"items": items, "rules": len(rules), "alt": alt_info, "yt": yt}


def auto_learned_replace(text, rules, fb):
    """確度が「高」の学習済み置換だけを適用する。(新しい文章, 置換した数)"""
    sugs = find_suggestions(text, rules, fb, only_high=True)
    for sg in reversed(sugs):
        text = text[:sg["i"]] + sg["right"] + text[sg["i"] + len(sg["wrong"]):]
    return text, len(sugs)


def load_roster():
    """同梱の名簿。読めない・形が違うときは空(画面では「名簿を読めません」と出す)。中身は文字列だけに整える。
    README で「直せます」と案内しているので、BOM 付きでも読む"""
    d = _fsio.read_json_or(_roster.ROSTER, None, kind=dict)
    if d is None:
        return {"asOf": "", "note": "", "groups": []}
    groups = []
    for g in d.get("groups") or []:
        names = [str(n).strip() for n in g.get("names") or [] if str(n).strip()]
        if names and g.get("id") and g.get("label"):
            groups.append({"id": str(g["id"])[:40], "label": str(g["label"])[:80], "names": names[:100]})
    return {"asOf": str(d.get("asOf") or "")[:20], "note": str(d.get("note") or "")[:400], "groups": groups}


def auto_glossary(user_terms, limit=150, settings=None):
    """よく直される正しい語を、認識のヒントとして自動で足す(ヒント全体が limit 文字に収まる範囲)。settings = 読んである設定(learn_rules へ)"""
    have = list(user_terms)
    out = []
    ranked = sorted(((x["pos"], r) for (w, r), x in learn_rules(settings).items() if not x["ctx"] and x["pos"] >= 2 and 2 <= len(r) <= 15), key=lambda t: (-t[0], t[1]))
    for _pos, r in ranked:
        if r in have or r in out:
            continue
        if len("、".join(have + out + [r])) > limit:
            continue
        out.append(r)
        if len(out) >= 20:
            break
    return out
