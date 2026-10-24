"""src/human/friend/upwatch.py(友人のアプリの更新の見張り)のテスト。リポジトリ直下で:

    py -3.12 -m unittest tests/human/friend/test_upwatch.py

一時フォルダだけを使う(本物の Dropbox・作業データには触らない)。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from human.friend import upwatch as U  # noqa: E402

T0 = 1792900000.0


class UpwatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sync, self.app = os.path.join(self.tmp, "sync"), os.path.join(self.tmp, "app")
        for d in (U.IN_DIR, U.UPDATE_DIR):
            os.makedirs(os.path.join(self.sync, d))
        self.now = T0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, d):
        with open(os.path.join(self.sync, rel), "w", encoding="utf-8") as f:
            json.dump(d, f)

    def publish(self, ver, hours_ago):
        self.write(os.path.join(U.UPDATE_DIR, "versions.json"), {"versions": [{"version": "0.99.1", "publishedAt": 1},
                                                                             {"version": ver, "publishedAt": int((self.now - hours_ago * 3600) * 1000)}]})

    def beat(self, ver, hours_ago, wait=""):
        at = int((self.now - hours_ago * 3600) * 1000)
        self.write(os.path.join(U.IN_DIR, "app__beat-%d.beat.json" % at), {"v": 1, "kind": "beat", "at": at, "appVersion": ver, "wait": wait})

    def scan(self):
        U.scan(self.sync, self.app, lambda: self.now)
        return U.alerts(self.app, self.now)

    def test_fail_file_is_top_once(self):
        self.write(os.path.join(U.IN_DIR, "launcher__fail-1792899990000.fail.json"), {"v": 1, "kind": "rollback", "from": "0.99.250", "to": "0.99.249", "why": "起動しない"})
        got = self.scan()
        self.assertEqual([(a["level"], "前の版へ戻した" in a["text"]) for a in got], [("top", True)])
        self.assertEqual(len(self.scan()), 1)   # 1 つの鍵に 1 回

    def test_stale_version_warns_after_24h(self):
        self.publish("0.99.250", 23)
        self.beat("0.99.249", 1)
        self.assertEqual(self.scan(), [])                       # まだ 24 時間たっていない
        self.now += 2 * 3600
        got = self.scan()
        self.assertEqual(got[0]["level"], "warn")
        self.assertIn("友人の PC を確かめて", got[0]["text"])

    def test_wait_reason_is_note_only(self):
        self.publish("0.99.250", 30)
        self.beat("0.99.249", 1, wait="recording")
        self.assertEqual([a["level"] for a in self.scan()], ["note"])

    def test_updated_friend_is_quiet(self):
        self.publish("0.99.250", 30)
        self.beat("0.99.250", 1)
        self.assertEqual(self.scan(), [])
        with open(os.path.join(self.app, "friend-bugs", U.STATE_NAME), encoding="utf-8") as f:
            st = json.load(f)
        self.assertEqual((st["published"]["version"], st["friend"]["version"], st["friend"]["from"]), ("0.99.250", "0.99.250", "beat"))
        self.assertTrue(st["lastSeen"])

    def test_old_alerts_pruned(self):
        self.write(os.path.join(U.IN_DIR, "launcher__fail-1792899990000.fail.json"), {"v": 1, "kind": "launch_fail"})
        self.scan()
        self.now += (U.KEEP_DAYS + 1) * 86400
        self.assertEqual(self.scan(), [])


if __name__ == "__main__":
    unittest.main()
