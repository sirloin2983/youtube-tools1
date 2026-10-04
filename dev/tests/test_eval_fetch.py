"""dev/eval_fetch.py(編集前の定点を配信から取得する道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_fetch.py

評価用のフォルダは一時フォルダに作る。yt-dlp・ffmpeg は呼ばない(配信の一覧・取得・無音の判定は差し替える)。ネットワークは使わない。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import eval_fetch as F  # noqa: E402
from ytt_core import schemas  # noqa: E402

DAY = 86400
SINCE = 1790000000          # テストの「この日以降」
MEMBERS = [{"name": "大空スバル", "channel": "UC" + "a" * 22, "keys": ["大空すばる"]},
           {"name": "さくらみこ", "channel": "UC" + "b" * 22, "keys": ["さくらみこ", "みこち"]},
           {"name": "常闇トワ", "channel": "", "keys": ["常闇とわ"]}]


def ent(n, title="雑談", dur=7200, ts=SINCE + DAY, status="was_live"):
    return {"id": ("v%010d" % n), "title": title, "duration": dur, "timestamp": ts, "live_status": status}


class PureTest(unittest.TestCase):
    def test_usable(self):
        self.assertTrue(F.usable(ent(1), SINCE))
        self.assertFalse(F.usable(ent(1, ts=SINCE - 1), SINCE))                 # 古い
        self.assertFalse(F.usable(ent(1, dur=600), SINCE))                      # 短い
        self.assertFalse(F.usable(ent(1, dur=None, status="is_live"), SINCE))   # 配信中
        self.assertFalse(F.usable(ent(1, status="is_upcoming"), SINCE))
        self.assertFalse(F.usable(ent(1, title="【歌枠】うたう"), SINCE))
        self.assertFalse(F.usable({**ent(1), "id": "bad id"}, SINCE))           # ID の形が違う
        self.assertFalse(F.usable({**ent(1), "timestamp": None}, SINCE))        # 日付が分からない

    def test_pick_start_inside_and_stable(self):
        for attempt in (0, 1):
            s = F.pick_start("1", "v0000000001", 7200, 40, attempt)
            self.assertGreaterEqual(s, 720)
            self.assertLessEqual(s + 40, 7200 - 720)
        self.assertEqual(F.pick_start("1", "v0000000001", 7200, 40), F.pick_start("1", "v0000000001", 7200, 40))
        self.assertNotEqual(F.pick_start("1", "v0000000001", 7200, 40, 0), F.pick_start("1", "v0000000001", 7200, 40, 1))

    def test_collab_and_names(self):
        self.assertTrue(F.is_collab("みこちと一緒にマイクラ", "大空スバル", MEMBERS))
        self.assertTrue(F.is_collab("オフコラボ", "大空スバル", MEMBERS))
        self.assertFalse(F.is_collab("【大空スバル】朝活", "大空スバル", MEMBERS))
        self.assertEqual(F.fmt_pos(6815), "1h53m35s")
        self.assertEqual(F.fmt_ts(3725.5), "1:02:05.500")
        self.assertEqual(F.clip_name("ラプラス・ダークネス", "abcdefghijk", 65), "配信_ラプラス・ダークネス_abcdefghijk_0h01m05s.mp4")

    def test_make_plan(self):
        listings = {"大空スバル": [ent(1), ent(2, "みこちとコラボ"), ent(3), ent(4, ts=SINCE - DAY)],
                    "さくらみこ": [ent(11), ent(11), ent(12, dur=300)]}
        items = F.make_plan(MEMBERS, listings, minutes=2, clip_sec=40, since_ts=SINCE)   # 3 区間
        self.assertEqual([(i["member"], i["slot"]) for i in items].count(("さくらみこ", 0)), 1)
        self.assertEqual(len(items), 3)
        sub = [i for i in items if i["member"] == "大空スバル"]
        self.assertFalse(sub[0]["candidates"][0]["collab"])                      # 1 巡目はひとりの配信
        self.assertEqual(sub[1]["candidates"][0]["id"], "v0000000002")           # 2 巡目はコラボを先に
        ids = [i["candidates"][0]["id"] for i in items]
        self.assertEqual(len(ids), len(set(ids)))                                # 1 つの配信から 1 区間
        self.assertNotIn("v0000000004", json.dumps(items))                       # 古い配信は候補にも入らない
        self.assertEqual(items, F.make_plan(MEMBERS, listings, 2, 40, SINCE))    # 何度作っても同じ
        many = F.make_plan(MEMBERS, listings, minutes=60, clip_sec=40, since_ts=SINCE)
        self.assertEqual(len(many), 4)                                           # 配信が尽きたら止まる(スバル 3 + みこ 1)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "評価用データ")
        os.makedirs(self.root)
        for name, target in (("load_members", lambda path=None: MEMBERS), ("default_since", lambda root: "2026-09-22")):
            p = mock.patch.object(F, name, target)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(F.normalize, "probe", lambda path: {"duration": 40.0})
        p.start()
        self.addCleanup(p.stop)
        self.ts = 1790500000

    def run_main(self, fn, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(F.time, "sleep", lambda s: None):
            args = mock.Mock(root=self.root, redo="--redo" in argv, since=None, minutes=2.0, clip_sec=40, seed="1", limit=0)
            for k, v in argv.items() if isinstance(argv, dict) else ():
                setattr(args, k, v)
            code = fn(args)
        return code, out.getvalue()

    def plan(self, **kw):
        listings = {MEMBERS[0]["channel"]: [ent(1, ts=self.ts), ent(2, ts=self.ts), ent(3, ts=self.ts)], MEMBERS[1]["channel"]: [ent(11, ts=self.ts)]}
        return self.run_main(lambda a: F.cmd_plan(a, lister=lambda ch: listings.get(ch, [])), kw)

    def test_plan_fetch_resume(self):
        code, out = self.plan()
        self.assertEqual(code, 0, out)
        plan = F.read_plan(self.root)
        self.assertEqual((plan["since"], len(plan["items"])), ("2026-09-22", 3))
        code, out = self.plan()
        self.assertIn("すでに一覧があります", out)

        calls = []

        def fetcher(vid, start, clip_sec, out_path, work):
            calls.append(vid)
            if vid == plan["items"][0]["candidates"][0]["id"]:
                return "メンバー限定です"                                        # 1 つ目の候補は取れない → 次の候補へ
            with open(out_path, "wb") as fh:
                fh.write(b"x")
            return None

        silent = iter([0.9, 0.1, 0.1, 0.1, 0.1])                                # 最初に取れた区間は無音ばかり → 同じ配信の別の所
        code, out = self.run_main(lambda a: F.cmd_fetch(a, fetcher=fetcher, silence=lambda p: next(silent)), {"limit": 1})
        self.assertEqual(code, 0, out)
        plan1 = F.read_plan(self.root)
        done = [i for i in plan1["items"] if i.get("done")]
        self.assertEqual(len(done), 1)                                           # --limit 1
        d = done[0]["done"]
        self.assertNotEqual(d["id"], plan["items"][0]["candidates"][0]["id"])
        self.assertEqual(calls.count(d["id"]), 2)                                # 無音で 1 回取り直した
        staging = os.path.join(self.root, F.eval_split.STAGING)
        self.assertEqual([n for n in os.listdir(staging) if n.endswith(".mp4")], [d["file"]])
        clip, warn = schemas.load_clip_file(schemas.find_clip_path(os.path.join(staging, d["file"])))
        self.assertIsNone(warn)
        self.assertEqual((clip["source"]["videoId"], clip["range"]["start"], clip["tool"]["name"]), (d["id"], float(d["start"]), "eval-fetch"))

        code, out = self.run_main(lambda a: F.cmd_fetch(a, fetcher=fetcher, silence=lambda p: 0.0), {})
        plan2 = F.read_plan(self.root)
        got = [i["done"]["id"] for i in plan2["items"] if i.get("done")]
        self.assertEqual(len(got), len(set(got)))                                # 同じ配信を 2 回使わない
        self.assertEqual(len(got) + sum(1 for i in plan2["items"] if i.get("failed")), 3)
        n = len(calls)
        code, out = self.run_main(lambda a: F.cmd_fetch(a, fetcher=fetcher, silence=lambda p: 0.0), {})
        self.assertEqual(len(calls), n)                                          # もう一度流しても取り直さない

        code, out = self.plan(redo=True)
        self.assertEqual(code, 2)                                                # 取得を始めたあとは作り直せない

    def test_fetch_without_plan(self):
        code, out = self.run_main(F.cmd_fetch, {})
        self.assertEqual(code, 2)

    def test_default_since_from_split_plan(self):
        mock.patch.stopall()
        files = [{"name": "a", "date": "26-08-21"}, {"name": "b", "date": "26-09-21"}, {"name": "c", "date": "25-1015"}, {"name": "d", "date": "26-02-07,08,10"}]
        with open(os.path.join(self.root, F.eval_split.PLAN_NAME), "w", encoding="utf-8") as fh:
            json.dump({"schema": F.eval_split.SCHEMA, "files": files}, fh)
        self.assertEqual(F.default_since(self.root), "2026-09-22")
        self.assertIsNone(F.default_since(self.tmp.name))


if __name__ == "__main__":
    unittest.main()
