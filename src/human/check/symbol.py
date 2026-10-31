"""「確かめる」の記号のカード「この記号は消してよいか」の反映(11-01 ユーザー「消してよかったかを見直す道具は確かめるに作ればよくない？」)。

カードは出どころ asr(src/app/check/symbol_sources.py。本番の文字起こしの素 <id>.asr.json で、決まり pipeline/transcribe/symbols が消す記号 1 つ = 1 枚)。
答え = {choice: ok(消してよい)| keep(例外にする)| unsure(迷う)}。
  - keep は、その字を入口の作業データの check/symbol-exceptions.json の keep_chars に足す(symbols.apply の extra = 次から消さない字)。
    もう足してあれば何もしない。ok・unsure は記録だけ
Z = keep で足した字を外す(この答えで足した時だけ。前から足してあった字は外さない)。もう外れていれば何もしない(やりかけの Z のやり直し)。
文字起こしの文書には触らない。入口が import すると register される(server が import する)。
"""
import os
import threading
import unicodedata

from ytt import fsio
from . import _doc, apply   # 同じ human/check の兄弟(register・Refused・答えの検査)

CHOICES = ("ok", "keep", "unsure")
MAX_BYTES = 256 * 1024   # pipeline/transcribe/symbols.MAX_EXTRA_BYTES と同じ(読み手が大きすぎる物を読まない)
_lock = threading.Lock()


def code_of(c):
    """記号 -> カードの鍵の形(u3001)。pipeline/transcribe/symbols.code_of と同じ(③ は ① を直に読まない)"""
    return "u%04x" % ord(c)


def char_of(code):
    """code_of の逆。記号(Unicode の P・S)でなければ None"""
    if not isinstance(code, str) or not code.startswith("u") or not 5 <= len(code) <= 7:
        return None
    try:
        c = chr(int(code[1:], 16))
    except ValueError:
        return None
    return c if unicodedata.category(c)[0] in "PS" else None


def extra_path(app_dir):
    """「例外にする」で足した字の置き場所(入口の作業データ)"""
    return os.path.join(app_dir or "", "check", "symbol-exceptions.json")


def _read(path):
    d = fsio.read_json_or(path, {}, max_bytes=MAX_BYTES, kind=dict)
    kc = d.get("keep_chars")
    return {"schema": "youtube-tools-symbol-exceptions/v1", "keep_chars": dict(kc) if isinstance(kc, dict) else {}}


def _target_char(card):
    c = char_of(str((card.get("target") or {}).get("symbol") or ""))
    if c is None:
        raise apply.Refused("カードの記号を特定できません", 409, "bad_target")
    return c


def _apply(ctx, card, answer):
    """-> applied {symbol, added}"""
    c = _target_char(card)
    code = code_of(c)
    if answer.get("choice") != "keep":
        return {"symbol": code, "added": False}
    path = extra_path(ctx.app_dir)
    with _lock:
        d = _read(path)
        if c in d["keep_chars"]:
            return {"symbol": code, "added": False}
        d["keep_chars"][c] = {"card": card.get("id")}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fsio.write_json(path, d, indent=1)
    return {"symbol": code, "added": True}


def _revert(ctx, row):
    """Z。この答えで足した字だけ外す。-> {symbol, removed}"""
    ap = row.get("applied") or {}
    code = ap.get("symbol")
    if not ap.get("added"):
        return {"symbol": code, "removed": False}
    c = char_of(str(code or ""))
    if c is None:
        raise apply.Refused("戻す記号を特定できません", 409, "cannot_undo")
    path = extra_path(ctx.app_dir)
    with _lock:
        d = _read(path)
        if c not in d["keep_chars"]:
            return {"symbol": code, "removed": False}
        del d["keep_chars"][c]
        fsio.write_json(path, d, indent=1)
    return {"symbol": code, "removed": True}


apply.register("symbol", "asr", _apply, revert=_revert, check=_doc.choice(CHOICES, only=True))
