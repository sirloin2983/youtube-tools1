#!/usr/bin/env python3
"""セッションの入口の要約(2026-10-18)。新しい AI のセッションが最初に流し、今の状態を 1 画面(150 行以内)で見る。

    py -3.12 dev/session_start.py [<領域>]                    # 両方の git・版・今週の作業の記録・境目のメモ・計画・重い仮決め・動いている worktree
    py -3.12 dev/session_start.py --brief <領域> --task "<一言>"   # 子への指示文の下書き(雛形・関係する地図と spec・重なりそうな worktree)

読むだけ(何も書き換えない)・新しい「正」は作らない。どの行も元の場所から読んで出す:
  git(リポジトリ・保管庫)・main の src/ytt/version.py・docs/worklog/<週>/ のセッションのファイル(dev/worklog.py の形)・
  境目-*.md(共有メモのフォルダ %APPDATA%/Claude/side-session-notes/*/ と保管庫)・plan/data/ の tasks と user・
  plan/仮決めの一覧.md・git worktree list・codemap/・docs/spec/ と AGENTS.md の「何を触るときに何を読むか」の表。
雛形の正は保管庫の docs/子への指示文の雛形.md(最初の ``` の中)。
領域は codemap/ と docs/spec/ のファイル名・AGENTS.md の表の行に当てる言葉(例: friendapp・pipeline・plan・editor・dev)。
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "dev"))
from ytt import layout  # noqa: E402
import worklog  # noqa: E402

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WIDTH = 120
MAIN = "main"
TEMPLATE_REL = "docs/子への指示文の雛形.md"
PROV_REL = "plan/仮決めの一覧.md"
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)
HEAVY_RE = re.compile(r"^## まだの重い物[((](\d+) 件[))]", re.M)
ACTIVE_DAYS = 2
# 領域の言葉に足す言葉(ファイル名・表の行に当てるだけ。中身の正ではない)
ALIASES = {
    "friendapp": ["friend", "友人"], "friend": ["friendapp", "友人"],
    "pipeline": ["受け渡し"], "plan": ["計画", "plan/"], "editor": ["編集", "文字起こし", "校正"],
    "dev": ["code", "lint", "開発の道具"], "live": ["録画"], "pack": ["cut2resolve", "パック"],
    "ui": ["ui-kit", "画面"], "app": ["入口"], "data": ["作業データ"], "cases": ["案件"], "check": ["確かめる"],
}
TASK_SHOW = ("doing", "next", "wait", "cont")
STATE_WORD = {"doing": "進行中", "next": "次", "wait": "ユーザー待ち", "cont": "継続", "todo": "あと"}


def cut(text, n=WIDTH):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def run(args, cwd):
    """git などを窓を出さずに流す。-> 標準出力(失敗は空)"""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=20, creationflags=NOWIN)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout if p.returncode == 0 else ""


def git(cwd, *args):
    return run(["git", "--no-optional-locks", "-c", "core.quotepath=false"] + list(args), cwd)   # status も index を書かない


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().replace("\r\n", "\n")
    except OSError:
        return None


# ---- git ----

def git_block(name, path, with_main=False):
    """-> 行のリスト(状態・未コミット・最新 5 コミット)"""
    if not os.path.isdir(path):
        return ["%s: 無い(%s)" % (name, path)]
    branch = git(path, "rev-parse", "--abbrev-ref", "HEAD").strip() or "?"
    status = [ln for ln in git(path, "status", "--porcelain").split("\n") if ln.strip()]
    head = "%s %s [%s] 未コミット %d" % (name, path, branch, len(status))
    if with_main and branch != MAIN:
        ab = git(path, "rev-list", "--left-right", "--count", "%s...HEAD" % MAIN).split()
        if len(ab) == 2:
            head += "・main より +%s / -%s" % (ab[1], ab[0])
    out = [head]
    if status:
        out.append("  未コミット: " + cut("・".join(ln[3:] for ln in status[:6]) + (" ほか" if len(status) > 6 else ""),
                                       WIDTH - 14))
    out += ["  " + cut(ln, WIDTH - 2) for ln in git(path, "log", "-5", "--format=%h %ad %s",
                                                   "--date=format:%m-%d %H:%M").split("\n") if ln]
    return out


def versions(repo):
    """-> (main の版, 今の作業フォルダの版)"""
    m = VERSION_RE.search(git(repo, "show", "%s:src/ytt/version.py" % MAIN))
    here = VERSION_RE.search(read(os.path.join(repo, "src", "ytt", "version.py")) or "")
    return (m.group(1) if m else "?"), (here.group(1) if here else "?")


# ---- 作業の記録 ----

def worklog_block(notes, today, limit=12):
    week = worklog.week_name(today)
    d = os.path.join(worklog.worklog_dir(notes), week)
    entries = worklog.sessions(d) if os.path.isdir(d) else []
    out = ["## 今週の作業の記録(docs/worklog/%s/・%d 件。新しい順)" % (week, len(entries))]
    for date, name, _title, summary in entries[:limit]:
        out.append("- " + cut("%s %s: %s" % (date[5:], name, summary or "(まとめ未記入)"), WIDTH - 2))
    if len(entries) > limit:
        out.append("- ほか %d 件(docs/worklog/%s.md)" % (len(entries) - limit, week))
    if not entries:
        out.append("- (まだ無い。docs/worklog/%s.md の手書きの所を見る)" % week)
    return out


# ---- 境目のメモ ----

def boundary_dirs(notes):
    appdata = os.environ.get("APPDATA")
    dirs = [notes]
    if appdata:
        dirs.append(os.path.join(appdata, "Claude", "side-session-notes"))
    return dirs


def boundary_notes(dirs):
    """-> [(更新の時刻, パス, 見出し)] 新しい順"""
    found = set()
    for d in dirs:
        found.update(glob.glob(os.path.join(d, "**", "境目-*.md"), recursive=True))
    out = []
    for p in found:
        if os.sep + ".git" + os.sep in p:
            continue
        text = read(p) or ""
        title = next((ln.lstrip("# ").strip() for ln in text.split("\n") if ln.startswith("#")), "")
        out.append((os.path.getmtime(p), p, title))
    return sorted(out, reverse=True)


def boundary_block(dirs, limit=10):
    notes = boundary_notes(dirs)
    out = ["## 境目のメモ(境目-*.md・%d 本。新しい順)" % len(notes)]
    for mt, p, title in notes[:limit]:
        stamp = datetime.datetime.fromtimestamp(mt).strftime("%m-%d %H:%M")
        out.append("- " + cut("%s %s — %s" % (stamp, os.path.basename(p), title), WIDTH - 2))
        out.append("    " + p)
    if not notes:
        out.append("- (無い)")
    return out


# ---- 計画 ----

def load_items(folder):
    items = []
    for p in glob.glob(os.path.join(folder, "*.json")):
        try:
            items.append(json.loads(read(p) or "{}"))
        except ValueError:
            items.append({"id": os.path.basename(p), "name": "(読めない JSON)", "state": "?"})
    return sorted(items, key=lambda x: (x.get("order", 0), str(x.get("id", ""))))


def plan_block(notes):
    data = os.path.join(notes, "plan", "data")
    if not os.path.isdir(data):
        return ["## 計画: plan/data/ が無い"]
    tasks = load_items(os.path.join(data, "tasks"))
    users = load_items(os.path.join(data, "user"))
    counts = {}
    for t in tasks:
        counts[t.get("state")] = counts.get(t.get("state"), 0) + 1
    out = ["## 計画(plan/data/。工程 %d: %s)" % (len(tasks), "・".join(
        "%s %d" % (STATE_WORD.get(k, k), v) for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])) if k != "done"))]
    for t in tasks:
        if t.get("state") in TASK_SHOW:
            out.append("- " + cut("[%s] %s %s(%s)" % (STATE_WORD[t["state"]], t.get("id"), t.get("name", ""),
                                                      t.get("who", "")), WIDTH - 2))
    now = [u for u in users if u.get("state") != "done" and u.get("list") == "ordered"]
    later = [u for u in users if u.get("state") != "done" and u.get("list") != "ordered"]
    out.append("人の番(1-1 今できる %d 件・1-2 あとで %d 件):" % (len(now), len(later)))
    for u in now:
        out.append("- " + cut("[%s] %s %s" % (STATE_WORD.get(u.get("state"), u.get("state")), u.get("id"),
                                              u.get("name", "")), WIDTH - 2))
    return out


def provisional_block(notes, top=3):
    text = read(os.path.join(notes, *PROV_REL.split("/")))
    if text is None:
        return ["## 重い仮決め: %s が無い" % PROV_REL]
    m = HEAVY_RE.search(text)
    out = ["## 重い仮決め: まだ %s 件(%s。週 1 回、重い順に 1 問ずつ聞く)" % (m.group(1) if m else "?", PROV_REL)]
    if m:
        body = text[m.end():].split("\n## ", 1)[0]
        for ln in [ln for ln in body.split("\n") if re.match(r"^\d+\. ", ln)][:top]:
            out.append("  " + cut(ln, WIDTH - 2))
    return out


# ---- worktree ----

def worktrees(repo):
    """-> [{path, branch, head}]"""
    out, cur = [], {}
    for ln in git(repo, "worktree", "list", "--porcelain").split("\n") + [""]:
        if not ln.strip():
            if cur.get("path"):
                out.append(cur)
            cur = {}
        elif ln.startswith("worktree "):
            cur["path"] = ln[9:].strip()
        elif ln.startswith("branch "):
            cur["branch"] = ln[7:].strip().replace("refs/heads/", "", 1)
        elif ln.startswith("HEAD "):
            cur["head"] = ln[5:].strip()
    return out


def index_mtime(path):
    """worktree の index の更新の時刻(.git のファイルの gitdir: から。読めなければ 0)"""
    try:
        dot = os.path.join(path, ".git")
        gd = dot
        if os.path.isfile(dot):
            gd = (read(dot) or "").strip().split("gitdir:", 1)[-1].strip()
            gd = gd if os.path.isabs(gd) else os.path.join(path, gd)
        return os.path.getmtime(os.path.join(gd, "index"))
    except OSError:
        return 0


def active_worktrees(repo, now=None, days=ACTIVE_DAYS):
    """動いている worktree = 未コミットがある(index を最近触った物だけ見る)か、main に入っていない(取り込み済みの写しを除く)
    コミットが days 日以内にある物。-> ([{path, branch, ahead, dirty, date, subject}] 新しい順, main 以外の数, 古い枝の数)"""
    now = now or datetime.datetime.now().timestamp()
    wts = [w for w in worktrees(repo) if w.get("branch") and w["branch"] != MAIN]

    def one(w):
        n = git(repo, "rev-list", "--count", "--cherry-pick", "--right-only", "%s...%s" % (MAIN, w["branch"])).strip()
        ahead = int(n) if n.isdigit() else 0
        info = git(repo, "log", "-1", "--format=%ct|%s", w["branch"]).strip().split("|", 1)
        date = int(info[0]) if info[0].isdigit() else 0
        dirty = []
        touched = index_mtime(w["path"])
        if now - touched < days * 86400:
            dirty = [ln[3:] for ln in git(w["path"], "status", "--porcelain").split("\n") if ln.strip()]
        return dict(w, ahead=ahead, dirty=dirty, date=max(date, int(touched)) if dirty else date,
                    subject=(info[1] if len(info) > 1 else "") if ahead else "(コミット前)")

    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(one, wts))
    act = [r for r in rows if r["dirty"] or (r["ahead"] and now - r["date"] < days * 86400)]
    stale = sum(1 for r in rows if r["ahead"] and r not in act)
    return sorted(act, key=lambda r: r["date"], reverse=True), len(wts), stale


def worktree_lines(act, total, stale=0, me=None, limit=12, overlap=None):
    out = ["## 動いている worktree(%d 本。main 以外 %d・main に入っていない古い枝 %d)" % (len(act), total, stale)]
    for r in act[:limit]:
        stamp = datetime.datetime.fromtimestamp(r["date"]).strftime("%m-%d %H:%M") if r["date"] else "?"
        mark = "(ここ)" if me and os.path.normcase(os.path.abspath(r["path"])) == os.path.normcase(me) else ""
        state = "・".join(s for s in ("+%d" % r["ahead"] if r["ahead"] else "",
                                      "未コミット %d" % len(r["dirty"]) if r["dirty"] else "") if s)
        line = "- %s %s%s [%s] %s %s" % (stamp, os.path.basename(r["path"]), mark, r["branch"], state, r["subject"])
        out.append(cut(line, WIDTH))
        if overlap and overlap.get(r["branch"]):
            out.append("    重なる: " + cut("・".join(overlap[r["branch"]]), WIDTH - 12))
    if len(act) > limit:
        out.append("- ほか %d 本" % (len(act) - limit))
    return out


# ---- 領域 ----

def words_of(domain):
    d = domain.strip().lower()
    return [d] + [w.lower() for w in ALIASES.get(d, [])]


def domain_refs(domain, repo, notes):
    """-> (codemap の頁, spec の文書, AGENTS.md の表の行の読む物)"""
    words = words_of(domain)

    def hit(stem):
        s = stem.lower()
        return any(w == s or (len(w) >= 3 and w in s) for w in words)

    cmap = sorted(p for p in glob.glob(os.path.join(repo, "codemap", "*.md"))
                  if hit(os.path.splitext(os.path.basename(p))[0]) and os.path.basename(p) != "index.md")
    spec = sorted(p for p in glob.glob(os.path.join(notes, "docs", "spec", "**", "*.md"), recursive=True)
                  if hit(os.path.splitext(os.path.basename(p))[0]))
    rows = []
    agents = read(os.path.join(notes, "AGENTS.md")) or ""
    sec = agents.split("## 何を触るときに何を読むか", 1)
    if len(sec) == 2:
        for ln in sec[1].split("\n## ", 1)[0].split("\n"):
            cells = ln.split("|")
            if len(cells) < 4 or ln.startswith("| ---") or ln.startswith("| 触る物"):
                continue
            if any(w in cells[1].lower() or w in cells[2].lower() for w in words):
                rows.append((cells[1].strip(), cells[2].strip()))
    return cmap, spec, rows


def codemap_files(page):
    """codemap の層の頁から、載っているファイルのリポジトリの中のパス"""
    out, cur = [], ""
    for ln in (read(page) or "").split("\n"):
        m = re.match(r"^## (\S+/)\s*$", ln)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^- \*\*([^*]+)\*\*", ln)
        if m and cur:
            out.append(cur + m.group(1))
    return out


def rel(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def domain_block(domain, repo, notes):
    cmap, spec, rows = domain_refs(domain, repo, notes)
    out = ["## 領域 %s" % domain]
    out += ["- 地図: %s" % rel(p, repo) for p in cmap] or ["- 地図: (当たる頁なし。codemap/index.md と codemap/words.md を見る)"]
    out += ["- spec: %s" % rel(p, notes) for p in spec] or ["- spec: (当たる文書なし)"]
    for what, refs in rows:
        out.append("- " + cut("%s → %s" % (what, refs), WIDTH - 2))
    return out


def overlaps(repo, act, files):
    """各枝が main から変えたファイルのうち、files に入る物。-> {枝: [パス]}"""
    want = set(files)

    def one(r):
        changed = git(repo, "diff", "--name-only", "%s...%s" % (MAIN, r["branch"])).split("\n") if r["ahead"] else []
        changed += [f.split(" -> ")[-1].strip('"') for f in r.get("dirty", [])]
        return r["branch"], sorted(set(f for f in changed if f in want))

    with ThreadPoolExecutor(8) as ex:
        return {b: fs for b, fs in ex.map(one, act) if fs}


# ---- 子への指示文 ----

def template_text(notes):
    """雛形の正(docs/子への指示文の雛形.md)の最初の ``` の中"""
    text = read(os.path.join(notes, *TEMPLATE_REL.split("/")))
    if text is None:
        raise SystemExit("雛形が無い: %s" % os.path.join(notes, TEMPLATE_REL))
    m = re.search(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S)
    if not m:
        raise SystemExit("雛形の ``` が無い: %s" % TEMPLATE_REL)
    return m.group(1).rstrip("\n")


