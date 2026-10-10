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
  4 dup-helper    … ytt にある小道具の写し(_unlink / _no_window / KillJob の定義が ytt の外にある。残すなら `# lint: keep <理由>`)
  5 js-dead       … JS のトップレベルの function が、同じツールの .js/.html のどこからも参照されていない(名前が 1 回だけ)
  6 dup-block     … 同じ行の並びが --dup 行以上、別の場所にもある(空白と行末のコメントをそろえて比べる。src/ と dev/ の .py・.js。tests/ は除く)
  7 no-docstring  … モジュールの先頭に説明(docstring)が無い .py(tests/ は除く)
  8 version       … 版は全体で 1 つ(ytt/version.py)。そこが正しい形か、各ツールの定数・画面に版の数字を直に書いていないか
対象: src/ と dev/ と setup/。friend-apps/ の C# は見ない(csc の警告 /warn:4 で代える)。
"""
import argparse
import ast
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
               "KillJob": "tools.KillJob(1 か所に)", "_kill_on_close_job": "tools.KillJob(1 か所に)",
               # 別名の写し(2026-10-09。ytt_core 1.3.0 で足した小道具。docs/design/code-review-simplify-2026-10-08.md の A・G10)
               "unlink_quiet": "fsio.unlink_quiet", "file_stamp": "fsio.stamp", "rotate": "fsio.rotate",
               "read_json": "fsio.read_json_or", "_read_json_file": "fsio.read_json_or", "_inside": "fsio.is_inside",
               "dir_size": "fsio.dir_size", "_dir_bytes": "fsio.dir_size",
               "low_flags": "tools.no_window_flags(priority=\"low\")", "_flags": "tools.no_window_flags(priority=\"low\")",
               "_ytcap_flags": "tools.no_window_flags(priority=\"low\")", "child_flags": "tools.no_window_flags(priority=\"low\")",
               "_worker_flags": "tools.no_window_flags(new_group=True)", "kill_tree": "tools.kill_tree", "_ytcap_kill": "tools.kill_tree",
               "_python": "tools.python_exe", "_why": "tools.why", "rss_mb": "tools.process_memory_mb", "memory_mb": "tools.process_memory_mb",
               "peak_memory_mb": "tools.process_memory_mb(peak=True)", "parse_version_line": "tools.tool_version(first_line=True)",
               "plain_int": "schemas.plain_int", "_num_sec": "schemas.num", "drain_body": "httpsec.drain_body"}
IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
JS_FUNC = re.compile(r"^(?:\s*)function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", re.M)
# 版は全体で 1 つ(RS5-E。ytt/version.py)。正の VERSION が正しい形で、ほかに版の文字そのものを書いた所が無いこと
VERSION_FILE = ("src/ytt/version.py", r'^VERSION\s*=\s*"(\d+\.\d+\.\d+)"')
VERSION_LITERALS = [   # 版の数字そのものを書いてはいけない所(version.py から読む)
    ("src/studio/serve.py", r'^SERVER_VERSION\s*=\s*"(\d[^"]*)"'), ("src/editor/serve.py", r'^SERVER_VERSION\s*=\s*"(\d[^"]*)"'),
    ("src/studio/core.js", r"APP_VERSION\s*=\s*['\"](\d[^'\"]*)['\"]"), ("src/editor/app.js", r"APP_VERSION\s*=\s*['\"](\d[^'\"]*)['\"]"),
    ("src/pipeline/pack/cut2resolve_core.py", r'^VERSION\s*=\s*"(\d[^"]*)"'), ("src/home/launch.py", r'^VERSION\s*=\s*"(\d[^"]*)"'),
    ("src/pipeline/ingest/recorder.py", r'^VERSION\s*=\s*"(\d[^"]*)"'), ("src/analytics/__init__.py", r'^VERSION\s*=\s*"(\d[^"]*)"'),
    ("src/pipeline/pack/srt2resolve.py", r'^VERSION\s*=\s*"(\d[^"]*)"'), ("src/pipeline/pack/auto_cut.py", r'^VERSION\s*=\s*"(\d[^"]*)"'),
    ("src/flow/live_export.py", r'^VERSION\s*=\s*"(\d[^"]*)"'),
]


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


def unused_imports(path, nodes, src):
    """nodes = ast.walk の結果(main で 1 回だけ作って 3 つの検査に渡す)。属性の根(a.b.c の a)は ast.walk が Name としても返すので、Name だけ見ればよい"""
    if os.path.basename(path) == "__init__.py":
        return []
    lines = src.splitlines()
    imported, used, strs = {}, set(), []
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            if node.lineno <= len(lines) and "noqa" in lines[node.lineno - 1]:
                continue
            for a in node.names:
                name = (a.asname or a.name).split(".")[0]
                if name != "*":
                    imported[name] = node.lineno
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strs.append(node.value)
    text_names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", "\n".join(strs)))
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


def long_functions(path, nodes, src, limit):
    out = []
    lines = src.splitlines()
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = node.end_lineno - node.lineno + 1
            if n > limit and not has_mark(lines, node.lineno, "lint: long"):
                out.append((node.lineno, node.name, n))
    return out


def dup_helpers(path, nodes, src):
    if "/ytt/" in rel(path):
        return []
    out, lines = [], src.splitlines()
    for node in nodes:
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


def dup_blocks(n, corpus):
    """同じ正規化した行の並び(n 行以上)が 2 か所以上にあるものを探す(tests は除く。空行・括弧だけの行は数えない)。
    窓は行の並びそのもの(タプル)をキーにする(ハッシュにしない = 衝突も無く、12 行を結んで符号化する手間も要らない)"""
    # tests/ は除く。ui-kit.js は正本(ui-kit/ui-kit.js)だけ入れる(各ツールの写しは数えない)
    files = [p for p in list(walk(SRC, (".py", ".js"))) + list(walk(os.path.join(REPO, "dev"), (".py",)))
             if (not is_test(p) and not p.endswith("ui-kit.js")) or p.endswith(os.path.join("ui-kit", "ui-kit.js"))]
    windows = defaultdict(list)
    for p in files:
        raw = (corpus.texts.get(p) or read(p)).splitlines()
        norm = [(i + 1, norm_line(l)) for i, l in enumerate(raw)]
        norm = [(ln, t) for ln, t in norm if t and t not in ("}", "{", "});", ")", "]", "},", "],", "else:", "try:", "else {", "} else {", "return", "pass", "continue", "break")]
        texts = [t for _, t in norm]
        for i in range(0, max(0, len(norm) - n + 1)):
            windows[tuple(texts[i:i + n])].append((rel(p), norm[i][0]))
    groups = {h: locs for h, locs in windows.items() if len(locs) >= 2}
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
    rel, pat = VERSION_FILE
    m = re.search(pat, read(os.path.join(REPO, rel)), re.M)
    if not m:
        out.append(("version.py", [(rel, None)]))
    for relpath, pat in VERSION_LITERALS:
        m = re.search(pat, read(os.path.join(REPO, relpath)), re.M)
        if m:
            out.append(("版の数字を直に書いている(ytt/version.py から読む)", [(relpath, m.group(1))]))
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

    def add(kind, file, line, name, **extra):
        issues[kind].append(dict({"file": file, "line": line, "name": name}, **extra))

    for p in py_files():
        src = corpus.texts.get(p) or read(p)   # Corpus が読んだ写し(同じファイルを読み直さない)
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            add("unused-import", rel(p), e.lineno or 0, "SyntaxError: %s" % e.msg)
            continue
        nodes = list(ast.walk(tree))   # 木をなめるのは 1 ファイル 1 回
        for ln, name in unused_imports(p, nodes, src):
            add("unused-import", rel(p), ln, name)
        for ln, name, n in long_functions(p, nodes, src, a.long_test if is_test(p) else a.long):
            add("long-function", rel(p), ln, name, lines=n)
        if not is_test(p):
            for ln, name in dead_names(p, tree, src, corpus):
                add("dead-name", rel(p), ln, name)
            for ln, name, hint in dup_helpers(p, nodes, src):
                add("dup-helper", rel(p), ln, name, hint=hint)
            if missing_docstrings(p, tree):
                add("no-docstring", rel(p), 1, "docstring")
    for f, ln, name in js_dead(corpus):
        add("js-dead", f, ln, name)
    for locs in dup_blocks(a.dup, corpus):
        add("dup-block", locs[0][0], locs[0][1], "同じ %d 行以上: " % a.dup + "・".join("%s:%d" % loc for loc in locs[1:4]))
    for tool, found in version_mismatch():
        add("version", found[0][0], 1, tool + ": " + "・".join("%s=%s" % (os.path.basename(f), v) for f, v in found))
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
