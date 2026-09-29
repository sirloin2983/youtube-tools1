#!/usr/bin/env python3
"""文字起こしの精度を、校正済みの文字起こし(評価用)で測る道具(文字起こしの改善の計画 段0-2。docs/transcription-overhaul-plan.md)。

    python tools/eval_asr.py stored  [--scope eval|train|all] [--label 名前]
        保存してある機械の出力(original)と、人が直した行を比べる(認識はしない。今の基準)
    python tools/eval_asr.py run     [--model large-v3] [--vad normal] [--beam 5] [--glossary "トワ、スバル"] [--context none|auto] [--temp0] [--scope eval] [--label 名前]
        評価用の音声を、指定のモデル・設定で認識し直して比べる(指定しない項目は、文字起こしの今の設定 settings.json のまま)。
        --context auto = 配信ごとの文脈(出る人の名前と呼び名。計画 段1-2)を文書ごとに作って渡す(既定 none = 渡さない = 基準)。
        --temp0 = 温度 0 に固定(雑音の多い音声で回ごとに結果が変わるのを抑える。比べるときは両方に付ける)
    python tools/eval_asr.py compare 結果A.json 結果B.json
        2つの結果を、同じ文書どうしで比べる(差と 95% の範囲。範囲が 0 をまたげば「差があるとは言えない」)
    python tools/eval_asr.py list
        今までの結果の一覧

- 比べ方は文字起こしの画面の「認識精度の測定」と同じ(serve.py の _groups・norm_cer・lev_counts。句読点・空白・記号・全角半角は数えない)。
  機械の出力と人の行を時刻の重なりでまとめ、全部の行が校正済みのまとまりだけを数える。人が消した行 = 余分、人が足した行 = 抜け
- 作業データ(%LOCALAPPDATA%\\youtube-tools\\transcribe)は**読むだけ**。文字起こしの文書は書き換えない。
  結果は作業データの evals\\asr\\ に JSON で残す(文章を含むのでリポジトリには入れない。数字のまとめだけを docs/accuracy に書く)
- run はこのプロセスの中で faster-whisper を動かす(サーバーの外の道具なので、ネイティブの部品を読んでよい)。起動中のツールとは別に動く
"""
import argparse
import ctypes
import datetime
import hashlib
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TT = os.path.join(REPO, "transcribe-tool")
SCHEMA = "youtube-tools-asr-eval/v1"
BOOT = 1000          # ブートストラップの回数(文書を選び直して、CER のぶれの範囲を出す)
TAG_NAMES = {"overlap": "声が重なる", "bgm": "BGM・音が大きい", "none": "メモなし"}
LP_BINS = ((-1.0, "自信 低(< -1.0)"), (-0.5, "自信 中(-1.0〜-0.5)"), (99.0, "自信 高(≥ -0.5)"))


# ---------------------------------------------------------------- 準備

