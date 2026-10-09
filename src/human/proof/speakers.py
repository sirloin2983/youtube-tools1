# -*- coding: utf-8 -*-
"""② 人の操作の層 human/proof: 話者判別の結果を文書へ(apply_diarization・1 人指定 single_speaker・守る行 diar_keep_row)・判別のジョブ(validate_diarize・
run_diarize)・重なりと抜けの所の空の行の下書き(ovdraft_)・文字起こしのあとの自動の判別(autodiar_)・話者の声を覚える(覚えた声の置き場所・
recognize_voices・voice_learn_plan・run_voice_learn)・話者ごとの字幕の見た目(speakers_sub_apply)。

役割で組み直す RS2-9(2026-10-10)に編集の src/editor/ed_speakers.py から移した(中身は同じ。段10 で editor/serve.py から分けた部品)。
判別の計算・判別の記録・声の特徴と照らし合わせは pipeline/transcribe/diarize.py へ分けた(ここからは `diarize.名前` で呼ぶたびに読む =
テストの patch.object(S, "has_sherpa"・"ensure_diar_models"・"embed_groups"・"write_diar") が届く)。
旧い名前 ed_speakers.名前 は editor/ed_speakers.py(転送だけの殻。RS5 で消す)が、serve.名前 は serve の名前の受付がここへ回す。
評価用の文書の名前の候補(eval の ed_drill.drill_candidates)は読まず、serve が set_context_namer で登録する口を呼ぶたびに引く(② から ④ を読まない)。
editor の部品は裸の名前で読む(human の ed_store・ed_learn は層の向きが許す)。後処理 fill は pipeline/transcribe の部品を fill.名前 で呼ぶたびに読む(RS2-9)。
"""
import bisect
import json
import os
import re
import threading
import time
import unicodedata

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, schemas as _yschemas, tools as _tools, workdata as _workdata  # noqa: E402
from pipeline.transcribe import backend as _backend, diarize, recognize  # noqa: E402   本物と疑似の差し込み口・判別の計算(呼ぶたびに diarize.名前 で読む)・音声の取り出し
from pipeline.transcribe import txbase as _txbase, worker_client  # noqa: E402   印・ロガー・ジョブの注意・環境変数のスイッチ / 疑似のワーカーの判定 worker_fake
from pipeline.transcribe import fill  # noqa: E402   判別のあと、定型の幻覚で声の無い行を捨てる fill_clean_turns(0.60.0。呼ぶたびに fill.名前 で読む)
import ed_learn  # noqa: E402,F401   設定(diarSmooth・diarEmb)
import ed_store  # noqa: E402,F401   文書の読み書き・保存のロック・控え

# ---------- serve が登録する口(RS2-9。eval の ed_drill を ② から読まない) ----------
_namer = {}


