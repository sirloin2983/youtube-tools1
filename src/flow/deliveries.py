# -*- coding: utf-8 -*-
"""② 管理の層 flow: 友人へ届けた記録(入口の作業データの logs/deliveries.jsonl)の読み口(OPT-M2。notes:plan/opt-manage.md の 7x-2)。

データの持ち主は ②(届けた = 起きた事実は起こした層。決定 3-48 の「切り抜きの印を 3 本に」)。④ の片付けは記録のファイルを直に読まず、
ここの delivered_requests だけを読む。書く口(1 行足す)は今は ③ human/friend/friend_feedback.record_delivery にあり、届ける段を ② へ移すとき
(D-SEND)にここへ寄せる。ファイルの名前は書く側と同じ(テストが一致を見張る)。
"""
import json
import os

LOG = "deliveries.jsonl"        # 届けた記録(入口の作業データの logs の中)
MAX_SCAN = 4 * 1024 * 1024      # 末尾から読む上限


def rows(log_dir):
    """届けた記録の行(dict)を古い順に。末尾から MAX_SCAN まで。読めなければ None"""
    p = os.path.join(log_dir, LOG)
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            if size > MAX_SCAN:
                f.seek(size - MAX_SCAN)
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    out = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def delivered_requests(log_dir):
    """-> {依頼 id: 最後に届けた時刻(秒)}。時刻の無い古い行は 0(= ずっと前)。読めなければ None(届けたかが分からない)"""
    got = rows(log_dir)
    if got is None:
        return None
    out = {}
    for d in got:
        rid, at = d.get("requestId"), d.get("at")
        if not isinstance(rid, str) or not rid:
            continue
        sec = at / 1000.0 if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0.0
        out[rid] = max(out.get(rid, 0.0), sec)
    return out
