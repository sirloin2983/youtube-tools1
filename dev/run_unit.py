#!/usr/bin/env python3
"""unittest を層ごと・フォルダごとに流す道具(1 本ずつ別のプロセス)。リポジトリ直下で:

    py -3.12 dev/run_unit.py --only manage            # 層かフォルダで絞る(複数可)
    py -3.12 dev/run_unit.py --only manage/keep       # フォルダでも絞れる(tests/manage/keep・src/manage/keep と書いても同じ)
    py -3.12 dev/run_unit.py --list                   # 流す物の一覧だけ
    py -3.12 dev/run_unit.py -j 2 --failfast          # 並べて流す数・最初の失敗で止める
    py -3.12 dev/run_unit.py                          # 全部

対象: tests/**/test_*.py(e2e_*.py と test_ で始まらない物は流さない)。tests/ の下は src の層の形(tests/flow・tests/pipeline/transcribe)と
      tests/dev・tests/chrome-ext・tests/friend-apps。同じ所の test_*.cjs は `node --test` で流す(node は PATH か Playwright に入っている node.exe。無ければ落ちた扱い)。
同じプロセスに混ぜると名前が重なるテストがあるので、1 本ずつ別のプロセスで流す。
.py は `py -3.12 -m unittest discover -s <フォルダ> -p <ファイル> -t <フォルダ>`(cwd はリポジトリ直下のまま・テストのフォルダが sys.path の先頭)。
例外: tests/dev/test_resolve_pack_contract.py は単独で流す(表示に「単独」と付ける)。
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
from _common import find_node  # noqa: E402

SOLO = {"tests/dev/test_resolve_pack_contract.py"}
SKIP_DIRS = {"__pycache__", "node_modules", "build", "dist", "work", "logs", "fixtures", ".venv"}
TAIL_LINES = 25
SLOWEST = 10
TIMEOUT_SEC = 600   # 1 本の上限(秒)。固まったテスト 1 本で関所が終わらないのを防ぐ(孫ごと止めて落ちた扱い)
PY = [sys.executable]   # この道具を動かした Python(py -3.12)で流す


NODE = find_node()

Unit = namedtuple("Unit", "rel cwd args label")
Result = namedtuple("Result", "unit ok count secs err skipped", defaults=(0,))


def find_files(root):
    """root の下の tests/**/test_*.py・test_*.cjs を、リポジトリ相対の / 区切りでソートして返す。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "tests")):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.startswith("test_") and name.endswith((".py", ".cjs")):
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, root).replace(os.sep, "/"))
    return sorted(found)


def matches(rel, tokens):
    """--only の語(層の名前・manage/keep のようなフォルダ・dev。頭の tests/・src/ は無くてよい)に rel が当たるか。"""
    if not tokens:
        return True
    for tok in tokens:
        t = tok.replace("\\", "/").strip("/")
        for head in ("tests/", "src/"):
            if t.startswith(head):
                t = t[len(head):]
        if t in ("tests", "src", ""):
            return True
        if rel.startswith("tests/" + t + "/"):
            return True
    return False


def build_units(root, only=None):
    """流す物の一覧。単独の物には印を付ける。only で絞る。"""
    units = []
    for rel in find_files(root):
        label = rel + (" (単独)" if rel in SOLO else "")
        if rel.endswith(".py"):
            d, name = rel.rsplit("/", 1)
            args = ["discover", "-s", d, "-p", name, "-t", d]
        else:
            args = [rel]
        units.append(Unit(rel, root, args, label))
    units = [u for u in units if matches(u.rel, only)]
    return sorted(units, key=lambda u: u.rel)


def run_one(unit, timeout=TIMEOUT_SEC):
    """1 本を別のプロセスで流す。結果(成否・テストの数・秒・stderr)を返す。.cjs は node --test(数は「tests N」の行)。
    timeout 秒を過ぎたら孫ごと止めて落ちた扱い"""
    env = dict(os.environ)
    env["YTT_DATA_DIR"] = "inplace"
    env.pop("PYTHONIOENCODING", None)
    cjs = unit.rel.endswith(".cjs")
    if cjs and not NODE:
        return Result(unit, False, 0, 0.0, "node が見つかりません(PATH か Playwright の node.exe)")
    cmd = [NODE, "--test"] + unit.args if cjs else PY + ["-m", "unittest"] + unit.args
    t0 = time.monotonic()
    p = subprocess.Popen(cmd, cwd=unit.cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=tools.no_window_flags())
    timed_out = False
    try:
        out, errb = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        tools.kill_tree(p, wait=10)
        out, errb = p.communicate()
    secs = time.monotonic() - t0
    err = errb.decode("utf-8", errors="replace")
    if timed_out:
        err += "\n時間切れ(%d 秒を過ぎたので止めた)\n" % timeout
    if cjs:
        err = out.decode("utf-8", errors="replace") + err
        m = re.search(r"^(?:ℹ|#) tests (\d+)", err, re.M)
        s = re.search(r"^(?:ℹ|#) skipped (\d+)", err, re.M)
    else:
        m = re.search(r"^Ran (\d+) tests?", err, re.M)
        s = re.search(r"^(?:OK|FAILED) \(.*\bskipped=(\d+)", err, re.M)
    count = int(m.group(1)) if m else 0
    return Result(unit, p.returncode == 0 and not timed_out, count, secs, err, int(s.group(1)) if s else 0)


def report(r):
    mark = "OK  " if r.ok else "FAIL"
    print(f"{mark} {r.unit.label}  {r.count}件  {r.secs:.1f}秒", flush=True)
    if not r.ok:
        for line in r.err.splitlines()[-TAIL_LINES:]:
            print("    " + line, file=sys.stderr)


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def run_all(units, jobs, failfast):
    """jobs 本ずつ並べて流す。failfast なら最初の失敗で残りを取りやめる。"""
    results = []
    # 大きいファイル(だいたい遅い)から先に始める = 最後に遅い 1 本だけが残って待つのを減らす
    order = sorted(units, key=lambda u: -_size(os.path.join(REPO, u.rel)))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = [ex.submit(run_one, u) for u in order]
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
    skipped = sorted((r for r in results if r.skipped), key=lambda r: r.unit.rel)   # 本物の部品が無くて飛んだ通しを埋もれさせない
    print(f"飛ばした {sum(r.skipped for r in skipped)} 件" + ("(" + "・".join(f"{r.unit.rel} {r.skipped}" for r in skipped) + ")" if skipped else ""))


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
