#!/usr/bin/env python3
"""計画のデータ(保管庫の plan/data/。計画の正)を 1 件 1 ファイルで持ち、表示用の plan/data.js を集めて作る。

    python dev/plan_data.py build                      # plan/data/ から plan/data.js を作る(手で直さない。git にも入れない)
    python dev/plan_data.py check                      # 各 JSON が読めるか・id の重複・ファイル名・必須の欄・参照(終了コード 1 = 問題あり)
    python dev/plan_data.py new <種類> <id> [欄=値 ...]  # 1 件の雛形を作る(order とファイル名は道具が振る)。種類 = tasks・recent・history・user・provisional
    python dev/plan_data.py sweep [--today YYYY-MM-DD] [--dry-run]
        # 軽い仮決めで入れて 7 日たち hold の無い物を確定へ移し(plan/data/confirmed/)、仮決めの一覧 plan/仮決めの一覧.md を作り直す
    python dev/plan_data.py split                      # 1 回きり: 今の手書きの plan/data.js を plan/data/ に分ける

並行のセッションが 1 つの data.js の末尾に同時に書き足すとカンマ抜けで壊れるので、配列の 1 件を 1 ファイルにする:
  plan/data/main.json        めったに直さない共有の部分(updated・lines・phases・totals・critical・schedule・gates・numbers・conflicts・userTasks の残り)
  plan/data/summary.md       全体の説明(PLAN.summary。素の文)
  plan/data/<種類>/<名前>.json  tasks・recent・history・user(userTasks の ordered / later。欄 list)・provisional・confirmed(自動で確定した仮決め)
並びは各ファイルの order(小さい順。同じなら id)。provisional は重い物が先・新しい順。ファイル名は id から道具が作る ASCII(slug)。
全体の版(versions の「全体」)は main ブランチの src/ytt/version.py から入れる(worktree の枝の版は入れない)。
"""
import argparse
import binascii
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from ytt import layout  # noqa: E402

KINDS = ("tasks", "recent", "history", "user", "provisional", "confirmed")
REQUIRED = {"tasks": ("id", "name", "state"), "recent": ("id", "name"), "history": ("id", "name"),
            "user": ("id", "name", "list"), "provisional": ("sec", "id", "date", "what", "weight"),
            "confirmed": ("sec", "id", "what", "confirmed")}
USER_LISTS = ("ordered", "later")
WEIGHTS = ("軽", "重")
WHY = ("形", "戻せない", "データ", "言い方")
LIGHT_DAYS = 7
RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}
KEY_ORDER = ("id", "sec", "name", "list", "line", "who", "phase", "pre", "rec", "ai", "user", "state", "date", "added",
             "weight", "why", "what", "impact", "hold", "confirmed", "order")
HEADER = ("/* plan/data.js — 自動で作る(dev/plan_data.py build)。手で直さない・git に入れない。\n"
          "   計画の正は plan/data/(1 件 1 ファイル。直し方は plan/data/README.md)。ここを直しても次の build で消える。 */\n")
PROV_LIST = "仮決めの一覧.md"
WHOLE = "全体"


def plan_dir_default():
    return os.path.join(layout.notes_root(), "plan")


def data_dir(plan_dir):
    return os.path.join(plan_dir, "data")


def has_split(plan_dir):
    return os.path.isfile(os.path.join(data_dir(plan_dir), "main.json"))


# ---------------------------------------------------------------- 読み書き

