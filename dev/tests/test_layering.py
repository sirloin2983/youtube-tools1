"""役割の層の import の向きを守るテスト(役割で組み直す計画 `plan/role-restructure.md` の 4 節 1。RS0)。

src/ の .py(tests/ を除く)の import を解き、`dev/layer_map.py` の層の表(許される相手の表 ALLOWED)で向きを検査する。
② 管理(src/flow)に ① の別名だけの関数が無いことも検査する(test_flow_is_not_alias。RS6 a-0)。
違反は `layer_map.KNOWN` の一覧と一致しなければならない(減らすだけ。新しい違反・表に無いファイルは落ちる)。

    python -m unittest dev/tests/test_layering.py
    python dev/tests/test_layering.py --list      # 違反の一覧を KNOWN に貼れる形で出す
"""
import ast
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import layer_map as LM   # noqa: E402

SRC = os.path.join(REPO, "src")
SKIP = {"tests", "__pycache__", "node_modules", "vendor"}


def rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def source_files():
    out = []
    for d, dirs, files in os.walk(SRC):
        dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(d, f))
    return sorted(out)


def parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), path)


def module_index(files):
    """モジュール名 → [パス]。ツールの中は裸の名前で import するので、同じ名前が複数のフォルダにあることがある"""
    idx = {}
    for p in files:
        idx.setdefault(os.path.splitext(os.path.basename(p))[0], []).append(p)
    return idx


def resolve(name, from_dir, idx):
    """裸の名前の import(ツールのフォルダの中の `import pack` など)→ ファイル。同じフォルダを優先し、無ければ src/ の中で
    1 つだけ見つかる物。見つからなければ None"""
    same = os.path.join(from_dir, name + ".py")
    if os.path.isfile(same):
        return same
    cands = [p for p in idx.get(name, []) if "/tests/" not in rel(p)]
    return cands[0] if len(cands) == 1 else None


def find_module(base, parts):
    """base の下の点区切りの名前 parts → (ファイル, 残りの名前)。a/b/c.py → a/b/c/__init__.py → a/b.py → a/b/__init__.py … の順に
    いちばん深い物を探す。残りの名前は、パッケージの __init__.py に落ちたときの、その中の名前(転送の付け替えに使う)"""
    for i in range(len(parts), 0, -1):
        head = os.path.join(base, *parts[:i])
        for f in (head + ".py", os.path.join(head, "__init__.py")):
            if os.path.isfile(f):
                return f, parts[i:]
    return None, []


def forward(f, rest):
    """転送のファイル(layer_map.FORWARDERS)に落ちた import を実体へ付け替える。転送でなければそのまま"""
    table = LM.FORWARDERS.get(rel(f)) if f else None
    if not table or not rest:
        return f
    real = table.get(rest[0]) or table["*"].format(name=rest[0])
    return os.path.join(REPO, *real.split("/"))


def imports_of(path, idx):
    """path が import しているリポジトリの中のファイル(src/ の中)→ 裸の名前で解いたか(bool)の辞書"""
    tree = parse(path)
    here = os.path.dirname(path)
    found = {}

    def add(f, bare=False):
        if f and f != path:
            found[f] = found.get(f, False) or bare

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                parts = a.name.split(".")
                if os.path.isdir(os.path.join(SRC, parts[0])):   # import ytt_core / import pipeline.pack.pack
                    add(forward(*find_module(SRC, parts)))
                else:
                    add(resolve(parts[0], here, idx), bare=True)
        elif isinstance(n, ast.ImportFrom):
            if n.level:   # 相対 import(パッケージの中)
                base = here
                for _ in range(n.level - 1):
                    base = os.path.dirname(base)
                mod = n.module.split(".") if n.module else []
                for a in n.names:
                    add(forward(*find_module(base, mod + [a.name])))
                continue
            parts = (n.module or "").split(".")
            if os.path.isdir(os.path.join(SRC, parts[0])):   # from ytt_core import fsio / from pipeline.pack import pack
                for a in n.names:
                    add(forward(*find_module(SRC, parts + [a.name])))
            else:
                add(resolve(parts[0], here, idx), bare=True)
    return found


def violations():
    """([(import する側, される側, 側の層, 先の層)], 表に無いファイル, 裸の名前で層のパッケージを読んでいる [(側, 先)])"""
    files = source_files()
    idx = module_index(files)
    bad, unmapped, bare_bad = [], [], []
    for p in files:
        r = rel(p)
        if r in LM.FORWARDERS:   # 転送は旧い名前を残すためだけの物。読み手は実体へ付け替えて検査する
            continue
        src_layer = LM.layer_of(r)
        if src_layer is None:
            unmapped.append(r)
            continue
        for q, bare in sorted(imports_of(p, idx).items()):
            rq = rel(q)
            if bare and any(rq.startswith(d + "/") for d in LM.DIRS):
                bare_bad.append((r, rq))
            dst_layer = LM.layer_of(rq)
            if dst_layer is None:
                if rq not in unmapped:
                    unmapped.append(rq)
                continue
            if not LM.allowed(src_layer, dst_layer):
                bad.append((r, rq, src_layer, dst_layer))
    return bad, unmapped, bare_bad


