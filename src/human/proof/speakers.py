# -*- coding: utf-8 -*-
"""③ 人の操作の層 human/proof: 話者判別の結果を文書へ(apply_diarization・1 人指定 single_speaker・守る行 diar_keep_row)・判別のジョブの受付と文書への書き込み(validate_diarize・
run_diarize)・評価用の文書の文字起こしのあとの自動の判別(autodiar_)・覚えた声での名前付けと声を覚える(声の登録簿の編集の受付 =
voice_learn_plan・voice_preview・validate_voice_learn・run_voice_learn・voices_summary・delete_voice)・話者ごとの字幕の見た目(speakers_sub_apply)。

判別の計算・判別の記録・声の特徴と照らし合わせは ① pipeline/transcribe/diarize.py。ここは ① を読まず ② flow/diar の動詞(`_diar.名前`。呼ぶたびに読む)と ytt だけを読む
(判別のジョブの計算の糸・判別の記録・声の特徴と照合・覚えた声の置き場所は ② flow/diar。テストの patch.object(S, "has_sherpa"・"ensure_diar_models"・"embed_groups"・"write_diar") は ① に届き、② が呼ぶたびに読む)。
評価用の文書の名前の候補(⑤ eval/drill の drill_candidates)は読まず、serve が set_context_namer で登録する口を呼ぶたびに引く(③ から ⑤ を読まない)。
人の名前を比べる鍵は ytt/textutil.person_key の 1 つ(決定 notes:plan/decisions.md の 3-47 Q8)。文書の置き場は隣の store。
"""
import copy
import re
import time

from ytt import errors as _errors, schemas as _yschemas, tools as _tools  # noqa: E402
from ytt import textutil as _textutil  # noqa: E402   人の名前を比べる鍵 person_key(OPT-H1。Q8)
from flow import jobs as _heavy  # noqa: E402
from ytt import jobs as _slots  # noqa: E402
from ytt import txbase as _txbase  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定の読み書き load_settings
from human.proof import voiceclips as _voiceclips  # noqa: E402
from flow import voicematerial as _vm  # noqa: E402   ショート由来の材料か(学習用データ。is_short)   声を覚える材料の短い音(元の動画が片付いたあとの覚え直し。10-24)
from flow import diar as _diar  # noqa: E402   ② 判別と声の段取り(判別・割り当て・判別の記録・声の特徴と照合・覚えた声の置き場所。呼ぶたびに _diar.名前 で読む)
from . import store  # noqa: E402   文書の読み書き・保存のロック・控え(呼ぶたびに store.名前 で読む)
from . import layers as _layers  # noqa: E402   話者の判別(機械の層・話者の対応表)

# ---------- serve が登録する口(⑤ eval の drill を ③ から読まない) ----------
_namer = {}


def set_context_namer(fn):
    """評価用の文書の「動画の手がかり」の名前の候補を返す関数 fn(tid) -> 名前 or None(eval の drill.drill_candidates の suggest =
    覚えた声 → 動画の入ったメンバーのフォルダ → 配信の文脈)。編集の serve.py が読み込みのときに登録する
    (呼ぶたびに持ち主のモジュールの属性を読む lambda を渡す = テストの差し替えが届く)。関数でなければ TypeError"""
    if not callable(fn):
        raise TypeError("speakers の口 context_namer は関数で渡す")
    _namer["context"] = fn


def check_context_namer():
    """口が登録されていなければ RuntimeError(serve が登録の直後に呼ぶ。autodiar_enqueue は失敗を記録して名前なしで続けるため、登録し忘れを黙って飲まない)"""
    if "context" not in _namer:
        raise RuntimeError("speakers に登録されていない口: context_namer(編集の serve.py が読み込みのときに登録する)")


def _context_name(tid):
    """登録した口で名前の候補を引く(登録されていなければ RuntimeError)"""
    check_context_namer()
    return _namer["context"](tid)


# ---------- 話者判別の結果を文書へ(判別の計算と判別の記録は pipeline/transcribe/diarize) ----------
MAX_SPEAKERS = 20
SPK_COLORS = ["#2f62d6", "#d9534f", "#2e9e5b", "#c98a12", "#8a4fd6", "#0f9aa8", "#d6479a", "#6b7280"]


def _diar_smooth_setting(st=None):
    """設定 diarSmooth(既定オフ)。st = 読んである設定(無ければ読む)"""
    return (_settings.load_settings() if st is None else st).get("diarSmooth") is True


def apply_diarization(tid, turns, offset, requested, emb=None, auto=None, smooth=False):
    """最新の文字起こしを読み直して話者を書き込む(判別中に行を編集されていても、時刻で割り当てるので矛盾しない)。
    読み直し〜書き込みは保存と同じロックの中で行う(間に画面の保存が挟まると、その保存が黙って上書きされるため)。
    auto(評価用の文字起こしのあとの自動の判別)なら文書の diarization と diar.json に印を残す(画面の「自動で付けた」の案内・人の最終との比べ)。
    smooth = 短い 1 行だけ別の人になるのをならす(S2。smooth_speakers。行の話者だけ。turns・overlaps はそのまま記録する)。emb = 判別モデル(None なら既定)。
    戻り値は (話者の数, 要確認の数)"""
    if emb is None:
        emb = _diar.default_embedding()
    with store._save_lock:
        return _apply_diarization(tid, turns, offset, requested, emb, auto, smooth)


def _spk_ids(doc):
    """文書の話者の id の集まり(文字列)"""
    return {str(s.get("id")) for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}


def diar_keep_row(g, ids):
    """話者判別のやり直し・1人指定・「全行をこの人に」で話者を変えない行: 字幕に出さない行(noSub)・
    組み込みの話者「ゲーム音声など」の行・音のメモ「声が重なる」(overlap)が付いていて話者のある行(手で作った重なる行を守る)。
    ids = 文書の話者の id の集まり(無い id の話者は守らない)"""
    if not isinstance(g, dict):
        return False
    sp = str(g.get("speaker") or "")
    if _yschemas.no_sub_row(g) or sp == _yschemas.OTHER_SPK_ID:
        return True
    return bool(sp) and sp in ids and "overlap" in (g.get("tags") if isinstance(g.get("tags"), list) else [])