def set_context_namer(fn):
    """評価用の文書の「動画の手がかり」の名前の候補を返す関数 fn(tid) -> 名前 or None(eval の ed_drill.drill_candidates の suggest =
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


def diar_smooth_setting():
    """設定 diarSmooth(既定オフ)"""
    return ed_learn.load_settings().get("diarSmooth") is True


def apply_diarization(tid, turns, offset, requested, emb=diarize.DIAR_EMB_DEFAULT, auto=None, smooth=False):
    """最新の文字起こしを読み直して話者を書き込む(判別中に行を編集されていても、時刻で割り当てるので矛盾しない)。
    読み直し〜書き込みは保存と同じロックの中で行う(間に画面の保存が挟まると、その保存が黙って上書きされるため)。
    auto(文字起こしのあとの自動の判別。v0.50.0)なら文書の diarization と diar.json に印を残す(画面の「自動で付けた」の案内・人の最終との比べ)。
    smooth = 短い 1 行だけ別の人になるのをならす(S2。smooth_speakers。行の話者だけ。turns・overlaps はそのまま記録する)"""
    with ed_store._save_lock:
        return _apply_diarization(tid, turns, offset, requested, emb, auto, smooth)


def _spk_ids(doc):
    """文書の話者の id の集まり(文字列)"""
    return {str(s.get("id")) for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}


def diar_keep_row(g, ids):
    """話者判別のやり直し・1人指定・「全行をこの人に」で話者を変えない行(2026-10-05): 字幕に出さない行(noSub)・
    組み込みの話者「ゲーム音声など」の行・音のメモ「声が重なる」(overlap)が付いていて話者のある行(手で作った重なる行を守る)・
    機械の下書きのままの空の行(重なりの所に置いた行。判別は行を作り直さないので、そのまま残して話者も変えない。話者なしの下書きを主の話者で埋めない)。
    ids = 文書の話者の id の集まり(無い id の話者は守らない)"""
    if not isinstance(g, dict):
        return False
    sp = str(g.get("speaker") or "")
    if _yschemas.no_sub_row(g) or sp == _yschemas.OTHER_SPK_ID or _yschemas.blank_draft_row(g):
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


def _apply_diarization(tid, turns, offset, requested, emb, auto=None, smooth=False):
    doc = ed_store.read_transcript(tid)
    dropped = fill.fill_clean_turns(doc, turns, offset)   # 定型の幻覚で声の区間と重ならない行を捨てる(autoFill の文書だけ。0.60.0)
    segs = doc.get("segments") or []
    ids = _spk_ids(doc)
    keep = [diar_keep_row(g, ids) for g in segs]   # 手で決めた行(字幕に出さない・ゲーム音声など・重なりのメモつき)は話者を変えない
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)   # 元の動画の秒(割り当て・ならし・記録で同じ並び)
    full = diarize._assign(segs, ts)
    raw, ratios = [r[:3] for r in full], [r[3] for r in full]
    smoothed = diarize.smooth_speakers(segs, raw, ts, keep, ratios) if smooth else None
    res = [(smoothed[i], r[1], True) if smoothed and i in smoothed else r for i, r in enumerate(raw)]   # ならした行は「不確か」の印を残す
    spent = {}
    for sg, (sp, _, _), k in zip(segs, res, keep):
        if sp is not None and not k:
            spent[sp] = spent.get(sp, 0.0) + max(0.0, sg["end"] - sg["start"])
    order = sorted(spent, key=lambda k: -spent[k])[:MAX_SPEAKERS]   # 話した時間が長い人から「話者1」「話者2」…
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
    ed_store.backup_doc(tid, "diarize")   # 直前の状態を1世代だけ残す・履歴にも残す(画面の「履歴」から戻せる)
    doc.update({"speakers": speakers, "segments": segs, "updatedAt": int(time.time() * 1000),
                "diarization": dict({"engine": "sherpa-onnx", "embedding": emb, "requested": requested, "found": len(order), "unsure": unsure, "at": int(time.time() * 1000)},
                                    **({"auto": True} if auto else {}), **({"smoothed": len(smoothed)} if smoothed is not None else {}),
                                    **({"fillDropped": dropped} if dropped else {}))})
    ed_store.write_doc(tid, doc)
    diarize._record_diar(tid, diarize.build_diar_run(segs, raw, turns, offset, requested, emb, idmap, auto, smoothed, ratios))   # 機械の最初の結果(人が直す前)を <id>.diar.json に
    return len(order), unsure


def validate_diarize(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
    if not doc.get("segments"):
        raise _errors.ApiError("empty", "行がないため、話者を判別できません", 400)
    _tools.check_source(doc.get("sourcePath"))
    try:
        n = int(req.get("numSpeakers") or 0)
    except (TypeError, ValueError):
        n = 0
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["diarize"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識)の最中です", 409)
    emb = str(req.get("embedding") or diarize.DIAR_EMB_DEFAULT)
    names = []   # 出てくる人の名前(友人からの依頼の「話す人」。2026-10-01)
    for x in req.get("names") if isinstance(req.get("names"), list) else []:
        s = str(x or "").strip()[:60] if isinstance(x, str) else ""
        if s and not any(ord(ch) < 32 for ch in s) and s not in names and not DEFAULT_SPK_NAME.match(s):
            names.append(s)
    return {"tid": tid, "numSpeakers": n if 1 <= n <= 10 else 0, "names": names[:10], "embedding": emb if emb in diarize.DIAR_EMBS else diarize.DIAR_EMB_DEFAULT, "title": _heavy.job_title("話者判別: ", doc),
            "recognize": req.get("recognize") is not False,   # A-3: 覚えている声と照らし合わせる(既定オン)
            "smooth": req["smooth"] if isinstance(req.get("smooth"), bool) else diar_smooth_setting()}   # S2: 細切れをならす(要求に無ければ設定 diarSmooth。既定オフ)


def single_speaker(tid, name):
    """話す人が1人: 判別せずに全部の行をその人に(名前が無ければ「話者1」)。-> 行の数。
    手で決めた行(diar_keep_row = 字幕に出さない・ゲーム音声など・重なりのメモつき)は話者を変えない(2026-10-05)"""
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        segs = doc.get("segments") or []
        ids = _spk_ids(doc)
        keep = [diar_keep_row(g, ids) for g in segs]
        kept_sps, remap = _diar_kept_speakers(doc, segs, keep, {"S1"})
        same = _spk_name_key(name or "話者1")
        for s in [s for s in kept_sps if s.get("id") != _yschemas.OTHER_SPK_ID and _spk_name_key(s.get("name")) == same]:   # 同じ名前の人は 1 人にまとめる
            remap.update({k: "S1" for k, v in remap.items() if v == s["id"]})
            kept_sps.remove(s)
        for sg, k in zip(segs, keep):
            if k:
                if sg.get("speaker"):
                    sg["speaker"] = remap.get(str(sg["speaker"]), sg["speaker"])
                continue
            sg["speaker"] = "S1"
            sg["flag"] = "、".join(x for x in str(sg.get("flag", "")).split("、") if x and x not in _txbase.SPK_FLAGS)[:100]
        ed_store.backup_doc(tid, "diarize")
        doc.update({"speakers": [{"id": "S1", "name": name or "話者1", "color": SPK_COLORS[0]}] + kept_sps, "segments": segs, "updatedAt": int(time.time() * 1000),
                    "diarization": {"engine": "single", "requested": 1, "found": 1, "unsure": 0, "at": int(time.time() * 1000)}})
        ed_store.write_doc(tid, doc)
        diarize._record_diar(tid, {"at": int(time.time() * 1000), "engine": {"name": "single", "requested": 1}, "offset": 0.0, "turns": [], "overlaps": [],
                                   "labelMap": {"0": "S1"}, "speakers": 1,
                                   "rows": {str(sg.get("id")): {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False} for sg in segs},
                                   "voices": {"checked": False, "speakers": {"S1": {"label": 0, "decided": name, "by": "request", "reason": None}} if name else {}}})
        return len(segs)


def _diarize_job_real(job, spec, wav):
    """判別のジョブの本物の道(backend の口の real): 部品の確かめ → モデルの取得 → ワーカーで判別 -> [(開始, 終了, 話者番号)]"""
    if not diarize.has_sherpa():
        raise _errors.ApiError("no_sherpa", "話者判別の部品(sherpa-onnx)が入っていません。フォルダ内の install-diarize.bat(Mac は install-diarize.command)を実行してください", 400)
    job["state"] = "loading"
    diarize.ensure_diar_models(job, spec["embedding"])
    job["state"], job["phase"], job["progress"] = "running", "話者を判別中(CPU。長い音声は時間がかかります)", 0.0
    try:
        return diarize.diarize_real(job, wav, spec["numSpeakers"], spec["embedding"])
    except (_heavy.Cancelled, _errors.ApiError):
        raise
    except Exception as e:
        raise _errors.ApiError("diar_failed", "話者の判別に失敗しました: %s %s" % (e.__class__.__name__, str(e)[:150]), 500)


def run_diarize(job):
    spec = job["spec"]
    if spec.get("auto") and autodiar_skip_at_start(job):   # 自動の判別: 待っている間に人が話者を付けた・確かめ済みにしたなら何もしない(v0.50.0)
        return
    if spec.get("numSpeakers") == 1:   # 1人なら判別しない(音声も取り出さない)
        try:
            single_speaker(spec["tid"], (spec.get("names") or [""])[0])
            job["speakers"], job["unsure"] = 1, 0
            job["named"] = [{"speaker": "S1", "name": spec["names"][0], "score": None}] if spec.get("names") else []
            _heavy.job_done(job, spec["tid"])
        except Exception as e:
            job["state"], job["error"], job["phase"] = "error", "話者を付けられませんでした: %s %s" % (e.__class__.__name__, str(e)[:150]), "失敗"
        return
    with _heavy.job_temp_wav(job) as wav:
        doc = ed_store.read_transcript(spec["tid"])
        src = _tools.check_source(doc.get("sourcePath"))
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        span = (end if end else (_tools.media_duration(src) or 0.0)) - start
        if span > diarize.MAX_DIAR_SEC:
            raise _errors.ApiError("too_long", "話者判別は3時間までの範囲で使えます。範囲を分けて文字起こししてください", 400)
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        recognize.extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
        total = _tools.media_duration(wav) or span
        turns = _backend.select().diarize(job, spec, wav, total, _diarize_job_real)   # 疑似は eval/fake/fake_asr の diarize_fake(RS2-9)
        _heavy.check_cancel(job)
        auto = {"eval": bool(spec.get("autoEval")), "contextName": spec.get("contextName") or None} if spec.get("auto") else None
        job["speakers"], job["unsure"] = apply_diarization(spec["tid"], turns, start, spec["numSpeakers"], spec["embedding"], auto, bool(spec.get("smooth")))
        if spec.get("recognize", True):   # A-3: 覚えている声と照らし合わせて、仮の名前(話者n)に名前を付ける。失敗しても判別の結果は残す
            try:
                job["named"] = recognize_voices(job, spec["tid"], wav, start, spec["embedding"], spec.get("names") or None)
            except _heavy.Cancelled:
                raise
            except Exception as e:
                _txbase.log.warning("声の照らし合わせに失敗: %s %s", e.__class__.__name__, str(e)[:200])
                job["voiceError"] = "覚えている声との照らし合わせに失敗しました(話者の判別の結果はそのまま): %s" % str(e)[:120]
                try:
                    diarize.update_diar_voices(spec["tid"], {"checked": False, "error": "%s %s" % (e.__class__.__name__, str(e)[:150]), "speakers": {}})
                except Exception:
                    pass
        if spec.get("contextName"):   # 評価用の自動の判別: 声で名前が付かなかった人のうち、いちばん長く話した人に動画の手がかりの名前(v0.50.0)
            try:
                hit = autodiar_name_by_context(spec["tid"], spec["contextName"])
                if hit:
                    job["named"] = list(job.get("named") or []) + [hit]
            except Exception as e:   # 名前が付けられなくても判別の結果は残す
                _txbase.log.warning("動画の手がかりで名前を付けられませんでした: %s %s", e.__class__.__name__, str(e)[:200])
        _heavy.job_done(job, spec["tid"])


# ---------- 重なりの所の空の行の下書き(2026-10-05。plan/line-b-overlap.md の 5-3 の C・6-2 の 1・2) ----------
# 同時にしゃべっている所は、認識が片方しか書かない。判別の記録(diar.json の latest)には、声があったのに行が付かなかった区間が残るので、
# そこを「時刻(と分かれば話者)を入れた空の行」の候補にする。ここは候補を数えるだけ(文書も diar.json も書かない)。行を足すのは画面(元に戻すが効く・保存はいつもの道)。
# 候補 = 判別の声の区間(同じラベルの区間はすき間 OVDRAFT_JOIN 以下でつなぐ)のうち、主の話者(区間の合計がいちばん長いラベル)でないもの:
#   (a) labelMap に無いラベル(行が 1 つも付かなかった声)→ speaker ""(誰か分からない)・why "unassigned"
#   (b) labelMap にあるラベルで、ほかの話者の区間と重なる(overlaps に入る部分がある)→ speaker = その話者の id・why "overlap"
# 区間の半分以上が「書いてある」(下の _ovdraft_cover_rows)なら出さない = 2 回押しても増えない。出す区間は、両端の書いてある所を削る(同じ話者の行と重ねて赤くしない)。
# 時刻は元の動画の秒(build_diar_run が offset を足して書く)= 行を直したあとの文書にもそのまま使える
OVDRAFT_JOIN = 0.3    # 同じラベルの区間をつなぐすき間(秒)
OVDRAFT_MIN = 0.5     # これより短い区間は出さない(短い相づちは数が多く当たりも悪いので、最初は出さない)
OVDRAFT_MAX = 40      # 1 回に出す数(開始の順。超えた数は more)
OVDRAFT_COVER = 0.5   # 区間のこの割合以上が書いてあれば出さない
OVDRAFT_KIND = "overlap"   # 置いた行の印 draft の値(ytt/schemas の ROW_DRAFT_KINDS の 1 つ)
# 抜け(why "missing"。計画 第2版 E2 の前倒し): 主の話者も含めて、どのラベルの声の区間でも、書いてある所(文字のある行は話者によらず・空の下書き・字幕に出さない行・
# ゲーム音声などの行)と、先に出した重なりの候補を除いた残り。区間の中のすき間(1 人の話の途中で認識が落とした所)も拾うため、区間ごとの「半分以上」ではなく、
# 書いてある所を引いた残りの切れ端ごとに見る。違うラベルの切れ端が重なればつなぐ(話者は長い方)。置いた行の印は OVDRAFT_MISS_KIND(音のメモ overlap は付けない)
OVDRAFT_MISS_MIN = 0.8     # 抜けの切れ端の最短(秒)。息・相づち・行の端の余りを出さない(本物のデータで 0.5・0.8・1.2 を数えて決めた。docs は WORKLOG)
OVDRAFT_MISS_KIND = "missing"
OVDRAFT_GROUPS = ("overlap", "missing")   # 画面で選べるまとまり: overlap = 重なり(why overlap・unassigned)・missing = 抜け
OVDRAFT_REASONS = {
    "no_diar": "話者の判別の記録がありません(「話者を自動で判別」のあとで使えます)",
    "single": "1 人として付けた判別なので、声の区間の記録がありません(人数を「自動」か 2 人以上で判別すると使えます)",
    "no_turns": "判別の記録に声の区間がありません",
}


def _ovdraft_union(spans):
    """[(開始, 終了)] をつなげて開始の順に(重なる・接するものは 1 つに。長さの無い区間は捨てる)"""
    return _yschemas.union_spans((a, b) for a, b in spans if b > a)


def _ovdraft_covered(a, b, union):
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in union if x < b and y > a)


def _ovdraft_trim(a, b, union):
    """両端が書いてある所に入っていれば、その外まで縮める(真ん中の書いてある所はそのまま)"""
    for x, y in union:
        if x <= a < y:
            a = y
    for x, y in reversed(union):
        if x < b <= y:
            b = x
    return a, b


def _ovdraft_cover_rows(segs, ids, speaker):
    """候補の区間を「書いてある」とみなす行の時間(つなげたもの)。speaker = None なら行の付かなかった声(a)、id ならその話者(b)。
    どちらも: 機械の下書きのままの空の行(話者によらず。置いた所)・字幕に出さない行・「ゲーム音声など」の行(別の声として書いてある)。
    (a): 文字のある行のうち、話者の無い行(文書に無い id を含む)と、判別のやり直しで守る行(diar_keep_row = 声が重なるのメモつきの話者のある行)。
    (b): 文字のある行のうち、その話者の行"""
    spans = []
    for g in segs:
        if not isinstance(g, dict):
            continue
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        if a is None or b is None or b <= a:
            continue
        if _yschemas.blank_draft_row(g):
            spans.append((a, b))
            continue
        if not str(g.get("text") or "").strip():
            continue
        sp = str(g.get("speaker") or "")
        if _yschemas.no_sub_row(g) or sp == _yschemas.OTHER_SPK_ID:
            spans.append((a, b))
        elif speaker is None:
            if sp not in ids or diar_keep_row(g, ids):
                spans.append((a, b))
        elif sp == speaker:
            spans.append((a, b))
    return _ovdraft_union(spans)


def ovdraft_candidates(doc, latest, kinds=None):
    """文書(今の行・話者)と diar.json の latest から、空の行の候補。読むだけ。kinds = 出すまとまり(OVDRAFT_GROUPS の部分。None は全部)。
    -> {"items": [{start, end, speaker: 話者の id か "", label, why: "unassigned" | "overlap" | "missing", draft: 置く行の印}](開始の順・選んだまとまりで OVDRAFT_MAX まで),
        "more": 超えた数, "counts": {"overlap": 重なり(why overlap・unassigned)の数, "missing": 抜けの数}(kinds によらず全部・上限の前),
        "reason": 出せない理由(文) か None, "reasonCode": no_diar | single | no_turns | None}。
    同じ所は二重に出さない(重なり overlap → unassigned → 抜け missing の順に決める)"""
    def empty(code):
        return {"items": [], "more": 0, "counts": {g: 0 for g in OVDRAFT_GROUPS}, "reason": OVDRAFT_REASONS[code], "reasonCode": code}
    if not isinstance(latest, dict):
        return empty("no_diar")
    eng = latest.get("engine") if isinstance(latest.get("engine"), dict) else {}
    if eng.get("name") == "single":
        return empty("single")
    turns = []
    for t in latest.get("turns") or []:
        if not isinstance(t, dict) or t.get("label") is None:
            continue
        a, b = _yschemas.num_or(t.get("start")), _yschemas.num_or(t.get("end"))
        if a is not None and b is not None and b > a:
            turns.append((a, b, t["label"]))
    if not turns:
        return empty("no_turns")
    lmap = {str(k): str(v) for k, v in (latest.get("labelMap") or {}).items() if v} if isinstance(latest.get("labelMap"), dict) else {}
    ovl = _ovdraft_union((_yschemas.num_or(x[0]), _yschemas.num_or(x[1])) for x in latest.get("overlaps") or []
                         if isinstance(x, (list, tuple)) and len(x) >= 2 and _yschemas.num_or(x[0]) is not None and _yschemas.num_or(x[1]) is not None)
    total = {}
    for a, b, lb in turns:
        total[str(lb)] = total.get(str(lb), 0.0) + (b - a)
    main = max(total, key=lambda k: total[k])   # 主の話者(ほかの声が乗っているだけの側。書かれている側なので出さない)
    joined = []   # [(開始, 終了, ラベル)] 同じラベルの区間をつないだもの
    for lb in total:
        if lb != main:
            joined += [tuple(j) for j in _join_label_spans(sorted(t for t in turns if str(t[2]) == lb))]
    lo = _yschemas.num_or(doc.get("start"), 0.0) or 0.0
    hi = _yschemas.num_or(doc.get("end"))
    dur = _yschemas.num_or(doc.get("duration"))
    hi = min(x for x in (hi, dur, float("inf")) if x is not None and x > 0)
    segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
    ids = _spk_ids(doc)
    covers = {}
    items = []
    for a, b, lb in sorted(joined):
        a, b = max(a, lo), min(b, hi)
        if b - a < OVDRAFT_MIN:
            continue
        sp = lmap.get(str(lb))
        if sp is not None and _ovdraft_covered(a, b, ovl) <= 0.01:   # (b) は、ほかの話者の区間と重なっている声だけ
            continue
        if sp not in covers:   # (a) は None
            covers[sp] = _ovdraft_cover_rows(segs, ids, sp)
        union = covers[sp]
        if _ovdraft_covered(a, b, union) >= OVDRAFT_COVER * (b - a):
            continue
        a2, b2 = _ovdraft_trim(a, b, union)
        if b2 - a2 < OVDRAFT_MIN:
            continue
        items.append({"start": round(a2, 2), "end": round(b2, 2), "speaker": sp if sp in ids else "", "label": lb,
                      "why": "unassigned" if sp is None else "overlap", "draft": OVDRAFT_KIND})
    items += _ovdraft_missing(turns, lmap, ids, segs, items, lo, hi)
    counts = {g: sum(1 for x in items if _ovdraft_group(x) == g) for g in OVDRAFT_GROUPS}
    want = set(OVDRAFT_GROUPS if kinds is None else [k for k in kinds if k in OVDRAFT_GROUPS])
    items = sorted((x for x in items if _ovdraft_group(x) in want), key=lambda x: (x["start"], x["end"]))
    return {"items": items[:OVDRAFT_MAX], "more": max(0, len(items) - OVDRAFT_MAX), "counts": counts, "reason": None, "reasonCode": None}


def _join_label_spans(ts):
    """同じラベルの区間 ts = [(開始, 終了, ラベル)](開始の順)を、すき間 OVDRAFT_JOIN 以下でつなぐ -> [[開始, 終了, 最初のラベル]]。
    重なりの候補(ovdraft_candidates)と抜けの候補(_ovdraft_missing)が同じつなぎ方を使う"""
    out = []
    for a, b, x in ts:
        if out and a - out[-1][1] <= OVDRAFT_JOIN:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b, x])
    return out


def _ovdraft_group(x):
    return "missing" if x.get("why") == "missing" else "overlap"


def _ovdraft_cover_any(segs):
    """抜けの覆い: 文字のある行(話者によらない)・機械の下書きのままの空の行・字幕に出さない行・ゲーム音声などの行"""
    spans = []
    for g in segs:
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        if a is None or b is None or b <= a:
            continue
        if (str(g.get("text") or "").strip() or _yschemas.blank_draft_row(g) or _yschemas.no_sub_row(g)
                or str(g.get("speaker") or "") == _yschemas.OTHER_SPK_ID):
            spans.append((a, b))
    return _ovdraft_union(spans)


def _ovdraft_cut(a, b, union, ends=None):
    """[a, b] から union(開始の順・重ならない)を引いた残り [(開始, 終了)]。ends = union の終わりの並び(渡せば二分探索で始める。長い文書でも重くしない)"""
    out, cur = [], a
    for k in range(bisect.bisect_right(ends, a) if ends is not None else 0, len(union)):
        x, y = union[k]
        if x >= b:
            break
        if y <= cur:
            continue
        if x > cur:
            out.append((cur, x))
        cur = max(cur, y)
        if cur >= b:
            break
    if cur < b:
        out.append((cur, b))
    return out


def _ovdraft_missing(turns, lmap, ids, segs, prior, lo, hi):
    """抜けの候補(why missing)。turns = [(開始, 終了, ラベル)]・prior = 先に決めた重なりの候補(同じ所は二重に出さない)。
    ラベルごとに区間をつなぎ(OVDRAFT_JOIN)、書いてある所と prior を引いた切れ端を、違うラベルどうしで重なればつないで、OVDRAFT_MISS_MIN 以上を出す"""
    cover = _ovdraft_union(_ovdraft_cover_any(segs) + [(x["start"], x["end"]) for x in prior])
    ends = [y for _, y in cover]
    by_label = {}
    for t in sorted(turns):
        by_label.setdefault(str(t[2]), []).append(t)
    pieces = []   # [(開始, 終了, ラベル)]
    for ts in by_label.values():
        for a, b, x in _join_label_spans(ts):
            pieces += [(p, q, x) for p, q in _ovdraft_cut(max(a, lo), min(b, hi), cover, ends)]
    groups = []   # [[開始, 終了, {ラベル: 秒}]]
    for a, b, lb in sorted((p for p in pieces if p[1] > p[0]), key=lambda p: (p[0], p[1], str(p[2]))):
        if groups and a < groups[-1][1]:
            g = groups[-1]
            g[1] = max(g[1], b)
            g[2][lb] = g[2].get(lb, 0.0) + (b - a)
        else:
            groups.append([a, b, {lb: b - a}])
    out = []
    for a, b, secs in groups:
        if b - a < OVDRAFT_MISS_MIN:
            continue
        best = max(secs, key=lambda k: (secs[k], str(k)))
        sp = lmap.get(str(best))
        out.append({"start": round(a, 2), "end": round(b, 2), "speaker": sp if sp in ids else "", "label": best, "why": "missing", "draft": OVDRAFT_MISS_KIND})
    return out


def ovdraft_for_doc(tid, kinds=None):
    """GET /api/overlap-drafts?id=&kinds= : 保存済みの文書と判別の記録で候補を数える(読むだけ)。文書が無ければ 404。
    kinds = 「,」区切りのまとまり(overlap・missing。無い・空なら全部。知らない名前は捨てる)。
    -> ovdraft_candidates の結果 + "diarAt"(判別の時刻。記録が無ければ None)"""
    doc = ed_store.read_transcript(tid)
    d = diarize.read_diar(tid)
    latest = d["latest"] if d else None
    ks = None if kinds is None or not str(kinds).strip() else [k.strip() for k in str(kinds)[:100].split(",")]
    out = ovdraft_candidates(doc, latest, ks)
    out["diarAt"] = latest.get("at") if latest else None
    return out


# ---------- 文字起こしのあと、話者を自動で判別する(v0.50.0。評価用は常に・それ以外は設定 autoDiarize) ----------
# 評価ドリルでは全行に話者が要る(評価用のフォルダの「メンバーのフォルダへ移す」条件)ので、評価用の文字起こしのあとは必ず判別のジョブを足し、
# 覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に「動画の手がかり」の名前
# (ed_drill.drill_candidates の suggest = 覚えた声 → 動画の入ったメンバーのフォルダ → 配信の文脈)を付ける。新しい認識の道は作らない(今の diarize のジョブ)。
# 人が付けたものは置き換えない: 文字のある行に1つでも話者があれば何もしない(足すときと、ジョブが動き出すときの両方で確かめる)。
# 判別の部品(sherpa-onnx)が無いときは黙って飛ばす(ログだけ。文字起こしは失敗にしない)。名前は serve.py からも見える(autodiar_ / AUTODIAR_ で始める)
AUTODIAR_BY = "context"   # diar.json の voices の by(動画の手がかりで付けた。覚えた声 = threshold・消去法 = elimination・依頼 = request と並べる)


def autodiar_enabled():
    """環境変数 TRANSCRIBE_AUTO_DIARIZE=off で自動の判別をしない(テスト・困ったとき用。評価用の決まりは変えない)"""
    return not _txbase.env_off("TRANSCRIBE_AUTO_DIARIZE")


def autodiar_ready():
    """判別の部品があるか(疑似のときは常に)。サーバー側では sherpa-onnx を読み込まない(has_sherpa はワーカー側で調べる)。
    テスト用の worker-fake(ワーカーの中だけ偽のモデル)では使わない(判別は本物の経路 = モデルの取得になるため)"""
    if _backend.select().name == "fake":
        return True
    return not worker_client.worker_fake() and diarize.has_sherpa()


def autodiar_why_not(doc):
    """自動で判別しない理由(None = 判別してよい): empty(文字のある行が無い)・reviewed(評価用で確かめ済み)・
    has_speakers(文字のある行に話者がある = 人か前の判別が付けた。置き換えない)"""
    ids = {s.get("id") for s in doc.get("speakers") or [] if isinstance(s, dict) and s.get("id")}
    rows = [g for g in doc.get("segments") or [] if isinstance(g, dict) and str(g.get("text") or "").strip()]
    if not rows:
        return "empty"
    if doc.get("evalSet") is True and isinstance(doc.get("evalReviewed"), dict):
        return "reviewed"
    if any(g.get("speaker") in ids and not diar_keep_row(g, ids) for g in rows):   # 守る行(ゲーム音声など・字幕に出さない・重なりのメモ)は判別で変わらないので数えない
        return "has_speakers"
    return None


def autodiar_enqueue(tid, batch=False):
    """自動の判別のジョブを足す(人数 自動・覚えた声との照合あり)。評価用なら名前の候補(suggest)も渡す。
    -> {"job": ジョブ, "name": 名前の候補 or None} か {"skipped": 理由}。足せない(待機列がいっぱい・処理中など)は ApiError。
    batch = 評価用のまとめての文字起こし(ed_evalbatch)が入れた印(spec["evalBatch"]。そちらの待ちの数に入る)"""
    if not autodiar_enabled():
        return {"skipped": "off"}
    if not autodiar_ready():
        _txbase.log.info("話者の自動判別を飛ばしました(判別の部品 sherpa-onnx が無い): %s", tid)
        return {"skipped": "no_sherpa"}
    doc = ed_store.read_transcript(tid)
    why = autodiar_why_not(doc)
    if why:
        return {"skipped": why}
    ev = doc.get("evalSet") is True
    name = None
    if ev:
        try:
            name = str(_context_name(tid) or "").strip()[:30] or None   # serve が登録した口 = ed_drill.drill_candidates の suggest(RS2-9)
        except Exception as e:   # 名簿・ほかのツールのデータが読めなくても判別は始める(名前は付けない)
            _txbase.log.info("話者の名前の候補を決められませんでした: %s %s", tid, str(e)[:150])
        if name and (DEFAULT_SPK_NAME.match(name) or is_generic_speaker_name(name)):
            name = None
    st = ed_learn.load_settings()   # 判別モデルと「細切れをならす」(diarSmooth)を 1 回で読む
    spec = validate_diarize({"tid": tid, "numSpeakers": 0, "recognize": True, "embedding": st.get("diarEmb"), "smooth": st.get("diarSmooth") is True})
    spec.update({"auto": True, "autoEval": ev, "contextName": name,
                 "title": _heavy.job_title("話者判別(自動): ", doc)})
    if batch:
        spec["evalBatch"] = True
    return {"job": _heavy.add_job(spec, "diarize"), "name": name}


def autodiar_after_transcribe(job, spec, tid):
    """文字起こしのジョブ(run_job)の終わり。文書を書いたあと・「完了」にする前に呼ぶ(ドリルが判別の前の文書を開かないよう、間を空けない)。
    評価用は常に・それ以外は設定 autoDiarize。始められなくても文字起こしは成功のまま(job["warnings"])"""
    if not (spec.get("evalSet") or spec.get("autoDiarize")):
        return
    try:
        r = autodiar_enqueue(tid, batch=bool(spec.get("evalBatch")))
        if r.get("skipped") == "no_sherpa" and not spec.get("evalSet"):   # 設定でオンにした人には知らせる(評価用は黙って飛ばす = 人が「全行をこの人に」)
            _txbase.add_warning(job, "話者の判別の部品(sherpa-onnx)が入っていないため、話者は自動で判別しませんでした")
    except _errors.ApiError as e:
        _txbase.add_warning(job, "話者の自動判別を始められませんでした: " + e.message)
    except Exception as e:   # 想定外でも、書き終えた文字起こしのジョブを失敗にしない
        _txbase.log.warning("話者の自動判別を始められませんでした: %s %s %s", tid, e.__class__.__name__, str(e)[:150])


def autodiar_skip_at_start(job):
    """自動の判別のジョブが動き出すとき、もう一度確かめる(待っている間に人が話者を付けた・確かめ済みにした・行が消えた)。
    判別しないなら「完了(判別しませんでした)」にして True"""
    spec = job["spec"]
    try:
        why = autodiar_why_not(ed_store.read_transcript(spec["tid"]))
    except _errors.ApiError as e:
        why = e.code
    if not why:
        return False
    job["autoSkipped"] = why
    _heavy.job_done(job, spec["tid"], "判別しませんでした(" + {"has_speakers": "話者が付いていました", "reviewed": "確かめ済みです", "empty": "文字のある行がありません"}.get(why, why) + ")")
    return True


def autodiar_name_by_context(tid, name):
    """覚えた声で名前が付かなかった(仮の名前 話者n の)話者のうち、話した秒がいちばん長い人に name を付ける(1 人だけならその人)。
    name がもうほかの話者に使われていれば付けない(覚えた声の名前を優先)。読み直し〜書き込みは保存と同じロックの中(recognize_voices と同じ)。
    -> {"speaker", "name", "score": None, "by": "context"} か None。経過は diar.json の voices(_autodiar_record)"""
    nm = str(name or "").strip()[:30]
    key = _spk_name_key(nm)
    hit, reason = None, None
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        sps = [s for s in doc.get("speakers") or [] if isinstance(s, dict)]
        spent = {}
        for g in doc.get("segments") or []:
            if isinstance(g, dict) and g.get("speaker") and str(g.get("text") or "").strip() and not _yschemas.no_sub_row(g):   # 字幕に出さない行(ゲームの声など)は話した秒に数えない
                a, b = _yschemas.num_or(g.get("start"), 0.0) or 0.0, _yschemas.num_or(g.get("end"), 0.0) or 0.0
                spent[g["speaker"]] = spent.get(g["speaker"], 0.0) + max(0.0, b - a)
        left = [s for s in sps if DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and spent.get(s.get("id"), 0.0) > 0]
        if not nm or not sps:
            reason = "no_speakers" if nm else "no_name"
        elif any(_spk_name_key(str(s.get("name") or "")) == key for s in sps):
            reason = "name_in_use"
        elif not left:
            reason = "all_named"
        else:
            pick = max(left, key=lambda s: spent.get(s.get("id"), 0.0))   # 同じ秒なら先の人(話者1 = 判別が長い順に付けた番号)
            pick["name"] = nm
            hit = {"speaker": pick["id"], "name": nm, "score": None, "by": AUTODIAR_BY}
            if isinstance(doc.get("diarization"), dict):
                doc["diarization"]["contextName"] = nm
            doc["updatedAt"] = int(time.time() * 1000)
            ed_store.write_doc(tid, doc)
    _autodiar_record(tid, nm, hit, reason)
    return hit


def _autodiar_record(tid, name, hit, reason):
    """diar.json の最新の voices に、動画の手がかりで付けた名前(speakers[id].by = context)と経過 context = {name, speaker, reason} を書く。
    人の最終(行の speaker・speakers[].name)と、機械が付けた名前を後で比べられるように。書けなくても名前付けは続ける"""
    try:
        with diarize._diar_edit(tid) as d:
            if not d:
                return
            latest = d["latest"]
            v = latest.get("voices") if isinstance(latest.get("voices"), dict) else {"checked": False}
            sp = v.get("speakers") if isinstance(v.get("speakers"), dict) else {}
            if hit:
                one = sp.get(hit["speaker"]) if isinstance(sp.get(hit["speaker"]), dict) else dict(diarize._VOICE_EMPTY, label=diarize._label_of(latest).get(hit["speaker"]))
                one.update({"decided": hit["name"], "by": AUTODIAR_BY, "reason": None})
                sp[hit["speaker"]] = one
            v["speakers"] = sp
            v["context"] = {"name": name, "speaker": hit["speaker"] if hit else None, "reason": reason}
            latest["voices"] = v
    except Exception as e:
        _txbase.log.warning("動画の手がかりの名前の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


# ---------- 話者の声を覚える(A-3。git の履歴(679ff01 以前)の docs/archive/backlog-ui-2026-09-27.md) ----------
# 名前を付けた話者の行の音声から「声の特徴」(sherpa-onnx の話者の埋め込み。判別モデルごとに別)を作って覚え、
# 次からの話者判別のあとで、見つかった話者を覚えている声と比べて名前を付ける。
# 声の特徴は個人を見分けられる情報なので、作業データ(voices/)にだけ置く(リポジトリ・パックには入れない)。
# 声の特徴の計算と照らし合わせ(VOICE_MATCH・embed_groups・match_voices)は pipeline/transcribe/diarize(numpy・sherpa-onnx は認識ワーカーの中だけ)。
# 置き場所は呼ぶたびに作業データ(ytt/workdata の DATA_DIR)の voices(voices_dir)。VOICES_DIR は上書き用(テストが一時フォルダを入れる)。None なら作業データの中。
# RS2-9 の不具合の直し(動きが変わる): 以前は読み込みのときに作り、serve の set_data_dir が直さなかったので、入口から起動すると
# 覚えた声が作業データではなく editor のフォルダの voices に読み書きされていた(判別のモデルの DIAR_DIR だけ直っていた)
VOICES_DIR = None
VOICE_MAX_PEOPLE = 300
DEFAULT_SPK_NAME = re.compile(r"^話者\d+$")   # 話者判別が付けた仮の名前(覚えない・声で付けた名前で置き換えてよい)
_voices_lock = threading.Lock()
# 一般的な名前(監査18。段1・2026-09-29 ユーザー決定): 声を覚えると、別の配信の「本人」「ゲスト」に同じ名前が付いてしまう(人ではなく役の名前)ので覚えない。
# 判定は is_generic_speaker_name の1か所(画面は preview の結果を出すだけ)。比べる前に NFKC・小文字・空白を寄せる(全角の「ＭＣ」・「Speaker 1」も同じに)
GENERIC_SPK_NAMES = frozenset(("本人", "ゲスト", "配信者", "私", "自分", "相手", "司会", "mc", "男性", "女性", "不明", "その他", "視聴者", "ナレーション",
                               "話者", "speaker", "スピーカー", _yschemas.OTHER_SPK_NAME))   # 組み込みの「ゲーム音声など」も人の名前ではない(覚えない・照らし合わせない)
GENERIC_SPK_FORM = re.compile(r"^(?:話者|speaker|spk|スピーカー)?(?:\d+|[a-z])$")   # 話者A・話者1・Speaker 1・英字1文字・数字だけ


def _spk_name_key(name):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or "")).lower())


def is_generic_speaker_name(name):
    k = _spk_name_key(name)
    return bool(k) and (k in GENERIC_SPK_NAMES or bool(GENERIC_SPK_FORM.match(k)))


def voices_dir():
    """覚えた声の置き場所(上書きの VOICES_DIR があればそれ、無ければ作業データの voices。呼ぶたびに決める)"""
    return VOICES_DIR or os.path.join(_workdata.DATA_DIR, "voices")


def voices_path(emb):
    return os.path.join(voices_dir(), emb + ".json")


def load_voices(emb):
    """{名前: {"vec": [...], "rows": 使った行の数, "sec": 使った秒, "updatedAt": ms}}(判別モデル emb ごと)"""
    d = _fsio.read_json_or(voices_path(emb), None, kind=dict)
    v = d.get("voices") if d is not None else None
    if not isinstance(v, dict):
        return {}
    return {str(k)[:60]: x for k, x in v.items() if isinstance(x, dict) and isinstance(x.get("vec"), list) and x["vec"]}


def save_voices(emb, voices):
    os.makedirs(voices_dir(), exist_ok=True)
    _fsio.atomic_write(voices_path(emb), json.dumps({"schema": "ytt-voices/v1", "embedding": emb, "voices": voices}, ensure_ascii=False).encode("utf-8"), fsync_required=True)


def recognize_voices(job, tid, wav, offset, emb, names=None):
    """話者判別のあと: 見つかった話者を覚えている声と比べ、仮の名前(話者n)のままの話者に名前を付ける。-> [{"speaker", "name", "score"}]。
    names(出てくる人の名前。友人からの依頼)があれば、照らし合わせをその名前だけにし、最後に仮の名前の話者と使っていない名前が1つずつ残れば消去法で付ける(score None)。
    照合の経過(点数・2位との差・決まり方・付けなかった理由)は <id>.diar.json の voices に残す(update_diar_voices。書けなくても名前付けは続ける)"""
    all_voices = load_voices(emb)
    voices = {n: v for n, v in all_voices.items() if n in names} if names else all_voices
    got, detail = {}, {}
    if voices:
        doc = ed_store.read_transcript(tid)
        grp = diarize.voice_groups(doc.get("segments") or [], lambda g: "" if _yschemas.no_sub_row(g) or g.get("speaker") == _yschemas.OTHER_SPK_ID else (g.get("speaker") or ""))   # ゲーム音声など・字幕に出さない行は照らし合わせない
        ids = list(grp)
        if ids:
            job["phase"] = "覚えている声と照らし合わせ中"
            vecs = diarize.embed_groups(job, wav, emb, [grp[i][0] for i in ids], offset)
            got, detail = diarize.match_voices_explain(dict(zip(ids, vecs)), voices)

    def record(doc, named):
        """diar.json の voices(話者ごとの経過 + 名前を付けた結果)。失敗しても名前付けには響かせない"""
        try:
            rec = {}
            for s in doc.get("speakers") or []:
                if not isinstance(s, dict):
                    continue
                d = dict(detail.get(s.get("id")) or dict(diarize._VOICE_EMPTY, reason="no_voices" if not voices else "no_rows"))
                hit = next((n for n in named if n["speaker"] == s.get("id")), None)
                if hit:
                    d["decided"], d["by"], d["reason"] = hit["name"], hit.get("by") or ("elimination" if hit["score"] is None else "threshold"), None
                elif d.get("decided"):   # しきい値は通ったが、名前が付かなかった(自分で付けた名前・別の人が使っている名前)
                    d["reason"] = "already_named" if not DEFAULT_SPK_NAME.match(str(s.get("name") or "")) else "name_in_use"
                    d["decided"], d["by"] = None, None
                rec[str(s.get("id"))] = d
            diarize.update_diar_voices(tid, {"checked": True, "embedding": emb, "registered": len(all_voices), "restrictedNames": list(names) if names else None,
                                             "match": diarize.VOICE_MATCH, "margin": diarize.VOICE_MARGIN, "speakers": rec})
        except Exception as e:
            _txbase.log.warning("声の照合の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])

    if not got and not names:
        record(ed_store.read_transcript(tid), [])
        return []
    named = []
    with ed_store._save_lock:   # 読み直し〜書き込みは保存と同じロックの中(話者判別の書き込みと同じ)
        doc = ed_store.read_transcript(tid)
        taken = {str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
        for s in doc.get("speakers") or []:
            hit = got.get(s.get("id")) if isinstance(s, dict) else None
            if hit and DEFAULT_SPK_NAME.match(str(s.get("name") or "")) and hit[0] not in taken:
                s["name"] = hit[0]
                taken.add(hit[0])
                named.append({"speaker": s["id"], "name": hit[0], "score": hit[1], "by": "threshold"})
        if names:   # 消去法: 名前の無い話者と使っていない名前が1つずつなら、その人
            left = [s for s in doc.get("speakers") or [] if isinstance(s, dict) and DEFAULT_SPK_NAME.match(str(s.get("name") or ""))]
            unused = [n for n in names if n not in taken]
            if len(left) == 1 and len(unused) == 1:
                left[0]["name"] = unused[0]
                named.append({"speaker": left[0]["id"], "name": unused[0], "score": None, "by": "elimination"})
        if named:
            doc["updatedAt"] = int(time.time() * 1000)
            ed_store.write_doc(tid, doc)
    record(doc, named)
    return named


VOICE_LEARN_TAGS = ("overlap", "bgm", "unclear")   # この印の行は覚えない(声が重なる・BGM が大きい・聞き取れない。監査17)
EVAL_SET_VOICE_MSG = "評価用の文字起こしでは声を覚えません(評価用のデータを、ほかの文書の話者の名前付けに使わないため)。評価用を外してから行ってください"


def voice_learn_plan(doc):
    """声を覚えるときに使う行(監査17。段1): voice_groups の条件(1秒以上・声が混ざっていない)に加えて、校正済みで、音のメモ(重なり・BGM・聞き取れない)が無い行だけ。
    話者判別のときの照らし合わせ(recognize_voices)は voice_groups のまま(校正前の文書でも名前が付くように。変えない決定)。
    -> {"groups": {名前: ([(開始, 終了)...], 秒)}, "speakers": {名前: [話者の id]}, "refused": [{"name", "speakers", "reason": "generic"|"no_rows"}],
        "skipped": {"unproofed", "tagged", "mixed", "short"}(覚える人の行のうち使わなかった数。理由は 1秒未満 → 混ざる → 音のメモ → 未校正 の順に1つ)}"""
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
    skipped = {"unproofed": 0, "tagged": 0, "mixed": 0, "short": 0}
    ok = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict) or g.get("speaker") not in who:
            continue
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        tags = g.get("tags") if isinstance(g.get("tags"), list) else []
        if a is None or b is None or b - a < diarize.VOICE_MIN_ROW:
            skipped["short"] += 1
        elif _txbase.MIXED_FLAG in str(g.get("flag") or ""):
            skipped["mixed"] += 1
        elif any(t in tags for t in VOICE_LEARN_TAGS):
            skipped["tagged"] += 1
        elif g.get("proofed") is not True:
            skipped["unproofed"] += 1
        else:
            ok.append(g)
    groups = diarize.voice_groups(ok, lambda g: who.get(g.get("speaker")) or "")
    for n, sids in by_name.items():
        if n not in groups:
            refused[n] = {"name": n, "speakers": sids, "reason": "no_rows"}
    return {"groups": groups, "speakers": {n: sids for n, sids in by_name.items() if n in groups},
            "refused": sorted(refused.values(), key=lambda r: r["name"]), "skipped": skipped}


def _voice_emb(req, doc):
    emb = str(req.get("embedding") or (doc.get("diarization") or {}).get("embedding") or diarize.DIAR_EMB_DEFAULT)
    return emb if emb in diarize.DIAR_EMBS else diarize.DIAR_EMB_DEFAULT


def voice_preview(tid, emb):
    """覚える前の確認(GET /api/voices/preview。読むだけ・ジョブを作らない。監査17・18)"""
    doc = ed_store.read_transcript(str(tid or ""))
    emb = _voice_emb({"embedding": emb}, doc)
    plan = voice_learn_plan(doc)
    voices = load_voices(emb)
    people = []
    for n in sorted(plan["groups"]):
        rs, sec = plan["groups"][n]
        old = voices.get(n)
        people.append({"name": n, "speaker": plan["speakers"][n][0], "speakers": plan["speakers"][n], "rows": len(rs), "sec": round(sec, 1), "exists": bool(old),
                       "old": {"rows": int(old.get("rows") or 0), "sec": float(old.get("sec") or 0.0), "updatedAt": int(old.get("updatedAt") or 0)} if old else None})
    return {"tid": tid, "embedding": emb, "evalSet": doc.get("evalSet") is True, "people": people, "refused": plan["refused"], "skipped": plan["skipped"]}


def validate_voice_learn(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
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
    voices = load_voices(emb)
    ask = [n for n in names if n in voices and n not in same]
    if ask:   # 監査18: 既にある名前に足すのは「同じ人」と確かめたときだけ(別人の声が混ざると、その名前の照らし合わせが外れる)
        raise _errors.ApiError("confirm_same", "「%s」の声はもう覚えています。同じ人か確かめてから、もう一度押してください" % "」「".join(ask), 409, extra={"names": ask})
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["voice-learn"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    return {"tid": tid, "embedding": emb, "names": names, "confirmSame": sorted(same & set(names)),
            "title": _heavy.job_title("声を覚える: ", doc)}


def run_voice_learn(job):
    spec = job["spec"]
    with _heavy.job_temp_wav(job) as wav:
        doc = ed_store.read_transcript(spec["tid"])
        if doc.get("evalSet") is True:   # 待っている間に評価用へ変えた場合も断る(監査02)
            raise _errors.ApiError("eval_set", EVAL_SET_VOICE_MSG, 400)
        src = _tools.check_source(doc.get("sourcePath"))
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        plan = voice_learn_plan(doc)   # 読み直した文書で決め直し、確認した人(spec["names"])との積だけを覚える(確認のあとで名前を付けた人を黙って覚えない)
        grp = {n: plan["groups"][n] for n in spec.get("names") or [] if n in plan["groups"]}
        if not grp:
            raise _errors.ApiError("no_names", "覚えられる話者の行がありません(待っている間に名前・校正済みの印が変わった可能性があります)", 400)
        fake = _backend.select().name == "fake"
        if not fake and not diarize.has_sherpa():
            raise _errors.ApiError("no_sherpa", "声を覚えるには話者判別の部品(sherpa-onnx)が要ります。フォルダ内の install-diarize.bat を実行してください", 400)
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        recognize.extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
        if not fake:
            job["state"] = "loading"
            diarize.ensure_diar_models(job, spec["embedding"])
        job["state"], job["phase"], job["progress"] = "running", "声の特徴を取り出し中(CPU)", 0.0
        people = sorted(grp)
        vecs = diarize.embed_groups(job, wav, spec["embedding"], [grp[n][0] for n in people], start)
        _heavy.check_cancel(job)
        learned = []
        with _voices_lock:
            voices = load_voices(spec["embedding"])
            same = set(spec.get("confirmSame") or [])
            for n, v in zip(people, vecs):
                if not v:
                    continue
                rows, sec = len(grp[n][0]), grp[n][1]
                old = voices.get(n)
                if old and n not in same:   # 待っている間にほかで同じ名前を覚えた(確かめていない人の声には足さない)
                    _txbase.add_warning(job, "「%s」の声は、待っている間にほかで覚えられたので足しませんでした(同じ人なら、もう一度「声を覚える」を押してください)" % n)
                    continue
                if old and len(old["vec"]) == len(v):   # 前に覚えた声と、使った長さで重みを付けて混ぜる(配信ごとの声の揺れをならす)
                    w0 = min(float(old.get("sec") or 0.0), 3600.0)
                    v = diarize._unit([a * w0 + b * sec for a, b in zip(old["vec"], v)]) or v
                    rows, sec = rows + int(old.get("rows") or 0), sec + w0
                voices[n] = {"vec": [round(x, 6) for x in v], "rows": rows, "sec": round(sec, 1), "updatedAt": int(time.time() * 1000)}
                learned.append(n)
            if len(voices) > VOICE_MAX_PEOPLE:
                raise _errors.ApiError("too_many", "覚えられる声は %d 人までです(使わない声を消してください)" % VOICE_MAX_PEOPLE, 400)
            if learned:
                save_voices(spec["embedding"], voices)
        if not learned:
            raise _errors.ApiError("no_voice", "声の特徴を取り出せませんでした(行が短すぎる・音声が無い可能性があります)", 400)
        job["learned"] = learned
        job["speakers"] = len(learned)
        _heavy.job_done(job, spec["tid"])


def voices_summary():
    """覚えている声の一覧(特徴そのものは返さない)。{判別モデル: [{"name", "rows", "sec", "updatedAt"}]}"""
    out = {}
    for emb in diarize.DIAR_EMBS:
        v = load_voices(emb)
        if v:
            out[emb] = sorted(({"name": n, "rows": int(x.get("rows") or 0), "sec": float(x.get("sec") or 0.0), "updatedAt": int(x.get("updatedAt") or 0),
                                "generic": is_generic_speaker_name(n)}   # 一般的な名前で前に覚えた声(消さない。一覧で「忘れることをおすすめします」と出す)
                               for n, x in v.items()), key=lambda r: r["name"])
    return out


def delete_voice(emb, name):
    if emb not in diarize.DIAR_EMBS:
        raise _errors.ApiError("bad_request", "判別モデルの指定が正しくありません", 400)
    with _voices_lock:
        voices = load_voices(emb)
        if name not in voices:
            raise _errors.ApiError("not_found", "その声は覚えていません", 404)
        del voices[name]
        save_voices(emb, voices)


# ---------- 話者ごとの字幕の見た目を外から入れる(入口のまとめて実行。2026-10-05。docs/spec/friend-intake.md の 3・6) ----------
# POST /api/speakers/sub {"id": 文書の id, "styles": {"名前": {"color": "#RRGGBB" か "RRGGBB"}}} -> {"ok": true, "applied": [名前…]}
# 友人の依頼で指定した色を、話者分離のあとに文書の話者へ覚える(PC の「自分の色」には入れない)。名前がちょうど合った人(NFKC・空白を寄せて比べる)だけ。
# 合う人がいなくても 200(applied が空)。履歴の控えは recognize_voices が名前を付けるときと同じく残さない(話者の見た目だけの書き込み)
SPKSUB_SKIP_KINDS = ("alt", "normalize")   # この文書を書き換えないジョブ(2つ目のエンジン・30fps の作り直し)は「最中」に数えない


def _spksub_key(name):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(name or ""))).strip()


def _spksub_busy(tid):
    with _heavy._jobs_lock:
        return any(j.get("state") in _heavy.ACTIVE_STATES and j.get("kind") not in SPKSUB_SKIP_KINDS
                   and tid in (j.get("tid"), (j.get("spec") or {}).get("tid"), (j.get("spec") or {}).get("intoDoc")) for j in _heavy._jobs.values())


def speakers_sub_apply(obj):
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
        if "color" in st and ed_store._sub_color(st["color"]) is None:
            raise _errors.ApiError("bad_request", "字幕の色は 16 進 6 桁(#RRGGBB)で送ってください: %s" % str(st["color"])[:20], 400)
        one = ed_store.sanitize_sub_style(st)   # 知らない鍵は黙って捨てる(新しい入口が古い編集へ送っても、色までは効く)
        key = _spksub_key(name)
        if one and key:
            want[key] = one
    with ed_store._save_lock:   # 読み直し〜書き込みは保存と同じロックの中(recognize_voices と同じ)
        doc = ed_store.read_transcript(tid)
        if _spksub_busy(tid):
            raise _errors.ApiError("busy", "この文字起こしは処理中です(話者判別などが終わってから、もう一度送ってください)", 409)
        applied = []
        for s in doc.get("speakers") or []:
            if not isinstance(s, dict) or _yschemas.other_speaker(s):
                continue
            one = want.get(_spksub_key(s.get("name")))
            if one:
                s["sub"] = dict(ed_store.sanitize_sub_style(s.get("sub")) or {}, **one)
                applied.append(str(s.get("name") or ""))
        if applied:
            doc["updatedAt"] = max(int(time.time() * 1000), int(_yschemas.num_or(doc.get("updatedAt"), 0) or 0) + 1)
            ed_store.write_doc(tid, doc)
    return {"ok": True, "applied": applied}
