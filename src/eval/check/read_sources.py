"""「確かめる」の読みのカードの出どころ read:alt・read:yt(V1 の V2b。docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
read:fill(後処理が直した行)は sources.py の V0 のまま。ここは 2 つ目のエンジン(alt)と YouTube の字幕(yt)が今の行と食い違う所を 1 行 1 枚のカードにする。
  2 択 = 1「今の字幕」と 2「その読みを入れた行」(行の文字のうち食い違う所だけを置き換えた物)。答えは 1 / 2 / どちらも違う(打つ)
候補の計算は編集の「提案」と同じ(human/proof の alt_diffs・ytcap_diffs。却下した候補は learn-feedback.json の dismissed に残っていて出さない)。
校正済みの行には出さない(今の規則)。評価用の文書は View.docs が外した後の物だけを読む。1 行に複数の候補があるときは違いがいちばん小さい物を 1 つ
(それを採る・却下するとまた次の候補が出る)。alt と yt が同じ直しを言っているときは alt のカードに「YouTube の字幕も同じ」と注記して yt は出さない。
"""
import os

from human.proof import alt, learn, ytcap
from ytt import fsio
from . import sources   # 同じ eval/check の兄弟

MAX_BYTES = 32 * 1024 * 1024
_ALT_SUFFIX, _YT_SUFFIX = ".alt.json", ".ytcap.json"


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
    rows = _read_rows(base + (_ALT_SUFFIX if tier == "alt" else _YT_SUFFIX), alt.ALT_SCHEMA if tier == "alt" else ytcap.YTCAP_SCHEMA)
    if rows:
        segs = doc.get("segments") or []
        found = (alt.alt_diffs(segs, rows) if tier == "alt" else ytcap.ytcap_diffs(segs, rows))[0]
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
    out = []
    for tid, path, doc in view.docs():
        items = _items(view, tid, path, doc, tier)
        if not items:
            continue
        other = _items(view, tid, path, doc, "alt") if tier == "yt" else []   # alt が同じ直しを言う行は alt のカードに任せる
        by_seg = {}
        for x in items:
            by_seg.setdefault(x["seg"], []).append(x)
        for g in sources._rows(doc):
            if g.get("proofed") is True or g.get("noSub") is True or g["id"] not in by_seg:
                continue
            text = str(g.get("text") or "")
            cands = [x for x in by_seg[g["id"]] if _replaced(text, x) is not None]
            if tier == "yt":   # alt と同じ位置の候補は alt に任せる(同じ直し = 注記だけ・違う直し = alt を優先。ytcap_suggest と同じ)
                cands = [x for x in cands if not any(y["seg"] == x["seg"] and x["i"] < y["i"] + len(y["wrong"]) and y["i"] < x["i"] + len(x["wrong"]) for y in other)]
            if not cands:
                continue
            x = min(cands, key=lambda y: (len(y["wrong"]) + len(y["right"]), y["i"]))
            note = "違い: 「%s」→「%s」" % (x["wrong"], x["right"])
            also = []
            if tier == "alt":
                yt = _items(view, tid, path, doc, "yt")
                if any(y["seg"] == x["seg"] and y["i"] == x["i"] and y["wrong"] == x["wrong"] and y["right"] == x["right"] for y in yt):
                    also = ["yt"]
                    note += "(YouTube の字幕も同じ読み)"
            out.append(sources._doc_card(view, "read", tier, tid, doc, g, 0.5, {
                "guess": None, "options": [{"id": "1", "text": text}, {"id": "2", "text": _replaced(text, x)}], "note": note,
                "score": len(x["wrong"]) + len(x["right"]),
                "_cand": {"i": x["i"], "wrong": x["wrong"], "right": x["right"], "tier": tier, "also": also},
                "_order": [len(x["wrong"]) + len(x["right"]), -sources._num(doc.get("updatedAt")), sources._num(g.get("start"))]}))
            if len(out) >= sources.MAX_PER_SOURCE:
                return out
    return out


def read_alt(view):
    return _cards(view, "alt")


def read_yt(view):
    return _cards(view, "yt")


for _s, _f in (("alt", read_alt), ("yt", read_yt)):
    sources.register("read", _s, _f)
