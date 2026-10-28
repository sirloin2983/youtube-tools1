"""YouTube の取得の列(src/app/check/ytqueue.py。10-25)。yt-dlp と API は偽物(ネットに出ない)。
両方に効く候補が先・研究と声を交互・間隔と判定の止め(翌日に伸ばす)・研究の頼みの形の検査・API の説明欄は枠を使わない・途中の物を消す。
実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_ytqueue.py -v
"""
import datetime
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402

from app.check import voicefetch as VF, ytqueue as Q  # noqa: E402
from ytt.errors import ApiError  # noqa: E402

SORA, ROBO = "UC" + "a" * 22, "UC" + "b" * 22
R = {"groups": [{"id": "gen0", "names": ["ときのそら", "ロボ子さん"]}],
     "members": [{"name": "ときのそら", "channel": SORA}, {"name": "ロボ子さん", "channel": ROBO}]}
NOON = datetime.datetime(2026, 10, 25, 12, 0).timestamp()
FULL_VOICE = {"ときのそら": 999, "ロボ子さん": 999}   # 声は足りている(声だけの取得が並ばない)


class YtQueueTest(unittest.TestCase):
    def setUp(self):
        self.app = kit.tempdir(self, "ytt-ytqueue-")
        self.logs, self.calls = [], []
        self.light = []
        for p in (mock.patch.object(Q, "_audio", self.audio), mock.patch.object(Q, "_light_fetch", self.light_fetch)):
            p.start()
            self.addCleanup(p.stop)

    def light_fetch(self, app_dir, urls):
        self.light.append(list(urls))
        got = {}
        for u in urls:
            v = u[-11:]
            d = Q.qdir(app_dir, Q.KEEP_DIR, v)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, "subs.ja.json3"), "w").close()
            manual = v.endswith("01")   # 1 本目だけ人の手の字幕がある
            with open(os.path.join(d, "info.json"), "w", encoding="utf-8") as f:
                json.dump({"id": v, "subtitles": {"ja": [{}]} if manual else {}, "automatic_captions": {"ja": [{}]}}, f)
            got[v] = {"subs": os.path.join(d, "subs.ja.json3"), "info": os.path.join(d, "info.json")}
        return got, ""

    def audio(self, app_dir, rid, url, section):
        self.calls.append((rid, url, section))
        os.makedirs(Q.qdir(app_dir, "done"), exist_ok=True)
        path = Q.qdir(app_dir, "done", rid + ".m4a")
        open(path, "wb").close()
        vid = url.rsplit("=", 1)[-1][-11:]
        return path, {"id": vid, "channel_id": SORA if "SORA" in vid else ROBO, "upload_date": "20260901", "title": "【雑談】おはなし"}

    def put_cands(self, items):
        os.makedirs(Q.qdir(self.app), exist_ok=True)
        with open(Q.qdir(self.app, "candidates.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)

    def put_req(self, rid, body):
        os.makedirs(Q.qdir(self.app, "req"), exist_ok=True)
        with open(Q.qdir(self.app, "req", rid + ".json"), "w", encoding="utf-8") as f:
            json.dump(body, f)

    def tick(self, now, counts=None):
        return Q.tick(self.app, R, dict(counts or {}), lambda: None, lambda req: "j", self.logs.append, now=now)

    def test_dual_first_then_alternate(self):
        self.put_cands([{"video": "RESONLY0001", "t": 1000, "channel": "UC" + "z" * 22, "title": "よそ", "research": 0.9},
                        {"video": "SORADUAL001", "t": 2000, "channel": SORA, "title": "【雑談】そら", "uploadDate": "20260901", "research": 0.5}])
        self.assertEqual(self.tick(NOON, {"ロボ子さん": 2}), "candidate")
        self.assertEqual(self.calls[-1][0], "cand-SORADUAL001")                 # 研究と声の両方に効く候補が先
        self.assertEqual(self.calls[-1][2], [2000 - Q.AROUND[0], 2000 + Q.AROUND[1]])   # ?t= の前後
        self.assertTrue(os.path.exists(os.path.join(self.app, "check", VF.INBOX_NAME, "SORADUAL001.json")))   # 声の材料へも回す
        with open(Q.qdir(self.app, "done", "cand-SORADUAL001.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["state"], "done")
        self.assertIsNone(self.tick(NOON + 1800, {"ロボ子さん": 2}))             # 1 時間に 1 本
        self.put_req("r1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=REQAUDIO001", "section": [10, 20]})
        self.put_req("bad", {"purpose": "research", "kind": "audio", "url": "https://evil.example.com/x"})   # YouTube でない = 取らない
        self.assertEqual(self.tick(NOON + 3700, {"ロボ子さん": 2, "ときのそら": 2}), "research")   # 次は研究(頼みが候補より先。声の足りない人がいれば声が先 = test_full_audio_first_in_order)
        self.assertEqual(self.calls[-1][:2], ("r1", "https://www.youtube.com/watch?v=REQAUDIO001"))
        with mock.patch.object(VF, "tick", lambda *a, **k: "ロボ子さん") as _t:
            self.assertEqual(self.tick(NOON + 7400, {"ときのそら": 2}), "voice")  # 次は声(候補に無いロボ子さんを RSS で)
        self.assertEqual(self.tick(NOON + 11100, {"ときのそら": 2, "ロボ子さん": 2}), "candidate")   # 声が足りれば研究だけの候補
        self.assertEqual(self.calls[-1][0], "cand-RESONLY0001")
        self.assertTrue(os.path.exists(Q.qdir(self.app, "ready.json")))

    def test_research_request_for_needy_member_first(self):
        """研究の音の頼みで、配信者(hint.streamer)が材料の少ない日本の対象のメンバー = 両方に効く = 声の番でも先に取り、声にも回す"""
        from pipeline.transcribe import roster
        self.put_req("r-rev-a", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=OTHERVIDEO1", "hint": {"streamer": "知らない人"}})
        self.put_req("r-rev-b", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=SORAVIDEO01", "hint": {"streamer": "ときのそら"}})
        st = Q._state(self.app)
        Q._save(self.app, dict(st, lastPurpose="research"))   # 普通なら声の番
        with mock.patch.object(roster, "ROSTER", roster.BUNDLED):
            self.assertEqual(self.tick(NOON, {"ロボ子さん": 2}), "research")
        self.assertEqual(self.calls[-1][0], "r-rev-b")
        self.assertEqual([o["label"] for o in Q.plan(self.app, R, {"ロボ子さん": 2})][:1], ["声だけ ときのそら"])   # 取った後 = 頼みは消えた
        self.assertTrue(os.path.exists(os.path.join(self.app, "check", VF.INBOX_NAME, "SORAVIDEO01.json")))

    def test_candidates_filled_by_api(self):
        """研究の候補は channel・title・uploadDate が空(streamer だけ)= 列が API で埋めて点を付ける。キーが無ければ streamer だけで"""
        from pipeline.transcribe import roster
        self.put_cands([{"video": "SORAFILL001", "t": 500, "channel": None, "title": None, "uploadDate": None, "streamer": "ときのそら", "research": 1.0}])
        got = {"items": [{"id": "SORAFILL001", "snippet": {"title": "【歌枠】うた", "channelId": SORA, "publishedAt": "2026-08-01T00:00:00Z"}}]}
        with mock.patch.object(Q._ytapi, "get", lambda path, params: got):
            self.assertEqual(Q.fill_candidates(self.app, NOON, self.logs.append), 1)
        self.assertEqual(Q._state(self.app)["meta"]["SORAFILL001"]["title"], "【歌枠】うた")
        with mock.patch.object(roster, "ROSTER", roster.BUNDLED):
            self.assertEqual(self.tick(NOON, {"ときのそら": 2, "ロボ子さん": 2}), "candidate")   # 研究には効く
        self.assertIn("声 0.00", self.logs[-1])                                 # 埋めた題名が歌 = 声には効かない

    def test_api_info_without_slot(self):
        self.put_req("i1", {"purpose": "research", "kind": "info", "urls": ["https://www.youtube.com/watch?v=INFOVIDEO01"]})
        got = {"items": [{"id": "INFOVIDEO01", "snippet": {"title": "t", "description": "【元配信】x", "channelId": SORA, "publishedAt": "2026-09-01T00:00:00Z"}}]}
        with mock.patch.object(Q._ytapi, "get", lambda path, params: got):
            Q.tidy(self.app, NOON)
            self.assertEqual(Q._api_infos(self.app, self.logs.append, NOON), 1)
        with open(Q.qdir(self.app, "done", "i1.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["via"], d["infos"][0]["upload_date"]), ("api", "20260901"))
        self.assertTrue(Q.due(self.app, NOON)[0])                                # 枠は使っていない
        self.put_req("i2", {"purpose": "research", "kind": "info", "urls": ["https://www.youtube.com/watch?v=INFOVIDEO02"]})

        def no_key(path, params):
            raise ApiError("no_key", "x", 400)
        with mock.patch.object(Q._ytapi, "get", no_key):
            self.assertEqual(Q._api_infos(self.app, self.logs.append, NOON), 0)   # キーが無い = 今日は枠の yt-dlp で
        self.assertFalse(os.path.exists(Q.qdir(self.app, "done", "i2.json")))

    def test_bundle_kept_small(self):
        """使い道の束: 動画の情報は要る欄だけ(説明欄・チャプター・場面の山)・字幕はそのまま・3 日で消す(hold は残す)"""
        d = Q.qdir(self.app, Q.KEEP_DIR, "BUNDLEVID01")
        os.makedirs(d)
        with open(os.path.join(d, "info.info.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "BUNDLEVID01", "description": "【元配信】", "heatmap": [{"start_time": 0, "value": 1}], "chapters": [], "formats": ["大きい"] * 100}, f)
        open(os.path.join(d, "subs.ja.json3"), "w").close()
        got = Q.bundle(self.app, "BUNDLEVID01")
        with open(got["info"], encoding="utf-8") as f:
            info = json.load(f)
        self.assertEqual((sorted(info), got["subs"].endswith("subs.ja.json3")), (["chapters", "description", "heatmap", "id"], True))
        self.assertEqual(Q.bundle(self.app, "../../x"), {})
        h = Q.qdir(self.app, Q.KEEP_DIR, "HOLDVIDEO01")
        os.makedirs(h)
        open(os.path.join(h, "hold"), "w").close()
        for x in (d, h):
            os.utime(x, (NOON - 5 * 86400, NOON - 5 * 86400))
        Q.tidy(self.app, NOON)
        self.assertEqual(os.listdir(Q.qdir(self.app, Q.KEEP_DIR)), ["HOLDVIDEO01"])   # 研究が hold を置いた物だけ残る

    def test_served_request_never_again(self):
        """済ませた頼みは req から消し、研究が done を消してももう取らない(10-25: 同じショートを 2 回取った)"""
        self.put_req("r1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=REQAUDIO001"})
        self.assertEqual(self.tick(NOON, {"ときのそら": 2, "ロボ子さん": 2}), "research")
        self.assertFalse(os.path.exists(Q.qdir(self.app, "req", "r1.json")))
        os.remove(Q.qdir(self.app, "done", "r1.json"))                          # 研究が読んで消した
        self.put_req("r1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=REQAUDIO001"})   # 頼みが残っていても
        self.assertEqual(Q.requests(self.app), [])
        self.assertIn("r1", Q._state(self.app)["served"])

    def test_orphan_media_removed(self):
        """結果の json の無い古い音(取っている途中で止まった)は消す"""
        os.makedirs(Q.qdir(self.app, "done"))
        p = Q.qdir(self.app, "done", "cand--IroUWmemE4.webm")
        open(p, "wb").close()
        os.utime(p, (NOON - 7200, NOON - 7200))
        Q.tidy(self.app, NOON)
        self.assertFalse(os.path.exists(p))

    def test_bot_rest_then_slower(self):
        """当たり(ボット確認)= その側(音)だけ 30 分休み、そのあと間隔 1.5 倍で続ける。3 回当たらなければ戻す。日が明けたら段を戻す(10-25)"""
        full = {"ときのそら": 2, "ロボ子さん": 2}
        self.put_req("r1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=REQAUDIO001", "section": [0, 60]})
        with mock.patch.object(Q, "_audio", lambda *a: (None, "ERROR: Sign in to confirm you're not a bot")):
            self.assertEqual(self.tick(NOON, full), "research")
        self.assertTrue(any("30 分休み" in x for x in self.logs))
        self.assertFalse(Q.due(self.app, NOON + 1700)[0])                        # 休み
        self.assertFalse(Q.due(self.app, NOON + 3600 * 1.2)[0])                  # 間隔 60 × 1.5 = 90 分
        self.assertTrue(Q.due(self.app, NOON + 3600 * 1.6)[0])
        st = Q._state(self.app)
        for _ in range(3):
            Q.fine(st, "audio", self.logs.append)
        self.assertEqual((st["audio"]["pen"], Q.audio_gap(st)), (0, 60 * 60))   # 3 回当たらなければ間隔を戻す
        for _ in range(3):
            Q.fine(st, "audio", self.logs.append)
        self.assertEqual(st["audio"]["level"], 0)                                 # 次の 3 回で休みの段を戻す
        for _ in range(3):
            Q.fine(st, "audio", self.logs.append)
        self.assertEqual(Q.audio_gap(st), 60 * 60)                                # 当たった日は当たった段より速くしない(10-25 夜)
        Q.rollover(st, datetime.datetime(2026, 10, 26, 1, 0).timestamp(), self.logs.append)
        self.assertIn("前の日に 60 分おきで当たったので", self.logs[-1])
        for _ in range(3):
            Q.fine(st, "audio", self.logs.append)
        self.assertEqual(Q.audio_gap(st), 40 * 60)                                # 次の日は 3 回で段を上げる(上限の段階の実験)
        self.assertIn("段を上げました", self.logs[-1])
        Q.hit(st, "audio", "rate", NOON + 86400, self.logs.append)
        self.assertEqual(Q.audio_gap(st), 60 * 60)                                # 当たったら 1 段落とす
        c = st["light"] = {"step": 0, "pen": 0, "level": 0, "pause": 0, "ok": 0}
        for _ in range(3):
            Q.fine(st, "light", self.logs.append)
        self.assertEqual(Q.light_n(st), 10)                                       # 軽い物 5 → 10 本
        Q.rollover(st, datetime.datetime(2026, 10, 27, 1, 0).timestamp(), self.logs.append)
        self.assertEqual((c["step"], Q.light_n(st)), (1, 10))                     # 日が変わっても段はそのまま

    def test_busy_is_slower_and_new_version_waits(self):
        """処理中・ライブ中は音を止めず BUSY_SLOWER 段遅く(10-25 夜)・入口の起動し直しの待ちは新しく取らない・段は 5 分まで"""
        self.assertEqual(Q.AUDIO_MIN[-1], 5)
        st = {"audio": {"step": 4, "pen": 0, "level": 0, "pause": 0, "ok": 0}}   # 15 分おき
        self.assertEqual((Q.audio_gap(st), Q.audio_gap(st, Q.BUSY_SLOWER)), (15 * 60, 30 * 60))
        Q._save(self.app, dict(st, last=NOON))
        self.assertTrue(Q.due(self.app, NOON + 16 * 60)[0])
        self.assertFalse(Q.due(self.app, NOON + 16 * 60, Q.BUSY_SLOWER)[0])
        self.assertTrue(Q.due(self.app, NOON + 31 * 60, Q.BUSY_SLOWER)[0])
        seen = []
        with mock.patch.object(Q, "due", lambda app, now, slower=0, ledger_weight=0.0: seen.append(slower) or (False, "")):
            Q.tick(self.app, R, {}, lambda: Q.LIVE_BUSY, lambda req: "j", self.logs.append, now=NOON + 41 * 60)
            Q.tick(self.app, R, {}, lambda: "処理中", lambda req: "j", self.logs.append, now=NOON + 42 * 60)
        self.assertEqual(seen, [0, Q.BUSY_SLOWER])   # ライブ中はふだんどおり・処理中は 2 段遅く(10-25 ユーザー)
        chats = []
        with mock.patch.object(Q, "chat_batch", lambda app, now, log: chats.append(now)), mock.patch.object(Q, "due", lambda *a, **k: (False, "")):
            Q.tick(self.app, R, {}, lambda: Q.LIVE_BUSY, lambda req: "j", self.logs.append, now=NOON + 43 * 60)
            Q.tick(self.app, R, {}, lambda: "処理中", lambda req: "j", self.logs.append, now=NOON + 44 * 60)
        self.assertEqual(chats, [NOON + 43 * 60])   # チャットの回もライブ中はふだんどおり・処理中は休む
        with mock.patch.object(Q, "due", side_effect=AssertionError("新しい版の待ちでは音を見ない")):
            Q.tick(self.app, R, {}, lambda: "新しい版 v9.9.9 を待っています", lambda req: "j", self.logs.append, now=NOON + 40 * 60)

    def test_ledger_yields_and_shares_hits(self):
        """帳簿(ytt/ytledger): 製品のほかの問い合わせの直近 30 分の重みが LEDGER_MAX を超えれば音を延ばす・誰かが当たれば列も休む(10-25 夜)"""
        self.assertFalse(Q.due(self.app, NOON, ledger_weight=Q.LEDGER_MAX + 1)[0])
        self.assertTrue(Q.due(self.app, NOON, ledger_weight=Q.LEDGER_MAX - 1)[0])
        led = {"weight": 0.0, "hits": [(NOON - 5, "rate", "recorder")], "lives": 0}
        with mock.patch.object(Q._ytledger, "load", lambda now, exclude_src=(), p=None: led):
            self.tick(NOON)
            self.tick(NOON + 1)   # 同じ当たりで二度休まない
        st = Q._state(self.app)
        self.assertEqual((st["audio"]["hits"], st["light"]["hits"]), (1, 1))
        self.assertTrue(any("当たったのは recorder" in x for x in self.logs))
        self.assertFalse(Q.due(self.app, NOON + 60)[0])

    def test_light_batch(self):
        """軽い物(字幕)は音の回と別に、1 回でまとめて取る(処理中でも)。字幕の頼みは 1 つで 5 本まで・返事は files"""
        urls = ["https://www.youtube.com/watch?v=SUBSVIDEO%02d" % i for i in range(1, 7)]
        self.put_req("s1", {"purpose": "research", "kind": "subs", "urls": urls})   # 6 本 → 5 本まで
        self.put_req("s2", {"purpose": "research", "kind": "subs", "url": "https://www.youtube.com/watch?v=SUBSVIDEO99"})
        Q._save(self.app, {"last": NOON - 60})   # 音の回はまだ間隔の中(この試しは軽い物だけを見る)
        got = Q.tick(self.app, R, {}, lambda: "処理中", lambda req: "j", self.logs.append, now=NOON)
        self.assertEqual((got, self.light[-1][:1], len(self.light[-1])), ("light", [urls[0]], 5))   # 上限 5 本 = s1 の 5 本だけ
        with open(Q.qdir(self.app, "done", "s1.json"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((len(d["files"]), len(d["infos"])), (5, 5))   # 動画の情報(heatmap)のパスも返す
        self.assertIn("waitSec", d)                                               # 待ち時間
        self.assertEqual(d["subsKind"]["SUBSVIDEO01"], "手")                     # 人の手の字幕(10-25 研究の頼み)
        self.assertEqual(d["subsKind"]["SUBSVIDEO02"], "自動")
        self.assertIsNone(Q.light_batch(self.app, NOON + 600, self.logs.append))  # 1 時間に 1 回
        self.assertEqual(Q.light_batch(self.app, NOON + 3700, self.logs.append), "light")   # 次の回に s2

    def put_at(self, rid, body, at):
        self.put_req(rid, dict({"purpose": "research", "kind": "audio"}, **body))
        os.utime(Q.qdir(self.app, "req", rid + ".json"), (at, at))

    def test_tiers_fixed_order(self):
        """段を上から固定(10-26 ユーザー OK): ② 急ぎ(印ごとに 60 本・2 日)③ 定期(声。2 時間に 1 回分)④ 配信全体 ⑤ その他・段の中は頼んだ順(待った時間で変えない)"""
        u = "https://www.youtube.com/watch?v="
        self.put_at("r-up-old", {"url": u + "OLDSHORT001", "section": [0, 600]}, NOON - 5 * 86400)   # 5 日待っても ⑤ のまま
        self.put_at("r-full-b", {"url": u + "FULLVIDEO01"}, NOON)
        self.put_at("r-full-a", {"url": u + "FULLVIDEO02"}, NOON + 60)
        for i in range(3):
            self.put_at("r-sa-%d" % i, {"url": u + "URGENTVID0%d" % i, "section": [0, 24], "urgent": "s1"}, NOON + 100 + i)
        self.put_at("r-sa-late", {"url": u + "URGENTOLD01", "section": [0, 24], "urgent": "s0"}, NOON - 3 * 86400)   # 期限 2 日を過ぎた急ぎ
        with mock.patch.object(Q, "URGENT_MAX", 2):
            ranked = Q.plan(self.app, R, {"ときのそら": 0, "ロボ子さん": 0}, now=NOON + 3600)
        ids = [(o["tier"], o["req"]["id"] if o.get("req") else o["label"]) for o in ranked]
        self.assertEqual(ids[:6], [(2, "r-sa-0"), (2, "r-sa-1"), (3, "声だけ ときのそら"), (3, "声だけ ロボ子さん"), (4, "r-full-b"), (4, "r-full-a")])
        self.assertEqual(ids[6:], [(5, "r-sa-late"), (5, "r-sa-2"), (5, "r-up-old")])   # 急ぎの超えた分・期限切れは ④ の後ろ → ほかは頼んだ順
        st = Q._state(self.app)
        st["voiceAt"] = NOON + 3000
        ranked = Q.plan(self.app, R, {"ときのそら": 0, "ロボ子さん": 0}, st=st, now=NOON + 3600)
        self.assertEqual([o["tier"] for o in ranked if o["kind"] == "voice"], [6, 6])   # 定期の間隔が来ていなければ一番下
        view = Q.order_view(ranked, st, NOON + 3600)
        t4 = next(x for x in view["tiers"] if x["tier"] == 4)
        self.assertEqual((t4["n"], t4["minutes"], t4["rounds"]), (2, 360, 2))
        t2 = next(x for x in view["tiers"] if x["tier"] == 2)
        self.assertEqual((t2["n"], t2["rounds"]), (3, 1))                         # 短い音 3 本 = 1 回
        self.assertLess(t2["etaH"], t4["etaH"])

    def test_tier_balance_and_voice_interval(self):
        """同じ段が 6 時間続いたら下の段に 1 回渡す・定期(声)を使ったら 2 時間は一番下・見える化の order.json"""
        u = "https://www.youtube.com/watch?v="
        for i in range(3):
            self.put_at("r-full-%d" % i, {"url": u + "FULLVIDEO0%d" % i}, NOON + i)
        self.put_at("r-up-x", {"url": u + "SHORTVIDE01", "section": [0, 300]}, NOON)
        got = []
        full = {"ときのそら": 999, "ロボ子さん": 999}
        with mock.patch.object(Q, "_audio", lambda a, rid, url, sec: got.append(rid) or self.audio(a, rid, url, sec)), mock.patch.object(Q, "TURNS_ON", False):
            self.tick(NOON, full)
            self.tick(NOON + 7 * 3600, full)                                      # ④ が 7 時間続いた = ⑤ に 1 回
            self.tick(NOON + 9 * 3600, full)
        self.assertEqual(got, ["r-full-0", "r-up-x", "r-full-1"])
        with open(Q.qdir(self.app, Q.ORDER_NAME), encoding="utf-8") as f:
            self.assertEqual([(x["tier"], x["n"]) for x in json.load(f)["tiers"]], [(4, 2)])
        with mock.patch.object(Q._vf, "tick", lambda *a, **k: got.append("voice") or "voice"),                 mock.patch.object(Q, "_audio", lambda a, rid, url, sec: got.append(rid) or self.audio(a, rid, url, sec)):
            self.tick(NOON + 12 * 3600, {})                                       # 声が足りない = ③ が先
            self.tick(NOON + 13 * 3600, {})                                       # 2 時間たっていない = ④
        self.assertEqual(got[-2:], ["voice", "r-full-2"])

    def test_turns_to_lower_tiers(self):
        """上の段から 3 回ごとに下の段へ 1 回・下の段が複数なら順に・間隔待ちの 6 には渡さない・見込みの時間も同じ回し方で(10-28)"""
        ranked = [{"tier": t, "id": "%d-%d" % (t, i)} for t in (2, 4, 5, 6) for i in range(20)]
        st, got = {}, []
        for _ in range(12):
            got.append(Q._pick(ranked, st, NOON, None)["tier"])
        self.assertEqual(got, [2, 2, 2, 4, 2, 2, 2, 5, 2, 2, 2, 4])
        self.assertEqual(Q._turn_etas({2: 3, 5: 1}, {}), {2: 3, 5: 4})
        self.assertEqual(Q._turn_etas({2: 6, 4: 1, 5: 2}, {}), {4: 4, 2: 7, 5: 9})   # 2,2,2,4,2,2,2 → 残りの 5 が 2 回
        with mock.patch.object(Q, "TURN_EVERY", 1):
            self.assertEqual(Q._turn_etas({2: 2, 5: 2}, {}), {2: 3, 5: 4})
        with mock.patch.object(Q, "TURNS_ON", False):
            self.assertEqual(Q._pick(ranked, {}, NOON, None)["tier"], 2)

    def test_keep_dir_setting(self):
        """keep の置き場は設定 ytQueueKeepDir で作業データの外へ(10-26)。無い・ドライブが無い・相対なら作業データの中"""
        other = kit.tempdir(self, "ytt-keep-")
        for v, want in ((None, Q.qdir(self.app, Q.KEEP_DIR, "V")), (other, os.path.join(other, "V")),
                        ("Q:\\nodrive\\keep" if not os.path.isdir("Q:\\") else 1, Q.qdir(self.app, Q.KEEP_DIR, "V")), ("rel\\keep", Q.qdir(self.app, Q.KEEP_DIR, "V"))):
            with mock.patch.object(Q._settings, "load_settings", lambda v=v: {Q.KEEP_SETTING: v}):
                self.assertEqual(Q.keep_dir(self.app, "V"), want, v)

    def test_short_audio_batched_in_one_round(self):
        """研究の短い区間の音(6 分以下)は音の回 1 回で数本(同じ動画は 1 回の yt-dlp に区間を複数)・当たったら残りは頼みのまま・本数を半分・
        配信全体の音は先に 1 本ずつ(10-26)"""
        secs = {"r-up-a": ("SAMEVIDEO01", [100, 400]), "r-up-b": ("SAMEVIDEO01", [900, 1200]), "r-up-c": ("OTHERVIDE01", [0, 300]),
                "r-up-d": ("OTHERVIDE02", [60, 360]), "r-full-z": ("FULLVIDEO01", None)}
        for rid, (vid, sec) in secs.items():
            self.put_req(rid, {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=" + vid, "section": sec})
        groups = []

        def sections(app_dir, url, reqs):
            groups.append([q["id"] for q in reqs])
            return [(q,) + self.audio(app_dir, q["id"], url, q["section"]) for q in reqs]
        with mock.patch.object(Q, "_audio_sections", sections), mock.patch.object(Q, "_sleep", lambda s: None):
            self.assertEqual(self.tick(NOON, FULL_VOICE), "research")
            self.assertEqual([c[0] for c in self.calls], ["r-full-z"])            # 配信全体の音が先(1 本だけ)
            self.calls.clear()
            self.assertEqual(self.tick(NOON + 7200, FULL_VOICE), "research")
        self.assertEqual(groups, [["r-up-a", "r-up-b"]])                          # 同じ動画は 1 回に区間 2 つ
        self.assertEqual(sorted(c[0] for c in self.calls), ["r-up-a", "r-up-b", "r-up-c", "r-up-d"])
        self.assertEqual(Q.requests(self.app), [])
        for i in range(8):
            self.put_req("r-up-h%d" % i, {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=HITVIDEO%03d" % i, "section": [0, 300]})
        n = []

        def audio_hit(app_dir, rid, url, section):
            n.append(rid)
            return (None, "ERROR: Sign in to confirm you're not a bot") if len(n) == 3 else self.audio(app_dir, rid, url, section)
        with mock.patch.object(Q, "_audio", audio_hit), mock.patch.object(Q, "_sleep", lambda s: None):
            self.tick(NOON + 14400, FULL_VOICE)
        self.assertEqual(len(n), 3)                                               # 始まりは 6 本まとめ・3 本目で当たって止めた
        self.assertEqual(len(Q.requests(self.app)), 6)                            # 当たった 1 本と残りは頼みのまま
        st = Q._state(self.app)
        self.assertEqual(Q.short_n(st), 3)                                        # 当たったら半分
        self.assertGreater(st["audio"]["pause"], NOON + 14400)                    # 音の休み(今のまま)

    def test_audio_sections_maps_files_to_requests(self):
        """同じ動画の区間を 1 回で: 出力は区間の始めの秒で分かれ、頼みごとの done/<rid>.<拡張子> へ"""
        reqs = [{"id": "r-up-a", "section": [100, 400]}, {"id": "r-up-b", "section": [900, 1200]}]
        seen = []

        def ytdlp(cmd, timeout):
            seen.append(cmd)
            out = cmd[cmd.index("-o") + 1]
            for s in (100, 900):
                with open(out.replace("%(section_start)d", str(s)).replace("%(ext)s", "m4a"), "wb") as f:
                    f.write(b"x" * s)
            return mock.Mock(returncode=0, stdout="SAMEVIDEO01\tUCx\t20261001\t3600\t題\n"), ""
        with mock.patch.object(VF._tools, "find_tool", lambda name: name), mock.patch.object(VF, "_ytdlp", ytdlp):
            got = Q._audio_sections(self.app, "https://www.youtube.com/watch?v=SAMEVIDEO01", reqs)
        self.assertEqual([a for a in seen[0] if a.startswith("*")], ["*100-400", "*900-1200"])
        self.assertEqual([os.path.basename(p) for _q, p, _i in got], ["r-up-a.m4a", "r-up-b.m4a"])
        self.assertEqual(os.path.getsize(got[1][1]), 900)
        self.assertEqual(got[0][2]["id"], "SAMEVIDEO01")

    def test_skip_download_writes_under_keep(self):
        """字幕・チャットだけの取得も既定の -o を keep/<動画>/ に置く(無いと途中の .part が作業フォルダ = src に残った。10-26)"""
        seen = []

        def ytdlp(cmd, timeout):
            seen.append(cmd)
            return None, ""
        with mock.patch.object(VF._tools, "find_tool", lambda name: "yt-dlp"), mock.patch.object(VF, "_ytdlp", ytdlp):
            Q._chat(self.app, "https://www.youtube.com/watch?v=CHATVIDE001")
            Q._light_fetch(self.app, ["https://www.youtube.com/watch?v=SUBSVIDEO01"])
        keep = Q.keep_dir(self.app)
        for cmd in seen:
            outs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-o" and not cmd[i + 1].startswith(("subtitle:", "infojson:"))]
            self.assertEqual(len(outs), 1, cmd)
            self.assertTrue(outs[0].startswith(keep + os.sep), outs[0])

    def test_list_is_light(self):
        """配信の一覧の頼みは音の回を使わず 5 分に 1 本(急ぎが先)・見込みは 1 分(10-27: 1 本 180 分と見込まれ、音の回を 1 本ずつ使っていた)"""
        u = "https://www.youtube.com/channel/UCAAAAAAAAAAAAAAAAAAAAAA/streams"
        self.put_req("r-md-a", {"purpose": "research", "kind": "list", "url": u, "items": 10})
        self.put_req("r-md-b", {"purpose": "research", "kind": "list", "url": u, "items": 10, "urgent": "直接"})
        got = []
        with mock.patch.object(Q, "_list_url", lambda url, n: got.append(n) or ([{"id": "AAAAAAAAAAA"}], "")):
            self.assertEqual(Q.list_batch(self.app, NOON, self.logs.append), "list")
            self.assertIsNone(Q.list_batch(self.app, NOON + 60, self.logs.append))   # 5 分に 1 本
        self.assertEqual([q["id"] for q in Q.requests(self.app)], ["r-md-a"])          # 急ぎが先
        self.assertEqual(Q._minutes({"kind": "request", "req": Q.requests(self.app)[0]}), 1.0)

    def test_chat_batch(self):
        """チャットの頼みは音の枠で競わず、軽い物の守りの中で 1 時間に 1 回・始まりは 10 本(10-25: 点 0.6 で候補・声に負け続け、38 件が 1 件も取られなかった)"""
        for i in range(12):
            self.put_req("c%d" % i, {"purpose": "research", "kind": "chat", "url": "https://www.youtube.com/watch?v=CHATVIDE%03d" % i})
        taken = []

        def chat(app_dir, url):
            taken.append(url[-11:])
            d = Q.qdir(app_dir, Q.KEEP_DIR, url[-11:])
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "chat.live_chat.json")
            open(p, "w").close()
            return p, ""
        alive = [False]
        sync = lambda fn: (fn(), mock.Mock(is_alive=lambda: alive[0]))[1]   # 裏の糸の代わりにその場で流す
        with mock.patch.object(Q, "_chat", chat), mock.patch.object(Q, "_start", sync):
            Q.tick(self.app, R, {}, lambda: "処理中", lambda req: "j", self.logs.append, now=NOON)
            self.assertEqual(taken, [])                                            # 処理中は取らない
            self.assertEqual([Q.chat_batch(self.app, NOON + i, self.logs.append) for i in range(11)], ["chat"] * 10 + [None])
            self.assertEqual((len(taken), len(Q.requests(self.app))), (10, 2))     # 始まりは 10 本・1 本ずつ裏で(見回りは待たない)
            self.assertIsNone(Q.chat_batch(self.app, NOON + 600, self.logs.append))   # 1 時間に 1 回
            self.assertEqual(Q.chat_batch(self.app, NOON + 3600, self.logs.append), "chat")
            alive[0] = True
            self.assertIsNone(Q.chat_batch(self.app, NOON + 3610, self.logs.append))   # 取っている間は次を始めない(1 本ずつ)
            alive[0] = False
        with mock.patch.object(Q, "_chat", lambda *a: (None, "HTTP Error 429: Too Many Requests")), mock.patch.object(Q, "_start", sync):
            self.assertEqual(Q.chat_batch(self.app, NOON + 3620, self.logs.append), "chat")   # 前の 1 本を書き、次を始める(当たる)
            self.assertIsNone(Q.chat_batch(self.app, NOON + 3630, self.logs.append))
        st = Q._state(self.app)
        self.assertGreater(st["light"]["pause"], NOON + 3630)                    # 当たったら軽い物の側が休む
        self.assertEqual(len(Q.requests(self.app)), 1)                           # 頼みは残す
        self.assertEqual(Q.chat_n(st), 5)                                         # 当たったら半分(10 本 → 5 本)
        st["light"].update(pause=0, chatLeft=3)
        st["audio"]["pause"] = NOON + 9999
        Q._save(self.app, st)
        self.assertIsNone(Q.chat_batch(self.app, NOON + 4000, self.logs.append))  # 音が断られて休んでいる間はチャットも休む(10-27)
        Q._CHAT_JOB["thread"] = mock.Mock(is_alive=lambda: True)
        try:
            with mock.patch.object(Q, "due", lambda *a, **k: (True, "")), mock.patch.object(Q, "_pick", side_effect=AssertionError("重ねない")), \
                    mock.patch.object(Q, "light_batch", side_effect=AssertionError("重ねない")):
                Q.tick(self.app, R, {}, lambda: None, lambda req: "j", self.logs.append, now=NOON + 4000)   # 裏のチャットの最中は音も軽い物も始めない
        finally:
            Q._CHAT_JOB.clear()
        with Q.run_lock(self.app) as a, Q.run_lock(self.app) as b:
            self.assertEqual((a, b), (True, False))                               # 列の錠は 1 つだけ
        with Q.run_lock(self.app) as a:
            self.assertTrue(a)                                                    # 出たら外れる

    def test_same_video_hit_twice_is_unfetchable(self):
        """同じ動画で続けて 2 回断られた = その動画だけの失敗。列は休ませず取れない印を付けて外し、次の頼みも取りに行かない・URL の数字の 429 は当たりではない(10-27 ggZMyu2FxgU)"""
        self.assertIsNone(Q.classify("ERROR: ffmpeg exited https://rr4.googlevideo.com/videoplayback?clen=242990&lmt=17429001"))
        self.assertEqual(Q.classify("ERROR: unable to download video data: HTTP Error 429: Too Many Requests"), "rate")
        full = {"ときのそら": 2, "ロボ子さん": 2}
        u = "https://www.youtube.com/watch?v=BADSHORT001"
        calls = []
        rate = lambda *a: calls.append(a[1]) or (None, "ERROR: HTTP Error 429: Too Many Requests")
        self.put_req("b1", {"purpose": "research", "kind": "audio", "url": u, "section": [0, 18]})
        with mock.patch.object(Q, "_audio", rate):
            self.tick(NOON, full)
            self.assertFalse(Q.due(self.app, NOON + 60)[0])                     # 1 回目はふつうの当たり(休む)
            self.put_req("b2", {"purpose": "research", "kind": "audio", "url": u, "section": [0, 18]})
            self.tick(NOON + 4 * 3600, full)
            self.assertTrue(Q.due(self.app, NOON + 4 * 3600 + 60)[0])           # 2 回目は休まない
            self.put_req("b3", {"purpose": "research", "kind": "audio", "url": u, "section": [0, 18]})
            self.tick(NOON + 4 * 3600 + 120, full)
        self.assertEqual(calls, ["b1", "b2"])                                    # 3 本目は取りに行かない
        for rid in ("b2", "b3"):
            with open(Q.qdir(self.app, "done", rid + ".json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["unfetchable"], Q.BAD_NOTE)
        self.assertEqual(Q._state(self.app)["badVids"], ["BADSHORT001"])

    def test_gone_not_counted(self):
        """動画が無い・メンバー限定は枠に数えない(次の見回りで次の 1 本)"""
        full = {"ときのそら": 2, "ロボ子さん": 2}
        self.put_req("g1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=GONEVIDEO01", "section": [0, 60]})
        with mock.patch.object(Q, "_audio", lambda *a: (None, "ERROR: [youtube] GONEVIDEO01: Video unavailable")):
            self.tick(NOON, full)
        self.assertTrue(Q.due(self.app, NOON + 60)[0])
        # 下の段へ渡した 1 回が取れない動画に当たったとき: 渡した回し(turnCount・turnLast)も戻す = その回が消えない(コードの見直し 10-29 の 13)
        self.put_req("r-full-1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=FULLVIDEO01"})   # 配信全体の音(上の段)
        self.put_req("g2", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=GONEVIDEO02", "section": [0, 60]})   # その他(下の段)
        st = Q._state(self.app)
        Q._save(self.app, dict(st, turnCount=Q.TURN_EVERY, turnLast=None))
        got = []

        def audio(app_dir, rid, url, section):
            got.append(rid)
            return (None, "ERROR: [youtube] GONEVIDEO02: Video unavailable") if "GONE" in url else self.audio(app_dir, rid, url, section)
        with mock.patch.object(Q, "_audio", audio):
            self.tick(NOON + 120, full)
        self.assertEqual(got, ["g2"])                                              # 下の段に渡した回
        st = Q._state(self.app)
        self.assertEqual((st.get("turnCount"), st.get("turnLast"), st.get("last")), (Q.TURN_EVERY, None, None))   # 回しも回の印も前のまま

    def test_short_source_by_title(self):
        """説明欄に URL が無く【元配信】の行に題名だけ = 手元の題名で引き、無ければ検索(1 本は 1 度だけ)・印 srcBy(10-26)"""
        self.assertEqual(Q.source_title("【元配信】\n【 🔴3Dオフコラボ 】みんなで楽しく遊ぼう♩ | 1-2-Switch\n#ホロライブ"), "【 🔴3Dオフコラボ 】みんなで楽しく遊ぼう♩ | 1-2-Switch")
        self.assertEqual(Q.source_title("元配信：晩酌の配信"), "晩酌の配信")
        self.assertIsNone(Q.source_title("【元配信】\nhttps://youtu.be/AAAAAAAAAAA"))
        self.assertIsNone(Q.source_title("#ホロライブ"))
        os.makedirs(Q.keep_dir(self.app, "LOCALVIDE01"))
        with open(Q.keep_dir(self.app, "LOCALVIDE01", "info.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "【 🔴3Dオフコラボ 】みんなで楽しく遊ぼう♩ | 1-2-Switch【 #スバおかすい/ホロライブ 】"}, f)
        have = {"S1": {"src": None, "srcTitle": "【 🔴3Dオフコラボ 】みんなで楽しく遊ぼう♩ | 1-2-Switch"},
                "S2": {"src": None, "srcTitle": "【 晩酌 】ラミィと買い物行ってそのままねねん家で晩酌!"},
                "S3": {"src": "XXXXXXXXXXX"}}
        seen = []

        def search(title):
            seen.append(title)
            return "FOUNDVIDE01", "【 晩酌 】ラミィと買い物行ってそのままねねん家で晩酌!【 桃鈴ねね / 雪花ラミィ 】"
        with mock.patch.object(Q, "_search_title", search):
            self.assertEqual(Q.resolve_titles(self.app, have, NOON, None), 2)
            self.assertEqual(Q.resolve_titles(self.app, have, NOON + 60, None), 0)   # もう探さない
        self.assertEqual((have["S1"]["src"], have["S1"]["srcBy"]), ("LOCALVIDE01", "title"))
        self.assertEqual((have["S2"]["src"], have["S2"]["srcBy"]), ("FOUNDVIDE01", "title-search"))
        self.assertEqual(len(seen), 1)                                              # 手元で引けた物は検索しない

    def test_short_sources_by_api(self):
        """友人のショート(分析の記録の videos の short)の説明欄を API で読み、元の配信と ?t= を short-sources.json に(枠は使わない)"""
        raw = os.path.join(self.app, "raw")
        os.makedirs(raw)
        with open(os.path.join(raw, "2026-10-25__x.json"), "w", encoding="utf-8") as f:
            json.dump({"videos": [{"id": "SHORTVID001", "short": "True"}, {"id": "LONGVIDEO01", "short": "False"}, {"id": "SHORTVID002", "short": "True"}]}, f)
        got = {"items": [{"id": "SHORTVID001", "snippet": {"description": "【元配信】\nhttps://www.youtube.com/live/SRCVIDEO001?t=1200"}},
                         {"id": "SHORTVID002", "snippet": {"description": "#ホロライブ"}}]}
        with mock.patch.object(Q._ytapi, "get", lambda path, params: got):
            self.assertEqual(Q.read_short_sources(self.app, raw, NOON, self.logs.append), 2)
            self.assertEqual(Q.read_short_sources(self.app, raw, NOON + 60, self.logs.append), 0)   # 6 時間に 1 回・読んだ物はもう読まない
        with open(Q.qdir(self.app, Q.SRC_NAME), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["SHORTVID001"]["src"], d["SHORTVID001"]["t"], d["SHORTVID002"]["src"]), ("SRCVIDEO001", 1200, None))
        self.assertEqual((d["SHORTVID001"]["srcs"], d["SHORTVID001"]["n"], d["SHORTVID001"]["tag"], d["SHORTVID002"]["tag"]),
                         (["SRCVIDEO001"], 1, True, False))
        self.assertEqual(Q.sources_all("元: https://youtu.be/AAAAAAAAAAA?t=5\nhttps://www.youtube.com/watch?v=BBBBBBBBBBB https://youtu.be/AAAAAAAAAAA"),
                         (["AAAAAAAAAAA", "BBBBBBBBBBB"], False))                 # 全部の id(重ねない)・【元配信】の行なし
        d["SHORTVID002"] = {"src": None, "t": None, "at": 1}                     # srcs の無い古い行 = 次の読み直しで埋める
        with open(Q.qdir(self.app, Q.SRC_NAME), "w", encoding="utf-8") as f:
            json.dump(d, f)
        with mock.patch.object(Q._ytapi, "get", lambda path, params: got):
            Q.read_short_sources(self.app, raw, NOON + 7 * 3600, self.logs.append)
        with open(Q.qdir(self.app, Q.SRC_NAME), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["SHORTVID002"]["srcs"], [])
        self.assertTrue(Q.due(self.app, NOON)[0])                                # 枠は使っていない

    def test_eval_sources_blocked(self):
        """評価用のショートの元の配信を外す(10-25): 評価用の .mov を分析の記録のショートと突き合わせ、説明欄の元の配信を候補から外す"""
        ev = os.path.join(self.app, "評価用データ", "1_JP")
        os.makedirs(ev)
        open(os.path.join(ev, "26-03-01_ときのそら.mov"), "wb").close()
        raw = os.path.join(self.app, "raw")
        os.makedirs(raw)
        with open(os.path.join(raw, "2026-10-25__x.json"), "w", encoding="utf-8") as f:
            json.dump({"videos": [{"id": "SHORTEVAL01", "title": "そら ときのそら #shorts", "published": "2026-03-01T10:00:00Z", "length": "30", "short": "True"}]}, f)
        os.makedirs(Q.qdir(self.app), exist_ok=True)
        with open(Q.qdir(self.app, Q.SRC_NAME), "w", encoding="utf-8") as f:
            json.dump({"SHORTEVAL01": {"src": "EVALSOURCE1", "t": 100}}, f)
        self.assertEqual(Q.eval_sources(self.app, [os.path.join(self.app, "評価用データ")], raw, NOON, self.logs.append, dur=lambda p: 30.4), 1)
        self.assertEqual(Q.blocked_videos(self.app), {"EVALSOURCE1"})
        self.put_cands([{"video": "EVALSOURCE1", "t": 100, "channel": SORA, "title": "【雑談】そら", "research": 1.0}])
        with mock.patch.object(Q._settings, "eval_dirs", lambda: []):
            self.assertIsNone(self.tick(NOON, {"ときのそら": 2, "ロボ子さん": 2}))   # 候補から外れる
        self.assertIn("EVALSOURCE1", VF._blocked(self.app))                      # 声の材料の取得・研究の音の受け取りも外す

    def test_tidy_removes_partial(self):
        os.makedirs(Q.qdir(self.app, "done"))
        open(Q.qdir(self.app, "done", "x.m4a.part"), "wb").close()
        Q.tidy(self.app, NOON)
        self.assertEqual([x for x in os.listdir(Q.qdir(self.app, "done")) if x != Q.STAGE], [])


if __name__ == "__main__":
    unittest.main()
