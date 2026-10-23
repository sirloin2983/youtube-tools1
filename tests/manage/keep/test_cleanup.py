"""src/manage/keep/cleanup.py(作業データの片付け。段9 9-2。10-24 から自動だけ)の単体テスト。

    python -m unittest tests/manage/keep/test_cleanup.py
"""
import json
import os
import sys
import time
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> keep -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from manage.keep import cleanup as C  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
from testkit import tempdir, write_json, write_text  # noqa: E402


def touch(path, size=10, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempdir(self, "ytt-cleanup-")
        self.app = os.path.join(self.tmp, "app")
        self.now = [time.time()]
        self.env = {"YTT_DATA_DIR": os.path.join(self.tmp, "data")}   # 作業データの置き場所を一時フォルダに(cache・log の候補)
        os.makedirs(os.path.join(self.tmp, "data", "transcribe", "cache", "peaks"))
        self.cl = self.cleanup(keep_days=14)

    def cleanup(self, **kw):
        return C.Cleanup(self.app, env=self.env, clock=lambda: self.now[0], **kw)

    def ymd(self, days_ago=0):
        return time.strftime("%Y-%m-%d", time.localtime(self.now[0] - days_ago * 86400))

    def kind(self, name, cl=None, intake_dir=None, keep=()):
        """自動で移す物(auto_items)のうち種類 name の物"""
        return [i for i in (cl or self.cl).auto_items(keep, intake_dir) if i["kind"] == name]

    def test_intake_done_days(self):
        """依頼の受付の 受付済み\\<日付>\\ は、受け取った日から keep_days 日より古い日付だけ自動で移す"""
        intake = os.path.join(self.tmp, "intake")
        old_day, new_day = self.ymd(20), self.ymd(2)
        touch(os.path.join(intake, "受付済み", old_day, "v.mp4"), 30)
        touch(os.path.join(intake, "受付済み", new_day, "v.mp4"), 30)
        items = self.kind("intake", intake_dir=intake)
        self.assertEqual([i["name"] for i in items], [old_day])
        self.assertTrue(items[0]["dir"])

    def test_send_back_done_days(self):
        """友人の送り返しの 送り返し\\受付済み\\<日付>\\ も、受け取った日から KEEP_DAYS(3 日)より古い物だけ自動で移す(intake)"""
        sync = os.path.join(self.tmp, "sync")
        old_day, new_day = self.ymd(5), self.ymd(1)
        touch(os.path.join(sync, "送り返し", "受付済み", old_day, "r.zip"), 30)
        touch(os.path.join(sync, "送り返し", "受付済み", new_day, "r.zip"), 30)
        items = self.kind("intake", self.cleanup(), intake_dir=sync)   # 既定の KEEP_DAYS(3)
        self.assertEqual([i["name"] for i in items], [old_day])
        self.assertTrue(items[0]["dir"])
        self.assertIn("送り返し", items[0]["note"])

    def test_send_back_failed_by_mtime(self):
        """送り返しの 送り返し\\失敗\\ の物は更新日時から 3 日たったら自動で移す(failed)。理由の .txt は一緒に。新しい物は出ない"""
        sync = os.path.join(self.tmp, "sync")
        fail = os.path.join(sync, "送り返し", "失敗")
        old = touch(os.path.join(fail, "old.zip"), 40, mtime=self.now[0] - 5 * 86400)
        reason = touch(os.path.join(fail, "old.理由.txt"), 5, mtime=self.now[0] - 5 * 86400)
        touch(os.path.join(fail, "new.zip"), 40, mtime=self.now[0] - 1 * 86400)
        items = self.kind("failed", self.cleanup(), intake_dir=sync)
        self.assertEqual([i["path"] for i in items], [old])
        self.assertEqual(items[0]["extra"], [reason])
        self.assertEqual(items[0]["bytes"], 45)
        self.assertIn("送り返しの失敗", items[0]["note"])

    def test_intake_failed_by_mtime(self):
        """受付の 失敗\\ の物も、更新日時から 3 日たったら自動で移す(failed)。フォルダの mtime でも数える。新しい物は出ない"""
        sync = os.path.join(self.tmp, "sync")
        fail = os.path.join(sync, "失敗")
        old_dir = os.path.join(fail, "bad-folder")
        touch(os.path.join(old_dir, "a.mp4"), 20)
        os.utime(old_dir, (self.now[0] - 5 * 86400, self.now[0] - 5 * 86400))
        touch(os.path.join(fail, "new.mp4"), 20, mtime=self.now[0] - 1 * 86400)
        touch(os.path.join(fail, "bad.mp4.理由.txt"), 5, mtime=self.now[0] - 1 * 86400)
        items = self.kind("failed", self.cleanup(), intake_dir=sync)
        self.assertEqual([i["path"] for i in items], [old_dir])
        self.assertIn("受付の失敗", items[0]["note"])

    def write_case(self, folder, rid):
        from flow import placement
        d = {"schema": placement.CASE_SCHEMA, "id": "c-" + os.path.basename(folder)[-6:]}
        if rid:
            d["requestId"] = rid
        write_json(placement.case_path(folder), d)

    def write_deliveries(self, rows):
        write_text(os.path.join(self.app, "logs", C.DELIVERIES_LOG), "".join(json.dumps(r) + "\n" for r in rows))

    def test_auto_clean_delivered(self):
        """届けて keep_days 日たった切り抜き(届けた記録のパック + 切り抜きの動画 + _edit.mp4)と、届けた依頼の置き場所の動画とパックを
        自動でごみ箱へ。届けていない・日数がたっていない・確かめるで待っている・手で置いた依頼の動画・文書と字幕は残す。依頼の置き場所と
        届けた記録のパックが同じ物は 1 回だけ"""
        out = os.path.join(self.tmp, "出力")
        cl = self.cleanup(keep_days=3, out_dirs=[out])
        old, recent = int((self.now[0] - 5 * 86400) * 1000), int((self.now[0] - 1 * 86400) * 1000)
        case = os.path.join(out, "配信の題")
        clip = touch(os.path.join(case, "01_a.mp4"), 30)
        edit = touch(os.path.join(case, "作業用", "01_a_edit.mp4"), 4)
        doc = touch(os.path.join(case, "作業用", "01_a.transcript.json"), 2)   # 文書 = 残す
        pack = os.path.join(case, "01_a_pack")
        touch(os.path.join(pack, "01_a_edit.mp4"), 8)
        wait_clip = touch(os.path.join(case, "02_b.mp4"), 30)                 # 確かめるで待っている
        wait_pack = os.path.join(case, "02_b_pack")
        touch(os.path.join(wait_pack, "x.mp4"), 8)
        new_clip = touch(os.path.join(case, "03_c.mp4"), 30)                  # 届けたばかり
        new_pack = os.path.join(case, "03_c_pack")
        touch(os.path.join(new_pack, "x.mp4"), 8)
        undelivered = os.path.join(case, "04_d_pack")                         # 届けていない
        touch(os.path.join(undelivered, "x.mp4"), 8)
        req = os.path.join(out, C.REQUEST_DIR, "%s_題_aaaaaa" % self.ymd(20))   # 届けた依頼の置き場所(パックは届けた記録にもある)
        touch(os.path.join(req, "v.mp4"), 20)
        touch(os.path.join(req, "v_pack", "v.mp4"), 6)
        self.write_case(req, "20261001-120000-aaaaaa")
        manual = os.path.join(out, C.REQUEST_DIR, "%s_題_123abc" % self.ymd(20))   # 手で置いた動画 = 届けていない
        touch(os.path.join(manual, "m.mp4"), 11)
        self.write_case(manual, "")
        self.write_deliveries([{"requestId": "", "at": old, "packs": [{"dir": pack, "path": clip}, {"dir": wait_pack, "path": wait_clip}]},
                               {"requestId": "", "at": recent, "packs": [{"dir": new_pack, "path": new_clip}]},
                               {"requestId": "20261001-120000-aaaaaa", "at": old, "packs": [{"dir": os.path.join(req, "v_pack"), "path": ""}]}])
        dry = cl.auto_clean([wait_clip], dry_run=True)
        self.assertEqual(sorted(sorted(os.path.basename(p) for p in it["parts"]) for it in dry["items"]),
                         [["01_a.mp4", "01_a_edit.mp4", "01_a_pack"], ["v.mp4", "v_pack"]])
        self.assertEqual((dry["moved"], dry["bytes"]), (0, 30 + 4 + 8 + 20 + 6))
        self.assertTrue(os.path.isfile(clip))                                 # dry_run は移さない
        r = cl.auto_clean([wait_clip])
        self.assertEqual((r["moved"], r["failed"]), (2, 0))
        for gone in (clip, edit, pack, os.path.join(req, "v.mp4")):
            self.assertFalse(os.path.exists(gone), gone)
        for kept in (doc, wait_clip, wait_pack, new_clip, new_pack, undelivered, os.path.join(manual, "m.mp4")):
            self.assertTrue(os.path.exists(kept), kept)
        self.assertEqual(cl.auto_clean([wait_clip])["items"], [])         # 2 回目は何も無い
        from unittest import mock
        with mock.patch.object(C, "AUTO_DELIVERED", False):                   # スイッチ
            touch(os.path.join(case, "01_a.mp4"), 30)
            self.assertEqual(cl.auto_clean([])["items"], [])

    def test_request_folders_from_last_delivery_or_receipt(self):
        """書き出し先の 依頼/<日付>_<題>_<id6>/ は、最後に届けてから keep_days 日で自動で移す。手で置いた動画(case.json に requestId が無い)・
        届けていない・case.json の無いフォルダは移さない。移すのは動画とパックだけ(作業用の文書は残す)"""
        out = os.path.join(self.tmp, "出力")
        cl = self.cleanup(keep_days=3, out_dirs=[out])
        old = self.ymd(20)
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
        by = {i["path"]: i for i in self.kind("intake", cl)}
        self.assertEqual(sorted(by), [d_ok])
        self.assertIn("届けてから 10 日", by[d_ok]["note"])
        self.assertEqual(by[d_ok]["bytes"], 37)                           # 動画 + パック(文書は数えない)
        r = cl.move([by[d_ok]["id"]])
        self.assertEqual((len(r["moved"]), r["failed"]), (1, []))
        self.assertFalse(os.path.exists(os.path.join(d_ok, "v.mp4")) or os.path.exists(os.path.join(d_ok, "v_pack")))
        self.assertTrue(os.path.isfile(os.path.join(d_ok, "作業用", "0123456789ab.json")))   # 文書は残る
        self.assertTrue(os.path.isfile(os.path.join(self.app, "ごみ箱", self.ymd(), "intake", os.path.basename(d_ok), "v.mp4")))
        self.assertEqual(self.kind("intake", cl), [])                     # 片付けたフォルダはもう出ない
        self.assertTrue(os.path.isfile(os.path.join(d_manual, "m.mp4")))   # 手で置いた動画は残る
        os.remove(os.path.join(self.app, "logs", C.DELIVERIES_LOG))       # 記録が読めなければ何も移さない
        touch(os.path.join(d_ok, "v.mp4"), 30)
        self.assertEqual(self.kind("intake", cl), [])

    def test_app_intake_copies(self):
        """作業データの app/intake/<日付>/<依頼 id>/(受付の写し)も、届けた依頼だけ同じ決まりで自動で移す。
        m で始まる id(手で置いた動画)・<日付>/ 直下の動画(依頼 id の分からない形)・届けていない・新しい物は移さない"""
        old, new = self.ymd(20), self.ymd(1)
        base = os.path.join(self.app, C.APP_INTAKE)
        sent = touch(os.path.join(base, old, "20261001-120000-aaaaaa", "a.mp4"), 10)
        touch(os.path.join(base, old, "20261001-120000-bbbbbb", "b.mp4"), 10)   # 届けていない
        man = touch(os.path.join(base, old, "m1a2b3c4d", "c.mp4"), 10)
        loose = touch(os.path.join(base, old, "x.mp4"), 10)
        touch(os.path.join(base, new, "m9999aaaa", "d.mp4"), 10)                # まだ新しい
        self.write_deliveries([{"requestId": "20261001-120000-aaaaaa", "at": int((self.now[0] - 5 * 86400) * 1000)}])
        items = self.kind("intake", self.cleanup(keep_days=3))
        got = sorted(p for i in items for p in i["parts"])
        self.assertEqual(got, [sent])
        self.assertTrue(os.path.isfile(man) and os.path.isfile(loose))

    def test_names_come_from_their_owners(self):
        from flow import placement
        from human.friend import friend_feedback
        self.assertEqual(C.DELIVERIES_LOG, friend_feedback.DELIVERIES_LOG)
        self.assertEqual(C.REQUEST_DIR, placement.REQUEST_DIR)

    def test_move_only_known_and_purge(self):
        """move は auto_items が出した物だけ移す(ほかの id は unknown)・同じ名前は (1)・purge は TRASH_DAYS を過ぎた日付だけ消す"""
        sync = os.path.join(self.tmp, "sync")
        fail = os.path.join(sync, "失敗")
        p1 = touch(os.path.join(fail, "x.zip"), 50, mtime=self.now[0] - 5 * 86400)
        self.cl = self.cleanup()   # 既定の KEEP_DAYS(3)
        ids = [i["id"] for i in self.kind("failed", intake_dir=sync)]
        res = self.cl.move([ids[0], "nope", 3])
        self.assertEqual([m["path"] for m in res["moved"]], [p1])
        self.assertEqual(res["unknown"], ["nope", "3"])
        self.assertFalse(os.path.exists(p1))
        day = self.ymd()
        self.assertTrue(os.path.isfile(os.path.join(self.app, "ごみ箱", day, "failed", "x.zip")))
        with open(os.path.join(self.app, "ごみ箱", day, "manifest.jsonl"), encoding="utf-8") as f:
            self.assertIn(p1.replace("\\", "\\\\"), f.read())
        self.assertEqual(self.cl.move([ids[0]])["unknown"], [ids[0]])   # 移した物はもう出ない
        touch(os.path.join(fail, "x.zip"), 5, mtime=self.now[0] - 5 * 86400)   # 同じ名前が来たら (1) を付ける
        self.cl.move([i["id"] for i in self.kind("failed", intake_dir=sync)])
        self.assertTrue(os.path.isfile(os.path.join(self.app, "ごみ箱", day, "failed", "x (1).zip")))
        # purge: TRASH_DAYS(3 日)を過ぎた日付のフォルダだけ消す(keep_days とは別)
        self.assertEqual(self.cl.purge(), 0)
        self.now[0] += 2 * 86400
        self.assertEqual(self.cl.purge(), 0)
        self.now[0] += 2 * 86400
        self.assertEqual(self.cl.purge(), 1)
        self.assertFalse(os.path.isdir(os.path.join(self.app, "ごみ箱", day)))

    def test_trash_on_the_same_drive(self):
        """作業データと別のドライブの物は、そのドライブの書き出し先\\ごみ箱(無ければ <ドライブ>\\youtube-tools ごみ箱)。purge もそこを見る"""
        out = os.path.join(self.tmp, "E", "切り抜き")
        cl = self.cleanup(out_dirs=lambda: [out])
        saved = C._drive
        C._drive = lambda p: "e:" if os.path.normcase(os.path.abspath(p)).startswith(os.path.normcase(os.path.join(self.tmp, "E"))) else "c:"
        try:
            self.assertEqual(cl.trash_for(os.path.join(out, "x", "a.mp4")), os.path.join(out, "ごみ箱"))
            self.assertEqual(cl.trash_for(os.path.join(self.app, "logs", "x.old.log")), os.path.join(self.app, "ごみ箱"))
            day = self.ymd(20)
            touch(os.path.join(out, "ごみ箱", day, "export", "a.mp4"))
            self.assertEqual(cl.purge(), 1)
            self.assertFalse(os.path.isdir(os.path.join(out, "ごみ箱", day)))
        finally:
            C._drive = saved

    def test_remember_root_keeps_old_list_when_write_fails(self):
        """trash-roots.json は原子的に書く: 書く途中で失敗しても前の一覧が残る"""
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
        old = self.ymd(20)
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
