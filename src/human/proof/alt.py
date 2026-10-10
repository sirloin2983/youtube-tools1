# -*- coding: utf-8 -*-
"""② 人の操作の層 human/proof: 2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b。plan/line-b-transcription.md)。
役割で組み直す RS3-E6(2026-10-10)に編集の src/editor/ed_alt.py から human/proof へ移した(中身は同じ)。旧い名前 ed_alt.名前 は editor/ed_alt.py(転送だけの殻。RS5 で消す)が回す。

ねらい: 校正を速くする。主のエンジンの文字起こしとは別に、2つ目のエンジンで同じ音声を認識し、2つの結果が食い違う所を
行の「候補」(学習の提案と同じ形。tier = "alt")として出す。人が 1 押しで採る。**自動では書き換えない**。
  POST /api/alt {id, engine?}   ジョブ(kind "alt")を足す。文書の範囲の音声を 2つ目のエンジンで認識して transcripts/<id>.alt.json に書く
  GET  /api/suggest?id=          学習の提案に alt の候補を足す(learn.suggest_for_doc → alt_suggest)

決まり:
  - 文書(<id>.json)は書き換えない・updatedAt を動かさない(開いている画面の保存を 409 にしない)ので、編集を止めるジョブにしない
  - ヒント(用語集・文脈)・置換辞書・学習した置換は使わない(機械の生の結果どうしを比べる。ヒントの語が候補に漏れないように)
  - 評価用の文書(evalSet)では断る・候補も出さない(定点の正解が 2 つのエンジンに寄るのを避ける決定)
  - その文書の最初の認識(recognition.runs の kind の無い記録)と同じエンジン・同じモデルなら断る(同じ結果を比べても意味が無い)
  - エンジンが使えない(実行ファイルが無い・GPU が無い)ときは、今のエンジンの仕組みどおり理由を出して失敗(黙って CPU にしない)
  - 候補は**今の行の文字**に対して毎回計算する(人が直した・採用した所は自然に消える)。校正済みの行には出さない

名前は serve.py からも見える(serve.py の _ED_MODULES。ほかの部品と重ならないよう、名前は alt_ / ALT_ / _alt_ で始める)。
ほかの部品の名前は `モジュール.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。編集の ed_state は読まない(app = 上の層)。
疑似の認識(TRANSCRIBE_BACKEND=fake)は backend.select() の口 alt_rows・check_engine・engine_version(本体は eval/fake/fake_asr)に任せる(RS5-D)。
**役割で組み直す RS6 a-3(2026-10-10)から ① pipeline/transcribe を直に読まない**: エンジンの準備(engine_ready)・ジョブの前の確かめ(check_engine_ready)・
音声の取り出しから整えた行まで(alt_lines。本物の処理 _alt_real とエンジンの版 alt_engine_version も)は ② の `flow/tx`(`_flowtx.名前`)。
ここに残るのは受付・alt.json の書き込み(文書があるときだけ = 保存のロック)・候補の計算(alt_diffs)と提案。
"""
import bisect
import difflib
import json
import os
import threading

from ytt import docloc as _docloc, errors as _errors, fsio as _fsio, schemas as _yschemas  # noqa: E402   エラー・書き込み・ジョブの表と待機列・文書の形の小道具
from flow import jobs as _heavy  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定の読み書き load_settings(RS3-1 に ed_learn から ytt/settings へ)
from ytt import tools as _tools, workdata as _workdata  # noqa: E402   (置き場所と版の今の値・動画と音声の小道具。RS3-0A に ed_state・ed_store から移した)
from flow import tx as _flowtx  # noqa: E402   ② エンジンの準備と確かめ・2 つ目のエンジンの行(engine_ready・check_engine_ready・alt_lines。RS6 a-3)
from ytt import txbase as _txbase  # noqa: E402   比べるときの寄せ方 alt_fold の正(RS2-9)・LANGS・MAX_TEXT・ロガー・ジョブの注意
from . import doc_jobs, store  # noqa: E402   行を分ける文字数 split_chars_for(doc_jobs ↔ alt は呼ぶときに読むので循環しても動く)・文書の読み書き(呼ぶたびに store.名前 で読む)

