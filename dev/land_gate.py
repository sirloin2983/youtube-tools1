#!/usr/bin/env python3
"""main に入れる前の関所(dev/land.py が版を上げる前に流す)。単独でも流せる:

    py -3.12 dev/land_gate.py [<ブランチ>] [--skip-tests] [--skip-checks] [--skip-worklog] [--worklog 名前] [-j 数] [--list]
        # 既定のブランチ = 今のブランチ。--list は選んだテストの一覧だけ(流さない)

流す物(落ちたら止める。e2e は入れない = 一式は今までどおり大きな区切りで dev/run_e2e.py):
  1 検査: dev/lint.py(0 件。規則の見張り dev/rule_checks.py・dev/rule_imports.py もここ)・dev/ui_audit.py static(画面の約束 A-xx の Must 0)・dev/plan_data.py check・dev/notes_tool.py check(保管庫。中身は notes_tool に任せる)・dev/spec_check.py --gone(消した道具の名前が今の正に残っていない)。
    落ちても main の作業フォルダで同じ数以上なら警告だけ(保管庫は 1 つ = ほかのセッションの途中の資料の変更でこの枝が止まらない)
  2 単体テスト: `git diff --name-only main...<ブランチ>` の変えたファイルから、docs/spec/code.md の 6「フォルダと、変えたら通すテスト」の
    行に当たる層を選び、dev/run_unit.py と同じ流し方(1 本ずつ別のプロセス・YTT_DATA_DIR=inplace・窓なし)で並べて流す。
    層を変えたら、その層を import してよい上の層(dev/layer_map.py の ALLOWED)のテストも流す。ytt(基盤)を変えたら全部。
    層のテスト(tests/<層>/)を変えたら、その層を変えたのと同じ。dev/・setup/・tests/dev/ を変えたら tests/dev/ の全部。いつも流す見張り(GUARDS)= 層の向き・YTT_DATA_DIR の切り離し・src に作業データを残さない
    BY_IMPORTS(既定。10-23)= 層の決まりの代わりに、変えたファイルを import(と道・ファイル名の文字列)でたどって使うテストだけ(dev/test_deps.py)。
    たどれないファイル(消した・.py でなく名前がどこにも出ない)はそのファイルだけ層の決まりで選ぶ。--all = 全部(大きな区切り)
  3 報告の型: 入れるセッションの作業の記録(dev/worklog.py check。名前の既定 = ブランチの claude/ と末尾の -16 進を外した物)。
    見出しが欠けたら止める・英字の割合は警告だけ
テストと検査は、ブランチをチェックアウトしている作業フォルダで流す(main と合わせた形ではない。main の新しい分を取り込んでいなければ警告)。
検査(1)は単体テスト(2)と並べて流す。作業フォルダに未コミット・未追跡の物が無いときは、通った単体を木の hash ごとに控え(git の共通ディレクトリの
ytt-gate-cache.json。新しい CACHE_TREES 個の木)、同じ木の流し直しでは通った物を飛ばす(1 バイトでも変われば木が変わる = 全部流す)。前回の秒で遅い順に始める。
表(code.md の 6)と実際のフォルダがずれていたら警告する(止めない)。抜け道は --skip-* の明示だけ = land.py が記録(git の共通ディレクトリの ytt-land.log)に残す。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))   # dev/
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
import run_unit  # noqa: E402
import test_deps  # noqa: E402
import worklog  # noqa: E402
from layer_map import ALLOWED  # noqa: E402
from ytt import layout  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PY = run_unit.PY
ALL = "*"
# 層 → 本体のフォルダ(app は入口と、入口が取り込んだツールのフォルダ)。テストのフォルダは tests/ の下の同じ形(TEST_DIRS)
LAYER_SRC = {"ytt": ["ytt"], "pipeline": ["pipeline"], "flow": ["flow"], "human": ["human"],
             "manage": ["manage"], "eval": ["eval"], "friendapp": ["friendapp"],
             "app": ["app", "studio", "editor", "cut2resolve", "ui-kit"]}
LAYER_DIRS = {k: ["src/%s/" % d for d in v] + ["tests/%s/" % d for d in v] for k, v in LAYER_SRC.items()}
DEV_TESTS = "tests/dev/"
# いつも流す見張り(test_ytt_core の YTT_DATA_DIR の決まり = 層をまたぐ決まり)
GUARDS = ("tests/dev/test_layering.py", "tests/ytt/test_ytt_core.py", "tests/dev/test_no_src_workdata.py")
# 単体テストの道具の外(C#・node・e2e)。変えたら手で流す物を出すだけ
MANUAL = {"friend-apps/holo-colors/": r"friend-apps\holo-colors\build.bat",
          "friend-apps/launcher/": r"friend-apps\launcher\build.bat",
          "friend-apps/common/": r"friend-apps\launcher\build.bat",
          "tests/friend-apps/holo-colors/": r"friend-apps\holo-colors\build.bat",
          "tests/friend-apps/launcher/": r"friend-apps\launcher\build.bat",
          "chrome-ext/yt-studio-time/": "node --test tests/chrome-ext/yt-studio-time/test_main.cjs",
          "tests/chrome-ext/yt-studio-time/": "node --test tests/chrome-ext/yt-studio-time/test_main.cjs"}
# テストの要らない場所(lint・notes_tool が見る)
NO_TESTS = ("codemap/", ".claude/", "README.txt", "AGENTS.md", "CLAUDE.md", ".gitignore", ".gitattributes", "push.bat")
TABLE_HEAD = "## 6. フォルダと、変えたら通すテスト"
BY_IMPORTS = True   # 単体テストを import のつながりで選ぶ(False = 層の決まりだけ = 前のまま。抜けの検査 = py -3.12 dev/test_deps.py --history 200)
TAIL = 12
CACHE_NAME = "ytt-gate-cache.json"   # 通った単体の控え {"trees": {木の hash: [通った本]}, "secs": {本: 前回の秒}}
CACHE_TREES = 20


def layer_of_dir(path):
    for layer, dirs in LAYER_DIRS.items():
        if path.startswith(tuple(dirs)):
            return layer
    return None


def dependents(layer):
    """layer と、layer を import してよい層(ALLOWED)"""
    return {layer} | {m for m, ok in ALLOWED.items() if layer in ok}


def select(paths):
    """変えたファイル → (流すテストのフォルダの集合 か ALL, 手で流す物, 決まりの無いファイル)"""
    dirs, manual, unknown = set(), set(), []
    for p in paths:
        layer = layer_of_dir(p)
        if layer == "ytt":
            return ALL, sorted(manual), unknown
        if layer:
            for d in dependents(layer):
                dirs.update(LAYER_DIRS[d])
        elif p.startswith(("dev/", "setup/", DEV_TESTS)):
            dirs.add(DEV_TESTS)
        elif p.startswith("tests/") and p.count("/") == 1:   # tests/ 直下の共通の下ごしらえ(testkit)= 全部
            return ALL, sorted(manual), unknown
        elif p.startswith(tuple(MANUAL)):
            manual.add(next(v for k, v in MANUAL.items() if p.startswith(k)))
        elif not p.startswith(NO_TESTS) and "/" in p:
            unknown.append(p)
    return dirs, sorted(manual), unknown


def pick_units(root, dirs):
    units = run_unit.build_units(root)
    if dirs == ALL:
        return units
    return [u for u in units if u.rel.startswith(tuple(dirs)) or u.rel in GUARDS]


def pick_by_imports(root, paths):
    """変えたファイル → 単体の一覧(import のつながりで使うテスト + 見張り。たどれないファイルの分は層の決まり)と、層の決まりに戻したファイルの数"""
    units = run_unit.build_units(root)
    sel, unknown = test_deps.Graph(root).select(paths, {u.rel for u in units})
    if unknown:
        dirs, _m, _u = select(unknown)
        sel |= {u.rel for u in pick_units(root, dirs)} if dirs else set()
    return [u for u in units if u.rel in sel or u.rel in GUARDS], len(unknown)


def run_units(units, jobs, log=print, secs=None):
    """並べて流す(前回の秒 secs で遅い順。無い本は先頭)-> 全部の Result の一覧"""
    secs, out = secs or {}, []
    order = sorted(units, key=lambda u: -secs.get(u.rel, 1e9))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for r in ex.map(run_unit.run_one, order):
            out.append(r)
            if not r.ok:
                log("  落ちた: %s(%.0f 秒)" % (r.unit.label, r.secs))
    return out


def cache_path(wt):
    d = git(wt, "rev-parse", "--git-common-dir")[1].strip()
    return os.path.join(wt, d, CACHE_NAME) if d else None


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError, TypeError):
        c = {}
    c = c if isinstance(c, dict) else {}
    return {"trees": c.get("trees") if isinstance(c.get("trees"), dict) else {},
            "secs": c.get("secs") if isinstance(c.get("secs"), dict) else {}}


def save_cache(path, cache, tree, results):
    """通った本を木 tree に足し(tree が空なら秒だけ)、古い木を捨てて書く"""
    for r in results:
        cache["secs"][r.unit.rel] = round(r.secs, 1)
    if tree:
        done = set(cache["trees"].pop(tree, [])) | {r.unit.rel for r in results if r.ok}
        cache["trees"][tree] = sorted(done)
        for old in list(cache["trees"])[:-CACHE_TREES]:
            del cache["trees"][old]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except OSError:
        pass


def count_of(tail):
    """検査の出力の最後の「… N 件」(読めなければ None)"""
    m = re.findall(r"(\d+) 件", tail)
    return int(m[-1]) if m else None


def run_check(wt, main_wt, name, args):
    """検査を流す -> (止める問題, 警告)。落ちても main でも同じ数以上なら警告だけ(保管庫は 1 つなので、
    ほかのセッションの途中の資料の変更で落ちる = この枝のせいではない)"""
    ok, tail = run_tool(wt, args)
    if ok:
        return None, None
    n = count_of(tail)
    if main_wt and n is not None and os.path.normcase(main_wt) != os.path.normcase(wt):
        m = count_of(run_tool(main_wt, args)[1])
        if m is not None and n <= m:
            return None, "%s: %d 件あるが main でも %d 件(保管庫の途中の変更など。この枝のせいではない)" % (name, n, m)
    return "%s が落ちた(py -3.12 %s):\n%s" % (name, " ".join(args), tail), None


def run_tool(root, args, timeout=600):
    """dev の道具を root で流す -> (成否, 出力の最後)"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(PY + args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=NOWIN, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "%d 秒で終わらなかった" % timeout
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    return p.returncode == 0, "\n".join(out[-TAIL:])


