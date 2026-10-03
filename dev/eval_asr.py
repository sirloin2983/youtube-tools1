#!/usr/bin/env python3
"""文字起こしの精度を、校正済みの文字起こし(評価用)で測る道具(文字起こしの改善の計画 段0-2。docs/plan/transcription-overhaul-plan.md)。

    python dev/eval_asr.py stored  [--scope eval|train|all] [--label 名前]
        保存してある機械の出力(original)と、人が直した行を比べる(認識はしない。今の基準)
    python dev/eval_asr.py run     [--model large-v3] [--vad normal] [--beam 5] [--glossary "トワ、スバル"] [--context none|auto] [--temp0] [--scope eval] [--label 名前]
        評価用の音声を、指定のモデル・設定で認識し直して比べる(指定しない項目は、文字起こしの今の設定 settings.json のまま)。
        --context auto = 配信ごとの文脈(出る人の名前と呼び名。計画 段1-2)を文書ごとに作って渡す(既定 none = 渡さない = 基準)。
        --temp0 = 温度 0 に固定(雑音の多い音声で回ごとに結果が変わるのを抑える。比べるときは両方に付ける)
    python dev/eval_asr.py compare 結果A.json 結果B.json
        2つの結果を、同じ文書どうしで比べる(差と 95% の範囲。範囲が 0 をまたげば「差があるとは言えない」)
    python dev/eval_asr.py list
        今までの結果の一覧

  どのモードでも(マスタープラン Q3。docs/plan/master-plan-2026-10.md の 2 の原則 4・8 のリスク):
    --source eval|daily|all|friend   測る文書の出どころ。eval = 評価用(既定。今までどおり)/ daily = 普段の校正済みの文書(評価用以外)/
                                     friend = 友人の送る用 zip(dev/eval_import.py で eval-intake/works/ に取り込んだもの。--intake で場所を変える)/
                                     all = 評価用 + 普段 + 友人。--scope(eval|train|all。all = 自分の文書だけ)は今までどおり使える
    --since YYYY-MM-DD --until YYYY-MM-DD   時期で分ける(その日を含む)。文書の時刻 = 校正済みの行の proofedAt(初めて校正済みにした時刻)の最大。
                                     無い文書は updatedAt(友人の zip は書き出した時刻)。どちらも無い文書は、時期を指定したときは数えない
    --group-by engine|model          文書ごとの下書きのエンジン・設定・辞書の版(recognition.runs)で分けて集計する(途中で変わった前後を混ぜない)。
                                     engine = エンジン・モデル・版・beam・VAD・ヒント・辞書の版まで / model = エンジン・モデル・版だけ。途中で変わった文書は「混在」の組
  普段の文書・友人の zip を run で認識し直すときは、用語のヒント・辞書を使わない(評価用と同じ条件。--glossary・--context auto を自分で付けたときだけ渡す)。
  普段のデータは「下書きを作ったエンジン」に甘く出る(人は迷うと下書きを直さずに通す)ので、結果に下書きのエンジンを出し、比べるエンジンと同じなら注意する。
  校正済みが 15 分に届かないときは「まだ少ない(参考)」

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
TT = os.path.join(REPO, "editor")
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from ytt_core import evaldata as ev  # noqa: E402  友人の送る用 zip の形と規則(記号 [?]・[笑]・作業ID)
SCHEMA = "youtube-tools-asr-eval/v1"
BOOT = 1000          # ブートストラップの回数(文書を選び直して、CER のぶれの範囲を出す)
LOW_DATA_SEC = 15 * 60   # 校正済みがこれに届かなければ「まだ少ない(参考)」(マスタープラン Q4: 定点は 15 分前後)
STORED = "stored"        # summarize の compared: 保存してある機械の出力(= 下書きそのもの)を測るとき
DRAFT_NONE = "不明(記録なし)"
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


# ---------------------------------------------------------------- 出どころ(評価用・普段・友人)・時期・下書きのエンジン

SCOPE_SOURCE = {"eval": "eval", "train": "daily", "all": "own"}          # 古い --scope -> 出どころ(own = 評価用 + 普段。友人は入れない = 今までの all)
SOURCE_SCOPE = {"eval": "eval", "daily": "train", "own": "all", "all": "all", "friend": "friend"}   # 出どころ -> 結果の meta.scope(古い値のまま)


def resolve_source(args):
    return getattr(args, "source", None) or SCOPE_SOURCE[args.scope]


def default_intake():
    """友人の zip の取り込み先(dev/eval_import.py と同じ場所)"""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import eval_import
    return eval_import.default_dest()


def _iso_ms(text):
    """ISO 8601 の時刻の文字(+0900 でも +09:00 でも)-> ミリ秒。読めなければ None"""
    s = str(text or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.datetime.strptime(s, fmt).timestamp() * 1000)
        except ValueError:
            pass
    try:
        return int(datetime.datetime.fromisoformat(s).timestamp() * 1000)
    except ValueError:
        return None


def load_friend_docs(intake, only=None):
    """友人の送る用 zip(dev/eval_import.py が eval-intake/works/<作業ID>/ に展開したもの。形は ytt_core/evaldata.py)を、
    文字起こしの文書と同じ形にして返す(読むだけ)-> (文書の一覧, 数えなかった作業 [{"id", "why"}])。
    正解 = final.json の確認済みの行のうち check.json(無ければ evaldata.judge)が使える行だけ。形式違いの記号の行・未確認の行は校正済みにしない。
    [?] の行と [笑] だけの行は「聞き取れない」(unclear)にして数えない。[笑] は取り除く。機械の出力 = asr_raw.json の行。作業ごと外れたものは数えない。
    音声 = audio.flac(run で認識し直せる)"""
    works = os.path.join(intake or "", "works")
    docs, skipped = [], []
    for wid in sorted(os.listdir(works)) if os.path.isdir(works) else []:
        if not ev.WORK_ID.match(wid) or (only and wid not in only):
            continue
        base = os.path.join(works, wid)
        final, raw = read_json(os.path.join(base, "final.json")), read_json(os.path.join(base, "asr_raw.json"))
        meta, check = read_json(os.path.join(base, "meta.json"), {}) or {}, read_json(os.path.join(base, "check.json"), {}) or {}
        if not isinstance(final, dict) or not isinstance(raw, dict) or not isinstance(final.get("rows"), list):
            skipped.append({"id": wid, "why": "final.json・asr_raw.json を読めない"})
            continue
        judged = check.get("judge") if isinstance(check.get("judge"), dict) and isinstance(check["judge"].get("rows"), list) else None
        if judged is None:
            try:
                judged = ev.judge(final, raw)
            except (TypeError, ValueError, AttributeError, KeyError) as e:
                skipped.append({"id": wid, "why": "判定できない: %s" % e})
                continue
        if (judged.get("work") or {}).get("use") is False:
            skipped.append({"id": wid, "why": "作業ごと外れている(" + "・".join((judged["work"].get("reasons") or [])[:2]) + ")"})
            continue
        use = {str(c.get("id")): c.get("use") is True for c in judged["rows"] if isinstance(c, dict)}
        segs, names = [], []
        for r in final["rows"]:
            if not isinstance(r, dict):
                continue
            try:
                a, b = float(r["start"]), float(r["end"])
            except (TypeError, ValueError, KeyError):
                continue
            if b < a:
                continue
            text, rid = str(r.get("text") or ""), str(r.get("id") or "")
            tags = [t for t in (r.get("tags") or []) if isinstance(t, str)]
            plain = ev.strip_marks(text)
            if ev.MARK_UNSURE in text or not plain:   # 聞き取れない行・[笑] だけの行は、文字の正しさを測れない
                tags.append("unclear")
            g = {"id": rid or "s%d" % (len(segs) + 1), "start": a, "end": b, "text": plain, "speaker": str(r.get("speaker") or ""), "tags": tags}
            if r.get("checked") is True and use.get(rid):
                g["proofed"] = True
            if g["speaker"] and g["speaker"] not in names:
                names.append(g["speaker"])
            segs.append(g)
        if not any(g.get("proofed") for g in segs):
            continue
        orig = [{k: v for k, v in o.items() if k != "words"} for o in raw.get("segments") or [] if isinstance(o, dict)]
        run = raw.get("run") if isinstance(raw.get("run"), dict) else {}
        audio = os.path.join(base, "audio.flac")
        at, kind = _iso_ms(meta.get("exportedAt")), "exportedAt"
        if at is None:
            at, kind = _iso_ms(check.get("checkedAt")), "checkedAt"
        title = ("%s %s" % (meta.get("streamer") or "", meta.get("sourceName") or "")).strip() or wid
        docs.append({"schema": "transcribe/v1", "id": wid, "title": title, "sourcePath": audio if os.path.isfile(audio) else "", "start": 0, "end": None,
                     "language": "ja", "speakers": [{"id": n, "name": n} for n in names], "segments": segs, "original": orig,
                     "recognition": {"runs": [run]} if run else {}, "updatedAt": str(check.get("sha256") or "")[:12],
                     "_source": "friend", "_basisAt": at, "_basisKind": kind if at is not None else ""})
    return docs, skipped


def doc_time(d):
    """文書の時期の基準の時刻 -> (ミリ秒, 何から決めたか)。校正済みの行の proofedAt の最大 → 無ければ updatedAt。
    友人の zip は書き出した時刻(exportedAt。無ければ取り込みチェックの時刻)。どれも無ければ (None, "")。
    proofedAt は初めて校正済みにした時刻(ed_store.sanitize_transcript)。それより前に校正した行は時刻が無い(= 分からない)ので数えない"""
    if d.get("_source") == "friend":
        return d.get("_basisAt"), d.get("_basisKind") or ""
    ats = [g["proofedAt"] for g in d.get("segments") or []
           if isinstance(g, dict) and g.get("proofed") and isinstance(g.get("proofedAt"), (int, float)) and not isinstance(g.get("proofedAt"), bool) and g["proofedAt"] > 0]
    if ats:
        return int(max(ats)), "proofedAt"
    ua = d.get("updatedAt")
    if isinstance(ua, (int, float)) and not isinstance(ua, bool) and ua > 0:
        return int(ua), "updatedAt"
    return None, ""


def parse_day(text, end=False):
    """YYYY-MM-DD(この PC の時刻の日付)-> ミリ秒。end なら、その日の終わり(その日を含む)"""
    try:
        day = datetime.datetime.strptime(str(text).strip(), "%Y-%m-%d")
    except ValueError:
        raise SystemExit("日付は YYYY-MM-DD で指定してください: %r" % text)
    if end:
        day += datetime.timedelta(days=1)
    return int(day.timestamp() * 1000) - (1 if end else 0)


def select_docs(data, args, intake=None):
    """測る文書を選ぶ(--source・--docs・--since・--until)-> (文書の一覧, 選び方の記録)。読むだけ。各文書に "_source"(eval・daily・friend)を付ける"""
    src, only = resolve_source(args), args.docs
    sel = {"source": src, "since": getattr(args, "since", None) or "", "until": getattr(args, "until", None) or "",
           "excludedByTime": 0, "unknownTime": 0, "friendSkipped": [], "intake": ""}
    own_scope = None if src == "friend" else SOURCE_SCOPE[src]
    docs = load_docs(data, "all" if only else own_scope, only) if (only or own_scope) else []
    for d in docs:
        d["_source"] = "eval" if d.get("evalSet") is True else "daily"
    if only or src in ("friend", "all"):
        sel["intake"] = intake or getattr(args, "intake", None) or default_intake()
        friend, sel["friendSkipped"] = load_friend_docs(sel["intake"], only)
        docs += friend
    lo = parse_day(args.since) if getattr(args, "since", None) else None
    hi = parse_day(args.until, end=True) if getattr(args, "until", None) else None
    if lo is not None or hi is not None:
        keep = []
        for d in docs:
            t, _basis = doc_time(d)
            if t is None:
                sel["unknownTime"] += 1
            elif (lo is not None and t < lo) or (hi is not None and t > hi):
                sel["excludedByTime"] += 1
            else:
                keep.append(d)
        docs = keep
    return docs, sel


def runs_of(d):
    rec = d.get("recognition") if isinstance(d.get("recognition"), dict) else {}
    return [r for r in rec.get("runs") or [] if isinstance(r, dict)]


def draft_run(d):
    """下書き(人が直す前の機械の出力)を作った認識の記録: recognition.runs の最初の認識。再認識の記録(kind がある)ではない最初のものを選ぶ(無ければ最初の記録)"""
    rs = runs_of(d)
    r = next((x for x in rs if not x.get("kind")), rs[0] if rs else None)
    return r if r and (r.get("engine") or r.get("model")) else None


def draft_of(d):
    """下書きを作ったエンジン -> {"engine", "model", "engineVersion"} か None"""
    r = draft_run(d)
    if not r:
        return None
    return {"engine": str(r.get("engine") or ""), "model": str(r.get("model") or ""), "engineVersion": str(r.get("engineVersion") or "")}


def _settings_of(r):
    st = r.get("settings") if isinstance(r.get("settings"), dict) else r.get("params")
    return st if isinstance(st, dict) else {}


def run_label(r, detail="model"):
    """認識の記録 1 件の見出し。detail = model(エンジン・モデル・版)/ engine(+ beam・VAD・ヒント・辞書の版)"""
    eng, model, ver = str(r.get("engine") or ""), str(r.get("model") or ""), str(r.get("engineVersion") or "")
    s = " ".join(x for x in (eng, model) if x) or DRAFT_NONE
    if ver:
        s += " v" + ver
    if detail == "engine":
        st = _settings_of(r)
        parts = ["beam%s" % st["beam"]] if st.get("beam") is not None else []
        if st.get("vadMode"):
            parts.append("vad:%s" % st["vadMode"])
        if "boost" in st:
            parts.append("boost:%s" % ("on" if st["boost"] else "off"))
        hint = bool(st.get("glossaryChars") or st.get("promptChars") or st.get("context") or st.get("autoDict"))
        dv = st.get("dict") if isinstance(st.get("dict"), dict) else {}
        s += " %s ヒント:%s 辞書:%s" % (" ".join(parts), "あり" if hint else "なし", ",".join("%s=%s" % (k, dv[k]) for k in sorted(dv)) or "-")
        s = s.replace("  ", " ")
    return s


def engine_key(d, detail="model"):
    """文書の「エンジン・設定・辞書の版」の組(--group-by)。記録が無ければ「不明」、途中で変わった(別のエンジン・設定で認識し直した)文書は「混在」の組"""
    ks = sorted({run_label(r, detail) for r in runs_of(d)})
    return DRAFT_NONE if not ks else ks[0] if len(ks) == 1 else "混在: " + " + ".join(ks)


def source_of(d):
    return d.get("_source") or ("eval" if d.get("evalSet") is True else "daily")


def draft_bias(d, compared):
    """普段・友人のデータは、下書きを作ったエンジンに甘く出る(計画 8)。注意の文(無ければ "")。
    compared = STORED(保存してある出力を測る = 下書きそのもの)か、比べるエンジンの {"engine", "model"}。評価用の文書は丁寧に校正したので注意しない"""
    if source_of(d) == "eval":
        return ""
    if compared == STORED:
        return "保存した機械の出力 = 下書きそのもの(人が直さず通した行は必ず合う)"
    dr = draft_of(d)
    if dr and dr["engine"] == compared.get("engine"):
        return "下書きを作ったエンジンと同じ(%s)" % ("モデルも同じ" if dr["model"] == compared.get("model") else "モデルは違う")
    return ""


def doc_info(d, compared=STORED, detail="engine"):
    """文書ごとの記録(結果の byDoc に入れる): 出どころ・時期・下書きのエンジン・認識の記録(エンジン・設定・辞書の版)・注意"""
    t, basis = doc_time(d)
    dr = draft_of(d)
    runs = []
    for r in runs_of(d)[:30]:
        st = _settings_of(r)
        runs.append({"kind": r.get("kind") or "", "engine": r.get("engine") or "", "model": r.get("model") or "", "engineVersion": r.get("engineVersion") or "",
                     "at": r.get("at"), "settings": {k: st[k] for k in ("beam", "vadMode", "boost", "wordSplit", "glossaryChars", "promptChars", "autoDict", "dict") if k in st}})
    return {"source": source_of(d), "timeAt": t, "timeBasis": basis,
            "draft": run_label(dr) if dr else DRAFT_NONE, "engineKey": engine_key(d, detail), "runs": runs, "draftBias": draft_bias(d, compared)}


def proofed_sec(groups):
    """数えた校正済みの長さ(秒): 人の行があるまとまり(両方にある・人が足した)の時刻の幅の合計"""
    return round(sum(max(0.0, g["end"] - g["start"]) for g in groups if g["kind"] in ("both", "humanOnly")), 1)


def fingerprint(docs):
    """どの文書のどの版で測ったか(2つの結果が同じ正解で測ったものかを確かめる)"""
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda d: d.get("id", "")):
        h.update(("%s:%s;" % (d.get("id"), d.get("updatedAt"))).encode())
    return h.hexdigest()[:16]


def git_rev():
    try:
        rev = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--", "editor"], capture_output=True, text=True, timeout=10).stdout.strip()
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


def doc_text(S, groups):
    """時刻によらない数え方: 文書ごとに、数えたまとまりの正解と機械の文字を時刻の順に通しでつないで比べる。
    行の時刻が目安のエンジン(Qwen3-ASR。段2-3)は、まとまりごとの数え方だと文字が隣のまとまりへずれて抜けと余分が二重に出るので、文字の正しさはこちらで比べる"""
    t = {"refChars": 0, "sub": 0, "del": 0, "ins": 0}
    by = {}
    for g in groups:
        by.setdefault(g["doc"], []).append(g)
    for gs in by.values():
        gs = sorted(gs, key=lambda g: g["start"])
        ref, hyp = S.norm_cer("".join(g["ref"] for g in gs)), S.norm_cer("".join(g["hyp"] for g in gs))
        a, b, c = S.lev_counts(ref, hyp)
        t["refChars"] += len(ref)
        t["sub"], t["del"], t["ins"] = t["sub"] + a, t["del"] + b, t["ins"] + c
    t["cer"] = round((t["sub"] + t["del"] + t["ins"]) / t["refChars"], 4) if t["refChars"] else None
    return t


def summarize(groups, docs, S=None, compared=STORED, group=None):
    """結果のまとめ。compared = 比べるエンジン(STORED = 保存してある出力)。下書きのエンジンとの注意(draftBias)に使う。
    group = (見出し, 文書 -> 組の名前)。--group-by のとき、組ごとの集計 byGroup を足す"""
    s = {"overall": total(groups), "ci95": boot_ci(groups)}
    s["proofedSec"] = proofed_sec(groups)
    s["lowData"] = s["proofedSec"] < LOW_DATA_SEC   # 校正済みが少ない間は「まだ少ない(参考)」(結果は出すが、決めるのに使わない)
    if S is not None:
        s["docText"] = doc_text(S, groups)
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
    info = {d["id"]: doc_info(d, compared) for d in docs}
    s["byDoc"] = [dict(total([g for g in groups if g["doc"] == i]), id=i, title=titles.get(i, ""), **info.get(i, {})) for i in sorted({g["doc"] for g in groups})]
    s["compared"] = compared
    # 下書きのエンジンごと(普段のデータは下書きを作ったエンジンに甘い。計画 8)と、注意が要る文書
    s["byDraft"] = {}
    for d in s["byDoc"]:
        s["byDraft"].setdefault(d.get("draft", DRAFT_NONE), []).append(d["id"])
    s["byDraft"] = {k: dict(total([g for g in groups if g["doc"] in set(v)]), docs=len(v)) for k, v in sorted(s["byDraft"].items())}
    s["draftBias"] = [{"id": d["id"], "note": d["draftBias"]} for d in s["byDoc"] if d.get("draftBias")]
    if group:
        s["groupBy"], key_of = group
        keys = {d["id"]: key_of(d) for d in docs}
        by = {}
        for g in groups:
            by.setdefault(keys.get(g["doc"], DRAFT_NONE), []).append(g)
        s["byGroup"] = {}
        for k, v in sorted(by.items()):
            t = dict(total(v), docs=len({g["doc"] for g in v}), proofedSec=proofed_sec(v), ci95=boot_ci(v))
            t["lowData"] = t["proofedSec"] < LOW_DATA_SEC
            s["byGroup"][k] = t
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


def run_spec(S, args, settings, hint_free=False):
    """hint_free = 評価用以外(普段・友人)の文書を含むとき: 用語集を渡さない(--glossary を自分で付けたときだけ渡す)。辞書(置換・学習)は常に使わない"""
    st = settings or {}
    raw_glossary = args.glossary if args.glossary is not None else ("" if hint_free else str(st.get("glossary") or ""))
    glossary = [t.strip() for t in re.split(r"[\r\n,、]+", raw_glossary) if t.strip()]
    beam = args.beam if args.beam else (1 if st.get("quality") == "fast" else 5)
    model = args.model or st.get("model") or "large-v3"
    eng = S.tx_engines.get(args.engine)
    if not args.model and not eng.valid_model(model) and getattr(eng, "DEFAULT_MODEL", ""):
        model = eng.DEFAULT_MODEL   # 設定のモデル(whisper の名前)は Qwen3-ASR のエンジンでは使えない
    return {"model": model, "language": "ja", "beam": beam,
            "vadMode": args.vad or (st.get("vadMode") if st.get("vadMode") in ("weak", "normal", "off") else "normal"),
            "boost": (st.get("boost") is True) if args.boost is None else args.boost == "on",
            "wordSplit": st.get("wordSplit") is not False, "splitChars": S.split_chars_for({}, st),
            "stripPunct": st.get("stripPunct") is not False, "glossary": glossary, "device": args.device, "temp0": bool(args.temp0),
            "engine": args.engine, "autoDict": False, "autoLearned": False}


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
    sel = m.get("selection") or {}
    src = {"eval": "評価用", "daily": "普段", "own": "評価用 + 普段", "all": "評価用 + 普段 + 友人", "friend": "友人の zip"}.get(m.get("source"), "")
    timed = bool(m.get("since") or m.get("until"))
    print("出どころ %s%s%s" % (src or m.get("scope"), "  期間 %s〜%s" % (m["since"], m["until"]) if timed else "",
                         "(時期で外した %d 本・時期が分からず外した %d 本)" % (sel.get("excludedByTime", 0), sel.get("unknownTime", 0)) if timed else ""))
    for sk in sel.get("friendSkipped") or []:
        print("  友人の zip を数えず: %s %s" % (sk["id"], sk["why"]))
    print("文書 %d 本・正解 %d 字・まとまり %d・校正済み %.1f 分" % (len(s["byDoc"]), o["refChars"], o["groups"], s.get("proofedSec", 0) / 60))
    if s.get("lowData"):
        print("※ まだ少ない(参考): 校正済みが %d 分に届いていません。決めるのには使わない" % (LOW_DATA_SEC // 60))
    ci = s.get("ci95")
    print("CER %s(95%%の範囲 %s)  置換 %d / 抜け %d / 余分 %d" % (pct(o["cer"]), "%s〜%s" % (pct(ci[0]).strip(), pct(ci[1]).strip()) if ci else "—", o["sub"], o["del"], o["ins"]))
    dt = s.get("docText")
    if dt and dt["refChars"]:
        print("時刻によらない CER %s  置換 %d / 抜け %d / 余分 %d(文書の文字を通しで比べる。行の時刻のずれを数えない)" % (pct(dt["cer"]), dt["sub"], dt["del"], dt["ins"]))
    if o["termRef"]:
        print("名前・用語の再現率 %s(%d/%d)・正解に無いのに出た %d" % (pct(o["termRate"]), o["termHit"], o["termRef"], o["termExtra"]))
    for title, key in (("条件(人の行のメモ)", "byTag"), ("要確認の印", "byFlag"), ("自信の度合い(機械の行の avg_logprob の最小)", "byConfidence"), ("まとまりの種類", "byKind")):
        print("  [%s]" % title)
        for k, v in s[key].items():
            if v["groups"]:
                print("    %-22s CER %s  字 %5d  置換 %3d 抜け %3d 余分 %3d" % (k, pct(v["cer"]), v["refChars"], v["sub"], v["del"], v["ins"]))
    if s.get("byDraft"):
        print("  [下書きを作ったエンジン(recognition.runs の最初の認識)]")
        for k, v in s["byDraft"].items():
            print("    %-40s CER %s  字 %5d  文書 %d 本" % (k, pct(v["cer"]), v["refChars"], v["docs"]))
    notes = {}
    for b in s.get("draftBias") or []:
        notes.setdefault(b["note"], []).append(b["id"])
    for note, ids in notes.items():
        print("注意: %s → %d 本(%s)。普段のデータは下書きを作ったエンジンに甘く出る。エンジンの比較の最終判断は評価用(定点)で"
              % (note, len(ids), ", ".join(ids[:5]) + (" …" if len(ids) > 5 else "")))
    if s.get("byGroup"):
        print("  [%s]" % s.get("groupBy"))
        for k, v in s["byGroup"].items():
            ci2 = v.get("ci95")
            print("    %s\n        文書 %d 本・字 %5d・校正済み %.1f 分  CER %s%s%s" % (k, v["docs"], v["refChars"], v["proofedSec"] / 60, pct(v["cer"]),
                  "(95%%の範囲 %s〜%s)" % (pct(ci2[0]).strip(), pct(ci2[1]).strip()) if ci2 else "", "  ※ まだ少ない(参考)" if v["lowData"] else ""))
    print("  [文書ごと]")
    for d in sorted(s["byDoc"], key=lambda d: -(d["cer"] or 0)):
        print("    %s %s  字 %5d  [%s] 下書き: %s%s  %s" % (d["id"], pct(d["cer"]), d["refChars"], d.get("source", ""), d.get("draft", ""), " ※" if d.get("draftBias") else "", d["title"]))


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


def base_meta(mode, args, docs, data, sel=None):
    sel = sel or {}
    return {"schema": SCHEMA, "mode": mode, "label": args.label or "", "at": int(time.time() * 1000), "git": git_rev(),
            "scope": SOURCE_SCOPE[resolve_source(args)] if not args.docs else "docs", "source": resolve_source(args),
            "since": sel.get("since", ""), "until": sel.get("until", ""), "selection": sel,
            "docs": [d["id"] for d in docs], "dataFingerprint": fingerprint(docs), "dataDir": data}


def group_spec(args, mode):
    """--group-by -> summarize の group(見出し, 文書 -> 組の名前)か None。
    stored = 文書の認識の記録すべて(途中で変わった文書は「混在」)/ run = 比べるエンジンは全部同じなので、下書きを作ったエンジンで分ける"""
    gb = getattr(args, "group_by", None)
    if not gb:
        return None
    if mode == "stored":
        return ("エンジン・設定・辞書の版ごと(--group-by %s)" % gb, lambda d: engine_key(d, gb))
    return ("下書きを作ったエンジンごと(--group-by %s)" % gb, lambda d: run_label(draft_run(d), gb) if draft_run(d) else DRAFT_NONE)


def cmd_stored(S, args, data):
    settings = read_json(os.path.join(data, "settings.json"), {}) or {}
    docs, sel = select_docs(data, args)
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
    res = {"meta": base_meta("stored", args, docs, data, sel), "summary": summarize(groups, docs, S, STORED, group_spec(args, "stored")), "groups": groups, "terms": terms}
    res["meta"]["mismatch"] = mismatch
    return res


def cmd_run(S, args, data):
    settings = read_json(os.path.join(data, "settings.json"), {}) or {}
    docs, sel = select_docs(data, args)
    if not docs:
        raise SystemExit("測れる文書がありません(校正済みの行がある%s)" % ("評価用の文書" if resolve_source(args) == "eval" else "文書"))
    hint_free = any(source_of(d) != "eval" for d in docs)   # 普段・友人の文書を認識し直すときは、ヒントなし(評価用と同じ条件)
    spec = run_spec(S, args, settings, hint_free)
    if hint_free and args.glossary is None and str(settings.get("glossary") or "").strip():
        print("用語集は渡しません(普段・友人の文書を含むため。ヒントなしの条件。渡すなら --glossary)")
    terms = name_terms(S, settings)
    load_sec, device = 0.0, ""
    if S.backend_name() != "fake":
        os.environ["TRANSCRIBE_ENGINE_DIR"] = data   # whisper.cpp の実行ファイル・モデルは本物の作業データの bin・models(serve の DATA_DIR は一時フォルダ。認識ワーカーにも届く)
        try:
            S.req_engine({"engine": spec["engine"]}, spec["model"])
            S.check_engine(spec)
        except S.ApiError as e:
            raise SystemExit(e.message)
        t0 = time.monotonic()
        _m, device = S.load_model(spec["model"], {"phase": "", "cancel": False}, spec["device"], engine=spec["engine"])
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
    meta = base_meta("run", args, docs, data, sel)
    run_rec = S.recognition_run(spec, {"device": device}, 0, 0)   # エンジンの名前と版(文字起こしの記録と同じ決め方)
    meta.update({"engine": {"engine": run_rec["engine"], "engineVersion": run_rec["engineVersion"],
                            "model": spec["model"], "device": device,
                            "settings": {k: spec[k] for k in ("language", "beam", "vadMode", "boost", "wordSplit", "splitChars", "stripPunct", "temp0")},
                            "glossary": spec["glossary"][:50], "context": args.context, "hintFree": hint_free},
                 "audioSec": round(audio_sec, 2), "wallSec": round(wall_sec, 2), "loadSec": round(load_sec, 2), "peakMemMB": peak_memory_mb(),
                 "perDoc": per_doc, "failed": len(failed)})
    if failed:
        print("注意: %d 本は認識できず、数に入っていません(比べるときは同じ文書で比べること)" % len(failed))
    summary = summarize(groups, docs, S, {"engine": run_rec["engine"], "model": spec["model"]}, group_spec(args, "run"))
    return {"meta": meta, "summary": summary, "groups": groups, "terms": terms}


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
        print("%s  %-6s CER %s  字 %5d  %s %s%s" % (name, m["mode"], pct(o["cer"]), o["refChars"], e.get("model", ""), m.get("label", ""),
                                               "  (まだ少ない・参考)" if r["summary"].get("lowData") else ""))


def main(argv=None):
    p = argparse.ArgumentParser(description="文字起こしの精度を評価用の校正済みデータで測る(作業データは読むだけ)")
    p.add_argument("mode", choices=("stored", "run", "compare", "list"))
    p.add_argument("files", nargs="*", help="compare の2つの結果")
    p.add_argument("--data", help="文字起こしの作業データのフォルダ(既定 %%LOCALAPPDATA%%\\youtube-tools\\transcribe)")
    p.add_argument("--scope", choices=("eval", "train", "all"), default="eval", help="eval = 評価用(既定)/ train = 評価用以外 / all = 自分の文書すべて(友人の zip は入れない)")
    p.add_argument("--source", choices=("eval", "daily", "all", "friend"),
                   help="測る文書の出どころ(--scope より優先)。eval = 評価用(既定)/ daily = 普段の校正済み(評価用以外)/ friend = 友人の zip / all = 全部")
    p.add_argument("--since", help="この日(YYYY-MM-DD。含む)以降のデータだけ。文書の時刻 = 校正済みの行の proofedAt の最大(無ければ updatedAt)")
    p.add_argument("--until", help="この日(YYYY-MM-DD。含む)までのデータだけ")
    p.add_argument("--group-by", dest="group_by", choices=("engine", "model"),
                   help="エンジン・設定・辞書の版ごとに集計する(engine = beam・VAD・ヒント・辞書の版まで / model = エンジン・モデル・版だけ)")
    p.add_argument("--intake", help="友人の zip の取り込み先(既定は dev/eval_import.py と同じ eval-intake)")
    p.add_argument("--docs", help="文書の id をカンマ区切りで(scope・source より優先。時期の指定は効く)")
    p.add_argument("--label", help="結果に付ける名前")
    p.add_argument("--model")
    p.add_argument("--vad", choices=("weak", "normal", "off"))
    p.add_argument("--beam", type=int)
    p.add_argument("--boost", choices=("on", "off"))
    p.add_argument("--glossary", help="認識のヒントに渡す語(、か改行区切り)。指定しなければ設定の用語集")
    p.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto", help="whisper.cpp では auto・cuda = GPU(Vulkan)")
    p.add_argument("--engine", choices=("faster-whisper", "whisper.cpp", "qwen3-asr", "llama.cpp"), default="faster-whisper", help="認識エンジン(計画 段2。whisper.cpp は setup/build-whisper-vulkan.bat で作ってから。qwen3-asr = Qwen3-ASR 0.6B の CPU(初回にモデル 879MB)・llama.cpp = Qwen3-ASR 1.7B の GPU(初回に実行ファイル 33MB とモデル 2.5GB))")
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
