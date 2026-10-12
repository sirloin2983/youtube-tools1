"""「確かめる」の読みのカード(どちらの読みが正しいか)の反映(V1 の V2b。notes:docs/design/v1-check-build.md の 2-3・3-2。import で apply に登録する)。
出どころ: fill = 後処理が直した行(1 = 今の文字・2 = 認識のまま)/ alt = 2 つ目のエンジンの読み / yt = YouTube の字幕の読み(1 = 今の字幕・2 = その読みを入れた行)。
答え = {choice: "1" | "2" | "other", text?: 打った正しい文字}。**文字だけの判定**: 行を校正済み(proofed)にしない・行の時刻には触れない(時刻の正解に使わない)。
  fill  1 = 何も変えない(後処理の札を残す)/ 2 = 認識のままに戻す(編集の「別の読み」の札と同じ。fill と後処理の印を外す)/ 3 = 打った文字(fill と印を外す)
  alt・yt  1 = 何も変えない・候補を却下 / 2 = 食い違う所を直す・候補を採る / 3 = 打った文字・候補を却下
  採否は編集の「提案」と同じ記録(learn-feedback.json の alt / yt の数と dismissed)に残す = eval_alt が今までどおり読める。fill の残す / 戻すは eval_fill が文書から読む。
文書へは store.commit(why='check:read')(人の層)。Z は逆の commit(行がその後に変わっていたら断る)+ 記録の取り消し。
③ の層: 文書は human/proof/store と learn だけを読む(① は読まない)。
"""
import re
import time

from ytt import errors as _errors, schemas as _yschemas, txbase as _txbase
from . import apply   # 同じ human/check の兄弟
from human.proof import learn, store

CHOICES = ("1", "2", "other")
FILL_FLAG_RE = re.compile(r"^(別の読みで埋めた|名簿の呼び名に直した|話者名を外した)")   # 編集の「別の読み」の札が外す印(src/editor/app.js の unfill と同じ)
TIERS = ("alt", "yt")


def check(ans):
    if not isinstance(ans, dict) or ans.get("choice") not in CHOICES:
        raise ValueError("choice は 1・2・other のどれかです")
    if ans["choice"] != "other":
        return {"choice": ans["choice"]}
    text = ans.get("text")
    if not isinstance(text, str):
        raise ValueError("正しい文字(text)を入れてください")
    text = " ".join(text.split()) if "\n" in text or "\r" in text else text.strip()
    if not text or len(text) > _txbase.MAX_TEXT or any(ord(c) < 32 for c in text):
        raise ValueError("正しい文字は 1〜%d 字にしてください" % _txbase.MAX_TEXT)
    return {"choice": "other", "text": text}


def _tid(card):
    tid = (card.get("target") or {}).get("docId")
    if not isinstance(tid, str) or not _yschemas.TID_RE.match(tid):
        raise apply.Refused("カードの文書の指定が正しくありません", 400, "bad_request")
    return tid


def _load(tid, row_id):
    try:
        doc = store.read_transcript(tid)
    except _errors.ApiError as e:
        raise apply.Refused("文字起こしを読めません: %s" % e.message, 409, "gone")
    seg = next((g for g in doc.get("segments") or () if isinstance(g, dict) and str(g.get("id")) == str(row_id)), None)
    if seg is None:
        raise apply.Refused("その行はもうありません", 409, "gone")
    return doc, seg


def _bump(doc):
    doc["updatedAt"] = max(int(time.time() * 1000), int(_yschemas.num_or(doc.get("updatedAt"), 0) or 0) + 1)


def _write(tid, doc, backup=True):
    if backup:
        store.backup_doc(tid, "check")   # 直前の 1 世代 + 履歴(「以前の版に戻す」でも戻せる)
    store.commit(tid, doc, why="check:read")


def _unflag(flag):
    return "、".join(f for f in str(flag or "").split("、") if f and not FILL_FLAG_RE.match(f))[:100]


