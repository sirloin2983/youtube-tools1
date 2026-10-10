#!/usr/bin/env python3
"""記録の土台(マスタープラン Q2。plan/line-bc-master-plan.md)のテスト。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_records -q                # これだけ(src/editor/tests で)

- 文字起こし: 行の proofedAt(初めて校正済みにした時刻。引き継ぐ・外れたら捨てる・機械が書き換えたら外す)・
  再認識の前の機械の出力を recognition.runs に範囲つきで残す(件数・行数の上限)・辞書の版(settings.dict / params.dict)
- カット: edit.json の draft(初めての保存のときだけ一度書く・以前の edit.json が読める・パックの記録で消えない)
- 校正の手間: POST /api/effort(updatedAt を変えない = 保存の競合に巻き込まない・累計)・保存で数える校正済みの行
- 生出力 <id>.asr.json(分ける前・置換の前の認識の結果。単語ごとの時刻と確信度)と GPU の精度の型(TRANSCRIBE_CUDA_COMPUTE)
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from test_backend import S, TID, StoreDir  # noqa: F401  (S = serve)
from test_edit import doc_obj, edit_obj
from human.proof import doc_jobs  # noqa: E402
from pipeline.transcribe import recognize  # noqa: E402
from pipeline.transcribe import records  # noqa: E402
from pipeline.transcribe import worker_client  # noqa: E402
from flow import jobs  # noqa: E402


def _rd(tid=TID):
    with open(S.tx_path(tid), encoding="utf-8") as f:
        return json.load(f)


def _seg(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


class TestProofedAt(StoreDir):
    def test_sanitize_sets_inherits_and_drops(self):
        before = int(time.time() * 1000)
        out = S.sanitize_transcript({"segments": [_seg(1, 0, 1, "a", proofed=True, proofedAt=5), _seg(2, 1, 2, "b", proofedAt=7)]}, {})["segments"]
        self.assertGreaterEqual(out[0]["proofedAt"], before)            # 画面の値(5)は使わない。保存済みに無ければ今
        self.assertNotIn("proofedAt", out[1])                           # 校正済みでない行には付けない
        base = {"segments": [_seg(1, 0, 1, "a", proofed=True, proofedAt=1234), _seg(2, 1, 2, "b", proofed=True, proofedAt=2345),
                             _seg(3, 2, 3, "c", proofed=True)]}          # s3 = この項目より前に校正済みにした行(時刻なし)
        out = S.sanitize_transcript({"segments": [_seg(1, 0, 1, "a2", proofed=True, proofedAt=99), _seg(2, 1, 2, "b"),
                                                  _seg(3, 2, 3, "c", proofed=True), _seg(4, 3, 4, "d", proofed=True)]}, base)["segments"]
        self.assertEqual(out[0]["proofedAt"], 1234)                     # 同じ id の行から引き継ぐ(文字を直しても初めての時刻のまま)
        self.assertNotIn("proofedAt", out[1])                           # 外した行は捨てる
        self.assertNotIn("proofedAt", out[2])                           # 以前から校正済みの行に、今の時刻を作らない
        self.assertGreaterEqual(out[3]["proofedAt"], before)
        # 外したあとにもう一度校正済みにしたら、その時刻から数え直す
        out2 = S.sanitize_transcript({"segments": [_seg(2, 1, 2, "b", proofed=True)]}, {"segments": out})["segments"]
        self.assertGreaterEqual(out2[0]["proofedAt"], before)

    def test_save_round_trip_and_old_lite_mark(self):
        """保存で付き、次の保存で引き継ぐ。以前の友人用簡易版の印(doc["lite"]。今は読まない)が残る文書も普通に保存できる"""
        for lite in (False, True):
            with self.subTest(lite=lite):
                d = doc_obj(**({"lite": {"streamer": "x"}} if lite else {}))
                self.put_doc(d)
                d["segments"][0]["proofed"] = True
                S.save_transcript(TID, dict(d, baseUpdatedAt=d["updatedAt"]))
                cur = _rd()
                at = cur["segments"][0]["proofedAt"]
                cur["segments"][0]["text"] = "直した"
                cur["segments"][0]["proofedAt"] = 1   # 画面が古い値を送っても
                time.sleep(0.01)
                S.save_transcript(TID, dict(cur, baseUpdatedAt=cur["updatedAt"]))
                self.assertEqual(_rd()["segments"][0]["proofedAt"], at)

    def test_retranscribe_drops_proofed_at(self):
        d = doc_obj(original=[{"start": 0.4, "end": 2.8, "text": "こんばんわ"}])
        d["segments"][0].update(proofed=True, proofedAt=1111)
        self.put_doc(d)
        S.apply_retranscribe({"tid": TID, "model": "m", "autoDict": False}, {"s1": ("こんばんは", "")})
        g = _rd()["segments"][0]
        self.assertNotIn("proofed", g)
        self.assertNotIn("proofedAt", g)


class TestReplacedRuns(StoreDir):
    def orig(self):
        return [{"start": 0.4, "end": 2.8, "text": "こんばんわ", "avg_logprob": -0.3}, {"start": 3.2, "end": 5.3, "text": "まって"},
                {"start": 6.0, "end": 8.3, "text": "あの"}, {"start": 8.8, "end": 11.1, "text": "それて"}]

    def put(self, **over):
        self.put_doc(doc_obj(original=self.orig(), recognition={"runs": [{"engine": "fake", "model": "small", "at": 1}]}, **over))

    def test_each_keeps_replaced_machine_output(self):
        self.put()
        S.apply_retranscribe({"tid": TID, "model": "large-v3", "autoDict": False, "beam": 5}, {"s2": ("待って", ""), "s4": ("それって", "")})
        d = _rd()
        runs = d["recognition"]["runs"]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0], {"engine": "fake", "model": "small", "at": 1})   # 最初の認識の記録はそのまま
        r = runs[1]
        self.assertEqual((r["kind"], r["model"], r["range"], r["spans"]), ("each", "large-v3", [3.2, 11.1], [[3.2, 5.3], [8.8, 11.1]]))
        self.assertEqual([o["text"] for o in r["replaced"]], ["まって", "それて"])   # 差し替える前の機械の出力
        self.assertIn("dict", r["settings"])
        self.assertEqual([o["text"] for o in d["original"]], ["こんばんわ", "待って", "あの", "それって"])

    def test_range_and_whole_skip_kept_rows(self):
        for mode in ("range", "whole"):
            with self.subTest(mode=mode):
                self.put()
                spec = {"tid": TID, "range": [0.0, 12.0], "ids": ["s2", "s3", "s4"], "model": "small", "autoDict": False, "mode": mode}
                S.apply_range(spec, [{"start": 3.0, "end": 11.5, "raw": "待ってあのーそれって", "flag": ""}])
                r = _rd()["recognition"]["runs"][-1]
                self.assertEqual((r["kind"], r["range"]), (mode, [0.0, 12.0]))
                self.assertNotIn("spans", r)
                self.assertEqual([o["text"] for o in r["replaced"]], ["まって", "あの", "それて"])   # s1(守った行)の機械の出力は差し替えないので入れない
                self.assertEqual(r["replaced"][0], {"start": 3.2, "end": 5.3, "text": "まって"})

    def test_redo(self):
        self.put()
        n = S.apply_redo({"tid": TID, "model": "large-v3"}, [("s3", "あのー", 5.8, 8.6, [{"start": 6.0, "end": 8.3, "raw": "あのですね", "flag": ""}])])
        self.assertEqual(n, 1)
        r = _rd()["recognition"]["runs"][-1]
        self.assertEqual((r["kind"], r["range"], [o["text"] for o in r["replaced"]]), ("redo", [5.8, 8.6], ["あの"]))

    def test_doc_without_original_or_recognition(self):
        self.put_doc(doc_obj())   # 文字起こしせずに開いた文書(original・recognition が無い)
        S.apply_retranscribe({"tid": TID, "model": "m", "autoDict": False}, {"s1": ("A", "")})
        r = _rd()["recognition"]["runs"]
        self.assertEqual((len(r), r[0]["kind"], r[0]["replaced"]), (1, "each", []))

    def test_limits(self):
        self.put()
        with patch.object(S, "MAX_RERUNS", 3):
            for i in range(5):
                S.apply_retranscribe({"tid": TID, "model": "m%d" % i, "autoDict": False}, {"s1": ("A%d" % i, "")})
        runs = _rd()["recognition"]["runs"]
        self.assertEqual([r.get("model") for r in runs], ["small", "m2", "m3", "m4"])   # 最初の認識は残し、再認識は新しい 3 件
        self.put()
        with patch.object(S, "MAX_REPLACED_ROWS", 3):
            S.apply_retranscribe({"tid": TID, "model": "a", "autoDict": False}, {"s1": ("A", ""), "s2": ("B", "")})
            S.apply_retranscribe({"tid": TID, "model": "b", "autoDict": False}, {"s3": ("C", ""), "s4": ("D", "")})
            runs = _rd()["recognition"]["runs"]
            self.assertEqual([r.get("model") for r in runs], ["small", "b"])          # 行の合計が上限を超えたら古い記録から
            S.apply_range({"tid": TID, "range": [0.0, 12.0], "ids": ["s1", "s2", "s3", "s4"], "model": "c", "autoDict": False},
                          [{"start": 0.3, "end": 11.5, "raw": "全部", "flag": ""}, {"start": 0.1, "end": 0.2, "raw": "x", "flag": ""}])
        r = _rd()["recognition"]["runs"][-1]
        self.assertEqual(r["model"], "c")
        self.assertLessEqual(len(r["replaced"]), 3)
        self.assertEqual(r["replacedOmitted"], 4 - len(r["replaced"]))


class TestDictVersion(StoreDir):
    def test_hashes(self):
        a = S.dict_version({"glossary": ["兎田ぺこら", "ぺこーら"]})
        self.assertEqual(len(a["glossary"]), 10)
        self.assertEqual(a, S.dict_version({"glossary": ["兎田ぺこら", "ぺこーら"]}))      # 同じ中身なら同じ版
        self.assertNotEqual(a["glossary"], S.dict_version({"glossary": ["兎田ぺこら"]})["glossary"])
        self.assertNotIn("replacements", a)                                                  # 使っていない辞書は入れない
        self.assertTrue(a.get("roster"))
        with open(S.SETTINGS, "w", encoding="utf-8") as f:
            json.dump({"replacements": "ぺこら=>ぺこら\nとわ様=>トワ様"}, f, ensure_ascii=False)
        r1 = S.dict_version({"autoDict": True})["replacements"]
        with open(S.SETTINGS, "w", encoding="utf-8") as f:
            json.dump({"replacements": "とわ様=>トワ様"}, f, ensure_ascii=False)
        self.assertNotEqual(r1, S.dict_version({"autoDict": True})["replacements"])          # 辞書を変えたら版が変わる
        self.assertIn("learned", S.dict_version({"autoLearned": True}))

    def test_recognition_run_has_dict(self):
        spec = {"engine": None, "model": "small", "language": "ja", "beam": 5, "vadMode": "normal", "glossary": ["ホロライブ"], "context": {}}
        run = S.recognition_run(spec, {}, 1.0, 1.0)
        self.assertEqual(run["settings"]["dict"], S.dict_version(spec))


class TestEditDraft(StoreDir):
    def setUp(self):
        super().setUp()
        self.put_doc(doc_obj())

    def draft(self, **over):
        d = {"origin": "rows", "settings": {"on": True, "after": 0.5, "before": 0.3, "padAfter": 0.2}, "keepsSec": [[0.3, 2.9], [3.1, 5.6]], "at": 1700000000000}
        d.update(over)
        return d

    def test_written_once(self):
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0, "draft": self.draft()})
        e = S.get_edit(TID)["edit"]
        self.assertEqual(e["draft"], self.draft())
        S.save_edit(TID, {"edit": edit_obj(clips=((0, 12),)), "baseRev": 1, "draft": self.draft(origin="silence")})   # 2回目以降は上書きしない
        self.assertEqual(S.get_edit(TID)["edit"]["draft"]["origin"], "rows")
        S.record_pack({"id": TID, "rev": 2, "docUpdatedAt": 1000, "dir": os.path.abspath(self.tmp), "files": []})   # パックの記録で消えない
        with open(S.edit_path(TID), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["draft"]["origin"], "rows")

    def test_old_edit_and_bad_draft(self):
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})   # 以前の画面(draft を送らない)
        g = S.get_edit(TID)
        self.assertEqual((g["rev"], "draft" in g["edit"]), (1, False))   # 以前の edit.json は今までどおり読める
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 1, "draft": self.draft()})
        self.assertNotIn("draft", S.get_edit(TID)["edit"])               # 後から足さない(始めたたき台が分からないため)
        os.unlink(S.edit_path(TID))
        for bad in (self.draft(origin="manual"), self.draft(keepsSec=[[2, 1]]), self.draft(keepsSec=[[3, 4], [1, 2]]), "x", self.draft(keepsSec="a")):
            with self.subTest(bad=str(bad)[:60]):
                r = S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0, "draft": bad})   # 記録の値が正しくなくてもカットは保存する
                self.assertEqual(r["rev"], 1)
                self.assertNotIn("draft", S.get_edit(TID)["edit"])
                os.unlink(S.edit_path(TID))
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0, "draft": self.draft(settings={"noise": -35, "x\n": 1, "s": "a" * 101, "ok": "abc", "b": [1]})})
        self.assertEqual(S.get_edit(TID)["edit"]["draft"]["settings"], {"noise": -35, "ok": "abc"})


class TestEffort(StoreDir):
    def setUp(self):
        super().setUp()
        self.put_doc(doc_obj())

    def test_add_does_not_touch_updated_at(self):
        r = S.add_effort({"id": TID, "activeSec": 30, "newSession": True})
        self.assertEqual({k: r["effort"][k] for k in ("activeSec", "cutSec", "sessions")}, {"activeSec": 30, "cutSec": 0, "sessions": 1})
        S.add_effort({"id": TID, "activeSec": 60, "cutSec": 30})
        d = _rd()
        self.assertEqual(d["updatedAt"], 1000)                                       # 記録のために updatedAt を動かさない
        self.assertEqual((d["effort"]["activeSec"], d["effort"]["cutSec"], d["effort"]["sessions"]), (90, 30, 1))
        S.save_transcript(TID, dict(d, baseUpdatedAt=1000, effort={"activeSec": 0}))  # 開いていた画面の保存は 409 にならず、累計も消さない
        self.assertEqual(_rd()["effort"]["activeSec"], 90)
        self.assertEqual(S.add_effort({"id": TID, "activeSec": 0})["effort"]["activeSec"], 90)   # 0 なら書かない
        for bad in ({"id": TID, "activeSec": -1}, {"id": TID, "activeSec": 3601}, {"id": TID, "activeSec": "30"}, {"id": TID, "activeSec": True},
                    {"id": TID, "activeSec": 1, "cutSec": 1.5}):
            with self.subTest(bad=bad):
                with self.assertRaises(S.ApiError) as cm:
                    S.add_effort(bad)
                self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(S.ApiError) as cm:
            S.add_effort({"id": "../x", "activeSec": 1})
        self.assertEqual(cm.exception.status, 404)

    def test_rows_counted_on_save_and_kept_on_restore(self):
        d = _rd()
        d["segments"][0]["proofed"] = d["segments"][1]["proofed"] = True
        S.save_transcript(TID, dict(d, baseUpdatedAt=1000))
        d = _rd()
        self.assertEqual((d["effort"]["proofedRows"], d["effort"]["unproofedRows"]), (2, 0))
        S.add_effort({"id": TID, "activeSec": 120, "newSession": True})
        d = _rd()
        d["segments"][1].pop("proofed")
        S.save_transcript(TID, dict(d, baseUpdatedAt=d["updatedAt"]))
        d = _rd()
        self.assertEqual((d["effort"]["proofedRows"], d["effort"]["unproofedRows"], d["effort"]["activeSec"]), (2, 1, 120))
        ts = S.hist_stamps(TID)[0]   # 校正済みにする前の版へ戻しても、手間の累計は戻さない
        S.restore_history(TID, ts)
        self.assertEqual(_rd()["effort"]["activeSec"], 120)


class TestCudaCompute(unittest.TestCase):
    def test_cuda_compute_env(self):
        with patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "int8_float16"}):
            self.assertEqual(worker_client.cuda_compute(), "int8_float16")
        with patch.dict(os.environ, {"TRANSCRIBE_CUDA_COMPUTE": "rm -rf"}):
            self.assertEqual(worker_client.cuda_compute(), "float16")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRANSCRIBE_CUDA_COMPUTE", None)
            self.assertEqual(worker_client.cuda_compute(), "float16")   # 既定は今までどおり


class TestAsrRaw(StoreDir):
    """生出力 transcripts/<id>.asr.json(分ける前・置換の前の認識の結果。単語ごとの時刻と確信度)"""

    def test_capture_raw_keeps_words_and_probs(self):
        segs = [{"start": 0.0, "end": 1.5, "text": "えーこんにちは", "avg_logprob": -0.21234, "words": [(0.0, 0.4, "えー"), (0.5, 1.5, "こんにちは")],
                 "wordProbs": [0.5, 0.98]},
                {"start": 2.0, "end": 3.0, "text": "テスト"}]
        raw = []
        out = list(records.capture_raw(iter(segs), raw, shift=10.0))
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
        d = recognize.seg_to_dict(Sg())
        self.assertEqual(d["words"], [(0.0, 0.5, "あ"), (0.5, 1.0, "い")])   # 3つ組は変えない
        self.assertEqual(d["wordProbs"], [0.9, None])

    def test_write_read_asr(self):
        records.write_asr("0123456789ab", [{"start": 0, "end": 1, "text": "x", "words": []}], {"model": "small"})
        with open(records.asr_path("0123456789ab"), encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d["run"], {"model": "small"})
        self.assertEqual(len(d["segments"]), 1)
        self.assertFalse(os.path.exists(records.asr_path("ffffffffffff")))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
    def test_fake_job_writes_asr(self):
        src = os.path.join(self.tmp, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=9", "-ar", "16000", src], check=True)
        spec = doc_jobs.validate_job({"sourcePath": src, "model": "small"})
        with patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0"}):
            job = jobs.add_job(spec)
            jobs._queue.get_nowait()   # 待機列のワーカーに取られないように、ここで直接動かす
            doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        with open(records.asr_path(job["tid"]), encoding="utf-8") as f:
            d = json.load(f)
        self.assertTrue(d["segments"])
        self.assertEqual(d["segments"][0]["text"], "テスト文1")
        self.assertEqual(d["run"]["engine"], "fake")


if __name__ == "__main__":
    unittest.main()
