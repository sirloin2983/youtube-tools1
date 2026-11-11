#!/usr/bin/env python3
"""セッションの入口の要約。新しい AI のセッションが最初に流し、今の状態を 1 画面(150 行以内)で見る。

    py -3.12 dev/session_start.py [<領域>]                    # 片付け(下)・両方の git・版・今週の作業の記録・境目のメモ・やること・動いている worktree
    py -3.12 dev/session_start.py --brief <領域> --task "<一言>"   # 子への指示文の下書き(雛形・関係する地図と仕様・重なりそうな worktree)
    py -3.12 dev/session_start.py --no-tidy [<領域>]          # 片付けをせずに要約だけ

要約は読むだけ・新しい「正」は作らない。どの行も元の場所から読んで出す:
  git(リポジトリ・保管庫)・main の src/ytt/version.py・docs/worklog/<週>/ のセッションのファイル(dev/worklog.py の形)・
  境目-*.md(共有メモのフォルダ %APPDATA%/Claude/side-session-notes/*/ と保管庫)・保管庫の やること.md・
  git worktree list・codemap/・今の道具の仕様/(と、残っていれば docs/spec/)と AGENTS.md の「何を触るときに何を読むか」の表。
片付け(tidy。資料が溜まらないように道具がする。11-11 の資料の整理):
  自分で移す(控えのフォルダへ。dev/notes_tool.py archive。いつでも戻せる): 今週より前の作業の記録(dev/worklog.py archive_old_weeks)・
    途中/ の、頭の「終わり: <日付>」を過ぎた物と「状態: 済み」の物。
  知らせる(1 行ずつ。止めない・まとめ役が片付ける): 置き場ごとの数・やること.md などの行数が上限(CAPS)を超えた・途中/ に「終わり:」の無い物・
    決まった置き場(PLACES)の外の物・切れたパス(dev/notes_tool.py check)。作業の記録を移した時は、済んでいない行を出す。
雛形の正は保管庫の docs/子への指示文の雛形.md(最初の ``` の中)。
領域は codemap/ と 今の道具の仕様/ のファイル名・AGENTS.md の表の行に当てる言葉(例: friendapp・pipeline・editor・dev)。
"""
import argparse
import datetime
import glob
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
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)
ACTIVE_DAYS = 2
# 領域の言葉に足す言葉(ファイル名・表の行に当てるだけ。中身の正ではない)
ALIASES = {
    "friendapp": ["friend", "友人"], "friend": ["friendapp", "友人"],
    "pipeline": ["受け渡し"], "editor": ["編集", "文字起こし", "校正"],
    "dev": ["code", "lint", "開発の道具", "コード"], "live": ["録画", "ライブ"], "pack": ["cut2resolve", "パック"],
    "ui": ["ui-kit", "画面"], "app": ["入口", "全体の形"], "data": ["作業データ", "データ"], "cases": ["案件"], "check": ["確かめる"],
}
SPEC_DIRS = ("今の道具の仕様", "docs/spec")   # 今の道具の仕様の正(docs/spec/ は 11-11 に控えへ移す。残っている間だけ読む)
TODO_REL = "やること.md"
TODO_LINES = 30
DOING_REL = "途中"
# 置き場ごとの上限(保管庫からの相対, 数, 中のフォルダも数えるか)と、行数の上限(保管庫からの相対, 行)。目安(超えたら知らせるだけ)
FOLDER_CAPS = (("決定と要件", 10, True), ("今の道具の仕様", 25, True), ("研究", 10, True), ("道具の作り直し", 10, True),
               (DOING_REL, 10, True), ("docs/worklog", 60, True), ("plan", 12, False))
LINE_CAPS = ((TODO_REL, 150), ("今の道具の仕様/直す候補.md", 200), ("決定.md", 300), ("AGENTS.md", 200))
# 決まった置き場(保管庫の直下と docs/ の直下)。ほかは「置き場の外」と知らせる
PLACES = {"": {"AGENTS.md", "ホーム.md", ".gitignore", TODO_REL, "決定.md", "決定と要件", "今の道具の仕様", "研究",
               "道具の作り直し", DOING_REL, "docs", "plan", "chrome-ext", "src"},
          "docs": {"AIの動き", "worklog", "動作環境.md", "子への指示文の雛形.md", "資料の書き方.md", "複数のAIの注意.md"}}
