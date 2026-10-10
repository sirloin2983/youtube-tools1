# -*- coding: utf-8 -*-
"""② 人の操作の層 human/proof: 行の時刻の候補の API の包み(POST /api/retime)。2026-10-05。役割で組み直す RS3-E6(2026-10-10)に編集の src/editor/ed_retime.py から移した(中身は同じ)。
旧い名前 ed_retime.名前 は editor/ed_retime.py(転送だけの殻。RS5 で消す)が回す。

読む速さの印・時刻の候補の計算(subread_*・retime_raw・retime_candidates ほか)は役割で組み直す RS2-9(2026-10-10)に
src/pipeline/transcribe/retime.py(① の層)へ切り出した。ここに残るのは、保存済みの文書と transcripts/<id>.words.json(認識のときの単語。行を直しても古いまま)を
読んで計算に渡す包みだけ:
   POST /api/retime {id, rows: [行の id…]} -> {items: [{id, start, end, matched, dStart, dEnd, edges, from}], checked, updatedAt, reasonCode?, reason?}
   候補を出すだけ(文書を書き換えない。採るのは画面の 1 押し)。単語の時刻が無ければ reasonCode "no_words"。
   終わりの端を候補にしないエンジンは retime.RETIME_END_SKIP(今は空)。細かい決まり・根拠の数字は retime.py の先頭。
名前は serve.py からも見える(serve.py の _ED_MODULES。pipeline/transcribe の retime(計算)を、ここ(包み)より前に並べる)。ほかの部品と重ならないよう retime_ で始める。
**この包み(human/proof/retime)と計算(pipeline/transcribe/retime)は同じ名前**。RS6 a-3(2026-10-10)から ③ は ① を直に読まず、
② の flow/tx.word_retime(words.json を読む・行の数の上限・終わりの端の決まり → ① の計算)を呼ぶ。ほかの部品も `モジュール.名前` で呼ぶたびに読む。
"""
from ytt import errors as _errors  # noqa: E402
from flow import tx as _flowtx  # noqa: E402   ② 単語の時刻を読んで ① の計算に渡す word_retime(RS6 a-3。それまでは records と計算 retime を直に読んでいた)
from . import alt, store  # noqa: E402   最初の認識の記録の探し方 alt_first_run(1 か所)・保存済みの文書の読み込み


def retime_engine(doc):
    """文書の最初の認識のエンジン(recognition.runs の kind の無い最初の記録。無ければ faster-whisper とみなす)"""
    first = alt.alt_first_run(doc) if isinstance(doc, dict) else None   # 探し方は alt の 1 か所
    return str((first or {}).get("engine") or "faster-whisper")


def retime_doc(obj):
    """POST /api/retime {id, rows: [行の id…]}: 保存済みの文書と単語の時刻で、行の時刻の候補を出す(読むだけ。文書を書き換えない)"""
    tid = str(obj.get("id") or obj.get("tid") or "")
    rows = obj.get("rows")
    if not isinstance(rows, list) or not rows or not all(isinstance(x, str) and x for x in rows):
        raise _errors.ApiError("bad_rows", "合わせる行(rows = 行の id の並び)を指定してください", 400)
    doc = store.read_transcript(tid)
    upd = int(doc.get("updatedAt") or 0)
    eng = retime_engine(doc)
    got = _flowtx.word_retime(tid, doc.get("segments") or [], rows, eng)   # 行の数の上限(RETIME_MAX_ROWS)・words.json・終わりの端の決まりは ②・計算は ①
    if got is None:
        return {"items": [], "checked": 0, "updatedAt": upd, "reasonCode": "no_words",
                "reason": "この文字起こしには単語の時刻がありません(古い文字起こし・単語の時刻を使わない設定)。範囲を再認識すると取り直せます"}
    return {"items": got["items"], "checked": got["checked"], "updatedAt": upd, "engine": eng, "endEdge": got["endEdge"]}
