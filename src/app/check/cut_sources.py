"""「確かめる」の自動カットのカードの出どころ(CUT-CARD。決定: plan/opt-eval.md の Q4 自動カットのカード)。

文書の隣の <id>.edit.json の draft(機械が最初に出したカットの案 {origin, settings, keepsSec, at})を読み、残す区間の間の「消した所」を見る。
  edge   切れ目カード: 消した所の前後 2 秒をつないで聞く(切れ目が早すぎ・遅すぎ・切ってはいけない所か)。切れ目の first・middle・last の 3 枚まで
  gap    消した所カード: 機械が消した所だけ聞く(2.0 秒以上の所だけ。笑い・反応などを残すべきか)。いちばん長い 1 枚
  whole  仕上がりカード: 残した所を通しで聞く(残した合計が 120 秒以下の本だけ)
答えは src/human/check/cutcard.py が記録する(文書と edit.json には触らない)。スイッチは cutcard.enabled()(既定オフ)。
評価用の文書は View.docs が外す(ここでは読まない)。1 本の文書から出すのは最大 5 枚。
"""
import os

from ytt import fsio
from human.check import cutcard
from . import lineup, sources   # 同じ app/check の兄弟(register・MEDIA・View を読む)

EDIT_SCHEMA = "youtube-tools-edit/v1"   # human/proof/store.py の EDIT_SCHEMA と同じ
EDIT_MAX_BYTES = 1024 * 1024
ORIGINS = ("rows", "silence")           # たたき台の出どころ(行の境目・無音の境目)
MIN_GAP = 0.05                          # これより短い消した所は切れ目にしない(秒)
GAP_CARD_MIN = 2.0                      # 消した所カードは 2 秒以上の所だけ(秒)
WHOLE_MAX = 120.0                       # 仕上がりカードは残した合計がこれ以下の本だけ(秒)
EDGE_PAD = 2.0                          # 切れ目カードの前後の余白(秒。消した所は再生の途中で飛ばす)
MAX_PER_DOC = 5                         # 1 本の文書から出すカードの上限(切れ目 3 + 消した所 1 + 仕上がり 1)
RANK = {"edge": 0, "gap": 1, "whole": 2}   # 同じ文書の中の順(edge → gap → whole)


def _pair(p):
    """[a, b] の数の組 -> (a, b) か None(形が違う・有限でない・b <= a)"""
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        return None
    a, b = p
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    a, b = float(a), float(b)
    if a != a or b != b or abs(a) == float("inf") or abs(b) == float("inf") or b <= a or a < 0:
        return None
    return a, b


def _keeps(edit):
    """edit.json の draft -> 残す区間 [(a, b)](時刻の順)か None(たたき台が無い・出どころが違う・2 つ未満)"""
    draft = edit.get("draft") if isinstance(edit, dict) else None
    if not isinstance(draft, dict) or draft.get("origin") not in ORIGINS or not isinstance(draft.get("keepsSec"), list):
        return None
    keeps = [p for p in (_pair(x) for x in draft["keepsSec"]) if p]
    keeps.sort()
    return keeps if len(keeps) >= 2 else None


def _gaps(keeps):
    """残す区間の間の消した所 [(b, a)](b = 前の区間の終わり・a = 次の区間の始まり)。MIN_GAP より長い物だけ"""
    out = []
    for (_a0, b0), (a1, _b1) in zip(keeps, keeps[1:]):
        if a1 - b0 > MIN_GAP:
            out.append((b0, a1))
    return out