def _diar_kept_speakers(doc, segs, keep, taken):
    """守った行の話者を、判別のあとの話者の一覧に残す。taken = 新しい話者の id(重なれば守った方の id を付け替える)。
    -> ([残す話者], {古い id: 新しい id})。組み込みの話者は id を変えない(決まった id)"""
    old = [s for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")]
    used = {str(g.get("speaker") or "") for g, k in zip(segs, keep) if k and g.get("speaker")}
    out, remap, have = [], {}, set(taken)
    for s in old:
        sid = str(s["id"])
        if sid not in used:
            continue
        nid, n = sid, 0
        if sid != _yschemas.OTHER_SPK_ID:
            while nid in have or nid == _yschemas.OTHER_SPK_ID:   # 例: 守った行の「S2」→「S2p」(新しい判別の S2 とは別の人)
                n += 1
                nid = sid[:8] + "p" + (str(n) if n > 1 else "")
        have.add(nid)
        remap[sid] = nid
        out.append(dict(s, id=nid))
    out.sort(key=lambda s: s.get("id") == _yschemas.OTHER_SPK_ID)   # 組み込みの話者は最後(Alt+数字の番号に入らない)
    return out, remap


def _commit_diar(tid, before, doc, keep_ids):
    """話者の判別の書き込み(決定 3-37 の (r8r) = notes:plan/decisions.md): 機械の層に判別の結果(話者 S…・話者の印)を入れ、判別の鍵 keys.diar を新しくする。
    判別し直し(前の文書に話者の付いた行がある)なら、人の層の話者の表はそのまま(付け直さない)で、機械の S… → 人の話者の対応表 spkMap を
    重なり時間で当てる(layers.assign_speakers。当たらない話者だけ新しい H… と弱い印 SPK_CHANGED)。人が決めた話者は残し、層より前の判別の話者は判別に従う
    (layers.after_rediar)。初めての判別は今と同じ(文書の話者 = 機械の話者)"""
    mach0, hum0 = store.layers_for(tid, before)
    mach1, _changed = _layers.advance_mach(mach0, before, doc, speakers=True)
    mach1["keys"] = dict(mach1.get("keys") or {}, diar="diar-%s" % ((doc.get("diarization") or {}).get("at") or int(time.time() * 1000)))
    _layers.set_spk_flags(mach1, doc, _txbase.SPK_FLAGS)
    ids = _spk_ids(before)
    if not any(str(g.get("speaker") or "") in ids and g.get("speaker") != _yschemas.OTHER_SPK_ID for g in before.get("segments") or [] if isinstance(g, dict)):
        store.commit(tid, doc, why="diar", mach=mach1)
        return
    hum1 = _layers.after_rediar(mach1, _layers.assign_speakers(mach1, hum0, before.get("segments")), keep_ids, _txbase.SPK_FLAGS)
    store.commit(tid, doc, why="diar", mach=mach1, hum=hum1)


def _apply_diarization(tid, turns, offset, requested, emb, auto=None, smooth=False):
    doc = store.read_transcript(tid)
    doc["segments"] = sorted(doc.get("segments") or [], key=lambda g: (g["start"], g["end"]))   # 層の組み立ては時刻の順(順が違う文書は「並び」が合わない警告になる)
    before = copy.deepcopy(doc)   # 人の層が話者の表を持つ((r8r))
    ids = _spk_ids(doc)
    # 定型の幻覚で声の区間と重ならない行を捨ててから(autoFill の文書だけ)割り当てる。手で決めた行(字幕に出さない・ゲーム音声など・重なりのメモつき)は話者を変えない
    a = _diar.assign(doc, turns, offset, lambda g: diar_keep_row(g, ids), smooth)
    segs, keep, res, smoothed, dropped = a["segs"], a["keep"], a["res"], a["smoothed"], a["dropped"]
    spent = {}
    for sg, (sp, _, _), k in zip(segs, res, keep):
        if sp is not None and not k:
            spent[sp] = spent.get(sp, 0.0) + max(0.0, sg["end"] - sg["start"])
    n_kept = len(_diar_kept_speakers(doc, segs, keep, ())[0])   # 守った行の話者(判別のあとも一覧に残る。合わせて MAX_SPEAKERS まで = 保存の検査で切れない)
    order = sorted(spent, key=lambda k: -spent[k])[:max(0, MAX_SPEAKERS - n_kept)]   # 話した時間が長い人から「話者1」「話者2」…
    idmap = {raw: "S%d" % (i + 1) for i, raw in enumerate(order)}
    speakers = [{"id": "S%d" % (i + 1), "name": "話者%d" % (i + 1), "color": SPK_COLORS[i % len(SPK_COLORS)]} for i in range(len(order))]
    kept_sps, remap = _diar_kept_speakers(doc, segs, keep, set(idmap.values()))
    speakers += kept_sps
    unsure = 0
    for sg, (sp, mixed, weak), k in zip(segs, res, keep):
        if k:   # 守った行: 話者(付け替えた id)も印もそのまま
            if sg.get("speaker"):
                sg["speaker"] = remap.get(str(sg["speaker"]), sg["speaker"])
            continue
        sg["speaker"] = idmap.get(sp, "")
        parts = [x for x in str(sg.get("flag", "")).split("、") if x and x not in _txbase.SPK_FLAGS]
        mark = _txbase.NONE_FLAG if not sg["speaker"] else _txbase.MIXED_FLAG if mixed else _txbase.WEAK_FLAG if weak else ""
        if mark:
            parts.append(mark)
            unsure += 1
        sg["flag"] = "、".join(parts)[:100]
    store.backup_doc(tid, "diarize")   # 判別の前の状態を履歴に残す(画面の「履歴」から戻せる)
    doc.update({"speakers": speakers, "segments": segs, "updatedAt": int(time.time() * 1000),
                "diarization": dict({"engine": "sherpa-onnx", "embedding": emb, "requested": requested, "found": len(order), "unsure": unsure, "at": int(time.time() * 1000)},
                                    **({"auto": True} if auto else {}), **({"smoothed": len(smoothed)} if smoothed is not None else {}),
                                    **({"fillDropped": dropped} if dropped else {}))})
    _commit_diar(tid, before, doc, {str(g.get("id")) for g, k in zip(segs, keep) if k})
    _diar.record_run(tid, a, turns, offset, requested, emb, idmap, auto)   # 機械の最初の結果(人が直す前)を <id>.diar.json に
    return len(order), unsure


def validate_diarize(req):
    tid = str(req.get("tid") or "")
    doc = store.read_transcript(tid)
    if not doc.get("segments"):
        raise _errors.ApiError("empty", "行がないため、話者を判別できません", 400)
    _tools.check_source(doc.get("sourcePath"))
    try:
        n = int(req.get("numSpeakers") or 0)
    except (TypeError, ValueError):
        n = 0
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["diarize"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    emb = _diar.embedding(str(req.get("embedding") or ""))   # 知らない・空なら既定
    names = []   # 出てくる人の名前(友人からの依頼の「話す人」)
    for x in req.get("names") if isinstance(req.get("names"), list) else []:
        s = str(x or "").strip()[:60] if isinstance(x, str) else ""
        if s and not any(ord(ch) < 32 for ch in s) and not DEFAULT_SPK_NAME.match(s) and _textutil.person_key(s) not in {_textutil.person_key(n) for n in names}:
            names.append(s)
    return {"tid": tid, "numSpeakers": n if 1 <= n <= 10 else 0, "names": names[:10], "embedding": emb, "title": _heavy.job_title("話者判別: ", doc),
            "recognize": req.get("recognize") is not False,   # A-3: 覚えている声と照らし合わせる(既定オン)
            "smooth": req["smooth"] if isinstance(req.get("smooth"), bool) else _diar_smooth_setting(),   # S2: 細切れをならす(要求に無ければ設定 diarSmooth。既定オフ)
            "keepRowVoice": req.get("keepRowVoice") is True}   # ② の流れの判別: 覚えた声で行の話者を当てた文書(rowvoice)は上書きしない


def single_speaker(tid, name):
    """話す人が1人: 判別せずに全部の行をその人に(名前が無ければ「話者1」)。-> 行の数。
    手で決めた行(diar_keep_row = 字幕に出さない・ゲーム音声など・重なりのメモつき)は話者を変えない"""
    with store._save_lock:
        doc = store.read_transcript(tid)
        segs = doc.get("segments") or []
        ids = _spk_ids(doc)
        keep = [diar_keep_row(g, ids) for g in segs]
        kept_sps, remap = _diar_kept_speakers(doc, segs, keep, {"S1"})
        same = _textutil.person_key(name or "話者1")
        for s in [s for s in kept_sps if s.get("id") != _yschemas.OTHER_SPK_ID and _textutil.person_key(s.get("name")) == same]:   # 同じ名前の人は 1 人にまとめる
            remap.update({k: "S1" for k, v in remap.items() if v == s["id"]})
            kept_sps.remove(s)
        for sg, k in zip(segs, keep):
            if k:
                if sg.get("speaker"):
                    sg["speaker"] = remap.get(str(sg["speaker"]), sg["speaker"])
                continue
            sg["speaker"] = "S1"
            sg["flag"] = "、".join(x for x in str(sg.get("flag", "")).split("、") if x and x not in _txbase.SPK_FLAGS)[:100]
        store.backup_doc(tid, "diarize")
        doc.update({"speakers": [{"id": "S1", "name": name or "話者1", "color": SPK_COLORS[0]}] + kept_sps, "segments": segs, "updatedAt": int(time.time() * 1000),
                    "diarization": {"engine": "single", "requested": 1, "found": 1, "unsure": 0, "at": int(time.time() * 1000)}})
        store.commit(tid, doc, why="single_speaker")
        _diar.record_single(tid, segs, name)
        return len(segs)


def run_diarize(job):
    spec = job["spec"]
    if spec.get("auto") and _autodiar_skip_at_start(job):   # 自動の判別: 待っている間に人が話者を付けた・確かめ済みにしたなら何もしない
        return
    if spec.get("keepRowVoice") and _rowvoice_doc(spec["tid"]):   # ② の流れの判別: 覚えた声で当てた話者を残す(短いコラボは判別が人を分けられない。notes:plan/行ごとの声の当て-1023.md)
        job["speakers"], job["unsure"], job["rowVoiceKept"] = len(store.read_transcript(spec["tid"]).get("speakers") or []), 0, True
        _heavy.job_done(job, spec["tid"], "判別しませんでした(覚えた声で行の話者を当ててあります)")
        return
    if spec.get("numSpeakers") == 1:   # 1人なら判別しない(音声も取り出さない)。失敗は ② のジョブの器が受ける(ほかの道と同じ)
        single_speaker(spec["tid"], (spec.get("names") or [""])[0])
        job["speakers"], job["unsure"] = 1, 0
        job["named"] = [{"speaker": "S1", "name": spec["names"][0], "score": None}] if spec.get("names") else []
        _heavy.job_done(job, spec["tid"])
        return
    with _heavy.job_temp_wav(job) as wav:
        doc = store.read_transcript(spec["tid"])
        src = _tools.check_source(doc.get("sourcePath"))
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        turns = _diar.diarize(job, spec, wav, {"sourcePath": src, "start": start, "end": end})   # 3 時間の上限・音声の取り出し・判別(疑似は backend の口)
        _slots.check_cancel(job)
        auto = {"eval": bool(spec.get("autoEval")), "contextName": spec.get("contextName") or None} if spec.get("auto") else None
        job["speakers"], job["unsure"] = apply_diarization(spec["tid"], turns, start, spec["numSpeakers"], spec["embedding"], auto, bool(spec.get("smooth")))
        if spec.get("recognize", True):   # A-3: 覚えている声と照らし合わせて、仮の名前(話者n)に名前を付ける。失敗しても判別の結果は残す
            try:
                job["named"] = _recognize_voices(job, spec["tid"], wav, start, _diar.match_embedding(spec["embedding"]), spec.get("names") or None)   # 照らすモデルは判別と別(VOICE_EMB)
            except _slots.Cancelled:
                raise
            except Exception as e:
                _txbase.log.warning("声の照らし合わせに失敗: %s %s", e.__class__.__name__, str(e)[:200])
                job["voiceError"] = "覚えている声との照らし合わせに失敗しました(話者の判別の結果はそのまま): %s" % str(e)[:120]
                _diar.record_match_error(spec["tid"], "%s %s" % (e.__class__.__name__, str(e)[:150]))
        if spec.get("contextName"):   # 評価用の自動の判別: 声で名前が付かなかった人のうち、いちばん長く話した人に動画の手がかりの名前
            try:
                hit = _autodiar_name_by_context(spec["tid"], spec["contextName"])
                if hit:
                    job["named"] = list(job.get("named") or []) + [hit]
            except Exception as e:   # 名前が付けられなくても判別の結果は残す
                _txbase.log.warning("動画の手がかりで名前を付けられませんでした: %s %s", e.__class__.__name__, str(e)[:200])
        _heavy.job_done(job, spec["tid"])


# ---------- 評価用の文書の文字起こしのあと、話者を自動で判別する ----------
# 評価用でない文書の自動の判別はしない(普段の判別は ② の流れ = 依頼は人数を指定して直に呼ぶ)。
# 評価ドリルでは全行に話者が要る(評価用のフォルダの「メンバーのフォルダへ移す」条件)ので、評価用の文字起こしのあとは必ず判別のジョブを足し、
# 覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に「動画の手がかり」の名前
# (drill.drill_candidates の suggest = 覚えた声 → 動画の入ったメンバーのフォルダ → 配信の文脈)を付ける。新しい認識の道は作らない(今の diarize のジョブ)。
# 人が付けたものは置き換えない: 文字のある行に1つでも話者があれば何もしない(足すときと、ジョブが動き出すときの両方で確かめる)。
# 判別の部品(sherpa-onnx)が無いときは黙って飛ばす(ログだけ。文字起こしは失敗にしない)。外から呼ぶ口は autodiar_enqueue・autodiar_after_transcribe
# (⑤ eval/drill/evalbatch と doc_jobs)・autodiar_enabled・autodiar_ready。名前は autodiar_ / _autodiar_ で始める
_AUTODIAR_BY = "context"   # diar.json の voices の by(動画の手がかりで付けた。覚えた声 = threshold・消去法 = elimination・依頼 = request と並べる)


def autodiar_enabled():
    """環境変数 TRANSCRIBE_AUTO_DIARIZE=off で自動の判別をしない(テスト・困ったとき用。評価用の決まりは変えない)"""
    return not _txbase.env_off("TRANSCRIBE_AUTO_DIARIZE")


def autodiar_ready():
    """判別の部品があるか(疑似のときは常に)。サーバー側では sherpa-onnx を読み込まない(has_sherpa はワーカー側で調べる)。
    テスト用の worker-fake(ワーカーの中だけ偽のモデル)では使わない(判別は本物の経路 = モデルの取得になるため)。決まりは ② の models_ready(auto=True)"""
    return _diar.models_ready(auto=True)


def _autodiar_why_not(doc):
    """自動で判別しない理由(None = 判別してよい): empty(文字のある行が無い)・reviewed(評価用で確かめ済み)・
    has_speakers(文字のある行に話者がある = 人か前の判別が付けた。置き換えない)"""
    ids = {s.get("id") for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()]
    if not rows:
        return "empty"
    if _yschemas.is_eval_reviewed(doc):
        return "reviewed"
    if any(g.get("speaker") in ids and not diar_keep_row(g, ids) for g in rows):   # 守る行(ゲーム音声など・字幕に出さない・重なりのメモ)は判別で変わらないので数えない
        return "has_speakers"
    return None


def autodiar_enqueue(tid, batch=False, smooth=None):
    """自動の判別のジョブを足す(人数 自動・覚えた声との照合あり)。評価用なら名前の候補(suggest)も渡す。
    -> {"job": ジョブ, "name": 名前の候補 or None} か {"skipped": 理由}。足せない(待機列がいっぱい・処理中など)は ApiError。
    batch = 評価用のまとめての文字起こし(eval/drill/evalbatch)が入れた印(spec["evalBatch"]。そちらの待ちの数に入る)。
    smooth = 細切れをならすか(文字起こしの要求にあればその値。None = 保存した設定 diarSmooth)"""
    if not autodiar_enabled():
        return {"skipped": "off"}
    if not autodiar_ready():
        _txbase.log.info("話者の自動判別を飛ばしました(判別の部品 sherpa-onnx が無い): %s", tid)
        return {"skipped": "no_sherpa"}
    doc = store.read_transcript(tid)
    why = _autodiar_why_not(doc)
    if why:
        return {"skipped": why}
    ev = doc.get("evalSet") is True
    name = None
    if ev:
        try:
            name = str(_context_name(tid) or "").strip()[:30] or None   # serve が登録した口 = drill.drill_candidates の suggest
        except Exception as e:   # 名簿・ほかのツールのデータが読めなくても判別は始める(名前は付けない)
            _txbase.log.info("話者の名前の候補を決められませんでした: %s %s", tid, str(e)[:150])
        if name and (DEFAULT_SPK_NAME.match(name) or is_generic_speaker_name(name)):
            name = None
    st = _settings.load_settings()   # 判別モデルと「細切れをならす」(diarSmooth)を 1 回で読む
    spec = validate_diarize({"tid": tid, "numSpeakers": 0, "recognize": True, "embedding": st.get("diarEmb"), "smooth": _diar_smooth_setting(st) if smooth is None else smooth})
    spec.update({"auto": True, "autoEval": ev, "contextName": name,
                 "title": _heavy.job_title("話者判別(自動): ", doc)})
    if batch:
        spec["evalBatch"] = True
    return {"job": _heavy.add_job(spec, "diarize"), "name": name}


def autodiar_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(run_job)の終わり。文書を書いたあと・「完了」にする前に呼ぶ(ドリルが判別の前の文書を開かないよう、間を空けない)。
    評価用の文書だけ(要求の autoDiarize は見ない)。部品が無ければ黙って飛ばす(人が「全行をこの人に」)。始められなくても文字起こしは成功のまま(job["warnings"])"""
    if not spec.get("evalSet"):
        return
    try:
        autodiar_enqueue(tid, batch=bool(spec.get("evalBatch")), smooth=spec.get("diarSmooth"))
    except _errors.ApiError as e:
        _txbase.add_warning(job, "話者の自動判別を始められませんでした: " + e.message)
    except Exception as e:   # 想定外でも、書き終えた文字起こしのジョブを失敗にしない
        _txbase.log.warning("話者の自動判別を始められませんでした: %s %s %s", tid, e.__class__.__name__, str(e)[:150])


def _rowvoice_doc(tid):
    """文書の話者を覚えた声で当てたか(flow/diar.row_voices の印 diarization.speakerBy rowvoice)"""
    d = store.read_transcript(tid).get("diarization")
    return isinstance(d, dict) and d.get("speakerBy") == "rowvoice"


def _autodiar_skip_at_start(job):
    """自動の判別のジョブが動き出すとき、もう一度確かめる(待っている間に人が話者を付けた・確かめ済みにした・行が消えた)。
    判別しないなら「完了(判別しませんでした)」にして True"""
    spec = job["spec"]
    try:
        why = _autodiar_why_not(store.read_transcript(spec["tid"]))
    except _errors.ApiError as e:
        why = e.code
    if not why:
        return False
    job["autoSkipped"] = why
    _heavy.job_done(job, spec["tid"], "判別しませんでした(" + {"has_speakers": "話者が付いていました", "reviewed": "確かめ済みです", "empty": "文字のある行がありません"}.get(why, why) + ")")
    return True


def _autodiar_name_by_context(tid, name):
    """覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に name を付ける(1 人だけならその人)。
    name がもうほかの話者に使われていれば付けない(覚えた声の名前を優先・名前は person_key で比べる)。読み直し〜書き込みは保存と同じロックの中(_recognize_voices と同じ)。
    -> {"speaker", "name", "score": None, "by": "context"} か None。経過は diar.json の voices(② の record_context)"""
    nm = str(name or "").strip()[:30]
    key = _textutil.person_key(nm)
    hit, reason = None, None
    with store._save_lock:
        doc = store.read_transcript(tid)
        sps = [s for s in doc.get("speakers") or [] if isinstance(s, dict)]
        spent = {}
        for g in doc.get("segments") or []:
            if isinstance(g, dict) and g.get("speaker") and str(g.get("text") or "").strip() and not _yschemas.no_sub_row(g):   # 字幕に出さない行(ゲームの声など)は話した秒に数えない
                a, b = _yschemas.num_or(g.get("start"), 0.0) or 0.0, _yschemas.num_or(g.get("end"), 0.0) or 0.0
                spent[g["speaker"]] = spent.get(g["speaker"], 0.0) + max(0.0, b - a)
        left = [s for s in sps if DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and spent.get(s.get("id"), 0.0) > 0]
        if not nm or not sps:
            reason = "no_speakers" if nm else "no_name"
        elif any(_textutil.person_key(s.get("name")) == key for s in sps):
            reason = "name_in_use"
        elif not left:
            reason = "all_named"
        else:
            pick = max(left, key=lambda s: spent.get(s.get("id"), 0.0))   # 同じ秒なら先の人(話者1 = 判別が長い順に付けた番号)
            pick["name"] = nm
            hit = {"speaker": pick["id"], "name": nm, "score": None, "by": _AUTODIAR_BY}
            if isinstance(doc.get("diarization"), dict):
                doc["diarization"]["contextName"] = nm
            doc["updatedAt"] = int(time.time() * 1000)
            store.commit(tid, doc, why="diar_context")
    _diar.record_context(tid, nm, hit, reason)   # diar.json の voices に by = context と経過(② flow/diar)
    return hit


# ---------- 覚えた声で名前を付ける・話者の声を覚える(A-3) ----------
# 名前を付けた話者の行の音声から「声の特徴」(sherpa-onnx の話者の埋め込み。判別モデルごとに別)を作って覚え、
# 次からの話者判別のあとで、見つかった話者を覚えている声と比べて名前を付ける。
# 声の特徴は個人を見分けられる情報なので、作業データ(voices/)にだけ置く(リポジトリ・パックには入れない)。
# 声の特徴の計算と照らし合わせ(VOICE_MATCH・embed_groups・match_voices_explain)は pipeline/transcribe/diarize(numpy・sherpa-onnx は認識ワーカーの中だけ)。
# 覚えた声の置き場所(VOICES_DIR・voices_dir・load_voices・save_voices・登録簿のロック)と、声の特徴を取る・照らし合わせる段取りは ② flow/diar。
# ここにあるのは、判別のあとの名前付け(_recognize_voices)・覚える行の計画・覚える前の確認・受付・覚えるジョブ・一覧・忘れる(声の登録簿の編集の受付)。
# 名前は person_key で比べる(登録簿の「Pekora」と文書の「pekora」は同じ人 = 登録簿の名前に足す)
_VOICE_MAX_PEOPLE = 300
DEFAULT_SPK_NAME = re.compile(r"^話者\d+$")   # 話者判別が付けた仮の名前(覚えない・声で付けた名前で置き換えてよい)
# 一般的な名前(監査18。段1・ユーザー決定): 声を覚えると、別の配信の「本人」「ゲスト」に同じ名前が付いてしまう(人ではなく役の名前)ので覚えない。
# 判定は is_generic_speaker_name の1か所(画面は preview の結果を出すだけ)。比べる前に person_key で寄せる(全角の「ＭＣ」・「Speaker 1」・カタカナとひらがなも同じに)
_GENERIC_SPK_NAMES = frozenset(_textutil.person_key(x) for x in (
    "本人", "ゲスト", "配信者", "私", "自分", "相手", "司会", "mc", "男性", "女性", "不明", "その他", "視聴者", "ナレーション",
    "話者", "speaker", "スピーカー", _yschemas.OTHER_SPK_NAME))   # 組み込みの「ゲーム音声など」も人の名前ではない(覚えない・照らし合わせない)
_GENERIC_SPK_FORM = re.compile(r"^(?:話者|speaker|spk|すぴーかー)?(?:\d+|[a-z])$")   # 話者A・話者1・Speaker 1・英字1文字・数字だけ(person_key のあとの形 = スピーカーはひらがな)
_spk_name_key = _textutil.person_key   # lint: keep 別名(⑤ eval/drill/drill が読む旧い内部名。⑤ が ytt.textutil.person_key を読むようにしたら消す = OPT-E1)


def is_generic_speaker_name(name):
    k = _textutil.person_key(name)
    return bool(k) and (k in _GENERIC_SPK_NAMES or bool(_GENERIC_SPK_FORM.match(k)))


def _voice_name(voices, name):
    """登録簿の中で name と同じ人(person_key が同じ)の名前。いなければ name のまま"""
    k = _textutil.person_key(name)
    return next((n for n in voices if _textutil.person_key(n) == k), name)


def _recognize_voices(job, tid, wav, offset, emb, names=None):
    """話者判別のあと: 見つかった話者を覚えている声と比べ、仮の名前(話者n)のままの話者に名前を付ける。-> [{"speaker", "name", "score"}]。
    names(出てくる人の名前。友人からの依頼)があれば、照らし合わせをその名前だけにし、最後に仮の名前の話者と使っていない名前が1つずつ残れば消去法で付ける(score None)。
    照合の経過(点数・2位との差・決まり方・付けなかった理由)は <id>.diar.json の voices に残す(② の record_match。書けなくても名前付けは続ける)"""
    all_voices = _diar.load_voices(emb)
    want = {_textutil.person_key(n) for n in names or ()}
    voices = {n: v for n, v in all_voices.items() if _textutil.person_key(n) in want} if names else all_voices
    got, detail = {}, {}
    if voices:
        doc = store.read_transcript(tid)
        key = lambda g: "" if _yschemas.no_sub_row(g) or g.get("speaker") == _yschemas.OTHER_SPK_ID else (g.get("speaker") or "")   # ゲーム音声など・字幕に出さない行は照らし合わせない
        got, detail = _diar.match_known_voices(job, {"embedding": emb}, wav, doc.get("segments") or [], key, voices, {"start": offset})

    def record(doc, named):
        """diar.json の voices(話者ごとの経過 + 名前を付けた結果)。失敗しても名前付けには響かせない"""
        try:
            rec = {}
            for s in doc.get("speakers") or []:
                if not isinstance(s, dict):
                    continue
                d = dict(detail.get(s.get("id")) or _diar.empty_voice(reason="no_voices" if not voices else "no_rows"))
                hit = next((n for n in named if n["speaker"] == s.get("id")), None)
                if hit:
                    d["decided"], d["by"], d["reason"] = hit["name"], hit.get("by") or ("elimination" if hit["score"] is None else "threshold"), None
                elif d.get("decided"):   # しきい値は通ったが、名前が付かなかった(自分で付けた名前・別の人が使っている名前)
                    d["reason"] = "already_named" if not DEFAULT_SPK_NAME.match(str(s.get("name") or "")) else "name_in_use"
                    d["decided"], d["by"] = None, None
                rec[str(s.get("id"))] = d
            _diar.record_match(tid, emb, len(all_voices), names, rec)
        except Exception as e:
            _txbase.log.warning("声の照合の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])

    if not got and not names:
        record(store.read_transcript(tid), [])
        return []
    named = []
    with store._save_lock:   # 読み直し〜書き込みは保存と同じロックの中(話者判別の書き込みと同じ)
        doc = store.read_transcript(tid)
        key = _textutil.person_key
        taken = {key(s.get("name")) for s in doc.get("speakers") or [] if isinstance(s, dict)}   # 使われている名前(person_key で比べる)
        for s in doc.get("speakers") or []:
            hit = got.get(s.get("id")) if isinstance(s, dict) else None
            if hit and DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and key(hit[0]) not in taken:
                s["name"] = hit[0]
                taken.add(key(hit[0]))
                named.append({"speaker": s["id"], "name": hit[0], "score": hit[1], "by": "threshold"})
        if names:   # 消去法: 名前の無い話者と使っていない名前が1つずつなら、その人
            left = [s for s in doc.get("speakers") or [] if isinstance(s, dict) and DEFAULT_SPK_NAME.match(str(s.get("name") or ""))]
            unused = [n for n in names if key(n) not in taken]
            if len(left) == 1 and len(unused) == 1:
                left[0]["name"] = unused[0]
                named.append({"speaker": left[0]["id"], "name": unused[0], "score": None, "by": "elimination"})
        if named:
            doc["updatedAt"] = int(time.time() * 1000)
            store.commit(tid, doc, why="diar_voices")
    record(doc, named)
    return named


VOICE_LEARN_TAGS = ("overlap", "bgm", "unclear")   # この印の行は覚えない(声が重なる・BGM が大きい・聞き取れない。監査17)
EVAL_SET_VOICE_MSG = "評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外してから行ってください"


def voice_learn_plan(doc, rows=None):
    """声を覚えるときに使う行(監査17。段1): voice_groups の条件(1秒以上・声が混ざっていない)に加えて、校正済みで、音のメモ(重なり・BGM・聞き取れない)が無い行だけ。
    話者判別のときの照らし合わせ(_recognize_voices)は voice_groups のまま(校正前の文書でも名前が付くように。変えない決定)。
    rows = 使う行の id を明示する(確かめるの声のカードで人が名前を答えた行。V1 V2c)。渡すとその行だけを使い、校正済みかは見ない
    (カードの行は校正済みにしない = 文字は確かめていない)。ほかの条件(1 秒以上・混ざり・音のメモ・名前)は同じ。
    -> {"groups": {名前: ([(開始, 終了)...], 秒)}, "speakers": {名前: [話者の id]}, "refused": [{"name", "speakers", "reason": "generic"|"no_rows"}],
        "skipped": {"unproofed", "tagged", "mixed", "short"}(覚える人の行のうち使わなかった数。理由は 1秒未満 → 混ざる → 音のメモ → 未校正 の順に1つ。
        rows を渡したときの unproofed = 指定に無い行), "rowIds": {名前: [声に使う行の id]}(groups に入った行だけ。1 人の上限(① voice_groups)で使わない行は入れない =
        確かめるの覚え直しで、使わなかった行を「覚えた」と控えない)}"""
    names = {s.get("id"): str(s.get("name") or "").strip()[:60] for s in doc.get("speakers") or [] if isinstance(s, dict) and not _yschemas.other_speaker(s)}   # 組み込みの「ゲーム音声など」は覚えない(断った扱いにもしない)
    by_name, refused = {}, {}
    for sid, n in names.items():
        if not n or DEFAULT_SPK_NAME.match(n):
            continue   # 仮の名前 = 名前を付けていない(断った扱いにもしない)
        if is_generic_speaker_name(n):
            refused.setdefault(n, {"name": n, "speakers": [], "reason": "generic"})["speakers"].append(sid)
            continue
        by_name.setdefault(n, []).append(sid)
    who = {sid: n for n, sids in by_name.items() for sid in sids}
    pick = None if rows is None else {str(r) for r in rows}
    row_ids = {}
    def accept(g):
        tags = g.get("tags") if isinstance(g.get("tags"), list) else []
        if any(t in tags for t in VOICE_LEARN_TAGS):
            return "tagged"
        ok = g.get("proofed") is True if pick is None else str(g.get("id")) in pick
        if not ok:
            return "unproofed"
        row_ids.setdefault(who.get(g.get("speaker")), []).append((str(g.get("id")), _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))))
        return None
    groups, skipped = _diar.voice_learn_rows(doc.get("segments") or [], who, accept)
    for n, sids in by_name.items():
        if n not in groups:
            refused[n] = {"name": n, "speakers": sids, "reason": "no_rows"}
    return {"groups": groups, "speakers": {n: sids for n, sids in by_name.items() if n in groups},
            "refused": sorted(refused.values(), key=lambda r: r["name"]), "skipped": skipped,
            "rowIds": {n: [rid for rid, a, b in ids if (a, b) in set(groups[n][0])] for n, ids in row_ids.items() if n in groups}}


def _voice_emb(req, doc):
    """声を覚える・確かめるモデル(要求か判別の記録のモデル → ② の learn_embedding = VOICE_EMB があればそれ)"""
    return _diar.learn_embedding(str(req.get("embedding") or (doc.get("diarization") or {}).get("embedding") or ""))   # 知らない・空なら既定


def voice_preview(tid, emb):
    """覚える前の確認(GET /api/voices/preview。読むだけ・ジョブを作らない。監査17・18)"""
    doc = store.read_transcript(str(tid or ""))
    emb = _voice_emb({"embedding": emb}, doc)
    plan = voice_learn_plan(doc)
    voices = _diar.load_voices(emb)
    people = []
    for n in sorted(plan["groups"]):
        rs, sec = plan["groups"][n]
        old = voices.get(_voice_name(voices, n))
        people.append({"name": n, "speaker": plan["speakers"][n][0], "speakers": plan["speakers"][n], "rows": len(rs), "sec": round(sec, 1), "exists": bool(old),
                       "old": {"rows": int(old.get("rows") or 0), "sec": float(old.get("sec") or 0.0), "updatedAt": int(old.get("updatedAt") or 0)} if old else None})
    return {"tid": tid, "embedding": emb, "evalSet": doc.get("evalSet") is True, "people": people, "refused": plan["refused"], "skipped": plan["skipped"]}


def validate_voice_learn(req):
    tid = str(req.get("tid") or "")
    doc = store.read_transcript(tid)
    if doc.get("evalSet") is True:   # 監査02: 評価用の声を覚えると、評価用のデータがほかの文書の名前付けに使われる
        raise _errors.ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
    want = req.get("names")
    if not isinstance(want, list) or not all(isinstance(n, str) for n in want):   # 画面と API の版はそろえて上げる(古い形は受けない = 確認を飛ばして覚えない)
        raise _errors.ApiError("bad_request", "覚える人の指定(names)がありません。画面を読み込み直してから、もう一度押してください", 400)
    plan = voice_learn_plan(doc)
    names = [n for n in dict.fromkeys(str(x).strip()[:60] for x in want) if n in plan["groups"]]
    if not names:
        gen = [r["name"] for r in plan["refused"] if r["reason"] == "generic"]
        raise _errors.ApiError("no_names", "覚えられる話者がいません。校正済みの行(1秒以上・音のメモなし)がある、名前を付けた話者の声だけを覚えます"
                       "(「話者1」のような仮の名前%sは覚えません)" % ("・「%s」のような一般的な名前" % "」「".join(gen[:3]) if gen else ""), 400)
    _tools.check_source(doc.get("sourcePath"))
    emb = _voice_emb(req, doc)
    same = {str(x) for x in req.get("confirmSame") or [] if isinstance(x, str)}
    voices = _diar.load_voices(emb)
    ask = [n for n in names if _voice_name(voices, n) in voices and n not in same]
    if ask:   # 監査18: 既にある名前に足すのは「同じ人」と確かめたときだけ(別人の声が混ざると、その名前の照らし合わせが外れる)
        raise _errors.ApiError("confirm_same", "「%s」の声はもう覚えています。同じ人か確かめてから、もう一度押してください" % "」「".join(ask), 409, extra={"names": ask})
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["voice-learn"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    return {"tid": tid, "embedding": emb, "names": names, "confirmSame": sorted(same & set(names)),
            "title": _heavy.job_title("声を覚える: ", doc)}


def run_voice_learn(job):
    spec = job["spec"]
    with _heavy.job_temp_wav(job) as wav:
        doc = store.read_transcript(spec["tid"])
        if doc.get("evalSet") is True:   # 待っている間に評価用へ変えた場合も断る(監査02)
            raise _errors.ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
        try:
            src = _tools.check_source(doc.get("sourcePath"))
        except _errors.ApiError:
            if not _voiceclips.index(spec["tid"]):
                raise
            src = None   # 元の動画は片付いた: 切り出して残した行の音で覚える(voiceclips。10-24)
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        plan = voice_learn_plan(doc, spec.get("rows"))   # 読み直した文書で決め直し、確認した人(spec["names"])との積だけを覚える(確認のあとで名前を付けた人を黙って覚えない)。
        # spec["rows"] = 確かめるの声のカードで名前を答えた行(by "check"。V1 V2c)
        grp = {n: plan["groups"][n] for n in spec.get("names") or [] if n in plan["groups"]}
        if not grp:
            raise _errors.ApiError("no_names", "覚えられる話者の行がありません(待っている間に名前・校正済みの印が変わった可能性があります)", 400)
        if not _diar.models_ready():
            raise _errors.ApiError("no_sherpa", "声を覚えるには話者判別の部品(sherpa-onnx)が要ります。フォルダ内の install-diarize.bat を実行してください", 400)
        people = sorted(grp)
        if src:
            hints = {"sourcePath": src, "start": start, "end": end}
        else:
            if not _voiceclips.timeline_wav(spec["tid"], wav, start, end):
                raise _errors.ApiError("no_file", "元の動画も、切り出した行の音もありません", 400)
            hints = {"start": start, "wavReady": True}
        vecs = _diar.embed(job, spec, wav, [grp[n][0] for n in people], hints)   # 音声の取り出し → モデルの取得 → 声の特徴
        _slots.check_cancel(job)
        segs = {str(g.get("id")): g for g in doc.get("segments") or () if isinstance(g, dict)}
        row_keys = [(n, rid, _yschemas.num_or(segs[rid].get("start")), _yschemas.num_or(segs[rid].get("end")))
                    for n in people for rid in plan["rowIds"].get(n) or () if rid in segs]
        row_keys = [k for k in row_keys if k[2] is not None and k[3] is not None and k[3] > k[2]]
        # 行ごとの特徴も同じ音で取って控える(あとで 1 行外すのに音が要らないように。10-25 ユーザー「後で取り直すのは面倒」)
        row_vecs = _diar.embed(job, spec, wav, [[(a, b)] for _n, _r, a, b in row_keys], {"start": start, "wavReady": True}) if row_keys else []
        _slots.check_cancel(job)
        learned = []
        with _diar.voices_edit(spec["embedding"]) as voices:   # 変わったときだけ書く(登録簿のロックの中。上限を超えたら書かない)
            same = set(spec.get("confirmSame") or [])
            for n, v in zip(people, vecs):
                if not v:
                    continue
                at = _voice_name(voices, n)   # 登録簿に同じ人(person_key が同じ)がいれば、その名前に足す
                old = voices.get(at)
                if old and n not in same:   # 待っている間にほかで同じ名前を覚えた(確かめていない人の声には足さない)
                    _txbase.add_warning(job, "「%s」の声は、待っている間にほかで覚えられたので足しませんでした(同じ人なら、もう一度「声を覚える」を押してください)" % n)
                    continue
                voices[at] = _diar.merge_voice(old, v, len(grp[n][0]), grp[n][1], spec["tid"],   # 前に覚えた声とは使った長さで重みを付けて混ぜる
                                              by=spec.get("by"), row_ids=plan["rowIds"].get(n) if spec.get("rows") is not None else None,
                                              short=_vm.is_short(doc.get("sourcePath")),   # ショート由来は重み半分・ショートだけなら仮(10-25)
                                              provisional=n in (spec.get("provisional") or ()))   # まだ声が無い人を少しの材料で = 仮(10-25)
                learned.append(n)
            if len(voices) > _VOICE_MAX_PEOPLE:
                raise _errors.ApiError("too_many", "覚えられる声は %d 人までです(使わない声を消してください)" % _VOICE_MAX_PEOPLE, 400)
        if not learned:
            raise _errors.ApiError("no_voice", "声の特徴を取り出せませんでした(行が短すぎる・音声が無い可能性があります)", 400)
        short = _vm.is_short(doc.get("sourcePath"))
        for n in learned:
            items = {"%s#%s" % (spec["tid"], rid): {"vec": [round(x, 6) for x in rv], "sec": round(b - a, 2), "short": bool(short)}
                     for (nn, rid, a, b), rv in zip(row_keys, row_vecs) if nn == n and rv}
            _diar.save_row_vectors(spec["embedding"], _voice_name(_diar.load_voices(spec["embedding"]), n), items)
        job["learned"] = learned
        job["speakers"] = len(learned)
        _heavy.job_done(job, spec["tid"])


def voices_summary():
    """覚えている声の一覧(特徴そのものは返さない)。{判別モデル: [{"name", "rows", "sec", "updatedAt"}]}"""
    out = {}
    for emb in _diar.embeddings():
        v = _diar.load_voices(emb)
        if v:
            out[emb] = sorted(({"name": n, "rows": int(x.get("rows") or 0), "sec": float(x.get("sec") or 0.0), "updatedAt": int(x.get("updatedAt") or 0),
                                "generic": is_generic_speaker_name(n)}   # 一般的な名前で前に覚えた声(消さない。一覧で「忘れることをおすすめします」と出す)
                               for n, x in v.items()), key=lambda r: r["name"])
    return out


def delete_voice(emb, name):
    if emb not in _diar.embeddings():
        raise _errors.ApiError("bad_request", "判別モデルの指定が正しくありません", 400)
    with _diar.voices_edit(emb) as voices:   # 消したら書く(登録簿のロックの中)
        if name not in voices:
            raise _errors.ApiError("not_found", "その声は覚えていません", 404)
        del voices[name]


# ---------- 話者ごとの字幕の見た目を外から入れる(入口のまとめて実行。notes:docs/spec/friend.md の 2-8・2-11) ----------
# POST /api/speakers/sub {"id": 文書の id, "styles": {"名前": {"color": "#RRGGBB" か "RRGGBB"}}} -> {"ok": true, "applied": [名前…]}
# 友人の依頼で指定した色を、話者分離のあとに文書の話者へ覚える(PC の「自分の色」には入れない)。名前が合った人(person_key で比べる)だけ。
# 合う人がいなくても 200(applied が空)。履歴の控えは _recognize_voices が名前を付けるときと同じく残さない(話者の見た目だけの書き込み)
SPKSUB_SKIP_KINDS = ("alt", "normalize")   # この文書を書き換えないジョブ(2つ目のエンジン・30fps の作り直し)は「最中」に数えない


def _spksub_busy(tid):
    return _heavy.doc_busy(tid, SPKSUB_SKIP_KINDS)


def speakers_sub_apply(obj):
    """POST /api/speakers/sub: 名前が合った話者の字幕の見た目 sub に色を重ねる -> {"ok": True, "applied": [名前…]}。処理中なら 409"""
    tid = str(obj.get("id") or "") if isinstance(obj, dict) else ""
    if not _yschemas.TID_RE.match(tid):
        raise _errors.ApiError("bad_request", "文書の指定が正しくありません", 400)
    styles = obj.get("styles")
    if not isinstance(styles, dict) or len(styles) > 50:
        raise _errors.ApiError("bad_request", "styles は {名前: {color}} の形で送ってください(50 人まで)", 400)
    want = {}
    for name, st in styles.items():
        if not isinstance(name, str) or not isinstance(st, dict) or len(name) > 200 or any(ord(ch) < 32 for ch in name):
            raise _errors.ApiError("bad_request", "styles の名前・中身の形が正しくありません", 400)
        if "color" in st and store._sub_color(st["color"]) is None:
            raise _errors.ApiError("bad_request", "字幕の色は 16 進 6 桁(#RRGGBB)で送ってください: %s" % str(st["color"])[:20], 400)
        one = store.sanitize_sub_style(st)   # 知らない鍵は黙って捨てる(新しい入口が古い編集へ送っても、色までは効く)
        key = _textutil.person_key(name)
        if one and key:
            want[key] = one
    with store._save_lock:   # 読み直し〜書き込みは保存と同じロックの中(_recognize_voices と同じ)
        doc = store.read_transcript(tid)
        if _spksub_busy(tid):
            raise _errors.ApiError("busy", "この文字起こしは処理中です(話者判別などが終わってから、もう一度送ってください)", 409)
        applied = []
        for s in doc.get("speakers") or []:
            if not isinstance(s, dict) or _yschemas.other_speaker(s):
                continue
            one = want.get(_textutil.person_key(s.get("name")))
            if one:
                s["sub"] = dict(store.sanitize_sub_style(s.get("sub")) or {}, **one)
                applied.append(str(s.get("name") or ""))
        if applied:
            doc["updatedAt"] = max(int(time.time() * 1000), int(_yschemas.num_or(doc.get("updatedAt"), 0) or 0) + 1)
            store.commit(tid, doc, why="speaker_sub")
    return {"ok": True, "applied": applied}
