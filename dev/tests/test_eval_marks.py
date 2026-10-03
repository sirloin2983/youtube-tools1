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


if __name__ == "__main__":
    unittest.main()
