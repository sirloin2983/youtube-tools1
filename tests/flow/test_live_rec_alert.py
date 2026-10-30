# -*- coding: utf-8 -*-
"""録画の知らせ(src/flow/live_rec_alert.py。10-30): 始まらない(a)・途中で止まって戻らない(b)・欠けが大きい(c)。
友人の依頼の録画は 出力 に .失敗.txt 1 つ + 調子、自分の録画は調子だけ。同じ出来事で 2 回置かない。
出力 はテストの一時フォルダ(本物の Dropbox へは置かない)"""
import glob
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")   # tests -> flow -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from flow import live_failures, live_rec_alert as RA  # noqa: E402
from friendapp import inbox as _inbox, progress as _progress  # noqa: E402
from ytt import recproto  # noqa: E402

T0 = 1793340000.0
RID = "20261030-150000-abcdef"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def rec(rid="20261030-150000-r1", active=False, **kw):
    r = {"recorder": "local", "id": rid, "title": "テストの配信", "active": active, "state": "recording" if active else "ended",
         "message": "", "endKind": None if active else "source", "segments": 0 if active else 900, "created": T0 - 3600,
         "endedAt": None if active else T0 + 60, "lastPdt": T0 + 30, "holeSec": None if active else 0.0, "holes": None if active else []}
    r.update(kw)
    return r


