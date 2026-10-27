"""src/friendapp/inbox.py のテスト(受信箱の記録・決める・3 日の片付け・画面へ出す形)。リポジトリ直下で: py -3.12 -m unittest tests/friendapp/test_inbox.py"""
import datetime
import glob
import json
import os
import shutil
import sys
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402
from friendapp import inbox  # noqa: E402
from ytt import trashbin  # noqa: E402

T0 = 1750000000.0          # 基準の時刻(秒)
DAY_MS = 86400 * 1000
RID = "20250615-120000-aaaaaa"
RID2 = "20250615-120100-bbbbbb"


class Clock:
    """時計(秒)。テストが t を書き換えて進める"""

    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def day_of(t):
    """受信箱がごみ箱へ移した物のフォルダ(<日付>/受信箱。形は ytt/trashbin)"""
    return os.path.join(trashbin.day_name(t), inbox.TRASH_KIND)


def iso_day(t):
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d")


class ClipLabelTest(unittest.TestCase):
    def test_clip_label_from_export_name(self):
        """受け取るのカードの下の文字: 書き出しの名前 <番号>_<始まり>-<終わり> は「配信の 1:56〜5:21」に・違えば題のまま"""
        L = inbox.Inbox._clip_label
        self.assertEqual(L({"title": "01_00h01m56s-00h05m21s", "name": "x"}), "配信の 1:56 あたり")
        self.assertEqual(L({"title": "03_01h52m21s-01h56m05s", "name": "x"}), "配信の 1:52:21 あたり")
        self.assertEqual(L({"title": "見どころ 1", "name": "x"}), "見どころ 1")


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self, "inbox-")
        self.path = os.path.join(self.tmp, "friend", "inbox.json")
        self.outbox = os.path.join(self.tmp, "outbox")
        self.save = os.path.join(self.tmp, "save")
        self.cases = os.path.join(self.tmp, "cases")
        self.clock = Clock(T0)
        self.box = self.new_box()

    def new_box(self):
        return inbox.Inbox(self.path, self.outbox, lambda: self.save, lambda: self.cases, clock=self.clock)

    def test_unreadable_record_is_kept_before_overwrite(self):
        """形の版が違う記録(前の版へ戻ったとき)は、空から始める前に写しを残す"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"v": 999, "rows": [{"id": "x"}]}, f)
        box = self.new_box()
        self.assertEqual(box.rows, [])
        bad = glob.glob(self.path + ".bad-*")
        self.assertEqual(len(bad), 1)
        with open(bad[0], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["v"], 999)

    def make_case(self, rid, names):
        """案件フォルダ(一時保管の中)とその中のパックのフォルダを作る -> (案件, [パックのフォルダ])"""
        case = os.path.join(self.cases, "案件-" + rid)
        dirs = []
        for n in names:
            d = os.path.join(case, "パック", n)
            os.makedirs(d)
            with open(os.path.join(d, "clip.mp4"), "wb") as f:
                f.write(b"x")
            dirs.append(d)
        return case, dirs

    def arrive(self, rid, names, run_id=None, vid="dQw4w9WgXcQ", title="題", streamer=""):
        """送った行を足して届いた状態にする -> (行, 案件, パックのフォルダ)"""
        run_id = run_id or "run-" + rid
        self.box.add(rid, {"url": "u", "videoId": vid, "streamer": streamer}, {"url": "u", "videoId": vid, "title": title}, run_id=run_id)
        case, dirs = self.make_case(rid, names)
        r = self.box.finished(run_id, "done", "", [{"dir": d, "seconds": 10.5} for d in dirs], case=case)
        return r, case, dirs

    def failed_row(self, rid, state="error", error=""):
        run_id = "run-" + rid
        self.box.add(rid, {"url": "u"}, {"url": "u", "videoId": "x", "title": "", "channel": ""}, run_id=run_id)
        return self.box.finished(run_id, state, error, [])

    def verdict_files(self, rid, name):
        """判断の記録(<依頼>__<パック名>~<13 桁>.verdict.json)の一覧(古い順)"""
        return sorted(glob.glob(os.path.join(self.outbox, "%s__%s~*.verdict.json" % (rid, glob.escape(name)))))

    def read_verdict(self, rid, name, nth=-1):
        files = self.verdict_files(rid, name)
        self.assertTrue(files, "判断の記録が無い: %s" % name)
        with open(files[nth], encoding="utf-8") as f:
            return json.load(f)

    def kept_path(self, folder, num):
        return os.path.join(self.save, "%s_#%d" % (folder, num))   # 保存先の直下に平らに(10-24)

    # ------------------------------------------------------------ 名前・形
    def test_pack_name_and_title(self):
        self.assertEqual(inbox.pack_name(os.path.join("a", "b", "題名_pack")), "題名_pack")
        self.assertEqual(inbox.pack_name("a*b?c.zip"), "a_b_c.zip")
        self.assertEqual(inbox.pack_name('x"<|>y'), "x____y")
        self.assertEqual(len(inbox.pack_name("a" * 300)), inbox.NAME_MAX)
        self.assertEqual(inbox.pack_name(None), "")
        self.assertEqual(inbox.pack_title("【雑談】テスト_pack"), "【雑談】テスト")
        self.assertEqual(inbox.pack_title("_pack"), "_pack")
        self.assertEqual(inbox.pack_title("ふつうの名前"), "ふつうの名前")

    def test_case_of(self):
        path = os.path.join(self.cases, "案件-1", "作業用", "runs", "abc.json")
        self.assertEqual(os.path.abspath(inbox.case_of(path)), os.path.abspath(os.path.join(self.cases, "案件-1")))
        self.assertIsNone(inbox.case_of(os.path.join(self.cases, "案件-1", "作業用", "abc.json")))
        self.assertIsNone(inbox.case_of(""))
        self.assertIsNone(inbox.case_of(None))

    # ------------------------------------------------------------ 送る
    def test_add_puts_sent_row_on_top(self):
        self.box.add(RID, {"top": 3}, {"url": "u"}, run_id="r1")
        r = self.box.add(RID2, {"top": 5}, {"url": "v"}, run_id="r2")
        self.assertEqual(self.box.rows[0]["id"], RID2)
        self.assertIs(self.box.row(RID2), r)
        self.assertEqual(r["state"], "sent")
        self.assertEqual(r["kind"], "url")
        self.assertEqual(r["packs"], [])
        self.assertEqual(r["groups"], [])
        self.assertEqual(r["runId"], "r2")
        self.assertEqual(r["createdAt"], int(T0 * 1000))

    def test_add_refuses_bad_id(self):
        for bad in ("", None, "../x", "a b", "x" * 65):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.box.add(bad, {}, {}, run_id="r")

    def test_making_only_from_sent(self):
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.making("r1")
        self.assertEqual(self.box.row(RID)["state"], "making")
        self.box.making("nope")   # 無い実行は何もしない

    def test_finished_with_packs_arrives_and_groups(self):
        names = ["a_pack", "b_pack", "c_pack", "d_pack", "e_pack"]
        self.clock.t = T0 + 100
        r, case, dirs = self.arrive(RID, names)
        self.assertEqual(r["state"], "arrived")
        self.assertEqual(r["arrivedAt"], int((T0 + 100) * 1000))
        self.assertEqual(r["case"], case)
        self.assertEqual([p["name"] for p in r["packs"]], names)
        self.assertEqual([p["title"] for p in r["packs"]], ["a", "b", "c", "d", "e"])
        self.assertEqual(r["packs"][0]["seconds"], 10.5)
        self.assertEqual(r["packs"][0]["dir"], dirs[0])
        # 1 本ずつ(C-3-1)
        self.assertEqual([(g["n"], g["names"]) for g in r["groups"]], [(i + 1, [n]) for i, n in enumerate(names)])
        self.assertTrue(all(g["preview"] is None for g in r["groups"]))
        # 配信ごとの通し番号と届いた時刻(3 日を数える)が付く
        self.assertEqual([p["num"] for p in r["packs"]], [1, 2, 3, 4, 5])
        self.assertEqual({p["key"] for p in r["packs"]}, {"v:dQw4w9WgXcQ"})
        self.assertEqual({p["arrivedAt"] for p in r["packs"]}, {int((T0 + 100) * 1000)})

    def test_finished_skips_missing_dirs(self):
        self.box.add(RID, {}, {}, run_id="r1")
        case, dirs = self.make_case(RID, ["a_pack"])
        r = self.box.finished("r1", "done", "", [{"dir": dirs[0]}, {"dir": os.path.join(case, "無い_pack")}, {"dir": None}], case=case)
        self.assertEqual([p["name"] for p in r["packs"]], ["a_pack"])
        self.assertEqual(r["state"], "arrived")

    def test_finished_cancelled_without_packs_removes_row(self):
        """[取り消す] で止めた(届いた物なし)= 行ごと消す(C-2-14)"""
        self.assertIsNone(self.failed_row(RID, state="cancelled"))
        self.assertIsNone(self.box.row(RID))
        # 取り消した印のある行は、何の状態で終わっても消す
        self.box.add(RID2, {}, {}, run_id="r9")
        self.box.row(RID2)["cancelled"] = True
        self.assertIsNone(self.box.finished("r9", "error", "x", []))
        self.assertIsNone(self.box.row(RID2))

    def test_finished_without_packs_fails_with_reason(self):
        r = self.failed_row(RID, state="error")
        self.assertEqual(r["state"], "failed")
        self.assertIn("パックができませんでした", r["error"])
        self.assertEqual(r["failedAt"], int(T0 * 1000))
        r2 = self.failed_row(RID2, state="error", error="ffmpeg が落ちました")
        self.assertEqual(r2["error"], "ffmpeg が落ちました")
        self.box.add("20250615-120200-cccccc", {}, {}, run_id="r3")
        r3 = self.box.finished("r3", "error", "", [])
        self.assertEqual(r3["state"], "failed")
        self.assertIn("パックができませんでした", r3["error"])

    def test_finished_unknown_run_is_none(self):
        self.assertIsNone(self.box.finished("nobody", "done", "", []))

    def test_set_preview(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.set_preview(RID, 2, "/x/preview2.mp4")
        self.assertEqual(self.box.row(RID)["groups"][1]["preview"], "/x/preview2.mp4")
        self.box.set_preview(RID, 9, "/x/none.mp4")   # 無い組は何もしない
        self.box.set_preview("nope", 1, "/x/none.mp4")
        self.assertIsNone(self.box.row(RID)["groups"][0]["preview"])

    # ------------------------------------------------------------ 決める
    def test_decide_keep_moves_to_save_and_writes_verdict(self):
        r, case, dirs = self.arrive(RID, ["【雑談】テスト_pack"])
        self.box.opened(RID, "【雑談】テスト_pack")   # 初めて再生した時刻(作業の時刻 D。2 回目は変えない)
        first = self.box.row(RID)["packs"][0]["openedAt"]
        self.box.opened(RID, "【雑談】テスト_pack")
        self.assertEqual(self.box.row(RID)["packs"][0]["openedAt"], first)
        got = self.box.decide(RID, [], "keep")
        self.assertEqual(got["done"], ["【雑談】テスト_pack"])
        self.assertEqual(got["errors"], [])
        self.assertFalse(os.path.exists(dirs[0]))
        # 保存先 = <保存先>\<配信の日付>_<配信者>_<題>\#番号(C-3-8。この行は配信者なし・題は行の題)
        saved = self.kept_path("%s_題" % iso_day(T0), 1)
        self.assertTrue(os.path.isdir(saved))
        self.assertEqual(got["row"]["packs"][0]["savedTo"], saved)
        self.assertEqual(got["row"]["packs"][0]["verdict"], "keep")
        v = self.read_verdict(RID, "【雑談】テスト_pack")
        self.assertEqual(v.pop("id").__class__, str)
        self.assertEqual((v.pop("arrivedAt"), v.pop("openedAt")), (int(T0 * 1000), first))   # 届いた・初めて再生した(D)
        self.assertEqual(v, {"v": 2, "judge": "good", "zip": "【雑談】テスト_pack", "origin": "request", "at": int(T0 * 1000), "videoId": "dQw4w9WgXcQ", "score": None})   # 点を選ばなかった = 空(10-27)
        self.assertEqual(self.box.saved_dir(RID, "【雑談】テスト_pack"), saved)

    def test_local_pack_verdict_carries_source_and_user_pc_reads_it(self):
        """この PC で処理したパックの判定に、元の配信の ID・区間・候補の印・版と設定が載り、ユーザーの PC の受け取りが人の判断の記録にそのまま残す(10-27 の通し)"""
        from human import judgments as J
        from human.friend import returns as R
        src = {"videoId": "dQw4w9WgXcQ", "markId": "a1", "range": [120.0, 165.5], "cand": {"rank": 3, "score": 4.2, "origin": "heatmap"},
               "tool": {"version": "0.99.307", "settings": {"count": 8, "wAudio": 1.0, "sensitivity": "normal"}}}
        self.box.add(RID, {"url": "u", "videoId": "dQw4w9WgXcQ"}, {"url": "u", "videoId": "dQw4w9WgXcQ", "title": "題"}, run_id="run-x")
        case, dirs = self.make_case(RID, ["【雑談】テスト_pack"])
        self.box.finished("run-x", "done", "", [{"dir": dirs[0], "seconds": 10.5, "info": dict(src, overlapNote="")}], case=case)
        self.box.decide(RID, [], "keep")
        v = self.read_verdict(RID, "【雑談】テスト_pack")
        self.assertEqual({k: v.get(k) for k in src}, src)
        sync = os.path.join(self.tmp, "Dropbox")
        app = os.path.join(self.tmp, "userapp")
        os.makedirs(os.path.join(sync, R.IN_DIR))
        for f in self.verdict_files(RID, "【雑談】テスト_pack"):
            shutil.copy(f, os.path.join(sync, R.IN_DIR, os.path.basename(f)))
            os.utime(os.path.join(sync, R.IN_DIR, os.path.basename(f)), (T0 - 600, T0 - 600))
        R.scan(sync, app, log=lambda m: None)
        row = J.rows(app)[-1]   # 届けた記録が無い = 判定の元を使う
        self.assertEqual((row["what"], row["videoId"], row["markId"], row["start"], row["end"], row["cand"], row["tool"]),
                         ("good", "dQw4w9WgXcQ", "a1", 120.0, 165.5, src["cand"], src["tool"]))
        old = R.parse_verdict(json.dumps({"v": 2, "id": "o1", "judge": "good", "at": 5}).encode())   # 古い形もそのまま読める
        self.assertEqual(old["judge"], "good")
        self.assertNotIn("cand", old)

    def test_decide_with_score_and_user_pc_keeps_it(self):
        """5 段階の点(10-27): 判定に score(1〜5)・選ばなければ null・範囲外は断る。ユーザーの PC の受け取りが人の判断の記録に score を残す"""
        from human import judgments as J
        from human.friend import returns as R
        self.arrive(RID, ["【雑談】テスト_pack", "【雑談】二本目_pack"])
        with self.assertRaises(ValueError):
            self.box.decide(RID, ["【雑談】テスト_pack"], "keep", score=6)
        self.box.decide(RID, ["【雑談】テスト_pack"], "keep", score=4)
        self.box.decide(RID, ["【雑談】二本目_pack"], "skip")
        self.assertEqual(self.read_verdict(RID, "【雑談】テスト_pack")["score"], 4)
        self.assertIsNone(self.read_verdict(RID, "【雑談】二本目_pack")["score"])
        sync, app = os.path.join(self.tmp, "Dropbox"), os.path.join(self.tmp, "userapp")
        os.makedirs(os.path.join(sync, R.IN_DIR))
        for name in ("【雑談】テスト_pack", "【雑談】二本目_pack"):
            for f in self.verdict_files(RID, name):
                shutil.copy(f, os.path.join(sync, R.IN_DIR, os.path.basename(f)))
                os.utime(os.path.join(sync, R.IN_DIR, os.path.basename(f)), (T0 - 600, T0 - 600))
        R.scan(sync, app, log=lambda m: None)
        self.assertEqual(sorted((r["what"], r.get("score", "なし")) for r in J.rows(app)), [("good", 4), ("unknown", None)])

    def test_decide_skip_moves_to_trash_and_writes_verdict(self):
        r, case, dirs = self.arrive(RID, ["a_pack", "b_pack"])
        got = self.box.decide(RID, ["a_pack"], "skip")
        self.assertEqual(got["done"], ["a_pack"])
        trash_day = os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0))
        self.assertTrue(os.path.isdir(os.path.join(trash_day, "a_pack")))
        self.assertFalse(os.path.exists(dirs[0]))
        self.assertEqual(got["row"]["packs"][0]["verdict"], "skip")
        self.assertEqual(self.read_verdict(RID, "a_pack")["judge"], "unknown")
        self.assertNotIn("by", self.read_verdict(RID, "a_pack"))
        self.assertEqual(self.verdict_files(RID, "b_pack"), [])

    def test_decide_bad_needs_reason_and_writes_it(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        for bad in (None, "", "other", "つまらない"):
            with self.subTest(reason=bad), self.assertRaises(ValueError):
                self.box.decide(RID, ["a_pack"], "bad", reason=bad)
        self.assertEqual(self.verdict_files(RID, "a_pack"), [])
        self.box.decide(RID, ["a_pack"], "bad", reason="boring")
        self.box.decide(RID, ["b_pack"], "bad", reason="cut")
        self.assertEqual((self.read_verdict(RID, "a_pack")["judge"], self.read_verdict(RID, "a_pack")["reason"]), ("bad", "boring"))
        self.assertEqual(self.read_verdict(RID, "b_pack")["reason"], "cut")
        p = self.box.row(RID)["packs"][0]
        self.assertEqual((p["verdict"], p["reason"]), ("bad", "boring"))
        self.assertTrue(os.path.isdir(p["trash"]))   # 見送ると同じにごみ箱へ(3 日は戻せる)

    def test_decide_reason_only_kept_for_bad(self):
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "skip", reason="boring")
        self.assertNotIn("reason", self.read_verdict(RID, "a_pack"))
        self.assertIsNone(self.box.row(RID)["packs"][0]["reason"])

    def test_verdict_files_never_overwrite_each_other(self):
        """同じ切り抜きの判断・取り消しは ~<at> で別のファイル(同じ ms でも)"""
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "skip")
        self.box.undo(RID, ["a_pack"])
        self.box.decide(RID, [], "skip")
        files = self.verdict_files(RID, "a_pack")
        self.assertEqual(len(files), 3)
        ats = [os.path.basename(f).split("~")[1][:13] for f in files]
        self.assertEqual(len(set(ats)), 3)
        self.assertTrue(all(len(a) == 13 and a.isdigit() for a in ats))

    def test_decide_names_limits_to_chosen_packs(self):
        self.arrive(RID, ["a_pack", "b_pack", "c_pack"])
        got = self.box.decide(RID, ["b_pack", "zzz_pack"], "keep")
        self.assertEqual(got["done"], ["b_pack"])
        row = self.box.row(RID)
        self.assertEqual(row["state"], "arrived")
        self.assertEqual([p["verdict"] for p in row["packs"]], [None, "keep", None])
        self.assertEqual(sum(1 for p in row["packs"] if not p["verdict"]), 2)

    def test_decide_all_closes_row_and_keeps_case_until_sweep(self):
        """全部決めた行は done。案件のフォルダは決めた時には動かさず(2 回目の依頼で失敗しないよう)、最後に決めてから 3 日で片付く(C-3-7)"""
        r, case, dirs = self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.assertEqual(self.box.row(RID)["state"], "arrived")
        self.assertTrue(os.path.isdir(case))
        self.clock.t = T0 + 60
        got = self.box.decide(RID, [], "skip")
        self.assertEqual(got["done"], ["b_pack"])
        row = self.box.row(RID)
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["doneAt"], int((T0 + 60) * 1000))
        self.assertTrue(os.path.isdir(case))
        self.clock.t = T0 + 60 + 3 * 86400
        self.box.sweep()
        self.assertFalse(os.path.exists(case))
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0 + 60 + 3 * 86400), "案件-" + RID)))
        self.assertIsNone(self.box.row(RID))

    def test_decide_numbers_continue_in_the_same_stream(self):
        """同じ配信の 2 回目の依頼は番号の続き・保存先の直下に平らに並ぶ(配信のフォルダは作らない)。同じ名前の物が既にあれば末尾に -xxxx"""
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "keep")
        self.arrive(RID2, ["a_pack"])
        got = self.box.decide(RID2, [], "keep")
        folder = "%s_題" % iso_day(T0)
        self.assertEqual(got["row"]["packs"][0]["savedTo"], self.kept_path(folder, 2))
        self.assertTrue(os.path.isdir(self.kept_path(folder, 1)))
        # 先に同じ名前の物があれば -xxxx
        self.arrive("20250615-120200-cccccc", ["a_pack"], vid="aaaaaaaaaaa")   # 別の配信 = 番号は 1 から → 同じフォルダの #1 とぶつかる
        got = self.box.decide("20250615-120200-cccccc", [], "keep")
        saved = got["row"]["packs"][0]["savedTo"]
        self.assertEqual(os.path.dirname(saved), self.save)
        self.assertTrue(os.path.basename(saved).startswith("%s_#1-" % folder))
        self.assertTrue(os.path.isdir(saved))

    def test_old_stream_folder_still_opens(self):
        """0.99.169 までの形(<保存先>\\<日付>_<題>\\#番号)で受け取った物も開ける(置き場所は記録 savedTo で読む。受け取った物は戻す・片付けの対象外)"""
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "keep")
        p = self.box.row(RID)["packs"][0]
        old = os.path.join(self.save, "%s_題" % iso_day(T0), "#1")
        os.makedirs(os.path.dirname(old))
        shutil.move(p["savedTo"], old)
        p["savedTo"] = old   # 前の版が書いた記録の形
        self.assertEqual(self.box.saved_dir(RID, "a_pack"), old)
        self.arrive(RID2, ["a_pack"])   # 同じ配信の次の 1 本は、前の形のフォルダに混ぜず直下に平らに
        self.box.decide(RID2, [], "keep")
        self.assertEqual(self.box.row(RID2)["packs"][0]["savedTo"], self.kept_path("%s_題" % iso_day(T0), 2))

    def test_keep_dest_uses_streamer_title_cut_and_safe_name(self):
        """<日付>_<配信者>_<題 40 文字>_#番号(使えない文字は _)を保存先の直下に。日付は配信が始まった日(一覧の写し)"""
        start = datetime.datetime(2025, 1, 2, 3, 4).timestamp()
        self.box.stream_info = lambda vid: {"title": "一覧の題", "streamer": "一覧の人", "startAt": int(start * 1000)} if vid == "dQw4w9WgXcQ" else None
        title = "a/b:c" + "あ" * 60
        self.arrive(RID, ["a_pack"], title=title, streamer="配信者")
        r = self.box.row(RID)
        folder, name = self.box.keep_dest(r, r["packs"][0])
        self.assertEqual((folder, name), (self.save, "2025-01-02_配信者_a_b_c" + "あ" * 35 + "_#1"))
        # 行に題も配信者も無ければ一覧の写しから
        self.arrive(RID2, ["b_pack"], title="", streamer="")
        r2 = self.box.row(RID2)
        self.assertEqual(self.box.keep_dest(r2, r2["packs"][0]), (self.save, "2025-01-02_一覧の人_一覧の題_#2"))

    def test_decide_error_is_reported_and_not_decided(self):
        for verdict, exc, said in (("keep", PermissionError("denied"), "保存先へ移せませんでした"), ("skip", OSError("busy"), "片付けられませんでした")):
            with self.subTest(verdict=verdict):
                rid = RID if verdict == "keep" else RID2
                self.arrive(rid, ["a_pack"])
                with mock.patch("friendapp.inbox.shutil.move", side_effect=exc):
                    got = self.box.decide(rid, [], verdict)
                self.assertEqual(got["done"], [])
                self.assertEqual([e["name"] for e in got["errors"]], ["a_pack"])
                self.assertIn(said, got["errors"][0]["message"])
                self.assertIn(type(exc).__name__, got["errors"][0]["message"])
                row = self.box.row(rid)
                self.assertEqual(row["state"], "arrived")
                self.assertIsNone(row["packs"][0]["verdict"])
                self.assertEqual(self.verdict_files(rid, "a_pack"), [])

    def test_decide_record_failure_puts_the_pack_back(self):
        """移したあとに判断の記録が書けない: 移した物を元の場所へ戻して「決めていない」のまま(もう一度押せば決まる。ごみ箱に残って日付で消えない)"""
        for verdict in ("skip", "keep"):
            with self.subTest(verdict=verdict):
                rid = RID if verdict == "skip" else RID2
                r, case, dirs = self.arrive(rid, ["a_pack"])
                with mock.patch.object(self.box, "_record", side_effect=PermissionError("denied")):
                    got = self.box.decide(rid, [], verdict)
                self.assertEqual((got["done"], [e["name"] for e in got["errors"]]), ([], ["a_pack"]))
                p = self.box.row(rid)["packs"][0]
                self.assertEqual((p["verdict"], p.get("trash"), p.get("savedTo")), (None, None, None))
                self.assertTrue(os.path.isdir(dirs[0]), "元の場所へ戻る")
                got = self.box.decide(rid, [], verdict)   # もう一度押すと決まる
                self.assertEqual(got["done"], ["a_pack"])

    def test_decide_record_failure_after_auto_removal_still_decides(self):
        """3 日の自動(すぐ消す)は戻せないので、記録が書けなくても決めたことにする(戻せない物を「決めていない」で残さない)"""
        r, case, dirs = self.arrive(RID, ["a_pack"])
        with mock.patch.object(self.box, "_record", side_effect=PermissionError("denied")):
            got = self.box.decide(RID, [], "skip", by="auto")
        self.assertEqual(got["done"], ["a_pack"])
        self.assertEqual(self.box.row(RID)["packs"][0]["verdict"], "skip")

    def test_summary_counts_undecided_and_decided_7d(self):
        """状態の書き出しの受け取るの箱の要約: 未決めの数・一番古い届いた時刻・直近 7 日に決めた数(keep/skip/bad/auto 別。読み直しても残る・7 日で落ちる。10-26)"""
        self.arrive(RID, ["a_pack", "b_pack", "c_pack"])
        self.clock.t = T0 + 60
        self.box.decide(RID, ["a_pack"], "keep")
        self.box.decide(RID, ["b_pack"], "skip", by="auto")
        s = self.box.summary()
        self.assertEqual((s["undecided"], s["decided7d"]), (1, {"keep": 1, "skip": 0, "bad": 0, "auto": 1}))
        self.assertIsInstance(s["oldestArrivedAt"], int)
        self.assertEqual(self.new_box().summary()["decided7d"]["auto"], 1)       # 読み直しても残る
        self.clock.t = T0 + 8 * 86400
        self.assertEqual(sum(self.box.summary()["decided7d"].values()), 0)      # 7 日より前は数えない

    def test_decide_missing_pack_dir_is_error(self):
        r, case, dirs = self.arrive(RID, ["a_pack"])
        shutil.rmtree(dirs[0])
        got = self.box.decide(RID, [], "keep")
        self.assertEqual(got["done"], [])
        self.assertEqual(got["errors"][0]["name"], "a_pack")

    def test_decide_refuses_bad_verdict_and_wrong_state(self):
        self.arrive(RID, ["a_pack"])
        with self.assertRaises(ValueError):
            self.box.decide(RID, [], "video")
        with self.assertRaises(KeyError):
            self.box.decide("nope", [], "keep")
        self.box.add(RID2, {}, {}, run_id="r9")   # まだ届いていない(sent)
        with self.assertRaises(KeyError):
            self.box.decide(RID2, [], "keep")

    def test_decide_with_auto_marks_verdict_and_removes_at_once(self):
        """3 日の自動は見送る(理由なし・by auto)。ごみ箱を経ずにすぐ消す"""
        r, case, dirs = self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "skip", by="auto")
        v = self.read_verdict(RID, "a_pack")
        self.assertEqual((v["judge"], v["by"]), ("unknown", "auto"))
        self.assertFalse(os.path.exists(dirs[0]))
        self.assertFalse(os.path.exists(os.path.join(self.cases, inbox.TRASH_NAME)))
        self.assertEqual(self.box.row(RID)["packs"][0]["by"], "auto")

    def test_decide_auto_leaves_a_pack_being_received(self):
        """受け取っている途中(want keep)の Dropbox のパックは自動で見送らない"""
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.row(RID)["packs"][0]["want"] = "keep"
        got = self.box.decide(RID, [], "skip", by="auto")
        self.assertEqual(got["done"], ["b_pack"])
        self.assertIsNone(self.box.row(RID)["packs"][0]["verdict"])

    def test_decide_dropbox_pack(self):
        """まだ手元に無い Dropbox のパック: 受け取るは「受け取っています」にするだけ・見送る / 届かなくてよかったは取らずに決める"""
        self.box.add(RID, {}, {}, run_id="r1")
        r = self.box.import_remote(RID, "request", "題", [{"packs": [{"zip": "%s__a.zip" % RID, "title": "a", "info": {"videoId": "dQw4w9WgXcQ"}},
                                                                    {"zip": "%s__b.zip" % RID, "title": "b"}]}])
        names = [p["name"] for p in r["packs"]]
        got = self.box.decide(RID, [names[0]], "keep")
        self.assertEqual((got["done"], got["pending"]), ([], [names[0]]))
        self.assertEqual(self.box.row(RID)["packs"][0]["want"], "keep")
        self.assertEqual(self.verdict_files(RID, names[0]), [])
        got = self.box.decide(RID, [names[1]], "bad", reason="cut")
        self.assertEqual(got["done"], [names[1]])
        v = self.read_verdict(RID, names[1])
        self.assertEqual((v["judge"], v["reason"], v["zip"]), ("bad", "cut", "%s__b.zip" % RID))

    # ------------------------------------------------------------ 3 日の片付け
    def test_left_days(self):
        self.arrive(RID, ["a_pack"])
        self.failed_row(RID2)
        self.assertEqual(self.box.left_days(self.box.row(RID)), 3)
        self.clock.t = T0 + 86400 + 5
        self.assertEqual(self.box.left_days(self.box.row(RID)), 2)
        self.assertEqual(self.box.left_days(self.box.row(RID2)), 2)
        self.clock.t = T0 + 3 * 86400
        self.assertEqual(self.box.left_days(self.box.row(RID)), 0)
        self.assertIsNone(self.box.left_days({"state": "sent"}))

    def test_sweep_auto_skips_after_three_days_and_notices(self):
        r, case, dirs = self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.clock.t = T0 + 3 * 86400 - 1
        self.assertEqual(self.box.sweep(), 0)
        self.assertEqual(self.box.row(RID)["state"], "arrived")
        self.assertIsNone(self.box.notice)
        self.clock.t = T0 + 3 * 86400
        self.assertEqual(self.box.sweep(), 1)
        row = self.box.row(RID)
        self.assertEqual(row["state"], "done")
        self.assertEqual(self.read_verdict(RID, "b_pack")["by"], "auto")
        self.assertEqual(self.read_verdict(RID, "b_pack")["judge"], "unknown")
        self.assertNotIn("by", self.read_verdict(RID, "a_pack"))
        self.assertFalse(os.path.exists(dirs[1]))   # すぐ消す(ごみ箱を経ない)
        self.assertFalse(os.path.exists(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0 + 3 * 86400), "b_pack")))
        # 画面に出す 1 行の知らせ(「3 日たった n 本を片付けました」。見たら消える)
        self.assertEqual(self.box.notice, {"n": 1, "at": int((T0 + 3 * 86400) * 1000)})
        self.assertEqual(self.new_box().notice["n"], 1)
        self.assertEqual(self.box.receive_view()["notice"]["n"], 1)
        self.box.notice_seen()
        self.assertIsNone(self.box.notice)
        self.assertIsNone(self.new_box().notice)

    def test_sweep_drops_preview_three_days_after_skip(self):
        """見送って 3 日たった物の確認用の動画を消す(戻せる間は残す)。受け取った物の動画は決めた時に消える"""
        self.arrive(RID, ["a_pack", "b_pack", "c_pack"])
        prev = {}
        for n in ("a_pack", "b_pack", "c_pack"):
            prev[n] = os.path.join(self.tmp, n + ".mp4")
            with open(prev[n], "wb") as f:
                f.write(b"v")
            [p for p in self.box.row(RID)["packs"] if p["name"] == n][0]["preview"] = prev[n]
        self.box.decide(RID, ["a_pack"], "skip")
        self.box.decide(RID, ["c_pack"], "keep")
        self.assertTrue(os.path.isfile(prev["a_pack"]))
        self.assertFalse(os.path.exists(prev["c_pack"]))
        for p in self.box.row(RID)["packs"]:   # b は後から届いた扱い(自動で見送られない)
            if p["name"] == "b_pack":
                p["arrivedAt"] = int((T0 + 5 * 86400) * 1000)
        self.clock.t = T0 + 3 * 86400 - 1
        self.box.sweep()
        self.assertTrue(os.path.isfile(prev["a_pack"]))
        self.clock.t = T0 + 3 * 86400
        self.box.sweep()
        self.assertFalse(os.path.exists(prev["a_pack"]))
        self.assertTrue(os.path.isfile(prev["b_pack"]))

    def test_sweep_removes_failed_after_three_days_and_trashes_case(self):
        case, dirs = self.make_case(RID, ["a_pack"])
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.finished("r1", "error", "x", [], case=case)
        self.clock.t = T0 + 3 * 86400 - 1
        self.assertEqual(self.box.sweep(), 0)
        self.assertEqual(self.box.row(RID)["state"], "failed")
        self.assertTrue(os.path.isdir(case))
        self.clock.t = T0 + 3 * 86400
        self.box.sweep()
        self.assertIsNone(self.box.row(RID))
        self.assertFalse(os.path.exists(case))
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0 + 3 * 86400), "案件-" + RID)))

    def test_sweep_removes_done_after_three_days(self):
        r, case, dirs = self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "keep")
        self.assertEqual(self.box.row(RID)["state"], "done")
        self.clock.t = T0 + 3 * 86400 - 10
        self.box.sweep()
        self.assertIsNotNone(self.box.row(RID))
        self.assertTrue(os.path.isdir(case))
        self.clock.t = T0 + 3 * 86400 + 10
        self.box.sweep()
        self.assertIsNone(self.box.row(RID))
        self.assertFalse(os.path.exists(case))   # 決めて 3 日の行の案件のフォルダはごみ箱へ
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0 + 3 * 86400 + 10), "案件-" + RID)))

    def test_sweep_purges_old_trash_days(self):
        trash = os.path.join(self.cases, inbox.TRASH_NAME)
        old = trashbin.day_name(T0 - 4 * 86400)
        edge = trashbin.day_name(T0 - 3 * 86400)
        fresh = trashbin.day_name(T0)
        for d in (old, edge, fresh, "memo"):
            os.makedirs(os.path.join(trash, d, "x"))
        self.box.sweep()
        self.assertFalse(os.path.exists(os.path.join(trash, old)))
        self.assertTrue(os.path.isdir(os.path.join(trash, edge)))
        self.assertTrue(os.path.isdir(os.path.join(trash, fresh)))
        self.assertTrue(os.path.isdir(os.path.join(trash, "memo")))

    # ------------------------------------------------------------ 画面へ
    def test_view_hides_done_and_dir(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.failed_row(RID2)
        self.box.add("20250615-120300-dddddd", {}, {}, run_id="r4")
        rows = self.box.view()
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, ["20250615-120300-dddddd", RID2, RID])
        arrived = rows[2]
        self.assertEqual(arrived["undecided"], 1)
        self.assertEqual(arrived["left"], 3)
        self.assertTrue(all("dir" not in p for p in arrived["packs"]))
        self.assertIsNone(rows[0]["left"])
        self.assertEqual(rows[1]["left"], 3)
        self.assertIn("dir", self.box.row(RID)["packs"][0])   # 中の記録は消さない

    def test_view_status_of_only_for_sent_or_making(self):
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.add(RID2, {}, {}, run_id="r2")
        self.box.making("r2")
        self.arrive("20250615-120400-eeeeee", ["a_pack"], run_id="r3")
        seen = []

        def status_of(run_id):
            seen.append(run_id)
            return {"state": "running", "message": "進んでいます"} if run_id == "r2" else None

        rows = self.box.view(status_of=status_of)
        self.assertEqual(sorted(seen), ["r1", "r2"])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[RID2]["run"], {"state": "running", "message": "進んでいます"})
        self.assertIsNone(by_id[RID]["run"])
        self.assertNotIn("run", by_id["20250615-120400-eeeeee"])

    # ------------------------------------------------------------ retry・remove・記録
    def test_resent_puts_failed_row_back_to_sent(self):
        self.failed_row(RID, error="x")
        r = self.box.resent(RID, "newrun")
        self.assertEqual(r["state"], "sent")
        self.assertEqual(r["runId"], "newrun")
        self.assertEqual(r["error"], "")
        self.assertIsNone(r["failedAt"])
        self.assertEqual(self.box.by_run("newrun")["id"], RID)
        with self.assertRaises(KeyError):
            self.box.resent("nope", "r")

    def test_remove_only_failed_and_trashes_case(self):
        case, dirs = self.make_case(RID, ["a_pack"])
        self.box.add(RID, {}, {}, run_id="r1")
        self.box.finished("r1", "error", "x", [], case=case)
        self.box.remove(RID)
        self.assertIsNone(self.box.row(RID))
        self.assertFalse(os.path.exists(case))
        self.assertTrue(os.path.isdir(os.path.join(self.cases, inbox.TRASH_NAME, day_of(T0), "案件-" + RID)))
        self.arrive(RID2, ["b_pack"])
        with self.assertRaises(KeyError):
            self.box.remove(RID2)
        with self.assertRaises(KeyError):
            self.box.remove("nope")

    def test_rows_persist_and_reload(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "keep")
        self.failed_row(RID2, error="止め")
        again = self.new_box()
        self.assertEqual([r["id"] for r in again.rows], [RID2, RID])
        row = again.row(RID)
        self.assertEqual(row["state"], "arrived")
        self.assertEqual(row["packs"][0]["verdict"], "keep")
        self.assertEqual(row["packs"][1]["verdict"], None)
        self.assertEqual(len(row["groups"]), 2)
        self.assertEqual(again.row(RID2)["error"], "止め")
        self.assertEqual(again.view()[1]["undecided"], 1)

    def test_load_drops_bad_rows_and_other_version(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        good = {"id": RID, "state": "failed", "failedAt": int(T0 * 1000)}
        bad_id = {"id": "../x", "state": "failed"}
        bad_state = {"id": RID2, "state": "weird"}
        testkit.write_json(self.path, {"v": inbox.V, "rows": [good, bad_id, bad_state, "text"]})
        self.assertEqual([r["id"] for r in self.new_box().rows], [RID])
        testkit.write_json(self.path, {"v": 99, "rows": [good]})
        self.assertEqual(self.new_box().rows, [])
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ こわれた")
        self.assertEqual(self.new_box().rows, [])

    def test_load_numbers_packs_without_num(self):
        """番号の無いパックは読んだときに番号が付く"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        row = {"id": RID, "state": "arrived", "kind": "url", "origin": "request", "arrivedAt": int(T0 * 1000), "createdAt": int(T0 * 1000),
               "source": {"videoId": "dQw4w9WgXcQ", "title": "題"}, "form": {}, "groups": [], "error": "", "note": "",
               "packs": [{"name": "a_pack", "title": "a", "dir": None, "verdict": "skip", "at": int(T0 * 1000), "by": None},
                         {"name": "b_pack", "title": "b", "dir": None, "verdict": None, "at": None, "by": None},
                         {"name": "c_pack", "title": "c", "dir": None, "verdict": "keep", "at": None, "by": None}]}
        testkit.write_json(self.path, {"v": inbox.V, "rows": [row]})
        again = self.new_box()
        ps = again.row(RID)["packs"]
        self.assertEqual([p["verdict"] for p in ps], ["skip", None, "keep"])
        self.assertEqual([p["num"] for p in ps], [1, 2, 3])
        self.assertEqual({p["key"] for p in ps}, {"v:dQw4w9WgXcQ"})
        self.assertEqual({p["arrivedAt"] for p in ps}, {int(T0 * 1000)})
        self.assertEqual(again.nums, {"v:dQw4w9WgXcQ": 3})
        # 次に届いた物は続きの番号
        again.add(RID2, {}, {"videoId": "dQw4w9WgXcQ"}, run_id="r2")
        case, dirs = self.make_case(RID2, ["d_pack"])
        r2 = again.finished("r2", "done", "", [{"dir": dirs[0]}], case=case)
        self.assertEqual(r2["packs"][0]["num"], 4)

    # ------------------------------------------------------------ 配信ごとの通し番号(C-3-2)
    def test_numbers_continue_per_stream_and_are_not_reused(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.arrive(RID2, ["c_pack"])   # 同じ配信の 2 回目の依頼 = 続き
        self.assertEqual([p["num"] for p in self.box.row(RID)["packs"]], [1, 2])
        self.assertEqual([p["num"] for p in self.box.row(RID2)["packs"]], [3])
        other = self.arrive("20250615-120200-cccccc", ["d_pack"], vid="aaaaaaaaaaa")[0]   # 別の配信は 1 から
        self.assertEqual(other["packs"][0]["num"], 1)
        # 見送って行ごと消えても番号は使い回さない
        self.box.decide(RID2, [], "skip")
        self.clock.t = T0 + 3 * 86400 + 10
        self.box.sweep()
        self.assertIsNone(self.box.row(RID2))
        self.clock.t = T0 + 4 * 86400
        self.arrive("20250615-120300-dddddd", ["e_pack"])
        self.assertEqual(self.box.row("20250615-120300-dddddd")["packs"][0]["num"], 4)
        # 開き直しても続き
        again = self.new_box()
        self.assertEqual(again.nums["v:dQw4w9WgXcQ"], 4)
        again.add("20250615-120400-eeeeee", {}, {"videoId": "dQw4w9WgXcQ"}, run_id="r5")
        case, dirs = self.make_case("20250615-120400-eeeeee", ["f_pack"])
        r = again.finished("r5", "done", "", [{"dir": dirs[0]}], case=case)
        self.assertEqual(r["packs"][0]["num"], 5)

    def test_number_key_falls_back_to_file_title_then_request(self):
        """配信の id が無い物: 動画ファイルは題ごと・それ以外は依頼ごと"""
        self.box.add(RID, {"title": "動画A"}, {"fileName": "a.mp4"}, run_id="r1", kind="file")
        case, dirs = self.make_case(RID, ["a_pack"])
        r = self.box.finished("r1", "done", "", [{"dir": dirs[0]}], case=case)
        self.assertEqual(r["packs"][0]["key"], "f:動画A")
        self.box.add(RID2, {}, {}, run_id="r2")
        case, dirs = self.make_case(RID2, ["b_pack"])
        r = self.box.finished("r2", "done", "", [{"dir": dirs[0]}], case=case)
        self.assertEqual(r["packs"][0]["key"], "r:" + RID2)

    # ------------------------------------------------------------ 受け取る画面(C-3)
    def test_receive_view_sections_order_numbers_and_skipped(self):
        # 配信 A(題 "配信A")に 2 本 → 配信 B に 1 本 → 配信 A にもう 1 本(最後に届いた時刻は A の方が新しい)
        self.clock.t = T0
        self.arrive(RID, ["a1_pack", "a2_pack"], vid="aaaaaaaaaaa", title="配信A", streamer="ぺこら")
        self.clock.t = T0 + 10
        self.arrive(RID2, ["b1_pack"], vid="bbbbbbbbbbb", title="配信B")
        self.clock.t = T0 + 20
        self.arrive("20250615-120200-cccccc", ["a3_pack"], vid="aaaaaaaaaaa", title="配信A", streamer="ぺこら")
        v = self.box.receive_view()
        self.assertEqual([s["videoId"] for s in v["sections"]], ["aaaaaaaaaaa", "bbbbbbbbbbb"])   # 最後に届いた時刻の新しい順
        a, b = v["sections"]
        self.assertEqual((a["title"], a["streamer"], a["arrived"], a["lastAt"]), ("配信A", "ぺこら", 3, int((T0 + 20) * 1000)))
        self.assertEqual([i["num"] for i in a["items"]], [1, 2, 3])   # 段の中は番号順
        self.assertEqual([i["name"] for i in a["items"]], ["a1_pack", "a2_pack", "a3_pack"])
        self.assertEqual([i["title"] for i in a["items"]], ["ぺこら|配信A #1", "ぺこら|配信A #2", "ぺこら|配信A #3"])   # 見出し(配信者|題 #番号)
        self.assertEqual(b["items"][0]["title"], "配信B #1")   # 配信者が分からなければ題 #番号
        self.assertEqual((a["making"], a["expect"], v["undecided"], v["skipped"], v["notice"]), (False, 0, 4, [], None))
        # 見送った物は 3 日の間 skipped に(段からは消える)・受け取った物はどこにも出ない
        self.clock.t = T0 + 30
        self.box.decide(RID, ["a1_pack"], "skip")
        self.box.decide(RID, ["a2_pack"], "keep")
        v = self.box.receive_view()
        self.assertEqual([i["name"] for i in v["sections"][0]["items"]], ["a3_pack"])
        self.assertEqual(v["undecided"], 2)
        self.assertEqual([(i["name"], i["verdict"], i["left"]) for i in v["skipped"]], [("a1_pack", "skip", 3)])
        self.assertEqual(v["skipped"][0]["title"], "ぺこら|配信A #1")
        self.clock.t = T0 + 30 + 2 * 86400 + 10
        self.assertEqual(self.box.receive_view()["skipped"][0]["left"], 1)
        self.clock.t = T0 + 30 + 3 * 86400
        self.assertEqual(self.box.receive_view()["skipped"], [])
        # 全部決めた配信の段は出ない
        self.box.decide(RID2, [], "keep")
        self.assertEqual([s["videoId"] for s in self.box.receive_view()["sections"]], ["aaaaaaaaaaa"])

    def test_receive_view_hides_auto_skipped_and_shows_bad_reason(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "skip", by="auto")
        self.box.decide(RID, ["b_pack"], "bad", reason="boring")
        v = self.box.receive_view()
        self.assertEqual([(i["name"], i["verdict"], i["reason"]) for i in v["skipped"]], [("b_pack", "bad", "boring")])   # 3 日の自動の物は出ない
        self.assertEqual(v["sections"], [])

    def test_receive_view_shows_expected_count_while_making(self):
        """まだ作っている依頼は、届いた数と待つ本数(区間の数か本数)を段に出す"""
        self.arrive(RID, ["a_pack"])
        r = self.box.row(RID)
        r.update(state="making", form={"top": 5, "videoId": "dQw4w9WgXcQ"})
        s = self.box.receive_view()["sections"][0]
        self.assertEqual((s["making"], s["expect"], s["arrived"]), (True, 5, 1))
        r["form"]["ranges"] = [[1, 5], [10, 20]]
        self.assertEqual(self.box.receive_view()["sections"][0]["expect"], 2)
        r["cancelled"] = True
        s = self.box.receive_view()["sections"][0]
        self.assertEqual((s["making"], s["expect"]), (False, 0))

    def test_receive_view_item_has_no_paths(self):
        self.arrive(RID, ["a_pack"])
        text = json.dumps(self.box.receive_view(), ensure_ascii=False)
        self.assertNotIn(self.tmp, text)

    # ------------------------------------------------------------ 戻す(C-3-6)
    def test_undo_restores_from_trash_and_writes_retract(self):
        r, case, dirs = self.arrive(RID, ["a_pack", "b_pack"])
        self.box.decide(RID, ["a_pack"], "bad", reason="cut")
        first = self.read_verdict(RID, "a_pack")
        self.assertFalse(os.path.exists(dirs[0]))
        self.clock.t = T0 + 86400
        got = self.box.undo(RID, ["a_pack", "b_pack"])   # 決めていない b は何もしない
        self.assertEqual((got["done"], got["errors"]), (["a_pack"], []))
        self.assertTrue(os.path.isdir(dirs[0]))   # ごみ箱から元の場所へ
        p = self.box.row(RID)["packs"][0]
        self.assertEqual((p["verdict"], p["reason"], p["at"], p["by"], p["trash"]), (None, None, None, None, None))
        self.assertEqual(p["arrivedAt"], int((T0 + 86400) * 1000))   # 戻した物にも 3 日
        rt = self.read_verdict(RID, "a_pack")
        self.assertEqual((rt["judge"], rt["of"]), ("retract", first["id"]))
        self.assertEqual(len(self.verdict_files(RID, "a_pack")), 2)
        self.assertNotIn("reason", rt)
        self.assertEqual(len(self.verdict_files(RID, "b_pack")), 0)

    def test_undo_reopens_a_done_row(self):
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "skip")
        self.assertEqual(self.box.row(RID)["state"], "done")
        self.clock.t = T0 + 100
        self.box.undo(RID, ["a_pack"])
        row = self.box.row(RID)
        self.assertEqual((row["state"], row["doneAt"], row["arrivedAt"]), ("arrived", None, int((T0 + 100) * 1000)))
        self.assertEqual(self.box.receive_view()["undecided"], 1)

    def test_undo_only_within_three_days_and_not_for_auto_or_keep(self):
        self.arrive(RID, ["a_pack", "b_pack", "c_pack"])
        self.box.decide(RID, ["a_pack"], "skip")
        self.box.decide(RID, ["b_pack"], "skip", by="auto")
        self.box.decide(RID, ["c_pack"], "keep")
        self.assertEqual(self.box.undo(RID, ["b_pack", "c_pack"])["done"], [])   # 3 日の自動の物・受け取った物は戻せない
        self.clock.t = T0 + 3 * 86400
        self.assertEqual(self.box.undo(RID, ["a_pack"])["done"], [])
        self.assertEqual(self.box.row(RID)["packs"][0]["verdict"], "skip")
        with self.assertRaises(KeyError):
            self.box.undo("nope", ["a_pack"])

    def test_undo_error_when_trash_is_gone(self):
        self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "skip")
        shutil.rmtree(os.path.join(self.cases, inbox.TRASH_NAME))
        got = self.box.undo(RID, ["a_pack"])
        self.assertEqual(got["done"], [])
        self.assertEqual(got["errors"][0]["name"], "a_pack")
        self.assertIn("戻せませんでした", got["errors"][0]["message"])
        self.assertEqual(self.box.row(RID)["packs"][0]["verdict"], "skip")
        self.assertEqual(len(self.verdict_files(RID, "a_pack")), 1)

    def test_undo_uses_new_place_when_original_is_taken(self):
        r, case, dirs = self.arrive(RID, ["a_pack"])
        self.box.decide(RID, [], "skip")
        os.makedirs(dirs[0])   # 元の場所に同じ名前が出来ていた
        self.box.undo(RID, ["a_pack"])
        p = self.box.row(RID)["packs"][0]
        self.assertNotEqual(p["dir"], dirs[0])
        self.assertTrue(os.path.isdir(p["dir"]))

    # ------------------------------------------------------------ 確認用の動画・取り消す・知らせた
    def test_pack_preview_from_pack_or_single_group(self):
        self.arrive(RID, ["a_pack", "b_pack"])
        self.assertIsNone(self.box.pack_preview(RID, "a_pack"))
        self.box.set_preview(RID, 2, "/x/b.mp4")   # 1 本ずつの枠の動画 = そのパックの確認用の動画
        self.assertEqual(self.box.pack_preview(RID, "b_pack"), "/x/b.mp4")
        self.assertEqual(self.box.row(RID)["packs"][1]["preview"], "/x/b.mp4")
        self.assertIsNone(self.box.pack_preview(RID, "zzz"))
        self.assertIsNone(self.box.pack_preview("nope", "a_pack"))

    def test_cancelled_removes_row_without_packs_else_keeps_arrived(self):
        self.box.add(RID, {}, {}, run_id="r1")
        self.assertIsNone(self.box.cancelled(RID))
        self.assertIsNone(self.box.row(RID))
        r, case, dirs = self.arrive(RID2, ["a_pack"])
        self.box.row(RID2).update(state="making")   # 作っている途中で 1 本届いていた
        self.clock.t = T0 + 5
        got = self.box.cancelled(RID2)
        self.assertEqual((got["state"], got["cancelled"]), ("arrived", True))
        self.assertEqual(len(got["packs"]), 1)

    def test_reported_marks_time_and_resent_clears_it(self):
        self.failed_row(RID, error="x")
        self.clock.t = T0 + 7
        self.assertEqual(self.box.reported(RID)["reportedAt"], int((T0 + 7) * 1000))
        with self.assertRaises(KeyError):
            self.box.reported("nope")
        self.assertIsNone(self.box.resent(RID, None)["reportedAt"])   # 友人が送り直した = また知らせられる
        self.box.fail(RID, "y")
        self.box.reported(RID)
        self.assertIsNotNone(self.box.resent(RID, None, auto=True)["reportedAt"])   # 自動のやり直しでは消さない

    def test_stage_stats_keep_latest_five(self):
        for i in range(7):
            self.box.record_stage("文字起こし", i + 0.25)
        self.box.record_stage("", 1)
        self.box.record_stage("x", -1)
        self.assertEqual(self.box.stage_stats(), {"文字起こし": [6.2, 5.2, 4.2, 3.2, 2.2]})   # 新しい順・5 件
        self.assertEqual(self.new_box().stage_stats(), {"文字起こし": [6.2, 5.2, 4.2, 3.2, 2.2]})

    def test_waiting_rows_and_wait_done(self):
        self.box.add(RID, {"kind": "wait", "url": "u"}, {"url": "u"}, kind="url", state="waiting")
        self.assertEqual([r["id"] for r in self.box.waiting_rows()], [RID])
        self.assertEqual(self.box.row(RID)["state"], "waiting")
        self.clock.t = T0 + 5
        self.box.wait_checked(RID)
        self.assertEqual(self.box.row(RID)["checkedAt"], int((T0 + 5) * 1000))
        r = self.box.wait_done(RID)
        self.assertEqual((r["state"], r["kind"], r["form"]["kind"], r["waited"]), ("sent", "url", "url", True))
        self.assertEqual(self.box.waiting_rows(), [])
        self.assertIsNone(self.box.wait_done(RID))
        self.box.add(RID2, {}, {}, state="waiting")
        self.assertIsNotNone(self.box.fail(RID2, "アーカイブが出ませんでした"))
        self.assertEqual(self.box.row(RID2)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
