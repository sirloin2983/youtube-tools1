"""採用の規則 F-5(plan/role-restructure.md 5-5・決定 3-29 Q3。RS8 B3-2 の G1a で human/review/store.py の Store.adopt_marks から出した純粋な関数)。

入力 = 配信のマークの一覧・区間・上限 → 出力 = 採る印をつけたマークの一覧と、選んだ id。ファイル・ロック・HTTP に触らない(ytt/marks の語彙だけを読む)。
保存は呼ぶ側(今はスタジオの Store.adopt_marks。② の flow/run.py の _step_adopt は今のまま HTTP の /api/video/request-marks を通す)。

採用の集合 = 区間 ranges のマーク ∪ 人が採用したマーク ∪ 自動マークの点数の高い順(上限 top までの残り)。不採用と、前の 2 つに重なる自動マークは除く。
- ranges = [[開始, 終了], …](秒)。同じ区間(±0.5 秒)のマークがあれば、それを使い回す(候補・不採用なら採用に戻す)。無ければ足す(区間は上限を超えても全部)
- 人が採用したマーク = 採用・書き出し済みで、機械が採用した印(adoptedBy)が無いもの
- 自動の分は、前に機械が採用・書き出したもの(同じ配信の送り直し・再実行)も点数の順に数に入れ、候補(判定前)のものを採用にする
- 機械が採用にしたマークには adoptedBy(区間 = "request"・自動の上位 = "auto")を付ける
- 人の判定ではないので、学習の記録(feedback)・コラボへの転写はしない(呼ぶ側もしない)
"""
import copy

from ytt import marks as _marks, schemas

TOP_MAX = 30   # 採用する数の上限


def check_args(ranges, top):
    """区間と上限を検査する。-> 小数 1 桁に丸めた区間 [(開始, 終了), …]。だめなら ValueError(画面に出せる理由)"""
    if not isinstance(ranges, list) or len(ranges) > _marks.MAX_REQUEST_RANGES:
        raise ValueError("区間は%d個までです" % _marks.MAX_REQUEST_RANGES)
    if schemas.int_in(top, 0, TOP_MAX) is None:
        raise ValueError("採用する数は0〜%dです" % TOP_MAX)
    want = []
    for r in ranges:
        if not isinstance(r, (list, tuple)) or len(r) != 2:
            raise ValueError("区間の形が正しくありません([開始, 終了])")
        try:
            want.append(_marks.check_times(r[0], r[1]))
        except _marks.BadMark as e:
            raise ValueError("区間が正しくありません: %s" % e)
    return want


def adopt(marks, want, top, duration=None):
    """採用の規則 F-5。marks = 配信のマーク(ytt/marks の形。変えない)・want = check_args の区間・top = 上限・duration = 配信の長さ(秒。区間の終わりを切る)。
    -> {"marks"(採る印をつけた新しい一覧。足した・変えたものがあれば時刻の順), "rangeIds"(want の順), "humanIds"(時刻の順),
        "autoIds"(点数の高い順), "added"(この呼び出しで採用にした id)}。
    区間が配信の外・マークが上限を超えるときは ValueError(画面に出せる理由。何も変えない)"""
    marks = copy.deepcopy(marks)
    range_ids, added = [], []
    for s, e in want:
        e = _marks.clamp_end(duration, s, e)
        if e is None:
            raise ValueError("区間が配信の長さの外です(%s 秒から)" % s)
        m = next((x for x in marks if _marks.same(x, {"start": s, "end": e})), None)
        if m is None:
            if len(marks) >= _marks.MAX_MARKS:
                raise ValueError("マークは%d件までです" % _marks.MAX_MARKS)
            m = _marks.new_mark("r", s, e, "adopted")
            m["adoptedBy"] = "request"
            marks.append(m)
            added.append(m["id"])
        elif m["status"] in ("", "rejected"):
            m["status"], m["adoptedBy"] = "adopted", "request"
            added.append(m["id"])
        if m["id"] not in range_ids:
            range_ids.append(m["id"])
    human_ids = [m["id"] for m in sorted(marks, key=_marks.by_time)
                 if m["status"] in ("adopted", "exported") and not m.get("adoptedBy") and m["id"] not in range_ids]
    taken = set(range_ids) | set(human_ids)
    picked = [(m["start"], m["end"]) for m in marks if m["id"] in taken]
    room = max(0, top - len(taken))
    autos = sorted((m for m in marks if m["src"] == "auto" and m["status"] != "rejected" and m["id"] not in taken
                    and not any(_marks.overlaps(m["start"], m["end"], s, e) for s, e in picked)), key=_marks.by_score)[:room]
    for m in autos:
        if m["status"] == "":
            m["status"], m["adoptedBy"] = "adopted", "auto"
            added.append(m["id"])
    if added:
        marks = sorted(marks, key=_marks.by_time)
    return {"marks": marks, "rangeIds": range_ids, "humanIds": human_ids, "autoIds": [m["id"] for m in autos], "added": added}
