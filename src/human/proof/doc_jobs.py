# -*- coding: utf-8 -*-
"""② 人の操作の層 human/proof: 文字起こしのジョブの本体(run_job)と文書づくり(行 → 文書の行・機械の出力・単語)・受付(validate_job・
validate_retranscribe・redo_spec と疑わしい行の選び方 redo_targets)・長い行の分け直し・字幕の文字数の設定・辞書の組・新しい行の id。
再認識(each・range・whole)と疑わしい所の認識し直しのジョブの本体・文書への反映・再認識の記録は隣の rerun.py(RS2-8c。rerun → doc_jobs の一方向 =
ここは rerun を読まない)。

役割で組み直す RS2-8b(2026-10-10)に編集の src/editor/ed_jobs.py から移した(中身は同じ。段10 で editor/serve.py から分けた部品。
git の履歴(679ff01 以前)の docs/plan/phase10-code-split.md)。認識そのもの(ワーカー・モデル・音声の取り出し・声の検出のやり直し・範囲の行・
記録・単語の時刻)は RS2-4〜7 に pipeline/transcribe へ、ジョブの表は ytt/jobs へ移してある。
旧い名前 ed_jobs.名前 は editor/ed_jobs.py(転送だけの殻。RS5 で消す)がここと移した先へ回す。名前は serve.py からも見える
(serve.py が受け付けて、この部品へ転送する。テストの S.名前 = … もここに入る)。
ほかの部品の名前は `ed_xxx.名前`・`postproc.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
評価用のフォルダ(manage の ed_relink)と評価用の作り直し(eval の ed_evalbatch)は読まず、serve が set_hooks で登録する口を呼ぶたびに引く(RS2-8d)。
editor の部品は裸の名前で読む(human の ed_store・ed_alt・ed_ytcap は層の向きが許す)。学習は隣の learn・置換辞書は pipeline/transcribe/replace(RS3-E5c に ed_learn から)。話者の部品は隣の speakers(RS2-9)。
後処理 fill・llm は RS2-9 から pipeline/transcribe の部品を `fill.名前`・`llm.名前` で呼ぶたびに読む(ed_fill・ed_llm の殻は無い)。
"""
import bisect
import json
import os
import time
import uuid

from ytt import errors as _errors, jobs as _heavy, schemas as _yschemas  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定の読み書き load_settings(RS3-1 に ed_learn から ytt/settings へ)
from pipeline.transcribe import roster as _roster  # noqa: E402,F401
from pipeline.transcribe import txbase as _txbase  # noqa: E402   ロガー・決まった値・印の文(RS2-1a。ed_state から移した)
from ytt import tools as _tools  # noqa: E402   元のファイルの検査と長さ(check_source・media_duration。RS3-0A まで txenv の口)
from pipeline.transcribe import postproc  # noqa: E402   行の後処理・要確認の印(RS2-4b。呼ぶたびに postproc.名前 で読む)
from pipeline.transcribe import records  # noqa: E402   認識の記録・生出力・単語の時刻(RS2-5。呼ぶたびに records.名前 で読む)
from pipeline.transcribe import worker_client  # noqa: E402   認識ワーカーとのやり取り・モデル・wav を読まずに渡す形(RS2-6。呼ぶたびに worker_client.名前 で読む)
from pipeline.transcribe import recognize  # noqa: E402   音声の取り出し・認識・範囲の行・全体の再認識の続きから(RS2-7。呼ぶたびに recognize.名前 で読む)
from pipeline.transcribe import fill  # noqa: E402   認識のあとの後処理 A・B・C・D(文字の少ない行を別の読みで埋める。10-08 の実験ループ。0.60.0。RS2-9 に ed_fill から移した)
from pipeline.transcribe import llm  # noqa: E402   LLM の後処理 E(名簿の呼び名の聞き違いらしい所だけ。P18。0.61.0。RS2-9 に ed_llm から移した)
from pipeline.transcribe import replace  # noqa: E402   置換辞書の読み方と当て方(RS3-E5c に ed_learn から。呼ぶたびに replace.名前 で読む)
import ed_alt  # noqa: E402,F401
import ed_ytcap  # noqa: E402,F401   YouTube の字幕の候補(run_job の ytcap・autoYtcap)
import ed_store  # noqa: E402,F401
from . import learn  # noqa: E402   学習・提案・確度「高」の自動置換・用語の自動追加(RS3-E5c に editor/ed_learn から隣へ。呼ぶたびに learn.名前 で読む)
from . import speakers  # noqa: E402   話者の自動判別 autodiar_after_transcribe(RS2-9 に editor/ed_speakers から隣へ。呼ぶたびに speakers.名前 で読む)

