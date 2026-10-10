#!/usr/bin/env python3
"""名簿の呼び名と配信ごとの文脈(文字起こしの改善の計画 段1-1・1-2。roster.py・serve.py の stream_context)のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_roster -q                        # これだけ
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from test_backend import HERE, S, free_port, start_server, write_json
from pipeline.transcribe import roster as R  # noqa: E402   (test_backend が serve を読んで src を sys.path に足したあと)

ROSTER = os.path.join(HERE, "hololive-roster.json")


def small_roster(tmp):
    p = os.path.join(tmp, "roster.json")
    write_json(p, {"groups": [{"id": "units", "label": "グループ", "names": ["ホロライブ"]},
                              {"id": "gen0", "label": "0期生", "names": ["さくらみこ", "ときのそら"]},
                              {"id": "gen3", "label": "3期生", "names": ["兎田ぺこら", "宝鐘マリン"]},
                              {"id": "en", "label": "EN", "names": ["IRyS"]}],
                   "members": [{"name": "さくらみこ", "aliases": ["みこ", "みこち", "みこ先輩"], "common": ["みこ"],
                                "misrecognitions": [{"wrong": "みく", "right": "みこ"}]},
                               {"name": "ときのそら", "aliases": ["そら", "そらちゃん"], "common": ["そら"]},
                               {"name": "兎田ぺこら", "aliases": ["ぺこら", "ぺこーら", "兎田"]},
                               {"name": "宝鐘マリン", "aliases": ["マリン", "船長"], "common": ["マリン", "船長", "ないもの"]},
                               {"name": "", "aliases": ["x"]}, "壊れた行"]})
    return p


class TestRosterFile(unittest.TestCase):
    """同梱の名簿(hololive-roster.json)の形"""

    def test_members_are_in_groups(self):
        with open(ROSTER, encoding="utf-8") as f:
            d = json.load(f)
        people = {n for g in d["groups"] if g["id"] != "units" for n in g["names"]}
        seen = {}
        for m in d["members"]:
            self.assertIn(m["name"], people, m["name"])                                   # 名簿の人だけ
            self.assertTrue(m["aliases"], m["name"])
            self.assertTrue(set(m.get("common") or []) <= set(m["aliases"]), m["name"])   # 普通の言葉と重なる印は呼び名から
            for a in m["aliases"]:
                self.assertNotIn(a, seen, "同じ呼び名が2人に: %s(%s・%s)" % (a, seen.get(a), m["name"]))
                seen[a] = m["name"]
            for x in m.get("misrecognitions") or []:
                self.assertTrue(x["wrong"] and x["right"] and x["wrong"] != x["right"])
        r = R.load(ROSTER)
        self.assertGreaterEqual(len(r["members"]), 50)
        self.assertNotIn("ホロライブ", r["people"])                                          # グループ名は人ではない

    def test_serve_roster_api_unchanged(self):
        r = S.load_roster()                                                                  # 画面の「名簿から追加」は groups だけを読む(形は今までどおり)
        self.assertEqual(set(r), {"asOf", "note", "groups"})
        self.assertTrue(any("さくらみこ" in g["names"] for g in r["groups"]))


class TestRosterRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.r = R.load(small_roster(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_cleans(self):
        self.assertEqual(sorted(self.r["members"]), ["さくらみこ", "ときのそら", "兎田ぺこら", "宝鐘マリン"])   # 名前の無い行・壊れた行は捨てる
        self.assertEqual(self.r["members"]["宝鐘マリン"]["common"], ["マリン", "船長"])                    # 呼び名に無い印は捨てる
        self.assertEqual(self.r["people"], ["さくらみこ", "ときのそら", "兎田ぺこら", "宝鐘マリン", "IRyS"])
        self.assertEqual(R.load(os.path.join(self.tmp, "無い.json")), {"groups": [], "members": {}, "people": []})

    def test_find_in_text(self):
        f = lambda t: R.find_in_text(t, self.r)   # noqa: E731
        self.assertEqual(f("Miko Ch. さくらみこ"), ["さくらみこ"])
        self.assertEqual(f("【ホロライブ】ぺこらと宝鐘 マリンのコラボ"), ["兎田ぺこら", "宝鐘マリン"])     # 空白をはさんでも・出てくる順
        self.assertEqual(f("ペコラの配信"), ["兎田ぺこら"])                                               # カタカナとひらがなを区別しない
        self.assertEqual(f("そらとマリンと船長"), [])                                                      # 普通の言葉と重なる呼び名では決めない
        self.assertEqual(f("みこちの雑談"), ["さくらみこ"])                                                # 3 文字以上の呼び名
        self.assertEqual(f("IRyS Ch. hololive-EN"), ["IRyS"])
        self.assertEqual(f(""), [])

    def test_match_name(self):
        self.assertEqual(R.match_name("みこ", self.r), "さくらみこ")         # 話者の名前は、普通の言葉と重なる呼び名でもよい(人が付けた名前)
        self.assertEqual(R.match_name("ぺこーら", self.r), "兎田ぺこら")
        self.assertIsNone(R.match_name("話者1", self.r))
        self.assertIsNone(R.match_name("ぺこらさん", self.r))                 # ちょうど同じときだけ

    def test_build_context_order_and_limit(self):
        c = R.build_context(self.r, "Pekora Ch. 兎田ぺこら", ["Marine Ch. 宝鐘マリン"], ["話者1", "みこ"], ["【ときのそら】ぺこらと"])
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]],
                         [("兎田ぺこら", ["channel", "title"]), ("宝鐘マリン", ["collab"]), ("さくらみこ", ["speaker"]), ("ときのそら", ["title"])])
        self.assertEqual(len(R.build_context(self.r, titles=["ぺこら 宝鐘マリン さくらみこ ときのそら"], limit=2)["members"]), 2)
        self.assertEqual(R.build_context(self.r)["members"], [])

    def test_member_terms_and_fit(self):
        t = R.member_terms(["さくらみこ", "IRyS"], self.r)
        self.assertEqual(t, ["さくらみこ", "みこ", "みこち", "みこ先輩", "IRyS"])   # 名前 + 呼び名 3 つ(名簿に呼び名が無い人は名前だけ)
        self.assertEqual(R.fit(["あいう", "えお", "かきくけこ"], 6), ["あいう", "えお"])   # 「あいう、えお」= 6 字。語の途中で切らない
        self.assertEqual(R.fit(["あいう", "えお"], 6, 2), ["あいう"])                   # 区切りが 2 字(", ")なら 7 字で入らない
        self.assertEqual(R.fit(["a", "a", " ", "b"]), ["a", "b"])

    def test_alias_variants_and_pairs(self):
        """呼び名の表記ゆれ(2026-10-08): 母音の長音 ↔ ー・ひらがな/カタカナの両方・短すぎる綴りと common の語は入れない・漢字の当て字"""
        self.assertEqual(R.alias_variants("はあちゃま"), ["はーちゃま", "ハーチャマ"])
        self.assertIn("ラミー", R.alias_variants("ラミィ"))
        self.assertIn("らみー", R.alias_variants("ラミィ"))
        self.assertEqual(R.alias_variants("みこち"), [])                       # 長音が無ければ変種なし
        self.assertIn("ルウナ", R.alias_variants("ルーナ"))                      # ー → 母音
        r = {"members": {"赤井はあと": {"aliases": ["はあと", "はあちゃま"], "common": []}, "白上フブキ": {"aliases": ["フブキ"], "common": []},
                         "さくらみこ": {"aliases": ["みこ"], "common": ["みこ"]}}, "people": []}
        pairs = R.variant_pairs(r)
        self.assertIn(("はーちゃま", "はあちゃま"), pairs)
        self.assertIn(("吹雪", "フブキ"), pairs)
        self.assertFalse(any(dst == "みこ" for _s, dst in pairs))                  # common の語は直さない
        kanji = {src for v in R.KANJI_VARIANTS.values() for src, _d in v}
        self.assertTrue(all(len(src) >= R.VARIANT_MIN for src, _d in pairs if src not in kanji))   # 長音の変種は 3 字以上(漢字の当て字は表のまま)
        self.assertEqual(pairs, sorted(pairs, key=lambda p: (-len(p[0]), p[0])))    # 長い綴りから先
        from ytt.dictfmt import apply_replacements   # RS6 a-3 に pipeline/transcribe/replace から
        text, n = apply_replacements("はーちゃまと吹雪が来た", pairs)
        self.assertEqual((text, n), ("はあちゃまとフブキが来た", 2))

    def test_leak_only(self):
        terms = ["大空スバル", "スバル", "みこち"]
        self.assertTrue(R.leak_only("スバル、みこち", terms))
        self.assertTrue(R.leak_only("用語: 大空スバル", terms))
        self.assertTrue(R.leak_only("すばる!", terms))                     # かなの違い・記号は数えない
        self.assertFalse(R.leak_only("スバルがさ", terms))
        self.assertFalse(R.leak_only("スバル", []))
        self.assertFalse(R.leak_only("、。", terms))


class TestStreamContext(unittest.TestCase):
    """serve.py の stream_context: スタジオの data.json(読むだけ)・題名・話者の名前から出る人を決める"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (S.ROSTER, S.STUDIO_DATA)
        S.ROSTER = small_roster(self.tmp)
        S.STUDIO_DATA = os.path.join(self.tmp, "data.json")
        write_json(S.STUDIO_DATA, {"schema": "x", "videos": {"vidA": {"title": "コラボ!", "channel": "Pekora Ch. 兎田ぺこら"},
                                                            "vidB": {"title": "別視点", "channel": "Marine Ch. 宝鐘マリン"},
                                                            "vidC": {"title": "関係ない", "channel": "Miko Ch. さくらみこ"}},
                                   "groups": {"g1": {"members": ["vidA", "vidB", "無い配信"]}}})

    def tearDown(self):
        S.ROSTER, S.STUDIO_DATA = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_channel_collab_title(self):
        doc = {"clip": {"source": {"kind": "youtube", "videoId": "vidA", "title": "【】"}}, "title": "01_00h01m", "sourcePath": "C:\\x\\ときのそら 雑談\\01.mp4",
               "speakers": [{"id": "S1", "name": "話者1"}]}
        c = S.stream_context(doc)
        self.assertEqual([(m["name"], m["from"]) for m in c["members"]],
                         [("兎田ぺこら", ["channel"]), ("宝鐘マリン", ["collab"]), ("ときのそら", ["title"])])   # フォルダの名前も題名として見る
        self.assertEqual(c["terms"][:4], ["兎田ぺこら", "ぺこら", "ぺこーら", "兎田"])
        self.assertEqual(S.stream_context(doc, False), {"members": [], "terms": []})
        self.assertEqual(S.studio_stream("vidA")["collab"], [{"channel": "Marine Ch. 宝鐘マリン", "title": "別視点", "videoId": "vidB"},
                                                             {"channel": "", "title": "", "videoId": "無い配信"}])
        self.assertIsNone(S.studio_stream("無い"))

    def test_broken_studio_data(self):
        with open(S.STUDIO_DATA, "w", encoding="utf-8") as f:
            f.write("{壊れた")
        c = S.stream_context({"clip": {"source": {"videoId": "vidA"}}, "title": "ぺこらの配信"})
        self.assertEqual([m["name"] for m in c["members"]], ["兎田ぺこら"])   # スタジオのデータが読めなくても、題名から続ける

    def test_prompt_and_kwargs(self):
        spec = {"language": "ja", "beam": 5, "vadMode": "normal", "model": "large-v3", "glossary": ["ホロライブ"],
                "context": {"members": [{"name": "兎田ぺこら", "from": ["channel"]}], "terms": ["兎田ぺこら", "ぺこら"]}}
        kw = S.whisper_kwargs(spec)
        self.assertEqual(kw["initial_prompt"], "用語: ホロライブ、兎田ぺこら、ぺこら")   # 用語集が先・文脈が後
        self.assertEqual(kw["hotwords"], "ホロライブ, 兎田ぺこら, ぺこら")
        self.assertNotIn("temperature", kw)
        self.assertEqual(S.whisper_kwargs(dict(spec, temp0=True))["temperature"], 0.0)
        long = dict(spec, glossary=["語%03d" % i for i in range(60)])
        p = S.whisper_kwargs(long)["initial_prompt"]
        self.assertLessEqual(len(p) - len("用語: "), 150)
        self.assertTrue(p.endswith(tuple("語%03d" % i for i in range(60))))                # 語の途中で切らない
        self.assertNotIn("initial_prompt", S.whisper_kwargs(dict(spec, glossary=[], context={})))
        self.assertEqual(S.context_record(spec), {"members": [{"name": "兎田ぺこら", "from": ["channel"]}], "terms": 2})
        self.assertIsNone(S.context_record({"context": {"members": []}}))


