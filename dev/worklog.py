#!/usr/bin/env python3
"""作業の記録(保管庫の docs/worklog/)をセッションごとのファイルに分けて書き、週のまとめを集めて作る(2026-10-18)。

    python dev/worklog.py new <セッションの名前> [--date YYYY-MM-DD] [--title 見出し] [--who "Claude Code(…。Opus)"]
        # docs/worklog/<その週の月曜>週/<日付>-<名前>.md を作り(あればそのまま)、パスを出す。続けて週のまとめを作り直す
    python dev/worklog.py build      # 週のまとめ docs/worklog/<週>週.md の自動の部分と docs/worklog/README.md(記録の書式と週の一覧)の週の一覧を作り直す
    python dev/worklog.py check <セッションの名前かパス>   # 報告の型の検査(決まった見出し・英字の割合)。見出しが欠けたら終了コード 1
        # dev/land.py が main に入れる前に、入れるセッションの記録について流す(名前の既定 = ブランチの claude/ と末尾の -16 進を外した物)

セッションのファイルは、そのセッションだけが書く(ほかのセッションの記録を巻き込まない・末尾の取り合いが無い)。
頭のプロパティ「まとめ」(1 行)を、週のまとめの「## まとめ」に新しい順で並べる。1 つのセッションで何度か書くときは同じファイルに「## 」で足す。
週のファイルの印 <!-- 自動: ここから --> 〜 <!-- 自動: ここまで --> の間だけが自動(10-18 より前に手で書いた所はそのまま残す)。
"""
import argparse
import datetime
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

BEGIN = "<!-- 自動: ここから(dev/worklog.py が書く。手で直さない) -->"
END = "<!-- 自動: ここまで -->"
WEEK_DIR = re.compile(r"^(\d{4}-\d{2}-\d{2})週$")
SESSION_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
NAME_OK = re.compile(r"^[^\\/:*?\"<>|\s]+$")
LIST_HEAD = "## 週のファイル(新しい週が上)"
PLACEHOLDER = "(1 行で。週のまとめに出る)"
# 報告の型(2026-10-18。AGENTS.md の「作業の記録」)。各見出しが 1 回は要る(中身が無ければ「なし」)。「## 見出し」か「- 見出し:」の形
HEADINGS = ("直した物", "確かめた物", "本物ではまだ確かめていない物", "ユーザーがすること")
TEMPLATE = """---
種類: 記録
状態: 有効
まとめ: {summary}
---
# {date} {who}— {title}
- 直した物:
- 確かめた物:
- 本物ではまだ確かめていない物:
- ユーザーがすること: なし
- 仮で決めたこと: なし
- 未コミット: なし
"""
# 英字の割合: コードの名前・パス・コマンド(`…`・``` の塊・リンクの先・URL・. / \ : を含む語)は数えない。
# 10-18 までの日本語の記録は 0.18〜0.29(仮名と漢字は 1 字ずつ・英字も 1 字ずつ数える)。英語の文が混ざると 0.5 を超える
EN_LIMIT = 0.45
EN_MIN_CHARS = 300   # これより短い記録は割合を見ない(雛形のままなど)
_DROP = [re.compile(p, re.S) for p in (r"```.*?```", r"`[^`\n]*`", r"\]\([^)]*\)", r"https?://\S+",
                                         r"[A-Za-z0-9_.\-]*[/\\.:][A-Za-z0-9_./\\\-]+")]
_ASCII = re.compile(r"[A-Za-z]")
_JP = re.compile(r"[぀-ヿ㐀-鿿＀-￯]")


def worklog_dir(notes=None):
    return os.path.join(notes or layout.notes_root(), "docs", "worklog")


def monday(day):
    return day - datetime.timedelta(days=day.weekday())


def week_name(day):
    return "%s週" % monday(day).isoformat()


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def front_matter(text):
    """頭の YAML の 1 行の値だけ(key: value)を dict に。リストの値は読まない"""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    out = {}
    for ln in text[4:end if end >= 0 else 0].split("\n"):
        m = re.match(r"^([^\s:#][^:]*):\s*(.*)$", ln)
        if m and m.group(2):
            out[m.group(1).strip()] = m.group(2).strip().strip('"')
    return out


def session_entry(path):
    """-> (日付, 名前, 見出しの行, まとめ)"""
    name = os.path.basename(path)
    m = SESSION_FILE.match(name)
    text = read(path)
    title = next((ln[2:].strip() for ln in text.split("\n") if ln.startswith("# ")), name[:-3])
    summary = front_matter(text).get("まとめ", "")
    return m.group(1), m.group(2), title, "" if summary == PLACEHOLDER else summary


def sessions(week_path):
    """週のフォルダのセッションのファイル(新しい順 = 日付の逆・同じ日は名前の順)"""
    names = [n for n in os.listdir(week_path) if SESSION_FILE.match(n)]
    entries = [session_entry(os.path.join(week_path, n)) for n in names]
    return sorted(entries, key=lambda e: (e[0], e[1]), reverse=True)


def auto_block(week, entries):
    out = [BEGIN, "## まとめ"]
    for date, name, _title, summary in entries:
        out.append("- %s %s: %s" % (date[5:], name, summary or "(まとめ未記入)"))
    if not entries:
        out.append("- (まだ無い)")
    out += ["", "## セッションの記録(新しい順)"]
    for date, name, title, _summary in entries:
        out.append("- [%s](%s/%s-%s.md)" % (title.replace("[", "(").replace("]", ")"), week, date, name))
    out.append(END)
    return "\n".join(out) + "\n"


