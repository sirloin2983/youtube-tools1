#!/usr/bin/env python3
"""コードの地図と言葉の索引を作る道具(AI のセッションがコードの場所を早く見つけるため)。

    python dev/code_map.py            # codemap/ を作り直す(index.md・層ごとの md・words.md)
    python dev/code_map.py --check    # 作り直さずに古い所だけ言う(古ければ終了コード 1。dev/lint.py の code-map が呼ぶ)
    python dev/code_map.py --missing  # 頭の説明が無いファイルの一覧(.py・.js・.cs)

対象は git ls-files の .py・.js・.cs(vendor と .min.js は除く)。1 ファイルにつき、パス・役目 1 行(頭の説明の 1 行目)・
主なクラスや関数(file:line)・受ける `/api/...` の口(file:line)を出す。言葉の索引は、手で書く dev/code_words.tsv
(画面の言葉 → コードの名前)から場所を引き、画面の文字列から集めた候補を後ろに付ける。
地図には行の番号が入るので、コードを直したら作り直す(lint が古さを言う)。rebase で地図がぶつかったら、どちらかを取ってから作り直す。
"""
import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "codemap")
WORDS = os.path.join(REPO, "dev", "code_words.tsv")
EXTS = (".py", ".js", ".cs")
HEAD_MAX = 150    # 役目の 1 行の長さ(文字)
SYM_MAX = 12      # 1 ファイルに出す名前の数

# 層(出す順)。(見出し, ファイル名, パスの頭の並び)。どれにも当たらない物は「その他」
LAYERS = [
    ("ytt(基盤)", "ytt", ("src/ytt/",)),
    ("① pipeline(道具 = データを加工する)", "pipeline", ("src/pipeline/",)),
    ("② flow(管理 = いつ・どの順で・どこに置くか)", "flow", ("src/flow/",)),
    ("③ human(人の操作)", "human", ("src/human/",)),
    ("④ manage(データ)", "manage", ("src/manage/",)),
    ("⑤ eval(検証)", "eval", ("src/eval/",)),
    ("src/app(入口と画面)", "app", ("src/app/",)),
    ("src/friendapp(友人の玄関)", "friendapp", ("src/friendapp/",)),
    ("その他の画面(editor・studio・ui-kit・cut2resolve)", "tools", ("src/",)),
    ("dev・setup(開発の道具)", "dev", ("dev/", "setup/")),
    ("friend-apps・chrome-ext(C# のアプリ・拡張)", "apps", ("friend-apps/", "chrome-ext/")),
]
ROUTE = re.compile(r"^/?(?:friend/|live/)?api/[A-Za-z0-9_\-/.]*$")
JS_ROUTE = re.compile(r"""['"`]/?((?:friend/|live/)?api/[A-Za-z0-9_\-/.]+)""")
JS_SYM = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(|class\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>|class\b))")
CS_CLASS = re.compile(r"^\s*(?:(?:public|internal|private|protected|static|sealed|abstract|partial)\s+)*(?:class|struct|enum|interface)\s+([A-Za-z_]\w*)")
CS_METHOD = re.compile(r"^\s+(?:(?:public|internal|protected|static|override|async|virtual)\s+)+[\w<>\[\],. ?]+\s+([A-Z]\w*)\s*\(")
JP = re.compile(r"[぀-ヿ一-鿿]")
UI_STR = re.compile(r"""(?:text:\s*|textContent\s*=\s*|title:\s*|label:\s*|placeholder:\s*|Text\s*=\s*)(['"`])([^'"`\n]{2,24})\1""")
HTML_TEXT = re.compile(r">([^<>\n]{2,24})<")


def git_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(p for p in out.split("\0") if p.endswith(EXTS) and not skipped(p))


def skipped(p):
    return "/vendor/" in p or p.endswith(".min.js")


def is_test(p):
    return "/tests/" in p or os.path.basename(p).startswith(("test_", "e2e_"))


