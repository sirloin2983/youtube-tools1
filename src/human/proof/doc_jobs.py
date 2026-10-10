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
ほかの部品の名前は `store.名前`・`_flowtx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
評価用のフォルダ(manage の relink・eval の folders)と評価用の作り直し(eval の evalbatch)は読まず、serve が set_hooks で登録する口を呼ぶたびに引く(RS2-8d)。
2つ目のエンジンの候補 alt・YouTube の字幕の候補 ytcap は隣(RS3-E6 に editor の ed_alt・ed_ytcap から)。学習は隣の learn(RS3-E5c に ed_learn から)。話者の部品は隣の speakers(RS2-9)・文書の置き場は隣の store(RS3-E5a)。
**役割で組み直す RS6 a-3(2026-10-10)から ③ は ① pipeline/transcribe を直に読まない**: 文字起こしの機械の分(取り出し → 認識 → 後処理 fill・llm → 文書の行 = ① clipjob)と
文書の機械の分 fields・記録の書き込み・置換辞書の組 dict_pairs・モデルとエンジンの確かめ・配信ごとの文脈は ② の `flow/tx`(`_flowtx.名前`)、
行を分ける・句読点・印の文・用語の区切りは ytt/txtext、置換辞書の読み方と当て方は ytt/dictfmt。範囲・全体の再認識の行の頭の「名前:」を外す決まり head_stripper は ① fill.fill_head_stripper へ。
単語の時刻の読み read_words は ytt/txwords(RS6 a-5b)。
"""
import bisect
import json
import os
import time
import uuid

from ytt import errors as _errors, schemas as _yschemas  # noqa: E402
from flow import jobs as _heavy  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定の読み書き load_settings(RS3-1 に ed_learn から ytt/settings へ)
from ytt import txbase as _txbase  # noqa: E402   ロガー・決まった値・印の文(RS2-1a。ed_state から移した)
from ytt import txtext as _txtext  # noqa: E402   行を分ける split_segment・句読点 strip_punct・印の文 SPARSE_FLAG・用語の区切り split_terms(RS6 a-3 に ① の postproc・roster から)
from ytt import tools as _tools  # noqa: E402   元のファイルの検査と長さ(check_source・media_duration。RS3-0A まで txenv の口)
from ytt import txwords  # noqa: E402   単語の時刻 read_words(RS6 a-5b に ① records から ytt へ)
from flow import tx as _flowtx  # noqa: E402   ② 文字起こしの動詞(transcribe_clip・write_clip_records・dict_pairs・check_model・request_engine。RS6 a-3)
from . import alt, ytcap  # noqa: E402   2つ目のエンジンの候補(run_job の autoAlt)・YouTube の字幕の候補(run_job の autoYtcap)(RS3-E6 に editor/ed_alt・ed_ytcap から隣へ。呼ぶたびに alt.名前・ytcap.名前 で読む)
from . import learn  # noqa: E402   学習・提案・確度「高」の自動置換・用語の自動追加(RS3-E5c に editor/ed_learn から隣へ。呼ぶたびに learn.名前 で読む)
from . import store  # noqa: E402   文書の読み書き・保存のロック・控え(RS3-E5a に editor/ed_store から隣へ。呼ぶたびに store.名前 で読む)
from . import overrides as _overrides  # noqa: E402   校正の上書き(人の行を新しい文書へ引き継ぐ・<id>.over.json。RS6 b-O1)
from . import speakers  # noqa: E402   話者の自動判別 autodiar_after_transcribe(RS2-9 に editor/ed_speakers から隣へ。呼ぶたびに speakers.名前 で読む)

# ---------- serve が登録する口(役割で組み直す RS2-8d。manage の relink・eval の evalbatch をここから読まない = ② から ③・④ を読まない) ----------
# 評価用のフォルダの判定(eval_name_guard・in_eval_dir)は RS3-1 から ytt/settings を直に呼ぶたびに読む(口は 5 → 3 本)
_HOOK_KEYS = ("redo_skip", "redo_fill", "norm_after")
_hooks = {}


def set_hooks(**hooks):
    """編集の serve.py が読み込みのときに登録する口(どれも関数。serve は呼ぶたびに持ち主のモジュールの属性を読む lambda を渡す = テストの差し替えが届く)。
    redo_skip(job) -> bool: 未確認の評価用の作り直しを動き出す直前に確かめ直し、手が入っていれば True = 認識しない(evalbatch.eb_redo_skip_at_start。run_job)
    redo_fill(job, spec, fields) -> 文書の id か None: 評価用の作り直しの書き込み(None = 書かなかった。evalbatch.eb_redo_fill。run_job)
    norm_after(job, spec, tid) -> None: 文字起こしのあとの 30fps の作り直しと付け替え(manage/cases/relink.py の norm_after_transcribe。run_job)
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
    glossary = _txtext.split_terms(req.get("glossary"))[:200]
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
    model = _flowtx.check_model(str(req.get("model") or "small").strip())
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
        target = store.read_transcript(into)
        if os.path.normcase(os.path.abspath(str(target.get("sourcePath") or ""))) != os.path.normcase(src):
            raise _errors.ApiError("bad_request", "文字起こしを入れる文書の動画と、選んだ動画が違います", 400)
        if store.doc_has_rows(target):
            raise _errors.ApiError("not_empty", "この文書にはもう行があります(新しい文字起こしとして作ってください)", 409)
        if not str(req.get("title") or "").strip():
            req = dict(req, title=target.get("title") or "")
        ev = ev or target.get("evalSet") is True
    _settings.eval_name_guard(src, ev)   # 評価用のフォルダの設定が消えているのに「評価用」のフォルダの動画なら止める(学習用に混ざらないように。master-plan Q0)
    ev = ev or _settings.in_eval_dir(src)   # 評価用のフォルダの動画は、画面のチェックが無くても評価用(2026-10-01)
    if ev:
        glossary, gauto = [], []
    title = str(req.get("title") or "")[:120] or os.path.splitext(os.path.basename(src))[0][:120]
    engine, ctx = _flowtx.request_engine(req, model, {"clip": clip, "title": title, "sourceName": os.path.basename(src), "sourcePath": src}, req.get("autoContext") is True and not ev)

    def pref(key, default_on=False):
        """要求の真偽値があればそれ、無ければ(まとめて実行・古い画面)保存した設定。default_on = 設定に無いときもオン(明示の false だけオフ)"""
        if isinstance(req.get(key), bool):
            return req[key]
        return st.get(key) is not False if default_on else st.get(key) is True
    return {"sourcePath": src, "sourceName": os.path.basename(src), "start": round(start, 2), "end": round(end, 2) if end else None, "intoDoc": into,
            "duration": dur, "whole": whole, "model": model, "engine": engine, "language": lang, "beam": 1 if req.get("quality") == "fast" else 5,
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
    out["redo"] = bool(sp.get("evalRedo"))   # 未確認の評価用の作り直し(eval/drill/evalbatch)
    out["redoOne"] = bool((sp.get("evalRedo") or {}).get("one"))   # 1 本ずつの作り直し(画面が押した。終わるまで編集を止める)
    out["redoSkipped"] = j.get("redoSkipped") or ""            # 手が入っていたので作り直さなかった理由
    if j.get("voiceError"):
        out["warnings"].append(j["voiceError"])
    out["warnings"] += [w for w in (j.get("warnings") or []) if w not in out["warnings"]]   # ジョブの中で足した注意(以前は画面に届いていなかった)
    out["vadNote"] = j.get("vadNote") or ""          # 声の検出を緩めてやり直した(4-2)
    out["normNote"] = j.get("normNote") or ""        # 30fps にそろえた・そろえられなかった理由(Q1。manage/cases/relink.py の norm_run)
    out["normOk"] = bool(j.get("normOk"))
    out["kept"], out["emptyKept"], out["loose"] = j.get("kept", 0), j.get("emptyKept", 0), j.get("loose", 0)   # 全体の再認識で残した行(3-4)
    return out


# 字幕の文字数(12 ②。ユーザー決定 2026-09-26: 縦 16・横 28、パックの字幕は2段 = 縦 8・横 14 文字前後で改行)。設定の "subtitle" に保存する
SUBTITLE_DEFAULT = {"orientation": "vertical", "maxChars": {"vertical": 16, "horizontal": 28}, "wrapChars": {"vertical": 8, "horizontal": 14},
                    "splitChars": _txtext.SPLIT_CHARS}   # splitChars = 文字起こしの行を分ける文字数(0.59.5 から maxChars とは別。既定 24 = 0.59.6。画面の欄はまだ無い = settings.json か環境変数 TRANSCRIBE_SPLIT_CHARS)
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


# 置換辞書の組 dict_pairs(設定の辞書 + 名簿の表記ゆれ)は RS6 a-3 に ② flow/tx へ(学習データを読む = ② の責任。③ は _flowtx.dict_pairs)


def learned_finder(lrules, lfb):
    """① clipjob に渡す確度「高」の学習済み置換の選び方 find(文字) -> [{"i", "wrong", "right"}](規則が無ければ None = 当てない)。
    規則と確度を決めるのは ③ の learn(find_suggestions の only_high)、当てるのは ① replace.auto_learned_replace(RS6 a-3)"""
    if not lrules:
        return None

    def find(text):
        return learn.find_suggestions(text, lrules, lfb, only_high=True)
    return find


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
    with store._save_lock:
        doc = store.read_transcript(tid)
        base = obj.get("baseUpdatedAt")
        if isinstance(base, int) and not isinstance(base, bool) and base != int(doc.get("updatedAt") or 0):
            raise _errors.ApiError("conflict", "別の画面で先に保存されています。読み直してから、もう一度押してください", 409)
        words = txwords.read_words(tid)
        if not words:
            raise _errors.ApiError("no_words", "この文字起こしには単語の時刻がありません(v0.17.0 より前の文字起こし・単語の時刻を使わない設定)。"
                                       "行を選んで「範囲を再認識」すると、その範囲の単語の時刻を取り直せます", 400)
        mids = [(w[0] + w[1]) / 2 for w in words]
        segs = [g for g in doc.get("segments") or [] if isinstance(g, dict)]
        used = {str(g.get("id")) for g in segs}
        out, changed, added, skipped = [], 0, 0, 0
        for g in segs:
            text = str(g.get("text") or "")
            if g.get("proofed") is True or len(_txtext._squash(text)) <= max_chars + _txtext.SPLIT_SLACK:
                out.append(g)
                continue
            a, b = float(g.get("start") or 0), float(g.get("end") or 0)
            lo, hi = bisect.bisect_left(mids, a - 0.05), bisect.bisect_right(mids, b + 0.05)
            ws = [tuple(w) for w in words[lo:hi]]
            joined = "".join(t for _a, _b, t in ws)
            if ws and _txtext._squash(joined) == _txtext._squash(text):
                strip = False
            elif ws and _txtext._squash(_txtext.strip_punct(joined)) == _txtext._squash(text):
                strip = True        # 句読点を取り除いた行(stripPunct)
            else:
                skipped += 1        # 人が直した行・辞書で置き換えた行・単語の無い行は分けない
                out.append(g)
                continue
            parts = _txtext.split_segment({"start": a, "end": b, "text": joined, "words": ws}, max_chars)
            if len(parts) < 2:
                out.append(g)
                continue
            changed += 1
            added += len(parts) - 1
            for k, p in enumerate(parts):
                t = _txtext.strip_punct(p["text"]) if strip else p["text"]
                base = str(g.get("id"))
                sid = _fresh_id(used, lambda n: "%s-%d" % (base, n), k)[0] if k else base   # 2つめからは <元の id>-2, -3 …(ほかの行と重ならない番号)
                out.append(dict(g, id=sid, start=round(p["start"], 2), end=round(p["end"], 2), text=t[:_txbase.MAX_TEXT]))
        if not changed:
            return {"changed": 0, "added": 0, "skipped": skipped, "rows": len(segs), "updatedAt": int(doc.get("updatedAt") or 0)}
        store.snapshot(tid)   # 分ける前を「以前の版に戻す」に残す
        doc["segments"] = sorted(out, key=lambda g: (g["start"], g["end"]))
        doc["updatedAt"] = int(time.time() * 1000)
        doc["resplit"] = {"maxChars": max_chars, "rows": changed, "at": doc["updatedAt"]}
        store.apply_edit_cuts(tid, doc)
        store.write_doc(tid, doc)
        return {"changed": changed, "added": added, "skipped": skipped, "rows": len(doc["segments"]), "updatedAt": doc["updatedAt"]}


def carry_overrides(job, spec, doc):
    """新しく作る文書 doc に、同じ動画の既存の文書(store.find_doc_for_media = 行のある・新しいもの)の人の行(上書き)を重ねる(RS6 b-O1。F-3)。
    force の再文字起こし・エンジンを変えた再実行などで人の直しが消えないように。評価用(作る側・元の側)と評価用の作り直しには当てない。
    環境変数 TRANSCRIBE_CARRY_OVERRIDES=off で止める(前の文書はそのまま残る = 引き継がなくても直しは失わない)。
    doc の segments・speakers を書き換え、recognition.runs[-1] に override = 数(元の文書の id from)を入れる -> 数か None(重ねなかった)"""
    if spec.get("evalSet") or spec.get("evalRedo") or _txbase.env_off("TRANSCRIBE_CARRY_OVERRIDES"):   # 止めるスイッチ(困ったとき用)
        return None
    hit = store.find_doc_for_media(spec["sourcePath"])
    if not hit or not hit.get("rows"):
        return None
    try:
        prev = store.read_transcript(hit["id"])
    except _errors.ApiError:
        return None
    if prev.get("evalSet") is True:
        return None
    over = _overrides.current(hit["id"], prev)
    if not over.get("rows"):
        return None
    rows, stats = _overrides.apply(doc.get("segments") or [], over, (spec.get("start") or 0.0, spec.get("end")))
    if not stats["total"]:
        return None
    stats["from"] = hit["id"]
    doc["segments"] = rows
    doc["speakers"] = _overrides.merge_speakers(doc.get("speakers"), over, rows)
    runs = list((doc.get("recognition") or {}).get("runs") or [])
    if runs:
        runs[-1] = dict(runs[-1], override=stats)   # 写しに入れる(生出力 asr.json に書く記録は機械の分のまま)
        doc["recognition"] = dict(doc["recognition"], runs=runs)
    msg = "同じ動画の前の文字起こしから、人の直し %d 行を引き継ぎました" % stats["matched"]
    if stats["stale"]:
        msg += "(対応する行が無い %d 行は印「古い認識を元にした直し」を付けて残しました)" % stats["stale"]
    _txbase.add_warning(job, msg)
    return stats


def run_job(job):
    """文字起こし(kind transcribe)のジョブの本体。ほかの種類は登録した本体へ回す(ytt/jobs の JOB_RUNNERS。テストが doc_jobs.run_job で直に動かす)"""
    kind = job.get("kind")
    if kind not in (None, "transcribe"):
        return _heavy.JOB_RUNNERS[kind](job)
    spec = job["spec"]
    # 未確認の評価用の作り直し(eval/drill/evalbatch): 動き出す直前にもう一度「手つかず」を確かめる。手が入っていれば認識せずに「作り直しませんでした」
    if spec.get("evalRedo") and _hook("redo_skip")(job):
        return
    with _heavy.job_temp_wav(job) as wav:
        # 置換辞書の組と学習した置換は認識の前に 1 回だけ読む(F-8。RS2-8e までは音声の取り出しのあと・認識の行を読み始める前に読んでいた)
        pairs = _flowtx.dict_pairs(spec)
        lrules, lfb = (learn.learn_rules(), learn.load_feedback()) if spec.get("autoLearned") else ({}, None)
        # 機械の分(② flow/tx.transcribe_clip → ① clipjob = 取り出し → 認識 → 後処理 B・A・C → 文書の行 → D → LLM の E。② が fields を組む。RS6 a-3)。
        # ここから下は ③ の分(文書の id・clip・評価用・入れる文書・評価用の作り直し・30fps・話者・続きのジョブ)
        clip = _flowtx.transcribe_clip(job, spec, wav, pairs, learned_finder(lrules, lfb))
        fields = clip["fields"]
        if spec.get("evalRedo"):
            # 評価用の作り直し: 同じ文書の行・機械の出力を置き換える(評価用の再認識を断る決まりの、この道だけの例外。ユーザー承認 2026-10-04)。
            # 認識の間に手が入っていたら書かない(新しい文書も作らない)
            tid = _hook("redo_fill")(job, spec, fields)
            if tid is None:
                return
        else:
            tid = store.fill_doc(spec, fields) if spec.get("intoDoc") else None
        if tid is None:
            tid = uuid.uuid4().hex[:12]
            doc = dict({"schema": "transcribe/v1", "id": tid, "title": spec["title"], "sourcePath": spec["sourcePath"], "sourceName": spec["sourceName"]},
                       **fields, createdAt=fields["updatedAt"])
            if spec.get("clip"):
                doc["clip"] = spec["clip"]   # youtube-tools-clip/v1 の中身そのもの(transcript/v1 にもそのまま入る)
            if spec.get("evalSet"):
                doc["evalSet"] = True
            carried = carry_overrides(job, spec, doc)   # 同じ動画の文書があれば人の行を引き継ぐ(RS6 b-O1。評価用には当てない)
            store.write_doc(tid, doc)
            if carried:
                _overrides.save_after(tid, doc)
        _flowtx.write_clip_records(tid, clip, spec)   # 単語の時刻・生出力・LLM の生の提案(② が文書の横に書く。書けなくても文書は残す)
        # 30fps でなければ、同じジョブの続きで <名前>_30fps.mp4 を作って付け替える(Q1。SLOTS はこのジョブが持っている。
        # 文書はもう書いてあるので、失敗・取り消しでも元の動画のまま残る = 文字起こしの結果は失わない。評価用は作らない)
        _hook("norm_after")(job, spec, tid)
        # 話者の自動判別(評価用は常に・それ以外は設定 autoDiarize。v0.50.0)。「完了」にする前に足す = 判別の待ちの文書をドリルが開く間を作らない
        speakers.autodiar_after_transcribe(job, spec, tid)
        _heavy.job_done(job, tid)
        if spec.get("autoRedo") and any(_txtext.SPARSE_FLAG in g["flag"] for g in clip["segs"]):   # 疑わしい所を自動で認識し直す(設定。既定オフ。③-2)
            try:
                _heavy.add_job(redo_spec(tid, {"redoLarge": spec.get("redoLarge", True), "oldLp": clip["sparseLp"]}), "redo")
            except _errors.ApiError as e:
                _txbase.add_warning(job, "疑わしい所の認識し直しを始められませんでした: " + e.message)
        alt.alt_after_transcribe(job, spec, tid)   # 設定 autoAlt: 2つ目のエンジンでも聞いて、食い違う所に候補を出す(既定オフ・評価用は除く。D1-b)
        ytcap.ytcap_after_transcribe(job, spec, tid)   # 設定 autoYtcap: 元の配信の YouTube の字幕と比べて候補を出す(既定オフ・評価用と元の配信が分からない文書は黙って飛ばす。A1)


# ---------- 選んだ行の再認識 ----------
MAX_RANGE_SEC = 900


def validate_retranscribe(req):
    tid = str(req.get("tid") or "")
    doc = store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは再認識できません(機械の出力=比べる基準が書き換わるため)。評価用を外してから行ってください", 400)
    src = _tools.check_source(doc.get("sourcePath"))
    valid = {g["id"] for g in (doc.get("segments") or [])}
    ids = [i for i in dict.fromkeys(str(x)[:16] for x in (req.get("ids") or [])[:5000] if isinstance(x, (str, int))) if i in valid][:2000]
    mode = req.get("mode") if req.get("mode") in ("range", "whole") else "each"
    if not ids and mode != "whole":
        raise _errors.ApiError("empty", "再認識する行がありません", 400)
    model = _flowtx.check_model(str(req.get("model") or "large-v3").strip())
    lang = str(req.get("language") or doc.get("language") or "ja")
    st = _settings.load_settings()   # 自動の用語と行を分ける文字数で 1 回だけ読む
    glossary, gauto = glossary_of(req, st)
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
    engine, ctx = _flowtx.request_engine(req, model, doc, req.get("autoContext") is True)   # (RS6 a-3 までは文脈を読んだのは busy の確かめの前。文脈は読むだけ = 順は動きに出ない)
    return {"tid": tid, "ids": ids, "mode": mode, "range": rng, "model": model, "engine": engine, "language": lang if lang in _txbase.LANGS else "ja", "beam": 5,
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
        if (ids is not None and g["id"] not in ids) or _txtext.SPARSE_FLAG not in str(g.get("flag") or "") or g.get("proofed") is True:
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
    doc = store.read_transcript(tid)
    if doc.get("evalSet") is True:
        raise _errors.ApiError("eval_set", "評価用の文字起こしは認識し直せません(機械の出力=比べる基準が書き換わるため)", 400)
    _tools.check_source(doc.get("sourcePath"))
    targets = redo_targets(doc)
    if not targets:
        raise _errors.ApiError("empty", "認識し直す疑わしい行がありません(「長い区間に文字が少ない」の印があり、校正・手直ししていない行が対象です)", 400)
    model = _flowtx.check_model(str(doc.get("model") or "large-v3"), fallback="large-v3")
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
