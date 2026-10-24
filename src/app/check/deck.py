"""「確かめる」の待ち行列を組み立てる(V1 の V0。GET /api/check/next の中身と、答える前にカードをサーバーの側で引き直す find)。

集める(sources.collect)→ 答えたカード・[分からない] にしたカードを外す(answers.jsonl の State.closed)→ 案件・種類で絞る → 並べる(lineup.order。目標は ctx.goals())→ n 枚。
読むだけ(書くのは ③ human/check)。ctx = human/check/apply の Context(app_dir・root・env・goals?(入口の条件の一覧を返す関数)・eval_dirs?)。
集めた結果は CACHE_SEC だけ覚える(ホームと案件の画面が数だけを 15 秒ごとに聞く。答え・飛ばす・戻すのあとは invalidate)。
文字起こしの文書のフォルダが変わった(文書が書かれた・足された)ら CACHE_SEC の前でも集め直す(_docs_stamp。10-25: 集め直しは 0.6〜1.5 秒かかり、
3 秒で切れて画面の 1 回ごとに集め直していた = 「読み込みが遅い」)。
"""
import os
import re
import threading
import time

from human.check import answerlog
from ytt import workdata as _workdata
from eval.check import goals as goals_mod   # ⑤ の確かめるの数え方(goals は eval/check に残る)
from human.check import section as section_mod   # 区間カードのスイッチ(評価のレーンの帯に出す。C-EVAL)
from . import lineup, sources   # 同じ app/check の兄弟

CACHE_SEC = 30.0
MAX_SKIP_PARAM = 200
CASE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
SERVED_SEC = 30 * 60   # 画面へ出したカードを、読みの失敗のときの控えとして覚える長さ(find)
MAX_SERVED = 500
_cache = {"key": None, "at": 0.0, "cards": None, "errors": None}
_cache_lock = threading.Lock()
_served = {}   # 画面へ出したカード id -> (時刻, カード)。古い順


def invalidate():
    with _cache_lock:
        _cache.update(key=None, cards=None, errors=None)


def _docs_stamp():
    """文字起こしの文書のフォルダの更新時刻(文書の書き込みは置き換えなのでフォルダの時刻が動く)。読めなければ None"""
    try:
        return os.stat(_workdata.TX_DIR).st_mtime_ns if _workdata.TX_DIR else None
    except OSError:
        return None


def _collect(ctx, st):
    key = (getattr(ctx, "app_dir", None), getattr(ctx, "root", None), st.rev, _docs_stamp())
    now = time.monotonic()
    with _cache_lock:
        if _cache["key"] == key and _cache["cards"] is not None and now - _cache["at"] < CACHE_SEC:
            return _cache["cards"], _cache["errors"]
    cards, view = sources.collect(ctx, st)
    with _cache_lock:
        _cache.update(key=key, at=now, cards=cards, errors=list(view.errors))
    return cards, view.errors


def _goals(ctx):
    fn = getattr(ctx, "goals", None)
    try:
        got = fn() if callable(fn) else []
    except Exception:
        got = []
    return got if isinstance(got, list) else []


def check_args(case=None, kind=None, n=None, skip=None, lane=None):
    """GET の引数を検査して整える。-> (case, kind, n, skip の集合, lane)。違えば ValueError(400)。
    lane = normal(普段のレーン。既定)| eval(評価のレーン = 評価用の文書の区間カード。C-EVAL)。kind はそのレーンの種類だけ"""
    lane = lane or "normal"
    if lane not in lineup.LANES:
        raise ValueError("lane は %s のどれかです" % "・".join(lineup.LANES))
    if case in ("", None):
        case = None
    elif not isinstance(case, str) or not CASE_RE.match(case):
        raise ValueError("c は案件の id にしてください")
    if kind in ("", None):
        kind = None
    elif kind not in lineup.LANES[lane]:
        raise ValueError("kind は %s のどれかです" % "・".join(lineup.LANES[lane]))
    n = lineup.check_n(n)
    if isinstance(skip, str):
        skip = [x for x in skip.split(",") if x]
    skip = [x for x in (skip or ()) if isinstance(x, str) and lineup.parse_id(x)][:MAX_SKIP_PARAM]
    return case, kind, n, set(skip), lane


