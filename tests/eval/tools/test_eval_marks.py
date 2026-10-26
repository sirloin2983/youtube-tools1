"""src/eval/tools/eval_marks.py(盛り上がりの検出を、人の判定の記録で測る道具。線 C の土台)のテスト。リポジトリ直下で:

    python -m unittest tests/eval/tools/test_eval_marks.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバーは動かさない。
"""
import contextlib
import gzip
import io
import json
import os
import sys
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src", "eval", "tools")   # src/eval/tools (道具の置き場所)
REPO = os.path.dirname(os.path.dirname(HERE))   # src(ツールと共通部品 ytt の置き場所)
sys.path.insert(0, REPO)
from eval.tools import eval_marks as M  # noqa: E402
from flow import packrec  # noqa: E402
from manage.cases import txindex  # noqa: E402
from flow import lengthhint  # noqa: E402
from human import judgments  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

V1, V2 = "v1aaaaaaaaa", "v2bbbbbbbbb"


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def mark(mid, s, e, score, status="", src="auto", created=None, **kw):
    m = {"id": mid, "start": s, "end": e, "label": "", "src": src, "score": score, "status": status, "createdAt": created or ms("2026-09-01")}
    if src == "auto":
        m["auto0"] = [s, e]
    m.update(kw)
    return m


def fb(day, event, verdict, s, e, score=None, src="auto", auto0=None, **kw):
    row = {"ts": day + "T12:00:00", "videoId": V1, "kind": "youtube", "start": s, "end": e, "score": score, "verdict": verdict, "src": src, "event": event, "type": "歌枠"}
    if auto0 is not None:
        row["auto0"] = auto0
    row.update(kw)
    return row


