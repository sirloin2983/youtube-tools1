#!/usr/bin/env python3
"""資料の保管庫(layout.notes_root())の plan/ の HTML(index.html・user-tasks.html)を、claude.ai の Artifact(リンクで開けるページ。スマホでも見る)用に 1 枚ずつまとめる。

    python dev/plan_artifact.py [--out <フォルダ>] [--plan <保管庫の plan フォルダ>] [--no-index]
    # --out の既定: <リポジトリ直下>/.artifact-build/plan/   --plan の既定: <保管庫>/plan

あわせて、保管庫の plan/data.js から計画の索引 <plan>/計画の索引.md を書き出す(Obsidian で読む用。--no-index で止める)。
data.js は JSON ではない JS なので、コメントと引用符なしのキーを外して Python だけで読む(node は使わない)。

Artifact は外部の CSS・JS を読めない(CDN 以外)ので、plan.css・data.js・plan.js(2 ページ共通の表示部品)を各ページに埋め込む。
主のページ(index.html)は Artifact 側が <head> を付けるので、<title> と <style> から始まる本文だけ(doctype・html・head・body は無し)。
2 枚目(user-tasks.html)は files として出すので、完全な HTML のまま(自分の doctype を持つ)。
md は Artifact に無いので、上のページ切り替えの md(決めたこと・改善案)は外し、ほかの md へのリンクはファイル名の文字だけにする
(画面が作るリンクは window.PLAN_NO_MD を見て plan.js の docLink が文字にする)。
公開は Claude Code が Artifact ツールで行う(保管庫の plan/data.js を直したら、これを流して公開し直す)。
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

PLAN = os.path.join(layout.notes_root(REPO), "plan")
INDEX_NAME = "計画の索引.md"
STATE_JA = {"done": "済み", "doing": "進行中", "next": "次(今できる)", "todo": "あと",
            "wait": "ユーザー待ち", "cont": "継続"}
DOC_PATH = re.compile(r"(?:docs|plan)/[\w./-]*?\.(?:md|html)")


def read(name):
    with open(os.path.join(PLAN, name), encoding="utf-8") as f:
        return f.read()


def inline_assets(html, css, data, common):
    for tag, body in (('<link rel="stylesheet" href="plan.css">', "<style>\n" + css + "\n</style>"),
                      ('<script src="data.js"></script>', "<script>\nwindow.PLAN_NO_MD = true;\n" + data + "\n</script>"),
                      ('<script src="plan.js"></script>', "<script>\n" + common + "\n</script>")):
        if tag not in html:
            raise SystemExit("plan の HTML に %s が無い(埋め込めない)" % tag)
        html = html.replace(tag, body)
    # md へのリンクは外す(Artifact には無い)。ページ切り替えの 2 つは消し、ほかはファイル名の文字だけ
    html = re.sub(r'<a href="(decisions|improvements)\.md">[^<]*</a>', "", html)
    html = re.sub(r'<a href="[^"]+\.md">([^<]*)</a>', r'<span class="mdref">\1</span>', html)
    return html


def main_fragment(html):
    """<title> と <style> と <script>(データ)を先頭に、<body> の中身を続ける(doctype・html・head・body を外す)"""
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(0)
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    keep = re.findall(r"<style>.*?</style>|<script>.*?</script>", head, re.S)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    return title + "\n" + "\n".join(keep) + "\n" + body.strip() + "\n"


def parse_plan_js(text):
    """data.js の window.PLAN = {...}; を dict にする。
    コメントを外し、引用符なしのキーに引用符を付け、末尾のカンマを消して json で読む(文字列の中は触らない)"""
    start = text.index("{", text.index("window.PLAN"))
    out, strs, i, n = [], [], start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            strs.append(text[i:j + 1])
            out.append("@@S%d@@" % (len(strs) - 1))
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            out.append(c)
            i += 1
    src = "".join(out)
    src = src[:src.rindex("}") + 1]
    src = re.sub(r"([{,]\s*)([A-Za-z_$][\w$]*)\s*:", r'\1"\2":', src)
    src = re.sub(r",(\s*[}\]])", r"\1", src)
    src = re.sub(r"@@S(\d+)@@", lambda m: strs[int(m.group(1))], src)
    return json.loads(src)


def link_paths(text, notes, name, warn):
    """文中の docs/・plan/ のパスを Markdown の相対リンクにする(索引は plan/ の中にある)。
    保管庫に無いパスは文字のまま残して warn(path, name)"""
    def sub(m):
        path = m.group(0)
        if not os.path.isfile(os.path.join(notes, *path.split("/"))):
            warn(path, name)
            return path
        rel = path[len("plan/"):] if path.startswith("plan/") else "../" + path
        return "[`%s`](%s)" % (path, rel)
    return DOC_PATH.sub(sub, text)


def task_line(t, linked):
    state = STATE_JA.get(t.get("state"), t.get("state") or "")
    return "- %s %s(%s)" % (t.get("id", ""), linked(t.get("name", ""), t.get("id", "")), state)


def build_index(plan, plan_dir, warn):
    """計画の索引(Markdown)の文字列を作る。同じ data.js なら同じ中身(順序は data.js の並び)"""
    notes = os.path.dirname(plan_dir)
    warned = set()

    def w(path, name):
        if (path, name) not in warned:
            warned.add((path, name))
            warn(path, name)

    def linked(text, name):
        return link_paths(text, notes, name, w)

    def doc_ref(d, name):
        """lines[].docs の項目(plan/ からの相対。docs/・plan/ の頭が付く物も)"""
        if re.match(r"(?:docs|plan)/", d):
            return linked(d, name)
        if os.path.isfile(os.path.normpath(os.path.join(plan_dir, d))):
            return "[`%s`](%s)" % (d, d)
        w(d, name)
        return d

    out = ["# 計画の索引", "",
           "状態: 自動で作る(dev/plan_artifact.py)・手で直さない", "",
           "更新日: %s" % plan.get("updated", ""), "",
           "計画のページ: [index.html](index.html)・[user-tasks.html](user-tasks.html)", ""]
    tasks = plan.get("tasks", [])
    used = set()
    for ln in plan.get("lines", []):
        lid = ln.get("id", "")
        label = "線 " + lid
        out += ["## 線 %s: %s" % (lid, ln.get("name", "")), ""]
        if "pct" in ln:
            out += ["進み: %s%%" % ln["pct"], ""]
        for key, head in (("aim", "狙い"), ("done", "済み"), ("next", "次"), ("gate", "条件")):
            if ln.get(key):
                out.append("- %s: %s" % (head, linked(ln[key], label)))
        if ln.get("docs"):
            out.append("- 資料: " + "・".join(doc_ref(d, label) for d in ln["docs"]))
        out.append("")
        for t in tasks:
            if lid in str(t.get("line", "")).split("・"):
                used.add(t.get("id"))
                out.append(task_line(t, linked))
        out.append("")
    rest = [t for t in tasks if t.get("id") not in used]
    if rest:
        out += ["## その他", ""] + [task_line(t, linked) for t in rest] + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def write_index(plan_dir):
    with open(os.path.join(plan_dir, "data.js"), encoding="utf-8") as f:
        plan = parse_plan_js(f.read())

    def warn(path, name):
        print("無い資料: %s(%s)" % (path, name), file=sys.stderr)
    text = build_index(plan, plan_dir, warn)
    with open(os.path.join(plan_dir, INDEX_NAME), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return text


def main():
    global PLAN
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, ".artifact-build", "plan"))
    ap.add_argument("--plan", default=None, help="plan フォルダ(既定: 保管庫の plan)")
    ap.add_argument("--no-index", action="store_true", help="計画の索引.md を書かない")
    a = ap.parse_args()
    if a.plan:
        PLAN = os.path.abspath(a.plan)
    if not a.no_index:
        write_index(PLAN)
    css, data, common = read("plan.css"), read("data.js"), read("plan.js")
    os.makedirs(a.out, exist_ok=True)
    index = inline_assets(read("index.html"), css, data, common)
    tasks = inline_assets(read("user-tasks.html"), css, data, common)
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(main_fragment(index))
    with open(os.path.join(a.out, "user-tasks.html"), "w", encoding="utf-8") as f:
        f.write(tasks)
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
