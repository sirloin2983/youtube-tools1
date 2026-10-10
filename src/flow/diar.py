# -*- coding: utf-8 -*-
"""② 管理の層 flow: 話者判別と声の段取り(役割で組み直す RS6 a-4。2026-10-10。決定 3-29)。

human/proof/speakers.py(③)が ① の pipeline/transcribe(diarize・backend・recognize・fill・worker_client)を直に読んでいた所 =
「① の半身が ③ に残っている所」(判別のジョブの計算の糸・判別の記録・声の特徴と照合・覚えた声の置き場所)をここへ移した。
③ に残るのは、文書への反映・空の行の下書き・自動の判別の判断・字幕の見た目・声の登録簿の編集の受付・判別のジョブの受付と文書への書き込み。

動詞(③ が呼ぶ口。どれも ① を呼ぶ前後で ② が足すことを docstring の「② が足すこと」に書いた):
- 部品と判別モデル: models_ready・default_embedding・embedding・embeddings
- 判別: diarize(ジョブの音声 → 区間)・assign(区間 → 行の割り当て)・record_run・record_single(<id>.diar.json)・latest_run
- 声: embed(声の特徴)・match_known_voices(覚えた声との照合)・voice_rows・voice_row_min・record_match・record_match_error・record_context・empty_voice
- 覚えた声の置き場所(作業データの voices/<判別モデル>.json): VOICES_DIR・voices_dir・voices_path・load_voices・save_voices・voices_edit・merge_voice
計算(sherpa-onnx・numpy)は ① の中・認識ワーカーの中だけ(ここでは読み込まない = src/editor/tests/test_worker.py の検査)。
① の名前は呼ぶたびに `_calc.名前` で読む(テストの patch.object(S, "has_sherpa"・"ensure_diar_models"・"embed_groups"・"write_diar") が ① に届く)。
疑似の判別・声の特徴は ① の口 backend.Backend.diarize・embed のまま(疑似の本体は eval/fake/fake_asr)。
"""
import contextlib
import json
import os
import threading
import time

from ytt import errors as _errors, fsio as _fsio, jobs as _slots, tools as _tools, txbase as _txbase, workdata as _workdata
from pipeline.transcribe import backend as _backend, diarize as _calc, fill as _fill, recognize as _recognize, worker_client as _wc


# ---------- 部品と判別モデル ----------
def models_ready(auto=False):
    """判別の部品が使えるか(疑似のときは常に)。auto = 文字起こしのあとの自動の判別の問い(テスト用の worker-fake では使わない =
    判別は本物の経路でモデルの取得になるため)。サーバー側では sherpa-onnx を読み込まない(① の has_sherpa はワーカー側で調べる)。
    ② が足すこと: 疑似(backend の口)と worker-fake の決まりを ① の部品の有無に重ねる"""
    if _backend.is_fake():
        return True
    if auto and _wc.worker_fake():
        return False
    return _calc.has_sherpa()


def default_embedding():
    """判別モデルの既定の名前(③ は ① の定数を直に読まない)"""
    return _calc.DIAR_EMB_DEFAULT


def embedding(name):
    """判別モデルの名前を確かめる -> 知っている名前ならそのまま、知らない・空なら既定"""
    return name if name in _calc.DIAR_EMBS else _calc.DIAR_EMB_DEFAULT


def embeddings():
    """判別モデルの名前の並び(覚えた声の一覧・忘れるの受付)"""
    return list(_calc.DIAR_EMBS)


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
    if not _calc.has_sherpa():
        raise _errors.ApiError("no_sherpa", "話者判別の部品(sherpa-onnx)が入っていません。フォルダ内の install-diarize.bat(Mac は install-diarize.command)を実行してください", 400)
    job["state"] = "loading"
    _calc.ensure_diar_models(job, spec["embedding"])
    job["state"], job["phase"], job["progress"] = "running", "話者を判別中(CPU。長い音声は時間がかかります)", 0.0
    try:
        return _calc.diarize_real(job, wav, spec["numSpeakers"], spec["embedding"])
    except (_slots.Cancelled, _errors.ApiError):
        raise
    except Exception as e:
        raise _errors.ApiError("diar_failed", "話者の判別に失敗しました: %s %s" % (e.__class__.__name__, str(e)[:150]), 500)


