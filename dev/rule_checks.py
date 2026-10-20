#!/usr/bin/env python3
"""規則(書き方・置き場所・ファイルの形)の見張り。test-trim の規則の担当。

    python dev/rule_checks.py              # 全部の規則を流して問題を出す(lint.py の 11 番 `rule` が同じ物を呼ぶ)
    python dev/rule_checks.py --list       # 規則の一覧(番号・何を止めるか・どのテストから移したか)

規則 1 つ = 関数 1 つ。関数は「問題の文字列の一覧」を返す(0 件で合格)。頭の @rule(番号, 何を止めるか, 移した元のテスト)が一覧になる。
中身を取り出して見る部分(`*_problems(…)`)は文字列・辞書を受け取る関数にして、`dev/tests/test_rule_checks.py` が破った見本で止まることを確かめる。
この PC のソースを import して突き合わせる規則(定数が食い違わない・別プロセスで読んだときネイティブ部品が入らない)は `dev/rule_imports.py`
(子プロセスで流す。lint がまとめて呼ぶ)。画面(HTML・JS・CSS)の見た目の規則は `dev/ui_audit.py` の A-xx。
"""
import ast
import fnmatch
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "src")
SKIP_DIRS = {".git", "node_modules", "dist", "bin", "obj", "__pycache__", "build", "packs", "work", "exports", "logs", ".artifact-build", "fixtures"}

RULES = []   # [(番号, 何を止めるか, 移した元のテスト, 関数)]


def rule(rid, title, moved_from):
    def deco(fn):
        RULES.append((rid, title, moved_from, fn))
        return fn
    return deco


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def rel(path, repo=REPO):
    return os.path.relpath(path, repo).replace("\\", "/")


def repo_files(repo, pattern):
    """リポジトリの中の pattern(fnmatch の形)に合うファイル(作られる物の置き場所は除く)"""
    out = []
    for d, dirs, names in os.walk(repo):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        out += [os.path.join(d, n) for n in fnmatch.filter(names, pattern)]
    return sorted(out)


def src_py_files(repo, skip=("tests", "__pycache__", ".runtime", "node_modules")):
    out = []
    for d, dirs, names in os.walk(os.path.join(repo, "src")):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith(".")]
        out += [os.path.join(d, n) for n in names if n.endswith(".py")]
    return sorted(out)


# ---------------------------------------------------------------- ファイルの形(ASCII・CRLF)

def non_ascii_lines(data):
    """bytes の中の ASCII 以外を含む行の番号"""
    return [i for i, line in enumerate(data.split(b"\n"), 1) if any(c > 0x7F for c in line)]


def bat_problems(name, data):
    """.bat は ASCII だけで CRLF(cmd.exe が UTF-8 や LF を読み違える)"""
    out = []
    bad = non_ascii_lines(data)
    if bad:
        out.append("%s に ASCII 以外の文字(行 %s)" % (name, ",".join(map(str, bad[:5]))))
    if data.count(b"\n") != data.count(b"\r\n"):
        out.append("%s に CRLF でない改行" % name)
    return out


def requirements_problems(name, data):
    """requirements は ASCII だけ。cp932 でも読める(日本語の Windows の pip が読むのと同じ)"""
    out = []
    bad = non_ascii_lines(data)
    if bad:
        out.append("%s に ASCII 以外の文字(行 %s)" % (name, ",".join(map(str, bad[:5]))))
    try:
        data.decode("cp932")
    except UnicodeDecodeError:
        out.append("%s が cp932 で読めない" % name)
    return out


@rule("R-01", ".bat が ASCII だけで CRLF", "dev/tests/test_setup_ascii.py test_bat_ascii_crlf")
def rule_bat_ascii_crlf(repo=REPO):
    bats = repo_files(repo, "*.bat")
    out = []
    if not any(p.replace("\\", "/").endswith("setup/install.bat") for p in bats):
        out.append("setup/install.bat が見つからない")
    for p in bats:
        out += bat_problems(rel(p, repo), read_bytes(p))
    return out


