# -*- coding: utf-8 -*-
"""pipeline/transcribe/roster の配信ごとの文脈 stream_context と用語の区切り split_terms(ytt/txtext)を、編集の serve を読まずに使うテスト。

    py -3.12 -m unittest src/pipeline/transcribe/tests/test_txroster.py -v

名簿のファイルは roster.ROSTER、スタジオの配信の情報は ytt/studiodata.studio_stream から読む。文書の見本(チャンネル・コラボ相手・動画のフォルダ・題名・
スタジオに無い配信・配信の ID が無い文書・オフ)を入口に通してまとめて確かめる。ジョブに文脈が残る形は src/editor/tests/test_fill.py の通し。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from ytt.tests import testkit  # noqa: E402
from pipeline.transcribe import roster  # noqa: E402
from ytt import studiodata  # noqa: E402
from ytt import txtext  # noqa: E402

STREAMS = {"vidA": {"channel": "Pekora Ch. 兎田ぺこら", "title": "コラボ!", "collab": [{"videoId": "vidB", "channel": "Marine Ch. 宝鐘マリン", "title": "別視点"}]}}


class TestStreamContext(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, prefix="txroster_")
        path = os.path.join(self.tmp, "roster.json")
        testkit.write_json(path, {"groups": [{"id": "gen0", "label": "0期生", "names": ["ときのそら"]},
                                             {"id": "gen3", "label": "3期生", "names": ["兎田ぺこら", "宝鐘マリン"]}],
                                  "members": [{"name": "ときのそら", "aliases": ["そら", "そらちゃん"], "common": ["そら"]},
                                              {"name": "兎田ぺこら", "aliases": ["ぺこら", "ぺこーら", "兎田"]},
                                              {"name": "宝鐘マリン", "aliases": ["マリン", "船長"], "common": ["マリン", "船長"]}]})
        self.calls = []

        def studio_stream(vid):
            self.calls.append(vid)
            return STREAMS.get(vid)
        for mod, name, value in ((roster, "ROSTER", path), (studiodata, "studio_stream", studio_stream)):
            self.enterContext(mock.patch.object(mod, name, value))   # 試験の間だけ(終わったら元に戻す)

    def doc(self, vid="vidA"):
        return {"clip": {"source": {"kind": "youtube", "videoId": vid, "title": "【】"}}, "title": "01_00h01m",
                "sourcePath": os.path.join("C:/x", "ときのそら 雑談", "01.mp4"), "speakers": [{"id": "S1", "name": "話者1"}]}

    def test_members_and_terms(self):
        c = roster.stream_context(self.doc())
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]],
                         [("兎田ぺこら", ["channel"]), ("宝鐘マリン", ["collab"]), ("ときのそら", ["title"])])   # 動画の入ったフォルダの名前も題名として見る
        self.assertEqual(c["terms"][:4], ["兎田ぺこら", "ぺこら", "ぺこーら", "兎田"])
        self.assertEqual([(m["name"], m["from"]) for m in roster.stream_context(self.doc("無い配信"))["members"]], [("ときのそら", ["title"])])   # スタジオに無い配信
        self.assertEqual([m["name"] for m in roster.stream_context({"title": "ぺこらの配信"})["members"]], ["兎田ぺこら"])   # 配信の ID が無ければスタジオを読まない
        self.assertEqual(roster.stream_context(self.doc(), False), {"members": [], "terms": []})   # オフは何も読まない
        self.assertEqual(self.calls, ["vidA", "無い配信"])
        self.assertEqual(txtext.split_terms("ホロライブ、ぺこら,マリン\n船長\r\n  みこ  ,、"), ["ホロライブ", "ぺこら", "マリン", "船長", "みこ"])
        self.assertEqual((txtext.split_terms(None), txtext.split_terms("")), ([], []))

    def test_broken_studio_data_continues(self):
        """スタジオの情報が例外のときは、チャンネル名とコラボ相手なしで題名・フォルダから続ける"""
        def broken(vid):
            raise ValueError("壊れた data.json")
        studiodata.studio_stream = broken
        self.assertEqual([(m["name"], m["from"]) for m in roster.stream_context(self.doc())["members"]], [("ときのそら", ["title"])])


if __name__ == "__main__":
    unittest.main()
