"""dev/eval_fill.py(認識のあとの後処理の様子見の物差し。計画の K1)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_fill.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバー・ネットワーク・editor の部品は使わない。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
sys.path.insert(0, HERE)
import eval_fill as F  # noqa: E402

NAME_FLAG = "名簿の呼び名に直した(別のエンジンも同じ呼び名)"


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def seg(i, a, b, text, proofed=False, fill_from=None, flag="", proofed_at=None):
    s = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": flag}
    if proofed:
        s["proofed"] = True
    if proofed_at:
        s["proofedAt"] = proofed_at
    if fill_from is not None:
        s["fill"] = {"from": fill_from, "by": "sense-voice"}
    return s


def machine(a, b, text, filled=False):
    """機械の出力 original の行。whisper の行は確信度を持ち、別の読みで埋めた行は持たない"""
    o = {"start": a, "end": b, "text": text}
    if not filled:
        o["avg_logprob"] = -0.3
    return o


class Env:
    """一時の作業データ(<root>/transcribe/transcripts/)に文書を作る"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.tdir = os.path.join(self.root, "transcribe", "transcripts")
        os.makedirs(self.tdir)

    def close(self):
        self._tmp.cleanup()

    def doc(self, tid, segments, original, auto_fill=True, eval_set=False, runs=None, raw=None, updated=None, **extra):
        d = {"id": tid, "title": "t-" + tid, "segments": segments, "original": original, "updatedAt": updated or ms("2026-10-09"),
             "params": {"autoFill": auto_fill}, "recognition": {"runs": runs or [{"engine": "whisper.cpp", "fill": {"engine": "sense-voice", "rows": 1, "dup": 0}}]}}
        if eval_set:
            d["evalSet"] = True
        d.update(extra)
        with open(os.path.join(self.tdir, tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        if raw is not None:
            with open(os.path.join(self.tdir, tid + ".asr.json"), "w", encoding="utf-8") as f:
                json.dump({"schema": "youtube-tools-asr/v1", "segments": raw}, f, ensure_ascii=False)


class FoldTest(unittest.TestCase):
    def test_fold_ignores_notation(self):
        self.assertEqual(F.fold("ペコラ、ー です!"), F.fold("ぺこら です"))
        self.assertEqual(F.fold("ＡＢＣ１"), "abc1")

    def test_edit_distance(self):
        self.assertEqual(F.edit_distance("あいう", "あいう"), 0)
        self.assertEqual(F.edit_distance("あいう", "あえう"), 1)
        self.assertIsNone(F.edit_distance("あ" * (F.MAX_EDIT_CHARS + 1), "あ"))


class EvalFillTest(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def run_eval(self, **kw):
        return F.evaluate(self.env.root, **kw)

    def test_kinds(self):
        e = self.env
        orig = [machine(0, 2, "こんにちは"),
                machine(2, 5, "やけくそなのかな", filled=True),      # 残した(別の読みのまま・校正済み)
                machine(5, 8, "ゲームやろう", filled=True),          # 直した(人の最終は別の読みに近い)
                machine(8, 11, "あいうえお", filled=True),          # 戻した(札で戻した = 印なし。生の結果と同じ)
                machine(11, 14, "かきくけこ", filled=True),          # 戻した(印が残ったまま手で whisper の文字に)
                machine(14, 17, "さしすせそ", filled=True),          # 消した
                machine(17, 20, "たちつてと", filled=True)]          # 未確認
        segs = [seg(1, 0, 2, "こんにちは", proofed=True),
                seg(2, 2, 5, "やけくそなのかな", proofed=True, fill_from="ーーー"),
                seg(3, 5, 8, "ゲームやろうよ", proofed=True, fill_from="げ"),
                seg(4, 8, 11, "あー", proofed=True),
                seg(5, 11, 14, "か", proofed=True, fill_from="か"),
                seg(7, 17, 20, "たちつてと", fill_from="た")]
        raw = [{"start": 8.1, "end": 10.9, "text": "あー"}]
        e.doc("aaaaaaaaaaa1", segs, orig, raw=raw)
        a = self.run_eval()["a"]
        self.assertEqual((a["kept"], a["edited"], a["reverted"], a["deleted"], a["unchecked"]), (1, 1, 2, 1, 1))
        self.assertEqual(a["rows"], 6)
        self.assertEqual(a["judged"], 5)
        self.assertEqual(a["keptRate"], 0.2)
        self.assertEqual(a["revertRate"], 0.6)
        self.assertEqual(a["closer"]["fill"], 1)
        self.assertTrue(a["few"])

    def test_skips_eval_and_no_autofill_and_rerun(self):
        e = self.env
        orig = [machine(0, 2, "あいう", filled=True)]
        segs = [seg(1, 0, 2, "あいう", proofed=True, fill_from="あ")]
        e.doc("bbbbbbbbbbb1", segs, orig, eval_set=True)
        e.doc("bbbbbbbbbbb2", segs, orig, auto_fill=False)
        e.doc("bbbbbbbbbbb3", segs, orig, runs=[{"engine": "whisper.cpp"}, {"kind": "range", "engine": "whisper.cpp"}])
        res = self.run_eval()
        self.assertEqual(res["docs"], 1)          # 評価用・後処理なしは数えない
        self.assertEqual(res["rerunDocs"], 1)
        self.assertEqual(res["a"]["rows"], 0)

    def test_name_rows_and_cleanup_records(self):
        e = self.env
        orig = [machine(0, 2, "ぺこらちゃん"), machine(2, 4, "みこち")]
        segs = [seg(1, 0, 2, "ぺこらちゃん", proofed=True, fill_from="へこらちゃん", flag=NAME_FLAG),
                seg(2, 2, 4, "みこち", fill_from="みこち", flag=NAME_FLAG)]
        e.doc("ccccccccccc1", segs, orig, runs=[{"engine": "whisper.cpp", "fill": {"rows": 0, "dup": 2}}], diarization={"fillDropped": 3})
        res = self.run_eval()
        self.assertEqual(res["d"], {"rows": 2, "proofed": 1, "retyped": 1})
        self.assertEqual(res["c"], {"dup": 2, "dropped": 3})
        self.assertEqual(res["a"]["rows"], 0)   # 確信度のある行は A に数えない

    def test_period_uses_proofed_at(self):
        e = self.env
        orig = [machine(0, 2, "あいうえ", filled=True), machine(2, 4, "かきくけ", filled=True)]
        segs = [seg(1, 0, 2, "あいうえ", proofed=True, fill_from="あ", proofed_at=ms("2026-10-01")),
                seg(2, 2, 4, "かきくけ", proofed=True, fill_from="か", proofed_at=ms("2026-10-10"))]
        e.doc("ddddddddddd1", segs, orig)
        self.assertEqual(self.run_eval(since="2026-10-05")["a"]["kept"], 1)
        self.assertEqual(self.run_eval(until="2026-10-05")["a"]["kept"], 1)
        self.assertEqual(self.run_eval()["a"]["kept"], 2)

    def test_split_fill_rows_match_by_overlap(self):
        """人が時刻を少し直しても、半分以上重なれば同じ所とみなす"""
        e = self.env
        orig = [machine(0, 4, "ながいべつのよみ", filled=True)]
        segs = [seg(1, 0.3, 4.2, "ながいべつのよみ", proofed=True, fill_from="な")]
        e.doc("eeeeeeeeeee1", segs, orig)
        self.assertEqual(self.run_eval()["a"]["kept"], 1)

    def test_report_and_json(self):
        e = self.env
        e.doc("fffffffffff1", [seg(1, 0, 2, "あいう", proofed=True, fill_from="あ")], [machine(0, 2, "あいう", filled=True)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(F.main(["--data-dir", e.root, "--json"]), 0)
        text = out.getvalue()
        self.assertIn("残した", text)
        self.assertIn("まだ少ない", text)
        saved = text.strip().splitlines()[-1]
        self.assertTrue(saved.startswith("保存: "))
        path = saved[len("保存: "):]
        self.assertTrue(path.startswith(os.path.join(e.root, "transcribe", "evals", "fill")))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["schema"], F.SCHEMA)

    def test_empty_data(self):
        res = self.run_eval()
        self.assertEqual(res["docs"], 0)
        self.assertIsNone(res["a"]["keptRate"])


if __name__ == "__main__":
    unittest.main()
