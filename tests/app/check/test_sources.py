"""「確かめる」のカードの出どころ(src/app/check/sources.py)と組み立て(deck.py)の単体テスト。一時フォルダの文書・.diar.json・スタジオの data.json だけを使う。
評価用の文書(evalSet・評価用のフォルダの動画)が 1 枚でも出たら落ちる。

実行(リポジトリ直下から): py -3.12 -m unittest tests/app/check/test_sources.py -v
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _checkkit as kit  # noqa: E402  (src を sys.path へ・YTT_DATA_DIR の既定・write・Ctx)

ROOT = kit.ROOT

from app.check import deck, lineup, sources  # noqa: E402
from human.check import answerlog, apply  # noqa: E402

DOC, EVAL_DOC, EVAL_DIR_DOC = "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"
VID, VID2 = "dQw4w9WgXcQ", "AAAAAAAAAAA"


write = kit.write


def doc(updated, src="", eval_set=False, rows=None):
    d = {"title": "t", "sourcePath": src, "updatedAt": updated, "speakers": [{"id": "S1", "name": "あ"}, {"id": "S2", "name": "い"}],
         "segments": rows if rows is not None else [
             {"id": "s1", "start": 0.0, "end": 2.0, "text": "埋めた文", "fill": {"from": "うめたぶん", "by": "llm"}},
             {"id": "s2", "start": 2.0, "end": 4.0, "text": "校正済み", "proofed": True, "speaker": "S1"},
             {"id": "s3", "start": 4.0, "end": 6.5, "text": "声の行", "speaker": "S2"},
             {"id": "s4", "start": 6.5, "end": 7.0, "text": "短い", "speaker": "S2"},
             {"id": "s5", "start": 7.0, "end": 9.0, "text": "同じ", "fill": {"from": "同 じ", "by": "name"}}]}
    if eval_set:
        d["evalSet"] = True
    return d


def diar(rows):
    return {"schema": sources.DIAR_SCHEMA, "latest": {"rows": rows, "voices": {"speakers": {"S2": {"score": 0.5, "secondScore": 0.45, "reason": "margin"}}}},
            "history": []}


Ctx = kit.Ctx


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = kit.tempdir(self, "ytt-check-src-")
        self.env = {"YTT_DATA_DIR": self.tmp}
        p = mock.patch.dict(os.environ, {"YTT_CHECK_VOICE_DIAR": "1"})   # 判別の声のカード(voice:diar)は既定オフ(10-24)。ここではオンにして作り方を確かめる
        p.start()
        self.addCleanup(p.stop)
        tx = os.path.join(self.tmp, "transcribe", "transcripts")
        self.evaldir = os.path.join(self.tmp, "評価用")
        os.makedirs(self.evaldir)
        self.media = os.path.join(self.tmp, "clip.mp4")   # 元の動画(空のファイル。元の動画が無い文書のカードは出さない)
        open(self.media, "wb").close()
        self.tx = tx
        write(os.path.join(tx, DOC + ".json"), doc(200, src=self.media))
        write(os.path.join(tx, EVAL_DOC + ".json"), doc(300, eval_set=True))
        write(os.path.join(tx, EVAL_DIR_DOC + ".json"), doc(400, src=os.path.join(self.evaldir, "x.mp4")))
        rows = {"s2": {"speaker": "S1", "ratio": 0.9}, "s3": {"speaker": "S2", "ratio": 0.6, "weak": True}, "s4": {"speaker": "S2", "ratio": 0.9},
                "s5": {"speaker": "S1", "ratio": 0.8, "mixed": True}}
        for t in (DOC, EVAL_DOC, EVAL_DIR_DOC):
            write(os.path.join(tx, t + ".diar.json"), diar(rows))
        marks = [{"id": "m1", "start": 10, "end": 40, "score": 0.4}, {"id": "m2", "start": 50, "end": 80, "score": 0.9},
                 {"id": "m3", "start": 90, "end": 120, "status": "rejected"}]
        write(os.path.join(self.tmp, "studio", "data.json"), {"videos": {
            VID: {"id": VID, "kind": "youtube", "title": "配信", "marks": marks},
            VID2: {"id": VID2, "kind": "youtube", "title": "選んだ配信", "marks": [{"id": "m1", "start": 1, "end": 5, "status": "adopted"},
                                                                              {"id": "m2", "start": 6, "end": 9}]}}})
        self.app = os.path.join(self.tmp, "app")
        self.ctx = Ctx(self.app, ROOT, env=self.env, eval_dirs=[self.evaldir])
        deck.invalidate()

    def collect(self, state=None):
        return sources.collect(self.ctx, state)[0]

    def test_schema_matches_diarize(self):
        from pipeline.transcribe import diarize
        self.assertEqual(sources.DIAR_SCHEMA, diarize.DIAR_SCHEMA)

    def test_eval_docs_never_appear(self):
        cards = sources.collect(self.ctx, kinds=lineup.NORMAL_KINDS)[0]   # 普段のレーン(評価のレーンの区間カードは既定オン = 評価用の文書だけを出す)
        self.assertTrue(cards)
        for c in cards:
            self.assertNotIn(EVAL_DOC, c["id"])
            self.assertNotIn(EVAL_DIR_DOC, c["id"])
            self.assertNotIn((c.get("target") or {}).get("docId"), (EVAL_DOC, EVAL_DIR_DOC))

    def test_missing_media_doc_gives_no_cards(self):
        """元の動画が無い文書(片付けで消えた・ネットワークのパス)はどの種類のカードも出さない。YouTube の埋め込み(value:cand)は出す(10-24)"""
        gone = "dddddddddddd"
        write(os.path.join(self.tx, gone + ".json"), doc(900, src=os.path.join(self.tmp, "gone.mp4")))
        write(os.path.join(self.tx, gone + ".diar.json"), diar({"s3": {"speaker": "S2", "ratio": 0.6}}))
        cards = self.collect()
        self.assertFalse([c for c in cards if (c.get("target") or {}).get("docId") == gone])
        self.assertTrue([c for c in cards if (c.get("target") or {}).get("docId") == DOC])
        self.assertTrue([c for c in cards if c["source"] == "cand"])
        self.assertFalse(sources.has_media({"sourcePath": r"\\server\share\x.mp4"}))
        self.assertFalse(sources.has_media({"sourcePath": ""}))
        self.assertTrue(sources.has_media({"sourcePath": self.media}))

    def test_is_eval_failure_leans_to_eval(self):
        """OPT-E1 3e-1: 評価用のフォルダの判定が例外を出したら評価用として扱う(出さない側)"""
        view = sources.View(self.ctx)
        plain = doc(1, src=os.path.join(self.tmp, "ふつう", "y.mp4"))
        self.assertFalse(view.is_eval(plain))
        self.assertTrue(view.is_eval(doc(1, src=os.path.join(self.evaldir, "x.mp4"))))
        orig = sources.settings.in_eval_dir

        def boom(*a, **k):
            raise RuntimeError("x")
        sources.settings.in_eval_dir = boom
        try:
            self.assertTrue(view.is_eval(plain))
        finally:
            sources.settings.in_eval_dir = orig

    def test_v0_sources(self):
        by = {c["id"]: c for c in self.collect()}
        fill = by["read:fill:%s#s1" % DOC]
        self.assertEqual([o["text"] for o in fill["options"]], ["埋めた文", "うめたぶん"])
        self.assertEqual((fill["target"]["docId"], fill["target"]["row"], fill["media"]["url"]), (DOC, "s1", "transcribe/media?id=" + DOC))
        self.assertNotIn("read:fill:%s#s5" % DOC, by)       # 空白だけの違いは出さない
        voice = by["voice:diar:%s#s3" % DOC]
        self.assertEqual(voice["guess"], {"id": "S2", "name": "い"})
        self.assertEqual([o["id"] for o in voice["options"]], ["S2", "S1", "other", "mixed"])   # 名前のボタンは予想(見立てに近い人)から
        self.assertEqual([o["id"] for o in voice["people"]][:2], ["S1", "S2"])                # 「メンバーを選ぶ」の欄は文書の話者から
        self.assertNotIn("voice:diar:%s#s2" % DOC, by)      # 校正済み
        self.assertNotIn("voice:diar:%s#s4" % DOC, by)      # 1 秒未満
        self.assertNotIn("voice:diar:%s#s5" % DOC, by)      # 混ざり
        self.assertIn("time:row:%s#s2" % DOC, by)           # 校正済みの行
        self.assertNotIn("time:row:%s#s1" % DOC, by)
        cand = sorted(c["id"] for c in by.values() if c["source"] == "cand")
        self.assertEqual(cand, ["value:cand:%s#m1" % VID, "value:cand:%s#m2" % VID])   # 選び始めた配信・決めたマークは出さない
        self.assertIn("youtube-nocookie.com/embed/%s?start=50&end=80" % VID, by["value:cand:%s#m2" % VID]["media"]["url"])

    def test_time_after_read_answer(self):
        st = answerlog.State([{"id": answerlog.new_id(), "at": 1, "kind": "read", "source": "fill", "card": "read:fill:%s#s1" % DOC,
                               "target": {"docId": DOC, "row": "s1"}}])
        self.assertIn("time:row:%s#s1" % DOC, {c["id"] for c in self.collect(st)})

    def test_time_gets_every_read_answer_but_unclear(self):
        """読みで答えた行は全部、時刻のカードに(答えた順に先・ショートの文書も)。聞き取れないは回さない・動画の無い文書は数だけ(10-25 ユーザー)"""
        short, gone = "eeeeeeeeeeee", "ffffffffffff"
        learn = os.path.join(self.tmp, "学習用データ", "x.mp4")
        os.makedirs(os.path.dirname(learn))
        open(learn, "wb").close()
        write(os.path.join(self.tx, short + ".json"), doc(150, src=learn))
        write(os.path.join(self.tx, gone + ".json"), doc(160, src=os.path.join(self.tmp, "gone.mp4")))

        def ans(i, tid, row, a):
            return {"id": answerlog.new_id(), "at": i, "kind": "read", "source": "fill", "card": "read:fill:%s#%s" % (tid, row),
                    "target": {"docId": tid, "row": row}, "answer": a}
        st = answerlog.State([ans(1, short, "s1", {"choice": "2"}), ans(2, DOC, "s3", {"choice": "shift"}), ans(3, DOC, "s1", {"choice": "unclear"}),
                              ans(4, DOC, "s5", {"choice": "other", "text": "x"}), ans(5, gone, "s1", {"choice": "1"})])
        with mock.patch.object(sources.voicefill, "in_learn_dir", lambda p: bool(p) and "学習用データ" in p):
            view = sources.View(self.ctx, st)
            cards = sorted(sources.time_row(view), key=lineup._order_key)
        rows = [(c["target"]["docId"], c["target"]["row"]) for c in cards]
        self.assertEqual(rows[:3], [(short, "s1"), (DOC, "s3"), (DOC, "s5")])   # 答えた順・ショートも
        self.assertNotIn((DOC, "s1"), rows)                                     # 聞き取れない
        self.assertEqual(view.notes["timeNoMedia"], 1)                          # 動画の無い文書の答え

    def test_read_card_has_around_rows(self):
        fill = {c["id"]: c for c in self.collect()}["read:fill:%s#s1" % DOC]
        self.assertEqual(fill["around"], {"prev": "", "next": "校正済み"})

    def test_hard_rows_skip_time_and_go_last_in_read(self):
        """BGM 大・重なり・聞き取れない・混ざりの行は時刻のカードに出さない・読みは後ろへ(10-25 確かめるの混ざりと BGM のルール)"""
        rows = [{"id": "p%d" % i, "start": float(i), "end": i + 1.0, "text": "行%d" % i, "proofed": True} for i in range(5)]
        for g, t in zip(rows, (["bgm"], ["overlap"], ["unclear"], None)):
            if t:
                g["tags"] = t
        rows[3]["flag"] = sources._yschemas.MIXED_FLAG
        rows += [{"id": "f1", "start": 10.0, "end": 11.0, "text": "埋め", "fill": {"from": "うめ", "by": "llm"}, "flag": "自信が低い"},
                 {"id": "f2", "start": 12.0, "end": 13.0, "text": "埋め二", "fill": {"from": "うめに", "by": "llm"}}]
        write(os.path.join(self.tx, DOC + ".json"), doc(200, src=self.media, rows=rows))
        cards = self.collect()
        self.assertEqual(sorted(c["target"]["row"] for c in cards if c["kind"] == "time"), ["p4"])
        fill = sorted((c for c in cards if c["kind"] == "read" and c["source"] == "fill"), key=lineup._order_key)
        self.assertEqual([c["target"]["row"] for c in fill], ["f2", "f1"])

    def test_value_auto(self):
        snap = {"cases": [{"id": VID, "title": "ライブ", "streamedAt": 5, "clips": [
            {"markId": "a1", "start": 3, "auto": {"score": 0.7, "originLabel": "配信中の候補"}, "review": {}, "transcript": {"id": DOC}},
            {"markId": "a2", "auto": {"score": 0.4}, "review": {"deliveredAt": 9}, "transcript": {"id": DOC}},   # 送った物も出す(2-8)
            {"markId": "a3", "auto": {}, "review": {"pending": True}, "transcript": {"id": DOC}},
            {"markId": "a4", "auto": {}, "review": {}, "transcript": {"id": EVAL_DOC}},
            {"markId": "a5", "auto": None, "review": {}, "transcript": {"id": DOC}},
            {"markId": "a6", "auto": {}, "review": {}, "exists": False, "transcript": {"id": DOC}},   # 要らないでごみ箱へ
            # まとめて実行の自動で送る形で送らなかった物(D-SEND。案件の auto[マーク].origin full → clip.auto)も出す(2-8)
            {"markId": "a7", "auto": {"origin": "full", "originLabel": "まとめて実行", "score": None}, "review": {"notSent": {"code": "stale"}},
             "transcript": {"id": DOC}}]}], "virtual": []}
        view = sources.View(self.ctx)
        view._cases = snap
        got = sources.value_auto(view)
        self.assertEqual([c["id"] for c in got], ["value:auto:%s#a1" % VID, "value:auto:%s#a2" % VID, "value:auto:%s#a7" % VID])
        self.assertEqual(got[2]["note"], "まとめて実行")
        self.assertEqual((got[0]["target"]["markId"], got[0]["options"], got[0]["note"]), ("a1", ["good", "bad", "unknown"], "配信中の候補"))
        self.assertEqual([r["id"] for r in got[0]["reasons"]], ["boring", "long", "short", "edge", "subtitle", "audio", "other_person"])

    def test_broken_source_does_not_stop_others(self):
        sources.register("time", "boom", lambda view: 1 / 0)
        self.addCleanup(sources._unregister, "time", "boom")
        cards, view = sources.collect(self.ctx)
        self.assertTrue(cards)
        self.assertTrue(any("time:boom" in e for e in view.errors))

    def test_deck_next_and_find(self):
        # 本番の山に載るカードの種類(cut・speech・read の出どころの import が外れると無言で消える)
        self.assertTrue({("cut", "edge"), ("cut", "gap"), ("cut", "whole"), ("speech", "diar"), ("read", "alt")} <= set(sources.registered()))
        got = deck.next_cards(self.ctx, n=3)
        self.assertEqual(len(got["cards"]), 3)
        self.assertGreater(got["total"], 3)
        self.assertEqual(sum(got["counts"]["perKind"].values()), got["total"])
        self.assertTrue(all("_order" not in c for c in got["cards"]))
        self.assertEqual(deck.next_cards(self.ctx, n=0)["cards"], [])
        only = deck.next_cards(self.ctx, kind="voice", n=50)
        self.assertEqual({c["kind"] for c in only["cards"]}, {"voice"})
        self.assertEqual(only["counts"]["perKind"], got["counts"]["perKind"])   # 種類で絞っても、種類ごとの数は絞る前(画面の切り替えの数)
        self.assertEqual(only["total"], got["counts"]["perKind"]["voice"])
        self.assertEqual(only["goal"]["kind"] if only["goal"] else "voice", "voice")
        mine = deck.next_cards(self.ctx, case=VID, n=50)
        self.assertEqual({c["case"]["id"] for c in mine["cards"]}, {VID})
        first = got["cards"][0]["id"]
        self.assertNotIn(first, [c["id"] for c in deck.next_cards(self.ctx, n=50, skip=first)["cards"]])
        self.assertEqual(deck.find(self.ctx, first)["id"], first)
        self.assertIsNone(deck.find(self.ctx, "read:fill:%s#s9" % DOC))
        self.assertIsNone(deck.find(self.ctx, "nope"))
        for bad in ({"kind": "talk"}, {"case": "../x"}, {"n": 99}):
            with self.assertRaises(ValueError):
                deck.next_cards(self.ctx, **bad)

    def _card(self, kind, source, row):
        return {"id": lineup.card_id(kind, source, DOC, row), "kind": kind, "source": source, "case": {"id": "", "title": "t"},
                "target": {"docId": DOC, "row": row}, "media": {}, "text": row, "guess": None, "options": [], "score": None, "note": "", "_order": [-1]}

    def test_find_sees_every_listed_card(self):
        """一覧(next)に出たカードは必ず find で見つかる(CK-1:読みのカードに答えると「もう確かめる物ではありません」で記録できなかった)"""
        calls = []

        def flaky(view):   # 1 回目だけ読める出どころ(E: の文書が一瞬読めない・書き換え中など、一度きりの読みの失敗)
            calls.append(1)
            if len(calls) > 1:
                raise OSError("一度だけ読めない")
            return [self._card("read", "flk", "s1")]

        def mark(view):   # 別の種類の出どころが view に残す物に寄るカード(find が 1 種類だけ集め直すと出ない)
            view.__dict__["_mark_seen"] = True
            return []

        def dep(view):
            return [self._card("value", "dep", "s1")] if view.__dict__.get("_mark_seen") else []
        for k, s, f in (("read", "flk", flaky), ("read", "mrk", mark), ("value", "dep", dep)):
            sources.register(k, s, f)
            self.addCleanup(sources._unregister, k, s)
        deck.invalidate()
        listed = [c["id"] for c in deck.next_cards(self.ctx, n=50)["cards"]]
        self.assertIn("read:flk:%s#s1" % DOC, listed)
        self.assertIn("value:dep:%s#s1" % DOC, listed)
        for cid in listed:
            self.assertEqual((deck.find(self.ctx, cid) or {}).get("id"), cid, cid)
        deck.invalidate()   # 覚えた一覧が切れたあと(答えるまでに 3 秒より長くかかる)でも
        for cid in listed:
            self.assertEqual((deck.find(self.ctx, cid) or {}).get("id"), cid, cid)
        why = []
        self.assertIsNone(deck.find(self.ctx, "read:fill:%s#s9" % DOC, why))   # 出していないカードは今までどおり None
        self.assertTrue(why and any("read:flk" in w for w in why), why)        # 見つからない理由に、集めたときの失敗を添える

    def test_find_does_not_bring_back_a_settled_card(self):
        """一覧に出たあと本当に確かめる物でなくなったカード(行を校正した)は、読みの失敗が無ければ find で出さない"""
        cid = "read:fill:%s#s1" % DOC
        self.assertIn(cid, [c["id"] for c in deck.next_cards(self.ctx, n=50)["cards"]])
        path = os.path.join(self.tmp, "transcribe", "transcripts", DOC + ".json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        d["segments"][0]["proofed"] = True
        d["updatedAt"] = d.get("updatedAt", 0) + 1
        write(path, d)
        deck.invalidate()
        self.assertIsNone(deck.find(self.ctx, cid))

    def test_deck_hides_answered_and_moves_skipped(self):
        cid = "read:fill:%s#s1" % DOC
        answerlog.append(self.app, {"id": answerlog.new_id(), "at": answerlog.now_ms(), "kind": "read", "source": "fill", "card": cid,
                                    "target": {"docId": DOC, "row": "s1"}, "answer": "1", "applied": {}})
        deck.invalidate()
        got = deck.next_cards(self.ctx, n=50)
        self.assertNotIn(cid, [c["id"] for c in got["cards"]])
        self.assertEqual(got["counts"]["today"], 1)
        first = got["cards"][0]["id"]
        answerlog.add_skip(self.app, first)
        deck.invalidate()
        again = [c["id"] for c in deck.next_cards(self.ctx, n=50)["cards"]]
        self.assertEqual(again[-1], first)


if __name__ == "__main__":
    unittest.main()
