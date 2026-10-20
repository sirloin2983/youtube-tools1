#!/usr/bin/env python3
"""2つ目のエンジンとの食い違いに候補を出す機能のテスト。

    py -3.12 -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest test_alt -q                    # これだけ(src/editor/tests で)

- alt_diffs(純粋な関数): 場面を並べた文書 1 本で、置き換え・表記だけの違いは出さない・片方だけの文字・長すぎ・行またぎ・行の大半が違う・校正済み・
  重なる候補をまとめて確かめる。長い文書は窓ごと
- ジョブの通し(疑似の認識 TRANSCRIBE_BACKEND=fake の行を差し替え + TRANSCRIBE_FAKE_ALT): 主の文字起こし → alt.json(同じ行の後処理・文書は書き換えない)→
  提案に足す・却下で消える・学習の提案を優先・採用/却下の数え方(学習の統計に入れない)・今の行の文字で計算し直す・評価用には出さない
- 断る場面(評価用/同じエンジンとモデル/実行中/文字の無い文書/動画の無い文書)・ジョブの途中で文書が消えた・autoAlt(設定と要求)・設定 altEngine の検査・壊れた採否の記録
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import StoreDir, write_json  # noqa: E402  (S = serve)
import ed_state  # noqa: E402
from human.proof import learn as _learn  # noqa: E402
from pipeline.transcribe import records as _records  # noqa: E402
from ytt import settings as _settings  # noqa: E402
from ytt import workdata as _workdata  # noqa: E402
from eval.fake import fake_asr  # noqa: E402
from ytt.tests import testkit  # noqa: E402
from human.proof import alt as proof_alt  # noqa: E402
from human.proof import doc_jobs  # noqa: E402
from human.proof import store  # noqa: E402
from flow import jobs  # noqa: E402

HAVE_FF = bool(shutil.which("ffmpeg"))


def _row(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def _alt(a, b, text):
    return {"start": a, "end": b, "text": text}


CASES = [   # (今の行, 2 つ目のエンジンの行, 候補 [(i, 誤, 正)])。行の頭に足した字は前の行の終わりにも見えるので、その場面は文書の頭に置く
    ("雨です", "大雨です", [(0, "雨", "大雨")]),                                  # 片方だけにある文字は隣の 1 文字を足して置き換えの形に
    ("こんばんは白上フブキです", "こんばんは、白神フブキです", [(6, "上", "神")]),
    ("今日は雨です", "今日は大雨です", [(2, "は", "は大")]),
    ("ふぶきちゃん", "フブキちゃん", []),                                          # 表記だけの違い(かなとカナ・句読点と空白・全角と半角・大小・伸ばし・読みが同じ漢字)
    ("今日は大雨です", "今日は雨です", [(2, "は大", "は")]),
    ("こんにちは。元気", "こんにちは 元気!", []), ("ＡＢＣです", "abcです", []), ("OKです", "okです", []), ("すごーいね", "すごいね", []), ("すごいね", "凄いね", []),
    ("あ" * 3 + "かきくけこさしすせそたちつ" + "あ" * 30, "あ" * 3 + "なにぬねのはひふへほまみむ" + "あ" * 30, []),   # 長すぎる置き換え
    ("今日はマイクラをやります", "きょうはマインクラフトやります", []),              # 行の文字の半分以上が違う
    ("白上フブキです", "白神フブキです", []),                                      # 校正済み
    ("あいうえおかきくけこさしすせそ", "あいXえおかきYけこさしすせそ", [(2, "う", "X"), (7, "く", "Y")]),   # 重なる候補は出さない
]


class TestAltDiffs(unittest.TestCase):
    def test_diffs_on_rich_doc(self):
        rows, alts, want, t = [], [], [], 0.0
        for k, (main, other, cands) in enumerate(CASES, 1):
            rows.append(_row(k, t, t + 3, main, **({"proofed": True} if main == "白上フブキです" else {})))
            alts.append(_alt(t, t + 3, other))
            want += [("s%d" % k, i, w, r) for i, w, r in cands]
            t += 4
        rows += [_row(90, t, t + 2, "ここからあいう"), _row(91, t + 2, t + 4, "えおそれから")]   # 行をまたぐ置き換え(1 行目の終わり〜2 行目の始まり)
        alts.append(_alt(t, t + 4, "ここからあいかきおそれから"))
        items, st = proof_alt.alt_diffs(rows, alts)
        self.assertEqual([(x["seg"], x["i"], x["wrong"], x["right"]) for x in items], want)
        self.assertEqual({x["tier"] for x in items}, {"alt"})
        for x in items[:1] + items[2:4]:   # 片方だけの文字: 画面の採用(位置で置き換え)で 2 つ目のエンジンの文字になる
            k = int(x["seg"][1:]) - 1
            self.assertEqual(CASES[k][0][:x["i"]] + x["right"] + CASES[k][0][x["i"] + len(x["wrong"]):], CASES[k][1])
        self.assertEqual(st, {"long": 1, "cross": 1, "mostly": 2, "notation": 2, "edge": 0})
        self.assertEqual(proof_alt.alt_diffs([], [_alt(0, 1, "a")]), ([], {"long": 0, "cross": 0, "mostly": 0, "notation": 0, "edge": 0}))
        self.assertEqual(proof_alt.alt_diffs(rows, [])[0], [])
        # 長い文書は時刻の窓ごとにそろえる(窓が複数・遠い所の食い違いも正しい行に・2 つ目のエンジンの時刻が少しずれていても)
        rows, alts = [], []
        for i in range(400):   # 20 分(3 秒ごと)
            text = "第%d番目の行です" % i
            rows.append(_row(i, i * 3.0, i * 3.0 + 2.5, text))
            alts.append(_alt(i * 3.0 + 0.4, i * 3.0 + 2.9, text.replace("行", "業") if i in (5, 250, 399) else text))
        self.assertGreater(len(proof_alt._alt_windows(sorted([dict(r, n=k) for k, r in enumerate(rows)], key=lambda r: r["start"]))), 5)
        items, st = proof_alt.alt_diffs(rows, alts)
        self.assertEqual([(x["seg"], x["wrong"], x["right"]) for x in items], [("s5", "行", "業"), ("s250", "行", "業"), ("s399", "行", "業")])
        self.assertEqual(st["cross"], 0)


class TestAltDiffsRowStart(unittest.TestCase):
    def test_inserted_char_at_row_start_stays_in_that_row(self):
        """行の頭に足された字は、前の行の終わりの候補にしない(次の行の頭の置き換えにする)"""
        rows = [_row(1, 0.0, 3.0, "今日は晴れですよ"), _row(2, 3.0, 6.0, "明日は雨になります")]
        alts = [_alt(0.0, 6.0, "今日は晴れですよ。そして明日は雨になります")]
        items, _st = proof_alt.alt_diffs(rows, alts)
        self.assertEqual([(x["seg"], x["wrong"], x["right"]) for x in items], [("s2", "明", "そして明")])


class _AltStore(StoreDir):
    def setUp(self):
        super().setUp()
        self.fb = mock.patch.object(_workdata, "FEEDBACK", os.path.join(self.tmp, "learn-feedback.json"))
        self.fb.start()
        proof_alt._alt_cache.clear()

    def tearDown(self):
        self.fb.stop()
        super().tearDown()


class TestAltSettings(_AltStore):
    def test_load_feedback_alt_and_dict_version(self):
        write_json(_workdata.FEEDBACK, {"stat": {}, "dismissed": {}, "alt": {"acc": "x", "rej": 3}})
        self.assertEqual(_learn.load_feedback()["alt"], {"acc": 0, "rej": 3})
        v1 = _records.dict_version({"autoLearned": True})
        write_json(_workdata.FEEDBACK, {"stat": {}, "dismissed": {}, "alt": {"acc": 9, "rej": 3}})
        self.assertEqual(_records.dict_version({"autoLearned": True}), v1)   # 別のエンジンの数は辞書の版を変えない

    def test_settings_alt_engine(self):
        for bad in ("bad", "whisper.cpp", "faster-whisper"):   # 選べるのは Qwen3-ASR 1.7B(llama.cpp)だけ
            with self.assertRaises(ed_state.ApiError):
                _settings.patch_settings({"values": {"altEngine": bad}})
        _settings.patch_settings({"values": {"altEngine": "llama.cpp"}})
        self.assertEqual(_settings.load_settings()["altEngine"], "llama.cpp")
        write_json(_workdata.SETTINGS, {"altEngine": "whisper.cpp"})   # 外れた値は既定に読む
        self.assertEqual(proof_alt.alt_engine_key({}), "llama.cpp")
        self.assertEqual(proof_alt.alt_engine_key({"engine": "faster-whisper"}), "llama.cpp")
        self.assertEqual(proof_alt.alt_engine_key({"engine": "nope"}), "llama.cpp")
        info = proof_alt.alt_info()
        self.assertEqual([e["key"] for e in info["engines"]], list(proof_alt.ALT_ENGINES))
        self.assertEqual(info["default"], "llama.cpp")


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestAltJob(_AltStore):
    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.video = testkit.make_video(os.path.join(cls.src_dir, "v.mp4"), 9)

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
        with jobs._jobs_lock:   # このテストのジョブを残さない
            for k in list(jobs._jobs):
                if k in self.mine or (jobs._jobs[k].get("spec") or {}).get("sourcePath") == self.video:
                    jobs._jobs.pop(k, None)
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

    def test_job_then_suggest(self):
        """主の文字起こし → 2 つ目のエンジンのジョブ(alt.json・同じ行の後処理。続いている行はつながない)→ 提案に足す → 却下・採用の数え方 →
        今の行の文字で計算し直す → 学習の提案を優先 → 評価用には出さない"""
        def rows(job, spec, wav, total):   # 9 秒の動画に、すき間 0.3 秒の 2 行と長さの外(100 秒)の行
            job["state"] = "running"
            yield {"start": 0.0, "end": 2.7, "text": "白上フブキです"}
            yield {"start": 3.0, "end": 6.0, "text": "大神ミオです"}
            yield {"start": 100.0, "end": 104.0, "text": "外の行"}
        self.enterContext(mock.patch.object(fake_asr, "transcribe_fake", rows))
        self.enterContext(mock.patch.dict(os.environ, {"TRANSCRIBE_FAKE_ALT": "白上=>白神,大神=>大上"}))
        tid = self.transcribe()
        before = store.read_transcript(tid)
        self.assertEqual([(g["end"], g["text"]) for g in before["segments"]], [(3.0, "白上フブキです"), (6.0, "大神ミオです")])
        self.assertIsNone(_learn.suggest_for_doc(tid)["alt"])                    # alt.json が無い
        self.assertEqual(proof_alt.alt_doc_candidates(tid, before), [])
        write_json(proof_alt.alt_path(tid), {"schema": "other", "rows": []})         # 形が違うものは読まない
        self.assertIsNone(_learn.suggest_for_doc(tid)["alt"])
        job = self.run_one(jobs.add_job(proof_alt.alt_spec(tid, {}), "alt"))
        self.assertEqual((job["tid"], job["kind"]), (tid, "alt"))
        alt = proof_alt.read_alt(tid)
        self.assertEqual((alt["schema"], alt["id"], alt["engine"], alt["model"], alt["range"][0]), ("youtube-tools-alt/v1", tid, "llama.cpp", "qwen3-asr-1.7b", 0))
        self.assertEqual([(r["end"], r["text"]) for r in alt["rows"]], [(2.7, "白神フブキです"), (6.0, "大上ミオです")])   # 長さの外は捨て、つながない
        self.assertEqual(alt["post"], {"clip": True, "mergeRepeats": True})
        for k in ("at", "audioSec", "wallSec", "engineVersion", "device"):
            self.assertIn(k, alt)
        self.assertEqual(store.read_transcript(tid), before)                # 文書は書き換えない(updatedAt も)

        r = _learn.suggest_for_doc(tid)
        self.assertEqual([(x["seg"], x["i"], x["wrong"], x["right"]) for x in r["items"] if x["tier"] == "alt"], [("s1", 1, "上", "神"), ("s2", 1, "神", "上")])
        self.assertEqual((r["alt"]["engine"], r["alt"]["model"], r["alt"]["count"]), ("llama.cpp", "qwen3-asr-1.7b", 2))
        items, info = proof_alt.alt_suggest(tid, before, set(), [{"seg": "s1", "i": 0, "wrong": "白上", "right": "白神", "tier": "mid"}])
        self.assertEqual(([x["seg"] for x in items], info["count"]), (["s2"], 1))   # 同じ行・同じ位置は学習の提案を優先
        # 却下: 学習の統計に入れず、数だけ fb["alt"]。却下した候補は出さない(文書 1 本の候補の口も採否の記録から却下を読む)
        _learn.record_feedback({"tid": tid, "action": "reject", "items": [{"seg": "s1", "wrong": "上", "right": "神", "tier": "alt"}]})
        _learn.record_feedback({"tid": tid, "action": "accept", "items": [{"seg": "s2", "wrong": "神", "right": "上", "tier": "alt"},
                                                                       {"seg": "s2", "wrong": "ミオ", "right": "みお"}]})
        fb = _learn.load_feedback()
        self.assertEqual((fb["alt"], list(fb["stat"])), ({"acc": 1, "rej": 1}, ["ミオ=>みお"]))   # 学習の提案の採用だけが統計に入る
        self.assertIn("s1|上=>神", fb["dismissed"][tid])
        r = _learn.suggest_for_doc(tid)
        self.assertEqual(([(x["seg"], x["wrong"]) for x in r["items"] if x["tier"] == "alt"], r["alt"]["count"]), ([("s2", "神")], 1))
        self.assertEqual([x["seg"] for x in proof_alt.alt_doc_candidates(tid, before)], ["s2"])
        self.assertEqual([x["seg"] for x in proof_alt.alt_doc_candidates(tid, before, set())], ["s1", "s2"])
        # 候補は今の行の文字で毎回計算する(採用して直した所は消える)
        d = dict(before, updatedAt=before["updatedAt"] + 1, segments=[before["segments"][0], dict(before["segments"][1], text="大上ミオです")])
        write_json(store.tx_path(tid), d)
        self.assertEqual([x for x in _learn.suggest_for_doc(tid)["items"] if x["tier"] == "alt"], [])
        write_json(store.tx_path(tid), dict(before, evalSet=True))                # 評価用には出さない
        r = _learn.suggest_for_doc(tid)
        self.assertEqual((r["alt"], [x for x in r["items"] if x["tier"] == "alt"], proof_alt.alt_doc_candidates(tid, dict(before, evalSet=True))), (None, [], []))

    def test_refusals(self):
        tid = self.transcribe()
        d = store.read_transcript(tid)
        first = dict(d["recognition"]["runs"][0])
        # 最初の認識と同じエンジンとモデル(2 つ目のエンジンは Qwen3-ASR 1.7B だけ = 選び直せない)
        d["recognition"]["runs"][0].update(engine="llama.cpp", model="qwen3-asr-1.7b")
        write_json(store.tx_path(tid), d)
        with self.assertRaises(ed_state.ApiError) as cm:
            proof_alt.alt_spec(tid, {})
        self.assertEqual(cm.exception.code, "same_engine")
        d["recognition"]["runs"][0] = first
        write_json(store.tx_path(tid), d)
        self.assertEqual(proof_alt.alt_spec(tid, {})["engine"], "llama.cpp")   # 最初の認識と違えば通る
        # 実行中のものがあれば断る
        self._take(jobs.add_job(proof_alt.alt_spec(tid, {}), "alt"))
        with self.assertRaises(ed_state.ApiError) as cm:
            proof_alt.alt_spec(tid, {})
        self.assertEqual(cm.exception.code, "busy")
        # 評価用・文字の無い文書・動画の無い文書
        for over, code in (({"evalSet": True}, "eval_set"), ({"segments": []}, "empty"), ({"sourcePath": os.path.join(self.tmp, "none.mp4")}, "no_file")):
            with self.subTest(code=code):
                write_json(store.tx_path(tid), dict(d, **over))
                with self.assertRaises(ed_state.ApiError) as cm:
                    proof_alt.alt_spec(tid, {})
                self.assertEqual(cm.exception.code, code)

    def test_doc_deleted_during_job(self):
        tid = self.transcribe()
        job = self._take(jobs.add_job(proof_alt.alt_spec(tid, {}), "alt"))
        os.unlink(store.tx_path(tid))
        doc_jobs.run_job(job)
        self.assertEqual(job["state"], "error")
        self.assertFalse(os.path.exists(proof_alt.alt_path(tid)))

    def test_auto_alt(self):
        """設定 autoAlt(既定オフ): 文字起こしが終わったら alt のジョブを足す。要求の autoAlt が優先・評価用は足さない"""
        tid = self.transcribe()
        self.assertEqual(self.queued("alt", tid), [])   # 既定はオフ
        write_json(_workdata.SETTINGS, {"autoAlt": True})
        tid2 = self.transcribe()
        q = self.queued("alt", tid2)
        self.assertEqual(len(q), 1)
        self.mine.update(j["id"] for j in q)
        self.assertEqual(q[0]["spec"]["engine"], "llama.cpp")
        tid3 = self.transcribe(autoAlt=False)
        self.assertEqual(self.queued("alt", tid3), [])
        tid4 = self.transcribe(evalSet=True)
        self.assertEqual(self.queued("alt", tid4), [])
        d4 = self.queued("diarize", tid4)   # 評価用は代わりに話者の自動判別が足される。このテストのジョブとして片付ける
        self.assertEqual(len(d4), 1)
        self.mine.update(j["id"] for j in d4)
        self.assertTrue(doc_jobs.validate_job({"sourcePath": self.video, "model": "small", "autoAlt": True})["autoAlt"])
        write_json(_workdata.SETTINGS, {"altEngine": "llama.cpp"})
        self.assertFalse(doc_jobs.validate_job({"sourcePath": self.video, "model": "small"})["autoAlt"])
        base = {"sourcePath": self.video, "model": "small"}   # llmModel は要求にあれば通す(合う名前だけ)
        self.assertIsNone(doc_jobs.validate_job(base)["llmModel"])
        self.assertEqual(doc_jobs.validate_job(dict(base, llmModel="qwen3-8b"))["llmModel"], "qwen3-8b")
        self.assertIsNone(doc_jobs.validate_job(dict(base, llmModel="../x y"))["llmModel"])
        # 始められなくても(同じエンジン)文字起こしは成功のまま・注意を出す
        job = {"warnings": []}
        with mock.patch.object(proof_alt, "alt_spec", side_effect=ed_state.ApiError("same_engine", "同じ", 400)):
            proof_alt.alt_after_transcribe(job, {"autoAlt": True}, tid)
        self.assertEqual(len(job["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