def table_folders(code_md):
    """code.md の 6 の表の 1 列目のフォルダ(最初の「(」より前の `…/`)"""
    text = worklog.read(code_md)
    if TABLE_HEAD not in text:
        return None
    sec = text.split(TABLE_HEAD, 1)[1].split("\n## ", 1)[0]
    found = []
    for ln in sec.splitlines():
        if ln.startswith("| ") and not ln.startswith(("| フォルダ", "| ---")):
            first = ln[2:].split(" | ", 1)[0].split("(", 1)[0]
            found += [f for f in re.findall(r"`([^`]+/)`", first)]
    return found


def table_drift(root, code_md):
    """表と実際のフォルダのずれ -> 警告の一覧"""
    folders = table_folders(code_md) if os.path.isfile(code_md) else None
    if folders is None:
        return ["code.md の 6 の表が読めない(%s)" % code_md]
    warns = []
    for f in folders:
        if f in ("docs/", "plan/"):
            continue
        if not os.path.isdir(os.path.join(root, f)):
            warns.append("表の %s は、もう無い(表の行を直す)" % f)
        elif not (layer_of_dir(f) or f.startswith(("dev/", "setup/")) or f.startswith(tuple(MANUAL))):
            warns.append("表の %s に関所の決まりが無い(dev/land_gate.py の LAYER_DIRS・MANUAL に足す)" % f)
    covered = tuple(folders)
    for top in ("src", "friend-apps", "chrome-ext"):
        base = os.path.join(root, top)
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            d = "%s/%s/" % (top, name)
            if os.path.isdir(os.path.join(base, name)) and name != "__pycache__" and not d.startswith(covered) \
                    and d not in ("src/home/",):   # 旧い入口の起動の殻だけ(表は src/app/ の行の「旧 src/home/」)
                warns.append("%s が表に無い(code.md の 6 に行を足す)" % d)
    return warns


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def worktree_of(root, branch):
    """branch をチェックアウトしている作業フォルダ(無ければ None)"""
    path = None
    for ln in git(root, "worktree", "list", "--porcelain")[1].splitlines():
        if ln.startswith("worktree "):
            path = ln[len("worktree "):].strip()
        elif ln.strip() == "branch refs/heads/" + branch:
            return os.path.normpath(path)
    return None


