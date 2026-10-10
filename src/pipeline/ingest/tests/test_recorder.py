# -*- coding: utf-8 -*-
"""録画の部品(recorder/)のテスト。本物の YouTube には繋がない: ffmpeg の lavfi で作った HLS を、手元の HTTP サーバーで
配信中のように少しずつ出し(tests/hls_fixture.py)、--source direct(HLS の URL を直接 ffmpeg に渡す)で録る。

    py -3.10 -m unittest src/pipeline/ingest/tests/test_recorder.py

確かめること: 再生リストの読み書き・URL の検査・置き場所(無いドライブ・空き容量)・書きかけの片付け /
録画 → 切断 → 繋ぎ直し(新しいセッション・#EXT-X-DISCONTINUITY)→ 停止(#EXT-X-ENDLIST)/ 配信の終わり /
起動時の復旧(書きかけを消す・読めないセッション・中断 → 新しいセッションで続ける)/
HTTP: 合言葉なしは 403・Host の検査・ブラウザからの直接は 403・セグメントと再生リスト・パスの検査・置き場所の変更・終わる /
P2: 区間にかかるセグメントと欠け(pick_segments・GET /live/<id>/segments) /
名前なしの録画に題を付ける(fetch_title を手元の HTTP サーバーの endpoint で・title_lookup を偽物にして・付けた名前は上書きしない・direct では聞かない)
"""
import http.client
import json
import os
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # src/pipeline/ingest(recorder.py のある所)
SRC = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SRC)
sys.path.insert(0, TESTS)
import hls_fixture as F  # noqa: E402
from pipeline.ingest import rec_core as R  # noqa: E402

FAST = dict(source="direct", hls_time=1, backoff=(1, 2), idle_end=8, stall_sec=4, first_seg_sec=15, poll=0.3)


