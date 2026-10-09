"""精度の自動測定(src/home/accuracy.py)の単体テスト。一時フォルダと、dev/eval_*.py の代わりの偽の道具(小さな Python スクリプト)だけを使う。

実行(リポジトリ直下から): py -3.10 -m unittest src/home/tests/test_accuracy.py -v
"""
import datetime
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HOME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(HOME)
for p in (HOME, ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)

import accuracy  # noqa: E402
import prefs as prefs_mod  # noqa: E402
from ytt_core import fsio, jobs  # noqa: E402
import launch as L  # noqa: E402
import test_launch as TL  # noqa: E402  (入口を一時フォルダで動かす道具を借りる。テストそのものは集めない)

# 偽の道具: 引数 = 領域の id・結果の置き場所。環境変数 FAKE_FAIL(領域の id をカンマ区切り)で失敗・FAKE_HANG(同)で居座る・
# FAKE_NOLINE(同)で「保存: 」の行を出さない・FAKE_OUTSIDE(同)で置き場所の外のファイルを知らせる。結果に環境変数 FAKE_MARK(引き継ぎの確認)と FAKE_VALUE を入れる
FAKE = r'''# -*- coding: utf-8 -*-
import json, os, sys, time
area, outdir = sys.argv[1], sys.argv[2]
def on(name):
    return area in [x for x in os.environ.get(name, "").split(",") if x]
if on("FAKE_FAIL"):
    sys.stderr.write("途中の行\n道具が壊れました\n")
    sys.exit(3)
if on("FAKE_HANG"):
    time.sleep(60)
v = float(os.environ.get("FAKE_VALUE", "0.2"))
meta = {"mark": os.environ.get("FAKE_MARK", ""), "docs": 4, "few": False, "fewNote": ""}
if area == "asr":
    res = {"meta": meta, "summary": {"overall": {"cer": v, "refChars": 1234}, "ci95": [v - 0.05, v + 0.05], "byDoc": [{}, {}, {}], "proofedSec": 900, "lowData": False,
                                     "reviewed": {"docs": 3, "sec": 950.0}, "gate": {"gate": "G1", "sec": 950.0}}}
elif area == "marks":
    res = {"meta": meta, "overall": {"judgedVideos": 12, "top": {"top10": {"adoptRate": 1 - v}}, "misses": {"missRate": v / 2}}}
elif area == "speakers":
    res = {"meta": dict(meta, rows=300), "subsets": {"all": {"rate": 1 - v, "rows": 300, "voices": {"rate": 0.9}}}, "speakerCount": {"exactRate": 0.8}}
elif area == "alt":
    res = {"meta": dict(meta, judged=40, candidates=55), "feedback": {"accepted": 3, "rejected": 1, "acceptRate": 0.75},
           "total": {"hitRate": 1 - v, "pickup": {"coveredRate": 0.3}}}
else:
    res = {"meta": meta, "accuracy": {"label": "カットの一致", "value": 1 - v, "docs": 5, "unit": "文書", "better": "higher"}}
d = os.environ.get("FAKE_OUTSIDE_DIR", outdir) if on("FAKE_OUTSIDE") else outdir
os.makedirs(d, exist_ok=True)
seq = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "seq_" + area)   # 本物と同じ名前の形(<日時>.json。asr だけ _auto 付き)。日時は呼ばれた回数で進める
n = (int(open(seq).read()) if os.path.exists(seq) else 0) + 1
open(seq, "w").write(str(n))
path = os.path.join(d, "20260101-%06d%s.json" % (n, "_auto" if area == "asr" else ""))
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
if not on("FAKE_NOLINE"):
    print("結果の表示のあとに")
    print("保存: " + path)
'''


