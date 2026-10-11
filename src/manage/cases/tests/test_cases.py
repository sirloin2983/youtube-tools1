#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案件(配信1本)ごとの紐づけ(src/manage/cases/cases.py)と、入口の /api/cases のテスト。本物の作業データは使わない。
実行(リポジトリ直下): python -m unittest src/manage/cases/tests/test_cases.py"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> cases -> manage -> src
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from manage.cases import cases  # noqa: E402
from manage.keep import cleanup  # noqa: E402
from human.friend import deliver  # noqa: E402
from manage.cases import txindex  # noqa: E402
from flow import casebook  # noqa: E402
from ytt import casefiles, schemas  # noqa: E402

VID = "abcdefghijk"
REC = "20261007-120000"   # ライブの録画の id(スタジオの配信の id = 録画の id)


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


class TestCaseFile(Base):
    def test_snapshot_reads_case_json_but_never_writes(self):
        from flow import placement
        self.studio({VID: {"kind": "youtube", "title": "配信A", "marks": [mark("m1", "exported", self.clip1)]}})
        self.assertIsNone(cases.snapshot(self.root, self.env)["cases"][0]["caseFile"])   # 無い案件は今までどおり
        self.assertFalse(os.path.exists(os.path.join(self.exports, "作業用", "case.json")))        # 読むだけ(④ は書かない)
        made = placement.ensure_case({"kind": "file", "path": self.clip1})
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["caseFile"], {"id": made["id"], "createdAt": made["createdAt"]})
        self.touch(os.path.join(self.exports, "作業用", "case.json"), "{壊れた")
        self.assertIsNone(cases.snapshot(self.root, self.env)["cases"][0]["caseFile"])


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


