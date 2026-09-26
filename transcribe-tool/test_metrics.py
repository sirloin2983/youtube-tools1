#!/usr/bin/env python3
"""v0.7.0 の追加分(校正済み・CER測定・英字フラグ・A/B比較・校正済みの書き出し)のテスト。

    python3 test_metrics.py          # 単体テスト + 疑似モードでの通し試験(ffmpeg が必要。数十秒)

実際の音声認識は使わない(疑似モード TRANSCRIBE_BACKEND=fake)。
"""
import io
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import queue
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように
sys.path.insert(0, HERE)
import serve as S  # noqa: E402


def lev(a, b):
    """参照実装(普通の編集距離)。"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def seg(i, a, b, text, proofed=False):
    d = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": ""}
    if proofed:
        d["proofed"] = True
    return d


class TestPure(unittest.TestCase):
    def test_norm_cer(self):
        self.assertEqual(S.norm_cer("ホロ・ライブ！ Ｔｅｓｔ、ー"), "ホロライブtestー")
        self.assertEqual(S.norm_cer(" 、。 "), "")

    def test_lev_counts_matches_reference(self):
        self.assertEqual(S.lev_counts("あいうえお", "あいくえおか"), (1, 0, 1))
        self.assertEqual(S.lev_counts("", "abc"), (0, 0, 3))
        self.assertEqual(S.lev_counts("abc", ""), (0, 3, 0))
        rnd = random.Random(1)
        for _ in range(300):
            a = "".join(rnd.choice("あいう") for _ in range(rnd.randint(0, 12)))
            b = "".join(rnd.choice("あいうえ") for _ in range(rnd.randint(0, 12)))
            s, d, i = S.lev_counts(a, b)
            self.assertEqual(s + d + i, lev(a, b), (a, b))
            self.assertEqual(len(b), len(a) - d + i, (a, b))   # 正解 - 脱落 + 挿入 = 機械の長さ

    def test_lev_counts_approx_fallback(self):
        old = S.MAX_LEV_CELLS
        S.MAX_LEV_CELLS = 10
        try:
            s, d, i = S.lev_counts("あいうえおかきくけこ", "あいうえおXかきくけこ")
            self.assertEqual((s, d, i), (0, 0, 1))
        finally:
            S.MAX_LEV_CELLS = old

    def test_latin_suspect(self):
        yes = ["ヴァ、ゲ son w見て。い", "な?ん?honeyit's upすでにそこに誰も作っちゃってる... alsoそうだよ", "honey it's up"]
        no = ["ガチでApexやってる", "GGありがとう", "ホロライブのトワ様", "草wwwwwwwwww", "OKじゃあいこう", "ワンちゃんあるかもwww", ""]
        for t in yes:
            self.assertTrue(S.latin_suspect(t), t)
        for t in no:
            self.assertFalse(S.latin_suspect(t), t)
        self.assertTrue(S.latin_suspect("今日はMinecraftやります"))
        self.assertFalse(S.latin_suspect("今日はMinecraftやります", ["Minecraft"]))   # 用語集にある語は数えない

    def test_make_flags_latin_only_for_ja(self):
        sg = {"text": "honey it's up", "start": 0, "end": 2, "avg_logprob": -0.2, "no_speech_prob": 0.1, "compression_ratio": 1.0}
        self.assertEqual(S.make_flags(sg, []), "")                              # 言語を渡さなければ従来どおり(印なし)
        self.assertEqual(S.make_flags(sg, [], "en"), "")
        self.assertIn("英字が多い", S.make_flags(sg, [], "ja"))
        self.assertEqual(S.make_flags(sg, [], "ja", ["honey", "it's", "up"]), "")

    def test_sanitize_keeps_proofed_only_when_true(self):
        obj = {"speakers": [], "segments": [
            {"id": "a", "start": 0, "end": 1, "text": "x", "proofed": True},
            {"id": "b", "start": 1, "end": 2, "text": "y", "proofed": "true"},
            {"id": "c", "start": 2, "end": 3, "text": "z", "proofed": False},
            {"id": "d", "start": 3, "end": 4, "text": "w"}]}
        out = S.sanitize_transcript(obj, {})["segments"]
        self.assertEqual([("proofed" in g) for g in out], [True, False, False, False])

    def test_doc_metrics_proofed(self):
        orig = [{"start": 0, "end": 2, "text": "トゥー様は後合流"}, {"start": 2, "end": 4, "text": "こんにちは"},
                {"start": 4, "end": 5, "text": "ざわざわ"}, {"start": 5, "end": 6, "text": "続き"},
                {"start": 6, "end": 8, "text": "未確認の行"}, {"start": 20, "end": 22, "text": "範囲の外の幻覚"}]
        segs = [seg(1, 0, 2, "トワ様は後合流", True), seg(2, 2, 4, "こんにちは", True),
                # 4-5 の行は人が消した(機械だけにある) / 6-8 は未校正 / 20-22 も消したが、校正した範囲の外
                seg(3, 5, 6, "続き", True), seg(4, 6, 8, "未確認の行を直した", False)]
        m = S.doc_metrics({"original": orig, "segments": segs})
        self.assertEqual(m["basis"], "proofed")
        # 数える: 1行目(置換1・挿入1: トゥー→トワ) + 2行目・4行目(誤りなし) + 消した行(挿入4)。未校正の6-8と、範囲外の20-22は数えない
        self.assertEqual((m["sub"], m["del"], m["ins"]), (1, 0, 5))
        self.assertEqual(m["refChars"], len(S.norm_cer("トワ様は後合流こんにちは続き")))
        self.assertEqual(m["machineOnly"], 1)
        self.assertEqual(S.acc_finish(m)["cer"], round(6 / m["refChars"], 4))

    def test_doc_metrics_added_line_is_deletion(self):
        orig = [{"start": 0, "end": 2, "text": "あいう"}]
        segs = [seg(1, 0, 2, "あいう", True), seg(2, 10, 12, "人が足した行", True)]
        m = S.doc_metrics({"original": orig, "segments": segs})
        self.assertEqual((m["sub"], m["del"], m["ins"]), (0, len(S.norm_cer("人が足した行")), 0))

    def test_doc_metrics_none_cases(self):
        orig = [{"start": 0, "end": 2, "text": "あ"}]
        self.assertIsNone(S.doc_metrics({"original": orig, "segments": [seg(1, 0, 2, "い")]}))                       # 校正済みなし
        self.assertIsNone(S.doc_metrics({"original": [], "segments": [seg(1, 0, 2, "い", True)]}))                 # 機械の出力なし
        self.assertIsNone(S.doc_metrics({"original": orig, "segments": [seg(1, 0, 2, "あ")]}, legacy=True))        # 旧データで修正なし
        m = S.doc_metrics({"original": orig, "segments": [seg(1, 0, 2, "い")]}, legacy=True)
        self.assertEqual((m["basis"], m["sub"]), ("legacy", 1))

    def test_terms_hit_and_extra(self):
        orig = [{"start": 0, "end": 2, "text": "トゥー様とホロライブ"}, {"start": 2, "end": 4, "text": "陽キャだよ"}]
        segs = [seg(1, 0, 2, "トワ様とホロライブ", True), seg(2, 2, 4, "陽キャだよ", True)]
        m = S.doc_metrics({"original": orig, "segments": segs}, terms=["トワ", "ホロライブ", "陽キャ"])
        self.assertEqual((m["termRef"], m["termHit"], m["termExtra"]), (3, 2, 0))
        # 正解に無い用語が機械に出た(用語集が誘発した語尾挿入の疑い)
        orig2 = [{"start": 0, "end": 2, "text": "ちゃうわけホロライブ"}]
        segs2 = [seg(1, 0, 2, "ちゃうわけ", True)]
        m2 = S.doc_metrics({"original": orig2, "segments": segs2}, terms=["ホロライブ"])
        self.assertEqual((m2["termRef"], m2["termHit"], m2["termExtra"]), (0, 0, 1))

    def test_learn_groups_proofed_scope(self):
        orig = [{"start": 0, "end": 2, "text": "トゥー様"}, {"start": 2, "end": 4, "text": "そのまま"}]
        segs = [seg(1, 0, 2, "トワ様", True), seg(2, 2, 4, "そのまま", True), seg(3, 4, 6, "未確認", False)]
        gs = S.learn_groups({"original": orig, "segments": segs}, "proofed")
        self.assertEqual([(g["text"], g["changed"]) for g in gs], [("トワ様", True), ("そのまま", False)])
        self.assertEqual([g["text"] for g in S.learn_groups({"original": orig, "segments": segs})], ["トワ様"])       # 既定は従来どおり(直した行だけ)
        # 機械の出力が無い文字起こしでも、校正済みの行は使える
        gs2 = S.learn_groups({"segments": segs}, "proofed")
        self.assertEqual([(g["original"], g["text"]) for g in gs2], [("", "トワ様"), ("", "そのまま")])


class TestStore(unittest.TestCase):
    """校正済みの印が、再認識で外れること。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.tmp, os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retranscribe_clears_proofed(self):
        tid = "0123456789ab"
        doc = {"id": tid, "original": [{"start": 0, "end": 2, "text": "a"}, {"start": 2, "end": 4, "text": "b"}],
               "segments": [seg(1, 0, 2, "a", True), seg(2, 2, 4, "b", True)]}
        with open(S.tx_path(tid), "w", encoding="utf-8") as f:
            json.dump(doc, f)
        S.apply_retranscribe({"tid": tid, "model": "large-v3", "autoDict": False}, {"s1": ("A", "")})
        d = S.read_transcript(tid)
        self.assertNotIn("proofed", d["segments"][0])   # 機械が書き換えた行は外れる
        self.assertTrue(d["segments"][1].get("proofed"))  # 触っていない行はそのまま
        self.assertEqual(d["segments"][0]["text"], "A")

    def test_hist_snapshot_interval_and_cap(self):
        tid = "0123456789ab"
        with open(S.tx_path(tid), "w", encoding="utf-8") as f:
            json.dump({"segments": [], "updatedAt": 1}, f)
        self.assertIsNotNone(S.hist_snapshot(tid))
        self.assertIsNone(S.hist_snapshot(tid))                      # 10分以内は増やさない
        old = S.HIST_INTERVAL
        S.HIST_INTERVAL = 0
        try:
            self.assertIsNotNone(S.hist_snapshot(tid))               # 間隔が過ぎていれば残す
        finally:
            S.HIST_INTERVAL = old
        for _ in range(S.HIST_KEEP + 5):
            S.hist_snapshot(tid, force=True)
        st = S.hist_stamps(tid)
        self.assertEqual(len(st), S.HIST_KEEP)                       # 古いものから消える
        self.assertEqual(st, sorted(set(st)))                        # 同じ時刻でも上書きしない
        with self.assertRaises(S.ApiError):
            S.restore_history(tid, 12345)


