"""「確かめる」の「この行は声ですか?」の反映(notes:docs/design/v1-check-build.md・C-EVAL (3))。

答え = {choice: keep | drop}。
  - keep = 文書は触らない(記録だけ。applied.changed = False)
  - drop = 行に字幕に出さない印 noSub = True と音のメモ "novoice" を付ける(行は消さない・校正済みにしない・ほかの印やメモは残す)
Z = 付けた印とメモを元に戻す(付けたままのときだけ。あとで直されていたら断る・もう戻っていれば何もしない)。
評価用・処理中の文書は _doc.edit_row が断る。文書は human/check/_doc(human/proof/store)だけを読む。入口が import すると register される。
"""
from ytt import schemas as _yschemas

from . import _doc, apply   # 同じ human/check の兄弟(register・Refused・文書の行を直す口)

CHOICES = ("keep", "drop")
TAG = "novoice"   # ytt/schemas.ROW_TAGS の 1 つ(声の区間と重ならない行)


def _check(answer):
    """答えを検査して整える -> {choice}。違えば ValueError(400)"""
    if not isinstance(answer, dict) or set(answer) != {"choice"} or answer.get("choice") not in CHOICES:
        raise ValueError("答え(choice)は keep・drop のどれかです")
    return {"choice": answer["choice"]}


def _row_of(card):
    t = card.get("target") or {}
    tid, rid = t.get("docId"), t.get("row")
    if not isinstance(tid, str) or not _yschemas.TID_RE.match(tid) or not isinstance(rid, str) or not rid:
        raise apply.Refused("カードの行を特定できません", 400, "bad_request")
    return tid, rid


def _tags(g):
    return [t for t in (g.get("tags") or []) if isinstance(t, str)] if isinstance(g.get("tags"), list) else []


def _state(g):
    """この反映が触る 2 つの値(noSub の真偽・tags の一覧)"""
    return (g.get("noSub") is True, _tags(g))


def _apply_speech(ctx, card, answer):
    """答えを実物へ。-> applied {docId, row, changed, before?}"""
    tid, rid = _row_of(card)
    if answer["choice"] == "keep":
        return {"docId": tid, "row": rid, "changed": False}

    def fn(doc, g):
        before = _state(g)
        if before[0] and TAG in before[1]:
            return False, {"docId": tid, "row": rid, "changed": False}   # もう付いている
        g["noSub"] = True
        g["tags"] = before[1] + ([] if TAG in before[1] else [TAG])
        return True, {"docId": tid, "row": rid, "changed": True, "before": {"noSub": before[0], "tags": before[1]}}
    return _doc.edit_row(tid, rid, fn, "check:speech")


def _revert_speech(ctx, row):
    """Z。付けた印とメモを外す(値が付けた物のままのときだけ。もう戻っていれば書かない)。-> {docId, row, changed}"""
    ap = row.get("applied") or {}
    tid, rid = ap.get("docId"), ap.get("row")
    if not ap.get("changed"):
        return {"docId": tid, "row": rid, "changed": False}
    bef = ap.get("before")
    if not isinstance(tid, str) or not isinstance(rid, str) or not isinstance(bef, dict) or not isinstance(bef.get("tags"), list):
        raise apply.Refused("この答えは戻せません(記録の形が違います)", 409, "cannot_undo")
    old = (bool(bef.get("noSub")), [t for t in bef["tags"] if isinstance(t, str)])

    def fn(doc, g):
        now = _state(g)
        if now == old:
            return False, None   # もう戻っている(やりかけの Z のやり直し)
        if not (now[0] and TAG in now[1]):
            raise apply.Refused("この行は答えのあとに直されているため、戻せません(編集の画面で直してください)", 409, "changed")
        if old[0]:
            g["noSub"] = True
        else:
            g.pop("noSub", None)
        if old[1]:
            g["tags"] = list(old[1])
        else:
            g.pop("tags", None)
        return True, None
    _doc.edit_row(tid, rid, fn, "check:speech")
    return {"docId": tid, "row": rid, "changed": True}


apply.register("speech", "diar", _apply_speech, revert=_revert_speech, check=_check)
