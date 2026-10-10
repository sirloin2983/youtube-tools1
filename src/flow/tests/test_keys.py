# -*- coding: utf-8 -*-
"""flow/keys(② 成果物の鍵を書く・読む。役割で組み直す RS6 b-K1)のテスト。

    py -3.10 -m unittest src/flow/tests/test_keys.py -v

- 書く・読む・壊れた鍵・stale の 3 通り(same / differ / none)・消す
- 段ごとの inputs・文書の鍵(transcribe・post・diar)・パックの鍵・スタジオの export の鍵
- F-1: 速報版を本番版に入れ替えたとき、export の鍵が媒体 = archive で書き直され、書けなければ消える
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from flow import keys, live_archive  # noqa: E402
from ytt import schemas, workdata  # noqa: E402

TID = "abc123def456"


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="flowkeys_")
        self.tx = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.tx)
        p = mock.patch.object(workdata, "TX_DIR", self.tx)
        p.start()
        self.addCleanup(p.stop)
        self.media = os.path.join(self.tmp, "clips", "a_0001.mp4")
        os.makedirs(os.path.dirname(self.media))
        with open(self.media, "wb") as f:
            f.write(b"movie-bytes")

    def tearDown(self):
        shutil.rmtree(self.tmp, True)


class TestWriteReadStale(_Env):
    def test_write_read_roundtrip(self):
        kp = keys.media_key_path(self.media, "export")
        self.assertTrue(kp.endswith(os.path.join("作業用", "a_0001.export.key.json")))
        inp = keys.export_inputs(schemas.media_identity("archive", videoId="vid12345678"), 12.0004, 40.5, {"fast": False})
        self.assertEqual((inp["start"], inp["end"]), (12000, 40500))   # 秒は ms の整数
        self.assertTrue(keys.write("export", kp, inp))
        k = keys.read(kp, "export")
        self.assertEqual(k["stage"], "export")
        self.assertEqual(k["madeBy"]["name"], "flow")
        self.assertEqual(keys.key_hash(kp, "export"), k["hash"])
        self.assertIsNone(keys.read(kp, "post"))   # 別の段としては読まない

    def test_broken_and_missing_key(self):
        kp = keys.media_key_path(self.media, "export")
        self.assertIsNone(keys.read(kp, "export"))
        os.makedirs(os.path.dirname(kp))
        with open(kp, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(keys.read(kp, "export"))
        with open(kp, "w", encoding="utf-8") as f:
            json.dump(dict(schemas.make_key("export", {"a": 1}), inputs={"a": 2}), f)   # 書き換えられた鍵(hash が合わない)
        self.assertIsNone(keys.read(kp, "export"))
        self.assertEqual(keys.stale(kp, "export", {"a": 1}), "none")

    def test_stale_three_ways(self):
        kp = keys.doc_key_path(TID, "post")
        self.assertEqual(keys.stale(kp, "post", {"x": 1}), "none")
        keys.write("post", kp, {"x": 1})
        self.assertEqual(keys.stale(kp, "post", {"x": 1}), "same")
        self.assertEqual(keys.stale(kp, "post", {"x": 2}), "differ")

    def test_write_failure_returns_false(self):
        blocker = os.path.join(self.tmp, "file")
        with open(blocker, "w") as f:
            f.write("x")
        self.assertFalse(keys.write("export", os.path.join(blocker, "sub", "k.json"), {"a": 1}))   # フォルダを作れない
        self.assertFalse(keys.write("nope", os.path.join(self.tmp, "k.json"), {"a": 1}))   # 段が正しくない

    def test_remove(self):
        kp = keys.doc_key_path(TID, "diar")
        keys.write("diar", kp, {"a": 1})
        self.assertTrue(keys.remove(kp))
        self.assertFalse(os.path.exists(kp))
        self.assertTrue(keys.remove(kp))   # 無くても真

    def test_doc_key_path_checks_id(self):
        with self.assertRaises(ValueError):
            keys.doc_key_path("../x", "post")
        self.assertEqual(os.path.basename(keys.doc_key_path(TID, "transcribe")), TID + ".transcribe.key.json")


class TestStages(_Env):
    RUN = {"engine": "fake", "engineVersion": "1", "model": "small", "language": "ja",
           "settings": {"beam": 5, "vadMode": "weak", "boost": False, "dict": {"glossary": "abc"}}, "post": {"v": 2}}

    def test_transcribe_and_post(self):
        spec = {"start": 0.0, "end": 4.0, "whole": True, "sourcePath": self.media}
        self.assertEqual(keys.write_after_transcribe(TID, spec, self.RUN), 2)
        t = keys.read(keys.doc_key_path(TID, "transcribe"), "transcribe")
        p = keys.read(keys.doc_key_path(TID, "post"), "post")
        self.assertEqual(t["inputs"]["engine"], "fake")
        self.assertEqual(p["inputs"]["transcribe"], t["hash"])   # post は transcribe の hash を材料にする
        self.assertEqual(t["inputs"]["export"]["media"]["kind"], "file")   # 書き出しの鍵が無ければ動画の識別
        self.assertNotIn("span", t["inputs"])

    def test_transcribe_uses_export_key_hash(self):
        keys.write_export(self.media, schemas.media_identity("archive", videoId="vid12345678"), 1, 9, {})
        spec = {"start": 2.0, "end": 4.0, "whole": False, "sourcePath": self.media}
        keys.write_after_transcribe(TID, spec, self.RUN)
        t = keys.read(keys.doc_key_path(TID, "transcribe"), "transcribe")
        self.assertEqual(t["inputs"]["export"], keys.key_hash(keys.media_key_path(self.media, "export"), "export"))
        self.assertEqual(t["inputs"]["span"], [2000, 4000])

    def test_diar(self):
        keys.write_after_transcribe(TID, {"start": 0, "end": 1, "whole": True, "sourcePath": self.media}, self.RUN)
        voices = os.path.join(self.tmp, "voices.json")
        with open(voices, "w") as f:
            f.write("{}")
        self.assertTrue(keys.write_diar(TID, {"requested": 2, "embedding": "e"}, voices))
        d = keys.read(keys.doc_key_path(TID, "diar"), "diar")
        self.assertEqual(d["inputs"]["transcribe"], keys.key_hash(keys.doc_key_path(TID, "transcribe"), "transcribe"))
        self.assertTrue(d["inputs"]["voices"])
        before = d["hash"]
        with open(voices, "w") as f:
            f.write('{"a":1}')   # 覚えた声が変わると別の鍵
        keys.write_diar(TID, {"requested": 2, "embedding": "e"}, voices)
        self.assertNotEqual(keys.key_hash(keys.doc_key_path(TID, "diar"), "diar"), before)

    def test_studio_export(self):
        spec = {"kind": "youtube", "videoId": "vid12345678", "fast": True, "maxHeight": 720, "volume": 100, "loudness": None}
        self.assertTrue(keys.write_studio_export(spec, self.media, 10, 20))
        k = keys.read(keys.media_key_path(self.media, "export"), "export")
        self.assertEqual(k["inputs"]["media"], {"kind": "archive", "videoId": "vid12345678"})
        self.assertEqual(k["inputs"]["settings"]["maxHeight"], 720)
        self.assertFalse(keys.write_studio_export({"kind": "live", "videoId": "x"}, self.media, 1, 2))   # 録画の配信は識別が無いので書かない
        self.assertFalse(keys.write_studio_export(spec, None, 1, 2))

    def test_pack(self):
        out = os.path.join(self.tmp, "pack")
        os.makedirs(out)
        keys.write_export(self.media, schemas.media_identity("archive", videoId="vid12345678"), 1, 9, {})
        plan = {"keeps": [[0, 1.5]]}
        self.assertTrue(keys.write_pack(out, self.media, plan, {"textplus": True}))
        k = keys.read(keys.pack_key_path(out), "pack")
        self.assertEqual(k["inputs"]["clips"], [keys.key_hash(keys.media_key_path(self.media, "export"), "export")])
        h = k["hash"]
        keys.write_pack(out, self.media, {"keeps": [[0, 2.5]]}, {"textplus": True})   # カット計画が変わる
        self.assertNotEqual(keys.key_hash(keys.pack_key_path(out), "pack"), h)


class TestArchiveSwap(_Env):
    def test_f1_rewrite_to_archive(self):
        rec = schemas.media_identity("recording", recorder="rc1", recording="20261005-190000")
        keys.write_export(self.media, rec, 100, 130, {"mode": "precise"})
        before = keys.key_hash(keys.media_key_path(self.media, "export"), "export")
        live_archive.Archiver._archive_key(self.media, {"videoId": "vid12345678", "start": 3600.0, "end": 3630.0})
        k = keys.read(keys.media_key_path(self.media, "export"), "export")
        self.assertEqual(k["inputs"]["media"], {"kind": "archive", "videoId": "vid12345678"})
        self.assertEqual((k["inputs"]["start"], k["inputs"]["end"]), (3600000, 3630000))
        self.assertEqual(k["inputs"]["settings"], {"mode": "precise"})   # 設定は引き継ぐ
        self.assertNotEqual(k["hash"], before)

    def test_f1_removes_key_when_write_fails(self):
        keys.write_export(self.media, schemas.media_identity("recording", recorder="rc1", recording="r1"), 1, 2, {})
        with mock.patch.object(keys, "write_export", return_value=False):
            live_archive.Archiver._archive_key(self.media, {"videoId": "vid12345678", "start": 1.0, "end": 2.0})
        self.assertIsNone(keys.read(keys.media_key_path(self.media, "export"), "export"))


if __name__ == "__main__":
    unittest.main()
