# -*- coding: utf-8 -*-
"""文書を「機械の層 + 人の層」から組み立てる関数(human/proof/layers。RS8 O2-1)のテスト。

    py -3.10 -m unittest src/human/proof/tests/test_layers.py -v

純粋な関数だけ(ファイル・サーバーは使わない)。人の操作ごとに 往復 compose(mach, diff(mach, doc)) == doc と、
機械を作り直したとき(行 id が変わる・文字が変わる)に人の直しが残るか・印 MACH_CHANGED / SPK_CHANGED を確かめる。
"""
import copy
import os
import sys
import unittest

SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from human.proof import layers as L  # noqa: E402

META = {"schema": "youtube-tools-transcript/v1", "id": "0123456789ab", "title": "題", "sourcePath": "C:/v/a.mp4", "start": 0, "end": None,
        "original": [{"start": 0, "end": 1, "text": "x"}], "updatedAt": 1}


def mrow(i, a, b, text, flag="", **kw):
    r = {"id": "s%d" % i, "start": a, "end": b, "text": text, "flag": flag}
    r.update(kw)
    return r


def machine(rows, rev=1, diar=None, speakers=None):
    return {"schema": L.MACH_SCHEMA, "rev": rev, "keys": {"diar": diar} if diar else {}, "rows": rows, "speakers": speakers or []}


def rebuild(mach, texts=None, rev=None, drop=(), extra=()):
    """機械を作り直した(行 id を n1, n2… に付け替え・rev を上げる)。texts = {行の番号: 新しい文字}"""
    m = copy.deepcopy(mach)
    m["rev"] = rev or (mach["rev"] + 1)
    rows = []
    for i, r in enumerate(m["rows"]):
        if i in drop:
            continue
        r["id"] = "n%d" % (i + 1)
        if texts and i in texts:
            r["text"] = texts[i]
        rows.append(r)
    m["rows"] = sorted(rows + list(extra), key=lambda r: (r["start"], r["end"]))
    return m


M0 = machine([mrow(1, 0.0, 2.0, "こんにちは"), mrow(2, 2.0, 4.0, "今日はいい天気", "要確認"), mrow(3, 4.0, 6.0, "ですね"),
              mrow(4, 6.0, 9.0, "ではまた", fill={"from": "では", "by": "sense-voice"}), mrow(5, 9.0, 12.0, "さようなら")])


def base_doc(mach=M0):
    return L.compose(mach, None, META)


def seg(d, sid):
    return next(g for g in d["segments"] if g["id"] == sid)


def texts(d):
    return [g["text"] for g in d["segments"]]


