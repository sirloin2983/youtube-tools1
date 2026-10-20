#!/usr/bin/env python3
"""資料の保管庫(layout.notes_root())の plan/ の HTML(index.html・user-tasks.html)を、claude.ai の Artifact(リンクで開けるページ。スマホでも見る)用に 1 枚ずつまとめる。

    python dev/plan_artifact.py [--out <フォルダ>] [--plan <保管庫の plan フォルダ>] [--no-index]
    # --out の既定: <リポジトリ直下>/.artifact-build/plan/   --plan の既定: <保管庫>/plan

計画の正が plan/data/ に分けてあれば、先に軽い仮決めの自動の確定(dev/plan_data.py sweep)と plan/data.js の生成をする。
索引を書くときは、計画の資料の頭の状態・線(dev/doc_state.py)と食い違いの一覧 plan/食い違いの一覧.md(dev/drift_report.py)も作り直す。
あわせて、計画のデータから計画の索引 <plan>/計画の索引.md・線ごとのまとめ <plan>/線*.md・ホームの自動の部分 <保管庫>/ホーム.md を書き出す
(Obsidian で読む用。--no-index で止める)。--graph で保管庫の根の ホーム.md(無いとき)と .obsidian/graph.json の colorGroups・search も書く。
data.js の全体の版(versions の「全体」)は毎回 main の src/ytt/version.py の VERSION に書き直す(手で書かない)。
週の記録のまとめ(docs/worklog/<週>週.md の自動の部分)も dev/worklog.py で作り直す。
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
import posixpath
import re
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

PLAN = os.path.join(layout.notes_root(), "plan")
INDEX_NAME = "計画の索引.md"
HOME_NAME = "ホーム.md"
STATE_JA = {"done": "済み", "doing": "進行中", "next": "次(今できる)", "todo": "あと",
            "wait": "ユーザー待ち", "cont": "継続"}
DOC_PATH = re.compile(r"(?:docs|plan)/[\w./-]*?\.(?:md|html)")
GIT_REF = re.compile(r"git:[0-9a-f]{7,40}:$")
MD_LINK = re.compile(r"(\]\()(<[^>]+>|[^)\s]+)(\))")


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


def link_paths(text, notes, name, warn):
    """文中の docs/・plan/ のパスを Markdown の相対リンクにする(索引は plan/ の中にある)。
    保管庫に無いパスは文字のまま残して warn(path, name)"""
    def sub(m):
        path = m.group(0)
        if GIT_REF.search(text, 0, m.start()):   # git:<コミット>:<パス> = 消した資料(git の履歴で読む)。文字のまま
            return path
        if not os.path.isfile(os.path.join(notes, *path.split("/"))):
            warn(path, name)
            return path
        rel = path[len("plan/"):] if path.startswith("plan/") else "../" + path
        return "[`%s`](%s)" % (path, rel)
    return DOC_PATH.sub(sub, text)


def task_line(t, linked):
    state = STATE_JA.get(t.get("state"), t.get("state") or "")
    return "- %s %s(%s)" % (t.get("id", ""), linked(t.get("name", ""), t.get("id", "")), state)


class Linker:
    """文中の資料のパスを Markdown の相対リンクにする(無い資料は同じ (パス, 名前) を 1 回だけ warn)"""

    def __init__(self, plan_dir, warn):
        self.plan_dir = plan_dir
        self.notes = os.path.dirname(plan_dir)
        self.warn = warn
        self.warned = set()

    def w(self, path, name):
        if (path, name) not in self.warned:
            self.warned.add((path, name))
            self.warn(path, name)

    def text(self, text, name):
        return link_paths(text, self.notes, name, self.w)

    def doc_ref(self, d, name):
        """lines[].docs の項目(plan/ からの相対。docs/・plan/ の頭が付く物も)"""
        if re.match(r"(?:docs|plan)/", d):
            return self.text(d, name)
        if os.path.isfile(os.path.normpath(os.path.join(self.plan_dir, d))):
            return "[`%s`](%s)" % (d, d)
        code = re.sub(r"^(?:\.\./)+", "", d)   # リポジトリの物(README.txt など)は保管庫の外 = 文字だけ
        if os.path.isfile(os.path.join(REPO, *code.split("/"))):
            return "`%s`(リポジトリ)" % code
        self.w(d, name)
        return d


def line_page_name(lid):
    return "線%s.md" % lid


def line_groups(plan):
    """[(線の id・表示名 or None, 線の dict or None, その線の tasks)] を data.js の並びで。最後に当たらない物の「その他」"""
    tasks = plan.get("tasks", [])
    used, groups = set(), []
    for ln in plan.get("lines", []):
        lid = ln.get("id", "")
        mine = [t for t in tasks if lid in str(t.get("line", "")).split("・")]
        used.update(t.get("id") for t in mine)
        groups.append((lid, ln, mine))
    rest = [t for t in tasks if t.get("id") not in used]
    if rest:
        groups.append(("その他", None, rest))
    return groups


def build_line_page(plan, lid, ln, mine, lk):
    """線 1 本のまとめ(Markdown)。ln が None なら「その他」"""
    label = "線 " + lid
    out = ["---", "種類: 索引", "状態: 有効", "線:", "  - %s" % lid, "---", "",
           "# %s%s" % (label, ": " + ln.get("name", "") if ln else "(どの線にも当たらない物)"), "",
           "更新(%s): 自動で作る(dev/plan_artifact.py)・手で直さない" % plan.get("updated", ""), "",
           "[計画の索引](計画の索引.md)・[ホーム](../ホーム.md)", ""]
    if ln:
        if "pct" in ln:
            out += ["進み: %s%%" % ln["pct"], ""]
        for key, head in (("aim", "狙い"), ("done", "済み"), ("next", "次"), ("gate", "条件")):
            if ln.get(key):
                out.append("- %s: %s" % (head, lk.text(ln[key], label)))
        if ln.get("docs"):
            out.append("- 資料: " + "・".join(lk.doc_ref(d, label) for d in ln["docs"]))
        out.append("")
    out += [task_line(t, lk.text) for t in mine] + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def build_line_pages(plan, plan_dir, warn):
    """{ファイル名: 中身}。同じ data.js なら同じ中身"""
    lk = Linker(plan_dir, warn)
    return {line_page_name(lid): build_line_page(plan, lid, ln, mine, lk)
            for lid, ln, mine in line_groups(plan)}


def build_index(plan, plan_dir, warn=None):
    """計画の索引(Markdown。短い)の文字列。線ごとのまとめへのリンクの一覧"""
    out = ["---", "種類: 索引", "状態: 有効", "---", "", "# 計画の索引", "",
           "更新(%s): 自動で作る(dev/plan_artifact.py)・手で直さない" % plan.get("updated", ""), "",
           "計画のページ: [index.html](index.html)・[user-tasks.html](user-tasks.html)", "",
           "## 線ごとのまとめ", ""]
    for lid, ln, mine in line_groups(plan):
        head = "線 %s" % lid
        if ln:
            pct = " %s%%" % ln["pct"] if "pct" in ln else ""
            out.append("- [%s %s](%s)%s" % (head, ln.get("name", ""), line_page_name(lid),
                                            "(進み%s)" % pct if pct else ""))
        else:
            out.append("- [%s](%s)(%d 件)" % (lid, line_page_name(lid), len(mine)))
    return "\n".join(out).rstrip("\n") + "\n"


HOME_BEGIN = "<!-- 自動: ここから(dev/plan_artifact.py が書く。手で直さない) -->"
HOME_END = "<!-- 自動: ここまで -->"
HOME_HAND = """---
種類: 索引
状態: 有効
---

