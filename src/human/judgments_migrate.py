# -*- coding: utf-8 -*-
"""今の記録から人の判断だけを人の判断の記録(judgments.jsonl)へ 1 回写す道具(MARKS-3 の S2)。元の記録は読むだけで、消さない・直さない。

  py -3.12 src/human/judgments_migrate.py [--data-dir D] [--apply]

既定は下見(出どころごとに「写す数・重複で飛ばす数・人の判断でないので写さない数」を出すだけ。何も書かない)。
書くのは --apply が付いていて、かつ定数 ENABLED が True のときだけ(既定 False。ユーザーの確認のあとでオンにする)。ENABLED が False のとき
--apply は「スイッチがオフです」と言って何もしない。二度流しても行は増えない(行の key で重複を飛ばす。行の id も key から決める)。
--data-dir は作業データの根(youtube-tools の根。中に app と studio がある)。無ければ ytt/datadir の決まり(YTT_DATA_DIR など)で引く。

読む記録と、人の判断とみなす行:
  feedback      スタジオの feedback.jsonl(と .old)。source が review・kind が live でない・adoptedBy なし。
                adopt は採用、reject と delete は不採用、unadopt と delete_judged は取り消し(of = 同じマークの直前の採否の行)。
                export・manual_add・manual_remove(書き出し・見逃し)は人の採否ではないので写さない
  live          app/live/live_feedback.jsonl の human が true の行。deliver と adopt(手で採用)は採用、reject は不採用
  auto_discard  案件の 採用.json の auto の記録のうち、要らないにした印(discardedAt)があり、日数で片付けた印(expiredAt)が無い物は不採用。
                同じマークの live の不採用の行があれば、それと同じ判断なので飛ばす
  friend        app/logs/friend_feedback.jsonl の reject と made_video(届けたパックのマークごとに 1 行。who friend)
  verdict       app/friend-returns の送り返しの採否 verdicts。keep は採用、reject は不採用、made_video は動画にした。by が auto の
                (友人のアプリが日数で自動で要らないにした)物は人の判断でないので写さない
  answers       確かめるの答え app/check/answers.jsonl の、効いている(戻していない)value の auto の答え。良い悪いを品質の判断に
機械の行(adoptedBy・origin が auto の adopt・export・miss・expiredAt)は写さない。
key の決まりは fb / lf / ad / ff / vd / ans の 6 つ(それぞれの出どころの記録を一意に指す)。ytt と ② の届けた記録(flow/deliveries)・案件の根の引き方
(flow/placement)と ③ の部品(judgments・check/answerlog・friend/returns)だけを読む。
"""
import argparse
import calendar
import collections
import hashlib
import json
import os
import sys
import time

if __package__ in (None, ""):   # 道具として直に動かすとき: 自分のフォルダを外し、src を足す(human/check などの名前が他の import を覆わないように)
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _here]
    sys.path.insert(0, os.path.dirname(_here))

from flow import deliveries as _deliveries, placement as _placement  # noqa: E402
from human import judgments as _judgments  # noqa: E402
from human.check import answerlog as _answerlog  # noqa: E402
from human.friend import returns as _returns  # noqa: E402
from ytt import casefiles as _casefiles, datadir as _datadir, fsio as _fsio  # noqa: E402

ENABLED = True   # 10-16 ユーザーが下見(88 件)を見て「写して」= オン。二度流しても増えない(key)

SOURCES = (("feedback", "スタジオの判定 feedback.jsonl"), ("live", "ライブの届ける・要らない live_feedback.jsonl"),
           ("auto_discard", "案件の要らない(採用.json の auto)"), ("friend", "友人の返事 friend_feedback.jsonl"),
           ("verdict", "送り返しの採否 verdicts"), ("answers", "確かめるの答え answers.jsonl"))
FEEDBACK_WHATS = {"adopt": "adopt", "reject": "reject", "delete": "reject", "unadopt": "retract", "delete_judged": "retract"}
FEEDBACK_MACHINE = ("export", "manual_add", "manual_remove")
_SELF_LANE = ("adopt", "reject")
_AT_MAX = 10 ** 13


