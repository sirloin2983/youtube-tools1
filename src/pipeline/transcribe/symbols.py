"""文字起こしの記号の決まり(11-01。保管庫 plan/文字起こしの書き方の決まり.md の 1-1 と decisions の 11-01 の例外)。
まだ文字起こしの流れには入れていない: 確かめるの記号のカード(app/check/symbol_sources.py)と研究の道具が、何を消すかを見るために使う。

- 字を NFKC にしてから、Unicode の区分が P(句読点)と S(記号)の字を消す。空白(Z)・「ー」「っ」「々」(L)・数字・英字は字なので触らない。
- 例外(symbols-exceptions.json・足すだけで効く): 名簿の名前と呼び名の中の記号(「アーニャ・メルフィッサ」の「・」)・keep_words の語の中(「Mr.」)・
  keep_chars(「%」)・between(数字の間の . : 〜 ~ / ・英字か数字にはさまれた ' - & _ .)。
  extra = 確かめるの「例外にする」の答え(入口の作業データの check/symbol-exceptions.json の keep_chars)。呼び手がパスを渡す。
- apply(text, extra=None) -> (残した字, [{"ch", "at", "kept", "why"}])。at は NFKC にした字の位置。
- decided(c) = ユーザーが消すと決めた記号か(decided_remove。消し方は変わらない・確かめるで聞かないだけ)。
- 場面(11-02 ユーザーの案 1): 記号の前後の字の種類(scene_kind = 数字・英字・かな・漢字・空白・記号・行の端・ほか)で機械的に分ける。
  scene_of(t, i) = (記号, 前の種類, 後の種類)。確かめるの記号のカードの答えから道具が決まりの案を作り、ユーザーが認めた「残す」の決まりは
  入口の作業データの check/symbol-rules.json に入る(read_scenes が読む = apply の scenes)。認めた「消す」の決まりは今の消し方のまま(カードに出さないだけ)。
"""
import json
import os
import threading
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
EXC = os.path.join(HERE, "symbols-exceptions.json")
ROSTER = os.path.join(HERE, "hololive-roster.json")
MAX_EXTRA_BYTES = 256 * 1024
_lock = threading.Lock()
_base = {"rules": None}
_extra = {}


def is_symbol(c):
    return unicodedata.category(c)[0] in "PS"


def _kind(c):
    if c.isdigit():
        return "digit"
    if c.isascii() and c.isalpha():
        return "latin"
    return ""


def _roster_words():
    out = set()

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and key in ("names", "aliases", "name", "misrecognitions") and len(x) <= 40:
            t = unicodedata.normalize("NFKC", x)
            if any(is_symbol(c) for c in t):
                out.add(t)
    with open(ROSTER, encoding="utf-8") as f:
        walk(json.load(f))
    return out


def base_rules():
    """製品の例外の一覧と名簿から作った決まり(1 回だけ読む)"""
    with _lock:
        if _base["rules"] is None:
            with open(EXC, encoding="utf-8") as f:
                e = json.load(f)
            words = {unicodedata.normalize("NFKC", w): "例外の語" for w in e.get("keep_words") or []}
            if e.get("roster"):
                for w in _roster_words():
                    words.setdefault(w, "名簿の語")
            _base["rules"] = {"words": sorted(words.items(), key=lambda kv: -len(kv[0])),
                              "chars": {unicodedata.normalize("NFKC", c): "いつも残す字" for c in e.get("keep_chars") or []},
                              "between": [(frozenset(b["chars"]), b["side"], b.get("why") or "") for b in e.get("between") or []],
                              "decided": e.get("decided_remove") or {}}
        return _base["rules"]


SCENE_LABEL = {"digit": "数字", "latin": "英字", "kana": "かな", "kanji": "漢字", "space": "空白", "symbol": "記号", "edge": "行の端", "other": "ほかの字"}
_scenes = {}


def scene_kind(c):
    """記号の前後の字の種類(場面を分ける)。c = None は行の端"""
    if c is None:
        return "edge"
    if c.isspace():
        return "space"
    if c.isdigit():
        return "digit"
    if c.isascii() and c.isalpha():
        return "latin"
    if is_symbol(c):
        return "symbol"
    n = unicodedata.name(c, "")
    if n.startswith(("HIRAGANA", "KATAKANA")) or c == "ー":
        return "kana"
    if n.startswith("CJK UNIFIED") or c in "々〆":
        return "kanji"
    return "other"


def scene_of(t, i):
    """-> (記号, 前の字の種類, 後の字の種類)"""
    return (t[i], scene_kind(t[i - 1] if i else None), scene_kind(t[i + 1] if i + 1 < len(t) else None))