def put_file(path, text="{}"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def at(day, hour, minute=0):
    return datetime.datetime(2026, 10, day, hour, minute).timestamp()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Busy:
    def __init__(self):
        self.why = None

    def __call__(self):
        return self.why


class AccuracyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-accuracy-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = os.path.join(self.tmp, "app")
        self.fake = os.path.join(self.tmp, "fake_eval.py")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write(FAKE)
        self.cut = True       # 偽の eval_cut.py があるか
        self.clock = Clock(at(5, 2))      # 夜の窓(1〜6 時)の中
        self.busy = Busy()
        self.last_edit = None
        self.logs = []
        self.prefs = prefs_mod.Prefs(os.path.join(self.app, "prefs.json"), fsio.atomic_write)
        self.txdir = os.path.join(self.tmp, "transcripts")    # 入口の条件の「普段」を数える文字起こしの文書(無ければ 0)
        env = mock.patch.dict(os.environ, {"FAKE_MARK": "引き継ぎ", "FAKE_FAIL": "", "FAKE_HANG": "", "FAKE_NOLINE": "", "FAKE_OUTSIDE": "",
                                           "FAKE_OUTSIDE_DIR": os.path.join(self.tmp, "outside"), "FAKE_VALUE": "0.2"})
        env.start()
        self.addCleanup(env.stop)
        self.acc = self.make()

    def edir(self, area):
        return os.path.join(self.tmp, "evals", area["id"])

    def commands(self, area):
        if area["id"] == "cut" and not self.cut:
            return None
        return [sys.executable, self.fake, area["id"], self.edir(area)]

    def make(self, **kw):
        a = dict(busy=self.busy, last_edit=lambda: self.last_edit, log=self.logs.append, clock=self.clock, commands=self.commands,
                 evals_dir=self.edir, timeout=30, transcripts_dir=lambda: self.txdir)
        a.update(kw)
        return accuracy.Accuracy(self.prefs, self.app, ROOT, **a)

    # ---- 夜の窓
    def test_in_window(self):
        cfg = {"nightFrom": 1, "nightTo": 6}
        self.assertFalse(accuracy.in_window(at(5, 0, 59), cfg))
        self.assertTrue(accuracy.in_window(at(5, 1), cfg))
        self.assertTrue(accuracy.in_window(at(5, 5, 59), cfg))
        self.assertFalse(accuracy.in_window(at(5, 6), cfg))
        wrap = {"nightFrom": 22, "nightTo": 6}     # 日をまたぐ
        self.assertTrue(accuracy.in_window(at(5, 23), wrap))
        self.assertTrue(accuracy.in_window(at(5, 3), wrap))
        self.assertFalse(accuracy.in_window(at(5, 12), wrap))
        self.assertTrue(accuracy.in_window(at(5, 12), {"nightFrom": 0, "nightTo": 24}))   # 一日中

    # ---- 設定
    def test_prefs_section(self):
        self.assertEqual(self.prefs.get(["accuracy"])["accuracy"], {"enabled": True, "nightFrom": 1, "nightTo": 6})   # 既定はオン
        self.assertEqual(self.prefs.patch("accuracy", {"nightFrom": 23, "nightTo": 5}), {"enabled": True, "nightFrom": 23, "nightTo": 5})
        for bad in ({"nightFrom": 24}, {"nightTo": 0}, {"nightFrom": "1"}, {"nightFrom": True}, {"nightFrom": 5, "nightTo": 5}):
            with self.assertRaises(prefs_mod.PrefsError):
                self.prefs.patch("accuracy", bad)
        self.assertEqual(self.prefs.patch("accuracy", {"enabled": False})["enabled"], False)
        self.assertEqual(self.prefs.patch("accuracy", {"enabled": "yes"})["enabled"], False)   # true 以外はオフ

    # ---- 結果の要約
    def test_summaries_from_tool_shapes(self):
        asr = accuracy.summarize_asr({"summary": {"overall": {"cer": 0.12, "refChars": 500}, "ci95": [0.1, 0.14], "byDoc": [{}, {}], "proofedSec": 800, "lowData": True}})
        self.assertEqual((asr["label"], asr["value"], asr["range"], asr["docs"], asr["few"], asr["lowData"], asr["better"]), ("CER", 0.12, [0.1, 0.14], 2, False, True, "lower"))
        self.assertEqual((asr["chars"], asr["proofedSec"]), (500, 800))
        one = accuracy.summarize_asr({"summary": {"overall": {"cer": None, "refChars": 0}, "ci95": None, "byDoc": [{}]}})
        self.assertIsNone(one["value"])
        self.assertTrue(one["few"])                      # 文書 2 本未満は「まだ少ない」
        marks = accuracy.summarize_marks({"meta": {"few": True}, "overall": {"judgedVideos": 3, "top": {"top10": {"adoptRate": 0.7}}, "misses": {"missRate": 0.1}}})
        self.assertEqual((marks["value"], marks["docs"], marks["unit"], marks["lowData"], marks["extra"][0]["value"]), (0.7, 3, "配信", True, 0.1))
        # K2: 線 D の録画・友人の返事も足した judgedAll があれば、配信の数(C1 の入口)はそれ。無い以前の結果は judgedVideos
        marks2 = accuracy.summarize_marks({"meta": {"few": True}, "overall": {"judgedVideos": 3, "judgedAll": 7, "top": {"top10": {"adoptRate": 0.7}}, "misses": {"missRate": 0.1}}})
        self.assertEqual((marks2["value"], marks2["docs"]), (0.7, 7))
        spk = accuracy.summarize_speakers({"meta": {"docs": 9, "fewNote": ""}, "subsets": {"all": {"rate": 0.8, "voices": {"rate": 0.9}}}, "speakerCount": {"exactRate": 0.5}})
        self.assertEqual((spk["value"], spk["docs"], [e["value"] for e in spk["extra"]]), (0.8, 9, [0.9, 0.5]))
        gen = accuracy.summarize_generic({"accuracy": {"label": "x", "value": 0.4, "docs": 3, "better": "lower", "extra": [{"label": "y", "value": 1}]}})
        self.assertEqual((gen["label"], gen["value"], gen["better"], gen["extra"]), ("x", 0.4, "lower", [{"label": "y", "value": 1.0, "better": "higher"}]))
        cut = accuracy.summarize_cut({"meta": {"docs": 6, "few": True}, "total": {"untouchedRate": 0.5, "edges30": {"sameRate": 0.75}}})
        self.assertEqual((cut["value"], cut["docs"], cut["lowData"], cut["extra"][0]["value"]), (0.5, 6, True, 0.75))
        self.assertEqual(accuracy.summarize_cut({"accuracy": {"label": "x", "value": 0.4}})["value"], 0.4)   # total が無くても accuracy の鍵があればそれを使う
        for fn in (accuracy.summarize_asr, accuracy.summarize_marks, accuracy.summarize_speakers, accuracy.summarize_cut, accuracy.summarize_generic):
            with self.assertRaises(ValueError):
                fn({})                                   # 形が違う結果は断る

    # ---- いつ測るか
    def test_runs_in_night_window_once_a_day(self):
        r = self.acc.tick()
        self.assertEqual(r, {"asr": "ok", "marks": "ok", "speakers": "ok", "cut": "ok", "alt": "ok"})
        snap = self.acc.snapshot()
        by = {a["id"]: a for a in snap["areas"]}
        self.assertEqual(by["asr"]["latest"]["summary"]["value"], 0.2)
        self.assertEqual(by["marks"]["latest"]["summary"]["value"], 0.8)
        self.assertEqual(by["speakers"]["latest"]["summary"]["value"], 0.8)
        self.assertEqual(by["cut"]["latest"]["summary"]["label"], "カットの一致")
        self.assertEqual(snap["state"], "idle")
        self.assertIs(snap["heavyEnabled"], False)       # 重い測定は入れていない
        self.assertEqual(self.acc.last["day"], "2026-10-05")
        self.clock.t = at(5, 4)
        self.assertIsNone(self.acc.tick())               # 同じ日の窓の中でも 2 回目は測らない
        self.clock.t = at(5, 15)
        self.assertIsNone(self.acc.tick())               # 昼は測らない
        self.clock.t = at(6, 12)
        self.assertIsNone(self.acc.tick())               # 次の日でも窓の外は測らない
        self.assertEqual(self.acc.snapshot()["state"], "idle")
        self.clock.t = at(6, 3)
        os.environ["FAKE_VALUE"] = "0.1"
        self.assertEqual(self.acc.tick()["asr"], "ok")   # 次の日の窓でまた 1 回
        by = {a["id"]: a for a in self.acc.snapshot()["areas"]}
        self.assertEqual(by["asr"]["latest"]["summary"]["value"], 0.1)    # 直近
        self.assertEqual(by["asr"]["prev"]["summary"]["value"], 0.2)      # 前回

    def test_child_inherits_environment(self):
        self.acc.tick()
        path = os.path.join(self.edir({"id": "asr"}))
        name = os.listdir(path)[0]
        with open(os.path.join(path, name), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["meta"]["mark"], "引き継ぎ")   # YTT_DATA_DIR などの環境変数をそのまま引き継ぐ

    def test_waits_while_busy_then_runs(self):
        self.busy.why = "文字起こしのジョブ"
        self.assertIsNone(self.acc.tick())
        snap = self.acc.snapshot()
        self.assertEqual(snap["state"], "waiting")
        self.assertIn("文字起こしのジョブ", snap["message"])
        self.assertIsNone(self.acc.last.get("day"))      # 測っていないので 1 日 1 回に数えない
        self.assertFalse(os.path.exists(self.edir({"id": "asr"})))
        self.busy.why = None
        self.assertEqual(self.acc.tick()["asr"], "ok")
        self.assertEqual(self.acc.snapshot()["state"], "idle")

    def test_waits_for_quiet_documents_only_for_automatic_runs(self):
        self.last_edit = self.clock.t - 10 * 60          # 10 分前に校正した
        self.assertIsNone(self.acc.tick())
        self.assertEqual(self.acc.snapshot()["state"], "waiting")
        self.assertIn("あと", self.acc.snapshot()["message"])
        self.last_edit = self.clock.t - 31 * 60
        self.assertIsNotNone(self.acc.tick())            # 30 分以上たてば測る
        self.last_edit = self.clock.t - 10
        self.assertTrue(self.acc.run_now())
        self.assertIsNotNone(self.acc.tick())            # 「今すぐ」は文書の静けさを待たない

    def test_run_now_ignores_window_and_day_but_waits_for_busy(self):
        self.clock.t = at(5, 15)                         # 昼
        self.assertIsNone(self.acc.tick())
        self.assertTrue(self.acc.run_now())
        self.assertIs(self.acc.snapshot()["forced"], True)
        self.busy.why = "重い処理"
        self.assertIsNone(self.acc.tick())               # 忙しいときは待つ(「今すぐ」も)
        self.assertIs(self.acc.force, True)              # 取り下げずに残る
        self.assertEqual(self.acc.snapshot()["state"], "waiting")
        self.busy.why = None
        self.assertIsNotNone(self.acc.tick())            # 空いたら昼でも測る
        self.assertIs(self.acc.force, False)
        self.assertIsNone(self.acc.tick())               # 1 回で終わる
        self.clock.t = at(6, 3)
        self.assertIsNotNone(self.acc.tick())            # 今日測ったあとでも、次の日の窓ではまた測る
        self.acc.last["day"] = "2026-10-06"
        self.assertTrue(self.acc.run_now())
        self.assertIsNotNone(self.acc.tick())            # 同じ日でも「今すぐ」は測る

    def test_disabled(self):
        self.prefs.patch("accuracy", {"enabled": False})
        self.assertIsNone(self.acc.tick())
        self.assertEqual(self.acc.snapshot()["state"], "off")
        self.assertFalse(self.acc.run_now())             # オフのときは受け付けない
        self.assertFalse(self.acc.force)
        self.assertFalse(os.path.exists(self.edir({"id": "asr"})))
        self.prefs.patch("accuracy", {"enabled": True})
        self.assertIsNotNone(self.acc.tick())

    # ---- 失敗しても止まらない
    def test_failing_tool_does_not_stop_the_others(self):
        os.environ["FAKE_FAIL"] = "marks"
        r = self.acc.tick()
        self.assertEqual((r["asr"], r["speakers"], r["cut"]), ("ok", "ok", "ok"))
        self.assertIn("終了コード 3", r["marks"])
        self.assertIn("道具が壊れました", r["marks"])
        by = {a["id"]: a for a in self.acc.snapshot()["areas"]}
        self.assertIn("道具が壊れました", by["marks"]["error"])
        self.assertIsNone(by["marks"]["latest"])
        self.assertIsNotNone(by["asr"]["latest"])
        self.assertEqual(self.acc.last["day"], "2026-10-05")   # 失敗でも 1 日 1 回に数える(夜通しやり直さない)
        self.assertTrue(any("盛り上がり" in m for m in self.logs))
        # 次の測定で直れば、前の結果は消えずに、新しい結果が直近になりエラーは消える
        os.environ["FAKE_FAIL"] = ""
        self.clock.t = at(6, 3)
        self.acc.tick()
        by = {a["id"]: a for a in self.acc.snapshot()["areas"]}
        self.assertEqual(by["marks"]["error"], "")
        self.assertIsNotNone(by["marks"]["latest"])
        # 直った後にまた失敗しても、最後の良い結果は残る
        os.environ["FAKE_FAIL"] = "marks"
        self.clock.t = at(7, 3)
        self.acc.tick()
        by = {a["id"]: a for a in self.acc.snapshot()["areas"]}
        self.assertIn("道具が壊れました", by["marks"]["error"])
        self.assertIsNotNone(by["marks"]["latest"])

    def test_timeout_kills_the_child(self):
        os.environ["FAKE_HANG"] = "speakers"
        self.acc.timeout = 1.5
        r = self.acc.tick()
        self.assertIn("時間切れ", r["speakers"])
        self.assertEqual((r["asr"], r["marks"]), ("ok", "ok"))

    def test_missing_tool_is_skipped(self):
        self.cut = False                                 # dev/eval_cut.py はまだ無い
        r = self.acc.tick()
        self.assertIsNone(r["cut"])
        by = {a["id"]: a for a in self.acc.snapshot()["areas"]}
        self.assertFalse(by["cut"]["available"])
        self.assertTrue(by["asr"]["available"])
        self.assertEqual(by["cut"]["error"], "")
        # 実物の既定の呼び方: dev/ に道具があれば呼ぶ・無ければ None
        real = accuracy.Accuracy(self.prefs, self.app, ROOT)
        got = {a["id"]: real.commands(a) for a in accuracy.AREAS}
        self.assertEqual(got["asr"][2:], ["stored", "--label", "auto"])
        self.assertEqual(os.path.basename(got["marks"][1]), "eval_marks.py")
        self.assertEqual(got["cut"] is None, not os.path.isfile(os.path.join(os.path.dirname(ROOT), "dev", "eval_cut.py")))   # dev/ は src の1つ上

    def test_result_file_found_without_saved_line_but_not_outside(self):
        real_clock = accuracy.Accuracy(self.prefs, self.app, ROOT, busy=self.busy, commands=self.commands, evals_dir=self.edir, timeout=30, log=self.logs.append)
        os.environ["FAKE_NOLINE"] = "asr"                # 「保存: 」の行が無ければ、置き場所の中の新しいファイルを使う
        self.assertTrue(real_clock.run_now())
        r = real_clock.tick()
        self.assertEqual(r["asr"], "ok")
        os.environ["FAKE_OUTSIDE"] = "marks"             # 置き場所の外のファイルを知らされても読まない
        self.assertTrue(real_clock.run_now())
        r = real_clock.tick()
        self.assertIn("外", r["marks"])
        self.assertEqual(r["asr"], "ok")

    def test_unreadable_result_is_a_failure_not_a_crash(self):
        with mock.patch.object(accuracy, "summarize_asr", side_effect=ValueError("壊れた結果")):
            areas = tuple(dict(a, summarize=accuracy.summarize_asr) if a["id"] == "asr" else a for a in accuracy.AREAS)
            with mock.patch.object(accuracy, "AREAS", areas):
                r = self.acc.tick()
        self.assertIn("結果を読めませんでした", r["asr"])
        self.assertEqual(r["marks"], "ok")

    # ---- 結果ファイルの整理
    def test_prunes_only_own_result_files_keeping_newest(self):
        acc = self.make(keep=3)
        mine = {a["id"]: self.edir(a) for a in accuracy.AREAS}
        # 人が手で流した結果(同じ名前の形の古い日時・別の名前・フォルダ・別の拡張子)は、自動の分ではないので消さない
        for aid, d in mine.items():
            put_file(os.path.join(d, "20250101-000000.json"))
            put_file(os.path.join(d, "20250102-000000_manual.json"))
            put_file(os.path.join(d, "memo.txt"))
            os.makedirs(os.path.join(d, "20240101-000000.json.d"))
        put_file(os.path.join(mine["asr"], "20250103-000000_baseline.json"))
        for day in range(5, 12):                      # 7 回測る(夜の窓に 1 日 1 回)
            self.clock.t = at(day, 3)
            self.assertEqual(acc.tick()["asr"], "ok")
        for aid, d in mine.items():
            names = sorted(os.listdir(d))
            auto = [n for n in names if n.startswith("20260101-")]
            self.assertEqual(len(auto), 3, (aid, names))                       # 自動の分は新しい 3 件だけ
            self.assertEqual(auto, sorted(acc.last["areas"][aid]["files"]))
            self.assertEqual(auto[-1], acc.last["areas"][aid]["latest"]["file"])   # 直近は残る
            self.assertTrue(os.path.isdir(os.path.join(d, "20240101-000000.json.d")))
            for keep in ("memo.txt",):
                self.assertIn(keep, names)
        for aid in ("marks", "speakers", "cut"):   # 印が無い領域: 手で流した分(古い日時の名前)は、一覧に無いので消さない
            self.assertIn("20250101-000000.json", os.listdir(mine[aid]))
            self.assertIn("20250102-000000_manual.json", os.listdir(mine[aid]))
        self.assertEqual(len([n for n in os.listdir(mine["asr"]) if n.endswith("_auto.json")]), 3)
        self.assertIn("20250101-000000.json", os.listdir(mine["asr"]))
        self.assertIn("20250102-000000_manual.json", os.listdir(mine["asr"]))
        self.assertIn("20250103-000000_baseline.json", os.listdir(mine["asr"]))

    def test_prune_finds_auto_asr_files_when_the_list_is_lost_but_not_other_areas(self):
        acc = self.make(keep=2)
        asr, marks = self.edir({"id": "asr"}), self.edir({"id": "marks"})
        for i in range(4):
            put_file(os.path.join(asr, "2025010%d-000000_auto.json" % (i + 1)))
            put_file(os.path.join(marks, "2025010%d-000000.json" % (i + 1)))   # marks は印が無い = 一覧に無いものは自分のか分からないので消さない
        self.assertEqual(acc.tick()["asr"], "ok")
        self.assertEqual(len([n for n in os.listdir(asr) if n.endswith("_auto.json")]), 2)   # asr は印で拾って整理
        self.assertEqual(len(os.listdir(marks)), 4 + 1)

    def test_prune_ignores_unsafe_names_and_symlinks_and_outside_files(self):
        acc = self.make(keep=1)
        d = self.edir({"id": "marks"})
        outside = os.path.join(self.tmp, "outside_file.json")
        put_file(outside)
        put_file(os.path.join(d, "20250101-000000.json"))
        put_file(os.path.join(d, "20260101-000009.json"))
        area = [a for a in accuracy.AREAS if a["id"] == "marks"][0]
        entry = {"files": ["../outside_file.json", "20250101-000000.json", "x/20250102-000000.json", "memo.json", 5, None, "20260101-000009.json"]}
        acc._prune(area, entry)
        self.assertTrue(os.path.exists(outside))                               # 置き場所の外は触らない
        self.assertEqual(entry["files"], ["20260101-000009.json"])             # 形の合う名前だけ数えて、新しい 1 件を残す
        self.assertFalse(os.path.exists(os.path.join(d, "20250101-000000.json")))   # 一覧にあって古いものは消える
        link = os.path.join(d, "20240101-000000.json")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError, AttributeError):
            return                                                             # シンボリックリンクを作れない環境では、ここまで
        entry["files"] = ["20240101-000000.json", "20260101-000009.json"]
        acc._prune(area, entry)
        self.assertTrue(os.path.islink(link))                                  # リンクは消さない(たどらない)
        self.assertTrue(os.path.exists(outside))

    # ---- 記録
    def test_state_is_persisted_and_reloaded(self):
        self.acc.tick()
        again = self.make()
        self.assertEqual(again.last["day"], "2026-10-05")
        self.assertIsNone(again.tick())                  # 起動し直しても今日は測らない
        by = {a["id"]: a for a in again.snapshot()["areas"]}
        self.assertEqual(by["asr"]["latest"]["summary"]["value"], 0.2)
        self.assertTrue(os.path.isfile(os.path.join(self.app, accuracy.STATE_FILE)))
        with open(os.path.join(self.app, accuracy.STATE_FILE), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        self.assertEqual(self.make().snapshot()["areas"][0]["latest"], None)   # 壊れた記録は読まずに空で始める

    def test_busy_and_last_edit_probe_errors_do_not_block(self):
        def boom():
            raise RuntimeError("probe")
        acc = self.make(busy=boom, last_edit=boom)
        self.assertIsNotNone(acc.tick())                 # 判定が失敗しても止まらない(測る)

    def test_snapshot_shape(self):
        snap = self.acc.snapshot()
        for k in ("enabled", "nightFrom", "nightTo", "state", "stateLabel", "message", "heavyEnabled", "forced", "lastRun", "areas"):
            self.assertIn(k, snap)
        self.assertEqual([a["id"] for a in snap["areas"]], ["asr", "marks", "speakers", "cut", "alt"])
        self.assertEqual([g["id"] for g in snap["goals"]], [g["id"] for g in accuracy.GOALS])
        json.dumps(snap)                                 # そのまま JSON にできる

    # ---- 入口の条件(あと何本・何分。入口 0.38.0)
    def test_goals_before_any_measurement_are_unmeasured(self):
        goals = self.acc.snapshot()["goals"]
        self.assertEqual(len(goals), 8)
        for g in goals:
            self.assertEqual((g["now"], g["left"], g["reached"], g["at"]), (None, None, False, None), g["id"])   # 画面は「未測定」
        by = {g["id"]: g for g in goals}
        self.assertEqual((by["g1"]["target"], by["g2fixed"]["target"], by["g2daily"]["target"], by["train"]["target"]), (900, 1800, 1800, 10800))
        self.assertEqual((by["speakers"]["target"], by["marks"]["target"], by["packs"]["target"], by["alt"]["target"]), (200, 10, 20, 100))
        self.assertEqual((by["g1"]["unit"], by["speakers"]["unit"], by["marks"]["unit"], by["alt"]["unit"]), ("sec", "行", "本", "件"))

    def test_goals_from_tool_results_and_daily_count(self):
        put_file(os.path.join(self.txdir, "aaaaaaaaaa01.json"), json.dumps({"id": "aaaaaaaaaa01", "segments": [   # 普段: 校正済み 2 行 = 30 秒
            {"start": 0, "end": 10, "proofed": True}, {"start": 20, "end": 40, "proofed": True},
            {"start": 40, "end": 100, "proofed": True, "tags": ["unclear"]},        # 聞き取れない印は数えない
            {"start": 100, "end": 500, "proofed": False}]}))                        # 校正していない行は数えない
        put_file(os.path.join(self.txdir, "aaaaaaaaaa02.json"), json.dumps({"id": "aaaaaaaaaa02", "evalSet": True, "segments": [
            {"start": 0, "end": 600, "proofed": True}]}))                           # 評価用は定点の側(普段に数えない)
        put_file(os.path.join(self.txdir, "aaaaaaaaaa01.edit.json"), json.dumps({"segments": [{"start": 0, "end": 900, "proofed": True}]}))   # 文書以外は読まない
        put_file(os.path.join(self.txdir, "notadoc.json"), json.dumps({"segments": [{"start": 0, "end": 900, "proofed": True}]}))
        put_file(os.path.join(self.txdir, "aaaaaaaaaa03.json"), "{壊れた")                                     # 読めない文書は飛ばす
        self.acc.tick()
        by = {g["id"]: g for g in self.acc.snapshot()["goals"]}
        self.assertEqual((by["g1"]["now"], by["g1"]["left"], by["g1"]["reached"]), (950.0, 0.0, True))     # 定点 = eval_asr の summary.reviewed.sec
        self.assertEqual((by["g2fixed"]["now"], by["g2fixed"]["left"], by["g2fixed"]["reached"]), (950.0, 850.0, False))
        self.assertEqual((by["g2daily"]["now"], by["g2daily"]["left"]), (30.0, 1770.0))                   # 普段 = 入口が数えた評価用以外の校正済み
        self.assertEqual((by["train"]["now"], by["train"]["left"]), (30.0, 10770.0))
        self.assertEqual((by["speakers"]["now"], by["speakers"]["left"], by["speakers"]["reached"]), (300.0, 0, True))
        self.assertEqual((by["marks"]["now"], by["marks"]["reached"]), (12.0, True))                        # 判定のある配信(eval_marks の judgedVideos)
        self.assertEqual((by["alt"]["now"], by["alt"]["left"], by["alt"]["reached"]), (40.0, 60, False))   # 判定できた候補(eval_alt の meta.judged)
        self.assertIsNone(by["packs"]["now"])            # 偽のカットの道具は fromPack を出さない = 未測定のまま
        self.assertIsNone(by["packs"]["left"])
        self.assertIsInstance(by["g1"]["at"], int)
        self.assertEqual(self.acc.last["daily"]["docs"], 1)
        again = self.make()                              # 記録に残る(起動し直しても出る)
        self.assertEqual({g["id"]: g["now"] for g in again.snapshot()["goals"]}, {g["id"]: g["now"] for g in self.acc.snapshot()["goals"]})

    def test_daily_count_failure_keeps_the_measurement(self):
        def boom():
            raise RuntimeError("フォルダ")
        acc = self.make(transcripts_dir=boom)
        self.assertEqual(acc.tick()["asr"], "ok")        # 数えられなくても測定は成功
        by = {g["id"]: g for g in acc.snapshot()["goals"]}
        self.assertIsNone(by["g2daily"]["now"])
        self.assertTrue(any("普段" in m for m in self.logs))
        self.assertEqual(accuracy.count_daily(os.path.join(self.tmp, "無い")), {"sec": 0.0, "docs": 0, "lines": 0})

    def test_goal_thresholds_match_the_tools(self):
        """しきい値は accuracy.py の GOALS の 1 か所。道具の「まだ少ない」の値(dev/eval_*.py の定数)と食い違わない(道具は読むだけ。import しない)"""
        import ast
        dev = os.path.join(os.path.dirname(ROOT), "dev")

        def const(script, name):
            path = os.path.join(dev, script)
            if not os.path.isfile(path):
                self.skipTest("dev/%s が無い" % script)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                    return eval(compile(ast.Expression(node.value), path, "eval"), {"__builtins__": {}})   # 定数の式(15 * 60 など)だけ
            self.fail("dev/%s に %s が無い" % (script, name))
        by = {g["id"]: g["target"] for g in accuracy.GOALS}
        gates = dict(const("eval_asr.py", "GATES"))
        self.assertEqual((by["g1"], by["g2fixed"]), (gates["G1"], gates["G2"]))
        self.assertEqual(by["speakers"], const("eval_speakers.py", "FEW_ROWS"))
        self.assertEqual(by["marks"], const("eval_marks.py", "FEW_VIDEOS"))
        self.assertEqual(by["packs"], const("eval_cut.py", "FEW_PACKS"))
        self.assertEqual(by["alt"], const("eval_alt.py", "FEW_CANDS"))

    def test_summarize_alt_and_counts(self):
        alt = accuracy.summarize_alt({"meta": {"docs": 3, "few": True, "judged": 7, "candidates": 31}, "feedback": None,
                                      "total": {"hitRate": 0.5, "pickup": {"coveredRate": 0.2}}})
        self.assertEqual((alt["value"], alt["docs"], alt["lowData"], alt["judged"], alt["candidates"]), (0.5, 3, True, 7.0, 31.0))
        self.assertEqual([e["value"] for e in alt["extra"]], [None, 0.2])
        with self.assertRaises(ValueError):
            accuracy.summarize_alt({"meta": {}})
        asr = accuracy.summarize_asr({"summary": {"overall": {"cer": 0.1}, "gate": {"sec": 120.5}}})
        self.assertEqual(asr["reviewedSec"], 120.5)      # reviewed が無ければ gate の秒
        self.assertIsNone(accuracy.summarize_asr({"summary": {"overall": {"cer": 0.1}}})["reviewedSec"])
        self.assertEqual(accuracy.summarize_speakers({"meta": {"rows": 208}, "subsets": {"all": {"rate": 0.86}}})["rows"], 208.0)
        self.assertEqual(accuracy.summarize_cut({"meta": {"docs": 6, "fromPack": 2}, "total": {"untouchedRate": 0.5}})["fromPack"], 2.0)


class AccuracyApiTest(TL.Base):
    """入口の API(GET api/accuracy・POST api/accuracy/run・調子の accuracy・設定の節)と、手が空いた判定のつなぎ"""

    def setUp(self):
        super().setUp()
        self.srv, self.port = L.make_server(0, self.sup)
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.host = "127.0.0.1:%d" % self.port

    def tearDown(self):
        if not self.srv.closing.is_set():
            self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=body, headers=dict({"Host": self.host}, **(headers or {})))
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r, data

    def post(self, path, headers=None, body=b"{}"):
        h = {"Content-Type": "application/json", "Origin": "http://" + self.host, "Sec-Fetch-Site": "same-origin", "X-YTT-Token": self.srv.token}
        h.update(headers or {})
        return self.req("POST", path, body, h)

    def test_api(self):
        r, body = self.req("GET", "/api/accuracy")
        j = json.loads(body)
        self.assertEqual((r.status, j["enabled"], j["state"], j["nightFrom"], j["nightTo"], j["heavyEnabled"]), (200, True, "idle", 1, 6, False))
        self.assertEqual([a["id"] for a in j["areas"]], ["asr", "marks", "speakers", "cut", "alt"])
        self.assertEqual(len(j["goals"]), len(accuracy.GOALS))   # 入口の条件(あと何本・何分)
        r, _ = self.req("GET", "/api/accuracy", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status, 403)
        r, body = self.req("GET", "/api/health")   # 調子にも同じものが入る
        self.assertEqual(json.loads(body)["accuracy"]["state"], "idle")
        r, _ = self.post("/api/accuracy/run", headers={"X-YTT-Token": "x"})   # 合言葉が要る
        self.assertEqual(r.status, 403)
        r, body = self.post("/api/accuracy/run")
        self.assertEqual((r.status, json.loads(body)["forced"]), (200, True))
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "accuracy", "value": {"enabled": False}}).encode())
        self.assertEqual((r.status, json.loads(body)["value"]["enabled"]), (200, False))
        r, body = self.post("/api/accuracy/run")
        self.assertEqual((r.status, json.loads(body)["error"]), (409, "off"))     # オフのときは受け付けない
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "patch", "section": "accuracy", "value": {"nightFrom": 7, "nightTo": 7}}).encode())
        self.assertEqual(r.status, 400)
        r, body = self.post("/api/ytt/prefs", body=json.dumps({"op": "get", "sections": ["accuracy"]}).encode())
        self.assertEqual(json.loads(body)["prefs"]["accuracy"], {"enabled": False, "nightFrom": 1, "nightTo": 6})

    def test_busy_probe(self):
        self.assertIsNone(self.srv._accuracy_busy())          # 何も動いていない(編集も動いていない)
        with jobs.SLOTS.slot("studio", "テスト") as ok:
            self.assertTrue(ok)
            self.assertEqual(self.srv._accuracy_busy(), "重い処理")
        self.assertIsNone(self.srv._accuracy_busy())

    def test_last_edit_probe(self):
        self.assertIsNone(self.srv._accuracy_last_edit())      # 文書のフォルダが無い
        import cases as cases_mod
        d = cases_mod.locations(self.sup.root)["transcripts"]
        os.makedirs(d, exist_ok=True)
        for name, t in (("a.json", 1000.0), ("b.edit.json", 3000.0), ("c.diar.json", 2000.0)):
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write("{}")
            os.utime(p, (t, t))
        os.makedirs(os.path.join(d, ".hist"))                  # 履歴のフォルダは数えない
        self.assertEqual(self.srv._accuracy_last_edit(), 3000.0)


if __name__ == "__main__":
    unittest.main()