# ---------- serve が登録する口(役割で組み直す RS2-8d。manage の ed_relink・eval の ed_evalbatch をここから読まない = ② から ③・④ を読まない) ----------
# 評価用のフォルダの判定(eval_name_guard・in_eval_dir)は RS3-1 から ytt/settings を直に呼ぶたびに読む(口は 5 → 3 本)
_HOOK_KEYS = ("redo_skip", "redo_fill", "norm_after")
_hooks = {}


def set_hooks(**hooks):
    """編集の serve.py が読み込みのときに登録する口(どれも関数。serve は呼ぶたびに持ち主のモジュールの属性を読む lambda を渡す = テストの差し替えが届く)。
    redo_skip(job) -> bool: 未確認の評価用の作り直しを動き出す直前に確かめ直し、手が入っていれば True = 認識しない(ed_evalbatch.eb_redo_skip_at_start。run_job)
    redo_fill(job, spec, fields) -> 文書の id か None: 評価用の作り直しの書き込み(None = 書かなかった。ed_evalbatch.eb_redo_fill。run_job)
    norm_after(job, spec, tid) -> None: 文字起こしのあとの 30fps の作り直しと付け替え(ed_relink.norm_after_transcribe。run_job)
    知らない鍵・関数でない値は TypeError"""
    bad = sorted(k for k in hooks if k not in _HOOK_KEYS)
    if bad:
        raise TypeError("doc_jobs の口に知らない鍵: %s" % ", ".join(bad))
    for k, fn in hooks.items():
        if not callable(fn):
            raise TypeError("doc_jobs の口 %s は関数で渡す" % k)
    _hooks.update(hooks)


def check_hooks(names=_HOOK_KEYS):
    """names のうち登録されていない口があれば RuntimeError(serve が登録のあとで呼ぶ)"""
    missing = [k for k in names if k not in _hooks]
    if missing:
        raise RuntimeError("doc_jobs に登録されていない口: %s(編集の serve.py が読み込みのときに登録する)" % ", ".join(missing))


def _hook(name):
    """登録した口(呼ぶたびに引く)。登録されていなければ RuntimeError"""
    try:
        return _hooks[name]
    except KeyError:
        raise RuntimeError("doc_jobs の口 %s が登録されていません(編集の serve.py が読み込みのときに登録する)" % name) from None


def glossary_of(req, st=None):
    """要求の用語集(200 語まで)と、自動で足す語(autoGloss。よく直される正しい語)-> (用語集, 自動の語)。st = 読んである設定"""
    glossary = _roster.split_terms(req.get("glossary"))[:200]
    return glossary, (learn.auto_glossary(glossary, settings=st) if req.get("autoGloss") is not False else [])