def wait_for(fn, timeout=30.0, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


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
    def test_parse_and_build_playlist(self):
        text = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-PLAYLIST-TYPE:EVENT\n"
                "#EXT-X-PROGRAM-DATE-TIME:2026-10-04T15:30:12.345+0900\n#EXTINF:4.000000,\nseg_000000.ts\n"
                "#EXT-X-PROGRAM-DATE-TIME:2026-10-04T15:30:16.345+0900\n#EXTINF:3.500000,\nseg_000001.ts\n"
                "#EXTINF:4.0,\n../evil.ts\n#EXT-X-ENDLIST\n")
        segs, ended = R.parse_playlist(text)
        self.assertTrue(ended)
        self.assertEqual([s["uri"] for s in segs], ["seg_000000.ts", "seg_000001.ts"])   # 決まった形の名前だけ
        self.assertEqual(segs[0]["pdt"], "2026-10-04T06:30:12.345Z")                      # UTC にそろえる
        out = R.build_playlist([("session_001", segs), ("session_002", []), ("session_003", segs[:1])], finished=False)
        self.assertIn("#EXT-X-PLAYLIST-TYPE:EVENT", out)
        self.assertEqual(out.count("#EXT-X-DISCONTINUITY"), 1)   # 空のセッションは数えない
        self.assertIn("session_003/seg_000000.ts", out)
        self.assertNotIn("#EXT-X-ENDLIST", out)
        self.assertIn("#EXT-X-TARGETDURATION:4", out)
        self.assertIn("#EXT-X-ENDLIST", R.build_playlist([("session_001", segs)], finished=True))

    def test_pick_segments(self):
        base = R.iso_epoch("2026-10-04T06:00:00Z")
        flat = [{"uri": "s1/a", "pdt": R.epoch_iso(base + i * 4), "dur": 4.0} for i in range(5)]               # 0〜20 秒
        flat += [{"uri": "s2/b", "pdt": R.epoch_iso(base + 30 + i * 4), "dur": 4.0} for i in range(3)]         # 30〜42 秒(繋ぎ直しの間 20〜30)
        segs, gaps = R.pick_segments(flat, base + 5, base + 15)
        self.assertEqual([s["pdt"] for s in segs], [R.epoch_iso(base + 4), R.epoch_iso(base + 8), R.epoch_iso(base + 12)])
        self.assertEqual(gaps, [])
        segs, gaps = R.pick_segments(flat, base + 18, base + 33)
        self.assertEqual(len(segs), 2)
        self.assertEqual(gaps, [(base + 20, base + 30)])                    # 繋ぎ直しの間
        segs, gaps = R.pick_segments(flat, base + 40, base + 50)
        self.assertEqual(gaps, [(base + 42, base + 50)])                    # まだ録れていない終わり
        segs, gaps = R.pick_segments(flat, base - 10, base + 2)
        self.assertEqual(gaps, [(base - 10, base)])                         # 録画の前
        flat2 = [dict(flat[0]), dict(flat[1], pdt=R.epoch_iso(base + 4.5))]   # 受信時刻の揺れ(1 秒より短い)は欠けにしない
        self.assertEqual(R.pick_segments(flat2, base, base + 8)[1], [])
        self.assertEqual(R.iso_epoch("2026-10-04T06:00:00.250Z"), base + 0.25)
        self.assertEqual(R.iso_epoch("2026-10-04T06:00:00+00:00"), base)
        for bad in (None, "", "2026-10-04 06:00:00", "x" * 50, 5):
            self.assertIsNone(R.iso_epoch(bad))

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

    def test_clean_tmp(self):
        tmp = tempfile.mkdtemp(prefix="ytt-rec-tmp-")
        try:
            for n in ("seg_000001.ts.tmp", "index.m3u8.tmp", "seg_000000.ts"):
                open(os.path.join(tmp, n), "wb").close()
            self.assertEqual(R.clean_tmp(tmp), 2)
            self.assertEqual(os.listdir(tmp), ["seg_000000.ts"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestRecording(unittest.TestCase):
    """Recorder を同じプロセスで動かす(direct で手元の HLS を録る)"""

    def setUp(self):
        self.src_dir, self.segs = source(40)
        self.tmp = tempfile.mkdtemp(prefix="ytt-rec-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.logs = []
        self.srv = F.LiveServer(self.src_dir, self.segs, start=3, rate=1.0)
        self.rec = R.Recorder(self.folder, log=self.logs.append, **FAST)

    def tearDown(self):
        self.rec.close()
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_reconnect_stop(self):
        s = self.rec.start(self.srv.url, "best", "テスト<b>")
        rid = s["id"]
        r = self.rec.get(rid)
        self.assertTrue(wait_for(lambda: r.summary()["segments"] >= 4), self.logs)
        self.assertEqual(r.summary()["state"], "recording")
        self.assertTrue(r.summary()["firstPdt"].endswith("Z"))
        with self.assertRaises(R.RecError):   # 同じ配信の二重録画は断る
            self.rec.start(self.srv.url)
        n1 = r.summary()["segments"]
        self.srv.down = True                  # 切断
        self.assertTrue(wait_for(lambda: r.summary()["state"] == "reconnecting", 20), (r.summary(), self.logs))
        self.srv.down = False                 # 戻る → 新しいセッション
        self.srv.end = False                  # まだ配信中(終わりの印を出さない)
        self.assertTrue(wait_for(lambda: r.summary()["sessions"] >= 2 and r.summary()["segments"] > n1 + 2, 40), (r.summary(), self.logs))
        pl = r.playlist()
        self.assertIn("#EXT-X-DISCONTINUITY", pl)
        self.assertIn("session_002/seg_", pl)
        self.assertNotIn("#EXT-X-ENDLIST", pl)
        st = self.rec.stop(rid)
        self.assertEqual(st["state"], "stopped")
        self.assertIn("#EXT-X-ENDLIST", r.playlist())
        for n in r.session_names():   # 止めたあとに書きかけが残らない
            self.assertFalse([x for x in os.listdir(os.path.join(r.dir, n)) if x.endswith(".tmp")])
        with open(os.path.join(r.dir, "recording.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["state"], "stopped")
        self.assertEqual(meta["title"], "テスト<b>")

    def test_stream_end(self):
        self.srv.rate = 4.0   # 早く出し終える → 終わりの印 → 「終了」
        s = self.rec.start(self.srv.url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.summary()["state"] == "ended", 40), (r.summary(), self.logs))
        self.assertGreater(r.summary()["segments"], 5)
        self.assertIn("#EXT-X-ENDLIST", r.playlist())

    def test_waiting_then_gives_up(self):
        self.srv.down = True   # 配信の前(まだ取れない)
        self.rec.wait_start = 3
        s = self.rec.start(self.srv.url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.summary()["state"] in ("waiting",), 5))
        self.assertTrue(wait_for(lambda: r.summary()["state"] == "ended", 30), (r.summary(), self.logs))
        self.assertEqual(r.session_names(), [])   # 取れなかったセッションは残さない

    def test_folder_missing_is_refused(self):
        d = missing_drive()
        if not d:
            self.skipTest("使っていないドライブ名がありません")
        rec = R.Recorder(d + ":\\Video\\live-rec", **FAST)
        with self.assertRaises(R.RecError) as cm:
            rec.start(self.srv.url)
        self.assertEqual(cm.exception.code, 409)
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
        """手で書き換えた recording.json の sessions(null・リストでない・中に dict でない物)でも復旧で落ちない(0.3.2):
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

    def test_delete(self):
        """P4 の「録画を自動で消す」: 録画中は 409・形の違う id は 400・置き場所の直下で recording.json があるものだけ・
        リンク(ジャンクション)の先は消さない・使用中のファイルが残ったら 409 で recording.json を残し、あとでまた消せる"""
        s = self.rec.start(self.srv.url)
        rid = s["id"]
        r = self.rec.get(rid)
        self.assertTrue(wait_for(lambda: r.summary()["segments"] >= 2, 30), self.logs)
        with self.assertRaises(R.RecError) as cm:
            self.rec.delete(rid)
        self.assertEqual(cm.exception.code, 409)   # 録画中
        for bad in (None, 3, "", "x", "../" + rid, rid + "/..", "20261004-000000/../../x", "..\\" + rid, rid + "\\session_001"):
            with self.assertRaises(R.RecError, msg=repr(bad)) as cm:
                self.rec.delete(bad)
            self.assertEqual(cm.exception.code, 400, bad)
        self.rec.stop(rid)
        # 使用中(再生中の画面がセグメントを読んでいる など)→ 409。recording.json は残り、一覧にも残る
        seg = os.path.join(r.dir, "session_001", "seg_000000.ts")
        held = open(seg, "rb")
        try:
            with self.assertRaises(R.RecError) as cm:
                self.rec.delete(rid)
            self.assertEqual(cm.exception.code, 409)
            self.assertIn("使用中", str(cm.exception))
            self.assertTrue(os.path.isfile(os.path.join(r.dir, "recording.json")))
            self.assertIs(self.rec.get(rid), r)
        finally:
            held.close()
        self.assertEqual(self.rec.delete(rid), rid)   # 閉じたら消せる
        self.assertFalse(os.path.exists(os.path.join(self.folder, rid)))
        with self.assertRaises(R.RecError) as cm:
            self.rec.get(rid)
        self.assertEqual(cm.exception.code, 404)
        with self.assertRaises(R.RecError) as cm:
            self.rec.delete(rid)
        self.assertEqual(cm.exception.code, 404)
        # recording.json の無いフォルダ(録画ではない)は消さない
        plain = os.path.join(self.folder, "20261004-000000-plain")
        os.makedirs(plain)
        open(os.path.join(plain, "keep.txt"), "wb").close()
        with self.assertRaises(R.RecError) as cm:
            self.rec.delete("20261004-000000-plain")
        self.assertEqual(cm.exception.code, 404)
        self.assertTrue(os.path.isfile(os.path.join(plain, "keep.txt")))
        # 置き場所の中のジャンクションの先(置き場所の外)は消さない
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "recording.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        link = os.path.join(self.folder, "20261004-000000-link")
        made = subprocess.run(["cmd", "/c", "mklink", "/J", link, outside], capture_output=True).returncode == 0 if os.name == "nt" else False
        if not made:
            try:
                os.symlink(outside, link, target_is_directory=True)
                made = True
            except (OSError, NotImplementedError):
                pass
        if made:
            with self.assertRaises(R.RecError):
                self.rec.delete("20261004-000000-link")
            self.assertTrue(os.path.isfile(os.path.join(outside, "recording.json")))
            os.rmdir(link) if os.name == "nt" else os.unlink(link)
        # 録画のフォルダの中のジャンクションは、それ自体だけ外して先(置き場所の外)は消さない
        rid2 = "20261004-000000-inner"
        d2 = os.path.join(self.folder, rid2)
        os.makedirs(os.path.join(d2, "session_001"))
        inner = os.path.join(outside, "inner")
        os.makedirs(inner)
        open(os.path.join(inner, "keep.ts"), "wb").close()
        with open(os.path.join(d2, "recording.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        j2 = os.path.join(d2, "session_002")
        if os.name == "nt" and subprocess.run(["cmd", "/c", "mklink", "/J", j2, inner], capture_output=True).returncode == 0:
            self.assertEqual(self.rec.delete(rid2), rid2)   # 中のジャンクションはそれ自体だけ外す
            self.assertTrue(os.path.isfile(os.path.join(inner, "keep.ts")))
            self.assertFalse(os.path.exists(d2))

    def test_halt_keeps_state_for_next_start(self):
        s = self.rec.start(self.srv.url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.summary()["segments"] >= 2, 30))
        self.rec.close()   # 録画の部品の終了(入口の「すべて終了」では呼ばれない。部品そのものを止めたとき)
        self.assertIn(r.meta["state"], R.ACTIVE)
        rec2 = R.Recorder(self.folder, **FAST)
        try:
            self.assertEqual(rec2.load(), [s["id"]])
        finally:
            rec2.close()


class TestStreamlinkPipe(unittest.TestCase):
    """本番の形(streamlink の出力 → ffmpeg の標準入力)。streamlink の hls:// で手元の HLS を読む(YouTube の URL の検査だけ外す)"""

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec("streamlink") is None:
            self.skipTest("streamlink が入っていません(py -3.10 -m pip install -r setup/requirements.txt)")
        self.src_dir, self.segs = source(40)
        self.tmp = tempfile.mkdtemp(prefix="ytt-rec-sl-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.logs = []
        self.srv = F.LiveServer(self.src_dir, self.segs, start=3, rate=1.0)
        self.rec = R.Recorder(self.folder, log=self.logs.append, **dict(FAST, source="streamlink", stall_sec=8, first_seg_sec=25))
        self._orig = R.validate_url
        R.validate_url = lambda url, allow_local=False: url

    def tearDown(self):
        R.validate_url = self._orig
        self.rec.close()
        self.srv.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

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

    def test_default_quality_is_1080p(self):
        """画質の既定は 1080p(2026-10-04 ユーザー決定。4K の配信で容量が膨らむのを避ける)。720p・best は今までどおり選べる"""
        import inspect
        self.assertEqual(R.DEFAULT_QUALITY, "1080p")
        self.assertEqual(inspect.signature(R.Recorder.start).parameters["quality"].default, "1080p")
        r = R.Recording(self.rec, "20261004-000000-y", os.path.join(self.folder, "y"), {"url": "https://www.youtube.com/watch?v=y", "quality": R.DEFAULT_QUALITY})
        self.assertEqual(r._commands("session_001")[0][-1], "1080p60,1080p,best")
        for q in ("best", "720p"):
            self.assertIn(q, R.QUALITIES)

    def test_disconnect_is_not_the_end(self):
        """streamlink は切断でも終了コード 0 で終わる。記録の「No new segments」で見分けて、終わりにせず繋ぎ直す"""
        self.srv.end = False
        s = self.rec.start("hls://" + self.srv.url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.summary()["segments"] >= 3, 40), (r.summary(), self.logs))
        self.srv.down = True
        self.assertTrue(wait_for(lambda: r.summary()["state"] == "reconnecting", 40), (r.summary(), self.logs))
        n1 = r.summary()["segments"]
        self.srv.down = False
        self.assertTrue(wait_for(lambda: r.summary()["sessions"] >= 2 and r.summary()["segments"] > n1, 60), (r.summary(), self.logs))
        self.assertEqual(self.rec.stop(s["id"])["state"], "stopped")

    def test_clean_end(self):
        self.srv.rate = 4.0
        s = self.rec.start("hls://" + self.srv.url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.summary()["state"] == "ended", 60), (r.summary(), self.logs))
        self.assertEqual(r.summary()["sessions"], 1)


class TestArchiveGuard(unittest.TestCase):
    def test_too_fast_means_archive(self):
        """配信ではなくアーカイブを頭から取り始めた(実際の時間より何倍も速く取れる)ら、そのセッションを消して「終了」"""
        src_dir, segs = source(120)
        tmp = tempfile.mkdtemp(prefix="ytt-rec-arc-")
        srv = F.LiveServer(src_dir, segs, start=len(segs), rate=1.0)   # 全部見えて終わりの印あり = アーカイブ
        rec = R.Recorder(os.path.join(tmp, "live-rec"), **FAST)
        os.makedirs(rec.folder)
        try:
            s = rec.start(srv.url)
            r = rec.get(s["id"])
            self.assertTrue(wait_for(lambda: r.summary()["state"] == "ended", 60), r.summary())
            self.assertIn("アーカイブ", r.summary()["message"])
            self.assertEqual(r.session_names(), [])
        finally:
            rec.close()
            srv.close()
            shutil.rmtree(tmp, ignore_errors=True)


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
                    time.sleep(3)
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
        import threading
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-rec-title-")
        self.folder = os.path.join(self.tmp, "live-rec")
        os.makedirs(self.folder)
        self.rec = R.Recorder(self.folder, **FAST)

    def tearDown(self):
        for r in list(self.rec.recs.values()):
            if r.active:
                self.rec.stop(r.id)
        self.rec.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

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
        self.assertLess(time.time() - t, 2.5)
        self.assertEqual(R.fetch_title(url, endpoint="http://127.0.0.1:%d/x" % free_port()), "")   # つながらない

    def test_lookup_only_for_streamlink(self):
        self.assertIsNone(self.rec.title_lookup)                                       # direct(テスト)では聞かない
        self.assertIs(R.Recorder(self.folder, source="streamlink").title_lookup, R.fetch_title)

    def test_untitled_recording_gets_title(self):
        calls = []
        self.rec.title_lookup = lambda url: (calls.append(url), "配信の題")[1]
        url = "https://127.0.0.1:%d/live.m3u8" % free_port()   # https の手元の URL(つながらないので録画は「待ち」のまま)
        s = self.rec.start(url)
        r = self.rec.get(s["id"])
        self.assertTrue(wait_for(lambda: r.meta.get("title") == "配信の題", 10), (r.meta, calls))
        self.assertEqual(calls, [url])
        with open(os.path.join(r.dir, "recording.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["title"], "配信の題")   # 記録にも残る
        self.assertEqual(self.rec.get(s["id"]).summary()["title"], "配信の題")

    def test_named_or_http_is_not_looked_up(self):
        calls = []
        self.rec.title_lookup = lambda url: (calls.append(url), "配信の題")[1]
        s = self.rec.start("https://127.0.0.1:%d/live.m3u8" % free_port(), title="付けた名前")
        s2 = self.rec.start("http://127.0.0.1:%d/live.m3u8" % free_port())   # 手元の http(テストの配信)では聞かない
        time.sleep(1.0)
        self.assertEqual(calls, [])
        self.assertEqual(self.rec.get(s["id"]).meta["title"], "付けた名前")
        self.assertEqual(self.rec.get(s2["id"]).meta["title"], "")

    def test_fill_title_does_not_overwrite_and_retries(self):
        s = self.rec.start("https://127.0.0.1:%d/live.m3u8" % free_port())   # title_lookup が None なので、ここでは聞かない
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
        """書き込みの本文の読み方は ytt.httpsec.read_json_body(0.3.3)。断る理由ごとの状態とコードは今までどおり"""
        self.assertEqual(self._post_raw(b"{}", "text/plain"), (415, "content_type"))
        self.assertEqual(self._post_raw(b"[1]"), (400, "json"))                               # オブジェクトでない
        self.assertEqual(self._post_raw(b"{x"), (400, "json"))
        self.assertEqual(self._post_raw(b"\xff\xfe"), (400, "json"))                         # UTF-8 でない
        self.assertEqual(self._post_raw(b"", headers={"Content-Length": "abc"}), (413, "size"))   # 数でない
        self.assertEqual(self._post_raw(b"", headers={"Content-Length": "-1"}), (413, "size"))
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
        # 区間の取得(P2): 区間にかかるセグメント・欠け・録画済みの最後の時刻
        first, last = R.iso_epoch(st["firstPdt"]), R.iso_epoch(st["lastPdt"])
        q = "/live/%s/segments?start=%s&end=%s" % (rid, R.epoch_iso(first + 0.5), R.epoch_iso(first + 2.5))
        code, sg = self.call("GET", q)
        self.assertEqual(code, 200, sg)
        self.assertTrue(sg["active"])
        self.assertEqual(sg["url"], self.srv.url)
        self.assertGreaterEqual(len(sg["segments"]), 2)
        self.assertEqual(sg["gaps"], [])
        self.assertTrue(all(x["uri"].startswith("session_001/seg_") and x["session"] == "session_001" for x in sg["segments"]))
        self.assertLessEqual(R.iso_epoch(sg["segments"][0]["pdt"]), first + 0.5)
        code, sg = self.call("GET", "/live/%s/segments?start=%s&end=%s" % (rid, R.epoch_iso(last + 100), R.epoch_iso(last + 110)))
        self.assertEqual((code, sg["segments"], len(sg["gaps"])), (200, [], 1))   # まだ録れていない
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
