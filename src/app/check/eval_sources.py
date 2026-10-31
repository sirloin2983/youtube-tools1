"""「確かめる」の評価のレーンの区間カードの出どころ section:eval(C-EVAL (2)。決定 3-47・3-49 Q2。反映は ③ src/human/check/section.py)。

評価用の文書(View.eval_docs。普段の出どころは使わない)のうち、まだ「全部聞いた」(evalReviewed)が無く処理中でない物から、1 本につき**次の 1 枚だけ**を出す。
  - 区間の頭 = この文書の効いている区間カードの答えの applied.to の最大(Z で戻せば頭も戻る)。無ければ文書の始まり
  - 区切り: 頭から SPAN_MIN〜SPAN_MAX 秒の間で、行のすき間(前の行の終わり〜次の行の始まり)がいちばん長い所の真ん中で切る。
    無ければ SPAN_MAX のあとの最初のすき間まで伸ばす。文書の終わりまで MIN_TAIL 秒を切るなら終わりまで(最後の区間)
  - 行の持ち主 = 行の中心が入る区間(全部の行がちょうど 1 回ずつ答えられる)。持ち主でない行で区間にかかる物は灰色で見せるだけ
  - 選択肢の名前 = メンバーのフォルダの名前だけ(⑤ eval/drill の _all_members。覚えた声・機械の予想は出さない = 正解が機械寄りにならない)。
    今の話者の名前は行に添えるだけ(選択肢にはしない。打ってもよい)
  - 行の「声が無いかも」= 話者の判別の声の区間と 3 割未満しか重ならない行(VOICE_MIN_RATIO。印だけ。10-31 に消した「この行は声ですか?」の出どころから移した)
  - スイッチ: ③ section.enabled()(既定オン・設定で消せる)。オフなら何も出さない
並びの _order: 途中まで答えた文書が先(続きから)→ 新しい文書から。
"""
import bisect

from ytt import schemas as _yschemas
from human.check import _doc as _check_doc, section as _section
from human.proof import store as _store
from eval.drill import drill as _drill
from . import evalredo, lineup, sources   # 同じ app/check の兄弟

SPAN_MIN, SPAN_MAX = 20.0, 40.0   # 区間の長さ(秒。決定 3-47)
MIN_TAIL = 10.0                   # 残りがこれより短ければ最後の区間に含める
PAD = 1.5                         # 前後に薄く流す秒
VOICE_MIN_RATIO = 0.3             # 行の長さのこの割合以上が声の区間と重なれば声の行(「声が無いかも」の印を付けない)


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


def _heads(view):
    """{文書の id: (区間の頭 = 答えた区間の終わりの最大, 答えた枚数)}"""
    out = {}
    for r in view.answered("section"):
        ap = r.get("applied") or {}
        tid, to = ap.get("docId"), _yschemas.num(ap.get("to"))
        if isinstance(tid, str) and to is not None:
            h, n = out.get(tid, (None, 0))
            out[tid] = (to if h is None else max(h, to), n + 1)
    return out


def _center(g):
    return (sources._num(g.get("start")) + sources._num(g.get("end"))) / 2


def cut_after(rows, head, end):
    """頭 head からの区間の終わり(秒)と、最後の区間か。rows = 文字のある行(時刻の順)"""
    if end - head <= SPAN_MAX + MIN_TAIL:
        return end, True
    gaps = []   # (すき間の長さ, 切る所)
    after = [g for g in rows if sources._num(g.get("end")) > head]
    for p, q in zip(after, after[1:]):
        pe, qs = sources._num(p.get("end")), sources._num(q.get("start"))
        if qs - pe > 0:
            gaps.append((qs - pe, (pe + qs) / 2))
    inside = [x for x in gaps if head + SPAN_MIN <= x[1] <= head + SPAN_MAX]
    if inside:
        to = max(inside, key=lambda x: (x[0], -x[1]))[1]
    else:
        later = [x for x in gaps if x[1] > head + SPAN_MAX]
        to = min(later, key=lambda x: x[1])[1] if later else end
    if end - to < MIN_TAIL:
        return end, True
    return round(to, 3), False


