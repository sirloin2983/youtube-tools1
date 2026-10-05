#!/usr/bin/env python3
"""「字幕に出さない」行(noSub)と、同時にしゃべっている所(重なり)の数え方・学習・保管のテスト(editor/ed_learn.py。計画 docs/plan/other-voice-and-overlap-plan.md の 2-1・6-2 の 5)。

    python -m unittest editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_nosub_metrics -q          # これだけ(editor/tests で)

- noSub の行(とその時間の機械の行)は、精度の測定の本体・学習・辞書の提案・修正データの書き出し・保管の学習用の材料に入らない。noSub が無い文書は今までと同じ数
- 重なりのまとまりの判定(違う話者で 0.3 秒以上)と、人の行の並べ方を入れ替えた小さい方の数え方
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
import zipfile

from test_backend import S, StoreDir  # noqa: F401  (S = serve)


def sg(i, a, b, text, proofed=True, speaker="", **kw):
    d = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": speaker, "flag": ""}
    if proofed:
        d["proofed"] = True
    d.update(kw)
    return d


def mo(a, b, text):
    return {"start": a, "end": b, "text": text}


class TestSplitNoSub(unittest.TestCase):
    def test_no_nosub_returns_same_lists(self):
        orig, segs = [mo(0, 2, "あ")], [sg(1, 0, 2, "あ")]
        o, s, no, ns = S.split_nosub(orig, segs)
        self.assertIs(o, orig)
        self.assertIs(s, segs)
        self.assertEqual((no, ns), ([], []))

    def test_machine_rows_half_inside_go_to_nosub(self):
        orig = [mo(0, 2, "本体"), mo(4, 6, "ゲーム"), mo(7, 9, "またぎ")]
        # noSub の行は 4〜7。「ゲーム」(4〜6)は全部・「またぎ」(7〜9)は 0 秒しか入らない
        segs = [sg(1, 0, 2, "本体"), sg(2, 4, 7, "ゲームの声", noSub=True), sg(3, 7, 9, "またぎ")]
        o, s, no, ns = S.split_nosub(orig, segs)
        self.assertEqual([x["text"] for x in o], ["本体", "またぎ"])
        self.assertEqual([x["text"] for x in no], ["ゲーム"])
        self.assertEqual([x["id"] for x in s], ["s1", "s3"])
        self.assertEqual([x["id"] for x in ns], ["s2"])

    def test_half_boundary_is_inclusive(self):
        # 機械の行 4〜6 のうち 4〜5 が noSub(ちょうど半分)→ 外す。4〜7 のうち 1 秒(半分未満)→ 残す
        segs = [sg(1, 0, 5, "x", noSub=True)]
        o, _s, no, _ns = S.split_nosub([mo(4, 6, "半分")], segs)
        self.assertEqual((len(o), len(no)), (0, 1))
        o, _s, no, _ns = S.split_nosub([mo(4, 7, "半分未満")], segs)
        self.assertEqual((len(o), len(no)), (1, 0))

    def test_is_nosub_needs_true(self):
        self.assertTrue(S.is_nosub({"noSub": True}))
        self.assertFalse(S.is_nosub({"noSub": 1}))
        self.assertFalse(S.is_nosub({"noSub": "true"}))
        self.assertFalse(S.is_nosub({}))


class TestDocMetricsNoSub(unittest.TestCase):
    base_orig = [mo(0, 4, "祭りが来た"), mo(4, 8, "二人で話す")]
    base_segs = [sg(1, 0, 4, "まつりが来た"), sg(2, 4, 8, "二人で話す")]

    def test_doc_without_nosub_has_no_nosub_key_and_same_numbers(self):
        m = S.doc_metrics({"original": self.base_orig, "segments": self.base_segs})
        self.assertNotIn("noSub", m)
        self.assertEqual((m["groups"], m["refChars"], m["sub"], m["del"], m["ins"]), (2, 11, 1, 1, 0))   # 今までの数(祭り→まつり は置換 1・抜け 1)

    def test_nosub_rows_and_their_machine_chars_are_set_aside(self):
        # 20〜24 はゲームの声(人は noSub の行を書いた)。機械はそこへ文字を書いている → 本体の余分に数えない
        orig = self.base_orig + [mo(20, 24, "ゲームのセリフです")]
        segs = self.base_segs + [sg(3, 20, 24, "ゲームのセリフ", noSub=True)]
        m = S.doc_metrics({"original": orig, "segments": segs})
        plain = S.doc_metrics({"original": self.base_orig, "segments": self.base_segs})
        for k in ("groups", "refChars", "sub", "del", "ins", "changed"):
            self.assertEqual(m[k], plain[k], k)
        self.assertEqual(m["noSub"], {"rows": 1, "sec": 4.0, "machineChars": len("ゲームのセリフです")})

    def test_nosub_in_machine_only_time_is_not_extra(self):
        """noSub の行が無いと、人が書いていない所の機械の文字は「余分」。noSub の行の中なら余分に数えない(校正した範囲の中)"""
        orig = [mo(0, 4, "ええ"), mo(4, 8, "ゲームの声"), mo(8, 12, "おわり")]
        segs = [sg(1, 0, 4, "ええ"), sg(3, 8, 12, "おわり")]
        without = S.doc_metrics({"original": orig, "segments": segs})
        self.assertEqual(without["ins"], len("ゲームの声"))
        segs2 = segs[:1] + [sg(2, 4, 8, "ゲーム", noSub=True)] + segs[1:]
        with_ns = S.doc_metrics({"original": orig, "segments": segs2})
        self.assertEqual(with_ns["ins"], 0)
        self.assertEqual(with_ns["noSub"]["machineChars"], len("ゲームの声"))

    def test_only_nosub_rows_gives_none(self):
        self.assertIsNone(S.doc_metrics({"original": [mo(0, 2, "あ")], "segments": [sg(1, 0, 2, "あ", noSub=True)]}))

    def test_acc_merge_adds_nosub(self):
        a, b = S.new_acc(), S.new_acc()
        S.acc_merge(a, S.doc_metrics({"original": self.base_orig + [mo(20, 24, "ゲーム")], "segments": self.base_segs + [sg(3, 20, 24, "ゲーム", noSub=True)]}))
        S.acc_merge(a, S.doc_metrics({"original": self.base_orig, "segments": self.base_segs}))
        S.acc_merge(a, S.doc_metrics({"original": self.base_orig + [mo(20, 22, "NPC")], "segments": self.base_segs + [sg(3, 20, 22, "NPC", noSub=True)]}))
        self.assertEqual(a["noSub"], {"rows": 2, "sec": 6.0, "machineChars": len("ゲーム") + len("NPC")})
        self.assertNotIn("noSub", S.acc_finish(b))


class TestOverlapGroup(unittest.TestCase):
    def rows(self, a_end, b_start=1.0, sa="A", sb="B"):
        return [sg(1, 0.0, a_end, "あ", speaker=sa), sg(2, b_start, 2.0, "か", speaker=sb)]

    def test_boundary_0_3(self):
        segs = self.rows(1.3)          # 重なり 0.3 秒ちょうど(1.3 − 1.0)
        self.assertTrue(S.is_overlap_group(segs, [0, 1]))
        self.assertTrue(S.is_overlap_group(self.rows(1.31), [0, 1]))
        self.assertFalse(S.is_overlap_group(self.rows(1.29), [0, 1]))

    def test_same_or_missing_speaker_is_not_overlap(self):
        self.assertFalse(S.is_overlap_group(self.rows(1.8, sa="A", sb="A"), [0, 1]))
        self.assertFalse(S.is_overlap_group(self.rows(1.8, sa="", sb="B"), [0, 1]))
        self.assertFalse(S.is_overlap_group(self.rows(1.8, sa="", sb=""), [0, 1]))

    def test_overlap_tag_is_not_a_condition(self):
        segs = self.rows(1.8)
        self.assertTrue(S.is_overlap_group(segs, [0, 1]))          # 音のメモが無くても
        segs = [dict(g, tags=["overlap"]) for g in self.rows(1.0)]  # 音のメモがあっても重なりが無ければ違う
        self.assertFalse(S.is_overlap_group(segs, [0, 1]))

    def test_chain_group_with_pair_in_middle(self):
        # A(0〜2)・A(1.9〜4)は同じ話者・B(3〜5)が A の 2 行目と 1 秒重なる
        segs = [sg(1, 0, 2, "あ", speaker="A"), sg(2, 1.9, 4, "い", speaker="A"), sg(3, 3, 5, "う", speaker="B")]
        self.assertTrue(S.is_overlap_group(segs, [0, 1, 2]))
        self.assertFalse(S.is_overlap_group(segs, [0, 1]))


class TestOverlapBest(unittest.TestCase):
    def test_swapped_order_wins(self):
        segs = [sg(1, 0, 2, "あいう", speaker="A"), sg(2, 1, 3, "かきく", speaker="B")]
        self.assertEqual(S.overlap_best_counts(segs, [0, 1], "あいうかきく"), (0, 0, 0))   # 開始時刻の順
        self.assertEqual(S.overlap_best_counts(segs, [0, 1], "かきくあいう"), (0, 0, 0))   # 話者の並びの入れ替え
        s, d, i = S.overlap_best_counts(segs, [0, 1], "かきあいう")
        self.assertEqual((s, d, i), (0, 1, 0))

    def test_orders_for_interleaved_speakers(self):
        segs = [sg(1, 0, 1, "あ", speaker="A"), sg(2, 0.5, 1.5, "か", speaker="B"), sg(3, 1.2, 2, "い", speaker="A")]
        self.assertEqual(sorted(S.overlap_orders(segs, [0, 1, 2])), sorted(["あかい", "あいか", "かあい"]))
        # 話者ごとの並びで機械が書いたとき、開始時刻の順より小さい
        self.assertEqual(S.overlap_best_counts(segs, [0, 1, 2], "あいか"), (0, 0, 0))
        e = S.lev_counts("あかい", "あいか")
        self.assertGreater(sum(e), 0)

    def test_many_speakers_use_two_orders_only(self):
        segs = [sg(i + 1, 0.1 * i, 1 + 0.1 * i, "ぁぃぅぇぉ"[i], speaker="S%d" % i) for i in range(5)]
        self.assertLessEqual(len(S.overlap_orders(segs, [0, 1, 2, 3, 4])), 2)
        three = segs[:3]
        self.assertEqual(len(S.overlap_orders(three, [0, 1, 2])), 6)   # 3 人までは並びを全部(開始時刻の順 = 話者ごとの 1 つと同じなので 6)

    def test_one_speaker_has_only_start_order(self):
        segs = [sg(1, 0, 2, "あい", speaker="A"), sg(2, 1, 3, "うえ", speaker="A")]
        self.assertEqual(S.overlap_orders(segs, [0, 1]), ["あいうえ"])


class TestLearningSkipsNoSub(StoreDir):
    def test_learn_events_ignores_nosub_rows(self):
        orig = [mo(0, 3, "トーイ様は後合流"), mo(10, 13, "ポルカ")]
        segs = [sg(1, 0, 3, "トワ様は後合流"), sg(2, 10, 13, "ホロライブ", noSub=True)]
        ev = [(w, r) for w, r, _c, _l, _r in S.learn_events({"original": orig, "segments": segs})]
        self.assertIn(("トーイ", "トワ"), ev)
        self.assertFalse([e for e in ev if "ポルカ" in e[0] or "ホロ" in e[1]])
        # noSub を外すと材料に入る(印が効いている)
        segs2 = [segs[0], dict(segs[1], noSub=False)]
        ev2 = [(w, r) for w, r, _c, _l, _r in S.learn_events({"original": orig, "segments": segs2})]
        self.assertTrue([e for e in ev2 if "ポルカ" in e[0]])

    def test_learn_groups_both_scopes_skip_nosub(self):
        orig = [mo(0, 3, "あい"), mo(10, 13, "ぽるか")]
        segs = [sg(1, 0, 3, "あう"), sg(2, 10, 13, "ホロ", noSub=True)]
        doc = {"original": orig, "segments": segs}
        self.assertEqual([g["text"] for g in S.learn_groups(doc)], ["あう"])
        self.assertEqual([g["text"] for g in S.learn_groups(doc, "proofed")], ["あう"])
        self.assertEqual([g["text"] for g in S.learn_groups({"segments": segs}, "proofed")], ["あう"])   # original が無い文書

    def test_doc_info_texts_skip_nosub(self):
        doc = {"id": "aaaaaaaaaaaa", "original": [mo(0, 2, "あい"), mo(5, 7, "NPC")], "segments": [sg(1, 0, 2, "あう"), sg(2, 5, 7, "NPCのセリフ", noSub=True)]}
        self.put_doc(doc, "aaaaaaaaaaaa")
        info = S._doc_info("aaaaaaaaaaaa")
        self.assertEqual(info["texts"], ["あう"])
        self.assertEqual(info["lines"], 1)

    def test_export_corrections_skips_nosub(self):
        doc = {"id": "aaaaaaaaaaaa", "original": [mo(0, 3, "あい"), mo(5, 8, "ぽるか")],
               "segments": [sg(1, 0, 3, "あう"), sg(2, 5, 8, "ホロ", noSub=True)]}
        self.put_doc(doc, "aaaaaaaaaaaa")
        for scope in ("changed", "proofed"):
            path, n, _na, _sk = S.export_corrections("aaaaaaaaaaaa", audio=False, scope=scope)
            try:
                with zipfile.ZipFile(path) as z:
                    rows = [json.loads(x) for x in z.read("corrections.jsonl").decode("utf-8").splitlines()]
            finally:
                os.unlink(path)
            self.assertEqual([r["text"] for r in rows], ["あう"], scope)
            self.assertEqual(n, 1)


class TestArchiveNoSub(unittest.TestCase):
    def doc(self, nosub=True):
        orig = [mo(0, 3, "あい"), mo(5, 8, "ぽるか"), mo(9, 12, "おわり")]
        segs = [sg(1, 0, 3, "あう", speaker="S1"), sg(2, 5, 8, "ホロ", speaker="S2", noSub=True) if nosub else sg(2, 5, 8, "ホロ", speaker="S2"), sg(3, 9, 12, "おわり", speaker="S1")]
        return {"id": "aaaaaaaaaaaa", "original": orig, "segments": segs, "speakers": [{"id": "S1", "name": "トワ"}, {"id": "S2", "name": "ゲーム音声など"}]}

    def test_nosub_row_is_kept_with_role_nosub(self):
        e = S.archive_entries(self.doc())
        self.assertEqual([x["role"] for x in e], ["positive", "nosub", "positive"])
        ns = e[1]
        self.assertTrue(ns["noSub"])
        self.assertEqual((ns["text"], ns["original"], ns["speakerName"]), ("ホロ", "ぽるか", "ゲーム音声など"))
        self.assertEqual([x["kind"] for x in e], ["line", "line", "line"])
        self.assertNotIn("noSub", e[0])
        self.assertEqual(len({x["key"] for x in e}), 3)

    def test_nosub_machine_row_is_not_a_negative(self):
        """noSub の行を人が書かずに機械の行だけが残っても(行と対応しない)、負例(人が消した行)にはしない"""
        d = self.doc()
        d["original"].append(mo(5.2, 6, "もうひとつ"))
        e = S.archive_entries(d)
        self.assertNotIn("negative", [x["role"] for x in e])

    def test_doc_without_nosub_is_unchanged(self):
        e = S.archive_entries(self.doc(nosub=False))
        self.assertEqual([x["role"] for x in e], ["positive", "positive", "positive"])
        self.assertTrue(all("noSub" not in x for x in e))

    def test_index_rebuild_excludes_nosub(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        old = S.DATASET_DIR
        S.DATASET_DIR = tmp
        try:
            os.makedirs(os.path.join(tmp, "docs", "aaaaaaaaaaaa"))
            with open(os.path.join(tmp, "docs", "aaaaaaaaaaaa", "lines.jsonl"), "w", encoding="utf-8") as f:
                for e in S.archive_entries(self.doc()):
                    e.pop("audioSig", None)
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            S.archive_rebuild_index()
            with open(os.path.join(tmp, "index.jsonl"), encoding="utf-8") as f:
                roles = [json.loads(x)["role"] for x in f.read().splitlines()]
            self.assertEqual(roles, ["positive", "positive"])
        finally:
            S.DATASET_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
