# -*- coding: utf-8 -*-
"""録画の部品(recorder/)のテスト。本物の YouTube には繋がない: ffmpeg の lavfi で作った HLS を、手元の HTTP サーバーで
配信中のように少しずつ出し(tests/hls_fixture.py)、--source direct(HLS の URL を直接 ffmpeg に渡す)で録る。

    py -3.12 -m unittest tests/pipeline/ingest/test_recorder.py

- TestRecordRun(通し): 1 つの録画の部品で 4 本を同時に録る。配信中の 1 本は 切断 → 繋ぎ直し(終わりにしない・新しいセッション・
  #EXT-X-DISCONTINUITY)→ 区間の取得(時刻と欠け)→ 部品の終了 → 起動し直して続ける → 停止(#EXT-X-ENDLIST)→ 消す(ごみ箱)。
  ほかに すぐ終わる配信・始まらない配信(取れなかったセッションは残さない)・アーカイブ(頭から速く取れる = 止めてセッションを消す)
- TestStreamlinkPipe(通し): 本番の形(streamlink → ffmpeg)の切断と終わり
- 通しでは起こせない物: 再生リストの名前の検査・URL の検査・置き場所(無いドライブ)・壊れた記録からの復旧・題の取得(YouTube の oEmbed の代わり)・
  HTTP の守り(合言葉・Host・ブラウザから・パス・本文)
"""
import http.client
import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS))), "src", "pipeline", "ingest")   # src/pipeline/ingest(recorder.py のある所)
SRC = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SRC)
sys.path.insert(0, TESTS)
import hls_fixture as F  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402
from pipeline.ingest import rec_core as R  # noqa: E402
from ytt import trashbin  # noqa: E402

FAST = dict(trash_days=3, source="direct", hls_time=1, backoff=(1, 2), idle_end=8, stall_sec=4, first_seg_sec=15, poll=0.3)


def wait_for(fn, timeout=30.0, step=0.2):
    return testkit.wait_for(fn, timeout, step)


free_port = testkit.free_port


_SRC = {}


def source(seconds=40):
    """lavfi の HLS(テストの間で使い回す)"""
    if seconds not in _SRC:
        d = tempfile.mkdtemp(prefix="ytt-rec-src-")
        _SRC[seconds] = (d, F.make_source(d, seconds))
    return _SRC[seconds]


def missing_drive():
    used = {d for d in string.ascii_uppercase if os.path.exists(d + ":\\")}
    for d in "QRSTUVWXYZ":
        if d not in used:
            return d
    return None


