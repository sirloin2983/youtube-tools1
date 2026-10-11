# -*- coding: utf-8 -*-
"""② 人の操作の層 human/proof: 再認識(選んだ行 each・範囲 range・全体 whole)と疑わしい所の認識し直し(redo)のジョブの本体と、文書への反映・
再認識で差し替えた機械の出力の記録(recognition.runs)・単語の時刻の差し替え。

役割で組み直す RS2-8c(2026-10-10)に human/proof/doc_jobs から割った(中身は同じ。元は編集の ed_jobs)。受付(validate_retranscribe・redo_spec)・
疑わしい行の選び方(redo_targets)・辞書の組(dict_pairs)・新しい行の id(_fresh_id)は doc_jobs に残し、ここから `doc_jobs.名前` で呼ぶたびに読む
(向きは rerun → doc_jobs だけ。doc_jobs はここを読まない)。
**役割で組み直す RS6 a-3(2026-10-10)から ① pipeline/transcribe を直に読まない**: 音声の取り出し(extract_span)・認識器とワーカーのモデル(redo_recognizer・
each_lines・recognize_range)・全体の続きの記録の後始末(end_whole)・声の検出の知らせ(note_vad)・置換辞書の組(dict_pairs)は ② の `flow/tx`(`_flowtx.名前`)。
疑わしい所の認識し直しの設定 redo_kwargs と本物の処理(_redo_real・_redo_finish・_each_real)もそこへ移した。句読点・文字数・印の文は ytt/txtext、
置換辞書の当て方は ytt/dictfmt。再認識の記録の共通項目は ② flow/tx の rerun_base・単語の時刻は ytt/txwords(RS6 a-5b)。
ed_state は読まない(置き場所と元のファイルの検査は ytt の workdata・tools・ジョブの表は ytt/jobs)。S.名前 は serve の受付がここへ回す
(テストの S.MAX_RERUNS = …・patch.object(S, "apply_range") もここに届く)。
"""
import time

from ytt import errors as _errors, schemas as _yschemas, tools as _tools  # noqa: E402
from flow import jobs as _heavy  # noqa: E402
from ytt import jobs as _slots  # noqa: E402
from ytt import dictfmt as _dictfmt, txtext as _txtext  # noqa: E402   置換辞書を当てる apply_replacements・句読点 strip_punct・文字数 text_chars・印の文 SPARSE_FLAG(RS6 a-3 に ① から ytt へ)
from ytt import txwords  # noqa: E402   単語の時刻の読み書き read_words・write_words(RS6 a-5b に ① records から ytt へ)
from flow import tx as _flowtx  # noqa: E402   ② 再認識の動詞(extract_span・redo_recognizer・each_lines・recognize_range・end_whole・note_vad・dict_pairs。RS6 a-3)
from ytt import txbase as _txbase  # noqa: E402
from . import store  # noqa: E402   文書の読み書き・保存のロック・控え(RS3-E5a に editor/ed_store から隣へ。呼ぶたびに store.名前 で読む)
from . import doc_jobs  # noqa: E402   受付の側の _fresh_id・redo_targets(呼ぶたびに doc_jobs.名前 で読む)


# ---------- 再認識で差し替えた機械の出力の記録(マスタープラン Q2。original を差し替える前の分を recognition.runs に残す) ----------
MAX_RERUNS = 30             # recognition.runs に残す再認識の記録の件数(古いものから捨てる。最初の認識の記録 = kind の無いものは捨てない)
MAX_REPLACED_ROWS = 20000   # 再認識の記録の replaced の行の合計の上限(超えたら古い記録から捨てる。文書が大きくなりすぎないように)


def replaced_rows(orig, spans, keep=()):
    """original のうち、spans のどれかに真ん中が入り、keep に入らない行(= これから差し替えられる機械の出力)。
    replace_original・replace_original_multi と同じ決まり(真ん中で決める)"""
    out = []
    for o in orig or []:
        if not isinstance(o, dict):
            continue
        try:
            m = (float(o["start"]) + float(o["end"])) / 2
        except (KeyError, TypeError, ValueError):
            continue
        if any(a <= m <= b for a, b in spans) and not _in_spans(m, keep):
            out.append(dict(o))
    return out