def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def write_atomic(path, text):
    """一時ファイルに書いてから置き換える(書きかけを他のセッションの build が読まない)"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def ordered_keys(d):
    keys = [k for k in KEY_ORDER if k in d] + sorted(k for k in d if k not in KEY_ORDER)
    return {k: d[k] for k in keys}


def dumps(d):
    return json.dumps(ordered_keys(d) if isinstance(d, dict) else d, ensure_ascii=False, indent=2) + "\n"


def slug(text):
    """id → ファイル名(英数と - だけ・小文字)。①〜㉙ は数字に。ほかの日本語の字があれば id の crc を足す(重ならないように)"""
    out, lost = [], False
    for c in str(text):
        if c.isascii() and c.isalnum():
            out.append(c.lower())
        elif not c.isascii() and unicodedata.numeric(c, None) is not None and float(unicodedata.numeric(c)).is_integer():
            out.append("%d" % unicodedata.numeric(c))
        elif c.isascii():
            out.append("-")
        else:
            lost = True
            out.append("-")
    s = re.sub(r"-+", "-", "".join(out)).strip("-")
    if lost or not s:
        s = (s + "-" if s else "") + "%06x" % (binascii.crc32(str(text).encode("utf-8")) & 0xFFFFFF)
    return s + "_" if s in RESERVED else s


def file_name(kind, item):
    if kind in ("provisional", "confirmed"):
        return "%s-%s.json" % (slug(item.get("sec", "")), slug(item.get("id", "")))
    if kind == "recent":
        return "%s.json" % slug(item.get("id", ""))
    return "%s.json" % slug(item.get("id", ""))


def items(plan_dir, kind):
    """-> [(ファイル名, dict か None(読めない), 読めない理由)]"""
    d = os.path.join(data_dir(plan_dir), kind)
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        if not n.endswith(".json"):
            continue
        try:
            out.append((n, json.loads(read_text(os.path.join(d, n))), None))
        except ValueError as e:
            out.append((n, None, str(e)))
    return out


def sort_key(kind):
    if kind == "provisional":
        return lambda it: (0 if it.get("weight") == "重" else 1, it.get("order", 0), str(it.get("id")))
    return lambda it: (it.get("order", 0), str(it.get("id")))


def main_version():
    """main ブランチの版(読めなければ今の作業フォルダの版)"""
    try:
        r = subprocess.run(["git", "-C", REPO, "show", "main:src/ytt/version.py"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', r.stdout.decode("utf-8", "replace"), re.M)
        if r.returncode == 0 and m:
            return m.group(1)
    except OSError:
        pass
    from ytt.version import VERSION
    return VERSION


def strip_internal(it):
    return {k: v for k, v in it.items() if k not in ("order", "list")}


def load(plan_dir, version=None):
    """plan/data/ を window.PLAN と同じ形の dict にする(読めない JSON は飛ばす = check が止める)"""
    dd = data_dir(plan_dir)
    plan = json.loads(read_text(os.path.join(dd, "main.json")))
    sp = os.path.join(dd, "summary.md")
    if os.path.isfile(sp):
        plan["summary"] = read_text(sp).strip()
    got = {k: sorted((it for _n, it, _e in items(plan_dir, k) if it), key=sort_key(k)) for k in KINDS}
    ut = plan.setdefault("userTasks", {})
    for lst in USER_LISTS:
        ut[lst] = [strip_internal(it) for it in got["user"] if it.get("list") == lst]
    ut["provisional"] = [strip_internal(it) for it in got["provisional"]]
    for k in ("recent", "tasks", "history"):
        plan[k] = [strip_internal(it) for it in got[k]]
    if version is not False:
        v = version or main_version()
        plan["versions"] = [[n, v] if str(n).startswith(WHOLE) else [n, x] for n, x in plan.get("versions", [])]
    return plan


KEY_ORDER_PLAN = ("updated", "artifactUrl", "summary", "versions", "recent", "lines", "phases", "tasks", "totals",
                  "critical", "schedule", "gates", "numbers", "conflicts", "userTasks", "history")


def render(plan):
    keys = [k for k in KEY_ORDER_PLAN if k in plan] + [k for k in plan if k not in KEY_ORDER_PLAN]
    body = ",\n".join("  %s: %s" % (k, json.dumps(plan[k], ensure_ascii=False, indent=None if k in ("summary", "updated", "artifactUrl") else 1).replace("\n", "\n  "))
                      for k in keys)
    return HEADER + "window.PLAN = {\n" + body + "\n};\n"


def build(plan_dir, version=None):
    """data.js を作る。check で読めない JSON があれば作らない(前の data.js を残す)。-> (書いたか, 問題)"""
    probs = [p for p in check(plan_dir, refs=False) if p[2].startswith("読めない")]
    if probs:
        return False, probs
    text = render(load(plan_dir, version))
    path = os.path.join(plan_dir, "data.js")
    if os.path.isfile(path) and read_text(path) == text:
        return False, []
    write_atomic(path, text)
    return True, []


# ---------------------------------------------------------------- 検査

def check(plan_dir, refs=True):
    """-> [(ファイル, 行, 説明)]"""
    dd = data_dir(plan_dir)
    bad = []
    try:
        json.loads(read_text(os.path.join(dd, "main.json")))
    except (OSError, ValueError) as e:
        bad.append(("plan/data/main.json", _line(e), "読めない: %s" % e))
    ids = {}
    for kind in KINDS:
        seen, lower = {}, {}
        for n, it, err in items(plan_dir, kind):
            rel = "plan/data/%s/%s" % (kind, n)
            if err:
                bad.append((rel, _line_msg(err), "読めない(JSON): " + err))
                continue
            if not isinstance(it, dict):
                bad.append((rel, 1, "読めない: 1 件の {...} ではない"))
                continue
            miss = [k for k in REQUIRED[kind] if k not in it]
            if miss:
                bad.append((rel, 1, "欄が無い: " + "・".join(miss)))
            if n != file_name(kind, it):
                bad.append((rel, 1, "ファイル名が id と合わない(%s にする)" % file_name(kind, it)))
            if n.lower() in lower:
                bad.append((rel, 1, "大文字小文字だけ違うファイルがある: " + lower[n.lower()]))
            lower[n.lower()] = n
            key = (it.get("sec", ""), it.get("id")) if kind in ("provisional", "confirmed") else it.get("id")
            if key in seen:
                bad.append((rel, 1, "id が重なる: %s(%s)" % (it.get("id"), seen[key])))
            seen[key] = n
            if kind == "user" and it.get("list") not in USER_LISTS:
                bad.append((rel, 1, "list は %s のどれか" % "・".join(USER_LISTS)))
            if kind == "provisional":
                if it.get("weight") not in WEIGHTS:
                    bad.append((rel, 1, "weight は 軽 か 重"))
                if it.get("weight") == "重" and not it.get("why"):
                    bad.append((rel, 1, "重い物は why(%s)を 1 つ以上" % "・".join(WHY)))
                if [w for w in it.get("why", []) if w not in WHY]:
                    bad.append((rel, 1, "why は %s から" % "・".join(WHY)))
                if not _date_ok(it.get("added")):
                    bad.append((rel, 1, "added(入れた日 YYYY-MM-DD)が無い"))
            if kind in ("tasks", "history", "user"):
                ids[it.get("id")] = rel
    if refs:
        for kind in ("tasks",):
            for n, it, err in items(plan_dir, kind):
                for ref in (it or {}).get("pre", []) if not err else []:
                    if ref not in ids:
                        bad.append(("plan/data/%s/%s" % (kind, n), 1, "pre の %s が tasks・history・user のどれにも無い" % ref))
    return bad


def _date_ok(s):
    try:
        datetime.date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def _line(e):
    return getattr(e, "lineno", 1) or 1


def _line_msg(msg):
    m = re.search(r"line (\d+)", msg)
    return int(m.group(1)) if m else 1


# ---------------------------------------------------------------- 足す・仮決めの見回り

def new(plan_dir, kind, ident, fields):
    if kind not in KINDS[:5]:
        raise SystemExit("種類は tasks・recent・history・user・provisional")
    item = {"id": ident}
    item.update(fields)
    if kind == "provisional":
        item.setdefault("added", datetime.date.today().isoformat())
        item.setdefault("date", item["added"][5:])
        item.setdefault("weight", "重")   # 迷う物は重
        item.setdefault("why", [] if item["weight"] == "軽" else ["形"])
        item.setdefault("what", "")
        item.setdefault("impact", "")
    if kind == "user":
        item.setdefault("list", "ordered")
    orders = [it.get("order", 0) for _n, it, _e in items(plan_dir, kind) if it]
    # provisional は新しい物が上 = 小さい order。ほかは末尾
    item["order"] = (min(orders, default=0) - 10) if kind == "provisional" else (max(orders, default=0) + 10)
    path = os.path.join(data_dir(plan_dir), kind, file_name(kind, item))
    if os.path.exists(path):
        raise SystemExit("もうある: %s" % path)
    write_atomic(path, dumps(item))
    build(plan_dir)
    return path


def sweep(plan_dir, today=None, dry_run=False):
    """軽い仮決めで added から 7 日たち hold の無い物を confirmed へ移す。仮決めの一覧を作り直す。-> 移した件数"""
    today = today or datetime.date.today()
    moved = 0
    for n, it, err in items(plan_dir, "provisional"):
        if err or it.get("weight") != "軽" or it.get("hold") or not _date_ok(it.get("added")):
            continue
        if datetime.date.fromisoformat(it["added"]) + datetime.timedelta(days=LIGHT_DAYS) > today:
            continue
        moved += 1
        if dry_run:
            continue
        it["confirmed"] = today.isoformat()
        src = os.path.join(data_dir(plan_dir), "provisional", n)
        write_atomic(os.path.join(data_dir(plan_dir), "confirmed", file_name("confirmed", it)), dumps(it))
        os.remove(src)
    if not dry_run:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import notes_tool   # 文の [送る](説明)・#pack が Obsidian のリンク・タグにならないように
        write_atomic(os.path.join(plan_dir, PROV_LIST), notes_tool.unlink_prose(prov_list(plan_dir, today)))
        build(plan_dir)
    return moved


def heavy_rank(it):
    """重い順: 当たる理由の数が多い → 古い"""
    return (-len(it.get("why", [])), it.get("added", ""), str(it.get("sec")))


def prov_list(plan_dir, today):
    monday = today - datetime.timedelta(days=today.weekday())
    pend = [it for _n, it, e in items(plan_dir, "provisional") if it]
    heavy = sorted((it for it in pend if it.get("weight") == "重"), key=heavy_rank)
    light = sorted((it for it in pend if it.get("weight") == "軽"), key=lambda it: it.get("added", ""))
    done = sorted((it for _n, it, e in items(plan_dir, "confirmed") if it and it.get("confirmed", "") >= monday.isoformat()),
                  key=lambda it: (it.get("confirmed"), str(it.get("sec"))))
    out = ["---", "種類: 索引", "状態: 有効", "---", "", "# 仮決めの一覧(重い物と、今週自動で確定した軽い物)", "",
           "更新(%s): 自動で作る(dev/plan_data.py sweep。plan_artifact も流す)・手で直さない。正は plan/data/provisional/ と [`plan/decisions.md`](decisions.md) の 3" % today.isoformat(), "",
           "- 重い = 形を大きく変える・消すと戻せない・本物のデータを動かす・ユーザーの言い方から変えた(迷う物も重い)。**1 問ずつユーザーに聞く**(重い順 = 当たる理由の数 → 古い順)",
           "- 軽い = 戻せる・影響が小さい・内部の作り。入れて %d 日たって問題が出なければ自動で確定(問題が出たら欄 hold: true を足して止める)" % LIGHT_DAYS, "",
           "## まだの重い物(%d 件)" % len(heavy), ""]
    out += ["%d. **%s %s**(%s・%s)%s — %s" % (i, it.get("sec"), it.get("id"), it.get("date"), "・".join(it.get("why", [])),
                                              "", _one(it.get("what"))) for i, it in enumerate(heavy, 1)] or ["(無し)"]
    out += ["", "## 今週(%s〜)自動で確定した軽い物(%d 件)" % (monday.isoformat()[5:], len(done)), ""]
    out += ["- %s %s(%s に確定)— %s" % (it.get("sec"), it.get("id"), it.get("confirmed", "")[5:], _one(it.get("what")))
            for it in done] or ["(無し)"]
    out += ["", "## 確定を待つ軽い物(%d 件。古い順)" % len(light), ""]
    out += ["- %s %s(%s に入れた → %s に確定%s)" % (it.get("sec"), it.get("id"), it.get("added", "")[5:],
                                              _plus(it.get("added"), LIGHT_DAYS)[5:], "・止めている" if it.get("hold") else "")
            for it in light] or ["(無し)"]
    return "\n".join(out) + "\n"


def _one(text, limit=160):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _plus(day, n):
    try:
        return (datetime.date.fromisoformat(day) + datetime.timedelta(days=n)).isoformat()
    except (TypeError, ValueError):
        return "????-??-??"


# ---------------------------------------------------------------- 1 回きりの分割

RULE_START = "2026-10-18"   # 軽い物の 7 日はこの日(重さ分けを決めた日)より前に戻らない = 前からの軽い物も 1 週は見られる


def split(plan_dir, plan=None, weights=None):
    """手書きの data.js を plan/data/ に分ける。weights = {provisional の並びの番号: {"w":…, "why":[…]}}(無ければ全部 重)"""
    if has_split(plan_dir):
        raise SystemExit("もう分けてある: %s" % data_dir(plan_dir))
    if plan is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from plan_artifact import parse_plan_js
        plan = parse_plan_js(read_text(os.path.join(plan_dir, "data.js")))
    dd = data_dir(plan_dir)
    year = (plan.get("updated") or datetime.date.today().isoformat())[:4]

    def put(kind, it, order):
        it = dict(it, order=order)
        write_atomic(os.path.join(dd, kind, file_name(kind, it)), dumps(it))

    for kind in ("recent", "tasks", "history"):
        for i, it in enumerate(plan.pop(kind, []), 1):
            put(kind, it, i * 10)
    ut = plan.setdefault("userTasks", {})
    for lst in USER_LISTS:
        for i, it in enumerate(ut.pop(lst, []), 1):
            put("user", dict(it, list=lst), i * 10)
    for i, it in enumerate(ut.pop("provisional", [])):
        w = (weights or {}).get(i, {})
        weight = w.get("w", "重")
        it = dict(it, weight=weight, why=list(w.get("why") or ([] if weight == "軽" else ["形"])),
                  added=max(_added(it.get("date", ""), year), RULE_START))
        put("provisional", it, (i + 1) * 10)
    write_atomic(os.path.join(dd, "summary.md"), plan.pop("summary", "") + "\n")
    write_atomic(os.path.join(dd, "main.json"), json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    return dd


def _added(date, year):
    """「10-18」「10-16 夜」→ 2026-10-18"""
    m = re.match(r"(\d{1,2})-(\d{1,2})", str(date))
    return "%s-%02d-%02d" % (year, int(m.group(1)), int(m.group(2))) if m else "%s-01-01" % year


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=None, help="plan フォルダ(既定: 保管庫の plan)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build")
    sub.add_parser("check")
    p = sub.add_parser("new")
    p.add_argument("kind")
    p.add_argument("id")
    p.add_argument("fields", nargs="*", help="欄=値(値が [ { で始まれば JSON)")
    p = sub.add_parser("sweep")
    p.add_argument("--today")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("split")
    p.add_argument("--weights", help="仕分けの JSON([{n, w, why}])")
    a = ap.parse_args(argv)
    plan_dir = os.path.abspath(a.plan) if a.plan else plan_dir_default()
    if a.cmd != "split" and not has_split(plan_dir):
        print("plan/data/main.json が無い(まだ分けていない): %s" % plan_dir)
        return 1
    if a.cmd == "build":
        wrote, probs = build(plan_dir)
        for f, ln, msg in probs:
            print("%s:%d %s" % (f, ln, msg))
        print("data.js を作った" if wrote else ("作らなかった(読めない JSON がある)" if probs else "data.js は今のまま"))
        return 1 if probs else 0
    if a.cmd == "check":
        bad = check(plan_dir)
        for f, ln, msg in bad:
            print("%s:%d %s" % (f, ln, msg))
        print("計画のデータの問題 %d 件" % len(bad))
        return 1 if bad else 0
    if a.cmd == "new":
        fields = {}
        for kv in a.fields:
            k, _, v = kv.partition("=")
            fields[k] = json.loads(v) if v[:1] in "[{" else v
        print(new(plan_dir, a.kind, a.id, fields))
        return 0
    if a.cmd == "sweep":
        today = datetime.date.fromisoformat(a.today) if a.today else None
        print("自動で確定した軽い仮決め %d 件" % sweep(plan_dir, today, a.dry_run))
        return 0
    if a.cmd == "split":
        weights = None
        if a.weights:
            with open(a.weights, encoding="utf-8") as f:
                weights = {int(w["n"]): w for w in json.load(f)}
        print("分けた: %s" % split(plan_dir, weights=weights))
        wrote, _ = build(plan_dir)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
