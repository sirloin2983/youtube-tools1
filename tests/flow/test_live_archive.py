# -*- coding: utf-8 -*-
"""録画に無い区間をアーカイブから書き出す・配信後の全自動(線 D。src/flow/live_archive.py・src/pipeline/ingest/live_align_worker.py)のテスト。
入口を通す API の分は tests/app/test_live_archive_api.py。本物の YouTube には繋がない。

    py -3.12 -m unittest tests/flow/test_live_archive.py

作るもの(ffmpeg の lavfi): 「アーカイブ」= 映像 testsrc2 の 60fps + 時間で変わる音(周波数が動く sine + ノイズ)。
「録画」の音 = その途中を別の符号化(AAC の作り直し・音量 60%)で切り出したもの(録画元への問い合わせと取得を偽物にする)。
偽の yt-dlp(丸ごとの音 = アーカイブの音)・偽のスタジオの section(アーカイブから ffmpeg で 30fps に切る)で動かす。

確かめること:
  - 通し(ArchiveTest.test_archive_run): 用意がまだ(post_live)→ 409 で待つ → 録画に無い区間(error + needsArchive)と M7 の採用(wait + from archive)だけを
    アーカイブから書き出す: 照合で求めたアーカイブの秒が正解 ±0.03 秒・clip.json の archive・job.state done・2 本目は前のずれの ±20 秒の窓・
    作りかけのフォルダが残らない。録画から書き出せたジョブは触らない / 同じ配信の別の録画は前の録画のずれの窓で 1 回 / 録画の音が合わない → 書き出さない /
    録画を消した後は同じ録画の照合できたマークのずれ
  - 録画の音が取れないときの残りのずれ: M7 のずれ → 失敗(M7 の採用は error + needsArchive に)・開始時刻が無い
  - 取り消し(スタジオの書き出しも取り消す)・前の版の入れ替え待ちのジョブは何もせず取り消し
  - 自動の見回り(時間を縮めて): 録画が終わって少したってから・用意ができたら・重い処理があれば待つ・7 日(縮めた)でやめる
  - 起動し直しで続く(途中の段 → 待ち)・スタジオが 409 busy なら待ってやり直す
  - worker 単体(ずれの正しさ・無音)
  - 配信後の全自動(M7)と友人のライブ配信の依頼(2-15): 依頼の afterStream が真ならホームの M7 がオフでも進める(本数は依頼の perHour)・
    偽ならホームの M7 がオンでも動かさない・録画を消すのを待つか(after_stream_hold)も同じ決め方。採用の範囲は配信の終わりまで
  - アーカイブ化したか(archived。録画を消す合図)
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import _livefix as LF  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import board as Board  # noqa: E402
from flow import live_archive as A  # noqa: E402
from flow import live_export as LX  # noqa: E402
from ytt import fsio, jobs, marks as _marks, schemas, tools  # noqa: E402

FF = tools.find_tool("ffmpeg", "YTT_FFMPEG")
RELEASE = 1790000000.0            # 配信の開始時刻(偽の yt-dlp の release_timestamp)
SKEW = 5.0                        # 録画の受信時刻 − アーカイブの秒 − 開始時刻(見当はこれだけずれる = 照合で求める offset)
ARC_SEC = 360
AUDIO = "0.4*sin(2*PI*t*(400+300*sin(2*PI*0.07*t)))*(0.6+0.4*sin(2*PI*1.3*t))+0.15*(2*random(0)-1)"
OTHER = "0.4*sin(2*PI*t*(520+180*sin(2*PI*0.11*t)))*(0.7+0.3*sin(2*PI*0.9*t))+0.15*(2*random(1)-1)"
REC = "20261005-120000-abcdefghijk"
VID = "abcdefghijk"


ff = LF.ff
wait_for = LF.wait_for
FakeStudio = LF.ArchiveStudio


class FakeExLive:
    """Exporter が使う Live の代わり(このテストは書き出しを動かさない)"""
    def find(self, rid):
        return {"id": rid, "name": rid}


class WavArgsTest(unittest.TestCase):
    def test_wav_args_of_archiver(self):
        """Archiver._wav が recognize.wav_args に渡す物(8kHz・精密な切り方・取り消しの印)。引数の組み方は test_recognize.py"""
        tmp = testkit.tempdir(self, "ytt-arc-wav-")
        cmds = []

        def run(cmd, timeout, cancelled=None):
            cmds.append((list(cmd), timeout, cancelled is not None))
            with open(cmd[-1], "wb") as f:
                f.write(b"x")
            return 0, "", []
        me = mock.Mock(ffmpeg="FF", _cancel=set())
        me._halt.is_set.return_value = False
        dst = os.path.join(tmp, "a.wav")
        with mock.patch.object(A, "run_proc", side_effect=run):
            A.Archiver._wav(me, "src.m4a", dst, 25.5, 4.25, {"id": "j"})
            A.Archiver._wav(me, "src.m4a", dst)
        head = ["FF", "-hide_banner", "-nostdin", "-y", "-v", "error"]
        tail = ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", "-f", "wav", dst]
        self.assertEqual([c for c, _, _ in cmds], [head + ["-ss", "15.500", "-i", "src.m4a", "-ss", "10.000", "-t", "4.250"] + tail, head + ["-i", "src.m4a"] + tail])
        self.assertEqual([(t, c) for _, t, c in cmds], [(A.FFMPEG_TIMEOUT, True), (A.FFMPEG_TIMEOUT, False)])   # 引数の組み方の全部の場合は tests/pipeline/transcribe/test_recognize.py


@unittest.skipUnless(FF, "ffmpeg が無い")
class ArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fix = tempfile.mkdtemp(prefix="ytt-live-arc-fix-")
        cls.arc = os.path.join(cls.fix, "archive.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=60:d=%d" % ARC_SEC, "-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=%d" % (AUDIO, ARC_SEC),
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", cls.arc)
        cls.other = os.path.join(cls.fix, "other.m4a")   # 別の音(照合できないはず)
        ff("-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=%d" % (OTHER, ARC_SEC), "-c:a", "aac", cls.other)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fix, ignore_errors=True)

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-arc-")
        p = mock.patch.object(_marks, "CLIP_MARGIN_FIXED", False)   # 頼む区間の長さは余白なしで組んである = スイッチを切る(固定 10 秒は test_live_export・test_exporter)
        p.start()
        self.addCleanup(p.stop)
        self.out = os.path.join(self.tmp, "out")
        self.store = os.path.join(self.tmp, "live")
        os.makedirs(self.out)
        self.status = "was_live"
        self.release = RELEASE
        self.probes, self.fetches, self.aligns, self.queries = [], [], [], []
        self.rec_gone = set()     # 録画元にもう無い録画(404)
        self.rec_src = {}         # 録画 -> 録画の音の元(無ければアーカイブと同じ音)
        self.ex = self.exporter()
        self.ex.marks.upsert("local", REC, "lm-000000000001", 1, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1),
                             url="https://www.youtube.com/watch?v=" + VID, title="配信の題")
        self.arcs = []

    def tearDown(self):
        for a in self.arcs:
            a.close()   # 一時フォルダは testkit.tempdir が後で消す

    # --- 偽物 ---
    def exporter(self):
        """本物の Exporter。録画元への問い合わせ(_query)と取得(_fetch)だけ偽物にする: 録画は アーカイブの 0 秒 = 受信時刻 RELEASE + SKEW から ARC_SEC 秒。
        取った「録画」の音はアーカイブ(か rec_src の音)の同じ所を AAC で作り直して音量 60% にしたもの"""
        ex = LX.Exporter(FakeExLive(), self.store, lambda: self.out)

        def query(rc, rec, a, b):
            self.queries.append((rec, a, b))
            if rec in self.rec_gone:
                return 404, None
            a, b = max(a, RELEASE + SKEW), min(b, RELEASE + SKEW + ARC_SEC)
            if b - a < 1.0:
                return 200, {"segments": [], "active": False}
            return 200, {"segments": [{"uri": "session_001/seg_000001.ts", "session": 1, "pdt": LX.epoch_iso(a), "dur": round(b - a, 3)}], "active": False}

        def fetch(job, rc, rec, segs, wdir):
            os.makedirs(wdir, exist_ok=True)
            p = os.path.join(wdir, "part_00.m4a")
            a = LX.iso_epoch(segs[0]["pdt"])
            ff("-ss", "%.3f" % (a - RELEASE - SKEW), "-i", self.rec_src.get(rec, self.arc), "-t", "%.3f" % segs[0]["dur"], "-vn", "-af", "volume=0.6",
               "-c:a", "aac", "-b:a", "96k", p)
            return [(p, 1)]
        ex._query, ex._fetch = query, fetch
        return ex

    def probe(self, vid):
        self.probes.append(vid)
        return {"status": self.status, "release": self.release, "timestamp": RELEASE + 7200, "duration": ARC_SEC, "availability": "public"}   # timestamp(配信の終わりごろ)は使わない

    def audio(self, vid, folder, cancelled=None):
        """偽の yt-dlp: 配信の丸ごとの音(m4a)"""
        self.fetches.append(vid)
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, "full.m4a")
        full = os.path.join(self.fix, "full.m4a")   # 作るのは 1 回だけ(360 秒の音の作り直しは 1 回 2 秒ほど)。あとは同じ中身を写す
        if not os.path.isfile(full):
            ff("-i", self.arc, "-vn", "-c:a", "aac", "-b:a", "128k", full)
        shutil.copyfile(full, p)
        return p

    def align(self, ref, win):
        self.aligns.append(win)
        return A.run_align(ref, win)

    def archiver(self, studio=None, **kw):
        studio = studio or FakeStudio(self.arc)
        opts = dict(studio=studio, probe=self.probe, audio=self.audio, align=self.align, poll=0.1, step=0.1, retry_sec=0.3, **studio.opts())
        opts.update(kw)
        a = A.Archiver(self.ex, **opts)
        self.arcs.append(a)
        return a

    # --- ジョブ ---
    def job(self, true_start, dur, n, state, label="", rec=REC, **kw):
        """書き出しのジョブ。true_start = アーカイブの秒(受信時刻 = RELEASE + true_start + SKEW)。state error = 録画に無い区間(needsArchive)"""
        a = RELEASE + true_start + SKEW
        j = {"id": "lx-%010x" % (n * 7919), "recorder": "local", "recording": rec, "markId": "lm-%012x" % n, "n": n, "label": label,
             "start": LX.epoch_iso(a), "end": LX.epoch_iso(a + dur), "transcribe": False, "state": state, "message": "", "error": "",
             "needsArchive": state == "error", "progress": 1.0 if state == "done" else 0, "source": "local", "path": "", "manifest": "",
             "runId": "", "warning": "", "attempts": 1, "created": LX.now_iso(), "updated": LX.now_iso(),
             "recBase": LX.epoch_iso(RELEASE + SKEW + 100.0),
             "studio": {"video": rec, "mark": "m%d" % n, "start": true_start - 100.0, "end": true_start - 100.0 + dur}}
        j.update(kw)
        self.ex.jobs.append(j)
        self.ex._save()
        return j

    def arc_of(self, job):
        return dict(job.get("archive") or {})

    def wait_state(self, job, states=("done", "error", "cancelled"), timeout=120):
        return wait_for(lambda: self.arc_of(job).get("state") in states, timeout)

    # --- テスト ---
    def test_archive_run(self):
        """アーカイブから書き出す通し(本物の ffmpeg・本物の照合 run_align・本物の Exporter の記録)。配信 1 本(VID)の録画 3 本"""
        done = self.job(100.0, 5.0, 9, "done", path=os.path.join(self.out, "速報版.mp4"))   # 録画から書き出せた: 対象でない
        j1 = self.job(150.047, 12.0, 1, "error", label="欠け")
        j2 = self.job(220.031, 8.0, 2, "wait", **{"from": "archive", "origin": "archive"})
        plain_wait = self.job(240.0, 5.0, 4, "wait")                       # 録画から書き出す待ち: 対象でない
        plain_err = self.job(250.0, 5.0, 5, "error", needsArchive=False)   # 録画にある区間の失敗: 対象でない
        studio = FakeStudio(self.arc)
        afters = []
        ar = self.archiver(studio, after=lambda rc, rec: afters.append((rc, rec)))
        self.assertEqual([j["id"] for j in ar.targets("local", REC)], [j1["id"], j2["id"]])
        self.assertEqual(ar.info_view("local", REC), {"ready": None, "checkedAt": None, "message": ""})
        self.status = "post_live"   # アーカイブの用意がまだ: 409 で待つ(何も入れない)
        with self.assertRaises(LX.LiveError) as cm:
            ar.request("local", REC)
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("処理中", str(cm.exception))
        self.assertIs(ar.info_view("local", REC)["ready"], False)
        self.assertNotIn("archive", j1)
        self.status = "was_live"
        r = ar.request("local", REC)
        self.assertEqual((r["ok"], r["queued"]), (True, 2), r)
        self.assertIn("アーカイブから書き出します", r["message"])
        for j in (j1, j2):
            self.assertTrue(self.wait_state(j), self.arc_of(j))
        for j, true, dur in ((j1, 150.047, 12.0), (j2, 220.031, 8.0)):
            a = self.arc_of(j)
            self.assertEqual((a["state"], j["state"], j["needsArchive"]), ("done", "done", False), a)
            self.assertAlmostEqual(a["archiveStart"], true, delta=0.03, msg=a)   # 照合で求めたアーカイブの秒
            self.assertAlmostEqual(a["offset"], -SKEW, delta=0.03)
            self.assertTrue(a["aligned"])
            self.assertIn("マークの手前の録画の音", a["offsetFrom"])
            self.assertTrue(j["path"].startswith(os.path.join(self.out, "配信の題")), j["path"])
            c = fsio.read_json_file(j["manifest"], 1 << 20)
            self.assertEqual((c["source"]["kind"], c["source"]["live"]["archive"]["videoId"], c["export"]["from"]), ("live", VID, "youtube-archive"))
        self.assertAlmostEqual(fsio.read_json_file(j1["manifest"], 1 << 20)["range"]["start"], 150.047 - 100.0, delta=0.01)   # recBase からの秒
        for j in (done, plain_wait, plain_err):
            self.assertNotIn("archive", j)
        self.assertEqual(done["state"], "done")
        self.assertEqual([c["videoId"] for c in studio.calls], [VID, VID])
        self.assertEqual(studio.calls[0]["maxHeight"], 0)
        for c, dur in zip(studio.calls, (12.0, 8.0)):   # 頼んだ区間の長さ(30fps の書き出しは書き出しの器の持ち物)
            self.assertAlmostEqual(c["end"] - c["start"], dur, delta=LX.LEN_TOL)
        self.assertEqual(self.fetches, [VID])   # 配信の音は 1 回だけ丸ごと取って使い回す
        self.assertEqual(len(self.aligns), 2)   # 照合は 1 本 1 回(2 本目は前のずれの ±20 秒で 1 回で合う)
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.out, "配信の題", schemas.WORK_DIR, A.BUILD_DIR)), 10))
        self.assertTrue(wait_for(lambda: not (os.path.isdir(self.ex.work) and os.listdir(self.ex.work)), 10))   # 一時ファイル(live/work)も残らない
        with self.assertRaises(LX.LiveError) as cm:
            ar.request("local", REC)
        self.assertEqual(cm.exception.code, 409)
        self.assertTrue(ar.info_view("local", REC)["ready"])
        self.assertEqual(afters, [("local", REC)])   # 録画の最後の1本が済んだときに1回(録画を消す Cleaner.check へ)

        # 同じ配信の別の録画: 前の録画で照合したずれを窓の見当に(最初から ±20 秒・1 回で合う)
        rec2, rec3 = "20261005-130000-abcdefghijk", "20261005-140000-abcdefghijk"
        for n, rec in ((6, rec2), (7, rec3)):
            self.ex.marks.upsert("local", rec, "lm-%012x" % n, n, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1), url="https://www.youtube.com/watch?v=" + VID,
                                 title="配信の題")
        k2 = self.job(300.019, 6.0, 6, "error", rec=rec2)
        ar.request("local", rec2)
        self.assertTrue(self.wait_state(k2))
        a = self.arc_of(k2)
        self.assertEqual(a["state"], "done", a)
        self.assertAlmostEqual(a["archiveStart"], 300.019, delta=0.03)
        self.assertEqual(len(self.aligns), 3)
        # 録画の音がアーカイブと合わない(切り貼り・別の配信)→ 書き出さない
        self.rec_src[rec3] = self.other
        k3 = self.job(150.0, 6.0, 7, "error", rec=rec3)
        n = len(studio.calls)
        ar.request("local", rec3)
        self.assertTrue(self.wait_state(k3))
        self.assertEqual(self.arc_of(k3)["state"], "error")
        self.assertIn("合わせられませんでした", self.arc_of(k3)["message"])
        self.assertEqual(len(studio.calls), n)
        # 録画を消した後(録画の音が取れない): 同じ録画の照合できたマークのずれ
        self.rec_gone.add(REC)
        j3 = self.job(260.0, 6.0, 3, "error")
        ar.request("local", REC)
        self.assertTrue(self.wait_state(j3))
        a = self.arc_of(j3)
        self.assertEqual(a["state"], "done", a)
        self.assertIn("照合できたマーク", a["offsetFrom"])
        self.assertAlmostEqual(a["archiveStart"], 260.0, delta=0.03)
        self.assertNotIn("aligned", a)

    def test_offset_fallbacks(self):
        """録画の音が取れず、同じ録画の照合できたマークも無いとき: M7 のずれ → どれも無ければ失敗(M7 の採用は error + needsArchive)。
        通しでは M7 の途中の記録(afterStream の offset)と、ずれの手がかりが何も無い録画を作れない"""
        ar2 = self.archiver()
        ar2._info_put("local", REC, afterStream={"state": "export", "offset": -SKEW})
        self.rec_gone.add(REC)
        j2 = self.job(220.031, 6.0, 2, "wait", **{"from": "archive"})
        ar2.request("local", REC)
        self.assertTrue(self.wait_state(j2))
        self.assertEqual(self.arc_of(j2)["state"], "done", self.arc_of(j2))
        self.assertIn("配信後の自動の切り抜き", self.arc_of(j2)["offsetFrom"])
        ar2.close()
        ar3 = self.archiver()
        j3 = self.job(260.0, 6.0, 3, "wait", rec="20261005-140000-abcdefghijk", **{"from": "archive"})
        self.rec_gone.add(j3["recording"])
        self.ex.marks.upsert("local", j3["recording"], "lm-000000000003", 3, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1),
                             url="https://www.youtube.com/watch?v=" + VID)
        ar3.request("local", j3["recording"])
        self.assertTrue(self.wait_state(j3))
        self.assertEqual(self.arc_of(j3)["state"], "error")
        self.assertIn("時刻を合わせられませんでした", self.arc_of(j3)["message"])
        self.assertEqual((j3["state"], j3["needsArchive"]), ("error", True))   # 待ちのまま残さない(人が押せばやり直せる)
        self.assertEqual(ar3.targets("local", j3["recording"]), [j3])

    def test_no_start_time(self):
        """付加情報に配信の開始時刻が無い(めったに来ない)→ 照合しない"""
        j1 = self.job(150.047, 6.0, 1, "error")
        ar = self.archiver()
        self.release = None
        ar.request("local", REC)
        self.assertTrue(self.wait_state(j1))
        self.assertEqual(self.arc_of(j1)["message"], "開始時刻が分からないので照合できません")

    def test_helpers(self):
        self.assertFalse(A.inside(os.path.join(self.out, "..", "x.mp4"), self.out))
        self.assertFalse(A.needs_archive({"state": "done", "from": "archive"}))   # 書き出し済みの M7 の採用(通しは済む前に見る)

    def test_board_follows_archive(self):
        """掲示板: 書き出しの状態が変わったら la:<ジョブの id> がその state で載る・配信後の全自動は la:as-<録画元>.<録画>"""
        j1 = self.job(150.0, 6.0, 1, "error", "山場")
        ar = self.archiver()
        ar.start = lambda: None   # 裏の糸は動かさない(状態は _aset で進める)
        b = Board.Board()
        ar.attach_board(b)
        jid = "la:" + j1["id"]
        self.assertIsNone(b.get(jid))   # 頼むまでは載らない
        ar._queue([j1], auto=False)
        got = b.get(jid)
        self.assertEqual((got["kind"], got["state"], got["canCancel"]), ("live_archive", "queued", True))
        self.assertIn("山場", got["title"])
        ar._aset(j1, state="align", progress=0.3)
        self.assertEqual((b.get(jid)["state"], b.get(jid)["progress"]), ("running", 0.3))
        self.assertFalse(b.cancel(jid)["canCancel"])   # 途中: 今の段を止める印(state は止まるまで running)
        self.assertIn(j1["id"], ar._cancel)
        ar._aset(j1, state="cancelled", progress=0)
        self.assertEqual(b.get(jid)["state"], "cancelled")
        ar._after_set("local", REC, state="none", message="採用する候補がありませんでした")
        got = b.get("la:as-local." + REC)
        self.assertEqual((got["state"], got["canCancel"], got["target"]), ("skipped", False, {"recording": REC}))
        with self.assertRaises(Board.Refused):
            b.cancel("la:as-local." + REC)

    def test_cancel(self):
        j1 = self.job(150.047, 6.0, 1, "error")
        studio = FakeStudio(self.arc, block=True, busy=1)   # 1 回目は 409 busy(ほかの書き出しが動いている = 待ってやり直す)
        ar = self.archiver(studio)
        ar.request("local", REC)
        self.assertTrue(wait_for(lambda: studio.calls, 60))
        self.assertEqual(ar.cancel("local", REC), 1)
        self.assertTrue(self.wait_state(j1))
        self.assertEqual(self.arc_of(j1)["state"], "cancelled")
        self.assertEqual(len(studio.cancelled), 1)   # スタジオの書き出しも取り消した
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.out, "配信の題", schemas.WORK_DIR, A.BUILD_DIR)), 10))
        self.assertEqual(ar.request("local", REC)["queued"], 1)   # 取り消したあとは、もう一度押せば始められる(自動では始めない)
        ar.cancel("local", REC)
        ar.close()
        # M7 の採用で待っていたジョブは、待ちのうちに取り消すとジョブも取り消しになる(書き出しの途中のまま残さない)
        j2 = self.job(220.0, 6.0, 2, "wait", **{"from": "archive"})
        ar2 = self.archiver(FakeStudio(self.arc))
        ar2.start = lambda: None
        ar2._queue([j2], auto=True)
        self.assertEqual(ar2.cancel("local", REC), 1)
        self.assertEqual((self.arc_of(j2)["state"], j2["state"]), ("cancelled", "cancelled"))

    def test_auto(self):
        j1 = self.job(150.047, 6.0, 1, "error")
        ended = {"t": time.time()}
        self.status = "post_live"
        slots = jobs.HeavySlots(2)
        ar = self.archiver(recording_state=lambda rc, rec: {"active": False, "endedAt": ended["t"]}, slots=slots,
                           first_delay=0.5, interval=0.4, give_up=60)
        self.assertEqual(ar.auto_tick(), 0)            # 終わってすぐは確かめない
        self.assertFalse(self.probes)
        time.sleep(0.6)
        self.assertEqual(ar.auto_tick(), 0)            # 確かめた: まだ(post_live)
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(ar.auto_tick(), 0)            # 間隔の前は確かめ直さない
        self.assertEqual(len(self.probes), 1)
        self.status = "was_live"
        time.sleep(0.45)
        tok = slots.acquire("studio", "ほかの重い処理")
        self.assertEqual(ar.auto_tick(), 0)            # 用意できたが、ほかの重い処理があるので待つ
        self.assertNotIn("archive", j1)
        slots.release(tok)
        self.assertEqual(ar.auto_tick(), 1)
        self.assertTrue(self.arc_of(j1)["auto"])
        self.assertTrue(self.wait_state(j1))
        self.assertEqual(self.arc_of(j1)["state"], "done")
        self.assertEqual(ar.auto_tick(), 0)            # 済んだものは入れない
        ar.close()
        # 7 日(縮めた)たっても用意できなければやめる
        j2 = self.job(220.0, 5.0, 2, "error", rec="20261005-130000-abcdefghijk")
        rec2 = j2["recording"]
        ar2 = self.archiver(recording_state=lambda rc, rec: None, first_delay=0, interval=0, give_up=1)   # 録画元につながらない: ジョブの時刻から
        self.status = "post_live"
        j2["end"] = LX.epoch_iso(time.time() - 5)
        self.assertEqual(ar2.auto_tick(), 0)
        self.assertIn("自動で書き出すのをやめました", ar2.info_view("local", rec2)["message"])
        n = len(self.probes)
        ar2.auto_tick()
        self.assertEqual(len(self.probes), n)

    def test_restart_continues(self):
        j1 = self.job(150.047, 6.0, 1, "error")
        j1["archive"] = {"state": "fetch", "label": "取得中", "progress": 0.4, "auto": False}
        self.ex._save()
        ex2 = self.exporter()   # 入口を起動し直した
        j = next(x for x in ex2.jobs if x["id"] == j1["id"])
        self.assertEqual(j["archive"]["state"], "wait")
        self.assertIn("起動し直した", j["archive"]["message"])
        self.ex = ex2
        ar = self.archiver()
        ar.start()
        self.assertTrue(self.wait_state(j))
        self.assertEqual(j["archive"]["state"], "done", j["archive"])
        ar3 = A.Archiver(ex2, studio=FakeStudio(self.arc))   # 用意の記録も残る
        self.assertTrue(ar3.info_view("local", REC)["ready"])
        # 途中のものがあるマークは書き出し直せない
        j["archive"] = dict(j["archive"], state="wait")
        self.assertTrue(ex2.busy(REC, j["markId"]))
        self.assertIn("アーカイブから書き出しています", str(ex2._busy_error(REC, j["markId"])))   # 画面に出す断りの文


@unittest.skipUnless(FF, "ffmpeg が無い")
class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-align-")

    def wav(self, name, expr, d, ss=None, t=None, af=None):
        src = os.path.join(self.tmp, name + ".src.wav")
        ff("-f", "lavfi", "-i", "aevalsrc=%s:s=8000:d=%d" % (expr, d), "-c:a", "pcm_s16le", src)
        if ss is None:
            return src
        out = os.path.join(self.tmp, name + ".wav")
        ff("-ss", "%.3f" % ss, "-t", "%.3f" % t, "-i", src, *(["-af", af] if af else []), "-c:a", "pcm_s16le", out)
        return out

    def test_offset_and_silence(self):
        win = self.wav("win", AUDIO, 120)
        ref = self.wav("ref", AUDIO, 120, ss=47.321, t=20, af="volume=0.3")
        r = A.run_align(ref, win)
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["offset"], 47.321, delta=0.002)
        self.assertGreater(r["score"], 0.95)
        self.assertGreater(r["ratio"], A.MIN_RATIO)
        self.assertEqual((r["refSec"], r["winSec"]), (20.0, 120.0))
        other = self.wav("other", OTHER, 60)
        r = A.run_align(ref, other)
        self.assertTrue(r["ok"] and r["score"] < A.MIN_SCORE, r)   # 別の音: 確かさが低い
        sil = os.path.join(self.tmp, "sil.wav")
        ff("-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "30", "-c:a", "pcm_s16le", sil)
        r = A.run_align(ref, sil)
        self.assertEqual((r["ok"], "無音" in r["reason"]), (False, True), r)
        r = A.run_align(win, ref)
        self.assertEqual(r["ok"], False)   # 窓の方が短い
        self.assertEqual(A.run_align(os.path.join(self.tmp, "none.wav"), win)["ok"], False)


class AfterStreamTest(unittest.TestCase):
    """線 D の M7(配信後の全自動。src/flow/live_archive.py の after_tick): 用意を待つ → 解析を頼む → 上位 N を採用(origin archive・hold archive)
    → アーカイブから書き出し → done。時刻合わせ(_after_offset)・スタジオ・採用(Live.adopt)は偽物(本物の通しは tests/app/e2e_live_archive.py の 9)"""
    HOURS = 3.0

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-after-")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.ex = LX.Exporter(FakeExLive(), os.path.join(self.tmp, "live"), lambda: self.out, disk_usage=lambda p: (100 * LX.GB, 200 * LX.GB))
        self.first = RELEASE + SKEW   # 録画の頭の受信時刻(アーカイブの秒 s ↔ 絶対時刻 RELEASE + s + SKEW = ずれ offset −SKEW)
        self.rec = {"recorder": "local", "id": REC, "url": "https://www.youtube.com/watch?v=" + VID, "title": "配信の題", "active": False,
                    "endedAt": time.time() - 7200, "firstPdt": self.first, "lastPdt": self.first + self.HOURS * 3600}
        self.status, self.on = "post_live", True
        self.arc_sec = (self.HOURS + 1) * 3600   # アーカイブの長さ(録画を止めたあとも 1 時間続いた配信)
        self.calls, self.queue, self.adopted = [], [], []
        self.analysis = None
        sc = [(1000, 9.0), (110, 8.5), (5000, 8.0), (20000, 7.5), (10750, 7.0), (2000, 6.5), (3000, 6.0), (4000, 5.5), (6000, 5.0), (7000, 4.5), (8000, 4.0)]
        self.marks = [{"id": "a%d" % i, "src": "auto", "status": "", "score": s, "start": float(t), "end": float(t + 60), "label": ""} for i, (t, s) in enumerate(sc)]
        self.marks += [{"id": "a99", "src": "auto", "status": "", "score": 7.2, "start": 12000.0, "end": 12060.0},   # 録画を止めたあと(配信の終わりまでは採用する)
                       {"id": "x1", "src": "auto", "status": "rejected", "score": 99.0, "start": 500.0, "end": 560.0},   # 人が不採用にした
                       {"id": "x2", "src": "manual", "status": "", "score": 50.0, "start": 600.0, "end": 660.0}]          # 人のマーク
        self.live_marks = [{"id": "h1", "status": "exported", "start": 100.0, "end": 160.0}]   # 録画の配信の人のマーク(録画の秒)
        self.reqs = {}   # (録画元, 録画) -> 友人のライブ配信の依頼(live_rules.RequestBook.get の代わり。2-15)
        self.arcs = []

    def tearDown(self):
        for a in self.arcs:
            a.close()   # 一時フォルダは testkit.tempdir が後で消す

    def studio(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/api/settings":
            return 200, {"settings": {"analyze": {"count": 8, "length": 60}}}
        if method == "POST" and path == "/api/queue/add":
            self.queue.append({"qid": "q1", "videoId": body["items"][0]["videoId"], "status": "running", "progress": 0.3, "phase": "音声"})
            return 200, {"added": [{"qid": "q1", "videoId": VID}], "rejected": []}
        if method == "GET" and path == "/api/queue":
            return 200, {"items": self.queue}
        if method == "GET" and path == "/api/video?id=" + VID:
            return 200, {"video": {"id": VID, "kind": "youtube", "analysis": self.analysis, "marks": self.marks}}
        if method == "GET" and path == "/api/video?id=" + REC and self.live_marks is not None:
            return 200, {"video": {"id": REC, "kind": "live", "marks": self.live_marks}}
        return 404, {"error": "not_found"}

    def adopt(self, body, hold=None):
        self.adopted.append((dict(body), hold))
        n = len(self.adopted)
        j = {"id": "lx-%010x" % (n * 31), "recorder": "local", "recording": REC, "markId": "lm-%012x" % n, "n": n, "label": body.get("label"),
             "start": body["start"], "end": body["end"], "state": "wait", "after": body.get("after"), "origin": body.get("origin"),
             "transcribe": True, "message": "", "error": "", "path": "", "runId": "", "warning": "", "created": LX.now_iso(), "updated": LX.now_iso()}
        if hold == "archive":
            j["from"] = "archive"   # 本物の Exporter.add と同じ(録画からは書き出さない)
        self.ex.jobs.append(j)
        return {"job": dict(j), "existing": False}

    def archiver(self, **kw):
        a = A.Archiver(self.ex, self.studio, probe=lambda vid: {"status": self.status, "release": RELEASE, "duration": self.arc_sec, "availability": "public"},
                       after_stream=lambda: self.on, per_hour=lambda: 2, recordings=lambda: [self.rec], adopt=self.adopt, first_delay=60, interval=0, poll=0.1,
                       request=lambda rc, rec: self.reqs.get((rc, rec)), **kw)
        a._after_offset = lambda rc, rec, vid, t0, first, last: (-SKEW, "テスト")
        a._queue = lambda js, auto: [j.update(archive={"state": "wait", "auto": auto}) for j in js]   # アーカイブからの書き出しは動かさない(順番に入れたことだけ)
        self.arcs.append(a)
        return a

    def test_pick_and_count(self):
        self.assertEqual((A.after_count(3 * 3600, 6), A.after_count(25, 6), A.after_count(100 * 3600, 6), A.after_count(1800, 3)), (18, 1, 30, 2))
        t0, off, first, last = 1000.0, -5.0, 1005.0, 1005.0 + 600
        marks = [{"src": "auto", "status": "", "score": 9, "start": 10.0, "end": 40.0},     # 録画の中
                 {"src": "auto", "status": "", "score": 8, "start": 100.0, "end": 150.0},   # 人のマーク(taken)と重なる
                 {"src": "auto", "status": "adopted", "score": 7.5, "start": 200.0, "end": 230.0},   # 判定済み
                 {"src": "manual", "status": "", "score": 7.2, "start": 250.0, "end": 280.0},       # 人のマーク
                 {"src": "auto", "status": "", "score": 7, "start": 700.0, "end": 730.0},   # 録画の外
                 {"src": "auto", "status": "", "score": 6, "start": 580.0, "end": 620.0},   # 半分以上が中 → 切り詰める
                 {"src": "auto", "status": "", "score": 5, "start": -30.0, "end": 5.0},     # 中は 5 秒 / 35 秒 → 使わない
                 {"src": "auto", "status": "", "score": 4, "start": 20.0, "end": 50.0},     # 選んだものと重なる
                 {"src": "auto", "status": "", "score": 3, "start": 300.0, "end": 330.0}]
        got = A.pick_candidates(marks, 3, t0, off, first, last, taken=[(first + 110, first + 140)])
        self.assertEqual([(round(a - first, 1), round(b - first, 1), m["score"]) for a, b, m in got], [(10.0, 40.0, 9), (300.0, 330.0, 3), (580.0, 600.0, 6)])
        self.assertEqual(A.pick_candidates(marks, 0, t0, off, first, last), [])

    def put_chat(self):
        """ライブで取ったチャット(② の置き場所 chat-keep)を、アーカイブの全体に 5 秒ごと置く(絶対時刻 = 開始 + SKEW + アーカイブの秒)"""
        d = os.path.join(self.ex.folder, A._chatreuse.KEEP_NAME)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, VID + ".0.live_chat.json"), "w", encoding="utf-8") as f:
            for i, s in enumerate(range(0, int(self.arc_sec), 5)):
                for k in range(1 + 4 * (i % 7 == 0)):   # 35 秒ごとに山(相関が測れるように)
                    r = {"id": "m%d-%d" % (i, k), "timestampUsec": str(int((RELEASE + SKEW + s + k * 0.1) * 1e6)), "message": {"runs": [{"text": "草"}]}}
                    f.write(json.dumps({"addChatItemAction": {"item": {"liveChatTextMessageRenderer": r}}}) + "\n")

    def test_live_chat_is_passed_or_compared(self):
        """ライブで取ったチャット(決定 3-117): on なら解析に chatFile で渡す(URL の依頼の口 chat_for も同じ物)/ measure なら渡さず、
        解析が済んだらリプレイと比べて chat-reuse.jsonl に 1 行"""
        self.put_chat()
        self.status = "was_live"
        with mock.patch.object(A._chatreuse, "MODE", "on"):
            a = self.archiver()
            a.after_tick()
            add = next(c for c in self.calls if c[1] == "/api/queue/add")[2]
            made = os.path.join(self.ex.folder, A._chatreuse.KEEP_NAME, VID + ".replay.json")
            self.assertEqual(add["items"][0].get("chatFile"), made)
            self.assertIs(a.info[a.key("local", REC)]["afterStream"]["chatReuse"]["used"], True)   # 印(archive.json の afterStream)
            self.assertEqual(a.chat_for(VID), made)
            self.assertIsNone(a.chat_for("zzzzzzzzzzz"))
        self.calls.clear()
        self.queue.clear()
        a2 = self.archiver()
        with mock.patch.object(A._chatreuse, "MODE", "measure"):
            a2._after_set("local", REC, state="", message="")
            a2.info[a2.key("local", REC)].pop("afterStream", None)
            a2.after_tick()
            add = next(c for c in self.calls if c[1] == "/api/queue/add")[2]
            self.assertNotIn("chatFile", add["items"][0])
            replay = os.path.join(self.tmp, "replay.json")
            shutil.copyfile(made, replay)   # 解析が取ったリプレイの代わり(同じ中身 = 近い)
            with mock.patch.object(A._fetch, "chat_cache_path", lambda vid: replay):
                self.queue[0]["status"], self.analysis = "done", {"at": 1}
                a2.after_tick()
        with open(os.path.join(self.ex.folder, A._chatreuse.LOG_NAME), encoding="utf-8") as f:
            rows = [json.loads(x) for x in f]
        cmp = [r for r in rows if r["kind"] == "compare"]
        self.assertEqual(len(cmp), 1)
        self.assertTrue(A._chatreuse.ok(cmp[0]), cmp[0])

    def test_flow_to_done(self):
        a = self.archiver()
        self.assertEqual(a.after_tick(), 0)                                    # 用意がまだ(post_live)
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual(st["state"], "wait")
        self.assertIn("処理中", st["message"])
        self.assertTrue(a.after_stream_hold("local", dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))))   # まだなので録画は消さない
        self.status = "was_live"
        self.assertEqual(a.after_tick(), 1)                                    # 用意できた → 解析を頼む
        add = next(c for c in self.calls if c[1] == "/api/queue/add")[2]
        self.assertEqual(add["items"], [{"kind": "youtube", "videoId": VID, "title": "配信の題"}])   # アーカイブの videoId で解析
        self.assertEqual((add["settings"]["count"], add["settings"]["length"]), (12, 60))           # N = 3 時間 × 2 = 6 → 候補は 2 倍まで・ほかはスタジオの設定
        self.assertEqual(a.info_view("local", REC)["afterStream"]["state"], "analyze")
        a.after_tick()
        self.assertIn("30%", a.info_view("local", REC)["afterStream"]["message"])
        self.assertEqual(self.adopted, [])
        self.queue[0]["status"], self.analysis = "done", {"at": 1}
        a.after_tick()                                                          # 解析が済んだ → 上位 N を採用
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual((st["state"], st["n"], st["jobs"]), ("export", 6, 6), st)
        secs = [round(LX.iso_epoch(b["start"]) - self.first, 1) for b, h in self.adopted]
        ends = [round(LX.iso_epoch(b["end"]) - self.first, 1) for b, h in self.adopted]
        self.assertEqual(sorted(secs), [1000.0, 2000.0, 3000.0, 5000.0, 10750.0, 12000.0])   # 人のマークと重なる 110・配信の外 20000 は飛ばす・録画の後(12000)も採る
        self.assertIn(10810.0, ends)   # 録画の終わり(10800)で切り詰めない(配信の終わりまで)
        self.assertAlmostEqual(a.info_view("local", REC)["afterStream"]["n"], 6)
        self.assertEqual({(b["origin"], b["after"], h) for b, h in self.adopted}, {("archive", "auto", "archive")})
        self.assertTrue(all(b["recorder"] == "local" and b["recording"] == REC for b, h in self.adopted))
        # 採用した候補はアーカイブからの書き出しに入れる(録画からは書き出さない)
        self.assertTrue(all(j["state"] == "wait" and j["from"] == "archive" for j in self.ex.jobs))
        a.after_tick()
        self.assertTrue(all((j.get("archive") or {}).get("state") == "wait" and j["archive"]["auto"] for j in self.ex.jobs))
        self.assertEqual(a.info_view("local", REC)["afterStream"]["state"], "export")
        for j in self.ex.jobs[:-1]:
            j.update(state="done", archive={"state": "done"}, runId="run-" + j["id"])
        last = self.ex.jobs[-1]
        last.update(state="error", needsArchive=True, error="合いませんでした", archive={"state": "error", "message": "合いませんでした"})   # 書き出せなかった
        a.after_tick()
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual(st["state"], "done", st)
        self.assertIn("6 本のうち 5 本", st["message"])
        self.assertIn("失敗 1 本", st["message"])
        self.assertEqual(a.after_stream_hold("local", dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))), "")   # 済んだので消してよい
        n = len(self.calls)
        self.assertEqual(a.after_tick(), 0)                                    # 済んだ録画はもう触らない
        self.assertEqual(len(self.calls), n)

    def test_measure_only(self):
        """EV-1: 配信後の全自動がオフでも、配信中の検出の記録がある録画(measure)はアーカイブを解析して比べる(採用しない)→ measured。
        比べるときに録画の欠け(録画元の /segments の gaps を 2 時間ずつ)を渡す。測り終えるまで録画を消さない。YTT_LIVE_MEASURE=off で止める"""
        self.on, self.status = False, "was_live"
        compared, queried = [], []

        def query(rc, rec, a, b):
            queried.append(round(b - a))
            gaps = [{"from": LX.epoch_iso(self.first + 100), "to": LX.epoch_iso(self.first + 160), "sec": 60}] if a == self.first else []
            return 200, {"segments": [], "gaps": gaps}
        self.ex._query = query
        a = self.archiver(compare=lambda rc, rec, af, marks, holes=None: compared.append((af.get("mode"), holes)) or {"archive": 5, "hit": 3, "excluded": 1},
                          measure=lambda rc, rec: True)
        rec = dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))
        self.assertIn("測り直し", a.after_stream_hold("local", rec))          # 測り終えるまで録画を消さない
        with mock.patch.dict(os.environ, {"YTT_LIVE_MEASURE": "off"}):
            self.assertEqual(a.after_tick(), 0)                                # 止めるスイッチ
            self.assertEqual(a.after_stream_hold("local", rec), "")
        self.assertEqual(a.after_tick(), 1)                                    # 用意できた → 解析を頼む
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual(st["state"], "analyze")
        self.assertIn("配信中の検出を測ります", st["message"])
        self.queue[0]["status"], self.analysis = "done", {"at": 1}
        a.after_tick()
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual(st["state"], "measured", st)
        self.assertIn("配信中にも出た 3 件(穴で外した 1 件)", st["message"])
        self.assertEqual(self.adopted, [])                                     # 採用しない
        self.assertEqual(compared, [("measure", [(100.0, 160.0)])])            # 録画の欠けを渡した(録画の頭からの秒)
        self.assertEqual(queried, [7200, 3600])                                # 3 時間の録画を 2 時間ずつ聞いた
        self.assertEqual(a.after_stream_hold("local", rec), "")               # 済んだので消してよい
        self.assertEqual(a.after_tick(), 0)
        # 測るものが無い録画(検出の記録が無い)は何もしない
        b = self.archiver(measure=lambda rc, rec: False)
        b.info.clear()
        self.assertEqual(b.after_tick(), 0)
        self.assertEqual(b.after_stream_hold("local", rec), "")
        # 録画元につながらない: 欠けは分からない(None)まま比べる
        self.ex._query = lambda rc, rec, a_, b_: (None, None)
        self.assertIsNone(a._rec_holes("local", REC, {"first": self.first, "last": self.first + 10}))

    def test_archived(self):
        """アーカイブ化したか(録画を消す合図): was_live・限定でない・開始と長さが分かる・アーカイブが録画の終わりまである。消す直前に必ず確かめ直す"""
        a = self.archiver()
        a.interval = 3600.0
        probes = []
        info = {"status": "was_live", "release": RELEASE, "duration": self.arc_sec, "availability": "public"}
        a.probe = lambda vid: probes.append(vid) or dict(info)
        r = dict(self.rec, endedAt=self.first + self.HOURS * 3600)
        self.assertEqual(a.archived("local", r), "")
        self.assertEqual(a.archived("local", r), "")
        self.assertEqual(len(probes), 2)   # 用意できた記録があっても、消す直前は確かめ直す
        info["duration"] = 3600.0          # アーカイブが短い(切られた・別の動画)
        self.assertIn("足りない", a.archived("local", r))
        info.update(duration=self.HOURS * 3600 - A.ARCHIVED_SLACK + 60)   # 少し短いのは許す(開始時刻のずれ)
        self.assertEqual(a.archived("local", r), "")
        info.update(availability="subscriber_only")
        self.assertTrue(a.archived("local", r).startswith(A.NOT_ARCHIVED))
        info.update(availability="public", status="post_live")
        a.info.clear()
        n = len(probes)
        self.assertIn("処理中", a.archived("local", r))
        self.assertIn("処理中", a.archived("local", r))
        self.assertEqual(len(probes), n + 1)   # 用意がまだと分かったばかりなら確かめ直さない
        info.update(status="was_live", duration=None)
        a.interval = 0
        self.assertIn("長さが分からない", a.archived("local", r))
        self.assertIn("YouTube の動画が分からない", a.archived("local", dict(r, url="http://127.0.0.1:1/x.m3u8", id="20261005-120000-local")))

    def test_taken_from_marks_book(self):
        """重ねない採用はマークの置き場から(taken。headless のスタジオなしの採用 = 案件の 採用.json か正本)。
        スタジオに録画の配信が無くても、置き場の採用と重なる候補は飛ばす・読めない(None・例外)なら重ねる物なしで続ける"""
        self.live_marks = None   # スタジオに録画の配信は無い(スタジオなし)
        asked = []

        def taken(rc, rec):
            asked.append((rc, rec))
            return [{"id": "a1", "status": "adopted", "start": 1000.0, "end": 1060.0}, {"id": "a2", "status": "", "start": 5000.0, "end": 5060.0}]
        a = self.archiver(taken=taken)
        self.status, self.analysis = "was_live", {"at": 1}
        a.after_tick()   # 解析済み → すぐ採用
        self.assertEqual(asked, [("local", REC)])
        secs = sorted(round(LX.iso_epoch(b["start"]) - self.first, 1) for b, h in self.adopted)
        self.assertNotIn(1000.0, secs)   # 置き場の採用と重なる
        self.assertIn(5000.0, secs)      # 候補のまま(採用でない)の印は重ねない区間に入れない
        self.assertIn(110.0, secs)       # スタジオの録画の配信(人のマーク 100〜160)はもう見ない
        a2 = self.archiver(taken=lambda rc, rec: 1 / 0)
        self.adopted.clear()
        a2.info.clear()
        a2.after_tick()
        self.assertEqual(len(self.adopted), 6)   # 読めなくても止めない

    def test_progress_for_the_band(self):
        """スタジオの LIVE の帯に出す進み具合: GET /live/api/exports の archiveInfo.afterStream の progress と text"""
        a = {"state": "export", "label": A.AFTER_LABELS["export"], "message": "3 本を採用しました", "jobs": ["j1", "j2", "j3", "j4"]}
        jobs = [{"id": "j1", "state": "done", "archive": {"state": "done"}, "runId": "r1", "tx": {"state": "done"}},
                {"id": "j2", "state": "done", "archive": {"state": "done"}, "runId": "r2", "tx": {"state": "running"}},
                {"id": "j3", "state": "error", "failure": {"kind": "export", "text": "書き出せませんでした"}},
                {"id": "other", "state": "done", "runId": "r9", "tx": {"state": "done"}}]   # 人の書き出し(数えない)
        p = A.after_progress(a, jobs)
        self.assertEqual(p, {"total": 4, "exported": 2, "archived": 2, "handed": 2, "finished": 1, "failed": 1})   # j4 は一覧から消えた(total だけ)
        self.assertEqual(A.after_text(a, p), "配信後の自動の切り抜き: アーカイブから書き出し → パック(4 本のうち アーカイブから書き出し 2・文字起こし → パックへ 2・パックまで済み 1・失敗 1)")
        w = {"state": "wait", "label": A.AFTER_LABELS["wait"], "message": "アーカイブはまだ処理中です"}
        self.assertEqual(A.after_text(w, A.after_progress(w, jobs)), "配信後の自動の切り抜き: アーカイブの用意を待っています(アーカイブはまだ処理中です)")
        self.assertEqual(A.after_progress({}, None)["total"], 0)
        ar = self.archiver()
        self.assertNotIn("afterStream", ar.info_view("local", REC, []))   # 配信後の全自動が無い録画は今までどおり
        ar._after_set("local", REC, state="export", jobs=["j1", "j2"], message="2 本を採用しました")
        st = ar.info_view("local", REC, jobs)["afterStream"]
        self.assertEqual((st["jobs"], st["progress"]["finished"], st["text"]), (2, 1, A.after_text(st, st["progress"])))
        self.assertEqual(ar.info_view("local", REC)["afterStream"]["progress"]["total"], 2)   # jobs を渡さなければ書き出しの一覧から

    def test_ended_at_accepts_epoch_and_iso(self):
        """録画の一覧の行の「終わった時刻」(ended_at): epoch(入口の list_recordings)と ISO の文字列(録画の部品の生の行)のどちらでも同じ値。
        endedAt が無ければ lastPdt。録画を消すのを待つか(after_stream_hold)も、どちらの形で渡しても古い録画は待たない"""
        t = 1790000000.5
        for row in ({"endedAt": t}, {"endedAt": LX.epoch_iso(t)}, {"endedAt": None, "lastPdt": t}, {"endedAt": "", "lastPdt": LX.epoch_iso(t)}):
            self.assertAlmostEqual(A.ended_at(row), t, places=3, msg=row)
        self.assertIsNone(A.ended_at({}))
        self.assertIsNone(A.ended_at({"endedAt": True, "lastPdt": "読めない"}))
        a = self.archiver()
        old = time.time() - A.AFTER_MAX_AGE - 60
        for ended in (old, LX.epoch_iso(old)):
            self.assertEqual(a.after_stream_hold("local", dict(self.rec, endedAt=ended)), "", ended)   # 終わって AFTER_MAX_AGE を過ぎた録画は待たない
        for ended in (time.time() - 7200, LX.epoch_iso(time.time() - 7200)):
            self.assertTrue(a.after_stream_hold("local", dict(self.rec, endedAt=ended)), ended)      # まだなので待つ

    def test_off_old_no_video_and_failure_text(self):
        a = self.archiver()
        self.on = False
        self.assertEqual(a.after_tick(), 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(a.after_stream_hold("local", dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))), "")
        self.on = True
        self.rec["endedAt"] = time.time() - A.AFTER_MAX_AGE - 60                 # 古い録画(オンにする前)は始めない
        self.status = "was_live"
        self.assertEqual(a.after_tick(), 0)
        self.assertEqual(self.calls, [])
        self.rec.update(endedAt=time.time() - 30)                                # 終わってすぐ(first_delay の前)も始めない
        self.assertEqual(a.after_tick(), 0)
        self.rec.update(endedAt=time.time() - 7200, url="http://127.0.0.1:1/x.m3u8", id="20261005-120000-local")   # YouTube の動画が分からない
        a.after_tick()
        i = a.info_view("local", "20261005-120000-local")["afterStream"]
        self.assertEqual(i["state"], "error")
        a._after_set("local", REC, state="error", message="アーカイブの解析が終わりませんでした: 取れません", title="配信の題")
        texts = sorted(x["text"] for x in a.after_failures())
        self.assertIn("「配信の題」: 配信後の自動の切り抜きに失敗しました: アーカイブの解析が終わりませんでした: 取れません", texts)
        self.assertEqual({x["kind"] for x in a.after_failures()}, {"afterStream"})

    def test_disk_low_waits(self):
        free = {"v": 1 * LX.GB}
        self.ex.disk_usage = lambda p: (free["v"], 100 * LX.GB)
        self.ex.disk_poll = 0
        self.status = "was_live"
        a = self.archiver()
        a.after_tick()
        st = a.info_view("local", REC)["afterStream"]
        self.assertNotEqual(st.get("state"), "analyze")
        self.assertIn("空き容量が少ない", st["message"])
        self.assertFalse(any(c[1] == "/api/queue/add" for c in self.calls))
        free["v"] = 50 * LX.GB
        i = a.info.get(a.key("local", REC))
        i["afterStream"]["retryAt"] = 0
        a.after_tick()
        self.assertEqual(a.info_view("local", REC)["afterStream"]["state"], "analyze")

    def test_friend_request_runs_with_switch_off(self):
        """2-15: 友人のライブ配信の依頼の録画は、ホームの M7 がオフでも依頼の afterStream が真なら進める(本数は依頼の perHour)・済むまで録画を消さない"""
        self.on, self.status = False, "was_live"
        self.reqs[("local", REC)] = {"rid": "20261008-120000-abcd", "settings": {"afterStream": True, "perHour": 3}}
        a = self.archiver()
        rec = dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))
        self.assertTrue(a.after_stream_hold("local", rec))                     # ホームの M7 はオフでも、この録画は済むまで消さない
        self.assertEqual(a.after_tick(), 1)                                    # 用意できた → 解析を頼む
        add = next(c for c in self.calls if c[1] == "/api/queue/add")[2]
        self.assertEqual(add["settings"]["count"], 18)                         # N = 3 時間 × 依頼の 3 本 = 9(ホームの 2 本なら 6)→ 候補は 2 倍
        self.queue[0]["status"], self.analysis = "done", {"at": 1}
        a.after_tick()                                                          # 解析が済んだ → 上位 N を採用
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual((st["state"], st["n"], st["jobs"]), ("export", 9, 9), st)
        self.assertEqual({(b["origin"], b["after"], h) for b, h in self.adopted}, {("archive", "auto", "archive")})
        self.reqs.clear()                                                       # 結びつきが消えた(14 日)= ホームのスイッチのまま
        self.assertEqual(a.after_stream_hold("local", rec), "")

    def test_friend_request_without_after_stream(self):
        """2-15: 依頼の afterStream が偽の録画では M7 を動かさない(ホームの M7 がオフでもオンでも。録画を消すのも待たない)。依頼の無い録画はホームの M7 の設定どおり"""
        self.status = "was_live"
        self.reqs[("local", REC)] = {"rid": "20261008-120000-abcd", "settings": {"afterStream": False, "perHour": 3}}
        a = self.archiver()
        rec = dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))
        for on in (False, True):
            self.on = on
            self.assertEqual(a.after_tick(), 0, on)
            self.assertEqual((self.calls, self.adopted), ([], []), on)
            self.assertEqual(a.after_stream_hold("local", rec), "", on)
        self.assertNotIn("afterStream", a.info_view("local", REC))
        self.reqs[("local", REC)] = {"rid": "20261008-120000-abcd"}            # settings の無い(壊れた)記録も「頼まれていない」
        self.assertFalse(a._request_after("local", REC))
        self.assertEqual(a.after_tick(), 0)
        self.reqs.clear()                                                       # 依頼の無い録画はホームのスイッチ(オン)で
        self.assertEqual(a.after_tick(), 1)
        self.assertEqual(a.info_view("local", REC)["afterStream"]["state"], "analyze")

    def test_per_hour_for_request(self):
        """配信後の 1 時間あたりの本数: 友人の依頼の録画は依頼の perHour、無い・壊れた値ならホームの設定(per_hour)"""
        a = self.archiver()
        self.assertIs(a.request.__func__, A.Archiver.request)   # 引数 request(依頼の結びつき)が「アーカイブからの書き出しを頼む」メソッド(POST /live/api/archive)を上書きしない
        self.assertEqual(a._per_hour_for("local", REC), 2)
        self.reqs[("local", REC)] = {"rid": "r", "settings": {"perHour": 5}}
        self.assertEqual(a._per_hour_for("local", REC), 5)
        self.assertEqual(a._per_hour_for("local", "20261005-130000-other"), 2)   # ほかの録画はホームの設定
        for bad in (0, -1, True, "5", 2.5, None):
            self.reqs[("local", REC)] = {"rid": "r", "settings": {"perHour": bad}}
            self.assertEqual(a._per_hour_for("local", REC), 2, bad)
        self.reqs[("local", REC)] = {"rid": "r", "settings": None}
        self.assertEqual(a._per_hour_for("local", REC), 2)


class YtdlpRetryTest(unittest.TestCase):
    """yt-dlp の一時的な失敗(HTTP 403 など)は、あけて 2 回までやり直す(用意の確認・音の取得)。照合のしきい値"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-live-ytdlp-")
        self.calls = []

    def fake_run(self, answers, folder=None):
        def run(cmd, timeout, cancelled=None):
            self.calls.append(cmd)
            code, out, tail = answers.pop(0)
            if code == 0 and folder:
                with open(os.path.join(folder, "full.webm"), "wb") as f:
                    f.write(b"x")
            return code, out, tail
        return run

    def test_probe_retries(self):
        ok = (0, "was_live\t1790000000\t1790007200\t100\tpublic\n", [])
        e403 = (1, "", ["ERROR: unable to download video data: HTTP Error 403: Forbidden"])
        with mock.patch.object(A.tools, "find_tool", return_value="yt-dlp"), mock.patch.object(A, "run_proc", self.fake_run([e403, e403, ok])):
            p = A.probe_archive("abcdefghijk", wait=0)
        self.assertEqual((p["status"], p["release"], len(self.calls)), ("was_live", 1790000000.0, 3))
        self.calls[:] = []
        with mock.patch.object(A.tools, "find_tool", return_value="yt-dlp"), mock.patch.object(A, "run_proc", self.fake_run([e403, e403, e403, ok])):
            p = A.probe_archive("abcdefghijk", wait=0)
        self.assertEqual((p["status"], len(self.calls)), ("unknown", 3))   # 2 回までやり直して、だめなら調べられない
        self.assertIn("403", p["message"])
        self.calls[:] = []
        member = (1, "", ["ERROR: Join this channel to get access to members-only content"])
        with mock.patch.object(A.tools, "find_tool", return_value="yt-dlp"), mock.patch.object(A, "run_proc", self.fake_run([member, ok])):
            p = A.probe_archive("abcdefghijk", wait=0)
        self.assertEqual((p["availability"], len(self.calls)), ("subscriber_only", 1))   # メンバー限定はやり直さない

    def test_probe_does_not_retry_final_failures(self):
        """やり直しても変わらない失敗(id が正しくない・yt-dlp が無い)は待たずに返す(印 final で決める。画面の文の中身では決めない)。
        印は結果に残さない"""
        with mock.patch.object(A, "run_proc", self.fake_run([])), mock.patch.object(A, "_pause", side_effect=AssertionError("待った")):
            p = A.probe_archive("bad id", wait=0)
            self.assertEqual((p["status"], "final" in p), ("unknown", False))
            self.assertIn("正しくありません", p["message"])
            with mock.patch.object(A.tools, "find_tool", return_value=None):
                p = A.probe_archive("abcdefghijk", wait=0)
            self.assertEqual((p["status"], "final" in p), ("unknown", False))
            self.assertIn("yt-dlp", p["message"])
        self.assertEqual(self.calls, [])

    def test_full_audio_retries(self):
        e403 = (1, "", ["ERROR: HTTP Error 403: Forbidden"])
        with mock.patch.object(A.tools, "find_tool", return_value="yt-dlp"), mock.patch.object(A, "run_proc", self.fake_run([e403, (0, "", [])], self.tmp)):
            p = A.fetch_full_audio("abcdefghijk", self.tmp, wait=0)
        self.assertEqual((os.path.basename(p), len(self.calls)), ("full.webm", 2))
        cmd = self.calls[0]
        self.assertEqual(cmd[cmd.index("-f") + 1], "ba")                 # スタジオの書き出し(bv*+ba)と同じ音
        self.assertNotIn("--download-sections", cmd)                     # 区間の取得は使わない(遅い・形式で頭がずれる)
        self.assertEqual(cmd[-2:], ["--", "https://www.youtube.com/watch?v=abcdefghijk"])
        os.unlink(p)
        self.calls[:] = []
        with mock.patch.object(A.tools, "find_tool", return_value="yt-dlp"), mock.patch.object(A, "run_proc", self.fake_run([e403, e403, e403])):
            with self.assertRaises(A.ArchiveError) as cm:
                A.fetch_full_audio("abcdefghijk", self.tmp, wait=0)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("403", str(cm.exception))
        with self.assertRaises(LX.Cancelled):   # やり直しを待つ間も取り消せる
            with mock.patch.object(A.tools, "find_tool", return_value="yt-dlp"), mock.patch.object(A, "run_proc", self.fake_run([e403, e403])):
                A.fetch_full_audio("abcdefghijk", self.tmp, cancelled=lambda: True, wait=5)

    def test_thresholds(self):
        self.assertEqual((A.MIN_SCORE, A.MIN_RATIO), (0.5, 3.0))   # 本物の配信: 合わない区間で ratio 1.58 が出た・正しい区間は 4.7〜58
        self.assertEqual((A.WINDOWS_FIRST[0], A.WINDOWS_NEXT[0]), (300.0, 20.0))


if __name__ == "__main__":
    unittest.main()
