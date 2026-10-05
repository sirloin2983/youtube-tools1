#!/usr/bin/env python3
"""元の配信の YouTube の字幕を校正の候補に出す(案 A1。editor/ed_ytcap.py)のテスト。**通信しない**(偽の yt-dlp tests/fake_ytdlp.py)。

    py -3.10 -m unittest editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    py -3.10 -m unittest test_ytcap -q                  # これだけ(editor/tests で)

- 純粋な関数: json3 の読み方(言葉ごとの時刻・改行だけの行・[音楽])・文書の範囲の切り出しと時刻の直し(clip_offset・actualStart・文書の範囲)・
  元の配信が分からない文書・ID の検査・alt_diffs をそのまま使う比べ方(tier yt)・切り抜きの頭と終わりは出さない
- 提案(suggest_for_doc): yt の候補・学習 → alt → yt の優先・alt と同じ直しは 1 つにまとめる(also)・却下・評価用には出さない・採否の数え方(学習の統計に入れない)
- ジョブ(偽の yt-dlp): 書く物・文書は書き換えない・配信ごとに使い回す・30 日で取り直す・手/自動の優先・字幕なし・非公開などの理由・取り消し・時間の上限・
  断る(評価用・元の配信が分からない・文字の無い文書・実行中)・autoYtcap
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt_core.datadir)
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS))
sys.path.insert(0, TESTS)
from test_backend import S, TID, StoreDir, write_json  # noqa: F401,E402  (S = serve)
import ed_alt  # noqa: E402
import ed_jobs  # noqa: E402
import ed_state  # noqa: E402
import ed_store  # noqa: E402
import ed_ytcap as Y  # noqa: E402

__all__ = ["TestYtcapPure", "TestYtcapSuggest", "TestYtcapJob"]   # test_metrics の import * で、テストの小道具(seg・doc など)が test_metrics の同じ名前を隠さないように
FAKE = os.path.join(TESTS, "fake_ytdlp.py")
VID = "AbCdEfGh_-1"
OFF = 100.0   # 切り抜きの先頭 = 配信の 100 秒目


def clip(vid=VID, start=OFF, end=OFF + 9, kind="youtube", **export):
    return {"schema": "youtube-tools-clip/v1", "tool": {"name": "clip-studio", "version": "x"}, "media": {"path": "x.mp4", "name": "x.mp4", "durationSec": end - start},
            "source": {"kind": kind, "videoId": vid, "url": None, "title": "配信", "path": None}, "range": {"start": start, "end": end},
            "mark": {"id": "m1", "label": "", "status": "exported", "src": "manual"}, "export": dict({"mode": "precise"}, **export)}


def seg(i, a, b, text, **kw):
    return dict({"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}, **kw)


def ev(t_ms, *words, dur=3000):
    """json3 の 1 行(言葉 = (オフセットのミリ秒, 文字))"""
    return {"tStartMs": t_ms, "dDurationMs": dur, "wWinId": 1, "segs": [dict({"utf8": w}, **({"tOffsetMs": o} if o else {})) for o, w in words]}


# 配信の時刻(ミリ秒)。切り抜きは 100〜109 秒。範囲の前後の行は切り出しで消える
JSON3 = {"events": [{"tStartMs": 0, "dDurationMs": 999999999, "id": 1},
                    ev(97000, (0, "前の話です")),
                    ev(100100, (0, "こんばんは"), (700, "白神"), (1100, "フブキ"), (1600, "です")),
                    {"tStartMs": 102900, "wWinId": 1, "aAppend": 1, "segs": [{"utf8": "\n"}]},
                    ev(103100, (0, "今日は"), (500, "[音楽]"), (900, "マイクラを"), (1500, "やります")),
                    ev(106100, (0, "よろしく"), (500, "お願い"), (900, "します")),
                    ev(109600, (0, "次の話です"))]}
MANUAL = {"events": [ev(100100, (0, "こんばんは白上フブキです")), ev(103100, (0, "今日はマイクラをやります")), ev(106100, (0, "よろしくお願いしました"))]}


def doc(**over):
    d = {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "", "start": 0, "end": 9, "updatedAt": 1000, "clip": clip(),
         "segments": [seg(1, 0, 3, "こんばんは白上フブキです"), seg(2, 3, 6, "今日はマイクラをやります"), seg(3, 6, 9, "よろしくお願いします")], "original": []}
    d.update(over)
    return d


class TestYtcapPure(unittest.TestCase):
    def test_parse_json3(self):
        cues = Y.ytcap_parse_json3(JSON3)
        self.assertEqual(len(cues), 5)   # 窓の定義・改行だけの行は捨てる
        c = cues[1]
        self.assertEqual([(w[0], w[2]) for w in c], [(100100, "こんばんは"), (100800, "白神"), (101200, "フブキ"), (101700, "です")])
        self.assertEqual([w[1] for w in c[:3]], [100800, 101200, 101700])   # 言葉の終わり = 次の言葉の始まり
        self.assertEqual(c[3][1], 101700 + 400)                             # 最後の言葉は字数の目安(2 文字 × 0.2 秒)
        self.assertEqual([w[2] for w in cues[2]], ["今日は", "マイクラを", "やります"])   # [音楽] は捨てる
        # 最後の言葉の長さは次の字幕の始まりまで
        cues = Y.ytcap_parse_json3({"events": [ev(0, (0, "あいうえおかきくけこ")), ev(1000, (0, "次"))]})
        self.assertEqual(cues[0][0][1], 1000)
        self.assertEqual(Y.ytcap_parse_json3({"events": "x"}), [])
        self.assertEqual(Y.ytcap_parse_json3([]), [])

    def test_doc_range_and_offset(self):
        r = Y.ytcap_doc_range(doc())
        self.assertEqual((r["videoId"], r["offset"], r["a"], r["b"]), (VID, 100.0, 100.0, 109.0))
        r = Y.ytcap_doc_range(doc(start=2, end=None))   # 文書が切り抜きの 2 秒目〜最後
        self.assertEqual((r["a"], r["b"], r["docStart"], r["docEnd"]), (102.0, 109.0, 2.0, 9.0))
        r = Y.ytcap_doc_range(doc(clip=clip(actualStart=99.5)))   # 以前の高速の書き出し: キーフレームにずれた実際の開始を優先
        self.assertEqual((r["offset"], r["a"]), (99.5, 99.5))
        for d, why in ((doc(clip=None), "no clip"), (doc(clip=clip(kind="file")), "file"), (doc(clip=clip(kind="live")), "live"),
                       (doc(clip=clip(vid="abc")), "short id"), (doc(clip=clip(vid="AbCdEfGh_-1\n")), "newline"), (doc(clip=clip(vid="AbCdEfGh/-1")), "slash"),
                       (doc(clip=clip(start=5, end=1)), "bad range"), (doc(clip=dict(clip(), schema="other")), "schema")):
            with self.subTest(why=why):
                with self.assertRaises(ed_state.ApiError) as cm:
                    Y.ytcap_doc_range(d)
                self.assertEqual(cm.exception.code, "no_clip")
        with self.assertRaises(ed_state.ApiError):
            Y.ytcap_video_path("../../evil.")   # ファイル名にも決まった形だけ
        with self.assertRaises(ed_state.ApiError):
            Y.ytcap_fetch({"id": "x", "cancel": False}, "a b c d e f")

    def test_cut_converts_times(self):
        rows, rng = Y.ytcap_doc_rows(doc(), {"cues": Y.ytcap_parse_json3(JSON3)})
        self.assertEqual([r["text"] for r in rows], ["こんばんは白神フブキです", "今日はマイクラをやります", "よろしくお願いします"])
        self.assertEqual([r["start"] for r in rows], [0.1, 3.1, 6.1])    # 配信の時刻 − 100 秒 = 文書の時刻
        self.assertTrue(all(r["end"] > r["start"] for r in rows))
        # 範囲の途中にかかる言葉は、文字ごとの時刻(言葉の長さを字数で等分)の真ん中で分ける
        cues = [[[99000, 101000, "あいうえ"]]]   # 1 文字 0.5 秒: 真ん中 99.25・99.75・100.25・100.75
        self.assertEqual(Y.ytcap_cut(cues, 100.0, 109.0, 100.0), [{"start": 0.0, "end": 1.0, "text": "うえ"}])
        self.assertEqual(Y.ytcap_cut(cues, 98.0, 100.0, 98.0)[0]["text"], "あい")
        self.assertEqual(Y.ytcap_cut([[["x", 1, 2]], "bad", []], 0, 9, 0), [])   # 壊れた形は黙って捨てる

    def test_diffs_are_alt_diffs_with_tier_yt(self):
        rows = doc()["segments"]
        yt, _rng = Y.ytcap_doc_rows(doc(), {"cues": Y.ytcap_parse_json3(JSON3)})
        items, st = Y.ytcap_diffs(rows, yt)
        self.assertEqual(items, [{"seg": "s1", "i": 6, "wrong": "上", "right": "神", "tier": "yt", "pos": 0, "neg": 0}])
        self.assertEqual(items[0]["wrong"], ed_alt.alt_diffs(rows, yt)[0][0]["wrong"])   # 比べ方は alt_diffs そのもの
        self.assertEqual(set(st), {"long", "cross", "mostly", "notation", "edge", "clipEdge", "filler"})
        # 句読点・カタカナ/ひらがな・全角/半角の違いは出さない
        items, _st = Y.ytcap_diffs([seg(1, 0, 3, "ＯＫです、ふぶきちゃん")], [{"start": 0, "end": 3, "text": "OKです。フブキちゃん"}])
        self.assertEqual(items, [])

    def test_fillers_are_not_candidates(self):
        """YouTube の字幕が句読点で区切って足した言いよどみ(え・あの・おお・ああ)だけの候補は出さない。句読点の無い 1 文字の足しは本当の直しのことがあるので出す"""
        self.assertTrue(Y.ytcap_filler_only("よ", "よ。あの"))
        self.assertTrue(Y.ytcap_filler_only("て", "て。え"))
        self.assertTrue(Y.ytcap_filler_only("な", "な。おお。ああ"))
        self.assertTrue(Y.ytcap_filler_only("何", "えっ、何"))
        self.assertFalse(Y.ytcap_filler_only("す", "ます"))
        self.assertFalse(Y.ytcap_filler_only("なで", "なんで"))
        self.assertFalse(Y.ytcap_filler_only("よ", "よ。本当"))
        self.assertFalse(Y.ytcap_filler_only("上", "神"))
        rows = [seg(1, 0, 3, "はじめに"), seg(2, 3, 6, "今日はいい天気だよそれでね"), seg(3, 6, 9, "おわりに")]
        items, st = Y.ytcap_diffs(rows, [{"start": 0, "end": 3, "text": "はじめに"}, {"start": 3, "end": 6, "text": "今日はいい天気だよ。あの、それでね"},
                                         {"start": 6, "end": 9, "text": "おわりに"}])
        self.assertEqual((items, st["filler"]), ([], 1))

    def test_clip_edges_are_not_candidates(self):
        """切り抜きの頭(最初の行の頭)と終わり(最後の行の終わり)にかかる食い違いは出さない(字幕の時刻で切るので境目の言葉がずれる)"""
        rows = doc()["segments"]
        yt = [{"start": 0, "end": 3, "text": "ねこんばんは白上フブキです"}, {"start": 3, "end": 6, "text": "今日はマイクラをやります"},
              {"start": 6, "end": 9, "text": "よろしくお願いしますね"}]
        items, st = Y.ytcap_diffs(rows, yt)
        self.assertEqual((items, st["clipEdge"]), ([], 2))
        self.assertEqual(len(ed_alt.alt_diffs(rows, yt)[0]), 2)   # alt_diffs だけなら出る
        # 真ん中の行の頭・終わりは出す
        yt[1] = {"start": 3, "end": 6, "text": "今日もマイクラをやります"}
        items, _st = Y.ytcap_diffs(rows, yt)
        self.assertEqual([(x["seg"], x["wrong"], x["right"]) for x in items], [("s2", "は", "も")])


class _YtStore(StoreDir):
    def setUp(self):
        super().setUp()
        self.fb = mock.patch.object(ed_state, "FEEDBACK", os.path.join(self.tmp, "learn-feedback.json"))
        self.fb.start()
        self.capdir = mock.patch.object(Y, "YTCAP_DIR", os.path.join(self.tmp, "ytcaps"))
        self.capdir.start()
        ed_alt._alt_cache.clear()
        Y._ytcap_cache.clear()

    def tearDown(self):
        self.capdir.stop()
        self.fb.stop()
        super().tearDown()

    def put_yt(self, rows, tid=TID, **over):
        write_json(Y.ytcap_path(tid), dict({"schema": Y.YTCAP_SCHEMA, "id": tid, "source": "youtube", "kind": "auto", "lang": "ja-orig", "videoId": VID,
                                            "at": 7, "fetchedAt": 6, "offset": OFF, "streamRange": [100, 109], "range": [0, 9], "rows": rows}, **over))

    def put_alt(self, rows, tid=TID):
        write_json(S.alt_path(tid), {"schema": S.ALT_SCHEMA, "id": tid, "engine": "llama.cpp", "model": "qwen3-asr-1.7b", "at": 5, "range": [0, 9], "rows": rows})


def _r(a, b, text):
    return {"start": a, "end": b, "text": text}


class TestYtcapSuggest(_YtStore):
    def test_suggest_has_yt_and_info(self):
        self.put_doc(doc())
        self.put_yt([_r(0, 3, "こんばんは白神フブキです"), _r(3, 6, "今日はマイクラをやります"), _r(6, 9, "よろしくお願いします")])
        r = S.suggest_for_doc(TID)
        yts = [x for x in r["items"] if x["tier"] == "yt"]
        self.assertEqual([(x["seg"], x["i"], x["wrong"], x["right"]) for x in yts], [("s1", 6, "上", "神")])
        self.assertEqual((r["yt"]["kind"], r["yt"]["count"], r["yt"]["agree"], r["yt"]["at"], r["yt"]["videoId"]), ("auto", 1, 0, 7, VID))
        self.assertIn("clipEdge", r["yt"]["skipped"])
        self.assertIsNone(r["alt"])
        # 却下 → 出ない。数は fb["yt"] だけ(学習の統計に入れない)
        S.record_feedback({"tid": TID, "action": "reject", "items": [{"seg": "s1", "wrong": "上", "right": "神", "tier": "yt"}]})
        fb = S.load_feedback()
        self.assertEqual((fb["yt"], fb["stat"], fb.get("alt")), ({"acc": 0, "rej": 1}, {}, None))
        r = S.suggest_for_doc(TID)
        self.assertEqual([x for x in r["items"] if x["tier"] == "yt"], [])
        self.assertEqual(r["yt"]["count"], 0)

    def test_priority_learned_alt_yt_and_agreement(self):
        """学習 → alt → yt。alt と同じ直しは 1 つにまとめて also: ["yt"](札「別・YT」)、同じ位置で違う直しは alt"""
        self.put_doc(doc(segments=[seg(1, 0, 3, "こんばんは白上フブキです"), seg(2, 3, 6, "今日はマイクラをやります"), seg(3, 6, 9, "よろしくお願いします")]))
        self.put_alt([_r(0, 3, "こんばんは白神フブキです"), _r(3, 6, "今日はマイクラをやりました"), _r(6, 9, "よろしくお願いします")])
        self.put_yt([_r(0, 3, "こんばんは白神フブキです"), _r(3, 6, "今日はマイクラをやりまに"), _r(6, 9, "よろしくお願いしまーす")])
        r = S.suggest_for_doc(TID)
        alt = [x for x in r["items"] if x["tier"] == "alt"]
        yts = [x for x in r["items"] if x["tier"] == "yt"]
        self.assertEqual([(x["seg"], x["wrong"], x["right"], x.get("also")) for x in alt], [("s1", "上", "神", ["yt"]), ("s2", "す", "した", None)])
        self.assertEqual(yts, [])   # s1 は alt とまとめ・s2 は同じ位置で違う直し → alt
        self.assertEqual((r["yt"]["count"], r["yt"]["agree"]), (1, 1))
        # 学習の提案と重なる位置は yt も出さない
        d = doc()
        items, info = Y.ytcap_suggest(TID, d, set(), [{"seg": "s1", "i": 5, "wrong": "白上", "right": "白神", "tier": "mid"}], [])
        self.assertEqual(([x["seg"] for x in items], info["count"]), (["s2"], 1))   # s1 は学習の提案と重なる・s2 は alt が無ければ出る
        # 一致した候補を採用すると、alt と yt の両方に数える(学習の統計には入れない)
        S.record_feedback({"tid": TID, "action": "accept", "items": [{"seg": "s1", "wrong": "上", "right": "神", "tier": "alt", "also": ["yt"]}]})
        S.record_feedback({"tid": TID, "action": "accept", "items": [{"seg": "s2", "wrong": "x", "right": "y", "tier": "alt", "also": [{"bad": 1}, "zz"]}]})
        fb = S.load_feedback()
        self.assertEqual((fb["alt"], fb["yt"], fb["stat"]), ({"acc": 2, "rej": 0}, {"acc": 1, "rej": 0}, {}))

    def test_eval_and_missing_file(self):
        self.put_doc(doc())
        self.assertIsNone(S.suggest_for_doc(TID)["yt"])
        self.put_yt([_r(0, 3, "こんばんは白神フブキです")])
        self.put_doc(doc(evalSet=True))
        r = S.suggest_for_doc(TID)
        self.assertIsNone(r["yt"])
        self.assertEqual([x for x in r["items"] if x["tier"] == "yt"], [])
        write_json(Y.ytcap_path(TID), {"schema": "other", "rows": []})   # 形が違うものは読まない
        self.put_doc(doc())
        self.assertIsNone(S.suggest_for_doc(TID)["yt"])

    def test_dict_version_ignores_yt(self):
        write_json(ed_state.FEEDBACK, {"stat": {}, "dismissed": {}, "yt": {"acc": 1, "rej": "x"}})
        self.assertEqual(S.load_feedback()["yt"], {"acc": 1, "rej": 0})
        v1 = S.dict_version({"autoLearned": True})
        write_json(ed_state.FEEDBACK, {"stat": {}, "dismissed": {}, "yt": {"acc": 9, "rej": 3}})
        self.assertEqual(S.dict_version({"autoLearned": True}), v1)


class TestYtcapJob(_YtStore):
    def setUp(self):
        super().setUp()
        self.files = tempfile.mkdtemp()
        self.log = os.path.join(self.files, "calls.jsonl")
        write_json(os.path.join(self.files, "auto.json3"), JSON3)
        write_json(os.path.join(self.files, "manual.json3"), MANUAL)
        self.env = mock.patch.dict(os.environ, {"TRANSCRIBE_YTDLP": FAKE, "FAKE_YTDLP_LOG": self.log, "FAKE_YTDLP_MODE": "auto",
                                                "FAKE_YTDLP_JSON3": os.path.join(self.files, "auto.json3"),
                                                "FAKE_YTDLP_MANUAL_JSON3": os.path.join(self.files, "manual.json3")})
        self.env.start()
        self.mine = set()

    def tearDown(self):
        self.env.stop()
        with ed_jobs._jobs_lock:
            for k in list(self.mine):
                ed_jobs._jobs.pop(k, None)
        import shutil
        shutil.rmtree(self.files, ignore_errors=True)
        super().tearDown()

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def job(self, tid=TID):
        j = ed_jobs.add_job(Y.ytcap_spec(tid, {}), "ytcap")
        self.mine.add(j["id"])
        return j

    def run_job(self, tid=TID, state="done"):
        j = self.job(tid)
        ed_jobs.run_job(j)
        self.assertEqual(j["state"], state, j.get("error"))
        return j

    def test_job_writes_ytcap_and_keeps_doc(self):
        self.put_doc(doc())
        before = ed_store.read_transcript(TID)
        j = self.run_job()
        self.assertEqual((j["tid"], j["kind"], j["segments"]), (TID, "ytcap", 3))
        y = Y.read_ytcap(TID)
        self.assertEqual((y["schema"], y["source"], y["kind"], y["lang"], y["videoId"], y["streamRange"], y["range"], y["offset"]),
                         (Y.YTCAP_SCHEMA, "youtube", "auto", "ja-orig", VID, [100.0, 109.0], [0.0, 9.0], 100.0))
        self.assertEqual([r["text"] for r in y["rows"]], ["こんばんは白神フブキです", "今日はマイクラをやります", "よろしくお願いします"])
        self.assertEqual(ed_store.read_transcript(TID), before)   # 文書は書き換えない(updatedAt も)
        # 引数: 字幕だけ・設定とクッキーを使わない・URL は ID から作る
        args = self.calls()[0]
        for a in ("--skip-download", "--ignore-config", "--no-cookies", "--write-subs", "--write-auto-subs", "json3"):
            self.assertIn(a, args)
        self.assertEqual(args[-2:], ["--", "https://www.youtube.com/watch?v=" + VID])
        self.assertIn("ja,ja-JP,ja-orig", args)
        self.assertNotIn("-f", args)
        # 配信ごとに置いて使い回す
        cache = Y.ytcap_load(VID)
        self.assertEqual((cache["kind"], cache["videoId"], len(cache["cues"])), ("auto", VID, 5))
        self.assertEqual(os.listdir(os.path.join(self.tmp, "ytcaps")), [VID + ".json"])
        self.assertFalse(os.path.isdir(os.path.join(S.TMP_DIR, j["id"] + "-ytcap")))   # 作業用のフォルダは消す
        tid2 = "abcdefabcdef"
        self.put_doc(doc(id=tid2, start=3, end=6, segments=[seg(2, 3, 6, "今日もマイクラをやります")]), tid=tid2)
        j2 = self.run_job(tid2)
        self.assertEqual(len(self.calls()), 1)   # 同じ配信の別の文書: 取り直さない
        self.assertIn("取ってあった字幕", j2["phase"])
        self.assertEqual([r["text"] for r in Y.read_ytcap(tid2)["rows"]], ["今日はマイクラをやります"])
        # suggest に出る(今の行と比べる)
        r = S.suggest_for_doc(tid2)
        self.assertEqual([(x["wrong"], x["right"], x["tier"]) for x in r["items"]], [("も", "は", "yt")])   # 今の行と比べる(行の真ん中なので境目ではない)
        # 30 日たったら取り直す
        cache["at"] = int(time.time() * 1000) - (Y.YTCAP_TTL_SEC + 10) * 1000
        write_json(Y.ytcap_video_path(VID), cache)
        self.run_job(tid2)
        self.assertEqual(len(self.calls()), 2)

    def test_manual_wins_over_auto(self):
        self.put_doc(doc())
        os.environ["FAKE_YTDLP_MODE"] = "manual"
        self.run_job()
        y = Y.read_ytcap(TID)
        self.assertEqual((y["kind"], y["lang"]), ("manual", "ja"))
        self.assertEqual([r["text"] for r in y["rows"]], ["こんばんは白上フブキです", "今日はマイクラをやります", "よろしくお願いしました"])
        r = S.suggest_for_doc(TID)
        self.assertEqual(r["yt"]["kind"], "manual")

    def test_no_captions_is_remembered(self):
        self.put_doc(doc())
        os.environ["FAKE_YTDLP_MODE"] = "none"
        j = self.run_job(state="error")
        self.assertIn("字幕がありません", j["error"])
        self.assertEqual(Y.ytcap_load(VID)["kind"], "none")
        self.assertIsNone(Y.read_ytcap(TID))
        self.run_job(state="error")
        self.assertEqual(len(self.calls()), 1)   # 「字幕が無い」も 1 日は覚える

    def test_failures_are_separated_and_not_cached(self):
        self.put_doc(doc())
        for mode, code_word in (("private", "非公開"), ("unavailable", "見つかりません"), ("bot", "ボット"), ("unlisted", "限定公開"),
                                ("live", "配信中"), ("fail", "something strange")):
            with self.subTest(mode=mode):
                os.environ["FAKE_YTDLP_MODE"] = mode
                j = self.run_job(state="error")
                self.assertIn(code_word, j["error"])
                self.assertIsNone(Y.ytcap_load(VID))
                self.assertIsNone(Y.read_ytcap(TID))
        e = Y.ytcap_classify("ERROR: [youtube] x: HTTP Error 429: Too Many Requests", 1)
        self.assertEqual(e.code, "too_many")
        self.assertEqual(Y.ytcap_classify("ERROR: Join this channel to get access to members-only content", 1).code, "not_public")

    def test_no_ytdlp(self):
        self.put_doc(doc())
        with mock.patch.object(Y._tools, "find_tool", return_value=None):
            j = self.run_job(state="error")
            self.assertIn("yt-dlp が見つかりません", j["error"])
            self.assertFalse(Y.ytcap_info()["ready"])
        self.assertTrue(Y.ytcap_info()["ready"])

    def test_cancel_and_timeout(self):
        self.put_doc(doc())
        os.environ["FAKE_YTDLP_SLEEP"] = "8"
        j = self.job()
        threading.Timer(0.8, lambda: j.update(cancel=True)).start()
        t0 = time.monotonic()
        ed_jobs.run_job(j)
        self.assertEqual(j["state"], "cancelled")
        self.assertLess(time.monotonic() - t0, 6)
        with mock.patch.object(Y, "YTCAP_TIMEOUT_SEC", 0.5):
            j = self.run_job(state="error")
        self.assertIn("秒を超えた", j["error"])
        self.assertIsNone(Y.ytcap_load(VID))

    def test_refusals(self):
        for d, code in ((doc(evalSet=True), "eval_set"), (doc(segments=[]), "empty"), (doc(clip=None), "no_clip"), (doc(clip=clip(kind="file")), "no_clip")):
            with self.subTest(code=code):
                self.put_doc(d)
                with self.assertRaises(S.ApiError) as cm:
                    Y.ytcap_spec(TID, {})
                self.assertEqual(cm.exception.code, code)
        self.put_doc(doc())
        self.job()
        with self.assertRaises(S.ApiError) as cm:
            Y.ytcap_spec(TID, {})
        self.assertEqual(cm.exception.code, "busy")

    def test_doc_deleted_during_job(self):
        self.put_doc(doc())
        j = self.job()
        os.unlink(S.tx_path(TID))
        ed_jobs.run_job(j)
        self.assertEqual(j["state"], "error")
        self.assertFalse(os.path.exists(Y.ytcap_path(TID)))

    def test_auto_ytcap(self):
        """設定 autoYtcap(既定オフ): 文字起こしの終わりのフック。元の配信が分からない・評価用は黙って飛ばす"""
        self.put_doc(doc())
        job = {"warnings": []}
        Y.ytcap_after_transcribe(job, {"autoYtcap": False}, TID)
        Y.ytcap_after_transcribe(job, {"autoYtcap": True, "evalSet": True}, TID)
        self.assertEqual([j for j in ed_jobs._jobs.values() if j.get("kind") == "ytcap" and j.get("tid") == TID], [])
        Y.ytcap_after_transcribe(job, {"autoYtcap": True}, TID)
        q = [j for j in ed_jobs._jobs.values() if j.get("kind") == "ytcap" and j.get("tid") == TID and j["state"] == "queued"]
        self.mine.update(j["id"] for j in q)
        self.assertEqual((len(q), job["warnings"]), (1, []))
        self.assertEqual(q[0]["spec"]["videoId"], VID)
        for j in q:
            j["state"] = "cancelled"
        self.put_doc(doc(clip=None))   # 元の配信が分からない: 黙って飛ばす(注意も出さない)
        Y.ytcap_after_transcribe(job, {"autoYtcap": True}, TID)
        self.assertEqual(job["warnings"], [])
        with mock.patch.object(Y, "ytcap_spec", side_effect=S.ApiError("busy", "最中", 409)):   # それ以外の理由は注意に
            Y.ytcap_after_transcribe(job, {"autoYtcap": True}, TID)
        self.assertEqual(len(job["warnings"]), 1)
        # validate_job: 要求の autoYtcap → 無ければ保存した設定・評価用は常に偽
        src = os.path.join(self.files, "v.wav")
        import wave
        with wave.open(src, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * 16000 * 2)
        self.assertFalse(ed_jobs.validate_job({"sourcePath": src, "model": "small"})["autoYtcap"])
        write_json(ed_state.SETTINGS, {"autoYtcap": True})
        self.assertTrue(ed_jobs.validate_job({"sourcePath": src, "model": "small"})["autoYtcap"])
        self.assertFalse(ed_jobs.validate_job({"sourcePath": src, "model": "small", "autoYtcap": False})["autoYtcap"])
        self.assertFalse(ed_jobs.validate_job({"sourcePath": src, "model": "small", "evalSet": True})["autoYtcap"])


if __name__ == "__main__":
    unittest.main()
