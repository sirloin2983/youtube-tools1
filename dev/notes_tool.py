#!/usr/bin/env python3
"""資料のフォルダ(Obsidian の保管庫の中。layout.notes_root())のパスの検査と、資料を動かす道具(2026-10-13)。

    python dev/notes_tool.py check                 # 切れたパスを並べる(終了コード 1 = 切れた物がある)
    python dev/notes_tool.py mv <旧> <新> [...]   # 資料のフォルダの中で git mv して、指している所を全部直す
    python dev/notes_tool.py fix-prose            # 本文のかっこ書き [送る](説明) に空白を入れてリンクにしない

check が見る物(dev/lint.py も同じ物を数える):
  - 資料のフォルダの md の相対リンク(外の URL・#だけ・obsidian: は見ない)と、リンクになってしまう本文のかっこ書き
  - plan/data.js の docs の並び(plan/ からの相対)と、文の中の docs/… plan/… の .md・.html
  - リポジトリのコード・README の notes:docs/… notes:plan/…
mv が直す物: md の相対リンク(動かした文書の中のリンクも)・リンクの表示が旧いパスそのものならその文字・
  data.js の両方の書き方・リポジトリの notes: の参照。リンクでない文字のパス(過去の記録の中など)は直さない。
Obsidian の中で動かすと md のリンクだけは Obsidian が直すが、data.js と notes: は直らない = 動かしたら check を流す。
"""
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

LINK = re.compile(r"(!?\[)([^\]\n]*)(\]\()(<[^>\n]+>|[^)\s]+)((?:\s+\"[^\"\n]*\")?\))")
NOTE_REF = re.compile(r"notes:((?:docs|plan)/[A-Za-z0-9_\-][A-Za-z0-9_./\-]*)")
DATA_DOCS = re.compile(r"docs:\s*\[([^\]]*)\]")
DATA_TEXT = re.compile(r"(?<![A-Za-z0-9_./\-])((?:docs|plan)/[A-Za-z0-9_./\-]+\.(?:md|html))")
QUOTED = re.compile(r"\"([^\"]+)\"")
FILE_EXT = re.compile(r"\.(md|html|js|css|png|jpg|jpeg|gif|svg|tsv|csv|json|txt|pdf|py)$", re.I)
FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"`+[^`\n]*`+")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
CODE_EXTS = (".py", ".js", ".cjs", ".mjs", ".css", ".html", ".bat", ".txt", ".md", ".cs", ".ps1", ".command", ".sh", ".gs")
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".artifact-build", "worktrees", "0old"}


def vault():
    return layout.notes_root()


def read(p):
    with open(p, "rb") as f:
        return f.read().decode("utf-8")


def write(p, text):
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))


def md_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(d, f)


def code_files():
    for d, dirs, files in os.walk(REPO):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not (d == REPO and x.startswith(".") and x != ".claude")]
        for f in files:
            if f.endswith(CODE_EXTS) and f != "test_notes_tool.py":   # テストの見本の notes: は本物の資料を指さない
                yield os.path.join(d, f)


def local_target(t):
    """リンク先が資料のフォルダの中のファイルを指すなら (パス, #以降) を返す。外の URL などは None"""
    t = t[1:-1] if t.startswith("<") else t
    if not t or t.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", t):
        return None
    path, _, frag = t.partition("#")
    # 「[送る](友人へ届ける)」のような本文のかっこはリンクではない = 拡張子のあるパスか / で終わる物だけ
    if path and not (FILE_EXT.search(path) or path.endswith("/")):
        return None
    return path, frag


def pseudo_link(t):
    """本文のかっこ書き「[送る](友人へ届ける)」なら True(Obsidian が中身の無いノートへのリンクにしてしまう)"""
    t = t[1:-1] if t.startswith("<") else t
    if not t or t.startswith("#") or SCHEME.match(t):
        return False
    path = t.partition("#")[0]
    return bool(path) and not (FILE_EXT.search(path) or path.endswith("/"))


def _links(line):
    """行の中のリンクの形(コードの `...` の中は除く)"""
    return LINK.finditer(CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line))


def unlink_prose(text):
    """かっこ書き「[送る](友人へ届ける)」の ] と ( の間に空白を入れてリンクにしない(コードのブロックと `...` の中は触らない)"""
    out, fence = [], False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            fence = not fence
        if not fence:
            for m in reversed(list(_links(line))):
                if m.group(1) == "[" and pseudo_link(m.group(4)):
                    i = m.start(3) + 1
                    line = line[:i] + " " + line[i:]
        out.append(line)
    return "".join(out)


def vrel(full, root):
    return os.path.relpath(full, root).replace(os.sep, "/")


def link_to(full, here_dir):
    r = os.path.relpath(full, here_dir).replace(os.sep, "/")
    return "<" + r + ">" if re.search(r"[ ()<>]", r) else r