def brief(domain, task, repo, notes, act=None):
    cmap, spec, rows = domain_refs(domain, repo, notes)
    files = [f for p in cmap for f in codemap_files(p)]
    if act is None:
        act = active_worktrees(repo)[0]
    over = overlaps(repo, act, files) if files else {}
    out = ["Task:", task, "", "**なぜ**", "(ここに 1〜3 行)", "", "**触る所(コードを探すときは、まず codemap/)**"]
    out += ["- 地図: `%s`" % rel(p, repo) for p in cmap] or [
        "- 地図: `codemap/index.md`・`codemap/words.md`"]
    out += ["- spec: `%s`" % rel(p, notes) for p in spec]
    for what, refs in rows:
        out.append("- %s → %s" % (what, refs))
    out += ["", "**並行で動いている worktree(重なりの注意。触る前に相手へ SendMessage)**"]
    if act:
        for r in act[:10]:
            fs = over.get(r["branch"])
            out.append("- %s — %s%s" % (r["branch"], cut(r["subject"], 60),
                                       ":重なる " + "・".join(fs[:6]) if fs else ""))
    else:
        out.append("- (main に入っていない枝は無い)")
    out += ["", template_text(notes), "", "**この仕事の完了の条件**", "- (ここに)"]
    return "\n".join(out)


