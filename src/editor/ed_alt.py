# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: 2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b。plan/line-b-transcription.md)。

ねらい: 校正を速くする。主のエンジンの文字起こしとは別に、2つ目のエンジンで同じ音声を認識し、2つの結果が食い違う所を
行の「候補」(学習の提案と同じ形。tier = "alt")として出す。人が 1 押しで採る。**自動では書き換えない**。
  POST /api/alt {id, engine?}   ジョブ(kind "alt")を足す。文書の範囲の音声を 2つ目のエンジンで認識して transcripts/<id>.alt.json に書く
  GET  /api/suggest?id=          学習の提案に alt の候補を足す(ed_learn.suggest_for_doc → alt_suggest)

決まり:
  - 文書(<id>.json)は書き換えない・updatedAt を動かさない(開いている画面の保存を 409 にしない)ので、編集を止めるジョブにしない
  - ヒント(用語集・文脈)・置換辞書・学習した置換は使わない(機械の生の結果どうしを比べる。ヒントの語が候補に漏れないように)
  - 評価用の文書(evalSet)では断る・候補も出さない(定点の正解が 2 つのエンジンに寄るのを避ける決定)
  - その文書の最初の認識(recognition.runs の kind の無い記録)と同じエンジン・同じモデルなら断る(同じ結果を比べても意味が無い)
  - エンジンが使えない(実行ファイルが無い・GPU が無い)ときは、今のエンジンの仕組みどおり理由を出して失敗(黙って CPU にしない)
  - 候補は**今の行の文字**に対して毎回計算する(人が直した・採用した所は自然に消える)。校正済みの行には出さない

名前は serve.py からも見える(serve.py の _ED_MODULES の最後。ほかの部品と重ならないよう、名前は alt_ / ALT_ / _alt_ で始める)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import bisect
import difflib
import json
import os
import threading
import time
import unicodedata

import ed_jobs  # noqa: E402,F401
import ed_learn  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
from pipeline.transcribe import tx_engines  # noqa: E402,F401   名前と版だけ(ネイティブの部品は読み込まない)

ALT_SCHEMA = "youtube-tools-alt/v1"
MAX_ALT_BYTES = 32 * 1024 * 1024
# 2つ目のエンジン(設定 altEngine の値 → エンジン・モデル・機器)。モデルはエンジンごとに決め打ち(ここ 1 か所)
ALT_ENGINES = {
    "llama.cpp": {"engine": "llama.cpp", "model": "qwen3-asr-1.7b", "device": "auto", "label": "Qwen3-ASR 1.7B(GPU・llama.cpp)"},
    "whisper.cpp": {"engine": "whisper.cpp", "model": "large-v3", "device": "auto", "label": "large-v3(GPU・whisper.cpp)"},
    "faster-whisper": {"engine": "faster-whisper", "model": "large-v3", "device": "cpu", "label": "large-v3(CPU・faster-whisper)"},
}
ALT_DEFAULT = "llama.cpp"   # 既定 = Qwen3-ASR(Whisper と間違え方が違い、GPU でとても速い)

# 食い違いの候補の決まり(alt_diffs)
ALT_WINDOW_SEC = 90         # 行の時刻でこの長さごとの窓に区切ってそろえる(長い文書でも遅くならないように)
ALT_WINDOW_SLACK = 20       # 窓の区切りは、目安の前後この秒の中で、行と行のすき間がいちばん長い所
ALT_MAX_CHARS = 12          # wrong・right のどちらかがこれより長い食い違いは候補にしない
ALT_DROP_CHARS = "ー〜～~"   # そろえるときに無視する字(伸ばし。表記だけの違いにしない)
ALT_MAX_ITEMS = 1000


# ---------- エンジンの選び方 ----------
def alt_engine_key(req=None):
    """要求の engine → 設定 altEngine → 既定。一覧に無い名前は使わない"""
    k = str((req or {}).get("engine") or "")
    if k in ALT_ENGINES:
        return k
    k = str(ed_learn.load_settings().get("altEngine") or "")
    return k if k in ALT_ENGINES else ALT_DEFAULT


