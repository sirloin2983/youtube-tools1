"""「確かめる」の記号のカード「この文の、この記号は消してよいか」の反映と、記号の決まりの案(11-01 ユーザー「消してよかったかを見直す道具は確かめるに作ればよくない？」・
11-02 ユーザーの案 1)。

カードは出どころ asr(src/app/check/symbol_sources.py)。本番の文字起こしの素で、決まり pipeline/transcribe/symbols が消す記号が出てきた 1 か所 = 1 枚。
答え = {choice: ok(消してよい)| keep(残す)| unsure(迷う)}。どれも記録だけ(文書・決まりには触らない)。applied = {symbol, scene: [記号の鍵, 前, 後], doc, seg, at}。
決まりの案(proposals): 同じ場面(記号・前の字の種類・後の字の種類 = symbols.scene_of)の答えが MIN_ANSWERS 件以上たまり、消してよい / 残すの答えが
  全部そろっていれば、道具が「数字と数字の間の . は残す」のような案を作る。ユーザーが認めた物だけ決まりに入る(入口の作業データの check/symbol-rules.json):
  残すの決まり = symbols.read_scenes が読み、apply がその場面の記号を残す / 消すの決まり = 今の消し方のまま。認めた場面のカードはもう出さない(枚数がだんだん減る)。
  認めなかった案は、その場面の答えが REASK_AFTER 件増えるまでもう出さない。
迷うの一覧(unsure_list): 「迷う」と答えたカードを見返す(画面の [もう一度答える] = その答えの Z = カードがまた出る)。
11-01 の記号ごとの答え(target に scene の無いカード)の「例外にする」で足した字(check/symbol-exceptions.json)は、その答えの Z で外せるように残す。
入口が import すると register される(server が import する)。
"""
import os
import threading
import time
import unicodedata

from ytt import fsio
from . import _doc, answerlog, apply   # 同じ human/check の兄弟(register・Refused・答えの検査)

CHOICES = ("ok", "keep", "unsure")
MAX_BYTES = 256 * 1024   # pipeline/transcribe/symbols.MAX_EXTRA_BYTES と同じ(読み手が大きすぎる物を読まない)
MIN_ANSWERS = 3          # 決まりの案を作る場面の答えの数
REASK_AFTER = 3          # 認めなかった案を、答えがこれだけ増えたらまた出す
KINDS = ("digit", "latin", "kana", "kanji", "space", "symbol", "edge", "other")   # symbols.scene_kind と同じ
LABEL = {"digit": "数字", "latin": "英字", "kana": "かな", "kanji": "漢字", "space": "空白", "symbol": "記号", "edge": "行の端", "other": "ほかの字"}
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


def scene_label(left, right):
    """pipeline/transcribe/symbols.scene_label と同じ言葉"""
    if left == "edge" and right == "edge":
        return "1 字だけの行"
    if left == "edge":
        return "行の頭(後ろが%s)" % LABEL.get(right, right)
    if right == "edge":
        return "行の終わり(前が%s)" % LABEL.get(left, left)
    return "%sと%sの間" % (LABEL.get(left, left), LABEL.get(right, right))


def extra_path(app_dir):
    """11-01 の「例外にする」で足した字の置き場所(入口の作業データ)"""
    return os.path.join(app_dir or "", "check", "symbol-exceptions.json")


def rules_path(app_dir):
    """認めた・認めなかった記号の決まりの置き場所(入口の作業データ。symbols.read_scenes が読む)"""
    return os.path.join(app_dir or "", "check", "symbol-rules.json")


def _read(path):
    d = fsio.read_json_or(path, {}, max_bytes=MAX_BYTES, kind=dict)
    kc = d.get("keep_chars")
    return {"schema": "youtube-tools-symbol-exceptions/v1", "keep_chars": dict(kc) if isinstance(kc, dict) else {}}


def read_rules(app_dir):
    """-> [{ch, left, right, action: keep|remove, approved: bool, n, at}]"""
    d = fsio.read_json_or(rules_path(app_dir), {}, max_bytes=MAX_BYTES, kind=dict)
    return [r for r in d.get("rules") or () if isinstance(r, dict) and isinstance(r.get("ch"), str) and r.get("action") in ("keep", "remove")]


def _scene_key(r):
    return (r.get("ch"), r.get("left"), r.get("right"))


def decided_scenes(app_dir):
    """認めた決まりの場面 -> {(記号, 前, 後): "keep" | "remove"}(その場面のカードは出さない)"""
    return {_scene_key(r): r["action"] for r in read_rules(app_dir) if r.get("approved") is True}


def _target(card):
    t = card.get("target") or {}
    c = char_of(str(t.get("symbol") or ""))
    if c is None:
        raise apply.Refused("カードの記号を特定できません", 409, "bad_target")
    return c, t


