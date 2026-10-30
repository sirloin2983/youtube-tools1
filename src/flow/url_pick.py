# -*- coding: utf-8 -*-
"""配信の後の解析から届ける候補の選び方(10-30 ユーザー。decisions の最後の 2 つの【重】)。

A. URL の自動依頼の選び方(スイッチ FINAL_ON。研究の 138 番 = queue138_url.py の「138 の形」・225 番):
  友人の URL の自動依頼(区間の指定なし = 本数だけ頼む)は、頼まれた本数のまま、最終の候補の点の順に選び、終わりを笑いの収まりまで縮める。
  最終の候補の点 = 仮説 8(excite.rerank の z)+ FINAL_LC_W × z(山の前後 60 秒の笑いの書き込みの件数)= 解析の印 chatRank.final
  (z は候補の元 RERANK_POOL 本の中・flow/live_batch の最終の候補の点と同じ式)。縮め = live_batch.shrink_end の配信の終わりの形
  (全部の箱をふだんにした収まり chatRank.settleAll・上限なし = 研究の 62 番の形)。つないだ候補は縮めない。
  解析の要約(配信の analysis.cands)に final・settle が無い(チャットの無い・前の版の解析)候補は、今のまま点数の順・元のまま。
B. heatmap の山を 1 本足す・見つけにくい配信は 1 本減らす(スイッチ HEAT_ONE_ON。研究の 275・278・280・281 番):
  解析の時に heatmap があれば、解析が足した heatmap の山(excite.heat_extra の origin heatmap。高い山の順)のうち、選んだ候補と重ならない最初の 1 本を本数の外に足す。
  無ければ足さない(待たない・取り直さない)。長さが LOW_LONG_SEC(3 時間)以上の配信とチャットの無い配信は本数を 1 本減らす(2 本以上のときだけ)。
  当てる先 = URL の自動依頼(flow/run._step_adopt)と配信の後のアーカイブの全自動(flow/live_archive._after_adopt)。live_batch の配信の終わりの分は対象外。
印: URL の自動依頼 = 採用の段の記録 urlPick {final, cut, low, heat}・足した候補は .clip.json の source.cand.origin heatmap(解析の要約の印)。
    アーカイブの全自動 = afterStream の low と picked の heat。
研究と違う所は decisions の【重】(10-30)。
"""
from ytt import schemas
from . import live_batch as _lb

FINAL_ON = True              # スイッチ A: False = 前の形(点数の順・元のまま)
HEAT_ONE_ON = True           # スイッチ B: False = 前の形(heatmap の山は足さない・本数は減らさない)
LOW_LONG_SEC = 3 * 3600.0    # 本数を 1 本減らす長い配信(秒)
HEAT_LABEL = "YouTube でよく見られている場面"


def _cands(analysis):
    a = analysis if isinstance(analysis, dict) else {}
    return [c for c in a.get("cands") or [] if isinstance(c, dict) and schemas.is_num(c.get("start")) and schemas.is_num(c.get("end"))]


def low_why(analysis, duration):
    """本数を 1 本減らす配信か -> "long"(3 時間以上)/ "nochat"(チャットが使えなかった)/ None。スイッチ HEAT_ONE_ON"""
    if not HEAT_ONE_ON or not isinstance(analysis, dict):
        return None
    if schemas.is_num(duration) and duration >= LOW_LONG_SEC:
        return "long"
    if (analysis.get("signals") or {}).get("chat") is False:
        return "nochat"
    return None


def heat_spans(analysis):
    """足す候補の並び [[開始, 終了], …](解析が足した heatmap の山 = 高い順)。スイッチ HEAT_ONE_ON"""
    if not HEAT_ONE_ON:
        return []
    return [[c["start"], c["end"]] for c in _cands(analysis) if c.get("origin") == "heatmap"]


def final_pref(analysis):
    """A: {"order": 最終の候補の点の順, "ends": 縮めた終わり}(採用の規則の pref。pipeline/analyze/adopt)。印が無ければ空"""
    if not FINAL_ON:
        return {}
    cs = [c for c in _cands(analysis) if schemas.is_num(c.get("final"))]
    if not cs:
        return {}
    order = [[c["start"], c["end"]] for c in sorted(cs, key=lambda c: -c["final"])]
    ends = []
    for c in cs:
        if schemas.is_num(c.get("settle")) and not c.get("joined"):
            e = _lb.shrink_end(c, c["settle"], None)
            if e < c["end"] - 0.05:
                ends.append([c["start"], c["end"], round(e, 1)])
    return {"order": order, "ends": ends}


def plan(analysis, duration, top):
    """URL の自動依頼の採用 -> (上限, pref, 印)。印 = {final(並びを替えた), cut(縮める候補の数), low(減らした訳), heat(足す候補があるか)}"""
    pref = final_pref(analysis)
    low = low_why(analysis, duration) if isinstance(top, int) and top >= 2 else None
    heat = heat_spans(analysis)
    if heat:
        pref["extra"] = heat
    note = {"final": bool(pref.get("order")), "cut": len(pref.get("ends") or []), "low": low, "heat": bool(heat)}
    return (top - 1 if low else top), pref, note
