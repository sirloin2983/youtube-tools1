# -*- coding: utf-8 -*-
"""② 管理の層 flow: 話者判別と声の段取り(RS6 a-4。決定 3-29)。

③ human/proof/speakers.py は ① の pipeline/transcribe(diarize・backend・recognize・fill・worker_client)を直に読まず、ここを通す。
ここが持つのは判別のジョブの計算の糸・判別の記録・声の特徴と照合・覚えた声の置き場所。③ に残るのは、文書への反映・自動の判別の判断・字幕の見た目・声の登録簿の編集の受付・判別のジョブの受付と文書への書き込み。

動詞(③ が呼ぶ口。どれも ① を呼ぶ前後で ② が足すことを docstring の「② が足すこと」に書いた):
- 部品と判別モデル: models_ready・default_embedding・embedding・embeddings
- 判別: diarize(ジョブの音声 → 区間)・merge_minor(話す時間の短い番号を声の近い番号へ移す)・assign(区間 → 行の割り当て)・record_run・record_single・record_minor(<id>.diar.json)・latest_run
- 声: embed(声の特徴)・match_known_voices(行 → 声の特徴 → 覚えた声との照合)・voice_learn_rows(声を覚える行の選び方)・record_match・record_match_error・record_context・empty_voice
- 覚えた声の置き場所(作業データの voices/<判別モデル>.json): VOICES_DIR・voices_dir・voices_path・load_voices・save_voices・voices_edit・merge_voice
計算(判別 = speech.cpp の子プロセス・声の特徴 = sherpa-onnx と numpy)は ① の中・認識ワーカーの中だけ(ここでは読み込まない = tests/pipeline/transcribe/test_worker.py の検査)。
① の名前は呼ぶたびに `_calc.名前` で読む(テストの patch.object(S, "has_diar"・"has_sherpa"・"ensure_diar_model"・"ensure_diar_models"・"embed_groups"・"write_diar") が ① に届く)。
疑似の判別・声の特徴は ① の口 backend.Backend.diarize・embed のまま(疑似の本体は eval/fake/fake_asr)。
"""
import bisect
import contextlib
import json
import os
import threading
import time

from ytt import schemas as _yschemas, errors as _errors, fsio as _fsio, jobs as _slots, tools as _tools, txbase as _txbase, workdata as _workdata
from pipeline.transcribe import backend as _backend, diarize as _calc, recognize as _recognize, worker_client as _wc

from . import keys as _keys


# ---------- 部品と判別モデル ----------
DIAR_ENGINE = _calc.DIAR_ENGINE   # 文書の diarization.engine(③ は ① の定数を直に読まない)


def models_ready(auto=False):
    """判別の部品が使えるか(疑似のときは常に)= speech.cpp の実行ファイル(① has_diar)。auto = 文字起こしのあとの自動の判別の問い(テスト用の worker-fake では使わない =
    判別は本物の経路でモデルの取得になるため)。
    ② が足すこと: 疑似(backend の口)と worker-fake の決まりを ① の部品の有無に重ねる"""
    def real():
        if auto and _wc.worker_fake():
            return False
        return _calc.has_diar()
    return _backend.select().diar_ready(real)   # 疑似は常に使える(backend の口。OPT-E2 1a-2)


def voice_ready():
    """声の特徴(覚える・照らし合わせる)の部品が使えるか(疑似のときは常に)。サーバー側では sherpa-onnx を読み込まない(① の has_sherpa はワーカー側で調べる)"""
    return _backend.select().diar_ready(_calc.has_sherpa)


def default_embedding():
    """判別モデルの既定の名前(③ は ① の定数を直に読まない)"""
    return _calc.DIAR_EMB_DEFAULT


def embedding(name):
    """判別モデルの名前を確かめる -> 知っている名前ならそのまま、知らない・空なら既定"""
    return name if name in _calc.DIAR_EMBS else _calc.DIAR_EMB_DEFAULT


def embeddings():
    """判別モデルの名前の並び(覚えた声の一覧・忘れるの受付)"""
    return list(_calc.DIAR_EMBS)


def learn_embedding(diar_emb):
    """声を覚えるモデル: ① の VOICE_EMB(空・知らない名前なら判別のモデル diar_emb)"""
    v = _calc.VOICE_EMB
    return v if v in _calc.DIAR_EMBS else embedding(diar_emb)