@rule("R-02", "setup/requirements*.txt が ASCII だけで cp932 でも読める", "dev/tests/test_setup_ascii.py test_requirements_ascii")
def rule_requirements_ascii(repo=REPO):
    import glob
    reqs = glob.glob(os.path.join(repo, "setup", "requirements*.txt"))
    out = [] if reqs else ["setup/requirements*.txt が見つからない"]
    for p in reqs:
        out += requirements_problems(rel(p, repo), read_bytes(p))
    return out


def push_bat_problems(s):
    """push.bat の処理の順(削除 → add → 検査)・検査で止まったら add を取り消す・保管庫は 2 か所から送る"""
    out = []
    try:
        a, b, c = s.index("push_helper.py removals"), s.index("git add -A"), s.index("push_helper.py check")
    except ValueError as e:
        return ["push.bat に処理が無い: %s" % e]
    if not a < b < c:
        out.append("処理の順が 削除 → git add → 検査 でない")
    if "git reset -q" not in s[c:c + 400]:
        out.append("検査で止まったときの git reset -q が検査の後に無い(コミットしてしまう)")
    if s.count("call :notes") < 2:
        out.append("保管庫を送る call :notes が 2 か所に無い(送ったあと・送る物が無いとき)")
    if "push_helper.py notes" not in s:
        out.append("push_helper.py notes が無い")
    return out


@rule("R-03", "push.bat の処理の順(削除 → add → 検査 → 保管庫)", "dev/tests/test_push_helper.py test_order_in_push_bat")
def rule_push_bat_order(repo=REPO):
    path = os.path.join(repo, "push.bat")
    if not os.path.isfile(path):
        return ["push.bat が無い"]
    return push_bat_problems(read_bytes(path).decode("ascii", "replace"))


# ---------------------------------------------------------------- e2e の一覧・単体テストの層の名前

def suite_problems(repo, suite, not_in_suite, found):
    """e2e の一覧(SUITE・NOT_IN_SUITE)の中身が実在し、リポジトリの e2e は一覧か除外のどちらかに必ず入る"""
    out = []
    for script in [s for _g, s, _a, _w in suite] + sorted(not_in_suite):
        if not os.path.isfile(os.path.join(repo, script)):
            out.append("run_e2e.py の一覧にあるが実在しない: %s" % script)
    listed = {s for _g, s, _a, _w in suite} | set(not_in_suite)
    for s in sorted(set(found) - listed):
        out.append("e2e を足したら dev/run_e2e.py の SUITE か NOT_IN_SUITE に入れる: %s" % s)
    return out


@rule("R-04", "e2e の一覧が実在する物と一致", "dev/tests/test_run_e2e.py test_every_listed_script_exists・test_every_repo_script_is_listed_or_excluded")
def rule_e2e_suite_listed(repo=REPO):
    import glob
    sys.path.insert(0, HERE)
    try:
        import run_e2e
    finally:
        sys.path.remove(HERE)
    found = set()
    for top in ("src", "dev", "chrome-ext", "friend-apps"):
        for p in glob.glob(os.path.join(repo, top, "**", "e2e_*.py"), recursive=True):
            r = rel(p, repo)
            if not r.endswith("/e2e_edit_common.py"):
                found.add(r)
    return suite_problems(repo, run_e2e.SUITE, run_e2e.NOT_IN_SUITE, found)


@rule("R-05", "単体テストの層の名前が src のフォルダと一致", "dev/tests/test_run_unit.py test_layer_names_are_src_folders")
def rule_run_unit_layers(repo=REPO):
    sys.path.insert(0, HERE)
    try:
        import run_unit
    finally:
        sys.path.remove(HERE)
    return ["run_unit.LAYERS の %s が src/ にフォルダとして無い" % layer for layer in run_unit.LAYERS if not os.path.isdir(os.path.join(repo, "src", layer))]


# ---------------------------------------------------------------- 配るデータの形(members.json・名簿)

HEX7 = re.compile(r"^#[0-9A-Fa-f]{6}$")
HEX_ANY = re.compile(r"^#?[0-9A-Fa-f]{6}$")
LABEL_MAX = 12
BRANCHES = ("JP", "DEV_IS", "EN", "ID", "GRAD")


