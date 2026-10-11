# -*- coding: utf-8 -*-
"""アーカイブで本番版に作り直す(線 D の P4。src/flow/live_archive.py・src/pipeline/ingest/live_align_worker.py)のテスト。入口を通す API の分は src/home/tests/test_live_archive_api.py。本物の YouTube には繋がない。

    py -3.10 -m unittest src/flow/tests/test_live_archive.py

作るもの(ffmpeg の lavfi): 「アーカイブ」= 映像 testsrc2 の 60fps + 時間で変わる音(周波数が動く sine + ノイズ)。
「速報版」= その途中の区間を別の符号化(AAC の作り直し・音量 60%・頭を数十 ms ずらした所から)で 30fps に切り出したもの。
偽の yt-dlp(窓の音 = アーカイブから ffmpeg で切る)・偽のスタジオの section(アーカイブから ffmpeg で 30fps に切る)で動かす。

確かめること:
  - 照合で求めたアーカイブの秒が正解 ±0.02 秒・入れ替え後のファイルが 30fps で長さが同じ・速報版が 作業用\\速報版 にある・clip.json の archive・
    ジョブの archive.state が done・2 本目は前のずれの ±20 秒の窓・作りかけのフォルダが残らない
  - 欠けのマーク(速報版なし)は近いマークのずれで新しく作る(job.state done・path・clip.json の archive)
  - 本番版と速報版の音が 1 コマより大きくずれたら、1 回だけ足して作り直す
  - 用意がまだ(post_live)→ 409 で待つ・開始時刻が無い・無音や別の音 → 照合できず入れ替えない・速報版が書き出し先の外 → 入れ替えない
  - 取り消し(スタジオの書き出しも取り消す)・使用中で動かせない → 待ちに戻して、作った本番版で後から入れ替える
  - 自動の見回り(時間を縮めて): 録画が終わって少したってから・用意ができたら・重い処理があれば待つ・7 日(縮めた)でやめる
  - 起動し直しで続く(途中の段 → 待ち)・スタジオが 409 busy なら待ってやり直す
  - worker 単体(ずれの正しさ・無音)
  - 配信後の全自動(M7)と友人のライブ配信の依頼(2-15): 依頼の afterStream が真ならホームの M7 がオフでも進める(本数は依頼の perHour)・
    偽ならホームの M7 がオンでも動かさない・録画を消すのを待つか(after_stream_hold)も同じ決め方
"""
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
from flow import live_archive as A  # noqa: E402
from flow import live_export as LX  # noqa: E402
from ytt import fsio, jobs, normalize, schemas, tools  # noqa: E402

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
    def test_wav_args_unchanged(self):
        """OPT2: 照合の wav(8kHz・精密な切り方)を作る ffmpeg の引数の列は、引数を組む所を ① へ移しても 1 つも変わらない"""
        tmp = tempfile.mkdtemp(prefix="ytt-arc-wav-")
        self.addCleanup(shutil.rmtree, tmp, True)
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
            A.Archiver._wav(me, "src.m4a", dst)
            A.Archiver._wav(me, "src.m4a", dst, 3.0, 5.0, {"id": "j"})
            A.Archiver._wav(me, "src.m4a", dst, 25.5, 4.25, {"id": "j"})
            A.Archiver._wav(me, "src.m4a", dst, 0.0, 0)
        head = ["FF", "-hide_banner", "-nostdin", "-y", "-v", "error"]
        tail = ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", "-f", "wav", dst]
        self.assertEqual([c for c, _, _ in cmds], [
            head + ["-i", "src.m4a"] + tail,
            head + ["-i", "src.m4a", "-ss", "3.000", "-t", "5.000"] + tail,                         # 手前 10 秒より前: 全部デコードして切る
            head + ["-ss", "15.500", "-i", "src.m4a", "-ss", "10.000", "-t", "4.250"] + tail,      # 手前まで入力側・残り 10 秒は出力側
            head + ["-i", "src.m4a"] + tail])                                                     # 0 は付けない
        self.assertEqual([(t, c) for _, t, c in cmds], [(A.FFMPEG_TIMEOUT, False), (A.FFMPEG_TIMEOUT, True), (A.FFMPEG_TIMEOUT, True), (A.FFMPEG_TIMEOUT, False)])