def match_embedding(diar_emb):
    """覚えた声と照らし合わせるモデル: 覚えるモデル。ただしそのモデルの声が 0 人で、判別のモデルで覚えた声があれば判別のモデル
    (10-22 より前に覚えた voxceleb の声がある PC で、モデルを替えたとたん名前が付かなくならないように)"""
    v, d = learn_embedding(diar_emb), embedding(diar_emb)
    return d if v != d and not load_voices(v) and load_voices(d) else v


# ---------- 判別 ----------
def diarize(job, spec, wav, hints):
    """判別のジョブの 1 回 -> [(開始, 終了, 話者番号)](音声の頭からの秒)。spec = 判別のジョブの指定(numSpeakers・embedding)・
    hints = {"sourcePath": 確かめた元の動画, "start": 範囲の頭(秒), "end": 範囲の終わり(None なら動画の終わりまで)}。
    ② が足すこと: 3 時間の上限・状態の表示・音声の取り出し(① recognize)・音声の長さを数えて本物と疑似の口(backend)へ・
    本物の道の部品の確かめとモデルの取得と失敗の言い換え(_diarize_job_real)"""
    src, start, end = hints["sourcePath"], hints["start"], hints.get("end")
    span = (end if end else (_tools.media_duration(src) or 0.0)) - start
    if span > _calc.MAX_DIAR_SEC:
        raise _errors.ApiError("too_long", "話者判別は3時間までの範囲で使えます。範囲を分けて文字起こししてください", 400)
    job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
    _recognize.extract_audio(job, {"sourcePath": src, "start": start, "end": end}, wav)
    total = _tools.media_duration(wav) or span
    return _backend.select().diarize(job, spec, wav, total, _diarize_job_real)   # 疑似は eval/fake/fake_asr の diarize_fake(RS2-9)


def _diarize_job_real(job, spec, wav):
    """判別のジョブの本物の道(backend の口の real): 部品の確かめ → モデルの取得 → ワーカーで判別 -> [(開始, 終了, 話者番号)]"""
    if not _calc.has_diar():
        raise _errors.ApiError("no_diar", "話者判別の部品(speech.cpp)がありません(setup\\place_speechcpp.py で置いてください)", 400)
    job["state"] = "loading"
    _calc.ensure_diar_model(job)
    job["state"], job["phase"], job["progress"] = "running", "話者を判別中", 0.0
    try:
        return _calc.diarize_real(job, wav, spec["numSpeakers"])
    except (_slots.Cancelled, _errors.ApiError):
        raise
    except Exception as e:
        raise _errors.ApiError("diar_failed", "話者の判別に失敗しました: %s %s" % (e.__class__.__name__, str(e)[:150]), 500)


# ---------- 話す時間の短い番号を移す(ゲームの声など。11-01 予備3 の試し = 保管庫 plan/Nemotron話者分離の調べ-1101.md の 12 章・ユーザー「メンバーの声を消さないなら入れていい」) ----------
# 配信の中で話す時間が全部の番号の合計の MINOR_SHARE 未満の番号は外す(いちばん長く話す番号は外さない)。外した番号の区間は捨てずに、
# 声の特徴(声の名前付けのモデル)が一番近い残りの番号へ移す(生スバルで、外した番号が白上フブキの声の割れた小さい方だった)。
# 声の特徴が取れない(短い区間だけ・部品が無い)ときは、いちばん長く話す番号へ移す。試しの数: カード 52 枚の当たり 42 → 44・少なく数えた外れ 5 → 5・ソロ 232 → 234 / 239
MINOR_SHARE = 0.05


def minor_labels(turns):
    """turns = [(開始, 終了, 番号)] -> ({外す番号: 秒}, {番号: 秒})。番号が 1 つなら外さない"""
    secs = {}
    for a, b, k in turns:
        secs[k] = secs.get(k, 0.0) + max(0.0, b - a)
    total = sum(secs.values())
    if len(secs) < 2 or total <= 0:
        return {}, secs
    top = max(secs, key=lambda k: (secs[k], -k))
    return {k: v for k, v in secs.items() if k != top and v < MINOR_SHARE * total}, secs


