#!/usr/bin/env python3
"""コードの行数を数える共通の道具(ユーザーと決めた数え方。セッションごとの数の食い違いを無くす)。

    py -3.12 dev/loc.py                    # 今(作業コピーの Git に入っているファイル)の層ごとの数
    py -3.12 dev/loc.py --since cdd95a14   # 前(コミット・版のタグ)と今を並べて正味の差
    py -3.12 dev/loc.py --rev v0.99.32     # 今の代わりにそのコミットを数える(--since と組める)
    py -3.12 dev/loc.py --json             # 同じ内容を JSON で
    py -3.12 dev/loc.py --line             # 合計を 1 行で(session_start.py の頭)

数え方:
  - 数えるのは Git に入っているプログラムだけ(LANG の拡張子)。codemap/(自動で作る地図)・vendor/(同梱のライブラリ)・.json・.md・.txt は数えない。
  - 空行は数えない。数は 2 つ: (a) 空行を除いた行(コメントを含む) (b) 空行とコメントを除いた行。
  - コメントは言語ごと: Python の # と docstring・JS/CS/CSS/GS の // と /* */(CSS は /* */ だけ)・HTML の <!-- -->(<script>・<style> の中は JS・CSS)・
    bat の REM と ::・ps1 の # と <# #>・vbs の ' と REM・lua の -- と --[[ ]]。コードの後ろに付いたコメントの行はコードの行。
  - 分け方: 層(src/app などのフォルダ。src/ と friend-apps/ は 2 段目まで・ほかは 1 段目)ごとに 本体・テスト・開発の道具。
    テスト = tests/ の下(層は持ち主: tests/flow → src/flow・tests/dev → dev・tests/friend-apps/x → friend-apps/x)・前のコミットの部品の隣の tests/ の下・名前が test_* か e2e_*。
    開発の道具 = dev/ の下。
  - 「減った」は前と後の合計の差(正味)だけ。消した行・足した行は出さない。
"""
import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = {".py": "py", ".js": "js", ".cjs": "js", ".mjs": "js", ".gs": "js", ".cs": "js", ".css": "css", ".html": "html",
        ".bat": "bat", ".ps1": "ps1", ".vbs": "vbs", ".lua": "lua"}
KINDS = ("本体", "テスト", "開発の道具")
SKIP_TOP = ("codemap/",)


# ---------------------------------------------------------------- どのファイルをどこに数えるか

def classify(path):
    """Git のパス → (層, 種類)。数えない物は None"""
    p = path.replace("\\", "/")
    ext = os.path.splitext(p)[1].lower()
    if ext not in LANG or p.startswith(SKIP_TOP) or "vendor" in p.lower().split("/")[:-1]:
        return None
    parts = p.split("/")
    if parts[0] == "tests":
        return test_layer(parts[1:-1]), "テスト"
    if len(parts) == 1:
        layer = "(直下)"
    elif parts[0] in ("src", "friend-apps") and len(parts) > 2:
        layer = "/".join(parts[:2])
    else:
        layer = parts[0]
    name = parts[-1].lower()
    if "tests" in parts[:-1] or name.startswith(("test_", "e2e_")):   # 部品の隣の tests/ は前のコミットを数えるとき(--since・--rev)
        kind = "テスト"
    elif parts[0] == "dev":
        kind = "開発の道具"
    else:
        kind = "本体"
    return layer, kind


def test_layer(dirs):
    """tests/ の下のフォルダの並び → 持ち主の層(src の層・dev・chrome-ext・friend-apps/x)。tests/ 直下の共通の物は tests"""
    if not dirs:
        return "tests"
    if dirs[0] == "friend-apps" and len(dirs) > 1:
        return "friend-apps/" + dirs[1]
    if dirs[0] in ("dev", "chrome-ext"):
        return dirs[0]
    return "src/" + dirs[0]


# ---------------------------------------------------------------- 1 ファイルの (a)(b)

def count_text(text, ext):
    """(空行を除いた行, 空行とコメントを除いた行)"""
    lines = text.splitlines()
    nonblank = [i for i, s in enumerate(lines, 1) if s.strip()]
    lang = LANG.get(ext.lower())
    if lang == "py":
        code = py_code_lines(text)
    elif lang in ("js", "css", "html"):
        code = scan_code_lines(text, lang)
    else:
        code = prefix_code_lines(lines, lang)
    return len(nonblank), len([i for i in nonblank if i in code])


def py_docstring_starts(text):
    """docstring(モジュール・クラス・関数の最初の文字列の文)の頭の (行, 桁)"""
    out = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add((first.lineno, first.col_offset))
    return out