@unittest.skipUnless(FF, "ffmpeg が無い")
class ArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fix = tempfile.mkdtemp(prefix="ytt-live-arc-fix-")
        cls.arc = os.path.join(cls.fix, "archive.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=60:d=%d" % ARC_SEC, "-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=%d" % (AUDIO, ARC_SEC),
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", cls.arc)
        cls.other = os.path.join(cls.fix, "other.mp4")   # 別の音(照合できないはず)
        ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20", "-f", "lavfi", "-i", "aevalsrc=%s:s=48000:d=20" % OTHER,
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.other)
        cls.silent = os.path.join(cls.fix, "silent.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=20", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-t", "20", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.silent)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fix, ignore_errors=True)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-arc-")
        self.out = os.path.join(self.tmp, "out")
        self.store = os.path.join(self.tmp, "live")
        os.makedirs(self.out)
        self.status = "was_live"
        self.release = RELEASE
        self.probes, self.fetches, self.aligns = [], [], []
        self.ex = LX.Exporter(FakeExLive(), self.store, lambda: self.out)
        self.ex.marks.upsert("local", REC, "lm-000000000001", 1, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1),
                             url="https://www.youtube.com/watch?v=" + VID, title="配信の題")
        self.arcs = []

    def tearDown(self):
        for a in self.arcs:
            a.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- 偽物 ---
    def probe(self, vid):
        self.probes.append(vid)
        return {"status": self.status, "release": self.release, "timestamp": RELEASE + 7200, "duration": ARC_SEC, "availability": "public"}   # timestamp(配信の終わりごろ)は使わない

    def audio(self, vid, folder, cancelled=None, late=0.0):
        """偽の yt-dlp: 配信の丸ごとの音(m4a)。late: 頭を削って、アーカイブの秒より late 秒遅れた音にする"""
        self.fetches.append(vid)
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, "full.m4a")
        ff(*(["-ss", "%.3f" % late] if late else []), "-i", self.arc, "-vn", "-c:a", "aac", "-b:a", "128k", p)
        return p

    def align(self, ref, win):
        self.aligns.append(win)
        return A.run_align(ref, win)

    def archiver(self, studio=None, **kw):
        opts = dict(studio=studio or FakeStudio(self.arc), probe=self.probe, audio=self.audio, align=self.align, poll=0.1, step=0.1, retry_sec=0.3)
        opts.update(kw)
        a = A.Archiver(self.ex, **opts)
        self.arcs.append(a)
        return a

    # --- 速報版とジョブ ---
    def speed(self, true_start, dur, n, src=None, label=""):
        """速報版(アーカイブの true_start から dur 秒。音は AAC で作り直して音量 60%)と、済んだ書き出しのジョブ"""
        folder = os.path.join(self.out, "配信の題")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "%02d_00h0%dm00s-00h0%dm10s.mp4" % (n, n, n))
        ff("-ss", "%.3f" % true_start, "-i", src or self.arc, "-t", "%.3f" % dur, "-map", "0:v:0", "-map", "0:a:0", "-vf", "fps=30",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-af", "volume=0.6", "-c:a", "aac", "-b:a", "96k", path)
        job = self.job(true_start, dur, n, "done", label)
        clip = schemas.build_clip(path, dur, {"kind": "youtube", "videoId": VID, "title": "配信の題"}, (10.0, 10.0 + dur),
                                  {"id": job["markId"], "label": "", "status": "exported", "src": "manual"},
                                  {"mode": "precise", "fps": "30/1", "from": "live-recording", "volume": 75}, LX.TOOL)
        clip["source"] = {"kind": "live", "videoId": VID, "url": None, "title": "配信の題", "path": None,
                          "live": {"recorder": "local", "recording": REC, "markId": job["markId"]}}
        manifest = schemas.clip_path_for(path)
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        fsio.write_json(manifest, clip)
        job.update(path=path, manifest=manifest)
        self.ex._save()
        return job, path

    def job(self, true_start, dur, n, state, label=""):
        a = RELEASE + true_start + SKEW   # 録画の受信時刻(= マークの絶対時刻)。アーカイブの秒の見当 a − 開始時刻 は SKEW だけ大きい
        j = {"id": "lx-%010x" % (n * 7919), "recorder": "local", "recording": REC, "markId": "lm-%012x" % n, "n": n, "label": label,
             "start": LX.epoch_iso(a), "end": LX.epoch_iso(a + dur), "transcribe": False, "state": state, "message": "", "error": "",
             "needsArchive": state == "error", "progress": 1.0 if state == "done" else 0, "source": "local", "path": "", "manifest": "",
             "runId": "", "warning": "", "attempts": 1, "created": LX.now_iso(), "updated": LX.now_iso(),
             "recBase": LX.epoch_iso(RELEASE + SKEW + 100.0),
             "studio": {"video": REC, "mark": "m%d" % n, "start": true_start - 100.0, "end": true_start - 100.0 + dur}}
        self.ex.jobs.append(j)
        self.ex._save()
        return j

    def arc_of(self, job):
        return dict(job.get("archive") or {})

    def wait_state(self, job, states=("done", "error", "cancelled"), timeout=120):
        return wait_for(lambda: self.arc_of(job).get("state") in states, timeout)

    def assert_30fps(self, path, dur):
        info = normalize.probe(path)
        self.assertTrue(normalize.is_30fps(info), info)
        self.assertAlmostEqual(info["duration"], dur, delta=LX.LEN_TOL)

    # --- テスト ---
    def test_replace_and_new_from_archive(self):
        j1, p1 = self.speed(150.047, 12.0, 1, label="一つ目")
        j2, p2 = self.speed(220.031, 8.0, 2)
        j3 = self.job(260.0, 6.0, 3, "error")   # 欠けで書き出せなかった(速報版なし)
        size1 = os.path.getsize(p1)
        studio = FakeStudio(self.arc)
        afters, asked = [], []
        ar = self.archiver(studio, after=lambda rc, rec: afters.append((rc, rec)),
                           pack_info=lambda path: asked.append(path) or ({"dir": "p"} if path == p1 else None))   # 1 本目だけ前に作ったパックがある
        self.assertEqual(ar.info_view("local", REC), {"ready": None, "checkedAt": None, "message": ""})
        r = ar.request("local", REC)
        self.assertEqual((r["ok"], r["queued"]), (True, 3), r)
        for j in (j1, j2, j3):
            self.assertTrue(self.wait_state(j), self.arc_of(j))
        for j, true in ((j1, 150.047), (j2, 220.031)):
            a = self.arc_of(j)
            self.assertEqual(a["state"], "done", a)
            self.assertAlmostEqual(a["archiveStart"], true, delta=0.02, msg=a)   # 照合で求めたアーカイブの秒
            self.assertAlmostEqual(a["offset"], -SKEW, delta=0.02)   # 見当(受信時刻 − 開始時刻)からアーカイブの秒までの差
            self.assertLessEqual(abs(a["residual"]), A.FRAME_TOL)
            self.assertEqual(j["state"], "done")
        self.assert_30fps(p1, 12.0)
        self.assert_30fps(p2, 8.0)
        self.assertCountEqual(asked, [p1, p2])   # 速報版を入れ替えた 2 本だけ、パックの有無を渡された口で聞く(txindex は読まない)
        self.assertEqual((self.arc_of(j1)["packOld"], self.arc_of(j2)["packOld"]), (True, False))
        self.assertIn("作り直してください", self.arc_of(j1)["message"])
        self.assertNotIn("作り直してください", self.arc_of(j2)["message"])
        self.assertNotEqual(os.path.getsize(p1), size1)   # 入れ替わった
        kept = os.path.join(os.path.dirname(p1), schemas.WORK_DIR, A.SPEED_DIR, os.path.basename(p1))
        self.assertEqual(os.path.getsize(kept), size1)    # 速報版は消さずに 作業用\速報版 へ
        self.assertEqual(self.arc_of(j1)["keep"], kept)
        clip = fsio.read_json_file(schemas.find_clip_path(p1), 1 << 20)
        arc = clip["source"]["live"]["archive"]
        self.assertEqual(arc["videoId"], VID)
        self.assertAlmostEqual(arc["start"], 150.047, delta=0.02)
        self.assertEqual(clip["range"], {"start": 10.0, "end": 22.0})   # range は録画の頭からの秒のまま
        self.assertEqual(clip["export"]["from"], "youtube-archive")
        self.assertEqual(studio.calls[0]["volume"], 75)        # 速報版と同じ音量(.clip.json の export)
        self.assertEqual(studio.calls[0]["maxHeight"], 0)      # 180p は選べる高さに無い → 指定なし
        self.assertEqual(studio.calls[0]["videoId"], VID)
        # 2 本目は前のずれの ±20 秒の窓
        w1, w2 = self.arc_of(j1)["window"], self.arc_of(j2)["window"]
        self.assertGreater(w1[1] - w1[0], 300 + 8)                  # 配信で最初の照合は ±300 秒(頭は 0 で切れる)
        self.assertLess(w2[1] - w2[0], 2 * 20 + 8 + 1, w2)         # 2 本目は前のずれの ±20 秒
        self.assertEqual(self.fetches, [VID])                       # 配信の音は 1 回だけ丸ごと取って、3 本で使い回す
        self.assertTrue(wait_for(lambda: not [n for n in os.listdir(self.ex.work) if n.startswith(A.AUDIO_DIR)], 10))   # 済んだら消す
        # 欠けのマーク: 近いマーク(2 本目)のずれで、新しく作る
        a3 = self.arc_of(j3)
        self.assertEqual((a3["state"], j3["state"], j3["needsArchive"]), ("done", "done", False), a3)
        self.assertAlmostEqual(a3["archiveStart"], 260.0, delta=0.03)
        self.assertTrue(j3["path"].startswith(os.path.join(self.out, "配信の題")), j3["path"])
        self.assert_30fps(j3["path"], 6.0)
        c3 = fsio.read_json_file(j3["manifest"], 1 << 20)
        self.assertEqual((c3["source"]["kind"], c3["source"]["live"]["archive"]["videoId"]), ("live", VID))
        self.assertAlmostEqual(c3["range"]["start"], 160.0, delta=0.01)   # recBase からの秒
        # 作りかけのフォルダ・一時ファイルは残らない
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.out, "配信の題", schemas.WORK_DIR, A.BUILD_DIR)), 10))
        self.assertTrue(wait_for(lambda: not (os.path.isdir(self.ex.work) and os.listdir(self.ex.work)), 10))   # 一時ファイル(live\work)も残らない
        # 記録に残る・もう一度押しても何もしない
        saved = fsio.read_json_file(os.path.join(self.store, "exports.json"), 1 << 22)
        self.assertEqual({j["archive"]["state"] for j in saved["jobs"]}, {"done"})
        with self.assertRaises(LX.LiveError) as cm:
            ar.request("local", REC)
        self.assertEqual(cm.exception.code, 409)
        self.assertTrue(ar.info_view("local", REC)["ready"])
        self.assertEqual(afters, [("local", REC)])   # 録画の最後の1本が済んだときに1回(録画を消す Cleaner.check へ)

    def test_residual_retry_and_busy_studio(self):
        j1, p1 = self.speed(150.047, 10.0, 1)
        def late_audio(vid, folder, cancelled=None):   # 取った音の頭が 0.1 秒ずれていた(照合のアーカイブの秒が 0.1 秒早くなる)
            return self.audio(vid, folder, cancelled, late=0.1)
        studio = FakeStudio(self.arc, busy=2)   # 最初の 2 回は 409 busy(ほかの書き出しが動いている)
        ar = self.archiver(studio, audio=late_audio)
        ar.request("local", REC)
        self.assertTrue(self.wait_state(j1))
        a = self.arc_of(j1)
        self.assertEqual(a["state"], "done", a)
        self.assertEqual(len(studio.calls), 2)   # ずれを足して1回だけ作り直した
        self.assertAlmostEqual(studio.calls[1]["start"] - studio.calls[0]["start"], 0.1, delta=0.02)
        self.assertAlmostEqual(a["archiveStart"], 150.047, delta=0.02)
        self.assertLessEqual(abs(a["residual"]), A.FRAME_TOL)
        # 作り直してもずれる(スタジオが 1 回目は 0.1 秒・2 回目は 0.2 秒ずらす = 足しても直らない)→ 入れ替えない
        j2, p2 = self.speed(220.031, 6.0, 2)
        mtime = os.path.getmtime(p2)
        j1["archive"] = dict(j1["archive"], state="done")
        studio2 = FakeStudio(self.arc, shifts=(0.1, 0.2))
        ar2 = self.archiver(studio2)
        ar.close()
        ar2.request("local", REC)
        self.assertTrue(self.wait_state(j2))
        self.assertEqual(self.arc_of(j2)["state"], "error")
        self.assertIn("ずれています", self.arc_of(j2)["message"])
        self.assertEqual(len(studio2.calls), 2)
        self.assertEqual(os.path.getmtime(p2), mtime)
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.out, "配信の題", schemas.WORK_DIR, A.BUILD_DIR)), 10))

    def test_not_ready_and_no_start_time(self):
        j1, p1 = self.speed(150.047, 6.0, 1)
        self.status = "post_live"
        ar = self.archiver()
        with self.assertRaises(LX.LiveError) as cm:
            ar.request("local", REC)
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("処理中", str(cm.exception))
        self.assertIs(ar.info_view("local", REC)["ready"], False)
        self.assertNotIn("archive", j1)   # 待つ(何も入れない)
        self.status, self.release = "was_live", None
        ar.request("local", REC)
        self.assertTrue(self.wait_state(j1))
        self.assertEqual(self.arc_of(j1)["message"], "開始時刻が分からないので照合できません")

    def test_mismatch_and_silence_do_not_replace(self):
        for n, src in ((1, self.other), (2, self.silent)):
            j, p = self.speed(5.0, 8.0, n, src=src)
            j["start"] = LX.epoch_iso(RELEASE + 150 + SKEW)   # 見当はアーカイブの 150 秒
            j["end"] = LX.epoch_iso(RELEASE + 158 + SKEW)
            mtime = os.path.getmtime(p)
            studio = FakeStudio(self.arc)
            ar = self.archiver(studio)
            ar.request("local", REC)
            self.assertTrue(self.wait_state(j))
            a = self.arc_of(j)
            self.assertEqual(a["state"], "error", a)
            self.assertIn("速報版のまま", a["message"]) if n == 1 else self.assertIn("無音", a["message"])
            self.assertEqual(os.path.getmtime(p), mtime)   # 入れ替えない
            self.assertFalse(studio.calls)
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(p), schemas.WORK_DIR, A.SPEED_DIR)))
            if n == 1:   # ±120 → ±600 で1回だけやり直した
                self.assertEqual(len(self.aligns), 2)
            ar.close()

    def test_outside_out_dir_is_refused(self):
        j1, p1 = self.speed(150.047, 6.0, 1)
        other = os.path.join(self.tmp, "elsewhere.mp4")
        shutil.copy(p1, other)
        j1["path"] = other
        ar = self.archiver()
        ar.request("local", REC)
        self.assertTrue(self.wait_state(j1))
        self.assertIn("書き出し先の中ではない", self.arc_of(j1)["message"])
        self.assertTrue(os.path.isfile(other))
        self.assertEqual(A.free_name(self.tmp, "elsewhere.mp4"), os.path.join(self.tmp, "elsewhere_2.mp4"))
        self.assertFalse(A.inside(os.path.join(self.out, "..", "x.mp4"), self.out))
        self.assertEqual(A.probe_archive("bad id!")["status"], "unknown")   # 動画の id は 11 文字の形だけ

    def test_cancel(self):
        j1, p1 = self.speed(150.047, 6.0, 1)
        size = os.path.getsize(p1)
        studio = FakeStudio(self.arc, block=True)
        ar = self.archiver(studio)
        ar.request("local", REC)
        self.assertTrue(wait_for(lambda: studio.calls, 60))
        self.assertEqual(ar.cancel("local", REC), 1)
        self.assertTrue(self.wait_state(j1))
        self.assertEqual(self.arc_of(j1)["state"], "cancelled")
        self.assertEqual(len(studio.cancelled), 1)   # スタジオの書き出しも取り消した
        self.assertEqual(os.path.getsize(p1), size)
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.out, "配信の題", schemas.WORK_DIR, A.BUILD_DIR)), 10))
        # 取り消したあとは、もう一度押せば始められる(自動では始めない)
        self.assertEqual(ar.request("local", REC)["queued"], 1)
        ar.cancel("local", REC)

    def test_in_use_then_later(self):
        j1, p1 = self.speed(150.047, 6.0, 1)
        real = A.fsio.replace_retry
        state = {"n": 0}

        def flaky(src, dst):
            if os.path.normcase(src) == os.path.normcase(p1) and state["n"] < 1:   # 速報版が開かれている
                state["n"] += 1
                raise PermissionError(32, "used")
            return real(src, dst)
        studio = FakeStudio(self.arc)
        ar = self.archiver(studio)
        with mock.patch.object(A.fsio, "replace_retry", flaky):
            ar.request("local", REC)
            self.assertTrue(wait_for(lambda: state["n"] == 1, 120))
            self.assertTrue(wait_for(lambda: self.arc_of(j1).get("state") == "wait" or self.arc_of(j1).get("state") == "done", 30))
            self.assertTrue(self.wait_state(j1))
        a = self.arc_of(j1)
        self.assertEqual(a["state"], "done", a)
        self.assertEqual(len(studio.calls), 1)   # 作った本番版を残しておいて、入れ替えだけやり直した
        self.assert_30fps(p1, 6.0)

    def test_auto(self):
        j1, p1 = self.speed(150.047, 6.0, 1)
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
        j2 = self.job(220.0, 5.0, 2, "error")
        rec2 = "20261005-130000-abcdefghijk"
        j2["recording"] = rec2
        ar2 = self.archiver(recording_state=lambda rc, rec: None, first_delay=0, interval=0, give_up=1)   # 録画元につながらない: ジョブの時刻から
        self.status = "post_live"
        j2["end"] = LX.epoch_iso(time.time() - 5)
        self.assertEqual(ar2.auto_tick(), 0)
        self.assertIn("自動で作り直すのをやめました", ar2.info_view("local", rec2)["message"])
        n = len(self.probes)
        ar2.auto_tick()
        self.assertEqual(len(self.probes), n)
        # 設定でオフなら何もしない
        self.assertEqual(self.archiver(auto=lambda: False).auto_tick(), 0)

    def test_offset_from_other_recording_of_same_stream(self):
        """同じ配信(videoId)の別の録画で照合したずれを、窓の見当に使う(最初から ±20 秒)。欠けのマークの時刻には使わない"""
        other = "20261005-110000-abcdefghijk"
        o = self.job(100.0, 5.0, 9, "done")
        o["recording"] = other
        o["archive"] = {"state": "done", "aligned": True, "offset": round(-SKEW + 1.24, 3)}   # 別の録画(受信時刻が 1.24 秒違う)
        j1, p1 = self.speed(150.047, 8.0, 1)
        ar = self.archiver()
        ar.info[ar.key("local", other)] = {"videoId": VID}
        ar.request("local", REC)
        self.assertTrue(self.wait_state(j1))
        a = self.arc_of(j1)
        self.assertEqual(a["state"], "done", a)
        self.assertLess(a["window"][1] - a["window"][0], 2 * 20 + 8 + 1, a)
        self.assertAlmostEqual(a["archiveStart"], 150.047, delta=0.02)
        self.assertEqual(len(self.aligns), 2)   # 照合 1 回 + 速報版とのずれの確かめ 1 回
        ar.close()
        # 欠けのマーク: 同じ録画に照合できたマークが無ければ、別の録画のずれは使わない
        rec3 = "20261005-140000-abcdefghijk"
        j3 = self.job(260.0, 6.0, 3, "error")
        j3["recording"] = rec3
        ar2 = self.archiver()
        ar2.info[ar2.key("local", other)] = {"videoId": VID}
        self.ex.marks.upsert("local", rec3, "lm-000000000003", 3, LX.epoch_iso(RELEASE), LX.epoch_iso(RELEASE + 1),
                             url="https://www.youtube.com/watch?v=" + VID)
        ar2.request("local", rec3)
        self.assertTrue(self.wait_state(j3))
        self.assertIn("同じ録画に照合できたマークも無い", self.arc_of(j3)["message"])

    def test_restart_continues(self):
        j1, p1 = self.speed(150.047, 6.0, 1)
        j1["archive"] = {"state": "fetch", "label": "取得中", "progress": 0.4, "auto": False}
        self.ex._save()
        ex2 = LX.Exporter(FakeExLive(), self.store, lambda: self.out)   # 入口を起動し直した
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
        # 途中のものがあるマークは書き出し直せない(入れ替える相手を変えない)
        j["archive"] = dict(j["archive"], state="wait")
        self.assertTrue(ex2.busy(REC, j["markId"]))
        self.assertIn("本番版に作り直しています", str(ex2._busy_error(REC, j["markId"])))   # 画面に出す断りの文


