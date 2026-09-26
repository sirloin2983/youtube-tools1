#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案件(配信1本)ごとの紐づけ(app/cases.py)と、入口の /api/cases のテスト。本物の作業データは使わない。
実行(リポジトリ直下): python -m unittest app/test_cases.py"""
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import cases  # noqa: E402

VID = "abcdefghijk"


def mark(mid, status, path="", start=10.0, end=40.0, label="見どころ"):
    return {"id": mid, "label": label, "start": start, "end": end, "status": status, "file": os.path.basename(path), "path": path}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "repo")
        self.data = os.path.join(self.tmp, "data")
        self.env = {"YTT_DATA_DIR": self.data}
        self.exports = os.path.join(self.tmp, "exports")
        os.makedirs(self.exports)
        self.clip1 = self.touch(os.path.join(self.exports, "01_見どころ.mp4"))
        self.clip2 = self.touch(os.path.join(self.exports, "02_次.mp4"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def touch(path, text="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def studio(self, videos):
        p = os.path.join(self.data, "studio", "data.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"schema": "x", "videos": videos}, f, ensure_ascii=False)

    def transcript(self, tid, source, proofed=1, total=3, clip=None, updated=1):
        d = {"id": tid, "title": "文字起こし" + tid, "sourcePath": source, "updatedAt": updated,
             "segments": [{"id": "s%d" % i, "start": i * 2.0, "end": i * 2.0 + 1.5, "text": "t", "proofed": i < proofed} for i in range(total)]}
        if clip:
            d["clip"] = clip
        p = os.path.join(self.data, "transcribe", "transcripts", tid + ".json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)


class TestBuild(Base):
    def test_links_clips_transcripts_and_packs(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "channel": "ch", "updatedAt": 5,
                           "marks": [mark("m1", "exported", self.clip1), mark("m2", "exported", self.clip2, 50, 80),
                                     mark("m3", "adopted"), mark("m4", "")]}})
        self.transcript("aaaaaaaaaaaa", self.clip1, proofed=3, total=3)                       # 動画のパスが同じ
        self.transcript("bbbbbbbbbbbb", os.path.join(self.tmp, "moved", "02_次.mp4"),
                        clip={"source": {"videoId": VID}, "mark": {"id": "m2"}})              # 動画を動かしても .clip.json の配信・マークで
        self.transcript("cccccccccccc", os.path.join(self.tmp, "other.mp4"))                  # どこにも紐づかない
        self.touch(os.path.join(self.exports, "01_見どころ_pack", "cut-plan.json"), "{}")
        self.touch(os.path.join(self.exports, "01_見どころ_pack", "textplus-import.json"), "{}")
        res = cases.snapshot(self.root, self.env)
        self.assertEqual(len(res["cases"]), 1)
        c = res["cases"][0]
        self.assertEqual((c["id"], c["title"], c["marks"]), (VID, "配信A", {"total": 4, "adopted": 1, "exported": 2, "candidates": 1}))
        c1, c2 = c["clips"]
        self.assertEqual((c1["markId"], c1["exists"], c1["transcript"]["id"], c1["transcript"]["proofed"]), ("m1", True, "aaaaaaaaaaaa", 3))
        self.assertTrue(c1["pack"]["textplus"])
        self.assertEqual((c2["transcript"]["id"], c2["pack"]), ("bbbbbbbbbbbb", None))
        self.assertEqual([t["id"] for t in res["unlinked"]], ["cccccccccccc"])
        self.assertTrue(res["casesFile"].endswith(os.path.join("app", "cases.json")))
        self.assertFalse(os.path.exists(res["casesFile"]))   # 何も付けていなければファイルを作らない

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


class TestListExtras(Base):
    """一覧(1件1行)が使う合計・「次にやること」・配信日の目安(2026-09-26 画面の見直しで追加)"""

    def test_next_action_order_and_remaining(self):
        # m1: 書き出し済み・文字起こしなし / m2: 書き出し済み・文字起こしあり(校正未了)・パックあり / m3: 採用済みでまだ書き出していない
        self.studio({VID: {"kind": "youtube", "title": "配信A", "channel": "ch",
                           "marks": [mark("m1", "exported", self.clip1), mark("m2", "exported", self.clip2), mark("m3", "adopted")]}})
        self.transcript("aaaaaaaaaaaa", self.clip2, proofed=1, total=4)
        self.touch(os.path.join(self.exports, "02_次_pack", "cut-plan.json"), "{}")
        c = cases.snapshot(self.root, self.env)["cases"][0]
        # 採用済みでまだ書き出していないマークが1本あるので、いちばん優先度の高い「書き出し」が出る
        self.assertEqual(c["next"], {"kind": "export", "label": "書き出し", "count": 1})
        self.assertEqual(c["tx"], {"clips": 2, "withTranscript": 1, "segments": 4, "proofed": 1})
        self.assertEqual(c["packs"], {"have": 1, "total": 2, "textplus": 0})
        # 残作業の合計 = 書き出し1 + 文字起こしなし1(m1) + 校正が残っている1(m2) + パックがまだ1(m1) = 4
        self.assertEqual(c["remaining"], 4)

    def test_next_action_falls_through_to_pack_when_nothing_else_left(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        self.transcript("aaaaaaaaaaaa", self.clip1, proofed=2, total=2)   # 校正済み・パックだけまだ
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual(c["next"], {"kind": "pack", "label": "パックを作る", "count": 1})
        self.touch(os.path.join(self.exports, "01_見どころ_pack", "cut-plan.json"), "{}")
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertIsNone(c["next"])   # 書き出し・文字起こし・校正・パックが全部済み
        self.assertEqual(c["remaining"], 0)

    def test_streamed_at_prefers_upload_date_then_created_then_updated(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [], "analysis": {"uploadDate": "20260101"},
                           "createdAt": 500, "updatedAt": 900}})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual(c["streamedAt"], 1767225600000)   # 2026-01-01T00:00:00Z
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [], "createdAt": 500, "updatedAt": 900}})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual(c["streamedAt"], 500)   # 解析の日付が無ければ、案件が増えた時刻
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [], "updatedAt": 900}})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual(c["streamedAt"], 900)   # それも無ければ最後に触った時刻

    def test_gone_case_keeps_streamed_at_and_recomputes_next(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)],
                           "analysis": {"uploadDate": "20260101"}}})
        cases.update(self.root, VID, status="working", env=self.env)
        cases.snapshot(self.root, self.env)   # 最後に見えた紐づけ(streamedAt を含む)を保存
        self.studio({})   # スタジオから消える
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["gone"], c["streamedAt"], c["next"]["kind"]), (True, 1767225600000, "transcribe"))


class TestUpdate(Base):
    def test_status_memo_and_last_seen(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        r = cases.update(self.root, VID, status="posted", env=self.env)
        self.assertEqual(r["status"], "posted")
        cases.update(self.root, VID, memo="10/1 に投稿", env=self.env)
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["status"], c["memo"]), ("posted", "10/1 に投稿"))
        saved = cases.load_saved(os.path.join(self.data, "app", "cases.json"))
        self.assertEqual(saved[VID]["last"]["title"], "配信A")               # 最後に見えた紐づけ
        # スタジオから動画が消えても、状態を付けた案件は最後に見えた内容で残る
        self.studio({})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["id"], c["gone"], c["status"], c["clips"][0]["markId"]), (VID, True, "posted", "m1"))
        # 状態もメモも外すと、案件ファイルからも消える
        cases.update(self.root, VID, status="", memo="", env=self.env)
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"], [])

    def test_validation(self):
        for kw in ({"case_id": "../x"}, {"case_id": ""}, {"case_id": VID, "status": "done"},
                   {"case_id": VID, "memo": "x" * 2001}, {"case_id": VID, "memo": 3}, {"case_id": None}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                cases.update(self.root, kw.pop("case_id"), env=self.env, **kw)

    def test_does_not_touch_tool_data(self):
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        p = os.path.join(self.data, "studio", "data.json")
        with open(p, encoding="utf-8") as f:
            before = f.read()
        cases.update(self.root, VID, status="working", env=self.env)
        cases.snapshot(self.root, self.env)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)


if __name__ == "__main__":
    unittest.main()
