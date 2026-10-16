"""パックを友人へ届ける(src/human/friend/deliver.py・入口の api/ytt/deliver)の単体テスト。一時フォルダだけを使う。

実行(リポジトリ直下から): python -m unittest src/human/friend/tests/test_deliver.py -v
(入口の ytt_api の受け渡しは src/app/tests/test_deliver_api.py)
"""
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
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
        # friend-apps/request-sender/src/Core.cs の NameRx と同じ形(アプリが先頭の id を除いて題名を出す)
        self.assertRegex(deliver.request_id(), r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class OriginTest(unittest.TestCase):
    """D-SEND 2-7: 出どころ。1 本(組でない)で依頼でなければ zip より先に <zip の名前>.meta.json。依頼・組の中の 1 本には置かない。届けた記録に origin・endedAt"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pack = os.path.join(self.tmp, "clip_pack")
        put(os.path.join(self.pack, "clip.mp4"), b"v")
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)
        self.logs = os.path.join(self.tmp, "logs")
        p = mock.patch.object(pv, "batch_preview", lambda dirs, check=None, log=None: None)
        p.start()
        self.addCleanup(p.stop)

    def run_(self, rid="rid"):
        import types
        return types.SimpleNamespace(request_id=rid, id="run1", video_id="abcdefghijk", title="題")

    def test_face_origin(self):
        self.assertEqual([deliver.face_origin(o) for o in ("request", None, "", "auto", "manual")], ["request"] * 3 + ["auto"] * 2)
        self.assertEqual(deliver.META_SUFFIX, ".meta.json")

    def test_auto_one_places_meta_before_zip(self):
        seen = []
        real = deliver.zip_packs

        def zip_packs(*a, **k):   # zip を置く時点で、印はもう隣にある(友人のアプリは zip が見えたらそろっているとみなす)
            seen.append(sorted(os.listdir(self.out)))
            return real(*a, **k)
        with mock.patch.object(deliver, "zip_packs", zip_packs):
            dest = deliver.deliver_one(self.pack, self.out, "20261016-120000-abcdef__題", log_dir=self.logs, run=self.run_(), origin="auto", ended_at=1000)
        meta = deliver.meta_path_for(dest)
        self.assertEqual(seen, [[os.path.basename(meta)]])
        with open(meta, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        doc = json.loads(raw.decode("utf-8"))
        self.assertEqual((doc["v"], doc["origin"]), (1, "auto"))
        self.assertRegex(doc["sentAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        from flow import deliveries
        row = deliveries.rows(self.logs)[-1]
        self.assertEqual((row["origin"], row["endedAt"], row["zip"]), ("auto", 1000000, os.path.basename(dest)))

    def test_request_and_group_member_have_no_meta(self):
        dest = deliver.deliver_one(self.pack, self.out, "rid__依頼", origin="request")
        dest2 = deliver.deliver_one(self.pack, self.out, "rid__組の 1 本", origin="auto", with_preview=False)
        self.assertEqual(sorted(os.listdir(self.out)), sorted([os.path.basename(dest), os.path.basename(dest2)]))

    def test_failure_removes_meta(self):
        with mock.patch.object(deliver, "zip_packs", side_effect=OSError(28, "no space")):
            with self.assertRaises(OSError):
                deliver.deliver_one(self.pack, self.out, "rid__題", origin="auto")
        self.assertEqual(os.listdir(self.out), [], "書きかけの印を残さない")

    def test_group_json_origin(self):
        os.makedirs(self.out)
        p = os.path.join(self.out, "g.group.json")
        self.assertEqual(deliver.write_group_json(p, "t", "1-2", None, [], origin="auto")["origin"], "auto")
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["origin"], "auto")
        self.assertNotIn("origin", deliver.write_group_json(p, "t", "1-2", None, []), "渡さなければ古い形のまま")


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
        self.assertIsNone(pv.batch_preview([self.a, empty]))   # ffmpeg を呼ばない
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".deliver-")], [])


class GroupFilesTest(unittest.TestCase):
    """組で届ける(notes:docs/spec/friend.md の 2-16)の部品: 組の名前・一覧の packs・一覧のファイル・クリップの長さ"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-deliver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "Dropbox", deliver.OUT_DIR)

    def test_suffix_constants(self):
        self.assertEqual((deliver.GROUP_SUFFIX, deliver.PREVIEW_SUFFIX), (".group.json", ".preview.mp4"))

    def test_group_paths_plain_and_unique(self):
        """組の名前 -> (まとめ動画, 一覧, 使う名前)。まとめ動画か一覧が同じ名前で残っていれば、末尾に 4 文字足す(2 つを同じ名前でそろえる)。zip の有無は見ない"""
        name = "20261001-120000-abc123__題 1-5"
        pv, js, used = deliver.group_paths(self.out, name)   # 出力\ がまだ無くても動く
        self.assertEqual((pv, js, used), (os.path.join(self.out, name + ".preview.mp4"), os.path.join(self.out, name + ".group.json"), name))
        os.makedirs(self.out)
        put(os.path.join(self.out, name + ".zip"))   # 同じ名前の zip だけなら変えない(zip は 1 本ずつ unique_zip で決める)
        self.assertEqual(deliver.group_paths(self.out, name)[2], name)
        for existing in (".preview.mp4", ".group.json"):
            put(os.path.join(self.out, name + existing))
            pv, js, used = deliver.group_paths(self.out, name)
            self.assertRegex(used, r"^%s-[0-9a-f]{4}$" % re.escape(name), existing)
            self.assertEqual((pv, js), (os.path.join(self.out, used + ".preview.mp4"), os.path.join(self.out, used + ".group.json")), existing)
            self.assertFalse(os.path.exists(pv) or os.path.exists(js))
            os.remove(os.path.join(self.out, name + existing))

    def test_group_members_accumulate_preview_start(self):
        """previewStart = まとめ動画の中でそのクリップが始まる秒(前のクリップの長さの合計)・duration = そのクリップの秒。小数 2 桁に丸める"""
        zips = [(1, os.path.join(self.out, "rid__a.zip")), (2, os.path.join(self.out, "rid__b.zip")), (3, os.path.join(self.out, "rid__c.zip"))]
        got = deliver.group_members(zips, ["a", "b", "c"], [10.5, 20.25, 5.0])
        self.assertEqual(got, [{"n": 1, "zip": "rid__a.zip", "title": "a", "previewStart": 0.0, "duration": 10.5},
                               {"n": 2, "zip": "rid__b.zip", "title": "b", "previewStart": 10.5, "duration": 20.25},
                               {"n": 3, "zip": "rid__c.zip", "title": "c", "previewStart": 30.75, "duration": 5.0}])
        self.assertEqual(sorted(got[0]), ["duration", "n", "previewStart", "title", "zip"])
        rounded = deliver.group_members(zips[:2], ["a", "b"], [12.3456, 7.0])
        self.assertEqual([(m["previewStart"], m["duration"]) for m in rounded], [(0.0, 12.35), (12.35, 7.0)])

    def test_group_members_unknown_length_makes_following_starts_unknown(self):
        """長さの分からないクリップ以降の previewStart は None(ずれた秒を教えない)。そのクリップ自身の頭は分かる"""
        zips = [(n, "rid__%d.zip" % n) for n in (1, 2, 3, 4)]
        got = deliver.group_members(zips, list("abcd"), [10.0, None, 5.0, 2.0])
        self.assertEqual([(m["n"], m["previewStart"], m["duration"]) for m in got], [(1, 0.0, 10.0), (2, 10.0, None), (3, None, 5.0), (4, None, 2.0)])
        got = deliver.group_members(zips[:2], ["a", "b"], [None, 3.0])
        self.assertEqual([(m["previewStart"], m["duration"]) for m in got], [(0.0, None), (None, 3.0)])

    def test_group_members_uses_placed_zips_only(self):
        """置けた zip だけ(n は実行の通し番号のまま)。zip の名前は名前だけ(フォルダは入れない)。何も置けなければ空"""
        got = deliver.group_members([(3, os.path.join(self.out, "rid__c.zip")), (4, os.path.join(self.out, "rid__d.zip"))], ["c", "d", "e"], [1.0, 2.0, 3.0])
        self.assertEqual([(m["n"], m["zip"], m["title"]) for m in got], [(3, "rid__c.zip", "c"), (4, "rid__d.zip", "d")])
        self.assertEqual(deliver.group_members([], ["a"], [1.0]), [])

    def test_write_group_json(self):
        """組の一覧: UTF-8・BOM なし・日本語はそのまま。鍵は v・title・range・preview(名前だけ)・packs・sentAt(ISO 8601 + タイムゾーン)"""
        os.makedirs(self.out)
        path = os.path.join(self.out, "rid__雑談 うた 1-2.group.json")
        members = deliver.group_members([(1, "rid__a.zip"), (2, "rid__b.zip")], ["あ", "い"], [4.5, 6.0])
        now = 1791000000   # 夏でも冬でも、その時点のずれ(夏時間)で書く
        doc = deliver.write_group_json(path, "雑談 / うた", "1-2", os.path.join(self.out, "rid__雑談 うた 1-2.preview.mp4"), members, now=now)
        with open(path, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("雑談".encode("utf-8"), raw, "\\uXXXX にしない")
        self.assertEqual(json.loads(raw.decode("utf-8")), doc)
        self.assertEqual(sorted(doc), ["packs", "preview", "range", "sentAt", "title", "v"])
        self.assertEqual((doc["v"], doc["title"], doc["range"], doc["preview"], doc["packs"]), (1, "雑談 / うた", "1-2", "rid__雑談 うた 1-2.preview.mp4", members))
        self.assertEqual(doc["sentAt"], datetime.datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"))
        for t in (1783000000, 1799000000):   # 冬・夏のどちらの時刻でも、その時刻のずれ
            self.assertEqual(deliver.write_group_json(path, "t", "1", None, [], now=t)["sentAt"],
                             datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds"), t)
        self.assertRegex(deliver.write_group_json(path, "t", "1", None, [])["sentAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")   # now を省けば今

    def test_write_group_json_is_atomic(self):
        """組の一覧は原子的に書く: 書く途中で失敗しても書きかけのファイルを残さない(友人のアプリは一覧が見えたら組がそろっているとみなす。
        前は open "w" で先に作っていた。資料 4 節の疑い 3)。中身は今までと同じ 1 行(json.dump と同じバイト列・改行なし)"""
        os.makedirs(self.out)
        path = os.path.join(self.out, "rid__t 1-2.group.json")
        with self.assertRaises(UnicodeError):
            deliver.write_group_json(path, "bad\ud800", "1-2", None, [])   # UTF-8 にできない題 = 書く途中の失敗
        self.assertEqual(os.listdir(self.out), [])
        doc = deliver.write_group_json(path, "雑談", "1-2", None, [], now=1791000000)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), json.dumps(doc, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(os.listdir(self.out), [os.path.basename(path)])   # 一時ファイルを残さない

    def test_write_group_json_without_preview_is_null(self):
        """まとめ動画を作れなかった組: preview は null(zip と一覧は届ける)"""
        path = os.path.join(self.tmp, "g.group.json")
        deliver.write_group_json(path, "t", "1-2", None, [])
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIsNone(doc["preview"])
        self.assertEqual(doc["packs"], [])

    def test_clip_seconds(self):
        """各パックの切り抜きの長さ(秒)。パックの切り抜きの動画(いちばん大きい動画。_roughcut は除く)を ffprobe に渡す。動画の無いパック・
        長さの読めない・0 以下の動画は None"""
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
            self.assertEqual(pv.clip_seconds([a, b, c, d], ffprobe="FFPROBE"), [48.25, None, None, None])
            self.assertEqual(pv.clip_seconds([]), [])
            infos[os.path.join(c, "c.mp4")] = {"duration": 7}
            infos[os.path.join(b, "b.mp4")] = {"duration": -3.0}
            self.assertEqual(pv.clip_seconds([b, c]), [None, 7.0])
            self.assertIsInstance(pv.clip_seconds([c])[0], float)
            self.assertEqual(pv.clip_seconds([os.path.join(self.tmp, "無い_pack")]), [None])   # フォルダが無い
        self.assertEqual(asked[0], (os.path.join(a, "a.mp4"), "FFPROBE"), "いちばん大きい動画(_roughcut でない)を調べる")
        self.assertNotIn(os.path.join(d, "cut-plan.json"), [p for p, _f in asked])
        self.assertEqual(len([1 for p, _f in asked if p.startswith(d)]), 0, "動画の無いパックは ffprobe を呼ばない")


class PreviewArgsTest(unittest.TestCase):
    """まとめ動画の ffmpeg の引数(ffmpeg は要らない): 等速だけ(setpts/atempo を入れない)・札はずっと(2026-10-08 ユーザー決定)"""

    def test_normal_speed_and_label_always(self):
        self.assertEqual(pv.PREVIEW_LABEL_SEC, 0)
        args = pv._preview_args("ffmpeg", ["a.mp4", "b.mp4"], "out.mp4", 480, True, label_files=["l1.txt", "l2.txt"], font="C:/Windows/Fonts/meiryo.ttc")
        fc = args[args.index("-filter_complex") + 1]
        self.assertNotIn("setpts", fc)
        self.assertNotIn("atempo", fc)
        self.assertIn("[0:a]anull[a0]", fc)
        self.assertIn("drawtext=", fc)
        self.assertNotIn("enable=", fc, "札はずっと出す")
        self.assertIn("concat=n=2:v=1:a=1[v][a]", fc)

    def test_without_labels_or_audio(self):
        args = pv._preview_args("ffmpeg", ["a.mp4"], "out.mp4", 480, False)
        fc = args[args.index("-filter_complex") + 1]
        self.assertNotIn("drawtext", fc)
        self.assertIn("concat=n=1:v=1:a=0[v]", fc)
        self.assertIn("-an", args)


class PreviewTest(unittest.TestCase):
    """まとめ動画(ffmpeg が要る。無ければ skip)"""

    def setUp(self):
        from ytt import tools
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

    def test_two_clips_at_normal_speed(self):
        from ytt import normalize
        a, b = self.clip("一本目_pack/一本目.mp4", 2), self.clip("二本目_pack/二本目.mp4", 2)
        out = os.path.join(self.tmp, "preview.mp4")
        self.assertTrue(pv.make_preview([a, b], out, ["一本目", "二本目"], ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        info = normalize.probe(out, ffprobe=self.ffprobe)
        self.assertEqual((info["height"], info["has_audio"]), (480, True))
        self.assertAlmostEqual(info["duration"], 4.0, delta=0.5)   # 等速: 2 秒 × 2 本 = 4 秒(2026-10-08 ユーザー決定)
        self.assertEqual(self.logs, [])

    def test_silent_clip_makes_a_silent_preview(self):
        from ytt import normalize
        a, b = self.clip("a_pack/a.mp4", 1), self.clip("b_pack/b.mp4", 1, audio=False)
        out = os.path.join(self.tmp, "preview.mp4")
        self.assertTrue(pv.make_preview([a, b], out, ["A", "B"], ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append), self.logs)
        self.assertFalse(normalize.probe(out, ffprobe=self.ffprobe)["has_audio"])

    def test_broken_input_fails_quietly(self):
        bad = os.path.join(self.tmp, "x_pack", "x.mp4")
        put(bad, os.urandom(3000))   # 文字だけのファイルは ffmpeg が「文字の動画」として読めてしまうので、でたらめなバイト列で
        self.assertFalse(pv.make_preview([bad], os.path.join(self.tmp, "p.mp4"), ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, log=self.logs.append))
        self.assertTrue(self.logs and "まとめ動画を作れませんでした" in self.logs[-1], self.logs)
        self.assertFalse(pv.make_preview([], os.path.join(self.tmp, "p.mp4")))

    def test_run_ffmpeg_stops_on_check_and_timeout(self):
        """まとめ動画の ffmpeg: check() が例外を投げたら止めて投げ直す・時間切れは (1, "timeout")・普通に終われば (0, 標準エラーの末尾)"""
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

    def test_clip_seconds_with_real_ffprobe(self):
        """組の一覧の長さ: 本物の動画は秒が読める・壊れた動画・動画の無いパックは None"""
        a = self.clip("一本目_pack/一本目.mp4", 2)
        bad = os.path.join(self.tmp, "x_pack", "x.mp4")
        put(bad, os.urandom(3000))
        empty = os.path.join(self.tmp, "空_pack")
        os.makedirs(empty)
        got = pv.clip_seconds([os.path.dirname(a), os.path.dirname(bad), empty], ffprobe=self.ffprobe)
        self.assertAlmostEqual(got[0], 2.0, delta=0.5)
        self.assertEqual(got[1:], [None, None])


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
        self.log_dir = os.path.join(self.tmp, "logs")
        self.dl = deliver.Deliveries(lambda: self.cfg["folder"], lambda d: os.path.normpath(d) in self.packs, log=self.logs.append, log_dir=self.log_dir)
        p = mock.patch.object(pv, "batch_preview", lambda dirs, check=None, log=None: None)   # まとめ動画は作らない(ffmpeg を呼ばない)。作るときは各テストで
        p.start()
        self.addCleanup(p.stop)

    def test_start_and_done(self):
        j = wait(self.dl, self.dl.start(self.pack, "【雑談】校正済み/1"))
        self.assertEqual(j["state"], "done")
        self.assertRegex(j["name"], r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}__【雑談】校正済み_1\.zip$")
        # 手で届けるも出どころの印 <zip の名前>.meta.json(友人には「依頼なし」= origin auto。D-SEND 2-7・2-8)
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, deliver.OUT_DIR))), sorted([j["name"], j["name"][:-4] + deliver.META_SUFFIX]))
        self.assertTrue(self.logs)

    def test_same_as_auto_preview_zip_and_record(self):
        """手で届けるのも全自動と同じ 1 本の届け方(deliver_one): まとめ動画を zip の隣に・届けた記録 deliveries.jsonl に 1 行(友人の「要らない」が引ける。Q16)"""
        from human.friend import friend_feedback
        tmp_preview = os.path.join(self.tmp, ".deliver-preview-x.mp4")

        def fake_preview(dirs, check=None, log=None):
            put(tmp_preview, b"PV")
            return tmp_preview
        clip = os.path.join(self.tmp, "clip.mp4")
        with mock.patch.object(pv, "batch_preview", fake_preview):
            j = wait(self.dl, self.dl.start(self.pack, "題", clip={"path": clip, "markId": "m1", "videoId": "abcdefghijk"}))
        self.assertEqual(j["state"], "done")
        out = os.path.join(self.folder, deliver.OUT_DIR)
        self.assertEqual(sorted(os.listdir(out)), sorted([j["name"], j["name"][:-4] + deliver.PREVIEW_SUFFIX, j["name"][:-4] + deliver.META_SUFFIX]))
        self.assertFalse(os.path.exists(tmp_preview), "一時のまとめ動画は消す")
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
