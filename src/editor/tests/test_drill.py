#!/usr/bin/env python3
"""評価ドリルと定点の「あと何分」(マスタープラン Q4。git の履歴(679ff01 以前)の docs/plan/q3-q4-design.md の (c)。eval/drill/drill.py。RS4-2 まで editor/ed_drill.py)のテスト。
2026-10-04 夜に作り直した形(動画 1 本ずつ・編集の画面で全部聞いて直す・文書の印 evalReviewed)。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_drill -q                  # これだけ(src/editor/tests で)

- 次の 1 本: 評価用・文字起こし済み・まだ確かめていない・直近 10 分に更新していない・処理中でない・飛ばしていない・動画がある文書から乱数で
- 確かめ済み: 残りの行を校正済み(proofedAt)・印(at・rows・durationSec)・409・updatedAt が上がる・履歴・画面の保存では消えない/書き換えられない・
  評価用を外すと消える・取り消し(印が校正済みにした行も戻す)・再認識(機械が行を書いた)で外れる
- あと何分と条件(確かめ済みの動画の長さ・条件は確かめ済みの動画の中で)・話者の候補(覚えた声 → メンバーのフォルダ → 配信の文脈)
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import time
import unittest
from unittest.mock import patch

from test_backend import S, StoreDir, write_json  # noqa: F401  (S = serve)

from eval.drill import drill as DR  # noqa: E402  (serve を読み込んだあとなので、部品の場所は通っている。RS4-2 に editor/ed_drill.py から)

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
             "model": "small", "speakers": [], "segments": segs, "updatedAt": updated, "createdAt": 1}
        if ev:
            d["evalSet"] = True
        d.update(over)
        write_json(S.tx_path(tid_of(n)), d)
        return d

    def rd(self, n):
        with open(S.tx_path(tid_of(n)), encoding="utf-8") as f:
            return json.load(f)

    def review(self, n, **kw):
        return DR.drill_reviewed(dict({"id": tid_of(n), "baseUpdatedAt": self.rd(n)["updatedAt"]}, **kw))


class TestDrillNext(DrillBase):
    def test_picks_one_unreviewed_eval_doc_at_random(self):
        for n in range(1, 9):
            self.doc(n, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い", proofed=True)])
        self.doc(20, [_seg(1, 0, 1, "学習用")], ev=False)                                   # 評価用でない
        self.doc(21, [_seg(1, 0, 1, "")], model="")                                         # 文字のある行が無い(文字起こし前)
        self.doc(22, [_seg(1, 0, 1, "済")], evalReviewed={"at": 1, "rows": 1, "durationSec": 30})   # 確かめ済み
        picked = {DR.drill_next(seed=i)["id"] for i in range(40)}
        self.assertEqual(picked, {tid_of(n) for n in range(1, 9)})                           # 乱数で(どの 1 本も出る)・ほかは出ない
        self.assertEqual(DR.drill_next(seed="a")["id"], DR.drill_next(seed="a")["id"])       # 同じ種なら同じ
        r = DR.drill_next(seed=1)
        self.assertTrue(r["title"].startswith("文書"))
        self.assertEqual((r["counts"]["eval"], r["counts"]["reviewed"], r["counts"]["untranscribed"]), (10, 1, 1))

    def test_skip_recent_busy_and_missing_media(self):
        self.doc(1, [_seg(1, 0, 1, "あ")], updated=int(time.time() * 1000) - 60 * 1000)   # 1 分前に保存 = 開いている可能性
        self.doc(2, [_seg(1, 0, 1, "い")], effort={"activeSec": 30, "lastAt": int(time.time() * 1000)})   # 画面が校正の時間を送ったばかり
        self.doc(3, [_seg(1, 0, 1, "う")], sourcePath=os.path.join(self.media, "無い.mp4"))   # 動画が無い = 聞けない
        self.doc(4, [_seg(1, 0, 1, "え")])
        self.doc(5, [_seg(1, 0, 1, "お")])
        self.doc(6, [_seg(1, 0, 1, "か")])
        with S._jobs_lock:
            S._jobs["jx"] = {"id": "jx", "kind": "diarize", "state": "running", "spec": {"tid": tid_of(5)}, "tid": tid_of(5)}
        try:
            got = {DR.drill_next(skip="%s,bad,%s" % (tid_of(6), "x" * 12), seed=i)["id"] for i in range(10)}
            r = DR.drill_next(skip=[tid_of(6), tid_of(4)])
        finally:
            with S._jobs_lock:
                S._jobs.pop("jx", None)
        self.assertEqual(got, {tid_of(4)})                                                   # 飛ばした文書(skip。壊れた id は無視)も出さない
        self.assertIsNone(r["id"])
        self.assertEqual((r["counts"]["recent"], r["counts"]["busy"], r["counts"]["noMedia"], r["counts"]["skipped"]), (2, 1, 1, 2))
        self.assertIn("次に出せる評価用の動画がありません", r["reason"])
        self.assertIn("このドリルで飛ばした 2 本", r["reason"])

    def test_empty(self):
        r = DR.drill_next()
        self.assertIsNone(r["id"])
        self.assertIn("評価用の文字起こしがまだありません", r["reason"])


class TestDrillReviewed(DrillBase):
    def test_marks_rows_proofed_and_writes_mark(self):
        self.doc(1, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い", proofed=True, proofedAt=1234), _seg(3, 2, 3, ""), _seg(4, 3, 4, "う", tags=["unclear"])],
                 speakers=[{"id": "S1", "name": "さくらみこ", "color": ""}], start=0, end=35.5, duration=35.5)
        before = int(time.time() * 1000)
        r = self.review(1, via="drill")
        d = self.rd(1)
        segs = {g["id"]: g for g in d["segments"]}
        self.assertGreater(d["updatedAt"], OLD)                                              # updatedAt を上げる(開いている画面の次の保存を 409 に)
        self.assertEqual(r["updatedAt"], d["updatedAt"])
        rv = d["evalReviewed"]
        self.assertEqual((rv["rows"], rv["durationSec"], rv["via"]), (3, 35.5, "drill"))
        self.assertGreaterEqual(rv["at"], before)
        self.assertEqual(r["evalReviewed"], rv)
        self.assertTrue(segs["s1"]["proofed"] and segs["s4"]["proofed"])                     # 残りの(文字のある)行を校正済みに
        self.assertEqual(segs["s1"]["proofedAt"], rv["at"])                                  # proofedAt = 印の時刻
        self.assertEqual(segs["s2"]["proofedAt"], 1234)                                      # 前から校正済みの行の時刻はそのまま
        self.assertNotIn("proofed", segs["s3"])                                              # 空の行は校正済みにしない
        self.assertEqual((r["proofed"], r["noSpeaker"]), (2, 3))
        self.assertEqual(d["effort"]["proofedRows"], 2)                                      # 校正の手間に数える
        self.assertTrue(os.listdir(os.path.join(self.tmp, ".hist", tid_of(1))))             # 履歴を残す
        self.assertTrue(DR.drill_is_reviewed(d))

    def test_conflict_and_bad_requests(self):
        self.doc(1, [_seg(1, 0, 1, "あ")])
        with self.assertRaises(S.ApiError) as cm:
            DR.drill_reviewed({"id": tid_of(1), "baseUpdatedAt": OLD - 5})
        self.assertEqual(cm.exception.status, 409)
        self.assertNotIn("evalReviewed", self.rd(1))                                         # 書かない
        with self.assertRaises(S.ApiError) as cm:
            DR.drill_reviewed({"id": tid_of(1)})                                             # 読み込んだときの版が無い
        self.assertEqual(cm.exception.status, 400)
        self.doc(2, [_seg(1, 0, 1, "あ")], ev=False)
        with self.assertRaises(S.ApiError) as cm:
            self.review(2)
        self.assertEqual(cm.exception.code, "not_eval")
        self.doc(3, [], model="")                                                            # 文字起こしせずに開いた文書
        with self.assertRaises(S.ApiError) as cm:
            self.review(3)
        self.assertEqual(cm.exception.code, "not_transcribed")
        self.doc(4, [_seg(1, 0, 1, "あ")])
        with S._jobs_lock:
            S._jobs["jx"] = {"id": "jx", "kind": "diarize", "state": "queued", "spec": {"tid": tid_of(4)}, "tid": tid_of(4)}
        try:
            with self.assertRaises(S.ApiError) as cm:
                self.review(4)
        finally:
            with S._jobs_lock:
                S._jobs.pop("jx", None)
        self.assertEqual(cm.exception.code, "busy")

    def test_silent_video_and_future_updated_at(self):
        self.doc(1, [], duration=31.0)                                                       # 文字起こし済みで行が 0(本当に無音)
        r = self.review(1)
        self.assertEqual((r["evalReviewed"]["rows"], r["evalReviewed"]["durationSec"], r["proofed"]), (0, 31.0, 0))
        future = int(time.time() * 1000) + 60000
        self.doc(2, [_seg(1, 0, 1, "あ")], updated=future)
        self.assertEqual(self.review(2)["updatedAt"], future + 1)                            # 必ず前より大きく

    def test_mark_survives_saves_and_is_not_writable(self):
        self.doc(1, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い")])
        self.review(1)
        d = self.rd(1)
        rv = d["evalReviewed"]
        segs = [dict(g, text=g["text"] + "直", end=g["end"] + 0.1) for g in d["segments"]]  # 人が後から文字・時刻を直す
        S.save_transcript(tid_of(1), {"title": "t", "speakers": [], "segments": segs, "baseUpdatedAt": d["updatedAt"], "evalSet": True,
                                      "evalReviewed": {"at": 1, "rows": 99}})                 # 画面から送った印は使わない
        d2 = self.rd(1)
        self.assertEqual(d2["evalReviewed"], rv)
        S.save_transcript(tid_of(1), {"title": "t", "speakers": [], "segments": d2["segments"], "baseUpdatedAt": d2["updatedAt"], "evalReviewed": None})
        self.assertEqual(self.rd(1)["evalReviewed"], rv)                                      # 消すこともできない
        d3 = self.rd(1)
        S.save_transcript(tid_of(1), {"title": "t", "speakers": [], "segments": d3["segments"], "baseUpdatedAt": d3["updatedAt"], "evalSet": False})
        self.assertNotIn("evalReviewed", self.rd(1))                                         # 評価用を外すと消える
        self.doc(2, [_seg(1, 0, 1, "あ")])
        S.save_transcript(tid_of(2), {"title": "t", "speakers": [], "segments": [], "evalReviewed": {"at": 1}})
        self.assertNotIn("evalReviewed", self.rd(2))                                         # 画面から付けることもできない

    def test_unreviewed_restores_rows_the_mark_proofed(self):
        self.doc(1, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い", proofed=True, proofedAt=1234), _seg(3, 2, 3, "う")])
        self.review(1)
        d = self.rd(1)
        with self.assertRaises(S.ApiError) as cm:
            DR.drill_unreviewed({"id": tid_of(1), "baseUpdatedAt": d["updatedAt"] - 1})
        self.assertEqual(cm.exception.status, 409)
        r = DR.drill_unreviewed({"id": tid_of(1), "baseUpdatedAt": d["updatedAt"]})
        d2 = self.rd(1)
        segs = {g["id"]: g for g in d2["segments"]}
        self.assertNotIn("evalReviewed", d2)
        self.assertEqual(r["unproofed"], 2)
        self.assertNotIn("proofed", segs["s1"])
        self.assertNotIn("proofed", segs["s3"])
        self.assertEqual((segs["s2"]["proofed"], segs["s2"]["proofedAt"]), (True, 1234))     # 前から校正済みの行はそのまま
        self.assertGreater(d2["updatedAt"], d["updatedAt"])
        self.assertEqual(DR.drill_unreviewed({"id": tid_of(1), "baseUpdatedAt": d2["updatedAt"]})["unproofed"], 0)   # 印が無ければ何もしない

    def test_rerecognition_removes_mark(self):
        self.doc(1, [_seg(1, 0, 1, "あ"), _seg(2, 1, 2, "い")])
        self.review(1)
        S.apply_retranscribe({"tid": tid_of(1), "model": "m", "autoDict": False}, {"s1": ("A", "")})   # 機械が行を書き換えた
        d = self.rd(1)
        self.assertNotIn("evalReviewed", d)
        self.assertNotIn("proofed", d["segments"][0])
        doc = {"evalReviewed": {"at": 1}}
        S.record_rerun(doc, {"model": "m"}, "range", [(0, 1)], [])                          # 範囲・全体・疑わしい所も同じ所を通る
        self.assertNotIn("evalReviewed", doc)
        # 行の無い文書(確かめ済みにしていた)へ文字起こしを入れたときも外す
        self.doc(2, [], model="", evalReviewed={"at": 1, "rows": 0, "durationSec": 30})
        self.assertEqual(S.fill_doc({"intoDoc": tid_of(2), "sourcePath": os.path.normcase(os.path.abspath(self.video))},
                                    {"segments": [_seg(1, 0, 1, "機械")], "model": "small"}), tid_of(2))
        self.assertNotIn("evalReviewed", self.rd(2))


class TestDrillStatus(DrillBase):
    def test_left_minutes_and_conditions_from_reviewed_docs(self):
        st = DR.drill_status()
        self.assertEqual((st["leftSec"], st["ready"], st["docs"], st["reviewedDocs"]), (900, False, 0, 0))
        spk = [{"id": "S%d" % i, "name": nm, "color": ""} for i, nm in enumerate(["さくらみこ", "星街すいせい", "本人", "話者4", "兎田ぺこら"], 1)]
        rv = {"at": 1, "rows": 5, "durationSec": 240}
        self.doc(1, [_seg(1, 0, 60, "みこちのはなし", proofed=True, speaker="S1"), _seg(2, 60, 120, "すいちゃん", proofed=True, speaker="S2", tags=["overlap"]),
                     _seg(3, 120, 180, "x", proofed=True, speaker="S3", tags=["bgm"]), _seg(4, 180, 200, "y", proofed=True, speaker="S4"),
                     _seg(5, 200, 230, "ぺこら", proofed=True, speaker="S5", tags=["unclear"])],
                 speakers=spk, clip={"source": {"videoId": "AAA"}}, evalReviewed=rv)
        # 印の長さが無い = 文書の長さ(最後の行の終わり)
        self.doc(2, [_seg(1, 0, 30, "ぺこらだ", proofed=True, speaker="S5")], speakers=spk, clip={"source": {"videoId": "BBB"}}, evalReviewed={"at": 1})
        # 確かめていない評価用の文書(全行校正済みでも数えない = すき間を聞いていない)
        self.doc(3, [_seg(1, 0, 300, "ときのそらです", proofed=True, speaker="S1", tags=["bgm"])], speakers=spk, clip={"source": {"videoId": "CCC"}})
        self.doc(4, [], model="")                                                            # 文字起こし前
        self.doc(5, [_seg(1, 0, 600, "学習用", proofed=True)], ev=False, evalReviewed=rv)     # 評価用でない(印があっても数えない)
        st = DR.drill_status()
        c = {x["key"]: x for x in st["conds"]}
        self.assertEqual(st["reviewedSec"], 270)
        self.assertEqual(st["leftSec"], 630)
        self.assertEqual((st["docs"], st["reviewedDocs"], st["pendingDocs"], st["untranscribed"]), (4, 2, 1, 1))
        self.assertEqual(c["speakers"]["have"], 3)                                           # 一般の名前(本人・話者4)は数えない
        self.assertEqual(sorted(c["speakers"]["items"]), sorted(["さくらみこ", "星街すいせい", "兎田ぺこら"]))
        self.assertEqual((c["streams"]["have"], c["overlap"]["have"], c["bgm"]["have"]), (2, 60, 60))   # 確かめていない文書の BGM・配信は数えない
        self.assertEqual(c["calls"]["have"], 3)                                              # 名簿に当たる行(みこち・すいちゃん・ぺこら。聞き取れない行は除く)
        self.assertFalse(st["ready"])
        # 15 分に届いて、条件がそろえば ready
        many = [{"id": "S%d" % i, "name": nm, "color": ""} for i, nm in enumerate(["さくらみこ", "星街すいせい", "兎田ぺこら", "白上フブキ"], 1)]
        for n in range(10, 13):
            self.doc(n, [_seg(i, i * 10, i * 10 + 10, "みこち", proofed=True, speaker="S%d" % (i % 4 + 1), tags=["overlap", "bgm"]) for i in range(4)],
                     speakers=many, clip={"source": {"videoId": "V%d" % n}}, evalReviewed={"at": 1, "rows": 4, "durationSec": 300})
        st = DR.drill_status()
        self.assertEqual(st["leftSec"], 0)
        self.assertTrue(st["ready"], st["conds"])

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


if __name__ == "__main__":
    unittest.main()
