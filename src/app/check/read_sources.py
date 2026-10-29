"""「確かめる」の読みのカードの出どころ read:alt(V1 の V2b。資料の git:before-1028-cleanup:docs/design/v1-check-build.md の 2-2)。読むだけ(作業データに書かない)。
read:fill(後処理が直した行)は sources.py の V0 のまま。ここは 2 つ目のエンジン(alt)が今の行と食い違う所を 1 行 1 枚のカードにする。
  2 択 = 1「今の字幕」と 2「その読みを入れた行」(行の文字のうち食い違う所だけを置き換えた物)。答えは 1 / 2 / どちらも違う(打つ)
候補の計算は編集の「提案」と同じ(human/proof の alt_diffs。却下した候補は learn-feedback.json の dismissed に残っていて出さない)。
校正済みの行には出さない(今の規則)。評価用の文書は View.docs が外した後の物だけを読む。1 行に複数の候補があるときは違いがいちばん小さい物を 1 つ
(それを採る・却下するとまた次の候補が出る)。
(古い答えの記録にある read:yt の行は読み飛ばす)
"""
import os
import threading

from human.proof import alt, learn
from ytt import fsio
from . import sources   # 同じ app/check の兄弟

MAX_BYTES = 32 * 1024 * 1024
_ALT_SUFFIX = ".alt.json"
# 2 つ目のエンジンとの違い(alt_diffs)は文書と .alt.json が変わらなければ同じ = 集め直しのたびに全部の文書で計算し直さない(10-29「起動するたびにカード全部読んでる？
# めちゃくちゃ遅い」: 集め直し 8.0 秒のうち 5.7 秒がこの計算)。鍵 = (文書のパス, 文書の更新時刻・大きさ, .alt.json の更新時刻・大きさ)。却下は毎回当てる
_DIFF_MEMO = {}
_DIFF_LOCK = threading.Lock()
DIFF_MEMO_MAX = 5000


def _stamp(path):
    try:
        s = os.stat(path)
        return (s.st_mtime_ns, s.st_size)
    except OSError:
        return None


def _diffs(doc_path, alt_path, doc):
    """文書 1 枚の alt_diffs の候補(覚えていれば計算しない)。.alt.json が無い・読めなければ []"""
    key = (os.path.normcase(doc_path), _stamp(doc_path), _stamp(alt_path))
    if key[2] is None:
        return []
    with _DIFF_LOCK:
        got = _DIFF_MEMO.get(key)
    if got is not None:
        return got
    rows = _read_rows(alt_path, alt.ALT_SCHEMA)
    found = alt.alt_diffs(doc.get("segments") or [], rows)[0] if rows else []
    if key[1] is not None:   # 文書の時刻が取れないときは覚えない(同じ時刻で中身が違うのを避ける)
        with _DIFF_LOCK:
            for k in [k for k in _DIFF_MEMO if k[0] == key[0]]:   # 同じ文書の古い計算は捨てる
                _DIFF_MEMO.pop(k, None)
            if len(_DIFF_MEMO) >= DIFF_MEMO_MAX:
                _DIFF_MEMO.pop(next(iter(_DIFF_MEMO)))
            _DIFF_MEMO[key] = found
    return found


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
    found = _diffs(doc_path, os.path.join(os.path.dirname(doc_path), tid) + _ALT_SUFFIX, doc)
    if found:
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