def py_code_lines(text):
    """コードの字句(コメント・docstring・改行・字下げでない物)が掛かる行。読めないときは # で始まる行だけをコメントに"""
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
    try:
        docs = py_docstring_starts(text)
        code = set()
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in skip or (tok.type == tokenize.STRING and tok.start in docs):
                continue
            code.update(range(tok.start[0], tok.end[0] + 1))
        return code
    except (SyntaxError, tokenize.TokenError, ValueError):
        return prefix_code_lines(text.splitlines(), "py")


def scan_code_lines(text, lang):
    """JS・CS・CSS・HTML を 1 字ずつ読み、コメントと空白の外の字がある行を返す(文字列の中の // や /* は見ない)"""
    code, line, i, n = set(), 1, 0, len(text)
    mode = lang            # "js" / "css" / "html"
    host = lang == "html"  # HTML の中の <script>・<style> から戻る先がある
    low = text.lower()
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if mode == "html":
            if text.startswith("<!--", i):
                j = skip_to(text, i + 4, "-->")
                line += text.count("\n", i, j)
                i = j
                continue
            m = re.match(r"<(script|style)\b[^>]*>", low[i:i + 400])
            if m:
                code.add(line)
                line += text.count("\n", i, i + m.end())
                i += m.end()
                mode = "js" if m.group(1) == "script" else "css"
                continue
            code.add(line)
            i += 1
            continue
        if host and low.startswith(("</script", "</style"), i):
            mode = "html"   # 閉じのタグそのものは HTML の行として次の回で数える
            continue
        if text.startswith("/*", i):
            j = skip_to(text, i + 2, "*/")
            line += text.count("\n", i, j)
            i = j
            continue
        if mode == "js" and text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if c in "\"'" or (mode == "js" and c == "`"):
            j = skip_string(text, i, c, host)
            code.update(range(line, line + text.count("\n", i, j) + 1))
            line += text.count("\n", i, j)
            i = j
            continue
        code.add(line)
        i += 1
    return code


def skip_to(text, i, end):
    j = text.find(end, i)
    return len(text) if j < 0 else j + len(end)


def skip_string(text, i, q, host):
    """i の引用符から閉じの次まで(' と " は行末で切れる・` は行をまたぐ。HTML の中では </script で切る)"""
    j, n = i + 1, len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == q:
            return j + 1
        if c == "\n" and q != "`":
            return j
        if host and c == "<" and text[j:j + 8].lower().startswith(("</script", "</style")):
            return j
        j += 1
    return n


LINE_MARK = {"py": re.compile(r"#"), "bat": re.compile(r"(@?rem\b|::)", re.I), "ps1": re.compile(r"#"),
             "vbs": re.compile(r"('|rem\b)", re.I), "lua": re.compile(r"--")}
BLOCK = {"ps1": ("<#", "#>"), "lua": ("--[[", "]]")}


def prefix_code_lines(lines, lang):
    """行の頭(空白の後)がコメントの印で始まる行と、ブロックのコメントの中の行を除いた行"""
    mark, block = LINE_MARK[lang], BLOCK.get(lang)
    code, inside = set(), False
    for i, s in enumerate(lines, 1):
        t = s.strip()
        if inside:
            k = t.find(block[1])
            if k < 0:
                continue
            inside, t = False, t[k + len(block[1]):].strip()
            if not t:
                continue
        if block and t.startswith(block[0]):
            k = t.find(block[1], len(block[0]))
            if k < 0:
                inside = True
                continue
            t = t[k + len(block[1]):].strip()
            if not t:
                continue
        if t and not mark.match(t):
            code.add(i)
    return code


# ---------------------------------------------------------------- 木(作業コピー か コミット)を数える

