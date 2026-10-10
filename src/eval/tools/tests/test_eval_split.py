"""src/eval/tools/eval_split.py(評価用_仮置き の動画を評価用と学習用に分ける道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_eval_split.py

動画・作業データは一時フォルダに作る(本物の作業データ・評価用のフォルダは読まない・書かない)。ffprobe は使わない(長さは差し替える)。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import eval_split as E  # noqa: E402

ROSTER = E.load_roster()


def f(name, sec=40.0):
    member, date, known = E.parse_name(name, ROSTER)
    return {"name": name, "sec": sec, "member": member, "date": date, "known": known}


class ParseTest(unittest.TestCase):
    def test_names(self):
        for name, want in [
            ("26-03-10_大空スバル.mov", ("大空スバル", "26-03-10", True)),
            ("26-02-28_鷹嶺ルイ2.mov", ("鷹嶺ルイ", "26-02-28", True)),              # 末尾の番号は日付に入れない
            ("AZKi(ショート)_26-02-06.mov", ("AZKi", "26-02-06", True)),
            ("大神ミオ_26-01-31(ショート).mov", ("大神ミオ", "26-01-31", True)),
            ("26-02-07,08,10,15,16,19_さくらみこ.mov", ("さくらみこ", "26-02-07,08,10,15,16,19", True)),
            ("25-1015_兎田ぺこら.mov", ("兎田ぺこら", "25-1015", True)),
            ("26-05-01_スバル.mov", ("大空スバル", "26-05-01", True)),                # 呼び名(3 文字以上・普通の言葉と重ならない)
            ("26-05-01_不知火フレア.mkv.mov", ("不知火フレア", "26-05-01", True)),    # 二重の拡張子
        ]:
            self.assertEqual(E.parse_name(name, ROSTER), want, name)

    def test_outside_and_unknown(self):
        member, date, known = E.parse_name("教師データ＿如月れん03.mp4", ROSTER)
        self.assertEqual((member, known), ("如月れん", False))
        self.assertEqual(date, "教師データ＿如月れん03")                               # 日付が無ければ 1 本で 1 単位
        self.assertEqual(E.parse_name("26-01-01.mov", ROSTER)[0], E.UNKNOWN)


class PlanTest(unittest.TestCase):
    def files(self):
        out = [f("26-03-%02d_大空スバル.mov" % d) for d in range(1, 11)]
        out += [f("26-03-%02d_さくらみこ.mov" % d) for d in range(1, 7)]
        out += [f("26-03-01_常闇トワ.mov"), f("26-03-02_鷹嶺ルイ1.mov"), f("26-03-02_鷹嶺ルイ2.mov")]
        out += [f("教師データ＿如月れん01.mp4"), f("26-01-01.mov")]
        return out

    def test_forced_and_balance(self):
        plan = E.make_plan(self.files(), 6 * 40, "1", used=["26-03-05_大空スバル.mov"])
        side = {p["name"]: (p["side"], p["why"]) for p in plan}
        self.assertEqual(side["26-03-05_大空スバル.mov"], ("eval", "doc"))
        self.assertEqual(side["教師データ＿如月れん01.mp4"], ("eval", "outside"))
        self.assertEqual(side["26-01-01.mov"], ("eval", "unknown"))
        # 残りは、評価用の少ないメンバーから 1 単位ずつ: みこ・トワ・ルイ(2 本で 1 単位)に 1 つずつ入ってから、スバルの 2 つ目へは行かない
        per, tot = E.summarize(plan)
        self.assertEqual(per["大空スバル"]["eval"][0], 1)
        self.assertGreaterEqual(tot["eval"][1], 6 * 40)
        self.assertEqual(side["26-03-02_鷹嶺ルイ1.mov"][0], side["26-03-02_鷹嶺ルイ2.mov"][0])   # 同じ単位は同じ側
        self.assertEqual(len(plan), len(self.files()))

    def test_stable(self):
        a = E.make_plan(self.files(), 300, "1")
        b = E.make_plan(list(reversed(self.files())), 300, "1")
        self.assertEqual(a, b)                                                       # 並びによらず同じ
        c = E.make_plan(self.files(), 300, "2")
        self.assertEqual(len(a), len(c))

    def test_unit_with_doc_keeps_whole_unit(self):
        plan = E.make_plan(self.files(), 0, "1", used=["26-03-02_鷹嶺ルイ2.mov"])
        side = {p["name"]: p["side"] for p in plan}
        self.assertEqual((side["26-03-02_鷹嶺ルイ1.mov"], side["26-03-02_鷹嶺ルイ2.mov"]), ("eval", "eval"))
        self.assertEqual(side["26-03-01_さくらみこ.mov"], "train")                    # 目標 0 分なら、決まったもの以外は学習用


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        self.root, self.train, self.data = os.path.join(t, "評価用データ"), os.path.join(t, "学習用データ"), os.path.join(t, "data")
        self.staging = os.path.join(self.root, E.STAGING)
        os.makedirs(self.staging)
        os.makedirs(os.path.join(self.data, "transcripts"))
        self.names = ["26-03-%02d_大空スバル.mov" % d for d in range(1, 6)] + ["26-03-01_さくらみこ.mov", "教師データ＿如月れん01.mp4", "メモ.txt"]
        for n in self.names:
            with open(os.path.join(self.staging, n), "wb") as fh:
                fh.write(n.encode("utf-8"))
        self.doc("aaaaaaaaaaaa", os.path.join(self.staging, "26-03-02_大空スバル.mov"))

    def doc(self, tid, src):
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"id": tid, "sourcePath": src, "evalSet": True}, fh, ensure_ascii=False)

    def run_tool(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = E.main(list(argv) + ["--root", self.root, "--data", self.data])
        return code, out.getvalue()

    def plan(self, eval_min="1.5"):
        real = E.probe_sec
        E.probe_sec = lambda path: 40.0
        try:
            orig = E.cmd_plan
            E.cmd_plan = lambda args, probe=E.probe_sec: orig(args, probe)
            try:
                return self.run_tool("plan", "--train", self.train, "--eval-min", eval_min)
            finally:
                E.cmd_plan = orig
        finally:
            E.probe_sec = real

    def test_plan_apply(self):
        code, out = self.plan()
        self.assertEqual(code, 0, out)
        plan = E.read_plan(self.root)
        side = {p["name"]: (p["side"], p["why"]) for p in plan["files"]}
        self.assertNotIn("メモ.txt", side)                                            # 動画だけ
        self.assertEqual(side["26-03-02_大空スバル.mov"], ("eval", "doc"))
        self.assertEqual(side["教師データ＿如月れん01.mp4"], ("eval", "outside"))
        self.assertEqual(side["26-03-01_さくらみこ.mov"], ("eval", "balance"))         # 評価用の無い人から足す
        train = sorted(n for n, s in side.items() if s[0] == "train")
        self.assertEqual(len(train), 4)
        self.assertEqual(os.listdir(self.root).count(E.PLAN_NAME), 1)
        self.assertFalse(os.path.exists(self.train))                                  # plan は動かさない

        code, out = self.plan()                                                       # 2 回目は作り直さない
        self.assertIn("すでに一覧があります", out)

        code, out = self.run_tool("apply")
        self.assertEqual(code, 0, out)
        moved = sorted(os.listdir(os.path.join(self.train, "大空スバル")))
        self.assertEqual(moved, train)
        left = sorted(n for n in os.listdir(self.staging) if n.endswith((".mov", ".mp4")))
        self.assertEqual(left, sorted(n for n, s in side.items() if s[0] == "eval"))
        self.assertEqual(len(E.read_plan(self.root)["applied"]["moved"]), 4)

        code, out = self.run_tool("apply")                                            # もう一度流しても何も起きない
        self.assertEqual(code, 0, out)
        self.assertIn("移した 0 本・飛ばした 0 本", out)
        self.assertEqual(len(E.read_plan(self.root)["applied"]["moved"]), 4)

        code, out = self.plan()
        code, out = self.run_tool("plan", "--redo", "--train", self.train)            # 移したあとは作り直せない
        self.assertEqual(code, 2, out)

    def test_apply_skips(self):
        self.plan()
        plan = E.read_plan(self.root)
        train = [p["name"] for p in plan["files"] if p["side"] == "train"]
        self.doc("bbbbbbbbbbbb", os.path.join(self.staging, train[0]))                # 一覧を作ったあとで文字起こしされた
        os.makedirs(os.path.join(self.train, "大空スバル"))
        with open(os.path.join(self.train, "大空スバル", train[1]), "wb") as fh:      # 移す先に同じ名前
            fh.write(b"x")
        code, out = self.run_tool("apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.staging, train[0])))
        self.assertTrue(os.path.isfile(os.path.join(self.staging, train[1])))
        self.assertIn("飛ばした 2 本", out)

    def test_apply_stops_while_batch_runs_and_on_mixed_unit(self):
        self.plan()
        with open(os.path.join(self.data, "eval-batch.json"), "w", encoding="utf-8") as fh:
            json.dump({"enabled": True}, fh)
        code, out = self.run_tool("apply")
        self.assertEqual(code, 2)
        self.assertIn("まとめての文字起こしが動いています", out)
        os.remove(os.path.join(self.data, "eval-batch.json"))

        plan = E.read_plan(self.root)
        for p in plan["files"]:
            if p["name"] == "教師データ＿如月れん01.mp4":
                p["side"] = "train"                                                   # 手で直すのはよい
        plan["files"].append({"name": "26-03-01_さくらみこ2.mov", "sec": 1, "member": "さくらみこ", "date": "26-03-01", "known": True, "side": "train", "why": "train"})
        E.write_plan(self.root, plan)
        code, out = self.run_tool("apply")
        self.assertEqual(code, 2)                                                     # 同じ単位が両方の側にある
        self.assertIn("分かれています", out)

    def test_train_inside_root_is_refused(self):
        code, out = self.run_tool("plan", "--train", os.path.join(self.root, "学習用"))
        self.assertEqual(code, 2)
        self.assertIn("外にしてください", out)


if __name__ == "__main__":
    unittest.main()