def assign(doc, turns, offset, keep_row, smooth=False):
    """判別の区間を文書の行に割り当てる(doc["segments"] は ① fill の掃除で減ることがある)。turns = [(開始, 終了, 話者番号)](音声の頭からの秒)・
    offset = 音声の頭の元の動画の秒・keep_row(行) = 話者を変えない行か(③ の決まり)・smooth = 細切れをならす(S2)。
    -> {"segs": 行, "keep": 守る行の印, "raw": [(ラベル or None, 混ざる, 不確か)], "res": ならしたあとの同じ形, "ratios", "smoothed": {行の番号: ラベル} or None, "dropped": 捨てた行の数}。
    ② が足すこと: ① の定型の幻覚の掃除(fill_clean_turns)を先に通し、残った行で守る行を数え、区間を元の動画の秒に直して並べて
    ① の割り当て(_assign)とならし(smooth_speakers)へ渡し、ならした行は「不確か」の印つきでまとめる"""
    dropped = _fill.fill_clean_turns(doc, turns, offset)   # 定型の幻覚で声の区間と重ならない行を捨てる(autoFill の文書だけ。0.60.0)
    segs = doc.get("segments") or []
    keep = [keep_row(g) for g in segs]
    ts = sorted((a + offset, b + offset, s) for a, b, s in turns)   # 元の動画の秒(割り当て・ならし・記録で同じ並び)
    full = _calc._assign(segs, ts)
    raw, ratios = [r[:3] for r in full], [r[3] for r in full]
    smoothed = _calc.smooth_speakers(segs, raw, ts, keep, ratios) if smooth else None
    res = [(smoothed[i], r[1], True) if smoothed and i in smoothed else r for i, r in enumerate(raw)]   # ならした行は「不確か」の印を残す
    return {"segs": segs, "keep": keep, "raw": raw, "res": res, "ratios": ratios, "smoothed": smoothed, "dropped": dropped}


def _record_diar(tid, run):
    try:
        _calc.write_diar(tid, run)
    except Exception as e:   # 記録が書けなくても判別の結果は残す
        _txbase.log.warning("判別の記録を書けませんでした: %s %s", e.__class__.__name__, str(e)[:150])


def record_run(tid, a, turns, offset, requested, emb, idmap, auto=None):
    """判別の 1 回の記録を <id>.diar.json に(機械の最初の結果 = 人が直す前)。a = assign の結果・idmap = {機械のラベル: 付けた話者の id}・
    auto = 自動の判別の印 {eval, contextName}。② が足すこと: 割り当ての結果を ① の記録の形(build_diar_run)へ渡し、書けなくても判別は失敗にしない"""
    _record_diar(tid, _calc.build_diar_run(a["segs"], a["raw"], turns, offset, requested, emb, idmap, auto, a["smoothed"], a["ratios"]))


def record_single(tid, segs, name):
    """1 人指定(判別しない)の記録を <id>.diar.json に(声の区間は無い・全部の行が S1)。name = 依頼の名前(無ければ空)。
    ② が足すこと: 判別していない回も同じ記録の形(engine single)で残し、書けなくても失敗にしない"""
    _record_diar(tid, {"at": int(time.time() * 1000), "engine": {"name": "single", "requested": 1}, "offset": 0.0, "turns": [], "overlaps": [],
                       "labelMap": {"0": "S1"}, "speakers": 1,
                       "rows": {str(sg.get("id")): {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False} for sg in segs},
                       "voices": {"checked": False, "speakers": {"S1": {"label": 0, "decided": name, "by": "request", "reason": None}} if name else {}}})


def latest_run(tid):
    """判別の記録の最新の回(無い・壊れていれば None)。② が足すこと: 記録のファイルの形(latest と history)を ③ に見せない"""
    d = _calc.read_diar(tid)
    return d["latest"] if d else None


# ---------- 声の特徴と照合 ----------
def voice_rows(segs, key):  # flow: alias ok  ① の行の選び方 voice_groups(声の特徴を取る行・1 人あたりの上限)を ③ の覚える計画に渡す(RS7 で割る)
    """行 → {キー: ([(開始, 終了)...], 合計秒)}(① の voice_groups。短い行・声が混ざっている行は使わない)"""
    return _calc.voice_groups(segs, key)


def voice_row_min():
    """声の特徴を取る行の最短(秒。① の VOICE_MIN_ROW)。③ の覚える計画が「短い行」を数えるため"""
    return _calc.VOICE_MIN_ROW


