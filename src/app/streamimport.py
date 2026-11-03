# -*- coding: utf-8 -*-
"""出来事の記録(ytt/streamlog。<データの根>\\app\\logs\\streams.jsonl)へ、古い記録から 1 回だけ取り込む(11-03。移し方の段 3。
正 = 資料の plan/情報をまとめる所-1103.md の「決まった形: 配信・依頼・切り抜き」)。

いつ: 入口の起動の少しあと(app/server.py の裏の糸)。記録に kind "import" の行があれば何もしない(1 回だけ)。書くのは入口の 1 プロセス。
どこまで: 記録の最初の行(段 2 の今の書く所が書き始めた時刻)より前の出来事だけ(あとの出来事は今の書く所が書いている = 二重にしない)。
読む物(読むだけ。どれも書き換えない):
  依頼の受付 intake-state.json(受けた・断った)/ ライブの依頼の結びつき live/requests.json(結んだ)/
  録画ごとの記録 live/archive.json(始めた人 = 始めた・終わった)/ ライブの書き出し live/exports.json(済んだジョブ = 採用した・書き出した)/
  届けた logs/deliveries.jsonl・送らなかった logs/not-sent.jsonl / まとめて実行 logs/autorun-runs.jsonl(.1 も)/
  人の判断の記録 judgments.jsonl の友人の判定(via friend_verdict。読むだけ)/ 案件の cases.json の要らない・日数の片付け
印: 元の記録に結びが書いてある物はそのまま。取り込みで推し量った物(時刻を書き出しのジョブから・採用をジョブから)は guess = True。
  受付の記録は最近 KEEP_REQUESTS 件だけ・案件のフォルダの 採用.json の要らないは読まない(足りない分は印 note に書く)。
"""
import datetime
import json
import os
import time

from ytt import fsio, streamlog
from flow import deliveries as _deliveries, runlog as _runlog
from human import judgments as _judgments

INTAKE_STATE = "intake-state.json"   # human/friend/intake.STATE_FILE と同じ(受付を読み込まずに読む)


def _read_json(p):
    try:
        return fsio.read_json_or(p, None, kind=dict)
    except Exception:   # noqa: BLE001
        return None