class TestAutoClips(Base):
    """自動でできた切り抜きの確認(線 D の M9・M12。入口 0.43.1): 札・未確認の数・失敗の文・採用 = 届ける・要らない = ごみ箱へ"""

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
        self.rows, self.hidden = [], []
        self.fs = FileStudio(os.path.join(self.data, "studio", "data.json"))
        self.trash = cleanup.Cleanup(os.path.join(self.data, "app"), out_dirs=[self.exports])
        self.dl = deliver.Deliveries(lambda: self.box, txindex.is_pack_dir)

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

    def pack(self, media):
        """cut2resolve が作ったパック(以前の形: フォルダの中の cut-plan.json)"""
        d = txindex.pack_dir(media)
        self.touch(os.path.join(d, "cut-plan.json"), json.dumps({"schema": schemas.CUT_PLAN_SCHEMA, "tool": {"name": "cut2resolve"}}))
        self.touch(os.path.join(d, "clip.mp4"), "v")
        return d

    def review(self, op, mid, **kw):
        kw = dict({"deliveries": self.dl, "studio": self.fs, "feedback": self.rows.append, "trash": self.trash, "hide": self.hidden.append, "env": self.env}, **kw)
        return cases.auto_review(self.root, {"op": op, "id": REC, "markId": mid}, **kw)

    def case(self):
        return next(c for c in cases.snapshot(self.root, self.env)["cases"] if c["id"] == REC)

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
        self.assertEqual(by["m1"]["auto"], {"origin": "auto", "originLabel": "配信中の候補", "score": None, "bench": False})
        self.assertEqual(by["m2"]["auto"], {"origin": "archive", "originLabel": "配信後の解析", "score": 0.88, "bench": True})   # 点数はスタジオのマークから
        self.assertIsNone(by["m3"]["auto"])   # 人の切り抜きは今までどおり
        self.assertNotIn("review", by["m3"])
        self.assertEqual(by["m1"]["review"], {"seenAt": 0, "deliveredAt": 0, "delivered": "", "failure": None, "unconfirmed": True})
        self.assertEqual((c["autoClips"], res["auto"]), ({"total": 2, "unconfirmed": 2}, {"total": 2, "unconfirmed": 2}))
        # .clip.json の点数が先(source.live.score)
        self.live_clip("10_自動.mp4", "auto", score=1.234)
        self.assertEqual(next(cl for cl in self.case()["clips"] if cl["markId"] == "m1")["auto"]["score"], 1.23)
        # ライブの録画でない配信は、.clip.json に origin があっても札を付けない(自動の採用はライブの録画だけ)
        self.studio({VID: {"kind": "youtube", "title": "配信", "marks": [mark("m1", "exported", self.auto1)]}})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["clips"][0]["auto"], c["autoClips"]), (None, {"total": 0, "unconfirmed": 0}))

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

    def test_seen_lowers_unconfirmed_and_is_kept_in_cases_file(self):
        code, r = self.review("seen", "m1")
        self.assertEqual(code, 200)
        self.assertTrue(r["review"]["seenAt"] > 0)
        c = self.case()
        m1 = next(cl for cl in c["clips"] if cl["markId"] == "m1")
        self.assertEqual((m1["review"]["unconfirmed"], c["autoClips"]["unconfirmed"]), (False, 1))
        first = m1["review"]["seenAt"]
        time.sleep(0.01)
        self.review("seen", "m1")   # 2 回目は最初の時刻のまま
        self.assertEqual(next(cl for cl in self.case()["clips"] if cl["markId"] == "m1")["review"]["seenAt"], first)
        # 状態・メモを外しても、確認の記録があれば案件ファイルに残る
        cases.update(self.root, REC, status="", memo="", env=self.env)
        self.assertIn("m1", cases.load_saved(os.path.join(self.data, "app", "cases.json"))[REC]["auto"])
        # 人の切り抜き・知らない切り抜き・正しくない指定は断る
        self.assertEqual(self.review("seen", "m3")[0], 409)
        self.assertEqual(self.review("seen", "m9")[0], 404)
        self.assertEqual(self.review("seen", "../x")[0], 400)
        self.assertEqual(self.review("open", "m1")[0], 400)
        self.assertEqual(cases.auto_review(self.root, {"op": "seen", "id": "../x", "markId": "m1"}, env=self.env)[0], 400)

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

    def test_deliver_puts_zip_in_output_and_records_it(self):
        code, r = self.review("deliver", "m1")
        self.assertEqual((code, r["message"]), (409, "パックがまだありません(文字起こし → パックが済むと届けられます)"))   # パックが無ければ採用できない
        self.pack(self.auto1)
        code, r = self.review("deliver", "m1", deliveries=deliver.Deliveries(lambda: "", txindex.is_pack_dir))
        self.assertEqual(code, 409)
        self.assertIn("Dropbox のフォルダが決まっていません", r["message"])   # 届ける先が無い: 理由をそのまま
        code, r = self.review("deliver", "m1")
        self.assertEqual(code, 200)
        j = self.wait_delivered(r["job"])
        self.assertEqual(j["state"], "done")
        zips = os.listdir(os.path.join(self.box, deliver.OUT_DIR))
        self.assertEqual(len(zips), 1)
        self.assertTrue(zips[0].endswith("__10_自動.zip"), zips)
        m1 = next(cl for cl in self.case()["clips"] if cl["markId"] == "m1")
        self.assertTrue(m1["review"]["deliveredAt"] > 0 and m1["review"]["seenAt"] > 0)
        self.assertEqual((m1["review"]["delivered"], m1["review"]["unconfirmed"]), (zips[0], False))
        self.assertEqual(len(self.rows), 1)
        row = self.rows[0]
        self.assertEqual({k: row[k] for k in ("event", "origin", "human", "verdict", "recorder", "recording", "markId", "studio", "start", "end", "delivered")},
                         {"event": "deliver", "origin": "auto", "human": True, "verdict": "good", "recorder": "local", "recording": REC, "markId": "lm-aaaaaaaaaaaa",
                          "studio": {"video": REC, "mark": "m1"}, "start": 10, "end": 40, "delivered": zips[0]})
        self.assertEqual(self.review("deliver", "m1")[0], 409)   # 二度は届けない
        self.assertEqual(self.review("deliver", "m3")[0], 409)   # 人の切り抜きはこの口では届けない

    def test_discard_moves_files_to_trash_rejects_mark_and_records(self):
        pk = self.pack(self.auto1)
        self.transcript("aaaaaaaaaaaa", self.auto1, proofed=0, total=2)
        clip_json = schemas.clip_path_for(self.auto1)
        code, r = self.review("discard", "m1")
        self.assertEqual(code, 200, r)
        self.assertEqual((r["moved"], r["studio"]), (3, "rejected"))   # 動画・パック・.clip.json
        for p in (self.auto1, pk, clip_json):
            self.assertFalse(os.path.exists(p), p)
        dest = r["trash"]
        self.assertTrue(dest.startswith(os.path.join(self.data, "app", cleanup.TRASH_DIR)), dest)
        self.assertEqual(os.path.basename(os.path.dirname(dest)), cases.DISCARD_KIND)
        self.assertTrue(os.path.isfile(os.path.join(dest, "10_自動.mp4")) and os.path.isfile(os.path.join(dest, "10_自動_pack", "cut-plan.json"))
                        and os.path.isfile(os.path.join(dest, schemas.WORK_DIR, "10_自動.clip.json")))
        with open(os.path.join(os.path.dirname(os.path.dirname(dest)), cleanup.MANIFEST), encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 3)   # 元の場所の記録(片付けと同じ)
        # スタジオのマークは不採用(画面と同じ PUT /api/video・baseRev つき)
        put = [c for c in self.fs.calls if c[0] == "PUT"]
        self.assertEqual(len(put), 1)
        self.assertEqual(put[0][2]["baseRev"], 1)
        self.assertEqual([m["status"] for m in put[0][2]["marks"] if m["id"] == "m1"], ["rejected"])
        # 誤検出の記録・文字起こしの非表示・一覧から消える(要らないにした文字起こしは「単体の文字起こし」にも出さない)
        self.assertEqual([{k: x[k] for k in ("event", "origin", "human", "verdict", "markId")} for x in self.rows],
                         [{"event": "reject", "origin": "auto", "human": True, "verdict": "bad", "markId": "lm-aaaaaaaaaaaa"}])
        self.assertEqual(self.hidden, ["aaaaaaaaaaaa"])
        res = cases.snapshot(self.root, self.env)
        c = next(x for x in res["cases"] if x["id"] == REC)
        self.assertEqual([cl["markId"] for cl in c["clips"]], ["m2", "m3"])
        self.assertEqual((c["autoClips"], res["unlinked"]), ({"total": 1, "unconfirmed": 1}, []))
        self.assertEqual(self.review("discard", "m1")[0], 404)   # もう一覧に無い

    def test_expire_unseen_after_three_days(self):
        """10-09 ユーザー決定: 見ても届けてもいない自動の切り抜きは、作ってから EXPIRE_SEC で「要らない」と同じくごみ箱へ(人の判定なしの expire の行)。
        新しい・見た・人の切り抜き・友人の依頼(live.deliver か結びつき)・届けている途中は片付けない"""
        old = time.time() - cases.EXPIRE_SEC - 60
        for p in (self.auto1, self.auto2, self.manual):
            os.utime(p, (old, old))
        kw = {"studio": self.fs, "feedback": self.rows.append, "trash": self.trash, "hide": self.hidden.append, "deliveries": self.dl, "env": self.env}
        self.review("seen", "m2")   # 見た → 片付けない
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: False, **kw), [(REC, "m1")])
        self.assertFalse(os.path.exists(self.auto1))
        self.assertTrue(os.path.isfile(self.auto2) and os.path.isfile(self.manual))
        self.assertEqual([{k: x.get(k) for k in ("event", "human", "verdict", "markId")} for x in self.rows],
                         [{"event": "expire", "human": False, "verdict": None, "markId": "lm-aaaaaaaaaaaa"}])   # 人の「悪い」ではない
        rec = cases.load_saved(os.path.join(self.data, "app", "cases.json"))[REC]["auto"]["m1"]
        self.assertTrue(rec.get("expiredAt") and rec.get("discardedAt") and not rec.get("seenAt"))
        self.assertEqual([cl["markId"] for cl in self.case()["clips"]], ["m2", "m3"])
        # 新しいもの・友人の依頼の分は片付けない
        new_auto = self.live_clip("13_自動.mp4", "auto")
        friend = self.live_clip("14_依頼.mp4", "auto", deliver={"rid": "20261009-120000-abcdef", "auto": False})
        os.utime(friend, (old, old))
        with open(self.fs.path, encoding="utf-8") as f:
            st = json.load(f)
        st["videos"][REC]["marks"] += [mark("m5", "exported", new_auto, 140, 170), mark("m6", "exported", friend, 180, 210)]
        with open(self.fs.path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: False, **kw), [])
        os.utime(new_auto, (old, old))
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: True, **kw), [])   # 録画が友人の依頼に結びついている
        self.assertEqual(cases.expire_unseen(self.root, is_request=lambda rc, rec: False, **kw), [(REC, "m5")])

    def test_discard_puts_files_back_when_studio_fails(self):
        pk = self.pack(self.auto2)
        for setup, code in ((lambda: setattr(self.fs, "down", True), 502), (lambda: setattr(self.fs, "refuse", True), 502)):
            self.fs.down = self.fs.refuse = False
            setup()
            got, r = self.review("discard", "m2")
            self.assertEqual(got, code, r)
            self.assertIn("片付けませんでした", r["message"])
            self.assertTrue(os.path.isfile(self.auto2) and os.path.isdir(pk) and os.path.isfile(schemas.clip_path_for(self.auto2)))   # 元に戻した
            self.assertEqual((self.rows, self.hidden), ([], []))
        self.assertEqual(next(cl for cl in self.case()["clips"] if cl["markId"] == "m2")["review"]["unconfirmed"], True)
        # 人の切り抜きは動かさない
        self.fs.down = self.fs.refuse = False
        self.assertEqual(self.review("discard", "m3")[0], 409)
        self.assertTrue(os.path.isfile(self.manual))

    def test_discard_refuses_while_delivering(self):
        pk = self.pack(self.auto1)

        class Busy:
            @staticmethod
            def running(d):
                return os.path.normcase(d) == os.path.normcase(pk)
        code, r = self.review("discard", "m1", deliveries=Busy())
        self.assertEqual(code, 409)
        self.assertIn("届けている途中", r["message"])
        self.assertTrue(os.path.isfile(self.auto1))