def _feedback(tid, row_id, cand, action):
    """alt・yt の候補の採否を編集の「提案」と同じ記録に。記録できなくても文書の反映は成功(戻り値が None)"""
    item = {"seg": str(row_id), "wrong": cand["wrong"], "right": cand["right"], "tier": cand["tier"]}
    if cand.get("also"):
        item["also"] = list(cand["also"])
    obj = {"tid": tid, "action": action, "items": [item]}
    try:
        return obj if learn.record_feedback(obj) else None
    except (_errors.ApiError, OSError, ValueError):
        return None


def _cand_of(card):
    c = card.get("_cand")
    if not isinstance(c, dict) or not isinstance(c.get("i"), int) or not all(isinstance(c.get(k), str) and c[k] for k in ("wrong", "right")) or c.get("tier") not in TIERS:
        raise apply.Refused("この候補を組み直せませんでした(カードを開き直してください)", 409, "gone")
    return c


def do_apply(ctx, card, ans):
    tid, row_id, source, choice = _tid(card), (card.get("target") or {}).get("row"), card.get("source"), ans["choice"]
    if source == "fill" and choice == "1":
        return {"docId": tid, "row": row_id, "source": source, "choice": "1"}   # 後処理の札を残す = 文書は何も変えない
    with store._save_lock:
        doc, seg = _load(tid, row_id)
        old = str(seg.get("text") or "")
        before = {"text": old, "fill": seg.get("fill"), "flag": seg.get("flag")}
        out = {"docId": tid, "row": row_id, "source": source, "choice": choice}
        cand = None if source == "fill" else _cand_of(card)
        new = old
        if choice == "other":
            new = ans["text"]
        elif choice == "2":
            if source == "fill":
                f = seg.get("fill")
                if not isinstance(f, dict) or not isinstance(f.get("from"), str):
                    raise apply.Refused("後処理の印がもうありません(行が変わっています)", 409, "gone")
                new = f["from"]
            else:
                if old[cand["i"]:cand["i"] + len(cand["wrong"])] != cand["wrong"]:
                    raise apply.Refused("行の文字が変わっているので、この候補は入れられません", 409, "gone")
                new = old[:cand["i"]] + cand["right"] + old[cand["i"] + len(cand["wrong"]):]
        changed = new != old
        if source == "fill" and isinstance(seg.get("fill"), dict):   # 戻す・打つ = 後処理の札は役目を終えた(編集の unfill と同じ)
            seg.pop("fill", None)
            seg["flag"] = _unflag(seg.get("flag"))
            changed = True
        if changed:
            seg["text"] = new
            _bump(doc)
            _write(tid, doc)
            out["before"], out["after"] = before, new
    if cand is not None:
        fb = _feedback(tid, row_id, cand, "accept" if choice == "2" else "reject")
        if fb:
            out["feedback"] = fb
    return out


def do_revert(ctx, row):
    a = row.get("applied") or {}
    before, changed = a.get("before"), False
    if isinstance(before, dict):   # 文書を先に戻す(行がその後に変わっていたら断る = 記録も戻さない)
        tid = _tid({"target": {"docId": a.get("docId")}})
        with store._save_lock:
            doc, seg = _load(tid, a.get("row"))
            if str(seg.get("text") or "") != a.get("after"):
                raise apply.Refused("その後に行の文字が変わっているので、戻せません(編集の画面で直してください)", 409, "changed")
            seg["text"] = str(before.get("text") or "")
            for k in ("fill", "flag"):
                if before.get(k) is None:
                    seg.pop(k, None)
                else:
                    seg[k] = before[k]
            _bump(doc)
            _write(tid, doc, backup=False)
        changed = True
    if isinstance(a.get("feedback"), dict):
        try:
            learn.unrecord_feedback(a["feedback"])
        except (_errors.ApiError, OSError, ValueError):
            pass
    return {"docId": a.get("docId"), "row": a.get("row"), "changed": changed}


for _src in ("fill", "alt", "yt"):
    apply.register("read", _src, do_apply, do_revert, check=check)
