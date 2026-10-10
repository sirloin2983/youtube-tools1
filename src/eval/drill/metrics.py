# -*- coding: utf-8 -*-
"""④ テストと検証の層 eval/drill: 認識精度の測定(文字誤り率 CER。人が校正済みにした行を正解に、機械の出力 original と比べる)・
「字幕に出さない」行(noSub)の別集計・同時にしゃべっている所(重なり)の数え方・評価用の基準の記録(eval-baselines.json)。

役割で組み直す RS3-E5c(2026-10-10)に編集の ed_learn(段10 で editor/serve.py から分けた部品)から移した(中身は同じ)。
機械と人の行の対応づけ(_groups・_prep・split_nosub・_norm)は human/proof/learn、置換辞書は pipeline/transcribe/replace を呼ぶたびに読む
(④ から ②・① を読む向き。learn はここを読まない)。画面の API(/api/metrics・/api/eval-baselines・/api/eval-baseline)は serve が直に呼び、
dev/eval_asr.py・dev/eval_alt.py は serve の名前(S.norm_cer・S.lev_counts・S.doc_metrics など)で読む。
旧い名前 ed_learn.名前・S.名前 は editor/ed_learn.py(転送だけの殻。serve が _add_moved でここを足す = 殻は eval を読まない。RS5 で消す)と
serve の受付がここへ回す(テストの S.MAX_LEV_CELLS = … もここに入る)。
"""
import difflib
import itertools
import json
import re
import threading
import time
import unicodedata

from ytt import errors as _errors, fsio as _fsio, settings as _settings, workdata as _workdata  # noqa: E402
from pipeline.transcribe import replace  # noqa: E402   置換辞書の「正」を用語に数える(parse_replacements)
from pipeline.transcribe import roster as _roster  # noqa: E402   用語集の区切り split_terms(RS2-8a に ed_jobs から)
from human.proof import learn  # noqa: E402   機械と人の行の対応づけ(_groups・_prep・split_nosub・_norm。呼ぶたびに learn.名前 で読む)
import ed_store  # noqa: E402   文書の一覧と読み(_tids・read_transcript)


# ---------- 同時にしゃべっている所(重なり)と「字幕に出さない」行(noSub)の別集計 ----------
# noSub の行の外し方(split_nosub)と対応づけは human/proof/learn。ここは数え方だけ(計画: plan/line-b-overlap.md の 2-2・6-2 の 5)
OVERLAP_SEC = 0.3     # 人の行どうしが違う話者でこれ(秒)以上時刻が重なる所を「重なりのまとまり」にする(認識の時刻のぶれ 0.1〜0.2 秒を数えないため。計画 2-2 と同じ値)
OVERLAP_PERM = 3      # 重なりのまとまりの話者が、これ以下の人数なら並べ方を全部試す(それより多ければ開始時刻の順と話者ごとの 1 通り)


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
    raw = _roster.split_terms(st.get("glossary"))
    raw += [r for _w, r in replace.parse_replacements(st.get("replacements")) if r]
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
    orig, segs = learn._prep(doc)
    if not orig or not segs:
        return None
    orig, segs, ns_orig, ns_segs = learn.split_nosub(orig, segs)   # noSub(字幕に出さない)の行とその時間の機械の文字は、本体の数え方から外して別に出す
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
    for go, ge in learn._groups(orig, segs):
        if ge and not all(is_ok(segs[i]) for i in ge):   # 人の行があるまとまり(①・③)は全行が校正済みのときだけ
            continue
        rows = [segs[i] for i in ge] or [orig[i] for i in go]   # 時刻は人の行を優先
        a, b = min(r["start"] for r in rows), max(r["end"] for r in rows)
        if not ge and (a < lo - 0.05 or b > hi + 0.05):   # 機械だけ(②)は校正した範囲の中だけ
            continue
        raw_ref, raw_hyp = (learn._norm(segs, ge) if ge else ""), (learn._norm(orig, go) if go else "")
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
        except _errors.ApiError:
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
        raise _errors.ApiError("no_eval", "評価用の文字起こしがありません(画面の「評価用にする」で印を付けてください)", 400)
    if not o.get("groups"):
        raise _errors.ApiError("no_proofed", "評価用に校正済みの行がまだありません", 400)
    st = _settings.load_settings()
    rec = {"at": int(time.time() * 1000), "label": str(label or "")[:80], "docs": m["docs"], "cer": o["cer"], "refChars": o["refChars"], "sub": o["sub"], "del": o["del"], "ins": o["ins"],
           "configs": [{"config": c["config"], "cer": c["cer"], "refChars": c["refChars"]} for c in m["byConfig"]][:6],
           "dict": len(replace.parse_replacements(st.get("replacements"))), "glossaryChars": len(str(st.get("glossary") or ""))}
    with _base_lock:
        items = read_baselines()
        items.append(rec)
        _fsio.atomic_write(_workdata.EVAL_BASE, json.dumps(items[-100:], ensure_ascii=False, indent=1).encode("utf-8"), fsync_required=True)
    return rec
