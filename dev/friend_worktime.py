#!/usr/bin/env python3
"""友人の作業の時刻の集計(新機能 D・10-23。資料の git:before-1028-cleanup:plan/人の作業なしの候補-1023.md の D)。ユーザーの PC で流す。作業データは読むだけ。

    py -3.12 dev/friend_worktime.py [--days 14] [--json]

材料(どれも今ある記録。友人の画面の操作の中身・個人の情報は入っていない):
  - 友人の判断の記録(送り返しの受け取り = app/friend-returns/<月>/<依頼 id>/verdicts/*.verdict.json。human/friend/returns が並べる)
    judge(good = 使う・unknown = 見送り・bad = 届かなくてよかった・retract = 取り消し)・at(決めた時刻)・arrivedAt(届いた)・openedAt(初めて再生した。0.99.150 から)
  - 届けた記録(app/logs/deliveries.jsonl)= ユーザーの PC が届けた時刻(友人のアプリが arrivedAt を送らない古い判断の代わり)
  - パックの配信者(cut2resolve/packs/*.json の streamer・友人の PC の分は friend-returns/<月>/<依頼 id>/<実行 id>/run.json の input.streamer)
  - 公開したショート(analytics/raw/ のいちばん新しい物。published・title)
出す物:
  - 届いてから再生まで・決めるまでの時間(中央値)
  - 使われなかったパックの割合 = 見送り + 届かなくてよかった(+ 届いてから 3 日決めていない)÷ 届いた
  - 届いてから公開までの時間(使うに決めたパックと、題名に同じ配信者の名前があり 0〜14 日後に公開したショートを結ぶ。
    1 本のショートに当たる配信者が 1 人のときだけ・いちばん近いパック = plan/auto-cut-research-1022/m1.py と同じ結び方)
  - 週ごとの本数(2 週間で数がそろうかを見る)
"""
import argparse
import collections
import glob
import json
import os
import statistics
import sys
import time

DAY = 86400.0
UNDECIDED_DAYS = 3        # 届いてからこの日数決めていなければ「使われなかった」に数える(友人のアプリの自動の見送りと同じ)
PUBLISH_DAYS = 14         # 届いてからこの日数までの公開を結ぶ


def data_root():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "youtube-tools")


def _json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def verdicts(root):
    """判断の記録 -> {(依頼 id, パック名): {"judge", "at", "arrivedAt", "openedAt", "videoId", "origin"}}(取り消しは消す・同じパックは新しい方)"""
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "app", "friend-returns", "*", "*", "verdicts", "*.verdict.json"))):
        d = _json(p)
        if not isinstance(d, dict) or not d.get("pack"):
            continue
        key = str(d.get("zip") or "") or (str(d.get("requestId") or ""), str(d["pack"]))   # 届けた zip の名前(友人の PC で作った物は依頼 id とパック名)
        if d.get("judge") == "retract":
            if key in out and out[key].get("id") == d.get("of"):
                del out[key]
            continue
        if key not in out or (d.get("at") or 0) >= (out[key].get("at") or 0):
            out[key] = d
    return out


