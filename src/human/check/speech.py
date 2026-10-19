"""「確かめる」の「この行は声ですか?」の反映(notes:docs/design/v1-check-build.md・C-EVAL (3))。

答え = {choice: keep | drop}。
  - keep = 文書は触らない(記録だけ。applied.changed = False)
  - drop = 行に字幕に出さない印 noSub = True と音のメモ "novoice" を付ける(行は消さない・校正済みにしない・ほかの印やメモは残す)
Z = 付けた印とメモを元に戻す(付けたままのときだけ。あとで直されていたら断る・もう戻っていれば何もしない)。
評価用・処理中の文書は _doc.edit_row が断る。文書は human/check/_doc(human/proof/store)だけを読む。入口が import すると register される。
"""
from . import _doc, apply   # 同じ human/check の兄弟(register・Refused・文書の行を直す口)

CHOICES = ("keep", "drop")
TAG = "novoice"   # ytt/schemas.ROW_TAGS の 1 つ(声の区間と重ならない行)


def _state(g):
    """この反映が触る 2 つの値 {noSub の真偽, tags の一覧}"""
    tags = [t for t in g.get("tags") if isinstance(t, str)] if isinstance(g.get("tags"), list) else []
    return {"noSub": g.get("noSub") is True, "tags": tags}


def _apply_speech(ctx, card, answer):
    """答えを実物へ。-> applied {docId, row, changed, before?}"""
    tid, rid = _doc.row_target(card)
    if answer["choice"] == "keep":
        return {"docId": tid, "row": rid, "changed": False}

    def change(doc, g, before):
        if before["noSub"] and TAG in before["tags"]:
            return None   # もう付いている
        g["noSub"] = True
        g["tags"] = before["tags"] + ([] if TAG in before["tags"] else [TAG])
        return True
    got = _doc.edit_fields(tid, rid, "check:speech", _state, change)
    return {"docId": tid, "row": rid, "changed": False} if got is None else {"docId": tid, "row": rid, "changed": True, "before": got[0]}


def _revert_speech(ctx, row):
    """Z。付けた印とメモを外す(値が付けた物のままのときだけ。もう戻っていれば書かない)。-> {docId, row, changed}"""
    ap = row.get("applied") or {}
    tid, rid = ap.get("docId"), ap.get("row")
    if not ap.get("changed"):
        return {"docId": tid, "row": rid, "changed": False}
    bef = ap.get("before")
    if not isinstance(tid, str) or not isinstance(rid, str) or not isinstance(bef, dict) or not isinstance(bef.get("tags"), list):
        raise apply.Refused("この答えは戻せません(記録の形が違います)", 409, "cannot_undo")
    old = {"noSub": bool(bef.get("noSub")), "tags": [t for t in bef["tags"] if isinstance(t, str)]}

    def put(doc, g):
        for k, v in (("noSub", True if old["noSub"] else None), ("tags", list(old["tags"]) or None)):
            if v is None:
                g.pop(k, None)
            else:
                g[k] = v
    _doc.revert_fields(tid, rid, "check:speech", _state, lambda now: now == old, lambda now: now["noSub"] and TAG in now["tags"], put,
                       "この行は答えのあとに直されているため、戻せません(編集の画面で直してください)")
    return {"docId": tid, "row": rid, "changed": True}


apply.register("speech", "diar", _apply_speech, revert=_revert_speech, check=_doc.choice(CHOICES, only=True))
