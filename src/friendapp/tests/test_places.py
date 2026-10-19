"""src/friendapp/places.py のテスト。リポジトリ直下で: py -3.12 -m unittest src/friendapp/tests/test_places.py"""
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import testkit  # noqa: E402
from friendapp import places  # noqa: E402
from ytt import colors  # noqa: E402


class MembersEnvTest(unittest.TestCase):
    def setUp(self):
        self.home = testkit.tempdir(self, "places-")

    def put_members(self):
        p = os.path.join(self.home, "members.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("[]")
        return p

    def test_zip_root_members_found(self):
        """zip の直下の members.json を colors.members_path が見つける(友人の PC)"""
        p = self.put_members()
        env = {}
        self.assertTrue(places.members_env(self.home, env))
        self.assertEqual(colors.members_path(env), p)

    def test_no_file_changes_nothing(self):
        """直下に無ければ何もしない(開発の PC は従来の場所のまま)"""
        env = {}
        self.assertFalse(places.members_env(self.home, env))
        self.assertNotIn(colors.MEMBERS_ENV, env)
        # ---- test_explicit_env_wins
        self.put_members()
        env = {colors.MEMBERS_ENV: "X:/mine.json"}
        self.assertFalse(places.members_env(self.home, env))
        self.assertEqual(env[colors.MEMBERS_ENV], "X:/mine.json")

if __name__ == "__main__":
    unittest.main()