def read(p):
    try:
        with open(os.path.join(REPO, p), encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def one_line(text):
    for ln in text.splitlines():
        ln = ln.strip().strip("*").strip()
        if ln:
            if len(ln) <= HEAD_MAX:
                return ln
            cut = ln[:HEAD_MAX - 1]
            m = re.search(r"(?:notes:|git:)[^\s、。・()()]*$", cut)   # 途中で切った資料のパスは残さない(notes_tool check が切れたパスと言う)
            return (cut[:m.start()] if m else cut) + "…"
    return ""


def comment_head(src):
    """.js・.cs の頭の説明(最初のコメント。'use strict'・#!・using は飛ばす)の 1 行目。無ければ空"""
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#!") or s.strip("'\";") == "use strict" or (s.startswith("using ") and s.endswith(";")):
            i += 1
            continue
        if s.startswith("//"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith("//"):
                buf.append(lines[i].strip().lstrip("/").strip())
                i += 1
            return one_line("\n".join(buf))
        if s.startswith("/*"):
            buf = []
            while i < len(lines):
                buf.append(lines[i].replace("/**", "").replace("/*", "").replace("*/", ""))
                if "*/" in lines[i]:
                    break
                i += 1
            return one_line("\n".join(buf))
        return ""
    return ""


def py_info(p, src):
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return "", [], [], []
    head = one_line(ast.get_docstring(tree) or "")
    syms = []
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            syms.append(("class " + n.name, n.lineno))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append((n.name, n.lineno))
    pub = [s for s in syms if not s[0].split()[-1].startswith("_")]
    serve, call = [], []
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Constant) and isinstance(n.value, str) and ROUTE.match(n.value)) or n.value.rstrip("/") in ("/api", "api"):
            continue
        par = parents.get(n)
        if isinstance(par, ast.Call) and n in par.args and not (isinstance(par.func, ast.Attribute) and par.func.attr in ("startswith", "get")):
            call.append((n.value, n.lineno))
        else:
            serve.append((n.value, n.lineno, isinstance(par, (ast.Compare, ast.Dict))))
    # 比べる所・表の鍵(= 処理の入口)を先に。同じ口の 2 つ目以降は出す側で落とす
    serve = [(r, ln) for r, ln, _ in sorted(serve, key=lambda x: (not x[2], x[1]))]
    return head, (pub or syms), serve, call


def js_info(p, src):
    head = comment_head(src)
    syms = []
    for i, ln in enumerate(src.splitlines(), 1):
        if ln[:1] in (" ", "\t"):
            continue
        m = JS_SYM.match(ln)
        if m:
            name = m.group(1) or m.group(3) or ("class " + m.group(2))
            syms.append((name, i))
    call = []
    seen = set()
    for i, ln in enumerate(src.splitlines(), 1):
        for m in JS_ROUTE.finditer(ln):
            r = "/" + m.group(1).rstrip("/")
            if r not in seen:
                seen.add(r)
                call.append((r, i))
    return head, syms, [], call


def cs_info(p, src):
    head = comment_head(src)
    syms = []
    for i, ln in enumerate(src.splitlines(), 1):
        m = CS_CLASS.match(ln)
        if m:
            syms.append(("class " + m.group(1), i))
            continue
        m = CS_METHOD.match(ln)
        if m and m.group(1) not in ("If", "While"):
            syms.append((m.group(1), i))
    call = []
    seen = set()
    for i, ln in enumerate(src.splitlines(), 1):
        for m in JS_ROUTE.finditer(ln):
            r = "/" + m.group(1).rstrip("/")
            if r not in seen:
                seen.add(r)
                call.append((r, i))
    return head, syms, [], call


def info(p):
    src = read(p)
    if p.endswith(".py"):
        head, syms, serve, call = py_info(p, src)
        if not head and os.path.basename(p) == "__init__.py":
            head = "(パッケージの印)" if not src.strip() else ""
    elif p.endswith(".js"):
        head, syms, serve, call = js_info(p, src)
    else:
        head, syms, serve, call = cs_info(p, src)
    return {"path": p, "head": head, "syms": syms, "serve": serve, "call": call, "lines": src.count("\n") + 1, "test": is_test(p)}


def layer_of(p):
    for title, key, prefixes in LAYERS:
        if p.startswith(prefixes):
            return key
    return "tools"


def norm_route(r):
    r = "/" + r.lstrip("/")
    for pre in ("/friend/api/", "/live/api/"):
        if r.startswith(pre):
            r = "/api/" + r[len(pre):]
    return r.rstrip("/") or r


def routes(infos):
    """受ける・呼ぶ `/api/...` の口(norm_route でそろえた集合)。docs/spec の検査(dev/spec_check.py)が使う"""
    return {norm_route(r[0]) for it in infos for r in list(it["serve"]) + list(it["call"])}


def fmt_syms(syms):
    shown = ["`%s` :%d" % s for s in syms[:SYM_MAX]]
    if len(syms) > SYM_MAX:
        shown.append("ほか %d" % (len(syms) - SYM_MAX))
    return "・".join(shown)


