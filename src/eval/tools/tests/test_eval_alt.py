"""src/eval/tools/eval_alt.py(2つ目のエンジンとの食い違いの候補の当たり率を測る道具)のテスト。リポジトリ直下で:

    py -3.12 -m unittest src/eval/tools/tests/test_eval_alt.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。ネットワーク・ffmpeg・本物のエンジンは使わない。
③ の部品を serve の名前の受付で読み込むので、test_eval_asr.py と同じ環境変数の決まり(YTT_DATA_DIR = inplace)に従う。
確かめるの答えは app/check/answers.jsonl を一時フォルダに書いて読ませる。
"""
import contextlib
import hashlib
import io
import json
import os
import sys
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import eval_alt as E  # noqa: E402
from human.proof import alt as _alt  # noqa: E402
from ytt import testkit  # noqa: E402


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def row(a, b, text, **kw):
    return dict({"start": a, "end": b, "text": text}, **kw)


def quiet(fn, *a, **kw):
    """fn を呼ぶ(画面の出力は捨てる)。表示まで落ちないことを見るのにも使う"""
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

    def __init__(self, case):
        self.root = testkit.tempdir(case)   # case の終わりに消す
        self.tx = os.path.join(self.root, "transcribe")
        self.tdir = os.path.join(self.tx, "transcripts")
        os.makedirs(self.tdir)

    def doc(self, tid, segments, original=ORIG, alt=ALT, engine="llama.cpp", model="qwen3-asr-1.7b", updated=1, **kw):
        d = {"schema": "youtube-tools-transcript/v1", "id": tid, "title": "t" + tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
             "speakers": [], "updatedAt": updated, "segments": segments, "original": original}
        d.update(kw)
        self._write(tid + ".json", d)
        if alt is not None:
            self._write(tid + ".alt.json", {"schema": _alt.ALT_SCHEMA, "id": tid, "engine": engine, "model": model, "rows": alt})

    def feedback(self, acc, rej):
        self._write("learn-feedback.json", {"stat": {}, "dismissed": {}, "alt": {"acc": acc, "rej": rej}}, under=self.tx)

    def _write(self, name, d, under=None):
        testkit.write_json(os.path.join(under or self.tdir, name), d)

    def answers(self, rows):
        """確かめるの答え(app/check/answers.jsonl)"""
        testkit.write_text(os.path.join(self.root, "app", "check", "answers.jsonl"), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

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
        E.C.prepare()

    def judge(self, segments, **kw):
        return E.judge_doc({"updatedAt": 1, "original": ORIG, "segments": segments}, {"rows": ALT}, **kw)

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

    def test_one_place_cases(self):
        cat, cat_dog = [row(0, 3, "私は猫が好き")], [row(0, 3, "私は犬が好き")]
        two, two_dog = [row(0, 3, "私は猫が"), row(3, 6, "好きです")], [row(0, 3, "私は犬が"), row(3, 6, "好きです")]
        ins = [row(0, 3, "私は猫だが好き")]   # 「が」の前に「だ」を足す候補
        for case, orig, alt, segs, want in [
            # 比べるときの文字の寄せ方は alt_fold: 人が right を全角・カタカナで書いても、伸ばしや記号を足しても当たり
            ("寄せ方", [row(0, 3, "私はカレーが好き")], [row(0, 3, "私はカレパンが好き")], [seg(1, 0, 3, "私はかれぱんが、好き!")], ["hit"]),
            # 候補が隣の 1 文字を足した置き換えの形で、人がその文字を足したら当たり・足さなければ外れ
            ("隣に足す・足した", cat, ins, [seg(1, 0, 3, "私は猫だが好き")], ["hit"]),
            ("隣に足す・足さない", cat, ins, [seg(1, 0, 3, "私は猫が好き")], ["miss"]),
            # 人が行をつないだ・分けた(時刻の重なりのまとまり)でも、まとまりの文字で当たりが分かる
            ("つないだ", two, two_dog, [seg(1, 0, 6, "私は犬が好きです")], ["hit"]),
            ("分けた", two, two_dog, [seg(1, 0, 2, "私は犬"), seg(2, 2, 6, "が好きです")], ["hit"]),
            ("その所の文字を消した = 別の直し", cat, cat_dog, [seg(1, 0, 3, "私はが好き")], ["other"]),
            ("2 つ目のエンジンの行が無い", ORIG, [], human_a(), []),
        ]:
            with self.subTest(case):
                r = E.judge_doc({"updatedAt": 1, "original": orig, "segments": segs}, {"rows": alt})
                self.assertEqual([c["status"] for c in r["cands"]], want)

    def test_time_range_by_group(self):
        """時期はまとまりの時刻(人の行の proofedAt の最大。無ければ文書の updatedAt)で絞る。範囲の外の候補は数えない"""
        r = self.judge(human_a(), since_ms=ms("2026-10-06"))
        # 校正済みの 1・2・3 行目と、校正済みでない・消した行(文書の updatedAt = 1 = 古い)は範囲の外
        self.assertEqual(r["cands"], [])
        self.assertFalse(r["inRange"])
        self.assertEqual(r["outOfRange"], 5)
        r = self.judge(human_a(), since_ms=ms("2026-10-05", "00:00:00"), until_ms=ms("2026-10-06"))
        self.assertEqual(len(r["cands"]), 3)   # 校正済みのまとまり 3 つだけ(updatedAt = 1 の行は外)

    def test_answers_decide_and_are_not_double_counted(self):
        """確かめるの答え(2 = 採った = 当たり・1 = 却下 = 外れ・打った = 別の直し)が正。同じ候補は置き換え、合わなければ足す"""
        def ans(i, seg_id, status, wrong, right, at=T1):
            return {"id": "a%d" % i, "seg": seg_id, "status": status, "wrong": wrong, "right": right, "at": at}
        answers = [ans(1, "s5", "hit", "花", "鳥"),            # 校正済みでない(分からない)まとまり → 答えで当たり
                   ans(2, "s2", "other", "晴れ", "雨"),         # 校正済みで外れの候補 → 答えが正(別の直し)
                   ans(3, "s1", "miss", "好き", "嫌い"),       # 出し直した候補に無い → 1 件足す
                   ans(4, "s6", "hit", None, None),            # 採否の記録が無い答え → 突き合わせられないので足す
                   ans(5, "s3", "hit", "蕎麦", "饂飩", at=ms("2026-09-01"))]   # 時期の外(答えの時刻)
        r = self.judge(human_a(), since_ms=ms("2026-10-01"), answers=answers)
        by = {(c["wrong"], c["right"]): c for c in r["cands"]}
        self.assertEqual((by[("花", "鳥")]["status"], by[("花", "鳥")]["check"]), ("hit", "matched"))
        self.assertEqual((by[("晴れ", "雨")]["status"], by[("晴れ", "雨")]["check"]), ("other", "matched"))
        self.assertEqual((by[("好き", "嫌い")]["status"], by[("好き", "嫌い")]["check"]), ("miss", "added"))
        self.assertEqual((by[("", "")]["status"], by[("", "")]["check"]), ("hit", "added"))
        self.assertNotIn(("蕎麦", "饂飩"), by)   # 答えの時刻が範囲の外 = 候補ごと数えない(二重に数えない)
        self.assertIsNone(by[("猫", "犬")]["check"])
        self.assertEqual(len(r["cands"]), 5)    # 出し直した 5 - 範囲の外 2(答えの時刻・消した行のまとまりの文書の時刻)+ 足した 2
        self.assertEqual(r["outOfRange"], 2)
        a = E.Agg()
        a.add(r)
        ck = a.result()["check"]
        self.assertEqual((ck["answers"], ck["hit"], ck["miss"], ck["other"], ck["matched"], ck["added"]), (4, 2, 1, 1, 2, 2))

    def test_nosub_row_candidates_are_not_judged(self):
        """字幕に出さない行(noSub)とその時間の機械の行は、候補の当たり率にも拾えた率にも入れない(件数だけ別に出す)"""
        base = self.judge(human_a())
        self.assertEqual((base["noSub"], len(base["cands"])), ({"rows": 0, "candidates": 0}, 5))
        segs = human_a()
        segs[0] = dict(segs[0], noSub=True)            # 1 行目(猫 → 犬の候補。当たりのはずの行)を字幕に出さない行にする
        r = self.judge(segs)
        self.assertEqual({(c["wrong"], c["right"]) for c in r["cands"]}, {("晴れ", "雨"), ("蕎麦", "饂飩"), ("星", "月"), ("花", "鳥")})
        self.assertEqual(r["noSub"], {"rows": 1, "candidates": 1})
        self.assertEqual(len(r["fixes"]), len(base["fixes"]) - 1)   # 人の直しの数(拾えた率の分母)にも入らない: 猫 → 犬 の直しが減る


class TestEvaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        E.C.prepare()

    def setUp(self):
        self.env = Env(self)

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
        self.assertTrue(res["meta"]["few"] and res["meta"]["fewNote"])     # 判定できた候補が 100 件未満
        self.assertIsNone(res["feedback"])
        quiet(E.print_report, res)

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
        testkit.write_text(os.path.join(self.env.tdir, "bbbbbbbbbbb2.json"), "{")
        testkit.write_text(os.path.join(self.env.tdir, "bbbbbbbbbbb2.alt.json"), "{}")
        res = self.env.run()
        self.assertEqual((res["meta"]["docs"], res["meta"]["skipped"]["noOriginal"], res["meta"]["skipped"]["broken"]), (0, 1, 1))
        quiet(E.print_report, res)   # 対象が無くても表示で落ちない

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
        saved = testkit.read_json(os.path.join(d, names[0]))
        self.assertEqual((saved["meta"]["schema"], saved["total"]["judged"]), ("youtube-tools-alt-eval/v1", 3))

    def test_check_answers_are_counted(self):
        """answers.jsonl の read:alt の答え(human/check/apply の形)を読む。戻した答え・別の出どころ・測らない文書は数えない"""
        n = [0]

        def answer(tid, row_id, choice, wrong, right, source="alt", text=None, at=T1):
            n[0] += 1
            a = {"choice": choice}
            if text:
                a["text"] = text
            fb = {"tid": tid, "action": "accept" if choice == "2" else "reject", "items": [{"seg": row_id, "wrong": wrong, "right": right, "tier": source}]}
            return {"id": "a%013d-%06x" % (at, n[0]), "at": at, "kind": "read", "source": source, "card": "read:%s:%s#%s" % (source, tid, row_id),
                    "case": {"id": "", "title": ""}, "target": {"docId": tid, "row": row_id}, "guess": None, "answer": a, "ms": 900,
                    "applied": {"docId": tid, "row": row_id, "source": source, "choice": choice, "feedback": fb}}
        self.env.doc("aaaaaaaaaaa1", human_a())
        self.env.doc("bbbbbbbbbbb2", human_a(), evalSet=True)
        undone = answer("aaaaaaaaaaa1", "s2", "2", "晴れ", "雨")
        rows = [answer("aaaaaaaaaaa1", "s5", "2", "花", "鳥"),                     # 校正済みでない → 当たり
                undone, {"id": "a%013d-ffffff" % (T1 + 1), "at": T1 + 1, "undo": undone["id"], "reverted": {}},
                answer("aaaaaaaaaaa1", "s3", "other", "蕎麦", "饂飩", text="昼はパンを食べる"),   # 校正済みで別の直し → 答えでも別の直し(1 件のまま)
                answer("aaaaaaaaaaa1", "s1", "1", "猫", "犬", source="yt"),         # 消した yt の答え(alt では数えない)
                answer("bbbbbbbbbbb2", "s1", "2", "猫", "犬")]                      # 測らない文書(評価用)
        self.env.answers(rows)
        before = self.env.snapshot()
        res = self.env.run()
        self.assertEqual(self.env.snapshot(), before)
        t = res["total"]
        self.assertEqual((t["candidates"], t["judged"], t["hit"], t["miss"], t["other"], t["unknown"]), (5, 4, 2, 1, 1, 1))
        ck = t["check"]
        self.assertEqual((ck["answers"], ck["hit"], ck["other"], ck["matched"], ck["added"], ck["notMeasured"]), (2, 1, 1, 2, 0, 1))

    def test_evaluate_reports_nosub_separately(self):
        segs = human_a()
        segs[0] = dict(segs[0], noSub=True)
        self.env.doc("aaaaaaaaaaa1", segs)
        self.env.doc("bbbbbbbbbbb2", human_a())
        t = quiet(self.env.run)["total"]
        self.assertEqual(t["noSub"], {"docs": 1, "rows": 1, "candidates": 1})
        self.assertEqual(t["candidates"], 9)           # 4 + 5(noSub の行の候補 1 件は数えない)


if __name__ == "__main__":
    unittest.main()
