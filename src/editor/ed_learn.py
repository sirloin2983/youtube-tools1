# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 置換辞書・修正からの学習・提案・認識精度の測定・評価用の基準(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
修正データの書き出し(zip)とデータの保管(dataset/ の書き手)は 0.68.0(2026-10-10。ユーザー決定「使っていない」)で消した(作業データの dataset/ は残る。戻すときは git の履歴)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import difflib
import itertools
import json
import os
import re
import threading
import time
import unicodedata

import ed_alt  # noqa: E402,F401
import ed_ytcap  # noqa: E402,F401   YouTube の字幕の候補(suggest_for_doc の yt。案 A1)
import ed_jobs  # noqa: E402,F401
import ed_state  # noqa: E402,F401
from ytt import workdata as _workdata  # noqa: E402   (置き場所と版の今の値。RS3-0A に ed_state から移した)
from pipeline.transcribe import roster as _roster  # noqa: E402   (名簿のファイルの場所 ROSTER の持ち主。RS3-0A に ed_state から)
import ed_store  # noqa: E402,F401
from ytt import fsio as _fsio, settings as _settings  # noqa: E402
from pipeline.transcribe import txbase as _txbase  # noqa: E402   文字の種類 char_class(RS2-4b に _cc を移した)
# 設定(settings.json)の読み書きと鍵の検査は ytt/settings(RS3-1 に移した。_settings.load_settings() で呼ぶたびに読む)


def parse_replacements(text):
    """「誤=>正」を1行に1つ書いた文字列 → [(誤, 正)](長い誤りから先に置換する)。"""
    pairs = []
    for line in str(text or "").splitlines():
        k = line.find("=>")
        if k > 0 and line[:k].strip():
            pairs.append((line[:k].strip(), line[k + 2:].strip()))
    return sorted(pairs[:500], key=lambda p: -len(p[0]))


def _bounded(text, k, w):
    """text の位置 k にある w が、同じ種類の文字の並び(カタカナ・漢字・英数字)の途中で切れていないか。
    例: 「トル」は「トルコ」の中では×、「トル様」の中なら○(ひらがな・記号との境目は切れ目とみなす)。"""
    c = _txbase.char_class(w[0])
    if c and k > 0 and _txbase.char_class(text[k - 1]) == c:
        return False
    c = _txbase.char_class(w[-1])
    if c and k + len(w) < len(text) and _txbase.char_class(text[k + len(w)]) == c:
        return False
    return True


def wb_split(w):
    """置換辞書の「誤」が |語| の形なら、(語, True)。単語の途中には当てない指定。それ以外は (w, False)。"""
    if len(w) >= 3 and w[0] == "|" and w[-1] == "|":
        return w[1:-1], True
    return w, False


def apply_replacements(text, pairs):
    n = 0
    for w, r in pairs:
        core, wb = wb_split(w)
        if not core or core not in text:
            continue
        if not wb:
            n += text.count(core)
            text = text.replace(core, r)
            continue
        out, i, k = [], 0, text.find(core)
        while k >= 0:
            if _bounded(text, k, core):
                out.append(text[i:k]); out.append(r); i = k + len(core); n += 1
                k = text.find(core, i)
            else:
                k = text.find(core, k + 1)
        out.append(text[i:]); text = "".join(out)
    return text, n


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
    orig = sorted([o for o in (doc.get("original") or []) if isinstance(o, dict) and ed_state.num(o.get("start")) is not None and ed_state.num(o.get("end")) is not None],
                  key=lambda o: o["start"])
    # 空のままの下書き(印 draft・文字なし。重なりの所に置いた空の行)は数えない: 残っている間、重なる校正済みのまとまりを丸ごと数から外してしまうため
    segs = sorted([g for g in (doc.get("segments") or []) if isinstance(g, dict) and not ed_state.blank_draft_row(g)], key=lambda g: g["start"])
    return orig, segs


