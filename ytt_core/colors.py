# -*- coding: utf-8 -*-
"""配信者の名前 → メンバーカラー(字幕の文字の色。docs/followup-2026-09-27.md の 4)。

色の一覧はホロカラーのものを**読むだけ**(書き換えない):
  - holo-colors/members.json(リポジトリの中。ホロカラーと同じ一覧)。YTT_HOLO_MEMBERS で場所を変えられる(テスト用)
  - ホロカラーのマイカラー(作業データの holo-colors/my-colors.json。ユーザーが足した色。同じ名前ならこちらが先)
名前の照らし合わせの規則はここ1か所(入口のまとめて実行・cut2resolve のパック・画面の候補が共通で使う)。
ひらがな/カタカナ・全角/半角・大文字/小文字・空白や「・」を区別しない。名前・ローマ字・id のどれでもよい。
完全に一致しなければ、名前の一部で1人に決まるときだけその人(「ぺこら」→ 兎田ぺこら)。2人以上なら決めない(候補を返す)。
"""
import json
import os
import re
import threading
import unicodedata

from . import datadir

MEMBERS_ENV = "YTT_HOLO_MEMBERS"
HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
NAME_MAX = 60
_cache = {}
_lock = threading.Lock()


def members_path(env=None):
    env = os.environ if env is None else env
    p = (env.get(MEMBERS_ENV) or "").strip()
    return p or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "holo-colors", "members.json")


def mine_path(env=None):
    """ホロカラーのマイカラー(ホロカラーは YTT_DATA_DIR を知らないので、inplace のとき(テスト)は読まない)"""
    root = datadir.data_root(env)
    return None if root is None else os.path.join(root, "holo-colors", "my-colors.json")


def norm_hex(s):
    """'#ff6699' / 'FF6699' -> '#FF6699'。形が違えば None"""
    m = HEX_RE.match(str(s or "").strip())
    return "#" + m.group(1).upper() if m else None


def rgb01(hex_):
    """'#FF6699' -> [1.0, 0.4, 0.6](Resolve の Text+ の色は 0〜1)"""
    h = norm_hex(hex_)
    if not h:
        raise ValueError("カラーコードの形が違います: %r" % (hex_,))
    return [round(int(h[i:i + 2], 16) / 255.0, 4) for i in (1, 3, 5)]


def normalize(s):
    """照らし合わせ用: NFKC・小文字・カタカナ → ひらがな・空白と区切り(・ - _ . など)を除く"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)
    return re.sub(r"[\s・･\-_.,、。'\"]+", "", t)


def _read_json(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache.get(path, (None,))[0] == key:
            return _cache[path][1]
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    with _lock:
        _cache[path] = (key, data)
    return data


def load(env=None, members=None, mine=None):
    """-> [{"name", "en", "id", "hex", "group", "mine"}](マイカラーが先。読めない一覧は飛ばす)"""
    out = []
    mp = mine if mine is not None else mine_path(env)
    d = _read_json(mp) if mp else None
    for m in (d.get("colors") or []) if isinstance(d, dict) else []:
        if isinstance(m, dict):
            h, name = norm_hex(m.get("hex")), str(m.get("name") or "").strip()
            if h and name:
                out.append({"name": name[:NAME_MAX], "en": "", "id": str(m.get("id") or ""), "hex": h, "group": "マイカラー", "mine": True})
    d = _read_json(members if members is not None else members_path(env))
    for g in (d.get("groups") or []) if isinstance(d, dict) else []:
        if not isinstance(g, dict):
            continue
        for m in g.get("members") or []:
            if isinstance(m, dict):
                h, name = norm_hex(m.get("hex")), str(m.get("name") or "").strip()
                if h and name:
                    out.append({"name": name[:NAME_MAX], "en": str(m.get("en") or ""), "id": str(m.get("id") or ""), "hex": h,
                                "group": str(g.get("name") or ""), "mine": False})
    return out


def lookup(name, entries=None, env=None):
    """名前 -> {"match": 1人 | None, "candidates": [名前の一部が合う人(8人まで)]}"""
    entries = load(env) if entries is None else entries
    q = normalize(name)
    if not q:
        return {"match": None, "candidates": []}
    for e in entries:
        if q in (normalize(e["name"]), normalize(e["en"]), normalize(e["id"])):
            return {"match": e, "candidates": [e]}
    part = [e for e in entries if q in normalize(e["name"]) or (len(q) >= 3 and (q in normalize(e["en"]) or q in normalize(e["id"])))]
    seen, uniq = set(), []
    for e in part:   # 同じ名前は1人と数える(先 = マイカラーが勝つ)
        k = normalize(e["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return {"match": uniq[0] if len(uniq) == 1 else None, "candidates": uniq[:8]}


def speaker_colors(names, env=None, entries=None):
    """話者の名前の並び -> ({名前: "#RRGGBB"}, [{"speaker", "name", "hex"}])(A-2: 話者ごとの字幕の色)。
    1人に決まる名前だけ(lookup の規則。「話者1」のような名前・候補が複数の名前は色を付けない)。多すぎる名前は最初の 40 人まで"""
    out, shown = {}, []
    uniq = sorted({str(n).strip() for n in names or [] if str(n or "").strip()})
    if not uniq:
        return out, shown
    entries = load(env) if entries is None else entries
    for n in uniq[:40]:
        r = lookup(n[:NAME_MAX], entries, env)
        if r["match"]:
            out[n] = r["match"]["hex"]
            shown.append({"speaker": n, "name": r["match"]["name"], "hex": r["match"]["hex"]})
    return out, shown


def resolve(name, env=None, entries=None):
    """画面・まとめて実行から来た配信者の名前 -> (名前, カラーコード)。空なら (None, None)(今までどおり黒い文字)。
    見つからない・1人に決まらなければ ValueError(画面にそのまま出せる文)"""
    s = str(name or "").strip()
    if not s:
        return None, None
    if len(s) > NAME_MAX:
        raise ValueError("配信者の名前が長すぎます(%d 文字まで)" % NAME_MAX)
    r = lookup(s, entries, env)
    if r["match"]:
        return r["match"]["name"], r["match"]["hex"]
    if r["candidates"]:
        raise ValueError("「%s」に合う人が複数います: %s。名前をもう少し詳しく入れてください" % (s, "・".join(e["name"] for e in r["candidates"][:5])))
    raise ValueError("「%s」のメンバーカラーが見つかりません(ホロカラーのマイカラーに足すと使えます)" % s)