def git(*args, data=None, repo=REPO):
    r = subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise SystemExit("git %s が失敗: %s" % (" ".join(args[:2]), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout


def files_at(rev=None, repo=REPO):
    """[(パス, 中身の文字列)]。rev が無ければ作業コピー(Git に入っている物をディスクから)"""
    if rev is None:
        names = [p for p in git("ls-files", "-z", repo=repo).decode("utf-8").split("\0") if p and classify(p)]
        out = []
        for p in names:
            try:
                with open(os.path.join(repo, p), "rb") as f:
                    out.append((p, f.read().decode("utf-8", "replace")))
            except OSError:
                pass   # 消したがまだ git rm していない
        return out
    names = [p for p in git("ls-tree", "-r", "-z", "--name-only", rev, repo=repo).decode("utf-8").split("\0") if p and classify(p)]
    data = git("cat-file", "--batch", data="".join("%s:%s\n" % (rev, p) for p in names).encode("utf-8"), repo=repo)
    out, i = [], 0
    for p in names:
        nl = data.index(b"\n", i)
        size = int(data[i:nl].split()[2])
        out.append((p, data[nl + 1:nl + 1 + size].decode("utf-8", "replace")))
        i = nl + 1 + size + 1
    return out


def tally(files):
    """{層: {種類: [a, b, ファイル数]}}"""
    t = defaultdict(lambda: {k: [0, 0, 0] for k in KINDS})
    for p, text in files:
        layer, kind = classify(p)
        a, b = count_text(text, os.path.splitext(p)[1])
        cell = t[layer][kind]
        cell[0] += a
        cell[1] += b
        cell[2] += 1
    return dict(t)


def totals(t):
    """{種類: [a, b, ファイル数]} と 合計"""
    out = {k: [0, 0, 0] for k in KINDS + ("合計",)}
    for kinds in t.values():
        for k in KINDS:
            for j in range(3):
                out[k][j] += kinds[k][j]
                out["合計"][j] += kinds[k][j]
    return out


def one_line(tot):
    return "コードの行数(dev/loc.py・空行を除く / さらにコメントを除く): 本体 {:,} / {:,}・テスト {:,} / {:,}・道具 {:,} / {:,}・合計 {:,} / {:,}".format(
        *tot["本体"][:2], *tot["テスト"][:2], *tot["開発の道具"][:2], *tot["合計"][:2])


# ---------------------------------------------------------------- 出し方

def report(now, before=None):
    tn = totals(now)
    out = {"now": {"layers": now, "totals": tn}}
    if before is not None:
        tb = totals(before)
        out["before"] = {"layers": before, "totals": tb}
        out["diff"] = {k: [tn[k][0] - tb[k][0], tn[k][1] - tb[k][1]] for k in tn}
    return out


def print_table(r, since, rev):
    now, tn = r["now"]["layers"], r["now"]["totals"]
    before = r.get("before", {}).get("layers", {})
    label = rev or "作業コピー"
    print("数え方: (a) 空行を除いた行 (b) 空行とコメントを除いた行(docstring はコメント)。codemap/・vendor/ は除く")
    if since:
        print("前 = %s・今 = %s。差は正味(今 − 前)\n" % (since, label))
        print("%-24s %-6s %10s %10s %10s %10s %9s %9s" % ("層", "種類", "前(a)", "今(a)", "前(b)", "今(b)", "差(a)", "差(b)"))
    else:
        print("今 = %s\n" % label)
        print("%-24s %-6s %10s %10s %6s" % ("層", "種類", "(a)", "(b)", "ファイル"))
    empty = {k: [0, 0, 0] for k in KINDS}
    for layer in sorted(set(now) | set(before)):
        for k in KINDS:
            c, p = now.get(layer, empty)[k], before.get(layer, empty)[k]
            if not (c[2] or p[2]):
                continue
            if since:
                print("%-24s %-6s %10s %10s %10s %10s %+9d %+9d" % (layer, k, f"{p[0]:,}", f"{c[0]:,}", f"{p[1]:,}", f"{c[1]:,}", c[0] - p[0], c[1] - p[1]))
            else:
                print("%-24s %-6s %10s %10s %6d" % (layer, k, f"{c[0]:,}", f"{c[1]:,}", c[2]))
    print()
    for k in KINDS + ("合計",):
        c = tn[k]
        if since:
            p = r["before"]["totals"][k]
            print("%-28s 前 %9s / %9s  今 %9s / %9s  差 %+8d / %+8d" % (k, f"{p[0]:,}", f"{p[1]:,}", f"{c[0]:,}", f"{c[1]:,}", c[0] - p[0], c[1] - p[1]))
        else:
            print("%-28s %9s / %9s(%d ファイル)" % (k, f"{c[0]:,}", f"{c[1]:,}", c[2]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="コードの行数(空行を除く・コメントを除く)と正味の差")
    ap.add_argument("--since", help="前の木(コミット・版のタグ)。今との正味の差を出す")
    ap.add_argument("--rev", help="今の代わりに数えるコミット(既定は作業コピー)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--line", action="store_true", help="合計を 1 行で")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    now = tally(files_at(a.rev))
    before = tally(files_at(a.since)) if a.since else None
    r = report(now, before)
    if a.json:
        r.update({"since": a.since, "rev": a.rev or "worktree"})
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif a.line:
        print(one_line(r["now"]["totals"]))
    else:
        print_table(r, a.since, a.rev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
