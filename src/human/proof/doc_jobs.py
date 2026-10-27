# -*- coding: utf-8 -*-
"""③ 人の操作の層 human/proof: 文字起こしのジョブの本体(run_job)と書く先の決め方・受付(validate_job と
疑わしい行の選び方 redo_targets)・字幕の文字数の設定・人の直しの引き継ぎ carry_overrides(layers.carry)・新しい行の id。
再認識(each・range・whole)の受付 validate_retranscribe・ジョブの本体・文書への反映・再認識の記録は隣の rerun.py(rerun → doc_jobs の一方向 =
ここは rerun を読まない。例外は評価用の作り直しの書き込み rerun.rebuild_whole を呼ぶときだけ読む)。ジョブの表と器は ② flow/jobs・flow/wire(本体は入口 editor/serve.py が渡す)。
ほかの部品の名前は `store.名前`・`_flowtx.名前` の形で呼ぶたびに読む(差し替えが効くように。from … import はしない)。
⑤ eval/drill/evalbatch は読まない(評価用の作り直しの書き込みは rerun.rebuild_whole = X-RERUN。評価用のフォルダの判定は ytt/settings を直に)。2つ目のエンジンの候補 alt・学習 learn・話者 speakers・文書の置き場 store は隣。
③ は ① pipeline/transcribe を直に読まない: 文字起こしの機械の分(取り出し → 認識 → 後処理 fill・llm → 文書の行 = ① clipjob)と
文書の機械の分 fields・記録の書き込み・置換辞書の組 dict_pairs・モデルとエンジンの確かめ・配信ごとの文脈は ② の `flow/tx`(`_flowtx.名前`)、
句読点・印の文・用語の区切りは ytt/txtext、置換辞書の読み方と当て方は ytt/dictfmt。
"""
import os
import uuid

from ytt import errors as _errors, schemas as _yschemas  # noqa: E402
from flow import jobs as _heavy  # noqa: E402
from ytt import settings as _settings  # noqa: E402   編集の設定の読み書き load_settings・評価用のフォルダの判定
from ytt import txbase as _txbase  # noqa: E402   ロガー・決まった値・印の文・ジョブの注意 add_warning
from ytt import txtext as _txtext  # noqa: E402   印の文 SPARSE_FLAG・用語の区切り split_terms・行を分ける文字数の既定 SPLIT_CHARS
from ytt import tools as _tools  # noqa: E402   元のファイルの検査と長さ(check_source・media_duration)
from flow import machine as _machine  # noqa: E402   この PC の設定(llmModel の検査。要求にあれば spec に通す)
from flow import placement as _placement  # noqa: E402   新しい文書の置き場所 doc_home
from flow import tx as _flowtx  # noqa: E402  ② 文字起こしの動詞(transcribe_clip・write_clip_records・dict_pairs・check_model・request_engine)
from . import alt  # noqa: E402   2つ目のエンジンの候補(run_job の autoAlt。呼ぶたびに alt.名前 で読む)
from . import learn  # noqa: E402   学習・提案・確度「高」の自動置換の選び方・用語の自動追加(呼ぶたびに learn.名前 で読む)
from . import store  # noqa: E402   文書の読み書き・行の無い文書へ入れる fill_doc(呼ぶたびに store.名前 で読む)
from . import layers as _layers  # noqa: E402   機械の層・人の層(人の行を新しい文書へ引き継ぐ carry)
from . import speakers  # noqa: E402   話者の自動判別 autodiar_after_transcribe(呼ぶたびに speakers.名前 で読む)

# 評価用のフォルダの判定(eval_name_guard・in_eval_dir)は ytt/settings を直に呼ぶたびに読む


# ---------- 学習データの読み手(入口が machine の learningDir があるときだけ set_learning で入れる。notes:docs/spec/friend.md の 10) ----------
# 入れた物(② flow/learning.Learning の形: glossary(terms)・learned()・dict_learned())があれば、用語の自動追加・確度「高」の学習済み置換・
# 辞書の版の learned をそこから読む(学習の束なら計算済みの規則 = 文書を読まない)。None(既定)= 今まで通り隣の learn から
_learning = [None]


def set_learning(learning):
    """学習データの読み手を入れる(None で外す)。入口(app)が起動のときに 1 回"""
    _learning[0] = learning


def glossary_of(req, st=None):
    """要求の用語集(200 語まで)と、自動で足す語(autoGloss。よく直される正しい語)-> (用語集, 自動の語)。st = 読んである設定"""
    glossary = _txtext.split_terms(req.get("glossary"))[:200]
    if req.get("autoGloss") is False:
        return glossary, []
    lr = _learning[0]
    return glossary, (list(lr.glossary(glossary)) if lr is not None else learn.auto_glossary(glossary, settings=st))


