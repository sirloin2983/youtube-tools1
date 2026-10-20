#!/usr/bin/env python3
"""サーバー側のバグ直し・機能のテスト。

    python3 -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python3 -m unittest test_backend -q                        # これだけ

受け渡しの約束(notes:docs/spec/pipeline.md)の API(export-file(transcript-v1)/ siblings)は、
疑似モード(TRANSCRIBE_BACKEND=fake)のサーバーを空いているポートで起動して確かめる(ffmpeg が必要)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

TESTS = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "src", "editor")   # ツール(editor/)のフォルダ
UI_DIR = os.path.join(os.path.dirname(HERE), "app", "ui", "editor")   # 画面の部品(RV C2 で src/app/ui/editor へ)
os.environ.setdefault("YTT_CORE_DIR", os.path.dirname(HERE))   # 一時フォルダに写した serve.py が共通部品 ytt(リポジトリ直下)を見つけられるように
sys.path.insert(0, HERE)
sys.path.insert(0, TESTS)
import serve as S  # noqa: E402
import ed_state  # noqa: E402
from flow import jobs as _jobs  # noqa: E402
from human.proof import doc_jobs as _doc_jobs  # noqa: E402
from human.proof import learn as _learn  # noqa: E402
from human.proof import rerun as _rerun  # noqa: E402
from human.proof import speakers as _speakers  # noqa: E402
from human.proof import store as _store  # noqa: E402
from manage.cases import doclist as _doclist  # noqa: E402
from pipeline.transcribe import models as _models  # noqa: E402
from pipeline.transcribe import recognize as _recognize  # noqa: E402
from pipeline.transcribe import roster as _roster  # noqa: E402
from pipeline.transcribe import worker_client as _worker_client  # noqa: E402
from ytt import dictfmt as _dictfmt  # noqa: E402
from ytt import settings as _settings  # noqa: E402
from ytt import tools as _tools  # noqa: E402
from ytt import workdata as _workdata  # noqa: E402
from manage.cases import handoff_io as P  # noqa: E402   (.clip.json が指す動画・動画の隣への保存)
from pipeline.pack import resolve_export as RE  # noqa: E402   (受け渡しの JSON と SRT の組み立て build_*。RS3-E5b)
from ytt import fsio, runtime, schemas  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/(testkit)
import testkit  # noqa: E402

TID = "0123456789ab"


write_json = testkit.write_json   # 他の試験ファイルがここから読む


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
        self.tmp = testkit.tempdir(self)
        for name, value in (("TX_DIR", self.tmp), ("TMP_DIR", os.path.join(self.tmp, ".tmp")), ("SETTINGS", os.path.join(self.tmp, "settings.json"))):
            self.patch(_workdata, name, value)

    def patch(self, obj, name, value):
        """このテストの間だけ obj.name を value に(終わりに戻す)"""
        p = patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def put_doc(self, doc, tid=TID):
        write_json(_store.tx_path(tid), doc)


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

        with _store._save_lock:
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
        self._blocked_while_locked(lambda: _rerun.apply_retranscribe({"tid": TID, "model": "m", "autoDict": False}, {"s1": ("A", "")}))
        self.assertEqual(_store.read_transcript(TID)["segments"][0]["text"], "A")

    def test_range_waits_for_save_lock(self):
        self.put_doc(self.base_doc())
        spec = {"tid": TID, "model": "m", "autoDict": False, "range": [0, 4], "ids": ["s1", "s2"]}
        self._blocked_while_locked(lambda: _rerun.apply_range(spec, [{"start": 0, "end": 4, "raw": "新しい", "flag": ""}]))
        self.assertEqual([g["text"] for g in _store.read_transcript(TID)["segments"]], ["新しい"])

    def test_diarization_waits_for_save_lock(self):
        self.put_doc(self.base_doc())
        self._blocked_while_locked(lambda: _speakers.apply_diarization(TID, [(0, 4, 0)], 0.0, 0))
        self.assertEqual(_store.read_transcript(TID)["segments"][0]["speaker"], "S1")


class TestJobs(unittest.TestCase):
    def setUp(self):
        self.old = dict(_jobs._jobs)
        _jobs._jobs.clear()

    def tearDown(self):
        _jobs._jobs.clear()
        _jobs._jobs.update(self.old)

    def test_exclusive_checked_inside_add_job(self):
        """同じ文字起こしへの話者判別・再認識は、待機列に入れるときにも重ねない(確認と登録の間の割り込み対策)。"""
        _jobs.add_job({"title": "d", "tid": "t1"}, "diarize")
        with self.assertRaises(ed_state.ApiError) as cm:
            _jobs.add_job({"title": "r", "tid": "t1"}, "retranscribe")
        self.assertEqual(cm.exception.status, 409)
        _jobs.add_job({"title": "d2", "tid": "t2"}, "diarize")        # 別の文字起こしなら入る
        _jobs.add_job({"title": "al", "tid": "t1"}, "alt")             # 2つ目のエンジンは話者判別と同時でもよい(文書を書き換えない)
        with self.assertRaises(ed_state.ApiError):
            _jobs.add_job({"title": "al2", "tid": "t1"}, "alt")


class TestPerformance(StoreDir):
    def test_audio_span(self):
        self.assertEqual(_recognize.audio_span([{"start": 100, "end": 102}, {"start": 50, "end": 51}], 0, 3600), (50 - 0.3 - _recognize.AUDIO_MARGIN, 102 + 0.3 + _recognize.AUDIO_MARGIN))
        self.assertEqual(_recognize.audio_span([{"start": 1, "end": 2}], 0.5, 3.0), (0.5, 3.0))       # 文書の範囲の外は取り出さない
        self.assertEqual(_recognize.audio_span([{"start": 1, "end": 2}], 0, None)[1], 2 + 0.3 + _recognize.AUDIO_MARGIN)

    def _long_doc(self):
        src = os.path.join(self.tmp, "long.wav")
        with open(src, "wb") as f:
            f.write(b"x" * 2000)
        segs = [{"id": "s%d" % i, "start": i * 10.0, "end": i * 10.0 + 5, "text": "行%d" % i, "speaker": "", "flag": "", "proofed": True} for i in range(360)]
        self.put_doc({"id": TID, "sourcePath": src, "start": 0, "end": 3600.0, "whole": True, "duration": 3600.0,
                      "original": [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in segs], "segments": segs, "updatedAt": 1})

    def _run_capturing(self, fn, job):
        seen = []
        with patch.object(_recognize, "extract_audio", lambda job, spec, wav: seen.append((spec["start"], spec["end"]))), \
                patch.dict(os.environ, {"TRANSCRIBE_BACKEND": "fake", "TRANSCRIBE_FAKE_DELAY": os.environ.get("TRANSCRIBE_FAKE_DELAY", "0")}):
            fn(job)
        return seen

    def _extracts_only_needed_span(self):
        """1時間の文書の2行だけを再認識するとき、1時間分ではなく、その行の前後だけを取り出す。"""
        self._long_doc()
        spec = {"tid": TID, "ids": ["s100", "s101"], "mode": "each", "range": None, "model": "small", "language": "ja", "beam": 5, "vadMode": "off",
                "wordSplit": False, "stripPunct": True, "device": "auto", "boost": False, "autoDict": False, "glossary": [], "title": "t"}
        job = {"id": "j1" + "0" * 10, "spec": spec, "cancel": False, "state": "queued", "progress": 0, "phase": "", "proc": None}
        seen = self._run_capturing(_rerun.run_retranscribe, job)
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(len(seen), 1)
        a, b = seen[0]
        self.assertLessEqual(a, 1000 - 0.3)
        self.assertGreaterEqual(b, 1015 + 0.3)
        self.assertLess(b - a, 30)
        return _store.read_transcript(TID)

    def test_retranscribe_extracts_only_needed_span_primary(self):
        """層が正: 取り出す範囲は同じ。行は校正済みなので機械の文字で置き換わらず、印 MACH_CHANGED が付く"""
        from human.proof import layers
        doc = self._extracts_only_needed_span()
        g = doc["segments"][100]
        self.assertEqual((g["text"], g.get("proofed")), ("行100", True))
        self.assertIn(layers.MACH_CHANGED, g["flag"])

    def test_idle_model_release(self):
        """認識ワーカーの中(IN_WORKER)でのモデルの手放し。サーバー側(ワーカーごと終わらせる)は test_worker.py"""
        old = (dict(_models._models), _models._model_used[0], _models.MODEL_IDLE_SEC, _worker_client.IN_WORKER)
        _worker_client.IN_WORKER = True
        try:
            _models._models.clear()
            _models._models[("large-v3", "cpu")] = object()
            _models.MODEL_IDLE_SEC = 900
            now = time.time()
            _models._model_used[0] = now - 100
            self.assertFalse(_worker_client.release_idle_models(now))            # まだ使って間もない
            _models._model_used[0] = now - 901
            self.assertTrue(_worker_client.release_idle_models(now))
            self.assertEqual(_models._models, {})
            _models._models[("small", "cpu")] = object()
            _models.MODEL_IDLE_SEC = 0
            self.assertFalse(_worker_client.release_idle_models(now + 10 ** 6))   # 0 は手放さない
        finally:
            _models._models.clear()
            _models._models.update(old[0])
            _models._model_used[0], _models.MODEL_IDLE_SEC, _worker_client.IN_WORKER = old[1], old[2], old[3]

    def test_summary_cache_without_rereading(self):
        self.put_doc({"id": TID, "title": "一", "sourcePath": "/v/a.mp4", "start": 0, "end": 10, "whole": True, "segments": [], "createdAt": 1})
        items = _doclist.list_transcripts()
        self.assertEqual((items[0]["title"], items[0]["hasClip"]), ("一", False))
        self.assertNotIn("_sourcePath", items[0])
        time.sleep(0.01)
        self.put_doc({"id": TID, "title": "二番目", "sourcePath": "/v/a.mp4", "clip": clip_obj(), "segments": [], "createdAt": 1})
        items = _doclist.list_transcripts()
        self.assertEqual((items[0]["title"], items[0]["hasClip"]), ("二番目", True))   # 書き換わったら読み直す
        os.unlink(_store.tx_path(TID))
        self.assertEqual(_doclist.list_transcripts(), [])
        self.assertNotIn(TID, _store._summary_cache)

    def test_list_fields_for_history(self):
        """履歴の一覧の項目(校正の進み具合・長さ・元の配信・配信者・元の動画の有無・パック)"""
        media_dir = os.path.join(self.tmp, "exports")
        os.makedirs(media_dir)
        media = os.path.join(media_dir, "01_見どころ.mp4")
        with open(media, "wb") as f:
            f.write(b"x")
        segs = [{"id": "s1", "start": 0, "end": 1, "text": "あ", "proofed": True},
                {"id": "s2", "start": 1, "end": 2, "text": "い", "proofed": True, "cutState": "cut"},
                {"id": "s3", "start": 2, "end": 3, "text": "う", "flag": "要確認: 聞き取りにくい"},
                {"id": "s4", "start": 3, "end": 4, "text": " ", "proofed": True}]   # 文字の無い行は数えない(校正済みの印があっても)
        self.put_doc({"id": TID, "title": "配信 見どころ", "sourcePath": media, "start": 0, "end": None, "whole": True, "duration": 24.0,
                      "segments": segs, "clip": clip_obj(), "createdAt": 5, "updatedAt": 9})
        other = "fedcba987654"
        self.put_doc({"id": other, "title": "共有の動画", "sourcePath": "\\\\server\\share\\a.mp4", "start": 10, "end": 70,
                      "segments": [], "createdAt": 3}, tid=other)
        studio = os.path.join(self.tmp, "studio-data.json")
        write_json(studio, {"videos": {"abcdefghijk": {"title": "スタジオの題名", "channel": "星見ルナ", "marks": []}}})
        old = (_workdata.STUDIO_DATA, _doclist.PACK_CHECK_BUDGET)
        _workdata.STUDIO_DATA = studio
        try:
            items = {x["id"]: x for x in _doclist.list_transcripts()}
            a = items[TID]
            self.assertEqual((a["rows"], a["proofed"], a["cut"], a["flagged"], a["durationSec"]), (3, 2, 1, 1, 24.0))
            self.assertEqual((a["videoId"], a["clipTitle"], a["clipStart"], a["clipEnd"], a["markLabel"]),
                             ("abcdefghijk", "配信<b>タイトル</b>", 1234.5, 1258.5, "見どころ"))
            self.assertEqual((a["channel"], a["streamTitle"], a["mediaOk"], a["pack"]), ("星見ルナ", "スタジオの題名", True, None))
            self.assertNotIn("_sp", a)
            b = items[other]
            self.assertEqual((b["durationSec"], b["videoId"], b["channel"], b["hasClip"]), (60.0, "", "", False))
            self.assertIsNone(b["mediaOk"])   # ネットワーク上のパスは調べない(資格情報を送らない)
            # パック(案件の画面と同じ判定: <名前>_pack のパックを作った記録。記録は YTT_CUT2RESOLVE_DIR の下 = リポジトリの .data に書かない)
            from flow import packrec
            pk = os.path.join(media_dir, "01_見どころ_pack")
            os.makedirs(pk)
            write_json(os.path.join(pk, "cut-plan.json"), {})                   # フォルダの中の cut-plan.json だけでは「パックあり」にしない
            self.assertIsNone({x["id"]: x for x in _doclist.list_transcripts()}[TID]["pack"])
            c2r = os.path.join(self.tmp, "cut2resolve")
            lua = os.path.join(pk, "create_resolve_textplus_project.lua")
            write_json(lua, {})
            time.sleep(0.01)
            write_json(studio, {"videos": {"abcdefghijk": {"title": "", "channel": "朝霧ソラ"}}})   # スタジオの data.json が変われば読み直す
            with patch.dict(os.environ, {"YTT_CUT2RESOLVE_DIR": c2r}):
                packrec.write_record({"out_dir": pk, "files": [("textplus_script", lua)]}, media, True, c2r_dir=c2r)
                a = {x["id"]: x for x in _doclist.list_transcripts()}[TID]
            self.assertEqual((a["pack"]["textplus"], a["pack"]["updatedAt"] > 0, a["channel"], a.get("streamTitle")), (True, True, "朝霧ソラ", None))
            os.unlink(media)
            self.assertIs({x["id"]: x for x in _doclist.list_transcripts()}[TID]["mediaOk"], False)
            _doclist.PACK_CHECK_BUDGET = -1   # 調べる時間を使い切ったら、残りは「不明」(一覧を止めない)
            a = {x["id"]: x for x in _doclist.list_transcripts()}[TID]
            self.assertEqual((a["mediaOk"], a["pack"]), (None, None))
        finally:
            _workdata.STUDIO_DATA, _doclist.PACK_CHECK_BUDGET = old


class TestStartupChecks(StoreDir):
    def test_checks(self):
        self.assertFalse(hasattr(S, "INDEX"))   # RS8 C4: 編集の画面のページ index.html は無い(入口が案件の画面へ転送する) = その検査もない
        self.patch(ed_state, "APP_JS", testkit.write_text(os.path.join(self.tmp, "app.js"), "// app"))
        self.patch(_tools, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
        self.assertEqual(S.startup_checks(), [])
        _tools.find_ffmpeg = lambda: None
        blocker = testkit.write_text(os.path.join(self.tmp, "file"), "x")
        _workdata.TX_DIR = os.path.join(blocker, "transcripts")    # ファイルの下には作れない = 書き込めない保存先
        w = " / ".join(S.startup_checks())
        for word in ("ffmpeg", "保存先に書き込めません"):
            self.assertIn(word, w)
        os.unlink(ed_state.APP_JS)
        self.assertIn("app.js が見つかりません", " / ".join(S.startup_checks()))
        self.assertNotIn("index.html", " / ".join(S.startup_checks()))   # 画面のページを確かめない


class TestBomTolerant(StoreDir):
    def test_settings_and_roster_with_bom(self):
        """メモ帳の「UTF-8 (BOM 付き)」で直した settings.json・名簿でも読める。"""
        with open(_workdata.SETTINGS, "w", encoding="utf-8-sig") as f:
            json.dump({"replacements": "よっきゃ=>陽キャ"}, f, ensure_ascii=False)
        self.assertEqual(_dictfmt.parse_replacements(_settings.load_settings().get("replacements")), [("よっきゃ", "陽キャ")])
        self.patch(_roster, "ROSTER", os.path.join(self.tmp, "roster.json"))
        with open(_roster.ROSTER, "w", encoding="utf-8-sig") as f:
            json.dump({"asOf": "2026-09-22", "groups": [{"id": "g", "label": "G", "names": ["兎田ぺこら"]}]}, f, ensure_ascii=False)
        self.assertEqual(_learn.load_roster()["groups"][0]["names"], ["兎田ぺこら"])


class TestModelName(unittest.TestCase):
    def test_local_paths_are_not_model_names(self):
        """faster-whisper は名前と同じフォルダがあればそれを読み込むので、手元に実在する名前は断る。"""
        self.assertTrue(_worker_client.valid_model("large-v3"))
        self.assertTrue(_worker_client.valid_model("kotoba-tech/kotoba-whisper-v2.0-faster"))
        for bad in ("../x", ".hidden", "a/b/c", "C:\\x", "", "x" * 101, None):
            self.assertFalse(_worker_client.valid_model(bad), bad)
        tmp = testkit.tempdir(self)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp)
        os.makedirs("mymodel")
        os.makedirs(os.path.join("org", "local"))
        self.assertFalse(_worker_client.valid_model("mymodel"))       # 起動したフォルダからの相対で実在する
        self.assertFalse(_worker_client.valid_model("org/local"))
        self.assertTrue(_worker_client.valid_model("org/remote"))
        self.assertFalse(_worker_client.valid_model("transcripts" if os.path.isdir(os.path.join(_workdata.ROOT, "transcripts")) else "hololive-roster.json"))   # ツールのフォルダの中の名前


class TestClipValidation(unittest.TestCase):
    def test_valid_clip_keeps_unknown_fields(self):
        clip, warn = schemas.validate_clip(clip_obj())
        self.assertIsNone(warn)
        self.assertEqual(clip["futureField"], {"x": 1})     # 知らない項目も残す(前方互換)
        self.assertEqual(schemas.clip_offset(clip), 1234.5)
        clip2, _ = schemas.validate_clip(clip_obj(export={"mode": "fast", "actualStart": 1231.0}))
        self.assertEqual(schemas.clip_offset(clip2), 1231.0)      # 高速書き出しのずれは actualStart を優先

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
            clip, warn = schemas.validate_clip(obj)
            self.assertIsNone(clip, obj)
            self.assertIn(word, warn)

    def test_files_and_media_resolution(self):
        tmp = testkit.tempdir(self)
        media = os.path.join(tmp, "動画_0012.mp4")
        with open(media, "wb") as f:
            f.write(b"x")
        cj = os.path.join(tmp, "動画_0012.clip.json")                          # 動画の隣の置き方も読む
        self.assertEqual(schemas.clip_path_for(media), os.path.join(tmp, schemas.WORK_DIR, "動画_0012.clip.json"))   # 書くのは 作業用\
        self.assertEqual(schemas.find_clip(media), (None, None, None))           # 無ければ何もしない
        with open(cj, "w", encoding="utf-8-sig") as f:                     # BOM 付きでも読む
            json.dump(clip_obj(), f, ensure_ascii=False)
        clip, warn, path = schemas.find_clip(media, 24.5)
        self.assertEqual((clip["range"]["start"], warn, path), (1234.5, None, cj))
        clip, warn, _ = schemas.find_clip(media, 60.0)                          # 長さが大きく違えば警告(clip は使う)
        self.assertIsNotNone(clip)
        self.assertIn("長さ", warn)
        # 壊れた JSON・大きすぎるファイルは使わない
        testkit.write_text(cj, "{broken")
        self.assertIsNone(schemas.load_clip_file(cj)[0])
        testkit.write_text(cj, " " * (schemas.MAX_CLIP_BYTES + 10))
        self.assertIn("大きすぎ", schemas.load_clip_file(cj)[1])


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
        t = RE.build_transcript_v1(d, "9.9.9")
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
        self.assertEqual(RE.build_transcript_v1(d, "1")["transcribedRange"], {"start": 100.0, "end": 160.0})

    def test_cut_plan_v1_uses_resolve_rule(self):
        t = RE.build_cut_plan_v1(sample_doc("/x/動画.mp4"), "1")
        self.assertEqual(t["schema"], "youtube-tools-cut-plan/v1")
        self.assertEqual([(g["start"], g["end"], g["status"], g["lines"]) for g in t["segments"]],
                         [(0.5, 4.0, "adopted", ["s1", "s2"]), (9.5, 11.0, "adopted", ["s5"])])   # カット済(s3)・空(s4)は除き、接する行はまとめる
        self.assertEqual(t["segments"][0]["label"], "一行目二行目")
        self.assertEqual(t["media"]["path"], "/x/動画.mp4")

    def test_srt_matches_screen_rules(self):
        text, n = RE.build_srt(sample_doc("/x/a.mp4"))
        self.assertEqual(n, 4)
        self.assertEqual(text, "1\n00:00:00,500 --> 00:00:02,000\n一行目\n\n2\n00:00:02,000 --> 00:00:04,000\n二行目\n\n"
                               "3\n00:00:06,000 --> 00:00:08,000\n三行目\n\n4\n00:00:09,500 --> 00:00:11,000\nとても長い行なので折り返されます\n")
        text, _ = RE.build_srt(sample_doc("/x/a.mp4"), wrap=8, speaker_names=True)
        self.assertIn("[ぺこら] 一行目\n", text)
        self.assertIn("[トワ] とても長い行なの\nで折り返されます\n", text)   # 8文字ごと(名前は数えない)
        self.assertIn("\n2\n00:00:02,000 --> 00:00:04,000\n二行目\n", text)   # 話者なしの行は名前を付けない


class TestSaveBeside(unittest.TestCase):
    def setUp(self):
        self.tmp = testkit.tempdir(self)
        self.media = os.path.join(self.tmp, "動画 A.mp4")
        with open(self.media, "wb") as f:
            f.write(b"x")

    def own(self, schema):
        return json.dumps({"schema": schema, "tool": {"name": "transcribe-tool", "version": "1"}}).encode()

    def test_overwrite_only_own_same_schema(self):
        sch = schemas.TRANSCRIPT_SCHEMA
        p1, ow = P.save_beside(self.media, ".transcript.json", self.own(sch), sch)
        self.assertEqual((os.path.basename(p1), ow), ("動画 A.transcript.json", False))
        p2, ow = P.save_beside(self.media, ".transcript.json", self.own(sch), sch)
        self.assertEqual((p2, ow), (p1, True))                                     # 前にこのツールが書いたものは上書き
        self.assertEqual(os.path.dirname(p1), os.path.join(self.tmp, schemas.WORK_DIR))   # 途中のファイルは 作業用\
        other = os.path.join(self.tmp, schemas.WORK_DIR, "動画 A.cut-plan.json")
        write_json(other, {"schema": schemas.CUT_PLAN_SCHEMA, "segments": []})           # 同じ schema でも他のツール(tool なし)が書いたもの
        p3, ow = P.save_beside(self.media, ".cut-plan.json", self.own(schemas.CUT_PLAN_SCHEMA), schemas.CUT_PLAN_SCHEMA)
        self.assertEqual((os.path.basename(p3), ow), ("動画 A (2).cut-plan.json", False))
        with open(other, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["segments"], [])                          # 元のファイルは無事
        p4, ow = P.save_beside(self.media, ".cut-plan.json", self.own(schemas.CUT_PLAN_SCHEMA), schemas.CUT_PLAN_SCHEMA)
        self.assertEqual((os.path.basename(p4), ow), ("動画 A (2).cut-plan.json", True))   # 別名の (2) も自分が書いたものなら上書き(書き出すたびに増えない)

    def test_srt_never_overwrites(self):
        names = [os.path.basename(P.save_beside(self.media, ".srt", b"1\n", None)[0]) for _ in range(3)]
        self.assertEqual(names, ["動画 A.srt", "動画 A (2).srt", "動画 A (3).srt"])
        self.assertEqual([n for n in os.listdir(os.path.join(self.tmp, schemas.WORK_DIR)) if n.startswith(".tmp-")], [])   # 一時ファイルが残らない

    def test_does_not_clobber_file_created_meanwhile(self):
        """名前を決めてから置くまでの間に同じ名前のファイルができても、上書きしない(ハードリンクで置く)。"""
        real_lexists = os.path.lexists
        target = os.path.join(self.tmp, schemas.WORK_DIR, "動画 A.srt")
        calls = []

        def racy(p):
            if p == target:   # 確認では「無い」と見えたが、その直後に他のアプリが作った(以後の確認でも見えない最悪の場合)
                if not calls:
                    calls.append(1)
                    with open(target, "wb") as f:
                        f.write(b"other")
                return False
            return real_lexists(p)
        with patch.object(os.path, "lexists", racy):
            p, _ = P.save_beside(self.media, ".srt", b"mine", None)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"other")
        self.assertEqual(os.path.basename(p), "動画 A (2).srt")

    def test_permission_error_is_400(self):
        def deny(*a, **k):
            raise PermissionError(13, "Permission denied", self.tmp)
        with patch.object(tempfile, "mkstemp", deny), self.assertRaises(P.PipelineError) as cm:
            P.save_beside(self.media, ".srt", b"1", None)
        self.assertEqual((cm.exception.code, cm.exception.status), ("no_write", 400))
        with self.assertRaises(P.PipelineError) as cm:
            P.save_beside(os.path.join(self.tmp, "無いフォルダ", "a.mp4"), ".srt", b"1", None)
        self.assertEqual(cm.exception.code, "no_dir")


class TestRuntime(unittest.TestCase):
    def setUp(self):
        self.dir = testkit.tempdir(self)

    def test_runtime_dir_env(self):
        with patch.dict(os.environ, {"YTT_RUNTIME_DIR": self.dir}):
            self.assertEqual(ed_state.runtime_path_dir(), self.dir)

    def test_entries_validation(self):
        write_json(os.path.join(self.dir, "studio.json"), {"tool": "studio", "port": 8801})
        write_json(os.path.join(self.dir, "cut2resolve.json"), {"tool": "cut2resolve", "port": "8810"})     # 文字列
        write_json(os.path.join(self.dir, "evil.json"), {"tool": "evil", "port": 22})                         # 知らないツール
        entries = lambda: [(t, info["port"]) for t in runtime.TOOL_APPS for info in [runtime.read_runtime(self.dir, t)] if info]   # noqa: E731
        self.assertEqual(entries(), [("studio", 8801)])
        for bad in (0, 70000, True, 8.5, None, -1):
            self.assertFalse(runtime.valid_port(bad), bad)
        write_json(os.path.join(self.dir, "studio.json"), {"tool": "cut2resolve", "port": 8801})              # 名前と中身が違う
        self.assertEqual(entries(), [])


class _PingServer:
    """/api/ping に指定の app で答える小さなサーバー"""

    def __init__(self, app):
        import http.server
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
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
    for n in ("serve.py", "hololive-roster.json") + tuple(n for n in sorted(os.listdir(HERE)) if n.startswith("ed_") and n.endswith(".py")):   # 段10 で serve.py から分けた部品。画面の部品は src/app/ui/editor(RV C2。YTT_EDITOR_UI_DIR で教える)
        shutil.copy(os.path.join(HERE, n), tmp)
    env = dict(os.environ, YTT_EDITOR_UI_DIR=UI_DIR,TRANSCRIBE_BACKEND="fake", TRANSCRIBE_FAKE_DELAY="0.005", YTT_RUNTIME_DIR=runtime,
               YTT_MACHINE_FILE=os.path.join(tmp, "machine.json"),   # この PC の設定は一時フォルダへ(src に書かない。RS7-1 S6b)
               YTT_CUT2RESOLVE_DIR=os.path.join(tmp, "cut2resolve"))   # パックを作った記録(flow/packrec)も一時フォルダへ(リポジトリの .data に書かない)
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
    """受け渡しの API(notes:docs/spec/pipeline.md の 6)と、HTTP の検査。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.media_dir = os.path.join(cls.tmp, "exports")
        os.makedirs(cls.media_dir)
        cls.wav = os.path.join(cls.media_dir, "動画_0012.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12", cls.wav], check=True)
        cls.runtime = os.path.join(cls.tmp, ".runtime")
        cls.port = testkit.free_port()
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
                p = os.path.join(self.media_dir, n)
                shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)   # 作業用\(途中のファイル)も消す

    # ---- .clip.json ----
    def export_v1(self, tid):
        """transcript-v1 の中身を、書き出された .transcript.json から読む(GET の口は無い)"""
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "transcript-v1"})
        return testkit.read_json(r["path"])

    def test_transcribe_reads_clip_and_transcript_v1(self):
        self.write_clip(clip_obj(media={"path": "C:\\別のPC\\動画_0012.wav", "name": "動画_0012.wav", "durationSec": 12.0}))
        job = self.transcribe(self.wav)
        self.assertEqual((job["state"], job["warnings"], job["hasClip"]), ("done", [], True))
        doc = self.call("GET", "/api/transcript?id=" + job["tid"])
        self.assertEqual(doc["clip"]["range"], {"start": 1234.5, "end": 1258.5})
        self.assertTrue(next(x for x in self.call("GET", "/api/transcripts")["items"] if x["id"] == job["tid"])["hasClip"])
        # 編集の保存で clip が消えない
        r = self.call("PUT", "/api/transcript?id=" + job["tid"], {"title": doc["title"], "speakers": [{"id": "S1", "name": "トワ"}], "segments": doc["segments"], "baseUpdatedAt": doc["updatedAt"]})
        self.assertTrue(r["ok"])
        t = self.export_v1(job["tid"])
        self.assertEqual(t["schema"], "youtube-tools-transcript/v1")
        self.assertEqual(t["clip"]["range"]["start"], 1234.5)
        self.assertEqual(self.call("POST", "/api/export-file", {"id": "../x", "format": "transcript-v1"}).get("_status"), 404)

    def test_range_transcription_keeps_clip_and_file_times(self):
        """範囲指定でも clip はそのまま、行の時刻は動画ファイルの先頭基準(元の配信の時刻 = range.start + 行の時刻)。"""
        self.write_clip(clip_obj())
        job = self.transcribe(self.wav, start=4, end=10)
        doc = self.call("GET", "/api/transcript?id=" + job["tid"])
        self.assertEqual(doc["clip"]["range"]["start"], 1234.5)
        self.assertGreaterEqual(doc["segments"][0]["start"], 4.0)
        t = self.export_v1(job["tid"])
        self.assertEqual(t["transcribedRange"], {"start": 4, "end": 10})
        self.assertGreaterEqual(t["segments"][0]["start"], 4.0)

    def test_bad_clip_is_ignored_with_warning(self):
        self.write_clip(clip_obj(schema="youtube-tools-clip/v2"))
        job = self.transcribe(self.wav)
        self.assertEqual(job["state"], "done")
        self.assertEqual(len(job["warnings"]), 1)
        self.assertNotIn("clip", self.call("GET", "/api/transcript?id=" + job["tid"]))

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
        with open(r["path"], "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))                        # BOM なし
        t = json.loads(raw)
        self.assertEqual((t["schema"], t["media"]["name"], len(t["segments"])), ("youtube-tools-transcript/v1", "動画_0012.wav", r["count"]))
        # 画面の表示が保存済みと違う(古い版を土台にしている)→ 409
        self.assertEqual(self.call("POST", "/api/export-file", {"id": tid, "format": "srt", "baseUpdatedAt": upd - 1}).get("_status"), 409)
        self.assertEqual(self.call("POST", "/api/export-file", {"id": tid, "format": "pdf"}).get("error"), "bad_format")
        self.assertEqual(self.call("POST", "/api/export-file", {"id": "../x", "format": "srt"}).get("_status"), 404)

    def test_export_file_srt_and_cut_plan(self):
        tid, _upd, segs = self.make_edited()
        self.assertEqual(self.call("POST", "/api/export-file", {"id": tid, "format": "srt"})["name"], "動画_0012.srt")
        with open(os.path.join(self.media_dir, "作業用", "動画_0012.srt"), encoding="utf-8") as f:
            srt = f.read()
        self.assertTrue(srt.startswith("1\n00:00:00,000 --> 00:00:04,000\nテスト文1\n\n2\n"))   # カット済の行も字幕には出す
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "srt", "speakerNames": True, "wrap": 3})
        with open(r["path"], encoding="utf-8") as f:
            self.assertIn("テスト\n文1\n", f.read())
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "cut-plan-v1"})
        self.assertEqual(r["name"], "動画_0012.cut-plan.json")
        plan = testkit.read_json(r["path"])
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
        me = testkit.read_json(os.path.join(self.runtime, "transcribe.json"))
        self.assertEqual((me["tool"], me["port"]), ("transcribe", self.port))
        studio = _PingServer("clip-studio")
        try:
            write_json(os.path.join(self.runtime, "studio.json"), {"tool": "studio", "port": studio.port})
            self.assertEqual(self.call("GET", "/api/siblings"), {"tools": {"transcribe": self.port, "studio": studio.port}})
        finally:
            studio.close()
            try:
                os.unlink(os.path.join(self.runtime, "studio.json"))
            except OSError:
                pass

    # ---- HTTP の検査 ----
    def test_no_page_and_other_sites_are_refused(self):
        nav = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        # 編集の画面のページ(/・/index.html)は配らない = 404。他のツールのリンクからの遷移の別扱いはない = 別のサイトからは 403
        for p in ("/", "/index.html"):
            st, hd, body = self.call("GET", p, headers={"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate"}, raw=True)
            self.assertEqual(st, 404, p)
            self.assertNotIn(b"<html", body.lower())
            self.assertEqual(self.call("GET", p, headers=nav, raw=True)[0], 403, p)
        for p in ("/ui-kit.js", "/ui-kit.css"):   # ui-kit の写しも配らない
            self.assertEqual(self.call("GET", p, headers={"Sec-Fetch-Site": "same-origin"}, raw=True)[0], 404, p)
        self.assertEqual(self.call("GET", "/app.js", headers={"Sec-Fetch-Site": "same-origin"}, raw=True)[0], 200)   # 案件の画面の校正のパネルが読む部品
        self.assertEqual(self.call("GET", "/app.js", headers={"Sec-Fetch-Site": "cross-site"}, raw=True)[0], 403)       # 別のサイトからは読めない
        self.assertEqual(self.call("GET", "/proof.css", headers={"Sec-Fetch-Site": "cross-site"}, raw=True)[0], 403)
        self.assertEqual(self.call("GET", "/app.js", headers=dict(nav, **{"Sec-Fetch-Dest": "iframe"}), raw=True)[0], 403)
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
        r = self.call("PUT", "/api/settings", b"")
        self.assertEqual((r["_status"], r["error"]), (413, "too_big"))
        self.assertIn("最大32MB", r["message"])

    def test_media_range_head_and_416(self):
        """/media の Range(シーク)・HEAD・範囲の外(416)。応答は ytt.httpsec.send_file(スタジオと同じ 1 か所)"""
        from test_edit import put_empty_doc   # 行の無い文書
        tid = put_empty_doc(os.path.join(self.tmp, "transcripts"), self.wav)
        with open(self.wav, "rb") as f:
            body = f.read()
        size = len(body)
        st, hd, d = self.call("GET", "/media?id=" + tid, raw=True)
        self.assertEqual((st, d, hd.get("Accept-Ranges"), hd.get("Content-Type")), (200, body, "bytes", "audio/wav"))
        self.assertEqual((hd.get("Cache-Control"), hd.get("X-Content-Type-Options")), ("no-store", "nosniff"))
        st, hd, d = self.call("GET", "/media?id=" + tid, headers={"Range": "bytes=10-19"}, raw=True)
        self.assertEqual((st, d, hd.get("Content-Range"), hd.get("Content-Length")), (206, body[10:20], "bytes 10-19/%d" % size, "10"))
        r = self.call("GET", "/media?id=ffffffffffff")
        self.assertEqual(r["_status"], 404)
        self.assertEqual(self.call("POST", "/api/transcribe", {"sourcePath": self.wav, "model": "hololive-roster.json"}).get("error"), "bad_model")


