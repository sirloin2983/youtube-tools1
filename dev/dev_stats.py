# -*- coding: utf-8 -*-
"""開発の無駄の見張り(10-25 まとめ役): 日ごとの入口の起動し直しの回数と、コミットのうち作業のコミットの割合を数える(読むだけ)。

    py -3.12 dev/dev_stats.py [--days 7] [--write]

入口: 作業データの app\\logs\\launcher.log・launcher.old.log の「ホームを終了しました」(起動し直し・終了)と「自動で起動し直します」。
コミット: main の題で分ける = 版(dev/land.py の「版を x.y.z に」)・地図(「コードの地図を作り直した」)・取り込み(「を main に入れる」)・作業(それ以外)。
--write: 保管庫の plan/開発の効率-日ごと.md に表を書く(研究の data/m2/progress.md と並べて見る)。
"""
import argparse
import collections
import datetime
import os
import re
import subprocess
import sys

from _common import write_utf8

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "youtube-tools", "app", "logs")
VAULT_PAGE = os.path.join("D:" + os.sep, "Obsidian保管庫", "youtube-tools", "plan", "開発の効率-日ごと.md")
DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} (.*)$")
KINDS = (("版", re.compile(r"\[Claude\] 版を \d+\.\d+\.\d+ に")), ("地図", re.compile(r"コードの地図を作り直した")),
         ("取り込み", re.compile(r"を main に入れる$")))


def restarts(logs_dir=LOGS):
    """{日付: {"stops": 入口の終了の数, "auto": 自動の起動し直しの数}}"""
    out = collections.defaultdict(lambda: {"stops": 0, "auto": 0})
    for name in ("launcher.old.log", "launcher.log"):
        try:
            with open(os.path.join(logs_dir, name), encoding="utf-8", errors="replace") as f:
                for ln in f:
                    m = DAY_RE.match(ln.rstrip("\n"))
                    if not m:
                        continue
                    if m.group(2).startswith("ホームを終了しました"):
                        out[m.group(1)]["stops"] += 1
                    elif m.group(2).startswith("自動で起動し直します"):
                        out[m.group(1)]["auto"] += 1
        except OSError:
            continue
    return out


def commits(days, repo=REPO):
    """{日付: Counter(種類)}(main の直近 days 日)"""
    since = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    r = subprocess.run(["git", "log", "main", "--since", since + " 00:00", "--format=%ad\t%s", "--date=format:%Y-%m-%d"],
                       cwd=repo, stdout=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = collections.defaultdict(collections.Counter)
    for ln in r.stdout.decode("utf-8", "replace").splitlines():
        day, _, subj = ln.partition("\t")
        kind = next((k for k, rx in KINDS if rx.search(subj)), "作業")
        out[day][kind] += 1
    return out


def table(days):
    rs, cs = restarts(), commits(days)
    today = datetime.date.today()
    rows = ["| 日 | 入口の終了(うち自動の起動し直し) | コミット | 作業 | 版 | 地図 | 取り込み | 作業の割合 |", "|---|---|---|---|---|---|---|---|"]
    for i in range(days):
        d = (today - datetime.timedelta(days=i)).isoformat()
        c, r = cs.get(d, collections.Counter()), rs.get(d, {"stops": 0, "auto": 0})
        n = sum(c.values())
        rows.append("| %s | %d(%d) | %d | %d | %d | %d | %d | %s |" % (d, r["stops"], r["auto"], n, c["作業"], c["版"], c["地図"], c["取り込み"],
                                                                 "%d%%" % round(100 * c["作業"] / n) if n else "-"))
    return "\n".join(rows)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="日ごとの入口の起動し直しと、作業のコミットの割合")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--write", action="store_true", help="保管庫の plan/開発の効率-日ごと.md に書く")
    a = ap.parse_args(argv)
    t = table(a.days)
    print(t)
    if a.write:
        write_utf8(VAULT_PAGE, "# 開発の効率(日ごと)\n\n`py -3.12 dev/dev_stats.py --write` が書く(手で直さない)。"
                               "10-25 から地図は 1 日 1 回(dev/land.py)・入口は版が落ち着いて 10 分後に起動し直す。\n\n" + t + "\n")
        print("書いた:", VAULT_PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
