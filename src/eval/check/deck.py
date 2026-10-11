"""「確かめる」の待ち行列を組み立てる(V1 の V0。GET /api/check/next の中身と、答える前にカードをサーバーの側で引き直す find)。

集める(sources.collect)→ 答えたカードを外す(answers.jsonl)→ 案件・種類で絞る → 並べる(lineup.order。目標は ctx.goals())→ n 枚。
読むだけ(書くのは ③ human/check)。ctx = human/check/apply の Context(app_dir・root・env・goals?(入口の条件の一覧を返す関数)・eval_dirs?)。
集めた結果は CACHE_SEC だけ覚える(ホームと案件の画面が数だけを 15 秒ごとに聞く。答え・飛ばす・戻すのあとは invalidate)。
"""
import re
import threading
import time

from human.check import answerlog
from . import goals as goals_mod, lineup, sources   # 同じ eval/check の兄弟

CACHE_SEC = 3.0
MAX_SKIP_PARAM = 200
CASE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_cache = {"key": None, "at": 0.0, "cards": None, "errors": None}
_cache_lock = threading.Lock()


def invalidate():
    with _cache_lock:
        _cache.update(key=None, cards=None, errors=None)


def _collect(ctx, st):
    key = (getattr(ctx, "app_dir", None), getattr(ctx, "root", None), st.rev)
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


def check_args(case=None, kind=None, n=None, skip=None):
    """GET の引数を検査して整える。-> (case, kind, n, skip の集合)。違えば ValueError(400)"""
    if case in ("", None):
        case = None
    elif not isinstance(case, str) or not CASE_RE.match(case):
        raise ValueError("c は案件の id にしてください")
    if kind in ("", None):
        kind = None
    elif kind not in lineup.KINDS:
        raise ValueError("kind は %s のどれかです" % "・".join(lineup.KINDS))
    n = lineup.check_n(n)
    if isinstance(skip, str):
        skip = [x for x in skip.split(",") if x]
    skip = [x for x in (skip or ()) if isinstance(x, str) and lineup.parse_id(x)][:MAX_SKIP_PARAM]
    return case, kind, n, set(skip)


def next_cards(ctx, case=None, kind=None, n=None, skip=None):
    """-> {rev, cards, counts: {today, perKind, failed}, goal, goals, total, held, failed, errors}。引数の誤りは ValueError"""
    case, kind, n, skipset = check_args(case, kind, n, skip)
    st = answerlog.state(ctx.app_dir)
    cards, errors = _collect(ctx, st)
    answered = set(st.by_card)
    pool = [c for c in cards if c["id"] not in answered and (case is None or (c.get("case") or {}).get("id") == case)
            and (kind is None or c.get("kind") == kind)]
    gk = goals_mod.by_kind(_goals(ctx))
    ordered = lineup.order(pool, gk, answerlog.read_skips(ctx.app_dir))
    rest = [c for c in ordered if c["id"] not in skipset]
    first = kind or (rest[0]["kind"] if rest else None)
    failed = st.failed()
    return {"rev": st.rev, "cards": [lineup.public(c) for c in rest[:n]],
            "counts": {"today": st.today(), "perKind": lineup.per_kind(pool), "failed": len(failed)},
            "goal": goals_mod.view(gk.get(first), first) if first else None,
            "goals": {k: goals_mod.view(g, k) for k, g in gk.items()},
            "total": len(pool),
            "held": [{"answer": r["id"], "card": r.get("card"), "kind": r.get("kind"), "source": r.get("source"), "at": r.get("at")} for r in st.held()],
            "failed": [{"answer": r["id"], "card": r.get("card"), "kind": r.get("kind"), "failed": r.get("failed"), "at": r.get("at")} for r in failed[:5]],
            "errors": list(errors or ())}


def find(ctx, card_id):
    """カードの id -> 今の出どころから組み直したカード(内側の鍵も持つ)か None(もう出ない・形が違う)。答える前に必ず引き直す(画面の target は信じない)"""
    got = lineup.parse_id(card_id)
    if not got:
        return None
    cards, _view = sources.collect(ctx, answerlog.state(ctx.app_dir), kinds=(got[0],))
    return next((c for c in cards if c["id"] == card_id), None)