def scene_label(left, right):
    """「数字と数字の間」・「行の頭(後ろがかな)」など"""
    if left == "edge" and right == "edge":
        return "1 字だけの行"
    if left == "edge":
        return "行の頭(後ろが%s)" % SCENE_LABEL.get(right, right)
    if right == "edge":
        return "行の終わり(前が%s)" % SCENE_LABEL.get(left, left)
    return "%sと%sの間" % (SCENE_LABEL.get(left, left), SCENE_LABEL.get(right, right))


def read_scenes(path):
    """認めた「残す」の場面の決まり(確かめるの記号の決まり check/symbol-rules.json)-> {(記号, 前, 後): 理由}(更新時刻で覚え直す)"""
    if not path:
        return {}
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    got = _scenes.get(path)
    if got and got[0] == key:
        return got[1]
    out = {}
    if st.st_size <= MAX_EXTRA_BYTES:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            for r in (d.get("rules") or ()) if isinstance(d, dict) else ():
                if isinstance(r, dict) and r.get("approved") is True and r.get("action") == "keep" and isinstance(r.get("ch"), str):
                    out[(unicodedata.normalize("NFKC", r["ch"]), str(r.get("left")), str(r.get("right")))] = "認めた決まり: %s の %s は残す" % (
                        scene_label(str(r.get("left")), str(r.get("right"))), r["ch"])
        except (OSError, ValueError, AttributeError):
            out = {}
    _scenes[path] = (key, out)
    return out


def _emoji(c):
    o = ord(c)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF


def decided(c):
    """消すと決めた記号か(symbols-exceptions.json の decided_remove: 字・区分(かっこ)・絵文字)。確かめるのカードはこれを聞かない"""
    d = base_rules()["decided"]
    c = unicodedata.normalize("NFKC", c)
    return c in (d.get("chars") or "") or unicodedata.category(c) in (d.get("categories") or ()) or bool(d.get("emoji") and _emoji(c))


def read_extra(path):
    """確かめるの「例外にする」で足した字 -> {字: 理由}。無い・壊れている・大きすぎるときは {}(ファイルの更新時刻で覚え直す)"""
    if not path:
        return {}
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    got = _extra.get(path)
    if got and got[0] == key:
        return got[1]
    out = {}
    if st.st_size <= MAX_EXTRA_BYTES:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            for c in (d.get("keep_chars") or {}) if isinstance(d, dict) else ():
                if isinstance(c, str) and len(unicodedata.normalize("NFKC", c)) == 1:
                    out[unicodedata.normalize("NFKC", c)] = "確かめるで例外にした字"
        except (OSError, ValueError, AttributeError):
            out = {}
    _extra[path] = (key, out)
    return out


def apply(text, extra=None, scenes=None):
    """記号を消す。extra = 足す例外の字 {字: 理由}(read_extra の戻り)・scenes = 残す場面 {(記号, 前, 後): 理由}(read_scenes の戻り)。
    -> (残した字, 記号ごとの出来事)"""
    t = unicodedata.normalize("NFKC", text or "")
    r = base_rules()
    chars = dict(r["chars"], **(extra or {}))
    guard = {}
    for w, why in r["words"]:   # 長い語から。すでに守った所に重ねない
        s = t.find(w)
        while s >= 0:
            span = range(s, s + len(w))
            if not any(k in guard for k in span):
                for k in span:
                    guard[k] = why
            s = t.find(w, s + 1)
    out, ev = [], []
    for i, c in enumerate(t):
        if not is_symbol(c):
            out.append(c)
            continue
        why = guard.get(i) or chars.get(c) or ((scenes or {}).get(scene_of(t, i)) if scenes else None)
        if why is None:
            lk, rk = _kind(t[i - 1]) if i else "", _kind(t[i + 1]) if i + 1 < len(t) else ""
            for cs, side, w in r["between"]:
                if c in cs and lk and rk and (side != "digit" or lk == rk == "digit"):
                    why = w
                    break
        ev.append({"ch": c, "at": i, "kept": why is not None, "why": why or ""})
        if why is not None:
            out.append(c)
    return "".join(out), ev


def code_of(c):
    """記号 -> カードの鍵に使える形(u3001)"""
    return "u%04x" % ord(c)


def char_of(code):
    """code_of の逆。形が違えば None"""
    if not isinstance(code, str) or not code.startswith("u") or not 5 <= len(code) <= 7:
        return None
    try:
        c = chr(int(code[1:], 16))
    except ValueError:
        return None
    return c if is_symbol(c) else None
