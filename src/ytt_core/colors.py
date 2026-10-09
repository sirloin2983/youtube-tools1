# -*- coding: utf-8 -*-
"""配信者の名前 → メンバーカラー(字幕の文字の色。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)。

色の一覧はホロカラーのものを**読むだけ**(書き換えない):
  - friend-apps/holo-colors/members.json(リポジトリの中。ホロカラーと同じ一覧)。YTT_HOLO_MEMBERS で場所を変えられる(テスト用)
  - ホロカラーのマイカラー(作業データの holo-colors/my-colors.json。ユーザーが足した色。同じ名前ならこちらが先)
  - ホロカラーで直したメンバーの色(作業データの holo-colors/member-colors.json。キーはメンバーの id。先頭が主な色)
字幕の色は、ホロカラーで直した色があればその先頭、無ければ members.json の subtitle(字幕の既定の色。2026-10-05 ユーザーの指定。
無い人は hex = ホロカラーの主な色)。members.json の colors(1人の色の一覧。
version 2。先頭 = hex)は項目の "colors" に入れて返すが、使う側(speaker_colors・resolve・入口)は "hex" だけを使う。
名前の照らし合わせの規則はここ1か所(入口のまとめて実行・cut2resolve のパック・画面の候補が共通で使う)。
ひらがな/カタカナ・全角/半角・大文字/小文字・空白や「・」を区別しない。名前・ローマ字・id のどれでもよい。
完全に一致しなければ、名前の一部で1人に決まるときだけその人(「ぺこら」→ 兎田ぺこら)。2人以上なら決めない(候補を返す)。
"""
import functools
import os
import re
import unicodedata

from . import datadir, fsio, layout

MEMBERS_ENV = "YTT_HOLO_MEMBERS"
HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
NAME_MAX = 60
LABEL_MAX = 12
MAX_BYTES = 4 * 1024 * 1024   # 色の一覧のファイルの上限(members.json は約 50KB。ホロカラーが書く作業データも小さい)
_SEP = re.compile(r"[\s・･\-_.,、。'\"]+")   # 照らし合わせで除く空白と区切り
_files = fsio.StampCache()   # パス -> 読んだ中身(ファイルが変わったときだけ読み直す)


def members_path(env=None):
    env = os.environ if env is None else env
    p = (env.get(MEMBERS_ENV) or "").strip()
    return p or os.path.join(layout.holo_colors_dir(), "members.json")


def _holo_file(env, name):
    """ホロカラーの作業データ(holo-colors/<name>)。ホロカラーは YTT_DATA_DIR を知らないので、inplace のとき(テスト)は読まない(None)"""
    root = datadir.data_root(env)
    return None if root is None else os.path.join(root, "holo-colors", name)


def mine_path(env=None):
    """ホロカラーのマイカラー(inplace のとき(テスト)は読まない)"""
    return _holo_file(env, "my-colors.json")


def member_colors_path(env=None):
    """ホロカラーで直したメンバーの色(マイカラーと同じく、inplace のとき(テスト)は読まない)"""
    return _holo_file(env, "member-colors.json")


def _color_list(items):
    """[{"hex", "label"}] の形の違う項目を捨てて、同じ色は1つに -> [{"hex": "#RRGGBB", "label": str}]"""
    out = []
    for c in items if isinstance(items, list) else []:
        h = norm_hex(c.get("hex")) if isinstance(c, dict) else None
        if h and all(x["hex"] != h for x in out):
            label = c.get("label")
            out.append({"hex": h, "label": label.strip()[:LABEL_MAX] if isinstance(label, str) else ""})
    return out


def _member_overrides(path):
    """member-colors.json -> {メンバーの id: [色](1つ以上)}。読めない・形の違うものは飛ばす"""
    d = _read_json(path) if path else None
    ms = d.get("members") if isinstance(d, dict) else None
    out = {}
    for k, v in ms.items() if isinstance(ms, dict) else []:
        cs = _color_list(v.get("colors")) if isinstance(v, dict) else []
        if k and cs:
            out[str(k)] = cs
    return out


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
    return _norm_text(str(s or ""))


@functools.lru_cache(maxsize=4096)   # 照らし合わせは 名前 × 一覧の人数 の回数になる(同じ文字列を何度も変換しない)
def _norm_text(t):
    t = unicodedata.normalize("NFKC", t).lower()
    t = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in t)
    return _SEP.sub("", t)


def _read_json(path):
    """色の一覧のファイル(読めなければ None。ファイルが変わったときだけ読み直す)"""
    return _files.get(path, lambda p: fsio.read_json_or(p, None, MAX_BYTES))


