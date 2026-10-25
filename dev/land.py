#!/usr/bin/env python3
"""作業のブランチを main に入れ、版(src/ytt/version.py の VERSION と README.txt の見出し)を道具が 1 つ上げる。

    python dev/land.py [<ブランチ>] [--minor | --no-bump | --bump] [-m 要約] [--dry-run] [--wait 秒]
        # worktree の中から流してよい(ブランチの既定 = 今のブランチ)。main をチェックアウトしている作業フォルダで merge する

各セッションは版を上げない(version.py と README の見出しを触らない)。main に入れる時にこの道具が上げるので、取り込みが重なっても番号がかぶらない:
  0. 関所(dev/land_gate.py。錠の外 = ほかの取り込みを待たせない): lint・計画のデータ・資料のパス・変えた層の単体テスト・作業の記録の型。
     落ちたら止める。抜けるのは --skip-tests・--skip-checks・--skip-worklog の明示だけ(git の共通ディレクトリの ytt-land.log に残る)
  1. 錠(git の共通ディレクトリの ytt-land.lock)を取る = 同時に流しても 1 つずつ
  2. main の作業フォルダの追跡中のファイルに未コミットの変更があれば止める(ほかの人の作業途中)
  3. git merge <ブランチ>(ff できれば ff)。ぶつかったら merge --abort して止める(版の 2 か所と codemap/ だけのぶつかりは main の側を取る)
  4. 前回の版上げ(最後に version.py を変えたコミット)から今の main までに、動く物(src/・friend-apps/・setup/・README.txt・
     配る zip の道具。テストは除く)が変わっていれば、merge の前の main の版の 3 つ目を 1 上げ(--minor は 2 つ目)、別のコミットにする
     = 前の取り込みが途中で落ちて上げ忘れても、次の取り込みか --repair で拾う
  5. コードの地図(codemap/)は 1 日 1 回だけ作り直す: その日に main で作り直したコミット(DAILY_TITLE)がまだ無ければ、python dev/code_map.py を流して
     別のコミットにする(10-25: land ごとの作り直しのコミットが 3 日で 140 本あった。各セッションは codemap/ を作り直さない・lint は警告だけ)
  6. 錠を外し、新しい版と「このあとすること」を出す。push はしない(push.bat)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

from _common import read_utf8 as read_file, write_utf8 as write_file

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_REL = "src/ytt/version.py"
CODEMAP_DIR = "codemap"   # コードの地図(dev/code_map.py)。1 日 1 回 land が作り直す
DAILY_TITLE = "コードの地図を作り直した(1 日 1 回)"
README_REL = "README.txt"
VERSION_RE = re.compile(r'^(VERSION\s*=\s*")(\d+)\.(\d+)\.(\d+)(")', re.M)
README_RE = re.compile(r"(\bv)(\d+\.\d+\.\d+)(\(仮\))?")
BUMP_PREFIXES = ("src/", "friend-apps/", "setup/", "dev/build_friend_zip.py", "dev/fetch_webview2.py")   # 入口が動かす物と配る zip に入る物
TEST_PATH = re.compile(r"(^|/)tests/|(^|/)(test|e2e)_[^/]*[.]py$")
LOCK_NAME = "ytt-land.lock"
STALE_SEC = 30 * 60
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Stop(Exception):
    pass


def git(*args, cwd=REPO, check=True):
    env = dict(os.environ, GIT_MERGE_AUTOEDIT="no", GIT_EDITOR="true")
    r = subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN, env=env)
    out = r.stdout.decode("utf-8", "replace")
    if check and r.returncode:
        raise Stop("git %s が失敗: %s" % (" ".join(args), (r.stderr.decode("utf-8", "replace") or out).strip()[-400:]))
    return out if check else (r.returncode, out)


def main_worktree(cwd=REPO, branch="main"):
    """main をチェックアウトしている作業フォルダ(無ければ Stop)"""
    path = None
    for ln in git("worktree", "list", "--porcelain", cwd=cwd).splitlines():
        if ln.startswith("worktree "):
            path = ln[len("worktree "):].strip()
        elif ln.strip() == "branch refs/heads/" + branch:
            return os.path.normpath(path)
    raise Stop("%s をチェックアウトしている作業フォルダが無い" % branch)


def bump(version, minor=False):
    a, b, c = (int(x) for x in version.split("."))
    return "%d.%d.0" % (a, b + 1) if minor else "%d.%d.%d" % (a, b, c + 1)


def read_version(text):
    m = VERSION_RE.search(text)
    if not m:
        raise Stop("version.py に VERSION = \"x.y.z\" が無い")
    return "%s.%s.%s" % m.group(2, 3, 4)


def set_version(text, new):
    return VERSION_RE.sub(lambda m: m.group(1) + new + m.group(5), text, count=1)


def set_readme(text, new):
    """README の見出し(先頭 5 行の中の最初の vX.Y.Z)だけを書き換える"""
    lines = text.split("\n")
    for i, ln in enumerate(lines[:5]):
        if README_RE.search(ln):
            lines[i] = README_RE.sub(lambda m: m.group(1) + new + (m.group(3) or ""), ln, count=1)
            return "\n".join(lines)
    raise Stop("README.txt の見出しに vX.Y.Z が無い")


def needs_bump(paths):
    """版を上げる理由になるか(テストだけの変更は入口にも zip にも載らない = 上げない)"""
    return any((p == README_REL or p.startswith(BUMP_PREFIXES)) and not TEST_PATH.search(p) for p in paths)


def pid_alive(pid):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Lock:
    """git の共通ディレクトリの錠(O_EXCL)。30 分より古い物は落ちた後の残りとして奪う"""

    def __init__(self, common_dir, wait=600, log=print):
        self.path = os.path.join(common_dir, LOCK_NAME)
        self.wait, self.log = wait, log

    def __enter__(self):
        end = time.time() + self.wait
        told = False
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"pid": os.getpid(), "at": time.time(), "cwd": os.getcwd()}, f)
                return self
            except FileExistsError:
                try:
                    if not self.holder_alive() or time.time() - os.path.getmtime(self.path) > STALE_SEC:
                        os.remove(self.path)
                        self.log("古い錠を外した(%s)" % self.path)
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    raise Stop("ほかの取り込みが終わらない(錠 %s)。落ちた後の残りなら消してよい" % self.path)
                if not told:
                    self.log("ほかのセッションが取り込み中。待ちます")
                    told = True
                time.sleep(2)

    def holder_alive(self):
        """錠を持つプロセスが生きているか(読めない・書きかけの錠は生きている扱い)"""
        try:
            with open(self.path, encoding="utf-8") as f:
                pid = int(json.load(f)["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return True
        return pid_alive(pid)

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass


def pending_paths(main):
    """最後に version.py を変えたコミットから今の main までに変わった、版を上げる理由になるファイル"""
    last = git("log", "-1", "--format=%H", "--", VERSION_REL, cwd=main).strip()
    if not last:
        return []
    return [p for p in git("diff", "--name-only", last + "..HEAD", cwd=main).splitlines() if p and needs_bump([p])]


def daily_codemap(main, log, today=None):
    """その日に main で地図を作り直したコミット(DAILY_TITLE)がまだ無ければ、地図を作り直して別のコミットにする(錠の中で呼ぶ)。-> コミットしたか"""
    today = today or time.strftime("%Y-%m-%d")
    last = git("log", "-1", "--fixed-strings", "--grep", DAILY_TITLE, "--format=%ad", "--date=format:%Y-%m-%d", cwd=main, check=False)
    if (last[1] if isinstance(last, tuple) else last).strip() == today:
        return False
    code = subprocess.run([sys.executable, os.path.join("dev", "code_map.py")], cwd=main, capture_output=True, creationflags=NOWIN).returncode
    changed = [p for p in git("status", "--porcelain", "--", CODEMAP_DIR, cwd=main).splitlines() if p.strip()]
    if code or not changed:
        return False
    git("add", "-A", "--", CODEMAP_DIR, cwd=main)
    commit(main, "[Claude] " + DAILY_TITLE, "dev/land.py が作り直した(各セッションは codemap/ を作り直さない)")
    log("コードの地図を作り直した(その日の 1 回目)")
    return True


def commit(main, title, body):
    """日本語の文はファイルで渡す(コマンドラインだとコードページで化けることがある)"""
    import tempfile
    with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as f:
        f.write((title + "\n\n" + body + "\n").encode("utf-8"))
    try:
        git("commit", "-q", "-F", f.name, cwd=main)
    finally:
        os.unlink(f.name)


def recover(main, log):
    """前の取り込みが merge の途中で落ちた残りを外す(錠の中で呼ぶ = ほかに merge している人はいない)"""
    mh = git("rev-parse", "--git-path", "MERGE_HEAD", cwd=main).strip()
    if os.path.isfile(mh if os.path.isabs(mh) else os.path.join(main, mh)):
        git("merge", "--abort", cwd=main, check=False)
        log("前の取り込みの途中の merge を外した")


def land(branch, mode="auto", message="", dry_run=False, wait=600, cwd=REPO, log=print):
    """branch を main に入れ(ff できれば ff)、版を上げる理由があれば別のコミットで 1 つ上げる。branch が None なら上げ忘れの直しだけ。
    -> 新しい版(上げなかったら今の版)"""
    common = os.path.normpath(os.path.join(cwd, git("rev-parse", "--git-common-dir", cwd=cwd).strip()))
    main = main_worktree(cwd)
    if branch in ("main", "HEAD", ""):
        raise Stop("main に入れるブランチを指定する(今のブランチが main)")
    if branch:
        git("rev-parse", "--verify", "-q", "refs/heads/" + branch, cwd=main)
    vp, rp = os.path.join(main, *VERSION_REL.split("/")), os.path.join(main, README_REL)
    with Lock(common, wait, log):
        if git("symbolic-ref", "-q", "HEAD", cwd=main, check=False)[1].strip() != "refs/heads/main":
            raise Stop("main の作業フォルダ(%s)が main ではないブランチになっている" % main)
        recover(main, log)
        dirty = [ln for ln in git("status", "--porcelain", "--untracked-files=no", cwd=main).splitlines() if ln.strip()]
        if dirty:
            raise Stop("main の作業フォルダに未コミットの変更がある(ほかの人の作業途中かもしれない):\n  " + "\n  ".join(dirty[:10]))
        cur = read_version(read_file(vp))   # 数えるのはいつも merge の前の main の版(ブランチが持ち込んだ値は使わない)
        extra = pending_paths(main)   # merge の前の上げ忘れ(merge で version.py の最後のコミットが変わる前に数える)
        if branch:
            base = git("rev-parse", "HEAD", cwd=main).strip()
            ahead = git("rev-list", base + ".." + branch, cwd=main).split()
            if not ahead:
                log("%s は main にもう入っている" % branch)
            elif dry_run:
                extra += [p for p in git("diff", "--name-only", base + "..." + branch, cwd=main).split() if needs_bump([p])]
                log("(試し)%s を main に入れる: コミット %d" % (branch, len(ahead)))
            else:
                code, out = git("merge", "--no-edit", branch, cwd=main, check=False)
                if code:
                    conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=main).split()
                    if not conflicts or [c for c in conflicts if c not in (VERSION_REL, README_REL) and not c.startswith(CODEMAP_DIR + "/")]:
                        git("merge", "--abort", cwd=main, check=False)
                        raise Stop("取り込めなかった(ぶつかった物: %s)。ブランチに main を取り込んでから流し直す。"
                                   "ファイルが開かれていて失敗したなら入口を止めてから" % ("・".join(conflicts) or out.strip()[-300:]))
                    for rel in conflicts:   # 版の 2 つ・codemap/ だけのぶつかり = main の側を取る(地図は 1 日 1 回作り直す)
                        git("checkout", "--ours", "--", rel, cwd=main)
                        git("add", "--", rel, cwd=main)
                    commit(main, "[Claude] %s を main に入れる" % branch, "dev/land.py(版の行・codemap のぶつかりは main の側を取った)")
                extra += [p for p in git("diff", "--name-only", base + "..HEAD", cwd=main).split() if needs_bump([p])]
                log("%s を main に入れた" % branch)
        if mode == "none":
            if read_version(read_file(vp)) != cur:
                raise Stop("--no-bump だが、ブランチが版を変えていた(version.py)。版を上げるか、ブランチの版の変更を外す")
            return cur
        reasons = sorted(set(extra)) if dry_run or branch else pending_paths(main)
        if read_version(read_file(vp)) != cur and mode != "none":   # ブランチが版を変えていた = 必ず main の版から数え直す
            reasons = reasons or [VERSION_REL]
        if mode == "auto" and not reasons:
            log("版を上げる物が無い(版は %s のまま)" % cur)
            return cur
        new = bump(cur, mode == "minor")
        if dry_run:
            log("(試し)版 %s → %s(理由: %s)" % (cur, new, "・".join(reasons[:5]) or "指定"))
            return new
        write_file(vp, set_version(read_file(vp), new))
        write_file(rp, set_readme(read_file(rp), new))
        git("add", "--", VERSION_REL, README_REL, cwd=main)
        why = "・".join(reasons[:8]) + (" ほか %d" % (len(reasons) - 8) if len(reasons) > 8 else "")
        commit(main, "[Claude] 版を %s に(%s)" % (new, message or ("%s を取り込んだ" % branch if branch else "上げ忘れの直し")),
               "dev/land.py が上げた。理由のファイル: " + (why or "指定"))
        daily_codemap(main, log)
    log("版 %s → %s" % (cur, new))
    log("このあと: 入口を起動し直す(赤い帯)・配る zip は main の作業フォルダで py -3.12 dev/build_friend_zip.py・"
        "計画の版は py -3.12 dev/plan_artifact.py で公開し直す")
    return new


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("branch", nargs="?")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--minor", action="store_const", dest="mode", const="minor", help="2 つ目を上げる")
    g.add_argument("--no-bump", action="store_const", dest="mode", const="none", help="版を上げない")
    g.add_argument("--bump", action="store_const", dest="mode", const="bump", help="動く物が無くても上げる")
    ap.add_argument("-m", "--message", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", type=int, default=600, help="ほかの取り込みを待つ秒")
    ap.add_argument("--repair", action="store_true", help="取り込まずに、上げ忘れ(前回の版上げのあとに動く物が変わった)だけを直す")
    import land_gate
    land_gate.add_args(ap)
    a = ap.parse_args(argv)
    gate, landed = None, False
    try:
        branch = None if a.repair else (a.branch or git("rev-parse", "--abbrev-ref", "HEAD").strip())
        if branch and branch not in ("main", "HEAD") and git("rev-list", "main.." + branch).strip():
            gate = land_gate.run(branch, REPO, land_gate.skips(a), a.worklog, a.jobs, all_tests=getattr(a, "all_tests", False))
            land_gate.report(gate)
            if gate.problems:
                raise Stop("関所で止めた(上の [落ちた] を直して流し直す)")
        msg = a.message
        if gate and gate.skipped:
            msg = (msg + "・" if msg else "") + "関所を抜いた: " + "・".join(gate.skipped)
        land(branch, a.mode or "auto", msg, a.dry_run, a.wait)
        landed = not a.dry_run
        return 0
    except Stop as e:
        print("[止めた] %s" % e)
        return 1
    finally:
        if gate and not a.dry_run:
            common = os.path.normpath(os.path.join(REPO, git("rev-parse", "--git-common-dir").strip()))
            land_gate.record(common, branch, gate, landed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