def delivered(root):
    """届けた記録 -> {zip の名前: {"at", "dir", "videoId"}}"""
    out = {}
    p = os.path.join(root, "app", "logs", "deliveries.jsonl")
    try:
        lines = open(p, encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        for k in r.get("packs") or []:
            d = k.get("dir") or "" if isinstance(k, dict) else ""
            if d and r.get("zip"):
                out[str(r["zip"])] = {"at": r.get("at"), "dir": d, "videoId": r.get("videoId") or ""}
    return out


def streamers(root):
    """配信者 -> パックのフォルダの名前・依頼 id から引く表 (by_dir, by_request)"""
    by_dir, by_req = {}, {}
    for p in glob.glob(os.path.join(root, "cut2resolve", "packs", "*.json")):
        d = _json(p)
        if isinstance(d, dict) and d.get("streamer") and d.get("dir"):
            by_dir[os.path.normcase(os.path.normpath(d["dir"]))] = d["streamer"]
    for p in glob.glob(os.path.join(root, "app", "friend-returns", "*", "*", "*", "run.json")):
        d = _json(p)
        who = ((d or {}).get("input") or {}).get("streamer") if isinstance(d, dict) else None
        if who:
            by_req[os.path.basename(os.path.dirname(os.path.dirname(p)))] = who
    return by_dir, by_req


def shorts(root):
    """公開したショート [(公開の時刻 秒, 題名)](analytics/raw のいちばん新しい物)"""
    raws = sorted(glob.glob(os.path.join(root, "analytics", "raw", "**", "*.json"), recursive=True), key=os.path.getmtime)
    d = _json(raws[-1]) if raws else None
    out = []
    for v in (d or {}).get("videos") or []:
        if not v.get("short"):
            continue
        try:
            out.append((time.mktime(time.strptime(str(v["published"])[:19], "%Y-%m-%dT%H:%M:%S")), str(v.get("title") or "")))
        except (KeyError, ValueError, OverflowError):
            continue
    return out


def collect(root, days=14, now=None):
    now = now or time.time()
    since = now - days * DAY
    vs, dl = verdicts(root), delivered(root)
    first = min(((v.get("at") or 0) / 1000.0 for v in vs.values() if v.get("at")), default=now)
    since = max(since, first - UNDECIDED_DAYS * DAY)   # 友人のアプリが判断を返す前に届いた物は「決めていない」に数えない
    by_dir, by_req = streamers(root)
    packs = []
    for key in set(vs) | set(dl):
        v, d = vs.get(key, {}), dl.get(key, {})
        arrived = (v.get("arrivedAt") or d.get("at") or 0) / 1000.0
        if not arrived or arrived < since:
            continue
        who = by_dir.get(os.path.normcase(os.path.normpath(d["dir"]))) if d.get("dir") else None
        packs.append({"key": key, "arrived": arrived, "opened": (v.get("openedAt") or 0) / 1000.0 or None, "decided": (v.get("at") or 0) / 1000.0 or None,
                      "judge": v.get("judge"), "streamer": who or by_req.get(str(v.get("requestId") or "")), "auto": v.get("by") == "auto"})
    # 公開と結ぶ(使うに決めたパック)
    used = [p for p in packs if p["judge"] == "good" and p["streamer"]]
    pub = []
    for t, title in shorts(root):
        hits = [p for p in used if p["streamer"] in title and 0 <= t - p["arrived"] <= PUBLISH_DAYS * DAY]
        if hits and len({p["streamer"] for p in hits}) == 1:
            p = min(hits, key=lambda p: t - p["arrived"])
            pub.append(t - p["arrived"])
    n = len(packs)
    undecided_old = sum(1 for p in packs if not p["judge"] and now - p["arrived"] > UNDECIDED_DAYS * DAY)
    unused = sum(1 for p in packs if p["judge"] in ("unknown", "bad")) + undecided_old
    med = lambda xs: round(statistics.median(xs) / 3600.0, 1) if xs else None
    weeks = collections.Counter(time.strftime("%Y-W%W", time.localtime(p["arrived"])) for p in packs)
    return {"days": days, "arrived": n, "decided": sum(1 for p in packs if p["judge"]),
            "judges": dict(collections.Counter(p["judge"] or "未定" for p in packs)), "autoSkip": sum(1 for p in packs if p["auto"]),
            "unusedRate": round(unused / n, 3) if n else None, "unused": unused, "undecidedOld": undecided_old,
            "unusedOfDecided": round(sum(1 for p in packs if p["judge"] in ("unknown", "bad")) / dec, 3) if (dec := sum(1 for p in packs if p["judge"])) else None,
            "toOpenHours": med([p["opened"] - p["arrived"] for p in packs if p["opened"]]), "opened": sum(1 for p in packs if p["opened"]),
            "toDecideHours": med([p["decided"] - p["arrived"] for p in packs if p["decided"] and not p["auto"]]),
            "toPublishHours": med(pub), "published": len(pub), "weeks": dict(sorted(weeks.items()))}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=14, help="届いた日がこの日数以内のパック(既定 14)")
    ap.add_argument("--root", default=None, help="作業データの親(既定 %%LOCALAPPDATA%%\\youtube-tools)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = collect(a.root or data_root(), a.days)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print("友人の作業の時刻(届いた日が %d 日以内)" % r["days"])
    print("  届いた %d 本・決めた %d 本 %s(うち 3 日の自動の見送り %d)" % (r["arrived"], r["decided"], r["judges"], r["autoSkip"]))
    pc = lambda x: "-" if x is None else "%.0f%%" % (100 * x)
    print("  使われなかった割合 %s(見送り・届かなくてよかった・3 日決めていない %d 本)・決めた物の中だけなら %s" % (pc(r["unusedRate"]), r["unused"], pc(r["unusedOfDecided"])))
    print("  届いてから再生まで 中央値 %s 時間(再生の記録 %d 本・0.99.150 から)・決めるまで %s 時間" % (r["toOpenHours"], r["opened"], r["toDecideHours"]))
    print("  届いてから公開まで 中央値 %s 時間(結べた %d 本)" % (r["toPublishHours"], r["published"]))
    print("  週ごとの届いた本数 %s" % r["weeks"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