def _llm_model_of(req):
    """要求の llmModel(合う名前だけ。無い・合わない = None)"""
    try:
        return _machine.check("llmModel", req.get("llmModel"))
    except ValueError:
        return None


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
    st = _settings.load_settings()   # 保存した設定は 1 回だけ読む(自動の用語・下の 4 つの auto・行を分ける文字数・用語集)
    if "glossary" not in req:   # 要求に用語集が無い(② のまとめて実行。用語集は束の外 = 学習データ): 保存した設定の用語集
        req = dict(req, glossary=st.get("glossary") if isinstance(st.get("glossary"), str) else None)   # (編集の画面から始めるときに送る値と同じ)
    glossary, gauto = glossary_of(req, st)
    ev = req.get("evalSet") is True   # 評価用として文字起こしする: 用語集・呼び名・置換辞書・学習した置換を使わない(git:679ff01:docs/archive/project/eval-set-procedure.md の 2)
    into = None
    if req.get("intoDoc") not in (None, ""):
        # 文字起こしの無い文書(② の全自動・⑤ の評価用のまとめてが指す)に行を入れる。id・題名・作った日・clip・編集の内容はそのまま
        into = str(req.get("intoDoc"))
        target = store.read_transcript(into)
        if os.path.normcase(os.path.abspath(str(target.get("sourcePath") or ""))) != os.path.normcase(src):
            raise _errors.ApiError("bad_request", "文字起こしを入れる文書の動画と、選んだ動画が違います", 400)
        if store.doc_has_rows(target):
            raise _errors.ApiError("not_empty", "この文書にはもう行があります(新しい文字起こしとして作ってください)", 409)
        if not str(req.get("title") or "").strip():
            req = dict(req, title=target.get("title") or "")
        ev = ev or target.get("evalSet") is True
    _settings.eval_name_guard(src, ev)   # 評価用のフォルダの設定が消えているのに「評価用」のフォルダの動画なら止める(学習用に混ざらないように。資料の git:before-1028-cleanup:plan/line-bc-master-plan.md の Q0)
    ev = ev or _settings.in_eval_dir(src)   # 評価用のフォルダの動画は、画面のチェックが無くても評価用
    if ev:
        glossary, gauto = [], []
    # 指定の本体は ② flow/tx の tx_spec(動画 1 本を頭から終わりまで・CLI の transcribe_start と同じ形。切り抜きの .clip.json の読み・モデルとエンジンの確かめ・
    # 配信ごとの文脈もそこ)。下は ③ が重ねる分: 範囲・入れる文書・評価用・2 つ目のエンジン・話者の細切れ・LLM のモデル・設定の読み方 pref・旧い vad
    def pref(key, default_on=False):
        """要求の真偽値があればそれ、無ければ(まとめて実行・古い画面)保存した設定。default_on = 設定に無いときもオン(明示の false だけオフ)"""
        if isinstance(req.get(key), bool):
            return req[key]
        return st.get(key) is not False if default_on else st.get(key) is True
    post = {"splitChars": split_chars_for(req, st),
            # 認識のあとの後処理(fill の A・C・D。既定オン)。要求に無ければ保存した設定 autoFill(明示の false だけオフ)。評価用には当てない
            "autoFill": pref("autoFill", default_on=True) and not ev,
            # LLM の後処理(llm。名簿の呼び名の聞き違いらしい所だけ。既定オン = decisions 3-17)。評価用には当てない
            "autoLlm": pref("autoLlm", default_on=True) and not ev,
            # 行の頭の話者名(「名前:」)を外す(fill の B。既定オン)。評価用には当てない
            "stripNames": pref("stripNames", default_on=True) and not ev,
            "autoLearned": req.get("autoLearned") is True and not ev, "autoContext": req.get("autoContext") is True and not ev,
            "learning": {"version": str(req.get("learningVersion") or "")[:80]}}
    spec = _flowtx.tx_spec(req, post, src=src, dur=dur)
    spec.update({"start": round(start, 2), "end": round(end, 2) if end else None, "intoDoc": into, "whole": whole,
                 "vadMode": spec["vadMode"] if req.get("vadMode") in ("weak", "normal", "off") or req.get("vad") is not False else "off",   # 旧い画面の vad: false は「なし」
                 "autoDict": spec["autoDict"] and not ev,
                 # 終わったら 2つ目のエンジンでも聞く(D1-b)。要求に無ければ(まとめて実行・古い画面)保存した設定 autoAlt
                 "autoAlt": pref("autoAlt") and not ev,
                 # 自動の判別の「細切れをならす」(diarSmooth。既定オフ)。要求に無ければ None = 保存した設定(speakers.autodiar_enqueue)
                 "diarSmooth": req["diarSmooth"] if isinstance(req.get("diarSmooth"), bool) else None,
                 "glossary": glossary + gauto, "glossAuto": gauto, "evalSet": ev,
                 "llmModel": _llm_model_of(req)})   # LLM の後処理のモデル(要求にあれば。無ければ ② が machine.json の値を入れる = flow/tx)
    return spec


