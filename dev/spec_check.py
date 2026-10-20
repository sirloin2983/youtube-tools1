#!/usr/bin/env python3
"""仕様(保管庫の docs/spec/)とコードの食い違いを探す。

    python dev/spec_check.py          # 止める物と警告を並べる(終了コード 1 = 止める物がある)
    python dev/spec_check.py --gone   # 消した道具の名前だけを探す(終了コード 1 = 残っている。main に入れる関所 dev/land_gate.py が止める)

食い違い(終了コード 1。警告として週 1 回の食い違いの一覧 dev/drift_report.py に出す。lint・push.bat は止めない =
保管庫は全部の worktree で共有なので、まだ main に入っていない別の worktree のコードを書いた仕様で止まらないように):
  - 環境変数 `YTT_*` がコード(git の src・dev・setup・friend-apps・chrome-ext と直下の起動ファイル)のどこにも無い
  - `/api/...` の口が、コードの地図(dev/code_map.py)の受ける所・呼ぶ所のどれにも当たらない
  - バッククォートの中の src/・dev/・setup/・friend-apps/・chrome-ext/ のパスが無い
警告(終了コード に関わらない):
  - 設定の鍵: 表の直前に `<!-- spec-check: 設定 -->` の印がある表の 1 列目のバッククォートが、コードの文字列に無い
  - 逆向き: src/・friend-apps/ のコード(テストを除く)が使う `YTT_*` が docs/spec のどこにも書いていない
消した道具の名前(--gone。GONE の名前。止める): 今の正に 1 つでも出たら止める。今の正 = リポジトリの git のファイル全部(配る zip の中身 =
src・friend-apps を含む。GONE_OK の物を除く)と、保管庫の AGENTS.md・docs/spec・codemap。経緯は docs/design・作業の記録・plan/done へ(そこは見ない)。
除くもの: 行に `<!-- spec-check: 旧 -->` の印・見出しに「経緯」「履歴」「過去」「旧い名前」が入る節(次の同じ深さの見出しまで)。
コードのブロック(``` の中)は除かない(環境変数の例はそこにある)。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402
from _common import tracked_files  # noqa: E402

YTT = re.compile(r"(?<![A-Za-z0-9_])YTT_[A-Z0-9_]+")
API = re.compile(r"(?<![A-Za-z0-9_.])/(?:friend/|live/)?api/[A-Za-z0-9_\-/.{}<>*:]*")
CODE = re.compile(r"`([^`\n]+)`")
PATH = re.compile(r"^(?:src|dev|setup|friend-apps|chrome-ext)/[^\s]*$")
SKIP_HEAD = re.compile(r"経緯|履歴|過去|旧い名前")
OLD_MARK = "<!-- spec-check: 旧 -->"
KEY_MARK = "<!-- spec-check: 設定 -->"
CODE_DIRS = ("src/", "dev/", "setup/", "friend-apps/", "chrome-ext/")
GONE = re.compile(r"RequestSender|request-sender|送るアプリ|依頼ボックス", re.I)   # 消した道具の名前
# 名前を出してよい物: この検査とそのテスト・手元に残った前のアプリのフォルダの鍵を git に入れない守り(.gitignore・push の鍵の検査)
GONE_OK = ("dev/spec_check.py", "dev/tests/test_doc_state.py", ".gitignore", "dev/push_helper.py", "dev/tests/test_push_helper.py")
GONE_NOTES = ("AGENTS.md", "docs/spec", "codemap")
CODE_EXTS = (".py", ".js", ".cjs", ".mjs", ".cs", ".bat", ".vbs", ".ps1", ".html", ".json", ".txt", ".command", ".gs", ".css")
SELF = ("dev/spec_check.py",)


def git_files():
    return tracked_files(REPO)


def read(p):
    try:
        with open(p, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


class Code:
    """コードの文字(1 回だけ読む)"""

    def __init__(self):
        files = [p for p in git_files() if p.endswith(CODE_EXTS) and p not in SELF
                 and (p.startswith(CODE_DIRS) or "/" not in p)]
        self.texts = {p: read(os.path.join(REPO, p)) for p in files}
        self.all = "\n".join(self.texts.values())
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import code_map
        self.routes = code_map.routes([code_map.info(p) for p in code_map.git_files()])

    def has_route(self, p):
        if p in self.routes:
            return True
        return any(r.startswith(p + "/") or p.startswith(r + "/") for r in self.routes)


def spec_files(root):
    d = os.path.join(root, "docs", "spec")
    out = []
    for base, dirs, files in os.walk(d):
        dirs.sort()
        out += [os.path.join(base, f) for f in sorted(files) if f.endswith(".md")]
    return out


def live_lines(text):
    """[(行の番号, 行)]。印のある行・経緯の節は除く"""
    out, skip_level = [], 0
    for ln, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^(#+)\s+(.*)", line)
        if m:
            level = len(m.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if not skip_level and SKIP_HEAD.search(m.group(2)):
                skip_level = level
        if skip_level or OLD_MARK in line:
            continue
        out.append((ln, line))
    return out


def norm_api(p):
    p = re.split(r"[{<*:?]", p)[0].rstrip("/.")
    for pre in ("/friend/api/", "/live/api/"):
        if p.startswith(pre):
            p = "/api/" + p[len(pre):]
    return p


def clean_path(s):
    s = re.sub(r"(:\d+(?:[-〜]\d+)?|::\w+|#.*)$", "", s.strip()).rstrip(".,、。)")
    return s


def setting_keys(lines):
    """印の次の表の 1 列目のバッククォート [(行, 鍵)]"""
    out, armed, in_table = [], False, False
    for ln, line in lines:
        if KEY_MARK in line:
            armed, in_table = True, False
            continue
        if armed and line.startswith("|"):
            in_table = True
            first = line.strip("|").split("|")[0]
            out += [(ln, k) for k in CODE.findall(first)]
        elif armed and in_table:
            armed = in_table = False
    return out


def check(root=None, code=None):
    """-> (食い違い [(資料, 行, 説明)], 警告 [(資料, 行, 説明)])"""
    root = root or layout.notes_root()
    files = spec_files(root) if os.path.isdir(root) else []
    if not files:
        return [], []
    code = code or Code()
    bad, warn, mentioned = [], [], set()
    for p in files:
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        text = read(p)
        mentioned.update(n for n in YTT.findall(text))
        lines = live_lines(text)
        for ln, line in lines:
            for m in YTT.finditer(line):
                name = m.group(0)
                if name.endswith("_") or line[m.end():m.end() + 1] in "*<{":
                    continue
                if not re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), code.all):
                    bad.append((rel, ln, "環境変数がコードに無い: " + name))
            for m in API.finditer(line):
                api = norm_api(m.group(0))
                if api.rstrip("/") in ("/api", "") or code.has_route(api):
                    continue
                bad.append((rel, ln, "口がコードに無い: " + m.group(0)))
            for s in CODE.findall(line):
                s = clean_path(s)
                if not PATH.match(s) or re.search(r"[*<{…]", s):
                    continue
                if not os.path.exists(os.path.join(REPO, *s.rstrip("/").split("/"))):
                    bad.append((rel, ln, "パスがリポジトリに無い: " + s))
        for ln, key in setting_keys(lines):
            if not re.search(r"""["']%s["']|\b%s\s*[:=]""" % (re.escape(key), re.escape(key)), code.all):
                warn.append((rel, ln, "設定の鍵がコードの文字列に無い: " + key))
    used = {}
    for path, text in code.texts.items():
        if path.startswith(("src/", "friend-apps/")) and "/tests/" not in path and not path.startswith("src/eval/"):
            for name in YTT.findall(text):
                if not name.endswith("_"):
                    used.setdefault(name, path)
    for name, path in sorted(used.items()):
        if name not in mentioned:
            warn.append((path, 1, "環境変数が docs/spec に書いていない: " + name))
    return bad, warn


def _gone_in(text):
    """-> [(行, 名前)]"""
    return [(i, m.group(0)) for i, line in enumerate(text.splitlines(), 1) for m in GONE.finditer(line)]


def gone(root=None, repo=REPO, files=None):
    """消した道具の名前の残り -> [(場所, 行, 名前)]。場所は リポジトリのパス か notes:<保管庫のパス>"""
    out = []
    for p in (git_files() if files is None else files):
        if p in GONE_OK or not os.path.isfile(os.path.join(repo, p)):
            continue
        out += [(p, ln, name) for ln, name in _gone_in(read(os.path.join(repo, p)))]
    root = root if root is not None else layout.notes_root()
    for top in GONE_NOTES if root and os.path.isdir(root) else ():
        base = os.path.join(root, *top.split("/"))
        paths = [base] if os.path.isfile(base) else [os.path.join(d, f) for d, _ds, fs in os.walk(base) for f in sorted(fs) if f.endswith(".md")]
        for p in paths:
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            out += [("notes:" + rel, ln, name) for ln, name in _gone_in(read(p))]
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if "--gone" in sys.argv[1:]:
        hits = gone()
        for where, ln, name in hits:
            print("%s:%d 消した道具の名前が残っている: %s" % (where, ln, name))
        print("消した道具の名前 %d 件" % len(hits))
        return 1 if hits else 0
    bad, warn = check()
    for where, ln, msg in bad:
        print("%s:%d %s" % (where, ln, msg))
    for where, ln, msg in warn:
        print("警告 %s:%d %s" % (where, ln, msg))
    print("食い違い %d 件・警告 %d 件" % (len(bad), len(warn)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
