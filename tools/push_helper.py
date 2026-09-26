#!/usr/bin/env python3
"""push.bat の補助(2026-09-26)。標準ライブラリだけ。リポジトリ直下で git が使えることが前提。

    python tools/push_helper.py removals   … tools/removals.txt に書いたファイルを git rm する(コミットの前に呼ぶ)
    python tools/push_helper.py check      … これからコミットするファイル(git add したもの)に、個人データ・秘密情報らしいものが無いか調べる

■ removals(ファイルの削除)
  Cowork(クラウドの Claude)は PC のファイルを消せないので、消したいファイルを tools/removals.txt に書き、ユーザーの push.bat で消す。
  - 消すのは **git が管理しているファイルだけ**(`git rm`。履歴に残るので戻せる)。管理していないファイル(作業データなど)・フォルダ・リポジトリの外は消さない
  - 1行に1つ、リポジトリ直下からの相対パス(/ 区切り)。# から後はコメント。ワイルドカード・.. ・絶対パスは使えない(書いてあれば何もせず止まる)
  - もう無いファイルは飛ばす(何度実行しても同じ結果)

■ check(コミット前の検査)
  リポジトリは Public にする方針なので、次のものが入っていたら止める(終了コード 1。push.bat はコミットせずに止まる):
  - 秘密情報の形: Google の API キー・OpenAI などの sk- キー・GitHub/Slack のトークン・AWS のキー・秘密鍵
  - 個人データ・実行時のデータの名前: data.json・config.json・settings*.json・cases.json・.migrated.json・*.jsonl・cookies.txt・.env・
    transcripts/ dataset/ models/ などの下・動画や音声のファイル・ログ
  - 大きすぎるファイル(5MB 超。動画・キャッシュの混入)
  誤検出で止まったときは、その表示を Claude に見せる(ALLOW に足すか、検査を直す)。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOVALS = os.path.join(ROOT, "tools", "removals.txt")
MAX_BYTES = 5 * 1024 * 1024

SECRET_PATTERNS = [
    ("Google の API キー", re.compile(rb"AIza[0-9A-Za-z_\-]{35}")),
    ("sk- で始まる API キー", re.compile(rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}")),
    ("GitHub のトークン", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub のトークン", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("Slack のトークン", re.compile(rb"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("AWS のアクセスキー", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("秘密鍵", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
# 名前で止めるもの(小文字で比べる)
BAD_NAMES = {"data.json", "config.json", "cases.json", ".migrated.json", "cookies.txt", ".env", "registry.json",
             "feedback.jsonl", "learn-feedback.json", "eval-baselines.json", ".running.json"}
BAD_NAME_RE = re.compile(r"^settings.*\.json$|\.jsonl(\.old)?$|\.log(\.old)?$|\.(mp4|mkv|mov|webm|m4a|mp3|wav|flac|ogg|opus|aac|ts|flv|onnx|bin|pt|safetensors)$")
BAD_DIRS = {"transcripts", "dataset", "models", "cache", "archive", "exports", "clips", "work", "logs", ".runtime", "0old", ".whisper_models", "evals"}
# 検査の対象外(この検査自身とテスト。テストは偽物のキー・名前を使う)
ALLOW = {"tools/push_helper.py", "tools/test_push_helper.py"}


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r


# ---------------------------------------------------------------- removals

def read_removals(path=REMOVALS):
    """-> [相対パス]。正しくない行があれば ValueError(何も消さない)"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for n, line in enumerate(lines, 1):
        p = line.split("#", 1)[0].strip()
        if not p:
            continue
        parts = p.replace("\\", "/").split("/")
        if (p.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", p) or any(ch in p for ch in "*?[]")
                or any(x in ("", ".", "..") for x in parts)):
            raise ValueError("tools/removals.txt の %d 行目が正しくありません(リポジトリ直下からの相対パスを1つ): %s" % (n, line))
        out.append("/".join(parts))
    return out


def tracked(path):
    r = git("ls-files", "--error-unmatch", "--", path, check=False)
    return r.returncode == 0 and r.stdout.decode("utf-8", "replace").strip() == path


def apply_removals(path=REMOVALS, log=print):
    """-> 消したファイルの一覧"""
    done = []
    for p in read_removals(path):
        full = os.path.join(ROOT, *p.split("/"))
        if os.path.isdir(full):
            log("  [飛ばす] フォルダは消しません: %s" % p)
            continue
        if not tracked(p):
            if os.path.exists(full):
                log("  [飛ばす] git が管理していないファイルは消しません: %s" % p)
            continue   # もう無い
        git("rm", "-q", "--", p)
        done.append(p)
        log("  消しました: %s" % p)
    return done


# ---------------------------------------------------------------- check

def staged_files():
    """これからコミットする(追加・変更の)ファイル。-> [相対パス]"""
    r = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [x for x in r.stdout.decode("utf-8", "replace").split("\0") if x]


def staged_blob(path):
    return git("show", ":" + path).stdout


def problems_for(path, data):
    """1つのファイルの問題。-> [理由]"""
    if path in ALLOW:
        return []
    out = []
    parts = path.split("/")
    name = parts[-1].lower()
    if name in BAD_NAMES or BAD_NAME_RE.search(name):
        out.append("個人データ・実行時のデータの名前(%s)" % parts[-1])
    bad_dir = next((d for d in parts[:-1] if d.lower() in BAD_DIRS), None)
    if bad_dir:
        out.append("作業データのフォルダ(%s/)の中" % bad_dir)
    if len(data) > MAX_BYTES:
        out.append("大きすぎる(%.1fMB)" % (len(data) / 1048576))
    for label, rx in SECRET_PATTERNS:
        if rx.search(data):
            out.append("秘密情報らしい文字列(%s)" % label)
    return out


def check(files=None, read=staged_blob, log=print):
    """-> 問題のあったファイルの数"""
    files = staged_files() if files is None else files
    bad = 0
    for p in files:
        try:
            data = read(p)
        except (RuntimeError, OSError) as e:
            data = b""
            log("  [読めない] %s: %s" % (p, e))
        why = problems_for(p, data)
        if why:
            bad += 1
            log("  [止める] %s … %s" % (p, "・".join(why)))
    return bad


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "removals":
            done = apply_removals()
            if done:
                print("tools/removals.txt のファイルを %d 個消しました(git の履歴には残ります)" % len(done))
            return 0
        if cmd == "check":
            n = check()
            if n:
                print("")
                print("個人データ・秘密情報らしいファイルが %d 個あります。コミットしません。" % n)
                print("心当たりが無ければ、この表示をそのまま Claude に見せてください。")
                return 1
            return 0
    except (ValueError, RuntimeError) as e:
        print("[エラー] %s" % e)
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
