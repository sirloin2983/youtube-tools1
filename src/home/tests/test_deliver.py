"""パックを友人へ届ける(src/home/deliver.py・入口の api/ytt/deliver)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest src/home/tests/test_deliver.py -v
"""
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import deliver  # noqa: E402


def put(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def wait(dl, job, limit=10):
    end = time.time() + limit
    while time.time() < end:
        j = dl.status(job["id"])
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("終わらない: %r" % dl.status(job["id"]))


class ZipPackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"), b"v" * 1000)
        put(os.path.join(self.pack, "sub", "textplus-import.json"), b"{}")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)

    def test_zip_has_top_folder_and_no_temp_left(self):
        dest = deliver.zip_pack(self.pack, self.out, "20261004-120000-abcdef__題名")
        self.assertEqual(os.path.basename(dest), "20261004-120000-abcdef__題名.zip")
        with zipfile.ZipFile(dest) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
            self.assertEqual(names, ["clip_pack/clip.mp4", "clip_pack/sub/textplus-import.json"])
            self.assertEqual(z.getinfo([n for n in z.namelist() if n.endswith(".mp4")][0]).compress_type, zipfile.ZIP_STORED)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])

    def test_same_name_does_not_overwrite(self):
        a = deliver.zip_pack(self.pack, self.out, "n")
        b = deliver.zip_pack(self.pack, self.out, "n")
        self.assertNotEqual(a, b)
        self.assertEqual(len(os.listdir(self.out)), 2)

    def test_check_stops_and_cleans_temp(self):
        class Stop(Exception):
            pass

        def check():
            raise Stop()
        with self.assertRaises(Stop):
            deliver.zip_pack(self.pack, self.out, "n", check=check)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])
        self.assertEqual(os.listdir(self.out), [])

    def test_request_id_matches_friend_app(self):
        # friend-apps/request-sender/src/Core.cs の NameRx と同じ形(アプリが先頭の id を除いて題名を出す)
        self.assertRegex(deliver.request_id(), r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class ZipPacksTest(unittest.TestCase):
    """n 本をまとめる zip(① 全自動の n 本ごとの届け方)とパックの中の動画の見つけ方"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a = os.path.join(self.tmp, "配信 A_pack")
        self.b = os.path.join(self.tmp, "配信 B_pack")
        put(os.path.join(self.a, "配信 A.mp4"), b"a" * 500)
        put(os.path.join(self.a, "配信 A_roughcut.mp4"), b"r" * 900)
        put(os.path.join(self.a, "cut-plan.json"), b"{}")
        put(os.path.join(self.b, "配信 B.mp4"), b"b" * 300)
        put(os.path.join(self.b, "sub", "x.txt"), b"x")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)

    def test_layout_and_extra_and_dest(self):
        preview = os.path.join(self.tmp, "p.mp4")
        put(preview, b"PV")
        dest = deliver.unique_zip(self.out, "rid__題 1-2")
        self.assertEqual(deliver.preview_path_for(dest), os.path.join(self.out, "rid__題 1-2.preview.mp4"))
        got = deliver.zip_packs([self.a, self.b], self.out, "rid__題 1-2", extra=[(preview, deliver.PREVIEW_NAME)], dest=dest)
        self.assertEqual(got, dest)
        with zipfile.ZipFile(got) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
        self.assertEqual(names, sorted([deliver.PREVIEW_NAME, "配信 A_pack/cut-plan.json", "配信 A_pack/配信 A.mp4", "配信 A_pack/配信 A_roughcut.mp4",
                                        "配信 B_pack/sub/x.txt", "配信 B_pack/配信 B.mp4"]))
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])

    def test_pack_video_and_title(self):
        self.assertEqual(deliver.pack_video(self.a), os.path.join(self.a, "配信 A.mp4"))   # いちばん大きくても _roughcut は選ばない
        self.assertEqual(deliver.pack_video(self.b), os.path.join(self.b, "配信 B.mp4"))
        self.assertIsNone(deliver.pack_video(os.path.join(self.tmp, "無い")))
        self.assertEqual(deliver.pack_title(self.a), "配信 A")
        self.assertEqual(deliver.pack_title(os.path.join(self.tmp, "そのまま")), "そのまま")
        self.assertEqual(deliver._atempo(2.0), "atempo=2")
        self.assertEqual(deliver._atempo(3.0), "atempo=2.0,atempo=1.5")

    def test_names_and_place_preview(self):
        """名前 <依頼 id>__<題>(使えない文字は _)・まとめ動画を zip の隣に写す(元は zip に入れるので残す)・動画の無いパックがあれば作らない"""
        self.assertEqual(deliver.delivery_name("rid", "題/1:2"), "rid__題_1_2")
        preview = os.path.join(self.tmp, "p.mp4")
        put(preview, b"PV")
        os.makedirs(self.out)
        placed = deliver.place_preview(preview, deliver.unique_zip(self.out, "rid__題 1-2"))
        self.assertEqual(placed, os.path.join(self.out, "rid__題 1-2.preview.mp4"))
        with open(placed, "rb") as f:
            self.assertEqual(f.read(), b"PV")
        self.assertTrue(os.path.isfile(preview))
        empty = os.path.join(self.tmp, "空_pack")
        os.makedirs(empty)
        self.assertIsNone(deliver.batch_preview([self.a, empty]))   # ffmpeg を呼ばない
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])


class PreviewArgsTest(unittest.TestCase):
    """まとめ動画の ffmpeg の引数(ffmpeg は要らない): 等速なら setpts/atempo を入れない・札はずっと(2026-10-08 ユーザー決定)"""

    def test_normal_speed_and_label_always(self):
        self.assertEqual((deliver.PREVIEW_SPEED, deliver.PREVIEW_LABEL_SEC), (1.0, 0))
        args = deliver._preview_args("ffmpeg", ["a.mp4", "b.mp4"], "out.mp4", 1.0, 480, True, label_files=["l1.txt", "l2.txt"], font="C:/Windows/Fonts/meiryo.ttc")
        fc = args[args.index("-filter_complex") + 1]
        self.assertNotIn("setpts", fc)
        self.assertNotIn("atempo", fc)
        self.assertIn("[0:a]anull[a0]", fc)
        self.assertIn("drawtext=", fc)
        self.assertNotIn("enable=", fc, "札はずっと出す")
        self.assertIn("concat=n=2:v=1:a=1[v][a]", fc)

    def test_fast_when_asked(self):
        args = deliver._preview_args("ffmpeg", ["a.mp4"], "out.mp4", 2.0, 480, True)
        fc = args[args.index("-filter_complex") + 1]
        self.assertIn("setpts=PTS/2", fc)
        self.assertIn("atempo=", fc)
        self.assertNotIn("drawtext", fc)


class PreviewTest(unittest.TestCase):
    """まとめ動画(ffmpeg が要る。無ければ skip)"""

    def setUp(self):
        from ytt_core import tools
        self.ffmpeg, self.ffprobe = tools.find_tool("ffmpeg"), tools.find_tool("ffprobe")   # 本物(ほかのテストが環境変数で偽物に向けていても)
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg が無い")
        self.tmp = tempfile.mkdtemp(prefix="ytt-preview-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = []

    def clip(self, rel, sec, audio=True):
        import subprocess
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        args = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=%d" % sec]
        if audio:
            args += ["-f", "lavfi", "-i", "sine=f=440:d=%d" % sec, "-c:a", "aac"]
        else:
            args += ["-an"]
        subprocess.run(args + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", p], check=True, timeout=60)
        return p

    def test_two_clips_at_normal_speed_and_double_when_asked(self):
        from ytt_core import normalize
        a, b = self.clip("一本目_pack/一本目.mp4", 2), self.clip("二本目_pack/二本目.mp4", 2)
        out = os.path.join(self.tmp, "preview.mp4")
        self.assertTrue(deliver.make_preview([a, b], out, ["一本目", "二本目"], ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        info = normalize.probe(out, ffprobe=self.ffprobe)
        self.assertEqual((info["height"], info["has_audio"]), (480, True))
        self.assertAlmostEqual(info["duration"], 4.0, delta=0.5)   # 等速: 2 秒 × 2 本 = 4 秒(2026-10-08 ユーザー決定)
        self.assertEqual(self.logs, [])
        fast = os.path.join(self.tmp, "fast.mp4")
        self.assertTrue(deliver.make_preview([a, b], fast, speed=2.0, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        self.assertAlmostEqual(normalize.probe(fast, ffprobe=self.ffprobe)["duration"], 2.0, delta=0.5)   # 定数を変えれば速くもできる

    def test_silent_clip_makes_a_silent_preview(self):
        from ytt_core import normalize
        a, b = self.clip("a_pack/a.mp4", 1), self.clip("b_pack/b.mp4", 1, audio=False)
        out = os.path.join(self.tmp, "preview.mp4")
        self.assertTrue(deliver.make_preview([a, b], out, ["A", "B"], ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        self.assertFalse(normalize.probe(out, ffprobe=self.ffprobe)["has_audio"])

    def test_broken_input_fails_quietly(self):
        bad = os.path.join(self.tmp, "x_pack", "x.mp4")
        put(bad, os.urandom(3000))   # 文字だけのファイルは ffmpeg が「文字の動画」として読めてしまうので、でたらめなバイト列で
        self.assertFalse(deliver.make_preview([bad], os.path.join(self.tmp, "p.mp4"), ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append))
        self.assertTrue(self.logs and "まとめ動画を作れませんでした" in self.logs[-1], self.logs)
        self.assertFalse(deliver.make_preview([], os.path.join(self.tmp, "p.mp4")))


class DeliveriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"))
        self.folder = os.path.join(self.tmp, "Dropbox")
        os.makedirs(self.folder)
        self.cfg = {"folder": self.folder}
        self.packs = {os.path.normpath(self.pack)}
        self.logs = []
        self.dl = deliver.Deliveries(lambda: self.cfg["folder"], lambda d: os.path.normpath(d) in self.packs, log=self.logs.append)

    def test_start_and_done(self):
        j = wait(self.dl, self.dl.start(self.pack, "【雑談】校正済み/1"))
        self.assertEqual(j["state"], "done")
        self.assertRegex(j["name"], r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}__【雑談】校正済み_1\.zip$")
        self.assertEqual(os.listdir(os.path.join(self.folder, deliver.OUT_DIR)), [j["name"]])
        self.assertTrue(self.logs)

    def test_title_falls_back_to_folder_name(self):
        j = wait(self.dl, self.dl.start(self.pack, ""))
        self.assertTrue(re.search(r"__clip\.zip$", j["name"]), j["name"])

    def test_refuses_non_pack_folder(self):
        other = os.path.join(self.tmp, "secret")
        put(os.path.join(other, "a.txt"))
        for d in (other, "", None, 3, "x" * 2000):
            with self.assertRaises(ValueError):
                self.dl.start(d, "t")
        self.assertFalse(os.path.exists(os.path.join(self.folder, deliver.OUT_DIR)))

    def test_refuses_without_intake_folder(self):
        self.cfg["folder"] = ""
        with self.assertRaisesRegex(ValueError, "決まっていません"):
            self.dl.start(self.pack, "t")
        self.cfg["folder"] = os.path.join(self.tmp, "nope")
        with self.assertRaisesRegex(ValueError, "見つかりません"):
            self.dl.start(self.pack, "t")

    def test_status_unknown(self):
        self.assertIsNone(self.dl.status("nope"))
        self.assertIsNone(self.dl.status(None))

    def test_error_is_reported(self):
        orig = deliver.zip_pack

        def boom(*a, **k):
            raise OSError(28, "No space left on device")
        deliver.zip_pack = boom
        self.addCleanup(setattr, deliver, "zip_pack", orig)
        j = wait(self.dl, self.dl.start(self.pack, "t"))
        self.assertEqual(j["state"], "error")
        self.assertIn("No space left", j["message"])


class ApiTest(unittest.TestCase):
    """入口の ytt_api("deliver") の受け渡し(HTTP の検査は test_window の api/ytt と同じ ytt_request)"""

    def test_api(self):
        import launch
        tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, tmp, True)
        pack = os.path.join(tmp, "p_pack")
        put(os.path.join(pack, "a.mp4"))
        os.makedirs(os.path.join(tmp, "Dropbox"))

        class Fake:
            ytt_api = launch.PortalServer.ytt_api
        srv = Fake()
        srv.deliveries = deliver.Deliveries(lambda: os.path.join(tmp, "Dropbox"), lambda d: d == os.path.normpath(pack))
        code, obj = srv.ytt_api("deliver", {"op": "start", "dir": os.path.join(tmp, "nope"), "title": "t"})
        self.assertEqual(code, 400)
        code, obj = srv.ytt_api("deliver", {"op": "start", "dir": pack, "title": "t"})
        self.assertEqual(code, 200)
        j = wait(srv.deliveries, obj["job"])
        self.assertEqual(j["state"], "done")
        code, obj = srv.ytt_api("deliver", {"op": "status", "job": j["id"]})
        self.assertEqual((code, obj["job"]["state"]), (200, "done"))
        code, _ = srv.ytt_api("deliver", {"op": "status", "job": "nope"})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
