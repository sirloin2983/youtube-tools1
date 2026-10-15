#!/usr/bin/env python3
"""コードの見直しの合格の基準を測る道具(読むだけ。基準は `notes:docs/spec/code.md`)。

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
  9 ref-path/ref-gone/ref-layer … 説明文(docstring とコメント。tests/ は除く)の参照が戻らない検査: 無い .py のパス・もう無い名前(ed_alt など)・先頭の説明の層の番号がフォルダと合わない。
                    過去の経緯として書くなら行に `lint: ref <理由>`。`notes:`・`git:` の後ろは見ない(notes_tool check が見る)
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
               # 別名の写し(2026-10-09。ytt_core 1.3.0 で足した小道具。notes:docs/design/reviews/code-review-simplify-2026-10-08.md の A・G10)
               "unlink_quiet": "fsio.unlink_quiet", "file_stamp": "fsio.stamp", "rotate": "fsio.rotate",
               "read_json": "fsio.read_json_or", "_read_json_file": "fsio.read_json_or", "_inside": "fsio.is_inside",
               "dir_size": "fsio.dir_size", "_dir_bytes": "fsio.dir_size",
               "low_flags": "tools.no_window_flags(priority=\"low\")", "_flags": "tools.no_window_flags(priority=\"low\")",
               "child_flags": "tools.no_window_flags(priority=\"low\")",
               "_worker_flags": "tools.no_window_flags(new_group=True)", "kill_tree": "tools.kill_tree",
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
    ("src/pipeline/pack/cut2resolve_core.py", r'^VERSION\s*=\s*"(\d[^"]*)"'), ("src/app/server.py", r'^VERSION\s*=\s*"(\d[^"]*)"'),
    ("src/pipeline/ingest/recorder.py", r'^VERSION\s*=\s*"(\d[^"]*)"'), ("src/manage/ops/analytics/__init__.py",r'^VERSION\s*=\s*"(\d[^"]*)"'),
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
        for root in (SRC, os.path.join(REPO, "dev"), os.path.join(REPO, "setup"), os.path.join(REPO, "friend-apps")):
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


# 説明文の参照が戻らない検査(OPT-H1 ③-R2。notes:plan/opt-human.md の ③ 全体)。対象は src/ dev/ setup/ の .py の docstring とコメント(tests/ と lint.py 自身は除く)
GONE_NAMES = ("ed_alt", "ed_jobs", "ed_learn", "ed_retime", "ed_ytcap", "ed_store", "ed_fill", "ed_llm", "ytt_core", "studio/common.py", "home/live_cleanup.py")
GONE_RE = re.compile(r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])" % "|".join(re.escape(n) for n in GONE_NAMES))
PATH_RE = re.compile(r"(?<![A-Za-z0-9_./:\\-])((?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_-]+\.py)(?![A-Za-z0-9_])")
LAYER_OF = {"pipeline": "①", "flow": "②", "human": "③", "manage": "④", "eval": "⑤"}   # src/ の直下のフォルダ → 層の番号(正は notes:docs/spec/overview.md の 2)
LAYER_RE = re.compile(r"([①②③④⑤])\s*(?:道具|管理|人の操作|人|データ|検証|テスト)")
# 一時的に許す物(件数を減らす方向だけ。OPT-M1・E1 で直したら外す)。キーは (kind, ファイル) → 理由
REF_ALLOW = {
    ("ref-path", "src/eval/drill/drill.py"): "OPT-E1 で直す",
    ("ref-path", "src/eval/drill/evalbatch.py"): "OPT-E1 で直す",
    ("ref-path", "src/eval/drill/metrics.py"): "OPT-E1 で直す",
    ("ref-path", "src/eval/fake/fake_worker.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/drill/evalbatch.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/drill/metrics.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/fake/fake_asr.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/tools/_evalcommon.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/tools/eval_asr.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/tools/eval_fill.py"): "OPT-E1 で直す",
    ("ref-gone", "src/eval/tools/eval_timing.py"): "OPT-E1 で直す",
    ("ref-layer", "src/eval/__init__.py"): "OPT-E1 で直す",
    ("ref-layer", "src/eval/drill/metrics.py"): "OPT-E1 で直す",
    ("ref-gone", "src/manage/cases/doclist.py"): "OPT-M1 で直す",
    ("ref-gone", "src/manage/cases/handoff_io.py"): "OPT-M1 で直す",
    ("ref-gone", "src/manage/cases/relink.py"): "OPT-M1 で直す",
    ("ref-layer", "src/manage/__init__.py"): "OPT-M1 で直す",
}


def doc_texts(tree, src):
    """説明文の本体 = docstring と # のコメント。[(行, 文字列)]。行は先頭行の番号(複数行の docstring は行ごとに分けて返す)"""
    import io
    import tokenize
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and isinstance(node.value.value, str):
            for i, line in enumerate(node.value.value.splitlines()):
                out.append((node.lineno + i, line))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def stale_refs(path, tree, src):
    """[(行, 種類, 名前)]。種類 = ref-path(無い .py のパス)・ref-gone(もう無い名前)・ref-layer(先頭の説明の層の番号がフォルダと合わない)。
    その行に `lint: ref <理由>` があれば除く(過去の経緯としての言及など)。`notes:`・`git:` の後ろのパスは見ない(notes_tool check が見る)"""
    r = rel(path)
    if is_test(path) or r in ("dev/lint.py", "dev/layer_map.py"):   # layer_map.py は旧い名前 → 新しい名前の表(旧い名前を書くのが仕事)
        return []
    lines = src.splitlines()
    out = []
    tops = set(os.listdir(SRC)) | {"src", "dev", "setup"}
    for ln, text in doc_texts(tree, src):
        if "lint: ref" in text or (ln <= len(lines) and "lint: ref" in lines[ln - 1]):
            continue
        for m in GONE_RE.finditer(text):
            out.append((ln, "ref-gone", m.group(0)))
        for m in PATH_RE.finditer(text):
            p = m.group(1)
            if p.split("/")[0] not in tops or any(c in text[m.start() - 1:m.start()] for c in "*<%"):
                continue
            base = REPO if p.split("/")[0] in ("src", "dev", "setup") else SRC
            if not os.path.isfile(os.path.join(base, p)):
                out.append((ln, "ref-path", p))
    # 先頭の説明の 1 行目(モジュールの docstring)の層の番号。src/<層>/ の下だけ
    parts = r.split("/")
    if len(parts) >= 3 and parts[0] == "src" and parts[1] in LAYER_OF and tree.body:
        first = tree.body[0]
        if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
            head = first.value.value.strip().splitlines()[0] if first.value.value.strip() else ""
            m = LAYER_RE.search(head)
            if m and m.group(1) != LAYER_OF[parts[1]] and "lint: ref" not in head:
                out.append((first.lineno, "ref-layer", "%s(%s は %s)" % (m.group(1), parts[1], LAYER_OF[parts[1]])))
    return sorted({x for x in out if (x[1], r) not in REF_ALLOW})


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
    issues = {k: [] for k in ("unused-import", "dead-name", "long-function", "dup-helper", "js-dead", "dup-block", "no-docstring", "version", "notes-path", "ref-path", "ref-gone", "ref-layer")}

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
        for ln, kind, name in stale_refs(p, tree, src):
            add(kind, rel(p), ln, name)
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
    # 資料のフォルダ(Obsidian の保管庫)の切れたパス = dev/notes_tool.py の check(資料のフォルダが無い PC では 0)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import notes_tool
    for where, ln, path in notes_tool.check():
        add("notes-path", where, ln, path)
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
