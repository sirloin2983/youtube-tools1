"""dev/run_e2e.py(e2e の一式)の一覧が、リポジトリの e2e_*.py と食い違っていないかを確かめる。

    py -3.12 -m unittest tests/dev/test_run_e2e.py
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import run_e2e  # noqa: E402


class TestSuiteList(unittest.TestCase):
    # 一覧が実在する物と一致するか・編集の一式が流す物は一覧にあるかは、lint の規則 R-04(dev/rule_checks.py)が見る
    def test_suite_stays_one_per_path(self):
        """e2e は主な道 1 つに 1 本。一式が 15 本を超えたら、足す前にどの道の 1 本に入るかを決める(細かい場面は単体・ui_audit へ)"""
        self.assertLessEqual(len(run_e2e.SUITE), 15, [run_e2e.label(s, a) for _g, s, a, _w in run_e2e.SUITE])

    def test_no_duplicates_and_known_groups(self):
        names = [run_e2e.label(s, a) for _g, s, a, _w in run_e2e.SUITE]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual({g for g, _s, _a, _w in run_e2e.SUITE}, {"cases", "home", "friend"})

    def test_only_filters_by_group_or_name(self):
        cases = run_e2e.selected(["cases"])
        self.assertTrue(cases and all(r[0] == "cases" for r in cases))
        live = run_e2e.selected(["live_"])
        self.assertEqual(sorted(r[4] for r in live), ["e2e_live_archive", "e2e_live_studio"])
        both = run_e2e.selected(["home", "e2e_cases_cut"])
        self.assertEqual({r[0] for r in both}, {"home", "cases"})
        self.assertEqual(len(run_e2e.selected([])), len(run_e2e.SUITE))
        no_live = run_e2e.selected([], ["live_"])
        self.assertEqual(len(no_live), len(run_e2e.SUITE) - 2)
        self.assertFalse(any("live_" in r[4] for r in no_live))
        self.assertEqual([r[0] for r in run_e2e.selected(["home"], ["home"])], [])

    def test_check_screen_is_covered(self):
        """確かめる(/check。V1)の e2e は一式の cases の組にあり、画面の検査(ui_audit all --demo)の場面は 4 種類のカードと空の状態を開く"""
        self.assertIn(("cases", "tests/app/e2e_check.py"), {(g, s) for g, s, _a, _w in run_e2e.SUITE})
        import ui_audit
        self.assertTrue(set(ui_audit.SCREENS["app/ui/check"]) >= {"index.html", "check.js", "check.css", "player.js",
                                                                  "cards/value.js", "cards/read.js", "cards/voice.js", "cards/time.js"})
        scenes = {s["name"]: s["url"] for s in ui_audit.default_scenes("http://127.0.0.1:9")}   # 見本サーバーが無い = 文書の id は空(場面の URL だけ見る)
        for kind in ("value", "read", "voice", "time"):
            self.assertTrue(any(u.endswith("/check?kind=" + kind) for u in scenes.values()), kind)
        self.assertIn("/check", scenes["check"])
        self.assertIn("c=zz-no-such-case", scenes["check-empty"])
        self.assertIn("/check", ui_audit.ALLOWED_PREFIX)

    def test_summary_counts_ok_and_fail(self):
        self.assertEqual(run_e2e.summary("OK   a\nOK   b\nFAIL c\nNG   d\n"), "OK 2 / FAIL 2")


if __name__ == "__main__":
    unittest.main()
