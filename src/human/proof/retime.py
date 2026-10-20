# -*- coding: utf-8 -*-
"""③ 人の操作の層 human/proof: 行の時刻の候補の API の包み POST /api/retime {id, rows: [行の id…]}
-> {items: [{id, start, end, matched, dStart, dEnd, edges, from}], checked, updatedAt, engine, reasonCode?, reason?}(読むだけ。採るのは画面の 1 押し)。
保存済みの文書を読み、② flow/tx.word_retime(words.json・行の数の上限 → ① pipeline/transcribe/retime の計算。名前が同じ)に渡す。
名前は retime_ で始める。
"""
from ytt import errors as _errors  # noqa: E402
from flow import tx as _flowtx  # noqa: E402   ② 単語の時刻を読んで ① の計算に渡す word_retime
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
    got = _flowtx.word_retime(tid, doc.get("segments") or [], rows)   # 行の数の上限(RETIME_MAX_ROWS)・words.json は ②・計算は ①
    if got is None:
        return {"items": [], "checked": 0, "updatedAt": upd, "reasonCode": "no_words",
                "reason": "この文字起こしには単語の時刻がありません(古い文字起こし・単語の時刻を使わない設定)。範囲を再認識すると取り直せます"}
    return {"items": got["items"], "checked": got["checked"], "updatedAt": upd, "engine": eng}
