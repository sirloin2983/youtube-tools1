#!/usr/bin/env python3
"""評価ドリルと定点の「あと何分」(マスタープラン Q4。docs/plan/q3-q4-design.md の (c)。editor/ed_drill.py)のテスト。

    python -m unittest editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_drill -q                  # これだけ(editor/tests で)

- 選び方: 評価用の文書だけ・文字あり・未校正・聞き取れない印なし・直近 10 分に更新した文書は除く・同じ文書から 2 行まで・動画の無い文書は除く
- 行の保存: 409(updatedAt が違う)・proofedAt・updatedAt が上がる・新しい名前は話者の一覧に・判別の印を外す・校正の手間・評価用でなければ断る
- あと何分と条件(話者・配信・重なり・BGM・呼び名)・話者の候補(覚えた声 → メンバーのフォルダ → 配信の文脈)
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import time
import unittest
from unittest.mock import patch

from test_backend import S, StoreDir, write_json  # noqa: F401  (S = serve)

import ed_drill as DR  # noqa: E402  (serve を読み込んだあとなので、部品の場所は通っている)

OLD = int(time.time() * 1000) - 3600 * 1000   # 1 時間前(直近 10 分ではない)


def _seg(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def tid_of(n):
    return "%012x" % (0xabc000 + n)


class DrillBase(StoreDir):
    def setUp(self):
        super().setUp()
        DR._drill_cache.clear()
        self.media = os.path.join(self.tmp, "media")
        os.makedirs(self.media)
        self.video = os.path.join(self.media, "clip.mp4")
        with open(self.video, "wb") as f:
            f.write(b"\0" * 64)

    def doc(self, n, segs, ev=True, updated=OLD, **over):
        d = {"schema": "transcribe/v1", "id": tid_of(n), "title": "文書%d" % n, "sourcePath": self.video, "sourceName": "clip.mp4",
             "speakers": [], "segments": segs, "updatedAt": updated, "createdAt": 1}
        if ev:
            d["evalSet"] = True
        d.update(over)
        write_json(S.tx_path(tid_of(n)), d)
        return d

    def rd(self, n):
        with open(S.tx_path(tid_of(n)), encoding="utf-8") as f:
            return json.load(f)


class TestDrillPick(DrillBase):
    def test_only_eval_unproofed_and_two_per_doc(self):
        for n in range(1, 13):   # 12 本 × 4 行(候補は 3 行: 校正済み 1 行を除く)
            self.doc(n, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い"), _seg(3, 2, 3, "う"), _seg(4, 3, 4, "え", proofed=True)])
        self.doc(20, [_seg(1, 0, 1, "学習用")], ev=False)                                   # 評価用でない
        self.doc(21, [_seg(1, 0, 1, ""), _seg(2, 1, 2, "x", tags=["unclear"]), _seg(3, 2, 2, "長さ0")])   # 文字なし・聞き取れない・長さ 0
        r = DR.drill_pick(20, seed="a")
        self.assertEqual(len(r["rows"]), 20)
        per = {}
        for row in r["rows"]:
            per[row["id"]] = per.get(row["id"], 0) + 1
            self.assertNotEqual(row["rowId"], "s4")                                       # 校正済みは出さない
        self.assertTrue(all(v <= 2 for v in per.values()), per)
        self.assertNotIn(tid_of(20), per)
        self.assertNotIn(tid_of(21), per)
        self.assertEqual(r["pool"], 36)
        self.assertEqual(set(r["docs"]), set(per))
        one = r["docs"][r["rows"][0]["id"]]
        self.assertEqual(one["updatedAt"], OLD)
        self.assertIn("candidates", one)
        self.assertEqual(DR.drill_pick(20, seed="a")["rows"], r["rows"])                 # 同じ種なら同じ選び方(乱数)
        self.assertNotEqual([x["rowId"] + x["id"] for x in DR.drill_pick(20, seed="b")["rows"]], [x["rowId"] + x["id"] for x in r["rows"]])

    def test_recent_busy_and_missing_media_are_skipped(self):
        self.doc(1, [_seg(1, 0, 1, "あ")], updated=int(time.time() * 1000) - 60 * 1000)   # 1 分前に保存 = 開いている可能性
        self.doc(2, [_seg(1, 0, 1, "い")], effort={"activeSec": 30, "lastAt": int(time.time() * 1000)})   # 画面が校正の時間を送ったばかり
        self.doc(3, [_seg(1, 0, 1, "う")], sourcePath=os.path.join(self.media, "無い.mp4"))   # 動画が無い = 聞けない
        self.doc(4, [_seg(1, 0, 1, "え")])
        self.doc(5, [_seg(1, 0, 1, "お")])
        with S._jobs_lock:
            S._jobs["jx"] = {"id": "jx", "kind": "diarize", "state": "running", "spec": {"tid": tid_of(5)}, "tid": tid_of(5)}
        try:
            r = DR.drill_pick(20, seed=1)
        finally:
            with S._jobs_lock:
                S._jobs.pop("jx", None)
        self.assertEqual([x["id"] for x in r["rows"]], [tid_of(4)])
        self.assertEqual(r["recent"], 2)

    def test_empty(self):
        r = DR.drill_pick()
        self.assertEqual((r["rows"], r["pool"], r["recent"]), ([], 0, 0))
        self.assertEqual(r["status"]["docs"], 0)


class TestDrillRow(DrillBase):
    def test_save_row_proofed_updated_and_effort(self):
        self.doc(1, [_seg(1, 0, 1, "あ", flag="話者が不確か"), _seg(2, 1, 2, "い")],
                 speakers=[{"id": "S1", "name": "さくらみこ", "color": "#2f62d6"}])
        before = int(time.time() * 1000)
        r = DR.drill_row({"id": tid_of(1), "rowId": "s1", "baseUpdatedAt": OLD, "text": " あいう\n", "speaker": "S1", "tags": ["bgm", "xx"],
                          "proofed": True, "activeSec": 12, "newSession": True})
        d = self.rd(1)
        g = d["segments"][0]
        self.assertGreater(d["updatedAt"], OLD)                                             # updatedAt を上げる(開いている編集の画面の次の保存を 409 に)
        self.assertEqual(r["updatedAt"], d["updatedAt"])
        self.assertEqual((g["text"], g["speaker"], g["tags"], g["proofed"]), ("あいう", "S1", ["bgm"], True))
        self.assertGreaterEqual(g["proofedAt"], before)
        self.assertEqual(g["flag"], "")                                                    # 人が話者を選んだので判別の印は外す
        self.assertNotIn("proofed", d["segments"][1])                                       # ほかの行はそのまま
        self.assertEqual(d["evalSet"], True)
        self.assertEqual((d["effort"]["proofedRows"], d["effort"]["activeSec"], d["effort"]["sessions"]), (1, 12, 1))
        self.assertTrue(os.listdir(os.path.join(self.tmp, ".hist", tid_of(1))))            # 履歴を残す
        # 同じ文書の次の行は、返ってきた updatedAt で保存できる
        DR.drill_row({"id": tid_of(1), "rowId": "s2", "baseUpdatedAt": r["updatedAt"], "text": "い", "proofed": True})
        self.assertTrue(self.rd(1)["segments"][1]["proofed"])
        self.assertEqual(self.rd(1)["segments"][1]["speaker"], "")                          # speaker を送らなければ変えない

    def test_conflict_409(self):
        self.doc(1, [_seg(1, 0, 1, "あ")])
        with self.assertRaises(S.ApiError) as cm:
            DR.drill_row({"id": tid_of(1), "rowId": "s1", "baseUpdatedAt": OLD - 5, "text": "x", "proofed": True})
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.rd(1)["segments"][0]["text"], "あ")                         # 書かない

    def test_updated_at_always_moves_forward(self):
        future = int(time.time() * 1000) + 60000
        self.doc(1, [_seg(1, 0, 1, "あ")], updated=future)
        r = DR.drill_row({"id": tid_of(1), "rowId": "s1", "baseUpdatedAt": future, "text": "x", "proofed": True})
        self.assertEqual(r["updatedAt"], future + 1)

    def test_new_name_is_added_to_speakers(self):
        self.doc(1, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い")], speakers=[{"id": "S1", "name": "話者1", "color": "#2f62d6"}])
        r = DR.drill_row({"id": tid_of(1), "rowId": "s1", "baseUpdatedAt": OLD, "text": "あ", "speakerName": "さくらみこ", "proofed": True})
        d = self.rd(1)
        self.assertTrue(r["added"])
        self.assertEqual([s["name"] for s in d["speakers"]], ["話者1", "さくらみこ"])
        self.assertEqual(d["segments"][0]["speaker"], "S2")
        r2 = DR.drill_row({"id": tid_of(1), "rowId": "s2", "baseUpdatedAt": r["updatedAt"], "text": "い", "speakerName": "さくらみこ", "proofed": True})
        self.assertFalse(r2["added"])                                                       # 同じ名前は増やさない
        self.assertEqual(len(self.rd(1)["speakers"]), 2)
        self.assertEqual(self.rd(1)["segments"][1]["speaker"], "S2")
        with self.assertRaises(S.ApiError):
            DR.drill_row({"id": tid_of(1), "rowId": "s2", "baseUpdatedAt": r2["updatedAt"], "text": "い", "speaker": "S9", "proofed": True})   # 無い話者

    def test_refuses_non_eval_and_missing_row(self):
        self.doc(1, [_seg(1, 0, 1, "あ")], ev=False)
        with self.assertRaises(S.ApiError) as cm:
            DR.drill_row({"id": tid_of(1), "rowId": "s1", "baseUpdatedAt": OLD, "text": "x", "proofed": True})
        self.assertEqual(cm.exception.code, "not_eval")
        self.doc(2, [_seg(1, 0, 1, "あ")])
        with self.assertRaises(S.ApiError) as cm:
            DR.drill_row({"id": tid_of(2), "rowId": "s9", "baseUpdatedAt": OLD, "text": "x", "proofed": True})
        self.assertEqual(cm.exception.status, 404)


class TestDrillStatus(DrillBase):
    def test_left_minutes_and_conditions(self):
        st = DR.drill_status()
        self.assertEqual((st["leftSec"], st["ready"], st["docs"]), (900, False, 0))
        spk = [{"id": "S%d" % i, "name": nm, "color": ""} for i, nm in enumerate(["さくらみこ", "星街すいせい", "本人", "話者4", "兎田ぺこら"], 1)]
        # 校正済み 60 秒 × 4 行(話者 3 人 + 一般の名前 2 = 数えない)。聞き取れない行は数えない
        self.doc(1, [_seg(1, 0, 60, "みこちのはなし", proofed=True, speaker="S1"), _seg(2, 60, 120, "すいちゃん", proofed=True, speaker="S2", tags=["overlap"]),
                     _seg(3, 120, 180, "x", proofed=True, speaker="S3", tags=["bgm"]), _seg(4, 180, 240, "y", proofed=True, speaker="S4"),
                     _seg(5, 240, 900, "z", proofed=True, speaker="S5", tags=["unclear"]), _seg(6, 900, 901, "未", speaker="S5")],
                 speakers=spk, clip={"source": {"videoId": "AAA"}})
        self.doc(2, [_seg(1, 0, 30, "ぺこらだ", proofed=True, speaker="S5")], speakers=spk, clip={"source": {"videoId": "BBB"}})
        self.doc(3, [_seg(1, 0, 30, "まだ")], clip={"source": {"videoId": "CCC"}})          # 校正済みの行が無い文書の配信は数えない
        self.doc(4, [_seg(1, 0, 600, "学習用", proofed=True)], ev=False)                      # 評価用でない
        st = DR.drill_status()
        c = {x["key"]: x for x in st["conds"]}
        self.assertEqual(st["proofedSec"], 270)
        self.assertEqual(st["leftSec"], 630)
        self.assertEqual((st["docs"], st["rows"], st["pendingRows"]), (3, 5, 2))
        self.assertEqual(c["speakers"]["have"], 3)
        self.assertEqual(sorted(c["speakers"]["items"]), sorted(["さくらみこ", "星街すいせい", "兎田ぺこら"]))
        self.assertEqual((c["streams"]["have"], c["overlap"]["have"], c["bgm"]["have"]), (2, 60, 60))
        self.assertTrue(c["overlap"]["ok"] and c["bgm"]["ok"])
        self.assertFalse(c["speakers"]["ok"] or c["streams"]["ok"])
        self.assertEqual(c["calls"]["have"], 3)                                               # 名簿に当たる行(みこち・すいちゃん・ぺこら)
        self.assertFalse(st["ready"])

    def test_stream_key_folder(self):
        self.assertEqual(DR.drill_stream_key({"clip": {"source": {"videoId": "X1"}}}), "v:X1")
        k = DR.drill_stream_key({"sourcePath": os.path.join(self.tmp, "評価用データ01_ときのそら", "a.mp4")})
        self.assertEqual(k, "m:ときのそら")
        k2 = DR.drill_stream_key({"sourcePath": os.path.join(self.tmp, S.EVAL_STAGING, "a.mp4")})
        self.assertTrue(k2.startswith("d:"))


class TestDrillCandidates(DrillBase):
    def test_order_voice_folder_stream_then_others(self):
        root = os.path.join(self.tmp, "評価用")
        member = os.path.join(root, "1_JP", "01_0期生", "評価用データ01_ときのそら")
        other = os.path.join(root, "1_JP", "02_1期生", "評価用データ02_夜空メル")
        os.makedirs(member)
        os.makedirs(other)
        video = os.path.join(member, "評価用データ01_ときのそら_01_未.mp4")
        with open(video, "wb") as f:
            f.write(b"\0" * 64)
        write_json(S.SETTINGS, {"evalDirs": [root]})
        self.doc(1, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い", speaker="S1")], sourcePath=video, title="さくらみこ コラボ",
                 speakers=[{"id": "S1", "name": "話者1", "color": ""}])
        diar = {"schema": S.DIAR_SCHEMA, "latest": {"voices": {"speakers": {"S1": {"top": "白上フブキ", "score": 0.5, "decided": None},
                                                                               "S2": {"top": "星街すいせい", "score": 0.7, "decided": "星街すいせい"}}}}}
        write_json(S.diar_path(tid_of(1)), diar)
        with patch.object(S, "voices_summary", return_value={"voxceleb": [{"name": "兎田ぺこら", "sec": 50.0, "generic": False},
                                                                          {"name": "本人", "sec": 99.0, "generic": True}]}):
            r = DR.drill_candidates(tid_of(1))
        names = [(c["name"], c["from"], c["near"]) for c in r["candidates"]]
        self.assertEqual(names[:4], [("星街すいせい", "voice", True), ("白上フブキ", "voice", True), ("ときのそら", "folder", True), ("さくらみこ", "stream", True)])
        rest = [n for n, _f, near in names if not near]
        self.assertEqual(rest[0], "兎田ぺこら")                                                # ほかの覚えた声(一般的な名前は除く)
        self.assertIn("夜空メル", rest)                                                        # ほかのメンバーのフォルダ
        self.assertNotIn("0期生", rest)                                                        # 上の段のまとまりのフォルダは人ではない
        self.assertNotIn("JP", rest)
        self.assertNotIn("本人", [n for n, _f, _ in names])
        self.assertEqual((r["eval"], r["rows"], r["noSpeaker"], r["suggest"]), (True, 2, 1, "星街すいせい"))


class TestDrillHttp(DrillBase):
    def test_kit_css_is_cut_from_index(self):
        css = DR.drill_kit_css().decode("utf-8")
        self.assertTrue(css.startswith("/* ui-kit:css:begin */") and css.rstrip().endswith("/* ui-kit:css:end */"))
        self.assertIn(".btn{", css)


if __name__ == "__main__":
    unittest.main()
