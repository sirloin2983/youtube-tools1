"""「確かめる」の時刻のカード「行の時刻が合っているか」の反映(notes:docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。

答え = {choice: ok | head | tail | both, dStart, dEnd}(dStart / dEnd = ← → で動かした量(秒。前へは負)。0.001 秒まで)。
  - 動かした量があれば、行の start / end をその分だけ変える(_doc.edit_row(why='check:time'))。量が 0(印だけ)なら文書は触らず記録だけ(決定 3-41)
  - ok は量 0・head は dEnd 0・tail は dStart 0 でなければならない(違えば 400)
  - 評価用の文書(evalSet)・処理中の文書は触らない。行が無い・動かすと区間が短すぎる(0.1 秒未満)ときは断る
Z = 変えた端を元に戻す。その端がもう別の値なら(あとで直された)断る・もう元の値なら何もしない(やりかけの Z のやり直し)。
文書は human/check/_doc(human/proof/store)だけを読む。入口が import すると register される。
"""
from ytt import schemas as _yschemas

from . import _doc, apply   # 同じ human/check の兄弟(register・Refused・文書の行を直す口)

CHOICES = ("ok", "head", "tail", "both")
MAX_MOVE = 2.5        # 1 枚で動かせる量の上限(秒)。画面(cards/time.js の LIMIT)と同じ = 余白 ± 2.5 秒の窓の外へは動かさない
MIN_ROW_SEC = 0.1     # 動かしたあとの行の長さの下限


def _move(v, name):
    if v is None:
        return 0.0
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) > MAX_MOVE:
        raise ValueError("%s(動かした量)は ±%g 秒までの数にしてください" % (name, MAX_MOVE))
    return round(float(v), 3)


def _check(answer):
    """答えを検査して整える -> {choice, dStart, dEnd}。違えば ValueError(400)"""
    if not isinstance(answer, dict) or answer.get("choice") not in CHOICES:
        raise ValueError("答え(choice)は ok・head・tail・both のどれかです")
    ch, ds, de = answer["choice"], _move(answer.get("dStart"), "dStart"), _move(answer.get("dEnd"), "dEnd")
    if ch in ("ok", "tail") and ds:
        raise ValueError("頭を動かしたのに、頭のずれとして答えていません")
    if ch in ("ok", "head") and de:
        raise ValueError("末を動かしたのに、末のずれとして答えていません")
    return {"choice": ch, "dStart": ds, "dEnd": de}


def _row_of(card):
    t = card.get("target") or {}
    tid, rid = t.get("docId"), t.get("row")
    if not isinstance(tid, str) or not _yschemas.TID_RE.match(tid) or not isinstance(rid, str) or not rid:
        raise apply.Refused("カードの行を特定できません", 400, "bad_request")
    return tid, rid


def _apply_time(ctx, card, answer):
    """答えを実物へ。-> applied {docId, row, moved, before?, after?}"""
    tid, rid = _row_of(card)
    ds, de = answer.get("dStart") or 0.0, answer.get("dEnd") or 0.0

    def fn(doc, g):
        if not ds and not de:
            return False, {"docId": tid, "row": rid, "moved": False}   # 印だけ(決定 3-41)= 文書は触らない
        a, b = _yschemas.num(g.get("start")), _yschemas.num(g.get("end"))
        if a is None or b is None:
            raise apply.Refused("その行に時刻がありません", 409, "no_time")
        na, nb = round(max(0.0, a + ds), 3), round(b + de, 3)
        if nb - na < MIN_ROW_SEC:
            raise apply.Refused("動かすと行の長さが %g 秒より短くなります" % MIN_ROW_SEC, 409, "too_short")
        g["start"], g["end"] = na, nb
        return True, {"docId": tid, "row": rid, "moved": True, "before": {"start": a, "end": b}, "after": {"start": na, "end": nb}}
    return _doc.edit_row(tid, rid, fn, "check:time")


def _revert_time(ctx, row):
    """Z。変えた端を元に戻す(その端が答えのあとに別の値へ直されていたら断る・もう元の値なら書かない)。-> {docId, row, moved}"""
    ap = row.get("applied") or {}
    tid, rid = ap.get("docId"), ap.get("row")
    if not ap.get("moved"):
        return {"docId": tid, "row": rid, "moved": False}
    if not isinstance(tid, str) or not isinstance(rid, str):
        raise apply.Refused("戻す行を特定できません", 409, "cannot_undo")
    bef, aft = ap.get("before") or {}, ap.get("after") or {}
    edges = [e for e in ("start", "end") if bef.get(e) != aft.get(e)]

    def fn(doc, g):
        now = {e: _yschemas.num(g.get(e)) for e in edges}
        if all(now[e] == bef.get(e) for e in edges):
            return False, None   # もう戻っている
        if any(now[e] != aft.get(e) for e in edges):
            raise apply.Refused("この行の時刻は答えのあとに直されているため、戻せません", 409, "changed")
        for e in edges:
            g[e] = bef[e]
        return True, None
    _doc.edit_row(tid, rid, fn, "check:time")
    return {"docId": tid, "row": rid, "moved": True}


apply.register("time", "row", _apply_time, revert=_revert_time, check=_check)
