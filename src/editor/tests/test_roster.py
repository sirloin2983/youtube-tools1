#!/usr/bin/env python3
"""名簿の呼び名(pipeline/transcribe/roster.py)と同梱の名簿のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_roster -q                        # これだけ

小さな名簿の見本(壊れた行・普通の言葉と重なる呼び名・長音の呼び名・英字の名前)を読み、配信の名前・題名・話者から出る人を決める入口(build_context)に通してまとめて確かめる。
要確認の印(ヒントの語だけ・決まり文句・繰り返し)は src/pipeline/transcribe/tests/test_postproc.py の見本の通し、配信ごとの文脈をジョブに残す形は test_fill.py の通し。
ここに残す単体: 認識のやり直し(VAD を外す)の判断 = ヒントの語だけが出た状態は本物の認識では起こせない。
"""
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import types
import unittest

from test_backend import S, write_json
from pipeline.transcribe import roster as R  # noqa: E402   (test_backend が serve を読んで src を sys.path に足したあと)
from ytt import testkit  # noqa: E402
from ytt.dictfmt import apply_replacements  # noqa: E402


def small_roster(tmp):
    p = os.path.join(tmp, "roster.json")
    write_json(p, {"groups": [{"id": "units", "label": "グループ", "names": ["ホロライブ"]},
                              {"id": "gen0", "label": "0期生", "names": ["さくらみこ", "ときのそら"]},
                              {"id": "gen3", "label": "3期生", "names": ["兎田ぺこら", "宝鐘マリン"]},
                              {"id": "en", "label": "EN", "names": ["IRyS"]}],
                   "members": [{"name": "さくらみこ", "aliases": ["みこ", "みこち", "みこ先輩"], "common": ["みこ"], "channel": "UC1", "region": "JP",
                                "misrecognitions": [{"wrong": "みく", "right": "みこ"}]},
                               {"name": "ときのそら", "aliases": ["そら", "そらちゃん"], "common": ["そら"], "channel": "UC2"},
                               {"name": "兎田ぺこら", "aliases": ["ぺこら", "ぺこーら", "兎田"], "region": "JP"},
                               {"name": "宝鐘マリン", "aliases": ["マリン", "船長"], "common": ["マリン", "船長", "ないもの"], "channel": "UC4", "region": "XX"},
                               {"name": "", "aliases": ["x"]}, "壊れた行"]})
    return p


