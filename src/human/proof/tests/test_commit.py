# -*- coding: utf-8 -*-
"""文書を書く唯一の口 human/proof/store.commit のテスト(RS8 O2-0。動きは write_doc と同じ・why をログに残す)。

    py -3.12 -m unittest src/human/proof/tests/test_commit.py -v
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import sys
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import layers, store  # noqa: E402
from ytt import workdata  # noqa: E402
from human.tests._workdata import temporary_workdata  # noqa: E402
from ytt import testkit  # noqa: E402

TID = "0123456789ab"


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_workdata(self, "commit-")

    def test_commit_writes_like_write_doc_and_logs_why(self):
        doc = {"id": TID, "segments": [{"id": 1, "start": 0, "end": 1, "text": "あ"}]}
        with self.assertLogs("tx", level="INFO") as cm:
            store.commit(TID, doc, why="save")
        with open(store.tx_path(TID), "rb") as f:
            got = f.read()
        self.assertEqual(got, json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"))
        self.assertTrue(any("why=save" in m and "by=human" in m for m in cm.output), cm.output)

    def test_machine_why_and_unknown_why(self):
        with self.assertLogs("tx", level="INFO") as cm:
            store.commit(TID, {"id": TID, "segments": []}, why="rerun_each")
        self.assertTrue(any("why=rerun_each" in m and "by=machine" in m for m in cm.output), cm.output)
        with self.assertRaises(ValueError):
            store.commit(TID, {"id": TID}, why="nope")

    def test_commit_resets_cut_flags_from_edit(self):
        """行の「カット済」は commit が必ず編集の内容から付け直す(確かめるの時刻のカード check:time のように apply_edit_cuts を呼ばない書き手でも。2a-1)"""
        edit = {"schema": store.EDIT_SCHEMA, "rev": 1, "sources": [{"fps": [30, 1], "duration": 40.0}], "clips": [{"src": 0, "in": 0.0, "out": 10.0}, {"src": 0, "in": 20.0, "out": 30.0}]}
        testkit.write_json(store.edit_path(TID, for_write=True), edit)
        doc = {"id": TID, "segments": [{"id": "a", "start": 8.0, "end": 9.5, "text": "あ", "cutState": "cut"},
                                       {"id": "b", "start": 10.5, "end": 12.0, "text": "い"}]}
        store.commit(TID, doc, why="check:time")
        segs = store.read_transcript(TID)["segments"]
        self.assertEqual([g.get("cutState") for g in segs], [None, "cut"])

    def test_whys_do_not_overlap(self):
        self.assertFalse(store.HUMAN_WHYS & store.MACHINE_WHYS)
        self.assertLessEqual(store.FULL_WHYS | store.DIAR_WHYS, store.MACHINE_WHYS)
        self.assertIn("fill", store.MACHINE_WHYS)   # 行の無い文書へ文字起こしを入れる = 機械(O2-2 で直した)
        self.assertIn("drill", store.HUMAN_WHYS)    # 評価ドリルの「全部聞いた」= 人



def _row(i, a, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": a + 1.0, "text": text, "speaker": "", "flag": ""}, **kw)


def _doc(rows, original=None, speakers=None):
    d = {"schema": "transcribe/v1", "id": TID, "title": "t", "speakers": speakers or [], "segments": rows, "updatedAt": 1}
    if original is not None:
        d["original"] = original
    return d


class LayersTest(unittest.TestCase):
    """commit のたびに人の層 <id>.hum.json・機械の層 <id>.mach.json も書き、組み立てが文書と合う(RS8 O2-2。層が正 = 写しは組み立て済み)"""

    def setUp(self):
        self.tmp = temporary_workdata(self, "layers-")

    def layer(self, sfx):
        path = os.path.join(workdata.TX_DIR, TID + sfx)
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def commit(self, doc, why, **kw):
        with self.assertLogs("tx", level="INFO") as cm:
            store.commit(TID, doc, why=why, **kw)
        self.assertFalse([m for m in cm.output if "WARNING" in m], cm.output)   # 合わない・作れない・書けない が無い
        mach, hum = self.layer(".mach.json"), self.layer(".hum.json")
        self.assertEqual(layers.compare_docs(doc, layers.compose(mach, hum, layers.split_meta(doc)), loose=True), [])
        return mach, hum

    def test_whole_then_human_save(self):
        rows = [_row(1, 0.0, "あ"), _row(2, 2.0, "い", flag="要確認")]
        mach, hum = self.commit(_doc(rows), "whole")
        self.assertEqual((mach["schema"], mach["rev"], [r["text"] for r in mach["rows"]]), (layers.MACH_SCHEMA, 1, ["あ", "い"]))
        self.assertEqual(mach["rows"][1]["flag"], "要確認")
        self.assertEqual((hum["schema"], hum["rows"], hum["dead"]), (layers.HUM_SCHEMA, [], []))
        with open(store.tx_path(TID), "rb") as f:   # 写しは文書と同じ中身 + 組み立てた版 composedFrom
            self.assertEqual(f.read(), json.dumps(dict(_doc(rows), composedFrom={"mach": 1, "hum": 1}), ensure_ascii=False, indent=1).encode("utf-8"))
        before = os.path.getmtime(os.path.join(workdata.TX_DIR, TID + ".mach.json"))
        edited = _doc([_row(1, 0.0, "あー", proofed=True), _row(2, 2.0, "い")])   # 人が直した・印を外した
        mach2, hum2 = self.commit(edited, "save")
        self.assertEqual(mach2, mach)   # 人の操作は機械の層を変えない(書き直しもしない)
        self.assertEqual(os.path.getmtime(os.path.join(workdata.TX_DIR, TID + ".mach.json")), before)
        by = {h["id"]: h for h in hum2["rows"]}
        self.assertEqual(by["s1"]["text"], "あー")
        self.assertTrue(by["s2"].get("flagOff"))
        self.assertEqual(hum2["rev"], 2)

    def test_first_commit_migrates_from_original(self):
        """機械の層が無い文書(O2-2 より前の文書)は、書く前の文書の original から機械の層を作る(移行。文書は書き換えない)"""
        orig = [{"start": 0.0, "end": 1.0, "text": "あ"}, {"start": 2.0, "end": 3.0, "text": "い"}]
        old = _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "い")], orig)
        store.write_doc(TID, old)
        new = _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "いい")], orig)
        mach, hum = self.commit(new, "save")
        self.assertEqual([r["text"] for r in mach["rows"]], ["あ", "い"])   # 書く前の文書の機械の出力
        self.assertEqual([h.get("text") for h in hum["rows"]], ["いい"])

    def test_machine_why_advances_mach_only_where_written(self):
        orig = [{"start": 0.0, "end": 1.0, "text": "あ"}, {"start": 2.0, "end": 3.0, "text": "い"}, {"start": 4.0, "end": 5.0, "text": "う"}]
        store.write_doc(TID, _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "い"), _row(3, 4.0, "う")], orig))
        self.commit(_doc([_row(1, 0.0, "あ直し", proofed=True), _row(2, 2.0, "い"), _row(3, 4.0, "う")], orig), "save")
        # 再認識(each)が s2 を書き換え・redo が s3 を 2 行に
        after = _doc([_row(1, 0.0, "あ直し", proofed=True), _row(2, 2.0, "いい", flag="要確認"),
                      dict(_row(3, 4.0, "う1"), id="s3-r1", end=4.5), dict(_row(3, 4.5, "う2"), id="s3-r2", end=5.0)], orig)
        mach, hum = self.commit(after, "rerun_each")
        self.assertEqual(mach["rev"], 2)
        self.assertEqual([(r["id"], r["text"]) for r in mach["rows"]], [("s1", "あ"), ("s2", "いい"), ("s3-r1", "う1"), ("s3-r2", "う2")])
        self.assertEqual([(h["id"], h.get("text")) for h in hum["rows"]], [("s1", "あ直し")])   # 人の直しは人の層のまま
        mach2, _hum = self.commit(after, "rerun_range")   # 何も書き換えていない機械の操作は機械の層を進めない
        self.assertEqual(mach2["rev"], 2)

    def test_diar_moves_speakers_into_mach(self):
        spk = [{"id": "S1", "name": "話者1", "color": "#f00"}, {"id": "S2", "name": "話者2", "color": "#0f0"}]
        self.commit(_doc([_row(1, 0.0, "あ"), _row(2, 2.0, "い")]), "whole")
        mach, hum = self.commit(_doc([_row(1, 0.0, "あ", speaker="S1"), _row(2, 2.0, "い", speaker="S2")], speakers=spk), "diar")
        self.assertEqual([r.get("speaker") for r in mach["rows"]], ["S1", "S2"])
        self.assertEqual(mach["speakers"], spk)
        self.assertEqual(hum["rows"], [])   # 機械の話者のまま = 人の層に行は無い
        _mach, hum2 = self.commit(_doc([_row(1, 0.0, "あ", speaker="S2"), _row(2, 2.0, "い", speaker="S2")], speakers=spk), "save")
        self.assertEqual([(h["id"], h.get("speaker")) for h in hum2["rows"]], [("s1", "S2")])   # 人が付け替えた話者

    def test_given_mach_keeps_carried_rows_human(self):
        mach_rows = [_row(1, 0.0, "まって")]
        mach, hum = self.commit(_doc([_row(1, 0.0, "待って", proofed=True)]), "whole", mach=layers._ys.make_mach(mach_rows))
        self.assertEqual([r["text"] for r in mach["rows"]], ["まって"])
        self.assertEqual([h.get("text") for h in hum["rows"]], ["待って"])

    def test_broken_layer_files_are_rebuilt(self):
        self.commit(_doc([_row(1, 0.0, "あ")]), "whole")
        for sfx in (".mach.json", ".hum.json"):
            with open(os.path.join(workdata.TX_DIR, TID + sfx), "w", encoding="utf-8") as f:
                f.write("{壊れた")
        mach, _hum = self.commit(_doc([_row(1, 0.0, "あ")]), "save")   # 壊れた層は無いのと同じ = 書く前の文書から作り直す
        self.assertEqual(mach["rev"], 1)

    def test_rows_without_speaker_or_flag_fields(self):
        """行に話者・印の欄が無い文書(手書きの文書など)も合う(欄が無い = 空)"""
        doc = {"id": TID, "segments": [{"id": "s1", "start": 0, "end": 1, "text": "あ"}]}
        self.commit(doc, "whole")
        self.commit(doc, "save")


class PrimaryTest(unittest.TestCase):
    """層が正(RS8 O2-3): 人の層 → 機械の層 → 写し(composedFrom)。開いたときに写しが古ければ組み立て直す"""

    def setUp(self):
        self.tmp = temporary_workdata(self, "primary-")

    def path(self, sfx):
        return os.path.join(workdata.TX_DIR, TID + sfx)

    def load(self, sfx):
        with open(self.path(sfx), encoding="utf-8") as f:
            return json.load(f)

    def put(self, sfx, obj):
        testkit.write_json(self.path(sfx), obj)

    def test_order_and_composed_from(self):
        order = []
        real_json, real_atomic = store._fsio.write_json, store._fsio.atomic_write
        with mock.patch.object(store._fsio, "write_json", side_effect=lambda p, *a, **k: (order.append(os.path.basename(p)), real_json(p, *a, **k))), \
                mock.patch.object(store._fsio, "atomic_write", side_effect=lambda p, *a, **k: (order.append(os.path.basename(p)), real_atomic(p, *a, **k))):
            out = store.commit(TID, _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "い")]), why="whole")
        order = [x for i, x in enumerate(order) if i == 0 or order[i - 1] != x]   # write_json の中の atomic_write を 1 回に
        self.assertEqual(order, [TID + ".hum.json", TID + ".mach.json", TID + ".json"])   # 人の層 → 機械の層 → 写し
        self.assertEqual(out["composedFrom"], {"mach": 1, "hum": 1})
        self.assertEqual(self.load(".json")["composedFrom"], {"mach": 1, "hum": 1})
        d = store.read_transcript(TID)
        d["segments"][0]["text"] = "あー"
        d["segments"][0]["proofed"] = True
        store.commit(TID, d, why="save")
        self.assertEqual(self.load(".json")["composedFrom"], {"mach": 1, "hum": 2})
        self.assertEqual(self.load(".hum.json")["rows"][0]["text"], "あー")

    def test_machine_layer_changed_by_flow_is_composed_on_open(self):
        """② が機械の層だけを書いた(人の層あり)→ ③ が開くと組み立て直す: 人の直しは残して印 MACH_CHANGED・触っていない行は新しい機械・updatedAt が進む"""
        store.commit(TID, _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "い"), _row(3, 4.0, "う")]), why="whole")
        d = store.read_transcript(TID)
        d["segments"][0].update(text="あー", proofed=True)
        store.commit(TID, d, why="save")
        before = self.load(".json")
        mach = self.load(".mach.json")
        mach["rev"] = 2
        mach["rows"][0]["text"] = "ああ"   # 人が直した行の機械が変わった
        mach["rows"][1]["text"] = "いい"   # 触っていない行の機械が変わった
        self.put(".mach.json", mach)
        self.assertEqual(store._load_doc(store.tx_path(TID)), before)   # 写しは ③ が開くまで古いまま
        with self.assertLogs("tx", level="INFO") as cm:
            got = store.read_transcript(TID)
        self.assertTrue(any("組み立て直しました" in m for m in cm.output), cm.output)
        self.assertEqual([g["text"] for g in got["segments"]], ["あー", "いい", "う"])
        self.assertIn(layers.MACH_CHANGED, got["segments"][0]["flag"])
        self.assertGreater(got["updatedAt"], before["updatedAt"])
        self.assertEqual(got["composedFrom"], {"mach": 2, "hum": 2})
        self.assertEqual(self.load(".json"), got)   # 写しも書き直した
        with mock.patch.object(store._layers, "compose", side_effect=AssertionError("組み立て直さない")):
            store.read_transcript(TID)   # もう新しい

    def test_broken_layer_reads_copy(self):
        store.commit(TID, _doc([_row(1, 0.0, "あ")]), why="whole")
        copy = self.load(".json")
        with open(self.path(".hum.json"), "w", encoding="utf-8") as f:
            f.write("{壊れた")
        with self.assertLogs("tx", level="WARNING") as cm:
            self.assertEqual(store.read_transcript(TID), copy)
        self.assertTrue(any("写しのまま" in m for m in cm.output), cm.output)
        os.remove(self.path(".mach.json"))   # 機械の層が無い: 組み立てられない = 写しのまま
        os.remove(self.path(".hum.json"))
        with self.assertLogs("tx", level="WARNING"):
            self.assertEqual(store.read_transcript(TID), copy)

    def test_copy_without_composed_from_is_not_recomposed(self):
        """composedFrom の無い写し(文書が正だったころの文書)は組み立て直さない = 次の commit が写しから層を作る"""
        orig = [{"start": 0.0, "end": 1.0, "text": "あ"}]
        store.write_doc(TID, _doc([_row(1, 0.0, "あ直し")], orig))
        self.put(".mach.json", layers._ys.make_mach([_row(1, 0.0, "ぜんぜん違う")], rev=9))
        self.assertEqual(store.read_transcript(TID)["segments"][0]["text"], "あ直し")
        self.put(".mach.json", {"schema": "x"})   # 形の違う層は無いのと同じ = 写しの original から作る(移行)
        out = store.commit(TID, store.read_transcript(TID), why="save")
        self.assertEqual(out["composedFrom"], {"mach": 1, "hum": 1})
        self.assertEqual([r["text"] for r in self.load(".mach.json")["rows"]], ["あ"])
        self.assertEqual([h.get("text") for h in self.load(".hum.json")["rows"]], ["あ直し"])

    def test_layer_write_failure_drops_composed_from(self):
        store.commit(TID, _doc([_row(1, 0.0, "あ")]), why="whole")
        with mock.patch.object(store, "_write_layers", side_effect=OSError("disk")), self.assertLogs("tx", level="WARNING"):
            out = store.commit(TID, _doc([_row(1, 0.0, "い")]), why="save")
        self.assertNotIn("composedFrom", out)
        self.assertEqual(store.read_transcript(TID)["segments"][0]["text"], "い")
        with mock.patch.object(store._layers, "roundtrip", side_effect=RuntimeError("boom")), self.assertLogs("tx", level="WARNING"):
            out = store.commit(TID, _doc([_row(1, 0.0, "う")]), why="save")
        self.assertNotIn("composedFrom", out)
        self.assertEqual(store.read_transcript(TID)["segments"][0]["text"], "う")

    def test_mismatch_writes_the_saved_doc(self):
        with mock.patch.object(store._layers, "roundtrip", return_value=({"schema": layers.HUM_SCHEMA, "rev": 5, "rows": []}, [("text", "s1")])), \
                self.assertLogs("tx", level="WARNING") as cm:
            out = store.commit(TID, _doc([_row(1, 0.0, "あ")]), why="whole")
        self.assertTrue(any("合いません" in m for m in cm.output), cm.output)
        self.assertEqual(out["segments"][0]["text"], "あ")
        self.assertEqual(out["composedFrom"], {"mach": 1, "hum": 5})

    def test_given_hum_composes_the_copy(self):
        store.commit(TID, _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "い")]), why="whole")
        mach = self.load(".mach.json")
        hum = layers.diff(mach, _doc([_row(1, 0.0, "あ"), _row(2, 2.0, "いい")]))
        out = store.commit(TID, _doc([]), why="save", hum=hum)   # 文書の行は使わない(欄だけ)
        self.assertEqual([g["text"] for g in out["segments"]], ["あ", "いい"])
        self.assertEqual(out["composedFrom"], {"mach": 1, "hum": 2})
        self.assertEqual(store.read_transcript(TID)["segments"][1]["text"], "いい")

    def test_new_doc_in_folder_copy_then_layers(self):
        wd = os.path.join(self.tmp, "out", "題名", "作業用")
        os.makedirs(os.path.dirname(wd))
        out = store.commit(TID, _doc([_row(1, 0.0, "あ")]), why="whole", folder=wd)
        self.assertEqual(out["composedFrom"], {"mach": 1, "hum": 1})
        for sfx in (".json", ".hum.json", ".mach.json"):
            self.assertTrue(os.path.isfile(os.path.join(wd, TID + sfx)), sfx)
        self.assertEqual(store.read_transcript(TID)["segments"][0]["text"], "あ")

    def test_read_repair_does_not_undo_a_save_in_progress(self):
        """P-PRIMARY(parts-review の H1): 保存が層を書いてから写しを書くまでの間に別のスレッドが古い写しを開いても、
        古い写しの original・recognition で組み立て直した物が保存のあとに書かれない(新しい認識の原文と履歴が古い値に戻らない)"""
        import threading
        store.commit(TID, _doc([_row(1, 0.0, "あ")], original=[{"start": 0.0, "end": 1.0, "text": "old machine"}]), why="whole")
        new = _doc([_row(1, 0.0, "新")], original=[{"start": 0.0, "end": 1.0, "text": "new machine"}])
        new["recognition"] = {"runs": [{"kind": "whole", "note": "new"}]}
        layers_written, go, got = threading.Event(), threading.Event(), {}
        real = store.write_doc

        def slow_write(tid, doc, folder=None):
            if not layers_written.is_set():   # 保存の写しの書き込みの直前(層はもう書いた)で止める
                layers_written.set()
                go.wait(10)
            return real(tid, doc, folder)

        def saver():
            with store.saving():
                store.commit(TID, new, why="whole")

        def reader():
            got["doc"] = store.read_transcript(TID)

        with mock.patch.object(store, "write_doc", side_effect=slow_write):
            ts = threading.Thread(target=saver)
            ts.start()
            self.assertTrue(layers_written.wait(10))
            tr = threading.Thread(target=reader)
            tr.start()
            tr.join(0.5)   # 読み手は古い写しを見て、組み立て直しの錠で待つ
            go.set()
            ts.join(10)
            tr.join(10)
        disk = self.load(".json")
        self.assertEqual(disk["original"][0]["text"], "new machine")
        self.assertEqual(disk["recognition"]["runs"][0]["note"], "new")
        self.assertEqual(got["doc"]["original"][0]["text"], "new machine")
        self.assertEqual(disk["segments"][0]["text"], "新")


if __name__ == "__main__":
    unittest.main()