END_RE = re.compile(r"^終わり[:：]\s*(\d{4}-\d{2}-\d{2})", re.M)
DONE_RE = re.compile(r"^状態[:：]\s*(済み|終わった|完了)", re.M)
PENDING_SHOW = 15


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
    except (OSError, ValueError):   # UTF-8 でないメモ 1 枚で止まらない
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
        try:
            mtime = os.path.getmtime(p)
        except OSError:   # glob と読みの間に消えた
            continue
        text = read(p) or ""
        title = next((ln.lstrip("# ").strip() for ln in text.split("\n") if ln.startswith("#")), "")
        out.append((mtime, p, title))
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


# ---- やること ----

def todo_block(notes, limit=TODO_LINES):
    """保管庫の やること.md の頭(頭の YAML を除いた見出しと箇条。計画のページ一式は 11-11 にやめた)"""
    text = read(os.path.join(notes, TODO_REL))
    if text is None:
        return ["## やること: %s が無い" % TODO_REL]
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        text = text[end + 4:] if end >= 0 else text
    lines = [ln for ln in text.split("\n") if ln.startswith(("## ", "### ", "- ", "| ")) and not ln.startswith("| ---")]
    out = ["## やること(%s・%d 行)" % (TODO_REL, len(text.split("\n")))]
    out += [cut(ln, WIDTH) for ln in lines[:limit]]
    if len(lines) > limit:
        out.append("- ほか %d 行(%s)" % (len(lines) - limit, TODO_REL))
    return out


# ---- 片付け(控えへ移す・知らせる) ----

def count_files(path, recursive=True):
    if not os.path.isdir(path):
        return 0
    if not recursive:
        return sum(1 for n in os.listdir(path) if os.path.isfile(os.path.join(path, n)) and not n.startswith("."))
    n = 0
    for _d, ds, fs in os.walk(path):
        ds[:] = [x for x in ds if not x.startswith(".") and x != "__pycache__"]
        n += sum(1 for f in fs if not f.startswith("."))
    return n


def doing_due(notes, today):
    """途中/ の物 -> (移す物 [相対], 「終わり:」の無い物 [相対])"""
    d = os.path.join(notes, DOING_REL)
    due, no_end = [], []
    if not os.path.isdir(d):
        return due, no_end
    for n in sorted(os.listdir(d)):
        if n.startswith("."):
            continue
        p = os.path.join(d, n)
        rel_p = "%s/%s" % (DOING_REL, n)
        head = "\n".join((read(p) or "").split("\n")[:15]) if os.path.isfile(p) else \
            "\n".join("\n".join((read(os.path.join(p, f)) or "").split("\n")[:15]) for f in sorted(os.listdir(p)) if f.endswith(".md"))
        m = END_RE.search(head)
        if DONE_RE.search(head) or (m and m.group(1) < today.isoformat()):
            due.append(rel_p)
        elif not m and not re.search(r"^終わり[:：]", head, re.M):
            no_end.append(rel_p)
    return due, no_end


def notices(notes, with_links=True):
    """上限・置き場の外・切れたパスの知らせ(1 行ずつ)"""
    out = []
    for rel_p, cap, rec in FOLDER_CAPS:
        n = count_files(os.path.join(notes, *rel_p.split("/")), rec)
        if n > cap:
            out.append("%s/ が %d 本(目安 %d)" % (rel_p, n, cap))
    for rel_p, cap in LINE_CAPS:
        text = read(os.path.join(notes, *rel_p.split("/")))
        if text is not None and text.count("\n") + 1 > cap:
            out.append("%s が %d 行(目安 %d)" % (rel_p, text.count("\n") + 1, cap))
    for base, allowed in PLACES.items():
        d = os.path.join(notes, base) if base else notes
        if not os.path.isdir(d):
            continue
        extra = sorted(n for n in os.listdir(d) if not n.startswith(".") and n not in allowed)
        if extra:
            out.append("決まった置き場の外: %s" % cut("・".join((base + "/" if base else "") + n for n in extra), WIDTH - 20))
    if with_links:
        try:
            import notes_tool
            bad = notes_tool.check(root=notes)
        except Exception as e:   # 知らせのための検査で入口を止めない
            bad, out = [], out + ["切れたパスの検査が落ちた: %s" % cut(e, 60)]
        if bad:
            out.append("切れたパス %d 件(py -3.12 dev/notes_tool.py check)" % len(bad))
    return out