# ---- まとめ ----

def loc_line(repo):
    """今の行数の合計を 1 行(dev/loc.py --line と同じ。行数の報告は dev/loc.py --since の数で)。数えられないときは空"""
    try:
        import loc
        return loc.one_line(loc.totals(loc.tally(loc.files_at(repo=repo)))) + "・差は dev/loc.py --since <rev>"
    except (Exception, SystemExit):
        return ""


def summary(domain, repo, notes, today):
    with ThreadPoolExecutor(4) as ex:
        f_repo = ex.submit(git_block, "リポジトリ", repo, True)
        f_notes = ex.submit(git_block, "保管庫", notes)
        f_ver = ex.submit(versions, repo)
        f_act = ex.submit(active_worktrees, repo)
        f_loc = ex.submit(loc_line, repo)
        repo_lines, notes_lines, (v_main, v_here), (act, total, stale) = (
            f_repo.result(), f_notes.result(), f_ver.result(), f_act.result())
        loc_text = f_loc.result()
    out = ["# セッションの入口 %s 版: main %s / ここ %s" % (
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), v_main, v_here)]
    out += [loc_text] if loc_text else []
    out.append("## git")
    out += repo_lines + notes_lines
    out += worklog_block(notes, today)
    out += boundary_block(boundary_dirs(notes))
    out += plan_block(notes)
    out += provisional_block(notes)
    over = None
    if domain:
        cmap, _spec, _rows = domain_refs(domain, repo, notes)
        files = [f for p in cmap for f in codemap_files(p)]
        over = overlaps(repo, act, files) if files else None
    out += worktree_lines(act, total, stale, me=os.path.normcase(os.path.abspath(repo)), overlap=over)
    if domain:
        out += domain_block(domain, repo, notes)
    out.append("次: 触る物の spec を読む・子へは --brief <領域> --task \"…\"")
    return "\n".join(out)


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("domain", nargs="?", default="")
    ap.add_argument("--brief", metavar="領域")
    ap.add_argument("--task", default="")
    a = ap.parse_args(argv)
    notes = layout.notes_root()
    if a.brief is not None:
        if not a.task:
            ap.error("--brief には --task \"<一言>\" が要る")
        print(brief(a.brief, a.task, REPO, notes))
        return 0
    print(summary(a.domain, REPO, notes, datetime.date.today()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
