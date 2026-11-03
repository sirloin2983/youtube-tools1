"""ytt/streamlog(配信・依頼・切り抜きの出来事の記録。11-03)。一時フォルダの記録だけ(本物の作業データには書かない)"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from ytt import streamlog as S  # noqa: E402

T0 = 1793600000.0


class StreamLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.p = os.path.join(self.tmp, "logs", S.NAME)

    def test_append_only_rows_and_stream_id(self):
        """後ろに足すだけ・配信の id は動画 id か録画の id の末・空の欄は書かない・読むときは壊れた行を飛ばす"""
        a = S.record("request", "w5UO1TRxc8c", now=T0, p=self.p, request="20261102-200502-8d062d", by="friend", note="")
        b = S.record("export", now=T0 + 1, p=self.p, recording="20261102-200617-w5UO1TRxc8c", mark="m1", start=1391.0, end=1512.5, base="recording")
        self.assertEqual((a["stream"], b["stream"]), ("w5UO1TRxc8c", "w5UO1TRxc8c"))
        self.assertNotIn("note", a)
        self.assertEqual(b["at"], int((T0 + 1) * 1000))
        with open(self.p, "a", encoding="utf-8") as f:
            f.write("こわれた行\n" + json.dumps({"kind": "nope", "at": 1}) + "\n")
        self.assertEqual([r["kind"] for r in S.rows(self.p)], ["request", "export"])
        self.assertEqual(S.stream_of("short"), "")
        self.assertEqual(S.stream_of(None, "20261102-200617-w5UO1TRxc8c"), "w5UO1TRxc8c")

    def test_roster_in_one_place(self):
        """知らない種類・欄は ValueError(名簿は KINDS・FIELDS の 1 か所)。書く所が無い(inplace)なら書かない"""
        with self.assertRaises(ValueError):
            S.record("unknown-kind", "w5UO1TRxc8c", p=self.p)
        with self.assertRaises(ValueError):
            S.record("deliver", "w5UO1TRxc8c", p=self.p, unknown="x")
        self.assertFalse(os.path.exists(self.p))
        self.assertIsNone(S.path({"YTT_DATA_DIR": "inplace"}))
        self.assertTrue(all(isinstance(v, str) and v for v in list(S.KINDS.values()) + list(S.FIELDS.values())))

    def test_unwritable_does_not_raise(self):
        """書けなくても呼び手は止めない(None)"""
        blocker = os.path.join(self.tmp, "file")
        with open(blocker, "w") as f:
            f.write("x")
        self.assertIsNone(S.record("deliver", "w5UO1TRxc8c", p=os.path.join(blocker, "logs", S.NAME)))


if __name__ == "__main__":
    unittest.main()
