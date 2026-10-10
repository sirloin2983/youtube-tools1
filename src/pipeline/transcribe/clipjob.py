# -*- coding: utf-8 -*-
"""① 文字起こしのジョブの機械の文書の行を作る(make_doc_rows)。役割で組み直す RS6 a-3(2026-10-10)に human/proof/doc_jobs の run_job から切り出した(中身は同じ)。

流れ: 音声を取り出して認識し整えた行(recognize.transcribe_rows)→ 行の頭の「名前:」を外す(fill.fill_strip_names。B)→ 認識のあとの後処理(fill.fill_after_rows。A・C)→
文書の行(_rows_to_doc = 要確認の印・学習した置換・置換辞書・機械の出力 original・単語の時刻)→ 別のエンジンも同じ呼び名なら 1 字違いを直す(fill.fill_agree_doc。D)→
名簿の呼び名の聞き違いらしい所だけ LLM で直す(llm.llm_after_doc。E)。
① は ② ③ を読まない: 置換辞書の組 pairs と学習した置換の選び方 learned は呼ぶ側(② の flow/tx・③ の doc_jobs)が渡す。ファイルは書かない
(文書・words.json・asr.json・llm.json を書くのは ② の flow/tx と ③)。名前は呼ぶたびに `モジュール.名前` で読む(S.extract_audio などの差し替えが届く)。
名前は編集の serve の名前の受付(_ED_MODULES)に並ぶ(旧 ed_jobs の S._rows_to_doc はここ)。
"""
from ytt import dictfmt as _dictfmt, jobs as _heavy, txbase as _txbase, txtext as _txtext
from . import fill, llm, postproc, recognize, replace, roster as _roster


def make_doc_rows(job, spec, wav, pairs, learned=None):
    """文字起こしのジョブの機械の分(wav は呼ぶ側の一時ファイル。取り出しもここ)。pairs = 置換辞書の組 [(誤, 正)]・
    learned = 確度「高」の学習済み置換の選び方 find(文字) -> [{"i", "wrong", "right"}](autoLearned で規則があるときだけ。無ければ None)。
    -> {"segs", "original", "words", "dictApplied", "learnApplied", "sparseLp"(_rows_to_doc)・"raw"(生出力 asr.json の segments)・"total"(音声の長さ)・
        "t_rec"(認識を始めた time.monotonic())・"fill_rec"・"names_n"・"llm_rec"・"llm_items"}。取り消しは途中で Cancelled"""
    res = recognize.transcribe_rows(job, spec, wav)
    rows, total = res["rows"], res["total"]
    rows, names_n = fill.fill_strip_names(spec, rows)   # 行の頭の「名前:」を外す(設定 stripNames。0.67.0)
    # 認識のあとの後処理(設定 autoFill。0.60.0): 末尾の重複を捨て、文字の少ない行の窓を SenseVoice で読んで埋める(A・C)。読めなければ警告だけ
    rows, fill_rec, fill_read = fill.fill_after_rows(job, spec, rows, wav, total)
    _heavy.check_cancel(job)
    out = _rows_to_doc(job, spec, rows, pairs, learned)
    if fill_read is not None:   # D: 別のエンジンも同じ呼び名なら 1 字違いを名簿の呼び名に(置換辞書のあと)
        fill_rec["agree"] = fill.fill_agree_doc(job, out["segs"], fill_read, total, spec)
    _heavy.check_cancel(job)
    # E: 名簿の呼び名の聞き違いらしい所だけを LLM で直す(設定 autoLlm。P18。選んだ所が無ければ LLM を読み込まない・失敗しても警告だけ)
    llm_rec, llm_items = llm.llm_after_doc(job, spec, out["segs"])
    _heavy.check_cancel(job)
    return dict(out, raw=res["raw"], total=total, t_rec=res["t_rec"], fill_rec=fill_rec, names_n=names_n, llm_rec=llm_rec, llm_items=llm_items)


def _rows_to_doc(job, spec, rows, pairs, learned=None):
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
        if _txtext.SPARSE_FLAG in seg["flag"] and s.get("avg_logprob") is not None:
            sparse_lp[seg["id"]] = float(s["avg_logprob"])
        if learned is not None:   # 確度が高い学習済みの置換は、機械の出力側にも反映する(そうしないと自分の置換を「人が直した」と数えて自己強化してしまう)
            seg["text"], ln = replace.auto_learned_replace(seg["text"], learned)
            learn_n += ln
        original.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], **postproc.machine_conf(s)})   # 機械の出力をそのまま残す(修正からの学習・精度の測定に使う)
        words.extend(postproc.row_words(s, spec["start"]))
        seg["text"], n = _dictfmt.apply_replacements(seg["text"], pairs)
        dict_n += n
        segs.append(seg)
        job["segments"] = len(segs)
    return {"segs": segs, "original": original, "words": words, "dictApplied": dict_n, "learnApplied": learn_n, "sparseLp": sparse_lp}
