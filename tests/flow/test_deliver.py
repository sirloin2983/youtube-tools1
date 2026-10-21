"""パックを友人へ届ける(src/flow/deliver.py・入口の api/ytt/deliver)のテスト。正しく動く道は本物の ffmpeg の通し(DeliverRun)で、
見本のパック(声のある切り抜き・音の無い切り抜き・壊れた動画・動画の無いパック・粗編集・1980 年より前のファイル)をまとめて届けて確かめる。
ほかのクラスは通しでは起こせない物だけ(途中の失敗・中止・時間切れ・書けない中身・焼き込みの有無)。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest tests/flow/test_deliver.py -v
(入口の ytt_api の受け渡しは tests/app/test_deliver_api.py)
"""
import json
import os
import subprocess
import sys
import time
import types
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import deliver  # noqa: E402
from pipeline.pack import preview as pv  # noqa: E402


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def fake_preview(case):
    """ffmpeg を呼ばない(確認用の動画は偽物・長さは分からない)。途中の失敗を差し込むテスト用"""
    def fake_make_preview(video, out_path, **_kw):
        put(out_path, b"PV")
        return True
    for name, fake in (("make_preview", fake_make_preview), ("pack_seconds", lambda d, ffprobe=None: None)):
        p = mock.patch.object(pv, name, fake)
        p.start()
        case.addCleanup(p.stop)


def wait(dl, job, limit=30):
    end = time.time() + limit
    while time.time() < end:
        j = dl.status(job["id"])
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("終わらない: %r" % dl.status(job["id"]))


def temps(d):
    return [n for n in os.listdir(d) if n.startswith(".deliver-")]