ALT_SCHEMA = "youtube-tools-alt/v1"
MAX_ALT_BYTES = 32 * 1024 * 1024
# 2つ目のエンジン(設定 altEngine の値 → エンジン・モデル・機器)。モデルはエンジンごとに決め打ち(ここ 1 か所)。
# 0.58.0(2026-10-11 ユーザー決定「普段よく使っているモデル以外は要らない」)で Qwen3-ASR 1.7B だけに(whisper.cpp・faster-whisper は外した。
# 保存した設定の外れた値は alt_engine_key が既定に戻す・古い alt.json のエンジンの名前は alt_suggest が「エンジン モデル」のまま出す)
ALT_ENGINES = {
    "llama.cpp": {"engine": "llama.cpp", "model": "qwen3-asr-1.7b", "device": "auto", "label": "Qwen3-ASR 1.7B(GPU・llama.cpp)"},
}
ALT_DEFAULT = "llama.cpp"   # 既定 = Qwen3-ASR(Whisper と間違え方が違い、GPU でとても速い)
# 設定 altEngine は api/settings/patch で直せる鍵。値の検査はこの表の持ち主のここで足す(ytt/settings は alt を読まない。RS3-1)
_settings.register_patch_key("altEngine", lambda v: isinstance(v, str) and v in ALT_ENGINES)

# 食い違いの候補の決まり(alt_diffs)
ALT_WINDOW_SEC = 90         # 行の時刻でこの長さごとの窓に区切ってそろえる(長い文書でも遅くならないように)
ALT_WINDOW_SLACK = 20       # 窓の区切りは、目安の前後この秒の中で、行と行のすき間がいちばん長い所
ALT_MAX_CHARS = 12          # wrong・right のどちらかがこれより長い食い違いは候補にしない
ALT_MAX_ITEMS = 1000        # (そろえるときに無視する字 ALT_DROP_CHARS は寄せ方 alt_fold と一緒に ytt/txbase.py。RS2-9)


# ---------- エンジンの選び方 ----------
def alt_engine_key(req=None):
    """要求の engine → 設定 altEngine → 既定。一覧に無い名前は使わない"""
    k = str((req or {}).get("engine") or "")
    if k in ALT_ENGINES:
        return k
    k = str(_settings.load_settings().get("altEngine") or "")
    return k if k in ALT_ENGINES else ALT_DEFAULT


def alt_info():
    """/api/tools の alt: 選べるエンジンと準備(画面の select)"""
    out = []
    for k, e in ALT_ENGINES.items():
        ok, why = _flowtx.engine_ready(e["engine"])   # 疑似は常に使える・faster-whisper は部品の有無・ほかは実行ファイルとモデル
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
    doc = store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしには、別のエンジンの候補を出しません(定点の正解が2つのエンジンに寄らないように)", 400)
    if not store.doc_has_rows(doc):
        raise _errors.ApiError("empty", "文字の無い文書です(先に文字起こしをしてください)", 400)
    src = _tools.check_source(doc.get("sourcePath"))
    if _settings.in_eval_dir(src):   # 印が無くても評価用のフォルダの動画は評価用(文字起こしと同じ扱い)
        raise _errors.ApiError("eval_set", "評価用のフォルダの動画には、別のエンジンの候補を出しません", 400)
    key = alt_engine_key(req)
    e = ALT_ENGINES[key]
    first = alt_first_run(doc)
    if first and str(first.get("engine") or "") == e["engine"] and str(first.get("model") or "") == e["model"]:
        raise _errors.ApiError("same_engine", "この文書の最初の文字起こしと同じエンジン・モデル(%s)です。「別のエンジンの候補」のエンジンを、別のものに変えてください" % e["label"], 400)
    if _heavy.tid_busy(tid, ("alt",)):
        raise _errors.ApiError("busy", "この文書は、もう別のエンジンで聞いている最中です", 409)
    start = _yschemas.num_or(doc.get("start"), 0.0) or 0.0
    end = _yschemas.num_or(doc.get("end"))
    spec = {"tid": tid, "sourcePath": src, "start": round(start, 2), "end": round(end, 2) if end else None, "altKey": key,
            "engine": e["engine"], "model": e["model"], "device": e["device"],
            "language": doc.get("language") if doc.get("language") in _txbase.LANGS and doc.get("language") != "auto" else "ja",
            "beam": 5, "vadMode": "weak", "boost": False, "wordSplit": True, "splitChars": doc_jobs.split_chars_for({}), "stripPunct": True,
            "glossary": [], "glossAuto": [], "context": {"members": [], "terms": []}, "autoDict": False, "autoLearned": False,
            "title": "別のエンジンで聞く: " + (str(doc.get("title") or "") or "無題")[:100]}
    # 実行ファイルが無い・faster-whisper が無い(理由を出して断る。GPU の有無は読み込みのときに分かる)。疑似は確かめない(口 check_engine。RS5-D)
    _flowtx.check_engine_ready(spec)
    return spec