NO_RETRY = ("extract_failed", "bad_range", "too_long", "bad_model", "bad_engine", "bad_ext", "not_found", "no_speech")   # 同じ指定ではまた失敗する理由(2 周目 N2)


def public_job(j):
    out = {k: j[k] for k in ("id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt")}
    out["errorDetail"] = j.get("errorDetail") or ""   # 失敗の原文・内部の名前(画面は「詳しく」の中だけ。M9・S12)
    out["internal"] = bool(j.get("internal"))   # 想定外の失敗(画面は「途中で止まりました」の決まった文)
    out["canRetry"] = _heavy.can_retry(j)   # 画面の [やり直す](同じ指定でもう一度)
    sp = j.get("spec") or {}
    out["warnings"] = list(sp.get("warnings") or [])   # 例: 隣の .clip.json が壊れている・別の版(文字起こしは続ける)
    out["hasClip"] = bool(sp.get("clip"))
    out["into"] = sp.get("intoDoc") or None   # 「編集」: 文字起こしの無い文書に入れる文字起こし(画面の行 0 の文書の「もう一度文字起こしする」・② の全自動・⑤ の評価用のまとめて)
    out["named"] = list(j.get("named") or [])       # A-3: 話者判別のあと、覚えている声で名前を付けた話者 [{"speaker", "name", "score"}]
    out["learned"] = list(j.get("learned") or [])   # A-3: 声を覚えた人の名前
    out["auto"] = bool(sp.get("auto"))   # 文字起こしのあとの自動の話者判別
    out["autoSkipped"] = j.get("autoSkipped") or ""   # 自動の判別を動き出すときにやめた理由(has_speakers・reviewed・empty)
    out["redo"] = bool(sp.get("evalRedo"))   # 未確認の評価用の作り直し(eval/drill/evalbatch)
    out["redoOne"] = bool((sp.get("evalRedo") or {}).get("one"))   # 1 本ずつの作り直し(画面が押した。終わるまで編集を止める)
    out["redoSkipped"] = j.get("redoSkipped") or ""            # 手が入っていたので作り直さなかった理由
    if j.get("voiceError"):
        out["warnings"].append(j["voiceError"])
    out["warnings"] += [w for w in (j.get("warnings") or []) if w not in out["warnings"]]   # ジョブの中で足した注意
    out["vadNote"] = j.get("vadNote") or ""          # 声の検出を緩めてやり直した(4-2)
    out["normNote"] = j.get("normNote") or ""        # 30fps にそろえた・そろえられなかった理由(Q1。flow/normalize の run_job)
    out["normOk"] = bool(j.get("normOk"))
    out["kept"], out["emptyKept"], out["loose"] = j.get("kept", 0), j.get("emptyKept", 0), j.get("loose", 0)   # 範囲・全体の再認識で残した行(3-4)
    return out


# 字幕の文字数(資料の git:before-1028-cleanup:docs/design/edit-tool-design.md の 12 ②。ユーザー決定: 縦 16・横 28、パックの字幕は2段 = 縦 8・横 14 文字前後で改行)。設定の "subtitle" に保存する
SUBTITLE_DEFAULT = {"orientation": "vertical", "maxChars": {"vertical": 16, "horizontal": 28}, "wrapChars": {"vertical": 8, "horizontal": 14},
                    "splitChars": _txtext.SPLIT_CHARS}   # splitChars = 文字起こしの行を分ける文字数(maxChars とは別。既定 24。画面の欄はまだ無い = settings.json か環境変数 TRANSCRIBE_SPLIT_CHARS)
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


