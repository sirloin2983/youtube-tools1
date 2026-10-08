# -*- coding: utf-8 -*-
"""分析と日報(src/analytics)のテスト。本物のチャンネルの数字は使わない(リポジトリは Public)。make_raw が規則どおりに伸びる架空のチャンネルを作る。

    py -3.10 -m unittest src/analytics/tests/test_analytics.py
"""
import datetime
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from analytics import bridge, calc, data, render, service, timeutil as T  # noqa: E402

UTC = T.UTC
DAY = datetime.timedelta(days=1)


def cum(h, a, tau=40.0):
    """架空の動画の、公開から h 時間の累計 EV"""
    return a * (1 - math.exp(-max(0.0, h) / tau)) if h > 0 else 0.0


def make_raw(fetched="2026-10-07T23:10:00Z", start="2026-05-01", per_day=3, hours=(3, 9, 12), amp=20000.0, backlog=3000.0,
             hits=(), long_every=7, title=None):
    """架空の raw。毎日 per_day 本のショート(公開は日本時間の hours 時)。1 本の累計は amp × (1 − e^(−h/40))。hits = [(何本目, 倍率)]"""
    f = T.parse_utc(fetched)
    d0 = datetime.date.fromisoformat(start)
    videos, vdays = [], {}
    per_pt = {}
    hit = dict(hits)
    i = 0
    day = d0
    while True:
        for k in range(per_day):
            pub = datetime.datetime.combine(day, datetime.time(hours[k % len(hours)]), T.JST).astimezone(UTC)
            if pub >= f:
                break
            vid = "v%05d" % i
            a = amp * hit.get(i, 1.0)
            rows = []
            d = T.to_pt(pub).date()
            while True:
                s, e = T.pt_day_start_utc(d), T.pt_day_start_utc(d + DAY)
                if s >= f:
                    break
                e = min(e, f)
                ev = cum((e - pub).total_seconds() / 3600, a) - cum((s - pub).total_seconds() / 3600, a)
                rows.append([int(d.strftime("%Y%m%d")), round(ev), round(ev * 2.2)])
                per_pt[d] = per_pt.get(d, 0.0) + ev
                d += DAY
            tot = sum(r[1] for r in rows)
            videos.append({"id": vid, "title": title(i) if title else "【見出し%d】本文【#さくらみこ ／#みこなま ／#ホロライブ ／#shorts 】" % i,
                           "published": pub.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "length": 20 + i % 40, "short": True,
                           "privacy": "VIDEO_PRIVACY_PUBLIC", "ev": tot, "views": tot * 2.2, "vtr": 50 + (i * 7) % 40, "awp": 90, "rev": tot * 0.2, "subs": 1})
            if (f - pub).days <= 92:
                vdays[vid] = rows
            i += 1
        day += DAY
        if datetime.datetime.combine(day, datetime.time(0), T.JST) > f:
            break
    daily, total = [], []
    d = d0 - DAY
    last = T.to_pt(f).date()
    while d <= last:
        sev = per_pt.get(d, 0.0) + backlog
        n = int(d.strftime("%Y%m%d"))
        daily.append({"DAY": n, "CREATOR_CONTENT_TYPE": "SHORTS", "ENGAGED_VIEWS": round(sev), "EXTERNAL_VIEWS": round(sev * 2.2),
                      "TOTAL_ESTIMATED_EARNINGS": round(sev * 0.19) if d < last - DAY else 0, "SUBSCRIBERS_NET_CHANGE": 10})
        daily.append({"DAY": n, "CREATOR_CONTENT_TYPE": "VIDEO_ON_DEMAND", "ENGAGED_VIEWS": 500, "EXTERNAL_VIEWS": 600,
                      "TOTAL_ESTIMATED_EARNINGS": 100 if d < last - DAY else 0, "SUBSCRIBERS_NET_CHANGE": 1})
        total.append({"DAY": n, "ENGAGED_VIEWS": round(sev) + 500, "EXTERNAL_VIEWS": round(sev * 2.2) + 600,
                      "TOTAL_ESTIMATED_EARNINGS": round(sev * 0.19) + 100 if d < last - DAY else 0, "SUBSCRIBERS_NET_CHANGE": 11})
        d += DAY
    videos.append({"id": "private1", "title": "非公開", "published": "1970-01-01T00:00:00.000Z", "length": 30, "short": True,
                   "privacy": "VIDEO_PRIVACY_PRIVATE", "ev": 0, "views": 0, "vtr": 0, "awp": 0, "rev": 0, "subs": 0})
    return {"channel": "UCtest", "fetched_at": fetched, "received_at": fetched, "date": T.jst_date(f).isoformat(), "source": "studio",
            "daily": daily, "daily_total": total, "videos": videos, "video_days": vdays}