@unittest.skipUnless(FF, "ffmpeg が無い")
class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-align-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

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
    → 本番版へ → done。時刻合わせ(_after_offset)・スタジオ・採用(Live.adopt)は偽物(本物の通しは src/home/tests/e2e_live_archive.py の 9)"""
    HOURS = 3.0

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-after-")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        self.ex = LX.Exporter(FakeExLive(), os.path.join(self.tmp, "live"), lambda: self.out, disk_usage=lambda p: (100 * LX.GB, 200 * LX.GB))
        self.first = RELEASE + SKEW   # 録画の頭の受信時刻(アーカイブの秒 s ↔ 絶対時刻 RELEASE + s + SKEW = ずれ offset −SKEW)
        self.rec = {"recorder": "local", "id": REC, "url": "https://www.youtube.com/watch?v=" + VID, "title": "配信の題", "active": False,
                    "endedAt": time.time() - 7200, "firstPdt": self.first, "lastPdt": self.first + self.HOURS * 3600}
        self.status, self.on = "post_live", True
        self.calls, self.queue, self.adopted = [], [], []
        self.analysis = None
        sc = [(1000, 9.0), (110, 8.5), (5000, 8.0), (20000, 7.5), (10750, 7.0), (2000, 6.5), (3000, 6.0), (4000, 5.5), (6000, 5.0), (7000, 4.5), (8000, 4.0)]
        self.marks = [{"id": "a%d" % i, "src": "auto", "status": "", "score": s, "start": float(t), "end": float(t + 60), "label": ""} for i, (t, s) in enumerate(sc)]
        self.marks += [{"id": "x1", "src": "auto", "status": "rejected", "score": 99.0, "start": 500.0, "end": 560.0},   # 人が不採用にした
                       {"id": "x2", "src": "manual", "status": "", "score": 50.0, "start": 600.0, "end": 660.0}]          # 人のマーク
        self.live_marks = [{"id": "h1", "status": "exported", "start": 100.0, "end": 160.0}]   # 録画の配信の人のマーク(録画の秒)
        self.reqs = {}   # (録画元, 録画) -> 友人のライブ配信の依頼(live_requests.Store.get の代わり。2-15)
        self.arcs = []

    def tearDown(self):
        for a in self.arcs:
            a.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

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
        if hold:
            j["holdFor"] = hold
        self.ex.jobs.append(j)
        return {"job": dict(j), "existing": False}

    def archiver(self, **kw):
        a = A.Archiver(self.ex, self.studio, probe=lambda vid: {"status": self.status, "release": RELEASE, "duration": self.HOURS * 3600, "availability": "public"},
                       after_stream=lambda: self.on, per_hour=lambda: 2, recordings=lambda: [self.rec], adopt=self.adopt, first_delay=60, interval=0, poll=0.1,
                       request=lambda rc, rec: self.reqs.get((rc, rec)), **kw)
        a._after_offset = lambda rc, rec, vid, t0, first, last: (-SKEW, "テスト")
        a._queue = lambda js, auto: [j.update(archive={"state": "wait", "auto": auto}) for j in js]   # 本番版への作り直しは動かさない(順番に入れたことだけ)
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
        self.assertEqual(sorted(secs), [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 10750.0])   # 人のマークと重なる 110・録画の外 20000 は飛ばす・10750 は録画の終わりまでに切り詰める
        self.assertEqual({(b["origin"], b["after"], h) for b, h in self.adopted}, {("archive", "auto", "archive")})
        self.assertTrue(all(b["recorder"] == "local" and b["recording"] == REC for b, h in self.adopted))
        # 書き出しが済む → 本番版への作り直しに入れる → 入れ替え・まとめて実行へ渡した → done
        for j in self.ex.jobs:
            j.update(state="done", path=os.path.join(self.out, j["id"] + ".mp4"))
            with open(j["path"], "wb") as f:
                f.write(b"x")
        a.after_tick()
        self.assertTrue(all((j.get("archive") or {}).get("state") == "wait" and j["archive"]["auto"] for j in self.ex.jobs))
        self.assertEqual(a.info_view("local", REC)["afterStream"]["state"], "export")
        for j in self.ex.jobs[:-1]:
            j.update(archive={"state": "done"}, runId="run-" + j["id"])
        last = self.ex.jobs[-1]
        last.update(archive={"state": "error", "message": "合いませんでした"}, handoffWait="archive")   # 本番版にできなかった → 速報版のまま渡す
        a.after_tick()
        self.assertIn("本番版にできなかったので、速報版のまま", last.get("warning") or "")
        self.assertIn("まとめて実行が使えません", last.get("handoffError") or "")   # このテストにまとめて実行は無い = 渡せなかった(失敗の集約に出る)
        st = a.info_view("local", REC)["afterStream"]
        self.assertEqual(st["state"], "done", st)
        self.assertIn("6 本のうち 5 本", st["message"])
        self.assertIn("失敗 1 本", st["message"])
        self.assertEqual(a.after_stream_hold("local", dict(self.rec, endedAt=LX.epoch_iso(self.rec["endedAt"]))), "")   # 済んだので消してよい
        n = len(self.calls)
        self.assertEqual(a.after_tick(), 0)                                    # 済んだ録画はもう触らない
        self.assertEqual(len(self.calls), n)

    def test_taken_from_marks_book(self):
        """G3(RS8 B3-5): 重ねない採用はマークの置き場から(taken。headless のスタジオなしの採用 = 案件の 採用.json か正本)。
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
        """スタジオの LIVE の帯に出す進み具合(入口 0.41.0): GET /live/api/exports の archiveInfo.afterStream の progress と text"""
        a = {"state": "export", "label": A.AFTER_LABELS["export"], "message": "3 本を採用しました", "jobs": ["j1", "j2", "j3", "j4"]}
        jobs = [{"id": "j1", "state": "done", "archive": {"state": "done"}, "runId": "r1", "tx": {"state": "done"}},
                {"id": "j2", "state": "done", "archive": {"state": "done"}, "runId": "r2", "tx": {"state": "running"}},
                {"id": "j3", "state": "error", "failure": {"kind": "export", "text": "書き出せませんでした"}},
                {"id": "other", "state": "done", "runId": "r9", "tx": {"state": "done"}}]   # 人の書き出し(数えない)
        p = A.after_progress(a, jobs)
        self.assertEqual(p, {"total": 4, "exported": 2, "archived": 2, "handed": 2, "finished": 1, "failed": 1})   # j4 は一覧から消えた(total だけ)
        self.assertEqual(A.after_text(a, p), "配信後の自動の切り抜き: 書き出し → 本番版 → パック(4 本のうち 書き出し 2・本番版 2・文字起こし → パックへ 2・パックまで済み 1・失敗 1)")
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
        endedAt が無ければ lastPdt。録画を消すのを待つか(after_stream_hold)も、どちらの形で渡しても古い録画は待たない(2026-10-09。前は ISO だけ見ていた)"""
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

    def test_speed_file_is_probed_once_while_unchanged(self):
        """速報版の ffprobe は、同じ作り直しの中では 1 回(照合・高さ・ずれの確かめで使い回す)。ファイルが変われば調べ直す・終われば忘れる"""
        a = self.archiver()
        speed = os.path.join(self.out, "速報版.mp4")
        with open(speed, "wb") as f:
            f.write(b"x")
        calls = []

        def probe(p, ffprobe=None):
            calls.append(p)
            return {"duration": 12.0, "height": 1080}
        with mock.patch.object(A.normalize, "probe", probe):
            self.assertEqual((a._probe_speed(speed)["height"], a._probe_speed(speed)["duration"]), (1080, 12.0))
            self.assertEqual(len(calls), 1)
            with open(speed, "wb") as f:
                f.write(b"xy")   # 入れ替えた(大きさが変わった)
            a._probe_speed(speed)
            self.assertEqual(len(calls), 2)
            a._probes.clear()
            a._probe_speed(speed)
            self.assertEqual(len(calls), 3)
            self.assertEqual(a._probe_speed(os.path.join(self.out, "無い.mp4")), {})   # 無いファイルは調べない

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
        """2-15: 依頼の afterStream が偽の録画では M7 を動かさない(ホームの M7 がオフでもオンでも。録画を消すのも待たない)。依頼の無い録画は今までどおり"""
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
        self.assertIs(a.request.__func__, A.Archiver.request)   # 引数 request(依頼の結びつき)が「作り直しを頼む」メソッド(POST /live/api/archive)を上書きしない
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
        self.tmp = tempfile.mkdtemp(prefix="ytt-live-ytdlp-")
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

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