def _read_jsonl(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    out = []
    for raw in data.decode("utf-8", "replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _s(v):
    return v if isinstance(v, str) and v else ""


def _ms(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v < _AT_MAX else 0


def _local_ms(ts):
    try:
        return int(time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
    except (ValueError, OverflowError):
        return 0


def _utc_ms(iso):
    s = str(iso or "")
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) * 1000
    except (ValueError, OverflowError):
        return 0


def _span(r):
    return {k: r[k] for k in ("start", "end") if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)}


def dirs(data_dir=None):
    """(スタジオの作業データ, 入口 app の作業データ, 書き出し先)。data_dir があればその下の studio と app"""
    if data_dir:
        studio, app = os.path.join(data_dir, "studio"), os.path.join(data_dir, "app")
        st = _fsio.read_json_or(os.path.join(studio, "settings.json"), None, kind=dict)
        out = st.get("outDir") if st else None
        return studio, app, out if isinstance(out, str) and out and os.path.isabs(out) else os.path.join(studio, "exports")
    return _datadir.resolve("studio"), _datadir.resolve("app"), _datadir.studio_out_dir()


class _Plan:
    def __init__(self):
        self.rows = []   # 写す候補(読んだ順)。辞書 = judgments.record に渡す欄 + src
        self.skip = {k: collections.Counter() for k, _ in SOURCES}   # 出どころ -> {写さない理由: 数}
        self.dup = collections.Counter()

    def add(self, src, **row):
        row.setdefault("via", "migrate")
        row["src"] = src
        self.rows.append(row)

    def no(self, src, why):
        self.skip[src][why] += 1


def _feedback(plan, studio):
    p = os.path.join(studio, "feedback.jsonl")
    for r in _read_jsonl(p + ".old") + _read_jsonl(p):
        ev = r.get("event")
        if r.get("source") != "review" or r.get("kind") == "live":
            plan.no("feedback", "人の確認画面の行でない(録画・別の出どころ)")
        elif r.get("adoptedBy"):
            plan.no("feedback", "機械の採用(adoptedBy)")
        elif ev in FEEDBACK_MACHINE:
            plan.no("feedback", "書き出し・見逃しの行(%s)" % ev)
        elif ev not in FEEDBACK_WHATS:
            plan.no("feedback", "知らない event")
        elif not (_s(r.get("videoId")) and _s(r.get("markId"))):
            plan.no("feedback", "配信かマークが分からない")
        elif not _local_ms(r.get("ts")):
            plan.no("feedback", "時刻が読めない")
        else:
            plan.add("feedback", at=_local_ms(r["ts"]), who="self", videoId=r["videoId"], markId=r["markId"], what=FEEDBACK_WHATS[ev],
                     origin="manual" if r.get("src") == "manual" else "auto", key="fb:%s:%s:%s:%s" % (r["ts"], r["videoId"], r["markId"], ev), **_span(r))


def _live(plan, app):
    p = os.path.join(app, "live", "live_feedback.jsonl")
    seen = set()
    for r in _read_jsonl(p + ".old") + _read_jsonl(p):
        ev = r.get("event")
        if ev not in ("deliver", "reject", "adopt"):
            plan.no("live", "検出の比べなど(%s)" % (ev or "event なし"))
            continue
        if r.get("human") is not True:
            plan.no("live", "機械の行(human でない)")
            continue
        st = r.get("studio") if isinstance(r.get("studio"), dict) else {}
        vid, mid = _s(st.get("video")), _s(st.get("mark"))
        at = _utc_ms(r.get("at"))
        if not (vid and mid):
            plan.no("live", "スタジオの配信かマークが分からない")
        elif not at:
            plan.no("live", "時刻が読めない")
        else:
            what = "reject" if ev == "reject" else "adopt"
            if what == "reject":
                seen.add((vid, mid))
            plan.add("live", at=at, who="self", videoId=vid, markId=mid, what=what, origin="live",
                     key="lf:%s:%s:%s:%s" % (r.get("at"), _s(r.get("recording")) or vid, mid, ev), ref={"recorder": r.get("recorder"), "recording": r.get("recording")},
                     **_span(r))
    return seen


def _auto_discard(plan, app, out_dir, live_rejects):
    # 案件の「要らない」は MARKS-3 から judgments に直に書く(via cases の reject・key lf:)= 同じ切り抜きの discardedAt は写さない(重複に数える)
    cases_rejects = {(r["videoId"], r["markId"]) for r in _judgments.rows(app) if r.get("via") == "cases" and r["what"] == "reject"}
    for root in _placement.case_roots(out_dir):
        try:
            case = _placement.read_case(root)
            adopts, _there = _casefiles.read_doc(_casefiles.work_path(root, _casefiles.ADOPTIONS_NAME), _casefiles.parse_adoptions)
        except Exception:   # 読めない案件は飛ばす(元は読むだけ)
            continue
        if not adopts or not isinstance(adopts.get("auto"), dict):
            continue
        vid = (case or {}).get("id") or next(iter(adopts.get("sources") or {}), "")
        for mid, rec in sorted(adopts["auto"].items()):
            at = _ms(rec.get("discardedAt"))
            if not at:
                continue
            if _ms(rec.get("expiredAt")):
                plan.no("auto_discard", "日数で片付けた(expiredAt)")
            elif not vid:
                plan.no("auto_discard", "配信が分からない")
            elif (vid, mid) in live_rejects or (vid, mid) in cases_rejects:
                plan.dup["auto_discard"] += 1   # live の不採用・案件が書いた不採用と同じ判断(二重を 1 つに)
            else:
                plan.add("auto_discard", at=at, who="self", videoId=vid, markId=mid, what="reject",
                         origin="auto" if rec.get("origin") == "full" else "live", key="ad:%s:%s:%s" % (vid, mid, at))


def _delivery_index(app):
    rows = _deliveries.rows(os.path.join(app, "logs")) or []
    by_zip, by_req = {}, collections.defaultdict(list)
    for d in rows:
        if _s(d.get("zip")):
            by_zip[d["zip"]] = d
        if _s(d.get("requestId")):
            by_req[d["requestId"]].append(d)
    return by_zip, by_req


def _pack_name(p):
    return os.path.basename(str(p.get("dir") or "").rstrip("/\\")) if isinstance(p, dict) else ""


def _friend(plan, app, by_zip):
    for r in _read_jsonl(os.path.join(app, "logs", "friend_feedback.jsonl")):
        what = r.get("verdict")
        at = _ms(r.get("at"))
        if what not in ("reject", "made_video"):
            plan.no("friend", "知らない判定")
            continue
        d = by_zip.get(r.get("zip")) or {}
        vid = _s(r.get("videoId")) or _s(d.get("videoId"))
        origin = r.get("origin") if r.get("origin") in ("request", "auto") else (_deliveries.origin_of(d) if d else "request")
        packs = [p for p in r.get("packs") or [] if isinstance(p, dict)]
        if not at or not packs:
            plan.no("friend", "時刻かパックが分からない")
            continue
        for p in packs:
            mid, pack = _s(p.get("markId")), _pack_name(p)
            if not (mid and vid) and not pack:
                plan.no("friend", "パックのマークも名前も分からない")
                continue
            # マークの分からない古い行は書き手(friend_feedback)と同じく配信・マークを空にしてパック名で残す(key の末尾もパック名)
            plan.add("friend", at=at, who="friend", videoId=vid if mid and vid else "", markId=mid if mid and vid else "", what=what, origin=origin,
                     key="ff:%s:%s:%s" % (at, r.get("zip"), mid if mid and vid else pack),
                     ref={"zip": r.get("zip"), "pack": _pack_name(p), "requestId": r.get("requestId"), "runId": r.get("runId")})


def _verdict(plan, app, by_req):
    base = _returns.returns_dir(app)
    if not os.path.isdir(base):
        return
    found = []
    for mo in sorted(os.listdir(base)):
        mp = os.path.join(base, mo)
        for rid in sorted(os.listdir(mp)) if os.path.isdir(mp) else ():
            vd = os.path.join(mp, rid, "verdicts")
            for n in sorted(os.listdir(vd)) if os.path.isdir(vd) else ():
                if n.endswith(_returns.VERDICT_SUFFIX):
                    found.append((os.path.join(vd, n), n, rid))
    for path, n, folder_rid in found:
        # 受け取った後の置き場所は <依頼 id>\verdicts\<パック>.verdict.json(送る前の <依頼 id>__<パック> の形でない)。
        # 依頼 id はフォルダ・パック名は中身(無ければファイル名)から。古い形の名前も読める
        m = _returns.VERDICT_RE.match(n)
        v = _fsio.read_json_or(path, None, kind=dict)
        if not v or v.get("verdict") not in _returns.VERDICTS:
            plan.no("verdict", "形が違う")
            continue
        if v.get("by") == "auto":
            plan.no("verdict", "友人のアプリが自動で要らないにした(by auto)")
            continue
        rid = _s(v.get("requestId")) or (m.group(1) if m else folder_rid)
        pack = _s(v.get("pack")) or (m.group(2) if m else n[:-len(_returns.VERDICT_SUFFIX)])
        d = next((x for x in by_req.get(rid, []) for p in x.get("packs") or [] if _pack_name(p) == pack), None)
        d = d or (by_req.get(rid) or [None])[-1] or {}
        hit = next((p for p in d.get("packs") or [] if _pack_name(p) == pack), None)
        vid = _s(d.get("videoId"))
        mid = _s((hit or {}).get("markId"))
        at = _ms(v.get("at"))
        try:
            when = at or int(os.path.getmtime(path) * 1000)
        except OSError:
            when = 0
        if not when:
            plan.no("verdict", "時刻が分からない")
            continue
        if not (mid and vid):
            vid, mid = "", ""   # 書き手(returns)と同じく配信・マークを空にしてパック名で残す
        origin = v.get("origin") if v.get("origin") in ("request", "auto") else (_deliveries.origin_of(d) if d else "request")
        what = {"keep": "adopt"}.get(v["verdict"], v["verdict"])
        plan.add("verdict", at=when, who="friend", videoId=vid, markId=mid, what=what, origin=origin, key="vd:%s:%s:%s" % (rid, pack, at),
                 ref={"requestId": rid, "pack": pack, "zip": d.get("zip"), "runId": d.get("runId")})


def _answers(plan, app):
    for r in _answerlog.state(app).effective():
        if r.get("kind") != "value" or r.get("source") != "auto":
            plan.no("answers", "品質の答えでない(%s:%s)" % (r.get("kind"), r.get("source")))
            continue
        ans = r.get("answer") if isinstance(r.get("answer"), dict) else {}
        ap = r.get("applied") if isinstance(r.get("applied"), dict) else {}
        tg = r.get("target") if isinstance(r.get("target"), dict) else {}
        if _s(ap.get("judgment")):
            plan.dup["answers"] += 1   # 書き手がもう judgments に書いた答え(applied.judgment がある)= 既に記録済み
            continue
        vid, mid = _s(ap.get("videoId")) or _s(tg.get("videoId")), _s(ap.get("markId")) or _s(tg.get("markId"))
        if ans.get("choice") not in ("good", "bad") or not (vid and mid) or not _ms(r.get("at")):
            plan.no("answers", "答え・切り抜き・時刻が読めない")
            continue
        extra = {"reason": ans["reason"]} if ans["choice"] == "bad" and _s(ans.get("reason")) else {}
        plan.add("answers", at=_ms(r["at"]), who="self", videoId=vid, markId=mid, what="quality_" + ans["choice"], origin="auto", key="ans:" + r["id"], **extra)


def _row_id(at, key):
    return "j%013d-%s" % (at, hashlib.sha1(key.encode("utf-8")).hexdigest()[:6])


def build(data_dir=None):
    """読んで写す行を決める(何も書かない)。-> {"rows": 書く行(古い順。record に渡せる欄だけ)、"stats": {出どころ: {copy, dup, skip: {理由: 数}}}、"paths"}"""
    studio, app, out_dir = dirs(data_dir)
    plan = _Plan()
    by_zip, by_req = _delivery_index(app)
    _feedback(plan, studio)
    live_rejects = _live(plan, app)
    _auto_discard(plan, app, out_dir, live_rejects)
    _friend(plan, app, by_zip)
    _verdict(plan, app, by_req)
    _answers(plan, app)
    cands = sorted(plan.rows, key=lambda r: r["at"])   # 安定(同じ時刻は読んだ順)
    last, resolved = {}, []
    for r in cands:   # 取り消しの of = 同じマークの直前の採否の行
        r["id"] = _row_id(r["at"], r["key"])
        if r["what"] == "retract":
            r["of"] = last.get((r["videoId"], r["markId"]))
            if r["of"] is None:
                plan.no(r["src"], "取り消す採否の行が見つからない")
                continue
        elif r["who"] == "self" and r["what"] in _SELF_LANE:
            last[(r["videoId"], r["markId"])] = r["id"]
        resolved.append(r)
    have = _judgments.keys(app)
    out, stats = [], {}
    for r in resolved:
        if r["key"] in have:
            plan.dup[r["src"]] += 1
        else:
            have.add(r["key"])
            out.append(r)
    for k, _label in SOURCES:
        stats[k] = {"copy": sum(1 for r in out if r["src"] == k), "dup": plan.dup[k], "skip": dict(plan.skip[k])}
    return {"rows": [{a: b for a, b in r.items() if a != "src"} for r in out], "stats": stats, "paths": {"studio": studio, "app": app, "outDir": out_dir}}


def apply(data_dir=None, enabled=None):
    """build して書く。ENABLED(または enabled)が False なら何も書かず {"written": 0, "off": True}。-> build の結果 + written"""
    got = build(data_dir)
    if not (ENABLED if enabled is None else enabled):
        return dict(got, written=0, off=True)
    n = 0
    for r in got["rows"]:
        _judgments.record(got["paths"]["app"], **r)
        n += 1
    return dict(got, written=n, off=False)


def report(got):
    lines = ["作業データ: studio = %s / app = %s" % (got["paths"]["studio"], got["paths"]["app"])]
    tc = td = ts = 0
    for k, label in SOURCES:
        s = got["stats"][k]
        sk = sum(s["skip"].values())
        tc, td, ts = tc + s["copy"], td + s["dup"], ts + sk
        lines.append("%-12s 写す %d / 重複で飛ばす %d / 人の判断でないので写さない %d  (%s)" % (k, s["copy"], s["dup"], sk, label))
        for why, n in sorted(s["skip"].items(), key=lambda x: -x[1]):
            lines.append("    写さない: %s %d" % (why, n))
    lines.append("合計        写す %d / 重複で飛ばす %d / 写さない %d" % (tc, td, ts))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="今の記録から人の判断だけを judgments.jsonl へ 1 回写す(既定は下見)")
    ap.add_argument("--data-dir", default=None, help="作業データの根(中に app と studio)。無ければ ytt/datadir の決まり")
    ap.add_argument("--apply", action="store_true", help="書く(定数 ENABLED が True のときだけ)")
    a = ap.parse_args(argv)
    if a.apply and not ENABLED:
        print("スイッチがオフです(ENABLED = False)。何も書きません。下見だけ出します。")
        a.apply = False
    got = apply(a.data_dir, enabled=True) if a.apply else build(a.data_dir)
    print(report(got))
    if a.apply:
        print("書いた行: %d" % got["written"])
    else:
        print("下見です。何も書いていません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
