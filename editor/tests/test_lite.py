#!/usr/bin/env python3
"""友人用 文字起こし簡易版(docs/plan/friend-lite-plan.md)のサーバー側のテスト。
L1 = 共通コアの editor 側(GPU の精度の型・生出力 <id>.asr.json・話者のふちの色)。
L2 = 書き出し(ed_lite.py。Resolve 用ファイルと送る用 zip)。

    python -m unittest editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest editor/tests/test_lite.py      # これだけ
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(TESTS)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import serve as S  # noqa: E402
import ed_jobs  # noqa: E402
import ed_store  # noqa: E402


class _Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.tmp, os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class LiteCoreCompute(unittest.TestCase):
    def test_cuda_compute_env(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "int8_float16"}):
            self.assertEqual(ed_jobs.cuda_compute(), "int8_float16")
        with mock.patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "rm -rf"}):
            self.assertEqual(ed_jobs.cuda_compute(), "float16")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRANSCRIBE_CUDA_COMPUTE", None)
            self.assertEqual(ed_jobs.cuda_compute(), "float16")   # 編集は今までどおり


class LiteCoreRaw(_Store):
    def test_capture_raw_keeps_words_and_probs(self):
        segs = [{"start": 0.0, "end": 1.5, "text": "えーこんにちは", "avg_logprob": -0.21234, "words": [(0.0, 0.4, "えー"), (0.5, 1.5, "こんにちは")],
                 "wordProbs": [0.5, 0.98]},
                {"start": 2.0, "end": 3.0, "text": "テスト"}]
        raw = []
        out = list(ed_jobs.capture_raw(iter(segs), raw, shift=10.0))
        self.assertEqual(out, segs)   # 流れはそのまま
        self.assertEqual(raw[0]["start"], 10.0)
        self.assertEqual(raw[0]["words"], [[10.0, 10.4, "えー", 0.5], [10.5, 11.5, "こんにちは", 0.98]])
        self.assertEqual(raw[0]["avg_logprob"], -0.2123)
        self.assertEqual(raw[1]["words"], [])

    def test_seg_to_dict_word_probs(self):
        class W:
            def __init__(self, a, b, t, p):
                self.start, self.end, self.word, self.probability = a, b, t, p

        class Sg:
            start, end, text = 0.0, 1.0, " あ い "
            words = [W(0.0, 0.5, "あ", 0.9), W(0.5, 1.0, "い", None)]
        d = ed_jobs.seg_to_dict(Sg())
        self.assertEqual(d["words"], [(0.0, 0.5, "あ"), (0.5, 1.0, "い")])   # 3つ組は変えない
        self.assertEqual(d["wordProbs"], [0.9, None])

    def test_write_read_asr(self):
        ed_jobs.write_asr("0123456789ab", [{"start": 0, "end": 1, "text": "x", "words": []}], {"model": "small"})
        d = ed_jobs.read_asr("0123456789ab")
        self.assertEqual(d["run"], {"model": "small"})
        self.assertEqual(len(d["segments"]), 1)
        self.assertIsNone(ed_jobs.read_asr("ffffffffffff"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
    def test_fake_job_writes_asr(self):
        src = os.path.join(self.tmp, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=9", "-ar", "16000", src], check=True)
        spec = ed_jobs.validate_job({"sourcePath": src, "model": "small"})
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0"}):
            job = ed_jobs.add_job(spec)
            ed_jobs._queue.get_nowait()   # 待機列のワーカーに取られないように、ここで直接動かす
            ed_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        d = ed_jobs.read_asr(job["tid"])
        self.assertTrue(d["segments"])
        self.assertEqual(d["segments"][0]["text"], "テスト文1")
        self.assertEqual(d["run"]["engine"], "fake")


class LiteCoreSpeakers(unittest.TestCase):
    def test_outline_saved(self):
        doc = ed_store.sanitize_transcript({"speakers": [{"id": "A", "name": "a", "color": "#ffe600", "outline": "#000000"},
                                                         {"id": "B", "name": "b", "color": "#ffffff", "outline": "red;x"}], "segments": []})
        self.assertEqual(doc["speakers"][0]["outline"], "#000000")
        self.assertNotIn("outline", doc["speakers"][1])


# ---------------------------------------------------------------- L2 書き出し(ed_lite)

import io  # noqa: E402
import zipfile  # noqa: E402
import ed_lite  # noqa: E402
from ytt_core import evaldata as EV  # noqa: E402


def make_video(path, sec=16, fps=60):   # 疑似の文字起こしは 4 秒ごとに1行 = 4 行
    """60fps・横 640x360・音つきのテスト用動画(Resolve の 30fps のプロジェクトに置く場合と同じ組み合わせ)"""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=%d:duration=%d" % (fps, sec),
                    "-f", "lavfi", "-i", "sine=f=440:d=%d" % sec, "-c:v", "mpeg4", "-q:v", "8", "-c:a", "aac", "-shortest", path], check=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg・ffprobe が必要")
class LiteExport(_Store):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "出力")
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "LITE_MODEL": "small",
                                                "LITE_OUT_DIR": self.out})
        self.env.start()
        self.video = os.path.join(self.tmp, "配信 動画.mp4")
        make_video(self.video)

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def transcribe(self, **req):
        job = ed_lite.start(dict({"path": self.video, "streamer": "兎田ぺこら", "sourceUrl": "https://www.youtube.com/watch?v=abc"}, **req))
        ed_jobs._queue.get_nowait()   # 待機列のワーカーに取られないように、ここで直接動かす
        j = ed_jobs._jobs[job["id"]]
        ed_jobs.run_job(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        return j["tid"]

    def test_start_validation(self):
        with self.assertRaises(S.ApiError) as c:
            ed_lite.start({"path": self.video, "streamer": "  "})
        self.assertEqual(c.exception.code, "no_streamer")
        with self.assertRaises(S.ApiError) as c:
            ed_lite.start({"path": self.video, "streamer": "a", "sourceUrl": "javascript:alert(1)"})
        self.assertEqual(c.exception.code, "bad_url")

    def test_new_doc_has_lite_and_default_speaker(self):
        tid = self.transcribe()
        doc = ed_store.read_transcript(tid)
        self.assertEqual(doc["lite"]["streamer"], "兎田ぺこら")
        self.assertEqual(doc["speakers"], [{"id": "A", "name": "兎田ぺこら", "color": "#FFE600", "outline": "#000000"}])
        self.assertTrue(all(g["speaker"] == "A" for g in doc["segments"]))
        self.assertEqual(ed_lite.load_settings()["streamers"][0], "兎田ぺこら")
        self.assertEqual([w["id"] for w in ed_lite.works()], [tid])
        # 保存しても印は消えない(sanitize_transcript は文書の他の項目を残す)
        doc2 = ed_store.save_transcript(tid, {"speakers": doc["speakers"], "segments": doc["segments"], "baseUpdatedAt": doc["updatedAt"]})
        self.assertEqual(doc2["lite"]["streamer"], "兎田ぺこら")

    def test_export_pack_and_zip(self):
        tid = self.transcribe()
        doc = ed_store.read_transcript(tid)
        segs = doc["segments"]
        self.assertEqual(len(segs), 4)   # 4 行目は確認しないまま
        segs[0].update(text="えー [笑] こんにちは", proofed=True)
        segs[1].update(text="[?]", proofed=True, speaker="B")          # 記号だけ = 字幕にしない(評価には残す)
        segs[2].update(text="それな(笑)", proofed=True, speaker="B")    # 形式違い = 評価でその行だけ外す
        speakers = doc["speakers"] + [{"id": "B", "name": "さくらみこ", "color": "#FF8FC8", "outline": "#5C1B47"}]
        ed_store.save_transcript(tid, {"speakers": speakers, "segments": segs, "baseUpdatedAt": doc["updatedAt"]})
        r = ed_lite.append_ops({"id": tid, "ops": [{"op": "confirm", "row": segs[0]["id"], "played": True}, {"op": "confirm", "row": segs[1]["id"], "played": False},
                                                   {"op": "hack", "row": "x"}, {"op": "time", "row": segs[0]["id"], "edge": "start", "from": 0, "to": 0.1}]})
        self.assertEqual(r["saved"], 3)

        res = ed_lite.export_now(tid)
        date = time.strftime("%Y-%m-%d", time.localtime(ed_store.read_transcript(tid)["createdAt"] / 1000))
        name = "%s_兎田ぺこら_%s" % (date, tid)
        self.assertEqual(res["zipName"], name + ".zip")
        zpath = os.path.join(self.out, name, "送る用ファイル", name + ".zip")
        self.assertEqual(EV.check_zip(zpath)[1], [])
        with zipfile.ZipFile(zpath) as z:
            self.assertEqual(sorted(z.namelist()), sorted(EV.FILES))
            final = json.loads(z.read("final.json"))
            meta = json.loads(z.read("meta.json"))
            raw = json.loads(z.read("asr_raw.json"))
            edits = EV.read_edits(z.read("edits.jsonl"))
            self.assertEqual(z.read("audio.flac")[:4], b"fLaC")
            blob = b"".join(z.read(n) for n in ("final.json", "meta.json", "asr_raw.json", "edits.jsonl")).decode("utf-8")
        # 記号は評価データに残す・生出力との対応・話者
        self.assertEqual(final["rows"][0]["text"], "えー [笑] こんにちは")
        self.assertEqual(final["rows"][1]["speaker"], "さくらみこ")
        self.assertEqual(final["rows"][0]["raw"], [0])
        self.assertTrue(final["rows"][0]["checked"])
        self.assertEqual(raw["source"], "asr")
        self.assertEqual(raw["run"]["model"], "small")
        self.assertEqual(meta["streamer"], "兎田ぺこら")
        self.assertEqual(meta["performers"], ["さくらみこ", "兎田ぺこら"])
        self.assertEqual(meta["sourceUrl"], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(meta["sourceName"], "配信 動画.mp4")
        self.assertEqual(meta["fps"], "30/1")   # 60fps の動画は lite-media/ に 30fps の写しを作って使う(Q1。名前は元のまま)
        self.assertEqual(meta["rulesVersion"], EV.RULES_VERSION)
        self.assertEqual(len(edits), 3)
        self.assertEqual(meta["notes"]["confirmedWithoutListening"], 1)
        # 絶対パス・PC のユーザー名を入れない
        self.assertEqual(EV.find_abs_paths([final, meta, raw]), [])
        self.assertNotIn(self.tmp.replace("\\", "\\\\"), blob)
        self.assertNotIn(os.path.expanduser("~").replace("\\", "\\\\"), blob)
        # 書き出しの知らせ: 未確認の行・形式違い
        self.assertTrue(any("確認していない行" in w for w in res["warnings"]))
        self.assertTrue(any("記号の形が違う行が 1 行" in w for w in res["warnings"]))
        # Resolve 用ファイル: 記号を除いた字幕・空の行は無し・字幕の型 lite・話者ごとのふち
        pack_dir = os.path.join(self.out, name, "Resolve用ファイル")
        self.assertTrue(os.path.isfile(os.path.join(pack_dir, "Resolveでの手順.txt")))
        self.assertTrue(os.path.isfile(os.path.join(pack_dir, "配信 動画.mp4")))
        _pack, tp = ed_lite._pack_mod()
        with open(os.path.join(pack_dir, "create_resolve_textplus_project.lua"), encoding="utf-8") as f:
            plan = tp.read_script_plan(f.read())
        texts = [c["text"].replace("\n", "") for c in plan["captions"]]
        self.assertEqual(texts[0], "えーこんにちは")
        self.assertNotIn("", texts)
        self.assertFalse(any("[?]" in t or "[笑]" in t for t in texts))
        self.assertIn("MS Gothic", plan["style"]["fonts"])
        self.assertEqual(plan["target"]["fps"], 30)
        self.assertEqual((plan["target"]["width"], plan["target"]["height"]), (1920, 1080))
        self.assertEqual(plan["captions"][1].get("outline"), tp.hex_rgba("#5C1B47"))   # 2つ目の字幕 = 「それな(笑)」(さくらみこ)
        self.assertEqual(plan["captions"][0].get("fill"), tp.hex_rgba("#FFE600"))
        self.assertNotIn("videoTracks", plan)                                        # 既定 = 映像トラック 1 本(V2 に字幕)
        with open(os.path.join(pack_dir, "Resolveでの手順.txt"), encoding="utf-8-sig") as f:
            self.assertIn("V1 映像・A1 音声・V2 Text+ 字幕", f.read())
        # 書き出し直し(上書き)もできる。映像トラックの数を選ぶと、覚えて Lua と手順書に入る(字幕は一番上 = V4)
        ed_lite.save_settings({"videoTracks": 3})
        self.assertEqual(ed_lite.export_now(tid)["zipName"], name + ".zip")
        with open(os.path.join(pack_dir, "create_resolve_textplus_project.lua"), encoding="utf-8") as f:
            self.assertEqual(tp.read_script_plan(f.read())["videoTracks"], 3)
        with open(os.path.join(pack_dir, "Resolveでの手順.txt"), encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("V1〜V3 同じ映像(重ねて加工する用。V2 から上は映像だけ)・V4 Text+ 字幕(一番上)", text)
        self.assertIn("V4 の Text+ を選び", text)
        self.assertEqual(ed_lite.read_export_record(tid)["counts"]["rows"], len(segs))

    def test_open_folder_only_inside_out_root(self):
        tid = self.transcribe()
        with self.assertRaises(S.ApiError):
            ed_lite.open_folder({"id": tid})   # まだ書き出していない
        ed_lite.export_now(tid)
        with mock.patch.object(ed_lite, "_start_folder") as m:
            ed_lite.open_folder({"id": tid, "what": "send"})
            self.assertTrue(m.call_args[0][0].endswith("送る用ファイル"))
        rec = ed_lite.read_export_record(tid)
        rec["zip"] = os.path.join(self.tmp, "外", "x.zip")
        os.makedirs(os.path.join(self.tmp, "外"))
        S.atomic_write(ed_lite.export_record_path(tid), json.dumps(rec).encode("utf-8"))
        with mock.patch.object(ed_lite, "_start_folder") as m, self.assertRaises(S.ApiError):
            ed_lite.open_folder({"id": tid, "what": "send"})
        m.assert_not_called()


class LiteUpload(_Store):
    def test_receive_upload(self):
        data = b"x" * 1000
        r = ed_lite.receive_upload(io.BytesIO(data), len(data), r"C:\Users\someone\動画 1.mp4")
        self.assertTrue(r["path"].startswith(ed_lite.media_dir()))
        self.assertTrue(r["name"].endswith("動画_1.mp4"))
        with open(r["path"], "rb") as f:
            self.assertEqual(f.read(), data)

    def test_bad_uploads(self):
        with self.assertRaises(S.ApiError):
            ed_lite.receive_upload(io.BytesIO(b"x"), 1, "evil.exe")
        with self.assertRaises(S.ApiError):
            ed_lite.receive_upload(io.BytesIO(b"x"), 0, "a.mp4")
        with self.assertRaises(S.ApiError) as c:
            ed_lite.receive_upload(io.BytesIO(b"xx"), 10, "a.mp4")   # 途中で切れた
        self.assertEqual(c.exception.code, "upload_cut")
        self.assertEqual(os.listdir(ed_lite.media_dir()), [])   # 書きかけは残さない


class LiteSettings(_Store):
    def test_settings_and_palette(self):
        s = ed_lite.save_settings({"worker": "友人<A>", "speakerStyles": {"さくらみこ": {"color": "#ff8fc8", "outline": "#000000"}, "bad": {"color": "red"}}})
        self.assertEqual(s["worker"], "友人A")
        self.assertEqual(s["speakerStyles"], {"さくらみこ": {"color": "#FF8FC8", "outline": "#000000"}})
        p = ed_lite.palette()
        self.assertEqual(p["text"][0]["hex"], "#FFE600")
        self.assertEqual(p["outline"][0]["hex"], "#000000")
        with mock.patch.object(ed_lite, "COLORS_FILE", os.path.join(self.tmp, "none.json")):
            self.assertEqual(ed_lite.palette(), ed_lite.FALLBACK_COLORS)

    def test_video_tracks_setting(self):
        """映像トラックの数: 既定 1・1〜5 だけ覚える(範囲の外・数でない値は断って前の値のまま)"""
        self.assertEqual(ed_lite.load_settings()["videoTracks"], 1)
        self.assertEqual(ed_lite.save_settings({"videoTracks": 5})["videoTracks"], 5)
        for bad in (0, 6, "3", True, None, 2.0):
            with self.assertRaises(S.ApiError):
                ed_lite.save_settings({"videoTracks": bad})
        self.assertEqual(ed_lite.load_settings()["videoTracks"], 5)
        self.assertEqual(ed_lite.save_settings({"worker": "x"})["videoTracks"], 5)   # 他の設定を保存しても残る


if __name__ == "__main__":
    unittest.main(verbosity=2)