def split_chars_for(req=None, st=None):
    """行を分けるときの最大文字数。優先の順: 要求の splitChars(4〜80)→ 環境変数 TRANSCRIBE_SPLIT_CHARS(8〜80)→ 設定の subtitle.splitChars(8〜80。既定 24)。
    編集の画面の文字起こしの要求は splitChars を付けない(app-rows.js の subtitleReq)= 環境変数・設定が効く。② のまとめて実行は束の値
    (flow/spec.TX_POST_KEYS。8〜80)を要求に付けるので、そちらがいつも勝つ(環境変数・設定は効かない)。
    字幕の向きの最大文字数(縦 16)では分けない = 区切りを意識した校正で 73% が戻された(notes:plan/done/line-b-row-split.md の 8)"""
    req = req or {}
    n = _chars_in(req.get("splitChars"), 4, 80)
    if n is not None:
        return n
    env = os.environ.get("TRANSCRIBE_SPLIT_CHARS", "").strip()
    if env.isdigit() and 8 <= int(env) <= 80:
        return int(env)
    return subtitle_settings(st)["splitChars"]


# 置換辞書の組 dict_pairs(設定の辞書 + 名簿の表記ゆれ)は ② flow/tx(学習データを読む = ② の責任。③ は _flowtx.dict_pairs)


def learned_finder(lrules, lfb):
    """① clipjob に渡す確度「高」の学習済み置換の選び方 find(文字) -> [{"i", "wrong", "right"}](規則が無ければ None = 当てない)。
    規則と確度を決めるのは ③ の learn(find_suggestions の only_high)、当てるのは ① replace.auto_learned_replace"""
    if not lrules:
        return None

    def find(text):
        return learn.find_suggestions(text, lrules, lfb, only_high=True)
    return find


def dict_learned():
    """辞書の版(records.dict_version)の learned の元の文字: 学習済みの置換の規則と採用・却下の記録(別のエンジン alt の数は除く)。
    学習(learn)を読むのは文書の側のここだけ(① の records は learn を読まない。serve が records.set_dict_inputs で登録する)。
    学習データの読み手(set_learning)があればそこから"""
    lr = _learning[0]
    return lr.dict_learned() if lr is not None else learn.dict_learned_text()


def _fresh_id(used, make, n=0):
    """行の新しい id: make(n+1), make(n+2), … のうち used に無い最初のもの(used に足す)。-> (id, その番号)"""
    while True:
        n += 1
        sid = make(n)
        if sid not in used:
            used.add(sid)
            return sid, n


def carry_overrides(job, spec, doc):
    """新しく作る文書 doc に、同じ動画の既存の文書(store.find_doc_for_media = 行のある・新しいもの)の人の行を重ねる(notes:plan/done/role-restructure.md の 5-5 の F-3)。
    force の再文字起こし・エンジンを変えた再実行などで人の直しが消えないように。評価用(作る側・元の側)と評価用の作り直しには当てない。
    環境変数 TRANSCRIBE_CARRY_OVERRIDES=off で止める(前の文書はそのまま残る = 引き継がなくても直しは失わない)。
    重ね方は層の組み立て(layers.carry。前の文書の機械の層 = store.layers_for = 層の無い古い文書は文書の original から作る)。
    横に古い控え <id>.over.json があっても読まない(保存のたびに文書から取り出した写しで、文書より多くを持たない)。
    doc の segments・speakers を書き換え、recognition.runs[-1] に override = 数の辞書を入れる
    -> layers.carry の数の辞書 {"matched", "stale", "total", …, "from": 元の文書の id} か None(重ねなかった)"""
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
    prev_mach, _hum = store.layers_for(hit["id"], prev)
    new_mach = _yschemas.make_mach(doc.get("segments"), speakers=doc.get("speakers"))
    rows, spk, stats = _layers.carry(prev, prev_mach, new_mach, (spec.get("start") or 0.0, spec.get("end")), doc.get("speakers"))
    if not stats["total"]:
        return None
    stats["from"] = hit["id"]
    doc["segments"] = rows
    if "speakers" in doc or spk:
        doc["speakers"] = spk
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
    """文字起こし(kind transcribe)のジョブの本体。ほかの種類は登録した本体へ回す(② flow/jobs の JOB_RUNNERS。テストが doc_jobs.run_job で直に動かす)。
    走っている間に指定 spec の warnings へ足された注意(② の声の検出のやり直し・入れる文書が変わっていた)は、終わったら(失敗でも)job の warnings へ移す
    = spec は受付のときの指定のまま([やり直す] の retry_job が前の回の注意を引き継がない。画面の見え方は public_job が両方を合わせるので同じ)"""
    kind = job.get("kind")
    if kind not in (None, "transcribe"):
        return _heavy.JOB_RUNNERS[kind](job)
    run_transcribe_job(job)


def run_transcribe_job(job):
    """文字起こし 1 本のジョブの本体(run_job の続き。校正の全体の再認識 = kind retranscribe の spec redo も rerun.run_retranscribe からここを通る)"""
    spec = job["spec"]
    at_accept = len(spec.get("warnings") or [])   # 受付の注意(隣の .clip.json が壊れているなど)の数
    try:
        _run_transcribe(job, spec)
    finally:
        added = list(spec.get("warnings") or [])[at_accept:]
        if added:
            spec["warnings"] = list(spec["warnings"][:at_accept])
            for w in added:
                if w not in (job.get("warnings") or []):
                    _txbase.add_warning(job, w)


