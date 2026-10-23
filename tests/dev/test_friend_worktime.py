"""dev/friend_worktime.py(友人の作業の時刻の集計。新機能 D)のテスト。一時フォルダの作業データだけを読む"""
import json
import os
import sys
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import friend_worktime as W  # noqa: E402
import testkit  # noqa: E402

NOW = 1792800000.0
H = 3600.0


class TestWorktime(unittest.TestCase):
    def test_collect(self):
        root = testkit.tempdir(self)
        logs = os.path.join(root, "app", "logs")
        rows = [{"at": int((NOW - 50 * H) * 1000), "zip": "r1__a.zip", "requestId": "r1", "videoId": "v1", "packs": [{"dir": "D:/c/a_pack"}]},
                {"at": int((NOW - 100 * H) * 1000), "zip": "r1__b.zip", "requestId": "r1", "videoId": "v1", "packs": [{"dir": "D:/c/b_pack"}]},
                {"at": int((NOW - 10 * H) * 1000), "zip": "r2__c.zip", "requestId": "r2", "videoId": "v1", "packs": [{"dir": "D:/c/c_pack"}]}]
        testkit.write_text(os.path.join(logs, "deliveries.jsonl"), "".join(json.dumps(r) + "\n" for r in rows))
        vd = os.path.join(root, "app", "friend-returns", "2026-10", "r1", "verdicts")
        testkit.write_json(os.path.join(vd, "a_pack~1.verdict.json"), {"v": 2, "judge": "good", "id": "x1", "zip": "r1__a.zip", "requestId": "r1", "pack": "a_pack",
                                                                     "at": int((NOW - 48 * H) * 1000), "arrivedAt": int((NOW - 50 * H) * 1000),
                                                                     "openedAt": int((NOW - 49 * H) * 1000)})
        testkit.write_json(os.path.join(root, "cut2resolve", "packs", "a.json"), {"dir": "D:/c/a_pack", "streamer": "星見ルナ"})
        pub = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(NOW - 26 * H))
        testkit.write_json(os.path.join(root, "analytics", "raw", "x.json"), {"videos": [{"short": True, "published": pub, "title": "星見ルナが叫ぶ"},
                                                                                         {"short": True, "published": pub, "title": "ほかの人"}]})
        r = W.collect(root, 14, now=NOW)
        # 届いた 3 本(c は判断の記録が無い = 届いて 10 時間なので「使われなかった」に数えない・b は 100 時間 = 数える)
        self.assertEqual((r["arrived"], r["decided"], r["unused"], r["undecidedOld"]), (3, 1, 1, 1))
        self.assertEqual((r["toOpenHours"], r["toDecideHours"], r["toPublishHours"], r["published"]), (1.0, 2.0, 24.0, 1))
        self.assertEqual(r["unusedOfDecided"], 0.0)


if __name__ == "__main__":
    unittest.main()
