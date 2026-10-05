"""dev/eval_marks.py(盛り上がりの検出を、人の判定の記録で測る道具。線 C の土台)のテスト。リポジトリ直下で:

    python -m unittest dev/tests/test_eval_marks.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバーは動かさない。
"""
import contextlib
import gzip
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
import eval_marks as M  # noqa: E402
from ytt_core import txindex  # noqa: E402

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
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.studio = os.path.join(self.root, "studio")
        self.logs = os.path.join(self.root, "app", "logs")
        os.makedirs(self.studio)
        os.makedirs(self.logs)

    def data(self, videos):
        with open(os.path.join(self.studio, "data.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "clip-studio/v1", "videos": videos, "groups": {}}, f, ensure_ascii=False)

    def feedback(self, rows, name="feedback.jsonl"):
        with open(os.path.join(self.studio, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def archive(self, vid, cands, at):
        os.makedirs(os.path.join(self.studio, "archive"), exist_ok=True)
        with gzip.open(os.path.join(self.studio, "archive", vid + ".json.gz"), "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "videoId": vid, "type": "歌枠", "runs": [{"at": at, "candidates": cands}]}, f)

    def runs(self, rows):
        with open(os.path.join(self.logs, "autorun-runs.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def pack(self, media):
        """media(書き出した mp4 のパス)の隣に _pack を作り、パックを作った記録を cut2resolve の packs/ に置く"""
        d = txindex.pack_dir(media)
        os.makedirs(d)
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("x")
        pk = os.path.join(self.root, "cut2resolve", "packs")
        os.makedirs(pk, exist_ok=True)
        with open(os.path.join(pk, txindex.pack_key(d)), "w", encoding="utf-8") as f:
            json.dump({"schema": txindex.PACK_RECORD_SCHEMA, "dir": d, "files": ["a.txt"], "builtAt": ms("2026-09-02"), "textplus": True}, f)

    def evaluate(self, **kw):
        return M.evaluate(self.root, **kw)


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
        fb("2026-09-01", "adopt", "good", 102.0, 140.0, 5.0, auto0=[100.0, 140.0], dStart=2.0, dEnd=0.0),
        fb("2026-09-02", "export", "good", 102.0, 140.0, 5.0, auto0=[100.0, 140.0], dStart=2.0, dEnd=0.0),
        fb("2026-09-01", "reject", "bad", 300.0, 340.0, 4.0, auto0=[300.0, 340.0]),
        fb("2026-09-01", "delete", "bad", 1000.0, 1040.0, 6.0, auto0=[1000.0, 1040.0]),
        fb("2026-09-03", "manual_add", "miss", 900.0, 930.0, src="manual", autoCount=4, nearAuto={"score": 2.0, "distance": 8.0, "start": 700.0, "end": 740.0, "status": ""}),
        fb("2026-09-03", "manual_add", "miss", 2000.0, 2030.0, src="manual", autoCount=4, nearAuto={"score": 2.0, "distance": 900.0, "start": 700.0, "end": 740.0, "status": ""}),
        fb("2026-09-03", "manual_remove", "unmiss", 2000.0, 2030.0, src="manual"),
        fb("2026-09-04", "unadopt", "retract", 500.0, 540.0, 3.0, auto0=[500.0, 540.0], prevStatus="adopted"),
        fb("2026-09-04", "adopt", "good", 900.0, 930.0, src="manual"),
    ])
    env.runs([{"v": 1, "id": "r1", "kind": "video", "videoId": V1, "state": "done", "requestId": "20260901-000000-abcdef",
               "steps": [{"key": "adopt", "state": "done"}, {"key": "deliver", "state": "done"}], "marks": ["mA", "mD"]}])
    return env


class EvalMarks(unittest.TestCase):
    def test_metrics(self):
        r = build(self).evaluate()
        o = r["overall"]
        t5 = o["top"]["top5"]
        self.assertEqual(t5["items"], 5)   # E・A・B・C・D(点数の順)
        self.assertEqual((t5["good"], t5["bad"], t5["judged"]), (1, 2, 3))
        self.assertEqual(t5["adoptRate"], round(1 / 3, 4))
        self.assertEqual(t5["adoptRateAll"], round(1 / 5, 4))
        self.assertEqual((t5["unjudged"], t5["machine"], t5["unrecorded"]), (1, 1, 0))   # 判定なしは分母に入れない・まとめて実行の採用は良いに数えない
        self.assertEqual(o["top"]["all"]["items"], 5)
        al = o["top"]["all"]
        self.assertEqual((al["exported"], al["packed"], al["delivered"]), (1, 1, 1))
        self.assertEqual((al["exportRate"], al["packRate"], al["deliveredRate"]), (1.0, 1.0, 1.0))
        self.assertEqual(o["videos"], 1)
        self.assertTrue(r["meta"]["few"])   # 配信 10 本未満
        self.assertIn("まだ少ない", r["meta"]["fewNote"])

    def test_top_n_order(self):
        """上位 N は点数の高い順。N=1 なら削除した候補 E(6.0)だけ = 悪い"""
        env = build(self)
        _env, studio, _app = M.locate(env.root)
        vids, _ = M.build_videos(studio, M.load_feedback(studio), M.load_runs(os.path.join(env.root, "app")), _env)
        order = [(i["score"], i["verdict"]) for i in M.ranked(vids[V1]["auto"])]
        self.assertEqual(order, [(6.0, "bad"), (5.0, "good"), (4.0, "bad"), (3.0, "none"), (2.0, "machine")])

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
        self.assertEqual((mm["marks"], mm["good"]), (1, 1))   # 手動マークの採用(まとめて実行の記録では機械になるが、人の adopt の行がある)

    def test_auto_adopt_not_counted_good(self):
        """行も無く、実行記録の「採用」の段が動いた配信のマーク = 自動採用 → 良いに数えない。実行記録も無ければ「記録なし」(--status-fallback で数える)"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted"), mark("b", 100.0, 140.0, 2.0)]),
                  V2: video(V2, [mark("c", 10.0, 50.0, 3.0, "adopted")], typ="雑談")})
        env.runs([{"v": 1, "id": "r", "kind": "video", "videoId": V1, "state": "done", "steps": [{"key": "adopt", "state": "done"}]}])
        r = env.evaluate()
        self.assertEqual(r["byVideo"][0]["top"]["all"]["machine"], 1)
        self.assertEqual(r["overall"]["top"]["all"]["good"], 0)
        self.assertEqual(r["overall"]["top"]["all"]["unrecorded"], 1)
        self.assertTrue(any("自動採用" in n for n in r["meta"]["notes"]))
        self.assertTrue(any("status-fallback" in n for n in r["meta"]["notes"]))
        r2 = env.evaluate(status_fallback=True)
        self.assertEqual(r2["overall"]["top"]["all"]["good"], 1)   # V2 だけ(V1 は自動採用のまま)
        self.assertEqual(r2["overall"]["top"]["all"]["machine"], 1)

    def test_human_adopt_after_machine_counts(self):
        """自動採用の配信でも、人の adopt の行があるマークは良い"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted"), mark("b", 100.0, 140.0, 2.0, "adopted")])})
        env.feedback([fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0])])
        env.runs([{"v": 1, "id": "r", "kind": "video", "videoId": V1, "state": "done", "steps": [{"key": "adopt", "state": "done"}]}])
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["good"], al["machine"]), (1, 1))

    def test_since_until(self):
        env = build(self)
        later = mark("n1", 10.0, 50.0, 9.0, "adopted", created=ms("2026-10-02"))
        with open(os.path.join(env.studio, "data.json"), encoding="utf-8") as f:
            d = json.load(f)
        d["videos"][V2] = video(V2, [later, mark("n2", 100.0, 140.0, 8.0, created=ms("2026-10-02"))], typ="雑談")
        env.data(d["videos"])
        with open(os.path.join(env.studio, "feedback.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(fb("2026-10-02", "adopt", "good", 10.0, 50.0, 9.0, auto0=[10.0, 50.0], videoId=V2, type="雑談")) + "\n")
            f.write(json.dumps(fb("2026-10-03", "manual_add", "miss", 500.0, 530.0, src="manual", videoId=V2, autoCount=2)) + "\n")
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
        env.feedback([fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0])])
        env.archive(V1, [{"start": 10.0, "end": 50.0, "score": 3.0}, {"start": 200.0, "end": 240.0, "score": 2.5}], ms("2026-09-01"))
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["items"], al["good"], al["unjudged"]), (2, 1, 1))

    def test_old_feedback_and_dedupe(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 3.0, "adopted")])})
        row = fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0])
        env.feedback([row], "feedback.jsonl.old")
        env.feedback([row, fb("2026-09-05", "manual_add", "miss", 500.0, 530.0, src="manual", autoCount=1)])   # 移す途中で止まった重なり
        with open(os.path.join(env.studio, "feedback.jsonl"), "ab") as f:
            f.write(b'{"ts": "2026-09-06T00:00:00", "videoId": ')   # 書きかけの行
        r = env.evaluate()
        self.assertEqual(r["overall"]["misses"]["added"], 1)
        self.assertEqual(r["overall"]["top"]["all"]["good"], 1)
        self.assertEqual(len(M.load_feedback(env.studio)), 2)

    def test_adopted_by_marks_and_rows(self):
        """adoptedBy(マーク・行)がある採用・書き出しは機械の判定。実行記録が無くても「記録なし」ではなく機械。
        markId のある新しい行は、実行記録の近似を使わない(人の adopt の行が無くても、adoptedBy が無ければ人の判定)"""
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 10.0, 50.0, 5.0, "adopted", adoptedBy="auto"), mark("b", 100.0, 140.0, 4.0, "exported", adoptedBy="request"),
                                 mark("c", 200.0, 240.0, 3.0, "exported"), mark("d", 300.0, 340.0, 2.0, "adopted")])})
        env.feedback([
            fb("2026-09-01", "export", "good", 100.0, 140.0, 4.0, auto0=[100.0, 140.0], markId="b", adoptedBy="request"),   # 機械が採用にしたものの書き出しの行
            fb("2026-09-01", "export", "good", 200.0, 240.0, 3.0, auto0=[200.0, 240.0], markId="c"),                        # 人が書き出した(adopt の行は無い)
        ])
        env.runs([{"v": 1, "id": "r", "kind": "video", "videoId": V1, "state": "done", "steps": [{"key": "adopt", "state": "done"}]}])   # 以前の近似なら c も機械になる
        al = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((al["good"], al["machine"], al["unrecorded"]), (1, 3, 0))   # c だけ良い。a・b は印で機械・d は印も行も無いが実行記録で機械(以前の近似)
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
        """markId のある行は ID で突き合わせる: 同じ区間でも別の ID のマークの行は混ぜない。ID の無い以前の行は区間で突き合わせる"""
        env = Env(self)
        env.data({V1: video(V1, [mark("x", 10.0, 50.0, 5.0, "adopted")])})
        env.feedback([fb("2026-09-01", "adopt", "good", 10.0, 50.0, 5.0, auto0=[10.0, 50.0], markId="x"),
                      fb("2026-09-01", "reject", "bad", 10.0, 50.0, 4.0, auto0=[10.0, 50.0], markId="y"),       # 別のマーク y(消えた)。同じ区間でも x に混ぜない
                      fb("2026-09-02", "reject", "bad", 200.0, 240.0, 3.0, auto0=[200.0, 240.0])])              # ID の無い以前の行
        r = env.evaluate()["overall"]["top"]["all"]
        self.assertEqual((r["items"], r["good"], r["bad"]), (3, 1, 2))
        # ID の無い以前の行は区間で data のマークに付く
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
            self.assertIsNone(r["overall"]["top"]["top5"]["adoptRate"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                M.print_report(r)
            self.assertIn("データがありません", buf.getvalue())

    def test_corrupt_data_json(self):
        env = Env(self)
        with open(os.path.join(env.studio, "data.json"), "w") as f:
            f.write("{broken")
        self.assertEqual(env.evaluate()["meta"]["videos"], 0)

    def test_cli_json_saved_and_read_only(self):
        env = build(self)
        before = {n: os.path.getmtime(os.path.join(env.studio, n)) for n in os.listdir(env.studio) if os.path.isfile(os.path.join(env.studio, n))}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = M.main(["--data-dir", env.root])
        out = buf.getvalue()
        self.assertIn("★ まだ少ない", out)
        self.assertIn("上位", out)
        self.assertFalse(os.path.exists(os.path.join(env.studio, "evals")))   # --json が無ければ何も書かない
        with contextlib.redirect_stdout(io.StringIO()):
            M.main(["--data-dir", env.root, "--json", "--since", "2026-01-01"])
        d = os.path.join(env.studio, "evals", "marks")
        files = os.listdir(d)
        self.assertEqual(len(files), 1)
        with open(os.path.join(d, files[0]), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["meta"]["schema"], M.SCHEMA)
        self.assertEqual(saved["overall"]["top"]["top5"], res["overall"]["top"]["top5"])   # 画面と同じ形・同じ値
        after = {n: os.path.getmtime(os.path.join(env.studio, n)) for n in before}
        self.assertEqual(before, after)   # 入力は書き換えない

    def test_many_videos_not_few(self):
        env = Env(self)
        vids = {}
        rows = []
        for i in range(M.FEW_VIDEOS):
            vid = "vid%08d" % i
            vids[vid] = video(vid, [mark("a%d" % i, 10.0, 50.0, 3.0, "adopted")])
            rows.append(fb("2026-09-01", "adopt", "good", 10.0, 50.0, 3.0, auto0=[10.0, 50.0], videoId=vid))
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


class FriendRanges(unittest.TestCase):
    """友人が時刻で指定した区間(friendRanges)を、自動の候補と比べる指標"""

    def fr(self, env, **kw):
        return env.evaluate(**kw)["friendRanges"]

    def test_hit_rule_boundaries(self):
        self.assertTrue(M.friend_hit((10.0, 110.0), (60.0, 100.0)))     # 候補の真ん中(60)が区間の端ちょうど = 中
        self.assertFalse(M.friend_hit((10.0, 110.0), (60.5, 100.0)))    # 真ん中が区間の外・重なりも半分に足りない
        self.assertTrue(M.friend_hit((10.0, 110.0), (0.0, 60.0)))
        self.assertFalse(M.friend_hit((10.0, 110.0), (0.0, 59.0)))
        self.assertFalse(M.friend_hit((10.0, 20.0), (30.0, 40.0)))      # 離れている
        self.assertTrue(M.friend_hit((100.0, 140.0), (120.0, 121.0)))   # 区間が短く、候補の真ん中を含む
        self.assertFalse(M.friend_hit((100.0, 140.0), (101.0, 102.0)))
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
        self.assertTrue(any("未解析" in n for n in fr["notes"]))

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
        self.assertTrue(any("取りこぼし" in n for n in fr["notes"]))
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
        self.assertTrue(fr["few"])
        self.assertIn("まだ少ない", fr["fewNote"])
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
        self.assertEqual(c_["on"], {"audio": 1, "chat": 1, "comments": 1})
        self.assertEqual(c_["dominant"], {"audio": 1, "chat": 1, "comments": 0})
        self.assertEqual(c_["reasons"], {"音量が急上昇": 1, "チャットが急増": 1, "コメント欄で時刻が指定されている": 1})
        # 内訳がどの候補にも無ければ None(表示も出さない)
        env.data({V1: video(V1, [mark("c", 500.0, 540.0, 3.0)])})
        env.runs([run_row(V1, [[510, 530]])])
        self.assertIsNone(self.fr(env)["overall"]["contribution"])

    def test_no_ranges_and_print(self):
        env = build(self)
        fr = self.fr(env)
        self.assertEqual(fr["overall"]["ranges"], 0)
        self.assertEqual(fr["byVideo"], [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            M.main(["--data-dir", env.root])
        self.assertIn("友人が時刻で指定した区間", buf.getvalue())
        self.assertIn("まだありません", buf.getvalue())
        env2 = Env(self)
        env2.data({V1: eight()})
        env2.runs([run_row(V1, [[110, 130], [5000, 5100]]), run_row(V2, [[1, 5]])])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            M.main(["--data-dir", env2.root])
        out = buf.getvalue()
        self.assertIn("拾えた率", out)
        self.assertIn("見逃し 1 個", out)
        self.assertIn("未解析", out)
        self.assertIn("★ まだ少ない", out)

    def test_existing_metrics_unchanged_by_ranges(self):
        env = build(self)
        before = env.evaluate()
        env.runs([{"v": 1, "id": "r1", "kind": "video", "videoId": V1, "state": "done", "requestId": "20260901-000000-abcdef",
                   "steps": [{"key": "adopt", "state": "done"}, {"key": "deliver", "state": "done"}], "marks": ["mA", "mD"],
                   "created": ms("2026-09-05"), "ranges": [[110, 130], [5000, 5100]]}])
        after = env.evaluate()
        self.assertEqual(after["overall"], before["overall"])
        self.assertEqual(after["byType"], before["byType"])
        self.assertEqual(after["byVideo"], before["byVideo"])
        self.assertEqual(after["friendRanges"]["overall"]["ranges"], 2)
        self.assertEqual(before["friendRanges"]["overall"]["ranges"], 0)

    def test_json_contains_friend_ranges(self):
        env = Env(self)
        env.data({V1: eight()})
        env.runs([run_row(V1, [[110, 130]])])
        with contextlib.redirect_stdout(io.StringIO()):
            M.main(["--data-dir", env.root, "--json"])
        d = os.path.join(env.studio, "evals", "marks")
        with open(os.path.join(d, os.listdir(d)[0]), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["friendRanges"]["overall"]["hit"], 1)


def ranges_over(vid, n, ratio_pad=(10, 60), typ="歌枠", **kw):
    """n 個の自動の候補(k 番目は 200k 秒から 45 秒・山は +30 秒)を持つ配信と、その山を含む友人の区間 n 個。ratio_pad = (山より前の秒, 区間の長さ)= 山の位置は 前 ÷ 長さ"""
    dv = video(vid, [mark("p%d" % k, 200.0 * k, 200.0 * k + 45, 5.0 - k * 0.01, peak=200.0 * k + 30) for k in range(n)], typ=typ)
    return dv, [[200.0 * k + 30 - ratio_pad[0], 200.0 * k + 30 - ratio_pad[0] + ratio_pad[1]] for k in range(n)]


class ClipLength(unittest.TestCase):
    """人が選んだ区間の長さ(clipLength)と、自動の長さの目安(suggest)"""

    def cl(self, env, **kw):
        return env.evaluate(**kw)["clipLength"]

    def test_sources_dedupe_outliers_and_median(self):
        env = Env(self)
        marks = [
            mark("mA", 105.0, 175.0, 5.0, "adopted", auto0=[100.0, 145.0], peak=130.0),     # 端を直した良い自動: 70 秒
            mark("mK", 300.0, 345.0, 4.0, "adopted", peak=320.0),                          # 直さなかった良い自動: 45 秒(kept)
            mark("mMa", 700.0, 745.0, 3.0, "adopted", adoptedBy="auto", peak=720.0),       # まとめて実行の自動採用: 見本にしない
            mark("mO", 500.0, 502.0, 2.0, "adopted", auto0=[500.0, 545.0], peak=520.0),    # 直して 2 秒: 外れ値
            mark("mF", 900.0, 945.0, 1.5, peak=930.0),                                      # 候補のまま(判定なし): 見本にしない
            mark("mG", 1480.0, 1525.0, 1.0, peak=1510.0),
            mark("rReq", 1498.0, 1542.0, None, "adopted", src="manual", adoptedBy="request")]   # 依頼のマーク(友人の区間 1500-1540 の余白つき)
        env.data({V1: video(V1, marks)})
        env.feedback([
            fb("2026-09-01", "adopt", "good", 105.0, 175.0, 5.0, auto0=[100.0, 145.0]),
            fb("2026-09-01", "adopt", "good", 300.0, 345.0, 4.0, auto0=[300.0, 345.0]),
            fb("2026-09-01", "adopt", "good", 500.0, 502.0, 2.0, auto0=[500.0, 545.0]),
            fb("2026-09-03", "manual_add", "miss", 900.0, 960.0, src="manual"),                           # 手で足した 60 秒
            fb("2026-09-03", "manual_add", "miss", 1200.0, 1230.0, src="manual"),                         # 足して消した: 数えない
            fb("2026-09-03", "manual_remove", "unmiss", 1200.0, 1230.0, src="manual"),
            fb("2026-09-03", "manual_add", "miss", 2000.0, 2700.0, src="manual"),                         # 700 秒: 外れ値
            fb("2026-09-03", "manual_add", "miss", 1500.0, 1540.0, src="manual", markId="x2"),            # 友人の区間と同じ: friend で数える
            fb("2026-09-03", "manual_add", "miss", 1498.0, 1542.0, src="manual", markId="x3"),            # 友人の区間 + 余白と同じ
            fb("2026-09-03", "manual_add", "miss", 1498.0, 1542.0, src="manual", markId="rReq"),          # 依頼のマークの id
        ])
        env.runs([run_row(V1, [[1500, 1540]]), run_row(V2, [[10, 100]])])   # V2 は解析していない配信(長さは使える)
        cl = self.cl(env)
        s = cl["samples"]
        self.assertEqual((s["friend"]["n"], s["friend"]["videos"], s["friend"]["outliers"]), (2, 2, 0))
        self.assertEqual((s["manual"]["n"], s["manual"]["outliers"]), (1, 1))
        self.assertEqual((s["adjusted"]["n"], s["adjusted"]["outliers"]), (1, 1))
        self.assertEqual((s["kept"]["n"], s["kept"]["outliers"]), (1, 0))
        self.assertEqual(s["kept"]["length"]["p50"], 45.0)
        self.assertEqual((s["all"]["n"], s["all"]["outliers"]), (5, 2))
        self.assertEqual(s["used"]["n"], 4)                     # friend 2 + manual 1 + adjusted 1(kept は入れない)
        self.assertEqual(s["used"]["length"]["min"], 40.0)
        self.assertEqual(s["used"]["length"]["max"], 90.0)
        sg = cl["suggest"]
        self.assertEqual(sg["length"], 65)                     # 40・60・70・90 の中央値
        self.assertEqual((sg["p25"], sg["p75"]), (55.0, 75.0))
        self.assertEqual((sg["samples"], sg["videos"], sg["kept"]), (4, 2, 1))
        self.assertFalse(sg["enough"])
        self.assertIn("まだ少ない", sg["note"])
        self.assertIsNone(sg["preRatio"])                      # 山の位置の見本が 10 未満
        self.assertEqual(sg["preSamples"], 3)
        # 山の位置: 直した自動 (130-105)/70・手で足した 900-960 の中の山 930 → 0.5・友人 1500-1540 の中の山 1510 → 0.25
        pr = cl["peakRatio"]
        self.assertEqual(pr["adjusted"]["median"], round(25 / 70, 2))
        self.assertEqual(pr["manual"]["median"], 0.5)
        self.assertEqual(pr["friend"]["median"], 0.25)
        self.assertEqual(pr["kept"]["median"], round(20 / 45, 2))
        self.assertEqual(pr["used"]["n"], 3)
        self.assertEqual(cl["schema"], "youtube-tools-clip-length/v1")

    def test_fixture_counts_and_old_metrics(self):
        env = build(self)
        r = env.evaluate()
        self.assertEqual(set(r), {"meta", "overall", "byType", "byVideo", "friendRanges", "clipLength"})
        s = r["clipLength"]["samples"]
        self.assertEqual((s["adjusted"]["n"], s["adjusted"]["length"]["p50"]), (1, 38.0))   # mA: 102〜140
        self.assertEqual((s["manual"]["n"], s["manual"]["length"]["p50"]), (1, 30.0))       # 900〜930(2000 の分は足して消した)
        self.assertEqual((s["kept"]["n"], s["friend"]["n"]), (0, 0))
        self.assertEqual(r["overall"]["top"]["top5"]["good"], 1)
        self.assertEqual(r["friendRanges"]["overall"]["ranges"], 0)

    def test_median_clamp_and_peak_ratio_clamp(self):
        env = Env(self)
        dv, rg = ranges_over(V1, 10, ratio_pad=(19, 20))      # 山の位置 0.95・長さ 20
        env.data({V1: dv})
        env.runs([run_row(V1, rg)])
        cl = self.cl(env)
        self.assertEqual(cl["suggest"]["length"], 20)
        self.assertEqual(cl["suggest"]["preRatio"], 0.9)       # 0.95 → 上限 0.9 に収める
        dv, rg = ranges_over(V1, 10, ratio_pad=(5, 50))        # 山の位置 0.1・長さ 50
        env.data({V1: dv})
        env.runs([run_row(V1, rg)])
        self.assertEqual(self.cl(env)["suggest"]["preRatio"], 0.3)   # 0.1 → 下限 0.3
        dv, rg = ranges_over(V1, 10, ratio_pad=(20, 50))       # 0.4
        env.data({V1: dv})
        env.runs([run_row(V1, rg)])
        sg = self.cl(env)["suggest"]
        self.assertEqual((sg["preRatio"], sg["preSamples"], sg["length"]), (0.4, 10, 50))
        env.runs([run_row(V1, rg[:9])])                        # 山の位置の見本 9 個: 出さない
        self.assertIsNone(self.cl(env)["suggest"]["preRatio"])
        # 長さの収め方: 200 秒 → 120・8 秒 → 10
        env.runs([run_row(V1, [[0, 200], [300, 400], [500, 800]])])
        self.assertEqual(self.cl(env)["suggest"]["length"], 120)    # 200・100・300 の中央値 200 → 120
        env.runs([run_row(V1, [[0, 8]])])
        self.assertEqual(self.cl(env)["suggest"]["length"], 10)

    def test_enough_boundary(self):
        def run(videos, per):
            env = Env(self)
            vids, rows = {}, []
            for i in range(videos):
                vid = "vid%08d" % i
                dv, rg = ranges_over(vid, per)
                vids[vid] = dv
                rows.append(run_row(vid, rg))
            env.data(vids)
            env.runs(rows)
            return self.cl(env)["suggest"]
        sg = run(M.CL_ENOUGH_VIDEOS, 4)
        self.assertEqual((sg["samples"], sg["videos"], sg["enough"]), (20, 5, True))
        self.assertNotIn("まだ少ない", sg["note"])
        self.assertFalse(run(M.CL_ENOUGH_VIDEOS, 3)["enough"])        # 15 個
        self.assertFalse(run(M.CL_ENOUGH_VIDEOS - 1, 5)["enough"])    # 20 個だが配信 4 本
        self.assertEqual(M.CL_ENOUGH_SAMPLES, 20)

    def test_peak_from_auto0_and_pre_ratio(self):
        env = Env(self)
        # peak の項目が無い候補: 最初の自動区間 auto0 に preRatio を当てて戻す。解析の記録(analysis.spec)が無ければ 0.65
        dv = video(V1, [mark("a", 100.0, 145.0, 5.0)])     # 100 + 45 × 0.65 = 129.25
        env.data({V1: dv})
        env.runs([run_row(V1, [[109.25, 159.25]])])
        self.assertEqual(self.cl(env)["peakRatio"]["friend"]["median"], 0.4)
        dv["analysis"]["spec"] = {"preRatio": 0.5}         # 100 + 45 × 0.5 = 122.5 → (122.5 − 102.5) ÷ 50
        env.data({V1: dv})
        env.runs([run_row(V1, [[102.5, 152.5]])])
        self.assertEqual(self.cl(env)["peakRatio"]["friend"]["median"], 0.4)
        # archive の解析の記録にだけ preRatio がある配信
        os.makedirs(os.path.join(env.studio, "archive"), exist_ok=True)
        with gzip.open(os.path.join(env.studio, "archive", V3 + ".json.gz"), "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "videoId": V3, "type": "歌枠", "runs": [{"at": ms("2026-09-02"), "spec": {"preRatio": 0.5}, "candidates": [{"start": 100.0, "end": 145.0, "score": 3.0}]}]}, f)
        env.data({V1: video(V1, [mark("a", 100.0, 145.0, 5.0)]), V3: {"id": V3, "kind": "youtube", "title": "w", "analysis": None, "marks": []}})
        env.runs([run_row(V3, [[102.5, 152.5]])])
        self.assertEqual(self.cl(env)["peakRatio"]["friend"]["median"], 0.4)
        env.runs([run_row(V3, [[200, 250]])])                # 区間の中に山が無い
        self.assertEqual(self.cl(env)["peakRatio"]["friend"]["n"], 0)

    def test_current_settings_read_only(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 100.0, 145.0, 5.0)])})
        env.runs([run_row(V1, [[110, 160]])])
        self.assertIsNone(self.cl(env)["suggest"]["current"])     # 設定のファイルが無い
        path = os.path.join(env.studio, "settings-ui.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"analyze": {"length": 45, "preRatio": 0.65, "count": 8}}, f)
        def snap():
            with open(path, "rb") as f:
                return os.path.getmtime(path), f.read()
        before = snap()
        sg = self.cl(env)["suggest"]
        self.assertEqual(sg["current"], {"length": 45.0, "preRatio": 0.65})
        self.assertIn("いまの設定: 45 秒・0.65", sg["note"])
        self.assertEqual(before, snap())    # 書き換えない
        for bad in ("{broken", json.dumps({"analyze": {"length": 45}}), json.dumps({"review": {}}), json.dumps({"analyze": {"length": "x", "preRatio": 0.5}})):
            with open(path, "w", encoding="utf-8") as f:
                f.write(bad)
            sg = self.cl(env)["suggest"]
            self.assertIsNone(sg["current"])
            self.assertIn("読めない", sg["note"])

    def test_by_type_and_print(self):
        env = Env(self)
        d1, r1 = ranges_over(V1, 10, typ="歌枠")
        d2, r2 = ranges_over(V2, 3, ratio_pad=(10, 80), typ="雑談")
        env.data({V1: d1, V2: d2})
        env.runs([run_row(V1, r1), run_row(V2, r2)])
        cl = self.cl(env)
        self.assertEqual(set(cl["byType"]), {"歌枠", "雑談"})
        self.assertEqual(cl["byType"]["歌枠"]["suggest"]["length"], 60)
        self.assertEqual(cl["byType"]["雑談"]["suggest"]["length"], 80)
        self.assertEqual(cl["byType"]["雑談"]["samples"]["friend"], 3)
        self.assertFalse(cl["byType"]["雑談"]["suggest"]["enough"])
        self.assertIsNone(cl["byType"]["雑談"]["suggest"]["preRatio"])    # 見本 3 個
        self.assertEqual(cl["suggest"]["samples"], 13)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            M.main(["--data-dir", env.root])
        out = buf.getvalue()
        self.assertIn("人が選んだ区間の長さ", out)
        self.assertIn("目安:", out)
        self.assertIn("[雑談]", out)
        # 見本が無いとき
        e2 = Env(self)
        e2.data({V1: video(V1, [mark("a", 100.0, 145.0, 5.0)])})
        c2 = self.cl(e2)
        self.assertIsNone(c2["suggest"]["length"])
        self.assertIsNone(c2["suggest"]["preRatio"])
        self.assertEqual(c2["suggest"]["samples"], 0)
        self.assertFalse(c2["suggest"]["enough"])
        self.assertEqual(c2["byType"], {})

    def test_since_until_and_json(self):
        env = Env(self)
        env.data({V1: video(V1, [mark("a", 100.0, 145.0, 5.0)])})
        env.runs([run_row(V1, [[110, 160]], day="2026-09-05"), run_row(V1, [[300, 330]], day="2026-10-05")])
        self.assertEqual(self.cl(env)["samples"]["friend"]["n"], 2)
        self.assertEqual(self.cl(env, since="2026-10-01")["samples"]["friend"]["n"], 1)
        self.assertEqual(self.cl(env, until="2026-09-30")["suggest"]["length"], 50)
        with contextlib.redirect_stdout(io.StringIO()):
            M.main(["--data-dir", env.root, "--json"])
        d = os.path.join(env.studio, "evals", "marks")
        with open(os.path.join(d, os.listdir(d)[0]), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["clipLength"]["suggest"]["samples"], 2)
        self.assertEqual(sorted(saved["clipLength"]["suggest"]), sorted(["length", "preRatio", "samples", "videos", "enough", "p25", "p75", "kept", "preSamples", "current", "note"]))


if __name__ == "__main__":
    unittest.main()