def validate_job(req):
    src = _tools.check_source(req.get("sourcePath"))
    dur = _tools.media_duration(src)
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
    clip, clip_warn, _clip_path = _yschemas.find_clip(src, dur)   # (RS3-0A まで受け渡しの部品 pipeline_io を口から読んでいた)
    warnings = [clip_warn] if clip_warn else []
    model = str(req.get("model") or "small").strip()
    if not worker_client.valid_model(model):
        raise _errors.ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or "ja")
    if lang not in _txbase.LANGS:
        lang = "ja"
    st = _settings.load_settings()   # 保存した設定は 1 回だけ読む(自動の用語・下の 4 つの auto・行を分ける文字数)
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
    _settings.eval_name_guard(src, ev)   # 評価用のフォルダの設定が消えているのに「評価用」のフォルダの動画なら止める(学習用に混ざらないように。master-plan Q0)
    ev = ev or _settings.in_eval_dir(src)   # 評価用のフォルダの動画は、画面のチェックが無くても評価用(2026-10-01)
    if ev:
        glossary, gauto = [], []
    title = str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]
    ctx = _roster.stream_context({"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src}, req.get("autoContext") is True and not ev)

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
            # 認識のあとの後処理(fill の A・C・D。既定オン。0.60.0)。要求に無ければ保存した設定 autoFill(明示の false だけオフ)。評価用には当てない
            "autoFill": pref("autoFill", default_on=True) and not ev,
            # LLM の後処理(llm。名簿の呼び名の聞き違いらしい所だけ。既定オン = decisions 3-17。0.61.0)。評価用には当てない
            "autoLlm": pref("autoLlm", default_on=True) and not ev,
            # 行の頭の話者名(「名前:」)を外す(fill の B。既定オン。0.67.0)。評価用には当てない
            "stripNames": pref("stripNames", default_on=True) and not ev,
            # 終わったら話者を自動で判別する(v0.50.0)。要求に無ければ保存した設定 autoDiarize。評価用はこの値によらず常に(speakers.autodiar_after_transcribe)
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
    v = (st if st is not None else _settings.load_settings()).get("subtitle")
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
    pairs = replace.parse_replacements(_settings.load_settings().get("replacements"))
    try:
        pairs += _roster.variant_pairs(_roster.load(_roster.ROSTER))
    except (OSError, ValueError, TypeError, KeyError) as e:   # 名簿の表は補助なので、作れなくても認識は止めない
        _txbase.log.warning("名簿の表記ゆれの表を作れませんでした: %s", e)
    return pairs


def dict_learned():
    """辞書の版(records.dict_version)の learned の元の文字: 学習済みの置換の規則と採用・却下の記録(別のエンジン alt・YouTube の字幕 yt の数は除く)。
    学習(learn)を読むのは文書の側のここだけ(① の records は learn を読まない。serve が records.set_dict_inputs で登録する。RS2-5)"""
    rules = learn.learn_rules()
    return json.dumps({"rules": sorted([w, r, x["pos"], len(x["docs"])] for (w, r), x in rules.items()), "fb": {k: v for k, v in learn.load_feedback().items() if k not in ("alt", "yt")}},
                      ensure_ascii=False, sort_keys=True)


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


def run_job(job):
    """文字起こし(kind transcribe)のジョブの本体。ほかの種類は登録した本体へ回す(ytt/jobs の JOB_RUNNERS。テストが ed_jobs.run_job で直に動かす)"""
    kind = job.get("kind")
    if kind not in (None, "transcribe"):
        return _heavy.JOB_RUNNERS[kind](job)
    spec = job["spec"]
    # 未確認の評価用の作り直し(ed_evalbatch): 動き出す直前にもう一度「手つかず」を確かめる。手が入っていれば認識せずに「作り直しませんでした」
    if spec.get("evalRedo") and _hook("redo_skip")(job):
        return
    with _heavy.job_temp_wav(job) as wav:
        # 置換辞書の組と学習した置換は認識の前に 1 回だけ読む(F-8。RS2-8e までは音声の取り出しのあと・認識の行を読み始める前に読んでいた)
        pairs = dict_pairs(spec)
        lrules, lfb = (learn.learn_rules(), learn.load_feedback()) if spec.get("autoLearned") else ({}, None)
        # ① 音声を取り出して認識し、整えた行を受け取る(recognize.transcribe_rows。RS2-8e)。ここから下は文書への書き込み(② の文書づくり)
        res = recognize.transcribe_rows(job, spec, wav)
        rows, raw_asr, total, t_rec = res["rows"], res["raw"], res["total"], res["t_rec"]   # raw = 生出力(<id>.asr.json)・t_rec = 認識を始めた時刻(recognition.runs の wallSec)
        rows, names_n = fill.fill_strip_names(spec, rows)   # 行の頭の「名前:」を外す(設定 stripNames。0.67.0)
        # 認識のあとの後処理(設定 autoFill。0.60.0): 末尾の重複を捨て、文字の少ない行の窓を SenseVoice で読んで埋める(A・C)。読めなければ警告だけ
        rows, fill_rec, fill_read = fill.fill_after_rows(job, spec, rows, wav, total)
        _heavy.check_cancel(job)
        out = _rows_to_doc(job, spec, rows, pairs, lrules, lfb)
        if fill_read is not None:   # D: 別のエンジンも同じ呼び名なら 1 字違いを名簿の呼び名に(置換辞書のあと)
            fill_rec["agree"] = fill.fill_agree_doc(job, out["segs"], fill_read, total, spec)
        _heavy.check_cancel(job)
        # E: 名簿の呼び名の聞き違いらしい所だけを LLM で直す(設定 autoLlm。P18。選んだ所が無ければ LLM を読み込まない・失敗しても警告だけ)
        llm_rec, llm_items = llm.llm_after_doc(job, spec, out["segs"])
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
            tid = _hook("redo_fill")(job, spec, fields)
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
            llm.llm_write(tid, llm_rec, llm_items)   # LLM の生の提案・採否(<id>.llm.json。あとで「あり/なし」を測り直せる)
        # 30fps でなければ、同じジョブの続きで <名前>_30fps.mp4 を作って付け替える(Q1。SLOTS はこのジョブが持っている。
        # 文書はもう書いてあるので、失敗・取り消しでも元の動画のまま残る = 文字起こしの結果は失わない。評価用は作らない)
        _hook("norm_after")(job, spec, tid)
        # 話者の自動判別(評価用は常に・それ以外は設定 autoDiarize。v0.50.0)。「完了」にする前に足す = 判別の待ちの文書をドリルが開く間を作らない
        speakers.autodiar_after_transcribe(job, spec, tid)
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
        if isinstance(s.get("fill"), dict):   # 別の読みで埋めた行(fill の A): 印と元の文字を残す(画面の「別の読み」の札で戻せる)
            seg["fill"] = {"from": str(s["fill"].get("from") or "")[:_txbase.MAX_TEXT], "by": str(s["fill"].get("by") or "")[:20]}
            mark = fill.FILL_SPK_FLAG if seg["fill"]["by"] == fill.FILL_SPK_BY else fill.FILL_FLAG   # B は話者名を外した印
            seg["flag"] = "、".join(x for x in (mark, seg["flag"]) if x)[:100]
        prev.append(seg["text"])
        if postproc.SPARSE_FLAG in seg["flag"] and s.get("avg_logprob") is not None:
            sparse_lp[seg["id"]] = float(s["avg_logprob"])
        if lrules:   # 確度が高い学習済みの置換は、機械の出力側にも反映する(そうしないと自分の置換を「人が直した」と数えて自己強化してしまう)
            seg["text"], ln = learn.auto_learned_replace(seg["text"], lrules, lfb)
            learn_n += ln
        original.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], **postproc.machine_conf(s)})   # 機械の出力をそのまま残す(修正からの学習・精度の測定に使う)
        words.extend(postproc.row_words(s, spec["start"]))
        seg["text"], n = replace.apply_replacements(seg["text"], pairs)
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
MAX_RANGE_SEC = 900


