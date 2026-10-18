#!/usr/bin/env python3
"""Claude Code の PreToolUse のフック: 事故のもとになる操作を機械が断る(2026-10-18)。標準ライブラリだけ・速く。

    py -3.12 dev/guard_hook.py                    # フックとして(標準入力に Claude Code の JSON。断るときは標準出力に deny の JSON)
    py -3.12 dev/guard_hook.py --check "<命令>"   # 試し: 命令を 1 つ判定して結果を出す(--tool PowerShell・--cwd で場所)
    py -3.12 dev/guard_hook.py --install [settings.json]   # .claude/settings.json にこのフックを足す(あれば何もしない)

断る物(確かな形だけ。断る理由と代わりのやり方を 1 行で返す):
  1. 名前でまとめてプロセスを止める(taskkill /IM・/FI IMAGENAME・Stop-Process -Name・Get-Process 名前 | Stop-Process・pkill・killall)
  2. sed -i(CRLF を壊す)
  3. git add -A / --all / . / :/ と git commit -a(ほかのセッションの差分を巻き込む)
  4. main の作業フォルダ(.git がフォルダで dev/land.py がある所)での git commit。抜け道は YTT_MAIN_COMMIT=1 だけ
  5. 生成物(保管庫の plan/data.js・plan/仮決めの一覧.md・リポジトリの codemap/*.md)への直の書き込み(Edit・Write・リダイレクト・Set-Content など)
足す物(断らない): unittest・pytest を YTT_DATA_DIR なしで直に流すときは、作業データの切り離しを忘れていると知らせる。
例外を出したら必ず通す(フックが壊れると全部のセッションの操作が止まるため)。設定の command は「|| true」付き。
"""
import json
import os
import re
import sys

MAIN_COMMIT_ENV = "YTT_MAIN_COMMIT"
PREFIX = "[守り] "
MSG = {
    "kill": "名前でまとめてプロセスを止めない(ほかのセッションやユーザーの入口まで止まる)。自分が起こした PID だけを止める"
            "(taskkill /PID <番号> /T /F・Stop-Process -Id <番号>)。",
    "sed": "sed -i は改行(CRLF)を壊す。Edit の道具か、Python で newline='' を付けて書き換える。",
    "add": "git add -A / . / commit -a はほかのセッションの差分を巻き込む。自分が直したファイルを名前で git add し、"
           "git diff --cached --stat で確かめてからコミットする。",
    "main": "main の作業フォルダでは直にコミットしない。worktree でコミットして py -3.12 dev/land.py で入れる"
            "(まとめ役が main で直すときだけ、頭に YTT_MAIN_COMMIT=1 を付ける。PowerShell は $env:YTT_MAIN_COMMIT=1; )。",
    "data.js": "plan/data.js は dev/plan_data.py build が作る生成物(直しても次の build で消える)。plan/data/ の JSON を直して build する。",
    "prov": "plan/仮決めの一覧.md は dev/plan_data.py sweep が作る生成物。plan/data/provisional/ を直して sweep する。",
    "codemap": "codemap/ は dev/code_map.py が作る生成物。コードを直してから py -3.12 dev/code_map.py で作り直す。",
}
WARN_DATA_DIR = ("[守り] テストを直に流すときは作業データを切り離す(頭に YTT_DATA_DIR=inplace、"
                 "PowerShell は $env:YTT_DATA_DIR='inplace'; )。py -3.12 dev/run_unit.py なら道具が付ける。")

