"""動画ファイルの依頼(映像 2 本の mkv・長い題)の確認用の動画が、URL の依頼と同じ道で作られ、受け取るの media が読む所に置かれること。
本物の ffmpeg・ffprobe を使う(無ければ飛ばす)。② の待ち行列は偽物。画面・音は出さない。
リポジトリ直下で: py -3.12 -m unittest src/friendapp/tests/test_file_preview.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from friendapp import engine, inbox  # noqa: E402
from ytt import fsio, normalize, tools  # noqa: E402

FFMPEG, FFPROBE = tools.find_tool("ffmpeg"), tools.find_tool("ffprobe")
RID = "20261016-100000-aaaaaa"


class FakeQueue:
    def set_finished_hook(self, fn):
        pass

    def status(self):
        return {"idle": True, "runs": []}

    def history(self, limit=None):
        return {"runs": []}

    def close(self):
        pass


def two_video_mkv(path, fps1=60):
    """映像 2 本(1 本目 1280x720、2 本目 640x360)・音声 1 本の 3 秒の mkv"""
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=1280x720:r=%d:d=3" % fps1,
                    "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-f", "lavfi", "-i", "sine=d=3", "-map", "0:v", "-map", "1:v", "-map", "2:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", fsio.long_path(path)], check=True, creationflags=tools.no_window_flags())


def probe(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-of", "json", "-show_entries", "stream=codec_type,codec_name,pix_fmt,height:format=format_name,duration",
                          fsio.long_path(path)], stdout=subprocess.PIPE, check=True, creationflags=tools.no_window_flags()).stdout
    return json.loads(out.decode("utf-8"))


def atoms(path):
    """mp4 の先頭の箱の名前の並び(faststart = moov が mdat より前)"""
    names, pos = [], 0
    with open(fsio.long_path(path), "rb") as f:
        while len(names) < 8:
            f.seek(pos)
            head = f.read(8)
            if len(head) < 8:
                break
            size = int.from_bytes(head[:4], "big")
            names.append(head[4:].decode("latin1"))
            if size < 8:
                break
            pos += size
    return names


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg・ffprobe が要る")
class FilePreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="friend-fprev-")
        self.addCleanup(shutil.rmtree, fsio.long_path(self.tmp), True)
        self.places = {"data": os.path.join(self.tmp, "data"), "friend": os.path.join(self.tmp, "friend"), "studio": None}
        os.makedirs(self.places["friend"])
        self.cases = os.path.join(self.tmp, "cases")
        self.ib = inbox.Inbox(os.path.join(self.tmp, "inbox.json"), os.path.join(self.tmp, "outbox"), lambda: os.path.join(self.tmp, "save"), lambda: self.cases)

    def deliver(self, stem, normalized=False, fps1=60):
        """偽の ②: 依頼のフォルダ/<題>.mkv(normalized なら 30fps にそろえた <題>.mp4)と、その隣の <題>_pack/(動画の写し)-> パックのフォルダ"""
        folder = os.path.join(self.cases, "依頼", "20261016_" + stem + "_aaaaaa")
        os.makedirs(fsio.long_path(folder))
        src = os.path.join(folder, stem + ".mkv")
        two_video_mkv(src, fps1)
        if normalized:
            dst = os.path.join(folder, stem + ".mp4")
            normalize.normalize(src, dst)
            os.unlink(fsio.long_path(src))
            src = dst
        pack = os.path.join(folder, stem + "_pack")
        os.makedirs(fsio.long_path(pack))
        shutil.copyfile(fsio.long_path(src), fsio.long_path(os.path.join(pack, os.path.basename(src))))
        return pack

    def run_engine(self, pack):
        self.ib.add(RID, {}, {}, run_id="r1")
        eng = engine.Engine(self.places, self.ib, queue_factory=lambda *a, **k: FakeQueue())
        self.addCleanup(eng.close)
        run = types.SimpleNamespace(id="r1", state="done", error="", result_path=None, all_packs=lambda: [pack])
        orig = engine._outbox.build
        engine._outbox.build = lambda *a, **k: None   # 送り返しの zip は作らない
        self.addCleanup(setattr, engine._outbox, "build", orig)
        eng.after_run(run)
        eng.make_previews(RID)
        return self.ib.row(RID)

    def check_preview(self, r):
        self.assertEqual(r["state"], "arrived")
        p = r["packs"][0]
        path = self.ib.pack_preview(RID, p["name"])   # 受け取るの media?id=&name= が読む所
        self.assertTrue(path and os.path.isfile(path), "確認用の動画が置かれていない")
        self.assertEqual(os.path.dirname(path), os.path.join(self.places["friend"], "previews"))   # server.py の media が許す所
        info = probe(path)
        kinds = [s["codec_type"] for s in info["streams"]]
        self.assertEqual(kinds, ["video", "audio"])   # 映像は 1 本だけ(0:v:0)
        v, a = info["streams"]
        self.assertEqual((v["codec_name"], v["pix_fmt"], v["height"], a["codec_name"]), ("h264", "yuv420p", 480, "aac"))
        self.assertIn("mp4", info["format"]["format_name"])
        self.assertLess(atoms(path).index("moov"), atoms(path).index("mdat"))   # faststart
        self.assertAlmostEqual(float(info["format"]["duration"]), 3.0, delta=0.3)
        self.assertAlmostEqual(p["seconds"], 3.0, delta=0.3)
        return path

    def test_two_video_track_mkv(self):
        """映像 2 本の mkv のまま(30fps 済みで作り直しが無かったとき)でも、1 本目で作る"""
        self.check_preview(self.run_engine(self.deliver("動画 (1)", fps1=30)))

    def test_two_video_track_mkv_normalized(self):
        """30fps にそろえた mp4(映像は 1 本目だけ)"""
        self.check_preview(self.run_engine(self.deliver("動画 (2)", normalized=True)))

    @unittest.skipUnless(os.name == "nt", "Windows の長いパスの話")
    def test_long_title_path_over_260(self):
        """題が長く、パックのパスが 260 文字を超えても作れる(題が 2 回入る = 友人の動画ファイルの依頼)"""
        pack = self.deliver("長い題の配信アーカイブ" * 6, fps1=30)
        self.assertGreater(len(os.path.join(pack, "長い題の配信アーカイブ" * 6 + ".mkv")), 260)
        self.check_preview(self.run_engine(pack))


if __name__ == "__main__":
    unittest.main()