class RoundTripTest(unittest.TestCase):
    def assertRoundTrip(self, mach, doc, prev=None):
        hum, reasons = L.roundtrip(mach, doc, prev)
        self.assertEqual(reasons, [], reasons)
        self.assertEqual(L.compose(mach, hum, L.split_meta(doc)), doc)
        return hum

    def test_machine_only(self):
        d = base_doc()
        self.assertEqual([g["id"] for g in d["segments"]], ["s1", "s2", "s3", "s4", "s5"])
        self.assertEqual(list(seg(d, "s4")), ["id", "start", "end", "text", "speaker", "flag", "fill"])   # 欄の並びは sanitize と同じ
        hum = self.assertRoundTrip(M0, d)
        self.assertEqual(hum["rows"], [])
        self.assertEqual(hum["dead"], [])
        self.assertEqual(hum["docFields"], {"title": "題", "sourcePath": "C:/v/a.mp4"})

    def test_edit_text_and_proofed(self):
        d = base_doc()
        seg(d, "s2").update(text="今日はいい天気だ", flag="")
        seg(d, "s3").update(proofed=True, proofedAt=123, flag="")
        hum = self.assertRoundTrip(M0, d)
        rows = {h["id"]: h for h in hum["rows"]}
        self.assertEqual(rows["s2"]["text"], "今日はいい天気だ")
        self.assertTrue(rows["s2"]["flagOff"])
        self.assertEqual(rows["s2"]["covers"], ["s2"])
        self.assertEqual(rows["s2"]["base"]["rows"][0]["text"], "今日はいい天気")
        self.assertEqual(rows["s3"]["text"], "ですね")   # 校正済みの行は文字の行(機械が変わっても人が確かめた文字のまま)
        self.assertNotIn("flag", rows["s3"])   # 校正済みの既定の印は空

    def test_delete_is_dead_mark(self):
        d = base_doc()
        d["segments"] = [g for g in d["segments"] if g["id"] != "s3"]
        hum = self.assertRoundTrip(M0, d)
        self.assertEqual(hum["dead"], [{"start": 4.0, "end": 6.0, "text": "ですね", "mid": "s3"}])
        out = L.compose(rebuild(M0), hum, L.split_meta(d))   # 作り直しても消した時間帯の機械の行を出さない(O1 の穴)
        self.assertEqual(texts(out), ["こんにちは", "今日はいい天気", "ではまた", "さようなら"])

    def test_small_dead_mark_keeps_long_row(self):
        m = machine([mrow(1, 0.0, 1.0, "あ"), mrow(2, 1.0, 2.0, "い")])
        d = base_doc(m)
        d["segments"] = [seg(d, "s2")]
        hum = L.diff(m, d)
        long_row = machine([{"id": "n1", "start": 0.0, "end": 9.0, "text": "あいうえお長い行", "flag": ""}], rev=2)
        self.assertEqual(texts(L.compose(long_row, hum)), ["あいうえお長い行"])   # 中心 4.5 が印 0〜1 に入らない = 消さない
        short = machine([{"id": "n1", "start": 0.1, "end": 0.9, "text": "あー", "flag": ""}, {"id": "n2", "start": 1.0, "end": 2.0, "text": "い", "flag": ""}], rev=2)
        self.assertEqual(texts(L.compose(short, hum)), ["い"])

    def test_unflag_and_unfill(self):
        d = base_doc()
        seg(d, "s2")["flag"] = ""
        g = seg(d, "s4")
        g["text"] = "では"
        del g["fill"]
        hum = self.assertRoundTrip(M0, d)
        rows = {h["id"]: h for h in hum["rows"]}
        self.assertEqual(rows["s2"], {"id": "s2", "start": 2.0, "end": 4.0, "flagOff": True, "covers": ["s2"],
                                      "base": {"rev": 1, "diar": "", "rows": [{"id": "s2", "start": 2.0, "end": 4.0, "text": "今日はいい天気", "flag": "要確認"}]}})
        self.assertTrue(rows["s4"]["fillOff"])
        self.assertNotIn("text", rows["s4"])   # 属性の行(文字は機械の fill.from)
        out = L.compose(rebuild(M0), hum, L.split_meta(d))   # 作り直しても印を外したまま・別の読みを戻したまま
        self.assertEqual(seg(out, "s2")["flag"], "")
        self.assertEqual(seg(out, "s4")["text"], "では")
        self.assertNotIn("fill", seg(out, "s4"))

    def test_split_join_add_move(self):
        d = base_doc()
        s1 = seg(d, "s1")
        segs = [dict(s1, end=1.0, text="こん"), dict(s1, id="s1x", start=1.0, text="にちは")]   # 分ける
        segs.append({"id": "s2", "start": 2.0, "end": 6.0, "text": "今日はいい天気ですね", "speaker": "", "flag": ""})   # つなぐ(s2 + s3)
        segs.append(dict(seg(d, "s4"), start=6.2, end=8.8))   # 時刻を動かす
        segs.append({"id": "a1", "start": 12.0, "end": 13.0, "text": "足した行", "speaker": "", "flag": ""})   # 足す
        segs.append(seg(d, "s5"))
        segs.sort(key=lambda g: (g["start"], g["end"]))
        d["segments"] = segs
        hum = self.assertRoundTrip(M0, d)
        rows = {h["id"]: h for h in hum["rows"]}
        self.assertEqual(rows["s1"]["covers"], ["s1"])
        self.assertEqual(rows["s1x"]["covers"], ["s1"])   # 分けた行は両方が同じ機械の行を覆う
        self.assertEqual(rows["s2"]["covers"], ["s2", "s3"])
        self.assertEqual(rows["a1"]["covers"], [])
        self.assertEqual(hum["dead"], [])
        out = L.compose(rebuild(M0), hum, L.split_meta(d))   # 同じ中身で作り直しても人の行のまま(機械の行が戻らない・印なし)
        self.assertEqual(texts(out), texts(d))
        self.assertFalse(any(L.MACH_CHANGED in g["flag"] for g in out["segments"]))

    def test_speaker_tags_nosub_draft_order(self):
        d = base_doc()
        d["speakers"] = [{"id": "S1", "name": "ぺこら", "color": "#39f"}]
        seg(d, "s1").update(speaker="S1", tags=["bgm"], noSub=True)
        seg(d, "s5")["id"] = "z9"   # id だけ違う行も属性の行
        d["segments"].append({"id": "d1", "start": 9.0, "end": 12.0, "text": "", "speaker": "", "flag": "", "draft": "overlap"})   # 同じ時刻の下書き
        d["segments"].sort(key=lambda g: (g["start"], g["end"]))
        d["segments"][-2:] = [d["segments"][-1], d["segments"][-2]]   # 同じ時刻の行の並び: 下書きを先に
        d["evalSet"] = True
        hum = self.assertRoundTrip(M0, d)
        self.assertEqual(hum["order"], ["d1", "z9"])
        self.assertEqual(hum["docFields"]["evalSet"], True)
        rows = {h["id"]: h for h in hum["rows"]}
        self.assertEqual((rows["s1"]["speaker"], rows["s1"]["tags"], rows["s1"]["noSub"]), ("S1", ["bgm"], True))
        self.assertEqual(rows["d1"]["covers"], [])   # 空の行は機械の行を覆わない
        self.assertNotIn("text", rows["z9"])

    def test_doc_fields_removed(self):
        d = base_doc()
        d["effort"] = {"sec": 3}
        hum = L.diff(M0, d)
        d2 = copy.deepcopy(d)
        del d2["effort"]
        self.assertEqual(L.roundtrip(M0, d2, hum)[1], [])
        self.assertNotIn("effort", L.compose(M0, L.diff(M0, d2, hum), L.split_meta(d2)))

    def test_compare_docs_reasons(self):
        d = base_doc()
        d2 = copy.deepcopy(d)
        seg(d2, "s1")["text"] = "x"
        seg(d2, "s2")["flag"] = "x"
        d2["title"] = "別"
        self.assertEqual([c for c, _x in L.compare_docs(d, d2)], ["text", "flag", "docFields"])
        d3 = copy.deepcopy(d)
        d3["segments"].reverse()
        self.assertEqual([c for c, _x in L.compare_docs(d, d3)], ["order"])
        d4 = copy.deepcopy(d)
        d4["segments"].pop()
        self.assertEqual([c for c, _x in L.compare_docs(d, d4)], ["rowCount", "rowIds"])


