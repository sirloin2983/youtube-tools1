"""dev/eval_speakers.py(話者の判別・声の照合を、人が直した最終で測る道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_speakers.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバーは動かさない。
"""
import contextlib
import io
import itertools
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import wave
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
REPO = os.path.join(os.path.dirname(HERE), "src")   # ツールと ytt_core の置き場所
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import eval_speakers as E  # noqa: E402


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


class Env:
    """一時の作業データ(<root>/transcribe/transcripts/)に、文書と判別の記録を作る"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.tdir = os.path.join(self.root, "transcribe", "transcripts")
        os.makedirs(self.tdir)

    def close(self):
        self._tmp.cleanup()

    def doc(self, tid, speakers, rows, diar=None, history=None, original=None, eval_set=False, updated=None, title="t", proofed=False, reviewed=False, source=None):
        """speakers: {id: 名前}。rows: [(行 id, 人の話者 id or "", 機械のラベル or None, 追加の項目(mixed・weak・proofed・proofedAt・start・end・tags))]。
        diar=None なら判別の記録を作らない。機械のラベル None = 機械が付けなかった行。diar は {"voices": {...}, "engine": {...}, "overlaps": [...]} など。
        proofed = 行の proofed の既定(行の項目が優先)。reviewed = 評価用の確かめ済み(evalSet と evalReviewed)"""
        segs, drows = [], {}
        for i, (rid, hsp, label, kw) in enumerate(rows):
            kw = dict(kw)
            seg = {"id": rid, "start": kw.pop("start", i * 2.0), "end": kw.pop("end", i * 2.0 + 1.5), "text": "あ", "speaker": hsp, "flag": ""}
            drows[rid] = {"label": 0 if label else None, "speaker": label or "", "ratio": 1.0, "mixed": bool(kw.pop("mixed", False)), "weak": bool(kw.pop("weak", False))}
            if proofed:
                seg["proofed"] = True
            for k in ("proofed", "proofedAt", "tags", "noSub"):
                if k in kw:
                    seg[k] = kw.pop(k)
            segs.append(seg)
        d = {"schema": "youtube-tools-transcript/v1", "id": tid, "title": title, "segments": segs, "updatedAt": updated or ms("2026-10-01"),
             "speakers": [{"id": k, "name": v, "color": "#000"} for k, v in speakers.items()]}
        if original is not None:
            d["original"] = original
        if eval_set or reviewed:
            d["evalSet"] = True
        if reviewed:
            d["evalReviewed"] = {"at": 1, "rows": len(segs), "durationSec": 30.0, "via": "drill"}
        if source:
            d.update({"sourcePath": source, "start": 0.0, "end": None})
        self._write(tid + ".json", d)
        if diar is not None:
            latest = {"at": 1, "engine": diar.get("engine") or {"name": "sherpa-onnx", "embedding": "voxceleb", "clusterThreshold": 0.5, "requested": "auto"},
                      "rows": diar.get("rows") or drows, "speakers": diar.get("speakers", len({r["speaker"] for r in drows.values() if r["speaker"]})),
                      "voices": diar.get("voices") or {"checked": False}, "overlaps": diar.get("overlaps") or []}
            hist = []
            for h in history or []:
                hr = {"at": 0, "engine": h.get("engine") or {"name": "sherpa-onnx", "embedding": "other", "clusterThreshold": 0.6, "requested": "auto"}, "rows": h["rows"],
                      "speakers": 2, "voices": {"checked": False}}
                hist.append(hr)
            self._write(tid + ".diar.json", {"schema": "youtube-tools-diar/v1", "latest": latest, "history": hist})

    def _write(self, name, d):
        with open(os.path.join(self.tdir, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def run(self, **kw):
        return E.evaluate(self.root, **kw)


def vinfo(top, score, second=None, second_score=None, decided=None, by=None, reason=None):
    return {"top": top, "score": score, "second": second, "secondScore": second_score, "decided": decided, "by": by, "reason": reason}


class TestMapping(unittest.TestCase):
    def test_hungarian_matches_brute_force(self):
        import random
        rnd = random.Random(7)
        for _ in range(60):
            r, c = rnd.randint(1, 5), rnd.randint(1, 5)
            w = [[rnd.randint(0, 9) for _ in range(c)] for _ in range(r)]
            got = E.hungarian_max(w)
            self.assertEqual(len(set(got.values())), len(got))
            best = 0
            for perm in itertools.permutations(range(max(r, c))):
                best = max(best, sum(w[i][perm[i]] for i in range(r) if perm[i] < c))
            self.assertEqual(sum(w[i][j] for i, j in got.items()), best)

    def test_best_mapping_swapped_labels_and_oversplit(self):
        rows = [{"label": "S1", "human": "B"}] * 4 + [{"label": "S2", "human": "A"}] * 3 + [{"label": "S3", "human": "A"}] * 1 + [{"label": "", "human": "A"}]
        m = E.best_mapping(rows)
        self.assertEqual(m, {"S1": "B", "S2": "A"})   # S3 は A に対応できない(分けすぎ)


class TestRows(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_swapped_labels_are_correct_and_counts(self):
        # 機械の S1 = 人の B、機械の S2 = 人の A(入れ替わり)。1行は取り違え・1行は機械が付けなかった・1行は重なり(mixed)で取り違え
        rows = [("r%d" % i, "S2", "S1", {}) for i in range(6)] + [("a%d" % i, "S1", "S2", {}) for i in range(4)]
        rows += [("w1", "S1", "S1", {}), ("n1", "S1", None, {}), ("m1", "S1", "S1", {"mixed": True}), ("m2", "S1", "S2", {"mixed": True}), ("k1", "S2", "S1", {"weak": True})]
        self.env.doc("aaaaaaaaaaaa", {"S1": "A", "S2": "B"}, rows, diar={}, proofed=True)
        res = self.env.run()
        a = res["subsets"]["all"]
        self.assertEqual(a["rows"], 15)
        # 正しい: r0-5(B→S1)=6・a0-3(A→S2)=4・m2(A→S2)=1・k1(B→S1)=1 → 12 / 間違い: w1・n1(未割り当て)・m1(S1=B なのに人は A)
        self.assertEqual(a["correct"], 12)
        self.assertEqual(a["unassigned"], 1)
        self.assertEqual(a["mixed"], {"rows": 2, "correct": 1, "rate": 0.5})
        self.assertEqual(a["weak"], {"rows": 1, "correct": 1, "rate": 1.0})
        self.assertEqual(a["plain"]["rows"], 12)
        self.assertEqual(a["plain"]["correct"], 10)
        self.assertEqual(a["rate"], round(12 / 15, 4))
        self.assertEqual(res["speakerCount"]["exact"], 1)

    def test_draft_names_unlabeled_and_no_record_rows_are_excluded(self):
        rows = [("r1", "S1", "S1", {}), ("r2", "S1", "S1", {}), ("d1", "S2", "S2", {}), ("u1", "", "S1", {}), ("x1", "S1", "S1", {})]
        self.env.doc("bbbbbbbbbbbb", {"S1": "A", "S2": "話者2"}, rows, diar={"rows": {k: {"label": 0, "speaker": "S1", "mixed": False, "weak": False} for k in ("r1", "r2", "d1", "u1")}},
                     proofed=True)
        res = self.env.run()
        self.assertEqual(res["subsets"]["all"]["rows"], 2)         # d1(仮の名前)・u1(話者なし)・x1(機械の記録なし)は外れる
        self.assertEqual(res["meta"]["draftRows"], 1)
        self.assertEqual(res["meta"]["noRecordRows"], 1)
        res2 = self.env.run(include_draft=True)
        self.assertEqual(res2["subsets"]["all"]["rows"], 3)

    def test_over_split_speaker_count_and_wrong_rows(self):
        rows = [("a%d" % i, "S1", "S1", {}) for i in range(5)] + [("b%d" % i, "S2", "S2", {}) for i in range(5)] + [("c%d" % i, "S2", "S3", {}) for i in range(2)]
        self.env.doc("cccccccccccc", {"S1": "A", "S2": "B"}, rows, diar={}, proofed=True)
        res = self.env.run()
        self.assertEqual(res["subsets"]["all"]["correct"], 10)
        self.assertEqual(res["speakerCount"]["diff"], {"1": 1})
        self.assertEqual(res["speakerCount"]["over"], 1)
        self.assertEqual(res["speakerCount"]["exactRate"], 0.0)

    def test_proofed_subset_and_time_edited_subset(self):
        orig = [{"start": 0.0, "end": 1.5, "text": "あ"}, {"start": 2.0, "end": 3.5, "text": "あ"}, {"start": 4.0, "end": 5.5, "text": "あ"}]
        rows = [("r0", "S1", "S1", {"proofed": True}),
                ("r1", "S1", "S2", {"proofed": True, "start": 2.0, "end": 3.9}),    # 終わりを直した(間違い)
                ("r2", "S1", "S1", {"start": 4.3, "end": 5.5})]                      # 始まりを直した
        self.env.doc("dddddddddddd", {"S1": "A", "S2": "B"}, rows, diar={}, original=orig, reviewed=True)
        res = self.env.run()
        self.assertEqual(res["subsets"]["all"]["rows"], 3)
        self.assertEqual(res["subsets"]["proofed"]["rows"], 2)
        te = res["subsets"]["timeEdited"]
        self.assertEqual(te["rows"], 2)
        self.assertEqual(te["correct"], 1)
        # original が無い文書は時刻を直したか分からないので、その行の集まりには入らない
        self.env.doc("eeeeeeeeeeee", {"S1": "A"}, [("r0", "S1", "S1", {})], diar={})
        self.assertEqual(self.env.run()["subsets"]["timeEdited"]["rows"], 2)

    def test_period_by_proofed_at_or_doc_updated_at(self):
        rows = [("r0", "S1", "S1", {"proofed": True, "proofedAt": ms("2026-09-10")}),
                ("r1", "S1", "S1", {"proofed": True, "proofedAt": ms("2026-09-20")}),
                ("r2", "S1", "S1", {})]                                            # 時刻なし → 文書の更新時刻 10-01
        self.env.doc("ffffffffffff", {"S1": "A"}, rows, diar={}, proofed=True)
        self.assertEqual(self.env.run()["subsets"]["all"]["rows"], 3)
        self.assertEqual(self.env.run(since="2026-09-15")["subsets"]["all"]["rows"], 2)
        self.assertEqual(self.env.run(since="2026-09-15", until="2026-09-20")["subsets"]["all"]["rows"], 1)   # until はその日を含む
        self.assertEqual(self.env.run(until="2026-09-10")["subsets"]["all"]["rows"], 1)
        self.assertEqual(self.env.run(since="2026-10-02")["meta"]["docs"], 0)

    def test_eval_set_included_by_default_and_excludable(self):
        self.env.doc("111111111111", {"S1": "A"}, [("r0", "S1", "S1", {})], diar={}, eval_set=True, proofed=True)
        self.env.doc("222222222222", {"S1": "A"}, [("r0", "S1", "S1", {})], diar={}, proofed=True)
        self.assertEqual(self.env.run()["meta"]["docs"], 2)
        r = self.env.run(include_eval=False)
        self.assertEqual((r["meta"]["docs"], r["meta"]["skipped"]["evalSet"]), (1, 1))

    def test_history_runs_grouped_by_engine(self):
        rows = [("r0", "S1", "S1", {}), ("r1", "S2", "S2", {}), ("r2", "S2", "S2", {})]
        old = {"r0": {"label": 0, "speaker": "S1"}, "r1": {"label": 0, "speaker": "S1"}, "r2": {"label": 1, "speaker": "S2"}}   # 前の回は r1 を取り違えた
        self.env.doc("333333333333", {"S1": "A", "S2": "B"}, rows, diar={}, history=[{"rows": old}], proofed=True)
        be = self.env.run()["byEngine"]
        self.assertEqual(len(be), 2)
        new = [v for k, v in be.items() if "voxceleb" in k][0]
        prev = [v for k, v in be.items() if "other" in k][0]
        self.assertEqual((new["rate"], prev["correct"], prev["rows"]), (1.0, 2, 3))

    def test_single_and_missing_diar_are_skipped(self):
        self.env.doc("444444444444", {"S1": "A"}, [("r0", "S1", "S1", {})], diar={"engine": {"name": "single", "requested": 1}})
        self.env.doc("555555555555", {"S1": "A"}, [("r0", "S1", "S1", {})])
        r = self.env.run()
        self.assertEqual((r["meta"]["docs"], r["meta"]["skipped"]["single"], r["meta"]["skipped"]["noDiar"]), (0, 1, 1))


class TestVoices(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def make(self):
        # 機械の S1 = 人の A(照合も A で正解・点数 0.80・差 0.30)/ S2 = 人の B(照合は C で間違い・点数 0.70・差 0.20)/
        # S3 = 人の D(しきい値に届かず付けなかったが、1位は D = 取りこぼし 0.55)/ S4 = 人の E(特徴が取れない)/ S5 = 行が無い
        rows = [("a%d" % i, "S1", "S1", {}) for i in range(4)] + [("b%d" % i, "S2", "S2", {}) for i in range(3)]
        rows += [("d%d" % i, "S3", "S3", {"proofed": True}) for i in range(2)] + [("e0", "S4", "S4", {})]
        voices = {"checked": True, "speakers": {
            "S1": vinfo("A", 0.80, "B", 0.50, decided="A", by="threshold"),
            "S2": vinfo("C", 0.70, "A", 0.50, decided="C", by="threshold"),
            "S3": vinfo("D", 0.55, "A", 0.20, reason="below_match"),
            "S4": vinfo(None, None, reason="no_feature"),
            "S5": vinfo("Z", 0.90, "Y", 0.10, decided="Z", by="elimination")}}
        self.env.doc("666666666666", {"S1": "A", "S2": "B", "S3": "D", "S4": "E"}, rows, diar={"voices": voices}, reviewed=True)

    def test_voice_correctness_reasons_and_missed(self):
        self.make()
        v = self.env.run()["subsets"]["all"]["voices"]
        self.assertEqual((v["decided"], v["correct"], v["wrong"], v["unverified"]), (2, 1, 1, 1))   # S5 は行が無く確かめられない
        self.assertEqual(v["rate"], 0.5)
        self.assertEqual(v["undecided"], {"below_match": 1, "no_feature": 1})
        self.assertEqual(v["correctScore"]["median"], 0.8)
        self.assertEqual(v["wrongScore"]["median"], 0.7)
        self.assertEqual(v["correctMargin"]["median"], 0.3)
        self.assertEqual(v["wrongMargin"]["median"], 0.2)
        self.assertEqual(v["missed"]["n"], 1)
        self.assertEqual(v["missed"]["score"]["median"], 0.55)
        self.assertEqual(v["missed"]["byReason"], {"below_match": 1})

    def test_voice_threshold_sweep(self):
        self.make()
        sw = {(x["match"], x["margin"]): x for x in self.env.run()["subsets"]["all"]["voices"]["sweep"]}
        # 点数と差が分かるのは S1(A 正解 0.80/0.30)・S2(C 間違い 0.70/0.20)・S3(D 正解 0.55/0.35)・S5 は行が無いので入らない
        self.assertEqual((sw[(0.6, 0.08)]["decided"], sw[(0.6, 0.08)]["correct"]), (2, 1))
        self.assertEqual((sw[(0.5, 0.08)]["decided"], sw[(0.5, 0.08)]["correct"]), (3, 2))   # しきい値を下げると D も決まる
        self.assertEqual((sw[(0.75, 0.0)]["decided"], sw[(0.75, 0.0)]["correct"]), (1, 1))   # 上げると間違いが消える
        self.assertEqual(sw[(0.8, 0.12)]["precision"], 1.0)

    def test_proofed_subset_voices_use_only_proofed_rows(self):
        self.make()
        v = self.env.run()["subsets"]["proofed"]["voices"]
        # 校正済みの行は S3 の2行だけ。S3 は付けなかった(1位 D が人の名前 = 取りこぼし)。S1・S2 は行が無いので確かめられない
        self.assertEqual((v["decided"], v["unverified"]), (0, 3))
        self.assertEqual(v["missed"]["n"], 1)

    def test_request_and_unchecked_voices_are_not_measured(self):
        rows = [("a0", "S1", "S1", {})]
        self.env.doc("777777777777", {"S1": "A"}, rows, diar={"voices": {"checked": True, "speakers": {"S1": vinfo(None, None, decided="A", by="request")}}}, proofed=True)
        self.env.doc("888888888888", {"S1": "A"}, rows, diar={"voices": {"checked": False}}, proofed=True)
        v = self.env.run()["subsets"]["all"]["voices"]
        self.assertEqual((v["decided"], v["unverified"], v["undecidedTotal"]), (0, 0, 0))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def snapshot(self):
        out = {}
        for dp, _, fns in os.walk(self.env.root):
            for fn in fns:
                p = os.path.join(dp, fn)
                out[p] = (os.path.getsize(p), os.path.getmtime(p))
        return out

    def test_empty_data_does_not_crash(self):
        res = self.env.run()
        self.assertEqual(res["meta"]["docs"], 0)
        self.assertTrue(res["meta"]["few"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(res)
        self.assertIn("まだ少ない(参考)", buf.getvalue())
        shutil_root = tempfile.mkdtemp()
        try:
            r = E.evaluate(os.path.join(shutil_root, "nothing"))   # transcribe フォルダも無い
            self.assertEqual(r["meta"]["docs"], 0)
        finally:
            os.rmdir(shutil_root)

    def test_report_and_json_save_and_read_only(self):
        rows = [("r%d" % i, "S1", "S1", {}) for i in range(5)]
        self.env.doc("999999999999", {"S1": "A"}, rows, diar={"voices": {"checked": True, "speakers": {"S1": vinfo("A", 0.7, "B", 0.3, decided="A", by="threshold")}}},
                     proofed=True)
        before = self.snapshot()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.main(["--data-dir", self.env.root])
        text = buf.getvalue()
        self.assertIn("話者の判別の測定", text)
        self.assertIn("行ごとの正しさ", text)
        self.assertEqual(self.snapshot(), before)     # --json なしでは何も書かない
        with contextlib.redirect_stdout(io.StringIO()):
            E.main(["--data-dir", self.env.root, "--json", "--no-eval"])
        d = os.path.join(self.env.root, "transcribe", "evals", "speakers")
        files = os.listdir(d)
        self.assertEqual(len(files), 1)
        with open(os.path.join(d, files[0]), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["meta"]["schema"], E.SCHEMA)
        self.assertEqual(saved["subsets"]["all"]["rows"], 5)
        self.assertFalse(saved["meta"]["includeEval"])
        # 元の文書・判別の記録は変わらない
        for p, v in before.items():
            self.assertEqual((os.path.getsize(p), os.path.getmtime(p)), v)

    def test_broken_files_are_skipped(self):
        with open(os.path.join(self.env.tdir, "aaaaaaaaaaaa.json"), "w") as f:
            f.write("{broken")
        self.env.doc("bbbbbbbbbbbb", {"S1": "A"}, [("r0", "S1", "S1", {})])
        with open(os.path.join(self.env.tdir, "bbbbbbbbbbbb.diar.json"), "w") as f:
            f.write("not json")
        r = self.env.run()
        self.assertEqual((r["meta"]["docs"], r["meta"]["skipped"]["broken"], r["meta"]["skipped"]["noDiar"]), (0, 1, 1))

    def test_few_note_disappears_at_200_rows(self):
        rows = [("r%d" % i, "S1", "S1", {"start": i * 2.0, "end": i * 2.0 + 1.0}) for i in range(E.FEW_ROWS)]
        self.env.doc("cccccccccccc", {"S1": "A"}, rows, diar={}, proofed=True)
        r = self.env.run()
        self.assertFalse(r["meta"]["few"])
        self.assertEqual(r["meta"]["fewNote"], "")


class TestConfirmed(unittest.TestCase):
    """人が確かめた行だけを数える(I-2a。機械の下書きのまま・確かめられない行を外す)"""

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_machine_draft_and_unverified_rows_are_excluded(self):
        # X: 名前は動画の手がかり(context)・行は判別のまま・誰も確かめていない = 機械の下書きのまま(全部外れて文書も数えない)
        ctx = {"checked": True, "speakers": {"S1": vinfo(None, None, decided="A", by="context")}}
        self.env.doc("aaaaaaaaaaaa", {"S1": "A"}, [("r%d" % i, "S1", "S1", {}) for i in range(4)], diar={"voices": ctx})
        # Y: S1 = 声の照合の名前(threshold)・S2 = 人が付けた名前(声の記録なし)
        #   c0 = 人が話者を付け替えた(機械 S1 → 人 S2)= 確かめた / p0 = 校正済み = 確かめた /
        #   r0 = S1 の確かめていない行(S1 は p0 で人が見た)= 確かめられない / u0 = 人が名前を付けた S2 の確かめていない行 = 確かめられない
        thr = {"checked": True, "speakers": {"S1": vinfo("A", 0.8, decided="A", by="threshold")}}
        self.env.doc("bbbbbbbbbbbb", {"S1": "A", "S2": "B"},
                     [("c0", "S2", "S1", {}), ("p0", "S1", "S1", {"proofed": True}), ("r0", "S1", "S1", {}), ("u0", "S2", "S2", {})], diar={"voices": thr})
        res = self.env.run()
        m = res["meta"]
        self.assertEqual((m["docs"], m["machineDraftRows"], m["unverifiedRows"], m["skipped"]["noRows"]), (1, 4, 2, 1))
        a = res["subsets"]["all"]
        self.assertEqual((a["rows"], a["correct"]), (2, 1))   # c0(S1 のラベルは A に対応 → 人は B で間違い)・p0 は正しい
        self.assertTrue(any("機械の下書きのまま" in n for n in m["notes"]))
        self.assertTrue(any("確かめられない" in n for n in m["notes"]))
        full = self.env.run(include_draft=True)   # 今までの数え方(全部)
        self.assertEqual((full["meta"]["docs"], full["subsets"]["all"]["rows"]), (2, 8))

    def test_confirm_map_rules(self):
        doc = {"speakers": [{"id": "S1", "name": "話者1"}, {"id": "S2", "name": "B"}, {"id": "S3", "name": "C"}],
               "segments": [{"id": "a", "speaker": "S1"}, {"id": "b", "speaker": "S2"}, {"id": "c", "speaker": "S3"}, {"id": "d", "speaker": "S3", "proofed": True}]}
        run = {"rows": {"a": {"speaker": "S1"}, "b": {"speaker": "S2"}, "c": {"speaker": "S3"}, "d": {"speaker": "S3"}},
               "voices": {"speakers": {"S2": {"decided": "Ｂ", "by": "elimination"}, "S3": {"decided": "C", "by": "request"}}}}
        got = E.confirm_map(doc, run, False)
        # S1 = 仮の名前・S2 = 消去法の名前(NFKC で同じ)= 機械 → 下書き / S3 = 依頼の名前(人の入力)→ 確かめられない / d = 校正済み
        self.assertEqual(got, {"a": "draft", "b": "draft", "c": "unknown", "d": "human"})
        self.assertEqual(set(E.confirm_map(doc, run, True).values()), {"human"})       # 確かめ済みの文書は全部
        self.assertEqual(E.confirm_map(doc, None, False)["b"], "unknown")               # 判別の記録が無ければ名前は人のもの扱い

    def test_reviewed_modes(self):
        ctx = {"checked": True, "speakers": {"S1": vinfo(None, None, decided="A", by="context")}}
        rows = [("r%d" % i, "S1", "S1", {}) for i in range(3)]
        self.env.doc("aaaaaaaaaaaa", {"S1": "A"}, rows, diar={"voices": ctx}, reviewed=True)           # 確かめ済み(行は校正していない・名前も機械)
        self.env.doc("bbbbbbbbbbbb", {"S1": "A"}, rows, diar={}, eval_set=True, proofed=True)         # 評価用・確かめ済みでない
        self.env.doc("cccccccccccc", {"S1": "A"}, rows, diar={}, proofed=True)                        # 評価用でない
        r = self.env.run()                                                                              # 既定 only
        self.assertEqual((r["meta"]["docs"], r["meta"]["reviewedDocs"], r["meta"]["skipped"]["notReviewed"]), (2, 1, 1))
        self.assertEqual(r["meta"]["reviewed"]["effective"], "only")
        self.assertEqual({d["id"] for d in r["byDoc"]}, {"aaaaaaaaaaaa", "cccccccccccc"})
        self.assertEqual(self.env.run(reviewed="prefer")["meta"]["docs"], 3)
        ig = self.env.run(reviewed="ignore")                                                            # 印を見ない: a は機械の下書きのまま
        self.assertEqual((ig["meta"]["docs"], ig["meta"]["machineDraftRows"]), (2, 3))
        self.assertEqual(self.env.run(only=["aaaaaaaaaaaa", "bbbbbbbbbbbb"])["meta"]["reviewed"]["effective"], "prefer")   # --docs の既定
        with self.assertRaises(SystemExit):
            self.env.run(reviewed="bad")

    def test_only_falls_back_when_nothing_reviewed(self):
        rows = [("r0", "S1", "S1", {})]
        self.env.doc("bbbbbbbbbbbb", {"S1": "A"}, rows, diar={}, eval_set=True, proofed=True)
        self.env.doc("cccccccccccc", {"S1": "A"}, rows, diar={}, proofed=True)
        r = self.env.run()
        self.assertEqual((r["meta"]["docs"], r["meta"]["reviewed"]["fallback"], r["meta"]["reviewed"]["effective"]), (2, True, "ignore"))
        self.assertTrue(any("0 本" in n for n in r["meta"]["notes"]))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(r)
        self.assertIn("only から戻した", buf.getvalue())
        # 評価用が 1 本も無いときは戻さない(注意も出さない)
        env2 = Env()
        self.addCleanup(env2.close)
        env2.doc("cccccccccccc", {"S1": "A"}, rows, diar={}, proofed=True)
        r2 = env2.run()
        self.assertEqual((r2["meta"]["docs"], r2["meta"]["reviewed"]["fallback"]), (1, False))


class TestOverlap(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_precision_and_recall(self):
        # 確かめ済みの文書: 人の重なりのメモ o1・o2・o3 / 機械の mixed は o1・m1 / 区間の重なり(overlaps)は o2 の所(4.0〜4.5)と m2 の所(とても短い 0.05 秒)
        rows = [("o1", "S1", "S1", {"tags": ["overlap"], "mixed": True}), ("p1", "S1", "S1", {}), ("o2", "S1", "S1", {"tags": ["overlap", "bgm"]}),
                ("m1", "S1", "S1", {"mixed": True}), ("m2", "S1", "S1", {}), ("o3", "S1", "S1", {"tags": ["overlap"]})]
        self.env.doc("aaaaaaaaaaaa", {"S1": "A"}, rows, diar={"overlaps": [[4.0, 4.5], [8.0, 8.05]]}, reviewed=True)
        # 確かめ済みでない文書: 校正済みの行だけ入る(u1 は校正していないので入らない)
        self.env.doc("bbbbbbbbbbbb", {"S1": "A"}, [("q1", "S1", "S1", {"proofed": True, "tags": ["overlap"]}), ("u1", "S1", "S1", {"tags": ["overlap"], "mixed": True})],
                     diar={}, reviewed=False)
        o = self.env.run()["overlap"]
        self.assertEqual((o["rows"], o["human"]), (7, 4))
        mx, rg, ei = (o["byPredictor"][k] for k in ("mixed", "region", "either"))
        self.assertEqual((mx["pred"], mx["tp"], mx["fp"], mx["fn"], mx["precision"], mx["recall"]), (2, 1, 1, 3, 0.5, 0.25))
        self.assertEqual((rg["pred"], rg["tp"], rg["recall"]), (1, 1, 0.25))      # m2 の重なりは OVL_MIN_SEC 未満
        self.assertEqual((ei["pred"], ei["tp"], ei["precision"]), (3, 2, round(2 / 3, 4)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(self.env.run())
        self.assertIn("重なりの見つけ方", buf.getvalue())
        self.assertIn("適合率", buf.getvalue())


HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def write_silence(path, sec):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(sec * 16000))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無い")
class TestRun(unittest.TestCase):
    """run(判別し直して測る)を疑似の判別(TRANSCRIBE_BACKEND=fake = 10 秒ごとに入れ替わる・しきい値 1.0 以上で 1 人)で"""

    def setUp(self):
        self.envp = mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0"})
        self.envp.start()
        self.addCleanup(self.envp.stop)
        self.env = Env()
        self.addCleanup(self.env.close)
        self.media = os.path.join(self.env.root, "media")
        os.makedirs(self.media)
        # A: 25 秒・1 人(12 行)。疑似の判別は 2 人に分ける(0〜10 秒・20 秒〜 = 0、10〜20 秒 = 1)
        write_silence(os.path.join(self.media, "a.wav"), 25)
        self.env.doc("aaaaaaaaaaaa", {"S1": "A"}, [("a%d" % i, "S1", "S1", {}) for i in range(12)], diar={}, reviewed=True,
                     source=os.path.join(self.media, "a.wav"))
        # B: 70 秒・2 人が 10 秒ごとに入れ替わる(35 行。S1 = 20 行・S2 = 15 行)。判別の記録なし(run は要らない)
        write_silence(os.path.join(self.media, "b.wav"), 70)
        self.env.doc("bbbbbbbbbbbb", {"S1": "A", "S2": "B"}, [("b%d" % i, "S1" if (i * 2) // 10 % 2 == 0 else "S2", None, {}) for i in range(35)],
                     reviewed=True, source=os.path.join(self.media, "b.wav"))
        # C: 動画が無い → 数えない
        self.env.doc("cccccccccccc", {"S1": "A"}, [("c0", "S1", "S1", {})], diar={}, reviewed=True, source=os.path.join(self.media, "none.wav"))

    def snapshot(self):
        out = {}
        for dp, _, fns in os.walk(self.env.tdir):
            for fn in fns:
                p = os.path.join(dp, fn)
                out[p] = (os.path.getsize(p), os.path.getmtime(p))
        return out

    def test_settings_scoring_lengths_and_table(self):
        before = self.snapshot()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = E.main(["run", "--data-dir", self.env.root, "--threshold", "0.5,1.0", "--num", "auto,2"])
        text = buf.getvalue()
        self.assertEqual(self.snapshot(), before)                                         # 文書・diar.json は書かない
        self.assertFalse(os.path.isdir(os.path.join(self.env.root, "transcribe", "evals")))
        m = res["meta"]
        self.assertEqual((m["mode"], m["backend"], m["docs"], m["reviewedDocs"], m["rows"], m["skipped"]["noAudio"]), ("run", "fake", 2, 2, 47, 1))
        by = {(s["settings"]["threshold"], s["settings"]["num"]): s for s in res["bySetting"]}
        self.assertEqual(len(by), 4)
        a = by[(0.5, 0)]                     # A は 2 人に分けすぎ(7/12)・B はちょうど(35/35)
        self.assertEqual((a["correct"], a["rows"]), (42, 47))
        self.assertEqual((a["byLength"]["short"]["correct"], a["byLength"]["short"]["rows"], a["byLength"]["short"]["docs"]), (7, 12, 1))
        self.assertEqual((a["byLength"]["long"]["correct"], a["byLength"]["long"]["rows"]), (35, 35))
        self.assertEqual(a["speakerCount"]["diff"], {"0": 1, "1": 1})
        self.assertEqual(a["byLength"]["short"]["speakerCount"]["over"], 1)
        b = by[(1.0, 0)]                     # しきい値を上げると 1 人にまとまる: A はちょうど・B は少なすぎ(20/35)
        self.assertEqual((b["correct"], b["byLength"]["short"]["correct"], b["byLength"]["long"]["correct"]), (32, 12, 20))
        self.assertEqual(b["speakerCount"]["diff"], {"-1": 1, "0": 1})
        self.assertEqual(by[(1.0, 2)]["correct"], 42)   # 人数を決めたらしきい値は効かない(本物と同じ)
        for s in res["bySetting"]:
            self.assertGreaterEqual(s["sec"], 0)
            self.assertIn("overlap", s)
        self.assertIn("#1 しきい値 0.50 / 人数 自動", text)
        self.assertIn("60秒未満", text)
        self.assertIn("60秒以上", text)
        self.assertIn("話者の数(機械 − 人)", text)
        self.assertIn("cccccccccccc  とばした", text)
        with contextlib.redirect_stdout(io.StringIO()):
            E.main(["run", "--data-dir", self.env.root, "--docs", "aaaaaaaaaaaa", "--json"])
        files = os.listdir(os.path.join(self.env.root, "transcribe", "evals", "speakers"))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith("-run.json"))

    def test_draft_rows_and_bad_options(self):
        # 確かめ済みでない文書の、人が確かめていない行は run でも数えない
        write_silence(os.path.join(self.media, "d.wav"), 12)
        self.env.doc("dddddddddddd", {"S1": "話者1", "S2": "B"}, [("d0", "S1", "S1", {}), ("d1", "S2", "S2", {}), ("d2", "S2", "S2", {"proofed": True})],
                     diar={}, source=os.path.join(self.media, "d.wav"))
        with contextlib.redirect_stdout(io.StringIO()):
            res = E.run_evaluate(self.env.root, only=["dddddddddddd"])
        self.assertEqual((res["meta"]["rows"], res["meta"]["draftRows"], res["meta"]["unverifiedRows"]), (1, 1, 1))
        self.assertEqual(res["bySetting"][0]["settings"], {"threshold": 0.5, "num": 0, "emb": "voxceleb", "minOn": 0.1, "minOff": 0.3, "smooth": False})   # 既定 = 本番の値
        for bad in (["--threshold", "x"], ["--num", "11"], ["--emb", "nope"], ["--min-on", "-1"], ["--smooth", "maybe"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                E.main(["run", "--data-dir", self.env.root] + bad)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            E.main(["--data-dir", self.env.root, "--threshold", "0.5"])     # run だけの設定


class TestDiarizeTune(unittest.TestCase):
    """src/editor/ed_speakers.py の diarize_real: 判別の設定は任意。渡さなければワーカーへの要求は以前と同じ形"""

    def test_worker_request_shape(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake"}):
            S = E.load_serve()
        calls = []

        class W:
            def call(self, op, args, job=None):
                calls.append((op, dict(args)))
                return [[0.0, 1.0, 0]]
        saved = (S.ed_jobs.IN_WORKER, S.ed_jobs.WORKER)
        S.ed_jobs.IN_WORKER, S.ed_jobs.WORKER = False, W()
        try:
            self.assertEqual(S.diarize_real({}, "a.wav", 0, "voxceleb"), [(0.0, 1.0, 0)])
            S.diarize_real({}, "a.wav", 2, "voxceleb", threshold=0.7, min_off=0.5)
            with self.assertRaises(S.ApiError):
                S.diarize_real({}, "a.wav", 0, "voxceleb", threshold=-1)
        finally:
            S.ed_jobs.IN_WORKER, S.ed_jobs.WORKER = saved
        self.assertEqual(calls[0], ("diarize", {"wav": "a.wav", "num": 0, "emb": "voxceleb"}))
        self.assertEqual(calls[1], ("diarize", {"wav": "a.wav", "num": 2, "emb": "voxceleb", "threshold": 0.7, "minOff": 0.5}))
        self.assertEqual(len(calls), 2)
        self.assertEqual(S.diar_tune(), {})
        self.assertEqual(S.diar_tune("0.6", None, 0), {"threshold": 0.6, "min_off": 0.0})


class TestSmooth(unittest.TestCase):
    """--smooth off,on(話者の細切れをならす S2。src/editor/ed_speakers.py の smooth_labels を読んで計算する)"""

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def put(self, tid, human_mid, smoothed_rec=False):
        """3 行: 前後はラベル 0(S1)・真ん中の短い行だけラベル 1(S2)で根拠が弱い(ratio 0.3)。人の最終は前後が A・真ん中が human_mid"""
        segs = [{"id": "r0", "start": 0.0, "end": 3.0, "text": "あ", "speaker": "S1", "flag": "", "proofed": True},
                {"id": "r1", "start": 3.2, "end": 4.0, "text": "い", "speaker": "S1" if human_mid == "A" else "S2", "flag": "", "proofed": True},
                {"id": "r2", "start": 4.2, "end": 7.0, "text": "う", "speaker": "S1", "flag": "", "proofed": True}]
        self.env._write(tid + ".json", {"id": tid, "title": "t", "updatedAt": ms("2026-10-01"), "segments": segs,
                                        "speakers": [{"id": "S1", "name": "A"}, {"id": "S2", "name": "B"}]})
        mid = {"label": 1, "speaker": "S1", "ratio": 0.3, "mixed": False, "weak": True, "smoothed": True} if smoothed_rec else \
            {"label": 1, "speaker": "S2", "ratio": 0.3, "mixed": False, "weak": True}
        rows = {"r0": {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False}, "r1": mid,
                "r2": {"label": 0, "speaker": "S1", "ratio": 1.0, "mixed": False, "weak": False}}
        self.env._write(tid + ".diar.json", {"schema": "youtube-tools-diar/v1", "history": [], "latest": {
            "at": 1, "engine": {"name": "sherpa-onnx", "embedding": "voxceleb", "clusterThreshold": 0.5, "requested": "auto"},
            "labelMap": {"0": "S1", "1": "S2"}, "rows": rows, "speakers": 2, "voices": {"checked": False}, "overlaps": [],
            "turns": [{"start": 0, "end": 3.1, "label": 0}, {"start": 3.5, "end": 3.74, "label": 1}, {"start": 4.1, "end": 7, "label": 0}]}})

    def test_stored_off_on(self):
        self.put("aaaaaaaaaaaa", "A")    # ならすと直る
        self.put("bbbbbbbbbbbb", "B")    # 本物の短い別の人(根拠は弱い)→ ならすと壊れる
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = E.main(["--data-dir", self.env.root, "--smooth", "off,on"])
        off, on = res["smooth"]
        self.assertEqual((off["key"], off["correct"], off["rows"], off["smoothedRows"]), ("ならさない", 5, 6, 0))   # a: S2 が対応できず 2/3・b: 3/3
        self.assertEqual((on["correct"], on["rows"], on["smoothedRows"], on["smoothedChecked"], on["smoothedCorrect"], on["smoothedWrong"], on["fixed"], on["broke"]),
                         (5, 6, 2, 2, 1, 1, 1, 1))
        self.assertIn("話者の細切れをならす", buf.getvalue())
        self.assertIn("直った 1・壊れた 1", buf.getvalue())
        self.assertNotIn("smooth", E.evaluate(self.env.root))   # 指定しなければ今までどおり(editor を読まない)

    def test_stored_record_already_smoothed(self):
        """ならした回の記録: ならさない側は元のラベル(label)から話者に戻す"""
        self.put("aaaaaaaaaaaa", "A", smoothed_rec=True)
        S = E.load_serve()
        with open(os.path.join(self.env.tdir, "aaaaaaaaaaaa.json"), encoding="utf-8") as f:
            doc = json.load(f)
        run = E.read_diar(self.env.tdir, "aaaaaaaaaaaa")["latest"]
        off, on, ids = E.stored_smooth_recs(S, doc, run)
        self.assertEqual((off["r1"]["speaker"], on["r1"]["speaker"], ids), ("S2", "S1", {"r1"}))

    def test_run_off_on_diarizes_once(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": "0"}):
            media = os.path.join(self.env.root, "media")
            os.makedirs(media)
            write_silence(os.path.join(media, "a.wav"), 25)
            self.env.doc("cccccccccccc", {"S1": "A"}, [("c%d" % i, "S1", "S1", {}) for i in range(12)], diar={}, reviewed=True, source=os.path.join(media, "a.wav"))
            calls = []
            real = E.diarize_once
            with mock.patch.object(E, "diarize_once", lambda *a: calls.append(1) or real(*a)), contextlib.redirect_stdout(io.StringIO()) as buf:
                res = E.main(["run", "--data-dir", self.env.root, "--smooth", "off,on"])
        self.assertEqual(len(calls), 1)   # 判別は 1 回・採点だけ両方
        keys = [s["key"] for s in res["bySetting"]]
        self.assertEqual(len(keys), 2)
        self.assertTrue(keys[1].endswith("/ ならす") and not keys[0].endswith("ならす"))
        self.assertEqual([s["smooth"]["on"] for s in res["bySetting"]], [False, True])
        self.assertEqual(res["bySetting"][0]["correct"], res["bySetting"][1]["correct"])   # 10 秒ごとの入れ替わりには、ならす行が無い
        self.assertIn("ならした行 0", buf.getvalue())


class TestNoSub(unittest.TestCase):
    """字幕に出さない行(noSub・組み込みの話者「ゲーム音声など」)は、話者の正しさ・重なりの見つけ方の数に入れない(件数だけ別に出す)"""

    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.close)

    def test_nosub_and_game_voice_rows_are_excluded(self):
        rows = [("r%d" % i, "S1", "S1", {}) for i in range(5)] + [("b%d" % i, "S2", "S2", {}) for i in range(5)]
        rows += [("g1", "S3", "S2", {"noSub": True, "tags": ["overlap"]}), ("g2", "S3", "S2", {}), ("g3", "S1", "S2", {"noSub": True})]   # S3 = ゲーム音声など
        self.env.doc("aaaaaaaaaaaa", {"S1": "A", "S2": "B", "S3": E.OTHER_VOICE_NAME}, rows, diar={}, proofed=True)
        res = self.env.run()
        self.assertEqual(res["subsets"]["all"]["rows"], 10)
        self.assertEqual(res["subsets"]["all"]["correct"], 10)       # ゲーム音声の行が S2 に紛れても、B の行の正しさは下がらない
        self.assertEqual(res["meta"]["noSubRows"], 3)
        self.assertTrue(any("noSub" in n for n in res["meta"]["notes"]))
        self.assertEqual(res["overlap"]["rows"], 10)                 # 重なりの見つけ方にも入れない(g1 は音のメモ overlap つき)
        self.assertEqual(res["overlap"]["human"], 0)
        # include_draft でも入れない
        self.assertEqual(self.env.run(include_draft=True)["subsets"]["all"]["rows"], 10)

    def test_doc_without_nosub_counts_zero(self):
        self.env.doc("bbbbbbbbbbbb", {"S1": "A"}, [("r1", "S1", "S1", {}), ("r2", "S1", "S1", {})], diar={}, proofed=True)
        res = self.env.run()
        self.assertEqual((res["subsets"]["all"]["rows"], res["meta"]["noSubRows"]), (2, 0))
        self.assertFalse(any("noSub" in n for n in res["meta"]["notes"]))


if __name__ == "__main__":
    unittest.main()
