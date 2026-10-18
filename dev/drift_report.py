#!/usr/bin/env python3
"""資料どうし・資料とコードの食い違いをまとめて流し、1 枚の一覧(保管庫の plan/食い違いの一覧.md。自動)に出す(2026-10-18)。

    python dev/drift_report.py [--no-write]    # 流して件数を出し、一覧を書く(--no-write は書かない)

見る物:
  - 止める物 = dev/notes_tool.py check と同じ(リンク切れ・計画のデータ・資料の頭の状態 dev/doc_state.py)
  - 警告 = 仕様とコードの食い違い(dev/spec_check.py)・文書の行数の上限・入口の文書(AGENTS.md・ホーム・docs/spec)の同じ文の重なり
週に 1 回(仮決めの一覧と同じ日)に見る。dev/plan_artifact.py が公開し直すたびに作り直すので、ふだんは開くだけでよい。
行数の上限と重なりは目安(仮決め 3-93)。超えたら短くする・リンクにする(同じ話は 1 か所だけに書く)。
"""
import argparse
import datetime
import fnmatch
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

REPORT = "plan/食い違いの一覧.md"
# 上から先に当たった上限(保管庫からの相対のパターン, 行)。自動で作る索引(種類: 索引)は数えない
CAPS = (("AGENTS.md", 200), ("ホーム.md", 120), ("plan/decisions.md", 700), ("plan/done/*", 0),
        ("plan/*.md", 400), ("docs/spec/*", 800))
DUP_MIN = 50
AUTO = re.compile(r"<!-- 自動: ここから.*?<!-- 自動: ここまで -->", re.S)


def read(p):
    with open(p, "rb") as f:
        return f.read().decode("utf-8", "replace")


def md_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if f.endswith(".md"):
                full = os.path.join(base, f)
                yield os.path.relpath(full, root).replace(os.sep, "/"), full


def is_index(text):
    return bool(re.match(r"---\r?\n(?:.*\r?\n)*?種類:\s*索引", text))


def caps(root):
    """[(資料, 行数, 上限)] 上限を超えた物"""
    out = []
    for rel, full in md_files(root):
        if rel.startswith("docs/worklog/"):
            continue
        limit = next((n for pat, n in CAPS if fnmatch.fnmatch(rel, pat)), 0)
        if not limit:
            continue
        text = read(full)
        n = text.count("\n") + 1
        if n > limit and not is_index(text):
            out.append((rel, n, limit))
    return out


def entry_docs(root):
    out = ["AGENTS.md", "ホーム.md"]
    out += [rel for rel, _ in md_files(os.path.join(root, "docs", "spec"))]
    return [r if r in ("AGENTS.md", "ホーム.md") else "docs/spec/" + r for r in out]


def sentences(text):
    """比べる文(行)。コードのブロック・見出し・表・自動の部分・頭は除き、箇条の印を外す"""
    text = AUTO.sub("", text)
    out, fence, head = [], False, text.startswith("---")
    for ln, line in enumerate(text.splitlines(), 1):
        if head:
            head = not (ln > 1 and line.strip() == "---")
            continue
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        s = line.strip()
        if fence or not s or s.startswith(("#", "|", "<!--")):
            continue
        s = re.sub(r"^(?:[-*>]|\d+\.)\s+", "", s)
        if len(s) >= DUP_MIN:
            out.append((ln, s))
    return out


def duplicates(root):
    """[(文の頭, [(資料, 行)])] 入口の文書の 2 か所以上に同じ文"""
    seen = {}
    for rel in entry_docs(root):
        full = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(full):
            continue
        for ln, s in sentences(read(full)):
            seen.setdefault(s, []).append((rel, ln))
    return [(s, locs) for s, locs in seen.items() if len({r for r, _ in locs}) >= 2]


def collect(root):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import notes_tool
    import spec_check
    bad = notes_tool.check(root=root)
    sbad, swarn = spec_check.check(root)
    return {"bad": bad, "spec": sbad + swarn, "caps": caps(root), "dups": duplicates(root)}


def render(res, today):
    total_warn = len(res["spec"]) + len(res["caps"]) + len(res["dups"])
    out = ["---", "種類: 索引", "状態: 有効", "---", "", "# 食い違いの一覧(資料どうし・資料とコード)", "",
           "更新(%s): 自動で作る(`dev/drift_report.py`。`dev/plan_artifact.py` も流す)・手で直さない。週に 1 回、"
           "[仮決めの一覧](仮決めの一覧.md) と同じ日に見て、警告を減らす" % today.isoformat(), "",
           "- 止める物 %d 件(0 でないと lint・push.bat が止まる。`py -3.12 dev/notes_tool.py check`。資料の頭の状態だけなら `check --fix`)" % len(res["bad"]),
           "- 警告 %d 件(止めない。仕様とコード %d・行数 %d・同じ文 %d)" % (total_warn, len(res["spec"]), len(res["caps"]), len(res["dups"])), ""]

    def section(title, rows):
        out.extend(["## %s(%d 件)" % (title, len(rows)), ""])
        out.extend(rows or ["(無し)"])
        out.append("")

    section("止める物", ["- `%s:%d` %s" % (w, ln, cell(m)) for w, ln, m in res["bad"]])
    section("仕様とコードの警告", ["- `%s:%d` %s" % (w, ln, cell(m)) for w, ln, m in res["spec"]])
    section("行数の上限を超えた文書", ["- `%s` %d 行(目安 %d)" % x for x in res["caps"]])
    section("入口の文書の同じ文(1 か所に書き、ほかはリンクに)",
            ["- %s — %s" % (cell(s, 60), "・".join("`%s:%d`" % l for l in locs)) for s, locs in res["dups"]])
    return "\n".join(out).rstrip("\n") + "\n"


def cell(text, limit=160):
    text = re.sub(r"\s+", " ", str(text)).replace("`", "'").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def write_report(root, today=None):
    """一覧を書く。-> 集めた結果"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import notes_tool
    path = os.path.join(root, *REPORT.split("/"))
    if not os.path.isfile(path) and os.path.isdir(os.path.dirname(path)):   # 初回: 一覧を指すリンクが集める間に切れないように
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("---\n種類: 索引\n状態: 有効\n---\n")
    res = collect(root)
    text = notes_tool.unlink_prose(render(res, today or datetime.date.today()))
    old = read(path) if os.path.isfile(path) else ""
    if re.sub(r"更新\(\d{4}-\d\d-\d\d\)", "", old) != re.sub(r"更新\(\d{4}-\d\d-\d\d\)", "", text):   # 日付だけの差では書かない
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return res


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    root = layout.notes_root()
    if not os.path.isdir(root):
        print("資料のフォルダが無い: %s" % root)
        return 0
    res = collect(root) if a.no_write else write_report(root)
    print("止める物 %d 件・警告 %d 件(仕様とコード %d・行数 %d・同じ文 %d)%s" % (
        len(res["bad"]), len(res["spec"]) + len(res["caps"]) + len(res["dups"]), len(res["spec"]), len(res["caps"]),
        len(res["dups"]), "" if a.no_write else " → " + REPORT))
    return 1 if res["bad"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
