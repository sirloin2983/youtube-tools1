"""resolve_export(Resolve パッケージ = cut2resolve の Text+ パックを zip にしたもの)の通し(本物の ffmpeg)と HTTP の口。
残す行の規則・字幕に出さない行・話者の字幕の色・置き先・余白つき素材・入力の誤りは、見本の文書に混ぜて zip を作って確かめる。
受け渡しの JSON と SRT の書式は src/flow/tests/test_pack_ingest.py の通し。
同じ入力から cut2resolve と同じ中身になることは、リポジトリ直下の dev/tests/test_resolve_pack_contract.py が確かめる。"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)   # ツール(editor/)のフォルダ
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が src(ytt・pipeline.pack)を見つけられるように
sys.path.insert(0, os.path.dirname(HERE))   # src(ytt・pipeline・manage の層)

from pipeline.pack import resolve_export  # noqa: E402
from ytt import errors as _errors  # noqa: E402
from ytt import testkit  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class PackageTests(unittest.TestCase):
    """zip の通し。見本: 8 秒・30fps・ずっと音(無音が無い = 行の端は決まった余白 前 3・後 6 コマ)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.source = os.path.join(cls.tmp, "clip.mp4")
        testkit.make_video(cls.source, 8)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # 残す行の規則(カット済・文字が空の行は除き、重なる・接する行はまとめる。すき間は残さない)・字幕に出さない行(noSub: 区間には数えて字幕は作らない)・
    # 話者の字幕の色(文書の sub.color が引数の色より先・組み込みの話者と形の違う色は使わない)を混ぜた文書
    SPEAKERS = [{"id": "S1", "name": "ぺこら", "color": "#888", "sub": {"color": "#ff00aa"}},
                {"id": "other", "name": "ゲーム音声など", "color": "#8a8f98", "builtin": "other", "sub": {"color": "#00FF00"}},
                {"id": "S2", "name": "みこ", "sub": {"color": "red;background:url(x)"}}]
    SEGS = [{"id": "a", "start": 0, "end": 2, "text": "残す", "speaker": "S1"},
            {"id": "b", "start": 1.5, "end": 4, "text": "NPC のセリフ", "speaker": "other", "noSub": True},
            {"id": "c", "start": 4, "end": 5, "text": "切る", "cutState": "cut"},
            {"id": "d", "start": 5, "end": 5.5, "text": "  "},
            {"id": "e", "start": 6, "end": 7, "text": "後", "speaker": "S2", "cutState": "keep"},
            {"id": "f", "start": 6.5, "end": 8, "text": "重なる"}]

    def doc(self, source=None, **kw):
        d = {"title": "テスト", "sourcePath": source or self.source, "whole": True, "duration": 8,
             "speakers": [dict(s) for s in self.SPEAKERS], "segments": [dict(g) for g in self.SEGS]}
        d.update(kw)
        return d

    def package(self, doc, *a, **kw):
        path, temp_dir, info = resolve_export.create_package(doc, *a, **kw)
        self.addCleanup(shutil.rmtree, temp_dir, True)
        z = zipfile.ZipFile(path)
        self.addCleanup(z.close)
        return z, info

    def ip(self, z):
        """パックの Lua に埋め込んだ計画(区間・字幕)"""
        from pipeline.pack import resolve_textplus
        return resolve_textplus.read_script_plan(z.read("テスト_pack/create_resolve_textplus_project.lua").decode("utf-8"))

    def test_zip_run(self):
        z, info = self.package(self.doc(), speaker_colors={"ぺこら": "#7EC2FE", "みこ": "#FF8FDF"})
        names = set(z.namelist())
        self.assertEqual({n.split("/")[0] for n in names}, {"テスト_pack"})          # 展開するとフォルダが1つ
        rel = {n.split("/", 1)[1] for n in names}
        # 最小限(④): 動画(直下)・Lua・雛形・登録用の ps1/bat だけ(EDL・SRT・cut-plan.json・textplus-import.json・友人へ.txt は入れない)
        self.assertEqual({"clip.mp4", "create_resolve_textplus_project.lua", "install_resolve_textplus_script.ps1",
                          "ResolveにText+スクリプトを登録.bat", "textplus-template.drb"}, {n for n in rel if not n.endswith("/")}, rel)
        self.assertEqual((info["cuts"], info["captions"], info["media"]["hasEditHandles"]), (2, 3, False))
        ip = self.ip(z)
        # 残す区間: a・b(字幕に出さない行も区間に数える)= 0〜4 秒・e・f = 6〜8 秒。端は決まった余白で広げる(カット済の c と動画の終わりは越えない)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(0, 120), (177, 240)])
        self.assertEqual([c["text"] for c in ip["captions"]], ["残す", "後", "重なる"])
        self.assertEqual([c.get("fill") for c in ip["captions"]], [[1.0, 0.0, 0.6667, 1.0], [1.0, 0.5608, 0.8745, 1.0], None])
        self.assertEqual(ip["target"], {"fps": 30, "width": 1080, "height": 1920})
        lua = z.read("テスト_pack/create_resolve_textplus_project.lua").decode("utf-8")
        self.assertNotIn("CreateProject", lua)                     # プロジェクトは手で作る(スクリプトは作らない)
        self.assertNotIn(self.tmp, lua)                            # PC のパスを入れない
        z, _ = self.package(self.doc(), row_edge=False)            # 行の端を広げなければ、残す行の時間そのまま
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in self.ip(z)["cuts"]], [(0, 120), (180, 240)])
        z, _ = self.package(self.doc(), "60", "1920x1080")         # 横の置き先
        self.assertEqual(self.ip(z)["target"], {"fps": 60, "width": 1920, "height": 1080})

        # 切り抜きスタジオの余白つき素材(前後10秒)があれば、それを入れて、区間を余白の分だけ後ろへずらす
        edit, side = os.path.join(self.tmp, "clip_edit.mp4"), os.path.join(self.tmp, "clip.edit.json")
        testkit.make_video(edit, 28)
        with open(side, "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/edit-media/v1", "media": "clip_edit.mp4", "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}, f)
        try:
            z, info = self.package(self.doc(segments=[dict(self.SEGS[0], end=2), dict(self.SEGS[2], start=2, end=4), {"id": "s3", "start": 4, "end": 8,
                                                                                                                       "text": "もう一度残す"}]),
                                   row_edge=False)
        finally:
            os.unlink(side)
            os.unlink(edit)
        self.assertEqual((info["media"]["hasEditHandles"], info["media"]["file"]), (True, "clip_edit.mp4"))
        ip = self.ip(z)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(300, 360), (420, 540)])
        self.assertEqual([c["startFrame"] for c in ip["captions"]], [0, 60])
        self.assertEqual(ip["sourceTimeline"], {"startFrame": 0, "endFrame": 840})
        self.assertIn("テスト_pack/clip_edit.mp4", z.namelist())

        # 入力の誤り: 断って、一時フォルダを残さない
        tmp_root = tempfile.gettempdir()
        before = {n for n in os.listdir(tmp_root) if n.startswith("resolve-package-")}
        for args, msg in (((self.doc(), "29.97"), "fps"), ((self.doc(), "30", "12x"), "解像度"),
                          ((self.doc(source=os.path.join(self.tmp, "none.mp4")),), "元の動画"),
                          ((self.doc(segments=[{"id": "a", "start": 1, "end": 2, "text": "x", "cutState": "cut"}]),), "残す行")):
            with self.subTest(msg=msg), self.assertRaises(_errors.ResolveExportError) as cm:
                resolve_export.create_package(*args)
            self.assertIn(msg, str(cm.exception))
        after = {n for n in os.listdir(tmp_root) if n.startswith("resolve-package-")}
        self.assertEqual(after - before, set())


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class HttpTests(unittest.TestCase):
    """/api/resolve-package(一時フォルダに写した serve.py から、パックの部品 pipeline.pack を YTT_CORE_DIR(src)で見つける)"""

    @classmethod
    def setUpClass(cls):
        import test_backend
        cls.tmp = tempfile.mkdtemp()
        cls.video = os.path.join(cls.tmp, "clip.mp4")
        testkit.make_video(cls.video, 8)
        os.makedirs(os.path.join(cls.tmp, "transcripts"))
        cls.tid = "0123456789ab"
        doc = {"id": cls.tid, "title": "HTTP", "sourcePath": cls.video, "whole": True, "duration": 8, "updatedAt": 1,
               "segments": [{"id": "s1", "start": 1, "end": 3, "text": "こんにちは"}, {"id": "s2", "start": 3, "end": 5, "text": "x", "cutState": "cut"}]}
        testkit.write_json(os.path.join(cls.tmp, "transcripts", cls.tid + ".json"), doc)
        cls.port = testkit.free_port()
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

    def test_download_and_bad_input(self):
        st, h, body = self.post({"tid": self.tid, "fps": "30", "size": "1080x1920"})
        self.assertEqual(st, 200, body[:300])
        self.assertEqual((h["Content-Type"], h["X-Resolve-Cuts"], h["X-Resolve-Captions"], h["X-Resolve-Handles"]),
                         ("application/zip", "1", "1", "0"))
        p = os.path.join(self.tmp, "dl.zip")
        with open(p, "wb") as f:
            f.write(body)
        with zipfile.ZipFile(p) as z:
            self.assertIn("HTTP_pack/clip.mp4", z.namelist())
        st, _, body = self.post({"tid": self.tid, "fps": "29.97"})
        self.assertEqual(st, 400)
        self.assertEqual(json.loads(body)["error"], "resolve_export")
        self.assertEqual(self.post({"tid": "../x"})[0], 400)       # 文書の id でパスの外を指させない


if __name__ == "__main__":
    unittest.main()