def render_layer(title, items):
    out = ["# コードの地図: %s" % title, "",
           "自動で作った物(`python dev/code_map.py`)。手で直さない。目次は [index.md](index.md)。"
           "`file:line` の行の番号は作った時点の物。", ""]
    by_dir = defaultdict(list)
    for it in items:
        by_dir[os.path.dirname(it["path"])].append(it)
    tests = []
    for d in sorted(by_dir):
        rows = [it for it in by_dir[d] if not it["test"]]
        tests.extend(it for it in by_dir[d] if it["test"])
        if not rows:
            continue
        out.append("## %s/" % d)
        out.append("")
        for it in rows:
            out.append("- **%s** (%d 行) — %s" % (os.path.basename(it["path"]), it["lines"], it["head"] or "(頭の説明なし)"))
            if it["syms"]:
                out.append("  - 名前: " + fmt_syms(it["syms"]))
            if it["serve"]:
                first = {}
                for r, ln in it["serve"]:
                    if norm_route(r) != "/api":
                        first.setdefault(norm_route(r), ln)
                rs = sorted(first.items(), key=lambda x: x[1])
                out.append("  - 受ける口: " + "・".join("`%s` :%d" % x for x in rs))
        out.append("")
    if tests:
        out.append("## テスト")
        out.append("")
        for it in tests:
            out.append("- %s — %s" % (it["path"], it["head"] or "(頭の説明なし)"))
        out.append("")
    return "\n".join(out)


def render_index(groups, infos):
    out = ["# コードの地図(目次)", "",
           "自動で作った物(`python dev/code_map.py`。古いと `python dev/lint.py` の code-map が言う)。手で直さない。",
           "探し方: 画面の言葉なら [words.md](words.md)、`/api/...` の口なら下の表、役目なら層ごとの md を見る。行の番号は作った時点の物。", "",
           "| 層 | md | ファイル | 行 |", "|---|---|---|---|"]
    for title, key, _ in LAYERS:
        its = groups.get(key, [])
        if its:
            out.append("| %s | [%s.md](%s.md) | %d | %d |" % (title, key, key, len(its), sum(i["lines"] for i in its)))
    out += ["", "## `/api/...` の口(受ける所 → 呼ぶ所)", "",
            "受ける所は .py の処理(比べる・表の鍵)。呼ぶ所は画面の .js・.cs・ほかの .py(テストは除く)。", ""]
    serve, call = defaultdict(list), defaultdict(set)
    for it in infos:
        if it["test"]:
            continue
        for r, ln in it["serve"]:
            serve[norm_route(r)].append("%s:%d" % (it["path"], ln))
        for r, ln in it["call"]:
            call[norm_route(r)].add(it["path"])
    for r in sorted(set(serve) | {c for c in call if any(c.startswith(s) for s in serve)}):
        if r not in serve:
            continue
        callers = sorted(call.get(r, ()))
        c = "・".join(os.path.basename(x) for x in callers[:5]) + (" ほか %d" % (len(callers) - 5) if len(callers) > 5 else "")
        out.append("- `%s` — %s%s" % (r, "・".join(list(dict.fromkeys(serve[r]))[:3]), (" ← " + c) if c else ""))
    out.append("")
    return "\n".join(out)


# ---- 言葉の索引 ----

def load_words():
    rows = []
    try:
        with open(WORDS, encoding="utf-8") as f:
            for ln in f:
                ln = ln.rstrip("\r\n")
                if not ln or ln.startswith("#"):
                    continue
                cols = (ln.split("\t") + ["", ""])[:3]
                rows.append((cols[0].strip(), [c.strip() for c in cols[1].split(",") if c.strip()], cols[2].strip()))
    except OSError:
        pass
    return rows


def ui_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(p for p in out.split("\0") if p.endswith((".js", ".html", ".cs")) and not skipped(p) and not is_test(p))


def fmt_name(name, where):
    return where if where.startswith("`") else "`%s` %s" % (name, where)


