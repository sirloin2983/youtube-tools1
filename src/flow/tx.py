# -*- coding: utf-8 -*-
"""② 管理の層 flow: 文字起こしの動詞。RS6 a-3(決定 3-29)。

③ 人(human/proof の doc_jobs・rerun・alt・retime・learn)は ① pipeline/transcribe を直に読まず、ここの動詞を呼ぶ。動詞は ① を呼ぶ前後で ② の責任
(本物と疑似の選び方と本物の処理 = ワーカーでモデルを読む・ジョブの状態・認識の記録 words.json・asr.json・llm.json の書き込み・学習データ(置換辞書と名簿)の読み・
文書の機械の分 fields の組み立て)を足す。① の別名だけの関数は作らない(tests/dev/test_layering.py の test_flow_is_not_alias)。変換のコードは ① に置く。
純粋な文字の関数(行を分ける・句読点・印の文・用語の区切り・置換辞書の読み方と当て方)は ytt(txtext・dictfmt)にあり、③ はそれを直に読む。

動詞(それぞれの docstring に「② が足すこと」):
  文字起こし    transcribe_clip(① clipjob → fields)・write_clip_records(words・asr・llm を書く)・write_machine_doc(③ なしで文書の機械の分を書く)・dict_pairs
  受付          check_model・request_engine・tx_spec(文字起こしの指定。③ の validate_job も使う)・new_doc(新しい文書の頭。③ の run_job も使う)
  再認識        extract_span・each_lines・recognize_range・note_vad・replace_span_words(words.json の差し替え)
  2 つ目のエンジン engine_ready・check_engine_ready・alt_lines(+ alt_engine_version)
  時刻の候補    word_retime
  名簿と学習    roster_listing・pick_glossary_terms
① の名前は呼ぶたびに `モジュール.名前` で読む(差し替えが届く)。
ジョブの表は兄弟の flow/jobs、枠と取り消しの確かめ(check_cancel・Cancelled)は ytt/jobs(_slots)。
"""
import json
import os
import time

from ytt import dictfmt as _dictfmt, docloc as _docloc, errors as _errors, fsio as _fsio, jobs as _slots, schemas as _yschemas, settings as _settings
from ytt import tools as _tools, txbase as _txbase, txtext as _txtext, txwords as _txwords, workdata as _workdata
from pipeline.transcribe import backend as _backend, clipjob, llm, postproc, recognize, records, roster as _roster, tx_engines, worker_client
from pipeline.transcribe import replace as _replace
from pipeline.transcribe import retime as _retime

from . import keys as _keys, machine as _machine


# ---------- 学習データ(置換辞書と名簿)----------
def dict_pairs(spec):
    """置換辞書の組 [(誤, 正)](autoDict のときだけ。評価用の文書は autoDict が外れるので当たらない)= 設定の replacements + 名簿の呼び名の表記ゆれ(roster.variant_pairs。
    はーちゃま → はあちゃま・ラミー → ラミィ・吹雪 → フブキ。確かめ済み 22 本で名前の再現率 28 → 40/53・普段の文書 1045 行で変わる行 0 = notes:plan/line-b-transcription.md の実験ループ B)。
    設定の組が先(ユーザーの辞書が名簿の表より強い)。名簿が読めなければ設定の組だけ。
    ② が足すこと = 学習データ(設定の辞書と名簿のファイル)を読んで ① の表記ゆれの表と合わせる(RS6 a-3)"""
    if not spec.get("autoDict"):
        return []
    # 人の置換辞書はオフ(ytt/dictfmt.USER_DICT。ユーザー指示)= 名簿の表だけ
    pairs = _dictfmt.parse_replacements(_settings.load_settings().get("replacements")) if _dictfmt.USER_DICT else []
    try:
        pairs += _roster.variant_pairs(_roster.load(_roster.ROSTER))
    except (OSError, ValueError, TypeError, KeyError) as e:   # 名簿の表は補助なので、作れなくても認識は止めない
        _txbase.log.warning("名簿の表記ゆれの表を作れませんでした: %s", e)
    return pairs


