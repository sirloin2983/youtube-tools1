#!/usr/bin/env python3
"""校正まわりの API の確かめ(編集の画面の裏の API だけで確かめる)。

    py -3.12 -m unittest tests/eval/drill/test_metrics.py     # test_metrics がこのファイルのテストも読み込む
    py -3.12 -m unittest tests/human/proof/test_proof_api.py   # これだけ

- 学習の規則 learn_rules(human/proof/learn.py。評価用は数えない・登録済み・無視した組は規則にしない)
- 精度の測定 all_metrics の scope(eval/drill/metrics.py)
- 範囲の再認識 mode=range(human/proof/rerun.py・doc_jobs.validate_retranscribe)
- 話者の色の整形(sanitize_transcript。CSS を差し込めない)
- GET /api/transcript の evalLocked
- 声を覚える -> 判別し直すと名前が付く鎖(recognize の有無・忘れたあと)
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # リポジトリ直下から py -3.12 -m unittest tests/human/proof/test_proof_api.py でも読めるように
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "editor"))   # test_backend・test_edit(編集のサーバーを一時フォルダで動かす道具)
from test_backend import HERE, S, StoreDir, write_json  # noqa: E402
import ed_state  # noqa: E402
from flow import diar as _diar  # noqa: E402
VE = _diar.learn_embedding("voxceleb")   # 覚えた声の帳のモデル(声の名前付け = pipeline/transcribe/diarize.VOICE_EMB。10-22)
from flow import jobs as _jobs  # noqa: E402
from human.proof import rerun as _rerun  # noqa: E402
from human.proof import speakers as _speakers  # noqa: E402
from human.proof import store as _store  # noqa: E402
from ytt import workdata as _workdata  # noqa: E402
from pipeline.transcribe import diarize as _diarize, recognize as _recognize  # noqa: E402
from ytt import tools as _tools  # noqa: E402
from test_voices import doc_with_speakers, unit
from human.proof import learn  # noqa: E402
from ytt import txtext as _txtext  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

TID_A, TID_B, TID_C = "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"
HAVE_FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def fixed_doc(tid, eval_set=False, proofed=True, source="C:\\x\\clip.mp4"):
    """機械の出力 original と人の最終 segments が「テスト → テスタ」だけ違う文書(学習・測定の材料)"""
    d = {"schema": "transcribe/v1", "id": tid, "title": "題名" + tid[:1], "sourcePath": source, "start": 0, "end": 10.0, "speakers": [],
         "createdAt": 1, "updatedAt": 1000, "model": "small",
         "original": [{"start": 0, "end": 4, "text": "今日はテストです"}, {"start": 4, "end": 8, "text": "そうですね"}],
         "segments": [{"id": "s1", "start": 0, "end": 4, "text": "今日はテスタです", "speaker": "", "flag": ""},
                      {"id": "s2", "start": 4, "end": 8, "text": "そうですね", "speaker": "", "flag": ""}]}
    if proofed:
        for g in d["segments"]:
            g["proofed"] = True
    if eval_set:
        d["evalSet"] = True
    return d


class _ProofStore(StoreDir):
    """作業データを一時フォルダに。学習の記録・文書の要約のキャッシュもテストごとに空に"""

    def setUp(self):
        super().setUp()
        self.patch(_workdata, "FEEDBACK", os.path.join(self.tmp, "learn-feedback.json"))
        learn._info_cache.clear()
        learn._rules_cache.update(key=None, val=None)
        self.addCleanup(learn._info_cache.clear)
        self.addCleanup(learn._rules_cache.update, key=None, val=None)


class TestLearnedRules(_ProofStore):
    """修正から作る学習の規則(learn_rules。確度「高」が自動置換 autoLearned の元)。評価用の修正は学習の元にしない(答えを見てから測ることになるため)"""

    def pair(self):
        """学習の規則 [(誤, 正)]。1 文字だけの違いは前後 1 文字を足す(learn_events)ので、中身は固定の文字でなく出てきた物を見る"""
        return list(learn.learn_rules())

    def test_train_docs_are_counted_and_eval_doc_is_not(self):
        self.put_doc(fixed_doc(TID_A), TID_A)
        self.put_doc(fixed_doc(TID_B), TID_B)
        self.put_doc(fixed_doc(TID_C, eval_set=True), TID_C)
        r = learn.learn_rules()
        self.assertEqual(len(r), 1)
        (w, rt), x = next(iter(r.items()))
        self.assertIn("テ", w + rt)                                                 # 「テスト → テスタ」の修正
        self.assertIn("ト", w)
        self.assertIn("タ", rt)
        self.assertEqual((x["pos"], len(x["docs"])), (2, 2))                        # 学習用 2 本の分だけ(評価用の分は足さない)

    def test_eval_only_gives_no_rules(self):
        self.put_doc(fixed_doc(TID_C, eval_set=True), TID_C)
        self.assertEqual(learn.learn_rules(), {})

    def test_registered_replacement_is_not_learned(self):
        self.put_doc(fixed_doc(TID_A), TID_A)
        (wrong, right), = self.pair()
        write_json(_workdata.SETTINGS, {"replacements": "%s=>%s\n" % (wrong, right)})     # 置換辞書に入れた組は、もう規則にしない
        self.assertEqual(self.pair(), [])
        write_json(_workdata.SETTINGS, {"replacements": "%s=>%s\n" % ("別の誤り", right)})  # 別の誤りの登録は影響しない
        self.assertEqual(self.pair(), [(wrong, right)])
        write_json(_workdata.SETTINGS, {"learnIgnore": ["%s=>%s" % (wrong, right)]})      # 「無視」にした組も規則にしない
        self.assertEqual(self.pair(), [])


class TestMetricsScope(_ProofStore):
    """精度の測定の対象(評価用のみ / 評価用でない)"""

    def setUp(self):
        super().setUp()
        self.put_doc(fixed_doc(TID_A), TID_A)                       # 学習用
        self.put_doc(fixed_doc(TID_C, eval_set=True), TID_C)        # 評価用

    def test_scope_splits_eval_and_train(self):
        def q(**kw):
            return lambda k, d="": kw.get(k, d)
        me, mt, ma = S._metrics(q(scope="eval")), S._metrics(q(scope="train")), S._metrics(q())
        self.assertEqual((me["docs"], mt["docs"], ma["docs"]), (1, 1, 2))
        self.assertEqual([r["id"] for r in me["byDoc"]], [TID_C])
        self.assertEqual([r["id"] for r in mt["byDoc"]], [TID_A])
        self.assertEqual((me["scope"], mt["scope"], ma["scope"]), ("eval", "train", "all"))
        self.assertGreater(me["overall"]["refChars"], 0)
        self.assertEqual(S._metrics(q(scope="でたらめ"))["scope"], "all")                              # 知らない scope は all
        one = S._metrics(q(id=TID_A))                                                                  # id 指定は scope に関わらず 1 本
        self.assertEqual((one["scope"], one["docs"]), ("doc", 1))


class TestSanitizeSpeakerColor(unittest.TestCase):
    """話者の色に CSS を書かれても、保存の時点で差し込めない形にする"""

    def test_css_injection_is_stripped(self):
        evil = "red;background-image:url(http://127.0.0.1:1/leak.png)"
        out = _store.sanitize_transcript({"speakers": [{"id": "S1", "name": "a", "color": evil}], "segments": []}, {})
        c = out["speakers"][0]["color"]
        self.assertLessEqual(len(c), 9)
        self.assertLess(len(c), len(evil))
        for ch in ";:()/.-\"'<> ":
            self.assertNotIn(ch, c)
        self.assertNotIn("http", c)
        self.assertNotIn("url", c)

    def test_normal_colors_survive(self):
        for col in ("#2f62d6", "#888", "#8a8f98cc"):
            out = _store.sanitize_transcript({"speakers": [{"id": "S1", "name": "a", "color": col}], "segments": []}, {})
            self.assertEqual(out["speakers"][0]["color"], col)
        out = _store.sanitize_transcript({"speakers": [{"id": "S1", "name": "a"}], "segments": []}, {})
        self.assertEqual(out["speakers"][0]["color"], "")                           # 無ければ空のまま


class TestTranscriptEvalLocked(_ProofStore):
    """評価用のフォルダの動画の文書は evalLocked(画面の評価用のチェックを固定する印)"""

    def test_eval_locked_follows_eval_dirs(self):
        ev = testkit.tempdir(self)
        inside = os.path.join(ev, "1_JP", "評価用データ01_ときのそら", "a.mp4")
        os.makedirs(os.path.dirname(inside))
        write_json(_workdata.SETTINGS, {"evalDirs": [ev]})
        self.put_doc(fixed_doc(TID_A, source=inside, eval_set=True), TID_A)
        self.put_doc(fixed_doc(TID_B, source="C:\\x\\clip.mp4"), TID_B)
        self.assertIs(S._transcript(TID_A)["evalLocked"], True)
        self.assertIs(S._transcript(TID_B)["evalLocked"], False)
        self.assertEqual(S._transcript(TID_A)["segments"][0]["text"], "今日はテスタです")   # 文書の中身は変えない
        write_json(_workdata.SETTINGS, {"evalDirs": []})                                     # 設定が消えたら、どれも固定しない
        self.assertIs(S._transcript(TID_A)["evalLocked"], False)


@unittest.skipUnless(HAVE_FF, "ffmpeg が必要")
class TestRangeRetranscribe(_ProofStore):
    """範囲の再認識(mode=range)。認識は疑似(3 秒ごとに「範囲再認識N」)"""

    @classmethod
    def setUpClass(cls):
        cls.src_dir = tempfile.mkdtemp()
        cls.wav = os.path.join(cls.src_dir, "r.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=10", cls.wav],
                       check=True, stdin=subprocess.DEVNULL, timeout=60)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src_dir, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0", "TRANSCRIBE_NORMALIZE": "off"})
        self.env.start()
        self.mine = []

    def tearDown(self):
        self.env.stop()
        with _jobs._jobs_lock:
            for k in self.mine:
                _jobs._jobs.pop(k, None)
        super().tearDown()

    def doc(self):
        with open(_store.tx_path(TID_A), encoding="utf-8") as f:
            return json.load(f)

    def put(self, segs, speakers=()):
        d = fixed_doc(TID_A, source=self.wav)
        d.update(segments=segs, original=[], speakers=list(speakers), end=10.0)
        self.put_doc(d, TID_A)

    def rows(self):
        """x0〜x3(2 秒ごと・1.8 秒)。全部校正済み・音のメモ bgm つき・x2 x3 は話者 S1"""
        return [{"id": "x%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.8, "text": "行%d" % i, "speaker": "S1" if i in (2, 3) else "", "flag": "",
                 "proofed": True, "tags": ["bgm"]} for i in range(4)]

    def run_range(self, ids):
        spec = _rerun.validate_retranscribe({"tid": TID_A, "ids": ids, "mode": "range", "model": "small"})
        job = _jobs.add_job(spec, "retranscribe")
        self.mine.append(job["id"])
        _jobs.work_one(job["id"])
        return spec, job

    def test_range_replaces_only_the_range(self):
        self.put(self.rows(), [{"id": "S1", "name": "話者", "color": "#2f62d6"}])
        spec, job = self.run_range(["x1", "x3"])
        self.assertEqual(spec["ids"], ["x1", "x2", "x3"])                          # 間にある選んでいない行も範囲に含む
        self.assertEqual(spec["range"], [2.0, 7.8])
        self.assertEqual(job["state"], "done", job.get("error"))
        d = self.doc()
        segs = d["segments"]
        self.assertEqual(segs[0]["text"], "行0")                                   # 範囲外の行は不変
        self.assertEqual({k: segs[0][k] for k in ("id", "start", "end", "proofed", "tags")}, {"id": "x0", "start": 0.0, "end": 1.8, "proofed": True, "tags": ["bgm"]})
        rest = segs[1:]   # 範囲の校正済みの行は人の行として残り、下の機械が変わった印 MACH_CHANGED(3 択)。機械の層だけが新しくなる
        from human.proof import layers
        self.assertEqual([g["id"] for g in rest], ["x1", "x2", "x3"])
        self.assertTrue(all(g.get("proofed") and layers.MACH_CHANGED in g["flag"] for g in rest))
        mach = _store.read_layers(TID_A)[0]
        self.assertTrue(mach["rows"] and all(r["text"].startswith("範囲再認識") for r in mach["rows"] if r["start"] >= 2.0 - 1e-6))
        self.assertGreaterEqual(min(r["start"] for r in mach["rows"] if r["text"].startswith("範囲再認識")), 2.0 - 1e-6)   # 新しい行は範囲の内側
        self.assertLessEqual(max(g["end"] for g in segs), 7.8 + 1e-6)
        starts = [g["start"] for g in segs]
        self.assertEqual(starts, sorted(starts))                                   # 時刻順
        self.assertEqual(len({g["id"] for g in segs}), len(segs))                  # id は重複しない
        self.assertEqual(os.listdir(_workdata.TMP_DIR) if os.path.isdir(_workdata.TMP_DIR) else [], [])                    # 一時ファイルは残さない
        with open(os.path.join(_store._hist_dir(TID_A), "%d.json" % _store.hist_stamps(TID_A)[-1]), encoding="utf-8") as f:   # 最後の履歴 = 実行の直前
            bak = json.load(f)
        self.assertEqual([g["text"] for g in bak["segments"]], ["行0", "行1", "行2", "行3"])                 # 差し替える前の行

    def test_range_longer_than_15_minutes_is_refused(self):
        far = [{"id": "y0", "start": 0, "end": 1, "text": "a"}, {"id": "y1", "start": 1000, "end": 1001, "text": "b"}]
        self.put(far)
        with self.assertRaises(ed_state.ApiError) as c:
            _rerun.validate_retranscribe({"tid": TID_A, "ids": ["y0", "y1"], "mode": "range", "model": "small"})
        self.assertEqual((c.exception.code, c.exception.status), ("too_long", 400))
        self.assertIn("長すぎ", str(c.exception))
        self.assertEqual(_rerun.MAX_RANGE_SEC, 900)
        ok = [{"id": "y0", "start": 0, "end": 1, "text": "a"}, {"id": "y1", "start": 899, "end": 900, "text": "b"}]   # ちょうど 15 分は通る
        self.put(ok)
        self.assertEqual(_rerun.validate_retranscribe({"tid": TID_A, "ids": ["y0", "y1"], "mode": "range", "model": "small"})["range"], [0, 900])


class TestVoiceChain(_ProofStore):
    """声を覚える -> 判別し直すと名前が付く。recognize: false なら付かない・忘れたあとは付かない
    (サーバー側は test_voices.py が部品ごとに確かめている。ここは覚える -> 判別の続けた流れ)"""

    def setUp(self):
        super().setUp()
        self.patch(_diar, "VOICES_DIR", os.path.join(self.tmp, "voices"))
        self.start_mocks()

    def read(self):
        with open(_store.tx_path(TID_A), encoding="utf-8") as f:
            return json.load(f)

    def job(self, spec):
        return {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "speakers": 0}

    @staticmethod
    def emb(job, wav, e, groups, off):
        """1 人目の声は (1,0,0)・それ以外は (0,1,0)(疑似の判別 diarize_fake は 10 秒ごとに入れ替わる)"""
        return [unit(1, 0, 0) if k == 0 else unit(0, 1, 0) for k, _ in enumerate(groups)]

    def doc(self, names):
        rows = [(0, 5, "S1", ""), (11, 18, "S2", ""), (21, 29, "S1", "")]
        d = doc_with_speakers(names, rows, proofed=True)
        d["id"] = TID_A
        self.put_doc(d, TID_A)

    def start_mocks(self):
        """動画・音声・判別のモデルは使わない(疑似の判別 diarize_fake と、上の emb の声の特徴)"""
        for obj, name, val in ((_tools, "check_source", lambda p: p), (_recognize, "extract_audio", lambda *a: None), (_diarize, "has_sherpa", lambda: True),
                               (_diarize, "ensure_diar_models", lambda *a: None), (ed_state, "backend_name", lambda: "fake"), (_diarize, "embed_groups", self.emb)):
            self.patch(obj, name, val)

    def learn(self):
        self.doc([("S1", "兎田ぺこら"), ("S2", "話者2")])
        spec = _speakers.validate_voice_learn({"tid": TID_A, "embedding": "voxceleb", "names": ["兎田ぺこら", "話者2"]})
        j = self.job(spec)
        _speakers.run_voice_learn(j)
        self.assertEqual((j["state"], j["learned"]), ("done", ["兎田ぺこら"]), j.get("error"))   # 仮の名前(話者2)は覚えない

    def rediarize(self, **req):
        self.doc([("S1", "話者1"), ("S2", "話者2")])                                  # 判別し直す前は仮の名前
        j = self.job(_speakers.validate_diarize(dict({"tid": TID_A, "numSpeakers": 2}, **req)))
        _speakers.run_diarize(j)
        self.assertEqual(j["state"], "done", j.get("error"))
        return j, self.read()

    def test_rediarize_names_the_learned_speaker(self):
        self.learn()
        j, d = self.rediarize()
        self.assertEqual([n["name"] for n in j["named"]], ["兎田ぺこら"])             # 覚えた声の話者に名前が付く
        self.assertEqual([s["name"] for s in d["speakers"]], ["兎田ぺこら", "話者2"])  # 文書の話者の名前(もう 1 人は似ていないので仮のまま)

    def test_recognize_false_does_not_name(self):
        self.learn()
        j, d = self.rediarize(recognize=False)
        self.assertFalse(j.get("named"))
        self.assertEqual([s["name"] for s in d["speakers"]], ["話者1", "話者2"])        # 照らし合わせをしない指定 = 仮の名前のまま

    def test_forgotten_voice_does_not_name(self):
        self.learn()
        self.assertEqual([v["name"] for v in _speakers.voices_summary()[VE]], ["兎田ぺこら"])
        _speakers.delete_voice(VE, "兎田ぺこら")                                       # 忘れる
        self.assertEqual(_speakers.voices_summary().get(VE, []), [])
        j, d = self.rediarize()
        self.assertFalse(j.get("named"))
        self.assertEqual([s["name"] for s in d["speakers"]], ["話者1", "話者2"])


class TestRerunReceive(_ProofStore):
    """POST /api/rerun の受付(human/proof/rerun.validate_rerun)。断る組・疑わしい行の選び方・評価用は断る(ジョブの中身は見ない)"""

    def put(self, segs, **extra):
        d = fixed_doc(TID_A, proofed=False)
        d.update(segments=segs, original=[{"start": g["start"], "end": g["end"], "text": g["text"]} for g in segs], end=10.0, **extra)
        self.put_doc(d, TID_A)

    def sparse_rows(self):
        """f1 = 長い区間に文字が少ない印つきで、機械の出力のまま(疑わしい)。f2 = 印なし"""
        return [{"id": "f1", "start": 0.0, "end": 4.0, "text": "あ", "speaker": "", "flag": _txtext.SPARSE_FLAG},
                {"id": "f2", "start": 4.0, "end": 8.0, "text": "いい", "speaker": "", "flag": ""}]

    def rerun(self, **req):
        return S._rerun.validate_rerun(dict({"tid": TID_A, "model": "small"}, **req))

    def test_refused(self):
        no_flag = self.sparse_rows()
        no_flag[0]["flag"] = ""                                            # 印が無い = 疑わしい行は無い
        for name, rows, extra, req, code in (
                ("2つ目のエンジンで全体を差し替える", self.sparse_rows(), {}, dict(engine="alt", result="replace", target="whole"), "bad_combo"),
                ("2つ目のエンジンで行を差し替える", self.sparse_rows(), {}, dict(engine="alt", result="replace", target="rows", ids=["f1"]), "bad_combo"),
                ("いつものエンジンで候補", self.sparse_rows(), {}, dict(engine="main", result="propose", target="rows", ids=["f1"]), "bad_combo"),
                ("疑わしい行が無い", no_flag, {}, dict(target="flagged"), "empty"),
                ("評価用", self.sparse_rows(), {"evalSet": True}, dict(target="flagged"), "eval_set")):
            with self.subTest(name):
                self.put(rows, **extra)
                with self.assertRaises(ed_state.ApiError) as c:
                    self.rerun(**req)
                self.assertEqual((c.exception.code, c.exception.status), (code, 400))

    def test_flagged_picks_the_suspect_rows_not_the_sent_ids(self):
        self.put(self.sparse_rows())
        with mock.patch("ytt.tools.check_source", lambda p: p):
            spec, kind = self.rerun(target="flagged", ids=["f2"])          # 送った ids は無視し、サーバーが疑わしい行を選ぶ
        self.assertEqual(kind, "retranscribe")
        self.assertEqual(spec["mode"], "each")
        self.assertEqual(spec["ids"], ["f1"])


if __name__ == "__main__":
    unittest.main()