ENTRIES = [{"name": "さくらみこ", "en": "Sakura Miko", "id": "miko"}, {"name": "大空スバル", "en": "Oozora Subaru", "id": "subaru"}]


def ds_of(raw):
    return data.parse(raw, data.member_matcher(ENTRIES))


class TimeTest(unittest.TestCase):
    def test_pt_dst(self):
        # 2026 の夏時間: 3/8 〜 11/1
        self.assertEqual(T.pt_offset(datetime.datetime(2026, 7, 1, tzinfo=UTC)), datetime.timedelta(hours=-7))
        self.assertEqual(T.pt_offset(datetime.datetime(2026, 12, 1, tzinfo=UTC)), datetime.timedelta(hours=-8))
        self.assertEqual(T.pt_offset(datetime.datetime(2026, 3, 8, 9, 59, tzinfo=UTC)), datetime.timedelta(hours=-8))
        self.assertEqual(T.pt_offset(datetime.datetime(2026, 3, 8, 10, 0, tzinfo=UTC)), datetime.timedelta(hours=-7))
        self.assertEqual(T.pt_day_start_utc(datetime.date(2026, 10, 7)), datetime.datetime(2026, 10, 7, 7, tzinfo=UTC))

    def test_elapsed_counts_the_publish_day(self):
        """日本時間の昼の公開は、PT ではその前日。公開日の数時間ぶんを落とさない(監査の E2)"""
        pub = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=T.JST).astimezone(UTC)   # PT 10/6 20:00
        self.assertEqual(T.to_pt(pub).date(), datetime.date(2026, 10, 6))
        self.assertAlmostEqual(T.elapsed_hours_at_day_end(pub, datetime.date(2026, 10, 6)), 4.0)


class DataTest(unittest.TestCase):
    def test_parse(self):
        ds = ds_of(make_raw())
        self.assertEqual(ds.pt_today, datetime.date(2026, 10, 7))
        self.assertIn("private1", ds.by_id)
        self.assertFalse(ds.by_id["private1"].public)   # 1970 年 = 非公開は数えない
        v = ds.by_id["v00000"]
        self.assertEqual(v.members, ["さくらみこ"])   # 「みこなま」(配信の名前)はメンバーではない
        self.assertAlmostEqual(ds.value("total", "rev", datetime.date(2026, 9, 1)), round(ds.value("shorts", "ev", datetime.date(2026, 9, 1)) * 0.19) / 1000 + 0.1, 1)

    def test_bad_raw(self):
        with self.assertRaises(data.DataError):
            data.parse({"fetched_at": "x"})
        with self.assertRaises(data.DataError):
            data.parse([])

    def test_collab(self):
        ds = data.parse(make_raw(title=lambda i: "【あ】本文【#大空スバル ／#さくらみこ ／#ホロライブ ／#shorts 】"), data.member_matcher(ENTRIES))
        self.assertEqual(ds.by_id["v00001"].members, ["大空スバル", "さくらみこ"])


class CalcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = ds_of(make_raw())
        cls.conf = calc.confirmed(cls.ds)

    def test_confirmed(self):
        self.assertEqual(self.conf["ev"], datetime.date(2026, 10, 5))   # タップした PT の日の 2 日前
        self.assertEqual(self.conf["rev"], datetime.date(2026, 10, 5))   # 収益は値が入っている最後の日

    def test_posts_jst(self):
        p = calc.posts_summary(self.ds)
        self.assertEqual(p["short7"], 21)   # 毎日 3 本 × 7 日(日本時間)
        self.assertEqual(p["perWeek28"], 21.0)

    def test_ypp_now(self):
        y = calc.ypp_now(self.ds, self.conf)
        want = sum(self.ds.value("shorts", "ev", self.conf["ev"] - i * DAY) for i in range(90))
        self.assertEqual(y["sum90"], round(want))

    def test_curve_matches_the_true_shape(self):
        """チェーンラダーの曲線が、作ったときの形(amp × (1 − e^(−h/40)))に近い"""
        m = calc.Model(self.ds, self.conf["ev"])
        for h in (24, 72, 168):
            self.assertAlmostEqual(m.curve.at(h) / cum(h, 20000), 1.0, delta=0.05)

    def test_backtest_on_steady_channel(self):
        """毎日同じに出して同じに伸びるチャンネルなら、答え合わせのずれは小さい"""
        bt = calc.backtest(self.ds, self.conf)
        self.assertGreaterEqual(len(bt["rows"]), 3)
        self.assertLess(bt["mape"], 0.08)
        self.assertLess(abs(bt["bias"]), 0.08)

    def test_forecast_more_posts_more_views(self):
        sigma = calc.backtest(self.ds, self.conf)["sigma"]
        m = calc.Model(self.ds, self.conf["ev"])
        lo = calc.forecast(self.ds, self.conf, 7, sigma, sims=100, model=m)
        hi = calc.forecast(self.ds, self.conf, 35, sigma, sims=100, model=m)
        self.assertLess(lo["p50"], hi["p50"])
        self.assertLessEqual(lo["prob"], hi["prob"])
        # 食い合いがあれば、同じ本数でも少なく見込む
        can = calc.forecast(self.ds, self.conf, 35, sigma, sims=100, model=m, e=0.5, ref=21)
        self.assertLess(can["p50"], hi["p50"])
        # 毎日 3 本 × 1 本 2 万 = 1 日 6 万 + 古い分 → 90 日で 約 570 万。週 21 本では 1,000 万に届かない
        mid = calc.forecast(self.ds, self.conf, 21, sigma, sims=200, model=m)
        self.assertLess(mid["prob"], 0.2)
        self.assertAlmostEqual(mid["p50"] / (90 * (3 * 20000 + 3000)), 1.0, delta=0.12)

    def test_launch_rank_by_hours(self):
        raw = make_raw(hits=[(480, 5.0)])
        ds = ds_of(raw)
        conf = calc.confirmed(ds)
        la = calc.launches(ds, conf)
        hit = [r for r in la["rows"] if r["id"] == "v00480"]
        if hit and hit[0]["pct"] is not None:
            self.assertEqual(hit[0]["label"], "当たり")
        self.assertTrue(any(r["label"] == "判定前" for r in la["rows"]))   # 24 時間ぶん確定していないもの

    def test_effect_table_finds_the_hit_member(self):
        """スバルの動画だけ 3 倍に伸びるなら、配信者の要因で スバル が上に出る"""
        def title(i):
            return "【あ】本文【#%s ／#ホロライブ ／#shorts 】" % ("大空スバル" if i % 3 == 0 else "さくらみこ")
        raw = make_raw(title=title, hits=[(i, 3.0) for i in range(0, 600, 3)])
        ds = ds_of(raw)
        conf = calc.confirmed(ds)
        e = calc.effect_table(ds, conf, conf["ev"])
        mem = next(f for f in e["factors"] if f["factor"] == "配信者")
        top = mem["rows"][0]
        self.assertEqual(top["key"], "大空スバル")
        self.assertTrue(top["stable"])

    def test_plan_scenario(self):
        """予定の本数(画面の設定)が見込みの行に名前付きで入り、判定にも使う"""
        posts = calc.posts_summary(self.ds)
        ol = calc.ypp_outlook(self.ds, self.conf, posts, sims=60, plan=28)
        plan = [s for s in ol["scenarios"] if "予定" in s["names"]]
        self.assertEqual([s["perWeek"] for s in plan], [28])
        self.assertIn("直近7日", [n for s in ol["scenarios"] for n in s["names"]])
        self.assertIn("予定(週28本)", render.outlook_brief(ol))

    def test_angles(self):
        """① 逆算・⑤ 当たり・④ 感度・食い合い・② 推移・境目の前後"""
        posts = calc.posts_summary(self.ds)
        ol = calc.ypp_outlook(self.ds, self.conf, posts, sims=60, plan=21, boundary=datetime.date(2026, 9, 1))
        self.assertEqual(sorted(ol["pools"]), ["after", "before"])
        # ① 逆算: 1 本 2 万 × 週 21 本では足りないので、必要な 1 本あたりは見本の平均より大きい
        row = next(x for x in ol["backcalc"]["rows"] if x["perWeek"] == 21)
        self.assertGreater(row["need7"], row["after"]["mean7"])
        self.assertLess(row["after"]["ratio"], 1.0)
        # 食い合いの無いチャンネル: 推定の e は 0 の近く(日の本数がいつも 3 本なので「推定できない」でもよい)
        c = ol["cannibal"]
        self.assertTrue(c["e"] is None or abs(c["e"]) < 0.3)
        self.assertEqual(ol["sensitivity"]["rows"][0]["diff"], 0.0)
        self.assertIsNotNone(ol["trend"]["after"])
        g = calc.regime_compare(self.ds, self.conf, datetime.date(2026, 9, 1))
        self.assertAlmostEqual(g["after"]["posts"], 3.0, delta=0.2)
        self.assertAlmostEqual(g["after"]["shortEv"] / g["before"]["shortEv"], 1.0, delta=0.1)   # 変わらないチャンネル

    def test_ledger(self):
        posts = calc.posts_summary(self.ds)
        ol = calc.ypp_outlook(self.ds, self.conf, posts, sims=40, plan=21)
        row = calc.ledger_row(self.ds, self.conf, ol)
        self.assertEqual(row["target"], (self.conf["ev"] + 28 * DAY).isoformat())
        old = dict(row, made="2026-09-01", target="2026-09-29")   # 目標の日が確定したもの
        ev = calc.ledger_eval(self.ds, self.conf, [old, row])
        self.assertEqual(len(ev["evaluated"]), 1)
        self.assertEqual(ev["pending"], 1)

    def test_deep_dive(self):
        d = calc.deep_dive(self.ds, self.conf, self.conf["ev"], days=90)
        self.assertGreater(d["n"], 100)
        self.assertEqual([o["name"].split(" ")[0] for o in d["outcomes"]], ["視聴を継続", "平均視聴率", "再生"])
        self.assertAlmostEqual(d["longevity"]["d7"], cum(168, 1) / cum(28 * 24, 1), delta=0.05)
        self.assertIsNotNone(d["concentration"]["top5"])

    def test_period_key(self):
        self.assertEqual(calc.period_key(self.ds, "daily"), "2026-10-08")
        self.assertEqual(calc.period_key(self.ds, "weekly"), "2026-09-28")   # 確定 10/5(月)以前の日曜 10/4 で終わる週
        self.assertEqual(calc.period_key(self.ds, "monthly"), "2026-09")


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = make_raw(title=lambda i: "【<script>x</script>】本文【#さくらみこ ／#shorts 】")
        cls.ds = ds_of(raw)

    def test_all_kinds(self):
        for kind, fn in (("daily", render.daily_parts), ("weekly", render.weekly_parts), ("monthly", render.monthly_parts)):
            r = calc.report(self.ds, kind, sims=60)
            text, page = fn(r)
            self.assertTrue(text.startswith("【"))
            self.assertLessEqual(len(text), 4500)
            self.assertIn("<!doctype html>", page)
            self.assertNotIn("<script>x", page)   # 題名は必ず逃がす
            self.assertNotIn("src=\"http", page)  # 外のファイルを読まない
            json.dumps(r, ensure_ascii=False)     # 画面へそのまま返せる