class TestSafe(unittest.TestCase):
    """Handler._safe: 想定外の例外でも黙って接続を切らずに 500 internal と理由を返す・応答を始めたあとは書かない・切断は黙る"""

    class Fake:
        command, path = "PUT", "/api/settings?x=1"

        def __init__(self):
            self.sent = []

        def _fail(self, code, error, message):
            self.sent.append((code, error, message))

    def test_unexpected_error_is_500(self):
        h = self.Fake()
        S.Handler._safe(h, lambda: (_ for _ in ()).throw(RecursionError("deep")))
        self.assertEqual([(c, e) for c, e, _m in h.sent], [(500, "internal")])
        self.assertIn("RecursionError", h.sent[0][2])

    def test_after_response_and_disconnect(self):
        h = self.Fake()

        def started():
            h._responded = True
            raise ValueError("途中")
        S.Handler._safe(h, started)
        self.assertEqual(h.sent, [])   # 応答を始めたあとは 500 を重ねて書かない
        S.Handler._safe(h, lambda: (_ for _ in ()).throw(BrokenPipeError()))
        self.assertEqual(h.sent, [])   # 切断は黙る


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestSettingsMerge(StoreDir):
    """設定の保存の「差のキーだけ」(PUT /api/settings {"patch"}。段2 監査 11): 別の窓が保存したほかのキーを消さない"""

    def st(self):
        return testkit.read_json(_workdata.SETTINGS)

    def test_merge_keeps_other_keys(self):
        # (名前, 保存前の設定ファイル(None = ファイルなし), 送る patch, 保存後の中身)
        for name, before, patch, want in [
            ("送らないキーは残る・null で消す・パックの項目は変えない",
             {"glossary": "ぺこら", "replacements": "a=>b", "packFps": "30", "old": 1},
             {"glossary": "みこ", "new": [1, 2], "old": None, "packFps": "60"},
             {"glossary": "みこ", "replacements": "a=>b", "packFps": "30", "new": [1, 2]}),
            ("空の patch は何も変えない", {"replacements": "a=>b"}, {}, {"replacements": "a=>b"}),
            ("設定ファイルが無いときは空から作る", None, {"glossary": "x"}, {"glossary": "x"}),
        ]:
            with self.subTest(name):
                if os.path.exists(_workdata.SETTINGS):
                    os.remove(_workdata.SETTINGS)
                if before is not None:
                    write_json(_workdata.SETTINGS, before)
                self.assertEqual(_settings.merge_settings({"patch": patch}), {"ok": True})
                self.assertEqual(self.st(), want)

    def test_merge_rejects(self):
        write_json(_workdata.SETTINGS, {"glossary": "ぺこら"})
        for bad in ({"patch": []}, {"patch": "x"}, {"patch": {"": 1}}, {"patch": {"k" * 61: 1}}, {"patch": {"a": 1}, "glossary": "y"},
                    {"patch": {"k%d" % i: 1 for i in range(201)}}):
            with self.assertRaises(ed_state.ApiError, msg=str(bad)[:60]) as c:
                _settings.merge_settings(bad)
            self.assertEqual(c.exception.status, 400)
        with self.assertRaises(ed_state.ApiError) as c:
            _settings.merge_settings({"patch": {"big": "x" * 500000}})
        self.assertEqual(c.exception.status, 413)
        self.assertEqual(self.st(), {"glossary": "ぺこら"})   # 断ったときは書かない