def load_serve(backend=None):
    """serve.py を読み込む。書き込みが本物の作業データの横にできないよう、serve 自身の DATA_DIR は一時フォルダにする
    (本物の作業データは、この道具が自分で読む)。"""
    os.environ.setdefault("YTT_CORE_DIR", REPO)
    os.environ["TRANSCRIBE_DATA_DIR"] = tempfile.mkdtemp(prefix="eval_asr_")
    if backend:
        os.environ["TRANSCRIBE_BACKEND"] = backend
    sys.path.insert(0, REPO)
    spec = importlib.util.spec_from_file_location("tx_serve_for_eval", os.path.join(TT, "serve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.IN_WORKER = True   # モデルはこのプロセスの中で読む(認識ワーカーを起動しない)
    mod.STUDIO_DATA = mod.studio_data_path()   # 配信ごとの文脈(--context auto)が、スタジオの配信のチャンネル名・コラボ相手を読めるように(起動時の処理を通らないため)
    return mod


def real_data_dir(arg=None):
    if arg:
        return os.path.abspath(arg)
    sys.path.insert(0, REPO)
    from ytt_core import datadir
    return datadir.tool_dir("transcribe", TT)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_docs(data, scope, only=None):
    """校正済みの行がある文書(scope: eval = 評価用 / train = 評価用以外 / all)。読むだけ"""
    tdir = os.path.join(data, "transcripts")
    out = []
    for name in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        if not re.fullmatch(r"[0-9a-f]{12}\.json", name):
            continue
        d = read_json(os.path.join(tdir, name))
        if not isinstance(d, dict):
            continue
        if only and d.get("id") not in only:
            continue
        ev = d.get("evalSet") is True
        if not only and scope != "all" and ev != (scope == "eval"):
            continue
        if not any(isinstance(g, dict) and g.get("proofed") for g in d.get("segments") or []):
            continue
        out.append(d)
    return out


def fingerprint(docs):
    """どの文書のどの版で測ったか(2つの結果が同じ正解で測ったものかを確かめる)"""
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda d: d.get("id", "")):
        h.update(("%s:%s;" % (d.get("id"), d.get("updatedAt"))).encode())
    return h.hexdigest()[:16]


def git_rev():
    try:
        rev = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--", "transcribe-tool"], capture_output=True, text=True, timeout=10).stdout.strip()
        return rev + ("+変更あり" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return ""


def peak_memory_mb():
    """このプロセスが使ったメモリの最大(MB)。分からなければ None"""
    try:
        if sys.platform.startswith("win"):
            class PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            k32 = ctypes.WinDLL("kernel32")
            psapi = ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return round(c.PeakWorkingSetSize / 1048576)
            return None
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / (1048576 if sys.platform == "darwin" else 1024))
    except Exception:
        return None


def name_terms(S, settings):
    """「名前が正しく出たか」を数える語: 用語集・置換辞書の「正」(画面の測定と同じ)+ 名簿の名前と呼び名(段1-1)"""
    terms = list(S.metric_terms(settings))
    r = S._roster.load(S.ROSTER)
    for n in r["people"]:
        m = r["members"].get(n)
        for x in [n] + (m["aliases"] if m else []):
            t = S.norm_cer(x)
            if len(t) >= 2 and t not in terms:
                terms.append(t)
    return terms


# ---------------------------------------------------------------- 採点(画面の doc_metrics と同じ規則。まとまりごとの内訳も残す)

def score_doc(S, doc, hyp, terms, flag_from="hyp"):
    """文書1件: 正解 = 校正済みの行、機械 = hyp(時刻は元の動画の秒)。まとまりの一覧を返す(数えないまとまりは入れない)。
    flag_from: 要確認の印を、機械の行(hyp。認識し直したとき)と人の行(ref。保存してある出力。original には印が無い)のどちらから読むか"""
    vdoc = dict(doc, original=hyp)
    orig, segs = S._prep(vdoc)
    proofed = [g for g in segs if g.get("proofed")]
    if not orig or not proofed:
        return []
    lo, hi = min(g["start"] for g in proofed), max(g["end"] for g in proofed)
    ok = lambda g: bool(g.get("proofed")) and "unclear" not in (g.get("tags") or [])
    out = []
    for go, ge in S._groups(orig, segs):
        if ge and not all(ok(segs[i]) for i in ge):
            continue
        if go and ge:
            kind = "both"
            a, b = min(segs[i]["start"] for i in ge), max(segs[i]["end"] for i in ge)
        elif go:
            kind = "machineOnly"
            a, b = min(orig[i]["start"] for i in go), max(orig[i]["end"] for i in go)
            if a < lo - 0.05 or b > hi + 0.05:
                continue
        else:
            kind = "humanOnly"
            a, b = min(segs[i]["start"] for i in ge), max(segs[i]["end"] for i in ge)
        raw_ref = S._norm(segs, ge) if ge else ""
        raw_hyp = S._norm(orig, go) if go else ""
        ref, hyp_n = S.norm_cer(raw_ref), S.norm_cer(raw_hyp)
        if not ref and not hyp_n:
            continue
        s, d, i = S.lev_counts(ref, hyp_n)
        tags = sorted({t for j in ge for t in (segs[j].get("tags") or []) if t in ("overlap", "bgm")})
        flag_rows = [orig[j] for j in go] if flag_from == "hyp" else [segs[j] for j in ge]
        flags = sorted({f for r in flag_rows for f in str(r.get("flag") or "").split("、") if f and f not in S.SPK_FLAGS})
        lps = [orig[j]["avg_logprob"] for j in go if isinstance(orig[j].get("avg_logprob"), (int, float))]
        th = sum(min(ref.count(t), hyp_n.count(t)) for t in terms)
        out.append({"doc": doc.get("id"), "start": round(a, 2), "end": round(b, 2), "kind": kind, "ref": raw_ref, "hyp": raw_hyp,
                    "refChars": len(ref), "sub": s, "del": d, "ins": i, "tags": tags, "flags": flags,
                    "lp": round(min(lps), 4) if lps else None,
                    "termRef": sum(ref.count(t) for t in terms), "termHit": th,
                    "termExtra": sum(max(0, hyp_n.count(t) - ref.count(t)) for t in terms)})
    return out


def total(groups):
    t = {"groups": len(groups), "refChars": 0, "sub": 0, "del": 0, "ins": 0, "termRef": 0, "termHit": 0, "termExtra": 0}
    for g in groups:
        for k in ("refChars", "sub", "del", "ins", "termRef", "termHit", "termExtra"):
            t[k] += g[k]
    t["errs"] = t["sub"] + t["del"] + t["ins"]
    t["cer"] = round(t["errs"] / t["refChars"], 4) if t["refChars"] else None
    t["termRate"] = round(t["termHit"] / t["termRef"], 4) if t["termRef"] else None
    return t


def boot_ci(groups, n=BOOT, seed=1):
    """文書を選び直して(重複あり)CER の 95% の範囲。文書が 2 本未満なら None"""
    by = {}
    for g in groups:
        by.setdefault(g["doc"], [0, 0])
        by[g["doc"]][0] += g["sub"] + g["del"] + g["ins"]
        by[g["doc"]][1] += g["refChars"]
    keys = sorted(by)
    if len(keys) < 2:
        return None
    rnd, vals = random.Random(seed), []
    for _ in range(n):
        e = r = 0
        for _k in keys:
            x = by[rnd.choice(keys)]
            e += x[0]
            r += x[1]
        if r:
            vals.append(e / r)
    vals.sort()
    return [round(vals[int(len(vals) * 0.025)], 4), round(vals[min(len(vals) - 1, int(len(vals) * 0.975))], 4)] if vals else None


def lp_bin(lp):
    if lp is None:
        return "自信 不明(記録なし)"
    for edge, name in LP_BINS:
        if lp < edge:
            return name
    return LP_BINS[-1][1]


def summarize(groups, docs):
    s = {"overall": total(groups), "ci95": boot_ci(groups)}
    s["byTag"] = {TAG_NAMES[k]: total([g for g in groups if ((k in g["tags"]) if k != "none" else not g["tags"])]) for k in ("overlap", "bgm", "none")}
    # 人が足した行(機械の行が無い = 抜け)は、印・自信の度合いを持たないので別の欄に(「印なし」「不明」に混ぜると、印の当たり方を読み違える)
    NO_HYP = "機械の行なし(抜け)"
    hyp = [g for g in groups if g["kind"] != "humanOnly"]
    s["byFlag"] = {"要確認の印あり": total([g for g in hyp if g["flags"]]), "印なし": total([g for g in hyp if not g["flags"]]),
                   NO_HYP: total([g for g in groups if g["kind"] == "humanOnly"])}
    s["byConfidence"] = {}
    for g in groups:
        s["byConfidence"].setdefault(NO_HYP if g["kind"] == "humanOnly" else lp_bin(g["lp"]), []).append(g)
    s["byConfidence"] = {k: total(v) for k, v in sorted(s["byConfidence"].items())}
    s["byKind"] = {"両方にある": total([g for g in groups if g["kind"] == "both"]), "人が消した(余分)": total([g for g in groups if g["kind"] == "machineOnly"]),
                   "人が足した(抜け)": total([g for g in groups if g["kind"] == "humanOnly"])}
    titles = {d["id"]: str(d.get("title") or "")[:40] for d in docs}
    s["byDoc"] = [dict(total([g for g in groups if g["doc"] == i]), id=i, title=titles.get(i, "")) for i in sorted({g["doc"] for g in groups})]
    return s


# ---------------------------------------------------------------- 認識し直す

def recognize_doc(S, doc, spec, data):
    """文書の範囲の音声を認識し直して、機械の行(元の動画の秒・印・自信の度合いつき)を返す。-> (行, 音声の秒, かかった秒, 音声の出どころ)"""
    src = str(doc.get("sourcePath") or "")
    start, end = S.num(doc.get("start"), 0.0) or 0.0, S.num(doc.get("end"))
    full = os.path.join(data, "dataset", "docs", doc["id"], "full.flac")
    if src and os.path.isfile(src):
        a_spec, offset, where = {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, start, "動画"
    elif os.path.isfile(full):   # 保管データの全体の音声(文書の範囲の先頭 = 0 秒)
        a_spec, offset, where = {"sourcePath": full, "start": 0.0, "end": None, "boost": spec["boost"]}, start, "保管の音声"
    else:
        raise RuntimeError("音声が見つかりません(元の動画も保管データの full.flac も無い)")
    job = {"cancel": False, "proc": None, "phase": "", "state": "", "device": "", "progress": 0.0}
    tmp = tempfile.mkdtemp(prefix="eval_asr_wav_")
    wav = os.path.join(tmp, "a.wav")
    try:
        S.extract_audio(job, a_spec, wav)
        audio_sec = S.media_duration(wav) or 0.0
        t0 = time.monotonic()
        gen = S.transcribe_fake(job, spec, wav, audio_sec) if S.backend_name() == "fake" else S.transcribe_real(job, spec, wav, audio_sec)
        rows, prev = [], []
        for s in S.expand_segments(gen, spec):   # 文字起こしのジョブ(run_job)と同じ整え方
            if not s["text"]:
                continue
            row = {"start": round(s["start"] + offset, 2), "end": round(s["end"] + offset, 2), "text": s["text"][:S.MAX_TEXT], **S.machine_conf(s)}
            row["flag"] = S.make_flags({**s, "text": row["text"], "start": row["start"], "end": row["end"]}, prev, spec["language"], S.prompt_terms(spec))
            prev.append(row["text"])
            rows.append(row)
        return rows, audio_sec, time.monotonic() - t0, where, job.get("device", "")
    finally:
        try:
            for n in os.listdir(tmp):
                os.unlink(os.path.join(tmp, n))
            os.rmdir(tmp)
        except OSError:
            pass


def run_spec(S, args, settings):
    st = settings or {}
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", args.glossary if args.glossary is not None else str(st.get("glossary") or "")) if t.strip()]
    beam = args.beam if args.beam else (1 if st.get("quality") == "fast" else 5)
    return {"model": args.model or st.get("model") or "large-v3", "language": "ja", "beam": beam,
            "vadMode": args.vad or (st.get("vadMode") if st.get("vadMode") in ("weak", "normal", "off") else "normal"),
            "boost": (st.get("boost") is True) if args.boost is None else args.boost == "on",
            "wordSplit": st.get("wordSplit") is not False, "splitChars": S.split_chars_for({}, st),
            "stripPunct": st.get("stripPunct") is not False, "glossary": glossary, "device": args.device, "temp0": bool(args.temp0)}


# ---------------------------------------------------------------- 表示

def pct(x):
    return "   —  " if x is None else "%5.1f%%" % (x * 100)


def print_summary(res):
    s, m = res["summary"], res["meta"]
    o = s["overall"]
    print("\n== %s  %s ==" % (m["mode"], m.get("label") or ""))
    if m["mode"] == "run":
        e = m["engine"]
        print("エンジン %s %s / モデル %s / 機器 %s / 設定 %s" % (e["engine"], e["engineVersion"], e["model"], e.get("device"), json.dumps(e["settings"], ensure_ascii=False)))
        print("音声 %.0f 秒 / 認識 %.0f 秒(実時間の %.2f 倍)/ モデルの読み込み %.0f 秒 / メモリの最大 %s MB"
              % (m["audioSec"], m["wallSec"], m["wallSec"] / m["audioSec"] if m["audioSec"] else 0, m.get("loadSec") or 0, m.get("peakMemMB")))
    print("文書 %d 本・正解 %d 字・まとまり %d" % (len(s["byDoc"]), o["refChars"], o["groups"]))
    ci = s.get("ci95")
    print("CER %s(95%%の範囲 %s)  置換 %d / 抜け %d / 余分 %d" % (pct(o["cer"]), "%s〜%s" % (pct(ci[0]).strip(), pct(ci[1]).strip()) if ci else "—", o["sub"], o["del"], o["ins"]))
    if o["termRef"]:
        print("名前・用語の再現率 %s(%d/%d)・正解に無いのに出た %d" % (pct(o["termRate"]), o["termHit"], o["termRef"], o["termExtra"]))
    for title, key in (("条件(人の行のメモ)", "byTag"), ("要確認の印", "byFlag"), ("自信の度合い(機械の行の avg_logprob の最小)", "byConfidence"), ("まとまりの種類", "byKind")):
        print("  [%s]" % title)
        for k, v in s[key].items():
            if v["groups"]:
                print("    %-22s CER %s  字 %5d  置換 %3d 抜け %3d 余分 %3d" % (k, pct(v["cer"]), v["refChars"], v["sub"], v["del"], v["ins"]))
    print("  [文書ごと]")
    for d in sorted(s["byDoc"], key=lambda d: -(d["cer"] or 0)):
        print("    %s %s  字 %5d  %s" % (d["id"], pct(d["cer"]), d["refChars"], d["title"]))


# ---------------------------------------------------------------- コマンド

def out_dir(data):
    d = os.path.join(data, "evals", "asr")
    os.makedirs(d, exist_ok=True)
    return d


def save(res, data):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = re.sub(r"[^\w.-]+", "_", res["meta"].get("label") or res["meta"]["mode"])[:40]
    path = os.path.join(out_dir(data), "%s_%s.json" % (stamp, label))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def base_meta(mode, args, docs, data):
    return {"schema": SCHEMA, "mode": mode, "label": args.label or "", "at": int(time.time() * 1000), "git": git_rev(),
            "scope": args.scope if not args.docs else "docs", "docs": [d["id"] for d in docs], "dataFingerprint": fingerprint(docs), "dataDir": data}


def cmd_stored(S, args, data):
    settings = read_json(os.path.join(data, "settings.json"), {}) or {}
    docs = load_docs(data, args.scope, args.docs)
    terms = name_terms(S, settings)
    groups, mismatch = [], []
    for d in docs:
        mine = score_doc(S, d, d.get("original") or [], terms, flag_from="ref")
        groups += mine
        ref = S.doc_metrics(d, False, terms)   # 画面の「認識精度の測定」と同じ数になるか(規則を二重に持っているので、ずれたら知らせる)
        t = total(mine)
        want = (ref["sub"], ref["del"], ref["ins"], ref["refChars"]) if ref else (0, 0, 0, 0)
        if want != (t["sub"], t["del"], t["ins"], t["refChars"]):
            mismatch.append(d["id"])
    if mismatch:
        print("注意: 画面の測定と数が合わない文書があります(この道具の採点の規則を直す必要があります): " + ", ".join(mismatch))
    res = {"meta": base_meta("stored", args, docs, data), "summary": summarize(groups, docs), "groups": groups, "terms": terms}
    res["meta"]["mismatch"] = mismatch
    return res


def cmd_run(S, args, data):
    settings = read_json(os.path.join(data, "settings.json"), {}) or {}
    docs = load_docs(data, args.scope, args.docs)
    if not docs:
        raise SystemExit("測れる文書がありません(校正済みの行がある%s)" % ("評価用の文書" if args.scope == "eval" else "文書"))
    spec = run_spec(S, args, settings)
    terms = name_terms(S, settings)
    load_sec, device = 0.0, ""
    if S.backend_name() != "fake":
        if not S.has_faster_whisper():
            raise SystemExit("faster-whisper が入っていません")
        t0 = time.monotonic()
        _m, device = S.load_model(spec["model"], {"phase": "", "cancel": False}, spec["device"])
        load_sec = time.monotonic() - t0
    groups, audio_sec, wall_sec, per_doc = [], 0.0, 0.0, []
    for n, d in enumerate(docs, 1):
        print("(%d/%d) %s %s …" % (n, len(docs), d["id"], str(d.get("title") or "")[:30]), flush=True)
        ctx = S.stream_context(d, args.context == "auto")   # 配信ごとの文脈(段1-2。文書の題名・チャンネル名・コラボ相手・話者の名前から)
        if ctx["members"]:
            print("   文脈: %s" % "、".join(m["name"] for m in ctx["members"]))
        try:
            rows, a, w, where, dev = recognize_doc(S, d, dict(spec, context=ctx), data)
        except Exception as e:
            print("   とばしました: %s" % str(e)[:200])
            per_doc.append({"id": d["id"], "error": str(e)[:200]})
            continue
        device = dev or device
        audio_sec += a
        wall_sec += w
        per_doc.append({"id": d["id"], "audioSec": round(a, 2), "wallSec": round(w, 2), "audio": where, "rows": len(rows),
                        "context": [m["name"] for m in ctx["members"]]})
        groups += score_doc(S, d, rows, terms, flag_from="hyp")
    failed = [p for p in per_doc if p.get("error")]
    meta = base_meta("run", args, docs, data)
    meta.update({"engine": {"engine": "fake" if S.backend_name() == "fake" else "faster-whisper",
                            "engineVersion": "" if S.backend_name() == "fake" else S.pkg_version("faster-whisper"),
                            "model": spec["model"], "device": device,
                            "settings": {k: spec[k] for k in ("language", "beam", "vadMode", "boost", "wordSplit", "splitChars", "stripPunct", "temp0")},
                            "glossary": spec["glossary"][:50], "context": args.context},
                 "audioSec": round(audio_sec, 2), "wallSec": round(wall_sec, 2), "loadSec": round(load_sec, 2), "peakMemMB": peak_memory_mb(),
                 "perDoc": per_doc, "failed": len(failed)})
    if failed:
        print("注意: %d 本は認識できず、数に入っていません(比べるときは同じ文書で比べること)" % len(failed))
    return {"meta": meta, "summary": summarize(groups, docs), "groups": groups, "terms": terms}


def cmd_compare(a_path, b_path, n=BOOT, seed=1):
    """同じ文書どうしで CER の差(B − A)と、文書を選び直した 95% の範囲。-> 結果の dict(表示もする)"""
    A, B = read_json(a_path), read_json(b_path)
    if not A or not B:
        raise SystemExit("結果のファイルを読めません")
    warn = []
    if A["meta"].get("dataFingerprint") != B["meta"].get("dataFingerprint"):
        warn.append("2つの結果は、正解のデータ(文書・版)が違います。同じ文書だけで比べます")
    per = {}
    for side, R in (("a", A), ("b", B)):
        for g in R["groups"]:
            x = per.setdefault(g["doc"], {"a": [0, 0], "b": [0, 0]})[side]
            x[0] += g["sub"] + g["del"] + g["ins"]
            x[1] += g["refChars"]
    keys = sorted(k for k, v in per.items() if v["a"][1] and v["b"][1])
    if not keys:
        raise SystemExit("共通の文書がありません")

    def cer(side, ks):
        e = sum(per[k][side][0] for k in ks)
        r = sum(per[k][side][1] for k in ks)
        return e / r if r else 0.0
    diff = cer("b", keys) - cer("a", keys)
    rnd, vals = random.Random(seed), []
    for _ in range(n):
        ks = [rnd.choice(keys) for _k in keys]
        vals.append(cer("b", ks) - cer("a", ks))
    vals.sort()
    lo, hi = vals[int(len(vals) * 0.025)], vals[min(len(vals) - 1, int(len(vals) * 0.975))]
    if hi < 0:
        verdict = "B の方が良い(差の範囲がすべて 0 より下)"
    elif lo > 0:
        verdict = "B の方が悪い(差の範囲がすべて 0 より上)"
    else:
        verdict = "差があるとは言えない(範囲が 0 をまたぐ。文書を増やすと分かることがある)"
    out = {"a": a_path, "b": b_path, "docs": len(keys), "cerA": round(cer("a", keys), 4), "cerB": round(cer("b", keys), 4),
           "diff": round(diff, 4), "ci95": [round(lo, 4), round(hi, 4)], "verdict": verdict, "warnings": warn,
           "byDoc": [{"id": k, "cerA": round(cer("a", [k]), 4), "cerB": round(cer("b", [k]), 4)} for k in keys]}
    for w in warn:
        print("注意: " + w)
    print("A %s: CER %s\nB %s: CER %s" % (os.path.basename(a_path), pct(out["cerA"]), os.path.basename(b_path), pct(out["cerB"])))
    print("差(B − A) %+.2f ポイント(95%%の範囲 %+.2f 〜 %+.2f)→ %s" % (diff * 100, lo * 100, hi * 100, verdict))
    for key in ("byTag", "byKind"):
        for k in A["summary"][key]:
            va, vb = A["summary"][key][k], B["summary"][key].get(k) or {}
            if va.get("groups") or vb.get("groups"):
                print("  %-22s A %s → B %s" % (k, pct(va.get("cer")), pct(vb.get("cer"))))
    for d in out["byDoc"]:
        if abs(d["cerB"] - d["cerA"]) >= 0.005:
            print("  %s  A %s → B %s" % (d["id"], pct(d["cerA"]), pct(d["cerB"])))
    return out


def cmd_list(data):
    d = os.path.join(data, "evals", "asr")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        r = read_json(os.path.join(d, name))
        if not r or r.get("meta", {}).get("schema") != SCHEMA:
            continue
        m, o = r["meta"], r["summary"]["overall"]
        e = m.get("engine") or {}
        print("%s  %-6s CER %s  字 %5d  %s %s" % (name, m["mode"], pct(o["cer"]), o["refChars"], e.get("model", ""), m.get("label", "")))


def main(argv=None):
    p = argparse.ArgumentParser(description="文字起こしの精度を評価用の校正済みデータで測る(作業データは読むだけ)")
    p.add_argument("mode", choices=("stored", "run", "compare", "list"))
    p.add_argument("files", nargs="*", help="compare の2つの結果")
    p.add_argument("--data", help="文字起こしの作業データのフォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools\\transcribe)")
    p.add_argument("--scope", choices=("eval", "train", "all"), default="eval", help="eval = 評価用(既定)/ train = 評価用以外 / all")
    p.add_argument("--docs", help="文書の id をカンマ区切りで(scope より優先)")
    p.add_argument("--label", help="結果に付ける名前")
    p.add_argument("--model")
    p.add_argument("--vad", choices=("weak", "normal", "off"))
    p.add_argument("--beam", type=int)
    p.add_argument("--boost", choices=("on", "off"))
    p.add_argument("--glossary", help="認識のヒントに渡す語(、か改行区切り)。指定しなければ設定の用語集")
    p.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    p.add_argument("--context", choices=("none", "auto"), default="none", help="配信ごとの文脈(出る人の名前と呼び名)を渡すか(既定 none = 基準)")
    p.add_argument("--temp0", action="store_true", help="温度 0 に固定する(回ごとのぶれを抑える)")
    p.add_argument("--no-save", action="store_true", help="結果を保存しない")
    args = p.parse_args(argv)
    args.docs = [x.strip() for x in args.docs.split(",") if x.strip()] if args.docs else None
    if args.mode == "compare":
        if len(args.files) != 2:
            raise SystemExit("compare には結果のファイルを2つ指定してください")
        return cmd_compare(*args.files)
    data = real_data_dir(args.data)
    if args.mode == "list":
        return cmd_list(data)
    S = load_serve()
    res = cmd_stored(S, args, data) if args.mode == "stored" else cmd_run(S, args, data)
    print_summary(res)
    if not args.no_save:
        print("\n保存: " + save(res, data))
    return res


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    main()
