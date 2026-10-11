"""「確かめる」の答えの記録(src/human/check/answerlog.py)と反映の土台(apply.py)の単体テスト。一時フォルダと偽の反映の部品だけを使う。

実行(リポジトリ直下から): py -3.10 -m unittest src/human/check/tests/test_apply.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> check -> human -> src
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from human.check import answerlog, apply  # noqa: E402


def card(key, kind="read", source="fake"):
    return {"id": "%s:%s:%s" % (kind, source, key), "kind": kind, "source": source, "case": {"id": "v1", "title": "t"},
            "target": {"docId": "aaaaaaaaaaaa", "row": key}, "guess": "1"}


class Fake:
    """偽の反映: 実物 = self.real(行 → 答え)"""

    def __init__(self):
        self.real, self.calls = {}, []

    def apply(self, ctx, c, ans):
        self.calls.append(("apply", c["id"], ans))
        if ans == "boom":
            raise apply.Refused("壊れました", 409, "boom")
        before = self.real.get(c["target"]["row"])
        self.real[c["target"]["row"]] = ans
        return {"row": c["target"]["row"], "before": before}

    def revert(self, ctx, row):
        self.calls.append(("revert", row["card"], row["applied"]))
        a = row["applied"]
        if a["before"] is None:
            self.real.pop(a["row"], None)
        else:
            self.real[a["row"]] = a["before"]
        return {"row": a["row"]}


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-check-apply-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ctx = apply.Context(self.tmp, ROOT)
        self.fake = Fake()

        def check(ans):
            if ans not in ("1", "2", "send", "boom"):
                raise ValueError("1 か 2 です")
            return ans
        apply.register("read", "fake", self.fake.apply, self.fake.revert, check=check)
        apply.register("value", "fake", self.fake.apply, self.fake.revert, defer=lambda ans: ans == "send")
        self.addCleanup(apply.unregister, "read", "fake")
        self.addCleanup(apply.unregister, "value", "fake")

    def lines(self):
        with open(answerlog.answers_path(self.tmp), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def test_answer_and_undo(self):
        got = apply.answer(self.ctx, card("s1"), {"answer": "2", "ms": 1500})
        self.assertEqual((got["ok"], got["held"], got["applied"]["row"], self.fake.real), (True, False, "s1", {"s1": "2"}))
        row = self.lines()[0]
        self.assertEqual((row["card"], row["answer"], row["ms"], row["case"], row["guess"]), ("read:fake:s1", "2", 1500, {"id": "v1", "title": "t"}, "1"))
        st = answerlog.state(self.tmp)
        self.assertEqual((st.by_card, st.today()), ({"read:fake:s1": got["answer"]}, 1))
        with self.assertRaises(apply.Refused) as e:
            apply.answer(self.ctx, card("s1"), {"answer": "1"})
        self.assertEqual(e.exception.error, "answered")
        back = apply.undo(self.ctx, got["answer"])
        self.assertEqual((back["card"], self.fake.real), ("read:fake:s1", {}))
        self.assertEqual(answerlog.state(self.tmp).by_card, {})
        with self.assertRaises(apply.Refused) as e:
            apply.undo(self.ctx, got["answer"])
        self.assertEqual(e.exception.error, "undone")
        again = apply.answer(self.ctx, card("s1"), {"answer": "1"})   # 戻したら答え直せる
        self.assertEqual(answerlog.state(self.tmp).by_card, {"read:fake:s1": again["answer"]})

    def test_refusals(self):
        cases = [(card("s1", source="nobody"), {"answer": "1"}, "not_ready"), (card("s1"), {}, "bad_request"),
                 (card("s1"), {"answer": "9"}, "bad_request"), (card("s1"), {"answer": "x" * 5000}, "size"),
                 (card("s1"), {"answer": float("nan")}, "bad_request"), (card("s1"), {"answer": "boom"}, "boom")]
        for c, body, err in cases:
            with self.assertRaises(apply.Refused) as e:
                apply.answer(self.ctx, c, body)
            self.assertEqual(e.exception.error, err, body)
        self.assertFalse(os.path.exists(answerlog.answers_path(self.tmp)))   # 断った答えは記録しない
        for bad, err in (("x", "bad_request"), (answerlog.new_id(), "not_found")):
            with self.assertRaises(apply.Refused) as e:
                apply.undo(self.ctx, bad)
            self.assertEqual(e.exception.error, err)

    def test_held_until_next_answer(self):
        a = apply.answer(self.ctx, card("v1", kind="value"), {"answer": "send"})
        self.assertEqual((a["held"], self.fake.real), (True, {}))           # まだ届けない
        self.assertEqual([r["card"] for r in answerlog.state(self.tmp).held()], ["value:fake:v1"])
        b = apply.answer(self.ctx, card("s1"), {"answer": "1"})            # 次のカードに答えた = 前の保留を確定
        self.assertEqual([f["card"] for f in b["flushed"]], ["value:fake:v1"])
        self.assertEqual(self.fake.real, {"v1": "send", "s1": "1"})
        self.assertEqual(answerlog.state(self.tmp).held(), [])
        back = apply.undo(self.ctx, a["answer"])                          # 確定のあとの Z は確定の applied で戻す
        self.assertEqual((back["reverted"], self.fake.real), ({"row": "v1"}, {"s1": "1"}))

    def test_held_undo_is_record_only_and_flush(self):
        a = apply.answer(self.ctx, card("v1", kind="value"), {"answer": "send"})
        back = apply.undo(self.ctx, a["answer"])
        self.assertEqual((back["reverted"], self.fake.calls), ({"held": True}, []))   # 届ける前に戻した = 何も呼ばない
        apply.answer(self.ctx, card("v2", kind="value"), {"answer": "send"})
        self.assertEqual(self.fake.real, {})
        got = apply.flush(self.ctx)                                        # 画面を離れた
        self.assertEqual(([f["card"] for f in got["flushed"]], self.fake.real), (["value:fake:v2"], {"v2": "send"}))
        self.assertEqual(apply.flush(self.ctx)["flushed"], [])             # 二重に確定しない

    def test_flush_failure_is_recorded_once(self):
        apply.register("value", "fake", lambda ctx, c, ans: (_ for _ in ()).throw(OSError("disk")), self.fake.revert, defer=lambda ans: True)
        a = apply.answer(self.ctx, card("v1", kind="value"), {"answer": "send"})
        got = apply.flush(self.ctx)
        self.assertEqual(got["flushed"][0]["failed"], "disk")
        st = answerlog.state(self.tmp)
        self.assertEqual(([r["id"] for r in st.failed()], st.held(), st.effective()), ([a["answer"]], [], []))
        self.assertEqual(apply.undo(self.ctx, a["answer"])["reverted"], {"held": True})   # 届かなかった物の Z は記録だけ

    def test_skip_flushes_and_records(self):
        apply.answer(self.ctx, card("v1", kind="value"), {"answer": "send"})
        got = apply.skip(self.ctx, "read:fake:s9")
        self.assertEqual(len(got["flushed"]), 1)
        self.assertEqual(answerlog.read_skips(self.tmp), ["read:fake:s9"])
        apply.skip(self.ctx, "read:fake:s8")
        apply.skip(self.ctx, "read:fake:s9")
        self.assertEqual(answerlog.read_skips(self.tmp), ["read:fake:s8", "read:fake:s9"])
        self.assertEqual(answerlog.read_skips(self.tmp, at_ms=answerlog.now_ms() + 2 * 86400 * 1000), [])   # 日が変わったら空

    def test_log_write_failure_reverts(self):
        with mock.patch.object(answerlog, "append", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                apply.answer(self.ctx, card("s1"), {"answer": "2"})
        self.assertEqual(self.fake.real, {})   # 記録できない答えは実物にも残さない

    def test_broken_lines_are_skipped(self):
        os.makedirs(answerlog.check_dir(self.tmp))
        with open(answerlog.answers_path(self.tmp), "w", encoding="utf-8") as f:
            f.write('{"id": "bad"}\nnot json\n{"id": "%s", "card": "read:fake:s1", "kind": "read", "source": "fake", "at": 1}\n' % answerlog.new_id(1))
        st = answerlog.state(self.tmp)
        self.assertEqual(list(st.by_card), ["read:fake:s1"])

    def test_hook_missing(self):
        with self.assertRaises(apply.Refused) as e:
            self.ctx.hook("auto_review")
        self.assertEqual(e.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
