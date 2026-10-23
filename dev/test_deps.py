#!/usr/bin/env python3
"""単体テストを、変えたファイルとの import のつながりから選ぶ(dev/land_gate.py の関所が使う。人の作業なしの候補 5・10-23)。

    py -3.12 dev/test_deps.py <変えたファイル>...      # 選んだテストの一覧(と、つながりの分からないファイル)
    py -3.12 dev/test_deps.py --history 150            # 抜けの検査: main の最近のコミットで、ソースと一緒に直したテストが選ばれるか

つながり(どれか 1 つでも = 依存。抜けないように広めに取る):
  1 import(ast で読む。`import a.b`・`from a import b`(b が別のファイルならそれも)・相対の `from . import x`)。
    名前の置き場所は src/(パッケージ)と、テストや起動が sys.path に足す平らなフォルダ(src/editor・src/studio・tests の各フォルダ)。
    名前だけの import(`import ed_state`)で、同じ名前のファイルが複数あれば全部
  2 文字列の中の名前: A の文字列の値(.py は ast の文字列。説明の文とコメントは見ない = 全部がつながらないように)に、B のファイル名(app.js・pack.lua・x.py)か
    B のモジュールの名前("eval.tools.eval_asr")があれば A は B を使う(画面のファイルを読むテスト・子のプロセスで動かす道具・-m で動かす部品)。
    .py でないファイル(画面・Lua・設定)は文の全部からファイル名を探す
選ぶ = 変えたファイルから逆向きにたどって着くテスト(run_unit の単位)。変えたファイルが .py でなく、どのファイルの文にも名前が出なければ
「分からない」として返す(関所はそのファイルの層の決まりで選ぶ = 今までどおり)。
"""
import ast
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCAN = ("src", "tests", "dev", "setup")
TEXT_EXT = (".py", ".js", ".mjs", ".cjs", ".css", ".html", ".json", ".lua", ".txt", ".bat", ".ps1", ".md", ".cs", ".vbs", ".drb", ".svg", ".tsv")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PATHLIKE = re.compile(r"^[\w\-./\:*?]+$")   # 道かファイル名だけの文字列(glob の * ? も)
_FILE = re.compile(r"[\w\-]+\.(?:py|js|mjs|cjs|css|html|json|lua|bat|ps1|vbs|drb|svg|tsv)\b")


