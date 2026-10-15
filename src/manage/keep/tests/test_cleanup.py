"""src/manage/keep/cleanup.py(作業データの片付け。段9 9-2)の単体テスト。

    python -m unittest src/manage/keep/tests/test_cleanup.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> keep -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from manage.keep import cleanup as C  # noqa: E402


def touch(path, size=10, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-cleanup-")
        self.app = os.path.join(self.tmp, "app")
        self.now = [time.time()]
        self.env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}   # 作業データの置き場所を一時フォルダに(cache・log の候補)
        os.makedirs(os.path.join(self.tmp, "data", "transcribe", "cache", "peaks"))
        self.cl = C.Cleanup(self.app, env=self.env, clock=lambda: self.now[0], keep_days=14)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_candidates_need_pack_and_done_status(self):
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "a.mp4"), 100)
        b = touch(os.path.join(v, "b.mp4"), 100)
        c = touch(os.path.join(v, "c.mp4"), 100)
        cases = [{"id": "1", "title": "終わった配信", "status": "posted", "clips": [{"path": a, "exists": True, "pack": {"dir": a + "_pack"}}, {"path": b, "exists": True, "pack": None}]},
                 {"id": "2", "title": "作業中", "status": "", "clips": [{"path": c, "exists": True, "pack": {"dir": c + "_pack"}}]}]
        r = self.cl.candidates(cases)
        exp = next(k for k in r["kinds"] if k["kind"] == "export")
        self.assertEqual([i["path"] for i in exp["items"]], [a])              # パックがあり、案件が投稿済み/見送りのものだけ
        self.assertIn("終わった配信", exp["items"][0]["note"])
        self.assertEqual(exp["bytes"], 100)
        self.assertEqual(r["bytes"], 100)
        self.assertEqual((r["keepDays"], r["trashDays"], r["packAgeDays"]), (14, 3, 3))   # 受付済みの候補(このテストは 14 を渡す)・ごみ箱 TRASH_DAYS・パックから PACK_AGE_DAYS

    def test_work_orphans(self):
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "a.mp4"))
        touch(os.path.join(v, "作業用", "a.transcript.json"))        # 元の動画がある → 候補にしない
        orphan = touch(os.path.join(v, "作業用", "gone.clip.json"))   # 元の動画が無い → 候補
        touch(os.path.join(v, "作業用", "memo.txt"))                  # 知らない形 → 候補にしない
        # 作業用に置く文字起こしの文書とその付き物(RS8 B2。名前が文書の id)と持ち主の印は、動画の付き物ではない → 候補にしない
        for n in ("0123456789ab.json", "0123456789ab.edit.json", "0123456789ab.words.json", "0123456789ab.transcript.json",
                  "0123456789ab.srt", ".studio-id", "case.json"):
            touch(os.path.join(v, "作業用", n))
        touch(os.path.join(v, "作業用", ".hist", "0123456789ab", "1.json"))
        touch(os.path.join(v, "作業用", ".bak", "0123456789ab.pre-fill.json"))
        r = self.cl.candidates([{"id": "1", "status": "", "clips": [{"path": a, "exists": True}]}])
        work = next(k for k in r["kinds"] if k["kind"] == "work")
        self.assertEqual([i["path"] for i in work["items"]], [orphan])
        self.assertIn("gone", work["items"][0]["note"])

    def test_media_stem_ignores_transcript_docs(self):
        self.assertEqual(C._media_stem("動画.edit.json"), "動画")
        self.assertEqual(C._media_stem("abcdef012345x.edit.json"), "abcdef012345x")   # 13 文字は文書の id ではない
        for n in ("0123456789ab.edit.json", "0123456789ab.clip.json", "0123456789ab.transcript.json", ".studio-id", "0123456789ab.json"):
            self.assertIsNone(C._media_stem(n), n)

    def test_cache_logs_and_intake(self):
        peaks = os.path.join(self.tmp, "data", "transcribe", "cache", "peaks")
        p1 = touch(os.path.join(peaks, "x.peaks"), 50)
        old = touch(os.path.join(self.app, "logs", "portal.old.log"), 20)
        touch(os.path.join(self.app, "logs", "portal.log"), 20)      # 今のログは候補にしない
        runs1 = touch(os.path.join(self.app, "logs", "autorun-runs.jsonl.1"), 20)
        intake = os.path.join(self.tmp, "intake")
        old_day = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 20 * 86400))
        new_day = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 2 * 86400))
        touch(os.path.join(intake, "受付済み", old_day, "v.mp4"), 30)
        touch(os.path.join(intake, "受付済み", new_day, "v.mp4"), 30)
        r = self.cl.candidates([], intake_dir=intake)
        by = {k["kind"]: k for k in r["kinds"]}
        self.assertEqual([i["path"] for i in by["cache"]["items"]], [p1])
        self.assertEqual(sorted(i["path"] for i in by["log"]["items"]), sorted([old, runs1]))
        self.assertEqual([i["name"] for i in by["intake"]["items"]], [old_day])
        self.assertTrue(by["intake"]["items"][0]["dir"])

    def write_case(self, folder, rid):
        from flow import placement
        p = placement.case_path(folder)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        d = {"schema": placement.CASE_SCHEMA, "id": "c-" + os.path.basename(folder)[-6:]}
        if rid:
            d["requestId"] = rid
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def write_deliveries(self, rows):
        os.makedirs(os.path.join(self.app, "logs"), exist_ok=True)
        with open(os.path.join(self.app, "logs", C.DELIVERIES_LOG), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_request_folders_from_last_delivery_or_receipt(self):
        """書き出し先の 依頼/<日付>_<題>_<id6>/ は、最後に届けてから keep_days 日(手で置いた動画 = case.json に requestId が無い は受け付けてから)。
        届けていない・case.json の無いフォルダは出さない。移すのは動画とパックだけ(作業用の文書は残す。Q4)"""
        out = os.path.join(self.tmp, "出力")
        cl = C.Cleanup(self.app, env=self.env, clock=lambda: self.now[0], keep_days=3, out_dirs=[out])
        old = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 20 * 86400))
        req = os.path.join(out, C.REQUEST_DIR)
        d_ok = os.path.join(req, "%s_題_aaaaaa" % old)
        touch(os.path.join(d_ok, "v.mp4"), 30)
        touch(os.path.join(d_ok, "v_pack", "v.mp4"), 7)
        self.write_case(d_ok, "20261001-120000-aaaaaa")
        touch(os.path.join(d_ok, "作業用", "0123456789ab.json"), 5)
        d_recent = os.path.join(req, "%s_題_cccccc" % old)                # 届けたばかり
        touch(os.path.join(d_recent, "v.mp4"), 30)
        self.write_case(d_recent, "20261001-120000-cccccc")
        d_not = os.path.join(req, "%s_題_bbbbbb" % old)                   # 届けていない
        touch(os.path.join(d_not, "v.mp4"), 30)
        self.write_case(d_not, "20261001-120000-bbbbbb")
        d_manual = os.path.join(req, "%s_題_123abc" % old)                # 手で置いた動画(依頼 id なし)
        touch(os.path.join(d_manual, "m.mp4"), 11)
        self.write_case(d_manual, "")
        touch(os.path.join(req, "%s_題_dddddd" % old, "v.mp4"), 30)       # case.json なし
        self.write_deliveries([{"requestId": "20261001-120000-aaaaaa", "zip": "z.zip", "at": int((self.now[0] - 10 * 86400) * 1000)},
                               {"requestId": "20261001-120000-cccccc", "zip": "y.zip", "at": int((self.now[0] - 1 * 86400) * 1000)}])
        items = next(k for k in cl.candidates([])["kinds"] if k["kind"] == "intake")["items"]
        by = {i["path"]: i for i in items}
        self.assertEqual(sorted(by), sorted([d_ok, d_manual]))
        self.assertIn("届けてから 10 日", by[d_ok]["note"])
        self.assertIn("手で置いた動画", by[d_manual]["note"])
        self.assertEqual(by[d_ok]["bytes"], 37)                           # 動画 + パック(文書は数えない)
        r = cl.move([by[d_ok]["id"]])
        self.assertEqual((len(r["moved"]), r["failed"]), (1, []))
        self.assertFalse(os.path.exists(os.path.join(d_ok, "v.mp4")) or os.path.exists(os.path.join(d_ok, "v_pack")))
        self.assertTrue(os.path.isfile(os.path.join(d_ok, "作業用", "0123456789ab.json")))   # 文書は残る
        day = time.strftime("%Y-%m-%d", time.localtime(self.now[0]))
        self.assertTrue(os.path.isfile(os.path.join(self.app, "ごみ箱", day, "intake", os.path.basename(d_ok), "v.mp4")))
        items = next(k for k in cl.candidates([])["kinds"] if k["kind"] == "intake")["items"]
        self.assertEqual([i["path"] for i in items], [d_manual])         # 片付けたフォルダはもう出ない
        os.remove(os.path.join(self.app, "logs", C.DELIVERIES_LOG))       # 記録が読めなければ届けた依頼は出さない(手で置いた物は出す)
        self.assertEqual([i["path"] for i in next(k for k in cl.candidates([])["kinds"] if k["kind"] == "intake")["items"]], [d_manual])

    def test_app_intake_copies(self):
        """作業データの app/intake/<日付>/<依頼 id>/(受付の写し)も同じ決まりで候補に(7b-1)。m で始まる id = 手で置いた動画・<日付>/ 直下の動画は受け付けた日から"""
        cl = C.Cleanup(self.app, env=self.env, clock=lambda: self.now[0], keep_days=3)
        old = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 20 * 86400))
        new = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 1 * 86400))
        base = os.path.join(self.app, C.APP_INTAKE)
        sent = touch(os.path.join(base, old, "20261001-120000-aaaaaa", "a.mp4"), 10)
        touch(os.path.join(base, old, "20261001-120000-bbbbbb", "b.mp4"), 10)   # 届けていない
        man = touch(os.path.join(base, old, "m1a2b3c4d", "c.mp4"), 10)
        loose = touch(os.path.join(base, old, "x.mp4"), 10)
        touch(os.path.join(base, new, "m9999aaaa", "d.mp4"), 10)                # まだ新しい
        self.write_deliveries([{"requestId": "20261001-120000-aaaaaa", "at": int((self.now[0] - 5 * 86400) * 1000)}])
        items = next(k for k in cl.candidates([])["kinds"] if k["kind"] == "intake")["items"]
        got = sorted(p for i in items for p in i["parts"])
        self.assertEqual(got, sorted([sent, man, loose]))

    def test_media_stem_edit_clip_json(self):
        """X_edit.clip.json は X の付き物(元の X.mp4 があれば work の候補にしない。7d-1)"""
        self.assertEqual(C._media_stem("clip_0001_edit.clip.json"), "clip_0001")
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "clip_0001.mp4"))
        touch(os.path.join(v, "作業用", "clip_0001_edit.clip.json"))
        gone = touch(os.path.join(v, "作業用", "gone_edit.clip.json"))
        work = next(k for k in self.cl.candidates([{"id": "1", "status": "", "clips": [{"path": a, "exists": True}]}])["kinds"] if k["kind"] == "work")
        self.assertEqual([i["path"] for i in work["items"]], [gone])

    def test_deliveries_log_name_matches_friend_feedback(self):
        from human.friend import friend_feedback
        self.assertEqual(C.DELIVERIES_LOG, friend_feedback.DELIVERIES_LOG)

    def test_request_dir_name_matches_placement(self):
        from flow import placement
        self.assertEqual(C.REQUEST_DIR, placement.REQUEST_DIR)

    def test_move_only_known_and_purge(self):
        peaks = os.path.join(self.tmp, "data", "transcribe", "cache", "peaks")
        p1 = touch(os.path.join(peaks, "x.peaks"), 50)
        p2 = touch(os.path.join(peaks, "y.peaks"), 50)
        r = self.cl.candidates([])
        ids = [i["id"] for i in next(k for k in r["kinds"] if k["kind"] == "cache")["items"]]
        res = self.cl.move([ids[0], "nope", 3])
        self.assertEqual([m["path"] for m in res["moved"]], [p1])
        self.assertEqual(res["unknown"], ["nope", "3"])
        self.assertFalse(os.path.exists(p1))
        self.assertTrue(os.path.exists(p2))
        day = time.strftime("%Y-%m-%d", time.localtime(self.now[0]))
        dest = os.path.join(self.app, "ごみ箱", day, "cache", "x.peaks")
        self.assertTrue(os.path.isfile(dest))
        with open(os.path.join(self.app, "ごみ箱", day, "manifest.jsonl"), encoding="utf-8") as f:
            self.assertIn(p1.replace("\\", "\\\\"), f.read())
        self.assertEqual(self.cl.move([ids[0]])["unknown"], [ids[0]])   # 移した物はもう候補ではない
        # 同じ名前が来たら (1) を付ける
        touch(os.path.join(peaks, "x.peaks"), 5)
        r = self.cl.candidates([])
        ids = {i["name"]: i["id"] for i in next(k for k in r["kinds"] if k["kind"] == "cache")["items"]}
        self.cl.move([ids["x.peaks"]])
        self.assertTrue(os.path.isfile(os.path.join(self.app, "ごみ箱", day, "cache", "x (1).peaks")))
        # purge: TRASH_DAYS(3 日)を過ぎた日付のフォルダだけ消す(keep_days とは別)
        self.assertEqual(self.cl.purge(), 0)
        self.now[0] += 2 * 86400
        self.assertEqual(self.cl.purge(), 0)
        self.now[0] += 2 * 86400
        self.assertEqual(self.cl.purge(), 1)
        self.assertFalse(os.path.isdir(os.path.join(self.app, "ごみ箱", day)))

    def make_pack(self, media, textplus=True, files=("a.mp4", "create_resolve_textplus_project.lua", "README.txt"), built=None):
        """<名前>_pack と、cut2resolve のパックを作った記録(作業データの packs/)"""
        from manage.cases import txindex
        d = txindex.pack_dir(media)
        for f in files:
            touch(os.path.join(d, f), 5)
        rec = {"schema": txindex.PACK_RECORD_SCHEMA, "dir": d, "textplus": textplus, "files": list(files),
               "builtAt": built or int((self.now[0] - 20 * 86400) * 1000)}
        p = os.path.join(txindex.packs_dir(self.env), txindex.pack_key(d))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        return d

    def test_export_aged_textplus_pack_with_sidecars(self):
        """パック(Text+)から 3 日(PACK_AGE_DAYS)たった元動画は、案件の状態が無くても候補。_edit.mp4・作業用の途中のファイルも一緒に移す"""
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "a.mp4"), 100)
        ed = touch(os.path.join(v, "作業用", "a_edit.mp4"), 40)
        cj = touch(os.path.join(v, "作業用", "a.clip.json"), 5)
        b = touch(os.path.join(v, "b.mp4"), 100)   # Text+ でないパック(動画のコピーなし) → 日数では出さない
        c = touch(os.path.join(v, "c.mp4"), 100)   # 新しいパック → まだ
        pa = self.make_pack(a)
        old = int((self.now[0] - 20 * 86400) * 1000)
        cases = [{"id": "1", "title": "作業中", "status": "", "clips": [
            {"path": a, "exists": True, "pack": {"dir": pa, "textplus": True, "updatedAt": old}},
            {"path": b, "exists": True, "pack": {"dir": b + "_pack", "textplus": False, "updatedAt": old}},
            {"path": c, "exists": True, "pack": {"dir": c + "_pack", "textplus": True, "updatedAt": int(self.now[0] * 1000)}}]}]
        r = self.cl.candidates(cases)
        exp = next(k for k in r["kinds"] if k["kind"] == "export")
        self.assertEqual([i["path"] for i in exp["items"]], [a])
        self.assertIn("パックから 20 日", exp["items"][0]["note"])
        self.assertEqual(exp["items"][0]["bytes"], 145)
        self.cl.move([exp["items"][0]["id"]])
        day = time.strftime("%Y-%m-%d", time.localtime(self.now[0]))
        base = os.path.join(self.app, "ごみ箱", day, "export", "a")
        self.assertTrue(os.path.isfile(os.path.join(base, "a.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(base, "作業用", "a_edit.mp4")) and os.path.isfile(os.path.join(base, "作業用", "a.clip.json")))
        self.assertFalse(any(os.path.exists(x) for x in (a, ed, cj)))

    def test_export_needs_a_complete_pack(self):
        """パックの動画・Lua が欠けている・空なら、日数がたっても元の動画を候補にしない。候補を出したあとで欠けたら移さない(部品 M1)"""
        v = os.path.join(self.tmp, "vid")
        old = int((self.now[0] - 20 * 86400) * 1000)

        def clip(name, **kw):
            m = touch(os.path.join(v, name + ".mp4"), 100)
            return m, {"path": m, "exists": True, "pack": {"dir": self.make_pack(m, files=(name + ".mp4", "x.lua", "README.txt"), **kw),
                                                           "textplus": True, "updatedAt": old}}
        a, ca = clip("a")
        b, cb = clip("b")
        os.remove(os.path.join(cb["pack"]["dir"], "b.mp4"))              # 外でパックの動画だけ消えた
        c, cc = clip("c")
        with open(os.path.join(cc["pack"]["dir"], "x.lua"), "wb"):
            pass                                                          # 空
        r = self.cl.candidates([{"id": "1", "title": "t", "status": "", "clips": [ca, cb, cc]}])
        exp = next(k for k in r["kinds"] if k["kind"] == "export")
        self.assertEqual([i["path"] for i in exp["items"]], [a])
        os.remove(os.path.join(ca["pack"]["dir"], "a.mp4"))              # 候補を出したあとで欠けた
        res = self.cl.move([exp["items"][0]["id"]])
        self.assertEqual((res["moved"], len(res["failed"])), ([], 1))
        self.assertIn("欠けている", res["failed"][0]["error"])
        self.assertTrue(os.path.exists(a))

    def test_export_delivered_auto_clip_without_pack(self):
        """自動の切り抜きで届けたあとパックだけが片付いた物(友人の「要らない」)は、届けてから 3 日で候補(opt-manage 2a-1)。
        人の切り抜き・届けていない・届けたばかりの物は出さない"""
        v = os.path.join(self.tmp, "vid")
        a = touch(os.path.join(v, "a.mp4"), 100)
        b = touch(os.path.join(v, "b.mp4"), 100)
        c = touch(os.path.join(v, "c.mp4"), 100)
        d = touch(os.path.join(v, "d.mp4"), 100)
        old, new = int((self.now[0] - 5 * 86400) * 1000), int(self.now[0] * 1000)
        cases = [{"id": "1", "title": "配信", "status": "", "clips": [
            {"path": a, "exists": True, "pack": None, "auto": {"origin": "auto"}, "review": {"deliveredAt": old}},
            {"path": b, "exists": True, "pack": None, "auto": {"origin": "auto"}, "review": {"deliveredAt": new}},
            {"path": c, "exists": True, "pack": None, "auto": {"origin": "auto"}, "review": {"deliveredAt": 0}},
            {"path": d, "exists": True, "pack": None, "auto": None, "review": {"deliveredAt": old}}]}]
        exp = next(k for k in self.cl.candidates(cases)["kinds"] if k["kind"] == "export")
        self.assertEqual([i["path"] for i in exp["items"]], [a])
        self.assertIn("届けてから 5 日", exp["items"][0]["note"])
        self.assertTrue(os.path.exists(b) and os.path.exists(c))

    def test_trash_on_the_same_drive(self):
        """作業データと別のドライブの物は、そのドライブの書き出し先\\ごみ箱(無ければ <ドライブ>\\youtube-tools ごみ箱)。purge もそこを見る"""
        out = os.path.join(self.tmp, "E", "切り抜き")
        cl = C.Cleanup(self.app, env=self.env, clock=lambda: self.now[0], out_dirs=lambda: [out])
        saved = C._drive
        C._drive = lambda p: "e:" if os.path.normcase(os.path.abspath(p)).startswith(os.path.normcase(os.path.join(self.tmp, "E"))) else "c:"
        try:
            self.assertEqual(cl.trash_for(os.path.join(out, "x", "a.mp4")), os.path.join(out, "ごみ箱"))
            self.assertEqual(cl.trash_for(os.path.join(self.app, "logs", "x.old.log")), os.path.join(self.app, "ごみ箱"))
            day = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 20 * 86400))
            touch(os.path.join(out, "ごみ箱", day, "export", "a.mp4"))
            self.assertEqual(cl.purge(), 1)
            self.assertFalse(os.path.isdir(os.path.join(out, "ごみ箱", day)))
        finally:
            C._drive = saved

    def test_remember_root_keeps_old_list_when_write_fails(self):
        """trash-roots.json は原子的に書く: 書く途中で失敗しても前の一覧が残る(前は open "w" で先に空にしていた。資料 4 節の疑い 3)"""
        far = os.path.join(self.tmp, "E", "ごみ箱")
        self.cl.remember_root(far)
        self.cl.remember_root(far)   # 同じものは足さない
        p = os.path.join(self.app, C.ROOTS_FILE)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), ('["%s"]' % far.replace("\\", "\\\\")).encode("utf-8"))   # 中身の形は今までと同じ(1 行・改行なし)
        with self.assertRaises(UnicodeError):
            self.cl.remember_root(os.path.join(self.tmp, "bad\ud800"))   # UTF-8 にできない名前 = 書く途中の失敗
        self.assertIn(os.path.normcase(os.path.abspath(far)), self.cl.trash_roots())
        self.assertEqual([n for n in os.listdir(self.app) if n != C.ROOTS_FILE], [])   # 一時ファイルを残さない
        with open(p, "w", encoding="utf-8") as f:
            f.write("{壊れた")
        self.assertEqual(self.cl.trash_roots(), [os.path.normcase(os.path.abspath(self.cl.trash_dir))])   # 読めなければ足さない(上げない)

    def test_old_day_dirs_skip_files_and_other_names(self):
        old = time.strftime("%Y-%m-%d", time.localtime(self.now[0] - 20 * 86400))
        root = os.path.join(self.tmp, "days")
        os.makedirs(os.path.join(root, old + " 2"))
        os.makedirs(os.path.join(root, "メモ"))
        touch(os.path.join(root, old + ".txt"))
        self.assertEqual(C._old_day_dirs(root, 3, self.now[0]), [(old + " 2", os.path.join(root, old + " 2"))])
        self.assertEqual(C._old_day_dirs(root, 30, self.now[0]), [])
        self.assertEqual(C._old_day_dirs(os.path.join(self.tmp, "無い"), 3, self.now[0]), [])

    def test_paths_not_offered_cannot_be_moved(self):
        secret = touch(os.path.join(self.tmp, "secret.txt"))
        res = self.cl.move([C._id(secret)])
        self.assertEqual(res["moved"], [])
        self.assertTrue(os.path.exists(secret))


if __name__ == "__main__":
    unittest.main()