def _label_spans(turns):
    """番号ごとの声の特徴を取る区間 {番号: [(開始, 終了)]}: ほかの番号と重ならない所の 1 秒以上(① VOICE_MIN_ROW)を長い順に ① VOICE_MAX_ROWS 区間・VOICE_MAX_SEC 秒まで"""
    ts = sorted(turns)
    starts = [t[0] for t in ts]
    dmax = max((b - a for a, b, _ in ts), default=0.0)
    out = {}
    for i, (a, b, k) in enumerate(ts):
        cut = [(a, b)]
        for j in range(bisect.bisect_left(starts, a - dmax), bisect.bisect_left(starts, b)):   # 重なりうる区間だけ(長い配信で数千区間)
            x, y, t = ts[j]
            if j == i or t == k or y <= a or x >= b:
                continue
            nxt = []
            for p, q in cut:
                if y <= p or x >= q:
                    nxt.append((p, q))
                    continue
                if x > p:
                    nxt.append((p, x))
                if y < q:
                    nxt.append((y, q))
            cut = nxt
        out.setdefault(k, []).extend(s for s in cut if s[1] - s[0] >= _calc.VOICE_MIN_ROW)
    for k, rs in out.items():
        rs.sort(key=lambda s: -(s[1] - s[0]))
        pick, tot = [], 0.0
        for s in rs[:_calc.VOICE_MAX_ROWS]:
            if tot >= _calc.VOICE_MAX_SEC:
                break
            pick.append(s)
            tot += s[1] - s[0]
        out[k] = sorted(pick)
    return out


def merge_minor(job, wav, turns, offset):
    """話す時間の短い番号を、声の一番近い残りの番号へ移す -> (移したあとの turns, 記録 {"share", "labels": {番号: {"sec", "share", "to", "score", "by"}}} か None)。
    turns = [(開始, 終了, 番号)](音声の頭からの秒)・wav = 判別の音声・offset = 音声の頭の元の動画の秒。
    ② が足すこと: 番号ごとの声の区間を選び、① の声の特徴(embed)で番号どうしを比べる。比べられなければ一番長く話す番号へ"""
    minor, secs = minor_labels(turns)
    if not minor:
        return turns, None
    keep = [k for k in secs if k not in minor]
    top = max(keep, key=lambda k: secs[k])
    spans = _label_spans(turns)
    labels = sorted(secs)
    vecs = {}
    try:
        got = embed(job, {"embedding": learn_embedding(default_embedding())}, wav,
                    [[(a + offset, b + offset) for a, b in spans.get(k, [])] for k in labels], {"start": offset})
        vecs = dict(zip(labels, got))
    except _slots.Cancelled:
        raise
    except Exception as e:   # 声の特徴が取れなくても移す(一番長く話す番号へ)
        _txbase.log.warning("短い番号の声の特徴を取れませんでした(一番長く話す番号へ移します): %s %s", e.__class__.__name__, str(e)[:150])
    total = sum(secs.values())
    moved = {}
    for k in sorted(minor):
        v = vecs.get(k)
        sc = sorted(((_calc._cos(v, vecs[t]), t) for t in keep if vecs.get(t)), reverse=True) if v else []
        to, score = (sc[0][1], round(sc[0][0], 3)) if sc else (top, None)
        moved[k] = {"sec": round(minor[k], 1), "share": round(minor[k] / total, 4), "to": to, "score": score, "by": "voice" if sc else "longest"}
    return [(a, b, moved[k]["to"] if k in moved else k) for a, b, k in turns], {"share": MINOR_SHARE, "labels": {str(k): m for k, m in moved.items()}}


