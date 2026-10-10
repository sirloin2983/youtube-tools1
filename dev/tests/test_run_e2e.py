"""dev/run_e2e.py(e2e の一式)の一覧が、リポジトリの e2e_*.py と食い違っていないかを確かめる。

    py -3.10 -m unittest dev/tests/test_run_e2e.py
"""
import glob
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import run_e2e  # noqa: E402


def repo_e2e_scripts():
    """リポジトリにある e2e_*.py(共通部品 e2e_edit_common は除く)をリポジトリからの相対パス(/ 区切り)で"""
    found = set()
    for top in ("src", "dev", "chrome-ext", "friend-apps"):
        for p in glob.glob(os.path.join(REPO, top, "**", "e2e_*.py"), recursive=True):
            rel = os.path.relpath(p, REPO).replace(os.sep, "/")
            if not rel.endswith("/e2e_edit_common.py"):
                found.add(rel)
    return found


class TestSuiteList(unittest.TestCase):
    def test_every_listed_script_exists(self):
        for _g, script, _a, _w in run_e2e.SUITE:
            self.assertTrue(os.path.isfile(os.path.join(REPO, script)), script)
        for script in run_e2e.NOT_IN_SUITE:
            self.assertTrue(os.path.isfile(os.path.join(REPO, script)), script)

    def test_every_repo_script_is_listed_or_excluded(self):
        listed = {s for _g, s, _a, _w in run_e2e.SUITE} | run_e2e.NOT_IN_SUITE
        missing = sorted(repo_e2e_scripts() - listed)
        self.assertEqual(missing, [], "e2e を足したら dev/run_e2e.py の SUITE か NOT_IN_SUITE に入れる")

    def test_no_duplicates_and_known_groups(self):
        names = [run_e2e.label(s, a) for _g, s, a, _w in run_e2e.SUITE]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual({g for g, _s, _a, _w in run_e2e.SUITE}, {"editor", "home", "studio", "dev", "ui-kit"})

    def test_only_filters_by_group_or_name(self):
        editor = run_e2e.selected(["editor"])
        self.assertTrue(editor and all(r[0] == "editor" for r in editor))
        live = run_e2e.selected(["live_"])
        self.assertEqual(sorted(r[4] for r in live), ["e2e_live_archive", "e2e_live_studio"])
        both = run_e2e.selected(["dev", "e2e_fill"])
        self.assertEqual({r[0] for r in both}, {"dev", "editor"})
        self.assertEqual(len(run_e2e.selected([])), len(run_e2e.SUITE))
        no_live = run_e2e.selected([], ["live_"])
        self.assertEqual(len(no_live), len(run_e2e.SUITE) - 2)
        self.assertFalse(any("live_" in r[4] for r in no_live))
        self.assertEqual([r[0] for r in run_e2e.selected(["home"], ["home"])], [])

    def test_summary_counts_ok_and_fail(self):
        self.assertEqual(run_e2e.summary("OK   a\nOK   b\nFAIL c\nNG   d\n"), "OK 2 / FAIL 2")

    def test_editor_suite_runner_agrees(self):
        """dev/run_editor_suite.py の編集の e2e の一覧は、一式の editor の組と同じ"""
        import run_editor_suite
        mine = sorted(run_e2e.label(s, a) for g, s, a, _w in run_e2e.SUITE if g == "editor")
        self.assertEqual(sorted(run_editor_suite.E2E), mine)


if __name__ == "__main__":
    unittest.main()
