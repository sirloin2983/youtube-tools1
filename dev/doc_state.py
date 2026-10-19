#!/usr/bin/env python3
"""計画の資料の頭の `状態`・`線` を計画の正(保管庫の plan/data/)から決めて書く・食い違いを止める。

    python dev/doc_state.py check     # 食い違いを並べる(終了コード 1 = ある)。dev/notes_tool.py check も同じ物を数える
    python dev/doc_state.py sync      # 頭の 2 行(状態・線)だけを計画のデータに合わせて書き直す(notes_tool check --fix も同じ)

対応は tasks(と history)の欄 `docs`(plan/ からの相対のパスの並び。1 つの資料を複数の作業が指してよい)。
決め方: 指す作業が全部 done(history は done と数える)→ 済み / 全部 todo → これから / それ以外 → 進行中。
線 = 指す作業の line を「・」で割った和集合(運用 → 全体)。どの作業も指さない資料の状態は手で持つ(議論中・有効・取り下げなど)。
置き場所の規則: 状態が 済み・取り下げ・置き換え済み の計画は plan/done/、plan/done/ の物はそのどれか(種類: 索引 の自動の物は見ない)。
書き直すのは頭の `状態:` と `線:`(続く `  - ` の行)だけで、ほかの行と改行(CRLF / LF)は 1 バイトも変えない。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

DONE_STATES = ("済み", "取り下げ", "置き換え済み")
LINE_ORDER = ("A", "B", "C", "D", "別件", "全体")
LINE_ALIAS = {"運用": "全体"}
FIX_HINT = "py -3.12 dev/notes_tool.py check --fix で直す"


def plan_data():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plan_data as pd
    return pd


def task_lines(line):
    out = set()
    for x in str(line or "").split("・"):
        x = LINE_ALIAS.get(x.strip(), x.strip())
        if x in LINE_ORDER:
            out.add(x)
    return out


def decide(states):
    if all(s == "done" for s in states):
        return "済み"
    if all(s == "todo" for s in states):
        return "これから"
    return "進行中"


def derived(root):
    """{資料(保管庫からの相対): (状態, [線], [指す作業の id])}"""
    pd = plan_data()
    plan = os.path.join(root, "plan")
    if not pd.has_split(plan):
        return {}
    got = {}
    for kind in ("tasks", "history"):
        for _n, it, err in pd.items(plan, kind):
            if err or not isinstance(it, dict):
                continue
            for d in it.get("docs") or []:
                rel = os.path.normpath(os.path.join("plan", d)).replace(os.sep, "/")
                st = it.get("state", "") if kind == "tasks" else "done"
                got.setdefault(rel, []).append((st, task_lines(it.get("line")), it.get("id")))
    out = {}
    for rel, xs in got.items():
        lines = set().union(*(x[1] for x in xs))
        out[rel] = (decide([x[0] for x in xs]), [l for l in LINE_ORDER if l in lines], [x[2] for x in xs])
    return out


# ---------------------------------------------------------------- 頭(YAML)を読む・2 行だけ書き直す

def front(text):
    """-> (頭の行の並び(改行つき), 頭の終わりの位置) か None。頭 = 先頭の --- から次の --- まで"""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[:i + 1], sum(len(x) for x in lines[:i + 1])
    return None


def read_props(head):
    """頭の行から (状態, [線])。線はブロック形式・行内 [A, B]・引用符つきを受ける"""
    state, lines = None, None
    for i, ln in enumerate(head):
        m = re.match(r"状態:\s*(.*?)\s*$", ln)
        if m:
            state = m.group(1).strip("'\"")
        m = re.match(r"線:\s*(.*?)\s*$", ln)
        if m:
            v = m.group(1)
            if v.startswith("["):
                lines = [x.strip().strip("'\"") for x in v.strip("[]").split(",") if x.strip()]
            elif v:
                lines = [v.strip("'\"")]
            else:
                lines = []
                for nxt in head[i + 1:]:
                    mm = re.match(r"\s+-\s*(.*?)\s*$", nxt)
                    if not mm:
                        break
                    lines.append(mm.group(1).strip("'\""))
    return state, lines


def write_props(text, state, lines):
    """頭の 状態 と 線 だけを差し替えた文字列(lines が None なら線は触らない)。頭が無ければ None"""
    fr = front(text)
    if fr is None:
        return None
    head, end = fr
    nl = "\r\n" if head[0].endswith("\r\n") else "\n"
    out, i, put_state, put_lines = [], 0, False, lines is None
    block = (["線:" + nl] + ["  - %s%s" % (l, nl) for l in lines]) if lines else []
    while i < len(head):
        ln = head[i]
        if re.match(r"状態:", ln):
            out.append("状態: %s%s" % (state, nl))
            put_state = True
        elif re.match(r"線:", ln) and lines is not None:
            i += 1
            while i < len(head) and re.match(r"\s+-", head[i]):
                i += 1
            out += block
            put_lines = True
            continue
        elif ln.strip() == "---" and i == len(head) - 1:
            if not put_state:
                out.append("状態: %s%s" % (state, nl))
            if not put_lines:
                out += block
            out.append(ln)
        else:
            out.append(ln)
        i += 1
    return "".join(out) + text[end:]


def read(p):
    with open(p, "rb") as f:
        return f.read().decode("utf-8")


def write(p, text):
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "wb") as f:
        f.write(text.encode("utf-8"))
    os.replace(tmp, p)


# ---------------------------------------------------------------- 検査と書き直し

def plan_docs(root):
    """plan/ の直下と plan/done/ の md(保管庫からの相対)"""
    out = []
    for sub in ("plan", "plan/done"):
        d = os.path.join(root, *sub.split("/"))
        if os.path.isdir(d):
            out += ["%s/%s" % (sub, n) for n in sorted(os.listdir(d)) if n.endswith(".md")]
    return out


def check(root=None):
    """-> [(資料, 行, 説明)]"""
    root = root or layout.notes_root()
    if not os.path.isdir(root):
        return []
    bad = []
    der = derived(root)
    for rel, (state, lines, ids) in sorted(der.items()):
        p = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(p):
            bad.append((rel, 1, "計画のデータの docs が指す資料が無い(%s)" % "・".join(ids)))
            continue
        fr = front(read(p))
        if fr is None:
            bad.append((rel, 1, "頭(YAML のプロパティ)が無い"))
            continue
        hs, hl = read_props(fr[0])
        if hs != state:
            bad.append((rel, 1, "状態が計画のデータと違う: %s → %s(%s。%s)" % (hs, state, "・".join(ids), FIX_HINT)))
        if lines and hl != lines:
            bad.append((rel, 1, "線が計画のデータと違う: %s → %s(%s)" % ("・".join(hl or []), "・".join(lines), FIX_HINT)))
    for rel in plan_docs(root):
        fr = front(read(os.path.join(root, *rel.split("/"))))
        if fr is None:
            continue
        head = "".join(fr[0])
        if re.search(r"^種類:\s*索引", head, re.M):
            continue
        state = read_props(fr[0])[0]
        st = der.get(rel, (state,))[0]   # 計画のデータが決める物はその値で見る(--fix のあとの置き場所)
        if rel.startswith("plan/done/") and st not in DONE_STATES:
            bad.append((rel, 1, "plan/done/ にあるのに 状態: %s(済んでいないなら plan/ へ戻す)" % st))
        elif not rel.startswith("plan/done/") and st in DONE_STATES:
            bad.append((rel, 1, "状態: %s の計画は plan/done/ へ(py -3.12 dev/notes_tool.py mv。有効な決まりが残るなら先に decisions か spec へ)" % st))
    return bad


def sync(root=None):
    """頭の 状態・線 を計画のデータに合わせる。-> 書き直したファイル(保管庫からの相対)"""
    root = root or layout.notes_root()
    done = []
    for rel, (state, lines, _ids) in sorted(derived(root).items()):
        p = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(p):
            continue
        text = read(p)
        new = write_props(text, state, lines or None)
        if new is not None and new != text:
            write(p, new)
            done.append(rel)
    for rel in done:
        print("頭の状態・線を直した: %s" % rel, file=sys.stderr)
    return done


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if argv[:1] == ["sync"]:
        print("直したファイル %d 本" % len(sync()))
        return 0
    if argv[:1] == ["check"]:
        bad = check()
        for where, ln, msg in bad:
            print("%s:%d %s" % (where, ln, msg))
        print("資料の状態の食い違い %d 件" % len(bad))
        return 1 if bad else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
