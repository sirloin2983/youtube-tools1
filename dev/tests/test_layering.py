"""役割の層の import の向きを守るテスト(役割で組み直す計画 `plan/role-restructure.md` の 4 節 1。RS0)。

src/ の .py(tests/ を除く)の import を解き、`dev/layer_map.py` の層の表で向きを検査する。
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


def module_index(files):
    """モジュール名 → [パス]。ツールの中は裸の名前で import するので、同じ名前が複数のフォルダにあることがある"""
    idx = {}
    for p in files:
        idx.setdefault(os.path.splitext(os.path.basename(p))[0], []).append(p)
    return idx


def resolve(name, from_dir, idx):
    """import の名前 → ファイル。同じフォルダを優先し、無ければ src/ の中で 1 つだけ見つかる物。見つからなければ None"""
    same = os.path.join(from_dir, name + ".py")
    if os.path.isfile(same):
        return same
    pkg_init = os.path.join(SRC, name, "__init__.py")
    if os.path.isfile(pkg_init):
        return pkg_init
    cands = [p for p in idx.get(name, []) if "/tests/" not in rel(p)]
    return cands[0] if len(cands) == 1 else None


def imports_of(path, idx):
    """path が import しているリポジトリの中のファイル(src/ の中)の集合"""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    here = os.path.dirname(path)
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                top = a.name.split(".")[0]
                f = resolve(top, here, idx)
                if f:
                    found.add(f)
        elif isinstance(n, ast.ImportFrom):
            if n.level:   # 相対 import(ytt_core の中)
                base = here
                for _ in range(n.level - 1):
                    base = os.path.dirname(base)
                if n.module:
                    f = os.path.join(base, *n.module.split(".")) + ".py"
                    if os.path.isfile(f):
                        found.add(f)
                for a in n.names:
                    f = os.path.join(base, *((n.module.split(".") if n.module else []) + [a.name])) + ".py"
                    if os.path.isfile(f):
                        found.add(f)
                continue
            top = (n.module or "").split(".")[0]
            pkg = os.path.join(SRC, top)
            if os.path.isdir(pkg):   # from ytt_core import fsio / from analytics import service
                rest = n.module.split(".")[1:]
                if rest:
                    f = os.path.join(pkg, *rest) + ".py"
                    found.add(f if os.path.isfile(f) else os.path.join(pkg, "__init__.py"))
                else:
                    for a in n.names:
                        f = os.path.join(pkg, a.name + ".py")
                        found.add(f if os.path.isfile(f) else os.path.join(pkg, "__init__.py"))
            else:
                f = resolve(top, here, idx)
                if f:
                    found.add(f)
    found.discard(path)
    return found


def violations():
    """[(import する側, される側, 側の層, 先の層)]。表に無いファイルは unmapped に"""
    files = source_files()
    idx = module_index(files)
    bad, unmapped = [], []
    for p in files:
        r = rel(p)
        src_layer = LM.layer_of(r)
        if src_layer is None:
            unmapped.append(r)
            continue
        for q in sorted(imports_of(p, idx)):
            rq = rel(q)
            dst_layer = LM.layer_of(rq)
            if dst_layer is None:
                if rq not in unmapped:
                    unmapped.append(rq)
                continue
            if not LM.allowed(src_layer, dst_layer):
                bad.append((r, rq, src_layer, dst_layer))
    return bad, unmapped


class TestLayering(unittest.TestCase):
    def test_every_file_has_a_layer(self):
        _, unmapped = violations()
        self.assertEqual(unmapped, [], "dev/layer_map.py の FILES に行き先が無い: %s" % ", ".join(unmapped))

    def test_direction_matches_known_list(self):
        bad, _ = violations()
        actual = {(a, b) for a, b, _, _ in bad}
        new = sorted(actual - LM.KNOWN)
        fixed = sorted(LM.KNOWN - actual)
        msg = []
        if new:
            msg.append("新しい向きの違反(低い層が高い層を import): " + ", ".join("%s -> %s" % x for x in new))
        if fixed:
            msg.append("直った違反は KNOWN から消す: " + ", ".join("%s -> %s" % x for x in fixed))
        self.assertFalse(msg, "\n".join(msg))

    def test_layer_order(self):
        self.assertTrue(LM.allowed("human", "pipeline"))
        self.assertFalse(LM.allowed("pipeline", "human"))
        self.assertTrue(LM.allowed("app", "eval"))
        self.assertFalse(LM.allowed("ytt", "pipeline"))


if __name__ == "__main__":
    if "--list" in sys.argv:
        bad, unmapped = violations()
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