def check():
    """切れたパスを [(どこ, 行, パス)] で返す。資料のフォルダが無い PC では空"""
    root = vault()
    if not os.path.isdir(root):
        return []
    bad = []
    for p in md_files(root):
        fence = False
        for ln, line in enumerate(read(p).splitlines(), 1):
            if FENCE.match(line):
                fence = not fence
            if fence:
                continue
            for m in _links(line):
                if m.group(1) == "[" and pseudo_link(m.group(4)):
                    bad.append((vrel(p, root), ln, "かっこ書きがリンクになる(] と ( の間に空白): " + m.group(0)))
                    continue
                lt = local_target(m.group(4))
                if lt and lt[0] and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(p), lt[0]))):
                    bad.append((vrel(p, root), ln, lt[0]))
    data = os.path.join(root, "plan", "data.js")
    if os.path.isfile(data):
        for ln, line in enumerate(read(data).splitlines(), 1):
            for m in DATA_DOCS.finditer(line):
                for q in QUOTED.findall(m.group(1)):
                    full = os.path.normpath(os.path.join(root, "plan", q))
                    # ../chrome-ext/… のようにリポジトリのファイルを指す物はリポジトリで探す
                    alt = os.path.join(REPO, os.path.relpath(full, root))
                    if not os.path.exists(full) and not os.path.exists(alt):
                        bad.append(("plan/data.js", ln, q))
            for m in DATA_TEXT.finditer(line):
                if not os.path.exists(os.path.join(root, m.group(1))):
                    bad.append(("plan/data.js", ln, m.group(1)))
    for p in code_files():
        try:
            text = read(p)
        except UnicodeDecodeError:
            continue
        if "notes:" not in text:
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            for m in NOTE_REF.finditer(line):
                if not os.path.exists(os.path.join(root, m.group(1).rstrip(".-"))):
                    bad.append((vrel(p, REPO), ln, "notes:" + m.group(1)))
    return bad


def _mapping(root, pairs):
    """[(旧, 新)](資料のフォルダからの相対)→ ファイルごとの {旧の絶対: 新の絶対}"""
    out = {}
    for old, new in pairs:
        o, n = os.path.join(root, old), os.path.join(root, new)
        if os.path.isdir(o):
            for d, _, files in os.walk(o):
                for f in files:
                    src = os.path.join(d, f)
                    out[os.path.normpath(src)] = os.path.normpath(os.path.join(n, os.path.relpath(src, o)))
        else:
            out[os.path.normpath(o)] = os.path.normpath(n)
    return out


def _moved(path, files, pairs, root):
    """旧の絶対パス → 新の絶対パス(動かさない物はそのまま。フォルダを指すリンクも)"""
    path = os.path.normpath(path)
    if path in files:
        return files[path]
    for old, new in pairs:
        o = os.path.normpath(os.path.join(root, old))
        if path == o or path.startswith(o + os.sep):
            return os.path.normpath(os.path.join(root, new) + path[len(o):])
    return path


def relink_text(text, old_file, new_file, resolve=lambda p: p, root=None):
    """文書の中身を old_file の場所から new_file の場所へ動かしたときの、相対リンクの書き直し。
    resolve は「旧の絶対パス → 今の絶対パス」(ほかのファイルも動いたとき)。表示が旧いパスそのものなら表示も直す"""
    old_dir, new_dir = os.path.dirname(old_file), os.path.dirname(new_file)

    def sub(m):
        lt = local_target(m.group(4))
        if not lt or not lt[0]:
            return m.group(0)
        was = os.path.normpath(os.path.join(old_dir, lt[0]))
        now = resolve(was)
        target = link_to(now, new_dir) + ("#" + lt[1] if lt[1] else "")
        label = m.group(2)
        if root and was != now:
            ov, nv = vrel(was, root), vrel(now, root)
            label = label.replace("`" + ov + "`", "`" + nv + "`") if label.strip("`") == ov else label
            label = nv if label == ov else label
        if target == m.group(4) and label == m.group(2):
            return m.group(0)
        return m.group(1) + label + m.group(3) + target + m.group(5)

    return LINK.sub(sub, text)


def mv(pairs):
    """資料のフォルダの中で git mv し、md のリンク・data.js・リポジトリの notes: を直す"""
    root = vault()
    files = _mapping(root, pairs)
    for old, new in pairs:
        os.makedirs(os.path.dirname(os.path.join(root, new)), exist_ok=True)
        subprocess.run(["git", "-C", root, "mv", old, new], check=True)
    back = {v: k for k, v in files.items()}
    resolve = lambda p: _moved(p, files, pairs, root)  # noqa: E731
    n = 0
    for p in md_files(root):
        p = os.path.normpath(p)
        text = read(p)
        new = relink_text(text, back.get(p, p), p, resolve, root)
        if new != text:
            write(p, new)
            n += 1
    data = os.path.join(root, "plan", "data.js")
    if os.path.isfile(data):
        text = new = read(data)
        for old, nw in pairs:
            new = re.sub(r"(?<![A-Za-z0-9_./\-])" + re.escape(old) + r"(?![A-Za-z0-9_\-]|\.[A-Za-z0-9])", nw, new)
            if old.startswith("plan/") and nw.startswith("plan/"):
                po, pn = old[5:], nw[5:]
                new = new.replace('"' + po, '"' + pn)
            new = new.replace('"../' + old, '"../' + nw)
        if new != text:
            write(data, new)
            n += 1
    for p in code_files():
        try:
            text = read(p)
        except UnicodeDecodeError:
            continue
        if "notes:" not in text:
            continue
        new = text
        for old, nw in pairs:
            new = re.sub(r"notes:" + re.escape(old) + r"(?![A-Za-z0-9_\-]|\.[A-Za-z0-9])", "notes:" + nw, new)
        if new != text:
            write(p, new)
            n += 1
    return n


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if argv[:1] == ["check"]:
        bad = check()
        for where, ln, p in bad:
            print("%s:%d %s" % (where, ln, p))
        print("切れたパス %d 件" % len(bad))
        return 1 if bad else 0
    if argv[:1] == ["fix-prose"]:
        n = 0
        for p in md_files(vault()):
            text = read(p)
            new = unlink_prose(text)
            if new != text:
                write(p, new)
                n += 1
        print("直したファイル %d 本" % n)
        return 0
    if argv[:1] == ["mv"] and len(argv) >= 3 and len(argv) % 2 == 1:
        pairs = [(argv[i].replace("\\", "/").rstrip("/"), argv[i + 1].replace("\\", "/").rstrip("/")) for i in range(1, len(argv), 2)]
        print("直したファイル %d 本" % mv(pairs))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
