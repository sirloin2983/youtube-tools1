#!/usr/bin/env python3
"""コードの見直しの合格の基準を測る道具(読むだけ。基準は `docs/spec/code-quality.md`)。

    python dev/lint.py            # 一覧と件数。問題が 1 つでもあれば終了コード 1
    python dev/lint.py --json     # 同じ内容を JSON で
    python dev/lint.py --long 150 --long-test 400 --dup 12

見るもの(標準ライブラリだけ。pyflakes などは入れない):
  1 unused-import … import したのに使っていない名前(`# noqa` の行・`__init__.py` の再公開・`__future__` は除く)
  2 dead-name     … モジュールの直下で定義した関数・クラスが、リポジトリのどこからも参照されていない
                    (名前がリポジトリ全体の .py/.js/.cjs/.html/.cs/.md に 1 回しか出ない。残すものは定義の行に `# lint: keep <理由>`)
  3 long-function … 本体が --long 行(テストは --long-test 行)を超える関数(残すものは def の行に `# lint: long <理由>`)
  4 dup-helper    … ytt_core にある小道具の写し(_unlink / _no_window / KillJob の定義が ytt_core の外にある。残すなら `# lint: keep <理由>`)
  5 js-dead       … JS のトップレベルの function が、同じツールの .js/.html のどこからも参照されていない(名前が 1 回だけ)
  6 dup-block     … 同じ行の並びが --dup 行以上、別の場所にもある(空白と行末のコメントをそろえて比べる。src/ と dev/ の .py・.js。tests/ は除く)
  7 no-docstring  … モジュールの先頭に説明(docstring)が無い .py(tests/ は除く)
  8 version       … ツールの版の 3 か所(serve.py の SERVER_VERSION・画面の APP_VERSION・README の見出し)の食い違い
対象: src/ と dev/ と setup/。friend-apps/ の C# は見ない(csc の警告 /warn:4 で代える)。
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", "build", "dist", "packs", "work", "exports", "logs", "fixtures", ".artifact-build"}
TEXT_EXT = (".py", ".js", ".cjs", ".html", ".css", ".cs", ".md", ".txt", ".bat", ".vbs", ".json")
DUP_HELPERS = {"_unlink": "fsio.unlink_quiet", "_unlink_quiet": "fsio.unlink_quiet", "_no_window": "tools.no_window_flags", "NO_WINDOW": "tools.no_window_flags",
               "KillJob": "tools.KillJob(1 か所に)", "_kill_on_close_job": "tools.KillJob(1 か所に)"}
IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
JS_FUNC = re.compile(r"^(?:\s*)function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", re.M)
# 版の 3 か所(ツールごと)
VERSIONS = {
    "studio": [("src/studio/serve.py", r'^SERVER_VERSION\s*=\s*"([^"]+)"'), ("src/studio/core.js", r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]"), ("src/studio/README.txt", r"v(\d+\.\d+\.\d+)")],
    "editor": [("src/editor/serve.py", r'^SERVER_VERSION\s*=\s*"([^"]+)"'), ("src/editor/app.js", r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]"), ("src/editor/README.txt", r"v(\d+\.\d+\.\d+)")],
    "cut2resolve": [("src/cut2resolve/cut2resolve_core.py", r'^VERSION\s*=\s*"([^"]+)"'), ("src/cut2resolve/README.txt", r"v(\d+\.\d+\.\d+)")],
    "home": [("src/home/launch.py", r'^(?:LAUNCHER_VERSION|VERSION|SERVER_VERSION)\s*=\s*"([^"]+)"'), ("src/home/README.txt", r"v(\d+\.\d+\.\d+)")],
    "recorder": [("src/recorder/recorder.py", r'^VERSION\s*=\s*"([^"]+)"'), ("src/recorder/README.txt", r"v(\d+\.\d+\.\d+)")],
}


def walk(root, exts):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        for f in files:
            if f.endswith(exts):
                yield os.path.join(d, f)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def rel(path):
    return os.path.relpath(path, REPO).replace("\\", "/")


def is_test(path):
    return "/tests/" in rel(path)


class Corpus:
    """リポジトリ全体の識別子の出現回数(ファイルごとに 1 回だけ数えて Counter に持つ)"""

    def __init__(self):
        self.texts, self.counts = {}, {}
        for root in (SRC, os.path.join(REPO, "dev"), os.path.join(REPO, "setup"), os.path.join(REPO, "friend-apps"), os.path.join(REPO, "docs"), os.path.join(REPO, "plan")):
            for p in walk(root, TEXT_EXT):
                t = read(p)
                self.texts[p] = t
                self.counts[p] = Counter(IDENT.findall(t))
        self.total = Counter()
        for c in self.counts.values():
            self.total.update(c)

    def count(self, name):
        return self.total.get(name, 0)

    def count_in(self, name, paths):
        return sum(self.counts.get(p, {}).get(name, 0) for p in paths)


def py_files():
    out = []
    for root in (SRC, os.path.join(REPO, "dev"), os.path.join(REPO, "setup")):
        out.extend(walk(root, (".py",)))
    return sorted(out)


def has_mark(lines, lineno, mark):
    line = lines[lineno - 1] if lineno <= len(lines) else ""
    return mark in line or (lineno >= 2 and mark in lines[lineno - 2])


def unused_imports(path, tree, src):
    if os.path.basename(path) == "__init__.py":
        return []
    lines = src.splitlines()
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            if node.lineno <= len(lines) and "noqa" in lines[node.lineno - 1]:
                continue
            for a in node.names:
                name = (a.asname or a.name).split(".")[0]
                if name != "*":
                    imported[name] = node.lineno
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            n = node
            while isinstance(n, ast.Attribute):
                n = n.value
            if isinstance(n, ast.Name):
                used.add(n.id)
    text_names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", "\n".join(s.value for s in ast.walk(tree) if isinstance(s, ast.Constant) and isinstance(s.value, str))))
    return [(ln, name) for name, ln in imported.items() if name not in used and name not in text_names]


def dead_names(path, tree, src, corpus):
    out = []
    lines = src.splitlines()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("__") or name == "main" or has_mark(lines, node.lineno, "lint: keep"):
                continue
            if corpus.count(name) <= 1:
                out.append((node.lineno, name))
    return out


def long_functions(path, tree, src, limit):
    out = []
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
            if n > limit and not has_mark(lines, node.lineno, "lint: long"):
                out.append((node.lineno, node.name, n))
    return out


def dup_helpers(path, tree, src):
    if "/ytt_core/" in rel(path):
        return []
    out, lines = [], src.splitlines()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        for name in names:
            if name in DUP_HELPERS and not has_mark(lines, node.lineno, "lint: keep"):
                out.append((node.lineno, name, DUP_HELPERS[name]))
    return out


def js_dead(corpus):
    out = []
    for tool in ("home", "studio", "editor", "ui-kit"):
        d = os.path.join(SRC, tool)
        paths = [p for p in walk(d, (".js", ".html", ".cjs")) if not p.endswith("ui-kit.js") or tool == "ui-kit"]
        for p in paths:
            if p.endswith(".cjs") or is_test(p):
                continue
            text = corpus.texts.get(p) or read(p)
            lines = text.splitlines()
            for m in JS_FUNC.finditer(text):
                name = m.group(1)
                line_no = text.count("\n", 0, m.start()) + 1
                if "lint: keep" in lines[line_no - 1]:
                    continue
                if corpus.count_in(name, paths) <= 1:
                    out.append((rel(p), line_no, name))
    return out


def norm_line(line):
    """空白と行末のコメントをそろえる(比べるため)"""
    line = re.sub(r"\s+#.*$|\s+//.*$", "", line)
    return re.sub(r"\s+", " ", line).strip()


def dup_blocks(n):
    """同じ正規化した行の並び(n 行以上)が 2 か所以上にあるものを、ハッシュで探す(tests は除く。空行・括弧だけの行は数えない)"""
    files = [p for p in list(walk(SRC, (".py", ".js"))) + list(walk(os.path.join(REPO, "dev"), (".py",))) if not is_test(p) and not p.endswith("ui-kit.js") or p.endswith(os.path.join("ui-kit", "ui-kit.js"))]
    files = [p for p in files if not (p.endswith("ui-kit.js") and "/ui-kit/" not in rel(p)) and not p.endswith("ui-kit.css")]
    windows = defaultdict(list)
    for p in files:
        raw = read(p).splitlines()
        norm = [(i + 1, norm_line(l)) for i, l in enumerate(raw)]
        norm = [(ln, t) for ln, t in norm if t and t not in ("}", "{", "});", ")", "]", "},", "],", "else:", "try:", "else {", "} else {", "return", "pass", "continue", "break")]
        for i in range(0, max(0, len(norm) - n + 1)):
            h = hashlib.md5("\n".join(t for _, t in norm[i:i + n]).encode("utf-8")).hexdigest()
            windows[h].append((rel(p), norm[i][0]))
    groups = {}
    for h, locs in windows.items():
        if len(locs) >= 2 and len({loc[0] for loc in locs}) + len(locs) > 2:
            groups[h] = locs
    # 連続する窓は 1 つの塊にまとめる(同じファイルの隣り合う開始行)
    merged, seen = [], set()
    for h, locs in sorted(groups.items(), key=lambda kv: kv[1][0]):
        key = tuple((f, ln // 40) for f, ln in locs)
        if key in seen:
            continue
        seen.add(key)
        merged.append(locs)
    return merged


def missing_docstrings(path, tree):
    if is_test(path) or os.path.basename(path) == "__init__.py":
        return False
    return not (tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(getattr(tree.body[0], "value", None), ast.Constant) and isinstance(tree.body[0].value.value, str))


def version_mismatch():
    out = []
    for tool, spots in VERSIONS.items():
        found = []
        for relpath, pat in spots:
            text = read(os.path.join(REPO, relpath))
            m = re.search(pat, text, re.M)
            found.append((relpath, m.group(1) if m else None))
        vals = {v for _, v in found}
        if len(vals) != 1 or None in vals:
            out.append((tool, found))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--long", type=int, default=150)
    ap.add_argument("--long-test", dest="long_test", type=int, default=400)
    ap.add_argument("--dup", type=int, default=12)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    corpus = Corpus()
    issues = {k: [] for k in ("unused-import", "dead-name", "long-function", "dup-helper", "js-dead", "dup-block", "no-docstring", "version")}
    for p in py_files():
        src = read(p)
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            issues["unused-import"].append({"file": rel(p), "line": e.lineno or 0, "name": "SyntaxError: %s" % e.msg})
            continue
        for ln, name in unused_imports(p, tree, src):
            issues["unused-import"].append({"file": rel(p), "line": ln, "name": name})
        for ln, name, n in long_functions(p, tree, src, a.long_test if is_test(p) else a.long):
            issues["long-function"].append({"file": rel(p), "line": ln, "name": name, "lines": n})
        if not is_test(p):
            for ln, name in dead_names(p, tree, src, corpus):
                issues["dead-name"].append({"file": rel(p), "line": ln, "name": name})
            for ln, name, hint in dup_helpers(p, tree, src):
                issues["dup-helper"].append({"file": rel(p), "line": ln, "name": name, "hint": hint})
            if missing_docstrings(p, tree):
                issues["no-docstring"].append({"file": rel(p), "line": 1, "name": "docstring"})
    for f, ln, name in js_dead(corpus):
        issues["js-dead"].append({"file": f, "line": ln, "name": name})
    for locs in dup_blocks(a.dup):
        issues["dup-block"].append({"file": locs[0][0], "line": locs[0][1], "name": "同じ %d 行以上: " % a.dup + "・".join("%s:%d" % loc for loc in locs[1:4])})
    for tool, found in version_mismatch():
        issues["version"].append({"file": found[0][0], "line": 1, "name": tool + ": " + "・".join("%s=%s" % (os.path.basename(f), v) for f, v in found)})
    total = sum(len(v) for v in issues.values())
    if a.json:
        print(json.dumps({"total": total, "issues": issues}, ensure_ascii=False, indent=1))
    else:
        for k, v in issues.items():
            print("== %s: %d" % (k, len(v)))
            for it in v:
                extra = " (%d 行)" % it["lines"] if "lines" in it else (" -> " + it["hint"] if "hint" in it else "")
                print("  %s:%d %s%s" % (it["file"], it["line"], it["name"], extra))
        print("合計 %d 件(0 で合格)" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