def _run_transcribe(job, spec):
    """run_job の中身(文字起こし 1 本)"""
    with _heavy.job_temp_wav(job) as wav:
        # 置換辞書の組と学習した置換は認識の前に 1 回だけ読む
        pairs = _flowtx.dict_pairs(spec)
        lr = _learning[0]
        if lr is not None:   # 学習データの読み手(machine の learningDir)
            finder = lr.learned() if spec.get("autoLearned") else None
        else:
            lrules, lfb = (learn.learn_rules(), learn.load_feedback()) if spec.get("autoLearned") else ({}, None)
            finder = learned_finder(lrules, lfb)
        # 機械の分(② flow/tx.transcribe_clip → ① clipjob = 取り出し → 認識 → 後処理 B・A・C → 文書の行 → D → LLM の E。② が fields を組む)。
        # ここから下は ③ の分(文書の id・clip・評価用・入れる文書・評価用の作り直し・30fps・話者・続きのジョブ)
        clip = _flowtx.transcribe_clip(job, spec, wav, pairs, finder)
        fields = clip["fields"]
        if spec.get("evalRedo") or spec.get("redo"):
            # 全体の作り直し(X-RERUN = 全体 × いつものエンジン × 差し替え): 評価用の作り直し(evalRedo)と校正の全体の再認識(redo = rerun.validate_whole)。
            # 同じ文書の機械の層を入れ替え、人の層は残す。文書が消えた・動画が変わったら書かない(新しい文書も作らない)
            from . import rerun as _rerun   # rerun は doc_jobs を読む(向き: rerun → doc_jobs)。ここは呼ぶときだけ
            tid = _rerun.rebuild_whole(job, spec, fields, eval_set=bool(spec.get("evalRedo")))
            if tid is None:
                return
        else:
            tid = store.fill_doc(spec, fields) if spec.get("intoDoc") else None
        if tid is None:
            tid = uuid.uuid4().hex[:12]
            doc = _flowtx.new_doc(tid, fields, spec)   # 文書の頭(schema・id・題名・動画・作った日・clip・評価用の印)は ② と同じ形
            mach = _yschemas.make_mach(doc["segments"], speakers=doc.get("speakers"))   # 機械の層 = 引き継ぐ前の機械の行(引き継いだ人の行は人の層へ)
            carry_overrides(job, spec, doc)   # 同じ動画の文書があれば人の行を引き継ぐ(評価用には当てない)
            # 書き出し先の案件の動画なら、その 作業用 に置く(② flow/placement.doc_home。評価用・案件でなければ transcripts)
            store.commit(tid, doc, why="whole", mach=mach, folder=_placement.doc_home(spec["sourcePath"], eval_set=spec.get("evalSet") is True))
        _flowtx.write_clip_records(tid, clip, spec, keep_spans=job.get("keepSpans"))   # 単語の時刻・生出力・LLM の生の提案(② が文書の横に書く。書けなくても文書は残す)
        # 話者の自動判別(評価用だけ。決定 3-47 Q7)。「完了」にする前に足す = 判別の待ちの文書をドリルが開く間を作らない
        speakers.autodiar_after_transcribe(job, spec, tid)
        _heavy.job_done(job, tid)
        alt.alt_after_transcribe(job, spec, tid)   # 設定 autoAlt: 2つ目のエンジンでも聞いて、食い違う所に候補を出す(既定オフ・評価用は除く)


# ---------- 疑わしい行の選び方(redo_targets。呼び手は今は無い = あとで別の人が使う) ----------
REDO_PAD = 1.0          # 行の前後に足す余白(秒)。ただし隣の行にはかからない(隣の行を消さないため)
REDO_MAX_ROWS = 30      # 1回で認識し直す行の上限


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
            continue   # 機械の出力と違う(人・辞書が直した)。機械の出力が無い文書は見分けない
        a = max(float(g["start"]) - REDO_PAD, lo_doc, float(segs[k - 1]["end"]) if k else lo_doc)
        b = float(g["end"]) + REDO_PAD
        if k + 1 < len(segs):
            b = min(b, float(segs[k + 1]["start"]))
        if hi_doc:
            b = min(b, hi_doc)
        out.append((g, round(min(a, float(g["start"])), 3), round(max(b, float(g["end"])), 3)))
    return out[:REDO_MAX_ROWS]