class TestPieces(unittest.TestCase):
    def test_playlist_names_and_empty_sessions(self):
        """再生リストは決まった形の名前だけ読む(../ を通さない)・空のセッションは区切りに数えない(録画の ffmpeg は決まった名前しか書かず、
        空のセッションは残さないので、通しでは起こせない)"""
        text = ("#EXTM3U\n#EXT-X-PROGRAM-DATE-TIME:2026-10-04T15:30:12.345+0900\n#EXTINF:4.000000,\nseg_000000.ts\n"
                "#EXTINF:4.0,\n../evil.ts\n#EXT-X-ENDLIST\n")
        segs, ended = R.parse_playlist(text)
        self.assertTrue(ended)
        self.assertEqual([s["uri"] for s in segs], ["seg_000000.ts"])
        self.assertEqual(segs[0]["pdt"], "2026-10-04T06:30:12.345Z")
        out = R.build_playlist([("session_001", segs), ("session_002", []), ("session_003", segs)], finished=False)
        self.assertEqual(out.count("#EXT-X-DISCONTINUITY"), 1)
        self.assertIn("session_003/seg_000000.ts", out)

    def test_pick_segments_reconnect_gap(self):
        """繋ぎ直しの間の欠けと、受信時刻の揺れ(1 秒より短い)は欠けにしないこと。手元の HLS は最初の数本を一度に出すので受信時刻が実際より先に進み、
        通しでは繋ぎ直しの間が受信時刻に決まった長さで出ない"""
        base = R.iso_epoch("2026-10-04T06:00:00Z")
        flat = [{"uri": "s1/a", "pdt": R.epoch_iso(base + i * 4), "dur": 4.0} for i in range(5)]               # 0〜20 秒
        flat += [{"uri": "s2/b", "pdt": R.epoch_iso(base + 30 + i * 4), "dur": 4.0} for i in range(3)]         # 30〜42 秒(繋ぎ直しの間 20〜30)
        segs, gaps = R.pick_segments(flat, base + 18, base + 33)
        self.assertEqual(len(segs), 2)
        self.assertEqual(gaps, [(base + 20, base + 30)])
        flat2 = [dict(flat[0]), dict(flat[1], pdt=R.epoch_iso(base + 4.5))]
        self.assertEqual(R.pick_segments(flat2, base, base + 8)[1], [])
        self.assertEqual(R.iso_epoch("2026-10-04T06:00:00.250Z"), base + 0.25)
        self.assertEqual(R.iso_epoch("2026-10-04T06:00:00+00:00"), base)
        for bad in (None, "", "2026-10-04 06:00:00", "x" * 50, 5):
            self.assertIsNone(R.iso_epoch(bad))

    def test_keep_order_after_reconnect(self):
        """繋ぎ直しのあとの頭の受信時刻が前のセッションの終わりを下回るとき(手元の HLS で約 0.4 秒)だけ後ろへ送る。下回らない所・空のセッション・元の一覧は変えない"""
        base = R.iso_epoch("2026-10-04T06:00:00Z")
        seg = lambda t, d=4.0: {"uri": "x", "pdt": R.epoch_iso(base + t), "dur": d}   # noqa: E731
        s1 = [seg(0), seg(4)]                        # 終わりは 8 秒
        s2 = [seg(7.6), seg(11.6), seg(16.5)]        # 頭 2 本が前のセッションの終わり(8 秒)から詰めた位置より前
        out = R.keep_order([("session_001", s1), ("session_002", []), ("session_003", s2)])
        self.assertEqual([R.iso_epoch(x["pdt"]) - base for x in out[2][1]], [8.0, 12.0, 16.5])   # 3 本目は詰めた終わり(16 秒)以降なので動かさない
        self.assertEqual(out[0][1], s1)
        self.assertAlmostEqual(R.iso_epoch(s2[0]["pdt"]) - base, 7.6, places=3)
        ok = [seg(8.3)]
        self.assertEqual(R.keep_order([("session_001", s1), ("session_002", ok)])[1][1], ok)

    def test_validate_url(self):
        for ok in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/live/dQw4w9WgXcQ",
                   "https://www.youtube.com/@channel/live", "https://m.youtube.com/watch?v=abc"):
            self.assertEqual(R.validate_url(ok), ok)
        for bad in ("http://www.youtube.com/watch?v=x", "https://evil.example/watch?v=x", "https://youtube.com.evil.example/",
                    "https://user@www.youtube.com/", "file:///C:/x", "https://www.youtube.com:8443/x", "", "https://www.youtube.com/a b", None, 3):
            with self.assertRaises(R.RecError, msg=repr(bad)):
                R.validate_url(bad)
        self.assertEqual(R.validate_url("http://127.0.0.1:9/live.m3u8", allow_local=True), "http://127.0.0.1:9/live.m3u8")
        with self.assertRaises(R.RecError):   # テストの取得でも外へは出ない
            R.validate_url("https://www.youtube.com/watch?v=x", allow_local=True)

    def test_new_rec_id(self):
        rid = R.new_rec_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1")
        self.assertRegex(rid, r"^\d{8}-\d{6}-dQw4w9WgXcQ$")
        self.assertTrue(R.REC_ID_RE.match(R.new_rec_id("http://127.0.0.1:1/live.m3u8")))
        self.assertTrue(R.REC_ID_RE.match(R.new_rec_id("https://youtu.be/<script>")))

    def test_folder_state(self):
        tmp = tempfile.mkdtemp(prefix="ytt-rec-fs-")
        try:
            st = R.folder_state(os.path.join(tmp, "まだ無い", "live-rec"))
            self.assertTrue(st["ok"], st)
            self.assertGreater(st["freeBytes"], 0)
            self.assertFalse(R.folder_state("relative\\path")["ok"])
            d = missing_drive()
            if d:
                st = R.folder_state(d + ":\\Video\\live-rec")
                self.assertFalse(st["ok"])
                self.assertIn(d + ":", st["message"])   # 作業データへ逃がさず、案内する
                self.assertIsNone(st["freeBytes"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

class TestRecording(unittest.TestCase):
    """Recorder を同じプロセスで(通しでは起こせない状態: 無いドライブ・前回の録画中に落ちた記録・手で書き換えた記録)"""

    def setUp(self):
        self.src_dir, self.segs = source(40)
        self.tmp = testkit.tempdir(self, prefix="ytt-rec-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.logs = []
        self.srv = F.LiveServer(self.src_dir, self.segs, start=3, rate=1.0)
        self.rec = R.Recorder(self.folder, log=self.logs.append, **FAST)

    def tearDown(self):
        self.rec.close()
        self.srv.close()

    def test_folder_missing_is_refused(self):
        d = missing_drive()
        if not d:
            self.skipTest("使っていないドライブ名がありません")
        rec = R.Recorder(d + ":\\Video\\live-rec", **FAST)
        with self.assertRaises(R.RecError) as cm:
            rec.start(self.srv.url)
        self.assertEqual(cm.exception.status, 409)
        self.assertFalse(rec.overview()["folderOk"])

    def test_recover_on_start(self):
        """前回の録画中に落ちた: 書きかけを消す・読めないセッションは使えない印・前のセッションは中断・新しいセッションで続ける"""
        rid = "20261004-120000-recover"
        d = os.path.join(self.folder, rid)
        s1 = os.path.join(d, "session_001")
        os.makedirs(s1)
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:1", "#EXT-X-PLAYLIST-TYPE:EVENT"]
        for i, (name, dur) in enumerate(self.segs[:3]):
            shutil.copy(os.path.join(self.src_dir, name), os.path.join(s1, "seg_%06d.ts" % i))
            lines += ["#EXT-X-PROGRAM-DATE-TIME:2026-10-04T12:00:0%d.000+0900" % i, "#EXTINF:%.6f," % dur, "seg_%06d.ts" % i]
        with open(os.path.join(s1, "index.m3u8"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        open(os.path.join(s1, "seg_000003.ts.tmp"), "wb").close()
        open(os.path.join(s1, "index.m3u8.tmp"), "wb").close()
        s2 = os.path.join(d, "session_002")
        os.makedirs(s2)
        with open(os.path.join(s2, "index.m3u8"), "wb") as f:
            f.write(b"\x00\x01garbage")
        meta = {"schema": R.SCHEMA, "id": rid, "url": self.srv.url, "quality": "best", "title": "", "state": "recording", "message": "",
                "created": "2026-10-04T03:00:00.000Z", "endedAt": None,
                "sessions": [{"name": "session_001", "state": "recording", "started": None}, {"name": "session_002", "state": "recording"}]}
        with open(os.path.join(d, "recording.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)
        resumed = self.rec.load()
        self.assertEqual(resumed, [rid])
        self.assertFalse([x for x in os.listdir(s1) if x.endswith(".tmp")])   # 書きかけを消した
        r = self.rec.get(rid)
        info = {x["name"]: x for x in r.meta["sessions"]}
        self.assertEqual(info["session_001"]["state"], "interrupted")
        self.assertEqual(info["session_002"]["state"], "broken")
        self.assertTrue(wait_for(lambda: "session_003" in r.session_names() and r.session_segments("session_003")[0], 30), (r.summary(), self.logs))
        pl = r.playlist()
        self.assertIn("session_001/seg_000000.ts", pl)
        self.assertNotIn("session_002/", pl)
        self.assertIn("#EXT-X-DISCONTINUITY", pl)

    def test_recover_bad_sessions(self):
        """手で書き換えた recording.json の sessions(null・リストでない・中に dict でない物)でも復旧で落ちない:
        空として読み、セッションのフォルダから付け直す・録画中だった物は新しいセッションで続ける"""
        base = {"schema": R.SCHEMA, "url": self.srv.url, "quality": "best", "title": "", "message": "",
                "created": "2026-10-04T03:00:00.000Z", "endedAt": None}
        cases = {"20261004-120001-nullsess": ("stopped", None), "20261004-120002-strsess": ("stopped", "x"),
                 "20261004-120003-junksess": ("stopped", ["junk", 3, {"name": "session_001", "state": "recording"}]),
                 "20261004-120004-activenull": ("recording", None)}
        for rid, (state, sessions) in cases.items():
            d = os.path.join(self.folder, rid)
            os.makedirs(d)
            if state == "stopped":   # 再生リストのあるセッション 1 つ
                s1 = os.path.join(d, "session_001")
                os.makedirs(s1)
                name, dur = self.segs[0]
                shutil.copy(os.path.join(self.src_dir, name), os.path.join(s1, "seg_000000.ts"))
                with open(os.path.join(s1, "index.m3u8"), "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n#EXT-X-PROGRAM-DATE-TIME:2026-10-04T12:00:00.000+0900\n#EXTINF:%.6f,\nseg_000000.ts\n#EXT-X-ENDLIST\n" % dur)
            with open(os.path.join(d, "recording.json"), "w", encoding="utf-8") as f:
                json.dump(dict(base, id=rid, state=state, sessions=sessions), f)
        self.assertEqual(self.rec.load(), ["20261004-120004-activenull"])
        for rid in list(cases)[:3]:
            r = self.rec.get(rid)
            want = "interrupted" if "junk" in rid else None   # dict の記録は残る(録画中だった = 中断)・無ければフォルダから付け直す
            self.assertEqual([(x["name"], x.get("state")) for x in r.meta["sessions"]], [("session_001", want)], rid)
            with open(os.path.join(r.dir, "recording.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["sessions"], r.meta["sessions"])   # 直した形で書き直した
            self.assertEqual(r.summary(detail=True)["sessions"], 1)
        r = self.rec.get("20261004-120004-activenull")
        self.assertTrue(wait_for(lambda: r.session_segments("session_001")[0], 30), (r.summary(), self.logs))   # 新しいセッションで録画を続けた
        self.assertEqual([x["name"] for x in r.meta["sessions"]], ["session_001"])


def have_streamlink():
    import importlib.util
    return importlib.util.find_spec("streamlink") is not None


class TestRecordRun(unittest.TestCase):
    """録画の通し: 手元の HLS を本物の ffmpeg で録る。--source direct の録画の部品で 4 本、同時に本番の形(streamlink → ffmpeg。
    streamlink の hls:// で手元の HLS を読む。YouTube の URL の検査だけ外す)の別の部品で 2 本(streamlink が無ければ direct だけ)"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, prefix="ytt-rec-run-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.logs = []
        src_dir, segs = source(40)
        arc_dir, arc_segs = source(120)
        self.live = F.LiveServer(src_dir, segs, start=3, rate=1.0)
        self.live.end = False                                              # まだ配信中(終わりの印を出さない)
        self.short = F.LiveServer(src_dir, segs[:16], start=3, rate=4.0)   # 早く出し終える → 終わりの印 → 「終了」
        self.before = F.LiveServer(src_dir, segs, start=3, rate=1.0)
        self.before.down = True                                            # 配信の前(まだ取れない)
        self.archive = F.LiveServer(arc_dir, arc_segs, start=len(arc_segs), rate=1.0)   # 全部見えて終わりの印あり = アーカイブ
        self.servers = [self.live, self.short, self.before, self.archive]
        self.sl = have_streamlink()
        if self.sl:
            self.sl_live = F.LiveServer(src_dir, segs, start=3, rate=1.0)
            self.sl_live.end = False
            self.sl_short = F.LiveServer(src_dir, segs[:16], start=3, rate=4.0)
            self.servers += [self.sl_live, self.sl_short]
            p = mock.patch.object(R, "validate_url", lambda url, allow_local=False: url)
            p.start()
            self.addCleanup(p.stop)
        self.recs = []

    def tearDown(self):
        for rec in self.recs:
            rec.close()
        for srv in self.servers:
            srv.close()

    def recorder(self, folder=None, **kw):
        rec = R.Recorder(folder or self.folder, log=self.logs.append, **dict(FAST, **kw))
        rec.wait_start = 3
        self.recs.append(rec)
        return rec

    def gaps(self, r, a, b):
        return [(R.iso_epoch(g["from"]), R.iso_epoch(g["to"])) for g in r.segments_in(R.epoch_iso(a), R.epoch_iso(b))["gaps"]]

    def check_segments(self, r):
        """区間にかかるセグメントと欠け(書き出しが録画元の GET /live/<id>/segments で聞く): 録画の前の頭・まだ録れていない終わり・
        同じセッションの中は受信時刻が揺れても欠けにしない・繋ぎ直しの前後のセッションを時刻の順に。区間の検査"""
        (n1, s1), (n2, s2) = r.all_segments()[:2]
        e = lambda x: R.iso_epoch(x["pdt"])   # noqa: E731
        first = e(s1[0])
        head = self.gaps(r, first - 10, first + 2)
        self.assertEqual(len(head), 1)
        self.assertAlmostEqual(head[0][0], first - 10, delta=0.01)
        self.assertAlmostEqual(head[0][1], first, delta=0.01)
        self.assertEqual(self.gaps(r, first + 0.5, e(s1[-1])), [])
        a, b = e(s1[-2]), max(e(s1[-1]) + s1[-1]["dur"], e(s2[1]))
        got = r.segments_in(R.epoch_iso(a), R.epoch_iso(b))
        self.assertEqual(sorted({x["session"] for x in got["segments"]}), [n1, n2])
        self.assertEqual([x["pdt"] for x in got["segments"]], sorted(x["pdt"] for x in got["segments"]))
        last = r.all_segments()[-1][1][-1]
        tail = self.gaps(r, e(last), e(last) + 30)
        self.assertGreaterEqual(tail[-1][0], e(last) + last["dur"] - 0.01)
        self.assertAlmostEqual(tail[-1][1], e(last) + 30, delta=0.01)
        for a, b in (("x", "y"), (R.epoch_iso(first + 5), R.epoch_iso(first)), (R.epoch_iso(first), R.epoch_iso(first + 4 * 3600))):
            with self.assertRaises(R.RecError):
                r.segments_in(a, b)

    def test_run(self):
        rec = self.recorder()
        r = rec.get(rec.start(self.live.url, "best", "テスト<b>")["id"])
        short = rec.get(rec.start(self.short.url)["id"])
        before = rec.get(rec.start(self.before.url)["id"])
        self.assertTrue(wait_for(lambda: before.summary()["state"] == "waiting", 5), before.summary())   # 始まるまで待つ(失敗にしない)
        arc =rec.get(rec.start(self.archive.url)["id"])
        if self.sl:   # streamlink は切断でも終了コード 0 で終わる。記録の「No new segments」で見分けて、終わりにせず繋ぎ直す
            slrec = self.recorder(os.path.join(self.tmp, "live-rec-sl"), source="streamlink", stall_sec=8, first_seg_sec=25)
            os.makedirs(slrec.folder)
            sl = slrec.get(slrec.start("hls://" + self.sl_live.url)["id"])
            sl_short = slrec.get(slrec.start("hls://" + self.sl_short.url)["id"])
        self.assertTrue(wait_for(lambda: r.summary()["segments"] >= 4), self.logs)
        self.assertEqual(r.summary()["state"], "recording")
        self.assertTrue(r.summary()["firstPdt"].endswith("Z"))   # 受信時刻(ffmpeg は手元の時刻帯で書く)は UTC にそろえる
        with self.assertRaises(R.RecError):   # 同じ配信の二重録画は断る
            rec.start(self.live.url)
        with self.assertRaises(R.RecError) as cm:
            rec.delete(r.id)
        self.assertEqual(cm.exception.status, 409)   # 録画中は消さない
        for bad in (None, 3, "", "x", "../" + r.id, r.id + "/..", "20261004-000000/../../x", "..\\" + r.id, r.id + "\\session_001"):
            with self.assertRaises(R.RecError, msg=repr(bad)) as cm:
                rec.delete(bad)
            self.assertEqual(cm.exception.status, 400, bad)

        # 切断は終わりにしない: 繋ぎ直して新しいセッション
        n1 = r.summary()["segments"]
        if self.sl:
            self.assertTrue(wait_for(lambda: sl.summary()["segments"] >= 3, 40), (sl.summary(), self.logs))
            self.sl_live.down = True
            m1 = sl.summary()["segments"]
        self.live.down = True
        self.assertTrue(wait_for(lambda: r.summary()["state"] == "reconnecting", 20), (r.summary(), self.logs))
        if self.sl:
            self.assertTrue(wait_for(lambda: sl.summary()["state"] == "reconnecting", 40), (sl.summary(), self.logs))
            self.sl_live.down = False
        self.live.down = False
        self.assertTrue(wait_for(lambda: r.summary()["sessions"] >= 2 and r.summary()["segments"] > n1 + 2, 40), (r.summary(), self.logs))
        if self.sl:
            self.assertTrue(wait_for(lambda: sl.summary()["sessions"] >= 2 and sl.summary()["segments"] > m1, 60), (sl.summary(), self.logs))
            self.assertEqual(slrec.stop(sl.id)["state"], "stopped")
            self.assertTrue(wait_for(lambda: sl_short.summary()["state"] == "ended", 60), (sl_short.summary(), self.logs))   # 切断のない普通の終わり
            self.assertEqual(sl_short.summary()["sessions"], 1)
        pl = r.playlist()
        self.assertIn("#EXT-X-DISCONTINUITY", pl)
        self.assertIn("session_002/seg_", pl)
        self.assertNotIn("#EXT-X-ENDLIST", pl)
        self.check_segments(r)

        # 同時に録っていたほかの 3 本
        self.assertTrue(wait_for(lambda: short.summary()["state"] == "ended", 40), (short.summary(), self.logs))
        self.assertGreater(short.summary()["segments"], 5)
        self.assertEqual(short.summary()["sessions"], 1)
        self.assertIn("#EXT-X-ENDLIST", short.playlist())
        self.assertTrue(wait_for(lambda: before.summary()["state"] == "ended", 30), (before.summary(), self.logs))   # 待つ上限(縮めた)で諦める
        self.assertEqual(before.session_names(), [])   # 取れなかったセッションは残さない
        self.assertTrue(wait_for(lambda: arc.summary()["state"] == "ended", 60), arc.summary())
        self.assertIn("アーカイブ", arc.summary()["message"])
        self.assertEqual(arc.session_names(), [])   # 頭から速く取れたセッション(受信時刻が合わない)は消す

        # 録画の部品そのものを終えた(入口の「すべて終了」では呼ばれない)→ 起動し直すと、録画中だった 1 本だけ新しいセッションで続ける
        rec.close()
        self.assertIn(r.meta["state"], R.ACTIVE)
        rec = self.recorder()
        self.assertEqual(rec.load(), [r.id])
        r = rec.get(r.id)
        self.assertTrue(wait_for(lambda: "session_003" in r.session_names() and r.session_segments("session_003")[0], 30), (r.summary(), self.logs))
        st = rec.stop(r.id)
        self.assertEqual(st["state"], "stopped")
        pl = r.playlist()
        self.assertIn("#EXT-X-ENDLIST", pl)
        self.assertEqual(pl.count("#EXT-X-DISCONTINUITY"), 2)
        for n in r.session_names():   # 止めたあとに書きかけが残らない
            self.assertFalse([x for x in os.listdir(os.path.join(r.dir, n)) if x.endswith(".tmp")])
        with open(os.path.join(r.dir, "recording.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual((meta["state"], meta["title"]), ("stopped", "テスト<b>"))
        self.check_delete(rec, r)

    def check_delete(self, rec, r):
        """「録画を自動で消す」: 置き場所の直下で recording.json があるものだけ・リンク(ジャンクション)の先は消さない・使用中のファイルがあれば 409 で
        何も動かさず、あとでまた消せる。消すのは 置き場所/ごみ箱/<日付>/録画/<id> へ改名(manifest.jsonl に元の場所)・3 日より古い日付のフォルダは purge_trash で消える"""
        rid = r.id
        held = open(os.path.join(r.dir, "session_001", "seg_000000.ts"), "rb")   # 使用中(再生中の画面がセグメントを読んでいる など)
        try:
            with self.assertRaises(R.RecError) as cm:
                rec.delete(rid)
            self.assertEqual(cm.exception.status, 409)
            self.assertIn("使用中", str(cm.exception))
            self.assertTrue(os.path.isfile(os.path.join(r.dir, "recording.json")))
            self.assertIs(rec.get(rid), r)
        finally:
            held.close()
        self.assertEqual(rec.delete(rid), rid)   # 閉じたら消せる
        self.assertFalse(os.path.exists(os.path.join(self.folder, rid)))
        day = os.path.join(self.folder, R.TRASH_DIR, trashbin.day_name())
        self.assertTrue(os.path.isfile(os.path.join(day, R.TRASH_KIND, rid, "recording.json")))   # ごみ箱へ移した(3 日は戻せる)
        with open(os.path.join(day, trashbin.MANIFEST), encoding="utf-8") as f:
            row = json.loads(f.readline())
        self.assertEqual((row["from"], row["to"], row["kind"]), (os.path.join(self.folder, rid), os.path.join(day, R.TRASH_KIND, rid), R.TRASH_KIND))
        self.assertEqual(rec.load(), [])   # ごみ箱は録画として読まない
        for fn in (rec.get, rec.delete):
            with self.assertRaises(R.RecError) as cm:
                fn(rid)
            self.assertEqual(cm.exception.status, 404)
        plain = os.path.join(self.folder, "20261004-000000-plain")   # recording.json の無いフォルダ(録画ではない)は消さない
        os.makedirs(plain)
        open(os.path.join(plain, "keep.txt"), "wb").close()
        with self.assertRaises(R.RecError) as cm:
            rec.delete("20261004-000000-plain")
        self.assertEqual(cm.exception.status, 404)
        self.assertTrue(os.path.isfile(os.path.join(plain, "keep.txt")))
        outside = os.path.join(self.tmp, "outside")   # 置き場所の中のジャンクションの先(置き場所の外)は消さない
        os.makedirs(outside)
        with open(os.path.join(outside, "recording.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        link = os.path.join(self.folder, "20261004-000000-link")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", link, outside], capture_output=True, creationflags=F.NO_WINDOW).returncode == 0 if os.name == "nt" else False
        if not made:
            try:
                os.symlink(outside, link, target_is_directory=True)
                made = True
            except (OSError, NotImplementedError):
                pass
        if made:
            with self.assertRaises(R.RecError):
                rec.delete("20261004-000000-link")
            self.assertTrue(os.path.isfile(os.path.join(outside, "recording.json")))
            os.rmdir(link) if os.name == "nt" else os.unlink(link)
        rid2 = "20261004-000000-inner"   # 録画のフォルダの中のジャンクションは、それ自体だけ外して先(置き場所の外)は消さない
        d2 = os.path.join(self.folder, rid2)
        os.makedirs(os.path.join(d2, "session_001"))
        inner = os.path.join(outside, "inner")
        os.makedirs(inner)
        open(os.path.join(inner, "keep.ts"), "wb").close()
        with open(os.path.join(d2, "recording.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        j2 = os.path.join(d2, "session_002")
        if os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", j2, inner], capture_output=True, creationflags=F.NO_WINDOW).returncode == 0:
            self.assertEqual(rec.delete(rid2), rid2)
            self.assertTrue(os.path.isfile(os.path.join(inner, "keep.ts")))
            self.assertFalse(os.path.exists(d2))
        old = os.path.join(self.folder, R.TRASH_DIR, "2020-01-01", R.TRASH_KIND, "20200101-000000-old")   # 3 日より古い日付のフォルダは消える
        os.makedirs(old)
        self.assertEqual(rec.purge_trash(), 1)
        self.assertFalse(os.path.exists(os.path.dirname(os.path.dirname(old))))
        self.assertTrue(os.path.isdir(day))
        if made:
            self.assertTrue(os.path.isfile(os.path.join(inner, "keep.ts")))   # ごみ箱を消しても、外して移したジャンクションの先は残る


class TestStreamlinkPipe(unittest.TestCase):
    """本番の形(streamlink の出力 → ffmpeg の標準入力)のコマンドと画質(切断と終わりの通しは TestRecordRun)"""

    def setUp(self):
        if not have_streamlink():
            self.skipTest("streamlink が入っていません(py -3.12 -m pip install -r setup/requirements.txt)")
        self.tmp = testkit.tempdir(self, prefix="ytt-rec-sl-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.rec = R.Recorder(self.folder, **dict(FAST, source="streamlink"))

    def tearDown(self):
        self.rec.close()

    def test_commands_are_argument_lists(self):
        r = R.Recording(self.rec, "20261004-000000-x", os.path.join(self.folder, "x"),
                        {"url": "https://www.youtube.com/watch?v=x;rm -rf", "quality": "720p"})
        src, ff = r._commands("session_001")
        self.assertEqual(src[1:5], ["-m", "streamlink", "--stdout", "--loglevel"])
        self.assertIn("--stream-types", src)                    # hls だけ = 終わった配信(アーカイブ)を取りに行かない
        self.assertEqual(src[-2:], ["https://www.youtube.com/watch?v=x;rm -rf", "720p60,720p,best"])   # シェルを通さない(1つの引数のまま)
        self.assertEqual(ff[ff.index("-i") + 1], "pipe:0")
        self.assertIn("-c", ff)
        self.assertEqual(ff[ff.index("-c") + 1], "copy")
        self.assertIn("temp_file+program_date_time", ff)

    def test_bot_block_resolves_hls_with_cookies(self):
        """YouTube に bot と判定された(streamlink の記録に 429)= yt-dlp(ログインの cookies つき)で再生リストを取って hls:// で録る。
        取れなければ bot の印のある記録だけを「判定された」とみなす(10-21 友人のライブが 1 秒も録れず 0 本だった件)"""
        r = R.Recording(self.rec, "20261021-000000-z", os.path.join(self.folder, "z"), {"url": "https://www.youtube.com/watch?v=z", "quality": "1080p"})
        sdir = os.path.join(r.dir, "session_001")
        os.makedirs(sdir)
        log = os.path.join(sdir, "source.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write("error: Unable to open URL: https://www.youtube.com/watch?v=z (429 Client Error: Too Many Requests for url: https://www.google.com/sorry/index)\n")
        self.assertTrue(r._blocked("session_001"))
        self.rec.ytdlp = "yt-dlp-fake"
        cookies = os.path.join(self.tmp, "cookies.txt")
        with open(cookies, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
        seen = []

        def run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"https://manifest.googlevideo.com/api/manifest/hls_playlist/x/index.m3u8\n", b"")
        with mock.patch.dict(os.environ, {"YTT_YTDLP_COOKIES": cookies}), mock.patch.object(R.subprocess, "run", run):
            self.assertTrue(r._resolve_hls())
        self.assertIn("--cookies", seen[0])
        self.assertEqual(seen[0][-2:], ["--", "https://www.youtube.com/watch?v=z"])
        src, _ff = r._commands("session_002")
        self.assertEqual(src[-2:], ["hls://https://manifest.googlevideo.com/api/manifest/hls_playlist/x/index.m3u8", "best"])
        self.assertTrue(r._blocked("session_002"))   # 取った再生リストでも取れなかった = 取り直す(期限切れ)
        self.assertIsNone(r._hls)
        with open(log, "w", encoding="utf-8") as f:
            f.write("[cli][error] No playable streams found on this URL\n")
        self.assertFalse(r._blocked("session_001"))   # 配信の前などは bot ではない

    def test_bot_block_even_with_resolved_hls_is_marked_and_gives_up(self):
        """yt-dlp で再生リストは取れたのに、それでも録れない(10-21 19:00 の本物のライブ = 10 分「録画中」のまま何も出なかった):
        記録に blockedAt と BLOCKED を出し、1 つも取れないまま BLOCKED_GIVE_UP たったら「エラー」で止める(偽の 429)"""
        r = R.Recording(self.rec, "20261021-190000-y", os.path.join(self.folder, "y"), {"url": "https://www.youtube.com/watch?v=y", "quality": "1080p"})
        os.makedirs(r.dir, exist_ok=True)
        resolved = []

        def session(name):
            os.makedirs(os.path.join(r.dir, name), exist_ok=True)
            with open(os.path.join(r.dir, name, "source.log"), "w", encoding="utf-8") as f:
                f.write("error: Unable to open URL (429 Client Error: Too Many Requests)\n")
            return 0, 1, "切れました"

        def resolve():
            resolved.append(1)
            r._hls = "https://manifest.googlevideo.com/x/index.m3u8"
            return True
        with mock.patch.object(r, "_run_session", session), mock.patch.object(r, "_resolve_hls", resolve), \
                mock.patch.object(R, "BLOCKED_GIVE_UP", 1.5), mock.patch.object(R, "BLOCKED_WAIT", 0):
            t = threading.Thread(target=r._run, daemon=True)
            t.start()
            self.assertTrue(wait_for(lambda: r.meta.get("blockedAt"), 10), r.meta)
            self.assertTrue(r.summary()["blockedAt"])
            t.join(20)
        self.assertFalse(t.is_alive())
        self.assertEqual((r.meta["state"], r.meta["message"]), ("error", R.BLOCKED))
        self.assertGreaterEqual(len(resolved), 2)   # 取り直しはする
        self.assertIsNone(r.summary()["blockedAt"])   # 止めたあとは出さない

    def test_expired_hls_after_recording_is_renewed_without_bot_mark(self):
        """取った再生リストで録れていたのに 0 になった(約 6 時間の期限切れなど・記録に bot の印なし)= 取り直すだけ。
        blockedAt(友人の知らせ)は出さず、つなぎ直しも BLOCKED_WAIT を待たない"""
        r = R.Recording(self.rec, "20261022-230000-v", os.path.join(self.folder, "v"), {"url": "https://www.youtube.com/watch?v=v", "quality": "1080p"})
        os.makedirs(r.dir, exist_ok=True)
        r._hls = "https://manifest.googlevideo.com/old/index.m3u8"
        runs, resolved, waits, marks = [], [], [], []

        def session(name):
            os.makedirs(os.path.join(r.dir, name), exist_ok=True)
            with open(os.path.join(r.dir, name, "source.log"), "w", encoding="utf-8") as f:
                f.write("[cli][error] Unable to open URL: hls://… (403 Client Error: Forbidden)\n")
            runs.append(name)
            if len(runs) >= 3:
                r._stop.set()
            return (5, 1, "切れました") if len(runs) == 1 else (0, 1, "切れました")

        def resolve():
            resolved.append(1)
            r._hls = "https://manifest.googlevideo.com/new/index.m3u8"
            return True
        real_set = r.set

        def set_(**kw):
            if kw.get("blockedAt"):
                marks.append(kw["blockedAt"])
            return real_set(**kw)
        with mock.patch.object(r, "_run_session", session), mock.patch.object(r, "_resolve_hls", resolve), \
                mock.patch.object(r, "_wait", lambda sec: waits.append(sec)), mock.patch.object(r, "set", set_), \
                mock.patch.object(r, "_session_mark", lambda *a, **kw: None), mock.patch.object(r, "all_segments", lambda: [("session_001", runs[:1])]):
            r._run()
        self.assertGreaterEqual(len(resolved), 1)   # 取り直した
        self.assertEqual(marks, [])                 # bot の知らせは出さない
        self.assertTrue(waits and max(waits) < R.BLOCKED_WAIT, waits)

    def test_bot_block_without_cookies_does_not_repeat_ytdlp(self):
        """10-21 19:00 の形: cookie が無く yt-dlp も「Sign in to confirm」で断られる = 35 秒ごとに yt-dlp を呼び直していた。
        断られたら HLS_RETRY_SEC は呼ばない・つなぎ直しは BLOCKED_WAIT あける・記録は blockedAt と BLOCKED(偽の 429・偽の yt-dlp)"""
        r = R.Recording(self.rec, "20261021-190043-w", os.path.join(self.folder, "w"), {"url": "https://www.youtube.com/watch?v=w", "quality": "1080p"})
        os.makedirs(r.dir, exist_ok=True)
        calls, waits = [], []

        def session(name):
            os.makedirs(os.path.join(r.dir, name), exist_ok=True)
            with open(os.path.join(r.dir, name, "source.log"), "w", encoding="utf-8") as f:
                f.write("error: Unable to open URL (429 Client Error: Too Many Requests)\n")
            return 0, 1, "切れました"

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, b"", "ERROR: [youtube] w: Sign in to confirm you’re not a bot.\n".encode("utf-8"))
        self.rec.ytdlp = "yt-dlp-fake"
        with mock.patch.object(r, "_run_session", session), mock.patch.object(R.subprocess, "run", run), \
                mock.patch.object(r, "_wait", lambda sec: (waits.append(sec), time.sleep(0.05))), mock.patch.object(R, "BLOCKED_GIVE_UP", 1.0):
            r._run()
        self.assertEqual((r.meta["state"], r.meta["message"]), ("error", R.BLOCKED))
        self.assertEqual(len(calls), 1)   # 断られてからは呼ばない
        self.assertTrue(waits and min(waits) >= R.BLOCKED_WAIT, waits)

    def test_default_quality_is_1080p(self):
        """画質の既定は 1080p(4K の配信で容量が膨らむのを避ける)。720p・best も選べる"""
        import inspect
        self.assertEqual(R.DEFAULT_QUALITY, "1080p")
        self.assertEqual(inspect.signature(R.Recorder.start).parameters["quality"].default, "1080p")
        r = R.Recording(self.rec, "20261004-000000-y", os.path.join(self.folder, "y"), {"url": "https://www.youtube.com/watch?v=y", "quality": R.DEFAULT_QUALITY})
        self.assertEqual(r._commands("session_001")[0][-1], "1080p60,1080p,best")
        for q in ("best", "720p"):
            self.assertIn(q, R.QUALITIES)


class TestTitle(unittest.TestCase):
    """名前なしで始めた録画に配信の題を付ける(fetch_title = YouTube の oEmbed。テストは手元の HTTP サーバーを endpoint にする)"""

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        cls.seen = []
        owner = cls

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                owner.seen.append(self.path)
                route = self.path.split("?")[0]
                code, body = 200, b""
                if route == "/ok":
                    body = json.dumps({"title": "【雑談】配信の\x07題 <b> ", "author_name": "x"}).encode("utf-8")
                elif route == "/long":
                    body = json.dumps({"title": "あ" * 500}).encode("utf-8")
                elif route == "/notitle":
                    body = b'{"author_name": "x"}'
                elif route == "/numtitle":
                    body = b'{"title": 5}'
                elif route == "/list":
                    body = b'["title"]'
                elif route == "/html":
                    body = b"<html>not json</html>"
                elif route == "/slow":
                    time.sleep(6)
                    body = b'{"title": "slow"}'
                else:
                    code, body = 404, b'{"error": "not found"}'
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.httpd.daemon_threads = True
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        # 配信の無い手元の URL の番号: 待ち受けはあるので ffmpeg はすぐ断られる(空きの番号だと Windows はつなぐのに 2 秒ほど粘り、止めるのが遅い)
        cls.no_live = cls.httpd.server_address[1]
        import threading
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = testkit.tempdir(self, prefix="ytt-rec-title-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.rec = R.Recorder(self.folder, **FAST)

    def tearDown(self):
        for r in list(self.rec.recs.values()):
            if r.active:
                self.rec.stop(r.id)
        self.rec.close()

    def test_fetch_title(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1"
        self.assertEqual(R.fetch_title(url, endpoint=self.base + "/ok"), "【雑談】配信の題 <b>")   # 制御文字は除く・HTML にはしない(文字のまま)
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.seen[-1]).query)
        self.assertEqual((q["url"], q["format"]), ([url], ["json"]))                              # URL は1つの値として渡す
        self.assertEqual(R.fetch_title(url, endpoint=self.base + "/long"), "あ" * R.TITLE_MAX)
        for bad in ("/notitle", "/numtitle", "/list", "/html", "/missing"):
            self.assertEqual(R.fetch_title(url, endpoint=self.base + bad), "", bad)
        t = time.time()
        self.assertEqual(R.fetch_title(url, endpoint=self.base + "/slow", timeout=0.5), "")      # 時間切れ
        self.assertLess(time.time() - t, 5.0)   # 返事(6 秒後)を待たずに戻った = 時間切れが効いた(負荷で 0.5 秒が延びても揺れない幅)
        self.assertEqual(R.fetch_title(url, endpoint="http://127.0.0.1:%d/x" % free_port()), "")   # つながらない

    def test_lookup_only_for_streamlink(self):
        self.assertIsNone(self.rec.title_lookup)                                       # direct(テスト)では聞かない
        self.assertIs(R.Recorder(self.folder, source="streamlink", trash_days=3).title_lookup, R.fetch_title)

    def test_untitled_recording_gets_title(self):
        calls = []
        self.rec.title_lookup = lambda url: (calls.append(url), "配信の題")[1]
        url = "https://127.0.0.1:%d/live.m3u8" % self.no_live   # https の手元の URL(配信が無いので録画は「待ち」のまま)
        s = self.rec.start(url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.meta.get("title") == "配信の題", 30), (r.meta, calls))
        self.assertEqual(calls, [url])
        with open(os.path.join(r.dir, "recording.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["title"], "配信の題")   # 記録にも残る
        self.assertEqual(self.rec.get(s["id"]).summary()["title"], "配信の題")

    def test_named_or_http_is_not_looked_up(self):
        calls = []
        self.rec.title_lookup = lambda url: (calls.append(url), "配信の題")[1]
        s = self.rec.start("https://127.0.0.1:%d/live.m3u8" % self.no_live, title="付けた名前")
        s2 = self.rec.start("http://127.0.0.1:%d/live.m3u8" % self.no_live)   # 手元の http(テストの配信)では聞かない
        self.assertEqual([t.name for t in threading.enumerate() if t.name.startswith("title-")], [])   # 題を聞くスレッドは始めた時点で決まる
        self.assertEqual(calls, [])
        self.assertEqual(self.rec.get(s["id"]).meta["title"], "付けた名前")
        self.assertEqual(self.rec.get(s2["id"]).meta["title"], "")

    def test_fill_title_does_not_overwrite_and_retries(self):
        s = self.rec.start("https://127.0.0.1:%d/live.m3u8" % self.no_live)   # title_lookup が None なので、ここでは聞かない
        r = self.rec.get(s["id"])
        # 聞いている間に名前が付いた → 上書きしない
        self.rec.title_lookup = lambda url: (r.set(title="手で付けた"), "配信の題")[1]
        r.set(title="")
        self.rec._fill_title(r)
        self.assertEqual(r.meta["title"], "手で付けた")
        # 既に名前がある → 聞かない
        calls = []
        self.rec.title_lookup = lambda url: (calls.append(url), "配信の題")[1]
        self.rec._fill_title(r)
        self.assertEqual((calls, r.meta["title"]), ([], "手で付けた"))
        # 取れなければ間を置いてもう一度(全部だめなら題なしのまま)
        r.set(title="")
        answers = ["", "二度目の題"]
        self.rec.title_lookup = lambda url: (calls.append(url), answers.pop(0) if answers else "")[1]
        with mock.patch.object(R, "TITLE_TRIES", (0, 0.2, 0.2)):
            self.rec._fill_title(r)
        self.assertEqual((len(calls), r.meta["title"]), (2, "二度目の題"))
        r.set(title="")
        calls.clear()
        self.rec.title_lookup = lambda url: (calls.append(url), "")[1]
        with mock.patch.object(R, "TITLE_TRIES", (0, 0.1)):
            self.rec._fill_title(r)
        self.assertEqual((len(calls), r.meta["title"]), (2, ""))
        # 録画が終わったら聞かない
        self.rec.stop(r.id)
        calls.clear()
        self.rec._fill_title(r)
        self.assertEqual(calls, [])


class TestHttp(unittest.TestCase):
    """recorder.py を別のプロセスで動かし、HTTP の API を確かめる"""

    @classmethod
    def setUpClass(cls):
        cls.src_dir, cls.segs = source(40)
        cls.tmp = tempfile.mkdtemp(prefix="ytt-rec-http-")
        cls.ddir = os.path.join(cls.tmp, "data")
        cls.folder = os.path.join(cls.tmp, "live-rec")
        cls.port = free_port()
        cls.srv = F.LiveServer(cls.src_dir, cls.segs, start=3, rate=1.0)
        cls.srv.end = False
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        cls.proc = subprocess.Popen([sys.executable, os.path.join(HERE, "recorder.py"), "--port", str(cls.port), "--data-dir", cls.ddir,
                                     "--folder", cls.folder, "--source", "direct", "--hls-time", "1", "--backoff", "1,2", "--stall-sec", "4",
                                     "--quiet"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        ok = wait_for(lambda: cls._raw("GET", "/api/ping")[0] == 200, 20)
        if not ok:
            cls.proc.kill()
            raise RuntimeError("録画の部品が起動しません")
        with open(os.path.join(cls.ddir, "token.txt"), encoding="ascii") as f:
            cls.token = f.read().strip()

    @classmethod
    def tearDownClass(cls):
        try:
            cls._raw("POST", "/live/quit", {}, token=cls.token)
            cls.proc.wait(20)
        except Exception:
            cls.proc.kill()
        cls.srv.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _raw(cls, method, path, body=None, token=None, headers=None):
        try:
            c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=30)
            h = {"Host": "127.0.0.1:%d" % cls.port}
            if token:
                h["Authorization"] = "Bearer " + token
            data = None
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                h["Content-Type"] = "application/json"
            h.update(headers or {})
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, r.getheader("Content-Type") or "", r.read()
        except OSError:
            return None, "", b""

    def call(self, method, path, body=None, **kw):
        code, ctype, raw = self._raw(method, path, body, token=kw.pop("token", self.token), **kw)
        return code, (json.loads(raw.decode("utf-8")) if ctype.startswith("application/json") else raw)

    def test_1_guards(self):
        self.assertEqual(self._raw("GET", "/api/ping")[0], 200)              # 生きているかは合言葉なしで分かる
        self.assertEqual(self._raw("GET", "/live/list")[0], 403)             # 合言葉なし
        self.assertEqual(self._raw("GET", "/live/list", token="x" * 40)[0], 403)
        self.assertEqual(self._raw("POST", "/live/start", {"url": self.srv.url})[0], 403)
        self.assertEqual(self._raw("GET", "/live/list", token=self.token, headers={"Host": "evil.example:%d" % self.port})[0], 403)   # DNS rebinding
        self.assertEqual(self._raw("GET", "/live/list", token=self.token, headers={"Origin": "http://127.0.0.1:%d" % self.port})[0], 403)   # ブラウザから直接
        self.assertEqual(self._raw("GET", "/live/list", token=self.token, headers={"Sec-Fetch-Site": "same-origin"})[0], 403)
        code, d = self.call("GET", "/live/list")
        self.assertEqual(code, 200)
        self.assertTrue(d["folderOk"])
        self.assertGreater(d["freeBytes"], 0)            # 空き容量
        self.assertEqual(os.path.normcase(d["folder"]), os.path.normcase(self.folder))
        code, d = self.call("POST", "/live/start", {"url": "https://www.youtube.com/watch?v=x"})   # direct では手元の URL だけ
        self.assertEqual(code, 400)
        code, d = self.call("POST", "/live/start", {"url": self.srv.url, "quality": "4k"})
        self.assertEqual(code, 400)
        code, d = self.call("POST", "/live/config", {"folder": "\\\\server\\share"})
        self.assertEqual(code, 400)
        code, _ = self.call("GET", "/live/99999999-999999/status")
        self.assertEqual(code, 404)

    def _post_raw(self, body, ctype="application/json", headers=None):
        """本文をそのまま送る POST(/live/config)。-> (状態, エラーのコード か None)"""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            h = {"Host": "127.0.0.1:%d" % self.port, "Authorization": "Bearer " + self.token, "Content-Type": ctype}
            h.update(headers or {})
            c.request("POST", "/live/config", body=body, headers=h)
            r = c.getresponse()
            d = json.loads(r.read().decode("utf-8"))
            return r.status, d.get("error")
        finally:
            c.close()

    def test_1b_body_errors(self):
        """書き込みの本文の読み方は ytt.httpsec.read_json_body。断る理由ごとの状態とコード(読み方の細部は ytt 側)"""
        self.assertEqual(self._post_raw(b"{}", "text/plain"), (415, "content_type"))
        self.assertEqual(self._post_raw(b"[1]"), (400, "json"))                               # オブジェクトでない
        self.assertEqual(self._post_raw(b"", headers={"Content-Length": "abc"}), (413, "size"))   # 数でない
        self.assertEqual(self._post_raw(b" " * (16 * 1024 + 1)), (413, "size"))               # 上限(recorder.BODY_MAX = 16KB)より大きい
        code, err = self._post_raw(b"")                                                       # 空の本文は {} として通り、中身の検査で断られる
        self.assertEqual(code, 400)
        self.assertNotIn(err, ("json", "size", "content_type"))
        self.assertEqual(self._post_raw(b'{"folder": 1}', "application/json; charset=utf-8")[0], 400)   # ; charset 付きも通る(中身の検査まで届く)

    def test_2_record_play_stop(self):
        code, d = self.call("POST", "/live/start", {"url": self.srv.url, "title": "http のテスト"})
        self.assertEqual(code, 200, d)
        rid = d["recording"]["id"]
        self.assertTrue(wait_for(lambda: (self.call("GET", "/live/%s/status" % rid)[1] or {}).get("segments", 0) >= 3, 30))
        code, st = self.call("GET", "/live/%s/status?since=1" % rid)
        self.assertEqual(st["since"], 1)
        self.assertEqual(len(st["segmentList"]), st["segments"] - 1)
        self.assertTrue(st["sessionList"][0]["firstPdt"])
        code, ctype, pl = self._raw("GET", "/live/%s/index.m3u8" % rid, token=self.token)
        self.assertEqual(code, 200)
        self.assertEqual(ctype, "application/vnd.apple.mpegurl")
        first = [ln for ln in pl.decode().splitlines() if ln.endswith(".ts")][0]
        code, ctype, ts = self._raw("GET", "/live/%s/%s" % (rid, first), token=self.token)
        self.assertEqual((code, ctype), (200, "video/mp2t"))
        self.assertEqual(ts[:1], b"\x47")   # TS の同期バイト
        for bad in ("/live/%s/../recording.json" % rid, "/live/%s/session_001/../../x.ts" % rid, "/live/%s/session_001/index.m3u8" % rid,
                    "/live/%s/session_001/seg_000000.ts.tmp" % rid, "/live/..%%2f/status"):
            self.assertEqual(self._raw("GET", bad, token=self.token)[0], 404, bad)
        code, d = self.call("GET", "/live/list")
        self.assertEqual(d["active"], 1)
        code, _ = self.call("POST", "/live/quit", {})   # 録画中は終わらない
        self.assertEqual(code, 409)
        code, _ = self.call("POST", "/live/config", {"folder": os.path.join(self.tmp, "other")})   # 録画中は置き場所を変えない
        self.assertEqual(code, 409)
        # 区間の取得: 応答の形と入力の検査(区間の選び方は TestRecordRun と TestPieces)
        first = R.iso_epoch(st["firstPdt"])
        q = "/live/%s/segments?start=%s&end=%s" % (rid, R.epoch_iso(first + 0.5), R.epoch_iso(first + 2.5))
        code, sg = self.call("GET", q)
        self.assertEqual(code, 200, sg)
        self.assertTrue(sg["active"])
        self.assertEqual(sg["url"], self.srv.url)
        for bad in ("start=x&end=y", "start=%s&end=%s" % (R.epoch_iso(first + 5), R.epoch_iso(first)),
                    "start=%s&end=%s" % (R.epoch_iso(first), R.epoch_iso(first + 4 * 3600)), ""):
            self.assertEqual(self.call("GET", "/live/%s/segments?%s" % (rid, bad))[0], 400, bad)
        self.assertEqual(self._raw("GET", q)[0], 403)   # 合言葉なし
        self.assertEqual(self.call("POST", "/live/%s/delete" % rid, {})[0], 409)   # 録画中は消さない(P4)
        code, d = self.call("POST", "/live/%s/stop" % rid, {})
        self.assertEqual(code, 200)
        self.assertEqual(d["recording"]["state"], "stopped")
        self.assertIn(b"#EXT-X-ENDLIST", self._raw("GET", "/live/%s/index.m3u8" % rid, token=self.token)[2])
        # 消す(P4 の「録画を自動で消す」): 合言葉なし・ブラウザから直接は 403・形の違う id は 400・消したら一覧と状態から消える
        self.assertEqual(self._raw("POST", "/live/%s/delete" % rid, {})[0], 403)
        self.assertEqual(self._raw("POST", "/live/%s/delete" % rid, {}, token=self.token, headers={"Origin": "http://127.0.0.1:%d" % self.port})[0], 403)
        self.assertEqual(self.call("POST", "/live/..%5c..%5cx/delete", {})[0], 400)
        self.assertTrue(os.path.isdir(os.path.join(self.folder, rid)))
        code, d = self.call("POST", "/live/%s/delete" % rid, {})
        self.assertEqual((code, d), (200, {"ok": True, "deleted": rid}))
        self.assertFalse(os.path.exists(os.path.join(self.folder, rid)))
        self.assertEqual(self.call("GET", "/live/%s/status" % rid)[0], 404)
        self.assertNotIn(rid, [r["id"] for r in self.call("GET", "/live/list")[1]["recordings"]])
        self.assertEqual(self.call("POST", "/live/%s/delete" % rid, {})[0], 404)

    def test_3_config(self):
        other = os.path.join(self.tmp, "other")
        code, d = self.call("POST", "/live/config", {"folder": other})
        self.assertEqual(code, 200, d)
        self.assertEqual(os.path.normcase(self.call("GET", "/live/list")[1]["folder"]), os.path.normcase(other))
        with open(os.path.join(self.ddir, "settings.json"), encoding="utf-8") as f:   # 次の起動でも同じ置き場所
            self.assertEqual(os.path.normcase(json.load(f)["folder"]), os.path.normcase(other))
        rid = "20261004-120000-kept"   # 元の置き場所に終わった録画を置いておく(test_2 の録画は消したので)
        os.makedirs(os.path.join(self.folder, rid), exist_ok=True)
        with open(os.path.join(self.folder, rid, "recording.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": R.SCHEMA, "id": rid, "url": self.srv.url, "quality": "best", "title": "", "state": "stopped", "message": "",
                       "created": "2026-10-04T03:00:00.000Z", "endedAt": "2026-10-04T03:10:00.000Z", "sessions": []}, f)
        code, d = self.call("POST", "/live/config", {"folder": self.folder})
        self.assertEqual(code, 200)
        self.assertIn(rid, [r["id"] for r in self.call("GET", "/live/list")[1]["recordings"]])   # 元の置き場所の録画がまた見える


if __name__ == "__main__":
    unittest.main()
