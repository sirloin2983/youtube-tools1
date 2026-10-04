"""dev/eval_alt.py(2つ目のエンジンとの食い違いの候補の当たり率を測る道具。計画 第2版 D1-b)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_alt.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。ネットワーク・ffmpeg・本物のエンジンは使わない。
editor の部品(serve.py)を読み込むので、test_eval_asr.py と同じ環境変数の決まり(YTT_DATA_DIR = inplace)に従う。
"""
import contextlib
import hashlib
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
sys.path.insert(0, HERE)
import eval_alt as E  # noqa: E402


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def row(a, b, text, **kw):
    return dict({"start": a, "end": b, "text": text}, **kw)


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


# 機械の最初の出力 original と、2つ目のエンジンの出力 alt(1 か所ずつ違う。候補は ()内)
ORIG = [row(0, 3, "私は猫が好き"), row(10, 13, "今日は晴れですね"), row(20, 23, "昼は蕎麦を食べる"), row(30, 33, "夜は星が見える"),
        row(40, 43, "朝は花が咲く"), row(50, 53, "海は青くて広い")]
ALT = [row(0, 3, "私は犬が好き"), row(10, 13, "今日は雨ですね"), row(20, 23, "昼は饂飩を食べる"), row(30, 33, "夜は月が見える"),
       row(40, 43, "朝は鳥が咲く"), row(50, 53, "海は青くて広い")]
T1 = ms("2026-10-05")


def seg(i, a, b, text, proofed=True, at=T1):
    g = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": ""}
    if proofed:
        g["proofed"] = True
        if at:
            g["proofedAt"] = at
    return g


def human_a(at=T1):
    """人の最終: 1 行目 = 候補どおり(当たり)・2 行目 = そのまま(外れ)・3 行目 = 別の語(別の直し)・4 行目の行は消した(分からない)・
    5 行目 = 校正済みでない(分からない)・6 行目 = 候補は無いが人が直した(拾えない直し)"""
    return [seg(1, 0, 3, "私は犬が好き", at=at), seg(2, 10, 13, "今日は晴れですね", at=at), seg(3, 20, 23, "昼はパンを食べる", at=at),
            seg(5, 40, 43, "朝は花が咲く", proofed=False), seg(6, 50, 53, "海は青くて深い", at=at)]