def record_rerun(doc, spec, kind, spans, replaced, pairs=None):
    """再認識で original を差し替える前に、差し替えられる機械の出力を recognition.runs に1件足す(文書を書くのは呼び出し側。_save_lock の中)。
    1件 = {"kind": "each" | "range" | "whole" | "redo", 新しい結果を出したエンジン・版・モデル・言語・設定(settings.dict = 辞書の版),
           "range": [最初, 最後], "spans"?: 行ごとの範囲(each・redo で2つ以上のとき), "replaced": [差し替えられた original の行], "at"}。
    original の無い文書(文字起こしせずに開いた)でも、いつ・何で認識し直したかは残す(replaced は空)。pairs = 作ってある _flowtx.dict_pairs(spec)"""
    spans = [[round(float(a), 3), round(float(b), 3)] for a, b in spans]
    if not spans:
        return
    # 機械が行を書き換えるので、「動画を全部聞いて確かめた」印(評価ドリル。eval/drill/drill)も外す。行の proofed を外すのと同じ時に。
    # 再認識(each・range・whole)と疑わしい所の認識し直し(redo)は、どれも差し替える前にここを通る
    doc.pop("evalReviewed", None)
    rep = replaced[:MAX_REPLACED_ROWS]
    run = dict(_flowtx.rerun_base(spec, pairs, kind), range=[min(a for a, _ in spans), max(b for _, b in spans)], replaced=rep)
    if len(spans) > 1:
        run["spans"] = spans[:MAX_REPLACED_ROWS]
    if len(replaced) > len(rep):
        run["replacedOmitted"] = len(replaced) - len(rep)
    rec = doc.get("recognition") if isinstance(doc.get("recognition"), dict) else {}
    runs = [r for r in rec.get("runs") or [] if isinstance(r, dict)] + [run]
    reruns = [r for r in runs if r.get("kind")]
    total = sum(len(r.get("replaced") or []) for r in reruns)
    drop = set()
    for r in reruns[:-1]:   # 古い記録から捨てる(今回の分は残す)
        if len(reruns) - len(drop) <= MAX_RERUNS and total <= MAX_REPLACED_ROWS:
            break
        drop.add(id(r))
        total -= len(r.get("replaced") or [])
    doc["recognition"] = dict(rec, runs=[r for r in runs if id(r) not in drop])


def replace_words(tid, a, b, new_words, model="", keep_spans=()):
    """範囲 [a, b] の単語を、認識し直した単語に差し替える(真ん中が範囲に入る単語を消す。keep_spans の区間の単語は残す)。
    以前の単語が無い文書は、新しい単語だけにしない(範囲の外の単語が無いまま一部だけあると、分け直すときに紛らわしいため、範囲の単語だけで作る)"""
    old = txwords.read_words(tid) or []
    keep = [w for w in old if not (a - 1e-6 <= (w[0] + w[1]) / 2 <= b + 1e-6) or _in_spans((w[0] + w[1]) / 2, keep_spans)]
    txwords.write_words(tid, keep + [list(w) for w in new_words], model)


# ---------- 選んだ行の再認識の反映(行ごと = each) ----------
def replace_original(orig, a, b, text):
    """機械の出力の記録のうち、a〜b にある分を、新しい機械の出力1件に差し替える(再認識の結果を『人が直した』と誤学習しないため)。"""
    return replace_original_multi(orig, a, b, [{"start": a, "end": b, "raw": text}])


def apply_retranscribe(spec, results):
    with store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_retranscribe(spec, results)


def _apply_retranscribe(spec, results):
    doc = store.read_transcript(spec["tid"])
    pairs = _flowtx.dict_pairs(spec)
    have_orig = isinstance(doc.get("original"), list)
    orig = doc["original"] if have_orig else []
    spans = [(sg["start"], sg["end"]) for sg in doc.get("segments") or [] if results.get(sg["id"])]
    record_rerun(doc, spec, "each", spans, replaced_rows(orig, spans), pairs)   # 差し替える前の機械の出力を残す(マスタープラン Q2)
    done = unsure = 0
    for sg in doc.get("segments") or []:
        r = results.get(sg["id"])
        if not r:
            continue
        raw, flag = r
        keep = [x for x in str(sg.get("flag", "")).split("、") if x in _txbase.SPK_FLAGS]   # 話者の印は残し、文字の印は付け直す
        sg["text"], _ = _dictfmt.apply_replacements(raw[:_txbase.MAX_TEXT], pairs)
        sg.pop("proofed", None)   # 機械が書き換えた行は、人が確認し直すまで校正済みにしない
        sg.pop("proofedAt", None)   # 校正した時刻も一緒に外す(次に校正済みにした時刻から数え直す)
        sg["flag"] = "、".join(([flag] if flag else []) + keep)[:100]
        unsure += 1 if flag else 0
        done += 1
        if have_orig:
            orig = replace_original(orig, sg["start"], sg["end"], raw)
    if have_orig:
        doc["original"] = orig
    store.backup_doc(spec["tid"], "retranscribe")
    doc["retranscribed"] = {"model": spec["model"], "lines": done, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    store.apply_edit_cuts(spec["tid"], doc)
    store.commit(spec["tid"], doc, why="rerun_each")
    return done, unsure


def _in_spans(t, spans):
    return any(p0 <= t <= p1 for p0, p1 in spans)


def replace_original_multi(orig, a, b, items, keep=()):
    """機械の出力の記録のうち、a〜b にある分を新しい機械の出力に差し替える。keep の区間(校正済み・元のまま残した行)にある分は古いまま残す"""
    keep_o = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b) or _in_spans((o["start"] + o["end"]) / 2, keep)]
    keep_o += [{"start": x["start"], "end": x["end"], "text": x["raw"][:_txbase.MAX_TEXT], **(x.get("conf") or {})} for x in items]
    keep_o.sort(key=lambda o: o["start"])
    return keep_o


