#!/usr/bin/env python3
"""文字起こしの精度の「基準」を、今ある校正済みデータから測る(段階0。ツールは変更しない・データは読むだけ)。

    python tools/baseline_analysis.py [transcribe-tool のフォルダ] [出力先フォルダ]

- transcripts/*.json(segments=人が直した行、original=機械の出力)を、serve.py の関数でツールの画面と同じ方法で比べる
- dataset/docs/<id>/full.flac(校正した範囲の音声)があれば、行ごとの音量(小声の目安)も測る(ffmpeg が必要)
- 出力: accuracy-baseline.json(数値)。文章のまとめ(docs/accuracy/accuracy-baseline.md)は、この数値を見て人/AI が書く
- 個人データ(音声・文章の全文)は出力しない(例は短い抜粋だけ)
"""
import importlib.util
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように
TT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "transcribe-tool"))
OUT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "docs", "accuracy"))


def load_serve():
    """serve.py を一時フォルダに写して読み込む(読み込み時に作られるフォルダなどが、本物のデータの横にできないように)。"""
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(TT, "serve.py"), tmp)
    spec = importlib.util.spec_from_file_location("serve_copy", os.path.join(tmp, "serve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = load_serve()


def rms_db(samples):
    if not samples:
        return None
    s = sum(x * x for x in samples) / len(samples)
    return round(10 * math.log10(s + 1e-12), 1)


def load_audio(path):
    """16kHz モノラルの float の並び(ffmpeg で読む)。"""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    import array
    a = array.array("h")
    a.frombytes(raw[: len(raw) // 2 * 2])
    return [x / 32768.0 for x in a]


def names():
    out = set()
    try:
        r = json.load(open(os.path.join(TT, "hololive-roster.json"), encoding="utf-8"))
        for g in r.get("groups") or []:
            for n in g.get("names") or []:
                out.add(n)
    except (OSError, ValueError):
        pass
    try:
        st = json.load(open(os.path.join(TT, "settings.json"), encoding="utf-8"))
        out.update(x.strip() for x in str(st.get("glossary") or "").splitlines() if x.strip())
    except (OSError, ValueError):
        pass
    return sorted(out, key=len, reverse=True)


def main():
    NAMES = names()
    docs = []
    for fn in sorted(os.listdir(os.path.join(TT, "transcripts"))):
        if fn.endswith(".json"):
            try:
                docs.append((fn[:-5], json.load(open(os.path.join(TT, "transcripts", fn), encoding="utf-8"))))
            except (OSError, ValueError):
                pass
    rows = []          # まとまり(機械と人の行を時刻で対応づけた単位)ごとの記録
    per_doc = {}
    inventory = {"docs": len(docs), "docsWithProofed": 0, "evalDocs": 0, "evalDocsProofed": 0, "proofedLines": 0, "proofedSec": 0.0,
                 "lines": 0, "tagCounts": Counter(), "flaggedProofed": 0, "models": Counter(), "titles": []}
    for tid, d in docs:
        segs = d.get("segments") or []
        pr = [g for g in segs if g.get("proofed")]
        inventory["lines"] += len(segs)
        inventory["proofedLines"] += len(pr)
        inventory["proofedSec"] += sum(max(0.0, g["end"] - g["start"]) for g in pr)
        inventory["models"][str(d.get("model"))] += 1
        inventory["titles"].append(d.get("title", ""))
        if d.get("evalSet"):
            inventory["evalDocs"] += 1
            if pr:
                inventory["evalDocsProofed"] += 1
        if pr:
            inventory["docsWithProofed"] += 1
        for g in pr:
            for t in g.get("tags") or []:
                inventory["tagCounts"][t] += 1
            if g.get("flag"):
                inventory["flaggedProofed"] += 1
        m = S.doc_metrics(d, terms=NAMES)
        if m:
            fm = S.acc_finish(m); fm.pop("worst", None)   # 文章の抜粋は出さない(個人データをリポジトリに残さないため)
            per_doc[tid] = {"title": d.get("title", ""), "model": d.get("model"), "evalSet": bool(d.get("evalSet")), **fm}
        # まとまりごと(doc_metrics と同じ規則。条件別に分けて数えるため)
        orig, ss = S._prep(d)
        if not orig or not ss or not pr:
            continue
        lo, hi = min(g["start"] for g in pr), max(g["end"] for g in pr)
        audio, a0 = None, 0.0
        man = os.path.join(TT, "dataset", "docs", tid, "manifest.json")
        fl = os.path.join(TT, "dataset", "docs", tid, "full.flac")
        if os.path.isfile(fl) and os.path.isfile(man):
            try:
                a0 = float(json.load(open(man, encoding="utf-8")).get("start") or 0)
                audio = load_audio(fl)
            except (OSError, ValueError):
                audio = None
        for go, ge in S._groups(orig, ss):
            ok = lambda g: bool(g.get("proofed")) and "unclear" not in (g.get("tags") or [])
            if ge and not all(ok(ss[i]) for i in ge):
                continue
            if not ge:
                a, b = min(orig[i]["start"] for i in go), max(orig[i]["end"] for i in go)
                if a < lo - 0.05 or b > hi + 0.05:
                    continue
            ref = S.norm_cer(S._norm(ss, ge)) if ge else ""
            hyp = S.norm_cer(S._norm(orig, go)) if go else ""
            if not ref and not hyp:
                continue
            s_, d_, i_ = S.lev_counts(ref, hyp)
            items = [ss[i] for i in ge] or [orig[i] for i in go]
            a, b = min(x["start"] for x in items), max(x["end"] for x in items)
            loud = None
            if audio:
                i0, i1 = int((a - a0) * 16000), int((b - a0) * 16000)
                loud = rms_db(audio[max(0, i0):max(0, i1)])
            tags = sorted({t for i in ge for t in (ss[i].get("tags") or [])})
            flag = "、".join(sorted({ss[i].get("flag") for i in ge if ss[i].get("flag")}))
            rows.append({"doc": tid, "evalSet": bool(d.get("evalSet")), "model": d.get("model"), "start": round(a, 2), "end": round(b, 2),
                         "refChars": len(ref), "sub": s_, "del": d_, "ins": i_, "tags": tags, "flag": flag, "loudDb": loud,
                         "names": [n for n in NAMES if n in ref], "namesHit": [n for n in NAMES if n in ref and n in hyp],
                         "kind": "both" if go and ge else ("machineOnly" if go else "humanOnly")})

    def cer(rs):
        n = sum(r["refChars"] for r in rs)
        e = sum(r["sub"] + r["del"] + r["ins"] for r in rs)
        return {"cer": round(e / n, 4) if n else None, "refChars": n, "errs": e, "groups": len(rs),
                "sub": sum(r["sub"] for r in rs), "del": sum(r["del"] for r in rs), "ins": sum(r["ins"] for r in rs)}

    def boot(rs, key="doc", n=2000):
        """文書単位のブートストラップで CER のおおよその 95% 区間。"""
        by = defaultdict(list)
        for r in rs:
            by[r[key]].append(r)
        ks = list(by)
        if len(ks) < 2:
            return None
        rnd = random.Random(0)
        vals = []
        for _ in range(n):
            pick = [r for k in (rnd.choice(ks) for _ in ks) for r in by[k]]
            c = cer(pick)["cer"]
            if c is not None:
                vals.append(c)
        vals.sort()
        return [round(vals[int(len(vals) * 0.025)], 4), round(vals[int(len(vals) * 0.975)], 4)] if vals else None

    res = {"inventory": {**inventory, "tagCounts": dict(inventory["tagCounts"]), "models": dict(inventory["models"]),
                         "proofedMin": round(inventory["proofedSec"] / 60, 1)}}
    res["overall"] = {**cer(rows), "ci95_doc": boot(rows)}
    res["eval"] = {**cer([r for r in rows if r["evalSet"]]), "ci95_doc": boot([r for r in rows if r["evalSet"]])}
    res["train"] = {**cer([r for r in rows if not r["evalSet"]]), "ci95_doc": boot([r for r in rows if not r["evalSet"]])}
    res["byModel"] = {m: {**cer(v), "ci95_doc": boot(v)} for m, v in _group(rows, "model").items()}
    res["byKind"] = {k: cer(v) for k, v in _group(rows, "kind").items()}
    res["byTag"] = {t: cer([r for r in rows if t in r["tags"]]) for t in ("overlap", "bgm")}
    res["byTag"]["none"] = cer([r for r in rows if not r["tags"]])
    res["byFlag"] = {"flagged": cer([r for r in rows if r["flag"]]), "unflagged": cer([r for r in rows if not r["flag"]])}
    fl = Counter()
    for r in rows:
        for f in (r["flag"] or "").split("、"):
            if f:
                fl[f] += 1
    res["flagKinds"] = dict(fl)
    ld = sorted([r for r in rows if r["loudDb"] is not None and r["kind"] != "machineOnly"], key=lambda r: r["loudDb"])
    if ld:
        q = len(ld) // 4 or 1
        parts = [ld[:q], ld[q:2 * q], ld[2 * q:3 * q], ld[3 * q:]]
        res["byLoudness"] = [{"range_db": [p[0]["loudDb"], p[-1]["loudDb"]], **cer(p)} for p in parts if p]
    nm = Counter(); nh = Counter()
    for r in rows:
        for n in r["names"]:
            nm[n] += 1
        for n in r["namesHit"]:
            nh[n] += 1
    res["names"] = {n: {"inRef": nm[n], "recognized": nh[n]} for n in nm}
    pairs = Counter()
    for tid, d in docs:
        for w, r, _c in S.learn_pairs(d):
            pairs[(w, r)] += 1
    res["topCorrections"] = [{"wrong": w, "right": r, "count": c} for (w, r), c in pairs.most_common(40)]
    res["perDoc"] = per_doc
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "accuracy-baseline.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: res[k] for k in ("overall", "eval", "train", "byModel", "byKind", "byTag", "byFlag", "flagKinds")}, ensure_ascii=False, indent=1))
    print(json.dumps(res.get("byLoudness"), ensure_ascii=False))
    print(json.dumps(res["inventory"], ensure_ascii=False)[:1500])


def _group(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[str(r[key])].append(r)
    return g


if __name__ == "__main__":
    main()
