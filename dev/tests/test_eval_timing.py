"""dev/eval_timing.py(行の時刻を原則の数字で測る道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_timing.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバー・ネットワーク・ffmpeg は使わない
(--apply の 1 件だけ、eval_asr.load_serve("fake") で editor の後処理 expand_segments を読む)。
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
REPO = os.path.join(os.path.dirname(HERE), "src")   # ツールと ytt_core の置き場所
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import eval_timing as T  # noqa: E402


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def seg(i, a, b, text, proofed=True):
    return {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "proofed": proofed, "flag": ""}


def orig(a, b, text):
    return {"start": a, "end": b, "text": text}


REVIEWED = {"at": 1, "via": "drill", "durationSec": 60.0}


class Env:
    """一時の作業データ(<root>/transcribe/transcripts/)に文書を作る"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.tdir = os.path.join(self.root, "transcribe", "transcripts")
        os.makedirs(self.tdir)

    def close(self):
        self._tmp.cleanup()

    def doc(self, tid, segments, original, reviewed=True, run=None, start=0.0, params=None, title="t"):
        d = {"schema": "transcribe/v1", "id": tid, "title": title, "start": start, "end": start + 60.0, "duration": 600.0,
             "segments": segments, "original": original, "updatedAt": ms("2026-10-01"), "evalSet": True,
             "params": params or {"wordSplit": True, "splitChars": 16, "stripPunct": True},
             "recognition": {"runs": [run or {"engine": "whisper.cpp", "model": "large-v3", "at": ms("2026-10-05")}]}}
        if reviewed:
            d["evalReviewed"] = dict(REVIEWED)
        self.write(tid + ".json", d)

    def write(self, name, d):
        with open(os.path.join(self.tdir, name), "w", encoding="utf-8") as f:
            f.write(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False))


# 5 つの数字が 1 回ずつ出る文書: ①頭(s1)・①末(s2)・②前(s3)・②次(s4)・文字が合わない行(s5)・校正済みでない行(s0)
FIVE_SEGS = [seg(0, 0.0, 0.9, "まえのぎょう", proofed=False), seg(1, 1.0, 2.0, "こんにちは"), seg(2, 2.0, 3.0, "元気ですか"),
             seg(3, 3.5, 4.5, "そうですね"), seg(4, 5.0, 6.0, "ありがとう"), seg(5, 6.2, 7.0, "全然違う")]
FIVE_ORIG = [orig(1.2, 2.0, "こんにちは"),      # 頭が 0.2 秒遅い → ①頭
             orig(1.95, 2.7, "元気ですか"),     # 末が 0.3 秒早い → ①末(頭の 0.05 秒早いのは余裕の中)
             orig(2.8, 4.5, "そうですね。"),    # 前の人の行の終わり 3.0 より 0.2 秒前から → ②前(句読点は比べない)
             orig(5.0, 6.4, "ありがとう"),      # 次の人の行の始まり 6.2 より 0.2 秒後ろまで → ②次
             orig(6.25, 7.0, "ほかの言葉")]     # 人の「全然違う」と文字が合わない → 数えない


class TimingTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_five_numbers(self):
        self.env.doc("aaaaaaaaaaaa", FIVE_SEGS, FIVE_ORIG)
        res = T.evaluate(self.env.root)
        o = res["overall"]
        self.assertEqual(o["n"], 4)                                                          # 文字が合う行(校正済み 5 行のうち)
        self.assertEqual(o["counts"], {"head": 1, "tail": 1, "prev": 1, "next": 1})
        self.assertEqual((o["head"], o["tail"], o["prev"], o["next"]), (0.25, 0.25, 0.25, 0.25))
        self.assertAlmostEqual(o["extraMedian"], 0.225, places=3)                            # はみ出し [0, 0.05, 0.4, 0.7]
        self.assertAlmostEqual(o["extraMean"], 0.2875, delta=0.001)
        m = res["meta"]
        self.assertEqual((m["docs"], m["proofedRows"], m["matchedRows"], m["unmatchedRows"]), (1, 5, 4, 1))
        self.assertTrue(m["few"])                                                            # 100 行未満は「まだ少ない(参考)」
        d = res["byDoc"][0]
        self.assertEqual((d["id"], d["proofed"], d["n"], d["unmatched"]), ("aaaaaaaaaaaa", 5, 4, 1))
        self.assertNotIn("_rows", d)

    def test_tolerance_is_strict(self):
        # ちょうど 0.1 秒のずれは余裕の中(浮動小数の誤差で数えない)
        self.env.doc("aaaaaaaaaaaa", [seg(1, 0.2, 1.2, "こんにちは"), seg(2, 3.0, 4.0, "元気ですか")],
                     [orig(0.3, 1.1, "こんにちは"), orig(2.9, 4.1, "元気ですか")])
        o = T.evaluate(self.env.root)["overall"]
        self.assertEqual(o["counts"], {"head": 0, "tail": 0, "prev": 0, "next": 0})
        self.assertAlmostEqual(o["extraMean"], 0.1, places=3)                                # 2 行目のはみ出し 0.1 + 0.1 の平均

    def test_text_match(self):
        self.assertTrue(T.text_match("こんにちは、みんな", "こんにちはみんなー"))                   # 頭の 3 文字
        self.assertTrue(T.text_match("えっと今日は", "今日は"))                               # 末の 3 文字
        self.assertTrue(T.text_match("ＡＢＣです", "ABCです!"))                             # NFKC・記号は比べない(大文字と小文字は区別する)
        self.assertFalse(T.text_match("全然違う", "ほかの言葉"))
        self.assertFalse(T.text_match("", "あ"))

    def test_only_reviewed_docs(self):
        self.env.doc("aaaaaaaaaaaa", FIVE_SEGS, FIVE_ORIG)
        self.env.doc("bbbbbbbbbbbb", FIVE_SEGS, FIVE_ORIG, reviewed=False)                  # 確かめ済みでない評価用
        self.env.doc("cccccccccccc", FIVE_SEGS, [])                                          # 機械の出力が無い
        self.env.write("dddddddddddd.json", "{壊れた")
        self.env.write("aaaaaaaaaaaa.edit.json", {"x": 1})                                   # 文書でないファイルは見ない
        res = T.evaluate(self.env.root)
        self.assertEqual(res["meta"]["docs"], 1)
        self.assertEqual(res["meta"]["skipped"], {"broken": 1, "notReviewed": 1, "noOriginal": 1, "outOfRange": 0})

    def test_groups_by_engine_and_post(self):
        post = {"version": "0.57.1", "endTrim": 0.0, "joinGap": 0.5, "pullEnds": False, "retime": "large-v3"}
        self.env.doc("aaaaaaaaaaaa", FIVE_SEGS, FIVE_ORIG, run={"engine": "whisper.cpp", "model": "large-v3", "at": ms("2026-10-08"), "post": post})
        self.env.doc("bbbbbbbbbbbb", FIVE_SEGS, FIVE_ORIG, run={"engine": "whisper.cpp", "model": "large-v3", "at": ms("2026-10-05"), "retimed": {"rows": 3}})
        self.env.doc("cccccccccccc", FIVE_SEGS, FIVE_ORIG, run={"kind": "evalRedo", "engine": "faster-whisper", "model": "small"})   # 最初の認識の記録が無い
        res = T.evaluate(self.env.root)
        keys = sorted(g["key"] for g in res["groups"])
        self.assertEqual(keys, sorted(["whisper.cpp large-v3 | 後処理 v0.57.1 endTrim=0.0 join=0.5 配り直し=large-v3",
                                       "whisper.cpp large-v3 | 後処理の記録なし(0.57.0 まで)・配り直しあり",
                                       "faster-whisper small | 後処理の記録なし(0.57.0 まで)"]))
        self.assertTrue(all(g["n"] == 4 and g["docs"] == 1 for g in res["groups"]))
        # 機械の出力を作った時刻(最初の認識の at)で絞る
        res = T.evaluate(self.env.root, since="2026-10-07")
        self.assertEqual([d["id"] for d in res["byDoc"]], ["aaaaaaaaaaaa"])
        self.assertEqual(res["meta"]["skipped"]["outOfRange"], 2)                             # at の無い文書は updatedAt(10-01)
        res = T.evaluate(self.env.root, until="2026-10-05")
        self.assertEqual([d["id"] for d in res["byDoc"]], ["bbbbbbbbbbbb", "cccccccccccc"])

    def test_empty_and_report(self):
        res = T.evaluate(self.env.root)
        self.assertEqual(res["overall"]["n"], 0)
        self.assertIsNone(res["overall"]["head"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.print_report(res)
        self.assertIn("測れる文書がありません", buf.getvalue())
        self.env.doc("aaaaaaaaaaaa", FIVE_SEGS, FIVE_ORIG)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.print_report(T.evaluate(self.env.root))
        self.assertIn("①末  25%", buf.getvalue())

    def test_out_writes_only_the_given_file(self):
        self.env.doc("aaaaaaaaaaaa", FIVE_SEGS, FIVE_ORIG)
        out = os.path.join(self.env.root, "elsewhere", "r.json")
        with contextlib.redirect_stdout(io.StringIO()):
            T.main(["--data-dir", self.env.root, "--out", out])
        with open(out, encoding="utf-8") as f:
            got = json.load(f)
        self.assertEqual(got["meta"]["schema"], T.SCHEMA)
        self.assertEqual(got["overall"]["n"], 4)
        self.assertFalse(os.path.exists(os.path.join(self.env.root, "transcribe", "evals")))   # 作業データには書かない


class ApplyTest(unittest.TestCase):
    """--apply: 保存してある生出力(asr.json)に後処理(0.57.0 / 7-1 だけ / 0.57.1)を当て直す。editor の expand_segments をそのまま使う"""

    @classmethod
    def setUpClass(cls):
        cls.S = T.eval_asr.load_serve("fake")
        cls.tmp_data = os.environ.get("TRANSCRIBE_DATA_DIR", "")

    @classmethod
    def tearDownClass(cls):
        if cls.tmp_data and os.path.basename(cls.tmp_data).startswith("eval_asr_"):
            shutil.rmtree(cls.tmp_data, ignore_errors=True)

    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_variants(self):
        # 範囲の先頭が 10 秒の文書。生出力の時刻は元の動画の秒。続いている 2 行(すき間 0.2 秒)
        raw = [{"start": 10.0, "end": 11.0, "text": "こんにちは", "words": [[10.0, 11.0, "こんにちは", 0.9]]},
               {"start": 11.2, "end": 12.0, "text": "元気ですか", "words": [[11.2, 12.0, "元気ですか", 0.9]]}]
        run = {"engine": "whisper.cpp", "model": "large-v3", "audioSec": 5.0, "at": ms("2026-10-05")}
        self.env.doc("aaaaaaaaaaaa", [seg(1, 10.0, 11.2, "こんにちは"), seg(2, 11.2, 12.0, "元気ですか")],
                     [orig(10.0, 10.9, "こんにちは"), orig(11.2, 12.0, "元気ですか")], run=run, start=10.0)   # original = 0.57.0 の後処理(終わりを 0.1 秒早めた)
        self.env.write("aaaaaaaaaaaa.asr.json", {"schema": T.ASR_SCHEMA, "run": run, "segments": raw})
        self.env.doc("bbbbbbbbbbbb", FIVE_SEGS, FIVE_ORIG)                                      # 生出力が無い文書は --apply では数えない
        before = (self.S.ed_jobs.END_TRIM, self.S.ed_jobs.JOIN_GAP)
        res = T.evaluate(self.env.root, apply=True, serve=self.S)
        self.assertEqual((self.S.ed_jobs.END_TRIM, self.S.ed_jobs.JOIN_GAP), before)          # 差し替えた値は戻す
        ap = res["apply"]
        self.assertEqual((ap["docs"], ap["skipped"]), (1, {"noAsr": 1, "badAsr": 0}))
        by = {v["key"]: v for v in ap["variants"]}
        self.assertEqual([v["key"] for v in ap["variants"]], ["v0570", "trim0", "v0571"])
        self.assertEqual(by["v0570"]["overall"]["counts"]["tail"], 1)                          # 10.9 < 11.2 − 0.1 = 末が切れる
        self.assertEqual(by["trim0"]["overall"]["counts"]["tail"], 1)                          # 11.0 でもまだ切れる
        self.assertEqual(by["v0571"]["overall"]["counts"]["tail"], 0)                          # 次の行の始まり 11.2 へつなぐ = 切れない
        self.assertEqual(by["v0571"]["overall"]["n"], 2)
        self.assertEqual(by["v0570"]["byDoc"][0]["reproduced"], 1.0)                           # 0.57.0 の後処理で original と同じ行になる
        self.assertNotIn("reproduced", by["v0571"]["byDoc"][0])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.print_report(res)
        self.assertIn("0.57.1 の後処理", buf.getvalue())

    def test_asr_raw_shapes(self):
        doc = {"start": 5.0, "params": {"wordSplit": False, "stripPunct": False}}
        self.assertIsNone(T.asr_raw(doc, {"schema": "other", "segments": []}))
        raw, spec, dur, start = T.asr_raw(doc, {"schema": T.ASR_SCHEMA, "run": {"engine": "faster-whisper", "audioSec": 3.0},
                                                "segments": [{"start": 5.5, "end": 6.0, "text": "あ", "words": [[5.5, 6.0, "あ", None]]}, {"start": "x"}]})
        self.assertEqual(raw, [{"start": 0.5, "end": 1.0, "text": "あ", "words": [(0.5, 1.0, "あ")]}])   # 行の秒に戻す・単語は 3 つ組
        self.assertEqual(spec, {"wordSplit": False, "stripPunct": False, "engine": "faster-whisper"})
        self.assertEqual((dur, start), (3.0, 5.0))


if __name__ == "__main__":
    unittest.main()