class TestRecAlerts(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "rec-alert-")
        self.outbox = os.path.join(self.tmp, "Dropbox", "依頼", "出力")   # 受付の Dropbox の代わり(親だけある = outbox_ok)
        os.makedirs(os.path.dirname(self.outbox))
        self.clock = Clock(T0)
        self.reqs = {}
        self.logs = []
        self.ra = self.new()
        self.ra.tick([], ())   # 入れた時刻(since)を T0 に

    def new(self):
        return RA.RecAlerts(os.path.join(self.tmp, "live"), lambda rc, r: self.reqs.get((rc, r)), log=self.logs.append, clock=self.clock)

    def friend(self, rid="20261030-150000-r1"):
        self.reqs[("local", rid)] = {"rid": RID, "deliverDir": self.outbox, "title": "テストの配信"}

    def txts(self):
        return sorted(glob.glob(os.path.join(self.outbox, "*.失敗.txt")))

    def read(self, p):
        with open(p, encoding="utf-8-sig") as f:
            return f.read()

    def records(self):
        return [f for f in self.ra.failures() if f["kind"] == "record"]

    def tick(self, *recs, down=()):
        self.clock.t += 30
        return self.ra.tick(list(recs), set(down))

    def test_a_not_started_friend_once(self):
        """a: 1 つも録れないまま終わった友人の依頼の録画 -> .失敗.txt 1 つ(友人のアプリでは失敗 liveNoRec・やり直さない)+ 調子。2 回目は置かない"""
        self.friend()
        r = rec(segments=0, endKind="notStarted", message="配信が始まらないので待つのをやめました")
        self.assertEqual(self.tick(r), 1)
        self.assertEqual(self.tick(r), 0)
        self.assertEqual(self.new().tick([r], set()), 0)   # 入口を起き直しても(覚えはファイル)
        files = self.txts()
        self.assertEqual(len(files), 1)
        self.assertTrue(os.path.basename(files[0]).startswith(RID + "__"))   # 友人のアプリが依頼 id を読む形 <依頼 id>__<題>
        text = self.read(files[0])
        self.assertTrue(text.startswith(RA.NO_REC_HEAD), text)
        self.assertIn("テストの配信", text)
        self.assertIn("配信が始まらないので待つのをやめました", text)
        cls = _progress.classify(text, "live")
        self.assertEqual((cls["code"], cls["retry"]), ("liveNoRec", False))
        f = self.records()
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["event"], f[0]["recording"], f[0]["kindLabel"]), ("a", r["id"], "録画"))
        self.assertIn("友人の Dropbox に知らせを置きました", f[0]["text"])

    def test_a_own_recording_health_only(self):
        """自分で始めた録画(依頼でない)は友人の Dropbox に置かない・調子だけ"""
        r = rec(segments=0, state="error", endKind=None, message="YouTube に bot と判定されて録画できません")   # 古い録画元(印なし)でも
        self.assertEqual(self.tick(r), 1)
        self.assertEqual(self.txts(), [])
        f = self.records()
        self.assertEqual([x["event"] for x in f], ["a"])
        self.assertNotIn("友人", f[0]["text"])
        live_failures.KIND_LABELS["record"]   # 種類の名前がある

    def test_b_stopped_midway_friend(self):
        """b: 録れた後に bot と判定され続けて終えた -> 友人の行の知らせ(REC_NOTE_HEAD)1 つ + 調子。欠けが小さければ c は出さない"""
        self.friend()
        r = rec(endKind="blocked", message="YouTube に bot と判定されたまま録画できなくなったので、録画を終えました", holeSec=12.0)
        self.assertEqual(self.tick(r), 1)
        self.assertEqual(self.tick(r), 0)
        files = self.txts()
        self.assertEqual(len(files), 1)
        text = self.read(files[0])
        self.assertTrue(text.startswith(RA.REC_NOTE_HEAD), text)
        self.assertIn(RA.clock_text(r["lastPdt"]), text)   # どこから録れていないか
        self.assertIn("届くパックが少なくなります", text)
        self.assertEqual([x["event"] for x in self.records()], ["b"])

    def test_b_recorder_no_answer(self):
        """b: 録画中だった録画の録画元が NOANSWER_SEC 答えないまま -> 1 回。戻って終わっても b を重ねない"""
        self.friend()
        self.assertEqual(self.tick(rec(active=True)), 0)
        self.assertEqual(self.tick(down=["local"]), 0)
        self.clock.t += RA.NOANSWER_SEC
        self.assertEqual(self.tick(down=["local"]), 1)
        self.assertEqual(self.tick(down=["local"]), 0)
        self.assertEqual(self.tick(rec(endKind="crash", state="error")), 0)   # 戻ってきて、思わぬエラーで終わっていた: 同じ b
        self.assertEqual(len(self.txts()), 1)
        self.assertIn("録画元が", self.read(self.txts()[0]))

    def test_c_large_holes_friend(self):
        """c: 終わった録画の欠けの合計が GAP_SEC 以上 -> 1 回(どの時間が欠けたかを書く)。ふつうに終わった録画でも"""
        self.friend()
        holes = [{"from": recproto.epoch_iso(T0 - 1800), "to": recproto.epoch_iso(T0 - 1500), "sec": 300.0},
                 {"from": recproto.epoch_iso(T0 - 900), "to": recproto.epoch_iso(T0 - 840), "sec": 60.0}]
        r = rec(endKind="idle", holeSec=360.0, holes=holes)
        self.assertEqual(self.tick(r), 1)
        self.assertEqual(self.tick(r), 0)
        files = self.txts()
        self.assertEqual(len(files), 1)
        text = self.read(files[0])
        self.assertTrue(text.startswith(RA.REC_NOTE_HEAD), text)
        self.assertIn("約 6 分", text)
        self.assertIn(RA.clock_text(T0 - 1800), text)
        self.assertEqual([x["event"] for x in self.records()], ["c"])

    def test_b_and_c_are_separate_files(self):
        """b と c が両方あれば、出来事ごとに 1 つずつ(名前が重ならない)"""
        self.friend()
        r = rec(endKind="disk", state="error", message="空き容量が足りないので録画を止めました", holeSec=600.0,
                holes=[{"from": recproto.epoch_iso(T0 - 1200), "to": recproto.epoch_iso(T0 - 600), "sec": 600.0}])
        self.assertEqual(self.tick(r), 2)
        self.assertEqual(len(self.txts()), 2)
        self.assertEqual(sorted(x["event"] for x in self.records()), ["b", "c"])

    def test_quiet_cases(self):
        """知らせない: ふつうの終わり(欠けが小さい)・データが来ないまま終わった(idle)・手で止めた・入れる前に終わった・録画中"""
        self.friend()
        self.friend("20261030-150000-r2")
        self.friend("20261030-150000-r3")
        self.friend("20261030-150000-r4")
        recs = [rec(), rec("20261030-150000-r2", endKind="idle", holeSec=40.0),
                rec("20261030-150000-r3", endKind="stopped", state="stopped", segments=0),
                rec("20261030-150000-r4", endKind="crash", state="error", endedAt=T0 - 600), rec("20261030-150000-r5", active=True)]
        self.assertEqual(self.tick(*recs), 0)
        self.assertEqual(self.txts(), [])
        self.assertEqual(self.records(), [])

    def test_outbox_missing_then_resend(self):
        """Dropbox のフォルダが見えない間は置かず(調子にはそう出す)、見えたら 1 回だけ置き直す"""
        self.reqs[("local", "20261030-150000-r1")] = {"rid": RID, "deliverDir": os.path.join(self.tmp, "無い", "出力")}
        r = rec(segments=0, endKind="notStarted")
        self.assertEqual(self.tick(r), 1)
        self.assertIn("置けていません", self.records()[0]["text"])
        os.makedirs(os.path.join(self.tmp, "無い"))
        self.tick(r)
        self.tick(r)
        self.assertEqual(len(glob.glob(os.path.join(self.tmp, "無い", "出力", "*.失敗.txt"))), 1)
        self.assertIn("置きました", self.records()[0]["text"])

    def test_switch_off(self):
        self.friend()
        with mock.patch.object(RA, "ON", False):
            self.assertEqual(self.tick(rec(segments=0, endKind="notStarted")), 0)
        self.assertEqual(self.txts(), [])