def section_eval(view):
    if not _section.enabled():
        return []
    out = []
    heads = _heads(view)
    names = None
    waiting = evalredo.waiting(getattr(view.ctx, "app_dir", None))
    for tid, path, doc in view.eval_docs():
        if tid in waiting and not evalredo.redone(doc):
            continue   # 評価用に移して、評価用の決まりでの作り直しを待っている文書(答えると作り直せなくなる。10-25)
        if _yschemas.is_eval_reviewed(doc):
            continue
        rows = sorted((g for g in sources._rows(doc) if str(g.get("text") or "").strip()), key=lambda g: (sources._num(g.get("start")), sources._num(g.get("end"))))
        if not rows or _check_doc.busy(tid):
            continue
        start = _yschemas.num_or(doc.get("start"), 0.0) or 0.0
        end = start + _store.doc_length(doc)
        head, done = heads.get(tid, (None, 0))
        head = start if head is None else head
        if head >= end - 0.05:
            continue
        to, last = cut_after(rows, head, end)
        owned = [g for g in rows if head <= _center(g) < to or (last and _center(g) >= to)]
        near = [g for g in rows if g not in owned and sources._num(g.get("end")) > head - PAD and sources._num(g.get("start")) < to + PAD]
        if names is None:
            try:
                names = _drill._all_members(view.eval_dirs())
            except Exception as e:   # 名前の一覧が読めなくてもカードは出す(打てばよい)
                view.errors.append("section:eval: names %s" % e.__class__.__name__)
                names = []
        latest = view.diar(tid, path)
        turns = _turns(latest) if isinstance(latest, dict) and latest.get("turns") else None
        sp_name = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or () if isinstance(s, dict)}

        def row_view(g, own):
            a, b = sources._num(g.get("start")), sources._num(g.get("end"))
            novoice = bool(turns) and b > a and _overlap(turns, a, b) / (b - a) < VOICE_MIN_RATIO
            return {"id": g["id"], "start": a, "end": b, "text": str(g.get("text") or ""), "speaker": sp_name.get(g.get("speaker"), ""),
                    "owned": own, "novoice": novoice, "proofed": g.get("proofed") is True,
                    "tags": [t for t in g.get("tags") or () if t in ("overlap", "bgm", "unclear")]}   # 行ごとのメモ(human/check/section.py の MEMO_TAGS)
        listed = sorted([row_view(g, True) for g in owned] + [row_view(g, False) for g in near], key=lambda r: (r["start"], r["end"]))
        case = view.case_of_doc(tid) or {"id": "", "title": str(doc.get("title") or "")[:120]}
        out.append({"id": lineup.card_id("section", "eval", tid, int(round(head * 1000))), "kind": "section", "source": "eval", "case": case,
                    "target": {"docId": tid, "from": round(head, 3), "to": round(to, 3), "rows": [g["id"] for g in owned],
                               "updatedAt": doc.get("updatedAt"), "last": last, "index": done},
                    "media": {"url": sources.MEDIA % tid, "start": head, "end": to, "pad": PAD}, "text": "",
                    "guess": None, "options": list(names), "score": None, "rows": listed,
                    "progress": {"index": done, "fromSec": round(head - start, 1), "totalSec": round(end - start, 1)},
                    "note": "評価用の動画の %d 枚目(%d:%02d〜)。答えた行は正解になります。機械の予想は出しません" % (done + 1, int(head - start) // 60, int(head - start) % 60),
                    "_order": [0 if done else 1, -sources._num(doc.get("updatedAt"))]})
        if len(out) >= sources.MAX_PER_SOURCE:
            break
    return out


sources.register("section", "eval", section_eval)
