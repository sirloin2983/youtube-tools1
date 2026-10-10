"""dev/eval_cut.py(カットのたたき台と人の最終の差を測る道具)のテスト。リポジトリ直下で:

    py -3.10 -m unittest dev/tests/test_eval_cut.py

作業データは一時フォルダに作る(本物の作業データは読まない・書かない)。サーバーは動かさない。
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
REPO = os.path.join(os.path.dirname(HERE), "src")   # ツールと ytt_core の置き場所
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import eval_cut as E  # noqa: E402

FPS30 = [30, 1]


def ms(day, hhmm="12:00:00"):
    return int(time.mktime(time.strptime("%sT%s" % (day, hhmm), "%Y-%m-%dT%H:%M:%S")) * 1000)


def fr(*pairs, fps=30):
    """コマ番号の組 -> 秒の区間"""
    return [(a / fps, b / fps) for a, b in pairs]


class Env:
    """一時の作業データ(<root>/transcribe/transcripts/ と <root>/cut2resolve/packs/)に、edit.json・文書・パックの記録を作る"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.tdir = os.path.join(self.root, "transcribe", "transcripts")
        os.makedirs(self.tdir)
        self.env = {"YTT_DATA_DIR": self.root}
        self.pdir = E.txindex.packs_dir(self.env)
        os.makedirs(self.pdir)

    def close(self):
        self._tmp.cleanup()

    def edit(self, tid, clips, draft=None, fps=FPS30, origin="manual", updated=None, source=None, relink_from=None, title="t", doc=True):
        """clips / draft の keepsSec は秒の組。draft = {"origin", "settings", "keeps", "at"}"""
        d = {"schema": E.EDIT_SCHEMA, "rev": 1, "updatedAt": updated or ms("2026-10-05"), "packRev": 0, "origin": origin,
             "sources": [{"fps": fps, "duration": 600.0}], "clips": [{"src": 0, "in": a, "out": b} for a, b in clips]}
        if draft:
            d["draft"] = {"origin": draft["origin"], "settings": draft.get("settings", {}), "keepsSec": [list(k) for k in draft["keeps"]], "at": draft.get("at", ms("2026-10-05"))}
        self._write(tid + ".edit.json", d)
        if doc:
            dd = {"schema": "youtube-tools-transcript/v1", "id": tid, "title": title, "segments": [], "sourcePath": source or ("C:\\clips\\%s.mp4" % tid)}
            if relink_from:
                dd["relinks"] = [{"from": relink_from, "to": dd["sourcePath"], "why": "normalize30"}]
            self._write(tid + ".json", dd)

    def pack(self, video, segments=None, keep_frames=None, frame_rate="30/1", built=None):
        d = E.txindex.pack_dir(video)
        cp = {"schema": "youtube-tools-cut-plan/v1"}
        if segments is not None:
            cp["segments"] = [{"id": "keep-%03d" % i, "start": a, "end": b, "status": "adopted"} for i, (a, b) in enumerate(segments, 1)]
        if keep_frames is not None:
            cp["keep_frames"] = keep_frames
            cp["frame_rate"] = frame_rate
        rec = {"schema": E.txindex.PACK_RECORD_SCHEMA, "dir": d, "video": video, "builtAt": built or ms("2026-10-06"), "files": [], "cutPlan": cp}
        with open(os.path.join(self.pdir, E.txindex.pack_key(d)), "w", encoding="utf-8") as f:
            json.dump(rec, f)

    def _write(self, name, d):
        with open(os.path.join(self.tdir, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def run(self, **kw):
        return E.evaluate(self.root, **kw)


class TestCompare(unittest.TestCase):
    def test_identical_is_untouched(self):
        D = fr((0, 90), (150, 300))
        r = E.compare(D, list(D), 30)
        self.assertEqual((r["same"], r["moved"], r["added"], r["removed"], r["reshaped"]), (2, 0, 0, 0, 0))
        self.assertEqual(r["keptDiff"], 0)
        self.assertEqual([round(x * 30, 6) for x in r["diffs"]], [0, 0, 0, 0])

    def test_edge_moved_in_frames(self):
        r = E.compare(fr((30, 120)), fr((27, 126)), 30)    # 開始 3 コマ早く・終了 6 コマ遅く
        self.assertEqual((r["moved"], r["same"]), (1, 0))
        self.assertEqual([round(x * 30) for x in r["diffs"]], [-3, 6])
        self.assertAlmostEqual(r["keptDiff"], 9 / 30, places=3)

    def test_rounding_noise_is_same(self):
        D = [(1.0, 2.0)]
        r = E.compare(D, [(1.001, 1.9995)], 30)            # 0.001 秒は 0.03 コマ(許容 0.5 コマ未満)
        self.assertEqual((r["same"], r["moved"]), (1, 0))

    def test_added_and_removed(self):
        r = E.compare(fr((0, 30), (60, 90)), fr((0, 30), (120, 150)), 30)
        self.assertEqual((r["same"], r["removed"], r["added"]), (1, 1, 1))
        self.assertEqual(r["keptDiff"], 0)

    def test_split_and_merge_are_reshaped(self):
        r = E.compare(fr((0, 300)), fr((0, 100), (200, 300)), 30)      # 中を削った(分けた)
        self.assertEqual((r["reshaped"], r["same"]), (1, 0))
        self.assertEqual([round(x * 30) for x in r["diffs"]], [0, 0])   # 外側の端は同じ
        self.assertAlmostEqual(r["keptDiff"], -100 / 30, places=3)
        r = E.compare(fr((0, 100), (150, 300)), fr((0, 300)), 30)      # つないだ
        self.assertEqual(r["reshaped"], 1)

    def test_touching_draft_intervals_are_one(self):
        r = E.compare([(0.0, 5.0), (5.0, 10.0)], [(0.0, 10.0)], 30)
        self.assertEqual((r["same"], r["reshaped"]), (1, 0))

    def test_touching_final_does_not_overlap_next(self):
        r = E.compare(fr((0, 30)), fr((30, 60)), 30)                   # 端が接するだけは重ならない = 消して足した
        self.assertEqual((r["removed"], r["added"], r["same"]), (1, 1, 0))

    def test_empty(self):
        for D, F in (([], []), (fr((0, 30)), []), ([], fr((0, 30)))):
            r = E.compare(D, F, 30)
            self.assertEqual(r["same"] + r["moved"] + r["reshaped"], 0)
        self.assertEqual(E.compare(fr((0, 30)), [], 30)["removed"], 1)

    def test_own_fps_tolerance(self):
        D = fr((0, 60), fps=60)
        r = E.compare(D, fr((1, 60), fps=60), 60)                      # 60fps の 1 コマ
        self.assertEqual(r["moved"], 1)
        self.assertEqual(round(r["diffs"][0] * 60), 1)


class TestEvaluate(unittest.TestCase):
    def setUp(self):
        self.env = Env()

    def tearDown(self):
        self.env.close()

    def test_empty_data_does_not_fail(self):
        res = self.env.run()
        self.assertEqual(res["meta"]["docs"], 0)
        self.assertTrue(res["meta"]["few"])
        self.assertEqual(res["byOrigin"], {})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(res)
        self.assertIn("測れる文書がありません", buf.getvalue())

    def test_missing_dirs_do_not_fail(self):
        with tempfile.TemporaryDirectory() as t:
            res = E.evaluate(t)
            self.assertEqual(res["meta"]["docs"], 0)

    def test_final_from_edit_clips_and_counts(self):
        # 行から: 開始を 3 コマ早く・終了は同じ → 端のずれ -3 と 0、区間 1 つを足した
        draft = {"origin": "rows", "settings": {"on": True, "after": 0.5, "before": 0.3, "padAfter": 0.2}, "keeps": fr((30, 120))}
        self.env.edit("aaaaaaaaaaaa", fr((27, 120), (200, 230)), draft)
        res = self.env.run()
        t = res["total"]
        self.assertEqual((t["docs"], t["fromPack"], t["untouched"]), (1, 0, 0))
        self.assertEqual(t["intervals"], {"added": 1, "removed": 0, "moved": 1, "reshaped": 0, "same": 0})
        self.assertEqual(t["fixes"], 2)
        self.assertEqual(t["edges30"]["n"], 2)
        self.assertEqual(t["edges30"]["signed"]["min"], -3)
        self.assertEqual(t["edges30"]["sameRate"], 0.5)
        self.assertAlmostEqual(t["keptDiffSec"]["median"], (3 + 30) / 30, places=3)
        self.assertEqual(res["byOrigin"]["rows"]["docs"], 1)
        self.assertEqual(res["byDoc"][0]["finalFrom"], "edit")
        self.assertTrue(res["meta"]["few"])      # パックが 20 本未満

    def test_pack_cutplan_is_the_final(self):
        video = "C:\\clips\\bbbbbbbbbbbb.mp4"
        draft = {"origin": "silence", "settings": {"noise": -35, "min": 0.6, "pad": 0.15}, "keeps": fr((0, 90), (150, 300))}
        self.env.edit("bbbbbbbbbbbb", fr((0, 90), (150, 300)), draft)      # 保存したカットはたたき台のまま
        self.env.pack(video, segments=fr((0, 90), (150, 306)))               # パックの最終は最後の終了を 6 コマ遅くした
        res = self.env.run()
        t = res["total"]
        self.assertEqual((t["docs"], t["fromPack"]), (1, 1))
        self.assertEqual((t["intervals"]["same"], t["intervals"]["moved"]), (1, 1))
        self.assertEqual(t["edges30"]["signed"]["max"], 6)
        self.assertEqual(res["byDoc"][0]["finalFrom"], "pack")

    def test_pack_keep_frames_fallback_and_relink_alias(self):
        old = "C:\\clips\\cccccccccccc.mp4"
        draft = {"origin": "rows", "settings": {}, "keeps": fr((0, 60))}
        self.env.edit("cccccccccccc", fr((0, 60)), draft, source="C:\\clips\\cccccccccccc_30fps.mp4", relink_from=old)
        self.env.pack(old, keep_frames=[[0, 63]])                            # 付け替える前のパスのパック・segments が無い形
        res = self.env.run()
        self.assertEqual(res["total"]["fromPack"], 1)
        self.assertEqual(res["total"]["edges30"]["signed"]["max"], 3)

    def test_untouched_rate_and_by_origin(self):
        for i, origin in enumerate(("rows", "rows", "silence")):
            tid = "%012x" % (i + 1)
            keeps = fr((0, 90), (150, 300))
            final = keeps if i != 1 else fr((0, 90))     # 2つ目の rows は区間を1つ消した
            self.env.edit(tid, final, {"origin": origin, "settings": {"pad": 0.15} if origin == "silence" else {"after": 0.5}, "keeps": keeps})
        res = self.env.run()
        self.assertEqual((res["total"]["docs"], res["total"]["untouched"]), (3, 2))
        self.assertEqual(res["total"]["untouchedRate"], round(2 / 3, 4))
        self.assertEqual((res["byOrigin"]["rows"]["docs"], res["byOrigin"]["rows"]["untouched"]), (2, 1))
        self.assertEqual(res["byOrigin"]["rows"]["intervals"]["removed"], 1)
        self.assertEqual((res["byOrigin"]["silence"]["docs"], res["byOrigin"]["silence"]["untouchedRate"]), (1, 1.0))
        self.assertEqual(res["byOrigin"]["rows"]["keptDiffSec"]["min"], -5.0)

    def test_settings_groups(self):
        for i, pad in enumerate((0.15, 0.15, 0.3)):
            tid = "%012x" % (i + 1)
            keeps = fr((0, 90))
            final = keeps if pad != 0.3 else fr((0, 99))
            self.env.edit(tid, final, {"origin": "silence", "settings": {"noise": -35, "pad": pad}, "keeps": keeps})
        res = self.env.run()
        sg = res["bySettings"]["silence"]
        self.assertEqual(sg["noise=-35 pad=0.15"]["docs"], 2)
        self.assertEqual(sg["noise=-35 pad=0.15"]["untouchedRate"], 1.0)
        self.assertEqual(sg["noise=-35 pad=0.3"]["untouchedRate"], 0.0)
        self.assertEqual(res["bySetting"]["silence"]["pad=0.15"]["docs"], 2)
        self.assertEqual(res["bySetting"]["silence"]["noise=-35"]["docs"], 3)

    def test_edit_without_draft_is_only_counted(self):
        self.env.edit("dddddddddddd", fr((0, 90)))
        self.env.edit("eeeeeeeeeeee", fr((0, 90)), {"origin": "rows", "settings": {}, "keeps": fr((0, 90))})
        res = self.env.run()
        self.assertEqual(res["meta"]["docs"], 1)
        self.assertEqual(res["meta"]["skipped"]["noDraft"], 1)
        self.assertTrue(any("draft" in n for n in res["meta"]["notes"]))

    def test_broken_edit_is_skipped(self):
        with open(os.path.join(self.env.tdir, "ffffffffffff.edit.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        self.env.edit("aaaaaaaaaaaa", fr((0, 90)), {"origin": "all", "settings": {}, "keeps": fr((0, 90))})
        res = self.env.run()
        self.assertEqual((res["meta"]["docs"], res["meta"]["skipped"]["broken"]), (1, 1))

    def test_other_fps_doc_reports_own_fps_frames(self):
        keeps = fr((0, 120), fps=60)
        self.env.edit("aaaaaaaaaaaa", fr((0, 124), fps=60), {"origin": "rows", "settings": {}, "keeps": keeps}, fps=[60, 1])
        self.env.edit("bbbbbbbbbbbb", fr((0, 93)), {"origin": "rows", "settings": {}, "keeps": fr((0, 90))})
        t = self.env.run()["total"]
        self.assertEqual(t["otherFpsDocs"], 1)
        self.assertEqual(t["edgesOwnFps"]["n"], 2)
        self.assertEqual(t["edgesOwnFps"]["signed"]["max"], 4)       # 60fps で 4 コマ(30fps では 2 コマ)
        self.assertEqual(t["edges30"]["signed"]["max"], 3)           # 30fps の文書の 3 コマ(60fps の文書の 2 コマより大きい)
        self.assertEqual(t["edges30"]["n"], 4)

    def test_since_until_by_draft_at(self):
        d = lambda day, t="12:00:00": {"origin": "rows", "settings": {}, "keeps": fr((0, 90)), "at": ms(day, t)}   # noqa: E731
        self.env.edit("aaaaaaaaaaaa", fr((0, 90)), d("2026-10-01"))
        self.env.edit("bbbbbbbbbbbb", fr((0, 90)), d("2026-10-03", "23:59:00"))
        self.env.edit("cccccccccccc", fr((0, 90)), d("2026-10-05"))
        self.assertEqual(self.env.run()["meta"]["docs"], 3)
        self.assertEqual(self.env.run(since="2026-10-02")["meta"]["docs"], 2)
        self.assertEqual(self.env.run(until="2026-10-03")["meta"]["docs"], 2)        # until はその日を含む
        r = self.env.run(since="2026-10-02", until="2026-10-03")
        self.assertEqual(r["meta"]["docs"], 1)
        self.assertEqual(r["meta"]["skipped"]["outOfRange"], 2)

    def test_few_note_threshold(self):
        for i in range(E.FEW_PACKS):
            tid = "%012x" % (i + 1)
            self.env.edit(tid, fr((0, 90)), {"origin": "rows", "settings": {}, "keeps": fr((0, 90))})
            self.env.pack("C:\\clips\\%s.mp4" % tid, segments=fr((0, 90)))
        res = self.env.run()
        self.assertEqual(res["meta"]["fromPack"], E.FEW_PACKS)
        self.assertFalse(res["meta"]["few"])
        self.assertEqual(res["meta"]["fewNote"], "")

    def test_newer_of_pack_and_edit_is_the_final(self):
        video = "C:\\clips\\aaaaaaaaaaaa.mp4"
        draft = {"origin": "rows", "settings": {}, "keeps": fr((0, 90))}
        # パックのあとにカットを直した(edit.json の updatedAt が新しい)→ 保存したカットが最終
        self.env.edit("aaaaaaaaaaaa", fr((0, 96)), draft, updated=ms("2026-10-07"))
        self.env.pack(video, segments=fr((0, 99)), built=ms("2026-10-06"))
        r = self.env.run()
        self.assertEqual((r["byDoc"][0]["finalFrom"], r["total"]["fromPack"], r["total"]["fromEdit"]), ("edit", 0, 1))
        self.assertEqual(r["total"]["edges30"]["signed"]["max"], 6)
        # カットのあとにパックを作った → パックが最終
        self.env.edit("bbbbbbbbbbbb", fr((0, 96)), draft, updated=ms("2026-10-05"))
        self.env.pack("C:\\clips\\bbbbbbbbbbbb.mp4", segments=fr((0, 99)), built=ms("2026-10-06"))
        r = self.env.run()
        by = {d["id"]: d["finalFrom"] for d in r["byDoc"]}
        self.assertEqual(by, {"aaaaaaaaaaaa": "edit", "bbbbbbbbbbbb": "pack"})
        self.assertEqual((r["total"]["fromPack"], r["total"]["fromEdit"]), (1, 1))
        self.assertEqual(r["byOrigin"]["rows"]["fromEdit"], 1)
        self.assertEqual(r["meta"]["fromEdit"], 1)

    def test_edit_without_updated_at_uses_file_mtime(self):
        video = "C:\\clips\\aaaaaaaaaaaa.mp4"
        self.env.edit("aaaaaaaaaaaa", fr((0, 96)), {"origin": "rows", "settings": {}, "keeps": fr((0, 90))})
        path = os.path.join(self.env.tdir, "aaaaaaaaaaaa.edit.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        del d["updatedAt"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f)
        self.env.pack(video, segments=fr((0, 99)), built=ms("2026-10-06"))
        os.utime(path, (ms("2026-10-07") / 1000, ms("2026-10-07") / 1000))     # ファイルの更新時刻がパックより新しい
        self.assertEqual(self.env.run()["byDoc"][0]["finalFrom"], "edit")
        os.utime(path, (ms("2026-10-05") / 1000, ms("2026-10-05") / 1000))     # 古い
        self.assertEqual(self.env.run()["byDoc"][0]["finalFrom"], "pack")

    def test_report_and_json_output(self):
        self.env.edit("aaaaaaaaaaaa", fr((27, 120), (200, 230)), {"origin": "rows", "settings": {"after": 0.5}, "keeps": fr((30, 120))}, title="見本")
        res = self.env.run()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            E.print_report(res)
        out = buf.getvalue()
        self.assertIn("まだ少ない(参考)", out)
        self.assertIn("行から", out)
        self.assertIn("端のずれ", out)
        path = E.C.save(res, res["meta"]["dataDir"], "cut")
        self.assertEqual(os.path.dirname(path), os.path.join(self.env.root, "transcribe", "evals", "cut"))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["meta"]["schema"], E.SCHEMA)

    def test_main_is_read_only_without_json(self):
        self.env.edit("aaaaaaaaaaaa", fr((0, 90)), {"origin": "rows", "settings": {}, "keeps": fr((0, 90))})
        before = sorted(os.listdir(os.path.join(self.env.root, "transcribe")))
        with contextlib.redirect_stdout(io.StringIO()):
            E.main(["--data-dir", self.env.root])
        self.assertEqual(sorted(os.listdir(os.path.join(self.env.root, "transcribe"))), before)
        self.assertFalse(os.path.exists(os.path.join(self.env.root, "transcribe", "evals")))


if __name__ == "__main__":
    unittest.main()