class DeliverRun(unittest.TestCase):
    """届けるの通し(本物の ffmpeg・ffprobe。無ければ飛ばす)"""

    @classmethod
    def setUpClass(cls):
        from ytt import tools
        cls.ffmpeg, cls.ffprobe = tools.find_tool("ffmpeg"), tools.find_tool("ffprobe")   # 本物(ほかのテストが環境変数で偽物に向けていても)
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("ffmpeg が無い")

    def clip(self, rel, sec, audio=True):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        args = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=%d" % sec]
        args += ["-f", "lavfi", "-i", "sine=f=440:d=%d" % sec, "-c:a", "aac"] if audio else ["-an"]
        subprocess.run(args + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", p], check=True, timeout=60)
        return p

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliver-")
        self.pack = os.path.join(self.tmp, "一本目_pack")
        self.video = self.clip("一本目_pack/一本目.mp4", 2)
        put(os.path.join(self.pack, "一本目_roughcut.mp4"), b"r" * (os.path.getsize(self.video) + 1000))   # いちばん大きくても粗編集は選ばない
        put(os.path.join(self.pack, "cut-plan.json"), b"{}")
        put(os.path.join(self.pack, "sub", "x.txt"), b"x")
        old = os.path.join(self.pack, "old.txt")
        put(old, b"old")
        os.utime(old, (315000000, 315000000))                    # 1979 年(zip にできる = 届けている途中のまま残らない。9c-2)
        self.silent = os.path.dirname(self.clip("b_pack/b.mp4", 1, audio=False))
        self.broken = os.path.join(self.tmp, "x_pack")
        put(os.path.join(self.broken, "x.mp4"), os.urandom(3000))   # 文字だけのファイルは ffmpeg が「文字の動画」として読めるので、でたらめなバイト列
        self.empty = os.path.join(self.tmp, "空_pack")
        put(os.path.join(self.empty, "cut-plan.json"), b"{}")
        self.folder = os.path.join(self.tmp, "Dropbox")
        os.makedirs(self.folder)
        self.out = os.path.join(self.folder, deliver.OUT_DIR)
        self.log_dir = os.path.join(self.tmp, "logs")
        self.logs = []

    def meta(self, zip_path):
        with open(deliver.meta_path_for(zip_path), "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))                   # UTF-8・BOM なし・1 行・日本語はそのまま
        self.assertNotIn(b"\n", raw.rstrip(b"\r\n"))
        self.assertNotIn(b"\\u", raw)
        return json.loads(raw.decode("utf-8"))

    def test_deliver_run(self):
        from flow import board as B
        from human.friend import friend_feedback
        from ytt import normalize
        cfg = {"folder": self.folder}
        packs = {os.path.normpath(p) for p in (self.pack, self.silent, self.broken, self.empty)}
        dl = deliver.Deliveries(lambda: cfg["folder"], lambda d: os.path.normpath(d) in packs, log=self.logs.append, log_dir=self.log_dir)
        board = B.Board()
        dl.attach_board(board)

        # 手で届ける(全自動と同じ 1 本ずつ): 確認用の動画 → 出どころの印 → zip の順に置く(zip が見えたら印も動画もそろっている = 友人のアプリの約束)
        events, real_zip, real_meta = [], deliver.zip_packs, deliver.write_meta_json

        def write_meta_json(path, doc):
            events.append(("meta", sorted(os.listdir(self.out))))
            return real_meta(path, doc)

        def zip_packs(*a, **k):
            events.append(("zip", sorted(os.listdir(self.out))))
            return real_zip(*a, **k)
        clip = os.path.join(self.tmp, "clip.mp4")
        with mock.patch.object(deliver, "zip_packs", zip_packs), mock.patch.object(deliver, "write_meta_json", write_meta_json):
            j = wait(dl, dl.start(self.pack, "【雑談】校正済み/1", clip={"path": clip, "markId": "m1", "videoId": "abcdefghijk"}))
        self.assertEqual(j["state"], "done", j)
        self.assertRegex(j["name"], r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}__【雑談】校正済み_1\.zip$")   # 依頼 id(友人のアプリと同じ形)__題(使えない文字は _)
        stem = j["name"][:-4]
        self.assertEqual(events, [("meta", [stem + ".preview.mp4"]), ("zip", sorted([stem + ".meta.json", stem + ".preview.mp4"]))])
        self.assertEqual(sorted(os.listdir(self.out)), sorted([j["name"], stem + deliver.PREVIEW_SUFFIX, stem + deliver.META_SUFFIX]))
        self.assertEqual(temps(self.tmp), [], "一時の確認用の動画・zip は消す")
        info = normalize.probe(os.path.join(self.out, stem + deliver.PREVIEW_SUFFIX), ffprobe=self.ffprobe)
        self.assertEqual((info["height"], info["has_audio"]), (480, True))     # 480p・音あり
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.5)                # 等速
        doc = self.meta(os.path.join(self.out, j["name"]))
        self.assertRegex(doc.pop("sentAt"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertAlmostEqual(doc.pop("seconds"), 2.0, delta=0.1)              # 切り抜きの長さ(本物の ffprobe)
        self.assertEqual(doc, {"v": 1, "kind": "clip", "origin": "auto", "requestId": stem.split("__")[0], "zip": j["name"],   # 手で届ける = 依頼なし(auto)
                               "preview": stem + ".preview.mp4", "title": "一本目", "videoId": "abcdefghijk", "markId": "m1",
                               "streamTitle": "", "streamer": ""})
        with zipfile.ZipFile(os.path.join(self.out, j["name"])) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
            stored = {n.replace("\\", "/"): z.getinfo(n).compress_type for n in z.namelist()}
        self.assertEqual(names, ["一本目_pack/cut-plan.json", "一本目_pack/old.txt", "一本目_pack/sub/x.txt", "一本目_pack/一本目.mp4",
                                 "一本目_pack/一本目_roughcut.mp4"])
        self.assertEqual((stored["一本目_pack/一本目.mp4"], stored["一本目_pack/cut-plan.json"]), (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED))   # 動画は圧縮しない
        row = friend_feedback.find_delivery(self.log_dir, j["name"])          # 届けた記録(友人の「要らない」が引く。Q16)
        self.assertEqual((row["requestId"], row["videoId"], row["title"], row["origin"]), (stem.split("__")[0], "abcdefghijk", "【雑談】校正済み/1", "manual"))
        self.assertEqual(row["packs"], [{"dir": os.path.normpath(self.pack), "path": clip, "markId": "m1"}])
        board.refresh()
        got = board.get("dl:" + j["id"])
        self.assertEqual((got["kind"], got["state"], got["target"]["path"], got["finishedAt"] is not None), ("deliver", "done", os.path.normpath(self.pack), True))
        self.assertTrue(self.logs)
        j2 = wait(dl, dl.start(self.pack, ""))                                 # 切り抜きが分からなければパックだけ・題が空ならフォルダ名
        self.assertRegex(j2["name"], r"__一本目\.zip$")
        self.assertEqual(friend_feedback.find_delivery(self.log_dir, j2["name"])["packs"], [{"dir": os.path.normpath(self.pack), "path": "", "markId": ""}])
        self.assertIsNone(dl.status("nope"))
        self.assertIsNone(dl.status(None))

        # 全自動・依頼の 1 本ずつ(deliver_one): 同じ名前でもう一度届けたら末尾に 4 文字(zip・確認用の動画・印は同じ名前)
        run = types.SimpleNamespace(request_id="rid", id="run1", video_id="abcdefghijk", title="題")
        first = deliver.deliver_one(self.pack, self.out, "rid__題", log_dir=self.log_dir, run=run, origin="auto",
                                    marks={self.pack: {"path": "x.mp4", "markId": "m7"}})
        second = deliver.deliver_one(self.pack, self.out, "rid__題", origin="request")
        self.assertEqual(os.path.basename(first), "rid__題.zip")
        self.assertRegex(os.path.basename(second), r"^rid__題-[0-9a-f]{4}\.zip$")
        s2 = os.path.basename(second)[:-4]
        for n in ("rid__題.zip", "rid__題.preview.mp4", "rid__題.meta.json", s2 + ".zip", s2 + ".preview.mp4", s2 + ".meta.json"):
            self.assertIn(n, os.listdir(self.out))
        self.assertEqual((self.meta(second)["zip"], self.meta(second)["origin"]), (s2 + ".zip", "request"))
        doc = self.meta(first)
        self.assertEqual((doc["origin"], doc["markId"], doc["streamTitle"], doc["videoId"]), ("auto", "m7", "題", "abcdefghijk"))
        from flow import deliveries
        last = deliveries.rows(self.log_dir)[-1]
        self.assertEqual((last["origin"], last["zip"]), ("auto", "rid__題.zip"))
        # 届けた記録の読み口(片付けが引く): 依頼 id
        self.assertGreater(deliveries.delivered_requests(self.log_dir)["rid"], 0)
        # 音の無い切り抜き → 音の無い確認用の動画。出どころを渡さなければ依頼(request)
        dest = deliver.deliver_one(self.silent, self.out, "rid__無音", origin=None)
        self.assertFalse(normalize.probe(deliver.preview_path_for(dest), ffprobe=self.ffprobe)["has_audio"])
        self.assertEqual(self.meta(dest)["origin"], "request")
        # 壊れた動画・動画の無いパック: 確認用の動画なし・長さは分からない(None)で、zip と印は届ける。動画の無いパックは ffmpeg を呼ばない
        for d in (self.broken, self.empty):
            self.logs.clear()
            dest = deliver.deliver_one(d, self.out, "rid__" + os.path.basename(d), log=self.logs.append)
            doc = self.meta(dest)
            self.assertEqual((doc["preview"], doc["seconds"]), (None, None), d)
            self.assertFalse(os.path.exists(deliver.preview_path_for(dest)))
            self.assertEqual(bool(self.logs and "確認用の動画を作れませんでした" in self.logs[-1]), d == self.broken, self.logs)
        self.assertEqual((pv.pack_video(os.path.join(self.tmp, "無い")), pv.pack_title(os.path.join(self.tmp, "そのまま"))), (None, "そのまま"))
        self.assertEqual(temps(self.tmp), [])

        # 記録のフォルダを渡さなければ記録しない・断る形(パックでないフォルダ・受付のフォルダが無い)
        n_rows = len(deliveries.rows(self.log_dir))
        dl2 = deliver.Deliveries(lambda: cfg["folder"], lambda d: os.path.normpath(d) in packs)
        self.assertEqual(wait(dl2, dl2.start(self.pack, "t"))["state"], "done")
        self.assertEqual(len(deliveries.rows(self.log_dir)), n_rows)
        other = os.path.join(self.tmp, "secret")
        put(os.path.join(other, "a.txt"))
        before = sorted(os.listdir(self.out))
        for d in (other, "", None, 3, "x" * 2000):
            with self.assertRaises(ValueError):
                dl.start(d, "t")
        cfg["folder"] = ""
        with self.assertRaisesRegex(ValueError, "決まっていません"):
            dl.start(self.pack, "t")
        cfg["folder"] = os.path.join(self.tmp, "nope")
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            dl.start(self.pack, "t")
        self.assertEqual(sorted(os.listdir(self.out)), before)


class FailureTest(unittest.TestCase):
    """途中の失敗・中止(差し込む)。確認用の動画は偽物"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliver-")
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"), b"v" * 1000)
        self.folder = os.path.join(self.tmp, "Dropbox")
        os.makedirs(self.folder)
        self.out = os.path.join(self.folder, deliver.OUT_DIR)
        self.log_dir = os.path.join(self.tmp, "logs")
        fake_preview(self)

    def test_check_stops_and_cleans_temp(self):
        class Stop(Exception):
            pass

        def check():
            raise Stop()
        with self.assertRaises(Stop):
            deliver.zip_packs([self.pack], self.out, "n", check=check)
        self.assertEqual(temps(self.tmp), [])
        self.assertEqual(os.listdir(self.out), [])

    def test_failure_removes_meta_and_preview(self):
        with mock.patch.object(deliver, "zip_packs", side_effect=OSError(28, "no space")):
            with self.assertRaises(OSError):
                deliver.deliver_one(self.pack, self.out, "rid__題", origin="auto")
        self.assertEqual(os.listdir(self.out), [], "書きかけの印・確認用の動画を残さない")
        self.assertEqual(temps(self.tmp), [], "一時の確認用の動画も消す")

    def test_errors_are_reported_and_not_left_running(self):
        """置けない(OSError)・zip にできない(ValueError など)は error にする: 掲示板にも載る・記録しない・同じパックをもう一度届けられる(9c-2)"""
        from flow import board as B
        dl = deliver.Deliveries(lambda: self.folder, lambda d: os.path.normpath(d) == os.path.normpath(self.pack), log_dir=self.log_dir)
        b = B.Board()
        dl.attach_board(b)
        with mock.patch.object(deliver, "zip_packs", mock.Mock(side_effect=OSError(28, "No space left on device"))):
            j = wait(dl, dl.start(self.pack, "t"))
        self.assertEqual(j["state"], "error")
        self.assertIn("No space left", j["message"])
        b.refresh()
        got = b.get("dl:" + j["id"])
        self.assertEqual(got["state"], "error")
        self.assertIn("No space left", got["error"]["text"])
        self.assertFalse(os.path.exists(self.log_dir), "置けなければ記録しない")
        with mock.patch.object(deliver, "zip_packs", mock.Mock(side_effect=ValueError("ZIP does not support timestamps before 1980"))):
            j = wait(dl, dl.start(self.pack, "t"))
        self.assertEqual(j["state"], "error")
        self.assertIn("ValueError", j["message"])
        self.assertFalse(dl.running(self.pack))
        self.assertEqual(wait(dl, dl.start(self.pack, "t"))["state"], "done")

    def test_meta_that_cannot_be_written_leaves_nothing(self):
        out = os.path.join(self.tmp, "出力")
        os.makedirs(out)
        with self.assertRaises(UnicodeError):
            deliver.write_meta_json(os.path.join(out, "x.meta.json"), {"t": "bad\ud800"})
        self.assertEqual(os.listdir(out), [], "書きかけを残さない")


class PreviewTest(unittest.TestCase):
    """確認用の動画の、出来た動画からは読めない決まりと、中止・時間切れ"""

    def test_no_labels_and_normal_speed(self):
        """札・字幕は焼かない・等速(焼き込みの有無は出来た動画から読めないので引数で見る)。音は 96k の aac か無し"""
        for audio in (True, False):
            args = pv._preview_args("ffmpeg", "in.mp4", "out.mp4", 480, audio)
            self.assertFalse(any("drawtext" in a or "setpts" in a or "atempo" in a for a in args), args)
            self.assertNotIn("-filter_complex", args)
            self.assertEqual("-an" in args, not audio)
        self.assertEqual(args[-1], "out.mp4")
        args = pv._preview_args("ffmpeg", "in.mp4", "out.mp4", 480, True)
        self.assertEqual(args[args.index("-b:a") + 1], "96k")

    def test_seconds_unknown_or_zero(self):
        """ffprobe が長さ 0・長さなしを返す動画(見本では作れない)は None"""
        tmp = testkit.tempdir(self, "ytt-deliver-")
        put(os.path.join(tmp, "a_pack", "a.mp4"), b"a")
        for dur in (0, None, -1, True):
            with mock.patch.object(pv.normalize, "probe", return_value={"duration": dur}):
                self.assertIsNone(pv.pack_seconds(os.path.join(tmp, "a_pack")), dur)

    def test_run_ffmpeg_stops_on_check_and_timeout(self):
        """確認用の動画の ffmpeg: check() が例外を投げたら止めて投げ直す・時間切れは (1, "timeout")・普通に終われば (0, 標準エラーの末尾)"""
        from ytt import tools
        ffmpeg = tools.find_tool("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg が無い")
        tmp = testkit.tempdir(self, "ytt-preview-")
        slow = [ffmpeg, "-hide_banner", "-nostdin", "-re", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=30", "-f", "null", "-"]

        class Stop(Exception):
            pass
        calls = []

        def check():
            calls.append(1)
            if len(calls) >= 2:
                raise Stop()
        t0 = time.time()
        with self.assertRaises(Stop):
            pv._run_ffmpeg(slow, 60, check)
        self.assertEqual(pv._run_ffmpeg(slow, 1, None), (1, "timeout"))
        self.assertLess(time.time() - t0, 15)
        code, err = pv._run_ffmpeg([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", os.path.join(tmp, "無い.mp4"), "-f", "null", "-"], 30, None)
        self.assertNotEqual(code, 0)
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
