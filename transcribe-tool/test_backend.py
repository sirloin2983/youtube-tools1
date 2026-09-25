#!/usr/bin/env python3
"""サーバー側の見直し(2026-09-24)で直したバグ・足した機能のテスト。

    python3 -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python3 -m unittest test_backend -q                        # これだけ

受け渡しの約束(docs/pipeline.md)の API(clip-info / transcript-v1 / export-file / siblings)は、
疑似モード(TRANSCRIBE_BACKEND=fake)のサーバーを空いているポートで起動して確かめる(ffmpeg が必要)。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt_core(リポジトリ直下)を見つけられるように
sys.path.insert(0, HERE)
import serve as S  # noqa: E402
import pipeline_io as P  # noqa: E402

TID = "0123456789ab"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def clip_obj(**over):
    d = {"schema": "youtube-tools-clip/v1", "tool": {"name": "clip-studio", "version": "0.2.0"}, "createdAt": "2026-09-24T12:00:00+09:00",
         "media": {"path": "C:\\x\\動画_0012.mp4", "name": "動画_0012.mp4", "durationSec": 24.0},
         "source": {"kind": "youtube", "videoId": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "配信<b>タイトル</b>", "path": None},
         "range": {"start": 1234.5, "end": 1258.5}, "mark": {"id": "m12", "label": "見どころ", "status": "exported", "src": "manual"},
         "export": {"mode": "precise"}, "futureField": {"x": 1}}
    d.update(over)
    return d


class StoreDir(unittest.TestCase):
    """serve の保存先を一時フォルダに差し替える。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (S.TX_DIR, S.TMP_DIR, S.SETTINGS)
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.tmp, os.path.join(self.tmp, ".tmp"), os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        S.TX_DIR, S.TMP_DIR, S.SETTINGS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put_doc(self, doc, tid=TID):
        write_json(S.tx_path(tid), doc)


class TestWriteLocks(StoreDir):
    """話者判別・再認識の書き込みは、画面の保存と同じロックの中で行う(間に保存が挟まると、その保存が黙って消えていた)。"""

    def _blocked_while_locked(self, fn):
        done = threading.Event()
        err = []

        def run():
            try:
                fn()
            except Exception as e:   # pragma: no cover - 失敗はテストで検出する
                err.append(e)
            done.set()

        with S._save_lock:
            th = threading.Thread(target=run, daemon=True)
            th.start()
            self.assertFalse(done.wait(0.3), "保存のロック中なのに書き込みが進んだ")
        self.assertTrue(done.wait(5))
        self.assertEqual(err, [])

    def base_doc(self):
        return {"id": TID, "sourcePath": "", "original": [{"start": 0, "end": 2, "text": "a"}, {"start": 2, "end": 4, "text": "b"}],
                "segments": [{"id": "s1", "start": 0, "end": 2, "text": "a", "speaker": "", "flag": ""},
                             {"id": "s2", "start": 2, "end": 4, "text": "b", "speaker": "", "flag": ""}], "updatedAt": 1}

    def test_retranscribe_waits_for_save_lock(self):
        self.put_doc(self.base_doc())
        self._blocked_while_locked(lambda: S.apply_retranscribe({"tid": TID, "model": "m", "autoDict": False}, {"s1": ("A", "")}))
        self.assertEqual(S.read_transcript(TID)["segments"][0]["text"], "A")

    def test_range_waits_for_save_lock(self):
        self.put_doc(self.base_doc())
        spec = {"tid": TID, "model": "m", "autoDict": False, "range": [0, 4], "ids": ["s1", "s2"]}
        self._blocked_while_locked(lambda: S.apply_range(spec, [{"start": 0, "end": 4, "raw": "新しい", "flag": ""}]))
        self.assertEqual([g["text"] for g in S.read_transcript(TID)["segments"]], ["新しい"])

    def test_diarization_waits_for_save_lock(self):
        self.put_doc(self.base_doc())
        self._blocked_while_locked(lambda: S.apply_diarization(TID, [(0, 4, 0)], 0.0, 0))
        self.assertEqual(S.read_transcript(TID)["segments"][0]["speaker"], "S1")

    def test_atomic_write_leaves_no_temp_on_failure(self):
        target = os.path.join(self.tmp, "x.json")
        S.atomic_write(target, b"{}")
        real = os.replace

        def boom(a, b):
            raise OSError("disk full")
        try:
            os.replace = boom
            with self.assertRaises(OSError):
                S.atomic_write(target, b"{\"a\": 1}")
        finally:
            os.replace = real
        self.assertEqual(sorted(os.listdir(self.tmp)), ["x.json"])   # 一時ファイルが残らない・元の内容は壊れない
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"{}")


class TestJobs(unittest.TestCase):
    def setUp(self):
        self.old = (dict(S._jobs), list(S._order))
        S._jobs.clear()
        S._order.clear()

    def tearDown(self):
        while not S._queue.empty():
            S._queue.get_nowait()
        S._jobs.clear()
        S._jobs.update(self.old[0])
        S._order.clear()
        S._order.extend(self.old[1])

    def test_exclusive_checked_inside_add_job(self):
        """同じ文字起こしへの話者判別・再認識は、待機列に入れるときにも重ねない(確認と登録の間の割り込み対策)。"""
        S.add_job({"title": "d", "tid": "t1"}, "diarize")
        with self.assertRaises(S.ApiError) as cm:
            S.add_job({"title": "r", "tid": "t1"}, "retranscribe")
        self.assertEqual(cm.exception.status, 409)
        S.add_job({"title": "d2", "tid": "t2"}, "diarize")        # 別の文字起こしなら入る
        S.add_job({"title": "ab", "tid": "t1"}, "abtest")          # 比較は話者判別と同時でもよい(文書を書き換えない)
        with self.assertRaises(S.ApiError):
            S.add_job({"title": "ab2", "tid": "t1"}, "abtest")


class TestExportCleanup(StoreDir):
    def test_failed_export_removes_partial_zip(self):
        """評価用の文字起こしを指定した書き出しは断る。そのとき作りかけの zip を .tmp に残さない。"""
        doc = {"id": TID, "evalSet": True, "original": [{"start": 0, "end": 2, "text": "a"}],
               "segments": [{"id": "s1", "start": 0, "end": 2, "text": "b", "proofed": True}]}
        self.put_doc(doc)
        with self.assertRaises(S.ApiError) as cm:
            S.export_corrections(TID, audio=False)
        self.assertEqual(cm.exception.code, "eval_set")
        self.assertEqual([n for n in os.listdir(S.TMP_DIR) if n.endswith(".zip")], [])


