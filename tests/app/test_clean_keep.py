"""自動の片付けが残す動画(src/app/server.py の clean_inputs・pending_check_docs。10-24 の直し):
確かめるにまだ出ているカードの文書の切り抜きは、カードの種類に関わらず残す。答えた物から 3 日の決まりに入る。カードを集められなければ何も移さない。
実行(リポジトリ直下から): python -m unittest tests/app/test_clean_keep.py -v
"""
import os
import sys
import types
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import server as S  # noqa: E402


def card(cid, kind, tid=None, url=None):
    c = {"id": cid, "kind": kind}
    if tid:
        c["target"] = {"docId": tid}
    if url:
        c["media"] = {"url": url}
    return c


class CleanKeepTest(unittest.TestCase):
    def test_pending_check_docs(self):
        cards = [card("voice:solo:a1:r1", "voice", "aaaaaaaaaaa1"), card("read:x:b1:r1", "read", "bbbbbbbbbbb1"),
                 card("time:x:c1:r1", "time", None, "transcribe/media?id=ccccccccccc1"), card("speech:x:d1:r1", "speech", "ddddddddddd1")]
        self.assertEqual(S.pending_check_docs(cards, {"speech:x:d1:r1"}), {"aaaaaaaaaaa1", "bbbbbbbbbbb1", "ccccccccccc1"})   # 答えたカードは外す

    def _srv(self):
        return types.SimpleNamespace(sup=types.SimpleNamespace(root="R"), cleanup=types.SimpleNamespace(app_dir="A"), check_ctx=lambda: None, _autorun=None)

    def test_clean_inputs_keeps_every_kind(self):
        snap = {"cases": [{"id": "v1", "clips": [{"path": "E:/x/01.mp4", "transcriptIds": ["aaaaaaaaaaa1"]},
                                                 {"path": "E:/x/02.mp4", "transcript": {"id": "bbbbbbbbbbb1"}},
                                                 {"path": "E:/x/03.mp4", "transcriptIds": ["zzzzzzzzzzz9"]}]}],
                "virtual": [{"id": "orphan", "caseKind": "orphan", "clips": [{"path": "E:/y/04.mp4", "transcriptIds": ["ccccccccccc1"]}]}]}
        cards = [card("voice:solo:a", "voice", "aaaaaaaaaaa1"), card("read:x:b", "read", "bbbbbbbbbbb1"), card("time:x:c", "time", "ccccccccccc1")]
        st = types.SimpleNamespace(by_card={})
        with mock.patch.object(S.cases_mod, "snapshot", lambda root: snap), mock.patch.object(S.check_answerlog, "state", lambda d: st), \
                mock.patch.object(S.check_sources, "collect", lambda ctx, s: (cards, types.SimpleNamespace(errors=[]))):
            cases, keep, busy = S.PortalServer.clean_inputs(self._srv())
            self.assertEqual(sorted(keep), ["E:/x/01.mp4", "E:/x/02.mp4", "E:/y/04.mp4"])   # 声・読み・時刻のカードの文書。03 はカードが無い = 3 日の決まり
            st.by_card = {"voice:solo:a": 1}
            self.assertNotIn("E:/x/01.mp4", S.PortalServer.clean_inputs(self._srv())[1])   # 答え終わった物から 3 日の決まりに入る
        with mock.patch.object(S.cases_mod, "snapshot", lambda root: snap), mock.patch.object(S.check_answerlog, "state", lambda d: st), \
                mock.patch.object(S.check_sources, "collect", lambda ctx, s: ([], types.SimpleNamespace(errors=["voice:solo: OSError"]))):
            with self.assertRaises(RuntimeError):   # 集められない出どころがある = 何も移さない(auto_clean が None を返す)
                S.PortalServer.clean_inputs(self._srv())


if __name__ == "__main__":
    unittest.main()