def _hex_name(m):
    """一覧の 1 項目 -> (主な色, 名前) か None(形が違う・色か名前が無い)"""
    if not isinstance(m, dict):
        return None
    h, name = norm_hex(m.get("hex")), str(m.get("name") or "").strip()
    return (h, name) if h and name else None


def _member_entry(m, group_name, fixed):
    """members.json のメンバー 1 人 -> 項目 か None。字幕の色の優先順位: ホロカラーで直した色の先頭 > subtitle > hex(ここ 1 か所)"""
    hn = _hex_name(m)
    if hn is None:
        return None
    h, name = hn
    mid = str(m.get("id") or "")
    cs = _color_list(m.get("colors"))
    sub = norm_hex(m.get("subtitle"))   # 字幕の既定の色(ユーザーの指定 2026-10-05)。無ければ hex
    h = sub or h
    main = next((c for c in cs if c["hex"] == h), {"hex": h, "label": "字幕" if sub else ""})   # 字幕の色を先頭へ
    cs = [main] + [c for c in cs if c["hex"] != h]
    custom = mid in fixed
    if custom:
        cs = fixed[mid]
    return {"name": name[:NAME_MAX], "en": str(m.get("en") or ""), "id": mid, "hex": cs[0]["hex"],
            "group": group_name, "mine": False, "colors": cs, "custom": custom}


def load(env=None, members=None, mine=None, member_colors=None):
    """-> [{"name", "en", "id", "hex", "group", "mine", "colors", "custom"}](マイカラーが先。読めない一覧は飛ばす)。
    hex = 字幕の色(直した色の先頭 > subtitle > members.json の hex)・colors = その人の色の一覧(先頭 = hex)・custom = ホロカラーで直した色か"""
    mp = mine if mine is not None else mine_path(env)
    d = _read_json(mp) if mp else None
    out = []
    for m in (d.get("colors") or []) if isinstance(d, dict) else []:
        hn = _hex_name(m)
        if hn:
            h, name = hn
            out.append({"name": name[:NAME_MAX], "en": "", "id": str(m.get("id") or ""), "hex": h, "group": "マイカラー", "mine": True,
                        "colors": [{"hex": h, "label": ""}], "custom": False})
    fixed = _member_overrides(member_colors if member_colors is not None else member_colors_path(env))
    d = _read_json(members if members is not None else members_path(env))
    groups = [g for g in ((d.get("groups") or []) if isinstance(d, dict) else []) if isinstance(g, dict)]
    out += [e for g in groups for e in (_member_entry(m, str(g.get("name") or ""), fixed) for m in g.get("members") or []) if e is not None]
    return out


def lookup(name, entries=None, env=None):
    """名前 -> {"match": 1人 | None, "candidates": [名前の一部が合う人(8人まで)]}"""
    entries = load(env) if entries is None else entries
    q = normalize(name)
    if not q:
        return {"match": None, "candidates": []}
    keys = [(e, normalize(e["name"]), normalize(e["en"]), normalize(e["id"])) for e in entries]
    exact = next((e for e, n, en, i in keys if q in (n, en, i)), None)
    if exact is not None:
        return {"match": exact, "candidates": [exact]}
    uniq = {}   # 名前の一部が合う人(ローマ字・id は3文字から)。同じ名前は1人と数える(先 = マイカラーが勝つ)
    for e, n, en, i in keys:
        if n not in uniq and (q in n or (len(q) >= 3 and (q in en or q in i))):
            uniq[n] = e
    uniq = list(uniq.values())
    return {"match": uniq[0] if len(uniq) == 1 else None, "candidates": uniq[:8]}


def from_channel(channel, env=None, entries=None):
    """配信のチャンネル名 -> メンバー(1人に決まるときだけ)か None(気が利く画面へ 段5・S-1)。
    チャンネル名に正式な名前(2文字以上)か英語名(4文字以上)がそのまま含まれる人。例: 「Pekora Ch. 兎田ぺこら」→ 兎田ぺこら・
    「Suisei Channel」→ None(Suisei だけでは決めない)。マイカラー(同じ名前に別の色を付けたもの)は使わない"""
    ch = normalize(channel)
    if not ch:
        return None
    entries = load(env) if entries is None else entries
    hits = {}
    for e in entries:
        if e.get("mine"):
            continue
        n, en = normalize(e["name"]), normalize(e["en"])
        if (len(n) >= 2 and n in ch) or (len(en) >= 4 and en in ch):
            hits[n] = e
    return next(iter(hits.values())) if len(hits) == 1 else None


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