class TestRuntimeCleanup(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "SIGTERM の確認は Linux / Mac のみ")
    def test_runtime_removed_on_terminate(self):
        """終了の合図(SIGTERM)でも .runtime/transcribe.json と起動中の印を消す。"""
        tmp = testkit.tempdir(self)
        runtime = os.path.join(tmp, "rt")
        port = testkit.free_port()
        proc = start_server(tmp, port, runtime)
        path = os.path.join(runtime, "transcribe.json")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(tmp, ".running.json")))
        proc.terminate()
        proc.wait(timeout=10)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(os.path.join(tmp, ".running.json")))   # 正常終了の扱い(次の起動で「異常終了」と出ない)


class TestHeavyJobLimit(unittest.TestCase):
    """文字起こしのジョブも、他のツールの重い処理と順番を待つ(ytt.jobs)。待っている間に取り消せる"""

    def setUp(self):
        from ytt import jobs
        self.jobs = jobs
        self.tmp = testkit.tempdir(self)
        self.saved = (ed_state.RUN_MARK, jobs.SLOTS, _doc_jobs.run_job)
        ed_state.RUN_MARK = os.path.join(self.tmp, ".running.json")
        jobs.SLOTS = jobs.HeavySlots(1)
        self.ran = []
        _doc_jobs.run_job = lambda job: (self.ran.append(job["id"]), job.update(state="done"))

    def tearDown(self):
        ed_state.RUN_MARK, self.jobs.SLOTS, _doc_jobs.run_job = self.saved
        for jid in ("hj1", "hj2"):
            _jobs._jobs.pop(jid, None)

    def job(self, jid):
        j = {"id": jid, "kind": "transcribe", "state": "queued", "phase": "待機中", "cancel": False, "spec": {"title": "t", "model": "m"}}
        _jobs._jobs[jid] = j
        return j

    def test_waits_then_runs_or_cancels(self):
        held = self.jobs.SLOTS.acquire("studio", "解析")
        j1 = self.job("hj1")
        t = threading.Thread(target=_jobs.work_one, args=("hj1",))
        t.start()
        for _ in range(100):
            if j1["phase"] == self.jobs.WAIT_MESSAGE:
                break
            time.sleep(0.02)
        self.assertEqual((j1["state"], j1["phase"], self.ran), ("queued", self.jobs.WAIT_MESSAGE, []))
        j1["cancel"] = True
        t.join(5)
        self.assertEqual((j1["state"], self.ran), ("cancelled", []))
        self.jobs.SLOTS.release(held)
        self.job("hj2")
        _jobs.work_one("hj2")
        self.assertEqual(self.ran, ["hj2"])
        self.assertEqual(self.jobs.SLOTS.snapshot()["active"], [])


