# -*- coding: utf-8 -*-
"""pipeline/transcribe/roster の配信ごとの文脈 stream_context と用語の区切り split_terms(役割で組み直す RS2-8a に編集の ed_jobs から移した)を、
編集の serve を読まずに使うテスト。

    py -3.10 -m unittest src/pipeline/transcribe/tests/test_txroster.py -v

名簿のファイルは roster.ROSTER、スタジオの配信の情報は ytt/studiodata.studio_stream から読む(RS3-0A まで txenv の口)。本物のスタジオの data.json を読む形
(serve の登録 = ytt/studiodata.studio_stream。RS3-0A まで ed_store)は編集のテスト(src/editor/tests/test_roster.py の TestStreamContext。serve の名前で読む)が確かめる。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)。ほかのテストとそろえる
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import roster  # noqa: E402
from ytt import studiodata  # noqa: E402

STREAMS = {"vidA": {"channel": "Pekora Ch. 兎田ぺこら", "title": "コラボ!", "collab": [{"videoId": "vidB", "channel": "Marine Ch. 宝鐘マリン", "title": "別視点"}]}}


class TestSplitTerms(unittest.TestCase):
    def test_separators(self):
        self.assertEqual(roster.split_terms("ホロライブ、ぺこら,マリン\n船長\r\n  みこ  ,、"), ["ホロライブ", "ぺこら", "マリン", "船長", "みこ"])
        self.assertEqual(roster.split_terms(None), [])
        self.assertEqual(roster.split_terms(""), [])


class TestStreamContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="txroster_")
        path = os.path.join(self.tmp, "roster.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"groups": [{"id": "gen0", "label": "0期生", "names": ["ときのそら"]},
                                  {"id": "gen3", "label": "3期生", "names": ["兎田ぺこら", "宝鐘マリン"]}],
                       "members": [{"name": "ときのそら", "aliases": ["そら", "そらちゃん"], "common": ["そら"]},
                                   {"name": "兎田ぺこら", "aliases": ["ぺこら", "ぺこーら", "兎田"]},
                                   {"name": "宝鐘マリン", "aliases": ["マリン", "船長"], "common": ["マリン", "船長"]}]}, f, ensure_ascii=False)
        self.calls = []

        def studio_stream(vid):
            self.calls.append(vid)
            return STREAMS.get(vid)
        for mod, name, value in ((roster, "ROSTER", path), (studiodata, "studio_stream", studio_stream)):
            p = mock.patch.object(mod, name, value)   # 試験の間だけ(終わったら元に戻す)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, True)

    def doc(self, vid="vidA"):
        return {"clip": {"source": {"kind": "youtube", "videoId": vid, "title": "【】"}}, "title": "01_00h01m",
                "sourcePath": os.path.join("C:/x", "ときのそら 雑談", "01.mp4"), "speakers": [{"id": "S1", "name": "話者1"}]}

    def test_channel_collab_title(self):
        c = roster.stream_context(self.doc())
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]],
                         [("兎田ぺこら", ["channel"]), ("宝鐘マリン", ["collab"]), ("ときのそら", ["title"])])   # 動画の入ったフォルダの名前も題名として見る
        self.assertEqual(c["terms"][:4], ["兎田ぺこら", "ぺこら", "ぺこーら", "兎田"])
        self.assertEqual(self.calls, ["vidA"])

    def test_disabled_reads_nothing(self):
        self.assertEqual(roster.stream_context(self.doc(), False), {"members": [], "terms": []})
        self.assertEqual(self.calls, [])

    def test_no_video_id_skips_studio(self):
        c = roster.stream_context({"title": "ぺこらの配信"})
        self.assertEqual([m["name"] for m in c["members"]], ["兎田ぺこら"])
        self.assertEqual(self.calls, [])

    def test_studio_unknown_or_broken_continues_without_context(self):
        """スタジオの情報が無い(None)・例外のときは、チャンネル名とコラボ相手なしで題名・フォルダから続ける(移す前と同じ)"""
        expect = [("ときのそら", ["title"])]
        c = roster.stream_context(self.doc("無い配信"))
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]], expect)

        def broken(vid):
            raise ValueError("壊れた data.json")
        studiodata.studio_stream = broken
        c = roster.stream_context(self.doc())
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]], expect)


if __name__ == "__main__":
    unittest.main()