# ---------- 「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり) ----------
# 行の印 noSub: true = 字幕に出さない(ゲームのキャラ・NPC の声など)。行は消えず、機械の出力 original も変わらない。
# 学習・辞書・提案・保管の材料にはしない。精度の数え方では、人の行のうち noSub の行を正解に入れず、その時間に機械が書いた文字も本体から外して別に数える
# (確かめ済みの文書で「何も話していない所の機械の文字 = 余分」に数えられないように)。計画: plan/line-b-overlap.md の 2-1・6-2 の 5
NOSUB_IN = 0.5        # 機械の行のうち、noSub の行の時間に入る長さの割合がこれ以上なら、noSub の時間の文字として本体から外す
OVERLAP_SEC = 0.3     # 人の行どうしが違う話者でこれ(秒)以上時刻が重なる所を「重なりのまとまり」にする(認識の時刻のぶれ 0.1〜0.2 秒を数えないため。計画 2-2 と同じ値)
OVERLAP_PERM = 3      # 重なりのまとまりの話者が、これ以下の人数なら並べ方を全部試す(それより多ければ開始時刻の順と話者ごとの 1 通り)


def is_nosub(g):
    return isinstance(g, dict) and g.get("noSub") is True


def split_nosub(orig, segs):
    """(機械の行, 人の行) -> (本体の機械の行, 本体の人の行, noSub の時間の機械の行, noSub の人の行)。
    noSub の人の行は本体から外す。機械の行は、半分以上(NOSUB_IN)が noSub の行の時間に入るものを外す。noSub の行が無ければ、渡した 2 つのリストをそのまま返す"""
    ns = [g for g in segs if is_nosub(g)]
    if not ns:
        return orig, segs, [], []
    span = ed_state.union_spans((g["start"], g["end"]) for g in ns if ed_state.num(g.get("start")) is not None and ed_state.num(g.get("end")) is not None)   # noSub の行の時間をつなげた区間
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


def nosub_stats(ns_orig, ns_segs):
    """noSub の別集計 {rows, sec, machineChars}(行の数・その長さの合計(秒)・その時間に機械が書いた文字数(norm_cer 後))"""
    return {"rows": len(ns_segs), "sec": round(sum(max(0.0, g["end"] - g["start"]) for g in ns_segs), 2),
            "machineChars": sum(len(norm_cer(o.get("text", ""))) for o in ns_orig)}


def _ov_sec(a, b):
    return min(a["end"], b["end"]) - max(a["start"], b["start"])


def is_overlap_group(segs, ge):
    """人の行 segs の中の ge(1 まとまりの行の番号)に、違う話者(どちらも話者あり)で OVERLAP_SEC 秒以上時刻が重なる組があるか(noSub は先に外した行を渡す。
    音のメモ overlap は見ない = 付け忘れに左右されない)。重なりのまとまりの判定はここだけ"""
    rows = sorted((segs[i] for i in ge), key=lambda g: g["start"])
    for i, a in enumerate(rows):
        sa = a.get("speaker")
        if not sa:
            continue
        for b in rows[i + 1:]:
            if b["start"] >= a["end"]:
                break
            sb = b.get("speaker")
            if sb and sb != sa and _ov_sec(a, b) >= OVERLAP_SEC - 1e-6:
                return True
    return False


def overlap_orders(segs, ge):
    """重なりのまとまりの人の行を、文字を並べる順番(行の文字列の組)で返す: 開始時刻の順(今までの数え方)と、話者ごとにまとめた順(話者の並びの入れ替え)。
    機械の出力には話者が無く、同時発話は書く順番が決まらないため、いちばん小さい CER の並べ方を採る(計画 6-2 の 5)"""
    rows = sorted((segs[i] for i in ge), key=lambda g: g["start"])
    texts = [norm_cer(str(g.get("text", ""))) for g in rows]
    spks = []
    for g in rows:
        k = g.get("speaker") or ""
        if k not in spks:
            spks.append(k)
    orders = ["".join(texts)]
    seqs = list(itertools.permutations(spks)) if len(spks) <= OVERLAP_PERM else [tuple(spks)]
    for q in seqs:
        t = "".join(texts[i] for k in q for i, g in enumerate(rows) if (g.get("speaker") or "") == k)
        if t not in orders:
            orders.append(t)
    return orders


