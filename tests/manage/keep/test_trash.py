"""src/ytt/trashbin.py のごみ箱へ移す・戻す(④ の片付けと「要らない」が使う 1 か所)の単体テスト。戻せなかった物の元の場所を必ず記録する。

    python -m unittest tests/manage/keep/test_trash.py
"""
import json
import os
import sys
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> keep -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from ytt import fsio, trashbin  # noqa: E402
from ytt import trashbin as T  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
from testkit import tempdir  # noqa: E402


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
        self.tmp = tempdir(self, "ytt-trash-")
        self.trash = _Trash(os.path.join(self.tmp, "ごみ箱"))
        self.clip = touch(os.path.join(self.tmp, "out", "a.mp4"))
        self.side = touch(os.path.join(self.tmp, "out", "作業用", "a.clip.json"))
        self.clock = lambda: 1790000000.0

    def manifest(self, res):
        with open(os.path.join(res["day"], trashbin.MANIFEST), encoding="utf-8") as f:
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
        real = os.rename
        calls = []

        def move(a, b):
            calls.append(a)
            if a == fsio.long_path(self.side):   # OS を呼ぶ所は長いパスで包む
                raise OSError("開いている")
            return real(a, b)
        with mock.patch.object(T.os, "rename", side_effect=move):
            res = T.to_trash(self.trash, [self.clip, self.side], "discard", "a", all_or_nothing=True, clock=self.clock)
        self.assertEqual((res["moved"], res["left"]), ([], []))
        self.assertEqual([s for s, _t in res["restored"]], [self.clip])
        self.assertTrue(os.path.isfile(self.clip))
        self.assertFalse(os.path.exists(res["dest"]))   # 戻したあとの空のフォルダは消す
        self.assertFalse(os.path.exists(os.path.join(res["day"], trashbin.MANIFEST)))   # 戻せた物は記録しない

    def test_put_back_failure_is_recorded(self):
        res = T.to_trash(self.trash, [self.clip, self.side], "discard", "a", record=False, clock=self.clock)
        real = os.rename

        def move(a, b):
            if b == fsio.long_path(self.clip):
                raise OSError("戻せない")
            return real(a, b)
        with mock.patch.object(T.os, "rename", side_effect=move):
            T.put_back(res)
        self.assertEqual([s for s, _t in res["restored"]], [self.side])
        self.assertEqual([s for s, _t in res["left"]], [self.clip])
        self.assertTrue(os.path.isfile(self.side))
        rows = self.manifest(res)
        self.assertEqual([(r["from"], r.get("leftBehind")) for r in rows], [(self.clip, True)])   # 残った物の元の場所を必ず書く
        self.assertTrue(os.path.isfile(rows[0]["to"]))

    def test_need_first(self):
        with mock.patch.object(T.os, "rename", side_effect=OSError("開いている")):
            res = T.to_trash(self.trash, [self.clip, self.side], "work", "a", need_first=True, clock=self.clock)
        self.assertEqual(len(res["failed"]), 1)   # 元動画が移せなければほかは試さない
        self.assertFalse(os.path.exists(res["dest"]))

    def pack(self):
        pack = os.path.join(self.tmp, "out", "a_pack")
        touch(os.path.join(pack, "p.json"), b"{}")
        touch(os.path.join(pack, "sub", "v.mp4"), b"vvv")
        return pack

    def test_same_drive_rename_failure_does_not_copy_and_delete(self):
        """同じドライブで改名を断られた(中のファイルが開かれている)= 写して消すに落とさず、パックを丸ごと残す(見直し 3 の 1)"""
        pack = self.pack()
        with mock.patch.object(T.os, "rename", side_effect=PermissionError(13, "開いている")):
            res = T.to_trash(self.trash, [self.clip, pack], "discard", "a", all_or_nothing=True, clock=self.clock)
        self.assertEqual([p for p, _w in res["failed"]], [self.clip])
        self.assertTrue(os.path.isfile(os.path.join(pack, "p.json")) and os.path.isfile(os.path.join(pack, "sub", "v.mp4")))
        self.assertFalse(os.path.exists(res["dest"]))   # ごみ箱に写しを残さない

    def test_cross_drive_moves_dir_by_copy_then_delete(self):
        """別のドライブ(EXDEV)はフォルダを写してから元を消す"""
        pack = self.pack()
        real = os.rename

        def rename(a, b):
            if a.endswith("a_pack"):
                raise OSError(T.errno.EXDEV, "別のドライブ")
            return real(a, b)
        with mock.patch.object(T.os, "rename", side_effect=rename):
            res = T.to_trash(self.trash, [pack], "discard", "a", clock=self.clock)
        self.assertEqual([p for p, _t in res["moved"]], [pack])
        self.assertFalse(os.path.exists(pack))
        self.assertTrue(os.path.isfile(os.path.join(res["moved"][0][1], "sub", "v.mp4")))

    def test_cross_drive_delete_failure_restores_from_copy(self):
        """別のドライブで写したあと元を消しきれない(開いているファイルがある)= 消えた分を写しから戻し、写しは消す。元は欠けない"""
        pack = self.pack()
        real_unlink, locked = os.unlink, fsio.long_path(os.path.join(pack, "sub", "v.mp4"))

        def unlink(p):
            if p == locked:
                raise PermissionError(13, "開いている")
            return real_unlink(p)
        with mock.patch.object(T.os, "rename", side_effect=OSError(T.errno.EXDEV, "別のドライブ")), mock.patch.object(T.os, "unlink", side_effect=unlink):
            res = T.to_trash(self.trash, [pack], "discard", "a", clock=self.clock)
        self.assertEqual([p for p, _w in res["failed"]], [pack])
        self.assertEqual(sorted(T._tree_files(pack)), sorted(["p.json", os.path.join("sub", "v.mp4")]))   # 消えた p.json は戻った
        self.assertFalse(os.path.exists(res["dest"]))

    def test_free_path(self):
        p = touch(os.path.join(self.tmp, "x.mp4"))
        self.assertEqual(trashbin.free_path(p), os.path.join(self.tmp, "x (1).mp4"))
        self.assertEqual(trashbin.free_path(p, first=2), os.path.join(self.tmp, "x (2).mp4"))


if __name__ == "__main__":
    unittest.main()