def _lines(p):
    try:
        with open(p, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _ms(v):
    """数(秒かミリ秒)・ISO の文字 -> ミリ秒か None"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v if v > 1e11 else v * 1000) if v > 0 else None
    if isinstance(v, str) and v:
        try:
            return int(datetime.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def gather(app_dir):
    """古い記録 -> [(ミリ秒, 種類, 配信, 欄)](時刻の分からない物は入れない)"""
    ev = []

    def add(at, kind, stream="", **f):
        at = _ms(at)
        if at:
            ev.append((at, kind, stream or "", f))

    logs, live = os.path.join(app_dir, "logs"), os.path.join(app_dir, "live")
    st = _read_json(os.path.join(app_dir, INTAKE_STATE)) or {}
    for q in st.get("requests") or []:
        if not isinstance(q, dict):
            continue
        lv = q.get("live") if isinstance(q.get("live"), dict) else {}
        add(q.get("received"), "request" if q.get("state") == "accepted" else "request-reject", request=q.get("requestId"),
            recording=lv.get("recording"), recorder=lv.get("recorder"), origin=q.get("kind"), title=q.get("title"), note=q.get("reason"),
            run=",".join(str(x) for x in (q.get("runIds") or [])[:5]), by="friend")
    book = _read_json(os.path.join(live, "requests.json")) or {}
    for key, it in (book.get("items") or {}).items():
        if isinstance(it, dict) and "/" in str(key):
            rc, rec = str(key).split("/", 1)
            add(it.get("createdAt"), "rec-link", request=it.get("rid"), recording=rec, recorder=rc, title=it.get("title"), by="friend")
    arch = _read_json(os.path.join(live, "archive.json")) or {}
    for it in (arch.get("recordings") or {}).values():
        if not isinstance(it, dict):
            continue
        rq = it.get("request") if isinstance(it.get("request"), dict) else {}
        if rq:
            add(rq.get("createdAt"), "rec-start", it.get("videoId"), recording=it.get("recording"), recorder=it.get("recorder"),
                request=rq.get("rid"), by="friend" if rq.get("kind") == "friend" else "self", note="録画ごとの記録の始めた人から")
        add(it.get("endedAt"), "rec-end", it.get("videoId"), recording=it.get("recording"), recorder=it.get("recorder"))
    ex = _read_json(os.path.join(live, "exports.json")) or {}
    for j in ex.get("jobs") or []:
        if not isinstance(j, dict) or j.get("state") != "done":
            continue
        sd = j.get("studio") if isinstance(j.get("studio"), dict) else {}
        rq = j.get("request") if isinstance(j.get("request"), dict) else {}
        span = "%s〜%s" % (j.get("start") or "", j.get("end") or "")
        common = dict(recording=j.get("recording"), recorder=j.get("recorder"), mark=sd.get("mark") or j.get("markId"), origin=j.get("origin"),
                      request=rq.get("rid"))
        add(j.get("created"), "adopt", guess=True, note="書き出しのジョブを作った時刻 " + span, **common)
        add(j.get("updated"), "export", path=j.get("path"), run=j.get("runId"), guess=True, note="ジョブの最後の更新の時刻 " + span, **common)
    for r in _lines(os.path.join(logs, _deliveries.LOG)):
        for p in (r.get("packs") if isinstance(r.get("packs"), list) else None) or [{}]:
            p = p if isinstance(p, dict) else {}
            add(r.get("at"), "deliver", r.get("videoId"), request=r.get("requestId"), run=r.get("runId"), zip=r.get("zip"), mark=p.get("markId"),
                path=p.get("path"), origin=r.get("origin"), title=r.get("title"))
    for r in _lines(os.path.join(logs, _deliveries.NOT_SENT_LOG)):
        add(r.get("at"), "not-sent", r.get("videoId"), mark=r.get("markId"), run=r.get("runId"), note=r.get("code"))
    p = os.path.join(logs, _runlog.RUNS_LOG)
    for r in _lines(p + ".1") + _lines(p):
        f = dict(run=r.get("id"), request=r.get("requestId"), doc=r.get("docId"))
        add(r.get("created"), "run-start", r.get("videoId"), path=r.get("sourcePath"), title=r.get("title"), note="受け付けた時刻", **f)
        add(r.get("finished"), "run-end", r.get("videoId"), state=r.get("state"), note=str(r.get("error") or "")[:200], **f)
    for r in _judgments.rows(app_dir):
        if r.get("via") == "friend_verdict" and r.get("who") == "friend":
            ref = r.get("ref") if isinstance(r.get("ref"), dict) else {}
            add(r.get("at"), "feedback", r.get("videoId"), mark=r.get("markId"), request=ref.get("requestId"), zip=ref.get("zip"),
                state=r.get("what"), by="friend")
    cases = _read_json(os.path.join(app_dir, "cases.json")) or {}
    for cid, s in cases.items():
        auto = (s or {}).get("auto") if isinstance(s, dict) else None
        for mid, a in (auto.items() if isinstance(auto, dict) else ()):
            if isinstance(a, dict):
                exp = a.get("expiredAt")
                add(exp or a.get("discardedAt"), "discard", cid, recording=cid, mark=mid, doc=a.get("tx"), by="auto" if exp else "self",
                    note="日数で片付けた" if exp else "要らない")
    return ev


def run(app_dir, p=None, now=None, log=None):
    """1 回だけ取り込む -> 足した行の数か None(もう取り込んだ・書く所が無い)"""
    p = p or streamlog.path()
    if not p or not app_dir:
        return None
    have = streamlog.rows(p)
    if any(r.get("kind") == "import" for r in have):
        return None
    now_ms = int((time.time() if now is None else now) * 1000)
    cutoff = min([r["at"] for r in have] + [now_ms])
    ev = sorted((e for e in gather(app_dir) if e[0] < cutoff), key=lambda e: e[0])
    n = 0
    for at, kind, stream, f in ev:
        if streamlog.record(kind, stream, now=at / 1000.0, p=p, **f):
            n += 1
    streamlog.record("import", now=now_ms / 1000.0, p=p, note="古い記録から %d 行(%s より前)。受付は最近の分だけ・案件のフォルダの要らないは読んでいない" % (
        n, datetime.datetime.fromtimestamp(cutoff / 1000).strftime("%Y-%m-%d %H:%M")))
    if log:
        log("出来事の記録: 古い記録から %d 行を取り込みました(streams.jsonl。1 回だけ)" % n)
    return n
