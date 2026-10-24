"""誰の声のカードの行の短い音(src/human/proof/voiceclips.py。10-24 夜): 元の動画から行の前後 1 秒を 16kHz の wav に切り出し、
動画が片付いたあとは、カードの再生の形(media)と、声を覚えるジョブの音(timeline_wav = 文書の時刻に並べた音)を作る。
本物の ffmpeg で 6 秒の音の動画を作って通す(30 秒以下の工程は本物の通し 1 本)。
実行(リポジトリ直下から): python -m unittest tests/human/proof/test_voiceclips.py -v
"""
import os
import subprocess
import sys
import tempfile
import unittest
import wave

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from human.proof import voiceclips as V  # noqa: E402
from ytt import tools, workdata  # noqa: E402


@unittest.skipUnless(tools.find_tool("ffmpeg"), "ffmpeg が無い")
class VoiceClipsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-voiceclips-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._old = workdata.DATA_DIR
        workdata.DATA_DIR = os.path.join(self.tmp, "data")
        self.addCleanup(lambda: setattr(workdata, "DATA_DIR", self._old))
        self.src = os.path.join(self.tmp, "clip.mp4")
        subprocess.run([tools.find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=6",
                        "-c:a", "pcm_s16le", self.src.replace(".mp4", ".wav")], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.src = self.src.replace(".mp4", ".wav")

    def test_make_media_and_timeline(self):
        doc = {"sourcePath": self.src}
        rows = [{"id": "r1", "start": 2.0, "end": 3.5}, {"id": "r2", "start": 0.3, "end": 1.0}, {"id": "../x", "start": 1, "end": 2}]
        self.assertEqual(V.make("abc123def456", doc, rows), 2)   # 形の悪い行 id は作らない
        self.assertEqual(V.make("abc123def456", doc, rows), 0)   # 1 回だけ(作り直さない)
        idx = V.index("abc123def456")
        self.assertEqual(idx["r1"], {"a": 1.0, "b": 4.5})   # 行の前後 PAD 秒
        self.assertEqual(idx["r2"]["a"], 0.0)               # 頭より前は 0 から
        with wave.open(V.clip_path("abc123def456", "r1"), "rb") as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), round(w.getnframes() / w.getframerate(), 1)), (16000, 1, 3.5))
        self.assertEqual(V.media("abc123def456", "r1", 2.0, 3.5), {"url": "api/check/voiceclip?doc=abc123def456&row=r1", "start": 1.0, "end": 2.5})
        self.assertIsNone(V.media("abc123def456", "nope", 0, 1))
        os.remove(self.src)   # 元の動画が片付いた
        self.assertEqual(V.make("abc123def456", doc, [{"id": "r3", "start": 4, "end": 5}]), 0)
        out = os.path.join(self.tmp, "tl.wav")
        self.assertEqual(V.timeline_wav("abc123def456", out, 0.0, 6.0), 2)
        with wave.open(out, "rb") as w:
            frames = w.readframes(w.getnframes())
            self.assertEqual(w.getnframes(), 6 * 16000)
        loud = lambda s: max(abs(int.from_bytes(frames[i:i + 2], "little", signed=True)) for i in range(int(s * 16000) * 2, int((s + 0.1) * 16000) * 2, 2))   # noqa: E731
        self.assertGreater(loud(2.5), 1000)   # 行の所に音がある
        self.assertEqual(loud(5.0), 0)        # 切り出していない所は無音


if __name__ == "__main__":
    unittest.main()
