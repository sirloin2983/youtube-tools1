# -*- coding: utf-8 -*-
"""① 文字起こしの行の後処理(clipjob.make_doc_rows = 整える postproc → 名前を外す B → 末尾の重複 C と別の読み A → 印・置換辞書 → 名簿の呼び名 D → LLM E)を、
編集の serve を読まずに 1 回通すテスト。

    py -3.12 -m unittest tests/pipeline/transcribe/test_postproc.py -v

認識の出力の見本(単語の時刻・続いている行・同じ文字の行・文字の少ない行・末尾の重複・決まり文句・行の中の繰り返し・同じ文の繰り返し・ヒントの語だけ・英字・
名簿の呼び名の聞き違い・置換辞書・空の行・長さの外・頭の「名前:」・自信の度合い)を、本物の後処理の入口に通して答えをまとめて確かめる。
認識・窓の読み(SenseVoice)・LLM は backend の口で決まった答えにする(本物の部品で通すのは test_fill_llm.py の TestRealParts)。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # 作業データは読み書きしないが、ほかのテストとそろえる
import json
import re
import sys
import unittest
from unittest import mock

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "src")   # tests -> transcribe -> pipeline -> src
sys.path.insert(0, SRC)
from pipeline.transcribe import backend, clipjob, fill, llm, postproc, recognize, roster  # noqa: E402
from ytt import studiodata, txbase, txtext, workdata  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # tests/(testkit)
import testkit  # noqa: E402

FILLED = "ラミーちゃんが来てくれてとても嬉しいです"   # 窓の読み(元の 5 字の 3 倍以上)。名簿の呼び名に近い所があっても後処理の行は LLM に選ばれない
DUR = 220.0
MEMBERS = [{"name": "雪花ラミィ", "aliases": ["ラミィ", "ラミィちゃん"], "common": []},
           {"name": "常闇トワ", "aliases": ["トワ", "トワ様"], "common": ["トワ"], "misrecognitions": [{"wrong": "トーイ", "right": "トワ"}]},
           {"name": "尾丸ポルカ", "aliases": ["ポルカ"], "common": []},
           {"name": "さくらみこ", "aliases": ["みこ", "みこち"], "common": ["みこ"]},
           {"name": "宝鐘マリン", "aliases": ["マリン", "船長"], "common": ["マリン", "船長"]}]


def W(a, b, text, **kw):
    return dict({"start": a, "end": b, "text": text, "avg_logprob": -0.3, "no_speech_prob": 0.1, "compression_ratio": 1.2}, **kw)


RAW = [   # 認識の出力(wav の秒)
    W(0.0, 1.0, "リリー:もう一回", words=[(0.0, 0.3, "リ"), (0.3, 0.6, "リー"), (0.6, 0.7, ":"), (0.7, 1.0, "もう一回")]),
    W(1.3, 2.0, "こんにちは。", avg_logprob=-0.123456, no_speech_prob=float("nan")),
    W(2.1, 2.5, "ああ"), W(2.6, 3.0, "ああ"), W(3.1, 3.5, "ああ"),
    W(5.0, 9.5, "テスト文1"), W(11.0, 15.5, "テスト文2"),
    W(17.0, 20.0, "今日はいい天気ですね"), W(20.0, 21.0, "いい天気ですね"), W(21.0, 22.0, "ですね"), W(22.0, 23.0, "いい天気ですね"),
    W(24.0, 26.0, "ご視聴ありがとうございました"), W(27.0, 29.0, "げんげんげんげんげん"),
    W(30.0, 30.8, "やばいやばい"), W(31.5, 32.0, "いくよ"), W(32.7, 33.5, "やばいやばい"), W(34.2, 35.0, "やばい、やばい"),
    W(36.0, 37.0, "スバル"), W(38.0, 40.0, "this is a random english line"),
    W(40.5, 42.0, "生き花ラミーちゃんが好き"), W(43.0, 45.0, "みこぢが来たよ"), W(45.5, 46.0, "白上フブキ"), W(46.2, 46.6, ""),
    W(47.0, 50.0, "あいうえお", words=[(47.0, 47.5, "あい"), (48.8, 49.4, "うえお")]),
    W(51.0, 52.0, "トーイ様こんばんは"), W(53.0, 54.0, "トルカ来た"), W(55.0, 56.0, "言ってみるか"), W(57.0, 58.0, "ラミィちゃん来た"),
    W(59.0, 61.0, "うわああああああああああああ"), W(62.0, 66.5, "テスト文3"),
    W(70.0, 72.0, "ご視聴いただきありがとうございました"), W(73.0, 75.0, "高評価よろしくお願いします!"), W(76.0, 78.0, "では次の動画でお会いしましょう"),
    W(79.0, 81.0, "みんな高評価よろしくお願いしますね今日も"), W(82.0, 84.0, "えっと字幕つけて"), W(85.0, 86.0, "♪～"), W(87.0, 88.0, "(音楽)"),
    W(89.0, 90.0, "【 BGM 】"), W(91.0, 92.0, "音楽いいね"), W(93.0, 94.0, "～"), W(95.0, 98.0, "ご覧いただきありがとうございました"),
    W(99.0, 108.0, "ご覧いただきありがとうございました"),
    W(109.0, 111.0, "なんかにもぱんぱんぱんぱんぱんぱん"), W(112.0, 114.0, "歩こう、歩こう、歩こう、歩こう、歩こう。"), W(115.0, 117.0, "はいはいはいはい"),
    W(118.0, 120.0, "あはははははははははは"),
    W(121.0, 121.5, "はい"), W(122.0, 122.5, "うん"), W(123.0, 123.5, "はい"), W(124.0, 124.5, "はい"), W(125.0, 125.5, "はい"),
    W(126.0, 128.0, "大空スバル、ホロライブ。"), W(129.0, 134.0, "スバル"), W(135.0, 145.0, "用語: スバル"), W(146.0, 147.0, "スバルだよ"), W(147.2, 147.5, "すばる!"), W(147.6, 147.8, "、。"),
    W(148.0, 149.0, " リリー： もう一回言って"), W(150.0, 151.0, "宝鐘マリン:ahoy"), W(152.0, 153.0, "マリン船長:ahoy"), W(154.0, 155.0, "マリンさん:ahoy"),
    W(156.0, 157.0, "結論:やらない"), W(158.0, 159.0, "12:30に集合"), W(160.0, 161.0, "リリー:!?"), W(162.0, 163.0, "とてもとても長いなまえです:はい"),
    W(164.0, 165.0, "Q:質問"),
    W(166.0, 167.0, "えーと", avg_logprob=-1.4, no_speech_prob=0.7, compression_ratio=2.5),
    W(168.0, 169.0, "アペやろう"), W(169.5, 169.9, "アペックス"),
] + [W(170.0 + i, 170.5 + i, "ラミーちゃん") for i in range(32)] + [
    W(218.5, 222.0, "最後"), W(225.0, 230.0, "外"),
]
EDITS = {"生き花ラミーちゃんが好き": [{"from": "ラミーちゃん", "to": "ラミィちゃん", "confidence": 0.95}, {"from": "好き", "to": "大嫌いだよね", "confidence": 0.9}],
         "トーイ様こんばんは": [{"from": "トーイ", "to": "トワ", "confidence": 0.9}, {"from": "こんばんは", "to": "ポルカ", "confidence": 0.9}],
         "トルカ来た": [{"from": "トルカ", "to": "ポルカ", "confidence": 0.2}, {"from": "無い", "to": "x", "confidence": 0.9}],
         "ラミーちゃん": [{"from": "ラミーちゃん", "to": "ラミィちゃん", "confidence": None}]}


class _Rich(backend.Backend):
    """認識 = RAW・窓の読み = 窓の場所で決まった答え・LLM = 直す行(→)で決まった答え(思考の札と形の違う案つき)"""
    name = "rich"

    def __init__(self):
        self.windows, self.asked = [], []

    def transcribe(self, job, spec, wav, total, real):
        return iter([dict(r) for r in RAW])

    def fill_reader(self, job, spec, wav, real):
        def read(s0, e0):
            if e0 - s0 > 30:   # D の全体の読み
                return [{"start": 43.2, "end": 45.0, "text": "みこちが来たよ"}]
            self.windows.append(round(s0, 1))
            if s0 < 6:
                return [{"start": s0 + 0.2, "end": e0 - 0.2, "text": FILLED}]
            if 10 < s0 < 12:
                return [{"start": s0, "end": e0, "text": "短い文です"}]                     # 3 倍に届かない
            if 60 < s0 < 63:
                return [{"start": 66.0, "end": 67.0, "text": "これは別の読みで埋めた長い文です"}]   # 元の行の時間に半分も入らない
            return []
        return read

    def llm_ask(self, job, spec, real):
        def ask(messages):
            self.asked.append(messages)
            row = re.search(r"^→ (.*)$", messages[1]["content"], re.M).group(1)
            return "<think>x</think>答え " + json.dumps({"edits": EDITS.get(row, []) + [{"from": 1}]}, ensure_ascii=False)
        return ask


class TestDocRowsRun(unittest.TestCase):
    def test_rich_sample_through_make_doc_rows(self):
        tmp = testkit.tempdir(self)
        path = os.path.join(tmp, "roster.json")
        testkit.write_json(path, {"groups": [], "members": MEMBERS})
        rich = _Rich()
        self.addCleanup(backend.set_selector, backend._selector[0])   # 前の選び方に戻す(REAL に固定しない)
        backend.set_selector(lambda: rich)
        for mod, name, value in ((roster, "ROSTER", path), (studiodata, "studio_stream", lambda vid: None),
                                 (recognize, "extract_audio", lambda job, spec, wav: None), (recognize._tools, "media_duration", lambda p: DUR)):
            self.enterContext(mock.patch.object(mod, name, value))
        spec = {"start": 0.0, "end": 0, "language": "ja", "glossary": ["ホロライブ", "大空スバル", "スバル"], "context": {"terms": []}, "stripNames": True,
                "autoFill": True, "autoLlm": True, "title": "雪花ラミィ・常闇トワ・尾丸ポルカの配信", "sourcePath": "E:/v.mp4", "wordSplit": True, "engine": "faster-whisper"}
        job = {"id": "j", "cancel": False}
        out = clipjob.make_doc_rows(job, spec, os.path.join(tmp, "a.wav"), [("白上", "白神"), ("|アペ|", "エペ")])
        segs = out["segs"]
        by = {}
        for g in segs:
            by.setdefault(g["text"], g)
        orig = {g["id"]: o for g, o in zip(segs, out["original"])}

        def at(text):
            g = by[text]
            return g["start"], g["end"], g["flag"], g.get("fill")
        REP, SAME, STOCK, LEAK, SPARSE = "繰り返しの可能性", "同じ文の繰り返し", "よくある誤認識の文", txbase.LEAK_FLAG, txtext.SPARSE_FLAG
        # 整える(postproc): 続いている行をつなぐ・句読点を除く・同じ文字の行をまとめる・単語の間で分ける・長さで切る・空の行と長さの外は捨てる
        self.assertEqual([(g["start"], g["end"], g["text"]) for g in segs[:3]], [(0.0, 1.3, "もう一回"), (1.3, 2.1, "こんにちは"), (2.1, 3.5, "ああああああ")])
        self.assertEqual(by["ああああああ"]["flag"], REP)
        self.assertEqual([(by[t]["start"], by[t]["end"]) for t in ("あい", "うえお", "最後")], [(47.0, 47.5), (48.8, 49.4), (218.5, 220.0)])
        self.assertNotIn("外", by)
        self.assertEqual(len(segs), 98)
        self.assertEqual((by["this is a random english line"]["end"], by["白神フブキ"]["end"]), (40.5, 46.2))   # すき間 0.5 秒まではつなぐ・空の行の始まりへも
        # 頭の「名前:」(B): 名簿・用語集の名前か、かな・カタカナだけの短い語で、直後に本文があるときだけ。単語の時刻も名前の分を除く
        self.assertEqual(at("もう一回")[2:], (fill.FILL_SPK_FLAG, {"from": "リリー:もう一回", "by": fill.FILL_SPK_BY}))
        self.assertEqual([by[t]["fill"]["from"] for t in ("もう一回言って", "ahoy")], [" リリー： もう一回言って", "宝鐘マリン:ahoy"])
        self.assertEqual(sum(1 for g in segs if g["text"] == "ahoy"), 2)   # 敬称を除くと名簿の名前(マリンさん)
        for t in ("マリン船長:ahoy", "結論:やらない", "12:30に集合", "リリー:", "とてもとても長いなまえです:はい", "Q:質問"):
            self.assertNotIn("fill", by[t], t)
        self.assertEqual(out["names_n"], 4)
        self.assertEqual(out["words"], [[0.7, 1.0, "もう一回"], [47.0, 47.5, "あい"], [48.8, 49.4, "うえお"]])
        # 末尾の重複(C)・別の読み(A。3 倍以上で、読みの半分以上が元の行の時間に入るときだけ。窓は前後 0.5 秒)
        self.assertEqual([by[t]["start"] for t in ("今日はいい天気ですね", "ですね", "いい天気ですね")], [17.0, 21.0, 22.0])   # 6 字未満・前の行の末尾でない行は残す
        self.assertEqual(at(FILLED), (4.7, 9.8, fill.FILL_FLAG, {"from": "テスト文1", "by": "sense-voice"}))
        self.assertEqual(at("テスト文2")[2:], (SPARSE, None))
        self.assertEqual(at("これは別の読みで埋めた長い文です")[3]["from"], "テスト文3")
        self.assertEqual(rich.windows, [4.5, 10.5, 58.5, 61.5, 117.5, 128.5, 134.5])   # 文字の少ない行の窓(3 回以上の繰り返しは 1 字に数える = 「あはは…」も)
        self.assertEqual(out["fill_rec"], {"engine": "sense-voice", "windows": 7, "rows": 2, "added": 2, "dup": 1, "agree": 1, "order": "AC"})
        self.assertEqual(orig[by[FILLED]["id"]], {"start": 4.7, "end": 9.8, "text": FILLED})   # 機械の出力 = 後処理のあと(自信の度合いの無い行)
        # 要確認の印
        self.assertEqual([by[t]["flag"] for t in ("ご視聴ありがとうございました", "げんげんげんげんげん", "スバル", "this is a random english line", "えーと")],
                         [STOCK, REP, LEAK, "英字が多い(英語の幻覚の可能性)", "自信が低い、音声でない可能性(BGMなど)、" + REP])
        self.assertEqual([g["flag"] for g in segs if g["text"] == "やばいやばい"], ["", "", SAME])   # 前の 5 行に同じ文が 2 回で 3 回目(句読点は除いて比べる)
        self.assertEqual([g["flag"] for g in segs if 121 <= g["start"] < 126], ["", "", "", "", SAME])   # 短い文は続けて 3 回のときだけ
        stock = {"ご視聴いただきありがとうございました": True, "高評価よろしくお願いします": True, "では次の動画でお会いしましょう": True,
                 "みんな高評価よろしくお願いしますね今日も": False, "えっと字幕つけて": True, "♪～": True, "(音楽)": True, "【 BGM 】": True,
                 "音楽いいね": False, "～": False}
        self.assertEqual({t: by[t]["flag"] == STOCK for t in stock}, stock)
        self.assertEqual([g["flag"] for g in segs if g["text"] == "ご覧いただきありがとうございました"], [STOCK, ""])   # 8 秒以上は対象外
        rep = {"なんかにもぱんぱんぱんぱんぱんぱん": True, "歩こう歩こう歩こう歩こう歩こう": True, "はいはいはいはい": False, "あはははははははははは": False}
        self.assertEqual({t: by[t]["flag"] == REP for t in rep}, rep)   # 4 回までと 1 文字の笑いは本当の発話にもある
        self.assertEqual(by["うわああああああああああ"]["flag"], REP)    # 同じ文字の続きは 10 字までに縮める
        self.assertEqual([by[t]["flag"] for t in ("大空スバルホロライブ", "用語: スバル", "スバルだよ", "すばる")], [LEAK, LEAK + "、" + SPARSE, "", LEAK])   # かなの違い・記号は数えない
        self.assertEqual([g["flag"] for g in segs if g["text"] == "スバル"], [LEAK, SPARSE])   # 長い区間は「文字が少ない」の印が拾う
        self.assertEqual(orig[by["こんにちは"]["id"]], {"start": 1.3, "end": 2.1, "text": "こんにちは", "avg_logprob": -0.1235, "compression_ratio": 1.2})
        # 置換辞書(機械の出力は変えない・|語| は単語の途中に当てない)
        self.assertEqual((out["dictApplied"], orig[by["白神フブキ"]["id"]]["text"], "エペやろう" in by, "アペックス" in by), (2, "白上フブキ", True, True))
        # 名簿の呼び名(D: 別のエンジンも同じ呼び名なら 1 字違いを直す)
        self.assertEqual(at("みこちが来たよ")[2:], ("名簿の呼び名に直した(別のエンジンも同じ呼び名)", {"from": "みこぢが来たよ", "by": "sense-voice"}))
        # LLM(E): 選ぶ(呼び名に近い所・誤りやすい形・カタカナの規則。そのまま出ている行・後処理の行・普通の言葉は選ばない・30 か所まで)→ 聞く → 検査 → 上限 → 当てる
        rec = out["llm_rec"]
        self.assertEqual(rec, {"engine": "llama-text", "model": "qwen3-8b", "picked": llm.LLM_MAX_PICKS, "proposed": 33, "applied": 14,
                               "rejected": {"length": 1, "newName": 1, "lowConfidence": 1, "notInRow": 1, "cap": 15}})
        self.assertEqual(at("生き花ラミィちゃんが好き")[3], {"from": "生き花ラミーちゃんが好き", "by": "llm"})
        self.assertTrue(by["生き花ラミィちゃんが好き"]["flag"].startswith(llm.LLM_FLAG))
        self.assertEqual((at("トワ様こんばんは")[3]["from"], "fill" in by["トルカ来た"], "fill" in by["言ってみるか"], "fill" in by["ラミィちゃん来た"]),
                         ("トーイ様こんばんは", False, False, False))
        self.assertEqual(sum(1 for g in segs if g["text"] == "ラミィちゃん"), 12)   # 1 文書で直す行は 15%(14 行)まで。自信の無い案は後
        self.assertEqual(orig[by["生き花ラミィちゃんが好き"]["id"]]["text"], "生き花ラミーちゃんが好き")
        self.assertEqual([it["rejected"] for it in out["llm_items"][:6]], [None, "length", None, "newName", "lowConfidence", "notInRow"])
        first = rich.asked[0]
        self.assertEqual([x["role"] for x in first], ["system", "user"])
        self.assertIn("/no_think", first[0]["content"])
        self.assertIn("→ 生き花ラミーちゃんが好き", first[1]["content"])
        ctx = first[1]["content"].split("前後の行")[1].split("疑わしい所")[0]
        self.assertEqual(ctx.count("\n  "), 4)                                   # 前後 2 行ずつ
        self.assertNotIn("やばい", ctx)                                            # 3 行前は見せない
        self.assertEqual((len(rich.asked), len(out["raw"]), out["raw"][0]["words"][0][:3]), (30, len(RAW), [0.0, 0.3, "リ"]))   # 生出力はそのまま
        self.assertFalse(job.get("warnings"))


class TestPostValues(unittest.TestCase):
    def test_spec_values_and_record(self):
        """測る道具は spec の endTrim・joinGap で渡す(モジュールの値を書き換えない)。範囲の外・数でなければ既定。版は呼ぶたびに ytt/workdata"""
        self.assertEqual(postproc.post_values({"endTrim": 0.1, "joinGap": 0}), (0.1, 0.0))
        self.assertEqual(postproc.post_values({"endTrim": 0.9, "joinGap": True}), (postproc.END_TRIM, postproc.JOIN_GAP))
        with mock.patch.object(workdata, "SERVER_VERSION", "9.9.9"), mock.patch.object(postproc, "END_TRIM", 0.1):
            self.assertEqual(postproc.post_record(), {"version": "9.9.9", "endTrim": 0.1, "joinGap": postproc.JOIN_GAP})
        self.assertEqual(postproc.post_record({"joinGap": 1.0})["joinGap"], 1.0)
        gen = [W(0.0, 1.0, "あ"), W(1.3, 2.0, "い")]
        self.assertEqual(list(postproc.expand_segments(gen, {"joinGap": 0.0}))[0]["end"], 1.0)   # つながない
        gen = [W(0.0, 1.0, "あ"), W(1.2, 2.0, "い")]
        self.assertEqual(list(postproc.expand_segments(gen, {"engine": "whisper.cpp", "endTrim": 0.2, "joinGap": 0.0}))[0]["end"], 0.8)   # whisper.cpp の続いている行だけ早める


if __name__ == "__main__":
    unittest.main()
