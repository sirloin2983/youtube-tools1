# -*- coding: utf-8 -*-
"""F3-2 友人のアプリの配信の一覧(friendapp/streams.py)のテスト。リポジトリ直下で: py -3.10 -m unittest src/friendapp/tests/test_streams.py

本物のネットには出ない(取りに行く口は偽物 = Web)。時計も偽物(Clock)。覚えの JSON は一時フォルダに書く。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from friendapp import streams as S  # noqa: E402

CH_A = "UC" + "a" * 22
CH_D = "UC" + "d" * 22
NOW = datetime(2026, 10, 17, 15, 0, 0)          # PC の現地時刻(10-17 15:00)
NOW_TS = NOW.timestamp()
TODAY0 = datetime(2026, 10, 17)
YEST0 = datetime(2026, 10, 16)
MEMBERS = {
    "version": 2,
    "groups": [
        {"name": "0期", "branch": "JP", "members": [
            {"id": "aaa", "name": "テストA", "en": "Test A", "hex": "#112233", "subtitle": "#445566", "channel": CH_A},
            {"id": "bbb", "name": "テストB", "hex": "#000000"},   # channel が無い = 出さない
        ]},
        {"name": "DEV", "branch": "DEV_IS", "members": [
            {"id": "ddd", "name": "テストD", "hex": "#ABCDEF", "channel": CH_D},
        ]},
        {"name": "EN", "branch": "EN", "members": [
            {"id": "eee", "name": "テストE", "hex": "#FFFFFF", "channel": "UC" + "e" * 22},   # 範囲外の枝
        ]},
    ],
}


def ms(dt):
    return int(dt.timestamp() * 1000)


def iso(dt):
    return dt.astimezone().isoformat()


def at(*args):
    """10-17 のような書き方の時刻(args = (日, 時, 分) か (月, 日, 時, 分))"""
    if len(args) == 3:
        return datetime(2026, 10, *args)
    return datetime(2026, *args)


def rss_xml(entries):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>'
             '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">']
    for e in entries:
        vid, title, pub = e[:3]
        views = '<media:group><media:community><media:statistics views="%d"/></media:community></media:group>' % e[3] if len(e) > 3 else ""
        parts.append('<entry><yt:videoId>%s</yt:videoId><title>%s</title><published>%s</published>'
                     '<updated>%s</updated>%s</entry>' % (vid, title, iso(pub), iso(pub), views))
    parts.append("</feed>")
    return "".join(parts).encode("utf-8")


def watch(vd, ps, lbd, mf_extra=None):
    mf = {"liveBroadcastDetails": lbd}
    mf.update(mf_extra or {})
    pr = {"videoDetails": vd, "playabilityStatus": ps, "microformat": {"playerMicroformatRenderer": mf}}
    return '<html><body><script>var ytInitialPlayerResponse = %s;</script></body></html>' % json.dumps(pr, ensure_ascii=False)


def live_page(start, title="配信中"):
    return watch({"isLiveContent": True, "isLive": True, "lengthSeconds": "0", "title": title},
                 {"status": "OK"}, {"isLiveNow": True, "startTimestamp": iso(start)})


def upcoming_page(start, title="予定"):
    slate = {"liveStreamOfflineSlateRenderer": {"scheduledStartTime": str(int(start.timestamp()))}}
    ps = {"status": "LIVE_STREAM_OFFLINE",
          "liveStreamability": {"liveStreamabilityRenderer": {"offlineSlate": slate}}}
    return watch({"isLiveContent": True, "isUpcoming": True, "lengthSeconds": "0", "title": title}, ps,
                 {"startTimestamp": iso(start)})


def ended_page(start, end, length, title="終わった配信"):
    return watch({"isLiveContent": True, "lengthSeconds": str(length), "title": title},
                 {"status": "OK"}, {"startTimestamp": iso(start), "endTimestamp": iso(end)})


def just_ended_page(start, end, title="終わったばかり"):
    return watch({"isLiveContent": True, "lengthSeconds": "0", "title": title},
                 {"status": "LIVE_STREAM_OFFLINE"}, {"startTimestamp": iso(start), "endTimestamp": iso(end)})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Web:
    """取りに行く口の代わり。routes = URL -> (状態, 本文)。無い URL は 404。同時に何本来たかを数える"""

    def __init__(self, delay=0.0):
        self.routes, self.calls, self.delay = {}, [], delay
        self.lock = threading.Lock()
        self.active = self.max_active = 0

    def __call__(self, url, timeout):
        with self.lock:
            self.calls.append(url)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return self.routes.get(url, (404, b""))
        finally:
            with self.lock:
                self.active -= 1

    def count(self, url):
        return sum(1 for u in self.calls if u == url)


class StreamsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="streams-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.members = os.path.join(self.tmp, "members.json")
        self.write_members(MEMBERS)
        self.cache = os.path.join(self.tmp, "cache", "streams.json")
        self.web = Web()
        self.clock = Clock(NOW_TS)
        self.feeds = {}
        self.s = self.make()

    def make(self):
        return S.Streams(self.cache, members_path=self.members, fetch=self.web, clock=self.clock)

    def write_members(self, d):
        with open(self.members, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def add(self, cid, vid, pub, html, title="題名", views=None):
        """チャンネルの RSS に動画を 1 本足し、その動画のページを用意する"""
        self.feeds.setdefault(cid, []).append((vid, title, pub) + ((views,) if views is not None else ()))
        self.web.routes[S.RSS_URL % cid] = (200, rss_xml(self.feeds[cid]))
        self.web.routes[S.WATCH_URL % vid] = (200, html.encode("utf-8"))

    def ids(self, view):
        return [(sec["key"], [it["videoId"] for it in sec["items"]]) for sec in view["sections"]]

    def run_at(self, t):
        self.clock.t = t
        self.s.tick()

    # ---------- 読む・分ける ----------
    def test_rss_and_roster(self):
        entries = S.parse_rss(rss_xml([("v0000000001", "題", at(10, 17, 9, 0))]))
        self.assertEqual([e["videoId"] for e in entries], ["v0000000001"])
        self.assertEqual(entries[0]["title"], "題")
        self.assertEqual(set(self.s._roster), {CH_A, CH_D})   # JP と DEV_IS だけ・channel の無い人と EN は外す
        self.assertEqual(self.s._roster[CH_A], {"name": "テストA", "hex": "#445566"})   # 字幕の色 = subtitle
        self.assertEqual(self.s._roster[CH_D]["hex"], "#ABCDEF")

    def test_classify_states(self):
        n = ms(NOW)
        c = S.classify
        self.assertEqual(c(live_page(at(10, 17, 14, 0)), n)["state"], "live")
        up = c(upcoming_page(at(10, 17, 20, 0)), n)
        self.assertEqual((up["state"], up["startAt"]), ("upcoming", ms(at(10, 17, 20, 0))))
        je = c(just_ended_page(at(10, 17, 13, 0), at(10, 17, 14, 0)), n)
        self.assertEqual(je["state"], "justEnded")
        en = c(ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600), n)
        self.assertEqual((en["state"], en["duration"], en["endAt"]), ("ended", 3600, ms(at(10, 17, 10, 0))))
        # 出さない: プレミア(isLiveContent 偽で予定)・投稿動画・ショート・メンバー限定・削除
        premiere = watch({"isLiveContent": False, "isUpcoming": True, "title": "P"},
                         {"status": "LIVE_STREAM_OFFLINE"}, {"startTimestamp": iso(at(10, 17, 20, 0))})
        self.assertEqual(c(premiere, n)["state"], "skip")
        self.assertEqual(c(watch({"isLiveContent": False, "lengthSeconds": "600"}, {"status": "OK"}, {}), n)["state"], "skip")
        self.assertEqual(c(watch({"isLiveContent": False, "lengthSeconds": "30"}, {"status": "OK"}, {},
                                 {"isShortsEligible": True}), n)["state"], "skip")
        members = watch({"isLiveContent": True, "title": "M"}, {"status": "LOGIN_REQUIRED", "reason": "メンバー限定"},
                        {"startTimestamp": iso(at(10, 17, 14, 0))})
        self.assertEqual(c(members, n)["state"], "skip")
        self.assertEqual(c(watch({}, {"status": "ERROR", "reason": "削除"}, {}), n)["state"], "skip")
        self.assertIsNone(c("<html>no player</html>", n))   # 読めない = 取り直す

    # ---------- 範囲・段・並び ----------
    def test_sections_ranges_and_order(self):
        A = CH_A
        self.add(A, "v0000000001", at(10, 17, 14, 0), live_page(at(10, 17, 14, 0)))
        self.add(A, "v0000000002", at(10, 17, 17, 0), upcoming_page(at(10, 17, 17, 0)))
        self.add(A, "v0000000003", at(10, 17, 9, 0), ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600))
        self.add(A, "v0000000004", at(10, 16, 22, 0), ended_page(at(10, 16, 22, 0), at(10, 16, 23, 0), 3600))
        # 前日より前に始まって前日に終わった長い配信: 昨日の一番下
        self.add(A, "v0000000005", at(10, 15, 20, 0), ended_page(at(10, 15, 20, 0), at(10, 16, 10, 0), 50400))
        self.add(A, "v0000000006", at(10, 15, 20, 0), ended_page(at(10, 15, 20, 0), at(10, 15, 23, 0), 10800))  # 前日より前に終わった
        self.add(A, "v0000000007", at(10, 18, 2, 0), upcoming_page(at(10, 18, 2, 0)))   # 今日の 24 時より後・12 時間の中
        self.add(A, "v0000000008", at(10, 18, 20, 0), upcoming_page(at(10, 18, 20, 0)))  # 12 時間の外
        self.add(A, "v0000000009", at(10, 16, 23, 30), premiere_page_for(at(10, 16, 23, 30)))
        self.add(A, "v0000000010", at(10, 17, 10, 0), watch({"isLiveContent": False, "lengthSeconds": "600"}, {"status": "OK"}, {}))
        self.add(A, "v0000000011", at(10, 17, 11, 0), members_page(at(10, 17, 11, 0)))
        self.add(A, "v0000000012", at(10, 17, 12, 0), watch({}, {"status": "ERROR"}, {}))
        self.run_at(NOW_TS)
        view = self.s.view()
        self.assertEqual(self.ids(view), [
            ("live", ["v0000000001", "v0000000002", "v0000000007"]),
            ("today", ["v0000000003"]),
            ("yesterday", ["v0000000004", "v0000000005"]),
        ])
        self.assertEqual(view["sections"][0]["label"], "ライブ中・これから")
        self.assertEqual(view["sections"][0]["count"], 3)
        first = view["sections"][0]["items"][0]
        self.assertEqual(first["hex"], "#445566")
        self.assertEqual(first["streamer"], "テストA")
        self.assertEqual(first["url"], S.WATCH_URL % "v0000000001")

    def test_empty_sections_are_not_shown(self):
        self.add(CH_A, "v0000000001", at(10, 17, 9, 0), ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600))
        self.run_at(NOW_TS)
        self.assertEqual([sec["key"] for sec in self.s.view()["sections"]], ["today"])

    def test_checking_until_read_then_read(self):
        self.web.routes.pop(S.WATCH_URL % "v0000000001", None)
        self.add(CH_A, "v0000000001", at(10, 17, 9, 0), "")
        self.web.routes[S.WATCH_URL % "v0000000001"] = (503, b"")   # まだ読めない
        self.run_at(NOW_TS)
        v = self.s.view()
        self.assertEqual(v["sections"][0]["items"][0]["state"], "checking")
        self.assertIsNone(v["error"])                                 # 一部の失敗は error にしない
        self.web.routes[S.WATCH_URL % "v0000000001"] = (200, ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600).encode())
        self.run_at(NOW_TS + 61)                                      # 確かめ中は 60 秒後に取り直す(見回りの間)
        self.assertEqual(self.s.view()["sections"][0]["items"][0]["state"], "ended")

    def test_skipped_is_not_read_again(self):
        self.add(CH_A, "v0000000011", at(10, 17, 11, 0), members_page(at(10, 17, 11, 0)))
        self.run_at(NOW_TS)
        self.run_at(NOW_TS + 300)
        self.assertEqual(self.web.count(S.WATCH_URL % "v0000000011"), 1)
        self.assertEqual(self.s.view()["sections"], [])

    def test_old_new_items_are_not_read(self):
        self.add(CH_A, "v0000000021", at(10, 1, 9, 0), live_page(at(10, 1, 9, 0)))   # 2 日より前 = 範囲の外
        self.run_at(NOW_TS)
        self.assertEqual(self.web.count(S.WATCH_URL % "v0000000021"), 0)

    def test_old_waiting_room_with_no_views_is_read(self):
        """何日も前に立てた予定の枠(再生数 0)は古くても読む = 初めて開いた日にも出る"""
        self.add(CH_A, "v0000000022", at(10, 1, 9, 0), upcoming_page(NOW + timedelta(hours=1)), views=0)
        self.add(CH_A, "v0000000023", at(10, 1, 9, 0), live_page(at(10, 1, 9, 0)), views=1200)
        self.run_at(NOW_TS)
        self.assertEqual(self.web.count(S.WATCH_URL % "v0000000022"), 1)
        self.assertEqual(self.web.count(S.WATCH_URL % "v0000000023"), 0)
        self.assertIn("v0000000022", [v for _k, vs in self.ids(self.s.view()) for v in vs])

    def test_tries_then_skip_for_unreadable_page(self):
        self.add(CH_A, "v0000000031", at(10, 17, 9, 0), "<html>no json</html>")
        self.run_at(NOW_TS)
        self.run_at(NOW_TS + 300)
        self.assertEqual(self.s.view()["sections"][0]["items"][0]["state"], "checking")
        self.run_at(NOW_TS + 600)
        self.assertEqual(self.s.view()["sections"], [])

    # ---------- 読み直し ----------
    def test_reread_while_screen_open_only(self):
        url = S.WATCH_URL % "v0000000041"
        self.add(CH_A, "v0000000041", at(10, 17, 14, 0), live_page(at(10, 17, 14, 0)))
        self.run_at(NOW_TS)
        self.s.view()                                                  # 画面が開いた(t0)
        self.web.routes[url] = (200, ended_page(at(10, 17, 14, 0), at(10, 17, 15, 0), 3600).encode())
        self.run_at(NOW_TS + 95)                                       # 開いている間・90 秒過ぎた = 読み直す
        self.assertEqual(self.web.count(url), 2)
        self.assertEqual(self.s.view()["sections"][0]["items"][0]["state"], "ended")
        self.run_at(NOW_TS + 250)                                      # 閉じた(最後に view が読まれて 2 分過ぎた)
        self.assertEqual(self.web.count(url), 2)
        self.run_at(NOW_TS + 300)                                      # 5 分おきの見回り
        self.assertEqual(self.web.count(url), 2)                       # ended は読み直さない

    def test_upcoming_far_away_not_reread_when_open(self):
        url = S.WATCH_URL % "v0000000051"
        self.add(CH_A, "v0000000051", at(10, 17, 20, 0), upcoming_page(at(10, 17, 20, 0)))
        self.run_at(NOW_TS)
        self.s.view()
        self.run_at(NOW_TS + 95)
        self.assertEqual(self.web.count(url), 1)                       # 開始まで 10 分より先は読み直さない

    # ---------- 取れないとき ----------
    def test_rejected_waits_ten_minutes_and_keeps_list(self):
        self.add(CH_A, "v0000000001", at(10, 17, 9, 0), ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600))
        self.run_at(NOW_TS)
        self.assertEqual(len(self.s.view()["sections"][0]["items"]), 1)
        self.web.routes[S.RSS_URL % CH_A] = (429, b"")
        self.run_at(NOW_TS + 300)                                      # 見回り = 断られる
        v = self.s.view()
        self.assertEqual(v["error"]["listAt"], v["updatedAt"])
        self.assertIn("の一覧を表示中", v["error"]["message"])
        self.assertEqual(len(v["sections"][0]["items"]), 1)            # 前の一覧は残す
        calls = len(self.web.calls)
        self.run_at(NOW_TS + 300 + 300)                                # まだ 10 分の中
        self.assertEqual(len(self.web.calls), calls)
        self.assertEqual(self.s.refresh(), {"ok": False, "waitSec": 300})
        self.run_at(NOW_TS + 300 + 600)
        self.assertGreater(len(self.web.calls), calls)

    def test_forbidden_on_page_also_blocks(self):
        self.add(CH_A, "v0000000001", at(10, 17, 9, 0), "")
        self.web.routes[S.WATCH_URL % "v0000000001"] = (403, b"")
        self.run_at(NOW_TS)
        self.assertEqual(self.s.refresh(), {"ok": False, "waitSec": 600})

    def test_partial_failure_is_silent(self):
        self.add(CH_D, "v0000000061", at(10, 17, 9, 0), ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600))
        self.web.routes[S.RSS_URL % CH_A] = (500, b"")
        self.run_at(NOW_TS)
        v = self.s.view()
        self.assertIsNone(v["error"])
        self.assertEqual(self.ids(v), [("today", ["v0000000061"])])

    def test_total_failure_on_first_time(self):
        self.run_at(NOW_TS)                                            # 何も routes が無い = 全部 404
        v = self.s.view()
        self.assertTrue(v["first"])
        self.assertEqual(v["error"]["message"], S.FIRST_MSG)
        self.assertIsNone(v["updatedAt"])

    def test_total_failure_with_previous_list(self):
        self.add(CH_D, "v0000000061", at(10, 17, 9, 0), ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600))
        self.run_at(NOW_TS)
        self.web.routes.pop(S.RSS_URL % CH_D)
        self.run_at(NOW_TS + 300)
        v = self.s.view()
        self.assertFalse(v["first"])
        self.assertEqual(v["error"]["listAt"], v["updatedAt"])
        self.assertIn("新しい一覧を取れませんでした", v["error"]["message"])
        self.assertEqual(self.ids(v), [("today", ["v0000000061"])])

    def test_startup_reads_saved_list(self):
        self.add(CH_D, "v0000000061", at(10, 17, 9, 0), ended_page(at(10, 17, 9, 0), at(10, 17, 10, 0), 3600))
        self.run_at(NOW_TS)
        before = self.s.view()
        again = self.make()                                            # 起動し直し(覚えの JSON から)
        v = again.view()
        self.assertEqual(self.ids(v), self.ids(before))
        self.assertEqual(v["updatedAt"], before["updatedAt"])
        self.assertEqual(self.web.count(S.RSS_URL % CH_D), 1)          # 起動では取りに行かない

    def test_refresh_forces_a_poll(self):
        self.run_at(NOW_TS)
        self.clock.t = NOW_TS + 10
        self.assertEqual(self.s.refresh(), {"ok": True})
        calls = self.web.count(S.RSS_URL % CH_D)
        self.s.tick()
        self.assertEqual(self.web.count(S.RSS_URL % CH_D), calls + 1)

    def test_at_most_four_at_once(self):
        members = {"version": 2, "groups": [{"name": "0期", "branch": "JP", "members": [
            {"id": "m%d" % i, "name": "名%d" % i, "hex": "#123456", "channel": "UC" + str(i) * 22} for i in range(9)]}]}
        self.write_members(members)
        self.web = Web(delay=0.05)
        for i in range(9):
            self.web.routes[S.RSS_URL % ("UC" + str(i) * 22)] = (200, rss_xml([]))
        self.s = self.make()
        self.run_at(NOW_TS)
        self.assertLessEqual(self.web.max_active, S.WORKERS)
        self.assertGreaterEqual(self.web.max_active, 2)
        self.assertEqual(self.web.count(S.RSS_URL % ("UC" + "0" * 22)), 1)

    def test_lookup(self):
        self.add(CH_A, "v0000000071", at(10, 17, 14, 0), live_page(at(10, 17, 14, 0)))
        self.run_at(NOW_TS)
        self.assertEqual(self.s.lookup("v0000000071")["state"], "live")
        self.assertIsNone(self.s.lookup("v0000000099"))
        self.assertIsNone(self.s.lookup("../x"))

    def test_tick_does_nothing_while_busy_and_thread_loop_is_safe(self):
        self.s.start()
        self.s.stop()
        self.s.tick()
        self.assertIsNotNone(self.s.view())


def premiere_page_for(start):
    """プレミア公開(isLiveContent が偽なのに予定)"""
    return watch({"isLiveContent": False, "isUpcoming": True, "title": "プレミア"},
                 {"status": "LIVE_STREAM_OFFLINE"}, {"startTimestamp": iso(start)})


def members_page(start):
    return watch({"isLiveContent": True, "title": "メン限"}, {"status": "LOGIN_REQUIRED", "reason": "メンバー限定"},
                 {"startTimestamp": iso(start)})


if __name__ == "__main__":
    unittest.main()
