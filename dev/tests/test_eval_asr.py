"""dev/eval_asr.py(文字起こしの精度を測る道具。計画 段0-2)のテスト。リポジトリ直下で:

    python -m unittest dev/tests/test_eval_asr.py

作業データは一時フォルダに作る(本物の作業データは読まない)。run は偽の認識(TRANSCRIBE_BACKEND=fake)で流れだけ確かめる(ffmpeg が必要)。
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import wave
import zipfile
from contextlib import redirect_stdout

os.environ.setdefault("YTT_DATA_DIR", "inplace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/ (道具の置き場所)
sys.path.insert(0, HERE)
import eval_asr as E  # noqa: E402
import eval_import as EI  # noqa: E402


def seg(i, a, b, text, proofed=True, tags=None, flag=""):
    g = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": "", "flag": flag}
    if proofed:
        g["proofed"] = True
    if tags:
        g["tags"] = tags
    return g


def silence_wav(path, sec):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * int(16000 * sec))


def quiet(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        return fn(*a)


class EvalAsrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0"
        # 評価用: 置換 1(祭り→まつり)・重なり・人が足した行(抜け)・人が消した行(余分)・未校正の行(数えない)
        self.write("aaaaaaaaaaa1", evalSet=True, segments=[
            seg(1, 0.0, 4.0, "まつりが来た"), seg(2, 4.0, 8.0, "二人で話す", tags=["overlap"]), seg(3, 20.0, 22.0, "足した行"),
            seg(4, 30.0, 34.0, "まだ見ていない", proofed=False)],
            original=[{"start": 0.0, "end": 4.0, "text": "祭りが来た"}, {"start": 4.0, "end": 8.0, "text": "二人で話す"},
                      {"start": 12.0, "end": 13.0, "text": "ご視聴ありがとうございました"}, {"start": 30.0, "end": 34.0, "text": "まだ見てない"}])
        self.write("bbbbbbbbbbb2", segments=[seg(1, 0.0, 2.0, "学習用")], original=[{"start": 0.0, "end": 2.0, "text": "学習よう"}])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def snapshot(self):
        d = os.path.join(self.data, "transcripts")
        out = {}
        for n in sorted(os.listdir(d)):
            with open(os.path.join(d, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_stored_counts_like_the_screen(self):
        before = self.snapshot()
        res = quiet(E.main, ["stored", "--data", self.data, "--no-save"])
        o = res["summary"]["overall"]
        self.assertEqual(res["meta"]["docs"], ["aaaaaaaaaaa1"])          # 既定は評価用だけ
        self.assertEqual(res["meta"]["mismatch"], [])                   # 画面の「認識精度の測定」と同じ数
        # 正解 = まつりが来た(6)+ 二人で話す(5)+ 足した行(4)= 15 字。祭り→まつり は置換 1・抜け 1(編集距離が最小の数え方)
        self.assertEqual(o["refChars"], 15)
        self.assertEqual(res["summary"]["byKind"]["両方にある"]["errs"], 2)
        self.assertEqual(res["summary"]["byKind"]["人が足した(抜け)"]["del"], 4)   # 人が足した行 = 抜け
        self.assertEqual(res["summary"]["byKind"]["人が消した(余分)"]["ins"], len("ご視聴ありがとうございました"))
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["refChars"], 5)
        self.assertEqual(res["summary"]["byTag"]["声が重なる"]["errs"], 0)
        self.assertTrue(all(g["start"] < 30 for g in res["groups"]))    # 未校正の行は数えない
        self.assertEqual(self.snapshot(), before)                       # 文書は書き換えない
        allres = quiet(E.main, ["stored", "--data", self.data, "--scope", "all", "--no-save"])
        self.assertEqual(sorted(allres["meta"]["docs"]), ["aaaaaaaaaaa1", "bbbbbbbbbbb2"])
        # 時刻によらない数え方(段2-3): 数えたまとまりの文字を通しでつないで比べる。まとまりの数え方と同じ文字数・誤りはそれ以下
        dt = res["summary"]["docText"]
        self.assertEqual(dt["refChars"], 15)
        self.assertLessEqual(dt["sub"] + dt["del"] + dt["ins"], o["errs"])

    def test_doc_text_ignores_time_shift(self):
        """行の時刻がずれて文字が隣のまとまりへ移っても、時刻によらない数え方では誤りにならない"""
        S = E.load_serve("fake")
        groups = [{"doc": "d", "start": 0.0, "ref": "あいう", "hyp": "あい"}, {"doc": "d", "start": 5.0, "ref": "えお", "hyp": "うえお"}]
        dt = E.doc_text(S, groups)
        self.assertEqual((dt["refChars"], dt["sub"], dt["del"], dt["ins"], dt["cer"]), (5, 0, 0, 0, 0.0))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_recognizes_and_saves_without_touching_docs(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 12.0)
            # 偽の認識は 4 秒ごとに「テスト文N」を出す
            self.write("ccccccccccc3", evalSet=True, sourcePath=src, start=0, end=12,
                       segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2x"), seg(3, 8.0, 12.0, "テスト文3")], original=[])
            before = self.snapshot()
            res = quiet(E.main, ["run", "--data", self.data, "--docs", "ccccccccccc3", "--label", "fake-test"])
            o = res["summary"]["overall"]
            self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (16, 0, 1, 0))   # 「x」が抜けた 1 字だけ
            self.assertEqual(res["meta"]["engine"]["engine"], "fake")
            self.assertEqual(res["meta"]["perDoc"][0]["audio"], "動画")
            self.assertGreater(res["meta"]["audioSec"], 11)
            self.assertEqual(self.snapshot(), before)                     # 文書は書き換えない
            saved = os.listdir(os.path.join(self.data, "evals", "asr"))
            self.assertEqual(len(saved), 1)
            self.assertTrue(saved[0].endswith("_fake-test.json"))
            # 元の動画が無ければ、保管データの全体の音声(文書の範囲の先頭 = 0 秒)で測る
            full = os.path.join(self.data, "dataset", "docs", "ccccccccccc3")
            os.makedirs(full)
            shutil.copy(src, os.path.join(full, "full.flac"))
            os.unlink(src)
            res2 = quiet(E.main, ["run", "--data", self.data, "--docs", "ccccccccccc3", "--no-save"])
            self.assertEqual(res2["meta"]["perDoc"][0]["audio"], "保管の音声")
            self.assertEqual(res2["summary"]["overall"]["errs"], 1)
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_with_context(self):
        """--context auto = 文書の題名などから出る人を決めて渡す(計画 段1-2)。既定の none では渡さない。--temp0 は設定に残る"""
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 8.0)
            self.write("ddddddddddd4", evalSet=True, title="教師データ＿さくらみこ01", sourcePath=src, start=0, end=8,
                       segments=[seg(1, 0.0, 4.0, "テスト文1"), seg(2, 4.0, 8.0, "テスト文2")], original=[])
            res = quiet(E.main, ["run", "--data", self.data, "--docs", "ddddddddddd4", "--context", "auto", "--temp0", "--no-save"])
            self.assertEqual(res["meta"]["perDoc"][0]["context"], ["さくらみこ"])
            self.assertEqual((res["meta"]["engine"]["context"], res["meta"]["engine"]["settings"]["temp0"]), ("auto", True))
            self.assertIn("みこち", res["terms"])                                          # 名前の再現率に呼び名も数える(段1-1)
            base = quiet(E.main, ["run", "--data", self.data, "--docs", "ddddddddddd4", "--no-save"])
            self.assertEqual((base["meta"]["perDoc"][0]["context"], base["meta"]["engine"]["context"]), ([], "none"))
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    def test_compare_same_docs(self):
        a = quiet(E.main, ["stored", "--data", self.data, "--label", "a"])
        pa = os.path.join(self.data, "evals", "asr", sorted(os.listdir(os.path.join(self.data, "evals", "asr")))[0])
        same = quiet(E.cmd_compare, pa, pa)
        self.assertEqual(same["diff"], 0)
        self.assertIn("差があるとは言えない", same["verdict"])
        # B: 置換の誤りを直した結果(文書を1本足して、文書ごとの差が出るように)
        b = json.loads(json.dumps(a))
        for g in b["groups"]:
            g["sub"] = 0
        pb = os.path.join(self.tmp, "b.json")
        with open(pb, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False)
        out = quiet(E.cmd_compare, pa, pb)
        self.assertLess(out["diff"], 0)                                   # B の方が誤りが少ない
        self.assertEqual(out["docs"], 1)


def ms(y, m, d, h=12):
    """この PC の時刻の日時 -> ミリ秒(--since・--until は日付をこの PC の時刻で読む)"""
    return int(datetime.datetime(y, m, d, h).timestamp() * 1000)


def pseg(i, a, b, text, at=None):
    """校正済みの行(proofedAt = 初めて校正済みにした時刻。at が None なら付けない = 以前の文書)"""
    g = seg(i, a, b, text)
    if at is not None:
        g["proofedAt"] = at
    return g


def run_rec(engine="faster-whisper", model="large-v3", dict_=None, kind=None, beam=5, hint=False):
    r = {"engine": engine, "engineVersion": "1.0", "model": model, "device": "cpu", "language": "ja",
         "settings": {"beam": beam, "vadMode": "normal", "boost": False, "wordSplit": True, "glossaryChars": 5 if hint else 0, "promptChars": 0,
                      "context": [], "dict": dict_ or {}}}
    if kind:
        r["kind"] = kind
    return r


class EvalAsrSelectTest(unittest.TestCase):
    """マスタープラン Q3: 時期で分ける・出どころ(評価用・普段・友人)・下書きのエンジンの注意・エンジン別の集計・少ないデータ"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_eval_asr_sel_")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "transcripts"))
        self.intake = os.path.join(self.tmp, "intake")
        os.environ["TRANSCRIBE_FAKE_DELAY"] = "0"
        orig = [{"start": 0.0, "end": 4.0, "text": "あいくお"}, {"start": 4.0, "end": 8.0, "text": "えお"}]   # 1 行目は「あいう」を聞き違えた
        # 評価用: 行ごとの proofedAt の最大が 09-10(最初の行は 09-01)/ proofedAt なしで updatedAt = 10-02
        self.write("eeeeeeeeee01", evalSet=True, segments=[pseg(1, 0, 4, "あいう", ms(2026, 9, 1)), pseg(2, 4, 8, "えお", ms(2026, 9, 10))],
                   original=orig, recognition={"runs": [run_rec()]})
        self.write("eeeeeeeeee02", evalSet=True, updatedAt=ms(2026, 10, 2), segments=[pseg(1, 0, 4, "あいう"), pseg(2, 4, 8, "えお")],
                   original=orig, recognition={"runs": [run_rec()]})
        # 普段: whisper.cpp(辞書の版 abc)・時期が分からない(updatedAt も無い)・途中で別のエンジンで認識し直した・同じ whisper.cpp で辞書の版だけ違う
        self.write("dddddddddd01", segments=[pseg(1, 0, 4, "あいう", ms(2026, 10, 3)), pseg(2, 4, 8, "えお", ms(2026, 10, 3))], original=orig,
                   recognition={"runs": [run_rec("whisper.cpp", "large-v3", {"glossary": "abc"})]})
        self.write("dddddddddd02", updatedAt=0, segments=[pseg(1, 0, 4, "あいう"), pseg(2, 4, 8, "えお")], original=orig)
        self.write("dddddddddd03", updatedAt=ms(2026, 8, 1), segments=[pseg(1, 0, 4, "あいう"), pseg(2, 4, 8, "えお")], original=orig,
                   recognition={"runs": [run_rec(), run_rec("whisper.cpp", kind="range")]})
        self.write("dddddddddd04", segments=[pseg(1, 0, 4, "あいう", ms(2026, 10, 4)), pseg(2, 4, 8, "えお", ms(2026, 10, 4))], original=orig,
                   recognition={"runs": [run_rec("whisper.cpp", "large-v3", {"glossary": "zzz"})]})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, tid, **kw):
        doc = {"schema": "transcribe/v1", "id": tid, "title": tid, "sourcePath": "", "start": 0, "end": None, "language": "ja",
               "speakers": [], "updatedAt": 1, **kw}
        with open(os.path.join(self.data, "transcripts", tid + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

    def stored(self, *argv):
        return quiet(E.main, ["stored", "--data", self.data, "--intake", self.intake, "--no-save", *argv])

    def ids(self, res):
        return sorted(res["meta"]["docs"])

    def printed(self, res):
        out = io.StringIO()
        with redirect_stdout(out):
            E.print_summary(res)
        return out.getvalue()

    # ---------------- 時期

    def test_doc_time_is_max_proofed_at_then_updated_at(self):
        d = {"segments": [pseg(1, 0, 1, "a", 100), pseg(2, 1, 2, "b", 300), pseg(3, 2, 3, "c")], "updatedAt": 999}
        self.assertEqual(E.doc_time(d), (300, "proofedAt"))                       # 行の proofedAt の最大
        self.assertEqual(E.doc_time(dict(d, segments=[seg(1, 0, 1, "a")])), (999, "updatedAt"))   # 無ければ updatedAt
        self.assertEqual(E.doc_time({"segments": [seg(1, 0, 1, "a", proofed=False)]}), (None, ""))
        # 校正済みでない行の proofedAt(外した行の残り)は数えない
        self.assertEqual(E.doc_time({"segments": [dict(seg(1, 0, 1, "a", proofed=False), proofedAt=500)], "updatedAt": 7}), (7, "updatedAt"))

    def test_since_until(self):
        every = ["dddddddddd01", "dddddddddd03", "dddddddddd04", "eeeeeeeeee01", "eeeeeeeeee02"]   # 時期が分からない dddddddddd02 は、時期の指定がなければ数える
        res = self.stored("--scope", "all")
        self.assertEqual(self.ids(res), sorted(every + ["dddddddddd02"]))
        # --since: その日を含む。eeeeeeeeee01 は行の proofedAt の最大(09-10)で決まる(最初の行 09-01 ではない)
        res = self.stored("--scope", "all", "--since", "2026-09-10")
        self.assertEqual(self.ids(res), ["dddddddddd01", "dddddddddd04", "eeeeeeeeee01", "eeeeeeeeee02"])
        self.assertEqual((res["meta"]["since"], res["meta"]["selection"]["unknownTime"], res["meta"]["selection"]["excludedByTime"]), ("2026-09-10", 1, 1))
        res = self.stored("--scope", "all", "--since", "2026-09-11")
        self.assertNotIn("eeeeeeeeee01", self.ids(res))
        # --until: その日の終わりまで含む(updatedAt が 10-02 の昼でも 10-02 を含む)
        res = self.stored("--scope", "all", "--until", "2026-10-02")
        self.assertEqual(self.ids(res), ["dddddddddd03", "eeeeeeeeee01", "eeeeeeeeee02"])
        res = self.stored("--scope", "all", "--since", "2026-09-11", "--until", "2026-10-02")
        self.assertEqual(self.ids(res), ["eeeeeeeeee02"])
        self.assertEqual(self.stored("--scope", "all", "--since", "2026-10-05")["meta"]["docs"], [])
        # 結果の「正解のデータの版」は選んだ文書で決まる(時期を変えれば別の正解 = compare が警告する)
        self.assertNotEqual(res["meta"]["dataFingerprint"], self.stored("--scope", "all")["meta"]["dataFingerprint"])
        with self.assertRaises(SystemExit):
            self.stored("--since", "10/01")

    # ---------------- 出どころ

    def test_source_choices(self):
        self.assertEqual(self.ids(self.stored()), ["eeeeeeeeee01", "eeeeeeeeee02"])                                    # 既定は今までどおり評価用だけ
        self.assertEqual(self.ids(self.stored("--source", "eval")), ["eeeeeeeeee01", "eeeeeeeeee02"])
        daily = ["dddddddddd01", "dddddddddd02", "dddddddddd03", "dddddddddd04"]
        self.assertEqual(self.ids(self.stored("--source", "daily")), daily)
        self.assertEqual(self.ids(self.stored("--scope", "train")), daily)                                             # 古い --scope も同じ
        self.assertEqual(self.ids(self.stored("--source", "all")), sorted(daily + ["eeeeeeeeee01", "eeeeeeeeee02"]))   # 友人の zip が無ければ自分の文書だけ
        self.assertEqual(self.ids(self.stored("--source", "friend")), [])
        res = self.stored("--source", "daily", "--docs", "eeeeeeeeee01")                                              # --docs は出どころより優先
        self.assertEqual(self.ids(res), ["eeeeeeeeee01"])
        src = {d["id"]: d["source"] for d in self.stored("--source", "all")["summary"]["byDoc"]}
        self.assertEqual((src["dddddddddd01"], src["eeeeeeeeee01"]), ("daily", "eval"))

    def make_zip(self, name, wid, rows, raw_segments, exported="2026-10-02T10:00:00+0900"):
        """友人の送る用 zip(形は ytt_core/evaldata.py)を作って eval_import で取り込む"""
        common = {"format": EI.ev.FORMAT, "formatVersion": EI.ev.FORMAT_VERSION, "workId": wid}
        parts = {"final.json": dict(common, rows=rows),
                 "asr_raw.json": dict(common, run=run_rec(), segments=raw_segments),
                 "meta.json": dict(common, rulesVersion=EI.ev.RULES_VERSION, streamer="テスト配信者", performers=[], sourceName="clip.mp4", exportedAt=exported)}
        path = os.path.join(self.tmp, name)
        with zipfile.ZipFile(path, "w") as z:
            for fn, obj in parts.items():
                z.writestr(fn, json.dumps(obj, ensure_ascii=False))
            z.writestr("audio.flac", b"fLaC")
            z.writestr("edits.jsonl", b"")
        res = EI.import_zip(path, self.intake, no_train=set())
        self.assertEqual(res["result"], "imported", res)

    def friend_fixture(self):
        def row(i, a, b, text, checked=True):
            return {"id": "r%d" % i, "start": a, "end": b, "text": text, "speaker": "", "checked": checked, "tags": [], "raw": [i - 1]}
        rows = [row(1, 0, 4, "こんにちは"), row(2, 4, 6, "[笑]"), row(3, 6, 9, "未確認の行", checked=False), row(4, 9, 12, "【笑】あ"), row(5, 12, 15, "これはテスト[?]")]
        raw = [{"start": 0, "end": 4, "text": "こんにちわ"}, {"start": 4, "end": 6, "text": "あはは"}, {"start": 6, "end": 9, "text": "みかくにん"},
               {"start": 9, "end": 12, "text": "あ"}, {"start": 12, "end": 15, "text": "これはてすと"}]
        self.make_zip("2026-10-01_配信者_abcdef012345.zip", "abcdef012345", rows, raw)
        # 確認済みの行が 1 つも無い作業 = 作業ごと外れる(数えない)
        self.make_zip("2026-10-01_配信者_abcdef012346.zip", "abcdef012346", [row(1, 0, 4, "あ", checked=False)], raw[:1])

    def test_friend_zip(self):
        self.friend_fixture()
        res = self.stored("--source", "friend")
        self.assertEqual(self.ids(res), ["abcdef012345"])
        self.assertEqual(res["meta"]["mismatch"], [])
        self.assertEqual([x["id"] for x in res["meta"]["selection"]["friendSkipped"]], ["abcdef012346"])
        self.assertIn("作業ごと", res["meta"]["selection"]["friendSkipped"][0]["why"])
        o = res["summary"]["overall"]
        # 数えるのは「こんにちは」だけ: 形式違いの記号の行・未確認の行は校正済みにしない。[笑] だけ・[?] の行は聞き取れない扱いで数えない
        self.assertEqual((o["refChars"], o["sub"], o["del"], o["ins"]), (5, 1, 0, 0))
        d = res["summary"]["byDoc"][0]
        self.assertEqual((d["source"], d["draft"], d["timeBasis"]), ("friend", "faster-whisper large-v3 v1.0", "exportedAt"))
        self.assertTrue(d["draftBias"])
        # 友人の zip は all に入る・時期は書き出した時刻(10-02)で分ける
        self.assertIn("abcdef012345", self.ids(self.stored("--source", "all")))
        self.assertEqual(self.ids(self.stored("--source", "friend", "--since", "2026-10-03")), [])
        self.assertEqual(self.ids(self.stored("--source", "friend", "--until", "2026-10-02")), ["abcdef012345"])
        # 友人の zip は --scope all(自分の文書だけ)には入らない
        self.assertNotIn("abcdef012345", self.ids(self.stored("--scope", "all")))
        docs, skipped = E.load_friend_docs(self.intake)
        self.assertTrue(docs[0]["sourcePath"].endswith("audio.flac"))      # run で認識し直す音声(作業ごとの audio.flac)
        self.assertEqual(len(skipped), 1)

    # ---------------- 下書きのエンジン

    def test_draft_bias_rules(self):
        ev_doc = {"_source": "eval", "recognition": {"runs": [run_rec()]}}
        daily = {"recognition": {"runs": [run_rec(), run_rec("whisper.cpp", kind="range")]}}
        self.assertEqual(E.draft_bias(ev_doc, E.STORED), "")                                    # 評価用は丁寧に校正してあるので注意しない
        self.assertIn("下書きそのもの", E.draft_bias(daily, E.STORED))                             # 保存した出力を測るのは下書きを測ること
        self.assertIn("モデルも同じ", E.draft_bias(daily, {"engine": "faster-whisper", "model": "large-v3"}))
        self.assertIn("モデルは違う", E.draft_bias(daily, {"engine": "faster-whisper", "model": "small"}))
        self.assertEqual(E.draft_bias(daily, {"engine": "whisper.cpp", "model": "large-v3"}), "")   # 下書きは最初の認識(再認識の記録 kind ではない)
        self.assertEqual(E.draft_bias({}, {"engine": "faster-whisper", "model": "large-v3"}), "")   # 記録が無ければ分からない
        self.assertEqual(E.draft_of({"recognition": {"runs": [run_rec("whisper.cpp", kind="range")]}})["engine"], "whisper.cpp")   # 再認識の記録しか無ければそれ
        self.assertIsNone(E.draft_of({}))

    def test_stored_marks_draft(self):
        res = self.stored("--source", "all")
        bias = {b["id"]: b["note"] for b in res["summary"]["draftBias"]}
        self.assertEqual(sorted(bias), ["dddddddddd01", "dddddddddd02", "dddddddddd03", "dddddddddd04"])   # 評価用は出ない
        by = {d["id"]: d for d in res["summary"]["byDoc"]}
        self.assertEqual((by["eeeeeeeeee01"]["draft"], by["dddddddddd01"]["draft"], by["dddddddddd02"]["draft"]),
                         ("faster-whisper large-v3 v1.0", "whisper.cpp large-v3 v1.0", E.DRAFT_NONE))
        self.assertEqual(by["dddddddddd03"]["draft"], "faster-whisper large-v3 v1.0")                   # 下書き = 最初の認識(あとの再認識ではない)
        self.assertEqual(res["summary"]["byDraft"]["whisper.cpp large-v3 v1.0"]["docs"], 2)
        text = self.printed(res)
        self.assertIn("下書きそのもの", text)
        self.assertIn("下書き: whisper.cpp large-v3 v1.0 ※", text)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が無い")
    def test_run_is_hint_free_and_warns_same_draft_engine(self):
        os.environ["TRANSCRIBE_BACKEND"] = "fake"
        try:
            src = os.path.join(self.tmp, "clip.wav")
            silence_wav(src, 8.0)
            with open(os.path.join(self.data, "settings.json"), "w", encoding="utf-8") as f:
                json.dump({"glossary": "トワ、スバル"}, f, ensure_ascii=False)
            segs = [pseg(1, 0, 4, "テスト文1", ms(2026, 10, 3)), pseg(2, 4, 8, "テスト文2", ms(2026, 10, 3))]
            self.write("ffffffffff01", sourcePath=src, start=0, end=8, segments=segs, original=[], recognition={"runs": [run_rec("fake", "tiny")]})
            self.write("ffffffffff02", sourcePath=src, start=0, end=8, segments=segs, original=[], recognition={"runs": [run_rec("faster-whisper")]})
            self.write("ffffffffff03", evalSet=True, sourcePath=src, start=0, end=8, segments=segs, original=[], recognition={"runs": [run_rec("fake")]})
            # 普段の文書: 設定の用語集があっても渡さない(ヒントなし)。評価用と同じ条件
            res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff01,ffffffffff02"])
            self.assertEqual((res["meta"]["engine"]["glossary"], res["meta"]["engine"]["hintFree"]), ([], True))
            self.assertEqual(res["summary"]["overall"]["errs"], 0)
            # 比べるエンジン(fake)と下書きのエンジンが同じ文書だけに注意が付く
            bias = {b["id"]: b["note"] for b in res["summary"]["draftBias"]}
            self.assertEqual(list(bias), ["ffffffffff01"])
            self.assertIn("同じ", bias["ffffffffff01"])
            # 自分で付けた --glossary は渡す。評価用だけのときは今までどおり設定の用語集・下書きの注意は付かない
            res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff01", "--glossary", "あ、い"])
            self.assertEqual(res["meta"]["engine"]["glossary"], ["あ", "い"])
            res = quiet(E.main, ["run", "--data", self.data, "--no-save", "--docs", "ffffffffff03"])
            self.assertEqual((res["meta"]["engine"]["glossary"], res["meta"]["engine"]["hintFree"], res["summary"]["draftBias"]), (["トワ", "スバル"], False, []))
            # 辞書(置換・学習)は常に使わない
            S = E.load_serve("fake")
            args = type("A", (), dict(glossary=None, beam=None, model=None, engine="faster-whisper", vad=None, boost=None, device="auto", temp0=False))()
            spec = E.run_spec(S, args, {"glossary": "トワ"}, hint_free=True)
            self.assertEqual((spec["glossary"], spec["autoDict"], spec["autoLearned"]), ([], False, False))
        finally:
            os.environ.pop("TRANSCRIBE_BACKEND", None)

    # ---------------- エンジン・設定ごと

    def test_group_by_engine(self):
        res = self.stored("--source", "all", "--group-by", "engine")
        g = res["summary"]["byGroup"]
        by_key = {k: v["docs"] for k, v in g.items()}
        fw = "faster-whisper large-v3 v1.0 beam5 vad:normal boost:off ヒント:なし 辞書:-"
        self.assertEqual(by_key[fw], 2)                                                      # 評価用の 2 本は同じエンジン・設定
        self.assertEqual(by_key["whisper.cpp large-v3 v1.0 beam5 vad:normal boost:off ヒント:なし 辞書:glossary=abc"], 1)   # 辞書の版が違えば別の組
        self.assertEqual(by_key["whisper.cpp large-v3 v1.0 beam5 vad:normal boost:off ヒント:なし 辞書:glossary=zzz"], 1)
        mixed = [k for k in g if k.startswith("混在")]                                         # 途中で別のエンジンで認識し直した文書は混ぜない
        self.assertEqual(len(mixed), 1)
        self.assertIn("faster-whisper", mixed[0])
        self.assertIn("whisper.cpp", mixed[0])
        self.assertEqual(g[E.DRAFT_NONE]["docs"], 1)                                          # 記録が無い文書
        self.assertEqual(sum(v["docs"] for v in g.values()), 6)
        self.assertEqual(g[fw]["refChars"], 10)
        # 設定・辞書の版を混ぜる粗い分け方
        g2 = self.stored("--source", "all", "--group-by", "model")["summary"]["byGroup"]
        self.assertEqual({k: v["docs"] for k, v in g2.items()}["whisper.cpp large-v3 v1.0"], 2)
        self.assertNotIn("byGroup", self.stored("--source", "all")["summary"])                 # 指定しなければ出さない
        self.assertIn("--group-by engine", self.printed(res))
        # run では、比べるエンジンは全部同じなので、下書きを作ったエンジンで分ける(group_spec)
        title, key_of = E.group_spec(type("A", (), {"group_by": "model"})(), "run")
        self.assertIn("下書き", title)
        self.assertEqual(key_of({"recognition": {"runs": [run_rec("whisper.cpp")]}}), "whisper.cpp large-v3 v1.0")
        self.assertEqual(key_of({}), E.DRAFT_NONE)

    def test_run_label_old_records(self):
        """辞書の版・設定が無い古い記録(設定が params にある・何も無い)でも落ちない"""
        self.assertEqual(E.run_label({"engine": "faster-whisper", "model": "small"}, "engine"), "faster-whisper small ヒント:なし 辞書:-")
        r = {"engine": "faster-whisper", "model": "small", "params": {"beam": 1, "dict": {"roster": "r1"}}}
        self.assertEqual(E.run_label(r, "engine"), "faster-whisper small beam1 ヒント:なし 辞書:roster=r1")
        self.assertEqual(E.engine_key({"recognition": {"runs": [{"kind": "range"}]}}), E.DRAFT_NONE)

    # ---------------- 少ないデータ

    def test_low_data(self):
        res = self.stored()
        self.assertTrue(res["summary"]["lowData"])
        self.assertEqual(res["summary"]["proofedSec"], 16.0)               # 8 秒 × 2 本
        self.assertIn("まだ少ない(参考)", self.printed(res))
        # 校正済みが 15 分に届けば外れる
        self.write("bbbbbbbbbb01", evalSet=True, segments=[pseg(1, 0, 900, "長い行のテスト文章です")], original=[{"start": 0, "end": 900, "text": "長い行のテスト文章です"}])
        res = self.stored("--docs", "bbbbbbbbbb01")
        self.assertEqual((res["summary"]["lowData"], res["summary"]["proofedSec"]), (False, 900.0))
        self.assertNotIn("まだ少ない", self.printed(res))
        res = self.stored("--docs", "bbbbbbbbbb01,eeeeeeeeee01", "--group-by", "model")      # 組ごとにも出す(組の校正済みが少なければ参考)
        self.assertEqual({k: v["lowData"] for k, v in res["summary"]["byGroup"].items()}, {E.DRAFT_NONE: False, "faster-whisper large-v3 v1.0": True})


if __name__ == "__main__":
    unittest.main()