SEPS = (";", "&&", "||", "|", "&", "\n")
REDIRECTS = (">", ">>", "1>", "2>", "1>>", "2>>", "*>", "*>>", "&>")
KILL_STOP = {"stop-process", "spps"}
GET_PROC = {"get-process", "gps"}
WRITE_CMDS = {"set-content", "add-content", "out-file", "tee", "tee-object", "sc", "ac"}
MOVE_CMDS = {"cp", "mv", "copy", "move", "copy-item", "move-item", "cpi", "mi", "install"}
CD_CMDS = {"cd", "set-location", "sl", "chdir", "pushd", "push-location"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


# ---- 命令を語に分ける(引用符・区切り・ヒアドキュメント・PowerShell の here-string)

class Tok(str):
    """語。quoted = 引用符の中身を含む(印や命令の選択肢としては見ない)。"""
    quoted = False


def tok(text, quoted=False):
    t = Tok(text)
    t.quoted = quoted
    return t


def tokenize(cmd):
    """命令の文字列を、区切り(SEPS)と語の並びにする。ヒアドキュメントと here-string の中身は 1 つの引用された語。"""
    out, buf, quoted, i, n = [], [], False, 0, len(cmd)
    heredocs = []

    def flush():
        nonlocal buf, quoted
        if buf:
            out.append(tok("".join(buf), quoted))
        buf, quoted = [], False

    while i < n:
        c = cmd[i]
        if c in "@" and cmd[i + 1:i + 2] in ("'", '"') and cmd[i + 2:i + 3] in ("\n", "\r") and not buf:
            q = cmd[i + 1]
            end = cmd.find("\n" + q + "@", i + 2)
            end = n if end < 0 else end
            out.append(tok(cmd[i + 2:end], True))
            i = end + 3
            continue
        if c in ("'", '"'):
            end = i + 1
            while end < n and cmd[end] != c:
                end += 2 if (c == '"' and cmd[end] in "\\`" and end + 1 < n) else 1
            buf.append(cmd[i + 1:end])
            quoted = True
            i = end + 1
            continue
        if c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            flush()
            m = re.match(r"<<-?\s*(['\"]?)([A-Za-z_][\w-]*)\1", cmd[i:])
            if m:
                heredocs.append(m.group(2))
                i += m.end()
                continue
        if c == "\n" and heredocs:
            flush()
            out.append(tok("\n"))
            for word in heredocs:
                m = re.compile(r"^[ \t]*" + re.escape(word) + r"[ \t\r]*$", re.M).search(cmd, i + 1)
                end = m.start() if m else n
                out.append(tok(cmd[i + 1:end], True))
                i = m.end() if m else n
            heredocs = []
            continue
        if c in " \t\r":
            flush()
            i += 1
            continue
        two = cmd[i:i + 2]
        if two in ("&&", "||", ">>", "&>"):
            flush()
            out.append(tok(two))
            i += 2
            continue
        if c in ";|&\n>":
            if c == ">" and buf and "".join(buf) in ("1", "2", "*"):
                buf.append(">")
                if cmd[i + 1:i + 2] == ">":
                    buf.append(">")
                    i += 1
                out.append(tok("".join(buf)))
                buf, quoted = [], False
                i += 1
                continue
            flush()
            out.append(tok(c))
            i += 1
            continue
        buf.append(c)
        i += 1
    flush()
    return out


def pipelines(tokens):
    """[(区切りの前の文字, [語の並び, ...] = | でつないだ命令)] にする。"""
    lines, cur, seg = [], [], []
    for t in tokens:
        if not t.quoted and t == "|":
            cur.append(seg)
            seg = []
        elif not t.quoted and t in SEPS:
            cur.append(seg)
            lines.append(cur)
            cur, seg = [], []
        else:
            seg.append(t)
    cur.append(seg)
    lines.append(cur)
    return [[s for s in p if s] for p in lines if any(p)]


def word_of(seg):
    """命令の名前(頭の X=1・& を飛ばし、小文字・.exe を外す)と、その後の語。"""
    k = 0
    while k < len(seg) and not seg[k].quoted and (re.match(r"^[A-Za-z_]\w*=", seg[k]) or seg[k] in ("&", "sudo", "exec")
                                                   or re.match(r"^\$env:\w+=", seg[k], re.I)):
        k += 1
    if k >= len(seg):
        return "", []
    name = os.path.basename(seg[k].replace("\\", "/")).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name, seg[k + 1:]


# ---- 場所

def norm_path(p, base):
    """Git Bash の /c/... も C:/... にして、base からの絶対パスにする(/ 区切り)。"""
    p = p.strip().replace("\\", "/")
    m = re.match(r"^/([a-zA-Z])(/|$)", p)
    if m:
        p = m.group(1).upper() + ":/" + p[3:]
    if p.startswith("~"):
        p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(base or os.getcwd(), p)
    return os.path.normpath(p).replace("\\", "/")


def is_main_checkout(path):
    """path を含む git の作業フォルダが、このリポジトリの main の作業フォルダ(.git がフォルダ・dev/land.py がある)か。"""
    cur = path
    for _ in range(40):
        g = os.path.join(cur, ".git")
        if os.path.exists(g):
            return os.path.isdir(g) and os.path.isfile(os.path.join(cur, "dev", "land.py"))
        up = os.path.dirname(cur)
        if up == cur:
            return False
        cur = up
    return False


def generated_kind(path):
    """生成物なら MSG の鍵を返す。"""
    low = path.replace("\\", "/")
    parent = os.path.dirname(low)
    name = os.path.basename(low)
    if os.path.basename(parent).lower() == "plan" and os.path.isdir(os.path.join(parent, "data")):
        if name.lower() == "data.js":
            return "data.js"
        if name == "仮決めの一覧.md":
            return "prov"
    if (os.path.basename(parent).lower() == "codemap" and name.lower().endswith(".md")
            and os.path.isfile(os.path.join(os.path.dirname(parent), "dev", "code_map.py"))):
        return "codemap"
    return None


# ---- 判定

def check_kill(pipe, tool):
    names = [word_of(s) for s in pipe]
    for name, args in names:
        low = [a.lower() for a in args if not a.quoted]
        if name in ("pkill", "killall"):
            return "kill"
        if name == "taskkill":
            if any(a in ("/im", "-im") for a in low):
                return "kill"
            if any(a in ("/fi", "-fi") for a in low) and any("imagename" in a.lower() for a in args):
                return "kill"
        if name == "wmic" and any("name" in a.lower() for a in args) and any(a in ("delete", "terminate") for a in low):
            return "kill"
        stop = name in KILL_STOP or (tool == "PowerShell" and name == "kill")
        if stop:
            if any(a in ("-name", "-n", "-na", "-nam", "-processname") for a in low):
                return "kill"
            has_id = any(a in ("-id", "-i") for a in low) or any(re.match(r"^\d+(,\d+)*$", a) for a in low)
            fed = any(n in GET_PROC or (tool == "PowerShell" and n == "ps") for n, _ in names)
            if fed and not has_id:
                feeder = [a for n, al in names if n in GET_PROC or n == "ps" for a in al]
                if not any(a.lower() in ("-id", "-i") for a in feeder if not a.quoted):
                    return "kill"
    return None


def check_sed(name, args):
    if name != "sed":
        return None
    for a in args:
        if a.quoted:
            continue
        if a.startswith("--in-place"):
            return "sed"
        if re.match(r"^-[A-Za-z]*i", a) and not a.startswith("--"):
            return "sed"
    return None


def git_sub(args, base):
    """git の後の語から (サブコマンド, その後の語, -C で変わった場所)。"""
    k, where = 0, base
    while k < len(args) and args[k].startswith("-") and not args[k].quoted:
        a = args[k]
        if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and k + 1 < len(args):
            if a == "-C":
                where = norm_path(args[k + 1], where)
            k += 2
            continue
        k += 1
    if k >= len(args):
        return "", [], where
    return args[k].lower(), args[k + 1:], where


def check_git(name, args, base, raw):
    if name != "git":
        return None
    sub, rest, where = git_sub(args, base)
    if sub == "add":
        for a in rest:
            if a in ("-A", "--all", ".", "./", ":/", "*", "--no-ignore-removal", ":/*"):
                return "add"
            if not a.quoted and re.match(r"^-[a-zA-Z]*A", a) and not a.startswith("--"):
                return "add"
    if sub == "commit":
        for a in rest:
            if a.quoted:
                continue
            if a == "--all" or (re.match(r"^-[a-zA-Z]*a", a) and not a.startswith("--")):
                return "add"
        if is_main_checkout(where) and not allow_main(raw):
            return "main"
    return None


def allow_main(raw):
    if os.environ.get(MAIN_COMMIT_ENV) == "1":
        return True
    return bool(re.search(r"\b" + MAIN_COMMIT_ENV + r"\s*=\s*['\"]?1\b", raw))


def write_targets(name, args, seg):
    """この命令が書くファイル(リダイレクトの先・Set-Content などの引数・cp/mv の行き先)。"""
    out = []
    for k, t in enumerate(seg):
        if not t.quoted and t in REDIRECTS and k + 1 < len(seg):
            out.append(seg[k + 1])
    plain = [a for a in args if not (a.startswith("-") and not a.quoted)]
    if name in WRITE_CMDS:
        out.extend(a for a in plain if a not in REDIRECTS)
    if name in MOVE_CMDS and plain:
        dest = [args[k + 1] for k, a in enumerate(args[:-1]) if a.lower() in ("-destination", "-target")]
        out.extend(dest or [plain[-1]])
    return out


def check_command(cmd, tool="Bash", cwd=None):
    """命令の文字列を判定する。(断る理由 or None, 知らせ or None)。"""
    base = cwd or os.getcwd()
    warn = None
    for pipe in pipelines(tokenize(cmd)):
        why = check_kill(pipe, tool)
        if why:
            return why, None
        for seg in pipe:
            name, args = word_of(seg)
            if name in CD_CMDS:
                plain = [a for a in args if not (a.startswith("-") and not a.quoted)]
                if plain:
                    base = norm_path(plain[0], base)
                continue
            why = check_sed(name, args) or check_git(name, args, base, cmd)
            if why:
                return why, None
            for target in write_targets(name, args, seg):
                kind = generated_kind(norm_path(target, base))
                if kind:
                    return kind, None
            if is_test_run(name, args) and "YTT_DATA_DIR" not in cmd and not os.environ.get("YTT_DATA_DIR"):
                warn = WARN_DATA_DIR
    return None, warn


def is_test_run(name, args):
    if name == "pytest":
        return True
    if name in ("py", "python", "python3"):
        plain = [a for a in args if not a.quoted]
        for k, a in enumerate(plain[:-1]):
            if a == "-m" and plain[k + 1] in ("unittest", "pytest"):
                return True
    return False


def check_edit(tool_input, cwd):
    paths = [tool_input.get("file_path"), tool_input.get("notebook_path")]
    for p in paths:
        if p:
            kind = generated_kind(norm_path(p, cwd))
            if kind:
                return kind
    return None


def decide(data):
    """フックの入力(dict)から (断る理由の文 or None, 知らせ or None)。"""
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool in ("Bash", "PowerShell"):
        why, warn = check_command(ti.get("command") or "", tool, cwd)
    elif tool in EDIT_TOOLS:
        why, warn = check_edit(ti, cwd), None
    else:
        return None, None
    return (PREFIX + MSG[why] + "(フックが断った。回り道をせず、この代わりのやり方を使う)") if why else None, warn


def respond(why, warn):
    if why:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": why}}
    elif warn:
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": warn}}
    else:
        return
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    sys.stdout.flush()


# ---- 設定に足す

HOOK_COMMAND = 'py -3.12 "C:/dev/youtube-tools/dev/guard_hook.py" || true'
MATCHER = "Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit"


def install(path):
    """settings.json の hooks.PreToolUse にこのフックを足す(同じ command があれば何もしない)。足したら True。"""
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
        data = json.loads(text) if text.strip() else {}
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for entry in pre:
        for h in entry.get("hooks", []):
            if "guard_hook.py" in (h.get("command") or ""):
                return False
    pre.append({"matcher": MATCHER, "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 10}]})
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return True


def main(argv):
    if argv[:1] == ["--install"]:
        path = argv[1] if len(argv) > 1 else os.path.join(os.getcwd(), ".claude", "settings.json")
        print(("足した: " if install(path) else "もう入っている: ") + path)
        return 0
    if argv[:1] == ["--check"]:
        tool = argv[argv.index("--tool") + 1] if "--tool" in argv else "Bash"
        cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
        why, warn = check_command(argv[1], tool, cwd)
        print(why and (PREFIX + MSG[why]) or warn or "通す")
        return 1 if why else 0
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        why, warn = decide(json.loads(raw) if raw.strip() else {})
        respond(why, warn)
    except Exception:   # 壊れたら通す(全部のセッションを止めないため)
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