def _edge_pick(gaps):
    """切れ目の選び = 頭・真ん中・末(重なりは 1 つに。切れ目が無ければ空)"""
    n = len(gaps)
    if not n:
        return []
    idx = []
    for i in (0, n // 2, n - 1):
        if i not in idx:
            idx.append(i)
    return [gaps[i] for i in idx]


def _plan(view):
    """文書ごとのカードの下ごしらえ(1 回の集めで共有)。-> [(tid, 文書の新しさ, case, 切れ目, 消した所カード用の区間, 仕上がり用の区間)]"""
    cached = getattr(view, "_cut_plan", None)
    if cached is not None:
        return cached
    out = []
    for tid, path, doc in view.docs():
        epath = os.path.join(os.path.dirname(path), tid + ".edit.json")
        if not os.path.isfile(epath):
            continue
        try:
            edit = fsio.read_json_file(epath, EDIT_MAX_BYTES)
        except (OSError, ValueError, UnicodeError, RecursionError):
            continue
        if not isinstance(edit, dict) or edit.get("schema") != EDIT_SCHEMA:
            continue
        keeps = _keeps(edit)
        if keeps is None:
            continue
        gaps = _gaps(keeps)
        longest = None
        for b, a in gaps:
            if a - b >= GAP_CARD_MIN and (longest is None or a - b > longest[1] - longest[0]):
                longest = (b, a)
        total = sum(b - a for a, b in keeps)
        whole = total <= WHOLE_MAX
        out.append({"tid": tid, "updated": sources._num(doc.get("updatedAt")), "keeps": keeps,
                    "edges": _edge_pick(gaps), "gap": longest, "whole": whole, "total": total})
    view._cut_plan = out
    return out


def _case(view, tid, doc):
    return view.case_of_doc(tid) or {"id": "", "title": str(doc.get("title") or "")[:120]}


def _cards(view, source):
    """出どころ 1 つ(edge・gap・whole)のカード。切り替えが切れていれば []"""
    if not cutcard.enabled():
        return []
    docs = {tid: doc for tid, _p, doc in view.docs()}   # 評価用は docs() が外す(ここは読まない)
    out = []
    for p in _plan(view):
        tid = p["tid"]
        if tid not in docs:
            continue
        doc = docs[tid]
        case = _case(view, tid, doc)
        made = []
        if source == "edge":
            for n, (b, a) in enumerate(p["edges"]):
                ms = int(round(b * 1000))
                made.append({"id": lineup.card_id("cut", "edge", tid, ms), "kind": "cut", "source": "edge", "case": case,
                             "target": {"docId": tid, "cut": [round(b, 3), round(a, 3)]},
                             "media": {"url": sources.MEDIA % tid, "start": round(max(0.0, b - EDGE_PAD), 3), "end": round(a + EDGE_PAD, 3), "pad": 0.0},
                             "text": "", "guess": None, "options": ["good", "early", "late", "keep"], "score": None,
                             "note": "切れ目 %d 個のうち %d 番目" % (len(p["edges"]), n + 1),
                             "_order": [-p["updated"], RANK["edge"], b]})
        elif source == "gap":
            if p["gap"] is not None:
                b, a = p["gap"]
                made.append({"id": lineup.card_id("cut", "gap", tid, int(round(b * 1000))), "kind": "cut", "source": "gap", "case": case,
                             "target": {"docId": tid, "cut": [round(b, 3), round(a, 3)]},
                             "media": {"url": sources.MEDIA % tid, "start": round(b, 3), "end": round(a, 3), "pad": 1.0},
                             "text": "", "guess": None, "options": ["ok", "keep"], "score": None,
                             "note": "消した所 %.1f 秒" % (a - b),
                             "_order": [-p["updated"], RANK["gap"], b]})
        elif source == "whole" and p["whole"]:
            keeps = p["keeps"]
            made.append({"id": lineup.card_id("cut", "whole", tid, "w"), "kind": "cut", "source": "whole", "case": case,
                         "target": {"docId": tid, "keeps": [[round(a, 3), round(b, 3)] for a, b in keeps]},
                         "media": {"url": sources.MEDIA % tid, "start": round(keeps[0][0], 3), "end": round(keeps[-1][1], 3), "pad": 0.0},
                         "text": "", "guess": None, "options": ["good", "tempo", "unnatural"], "score": None,
                         "note": "残す %d 区間・%d 秒" % (len(keeps), round(p["total"])),
                         "_order": [-p["updated"], RANK["whole"], 0.0]})
        out.extend(made)   # 1 文書の枚数は 3 + 1 + 1 = MAX_PER_DOC までで頭打ち(_edge_pick・gap・whole の作りがそう決める)
    return out


def cut_edge(view):
    return _cards(view, "edge")


def cut_gap(view):
    return _cards(view, "gap")


def cut_whole(view):
    return _cards(view, "whole")


sources.register("cut", "edge", cut_edge)
sources.register("cut", "gap", cut_gap)
sources.register("cut", "whole", cut_whole)