def render_words(infos):
    texts = {p: read(p) for p in ui_files()}
    defs = {}
    for it in infos:
        if it["test"]:
            continue
        for name, ln in it["syms"]:
            defs.setdefault(name.split()[-1], "%s:%d" % (it["path"], ln))
            defs.setdefault(name, "%s:%d" % (it["path"], ln))   # "class X" でも引ける
    code_texts = {it["path"]: read(it["path"]) for it in infos if not it["test"]}

    serve = {}
    for it in infos:
        if not it["test"]:
            for r, ln in it["serve"]:
                serve.setdefault(norm_route(r), "%s:%d" % (it["path"], ln))

    def where_word(w, limit=4):
        """画面の文字列(コメントの行を除き、引用符か > < の中)に言葉が出る最初の行。ファイルごとに 1 つ"""
        hits = []
        for p, t in texts.items():
            for i, ln in enumerate(t.splitlines(), 1):
                s = ln.strip()
                if w in s and not s.startswith(("//", "*", "/*", "<!--", "#")) and re.search(r"""['"`>][^'"`<>]*""" + re.escape(w), s):
                    hits.append("%s:%d" % (p, i))
                    break
        hits.sort(key=lambda h: ("/ui/" not in h, h))
        return hits[:limit], len(hits)

    paths = [it["path"] for it in infos] + list(texts)

    def where_name(n):
        """名前の定義(無ければ最初に出る所)の file:line。パス(/ か拡張子つき)はリポジトリの中の本当のパスへ直す"""
        if n.startswith("/api/"):
            return serve.get(n, "(受ける所が見つからない)")
        if "/" in n or n.endswith((".py", ".js", ".cs", ".html")):
            for cand in (n.rstrip("/"), "src/" + n.rstrip("/")):
                if os.path.exists(os.path.join(REPO, cand)):
                    return "`%s`" % cand
            hits = [p for p in paths if p.endswith("/" + n)]
            return "`%s`" % hits[0] if hits else "(無いパス)"
        if n in defs:
            return defs[n]
        if "." in n and ("class " + n.split(".")[0]) in defs:   # Class.method = そのクラスのファイルの def
            p = defs["class " + n.split(".")[0]].rsplit(":", 1)[0]
            m = re.search(r"def " + re.escape(n.split(".")[1]) + r"\(", code_texts.get(p, ""))
            if m:
                return "%s:%d" % (p, code_texts[p].count("\n", 0, m.start()) + 1)
        pat = re.compile(r"(?<![\w$])" + re.escape(n) + r"(?![\w$])")
        for p, t in code_texts.items():
            m = pat.search(t)
            if m:
                return "%s:%d" % (p, t.count("\n", 0, m.start()) + 1)
        return "(見つからない)"

    out = ["# 言葉の索引(画面の言葉 → コードの名前)", "",
           "自動で作った物(`python dev/code_map.py`)。上の表の言葉と名前は `dev/code_words.tsv` に手で書く(足すときはそこへ)。"
           "場所は作るたびに引き直す。下の「候補」は画面の文字列から集めた物(手で整える前)。目次は [index.md](index.md)。", "",
           "## 主な言葉", ""]
    covered = set()
    for word, names, memo in load_words():
        covered.add(word)
        hits, n = where_word(word)
        out.append("- **%s**%s" % (word, (" — " + memo) if memo else ""))
        if names:
            out.append("  - コード: " + "・".join(fmt_name(nm, where_name(nm)) for nm in names))
        out.append("  - 画面: " + ("・".join(hits) + (" ほか %d" % (n - len(hits)) if n > len(hits) else "") if hits else "(画面の文字列に無い)"))
    out += ["", "## 候補(画面の文字列。多く出る順。手で整える前)", ""]
    cnt, first = Counter(), {}
    for p, t in texts.items():
        for rx in (UI_STR, HTML_TEXT) if p.endswith(".html") or p.endswith(".js") else (UI_STR,):
            for m in rx.finditer(t):
                s = m.group(m.lastindex).strip()
                if not JP.search(s) or "${" in s or len(s) < 2:
                    continue
                cnt[s] += 1
                first.setdefault(s, "%s:%d" % (p, t.count("\n", 0, m.start()) + 1))
    for s, n in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[:200]:
        if s not in covered:
            out.append("- %s(%d)— %s" % (s, n, first[s]))
    out.append("")
    return "\n".join(out)


def build():
    infos = [info(p) for p in git_files()]
    groups = defaultdict(list)
    for it in infos:
        groups[layer_of(it["path"])].append(it)
    pages = {"index.md": render_index(groups, infos), "words.md": render_words(infos)}
    for title, key, _ in LAYERS:
        if groups.get(key):
            pages[key + ".md"] = render_layer(title, groups[key])
    return pages, infos


def stale(pages):
    """古い・足りない・余分な md の名前(空なら最新)"""
    bad = []
    for name, text in pages.items():
        try:
            with open(os.path.join(OUT, name), encoding="utf-8", newline="") as f:
                if f.read().replace("\r\n", "\n") != text:
                    bad.append(name)
        except OSError:
            bad.append(name)
    if os.path.isdir(OUT):
        bad += [n for n in os.listdir(OUT) if n.endswith(".md") and n not in pages]
    return sorted(bad)


def write(pages):
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name.endswith(".md") and name not in pages:
            os.remove(os.path.join(OUT, name))
    for name, text in pages.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--missing", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    pages, infos = build()
    if a.missing:
        miss = [it["path"] for it in infos if not it["head"]]
        print("\n".join(miss))
        print("頭の説明なし: %d 本" % len(miss))
        return 1 if miss else 0
    if a.check:
        bad = stale(pages)
        if bad:
            print("地図が古い: %s(python dev/code_map.py で作り直す)" % "・".join(bad))
            return 1
        print("地図は最新")
        return 0
    write(pages)
    print("codemap/ に %d 枚(%s)" % (len(pages), "・".join("%s %dKB" % (n, len(t.encode("utf-8")) // 1024) for n, t in sorted(pages.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
