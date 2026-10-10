#!/usr/bin/env python3
"""2つ目のエンジンとの食い違いに候補を出す(精度改善の計画 第2版 D1-b。editor/ed_alt.py)のテスト。

    py -3.10 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest test_alt -q                    # これだけ(src/editor/tests で)

- alt_diffs(純粋な関数): 置き換え・表記だけの違いは出さない・片方だけの文字・長すぎ・行またぎ・行の大半が違う・校正済み・窓
- 提案(GET /api/suggest の suggest_for_doc)に足す・却下で消える・学習の提案を優先・評価用には出さない・採用/却下の数え方(学習の統計に入れない)
- ジョブ(疑似の認識 TRANSCRIBE_BACKEND=fake + TRANSCRIBE_FAKE_ALT): alt.json を書く・文書は書き換えない(updatedAt も)・
  評価用/同じエンジンとモデル/文字の無い文書/動画の無い文書は断る・autoAlt(設定と要求)・設定 altEngine の検査
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, TID, StoreDir, write_json  # noqa: F401,E402  (S = serve)
from eval.fake import fake_asr  # noqa: E402
from human.proof import alt as proof_alt  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from human.proof import store  # noqa: E402
from pipeline.transcribe import postproc  # noqa: E402
from flow import jobs  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))


def _row(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def _alt(a, b, text):
    return {"start": a, "end": b, "text": text}


class TestAltDiffs(unittest.TestCase):
    def test_replace(self):
        items, _st = S.alt_diffs([_row(1, 0, 3, "こんばんは白上フブキです")], [_alt(0, 3, "こんばんは、白神フブキです")])
        self.assertEqual(items, [{"seg": "s1", "i": 6, "wrong": "上", "right": "神", "tier": "alt", "pos": 0, "neg": 0}])

    def test_notation_only_is_not_a_candidate(self):
        """かなとカナ・句読点と空白・全角と半角・大小・伸ばし・ひらがなと漢字(読みが同じらしいもの)は候補にしない"""
        cases = [("ふぶきちゃん", "フブキちゃん"), ("こんにちは。元気", "こんにちは 元気!"), ("ＡＢＣです", "abcです"),
                 ("OKです", "okです"), ("すごーいね", "すごいね"), ("すごいね", "凄いね")]
        for a, b in cases:
            with self.subTest(a=a, b=b):
                items, st = S.alt_diffs([_row(1, 0, 3, a)], [_alt(0, 3, b)])
                self.assertEqual(items, [])
        self.assertEqual(S.alt_diffs([_row(1, 0, 3, "すごいね")], [_alt(0, 3, "凄いね")])[1]["notation"], 1)

    def test_insert_and_delete_become_replacements(self):
        """片方だけにある文字は、隣の 1 文字を足して置き換えの形に(wrong も right も空にしない)。画面の採用(位置で置き換え)で alt の文字になる"""
        for main, other, want in (("今日は雨です", "今日は大雨です", ("は", "は大")), ("今日は大雨です", "今日は雨です", ("は大", "は")),
                                  ("雨です", "大雨です", ("雨", "大雨"))):
            with self.subTest(main=main):
                items, _st = S.alt_diffs([_row(1, 0, 3, main)], [_alt(0, 3, other)])
                self.assertEqual([(x["wrong"], x["right"]) for x in items], [want])
                x = items[0]
                self.assertEqual(main[:x["i"]] + x["right"] + main[x["i"] + len(x["wrong"]):], other)

    def test_too_long_cross_and_mostly(self):
        long_a, long_b = "あ" * 3 + "かきくけこさしすせそたちつ" + "あ" * 30, "あ" * 3 + "なにぬねのはひふへほまみむ" + "あ" * 30
        items, st = S.alt_diffs([_row(1, 0, 5, long_a)], [_alt(0, 5, long_b)])
        self.assertEqual((items, st["long"]), ([], 1))
        # 行をまたぐ置き換え(1行目の終わり〜2行目の始まり)
        items, st = S.alt_diffs([_row(1, 0, 2, "ここからあいう"), _row(2, 2, 4, "えおそれから")], [_alt(0, 4, "ここからあいかきおそれから")])
        self.assertEqual((items, st["cross"]), ([], 1))
        # 行の文字の半分以上が違う行には出さない
        items, st = S.alt_diffs([_row(1, 0, 3, "今日はマイクラをやります")], [_alt(0, 3, "きょうはマインクラフトやります")])
        self.assertEqual(items, [])
        self.assertGreaterEqual(st["mostly"], 1)

    def test_proofed_rows_and_empty(self):
        rows = [_row(1, 0, 3, "白上フブキです", proofed=True), _row(2, 3, 6, "大神ミオです")]
        items, _st = S.alt_diffs(rows, [_alt(0, 3, "白神フブキです"), _alt(3, 6, "大上ミオです")])
        self.assertEqual([(x["seg"], x["wrong"], x["right"]) for x in items], [("s2", "神", "上")])
        self.assertEqual(S.alt_diffs([], [_alt(0, 1, "a")]), ([], {"long": 0, "cross": 0, "mostly": 0, "notation": 0, "edge": 0}))
        self.assertEqual(S.alt_diffs(rows, [])[0], [])

    def test_windows_on_a_long_document(self):
        """長い文書は時刻の窓ごとにそろえる(窓が複数・遠い所の食い違いも正しい行に・2つ目のエンジンの時刻が少しずれていても)"""
        rows, alts = [], []
        for i in range(400):   # 20 分(3 秒ごと)
            t = "第%d番目の行です" % i
            rows.append(_row(i, i * 3.0, i * 3.0 + 2.5, t))
            alts.append(_alt(i * 3.0 + 0.4, i * 3.0 + 2.9, t.replace("行", "業") if i in (5, 250, 399) else t))
        self.assertGreater(len(proof_alt._alt_windows(sorted([dict(r, n=k) for k, r in enumerate(rows)], key=lambda r: r["start"]))), 5)
        items, st = S.alt_diffs(rows, alts)
        self.assertEqual([(x["seg"], x["wrong"], x["right"]) for x in items], [("s5", "行", "業"), ("s250", "行", "業"), ("s399", "行", "業")])
        self.assertEqual(st["cross"], 0)

    def test_overlapping_candidates_are_dropped(self):
        items, _st = S.alt_diffs([_row(1, 0, 3, "あいうえおかきくけこさしすせそ")], [_alt(0, 3, "あいXえおかきYけこさしすせそ")])
        spans = [(x["i"], x["i"] + len(x["wrong"])) for x in items]
        self.assertTrue(all(not (a < d and c < b) for k, (a, b) in enumerate(spans) for (c, d) in spans[k + 1:]))
        self.assertEqual(len(items), 2)


class _AltStore(StoreDir):
    def setUp(self):
        super().setUp()
        self.fb = mock.patch.object(S, "FEEDBACK", os.path.join(self.tmp, "learn-feedback.json"))
        self.fb.start()
        proof_alt._alt_cache.clear()

    def tearDown(self):
        self.fb.stop()
        super().tearDown()

    def doc(self, **over):
        d = {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "", "start": 0, "end": 10, "updatedAt": 1000,
             "segments": [_row(1, 0, 3, "白上フブキです"), _row(2, 3, 6, "大神ミオです")], "original": []}
        d.update(over)
        return d

    def put_alt(self, rows, tid=TID, **over):
        write_json(S.alt_path(tid), dict({"schema": S.ALT_SCHEMA, "id": tid, "engine": "llama.cpp", "model": "qwen3-asr-1.7b", "at": 5,
                                          "range": [0, 10], "rows": rows}, **over))


class TestAltSuggest(_AltStore):
    def test_suggest_adds_alt_and_dismiss_removes(self):
        self.put_doc(self.doc())
        self.put_alt([_alt(0, 3, "白神フブキです"), _alt(3, 6, "大上ミオです")])
        r = S.suggest_for_doc(TID)
        alt = [x for x in r["items"] if x["tier"] == "alt"]
        self.assertEqual([(x["seg"], x["i"], x["wrong"], x["right"]) for x in alt], [("s1", 1, "上", "神"), ("s2", 1, "神", "上")])
        self.assertEqual((r["alt"]["engine"], r["alt"]["model"], r["alt"]["count"], r["alt"]["at"]), ("llama.cpp", "qwen3-asr-1.7b", 2, 5))
        # 却下: 学習の統計に入れず、数だけ fb["alt"]。却下した候補は出さない
        S.record_feedback({"tid": TID, "action": "reject", "items": [{"seg": "s1", "wrong": "上", "right": "神", "tier": "alt"}]})
        S.record_feedback({"tid": TID, "action": "accept", "items": [{"seg": "s2", "wrong": "神", "right": "上", "tier": "alt"},
                                                                       {"seg": "s2", "wrong": "ミオ", "right": "みお"}]})
        fb = S.load_feedback()
        self.assertEqual(fb["alt"], {"acc": 1, "rej": 1})
        self.assertEqual(list(fb["stat"]), ["ミオ=>みお"])   # 学習の提案の採用だけが統計に入る
        self.assertIn("s1|上=>神", fb["dismissed"][TID])
        r = S.suggest_for_doc(TID)
        self.assertEqual([(x["seg"], x["wrong"]) for x in r["items"] if x["tier"] == "alt"], [("s2", "神")])
        self.assertEqual(r["alt"]["count"], 1)

    def test_current_text_is_used(self):
        """候補は今の行の文字で毎回計算する(採用して直した所は消える)"""
        self.put_doc(self.doc())
        self.put_alt([_alt(0, 3, "白神フブキです"), _alt(3, 6, "大神ミオです")])
        self.assertEqual(len([x for x in S.suggest_for_doc(TID)["items"] if x["tier"] == "alt"]), 1)
        self.put_doc(self.doc(updatedAt=2000, segments=[_row(1, 0, 3, "白神フブキです"), _row(2, 3, 6, "大神ミオです")]))
        self.assertEqual([x for x in S.suggest_for_doc(TID)["items"] if x["tier"] == "alt"], [])

    def test_learned_suggestion_wins_and_eval_has_none(self):
        self.put_doc(self.doc())
        self.put_alt([_alt(0, 3, "白神フブキです"), _alt(3, 6, "大上ミオです")])
        d = self.doc()
        items, info = S.alt_suggest(TID, d, set(), [{"seg": "s1", "i": 0, "wrong": "白上", "right": "白神", "tier": "mid"}])
        self.assertEqual([x["seg"] for x in items], ["s2"])   # 同じ行・同じ位置は学習の提案を優先
        self.assertEqual(info["count"], 1)
        self.put_doc(self.doc(evalSet=True))
        r = S.suggest_for_doc(TID)
        self.assertIsNone(r["alt"])
        self.assertEqual([x for x in r["items"] if x["tier"] == "alt"], [])

    def test_no_alt_file(self):
        self.put_doc(self.doc())
        r = S.suggest_for_doc(TID)
        self.assertIsNone(r["alt"])
        write_json(S.alt_path(TID), {"schema": "other", "rows": []})   # 形が違うものは読まない
        self.assertIsNone(S.suggest_for_doc(TID)["alt"])

    def test_load_feedback_alt_and_dict_version(self):
        write_json(S.FEEDBACK, {"stat": {}, "dismissed": {}, "alt": {"acc": "x", "rej": 3}})
        self.assertEqual(S.load_feedback()["alt"], {"acc": 0, "rej": 3})
        v1 = S.dict_version({"autoLearned": True})
        write_json(S.FEEDBACK, {"stat": {}, "dismissed": {}, "alt": {"acc": 9, "rej": 3}})
        self.assertEqual(S.dict_version({"autoLearned": True}), v1)   # 別のエンジンの数は辞書の版を変えない

    def test_settings_alt_engine(self):
        with self.assertRaises(S.ApiError):
            S.patch_settings({"values": {"altEngine": "bad"}})
        S.patch_settings({"values": {"altEngine": "whisper.cpp"}})
        self.assertEqual(S.load_settings()["altEngine"], "whisper.cpp")
        self.assertEqual(S.alt_engine_key({}), "whisper.cpp")
        self.assertEqual(S.alt_engine_key({"engine": "faster-whisper"}), "faster-whisper")
        self.assertEqual(S.alt_engine_key({"engine": "nope"}), "whisper.cpp")
        info = S.alt_info()
        self.assertEqual([e["key"] for e in info["engines"]], list(S.ALT_ENGINES))
        self.assertEqual(info["default"], "llama.cpp")


def make_video(path, sec=9):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=%s" % sec,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % sec, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
                   check=True, timeout=120)
    return path


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestAltJob(_AltStore):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.video = make_video(os.path.join(cls.src_dir, "v.mp4"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off",
                                                "TRANSCRIBE_FAKE_ALT": "文=>分"})
        self.env.start()
        self.mine = set()

    def tearDown(self):
        self.env.stop()
        with jobs._jobs_lock:   # このテストのジョブを残さない(待機列の分も)
            for k in list(jobs._jobs):
                if k in self.mine or (jobs._jobs[k].get("spec") or {}).get("sourcePath") == self.video:
                    jobs._jobs.pop(k, None)
            keep = []
            while True:
                try:
                    it = jobs._queue.get_nowait()
                except Exception:
                    break
                if it[2] in jobs._jobs:
                    keep.append(it)
            for it in keep:
                jobs._queue.put(it)
        super().tearDown()

    def _take(self, job):
        self.mine.add(job["id"])
        return job

    def run_one(self, job):
        self._take(job)
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def transcribe(self, **req):
        job = self.run_one(jobs.add_job(doc_jobs.validate_job(dict({"sourcePath": self.video, "model": "small"}, **req))))
        return job["tid"]

    def queued(self, kind, tid):
        return [j for j in jobs._jobs.values() if j.get("kind") == kind and j.get("tid") == tid and j["state"] == "queued"]

    def test_job_writes_alt_and_keeps_doc(self):
        tid = self.transcribe()
        before = store.read_transcript(tid)
        job = self.run_one(jobs.add_job(S.alt_spec(tid, {}), "alt"))
        self.assertEqual((job["tid"], job["kind"]), (tid, "alt"))
        alt = S.read_alt(tid)
        self.assertEqual((alt["schema"], alt["id"], alt["engine"], alt["model"]), ("youtube-tools-alt/v1", tid, "llama.cpp", "qwen3-asr-1.7b"))
        self.assertEqual(alt["range"][0], 0)
        self.assertEqual([r["text"] for r in alt["rows"]], [g["text"].replace("文", "分") for g in before["segments"]])
        for k in ("at", "audioSec", "wallSec", "engineVersion", "device"):
            self.assertIn(k, alt)
        after = store.read_transcript(tid)
        self.assertEqual(after, before)   # 文書は書き換えない(updatedAt も)
        r = S.suggest_for_doc(tid)
        alts = [x for x in r["items"] if x["tier"] == "alt"]
        self.assertEqual([(x["wrong"], x["right"]) for x in alts], [("文", "分")] * len(before["segments"]))
        self.assertEqual(r["alt"]["count"], len(before["segments"]))

    def test_job_applies_row_post_processing(self):
        """主の文字起こしと同じ行の後処理(長さより後ろの行を捨てる)を通し、alt.json に印を残す(v0.52.1。音の谷へ寄せる pullEnds は 0.65.0 で消した)"""
        tid = self.transcribe()
        job = self._take(jobs.add_job(S.alt_spec(tid, {}), "alt"))
        calls = []
        real = postproc.expand_segments

        def spy(gen, spec, dur=None, join=True):
            calls.append((dur, join))
            return real(gen, spec, dur, join=join)

        def fake(job, spec, wav, total):   # 9 秒の動画に、長さの外(100 秒)の行
            yield {"start": 0.0, "end": 4.0, "text": "中の行"}
            yield {"start": 100.0, "end": 104.0, "text": "外の行"}
        with mock.patch.object(postproc, "expand_segments", spy), mock.patch.object(fake_asr, "transcribe_fake", fake):
            doc_jobs.run_job(job)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0][0], 9.0, delta=0.5)   # dur = 音声の長さ
        self.assertFalse(calls[0][1])                         # 候補は続いている行をつながない(時刻を使わない。0.57.1 の join_rows)
        alt = S.read_alt(tid)
        self.assertEqual([r["text"] for r in alt["rows"]], ["中の行"])
        self.assertEqual(alt["post"], {"clip": True, "mergeRepeats": True})   # 0.64.0 までは pullEnds も(0.65.0 で消した)

    def test_job_whisper_cpp_does_not_join(self):
        """whisper.cpp の候補も同じ整え方(0.64.0 までは音の谷へ寄せる levels を渡した = 0.65.0 で消した)"""
        tid = self.transcribe()
        job = self._take(jobs.add_job(S.alt_spec(tid, {"engine": "whisper.cpp"}), "alt"))
        got = []

        def spy(gen, spec, dur=None, join=True):
            got.append((spec["engine"], join))
            return iter(())
        with mock.patch.object(postproc, "expand_segments", spy):
            doc_jobs.run_job(job)
        self.assertEqual(got, [("whisper.cpp", False)])   # 候補は続いている行をつながない(時刻を使わない。0.57.1 の join_rows)
        self.assertEqual(S.read_alt(tid)["post"], {"clip": True, "mergeRepeats": True})

    def test_refusals(self):
        tid = self.transcribe()
        d = store.read_transcript(tid)
        # 最初の認識と同じエンジンとモデル
        d["recognition"]["runs"][0].update(engine="llama.cpp", model="qwen3-asr-1.7b")
        write_json(S.tx_path(tid), d)
        with self.assertRaises(S.ApiError) as cm:
            S.alt_spec(tid, {})
        self.assertEqual(cm.exception.code, "same_engine")
        self.assertEqual(S.alt_spec(tid, {"engine": "whisper.cpp"})["engine"], "whisper.cpp")   # 別のエンジンなら通る
        # 実行中のものがあれば断る
        self._take(jobs.add_job(S.alt_spec(tid, {"engine": "faster-whisper"}), "alt"))
        with self.assertRaises(S.ApiError) as cm:
            S.alt_spec(tid, {"engine": "faster-whisper"})
        self.assertEqual(cm.exception.code, "busy")
        # 評価用・文字の無い文書・動画の無い文書
        for over, code in (({"evalSet": True}, "eval_set"), ({"segments": []}, "empty"), ({"sourcePath": os.path.join(self.tmp, "none.mp4")}, "no_file")):
            with self.subTest(code=code):
                write_json(S.tx_path(tid), dict(d, **over))
                with self.assertRaises(S.ApiError) as cm:
                    S.alt_spec(tid, {"engine": "whisper.cpp"})
                self.assertEqual(cm.exception.code, code)

    def test_doc_deleted_during_job(self):
        tid = self.transcribe()
        job = self._take(jobs.add_job(S.alt_spec(tid, {}), "alt"))
        os.unlink(S.tx_path(tid))
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "error")
        self.assertFalse(os.path.exists(S.alt_path(tid)))

    def test_auto_alt(self):
        """設定 autoAlt(既定オフ): 文字起こしが終わったら alt のジョブを足す。要求の autoAlt が優先・評価用は足さない"""
        tid = self.transcribe()
        self.assertEqual(self.queued("alt", tid), [])   # 既定はオフ
        write_json(S.SETTINGS, {"autoAlt": True})
        tid2 = self.transcribe()
        q = self.queued("alt", tid2)
        self.assertEqual(len(q), 1)
        self.mine.update(j["id"] for j in q)
        self.assertEqual(q[0]["spec"]["engine"], "llama.cpp")
        tid3 = self.transcribe(autoAlt=False)
        self.assertEqual(self.queued("alt", tid3), [])
        tid4 = self.transcribe(evalSet=True)
        self.assertEqual(self.queued("alt", tid4), [])
        d4 = self.queued("diarize", tid4)   # 評価用は代わりに話者の自動判別が足される(v0.50.0)。このテストのジョブとして片付ける
        self.assertEqual(len(d4), 1)
        self.mine.update(j["id"] for j in d4)
        self.assertTrue(doc_jobs.validate_job({"sourcePath": self.video, "model": "small", "autoAlt": True})["autoAlt"])
        write_json(S.SETTINGS, {"altEngine": "llama.cpp"})
        self.assertFalse(doc_jobs.validate_job({"sourcePath": self.video, "model": "small"})["autoAlt"])
        # 始められなくても(同じエンジン)文字起こしは成功のまま・注意を出す
        job = {"warnings": []}
        with mock.patch.object(proof_alt, "alt_spec", side_effect=S.ApiError("same_engine", "同じ", 400)):
            S.alt_after_transcribe(job, {"autoAlt": True}, tid)
        self.assertEqual(len(job["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