class TestCaseRoot(Base):
    """案件にした配信(RS8 B3-6): 状態・メモ・自動の確認は 採用.json の上の段・一覧は書き出し先の走査 ∪ 索引"""

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

    def test_listed_once_with_index(self):
        self.index()
        self.assertEqual([c["id"] for c in cases.snapshot(self.root, self.env)["cases"]], [VID])

    def test_update_writes_upper_tier_not_cases_json(self):
        self.index()
        before = self.adopts()
        got = cases.update(self.root, VID, status="working", memo="メモ", env=self.env)
        self.assertEqual((got["status"], got["memo"]), ("working", "メモ"))
        a = self.adopts()
        self.assertEqual((a["status"], a["memo"]), ("working", "メモ"))
        self.assertTrue(a["statusUpdatedAt"])
        self.assertEqual((a["marks"], a["sources"]), (before["marks"], before["sources"]))   # marks・sources は触らない
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]))
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["status"], c["memo"]), ("working", "メモ"))
        cases.update(self.root, VID, status="", memo="", env=self.env)
        self.assertEqual(cases.snapshot(self.root, self.env)["cases"][0]["status"], "")

    def test_carries_cases_json_row_on_first_write(self):
        self.index()
        loc = cases.locations(self.root, self.env)
        cases._write(loc["cases"], {VID: {"status": "posted", "memo": "前の", "statusUpdatedAt": 7, "last": {"title": "x"}}})
        c = cases.snapshot(self.root, self.env)["cases"][0]
        self.assertEqual((c["status"], c["memo"]), ("posted", "前の"))   # 採用.json が空の間は cases.json の行を使う
        cases.update(self.root, VID, memo="新しい", env=self.env)
        a = self.adopts()
        self.assertEqual((a["status"], a["memo"], a["statusUpdatedAt"]), ("posted", "新しい", 7))   # 引き継いで書く
        self.assertEqual(cases.load_saved(loc["cases"]), {})   # cases.json の行は消える

    def test_auto_review_remembered_in_case(self):
        self.index()
        r = cases._remember(self.root, VID, "m1", self.env)
        self.assertTrue(r["seenAt"])
        self.assertIn("m1", self.adopts()["auto"])
        cases._remember(self.root, VID, "m1", self.env, delivered="z.zip")
        self.assertEqual(self.adopts()["auto"]["m1"]["delivered"], "z.zip")
        self.assertFalse(os.path.exists(cases.locations(self.root, self.env)["cases"]))

    def test_unseen_case_folder_says_so(self):
        self.index()
        shutil.rmtree(self.folder)
        with self.assertRaises(ValueError) as cm:
            cases.update(self.root, VID, status="working", env=self.env)
        self.assertIn("見えません", str(cm.exception))
        self.assertFalse(os.path.exists(self.folder))   # 勝手に作り直さない

    def test_non_case_video_still_uses_cases_json(self):
        other = "zzzzzzzzzzz"
        self.studio({other: {"kind": "youtube", "title": "別", "marks": []}})
        cases.update(self.root, other, status="working", env=self.env)
        self.assertEqual(cases.load_saved(cases.locations(self.root, self.env)["cases"])[other]["status"], "working")


if __name__ == "__main__":
    unittest.main()
