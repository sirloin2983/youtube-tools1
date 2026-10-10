# -*- coding: utf-8 -*-
"""② 「編集」のサーバーの部品: 行の時刻の候補の API の包み(POST /api/retime)。2026-10-05。

読む速さの印・時刻の候補の計算(subread_*・retime_raw・retime_candidates ほか)は役割で組み直す RS2-9(2026-10-10)に
src/pipeline/transcribe/retime.py(① の層)へ切り出した。ここに残るのは、保存済みの文書と transcripts/<id>.words.json(認識のときの単語。行を直しても古いまま)を
読んで計算に渡す包みだけ:
   POST /api/retime {id, rows: [行の id…]} -> {items: [{id, start, end, matched, dStart, dEnd, edges, from}], checked, updatedAt, reasonCode?, reason?}
   候補を出すだけ(文書を書き換えない。採るのは画面の 1 押し)。単語の時刻が無ければ reasonCode "no_words"。
   終わりの端を候補にしないエンジンは retime.RETIME_END_SKIP(今は空)。細かい決まり・根拠の数字は retime.py の先頭。
名前は serve.py からも見える(serve.py の _ED_MODULES。retime を ed_retime より前に並べる)。ほかの部品と重ならないよう retime_ で始める。
retime.py の名前は別名・転送を置かず、`retime.名前` を呼ぶたびに読む(差し替えが効くように)。ほかの editor の部品も `ed_xxx.名前` で呼ぶたびに読む。
"""
import ed_alt  # noqa: E402,F401   最初の認識の記録の探し方 alt_first_run(1 か所)
import ed_store  # noqa: E402,F401   保存済みの文書の読み込み
from pipeline.transcribe import records, retime  # noqa: E402   単語の時刻 read_words(RS2-8a)・計算(RS2-9)
from ytt import errors as _errors  # noqa: E402


def retime_engine(doc):
    """文書の最初の認識のエンジン(recognition.runs の kind の無い最初の記録。無ければ faster-whisper とみなす)"""
    first = ed_alt.alt_first_run(doc) if isinstance(doc, dict) else None   # 探し方は ed_alt の 1 か所
    return str((first or {}).get("engine") or "faster-whisper")


def retime_doc(obj):
    """POST /api/retime {id, rows: [行の id…]}: 保存済みの文書と単語の時刻で、行の時刻の候補を出す(読むだけ。文書を書き換えない)"""
    tid = str(obj.get("id") or obj.get("tid") or "")
    rows = obj.get("rows")
    if not isinstance(rows, list) or not rows or not all(isinstance(x, str) and x for x in rows):
        raise _errors.ApiError("bad_rows", "合わせる行(rows = 行の id の並び)を指定してください", 400)
    rows = rows[:retime.RETIME_MAX_ROWS]
    doc = ed_store.read_transcript(tid)
    upd = int(doc.get("updatedAt") or 0)
    words = records.read_words(tid)
    if not words:
        return {"items": [], "checked": 0, "updatedAt": upd, "reasonCode": "no_words",
                "reason": "この文字起こしには単語の時刻がありません(古い文字起こし・単語の時刻を使わない設定)。範囲を再認識すると取り直せます"}
    eng = retime_engine(doc)
    end_ok = eng not in retime.RETIME_END_SKIP
    items = retime.retime_candidates(doc.get("segments") or [], words, rows, end_ok=end_ok)
    return {"items": items, "checked": len(rows), "updatedAt": upd, "engine": eng, "endEdge": end_ok}
