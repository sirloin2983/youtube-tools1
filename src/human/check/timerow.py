"""「確かめる」の時刻のカード「行の時刻が合っているか」の反映(notes:docs/design/v1-check-build.md の 3-2・5 節・決定 3-41)。

答え = {choice: ok | head | tail | both, dStart, dEnd}(dStart / dEnd = ← → で動かした量(秒。前へは負)。0.001 秒まで)。
  - 動かした量があれば、行の start / end をその分だけ変える(_doc.edit_row(why='check:time'))。量が 0(印だけ)なら文書は触らず記録だけ(決定 3-41)
  - ok は量 0・head は dEnd 0・tail は dStart 0 でなければならない(違えば 400)
  - 評価用の文書(evalSet)・処理中の文書は触らない。行が無い・動かすと区間が短すぎる(0.1 秒未満)ときは断る
  - text = 「読みを直す」(T)で打ち直した行の文字(10-26 ユーザー: 時刻のカードで読みを直したくなったらその場で)。あれば行の文字も直す(読みの答えの新しい版 =
    答えの記録は kind time の answer.text。eval_alt・eval_fill は読まない)。時刻の答えはそのまま
Z = 変えた端を元に戻す。その端がもう別の値なら(あとで直された)断る・もう元の値なら何もしない(やりかけの Z のやり直し)。
文書は human/check/_doc(human/proof/store)だけを読む。入口が import すると register される。
"""
from ytt import schemas as _yschemas, txbase as _txbase

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
    out = {"choice": ch, "dStart": ds, "dEnd": de}
    if "text" in answer:
        t = answer["text"]
        if not isinstance(t, str):
            raise ValueError("直した文字(text)は文字で送ってください")
        t = " ".join(t.split())
        if not t or len(t) > _txbase.MAX_TEXT or any(ord(c) < 32 for c in t):
            raise ValueError("直した文字は 1〜%d 字にしてください" % _txbase.MAX_TEXT)
        out["text"] = t
    return out


def _times(g):
    return {"start": _yschemas.num(g.get("start")), "end": _yschemas.num(g.get("end"))}


def _apply_time(ctx, card, answer):
    """答えを実物へ。-> applied {docId, row, moved, before?, after?}"""
    tid, rid = _doc.row_target(card)
    ds, de, text = answer.get("dStart") or 0.0, answer.get("dEnd") or 0.0, answer.get("text")

    def change(doc, g, before):
        retext = text is not None and text != before["text"]
        if not ds and not de and not retext:
            return None   # 印だけ(決定 3-41)= 文書は触らない
        if retext:
            g["text"] = text
        if not ds and not de:
            return True
        a, b = before["start"], before["end"]
        if a is None or b is None:
            raise apply.Refused("その行に時刻がありません", 409, "no_time")
        na, nb = round(max(0.0, a + ds), 3), round(b + de, 3)
        if nb - na < MIN_ROW_SEC:
            raise apply.Refused("動かすと行の長さが %g 秒より短くなります" % MIN_ROW_SEC, 409, "too_short")
        g["start"], g["end"] = na, nb
        return True
    got = _doc.edit_fields(tid, rid, "check:time", lambda g: dict(_times(g), text=str(g.get("text") or "")), change)
    if got is None:
        return {"docId": tid, "row": rid, "moved": False}
    bef, aft = got[0], got[1]
    out = {"docId": tid, "row": rid, "moved": bef["start"] != aft["start"] or bef["end"] != aft["end"],
           "before": {k: bef[k] for k in ("start", "end")}, "after": {k: aft[k] for k in ("start", "end")}}
    if bef["text"] != aft["text"]:
        out["text"] = {"before": bef["text"], "after": aft["text"]}
    return out


def _revert_time(ctx, row):
    """Z。変えた端を元に戻す(その端が答えのあとに別の値へ直されていたら断る・もう元の値なら書かない)。-> {docId, row, moved}"""
    ap = row.get("applied") or {}
    tid, rid = ap.get("docId"), ap.get("row")
    tx = ap.get("text") if isinstance(ap.get("text"), dict) else None
    if (ap.get("moved") or tx) and (not isinstance(tid, str) or not isinstance(rid, str)):
        raise apply.Refused("戻す行を特定できません", 409, "cannot_undo")
    if tx:   # 読みを直した文字を戻す(その後に直されていたら断る)
        _doc.revert_fields(tid, rid, "check:time", lambda g: str(g.get("text") or ""),
                           lambda now: now == tx.get("before"), lambda now: now == tx.get("after"), lambda doc, g: g.update(text=tx.get("before")),
                           "この行の文字は答えのあとに直されているため、戻せません")
    if not ap.get("moved"):
        return {"docId": tid, "row": rid, "moved": False}
    bef, aft = ap.get("before") or {}, ap.get("after") or {}
    edges = [e for e in ("start", "end") if bef.get(e) != aft.get(e)]
    bef, aft = {e: bef.get(e) for e in edges}, {e: aft.get(e) for e in edges}
    _doc.revert_fields(tid, rid, "check:time", lambda g: {e: _yschemas.num(g.get(e)) for e in edges},
                       lambda now: now == bef, lambda now: bool(edges) and now == aft, lambda doc, g: g.update(bef),
                       "この行の時刻は答えのあとに直されているため、戻せません")
    return {"docId": tid, "row": rid, "moved": True}


apply.register("time", "row", _apply_time, revert=_revert_time, check=_check)
