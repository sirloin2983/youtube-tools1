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
    res = {"meta": meta, "summary": {"overall": {"cer": v, "refChars": 1234}, "ci95": [v - 0.05, v + 0.05], "byDoc": [{}, {}, {}], "proofedSec": 900, "lowData": False}}
elif area == "marks":
    res = {"meta": meta, "overall": {"judgedVideos": 12, "top": {"top10": {"adoptRate": 1 - v}}, "misses": {"missRate": v / 2}}}
elif area == "speakers":
    res = {"meta": meta, "subsets": {"all": {"rate": 1 - v, "rows": 300, "voices": {"rate": 0.9}}}, "speakerCount": {"exactRate": 0.8}}
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
                 evals_dir=self.edir, timeout=30)
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
        self.assertEqual(r, {"asr": "ok", "marks": "ok", "speakers": "ok", "cut": "ok"})
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
        self.assertEqual([a["id"] for a in snap["areas"]], ["asr", "marks", "speakers", "cut"])
        json.dumps(snap)                                 # そのまま JSON にできる


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
        self.assertEqual([a["id"] for a in j["areas"]], ["asr", "marks", "speakers", "cut"])
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
