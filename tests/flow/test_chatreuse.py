"""ライブで取ったチャットの使い回し(src/flow/chatreuse.py・① fetch.live_to_replay・ワーカーの移す口 ChatFeed._drop。決定 3-117)のテスト。

実行(リポジトリ直下から): python -m unittest tests/flow/test_chatreuse.py -v
"""
import json
import os
import sys
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from flow import chatreuse as CR  # noqa: E402
from pipeline.analyze import fetch, live_excite_worker as EW  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402

T0 = 1_760_000_000.0   # 配信の開始時刻(epoch)


def live_line(ts, mid, text="草"):
    """yt-dlp の live_chat(配信中)の 1 行"""
    r = {"id": mid, "timestampUsec": str(int(ts * 1e6)), "authorExternalChannelId": "u" + mid, "message": {"runs": [{"text": text}]}}
    return json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": r}}}]}, "isLive": True})


def replay_line(sec, mid, text="草"):
    r = {"id": mid, "timestampUsec": "0", "authorExternalChannelId": "u" + mid, "message": {"runs": [{"text": text}]}}
    return json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": r}}}],
                                                "videoOffsetTimeMsec": str(int(sec * 1000))}})


class TestChatReuse(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.keep = os.path.join(self.tmp, CR.KEEP_NAME)
        os.makedirs(self.keep)

    def put(self, gen, secs, offset=0.0, start_id=0):
        """配信の秒 secs のメッセージを、ライブのファイル(通し番号 gen)に書く。絶対時刻 = T0 − offset + 秒"""
        with open(os.path.join(self.keep, "vid00000001.%d.live_chat.json" % gen), "w", encoding="utf-8") as f:
            for i, s in enumerate(secs):
                f.write(live_line(T0 - offset + s, "m%d" % (start_id + i)) + "\n")

    def test_convert_dedupes_across_restarts_and_is_read_like_the_replay(self):
        self.put(0, range(0, 600, 5))
        self.put(1, range(300, 1200, 5), start_id=60)   # 起動し直し: 前のファイルと重なる所は同じ id
        got = CR.prepare(self.tmp, "vid00000001", T0, 12.5, 1213.0)
        self.assertEqual((got["stats"]["count"], got["why"]), (240, ""), got)
        self.assertEqual(got["path"], got["made"])
        with open(got["made"], encoding="utf-8") as f:
            first = json.loads(f.readline())
        self.assertEqual(first["replayChatItemAction"]["videoOffsetTimeMsec"], "12500")   # アーカイブの秒 = 絶対時刻 − t0 + offset
        replay = os.path.join(self.tmp, "replay.json")
        with open(replay, "w", encoding="utf-8") as f:
            for i, s in enumerate(range(0, 1200, 5)):
                f.write(replay_line(s + 12.5, "m%d" % i) + "\n")
        c = CR.compare(got["made"], replay, 1213.0)
        self.assertEqual((c["countLive"], c["countReplay"], c["ratio"], c["corr10"], c["lag"]), (240, 240, 1.0, 1.0, 0))

    def test_gap_or_too_few_is_not_passed(self):
        self.put(0, list(range(0, 300, 5)) + list(range(900, 1200, 5)))   # 600 秒の空き(途切れ)
        got = CR.prepare(self.tmp, "vid00000001", T0, 0.0, 1200.0)
        self.assertIsNone(got["path"])
        self.assertIn("空き", got["why"])
        self.assertTrue(os.path.isfile(got["made"]))   # measure の比べには使える
        self.assertIn("残っていません", CR.prepare(self.tmp, "other000000", T0, 0.0, 1200.0)["why"])

    def test_auto_uses_after_close_compares(self):
        """auto: 比べた記録の新しい 2 本がどれも近ければ使う。1 本でも遠ければ比べるだけに戻る"""
        good, bad = {"ratio": 1.0, "corr10": 0.99, "lag": 0}, {"ratio": 1.0, "corr10": 0.15, "lag": 20}
        self.assertEqual(CR.mode_now(self.tmp), "measure")
        CR.log(self.tmp, dict(good, kind="compare"))
        CR.log(self.tmp, dict(kind="prepare"))
        self.assertEqual(CR.mode_now(self.tmp), "measure")
        CR.log(self.tmp, dict(good, kind="compare"))
        self.assertEqual(CR.mode_now(self.tmp), "on")
        CR.log(self.tmp, dict(bad, kind="compare"))
        self.assertEqual(CR.mode_now(self.tmp), "measure")

    def test_prune_after_keep_days(self):
        self.put(0, [1, 2])
        p = os.path.join(self.keep, "vid00000001.0.live_chat.json")
        os.utime(p, (T0, T0))
        self.assertEqual(CR.prune(self.tmp, now=T0 + CR._retention.KEEP_SEC + 1), 1)
        self.assertFalse(os.path.exists(p))

    def test_worker_moves_instead_of_deleting(self):
        """① のワーカーは渡された置き場所へ移すだけ(書きかけの .part は名前を直す)。置き場所が無ければ今までどおり消す"""
        live = os.path.join(self.tmp, "chat")
        os.makedirs(live)
        for keep, gen in ((self.keep, 0), (None, 1)):
            part = os.path.join(live, "vid00000001.%d.live_chat.json.part" % gen)
            with open(part, "w", encoding="utf-8") as f:
                f.write(live_line(T0, "x") + "\n")
            EW.ChatFeed("vid00000001", "u", live, None, keep_dir=keep)._remove_files(gen)
            self.assertFalse(os.path.exists(part))
        self.assertEqual(sorted(os.listdir(self.keep)), ["vid00000001.0.live_chat.json"])

    def test_given_chat_skips_the_replay(self):
        p = os.path.join(self.tmp, "given.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(replay_line(1, "a") + "\n")
        run = {}

        class Ctl:
            def note(self, *a):
                pass
        fetch.start_chat(Ctl(), run, "vid00000001", self.tmp, 60, given=p)
        run["chat"]["thread"].join(5)
        self.assertEqual((run["chat"]["path"], run["chat"].get("given"), run["chat"]["state"]), (p, True, "done"))


if __name__ == "__main__":
    unittest.main()
