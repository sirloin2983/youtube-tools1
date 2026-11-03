"""配信・依頼・切り抜きの状態を、出来事の記録(ytt/streamlog)の外に書くコードが増えていないかの見張り(11-03。資料 plan/情報をまとめる所-1103.md の「弱い所」)。

今の状態のファイル(STATE_FILES)の名前を文字として持つ部品(docstring・コメントは数えない)を、src の下から AST で集め、OWNERS と比べる。
- 新しい部品がこれらのファイルを読み書きし始めたら落ちる = 足す前に「出来事の記録に書くか・写しを読むか」を考える(足すなら OWNERS に理由つきで)。
- 部品が名前を持たなくなったら(写しへ移した)落ちる = OWNERS から外して、旧の読み方を減らしたことを残す。
状態のファイルを新しく作るときも STATE_FILES に足す(出来事の記録へ書くのが先)。
"""
import ast
import os
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
sys.path.insert(0, SRC)
from ytt import streamlog  # noqa: E402

# 今の書く所(段 2・11-03): 出来事の記録にも 1 行書く部品 -> 書く種類。消したら落ちる(旧の記録だけに書く所に戻さない)
WRITERS = {
    "human/friend/intake.py": {"request", "request-reject"},
    "flow/livesession.py": {"rec-start", "rec-link"},
    "flow/live_archive.py": {"rec-end"},
    "flow/live_adopt.py": {"adopt"},
    "flow/live_export.py": {"export"},
    "flow/deliveries.py": {"deliver", "not-sent"},
    "human/friend/returns.py": {"feedback", "undo"},
    "manage/cases/cases.py": {"discard"},
    "flow/runqueue.py": {"run-start", "run-end"},
}

# 配信・依頼・切り抜きの状態を持つファイル(作業データの中の名前)
STATE_FILES = ("exports.json", "requests.json", "bundles.json", "archive.json", "deliveries.jsonl", "not-sent.jsonl",
               "autorun-runs.jsonl", "intake-state.json", "friend_feedback.jsonl", "cases.json")

# 名前を持つ部品(src からの相対パス)-> 持ってよいファイル。11-03 の時点の全部(移し終えたら減らす)
OWNERS = {
    "app/live.py": ("requests.json",),                       # 依頼と録画の結びつき(RequestBook を組む)
    "flow/deliveries.py": ("deliveries.jsonl", "not-sent.jsonl"),   # 届けた・送らなかった(書く口と読む口)
    "flow/live_archive.py": ("archive.json",),               # 録画に無い区間をアーカイブから
    "flow/live_export.py": ("exports.json",),                # ライブの書き出しのジョブ
    "flow/live_head.py": ("archive.json",),
    "flow/live_report.py": ("exports.json",),
    "flow/livesession.py": ("bundles.json",),                # 録画ごとの封筒と束
    "flow/runlog.py": ("autorun-runs.jsonl",),               # まとめて実行の記録
    "friendapp/live.py": ("requests.json",),
    "friendapp/tidy.py": ("autorun-runs.jsonl",),
    "human/friend/intake.py": ("intake-state.json",),        # 友人の依頼の受付
    "manage/cases/cases.py": ("autorun-runs.jsonl", "cases.json", "deliveries.jsonl", "exports.json"),   # 案件(読む側。写しへ移す段 4 の相手)
}


def _strings(tree):
    """docstring を除いた文字の定数"""
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.value


def _calls(tree):
    """streamlog.note / streamlog.record の呼び出し -> [(種類の文字か None, 欄の名前の集まり)]"""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("note", "record")
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "streamlog"):
            kind = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            if kind is None and node.args and isinstance(node.args[0], ast.IfExp):   # "a" if x else "b"
                kind = tuple(x.value for x in (node.args[0].body, node.args[0].orelse) if isinstance(x, ast.Constant))
            yield kind, {k.arg for k in node.keywords if k.arg}


def _trees():
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", ".venv", "build", "dist", "work", "models", "fixtures")]
        for fn in files:
            if fn.endswith(".py"):
                p = os.path.join(base, fn)
                try:
                    with open(p, encoding="utf-8") as f:
                        yield os.path.relpath(p, SRC).replace(os.sep, "/"), ast.parse(f.read())
                except (SyntaxError, UnicodeDecodeError, OSError):
                    continue


def current():
    out = {}
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", ".venv", "build", "dist", "work", "models", "fixtures")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(base, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            got = sorted({s for s in STATE_FILES for v in _strings(tree) if s in v and len(v) < 200})
            if got:
                out[os.path.relpath(p, SRC).replace(os.sep, "/")] = tuple(got)
    return out


class GuardTest(unittest.TestCase):
    def test_no_new_state_owner(self):
        """状態のファイルの名前を持つ部品が OWNERS と同じ(増えた = 記録の外に状態を書く・読むコードが足された / 減った = OWNERS を減らす)"""
        got = current()
        self.assertEqual(got, OWNERS, "増えた: %s / 減った: %s(足すなら先に ytt/streamlog の出来事の記録へ。理由つきで OWNERS に)" % (
            sorted(set(got.items()) - set(OWNERS.items())), sorted(set(OWNERS.items()) - set(got.items()))))

    def test_writers_write_the_event_log(self):
        """今の書く所が出来事の記録にも書く(WRITERS)・呼び出しの種類と欄は名簿(streamlog.KINDS・FIELDS)にある物だけ"""
        found = {}
        for rel, tree in _trees():
            if rel == "ytt/streamlog.py":
                continue
            for kind, keys in _calls(tree):
                kinds = kind if isinstance(kind, tuple) else (kind,)
                for k in kinds:
                    self.assertIn(k, streamlog.KINDS, "%s: 知らない種類 %r" % (rel, k))
                    found.setdefault(rel, set()).add(k)
                self.assertEqual(keys - set(streamlog.FIELDS) - {"now", "p"}, set(), "%s: 知らない欄" % rel)
        self.assertEqual(found, WRITERS)


if __name__ == "__main__":
    unittest.main()
