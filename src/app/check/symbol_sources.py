"""「確かめる」の記号のカードの出どころ symbol:asr(11-01 ユーザー「消してよかったかを見直す道具は確かめるに作ればよくない？」・11-02 ユーザーの案 1)。読むだけ。

本番の文字起こしの素(文書の隣の <id>.asr.json の segments の text)に、文字起こしの記号の決まり(① pipeline/transcribe/symbols)を当て、
**消す記号が出てきた 1 か所 = 1 枚**(その文の中で消すか残すかを答える)。間引きや 1 日の上限は置かない(11-02 ユーザー「別になくていい」)。
  - 文書は View.docs(need_media=False)(評価用は外す・動画が片付いた文書も。音は要らない = 文字だけで決める)。
    whisper の頃の文字起こしの素(run.engine に whisper を含む)は外す(今の文字起こしと記号の出方が違う)
  - カード = その文の前後 CTX 字の文脈(記号に色を付けるのは画面 cards/symbol.js)・「消した後」の文・記号の名前と全角 / 半角・場面
    (前後の字の種類 = symbols.scene_of・scene_label)
  - 消すと決めた記号(① symbols.decided)・決まりで残す記号・答えた所・認めた決まりの場面(③ human/check/symbol.decided_scenes)は出さない
  - 並び = 答えの少ない場面が先ではなく、出てくる数の多い場面から(同じ場面の答えがたまると決まりの案になる)
"""
import os
import unicodedata

from human.check import symbol as symbol_mod
from pipeline.transcribe import symbols as _symbols
from ytt import fsio
from . import lineup, sources   # 同じ app/check の兄弟(register・View)

SOURCE = "asr"
CTX = 16
MAX_ASR_BYTES = 64 * 1024 * 1024
NAMES = {"・": "中黒", ".": "ピリオド", ":": "コロン", ";": "セミコロン", ",": "カンマ", "〜": "波線", "~": "チルダ", "/": "スラッシュ", "-": "ハイフン",
         "'": "アポストロフィ", '"': "ダブルクォート", "&": "アンド", "_": "アンダーバー", "…": "三点リーダー", "‥": "二点リーダー", "%": "パーセント",
         "#": "シャープ", "@": "アット", "*": "アスタリスク", "^": "キャレット", "|": "縦線", "\\": "バックスラッシュ", "$": "ドル", "¥": "円",
         "°": "度", "‐": "ハイフン", "―": "ダッシュ", "—": "ダッシュ", "–": "ダッシュ", "〃": "同じく", "゛": "濁点", "゜": "半濁点", "※": "米印", "§": "節"}
_asr = fsio.StampCache()


def _load(path):
    """<id>.asr.json -> (segments の text の一覧, whisper の頃か)(読めない・形が違えば ([], False))"""
    try:
        d = fsio.read_json_file(path, MAX_ASR_BYTES, allow_nan=True)
    except (OSError, UnicodeError, ValueError, RecursionError):
        return [], False
    run = d.get("run") if isinstance(d, dict) else None
    old = "whisper" in str((run or {}).get("engine") or "").lower()
    segs = d.get("segments") if isinstance(d, dict) else d
    texts = [s["text"] if isinstance(s, dict) and isinstance(s.get("text"), str) else "" for s in segs or ()] if isinstance(segs, list) else []
    return texts, old


def _orig_char(text, at):
    """NFKC の位置 at の字の、元の文字列での字(1 字ずつの NFKC が全体の NFKC と同じ形のときだけ。違えば None)= 全角 / 半角を出すため"""
    pos = 0
    for c in text:
        n = unicodedata.normalize("NFKC", c)
        if pos <= at < pos + len(n):
            return c if len(n) == 1 else None
        pos += len(n)
    return None


def name_of(ch, orig):
    """「中黒(全角)」・「ピリオド(半角)」。名前の無い記号は Unicode の名前"""
    base = NAMES.get(ch) or unicodedata.name(ch, "記号").lower()
    w = "" if orig is None else "全角" if unicodedata.east_asian_width(orig) in ("F", "W") else "半角"
    return base + ("(%s)" % w if w else "")


def symbol_asr(view):
    app_dir = getattr(view.ctx, "app_dir", None)
    extra = _symbols.read_extra(symbol_mod.extra_path(app_dir))
    scenes = _symbols.read_scenes(symbol_mod.rules_path(app_dir))
    decided = symbol_mod.decided_scenes(app_dir)
    done = {r.get("card") for r in view.answered("symbol")}
    found, per_scene = [], {}
    for tid, path, doc in view.docs(need_media=False):
        texts, old = _asr.get(os.path.join(os.path.dirname(path), tid + ".asr.json"), _load) or ([], False)
        if old:
            continue
        title = str(doc.get("title") or "")[:80]
        for si, text in enumerate(texts):
            if not text:
                continue
            out, ev = _symbols.apply(text, extra, scenes)
            norm = None
            for e in ev:
                if e["kept"] or _symbols.decided(e["ch"]):
                    continue
                norm = norm if norm is not None else unicodedata.normalize("NFKC", text)
                ch, left, right = _symbols.scene_of(norm, e["at"])
                if (ch, left, right) in decided:
                    continue
                cid = lineup.card_id("symbol", SOURCE, tid, si, e["at"])
                if cid in done:
                    continue
                a = e["at"]
                per_scene[(ch, left, right)] = per_scene.get((ch, left, right), 0) + 1
                found.append({"id": cid, "ch": ch, "left": left, "right": right, "tid": tid, "si": si, "at": a, "title": title,
                              "before": norm[max(0, a - CTX):a], "after_": norm[a + 1:a + 1 + CTX],
                              "removed": norm[max(0, a - CTX):a] + norm[a + 1:a + 1 + CTX], "orig": _orig_char(text, a)})
    cards = []
    for f in found:
        sc = (f["ch"], f["left"], f["right"])
        cards.append({"id": f["id"], "kind": "symbol", "source": SOURCE, "case": {"id": "", "title": f["title"]},
                      "target": {"symbol": _symbols.code_of(f["ch"]), "docId": f["tid"], "row": None, "seg": f["si"], "at": f["at"],
                                 "scene": [f["left"], f["right"]], "ctx": f["before"] + "[" + f["ch"] + "]" + f["after_"]},
                      "media": None, "text": f["ch"], "guess": None, "options": list(symbol_mod.CHOICES),
                      "context": {"left": f["before"], "right": f["after_"], "removed": f["removed"], "title": f["title"]},
                      "name": name_of(f["ch"], f["orig"]), "scene": _symbols.scene_label(f["left"], f["right"]), "sceneCount": per_scene[sc],
                      "score": None, "note": "", "_order": [-per_scene[sc], _symbols.code_of(f["ch"]), f["left"], f["right"], f["tid"], f["si"], f["at"]]})
    cards.sort(key=lambda c: c["_order"])
    return cards


sources.register("symbol", SOURCE, symbol_asr)