def record_minor(tid, info):
    """最新の判別の記録に、移した短い番号を書く(latest.minor。番号は判別の生の番号 = labelMap の鍵ではない)。書けなくても判別は失敗にしない"""
    try:
        with _calc._diar_edit(tid) as d:
            if d:
                d["latest"]["minor"] = info
    except Exception as e:
        _txbase.log.warning("短い番号の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


def assign(doc, turns, offset, keep_row, smooth=False):
    """判別の区間を文書の行に割り当てる。turns = [(開始, 終了, 話者番号)](音声の頭からの秒)・
    offset = 音声の頭の元の動画の秒・keep_row(行) = 話者を変えない行か(③ の決まり)・smooth = 細切れをならす(S2)。
    -> {"segs": 行, "keep": 守る行の印, "raw": [(ラベル or None, 混ざる, 不確か)], "res": ならしたあとの同じ形, "ratios", "smoothed": {行の番号: ラベル} or None}。
    ② が足すこと: 守る行を数え、区間を元の動画の秒に直して並べて ① の割り当て(_assign)とならし(smooth_speakers)へ渡し、
    ならした行は「不確か」の印つきでまとめる。前は ① の定型の幻覚の掃除(後処理 C の fill_clean_turns)を先に通していた(11-01 に消した)"""
    segs = doc.get("segments") or []
    keep = [keep_row(g) for g in segs]
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)   # 元の動画の秒(割り当て・ならし・記録で同じ並び)
    full = _calc._assign(segs, ts)
    raw, ratios = [r[:3] for r in full], [r[3] for r in full]
    smoothed = _calc.smooth_speakers(segs, raw, ts, keep, ratios) if smooth else None
    res = [(smoothed[i], r[1], True) if smoothed and i in smoothed else r for i, r in enumerate(raw)]   # ならした行は「不確か」の印を残す
    return {"segs": segs, "keep": keep, "raw": raw, "res": res, "ratios": ratios, "smoothed": smoothed}