def rerun_base(spec, pairs, kind):
    """再認識の記録(recognition.runs の 1 件)の共通項目: ① records の共通項目(エンジンと版・モデル・設定・辞書の版・後処理)に kind・機器・autoDict を足したもの。
    ② が足すこと = 再認識の記録だけの項目(どの機器で・辞書を使ったか)。range・replaced などは ③ の record_rerun が足す(RS6 a-5b に human/proof/rerun から)。
    pairs = 作ってある dict_pairs(spec)(設定と名簿を読み直さない)"""
    run = dict(records._run_base(spec, pairs), kind=kind, device=str(spec.get("device") or ""))
    run["settings"]["autoDict"] = bool(spec.get("autoDict"))
    return run


def roster_listing():
    """名簿の画面向けの中身 {asOf, note, groups: [{id, label, names}]}(③ の learn.load_roster = GET /api/roster)。読めない・形が違うときは空。BOM 付きでも読む。
    ② が足すこと = 学習データの置き場所(① roster.ROSTER)から読み、groups は ① roster.load の整え方(認識と同じ検査)に、ファイルの asOf・note を添える"""
    if not _roster.ROSTER:
        return {"asOf": "", "note": "", "groups": []}
    d = _fsio.read_json_or(_roster.ROSTER, None, kind=dict) or {}
    return {"asOf": str(d.get("asOf") or "")[:20], "note": str(d.get("note") or "")[:400],
            "groups": [dict(g, names=list(g["names"])) for g in _roster.load(_roster.ROSTER)["groups"]]}


def pick_glossary_terms(user_terms, ranked, limit=150):   # flow: alias ok(③ は ① を読めない。選び方の正は ① replace.pick_glossary = 友人の PC と同じ)
    """③ の learn.auto_glossary が順位を付けた語 ranked から、認識のヒントに足す語を選ぶ(① replace.pick_glossary)"""
    return _replace.pick_glossary(user_terms, ranked, limit)


# ---------- 受付 ----------
def check_model(model, fallback=None):
    """③ の受付のモデル名の確かめ(① worker_client.valid_model)。② が足すこと = 使えない名前を fallback に替えるか、無ければ ApiError bad_model"""
    if worker_client.valid_model(model):
        return model
    if fallback is not None:
        return fallback
    raise _errors.ApiError("bad_model", "モデル名が正しくありません", 400)


def request_engine(req, model, ctx_doc, auto_context):
    """③ の受付が spec に入れる認識の値 -> (エンジン, 配信ごとの文脈)。エンジンは ① worker_client.req_engine(使えない組は ApiError)・
    文脈は ① roster.stream_context(ctx_doc = clip・title・sourceName・sourcePath・speakers を持つ辞書)。
    ② が足すこと = 2 つを受付の 1 か所で組む(文脈の材料 = スタジオの data.json と名簿は ② が置き場所を知る学習データ)"""
    ctx = _roster.stream_context(ctx_doc, auto_context)
    return worker_client.req_engine(req, model), ctx