def alt_info():
    """/api/tools の alt: 選べるエンジンと準備(画面の select)"""
    out = []
    fake = ed_state.backend_name() == "fake"
    for k, e in ALT_ENGINES.items():
        if fake:
            ok, why = True, ""
        elif e["engine"] == tx_engines.DEFAULT:
            ok = ed_state.has_faster_whisper()
            why = "" if ok else "faster-whisper が入っていません"
        else:
            ok, why = tx_engines.get(e["engine"]).ready(ed_jobs.engine_home())
        out.append({"key": k, "label": e["label"], "ready": bool(ok), "why": why})
    return {"engines": out, "default": ALT_DEFAULT}


def alt_first_run(doc):
    """その文書の最初の認識の記録(recognition.runs の kind の無いもの)。無ければ None"""
    rec = doc.get("recognition") if isinstance(doc.get("recognition"), dict) else {}
    for r in rec.get("runs") or []:
        if isinstance(r, dict) and not r.get("kind"):
            return r
    return None


def alt_spec(tid, req=None):
    """2つ目のエンジンで聞くジョブの指定。断る: 評価用・文字の無い文書・動画が無い・最初の認識と同じエンジンとモデル・同じ文書で実行中"""
    req = req or {}
    tid = str(tid or "")
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise ed_state.ApiError("eval_set", "評価用の文字起こしには、別のエンジンの候補を出しません(定点の正解が2つのエンジンに寄らないように)", 400)
    if not ed_store.doc_has_rows(doc):
        raise ed_state.ApiError("empty", "文字の無い文書です(先に文字起こしをしてください)", 400)
    src = ed_state.check_source(doc.get("sourcePath"))
    if ed_relink.in_eval_dir(src):   # 印が無くても評価用のフォルダの動画は評価用(文字起こしと同じ扱い)
        raise ed_state.ApiError("eval_set", "評価用のフォルダの動画には、別のエンジンの候補を出しません", 400)
    key = alt_engine_key(req)
    e = ALT_ENGINES[key]
    first = alt_first_run(doc)
    if first and str(first.get("engine") or "") == e["engine"] and str(first.get("model") or "") == e["model"]:
        raise ed_state.ApiError("same_engine", "この文書の最初の文字起こしと同じエンジン・モデル(%s)です。「別のエンジンの候補」のエンジンを、別のものに変えてください" % e["label"], 400)
    if ed_jobs.tid_busy(tid, ("alt",)):
        raise ed_state.ApiError("busy", "この文書は、もう別のエンジンで聞いている最中です", 409)
    start = ed_state.num(doc.get("start"), 0.0) or 0.0
    end = ed_state.num(doc.get("end"))
    spec = {"tid": tid, "sourcePath": src, "start": round(start, 2), "end": round(end, 2) if end else None, "altKey": key,
            "engine": e["engine"], "model": e["model"], "device": e["device"],
            "language": doc.get("language") if doc.get("language") in ed_state.LANGS and doc.get("language") != "auto" else "ja",
            "beam": 5, "vadMode": "weak", "boost": False, "wordSplit": True, "splitChars": ed_jobs.split_chars_for({}), "stripPunct": True,
            "glossary": [], "glossAuto": [], "context": {"members": [], "terms": []}, "autoDict": False, "autoLearned": False,
            "title": "別のエンジンで聞く: " + (str(doc.get("title") or "") or "無題")[:100]}
    if ed_state.backend_name() != "fake":
        ed_jobs.check_engine(spec)   # 実行ファイルが無い・faster-whisper が無い(理由を出して断る。GPU の有無は読み込みのときに分かる)
    return spec


# ---------- ジョブ ----------
def alt_path(tid):
    return os.path.join(ed_state.TX_DIR, tid + ".alt.json")


def read_alt(tid):
    """<id>.alt.json(形が違えば None)"""
    if not ed_state.TID_RE.match(str(tid or "")):
        return None
    return ed_state.read_schema_json(alt_path(tid), MAX_ALT_BYTES, ALT_SCHEMA, "rows")