ALIAS_OK = "# flow: alias ok"


def _pipeline_names(tree):
    """モジュールの中で pipeline のモジュールか pipeline から import した物を指す名前(import pipeline.x は pipeline、as は別名)"""
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] == "pipeline":
                    names.add(a.asname or "pipeline")
        elif isinstance(n, ast.ImportFrom) and not n.level and (n.module or "").split(".")[0] == "pipeline":
            for a in n.names:
                names.add(a.asname or a.name)
    return names


def _root_name(node):
    """a.b.c → a(名前の連なりでなければ None)"""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _passes_params_through(fn, call, method):
    """call の引数が fn の受け取った引数を(足し引きなく)そのまま渡しているか"""
    a = fn.args
    params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    if method and params:
        params = params[1:]   # self・cls
    star = {x.arg for x in (a.vararg, a.kwarg) if x}
    used = []
    for x in call.args:
        if isinstance(x, ast.Starred) and isinstance(x.value, ast.Name) and x.value.id in star:
            used.append(x.value.id)
        elif isinstance(x, ast.Name) and x.id in params:
            used.append(x.id)
        else:
            return False
    for k in call.keywords:
        if isinstance(k.value, ast.Name) and (k.value.id in params or (k.arg is None and k.value.id in star)):
            used.append(k.value.id)
        else:
            return False
    return sorted(used) == sorted(params + list(star))


def _is_alias(fn, pnames, method):
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]   # docstring
    if len(body) != 1 or not isinstance(body[0], ast.Return) or not isinstance(body[0].value, ast.Call):
        return False
    call = body[0].value
    return _root_name(call.func) in pnames and _passes_params_through(fn, call, method)


def flow_aliases(files=None):
    """src/flow の関数(メソッドも)で、本体が `return <pipeline の名前>.<名前>(受け取った引数そのまま)` の 1 文だけの物 → ["パス:行 名前"]。
    def の行・return の行の末尾か、def(飾りがあればその上)の直前の行に `# flow: alias ok` があれば除く"""
    if files is None:
        files = []
        for d, dirs, fs in os.walk(os.path.join(SRC, "flow")):
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
            files += [os.path.join(d, f) for f in fs if f.endswith(".py")]
    out = []
    for p in sorted(files):
        with open(p, encoding="utf-8") as f:
            src = f.read()
        lines = src.splitlines()
        tree = ast.parse(src, p)
        pnames = _pipeline_names(tree)
        if not pnames:
            continue
        methods = {id(fn) for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for fn in c.body}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_alias(fn, pnames, id(fn) in methods):
                continue
            top = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
            marks = [fn.lineno, fn.body[-1].lineno, top - 1]
            if any(0 < i <= len(lines) and ALIAS_OK in lines[i - 1] for i in marks):
                continue
            out.append("%s:%d %s" % (rel(p) if p.startswith(REPO) else p, fn.lineno, fn.name))
    return out


def package_inits_with_imports():
    """層のパッケージ(DIRS)の __init__.py で import している物。基盤を読むだけで上の層を引きずらないよう、__init__ は説明と定数だけ"""
    out = []
    for d in LM.DIRS:
        for dirpath, dirs, files in os.walk(os.path.join(REPO, *d.split("/"))):
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
            if "__init__.py" in files:
                p = os.path.join(dirpath, "__init__.py")
                tree = parse(p)
                if any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree)):
                    out.append(rel(p))
    return out


