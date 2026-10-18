"""資料の食い違いの検査(dev/doc_state.py・dev/spec_check.py・dev/drift_report.py)のテスト。一時フォルダの偽の保管庫だけを使う"""
import json
import os
import sys
import tempfile
import unittest

DEV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DEV)
import doc_state  # noqa: E402
import drift_report  # noqa: E402
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

    def test_decide(self):
        self.assertEqual(doc_state.decide(["done", "done"]), "済み")
        self.assertEqual(doc_state.decide(["todo"]), "これから")
        self.assertEqual(doc_state.decide(["done", "todo"]), "進行中")   # 始めて終わっていない
        self.assertEqual(doc_state.decide(["wait"]), "進行中")

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

    def test_inline_lines_and_missing_props(self):
        self.put_task("Y", "todo", "C", ["y.md"])
        p = os.path.join(self.root, "plan", "y.md")
        write(p, "---\n種類: 計画\n線: [C]\n---\n# y\n")
        self.assertEqual(doc_state.read_props(doc_state.front(read(p))[0]), (None, ["C"]))
        doc_state.sync(self.root)
        self.assertEqual(read(p), "---\n種類: 計画\n線:\n  - C\n状態: これから\n---\n# y\n")

    def test_done_placement_and_missing_doc(self):
        self.put_task("Z", "done", "D", ["z.md", "gone.md"])
        write(os.path.join(self.root, "plan", "z.md"), DOC.format(st="済み").replace("- A", "- D"))
        write(os.path.join(self.root, "plan", "done", "w.md"), DOC.format(st="進行中"))
        write(os.path.join(self.root, "plan", "h.md"), DOC.format(st="取り下げ"))   # 手で持つ資料も置き場所は見る
        write(os.path.join(self.root, "plan", "idx.md"), "---\n種類: 索引\n状態: 済み\n---\n")   # 自動の索引は見ない
        msgs = {(r, m.split("(")[0]) for r, _l, m in doc_state.check(self.root)}
        self.assertIn(("plan/z.md", "状態: 済み の計画は plan/done/ へ"), msgs)
        self.assertIn(("plan/h.md", "状態: 取り下げ の計画は plan/done/ へ"), msgs)
        self.assertIn(("plan/done/w.md", "plan/done/ にあるのに 状態: 進行中"), msgs)
        self.assertIn(("plan/gone.md", "計画のデータの docs が指す資料が無い"), msgs)
        self.assertFalse(any(r == "plan/idx.md" for r, _m in msgs))


class FakeCode:
    def __init__(self, text, routes):
        self.all = text
        self.texts = {"src/app/x.py": text}
        self.routes = routes

    def has_route(self, p):
        return spec_check.Code.has_route(self, p)


class SpecCheckTest(unittest.TestCase):
    def test_finds_missing_names_routes_paths(self):
        with tempfile.TemporaryDirectory() as root:
            write(os.path.join(root, "docs", "spec", "a.md"), "\n".join([
                "# 仕様", "`YTT_HERE` と `YTT_GONE` と接頭辞 `YTT_MACHINE_`",
                "口 `/api/cases/list` と `/friend/api/setup/start` と `/api/nope`",
                "パス `dev/spec_check.py:12` と `src/nothing_here.py` と `src/<層>/`",
                "旧 `src/old.py` <!-- spec-check: 旧 -->",
                "前のアプリ RequestSender の形", "## 経緯", "`YTT_HISTORY`", "RequestSender から移った", "## 今",
                "<!-- spec-check: 設定 -->", "| 鍵 | 説明 |", "| --- | --- |", "| `liveDetect` | 説明 |", "| `missingKey` | 説明 |"]))
            code = FakeCode('os.environ.get("YTT_HERE")\nos.environ["YTT_SECRET_ONLY"]\nd = {"liveDetect": 1}',
                            {"/api/cases", "/api/setup/start"})
            bad, warn = spec_check.check(root, code)
            msgs = sorted(m for _r, _l, m in bad)
            self.assertEqual(msgs, ["パスがリポジトリに無い: src/nothing_here.py", "口がコードに無い: /api/nope",
                                    "環境変数がコードに無い: YTT_GONE"])
            wmsgs = sorted(m for _r, _l, m in warn)
            self.assertEqual(wmsgs, ["消した道具の名前が仕様に残っている: RequestSender",   # 経緯の節の物は数えない
                                     "環境変数が docs/spec に書いていない: YTT_SECRET_ONLY", "設定の鍵がコードの文字列に無い: missingKey"])


class DriftReportTest(unittest.TestCase):
    def test_caps_and_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            long = "これは入口の文書に何度も出てくる、とても長い同じ説明の文で、五十字を超えるように書いてある行です。念のためもう少し足しておく。"
            write(os.path.join(root, "AGENTS.md"), "---\n種類: 決まり\n---\n# A\n- " + long + "\n" + "x\n" * 210)
            write(os.path.join(root, "docs", "spec", "s.md"), "# S\n" + long + "\n| " + long + " |\n")
            write(os.path.join(root, "ホーム.md"), "# H\n<!-- 自動: ここから -->\n" + long + "\n<!-- 自動: ここまで -->\n")
            write(os.path.join(root, "plan", "done", "big.md"), "y\n" * 900)   # 済んだ計画は数えない
            self.assertEqual([(r, lim) for r, _n, lim in drift_report.caps(root)], [("AGENTS.md", 200)])
            dups = drift_report.duplicates(root)
            self.assertEqual(len(dups), 1)
            self.assertEqual(sorted(r for r, _l in dups[0][1]), ["AGENTS.md", "docs/spec/s.md"])   # 表・自動の部分は数えない


if __name__ == "__main__":
    unittest.main()