def _strings(tree):
    """ast の文字列の値(説明の文 = 関数・クラス・モジュールの頭の文字列は除く)"""
    if tree is None:
        return []
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            b = node.body[0]
            if isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant):
                docs.add(id(b.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _pick(cands, frm):
    """同じ名前のファイルが複数あるとき、使う側から見て近い物: 同じフォルダ > フォルダの名前が使う側の道に出てくる物(tests/editor → src/editor)> 全部"""
    if len(cands) < 2:
        return set(cands)
    d = os.path.dirname(frm)
    same = [c for c in cands if os.path.dirname(c) == d]
    if same:
        return set(same)
    parts = set(d.split("/"))
    near = [c for c in cands if os.path.basename(os.path.dirname(c)) in parts]
    return set(near or cands)


def _files(root):
    out = []
    for top in SCAN:
        for d, dirs, names in os.walk(os.path.join(root, top)):
            dirs[:] = [x for x in dirs if not x.startswith((".", "__pycache__", "node_modules"))]
            out += [os.path.relpath(os.path.join(d, n), root).replace("\\", "/") for n in names if n.endswith(TEXT_EXT)]
    return sorted(out)


def _read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


class Graph:
    """ファイル → 使うファイルの集まり(import と文字列の中の名前)"""

    def __init__(self, root=REPO):
        self.root = root
        self.files = _files(root)
        self.py = [f for f in self.files if f.endswith(".py")]
        self.dotted = {}   # "pipeline.transcribe.llm" -> ファイル
        self.bare = {}     # "ed_state" -> [ファイル]
        for f in self.py:
            stem = f[:-3]
            if f.startswith("src/"):
                mod = stem[4:].replace("/", ".")
                if mod.endswith(".__init__"):
                    mod = mod[:-9]
                self.dotted[mod] = f
            name = os.path.basename(stem)
            if name != "__init__":
                self.bare.setdefault(name, []).append(f)
        self.by_name = {}  # 文字列で出てくる名前(拡張子なし・ファイル名)-> [ファイル]
        for f in self.files:
            base = os.path.basename(f)
            self.by_name.setdefault(base, []).append(f)
            if f.endswith(".py") and not base.startswith("__"):
                self.by_name.setdefault(base[:-3], []).append(f)
        self.deps = {f: self._deps(f) for f in self.files}
        self.rdeps = {}
        for f, ds in self.deps.items():
            for d in ds:
                self.rdeps.setdefault(d, set()).add(f)

    def _resolve(self, mod, frm):
        """import の名前 -> ファイルの集まり(見つからなければ空)"""
        if mod in self.dotted:
            return {self.dotted[mod]}
        head = mod.split(".")[0]
        if "." not in mod and head in self.bare:
            return _pick(self.bare[head], frm)
        return set()

    def _deps(self, f):
        text = _read(self.root, f)
        out = set()
        if f.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            pkg = f[4:-3].replace("/", ".").rsplit(".", 1)[0] if f.startswith("src/") else ""
            for node in ast.walk(tree) if tree else []:
                if isinstance(node, ast.Import):
                    for a in node.names:
                        parts = a.name.split(".")
                        for k in range(1, len(parts) + 1):
                            out |= self._resolve(".".join(parts[:k]), f)
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    if node.level:
                        up = pkg.split(".") if pkg else []
                        up = up[:len(up) - (node.level - 1)] if node.level > 1 else up
                        base = ".".join([x for x in up + ([node.module] if node.module else []) if x])
                    if base:
                        out |= self._resolve(base, f)
                    for a in node.names:
                        out |= self._resolve((base + "." if base else "") + a.name, f) if base else self._resolve(a.name, f)
        if f.endswith(".py"):   # .py は文字列の値だけを見る(説明の文・コメントの中のファイル名で全部がつながらないように)
            strs = _strings(tree)
            for x in strs:
                if not _PATHLIKE.match(x.strip()):   # 文の中のファイル名(エラーの文・説明)は見ない。道かファイル名だけの文字列
                    continue
                for name in _FILE.findall(x):
                    if name.endswith(".py") and not f.startswith(("tests/", "dev/")):
                        continue   # 本体が道で起こす別のプロセス(録画など)は、本体を import しても動かない = つながりにしない(テストと道具が起こすときは数える)
                    out |= self._named(name, x, f)
                if x in self.dotted:   # "eval.tools.eval_asr" など(-m で動かす・名前で読み込む)
                    out.add(self.dotted[x])
        else:   # 画面・Lua・設定は、.py でないファイルだけを指す(画面は Python を読み込まない。説明の中の x.py でつながらないように)
            for name in _FILE.findall(text):
                if not name.endswith(".py"):
                    out |= self._named(name, "", f)
        out.discard(f)
        return out

    def _named(self, name, s, frm):
        """文字列の中のファイル名 -> ファイル。同じ名前が複数あれば、文字列の道(a/b/x.js)の後ろが合う物、無ければ置き場所の近い物(_pick)"""
        cands = self.by_name.get(name, ())
        if len(cands) < 2:
            return set(cands)
        path = s.replace("\\", "/")
        m = re.search(r"([\w\-./]+/)?" + re.escape(name), path)
        tail = (m.group(1) or "").strip("./") if m else ""
        if tail:
            hit = [c for c in cands if c.rsplit("/", 1)[0].endswith(tail)]
            if hit:
                return set(hit)
        return _pick(cands, frm)

    def users(self, changed):
        """変えたファイルを(たどって)使うファイルの集まり(変えたファイルも入る)"""
        seen, todo = set(changed), list(changed)
        while todo:
            f = todo.pop()
            for g in self.rdeps.get(f, ()):
                if g not in seen:
                    seen.add(g)
                    todo.append(g)
        return seen

    def select(self, changed, tests):
        """変えたファイル → (選んだテストの集まり, 分からないファイル)。tests = 単体の単位のファイル(run_unit の rel)"""
        unknown = [p for p in changed if p not in self.deps or (not p.endswith(".py") and not self.rdeps.get(p) and p not in tests)]
        hit = self.users([p for p in changed if p in self.deps])
        return {t for t in tests if t in hit}, unknown


def _git(*args):
    r = subprocess.run(["git"] + list(args), cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    return r.stdout


def history(n, graph, tests, layer_select=None):
    """main の最近 n 個のコミット(版上げ・取り込みを除く)で、ソースと一緒に直したテストの単位が選ばれるか -> 結果の辞書"""
    out = {"commits": 0, "pairs": 0, "missed": [], "sel": 0, "layer": 0}
    for line in _git("log", "--no-merges", "-n", str(n), "--format=%h", "main").split():
        files = [p for p in _git("show", "--name-only", "--format=", line).splitlines() if p]
        src = [p for p in files if not p.startswith("tests/") and p.startswith(("src/", "dev/", "setup/"))]
        touched = [p for p in files if p in tests]
        if not src or not touched:
            continue
        out["commits"] += 1
        sel, _unk = graph.select(files, tests)
        out["sel"] += len(sel)
        if layer_select:
            out["layer"] += len(layer_select(files))
        for t in touched:
            out["pairs"] += 1
            if t not in sel:
                out["missed"].append((line, t, src[:3]))
    return out


def main(argv):
    sys.path.insert(0, HERE)
    import run_unit
    tests = {u.rel for u in run_unit.build_units(REPO)}
    g = Graph()
    if argv[:1] == ["--history"]:
        res = history(int(argv[1]) if len(argv) > 1 else 100, g, tests)
        print("コミット %d・ソースと一緒に直したテスト %d・選ばれなかった %d" % (res["commits"], res["pairs"], len(res["missed"])))
        for c, t, s in res["missed"]:
            print("  抜け %s %s(変えた %s)" % (c, t, "・".join(s)))
        return 1 if res["missed"] else 0
    sel, unk = g.select(argv, tests)
    for t in sorted(sel):
        print(t)
    for p in unk:
        print("分からない: " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