def row(a, b, text, **kw):
    return dict({"start": a, "end": b, "text": text}, **kw)


class TestFlagsS3(unittest.TestCase):
    """S-3: よくある誤認識の文・行の中の繰り返し・近くの行の同じ文・ヒントの語だけの行"""

    def test_stock_phrase(self):
        self.assertTrue(S.stock_phrase("ご視聴いただきありがとうございました"))
        self.assertTrue(S.stock_phrase("高評価よろしくお願いします!"))
        self.assertTrue(S.stock_phrase("では次の動画でお会いしましょう"))                     # 決まり文句の前後 3 文字まで
        self.assertFalse(S.stock_phrase("みんな高評価よろしくお願いしますね今日も"))          # 配信者が本当に言う形(文の一部)は印なし
        self.assertTrue(S.stock_phrase("えっと字幕つけて"))                                   # 以前からの HALLUC は文の一部でも(今までどおり)
        self.assertTrue(S.stock_phrase("♪～"))
        self.assertTrue(S.stock_phrase("(音楽)"))
        self.assertTrue(S.stock_phrase("【 BGM 】"))
        self.assertFalse(S.stock_phrase("音楽いいね"))
        self.assertFalse(S.stock_phrase("～"))
        self.assertFalse(S.stock_phrase(""))
        self.assertIn("よくある誤認識の文", S.make_flags(row(0, 3, "ご覧いただきありがとうございました"), []))
        self.assertNotIn("よくある誤認識の文", S.make_flags(row(0, 9, "ご覧いただきありがとうございました"), []))   # 8 秒以上は対象外(今までどおり)

    def test_repeats_in_line(self):
        self.assertTrue(S.repeats_in_line("なんかにもぱんぱんぱんぱんぱんぱん"))
        self.assertTrue(S.repeats_in_line("歩こう、歩こう、歩こう、歩こう、歩こう。"))            # 記号をはさんでも
        self.assertFalse(S.repeats_in_line("はいはいはいはい"))                                   # 4 回までは本当の発話にもある
        self.assertFalse(S.repeats_in_line("あはははははははははは"))                             # 笑い・叫び(1 文字の繰り返し)は除く
        self.assertFalse(S.repeats_in_line("ああああああああああああ"))
        self.assertIn("繰り返しの可能性", S.make_flags(row(0, 3, "げんげんげんげんげん"), []))
        self.assertEqual(S.make_flags(row(0, 3, "はいはいはいはい"), []), "")

    def test_same_line_nearby(self):
        prev = ["やばいやばい", "いくよ", "やばいやばい", "ね"]
        self.assertIn("同じ文の繰り返し", S.make_flags(row(0, 2, "やばい、やばい"), prev))          # 前の5行に同じ文が2回
        self.assertEqual(S.make_flags(row(0, 2, "やばいやばい"), prev[:2]), "")                   # 2回目までは印なし
        self.assertEqual(S.make_flags(row(0, 1, "はい"), ["はい", "うん", "はい"]), "")          # 短い文は、続けて3回のときだけ
        self.assertIn("同じ文の繰り返し", S.make_flags(row(0, 1, "はい"), ["はい", "はい"]))

    def test_leak_flag(self):
        terms = ["ホロライブ", "大空スバル", "スバル"]
        self.assertIn(S.LEAK_FLAG, S.make_flags(row(0, 1.2, "スバル"), [], "ja", terms))
        self.assertIn(S.LEAK_FLAG, S.make_flags(row(0, 2.0, "大空スバル、ホロライブ。"), [], "ja", terms))
        self.assertNotIn(S.LEAK_FLAG, S.make_flags(row(0, 5.0, "スバル"), [], "ja", terms))        # 短い区間だけ(長い区間は「文字が少ない」の印が拾う)
        self.assertIn(S.LEAK_FLAG, S.make_flags(row(0, 10.0, "用語: スバル"), [], "ja", terms))    # ヒントの書き出しそのものは長さによらず
        self.assertNotIn(S.LEAK_FLAG, S.make_flags(row(0, 1.2, "スバルだよ"), [], "ja", terms))
        self.assertNotIn(S.LEAK_FLAG, S.make_flags(row(0, 1.2, "スバル"), [], "ja", []))           # ヒントを渡していなければ付けない
        self.assertIn(S.LEAK_FLAG, S.REDO_BAD_FLAGS)                                               # 認識し直してこの印なら「良くなった」とみなさない

    def test_vad_fallback_treats_leak_as_empty(self):
        import types

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


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestContextHttp(unittest.TestCase):
    """疑似モードのサーバー: 設定の autoContext で文書に文脈が残る・評価用として文字起こしすると辞書・文脈を使わない"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        media = os.path.join(cls.tmp, "media", "兎田ぺこら 雑談")
        os.makedirs(media)
        cls.wav = os.path.join(media, "01.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=9", cls.wav], check=True)
        cls.port = free_port()
        old = os.environ.get("TRANSCRIBE_STUDIO_DATA")
        os.environ["TRANSCRIBE_STUDIO_DATA"] = os.path.join(cls.tmp, "無い.json")
        try:
            cls.proc = start_server(cls.tmp, cls.port, os.path.join(cls.tmp, ".runtime"))
        finally:
            if old is None:
                os.environ.pop("TRANSCRIBE_STUDIO_DATA", None)
            else:
                os.environ["TRANSCRIBE_STUDIO_DATA"] = old
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=60) as r:
                return dict(json.loads(r.read()), _status=r.status)
        except urllib.error.HTTPError as e:
            return dict(json.loads(e.read() or b"{}"), _status=e.code)

    def run_job(self, body):
        j = self.call("POST", "/api/transcribe", dict({"sourcePath": self.wav, "model": "small", "autoGloss": False}, **body))
        self.assertEqual(j["_status"], 200, j)
        end = time.time() + 60
        while time.time() < end:
            x = next(v for v in self.call("GET", "/api/jobs")["jobs"] if v["id"] == j["id"])
            if x["state"] in ("done", "error", "cancelled"):
                break
            time.sleep(0.05)
        self.assertEqual(x["state"], "done", x)
        return self.call("GET", "/api/transcript?id=" + x["tid"])

    def test_context_and_eval_start(self):
        d = self.run_job({"autoContext": True, "glossary": "ホロライブ"})
        self.assertEqual(d["params"]["context"], {"members": [{"name": "兎田ぺこら", "from": ["title"]}], "terms": 4})   # 動画のフォルダの名前から
        self.assertEqual(d["recognition"]["runs"][0]["settings"]["context"], ["兎田ぺこら"])
        self.assertNotIn("evalSet", d)
        d = self.run_job({"glossary": "ホロライブ"})
        self.assertIsNone(d["params"]["context"])                                                     # 既定はオフ
        d = self.run_job({"autoContext": True, "glossary": "ホロライブ", "evalSet": True, "autoDict": True, "autoLearned": True})
        self.assertIs(d["evalSet"], True)                                                              # 評価用として文字起こし
        self.assertEqual((d["params"]["glossary"], d["params"]["context"], d["params"]["autoDict"], d["params"]["autoLearned"]), ([], None, False, False))
        self.assertEqual(d["recognition"]["runs"][0]["settings"]["promptChars"], 0)


if __name__ == "__main__":
    unittest.main()
