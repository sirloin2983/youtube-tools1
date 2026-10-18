# -*- coding: utf-8 -*-
"""友人のライブ配信の依頼の設定の決まり(notes:docs/spec/friend.md の 2-15)。範囲・既定・読み直しの 1 か所。

読む所は 2 つ: この PC の受付(human/friend/live_requests.py)と友人の玄関(friendapp/live.py)。どちらも結びつきの記録
{"v": 1, "items": {"<録画元>/<録画>": {..., "settings": clean_settings の形, "createdAt"}}} を持ち、② の検出・採用・配信後の追加が読む。
長さの上限 180 秒 = A-5b の仮(ユーザーの PC の自動の切り抜きの上限と同じ)。
長さ「自動(場面ごと)」(友人の玄関の C-2-11)は settings の lengthMode "auto"(無い = 固定の長さ)。検出のワーカーが場面ごとの形で切る(長さは場面が取れないときの長さ)。
軽い部品だけ(友人の玄関が画面を先に出すため。ytt だけを読む)。
"""
from ytt import schemas

SENS = ("high", "normal", "low")
LENGTH = (10, 180)      # 切り抜きの長さの範囲(秒)
SETTINGS_DEFAULT = {"sens": "normal", "perHour": 6, "length": 45, "waitMin": 5, "pad": 2.0, "afterStream": True}
RANGES = {"perHour": (1, 30), "length": LENGTH, "waitMin": (1, 60), "pad": (0.0, 5.0)}
KEEP_DAYS = 3           # 結びつきを残す日数(録画 12 時間 + 配信後の全自動 live_archive.AFTER_MAX_AGE 2 日に足りる)
MAX_ITEMS = 50          # 結びつきの数の上限(多すぎれば古い物から捨てる)
TEXT_MAX = 300          # url・題名を残す長さ


def num_in(v, lo, hi):
    return schemas.is_num(v) and lo <= v <= hi


def clean_settings(v):
    """依頼・記録・前回の値から読んだ設定 -> 検査済みの設定(無い・範囲の外は既定)"""
    v = v if isinstance(v, dict) else {}
    out = dict(SETTINGS_DEFAULT)
    if v.get("sens") in SENS:
        out["sens"] = v["sens"]
    for k in ("perHour", "length", "waitMin"):
        x = v.get(k)
        if num_in(x, *RANGES[k]):
            out[k] = int(round(x))
    if num_in(v.get("pad"), *RANGES["pad"]):
        out["pad"] = float(v["pad"])
    if isinstance(v.get("afterStream"), bool):
        out["afterStream"] = v["afterStream"]
    if v.get("lengthMode") == "auto":
        out["lengthMode"] = "auto"
    return out


def settings_text(s, sens_labels):
    """検査済みの設定 -> 「感度 …・1 時間 … 本・長さ …・待ち … 分・余白 … 秒・配信後の追加 …」(感度の言葉は読む側の画面に合わせて渡す)"""
    size = "長さ 自動(場面ごと)" if s.get("lengthMode") == "auto" else "長さ %d 秒" % s["length"]
    return "感度 %s・1 時間 %d 本・%s・待ち %d 分・余白 %g 秒・配信後の追加 %s" % (
        sens_labels[s["sens"]], s["perHour"], size, s["waitMin"], s["pad"], "あり" if s["afterStream"] else "なし")