def members_problems(d):
    """friend-apps/holo-colors/members.json の形(version 2。C# の同梱のデータの検査と ytt.colors の読めるかを 1 つに)"""
    out = []
    if d.get("version") != 2:
        out.append("version が 2 でない: %r" % d.get("version"))
    if len(str(d.get("updated") or "")) != 10:
        out.append("updated(YYYY-MM-DD)が無い")
    groups = d.get("groups") or []
    if not groups:
        out.append("グループが無い")
    known = {s.get("id") for s in d.get("sources") or []}
    ids, places, total = set(), set(), 0
    for g in groups:
        if not str(g.get("name") or "").strip():
            out.append("グループの名前が空: %s" % g.get("id"))
        if not g.get("members"):
            out.append("空のグループ: %s" % g.get("name"))
        for m in g.get("members") or []:
            total += 1
            name = m.get("name")
            if not str(m.get("en") or "").strip():
                out.append("ローマ字・英語名(en)が無い: %s" % name)
            where = "%s/%s" % (g.get("branch"), name)
            if where in places:
                out.append("同じ人が同じ所に 2 回: %s" % where)
            places.add(where)
            if not HEX7.match(str(m.get("hex") or "")):
                out.append("hex の形が違う: %s" % name)
            mid = m.get("id")
            if not mid or mid in ids:
                out.append("メンバーの id が無いか重なっている: %s / %s" % (name, mid))
            ids.add(mid)
            cs = m.get("colors") or []
            if not cs:
                out.append("colors が無い: %s" % name)
                continue
            if str(cs[0].get("hex") or "").upper() != str(m.get("hex") or "").upper():
                out.append("colors の先頭と hex が違う: %s" % name)
            for c in cs:
                if not HEX_ANY.match(str(c.get("hex") or "")):
                    out.append("色のカラーコードの形: %s" % name)
                if len(c.get("label") or "") > LABEL_MAX:
                    out.append("ラベルが %d 文字を超える: %s / %s" % (LABEL_MAX, name, c.get("label")))
                if c.get("confidence") not in ("high", "medium", "low"):
                    out.append("確かさ(confidence)が無い: %s" % name)
                if not set(c.get("src") or []) <= known:
                    out.append("知らない出典: %s %s" % (name, c.get("src")))
            if not set(m.get("src") or []) <= known:
                out.append("知らない出典: %s" % name)
            if "subtitle" in m and not HEX_ANY.match(str(m["subtitle"])):
                out.append("subtitle の形: %s" % name)
    for b in BRANCHES:
        if not any(g.get("branch") == b for g in groups):
            out.append("このグループが無い: %s" % b)
    if groups and total <= 50:
        out.append("メンバーが 50 人以下(読めていない?): %d" % total)
    return out


@rule("R-06", "同梱の members.json が version 2 の決まった形(id の一意・先頭の色が hex と同じ・ラベル 12 字まで・出典が実在)",
      "friend-apps/holo-colors/tests/CoreTests.cs BundledMembers・src/ytt/tests/test_ytt_core.py test_repo_members_json_is_readable")
def rule_members_json(repo=REPO):
    path = os.path.join(repo, "friend-apps", "holo-colors", "members.json")
    if not os.path.isfile(path):
        return ["friend-apps/holo-colors/members.json が無い"]
    with open(path, encoding="utf-8") as f:
        return members_problems(json.load(f))


def roster_problems(d, group_region, regions):
    """src/pipeline/transcribe の名簿(roster.json): 人は組に入っている・呼び名は 1 人だけ・地域は組から決めた物と合う"""
    out = []
    people = {n for g in d.get("groups", []) if g.get("id") != "units" for n in g.get("names", [])}
    seen = {}
    in_groups = {}
    for g in d.get("groups", []):
        for n in g.get("names", []):
            in_groups.setdefault(n, []).append(g.get("id"))
    for m in d.get("members", []):
        name = m.get("name")
        if name not in people:
            out.append("名簿の人でない: %s" % name)
        if not m.get("aliases"):
            out.append("呼び名が無い: %s" % name)
        if not set(m.get("common") or []) <= set(m.get("aliases") or []):
            out.append("普通の言葉と重なる印は呼び名から選ぶ: %s" % name)
        for a in m.get("aliases") or []:
            if a in seen:
                out.append("同じ呼び名が 2 人に: %s(%s・%s)" % (a, seen[a], name))
            seen[a] = name
        for x in m.get("misrecognitions") or []:
            if not (x.get("wrong") and x.get("right") and x["wrong"] != x["right"]):
                out.append("聞き違いの組が空か同じ: %s" % name)
        want = {group_region[g] for g in in_groups.get(name, []) if g in group_region}
        if len(want) > 1:
            out.append("組から決まる地域が 2 つ: %s %s" % (name, sorted(want)))
        elif m.get("region") != (next(iter(want)) if want else None):
            out.append("region が組と合わない: %s(%r)" % (name, m.get("region")))
        if m.get("region") not in (None,) + tuple(regions):
            out.append("知らない region: %s %r" % (name, m.get("region")))
    if len(d.get("members", [])) < 50:
        out.append("名簿の人数が 50 人未満")
    if "ホロライブ" in {m.get("name") for m in d.get("members", [])}:
        out.append("グループ名(ホロライブ)が人として入っている")
    return out


