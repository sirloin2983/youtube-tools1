# -*- coding: utf-8 -*-
"""pipeline/analyze/live_audio.py(配信中の音の控え・11-01 案 C): 足す・切れ目・余白・重なり・欠け・消す、本物の ffmpeg の 1 回で測りと音を両方"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from pipeline.analyze import levels, live_audio as LA  # noqa: E402
from ytt import tools  # noqa: E402


class LiveAudioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-liveaudio-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = os.path.join(self.tmp, "rec")

    def put(self, t, sec, value=0):
        p = os.path.join(self.tmp, "c.pcm")
        with open(p, "wb") as f:
            f.write(bytes([value, 0]) * int(sec * LA.RATE))
        return LA.append(self.folder, t, p)

    def test_cut_margin_gap_overlap_and_drop(self):
        self.assertIsNone(LA.cut(self.folder, 10, 20))   # 控えなし
        self.assertEqual(self.put(100, 12, 1), 12 * LA.BPS)
        self.put(112.1, 12, 2)   # 0.1 秒の隙間 = 続き(無音で埋める)
        self.put(112.1, 12, 9)   # 同じ所をもう一度(ワーカーの起こし直し)= 前の方
        self.put(150, 12, 3)     # 離れた所 = 別のまとまり
        wa, wb, data = LA.cut(self.folder, 105, 115, margin=10)
        self.assertEqual((wa, wb), (100, 124.1))   # 前は控えの頭まで・後ろは控えの終わりまで
        self.assertAlmostEqual(len(data) / LA.BPS, 24.1, places=2)
        self.assertEqual(data[0], 1)
        self.assertEqual(data[int(12.05 * LA.RATE) * 2], 0)   # 隙間は無音
        self.assertEqual(data[int(13 * LA.RATE) * 2], 2)
        self.assertNotIn(9, data[::2])
        self.assertIsNone(LA.cut(self.folder, 120, 155))   # 欠けをまたぐ
        self.assertEqual(LA.cut(self.folder, 151, 160)[:2], (151, 160))   # 余白なし = 区間だけ
        wav = os.path.join(self.tmp, "o.wav")
        LA.write_wav(wav, data)
        with wave.open(wav) as w:
            self.assertEqual((w.getnchannels(), w.getframerate(), w.getnframes()), (1, 16000, len(data) // 2))
        LA.drop(self.folder)
        self.assertEqual(os.listdir(self.folder), [])
        self.assertFalse(LA.enabled({LA.KEEP_ENV: "off"}))

    def test_real_ffmpeg_levels_and_pcm_in_one_run(self):
        ff = tools.find_ffmpeg()
        if not ff:
            self.skipTest("ffmpeg が無い")
        src = os.path.join(self.tmp, "in.ts")
        subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=3:sample_rate=48000", "-ac", "2", "-c:a", "aac", "-f", "mpegts", src],
                       check=True, timeout=60, creationflags=tools.no_window_flags())
        pcm = os.path.join(self.tmp, "o.pcm")
        levels.clear(self.tmp)
        subprocess.run([ff, "-hide_banner", "-nostdin", "-v", "error"] + levels.args(src, pcm), cwd=self.tmp, check=True, timeout=60,
                       creationflags=tools.no_window_flags())
        full, band = levels.collect(self.tmp)
        self.assertGreaterEqual(len(full), 3)
        self.assertAlmostEqual(os.path.getsize(pcm) / LA.BPS, 3.0, delta=0.1)   # 16kHz・モノラル・s16le


if __name__ == "__main__":
    unittest.main()
