# -*- coding: utf-8 -*-
"""友人の玄関のライブの依頼の欄と結びつき(notes:docs/design/friend-history.md の 7 章、docs/spec/friend.md の 2-15)。軽い部品だけ(画面を先に出すため)。

- 6 つの設定の範囲・既定・読み直し(clean_settings)は flow/live_rules.py(この PC の受付 human/friend/live_requests.py と 1 つ)。
  ここに残すのは送る欄の検査 check_settings(画面に出す文つき)と記録の 1 行の言葉
- 友人の依頼と録画の結びつきは ② flow/live_rules.RequestBook(ユーザーの PC の入口と 1 つ。友人の PC は届けない = deliver=False。
  録画中の設定の差し替え update = C-2-11)。置き場所は STORE_DIR の REQUESTS_NAME
② のライブ係 FriendLive は friendapp/live_session.py(flow/livesession を読む重い部品)。
"""
import os

from flow.live_rules import KEEP_DAYS, LENGTH, MAX_ITEMS, RANGES, SENS, SETTINGS_DEFAULT, TEXT_MAX, clean_settings, num_in as _num_in, settings_text  # noqa: F401

SENS_LABELS = {"high": "高い", "normal": "ふつう", "low": "低い"}
STORE_DIR = os.path.join("app", "live")
REQUESTS_NAME = "requests.json"
REC_FOLDER = "ライブの録画"         # 一時保管の中の録画の置き場所(7 章)


def check_settings(v):
    """送る欄のライブの 6 つの設定 -> 整えた設定。範囲の外・形の違う値は ValueError(画面にそのまま出す文)"""
    if not isinstance(v, dict):
        raise ValueError("ライブの設定が正しくありません")
    if v.get("sens") not in SENS:
        raise ValueError("感度は 高い・ふつう・低い のどれかにしてください")
    out = {"sens": v["sens"]}
    for key, what, unit in (("perHour", "1 時間の枠", "本"), ("length", "長さ", "秒"), ("waitMin", "待ち", "分")):
        x = v.get(key)
        lo, hi = RANGES[key]
        if not (isinstance(x, int) and not isinstance(x, bool) and lo <= x <= hi):
            raise ValueError("%sは %d〜%d %s にしてください" % (what, lo, hi, unit))
        out[key] = x
    if not _num_in(v.get("pad"), *RANGES["pad"]):
        raise ValueError("余白は 0〜5 秒にしてください")
    out["pad"] = float(v["pad"])
    if not isinstance(v.get("afterStream"), bool):
        raise ValueError("配信後の追加はオンかオフにしてください")
    out["afterStream"] = v["afterStream"]
    return out


def settings_label(s):
    """記録に出す 1 行"""
    return settings_text(s, SENS_LABELS)