def embed(job, spec, wav, groups, hints):
    """声の特徴 -> [長さ 1 の特徴 or None](groups と同じ並び)。groups = [[(開始, 終了)…]](元の動画の秒)・spec["embedding"] = 判別モデル・
    hints = {"start": wav の頭の元の動画の秒, "sourcePath"?: 元の動画, "end"?}。sourcePath があれば(声を覚えるジョブ)音声を取り出してから・
    本物ならモデルを取ってから特徴を取る(判別のあとの照合は判別の音声とモデルをそのまま使う)。
    ② が足すこと: 音声の取り出しと状態の表示・モデルの取得(疑似は取らない)"""
    if hints.get("sourcePath"):
        job["state"], job["phase"], job["device"] = "extracting", "音声を取り出し中", "cpu"
        _recognize.extract_audio(job, {"sourcePath": hints["sourcePath"], "start": hints["start"], "end": hints.get("end")}, wav)
        if not _backend.is_fake():
            job["state"] = "loading"
            _calc.ensure_diar_models(job, spec["embedding"])
        job["state"], job["phase"], job["progress"] = "running", "声の特徴を取り出し中(CPU)", 0.0
    return _calc.embed_groups(job, wav, spec["embedding"], groups, hints["start"])


def match_known_voices(job, spec, wav, groups, voices, hints):
    """判別の音声 wav の話者ごとの行(groups = {話者の id: ([(開始, 終了)...], 秒)})の声の特徴を取り、覚えている声(voices)と照らし合わせる
    -> ({話者の id: (名前, 似ている度合い)}, {話者の id: 経過})(① の match_voices_explain の形)。話者が無ければ ({}, {})。
    ② が足すこと: 状態の表示・声の特徴(ワーカー)と照合(①)の 2 段をつなぐ"""
    ids = list(groups)
    if not ids:
        return {}, {}
    job["phase"] = "覚えている声と照らし合わせ中"
    vecs = embed(job, spec, wav, [groups[i][0] for i in ids], hints)
    return _calc.match_voices_explain(dict(zip(ids, vecs)), voices)


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


# ---------- 覚えた声の置き場所(A-3。声の特徴は個人を見分けられる情報なので作業データの voices/ にだけ置く) ----------
# 置き場所は呼ぶたびに作業データ(ytt/workdata の DATA_DIR)の voices(voices_dir)。VOICES_DIR は上書き用(テストが一時フォルダを入れる)。None なら作業データの中。
# RS2-9 の不具合の直し(動きが変わる): 以前は読み込みのときに作り、serve の set_data_dir が直さなかったので、入口から起動すると
# 覚えた声が作業データではなく editor のフォルダの voices に読み書きされていた(判別のモデルの DIAR_DIR だけ直っていた)
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
    _fsio.atomic_write(voices_path(emb), json.dumps({"schema": "ytt-voices/v1", "embedding": emb, "voices": voices}, ensure_ascii=False).encode("utf-8"), fsync_required=True)


@contextlib.contextmanager
def voices_edit(emb):
    """覚えた声(判別モデル emb)を読んで書き換えさせ、変わっていれば書く(登録簿のロックの中。途中で例外なら書かない)"""
    with _voices_lock:
        voices = load_voices(emb)
        before = json.dumps(voices, sort_keys=True)
        yield voices
        if json.dumps(voices, sort_keys=True) != before:
            save_voices(emb, voices)


def merge_voice(old, vec, rows, sec):
    """覚える声の 1 人分 -> {"vec", "rows", "sec", "updatedAt"}。前に覚えた声 old(同じ次元のとき)とは、使った長さで重みを付けて混ぜる
    (配信ごとの声の揺れをならす。前の重みは 1 時間まで)。② が足すこと: 登録簿の 1 人分の形と混ぜ方(長さ 1 にするのは ① の _unit)"""
    if old and len(old["vec"]) == len(vec):
        w0 = min(float(old.get("sec") or 0.0), 3600.0)
        vec = _calc._unit([a * w0 + b * sec for a, b in zip(old["vec"], vec)]) or vec
        rows, sec = rows + int(old.get("rows") or 0), sec + w0
    return {"vec": [round(x, 6) for x in vec], "rows": rows, "sec": round(sec, 1), "updatedAt": int(time.time() * 1000)}
