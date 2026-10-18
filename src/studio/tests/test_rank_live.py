"""① 探す の「配信中」のタブ: 配信中・これからの予定の取得(rank.live_list)と GET /api/rank/live のテスト。外へは繋がない。
実行(リポジトリ直下): python -m unittest src/studio/tests/test_rank_live.py"""
import http.client
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ["STUDIO_FAKE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # ツールのフォルダ(studio/)
import startup  # noqa: E402  (src を sys.path に足し、スタジオのフォルダを ytt/studio_env に知らせる)
from ytt import studio_env  # noqa: E402
import serve  # noqa: E402
from human.find import rank  # noqa: E402

CH_A, CH_B, CH_C = "UC" + "a" * 22, "UC" + "b" * 22, "UC" + "c" * 22
NOW = 1_800_000_000.0   # 2027-01-15 08:00 UTC(固定の「今」)
BOTH = ["hololive", "other"]   # 事務所を両方とも明示する(省くとホロライブだけ = rank.DEFAULT_GROUPS)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vid(n):
    return ("v%010d" % n)[:11]


def item(n, kind, ch=CH_A, title=None, **ld):
    """videos.list の1件(偽物)"""
    it = {"id": vid(n), "snippet": {"title": title or "配信 %d" % n, "channelId": ch, "channelTitle": "チャンネル" + ch[2],
                                    "liveBroadcastContent": kind, "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/%s/mqdefault_live.jpg" % vid(n)}}},
          "contentDetails": {}}
    if ld:
        it["liveStreamingDetails"] = ld
    return it


class FakeYT:
    """yt_get の偽物: チャンネルごとのアップロード一覧と、動画 ID → videos.list の1件。呼ばれた回数を数える"""

    def __init__(self, uploads, videos):
        self.uploads, self.videos, self.calls = uploads, videos, []
        self.fail = None

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        if self.fail:
            raise self.fail
        if path == "playlistItems":
            ids = self.uploads.get("UC" + params["playlistId"][2:], [])
            return {"items": [{"contentDetails": {"videoId": i}} for i in ids[:params["maxResults"]]]}
        if path == "videos":
            return {"items": [self.videos[i] for i in params["id"].split(",") if i in self.videos]}
        raise AssertionError(path)

    def count(self, path):
        return sum(1 for p, _ in self.calls if p == path)