class TestLayering(unittest.TestCase):
    def test_every_file_has_a_layer(self):
        _, unmapped, _ = violations()
        self.assertEqual(unmapped, [], "dev/layer_map.py の FILES に行き先が無い: %s" % ", ".join(unmapped))

    def test_known_only_shrinks(self):
        """KNOWN に手で足して黙らせない(上限は KNOWN_MAX。RS0 の 69 件 → RS5 で 0 → RS6 a-0 で ③④ → ① の 54 件。減ったら KNOWN_MAX も下げる)"""
        self.assertLessEqual(len(LM.KNOWN), LM.KNOWN_MAX)

    def test_no_bare_import_into_layer_packages(self):
        """層のパッケージの部品を裸の名前(`import pack`)で読まない。`pack` と `pipeline.pack.pack` が別のモジュールになる事故を防ぐ。
        パッケージの中は兄弟を相対(`from . import x`)、外からは絶対(`from pipeline.pack import pack`)"""
        _, _, bare_bad = violations()
        self.assertEqual(bare_bad, [], "裸の名前で層のパッケージを読んでいる: " + ", ".join("%s -> %s" % x for x in bare_bad))

    def test_package_inits_do_not_import(self):
        self.assertEqual(package_inits_with_imports(), [])

    def test_direction_matches_known_list(self):
        bad, _, _ = violations()
        actual = {(a, b) for a, b, _, _ in bad}
        new = sorted(actual - LM.KNOWN)
        fixed = sorted(LM.KNOWN - actual)
        msg = []
        if new:
            msg.append("新しい向きの違反(layer_map.ALLOWED に無い向きの import): "+ ", ".join("%s -> %s" % x for x in new))
        if fixed:
            msg.append("直った違反は KNOWN から消す: " + ", ".join("%s -> %s" % x for x in fixed))
        self.assertFalse(msg, "\n".join(msg))

    def test_resolver(self):
        """入れ子のパッケージ(from manage.cases import txindex)と、転送の付け替え"""
        f, rest = find_module(SRC, ["pipeline", "pack", "nothing_here"])
        self.assertEqual((rel(f), rest), ("src/pipeline/pack/__init__.py", ["nothing_here"]))
        init = os.path.join(SRC, "pipeline", "pack", "__init__.py")
        saved = LM.FORWARDERS
        try:
            LM.FORWARDERS = {"src/pipeline/pack/__init__.py": {"a": "src/x/a.py", "*": "src/y/{name}.py"}}
            self.assertEqual(rel(forward(init, ["a"])), "src/x/a.py")
            self.assertEqual(rel(forward(init, ["b", "c"])), "src/y/b.py")
            self.assertEqual(forward(init, []), init)
        finally:
            LM.FORWARDERS = saved

    def test_layer_order(self):
        """ALLOWED の表(RS6 a-0): ③④ は ① を直に読まず ② を通す・⑤ は ① を読んでよい・app は全部"""
        self.assertEqual(LM.LAYERS, ["ytt", "pipeline", "flow", "human", "manage", "eval", "app"])
        self.assertEqual(set(LM.ALLOWED), set(LM.LAYERS))
        self.assertTrue(LM.allowed("flow", "pipeline"))
        self.assertFalse(LM.allowed("pipeline", "flow"))
        self.assertTrue(LM.allowed("human", "flow"))
        self.assertFalse(LM.allowed("human", "pipeline"))
        self.assertFalse(LM.allowed("manage", "pipeline"))
        self.assertTrue(LM.allowed("manage", "human"))
        self.assertFalse(LM.allowed("flow", "human"))
        self.assertTrue(LM.allowed("eval", "pipeline"))
        self.assertFalse(LM.allowed("pipeline", "human"))
        self.assertTrue(LM.allowed("app", "eval"))
        self.assertFalse(LM.allowed("ytt", "pipeline"))
        self.assertTrue(LM.allowed("ytt", "ytt"))
        self.assertEqual(LM.layer_of("src/flow/x.py"), "flow")

    def test_flow_is_not_alias(self):
        """② に ① の別名だけの関数を作らない(RS6 決定 3-29。例外は `# flow: alias ok`)"""
        self.assertEqual(flow_aliases(), [], "② の関数が ① をそのまま呼ぶだけ(① を直に呼ぶか、② の責任を足す): ")

    def test_flow_alias_detector(self):
        import tempfile
        code = "\n".join([
            "from pipeline.pack import pack",
            "import pipeline.transcribe.fill as fl",
            "from pipeline.transcribe.recognize import transcribe_rows",
            "",
            "def a(job, spec):",
            '    """別名"""',
            "    return pack.build(job, spec)",
            "",
            "def b(x, *rest, **kw):",
            "    return fl.run(x, *rest, **kw)",
            "",
            "def c(job):",
            "    return transcribe_rows(job=job)",
            "",
            "class K:",
            "    def m(self, x):",
            "        return pack.build(x)",
            "",
            "def ok1(job):   " + ALIAS_OK,
            "    return pack.build(job)",
            "",
            ALIAS_OK,
            "def ok2(job):",
            "    return pack.build(job)",
            "",
            "def adds(job):",
            "    return pack.build(job, 3)",
            "",
            "def drops(job, spec):",
            "    return pack.build(job)",
            "",
            "def two(job):",
            "    x = pack.build(job)",
            "    return x",
            "",
            "def notpipe(job):",
            "    return len(job)",
            "",
        ])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.py")
            with open(p, "w", encoding="utf-8") as f:
                f.write(code)
            got = [x.rsplit(" ", 1)[1] for x in flow_aliases([p])]
        self.assertEqual(got, ["a", "b", "c", "m"])


if __name__ == "__main__":
    if "--list" in sys.argv:
        bad, unmapped, _ = violations()
        by = {}
        for a, b, la, lb in bad:
            by.setdefault((la, lb), []).append((a, b))
        for k in sorted(by):
            print("# %s -> %s: %d" % (k[0], k[1], len(by[k])))
            for a, b in by[k]:
                print('    ("%s", "%s"),' % (a, b))
        print("# 違反 %d 件・表に無いファイル %d 件 %s" % (len(bad), len(unmapped), unmapped))
    else:
        unittest.main()
