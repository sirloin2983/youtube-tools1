# -*- coding: utf-8 -*-
"""文書を書く唯一の口 human/proof/store.commit のテスト(RS8 O2-0。動きは write_doc と同じ・why をログに残す)。

    py -3.10 -m unittest src/human/proof/tests/test_commit.py -v
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import layers, store  # noqa: E402
from ytt import workdata  # noqa: E402

TID = "0123456789ab"


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="commit-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        os.makedirs(workdata.TX_DIR)

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

    def test_hum_not_yet(self):
        with self.assertRaises(NotImplementedError):
            store.commit(TID, {"id": TID}, why="save", hum={})

    def test_whys_do_not_overlap(self):
        self.assertFalse(store.HUMAN_WHYS & store.MACHINE_WHYS)
        self.assertLessEqual(store.FULL_WHYS | store.DIAR_WHYS, store.MACHINE_WHYS)
        self.assertIn("fill", store.MACHINE_WHYS)   # 行の無い文書へ文字起こしを入れる = 機械(O2-2 で直した)
        self.assertIn("drill", store.HUMAN_WHYS)    # 評価ドリルの「全部聞いた」= 人

    def test_save_transcript_goes_through_commit(self):
        store.commit(TID, {"id": TID, "title": "t", "segments": [], "updatedAt": 1}, why="save")
        with mock.patch.object(store, "commit", wraps=store.commit) as c:
            store.save_transcript(TID, {"id": TID, "title": "t2", "segments": [], "updatedAt": 1})
        self.assertEqual([x.kwargs.get("why") for x in c.call_args_list], ["save"])

    def test_every_doc_write_in_src_uses_commit(self):
        """文書を書く呼び出しは store.commit だけ(write_doc は store.py の中の commit からだけ)"""
        pat = re.compile(r"\bwrite_doc\(")
        bad = []
        for base, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".runtime")]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(base, fn)
                with open(path, encoding="utf-8") as f:
                    for i, ln in enumerate(f, 1):
                        if pat.search(ln) and not ln.lstrip().startswith(("#", "def write_doc")):
                            bad.append((os.path.relpath(path, SRC), i))
        self.assertEqual([b[0] for b in bad], [os.path.join("human", "proof", "store.py")], bad)


def _row(i, a, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": a + 1.0, "text": text, "speaker": "", "flag": ""}, **kw)


def _doc(rows, original=None, speakers=None):
    d = {"schema": "transcribe/v1", "id": TID, "title": "t", "speakers": speakers or [], "segments": rows, "updatedAt": 1}
    if original is not None:
        d["original"] = original
    return d


class ShadowTest(unittest.TestCase):
    """影のモード(RS8 O2-2): commit のたびに人の層 <id>.hum.json・機械の層 <id>.mach.json も書き、組み立てが文書と合うかをログに。正は文書のまま"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shadow-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        os.makedirs(workdata.TX_DIR)
        p = mock.patch.dict(os.environ, {"TRANSCRIBE_LAYERS": ""})
        p.start()
        self.addCleanup(p.stop)

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
        with open(store.tx_path(TID), "rb") as f:   # 文書は今までどおり(書き方も同じ)
            self.assertEqual(f.read(), json.dumps(_doc(rows), ensure_ascii=False, indent=1).encode("utf-8"))
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

    def test_switch_off_writes_no_layers(self):
        with mock.patch.dict(os.environ, {"TRANSCRIBE_LAYERS": "off"}):
            store.commit(TID, _doc([_row(1, 0.0, "あ")]), why="whole")
        self.assertTrue(os.path.isfile(store.tx_path(TID)))
        self.assertIsNone(self.layer(".mach.json"))
        self.assertIsNone(self.layer(".hum.json"))

    def test_shadow_failures_do_not_fail_the_save(self):
        doc = _doc([_row(1, 0.0, "あ")])
        with mock.patch.object(store._layers, "roundtrip", side_effect=RuntimeError("boom")), self.assertLogs("tx", level="WARNING") as cm:
            store.commit(TID, doc, why="whole")
        self.assertTrue(any("作れませんでした" in m for m in cm.output), cm.output)
        self.assertEqual(store.read_transcript(TID)["segments"][0]["text"], "あ")
        self.assertIsNone(self.layer(".hum.json"))
        with mock.patch.object(store._fsio, "write_json", side_effect=OSError("disk")), self.assertLogs("tx", level="WARNING") as cm:
            store.commit(TID, _doc([_row(1, 0.0, "い")]), why="save")
        self.assertTrue(any("書けませんでした" in m for m in cm.output), cm.output)
        self.assertEqual(store.read_transcript(TID)["segments"][0]["text"], "い")   # 文書は書けている

    def test_broken_layer_files_are_rebuilt(self):
        self.commit(_doc([_row(1, 0.0, "あ")]), "whole")
        for sfx in (".mach.json", ".hum.json"):
            with open(os.path.join(workdata.TX_DIR, TID + sfx), "w", encoding="utf-8") as f:
                f.write("{壊れた")
        mach, _hum = self.commit(_doc([_row(1, 0.0, "あ")]), "save")   # 壊れた層は無いのと同じ = 書く前の文書から作り直す
        self.assertEqual(mach["rev"], 1)

    def test_mismatch_is_logged_not_raised(self):
        with mock.patch.object(store._layers, "roundtrip", return_value=({"schema": layers.HUM_SCHEMA, "rows": []}, [("text", "s1")])), \
                self.assertLogs("tx", level="WARNING") as cm:
            store.commit(TID, _doc([_row(1, 0.0, "あ")]), why="whole")
        self.assertTrue(any("合いません" in m and "文字" in m for m in cm.output), cm.output)
        self.assertTrue(os.path.isfile(store.tx_path(TID)))

    def test_rows_without_speaker_or_flag_fields(self):
        """行に話者・印の欄が無い文書(手書きの文書など)も合う(欄が無い = 空)"""
        doc = {"id": TID, "segments": [{"id": "s1", "start": 0, "end": 1, "text": "あ"}]}
        self.commit(doc, "whole")
        self.commit(doc, "save")

    def test_layer_suffixes_go_with_the_doc(self):
        """移動・削除・バックアップの一覧(docloc.DOC_SUFFIXES)に機械の層・人の層が入る"""
        from ytt import docloc, schemas
        self.assertIn(schemas.MACH_SUFFIX, docloc.DOC_SUFFIXES)
        self.assertIn(schemas.HUM_SUFFIX, docloc.DOC_SUFFIXES)


if __name__ == "__main__":
    unittest.main()
