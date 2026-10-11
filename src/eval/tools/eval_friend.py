#!/usr/bin/env python3
"""友人の PC から送り返された物(app/friend-returns/)を並べて数える最小の道具(F1 の F2。docs/design/f1-build.md の (f1d))。

    py -3.10 src/eval/tools/eval_friend.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(human/friend/returns.iter_requests で依頼ごとの実行・採否を読む)。--json のときだけ evals/friend/<日時>.json に結果を残す
- 依頼ごとに、実行の状態・エンジン / モデル / デバイス(文字起こしの鍵の inputs。無ければ -)と、パックごとの採否を並べる
- 採否 = keep(要る)/ reject(要らない)/ made_video(動画にした = 確実な当たり)/ 不明(押さなかった。答えなくても困らない)
- 注意: 友人の reject はユーザーの基準(70 点)での外れの印にしない(友人は 95 点以上を動画にする。plan/improvements.md の 13)。
  made_video が当たりの印。点数との突き合わせは eval_marks.py の側で(この道具は数えるだけ)
- --since / --until は 実行の時刻(結果の束の at)で絞る(until はその日を含む)
"""
import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(os.path.dirname(HERE))   # tools -> eval -> src
if not __package__:   # スクリプトとして起動したとき(py -3.10 src/eval/tools/eval_friend.py)だけ。src を先頭に・この道具のフォルダは外す
    sys.path[:] = [SRC] + [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.curdir)) not in (os.path.normcase(HERE), os.path.normcase(SRC))]
from eval.tools import _evalcommon as C  # noqa: E402
from human.friend import returns  # noqa: E402
from ytt import fsio  # noqa: E402

SCHEMA = "youtube-tools-friend-eval/v1"
VERDICT_LABELS = {"keep": "要る", "reject": "要らない", "made_video": "動画にした", "unknown": "不明"}


def _device(run_dir):
    """文字起こしの鍵の inputs から (engine, model, device)。無ければ "-"。鍵は run_dir/keys/transcribe/ にある"""
    d = os.path.join(run_dir, "keys", "transcribe")
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return "-", "-", "-"
    for n in names:
        key = fsio.read_json_or(os.path.join(d, n), None, kind=dict)
        inp = key.get("inputs") if isinstance(key, dict) else None
        if isinstance(inp, dict):
            return str(inp.get("engine") or "-"), str(inp.get("model") or "-"), str(inp.get("device") or "-")
    return "-", "-", "-"


def _packs(result):
    out = result.get("packs") if isinstance(result, dict) else None
    return [os.path.basename(str(p).rstrip("/\\")) for p in out] if isinstance(out, list) else []


def evaluate(data_dir=None, since=None, until=None):
    app = C.locate("app", data_dir)
    since_ms, until_ms = C.period(since, until)
    reqs, runs = [], []
    counts = collections.Counter()
    for r in returns.iter_requests(app):
        rr = []
        for run in r["runs"]:
            res = run["result"] if isinstance(run["result"], dict) else {}
            at = res.get("at") or run["manifest"].get("at")
            if not C.in_period(at, since_ms, until_ms):
                continue
            eng, model, dev = _device(run["dir"])
            packs = _packs(res)
            rr.append({"runId": run["runId"], "state": res.get("state") or "?", "engine": eng, "model": model, "device": dev, "packs": packs, "at": at,
                       "trimmed": run["manifest"].get("trimmed") or []})
        if not rr and (since or until):
            continue
        verdicts = r["verdicts"]
        for v in verdicts.values():
            counts[v["verdict"]] += 1
        known = set(verdicts)
        unknown = sum(1 for x in rr for p in x["packs"] if p not in known and not any(k.endswith(p) or p.endswith(k) for k in known))
        counts["unknown"] += unknown
        reqs.append({"requestId": r["requestId"], "month": r["month"], "runs": rr, "verdicts": verdicts, "unknownPacks": unknown})
        runs += rr
    states = collections.Counter(x["state"] for x in runs)
    return {"schema": SCHEMA, "root": app, "since": since, "until": until, "requests": reqs,
            "total": {"requests": len(reqs), "runs": len(runs), "states": dict(states), "verdicts": {k: counts.get(k, 0) for k in list(returns.VERDICTS) + ["unknown"]},
                      "devices": dict(collections.Counter("%s/%s/%s" % (x["engine"], x["model"], x["device"]) for x in runs))}}


def print_report(res):
    t = res["total"]
    print("友人の送り返し: 依頼 %d 件・実行 %d 本 (%s)" % (t["requests"], t["runs"], C.period_label(res["since"], res["until"])))
    if not t["requests"]:
        print("  まだ届いていません(%s)" % os.path.join(res["root"], returns.RETURNS_DIR))
        return
    print("  実行の状態: " + "  ".join("%s %d" % (k, v) for k, v in sorted(t["states"].items())))
    print("  採否: " + "  ".join("%s %d" % (VERDICT_LABELS[k], t["verdicts"][k]) for k in list(returns.VERDICTS) + ["unknown"]))
    print("  エンジン / モデル / デバイス: " + "  ".join("%s %d" % (k, v) for k, v in sorted(t["devices"].items())))
    print()
    print("  %-8s %-24s %-9s %-24s %s" % ("月", "依頼", "状態", "エンジン / モデル / デバイス", "パックと採否"))
    for r in res["requests"]:
        for x in r["runs"] or [None]:
            if x is None:
                print("  %-8s %-24s (実行なし)" % (r["month"], r["requestId"]))
                continue
            vs = ", ".join("%s=%s" % (p[:20], VERDICT_LABELS.get((r["verdicts"].get(p) or {}).get("verdict", "unknown"))) for p in x["packs"]) or "-"
            print("  %-8s %-24s %-9s %-24s %s" % (r["month"], r["requestId"][:24], x["state"], "%s/%s/%s" % (x["engine"], x["model"], x["device"]), vs))


def main(argv=None):
    p = argparse.ArgumentParser(description="友人の送り返し(app/friend-returns)を並べて数える(作業データは読むだけ)")
    C.add_period_args(p, "この日(YYYY-MM-DD)以後だけ(実行の時刻)")
    args = p.parse_args(argv)
    C.utf8_stdout()
    res = evaluate(args.data_dir, args.since, args.until)
    print_report(res)
    C.report_saved(res, args.json, res["root"], "friend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
