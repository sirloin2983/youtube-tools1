"""src/manage/keep/trash.py(ごみ箱へ移す・戻すの 1 か所。OPT-M2)の単体テスト。設計原則の指摘 1 = 戻せなかった物の元の場所を必ず記録する。

    python -m unittest src/manage/keep/tests/test_trash.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> keep -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from manage.keep import trash as T  # noqa: E402


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class _Trash:
    def __init__(self, root):
        self.root, self.roots = root, []

    def trash_for(self, path):
        return self.root

    def remember_root(self, root):
        self.roots.append(root)


class TrashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-trash-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.trash = _Trash(os.path.join(self.tmp, "ごみ箱"))
        self.clip = touch(os.path.join(self.tmp, "out", "a.mp4"))
        self.side = touch(os.path.join(self.tmp, "out", "作業用", "a.clip.json"))
        self.clock = lambda: 1790000000.0

    def manifest(self, res):
        with open(os.path.join(res["day"], T.MANIFEST), encoding="utf-8") as f:
            return [json.loads(x) for x in f]

    def test_moves_and_records(self):
        res = T.to_trash(self.trash, [self.clip, self.side], "discard", "a", clock=self.clock)
        self.assertEqual([s for s, _t in res["moved"]], [self.clip, self.side])
        self.assertTrue(res["moved"][1][1].endswith(os.path.join("a", "作業用", "a.clip.json")))
        rows = self.manifest(res)
        self.assertEqual([r["from"] for r in rows], [self.clip, self.side])
        self.assertEqual(rows[0]["at"], 1790000000000)
        self.assertEqual(self.trash.roots, [self.trash.root])

    def test_all_or_nothing_puts_back(self):
        real = shutil.move
        calls = []

        def move(a, b):
            calls.append(a)
            if a == self.side:
                raise OSError("開いている")
            return real(a, b)
        with mock.patch.object(T.shutil, "move", side_effect=move):
            res = T.to_trash(self.trash, [self.clip, self.side], "discard", "a", all_or_nothing=True, clock=self.clock)
        self.assertEqual((res["moved"], res["left"]), ([], []))
        self.assertEqual([s for s, _t in res["restored"]], [self.clip])
        self.assertTrue(os.path.isfile(self.clip))
        self.assertFalse(os.path.exists(res["dest"]))   # 戻したあとの空のフォルダは消す
        self.assertFalse(os.path.exists(os.path.join(res["day"], T.MANIFEST)))   # 戻せた物は記録しない

    def test_put_back_failure_is_recorded(self):
        res = T.to_trash(self.trash, [self.clip, self.side], "discard", "a", record=False, clock=self.clock)
        real = shutil.move

        def move(a, b):
            if b == self.clip:
                raise OSError("戻せない")
            return real(a, b)
        with mock.patch.object(T.shutil, "move", side_effect=move):
            T.put_back(res)
        self.assertEqual([s for s, _t in res["restored"]], [self.side])
        self.assertEqual([s for s, _t in res["left"]], [self.clip])
        self.assertTrue(os.path.isfile(self.side))
        rows = self.manifest(res)
        self.assertEqual([(r["from"], r.get("leftBehind")) for r in rows], [(self.clip, True)])   # 残った物の元の場所を必ず書く
        self.assertTrue(os.path.isfile(rows[0]["to"]))

    def test_need_first(self):
        with mock.patch.object(T.shutil, "move", side_effect=OSError("開いている")):
            res = T.to_trash(self.trash, [self.clip, self.side], "work", "a", need_first=True, clock=self.clock)
        self.assertEqual(len(res["failed"]), 1)   # 元動画が移せなければほかは試さない
        self.assertFalse(os.path.exists(res["dest"]))

    def test_free_path(self):
        p = touch(os.path.join(self.tmp, "x.mp4"))
        self.assertEqual(T.free_path(p), os.path.join(self.tmp, "x (1).mp4"))
        self.assertEqual(T.free_path(p, first=2), os.path.join(self.tmp, "x (2).mp4"))


if __name__ == "__main__":
    unittest.main()
