#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案件(配信1本)ごとの紐づけ(src/home/cases.py)と、入口の /api/cases のテスト。本物の作業データは使わない。
実行(リポジトリ直下): python -m unittest src/home/tests/test_cases.py"""
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
TESTS = os.path.dirname(os.path.abspath(__file__))   # src/home/tests
HERE = os.path.dirname(TESTS)   # home(入口の部品)
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
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
        # 次にやることは仕掛かりを先に(TODO_ORDER = 校正 → パック → 文字起こし → 書き出し → 候補の確認。UI の見直し M1): 校正が残っている 1 本が先
        self.assertEqual(c["next"], {"kind": "proof", "label": "校正", "count": 1})
        self.assertEqual(c["tx"], {"clips": 2, "withTranscript": 1, "segments": 4, "proofed": 1})
        self.assertEqual(c["packs"], {"have": 1, "total": 2, "textplus": 0})
        # 残作業の合計 = 書き出し1 + 文字起こしなし1(m1) + 校正が残っている1(m2) + パックがまだ1(m1) = 4
        self.assertEqual(c["remaining"], 4)
        # 作業ごとの残りの数(ホームの「次にやること」の種類ごとの行。入口 0.42.0・S-6)。採用済みがあるので候補の確認は数えない
        self.assertEqual(c["todo"], {"review": 0, "export": 1, "transcribe": 1, "proof": 1, "pack": 1})

    def test_next_follows_the_todo_order_table(self):
        """M1: 案件の next は TODO_ORDER(ホームの「次にやること」の並びと同じ表)の順で最初に残っている作業。表は build() の todoOrder で画面にも渡す
        (同じ配信なら、上の一覧の先頭の作業と行のボタンが必ず同じになる)"""
        self.assertEqual(cases.TODO_ORDER, ("proof", "pack", "transcribe", "export", "review"))
        self.assertEqual(set(cases.TODO_LABEL), set(cases.TODO_ORDER))
        self.assertEqual(cases.build({}, [])["todoOrder"], list(cases.TODO_ORDER))
        # 作業が全部そろっている配信(校正が残る・校正済みでパックまだ・文字起こしまだ・採用済みの書き出しまだ)から、先頭を片付けるたびに次の順で出る
        clip3 = os.path.join(self.exports, "03_三.mp4")
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [
            mark("m1", "exported", self.clip1), mark("m2", "exported", self.clip2), mark("m3", "exported", clip3), mark("m4", "adopted")]}})
        self.transcript("aaaaaaaaaaaa", self.clip1, proofed=2, total=2)   # 校正済み・パックまだ
        self.transcript("bbbbbbbbbbbb", self.clip2, proofed=1, total=4)   # 校正が残っている
        order = []
        for step in range(4):
            c = cases.snapshot(self.root, self.env)["cases"][0]
            order.append(c["next"]["kind"])
            if step == 0:
                self.transcript("bbbbbbbbbbbb", self.clip2, proofed=4, total=4)               # 校正を済ませる → パック(m1 がまだ。m2 は作ってある)
                self.touch(os.path.join(self.exports, "02_次_pack", "cut-plan.json"), "{}")
            elif step == 1:
                self.touch(os.path.join(self.exports, "01_見どころ_pack", "cut-plan.json"), "{}")   # パックを作る → 文字起こし(m3)
            else:
                self.transcript("cccccccccccc", clip3, proofed=1, total=1)                   # 文字起こし → 書き出し(m4)。校正済みなのでパックの次はまた pack
                self.touch(os.path.join(self.exports, "03_三_pack", "cut-plan.json"), "{}")
        self.assertEqual(order, ["proof", "pack", "transcribe", "export"])
        # 「パックがまだ」でも校正が残っている切り抜きは、パックではなく校正(校正の前にパックを勧めない)
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        self.transcript("aaaaaaaaaaaa", self.clip1, proofed=1, total=2)
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["next"]["kind"], "proof")

    def test_review_candidates_until_something_is_picked(self):
        # 解析したが 1 本も採用していない配信: 確認前の候補(採用・見送りを付けていないマーク)の数を返す(入口 0.42.0・S-6)
        base = {"kind": "youtube", "title": "配信A", "analysis": {"uploadDate": "20260101"}}
        self.studio({VID: dict(base, marks=[mark("m1", ""), mark("m2", ""), mark("m3", "rejected"), mark("m4", "")])})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual(c["next"], {"kind": "review", "label": "候補の確認", "count": 3})   # 見送り(rejected)は数えない
        self.assertEqual(c["todo"], {"review": 3, "export": 0, "transcribe": 0, "proof": 0, "pack": 0})
        self.assertEqual(c["remaining"], 1)   # 候補の確認は候補の数ではなく、配信 1 本で 1 件
        # 1 本でも採用したら、残った候補は「選ばなかったもの」として数えない(次は書き出し)
        self.studio({VID: dict(base, marks=[mark("m1", "adopted"), mark("m2", ""), mark("m3", "rejected"), mark("m4", "")])})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["next"], c["todo"]["review"], c["remaining"]), ({"kind": "export", "label": "書き出し", "count": 1}, 0, 1))
        # 書き出し済みだけ(採用は 0)でも同じ(次は文字起こし)
        self.studio({VID: dict(base, marks=[mark("m1", "exported", self.clip1), mark("m2", "")])})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["todo"]["review"], c["next"]["kind"]), (0, "transcribe"))
        # 候補も無い(マーク 0)なら何も出さない
        self.studio({VID: dict(base, marks=[])})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["next"], c["todo"]["review"], c["remaining"]), (None, 0, 0))

    def test_gone_case_does_not_count_review_or_export(self):
        # スタジオから消えた配信は、候補の確認・書き出しをスタジオでできないので数えない(次にやることに出さない)
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "adopted"), mark("m2", "")]}})
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["todo"]["export"], 1)
        cases.update(self.root, VID, status="working", env=self.env)
        cases.snapshot(self.root, self.env)   # 最後に見えた紐づけを保存
        self.studio({})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["gone"], c["marks"]["adopted"], c["next"], c["todo"]["review"], c["todo"]["export"], c["remaining"]), (True, 1, None, 0, 0, 0))

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