def _alt_fake(job, spec, wav, total):
    """疑似の認識(TRANSCRIBE_BACKEND=fake)。主の疑似と同じ行に、TRANSCRIBE_FAKE_ALT = "誤=>正,…" の置き換えをかける(テスト用)"""
    pairs = []
    for part in os.environ.get("TRANSCRIBE_FAKE_ALT", "").split(","):
        if "=>" in part:
            a, b = part.split("=>", 1)
            if a:
                pairs.append((a, b))
    for s in ed_jobs.transcribe_fake(job, spec, wav, total):
        t = s["text"]
        for a, b in pairs:
            t = t.replace(a, b)
        yield dict(s, text=t)


def alt_engine_version(spec):
    if ed_state.backend_name() == "fake":
        return ""
    try:
        return ed_jobs.engine_version(tx_engines.get(spec["engine"]))
    except Exception:   # 記録のための値なので、分からなくても止めない
        return ""


def run_alt(job):
    """文書の範囲の音声を 2つ目のエンジンで認識し、<id>.alt.json に書く。文書は書き換えない(updatedAt も動かさない)"""
    spec = job["spec"]
    tid = spec["tid"]
    wav = os.path.join(ed_state.TMP_DIR, job["id"] + ".wav")
    with ed_jobs.job_errors(job, wav, log="別のエンジンでの認識で例外"):
        os.makedirs(ed_state.TMP_DIR, exist_ok=True)
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        ed_jobs.extract_audio(job, {"sourcePath": spec["sourcePath"], "start": spec["start"], "end": spec["end"], "boost": False}, wav)
        total = ed_state.media_duration(wav) or ((spec["end"] or 0) - spec["start"])
        t0 = time.monotonic()
        if ed_state.backend_name() == "fake":
            gen = _alt_fake(job, spec, wav, total)
        else:
            ed_jobs.check_engine(spec)
            job["state"] = "loading"
            gen = ed_jobs.transcribe_real(job, spec, wav, total)
        rows = []
        # 文字起こしのジョブと同じ整え方(句読点の除去・長い行の分け方・長さより後ろを捨てる・繰り返しをまとめる)。置換・学習はかけない。
        # 続いている行をつなぐ join_rows(0.57.1)はかけない(候補は文字を比べるだけで行の時刻を使わない。plan/line-b-row-timing.md の 7-2)
        for s in ed_jobs.expand_segments(gen, spec, total, join=False):
            if not s["text"]:
                continue
            rows.append({"start": round(s["start"] + spec["start"], 2), "end": round(s["end"] + spec["start"], 2), "text": s["text"][:ed_state.MAX_TEXT]})
            job["segments"] = len(rows)
        if job["cancel"]:
            raise ed_jobs.Cancelled()
        body = {"schema": ALT_SCHEMA, "id": tid, "engine": spec["engine"], "engineVersion": alt_engine_version(spec), "model": spec["model"],
                "device": job.get("device", ""), "at": ed_state.now_ms(), "range": [spec["start"], spec["end"]],
                "audioSec": round(float(total or 0), 2), "wallSec": round(time.monotonic() - t0, 2), "rows": rows,
                "post": {"clip": True, "mergeRepeats": True}}   # 行の後処理の印(0.52.1 より前の alt.json には無い。0.64.0 までは pullEnds も = 0.65.0 で音の谷へ寄せるのを消した)
        if ed_state.backend_name() == "fake":
            body["fake"] = True
        with ed_store._save_lock:   # 認識の間に文書が消えていたら書かない(削除と同じロック。消したあとに付き物だけが生き返らないように)
            if not os.path.isfile(ed_store.tx_path(tid)):
                raise ed_state.ApiError("not_found", "認識の間に文書が消されました", 404)
            ed_state.atomic_write(alt_path(tid), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        with _alt_cache_lock:
            _alt_cache.pop(tid, None)
        ed_jobs.job_done(job, tid, "完了(%d 行)" % len(rows))


def alt_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(run_job)が終わったあと: 設定 autoAlt がオンで評価用でなければ、alt のジョブを足す(失敗しても文字起こしの結果には影響しない)"""
    if not spec.get("autoAlt") or spec.get("evalSet"):
        return
    try:
        ed_jobs.add_job(alt_spec(tid, {}), "alt")
    except ed_state.ApiError as e:
        ed_state.add_warning(job, "別のエンジンで聞くのを始められませんでした: " + e.message)
    except Exception as e:   # 想定外でも、書き終えた文字起こしのジョブを失敗にしない
        ed_state.log.warning("別のエンジンで聞くのを始められませんでした: %s %s", tid, e)


# ---------- 食い違いから候補を作る(純粋な関数) ----------
def alt_fold(ch):
    """比べるときだけの寄せ方: NFKC・小文字・カタカナ → ひらがな・伸ばしと記号と空白は捨てる(文字でも数字でもないもの)"""
    out = []
    for c in unicodedata.normalize("NFKC", ch).lower():
        o = ord(c)
        if 0x30A1 <= o <= 0x30F6:
            c = chr(o - 0x60)
        if c in ALT_DROP_CHARS or unicodedata.category(c)[0] not in "LN":
            continue
        out.append(c)
    return "".join(out)


def _alt_chars(text, tag):
    """寄せた文字の並び [(寄せた字, tag, 元の位置)]"""
    out = []
    for p, ch in enumerate(text):
        for c in alt_fold(ch):
            out.append((c, tag, p))
    return out


def _alt_is_hira(s):
    return bool(s) and all(0x3041 <= ord(c) <= 0x309F for c in s)


def _alt_has_kanji(s):
    return any(0x4E00 <= ord(c) <= 0x9FFF or 0x3400 <= ord(c) <= 0x4DBF or c in "々〆" for c in s)


def alt_notation_only(wrong, right):
    """表記だけの違いらしい(片方がひらがなだけ・もう片方が漢字まじり。例: すご → 凄)。読みは分からないので、安全な側(候補にしない)に倒す"""
    for a, b in ((wrong, right), (right, wrong)):
        if _alt_is_hira(a) and _alt_has_kanji(b) and all(_alt_has_kanji(c) or _alt_is_hira(c) for c in b):
            return True
    return False


def _alt_windows(rows):
    """行(時刻の順)を ALT_WINDOW_SEC ごとの窓に区切る → [(最初の行, 最後の行の次)]。区切りは目安の前後で行のすき間がいちばん長い所"""
    out, i0, n = [], 0, len(rows)
    while i0 < n:
        t0 = rows[i0]["start"]
        k, best, gap_best, end_max = i0 + 1, None, None, rows[i0]["end"]
        while k < n and rows[k]["start"] < t0 + ALT_WINDOW_SEC + ALT_WINDOW_SLACK:
            if rows[k]["start"] >= t0 + ALT_WINDOW_SEC - ALT_WINDOW_SLACK:
                gap = rows[k]["start"] - end_max
                if gap_best is None or gap > gap_best:
                    best, gap_best = k, gap
            end_max = max(end_max, rows[k]["end"])
            k += 1
        cut = best if best is not None else k
        out.append((i0, cut))
        i0 = cut
    return out


def alt_diffs(rows, alt_rows):
    """今の行と 2つ目のエンジンの行の食い違い → (候補 [{seg, i, wrong, right, tier: "alt", pos: 0, neg: 0}], 数えた理由 {long, cross, mostly, notation, edge})。
    rows = 文書の segments(id・start・end・text・proofed)、alt_rows = alt.json の rows(start・end・text。時刻は元の動画の秒)。
    窓(ALT_WINDOW_SEC)ごとに、寄せた文字を difflib.SequenceMatcher でそろえる。候補にするのは 1 つの行の中に収まる置き換え
    (片方だけにある文字は隣の 1 文字を足して置き換えの形に)。長すぎる・行をまたぐ・行の半分以上が違う・表記だけの違い・窓の境目は出さない"""
    stats = {"long": 0, "cross": 0, "mostly": 0, "notation": 0, "edge": 0}
    segs = []
    for n, g in enumerate(rows or []):
        if not isinstance(g, dict) or not str(g.get("text") or "").strip():
            continue
        a, b = ed_state.num(g.get("start")), ed_state.num(g.get("end"))
        if a is None or b is None:
            continue
        segs.append({"n": n, "id": str(g.get("id") or ""), "start": a, "end": max(a, b), "text": str(g["text"]), "proofed": bool(g.get("proofed"))})
    segs.sort(key=lambda s: (s["start"], s["n"]))
    alts = []
    for r in alt_rows or []:
        if isinstance(r, dict) and str(r.get("text") or "").strip():
            a, b = ed_state.num(r.get("start")), ed_state.num(r.get("end"))
            if a is not None and b is not None:
                alts.append(((a + max(a, b)) / 2, str(r["text"])))
    alts.sort(key=lambda x: x[0])
    if not segs or not alts:
        return [], stats
    wins = _alt_windows(segs)
    # 窓の境目の時刻(前の窓の行の終わりの最大と、次の窓の最初の行の始まりの間)。2つ目のエンジンの行は、真ん中の時刻で1つの窓だけに入れる
    bounds = []
    for i0, i1 in wins[1:]:
        prev_end = max(s["end"] for s in segs[:i0][-50:])
        nxt = segs[i0]["start"]
        bounds.append((prev_end + nxt) / 2 if prev_end < nxt else nxt)
    groups = [[] for _ in wins]
    for mid, text in alts:
        groups[bisect.bisect_right(bounds, mid)].append(text)
    found = {}   # 行の通し番号 → [候補]
    for w, (i0, i1) in enumerate(wins):
        a_chars = []
        for s in segs[i0:i1]:
            a_chars += _alt_chars(s["text"], s["n"])
        alt_text = "".join(groups[w])
        b_chars = _alt_chars(alt_text, 0)
        if not a_chars or not b_chars:
            continue
        a_str, b_str = "".join(c for c, _t, _p in a_chars), "".join(c for c, _t, _p in b_chars)
        row_len, row_diff, cands = {}, {}, []
        for _c, t, _p in a_chars:
            row_len[t] = row_len.get(t, 0) + 1
        sm = difflib.SequenceMatcher(None, a_str, b_str, autojunk=False)
        for tag, x1, x2, y1, y2 in sm.get_opcodes():
            if tag == "equal":
                continue
            # 行ごとの違いの量(行の半分以上が違う行は、候補を出さない)
            for k in range(x1, x2):
                row_diff[a_chars[k][1]] = row_diff.get(a_chars[k][1], 0) + 1
            extra = max(0, (y2 - y1) - (x2 - x1))
            if extra:
                k = x1 if x1 < len(a_chars) else x1 - 1
                row_diff[a_chars[k][1]] = row_diff.get(a_chars[k][1], 0) + extra
            if (w > 0 and x1 == 0) or (w < len(wins) - 1 and x2 == len(a_chars)):
                stats["edge"] += 1   # 窓の境目(2つ目のエンジンの行が窓をまたいだ分の食い違いかもしれない)
                continue
            if x1 == x2 or y1 == y2:   # 片方だけにある文字: 隣の 1 文字(そろった所)を足して置き換えの形に
                if x1 > 0 and y1 > 0:
                    x1, y1 = x1 - 1, y1 - 1
                elif x2 < len(a_chars) and y2 < len(b_chars):
                    x2, y2 = x2 + 1, y2 + 1
                else:
                    continue
            rows_in = {a_chars[k][1] for k in range(x1, x2)}
            if len(rows_in) != 1:
                stats["cross"] += 1
                continue
            t = a_chars[x1][1]
            p0, p1 = a_chars[x1][2], a_chars[x2 - 1][2]
            q0, q1 = b_chars[y1][2], b_chars[y2 - 1][2]
            seg = next(s for s in segs[i0:i1] if s["n"] == t)
            wrong = seg["text"][p0:p1 + 1]
            right = "".join(alt_text[q0:q1 + 1].split())
            if not wrong or not right or alt_fold(wrong) == alt_fold(right):
                continue
            if len(wrong) > ALT_MAX_CHARS or len(right) > ALT_MAX_CHARS:
                stats["long"] += 1
                continue
            if tag == "replace" and alt_notation_only(wrong, right):   # 片方だけにある文字(足した・抜けた)は表記の違いにしない
                stats["notation"] += 1
                continue
            cands.append((t, p0, wrong, right))
        for t, p0, wrong, right in cands:
            if row_diff.get(t, 0) * 2 >= row_len.get(t, 1):
                stats["mostly"] += 1
                continue
            found.setdefault(t, []).append((p0, wrong, right))
    by_n = {s["n"]: s for s in segs}
    out = []
    for t in sorted(found):
        seg, used = by_n[t], []
        if seg["proofed"]:   # 校正済み(人が聞いて確かめた)の行には出さない
            continue
        for p0, wrong, right in sorted(found[t]):
            if any(p0 < b and a < p0 + len(wrong) for a, b in used):
                continue   # 同じ位置で重なる候補は出さない
            used.append((p0, p0 + len(wrong)))
            out.append({"seg": seg["id"], "i": p0, "wrong": wrong, "right": right, "tier": "alt", "pos": 0, "neg": 0})
    return out, stats


# ---------- 提案(GET /api/suggest)に足す ----------
_alt_cache = {}   # tid -> (鍵, (候補, 数えた理由))
_alt_cache_lock = threading.Lock()


def alt_cached(cache, lock, tid, key, compute):
    """文書ごとの候補の計算(compute())を覚えておく(鍵 = 結果のファイルの更新日時と大きさ・文書の updatedAt・行の数が同じなら前の結果)"""
    with lock:
        hit = cache.get(tid)
    if hit and hit[0] == key:
        return hit[1]
    val = compute()
    with lock:
        cache[tid] = (key, val)
    return val


def alt_spans_of(items):
    """先に出す候補の位置 {行の id: [(始め, 終わり)…]}"""
    spans = {}
    for x in items:
        spans.setdefault(x.get("seg"), []).append((x["i"], x["i"] + len(x["wrong"])))
    return spans


def alt_skip(x, dismissed, spans):
    """出さない候補か: 却下した(dismissed = {"seg|誤=>正"})・先に出す候補(spans = alt_spans_of。学習の提案)と重なる"""
    return ("%s|%s=>%s" % (x["seg"], x["wrong"], x["right"]) in dismissed
            or any(x["i"] < b and a < x["i"] + len(x["wrong"]) for a, b in spans.get(x["seg"], [])))


def alt_suggest(tid, doc, dismissed, taken):
    """文書への alt の候補 → (候補, 情報 {engine, model, label, at, count, skipped} か None)。
    評価用の文書・alt.json が無い文書は ([], None)。却下した候補(dismissed = {"seg|誤=>正"})・学習の提案(taken)と重なる位置は出さない"""
    if doc.get("evalSet") is True:
        return [], None
    stamp = ed_state.file_stamp(alt_path(tid))
    if stamp is None:
        return [], None
    alt = read_alt(tid)
    if not alt:
        return [], None
    items, stats = alt_cached(_alt_cache, _alt_cache_lock, tid, (stamp, doc.get("updatedAt"), len(doc.get("segments") or [])),
                              lambda: alt_diffs(doc.get("segments") or [], alt.get("rows") or []))
    spans = alt_spans_of(taken)
    out = []
    for x in items:
        if alt_skip(x, dismissed, spans):
            continue   # 却下した・学習の提案を優先
        out.append(dict(x))
        if len(out) >= ALT_MAX_ITEMS:
            break
    e = next((v for v in ALT_ENGINES.values() if v["engine"] == alt.get("engine") and v["model"] == alt.get("model")), None)
    info = {"engine": str(alt.get("engine") or ""), "model": str(alt.get("model") or ""), "label": e["label"] if e else "%s %s" % (alt.get("engine"), alt.get("model")),
            "at": alt.get("at"), "count": len(out), "skipped": stats}
    return out, info