def _record_diar(tid, run):
    try:
        _calc.write_diar(tid, run)
    except Exception as e:   # 記録が書けなくても判別の結果は残す
        _txbase.log.warning("判別の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


def record_run(tid, a, turns, offset, requested, emb, idmap, auto=None):
    """判別の 1 回の記録を <id>.diar.json に(機械の最初の結果 = 人が直す前)。a = assign の結果・idmap = {機械のラベル: 付けた話者の id}・
    auto = 自動の判別の印 {eval, contextName}。② が足すこと: 割り当ての結果を ① の記録の形(build_diar_run)へ渡し、書けなくても判別は失敗にしない"""
    _record_diar(tid, _calc.build_diar_run(a["segs"], a["raw"], turns, offset, requested, emb, idmap, auto, a["smoothed"], a["ratios"]))
    _keys.write_diar(tid, {"requested": requested, "embedding": emb}, voices_path(match_embedding(emb)))   # 成果物の鍵 <id>.diar.key.json(RS6 b-K1。材料は照らし合わせる声)


def record_single(tid, segs, name):
    """1 人指定(判別しない)の記録を <id>.diar.json に(声の区間は無い・全部の行が S1)。name = 依頼の名前(無ければ空)。
    ② が足すこと: 判別していない回も同じ記録の形(engine single)で残し、書けなくても失敗にしない"""
    _record_diar(tid, {"at": int(time.time() * 1000), "engine": {"name": "single", "requested": 1}, "offset": 0.0, "turns": [], "overlaps": [],
                       "labelMap": {"0": "S1"}, "speakers": 1,
                       "rows": {str(sg.get("id")): {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False} for sg in segs},
                       "voices": {"checked": False, "speakers": {"S1": {"label": 0, "decided": name, "by": "request", "reason": None}} if name else {}}})
    _keys.write_diar(tid, {"requested": 1, "embedding": "single", "name": name or ""}, None)   # 成果物の鍵(RS6 b-K1)


def latest_run(tid):
    """判別の記録の最新の回(無い・壊れていれば None)。② が足すこと: 記録のファイルの形(latest と history)を ③ に見せない"""
    d = _calc.read_diar(tid)
    return d["latest"] if d else None


# ---------- 声の特徴と照合 ----------
def embed(job, spec, wav, groups, hints):
    """声の特徴 -> [長さ 1 の特徴 or None](groups と同じ並び)。groups = [[(開始, 終了)…]](元の動画の秒)・spec["embedding"] = 判別モデル・
    hints = {"start": wav の頭の元の動画の秒, "sourcePath"?: 元の動画, "end"?}。sourcePath があれば(声を覚えるジョブ)音声を取り出してから・
    本物ならモデルを取ってから特徴を取る(判別のあとの照合は判別の音声をそのまま使い、照合のモデルが判別と違えば取る = VOICE_EMB)。
    ② が足すこと: 音声の取り出しと状態の表示・モデルの取得(疑似は取らない)"""
    def fetch(j, emb):
        j["state"] = "loading"
        _calc.ensure_diar_models(j, emb)
    if hints.get("sourcePath") or hints.get("wavReady"):   # wavReady = 呼ぶ側が wav を用意した(元の動画が片付いた文書の、切り出した行の音。human/proof/voiceclips)
        if hints.get("sourcePath"):
            job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
            _recognize.extract_audio(job, {"sourcePath": hints["sourcePath"], "start": hints["start"], "end": hints.get("end")}, wav)
        _backend.select().diar_models(job, spec["embedding"], fetch)   # 疑似は取らない(backend の口。OPT-E2 1a-2)
        job["state"], job["phase"], job["progress"] = "running", "声の特徴を取り出し中(CPU)", 0.0
    else:   # 判別のあとの照合(11-01 から判別は声の特徴のモデルを取らない = いつも確かめる。あれば何もしない)
        state = job.get("state")
        _backend.select().diar_models(job, spec["embedding"], fetch)
        job["state"] = state or "running"   # 取ったあと「読み込み中」のまま残さない
    return _calc.embed_groups(job, wav, spec["embedding"], groups, hints["start"])


def match_known_voices(job, spec, wav, segs, key, voices, hints):
    """判別の音声 wav の行(segs)を key(行)(話者の id。空なら使わない)で分け、声の特徴を取り、覚えている声(voices)と照らし合わせる
    -> ({話者の id: (名前, 似ている度合い)}, {話者の id: 経過})(① の match_voices_explain の形)。話者が無ければ ({}, {})。
    ② が足すこと: 行の選び方(① voice_groups)・状態の表示・声の特徴(ワーカー)と照合(①)の 3 段をつなぐ"""
    groups = _calc.voice_groups(segs, key)
    ids = list(groups)
    if not ids:
        return {}, {}
    job["phase"] = "覚えている声と照らし合わせ中"
    vecs = embed(job, spec, wav, [groups[i][0] for i in ids], hints)
    return _calc.match_voices_explain(dict(zip(ids, vecs)), voices)


def voice_learn_rows(segs, who, accept):
    """声を覚える行の選び方 -> ({名前: ([(開始, 終了)...], 秒)}, skipped)。who = {話者の id: 覚える名前}(無い話者の行は数えない)・
    accept(行) = ③ の決まり(校正済みか・音のメモが無いか)で使えない理由 or None。
    skipped = {"unproofed", "tagged", "mixed", "short"}(使わなかった行の数。理由は 1 秒未満 → 混ざる → accept の理由 の順に 1 つ)。
    ② が足すこと: 短い行(① VOICE_MIN_ROW)と混声(① MIXED_FLAG)の数え、通った行を ① の voice_groups(1 人あたりの上限)へ渡す"""
    skipped = {"unproofed": 0, "tagged": 0, "mixed": 0, "short": 0}
    ok = []
    for g in segs:
        if not isinstance(g, dict) or g.get("speaker") not in who:
            continue
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        if a is None or b is None or b - a < _calc.VOICE_MIN_ROW:
            skipped["short"] += 1
        elif _txbase.MIXED_FLAG in str(g.get("flag") or ""):
            skipped["mixed"] += 1
        else:
            why = accept(g)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
            else:
                ok.append(g)
    return _calc.voice_groups(ok, lambda g: who.get(g.get("speaker")) or ""), skipped


def empty_voice(**kw):
    """話者ごとの照合の経過の空の形(top・score・second・secondScore・decided・by・reason)に kw を重ねた新しい辞書"""
    return dict(_calc._VOICE_EMPTY, **kw)


def record_match(tid, emb, registered, names, speakers):
    """最新の判別の記録に「覚えた声との照合」を書く(話者のラベルは ① が labelMap から付ける)。判別の記録が無ければ何もしない -> 書いたか。
    registered = 覚えている声の数・names = 照らし合わせを絞った名前(依頼)・speakers = {話者の id: 経過}。
    ② が足すこと: 照合の決まり(しきい値 match・2 位との差 margin)を記録に添える"""
    return _calc.update_diar_voices(tid, {"checked": True, "embedding": emb, "registered": registered, "restrictedNames": list(names) if names else None,
                                          "match": _calc.VOICE_MATCH, "margin": _calc.VOICE_MARGIN, "speakers": speakers})


def record_match_error(tid, error):
    """照合に失敗したことを最新の判別の記録に書く(書けなくても黙って続ける = 判別の結果は残す)"""
    try:
        _calc.update_diar_voices(tid, {"checked": False, "error": error, "speakers": {}})
    except Exception:
        pass


def record_context(tid, name, hit, reason):
    """diar.json の最新の voices に、動画の手がかりで付けた名前(speakers[id].by = hit["by"])と経過 context = {name, speaker, reason} を書く。
    人の最終(行の speaker・speakers[].name)と、機械が付けた名前を後で比べられるように。書けなくても名前付けは続ける。
    ② が足すこと: 判別の記録を読んで書き換える(① の _diar_edit のロックの中)・話者の id から機械のラベルを引く"""
    try:
        with _calc._diar_edit(tid) as d:
            if not d:
                return
            latest = d["latest"]
            v = latest.get("voices") if isinstance(latest.get("voices"), dict) else {"checked": False}
            sp = v.get("speakers") if isinstance(v.get("speakers"), dict) else {}
            if hit:
                one = sp.get(hit["speaker"]) if isinstance(sp.get(hit["speaker"]), dict) else empty_voice(label=_calc._label_of(latest).get(hit["speaker"]))
                one.update({"decided": hit["name"], "by": hit["by"], "reason": None})
                sp[hit["speaker"]] = one
            v["speakers"] = sp
            v["context"] = {"name": name, "speaker": hit["speaker"] if hit else None, "reason": reason}
            latest["voices"] = v
    except Exception as e:
        _txbase.log.warning("動画の手がかりの名前の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


# ---------- 覚えた声で 1 行ずつ話者を当てる(資料の git:before-1028-cleanup:plan/行ごとの声の当て-1023.md) ----------
# 出る人(spec の people)が 2 人以上で、全員の声が帳にあるときだけ動く(帳が足りなければ何もしない。スイッチ ROWVOICE は 10-30 の片付けで外した)
ROWVOICE_MARGIN = 0.05    # 1 位と 2 位の差がこれ未満の行は配信者(出る人の先頭)のまま
ROWVOICE_MIN = 0.5        # 声の特徴を取る行の長さの下限(秒)。短い行は配信者のまま
ROWVOICE_COLORS = ["#2f62d6", "#d9534f", "#2e9e5b", "#c98a12", "#8a4fd6", "#0f9aa8", "#d6479a", "#6b7280"]   # 話者の色(③ speakers.SPK_COLORS と同じ並び)
ROWVOICE_KEEP = 200       # 記録に残す行の点数の数


def row_voices(job, spec, wav, segs):
    """文字起こしの後処理の最後(文書を書く前)に、行ごとに声の特徴を取り、出る人の覚えた声と比べていちばん近い人を行の話者にする。
    segs を書き換え -> {"speakers": 文書の話者, "diarization": 文書の印, "record": 生の点数} か None(動かない・動けない)。
    wav = 文字起こしの音(spec["start"] 秒から)。出る人の先頭 = 配信者 = 声で決まらない行の話者。字幕に出さない行・話者の付いた行は変えない。
    ② が足すこと: 帳の確かめ(全員そろうときだけ)・行の選び方・照合(1 位と 2 位の差)・記録の形(声の特徴は ① の embed_groups)"""
    people = list(dict.fromkeys(p for p in spec.get("people") or [] if isinstance(p, str) and p))
    if len(people) < 2:
        return None
    emb = learn_embedding(default_embedding())
    voices = load_voices(emb)
    if any(p not in voices for p in people):
        return None
    dim = len(voices[people[0]]["vec"])
    if any(len(voices[p]["vec"]) != dim for p in people):
        return None
    rows = [g for g in segs if isinstance(g, dict) and str(g.get("text") or "").strip() and not _yschemas.no_sub_row(g) and not g.get("speaker")]
    if not rows:
        return None
    groups = []
    for g in rows:
        a, b = _yschemas.num_or(g.get("start")), _yschemas.num_or(g.get("end"))
        groups.append([(a, b)] if a is not None and b is not None and b - a >= ROWVOICE_MIN else [])
    job["phase"] = "覚えた声で行の話者を当てています"
    vecs = embed(job, {"embedding": emb}, wav, groups, {"start": _yschemas.num_or(spec.get("start"), 0.0) or 0.0})
    ids = {p: "S%d" % (i + 1) for i, p in enumerate(people)}
    count = {"voice": 0, "low": 0, "short": 0}
    scores = []
    for g, v in zip(rows, vecs):
        who, why = people[0], "short"
        if v:
            sc = sorted(((sum(x * y for x, y in zip(v, voices[p]["vec"])), p) for p in people), reverse=True)
            if sc[0][0] - sc[1][0] >= ROWVOICE_MARGIN:
                who, why = sc[0][1], "voice"
            else:
                why = "low"
            if len(scores) < ROWVOICE_KEEP:
                scores.append({"id": str(g.get("id")), "top": sc[0][1], "score": round(sc[0][0], 4), "second": round(sc[1][0], 4)})
        count[why] += 1
        g["speaker"] = ids[who]
    speakers = [{"id": ids[p], "name": p, "color": ROWVOICE_COLORS[i % len(ROWVOICE_COLORS)]} for i, p in enumerate(people)]
    mark = dict({"engine": "rowvoice", "speakerBy": "rowvoice", "embedding": emb, "requested": len(people), "found": len(people),
                 "margin": ROWVOICE_MARGIN, "unsure": count["low"] + count["short"], "at": int(time.time() * 1000)}, **count)
    return {"speakers": speakers, "diarization": mark, "record": dict(mark, people=people, rows=scores)}


# ---------- 覚えた声の置き場所(A-3。声の特徴は個人を見分けられる情報なので作業データの voices/ にだけ置く) ----------
# 置き場所は呼ぶたびに作業データ(ytt/workdata の DATA_DIR)の voices(voices_dir)。VOICES_DIR は上書き用(テストが一時フォルダを入れる)。None なら作業データの中。
# 置き場所は読み込みのときに固定せず呼ぶたびに求める(入口から起動しても作業データの voices に読み書きするため)
VOICES_DIR = None
_voices_lock = threading.Lock()


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
    _fsio.write_json(voices_path(emb), {"schema": "ytt-voices/v1", "embedding": emb, "voices": voices}, indent=None, fsync_required=True)


@contextlib.contextmanager
def voices_edit(emb):
    """覚えた声(判別モデル emb)を読んで書き換えさせ、変わっていれば書く(登録簿のロックの中。途中で例外なら書かない)"""
    with _voices_lock:
        voices = load_voices(emb)
        before = json.dumps(voices, sort_keys=True)
        yield voices
        if json.dumps(voices, sort_keys=True) != before:
            save_voices(emb, voices)


LEARNED_ROWS_MAX = 2000   # learnedFrom の 1 文書に控える行の id の上限(古い物から捨てる)


SHORT_WEIGHT = 0.5       # ショート由来(学習用データ。編集後の音)の材料を混ぜる重み(配信の材料の半分。10-25)
PROVISIONAL_KEEP = 0.1   # ショートだけで覚えた「仮」の声に、配信の材料が初めて来たとき前の声に残す重み(上書きに近い = 普段の声に直る)


def row_vectors_path(emb):
    """行ごとの声の特徴の控え voices/<モデル>.rows.json({名前: {"文書#行": {"vec", "sec", "short"}}}。1 行ずつ外してまとめ直すため = human/proof/voicerebuild)"""
    return os.path.join(voices_dir(), emb + ".rows.json")


def save_row_vectors(emb, name, items):
    """その人の行ごとの特徴を控えに足す(items = {"文書#行": {"vec", "sec", "short"}})。登録簿のロックの中で読んで書く"""
    if not items:
        return
    with _voices_lock:
        p = row_vectors_path(emb)
        cur = _fsio.read_json_or(p, {}, kind=dict)
        cur.setdefault(name, {}).update(items)
        _fsio.write_json(p, cur, indent=None)


PROVISIONAL_UNTIL = 30.0   # 配信の材料で仮に覚えた声(初回 10 秒)は、覚えた秒がこれに届くまで仮のまま(普通に混ぜる)


def merge_voice(old, vec, rows, sec, doc=None, by=None, row_ids=None, short=False, provisional=False):
    """覚える声の 1 人分 -> {"vec", "rows", "sec", "updatedAt", "learnedFrom"}。前に覚えた声 old(同じ次元のとき)とは、使った長さで重みを付けて混ぜる
    (配信ごとの声の揺れをならす。前の重みは 1 時間まで)。doc = 覚えた文書の id(learnedFrom に {doc, at} を足す。同じ文書は重ねず at だけ新しくする。
    古い形(learnedFrom が無い声)もそのまま読める)。by = 何が覚えさせたか(例 "check" = 確かめるの声のカード。V1 V2c)・
    row_ids = 使った行の id(learnedFrom の rows に前の分と合わせて控え、sec に足す = 同じ行を 2 度覚えないための印。確かめるが読む)。
    short = ショート由来の材料(学習用データ。voicematerial.is_short)= 重み SHORT_WEIGHT で混ぜ、shortSec に足す。ショートだけで覚えた声は
    provisional(仮)。ショート由来の仮の声に配信の材料が来たら、前の声の重みを PROVISIONAL_KEEP 倍にして混ぜる(上書きに近い)。配信の材料が増えるほど普段の声に寄る。
    provisional=True = まだ声が無い人を少しの材料(human/check/voice.FIRST_SEC)で覚えた = 仮。配信の材料の仮は PROVISIONAL_UNTIL 秒まで仮のまま(10-25)。
    ② が足すこと: 登録簿の 1 人分の形・行の控え・どの文書から覚えたかの記録(混ぜる計算は ① の blend_voice)"""
    now = int(time.time() * 1000)
    src = [x for x in (old or {}).get("learnedFrom") or [] if isinstance(x, dict) and x.get("doc")]
    if doc:
        prev = next((x for x in src if x["doc"] == str(doc)), None)
        entry = dict(prev or {}, doc=str(doc), at=now)   # 前の控え(by・rows・sec)は引き継ぐ(普通の「声を覚える」で控えの行を忘れない)
        if by:
            entry["by"] = str(by)[:20]
        if row_ids is not None:
            ids = [str(r) for r in (prev or {}).get("rows") or [] if isinstance(r, str)] + [str(r) for r in row_ids]
            entry["rows"] = list(dict.fromkeys(ids))[-LEARNED_ROWS_MAX:]
            entry["sec"] = round(float(_yschemas.num_or((prev or {}).get("sec"), 0.0) or 0.0) + float(sec), 1)
        src = [x for x in src if x["doc"] != str(doc)] + [entry]
    short_sec = float(sec) if short else 0.0
    first_provisional = bool(provisional)
    provisional = bool(short) or first_provisional
    if old and len(old["vec"]) == len(vec):
        old_sec = float(_yschemas.num_or(old.get("sec"), 0.0) or 0.0)
        old_short = min(old_sec, float(_yschemas.num_or(old.get("shortSec"), 0.0) or 0.0))
        w_old = old_sec - old_short * (1.0 - SHORT_WEIGHT)   # ショート由来の分は半分に数える
        if old.get("provisional") is True and not short and old_short > 0:
            w_old *= PROVISIONAL_KEEP   # ショート由来の仮の声に配信の材料 = 上書きに近い
        vec, _w = _calc.blend_voice(old["vec"], w_old, vec, float(sec) * (SHORT_WEIGHT if short else 1.0))   # 混ぜる計算は ① の blend_voice
        sec = min(old_sec, _calc.BLEND_MAX_SEC) + float(sec)   # 覚えた秒(覚え直しの量の決まりが読む)は重みと別に今までどおり
        rows = rows + int(old.get("rows") or 0)
        short_sec += old_short
        provisional = old.get("provisional") is True and (bool(short) or (old_short <= 0 and sec < PROVISIONAL_UNTIL))
    out = {"vec": [round(x, 6) for x in vec], "rows": rows, "sec": round(sec, 1), "updatedAt": now}
    if short_sec:
        out["shortSec"] = round(short_sec, 1)
    if provisional:
        out["provisional"] = True
    if src:
        out["learnedFrom"] = src
    return out
