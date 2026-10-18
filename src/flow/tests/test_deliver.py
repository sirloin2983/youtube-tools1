"""パックを友人へ届ける(src/human/friend/deliver.py・入口の api/ytt/deliver)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest src/human/friend/tests/test_deliver.py -v
(入口の ytt_api の受け渡しは src/app/tests/test_deliver_api.py)
"""
import json
import os
import re
import sys
import time
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ytt import testkit  # noqa: E402
from flow import deliver  # noqa: E402
from pipeline.pack import preview as pv  # noqa: E402  (まとめ動画は ① へ分けた。ds1)


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
        self.tmp = testkit.tempdir(self, "ytt-deliver-")
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"), b"v" * 1000)
        put(os.path.join(self.pack, "sub", "textplus-import.json"), b"{}")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)

    def test_zip_has_top_folder_and_no_temp_left(self):
        dest = deliver.zip_packs([self.pack], self.out, "20261004-120000-abcdef__題名")
        self.assertEqual(os.path.basename(dest), "20261004-120000-abcdef__題名.zip")
        with zipfile.ZipFile(dest) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
            self.assertEqual(names, ["clip_pack/clip.mp4", "clip_pack/sub/textplus-import.json"])
            self.assertEqual(z.getinfo([n for n in z.namelist() if n.endswith(".mp4")][0]).compress_type, zipfile.ZIP_STORED)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])

    def test_same_name_does_not_overwrite(self):
        a = deliver.zip_packs([self.pack], self.out, "n")
        b = deliver.zip_packs([self.pack], self.out, "n")
        self.assertNotEqual(a, b)
        self.assertEqual(len(os.listdir(self.out)), 2)

    def test_check_stops_and_cleans_temp(self):
        class Stop(Exception):
            pass

        def check():
            raise Stop()
        with self.assertRaises(Stop):
            deliver.zip_packs([self.pack], self.out, "n", check=check)
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])
        self.assertEqual(os.listdir(self.out), [])

    def test_file_older_than_1980_is_zipped(self):
        """更新時刻が 1980 年より前のファイルも zip にできる(前は ValueError で手で届ける仕事が「届けている途中」のまま残った。9c-2)"""
        old = os.path.join(self.pack, "old.txt")
        put(old, b"old")
        os.utime(old, (315000000, 315000000))   # 1979 年
        dest = deliver.zip_packs([self.pack], self.out, "n")
        with zipfile.ZipFile(dest) as z:
            self.assertIn("clip_pack/old.txt", [n.replace("\\", "/") for n in z.namelist()])

    def test_request_id_matches_friend_app(self):
        # 前のアプリ(消した request-sender)の Core.cs の NameRx と同じ形(アプリが先頭の id を除いて題名を出す)
        self.assertRegex(deliver.request_id(), r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def fake_make_preview(video, out_path, **_kw):
    """ffmpeg の代わり(中身は見ない。名前と置く順だけ確かめる)。PreviewTest は本物の ffmpeg で確かめる"""
    put(out_path, b"PV")
    return True


class OriginTest(unittest.TestCase):
    """F3-6: 1 本ずつの届け方。確認用の動画 → meta → zip の順に置く。依頼でも自動でも meta を必ず置く。届けた記録に origin・endedAt"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliver-")
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"), b"v")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)
        self.logs = os.path.join(self.tmp, "logs")
        for name, fake in (("make_preview", fake_make_preview), ("pack_seconds", lambda d, ffprobe=None: None)):
            p = mock.patch.object(pv, name, fake)
            p.start()
            self.addCleanup(p.stop)

    def run_(self, rid="rid"):
        import types
        return types.SimpleNamespace(request_id=rid, id="run1", video_id="abcdefghijk", title="題")

    def test_face_origin(self):
        self.assertEqual([deliver.face_origin(o) for o in ("request", None, "", "auto", "manual")], ["request"] * 3 + ["auto"] * 2)
        self.assertEqual(deliver.META_SUFFIX, ".meta.json")

    def test_auto_one_places_preview_then_meta_then_zip(self):
        """置く順 = 確認用の動画 → meta → zip(zip が見えたら印も動画もそろっている = 友人のアプリの約束)"""
        events = []
        real_zip, real_meta = deliver.zip_packs, deliver.write_meta_json

        def write_meta_json(path, doc):
            events.append(("meta", sorted(os.listdir(self.out))))
            return real_meta(path, doc)

        def zip_packs(*a, **k):
            events.append(("zip", sorted(os.listdir(self.out))))
            return real_zip(*a, **k)
        with mock.patch.object(deliver, "zip_packs", zip_packs), mock.patch.object(deliver, "write_meta_json", write_meta_json):
            dest = deliver.deliver_one(self.pack, self.out, "20261016-120000-abcdef__題", log_dir=self.logs, run=self.run_(), origin="auto", ended_at=1000)
        stem = "20261016-120000-abcdef__題"
        self.assertEqual(events, [("meta", [stem + ".preview.mp4"]), ("zip", sorted([stem + ".meta.json", stem + ".preview.mp4"]))])
        meta = deliver.meta_path_for(dest)
        with open(meta, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        doc = json.loads(raw.decode("utf-8"))
        self.assertEqual((doc["v"], doc["origin"]), (1, "auto"))
        self.assertRegex(doc["sentAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        from flow import deliveries
        row = deliveries.rows(self.logs)[-1]
        self.assertEqual((row["origin"], row["endedAt"], row["zip"]), ("auto", 1000000, os.path.basename(dest)))

    def test_meta_doc_fields_for_a_request(self):
        """依頼の分にも meta を必ず置く。欄 = meta_doc の形(v 1・kind clip・origin・requestId・zip・preview・title・videoId・markId・streamTitle・streamer・seconds)"""
        with mock.patch.object(pv, "pack_seconds", lambda d, ffprobe=None: 48.256):
            dest = deliver.deliver_one(self.pack, self.out, "20261016-120000-abcdef__題", origin="request", run=self.run_(),
                                       marks={self.pack: {"path": "x.mp4", "markId": "m7"}})
        with open(deliver.meta_path_for(dest), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(sorted(doc), sorted(["v", "kind", "origin", "sentAt", "requestId", "zip", "preview", "title", "videoId", "markId",
                                              "streamTitle", "streamer", "seconds"]))
        self.assertEqual(doc, {"v": 1, "kind": "clip", "origin": "request", "sentAt": doc["sentAt"], "requestId": "20261016-120000-abcdef",
                               "zip": "20261016-120000-abcdef__題.zip", "preview": "20261016-120000-abcdef__題.preview.mp4", "title": "clip",
                               "videoId": "abcdefghijk", "markId": "m7", "streamTitle": "題", "streamer": "", "seconds": 48.26})

    def test_two_packs_same_name_get_separate_metas(self):
        d1 = deliver.deliver_one(self.pack, self.out, "rid__題", origin="auto")
        d2 = deliver.deliver_one(self.pack, self.out, "rid__題", origin="auto")
        self.assertNotEqual(d1, d2)
        self.assertEqual(len([n for n in os.listdir(self.out) if n.endswith(".meta.json")]), 2)

    def test_failure_removes_meta_and_preview(self):
        with mock.patch.object(deliver, "zip_packs", side_effect=OSError(28, "no space")):
            with self.assertRaises(OSError):
                deliver.deliver_one(self.pack, self.out, "rid__題", origin="auto")
        self.assertEqual(os.listdir(self.out), [], "書きかけの印・確認用の動画を残さない")
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [], "一時の確認用の動画も消す")


class ZipPacksTest(unittest.TestCase):
    """n 本をまとめる zip(① 全自動の n 本ごとの届け方)とパックの中の動画の見つけ方"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliver-")
        self.a = os.path.join(self.tmp, "配信 A_pack")
        self.b = os.path.join(self.tmp, "配信 B_pack")
        put(os.path.join(self.a, "配信 A.mp4"), b"a" * 500)
        put(os.path.join(self.a, "配信 A_roughcut.mp4"), b"r" * 900)
        put(os.path.join(self.a, "cut-plan.json"), b"{}")
        put(os.path.join(self.b, "配信 B.mp4"), b"b" * 300)
        put(os.path.join(self.b, "sub", "x.txt"), b"x")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)

    def test_layout_and_dest(self):
        dest = deliver.unique_zip(self.out, "rid__題 1-2")
        self.assertEqual(deliver.preview_path_for(dest), os.path.join(self.out, "rid__題 1-2.preview.mp4"))
        got = deliver.zip_packs([self.a, self.b], self.out, "rid__題 1-2", dest=dest)
        self.assertEqual(got, dest)
        with zipfile.ZipFile(got) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
        self.assertEqual(names, sorted(["配信 A_pack/cut-plan.json", "配信 A_pack/配信 A.mp4", "配信 A_pack/配信 A_roughcut.mp4",
                                        "配信 B_pack/sub/x.txt", "配信 B_pack/配信 B.mp4"]))
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])

    def test_pack_video_and_title(self):
        self.assertEqual(pv.pack_video(self.a), os.path.join(self.a, "配信 A.mp4"))   # いちばん大きくても _roughcut は選ばない
        self.assertEqual(pv.pack_video(self.b), os.path.join(self.b, "配信 B.mp4"))
        self.assertIsNone(pv.pack_video(os.path.join(self.tmp, "無い")))
        self.assertEqual(pv.pack_title(self.a), "配信 A")
        self.assertEqual(pv.pack_title(os.path.join(self.tmp, "そのまま")), "そのまま")

    def test_names_and_place_preview(self):
        """名前 <依頼 id>__<題>(使えない文字は _)・まとめ動画を zip の隣に写す(元の一時ファイルは呼ぶ側が消す)・動画の無いパックがあれば作らない"""
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
        self.assertIsNone(pv.clip_preview(empty))   # 動画の無いパックは ffmpeg を呼ばない
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])