class TestLearnBoundary(unittest.TestCase):
    """辞書の学習: 語の途中だけの断片にならない / 単語の途中には当てない。"""

    def test_events_widen_to_whole_run(self):
        doc = {"original": [{"start": 0, "end": 3, "text": "トーイ様は後合流するんで"}, {"start": 3, "end": 6, "text": "トルカパパ"}],
               "segments": [seg(1, 0, 3, "トワ様は後合流するんで", True), seg(2, 3, 6, "ポルカパパ", True)]}
        ev = [(w, r) for w, r, _c, _l, _r in S.learn_events(doc)]
        self.assertIn(("トーイ", "トワ"), ev)             # 「ーイ→ワ」の断片ではなく、カタカナの語の全体
        self.assertIn(("トルカパパ", "ポルカパパ"), ev)
        self.assertNotIn(("ーイ", "ワ"), ev)
        # 漢字の並びも全体に広げる
        doc2 = {"original": [{"start": 0, "end": 3, "text": "反省魂だなぁ"}], "segments": [seg(1, 0, 3, "配信魂だなぁ", True)]}
        self.assertEqual([(w, r) for w, r, _c, _l, _r in S.learn_events(doc2)], [("反省魂", "配信魂")])

    def test_spans_do_not_hit_inside_a_word(self):
        self.assertEqual(S._spans("トルコとトル様", "トル", "ポル"), [4])         # 「トルコ」の中には当てない。「トル様」は語の切れ目
        self.assertEqual(S._spans("ABCD abc", "abc", "x"), [5])
        self.assertEqual(S._spans("あんきも", "きも", "肝"), [2])                 # ひらがなは切れ目の判定に使わない(従来どおり)

    def test_manual_dict_word_bound_syntax(self):
        pairs = S.parse_replacements("|トル|=>ポル\nふぶき=>フブキ")
        self.assertEqual(S.apply_replacements("トルコとトル様、ふぶき", pairs), ("トルコとポル様、フブキ", 2))
        # 縦棒なしは従来どおり(全部置換)
        self.assertEqual(S.apply_replacements("トルコとトル様", S.parse_replacements("トル=>ポル")), ("ポルコとポル様", 2))
        # 登録済みの判定は、縦棒を外した形で(学習候補に同じものが残らない)
        self.assertEqual(S.wb_split("|ab|"), ("ab", True))
        self.assertEqual(S.wb_split("||"), ("||", False))


