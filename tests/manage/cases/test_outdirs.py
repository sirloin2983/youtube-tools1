#!/usr/bin/env python3
"""書き出し先を変えたあとの案件の繋ぎ直し(src/manage/cases/outdirs.py)の確かめ。

    python -m unittest tests/manage/cases/test_outdirs.py

一時フォルダにスタジオの作業データ(data.json)と書き出し先(案件のフォルダ)を作って流す(本物の作業データには触らない)。
配信は Store で書き出して案件にする(casebook.case_of を案件の根に固定 = 初めての書き出しで案件になる)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src"))   # src
from flow import casebook  # noqa: E402
from human.review import store  # noqa: E402
from manage.cases import outdirs as O  # noqa: E402
from ytt import names, schemas, studio_env  # noqa: E402
from ytt.errors import ApiError  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
from testkit import read_json, tempdir  # noqa: E402

YT = {"kind": "youtube", "videoId": "abcdefghijk", "name": "abcdefghijk"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempdir(self, "outdirs-")
        studio_env.set_home(os.path.join(self.tmp, "studio"))
        self.data = os.path.join(self.tmp, "studio", "data.json")
        self.out = os.path.join(self.tmp, "out")
        self.root = os.path.join(self.out, "題")
        os.makedirs(os.path.join(self.root, schemas.WORK_DIR))
        names.write_owner(self.root, YT["videoId"])
        p = mock.patch.object(casebook._fsio, "is_fixed_drive", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.st = store.Store(self.data)
        self.logs = []

    def video(self):
        """書き出し済みの配信を 1 本作る(初めての書き出しで案件 self.root になる) -> 配信の id"""
        vid = YT["videoId"]
        self.st.ensure(YT, "t", "ch")
        self.st.put_video(vid, "t", [{"id": "m1", "start": 10, "end": 40, "status": "adopted"}], self.st.get(vid)[0]["rev"])
        path = os.path.join(self.root, "01.mp4")
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(casebook, "case_of", return_value=self.root):
            self.assertTrue(self.st.mark_exported(vid, "m1", os.path.basename(self.root) + "/01.mp4", 10, 40, path))
        self.assertEqual(self.row(vid)["case"], os.path.normpath(self.root))
        return vid

    def row(self, vid):
        return read_json(self.data)["videos"][vid]

    def full(self, vid):
        """スタジオを起動し直したときの配信 1 本(公開の形)"""
        return store.Store(self.data).get(vid)[0]

    def cli(self, argv):
        with mock.patch.object(O._placement, "studio_data", return_value=self.data), \
                mock.patch.object(O._placement, "acquire", return_value=object()), mock.patch.object(O._placement, "release"), \
                mock.patch("builtins.print"):
            return O.main(argv)


class RelinkTest(Base):
    def setUp(self):
        super().setUp()
        self.vid = self.video()
        self.before = self.full(self.vid)

    def test_relink_by_command(self):
        moved = os.path.join(self.tmp, "動かした先")
        shutil.move(self.root, moved)
        with self.assertRaises(ApiError) as cm:
            store.Store(self.data).get(self.vid)
        self.assertEqual(cm.exception.status, 503)
        self.assertEqual(O.status(self.data)["cases"], 1)
        wrong = os.path.join(self.tmp, "ちがう")
        os.makedirs(os.path.join(wrong, schemas.WORK_DIR))
        names.write_owner(wrong, "someone-else")
        self.assertIn("持ち主", O.relink(self.data, self.vid, wrong, log=self.logs.append))
        self.assertIn("案件にした配信", O.relink(self.data, "nonexistent00", moved, log=self.logs.append))
        # 繋ぎ直しは CLI の入口から(終了コード 1 = 見つからない・0 = 繋ぎ直した)。関数の道も同じ
        self.assertEqual(self.cli(["--relink", self.vid, os.path.join(self.tmp, "無い")]), 1)
        self.assertEqual(self.cli(["--relink", self.vid, moved]), 0)
        self.assertEqual(self.row(self.vid)["case"], os.path.normpath(moved))
        got = self.full(self.vid)
        self.assertEqual([m["id"] for m in got["marks"]], [m["id"] for m in self.before["marks"]])
        self.assertEqual(store.Store(self.data).internal(self.vid)["marks"][0]["path"], os.path.join(os.path.normpath(moved), "01.mp4"))
        self.assertIsNone(O.status(self.data))   # 見えない案件が 0 に戻ったら行を出さない(繋ぎ直した本数は 0 のまま)
        self.assertIsNone(O.relink(self.data, self.vid, moved, log=self.logs.append))   # 関数の入口は成功で None

    def test_relink_needs_source_in_adoptions(self):
        other = os.path.join(self.tmp, "持ち主だけ")
        os.makedirs(os.path.join(other, schemas.WORK_DIR))
        names.write_owner(other, YT["videoId"])
        self.assertIn("採用.json", O.relink(self.data, self.vid, other, log=self.logs.append))

    def test_out_dir_change_relinks_same_relative_path(self):
        O.relink_out_dir(self.data, self.out, log=self.logs.append)   # 起動のたびに今の書き出し先を覚える
        self.assertEqual(O.read_state(self.data)["outDirs"], [os.path.normpath(self.out)])
        new_out = os.path.join(self.tmp, "新しい書き出し先")
        shutil.move(self.out, new_out)
        self.assertEqual(O.relink_out_dir(self.data, new_out, log=self.logs.append), 1)
        self.assertEqual(self.row(self.vid)["case"], os.path.join(os.path.normpath(new_out), "題"))
        self.assertEqual(self.full(self.vid)["marks"][0]["path"], os.path.join(os.path.normpath(new_out), "題", "01.mp4"))
        self.assertEqual(O.read_state(self.data)["outDirs"][:2], [os.path.normpath(new_out), os.path.normpath(self.out)])
        self.assertEqual(O.status(self.data)["relinked"], 1)
        self.assertEqual(O.relink_out_dir(self.data, new_out, log=self.logs.append), 0)   # 2 回目は何もしない

    def test_out_dir_change_does_not_search_by_title(self):
        """相対パスが違う(題でフォルダ名が変わった)なら繋ぎ直さない・見えている案件は触らない"""
        O.relink_out_dir(self.data, self.out)
        new_out = os.path.join(self.tmp, "新しい書き出し先")
        os.makedirs(new_out)
        shutil.move(self.root, os.path.join(new_out, "別の題"))
        self.assertEqual(O.relink_out_dir(self.data, new_out), 0)
        self.assertEqual(self.row(self.vid)["case"], os.path.normpath(self.root))

    def test_no_data_does_nothing(self):
        """data.json が無い・書き出し先が相対パスなら何もしない(0 本・覚えない)"""
        self.assertEqual(O.relink_out_dir(os.path.join(self.tmp, "無い", "data.json"), self.out), 0)
        self.assertEqual(O.relink_out_dir(self.data, "相対"), 0)
        self.assertIsNone(O.read_state(self.data).get("outDirs"))


class StatusAndCliTest(Base):
    def test_status_none_when_nothing(self):
        self.assertIsNone(O.status(self.data))

    def test_cli_lock_busy(self):
        busy = O._placement.LockBusy({"pid": 1, "port": 8700})
        with mock.patch.object(O._placement, "acquire", side_effect=busy), mock.patch("builtins.print"):
            self.assertEqual(O.main(["--relink", "x", "y"]), 4)


if __name__ == "__main__":
    unittest.main()
