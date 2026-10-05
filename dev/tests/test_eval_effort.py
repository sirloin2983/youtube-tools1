"""dev/eval_effort.py(校正の手間を見る道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_effort.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバー・ネットワーク・ffmpeg は使わない
(CER の 1 件だけ、eval_asr.load_serve("fake") で採点の関数を読む)。
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
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import eval_effort as E  # noqa: E402


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def seg(i, a, b, text="あ", proofed=True, speaker="S1"):
    return {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": speaker, "proofed": proofed, "flag": ""}


def orig(a, b, text="あ"):
    return {"start": a, "end": b, "text": text}


class Env:
    """一時の作業データ(<root>/transcribe/transcripts/)に文書を作る"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.tdir = os.path.join(self.root, "transcribe", "transcripts")
        os.makedirs(self.tdir)

    def close(self):
        self._tmp.cleanup()

    def doc(self, tid, segments, original=None, active=600, cut=0, sessions=1, last_at=None, duration=60.0, eval_set=False, reviewed=None,
            run=None, clip=None, alt=False, diar_rows=None, effort="auto", updated=None, title="t", **extra):
        d = {"schema": "transcribe/v1", "id": tid, "title": title, "start": 0.0, "end": duration, "duration": duration,
             "segments": segments, "updatedAt": updated or ms("2026-10-01")}
        if original is not None:
            d["original"] = original
        if effort == "auto":
            d["effort"] = {"activeSec": active, "cutSec": cut, "sessions": sessions, "proofedRows": 0, "unproofedRows": 0, "lastAt": last_at or ms("2026-10-02")}
        elif effort is not None:
            d["effort"] = effort
        if eval_set:
            d["evalSet"] = True
        if reviewed:
            d["evalReviewed"] = reviewed
        d["recognition"] = {"runs": [run or {"engine": "whisper.cpp", "model": "large-v3", "engineVersion": "1"}]}
        if clip:
            d["clip"] = clip
        d.update(extra)
        self._write(tid + ".json", d)
        if alt:
            self._write(tid + ".alt.json", {"schema": "youtube-tools-alt/v1"})
        if diar_rows is not None:
            self._write(tid + ".diar.json", {"schema": "youtube-tools-diar/v1", "latest": {"rows": diar_rows}, "history": []})

    def _write(self, name, d):
        with open(os.path.join(self.tdir, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def run(self, **kw):
        kw.setdefault("cer", False)
        return E.evaluate(self.root, **kw)


def done_doc(env, tid, active, duration=60.0, **kw):
    """全行が校正済みの普段の文書(終わった)"""
    env.doc(tid, [seg(1, 0, 2), seg(2, 3, 5)], original=[orig(0, 2), orig(3, 5)], active=active, duration=duration, **kw)


class TestLength(unittest.TestCase):
    def test_doc_length_rules(self):
        s = [{"start": 1, "end": 9, "text": "あ"}]
        self.assertEqual(E.doc_length({"start": 10, "end": 70, "duration": 500, "segments": s}), 60)    # 範囲の終わり − 始まり
        self.assertEqual(E.doc_length({"start": 10, "duration": 100, "segments": s}), 90)              # 動画の長さ − 始まり
        self.assertEqual(E.doc_length({"segments": s}), 9)                                              # 最後の行の終わり
        self.assertEqual(E.doc_length({"start": 5, "segments": s}), 4)
        self.assertEqual(E.doc_length({"start": 0, "end": 0, "duration": 0, "segments": []}), 0)
        self.assertEqual(E.doc_length({"end": True, "duration": "x", "segments": s}), 9)               # 真偽値・文字は数として扱わない

    def test_matches_editor_doc_length(self):
        sys.path.insert(0, os.path.join(REPO, "editor"))
        try:
            import ed_state  # noqa: F401
            import ed_store
        except Exception:
            self.skipTest("editor の部品を読み込めない")
        for d in ({"start": 10, "end": 70, "duration": 500, "segments": []}, {"start": 10, "duration": 100, "segments": []},
                  {"start": 3, "segments": [{"end": 9}]}, {"segments": [{"end": 4.5}, {"end": 2}]}, {"end": 0, "duration": 0, "segments": []}):
            self.assertAlmostEqual(E.doc_length(d), ed_store.doc_length(d))


class TestRatioAndFinished(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_ratio_is_active_over_duration(self):
        done_doc(self.env, "aaaaaaaaaaaa", active=300, duration=60.0, cut=120, sessions=3)
        res = self.env.run()
        r = res["byDoc"][0]
        self.assertEqual(r["ratio"], 5.0)                 # 300 秒 ÷ 60 秒
        self.assertEqual((r["cutSec"], r["sessions"]), (120, 3))
        self.assertEqual(res["finished"]["ratio"]["median"], 5.0)
        self.assertEqual(res["finished"]["totalRatio"], 5.0)
        self.assertEqual(res["finished"]["cut"], 120)

    def test_finished_vs_unfinished_split(self):
        done_doc(self.env, "aaaaaaaaaaaa", active=120)                                   # 普段: 全行校正済み = 終わった(2 倍)
        done_doc(self.env, "bbbbbbbbbbbb", active=360)                                   # 終わった(6 倍)
        self.env.doc("cccccccccccc", [seg(1, 0, 2), seg(2, 3, 5, proofed=False)], original=[orig(0, 2), orig(3, 5)], active=30)   # 途中
        self.env.doc("dddddddddddd", [seg(1, 0, 2)], original=[orig(0, 2)], active=300, eval_set=True)                              # 評価用で確かめ済みの印なし = 途中
        self.env.doc("eeeeeeeeeeee", [seg(1, 0, 2, proofed=False)], original=[orig(0, 2)], active=240, eval_set=True,
                     reviewed={"at": 1, "rows": 1, "durationSec": 60.0, "via": "drill"})                                              # 評価用の確かめ済み = 終わった(4 倍)
        self.env.doc("ffffffffffff", [seg(1, 0, 2)], original=[orig(0, 2)], active=120, evalReviewed={"at": 1, "rows": 1})           # 評価用でない文書の印は見ない(全行校正済み = 終わった)
        res = self.env.run()
        self.assertEqual((res["meta"]["finishedDocs"], res["meta"]["unfinishedDocs"]), (4, 2))
        self.assertEqual(sorted(r["ratio"] for r in res["byDoc"] if r["finished"]), [2.0, 2.0, 4.0, 6.0])
        self.assertEqual(res["finished"]["ratio"]["median"], 3.0)
        self.assertEqual(res["unfinished"]["n"], 2)
        self.assertEqual(res["unfinished"]["activeSec"], 330)
        self.assertNotIn(0.5, [r["ratio"] for r in res["byDoc"] if r["finished"]])   # 途中の倍率(0.5)は終わったほうに入らない

    def test_no_text_rows_is_unfinished(self):
        self.env.doc("aaaaaaaaaaaa", [seg(1, 0, 2, text="  ")], original=[orig(0, 2)], active=60)
        res = self.env.run()
        self.assertEqual(res["meta"]["finishedDocs"], 0)
        self.assertEqual(res["meta"]["unfinishedDocs"], 1)

    def test_skips_without_crashing(self):
        done_doc(self.env, "aaaaaaaaaaaa", active=60)
        self.env.doc("bbbbbbbbbbbb", [seg(1, 0, 2)], original=[orig(0, 2)], effort=None)                    # effort なし
        self.env.doc("cccccccccccc", [seg(1, 0, 2)], original=[orig(0, 2)], effort="壊れている")             # effort が文字
        self.env.doc("eeeeeeeeeeee", [seg(1, 0, 2)], original=[orig(0, 2)], active=0, cut=300)             # 校正の時間 0
        self.env.doc("ffffffffffff", [], original=[], active=60, duration=0.0)                              # 長さが分からない
        self.env.doc("111111111111", [seg(1, 0, 2)], original=[orig(0, 2)], effort={"activeSec": "x", "cutSec": True, "lastAt": None})   # 数でない値は 0
        with open(os.path.join(self.env.tdir, "222222222222.json"), "w") as f:
            f.write("{壊れた")
        res = self.env.run()
        self.assertEqual(res["meta"]["docs"], 1)
        self.assertEqual(res["meta"]["skipped"], {"broken": 1, "noEffort": 2, "noDuration": 1, "noTime": 2, "evalSet": 0, "outOfRange": 0})

    def test_no_data_dir_and_empty(self):
        with tempfile.TemporaryDirectory() as d:
            res = E.evaluate(d, cer=False)
        self.assertEqual(res["meta"]["docs"], 0)
        self.assertTrue(res["meta"]["few"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(res)
        self.assertIn("測れる文書がありません", buf.getvalue())

    def test_no_eval_excludes_eval_docs(self):
        done_doc(self.env, "aaaaaaaaaaaa", active=60)
        self.env.doc("bbbbbbbbbbbb", [seg(1, 0, 2)], original=[orig(0, 2)], active=60, eval_set=True)
        res = self.env.run(include_eval=False)
        self.assertEqual(res["meta"]["docs"], 1)
        self.assertEqual(res["meta"]["skipped"]["evalSet"], 1)


class TestFewAndTime(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_few_note_until_ten_finished(self):
        for i in range(9):
            done_doc(self.env, "%012x" % (0xa0 + i), active=120)
        res = self.env.run()
        self.assertTrue(res["meta"]["few"])
        self.assertIn("まだ少ない(参考)", res["meta"]["fewNote"])
        done_doc(self.env, "%012x" % 0xb0, active=120)
        res = self.env.run()
        self.assertFalse(res["meta"]["few"])
        self.assertEqual(res["meta"]["fewNote"], "")

    def test_since_until_by_last_at_then_updated_at(self):
        done_doc(self.env, "aaaaaaaaaaaa", active=60, last_at=ms("2026-09-30", "23:59:59"))
        done_doc(self.env, "bbbbbbbbbbbb", active=60, last_at=ms("2026-10-01", "00:00:00"))
        done_doc(self.env, "cccccccccccc", active=60, last_at=ms("2026-10-03", "23:59:59"))
        done_doc(self.env, "dddddddddddd", active=60, last_at=ms("2026-10-04", "00:00:00"))
        # lastAt が無い effort は updatedAt を使う
        self.env.doc("eeeeeeeeeeee", [seg(1, 0, 2)], original=[orig(0, 2)], effort={"activeSec": 60, "cutSec": 0, "sessions": 1}, updated=ms("2026-10-02"))
        res = self.env.run(since="2026-10-01", until="2026-10-03")
        self.assertEqual(sorted(r["id"] for r in res["byDoc"]), ["bbbbbbbbbbbb", "cccccccccccc", "eeeeeeeeeeee"])
        self.assertEqual(res["meta"]["skipped"]["outOfRange"], 2)
        self.assertEqual(self.env.run(since="2026-10-04")["meta"]["docs"], 1)
        with self.assertRaises(SystemExit):
            self.env.run(since="10/01")

    def test_week_label(self):
        self.assertEqual(E.week_of(ms("2026-10-04")), "2026-W40")
        self.assertEqual(E.week_of(None), "不明")


class TestEditCounts(unittest.TestCase):
    def doc(self, segs, orig_, **kw):
        return dict({"segments": segs, "original": orig_}, **kw)

    def test_text_added_deleted_time_speaker(self):
        orig_ = [orig(0, 2, "おはよう"), orig(3, 5, "こんにちは"), orig(6, 8, "ゴミ"), orig(9, 11, "そのまま"), orig(12, 14, "時刻")]
        segs = [seg(1, 0, 2, "おはよ"),                       # 文字を直した
                seg(2, 3, 5, "こんにちは"),                    # 同じ(空白だけ違うのは直しにしない: 下で " " を足す)
                seg(4, 9, 11, "そ の ま ま"),                  # 空白だけ = 直しではない
                seg(5, 12.2, 14, "時刻"),                      # 時刻を直した(始まりが 0.2 秒ずれ)
                seg(6, 20, 22, "足した行")]                    # 人が足した
        diar = {"s1": {"speaker": "S1"}, "s2": {"speaker": "S2"}, "s4": {"speaker": "S1"}, "s5": {"speaker": "S1"}}
        segs[1]["speaker"] = "S1"                              # diar は S2 → 話者を直した
        c = E.edit_counts(self.doc(segs, orig_), diar)
        self.assertEqual((c["text"], c["added"], c["deleted"], c["time"], c["speaker"]), (1, 1, 1, 1, 1))
        self.assertEqual(c["textRows"], 5)
        self.assertEqual(c["edited"], 4)                      # 文字 s1・話者 s2・時刻 s5・足した s6(s4 は直していない)
        self.assertEqual(c["frac"], round((4 + 1) / (5 + 1), 4))

    def test_split_merge_with_same_text_is_not_text_edit_but_time_edit(self):
        # 機械 1 行 → 人が 2 行に分けた(文字は同じ): 文字は直していない・時刻は直した(端が合わない)
        c = E.edit_counts({"segments": [seg(1, 0, 1, "おは"), seg(2, 1, 2, "よう")], "original": [orig(0, 2, "おはよう")]}, None)
        self.assertEqual((c["text"], c["added"], c["deleted"]), (0, 0, 0))
        self.assertEqual(c["time"], 2)
        self.assertIsNone(c["speaker"])                       # diar が無い = 分からない
        # 機械 2 行 → 人が 1 行に(文字は同じ・端は全体と合わない)
        c = E.edit_counts({"segments": [seg(1, 0, 2, "おはよう")], "original": [orig(0, 1, "おは"), orig(1, 2, "よう")]}, None)
        self.assertEqual((c["text"], c["added"], c["deleted"], c["time"]), (0, 0, 0, 1))

    def test_time_tolerance_is_005(self):
        c = E.edit_counts({"segments": [seg(1, 0.04, 2.05, "あ"), seg(2, 3.0, 5.2, "い")], "original": [orig(0, 2, "あ"), orig(3, 5, "い")]}, None)
        self.assertEqual(c["time"], 1)                        # 1 行目は 0.05 秒以内(同じ)・2 行目は終わりが 0.2 秒ずれ

    def test_no_original_is_unknown(self):
        self.assertIsNone(E.edit_counts({"segments": [seg(1, 0, 2)]}, None))
        self.assertIsNone(E.edit_counts({"segments": [seg(1, 0, 2)], "original": []}, None))
        self.assertIsNone(E.edit_counts({"segments": [seg(1, 0, 2)], "original": [{"start": 0, "end": 1, "text": " "}]}, None))

    def test_speaker_unrecorded_row_is_not_counted(self):
        # 判別のあとに足した行(記録が無い)は話者を直した行に数えない
        c = E.edit_counts({"segments": [seg(1, 0, 2, speaker="S2"), seg(2, 3, 5, speaker="S1")], "original": [orig(0, 2), orig(3, 5)]}, {"s1": {"speaker": "S1"}})
        self.assertEqual(c["speaker"], 1)

    def test_per_doc_in_summary(self):
        env = Env()
        self.addCleanup(env.close)
        env.doc("aaaaaaaaaaaa", [seg(1, 0, 2, "おはよ"), seg(2, 3, 5, "あ")], original=[orig(0, 2, "おはよう"), orig(3, 5, "あ")], active=600, duration=120.0,
                diar_rows={"s1": {"speaker": "S1"}, "s2": {"speaker": "S1"}})
        env.doc("bbbbbbbbbbbb", [seg(1, 0, 2)], active=300, duration=60.0)                    # original なし
        res = env.run()
        e = res["edits"]
        self.assertEqual((e["docs"], e["unknown"]), (1, 1))
        self.assertEqual(e["totals"]["text"], 1)
        self.assertEqual(e["perMin"]["text"], 0.5)           # 1 行 ÷ 2 分
        self.assertEqual(e["totals"]["speaker"], 0)
        self.assertEqual(e["speakerKnownDocs"], 1)
        self.assertEqual(e["perMin"]["speaker"], 0.0)
        self.assertTrue(any("original" in n for n in res["meta"]["notes"]))


class TestGroups(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_group_tables(self):
        fw = {"engine": "faster-whisper", "model": "large-v3", "engineVersion": "1"}
        raw = {"source": {"videoId": "abc"}}
        done_doc(self.env, "aaaaaaaaaaaa", active=60, run=fw)                                              # 1 倍
        done_doc(self.env, "bbbbbbbbbbbb", active=180, run=fw, clip={"source": {"kind": "stream"}})        # 3 倍・編集前
        done_doc(self.env, "cccccccccccc", active=600, alt=True, clip=raw)                                 # 10 倍・whisper.cpp・alt あり・編集前
        self.env.doc("dddddddddddd", [seg(1, 0, 2, proofed=False)], original=[orig(0, 2)], active=30, run=fw)   # 途中
        self.env.doc("eeeeeeeeeeee", [seg(1, 0, 2, proofed=False)], original=[orig(0, 2)], active=60, eval_set=True,
                     reviewed={"at": 1, "rows": 1, "durationSec": 60.0, "via": "editor"}, run={"engine": "llama.cpp", "model": "q"})
        self.env.doc("ffffffffffff", [seg(1, 0, 2)], original=[orig(0, 2)], active=60, run={"at": 1})      # 最初の認識の記録なし(エンジン・モデルの無い記録)
        res = self.env.run()
        g = {t["key"]: t for t in res["groups"]["engine"]}
        self.assertEqual((g["faster-whisper large-v3"]["finished"], g["faster-whisper large-v3"]["median"], g["faster-whisper large-v3"]["unfinished"]), (2, 2.0, 1))
        self.assertEqual((g["whisper.cpp large-v3"]["finished"], g["whisper.cpp large-v3"]["median"]), (1, 10.0))
        self.assertEqual(g["不明(記録なし)"]["finished"], 1)
        o = {t["key"]: t for t in res["groups"]["origin"]}
        self.assertEqual(o["編集前"]["finished"], 2)
        self.assertEqual(o["ショート"]["finished"], 3)
        a = {t["key"]: t for t in res["groups"]["alt"]}
        self.assertEqual((a["あり"]["finished"], a["あり"]["median"]), (1, 10.0))
        v = {t["key"]: t for t in res["groups"]["via"]}
        self.assertEqual(v["editor"]["finished"], 1)
        self.assertEqual(v["(確かめ済みの印なし)"]["finished"], 4)
        el = {t["key"]: t for t in res["groups"]["eval"]}
        self.assertEqual((el["評価用"]["finished"], el["普段"]["finished"]), (1, 4))
        self.assertIn("faster-whisper large-v3", [t["key"] for t in res["groups"]["engine"]])

    def test_week_group_sorted_oldest_first(self):
        done_doc(self.env, "aaaaaaaaaaaa", active=60, last_at=ms("2026-10-04"))   # 2026-W40
        done_doc(self.env, "bbbbbbbbbbbb", active=120, last_at=ms("2026-09-22"))  # 2026-W39
        res = self.env.run()
        self.assertEqual([t["key"] for t in res["groups"]["week"]], ["2026-W39", "2026-W40"])

    def test_buckets_by_edited_fraction(self):
        def mk(tid, changed, active):
            # 4 行のうち changed 行の文字を直す
            segs = [seg(i, i * 3, i * 3 + 2, "直した" if i < changed else "そのまま") for i in range(4)]
            orig_ = [orig(i * 3, i * 3 + 2, "そのまま") for i in range(4)]
            self.env.doc(tid, segs, original=orig_, active=active, duration=60.0)
        mk("aaaaaaaaaaaa", 0, 60)      # 0%   → 〜25%・1 倍
        mk("bbbbbbbbbbbb", 1, 120)     # 25%  → 25〜50%・2 倍
        mk("cccccccccccc", 2, 180)     # 50%  → 50〜75%・3 倍
        mk("dddddddddddd", 3, 240)     # 75%  → 75%〜・4 倍
        mk("eeeeeeeeeeee", 4, 360)     # 100% → 75%〜・6 倍
        self.env.doc("ffffffffffff", [seg(1, 0, 2)], active=999)    # original なし = 区切りに入れない
        res = self.env.run()
        b = {x["bucket"]: x for x in res["buckets"]}
        self.assertEqual([x["bucket"] for x in res["buckets"]], ["〜25%", "25〜50%", "50〜75%", "75%〜"])
        self.assertEqual((b["〜25%"]["docs"], b["〜25%"]["median"]), (1, 1.0))
        self.assertEqual((b["25〜50%"]["docs"], b["25〜50%"]["median"]), (1, 2.0))
        self.assertEqual((b["50〜75%"]["docs"], b["50〜75%"]["median"]), (1, 3.0))
        self.assertEqual((b["75%〜"]["docs"], b["75%〜"]["median"]), (2, 5.0))
        self.assertEqual(b["75%〜"]["perMin"], round((3 + 4) / 2.0, 2))      # 2 文書・計 2 分・直した行 3 + 4


class TestCer(unittest.TestCase):
    def test_cer_of_finished_doc(self):
        env = Env()
        self.addCleanup(env.close)
        env.doc("aaaaaaaaaaaa", [seg(1, 0, 2, "あいうえか"), seg(2, 3, 5, "かきくけこ")], original=[orig(0, 2, "あいうえお"), orig(3, 5, "かきくけこ")], active=120)
        res = E.evaluate(env.root, cer=True)
        c = res["byDoc"][0]["cer"]
        self.assertEqual((c["errs"], c["refChars"], c["cer"]), (1, 10, 0.1))
        self.assertEqual(res["cer"]["cer"], 0.1)
        self.assertEqual(res["cer"]["docs"], 1)

    def test_no_cer_flag(self):
        env = Env()
        self.addCleanup(env.close)
        done_doc(env, "aaaaaaaaaaaa", active=60)
        res = env.run(cer=False)
        self.assertIsNone(res["byDoc"][0]["cer"])
        self.assertEqual(res["cer"]["docs"], 0)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)
        done_doc(self.env, "aaaaaaaaaaaa", active=120)

    def _files(self):
        out = []
        for base, _dirs, files in os.walk(self.env.root):
            out += [os.path.join(base, f) for f in files]
        return sorted(out)

    def test_read_only_without_json(self):
        before = {p: os.path.getmtime(p) for p in self._files()}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.main(["--data-dir", self.env.root, "--no-cer"])
        self.assertEqual(before, {p: os.path.getmtime(p) for p in self._files()})
        out = buf.getvalue()
        self.assertIn("校正の手間の測定", out)
        self.assertIn("まだ少ない(参考)", out)
        self.assertIn("×2.0", out)

    def test_json_saved_under_evals_effort(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = E.main(["--data-dir", self.env.root, "--no-cer", "--json"])
        d = os.path.join(self.env.root, "transcribe", "evals", "effort")
        files = os.listdir(d)
        self.assertEqual(len(files), 1)
        with open(os.path.join(d, files[0]), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["meta"]["schema"], "youtube-tools-effort-eval/v1")
        self.assertEqual(saved["finished"]["n"], res["finished"]["n"])


class TestNoSubEdits(unittest.TestCase):
    """字幕に出さない行(noSub)は、機械の話者判別の外れには数えない。人が印を付けた行として「直した行」には入れる"""

    def test_nosub_row_is_not_a_speaker_error_but_is_an_edit(self):
        orig_ = [orig(0, 2, "おはよう"), orig(3, 5, "ゲームの声")]
        diar = {"s1": {"speaker": "S1"}, "s2": {"speaker": "S2"}}
        plain = E.edit_counts({"segments": [seg(1, 0, 2, "おはよう"), seg(2, 3, 5, "ゲームの声", speaker="S3")], "original": orig_}, diar)
        self.assertEqual((plain["speaker"], plain["edited"]), (1, 1))                      # noSub でなければ、話者を変えた = 直した
        self.assertNotIn("noSub", plain)
        ns = E.edit_counts({"segments": [seg(1, 0, 2, "おはよう"), dict(seg(2, 3, 5, "ゲームの声", speaker="S3"), noSub=True)], "original": orig_}, diar)
        self.assertEqual((ns["speaker"], ns["noSub"]), (0, 1))
        self.assertEqual(ns["edited"], 1)                                                  # 印を付けたことは直した行に数える
        self.assertEqual((ns["text"], ns["added"], ns["deleted"], ns["time"]), (0, 0, 0, 0))

    def test_summary_has_nosub_total_only_when_present(self):
        env = Env()
        self.addCleanup(env.close)
        done_doc(env, "aaaaaaaaaaa1", 600)
        res = env.run()
        self.assertNotIn("noSub", res["edits"]["totals"])
        env.doc("bbbbbbbbbbb2", [seg(1, 0, 2), dict(seg(2, 3, 5, speaker="S3"), noSub=True)], original=[orig(0, 2), orig(3, 5)], active=600,
                diar_rows={"s1": {"speaker": "S1"}, "s2": {"speaker": "S2"}})
        res = env.run()
        self.assertEqual(res["edits"]["totals"]["noSub"], 1)
        self.assertEqual(res["edits"]["totals"]["speaker"], 0)


if __name__ == "__main__":
    unittest.main()