class Env:
    """一時フォルダの作業データ: <root>/studio・<root>/app・<root>/cut2resolve"""

    def __init__(self, test):
        self.test = test
        self.root = testkit.tempdir(test)
        self.studio = os.path.join(self.root, "studio")
        self.logs = os.path.join(self.root, "app", "logs")
        os.makedirs(self.studio)
        os.makedirs(self.logs)

    def jsonl(self, rel, rows, mode="w"):
        """root の下の rel(/ 区切り)へ JSON の行を書く。mode "a" で足す"""
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode, encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def data(self, videos):
        testkit.write_json(os.path.join(self.studio, "data.json"), {"schema": "clip-studio/v1", "videos": videos, "groups": {}})

    def videos(self):
        return testkit.read_json(os.path.join(self.studio, "data.json"))["videos"]

    def feedback(self, rows, name="machine_marks.jsonl", mode="w"):
        """機械の記録(machine_marks.jsonl と .old)の行を書き、スタジオの保存と同じく人の採否を judgments へ写す
        (adopt・reject・delete = 機械の採用の印の無い行・markId のある行だけ。unadopt・delete_judged は同じマークの最後の採否を取り消す = review/store と同じ)"""
        self.jsonl("studio/" + name, rows, mode)
        app = os.path.join(self.root, "app")
        for r in rows:
            ev, mid, vid = r.get("event"), r.get("markId"), r.get("videoId")
            if not mid or r.get("adoptedBy") or r.get("kind") == "live":
                continue
            at = M.ts_ms(r["ts"])
            if ev in ("adopt", "reject", "delete"):
                judgments.record(app, who="self", what="adopt" if ev == "adopt" else "reject", videoId=vid, markId=mid, origin="auto", via="review",
                                 at=at, key="fb:%s:%s:%s:%s" % (r["ts"], vid, mid, ev))
            elif ev in ("unadopt", "delete_judged"):
                rows_ = judgments.rows(app)
                done = {x.get("of") for x in rows_ if x["what"] == "retract"}
                hit = [x for x in rows_ if x["who"] == "self" and x["what"] in ("adopt", "reject") and (x["videoId"], x["markId"]) == (vid, mid) and x["id"] not in done]
                if hit:
                    judgments.retract(app, hit[-1], "self", "review", at=at)

    def archive(self, vid, cands, at):
        os.makedirs(os.path.join(self.studio, "archive"), exist_ok=True)
        with gzip.open(os.path.join(self.studio, "archive", vid + ".json.gz"), "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "videoId": vid, "type": "歌枠", "runs": [{"at": at, "candidates": cands}]}, f)

    def runs(self, rows, mode="w"):
        """入口の実行記録(flow/runlog の形: v・id・state・steps が無い行は読み飛ばされるので、省いた鍵は足す)"""
        self.jsonl("app/logs/autorun-runs.jsonl", [dict({"v": 1, "state": "done", "steps": [], "kind": "video"}, **r) for r in rows], mode)

    def live_feedback(self, rows, mode="w"):
        self.jsonl("app/live/live_feedback.jsonl", rows, mode)

    def built(self):
        """道具の中の配信ごとのまとめ(build_videos)"""
        env, studio, app = M.locate(self.root)
        return M.build_videos(studio, M.load_machine(studio), M.load_runs(app), env, human=M.human_marks(app))

    def saved(self, suffix=".json"):
        """--json で保存した evals/marks の結果(名前の終わりが suffix の 1 つ)"""
        d = os.path.join(self.studio, "evals", "marks")
        names = [n for n in os.listdir(d) if n.endswith(suffix) and (suffix != ".json" or not n.endswith("-live.json"))]
        self.test.assertEqual(len(names), 1)
        return testkit.read_json(os.path.join(d, names[0]))

    def pack(self, media):
        """media(書き出した mp4 のパス)の隣に _pack を作り、パックを作った記録を cut2resolve の packs/ に置く"""
        d = txindex.pack_dir(media)
        os.makedirs(d)
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("x")
        pk = os.path.join(self.root, "cut2resolve", "packs")
        os.makedirs(pk, exist_ok=True)
        with open(os.path.join(pk, packrec.record_name(d)), "w", encoding="utf-8") as f:
            json.dump({"schema": packrec.SCHEMA, "dir": d, "files": ["a.txt"], "builtAt": ms("2026-09-02"), "textplus": True}, f)

    def evaluate(self, **kw):
        return M.evaluate(self.root, **kw)

    def judge(self, n, what, vid="vj", mid=None, who="self", origin="live", via="cases", at=None, **kw):
        """人の判断(judgments.jsonl)を 1 行足す。key は n(同じ n は 1 回だけ)"""
        return judgments.record(os.path.join(self.root, "app"), what=what, who=who, videoId=vid, markId=mid or "m%d" % n, origin=origin, via=via,
                                at=at or ms("2026-10-08", "10:%02d:00" % n), key="t:%d" % n, **kw)

    def deliver(self, zip_name, packs, origin="request", at="2026-10-08", vid=V1, **kw):
        """届けた記録(logs/deliveries.jsonl)を 1 行足す。packs = [(パックのフォルダ名, markId)]"""
        row = dict({"at": ms(at), "zip": zip_name, "requestId": "q" if origin == "request" else "", "runId": "r", "videoId": vid, "origin": origin,
                    "packs": [{"dir": "C:\\out\\" + n, "markId": m} for n, m in packs]}, **kw)
        self.jsonl("app/logs/deliveries.jsonl", [row], "a")


def printed(fn, *args):
    """fn(*args) が画面に出した文字"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args)
    return out.getvalue()


def video(vid, marks, typ="歌枠", title="t"):
    return {"id": vid, "kind": "youtube", "title": title, "analysis": {"type": typ, "at": ms("2026-09-01")}, "marks": marks, "rev": 1}


def build(test):
    """V1: 自動 A(5.0 採用・書き出し・パック・友人へ)B(4.0 不採用)C(3.0 判定なし)D(2.0 まとめて実行で採用)・削除した候補 E(6.0)。
    A は開始を 2 秒直した。手で足した 2 個(1 個は後で消した)・採用の取り消し 1 個。"""
    env = Env(test)
    media = os.path.join(env.root, "clips", "a.mp4")
    os.makedirs(os.path.dirname(media))
    env.pack(media)
    a = mark("mA", 102.0, 140.0, 5.0, "exported", path=media, file="x/a.mp4", auto0=[100.0, 140.0])
    env.data({V1: video(V1, [a, mark("mB", 300.0, 340.0, 4.0, "rejected"), mark("mC", 500.0, 540.0, 3.0), mark("mD", 700.0, 740.0, 2.0, "adopted"),
                             mark("mM", 900.0, 930.0, None, "adopted", src="manual")])})
    env.feedback([
        fb("2026-09-01", "adopt", "good", 102.0, 140.0, 5.0, auto0=[100.0, 140.0], dStart=2.0, dEnd=0.0, markId="mA"),
        fb("2026-09-02", "export", "good", 102.0, 140.0, 5.0, auto0=[100.0, 140.0], dStart=2.0, dEnd=0.0, markId="mA"),
        fb("2026-09-01", "reject", "bad", 300.0, 340.0, 4.0, auto0=[300.0, 340.0], markId="mB"),
        fb("2026-09-01", "delete", "bad", 1000.0, 1040.0, 6.0, auto0=[1000.0, 1040.0], markId="mE"),
        fb("2026-09-03", "manual_add", "miss", 900.0, 930.0, src="manual", autoCount=4, nearAuto={"score": 2.0, "distance": 8.0, "start": 700.0, "end": 740.0, "status": ""}),
        fb("2026-09-03", "manual_add", "miss", 2000.0, 2030.0, src="manual", markId="mX", autoCount=4, nearAuto={"score": 2.0, "distance": 900.0, "start": 700.0, "end": 740.0, "status": ""}),
        fb("2026-09-03", "manual_remove", "unmiss", 2000.0, 2030.0, src="manual", markId="mX"),
        fb("2026-09-04", "unadopt", "retract", 500.0, 540.0, 3.0, auto0=[500.0, 540.0], prevStatus="adopted", markId="mC"),
        fb("2026-09-04", "adopt", "good", 900.0, 930.0, src="manual", markId="mM"),
    ])
    env.runs([build_run()])
    return env


def build_run(**kw):
    """build の実行記録(採用と届けるの段が動いた・届けたのは mA・mD)。kw で区間などを足す"""
    return dict({"v": 1, "id": "r1", "kind": "video", "videoId": V1, "state": "done", "requestId": "20260901-000000-abcdef",
                 "steps": [{"key": "adopt", "state": "done"}, {"key": "deliver", "state": "done"}], "marks": ["mA", "mD"]}, **kw)


class EvalMarks(unittest.TestCase):
    def test_metrics(self):
        r = build(self).evaluate()
        o = r["overall"]
        t5 = o["top"]["top5"]
        self.assertEqual(t5["items"], 5)   # E・A・B・C・D(点数の順)
        self.assertEqual((t5["good"], t5["bad"], t5["judged"]), (1, 2, 3))
        self.assertEqual(t5["adoptRate"], round(1 / 3, 4))
        self.assertEqual(t5["adoptRateAll"], round(1 / 5, 4))
        self.assertEqual((t5["unjudged"], t5["machine"]), (2, 0))   # 判定なしは分母に入れない(人の採否の行の無い採用 D も判定なし)
        self.assertEqual(o["top"]["all"]["items"], 5)
        al = o["top"]["all"]
        self.assertEqual((al["exported"], al["packed"], al["delivered"]), (1, 1, 1))
        self.assertEqual((al["exportRate"], al["packRate"], al["deliveredRate"]), (1.0, 1.0, 1.0))
        self.assertEqual(o["videos"], 1)
        self.assertTrue(r["meta"]["few"])   # 配信 10 本未満
        self.assertTrue(r["meta"]["fewNote"])

    def test_top_n_order(self):
        """上位 N は点数の高い順。N=1 なら削除した候補 E(6.0)だけ = 悪い"""
        order = [(i["score"], i["verdict"]) for i in M.ranked(build(self).built()[V1]["auto"])]
        self.assertEqual(order, [(6.0, "bad"), (5.0, "good"), (4.0, "bad"), (3.0, "none"), (2.0, "none")])

    def test_rejected_without_human_row_is_none(self):
        """人の行(却下・削除)の無い rejected(マークの状態だけ)は「悪い」ではなく判定なし"""
        env = build(self)
        d = env.videos()
        d[V1]["marks"].append(mark("mR", 1100.0, 1140.0, 1.0, "rejected"))
        env.data(d)
        by = {i["score"]: i["verdict"] for i in env.built()[V1]["auto"]}
        self.assertEqual((by[1.0], by[4.0]), ("none", "bad"))   # 行のある mB(4.0)は今までどおり悪い

    def test_live_recording_not_counted(self):
        """ライブの録画(kind live。解析していない・手のマークだけ)は、data.json にも feedback の行にもあっても数字を変えない"""
        env = build(self)
        before = env.evaluate()["overall"]
        rid = "20261005-185300-U972n0ncl4k"
        d = env.videos()
        d[rid] = {"id": rid, "kind": "live", "title": "録画", "analysis": None, "rev": 1,
                  "marks": [mark("lm1", 10.0, 20.0, None, "exported", src="manual"), mark("lm2", 30.0, 40.0, None, "", src="manual")]}
        env.data(d)
        env.feedback([fb("2026-09-05", "manual_add", "miss", 10.0, 20.0, src="manual", videoId=rid, kind="live", autoCount=0, nearAuto=None),
                      fb("2026-09-05", "export", "good", 10.0, 20.0, src="manual", videoId=rid, kind="live")], mode="a")
        after = env.evaluate()["overall"]
        self.assertEqual((after["videos"], after["misses"], after["top"]), (before["videos"], before["misses"], before["top"]))

    def test_judged_elsewhere_counts_live_and_friend(self):
        """C1 の入口の数に線 D の人の判定(届けた・要らない)と友人の返事も足す。採用率は変えない(友人の基準は別)"""
        env = build(self)
        before = env.evaluate()["overall"]
        env.live_feedback([{"v": 1, "at": "2026-10-08T10:00:00.000Z", "event": "adopt", "human": False, "recorder": "local", "recording": "rec1"},   # 機械の行は人の判断に数えない
                           {"v": 1, "at": "2026-10-08T12:00:00.000Z", "event": "detect_compare", "recorder": "local", "recording": "rec3"},
                           {"v": 1, "at": "2026-10-08T10:05:00.000Z", "event": "deliver", "human": True, "recorder": "local", "recording": "rec9"}])   # human の行は読まない(人の判断は judgments)
        for n, what, rec in ((1, "adopt", "rec1"), (2, "reject", "rec1"), (3, "reject", "rec2")):
            env.judge(n, what, vid=rec, ref={"recorder": "local", "recording": rec})
        env.judge(4, "adopt", vid="recx", origin="manual", ref={"recorder": "local", "recording": "recx"})   # origin live でない物は数えない
        n = iter(range(10, 99))

        def friend(zip_name, vid="", run_id="", what="reject"):   # 友人の「要らない」は judgments だけ(Q3。古い reject・bad・unknown)
            k = next(n)
            judgments.record(os.path.join(env.root, "app"), who="friend", what=what, videoId=vid, markId="f%d" % k if vid else "", origin="request",
                             via="friend_file", at=ms("2026-10-08"), key="ff:%d" % k, ref={"zip": zip_name, "pack": "p%d" % k, "runId": run_id})
        env.runs([{"v": 1, "id": "file1", "kind": "file", "sourcePath": os.path.join(env.root, "clips", "b.mp4")},
                                                  {"v": 1, "id": "file2", "kind": "file", "sourcePath": os.path.join(env.root, "other", "c.mp4")}], "a")
        friend("z.zip", V1), friend("z.zip", V2), friend("z.zip", V2, what="bad")   # V1 はスタジオで判定あり = 二重に数えない
        friend("y.zip", run_id="r1")        # 実行記録 r1 = V1
        friend("x.zip", run_id="nothing")   # たどれない
        friend("w.zip", run_id="file1")     # 実行記録の動画が V1 の書き出し先と同じフォルダ = V1
        friend("v.zip", run_id="file2")     # 突き合わないフォルダ = 1 つの配信
        friend("u.zip", V2, what="good")    # 受け取った = 「要らない」ではない(数えない)
        friend("t.zip")                     # 配信の分からない行(markId の無い古い行)= zip の届けた記録の配信 = V2
        env.deliver("t.zip", [("t_pack", "")], vid=V2)
        r = env.evaluate()
        o = r["overall"]
        self.assertEqual(o["judgedElsewhere"], {"live": {"recordings": 2, "good": 1, "bad": 2}, "friend": {"videos": 3, "rows": 8, "unknown": 1, "notInStudio": 2}, "all": 5})
        self.assertEqual((o["judgedAll"], r["meta"]["judgedAll"], o["judgedVideos"]), (5, 5, 1))
        self.assertEqual((o["top"], o["misses"]), (before["top"], before["misses"]))   # 採用率・見逃しは今までどおり
        self.assertEqual(env.evaluate(since="2026-10-09")["overall"]["judgedElsewhere"]["live"]["recordings"], 0)   # 時期で絞る

    def test_misses_edits_retracts(self):
        o = build(self).evaluate()["overall"]
        m = o["misses"]
        self.assertEqual(m["added"], 1)               # 2 個足して 1 個は消した
        self.assertEqual(m["goodAuto"], 1)
        self.assertEqual(m["missRate"], 0.5)
        self.assertEqual((m["withNearAuto"], m["near15s"], m["farOrNone"]), (1, 1, 0))
        self.assertEqual(m["nearDistance"]["median"], 8.0)
        self.assertEqual(m["nearScore"]["median"], 2.0)
        e = o["edits"]
        self.assertEqual(e["items"], 1)               # 良い自動 A だけ
        self.assertEqual((e["dStart"]["median"], e["dEnd"]["median"], e["editedRate"]), (2.0, 0.0, 1.0))
        self.assertEqual(o["retracts"], {"unadopt": 1, "deleteJudged": 0, "total": 1})
        mm = o["manualMarks"]
        self.assertEqual((mm["marks"], mm["good"]), (1, 1))   # 手動マークの採用(人の adopt の行がある)

    def test_status_without_human_row_is_unjudged(self):
        """採用の状態があっても人の採否の行も機械の印も無いマークは判定なし。実行記録の「採用」の段は判定に使わない"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted"), mark("b", 100.0, 140.0, 2.0)])})
        env.runs([{"v": 1, "id": "r", "kind": "video", "videoId": V1, "state": "done", "steps": [{"key": "adopt", "state": "done"}]}])
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["good"], al["machine"], al["unjudged"]), (0, 0, 2))

    def test_verdict_comes_from_judgments(self):
        """採否は judgments だけ(10-19 Q2): 機械の記録に adopt の行と verdict good があっても、人の判断の行が無ければ良いに数えない。
        judgments だけにある採否(機械の記録の行が無い)は当たる"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted"), mark("b", 100.0, 140.0, 2.0, "rejected")])})
        env.jsonl("studio/machine_marks.jsonl", [fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0], markId="a")])   # 判断を写さない
        env.judge(1, "reject", vid=V1, mid="b", origin="auto", via="review")
        env.judge(2, "adopt", vid=V1, mid="b", origin="auto", via="cases")   # スタジオの保存の外の判断は数えない
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["good"], al["bad"], al["unjudged"]), (0, 1, 1))

    def test_since_until(self):
        env = build(self)
        later = mark("n1", 10.0, 50.0, 9.0, "adopted", created=ms("2026-10-02"))
        d = env.videos()
        d[V2] = video(V2, [later, mark("n2", 100.0, 140.0, 8.0, created=ms("2026-10-02"))], typ="雑談")
        env.data(d)
        env.feedback([fb("2026-10-02", "adopt", "good", 10.0, 50.0, 9.0, auto0=[10.0, 50.0], videoId=V2, type="雑談", markId="n1"),
                      fb("2026-10-03", "manual_add", "miss", 500.0, 530.0, src="manual", videoId=V2, autoCount=2)], mode="a")
        allr = env.evaluate()
        self.assertEqual(allr["overall"]["videos"], 2)
        self.assertEqual(sorted(allr["byType"]), ["歌枠", "雑談"])
        new = env.evaluate(since="2026-10-01")
        self.assertEqual(new["overall"]["videos"], 1)
        self.assertEqual(new["byVideo"][0]["videoId"], V2)
        self.assertEqual(new["overall"]["top"]["all"]["items"], 2)
        self.assertEqual(new["overall"]["top"]["all"]["good"], 1)
        self.assertEqual(new["overall"]["misses"]["added"], 1)
        old = env.evaluate(until="2026-09-30")
        self.assertEqual([v["videoId"] for v in old["byVideo"]], [V1])
        self.assertEqual(old["overall"]["misses"]["added"], 1)   # 09-03 の分は入る・10-03 の分は入らない
        none = env.evaluate(since="2026-11-01")
        self.assertEqual(none["overall"]["videos"], 0)
        with self.assertRaises(SystemExit):
            env.evaluate(since="2026/10/01")

    def test_archive_fills_deleted_candidates(self):
        """data.json から消えた候補も archive の最後の解析から補う(判定なし)。data にあるものは二重に数えない"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted")])})
        env.feedback([fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0], markId="a")])
        env.archive(V1, [{"start": 10.0, "end": 50.0, "score": 3.0}, {"start": 200.0, "end": 240.0, "score": 2.5}], ms("2026-09-01"))
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["items"], al["good"], al["unjudged"]), (2, 1, 1))

    def test_old_file_and_dedupe(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted")])})
        row = fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0], markId="a")
        env.feedback([row], "machine_marks.jsonl.old")
        env.feedback([row, fb("2026-09-05", "manual_add", "miss", 500.0, 530.0, src="manual", autoCount=1)])   # .old へ移す途中で止まった重なり
        env.feedback([fb("2026-09-07", "manual_add", None, 600.0, 630.0, src="manual", autoCount=1)], mode="a")
        env.feedback([fb("2026-09-08", "manual_add", None, 700.0, 730.0, src="manual", autoCount=1)], "feedback.jsonl")   # 前の名前は読まない
        with open(os.path.join(env.studio, "machine_marks.jsonl"), "ab") as f:
            f.write(b'{"ts": "2026-09-06T00:00:00", "videoId": ')   # 書きかけの行
        r = env.evaluate()
        self.assertEqual(r["overall"]["misses"]["added"], 2)
        self.assertEqual(r["overall"]["top"]["all"]["good"], 1)
        self.assertEqual(len(M.load_machine(env.studio)), 3)

    def test_adopted_by_marks_and_rows(self):
        """adoptedBy(マーク・行)がある採用・書き出しは機械の判定。印も人の採否の行も無い採用は判定なし(実行記録で自動採用と推し量らない)"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 5.0, "adopted", adoptedBy="auto"), mark("b", 100.0, 140.0, 4.0, "exported", adoptedBy="request"),
                                 mark("c", 200.0, 240.0, 3.0, "exported"), mark("d", 300.0, 340.0, 2.0, "adopted")])})
        env.feedback([
            fb("2026-09-01", "export", "good", 100.0, 140.0, 4.0, auto0=[100.0, 140.0], markId="b", adoptedBy="request"),   # 機械が採用にしたものの書き出しの行
            fb("2026-09-01", "export", "good", 200.0, 240.0, 3.0, auto0=[200.0, 240.0], markId="c"),                        # 人が書き出した
        ])
        env.judge(9, "adopt", vid=V1, mid="c", origin="auto", via="review")   # 人の採用(採否は judgments だけ)
        env.runs([{"v": 1, "id": "r", "kind": "video", "videoId": V1, "state": "done", "steps": [{"key": "adopt", "state": "done"}]}])   # 実行記録は判定に使わない
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["good"], al["machine"], al["unjudged"]), (1, 2, 1))   # c だけ良い。a・b は印で機械・d は判定なし
        self.assertEqual((al["exported"], al["adoptRate"]), (1, 1.0))

    def test_adopted_by_row_only(self):
        """data.json から消えたマークでも、行の adoptedBy で機械の採用と分かる。人が後で不採用にすれば悪い"""
        env = Env(self)
        env.data({V1: video(V1, [])})
        env.feedback([fb("2026-09-01", "export", "good", 10.0, 50.0, 5.0, auto0=[10.0, 50.0], markId="a", adoptedBy="auto"),
                      fb("2026-09-01", "export", "good", 100.0, 140.0, 4.0, auto0=[100.0, 140.0], markId="b", adoptedBy="auto"),
                      fb("2026-09-02", "reject", "bad", 100.0, 140.0, 4.0, auto0=[100.0, 140.0], markId="b")])
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["items"], al["machine"], al["good"], al["bad"]), (2, 1, 0, 1))

    def test_match_by_mark_id(self):
        """機械の記録の行は markId で突き合わせる: 同じ区間でも別の ID のマークの行は混ぜない。ID の無い古い行は使わない(区間で推し量らない)"""
        env = Env(self)
        env.data({V1: video(V1, [mark("x", 10.0, 50.0, 5.0, "adopted")])})
        env.feedback([fb("2026-09-01", "adopt", "good", 10.0, 50.0, 5.0, auto0=[10.0, 50.0], markId="x"),
                      fb("2026-09-01", "reject", "bad", 10.0, 50.0, 4.0, auto0=[10.0, 50.0], markId="y"),       # 別のマーク y(消えた)。同じ区間でも x に混ぜない
                      fb("2026-09-02", "reject", "bad", 200.0, 240.0, 3.0, auto0=[200.0, 240.0])])              # ID の無い行
        r = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((r["items"], r["good"], r["bad"]), (2, 1, 1))
        env.feedback([fb("2026-09-01", "adopt", "good", 10.0, 50.0, 5.0, auto0=[10.0, 50.0])])
        r = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((r["items"], r["good"]), (1, 1))

    def test_manual_remove_by_mark_id(self):
        env = Env(self)
        env.data({V1: video(V1, [])})
        env.feedback([fb("2026-09-03", "manual_add", "miss", 900.0, 930.0, src="manual", markId="m1", autoCount=1),
                      fb("2026-09-03", "manual_add", "miss", 900.0, 930.0, src="manual", markId="m2", autoCount=1),
                      fb("2026-09-03", "manual_remove", "unmiss", 905.0, 935.0, src="manual", markId="m2")])   # 区間が少しずれていても ID で m2 だけ消える
        self.assertEqual(M.evaluate(env.root)["overall"]["misses"]["added"], 1)

    def test_empty(self):
        """作業データが空(入れ直し直後)・フォルダ自体が無くても落ちない"""
        env = Env(self)
        for root in (env.root, os.path.join(env.root, "nothing")):
            r = M.evaluate(root)
            self.assertEqual(r["meta"]["videos"], 0)
            self.assertTrue(r["meta"]["few"])
            self.assertEqual(r["overall"]["top"]["all"]["items"], 0)
            printed(M.print_report, r)   # 空でも表示で落ちない

    def test_corrupt_data_json(self):
        env = Env(self)
        testkit.write_text(os.path.join(env.studio, "data.json"), "{broken")
        self.assertEqual(env.evaluate()["meta"]["videos"], 0)

    def test_cli_json_saved_and_read_only(self):
        """--json なしでは何も書かない。--json の保存は画面と同じ値(友人の区間も入る)。入力は書き換えない"""
        env = build(self)
        env.runs([build_run(created=ms("2026-09-05"), ranges=[[110, 130]])])
        before = {n: os.path.getmtime(os.path.join(env.studio, n)) for n in os.listdir(env.studio) if os.path.isfile(os.path.join(env.studio, n))}
        with contextlib.redirect_stdout(io.StringIO()):
            res = M.main(["--data-dir", env.root])
        self.assertFalse(os.path.exists(os.path.join(env.studio, "evals")))
        printed(M.main, ["--data-dir", env.root, "--json", "--since", "2026-01-01"])
        saved = env.saved()
        self.assertEqual(saved["meta"]["schema"], M.SCHEMA)
        self.assertEqual(saved["overall"]["top"]["top5"], res["overall"]["top"]["top5"])   # 画面と同じ形・同じ値
        self.assertEqual(saved["friendRanges"]["overall"]["hit"], 1)
        after = {n: os.path.getmtime(os.path.join(env.studio, n)) for n in before}
        self.assertEqual(before, after)   # 入力は書き換えない

    def test_many_videos_not_few(self):
        env = Env(self)
        vids = {}
        rows = []
        for i in range(M.FEW_VIDEOS):
            vid = "vid%08d" % i
            vids[vid] = video(vid, [mark("a%d" % i, 10.0, 50.0, 3.0, "adopted")])
            rows.append(fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0], videoId=vid, markId="a%d" % i))
        env.data(vids)
        env.feedback(rows)
        r = env.evaluate()
        self.assertFalse(r["meta"]["few"])
        self.assertEqual(r["meta"]["fewNote"], "")
        self.assertEqual(r["overall"]["top"]["top5"]["adoptRate"], 1.0)


V3 = "v3ccccccccc"


def run_row(vid, ranges, day="2026-09-05", **kw):
    r = {"v": 1, "id": "q" + vid[:3], "kind": "video", "videoId": vid, "state": "done", "created": ms(day), "ranges": ranges, "steps": [{"key": "analyze", "state": "done"}]}
    r.update(kw)
    return r


def eight(vid=V1):
    """点数 8..1 の自動の候補 8 個(順位 k は 100+200*(k-1) 秒から 40 秒)"""
    return video(vid, [mark("c%d" % k, 100.0 + 200 * (k - 1), 140.0 + 200 * (k - 1), float(9 - k)) for k in range(1, 9)])


class LiveReports(unittest.TestCase):
    """--live: 入口の配信ごとの記録(live/reports/)と live_feedback.jsonl を録画ごとに並べる(読むだけ)"""
    RC, R1, R2, R3 = "local", "20261008-200000-abcdefghijk", "20261009-200000-bbbbbbbbbbb", "20261001-100000-ccccccccccc"

    def report(self, env, rec, started, **kw):
        d = os.path.join(env.root, "app", "live", "reports")
        rep = dict({"v": 1, "recorder": self.RC, "recording": rec, "state": "done", "startedAt": started, "updatedAt": started, "finishedAt": started,
                    "info": {"title": "配信 " + rec[-3:], "hours": 2.5}, "samples": {"behindMax": 12.0, "memMaxMB": 300.0, "lagMax": 9, "restarts": 1, "chatRestarts": 2, "chat": "ok"},
                    "detect": {"frame": 5, "bench": 2, "dismissed": 1, "adopted": 3, "adoptedAuto": 2, "adoptedManual": 1, "givenUp": 1, "gaps": 0, "ended": True},
                    "tx": {"ok": 4, "empty": 1, "error": 1, "secMedian": 6.0}, "exports": {"total": 3, "failures": 1, "waitSecMedian": 90.0, "waitSecMax": 200.0, "byState": {"done": 2, "error": 1}},
                    "disk": {"state": "ok", "rows": []}, "request": None}, **kw)
        testkit.write_json(os.path.join(d, "%s__%s.json" % (self.RC, rec)), rep)

    def rows(self):
        R1, R2, R3, RC = self.R1, self.R2, self.R3, self.RC
        def row(at, rec, event, origin=None, mark=None, **kw):
            return dict({"v": 1, "at": at, "event": event, "origin": origin, "recorder": RC, "recording": rec, "markId": "lm-" + (mark or "x"),
                         "studio": {"video": rec, "mark": mark}}, **kw)
        return [row("2026-10-08T20:10:00Z", R1, "adopt", "auto", "m1", human=False, verdict=None),
                row("2026-10-08T20:30:00Z", R1, "adopt", "auto", "m2", human=False, verdict=None),
                row("2026-10-08T20:40:00Z", R1, "adopt", "manual", "m3", human=True, verdict="good"),
                row("2026-10-09T01:00:00Z", R1, "adopt", "archive", "m4", human=False, verdict=None),
                row("2026-10-09T02:00:00Z", R1, "deliver", "auto", "m1", human=True, verdict="good"),   # 古い人の行は読まない(judgments が持つ)
                {"v": 1, "at": "2026-10-09T01:30:00Z", "event": "detect_compare", "recorder": RC, "recording": R1, "archive": 4, "hit": 3, "ratio": 0.75,
                 "medianAbsDiff": 2.5, "liveFrame": 5, "liveBench": 2, "liveUnmatched": 2},
                row("2026-10-01T10:10:00Z", R3, "adopt", "auto", "m9", human=False, verdict=None),   # 記録の無い録画(行だけ)
                {"v": 1, "at": "2026-10-01T10:11:00Z", "event": "adopt"}]   # 壊れた行は飛ばす

    def human(self, env):
        """人の判断(judgments): m1 を届けた = 良い・m4 を要らない = 悪い・m3(人の採用)も届けたが自動の採用ではないので数えない"""
        ref = {"recorder": self.RC, "recording": self.R1}
        env.judge(1, "adopt", vid=self.R1, mid="m1", ref=ref)
        env.judge(2, "reject", vid=self.R1, mid="m4", ref=ref)
        env.judge(3, "adopt", vid=self.R1, mid="m3", ref=ref)

    def test_live_rows_and_totals(self):
        env = Env(self)
        self.report(env, self.R1, "2026-10-08T20:00:00Z")
        self.report(env, self.R2, "2026-10-10T12:00:00Z", request={"rid": "r", "streamer": "x"}, detect={"frame": 1, "bench": 0, "dismissed": 0, "adopted": 0, "adoptedAuto": 0, "adoptedManual": 0, "givenUp": 0, "gaps": 1, "ended": False})
        env.live_feedback(self.rows())
        self.human(env)
        res = M.evaluate_live(env.root)
        m, t = res["meta"], res["totals"]
        self.assertEqual((m["schema"], m["recordings"], m["few"], m["liveDir"]), (M.LIVE_SCHEMA, 3, True, os.path.join(env.root, "app", "live")))
        self.assertEqual([r["recording"] for r in res["recordings"]], [self.R2, self.R1, self.R3])   # 新しい順(行だけの録画は最後)
        r1 = res["recordings"][1]
        self.assertEqual(r1["adopt"], {"auto": 2, "manual": 1, "archive": 1, "good": 1, "bad": 1, "unjudged": 1})
        self.assertEqual((r1["peaks"]["frame"], r1["peaks"]["bench"], r1["compare"]["ratio"], r1["compare"]["hit"], r1["worker"]["memMaxMB"], r1["title"]), (5, 2, 0.75, 3, 300.0, "配信 ijk"))
        r3 = res["recordings"][2]
        self.assertEqual((r3["state"], r3["adopt"]["auto"], r3["hours"], r3["compare"]), ("feedback", 1, None, None))
        self.assertTrue(res["recordings"][0]["request"])
        self.assertEqual((t["recordings"], t["hours"], t["peaks"], t["adoptAuto"], t["adoptManual"], t["adoptArchive"], t["good"], t["bad"], t["adoptRate"], t["unjudged"]),
                         (3, 5.0, 9, 3, 1, 1, 1, 1, 0.5, 2))   # 候補 = 枠 + 採用(控えは別)。記録のある録画は行から数えない
        self.assertEqual((t["compare"]["archive"], t["compare"]["hit"], t["compare"]["ratio"], t["compare"]["medianAbsDiff"]), (4, 3, 0.75, 2.5))
        self.assertEqual((t["behindMax"], t["memMaxMB"], t["restarts"], t["tx"], t["exports"]["total"], t["exports"]["waitSecMedian"], t["exports"]["waitSecMax"]),
                         (12.0, 300.0, 2, {"ok": 8, "empty": 2, "error": 2}, 6, 90.0, 200.0))
        # 時期で絞る(記録は startedAt・行だけの録画は at)
        res = M.evaluate_live(env.root, since="2026-10-10")   # 記録の時刻は UTC → 手元の日付で絞る(どの時間帯でも R1 = 10-08 20:00Z は外れる)
        self.assertEqual([r["recording"] for r in res["recordings"]], [self.R2])
        res = M.evaluate_live(env.root, until="2026-10-05")
        self.assertEqual([r["recording"] for r in res["recordings"]], [self.R3])

    def test_live_empty_and_cli(self):
        env = Env(self)
        res = M.evaluate_live(env.root)
        self.assertEqual((res["meta"]["recordings"], res["recordings"], res["totals"]["recordings"], res["totals"]["adoptRate"]), (0, [], 0, None))
        printed(M.main, ["--live", "--data-dir", env.root])   # 空でも表示で落ちない
        self.report(env, self.R1, "2026-10-08T20:00:00Z")
        env.live_feedback(self.rows())
        self.human(env)
        before = sorted(os.listdir(env.root))
        self.assertIn(M.C.SAVED_MARK, printed(M.main, ["--live", "--data-dir", env.root, "--json"]))   # 入口の accuracy が読む印
        saved = env.saved("-live.json")
        self.assertEqual((saved["meta"]["schema"], saved["meta"]["recordings"]), (M.LIVE_SCHEMA, 2))
        self.assertEqual(sorted(os.listdir(env.root)), before)   # 作業データの親には何も足さない(evals は studio の中)


class Human3(unittest.TestCase):
    """物差し 3 本(human3): 友人の区間・届けた物を友人が使ったか・確かめるの良い / 悪い。人の判断は judgments だけを読む"""

    def h3(self, env, **kw):
        return env.evaluate(**kw)["human3"]

    def test_used_counts_unanswered_and_origin(self):
        env = Env(self)
        env.deliver("a.zip", [("p1", "m1"), ("p2", "m2"), ("p3", "m3")], origin="request")
        env.deliver("b.zip", [("p4", "m4"), ("p5", "m5")], origin="auto", vid=V2)
        env.deliver("c.zip", [("p6", "m6")], origin="manual")
        fr = {"zip": "a.zip", "pack": "C:\\out\\P1"}   # パック名で突き合わせる(場所・大文字小文字は問わない)
        env.judge(1, "adopt", vid=V1, mid="m1", who="friend", origin="request", via="friend_verdict", ref=fr)
        env.judge(2, "reject", vid=V1, mid="m2", who="friend", origin="request", via="friend_verdict", ref={"zip": "a.zip", "pack": "p2"})
        env.judge(4, "made_video", vid=V2, mid="m4", who="friend", origin="auto", via="friend_file", ref={"zip": "b.zip", "pack": "p4"})   # 使った(動画にした)
        env.judge(5, "adopt", vid=V1, mid="m6", who="friend", origin="manual", via="friend_verdict", ref={"zip": "c.zip", "pack": "p6"})
        env.judge(6, "adopt", vid=V1, mid="mx", who="self", origin="live", via="cases")   # 自分の判断は分子に入れない
        u = self.h3(env)["used"]
        # p1 良い・p2 古い reject = 不明・p3 答えなし = 不明
        self.assertEqual((u["request"]["delivered"], u["request"]["good"], u["request"]["bad"], u["request"]["unknown"], u["request"]["answered"]), (3, 1, 0, 2, 2))
        self.assertEqual((u["auto"]["delivered"], u["auto"]["good"], u["auto"]["unknown"], u["auto"]["answered"]), (2, 1, 1, 1))   # p5 = 答えなし = 不明
        self.assertEqual((u["manual"]["delivered"], u["manual"]["good"]), (1, 1))
        self.assertEqual((u["all"]["delivered"], u["all"]["good"], u["all"]["bad"], u["all"]["unknown"], u["all"]["answered"]), (6, 3, 0, 3, 4))   # 答え = 行がある = p1・p2(古い reject)・p4・p6
        self.assertEqual((u["all"]["goodRate"], u["all"]["badRate"], u["all"]["badOfJudged"]), (0.5, 0.0, 0.0))
        self.assertEqual(self.h3(env)["judgments"], 5)

    def test_used_match_by_mark_when_no_pack_name_and_last_wins(self):
        env = Env(self)
        env.deliver("a.zip", [("p1", "m1")])
        env.judge(1, "reject", vid=V1, mid="m1", who="friend", origin="request", via="friend_verdict")                 # ref.pack 無し = (videoId, markId) で突き合わせる
        j = env.judge(2, "adopt", vid=V1, mid="m1", who="friend", origin="request", via="friend_verdict")              # 後の判断が勝つ
        self.assertEqual(self.h3(env)["used"]["request"]["good"], 1)
        env.judge(3, "retract", vid=V1, mid="m1", who="friend", origin="request", via="friend_verdict", of=j["id"])   # 取り消し = 答えなしに戻る(古い reject は後から復活しない)
        g = self.h3(env)["used"]["request"]
        self.assertEqual((g["good"], g["bad"], g["unknown"], g["answered"]), (0, 0, 1, 0))

    def test_used_period_and_no_deliveries(self):
        env = Env(self)
        self.assertEqual(self.h3(env)["used"]["all"], {"delivered": 0, "good": 0, "bad": 0, "unknown": 0, "answered": 0, "goodRate": None, "badRate": None,
                                                       "badReasons": {"boring": 0, "cut": 0, "other": 0}, "badOfJudged": None,
                                                       "scene": {"judged": 0, "boring": 0}, "sceneBoringRate": None})
        env.deliver("a.zip", [("p1", "m1")], at="2026-10-01")
        env.deliver("b.zip", [("p2", "m2")], at="2026-10-09")
        self.assertEqual(self.h3(env)["used"]["all"]["delivered"], 2)
        self.assertEqual(self.h3(env, since="2026-10-05")["used"]["all"]["delivered"], 1)
        self.assertEqual(self.h3(env, until="2026-10-05")["used"]["all"]["delivered"], 1)

    def test_quality_origin_and_reason(self):
        env = Env(self)
        env.judge(1, "quality_good", vid=V1, mid="m1", origin="request", via="check")
        env.judge(2, "quality_good", vid=V1, mid="m2", origin="auto", via="check")
        env.judge(3, "quality_bad", vid=V1, mid="m3", origin="auto", via="check", reason="cut")
        b = env.judge(4, "quality_bad", vid=V1, mid="m4", origin="auto", via="check", reason="cut")
        env.judge(5, "quality_bad", vid=V1, mid="m5", origin="request", via="check", reason="boring")
        env.judge(6, "retract", vid=V1, mid="m4", origin="auto", via="check", of=b["id"])   # Z で取り消した答えは数えない
        env.judge(7, "adopt", vid=V1, mid="m1", origin="manual", via="review")             # 採否は物差し 3 に入らない
        env.judge(8, "quality_unknown", vid=V1, mid="m8", origin="auto", via="check")      # 不明 = 良い・悪いの数には入らない
        q = self.h3(env)["quality"]
        self.assertEqual((q["good"], q["bad"], q["unknown"], q["judged"], q["goodRate"]), (2, 2, 1, 4, 0.5))
        self.assertEqual(q["byOrigin"], {"request": {"good": 1, "bad": 1, "unknown": 0}, "auto": {"good": 1, "bad": 1, "unknown": 1}})
        self.assertEqual(q["reasons"], {"cut": 1, "boring": 1})

    def test_friend_good_bad_unknown_reasons_and_scene(self):
        env = Env(self)
        env.deliver("a.zip", [("p1", "m1"), ("p2", "m2"), ("p3", "m3"), ("p4", "m4")], origin="request", runId="rq1")   # 区間指定の実行
        env.deliver("b.zip", [("p5", "m5"), ("p6", "m6"), ("p7", "m7")], origin="request", runId="rn1")               # 区間指定でない実行
        env.runs([{"id": "rq1", "videoId": V1, "state": "done", "ranges": [[10, 20]]},
                  {"id": "rn1", "videoId": V1, "state": "done", "ranges": []}])
        env.judge(1, "bad", vid=V1, mid="m1", who="friend", origin="request", via="friend_verdict", reason="boring", ref={"pack": "p1"})
        env.judge(2, "good", vid=V1, mid="m2", who="friend", origin="request", via="friend_verdict", ref={"pack": "p2"})
        env.judge(3, "unknown", vid=V1, mid="m3", who="friend", origin="request", via="friend_verdict", by="auto", ref={"pack": "p3"})
        env.judge(5, "bad", vid=V1, mid="m5", who="friend", origin="request", via="friend_verdict", reason="boring", ref={"pack": "p5"})
        env.judge(6, "bad", vid=V1, mid="m6", who="friend", origin="request", via="friend_verdict", reason="cut", ref={"pack": "p6"})
        env.judge(7, "bad", vid=V1, mid="m7", who="friend", origin="request", via="friend_verdict", ref={"pack": "p7"})   # 理由なし = その他
        u = self.h3(env)["used"]["all"]
        self.assertEqual((u["delivered"], u["good"], u["bad"], u["unknown"], u["answered"]), (7, 1, 4, 2, 6))   # p4 = 答えなし
        self.assertEqual(u["badReasons"], {"boring": 2, "cut": 1, "other": 1})   # p1・p5 つまらない / p6 切り方が変 / p7 理由なし
        self.assertEqual((u["goodRate"], u["badRate"], u["badOfJudged"]), (0.1429, 0.5714, 0.8))
        self.assertEqual(u["scene"], {"judged": 3, "boring": 1})   # 区間指定の実行(rq1 = p1〜p4)を外す。p5 つまらない・p6 切り方が変・p7 理由なし
        self.assertEqual(u["sceneBoringRate"], 0.3333)

    def test_friend_range_is_passed_through_and_printed_first(self):
        env = build(self)
        env.deliver("a.zip", [("p1", "m1")])
        env.judge(1, "adopt", vid=V1, mid="m1", who="friend", origin="request", via="friend_verdict", ref={"pack": "p1"})
        res = env.evaluate()
        fr = res["friendRanges"]["overall"]
        self.assertEqual((res["human3"]["friendRange"]["hit"], res["human3"]["friendRange"]["hitRate"], res["human3"]["friendRange"]["ranges"]), (fr["hit"], fr["hitRate"], fr["ranges"]))
        text = printed(M.print_report, res)
        self.assertLess(text.index("物差し 3 本"), text.index("上位"))   # 3 本が先頭(古い物差しより前)


class FriendRanges(unittest.TestCase):
    """友人が時刻で指定した区間(friendRanges)を、自動の候補と比べる指標"""

    def fr(self, env, **kw):
        return env.evaluate(**kw)["friendRanges"]

    def test_hit_rule_boundaries(self):
        for rng, cand, want, case in [
            ((10.0, 110.0), (60.0, 100.0), True, "候補の真ん中(60)が区間の端ちょうど = 中"),
            ((10.0, 110.0), (60.5, 100.0), False, "真ん中が区間の外・重なりも半分に足りない"),
            ((10.0, 110.0), (0.0, 60.0), True, "候補の真ん中が区間の端ちょうど"),
            ((10.0, 110.0), (0.0, 59.0), False, "候補の真ん中が区間の外"),
            ((10.0, 20.0), (30.0, 40.0), False, "離れている"),
            ((100.0, 140.0), (120.0, 121.0), True, "区間が短く、候補の真ん中を含む"),
            ((100.0, 140.0), (101.0, 102.0), False, "区間が短く、候補の真ん中を含まない"),
        ]:
            with self.subTest(case):
                self.assertEqual(M.friend_hit(rng, cand), want)
        self.assertEqual(M.friend_gap((300.0, 340.0), (345.0, 400.0)), 5.0)
        self.assertEqual(M.friend_gap((300.0, 340.0), (330.0, 400.0)), 0.0)

    def test_rank_top_n_miss_and_lengths(self):
        env = Env(self)
        env.data({V1: eight()})
        env.runs([run_row(V1, [[110, 130], [510, 530], [1300, 1350], [5000, 5200]])])
        fr = self.fr(env)
        o = fr["overall"]
        self.assertEqual((o["ranges"], o["analyzedRanges"], o["unanalyzedRanges"], o["videos"]), (4, 4, 0, 1))
        self.assertEqual((o["hit"], o["miss"]), (3, 1))
        self.assertEqual(o["top"]["top5"], {"hit": 2, "rate": 0.5})    # 順位 1・3 が上位 5 に入る。順位 7 は入らない
        self.assertEqual(o["top"]["top10"], {"hit": 3, "rate": 0.75})
        self.assertEqual(o["top"]["top20"], {"hit": 3, "rate": 0.75})
        self.assertEqual(o["top"]["all"], {"hit": 3, "rate": 0.75})
        self.assertEqual((o["hitRate"], o["missRate"]), (0.75, 0.25))
        self.assertEqual((o["bestRank"]["min"], o["bestRank"]["max"]), (1, 7))
        self.assertEqual(o["bestScore"]["min"], 2.0)     # 順位 7 の点数 = 9 - 7
        # 長さごと: 20 秒 2 個(2 当たり)・50 秒 1 個(当たり)・200 秒 1 個(見逃し)
        bl = o["byLength"]
        self.assertEqual((bl["short"]["analyzedRanges"], bl["short"]["hit"], bl["short"]["hitRate"]), (2, 2, 1.0))
        self.assertEqual((bl["mid"]["analyzedRanges"], bl["mid"]["hit"]), (1, 1))
        self.assertEqual((bl["long"]["analyzedRanges"], bl["long"]["hit"], bl["long"]["hitRate"]), (1, 0, 0.0))
        # 端のずれ(120 秒未満で当たった 3 個。候補 − 区間)
        e = o["edges"]
        self.assertEqual(e["ranges"], 3)
        self.assertEqual(e["dStartSigned"]["min"], -10.0)
        self.assertEqual(e["dEndSigned"]["min"], -10.0)
        self.assertEqual(e["dStart"]["median"], 10.0)
        # 配信ごと
        self.assertEqual(len(fr["byVideo"]), 1)
        v = fr["byVideo"][0]
        self.assertEqual((v["videoId"], v["analyzed"], v["candidates"], v["hit"]), (V1, True, 8, 3))
        self.assertEqual([i["rank"] for i in v["items"]], [1, 3, 7, None])

    def test_miss_nearest_candidate(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 300.0, 340.0, 4.0), mark("b", 900.0, 940.0, 1.0)])})
        env.runs([run_row(V1, [[345, 400], [1500, 1560]])])
        fr = self.fr(env)
        o = fr["overall"]
        self.assertEqual((o["hit"], o["miss"]), (0, 2))
        m = o["misses"]
        self.assertEqual((m["missed"], m["withNearAuto"], m["noAuto"]), (2, 2, 0))
        self.assertEqual((m["near15s"], m["farOrNone"]), (1, 1))
        self.assertEqual(m["nearDistance"]["min"], 5.0)
        self.assertEqual(m["nearDistance"]["max"], 560.0)
        self.assertEqual(m["nearScore"]["max"], 4.0)
        it = fr["byVideo"][0]["items"]
        self.assertEqual((it[0]["nearRank"], it[0]["nearScore"]), (1, 4.0))
        self.assertEqual((it[1]["nearRank"], it[1]["nearScore"]), (2, 1.0))

    def test_unanalyzed_video_is_separate(self):
        env = Env(self)
        # V1: 解析済み / V2: 解析の記録も候補も無い(解析なしで区間だけを取りに行った依頼)/ V3: archive の解析だけがある
        env.data({V1: video(V1, [mark("a", 100.0, 140.0, 5.0)]),
                  V2: {"id": V2, "kind": "youtube", "title": "u", "analysis": None, "duration": 3000.0, "marks": [mark("r1", 98.0, 142.0, None, "adopted", src="manual", adoptedBy="request")]},
                  V3: {"id": V3, "kind": "youtube", "title": "w", "analysis": None, "duration": 3000.0, "marks": []}})
        env.archive(V3, [{"start": 500.0, "end": 540.0, "score": 3.0, "peak": 1, "parts": {}}], ms("2026-09-02"))
        env.runs([run_row(V1, [[110, 130]]), run_row(V2, [[100, 140]]), run_row(V3, [[510, 530], [5000, 5100]])])
        fr = self.fr(env)
        o = fr["overall"]
        self.assertEqual((o["videos"], o["analyzedVideos"], o["unanalyzedVideos"]), (3, 2, 1))
        self.assertEqual((o["ranges"], o["analyzedRanges"], o["unanalyzedRanges"]), (4, 3, 1))
        self.assertEqual((o["hit"], o["miss"]), (2, 1))       # 未解析の V2 は見逃しに入れない
        self.assertEqual(o["missRate"], round(1 / 3, 4))
        v2 = next(v for v in fr["byVideo"] if v["videoId"] == V2)
        self.assertFalse(v2["analyzed"])
        self.assertEqual((v2["ranges"], v2["unanalyzedRanges"], v2["miss"], v2["hit"]), (1, 1, 0, 0))
        self.assertIsNone(v2["items"][0]["rank"])

    def test_merge_same_ranges(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 100.0, 140.0, 5.0), mark("r1", 98.0, 142.0, None, "adopted", src="manual", adoptedBy="request")])})
        # 同じ区間を 2 回の実行で / ±0.6 秒の違い / 別の区間 / 出どころ 2 のマークも同じ区間(余白 2 秒を引くと 100-140)
        env.runs([run_row(V1, [[100, 140]], day="2026-09-05"), run_row(V1, [[100.5, 139.6], [300, 330]], day="2026-09-06")])
        o = self.fr(env)["overall"]
        self.assertEqual(o["ranges"], 2)
        self.assertEqual(o["sources"], {"runs": 2, "marks": 0})
        env.runs([run_row(V1, [[100, 140]]), run_row(V1, [[101, 140]])])    # 1 秒違えば別の区間(マークは 100-140 と同じ)
        o = self.fr(env)["overall"]
        self.assertEqual(o["ranges"], 2)
        self.assertEqual(o["sources"], {"runs": 2, "marks": 0})

    def test_source2_marks_unpad_and_clamp(self):
        env = Env(self)
        dv = video(V1, [mark("a", 100.0, 140.0, 5.0), mark("b", 600.0, 640.0, 4.0),
                        mark("r1", 98.0, 142.0, None, "adopted", src="manual", adoptedBy="request"),      # 100-140 に戻る
                        mark("r2", 0.0, 32.0, None, "exported", src="manual", adoptedBy="request"),      # 開始が 0 で切られていた: 0 のまま
                        mark("r3", 898.0, 1000.0, None, "adopted", src="manual", adoptedBy="request"),   # 終了が長さで切られていた: 1000 のまま
                        mark("h1", 2000.0, 2030.0, None, "adopted", src="manual"),                       # 人が手で足したマーク: 友人の区間ではない
                        mark("h2", 2100.0, 2130.0, None, "adopted", src="manual", adoptedBy="auto")])    # 自動採用の印
        dv["duration"] = 1000.0
        env.data({V1: dv})
        fr = self.fr(env)
        o = fr["overall"]
        self.assertEqual((o["ranges"], o["sources"]), (3, {"runs": 0, "marks": 3}))
        its = {(i["start"], i["end"]): i for i in fr["byVideo"][0]["items"]}
        self.assertEqual(sorted(its), [(0.0, 30.0), (100.0, 140.0), (900.0, 1000.0)])
        self.assertEqual(its[(100.0, 140.0)]["rank"], 1)
        # 実行の記録の区間(指定したまま)と同じ区間のマークは 1 つ(出どころ 1 を優先)。開始が切られたマークも、元の区間(1〜30)に合えば同じ
        env.runs([run_row(V1, [[1, 30], [900, 1000]])])
        o = self.fr(env)["overall"]
        self.assertEqual((o["ranges"], o["sources"]), (3, {"runs": 2, "marks": 1}))   # 1-30・900-1000(記録)+ 98-142 のマーク(→ 100-140)
        u = M.unpad_mark({"start": 1.0, "end": 1.2}, 100.0)    # 余白を引くと残らない短い区間はそのまま
        self.assertEqual(u[:2], (1.0, 1.2))

    def test_since_until_by_run_time(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 100.0, 140.0, 5.0)])})
        env.runs([run_row(V1, [[110, 130]], day="2026-09-05"), run_row(V1, [[400, 430]], day="2026-10-05")])
        self.assertEqual(self.fr(env)["overall"]["ranges"], 2)
        self.assertEqual(self.fr(env, since="2026-10-01")["overall"]["ranges"], 1)
        self.assertEqual(self.fr(env, until="2026-09-30")["overall"]["ranges"], 1)
        self.assertEqual(self.fr(env, since="2026-09-05", until="2026-09-05")["overall"]["ranges"], 1)   # until はその日を含む
        self.assertEqual(self.fr(env, since="2027-01-01")["overall"]["ranges"], 0)
        self.assertEqual(self.fr(env, since="2027-01-01")["byVideo"], [])

    def test_few_note(self):
        env = Env(self)
        env.data({V1: eight()})
        env.runs([run_row(V1, [[110, 130]])])
        fr = self.fr(env)
        self.assertTrue(fr["few"] and fr["fewNote"])
        vids, rows = {}, []
        for i in range(M.FRIEND_FEW_VIDEOS):
            vid = "vid%08d" % i
            vids[vid] = eight(vid)
            rows.append(run_row(vid, [[110 + 200 * k, 130 + 200 * k] for k in range(4)]))
        self.assertEqual(M.FRIEND_FEW_VIDEOS * 4, M.FRIEND_FEW_RANGES)
        env.data(vids)
        env.runs(rows)
        fr = self.fr(env)
        self.assertFalse(fr["few"])
        self.assertEqual(fr["fewNote"], "")
        self.assertEqual(fr["overall"]["analyzedRanges"], M.FRIEND_FEW_RANGES)
        rows.pop()    # 配信が 4 本・区間 16 個: 少ない
        env.runs(rows)
        self.assertTrue(self.fr(env)["few"])

    def test_contribution_from_parts(self):
        env = Env(self)
        a = mark("a", 100.0, 140.0, 5.0, parts={"audio": 2.0, "chat": 0.3, "comments": 0.0}, reasons=["音量が急上昇"])
        b = mark("b", 300.0, 340.0, 4.0, parts={"audio": 0.5, "chat": 3.0, "comments": 1.0}, reasons=["チャットが急増", "コメント欄で時刻が指定されている"])
        c = mark("c", 500.0, 540.0, 3.0)    # 内訳なし
        env.data({V1: video(V1, [a, b, c])})
        env.runs([run_row(V1, [[110, 130], [310, 330], [510, 530]])])
        c_ = self.fr(env)["overall"]["contribution"]
        self.assertEqual(c_["hits"], 2)      # 内訳の無い候補は数えない
        self.assertEqual(c_["on"], {"audio": 1, "chat": 1, "comments": 1, "heat": 0})   # heat = 点に足した heatmap(10-26)
        self.assertEqual(c_["dominant"], {"audio": 1, "chat": 1, "comments": 0, "heat": 0})
        self.assertEqual(c_["reasons"], {"音量が急上昇": 1, "チャットが急増": 1, "コメント欄で時刻が指定されている": 1})
        # 内訳がどの候補にも無ければ None(表示も出さない)
        env.data({V1: video(V1, [mark("c", 500.0, 540.0, 3.0)])})
        env.runs([run_row(V1, [[510, 530]])])
        self.assertIsNone(self.fr(env)["overall"]["contribution"])

    def test_no_ranges_and_video_not_in_data(self):
        """区間が無い・区間の配信が data.json に無い(未解析)でも数えて表示まで落ちない"""
        env = build(self)
        fr = self.fr(env)
        self.assertEqual((fr["overall"]["ranges"], fr["byVideo"]), (0, []))
        printed(M.main, ["--data-dir", env.root])
        env2 = Env(self)
        env2.data({V1: eight()})
        env2.runs([run_row(V1, [[110, 130], [5000, 5100]]), run_row(V2, [[1, 5]])])
        o = self.fr(env2)["overall"]
        self.assertEqual((o["hit"], o["miss"], o["unanalyzedVideos"], o["unanalyzedRanges"]), (1, 1, 1, 1))
        printed(M.main, ["--data-dir", env2.root])

    def test_existing_metrics_unchanged_by_ranges(self):
        env = build(self)
        before = env.evaluate()
        env.runs([build_run(created=ms("2026-09-05"), ranges=[[110, 130], [5000, 5100]])])
        after = env.evaluate()
        self.assertEqual(after["overall"], before["overall"])
        self.assertEqual(after["byType"], before["byType"])
        self.assertEqual(after["byVideo"], before["byVideo"])
        self.assertEqual(after["friendRanges"]["overall"]["ranges"], 2)
        self.assertEqual(before["friendRanges"]["overall"]["ranges"], 0)


class ClipLength(unittest.TestCase):
    """友人が指定した区間の長さ(clipLength = src/flow/lengthhint の数。細かい式は tests/flow/test_lengthhint.py)"""

    def cl(self, env):
        return env.evaluate()["clipLength"]

    def test_friend_ranges_to_clip_length(self):
        env = Env(self)
        env.data({V1: video(V1, [], typ="歌枠"), V2: video(V2, [], typ="雑談")})
        env.runs([run_row(V1, [[100, 140], [300, 345], [500, 502], [900, 1600]]),
                  run_row(V2, [[10, 70]], day="2026-09-06"), run_row(V2, [[10, 70]], day="2026-09-07")])   # 同じ区間は 1 つ
        cl = self.cl(env)
        self.assertEqual(cl["schema"], lengthhint.SCHEMA)
        # 見本 40・45・60 秒(2 秒と 700 秒は外れ値で数だけ)
        self.assertEqual((cl["length"], cl["p50"], cl["samples"], cl["videos"], cl["outliers"]), (45, 45.0, 3, 2, 2))
        self.assertFalse(cl["enough"])
        self.assertEqual(sorted(cl["byType"]), ["歌枠", "雑談"])
        self.assertEqual((cl["byType"]["雑談"]["length"], cl["byType"]["歌枠"]["samples"]), (60, 2))

    def test_enough_boundary(self):
        def run(videos, per):
            env = Env(self)
            vids, rows = {}, []
            for i in range(videos):
                vid = "vid%08d" % i
                vids[vid] = video(vid, [])
                rows.append(run_row(vid, [[k * 100, k * 100 + 60] for k in range(per)]))
            env.data(vids)
            env.runs(rows)
            return self.cl(env)
        cl = run(5, 4)
        self.assertEqual((cl["samples"], cl["videos"], cl["enough"], cl["length"]), (20, 5, True, 60))
        self.assertFalse(run(5, 3)["enough"])      # 15 個
        self.assertFalse(run(4, 5)["enough"])      # 20 個だが配信 4 本
        self.assertEqual((lengthhint.ENOUGH_SAMPLES, lengthhint.ENOUGH_VIDEOS), (20, 5))

    def test_print_and_no_write(self):
        env = Env(self)
        env.data({V1: video(V1, [], typ="歌枠")})
        env.runs([run_row(V1, [[100, 140]])])
        printed(M.main, ["--data-dir", env.root])   # 見本 1 個(少ない)でも表示で落ちない
        self.assertFalse(os.path.exists(os.path.join(env.studio, "evals")))   # --json なしでは何も書かない


if __name__ == "__main__":
    unittest.main()