class TestArchiveWithoutFfmpeg(StoreDir):
    def test_existing_full_flac_without_ffmpeg(self):
        """ffmpeg が無いのに前回の full.flac が残っていると、保管が TypeError で失敗していた。"""
        old_ds, old_ff = S.DATASET_DIR, S.find_ffmpeg
        S.DATASET_DIR = os.path.join(self.tmp, "dataset")
        try:
            src = os.path.join(self.tmp, "a.wav")
            with open(src, "wb") as f:
                f.write(b"x" * 2000)
            self.put_doc({"id": TID, "sourcePath": src, "start": 0, "end": 4, "original": [{"start": 0, "end": 2, "text": "a"}],
                          "segments": [{"id": "s1", "start": 0, "end": 2, "text": "a", "proofed": True}], "updatedAt": 1})
            root = os.path.join(S.DATASET_DIR, "docs", TID)
            os.makedirs(root)
            with open(os.path.join(root, "full.flac"), "wb") as f:
                f.write(b"fLaC" + b"0" * 500)
            S.find_ffmpeg = lambda: None
            man = S.archive_doc(TID)
            self.assertEqual(man["newClips"], 0)
            self.assertEqual(man["counts"]["positive"], 1)
        finally:
            S.DATASET_DIR, S.find_ffmpeg = old_ds, old_ff


class TestPerformance(StoreDir):
    def test_audio_span(self):
        self.assertEqual(S.audio_span([{"start": 100, "end": 102}, {"start": 50, "end": 51}], 0, 3600), (50 - 0.3 - S.AUDIO_MARGIN, 102 + 0.3 + S.AUDIO_MARGIN))
        self.assertEqual(S.audio_span([{"start": 1, "end": 2}], 0.5, 3.0), (0.5, 3.0))       # 文書の範囲の外は取り出さない
        self.assertEqual(S.audio_span([{"start": 1, "end": 2}], 0, None)[1], 2 + 0.3 + S.AUDIO_MARGIN)

    def _long_doc(self):
        src = os.path.join(self.tmp, "long.wav")
        with open(src, "wb") as f:
            f.write(b"x" * 2000)
        segs = [{"id": "s%d" % i, "start": i * 10.0, "end": i * 10.0 + 5, "text": "行%d" % i, "speaker": "", "flag": "", "proofed": True} for i in range(360)]
        self.put_doc({"id": TID, "sourcePath": src, "start": 0, "end": 3600.0, "whole": True, "duration": 3600.0,
                      "original": [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in segs], "segments": segs, "updatedAt": 1})

    def _run_capturing(self, fn, job):
        seen = []
        old_ex, old_env = S.extract_audio, os.environ.get("TRANSCRIBE_BACKEND")

        def fake_extract(job, spec, wav):
            seen.append((spec["start"], spec["end"]))
        try:
            S.extract_audio = fake_extract
            os.environ["TRANSCRIBE_BACKEND"] = "fake"
            os.environ.setdefault("TRANSCRIBE_FAKE_DELAY", "0")
            fn(job)
        finally:
            S.extract_audio = old_ex
            if old_env is None:
                os.environ.pop("TRANSCRIBE_BACKEND", None)
            else:
                os.environ["TRANSCRIBE_BACKEND"] = old_env
        return seen

    def test_retranscribe_extracts_only_needed_span(self):
        """1時間の文書の2行だけを再認識するとき、1時間分ではなく、その行の前後だけを取り出す。"""
        self._long_doc()
        spec = {"tid": TID, "ids": ["s100", "s101"], "mode": "each", "range": None, "model": "small", "language": "ja", "beam": 5, "vadMode": "off",
                "wordSplit": False, "stripPunct": True, "device": "auto", "boost": False, "autoDict": False, "glossary": [], "title": "t"}
        job = {"id": "j1" + "0" * 10, "spec": spec, "cancel": False, "state": "queued", "progress": 0, "phase": "", "proc": None}
        seen = self._run_capturing(S.run_retranscribe, job)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(len(seen), 1)
        a, b = seen[0]
        self.assertLessEqual(a, 1000 - 0.3)
        self.assertGreaterEqual(b, 1015 + 0.3)
        self.assertLess(b - a, 30)
        doc = S.read_transcript(TID)
        self.assertEqual(doc["segments"][100]["text"], "行100(再)")

    def test_abtest_extracts_only_needed_span(self):
        self._long_doc()
        segs = S.read_transcript(TID)["segments"]
        for g in segs:
            g.pop("proofed", None)
        for i in (200, 203):
            segs[i]["proofed"] = True
        d = S.read_transcript(TID)
        d["segments"] = segs
        self.put_doc(d)
        spec = {"tid": TID, "ids": ["s200", "s203"], "variants": [{"model": "small", "glossary": False}], "language": "ja", "beam": 5, "vadMode": "off",
                "device": "auto", "boost": False, "glossary": [], "title": "t"}
        old_eval = S.EVAL_DIR
        S.EVAL_DIR = os.path.join(self.tmp, "evals")
        try:
            job = {"id": "ab" + "0" * 10, "spec": spec, "cancel": False, "state": "queued", "progress": 0, "phase": "", "proc": None}
            seen = self._run_capturing(S.run_abtest, job)
        finally:
            S.EVAL_DIR = old_eval
        self.assertEqual(job["state"], "done", job.get("error"))
        a, b = seen[0]
        self.assertTrue(a <= 2000 - 0.3 and b >= 2035 + 0.3 and b - a < 60, seen)

    def test_idle_model_release(self):
        """認識ワーカーの中(IN_WORKER)でのモデルの手放し。サーバー側(ワーカーごと終わらせる)は test_worker.py"""
        old = (dict(S._models), S._model_used[0], S.MODEL_IDLE_SEC, S.IN_WORKER)
        S.IN_WORKER = True
        try:
            S._models.clear()
            S._models[("large-v3", "cpu")] = object()
            S.MODEL_IDLE_SEC = 900
            now = time.time()
            S._model_used[0] = now - 100
            self.assertFalse(S.release_idle_models(now))            # まだ使って間もない
            S._model_used[0] = now - 901
            self.assertTrue(S.release_idle_models(now))
            self.assertEqual(S._models, {})
            S._models[("small", "cpu")] = object()
            S.MODEL_IDLE_SEC = 0
            self.assertFalse(S.release_idle_models(now + 10 ** 6))   # 0 は手放さない
        finally:
            S._models.clear()
            S._models.update(old[0])
            S._model_used[0], S.MODEL_IDLE_SEC, S.IN_WORKER = old[1], old[2], old[3]

    def test_summary_cache_and_ranges_without_rereading(self):
        self.put_doc({"id": TID, "title": "一", "sourcePath": "/v/a.mp4", "start": 0, "end": 10, "whole": True, "segments": [], "createdAt": 1})
        items = S.list_transcripts()
        self.assertEqual((items[0]["title"], items[0]["hasClip"]), ("一", False))
        self.assertNotIn("_sourcePath", items[0])
        old = S.read_transcript
        S.read_transcript = lambda tid: (_ for _ in ()).throw(AssertionError("読み直さない"))
        try:
            r = S.transcribed_ranges()
        finally:
            S.read_transcript = old
        self.assertEqual([(x["tid"], x["whole"]) for x in r], [(TID, True)])
        time.sleep(0.01)
        self.put_doc({"id": TID, "title": "二番目", "sourcePath": "/v/a.mp4", "clip": clip_obj(), "segments": [], "createdAt": 1})
        items = S.list_transcripts()
        self.assertEqual((items[0]["title"], items[0]["hasClip"]), ("二番目", True))   # 書き換わったら読み直す
        os.unlink(S.tx_path(TID))
        self.assertEqual(S.list_transcripts(), [])
        self.assertNotIn(TID, S._summary_cache)

    def test_scan_common_reads_transcripts_once(self):
        calls = []
        old = S.transcribed_ranges
        S.transcribed_ranges = lambda: calls.append(1) or [{"path": os.path.normcase(os.path.abspath("/d1/a.mp4")), "start": 0, "end": None, "whole": True, "tid": "t1"}]
        try:
            out = S.scan_common(["/d1/a.mp4", "/d2/b.mp4", "/d3/.hidden.mp4"])
        finally:
            S.transcribed_ranges = old
        self.assertEqual(len(calls), 1)                              # フォルダごとに全文書を読み直さない
        self.assertEqual([(o["doneTid"], o["queued"]) for o in out], [("t1", False), ("", False), ("", False)])


