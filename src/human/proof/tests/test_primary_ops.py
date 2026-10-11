# -*- coding: utf-8 -*-
"""層が正(TRANSCRIBE_LAYERS=primary)のときの機械の操作(RS8 O2-5)のテスト。

    py -3.10 -m unittest src/human/proof/tests/test_primary_ops.py -v

- (r8s) 再認識 each: 校正済みの行は機械で置き換えない(機械の層だけ更新・人の行に印 MACH_CHANGED)・校正していない行は今と同じく置き換わる
- (r8r) 話者の判別: 人の層が話者の表を持ち(付け直さない)、判別し直したら機械の S… → 人の話者を重なり時間で当てる。当たらない話者だけ新しい H… と弱い印
- shadow・off では今の動きのまま
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データ(AppData など)に触らない
import shutil
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
for _p in (os.path.join(SRC, "editor"), SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from human.proof import layers as L, rerun, speakers, store  # noqa: E402
from ytt import schemas as YS, txbase, workdata  # noqa: E402

TID = "0123456789ab"
SPEC = {"tid": TID, "model": "m", "autoDict": False}


def row(i, a, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": a + 1.5, "text": text, "speaker": "", "flag": ""}, **kw)


def doc(rows, speakers=None):
    return {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "", "speakers": speakers or [], "segments": rows,
            "original": [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in rows], "updatedAt": 1}


class LayerFunctionsTest(unittest.TestCase):
    def test_put_mach_rows(self):
        m = YS.make_mach([row(1, 0.0, "あ", speaker="S1"), row(2, 2.0, "い", speaker="S2"), row(3, 4.0, "う")], rev=3)
        m2 = L.put_mach_rows(m, [row(2, 2.0, "いい", flag="要確認"), dict(row(9, 8.0, "新"), id="s1")])
        self.assertEqual(m2["rev"], 4)
        self.assertEqual([(r["id"], r["text"], r.get("speaker")) for r in m2["rows"]],
                         [("s1", "あ", "S1"), ("s2", "いい", "S2"), ("s3", "う", None), ("s1x", "新", None)])   # 話者は捨てた行から・id の重なりは x
        self.assertEqual(m["rev"], 3)   # 元は書き換えない

    def test_mach_moved(self):
        m = YS.make_mach([row(1, 0.0, "あ")])
        d = L.compose(m, None, {})
        d["segments"][0].update(text="あー", proofed=True)
        hum = L.diff(m, d)
        self.assertTrue(L.mach_moved(hum, "s1", "ああ", "あー"))
        self.assertFalse(L.mach_moved(hum, "s1", "あ", "あー"))   # 機械は前と同じ
        self.assertFalse(L.mach_moved(hum, "s1", "あー", "あー"))   # 機械が人に合った

    def test_assign_other_speaker_is_itself(self):
        m = YS.make_mach([row(1, 0.0, "あ", speaker="S1"), row(2, 2.0, "い", speaker=YS.OTHER_SPK_ID)])
        m["keys"] = {"diar": "k2"}
        hum = {"schema": L.HUM_SCHEMA, "rev": 1, "rows": [], "speakers": [{"id": "S1", "name": "ぺこら", "color": ""}], "spkMap": {}}
        out = L.assign_speakers(m, hum, [row(1, 0.0, "あ", speaker="S1")])
        self.assertEqual(out["spkMap"]["k2"], {"S1": "S1", YS.OTHER_SPK_ID: YS.OTHER_SPK_ID})
        self.assertNotIn("spkFresh", out)
        self.assertEqual(out["speakers"][-1]["id"], YS.OTHER_SPK_ID)


class _Env(unittest.TestCase):
    MODE = "primary"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="primary-ops-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {n: getattr(workdata, n) for n in ("DATA_DIR", "TX_DIR", "TMP_DIR", "EVAL_BASE", "SETTINGS", "FEEDBACK")}
        self.addCleanup(lambda: [setattr(workdata, n, v) for n, v in saved.items()])
        workdata.set_data_dir(os.path.join(self.tmp, "data"))
        os.makedirs(workdata.TX_DIR)
        p = mock.patch.dict(os.environ, {"TRANSCRIBE_LAYERS": self.MODE})
        p.start()
        self.addCleanup(p.stop)
        from pipeline.transcribe import roster   # 再認識の記録が名簿の版を読む(無いファイル)
        p = mock.patch.object(roster, "ROSTER", os.path.join(self.tmp, "no-roster.json"))
        p.start()
        self.addCleanup(p.stop)

    def load(self, sfx):
        with open(os.path.join(workdata.TX_DIR, TID + sfx), encoding="utf-8") as f:
            return json.load(f)

    def start(self, rows, speakers=None):
        store.commit(TID, doc(rows, speakers), why="whole")
        d = store.read_transcript(TID)
        return d

    def save(self, d):
        return store.save_transcript(TID, dict(d, baseUpdatedAt=d["updatedAt"]))


class RerunEachPrimaryTest(_Env):
    def test_proofed_row_keeps_human_text_with_flag(self):
        d = self.start([row(1, 0.0, "あ"), row(2, 2.0, "い"), row(3, 4.0, "う")])
        d["segments"][1].update(text="いー", proofed=True)
        d["segments"][2]["text"] = "うー"   # 直したが校正済みにしていない
        d = self.save(d)
        done, _u = rerun.apply_retranscribe(SPEC, {"s1": ("ああ", ""), "s2": ("いい", ""), "s3": ("うう", "")})
        self.assertEqual(done, 3)
        got = store.read_transcript(TID)
        by = {g["id"]: g for g in got["segments"]}
        self.assertEqual((by["s1"]["text"], by["s3"]["text"]), ("ああ", "うう"))   # 校正していない行は置き換わる
        self.assertEqual((by["s2"]["text"], by["s2"].get("proofed")), ("いー", True))   # 校正済みは人の直しのまま
        self.assertIn(L.MACH_CHANGED, by["s2"]["flag"])
        self.assertEqual(got["retranscribed"]["keptProofed"], 1)
        mach = self.load(".mach.json")
        self.assertEqual([r["text"] for r in mach["rows"]], ["ああ", "いい", "うう"])   # 機械の層は全部新しい
        from human.proof import machpick
        x = machpick.changes(TID)["rows"]
        self.assertEqual(([r["id"] for r in x], [b["text"] for b in x[0]["before"]], [n["text"] for n in x[0]["now"]]), (["s2"], ["い"], ["いい"]))
        machpick.pick({"id": TID, "row": "s2", "pick": "machine"})
        self.assertEqual([g["text"] for g in store.read_transcript(TID)["segments"]], ["ああ", "いい", "うう"])

    def test_same_machine_text_no_flag(self):
        d = self.start([row(1, 0.0, "あ")])
        d["segments"][0].update(text="あー", proofed=True)
        self.save(d)
        rerun.apply_retranscribe(SPEC, {"s1": ("あ", "")})   # 機械は前と同じ
        g = store.read_transcript(TID)["segments"][0]
        self.assertEqual((g["text"], g["flag"]), ("あー", ""))


class RerunEachShadowTest(_Env):
    MODE = "shadow"

    def test_shadow_replaces_proofed_like_before(self):
        d = self.start([row(1, 0.0, "あ")])
        d["segments"][0].update(text="あー", proofed=True)
        self.save(d)
        rerun.apply_retranscribe(SPEC, {"s1": ("ああ", "")})
        g = store.read_transcript(TID)["segments"][0]
        self.assertEqual((g["text"], g.get("proofed")), ("ああ", None))   # 今と同じ: 機械で置き換えて校正済みを外す
        self.assertNotIn("keptProofed", store.read_transcript(TID)["retranscribed"])


TURNS2 = [(0.0, 1.6, 0), (2.0, 3.6, 1), (4.0, 5.6, 0)]


class DiarPrimaryTest(_Env):
    def diar(self, turns):
        with mock.patch.object(speakers._diar, "record_run"):
            return speakers.apply_diarization(TID, turns, 0.0, 0, emb="e")

    def test_first_then_rediar_keeps_human_table(self):
        self.start([row(1, 0.0, "あ"), row(2, 2.0, "い"), row(3, 4.0, "う")])
        self.diar(TURNS2)   # 初めての判別 = 今と同じ(文書の話者 = 機械の話者)
        d = store.read_transcript(TID)
        self.assertEqual([g["speaker"] for g in d["segments"]], ["S1", "S2", "S1"])
        d["speakers"][0]["name"] = "ぺこら"   # 人が名前を付けた
        d["segments"][1]["speaker"] = "S1"   # 人が「い」の話者を直した
        self.save(d)
        # 判別し直し: 機械は話した長さの順で振り直す(S1 と S2 が入れ替わる)・知らない声の行が増えるのは無し
        self.diar([(0.0, 1.6, 1), (2.0, 3.6, 0), (4.0, 5.6, 1)])
        got = store.read_transcript(TID)
        self.assertEqual(got["speakers"][0], {"id": "S1", "name": "ぺこら", "color": d["speakers"][0]["color"]})   # 表は人の物(付け直さない)
        self.assertEqual([g["speaker"] for g in got["segments"]], ["S1", "S1", "S1"])   # 対応表で当たる・人が直した行は人の値
        hum = self.load(".hum.json")
        key = self.load(".mach.json")["keys"]["diar"]
        self.assertTrue(key.startswith("diar-"))
        self.assertIn(key, hum["spkMap"])
        self.assertFalse(any(L.SPK_CHANGED in g["flag"] for g in got["segments"][::2]))

    def test_new_voice_gets_h_and_weak_flag(self):
        self.start([row(1, 0.0, "あ"), row(2, 2.0, "い"), row(3, 4.0, "う"), row(4, 6.0, "え")])
        self.diar([(0.0, 1.6, 0), (2.0, 3.6, 0), (4.0, 5.6, 0), (6.0, 7.6, 0)])
        d = store.read_transcript(TID)
        d["segments"][3]["speaker"] = ""   # 4 行目は人が話者を外した(どの人にも当たらない)
        self.save(d)
        self.diar([(0.0, 1.6, 0), (2.0, 3.6, 0), (4.0, 5.6, 0), (6.0, 7.6, 1)])   # 4 行目に知らない声
        got = store.read_transcript(TID)
        last = got["segments"][3]
        self.assertEqual(last["speaker"], "")   # 人が決めた(外した)話者のまま
        self.assertIn(L.SPK_CHANGED, last["flag"])   # 機械は知らない声 = 弱い印
        self.assertEqual([s["id"] for s in got["speakers"]], ["S1", "H1"])   # 当たらない話者だけ新しい H
        self.assertEqual(self.load(".hum.json")["spkFresh"], ["H1"])
        self.assertEqual([g["speaker"] for g in got["segments"][:3]], ["S1"] * 3)


class DiarLegacyTest(_Env):
    def test_speakers_before_layers_follow_the_new_diar(self):
        """層より前の文書(機械の層に話者が無い)の話者は、人が決めたか分からないので判別し直しに従う(今と同じ)。表の名前は人の物のまま"""
        spk = [{"id": "S1", "name": "ぺこら", "color": "#111"}, {"id": "S2", "name": "みこ", "color": "#222"}]
        store.write_doc(TID, doc([row(1, 0.0, "あ", speaker="S1"), row(2, 2.0, "い", speaker="S2"), row(3, 4.0, "う", speaker="S1")], spk))
        with mock.patch.object(speakers._diar, "record_run"):
            speakers.apply_diarization(TID, [(0.0, 1.6, 0), (2.0, 3.6, 0), (4.0, 5.6, 1)], 0.0, 0, emb="e")
        got = store.read_transcript(TID)
        self.assertEqual([s["name"] for s in got["speakers"]], ["ぺこら", "みこ"])
        self.assertEqual(got["segments"][1]["speaker"], "S1")   # 機械は「い」を「あ」と同じ人と言う
        self.assertEqual(self.load(".hum.json")["rows"], [])   # 人の直しとして残る行は無い

    def test_after_rediar_keeps_protected_and_human_rows(self):
        m = YS.make_mach([row(1, 0.0, "あ", speaker="S1", flag=txbase.WEAK_FLAG), row(2, 2.0, "い", speaker="S1")])
        hum = {"schema": L.HUM_SCHEMA, "rows": [
            {"id": "s1", "start": 0.0, "end": 1.5, "speaker": "S2", "flag": "", "covers": ["s1"], "base": {"rows": [{"id": "s1", "speaker": "S1"}]}},   # 人が決めた
            {"id": "s2", "start": 2.0, "end": 3.5, "speaker": "S2", "noSub": True, "covers": ["s2"], "base": {"rows": [{"id": "s2"}]}}]}   # 守る行
        out = L.after_rediar(m, hum, {"s2"}, txbase.SPK_FLAGS)
        self.assertEqual([h.get("speaker") for h in out["rows"]], ["S2", "S2"])
        self.assertNotIn("flag", out["rows"][0])   # 話者の印を除けば機械と同じ印 = 機械のまま
        self.assertEqual(hum["rows"][0]["flag"], "")   # 元は書き換えない


class DiarShadowTest(_Env):
    MODE = "shadow"

    def test_shadow_renumbers_like_before(self):
        self.start([row(1, 0.0, "あ"), row(2, 2.0, "い"), row(3, 4.0, "う")])
        with mock.patch.object(speakers._diar, "record_run"):
            speakers.apply_diarization(TID, TURNS2, 0.0, 0, emb="e")
            d = store.read_transcript(TID)
            d["speakers"][0]["name"] = "ぺこら"
            self.save(d)
            speakers.apply_diarization(TID, [(0.0, 1.6, 1), (2.0, 3.6, 0), (4.0, 5.6, 1)], 0.0, 0, emb="e")
        got = store.read_transcript(TID)
        self.assertEqual(got["speakers"][0]["name"], "話者1")   # 今と同じ: 判別が表を作り直す


if __name__ == "__main__":
    unittest.main()
