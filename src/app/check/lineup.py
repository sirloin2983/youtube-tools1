"""「確かめる」の待ち行列の並び(lineup)と数え方(V1 の V0。名前は標準の queue と重ねない。資料の git:before-1028-cleanup:docs/design/v1-check-build.md の 2-3)。純粋な関数だけ(ファイルを読まない)。

カード = {id, kind, source, case: {id, title}, target, media, text, guess, options, score, note} と、並べるための内側の鍵 `_order`(数の並び。
出どころ sources.py が付ける。外へ出す前に public() で外す)。
順の規則(order):
  (1) 種類ごとの「あと / 目標」(goals.py が種類 → 入口の条件 GOALS の 1 行を引く)。届いた種類は後ろ・まだ測っていない(now が無い)種類は
      測った種類の後ろ・それ以外は あと / 目標 の小さい種類から(もう少しで決まる物を先に)
  (2) 種類の中は出どころが付けた `_order`
  (3) 同率なら軽い物から value → voice → time → cut → symbol(押す数が少ない順)
レーン(C-EVAL): 普段のレーン = NORMAL_KINDS(評価用の文書は出どころ sources.View が外す)・評価のレーン = EVAL_KINDS(評価用の文書の区間カードだけ)。
  その日に飛ばしたカード(later)は全部の後ろ(飛ばした順)。
"""
import math
import re

NORMAL_KINDS = ("value", "voice", "time", "cut", "symbol")   # 普段のレーン(cut = 自動カットのカード CUT-CARD・symbol = 文字起こしから消した記号 11-01。読み read と「この行は声ですか?」speech は 10-31 に消した = Haas に替えるため)
EVAL_KINDS = ("section",)   # 評価のレーン(評価用の文書の区間カード。C-EVAL (2))
KINDS = NORMAL_KINDS + EVAL_KINDS
LANES = {"normal": NORMAL_KINDS, "eval": EVAL_KINDS}
LIGHT = {k: i for i, k in enumerate(KINDS)}
# カードの id = <種類>:<出どころ>:<対象の鍵>(同じ対象を 2 回出さない鍵。対象の鍵は文書の id・行の id・配信・マークを # でつなぐ)
CARD_ID_RE = re.compile(r"^(value|voice|time|cut|symbol|section):([a-z]{1,12}):([A-Za-z0-9_#.-]{1,160})\Z")
DEFAULT_N, MAX_N = 10, 50


def card_id(kind, source, *parts):
    return "%s:%s:%s" % (kind, source, "#".join(str(p) for p in parts))


def parse_id(s):
    """-> (kind, source, key) か None(形が違う)"""
    m = CARD_ID_RE.match(s) if isinstance(s, str) else None
    return m.groups() if m else None


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def kind_rank(goal):
    """種類の並びの鍵(小さいほど先)。goal = 入口の条件の 1 行 {target, now, left, reached} か None(対応する目標が無い)"""
    if not isinstance(goal, dict):
        return (2, 1.0)
    if goal.get("reached"):
        return (3, 1.0)
    now, left, target = goal.get("now"), goal.get("left"), goal.get("target")
    if not _finite(now) or not _finite(left) or not _finite(target) or target <= 0:
        return (1, 1.0)
    return (0, max(0.0, min(1.0, left / target)))


def _order_key(card):
    o = card.get("_order")
    return tuple(x if _finite(x) else 0 for x in o) if isinstance(o, (list, tuple)) else ()


def _sort_key(goals_by_kind, later):
    goals_by_kind = goals_by_kind or {}
    later_pos = {cid: i for i, cid in enumerate(later)}

    def key(c):
        lp = later_pos.get(c.get("id"))
        return (0 if lp is None else 1, lp or 0, kind_rank(goals_by_kind.get(c.get("kind"))), LIGHT.get(c.get("kind"), 9), _order_key(c), c.get("id") or "")
    return key


def order(cards, goals_by_kind=None, later=()):
    """cards を出す順に並べた新しい一覧。goals_by_kind = {種類: 入口の条件の 1 行}・later = 今日飛ばしたカードの id(順に)"""
    return sorted(cards, key=_sort_key(goals_by_kind, later))


def first(cards, goals_by_kind=None, later=()):
    """order の先頭だけ(並べない = 件数だけの問い合わせ n=0 で全部を並べない。O14)。空なら None"""
    return min(cards, key=_sort_key(goals_by_kind, later)) if cards else None


def per_kind(cards, kinds=NORMAL_KINDS):
    """{種類: 枚数}(kinds の種類は 0 でも出す。既定は普段のレーンの種類)"""
    out = {k: 0 for k in kinds}
    for c in cards:
        if c.get("kind") in out:
            out[c["kind"]] += 1
    return out


def public(card):
    """外へ出す形(内側の鍵 `_` で始まる物を外す)"""
    return {k: v for k, v in card.items() if not k.startswith("_")}


def check_n(n):
    """?n= の値 -> 0〜MAX_N(0 = 数だけ)。数でない・範囲の外は ValueError"""
    if n is None or n == "":
        return DEFAULT_N
    try:
        v = int(n)
    except (TypeError, ValueError):
        raise ValueError("n は 0〜%d の数にしてください" % MAX_N)
    if not 0 <= v <= MAX_N:
        raise ValueError("n は 0〜%d の数にしてください" % MAX_N)
    return v
