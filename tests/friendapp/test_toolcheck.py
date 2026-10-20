"""src/friendapp/toolcheck.py と places の道具の置き方(F3-5)のテスト。本物の道具・文字起こし・ネットは動かさない(偽の run・偽の transcribe)。
リポジトリ直下で: py -3.12 -m unittest src/friendapp/tests/test_toolcheck.py"""
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt.tests import testkit  # noqa: E402
from friendapp import places as P, toolcheck as T  # noqa: E402


class ToolCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "toolcheck-")
        self.paths = {}
        for var, name in (("YTT_FFMPEG", "ffmpeg.exe"), ("YTT_FFPROBE", "ffprobe.exe"), ("YTT_YTDLP", "yt-dlp.exe"), ("YTT_DENO", "deno.exe")):
            p = os.path.join(self.tmp, name)
            with open(p, "wb") as f:
                f.write(b"x")
            self.paths[var] = p
        self.calls = []

    def fake_run(self, cmd, timeout):
        self.calls.append((list(cmd), timeout))
        if "lavfi" in cmd:
            with open(cmd[-1], "wb") as f:
                f.write(b"wav")
            return 0, "", None
        return 0, "ffmpeg version 9.0.2-essentials", None

    def test_each_tool_once_with_timeout(self):
        rows = T.check_tools(self.paths, self.fake_run)
        self.assertEqual([r["name"] for r in rows], ["ffmpeg", "ffprobe", "yt-dlp", "deno"])
        self.assertTrue(all(r["ok"] for r in rows))
        self.assertIn("9.0.2", rows[0]["text"])
        self.assertEqual([c[0][1] for c in self.calls], ["-version", "-version", "--version", "--version"])
        self.assertTrue(all(c[1] == T.TIMEOUT for c in self.calls))

    def test_missing_timeout_exit_and_oserror(self):
        self.assertEqual(T.check_tool("deno", "D", None, "--version", self.fake_run)["text"], "見つかりません")
        r = T.check_tool("a", "A", self.paths["YTT_FFMPEG"], "-version", lambda c, t: (None, "", "timeout"))
        self.assertFalse(r["ok"])
        self.assertIn("答えが返りません", r["text"])
        r = T.check_tool("a", "A", self.paths["YTT_FFMPEG"], "-version", lambda c, t: (3, "boom\nmore", None))
        self.assertFalse(r["ok"])
        self.assertIn("終了コード 3", r["text"])

        def boom(c, t):
            raise OSError(5, "アクセスが拒否されました")
        r = T.check_tool("a", "A", self.paths["YTT_FFMPEG"], "-version", boom)
        self.assertFalse(r["ok"])
        self.assertIn("起動できません", r["text"])
        self.assertEqual(len(T.failed([r])), 1)

    def test_whisper_uses_short_wav_and_cleans_up(self):
        seen = []
        row = T.check_whisper("vulkan", self.tmp, self.paths["YTT_FFMPEG"], os.path.join(self.tmp, "w"), self.fake_run,
                              lambda dev, root, wav: seen.append((dev, root, os.path.isfile(wav))))
        self.assertTrue(row["ok"])
        self.assertEqual(seen, [("vulkan", self.tmp, True)])
        self.assertIn("sine", " ".join(self.calls[0][0]))
        self.assertIn("duration=2", " ".join(self.calls[0][0]))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "w")), [])

    def test_whisper_failure_message_and_no_wav(self):
        def bad(dev, root, wav):
            raise RuntimeError("GPU が見つかりません")
        row = T.check_whisper("cuda", self.tmp, self.paths["YTT_FFMPEG"], os.path.join(self.tmp, "w"), self.fake_run, bad)
        self.assertFalse(row["ok"])
        self.assertIn("GPU が見つかりません", row["text"])
        row = T.check_whisper("vulkan", self.tmp, self.paths["YTT_FFMPEG"], os.path.join(self.tmp, "w"), lambda c, t: (1, "", None), bad)
        self.assertIn("音を作れません", row["text"])

    def test_signature_changes_with_file(self):
        files = list(self.paths.values()) + [os.path.join(self.tmp, "none.exe")]
        a = T.signature(files)
        self.assertEqual(len(a), 4)
        with open(self.paths["YTT_FFMPEG"], "ab") as f:
            f.write(b"more")
        self.assertNotEqual(a, T.signature(files))


class PlacesToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "placestools-")
        self.tools = os.path.join(self.tmp, "tools")

    def put(self, *parts):
        p = os.path.join(self.tools, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x")
        return p

    def test_tool_env_finds_three_levels_down(self):
        deep = self.put("ffmpeg", "ffmpeg-9", "bin", "ffmpeg.exe")
        env = {}
        got = P.tool_env(self.tools, env)
        self.assertEqual(got["YTT_FFMPEG"], deep)
        self.assertIn(os.path.dirname(deep), env["PATH"])

    def test_tool_env_depth_limit_and_stale_value(self):
        self.put("a", "b", "c", "d", "e", "deno.exe")   # 5 段下 = 見ない
        self.assertNotIn("YTT_DENO", P.tool_env(self.tools, {}))
        shallow = self.put("deno", "deno.exe")
        env = {"YTT_DENO": os.path.join(self.tools, "gone", "deno.exe")}   # 無くなったパスは見つけ直す
        self.assertEqual(P.tool_env(self.tools, env)["YTT_DENO"], shallow)
        keep = self.put("mine", "yt-dlp.exe")
        env = {"YTT_YTDLP": keep}
        self.assertNotIn("YTT_YTDLP", P.tool_env(self.tools, env))   # あるうちは変えない

    def test_lay_shallow(self):
        self.put("ffmpeg", "ffmpeg-9", "bin", "ffmpeg.exe")
        self.put("ffmpeg", "ffmpeg-9", "bin", "ffprobe.exe")
        self.put("ffmpeg", "ffmpeg-9", "LICENSE")
        self.put("yt-dlp", "yt-dlp.exe")
        self.put("whisper.cpp-1-vulkan", "bin", "whisper-cli.exe")
        said = []
        self.assertEqual(P.lay_tools_shallow(self.tools, said.append), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.tools, "ffmpeg", "ffmpeg.exe")))
        self.assertTrue(os.path.isfile(os.path.join(self.tools, "ffmpeg", "ffprobe.exe")))
        self.assertFalse(os.path.exists(os.path.join(self.tools, "ffmpeg", "ffmpeg-9")))
        self.assertTrue(os.path.isfile(os.path.join(self.tools, "whisper.cpp-1-vulkan", "bin", "whisper-cli.exe")))   # whisper には触らない
        self.assertEqual(P.lay_tools_shallow(self.tools), 0)   # 2 回目は何もしない
        self.assertEqual(P.lay_tools_shallow(os.path.join(self.tmp, "none")), 0)


if __name__ == "__main__":
    unittest.main()