# youtube-tools

## よく見る

- 計画: [全体の計画](plan/index.html)・[やること](plan/user-tasks.html)・[計画の索引](plan/計画の索引.md)
- 決めたこと [decisions](plan/decisions.md)・改善案 [improvements](plan/improvements.md)
- 仕様: [受け渡し](docs/spec/pipeline.md)・[作業データの置き場所](docs/spec/data.md)・[設定](docs/spec/data.md)
- AI 向け: [AGENTS](AGENTS.md)・[資料の索引](docs/資料の索引.md)・[作業の記録](docs/worklog/README.md)・[食い違いの一覧](plan/食い違いの一覧.md)
"""
WEEK_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}週\.md$")
STATE_ORDER = ("doing", "next", "wait")
STATE_CAP = 8


def first_sentences(text, n=3):
    """。で区切って先頭 n 文(括弧の中の。では区切らない)"""
    depth, sents, cur = 0, [], []
    for c in text:
        cur.append(c)
        if c in "((":
            depth += 1
        elif c in "))":
            depth = max(0, depth - 1)
        elif c == "。" and depth == 0:
            sents.append("".join(cur))
            cur = []
            if len(sents) == n:
                break
    if cur and len(sents) < n:
        sents.append("".join(cur))
    return "".join(sents).strip()


def cell(text, limit=60):
    text = re.sub(r"\s+", " ", str(text)).replace("|", "/").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def week_summary(notes):
    """docs/worklog/ の最新の週のファイル名と「## まとめ」の節(無ければ (None, None))"""
    d = os.path.join(notes, "docs", "worklog")
    names = sorted(n for n in os.listdir(d) if WEEK_FILE.match(n)) if os.path.isdir(d) else []
    if not names:
        return None, None
    with open(os.path.join(d, names[-1]), encoding="utf-8") as f:
        lines = f.read().replace("\r\n", "\n").split("\n")
    body, on = [], False
    for ln in lines:
        if not on:
            on = ln.strip() == "## まとめ"
        elif ln.startswith("## ") or ln.strip() == "---":
            break
        else:
            body.append(ln)
    return names[-1], "\n".join(body).strip("\n")