def tidy(notes, today, with_links=True):
    """片付け -> 出す行(何も無ければ空)。移すのは控えのフォルダへ(dev/notes_tool.py archive)"""
    if not os.path.isdir(notes):
        return []
    import notes_tool
    out = []
    gone, pending, probs = worklog.archive_old_weeks(notes, today)
    if gone:
        out.append("- 作業の記録の前の週を控えへ移した: %s。済んでいない行 %d(まとめ役が %s へ写すか捨てる)" % (
            "・".join(gone), len(pending), TODO_REL))
        out += ["    " + cut("%s %s: %s" % p, WIDTH - 4) for p in pending[:PENDING_SHOW]]
        if len(pending) > PENDING_SHOW:
            out.append("    ほか %d 行(控えのフォルダ %s の docs/worklog/)" % (len(pending) - PENDING_SHOW, notes_tool.archive_root()))
    due, no_end = doing_due(notes, today)
    if due:
        _m, _n, p2 = notes_tool.archive(due, root=notes)
        probs += p2
        out.append("- %s/ の終わった物を控えへ移した: %s" % (DOING_REL, "・".join(due)))
    out += ["- [問題] " + s for s in probs]
    if no_end:
        out.append("- %s/ に「終わり:」の無い物: %s(まとめ役が片付ける)" % (DOING_REL, "・".join(no_end)))
    out += ["- %s(まとめ役が片付ける)" % s for s in notices(notes, with_links)]
    return ["## 片付けと知らせ"] + out if out else []


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
        return any(w == s or ((len(w) >= 3 or not w.isascii()) and w in s) for w in words)   # 日本語は 2 字でも

    cmap = sorted(p for p in glob.glob(os.path.join(repo, "codemap", "*.md"))
                  if hit(os.path.splitext(os.path.basename(p))[0]) and os.path.basename(p) != "index.md")
    spec = sorted(p for d in SPEC_DIRS for p in glob.glob(os.path.join(notes, *d.split("/"), "**", "*.md"), recursive=True)
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
    out += ["- 仕様: %s" % rel(p, notes) for p in spec] or ["- 仕様: (当たる文書なし)"]
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
    out += ["- 仕様: `%s`" % rel(p, notes) for p in spec]
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


def summary(domain, repo, notes, today, tidy_lines=()):
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
    out += list(tidy_lines)
    out.append("## git")
    out += repo_lines + notes_lines
    out += worklog_block(notes, today)
    out += boundary_block(boundary_dirs(notes))
    out += todo_block(notes)
    over = None
    if domain:
        cmap, _spec, _rows = domain_refs(domain, repo, notes)
        files = [f for p in cmap for f in codemap_files(p)]
        over = overlaps(repo, act, files) if files else None
    out += worktree_lines(act, total, stale, me=os.path.normcase(os.path.abspath(repo)), overlap=over)
    if domain:
        out += domain_block(domain, repo, notes)
    out.append("次: 触る物の仕様(今の道具の仕様/)を読む・子へは --brief <領域> --task \"…\"")
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
    ap.add_argument("--no-tidy", action="store_true", help="片付け(控えへ移す・知らせる)をしない")
    a = ap.parse_args(argv)
    notes = layout.notes_root()
    if a.brief is not None:
        if not a.task:
            ap.error("--brief には --task \"<一言>\" が要る")
        print(brief(a.brief, a.task, REPO, notes))
        return 0
    today = datetime.date.today()
    lines = [] if a.no_tidy else tidy(notes, today)
    print(summary(a.domain, REPO, notes, today, lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
