# -*- coding: utf-8 -*-
"""今の記録から人の判断の記録への写し(human/judgments_migrate)のテスト: 下見の数・スイッチが既定でオフ・書く行・二度流しても増えない・
機械の行を写さない・live と auto の二重を 1 つに・戻した答えと書き手が書いた答えを写さない"""
import contextlib
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests → human → src
from human import judgments as J  # noqa: E402
from human import judgments_migrate as M  # noqa: E402
from human.check import answerlog  # noqa: E402
from ytt import casefiles  # noqa: E402
from ytt import testkit  # noqa: E402


def jl(path, rows):
    testkit.write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def aid(n):
    return "a%013d-%06x" % (1760000000000 + n, n)


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.d = testkit.tempdir(self, "jmig-")
        self.studio, self.app = os.path.join(self.d, "studio"), os.path.join(self.d, "app")
        out = os.path.join(self.d, "out")
        os.makedirs(self.studio)
        testkit.write_json(os.path.join(self.studio, "settings.json"), {"outDir": out})
        fb = lambda ts, ev, mid, **kw: dict({"ts": ts, "videoId": "V1", "kind": "youtube", "markId": mid, "source": "review", "src": "auto", "event": ev,
                                              "verdict": "good"}, **kw)
        jl(os.path.join(self.studio, "feedback.jsonl"), [
            fb("2026-10-01T10:00:00", "adopt", "m1"), fb("2026-10-01T10:01:00", "reject", "m2", verdict="bad"),
            fb("2026-10-01T10:02:00", "export", "m1"), fb("2026-10-01T10:03:00", "adopt", "m3", adoptedBy="auto"),
            fb("2026-10-01T10:05:00", "unadopt", "m1", verdict="retract"), fb("2026-10-01T10:06:00", "manual_add", "m4", verdict="miss"),
            fb("2026-10-01T10:07:00", "delete_judged", "mZ", verdict="retract")])
        jl(os.path.join(self.app, "live", "live_feedback.jsonl"), [
            {"v": 1, "at": "2026-10-02T00:00:00Z", "event": "deliver", "human": True, "recorder": "r", "recording": "rec1", "studio": {"video": "V1", "mark": "m5"}},
            {"v": 1, "at": "2026-10-02T00:01:00Z", "event": "reject", "human": True, "recorder": "r", "recording": "rec1", "studio": {"video": "V1", "mark": "m6"}},
            {"v": 1, "at": "2026-10-02T00:02:00Z", "event": "adopt", "origin": "manual", "human": True, "recorder": "r", "recording": "rec1",
             "studio": {"video": "V1", "mark": "m11"}},
            {"v": 1, "at": "2026-10-02T00:03:00Z", "event": "adopt", "origin": "auto", "human": False, "studio": {"video": "V1", "mark": "m12"}},
            {"v": 1, "at": "2026-10-02T00:04:00Z", "event": "detect_compare"}])
        root = os.path.join(out, "case1")
        testkit.write_json(os.path.join(root, "作業用", "case.json"), {"schema": "youtube-tools-case/v1", "id": "V1"})
        testkit.write_json(os.path.join(root, "作業用", "採用.json"),
                           {"schema": casefiles.ADOPTIONS_SCHEMA, "sources": {"V1": {"kind": "youtube"}}, "marks": [],
                            "auto": {"m6": {"discardedAt": 1760000000000}, "m7": {"discardedAt": 1760000001000},
                                     "m8": {"discardedAt": 1760000002000, "expiredAt": 1760000003000}, "m10": {"seenAt": 1760000004000}}})
        logs = os.path.join(self.app, "logs")
        jl(os.path.join(logs, "deliveries.jsonl"), [{"at": 1760100000000, "zip": "REQ1__t.zip", "requestId": "REQ1", "runId": "run1", "videoId": "V1",
                                                     "origin": "request", "packs": [{"dir": "X:/p/pack1", "markId": "m9"}, {"dir": "X:/p/pack2", "markId": "m13"}]}])
        pk = [{"dir": "X:/p/pack1", "markId": "m9"}]
        jl(os.path.join(logs, "friend_feedback.jsonl"), [
            {"at": 1760200000000, "zip": "REQ1__t.zip", "verdict": "reject", "requestId": "REQ1", "videoId": "V1", "runId": "run1", "packs": pk, "origin": "request"},
            {"at": 1760200001000, "zip": "REQ1__t.zip", "verdict": "made_video", "requestId": "REQ1", "videoId": "V1", "runId": "run1", "packs": pk}])
        vd = os.path.join(self.app, "friend-returns", "2026-10", "REQ1", "verdicts")
        for name, body in (("pack1.verdict.json", {"verdict": "keep", "at": 1760300000000, "requestId": "REQ1", "pack": "pack1"}),   # 受け取った後の本物の形(returns が並べる)
                           ("REQ1__pack2.verdict.json", {"verdict": "reject", "at": 1760300001000, "by": "auto"})):
            testkit.write_json(os.path.join(vd, name), body)
        ans = lambda n, mid, choice, **kw: {"id": aid(n), "at": 1760400000000 + n, "kind": "value", "source": "auto", "card": "c%d" % n, "case": "V1",
                                              "target": {"videoId": "V1", "markId": mid}, "answer": dict({"choice": choice}, **kw), "applied": {}}
        for r in (ans(1, "m1", "good"), ans(2, "m2", "bad", reason="boring"), ans(3, "m3", "good"),
                  dict(ans(4, "m4", "good"), applied={"judgment": "jx", "jkey": "ans:zz"}),
                  {"id": aid(5), "at": 1760400000100, "undo": aid(3)}):
            answerlog.append(self.app, r)

    def written(self):
        return J.rows(self.app)

    def test_preview_counts_and_writes_nothing(self):
        got = M.build(self.d)
        st = got["stats"]
        self.assertEqual({k: v["copy"] for k, v in st.items()},
                         {"feedback": 3, "live": 3, "auto_discard": 1, "friend": 2, "verdict": 1, "answers": 2})
        self.assertEqual(st["auto_discard"]["dup"], 1)   # live の reject と二重
        self.assertEqual(st["answers"]["dup"], 1)        # 書き手が書いた答え
        self.assertEqual(sum(st["feedback"]["skip"].values()), 4)
        self.assertEqual(sum(st["verdict"]["skip"].values()), 1)
        self.assertEqual(sum(st["live"]["skip"].values()), 2)
        self.assertEqual(sum(st["auto_discard"]["skip"].values()), 1)   # expiredAt
        self.assertEqual(self.written(), [])
        self.assertIn("写す 3", M.report(got))

    def test_cases_reject_already_written_is_dup(self):
        """案件の「要らない」は judgments に直に書く(via cases の reject・key lf:)= 同じ切り抜きの auto の discardedAt は写さず重複に数える"""
        J.record(self.app, at=1760000001000, who="self", videoId="V1", markId="m7", what="reject", origin="live", via="cases",
                 key="lf:1760000001000:rec1:m7:reject")
        J.record(self.app, at=1760000001500, who="self", videoId="V1", markId="m6", what="adopt", origin="live", via="cases",
                 key="lf:1760000001500:rec1:m6:deliver")   # 案件の採用(reject でない)は重複の判定に使わない
        st = M.build(self.d)["stats"]["auto_discard"]
        self.assertEqual((st["copy"], st["dup"]), (0, 2))   # m7 = 案件が書いた reject・m6 = live の reject
        got = M.apply(self.d, enabled=True)
        self.assertEqual(sum(1 for r in self.written() if r["markId"] == "m7"), 1)
        self.assertEqual(got["stats"]["auto_discard"]["copy"], 0)

    def test_switch_off_writes_nothing(self):
        """スイッチがオフなら --apply でも書かない(オフに戻したときの守り)"""
        self.addCleanup(setattr, M, "ENABLED", M.ENABLED)
        M.ENABLED = False
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(M.main(["--data-dir", self.d, "--apply"]), 0)
        self.assertIn("スイッチがオフ", out.getvalue())
        self.assertEqual(self.written(), [])
        self.assertTrue(M.apply(self.d)["off"])
        self.assertFalse(os.path.exists(J.path(self.app)))

    def test_apply_writes_and_is_idempotent(self):
        got = M.apply(self.d, enabled=True)
        self.assertEqual(got["written"], 12)
        rows = self.written()
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["via"] == "migrate" for r in rows))
        keys = {r["key"] for r in rows}
        self.assertNotIn("fb:2026-10-01T10:03:00:V1:m3:adopt", keys)       # adoptedBy
        self.assertFalse([k for k in keys if ":export" in k or "manual_add" in k or "m8" in k or "m12" in k or k.endswith("detect_compare")])
        self.assertNotIn("ans:" + aid(3), keys)                            # 戻した答え
        self.assertNotIn("ans:" + aid(4), keys)                            # 書き手が書いた答え
        self.assertEqual(sum(1 for r in rows if r["markId"] == "m6"), 1)   # live の reject と auto の discardedAt の二重が 1 つ
        # 取り消しは直前の採否の行を指し、レーンが空に戻る
        ad = next(r for r in rows if r["key"].startswith("fb:") and r["what"] == "adopt")
        rt = next(r for r in rows if r["what"] == "retract")
        self.assertEqual(rt["of"], ad["id"])
        self.assertIsNone(J.fold(rows)[("V1", "m1")]["adopt"])
        self.assertEqual(J.fold(rows)[("V1", "m1")]["quality"]["what"], "quality_good")
        self.assertEqual(next(r for r in rows if r["key"] == "ans:" + aid(2))["reason"], "boring")
        # 友人の行
        fr = J.fold(rows)[("V1", "m9")]["friend"]
        self.assertEqual((fr["who"], fr["what"]), ("friend", "adopt"))   # 最後は keep(adopt)
        self.assertFalse([r for r in rows if r["markId"] == "m13"])      # by auto の verdict
        again = M.apply(self.d, enabled=True)
        self.assertEqual(again["written"], 0)
        self.assertEqual(len(self.written()), 12)
        self.assertEqual(sum(v["dup"] for v in again["stats"].values()), 12 + 2)


if __name__ == "__main__":
    unittest.main()