def build_home_auto(plan, plan_dir):
    """ホームの自動の部分(印の間)の中身"""
    notes = os.path.dirname(plan_dir)
    out = ["## 今の状況(%s)" % plan.get("updated", ""), "", first_sentences(plan.get("summary", "")), "",
           "| 線 | 進み | 次 |", "| --- | --- | --- |"]
    for lid, ln, mine in line_groups(plan):
        if ln:
            pct = "%s%%" % ln["pct"] if "pct" in ln else ""
            out.append("| [線 %s %s](plan/%s) | %s | %s |" % (lid, ln.get("name", ""), line_page_name(lid), pct,
                                                           cell(ln.get("next", ""))))
        else:
            out.append("| [%s](plan/%s) | | %d 件 |" % (lid, line_page_name(lid), len(mine)))
    out += ["", "## 動いている・次にやる", ""]
    tasks = plan.get("tasks", [])
    for st in STATE_ORDER:
        sel = [t for t in tasks if t.get("state") == st]
        if not sel:
            continue
        out.append("- %s(%d 件)" % (STATE_JA[st], len(sel)))
        for t in sel[:STATE_CAP]:
            out.append("  - 線 %s: %s %s" % (t.get("line", ""), t.get("id", ""), cell(t.get("name", ""), 80)))
        if len(sel) > STATE_CAP:
            out.append("  - ほか %d 件" % (len(sel) - STATE_CAP))
    out += ["", "## 確認待ちの仮決め: %d 件" % len(plan.get("userTasks", {}).get("provisional", [])), "",
            "[一覧](plan/decisions.md)", "", "## 今週の作業", ""]
    name, summary = week_summary(notes)
    if name is None:
        out.append("(まだ無い)")
    else:
        out += [rebase_links(summary, "docs/worklog"), "", "[詳しく](docs/worklog/%s)" % name]
    return "\n".join(out).rstrip("\n") + "\n"


def rebase_links(text, src_dir):
    """src_dir(保管庫の直下からの相対)にあった Markdown の相対リンクを、保管庫の直下(ホーム)から見たパスに直す。
    URL・ページ内の # ・保管庫の外へ出るリンクはそのまま"""
    def sub(m):
        target = m.group(2)
        angle = target.startswith("<")
        path, frag = (target[1:-1] if angle else target), ""
        if "#" in path:
            path, frag = path.split("#", 1)
            frag = "#" + frag
        if not path or re.match(r"[A-Za-z][\w+.-]*:", path) or path.startswith("/"):
            return m.group(0)
        new = posixpath.normpath(posixpath.join(src_dir, path))
        if new.startswith(".."):
            return m.group(0)
        new += frag
        return m.group(1) + ("<%s>" % new if angle else new) + m.group(3)
    return MD_LINK.sub(sub, text)