def next_cards(ctx, case=None, kind=None, n=None, skip=None, lane=None):
    """-> {rev, lane, cards, counts: {today, perKind, failed}, goal, goals, total, held, failed, errors}。引数の誤りは ValueError。
    lane のカードの種類だけを出す(評価のレーンの区間カードは普段のレーンに出ない・その逆も)。
    perKind は kind で絞る前の数(画面の種類の切り替えが、選んでいない種類の残りも出すため)。total は絞った後"""
    case, kind, n, skipset, lane = check_args(case, kind, n, skip, lane)
    kinds = lineup.LANES[lane]
    st = answerlog.state(ctx.app_dir)
    cards, errors = _collect(ctx, st)
    every = [c for c in cards if not st.closed(c) and (case is None or (c.get("case") or {}).get("id") == case) and c.get("kind") in kinds]
    pool = every if kind is None else [c for c in every if c.get("kind") == kind]
    gk = goals_mod.by_kind(_goals(ctx))
    later = answerlog.read_skips(ctx.app_dir)
    if n:
        rest = [c for c in lineup.order(pool, gk, later) if c["id"] not in skipset]
        head = rest[0] if rest else None
    else:   # 数だけ(ホーム・案件の画面が 15 秒ごと): 全部を並べず先頭だけ求める(O14)
        rest = []
        head = lineup.first([c for c in pool if c["id"] not in skipset], gk, later)
    first = kind or (head["kind"] if head else None)
    failed = st.failed()
    _remember(rest[:n])
    return {"rev": st.rev, "lane": lane, "cards": [lineup.public(c) for c in rest[:n]],
            "counts": {"today": st.today(), "perKind": lineup.per_kind(every, kinds), "failed": len(failed)},
            "goal": goals_mod.view(gk.get(first), first) if first else None,
            "goals": {k: goals_mod.view(g, k) for k, g in gk.items()},
            "total": len(pool),
            "held": [{"answer": r["id"], "card": r.get("card"), "kind": r.get("kind"), "source": r.get("source"), "at": r.get("at")} for r in st.held()],
            "failed": [{"answer": r["id"], "card": r.get("card"), "kind": r.get("kind"), "failed": r.get("failed"), "at": r.get("at")} for r in failed[:5]],
            "errors": list(errors or ()),
            **({"sectionCards": section_mod.enabled()} if lane == "eval" else {})}


def _remember(cards):
    """next で画面へ出したカード(サーバーが組んだ物。内側の鍵も持つ)を覚える。find が集め直しで読みに失敗したときだけ使う"""
    now = time.monotonic()
    with _cache_lock:
        for c in cards:
            _served.pop(c["id"], None)
            _served[c["id"]] = (now, c)
        while len(_served) > MAX_SERVED:
            _served.pop(next(iter(_served)))


def find(ctx, card_id, why=None):
    """カードの id -> 今の出どころから組み直したカード(内側の鍵も持つ)か None(もう出ない・形が違う)。答える前に必ず引き直す(画面の target は信じない)。
    集め方は next と同じ(全種類・同じキャッシュ。出どころが view を共有するので 1 種類だけ集めると next と食い違う)。覚えた一覧に無ければ 1 回だけ集め直す。
    集め直しで出どころ・文書の読みが失敗していて、そのカードを SERVED_SEC 以内に画面へ出していたら、出したときのカードを使う
    (一度きりの読みの失敗で「もう確かめる物ではありません」にしない。CK-1。実物の反映は種類ごとの部品が実物を読み直して断る)。
    why にリストを渡すと、見つからないときの理由(集めたときの失敗)を足す"""
    if not lineup.parse_id(card_id):
        return None
    st = answerlog.state(ctx.app_dir)
    cards, errors = _collect(ctx, st)
    hit = next((c for c in cards if c["id"] == card_id), None)
    if hit is None:
        invalidate()
        cards, errors = _collect(ctx, st)
        hit = next((c for c in cards if c["id"] == card_id), None)
    kind, source, _key = lineup.parse_id(card_id)
    if hit is None and any(e.startswith("%s:%s:" % (kind, source)) or e.split(":", 1)[0] in ("docs", "cases") for e in errors or ()):
        with _cache_lock:
            at, card = _served.get(card_id) or (None, None)
        if card is not None and time.monotonic() - at <= SERVED_SEC:
            return card
    if hit is None and why is not None:
        why.extend(errors or ())
    return hit
