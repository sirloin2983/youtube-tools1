"""話の切れ目(breaks)。切り抜きの区間の両端を、文字起こしの話の切れ目へ寄せて言葉の途中で切らないための関数(線 LD-2c。notes:plan/done/ld2-clip-length.md)。
横動画の「話題で区切る」の土台にもなる。

決まり:
- 標準ライブラリだけ。純粋な関数(ファイルも時計も読まない)。入力は文字起こしの行 [{"start": 秒, "end": 秒, "text": "…"}] だけ
- cuts = 切れ目の候補の一覧 / snap = 区間の両端を近くの切れ目へ寄せる
- 壊れた行(数でない・end < start・辞書でない)は飛ばす。text が無い行は text を "" とみなす

使い方:
    from pipeline.analyze import breaks
    cs = breaks.cuts(rows)
    a2, b2, info = breaks.snap(a, b, cs)
"""
import math

MIN_GAP = 0.4        # 行と行の間がこの秒数以上なら切れ目
GAP_CAP = 3.0        # 間の秒の加点の上限
PUNCT_BONUS = 1.0    # 行の末が句読点なら加点
TAIL_BONUS = 0.5     # 行の末が終助詞なら加点(句読点と両方はない。大きい方だけ)
PUNCT_CHARS = "。？！?!"
TAIL_CHARS = "ねよかなわぞ"
EDGE_PAD = 0.2       # 話の前後の切れ目は話の端から、この秒数離す
RADIUS = 10.0        # snap が探す前後の秒数
MIN_LEN = 5.0        # 寄せたあとの区間の最短(秒)。これより短くなるなら寄せない


def _row(r):
    """行を (start, end, text) にする。壊れた行は None"""
    if not isinstance(r, dict):
        return None
    s, e = r.get("start"), r.get("end")
    for v in (s, e):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return None
    if e < s:
        return None
    text = r.get("text")
    return float(s), float(e), (text if isinstance(text, str) else "")


def _rows(rows):
    """壊れた行を飛ばした (start, end, text) の並び"""
    out = []
    for r in rows or []:
        x = _row(r)
        if x is not None:
            out.append(x)
    return out


def _last(text):
    """text の末尾の空白を除いた最後の 1 文字。無ければ空文字"""
    s = text.rstrip()
    return s[-1] if s else ""


def _is(ch, chars):
    return bool(ch) and ch in chars


def cuts(rows, min_gap=MIN_GAP):
    """切れ目の一覧 [{"t", "gap", "kind", "score"}](t の順)。kind は句読点か終助詞の加点があれば "punct"、無ければ "gap"。行が無ければ []"""
    rs = _rows(rows)
    if not rs:
        return []
    out = []
    first = rs[0][0]
    if first >= min_gap:
        t = max(0.0, first - EDGE_PAD)
        out.append({"t": t, "gap": first - t, "kind": "gap", "score": GAP_CAP})
    for i in range(len(rs) - 1):
        _s0, e0, text = rs[i]
        s1 = rs[i + 1][0]
        gap = s1 - e0
        t = (e0 + s1) / 2
        last = _last(text)
        punct = _is(last, PUNCT_CHARS)
        tail = _is(last, TAIL_CHARS)
        if gap >= min_gap:
            bonus = PUNCT_BONUS if punct else (TAIL_BONUS if tail else 0.0)
            out.append({"t": t, "gap": gap, "kind": "punct" if (punct or tail) else "gap",
                        "score": min(gap, GAP_CAP) + bonus})
        elif punct:
            out.append({"t": t, "gap": gap, "kind": "punct", "score": PUNCT_BONUS})
    last_end = rs[-1][1]
    out.append({"t": last_end + EDGE_PAD, "gap": EDGE_PAD, "kind": "gap", "score": GAP_CAP})
    out.sort(key=lambda c: c["t"])
    return out


def _best(x, cs, radius):
    """x から ±radius の中で score ÷ (1 + 距離 ÷ radius) が最大の切れ目。無ければ None"""
    if radius <= 0:
        return None
    best = None
    for c in cs:
        d = abs(c["t"] - x)
        if d > radius:
            continue
        v = c["score"] / (1 + d / radius)
        if best is None or v > best[0]:
            best = (v, c)
    return best[1] if best else None


def snap(a, b, cs, radius=RADIUS):
    """区間 [a, b] の両端を近くの切れ目へ寄せる。(a2, b2, info)。info = {"in": [a, a2, kind か None], "out": [b, b2, kind か None]}。
    寄せたあとに短くなりすぎる(a2 >= b2 - MIN_LEN)なら両方とも動かさない。"""
    ca = _best(a, cs, radius)
    cb = _best(b, cs, radius)
    a2 = ca["t"] if ca else a
    b2 = cb["t"] if cb else b
    ka = ca["kind"] if ca else None
    kb = cb["kind"] if cb else None
    if a2 >= b2 - MIN_LEN:
        a2, b2, ka, kb = a, b, None, None
    return a2, b2, {"in": [a, a2, ka], "out": [b, b2, kb]}