class TestStartupChecks(StoreDir):
    def test_checks(self):
        old = (S.INDEX, S.APP_JS, S.find_ffmpeg)
        try:
            S.INDEX = os.path.join(self.tmp, "index.html")
            with open(S.INDEX, "w", encoding="utf-8") as f:
                f.write("<html></html>")
            S.APP_JS = os.path.join(self.tmp, "app.js")
            with open(S.APP_JS, "w", encoding="utf-8") as f:
                f.write("const APP_VERSION = '%s';" % S.SERVER_VERSION)
            S.find_ffmpeg = lambda: "/usr/bin/ffmpeg"
            self.assertEqual(S.startup_checks(), [])
            with open(S.APP_JS, "w", encoding="utf-8") as f:
                f.write("const APP_VERSION = '0.0.1';")
            S.find_ffmpeg = lambda: None
            blocker = os.path.join(self.tmp, "file")
            with open(blocker, "w") as f:
                f.write("x")
            S.TX_DIR = os.path.join(blocker, "transcripts")    # ファイルの下には作れない = 書き込めない保存先
            w = " / ".join(S.startup_checks())
            for word in ("ffmpeg", "版が違います", "保存先に書き込めません"):
                self.assertIn(word, w)
            os.unlink(S.APP_JS)
            self.assertIn("app.js が見つかりません", " / ".join(S.startup_checks()))
            os.unlink(S.INDEX)
            self.assertIn("index.html が見つかりません", " / ".join(S.startup_checks()))
        finally:
            S.INDEX, S.APP_JS, S.find_ffmpeg = old


class TestBomTolerant(StoreDir):
    def test_settings_and_roster_with_bom(self):
        """メモ帳の「UTF-8 (BOM 付き)」で直した settings.json・名簿でも読める(以前は置換辞書が黙って使われず、名簿は読めないと出た)。"""
        with open(S.SETTINGS, "w", encoding="utf-8-sig") as f:
            json.dump({"replacements": "よっきゃ=>陽キャ"}, f, ensure_ascii=False)
        self.assertEqual(S.parse_replacements(S.load_settings().get("replacements")), [("よっきゃ", "陽キャ")])
        old = S.ROSTER
        try:
            S.ROSTER = os.path.join(self.tmp, "roster.json")
            with open(S.ROSTER, "w", encoding="utf-8-sig") as f:
                json.dump({"asOf": "2026-09-22", "groups": [{"id": "g", "label": "G", "names": ["兎田ぺこら"]}]}, f, ensure_ascii=False)
            self.assertEqual(S.load_roster()["groups"][0]["names"], ["兎田ぺこら"])
        finally:
            S.ROSTER = old
        p = os.path.join(self.tmp, "data.json")
        with open(p, "w", encoding="utf-8-sig") as f:
            json.dump({"videos": {}}, f)
        self.assertEqual(S._read_json_file(p), {"videos": {}})


class TestModelName(unittest.TestCase):
    def test_local_paths_are_not_model_names(self):
        """faster-whisper は名前と同じフォルダがあればそれを読み込むので、手元に実在する名前は断る。"""
        self.assertTrue(S.valid_model("large-v3"))
        self.assertTrue(S.valid_model("kotoba-tech/kotoba-whisper-v2.0-faster"))
        for bad in ("../x", ".hidden", "a/b/c", "C:\\x", "", "x" * 101, None):
            self.assertFalse(S.valid_model(bad), bad)
        tmp = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            os.chdir(tmp)
            os.makedirs("mymodel")
            os.makedirs(os.path.join("org", "local"))
            self.assertFalse(S.valid_model("mymodel"))       # 起動したフォルダからの相対で実在する
            self.assertFalse(S.valid_model("org/local"))
            self.assertTrue(S.valid_model("org/remote"))
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse(S.valid_model("transcripts" if os.path.isdir(os.path.join(S.ROOT, "transcripts")) else "hololive-roster.json"))   # ツールのフォルダの中の名前


