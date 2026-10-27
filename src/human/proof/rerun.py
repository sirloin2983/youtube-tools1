# -*- coding: utf-8 -*-
"""③ 人の操作の層 human/proof: 再認識(選んだ行 each・範囲 range)のジョブの本体と、文書への反映・
再認識で差し替えた機械の出力の記録(recognition.runs)。全体(whole)は文字起こしのジョブ(doc_jobs.run_job)で認識し直し、書き込みは rebuild_whole の 1 本
(校正の全体の再認識と評価用の作り直し。評価用かは引数 eval_set。10-20 ユーザー決定 = 全体の続きからと緩い条件の認識し直しは消した)。

受付は validate_rerun(POST /api/rerun)→ validate_retranscribe(行・範囲)か validate_whole(全体)。新しい行の id(_fresh_id)・用語集 glossary_of・
行を分ける文字数 split_chars_for・文字起こしの受付 validate_job は doc_jobs にあり、ここから `doc_jobs.名前` で呼ぶたびに読む(向きは rerun → doc_jobs だけ。
doc_jobs は rebuild_whole を呼ぶときだけここを読む)。
① pipeline/transcribe は直に読まない: 音声の取り出し(extract_span)・認識器とワーカーのモデル(each_lines・recognize_range)・
声の検出の知らせ(note_vad)・置換辞書の組(dict_pairs)・再認識の記録の共通項目(rerun_base)・
単語の時刻 words.json の差し替え(replace_span_words)は ② の `flow/tx`(`_flowtx.名前`)。句読点・文字数・印の文は ytt/txtext、置換辞書の当て方は ytt/dictfmt。
置き場所と元のファイルの検査は ytt の tools・ジョブの表は ② flow/jobs。
"""
import time

from ytt import errors as _errors, schemas as _yschemas, tools as _tools  # noqa: E402
from flow import jobs as _heavy  # noqa: E402
from ytt import jobs as _slots  # noqa: E402
from ytt import dictfmt as _dictfmt  # noqa: E402   置換辞書を当てる apply_replacements
from flow import tx as _flowtx  # noqa: E402   ② 再認識の動詞(extract_span・each_lines・recognize_range・note_vad・dict_pairs・rerun_base・replace_span_words)
from ytt import txbase as _txbase  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定(受付の用語集・行を分ける文字数)
from . import store  # noqa: E402   文書の読み書き・保存のロック・控え(呼ぶたびに store.名前 で読む)
from . import doc_jobs  # noqa: E402   _fresh_id・glossary_of・split_chars_for(呼ぶたびに doc_jobs.名前 で読む)
from . import layers as _layers  # noqa: E402   再認識(機械の層の差し替え・印 MACH_CHANGED)


# ---------- 再認識で差し替えた機械の出力の記録(マスタープラン Q2 = 資料の git:before-1028-cleanup:plan/line-bc-master-plan.md の Q2。original を差し替える前の分を recognition.runs に残す) ----------
MAX_RERUNS = 30             # recognition.runs に残す再認識の記録の件数(古いものから捨てる。最初の認識の記録 = kind の無いものは捨てない)
MAX_REPLACED_ROWS = 20000   # 再認識の記録の replaced の行の合計の上限(超えたら古い記録から捨てる。文書が大きくなりすぎないように)


