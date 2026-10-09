# -*- coding: utf-8 -*-
"""「編集」のサーバーの部品: ジョブの本体(文字起こし・選んだ行/範囲/全体の再認識・疑わしい所の認識し直し)と文書への反映・再認識の記録・長い行の分け直し(段10 で editor/serve.py から分けた。git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。
認識そのもの(ワーカー・モデル・音声の取り出し・声の検出のやり直し・範囲の行・記録・単語の時刻)は役割で組み直す RS2-4〜7(2026-10-10)に pipeline/transcribe へ移した(下の _MOVED の転送で ed_jobs.名前 のまま読める)。

名前は serve.py からも見える(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
"""
import bisect
import json
import os
import re
import time
import uuid

from ytt import errors as _errors, fsio as _fsio, jobs as _heavy, modfwd as _modfwd, schemas as _yschemas, tools as _tools  # noqa: E402
from pipeline.transcribe import roster as _roster  # noqa: E402,F401
from pipeline.transcribe import txbase as _txbase  # noqa: E402   ロガー・決まった値・印の文(RS2-1a。ed_state から移した)
from pipeline.transcribe import backend as _backend, txenv as _txenv  # noqa: E402   本物と疑似の差し込み口・置き場所と外の道具の口(RS2-2)
from pipeline.transcribe import postproc  # noqa: E402   行の後処理・要確認の印(RS2-4b。呼ぶたびに postproc.名前 で読む)
from pipeline.transcribe import records  # noqa: E402   認識の記録・生出力・単語の時刻(RS2-5。呼ぶたびに records.名前 で読む)
from pipeline.transcribe import worker_client  # noqa: E402   認識ワーカーとのやり取り・モデル・wav を読まずに渡す形(RS2-6。呼ぶたびに worker_client.名前 で読む)
from pipeline.transcribe import recognize  # noqa: E402   音声の取り出し・認識・範囲の行・全体の再認識の続きから(RS2-7。呼ぶたびに recognize.名前 で読む)
import ed_alt  # noqa: E402,F401
import ed_fill  # noqa: E402,F401   認識のあとの後処理 A・C・D(文字の少ない行を別の読みで埋める。10-08 の実験ループ。0.60.0)
import ed_llm  # noqa: E402,F401   LLM の後処理 E(名簿の呼び名の聞き違いらしい所だけ。P18。0.61.0)
import ed_ytcap  # noqa: E402,F401   YouTube の字幕の候補(run_job の ytcap・autoYtcap)
import ed_evalbatch  # noqa: E402,F401   評価用の作り直し(run_job の evalRedo)
import ed_learn  # noqa: E402,F401
import ed_relink  # noqa: E402,F401
import ed_speakers  # noqa: E402,F401
import ed_state  # noqa: E402,F401
import ed_store  # noqa: E402,F401
from pipeline.transcribe import tx_engines  # noqa: E402,F401   名前と版だけ(ネイティブの部品は読み込まない)


def split_terms(text):
    """「、」「,」・改行で区切った語の並び(用語集の欄など)"""
    return [t.strip() for t in re.split(r"[\r\n,、]+", str(text or "")) if t.strip()]


def glossary_of(req, st=None):
    """要求の用語集(200 語まで)と、自動で足す語(autoGloss。よく直される正しい語)-> (用語集, 自動の語)。st = 読んである設定"""
    glossary = split_terms(req.get("glossary"))[:200]
    return glossary, (ed_learn.auto_glossary(glossary, settings=st) if req.get("autoGloss") is not False else [])


