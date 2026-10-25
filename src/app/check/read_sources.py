"""「確かめる」の読みのカードの出どころ read:alt(V1 の V2b。notes:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
read:fill(後処理が直した行)は sources.py の V0 のまま。ここは 2 つ目のエンジン(alt)が今の行と食い違う所を 1 行 1 枚のカードにする。
  2 択 = 1「今の字幕」と 2「その読みを入れた行」(行の文字のうち食い違う所だけを置き換えた物)。答えは 1 / 2 / どちらも違う(打つ)
候補の計算は編集の「提案」と同じ(human/proof の alt_diffs。却下した候補は learn-feedback.json の dismissed に残っていて出さない)。
校正済みの行には出さない(今の規則)。評価用の文書は View.docs が外した後の物だけを読む。1 行に複数の候補があるときは違いがいちばん小さい物を 1 つ
(それを採る・却下するとまた次の候補が出る)。
(古い答えの記録にある read:yt の行は読み飛ばす)
"""
import os

from human.proof import alt, learn
from ytt import fsio
from . import sources   # 同じ app/check の兄弟

MAX_BYTES = 32 * 1024 * 1024
_ALT_SUFFIX = ".alt.json"


def _dismissed(tid):
    """却下した候補 {"seg|誤=>正"}(編集と同じ記録 learn-feedback.json。読めなければ空)"""
    try:
        return set(learn.load_feedback()["dismissed"].get(tid, []))
    except Exception:
        return set()


def _read_rows(path, schema):
    d = fsio.read_schema_json(path, MAX_BYTES, schema, "rows")
    return d.get("rows") if isinstance(d, dict) and isinstance(d.get("rows"), list) else None


def _items(view, tid, doc_path, doc, tier):
    """文書 1 枚の候補 [{seg, i, wrong, right, tier}](却下済みを除く)。view の中で 1 回だけ計算する"""
    memo = view.__dict__.setdefault("_read_items", {})
    if (tid, tier) in memo:
        return memo[(tid, tier)]
    out = []
    base = os.path.join(os.path.dirname(doc_path), tid)
    rows = _read_rows(base + _ALT_SUFFIX, alt.ALT_SCHEMA)
    if rows:
        segs = doc.get("segments") or []
        found = alt.alt_diffs(segs, rows)[0]
        gone = _dismissed(tid)
        out = [x for x in found if "%s|%s=>%s" % (x["seg"], x["wrong"], x["right"]) not in gone]
    memo[(tid, tier)] = out
    return out


def _replaced(text, x):
    i = x["i"]
    if text[i:i + len(x["wrong"])] != x["wrong"]:
        return None
    return text[:i] + x["right"] + text[i + len(x["wrong"]):]


def _cards(view, tier):
    out, per = [], {}
    for tid, path, doc in view.docs(shorts=True):
        items = _items(view, tid, path, doc, tier)
        if not items:
            continue
        by_seg = {}
        for x in items:
            by_seg.setdefault(x["seg"], []).append(x)
        for g in sources._rows(doc):
            if sources.short_full(per, tid, doc):
                break
            if g.get("proofed") is True or g.get("noSub") is True or g["id"] not in by_seg:
                continue
            text = str(g.get("text") or "")
            cands = [x for x in by_seg[g["id"]] if _replaced(text, x) is not None]
            if not cands:
                continue
            x = min(cands, key=lambda y: (len(y["wrong"]) + len(y["right"]), y["i"]))
            note = "違い: 「%s」→「%s」" % (x["wrong"], x["right"])
            per[tid] = per.get(tid, 0) + 1
            out.append(sources._doc_card(view, "read", tier, tid, doc, g, 0.5, {
                "guess": None, "options": [{"id": "1", "text": text}, {"id": "2", "text": _replaced(text, x)}], "note": note,
                "score": len(x["wrong"]) + len(x["right"]),
                "_cand": {"i": x["i"], "wrong": x["wrong"], "right": x["right"], "tier": tier, "also": []},
                "_order": [sources.hard_row(g), len(x["wrong"]) + len(x["right"]), -sources._num(doc.get("updatedAt")), sources._num(g.get("start"))]}, tight=True))
            if len(out) >= sources.MAX_PER_SOURCE:
                return out
    return out


def read_alt(view):
    return _cards(view, "alt")


sources.register("read", "alt", read_alt)