class TestLiveList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        studio_env.set_home(self.tmp)
        rank.put_registry({"agencies": [
            {"id": "aaa", "name": "事務所A", "channels": [{"ref": CH_A}, {"ref": CH_B}, {"ref": "@notyet"}]},
            {"id": "hololive", "name": "ホロライブ", "channels": [{"ref": CH_C}]},
        ]})
        rank._cache.clear()
        rank._live_none.clear()
        long_title = "長い" * 300
        vids = [
            item(1, "live", actualStartTime=iso(NOW - 3600), concurrentViewers="1200"),
            item(2, "live", ch=CH_B, actualStartTime=iso(NOW - 600), concurrentViewers="9000"),
            item(3, "live", actualStartTime=iso(NOW - 60)),                                           # 視聴者数を隠している
            item(4, "upcoming", scheduledStartTime=iso(NOW + 5 * 3600)),
            item(5, "upcoming", ch=CH_B, scheduledStartTime=iso(NOW + 35 * 60)),
            item(6, "upcoming", scheduledStartTime=iso(NOW + 30 * 3600)),                            # 24 時間より先 → 出さない
            item(7, "upcoming", scheduledStartTime=iso(NOW - 2 * 3600)),                             # 予定を過ぎたがまだ始まらない → 出す
            item(8, "upcoming", scheduledStartTime=iso(NOW - 10 * 3600)),                            # 立てたまま使わなかった枠 → 出さない
            item(9, "none"),                                                                          # アーカイブ
            item(10, "live", title="【メン限】雑談", actualStartTime=iso(NOW - 100), concurrentViewers="50"),
            item(11, "live", ch=CH_C, title=long_title, actualStartTime=iso(NOW - 100), concurrentViewers="10"),
            item(12, "live", actualStartTime=iso(NOW - 5), actualEndTime=iso(NOW - 1)),               # もう終わった
        ]
        vids[10]["snippet"]["thumbnails"]["medium"]["url"] = "https://evil.example.com/x.jpg"     # CSP に合わないサムネイルは出さない
        vids[3]["contentDetails"]["contentRating"] = {"ytRating": "ytAgeRestricted"}
        self.videos = {v["id"]: v for v in vids}
        self.fake = FakeYT({CH_A: [vid(n) for n in (1, 3, 4, 6, 7, 8, 9, 10, 12)], CH_B: [vid(2), vid(5)], CH_C: [vid(11), vid(1)]}, self.videos)
        self.p = patch.object(rank, "yt_get", self.fake)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_split_order_and_fields(self):
        r = rank.live_list(BOTH, now=NOW)
        self.assertEqual([x["id"] for x in r["live"]], [vid(2), vid(1), vid(10), vid(11), vid(3)])   # 視聴者数の多い順・隠している配信は後ろ
        self.assertEqual([x["id"] for x in r["upcoming"]], [vid(7), vid(5), vid(4)])                  # 始まる時刻の早い順(24 時間より先・古い枠は除く)
        a = r["live"][0]
        self.assertEqual((a["state"], a["viewers"], a["agency"], a["agencyName"], a["start"]), ("live", 9000, "other", "その他", int((NOW - 600) * 1000)))
        self.assertEqual(a["url"], "https://www.youtube.com/watch?v=" + vid(2))
        self.assertTrue(a["thumb"].startswith("https://i.ytimg.com/"))
        self.assertIsNone(r["live"][-1]["viewers"])
        up = next(x for x in r["upcoming"] if x["id"] == vid(5))
        self.assertEqual((up["state"], up["start"], up["viewers"]), ("upcoming", int((NOW + 35 * 60) * 1000), None))
        self.assertEqual(next(x for x in r["live"] if x["id"] == vid(10))["blocked"], "members")
        self.assertEqual(next(x for x in r["upcoming"] if x["id"] == vid(4))["blocked"], "age")
        self.assertEqual(r["live"][0]["blocked"], "")
        long = next(x for x in r["live"] if x["id"] == vid(11))
        self.assertEqual((len(long["title"]), long["thumb"], long["agency"]), (rank.LIVE_TITLE_MAX, "", "hololive"))
        self.assertEqual(sum(1 for x in r["live"] + r["upcoming"] if x["id"] == vid(1)), 1)   # 2つのチャンネルに出ても1回だけ(最初の事務所)
        self.assertEqual((r["unresolved"], r["channels"], r["cached"]), (1, 3, False))
        self.assertEqual(self.fake.count("playlistItems"), 3)
        self.assertTrue(all(p["maxResults"] == rank.LIVE_PAGE for path, p in self.fake.calls if path == "playlistItems"))
        self.assertEqual(self.fake.count("videos"), 1)   # 50 本までは 1 回
        self.assertEqual(r["quota"], 0)   # yt_get を偽物に替えたので数えない(本物は 1 回 1 ユニット)

    def test_agency_filter(self):
        r = rank.live_list("hololive", now=NOW)
        self.assertEqual(([x["id"] for x in r["live"]], r["upcoming"]), ([vid(1), vid(11)], []))
        self.assertEqual(r["agencies"], [{"id": "hololive", "name": "ホロライブ"}])
        r = rank.live_list(["other"], now=NOW)   # ホロライブ以外は「その他」にまとまる
        self.assertEqual(r["agencies"], [{"id": "other", "name": "その他"}])
        self.assertNotIn(vid(11), [x["id"] for x in r["live"]])
        r = rank.live_list("aaa", now=NOW)       # 登録簿の事務所の id でも(その他に入る事務所なら)選べる
        self.assertEqual(r["agencies"], [{"id": "other", "name": "その他"}])
        with self.assertRaises(rank.ApiError) as cm:
            rank.live_list("nothere", now=NOW)
        self.assertEqual(cm.exception.code, "no_agency")
        self.assertEqual([x["id"] for x in rank.live_list(None, now=NOW)["live"]], [vid(1), vid(11)])   # 省くとホロライブだけ(その他の vid(2)・vid(10) は入らない)
        self.assertEqual([a["id"] for a in rank.validate_search({"start": "2026-09-01", "end": "2026-09-30"})["agencies"]], ["hololive"])
        self.assertEqual(rank.parse_live_agencies("A A, b<script>,," + "x" * 50), ["aa", "bscript", "x" * 30])   # 文字の検査と長さ
        self.assertEqual(len(rank.parse_live_agencies(",".join("a%d" % i for i in range(100)))), rank.MAX_AGENCIES)

    def test_region_filter(self):
        """地域: 既定は JP と不明。手の指定が名簿より先。選んだ地域に当てはまらない物は探さない。各行に region が付く"""
        rank.put_registry({"agencies": [
            {"id": "aaa", "name": "事務所A", "channels": [{"ref": CH_A, "region": "EN"}, {"ref": CH_B}, {"ref": "@notyet"}]},
            {"id": "hololive", "name": "ホロライブ", "channels": [{"ref": CH_C}]},
        ]})
        rank.put_registry(dict(rank.load_registry()))   # 保存した形でも region が残る
        self.assertEqual(rank.load_registry()["agencies"][0]["channels"][0]["region"], "EN")
        self.assertNotIn("region", rank.load_registry()["agencies"][0]["channels"][1])
        table = {CH_B: "JP", CH_C: "ID"}
        with patch.object(rank._live, "channel_regions", return_value=table):
            r = rank.live_list(BOTH, now=NOW)            # 既定 = JP と不明: A(手の EN)は外れ、B(JP)だけ。C(ID)も外れる
            self.assertEqual((r["channels"], sorted(x["id"] for x in r["live"])), (1, [vid(2)]))
            self.assertEqual(r["live"][0]["region"], "JP")
            r = rank.live_list(BOTH, now=NOW,regions="EN,ID")
            self.assertEqual(sorted(x["id"] for x in r["live"]), sorted([vid(1), vid(10), vid(11), vid(3)]))
            self.assertEqual({x["id"]: x["region"] for x in r["live"]}[vid(11)], "ID")
            self.assertEqual({x["id"]: x["region"] for x in r["live"]}[vid(1)], "EN")   # 2 つのチャンネルに出る動画は先のチャンネルの地域
            with self.assertRaises(rank.ApiError) as cm:
                rank.live_list(BOTH, now=NOW,regions=["unknown"])   # 不明のチャンネルは「@notyet」(未解決)だけ = 解決済みの物は全部外れる
            self.assertEqual(cm.exception.code, "no_region")
            with self.assertRaises(rank.ApiError) as cm:
                rank.live_list(BOTH, now=NOW,regions="")
            self.assertEqual(cm.exception.code, "no_region")
        with patch.object(rank._live, "channel_regions", return_value={CH_B: "EN", CH_C: "ID"}):
            with self.assertRaises(rank.ApiError) as cm:
                rank.live_list(BOTH, now=NOW,regions="JP")   # 解決済みはあるが、選んだ地域に当てはまる物が無い
        self.assertEqual(cm.exception.code, "no_region")

    def test_region_filter_changes_cache_key(self):
        with patch.object(rank._live, "channel_regions", return_value={CH_B: "JP", CH_C: "ID"}):
            a = rank.live_list(BOTH, now=NOW,regions="JP")
            b = rank.live_list(None, now=NOW + 1, regions="ID")
        self.assertFalse(b["cached"])
        self.assertNotEqual([x["id"] for x in a["live"]], [x["id"] for x in b["live"]])

    def test_search_uses_regions_and_groups(self):
        """過去の検索も同じ絞り込み: 結果は「ホロライブ」「その他」にまとまり、各行に region が付く。regions の既定は JP と不明"""
        rank.put_registry({"agencies": [
            {"id": "aaa", "name": "事務所A", "channels": [{"ref": CH_A, "region": "EN"}, {"ref": CH_B}]},
            {"id": "hololive", "name": "ホロライブ", "channels": [{"ref": CH_C}]},
        ]})
        pub = {CH_A: vid(21), CH_B: vid(22), CH_C: vid(23)}

        def fake(path, params):
            if path == "playlistItems":
                ch = "UC" + params["playlistId"][2:]
                return {"items": [{"contentDetails": {"videoId": pub[ch], "videoPublishedAt": "2026-09-10T00:00:00Z"}}]}
            return {"items": [{"id": i, "snippet": {"title": "t" + i, "channelId": "x", "publishedAt": "2026-09-10T00:00:00Z"}, "statistics": {"viewCount": "5"},
                               "contentDetails": {"duration": "PT1H"}, "liveStreamingDetails": {"actualStartTime": "2026-09-10T00:00:00Z", "actualEndTime": "2026-09-10T01:00:00Z"}}
                              for i in params["id"].split(",")]}

        def run(**k):
            job = {"cancel": False, "progress": 0.0}
            rank.run_search(job, rank.validate_search(dict({"start": "2026-09-01", "end": "2026-09-30", "agencies": BOTH}, **k)))
            return job
        with patch.object(rank, "yt_get", fake), patch.object(rank._live, "channel_regions", return_value={CH_B: "JP", CH_C: "ID"}):
            j = run()   # 既定 = JP と不明: A(手の EN)・C(ID)は外れ、B(JP)だけ。事務所 aaa は「その他」
            self.assertEqual(j["state"], "done", j)
            self.assertEqual([(a["id"], a["name"], [(i["id"], i["region"]) for i in a["items"]]) for a in j["result"]["agencies"]], [("hololive", "ホロライブ", []), ("other", "その他", [(vid(22), "JP")])])
            j = run(regions=["EN", "ID"], agencies=["hololive", "other"])
            self.assertEqual([(a["id"], [(i["id"], i["region"]) for i in a["items"]]) for a in j["result"]["agencies"]], [("hololive", [(vid(23), "ID")]), ("other", [(vid(21), "EN")])])
            with self.assertRaises(rank.ApiError) as cm:
                rank.validate_search({"start": "2026-09-01", "end": "2026-09-30", "regions": []})
            self.assertEqual(cm.exception.code, "no_region")

    def test_parse_regions(self):
        self.assertEqual(rank.parse_regions(None), ["JP", "unknown"])
        self.assertEqual(rank.parse_regions("jp, EN,unknown,xx,JP"), ["JP", "EN", "unknown"])
        self.assertEqual(rank.parse_regions(["ID", 5, "Unknown"]), ["ID", "unknown"])
        self.assertEqual(rank.parse_regions(""), [])

    def test_cache_does_not_call_out(self):
        rank.live_list(BOTH, now=NOW)
        n = len(self.fake.calls)
        r = rank.live_list(BOTH, now=NOW + 30)              # 60 秒の間は外へ聞かない
        self.assertEqual((len(self.fake.calls), r["cached"]), (n, True))
        r = rank.live_list(BOTH, now=NOW + 61)              # 過ぎたら状態だけ聞き直す(一覧の見回りは 20 分覚える)
        self.assertFalse(r["cached"])
        self.assertEqual(self.fake.count("playlistItems"), 3)
        last = self.fake.calls[-1]
        self.assertEqual(last[0], "videos")
        asked = set(last[1]["id"].split(","))
        self.assertNotIn(vid(9), asked)    # 配信でない(アーカイブ・終わった)と分かった動画は聞き直さない
        self.assertNotIn(vid(12), asked)
        self.assertIn(vid(1), asked)
        rank.live_list("hololive", now=NOW + 62)                  # 事務所の組み合わせが違えば別に覚える(見回りはチャンネルごとに覚えたものを使う)
        self.assertEqual(self.fake.count("playlistItems"), 3)

    def test_errors(self):
        for err in (rank.ApiError("no_key", "APIキーが未設定です(右上の「APIキー」から設定してください)", 400),
                    rank.ApiError("quota", "YouTube APIの1日の利用上限に達しました", 429)):
            rank._cache.clear()
            self.fake.fail = err
            with self.assertRaises(rank.ApiError) as cm:
                rank.live_list(BOTH, now=NOW)
            self.assertEqual((cm.exception.code, cm.exception.message), (err.code, err.message))
        rank._cache.clear()
        self.fake.fail = rank.ApiError("network", "YouTube APIに接続できません", 502)   # 全部のチャンネルが読めない → 空の一覧ではなく失敗
        with self.assertRaises(rank.ApiError) as cm:
            rank.live_list(BOTH, now=NOW)
        self.assertEqual(cm.exception.code, "network")
        self.fake.fail = None
        rank.put_registry({"agencies": [{"id": "zzz", "name": "空", "channels": [{"ref": "@pending"}]}]})
        with self.assertRaises(rank.ApiError) as cm:
            rank.live_list(BOTH, now=NOW)
        self.assertEqual(cm.exception.code, "no_channels")

    def test_some_channels_fail(self):
        real = self.fake.__call__

        def flaky(path, params):
            if path == "playlistItems" and params["playlistId"] == "UU" + CH_B[2:]:
                raise rank.ApiError("not_found", "見つかりません", 404)
            return real(path, params)
        with patch.object(rank, "yt_get", flaky):
            r = rank.live_list(BOTH, now=NOW)
        self.assertEqual(len(r["warnings"]), 1)
        self.assertNotIn(vid(2), [x["id"] for x in r["live"]])

    def test_live_row_rejects_bad_input(self):
        self.assertIsNone(rank.live_row({"id": "bad id"}, NOW))
        self.assertIsNone(rank.live_row({"id": vid(1), "snippet": {"liveBroadcastContent": "upcoming"}}, NOW))   # 予定の時刻が無い
        r = rank.live_row({"id": vid(1), "snippet": {"liveBroadcastContent": "live", "title": 5, "channelId": "x"}, "liveStreamingDetails": {"concurrentViewers": "abc"}}, NOW)
        self.assertEqual((r["title"], r["channelId"], r["viewers"], r["start"]), ("5", "", None, 0))


