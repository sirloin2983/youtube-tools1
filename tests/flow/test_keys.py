# -*- coding: utf-8 -*-
"""flow/keys(② 成果物の鍵を書く・読む。役割で組み直す RS6 b-K1)のテスト。

    py -3.12 -m unittest src/flow/tests/test_keys.py -v

- 書く・読む・壊れた鍵・stale の 3 通り(same / differ / none)・消す
- 段ごとの inputs・文書の鍵(transcribe・post・diar)・パックの鍵・スタジオの export の鍵
- F-1: 速報版を本番版に入れ替えたとき、export の鍵が媒体 = archive で書き直され、書けなければ消える
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしない(一時フォルダだけ)
import json
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests -> flow -> src
sys.path.insert(0, SRC)
from ytt.tests import testkit  # noqa: E402
from flow import keys, live_archive, packrec  # noqa: E402
from ytt import schemas, workdata  # noqa: E402

TID = "abc123def456"


class _Env(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "flowkeys_")
        self.tx = os.path.join(self.tmp, "transcripts")
        os.makedirs(self.tx)
        p = mock.patch.object(workdata, "TX_DIR", self.tx)
        p.start()
        self.addCleanup(p.stop)
        self.media = os.path.join(self.tmp, "clips", "a_0001.mp4")
        os.makedirs(os.path.dirname(self.media))
        testkit.write_text(self.media, "movie-bytes")
        packs = os.path.join(self.tmp, "packs")
        p = mock.patch.object(packrec, "packs_dir", lambda env=None, c2r_dir=None: packs)   # パックを作った記録は一時フォルダへ
        p.start()
        self.addCleanup(p.stop)

    def built(self, out):
        """out にパックの中身(動画 1 つ)と、パックを作った記録を置く(作り終えたパックの形 = keys.pack_state の same の条件)"""
        os.makedirs(out, exist_ok=True)
        v = os.path.join(out, "a_0001.mp4")
        testkit.write_text(v, "pack-movie")
        packrec.write_record({"out_dir": out, "files": [("video", v)]}, self.media, False)


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
        testkit.write_text(kp, "{not json")
        self.assertIsNone(keys.read(kp, "export"))
        testkit.write_json(kp, dict(schemas.make_key("export", {"a": 1}), inputs={"a": 2}))   # 書き換えられた鍵(hash が合わない)
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
        testkit.write_text(blocker, "x")
        self.assertFalse(keys.write("export", os.path.join(blocker, "sub", "k.json"), {"a": 1}))   # フォルダを作れない
        self.assertFalse(keys.write("nope", os.path.join(self.tmp, "k.json"), {"a": 1}))   # 段が正しくない

    def test_remove(self):
        kp = keys.doc_key_path(TID, "diar")
        keys.write("diar", kp, {"a": 1})
        self.assertTrue(keys.remove(kp))
        self.assertFalse(os.path.exists(kp))
        self.assertTrue(keys.remove(kp))   # 無くても真

    def test_doc_key_follows_index(self):
        """索引で 作業用 に置いた文書の鍵は、その 作業用 に書かれて読める"""
        from ytt import docloc
        work = os.path.join(self.tmp, "案件", "作業用")
        os.makedirs(work)
        testkit.write_text(os.path.join(work, TID + ".json"), "{}")
        docloc.place(TID, work)
        kp = keys.doc_key_path(TID, "post")
        self.assertEqual(kp, os.path.join(os.path.normpath(work), TID + ".post.key.json"))
        keys.write("post", kp, {"a": 1})
        self.assertTrue(os.path.isfile(kp))
        self.assertFalse(os.path.exists(os.path.join(self.tx, TID + ".post.key.json")))

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

    def test_post_key_learning_version(self):
        """学習データの版(束の post.learning.version)は後処理の鍵に入る。空(既定)なら今の鍵と同じ inputs"""
        self.assertEqual(keys.post_inputs("h", {"v": 2}, {"g": 1}), {"transcribe": "h", "post": {"v": 2}, "dict": {"g": 1}})
        self.assertEqual(keys.post_inputs("h", {"v": 2}, {"g": 1}, "")["transcribe"], "h")
        self.assertNotIn("learning", keys.post_inputs("h", {"v": 2}, {"g": 1}, ""))
        spec = {"start": 0.0, "end": 4.0, "whole": True, "sourcePath": self.media, "learningVersion": "v7"}
        self.assertEqual(keys.write_after_transcribe(TID, spec, self.RUN), 2)
        self.assertEqual(keys.read(keys.doc_key_path(TID, "post"), "post")["inputs"]["learning"], "v7")

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
        testkit.write_text(voices, "{}")
        self.assertTrue(keys.write_diar(TID, {"requested": 2, "embedding": "e"}, voices))
        d = keys.read(keys.doc_key_path(TID, "diar"), "diar")
        self.assertEqual(d["inputs"]["transcribe"], keys.key_hash(keys.doc_key_path(TID, "transcribe"), "transcribe"))
        self.assertTrue(d["inputs"]["voices"])
        before = d["hash"]
        testkit.write_text(voices, '{"a":1}')   # 覚えた声が変わると別の鍵
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
        self.assertTrue(keys.write_pack(out, {"video": self.media, "keeps": [[0, 1.5]]}, {"textplus": True}))
        k = keys.read(keys.pack_key_path(out), "pack")
        self.assertEqual(k["inputs"]["clips"], [keys.key_hash(keys.media_key_path(self.media, "export"), "export")])
        h = k["hash"]
        keys.write_pack(out, {"video": self.media, "keeps": [[0, 2.5]]}, {"textplus": True})   # カットが変わる
        self.assertNotEqual(keys.key_hash(keys.pack_key_path(out), "pack"), h)
        self.assertFalse(keys.write_pack(out, {"video": self.media}, {"textplusFps": "7"}))   # 形が違う = 書かない(ログだけ)


class TestReadK2(_Env):
    """鍵を読む(RS6 b-K2): 文字起こしは今の要求の材料と・パックは今の本文と比べる(same / differ / none)"""
    REQ = {"model": "small", "language": "ja", "quality": "best", "vadMode": "weak", "boost": False, "device": "auto"}

    def setUp(self):
        super().setUp()
        from pipeline.transcribe import backend
        from eval.fake import fake_asr
        saved = backend._selector[0]
        backend.set_selector(lambda: fake_asr.FAKE)   # 記録に書くエンジンと版 = 疑似の ("fake", "")
        self.addCleanup(backend.set_selector, saved)
        p = mock.patch.object(workdata, "ROOT", self.tmp)   # モデル名の検査(worker_client.valid_model)が読む
        p.start()
        self.addCleanup(p.stop)

    def write_tx(self, tid=TID, model="small"):
        run = {"engine": "fake", "engineVersion": "", "model": model, "language": "ja", "settings": {"beam": 5, "vadMode": "weak", "boost": False}}
        self.assertEqual(keys.write_after_transcribe(tid, {"sourcePath": self.media, "whole": True}, run), 2)

    def test_transcribe_state(self):
        self.assertEqual(keys.transcribe_state(TID, self.media, self.REQ), "none")   # 鍵なし
        self.write_tx()
        self.assertEqual(keys.transcribe_state(TID, self.media, self.REQ), "same")
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, model="large-v3")), "differ")   # 設定が違う
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, quality="fast")), "differ")
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, model="../x")), "none")   # 今の材料が分からない
        keys.write_export(self.media, schemas.media_identity("archive", videoId="vid12345678"), 1, 9, {})   # 切り抜きを書き出し直した
        self.assertEqual(keys.transcribe_state(TID, self.media, self.REQ), "differ")
        self.assertEqual(keys.transcribe_state("bad id", self.media, self.REQ), "none")

    def test_transcribe_state_device(self):
        """機器は cuda のときだけ鍵に入る(F1 F6a): vulkan は鍵に入れない = 作り直さない・cuda と vulkan は別の物"""
        self.write_tx()   # 機器なしで書いた(今までの鍵)
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, engine="faster-whisper", device="vulkan")), "same")
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, engine="faster-whisper", device="cuda")), "differ")
        run = {"engine": "fake", "engineVersion": "", "model": "small", "language": "ja", "settings": {"beam": 5, "vadMode": "weak", "boost": False}}
        keys.write_after_transcribe(TID, {"sourcePath": self.media, "whole": True, "device": "cuda"}, run)
        self.assertEqual(keys.read(keys.doc_key_path(TID, "transcribe"), "transcribe")["inputs"]["device"], "cuda")
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, engine="faster-whisper", device="cuda")), "same")
        self.assertEqual(keys.transcribe_state(TID, self.media, dict(self.REQ, engine="faster-whisper", device="vulkan")), "differ")
        self.assertNotIn("device", keys.transcribe_inputs("h", "e", "1", "m", "ja", 5, "weak", False, device="vulkan"))

    def test_pack_state(self):
        body = {"spec": {"video": self.media, "mode": "silence", "silence": {"noise": -35}}, "output": {"textplus": True, "textplusFps": "30"}}
        calls = []

        def make(b=body):
            calls.append(1)
            return b, None, 0
        self.assertEqual(keys.pack_state(self.media, make), ("none", None))
        self.assertEqual(calls, [])   # 鍵が無ければ本文を作らない
        out = str(keys._pack.default_out_dir(self.media))
        os.makedirs(out)
        self.assertTrue(keys.write_pack(out, body["spec"], body["output"]))
        self.assertEqual(keys.pack_state(self.media, make)[0], "differ")   # 鍵は同じでもパックを作った記録・中身が無い = 作り直す(部品 F3)
        self.built(out)
        self.assertEqual(keys.pack_state(self.media, make)[0], "same")
        with open(os.path.join(out, "a_0001.mp4"), "wb"):
            pass   # 中身の動画が空になった
        self.assertEqual(keys.pack_state(self.media, make)[0], "differ")
        self.built(out)
        same = {"spec": dict(body["spec"]), "output": {"textplus": True, "volume": 100, "speakerColors": True}}   # 既定の値・省略の違いはそろえる
        self.assertEqual(keys.pack_state(self.media, lambda: same)[0], "same")
        other = {"spec": body["spec"], "output": dict(body["output"], textplusWrap=8)}
        self.assertEqual(keys.pack_state(self.media, lambda: other)[0], "differ")   # 設定が違う
        keys.write("pack", keys.pack_key_path(out), keys.pack_inputs(["x"], "plan-hash", {}))   # b-K1 の形の鍵(form なし)= 鍵なしと同じ
        self.assertEqual(keys.pack_state(self.media, make)[0], "none")

    def test_pack_state_sees_new_subtitles(self):
        tr = os.path.join(self.tmp, "t.transcript.json")

        def write_tr(text, at):
            testkit.write_json(tr, {"createdAt": at, "tool": {"version": at}, "segments": [{"start": 0, "end": 1, "text": text}]})
        write_tr("あ", "1")
        body = {"spec": {"video": self.media, "transcript": tr, "preset": "transcript-rows"}, "output": {"textplus": True}}
        out = str(keys._pack.default_out_dir(self.media))
        self.built(out)
        keys.write_pack(out, body["spec"], body["output"])
        write_tr("あ", "2")   # 作り直しただけ(作った日時が違う)= 同じ
        self.assertEqual(keys.pack_state(self.media, lambda: body)[0], "same")
        write_tr("い", "3")   # 字幕が新しい
        self.assertEqual(keys.pack_state(self.media, lambda: body)[0], "differ")

class TestPackRecord(_Env):
    """パックを作った記録(② flow/packrec)。API と CLI が同じ after_build を呼ぶ(設計原則の指摘 3)"""

    def test_after_build_writes_record_and_key(self):
        out = str(keys._pack.default_out_dir(self.media))
        os.makedirs(out)
        v = os.path.join(out, "a_0001.mp4")
        testkit.write_text(v, "pack-movie")
        res = {"out_dir": out, "files": [("video", v)], "plan": {"cuts": 1}, "editMedia": None}
        body = {"spec": {"video": self.media, "keeps": [[0, 1]]}, "output": {"textplus": False}}
        self.assertEqual(packrec.after_build(res, self.media, body["spec"], body["output"], False, tool={"name": "flow"}), [])
        rec = packrec.read_record(out)
        self.assertEqual((rec["tool"], rec["files"], rec["cutPlan"]), ({"name": "flow"}, ["a_0001.mp4"], {"cuts": 1}))
        self.assertEqual(packrec.ready(out), (True, ""))
        self.assertEqual(keys.pack_state(self.media, lambda: body)[0], "same")   # 鍵も同じ口で書いた
        old = {"spec": body["spec"], "output": dict(body["output"], backup=True)}   # 要求に backup(予備。決定 3-34)があっても鍵を変えない
        self.assertEqual(keys.pack_state(self.media, lambda: old)[0], "same")
        os.unlink(v)
        self.assertIsNone(packrec.read_record(out))   # 中身が 1 つも無い = 記録は無効
        self.assertEqual(keys.pack_state(self.media, lambda: body)[0], "differ")

    def test_ready_needs_lua_for_textplus(self):
        out = os.path.join(self.tmp, "p")
        os.makedirs(out)
        v = os.path.join(out, "a.mp4")
        testkit.write_text(v, "x")
        packrec.write_record({"out_dir": out, "files": [("video", v)]}, self.media, True)
        self.assertEqual(packrec.ready(out)[0], False)

    def test_write_failure_is_a_warning(self):
        with mock.patch.object(packrec, "write_record", side_effect=OSError("書けない")):
            w = packrec.after_build({"out_dir": self.tmp, "files": []}, self.media, {"video": self.media}, {}, False)
        self.assertEqual(len(w), 1)


if __name__ == "__main__":
    unittest.main()
