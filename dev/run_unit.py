#!/usr/bin/env python3
"""unittest を層ごと・フォルダごとに流す道具(1 本ずつ別のプロセス)。リポジトリ直下で:

    py -3.10 dev/run_unit.py --only manage            # 層かフォルダで絞る(複数可)
    py -3.10 dev/run_unit.py --only src/manage/keep   # フォルダでも絞れる
    py -3.10 dev/run_unit.py --list                   # 流す物の一覧だけ
    py -3.10 dev/run_unit.py -j 2 --failfast          # 並べて流す数・最初の失敗で止める
    py -3.10 dev/run_unit.py                          # 全部

対象: src/**/tests/test_*.py と dev/tests/test_*.py(e2e_*.py と test_ で始まらない物は流さない)。
同じプロセスに混ぜると名前が重なるテストがあるので、1 本ずつ `py -3.10 -m unittest <ファイル>` を別のプロセスで流す。
例外 1: src/editor/tests/ は 1 本ずつだと test_backend の import で落ちるので、そのフォルダを cwd にして test_metrics を 1 回だけ流す(編集の一式)。
例外 2: dev/tests/test_resolve_pack_contract.py は単独で流す(表示に「単独」と付ける)。
環境: YTT_DATA_DIR=inplace。PYTHONIOENCODING は外す。Windows の子プロセスは窓を出さない(CREATE_NO_WINDOW)。
終了コード: 落ちた物があれば 1。使い方の誤りは 2。
"""
import argparse
import os
import re
import subprocess
import sys
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))   # dev/
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
from layer_map import LAYERS  # noqa: E402
from ytt import tools  # noqa: E402

EDITOR_TESTS = "src/editor/tests"
EDITOR_ENTRY = "test_metrics"
SOLO = {"dev/tests/test_resolve_pack_contract.py"}
SKIP_DIRS = {"__pycache__", "node_modules", "build", "dist", "work", "logs", "fixtures", ".venv"}
TAIL_LINES = 25
SLOWEST = 10
PY = ["py", "-3.10"] if os.name == "nt" else [sys.executable]

Unit = namedtuple("Unit", "rel cwd args label")
Result = namedtuple("Result", "unit ok count secs err")


def find_files(root):
    """root の下の src/**/tests/test_*.py と dev/tests/test_*.py を、リポジトリ相対の / 区切りでソートして返す。"""
    found = []
    for base in ("src", "dev"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, base)):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if os.path.basename(dirpath) != "tests":
                continue
            for name in filenames:
                if name.startswith("test_") and name.endswith(".py"):
                    full = os.path.join(dirpath, name)
                    found.append(os.path.relpath(full, root).replace(os.sep, "/"))
    return sorted(found)


def matches(rel, tokens):
    """--only の語(層の名前・src/manage/keep のようなフォルダ・dev)に rel が当たるか。"""
    if not tokens:
        return True
    for tok in tokens:
        t = tok.replace("\\", "/").strip("/")
        if t == "src":
            prefix = "src/"
        elif t.startswith(("src/", "dev/")) or t == "dev":
            prefix = t + "/"
        else:
            prefix = "src/" + t + "/"
        if rel.startswith(prefix):
            return True
    return False


def build_units(root, only=None):
    """流す物の一覧。editor は 1 つにまとめ、単独の物には印を付ける。only で絞る。"""
    files = find_files(root)
    units = []
    editor_files = [rel for rel in files if rel.startswith(EDITOR_TESTS + "/")]
    for rel in files:
        if rel.startswith(EDITOR_TESTS + "/"):
            continue
        label = rel + (" (単独)" if rel in SOLO else "")
        units.append(Unit(rel, root, [rel], label))
    if editor_files:
        entry = EDITOR_TESTS + "/" + EDITOR_ENTRY + ".py"
        units.append(Unit(entry, os.path.join(root, EDITOR_TESTS), [EDITOR_ENTRY],
                          EDITOR_TESTS + " (編集の一式: " + EDITOR_ENTRY + " を 1 回)"))
    units = [u for u in units if matches(u.rel, only)]
    return sorted(units, key=lambda u: u.rel)


def run_one(unit):
    """1 本を別のプロセスで流す。結果(成否・テストの数・秒・stderr)を返す。"""
    env = dict(os.environ)
    env["YTT_DATA_DIR"] = "inplace"
    env.pop("PYTHONIOENCODING", None)
    cmd = PY + ["-m", "unittest"] + unit.args
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=unit.cwd, env=env, capture_output=True, creationflags=tools.no_window_flags())
    secs = time.monotonic() - t0
    err = p.stderr.decode("utf-8", errors="replace")
    m = re.search(r"^Ran (\d+) tests?", err, re.M)
    count = int(m.group(1)) if m else 0
    return Result(unit, p.returncode == 0, count, secs, err)


def report(r):
    mark = "OK  " if r.ok else "FAIL"
    print(f"{mark} {r.unit.label}  {r.count}件  {r.secs:.1f}秒", flush=True)
    if not r.ok:
        for line in r.err.splitlines()[-TAIL_LINES:]:
            print("    " + line, file=sys.stderr)


def run_all(units, jobs, failfast):
    """jobs 本ずつ並べて流す。failfast なら最初の失敗で残りを取りやめる。"""
    results = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = [ex.submit(run_one, u) for u in units]
        for f in as_completed(futs):
            if f.cancelled():
                continue
            r = f.result()
            results.append(r)
            report(r)
            if failfast and not r.ok:
                for g in futs:
                    g.cancel()
    return results


def print_summary(results, elapsed):
    print("")
    print("遅い順 " + str(SLOWEST) + " 本:")
    for r in sorted(results, key=lambda r: r.secs, reverse=True)[:SLOWEST]:
        print(f"  {r.secs:7.1f}秒  {r.unit.label}")
    failed = [r for r in results if not r.ok]
    total = sum(r.count for r in results)
    print(f"合計 {len(results)} 本(テスト {total} 件)・落ちた {len(failed)} 本・{elapsed:.1f} 秒")


def main(argv=None):
    ap = argparse.ArgumentParser(description="unittest を層ごと・フォルダごとに 1 本ずつ別のプロセスで流す")
    ap.add_argument("--only", nargs="+", metavar="層かフォルダ",
                    help="層(" + " ".join(LAYERS) + ")かフォルダ(src/manage/keep など)。複数可")
    ap.add_argument("--list", action="store_true", help="流す物の一覧だけ出す")
    ap.add_argument("-j", dest="jobs", type=int, default=1, help="並べて流す数(既定 1)")
    ap.add_argument("--failfast", action="store_true", help="最初に落ちたら残りを取りやめる")
    args = ap.parse_args(argv)
    if args.jobs < 1:
        print("-j は 1 以上", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    units = build_units(REPO, args.only)
    if not units:
        print("流す物がありません(--only の語を見直す)", file=sys.stderr)
        return 2
    if args.list:
        for u in units:
            print(u.label)
        print(f"{len(units)} 本")
        return 0
    t0 = time.monotonic()
    results = run_all(units, args.jobs, args.failfast)
    print_summary(results, time.monotonic() - t0)
    return 1 if any(not r.ok for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