# ---------- 範囲・全体の再認識の反映(docs/design/whole-retranscribe-design.md の 3-4・4-2) ----------
PROTECT_PAD = 0.05      # 守る行(校正済み・元のまま残す行)の前後の余白(秒)
MIN_NEW_LINE = 0.3      # 守る区間を避けて切り詰めた行がこれより短ければ捨てる(秒)
EMPTY_COVER = 0.3       # 元の行の時間のうち、新しい行が重なるのがこの割合未満なら「新しい認識でほぼ空」→ 元の行を残す
LOOSE_PAD = 0.5         # ほぼ空だった所を緩い条件で認識し直すときの前後の余白(秒)
EMPTY_FLAG = "再認識で文字が出なかった(元の行のまま)"
LOOSE_FLAG = "声が重なる所などを緩い条件で認識"


def _ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def fit_lines(lines, protect, strip=True):
    """新しい行が守る区間 protect=[(a,b)] にかからないようにする: 真ん中が守る区間に入る行は捨て、一部だけ重なる行は外側に切り詰める
    (単語の時刻があれば文字も切り詰める)。MIN_NEW_LINE 秒未満になった行は捨てる"""
    out = []
    for x in lines:
        st, en = float(x["start"]), float(x["end"])
        mid = (st + en) / 2
        if _in_spans(mid, protect):
            continue
        for p0, p1 in protect:
            if p1 <= st or p0 >= en:
                continue
            if p0 <= st:
                st = p1
            elif en <= p1:
                en = p0
            elif mid < p0:   # 守る区間が行の中にある: 真ん中のある側を残す
                en = p0
            else:
                st = p1
        if en - st < MIN_NEW_LINE:
            continue
        if (st, en) != (x["start"], x["end"]):
            ws = [w for w in x.get("words") or [] if st - 1e-6 <= (w[0] + w[1]) / 2 <= en + 1e-6]
            y = dict(x, start=st, end=en, words=ws)
            if x.get("words"):
                joined = "".join(w[2] for w in ws).strip()
                y["raw"] = _txtext.strip_punct(joined) if strip else joined
                if not y["raw"]:
                    continue
            x = y
        out.append(x)
    return out


def plan_range(doc, spec, lines):
    """範囲・全体の再認識の反映の計画(文書は変えない)。
    -> {"protect": 守る区間, "kept": 守った行(範囲にかかる、差し替えない行), "lines": 守る区間を避けた新しい行,
        "empty": 新しい認識でほぼ空だった差し替え対象の行(元のまま残す)}"""
    a, b = spec["range"]
    ids = set(spec["ids"])
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    kept = [g for g in segs if g["id"] not in ids and _ov(g["start"], g["end"], a, b) > 0]
    protect = [(g["start"] - PROTECT_PAD, g["end"] + PROTECT_PAD) for g in kept]
    fitted = fit_lines(lines, protect, spec.get("stripPunct", True) is not False)
    empty = []
    for g in segs:
        if g["id"] not in ids or not str(g.get("text") or "").strip():
            continue
        d = g["end"] - g["start"]
        cover = sum(_ov(g["start"], g["end"], x["start"], x["end"]) for x in fitted) / d if d > 0 else 1.0
        if cover < EMPTY_COVER:
            empty.append(g)
    return {"protect": protect, "kept": kept, "lines": fitted, "empty": empty}