class Env:
    """一時の作業データ(<root>/transcribe/ の transcripts/ と learn-feedback.json)"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.tx = os.path.join(self.root, "transcribe")
        self.tdir = os.path.join(self.tx, "transcripts")
        os.makedirs(self.tdir)

    def close(self):
        self._tmp.cleanup()

    def doc(self, tid, segments, original=ORIG, alt=ALT, engine="llama.cpp", model="qwen3-asr-1.7b", updated=1, **kw):
        d = {"schema": "youtube-tools-transcript/v1", "id": tid, "title": "t" + tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
             "speakers": [], "updatedAt": updated, "segments": segments, "original": original}
        d.update(kw)
        self._write(tid + ".json", d)
        if alt is not None:
            self._write(tid + ".alt.json", {"schema": E.get_serve().ALT_SCHEMA, "id": tid, "engine": engine, "model": model, "rows": alt})

    def feedback(self, acc, rej):
        self._write("learn-feedback.json", {"stat": {}, "dismissed": {}, "alt": {"acc": acc, "rej": rej}}, under=self.tx)

    def _write(self, name, d, under=None):
        with open(os.path.join(under or self.tdir, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def run(self, **kw):
        return E.evaluate(self.root, **kw)

    def snapshot(self):
        out = {}
        for dirpath, _dirs, files in os.walk(self.root):
            for n in sorted(files):
                p = os.path.join(dirpath, n)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.root)] = hashlib.sha256(f.read()).hexdigest()
        return out


class TestJudge(unittest.TestCase):
    """判定の中心(純粋な関数。ファイルを作らない)"""

    @classmethod
    def setUpClass(cls):
        cls.S = E.get_serve()

    def judge(self, segments, **kw):
        return E.judge_doc(self.S, {"updatedAt": 1, "original": ORIG, "segments": segments}, {"rows": ALT}, **kw)

    def test_hit_miss_other_unknown(self):
        r = self.judge(human_a())
        by = {(c["wrong"], c["right"]): c for c in r["cands"]}
        self.assertEqual(set(by), {("猫", "犬"), ("晴れ", "雨"), ("蕎麦", "饂飩"), ("星", "月"), ("花", "鳥")})
        self.assertEqual(by[("猫", "犬")]["status"], "hit")
        self.assertEqual(by[("晴れ", "雨")]["status"], "miss")
        self.assertEqual(by[("蕎麦", "饂飩")]["status"], "other")
        self.assertEqual((by[("星", "月")]["status"], by[("星", "月")]["why"]), ("unknown", "removed"))
        self.assertEqual((by[("花", "鳥")]["status"], by[("花", "鳥")]["why"]), ("unknown", "notProofed"))

    def test_fixes_covered(self):
        """人の直し 3 か所(猫→犬・蕎麦→パン・広→深)のうち、候補が同じ所に出ていたのは 2 か所・当たりは 1 か所"""
        f = self.judge(human_a())["fixes"]
        self.assertEqual(len(f), 3)
        self.assertEqual(sum(x["covered"] for x in f), 2)
        self.assertEqual(sum(x["hit"] for x in f), 1)
        self.assertTrue(all(x["short"] for x in f))

    def test_fold_matches_alt_fold(self):
        """比べるときの文字の寄せ方は alt_fold: 人が right を全角・カタカナで書いても、伸ばしや記号を足しても当たり"""
        orig = [row(0, 3, "私はカレーが好き")]
        alt = [row(0, 3, "私はカレパンが好き")]
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": orig, "segments": [seg(1, 0, 3, "私はかれぱんが、好き!")]}, {"rows": alt})
        self.assertEqual([c["status"] for c in r["cands"]], ["hit"])

    def test_adjacent_insert_counts_as_hit(self):
        """候補が隣の 1 文字を足した置き換えの形(足りない文字を足す)で、人がその文字を足したら当たり"""
        orig = [row(0, 3, "私は猫が好き")]
        alt = [row(0, 3, "私は猫だが好き")]   # 「が」の前に「だ」を足す候補
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": orig, "segments": [seg(1, 0, 3, "私は猫だが好き")]}, {"rows": alt})
        self.assertEqual([c["status"] for c in r["cands"]], ["hit"])
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": orig, "segments": [seg(1, 0, 3, "私は猫が好き")]}, {"rows": alt})
        self.assertEqual([c["status"] for c in r["cands"]], ["miss"])

    def test_split_and_merged_rows(self):
        """人が行を分けた・つないだ(時刻の重なりのまとまり)でも、まとまりの文字で当たりが分かる"""
        orig = [row(0, 3, "私は猫が"), row(3, 6, "好きです")]
        alt = [row(0, 3, "私は犬が"), row(3, 6, "好きです")]
        merged = [seg(1, 0, 6, "私は犬が好きです")]
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": orig, "segments": merged}, {"rows": alt})
        self.assertEqual([c["status"] for c in r["cands"]], ["hit"])
        split = [seg(1, 0, 2, "私は犬"), seg(2, 2, 6, "が好きです")]
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": orig, "segments": split}, {"rows": alt})
        self.assertEqual([c["status"] for c in r["cands"]], ["hit"])

    def test_deleted_text_is_other(self):
        """人がその所の文字を消した(wrong でも right でもない)= 別の直し"""
        orig = [row(0, 3, "私は猫が好き")]
        alt = [row(0, 3, "私は犬が好き")]
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": orig, "segments": [seg(1, 0, 3, "私はが好き")]}, {"rows": alt})
        self.assertEqual([c["status"] for c in r["cands"]], ["other"])

    def test_time_range_by_group(self):
        """時期はまとまりの時刻(人の行の proofedAt の最大。無ければ文書の updatedAt)で絞る。範囲の外の候補は数えない"""
        r = self.judge(human_a(), since_ms=ms("2026-10-06"))
        # 校正済みの 1・2・3 行目と、校正済みでない・消した行(文書の updatedAt = 1 = 古い)は範囲の外
        self.assertEqual(r["cands"], [])
        self.assertFalse(r["inRange"])
        self.assertEqual(r["outOfRange"], 5)
        r = self.judge(human_a(), since_ms=ms("2026-10-05", "00:00:00"), until_ms=ms("2026-10-06"))
        self.assertEqual(len(r["cands"]), 3)   # 校正済みのまとまり 3 つだけ(updatedAt = 1 の行は外)

    def test_no_candidates_without_alt_rows(self):
        r = E.judge_doc(self.S, {"updatedAt": 1, "original": ORIG, "segments": human_a()}, {"rows": []})
        self.assertEqual(r["cands"], [])


class TestEvaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        E.get_serve()

    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_counts_rates_and_read_only(self):
        self.env.doc("aaaaaaaaaaa1", human_a())
        before = self.env.snapshot()
        res = self.env.run()
        self.assertEqual(self.env.snapshot(), before)                      # 作業データは書き換えない
        t = res["total"]
        self.assertEqual((t["candidates"], t["judged"], t["hit"], t["miss"], t["other"], t["unknown"]), (5, 3, 1, 1, 1, 2))
        self.assertEqual(t["unknownWhy"], {"notProofed": 1, "removed": 1})
        self.assertAlmostEqual(t["hitRate"], 1 / 3, places=3)             # 率は校正済みのまとまり(判定できた 3 件)だけ
        p = t["pickup"]
        self.assertEqual((p["fixes"], p["covered"], p["coveredHit"]), (3, 2, 1))
        self.assertEqual((p["coveredRate"], p["hitRateOfCovered"]), (round(2 / 3, 4), 0.5))
        self.assertEqual(sum(t["skipped"].values()), 0)
        self.assertEqual(res["meta"]["docs"], 1)
        self.assertTrue(res["meta"]["few"])                                # 判定できた候補が 100 件未満
        self.assertIn("まだ少ない(参考)", res["meta"]["fewNote"])
        self.assertIsNone(res["feedback"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(res)
        text = buf.getvalue()
        self.assertIn("まだ少ない(参考)", text)
        self.assertIn("当たり 1", text)
        self.assertIn("llama.cpp / qwen3-asr-1.7b", text)

    def test_eval_set_and_docs_without_alt_are_not_measured(self):
        self.env.doc("aaaaaaaaaaa1", human_a())
        self.env.doc("bbbbbbbbbbb2", human_a(), evalSet=True)             # 評価用(候補を出さない決まり。alt.json があっても入れない)
        self.env.doc("ccccccccccc3", human_a(), alt=None)                 # alt.json が無い
        res = self.env.run()
        self.assertEqual(res["meta"]["docs"], 1)
        self.assertEqual(res["meta"]["noAlt"], 1)
        self.assertEqual(res["meta"]["skipped"]["evalSet"], 1)
        self.assertEqual([d["id"] for d in res["byDoc"]], ["aaaaaaaaaaa1"])

    def test_no_original_and_broken_are_skipped(self):
        self.env.doc("aaaaaaaaaaa1", human_a(), original=[])
        with open(os.path.join(self.env.tdir, "bbbbbbbbbbb2.json"), "w", encoding="utf-8") as f:
            f.write("{")
        with open(os.path.join(self.env.tdir, "bbbbbbbbbbb2.alt.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        res = self.env.run()
        self.assertEqual(res["meta"]["docs"], 0)
        self.assertEqual(res["meta"]["skipped"]["noOriginal"], 1)
        self.assertEqual(res["meta"]["skipped"]["broken"], 1)
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            E.print_report(res)
        self.assertIn("対象なし", text.getvalue())

    def test_by_engine_and_by_doc(self):
        self.env.doc("aaaaaaaaaaa1", human_a())
        good = [seg(1, 0, 3, "私は犬が好き"), seg(2, 10, 13, "今日は雨ですね"), seg(3, 20, 23, "昼は饂飩を食べる"), seg(4, 30, 33, "夜は月が見える"),
                seg(5, 40, 43, "朝は鳥が咲く"), seg(6, 50, 53, "海は青くて広い")]
        self.env.doc("bbbbbbbbbbb2", good, engine="whisper.cpp", model="large-v3")
        res = self.env.run()
        self.assertEqual(sorted(res["byEngine"]), ["llama.cpp / qwen3-asr-1.7b", "whisper.cpp / large-v3"])
        b = res["byEngine"]["whisper.cpp / large-v3"]
        self.assertEqual((b["candidates"], b["hit"], b["hitRate"]), (5, 5, 1.0))
        self.assertEqual(res["total"]["candidates"], 10)
        worst = sorted(res["byDoc"], key=lambda d: d["hitRate"])
        self.assertEqual(worst[0]["id"], "aaaaaaaaaaa1")

    def test_since_until(self):
        # 校正済みでないまとまり・消した行のまとまりは、文書の updatedAt で時期を決める
        self.env.doc("aaaaaaaaaaa1", human_a(at=ms("2026-10-05")), updated=ms("2026-10-05"))
        self.env.doc("bbbbbbbbbbb2", human_a(at=ms("2026-10-10")), updated=ms("2026-10-10"))
        self.assertEqual(self.env.run()["meta"]["docs"], 2)
        res = self.env.run(since="2026-10-08")
        self.assertEqual([d["id"] for d in res["byDoc"]], ["bbbbbbbbbbb2"])
        res = self.env.run(until="2026-10-05")                             # until はその日を含む
        self.assertEqual([d["id"] for d in res["byDoc"]], ["aaaaaaaaaaa1"])
        self.assertEqual(self.env.run(since="2026-11-01")["meta"]["docs"], 0)
        self.assertEqual(self.env.run(since="2026-11-01")["meta"]["skipped"]["outOfRange"], 2)

    def test_feedback_acceptance(self):
        self.env.doc("aaaaaaaaaaa1", human_a())
        self.env.feedback(acc=3, rej=1)
        res = self.env.run()
        self.assertEqual(res["feedback"], {"accepted": 3, "rejected": 1, "acceptRate": 0.75})

    def test_enough_candidates_is_not_few(self):
        """判定できた候補が 100 件以上なら「まだ少ない」を出さない"""
        n = 40
        orig = [row(i * 10, i * 10 + 3, "私は猫が好き") for i in range(n)]
        alt = [row(i * 10, i * 10 + 3, "私は犬が好き") for i in range(n)]
        segs = [seg(i, i * 10, i * 10 + 3, "私は犬が好き") for i in range(n)]
        for tid in ("aaaaaaaaaaa1", "bbbbbbbbbbb2", "ccccccccccc3"):
            self.env.doc(tid, segs, original=orig, alt=alt)
        res = self.env.run()
        self.assertEqual(res["total"]["judged"], 120)
        self.assertEqual(res["total"]["hit"], 120)
        self.assertFalse(res["meta"]["few"])
        self.assertEqual(res["meta"]["fewNote"], "")

    def test_json_is_saved_only_when_asked(self):
        self.env.doc("aaaaaaaaaaa1", human_a())
        quiet(E.main, ["--data-dir", self.env.root])
        self.assertFalse(os.path.isdir(os.path.join(self.env.tx, "evals")))
        quiet(E.main, ["--data-dir", self.env.root, "--json"])
        d = os.path.join(self.env.tx, "evals", "alt")
        names = os.listdir(d)
        self.assertEqual(len(names), 1)
        with open(os.path.join(d, names[0]), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["meta"]["schema"], "youtube-tools-alt-eval/v1")
        self.assertEqual(saved["total"]["judged"], 3)


if __name__ == "__main__":
    unittest.main()