def _replaced_rows(orig, spans, keep=()):
    """original のうち、spans のどれかに真ん中が入り、keep に入らない行(= これから差し替えられる機械の出力)。
    _replace_original・replace_original_multi と同じ決まり(真ん中で決める)"""
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
    1件 = {"kind": "each" | "range" | "whole" | "evalRedo"(⑤ eval/drill/evalbatch の評価用の作り直し), 新しい結果を出したエンジン・版・モデル・言語・設定(settings.dict = 辞書の版),
           "range": [最初, 最後], "spans"?: 行ごとの範囲(each で2つ以上のとき), "replaced": [差し替えられた original の行], "at"}。
    original の無い文書(文字起こしせずに開いた)でも、いつ・何で認識し直したかは残す(replaced は空)。pairs = 作ってある _flowtx.dict_pairs(spec)"""
    spans = [[round(float(a), 3), round(float(b), 3)] for a, b in spans]
    if not spans:
        return
    # 機械が行を書き換えるので、「動画を全部聞いて確かめた」印(評価ドリル。eval/drill/drill)も外す。行の proofed を外すのと同じ時に。
    # 再認識(each・range・whole)は、どれも差し替える前にここを通る
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


# ---------- 選んだ行の再認識の反映(行ごと = each) ----------
def _replace_original(orig, a, b, text):
    """機械の出力の記録のうち、a〜b にある分を、新しい機械の出力1件に差し替える(再認識の結果を『人が直した』と誤学習しないため)。"""
    return replace_original_multi(orig, a, b, [{"start": a, "end": b, "raw": text}])


def apply_retranscribe(spec, results):
    with store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_retranscribe(spec, results)


def _apply_retranscribe(spec, results):
    """選んだ行の再認識(each)の反映(X-RERUN。守り方は層 = 機械の層の選んだ行の区間だけを新しい機械の行に差し替え、人の層は今のまま。
    人が直した行(校正済みでなくても)は残り、覆っていた機械が変わったら組み立てが印 MACH_CHANGED を付ける = 3 択。直していない行は新しい機械の文字になる)"""
    doc = store.read_transcript(spec["tid"])
    layers0 = store.layers_for(spec["tid"], doc)   # 差し替える前の層(機械の層のファイルが無い文書は original から作るので、original を変える前に)
    pairs = _flowtx.dict_pairs(spec)
    have_orig = isinstance(doc.get("original"), list)
    orig = doc["original"] if have_orig else []
    spans = [(sg["start"], sg["end"]) for sg in doc.get("segments") or [] if results.get(sg["id"])]
    record_rerun(doc, spec, "each", spans, _replaced_rows(orig, spans), pairs)   # 差し替える前の機械の出力を残す(マスタープラン Q2)
    done = unsure = 0
    mrows = []
    for sg in doc.get("segments") or []:
        r = results.get(sg["id"])
        if not r:
            continue
        raw, flag = r
        keep = [x for x in str(sg.get("flag", "")).split("、") if x in _txbase.SPK_FLAGS]   # 話者の印は残し、文字の印は付け直す
        text, _ = _dictfmt.apply_replacements(raw[:_txbase.MAX_TEXT], pairs)
        mrows.append({"id": sg["id"], "start": sg["start"], "end": sg["end"], "text": text, "flag": _yschemas.join_flags(flag, *keep),
                      **({"speaker": sg["speaker"]} if sg.get("speaker") else {})})
        unsure += 1 if flag else 0
        done += 1
        if have_orig:
            orig = _replace_original(orig, sg["start"], sg["end"], raw)
    if have_orig:
        doc["original"] = orig
    store.backup_doc(spec["tid"], "retranscribe")
    st = _commit_rerun(spec["tid"], doc, layers0, spans, mrows, "rerun_each",
                     lambda st: {"retranscribed": dict({"model": spec["model"], "lines": done, "at": int(time.time() * 1000)},
                                                       **({"keptProofed": st["machChanged"]} if st["machChanged"] else {}))})
    return done, unsure


def _commit_rerun(tid, doc, layers0, spans, mrows, why, extra=None, empty_cover=None):
    """認識し直しの書き込み(X-RERUN の 1 か所)。doc = 書く前の文書(original・recognition.runs はもう新しくしてある)。
    layers0 = 差し替える前の (機械の層, 人の層)(store.layers_for。doc の original を変える前に取る)。機械の層の spans の中を mrows に差し替え(layers.replace_mach_span)、人の層は今のまま(差分を取り直さない = 認識し直しは人の層を変えない)で
    組み立てた文書を commit(why, mach=)する。人の層があれば hum も渡す(人の層を持たない評価用の丸ごとの作り直しは mach だけ)。
    extra(stats) -> 文書の欄(retranscribed など)。-> {組み立ての stats + replace_mach_span の数}"""
    mach0, hum0 = layers0
    if hum0 is not None:
        hum0 = dict(hum0, docFields={k: v for k, v in (hum0.get("docFields") or {}).items() if k in doc})   # record_rerun が外した文書の欄(evalReviewed)は人の層からも外す
    mach1, rep = _layers.replace_mach_span(mach0, spans, mrows, empty_cover, EMPTY_FLAG)
    rows, st = _layers.compose_rows(mach1, hum0)
    st = dict(st, **rep)
    if extra:
        doc.update(extra(st))
    doc["updatedAt"] = int(time.time() * 1000)
    meta = _layers.split_meta(doc)
    if hum0 is None:   # 人の層を持たない(評価用の丸ごとの作り直し): 文書の欄(evalSet など)は文書から
        meta.update({k: doc[k] for k in _layers.DOC_FIELDS if k in doc})
    new = _layers.compose(mach1, hum0, meta, rows)
    store.apply_edit_cuts(tid, new)   # 差し替えた行の「カット済」は、編集の内容(時刻)から付け直す
    if hum0 is not None:
        store.commit(tid, new, why=why, mach=mach1, hum=hum0)
    else:
        store.commit(tid, new, why=why, mach=mach1)
    return st


def _in_spans(t, spans):
    return any(p0 <= t <= p1 for p0, p1 in spans)


def replace_original_multi(orig, a, b, items, keep=()):
    """機械の出力の記録のうち、a〜b にある分を新しい機械の出力に差し替える。keep の区間(校正済み・元のまま残した行)にある分は古いまま残す"""
    keep_o = [o for o in orig if not (a <= (o["start"] + o["end"]) / 2 <= b) or _in_spans((o["start"] + o["end"]) / 2, keep)]
    keep_o += [{"start": x["start"], "end": x["end"], "text": x["raw"][:_txbase.MAX_TEXT], **(x.get("conf") or {})} for x in items]
    keep_o.sort(key=lambda o: o["start"])
    return keep_o


# ---------- 範囲・全体の再認識の反映 ----------
EMPTY_COVER = 0.3       # 機械の行の時間のうち、新しい行が重なるのがこの割合未満なら「新しい認識でほぼ空」→ 元の機械の行を印つきで残す
LOOSE_PAD = 0.5         # ほぼ空だった所を緩い条件で認識し直すときの前後の余白(秒)
EMPTY_FLAG = _yschemas.EMPTY_FLAG
LOOSE_FLAG = "声が重なる所などを緩い条件で認識"


def _ov(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def thin_rows(doc, a, b, lines):
    """範囲 a〜b の文字のある文書の行のうち、新しい行 lines が時間の EMPTY_COVER 未満しか重ならない行(新しい認識でほぼ空 = 緩い条件で認識し直す所)"""
    out = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict) or not str(g.get("text") or "").strip() or _ov(g["start"], g["end"], a, b) <= 0:
            continue
        d = g["end"] - g["start"]
        cover = sum(_ov(g["start"], g["end"], x["start"], x["end"]) for x in lines) / d if d > 0 else 1.0
        if cover < EMPTY_COVER:
            out.append(g)
    return out


def apply_range(spec, lines, loose=()):
    """範囲を新しく認識した行に差し替える(X-RERUN。守り方は層 = 機械の層の a〜b の行だけを差し替え、人の行は残る)。
    lines=[{start,end,raw,flag,words?,conf?}]、loose = ほぼ空だった所を緩い条件で認識した行(印を付けて入れる)。
    新しい認識でほぼ空だった機械の行は印 EMPTY_FLAG を付けて残す。話者は時間が最も重なっていた前の機械の行から。
    -> {"lines": 入れた新しい行の数, "unsure", "kept": 機械が変わって 3 択になった人の行の数, "emptyKept": 元のまま残した機械の行の数, "loose": 緩い条件の行の数}"""
    with store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_range(spec, lines, loose)


def _apply_range(spec, lines, loose=()):
    a, b = spec["range"]
    tid = spec["tid"]
    doc = store.read_transcript(tid)
    pairs = _flowtx.dict_pairs(spec)
    loose = [dict(x, flag=_yschemas.join_flags(LOOSE_FLAG, x.get("flag", ""))) for x in loose]
    new_lines = sorted(list(lines) + loose, key=lambda x: x["start"])
    used = {g["id"] for g in doc.get("segments") or []}
    mrows, unsure, n = [], 0, 0
    for x in new_lines:
        text, _ = _dictfmt.apply_replacements(x["raw"][:_txbase.MAX_TEXT], pairs)
        sid, n = doc_jobs._fresh_id(used, "r%d".__mod__, n)
        mrows.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": text, "flag": _yschemas.join_flags(x.get("flag", ""))})
        unsure += 1 if x.get("flag") else 0
    # 元のまま残す機械の行(ほぼ空)の original・単語は古いまま(下の replace の keep)。数え方は replace_mach_span と同じ
    layers0 = store.layers_for(tid, doc)
    mach0 = layers0[0]
    keep_spans = _layers.replace_mach_span(mach0, [(a, b)], mrows, EMPTY_COVER)[1]["emptySpans"]
    record_rerun(doc, spec, "range", [(a, b)],
                 _replaced_rows(doc.get("original") if isinstance(doc.get("original"), list) else [], [(a, b)], keep_spans), pairs)   # 差し替える前の機械の出力を残す(Q2)
    if isinstance(doc.get("original"), list):   # 元のまま残した機械の行の出力は古いまま
        doc["original"] = replace_original_multi(doc["original"], a, b, new_lines, keep_spans)
    store.backup_doc(tid, "retranscribe")
    n_loose = sum(1 for x in new_lines if _yschemas.has_flag(x.get("flag"), LOOSE_FLAG))
    st = _commit_rerun(tid, doc, layers0, [(a, b)], mrows, "rerun_range",
                     lambda st: {"retranscribed": {"model": spec["model"], "lines": len(mrows), "range": [a, b], "whole": False,
                                                   "kept": st["machChanged"], "emptyKept": st["emptyKept"], "loose": n_loose, "at": int(time.time() * 1000)}},
                     EMPTY_COVER)
    try:   # 単語の時刻も範囲の分を差し替える(元のまま残した行の単語は残す。古い文書は、ここで取り直せる = 「今の文書を分け直す」の案内)
        _flowtx.replace_span_words(tid, a, b, [w for x in new_lines for w in x.get("words") or []], spec["model"], keep_spans)
    except OSError as e:
        _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
    return {"lines": len(mrows), "unsure": unsure, "kept": st["machChanged"], "emptyKept": st["emptyKept"], "loose": n_loose}


# ---------- 再認識のジョブの本体(each・range) ----------
def run_retranscribe(job):
    spec = job["spec"]
    if spec.get("redo"):   # 校正の全体の再認識(validate_whole): 文字起こし 1 本 → rebuild_whole(eval_set=False)。種類は retranscribe のまま = 同じ文書の排他(DOC_LOCK)
        return doc_jobs.run_transcribe_job(job)
    with _heavy.job_temp_wav(job) as wav:
        doc = store.read_transcript(spec["tid"])
        src = _tools.check_source(doc.get("sourcePath"))
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        by_id = {g["id"]: g for g in doc.get("segments") or []}
        targets = sorted((by_id[i] for i in spec["ids"] if i in by_id), key=lambda g: g["start"])
        if not targets:
            raise _errors.ApiError("empty", "再認識する行が見つかりません(先に削除された可能性があります)", 400)
        rng = spec.get("mode") == "range"
        span_src = targets + ([{"start": spec["range"][0], "end": spec["range"][1]}] if rng else [])
        start = _flowtx.extract_span(job, src, span_src, start, end, spec["boost"], wav)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        if rng:
            return _retranscribe_range(job, spec, doc, wav, start)
        results = _retranscribe_each(job, spec, targets, wav, start)
        _slots.check_cancel(job)
        job["segments"], job["unsure"] = apply_retranscribe(spec, results)
        _heavy.job_done(job, spec["tid"])


def _retranscribe_range(job, spec, doc, wav, start):
    """範囲の再認識(run_retranscribe の続き。音声は取り出し済み。先頭 = 元の動画の start 秒)"""
    a, b = spec["range"]
    rec, lines = _flowtx.recognize_range(job, spec, wav, start, doc)   # 状態 running
    _slots.check_cancel(job)
    # 新しい認識でほぼ空だった所(元の行があった所 = 声があった所)だけ、声の検出なし・捨てる判定なしで認識し直す
    gaps = [(max(a, g["start"] - LOOSE_PAD), min(b, g["end"] + LOOSE_PAD)) for g in thin_rows(doc, a, b, lines)]
    loose = rec.loose(_yschemas.union_spans(gaps)) if gaps else []
    _slots.check_cancel(job)
    if not lines and not loose:
        raise _errors.ApiError("no_speech", "この範囲からは、文字が認識されませんでした(元の行はそのままです)", 400)
    r = apply_range(spec, lines, loose)
    job["segments"], job["unsure"], job["kept"], job["emptyKept"], job["loose"] = r["lines"], r["unsure"], r["kept"], r["emptyKept"], r["loose"]
    _flowtx.note_vad(job, rec.vad)   # 声の検出を緩めてやり直していれば知らせる
    _heavy.job_done(job, spec["tid"])


def _retranscribe_each(job, spec, targets, wav, start):
    """選んだ行を 1 行ずつ認識する(run_retranscribe の each。音声は取り出し済み)。-> {行の id: (文章, 要確認の理由)}。
    本物と疑似の選び方・ワーカーでの行ごとの認識は ② flow/tx.each_lines(本物の処理 _each_real もそこ)"""
    return _flowtx.each_lines(job, spec, targets, wav, start)

# ---------- 全体の作り直しの書き込み(X-RERUN = 全体 × いつものエンジン × 差し替え。ユーザー決定 Q-A・10-19 ③ の統合 Q6 = 全体は 1 本) ----------
def rebuild_whole(job, spec, fields, eval_set=True):
    """文書の全体を新しい認識に入れ替える書き込みの 1 本(doc_jobs.run_job の文字起こしの結果 fields を、同じ文書 spec["tid"] へ)。
    評価用かは eval_set で分ける。-> 文書の id か None(書かなかった)。
    機械の層を新しい認識に入れ替え、人の層(人が直した行・校正済みの行・音のメモ・人が付けた話者)は残す。前の状態は履歴に 1 つ(store.snapshot)。
    書かない: 文書が消えた・動画が変わった(ジョブは「…しませんでした」で終わる)。新しい最初の認識の記録を runs の先頭に。
    eval_set=True(評価用の作り直し。spec["evalRedo"]): 入れたときに「手つかず」で(evalRedo.machineOnly)、そのあと文書が変わっていなければ
      (updatedAt が base のまま)人の層も持たない = 丸ごと入れ替える。前の機械の出力は kind "evalRedo"(replaced = 前の original・
      replacedRun = 前の最初の認識の記録)。話者の判別の記録・確かめ済み・分け直しの印は外す(話者は run_job の続きの自動の判別がもう一度付ける)。
    eval_set=False(校正の全体の再認識。spec["redo"] = validate_whole): **人の層はいつも残す**(machineOnly は見ない)。
      新しい認識でほぼ空だった機械の行は印 EMPTY_FLAG を付けて残す。前の機械の出力は kind "whole"。話者は前の機械の行から(判別の記録は残す)。
      確かめ済み・分け直しの印は外す。文書の retranscribed と、ジョブの kept・emptyKept(画面の知らせ)。
      夜の古い版の作り直し(spec["redo"]["refresh"]。validate_whole の refresh): 入れたあとに文書が変わっていれば書かない・retranscribed に refresh"""
    tid = str(spec.get("tid") or spec.get("intoDoc") or "")
    red = spec.get("evalRedo") if isinstance(spec.get("evalRedo"), dict) else {}
    what = "作り直し" if eval_set else "全体を再認識し"
    with store._save_lock:
        try:
            doc = store.read_transcript(tid)
        except _errors.ApiError as e:
            job["redoSkipped"] = e.code
            _heavy.job_done(job, tid, "%sませんでした(文書がありません)" % what)
            return None
        if _fsio_norm(doc.get("sourcePath")) != _fsio_norm(spec.get("sourcePath")):
            job["redoSkipped"] = "moved"
            _heavy.job_done(job, tid, "%sませんでした(動画が変わっていました)" % what)
            return None
        refresh = not eval_set and isinstance(spec.get("redo"), dict) and spec["redo"].get("refresh") is True
        if refresh and doc.get("updatedAt") != spec["redo"].get("base"):   # 夜の作り直し: 入れたあとに人が直した文書は書かない(次の夜にもう一度選ばれる)
            job["redoSkipped"] = "changed"
            _heavy.job_done(job, tid, "%sませんでした(作り直しの間に直されました)" % what)
            return None
        machine_only = eval_set and red.get("machineOnly") is True and doc.get("updatedAt") == red.get("base")
        segs = list(fields.get("segments") or [])
        if not eval_set and not segs:   # 前の全体の再認識と同じ: 文字が出なければ文書に触らない
            raise _errors.ApiError("no_speech", "この動画からは、文字が認識されませんでした(元の行はそのままです)", 400)
        layers0 = store.layers_for(tid, doc)
        if machine_only:
            layers0 = (layers0[0], None)
        store.snapshot(tid)   # 作り直す前を「以前の版に戻す」に残す
        old_rec = doc.get("recognition") if isinstance(doc.get("recognition"), dict) else {}
        old_first = [r for r in old_rec.get("runs") or [] if isinstance(r, dict) and not r.get("kind")]
        a = float(spec.get("start") or 0)
        b = _yschemas.num_or(spec.get("end")) or _yschemas.num_or(spec.get("duration")) or max(
            [_yschemas.num_or(o.get("end"), 0.0) or 0.0 for o in doc.get("original") or [] if isinstance(o, dict)] + [a + 0.01])
        kind = "evalRedo" if eval_set else "whole"
        old_orig = [dict(o) for o in doc.get("original") or [] if isinstance(o, dict)]
        keep = [] if eval_set else _layers.replace_mach_span(layers0[0], [(-1e18, 1e18)], segs, EMPTY_COVER)[1]["emptySpans"]   # 元のまま残す機械の行の区間
        record_rerun(doc, spec, kind, [[a, max(b, a + 0.01)]], _replaced_rows(old_orig, [(-1e18, 1e18)], keep) if keep else old_orig)
        runs = doc["recognition"]["runs"]
        if old_first and runs and runs[-1].get("kind") == kind:
            runs[-1]["replacedRun"] = old_first[0]
        doc.update({k: v for k, v in fields.items() if k not in ("segments", "speakers")})
        if keep:   # 元のまま残した機械の行の出力は古いまま(前の apply_range と同じ)・単語も残す(run_job の write_clip_records)
            doc["original"] = sorted([o for o in old_orig if _kept(o, keep)] +
                                     [o for o in doc.get("original") or [] if isinstance(o, dict) and not _kept(o, keep)], key=lambda o: o.get("start") or 0)
            job["keepSpans"] = [list(p) for p in keep]
        doc["recognition"] = dict(old_rec, runs=list((fields.get("recognition") or {}).get("runs") or []) + [r for r in runs if r.get("kind")])
        for k in ("diarization", "evalReviewed", "resplit") if eval_set else ("evalReviewed", "resplit"):
            doc.pop(k, None)
        if eval_set:
            doc["evalSet"] = True
            _commit_rerun(tid, doc, layers0, [(-1e18, 1e18)], segs, "eval_rebuild")
        else:
            st = _commit_rerun(tid, doc, layers0, [(-1e18, 1e18)], segs, "rerun_range",
                               lambda st: {"retranscribed": dict({"model": spec["model"], "lines": len(segs), "range": [a, b], "whole": True,
                                                                  "kept": st["machChanged"], "emptyKept": st["emptyKept"], "at": int(time.time() * 1000)},
                                                                 **({"refresh": True} if refresh else {}))},
                               EMPTY_COVER)
            job["segments"], job["kept"], job["emptyKept"] = len(segs), st["machChanged"], st["emptyKept"]
    _txbase.log.info("%s: %s(%d 行%s)", "評価用の文書を作り直しました" if eval_set else "文書の全体を再認識しました", tid, len(segs),
                     "" if machine_only else "・人の層は残した")
    return tid


def _kept(o, spans):
    """original の行の真ん中が spans(元のまま残した機械の行の区間)に入るか(時刻が読めなければ入らない)"""
    try:
        return _in_spans((float(o["start"]) + float(o["end"])) / 2, spans)
    except (KeyError, TypeError, ValueError):
        return False


def _fsio_norm(p):
    from ytt import fsio
    return fsio.norm_path(str(p or ""))


# ---------- 再認識の受付(選んだ行 each・範囲 range。10-19 ③ の統合で doc_jobs から移した)と全体の受付 validate_whole ----------
MAX_RANGE_SEC = 900


def validate_retranscribe(req):
    tid = str(req.get("tid") or "")
    doc = store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    _tools.check_source(doc.get("sourcePath"))   # 元の動画が無ければ断る
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    mode = "range" if req.get("mode") == "range" else "each"
    if not ids:
        raise _errors.ApiError("empty", "再認識する行がありません", 400)
    model = _flowtx.check_model(str(req.get("model") or "large-v3").strip())
    lang = str(req.get("language") or doc.get("language") or "ja")
    st = _settings.load_settings()   # 自動の用語と行を分ける文字数で 1 回だけ読む
    glossary, gauto = doc_jobs.glossary_of(req, st)
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["retranscribe"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    rng = None
    segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
    if mode == "range":   # 選んだ行の最初〜最後を、ひとまとまりの音声として認識し直す(間にある選んでいない行も含む)
        chosen = [g for g in segs if g["id"] in set(ids)]
        a, b = min(g["start"] for g in chosen), max(g["end"] for g in chosen)
        ids = [g["id"] for g in segs if a - 1e-6 <= (g["start"] + g["end"]) / 2 <= b + 1e-6]
        if b - a > MAX_RANGE_SEC:
            raise _errors.ApiError("too_long", "範囲が長すぎます(最大%d分)。範囲を狭めてください" % (MAX_RANGE_SEC // 60), 400)
        rng = [a, b]
    engine, ctx = _flowtx.request_engine(req, model, doc, req.get("autoContext") is True)
    return {"tid": tid, "ids": ids, "mode": mode, "range": rng, "model": model, "engine": engine, "language": lang if lang in _txbase.LANGS else "ja", "beam": 5,
            "vadMode": req.get("vadMode") if mode == "range" and req.get("vadMode") in ("weak", "normal", "off") else "off",
            "wordSplit": mode == "range" and req.get("wordSplit") is not False, "splitChars": doc_jobs.split_chars_for(req, st),
            "stripPunct": req.get("stripPunct") is not False, "stripNames": st.get("stripNames") is not False,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto", "boost": req.get("boost") is True,
            "autoDict": req.get("autoDict") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx,
            "title": _heavy.job_title("範囲を再認識: " if mode == "range" else "再認識: ", doc)}


def validate_whole(req):
    """校正の全体の再認識の受付(target whole)-> 文字起こしの spec(doc_jobs.validate_job。同じ文書へ入れ直す = intoDoc・tid・redo。
    書き込みは doc_jobs.run_job → rebuild_whole(eval_set=False) = 人の行・校正済みの行は残る)。文書の範囲(全体でない文書は start〜end)を、
    今の文字起こしの設定(要求の認識の設定が勝つ)で認識する。声の検出は「弱め」から(抜けを拾うのが目的。明示の「なし」だけは尊重)。
    2 つ目のエンジンの自動の聞き直し(autoAlt)はしない。断る: 評価用(400 eval_set)・処理中(409 busy)・動画が無い・6 時間を超える(validate_job)"""
    tid = str(req.get("tid") or "")
    doc = store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["retranscribe"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    q = {k: v for k, v in req.items() if k not in ("tid", "id", "ids", "mode", "target", "result", "intoDoc", "start", "end", "title", "evalSet")}
    if q.get("engine") in RERUN_ENGINES:   # 受付の「いつものエンジン」の印(認識のエンジンの名前ではない)
        q.pop("engine")
    q.update(sourcePath=doc.get("sourcePath"), vadMode="off" if req.get("vadMode") == "off" else "weak")
    if not doc.get("whole"):
        q.update(start=_yschemas.num_or(doc.get("start"), 0.0) or 0.0, end=_yschemas.num_or(doc.get("end")))
    spec = doc_jobs.validate_job(q)
    spec.update(intoDoc=tid, tid=tid, autoAlt=False, redo={"base": doc.get("updatedAt")}, title=_heavy.job_title("全体を再認識: ", doc))
    if req.get("refresh") is True:   # 夜の古い版の作り直し(app/check/refresh): 空いているときだけ動く級・文書の印・入れたあとに直された文書は書かない
        spec.update(prio="later", redo=dict(spec["redo"], refresh=True), title=_heavy.job_title("古い版を作り直し: ", doc))
    return spec


# ---------- 認識し直しの受付を 1 つに(X-RERUN。ユーザー決定 = 対象 × エンジン × 結果の扱い) ----------
RERUN_TARGETS = ("rows", "span", "whole", "flagged")   # 選んだ行・選んだ行の最初〜最後の範囲・文書の全体・印の付いた所(疑わしい行 = doc_jobs.redo_targets)
RERUN_ENGINES = ("main", "alt")                         # いつものエンジン(文書の設定)・2 つ目のエンジン(alt)
RERUN_RESULTS = ("replace", "propose")                  # 機械の結果を差し替える(機械の層だけ。人の行は残る)・候補として出す(文書は書かない)


def validate_rerun(req):
    """POST /api/rerun {tid, target, engine, result, ids?, 認識の設定(model・language・vadMode…)} -> (spec, ジョブの種類)。
    決まった組だけ受ける: いつものエンジン × 差し替える(rows = 行ごと・span = 範囲・whole = 全体・flagged = 印の付いた行ごと)/
    2 つ目のエンジン × 候補(whole だけ。<id>.alt.json に書く)。2 つ目のエンジンで差し替える・いつものエンジンで候補 は断る(400 bad_combo)。
    評価用の文書は断る(評価用の作り直しは ⑤ の見回りが全体を入れ直す道だけ = ユーザー決定 Q-A)"""
    req = req if isinstance(req, dict) else {}
    target = req.get("target") if req.get("target") in RERUN_TARGETS else "rows"
    engine = req.get("engine") if req.get("engine") in RERUN_ENGINES else "main"
    result = req.get("result") if req.get("result") in RERUN_RESULTS else ("propose" if engine == "alt" else "replace")
    tid = str(req.get("tid") or req.get("id") or "")
    if engine == "alt":
        if result != "propose":
            raise _errors.ApiError("bad_combo", "2 つ目のエンジンの結果は候補として出すだけです(文書は差し替えません)", 400)
        if target != "whole":
            raise _errors.ApiError("bad_combo", "2 つ目のエンジンで聞くのは、今は文書の全体だけです", 400)
        from . import alt as _alt   # alt は doc_jobs を読む(向き: rerun → alt → doc_jobs)
        return _alt.alt_spec(tid, dict(req, engine=req.get("altEngine") or req.get("engineKey"))), "alt"
    if result != "replace":
        raise _errors.ApiError("bad_combo", "いつものエンジンの結果は機械の結果を差し替えます(候補として出すのは 2 つ目のエンジンだけ)", 400)
    if target == "whole":
        return validate_whole(dict(req, tid=tid)), "retranscribe"   # 排他は前と同じ DOC_LOCK(flow/wire)
    mode = {"rows": "each", "span": "range", "flagged": "each"}[target]
    ids = req.get("ids")
    if target == "flagged":
        doc = store.read_transcript(tid)
        ids = [g["id"] for g, _a, _b in doc_jobs.redo_targets(doc)]
        if not ids:
            raise _errors.ApiError("empty", "印の付いた(疑わしい)行がありません", 400)
    return validate_retranscribe(dict(req, tid=tid, ids=ids, mode=mode)), "retranscribe"
