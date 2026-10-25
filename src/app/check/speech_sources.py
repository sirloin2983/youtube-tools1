"""「確かめる」の普段のレーンの「この行は声ですか?」カードの出どころ speech:diar(C-EVAL (3))。

文書の隣の .diar.json の latest.turns(声の区間。元の動画の秒。判別の記録の形)と行を比べ、声の区間と重なるのが少ない行を出す。
重なりの割合が低い順(声の無い行を先に)。評価用の文書は出さない(View.docs だけを使う)。答えは src/human/check/speech.py が反映する。
"""
import bisect

from ytt import schemas as _yschemas
from . import sources   # 同じ app/check の兄弟(register・_doc_card・_rows を読む)

VOICE_MIN_RATIO = 0.3   # 行の長さのこの割合以上が声の区間と重なれば声の行(候補にしない)
MIN_ROW_SEC = 0.3       # これより短い行は候補にしない
PAD = 1.5               # 再生の前後の余白(秒)


def _turns(latest):
    """声の区間を [(開始, 終了)] に(開始の順)。-> (開始の一覧, 区間, 一番長い区間の長さ)"""
    out = []
    for t in latest.get("turns") or ():
        if not isinstance(t, dict):
            continue
        a, b = sources._num(t.get("start"), None), sources._num(t.get("end"), None)
        if a is None or b is None or b <= a:
            continue
        out.append((a, b))
    out.sort()
    return [a for a, _b in out], out, max((b - a for a, b in out), default=0.0)


def _overlap(turns, a, b):
    """行 [a, b] と声の区間の重なりの合計(秒)。区間が重なっていれば 1 つにまとめない(行の長さを超えない)"""
    starts, spans, longest = turns
    lo = bisect.bisect_left(starts, a - longest)
    hi = bisect.bisect_left(starts, b)
    total = 0.0
    for x, y in spans[lo:hi]:
        total += max(0.0, min(y, b) - max(x, a))
    return min(total, b - a)


def speech_diar(view):
    out, per = [], {}
    for tid, path, doc in view.docs(shorts=True):
        latest = view.diar(tid, path)
        if not isinstance(latest, dict) or not isinstance(latest.get("turns"), list) or not latest["turns"]:
            continue   # 判別の記録が無い・声の区間が空(1 人指定 = engine single は判別していない)の文書は出さない(全部の行が候補になってしまう)
        turns = _turns(latest)
        for g in sources._rows(doc):
            if sources.short_full(per, tid, doc):
                break
            if g.get("proofed") is True or _yschemas.no_sub_row(g) or not str(g.get("text") or "").strip():
                continue
            a, b = sources._num(g.get("start")), sources._num(g.get("end"))
            if b - a < MIN_ROW_SEC:
                continue
            ratio = _overlap(turns, a, b) / (b - a)
            if ratio >= VOICE_MIN_RATIO:
                continue
            per[tid] = per.get(tid, 0) + 1
            out.append(sources._doc_card(view, "speech", "diar", tid, doc, g, PAD, {
                "options": ["keep", "drop"], "note": "声の区間と重なるのは %d 割" % int(ratio * 10),
                "_order": [ratio, -sources._num(doc.get("updatedAt")), a]}))
            if len(out) >= sources.MAX_PER_SOURCE:
                return out
    return out


sources.register("speech", "diar", speech_diar)