def session_name(branch):
    """claude/land-gate-c990b8 → land-gate(末尾の 16 進は 6 文字以上。worktree-agent-<17 文字> も外す)"""
    name = branch.split("/")[-1]
    return re.sub(r"-[0-9a-f]{6,}$", "", name)


class Gate:
    """関所の結果。problems が空なら通す"""

    def __init__(self):
        self.problems, self.warns, self.times, self.skipped = [], [], [], []
        self.wall = None   # 流した全体の秒(検査と単体を並べたので times の和ではない)

    def step(self, name, t0):
        self.times.append((name, time.monotonic() - t0))


def run(branch, root=REPO, skip=(), worklog_name=None, jobs=None, list_only=False, notes=None, log=print, all_tests=False):
    """branch の関所を流す -> Gate。root はどの作業フォルダでもよい(ブランチの作業フォルダを探す)"""
    g = Gate()
    g.skipped = sorted(skip)
    wt = worktree_of(root, branch)
    if not wt:
        g.problems.append("%s をチェックアウトしている作業フォルダが無い(関所はそこで流す)" % branch)
        return g
    notes = notes or layout.notes_root()
    code, out = git(wt, "status", "--porcelain", "--untracked-files=no")
    if out.strip():
        g.warns.append("作業フォルダに未コミットの変更がある(テストは今のファイルで流す・main に入るのはコミットだけ)")
    if git(wt, "merge-base", "--is-ancestor", "main", branch)[0]:
        g.warns.append("main の新しい分を取り込んでいない(合わせた形はテストしていない。git rebase main を勧める)")
    paths = [p for p in git(wt, "diff", "--name-only", "main..." + branch)[1].splitlines() if p]
    dirs, manual, unknown = select(paths)
    if all_tests:
        units, how = pick_units(wt, ALL), "全部"
    elif BY_IMPORTS:
        units, back = pick_by_imports(wt, paths)
        how = "import のつながり" + ("・層の決まりに戻した %d ファイル" % back if back else "")
    else:
        units = pick_units(wt, dirs)
        how = "全部" if dirs == ALL else "・".join(sorted(d.rstrip("/") for d in dirs))
    jobs = jobs or max(2, min(8, (os.cpu_count() or 4) // 3))
    log("関所: 変えたファイル %d・単体テスト %d 本(%s)・並べる数 %d" % (len(paths), len(units), how or "見張りだけ", jobs))
    for m in manual:
        g.warns.append("単体テストの外の物を変えた。手で流す: " + m)
    for p in unknown[:5]:
        g.warns.append("関所の決まりが無い場所: %s(dev/land_gate.py の select に足す)" % p)
    g.warns += table_drift(wt, os.path.join(notes, "docs", "spec", "code.md"))
    if list_only:
        for u in units:
            log("  " + u.label)
        return g
    t_all = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=1)   # 検査は単体と並べる
    checks = pool.submit(_checks, g, wt, root) if "checks" not in skip else None
    if "tests" not in skip:
        t0 = time.monotonic()
        cpath = cache_path(wt)
        cache = load_cache(cpath) if cpath else {"trees": {}, "secs": {}}
        clean = not git(wt, "status", "--porcelain")[1].strip()
        tree = git(wt, "rev-parse", "HEAD^{tree}")[1].strip() if clean else ""
        done = set(cache["trees"].get(tree, [])) if tree else set()
        todo = [u for u in units if u.rel not in done]
        if len(todo) < len(units):
            log("関所: 同じ木で通った単体 %d 本を飛ばす(%s の控え)" % (len(units) - len(todo), CACHE_NAME))
        results = run_units(todo, jobs, log, cache["secs"])
        if cpath:
            save_cache(cpath, cache, tree, results)
        for r in results:
            if r.ok:
                continue
            tail = "\n".join("    " + s for s in r.err.strip().splitlines()[-TAIL:])
            g.problems.append("単体テストが落ちた: %s\n%s" % (r.unit.label, tail))
        g.step("単体テスト %d 本" % len(todo), t0)
    if checks:
        checks.result()
    pool.shutdown()
    g.wall = time.monotonic() - t_all
    if "worklog" not in skip:
        name = worklog_name or session_name(branch)
        path = worklog.find_session(name, notes)
        if not path:
            g.problems.append("作業の記録が無い: %s(py -3.12 dev/worklog.py new %s で作る。名前が違えば --worklog)" % (name, name))
        else:
            probs, warns = worklog.check(path)
            g.problems += ["作業の記録 %s: %s" % (os.path.basename(path), s) for s in probs]
            g.warns += ["作業の記録 %s: %s" % (os.path.basename(path), s) for s in warns]
    return g


def _checks(g, wt, root):
    """検査 5 本(直列。単体テストと並べて呼ぶ)"""
    t0 = time.monotonic()
    main_wt = worktree_of(root, "main")
    for name, args in (("lint", ["dev/lint.py"]), ("画面の静的な検査", ["dev/ui_audit.py", "static"]), ("計画のデータ", ["dev/plan_data.py", "check"]),
                           ("資料のパス", ["dev/notes_tool.py", "check"]), ("消した道具の名前", ["dev/spec_check.py", "--gone"])):
        prob, warn = run_check(wt, main_wt, name, args)
        g.problems += [prob] if prob else []
        g.warns += [warn] if warn else []
    g.step("検査", t0)


def report(g, log=print):
    for w in g.warns:
        log("[警告] " + w)
    for p in g.problems:
        log("[落ちた] " + p)
    if g.skipped:
        log("[抜いた] " + "・".join(g.skipped))
    total = g.wall if g.wall is not None else sum(s for _n, s in g.times)
    log("関所: %s(%s・計 %.0f 秒)" % ("止めた" if g.problems else "通った",
                                   "・".join("%s %.0f 秒" % t for t in g.times) or "流した物なし", total))


def record(common, branch, g, landed):
    """land の記録(git の共通ディレクトリの ytt-land.log。抜け道を使ったかを後から見る)"""
    line = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "branch": branch, "skipped": g.skipped,
            "problems": len(g.problems), "secs": round(g.wall if g.wall is not None else sum(s for _n, s in g.times)), "landed": landed}
    try:
        with open(os.path.join(common, "ytt-land.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def add_args(ap):
    ap.add_argument("--skip-tests", action="store_true", help="単体テストを抜く(記録に残る)")
    ap.add_argument("--skip-checks", action="store_true", help="lint・計画のデータ・資料のパスを抜く(記録に残る)")
    ap.add_argument("--skip-worklog", action="store_true", help="作業の記録の検査を抜く(記録に残る)")
    ap.add_argument("--worklog", default=None, help="作業の記録の名前かパス(既定はブランチから)")
    ap.add_argument("-j", dest="jobs", type=int, default=None, help="テストを並べて流す数")
    ap.add_argument("--all", dest="all_tests", action="store_true", help="単体テストを全部流す(大きな区切り。import のつながりで選ばない)")


def skips(a):
    return {k for k, on in (("tests", a.skip_tests), ("checks", a.skip_checks), ("worklog", a.skip_worklog)) if on}


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("branch", nargs="?")
    ap.add_argument("--list", action="store_true", help="選んだテストの一覧だけ")
    add_args(ap)
    a = ap.parse_args(argv)
    branch = a.branch or git(REPO, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    g = run(branch, skip=skips(a), worklog_name=a.worklog, jobs=a.jobs, list_only=a.list, all_tests=a.all_tests)
    report(g)
    return 1 if g.problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