# ---------------------------------------------------------------- ソースの書き方

def write_doc_problems(files):
    """文書を書く write_doc( の呼び出しは store.py(の commit・組み立て直し)の中だけ。files: {src からの相対パス: 本文}"""
    pat = re.compile(r"\bwrite_doc\(")
    bad = set()
    for name, text in files.items():
        for ln in text.splitlines():
            if pat.search(ln) and not ln.lstrip().startswith(("#", "def write_doc")):
                bad.add(name)
    return ["write_doc を store.commit の外で呼んでいる: %s" % n for n in sorted(bad) if n != "human/proof/store.py"]


@rule("R-07", "文書を書く write_doc は store.py の中(commit)からだけ", "src/human/proof/tests/test_commit.py test_every_doc_write_in_src_uses_commit")
def rule_write_doc_only_in_store(repo=REPO):
    files = {os.path.relpath(p, os.path.join(repo, "src")).replace("\\", "/"): read_text(p) for p in src_py_files(repo)}
    return write_doc_problems(files)


def ytdlp_template_problems(name, text):
    """yt-dlp の -o は必ず yturl.ytdlp_out を通す(os.path.join を直に渡さない)"""
    return ["%s: yt-dlp の -o に os.path.join を直に渡している(yturl.ytdlp_out を通す)" % name] if '"-o", os.path.join(' in text else []


@rule("R-08", "解析と書き出しの yt-dlp の -o は yturl.ytdlp_out を通す", "src/studio/tests/test_robustness.py test_all_ytdlp_calls_use_the_escaped_template")
def rule_ytdlp_out_template(repo=REPO):
    out = []
    for fn in ("src/pipeline/analyze/analyze.py", "src/pipeline/export/exporter.py"):
        path = os.path.join(repo, *fn.split("/"))
        out += ytdlp_template_problems(fn, read_text(path)) if os.path.isfile(path) else ["%s が無い(規則の対象を直す)" % fn]
    return out


def tool_apps_problems(text):
    """cut2resolve/serve.py は TOOL_APPS を自分で書き直さず ytt.runtime の物をそのまま使う"""
    tree = ast.parse(text)
    found = [ast.unparse(n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "TOOL_APPS" for t in n.targets)]
    return [] if found == ["_runtime.TOOL_APPS"] else ["cut2resolve/serve.py の TOOL_APPS が ytt.runtime そのままでない: %s" % found]


@rule("R-09", "cut2resolve の TOOL_APPS は ytt.runtime の物(写しを持たない)", "src/ytt/tests/test_ytt_core.py test_cut2resolve_uses_ytt_core")
def rule_cut2resolve_tool_apps(repo=REPO):
    path = os.path.join(repo, "src", "cut2resolve", "serve.py")
    return tool_apps_problems(read_text(path)) if os.path.isfile(path) else []


def keys_adopt_problems(text):
    """flow/keys.py の本文に束の adopt の語を書かない(成果物の鍵の材料にしない = 欄を足しても今の鍵は「違う」にならない)"""
    return ["flow/keys.py に束の adopt の語「%s」がある(鍵の材料にしない)" % w for w in ("adopt", "afterStream", "perHour", "waitMin") if w in text.replace("adoptedBy", "")]