def _apply(ctx, card, answer):
    """-> applied {symbol, scene?, doc?, seg?, at?, added}"""
    c, t = _target(card)
    code = code_of(c)
    sc = t.get("scene")
    if isinstance(sc, list) and len(sc) == 2:   # 11-02 の 1 か所ずつのカード = 記録だけ(決まりは案を認めた時だけ変わる)
        return {"symbol": code, "scene": [code, str(sc[0]), str(sc[1])], "doc": t.get("docId"), "seg": t.get("seg"), "at": t.get("at"),
                "text": str(t.get("ctx") or "")[:120], "added": False}   # text = 前後の文脈(迷うの一覧で見返す)
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
    """Z。この答えで足した字だけ外す(11-01 の形)。1 か所ずつのカードは記録を戻すだけ。-> {symbol, removed}"""
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


def _scene_rows(app_dir, rows=None):
    """効いている 1 か所ずつの答え -> [(場面 (記号, 前, 後), 答えの行)]"""
    out = []
    for r in rows if rows is not None else answerlog.state(app_dir).effective():
        if r.get("kind") != "symbol":
            continue
        sc = (r.get("applied") or {}).get("scene")
        c = char_of(sc[0]) if isinstance(sc, list) and len(sc) == 3 else None
        if c:
            out.append(((c, sc[1], sc[2]), r))
    return out


def proposals(app_dir, rows=None):
    """決まりの案 -> [{ch, left, right, label, action, n, ok, keep, unsure, text}](答えの多い順)"""
    by = {}
    for sc, r in _scene_rows(app_dir, rows):
        x = by.setdefault(sc, {"ok": 0, "keep": 0, "unsure": 0})
        ch = (r.get("answer") or {}).get("choice")
        if ch in x:
            x[ch] += 1
    done = {_scene_key(r): r for r in read_rules(app_dir)}
    out = []
    for (c, left, right), x in by.items():
        n = x["ok"] + x["keep"]
        if n < MIN_ANSWERS or (x["ok"] and x["keep"]):
            continue
        prev = done.get((c, left, right))
        if prev and (prev.get("approved") is True or n < int(prev.get("n") or 0) + REASK_AFTER):
            continue
        action = "keep" if x["keep"] else "remove"
        label = scene_label(left, right)
        out.append({"ch": c, "left": left, "right": right, "label": label, "action": action, "n": n, "ok": x["ok"], "keep": x["keep"], "unsure": x["unsure"],
                    "text": "%sの「%s」は%s" % (label, c, "残す" if action == "keep" else "消す")})
    out.sort(key=lambda p: (-p["n"], p["ch"]))
    return out


def decide(app_dir, ch, left, right, action, approve):
    """案を認める(approve = True)・認めない(False)。-> その決まりの行。形が違えば ValueError"""
    if not isinstance(ch, str) or len(unicodedata.normalize("NFKC", ch)) != 1 or char_of(code_of(ch)) is None:
        raise ValueError("記号の指定が正しくありません")
    if left not in KINDS or right not in KINDS or action not in ("keep", "remove") or not isinstance(approve, bool):
        raise ValueError("決まりの指定が正しくありません(left・right は字の種類・action は keep か remove・approve は true か false)")
    n = sum(1 for sc, r in _scene_rows(app_dir) if sc == (ch, left, right) and (r.get("answer") or {}).get("choice") in ("ok", "keep"))
    path = rules_path(app_dir)
    with _lock:
        d = fsio.read_json_or(path, {}, max_bytes=MAX_BYTES, kind=dict)
        rules = [r for r in d.get("rules") or () if isinstance(r, dict) and _scene_key(r) != (ch, left, right)]
        row = {"ch": ch, "left": left, "right": right, "action": action, "approved": approve, "n": n, "at": int(time.time() * 1000)}
        rules.append(row)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fsio.write_json(path, {"schema": "youtube-tools-symbol-rules/v1", "rules": rules}, indent=1)
    return row


def unsure_list(app_dir, rows=None):
    """「迷う」と答えた 1 か所ずつのカード -> [{answer, card, ch, label, left, right, at}](新しい順)"""
    out = []
    for (c, left, right), r in _scene_rows(app_dir, rows):
        if (r.get("answer") or {}).get("choice") != "unsure":
            continue
        out.append({"answer": r.get("id"), "card": r.get("card"), "ch": c, "label": scene_label(left, right), "left": left, "right": right,
                    "text": (r.get("applied") or {}).get("text") or "", "at": r.get("at")})
    out.sort(key=lambda x: -(x.get("at") or 0))
    return out


def summary(app_dir):
    """画面の記号の決まりの欄: {proposals, rules: [認めた決まり], unsure}"""
    rows = answerlog.state(app_dir).effective()
    rules = [dict(r, label=scene_label(str(r.get("left")), str(r.get("right")))) for r in read_rules(app_dir) if r.get("approved") is True]
    return {"proposals": proposals(app_dir, rows), "rules": rules, "unsure": unsure_list(app_dir, rows)}


apply.register("symbol", "asr", _apply, revert=_revert, check=_doc.choice(CHOICES, only=True))
