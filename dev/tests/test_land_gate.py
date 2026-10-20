"""dev/land_gate.py(main に入れる前の関所)と dev/worklog.py check(報告の型)のテスト。一時フォルダだけを使う(テストは流さない)"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
sys.path.insert(0, os.path.join(REPO, "src"))
import land_gate  # noqa: E402
import worklog  # noqa: E402
from ytt.tests import testkit  # noqa: E402

GOOD = """---
種類: 記録
まとめ: 関所を足した
---
# 2026-10-18 Claude Code — 関所
- 直した物: `dev/land.py` に関所を足した
- 確かめた物: 単体テスト
## 本物ではまだ確かめていない物
なし
- **ユーザーがすること**: なし
"""


put = testkit.write_text


class SelectTest(unittest.TestCase):
    def test_layer_runs_itself_and_upper_layers(self):
        dirs, manual, unknown = land_gate.select(["src/manage/keep/trash.py"])
        self.assertIn("src/manage/", dirs)
        self.assertIn("src/eval/", dirs)            # eval は manage を読んでよい
        self.assertIn("src/editor/", dirs)          # app(入口が取り込んだ旧いツールも)
        self.assertNotIn("src/pipeline/", dirs)     # 下の層は流さない
        self.assertNotIn("src/friendapp/", dirs)
        self.assertEqual((manual, unknown), ([], []))

    def test_ytt_runs_everything(self):
        self.assertEqual(land_gate.select(["src/flow/a.py", "src/ytt/fsio.py"])[0], land_gate.ALL)

    def test_dev_setup_manual_and_docs(self):
        dirs, manual, unknown = land_gate.select(["dev/lint.py", "setup/a.bat", "friend-apps/launcher/src/A.cs",
                                                  "codemap/dev.md", "README.txt", "odd/x.py"])
        self.assertEqual(dirs, {land_gate.DEV_TESTS})
        self.assertEqual(manual, [r"friend-apps\launcher\build.bat"])
        self.assertEqual(unknown, ["odd/x.py"])

    def test_docs_only_runs_guards(self):
        units = land_gate.pick_units(REPO, land_gate.select(["codemap/dev.md"])[0])
        self.assertEqual(sorted(u.rel for u in units), sorted(land_gate.GUARDS))

    def test_session_name(self):
        self.assertEqual(land_gate.session_name("claude/land-gate-c990b8"), "land-gate")
        self.assertEqual(land_gate.session_name("friend-preflight"), "friend-preflight")


class TableTest(unittest.TestCase):
    def setUp(self):
        tmp = testkit.tempdir(self)
        self.root = os.path.join(tmp, "repo")
        for d in ("src/ytt", "src/newlayer", "friend-apps/launcher", "dev"):
            os.makedirs(os.path.join(self.root, *d.split("/")))
        self.md = os.path.join(tmp, "code.md")
        put(self.md, "# x\n\n" + land_gate.TABLE_HEAD + "\n説明\n\n| フォルダ | テスト |\n| --- | --- |\n"
            "| `src/ytt/`(旧 `src/ytt_core/`) | a |\n| `friend-apps/launcher/` | b |\n| `friend-apps/gone/` | c |\n"
            "| `dev/` | d |\n| `docs/`・`plan/` | e |\n\n## 7. 次\n| `src/other/` | x |\n")

    def test_folders_of_first_column(self):
        self.assertEqual(land_gate.table_folders(self.md),
                         ["src/ytt/", "friend-apps/launcher/", "friend-apps/gone/", "dev/", "docs/", "plan/"])

    def test_drift_warns_both_ways(self):
        warns = land_gate.table_drift(self.root, self.md)
        self.assertTrue(any("friend-apps/gone/ は、もう無い" in w for w in warns))
        self.assertTrue(any("src/newlayer/ が表に無い" in w for w in warns))
        self.assertEqual(len(warns), 2)

    def test_real_table_matches_repo(self):
        """今の code.md の表(保管庫がある PC だけ)と、関所の決まり・実際のフォルダがずれていない"""
        code_md = os.path.join(land_gate.layout.notes_root(), "docs", "spec", "code.md")
        if not os.path.isfile(code_md):
            self.skipTest("保管庫が無い")
        self.assertEqual(land_gate.table_drift(REPO, code_md), [])


class WorklogCheckTest(unittest.TestCase):
    def setUp(self):
        self.notes = testkit.tempdir(self)

    def test_good_report_passes(self):
        p = os.path.join(self.notes, "a.md")
        put(p, GOOD)
        self.assertEqual(worklog.check(p), ([], []))

    def test_template_has_all_headings(self):
        text = worklog.TEMPLATE.format(summary="x", date="2026-10-18", who="Claude Code ", title="t")
        self.assertEqual(worklog.missing_headings(text), [])

    def test_missing_heading_stops(self):
        p = os.path.join(self.notes, "a.md")
        put(p, GOOD.replace("- 確かめた物: 単体テスト\n", "- 確かめ: 単体テスト\n"))
        probs, _w = worklog.check(p)
        self.assertEqual(len(probs), 1)
        self.assertIn("確かめた物", probs[0])

    def test_english_warns_but_code_names_do_not_count(self):
        code_heavy = GOOD + "".join("- `dev/land_gate.py` の `select()` と `run_unit.build_units` を使う(src/ytt/tests/test_ytt_core.py)\n"
                                    for _ in range(20))
        p = os.path.join(self.notes, "a.md")
        put(p, code_heavy)
        self.assertEqual(worklog.check(p)[1], [])
        put(p, GOOD + "Added the gate to land and verified that it stops when another layer's test fails. " * 10)
        probs, warns = worklog.check(p)
        self.assertEqual(probs, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("英字が多い", warns[0])

    def test_find_session_picks_newest(self):
        old = os.path.join(worklog.worklog_dir(self.notes), "2026-10-12週", "2026-10-13-land-gate.md")
        new = os.path.join(worklog.worklog_dir(self.notes), "2026-10-19週", "2026-10-20-land-gate.md")
        put(old, GOOD)
        put(new, GOOD)
        put(os.path.join(worklog.worklog_dir(self.notes), "2026-10-19週", "2026-10-21-land-gate-x.md"), GOOD)
        self.assertEqual(worklog.find_session("land-gate", self.notes), new)
        self.assertIsNone(worklog.find_session("nothing", self.notes))


class RunTest(unittest.TestCase):
    """関所の流れ(git は一時フォルダ・テストと道具は差し替え)"""

    def setUp(self):
        self.notes = os.path.join(testkit.tempdir(self), "notes")
        put(os.path.join(worklog.worklog_dir(self.notes), "2026-10-12週", "2026-10-18-gate.md"), GOOD)
        self.saved = (land_gate.worktree_of, land_gate.git, land_gate.run_tool, land_gate.run_units, land_gate.table_drift)
        land_gate.worktree_of = lambda root, b: REPO
        land_gate.git = lambda root, *a: (0, "src/manage/keep/trash.py\n" if a[0] == "diff" else "")
        land_gate.run_tool = lambda root, args: (True, "")
        land_gate.table_drift = lambda root, md: []
        self.ran = []

    def tearDown(self):
        (land_gate.worktree_of, land_gate.git, land_gate.run_tool, land_gate.run_units, land_gate.table_drift) = self.saved

    def fake_units(self, fail):
        def run_units(units, jobs, log=print):
            self.ran = [u.rel for u in units]
            return [land_gate.run_unit.Result(u, False, 1, 0.1, "AssertionError: x") for u in units if u.rel in fail]
        land_gate.run_units = run_units

    def test_passes_and_times(self):
        self.fake_units(set())
        g = land_gate.run("claude/gate-abc123", notes=self.notes, log=lambda s: None)
        self.assertEqual(g.problems, [])
        self.assertIn("src/ytt/tests/test_ytt_core.py", self.ran)            # 見張りはいつも
        self.assertTrue(any(r.startswith("src/manage/") for r in self.ran))
        self.assertFalse(any(r.startswith("src/pipeline/") for r in self.ran))
        self.assertEqual([n for n, _s in g.times][0], "検査")

    def test_other_layer_test_failure_stops(self):
        self.fake_units({"src/ytt/tests/test_ytt_core.py"})
        g = land_gate.run("claude/gate-abc123", notes=self.notes, log=lambda s: None)
        self.assertEqual(len(g.problems), 1)
        self.assertIn("test_ytt_core", g.problems[0])

    def test_check_failure_and_missing_worklog_stop(self):
        self.fake_units(set())
        land_gate.run_tool = lambda root, args: (args[0] != "dev/lint.py", "合計 1 件")
        g = land_gate.run("claude/other-abc123", notes=self.notes, log=lambda s: None)
        self.assertTrue(any(p.startswith("lint が落ちた") for p in g.problems))
        self.assertTrue(any(p.startswith("作業の記録が無い: other") for p in g.problems))

    def test_check_failing_on_main_too_only_warns(self):
        outs = {"wt": (False, "notes-path: 3\n合計 3 件(0 で合格)"), "main": (False, "合計 5 件(0 で合格)")}
        land_gate.run_tool = lambda root, args: outs[root]
        self.assertEqual(land_gate.run_check("wt", "main", "lint", ["dev/lint.py"])[0], None)
        self.assertIn("main でも 5 件", land_gate.run_check("wt", "main", "lint", ["dev/lint.py"])[1])
        outs["main"] = (True, "合計 0 件(0 で合格)")
        prob, warn = land_gate.run_check("wt", "main", "lint", ["dev/lint.py"])
        self.assertIn("lint が落ちた", prob)
        self.assertIsNone(warn)

    def test_skips_are_kept(self):
        self.fake_units({"src/ytt/tests/test_ytt_core.py"})
        g = land_gate.run("claude/x-abc123", skip={"tests", "worklog"}, notes=self.notes, log=lambda s: None)
        self.assertEqual(g.problems, [])
        self.assertEqual(g.skipped, ["tests", "worklog"])
        self.assertEqual(self.ran, [])


if __name__ == "__main__":
    unittest.main()
