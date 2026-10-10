# -*- coding: utf-8 -*-
"""human/proof/overrides(校正の上書きの第 1 版 O1。役割で組み直す RS6 b-O1)のテスト。

    py -3.10 -m unittest src/human/proof/tests/test_overrides.py -v

人の行の取り出し(extract)・新しい機械の行への重ね方(apply = 時刻の重なり・印 STALE_FLAG・行の順)・控え <id>.over.json(write・read・current)・
切り抜きの書き出しの鍵の hash(clip_key_of)・保存(store.save_transcript)で控えが書かれること。編集の serve は読まない。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import shutil
import sys
import tempfile
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests -> proof -> human -> src
EDITOR = os.path.join(SRC, "editor")
for _p in (EDITOR, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import overrides as O, store  # noqa: E402
from ytt import schemas as Y, workdata  # noqa: E402

TID = "0123456789ab"


def row(sid, a, b, text, **kw):
    return dict({"id": sid, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def orig(a, b, text):
    return {"start": a, "end": b, "text": text}


class TestMatch(unittest.TestCase):
    def test_center_or_half(self):
        self.assertTrue(O.match((0.0, 2.0), (0.5, 1.5)))      # 中心が入る
        self.assertTrue(O.match((0.0, 1.0), (0.4, 3.0)))      # 0.6 秒の重なり = 短い方(1 秒)の 60%
        self.assertFalse(O.match((0.0, 1.0), (0.8, 3.0)))     # 0.2 秒 = 20%・中心も入らない
        self.assertFalse(O.match((0.0, 1.0), (1.0, 2.0)))     # 接しているだけ


class TestExtract(unittest.TestCase):
    def doc(self):
        return {"speakers": [{"id": "A", "name": "ぺこら", "color": "#123456"}, {"id": "B", "name": "使わない", "color": ""}],
                "original": [orig(0.0, 2.0, "こんばんは"), orig(2.5, 4.0, "まって"), orig(4.5, 6.0, "あのー"), orig(6.5, 8.0, "それって"),
                             orig(8.5, 9.5, "ういっす"), orig(10.0, 11.0, "おわり")],
                "segments": [row("s1", 0.0, 2.0, "こんばんは"),                                     # 触っていない
                             row("s2", 2.5, 4.0, "待って"),                                         # 文字だけ直した
                             row("s3", 4.5, 6.0, "あのー", proofed=True, proofedAt=1700),           # 校正済み(文字は同じ)
                             row("s4", 6.5, 8.0, "それって", speaker="A"),                          # 話者だけ
                             row("s5", 8.5, 9.5, "ういっす。", fill={"from": "うい", "by": "sv"}),  # 後処理が埋めた行(機械)
                             row("s6", 10.0, 11.0, "", draft="overlap"),                            # 空の下書き
                             row("s7", 12.0, 13.0, "足した行")]}                                    # 機械に無い所へ人が足した

    def test_rows(self):
        over = O.extract(self.doc())
        rows = over["rows"]
        self.assertEqual([(r["start"], r.get("text")) for r in rows], [(2.5, "待って"), (4.5, "あのー"), (6.5, None), (12.0, "足した行")])
        self.assertEqual(rows[1]["proofed"], True)
        self.assertEqual(rows[1]["proofedAt"], 1700)
        self.assertNotIn("proofed", rows[0])
        self.assertEqual(rows[2]["speaker"], "A")
        self.assertNotIn("text", rows[2])                       # 話者だけの行は文字を持たない(機械の文字を古い文字で戻さない)
        self.assertEqual([s["id"] for s in over["speakers"]], ["A"])   # 行が使う話者だけ

    def test_nosub_tags_and_no_original(self):
        d = {"segments": [row("s1", 0.0, 1.0, "x", noSub=True), row("s2", 1.0, 2.0, "y", tags=["bgm", "知らない"]),
                          row("s3", 2.0, 3.0, "z")]}
        rows = O.extract(d)["rows"]
        self.assertEqual(rows, [{"start": 0.0, "end": 1.0, "noSub": True}, {"start": 1.0, "end": 2.0, "tags": ["bgm"]}])   # original の無い古い文書 = 校正済みだけが文字の行


class TestApply(unittest.TestCase):
    def test_human_rows_win_and_untouched_rows_are_new(self):
        machine = [row("s1", 0.0, 2.0, "こんばんわ"), row("s2", 2.5, 4.0, "まってね", flag="要確認"), row("s3", 4.5, 6.0, "新しいあのー")]
        over = {"rows": [{"start": 2.4, "end": 3.9, "text": "待って", "proofed": True, "proofedAt": 5}]}
        rows, st = O.apply(machine, over)
        self.assertEqual([g["text"] for g in rows], ["こんばんわ", "待って", "新しいあのー"])   # 人が触っていない行だけ新しい
        h = rows[1]
        self.assertEqual((h["id"], h["start"], h["end"], h["proofed"], h["proofedAt"], h["flag"]), ("o1", 2.4, 3.9, True, 5, ""))
        self.assertEqual(st, {"matched": 1, "stale": 0, "dropped": 0, "total": 1, "replaced": 1, "outside": 0})
        self.assertEqual(machine[1]["text"], "まってね")   # 渡した行は書き換えない

    def test_unproofed_human_row_keeps_machine_flag(self):
        rows, _st = O.apply([row("s1", 0.0, 2.0, "あ", flag="要確認")], {"rows": [{"start": 0.0, "end": 2.0, "text": "い"}]})
        self.assertEqual((rows[0]["text"], rows[0]["flag"]), ("い", "要確認"))
        self.assertNotIn("proofed", rows[0])

    def test_stale_row_is_kept_in_time_order(self):
        machine = [row("s1", 0.0, 2.0, "あ"), row("s2", 5.0, 6.0, "う")]
        over = {"rows": [{"start": 3.0, "end": 4.0, "text": "人が足した", "proofed": True}]}
        rows, st = O.apply(machine, over)
        self.assertEqual([g["text"] for g in rows], ["あ", "人が足した", "う"])
        self.assertIn(O.STALE_FLAG, rows[1]["flag"])
        self.assertEqual((st["matched"], st["stale"]), (0, 1))

    def test_small_human_row_does_not_drop_long_machine_row(self):
        machine = [row("s1", 0.0, 10.0, "いろいろ話してそれでその間にうわーって言ってまた続ける")]
        over = {"rows": [{"start": 4.5, "end": 5.0, "text": "うわー", "proofed": True}]}
        rows, st = O.apply(machine, over)
        self.assertEqual([g["id"] for g in rows], ["s1", "o1"])   # 長い機械の行のほかの言葉は消さない(人の行は対応づいた扱い)
        self.assertEqual((st["matched"], st["stale"], st["replaced"]), (1, 0, 0))

    def test_shifted_time_with_same_words_is_matched(self):
        """人が時刻を大きく直した行: 時刻の決まりに当たらなくても、重なっていて機械の文字が人の文字に現れれば置き換える"""
        machine = [row("s1", 24.38, 29.29, "大凶だけか")]
        over = {"rows": [{"start": 28.41, "end": 31.28, "text": "大凶だけか赤が増えるのは", "proofed": True}]}
        rows, st = O.apply(machine, over)
        self.assertEqual([g["text"] for g in rows], ["大凶だけか赤が増えるのは"])
        self.assertEqual((st["matched"], st["replaced"]), (1, 1))

    def test_split_rows_replace_one_machine_row(self):
        machine = [row("s1", 0.0, 4.0, "まえのぶんうしろのぶん"), row("s2", 4.5, 5.0, "つぎ")]
        over = {"rows": [{"start": 0.0, "end": 2.0, "text": "前の文", "proofed": True}, {"start": 2.0, "end": 4.0, "text": "後ろの文", "proofed": True}]}
        rows, st = O.apply(machine, over)
        self.assertEqual([g["text"] for g in rows], ["前の文", "後ろの文", "つぎ"])
        self.assertEqual((st["matched"], st["replaced"]), (2, 1))

    def test_attribute_rows_keep_machine_text(self):
        machine = [row("s1", 0.0, 2.0, "新しい文字"), row("s2", 3.0, 4.0, "べつ")]
        over = {"rows": [{"start": 0.1, "end": 1.9, "speaker": "A", "noSub": True, "tags": ["bgm"]}, {"start": 8.0, "end": 9.0, "speaker": "B"}]}
        rows, st = O.apply(machine, over)
        self.assertEqual((rows[0]["text"], rows[0]["speaker"], rows[0]["noSub"], rows[0]["tags"]), ("新しい文字", "A", True, ["bgm"]))
        self.assertEqual(rows[1]["speaker"], "")
        self.assertEqual((st["matched"], st["dropped"], st["stale"]), (1, 1, 0))   # 対応づかない話者だけの行は捨てる(行は増やさない)
        self.assertEqual(len(rows), 2)

    def test_span_and_ids(self):
        machine = [row("o1", 0.0, 1.0, "あ"), row("s2", 5.0, 6.0, "い")]
        over = {"rows": [{"start": 20.0, "end": 21.0, "text": "範囲の外", "proofed": True}, {"start": 3.0, "end": 4.0, "text": "中", "proofed": True}]}
        rows, st = O.apply(machine, over, (0.0, 10.0))
        self.assertEqual([g["id"] for g in rows], ["o1", "o2", "s2"])   # 機械の行の id と重ならない
        self.assertEqual((st["total"], st["outside"]), (1, 1))

    def test_merge_speakers(self):
        over = {"speakers": [{"id": "A", "name": "ぺこら", "color": "#1"}, {"id": "B", "name": "b", "color": ""}]}
        sps = O.merge_speakers([{"id": "B", "name": "新しいB", "color": ""}], over, [{"speaker": "A"}, {"speaker": "B"}])
        self.assertEqual([(s["id"], s["name"]) for s in sps], [("B", "新しいB"), ("A", "ぺこら")])


class TempTx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ytt-over-")
        self.saved = (workdata.TX_DIR, workdata.SETTINGS)
        workdata.TX_DIR = os.path.join(self.tmp, "transcripts")
        workdata.SETTINGS = os.path.join(self.tmp, "settings.json")   # 無いファイル = 既定の設定(評価用のフォルダなし)
        os.makedirs(workdata.TX_DIR)
        store._summary_cache.clear()

    def tearDown(self):
        workdata.TX_DIR, workdata.SETTINGS = self.saved
        store._summary_cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestFile(TempTx):
    def test_write_read_current(self):
        over = {"rows": [{"start": 0.0, "end": 1.0, "text": "x", "proofed": True}], "speakers": []}
        body = O.write(TID, over, "ab" * 32, at=1000)
        self.assertEqual((body["schema"], body["clipKey"], body["at"]), (O.OVER_SCHEMA, "ab" * 32, 1000))
        self.assertEqual(O.read(TID)["rows"], over["rows"])
        self.assertTrue(os.path.isfile(O.over_path(TID)))
        doc = {"updatedAt": 1000, "segments": [row("s1", 0.0, 1.0, "y", proofed=True)], "original": []}
        self.assertEqual(O.current(TID, doc)["rows"][0]["text"], "x")            # 控えが同じ版 = 控え
        self.assertEqual(O.current(TID, dict(doc, updatedAt=2000))["rows"][0]["text"], "y")   # 文書のほうが新しい = 文書から
        self.assertIsNone(O.read("bad"))
        with self.assertRaises(ValueError):
            O.write("../x", over)

    def test_clip_key_of(self):
        video = os.path.join(self.tmp, "clip_0001.mp4")
        open(video, "wb").close()
        self.assertIsNone(O.clip_key_of(video))
        key = Y.make_key("export", {"src": "x", "a": 1})
        kp = Y.key_path(video, "export")
        os.makedirs(os.path.dirname(kp), exist_ok=True)
        with open(kp, "w", encoding="utf-8") as f:
            json.dump(key, f)
        self.assertEqual(O.clip_key_of(video), key["hash"])
        with open(kp, "w", encoding="utf-8") as f:
            json.dump(dict(key, hash="0" * 64), f)   # 書き換えられた鍵は使わない
        self.assertIsNone(O.clip_key_of(video))

    def test_save_transcript_writes_over(self):
        doc = {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": os.path.join(self.tmp, "v.mp4"), "speakers": [],
               "segments": [row("s1", 0.0, 1.0, "あ"), row("s2", 1.0, 2.0, "い")], "original": [orig(0.0, 1.0, "あ"), orig(1.0, 2.0, "い")],
               "updatedAt": 1}
        store.write_doc(TID, doc)
        saved = store.save_transcript(TID, {"segments": [row("s1", 0.0, 1.0, "あ"), row("s2", 1.0, 2.0, "胃", proofed=True)], "speakers": []})
        over = O.read(TID)
        self.assertEqual([(r["start"], r["text"]) for r in over["rows"]], [(1.0, "胃")])
        self.assertEqual(over["at"], saved["updatedAt"])
        self.assertIsNone(over["clipKey"])


if __name__ == "__main__":
    unittest.main()