def overlap_best_counts(segs, ge, hyp):
    """重なりのまとまりの (置換, 脱落, 挿入)。hyp = 機械の文字(norm_cer 済み)。並べ方ごとの編集距離のうち小さい方(同じなら開始時刻の順)"""
    best = None
    for ref in overlap_orders(segs, ge):
        c = lev_counts(ref, hyp)
        if best is None or sum(c) < sum(best):
            best = c
    return best


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
    mt = os.stat(ed_store.tx_path(tid)).st_mtime_ns
    hit = _info_cache.get(tid)
    if hit and hit[0] == mt:
        return hit[1]
    with open(ed_store.tx_path(tid), "r", encoding="utf-8") as f:
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
    for tid in sorted(ed_store._tids()):
        try:
            info = _doc_info(tid)
        except (OSError, ValueError):
            continue
        if info is not None:
            out.append((tid, info))
    return out


def learned_candidates(min_count=1):
    settings = _settings.load_settings()
    have = {(wb_split(w)[0], r) for w, r in parse_replacements(settings.get("replacements"))}
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
    if action not in ("accept", "reject") or not ed_state.TID_RE.match(tid):
        raise ed_state.ApiError("bad_request", "記録の内容が正しくありません", 400)
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
        ed_state.atomic_write(_workdata.FEEDBACK, json.dumps(fb, ensure_ascii=False).encode("utf-8"))
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
        if not any(a <= k and k + len(w) <= b for a, b in rs) and _bounded(text, k, w):   # 単語の途中には当てない(トル→ポル が「トルコ」に当たらない)
            out.append(k)
        k = text.find(w, k + 1)
    return out


def learn_rules(settings=None):
    """全文字起こしの修正から、{(誤,正): {pos, docs, pctx, neg(そのまま残した例の前後), ctx}} を作る。settings = 読んである設定(無ければ読む)"""
    settings = settings if settings is not None else _settings.load_settings()
    have = {(wb_split(w)[0], r) for w, r in parse_replacements(settings.get("replacements"))}
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
    """行ごとの提案(学習の統計)+ 2つ目のエンジンとの食い違いの候補(tier "alt"。同じ行・同じ位置では学習の提案を優先。ed_alt.alt_suggest)。
    応答の alt = 2つ目のエンジンの結果の情報 {engine, model, label, at, count, skipped}(無い・評価用は null)"""
    doc = ed_store.read_transcript(tid)
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
    alt_items, alt = ed_alt.alt_suggest(tid, doc, dismissed, items)
    alt_items = alt_items[:max(0, 1000 - len(items))]
    learned = list(items)
    items += alt_items
    if alt:
        alt["count"] = len(alt_items)
    # YouTube の字幕の候補(tier "yt"。案 A1): 学習 → alt → yt の順に優先。alt と同じ直しは alt の項目に also: ["yt"] を付けてまとめる(ed_ytcap.ytcap_suggest)
    yt_items, yt = ed_ytcap.ytcap_suggest(tid, doc, dismissed, learned, alt_items)
    yt_items = yt_items[:max(0, 1000 - len(items))]
    items += yt_items
    if yt:
        yt["count"] = len(yt_items) + yt["agree"]
    return {"items": items, "rules": len(rules), "alt": alt, "yt": yt}


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


# ---------- 認識精度の測定(文字誤り率 CER) ----------
# 正解 = 人が「校正済み」にした行の文章 / 機械の出力 = original。句読点・空白・記号・全角半角・大文字小文字の違いは数えない。
# CER = (置換 + 脱落 + 挿入) ÷ 正解の文字数。置換=別の字に間違えた、脱落=正解にある字が機械に無い、挿入=機械が余計な字を出した(幻覚など)。
MAX_LEV_CELLS = 250000   # 1まとまりの文字数が多すぎるときは、厳密な編集距離をやめて近似にする