class TestFriendInbox(unittest.TestCase):
    """友人のアプリ: 録画の知らせ(b・c)の .失敗.txt は行を失敗にせず、送った物・受け取るの段に 1 行出す"""

    def setUp(self):
        self.tmp = testkit.tempdir(self, "rec-alert-inbox-")
        self.box = _inbox.Inbox(os.path.join(self.tmp, "friend", "inbox.json"), os.path.join(self.tmp, "outbox"),
                                lambda: os.path.join(self.tmp, "save"), lambda: os.path.join(self.tmp, "cases"))

    def test_note_keeps_state(self):
        self.assertEqual(_inbox.REC_NOTE_HEAD, RA.REC_NOTE_HEAD)   # 作る人の PC と同じ頭
        self.box.add(RID, {"url": "u"}, {"url": "u", "videoId": "x", "title": "題"}, pc="user", kind="live")
        text = RA.REC_NOTE_HEAD + " 「題」の録画が途中で止まり、戻りませんでした。\n録れていない時間: 10/30 21:05 から配信の終わりまで"
        r = self.box.remote_failure(RID, "題", text, "a.失敗.txt")
        self.assertEqual(r["state"], "sent")
        self.assertEqual(len(r["recNotes"]), 1)
        self.assertTrue(r["recNotes"][0].startswith("「題」の録画が途中で止まり"))
        self.box.remote_failure(RID, "題", text, "b.失敗.txt")   # 同じ文は 1 行
        row = next(v for v in self.box.view() if v["id"] == RID)
        self.assertEqual(len(row["recNotes"]), 1)
        self.assertIsNone(self.box.remote_failure("20261030-150000-ffffff", "題", text, "c.失敗.txt"))   # 行が無ければ足さない
        r = self.box.remote_failure(RID, "題", RA.NO_REC_HEAD + " 「題」の録画が始まりませんでした。", "d.失敗.txt")
        self.assertEqual(r["state"], "failed")   # a は失敗


if __name__ == "__main__":
    unittest.main()