class TestWiring(unittest.TestCase):
    """serve の配線: 画面が読むジョブの形(public_job の鍵)と、本物と疑似の選び方(呼ぶたびに ed_state.backend_name を読む)"""
    PUBLIC_JOB_KEYS = {
        "id", "title", "state", "phase", "progress", "tid", "error", "segments", "speakers", "unsure", "kind", "device", "createdAt",
        "errorDetail", "internal", "canRetry", "warnings", "hasClip", "into", "named", "learned", "auto", "autoSkipped",
        "redo", "redoOne", "redoSkipped", "vadNote", "normNote", "normOk", "kept", "emptyKept", "loose"}

    def test_public_job_keys(self):
        job = {"id": "j1", "title": "t", "state": "done", "phase": "完了", "progress": 1.0, "tid": "", "error": "", "segments": 0,
               "speakers": 0, "unsure": 0, "kind": "transcribe", "device": "cpu", "createdAt": 0, "spec": {}}
        self.assertEqual(set(_doc_jobs.public_job(job)), self.PUBLIC_JOB_KEYS)

    def test_selector_follows_backend_name(self):
        from eval.fake import fake_asr
        from pipeline.transcribe import backend
        with patch.object(ed_state, "backend_name", lambda: "fake"):
            self.assertIs(backend.select(), fake_asr.FAKE)
        with patch.object(ed_state, "backend_name", lambda: "faster-whisper"):
            self.assertIs(backend.select(), backend.REAL)


if __name__ == "__main__":
    unittest.main()