class TestRosterRun(unittest.TestCase):
    def test_bundled_roster(self):
        """同梱の名簿: 画面の「名簿から追加」は groups だけを読む・所属 id が一意・名前が空でなく前後に空白がなく重ならない・主な人がいる・基準日がある"""
        r = S.load_roster()
        self.assertEqual(set(r), {"asOf", "note", "groups"})
        ids = [g["id"] for g in r["groups"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 15)
        for g in r["groups"]:
            self.assertTrue(g["names"] and all(isinstance(n, str) and n.strip() == n and n for n in g["names"]), g["id"])
            self.assertEqual(len(g["names"]), len(set(g["names"])), g["id"])
        names = {n for g in r["groups"] for n in g["names"]}
        self.assertTrue({"兎田ぺこら", "宝鐘マリン", "AZKi", "熱千めら", "さくらみこ"} <= names)
        self.assertRegex(r["asOf"], r"^\d{4}-\d\d-\d\d$")

    def test_context_from_channel_titles_and_speakers(self):
        tmp = testkit.tempdir(self)
        path = small_roster(tmp)
        r = R.load(path)
        self.assertEqual(sorted(r["members"]), ["さくらみこ", "ときのそら", "兎田ぺこら", "宝鐘マリン"])   # 名前の無い行・壊れた行は捨てる
        self.assertEqual(r["members"]["宝鐘マリン"]["common"], ["マリン", "船長"])                    # 呼び名に無い印は捨てる
        self.assertEqual(r["people"], ["さくらみこ", "ときのそら", "兎田ぺこら", "宝鐘マリン", "IRyS"])
        self.assertEqual(R.load(os.path.join(tmp, "無い.json")), {"groups": [], "members": {}, "people": []})
        self.assertEqual(R.channel_regions(path), {"UC1": "JP"})   # channel と有効な region がそろう人だけ

        c = R.build_context(r, "Pekora Ch. 兎田ぺこら", ["Marine Ch. 宝鐘 マリン"], ["話者1", "みこ", "ぺこらさん"],
                            ["【ときのそら】ペコラと", "そらとマリンと船長", "IRyS Ch. hololive-EN", "みこちの雑談"])
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]],
                         [("兎田ぺこら", ["channel", "title"]), ("宝鐘マリン", ["collab"]), ("さくらみこ", ["speaker", "title"]), ("ときのそら", ["title"]), ("IRyS", ["title"])])
        # 空白をはさんでも・カタカナとひらがなを区別しない・普通の言葉と重なる呼び名(そら・マリン・船長)では題名から決めない・3 文字以上の呼び名・
        # 話者の名前は普通の言葉と重なる呼び名でもよいがちょうど同じときだけ(ぺこらさん・話者1 は当たらない)
        self.assertEqual(R.member_terms(["さくらみこ", "IRyS"], r), ["さくらみこ", "みこ", "みこち", "みこ先輩", "IRyS"])   # 名前 + 呼び名 3 つ(呼び名が無い人は名前だけ)
        self.assertEqual(len(R.build_context(r, titles=["ぺこら 宝鐘マリン さくらみこ ときのそら"], limit=2)["members"]), 2)
        self.assertEqual((R.build_context(r)["members"], R.find_in_text("", r), R.match_name("話者1", r)), ([], [], None))
        self.assertEqual(R.fit(["あいう", "えお", "かきくけこ"], 6), ["あいう", "えお"])   # 「あいう、えお」= 6 字。語の途中で切らない
        self.assertEqual(R.fit(["あいう", "えお"], 6, 2), ["あいう"])                   # 区切りが 2 字(", ")なら 7 字で入らない
        self.assertEqual(R.fit(["a", "a", " ", "b"]), ["a", "b"])

    def test_alias_variants_and_pairs(self):
        """呼び名の表記ゆれ: 母音の長音 ↔ ー・ひらがな/カタカナの両方・短すぎる綴りと common の語は入れない・漢字の当て字。置換辞書の形で当てる"""
        self.assertEqual(R.alias_variants("はあちゃま"), ["はーちゃま", "ハーチャマ"])
        self.assertTrue({"ラミー", "らみー"} <= set(R.alias_variants("ラミィ")))
        self.assertEqual(R.alias_variants("みこち"), [])                       # 長音が無ければ変種なし
        self.assertIn("ルウナ", R.alias_variants("ルーナ"))                      # ー → 母音
        r = {"members": {"赤井はあと": {"aliases": ["はあと", "はあちゃま"], "common": []}, "白上フブキ": {"aliases": ["フブキ"], "common": []},
                         "さくらみこ": {"aliases": ["みこ"], "common": ["みこ"]}}, "people": []}
        pairs = R.variant_pairs(r)
        self.assertTrue({("はーちゃま", "はあちゃま"), ("吹雪", "フブキ")} <= set(pairs))
        self.assertFalse(any(dst == "みこ" for _s, dst in pairs))                  # common の語は直さない
        kanji = {src for v in R.KANJI_VARIANTS.values() for src, _d in v}
        self.assertTrue(all(len(src) >= R.VARIANT_MIN for src, _d in pairs if src not in kanji))   # 長音の変種は 3 字以上(漢字の当て字は表のまま)
        self.assertEqual(pairs, sorted(pairs, key=lambda p: (-len(p[0]), p[0])))    # 長い綴りから先
        self.assertEqual(apply_replacements("はーちゃまと吹雪が来た", pairs), ("はあちゃまとフブキが来た", 2))


class TestVadFallback(unittest.TestCase):
    def test_vad_fallback_treats_leak_as_empty(self):
        class Segs(list):
            def close(self):
                pass

        class Model:
            params = {"vad_filter", "vad_parameters", "language", "beam_size", "condition_on_previous_text", "no_speech_threshold", "initial_prompt", "hotwords"}

            def transcribe(self, audio, **kw):
                if kw.get("vad_filter"):   # 残りは十分だが、出たのはヒントの語だけ → 文字が 0 と同じにやり直す
                    return Segs([types.SimpleNamespace(start=0.0, end=1.0, text="スバル", words=[])]), types.SimpleNamespace(duration=30.0, duration_after_vad=20.0)
                return Segs([types.SimpleNamespace(start=0.0, end=2.0, text="やるぜよー", words=[])]), types.SimpleNamespace(duration=30.0, duration_after_vad=30.0)

        spec = {"vadMode": "weak", "language": "ja", "beam": 5, "model": "large-v3", "glossary": [], "context": {"terms": ["大空スバル", "スバル"]}}
        raw, vad = S.transcribe_vad_fallback({"cancel": False}, Model(), "a.wav", spec)
        self.assertEqual(([r["text"] for r in raw], vad["used"], vad["retries"][0]["why"]), (["やるぜよー"], "off", "empty"))
        raw, vad = S.transcribe_vad_fallback({"cancel": False}, Model(), "a.wav", dict(spec, context={}))
        self.assertEqual(([r["text"] for r in raw], vad["retries"]), (["スバル"], []))            # ヒントを渡していなければ本物の発話とみなす


if __name__ == "__main__":
    unittest.main()