class TestFakeMode(unittest.TestCase):
    """疑似モード(STUDIO_FAKE=1)でも「配信中」が出る(画面の確かめ・見本用)"""

    def test_fake_has_live(self):
        tmp = tempfile.mkdtemp()
        try:
            studio_env.set_home(tmp)
            rank._cache.clear()
            rank._live_none.clear()
            rank.put_registry({"agencies": [{"id": "f", "name": "疑似", "channels": [{"ref": "UC" + ("%022d" % i)} for i in range(30)]}]})
            r = rank.live_list(BOTH)
            self.assertTrue(r["live"] and r["upcoming"], r)
            self.assertTrue(all(x["start"] <= (time.time() + rank.LIVE_AHEAD) * 1000 for x in r["upcoming"]))
            self.assertTrue(any(x["blocked"] == "members" for x in r["live"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestHttp(unittest.TestCase):
    """GET /api/rank/live(疑似モードの実サーバー)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        serve.init(cls.tmp)
        rank.put_registry({"agencies": [{"id": "f", "name": "疑似", "channels": [{"ref": "UC" + ("%022d" % i)} for i in range(30)]}]})
        rank._cache.clear()
        cls.srv, cls.port = serve.make_server(0)
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Host": host or "127.0.0.1:%d" % self.port})
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def test_get(self):
        st, d = self.get("/api/rank/live?agencies=hololive,other")
        self.assertEqual(st, 200, d)
        self.assertTrue({"live", "upcoming", "agencies", "warnings", "quota", "checkedAt", "cached"} <= set(d))
        st, d2 = self.get("/api/rank/live?agencies=hololive,other")
        self.assertEqual((st, d2["cached"], d2["live"]), (200, True, d["live"]))
        st, e = self.get("/api/rank/live?agencies=nothere")
        self.assertEqual((st, e["error"]), (400, "no_agency"))
        st, _ = self.get("/api/rank/live", host="evil.example.com")
        self.assertEqual(st, 403)


class TestResolveAndRetry(unittest.TestCase):
    """8b-1: ハンドルの解決で通信の失敗を「見つかりません」と書かない / 8c-1: やり直しは今の登録簿で / 数えと見出しのキー"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        studio_env.set_home(self.tmp)
        rank.put_registry({"agencies": [{"id": "aaa", "name": "事務所A", "channels": [{"ref": "@abc"}]}]})
        rank._cache.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_handle_network_failure_stays_pending(self):
        from ytt.errors import ApiError
        with patch.object(rank, "yt_get", side_effect=ApiError("network", rank.NET_MSG, 502)):
            r = rank.resolve("aaa")
        c = r["registry"]["agencies"][0]["channels"][0]
        self.assertEqual((c["status"], r["resolved"]), ("pending", 0))
        self.assertIn("通信", c["note"])
        self.assertNotIn("見つかりません", c["note"])
        with patch.object(rank, "yt_get", return_value={"items": []}):   # 引けたが無い = 本当に見つからない
            c = rank.resolve("aaa")["registry"]["agencies"][0]["channels"][0]
        self.assertEqual((c["status"], "見つかりません" in c["note"]), ("error", True))

    def test_board_retry_validates_again_with_current_registry(self):
        from flow import board as B
        b = B.Board()
        rank.attach_board(b)
        req = {"start": "2026-09-01", "end": "2026-09-30", "agencies": ["other"]}
        spec = rank.validate_search(req)
        self.assertEqual(spec["req"], req)
        self.assertEqual([c["ref"] for c in spec["agencies"][0]["channels"]], ["@abc"])
        rank._jobs["s1"] = {"id": "s1", "state": "cancelled", "phase": "", "progress": 0.0, "cancel": True, "error": "", "result": None, "created": 1, "spec": spec}
        self.addCleanup(rank._jobs.clear)
        rank.put_registry({"agencies": [{"id": "aaa", "name": "事務所A", "channels": [{"ref": "@abc"}, {"ref": "@later"}]}]})   # 検索のあとで足したチャンネル
        got = []
        with patch.object(rank, "_start_search", lambda s: got.append(s) or {"id": "s2", "state": "running", "phase": "", "progress": 0.0, "cancel": False, "error": "", "created": 2}):
            b.refresh()
            b.retry("se:s1")
        self.assertEqual([c["ref"] for c in got[0]["agencies"][0]["channels"]], ["@abc", "@later"])


if __name__ == "__main__":
    unittest.main()