class FakeOpener:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def open(self, req, timeout=None):
        self.sent.append(json.loads(req.data.decode("utf-8")))
        body = self.replies.pop(0)

        class R:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def read(s, n=-1):
                return body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        return R()


URL = "https://script.google.com/macros/s/" + "A" * 40 + "/exec"
SECRET = "s" * 40


class BridgeTest(unittest.TestCase):
    def test_check(self):
        with self.assertRaises(bridge.BridgeError):
            bridge.check_url("https://example.com/exec")
        with self.assertRaises(bridge.BridgeError):
            bridge.check_secret("short")
        bridge.check_url(URL)
        bridge.check_secret(SECRET)

    def test_call_and_errors(self):
        op = FakeOpener([{"ok": True, "version": "1"}, {"ok": False, "error": "secret", "message": "合言葉が違います"}, b"<html>login</html>"])
        b = bridge.Bridge(URL, SECRET, opener=op)
        self.assertEqual(b.ping()["version"], "1")
        self.assertEqual(op.sent[0], {"secret": SECRET, "op": "ping"})
        with self.assertRaises(bridge.BridgeError) as c:
            b.ping()
        self.assertEqual(c.exception.code, "secret")
        with self.assertRaises(bridge.BridgeError) as c:
            b.ping()
        self.assertIn("全員", c.exception.message)
        self.assertNotIn(SECRET, c.exception.message)

    def test_list_pages(self):
        page1 = [{"id": "f%03d" % i + "x" * 10, "name": "2026-10-%02d.json" % (i % 28 + 1), "updated": "2026-10-08T00:%02d:00Z" % i} for i in range(60)]
        page2 = page1[-1:] + [{"id": "zz" + "x" * 10, "name": "2026-10-08.json", "updated": "2026-10-08T01:00:00Z"}]
        b = bridge.Bridge(URL, SECRET, opener=FakeOpener([{"ok": True, "files": page1}, {"ok": True, "files": page2}]))
        got = b.list_raw(None)
        self.assertEqual(len(got), 61)   # 境目の 1 件は重ねて取って重なりを除く