def apply_range(spec, lines, loose=()):
    """範囲の行を、新しく認識した行に差し替える。話者は、時間が最も重なっていた元の行から引き継ぐ。
    lines=[{start,end,raw,flag,words?,conf?}]、loose = ほぼ空だった所を緩い条件で認識した行(印を付けて入れる)。
    差し替えない行(spec["ids"] に無い行。全体の再認識では校正済み)にかかる新しい行は避け、新しい認識でほぼ空だった元の行は残す(4-2・3-4)。
    -> {"lines": 入れた新しい行の数, "unsure", "kept": 守った行の数, "emptyKept": 元のまま残した行の数, "loose": 緩い条件の行の数}"""
    with store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_range(spec, lines, loose)


def _apply_range(spec, lines, loose=()):
    a, b = spec["range"]
    doc = store.read_transcript(spec["tid"])
    pairs = _flowtx.dict_pairs(spec)
    loose = [dict(x, flag="、".join(f for f in (LOOSE_FLAG, x.get("flag", "")) if f)) for x in loose]
    plan = plan_range(doc, spec, sorted(list(lines) + loose, key=lambda x: x["start"]))
    empty_ids = {g["id"] for g in plan["empty"]}
    empty_spans = [(g["start"] - PROTECT_PAD, g["end"] + PROTECT_PAD) for g in plan["empty"]]
    keep_spans = plan["protect"] + empty_spans
    new_lines = fit_lines(plan["lines"], empty_spans, spec.get("stripPunct", True) is not False)   # 元のまま残す行にもかけない
    ids = set(spec["ids"])
    old = [g for g in doc.get("segments") or [] if g["id"] in ids]
    rest = [g for g in doc.get("segments") or [] if g["id"] not in ids or g["id"] in empty_ids]
    for g in rest:
        if g["id"] in empty_ids and EMPTY_FLAG not in str(g.get("flag") or ""):
            g["flag"] = "、".join(f for f in (str(g.get("flag") or ""), EMPTY_FLAG) if f)[:100]
    used = {g["id"] for g in rest}
    new, unsure, n = [], 0, 0
    for x in new_lines:
        best, bo = "", 0.0
        for g in old:
            ov = min(g["end"], x["end"]) - max(g["start"], x["start"])
            if ov > bo and g.get("speaker"):
                best, bo = g["speaker"], ov
        text, _ = _dictfmt.apply_replacements(x["raw"][:_txbase.MAX_TEXT], pairs)
        sid, n = doc_jobs._fresh_id(used, "r%d".__mod__, n)
        new.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": text, "speaker": best, "flag": x.get("flag", "")[:100]})
        unsure += 1 if x.get("flag") else 0
    doc["segments"] = sorted(rest + new, key=lambda g: (g["start"], g["end"]))
    record_rerun(doc, spec, "whole" if spec.get("mode") == "whole" else "range", [(a, b)],
                 replaced_rows(doc.get("original") if isinstance(doc.get("original"), list) else [], [(a, b)], keep_spans), pairs)   # 差し替える前の機械の出力を残す(Q2)
    if isinstance(doc.get("original"), list):   # 守った行・元のまま残した行の機械の出力は古いまま(人が直した行との対応を壊さない)
        doc["original"] = replace_original_multi(doc["original"], a, b, new_lines, keep_spans)
    store.backup_doc(spec["tid"], "retranscribe")
    n_loose = sum(1 for x in new_lines if LOOSE_FLAG in str(x.get("flag") or ""))
    doc["retranscribed"] = {"model": spec["model"], "lines": len(new), "range": [a, b], "whole": spec.get("mode") == "whole",
                            "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    store.apply_edit_cuts(spec["tid"], doc)   # 差し替えた行の「カット済」は、編集の内容(時刻)から付け直す
    store.commit(spec["tid"], doc, why="rerun_range")
    try:   # 単語の時刻も範囲の分を差し替える(守った行の単語は残す。古い文書は、ここで取り直せる = 「今の文書を分け直す」の案内)
        replace_words(spec["tid"], a, b, [w for x in new_lines for w in x.get("words") or []], spec["model"], keep_spans)
    except OSError as e:
        _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", spec["tid"], e)
    return {"lines": len(new), "unsure": unsure, "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose}


# ---------- 疑わしい所だけ認識し直す(12 ③-2。ユーザー承認 2026-09-27: 設計どおり) ----------
REDO_MAX_SEC = 600      # 時間の上限(秒)。超えたら残りの行はやめて、そこまでの結果で置き換える
REDO_BAD_FLAGS = (_txtext.SPARSE_FLAG, "よくある誤認識の文", "同じ文の繰り返し", "繰り返しの可能性", "音声でない可能性", _txbase.LEAK_FLAG)


# 疑わしい所を認識し直すときの設定 redo_kwargs は RS6 a-3 に ② flow/tx へ(ワーカーに渡す設定 = 認識器の準備と一緒)


def redo_better(row, lines, old_lp=None):
    """認識し直した結果が良くなったか: 文字が増えた・まだ疑わしい印(文字が少ない・よくある誤認識・繰り返し・BGM)が無い・
    avg_logprob が分かれば上がった。-> (良くなったか, 理由)"""
    if not lines:
        return False, "何も認識されない"
    new_chars, old_chars = sum(_txtext.text_chars(x["raw"]) for x in lines), _txtext.text_chars(row.get("text"))
    if new_chars <= old_chars:
        return False, "文字が増えない"
    flags = "、".join(str(x.get("flag") or "") for x in lines)
    if any(f in flags for f in REDO_BAD_FLAGS):
        return False, "まだ疑わしい"
    lps = [float(x["lp"]) for x in lines if isinstance(x.get("lp"), (int, float))]
    if old_lp is not None and lps and sum(lps) / len(lps) <= old_lp:
        return False, "自信が上がらない"
    return True, ""


def apply_redo(spec, results):
    """認識し直して良くなった行をまとめて置き換える(1回の保存。前の版は履歴に残す = 「以前の版に戻す」で戻せる)。
    途中で人が直した・校正した行は置き換えない。-> 置き換えた行の数"""
    if not results:
        return 0
    with store._save_lock:
        tid = spec["tid"]
        doc = store.read_transcript(tid)
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        by_id = {g["id"]: g for g in segs}
        used = {g["id"] for g in segs}
        n_rep, new_words, drop, spans, replaced = 0, [], set(), [], []
        for rid, old_text, a, b, lines in results:
            g = by_id.get(rid)
            if not g or g.get("proofed") is True or g.get("text") != old_text:
                continue
            drop.add(rid)
            n_rep += 1
            k = 0
            for x in lines:
                sid, k = doc_jobs._fresh_id(used, lambda n: "%s-r%d" % (rid, n), k)
                segs.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": x["raw"][:_txbase.MAX_TEXT],
                             "speaker": g.get("speaker", ""), "flag": str(x.get("flag") or "")[:100]})
            spans.append((a, b))
            if isinstance(doc.get("original"), list):
                replaced += replaced_rows(doc["original"], [(a, b)])   # 差し替える前の機械の出力(下で recognition.runs に残す。Q2)
                doc["original"] = replace_original_multi(doc["original"], a, b, lines)
            new_words.append((a, b, [w for x in lines for w in x.get("words") or []]))
        if not n_rep:
            return 0
        record_rerun(doc, spec, "redo", spans, replaced)
        store.snapshot(tid)
        doc["segments"] = sorted((g for g in segs if g["id"] not in drop), key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["redo"] = {"model": spec["model"], "rows": n_rep, "at": doc["updatedAt"]}
        store.apply_edit_cuts(tid, doc)
        store.commit(tid, doc, why="redo")
        for a, b, ws in new_words:
            try:
                replace_words(tid, a, b, ws, spec["model"])
            except OSError as e:
                _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        return n_rep


def run_redo(job):
    """疑わしい所だけ認識し直す(12 ③-2)。行ごとに、前後の余白を足した範囲を今の範囲の再認識と同じ仕組みで認識し直し、良くなったものだけ最後にまとめて置き換える。
    中止したら何も置き換えない。時間の上限(REDO_MAX_SEC)を超えたら残りの行はやめる"""
    spec = job["spec"]
    with _heavy.job_temp_wav(job, "中止しました(何も置き換えていません)", "疑わしい所の認識し直しで例外") as wav:
        doc = store.read_transcript(spec["tid"])
        src = _tools.check_source(doc.get("sourcePath"))
        targets = doc_jobs.redo_targets(doc, set(spec["ids"]))
        if not targets:
            job["segments"] = 0
            _heavy.job_done(job, spec["tid"], "完了(認識し直す行がありませんでした)")
            return
        start = _flowtx.extract_span(job, src, [{"start": a, "end": b} for _g, a, b in targets], _yschemas.num_or(doc.get("start"), 0.0) or 0.0,
                                     _yschemas.num_or(doc.get("end")), spec["boost"], wav)
        recognize_row = _flowtx.redo_recognizer(job, spec, wav, start)   # 本物ならワーカーにモデルを読む(状態 loading → running)
        t0, results, tried, timed_out = time.monotonic(), [], 0, False
        for n, (g, a, b) in enumerate(targets):
            _slots.check_cancel(job)
            if time.monotonic() - t0 > REDO_MAX_SEC:
                timed_out = True
                break
            job["phase"] = "疑わしい所を認識し直し中(%d / %d)" % (n + 1, len(targets))
            sub = dict(spec, range=[a, b])
            lines = recognize_row(sub, a, b)
            tried += 1
            ok, _why = redo_better(g, lines, spec.get("oldLp", {}).get(g["id"]))
            if ok:
                results.append((g["id"], g["text"], a, b, lines))
            job["progress"] = min(0.95, (n + 1) / len(targets))
        _slots.check_cancel(job)
        n_rep = apply_redo(spec, results)
        job["segments"], job["unsure"] = n_rep, max(0, tried - n_rep)
        _heavy.job_done(job, spec["tid"], "完了(%d か所のうち %d か所を置き換えました%s)" % (tried, n_rep, "。時間の上限で残りはやめました" if timed_out else ""))


# ---------- 再認識のジョブの本体(each・range・whole) ----------
def run_retranscribe(job):
    spec = job["spec"]
    with _heavy.job_temp_wav(job) as wav:
        doc = store.read_transcript(spec["tid"])
        src = _tools.check_source(doc.get("sourcePath"))
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        by_id = {g["id"]: g for g in doc.get("segments") or []}
        targets = sorted((by_id[i] for i in spec["ids"] if i in by_id), key=lambda g: g["start"])
        whole = spec.get("mode") == "whole"
        if not targets and not whole:
            raise _errors.ApiError("empty", "再認識する行が見つかりません(先に削除された可能性があります)", 400)
        span_src = targets + ([{"start": spec["range"][0], "end": spec["range"][1]}] if spec.get("mode") in ("range", "whole") else [])
        start = _flowtx.extract_span(job, src, span_src, start, end, spec["boost"], wav)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        if spec.get("mode") in ("range", "whole"):
            return _retranscribe_range(job, spec, doc, wav, start, whole)
        results = _retranscribe_each(job, spec, targets, wav, start)
        _slots.check_cancel(job)
        job["segments"], job["unsure"] = apply_retranscribe(spec, results)
        _heavy.job_done(job, spec["tid"])


def _retranscribe_range(job, spec, doc, wav, start, whole):
    """範囲・全体の再認識(run_retranscribe の続き。音声は取り出し済み。先頭 = 元の動画の start 秒)"""
    a, b = spec["range"]
    rec, lines = _flowtx.recognize_range(job, spec, wav, start, doc)   # 全体は区間に分けて続きから(状態 running)
    _slots.check_cancel(job)
    # 新しい認識でほぼ空だった所(元の行があった所 = 声があった所)だけ、声の検出なし・捨てる判定なしで認識し直す(4-2 の 3)
    gaps = [(max(a, g["start"] - LOOSE_PAD), min(b, g["end"] + LOOSE_PAD)) for g in plan_range(doc, spec, lines)["empty"]]
    loose = rec.loose(_yschemas.union_spans(gaps)) if gaps else []
    _slots.check_cancel(job)
    if not lines and not loose:
        _flowtx.end_whole(spec)   # 全体の認識は終わった(続きから再開するものが無い)
        raise _errors.ApiError("no_speech", "この%sからは、文字が認識されませんでした(元の行はそのままです)" % ("動画" if whole else "範囲"), 400)
    r = apply_range(spec, lines, loose)
    _flowtx.end_whole(spec)
    job["segments"], job["unsure"], job["kept"], job["emptyKept"], job["loose"] = r["lines"], r["unsure"], r["kept"], r["emptyKept"], r["loose"]
    _flowtx.note_vad(job, rec.vad)   # 声の検出を緩めてやり直していれば知らせる
    _heavy.job_done(job, spec["tid"])


def _retranscribe_each(job, spec, targets, wav, start):
    """選んだ行を 1 行ずつ認識する(run_retranscribe の each。音声は取り出し済み)。-> {行の id: (文章, 要確認の理由)}。
    本物と疑似の選び方・ワーカーでの行ごとの認識は ② flow/tx.each_lines(RS6 a-3。本物の処理 _each_real もそこ)"""
    return _flowtx.each_lines(job, spec, targets, wav, start)