def merge_week(existing, week, block):
    """週のファイルの印の間を差し替える。無ければ作る(10-18 より前の手書きの週は見出しの下に入れ、前の「## まとめ」は名前を変える)"""
    if existing is None:
        return ("---\n種類: 記録\n状態: 進行中\n---\n# 作業の記録 %s(%s〜)\n\n" % (week, week[5:10]) + block)
    a = existing.find(BEGIN)
    b = existing.find(END, a + 1) if a >= 0 else -1
    if a >= 0 and b >= 0:
        return existing[:a] + block + existing[b + len(END):].lstrip("\n")
    lines = existing.split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.startswith("# ")), -1) + 1
    rest = "\n".join(lines[i:]).replace("\n## まとめ\n", "\n## まとめ(分ける前に手で書いた分)\n", 1)
    return "\n".join(lines[:i]) + "\n\n" + block + rest


def update_index(notes, weeks):
    """docs/worklog/README.md の週の一覧に、まだ無い週の行を足す(新しい週が上)"""
    path = os.path.join(notes, "docs", "worklog", "README.md")
    if not os.path.isfile(path):
        return False
    text = read(path)
    add = ["- [%s](%s.md)(%s〜。セッションごとのファイルは %s/)" % (w, w, w[5:10], w)
           for w in sorted(weeks, reverse=True) if "](%s.md)" % w not in text]
    if not add or LIST_HEAD not in text:
        return False
    i = text.index(LIST_HEAD) + len(LIST_HEAD)
    write(path, text[:i] + "\n" + "\n".join(add) + text[i:])
    return True


def build(notes=None):
    """週のフォルダがある週の、週のまとめを作り直す。-> 書き直したファイルの数"""
    notes = notes or layout.notes_root()
    d = worklog_dir(notes)
    if not os.path.isdir(d):
        return 0
    weeks = sorted(n for n in os.listdir(d) if WEEK_DIR.match(n) and os.path.isdir(os.path.join(d, n)))
    n = 0
    for w in weeks:
        path = os.path.join(d, w + ".md")
        existing = read(path) if os.path.isfile(path) else None
        new = merge_week(existing, w, auto_block(w, sessions(os.path.join(d, w))))
        if new != existing:
            write(path, new)
            n += 1
    if update_index(notes, weeks):
        n += 1
    return n


def new(name, day=None, title="", who="Claude Code ", notes=None):
    """セッションのファイルを作る(あればそのまま)。-> パス"""
    if not NAME_OK.match(name):
        raise SystemExit("名前に空白や \\ / : * ? \" < > | は使えません: %r" % name)
    day = day or datetime.date.today()
    d = os.path.join(worklog_dir(notes), week_name(day))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s-%s.md" % (day.isoformat(), name))
    if not os.path.isfile(path):
        write(path, TEMPLATE.format(summary=PLACEHOLDER, date=day.isoformat(),
                                    who=who, title=title or name))
    build(notes)
    return path


def body_of(text):
    """頭の YAML を外した本文"""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            return text[end + 4:]
    return text


def english_ratio(text):
    """-> (英字の割合, 英字の数, 日本語の字の数)。コードの名前・パス・コマンドは数えない"""
    t = body_of(text)
    for r in _DROP:
        t = r.sub(" ", t)
    a, j = len(_ASCII.findall(t)), len(_JP.findall(t))
    return a / max(1, a + j), a, j


def missing_headings(text):
    """決まった見出しのうち、無い物"""
    body = body_of(text)
    return [h for h in HEADINGS
            if not re.search(r"^(#{2,4}\s*|[-*]\s*(\*\*)?)%s(\*\*)?\s*([:：(]|$)" % re.escape(h), body, re.M)]


def find_session(name, notes=None):
    """セッションの名前 → 記録のファイル(いちばん新しい物)。パスならそのまま。無ければ None"""
    if os.path.isfile(name):
        return name
    d = worklog_dir(notes)
    if not os.path.isdir(d):
        return None
    found = []
    for w in os.listdir(d):
        wp = os.path.join(d, w)
        if WEEK_DIR.match(w) and os.path.isdir(wp):
            for n in os.listdir(wp):
                m = SESSION_FILE.match(n)
                if m and m.group(2) == name:
                    found.append((m.group(1), os.path.join(wp, n)))
    return max(found)[1] if found else None


def check(path):
    """報告の型の検査 -> (止める問題, 警告)。見出しが欠けたら止める・英字の割合は警告だけ"""
    text = read(path)
    probs = ["見出し「%s」が無い(中身が無ければ「- %s: なし」)" % (h, h) for h in missing_headings(text)]
    ratio, a, j = english_ratio(text)
    warns = []
    if a + j >= EN_MIN_CHARS and ratio > EN_LIMIT:
        warns.append("英字が多い(%.0f%%。目安 %.0f%% 以下。コードの名前・パスは `…` で囲むと数えない)" % (ratio * 100, EN_LIMIT * 100))
    return probs, warns


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("new")
    p.add_argument("name")
    p.add_argument("--date")
    p.add_argument("--title", default="")
    p.add_argument("--who", default="Claude Code ")
    sub.add_parser("build")
    p = sub.add_parser("check")
    p.add_argument("name")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        path = find_session(a.name)
        if not path:
            print("記録のファイルが無い: %s(dev/worklog.py new %s で作る)" % (a.name, a.name))
            return 1
        probs, warns = check(path)
        for s in probs:
            print("[止める] " + s)
        for s in warns:
            print("[警告] " + s)
        print("%s: 問題 %d・警告 %d" % (path, len(probs), len(warns)))
        return 1 if probs else 0
    if a.cmd == "new":
        day = datetime.date.fromisoformat(a.date) if a.date else None
        print(new(a.name, day, a.title, a.who))
        return 0
    if a.cmd == "build":
        print("書き直したファイル %d 本" % build())
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
