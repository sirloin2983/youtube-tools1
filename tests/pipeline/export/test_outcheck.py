"""書き出しのあとの自動の点検(① pipeline/export/outcheck)のテスト。本物の ffmpeg で合成した壊れた動画(黒いコマ・無音・割れ・声の途中で切れる・長さ違い)を点検する。
ffmpeg が無い PC では飛ばす。動画は再生しない(音は出ない)。

    py -3.12 -m unittest tests/pipeline/export/test_outcheck.py
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
sys.path.insert(0, SRC)
from pipeline.export import outcheck as OC  # noqa: E402
from ytt import tools  # noqa: E402

FFMPEG = tools.find_tool("ffmpeg")
SPEECH = "sine=f=300:d=4,volume=-12dB,afade=t=in:d=0.4,afade=t=out:st=3.6:d=0.4"   # 頭と末が静かな「声」


def make(path, video, audio):
    """lavfi の映像と音(None = 音なし)から 30fps の mp4 を作る"""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        cmd += ["-f", "lavfi", "-i", audio]
    cmd += ["-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", "-shortest"] + (["-c:a", "aac"] if audio else []) + [path]
    r = tools.run(cmd, timeout=60)
    assert r.code == 0, r.err_lines()


class TestJudge(unittest.TestCase):
    def test_kinds(self):
        kinds = lambda out: [x["kind"] for x in out]
        self.assertEqual(OC.judge(10.0, 10.2, True, -20.0, -3.0, []), [])
        self.assertEqual(kinds(OC.judge(4.0, 10.0, True, -20.0, -3.0, [])), ["length"])
        self.assertEqual(kinds(OC.judge(10.0, None, False, None, None, [])), ["silent"])
        self.assertEqual(kinds(OC.judge(10.0, None, True, -70.0, -40.0, [])), ["silent"])
        self.assertEqual(kinds(OC.judge(10.0, None, True, -15.0, 0.0, [])), ["clip"])
        self.assertEqual(kinds(OC.judge(10.0, None, True, -20.0, -3.0, [(4.0, 4.6)])), [])          # 途中の短い黒は知らせない
        self.assertEqual(kinds(OC.judge(10.0, None, True, -20.0, -3.0, [(0.0, 0.6)])), ["black"])  # 頭の黒は短くても


@unittest.skipUnless(FFMPEG, "ffmpeg が無い")
class TestRealFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="outcheck_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_one(self, name, video, audio, expected=None):
        p = os.path.join(self.tmp, name + ".mp4")
        make(p, video, audio)
        self.res = OC.check(p, expected, FFMPEG)   # 音の有無は点検が自分で見る
        return [x["kind"] for x in self.res["issues"]]

    def test_broken_files(self):
        self.assertEqual(self.run_one("good", "testsrc=s=320x240:r=30:d=4", SPEECH, 4.0), [])
        self.assertLess(max(self.res["edge"].values()), 0.3)                                     # 頭と末が静か
        self.assertEqual(self.run_one("short", "testsrc=s=320x240:r=30:d=4", SPEECH, 10.0), ["length"])
        self.assertEqual(self.run_one("black", "color=c=black:s=320x240:r=30:d=4", SPEECH), ["black"])
        self.assertEqual(self.run_one("silent", "testsrc=s=320x240:r=30:d=4", "anullsrc=r=48000:cl=mono:d=4"), ["silent"])
        self.assertEqual(self.run_one("noaudio", "testsrc=s=320x240:r=30:d=4", None), ["silent"])
        self.assertEqual(self.run_one("loud", "testsrc=s=320x240:r=30:d=4", "sine=f=300:d=4,volume=24dB,afade=t=in:d=0.4,afade=t=out:st=3.6:d=0.4"), ["clip"])
        self.assertEqual(self.run_one("cut", "testsrc=s=320x240:r=30:d=4", "sine=f=300:d=4,volume=-12dB"), [])   # 声の途中の切れは値だけ残す(知らせない)
        self.assertGreater(min(self.res["edge"].values()), 0.8)

    def test_switch_off(self):
        p = os.path.join(self.tmp, "x.mp4")
        make(p, "testsrc=s=320x240:r=30:d=2", SPEECH)
        OC.OUTCHECK = False
        self.addCleanup(setattr, OC, "OUTCHECK", True)
        self.assertIsNone(OC.check(p, 2.0, FFMPEG))


if __name__ == "__main__":
    unittest.main()
