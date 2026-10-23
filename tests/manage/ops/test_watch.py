"""元の配信とガイドラインの見張り(src/manage/ops/watch.py。10-23 提案 P7)。本物の YouTube・ページには繋がない(偽の API と偽の取得)。リポジトリ直下で:
    python -m unittest tests/manage/ops/test_watch.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from manage.ops import watch as W  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

DAY = 86400
B = 1790000000   # 今に近い時刻(初回は記録が無い = どちらも期限を過ぎている)
PAGE_A = "<h1>二次創作ガイドライン</h1><p>2024年 3月 1日 制定</p><p>2025年10月 1日 改定</p>"
PAGE_B = PAGE_A + "<p>2026年11月 1日 改定</p>"


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-watch-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = os.path.join(self.tmp, "logs")
        os.makedirs(self.logs)
        with open(os.path.join(self.logs, W.DELIVERIES), "w", encoding="utf-8") as f:
            for i, vid in enumerate(["aaaaaaaaaaa", "bbbbbbbbbbb", "aaaaaaaaaaa", "ccccccccccc", "bad"]):
                f.write(json.dumps({"at": i, "videoId": vid, "title": "題" + vid[:1]}, ensure_ascii=False) + "\n")
            f.write("壊れた行\n")
        self.status = {"aaaaaaaaaaa": "public", "bbbbbbbbbbb": "public", "ccccccccccc": "public"}
        self.calls = []
        self.page = PAGE_A
        self.logged = []

    def get(self, path, params):
        self.calls.append(params["id"])
        return {"items": [{"id": v, "status": {"privacyStatus": self.status[v]}} for v in params["id"].split(",") if v in self.status]}

    def watch(self):
        return W.Watch(self.tmp, self.logs, log=self.logged.append, get=self.get, fetch=lambda url: self.page.encode("utf-8"), env={})

    def test_sources_newest_first_unique(self):
        self.assertEqual([v for v, _ in W.delivered_sources(self.logs)], ["ccccccccccc", "aaaaaaaaaaa", "bbbbbbbbbbb"])

    def test_private_or_gone_is_reported_once_with_since(self):
        w = self.watch()
        s = w.run(now=B + 10 * DAY)
        self.assertEqual((s["sources"]["checked"], s["sources"]["changed"]), (3, []))
        self.assertEqual(s["terms"]["mark"], "2025-10-01 改定 / 2024-03-01 制定")
        self.status["bbbbbbbbbbb"] = "private"
        del self.status["ccccccccccc"]   # 削除された = API の答えに無い
        s = w.run(now=B + 10 * DAY + 1)       # 1 週間たっていない = 見に行かない
        self.assertEqual(s["sources"]["changed"], [])
        s = w.run(now=B + 18 * DAY)
        got = {x["videoId"]: (x["state"], x["since"]) for x in s["sources"]["changed"]}
        self.assertEqual(got, {"bbbbbbbbbbb": ("非公開", (B + 18 * DAY) * 1000), "ccccccccccc": (W.GONE, (B + 18 * DAY) * 1000)})
        self.assertTrue(any("2 本" in m for m in self.logged))
        s = w.run(now=B + 26 * DAY)   # 同じ状態のまま = 気づいた日は前のまま・知らせ直さない
        self.assertEqual({x["videoId"]: x["since"] for x in s["sources"]["changed"]}, {"bbbbbbbbbbb": (B + 18 * DAY) * 1000, "ccccccccccc": (B + 18 * DAY) * 1000})
        self.assertEqual(sum(1 for m in self.logged if "公開でなくなりました" in m), 1)
        self.assertEqual(self.calls[-1].count(","), 2)   # 3 本を 1 回で(50 本ずつ)

    def test_terms_change_and_unreadable_page(self):
        w = self.watch()
        w.run(now=B + 40 * DAY)
        self.page = "<p>ページの作りが変わった</p>"
        s = w.run(now=B + 80 * DAY)
        self.assertFalse(s["terms"].get("changedAt"))   # 日付が読めない = 変わったとは言わない
        self.assertIn("読めませんでした", s["terms"]["error"])
        self.page = PAGE_B
        s = w.run(now=B + 120 * DAY)
        self.assertEqual((s["terms"]["changedAt"], s["terms"]["prev"]), ((B + 120 * DAY) * 1000, "2025-10-01 改定 / 2024-03-01 制定"))
        self.assertTrue(s["terms"]["mark"].startswith("2026-11-01 改定"))

    def test_api_error_waits_and_switch(self):
        def broken(path, params):
            raise ApiError("no_key", "API キーが未設定です", 400)
        w = W.Watch(self.tmp, self.logs, get=broken, fetch=lambda url: PAGE_A.encode("utf-8"), env={})
        s = w.run(now=B + 10 * DAY)
        self.assertIn("API キー", s["sources"]["error"])
        self.assertFalse(W.Watch(self.tmp, self.logs, env={W.SWITCH_ENV: "0"}).due())
        self.assertFalse(W.Watch(self.tmp, self.logs, env={"YTT_DATA_DIR": "inplace"}).due())   # テスト・見本はネットに繋がない
        self.assertEqual(set(w.view(start=False)), {"sources", "terms"})


if __name__ == "__main__":
    unittest.main()