# 伸ばしの「〜」(波ダッシュ・全角チルダ・半角の ~)は長音「ー」と同じに数える(ユーザー決定 2026-10-04:「〜 と ー の違いは無視する」)。
# NFKC で全角チルダ ～ は ~ になる。〜 は記号なので、読み替えないと下の絞り込みで消え、「すご〜い」と「すごーい」が 1 文字違いになっていた
_LONG_MARKS = str.maketrans({"〜": "ー", "~": "ー", "⁓": "ー", "∼": "ー"})
# 表記の違いを数えない(ユーザー決定 2026-10-06。docs/spec/subtitle-notation.md の B): CER は「聞き取れたか」を測り、字幕としての書き方は数えない。
# カタカナ → ひらがな(ァ〜ヶ。ヴ → ゔ)・小さい母音 → 大きい母音(まぁ = まあ。ゃゅょ・っ は音が違うので残す)・伸ばし棒と小さいかなの連続は 1 つ
_SMALL_VOWELS = str.maketrans("ぁぃぅぇぉ", "あいうえお")
_RUNS = re.compile(r"([ーぁぃぅぇぉっ])\1+")


def norm_cer(text):
    t = unicodedata.normalize("NFKC", str(text or "")).lower().translate(_LONG_MARKS)
    t = "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in t if unicodedata.category(ch)[0] in "LNM")
    return _RUNS.sub(r"\1", t).translate(_SMALL_VOWELS)


def lev_counts(ref, hyp):
    """(置換, 脱落, 挿入)。ref=正解、hyp=機械の出力。編集距離が最小になる組み合わせで数える。"""
    n, m = len(ref), len(hyp)
    if n == 0:
        return (0, 0, m)
    if m == 0:
        return (0, n, 0)
    if n * m > MAX_LEV_CELLS:   # 近似(difflib)。極端に長い1まとまりだけ
        s = d = i = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes():
            if tag == "replace":
                a, b = i2 - i1, j2 - j1
                s += min(a, b)
                d += max(0, a - b)
                i += max(0, b - a)
            elif tag == "delete":
                d += i2 - i1
            elif tag == "insert":
                i += j2 - j1
        return (s, d, i)
    prev = [(j, 0, 0, j) for j in range(m + 1)]
    for a in range(1, n + 1):
        cur = [(a, 0, a, 0)]
        ra = ref[a - 1]
        for b in range(1, m + 1):
            if ra == hyp[b - 1]:
                best = prev[b - 1]
            else:
                p = prev[b - 1]
                best = (p[0] + 1, p[1] + 1, p[2], p[3])
                q = prev[b]
                if q[0] + 1 < best[0]:
                    best = (q[0] + 1, q[1], q[2] + 1, q[3])
                r = cur[b - 1]
                if r[0] + 1 < best[0]:
                    best = (r[0] + 1, r[1], r[2], r[3] + 1)
            cur.append(best)
        prev = cur
    return prev[m][1:]


def metric_terms(settings=None):
    """「用語が正しく出たか」を数えるための用語(用語集 + 置換辞書の「正」)。正規化済み・2文字以上。"""
    st = settings if settings is not None else _settings.load_settings()
    raw = ed_jobs.split_terms(st.get("glossary"))
    raw += [r for _w, r in parse_replacements(st.get("replacements")) if r]
    out = []
    for t in raw:
        n = norm_cer(t)
        if len(n) >= 2 and n not in out:
            out.append(n)
    return out[:300]


def new_acc():
    return {"groups": 0, "changed": 0, "refChars": 0, "sub": 0, "del": 0, "ins": 0, "termRef": 0, "termHit": 0, "termExtra": 0,
            "machineOnly": 0, "machineOnlyChars": 0, "worst": []}


def acc_line(acc, ref, hyp, terms=(), info=None, machine_only=False):
    """1まとまり(正解 ref と機械の出力 hyp。どちらも norm_cer 済み)を集計に足す。"""
    s, d, i = lev_counts(ref, hyp)
    acc["groups"] += 1
    acc["refChars"] += len(ref)
    acc["sub"] += s
    acc["del"] += d
    acc["ins"] += i
    if s + d + i:
        acc["changed"] += 1
        if info is not None:
            acc["worst"].append({**info, "errs": s + d + i})
            acc["worst"].sort(key=lambda x: -x["errs"])
            del acc["worst"][10:]
    if machine_only:
        acc["machineOnly"] += 1
        acc["machineOnlyChars"] += len(hyp)
    for t in terms:
        rc, hc = ref.count(t), hyp.count(t)
        acc["termRef"] += rc
        acc["termHit"] += min(rc, hc)
        acc["termExtra"] += max(0, hc - rc)   # 正解に無いのに機械が出した用語(用語集が誘発した誤挿入の疑い)


