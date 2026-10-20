"""資料の食い違いの検査(dev/doc_state.py・dev/spec_check.py の --gone)のテスト。一時フォルダの偽の保管庫だけを使う"""
import json
import os
import sys
import tempfile
import unittest

DEV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DEV)
import doc_state  # noqa: E402
import spec_check  # noqa: E402


def write(path, text, newline="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.replace("\n", newline).encode("utf-8"))


def read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def task(id_, state, line, docs):
    return json.dumps({"id": id_, "name": id_, "state": state, "line": line, "docs": docs, "order": 10}, ensure_ascii=False)


DOC = "---\n種類: 計画\n状態: {st}\n線:\n  - A\n---\n# 見出し\n本文\n"


class DocStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        write(os.path.join(self.root, "plan", "data", "main.json"), "{}")

    def tearDown(self):
        self.tmp.cleanup()

    def put_task(self, id_, state, line, docs):
        write(os.path.join(self.root, "plan", "data", "tasks", id_.lower() + ".json"), task(id_, state, line, docs))

    def test_shifted_state_is_stopped_and_fix_keeps_crlf(self):
        self.put_task("X1", "done", "A", ["x.md"])
        self.put_task("X2", "doing", "B・運用", ["x.md"])
        p = os.path.join(self.root, "plan", "x.md")
        write(p, DOC.format(st="済み"), newline="\r\n")   # わざと状態をずらした資料
        bad = doc_state.check(self.root)
        self.assertTrue(any("状態が計画のデータと違う: 済み → 進行中" in m for _r, _l, m in bad), bad)
        self.assertTrue(any("線が計画のデータと違う" in m for _r, _l, m in bad), bad)
        self.assertEqual(doc_state.sync(self.root), ["plan/x.md"])
        text = read(p)
        self.assertEqual(text, "---\r\n種類: 計画\r\n状態: 進行中\r\n線:\r\n  - A\r\n  - B\r\n  - 全体\r\n---\r\n# 見出し\r\n本文\r\n")
        self.assertEqual(doc_state.check(self.root), [])
        self.assertEqual(doc_state.sync(self.root), [])   # 同じなら書かない


class SpecCheckTest(unittest.TestCase):
    def test_gone_names_in_repo_and_notes(self):
        """消した道具の名前: リポジトリのファイル(GONE_OK を除く)と保管庫の AGENTS.md・docs/spec・codemap。経緯の場所(docs/design・plan/done)は見ない"""
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as repo:
            write(os.path.join(repo, "src", "a.py"), "x = 1\n# 前の Request" + "Sender の口\n")
            write(os.path.join(repo, ".gitignore"), "friend-apps/request-" + "sender/\n")
            write(os.path.join(root, "AGENTS.md"), "依頼" + "ボックス\n")
            write(os.path.join(root, "docs", "spec", "f.md"), "# 仕様\n## 経緯\n送る" + "アプリ 2.0\n")
            write(os.path.join(root, "docs", "design", "history.md"), "Request" + "Sender\n")
            write(os.path.join(root, "plan", "done", "x.md"), "Request" + "Sender\n")
            hits = spec_check.gone(root, repo, files=["src/a.py", ".gitignore", "src/missing.py"])
            self.assertEqual(sorted((w, ln) for w, ln, _n in hits), [("notes:AGENTS.md", 1), ("notes:" + "docs/spec/f.md", 3), ("src/a.py", 2)])


if __name__ == "__main__":
    unittest.main()
