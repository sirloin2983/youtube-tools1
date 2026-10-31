"""「確かめる」の記号のカードの出どころ symbol:asr(11-01 ユーザー「消してよかったかを見直す道具は確かめるに作ればよくない？」)。読むだけ。

本番の文字起こしの素(文書の隣の <id>.asr.json の segments の text)に、文字起こしの記号の決まり(① pipeline/transcribe/symbols)を当て、
消した記号 1 つ = 1 枚(同じ記号は全部の文書でまとめて 1 枚)。数の多い記号から並べる。
  - 文書は View.docs(need_media=False)(評価用は外す・動画が片付いた文書も。音は要らない = 文字だけで決める)
  - 例 = 前後 CTX 字の文脈を EXAMPLES 個まで(いろいろな文書から)。記号に色を付けるのは画面(cards/symbol.js)
  - 一度答えた記号(答えの記録の symbol)は出さない。「例外にする」で足した字(③ human/check/symbol の check/symbol-exceptions.json)は
    決まりが残すので出ない
"""
import os
import unicodedata

from human.check import symbol as symbol_mod
from pipeline.transcribe import symbols as _symbols
from ytt import fsio
from . import lineup, sources   # 同じ app/check の兄弟(register・View)

SOURCE = "asr"
CTX = 10
EXAMPLES = 3
MAX_ASR_BYTES = 64 * 1024 * 1024
_asr = fsio.StampCache()


def _load_texts(path):
    """<id>.asr.json -> segments の text の一覧(読めない・形が違えば [])"""
    try:
        d = fsio.read_json_file(path, MAX_ASR_BYTES, allow_nan=True)
    except (OSError, UnicodeError, ValueError, RecursionError):
        return []
    segs = d.get("segments") if isinstance(d, dict) else d
    return [s["text"] for s in segs or () if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"]] if isinstance(segs, list) else []


def symbol_asr(view):
    extra = _symbols.read_extra(symbol_mod.extra_path(getattr(view.ctx, "app_dir", None)))
    done = {str((r.get("target") or {}).get("symbol") or "") for r in view.answered("symbol")}
    found = {}
    for tid, path, doc in view.docs(need_media=False):
        texts = _asr.get(os.path.join(os.path.dirname(path), tid + ".asr.json"), _load_texts) or ()
        title = str(doc.get("title") or "")[:80]
        for text in texts:
            _out, ev = _symbols.apply(text, extra)
            norm = None
            for e in ev:
                if e["kept"]:
                    continue
                code = _symbols.code_of(e["ch"])
                if code in done:
                    continue
                f = found.setdefault(code, {"ch": e["ch"], "n": 0, "docs": set(), "ex": []})
                f["n"] += 1
                f["docs"].add(tid)
                if len(f["ex"]) < EXAMPLES and all(x["docId"] != tid for x in f["ex"]):
                    norm = norm if norm is not None else unicodedata.normalize("NFKC", text)
                    a = e["at"]
                    f["ex"].append({"left": norm[max(0, a - CTX):a], "right": norm[a + 1:a + 1 + CTX], "docId": tid, "title": title})
    out = []
    for code, f in found.items():
        out.append({"id": lineup.card_id("symbol", SOURCE, code), "kind": "symbol", "source": SOURCE,
                    "case": {"id": "", "title": ""}, "target": {"symbol": code, "docId": None, "row": None},
                    "media": None, "text": f["ch"], "guess": None, "options": list(symbol_mod.CHOICES),
                    "examples": f["ex"], "count": f["n"], "docs": len(f["docs"]), "score": None, "note": "",
                    "_order": [-f["n"], code]})
    out.sort(key=lambda c: c["_order"])
    return out


sources.register("symbol", SOURCE, symbol_asr)