def validate_retranscribe(req):
    tid = str(req.get("tid") or "")
    doc = ed_store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    src = _tools.check_source(doc.get("sourcePath"))
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    mode = req.get("mode") if req.get("mode") in ("range", "whole") else "each"
    if not ids and mode != "whole":
        raise _errors.ApiError("empty", "再認識する行がありません", 400)
    model = str(req.get("model") or "large-v3").strip()
    if not worker_client.valid_model(model):
        raise _errors.ApiError("bad_model", "モデル名が正しくありません", 400)
    lang = str(req.get("language") or doc.get("language") or "ja")
    st = _settings.load_settings()   # 自動の用語と行を分ける文字数で 1 回だけ読む
    glossary, gauto = glossary_of(req, st)
    ctx = _roster.stream_context(doc, req.get("autoContext") is True)
    if _heavy.tid_busy(tid, _heavy.EXCLUSIVE["retranscribe"]):
        raise _errors.ApiError("busy", "この文字起こしは、すでに別の処理(話者判別・再認識・声を覚える)の最中です", 409)
    rng = None
    segs = sorted((g for g in doc.get("segments") or []), key=lambda g: g["start"])
    if mode == "whole":   # 動画全体(文書の範囲全体)を範囲と同じやり方で認識し直す。校正済みの行は残す(docs/design/whole-retranscribe-design.md の 3)
        a = _yschemas.num_or(doc.get("start"), 0.0) or 0.0
        b = _yschemas.num_or(doc.get("end")) or _tools.media_duration(src) or max([g["end"] for g in segs] or [0.0])
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


# ---------- 疑わしい所だけ認識し直す(12 ③-2。ユーザー承認 2026-09-27: 設計どおり) ----------
REDO_PAD = 1.0          # 行の前後に足す余白(秒)。ただし隣の行にはかからない(隣の行を消さないため)
REDO_MAX_ROWS = 30      # 1回で認識し直す行の上限
# 認識し直しの本体と反映(run_redo・apply_redo・redo_better・REDO_MAX_SEC・REDO_BAD_FLAGS)は rerun.py(RS2-8c)。ここは受付と行の選び方


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
    _tools.check_source(doc.get("sourcePath"))
    targets = redo_targets(doc)
    if not targets:
        raise _errors.ApiError("empty", "認識し直す疑わしい行がありません(「長い区間に文字が少ない」の印があり、校正・手直ししていない行が対象です)", 400)
    model = str(doc.get("model") or "large-v3")
    if not worker_client.valid_model(model):
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


def head_stripper(spec):
    """範囲・全体の再認識と疑わしい所の認識し直しで、行の頭の「名前:」を外す決まり(fill の B。0.67.0)。recognize.finish_range_lines が使う
    (① の recognize は fill を読まない。serve が recognize.set_head_stripper で登録する。RS2-7)。
    -> None(設定 stripNames が明示のオフ・評価用)か、split(文字) -> (本文, 外したときの印 FILL_SPK_NOTE か None)"""
    if spec.get("stripNames", True) is False or spec.get("evalSet"):
        return None
    names = fill.fill_spk_names(spec)

    def split(text):
        text, head = fill.fill_spk_split(text, names)
        return text, (fill.FILL_SPK_NOTE if head else None)
    return split
