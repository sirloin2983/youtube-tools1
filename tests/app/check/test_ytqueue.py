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

    def test_request_aging_never_starves(self):
        """待った時間で研究の頼みの点が上がり、24 時間を超えた頼みは一番上(10-26: 配信全体の音 r-full-* が一度も順番を取れなかった)"""
        self.put_req("r-long-x", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=FULLVIDEO01"})   # 区間なし = 長い音で引かれる
        os.utime(Q.qdir(self.app, "req", "r-long-x.json"), (NOON, NOON))
        self.put_req("r-up-y", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=SHORTVIDE01", "section": [0, 600]})
        os.utime(Q.qdir(self.app, "req", "r-up-y.json"), (NOON + 3600, NOON + 3600))

        def top(now):
            return [o["label"] for o in Q.plan(self.app, R, {}, now=now) if o["kind"] == "request"][0]
        self.assertIn("r-up-y", top(NOON + 3600))                                 # 始めは短い音が上
        sc = lambda now: [o["score"] for o in Q.plan(self.app, R, {}, now=now) if "r-long-x" in o["label"]][0]   # noqa: E731
        self.assertLess(sc(NOON), sc(NOON + 6 * 3600))                            # 待つほど少しずつ上がる
        self.assertEqual(sc(NOON + 23 * 3600) - sc(NOON + 20 * 3600), 0)          # 上限で止まる(1.0 = 20 時間)
        self.assertIn("r-long-x", top(NOON + Q.STARVE_SEC + 60))                  # 24 時間を超えたら一番上
        best = Q.plan(self.app, R, {"ときのそら": 0, "ロボ子さん": 0}, now=NOON + Q.STARVE_SEC + 60)[0]
        self.assertIn("r-long-x", best["label"])                                  # 候補・声だけよりも上

    def test_full_audio_first_in_order(self):
        """配信全体の音(r-full-*)が待っていれば頼んだ順に先に全部・待った時間の点でも割り込まない(10-26 ユーザー)"""
        for i, rid in enumerate(("r-full-b", "r-full-a", "r-up-old")):
            self.put_req(rid, {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=FULLVIDEO0%d" % i,
                               "section": [0, 600] if rid == "r-up-old" else None})
            t = {"r-full-b": NOON, "r-full-a": NOON + 60, "r-up-old": NOON - 3 * 86400}[rid]
            os.utime(Q.qdir(self.app, "req", rid + ".json"), (t, t))
        labels = [o["label"] for o in Q.plan(self.app, R, {"ときのそら": 0, "ロボ子さん": 0}, now=NOON + 3600)]
        self.assertTrue(labels[0].startswith("研究の頼み r-full-b") and labels[1].startswith("研究の頼み r-full-a"), labels)   # 頼んだ順・3 日待った短い音より先
        os.remove(Q.qdir(self.app, "req", "r-full-b.json"))
        os.remove(Q.qdir(self.app, "req", "r-full-a.json"))
        labels = [o["label"] for o in Q.plan(self.app, R, {}, now=NOON + 3600)]
        self.assertTrue(labels[0].startswith("研究の頼み r-up-old") and labels[1].startswith("声だけ"), labels)   # 尽きたら 24 時間を超えた頼み → 声の足りない人(10-26)
        os.utime(Q.qdir(self.app, "req", "r-up-old.json"), (NOON, NOON))
        labels = [o["label"] for o in Q.plan(self.app, R, {}, now=NOON + 3600)]
        self.assertTrue(labels[0].startswith("声だけ") and labels[-1].startswith("研究の頼み r-up-old"), labels)   # 飢えていない頼みは声の足りない人より後
        full = {"ときのそら": 2, "ロボ子さん": 2}
        self.assertIn("r-up-old", Q.plan(self.app, R, full, now=NOON + 3600)[0]["label"])   # 声が足りていればふだんの点

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
        with mock.patch.object(Q, "_chat", chat):
            Q.tick(self.app, R, {}, lambda: "処理中", lambda req: "j", self.logs.append, now=NOON)
            self.assertEqual(taken, [])                                            # 処理中は取らない
            self.assertEqual(Q.chat_batch(self.app, NOON, self.logs.append), "chat")
            self.assertEqual(len(taken), 10)                                       # 始まりは 10 本
            self.assertIsNone(Q.chat_batch(self.app, NOON + 600, self.logs.append))   # 1 時間に 1 回
        with mock.patch.object(Q, "_chat", lambda *a: (None, "HTTP Error 429: Too Many Requests")):
            self.assertIsNone(Q.chat_batch(self.app, NOON + 3700, self.logs.append))
        st = Q._state(self.app)
        self.assertGreater(st["light"]["pause"], NOON + 3700)                    # 当たったら軽い物の側が休む
        self.assertEqual(len(Q.requests(self.app)), 2)                           # 頼みは残す
        self.assertEqual(Q.chat_n(st), 5)                                         # 当たったら半分(10 本 → 5 本)
        with Q.run_lock(self.app) as a, Q.run_lock(self.app) as b:
            self.assertEqual((a, b), (True, False))                               # 列の錠は 1 つだけ
        with Q.run_lock(self.app) as a:
            self.assertTrue(a)                                                    # 出たら外れる

    def test_gone_not_counted(self):
        """動画が無い・メンバー限定は枠に数えない(次の見回りで次の 1 本)"""
        full = {"ときのそら": 2, "ロボ子さん": 2}
        self.put_req("g1", {"purpose": "research", "kind": "audio", "url": "https://www.youtube.com/watch?v=GONEVIDEO01", "section": [0, 60]})
        with mock.patch.object(Q, "_audio", lambda *a: (None, "ERROR: [youtube] GONEVIDEO01: Video unavailable")):
            self.tick(NOON, full)
        self.assertTrue(Q.due(self.app, NOON + 60)[0])

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
