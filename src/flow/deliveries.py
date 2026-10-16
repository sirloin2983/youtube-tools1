# -*- coding: utf-8 -*-
"""② 管理の層 flow: 友人へ届けた記録(入口の作業データの logs/deliveries.jsonl)の読み口(OPT-M2。notes:plan/opt-manage.md の 7x-2)。

データの持ち主は ②(届けた = 起きた事実は起こした層。決定 3-48 の「切り抜きの印を 3 本に」)。④ の片付けは記録のファイルを直に読まず、
ここの delivered_requests だけを読む。書く口 record は D-SEND の段 1 でここへ寄せた(③ human/friend/friend_feedback.record_delivery は
ここへ渡すだけの薄い転送)。行の鍵 origin(request・auto・manual。flow/sendpolicy.ORIGINS)と endedAt(配信が終わった時刻。ミリ秒。分からなければ 0)は
D-SEND から。無い古い行は、依頼の id があれば request・無ければ auto として読む。既存の読み手は知らない鍵を無視する。
ファイルの名前は書く側と同じ(テストが一致を見張る)。
"""
import json
import os
import time

from ytt import fsio

LOG = "deliveries.jsonl"        # 届けた記録(入口の作業データの logs の中)
MAX_SCAN = 4 * 1024 * 1024      # 末尾から読む上限


def record(log_dir, zip_path, run, packs, marks=None, origin="request", ended_at=None):
    """zip を 出力\\ に置いたことを 1 行足す(あとで友人の「要らない」が来たときに中身を引くため・配信ごとの届けた時刻を引くため)。
    書けなくても届けるのは止めない。ended_at = 配信が終わった時刻(秒。分からなければ None = 0)。-> 書いた行(dict)"""
    marks = marks or {}
    end = int(ended_at * 1000) if isinstance(ended_at, (int, float)) and not isinstance(ended_at, bool) and ended_at > 0 else 0
    row = {"at": int(time.time() * 1000), "zip": os.path.basename(zip_path), "requestId": run.request_id or "", "runId": run.id,
           "videoId": run.video_id or "", "title": run.title or "", "origin": origin, "endedAt": end,
           "packs": [{"dir": d, "path": (marks.get(d) or {}).get("path") or "", "markId": (marks.get(d) or {}).get("markId") or ""} for d in packs]}
    try:
        # 回さない(max_bytes None): find_delivery は今のファイルだけを見るので、回すと届けた記録を引けなくなる
        fsio.append_line(os.path.join(log_dir, LOG), json.dumps(row, ensure_ascii=False) + "\n", None)
    except OSError:
        pass
    return row


def origin_of(row):
    """行の出どころ。origin の鍵が無い古い行は、依頼の id があれば request・無ければ auto"""
    o = row.get("origin")
    if o in ("request", "auto", "manual"):
        return o
    return "request" if row.get("requestId") else "auto"


def delivered_videos(log_dir, origin=None):
    """-> {配信 id: 最後に届けた時刻(秒)}。origin を渡すとその出どころの行だけ(request・auto・manual)。読めなければ None(届けたかが分からない)"""
    got = rows(log_dir)
    if got is None:
        return None
    out = {}
    for d in got:
        vid, at = d.get("videoId"), d.get("at")
        if not isinstance(vid, str) or not vid or (origin is not None and origin_of(d) != origin):
            continue
        sec = at / 1000.0 if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0 else 0.0
        out[vid] = max(out.get(vid, 0.0), sec)
    return out


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