@rule("R-10", "成果物の鍵(flow/keys.py)に束の adopt 節を使わない", "src/flow/tests/test_keys.py test_no_bundle_adopt_in_keys")
def rule_keys_ignore_adopt(repo=REPO):
    return keys_adopt_problems(read_text(os.path.join(repo, "src", "flow", "keys.py")))


ED_PARTS = re.compile(r"^(ed_\w+|serve)$")


def editor_import_problems(name, text):
    """モジュールの先頭(関数の外)で編集の部品(ed_* ・serve)を読んでいない = import の向き(持ち主は編集の部品を読まない)"""
    out = []
    tree = ast.parse(text)

    def walk(stmts):
        for n in stmts:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(n, ast.Import):
                for a in n.names:
                    if ED_PARTS.match((a.asname or a.name).split(".")[0]):
                        out.append("%s:%d import %s" % (name, n.lineno, a.name))
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if (n.level == 0 and ED_PARTS.match((n.module or "").split(".")[0])) or ED_PARTS.match(a.asname or a.name):
                        out.append("%s:%d from %s import %s" % (name, n.lineno, n.module, a.name))
            for field in ("body", "orelse", "finalbody"):
                walk(getattr(n, field, None) or [])
            for h in getattr(n, "handlers", None) or []:
                walk(h.body)
    walk(tree.body)
    return out


OWNERS_NO_EDITOR = ("src/human/proof/alt.py", "src/human/proof/retime.py", "src/eval/drill/drill.py", "src/eval/drill/evalbatch.py")


@rule("R-11", "持ち主(alt・retime・drill・evalbatch)は編集の部品(ed_*・serve)を先頭で読まない", "src/editor/tests/test_names.py test_owners_do_not_read_editor_parts(2 本)")
def rule_owners_do_not_read_editor_parts(repo=REPO):
    out = []
    for fn in OWNERS_NO_EDITOR:
        path = os.path.join(repo, *fn.split("/"))
        out += editor_import_problems(fn, read_text(path)) if os.path.isfile(path) else ["%s が無い(規則の対象を直す)" % fn]
    return out


# ---------------------------------------------------------------- 空行の続きすぎ(2 行までは PEP 8 のとおりよい)

def blank_run_problems(name, text, limit=3):
    """空白だけの行が limit 行以上続く所"""
    out, run = [], 0
    for i, s in enumerate(text.splitlines() + ["x"], 1):
        if not s.strip():
            run += 1
            continue
        if run >= limit:
            out.append("%s:%d から空行が %d 行続く(2 行まで)" % (name, i - run, run))
        run = 0
    return out


@rule("R-12", "プログラムのファイル(dev/loc.py が数える物)に空行が 3 行以上続かない", "(新しく足した規則・10-19)")
def rule_blank_runs(repo=REPO):
    sys.path.insert(0, HERE)
    try:
        import loc
    finally:
        sys.path.remove(HERE)
    out = []
    for path in repo_files(repo, "*"):
        name = rel(path, repo)
        if loc.classify(name):
            out += blank_run_problems(name, read_text(path))
    return out


# ---------------------------------------------------------------- 流す

def run(repo=REPO, only=None):
    """静的な規則を全部流す -> [(番号, 問題の文字列)]。only = 番号の集合"""
    out = []
    for rid, _title, _moved, fn in RULES:
        if only and rid not in only:
            continue
        try:
            problems = fn(repo)
        except Exception as e:   # 規則の側の不具合も止める(黙って通さない)
            problems = ["規則が動かない: %s: %s" % (type(e).__name__, e)]
        out += [(rid, p) for p in problems]
    return out


def run_all(repo=REPO):
    """静的な規則 + 子プロセスで流す規則(dev/rule_imports.py)の全部 -> [(番号, 問題の文字列)]"""
    sys.path.insert(0, HERE)
    try:
        import rule_imports
    finally:
        sys.path.remove(HERE)
    return run(repo) + rule_imports.run(repo)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--list" in argv:
        for rid, title, moved, _fn in RULES:
            print("%s  %s  <- %s" % (rid, title, moved))
        sys.path.insert(0, HERE)
        import rule_imports
        rule_imports.main(["--list"])
        return 0
    found = run_all()
    for rid, p in found:
        print("%s  %s" % (rid, p))
    print("合計 %d 件(0 で合格)" % len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