class FormatTest(unittest.TestCase):
    """届く物の名前の約束(F3-6): 確認用の動画 <zip の名前>.preview.mp4・印 <zip の名前>.meta.json。組の部品は無い"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliver-")

    def test_suffix_constants(self):
        self.assertEqual((deliver.PREVIEW_SUFFIX, deliver.META_SUFFIX), (".preview.mp4", ".meta.json"))
        self.assertEqual(deliver.meta_path_for(os.path.join("出力", "rid__題.zip")), os.path.join("出力", "rid__題.meta.json"))

    def test_meta_is_written_as_one_utf8_line_atomically(self):
        """meta の書き方: UTF-8・BOM なし・1 行・日本語はそのまま。書けなければ何も残さない"""
        out = os.path.join(self.tmp, "出力")
        os.makedirs(out)
        path = os.path.join(out, "rid__雑談 うた.meta.json")
        doc = {"v": 1, "title": "雑談 / うた"}
        self.assertEqual(deliver.write_meta_json(path, doc), doc)
        with open(path, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("雑談".encode("utf-8"), raw, "\\uXXXX にしない")
        self.assertEqual(json.loads(raw.decode("utf-8")), doc)
        self.assertNotIn(b"\n", raw.rstrip(b"\r\n"), "1 行")
        with self.assertRaises(UnicodeError):
            deliver.write_meta_json(os.path.join(out, "x.meta.json"), {"t": "bad\ud800"})
        self.assertEqual(os.listdir(out), [os.path.basename(path)], "書きかけを残さない")

    def test_pack_seconds(self):
        """パックの切り抜きの長さ(秒)。いちばん大きい動画(_roughcut は除く)を ffprobe に渡す。動画の無いパック・長さの読めない・0 以下・
        フォルダの無いものは None(ffprobe を呼ばない)"""
        a, b, c, d = (os.path.join(self.tmp, n + "_pack") for n in "abcd")
        put(os.path.join(a, "a.mp4"), b"a" * 500)
        put(os.path.join(a, "a_roughcut.mp4"), b"r" * 900)
        put(os.path.join(b, "b.mp4"), b"b")
        put(os.path.join(c, "c.mp4"), b"c")
        os.makedirs(d)   # 動画の無いパック
        put(os.path.join(d, "cut-plan.json"), b"{}")
        asked = []
        infos = {os.path.join(a, "a.mp4"): {"duration": 48.25}, os.path.join(b, "b.mp4"): {"duration": 0}, os.path.join(c, "c.mp4"): {"duration": None}}

        def probe(path, ffprobe=None, **_k):
            asked.append((path, ffprobe))
            return infos.get(path)
        with mock.patch.object(pv.normalize, "probe", probe):
            self.assertEqual(pv.pack_seconds(a, ffprobe="FFPROBE"), 48.25)
            self.assertIsNone(pv.pack_seconds(b))
            self.assertIsNone(pv.pack_seconds(c))
            self.assertIsNone(pv.pack_seconds(d))
            self.assertIsNone(pv.pack_seconds(os.path.join(self.tmp, "無い_pack")))
            infos[os.path.join(c, "c.mp4")] = {"duration": 7}
            self.assertIsInstance(pv.pack_seconds(c), float)
            self.assertEqual(pv.pack_seconds(c), 7.0)
        self.assertEqual(asked[0], (os.path.join(a, "a.mp4"), "FFPROBE"), "いちばん大きい動画(_roughcut でない)を調べる")
        self.assertEqual(len([1 for p, _f in asked if p.startswith(d)]), 0, "動画の無いパックは ffprobe を呼ばない")

class PreviewArgsTest(unittest.TestCase):
    """確認用の動画の ffmpeg の引数(ffmpeg は要らない): 480p・等速・札と字幕の焼き込み(drawtext)は無い・音は 96k の aac か無し(F3-6)"""

    def test_scale_480_and_no_labels(self):
        self.assertEqual(pv.PREVIEW_HEIGHT, 480)
        args = pv._preview_args("ffmpeg", "in.mp4", "out.mp4", 480, True)
        self.assertEqual(args[args.index("-vf") + 1], "scale=-2:480")
        self.assertNotIn("-filter_complex", args)
        self.assertFalse(any("drawtext" in a for a in args), "札・字幕は焼かない")
        self.assertFalse(any("setpts" in a or "atempo" in a for a in args), "等速")
        self.assertIn("-map", args)
        self.assertNotIn("-an", args)
        self.assertEqual(args[args.index("-b:a") + 1], "96k")
        self.assertEqual(args[-1], "out.mp4")

    def test_silent_clip_has_no_audio_args(self):
        args = pv._preview_args("ffmpeg", "in.mp4", "out.mp4", 480, False)
        self.assertIn("-an", args)
        self.assertNotIn("-b:a", args)
        self.assertFalse(any("drawtext" in a for a in args))

class PreviewTest(unittest.TestCase):
    """確認用の動画(ffmpeg が要る。無ければ skip)"""

    def setUp(self):
        from ytt import tools
        self.ffmpeg, self.ffprobe = tools.find_tool("ffmpeg"), tools.find_tool("ffprobe")   # 本物(ほかのテストが環境変数で偽物に向けていても)
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg が無い")
        self.tmp = testkit.tempdir(self, "ytt-preview-")
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

    def test_one_clip_at_480_and_normal_speed(self):
        from ytt import normalize
        a = self.clip("一本目_pack/一本目.mp4", 2)
        out = os.path.join(self.tmp, "preview.mp4")
        self.assertTrue(pv.make_preview(a, out, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        info = normalize.probe(out, ffprobe=self.ffprobe)
        self.assertEqual((info["height"], info["has_audio"]), (480, True))
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.5)   # 等速(2026-10-08 ユーザー決定)
        self.assertEqual(self.logs, [])

    def test_silent_clip_makes_a_silent_preview(self):
        from ytt import normalize
        b = self.clip("b_pack/b.mp4", 1, audio=False)
        out = os.path.join(self.tmp, "preview.mp4")
        self.assertTrue(pv.make_preview(b, out, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        self.assertFalse(normalize.probe(out, ffprobe=self.ffprobe)["has_audio"])

    def test_broken_input_fails_quietly(self):
        bad = os.path.join(self.tmp, "x_pack", "x.mp4")
        put(bad, os.urandom(3000))   # 文字だけのファイルは ffmpeg が「文字の動画」として読めてしまうので、でたらめなバイト列で
        out = os.path.join(self.tmp, "p.mp4")
        self.assertFalse(pv.make_preview(bad, out, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append))
        self.assertTrue(self.logs and "確認用の動画を作れませんでした" in self.logs[-1], self.logs)
        self.assertFalse(os.path.exists(out))
        self.assertFalse(pv.make_preview("", os.path.join(self.tmp, "p.mp4")))

    def test_run_ffmpeg_stops_on_check_and_timeout(self):
        """確認用の動画の ffmpeg: check() が例外を投げたら止めて投げ直す・時間切れは (1, "timeout")・普通に終われば (0, 標準エラーの末尾)"""
        slow = [self.ffmpeg, "-hide_banner", "-nostdin", "-re", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=30", "-f", "null", "-"]

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
        code, err = pv._run_ffmpeg([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", os.path.join(self.tmp, "無い.mp4"), "-f", "null", "-"], 30, None)
        self.assertNotEqual(code, 0)
        self.assertTrue(err)

    def test_pack_seconds_with_real_ffprobe(self):
        """組の印の長さ(meta の seconds): 本物の動画は秒が読める・壊れた動画・動画の無いパックは None"""
        a = self.clip("一本目_pack/一本目.mp4", 2)
        bad = os.path.join(self.tmp, "x_pack", "x.mp4")
        put(bad, os.urandom(3000))
        empty = os.path.join(self.tmp, "空_pack")
        os.makedirs(empty)
        self.assertAlmostEqual(pv.pack_seconds(os.path.dirname(a), ffprobe=self.ffprobe), 2.0, delta=0.5)
        self.assertIsNone(pv.pack_seconds(os.path.dirname(bad), ffprobe=self.ffprobe))
        self.assertIsNone(pv.pack_seconds(empty, ffprobe=self.ffprobe))

class DeliveriesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "ytt-deliver-")
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"))
        self.folder = os.path.join(self.tmp, "Dropbox")
        os.makedirs(self.folder)
        self.cfg = {"folder": self.folder}
        self.packs = {os.path.normpath(self.pack)}
        self.logs = []
        self.log_dir = os.path.join(self.tmp, "logs")
        self.dl = deliver.Deliveries(lambda: self.cfg["folder"], lambda d: os.path.normpath(d) in self.packs, log=self.logs.append, log_dir=self.log_dir)
        for name, fake in (("make_preview", fake_make_preview), ("pack_seconds", lambda d, ffprobe=None: None)):   # ffmpeg を呼ばない
            p = mock.patch.object(pv, name, fake)
            p.start()
            self.addCleanup(p.stop)

    def test_start_and_done(self):
        j = wait(self.dl, self.dl.start(self.pack, "【雑談】校正済み/1"))
        self.assertEqual(j["state"], "done")
        self.assertRegex(j["name"], r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}__【雑談】校正済み_1\.zip$")
        # 手で届けるのも 1 本ずつの届け方: 確認用の動画 + 出どころの印 <zip の名前>.meta.json(友人には「依頼なし」= origin auto。D-SEND 2-7・2-8)
        stem = j["name"][:-4]
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, deliver.OUT_DIR))), sorted([j["name"], stem + deliver.PREVIEW_SUFFIX, stem + deliver.META_SUFFIX]))
        self.assertTrue(self.logs)

    def test_same_as_auto_preview_zip_and_record(self):
        """手で届けるのも全自動と同じ 1 本の届け方(deliver_one): 確認用の動画を zip の隣に・届けた記録 deliveries.jsonl に 1 行(友人の「要らない」が引ける。Q16)"""
        from human.friend import friend_feedback
        clip = os.path.join(self.tmp, "clip.mp4")
        j = wait(self.dl, self.dl.start(self.pack, "題", clip={"path": clip, "markId": "m1", "videoId": "abcdefghijk"}))
        self.assertEqual(j["state"], "done")
        out = os.path.join(self.folder, deliver.OUT_DIR)
        self.assertEqual(sorted(os.listdir(out)), sorted([j["name"], j["name"][:-4] + deliver.PREVIEW_SUFFIX, j["name"][:-4] + deliver.META_SUFFIX]))
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [], "一時の確認用の動画は消す")
        with open(os.path.join(out, j["name"][:-4] + deliver.META_SUFFIX), "rb") as f:
            meta = json.loads(f.read().decode("utf-8"))
        self.assertEqual((meta["v"], meta["origin"]), (1, "auto"))
        row = friend_feedback.find_delivery(self.log_dir, j["name"])
        self.assertEqual((row["requestId"], row["videoId"], row["title"], row["origin"]), (j["name"].split("__")[0], "abcdefghijk", "題", "manual"))
        self.assertEqual(row["packs"], [{"dir": os.path.normpath(self.pack), "path": clip, "markId": "m1"}])
        j2 = wait(self.dl, self.dl.start(self.pack, ""))   # 切り抜きが分からなければパックだけ
        self.assertEqual(friend_feedback.find_delivery(self.log_dir, j2["name"])["packs"], [{"dir": os.path.normpath(self.pack), "path": "", "markId": ""}])

    def test_without_log_dir_does_not_record(self):
        dl = deliver.Deliveries(lambda: self.cfg["folder"], lambda d: os.path.normpath(d) in self.packs)
        self.assertEqual(wait(dl, dl.start(self.pack, "t"))["state"], "done")
        self.assertFalse(os.path.exists(self.log_dir))

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

    def test_state_on_board(self):
        """RS8 の ② の口 S2: 仕事の状態が変わると、掲示板に dl:<id> がその state で載る"""
        from flow import board as B
        b = B.Board()
        self.dl.attach_board(b)
        j = wait(self.dl, self.dl.start(self.pack, "t"))
        b.refresh()
        got = b.get("dl:" + j["id"])
        self.assertEqual((got["kind"], got["state"], got["target"]["path"], got["finishedAt"] is not None), ("deliver", "done", os.path.normpath(self.pack), True))
        orig = deliver.zip_packs
        deliver.zip_packs = mock.Mock(side_effect=OSError(28, "No space left on device"))
        self.addCleanup(setattr, deliver, "zip_packs", orig)
        j2 = wait(self.dl, self.dl.start(self.pack, "t2"))
        b.refresh()
        got = b.get("dl:" + j2["id"])
        self.assertEqual(got["state"], "error")
        self.assertIn("No space left", got["error"]["text"])

    def test_status_unknown(self):
        self.assertIsNone(self.dl.status("nope"))
        self.assertIsNone(self.dl.status(None))

    def test_error_is_reported(self):
        orig = deliver.zip_packs

        def boom(*a, **k):
            raise OSError(28, "No space left on device")
        deliver.zip_packs = boom
        self.addCleanup(setattr, deliver, "zip_packs", orig)
        j = wait(self.dl, self.dl.start(self.pack, "t"))
        self.assertEqual(j["state"], "error")
        self.assertIn("No space left", j["message"])
        self.assertFalse(os.path.exists(self.log_dir), "置けなければ記録しない")

    def test_unexpected_error_is_not_left_running(self):
        """OSError でない失敗(zip にできないファイルの ValueError など)でも error にする = 同じパックをもう一度届けられる(9c-2)"""
        with mock.patch.object(deliver, "zip_packs", mock.Mock(side_effect=ValueError("ZIP does not support timestamps before 1980"))):
            j = wait(self.dl, self.dl.start(self.pack, "t"))
        self.assertEqual(j["state"], "error")
        self.assertIn("ValueError", j["message"])
        self.assertFalse(self.dl.running(self.pack))
        self.assertEqual(wait(self.dl, self.dl.start(self.pack, "t"))["state"], "done")



if __name__ == "__main__":
    unittest.main()
