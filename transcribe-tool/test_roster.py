#!/usr/bin/env python3
"""名簿の呼び名と配信ごとの文脈(文字起こしの改善の計画 段1-1・1-2。roster.py・serve.py の stream_context)のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_roster -q                        # これだけ
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import roster as R
from test_backend import HERE, S, free_port, start_server, write_json

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
