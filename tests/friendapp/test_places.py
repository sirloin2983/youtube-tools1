"""src/friendapp/places.py のテスト。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_places.py"""
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
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


class FirstRosterTest(unittest.TestCase):
    def test_copies_bundled_to_work_data(self):
        """名簿は作業データの側へ同梱の物を写して読む(無い・中身が違えば写し直す)"""
        tx = os.path.join(testkit.tempdir(self, "roster-"), "transcribe")
        with open(places._roster.BUNDLED, "rb") as f:
            want = f.read()
        p = places.first_roster(tx)
        self.assertEqual(p, os.path.join(tx, "hololive-roster.json"))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), want)
        with open(p, "wb") as f:
            f.write(b"{}")
        places.first_roster(tx)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), want)


if __name__ == "__main__":
    unittest.main()
