"""「確かめる」のカードの種類 → 入口の条件(src/eval/drill/accuracy.py の GOALS)の対応と、答えの数え方(V1 の V0。notes:docs/design/v1-check-build.md の 2-3)。

- 種類(と出どころ)→ 目標の id: value → marks(配信 10 本)・read 後処理 → fill(30 行)・read 別 → alt(100 件)・
  voice → speakers(200 行)・time → timing(100 行)。出どころが表に無ければ種類の既定(DEFAULT)
- 答えの数え方(COUNT): unit = "card"(答え 1 件 = 1)/ "case"(配信の単位 = 同じ配信の答えは 1 本)、mode = "since"(測る道具が次の測定で
  答えを数えるので、直近の測定より後の答えだけ足す)/ "all"(道具が答えを見ない = 全部足す)。
  since の 3 つ: marks は答えの副産物(スタジオの判定)を数える・fill と alt は道具が answers.jsonl の read:fill・read:alt を直に読む(read:yt の古い行は読み飛ばす)
  (src/eval/tools/eval_fill.py・eval_alt.py。答えを人の判断の正として判定できた数 judged に入れる。ただし入口の fill は A の行の judged だけなので、
  E(LLM)・D(名簿)の行への答えは次の測定で入口の数から消える)。
  all の 2 つ: 話者は道具が評価用の文書しか数えず、確かめるは評価用を出さない・行の時刻は道具の --check が夜の測定に入っていない
足すのは accuracy.goals_of(extra=)(入口の「調子」と /api/check/next の帯が同じ数を出す)。V2 の 4 本は register で組を足し・直してよい。
対応と数え方の正は入口の条件の表(accuracy.GOALS の各行の check)。ここの 3 つの表はそこから作る。
"""
from eval.drill.accuracy import GOALS
from human.check import answerlog

DEFAULT = {g["check"]["kind"]: g["id"] for g in GOALS if g.get("check") and g["check"].get("default", True)}
KIND_GOAL = {(g["check"]["kind"], s): g["id"] for g in GOALS if g.get("check") for s in g["check"]["sources"]}
COUNT = {g["id"]: tuple(g["check"]["count"]) for g in GOALS if g.get("check")}


def register(kind, source, goal_id, unit=None, mode=None):
    """種類と出どころ → 目標の対応を足す・直す(unit・mode を渡すとその目標の数え方も)"""
    KIND_GOAL[(kind, source)] = goal_id
    if unit or mode:
        cur = COUNT.get(goal_id, ("card", "since"))
        COUNT[goal_id] = (unit or cur[0], mode or cur[1])


def goal_of(kind, source=None):
    """-> 目標の id(無ければ None)"""
    return KIND_GOAL.get((kind, source)) or DEFAULT.get(kind)


def extra_counter(rows):
    """効いている答えの行 -> f(目標の id, 直近の測定の時刻 ms か None) -> その目標に足す数"""
    per = {}
    for r in rows:
        gid = goal_of(r.get("kind"), r.get("source"))
        if gid:
            per.setdefault(gid, []).append(r)

    def count(gid, at):
        unit, mode = COUNT.get(gid, ("card", "since"))
        hit = [r for r in per.get(gid, ()) if mode == "all" or not isinstance(at, (int, float)) or (isinstance(r.get("at"), int) and r["at"] > at)]
        if unit == "case":
            return len({str(r.get("case") or r.get("card")) for r in hit})
        return len(hit)
    return count


def extra_from(app_dir):
    """入口の作業データ(app)の answers.jsonl から extra_counter を作る(読めなければ 0 を返す関数)"""
    try:
        return extra_counter(answerlog.state(app_dir).effective())
    except Exception:
        return lambda gid, at: 0


def by_kind(goals):
    """入口の条件の一覧(accuracy.goals_of の結果)-> {種類: その種類の既定の目標の行}"""
    rows = {g.get("id"): g for g in goals or () if isinstance(g, dict)}
    return {k: rows.get(gid) for k, gid in DEFAULT.items() if rows.get(gid)}


def view(goal, kind):
    """帯に出す形 {kind, id, label, left, target, unit, opens, now, reached}(goal が無ければ None)"""
    if not isinstance(goal, dict):
        return None
    return {"kind": kind, "id": goal.get("id"), "label": goal.get("label"), "left": goal.get("left"), "target": goal.get("target"),
            "unit": goal.get("unit"), "opens": goal.get("opens"), "now": goal.get("now"), "reached": bool(goal.get("reached"))}