def merge_home(existing, auto):
    """既存のホームの印の間だけ差し替える(印が無ければ末尾に足す。existing が None なら手書きの初めの中身から)"""
    block = HOME_BEGIN + "\n" + auto + HOME_END + "\n"
    if existing is None:
        return HOME_HAND + "\n" + block
    a = existing.find(HOME_BEGIN)
    b = existing.find(HOME_END, a + 1) if a >= 0 else -1
    if a >= 0 and b >= 0:
        return existing[:a] + block + existing[b + len(HOME_END):].lstrip("\n")
    return existing.rstrip("\n") + "\n\n" + block


def write_text(path, text):
    # data.js の文に入っている「#pack」「[送る](説明)」が Obsidian のタグ・リンクにならないように(notes_tool と同じ直し)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import notes_tool
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(notes_tool.unlink_prose(text) if path.endswith(".md") else text)


def load_plan(plan_dir):
    """計画のデータ(plan/data/)"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plan_data
    return plan_data.load(plan_dir)


DOC_INDEX = "docs/資料の索引.md"
DOC_GROUPS = (("入口", ("AGENTS.md", "ホーム.md"), False), ("製品の今の正(docs/spec/)", ("docs/spec",), True),
              ("これからの計画・決めたこと(plan/)", ("plan",), False), ("済んだ計画(plan/done/)", ("plan/done",), False),
              ("経緯(docs/design/)", ("docs/design",), True), ("作業の記録", ("docs/worklog/README.md",), False))


def doc_title(text):
    m = re.search(r"^# (.+)$", text, re.M)
    st = re.search(r"^状態:\s*(\S+)", text, re.M)
    return (m.group(1).strip() if m else ""), (st.group(1) if st else "")


def build_doc_index(notes):
    """資料の索引(どの資料に何があるか)。資料の頭の 状態 と最初の見出しから作る = 手で説明を書き写さない"""
    out = ["---", "種類: 索引", "状態: 有効", "---", "", "# 資料の索引", "",
           "自動で作る(dev/plan_artifact.py)・手で直さない。説明は各資料の最初の見出し、状態は資料の頭のプロパティ"
           "(計画の物は計画のデータから = dev/doc_state.py)。入口は [AGENTS.md](../AGENTS.md)(AI)と [ホーム](../ホーム.md)(人)", ""]
    for head, roots, deep in DOC_GROUPS:
        rows = []
        for r in roots:
            full = os.path.join(notes, *r.split("/"))
            if os.path.isfile(full):
                paths = [r]
            elif os.path.isdir(full):
                paths = []
                for base, dirs, files in os.walk(full):
                    dirs.sort()
                    paths += [os.path.relpath(os.path.join(base, f), notes).replace(os.sep, "/") for f in sorted(files) if f.endswith(".md")]
                    if not deep:
                        break
            else:
                continue
            for p in paths:
                with open(os.path.join(notes, *p.split("/")), encoding="utf-8") as f:
                    title, st = doc_title(f.read())
                rows.append("- [`%s`](%s)%s — %s" % (p, posixpath.relpath(p, "docs").replace(" ", "%20"),
                                                    "(%s)" % st if st else "", cell(title, 80)))
        out += ["## %s" % head, ""] + (rows or ["(無し)"]) + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def write_index(plan_dir):
    """計画の索引・線ごとのまとめ・資料の索引・ホームを書く(plan_dir は <保管庫>/plan)"""
    plan = load_plan(plan_dir)
    write_text(os.path.join(os.path.dirname(plan_dir), *DOC_INDEX.split("/")), build_doc_index(os.path.dirname(plan_dir)))
    import worklog
    worklog.build(os.path.dirname(plan_dir))

    def warn(path, name):
        print("無い資料: %s(%s)" % (path, name), file=sys.stderr)
    for name, body in build_line_pages(plan, plan_dir, warn).items():
        write_text(os.path.join(plan_dir, name), body)
    text = build_index(plan, plan_dir)
    write_text(os.path.join(plan_dir, INDEX_NAME), text)
    home = os.path.join(os.path.dirname(plan_dir), HOME_NAME)
    existing = None
    if os.path.isfile(home):
        with open(home, encoding="utf-8") as f:
            existing = f.read().replace("\r\n", "\n")
    write_text(home, merge_home(existing, build_home_auto(plan, plan_dir)))
    return text


# 保管庫の根(notes_root の 1 つ上)の物。無いときだけ作る/キーを足す
VAULT_HOME = """---
種類: 索引
---

# 保管庫のホーム

## プロジェクト