def tx_spec(req, post, learning=None, *, src=None, dur=None):
    """要求と後処理の値 post -> 文字起こしのジョブの指定(動画 1 本を頭から終わりまで。評価用・入れる文書・2 つ目のエンジン・話者の自動の判別・LLM のモデルは入れない)。
    ② の CLI(flow/tools の transcribe_start)と ③ の受付(human/proof/doc_jobs の validate_job)が同じ形を使う = ③ は返した指定に自分の分(範囲・入れる文書・評価用・
    2 つ目のエンジン・話者・LLM のモデル)を重ねる。post = 束の post の形(splitChars・autoFill・autoLlm・stripNames・autoLearned・autoContext・
    autoGloss・learning.version)。learning = 学習データの読み手(ユーザーの用語が先・自動の用語はその後ろ。無ければ自動の用語は入れない)。
    src・dur = 検査済みの動画のパスと長さ(③ が先に範囲を確かめるとき。無ければここで check_source・media_duration)。
    機器は auto・cuda・cpu・vulkan。要求の title(120 字まで)があれば題名に(無ければ動画のファイル名)"""
    if src is None:
        src = _tools.check_source(req.get("sourcePath"))
        dur = _tools.media_duration(src)
    clip, clip_warn, _clip_path = _yschemas.find_clip(src, dur)
    title = str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]
    model = check_model(str(req.get("model") or "large-v3").strip())
    lang = req.get("language") if req.get("language") in _txbase.LANGS else "ja"
    glossary = _txtext.split_terms(req.get("glossary"))[:200]
    gauto = list(learning.glossary(glossary)) if learning is not None and post.get("autoGloss") is not False else []
    engine, ctx = request_engine(req, model, {"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src}, post["autoContext"])
    audio = _tools.check_source(req["audioPath"]) if req.get("audioPath") else None   # 音だけ先に作った物(② の 30fps の作り直しと並べるとき。無ければ動画から)
    return {"sourcePath": src, "sourceName": os.path.basename(src), **({"audioPath": audio} if audio else {}),
            "start": 0.0, "end": round(dur, 2) if dur else None, "intoDoc": None,
            "duration": dur, "whole": True, "model": model, "engine": engine, "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
            "device": req.get("device") if req.get("device") in ("auto", "cuda", "cpu", "vulkan") else "auto",
            "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else "weak",
            "boost": req.get("boost") is True, "autoDict": req.get("autoDict") is not False, "wordSplit": req.get("wordSplit") is not False,
            "splitChars": post["splitChars"], "autoAlt": False,
            "autoFill": post["autoFill"], "autoLlm": post["autoLlm"], "stripNames": post["stripNames"], "dropSilent": post.get("dropSilent") is True, "endSnap": post.get("endSnap") is True,
            "stripPunct": req.get("stripPunct") is not False, "glossary": glossary + gauto, "glossAuto": gauto,
            "learningVersion": post["learning"]["version"], "context": ctx, "evalSet": False, "autoLearned": post["autoLearned"], "clip": clip,
            "warnings": [clip_warn] if clip_warn else [], "title": title}


def new_doc(tid, fields, spec=None):
    """新しい文字起こしの文書の頭: schema・id・題名・動画(spec があれば。title・sourcePath・sourceName)+ fields(transcribe_clip の "fields")+ 作った日
    (fields の updatedAt。無ければ今)+ clip・評価用の印(spec にあれば)。③ の文字起こし(doc_jobs の run_job)と ② の write_machine_doc が同じ形で作る"""
    doc = {"schema": "transcribe/v1", "id": tid}
    if spec:
        doc.update({"title": spec.get("title") or "", "sourcePath": spec.get("sourcePath") or "", "sourceName": spec.get("sourceName") or ""})
    doc.update(fields)
    doc["createdAt"] = fields.get("updatedAt") or int(time.time() * 1000)
    if spec and spec.get("clip"):
        doc["clip"] = spec["clip"]   # youtube-tools-clip/v1 の中身そのもの(transcript/v1 にもそのまま入る)
    if spec and spec.get("evalSet"):
        doc["evalSet"] = True
    return doc


# ---------- 文字起こし ----------
def transcribe_clip(job, spec, wav, pairs, learned=None):
    """文字起こしのジョブの機械の分(wav = 呼ぶ側の一時ファイル)。① clipjob.make_doc_rows の結果に "fields"(文書の機械の分)を足して返す。
    ② が足すこと = 文書の機械の分 fields(original・recognition.runs の最初の記録・params・辞書の版)と、後処理の記録(fill・names・llm)を runs に入れる・
    声の検出をやり直した知らせ(spec の warnings・job の vadNote)・LLM の後処理のモデル(要求に無ければこの PC の設定 flow/machine.py で決めた値。RS7-1 S1)。
    ファイルは書かない(③ が文書の id を決めてから write_clip_records)"""
    if not spec.get("llmModel"):
        m = _machine.overlay_llm()   # 決めた値か VRAM で決まる既定が今の既定(llm.LLM_MODEL)と違うときだけ = machine.json が無く VRAM 10GB 以上・不明なら今と同じ指定(F1 F0-2)
        if m:
            spec["llmModel"] = m
    res = clipjob.make_doc_rows(job, spec, wav, pairs, learned)
    fields = _doc_fields(job, spec, res, res["total"], res["t_rec"], pairs)
    run = fields["recognition"]["runs"][-1]
    if res.get("secs"):
        run["secs"] = res["secs"]   # 段ごとの秒(認識・後処理の埋める・LLM。wallSec の内訳)
    if res["fill_rec"]:
        run["fill"] = res["fill_rec"]   # 後処理の記録(読んだ窓・置き換えた行・捨てた行・直した呼び名)
    if res["names_n"]:
        run["names"] = res["names_n"]   # 話者名を外した行の数(B)
    if res["llm_rec"]:
        run["llm"] = res["llm_rec"]   # LLM の後処理の記録(選んだ所・案・当てた数・断った理由)
    return dict(res, fields=fields)


def _doc_fields(job, spec, out, total, t_rec, pairs=None):
    """新しい文字起こしの文書の中身(id・題名・動画・作った日・clip・評価用の印は除く)。recognition.runs の最初の記録・params(その時の辞書の版 dict。Q2)。
    声の検出をやり直していれば、その知らせを spec の warnings と job の vadNote に(RS6 a-3)"""
    now = int(time.time() * 1000)
    params = {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": spec["boost"], "device": job.get("device", ""), "glossary": spec["glossary"][:50],
              "autoDict": bool(spec.get("autoDict")), "dictApplied": out["dictApplied"], "wordSplit": bool(spec.get("wordSplit")),
              "splitChars": spec.get("splitChars"), "stripPunct": spec.get("stripPunct", True) is not False,
              "autoLearned": bool(spec.get("autoLearned")), "learnApplied": out["learnApplied"], "glossAuto": spec.get("glossAuto", [])[:20],
              "context": records.context_record(spec), "autoFill": bool(spec.get("autoFill")), "autoLlm": bool(spec.get("autoLlm")),
              "stripNames": bool(spec.get("stripNames")), "dropSilent": bool(spec.get("dropSilent")), "endSnap": bool(spec.get("endSnap"))}
    fields = {"start": spec["start"], "end": spec["end"], "whole": spec["whole"], "duration": spec["duration"], "model": spec["model"],
              "language": spec["language"], "params": params, "speakers": [], "segments": out["segs"], "original": out["original"], "updatedAt": now,
              "recognition": {"runs": [records.recognition_run(spec, job, total, time.monotonic() - t_rec, pairs)]}}
    params["dict"] = fields["recognition"]["runs"][0]["settings"]["dict"]
    if job.get("vad"):
        params["vadUsed"] = job["vad"].get("used")
        note = recognize.vad_note(job["vad"])
        if note:
            _txbase.add_warning(spec, note)
            job["vadNote"] = note
    return fields


def write_clip_records(tid, clip, spec, keep_spans=None):
    """文字起こしの記録を文書の横に書く: 単語の時刻 <id>.words.json・生出力 <id>.asr.json・LLM の生の提案 <id>.llm.json(あれば)。
    keep_spans = 全体の再認識で元のまま残した機械の行の区間(その区間の前の単語は残す = replace_span_words。None = 単語を丸ごと書く)。
    ② が足すこと = ① の結果(transcribe_clip が返した clip)を、文書の id が決まったあとで記録として置く。書けなくても文書は残す(警告だけ)"""
    try:
        if keep_spans is None:
            _txwords.write_words(tid, clip["words"], spec["model"])
        else:
            replace_span_words(tid, float("-inf"), float("inf"), clip["words"], spec["model"], keep_spans)
    except OSError as e:
        _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
    try:
        records.write_asr(tid, clip["raw"], clip["fields"]["recognition"]["runs"][-1])
    except (OSError, TypeError, ValueError) as e:
        _txbase.log.warning("生出力を保存できませんでした: %s %s", tid, e)
    if clip["llm_items"]:
        llm.llm_write(tid, clip["llm_rec"], clip["llm_items"])   # LLM の生の提案・採否(<id>.llm.json。あとで「あり/なし」を測り直せる)
    _keys.write_after_transcribe(tid, spec, clip["fields"]["recognition"]["runs"][-1])   # 成果物の鍵 <id>.transcribe.key.json・<id>.post.key.json(書けなくてもログだけ。RS6 b-K1)


def replace_span_words(tid, a, b, new_words, model="", keep_spans=()):
    """再認識(③ human/proof/rerun の range・whole)のあと、単語の時刻 <id>.words.json の範囲 [a, b] を認識し直した単語に差し替える
    (真ん中が範囲に入る単語を消す。keep_spans の区間の単語は残す)。以前の単語が無い文書は、新しい単語だけを書く。
    ② が足すこと = 認識の記録 words.json の書き込み(③ は ytt/txwords を直に書かない)"""
    old = _txwords.read_words(tid) or []

    def inside(w):
        m = (w[0] + w[1]) / 2
        return a - 1e-6 <= m <= b + 1e-6 and not any(p0 <= m <= p1 for p0, p1 in keep_spans)
    _txwords.write_words(tid, [w for w in old if not inside(w)] + [list(w) for w in new_words], model)


def write_machine_doc(tid, fields, spec=None, folder=None):
    """③ なしで文書 transcripts/<id>.json の機械の分を書く最小の口(CLI 用。RS6 b の S1 が使う)。fields = transcribe_clip の "fields"。
    spec があれば題名・動画(title・sourcePath・sourceName)・clip・評価用の印も入れる。-> 書いたパス。
    folder = 新しい文書を置く 作業用(placement.doc_home が決める。None = 今までどおり。あれば docloc.place_new = 本体のあとに索引。RS8 B2-2)。
    機械の層 (r8t。RS8 O2-2): 文書の横に機械の層 <id>.mach.json(fields の行 = ① の後処理まで当てた行)も書く。人の層 <id>.hum.json があれば
    文書は ③ の物なので書かない(機械の層だけ)。機械の層を書けなくても文書は残す(ログだけ)。
    層が正(RS8 O2-3): 人の層が無いときの文書は機械の層だけから組み立てた写し = 欄 composedFrom {"mach": 機械の層の rev, "hum": None} を付け、
    今ある文書は 機械の層 → 写し の順に書く(写しの版が先に進んで層が無い、を作らない)。新しい文書(folder)は置き場所が決まってから層を置くので 写し → 機械の層。
    機械の層を書けなければ写しに composedFrom を付けない(= ③ が開いても組み立て直さない)。
    ② が足すこと = 置き場所(ytt/workdata の TX_DIR か案件の 作業用)と原子的な書き込み(ytt/fsio。③ の store.write_doc と同じ形の JSON)"""
    if not _yschemas.TID_RE.match(str(tid or "")):
        raise _errors.ApiError("bad_request", "文書の id が正しくありません", 400)
    if os.path.isfile(_docloc.doc_file(tid, _yschemas.HUM_SUFFIX)):   # 人の層がある = 文書(組み立て済みの写し)は ③ が書く
        _write_mach(tid, fields)
        return _docloc.doc_file(tid, ".json")
    doc = new_doc(tid, fields, spec)
    def _write(path):
        _fsio.write_json(path, doc, indent=1, fsync_required=True)
    if not folder:   # 今ある文書: 機械の層 → 写し(書けた版を写しに記す)
        rev = _write_mach(tid, fields)
        if rev is not None:
            doc[_yschemas.COMPOSED_FROM] = _yschemas.composed_from(rev, None)
        path = _docloc.doc_file(tid, ".json", for_write=True)
        _write(path)
        return path
    doc[_yschemas.COMPOSED_FROM] = _yschemas.composed_from(_next_mach_rev(tid), None)   # 新しい文書: 写し → 機械の層(rev は前の機械の層の次 = 先に決めて写しに記す)
    path = _docloc.place_new(tid, folder, _write)
    if _write_mach(tid, fields) is None:   # 文書のあと(新しい文書の置き場所が決まってから同じ所へ)
        doc.pop(_yschemas.COMPOSED_FROM, None)   # 機械の層が書けなかった: 写しから版を外す(③ が組み立て直さない)
        _write(path)
    return path


def _next_mach_rev(tid):
    """次に書く機械の層の rev(前の機械の層の rev + 1。無い・読めなければ 1)"""
    path = _docloc.doc_file(tid, _yschemas.MACH_SUFFIX)
    try:
        prev = _fsio.read_json_or(path, None, os.path.getsize(path), kind=dict) if os.path.isfile(path) else None   # 上限 = 大きさ(大きな入れ物を取らない)
    except OSError:
        prev = None
    return (_yschemas.plain_int(prev.get("rev")) or 0) + 1 if prev and prev.get("schema") == _yschemas.MACH_SCHEMA else 1


def _write_mach(tid, fields):
    """機械の層 <id>.mach.json を書く(rev は前の機械の層の次)-> 書いた rev。書けなければログだけで None"""
    try:
        path = _docloc.doc_file(tid, _yschemas.MACH_SUFFIX, for_write=True)
        rev = _next_mach_rev(tid)
        _fsio.write_json(path, _yschemas.make_mach(fields.get("segments"), rev=rev, speakers=fields.get("speakers")), indent=1)
        return rev
    except (OSError, ValueError, TypeError, _errors.ApiError) as e:
        _txbase.log.warning("機械の層を書けませんでした %s: %s %s", tid, e.__class__.__name__, str(e)[:200])
        return None


# ---------- 再認識(選んだ行・範囲・全体) ----------
def extract_span(job, src, spans, doc_start, doc_end, boost, wav):
    """再認識で取り出す音声の範囲を決めて(① recognize.audio_span。spans = [{"start", "end"}])取り出す -> 取り出した音声の先頭が元の動画の何秒か。
    ② が足すこと = ジョブの状態(extracting・音声を取り出し中)"""
    start, end = recognize.audio_span(spans, doc_start, doc_end)
    job["state"], job["phase"] = "extracting", "音声を取り出し中"
    recognize.extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": boost}, wav)
    return start


def _each_real(job, spec, targets, wav, start):
    """each_lines の本物の認識(行ごとに音声を切って、ワーカーで 1 行ずつ。GPU が実行時に失敗したら CPU でやり直す = ChunkModel)"""
    results = {}
    worker_client.check_engine(spec)
    job["state"] = "loading"
    cm = recognize.ChunkModel(job, spec["model"], spec["device"], spec, tx_engines.engine_of(spec))
    audio = worker_client.read_wav_f32(wav)
    job["state"], job["phase"] = "running", "再認識中"
    sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
    terms = _roster.prompt_terms(spec)
    for n, t in enumerate(targets):
        _slots.check_cancel(job)
        a, b = max(0.0, t["start"] - start - 0.3), t["end"] - start + 0.3   # 前後に少し余裕を持たせる(語頭・語尾が欠けにくい)
        r = cm.recognize(audio[int(a * 16000):int(b * 16000)], t, sep, terms, n == 0)
        if r:
            text, flag = r
            results[t["id"]] = (_txtext.strip_punct(text) if spec.get("stripPunct", True) else text, flag)
        job["progress"] = min(0.99, (n + 1) / len(targets))
    return results


def each_lines(job, spec, targets, wav, start):
    """選んだ行を 1 行ずつ認識する(音声は取り出し済み。先頭 = 元の動画の start 秒)-> {行の id: (文章, 要確認の理由)}。
    ② が足すこと = 本物と疑似の選び方(backend)・本物ならワーカーにモデルを読んで行ごとに回す(_each_real)・ジョブの状態と進み具合"""
    return _backend.select().each_lines(job, spec, targets, wav, start, _each_real)


def recognize_range(job, spec, wav, start, doc):
    """範囲(spec の range)の再認識の認識 -> (認識器, 行)。認識器の loose(spans)・vad は ③ が続けて使う(全体の再認識は文字起こしのジョブ)。
    ② が足すこと = 認識器を作る(ワーカーのモデルはその中で読む)・ジョブの状態(running・範囲を認識中)"""
    rec = recognize.RangeRecognizer(job, spec, wav, start)
    job["state"], job["phase"] = "running", "範囲を認識中"
    a, b = spec["range"]
    return rec, rec.main(a, b)


def note_vad(job, vad):
    """声の検出を緩めてやり直していれば、その知らせ(① recognize.vad_note)をジョブの vadNote と注意に入れる -> 知らせの文か ""。
    ② が足すこと = ジョブへの知らせ"""
    note = recognize.vad_note(vad)
    if note:
        job["vadNote"] = note
        _txbase.add_warning(job, note)
    return note


# ---------- 2 つ目のエンジン(human/proof/alt) ----------
def engine_ready(engine):
    """エンジンの準備 -> (使えるか, 使えない理由)。疑似は常に使える・faster-whisper は部品の有無・ほかは実行ファイルとモデル(① tx_engines の ready)。
    ② が足すこと = 本物と疑似の選び方と、エンジンごとの確かめ方の振り分け(/api/tools の alt の表示)"""
    def real(eng):
        if eng == tx_engines.FasterWhisper.id:
            ok = worker_client.has_faster_whisper()
            return ok, ("" if ok else "faster-whisper が入っていません")
        return tx_engines.get(eng).ready(tx_engines.engine_home())
    return _backend.select().engine_ready(engine, real)   # 疑似は常に使える(backend の口。OPT-E2 1a-2)


def check_engine_ready(spec):
    """ジョブを足す前にエンジンを確かめる(実行ファイルが無い・faster-whisper が無いなら ApiError。GPU の有無は読み込みのときに分かる)。
    ② が足すこと = 本物と疑似の選び方(疑似は確かめない = backend の口 check_engine)"""
    _backend.select().check_engine(spec, lambda sp: worker_client.check_engine(sp))


def _alt_real(job, spec, wav, total):
    """本物の認識(行の生成器): エンジンを確かめ(実行ファイルが無い・faster-whisper が無い)→ 読み込み(loading)→ 認識。疑似は Backend.alt_rows(eval/fake/fake_asr)"""
    worker_client.check_engine(spec)
    job["state"] = "loading"
    return recognize.transcribe_real(job, spec, wav, total)


def alt_engine_version(spec):
    """記録に入れる 2つ目のエンジンの版。疑似は ""(口 engine_version。RS5-D)"""
    return _backend.select().engine_version(spec, _alt_engine_version_real)


def _alt_engine_version_real(spec):
    try:
        return records.engine_version(tx_engines.get(spec["engine"]))
    except Exception:   # 記録のための値なので、分からなくても止めない
        return ""


def alt_lines(job, spec, wav):
    """文書の範囲(spec の start〜end)の音声を 2 つ目のエンジンで認識した行(時刻は元の動画の秒)。
    -> {"rows": [{start, end, text}], "total": 音声の長さ, "wallSec", "engineVersion", "fake"}。取り消しは Cancelled。
    文字起こしのジョブと同じ整え方(句読点の除去・長い行の分け方・長さより後ろを捨てる・繰り返しをまとめる。① postproc.expand_segments)。置換・学習はかけない。
    続いている行をつなぐ join_rows はかけない(候補は文字を比べるだけで行の時刻を使わない。notes:plan/done/line-b-row-timing.md の 7-2)。
    ② が足すこと = 一時の wav への取り出しとジョブの状態・本物と疑似の選び方と本物の処理(_alt_real)・行の数・取り消しの確かめ・エンジンの版"""
    os.makedirs(_workdata.TMP_DIR, exist_ok=True)
    job["state"], job["phase"] = "extracting", "音声を取り出し中"
    recognize.extract_audio(job, {"sourcePath": spec["sourcePath"], "start": spec["start"], "end": spec["end"], "boost": False}, wav)
    total = _tools.media_duration(wav) or ((spec["end"] or 0) - spec["start"])
    t0 = time.monotonic()
    gen = _backend.select().alt_rows(job, spec, wav, total, _alt_real)   # 疑似は主の疑似の行に TRANSCRIBE_FAKE_ALT の置き換えをかけた行
    rows = []
    for s in postproc.expand_segments(gen, spec, total, join=False):
        if not s["text"]:
            continue
        rows.append({"start": round(s["start"] + spec["start"], 2), "end": round(s["end"] + spec["start"], 2), "text": s["text"][:_txbase.MAX_TEXT]})
        job["segments"] = len(rows)
    if job["cancel"]:
        raise _slots.Cancelled()
    return {"rows": rows, "total": total, "wallSec": round(time.monotonic() - t0, 2), "engineVersion": alt_engine_version(spec), "fake": _backend.is_fake()}


# ---------- 行の時刻の候補(human/proof/retime) ----------
def word_retime(tid, segments, rows):
    """行の時刻を単語の時刻に合わせる候補(読むだけ)。単語の時刻(<id>.words.json)が無ければ None。
    -> {"items": 候補(① retime.retime_candidates), "checked": 調べた行の数(上限 RETIME_MAX_ROWS)}。
    ② が足すこと = 認識の記録(words.json)を読む・行の数の上限"""
    rows = list(rows)[:_retime.RETIME_MAX_ROWS]
    words = _txwords.read_words(tid)
    if not words:
        return None
    return {"items": _retime.retime_candidates(segments, words, rows), "checked": len(rows)}
