"""resolve_export(Resolve パッケージ = cut2resolve の Text+ パックを zip にしたもの)と「残す行」の規則のテスト。
同じ入力から cut2resolve と同じ中身になることは、リポジトリ直下の tools/test_resolve_pack_contract.py が確かめる。"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
os.environ.setdefault("YTT_CUT2RESOLVE_DIR", os.path.join(os.path.dirname(HERE), "cut2resolve"))   # 一時フォルダに写した serve.py 用

import resolve_export  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_video(path, dur, fps="30"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=%s:duration=%s" % (fps, dur),
                    "-f", "lavfi", "-i", "sine=duration=%s" % dur, "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", path], check=True)


class RulesTests(unittest.TestCase):
    def test_kept_spans_is_the_single_rule(self):
        """残す区間の規則: カット済・文字が空の行は除き、重なる・接する行はまとめる。すき間は残さない。"""
        segs = [{"id": "a", "start": 0, "end": 2, "text": "残す"}, {"id": "b", "start": 2, "end": 3, "text": "続き"},
                {"id": "c", "start": 3, "end": 4, "text": "切る", "cutState": "cut"}, {"id": "d", "start": 4.5, "end": 5, "text": "  "},
                {"id": "e", "start": 6, "end": 7, "text": "後"}, {"id": "f", "start": 6.5, "end": 8, "text": "重なる"}]
        spans = resolve_export.kept_spans(segs)
        self.assertEqual([(s["start"], s["end"], [g["id"] for g in s["segments"]]) for s in spans],
                         [(0.0, 3.0, ["a", "b"]), (6.0, 8.0, ["e", "f"])])
        self.assertFalse(resolve_export.is_kept({"text": "x", "cutState": "cut"}))
        self.assertTrue(resolve_export.is_kept({"text": "x", "cutState": "keep"}))

    def test_srt_text_format(self):
        self.assertEqual(resolve_export.srt_text([(0, 1.5, "一"), (3661.0005, 3662, "二\n行")]),
                         "1\n00:00:00,000 --> 00:00:01,500\n一\n\n2\n01:01:01,001 --> 01:01:02,000\n二\n行\n")
        self.assertEqual(resolve_export.srt_time(-1), "00:00:00,000")

    def test_cut2resolve_dir(self):
        self.assertTrue(os.path.isfile(os.path.join(resolve_export.cut2resolve_dir(), "pack.py")))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.source = os.path.join(cls.tmp, "clip.mp4")
        make_video(cls.source, 8)
        cls.v60 = os.path.join(cls.tmp, "v60.mp4")
        make_video(cls.v60, 6, "60")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        for n in ("clip.edit.json", "clip_edit.mp4"):
            p = os.path.join(self.tmp, n)
            if os.path.exists(p):
                os.unlink(p)

    def doc(self, source=None, **kw):
        d = {"title": "テスト", "sourcePath": source or self.source, "whole": True, "duration": 8,
             "segments": [{"id": "s1", "start": 0, "end": 2, "text": "残す"},
                          {"id": "s2", "start": 2, "end": 4, "text": "切る", "cutState": "cut"},
                          {"id": "s3", "start": 4, "end": 8, "text": "もう一度残す"}]}
        d.update(kw)
        return d

    def package(self, doc, *a, **kw):
        path, temp_dir, info = resolve_export.create_package(doc, *a, **kw)
        self.addCleanup(shutil.rmtree, temp_dir, True)
        z = zipfile.ZipFile(path)
        self.addCleanup(z.close)
        return z, info

    def ip(self, z):
        """パックの Lua に埋め込んだ計画(区間・字幕)。2026-09-26 まで textplus-import.json で入れていた中身"""
        import resolve_textplus
        return resolve_textplus.read_script_plan(z.read("テスト_pack/create_resolve_textplus_project.lua").decode("utf-8"))

    def test_zip_is_the_textplus_pack(self):
        z, info = self.package(self.doc())
        names = set(z.namelist())
        top = {n.split("/")[0] for n in names}
        self.assertEqual(top, {"テスト_pack"})                      # 展開するとフォルダが1つ
        rel = {n.split("/", 1)[1] for n in names}
        # 最小限(④): 動画・Lua・雛形・登録用の ps1/bat・友人へ.txt だけ(EDL・SRT・cut-plan.json・textplus-import.json は入れない)
        self.assertEqual({"media/clip.mp4", "create_resolve_textplus_project.lua",
                          "install_resolve_textplus_script.ps1", "ResolveにText+スクリプトを登録.bat", "友人へ.txt",
                          "textplus-template.drb"}, {n for n in rel if not n.endswith("/")}, rel)
        self.assertEqual((info["cuts"], info["captions"], info["media"]["hasEditHandles"]), (2, 2, False))
        ip = self.ip(z)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(0, 60), (120, 240)])
        self.assertEqual([(c["startFrame"], c["endFrame"], c["text"]) for c in ip["captions"]],
                         [(0, 60, "残す"), (60, 180, "もう一度残す")])
        self.assertEqual(ip["target"], {"fps": 30, "width": 1080, "height": 1920})
        lua = z.read("テスト_pack/create_resolve_textplus_project.lua").decode("utf-8")
        self.assertNotIn("CreateProject", lua)                     # プロジェクトは手で作る(スクリプトは作らない)
        self.assertNotIn(self.tmp, lua)                            # PC のパスを入れない
        z2, _ = self.package(self.doc(), backup=True)              # 「予備も入れる」
        rel2 = {n.split("/", 1)[1] for n in z2.namelist()}
        self.assertTrue({"clip.edl", "clip_cut.srt", "予備_EDLで開く手順.txt"} <= rel2, rel2)
        self.assertNotIn("cut-plan.json", rel2)
        self.assertIn("もう一度残す", z2.read("テスト_pack/clip_cut.srt").decode("utf-8"))

    def test_uses_studio_edit_media(self):
        """切り抜きスタジオの余白つき素材(前後10秒)があれば、それを入れて、区間を余白の分だけ後ろへずらす"""
        make_video(os.path.join(self.tmp, "clip_edit.mp4"), 28)
        with open(os.path.join(self.tmp, "clip.edit.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/edit-media/v1", "media": "clip_edit.mp4", "selectionIn": 10,
                       "handleBefore": 10, "handleAfter": 10}, f)
        z, info = self.package(self.doc())
        self.assertTrue(info["media"]["hasEditHandles"])
        self.assertEqual(info["media"]["file"], "media/clip_edit.mp4")
        ip = self.ip(z)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(300, 360), (420, 540)])
        self.assertEqual([c["startFrame"] for c in ip["captions"]], [0, 60])
        self.assertEqual(ip["sourceTimeline"], {"startFrame": 0, "endFrame": 840})
        self.assertIn("テスト_pack/media/clip_edit.mp4", z.namelist())

    def test_selected_fps_is_the_project_not_the_media(self):
        """60fps の動画で 30 を選んでも、カットの位置は動画の fps で数える(以前はここがずれていた)"""
        doc = self.doc(self.v60, duration=6, segments=[{"id": "a", "start": 2, "end": 4, "text": "a"}])
        z, _ = self.package(doc, "30")
        ip = self.ip(z)
        # 2〜4 秒 = 60fps の 120〜240。行の端を広げる(⑥。この動画は無音が無い → 決まった余白 前 0.1 秒・後 0.2 秒 = 6・12 フレーム)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(114, 252)])
        self.assertEqual((ip["fps"], ip["target"]["fps"]), ("60/1", 30))

    def test_landscape_target(self):
        z, _ = self.package(self.doc(), "60", "1920x1080")
        self.assertEqual(self.ip(z)["target"], {"fps": 60, "width": 1920, "height": 1080})

    def test_errors(self):
        tmp_root = tempfile.gettempdir()
        before = {n for n in os.listdir(tmp_root) if n.startswith("resolve-package-")}
        for args, msg in (((self.doc(), "29.97"), "fps"), ((self.doc(), "30", "12x"), "解像度"),
                          ((self.doc(source=os.path.join(self.tmp, "none.mp4")),), "元の動画"),
                          ((self.doc(segments=[{"id": "a", "start": 1, "end": 2, "text": "x", "cutState": "cut"}]),), "残す行")):
            with self.subTest(msg=msg), self.assertRaises(resolve_export.ResolveExportError) as cm:
                resolve_export.create_package(*args)
            self.assertIn(msg, str(cm.exception))
        after = {n for n in os.listdir(tmp_root) if n.startswith("resolve-package-")}
        self.assertEqual(after - before, set())   # 失敗しても一時フォルダを残さない


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class HttpTests(unittest.TestCase):
    """/api/resolve-package(一時フォルダに写した serve.py から、隣に無い cut2resolve を YTT_CUT2RESOLVE_DIR で見つける)"""

    @classmethod
    def setUpClass(cls):
        import test_backend
        cls.tmp = tempfile.mkdtemp()
        cls.video = os.path.join(cls.tmp, "clip.mp4")
        make_video(cls.video, 8)
        os.makedirs(os.path.join(cls.tmp, "transcripts"))
        cls.tid = "0123456789ab"
        doc = {"id": cls.tid, "title": "HTTP", "sourcePath": cls.video, "whole": True, "duration": 8, "updatedAt": 1,
               "segments": [{"id": "s1", "start": 1, "end": 3, "text": "こんにちは"}, {"id": "s2", "start": 3, "end": 5, "text": "x", "cutState": "cut"}]}
        with open(os.path.join(cls.tmp, "transcripts", cls.tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        cls.port = test_backend.free_port()
        cls.proc = test_backend.start_server(cls.tmp, cls.port, os.path.join(cls.tmp, ".runtime"))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, body):
        req = urllib.request.Request("http://127.0.0.1:%d/api/resolve-package" % self.port, method="POST",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=60) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_download(self):
        st, h, body = self.post({"tid": self.tid, "fps": "30", "size": "1080x1920"})
        self.assertEqual(st, 200, body[:300])
        self.assertEqual((h["Content-Type"], h["X-Resolve-Cuts"], h["X-Resolve-Captions"], h["X-Resolve-Handles"]),
                         ("application/zip", "1", "1", "0"))
        p = os.path.join(self.tmp, "dl.zip")
        with open(p, "wb") as f:
            f.write(body)
        with zipfile.ZipFile(p) as z:
            self.assertIn("HTTP_pack/media/clip.mp4", z.namelist())

    def test_bad_input(self):
        st, _, body = self.post({"tid": self.tid, "fps": "29.97"})
        self.assertEqual(st, 400)
        self.assertEqual(json.loads(body)["error"], "resolve_export")
        self.assertEqual(self.post({"tid": "../x"})[0], 400)


if __name__ == "__main__":
    unittest.main()