- [youtube-tools](%s/ホーム.md) — YouTube ショート動画の編集支援ツール
"""
PLUGIN_ID = "graph-history-toggle"
GRAPH_HIDE = "-[状態:済み] -[状態:置き換え済み] -[状態:取り下げ]"   # dev/obsidian/graph-history-toggle/main.js の HIDE と同じ
GRAPH_COLORS = (  # 上から先に当たった色。灰(済んだ物)→ 種類ごと
    ("[状態:済み]", 0x8A8F98), ("[状態:置き換え済み]", 0x8A8F98), ("[状態:取り下げ]", 0x8A8F98),
    ("[種類:決まり]", 0xE5484D), ("[種類:索引]", 0xF2C94C), ("[種類:仕様]", 0x3B82F6),
    ("[種類:設計]", 0xA855F7), ("[種類:計画]", 0x22C55E), ("[種類:レビュー]", 0xF97316))


def write_vault_extras(notes, graph=True):
    """保管庫の根のホーム(無いときだけ)と graph.json の colorGroups・search(今の中身のほかのキーは残す)"""
    root = os.path.dirname(notes)
    home = os.path.join(root, HOME_NAME)
    if not os.path.isfile(home):
        write_text(home, VAULT_HOME % os.path.basename(notes))
    gp = os.path.join(root, ".obsidian", "graph.json")
    if not graph:
        return
    # グラフの「経緯の表示・非表示」のボタン(自作のプラグイン。正本は dev/obsidian/。オンにするのは Obsidian の設定で人が 1 回)
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obsidian", PLUGIN_ID)
    dst = os.path.join(root, ".obsidian", "plugins", PLUGIN_ID)
    os.makedirs(dst, exist_ok=True)
    for name in ("manifest.json", "main.js"):
        shutil.copyfile(os.path.join(src, name), os.path.join(dst, name))
    if not os.path.isfile(gp):
        print("graph.json が無い(Obsidian で一度グラフを開く): %s" % gp, file=sys.stderr)
        return
    with open(gp, encoding="utf-8") as f:
        g = json.load(f)
    # 普段は経緯(状態が 済み・置き換え済み・取り下げ)を隠す。直し待ちのレビュー・今週の記録(進行中)は出る。
    # グラフの左のボタン(プラグイン graph-history-toggle)で「すべてのファイル」と切り替える。条件の文字はプラグインの HIDE と同じ
    g["search"] = GRAPH_HIDE
    g["colorGroups"] = [{"query": q, "color": {"a": 1, "rgb": rgb}} for q, rgb in GRAPH_COLORS]
    write_text(gp, json.dumps(g, ensure_ascii=False, indent=2) + "\n")


def main():
    global PLAN
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, ".artifact-build", "plan"))
    ap.add_argument("--plan", default=None, help="plan フォルダ(既定: 保管庫の plan)")
    ap.add_argument("--no-index", action="store_true", help="計画の索引・線ごとのまとめ・ホームを書かない")
    ap.add_argument("--graph", action="store_true",
                    help="保管庫の根のホーム(無いとき)と .obsidian/graph.json の色と検索を書く(Obsidian を閉じてから)")
    a = ap.parse_args()
    if a.plan:
        PLAN = os.path.abspath(a.plan)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plan_data
    if not plan_data.has_split(PLAN):
        print("plan/data/main.json が無い: %s" % PLAN, file=sys.stderr)
        return 1
    plan_data.sweep(PLAN)   # 正は plan/data/(1 件 1 ファイル)。軽い仮決めの自動の確定 → data.js を作る
    _wrote, probs = plan_data.build(PLAN)
    if probs:
        for f, ln, msg in probs:
            print("%s:%d %s" % (f, ln, msg), file=sys.stderr)
        return 1
    if not a.no_index:
        import doc_state
        import drift_report
        doc_state.sync(os.path.dirname(PLAN))   # 計画の資料の頭の状態・線は計画のデータから(手で書かない)
        write_index(PLAN)
        if os.path.normcase(os.path.dirname(PLAN)) == os.path.normcase(layout.notes_root()):   # 本物の保管庫だけ(リポジトリ全体を読むので重い)
            drift_report.write_report(os.path.dirname(PLAN))   # 食い違いの一覧(仮決めの一覧と同じ時に作り直す)
    if a.graph:
        write_vault_extras(os.path.dirname(PLAN))
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