class TestClipValidation(unittest.TestCase):
    def test_valid_clip_keeps_unknown_fields(self):
        clip, warn = P.validate_clip(clip_obj())
        self.assertIsNone(warn)
        self.assertEqual(clip["futureField"], {"x": 1})     # 知らない項目も残す(前方互換)
        self.assertEqual(P.clip_offset(clip), 1234.5)
        clip2, _ = P.validate_clip(clip_obj(export={"mode": "fast", "actualStart": 1231.0}))
        self.assertEqual(P.clip_offset(clip2), 1231.0)      # 高速書き出しのずれは actualStart を優先

    def test_invalid_or_other_version(self):
        cases = [
            ([], "オブジェクト"),
            (clip_obj(schema="youtube-tools-clip/v2"), "未対応の版"),
            (clip_obj(schema="something-else"), "schema"),
            (clip_obj(range={"start": 10, "end": 5}), "range"),
            (clip_obj(range={"start": -1, "end": 5}), "range"),
            (clip_obj(range={"start": True, "end": 5}), "range"),
            (clip_obj(range=None), "range"),
            (clip_obj(source="text"), "source"),
            (clip_obj(export={"actualStart": "abc"}), "actualStart"),
        ]
        for obj, word in cases:
            clip, warn = P.validate_clip(obj)
            self.assertIsNone(clip, obj)
            self.assertIn(word, warn)

    def test_files_and_media_resolution(self):
        tmp = tempfile.mkdtemp()
        try:
            media = os.path.join(tmp, "動画_0012.mp4")
            with open(media, "wb") as f:
                f.write(b"x")
            cj = os.path.join(tmp, "動画_0012.clip.json")
            self.assertEqual(P.clip_path_for(media), cj)
            self.assertEqual(P.find_clip(media), (None, None, None))           # 無ければ何もしない
            with open(cj, "w", encoding="utf-8-sig") as f:                     # BOM 付きでも読む
                json.dump(clip_obj(), f, ensure_ascii=False)
            clip, warn, path = P.find_clip(media, 24.5)
            self.assertEqual((clip["range"]["start"], warn, path), (1234.5, None, cj))
            clip, warn, _ = P.find_clip(media, 60.0)                          # 長さが大きく違えば警告(clip は使う)
            self.assertIsNotNone(clip)
            self.assertIn("長さ", warn)
            # media.path は別の PC のパス → 同じフォルダの media.name を使う
            self.assertEqual(P.resolve_clip_media(cj, clip, S.MEDIA_TYPES), os.path.abspath(media))
            # media.name に ../ があっても、フォルダの外は見ない(名前だけを使う)
            outside = os.path.join(os.path.dirname(tmp), "outside_%s.mp4" % os.getpid())
            with open(outside, "wb") as f:
                f.write(b"x")
            try:
                c2 = dict(clip, media={"name": "../" + os.path.basename(outside), "path": ""})
                os.unlink(media)
                self.assertIsNone(P.resolve_clip_media(cj, c2, S.MEDIA_TYPES))
            finally:
                os.unlink(outside)
            # .clip.json の中のネットワークのパスには接続しない
            self.assertTrue(P.is_network_path("\\\\host\\share\\x.mp4") and P.is_network_path("//host/x.mp4"))
            self.assertFalse(P.is_network_path("C:\\x.mp4") or P.is_network_path("/home/x.mp4") or P.is_network_path("Z:/x.mp4"))
            seen = []
            real_isfile = os.path.isfile
            os.path.isfile = lambda c: seen.append(c) or real_isfile(c)
            try:
                P.resolve_clip_media(cj, dict(clip, media={"path": "\\\\evil\\share\\x.mp4", "name": ""}), S.MEDIA_TYPES)
            finally:
                os.path.isfile = real_isfile
            self.assertFalse(any("evil" in c for c in seen))
            # 壊れた JSON・大きすぎるファイルは使わない
            with open(cj, "w", encoding="utf-8") as f:
                f.write("{broken")
            self.assertIsNone(P.load_clip_file(cj)[0])
            with open(cj, "w", encoding="utf-8") as f:
                f.write(" " * (P.MAX_SIDECAR_BYTES + 10))
            self.assertIn("大きすぎ", P.load_clip_file(cj)[1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def sample_doc(src):
    return {"schema": "transcribe/v1", "id": TID, "title": "テスト", "sourcePath": src, "sourceName": os.path.basename(src),
            "start": 0, "end": 12.0, "whole": True, "duration": 12.0, "model": "small", "language": "ja", "params": {"glossary": ["x"]},
            "speakers": [{"id": "S1", "name": "トワ", "color": "#111"}, {"id": "S2", "name": "ぺこら", "color": "#222"}],
            "segments": [
                {"id": "s3", "start": 6.0, "end": 8.0, "text": "三行目", "speaker": "S1", "flag": "自信が低い", "cutState": "cut"},
                {"id": "s1", "start": 0.5, "end": 2.0, "text": " 一行目 ", "speaker": "S2", "flag": "", "proofed": True, "tags": ["bgm"]},
                {"id": "s2", "start": 2.0, "end": 4.0, "text": "二行目", "speaker": "", "flag": ""},
                {"id": "s4", "start": 8.5, "end": 9.0, "text": "   ", "speaker": "", "flag": ""},
                {"id": "s5", "start": 9.5, "end": 11.0, "text": "とても長い行なので折り返されます", "speaker": "S1", "flag": ""}],
            "original": [{"start": 0.5, "end": 2.0, "text": "機械の出力"}], "createdAt": 1, "updatedAt": 5}


class TestFormats(unittest.TestCase):
    def test_transcript_v1(self):
        d = sample_doc("/x/動画.mp4")
        d["clip"] = clip_obj()
        t = P.build_transcript_v1(d, "9.9.9")
        self.assertEqual(t["schema"], "youtube-tools-transcript/v1")
        self.assertEqual(t["tool"], {"name": "transcribe-tool", "version": "9.9.9"})
        self.assertRegex(t["createdAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(t["media"], {"path": "/x/動画.mp4", "name": "動画.mp4", "durationSec": 12.0})
        self.assertEqual(t["clip"]["range"], {"start": 1234.5, "end": 1258.5})
        self.assertEqual(t["speakers"], [{"id": 0, "name": "トワ"}, {"id": 1, "name": "ぺこら"}])
        self.assertEqual([(g["id"], g["speaker"], g["proofed"], g["cut"]) for g in t["segments"]],
                         [("s1", 1, True, False), ("s2", None, False, False), ("s3", 0, False, True), ("s5", 0, False, False)])   # 時刻順・空の行なし
        self.assertEqual(t["segments"][0]["text"], "一行目")
        blob = json.dumps(t, ensure_ascii=False)
        for secret in ("original", "機械の出力", "params", "flag", "自信が低い", "tags", "updatedAt"):
            self.assertNotIn(secret, blob)                  # 機械の出力・学習用の情報は入れない
        self.assertNotIn("transcribedRange", t)
        d.update({"whole": False, "start": 100.0, "end": 160.0})
        self.assertEqual(P.build_transcript_v1(d, "1")["transcribedRange"], {"start": 100.0, "end": 160.0})

    def test_cut_plan_v1_uses_resolve_rule(self):
        t = P.build_cut_plan_v1(sample_doc("/x/動画.mp4"), "1")
        self.assertEqual(t["schema"], "youtube-tools-cut-plan/v1")
        self.assertEqual([(g["start"], g["end"], g["status"], g["lines"]) for g in t["segments"]],
                         [(0.5, 4.0, "adopted", ["s1", "s2"]), (9.5, 11.0, "adopted", ["s5"])])   # カット済(s3)・空(s4)は除き、接する行はまとめる
        self.assertEqual(t["segments"][0]["label"], "一行目二行目")
        self.assertEqual(t["media"]["path"], "/x/動画.mp4")

    def test_srt_matches_screen_rules(self):
        text, n = P.build_srt(sample_doc("/x/a.mp4"))
        self.assertEqual(n, 4)
        self.assertEqual(text, "1\n00:00:00,500 --> 00:00:02,000\n一行目\n\n2\n00:00:02,000 --> 00:00:04,000\n二行目\n\n"
                               "3\n00:00:06,000 --> 00:00:08,000\n三行目\n\n4\n00:00:09,500 --> 00:00:11,000\nとても長い行なので折り返されます\n")
        text, _ = P.build_srt(sample_doc("/x/a.mp4"), wrap=8, speaker_names=True)
        self.assertIn("[ぺこら] 一行目\n", text)
        self.assertIn("[トワ] とても長い行なの\nで折り返されます\n", text)   # 8文字ごと(名前は数えない)
        self.assertIn("\n2\n00:00:02,000 --> 00:00:04,000\n二行目\n", text)   # 話者なしの行は名前を付けない


class TestSaveBeside(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.media = os.path.join(self.tmp, "動画 A.mp4")
        with open(self.media, "wb") as f:
            f.write(b"x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def own(self, schema):
        return json.dumps({"schema": schema, "tool": {"name": "transcribe-tool", "version": "1"}}).encode()

    def test_overwrite_only_own_same_schema(self):
        sch = P.TRANSCRIPT_SCHEMA
        p1, ow = P.save_beside(self.media, ".transcript.json", self.own(sch), sch)
        self.assertEqual((os.path.basename(p1), ow), ("動画 A.transcript.json", False))
        p2, ow = P.save_beside(self.media, ".transcript.json", self.own(sch), sch)
        self.assertEqual((p2, ow), (p1, True))                                     # 前にこのツールが書いたものは上書き
        other = os.path.join(self.tmp, "動画 A.cut-plan.json")
        write_json(other, {"schema": P.CUT_PLAN_SCHEMA, "segments": []})           # 同じ schema でも他のツール(tool なし)が書いたもの
        p3, ow = P.save_beside(self.media, ".cut-plan.json", self.own(P.CUT_PLAN_SCHEMA), P.CUT_PLAN_SCHEMA)
        self.assertEqual((os.path.basename(p3), ow), ("動画 A (2).cut-plan.json", False))
        with open(other, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["segments"], [])                          # 元のファイルは無事
        p4, ow = P.save_beside(self.media, ".cut-plan.json", self.own(P.CUT_PLAN_SCHEMA), P.CUT_PLAN_SCHEMA)
        self.assertEqual((os.path.basename(p4), ow), ("動画 A (2).cut-plan.json", True))   # 別名の (2) も自分が書いたものなら上書き(書き出すたびに増えない)

    def test_srt_never_overwrites(self):
        names = [os.path.basename(P.save_beside(self.media, ".srt", b"1\n", None)[0]) for _ in range(3)]
        self.assertEqual(names, ["動画 A.srt", "動画 A (2).srt", "動画 A (3).srt"])
        self.assertEqual([n for n in os.listdir(self.tmp) if n.startswith(".tmp-")], [])   # 一時ファイルが残らない

    def test_does_not_clobber_file_created_meanwhile(self):
        """名前を決めてから置くまでの間に同じ名前のファイルができても、上書きしない(ハードリンクで置く)。"""
        real_lexists = os.path.lexists
        target = os.path.join(self.tmp, "動画 A.srt")
        calls = []

        def racy(p):
            if p == target:   # 確認では「無い」と見えたが、その直後に他のアプリが作った(以後の確認でも見えない最悪の場合)
                if not calls:
                    calls.append(1)
                    with open(target, "wb") as f:
                        f.write(b"other")
                return False
            return real_lexists(p)
        try:
            os.path.lexists = racy
            p, _ = P.save_beside(self.media, ".srt", b"mine", None)
        finally:
            os.path.lexists = real_lexists
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"other")
        self.assertEqual(os.path.basename(p), "動画 A (2).srt")

    def test_permission_error_is_400(self):
        real = tempfile.mkstemp

        def deny(*a, **k):
            raise PermissionError(13, "Permission denied", self.tmp)
        try:
            tempfile.mkstemp = deny
            with self.assertRaises(P.PipelineError) as cm:
                P.save_beside(self.media, ".srt", b"1", None)
        finally:
            tempfile.mkstemp = real
        self.assertEqual((cm.exception.code, cm.exception.status), ("no_write", 400))
        with self.assertRaises(P.PipelineError) as cm:
            P.save_beside(os.path.join(self.tmp, "無いフォルダ", "a.mp4"), ".srt", b"1", None)
        self.assertEqual(cm.exception.code, "no_dir")


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_runtime_dir_env(self):
        old = os.environ.get("YTT_RUNTIME_DIR")
        try:
            os.environ.pop("YTT_RUNTIME_DIR", None)
            self.assertEqual(P.runtime_dir("/a/b/transcribe-tool"), os.path.join(os.path.abspath("/a/b"), ".runtime"))
            os.environ["YTT_RUNTIME_DIR"] = self.dir
            self.assertEqual(P.runtime_dir("/a/b/transcribe-tool"), self.dir)
            self.assertEqual(S.runtime_path_dir(), self.dir)
        finally:
            if old is None:
                os.environ.pop("YTT_RUNTIME_DIR", None)
            else:
                os.environ["YTT_RUNTIME_DIR"] = old

    def test_write_remove_only_own(self):
        p = P.write_runtime(self.dir, "transcribe", 8776, "0.9.9")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual((d["tool"], d["port"], d["version"]), ("transcribe", 8776, "0.9.9"))
        self.assertFalse(P.remove_runtime(self.dir, "transcribe", 8777))   # 別のポートで動いている同じツールの記録は消さない
        self.assertTrue(os.path.exists(p))
        self.assertTrue(P.remove_runtime(self.dir, "transcribe", 8776))
        self.assertFalse(os.path.exists(p))
        self.assertIsNone(P.write_runtime(os.path.join(self.dir, "x\0y"), "transcribe", 1, "v"))   # 書けなくても例外にしない

    def test_entries_validation(self):
        write_json(os.path.join(self.dir, "studio.json"), {"tool": "studio", "port": 8801})
        write_json(os.path.join(self.dir, "cut2resolve.json"), {"tool": "cut2resolve", "port": "8810"})     # 文字列
        write_json(os.path.join(self.dir, "evil.json"), {"tool": "evil", "port": 22})                         # 知らないツール
        self.assertEqual(P.read_runtime_entries(self.dir), [("studio", 8801)])
        for bad in (0, 70000, True, 8.5, None, -1):
            self.assertFalse(P.valid_port(bad), bad)
        write_json(os.path.join(self.dir, "studio.json"), {"tool": "cut2resolve", "port": 8801})              # 名前と中身が違う
        self.assertEqual(P.read_runtime_entries(self.dir), [])


class _PingServer:
    """/api/ping に指定の app で答える小さなサーバー(hang=True なら接続を受けても答えない)。"""

    def __init__(self, app, hang=False):
        import http.server
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if hang:
                    time.sleep(2)
                body = json.dumps({"app": app, "version": "x"}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:   # 問い合わせ側が時間切れで先に切った
                    pass

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def start_server(tmp, port, runtime):
    for n in ("serve.py", "index.html", "app.js", "ui-kit.js", "hololive-roster.json", "pipeline_io.py", "resolve_export.py"):
        shutil.copy(os.path.join(HERE, n), tmp)
    for n in ("tx_worker.py",):   # 文字起こしワーカー(あれば一緒に写す。まだ無い環境でも他の確認は動くように)
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            shutil.copy(p, tmp)
    env = dict(os.environ, TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.005", YTT_RUNTIME_DIR=runtime)
    proc = subprocess.Popen([sys.executable, os.path.join(tmp, "serve.py"), str(port), "--no-open"], cwd=tmp, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:%d/api/ping" % port, timeout=1):
                return proc
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("サーバーが起動しません")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestPipelineHttp(unittest.TestCase):
    """受け渡しの API(docs/pipeline.md の 6)と、HTTP の検査。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.media_dir = os.path.join(cls.tmp, "exports")
        os.makedirs(cls.media_dir)
        cls.wav = os.path.join(cls.media_dir, "動画_0012.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12", cls.wav], check=True)
        cls.runtime = os.path.join(cls.tmp, ".runtime")
        cls.port = free_port()
        cls.proc = start_server(cls.tmp, cls.port, cls.runtime)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, headers=None, raw=False):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode())
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=data, headers=h)
        try:
            with self.opener.open(req, timeout=30) as r:
                d = r.read()
                return (r.status, dict(r.headers), d) if raw else json.loads(d)
        except urllib.error.HTTPError as e:
            d = e.read()
            if raw:
                return e.code, dict(e.headers), d
            try:
                return {"_status": e.code, **json.loads(d or b"{}")}
            except ValueError:
                return {"_status": e.code, "_raw": d}

    def transcribe(self, path, **extra):
        j = self.call("POST", "/api/transcribe", dict({"sourcePath": path, "model": "small", "autoGloss": False}, **extra))
        self.assertIn("id", j, j)
        end = time.time() + 60
        while time.time() < end:
            x = next(v for v in self.call("GET", "/api/jobs")["jobs"] if v["id"] == j["id"])
            if x["state"] in ("done", "error", "cancelled"):
                return x
            time.sleep(0.05)
        self.fail("ジョブが終わりません")

    def q(self, v):
        return urllib.parse.quote(v)

    def write_clip(self, obj, name="動画_0012.clip.json"):
        write_json(os.path.join(self.media_dir, name), obj)

    def tearDown(self):
        for n in os.listdir(self.media_dir):
            if n != os.path.basename(self.wav):
                os.unlink(os.path.join(self.media_dir, n))

    # ---- .clip.json ----
    def test_transcribe_reads_clip_and_transcript_v1(self):
        self.write_clip(clip_obj(media={"path": "C:\\別のPC\\動画_0012.wav", "name": "動画_0012.wav", "durationSec": 12.0}))
        job = self.transcribe(self.wav)
        self.assertEqual((job["state"], job["warnings"], job["hasClip"]), ("done", [], True))
        doc = self.call("GET", "/api/transcript?id=" + job["tid"])
        self.assertEqual(doc["clip"]["range"], {"start": 1234.5, "end": 1258.5})
        self.assertTrue(next(x for x in self.call("GET", "/api/transcripts")["items"] if x["id"] == job["tid"])["hasClip"])
        # 編集の保存で clip が消えない
        segs = doc["segments"]
        segs[0]["cutState"] = "cut"
        segs[1]["proofed"] = True
        r = self.call("PUT", "/api/transcript?id=" + job["tid"], {"title": doc["title"], "speakers": [{"id": "S1", "name": "トワ"}], "segments": segs, "baseUpdatedAt": doc["updatedAt"]})
        self.assertTrue(r["ok"])
        t = self.call("GET", "/api/transcript-v1?id=" + job["tid"])
        self.assertEqual(t["schema"], "youtube-tools-transcript/v1")
        self.assertEqual(t["clip"]["range"]["start"], 1234.5)
        self.assertEqual([g["cut"] for g in t["segments"][:2]], [True, False])
        self.assertEqual([g["proofed"] for g in t["segments"][:2]], [False, True])
        self.assertEqual(t["segments"], sorted(t["segments"], key=lambda g: g["start"]))
        self.assertNotIn("original", t)
        self.assertEqual(self.call("GET", "/api/transcript-v1?id=../x").get("_status"), 404)

    def test_range_transcription_keeps_clip_and_file_times(self):
        """範囲指定でも clip はそのまま、行の時刻は動画ファイルの先頭基準(元の配信の時刻 = range.start + 行の時刻)。"""
        self.write_clip(clip_obj())
        job = self.transcribe(self.wav, start=4, end=10)
        doc = self.call("GET", "/api/transcript?id=" + job["tid"])
        self.assertEqual(doc["clip"]["range"]["start"], 1234.5)
        self.assertGreaterEqual(doc["segments"][0]["start"], 4.0)
        t = self.call("GET", "/api/transcript-v1?id=" + job["tid"])
        self.assertEqual(t["transcribedRange"], {"start": 4, "end": 10})
        self.assertGreaterEqual(t["segments"][0]["start"], 4.0)

    def test_bad_clip_is_ignored_with_warning(self):
        self.write_clip(clip_obj(schema="youtube-tools-clip/v2"))
        job = self.transcribe(self.wav)
        self.assertEqual(job["state"], "done")
        self.assertEqual(len(job["warnings"]), 1)
        self.assertIn("未対応の版", job["warnings"][0])
        self.assertNotIn("clip", self.call("GET", "/api/transcript?id=" + job["tid"]))
        # フォルダ一括でも同じ
        self.write_clip(clip_obj())
        r = self.call("POST", "/api/transcribe-batch", {"paths": [self.wav, self.wav], "skipDone": False, "model": "small", "autoGloss": False})
        self.assertEqual(len(r["added"]), 1)   # 同じファイルは1回だけ
        self.assertTrue(r["added"][0]["hasClip"])

    def test_clip_info(self):
        r = self.call("GET", "/api/clip-info?path=" + self.q(self.wav))
        self.assertEqual((r["clip"], r["mediaPath"], r["warning"]), (None, os.path.abspath(self.wav), None))   # 無ければ null
        self.write_clip(clip_obj(media={"path": "C:\\別のPC\\x.mp4", "name": "動画_0012.wav"}))
        r = self.call("GET", "/api/clip-info?path=" + self.q(self.wav))
        self.assertEqual(r["clip"]["source"]["videoId"], "abcdefghijk")
        self.assertTrue(r["clipPath"].endswith("動画_0012.clip.json"))
        cj = os.path.join(self.media_dir, "動画_0012.clip.json")
        r = self.call("GET", "/api/clip-info?path=" + self.q(cj))            # ?clip= 用: .clip.json から動画を探す
        self.assertEqual(r["mediaPath"], os.path.abspath(self.wav))
        self.write_clip({"schema": "youtube-tools-clip/v1", "range": {"start": 5}})
        r = self.call("GET", "/api/clip-info?path=" + self.q(self.wav))
        self.assertIsNone(r["clip"])
        self.assertIn("range", r["warning"])
        r = self.call("GET", "/api/clip-info?path=" + self.q(os.path.join(self.media_dir, "無い.mp4")))
        self.assertEqual((r["clip"], r["mediaPath"]), (None, None))
        self.assertIn("見つかりません", r["warning"])
        self.assertEqual(self.call("GET", "/api/clip-info?path=").get("_status"), 400)
        for unc in ("\\\\evil.example\\share\\a.mp4", "//evil.example/share/a.mp4", "\\\\?\\UNC\\evil\\s\\a.mp4"):
            r = self.call("GET", "/api/clip-info?path=" + self.q(unc))           # ネットワークのパスは調べない(Windows の資格情報の漏れ対策)
            self.assertEqual((r["clip"], r["mediaPath"]), (None, None), unc)
            self.assertIn("ネットワーク", r["warning"])
        self.assertEqual(self.call("GET", "/api/clip-info?path=" + self.q(os.path.join(self.tmp, "serve.py"))).get("error"), "bad_ext")

    # ---- 動画の隣への保存 ----
    def make_edited(self):
        job = self.transcribe(self.wav)
        doc = self.call("GET", "/api/transcript?id=" + job["tid"])
        segs = doc["segments"]
        segs[1]["cutState"] = "cut"
        r = self.call("PUT", "/api/transcript?id=" + doc["id"], {"title": doc["title"], "speakers": [], "segments": segs})
        return doc["id"], r["updatedAt"], segs

    def test_export_file_transcript_and_overwrite_rule(self):
        tid, upd, segs = self.make_edited()
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "transcript-v1", "baseUpdatedAt": upd})
        self.assertEqual((r["name"], r["overwritten"], r["format"]), ("動画_0012.transcript.json", False, "transcript-v1"))
        self.assertEqual(os.path.dirname(r["path"]), os.path.abspath(self.media_dir))
        with open(r["path"], "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))                        # BOM なし
        t = json.loads(raw)
        self.assertEqual((t["schema"], t["media"]["name"], len(t["segments"])), ("youtube-tools-transcript/v1", "動画_0012.wav", r["count"]))
        r2 = self.call("POST", "/api/export-file", {"id": tid, "format": "transcript-v1"})
        self.assertEqual((r2["path"], r2["overwritten"]), (r["path"], True))      # 前に書いたものは上書き
        with open(r["path"], "w", encoding="utf-8") as f:                           # 手で別の内容に置き換えた → 別名
            json.dump({"note": "user file"}, f)
        r3 = self.call("POST", "/api/export-file", {"id": tid, "format": "transcript-v1"})
        self.assertEqual((r3["name"], r3["overwritten"]), ("動画_0012 (2).transcript.json", False))
        # 画面の表示が保存済みと違う(古い版を土台にしている)→ 409
        self.assertEqual(self.call("POST", "/api/export-file", {"id": tid, "format": "srt", "baseUpdatedAt": upd - 1}).get("_status"), 409)
        self.assertEqual(self.call("POST", "/api/export-file", {"id": tid, "format": "pdf"}).get("error"), "bad_format")
        self.assertEqual(self.call("POST", "/api/export-file", {"id": "../x", "format": "srt"}).get("_status"), 404)

    def test_export_file_srt_and_cut_plan(self):
        tid, _upd, segs = self.make_edited()
        names = [self.call("POST", "/api/export-file", {"id": tid, "format": "srt"})["name"] for _ in range(2)]
        self.assertEqual(names, ["動画_0012.srt", "動画_0012 (2).srt"])            # SRT は上書きしない
        with open(os.path.join(self.media_dir, "動画_0012.srt"), encoding="utf-8") as f:
            srt = f.read()
        self.assertTrue(srt.startswith("1\n00:00:00,000 --> 00:00:04,000\nテスト文1\n\n2\n"))   # カット済の行も字幕には出す
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "srt", "speakerNames": True, "wrap": 3})
        with open(r["path"], encoding="utf-8") as f:
            self.assertIn("テスト\n文1\n", f.read())
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "cut-plan-v1"})
        self.assertEqual(r["name"], "動画_0012.cut-plan.json")
        with open(r["path"], encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(plan["schema"], "youtube-tools-cut-plan/v1")
        cut = next(g for g in segs if g.get("cutState") == "cut")
        self.assertEqual(plan["segments"][0]["end"], cut["start"])                   # カット済の行の手前で区切れる
        self.assertEqual(plan["segments"][1]["start"], cut["end"])
        self.assertTrue(all(g["status"] == "adopted" for g in plan["segments"]))
        # 全部カット済 → 残す区間なし
        for g in segs:
            g["cutState"] = "cut"
        self.call("PUT", "/api/transcript?id=" + tid, {"title": "x", "speakers": [], "segments": segs})
        self.assertEqual(self.call("POST", "/api/export-file", {"id": tid, "format": "cut-plan-v1"}).get("error"), "empty")

    def test_export_file_without_media(self):
        tmp2 = os.path.join(self.tmp, "gone")
        os.makedirs(tmp2, exist_ok=True)
        src = os.path.join(tmp2, "消える.wav")
        shutil.copy(self.wav, src)
        job = self.transcribe(src)
        os.unlink(src)
        r = self.call("POST", "/api/export-file", {"id": job["tid"], "format": "transcript-v1"})
        self.assertEqual((r.get("_status"), r.get("error")), (400, "no_media"))

    # ---- .runtime と /api/siblings ----
    def test_runtime_file_and_siblings(self):
        with open(os.path.join(self.runtime, "transcribe.json"), encoding="utf-8") as f:
            me = json.load(f)
        self.assertEqual((me["tool"], me["port"]), ("transcribe", self.port))
        studio, hang, wrong = _PingServer("clip-studio"), _PingServer("cut2resolve", hang=True), _PingServer("clip-studio")
        try:
            write_json(os.path.join(self.runtime, "studio.json"), {"tool": "studio", "port": studio.port})
            write_json(os.path.join(self.runtime, "cut2resolve.json"), {"tool": "cut2resolve", "port": hang.port})
            t0 = time.time()
            r = self.call("GET", "/api/siblings")
            self.assertLess(time.time() - t0, 1.5)                                   # 答えないサーバーがあっても待たされない
            self.assertEqual(r, {"tools": {"transcribe": self.port, "studio": studio.port}})
            write_json(os.path.join(self.runtime, "cut2resolve.json"), {"tool": "cut2resolve", "port": wrong.port})   # 答えるが app が違う
            self.assertEqual(self.call("GET", "/api/siblings"), {"tools": {"transcribe": self.port, "studio": studio.port}})
            write_json(os.path.join(self.runtime, "studio.json"), {"tool": "studio", "port": free_port()})       # 誰もいない
            self.assertEqual(self.call("GET", "/api/siblings"), {"tools": {"transcribe": self.port}})
        finally:
            studio.close()
            hang.close()
            wrong.close()
            for n in ("studio.json", "cut2resolve.json"):
                try:
                    os.unlink(os.path.join(self.runtime, n))
                except OSError:
                    pass

    # ---- HTTP の検査 ----
    def test_navigation_from_other_tool_is_allowed_but_api_is_not(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        st, hd, body = self.call("GET", "/?media=" + self.q(self.wav), headers=nav, raw=True)
        self.assertEqual(st, 200)
        self.assertEqual(hd.get("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", hd.get("Content-Security-Policy", ""))
        self.assertEqual(self.call("GET", "/", headers=dict(nav, **{"Sec-Fetch-Site": "cross-site"}), raw=True)[0], 200)
        self.assertEqual(self.call("GET", "/", headers=dict(nav, **{"Sec-Fetch-Dest": "iframe"}), raw=True)[0], 403)
        self.assertEqual(self.call("GET", "/", headers=dict(nav, **{"Sec-Fetch-Mode": "cors"}), raw=True)[0], 403)
        r = self.call("GET", "/api/transcripts", headers=nav)
        self.assertEqual((r["_status"], r["error"]), (403, "forbidden"))
        self.assertIn("message", r)                                                  # 理由も JSON で返す
        self.assertEqual(self.call("GET", "/api/ping", headers={"Sec-Fetch-Site": "same-origin"})["app"], "transcribe-tool")

    def test_origin_and_body_checks(self):
        ok = "http://127.0.0.1:%d" % self.port
        self.assertEqual(self.call("PUT", "/api/settings", {"glossary": ""}, headers={"Origin": ok}), {"ok": True})
        for bad in (ok + "http://", "http://evil.example", "null", "https://127.0.0.1:%d" % self.port):
            self.assertEqual(self.call("PUT", "/api/settings", {"glossary": ""}, headers={"Origin": bad}).get("_status"), 403, bad)
        r = self.call("PUT", "/api/settings", b'{"a": NaN}')
        self.assertEqual((r["_status"], r["error"]), (400, "bad_json"))
        r = self.call("PUT", "/api/settings", b"{}", headers={"Content-Type": "text/plain"})
        self.assertEqual((r["_status"], r["error"]), (415, "bad_type"))
        # 想定外の例外(深すぎる JSON で RecursionError)でも、接続を切らずに 500 と理由を返す
        deep = b'{"a":' + b"[" * 100000 + b"]" * 100000 + b"}"
        r = self.call("PUT", "/api/settings", deep)
        self.assertEqual((r["_status"], r["error"]), (500, "internal"))
        self.assertEqual(self.call("GET", "/api/ping")["app"], "transcribe-tool")   # サーバーは生きている
        self.assertEqual(self.call("POST", "/api/transcribe", {"sourcePath": self.wav, "model": "hololive-roster.json"}).get("error"), "bad_model")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestRuntimeCleanup(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "SIGTERM の確認は Linux / Mac のみ")
    def test_runtime_removed_on_terminate(self):
        """終了の合図(SIGTERM)でも .runtime/transcribe.json と起動中の印を消す。"""
        tmp = tempfile.mkdtemp()
        try:
            runtime = os.path.join(tmp, "rt")
            port = free_port()
            proc = start_server(tmp, port, runtime)
            path = os.path.join(runtime, "transcribe.json")
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.exists(os.path.join(tmp, ".running.json")))
            proc.terminate()
            proc.wait(timeout=10)
            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".running.json")))   # 正常終了の扱い(次の起動で「異常終了」と出ない)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