def validate_job(req):
    src = _txenv.check_source(req.get("sourcePath"))
    dur = _txenv.media_duration(src)
    start = _yschemas.num_or(req.get("start"), 0.0) or 0.0
    end = _yschemas.num_or(req.get("end"))
    if start < 0:
        raise _errors.ApiError("bad_range", "開始時刻が正しくありません", 400)
    if dur is not None and start >= dur - 0.5:
        raise _errors.ApiError("bad_range", "開始時刻がファイルの長さ(%s)を超えています" % _yschemas.fmt_hms(dur), 400)
    if end is None or (dur is not None and end > dur):
        end = dur
    if end is not None and end <= start + 0.5:
        raise _errors.ApiError("bad_range", "終了は開始より後にしてください", 400)
    if end is not None and end - start > _txbase.MAX_SPAN_SEC:
        raise _errors.ApiError("too_long", "1回に処理できるのは6時間までです。範囲を分けてください", 400)
    whole = start == 0 and (end is None or dur is None or abs(end - dur) < 0.5)
    # 切り抜きスタジオが書き出した mp4 なら、隣の .clip.json(youtube-tools-clip/v1)を読んで文書に残す(元の配信のどこかが分かる)。
    # 不正・別の版なら使わずに警告だけ(文字起こし自体は続ける)。範囲指定でも clip はそのまま残す:
    # 文書の時刻は「動画ファイルの先頭 = 0 秒」のままなので、元の配信の時刻は常に clip_offset(clip) + 行の時刻になる(範囲の開始で補正しない)
    pm = ed_state.pio(required=False)
    clip, clip_warn, _clip_path = pm.find_clip(src, dur) if pm else (None, None, None)
    warnings = [clip_warn] if clip_warn else []
    model = str(req.get("model") or "small").strip()
    if not ed_state.valid_model(model):
        raise _errors.ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or "ja")
    if lang not in _txbase.LANGS:
        lang = "ja"
    st = ed_learn.load_settings()   # 保存した設定は 1 回だけ読む(自動の用語・下の 4 つの auto・行を分ける文字数)
    glossary, gauto = glossary_of(req, st)
    ev = req.get("evalSet") is True   # 評価用として文字起こしする: 用語集・呼び名・置換辞書・学習した置換を使わない(git の履歴(679ff01 以前)の docs/archive/project/eval-set-procedure.md の 2)
    into = None
    if req.get("intoDoc") not in (None, ""):
        # 「編集」の文字起こしの無い文書(文字起こしせずに開いた動画)に行を入れる。id・題名・作った日・clip・編集の内容はそのまま
        into = str(req.get("intoDoc"))
        target = ed_store.read_transcript(into)
        if os.path.normcase(os.path.abspath(str(target.get("sourcePath") or ""))) != os.path.normcase(src):
            raise _errors.ApiError("bad_request", "文字起こしを入れる文書の動画と、選んだ動画が違います", 400)
        if ed_store.doc_has_rows(target):
            raise _errors.ApiError("not_empty", "この文書にはもう行があります(新しい文字起こしとして作ってください)", 409)
        if not str(req.get("title") or "").strip():
            req = dict(req, title=target.get("title") or "")
        ev = ev or target.get("evalSet") is True
    ed_relink.eval_name_guard(src, ev)   # 評価用のフォルダの設定が消えているのに「評価用」のフォルダの動画なら止める(学習用に混ざらないように。master-plan Q0)
    ev = ev or ed_relink.in_eval_dir(src)   # 評価用のフォルダの動画は、画面のチェックが無くても評価用(2026-10-01)
    if ev:
        glossary, gauto = [], []
    title = str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]
    ctx = stream_context({"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src}, req.get("autoContext") is True and not ev)

    def pref(key, default_on=False):
        """要求の真偽値があればそれ、無ければ(まとめて実行・古い画面)保存した設定。default_on = 設定に無いときもオン(明示の false だけオフ)"""
        if isinstance(req.get(key), bool):
            return req[key]
        return st.get(key) is not False if default_on else st.get(key) is True
    return {"sourcePath": src, "sourceName": os.path.basename(src), "start": round(start, 2), "end": round(end, 2) if end else None, "intoDoc": into,
            "duration": dur, "whole": whole, "model": model, "engine": worker_client.req_engine(req, model), "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto",
            "vadMode": req.get("vadMode") if req.get("vadMode") in ("weak", "normal", "off") else ("off" if req.get("vad") is False else "weak"),
            "boost": req.get("boost") is True, "autoDict": req.get("autoDict") is not False and not ev, "wordSplit": req.get("wordSplit") is not False,
            "splitChars": split_chars_for(req, st),
            "autoRedo": req.get("autoRedo") is True, "redoLarge": req.get("redoLarge") is not False,
            # 終わったら 2つ目のエンジンでも聞く(D1-b)。要求に無ければ(まとめて実行・古い画面)保存した設定 autoAlt
            "autoAlt": pref("autoAlt") and not ev,
            # 終わったら元の配信の YouTube の字幕と比べる(案 A1)。要求に無ければ保存した設定 autoYtcap。元の配信が分からない文書は ytcap_after_transcribe が黙って飛ばす
            "autoYtcap": pref("autoYtcap") and not ev,
            # 認識のあとの後処理(ed_fill の A・C・D。既定オン。0.60.0)。要求に無ければ保存した設定 autoFill(明示の false だけオフ)。評価用には当てない
            "autoFill": pref("autoFill", default_on=True) and not ev,
            # LLM の後処理(ed_llm。名簿の呼び名の聞き違いらしい所だけ。既定オン = decisions 3-17。0.61.0)。評価用には当てない
            "autoLlm": pref("autoLlm", default_on=True) and not ev,
            # 行の頭の話者名(「名前:」)を外す(ed_fill の B。既定オン。0.67.0)。評価用には当てない
            "stripNames": pref("stripNames", default_on=True) and not ev,
            # 終わったら話者を自動で判別する(v0.50.0)。要求に無ければ保存した設定 autoDiarize。評価用はこの値によらず常に(ed_speakers.autodiar_after_transcribe)
            "autoDiarize": pref("autoDiarize"),
            "stripPunct": req.get("stripPunct") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx, "evalSet": ev,
            "autoLearned": req.get("autoLearned") is True and not ev, "clip": clip, "warnings": warnings,
            "title": title}


NO_RETRY = ("extract_failed", "bad_range", "too_long", "bad_model", "bad_engine", "bad_ext", "not_found", "no_speech")   # 同じ指定ではまた失敗する理由(2 周目 N2)


def public_job(j):
    out = {k: j[k] for k in ("id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt")}
    out["errorDetail"] = j.get("errorDetail") or ""   # 失敗の原文・内部の名前(画面は「詳しく」の中だけ。M9・S12)
    out["internal"] = bool(j.get("internal"))   # 想定外の失敗(画面は「途中で止まりました」の決まった文)
    out["canRetry"] = _heavy.can_retry(j)   # 画面の [やり直す](同じ指定でもう一度)
    sp = j.get("spec") or {}
    out["warnings"] = list(sp.get("warnings") or [])   # 例: 隣の .clip.json が壊れている・別の版(文字起こしは続ける)
    out["hasClip"] = bool(sp.get("clip"))
    out["into"] = sp.get("intoDoc") or None   # 「編集」: 文字起こしの無い文書に入れる文字起こし(画面の「この動画を文字起こしする」)
    out["named"] = list(j.get("named") or [])       # A-3: 話者判別のあと、覚えている声で名前を付けた話者 [{"speaker", "name", "score"}]
    out["learned"] = list(j.get("learned") or [])   # A-3: 声を覚えた人の名前
    out["auto"] = bool(sp.get("auto"))   # 文字起こしのあとの自動の話者判別(v0.50.0)
    out["autoSkipped"] = j.get("autoSkipped") or ""   # 自動の判別を動き出すときにやめた理由(has_speakers・reviewed・empty)
    out["redo"] = bool(sp.get("evalRedo"))   # 未確認の評価用の作り直し(ed_evalbatch)
    out["redoOne"] = bool((sp.get("evalRedo") or {}).get("one"))   # 1 本ずつの作り直し(画面が押した。終わるまで編集を止める)
    out["redoSkipped"] = j.get("redoSkipped") or ""            # 手が入っていたので作り直さなかった理由
    if j.get("voiceError"):
        out["warnings"].append(j["voiceError"])
    out["warnings"] += [w for w in (j.get("warnings") or []) if w not in out["warnings"]]   # ジョブの中で足した注意(以前は画面に届いていなかった)
    out["vadNote"] = j.get("vadNote") or ""          # 声の検出を緩めてやり直した(4-2)
    out["normNote"] = j.get("normNote") or ""        # 30fps にそろえた・そろえられなかった理由(Q1。ed_relink.norm_run)
    out["normOk"] = bool(j.get("normOk"))
    out["kept"], out["emptyKept"], out["loose"] = j.get("kept", 0), j.get("emptyKept", 0), j.get("loose", 0)   # 全体の再認識で残した行(3-4)
    return out


def stream_context(doc, enabled=True):
    """配信ごとの文脈(段1-2): その配信に出る人を、配信のチャンネル名・コラボ相手(スタジオの data.json を読むだけ)・話者の名前・題名から決め、
    その人の名前と呼び名だけをヒントの語にする。**題名の文字列そのものは渡さない**。
    doc: clip・title・sourceName・sourcePath・speakers を持つ辞書。-> {"members": [{"name", "from"}], "terms": [語]}"""
    if not enabled:
        return {"members": [], "terms": []}
    r = _roster.load(_txenv.ROSTER)
    clip = doc.get("clip") if isinstance(doc.get("clip"), dict) else {}
    src = clip.get("source") if isinstance(clip.get("source"), dict) else {}
    try:
        info = ed_store.studio_stream(src.get("videoId")) if src.get("videoId") else None
    except Exception as e:   # 他のツールのデータが読めなくても、文脈なしで続ける
        _txbase.log.info("スタジオの配信の情報を読めませんでした: %s", str(e)[:120])
        info = None
    path = str(doc.get("sourcePath") or "")
    titles = [src.get("title"), (info or {}).get("title"), doc.get("title"), doc.get("sourceName"),
              os.path.basename(os.path.dirname(path)) if path else ""]   # 動画の入ったフォルダ(スタジオは配信の題名のフォルダに書き出す)
    ctx = _roster.build_context(r, (info or {}).get("channel", ""), [c["channel"] for c in (info or {}).get("collab") or []],
                                [s.get("name") for s in doc.get("speakers") or [] if isinstance(s, dict)], [str(t or "")[:300] for t in titles])
    ctx["terms"] = _roster.member_terms([m["name"] for m in ctx["members"]], r)
    return ctx


# 字幕の文字数(12 ②。ユーザー決定 2026-09-26: 縦 16・横 28、パックの字幕は2段 = 縦 8・横 14 文字前後で改行)。設定の "subtitle" に保存する
SUBTITLE_DEFAULT = {"orientation": "vertical", "maxChars": {"vertical": 16, "horizontal": 28}, "wrapChars": {"vertical": 8, "horizontal": 14},
                    "splitChars": postproc.SPLIT_CHARS}   # splitChars = 文字起こしの行を分ける文字数(0.59.5 から maxChars とは別。既定 24 = 0.59.6。画面の欄はまだ無い = settings.json か環境変数 TRANSCRIBE_SPLIT_CHARS)
ORIENTATIONS = ("vertical", "horizontal")


def _chars_in(v, lo, hi, default=None):
    """文字数の値(数。bool・NaN・無限は除く。小数は切り捨て)が lo〜hi なら int、違えば default(設定の subtitle・要求の splitChars)"""
    x = _yschemas.num(v)
    return int(x) if x is not None and lo <= x <= hi else default


def subtitle_settings(st=None):
    """設定の subtitle(字幕の向き・1つの字幕の最大文字数・パックの字幕の改行の文字数)を、範囲を確かめて返す(無い・おかしい値は既定)"""
    v = (st if st is not None else ed_learn.load_settings()).get("subtitle")
    v = v if isinstance(v, dict) else {}
    out = {"orientation": v.get("orientation") if v.get("orientation") in ORIENTATIONS else SUBTITLE_DEFAULT["orientation"]}
    for key, lo, hi in (("maxChars", 4, 80), ("wrapChars", 2, 40)):
        src = v.get(key) if isinstance(v.get(key), dict) else {}
        out[key] = {}
        for o in ORIENTATIONS:
            out[key][o] = _chars_in(src.get(o), lo, hi, SUBTITLE_DEFAULT[key][o])
    out["splitChars"] = _chars_in(v.get("splitChars"), 8, 80, SUBTITLE_DEFAULT["splitChars"])
    return out


def subtitle_max_chars(req=None, st=None):
    """字幕の最大文字数(要求の splitChars → 要求の subtitleOrientation → 設定の字幕の向き)。「長い行を分け直す」(/api/resplit)が使う = 0.59.4 までの split_chars_for の決め方"""
    req = req or {}
    n = _chars_in(req.get("splitChars"), 4, 80)
    if n is not None:
        return n
    sub = subtitle_settings(st)
    o = req.get("subtitleOrientation")
    return sub["maxChars"][o if o in ORIENTATIONS else sub["orientation"]]


def split_chars_for(req=None, st=None):
    """行を分けるときの最大文字数(要求の splitChars → 環境変数 TRANSCRIBE_SPLIT_CHARS → 設定の subtitle.splitChars。既定 24 = 0.59.6。0.59.5 は 40)。
    要求の splitChars は「長い行を分け直す」(/api/resplit)が字幕の最大文字数を明示して渡す。文字起こしの要求には付けない(0.59.5 から。画面の app-rows.js の subtitleReq)。
    0.59.4 までは字幕の向きの最大文字数(縦 16)で分けていた = 区切りを意識した校正で 73% が戻された(plan/line-b-row-split.md の 8)ので、字幕の向きでは変えない"""
    req = req or {}
    n = _chars_in(req.get("splitChars"), 4, 80)
    if n is not None:
        return n
    env = os.environ.get("TRANSCRIBE_SPLIT_CHARS", "").strip()
    if env.isdigit() and 8 <= int(env) <= 80:
        return int(env)
    return subtitle_settings(st)["splitChars"]


def dict_pairs(spec):
    """置換辞書の組 [(誤, 正)](autoDict のときだけ。評価用の文書は autoDict が外れるので当たらない)= 設定の replacements + 名簿の呼び名の表記ゆれ(roster.variant_pairs。0.59.7。
    はーちゃま → はあちゃま・ラミー → ラミィ・吹雪 → フブキ。確かめ済み 22 本で名前の再現率 28 → 40/53・普段の文書 1045 行で変わる行 0 = plan/line-b-transcription.md の「10-08 の実験ループ」B)。
    設定の組が先(ユーザーの辞書が名簿の表より強い)。名簿が読めなければ設定の組だけ"""
    if not spec.get("autoDict"):
        return []
    pairs = ed_learn.parse_replacements(ed_learn.load_settings().get("replacements"))
    try:
        pairs += _roster.variant_pairs(_roster.load(_txenv.ROSTER))
    except (OSError, ValueError, TypeError, KeyError) as e:   # 名簿の表は補助なので、作れなくても認識は止めない
        _txbase.log.warning("名簿の表記ゆれの表を作れませんでした: %s", e)
    return pairs


def dict_learned():
    """辞書の版(records.dict_version)の learned の元の文字: 学習済みの置換の規則と採用・却下の記録(別のエンジン alt・YouTube の字幕 yt の数は除く)。
    学習(ed_learn)を読むのは文書の側のここだけ(① の records は ed_learn を読まない。serve が records.set_dict_inputs で登録する。RS2-5)"""
    rules = ed_learn.learn_rules()
    return json.dumps({"rules": sorted([w, r, x["pos"], len(x["docs"])] for (w, r), x in rules.items()), "fb": {k: v for k, v in ed_learn.load_feedback().items() if k not in ("alt", "yt")}},
                      ensure_ascii=False, sort_keys=True)


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
    original の無い文書(文字起こしせずに開いた)でも、いつ・何で認識し直したかは残す(replaced は空)。pairs = 作ってある dict_pairs(spec)"""
    spans = [[round(float(a), 3), round(float(b), 3)] for a, b in spans]
    if not spans:
        return
    # 機械が行を書き換えるので、「動画を全部聞いて確かめた」印(評価ドリル。ed_drill)も外す。行の proofed を外すのと同じ時に。
    # 再認識(each・range・whole)と疑わしい所の認識し直し(redo)は、どれも差し替える前にここを通る
    doc.pop("evalReviewed", None)
    rep = replaced[:MAX_REPLACED_ROWS]
    run = dict(records._run_base(spec, pairs), kind=kind, device=str(spec.get("device") or ""),
               range=[min(a for a, _ in spans), max(b for _, b in spans)], replaced=rep)
    run["settings"]["autoDict"] = bool(spec.get("autoDict"))
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
    old = records.read_words(tid) or []
    keep = [w for w in old if not (a - 1e-6 <= (w[0] + w[1]) / 2 <= b + 1e-6) or _in_spans((w[0] + w[1]) / 2, keep_spans)]
    records.write_words(tid, keep + [list(w) for w in new_words], model)


def _fresh_id(used, make, n=0):
    """行の新しい id: make(n+1), make(n+2), … のうち used に無い最初のもの(used に足す)。-> (id, その番号)"""
    while True:
        n += 1
        sid = make(n)
        if sid not in used:
            used.add(sid)
            return sid, n


def resplit_doc(obj):
    """POST /api/resplit {"id", "orientation"?, "baseUpdatedAt"?}: 今の文書の長い行を、保存してある単語の時刻で分け直す(12 ②)。
    分けるのは: 校正済みでない・文字が単語と一致する(人が直していない)・最大文字数 + 2 を超える行だけ。分けた行は話者・印・タグ・メモを引き継ぐ。
    分ける前の文書は履歴に残す(「以前の版に戻す」で戻せる)。-> {"changed": 分けた行の数, "added": 増えた行, "skipped": 単語と一致しない長い行, "rows", "updatedAt"}"""
    tid = str(obj.get("id") or "")
    o = obj.get("orientation")
    max_chars = subtitle_max_chars({"subtitleOrientation": o, "splitChars": obj.get("splitChars")})   # 分け直しは字幕の最大文字数(向きごと)で。文字起こしの分ける文字数(40)ではない
    with ed_store._save_lock:
        doc = ed_store.read_transcript(tid)
        base = obj.get("baseUpdatedAt")
        if isinstance(base, int) and not isinstance(base, bool) and base != int(doc.get("updatedAt") or 0):
            raise _errors.ApiError("conflict", "別の画面で先に保存されています。読み直してから、もう一度押してください", 409)
        words = records.read_words(tid)
        if not words:
            raise _errors.ApiError("no_words", "この文字起こしには単語の時刻がありません(v0.17.0 より前の文字起こし・単語の時刻を使わない設定)。"
                                       "行を選んで「範囲を再認識」すると、その範囲の単語の時刻を取り直せます", 400)
        mids = [(w[0] + w[1]) / 2 for w in words]
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        used = {str(g.get("id")) for g in segs}
        out, changed, added, skipped = [], 0, 0, 0
        for g in segs:
            text = str(g.get("text") or "")
            if g.get("proofed") is True or len(postproc._squash(text)) <= max_chars + postproc.SPLIT_SLACK:
                out.append(g)
                continue
            a, b = float(g.get("start") or 0), float(g.get("end") or 0)
            lo, hi = bisect.bisect_left(mids, a - 0.05), bisect.bisect_right(mids, b + 0.05)
            ws = [tuple(w) for w in words[lo:hi]]
            joined = "".join(t for _a, _b, t in ws)
            if ws and postproc._squash(joined) == postproc._squash(text):
                strip = False
            elif ws and postproc._squash(postproc.strip_punct(joined)) == postproc._squash(text):
                strip = True        # 句読点を取り除いた行(stripPunct)
            else:
                skipped += 1        # 人が直した行・辞書で置き換えた行・単語の無い行は分けない
                out.append(g)
                continue
            parts = postproc.split_segment({"start": a, "end": b, "text": joined, "words": ws}, max_chars)
            if len(parts) < 2:
                out.append(g)
                continue
            changed += 1
            added += len(parts) - 1
            for k, p in enumerate(parts):
                t = postproc.strip_punct(p["text"]) if strip else p["text"]
                base = str(g.get("id"))
                sid = _fresh_id(used, lambda n: "%s-%d" % (base, n), k)[0] if k else base   # 2つめからは <元の id>-2, -3 …(ほかの行と重ならない番号)
                out.append(dict(g, id=sid, start=round(p["start"], 2), end=round(p["end"], 2), text=t[:_txbase.MAX_TEXT]))
        if not changed:
            return {"changed": 0, "added": 0, "skipped": skipped, "rows": len(segs), "updatedAt": int(doc.get("updatedAt") or 0)}
        ed_store.snapshot(tid)   # 分ける前を「以前の版に戻す」に残す
        doc["segments"] = sorted(out, key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["resplit"] = {"maxChars": max_chars, "rows": changed, "at": doc["updatedAt"]}
        ed_store.apply_edit_cuts(tid, doc)
        ed_store.write_doc(tid, doc)
        return {"changed": changed, "added": added, "skipped": skipped, "rows": len(doc["segments"]), "updatedAt": doc["updatedAt"]}


def _transcribe_checked(job, spec, wav, total):
    """run_job の本物の認識: エンジンを確かめてから transcribe_real(行の生成器)"""
    worker_client.check_engine(spec)
    job["state"] = "loading"
    return recognize.transcribe_real(job, spec, wav, total)


def run_job(job):
    """文字起こし(kind transcribe)のジョブの本体。ほかの種類は登録した本体へ回す(ytt/jobs の JOB_RUNNERS。テストが ed_jobs.run_job で直に動かす)"""
    kind = job.get("kind")
    if kind not in (None, "transcribe"):
        return _heavy.JOB_RUNNERS[kind](job)
    spec = job["spec"]
    # 未確認の評価用の作り直し(ed_evalbatch): 動き出す直前にもう一度「手つかず」を確かめる。手が入っていれば認識せずに「作り直しませんでした」
    if spec.get("evalRedo") and ed_evalbatch.eb_redo_skip_at_start(job):
        return
    with _heavy.job_temp_wav(job) as wav:
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        recognize.extract_audio(job, spec, wav)
        total = _txenv.media_duration(wav) or (spec["end"] - spec["start"] if spec["end"] else 0)
        t_rec = time.monotonic()   # 認識にかかった時間(モデルの読み込みを含む)。recognition.runs に残す
        gen = _backend.select().transcribe(job, spec, wav, total, _transcribe_checked)
        raw_asr = []   # 生出力(<id>.asr.json)
        gen = records.capture_raw(gen, raw_asr, spec["start"])
        pairs = dict_pairs(spec)
        lrules, lfb = (ed_learn.learn_rules(), ed_learn.load_feedback()) if spec.get("autoLearned") else ({}, None)
        rows = list(postproc.expand_segments(gen, spec, total))
        rows, names_n = ed_fill.fill_strip_names(spec, rows)   # 行の頭の「名前:」を外す(設定 stripNames。0.67.0)
        # 認識のあとの後処理(設定 autoFill。0.60.0): 末尾の重複を捨て、文字の少ない行の窓を SenseVoice で読んで埋める(A・C)。読めなければ警告だけ
        rows, fill_rec, fill_read = ed_fill.fill_after_rows(job, spec, rows, wav, total)
        _heavy.check_cancel(job)
        out = _rows_to_doc(job, spec, rows, pairs, lrules, lfb)
        if fill_read is not None:   # D: 別のエンジンも同じ呼び名なら 1 字違いを名簿の呼び名に(置換辞書のあと)
            fill_rec["agree"] = ed_fill.fill_agree_doc(job, out["segs"], fill_read, total, spec)
        _heavy.check_cancel(job)
        # E: 名簿の呼び名の聞き違いらしい所だけを LLM で直す(設定 autoLlm。P18。選んだ所が無ければ LLM を読み込まない・失敗しても警告だけ)
        llm_rec, llm_items = ed_llm.llm_after_doc(job, spec, out["segs"])
        _heavy.check_cancel(job)
        fields = _doc_fields(job, spec, out, total, t_rec, pairs)
        if fill_rec:
            fields["recognition"]["runs"][-1]["fill"] = fill_rec   # 後処理の記録(読んだ窓・置き換えた行・捨てた行・直した呼び名)
        if names_n:
            fields["recognition"]["runs"][-1]["names"] = names_n   # 話者名を外した行の数(B)
        if llm_rec:
            fields["recognition"]["runs"][-1]["llm"] = llm_rec   # LLM の後処理の記録(選んだ所・案・当てた数・断った理由)
        if spec.get("evalRedo"):
            # 評価用の作り直し: 同じ文書の行・機械の出力を置き換える(評価用の再認識を断る決まりの、この道だけの例外。ユーザー承認 2026-10-04)。
            # 認識の間に手が入っていたら書かない(新しい文書も作らない)
            tid = ed_evalbatch.eb_redo_fill(job, spec, fields)
            if tid is None:
                return
        else:
            tid = ed_store.fill_doc(spec, fields) if spec.get("intoDoc") else None
        if tid is None:
            tid = uuid.uuid4().hex[:12]
            doc = dict({"schema": "transcribe/v1", "id": tid, "title": spec["title"], "sourcePath": spec["sourcePath"], "sourceName": spec["sourceName"]},
                       **fields, createdAt=fields["updatedAt"])
            if spec.get("clip"):
                doc["clip"] = spec["clip"]   # youtube-tools-clip/v1 の中身そのもの(transcript/v1 にもそのまま入る)
            if spec.get("evalSet"):
                doc["evalSet"] = True
            ed_store.write_doc(tid, doc)
        try:
            records.write_words(tid, out["words"], spec["model"])
        except OSError as e:
            _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        try:
            records.write_asr(tid, raw_asr, fields["recognition"]["runs"][-1])
        except (OSError, TypeError, ValueError) as e:
            _txbase.log.warning("生出力を保存できませんでした: %s %s", tid, e)
        if llm_items:
            ed_llm.llm_write(tid, llm_rec, llm_items)   # LLM の生の提案・採否(<id>.llm.json。あとで「あり/なし」を測り直せる)
        # 30fps でなければ、同じジョブの続きで <名前>_30fps.mp4 を作って付け替える(Q1。SLOTS はこのジョブが持っている。
        # 文書はもう書いてあるので、失敗・取り消しでも元の動画のまま残る = 文字起こしの結果は失わない。評価用は作らない)
        ed_relink.norm_after_transcribe(job, spec, tid)
        # 話者の自動判別(評価用は常に・それ以外は設定 autoDiarize。v0.50.0)。「完了」にする前に足す = 判別の待ちの文書をドリルが開く間を作らない
        ed_speakers.autodiar_after_transcribe(job, spec, tid)
        _heavy.job_done(job, tid)
        if spec.get("autoRedo") and any(postproc.SPARSE_FLAG in g["flag"] for g in out["segs"]):   # 疑わしい所を自動で認識し直す(設定。既定オフ。③-2)
            try:
                _heavy.add_job(redo_spec(tid, {"redoLarge": spec.get("redoLarge", True), "oldLp": out["sparseLp"]}), "redo")
            except _errors.ApiError as e:
                _txbase.add_warning(job, "疑わしい所の認識し直しを始められませんでした: " + e.message)
        ed_alt.alt_after_transcribe(job, spec, tid)   # 設定 autoAlt: 2つ目のエンジンでも聞いて、食い違う所に候補を出す(既定オフ・評価用は除く。D1-b)
        ed_ytcap.ytcap_after_transcribe(job, spec, tid)   # 設定 autoYtcap: 元の配信の YouTube の字幕と比べて候補を出す(既定オフ・評価用と元の配信が分からない文書は黙って飛ばす。A1)


def _rows_to_doc(job, spec, rows, pairs, lrules, lfb):
    """整えた行 → 文書の行(要確認の印・学習した置換・置換辞書)・機械の出力 original・単語の時刻。
    -> {"segs", "original", "words", "dictApplied", "learnApplied", "sparseLp"(「長い区間に文字が少ない」行の avg_logprob。認識し直したときに良くなったかを比べる。③-2)}"""
    segs, prev, original, words, sparse_lp, dict_n, learn_n = [], [], [], [], {}, 0, 0
    terms = _roster.prompt_terms(spec)
    for s in rows:
        if not s["text"]:
            continue
        seg = {"id": "s%d" % (len(segs) + 1), "start": round(s["start"] + spec["start"], 2), "end": round(s["end"] + spec["start"], 2),
               "text": s["text"][:_txbase.MAX_TEXT], "speaker": "", "flag": ""}
        seg["flag"] = postproc.make_flags({**s, "text": seg["text"], "start": seg["start"], "end": seg["end"]}, prev, spec["language"], terms)
        if isinstance(s.get("fill"), dict):   # 別の読みで埋めた行(ed_fill の A): 印と元の文字を残す(画面の「別の読み」の札で戻せる)
            seg["fill"] = {"from": str(s["fill"].get("from") or "")[:_txbase.MAX_TEXT], "by": str(s["fill"].get("by") or "")[:20]}
            mark = ed_fill.FILL_SPK_FLAG if seg["fill"]["by"] == ed_fill.FILL_SPK_BY else ed_fill.FILL_FLAG   # B は話者名を外した印
            seg["flag"] = "、".join(x for x in (mark, seg["flag"]) if x)[:100]
        prev.append(seg["text"])
        if postproc.SPARSE_FLAG in seg["flag"] and s.get("avg_logprob") is not None:
            sparse_lp[seg["id"]] = float(s["avg_logprob"])
        if lrules:   # 確度が高い学習済みの置換は、機械の出力側にも反映する(そうしないと自分の置換を「人が直した」と数えて自己強化してしまう)
            seg["text"], ln = ed_learn.auto_learned_replace(seg["text"], lrules, lfb)
            learn_n += ln
        original.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], **postproc.machine_conf(s)})   # 機械の出力をそのまま残す(修正からの学習・精度の測定に使う)
        words.extend(postproc.row_words(s, spec["start"]))
        seg["text"], n = ed_learn.apply_replacements(seg["text"], pairs)
        dict_n += n
        segs.append(seg)
        job["segments"] = len(segs)
    return {"segs": segs, "original": original, "words": words, "dictApplied": dict_n, "learnApplied": learn_n, "sparseLp": sparse_lp}


def _doc_fields(job, spec, out, total, t_rec, pairs=None):
    """新しい文字起こしの文書の中身(id・題名・動画・作った日・clip・評価用の印は除く)。recognition.runs の最初の記録・params(その時の辞書の版 dict。Q2)。
    声の検出をやり直していれば、その知らせを spec の warnings と job の vadNote に"""
    now = int(time.time() * 1000)
    params = {"beam": spec["beam"], "vadMode": spec["vadMode"], "boost": spec["boost"], "device": job.get("device", ""), "glossary": spec["glossary"][:50],
              "autoDict": bool(spec.get("autoDict")), "dictApplied": out["dictApplied"], "wordSplit": bool(spec.get("wordSplit")),
              "splitChars": spec.get("splitChars"), "stripPunct": spec.get("stripPunct", True) is not False,
              "autoLearned": bool(spec.get("autoLearned")), "learnApplied": out["learnApplied"], "glossAuto": spec.get("glossAuto", [])[:20],
              "context": records.context_record(spec), "autoFill": bool(spec.get("autoFill")), "autoLlm": bool(spec.get("autoLlm")),
              "stripNames": bool(spec.get("stripNames"))}
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


# ---------- 選んだ行の再認識 ----------
SPK_FLAGS = (_txbase.MIXED_FLAG, _txbase.WEAK_FLAG, _txbase.NONE_FLAG)


MAX_RANGE_SEC = 900


def validate_retranscribe(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    src = _txenv.check_source(doc.get("sourcePath"))
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    mode = req.get("mode") if req.get("mode") in ("range", "whole") else "each"
    if not ids and mode != "whole":
        raise _errors.ApiError("empty", "再認識する行がありません", 400)
    model = str(req.get("model") or "large-v3").strip()
    if not ed_state.valid_model(model):
        raise _errors.ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or doc.get("language") or "ja")
    st = ed_learn.load_settings()   # 自動の用語と行を分ける文字数で 1 回だけ読む
    glossary, gauto = glossary_of(req, st)
    ctx = stream_context(doc, req.get("autoContext") is True)
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["retranscribe"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    rng = None
    segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
    if mode == "whole":   # 動画全体(文書の範囲全体)を範囲と同じやり方で認識し直す。校正済みの行は残す(docs/design/whole-retranscribe-design.md の 3)
        a = _yschemas.num_or(doc.get("start"), 0.0) or 0.0
        b = _yschemas.num_or(doc.get("end")) or _txenv.media_duration(src) or max([g["end"] for g in segs] or [0.0])
        if b <= a + 0.5:
            raise _errors.ApiError("bad_range", "動画の長さが分かりません", 400)
        if b - a > _txbase.MAX_SPAN_SEC:
            raise _errors.ApiError("too_long", "1回に処理できるのは6時間までです", 400)
        ids = [g["id"] for g in segs if not g.get("proofed")]   # 校正済みでない行を差し替える(画面の選択は使わない)
        rng = [round(a, 3), round(b, 3)]
    elif mode == "range":   # 選んだ行の最初〜最後を、ひとまとまりの音声として認識し直す(間にある選んでいない行も含む)
        chosen = [g for g in segs if g["id"] in set(ids)]
        a, b = min(g["start"] for g in chosen), max(g["end"] for g in chosen)
        ids = [g["id"] for g in segs if a - 1e-6 <= (g["start"] + g["end"]) / 2 <= b + 1e-6]
        if b - a > MAX_RANGE_SEC:
            raise _errors.ApiError("too_long", "範囲が長すぎます(最大%d分)。範囲を狭めてください" % (MAX_RANGE_SEC // 60), 400)
        rng = [a, b]
    return {"tid": tid, "ids": ids, "mode": mode, "range": rng, "model": model, "engine": worker_client.req_engine(req, model), "language": lang if lang in _txbase.LANGS else "ja", "beam": 5,
            # 全体は画面の設定によらず「弱め」から(抜けを拾うのが目的。捨てすぎたら「なし」へ緩める)。明示の「なし」だけは尊重する
            "vadMode": ("off" if req.get("vadMode") == "off" else "weak") if mode == "whole"
            else req.get("vadMode") if mode == "range" and req.get("vadMode") in ("weak", "normal", "off") else "off",
            "wordSplit": mode in ("range", "whole") and req.get("wordSplit") is not False, "splitChars": split_chars_for(req, st),
            "stripPunct": req.get("stripPunct") is not False, "stripNames": st.get("stripNames") is not False,
            "device": req.get("device") if req.get("device") in ("cuda", "cpu") else "auto", "boost": req.get("boost") is True,
            "autoDict": req.get("autoDict") is not False, "glossary": glossary + gauto, "glossAuto": gauto, "context": ctx,
            "title": _heavy.job_title({"range": "範囲を再認識: ", "whole": "全体を再認識: "}.get(mode, "再認識: "), doc)}


def replace_original(orig, a, b, text):
    """機械の出力の記録のうち、a〜b にある分を、新しい機械の出力1件に差し替える(再認識の結果を『人が直した』と誤学習しないため)。"""
    return replace_original_multi(orig, a, b, [{"start": a, "end": b, "raw": text}])


def apply_retranscribe(spec, results):
    with ed_store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_retranscribe(spec, results)


def _apply_retranscribe(spec, results):
    doc = ed_store.read_transcript(spec["tid"])
    pairs = dict_pairs(spec)
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
        keep = [x for x in str(sg.get("flag", "")).split("、") if x in SPK_FLAGS]   # 話者の印は残し、文字の印は付け直す
        sg["text"], _ = ed_learn.apply_replacements(raw[:_txbase.MAX_TEXT], pairs)
        sg.pop("proofed", None)   # 機械が書き換えた行は、人が確認し直すまで校正済みにしない
        sg.pop("proofedAt", None)   # 校正した時刻も一緒に外す(次に校正済みにした時刻から数え直す)
        sg["flag"] = "、".join(([flag] if flag else []) + keep)[:100]
        unsure += 1 if flag else 0
        done += 1
        if have_orig:
            orig = replace_original(orig, sg["start"], sg["end"], raw)
    if have_orig:
        doc["original"] = orig
    ed_store.backup_doc(spec["tid"], "retranscribe")
    doc["retranscribed"] = {"model": spec["model"], "lines": done, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    ed_store.apply_edit_cuts(spec["tid"], doc)
    ed_store.write_doc(spec["tid"], doc)
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
                y["raw"] = postproc.strip_punct(joined) if strip else joined
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
    with ed_store._save_lock:   # 保存と同じロック(apply_diarization と同じ理由)
        return _apply_range(spec, lines, loose)


def _apply_range(spec, lines, loose=()):
    a, b = spec["range"]
    doc = ed_store.read_transcript(spec["tid"])
    pairs = dict_pairs(spec)
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
        text, _ = ed_learn.apply_replacements(x["raw"][:_txbase.MAX_TEXT], pairs)
        sid, n = _fresh_id(used, "r%d".__mod__, n)
        new.append({"id": sid, "start": round(x["start"], 2), "end": round(x["end"], 2), "text": text, "speaker": best, "flag": x.get("flag", "")[:100]})
        unsure += 1 if x.get("flag") else 0
    doc["segments"] = sorted(rest + new, key=lambda g: (g["start"], g["end"]))
    record_rerun(doc, spec, "whole" if spec.get("mode") == "whole" else "range", [(a, b)],
                 replaced_rows(doc.get("original") if isinstance(doc.get("original"), list) else [], [(a, b)], keep_spans), pairs)   # 差し替える前の機械の出力を残す(Q2)
    if isinstance(doc.get("original"), list):   # 守った行・元のまま残した行の機械の出力は古いまま(人が直した行との対応を壊さない)
        doc["original"] = replace_original_multi(doc["original"], a, b, new_lines, keep_spans)
    ed_store.backup_doc(spec["tid"], "retranscribe")
    n_loose = sum(1 for x in new_lines if LOOSE_FLAG in str(x.get("flag") or ""))
    doc["retranscribed"] = {"model": spec["model"], "lines": len(new), "range": [a, b], "whole": spec.get("mode") == "whole",
                            "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose, "at": int(time.time() * 1000)}
    doc["updatedAt"] = int(time.time() * 1000)
    ed_store.apply_edit_cuts(spec["tid"], doc)   # 差し替えた行の「カット済」は、編集の内容(時刻)から付け直す
    ed_store.write_doc(spec["tid"], doc)
    try:   # 単語の時刻も範囲の分を差し替える(守った行の単語は残す。古い文書は、ここで取り直せる = 「今の文書を分け直す」の案内)
        replace_words(spec["tid"], a, b, [w for x in new_lines for w in x.get("words") or []], spec["model"], keep_spans)
    except OSError as e:
        _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", spec["tid"], e)
    return {"lines": len(new), "unsure": unsure, "kept": len(plan["kept"]), "emptyKept": len(empty_ids), "loose": n_loose}


# ---------- 疑わしい所だけ認識し直す(12 ③-2。ユーザー承認 2026-09-27: 設計どおり) ----------
REDO_PAD = 1.0          # 行の前後に足す余白(秒)。ただし隣の行にはかからない(隣の行を消さないため)
REDO_MAX_ROWS = 30      # 1回で認識し直す行の上限
REDO_MAX_SEC = 600      # 時間の上限(秒)。超えたら残りの行はやめて、そこまでの結果で置き換える
REDO_BAD_FLAGS = (postproc.SPARSE_FLAG, "よくある誤認識の文", "同じ文の繰り返し", "繰り返しの可能性", "音声でない可能性", _txbase.LEAK_FLAG)


def redo_targets(doc, ids=None):
    """認識し直す行: 「長い区間に文字が少ない」の印があり、校正済みでなく、文字が機械の出力のまま(人・辞書が直していない)。
    -> [(行, 範囲の始まり, 終わり)](範囲は前後 REDO_PAD 秒。隣の行・文書の範囲の外にはかからない)"""
    segs = sorted((g for g in doc.get("segments") or [] if isinstance(g, dict)), key=lambda g: (g["start"], g["end"]))
    orig = doc.get("original") if isinstance(doc.get("original"), list) else None
    machine = {(round(float(o["start"]), 2), round(float(o["end"]), 2)): o.get("text") for o in orig or [] if isinstance(o, dict)}
    lo_doc = _yschemas.num_or(doc.get("start"), 0.0) or 0.0
    hi_doc = _yschemas.num_or(doc.get("end")) or (lo_doc + (_yschemas.num_or(doc.get("duration")) or 0.0)) or None
    out = []
    for k, g in enumerate(segs):
        if (ids is not None and g["id"] not in ids) or postproc.SPARSE_FLAG not in str(g.get("flag") or "") or g.get("proofed") is True:
            continue
        if machine and machine.get((round(float(g["start"]), 2), round(float(g["end"]), 2))) != g.get("text"):
            continue   # 機械の出力と違う(人・辞書が直した)。機械の出力が無い文書(文字起こしせずに開いた)は見分けない
        a = max(float(g["start"]) - REDO_PAD, lo_doc, float(segs[k - 1]["end"]) if k else lo_doc)
        b = float(g["end"]) + REDO_PAD
        if k + 1 < len(segs):
            b = min(b, float(segs[k + 1]["start"]))
        if hi_doc:
            b = min(b, hi_doc)
        out.append((g, round(min(a, float(g["start"])), 3), round(max(b, float(g["end"])), 3)))
    return out[:REDO_MAX_ROWS]


def redo_spec(tid, req=None):
    """疑わしい所を認識し直すジョブの指定。モデルは文字起こしと同じ(kotoba なら、redoLarge で large-v3)。VAD は普通の強さで短く区切る"""
    req = req or {}
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは認識し直せません(機械の出力=比べる基準が書き換わるため)", 400)
    _txenv.check_source(doc.get("sourcePath"))
    targets = redo_targets(doc)
    if not targets:
        raise _errors.ApiError("empty", "認識し直す疑わしい行がありません(「長い区間に文字が少ない」の印があり、校正・手直ししていない行が対象です)", 400)
    model = str(doc.get("model") or "large-v3")
    if not ed_state.valid_model(model):
        model = "large-v3"
    if "kotoba" in model.lower() and req.get("redoLarge") is not False:
        model = "large-v3"   # kotoba は聞き取りにくい音声が苦手なので、重いモデルで試す(設定)
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["redo"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    pr = doc.get("params") if isinstance(doc.get("params"), dict) else {}
    old_lp = req.get("oldLp") if isinstance(req.get("oldLp"), dict) else {}
    return {"tid": tid, "ids": [g["id"] for g, _a, _b in targets], "model": model, "language": doc.get("language") if doc.get("language") in _txbase.LANGS else "ja",
            "beam": 5, "vadMode": "normal", "wordSplit": True, "splitChars": split_chars_for({}), "stripPunct": pr.get("stripPunct", True) is not False,
            "stripNames": pr.get("stripNames", True) is not False,
            "device": "auto", "boost": pr.get("boost") is True, "autoDict": False, "glossary": [], "glossAuto": [],
            "oldLp": {k: float(v) for k, v in old_lp.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
            "title": _heavy.job_title("疑わしい所を認識し直す: ", doc)}


def redo_kwargs(spec):
    """疑わしい所を認識し直すときの設定: VAD は普通の強さで、短い無音でも区切る(長い塊に単語1つ・途中を飛ばす、を減らす)"""
    kw = worker_client.whisper_kwargs(spec)
    kw["vad_filter"] = True
    kw["vad_parameters"] = {"min_silence_duration_ms": 250, "speech_pad_ms": 200}
    kw["chunk_length"] = 10
    return kw


def redo_better(row, lines, old_lp=None):
    """認識し直した結果が良くなったか: 文字が増えた・まだ疑わしい印(文字が少ない・よくある誤認識・繰り返し・BGM)が無い・
    avg_logprob が分かれば上がった。-> (良くなったか, 理由)"""
    if not lines:
        return False, "何も認識されない"
    new_chars, old_chars = sum(postproc.text_chars(x["raw"]) for x in lines), postproc.text_chars(row.get("text"))
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
    with ed_store._save_lock:
        tid = spec["tid"]
        doc = ed_store.read_transcript(tid)
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
                sid, k = _fresh_id(used, lambda n: "%s-r%d" % (rid, n), k)
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
        ed_store.snapshot(tid)
        doc["segments"] = sorted((g for g in segs if g["id"] not in drop), key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["redo"] = {"model": spec["model"], "rows": n_rep, "at": doc["updatedAt"]}
        ed_store.apply_edit_cuts(tid, doc)
        ed_store.write_doc(tid, doc)
        for a, b, ws in new_words:
            try:
                replace_words(tid, a, b, ws, spec["model"])
            except OSError as e:
                _txbase.log.warning("単語の時刻を保存できませんでした: %s %s", tid, e)
        return n_rep


def _redo_real(job, spec, wav, start):
    """run_redo の本物の認識の準備(エンジンを確かめてモデルと音声を読む)→ 行ごとに呼ぶ関数 f(sub, a, b) -> 行"""
    worker_client.check_engine(spec)
    job["state"] = "loading"
    model, device = worker_client.load_model(spec["model"], job, spec["device"], engine=tx_engines.engine_of(spec))
    job["device"] = device
    audio = worker_client.read_wav_f32(wav)
    kw = worker_client.filter_kwargs(model, redo_kwargs(spec))
    return lambda sub, a, b: recognize.range_lines_real(job, model, kw, audio, sub, start)


def _redo_finish(raw, sub, shift):
    """疑わしい所の認識し直しの行の整え方(疑似の差し込み口が使う。文字を比べるだけなので続いている行をつながない)"""
    return recognize.finish_range_lines(raw, sub, shift, join=False)


def head_stripper(spec):
    """範囲・全体の再認識と疑わしい所の認識し直しで、行の頭の「名前:」を外す決まり(ed_fill の B。0.67.0)。recognize.finish_range_lines が使う
    (① の recognize は ed_fill を読まない。serve が recognize.set_head_stripper で登録する。RS2-7)。
    -> None(設定 stripNames が明示のオフ・評価用)か、split(文字) -> (本文, 外したときの印 FILL_SPK_NOTE か None)"""
    if spec.get("stripNames", True) is False or spec.get("evalSet"):
        return None
    names = ed_fill.fill_spk_names(spec)

    def split(text):
        text, head = ed_fill.fill_spk_split(text, names)
        return text, (ed_fill.FILL_SPK_NOTE if head else None)
    return split


def run_redo(job):
    """疑わしい所だけ認識し直す(12 ③-2)。行ごとに、前後の余白を足した範囲を今の範囲の再認識と同じ仕組みで認識し直し、良くなったものだけ最後にまとめて置き換える。
    中止したら何も置き換えない。時間の上限(REDO_MAX_SEC)を超えたら残りの行はやめる"""
    spec = job["spec"]
    with _heavy.job_temp_wav(job, "中止しました(何も置き換えていません)", "疑わしい所の認識し直しで例外") as wav:
        doc = ed_store.read_transcript(spec["tid"])
        src = _txenv.check_source(doc.get("sourcePath"))
        targets = redo_targets(doc, set(spec["ids"]))
        if not targets:
            job["segments"] = 0
            _heavy.job_done(job, spec["tid"], "完了(認識し直す行がありませんでした)")
            return
        start, end = recognize.audio_span([{"start": a, "end": b} for _g, a, b in targets], _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end")))
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        recognize.extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        recognize_row = _backend.select().redo_recognizer(job, spec, wav, start, _redo_real, _redo_finish)
        job["state"] = "running"
        t0, results, tried, timed_out = time.monotonic(), [], 0, False
        for n, (g, a, b) in enumerate(targets):
            _heavy.check_cancel(job)
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
        _heavy.check_cancel(job)
        n_rep = apply_redo(spec, results)
        job["segments"], job["unsure"] = n_rep, max(0, tried - n_rep)
        _heavy.job_done(job, spec["tid"], "完了(%d か所のうち %d か所を置き換えました%s)" % (tried, n_rep, "。時間の上限で残りはやめました" if timed_out else ""))


def run_retranscribe(job):
    spec = job["spec"]
    with _heavy.job_temp_wav(job) as wav:
        doc = ed_store.read_transcript(spec["tid"])
        src = _txenv.check_source(doc.get("sourcePath"))
        start, end = _yschemas.num_or(doc.get("start"), 0.0) or 0.0, _yschemas.num_or(doc.get("end"))
        by_id = {g["id"]: g for g in doc.get("segments") or []}
        targets = sorted((by_id[i] for i in spec["ids"] if i in by_id), key=lambda g: g["start"])
        whole = spec.get("mode") == "whole"
        if not targets and not whole:
            raise _errors.ApiError("empty", "再認識する行が見つかりません(先に削除された可能性があります)", 400)
        span_src = targets + ([{"start": spec["range"][0], "end": spec["range"][1]}] if spec.get("mode") in ("range", "whole") else [])
        start, end = recognize.audio_span(span_src, start, end)   # 以下の start は「取り出した音声の先頭が、元の動画の何秒か」
        job["state"], job["phase"] = "extracting", "音声を取り出し中"
        recognize.extract_audio(job, {"sourcePath": src, "start": start, "end": end, "boost": spec["boost"]}, wav)
        if spec.get("mode") in ("range", "whole"):
            return _retranscribe_range(job, spec, doc, wav, start, whole)
        results = _retranscribe_each(job, spec, targets, wav, start)
        _heavy.check_cancel(job)
        job["segments"], job["unsure"] = apply_retranscribe(spec, results)
        _heavy.job_done(job, spec["tid"])


def _retranscribe_range(job, spec, doc, wav, start, whole):
    """範囲・全体の再認識(run_retranscribe の続き。音声は取り出し済み。先頭 = 元の動画の start 秒)"""
    a, b = spec["range"]
    rec = recognize.RangeRecognizer(job, spec, wav, start)
    job["state"], job["phase"] = "running", "全体を認識中" if whole else "範囲を認識中"
    lines = recognize.whole_lines(job, spec, doc, rec) if whole else rec.main(a, b)
    _heavy.check_cancel(job)
    # 新しい認識でほぼ空だった所(元の行があった所 = 声があった所)だけ、声の検出なし・捨てる判定なしで認識し直す(4-2 の 3)
    gaps = [(max(a, g["start"] - LOOSE_PAD), min(b, g["end"] + LOOSE_PAD)) for g in plan_range(doc, spec, lines)["empty"]]
    loose = rec.loose(_yschemas.union_spans(gaps)) if gaps else []
    _heavy.check_cancel(job)
    if not lines and not loose:
        if whole:
            recognize.drop_resume(spec["tid"])   # 認識は終わった(続きから再開するものが無い)
        raise _errors.ApiError("no_speech", "この%sからは、文字が認識されませんでした(元の行はそのままです)" % ("動画" if whole else "範囲"), 400)
    r = apply_range(spec, lines, loose)
    if whole:
        recognize.drop_resume(spec["tid"])
    job["segments"], job["unsure"], job["kept"], job["emptyKept"], job["loose"] = r["lines"], r["unsure"], r["kept"], r["emptyKept"], r["loose"]
    note = recognize.vad_note(rec.vad)
    if note:
        job["vadNote"] = note
        _txbase.add_warning(job, note)
    _heavy.job_done(job, spec["tid"])


def _retranscribe_each(job, spec, targets, wav, start):
    """選んだ行を 1 行ずつ認識する(run_retranscribe の each。音声は取り出し済み)。-> {行の id: (文章, 要確認の理由)}"""
    return _backend.select().each_lines(job, spec, targets, wav, start, _each_real)


def _each_real(job, spec, targets, wav, start):
    """_retranscribe_each の本物の認識"""
    results = {}
    worker_client.check_engine(spec)
    job["state"] = "loading"
    cm = recognize.ChunkModel(job, spec["model"], spec["device"], spec, tx_engines.engine_of(spec))
    audio = worker_client.read_wav_f32(wav)
    job["state"], job["phase"] = "running", "再認識中"
    sep = "" if spec["language"] in ("ja", "zh", "ko") else " "
    terms = _roster.prompt_terms(spec)
    for n, t in enumerate(targets):
        _heavy.check_cancel(job)
        a, b = max(0.0, t["start"] - start - 0.3), t["end"] - start + 0.3   # 前後に少し余裕を持たせる(語頭・語尾が欠けにくい)
        r = cm.recognize(audio[int(a * 16000):int(b * 16000)], t, sep, terms, n == 0)
        if r:
            text, flag = r
            results[t["id"]] = (postproc.strip_punct(text) if spec.get("stripPunct", True) else text, flag)
        job["progress"] = min(0.99, (n + 1) / len(targets))
    return results


# ---------- 移した名前の転送(役割で組み直す RS2。2026-10-10。RS5 で消す) ----------
# 中身を pipeline/transcribe・human/proof・ytt/jobs へ移す間、ed_jobs.名前 の読み・書き・削除を移した先へ回す(ytt/modfwd.py)。
# ここに残っている名前が先。移した名前を from … import で読み直さない(serve の名前の受付と同じく、差し替えが別名に当たって本体に効かなくなる)。
_MOVED = (_heavy,)   # 移した先のモジュール(移すたびに足す。serve.py の _ED_MODULES にも ed_jobs より前に足す)。ytt/jobs = ジョブの表・待機列・ワーカー・取り消し(RS2-1b)
_MOVED += (_roster, tx_engines)   # 名簿の prompt_terms・エンジンの engine_of・engine_home・ENGINE_DIR(RS2-4a)
_MOVED += (postproc,)   # 行の後処理と要確認の印(RS2-4b。END_TRIM・JOIN_GAP・expand_segments の差し替えもここへ届く)
_MOVED += (records,)   # 認識の記録・辞書の版・生出力・単語の時刻(RS2-5。dict_version の差し替えもここへ届く)
_MOVED += (worker_client,)   # 認識ワーカー・モデル・エンジンの確かめ・wav の形(RS2-6。IN_WORKER・WORKER_*・load_model・check_engine の差し替えもここへ届く)
_MOVED += (recognize,)   # 音声の取り出し・認識・範囲の行・全体の再認識の続きから(RS2-7。extract_audio・WHOLE_PART_SEC・RangeRecognizer.main の差し替えもここへ届く)
_moved_owner = _modfwd.install(globals(), _MOVED, "ed_jobs")


def _add_moved(mod):
    """ed_jobs が読まない層の持ち主(④ の疑似 eval/fake/fake_asr の transcribe_fake・_fake_spans)を転送に足す。呼ぶのは app(serve)だけ
    (ed_jobs から eval を import しない = 層の向きを守る。RS2-2)"""
    global _MOVED, _moved_owner
    if mod not in _MOVED:
        _MOVED += (mod,)
        _moved_owner = _modfwd.install(globals(), _MOVED, "ed_jobs")