def acc_merge(a, b):
    for k in ("groups", "changed", "refChars", "sub", "del", "ins", "termRef", "termHit", "termExtra", "machineOnly", "machineOnlyChars"):
        a[k] += b[k]
    a["worst"] = sorted(a["worst"] + b["worst"], key=lambda x: -x["errs"])[:10]
    if b.get("noSub"):
        n = a.setdefault("noSub", {"rows": 0, "sec": 0.0, "machineChars": 0})
        n["rows"] += b["noSub"]["rows"]
        n["sec"] = round(n["sec"] + b["noSub"]["sec"], 2)
        n["machineChars"] += b["noSub"]["machineChars"]


def acc_finish(acc):
    out = dict(acc)
    errs = acc["sub"] + acc["del"] + acc["ins"]
    out["errs"] = errs
    out["cer"] = round(errs / acc["refChars"], 4) if acc["refChars"] else None
    out["termRate"] = round(acc["termHit"] / acc["termRef"], 4) if acc["termRef"] else None
    return out


def doc_metrics(doc, legacy=False, terms=()):
    """1件の文字起こしの集計。校正済みの行が無ければ None(legacy=True なら、校正済みの印が無くても、修正のある文書は全行を校正済みとみなして仮計算)。
    数える対象: ①機械と人の両方にある まとまり(全行が校正済み) ②機械だけにある まとまり(人が行を消した=挿入の誤り。校正した範囲の中だけ)
    ③人だけにある まとまり(人が足した行=脱落の誤り。全行が校正済み)"""
    terms = tuple(dict.fromkeys(n for n in (norm_cer(t) for t in terms) if n))   # 文字と同じ正規化に(カタカナのままの用語が当たらないため。済みの用語は変わらない)
    orig, segs = _prep(doc)
    if not orig or not segs:
        return None
    orig, segs, ns_orig, ns_segs = split_nosub(orig, segs)   # noSub(字幕に出さない)の行とその時間の機械の文字は、本体の数え方から外して別に出す
    if not segs:
        return None
    proofed = [g for g in segs if g.get("proofed")]
    basis = "proofed"
    if proofed:
        lo, hi = min(g["start"] for g in proofed), max(g["end"] for g in proofed)
        is_ok = lambda g: bool(g.get("proofed")) and "unclear" not in (g.get("tags") or [])
    elif legacy:
        if "".join(norm_cer(o.get("text", "")) for o in orig) == "".join(norm_cer(g.get("text", "")) for g in segs):
            return None   # 修正が無い文書は、見直したのか分からないので数えない
        basis = "legacy"
        lo, hi = min(g["start"] for g in segs), max(g["end"] for g in segs)
        is_ok = lambda g: "unclear" not in (g.get("tags") or [])
    else:
        return None
    acc = new_acc()
    for go, ge in _groups(orig, segs):
        if ge and not all(is_ok(segs[i]) for i in ge):   # 人の行があるまとまり(①・③)は全行が校正済みのときだけ
            continue
        rows = [segs[i] for i in ge] or [orig[i] for i in go]   # 時刻は人の行を優先
        a, b = min(r["start"] for r in rows), max(r["end"] for r in rows)
        if not ge and (a < lo - 0.05 or b > hi + 0.05):   # 機械だけ(②)は校正した範囲の中だけ
            continue
        raw_ref, raw_hyp = (_norm(segs, ge) if ge else ""), (_norm(orig, go) if go else "")
        ref, hyp, mo = norm_cer(raw_ref), norm_cer(raw_hyp), not ge   # norm_cer("") は ""
        if not ref and not hyp:
            continue
        acc_line(acc, ref, hyp, terms, {"start": round(a, 2), "end": round(b, 2), "ref": raw_ref[:120], "hyp": raw_hyp[:120]}, mo)
    if not acc["groups"]:
        return None
    acc["basis"] = basis
    if ns_segs:   # noSub の行がある文書だけ(無い文書は今までと同じ形)
        acc["noSub"] = nosub_stats(ns_orig, ns_segs)
    return acc


