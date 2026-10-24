# -*- coding: utf-8 -*-
"""ホームの「友人の依頼」(10-24。ホームの見直しの 1・5): 受付の記録(human/friend/intake の snapshot の requests)に、
実行の記録(② flow/runqueue のメモリの実行と autorun-runs.jsonl)を結んで、新しい順に 1 行ずつの形にする。

行の札(state): rejected 断った / received 届いた(まだ実行が無い)/ live ライブ(録画に結んだ)/ making 作っている / error 失敗 /
sent 送った(届ける段が済んだ)/ done できた(届ける段の無い実行が済んだ)。
済んだ(done = True): 断った・送った・できた・失敗のうち、受け付けて DONE_DAYS 日たった物(画面は 1 行に畳む)。
案件の画面への道(link): ライブ = 録画の id(c。候補のタブ)・URL = 実行の動画 id(c。候補)・動画ファイル = 実行の文書 id(d。校正)。
ライブの録画は依頼の記録の live(10-24 から書く)か、ライブの依頼の結びつき(flow/live_rules.RequestBook = live/requests.json)を
依頼の id(requestId)・題名と受けた時刻の近さで引く(10-24 より前の依頼。録画が片付いていれば結びつきも無い)。
録画が終わったら(入口が渡す録画中の一覧 active に無い)、案件は動画の id で一覧に載るので、道は録画の id の末の動画 id(c。候補)へ移し、
札は届けた記録(delivered = flow/deliveries.delivered_requests)に依頼の id があれば 送った・無ければ nocand 候補なし(10-24 めらの依頼)。
active が None(ライブがオフ・分からない)なら今までどおり録画中として扱う。
道が無ければ link は None と why(開けない理由)。案件がもう無いかは画面が案件の一覧と照らす(ここは記録だけで決める)。
画面は src/app/ui/home/portal.js の renderFriendReqs・入口の口は GET /api/home/requests(src/app/server.py)
"""
import re

DONE_DAYS = 3
LIMIT = 200   # 返す行の数の上限(受付の記録は intake.KEEP_REQUESTS まで)
LABELS = {"rejected": "断った", "received": "届いた", "live": "ライブ", "making": "作っている", "error": "失敗", "sent": "送った", "done": "できた",
          "nocand": "候補なし"}
ENDED = ("rejected", "error", "sent", "done", "nocand")
REC_VID_RE = re.compile(r"^\d{8}-\d{6}-([A-Za-z0-9_-]{11})$")   # 録画の id = <日付>-<時刻>-<動画 id>(録画の部品の REC_ID_RE と同じ形)


def _state(q, runs):
    if q.get("state") != "accepted":
        return "rejected"
    states = [r.get("state") for r in runs]
    if any(s in ("queued", "running") for s in states):
        return "making"
    if q.get("live") and not runs:
        return "live"
    if not runs:
        return "received"
    if all(s == "error" for s in states) or (any(s == "error" for s in states) and not any(s == "done" for s in states)):
        return "error"
    if any(s == "done" and _delivered(r) for s, r in zip(states, runs)):
        return "sent"
    return "done" if any(s == "done" for s in states) else "making"


def _delivered(run):
    """届ける段(deliver)が済んだ実行か(段の記録 steps の key deliver)"""
    return any(isinstance(s, dict) and s.get("key") == "deliver" and s.get("state") == "done" for s in run.get("steps") or [])


def _book_live(q, book):
    """ライブの依頼の結びつき {"<録画元>/<録画>": {rid, title, createdAt}} から、この依頼の録画 {recorder, recording} か None"""
    best, gap = None, None
    for key, it in (book or {}).items():
        if not isinstance(it, dict) or "/" not in str(key):
            continue
        rc, rec = str(key).split("/", 1)
        if q.get("requestId") and it.get("rid") == q["requestId"]:
            return {"recorder": rc, "recording": rec}
        if it.get("title") and it.get("title") == q.get("title") and isinstance(it.get("createdAt"), (int, float)):
            g = abs(it["createdAt"] * 1000 - (q.get("received") or 0))
            if g <= 6 * 3600 * 1000 and (gap is None or g < gap):
                best, gap = {"recorder": rc, "recording": rec}, g
    return best


def _link(q, runs, book=None, active=None):
    """-> ({c, d, tab} か None, 開けない理由)。active = 録画中の "<録画元>/<録画>" の集まり(None = 分からない = 録画中として扱う)。
    録画が終わったライブは {c: 動画 id, tab, ended: True}"""
    if q.get("state") != "accepted":
        return None, "断った依頼"
    lv = q.get("live") if isinstance(q.get("live"), dict) else (_book_live(q, book) if q.get("kind") == "live" else None)
    if lv and isinstance(lv.get("recording"), str) and lv["recording"]:
        m = REC_VID_RE.match(lv["recording"])
        if active is not None and m and "%s/%s" % (lv.get("recorder") or "", lv["recording"]) not in active:
            return {"c": m.group(1), "tab": "cand", "ended": True}, ""   # 録画が終わった: 案件は動画の id で載る
        return {"c": lv["recording"], "tab": "cand", "live": True}, ""
    for r in runs:
        if isinstance(r.get("videoId"), str) and r["videoId"]:
            return {"c": r["videoId"], "tab": "cand"}, ""
    for r in runs:
        if isinstance(r.get("docId"), str) and r["docId"]:
            return {"d": r["docId"], "tab": "proof"}, ""
    if q.get("kind") == "live":
        return None, "録画の記録が無い(古い依頼)"
    return None, "まだ実行が始まっていない" if not q.get("runIds") else "実行の記録が片付いた"


def rows(requests, runs, now_ms, book=None, active=None, delivered=None):
    """受付の記録(新しい順)と実行の記録 -> [{id, kind, title, streamer, received, state, label, done, link, why, runs: 数}]。
    book = ライブの依頼の結びつき(RequestBook.all())・active = 録画中の "<録画元>/<録画>" の集まりか None・
    delivered = {依頼 id: 届けた時刻}(終わったライブの札)。友人の返事(kind feedback)は依頼ではないので出さない"""
    by_id = {}
    for r in runs or []:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            by_id.setdefault(r["id"], r)   # 先に渡した物(メモリの今の実行)を優先
    out = []
    for q in requests or []:
        if not isinstance(q, dict) or q.get("kind") == "feedback":
            continue
        rr = [by_id[i] for i in q.get("runIds") or [] if i in by_id]
        link, why = _link(q, rr, book, active)
        if link and link.get("ended") and not rr:   # 録画が終わったライブ(実行は無い): 届けた記録で 送った / 候補なし
            st = "sent" if q.get("requestId") and q["requestId"] in (delivered or {}) else "nocand"
        else:
            st = _state(dict(q, live=q.get("live") or (link if link and link.get("live") else None)), rr)
            if st in ("error", "done", "received") and q.get("requestId") and q["requestId"] in (delivered or {}):
                st = "sent"   # 実行は失敗・届ける段なしでも、元の依頼 id で後から届けた(後追い・引き継ぎ・手で届ける。問題 2・10-25)
        rec = q.get("received") if isinstance(q.get("received"), (int, float)) else 0
        out.append({"id": q.get("id") or "", "kind": q.get("kind") or "", "title": q.get("title") or "", "streamer": q.get("streamer") or "",
                    "received": rec, "state": st, "label": LABELS[st], "reason": q.get("reason") or "",
                    "done": st in ENDED and now_ms - rec > DONE_DAYS * 86400000, "link": link, "why": why, "runs": len(rr)})
        if len(out) >= LIMIT:
            break
    return out