class TestSplitAndRobust(unittest.TestCase):
    def _w(self, items):
        return [(a, b, t) for a, b, t in items]

    def test_split_segment(self):
        # 声のない所まで伸びた行(0〜20秒で、実際に話しているのは 3.0〜4.0 秒): 行の時刻が単語にそろう
        s = {"start": 0.0, "end": 20.0, "text": "おっけ!", "words": self._w([(3.0, 3.5, "おっ"), (3.5, 4.0, "け!")]), "avg_logprob": -0.3}
        out = S.split_segment(s)
        self.assertEqual([(o["start"], o["end"], o["text"]) for o in out], [(3.0, 4.0, "おっけ!")])
        self.assertEqual(out[0]["avg_logprob"], -0.3)     # 他の項目は引き継ぐ
        self.assertNotIn("words", out[0])
        # 間が1秒以上あいた所で分かれる
        s = {"start": 0.0, "end": 9.0, "text": "こんにちはありがとう", "words": self._w([(0.0, 0.8, "こんにちは"), (5.0, 5.9, "ありがとう")])}
        self.assertEqual([o["text"] for o in S.split_segment(s)], ["こんにちは", "ありがとう"])
        # 長すぎる行(8秒超)は句点のあとなど区切りのよい所で分かれる。続けて話していても分かれる
        ws = [(i * 0.5, i * 0.5 + 0.45, "あ" * 2 + ("。" if i == 9 else "")) for i in range(20)]      # 10秒・40文字超
        s = {"start": 0.0, "end": 10.0, "text": "".join(t for _a, _b, t in ws), "words": ws}
        out = S.split_segment(s)
        self.assertGreaterEqual(len(out), 2)
        self.assertEqual("".join(o["text"] for o in out), s["text"])          # 文字は増えも減りもしない
        self.assertTrue(all(o["end"] - o["start"] <= S.SPLIT_SEC + 0.01 for o in out))
        self.assertEqual(out[0]["text"].endswith("。"), True)                  # 句点のあとで切れる
        # 単語の並びと文章が合わない・単語が無い → 何もしない
        s = {"start": 0.0, "end": 5.0, "text": "違う文章", "words": self._w([(0.0, 1.0, "こんにちは")])}
        self.assertEqual(S.split_segment(s), [s])
        s = {"start": 0.0, "end": 5.0, "text": "単語なし"}
        self.assertEqual(S.split_segment(s), [s])

    def test_expand_and_kwargs(self):
        gen = iter([{"start": 0.0, "end": 9.0, "text": "あいう", "words": [(0.0, 0.5, "あ"), (6.0, 6.5, "いう")]}])
        self.assertEqual(len(list(S.expand_segments(gen, {"wordSplit": True}))), 2)
        gen = iter([{"start": 0.0, "end": 9.0, "text": "あいう", "words": [(0.0, 0.5, "あ"), (6.0, 6.5, "いう")]}])
        self.assertEqual(len(list(S.expand_segments(gen, {"wordSplit": False}))), 1)     # 無効なら従来どおり
        self.assertTrue(S.whisper_kwargs({"language": "ja", "beam": 5, "model": "large-v3", "glossary": [], "wordSplit": True}).get("word_timestamps"))
        self.assertNotIn("word_timestamps", S.whisper_kwargs({"language": "ja", "beam": 5, "model": "large-v3", "glossary": []}))

    def test_strip_punct(self):
        self.assertEqual(S.strip_punct("こんにちは、元気?今日は晴れです。すごい!"), "こんにちは元気今日は晴れですすごい")
        self.assertEqual(S.strip_punct("かっこ(括弧)は残る"), "かっこ(括弧)は残る")   # 、。？！と半角?!以外は対象外
        self.assertEqual(S.strip_punct(""), "")

    def test_expand_segments_strip_punct(self):
        """句読点の除去(stripPunct)は既定でオン。単語分割の区切り判断には除去前の句読点を使うので、分け方(行数・時刻)は変わらない。"""
        ws = [(i * 0.5, i * 0.5 + 0.45, "あ" * 2 + ("。" if i == 9 else "")) for i in range(20)]   # test_split_segment と同じ素材(10秒・40字超)
        text = "".join(t for _a, _b, t in ws)
        mk_gen = lambda: iter([{"start": 0.0, "end": 10.0, "text": text, "words": ws}])
        with_strip = list(S.expand_segments(mk_gen(), {"wordSplit": True, "stripPunct": True}))
        without_strip = list(S.expand_segments(mk_gen(), {"wordSplit": True, "stripPunct": False}))
        self.assertGreaterEqual(len(with_strip), 2)
        self.assertEqual([(o["start"], o["end"]) for o in with_strip], [(o["start"], o["end"]) for o in without_strip])   # 分け方は不変
        self.assertNotIn("。", "".join(o["text"] for o in with_strip))    # オンなら句点が消える
        self.assertIn("。", "".join(o["text"] for o in without_strip))    # オフなら残る
        default_spec = list(S.expand_segments(mk_gen(), {"wordSplit": True}))   # spec に無いときはオン扱い(既定)
        self.assertEqual([o["text"] for o in default_spec], [o["text"] for o in with_strip])

    def test_finish_range_lines_drops_punct_only_line(self):
        """句読点だけの行は、除去すると空文字になるので捨てられる。"""
        spec = {"range": [0.0, 10.0], "language": "ja", "glossary": [], "wordSplit": False, "stripPunct": True}
        raw = [{"start": 1.0, "end": 2.0, "text": "。", "avg_logprob": -0.3}, {"start": 3.0, "end": 4.0, "text": "元気?", "avg_logprob": -0.3}]
        out = S.finish_range_lines(raw, spec, 0.0)
        self.assertEqual([o["raw"] for o in out], ["元気"])

    def test_model_cache_keeps_one(self):
        import types
        made = []

        class FakeModel:
            def __init__(self, name, device=None, compute_type=None):
                made.append(name)

        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = FakeModel
        old = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = fw
        S._models.clear()
        try:
            job = {"phase": ""}
            m1, _ = S._load_model_local("large-v3", job, "cpu")   # 認識ワーカーの中で動く本体
            self.assertIs(S._load_model_local("large-v3", job, "cpu")[0], m1)     # 同じモデルは使い回す
            S._load_model_local("large-v3-turbo", job, "cpu")
            self.assertEqual(len(S._models), 1)                            # 別のモデルを読み込んだら、前のモデルは手放す
            self.assertEqual(list(S._models)[0][0], "large-v3-turbo")
            self.assertEqual(made, ["large-v3", "large-v3-turbo"])
        finally:
            S._models.clear()
            if old is None:
                del sys.modules["faster_whisper"]
            else:
                sys.modules["faster_whisper"] = old

    def test_worker_survives_and_marks(self):
        tmp = tempfile.mkdtemp()
        old_mark, old_run = S.RUN_MARK, S.run_job
        S.RUN_MARK = os.path.join(tmp, ".running.json")
        try:
            S.write_mark({"id": "j1", "kind": "transcribe", "model": "m", "title": "t"})
            prev = S.check_previous_run()
            self.assertEqual(prev["job"]["id"], "j1")                       # 印が残っていれば「前回は異常終了」と分かる
            S.clear_mark()
            self.assertIsNone(S.check_previous_run())

            def boom(job):
                raise ValueError("boom")
            S.run_job = boom
            job = {"id": "jx", "state": "queued", "cancel": False, "spec": {"model": "m", "title": "t"}, "kind": "transcribe"}
            S._jobs["jx"] = job
            try:
                S.work_one("jx")                                            # 例外でもワーカー(の1回分)は落ちず、ジョブが失敗になる
            finally:
                S._jobs.pop("jx", None)
            self.assertEqual(job["state"], "error")
            self.assertIn("boom", job["error"])
            self.assertIsNone(S._run_state["job"])                          # 終わったら実行中の印は消える
        finally:
            S.RUN_MARK, S.run_job = old_mark, old_run
            shutil.rmtree(tmp, ignore_errors=True)

    def _drain_queue(self):
        while True:
            try:
                S._queue.get_nowait()
            except queue.Empty:
                return

    def test_diarize_overtakes_queued_transcribe(self):
        """話者判別(diarize)は、待機列に並んでいる文字起こし(transcribe)より先に取り出される。
        実行中のジョブを中断するわけではなく、待機列の中の順序だけを入れ替える(同じ種類どうしの順番は変えない)。"""
        old_jobs, old_order = dict(S._jobs), list(S._order)
        self._drain_queue()
        S._jobs.clear()
        S._order.clear()
        try:
            j1 = S.add_job({"title": "t1"}, "transcribe")
            j2 = S.add_job({"title": "t2"}, "transcribe")
            j3 = S.add_job({"title": "d1", "tid": "docabc"}, "diarize")
            j4 = S.add_job({"title": "t3"}, "transcribe")
            picked = [S._queue.get_nowait()[2] for _ in range(4)]
            self.assertEqual(picked, [j3["id"], j1["id"], j2["id"], j4["id"]])
        finally:
            self._drain_queue()
            S._jobs.clear()
            S._jobs.update(old_jobs)
            S._order.clear()
            S._order.extend(old_order)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        for n in ("serve.py", "index.html", "app.js", "cut.js", "pack-tab.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):
            shutil.copy(os.path.join(HERE, n), cls.tmp)
        for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
            p = os.path.join(HERE, n)
            if os.path.exists(p):
                shutil.copy(p, cls.tmp)
        cls.wav = os.path.join(cls.tmp, "sample.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=24", cls.wav], check=True)
        with open(os.path.join(cls.tmp, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"glossary": "ホロライブ\nトワ", "replacements": "よっきゃ=>陽キャ"}, f)
        cls.port = free_port()
        env = dict(os.environ, TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.01", YTT_RUNTIME_DIR=os.path.join(cls.tmp, ".runtime"))
        cls.proc = subprocess.Popen([sys.executable, os.path.join(cls.tmp, "serve.py"), str(cls.port), "--no-open"], cwd=cls.tmp, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                cls.call("GET", "/api/ping")
                break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def call(cls, method, path, body=None, raw=False):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (cls.port, path), method=method,
                                     data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            return {"_status": e.code, **json.loads(e.read() or b"{}")}

    def wait_job(self, jid, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            j = next((x for x in self.call("GET", "/api/jobs")["jobs"] if x["id"] == jid), None)
            if j and j["state"] in ("done", "error", "cancelled"):
                return j
            time.sleep(0.1)
        self.fail("ジョブが終わりません")

    def make_doc(self):
        j = self.call("POST", "/api/transcribe", {"sourcePath": self.wav, "model": "small", "language": "ja", "glossary": "ホロライブ\nトワ", "autoGloss": False})
        j = self.wait_job(j["id"])
        self.assertEqual(j["state"], "done", j)
        return self.call("GET", "/api/transcript?id=" + j["tid"])

    def test_end_to_end(self):
        doc = self.make_doc()
        tid, segs = doc["id"], doc["segments"]
        self.assertGreaterEqual(len(segs), 4)
        # 何も校正していない → 測定は空
        m = self.call("GET", "/api/metrics")
        self.assertEqual(m["overall"]["groups"], 0)
        self.assertEqual(m["proofedLines"], 0)
        # 校正: 1行目は人が直して校正済み、2〜3行目は直さず校正済み、4行目以降は未校正
        segs[0]["text"] = "トワ様のテスト"
        for i in (0, 1, 2):
            segs[i]["proofed"] = True
        r = self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [], "segments": segs})
        self.assertTrue(r["ok"])
        saved = self.call("GET", "/api/transcript?id=" + tid)
        self.assertEqual([bool(g.get("proofed")) for g in saved["segments"][:4]], [True, True, True, False])
        m = self.call("GET", "/api/metrics?id=" + tid)
        o = m["overall"]
        self.assertEqual(m["proofedLines"], 3)
        self.assertEqual(o["groups"], 3)
        self.assertGreater(o["cer"], 0)
        self.assertEqual(o["changed"], 1)
        self.assertEqual(m["byConfig"][0]["config"], "small / 用語集あり")
        # 全件でも同じ(1件しかない)
        self.assertEqual(self.call("GET", "/api/metrics")["overall"]["errs"], o["errs"])
        # 不正なID
        self.assertEqual(self.call("GET", "/api/metrics?id=../x").get("_status"), 404)

        # A/B 比較: 用語集あり(疑似では完全一致+ときどき用語が余計に出る)と、なし(最後の1文字が抜ける)
        v = [{"model": "small", "glossary": True}, {"model": "small", "glossary": False}]
        j = self.call("POST", "/api/abtest", {"tid": tid, "variants": v, "language": "ja", "glossary": "ホロライブ"})
        self.assertEqual(j["kind"], "abtest")
        self.assertIsNone(j["tid"])
        j = self.wait_job(j["id"])
        self.assertEqual(j["state"], "done", j)
        ev = self.call("GET", "/api/evals?id=" + tid)["items"]
        self.assertEqual(len(ev), 1)
        va, vb = ev[0]["variants"]
        self.assertEqual((va["label"], vb["label"]), ("small / 用語集あり", "small / 用語集なし"))
        self.assertEqual(ev[0]["lines"], 3)
        # 疑似の出力: 用語集あり=完全一致+3行目に用語「ホロライブ」を余計に出す / なし=各行の最後の1文字が抜ける
        self.assertEqual((va["sub"], va["del"], va["ins"]), (0, 0, len("ホロライブ")))
        self.assertEqual((vb["sub"], vb["del"], vb["ins"]), (0, 3, 0))
        self.assertEqual((va["termExtra"], vb["termExtra"]), (1, 0))
        self.assertGreater(va["cer"], 0)
        self.assertGreaterEqual(va["cerDict"], 0)
        self.assertEqual(self.call("GET", "/api/eval?id=" + ev[0]["id"])["id"], ev[0]["id"])
        # 設定別の用語集: 空欄=共通 / 書くとその設定だけその語(自動追加なし) / なし
        v3 = [{"model": "small", "glossary": True}, {"model": "small", "glossary": True, "terms": "ぺこら、マリン\nルイ"},
              {"model": "small", "glossary": True, "terms": "ぺこら,マリン,ルイ"}, {"model": "small", "glossary": False, "terms": "無視される"}]
        j = self.wait_job(self.call("POST", "/api/abtest", {"tid": tid, "variants": v3, "language": "ja", "glossary": "ホロライブ"})["id"])
        self.assertEqual(j["state"], "done", j)
        ev3 = self.call("GET", "/api/evals?id=" + tid)["items"][0]["variants"]
        self.assertEqual(len(ev3), 3)   # 同じ内容の設定は1つにまとめる
        self.assertEqual(ev3[0]["label"], "small / 用語集あり")
        self.assertEqual(ev3[1]["label"], "small / 用語集独自3語(ぺこら、マリン…)")
        self.assertEqual(ev3[1]["terms"], ["ぺこら", "マリン", "ルイ"])
        self.assertEqual((ev3[0]["ins"], ev3[1]["ins"]), (len("ホロライブ"), len("ぺこら")))
        self.assertEqual((ev3[2]["label"], ev3[2]["terms"], ev3[2]["del"]), ("small / 用語集なし", [], 3))
        # ホロライブの名簿: 読める・重複や空が無い・所属IDが一意
        r = self.call("GET", "/api/roster")
        ids = [g["id"] for g in r["groups"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 15)
        for g in r["groups"]:
            self.assertTrue(g["names"] and all(isinstance(n, str) and n.strip() == n and n for n in g["names"]), g["id"])
            self.assertEqual(len(g["names"]), len(set(g["names"])), g["id"])
        names = {n for g in r["groups"] for n in g["names"]}
        self.assertTrue({"兎田ぺこら", "宝鐘マリン", "AZKi", "熱千めら"} <= names)
        self.assertRegex(r["asOf"], r"^\d{4}-\d\d-\d\d$")
        # 校正済みの行が無い文書には比較できない
        other = self.make_doc()
        self.assertEqual(self.call("POST", "/api/abtest", {"tid": other["id"], "variants": v}).get("error"), "empty")
        self.assertEqual(self.call("POST", "/api/abtest", {"tid": tid, "variants": []}).get("error"), "empty")
        self.assertEqual(self.call("POST", "/api/abtest", {"tid": tid, "variants": [{"model": "../x"}]}).get("error"), "bad_model")

        # 書き出し: 校正済みの行すべて(直していない行も入る) / 従来どおり直した行だけ
        z = zipfile.ZipFile(io.BytesIO(self.call("POST", "/api/export-corrections", {"tid": tid, "audio": False, "scope": "proofed"}, raw=True)))
        rows = [json.loads(x) for x in z.read("corrections.jsonl").decode().splitlines()]
        self.assertEqual([(r["changed"], r["proofed"]) for r in rows], [(True, True), (False, True), (False, True)])
        self.assertEqual(rows[0]["text"], "トワ様のテスト")
        z = zipfile.ZipFile(io.BytesIO(self.call("POST", "/api/export-corrections", {"tid": tid, "audio": False}, raw=True)))
        rows = [json.loads(x) for x in z.read("corrections.jsonl").decode().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("changed", rows[0])

    def test_fake_flags_unchanged(self):
        """疑似の文字起こし(「テスト文N」)には、英字の要確認が付かない(誤検出しない)。"""
        doc = self.make_doc()
        self.assertFalse(any("英字" in (g.get("flag") or "") for g in doc["segments"]))

    def test_history_and_conflict(self):
        doc = self.make_doc()
        tid, segs = doc["id"], doc["segments"]
        put = lambda body: self.call("PUT", "/api/transcript?id=" + tid, dict({"title": doc["title"], "speakers": [], "segments": segs}, **body))
        self.assertEqual(self.call("GET", "/api/history?id=" + tid)["items"], [])
        base0 = doc["updatedAt"]
        segs[0]["text"] = "一回目"
        r1 = put({"baseUpdatedAt": base0})
        self.assertTrue(r1["ok"])
        h = self.call("GET", "/api/history?id=" + tid)["items"]
        self.assertEqual(len(h), 1)                          # 最初の保存で、保存前の状態が1つ残る
        segs[0]["text"] = "二回目"
        r2 = put({"baseUpdatedAt": r1["updatedAt"]})
        self.assertTrue(r2["ok"])
        self.assertEqual(len(self.call("GET", "/api/history?id=" + tid)["items"]), 1)   # 10分以内なので増えない
        # 古い版を土台にした保存は 409、force なら上書きできる
        segs[0]["text"] = "古い画面から"
        self.assertEqual(put({"baseUpdatedAt": base0}).get("_status"), 409)
        self.assertEqual(self.call("GET", "/api/transcript?id=" + tid)["segments"][0]["text"], "二回目")
        self.assertTrue(put({"baseUpdatedAt": base0, "force": True})["ok"])
        # 履歴から戻す: 戻す前の状態も履歴に残る
        ts = h[0]["ts"]
        r = self.call("POST", "/api/restore", {"id": tid, "ts": ts})
        self.assertTrue(r["ok"])
        self.assertEqual(self.call("GET", "/api/transcript?id=" + tid)["segments"][0]["text"], "テスト文1")
        self.assertEqual(len(self.call("GET", "/api/history?id=" + tid)["items"]), 2)
        self.assertEqual(self.call("POST", "/api/restore", {"id": tid, "ts": 123}).get("_status"), 404)
        self.assertEqual(self.call("POST", "/api/restore", {"id": "../x", "ts": ts}).get("_status"), 404)
        self.assertEqual(self.call("GET", "/api/history?id=../x").get("_status"), 404)

    def test_tags_and_archive(self):
        doc = self.make_doc()
        tid, segs = doc["id"], doc["segments"]
        self.assertGreaterEqual(len(segs), 6)
        spk = [{"id": "S1", "name": "トワ", "color": "#2f62d6"}]
        segs[0]["text"] = "トワ様のテスト"
        segs[0]["speaker"] = "S1"
        for i in (0, 1, 2, 4):
            segs[i]["proofed"] = True
        segs[1]["tags"] = ["unclear", "bgm", "hack"]      # 決まった印だけ残る
        gone = segs.pop(3)                                 # 人が消した行(校正した範囲の中 → 負例)
        r = self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": spk, "segments": segs})
        self.assertTrue(r["ok"])
        saved = self.call("GET", "/api/transcript?id=" + tid)
        self.assertEqual(saved["segments"][1]["tags"], ["unclear", "bgm"])
        self.assertNotIn("tags", saved["segments"][0])
        # 「聞き取れない」の行は精度の測定に入らない(校正済み4行のうち3行 + 消した行1つ)
        m = self.call("GET", "/api/metrics?id=" + tid)
        self.assertEqual(m["overall"]["groups"], 4)

        self.assertEqual(self.call("GET", "/api/dataset")["totals"]["docs"], 0)
        self.assertEqual(self.call("POST", "/api/archive", {"tid": "../x"}).get("_status"), 400)
        self.assertEqual(self.call("POST", "/api/archive", {"tid": tid})["docs"], 1)
        end = time.time() + 60
        while time.time() < end and self.call("GET", "/api/dataset")["running"]:
            time.sleep(0.1)
        st = self.call("GET", "/api/dataset")
        self.assertEqual(st["errors"], [])
        t = st["totals"]
        self.assertEqual((t["docs"], t["positive"], t["negative"], t["unclear"]), (1, 3, 1, 1))
        self.assertEqual(st["speakers"], {"トワ": round(segs[0]["end"] - segs[0]["start"], 1), "(話者なし)": round(segs[2]["end"] - segs[2]["start"] + segs[3]["end"] - segs[3]["start"], 1)})
        self.assertGreater(t["audioBytes"], 1000)
        base = os.path.join(self.tmp, "dataset")
        self.assertTrue(os.path.isfile(os.path.join(base, "README.txt")))
        self.assertTrue(os.path.isfile(os.path.join(base, "settings-snapshot.json")))
        rows = [json.loads(x) for x in open(os.path.join(base, "index.jsonl"), encoding="utf-8").read().splitlines()]
        self.assertEqual(sorted((x["kind"], x["role"]) for x in rows), [("deleted", "negative"), ("line", "positive"), ("line", "positive"), ("line", "positive"), ("line", "unclear")])
        neg = next(x for x in rows if x["kind"] == "deleted")
        self.assertEqual((neg["text"], neg["original"]), ("", gone["text"]))
        self.assertEqual(next(x for x in rows if x["role"] == "unclear")["tags"], ["unclear", "bgm"])
        for x in rows:
            self.assertTrue(os.path.isfile(os.path.join(base, x["audio"])), x)
        self.assertTrue(os.path.isfile(os.path.join(base, "docs", tid, "full.flac")))
        first = json.loads(open(os.path.join(base, "docs", tid, "lines.jsonl"), encoding="utf-8").readline())
        self.assertEqual((first["text"], first["speakerName"], first["changed"]), ("トワ様のテスト", "トワ", True))
        self.assertTrue(first["original"].startswith("テスト文"))
        man = json.load(open(os.path.join(base, "docs", tid, "manifest.json"), encoding="utf-8"))
        self.assertEqual(man["newClips"], 5)
        # 2回目: 変わっていないので、音声は切り直さない。校正を外した行の音声は消える
        segs[2].pop("proofed")
        self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": spk, "segments": segs})
        self.call("POST", "/api/archive", {"tid": tid, "full": False})
        end = time.time() + 60
        while time.time() < end and self.call("GET", "/api/dataset")["running"]:
            time.sleep(0.1)
        man = json.load(open(os.path.join(base, "docs", tid, "manifest.json"), encoding="utf-8"))
        self.assertEqual(man["newClips"], 0)
        self.assertEqual(len(os.listdir(os.path.join(base, "docs", tid, "audio"))), 4)
        self.assertTrue(man["fullAudio"])   # 一度保管した全体の音声は、full=False でも消さない
        # 元のファイルが無くなっても、保管済みの音声は残り、エラーにならない
        os.rename(self.wav, self.wav + ".moved")
        try:
            segs[2]["proofed"] = True
            self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": spk, "segments": segs})
            self.call("POST", "/api/archive", {"tid": tid})
            end = time.time() + 60
            while time.time() < end and self.call("GET", "/api/dataset")["running"]:
                time.sleep(0.1)
            man = json.load(open(os.path.join(base, "docs", tid, "manifest.json"), encoding="utf-8"))
            self.assertIn("元のファイルが見つからない", man["note"])
            self.assertEqual(len(os.listdir(os.path.join(base, "docs", tid, "audio"))), 5)   # full.flac から切り出せた
        finally:
            os.rename(self.wav + ".moved", self.wav)


class TestRangeAndStudio(unittest.TestCase):
    def test_range_lines_clamped(self):
        # 範囲 10〜20 秒。チャンクは 9.7 秒から始まる想定(shift=9.7)。範囲の外にはみ出した分は切り、ほぼ範囲外の行は捨てる
        spec = {"range": [10.0, 20.0], "language": "ja", "glossary": [], "wordSplit": False}
        raw = [{"start": 0.0, "end": 1.0, "text": "頭", "avg_logprob": -0.3}, {"start": 9.0, "end": 10.6, "text": "尾", "avg_logprob": -0.3},
               {"start": 10.55, "end": 10.58, "text": "極小", "avg_logprob": -0.3}, {"start": 3.0, "end": 4.0, "text": "", "avg_logprob": -0.3}]
        out = S.finish_range_lines(raw, spec, 9.7)
        self.assertEqual([o["raw"] for o in out], ["頭", "尾"])
        self.assertEqual((out[0]["start"], out[0]["end"]), (10.0, 10.7))     # 開始は範囲の始まりまで切り上げる
        self.assertEqual(out[1]["end"], 20.0)

    def test_marker_tolerant(self):
        d = {"videos": [{"videoId": "a", "title": "T", "marks": [{"id": "1", "start": 1, "end": 5, "label": "L", "status": "adopted"}, {"start": 5, "end": 5}, "x"]},
                        {"videoId": "b", "title": "none", "marks": []}, {"id": "demo", "demo": True, "clips": [{"start": 0, "end": 1}]}]}
        vs = S.marker_videos(d)
        self.assertEqual([(v["videoId"], len(v["clips"]), v["clips"][0]["title"]) for v in vs], [("a", 1, "L")])
        old = {"videos": {"v": {"title": "旧", "clips": [{"id": "c", "start": 2, "end": 4, "title": "t", "status": "", "rating": 3}]}}}
        self.assertEqual(S.marker_videos(old)[0]["clips"][0]["rating"], 3)
        self.assertEqual(S.marker_videos([]), [])
        self.assertEqual(S.marker_videos({"videos": 5}), [])


class TestStudioExportDirectory(unittest.TestCase):
    def test_default_exports_are_available_to_marker_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "data.json")
            clip_path = os.path.join(tmp, "exports", "video", "clip.mp4")
            os.makedirs(os.path.dirname(clip_path))
            with open(clip_path, "wb") as f:
                f.write(b"test fixture")
            data = {"videos": {"abcdefghijk": {"kind": "youtube", "marks": [
                {"id": "m1", "start": 10, "end": 15, "status": "exported", "file": "video/clip.mp4"}]}}}
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            with patch.object(S, "STUDIO_DATA", data_path), \
                    patch.object(S, "MARKER_DATA", os.path.join(tmp, "missing.json")), \
                    patch.object(S, "transcribed_ranges", return_value=[]):
                result = S.read_marker()
            self.assertEqual(result["outDir"], os.path.join(tmp, "exports"))
            self.assertEqual(result["videos"][0]["clips"][0]["fileAbs"], os.path.realpath(clip_path))

    def test_explicit_settings_and_legacy_config_keep_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "data.json")
            settings = os.path.join(tmp, "settings.json")
            with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
                json.dump({"settings": {"outDir": "legacy"}}, f)
            self.assertEqual(S.studio_out_dir(data_path), os.path.join(tmp, "legacy"))
            custom = os.path.join(tmp, "custom")
            with open(settings, "w", encoding="utf-8") as f:
                json.dump({"outDir": custom}, f)
            self.assertEqual(S.studio_out_dir(data_path), custom)

    def test_empty_or_broken_settings_fall_back_to_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            for body in ('{}', '{"outDir": " "}', 'broken json'):
                with self.subTest(body=body):
                    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
                        f.write(body)
                    self.assertEqual(S.studio_out_dir(os.path.join(tmp, "data.json")), os.path.join(tmp, "exports"))


class TestMarkerDone(unittest.TestCase):
    def test_covered(self):
        ranges = [{"path": os.path.normcase(os.path.abspath("/a/full.mp4")), "start": 0.0, "end": 60.0, "whole": True, "tid": "w1"},
                  {"path": os.path.normcase(os.path.abspath("/a/vid.mp4")), "start": 100.0, "end": 130.0, "whole": False, "tid": "p1"}]
        self.assertEqual(S._covered(ranges, "/a/full.mp4", 5.0, 9.0), "w1")     # 全体を処理した文字起こしがあれば、どの範囲でも「済み」
        self.assertEqual(S._covered(ranges, "/a/vid.mp4", 101.0, 129.0), "p1")  # ほぼ重なる部分一致
        self.assertEqual(S._covered(ranges, "/a/vid.mp4", 100.0, 200.0), "")    # 重なりが9割未満なら「済み」にしない
        self.assertEqual(S._covered(ranges, "/a/other.mp4", 0.0, 10.0), "")     # 別ファイル


# 2026-09-24 の見直しで足したテスト(test_backend.py)も、従来のコマンド(python -m unittest test_metrics test_resolve_export)で一緒に走らせる
from test_backend import *  # noqa: E402,F401,F403
from test_worker import *  # noqa: E402,F401,F403   認識ワーカー(別プロセス)のテストも同じコマンドで
from test_edit import *  # noqa: E402,F401,F403   「編集」のサーバー側(編集の内容・open-video・peaks・intoDoc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