class FakeBridge:
    """Apps Script の連携の代わり(メモリの中に raw を持つ)"""

    def __init__(self, files):
        self.files = files      # id → (name, updated, raw)
        self.reports = []

    def list_raw(self, since=None):
        return [{"id": k, "name": n, "updated": u} for k, (n, u, _) in sorted(self.files.items(), key=lambda x: x[1][1]) if not since or u > since]

    def get_raw(self, fid):
        n, u, raw = self.files[fid]
        return {"id": fid, "name": n, "updated": u, "content": json.dumps(raw)}

    def report(self, kind, date, text, html, source, notify=True):
        self.reports.append((kind, date, source["rawId"]))
        return {"ok": True, "url": "https://script.google.com/macros/s/x/exec?v=key", "sent": True}

    def ping(self):
        return {"ok": True, "folder": True, "version": "1"}


class FakeHandler:
    def __init__(self):
        self.out = []

    def _send(self, code, body=b"", ctype="", extra=None):
        self.out.append((code, body, ctype, extra or {}))

    def _json(self, code, obj):
        self.out.append((code, obj, "json", {}))


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fb = FakeBridge({"id_first_aaaa": ("2026-10-08.json", "2026-10-07T23:11:00Z", make_raw())})
        self.svc = service.Service(base_dir=self.tmp, members=data.member_matcher(ENTRIES), bridge_factory=lambda url, secret: self.fb, sims=50)
        self.svc.set_config(URL, SECRET)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_daily_sent_once_and_resent_on_new_tap(self):
        out = self.svc.tick()
        kinds = [r["kind"] for r in out["sent"]]
        self.assertEqual(sorted(kinds), ["daily", "monthly", "weekly"])   # 初回は 3 つとも
        self.assertEqual(self.svc.tick()["sent"], [])                     # 同じデータでは送らない
        # 同じ日にもう一度タップ → 日報だけ作り直して送り直す
        self.fb.files["id_second_bbb"] = ("2026-10-08.json", "2026-10-08T02:00:00Z", make_raw(fetched="2026-10-08T01:59:00Z"))
        out = self.svc.tick()
        self.assertEqual([(r["kind"], r["period"]) for r in out["sent"]], [("daily", "2026-10-08")])
        self.assertEqual(self.fb.reports[-1][2], "id_second_bbb")
        self.assertEqual(len(self.svc.st["ledger"]), 1)   # 同じ確定日の見込みは置き換える

    def test_manual_run_resends(self):
        self.svc.tick()
        n = len(self.fb.reports)
        self.svc.run_now("weekly", True)
        self.assertEqual(len(self.fb.reports), n + 1)
        self.assertEqual(self.fb.reports[-1][0], "weekly")
        self.svc.run_now("daily", False)   # 送らずに作り直す
        self.assertEqual(len(self.fb.reports), n + 1)

    def test_not_configured(self):
        s = service.Service(base_dir=self.tmp + "x", bridge_factory=lambda u, s: self.fb)
        self.assertIsNone(s.tick())
        self.assertEqual(s.state, "off")

    def test_secret_not_shown(self):
        snap = json.dumps(self.svc.snapshot())
        self.assertNotIn(SECRET, snap)
        self.assertTrue(self.svc.snapshot()["config"]["hasSecret"])

    def test_web(self):
        self.svc.tick()
        h = FakeHandler()
        self.assertTrue(self.svc.handle_get(h, urllib.parse.urlsplit("/analytics/")))
        code, body, ctype, extra = h.out[-1]
        self.assertEqual(code, 200)
        self.assertIn("script-src 'self'", extra["Content-Security-Policy"])
        self.assertTrue(self.svc.handle_get(h, urllib.parse.urlsplit("/analytics/report/daily/2026-10-08.html")))
        code, body, ctype, extra = h.out[-1]
        self.assertEqual(code, 200)
        self.assertIn("default-src 'none'", extra["Content-Security-Policy"])   # 報告のページはスクリプトを動かさない
        self.assertTrue(self.svc.handle_get(h, urllib.parse.urlsplit("/analytics/report/daily/..%2f..%2fconfig.html")))
        self.assertEqual(h.out[-1][0], 404)
        self.assertFalse(self.svc.handle_get(h, urllib.parse.urlsplit("/studio/")))
        self.svc.handle_post(h, urllib.parse.urlsplit("/analytics/api/config"), {"url": "https://evil.example/exec"})
        self.assertEqual(h.out[-1][0], 400)


if __name__ == "__main__":
    unittest.main()
