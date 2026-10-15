"""src/eval/tools/eval_fill.py(認識のあとの後処理の様子見の物差し)のテスト。リポジトリ直下で:

    py -3.10 -m unittest src/eval/tools/tests/test_eval_fill.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバー・ネットワーク・③ の部品は使わない
(確かめるの答えは app/check/answers.jsonl を一時フォルダに書いて読ませる)。
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
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import eval_fill as F  # noqa: E402

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

    def answers(self, rows):
        """確かめるの答えの記録(入口の作業データ app/check/answers.jsonl)を書く"""
        d = os.path.join(self.root, "app", "check")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "answers.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


_n = [0]


def answer(tid, row, choice, text=None, at=None, before=None, source="fill"):
    """read:fill の答えの行(human/check/apply の形)"""
    _n[0] += 1
    at = at or ms("2026-10-12")
    ans = {"choice": choice}
    if text is not None:
        ans["text"] = text
    applied = {"docId": tid, "row": row, "source": source, "choice": choice}
    if before is not None:
        applied["before"] = before
    return {"id": "a%013d-%06x" % (at, _n[0]), "at": at, "kind": "read", "source": source, "card": "read:%s:%s#%s" % (source, tid, row),
            "case": {"id": "", "title": ""}, "target": {"docId": tid, "row": row}, "guess": "1", "answer": ans, "ms": 1000, "applied": applied}


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
                machine(14, 17, "さしすせそ", filled=True),          # 未確認(行が無いが、後ろの隣の行が校正済みでない)
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
        self.assertEqual((a["kept"], a["edited"], a["reverted"], a["deleted"], a["unchecked"]), (1, 1, 2, 0, 2))
        self.assertEqual(a["rows"], 6)
        self.assertEqual(a["judged"], 4)
        self.assertEqual(a["keptRate"], 0.25)
        self.assertEqual(a["revertRate"], 0.5)
        self.assertEqual(a["closer"]["fill"], 1)
        self.assertTrue(a["few"])

    def test_not_proofed_changes_are_unchecked(self):
        """5b: 校正済みでない行は、直した・戻した・消したに見えても未確認(人が確認していない物を当たり・外れに入れない)"""
        e = self.env
        orig = [machine(0, 2, "ゲームやろう", filled=True),   # 文字が違う・校正済みでない
                machine(2, 4, "あいうえお", filled=True),     # whisper の文字に戻っている・校正済みでない
                machine(4, 6, "かきくけこ", filled=True),     # 行が無い・前の隣が校正済みでない
                machine(8, 10, "さしすせそ", filled=True),    # 行が無い・前後の隣がどちらも校正済み = 消した
                machine(12, 14, "たちつてと", filled=True)]   # 行が無い・端(前の隣だけ・校正済み)= 消した
        segs = [seg(1, 0, 2, "ゲームやろうよ", fill_from="げ"),
                seg(2, 2, 4, "あー", fill_from="あー"),
                seg(3, 6, 8, "なにぬ", proofed=True),
                seg(4, 10, 12, "はひふ", proofed=True)]
        e.doc("abababababa1", segs, orig)
        a = self.run_eval()["a"]
        self.assertEqual((a["kept"], a["edited"], a["reverted"], a["deleted"], a["unchecked"]), (0, 0, 0, 2, 3))

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
        self.assertEqual(res["d"], {"rows": 2, "proofed": 1, "retyped": 1, "checked": {"kept": 0, "reverted": 0, "edited": 0}})
        self.assertEqual(res["c"], {"dup": 2, "dropped": 3})
        self.assertEqual(res["a"]["rows"], 0)   # 確信度のある行は A に数えない

    def test_llm_rows(self):
        """E: <id>.llm.json の当てた案を今の行と突き合わせる。LLM の印は D に数えない"""
        e = self.env
        llm_flag = "名簿の呼び名に直した(LLM。元の文字は「別の読み」の札)"
        segs = [seg(1, 0, 2, "みこちゃん来た", proofed=True, fill_from="メコちゃん来た", flag=llm_flag),   # 残した
                seg(2, 2, 4, "メコちゃん来た", proofed=True),                                            # 戻した(札で戻した = 印なし)
                seg(3, 4, 6, "みこちゃん来た", fill_from="メコちゃん来た", flag=llm_flag),                # 未確認
                seg(4, 8, 10, "みこち来た", proofed=True)]                                               # 直した(6〜8 の行は前の隣が校正済みでない = 未確認)
        for s in segs[:1] + segs[2:3]:
            s["fill"]["by"] = "llm"
        orig = [machine(i * 2, i * 2 + 2, "メコちゃん来た") for i in range(5)]
        e.doc("abcdefabcde1", segs, orig, auto_fill=False, params={"autoLlm": True})
        items = [{"row": i, "start": i * 2.0, "end": i * 2.0 + 2, "text": "メコちゃん来た", "from": "メコちゃん", "to": "みこちゃん", "confidence": 0.8, "rejected": None}
                 for i in range(5)] + [{"row": 0, "start": 0, "end": 2, "text": "x", "from": "a", "to": "b", "rejected": "length"}]
        with open(os.path.join(e.tdir, "abcdefabcde1.llm.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-llm/v1", "items": items}, f, ensure_ascii=False)
        res = self.run_eval()
        x = res["e"]
        self.assertEqual((x["kept"], x["reverted"], x["unchecked"], x["deleted"], x["edited"]), (1, 1, 2, 0, 1))
        self.assertEqual(res["d"]["rows"], 0)   # LLM の印は D に混ぜない
        e.answers([answer("abcdefabcde1", "s3", "2", before={"text": "みこちゃん来た", "fill": {"from": "メコちゃん来た", "by": "llm"}, "flag": llm_flag})])
        x = self.run_eval()["e"]   # 未確認だった行に確かめるで「戻す」と答えた = 戻した
        self.assertEqual((x["kept"], x["reverted"], x["unchecked"], x["deleted"], x["edited"]), (1, 2, 1, 0, 1))
        self.assertEqual(self.run_eval()["d"]["checked"], {"kept": 0, "reverted": 0, "edited": 0})   # LLM の行の答えは D に数えない

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
        self.assertEqual(res["check"], {"answers": 0, "a": 0, "e": 0, "d": 0, "unmatched": 0})


class AnswerTest(unittest.TestCase):
    """5b-1: 確かめるの read:fill の答え(1 = 残した・2 = 戻した・打つ = 直した)を人の判断の正として読む"""

    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_answers_are_the_judgement(self):
        e, tid = self.env, "acacacacaca1"
        orig = [machine(0, 2, "あいうえお", filled=True),    # 1 = 残した(校正済みでない・札のまま)
                machine(2, 4, "かきくけこ", filled=True),    # 2 = 戻した(認識のままに戻した = 札も消えた)
                machine(4, 6, "さしすせそ", filled=True),    # 打つ = 直した(人の最終は別の読みに近い)
                machine(6, 8, "たちつてと", filled=True),    # 答えなし・校正済みでない = 未確認
                machine(8, 10, "なにぬねの", filled=True)]   # 答えなし・校正済み・札のまま = 残した
        segs = [seg(1, 0, 2, "あいうえお", fill_from="あ"),
                seg(2, 2, 4, "かき"),
                seg(3, 4, 6, "さしすせぞ"),
                seg(4, 6, 8, "たちつてと", fill_from="た"),
                seg(5, 8, 10, "なにぬねの", proofed=True, fill_from="な")]
        e.doc(tid, segs, orig)
        e.answers([answer(tid, "s1", "1"),
                   answer(tid, "s2", "2", before={"text": "かきくけこ", "fill": {"from": "かき", "by": "sense-voice"}, "flag": "別の読みで埋めた"}),
                   answer(tid, "s3", "other", text="さしすせぞ", before={"text": "さしすせそ", "fill": {"from": "ざじ", "by": "sense-voice"}, "flag": ""}),
                   answer(tid, "s9", "1"),                  # 行が無い = 数えない
                   answer("bcbcbcbcbcb1", "s1", "2")])      # 測らない文書 = 数えない
        res = F.evaluate(e.root)
        a = res["a"]
        self.assertEqual((a["kept"], a["edited"], a["reverted"], a["deleted"], a["unchecked"]), (2, 1, 1, 0, 1))
        self.assertEqual(a["closer"]["fill"], 1)
        self.assertEqual(a["keptRate"], 0.5)
        self.assertEqual(res["check"], {"answers": 5, "a": 3, "e": 0, "d": 0, "unmatched": 2})

    def test_undo_and_later_answer_and_period(self):
        e, tid = self.env, "adadadadada1"
        e.doc(tid, [seg(1, 0, 2, "あいうえお", fill_from="あ"), seg(2, 2, 4, "かきくけこ", fill_from="か")],
              [machine(0, 2, "あいうえお", filled=True), machine(2, 4, "かきくけこ", filled=True)])
        first = answer(tid, "s1", "2", at=ms("2026-10-11"))
        undo = {"id": "a%013d-ffffff" % ms("2026-10-11", "12:01:00"), "at": ms("2026-10-11", "12:01:00"), "undo": first["id"], "reverted": {}}
        e.answers([first, undo, answer(tid, "s1", "1", at=ms("2026-10-12")),   # 戻した答えは数えない・後の答えが効く
                   answer(tid, "s2", "1", at=ms("2026-10-01"))])
        a = F.evaluate(e.root)["a"]
        self.assertEqual((a["kept"], a["reverted"], a["unchecked"]), (2, 0, 0))
        res = F.evaluate(e.root, since="2026-10-05")   # 答えのある行の時刻は答えの時刻
        self.assertEqual((res["a"]["kept"], res["a"]["rows"]), (1, 1))
        self.assertEqual(res["check"]["answers"], 1)

    def test_name_rows_answers(self):
        """D: 札を残す答えは今の印で、戻す・打つは答えに残る反映の前の印で D の行と分かる"""
        e, tid = self.env, "aeaeaeaeaea1"
        segs = [seg(1, 0, 2, "ぺこらちゃん", fill_from="へこらちゃん", flag=NAME_FLAG),
                seg(2, 2, 4, "へこら"),
                seg(3, 4, 6, "ぺこーら")]
        e.doc(tid, segs, [machine(0, 2, "へこらちゃん"), machine(2, 4, "へこら"), machine(4, 6, "へこら")])
        e.answers([answer(tid, "s1", "1"),
                   answer(tid, "s2", "2", before={"text": "ぺこら", "fill": {"from": "へこら", "by": "sense-voice"}, "flag": NAME_FLAG}),
                   answer(tid, "s3", "other", text="ぺこーら", before={"text": "ぺこら", "fill": {"from": "へこら", "by": "sense-voice"}, "flag": NAME_FLAG})])
        res = F.evaluate(e.root)
        self.assertEqual(res["d"]["rows"], 1)
        self.assertEqual(res["d"]["checked"], {"kept": 1, "reverted": 1, "edited": 1})
        self.assertEqual((res["check"]["d"], res["check"]["unmatched"]), (3, 0))

    def test_other_sources_are_ignored(self):
        e, tid = self.env, "afafafafafa1"
        e.doc(tid, [seg(1, 0, 2, "あいうえお", fill_from="あ")], [machine(0, 2, "あいうえお", filled=True)])
        e.answers([answer(tid, "s1", "2", source="alt")])
        res = F.evaluate(e.root)
        self.assertEqual((res["a"]["unchecked"], res["check"]["answers"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
