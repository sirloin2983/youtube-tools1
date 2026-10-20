#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案件(配信1本)ごとの紐づけ(src/manage/cases/cases.py)と、入口の /api/cases のテスト。本物の作業データは使わない。
実行(リポジトリ直下): python -m unittest tests/manage/cases/test_cases.py"""
import json
import os
import shutil
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> cases -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from manage.cases import cases  # noqa: E402
from manage.keep import cleanup  # noqa: E402
from flow import deliver, packrec  # noqa: E402
from manage.cases import txindex  # noqa: E402
from flow import casebook  # noqa: E402
from ytt import casefiles, schemas, trashbin  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
from testkit import read_json, tempdir, write_json, write_text  # noqa: E402

VID = "abcdefghijk"
REC = "20261007-120000"   # ライブの録画の id(スタジオの配信の id = 録画の id)


def mark(mid, status, path="", start=10.0, end=40.0, label="見どころ"):
    return {"id": mid, "label": label, "start": start, "end": end, "status": status, "file": os.path.basename(path), "path": path}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempdir(self)
        self.root = os.path.join(self.tmp, "repo")
        self.data = os.path.join(self.tmp, "data")
        self.env = {"YTT_DATA_DIR": self.data}
        self.exports = os.path.join(self.tmp, "exports")
        os.makedirs(self.exports)
        self.clip1 = self.touch(os.path.join(self.exports, "01_見どころ.mp4"))
        self.clip2 = self.touch(os.path.join(self.exports, "02_次.mp4"))
        # パックを作った記録の置き場所(cases は env を渡さずに txindex.pack_info を読む = 環境変数 YTT_CUT2RESOLVE_DIR の下。リポジトリの .data に書かない)
        self.c2r = os.path.join(self.tmp, "cut2resolve")
        p = mock.patch.dict(os.environ, {"YTT_CUT2RESOLVE_DIR": self.c2r})
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def touch(path, text="x"):
        return write_text(path, text)

    def make_pack(self, d, textplus=False):
        """cut2resolve が作ったパック(パックを作った記録 = ② flow/packrec と、中身の動画 1 本)。d = パックのフォルダ(書き出し先からの名前でも)"""
        d = os.path.join(self.exports, d)
        video = self.touch(os.path.join(d, "clip.mp4"), "v")
        packrec.write_record({"out_dir": d, "files": [("video", video)]}, video, textplus, c2r_dir=self.c2r)
        return d

    def studio(self, videos):
        write_json(os.path.join(self.data, "studio", "data.json"), {"schema": "x", "videos": videos})

    def transcript(self, tid, source, proofed=1, total=3, clip=None, updated=1, **extra):
        d = {"id": tid, "title": "文字起こし" + tid, "sourcePath": source, "updatedAt": updated, **extra,
             "segments": [{"id": "s%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.5, "text": "t", "proofed": i < proofed} for i in range(total)]}
        if clip:
            d["clip"] = clip
        write_json(os.path.join(self.data, "transcribe", "transcripts", tid + ".json"), d)


class TestBuild(Base):
    def test_links_clips_transcripts_and_packs(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "channel": "ch", "updatedAt": 5,
                           "marks": [mark("m1", "exported", self.clip1), mark("m2", "exported", self.clip2, 50, 80),
                                     mark("m3", "adopted"), mark("m4", "")]}})
        self.transcript("aaaaaaaaaaaa", self.clip1, proofed=3, total=3)                       # 動画のパスが同じ
        self.transcript("bbbbbbbbbbbb", os.path.join(self.tmp, "moved", "02_次.mp4"),
                        clip={"source": {"videoId": VID}, "mark": {"id": "m2"}})              # 動画を動かしても .clip.json の配信・マークで
        self.transcript("cccccccccccc", os.path.join(self.tmp, "other.mp4"))                  # どこにも紐づかない
        self.make_pack("01_見どころ_pack", textplus=True)
        res = cases.snapshot(self.root, self.env)
        self.assertEqual(len(res["cases"]), 1)
        c = res["cases"][0]
        self.assertEqual((c["id"], c["title"], c["marks"]), (VID, "配信A", {"total": 4, "adopted": 1, "exported": 2, "candidates": 1}))
        c1, c2 = c["clips"]
        self.assertEqual((c1["markId"], c1["exists"], c1["transcript"]["id"], c1["transcript"]["proofed"]), ("m1", True, "aaaaaaaaaaaa", 3))
        self.assertTrue(c1["pack"]["textplus"])
        self.assertEqual((c2["transcript"]["id"], c2["pack"]), ("bbbbbbbbbbbb", None))
        self.assertEqual([t["id"] for t in res["unlinked"]], ["cccccccccccc"])
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]))   # 何も付けていなければファイルを作らない

    def test_newest_transcript_wins_and_missing_video(self):
        gone = os.path.join(self.exports, "消えた.mp4")
        self.studio({VID: {"kind": "youtube", "title": "配信", "marks": [mark("m1", "exported", gone)]}})
        self.transcript("aaaaaaaaaaaa", gone, updated=1)
        self.transcript("bbbbbbbbbbbb", gone, updated=9)
        cl = cases.snapshot(self.root, self.env)["cases"][0]["clips"][0]
        self.assertEqual((cl["exists"], cl["transcript"]["id"], cl["transcripts"]), (False, "bbbbbbbbbbbb", 2))

    def test_broken_or_missing_data(self):
        res = cases.snapshot(self.root, self.env)
        self.assertEqual((res["cases"], res["unlinked"]), ([], []))
        self.touch(os.path.join(self.data, "studio", "data.json"), "{壊れた")
        self.touch(os.path.join(self.data, "transcribe", "transcripts", "dddddddddddd.json"), "[")
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"], [])


class TestFullAuto(Base):
    """まとめて実行の自動で送る形。送らなかった物 = ② の送らなかった記録 logs/not-sent.jsonl(案件の auto[マーク].origin "full" と
    notSent = 読むだけ)・送った物 = 届けた記録の mode full・origin auto。どちらもライブでなくても clip["auto"](品質のカードの対象)・notSent は届けていない間だけ
    review に出る・届けた・送らなかったは案件に写さない"""

    def test_revision_changes_when_delivered(self):
        from flow import deliveries
        before = cases.revision(self.root, self.env)
        self.assertEqual(before, cases.revision(self.root, self.env))   # 何も変わらなければ同じ
        deliveries.record_not_sent(cases.locations(self.root, self.env)["logs"], VID, "m1", "stale", "理由")
        os.makedirs(os.path.dirname(cases.locations(self.root, self.env)["runs"]), exist_ok=True)
        with open(os.path.join(cases.locations(self.root, self.env)["logs"], "deliveries.jsonl"), "a", encoding="utf-8") as f:
            f.write("{}\n")
        self.assertNotEqual(before, cases.revision(self.root, self.env))   # 届けた記録が増えた = ホームが一覧を読み直す

    def test_not_sent_and_sent_full_clips(self):
        import types
        from flow import deliveries
        clip3 = self.touch(os.path.join(self.exports, "03_三.mp4"))
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1, label="一"), mark("m2", "exported", self.clip2, 50, 80),
                                                                         mark("m3", "exported", clip3, 90, 99)]}})
        logs = cases.locations(self.root, self.env)["logs"]
        deliveries.record_not_sent(logs, VID, "m1", "stale", "前の理由")
        r = deliveries.record_not_sent(logs, VID, "m1", "stale", "古い配信なので送りません(終わってから 50 時間)")   # 同じ切り抜きは新しい方
        self.assertEqual((r["code"], r["markId"]), ("stale", "m1"))

        def send(clip, mid, zip_name, origin, mode="full", rid=""):
            d = txindex.pack_dir(clip)
            deliveries.record(logs, zip_name, types.SimpleNamespace(request_id=rid, id="r1", video_id=VID, title="", mode=mode), [d],
                              {d: {"path": clip, "markId": mid}}, origin=origin)
        send(self.clip2, "m2", "t__z.zip", "auto")
        c = cases.snapshot(self.root, self.env)["cases"][0]
        m1, m2, m3 = c["clips"]
        self.assertEqual((m1["auto"]["origin"], m1["auto"]["originLabel"], m1["review"]["notSent"]["text"]),
                         ("full", "まとめて実行", "古い配信なので送りません(終わってから 50 時間)"))
        self.assertEqual(set(m1["review"]), {"deliveredAt", "delivered", "failure", "notSent"})   # 見た・未確認・保留は無い
        self.assertEqual((m2["auto"]["origin"], m2["review"]["delivered"], m2["review"]["deliveredAt"] > 0, "notSent" in m2["review"]), ("full", "t__z.zip", True, False))
        self.assertIsNone(m3["auto"], "印の無い切り抜きは今までどおり人の切り抜き")
        self.assertEqual(c["autoClips"], {"total": 2})
        self.assertEqual((cases.load_saved(cases.locations(self.root, self.env)["cases"]).get(VID) or {}).get("auto") or {}, {}, "届けた・送らなかったは案件に写さない")
        send(self.clip1, "m1", "t__手.zip", "manual", mode="")   # 手で届けた = 送らなかった理由は出さない(印 full は送らなかった記録のまま)
        m1 = cases.snapshot(self.root, self.env)["cases"][0]["clips"][0]
        self.assertEqual((m1["auto"]["origin"], m1["review"]["delivered"], "notSent" in m1["review"]), ("full", "t__手.zip", False))
        send(clip3, "m3", "rid__依頼.zip", "request", rid="rid")   # 友人の依頼で届けた mode full は「まとめて実行の自動」ではない
        self.assertIsNone(cases.snapshot(self.root, self.env)["cases"][0]["clips"][2]["auto"])
        self.assertFalse(hasattr(cases, "remember_auto"), "案件へ写す口は無い")

    def test_old_case_marks_not_read(self):
        """案件の auto[マーク] に古く書かれた origin "full"・notSent は読まない"""
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        cases._write(cases.locations(self.root, self.env)["cases"],
                     {VID: {"auto": {"m1": {"origin": "full", "notSent": {"code": "stale", "text": "古い", "at": 5}}}}})
        m1 = cases.snapshot(self.root, self.env)["cases"][0]["clips"][0]
        self.assertIsNone(m1["auto"])


class TestCasesC0(Base):
    """案件の画面の下ごしらえ: root・caseKind・切り抜きごとの状態・仮の案件(file・eval・orphan)・todo の集計・文書から案件を引く"""

    def raw_doc(self, tid, source, evalset=False, proofed=0, total=2):
        self.transcript(tid, source, proofed=proofed, total=total, updated=5, evalSet=evalset)

    def test_clip_state(self):
        tx = lambda s, p: {"segments": s, "proofed": p}
        self.assertEqual(cases.clip_state(None, None), {"state": "none"})
        self.assertEqual(cases.clip_state(tx(0, 0), None)["state"], "none")
        self.assertEqual(cases.clip_state(tx(4, 1), None), {"state": "proofing"})
        self.assertEqual(cases.clip_state(tx(4, 4), None), {"state": "proofed"})
        self.assertEqual(cases.clip_state(tx(4, 1), {"dir": "x"})["state"], "packed")   # パックがあれば校正の途中でも packed

    def test_stream_case_fields(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "updatedAt": 5,
                           "marks": [mark("m1", "exported", self.clip1), mark("m2", "exported", self.clip2, 50, 80)]}})
        self.transcript("aaaaaaaaaaaa", self.clip1, proofed=1, total=3)
        self.transcript("bbbbbbbbbbbb", self.clip2, proofed=3, total=3)
        res = cases.snapshot(self.root, self.env)
        c = res["cases"][0]
        self.assertEqual((c["caseKind"], c["root"], c["kind"]), ("stream", "", "youtube"))   # 案件にしていない配信は root が空・kind は今までどおり
        self.assertEqual([(cl["state"], cl["transcriptIds"]) for cl in c["clips"]], [("proofing", ["aaaaaaaaaaaa"]), ("proofed", ["bbbbbbbbbbbb"])])
        self.assertEqual(c["failed"], 0)

    def test_root_of_case_stream(self):
        root = os.path.join(self.tmp, "case1")
        os.makedirs(root)
        self.studio({VID: {"kind": "youtube", "title": "配信A", "case": root, "marks": []}})
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["root"], root)

    def test_virtual_rows_always_exist_and_do_not_touch_cases(self):
        res = cases.snapshot(self.root, self.env)
        self.assertEqual(res["cases"], [])
        self.assertEqual([(c["id"], c["caseKind"], c["clips"]) for c in res["virtual"]], [("eval", "eval", []), ("orphan", "orphan", [])])

    def test_virtual_eval_orphan_and_file_case(self):
        from flow import placement
        made = placement.ensure_case({"kind": "file", "path": self.clip1})   # exports/作業用/case.json(動画ファイルの案件)
        self.raw_doc("aaaaaaaaaaaa", self.clip1, proofed=1)                  # 動画ファイルの案件
        self.raw_doc("bbbbbbbbbbbb", os.path.join(self.tmp, "x", "e.mp4"), evalset=True, proofed=2)   # 評価用
        self.raw_doc("cccccccccccc", os.path.join(self.tmp, "y", "o.mp4"))   # どこにも当たらない
        res = cases.snapshot(self.root, self.env)
        self.assertEqual(res["cases"], [])
        rows = {c["id"]: c for c in res["virtual"]}
        self.assertEqual([c["id"] for c in res["virtual"]], [made["id"], "eval", "orphan"])
        self.assertEqual((rows[made["id"]]["caseKind"], rows[made["id"]]["root"]), ("file", self.exports))
        self.assertEqual([cl["transcriptIds"] for cl in rows["eval"]["clips"]], [["bbbbbbbbbbbb"]])
        self.assertEqual(rows["eval"]["clips"][0]["state"], "proofed")
        self.assertEqual([cl["transcriptIds"] for cl in rows["orphan"]["clips"]], [["cccccccccccc"]])
        self.assertEqual(len(res["unlinked"]), 3)   # 今の unlinked は変えない(3 本とも入る)

    def test_find_doc(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        self.transcript("aaaaaaaaaaaa", self.clip1)
        self.raw_doc("cccccccccccc", os.path.join(self.tmp, "y", "o.mp4"))
        got = cases.find_doc(self.root, "aaaaaaaaaaaa", self.env)
        self.assertEqual((got["case"]["id"], got["markId"], got["docId"]), (VID, "m1", "aaaaaaaaaaaa"))
        got = cases.find_doc(self.root, "cccccccccccc", self.env)
        self.assertEqual((got["case"]["id"], got["markId"]), ("orphan", ""))
        self.assertIsNone(cases.find_doc(self.root, "ffffffffffff", self.env))
        with self.assertRaises(ValueError):
            cases.find_doc(self.root, "../x", self.env)


class TestListExtras(Base):
    """一覧(1件1行)が使う合計・配信日の目安"""

    def test_totals(self):
        # m1: 書き出し済み・文字起こしなし / m2: 書き出し済み・文字起こしあり(校正未了)・パックあり / m3: 採用済みでまだ書き出していない
        self.studio({VID: {"kind": "youtube", "title": "配信A", "channel": "ch",
                           "marks": [mark("m1", "exported", self.clip1), mark("m2", "exported", self.clip2), mark("m3", "adopted")]}})
        self.transcript("aaaaaaaaaaaa", self.clip2, proofed=1, total=4)
        self.make_pack("02_次_pack")
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual(c["tx"], {"clips": 2, "withTranscript": 1, "segments": 4, "proofed": 1})
        self.assertEqual(c["packs"], {"have": 1, "total": 2, "textplus": 0})
        self.assertEqual(c["failed"], 0)

    def test_gone_case_is_not_listed(self):
        """スタジオから消えた配信の行は一覧に出さない(前の状態・メモと最後に見えた紐づけ last は cases.json に残る = 読み飛ばすだけで書き換えない)"""
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "adopted"), mark("m2", "")]}})
        p = cases.locations(self.root, self.env)["cases"]
        cases._write(p, {VID: {"status": "working", "memo": "前の", "last": {"title": "配信A", "clips": [], "marks": {"adopted": 1}}}})
        with open(p, "rb") as f:
            before = f.read()
        self.assertEqual([c["id"] for c in cases.snapshot(self.root, self.env)["cases"]], [VID])
        self.studio({})
        res = cases.snapshot(self.root, self.env)
        self.assertEqual(res["cases"], [])
        with open(p, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_streamed_at_prefers_upload_date_then_created_then_updated(self):
        rows = [({"analysis": {"uploadDate": "20260101"}, "createdAt": 500, "updatedAt": 900}, 1767225600000),   # 2026-01-01T00:00:00Z
                ({"createdAt": 500, "updatedAt": 900}, 500),   # 解析の日付が無ければ、案件が増えた時刻
                ({"updatedAt": 900}, 900)]   # それも無ければ最後に触った時刻
        for extra, want in rows:
            with self.subTest(extra=extra):
                self.studio({VID: dict({"kind": "youtube", "title": "配信A", "marks": []}, **extra)})
                self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["streamedAt"], want)


class TestNoStatusMemo(Base):
    """案件の状態・メモ・「見た」「未確認」「保留」は持たない。採用.json・cases.json に古い欄が残っていても読み飛ばす(書き換えない)"""

    def test_old_fields_are_not_listed_and_not_rewritten(self):
        self.assertEqual((cases.AUTO_OPS, cases.FIELDS), (("deliver", "discard"), ("auto",)))
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        p = cases.locations(self.root, self.env)["cases"]
        cases._write(p, {VID: {"status": "posted", "memo": "10/1 に投稿", "statusUpdatedAt": 7, "last": {"title": "x"}}})
        with open(p, "rb") as f:
            before = f.read()
        res = cases.snapshot(self.root, self.env)
        for row in res["cases"] + res["virtual"]:
            for k in ("status", "memo", "statusUpdatedAt"):
                self.assertNotIn(k, row, (row["id"], k))
            self.assertEqual(set(row["autoClips"]), {"total"})
        self.assertEqual(res["auto"], {"total": 0})
        with open(p, "rb") as f:
            self.assertEqual(f.read(), before, "一覧は案件ファイルを書かない(最後に見えた紐づけも足さない)")

    def test_does_not_touch_tool_data(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        p = os.path.join(self.data, "studio", "data.json")
        with open(p, encoding="utf-8") as f:
            before = f.read()
        cases.snapshot(self.root, self.env)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]))


class FileStudio:
    """取り込んだスタジオの API(Live.studio_call)の代わり。読む・保存はテストの data.json に(案件の一覧に結果が出るように)。
    down = True でつながらない、refuse = True で PUT を断る"""

    def __init__(self, path):
        self.path, self.calls, self.down, self.refuse = path, [], False, False

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, json.loads(json.dumps(body)) if body is not None else None))
        if self.down:
            return None, {"message": "つながらない"}
        with open(self.path, encoding="utf-8") as f:
            doc = json.load(f)
        if method == "GET" and path.startswith("/api/video?id="):
            v = doc["videos"].get(path.split("=", 1)[1])
            return (200, {"video": dict(v, rev=v.get("rev", 1))}) if v else (404, {"message": "無い"})
        if method == "PUT" and path == "/api/video":
            if self.refuse:
                return 400, {"message": "マークが正しくありません"}
            v = doc["videos"][body["id"]]
            if body.get("baseRev") != v.get("rev", 1):
                return 409, {"message": "古い"}
            v.update(marks=body["marks"], rev=v.get("rev", 1) + 1)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            return 200, {"video": v}
        return 404, {"message": "なし"}


def busy(pack_dir):
    """このパックのフォルダだけ「届けている途中」と答える Deliveries の代わり"""
    return mock.Mock(running=lambda d: os.path.normcase(d) == os.path.normcase(pack_dir))


class TestAutoClips(Base):
    """自動でできた切り抜き: 札・失敗の文・届けた(② の届けた記録から)・採用 = 届ける・要らない = ごみ箱へ・
    人の判断は ③ human/judgments(live_feedback.jsonl には書かない)・日数の片付け"""

    def setUp(self):
        super().setUp()
        self.auto1 = self.live_clip("10_自動.mp4", "auto", markId="lm-aaaaaaaaaaaa")
        self.auto2 = self.live_clip("11_アーカイブ.mp4", "archive", bench=True)
        self.manual = self.live_clip("12_人.mp4", "manual")
        self.studio({REC: {"kind": "live", "title": "ライブ", "channel": "ch", "rev": 1, "marks": [
            mark("m1", "exported", self.auto1, 10, 40), dict(mark("m2", "exported", self.auto2, 50, 90), score=0.876),
            mark("m3", "exported", self.manual, 100, 130), mark("m4", "")]}})
        self.box = os.path.join(self.tmp, "Dropbox")   # 依頼の受付の見張るフォルダ(出力 はこの下)
        os.makedirs(self.box)
        self.hidden = []
        self.fs = FileStudio(os.path.join(self.data, "studio", "data.json"))
        self.trash = cleanup.Cleanup(os.path.join(self.data, "app"), out_dirs=[self.exports])
        self.logs = os.path.join(self.data, "app", "logs")   # 届けた記録(入口と同じ = 案件が引く場所)
        self.dl = deliver.Deliveries(lambda: self.box, txindex.is_pack_dir, log_dir=self.logs)
        self.since_path = os.path.join(self.data, "app", cases.EXPIRE_SINCE_FILE)
        self.touch(self.since_path, json.dumps({"v": 1, "at": 1}))   # 数え始めはずっと前(ほかの試験は作った時刻から数える)

    def live_clip(self, name, origin, **live):
        """ライブの書き出し(src/flow/live_export.py の _finish)と同じ形の .clip.json を 作業用 に置いた切り抜き"""
        media = self.touch(os.path.join(self.exports, name))
        clip = schemas.build_clip(media, 30.0, {"kind": "youtube", "videoId": "", "title": "ライブ"}, (10.0, 40.0),
                                  {"id": "lm-x", "label": "", "status": "exported", "src": "manual" if origin == "manual" else "auto"},
                                  {"mode": "precise", "fps": "30/1"}, {"name": "ytt-live", "version": "0.1.0"})
        clip["source"] = {"kind": "live", "videoId": "", "url": None, "title": "ライブ", "path": None,
                          "live": dict({"url": "", "recorder": "local", "recording": REC, "base": "", "start": "", "end": "", "markId": "lm-x", "origin": origin}, **live)}
        self.touch(schemas.clip_path_for(media), json.dumps(clip, ensure_ascii=False))
        return media

    def add_marks(self, *marks):
        st = read_json(self.fs.path)
        st["videos"][REC]["marks"] += marks
        write_json(self.fs.path, st)

    def pack(self, media):
        """cut2resolve が作ったパック(パックを作った記録と中身の動画)"""
        return self.make_pack(txindex.pack_dir(media))

    def review(self, op, mid, **kw):
        kw = dict({"deliveries": self.dl, "studio": self.fs, "trash": self.trash, "hide": self.hidden.append, "env": self.env}, **kw)
        return cases.auto_review(self.root, {"op": op, "id": REC, "markId": mid}, **kw)

    def case(self, cid=REC):
        return next(c for c in cases.snapshot(self.root, self.env)["cases"] if c["id"] == cid)

    def clip_of(self, mid, cid=REC):
        return next(cl for cl in self.case(cid)["clips"] if cl["markId"] == mid)

    def judged(self):
        from human import judgments
        return judgments.rows(cases.locations(self.root, self.env)["app"])

    def sent(self, pack_dir, at, zip_name, vid=REC, mid="", path="", mode="", origin=None):
        """届けた記録(② の deliveries.jsonl)に時刻を決めて 1 行"""
        row = {"at": at, "zip": zip_name, "requestId": "", "runId": "r", "videoId": vid, "title": "", "mode": mode,
               "packs": [{"dir": pack_dir, "path": path, "markId": mid}]}
        if origin:
            row["origin"] = origin
        os.makedirs(self.logs, exist_ok=True)
        with open(os.path.join(self.logs, cleanup.DELIVERIES_LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def assert_no_live_feedback(self):
        self.assertFalse(os.path.exists(os.path.join(self.data, "app", "live", "live_feedback.jsonl")), "live_feedback.jsonl に人の行を書かない")

    def wait_delivered(self, job):
        end = time.time() + 10
        while time.time() < end:
            j = self.dl.status(job["id"])
            if j["state"] != "running":
                return j
            time.sleep(0.02)
        self.fail("届け終わらない")

    def test_auto_badge_origin_score_bench_and_counts(self):
        res = cases.snapshot(self.root, self.env)
        c = next(x for x in res["cases"] if x["id"] == REC)
        by = {cl["markId"]: cl for cl in c["clips"]}
        self.assertEqual(by["m1"]["auto"], {"origin": "auto", "originLabel": "配信中の候補", "score": None, "bench": False, "deliver": False})
        self.assertEqual(by["m2"]["auto"], {"origin": "archive", "originLabel": "配信後の解析", "score": 0.88, "bench": True, "deliver": False})   # 点数はスタジオのマークから
        self.assertIsNone(by["m3"]["auto"])   # 人の切り抜きは今までどおり
        self.assertNotIn("review", by["m3"])
        self.assertEqual(by["m1"]["review"], {"deliveredAt": 0, "delivered": "", "failure": None})   # 見た・未確認・保留は無い
        self.assertEqual((c["autoClips"], res["auto"]), ({"total": 2}, {"total": 2}))
        # .clip.json の点数が先(source.live.score)
        self.live_clip("10_自動.mp4", "auto", score=1.234)
        self.assertEqual(self.clip_of("m1")["auto"]["score"], 1.23)
        # ライブの録画でない配信は、.clip.json に origin があっても札を付けない(自動の採用はライブの録画だけ)
        self.studio({VID: {"kind": "youtube", "title": "配信", "marks": [mark("m1", "exported", self.auto1)]}})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["clips"][0]["auto"], c["autoClips"]), (None, {"total": 0}))

    def test_clips_to_deliver_keep_the_mark(self):
        """届ける印つき(友人の依頼・live.autoDeliver)は clip.auto.deliver(日数の片付けで届けるまで待つ印)。review は届けた・失敗だけ"""
        self.live_clip("10_自動.mp4", "auto", markId="lm-aaaaaaaaaaaa", deliver={"rid": "20261009-120000-abcdef", "auto": False})
        m1 = self.clip_of("m1")
        self.assertEqual((m1["auto"]["deliver"], set(m1["review"])), (True, {"deliveredAt", "delivered", "failure"}))

    def test_delivered_comes_from_the_delivery_record(self):
        """届けた(clip.review の deliveredAt・delivered)は ② の届けた記録から毎回引く(案件に写さない)。配信とマークで引き、配信かマークの空の古い行は
        パックのフォルダの名前で(別の配信・別のマークの行は結ばない)。同じ切り抜きを二度届けたら新しい方。壊れた行は飛ばす"""
        at = 1760000000000
        pk1, pk2 = txindex.pack_dir(self.auto1), txindex.pack_dir(self.auto2)   # m1 のパックはもう無い(フォルダの名前だけで結ぶ)
        self.sent(pk1, at, "r1__10_自動.zip", vid="")                           # 古い行: 配信もマークも空
        self.sent(pk2, at + 1, "r1__別.zip", vid="other000000")                 # 別の配信の行
        self.sent(os.path.join(self.tmp, "どこか", os.path.basename(pk2)), at + 2, "r1__別マーク.zip", vid="", mid="m9")   # 名前は同じでもマークが違う
        by = {cl["markId"]: cl["review"] for cl in self.case()["clips"] if cl.get("auto")}
        self.assertEqual((by["m1"]["deliveredAt"], by["m1"]["delivered"]), (at, "r1__10_自動.zip"))
        self.assertEqual((by["m2"]["deliveredAt"], by["m2"]["delivered"]), (0, ""))
        self.sent(pk2, at + 3, "r1__済.zip", mid="m2", path=self.auto2)
        self.sent(pk2, at + 4, "r1__二度目.zip", mid="m2", path=self.auto2)
        with open(os.path.join(self.logs, cleanup.DELIVERIES_LOG), "a", encoding="utf-8") as f:
            f.write("こわれた行\n")
        self.assertEqual((self.clip_of("m2")["review"]["deliveredAt"], self.clip_of("m2")["review"]["delivered"]), (at + 4, "r1__二度目.zip"))
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]), "届けたは案件ファイルに写さない")

    def test_clip_live_reads_only_live_clips(self):
        """.clip.json の読み方(まとめて実行の M8 = autorun.live_auto_origin も同じ): ライブの書き出しだけ。無い・ライブでないものは (None, None)"""
        live, cmark = cases.clip_live(self.auto1)
        self.assertEqual((live["origin"], cmark["src"]), ("auto", "auto"))
        self.assertEqual(cases.clip_live(None), (None, None))
        self.assertEqual(cases.clip_live(os.path.join(self.tmp, "無い.mp4")), (None, None))
        p = schemas.clip_path_for(self.auto1)
        with open(p, encoding="utf-8") as f:
            clip = json.load(f)
        clip["source"]["kind"] = "youtube"
        self.touch(p, json.dumps(clip, ensure_ascii=False))
        self.assertEqual(cases.clip_live(self.auto1), (None, None))

    def test_seen_is_gone_and_bad_requests(self):
        """「見た」(op seen)は無い: 古い画面から来ても 400 で何も書かない。人の切り抜き・知らない切り抜き・正しくない指定は断る"""
        code, r = self.review("seen", "m1")
        self.assertEqual((code, r["error"]), (400, "bad_request"))
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]))
        self.assertEqual(self.judged(), [])
        self.assertEqual(self.review("discard", "m3")[0], 409)
        self.assertEqual(self.review("deliver", "m9")[0], 404)
        self.assertEqual(self.review("deliver", "../x")[0], 400)
        self.assertEqual(self.review("open", "m1")[0], 400)
        self.assertEqual(cases.auto_review(self.root, {"op": "deliver", "id": "../x", "markId": "m1"}, env=self.env)[0], 400)

    def test_failure_text_comes_from_live_failures(self):
        jobs = [{"id": "lx-0000000001", "state": "done", "path": self.auto1, "label": "", "n": 1, "handoffError": "文字起こしへ渡せませんでした: 止まっています",
                 "studio": {"video": REC, "mark": "m1"}, "updated": "2026-10-07T10:00:00.000Z"},
                {"id": "lx-0000000002", "state": "done", "path": self.auto2, "label": "", "n": 2, "studio": {"video": REC, "mark": "m2"},
                 "updated": "2026-10-07T10:00:00.000Z"}]
        self.touch(os.path.join(self.data, "app", "live", "exports.json"), json.dumps({"schema": "ytt-live-exports/v1", "jobs": jobs}, ensure_ascii=False))
        by = {cl["markId"]: cl for cl in self.case()["clips"]}
        self.assertEqual(by["m1"]["review"]["failure"], {"kind": "handoff", "kindLabel": "まとめて実行へ渡す",
                                                         "text": "10_自動.mp4: 文字起こしへ渡せませんでした: 止まっています"})
        self.assertIsNone(by["m2"]["review"]["failure"])

    def test_deliver_passes_clip_for_the_delivery_record(self):
        """手で届けるも届けた記録に切り抜き(mp4 のパス・マーク・動画)を渡す = 友人の「要らない」で mp4 も片付く・案件の「届けた」も引ける"""
        self.pack(self.auto1)
        seen = {}
        start = self.dl.start
        self.dl.start = lambda d, title="", on_done=None, clip=None: seen.update(clip=clip) or start(d, title, on_done=on_done, clip=clip)
        code, r = self.review("deliver", "m1")
        self.assertEqual(code, 200)
        self.wait_delivered(r["job"])
        self.assertEqual(seen["clip"], {"path": self.auto1, "markId": "m1", "videoId": REC})

    def test_deliver_puts_zip_in_output_and_records_it(self):
        code, r = self.review("deliver", "m1")
        self.assertEqual((code, r["message"]), (409, "パックがまだありません(文字起こし → パックが済むと届けられます)"))   # パックが無ければ採用できない
        self.pack(self.auto1)
        code, r = self.review("deliver", "m1", deliveries=deliver.Deliveries(lambda: "", txindex.is_pack_dir))
        self.assertEqual(code, 409)
        self.assertIn("Dropbox のフォルダが決まっていません", r["message"])   # 届ける先が無い: 理由をそのまま
        self.assertEqual(self.judged(), [], "断ったときは人の判断を書かない")
        code, r = self.review("deliver", "m1")
        self.assertEqual((code, r["judged"]), (200, True))
        j = self.wait_delivered(r["job"])
        self.assertEqual(j["state"], "done")
        names = os.listdir(os.path.join(self.box, deliver.OUT_DIR))
        zips = [n for n in names if n.endswith(".zip")]
        self.assertEqual(len(zips), 1)
        self.assertTrue(zips[0].endswith("__10_自動.zip"), zips)
        self.assertEqual(sorted(names), sorted([zips[0], zips[0][:-4] + deliver.META_SUFFIX]), "手で届けるも出どころの印(友人には「依頼なし」)")
        rv = self.clip_of("m1")["review"]
        self.assertTrue(rv["deliveredAt"] > 0)
        self.assertEqual(rv["delivered"], zips[0])
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]), "届けたは案件に写さない(② の届けた記録から)")
        rows = self.judged()   # 人の判断(③ human/judgments)。live_feedback.jsonl には書かない
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0].get(k) for k in ("who", "videoId", "markId", "what", "origin", "via", "start", "end", "ref")},
                         {"who": "self", "videoId": REC, "markId": "m1", "what": "adopt", "origin": "live", "via": "cases", "start": 10, "end": 40,
                          "ref": {"recorder": "local", "recording": REC}})
        self.assertRegex(rows[0]["key"], r"^lf:\d+:%s:m1:deliver$" % REC)
        self.assert_no_live_feedback()
        self.assertEqual(self.review("deliver", "m1")[0], 409)   # 二度は届けない
        self.assertEqual(self.review("deliver", "m3")[0], 409)   # 人の切り抜きはこの口では届けない
        self.assertEqual(len(self.judged()), 1)

    def test_discard_moves_files_to_trash_rejects_mark_and_records(self):
        pk = self.pack(self.auto1)
        self.transcript("aaaaaaaaaaaa", self.auto1, proofed=0, total=2)
        clip_json = schemas.clip_path_for(self.auto1)
        code, r = self.review("discard", "m1")
        self.assertEqual(code, 200, r)
        self.assertEqual((r["moved"], r["studio"], r["judged"]), (3, "rejected", True))   # 動画・パック・.clip.json
        for p in (self.auto1, pk, clip_json):
            self.assertFalse(os.path.exists(p), p)
        dest = r["trash"]
        self.assertTrue(dest.startswith(os.path.join(self.data, "app", trashbin.TRASH_DIR)), dest)
        self.assertEqual(os.path.basename(os.path.dirname(dest)), cases.DISCARD_KIND)
        self.assertTrue(os.path.isfile(os.path.join(dest, "10_自動.mp4")) and os.path.isfile(os.path.join(dest, "10_自動_pack", "clip.mp4"))
                        and os.path.isfile(os.path.join(dest, schemas.WORK_DIR, "10_自動.clip.json")))
        with open(os.path.join(os.path.dirname(os.path.dirname(dest)), trashbin.MANIFEST), encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 3)   # 元の場所の記録(片付けと同じ)
        # スタジオのマークは不採用(画面と同じ PUT /api/video・baseRev つき)
        put = [c for c in self.fs.calls if c[0] == "PUT"]
        self.assertEqual(len(put), 1)
        self.assertEqual(put[0][2]["baseRev"], 1)
        self.assertEqual([m["status"] for m in put[0][2]["marks"] if m["id"] == "m1"], ["rejected"])
        # 人の判断(reject)・文字起こしの非表示・一覧から消える(要らないにした文字起こしは「単体の文字起こし」にも出さない)
        self.assertEqual([(x["what"], x["markId"], x["origin"], x["via"]) for x in self.judged()], [("reject", "m1", "live", "cases")])
        self.assertTrue(self.judged()[0]["key"].endswith(":%s:m1:reject" % REC))
        self.assert_no_live_feedback()
        self.assertEqual(self.hidden, ["aaaaaaaaaaaa"])
        res = cases.snapshot(self.root, self.env)
        c = next(x for x in res["cases"] if x["id"] == REC)
        self.assertEqual([cl["markId"] for cl in c["clips"]], ["m2", "m3"])
        self.assertEqual((c["autoClips"], res["unlinked"]), ({"total": 1}, []))
        rec = cases.load_saved(cases.locations(self.root, self.env)["cases"])[REC]["auto"]["m1"]
        self.assertEqual((bool(rec["discardedAt"]), rec["tx"], "seenAt" in rec), (True, "aaaaaaaaaaaa", False))
        self.assertEqual(self.review("discard", "m1")[0], 404)   # もう一覧に無い

    def test_expire_after_three_days(self):
        """「見た」の守りは無し。届けていない自動の切り抜きは作ってから・届けた物は届けてから EXPIRE_SEC でごみ箱へ。
        マークは不採用にせず人の判断も書かない(片付けは評価と無関係)。新しい・人の切り抜き・友人の依頼(live.deliver か結びつき)で届けていない物は片付けない"""
        old = time.time() - cases.EXPIRE_SEC - 60
        for p in (self.auto1, self.auto2, self.manual):
            os.utime(p, (old, old))
        kw = {"studio": self.fs, "trash": self.trash, "hide": self.hidden.append, "deliveries": self.dl, "env": self.env}
        self.assertEqual(sorted(cases.expire_unseen(self.root, is_request=lambda rc, rec: False, **kw)), [(REC, "m1"), (REC, "m2")])
        self.assertFalse(os.path.exists(self.auto1) or os.path.exists(self.auto2))
        self.assertTrue(os.path.isfile(self.manual))
        self.assertEqual((self.judged(), [c for c in self.fs.calls if c[0] == "PUT"]), ([], []))   # 人の判断を書かない・マークを不採用にしない
        self.assert_no_live_feedback()
        rec = cases.load_saved(cases.locations(self.root, self.env)["cases"])[REC]["auto"]["m1"]
        self.assertTrue(rec.get("expiredAt") and rec.get("discardedAt") and not rec.get("seenAt"))
        self.assertEqual([cl["markId"] for cl in self.case()["clips"]], ["m3"])
        # 新しいもの・友人の依頼の分は片付けない
        new_auto = self.live_clip("13_自動.mp4", "auto")
        friend = self.live_clip("14_依頼.mp4", "auto", deliver={"rid": "20261009-120000-abcdef", "auto": False})
        fresh = self.live_clip("15_届けたばかり.mp4", "auto")
        os.utime(friend, (old, old))
        os.utime(fresh, (old, old))
        self.add_marks(mark("m5", "exported", new_auto, 140, 170), mark("m6", "exported", friend, 180, 210), mark("m7", "exported", fresh, 220, 250))
        self.sent(txindex.pack_dir(fresh), int(time.time() * 1000), "r__届けたばかり.zip", mid="m7", path=fresh)   # 作ったのは前・届けたのは今
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: False, **kw), [])
        os.utime(new_auto, (old, old))
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: True, **kw), [])   # 録画が友人の依頼に結びついている
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: False, **kw), [(REC, "m5")])
        # 届けた物(友人の依頼も)は、届けてから EXPIRE_SEC で片付ける(既定オン)。スイッチ TRASH_DELIVERED がオフなら片付けない
        self.assertTrue(cases.TRASH_DELIVERED)
        self.sent(txindex.pack_dir(friend), int(old * 1000), "r__依頼.zip", mid="m6", path=friend)
        self.addCleanup(setattr, cases, "TRASH_DELIVERED", True)
        cases.TRASH_DELIVERED = False
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: True, **kw), [])
        cases.TRASH_DELIVERED = True
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: True, **kw), [(REC, "m6")])
        self.assertFalse(os.path.exists(friend))
        self.assertTrue(os.path.isfile(fresh))
        self.assertEqual((self.judged(), [c for c in self.fs.calls if c[0] == "PUT"]), ([], []))

    def test_expire_counts_from_the_first_round(self):
        """この版より前にできた届けていない切り抜きは、初めて見回った時刻(app の expire-since.json に 1 回だけ書く)から数える
        = 入れた直後の見回りでまとめて片付けない。新しい物は作ってから。ファイルが壊れていれば片付けない(安全側)"""
        os.remove(self.since_path)
        kw = {"studio": self.fs, "trash": self.trash, "hide": None, "deliveries": self.dl, "env": self.env, "is_request": lambda rc, rec: False}
        first = time.time()
        long_ago = first - 30 * 86400
        for p in (self.auto1, self.auto2):
            os.utime(p, (long_ago, long_ago))
        self.assertEqual(cases.expire_unseen(self.root, now=first, **kw), [])   # 初回: 古い物も動かない
        with open(self.since_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"v": 1, "at": int(first * 1000)})
        later = first + 86400   # 数え始めのあとに作った物は作ってから
        newer = self.live_clip("13_自動.mp4", "auto")
        os.utime(newer, (later, later))
        self.add_marks(mark("m5", "exported", newer, 140, 170))
        self.assertEqual(cases.expire_unseen(self.root, now=first + cases.EXPIRE_SEC - 60, **kw), [])
        self.assertEqual(sorted(cases.expire_unseen(self.root, now=first + cases.EXPIRE_SEC + 60, **kw)), [(REC, "m1"), (REC, "m2")])   # 書いた時刻は変えない
        self.assertEqual(cases.expire_unseen(self.root, now=later + cases.EXPIRE_SEC - 60, **kw), [])
        self.touch(self.since_path, "{壊れた")
        self.assertEqual(cases.expire_unseen(self.root, now=later + cases.EXPIRE_SEC + 60, **kw), [])   # 壊れていたら片付けない・書き直さない
        self.assertTrue(os.path.isfile(newer))
        with open(self.since_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{壊れた")
        self.touch(self.since_path, json.dumps({"v": 1, "at": int(first * 1000)}))
        self.assertEqual(cases.expire_unseen(self.root, now=later + cases.EXPIRE_SEC + 60, **kw), [(REC, "m5")])

    def test_expire_waits_while_delivering_or_unreadable(self):
        """届けている途中のパックは片付けない。届けた記録を読めないとき(届けたかが分からない)は何もしない"""
        from flow import deliveries
        old = time.time() - cases.EXPIRE_SEC - 60
        os.utime(self.auto1, (old, old))
        kw = {"studio": self.fs, "trash": self.trash, "hide": self.hidden.append, "env": self.env, "is_request": lambda rc, rec: False}
        with mock.patch.object(deliveries, "delivered_marks", lambda log_dir: None):
            self.assertEqual(cases.expire_unseen(self.root, deliveries=self.dl, **kw), [])
        self.assertEqual(cases.expire_unseen(self.root, deliveries=busy(txindex.pack_dir(self.auto1)), **kw), [])
        self.assertTrue(os.path.isfile(self.auto1))
        self.assertEqual(cases.expire_unseen(self.root, deliveries=self.dl, **kw), [(REC, "m1")])

    def test_full_clips_follow_the_same_rules(self):
        """まとめて実行の自動の採用(full)も同じ規則: 送らなかった物は作ってから・送った物は送ってから EXPIRE_SEC。人の切り抜きは触らない。
        要らないにした人の判断は origin auto(ライブの録画でない = key は配信の id)"""
        names = ("f1", "f2", "f3", "f4", "f5")
        clips = {n: self.touch(os.path.join(self.exports, "%s.mp4" % n)) for n in names}
        old = time.time() - cases.EXPIRE_SEC - 60
        for p in clips.values():
            os.utime(p, (old, old))
        self.studio({VID: {"kind": "youtube", "title": "配信", "rev": 1, "marks": [mark(n, "exported", clips[n], 10 * i, 10 * i + 5) for i, n in enumerate(names)]}})
        from flow import deliveries
        for n in ("f1", "f5"):
            deliveries.record_not_sent(cases.locations(self.root, self.env)["logs"], VID, n, "stale", "古い")
        self.sent(txindex.pack_dir(clips["f2"]), int(old * 1000), "f2.zip", vid=VID, mid="f2", path=clips["f2"], mode="full", origin="auto")
        self.sent(txindex.pack_dir(clips["f3"]), int(time.time() * 1000), "f3.zip", vid=VID, mid="f3", path=clips["f3"], mode="full", origin="auto")
        self.assertEqual([cl["markId"] for cl in self.case(VID)["clips"] if cl["auto"]], ["f1", "f2", "f3", "f5"])
        code, r = cases.auto_review(self.root, {"op": "discard", "id": VID, "markId": "f5"}, studio=self.fs, trash=self.trash, env=self.env)
        self.assertEqual(code, 200, r)
        self.assertEqual([(x["what"], x["origin"], x["key"].split(":")[2]) for x in self.judged()], [("reject", "auto", VID)])
        kw = {"studio": self.fs, "trash": self.trash, "hide": None, "deliveries": self.dl, "env": self.env}
        self.assertEqual(sorted(cases.expire_unseen(self.root, **kw)), [(VID, "f1"), (VID, "f2")])
        self.assertTrue(os.path.isfile(clips["f3"]) and os.path.isfile(clips["f4"]))
        self.assertEqual(len(self.judged()), 1)

    def test_discard_puts_files_back_when_studio_fails(self):
        pk = self.pack(self.auto2)
        for fault in ("down", "refuse"):
            self.fs.down = self.fs.refuse = False
            setattr(self.fs, fault, True)
            got, r = self.review("discard", "m2")
            self.assertEqual(got, 502, r)
            self.assertIn("片付けませんでした", r["message"])
            self.assertTrue(os.path.isfile(self.auto2) and os.path.isdir(pk) and os.path.isfile(schemas.clip_path_for(self.auto2)))   # 元に戻した
            self.assertEqual((self.judged(), self.hidden), ([], []))   # 片付けなかったので人の判断も書かない
        self.assertEqual(self.clip_of("m2")["review"]["deliveredAt"], 0)   # 一覧に残る
        # 人の切り抜きは動かさない
        self.fs.down = self.fs.refuse = False
        self.assertEqual(self.review("discard", "m3")[0], 409)
        self.assertTrue(os.path.isfile(self.manual))

    def test_discard_refuses_while_delivering(self):
        code, r = self.review("discard", "m1", deliveries=busy(self.pack(self.auto1)))
        self.assertEqual(code, 409)
        self.assertIn("届けている途中", r["message"])
        self.assertTrue(os.path.isfile(self.auto1))


class TestCaseRoot(Base):
    """案件にした配信: 自動でできた切り抜きの記録は 採用.json の上の段・一覧は書き出し先の走査 ∪ 索引。状態・メモの古い欄は書き換えない"""

    def setUp(self):
        super().setUp()
        out = os.path.join(self.tmp, "out")
        sdir = os.path.join(self.data, "studio")
        os.makedirs(sdir)
        with open(os.path.join(sdir, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"outDir": out}, f)
        self.out = out
        self.folder = os.path.join(out, "配信A")
        self.clip = self.touch(os.path.join(self.folder, "01_見どころ.mp4"))
        self.touch(os.path.join(self.folder, schemas.WORK_DIR, ".studio-id"), VID)
        video = {"id": VID, "kind": "youtube", "title": "配信A", "channel": "ch", "duration": 100.0, "updatedAt": 5,
                 "marks": [dict(mark("m1", "exported", self.clip), src="manual", createdAt=1000)]}
        cands, adopts = casebook.split(video, self.folder)
        casebook.write(self.folder, cands, adopts)

    def index(self, row=None):
        self.studio({VID: row or {"id": VID, "kind": "youtube", "title": "配信A", "case": self.folder}})

    def adopts(self):
        return casefiles.read(self.folder)[1]

    def test_listed_by_scan_without_index(self):
        self.studio({})   # 索引を失っても書き出し先の走査で一覧に出る
        res = cases.snapshot(self.root, self.env)
        self.assertEqual([c["id"] for c in res["cases"]], [VID])
        self.assertEqual(len(res["cases"][0]["clips"]), 1)

    def test_request_folder_scanned_and_case_json_only_ignored(self):
        self.studio({})
        req = os.path.join(self.out, "依頼", "2026-10-11_題_abc123")
        v2 = "yyyyyyyyyyy"
        c2, a2 = casebook.split({"id": v2, "kind": "file", "title": "依頼", "channel": "", "fileName": "a.mp4", "marks": []}, req)
        os.makedirs(os.path.join(req, schemas.WORK_DIR))
        casebook.write(req, c2, a2)
        bare = os.path.join(self.out, "依頼", "2026-10-11_空_def456", schemas.WORK_DIR)
        os.makedirs(bare)
        self.touch(os.path.join(bare, "case.json"), "{}")   # 採用.json が無い依頼の案件は配信が無いので一覧に出さない
        self.assertEqual(sorted(c["id"] for c in cases.snapshot(self.root, self.env)["cases"]), sorted([VID, v2]))

    def test_listed_once_with_index(self):
        self.index()
        self.assertEqual([c["id"] for c in cases.snapshot(self.root, self.env)["cases"]], [VID])

    def test_old_status_memo_are_kept_but_not_listed(self):
        self.index()
        a = self.adopts()
        a.update(status="posted", memo="メモ", statusUpdatedAt=7)
        casebook.write(self.folder, adoptions=a)
        before = self.adopts()
        c = cases.snapshot(self.root, self.env)["cases"][0]
        for k in ("status", "memo", "statusUpdatedAt"):
            self.assertNotIn(k, c)
        cases._remember(self.root, VID, "m1", self.env, discarded="")
        a = self.adopts()
        self.assertEqual((a["status"], a["memo"], a["statusUpdatedAt"]), ("posted", "メモ", 7))   # 古い欄は読んだまま書き戻す(書き換えない)
        self.assertEqual((a["marks"], a["sources"]), (before["marks"], before["sources"]))   # marks・sources は触らない
        self.assertTrue(a["auto"]["m1"]["discardedAt"])
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]))

    def test_carries_cases_json_auto_on_first_write(self):
        self.index()
        loc = cases.locations(self.root, self.env)
        cases._write(loc["cases"], {VID: {"status": "posted", "memo": "前の", "auto": {"m0": {"discardedAt": 5, "tx": ""}}, "last": {"title": "x"}}})
        with open(loc["cases"], "rb") as f:
            before = f.read()
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["autoClips"], {"total": 0})
        cases._remember(self.root, VID, "m1", self.env, expired=True)
        a = self.adopts()
        self.assertEqual(sorted(a["auto"]), ["m0", "m1"])   # 採用.json に auto が無い間は cases.json の auto を引き継いで書く
        self.assertEqual((a["status"], a["memo"], bool(a["auto"]["m1"]["expiredAt"])), ("", "", True))   # 状態・メモは引き継がない(読み飛ばす)
        with open(loc["cases"], "rb") as f:
            self.assertEqual(f.read(), before, "cases.json は書き換えない(以後は採用.json が勝つ)")

    def test_unseen_case_folder_says_so(self):
        self.index()
        shutil.rmtree(self.folder)
        with self.assertRaises(OSError) as cm:
            cases._remember(self.root, VID, "m1", self.env, discarded="")
        self.assertIn("見えません", str(cm.exception))
        self.assertFalse(os.path.exists(self.folder))   # 勝手に作り直さない

    def test_non_case_video_still_uses_cases_json(self):
        other = "zzzzzzzzzzz"
        self.studio({other: {"kind": "youtube", "title": "別", "marks": []}})
        cases._remember(self.root, other, "m1", self.env, discarded="")
        self.assertTrue(cases.load_saved(cases.locations(self.root, self.env)["cases"])[other]["auto"]["m1"]["discardedAt"])


if __name__ == "__main__":
    unittest.main()