class MachChangedTest(unittest.TestCase):
    def edited(self):
        d = base_doc()
        seg(d, "s2").update(text="今日はいい天気だ", flag="")
        return d, L.diff(M0, d)

    def test_same_text_rebuilt_no_flag(self):
        d, hum = self.edited()
        out = L.compose(rebuild(M0), hum, L.split_meta(d))
        self.assertEqual(seg(out, "s2")["flag"], "")
        self.assertEqual(texts(out), texts(d))

    def test_changed_machine_keeps_human_text_and_flags(self):
        d, hum = self.edited()
        m2 = rebuild(M0, texts={1: "今日は良い天気", 4: "さよなら"})
        out = L.compose(m2, hum, L.split_meta(d))
        g = seg(out, "s2")
        self.assertEqual(g["text"], "今日はいい天気だ")   # 人の直しを残す(既定は自分の直しのまま)
        self.assertIn(L.MACH_CHANGED, g["flag"])
        self.assertEqual(texts(out)[-1], "さよなら")   # 人が触っていない行は新しい機械
        self.assertEqual(sum(1 for x in out["segments"] if L.MACH_CHANGED in x["flag"]), 1)
        # 人がまだ選んでいない間: 保存し直しても印と前の機械(base)が残る・往復も合う
        hum2 = L.diff(m2, out, hum)
        h2 = next(h for h in hum2["rows"] if h["id"] == "s2")
        self.assertEqual(h2["base"]["rows"][0]["text"], "今日はいい天気")
        self.assertEqual(h2["covers"], ["n2"])
        self.assertEqual(L.compose(m2, hum2, L.split_meta(out)), out)
        # 印を外した(自分の直しのまま を選んだ)ら base は今の機械になり、印はもう付かない
        g["flag"] = ""
        hum3 = L.diff(m2, out, hum2)
        self.assertEqual(next(h for h in hum3["rows"] if h["id"] == "s2")["base"]["rows"][0]["text"], "今日は良い天気")
        self.assertEqual(seg(L.compose(m2, hum3, L.split_meta(out)), "s2")["flag"], "")

    def test_machine_row_gone(self):
        d, hum = self.edited()
        out = L.compose(rebuild(M0, drop=(1,)), hum, L.split_meta(d))
        self.assertIn(L.MACH_CHANGED, seg(out, "s2")["flag"])   # 覆っていた機械の行が無くなった(O1 の STALE_FLAG)
        self.assertEqual(seg(out, "s2")["text"], "今日はいい天気だ")

    def test_rev_bump_same_rows(self):
        d, hum = self.edited()
        m2 = copy.deepcopy(M0)
        m2["rev"] = 7   # rev だけ上がった(別の範囲の再認識など): id と写しで当たる
        self.assertEqual(L.compose(m2, hum, L.split_meta(d)), d)

    def test_id_collision(self):
        d = base_doc()
        seg(d, "s1")["text"] = "こんばんは"
        hum = L.diff(M0, d)
        m2 = copy.deepcopy(M0)
        m2["rev"] = 2
        m2["rows"].insert(0, {"id": "s1", "start": 12.0, "end": 13.0, "text": "新しい行", "flag": ""})
        m2["rows"][1]["id"] = "q1"
        out = L.compose(m2, hum, L.split_meta(d))
        ids = [g["id"] for g in out["segments"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("s1x", ids)


class SpeakerTest(unittest.TestCase):
    def setUp(self):
        self.m = machine([mrow(1, 0.0, 2.0, "あ", speaker="S1"), mrow(2, 2.0, 4.0, "い", speaker="S2"), mrow(3, 4.0, 6.0, "う", speaker="S1")],
                         diar="k1", speakers=[{"id": "S1", "name": "S1", "color": "#111"}, {"id": "S2", "name": "S2", "color": "#222"}])

    def first_doc(self):
        d = base_doc(self.m)
        d["speakers"] = [{"id": "S1", "name": "ぺこら", "color": "#39f"}, {"id": "S2", "name": "みこ", "color": "#f39"}]
        return d

    def test_ids_adopted(self):
        d = self.first_doc()
        hum = L.diff(self.m, d)
        self.assertEqual(hum["spkMap"], {"k1": {"S1": "S1", "S2": "S2"}})   # 今の文書の話者の id はそのまま人の id(付け直さない)
        self.assertEqual(hum["rows"], [])
        self.assertEqual(L.compose(self.m, hum, L.split_meta(d)), d)

    def test_rediarize_maps_by_overlap_and_new_h(self):
        d = self.first_doc()
        hum = L.diff(self.m, d)
        # 判別し直し: 話した長さ順の振り直しで S1 と S2 が入れ替わり、知らない声 S3 が増えた
        m2 = machine([mrow(1, 0.0, 2.0, "あ", speaker="S2"), mrow(2, 2.0, 4.0, "い", speaker="S1"), mrow(3, 4.0, 6.0, "う", speaker="S2"),
                      mrow(4, 6.0, 8.0, "え", speaker="S3")], rev=2, diar="k2",
                     speakers=[{"id": "S3", "name": "S3", "color": "#333"}])
        hum2 = L.assign_speakers(m2, hum, d["segments"])
        self.assertEqual(hum2["spkMap"]["k2"], {"S2": "S1", "S1": "S2", "S3": "H1"})
        self.assertEqual(hum2["speakers"][-1], {"id": "H1", "name": "S3", "color": "#333"})
        self.assertEqual(hum2["spkFresh"], ["H1"])
        self.assertEqual(hum["spkMap"], {"k1": {"S1": "S1", "S2": "S2"}})   # 元の人の層は書き換えない
        out = L.compose(m2, hum2, L.split_meta(d))
        self.assertEqual([g["speaker"] for g in out["segments"]], ["S1", "S2", "S1", "H1"])
        self.assertEqual([L.SPK_CHANGED in g["flag"] for g in out["segments"]], [False, False, False, True])   # 自動で当たった行は印なし
        self.assertEqual(L.roundtrip(m2, out, hum2)[1], [])
        self.assertEqual(L.assign_speakers(m2, hum2, out["segments"]), hum2)   # 同じ鍵はもう当てない

    def test_human_speaker_kept_with_weak_flag(self):
        d = self.first_doc()
        seg(d, "s2")["speaker"] = "S1"   # 人が「い」を S1 に直した
        hum = L.diff(self.m, d)
        self.assertEqual(next(h for h in hum["rows"] if h["id"] == "s2")["speaker"], "S1")
        m2 = copy.deepcopy(self.m)
        m2["rev"] = 2
        m2["keys"] = {"diar": "k2"}
        m2["rows"][1]["speaker"] = "S3"   # 判別し直したら機械は 3 人目と言う
        hum2 = L.assign_speakers(m2, hum, d["segments"])
        self.assertEqual(hum2["spkMap"]["k2"]["S3"], "S1")   # 重なりで人の S1 に当たった = 機械が人に合った
        self.assertEqual(seg(L.compose(m2, hum2, L.split_meta(d)), "s2")["flag"], "")
        hum3 = copy.deepcopy(hum)   # 機械の話者が前(S2)とも人の値(S1)とも違う人の話者に当たった
        hum3["speakers"].append({"id": "H1", "name": "H1", "color": ""})
        hum3["spkMap"]["k2"] = {"S1": "S1", "S3": "H1"}
        g = seg(L.compose(m2, hum3, L.split_meta(d)), "s2")
        self.assertEqual(g["speaker"], "S1")   # 人が決めた話者のまま
        self.assertIn(L.SPK_CHANGED, g["flag"])
        self.assertNotIn(L.MACH_CHANGED, g["flag"])

    def test_other_speaker_not_target_and_full_table(self):
        d = self.first_doc()
        d["speakers"].append({"id": "other", "name": "ゲーム音声など", "color": "#8a8f98", "builtin": "other"})
        for g in d["segments"]:
            g["speaker"] = "other"
        hum = L.diff(self.m, d)
        m2 = copy.deepcopy(self.m)
        m2["keys"] = {"diar": "k2"}
        hum2 = L.assign_speakers(m2, hum, d["segments"])
        self.assertEqual(set(hum2["spkMap"]["k2"].values()), {"H1", "H2"})   # ゲーム音声には当てない
        full = copy.deepcopy(hum)
        full["speakers"] = [{"id": "P%d" % i, "name": "p", "color": ""} for i in range(20)]
        self.assertEqual(L.assign_speakers(m2, full, [])["spkMap"]["k2"], {"S1": "", "S2": ""})


class MachFromDocTest(unittest.TestCase):
    def test_from_original(self):
        d = {"original": [{"start": 0, "end": 1, "text": "あ", "avg_logprob": -0.2}, {"start": 1, "end": 2, "text": "い"}],
             "segments": [{"id": "s1", "start": 0, "end": 1, "text": "亜", "speaker": "S1", "flag": "要確認"},
                          {"id": "s2", "start": 1.5, "end": 2, "text": "い", "speaker": "", "flag": "x"}]}
        m = L.mach_from_doc(d)
        self.assertEqual(m["rows"], [{"id": "s1", "start": 0, "end": 1, "text": "あ", "flag": "要確認"}, {"id": "s2", "start": 1, "end": 2, "text": "い", "flag": ""}])
        self.assertEqual(L.roundtrip(m, dict(d, speakers=[{"id": "S1", "name": "a", "color": ""}]))[1], [])


if __name__ == "__main__":
    unittest.main()