# ---------- ジョブ ----------
def alt_path(tid, for_write=False):
    """<id>.alt.json のパス(for_write = 書く所。索引があるのに置き場所が見えなければ断る = docloc.doc_dir)"""
    return _docloc.doc_file(tid, ".alt.json", for_write=for_write)


def read_alt(tid):
    """<id>.alt.json(形が違えば None)"""
    if not _yschemas.TID_RE.match(str(tid or "")):
        return None
    return _fsio.read_schema_json(alt_path(tid), MAX_ALT_BYTES, ALT_SCHEMA, "rows")


# 本物の認識 _alt_real とエンジンの版 alt_engine_version は RS6 a-3 に ② flow/tx へ(alt_lines が使う)


def run_alt(job):
    """文書の範囲の音声を 2つ目のエンジンで認識し、<id>.alt.json に書く。文書は書き換えない(updatedAt も動かさない)"""
    spec = job["spec"]
    tid = spec["tid"]
    wav = os.path.join(_workdata.TMP_DIR, job["id"] + ".wav")
    with _heavy.job_errors(job, wav, log="別のエンジンでの認識で例外"):
        # 取り出し → 2 つ目のエンジン(本物 / 疑似)→ 文字起こしと同じ整え方(つなぐ join_rows はかけない)。置換・学習はかけない(② flow/tx.alt_lines)
        res = _flowtx.alt_lines(job, spec, wav)
        rows = res["rows"]
        body = {"schema": ALT_SCHEMA, "id": tid, "engine": spec["engine"], "engineVersion": res["engineVersion"], "model": spec["model"],
                "device": job.get("device", ""), "at": _yschemas.now_ms(), "range": [spec["start"], spec["end"]],
                "audioSec": round(float(res["total"] or 0), 2), "wallSec": res["wallSec"], "rows": rows,
                "post": {"clip": True, "mergeRepeats": True}}   # 行の後処理の印(0.52.1 より前の alt.json には無い。0.64.0 までは pullEnds も = 0.65.0 で音の谷へ寄せるのを消した)
        if res["fake"]:
            body["fake"] = True
        with store._save_lock:   # 認識の間に文書が消えていたら書かない(削除と同じロック。消したあとに付き物だけが生き返らないように)
            if not os.path.isfile(store.tx_path(tid)):
                raise _errors.ApiError("not_found", "認識の間に文書が消されました", 404)
            _fsio.atomic_write(alt_path(tid, for_write=True), json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), fsync_required=True)
        with _alt_cache_lock:
            _alt_cache.pop(tid, None)
        _heavy.job_done(job, tid, "完了(%d 行)" % len(rows))


def alt_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(run_job)が終わったあと: 設定 autoAlt がオンで評価用でなければ、alt のジョブを足す(失敗しても文字起こしの結果には影響しない)"""
    if not spec.get("autoAlt") or spec.get("evalSet"):
        return
    try:
        _heavy.add_job(alt_spec(tid, {}), "alt")
    except _errors.ApiError as e:
        _txbase.add_warning(job, "別のエンジンで聞くのを始められませんでした: " + e.message)
    except Exception as e:   # 想定外でも、書き終えた文字起こしのジョブを失敗にしない
        _txbase.log.warning("別のエンジンで聞くのを始められませんでした: %s %s", tid, e)


# ---------- 食い違いから候補を作る(純粋な関数) ----------
alt_fold = _txbase.alt_fold   # lint: keep 別名(RS2-9)= 比べるときだけの寄せ方(正は txbase。S.alt_fold・src/eval/tools/eval_alt・retime・ytcap が読む。差し替えない)


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
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        if a is None or b is None:
            continue
        segs.append({"n": n, "id": str(g.get("id") or ""), "start": a, "end": max(a, b), "text": str(g["text"]), "proofed": bool(g.get("proofed"))})
    segs.sort(key=lambda s: (s["start"], s["n"]))
    alts = []
    for r in alt_rows or []:
        if isinstance(r, dict) and str(r.get("text") or "").strip():
            a, b = _yschemas.num_or(r.get("start")), _yschemas.num_or(r.get("end"))
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
    stamp = _fsio.stamp(alt_path(tid))
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
