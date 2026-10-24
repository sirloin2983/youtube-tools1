"""「確かめる」の読みのカード(どちらの読みが正しいか)の反映(notes:docs/design/v1-check-build.md の 2-2・3-2。import で apply に登録する)。
出どころ: fill = 後処理が直した行(1 = 今の文字・2 = 認識のまま)/ alt = 2 つ目のエンジンの読み(1 = 今の字幕・2 = その読みを入れた行)。
答え = {choice: "1" | "2" | "other" | "shift", text?: 打った正しい文字}(other = 画面の 3 のキー・shift = 4 のキー「区間がずれている・ほかの発言が入っている」)。
  shift = 何も変えない・候補の採否も記録しない(編集の「提案」に残る)。答えた行は time_row が時刻のカードに回す(読みの答えのある行 = 時刻を確かめる行)。
  ⑤ の eval_alt・eval_fill は答えを choices で絞るので shift は読み飛ばす・目標の数(eval/check/goals.py)も数えない。**文字だけの判定**: 行を校正済み(proofed)にしない・行の時刻には触れない(時刻の正解に使わない)。
  fill  1 = 何も変えない(後処理の札を残す)/ 2 = 認識のままに戻す(編集の「別の読み」の札と同じ。fill と後処理の印を外す)/ other = 打った文字(fill と印を外す)
  alt  1 = 何も変えない・候補を却下 / 2 = 食い違う所を直す・候補を採る / other = 打った文字・候補を却下
  採否は編集の「提案」と同じ記録(learn-feedback.json の alt の数と dismissed)に残す。当たり率は ⑤ の eval_alt・eval_fill が答えの記録(answers.jsonl)を読んで数える(fill は 1 = 残した・2 = 戻した・打つ = 直した)。
  alt の反映は card["_cand"](候補の位置と文字)を使う = 記録の行からカードを組み直せないので defer(1 枚遅れ)にはできない。
文書へは _doc.edit_row(why='check:read'。人の層・履歴は 10 分に 1 つ・処理中と評価用は断る)。
Z = 行の文字・fill・印の 3 つが答えたあとのままのときだけ答える前に戻す(どれかがその後に変わっていたら断る)+ 採否の記録の取り消し。
③ の層: 文書は human/check/_doc(human/proof/store)と learn だけを読む(① は読まない)。
"""
import re

from ytt import errors as _errors, schemas as _yschemas, txbase as _txbase
from . import _doc, apply   # 同じ human/check の兄弟
from human.proof import learn

CHOICES = ("1", "2", "other", "shift")   # shift = 区間がずれている・ほかの発言が入っている(読みは判定しない)
FILL_FLAG_RE = re.compile(r"^(別の読みで埋めた|名簿の呼び名に直した|話者名を外した)")   # 編集の「別の読み」の札が外す印(src/app/ui/editor/app.js の unfill と同じ)
TIERS = ("alt",)


def _check(ans):
    if not isinstance(ans, dict) or ans.get("choice") not in CHOICES:
        raise ValueError("choice は 1・2・other・shift のどれかです")
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
    return _doc.doc_id(card, "カードの文書の指定が正しくありません")


def _unflag(flag):
    return _yschemas.join_flags(*(f for f in _yschemas.flag_parts(flag) if not FILL_FLAG_RE.match(f)))


def _row_state(seg):
    """Z で比べる・戻す行の 3 つの欄(無い欄は None)"""
    return {"text": str(seg.get("text") or ""), "fill": seg.get("fill"), "flag": seg.get("flag")}


def _feedback(tid, row_id, cand, action):
    """alt の候補の採否を編集の「提案」と同じ記録に。記録できなくても文書の反映は成功(戻り値が None)"""
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


def _apply(ctx, card, ans):
    tid, row_id, source, choice = _tid(card), (card.get("target") or {}).get("row"), card.get("source"), ans["choice"]
    if choice == "shift":   # 区間がずれている = 文字は判定しない(文書も採否の記録も触らない)。行は時刻のカード(app/check/sources.py の time_row)に回る
        return {"docId": tid, "row": row_id, "source": source, "choice": "shift"}
    if source == "fill" and choice == "1":
        return {"docId": tid, "row": row_id, "source": source, "choice": "1"}   # 後処理の札を残す = 文書は何も変えない
    cand = None if source == "fill" else _cand_of(card)

    def change(doc, seg, before):
        old = before["text"]
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
        if not changed:
            return None
        seg["text"] = new
        return True

    got = _doc.edit_fields(tid, row_id, "check:read", _row_state, change)
    out = {"docId": tid, "row": row_id, "source": source, "choice": choice}
    if got is not None:
        out["before"], out["after"] = got[0], got[1]
    if cand is not None:
        fb = _feedback(tid, row_id, cand, "accept" if choice == "2" else "reject")
        if fb:
            out["feedback"] = fb
    return out


def _same(now, want):
    """行の今の 3 つの欄 now が want と同じか(want が文字だけの古い記録なら文字だけ比べる)"""
    return now == want if isinstance(want, dict) else now["text"] == want


def _revert(ctx, row):
    a = row.get("applied") or {}
    before, changed = a.get("before"), False
    if isinstance(before, dict):   # 文書を先に戻す(行がその後に変わっていたら断る = 記録も戻さない)
        def put(doc, seg):
            seg["text"] = str(before.get("text") or "")
            for k in ("fill", "flag"):
                if before.get(k) is None:
                    seg.pop(k, None)
                else:
                    seg[k] = before[k]
        changed = _doc.revert_fields(_tid({"target": {"docId": a.get("docId")}}), a.get("row"), "check:read", _row_state,
                                     lambda now: _same(now, before), lambda now: _same(now, a.get("after")), put,
                                     "その後に行の文字か印が変わっているので、戻せません(編集の画面で直してください)")
    # 採否の記録の取り消しは数を 1 つ減らす(何度も呼ぶと減りすぎる)= やりかけの Z のやり直しで文書がもう戻っていたら、取り消しも済んでいると見る
    if isinstance(a.get("feedback"), dict) and not (row.get("again") and not changed):
        try:
            learn.unrecord_feedback(a["feedback"])
        except (_errors.ApiError, OSError, ValueError):
            pass
    return {"docId": a.get("docId"), "row": a.get("row"), "changed": changed}


for _src in ("fill", "alt"):
    apply.register("read", _src, _apply, _revert, check=_check)