def config_key(d):
    """認識の設定ごとに成績を分けて比べるための名前(モデル・用語集の有無・速度優先・再認識を含むか)。"""
    p = d.get("params") or {}
    parts = [str(d.get("model") or "?").split("/")[-1], "用語集あり" if p.get("glossary") else "用語集なし"]
    if p.get("beam") == 1:
        parts.append("速度優先")
    if d.get("retranscribed"):
        parts.append("再認識を含む")
    return " / ".join(parts)


def all_metrics(tid=None, legacy=False, scope="all"):
    terms = metric_terms()
    tids = [tid] if tid else sorted(ed_store._tids())
    total, by_cfg, rows = new_acc(), {}, []
    proofed_lines = docs_proofed = docs = 0
    for t in tids:
        try:
            d = ed_store.read_transcript(t)
        except ed_state.ApiError:
            continue
        if not tid and ((scope == "eval") != (d.get("evalSet") is True)) and scope != "all":
            continue
        docs += 1
        n = sum(1 for g in d.get("segments") or [] if isinstance(g, dict) and g.get("proofed"))
        proofed_lines += n
        docs_proofed += 1 if n else 0
        m = doc_metrics(d, legacy, terms)
        if not m:
            continue
        cfg = config_key(d)
        for w in m["worst"]:
            w["doc"] = str(d.get("title") or "")[:40]
        acc_merge(by_cfg.setdefault(cfg, new_acc()), m)
        acc_merge(total, m)
        row = acc_finish(m)
        row.update({"id": t, "title": str(d.get("title") or "")[:60], "config": cfg})
        row.pop("worst", None)
        rows.append(row)
    return {"scope": scope if not tid else "doc", "legacy": bool(legacy), "docs": docs, "docsProofed": docs_proofed, "proofedLines": proofed_lines, "overall": acc_finish(total),
            "byConfig": sorted(({"config": k, **acc_finish(v)} for k, v in by_cfg.items()), key=lambda x: x["config"]), "byDoc": rows, "termCount": len(terms)}


# ---------- 評価用の基準の記録 ----------
# 置き場所は ytt/workdata の EVAL_BASE(作業データの eval-baselines.json。RS3-0A に ed_learn から移した = serve.set_data_dir が作り直す)
_base_lock = threading.Lock()


def read_baselines():
    return _fsio.read_json_or(_workdata.EVAL_BASE, [], kind=list)


def record_baseline(label):
    """評価用の文書の、いまの成績を記録する(施策の前後で比べるため)。評価用が無い・校正済みが無いときは断る。"""
    m = all_metrics(None, False, "eval")
    o = m["overall"]
    if not m["docs"]:
        raise ed_state.ApiError("no_eval", "評価用の文字起こしがありません(画面の「評価用にする」で印を付けてください)", 400)
    if not o.get("groups"):
        raise ed_state.ApiError("no_proofed", "評価用に校正済みの行がまだありません", 400)
    st = _settings.load_settings()
    rec = {"at": int(time.time() * 1000), "label": str(label or "")[:80], "docs": m["docs"], "cer": o["cer"], "refChars": o["refChars"], "sub": o["sub"], "del": o["del"], "ins": o["ins"],
           "configs": [{"config": c["config"], "cer": c["cer"], "refChars": c["refChars"]} for c in m["byConfig"]][:6],
           "dict": len(parse_replacements(st.get("replacements"))), "glossaryChars": len(str(st.get("glossary") or ""))}
    with _base_lock:
        items = read_baselines()
        items.append(rec)
        ed_state.atomic_write(_workdata.EVAL_BASE, json.dumps(items[-100:], ensure_ascii=False, indent=1).encode("utf-8"))
    return rec
