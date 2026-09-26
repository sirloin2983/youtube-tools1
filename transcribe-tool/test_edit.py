#!/usr/bin/env python3
"""「編集」ツールのサーバー側(docs/edit-tool-design.md の 4・5・9)のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_edit -q                          # これだけ

編集の内容(<id>.edit.json)の検査・rev と 409・行の cutState の同期(どの書き込みでも編集の内容から決まる)・パックの記録と「作り直し」、
文字起こしせずに開く(open-video)・音の波形(peaks)・文字起こしを文字起こしの無い文書に入れる(intoDoc)を確かめる。
HTTP のものは疑似モード(TRANSCRIBE_BACKEND=fake)のサーバーを空いているポートで起動する(ffmpeg が必要)。
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
import urllib.parse
import urllib.request

from test_backend import HERE, S, TID, StoreDir, free_port, start_server, write_json  # noqa: F401  (S = serve)

os.environ.setdefault("YTT_CUT2RESOLVE_DIR", os.path.join(os.path.dirname(HERE), "cut2resolve"))   # 一時フォルダに写した serve.py が pack.py を見つけられるように


def doc_obj(**over):
    d = {"schema": "transcribe/v1", "id": TID, "title": "t", "sourcePath": "C:\\x\\clip.mp4", "sourceName": "clip.mp4",
         "start": 0, "end": 12.0, "duration": 12.0, "speakers": [], "createdAt": 1, "updatedAt": 1000,
         "segments": [{"id": "s1", "start": 0.4, "end": 2.8, "text": "こんばんは"},
                      {"id": "s2", "start": 3.2, "end": 5.3, "text": "待って"},
                      {"id": "s3", "start": 6.0, "end": 8.3, "text": "あのー"},
                      {"id": "s4", "start": 8.8, "end": 11.1, "text": "それって"}]}
    d.update(over)
    return d


def edit_obj(clips=((0.3, 5.6), (8.6, 11.2)), fps=(30, 1), duration=12.0, **over):
    d = {"sources": [{"fps": list(fps), "duration": duration}], "clips": [{"src": 0, "in": a, "out": b} for a, b in clips], "origin": "manual"}
    d.update(over)
    return d


class TestEditStore(StoreDir):
    def setUp(self):
        super().setUp()
        self.put_doc(doc_obj())

    def doc(self):
        with open(S.tx_path(TID), encoding="utf-8") as f:
            return json.load(f)

    def cut_ids(self, doc=None):
        return [s["id"] for s in (doc or self.doc())["segments"] if s.get("cutState") == "cut"]

    def test_sanitize_rules(self):
        e = S.sanitize_edit(dict(edit_obj(clips=((0.30001, 5.6), (8.6, 12.0))), extra="捨てる", rev=99, packRev=5))
        self.assertEqual(e, {"sources": [{"fps": [30, 1], "duration": 12.0}], "clips": [{"src": 0, "in": 0.3, "out": 5.6}, {"src": 0, "in": 8.6, "out": 12.0}],
                             "origin": "manual"})                                               # 知らない項目・rev は捨てる
        self.assertEqual(S.sanitize_edit(edit_obj(clips=()))["clips"], [])                      # 全部削った状態も保存できる
        self.assertEqual(S.sanitize_edit(edit_obj(clips=((0, 12.03),)))["clips"][0]["out"], 12.03)   # 長さ + 1フレームまで
        self.assertEqual(S.sanitize_edit(edit_obj(origin="rows"))["origin"], "rows")
        self.assertEqual(S.sanitize_edit(edit_obj(origin="<b>"))["origin"], "manual")
        bad = [
            None, [], {"clips": []},
            edit_obj(fps=(0, 1)), edit_obj(fps=(30,)), edit_obj(fps=(True, 1)), edit_obj(fps=(30.0, 1)), edit_obj(fps=(1000, 1)),
            edit_obj(duration=0), edit_obj(duration="12"), edit_obj(duration=10 ** 9),
            dict(edit_obj(), sources=[{"fps": [30, 1], "duration": 12}, {"fps": [30, 1], "duration": 12}]),   # 複数の動画はまだ
            dict(edit_obj(), clips=[{"src": 1, "in": 0, "out": 1}]),
            dict(edit_obj(), clips=[{"src": True, "in": 0, "out": 1}]),
            edit_obj(clips=((1, 1),)), edit_obj(clips=((2, 1),)), edit_obj(clips=((-0.1, 1),)), edit_obj(clips=((0, 12.1),)),
            edit_obj(clips=((0, 5), (4, 6))),        # 重なり
            edit_obj(clips=((5, 6), (0, 1))),        # 順番の入れ替え(v1 では断る)
            edit_obj(clips=((0.1, 0.1002),)),        # 丸めると長さ 0
            dict(edit_obj(), clips=[{"src": 0, "in": "0", "out": 1}]),
            dict(edit_obj(), clips=[{"src": 0, "in": False, "out": 1}]),
            dict(edit_obj(), clips=[[0, 1]]),
            dict(edit_obj(), clips=[{"src": 0, "in": i * 0.002, "out": i * 0.002 + 0.001} for i in range(5001)]),
        ]
        for b in bad:
            with self.subTest(b=str(b)[:80]):
                with self.assertRaises(S.ApiError) as cm:
                    S.sanitize_edit(b)
                self.assertEqual(cm.exception.code, "bad_edit")

    def test_save_rev_conflict_and_cut_rows(self):
        self.assertEqual(S.get_edit(TID), {"edit": None, "rev": 0, "broken": False, "packStale": False})
        r = S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})
        self.assertEqual((r["rev"], r["cutRows"]), (1, ["s3"]))                                   # 6.0–8.3 は削る区間 5.6–8.6 の中
        d = self.doc()
        self.assertEqual((self.cut_ids(d), d["updatedAt"]), (["s3"], 1000))                       # 文書の updatedAt は変えない(校正の保存を 409 にしない)
        g = S.get_edit(TID)
        self.assertEqual((g["rev"], g["edit"]["schema"], g["edit"]["clips"][1], g["edit"]["packRev"]),
                         (1, "youtube-tools-edit/v1", {"src": 0, "in": 8.6, "out": 11.2}, 0))
        with self.assertRaises(S.ApiError) as cm:                                                 # 別のタブが古い rev で保存 → 409 と今の rev
            S.save_edit(TID, {"edit": edit_obj(clips=((0, 12),)), "baseRev": 0})
        self.assertEqual((cm.exception.status, cm.exception.code, cm.exception.extra), (409, "conflict", {"rev": 1}))
        self.assertEqual(self.cut_ids(), ["s3"])
        r = S.save_edit(TID, {"edit": edit_obj(clips=((0, 12),)), "baseRev": 1})                # 「こちらで上書き」= 今の rev で送り直す
        self.assertEqual((r["rev"], r["cutRows"], self.cut_ids()), (2, [], []))
        for body in ({"edit": edit_obj()}, {"edit": edit_obj(), "baseRev": "2"}, {"edit": edit_obj(), "baseRev": True}):
            with self.assertRaises(S.ApiError) as cm:
                S.save_edit(TID, body)
            self.assertEqual(cm.exception.code, "bad_request")
        with self.assertRaises(S.ApiError) as cm:
            S.save_edit("../../x", {"edit": edit_obj(), "baseRev": 2})
        self.assertEqual(cm.exception.status, 404)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.edit.json")))

    def test_doc_save_and_other_writers_follow_edit(self):
        """編集の内容があれば、行の cutState はどの書き込みでも編集の内容から決まる(画面の古い印・再認識・履歴から戻すで食い違わない)"""
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})
        d = self.doc()
        d["segments"][0]["cutState"] = "cut"                  # 古い画面が、編集と違う印で保存しても
        d["segments"][2].pop("cutState")
        d["segments"][1]["text"] = "待って待って"
        S.save_transcript(TID, dict(d, baseUpdatedAt=d["updatedAt"]))
        d = self.doc()
        self.assertEqual((self.cut_ids(d), d["segments"][1]["text"]), (["s3"], "待って待って"))   # 文字は保存・印は編集の内容のまま
        # 範囲の再認識で行が入れ替わっても、新しい行の印は時刻から付く
        S.apply_range({"tid": TID, "range": [5.9, 8.5], "ids": ["s3"], "model": "small", "autoDict": False},
                      [{"start": 6.1, "end": 8.2, "raw": "新しい行", "flag": ""}])
        d = self.doc()
        new = next(s for s in d["segments"] if s["text"] == "新しい行")
        self.assertEqual(new.get("cutState"), "cut")
        # 履歴から戻しても、カットは今の編集の内容のまま
        S.hist_snapshot(TID, force=True)
        ts = S.hist_stamps(TID)[-1]
        S.save_edit(TID, {"edit": edit_obj(clips=((0, 12),)), "baseRev": 1})
        S.restore_history(TID, ts)
        self.assertEqual(self.cut_ids(), [])

    def test_without_edit_rows_keep_their_own_cut_state(self):
        """編集の内容が無い文書(以前の使い方)は、画面から来た cutState をそのまま保存する"""
        d = self.doc()
        d["segments"][1]["cutState"] = "cut"
        S.save_transcript(TID, d)
        self.assertEqual(self.cut_ids(), ["s2"])

    def test_cut_flags_frame_rounding_and_short_rows(self):
        fps = [30000, 1001]
        fr = lambda n: round(n * 1001 / 30000, 3)   # noqa: E731  フレームの境目の秒
        e = S.sanitize_edit(edit_obj(clips=((0, fr(168)), (fr(258), fr(359))), fps=fps))   # 5.6056 / 8.6086(行の端 5.60・8.60 に一番近いフレーム)
        segs = [{"start": 5.60, "end": 8.60}, {"start": 5.00, "end": 5.60}, {"start": 8.61, "end": 9.0},
                {"start": 7.0, "end": 7.01}, {"start": 1.0, "end": 1.0}, {"start": 5.58, "end": 5.64}]
        self.assertEqual(S.edit_cut_flags(segs, e), [True, False, False, True, False, False])
        # 1フレームより多く残っていれば残す行
        e2 = S.sanitize_edit(edit_obj(clips=((0, 5.7),)))
        self.assertEqual(S.edit_cut_flags([{"start": 5.6, "end": 8.0}], e2), [False])
        e3 = S.sanitize_edit(edit_obj(clips=((0, 5.6166),)))                            # 0.0166 秒 = 30fps の半フレーム → カット済
        self.assertEqual(S.edit_cut_flags([{"start": 5.6, "end": 8.0}], e3), [True])
        self.assertEqual(S.edit_cut_flags([{"start": 0, "end": 1}], S.sanitize_edit(edit_obj(clips=()))), [True])   # 全部削った

    def test_record_pack_and_stale(self):
        with self.assertRaises(S.ApiError) as cm:
            S.record_pack({"id": TID, "rev": 1, "docUpdatedAt": 1000, "dir": os.path.join(self.tmp, "p")})
        self.assertEqual(cm.exception.code, "no_edit")
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})
        out = os.path.join(self.tmp, "clip_pack")
        r = S.record_pack({"id": TID, "rev": 1, "docUpdatedAt": 1000, "dir": out, "files": ["clip.edl", "..\\..\\x.txt", 3]})
        self.assertEqual(r["packRev"], 1)
        g = S.get_edit(TID)
        self.assertEqual((g["rev"], g["edit"]["packRev"], g["edit"]["pack"]["dir"], g["edit"]["pack"]["files"], g["packStale"]),
                         (1, 1, out, ["clip.edl", "x.txt"], False))                     # rev は増やさない・ファイルは名前だけ
        item = next(i for i in S.list_transcripts() if i["id"] == TID)
        self.assertEqual((item["hasEdit"], item["editRev"], item["packRev"], item["packStale"]), (True, 1, 1, False))
        self.assertNotIn("_packDocAt", item)
        S.save_edit(TID, {"edit": edit_obj(clips=((0, 12),)), "baseRev": 1})             # カットが変わった → 作り直し
        self.assertTrue(S.get_edit(TID)["packStale"])
        self.assertEqual(S.get_edit(TID)["edit"]["pack"]["rev"], 1)                        # 前回のパックの記録は残る
        S.record_pack({"id": TID, "rev": 2, "docUpdatedAt": 1000, "dir": out})
        self.assertFalse(S.get_edit(TID)["packStale"])
        d = self.doc()
        S.save_transcript(TID, dict(d, baseUpdatedAt=d["updatedAt"]))                     # 文字が変わった(文書が新しい)→ 作り直し
        self.assertTrue(S.get_edit(TID)["packStale"])
        item = next(i for i in S.list_transcripts() if i["id"] == TID)
        self.assertTrue(item["packStale"])
        for bad in ({"rev": 9, "docUpdatedAt": 1, "dir": out}, {"rev": 0, "docUpdatedAt": 1, "dir": out}, {"rev": 1, "docUpdatedAt": 1, "dir": "rel\\p"},
                    {"rev": 1, "docUpdatedAt": 1, "dir": out + "\n"}, {"rev": 1, "docUpdatedAt": -1, "dir": out}, {"rev": True, "docUpdatedAt": 1, "dir": out}):
            with self.assertRaises(S.ApiError) as cm:
                S.record_pack(dict(bad, id=TID))
            self.assertEqual(cm.exception.status, 400, bad)

    def test_broken_edit_file(self):
        with open(S.edit_path(TID), "w", encoding="utf-8") as f:
            f.write('{"schema": "youtube-tools-edit/v1", "rev": 3, "clips": [')
        g = S.get_edit(TID)
        self.assertEqual((g["edit"], g["rev"], g["broken"]), (None, 0, True))
        d = self.doc()
        d["segments"][0]["cutState"] = "cut"
        S.save_transcript(TID, d)
        self.assertEqual(self.cut_ids(), ["s1"])                                           # 壊れた編集の内容では行の印を変えない
        self.assertEqual(S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})["rev"], 1)   # 読み直して保存し直せる
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, TID + ".edit.broken.json")))  # 壊れたものは1つ残す
        with open(S.edit_path(TID), "w", encoding="utf-8") as f:                           # 形は JSON でも中身が正しくない(手で書き換えた)
            json.dump({"schema": "youtube-tools-edit/v1", "rev": 3, "sources": [{"fps": [30, 1], "duration": 12}], "clips": [{"in": 5, "out": 1}]}, f)
        self.assertTrue(S.get_edit(TID)["broken"])

    def test_edit_file_is_not_a_document(self):
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})
        self.assertEqual(S._tids(), [TID])
        from ytt_core import txindex
        self.assertEqual([d["id"] for d in txindex.load(self.tmp)], [TID])                 # 入口の案件・スタジオのセリフも文書だけを読む

    def test_fill_doc_into_empty_document(self):
        self.put_doc(doc_obj(segments=[], title="動画だけ", createdAt=5))
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})                               # 文字起こしの前にカットを決めてあった
        segs = [{"id": "s1", "start": 1.0, "end": 2.0, "text": "a"}, {"id": "s2", "start": 6.5, "end": 7.5, "text": "b"}]
        spec = {"intoDoc": TID, "sourcePath": "C:\\x\\clip.mp4", "clip": None, "warnings": []}
        self.assertEqual(S.fill_doc(spec, {"segments": segs, "original": [], "model": "small", "updatedAt": 2000}), TID)
        d = self.doc()
        self.assertEqual((d["title"], d["createdAt"], d["model"], [s.get("cutState") for s in d["segments"]]),
                         ("動画だけ", 5, "small", [None, "cut"]))
        # もう行がある・別の動画 → 入れない(呼び出し側が新しい文書にする)
        self.assertIsNone(S.fill_doc(dict(spec, warnings=[]), {"segments": segs, "updatedAt": 3000}))
        self.put_doc(doc_obj(segments=[]))
        sp2 = dict(spec, sourcePath="C:\\y\\other.mp4", warnings=[])
        self.assertIsNone(S.fill_doc(sp2, {"segments": segs, "updatedAt": 3000}))
        self.assertTrue(sp2["warnings"])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestEditHttp(unittest.TestCase):
    """open-video・peaks・edit の HTTP・intoDoc・削除(疑似モードのサーバー)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.media_dir = os.path.join(cls.tmp, "media")
        os.makedirs(cls.media_dir)
        ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        cls.video = os.path.join(cls.media_dir, "切り抜き.mkv")   # 映像と音声(音は 1.5 秒ずつ鳴る・止まる)
        subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=6", "-f", "lavfi",
                             "-i", "sine=frequency=440:duration=6,volume='if(lt(mod(t,3),1.5),1,0)':eval=frame",
                             "-c:v", "mpeg4", "-c:a", "pcm_s16le", "-shortest", cls.video], check=True)
        cls.silent = os.path.join(cls.media_dir, "音なし.mkv")
        subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=2", "-c:v", "mpeg4", cls.silent], check=True)
        cls.wav = os.path.join(cls.media_dir, "声.wav")
        subprocess.run(ff + ["-f", "lavfi", "-i", "sine=frequency=300:duration=12", cls.wav], check=True)
        cls.fake_mp4 = os.path.join(cls.media_dir, "壊れた.mp4")
        with open(cls.fake_mp4, "wb") as f:
            f.write(os.urandom(4096))
        cls.txt = os.path.join(cls.media_dir, "メモ.txt")
        with open(cls.txt, "w", encoding="utf-8") as f:
            f.write("not a video")
        cls.runtime = os.path.join(cls.tmp, ".runtime")
        cls.port = free_port()
        cls.proc = start_server(cls.tmp, cls.port, cls.runtime)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, raw=False):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=60) as r:
                d = r.read()
                return (r.status, dict(r.headers), d) if raw else dict(json.loads(d), _status=r.status)
        except urllib.error.HTTPError as e:
            d = e.read()
            if raw:
                return e.code, dict(e.headers), d
            return dict(json.loads(d or b"{}"), _status=e.code)

    def open_video(self, path, **kw):
        return self.call("POST", "/api/open-video", dict({"path": path}, **kw))

    def peaks(self, tid, timeout=60):
        end = time.time() + timeout
        seen = set()
        while time.time() < end:
            st, hd, body = self.call("GET", "/api/peaks?id=" + tid, raw=True)
            if st != 202:
                return st, hd, body, seen
            seen.add(json.loads(body)["state"])
            time.sleep(0.1)
        self.fail("波形ができません")

    def test_open_video(self):
        video = os.path.join(self.media_dir, "開く.mkv")   # 他のテストが開いていない動画
        shutil.copy(self.video, video)
        r = self.open_video(video, title="  <題名>  ")
        self.assertEqual((r["_status"], r["created"]), (200, True), r)
        tid = r["id"]
        d = self.call("GET", "/api/transcript?id=" + tid)
        self.assertEqual((d["title"], d["segments"], os.path.normcase(d["sourcePath"]), d["whole"]),
                         ("<題名>", [], os.path.normcase(video), True))
        self.assertAlmostEqual(d["duration"], 6.0, delta=0.1)
        again = self.open_video(video.replace("\\", "/"))      # 同じ動画(書き方が違っても)→ 同じ文書
        self.assertEqual((again["id"], again["created"]), (tid, False))
        item = next(i for i in self.call("GET", "/api/transcripts")["items"] if i["id"] == tid)
        self.assertEqual((item["rows"], item["hasEdit"], item["mediaOk"]), (0, False, True))
        st, hd, body = self.call("GET", "/media?id=" + tid, raw=True)
        self.assertEqual(st, 200)
        # 動画でないもの・読めないもの・無いもの・相対パスは文書にしない(文書にした動画は /media で配るため)
        for p, code in ((self.txt, "bad_ext"), (self.fake_mp4, "bad_media"), (os.path.join(self.media_dir, "無い.mp4"), "no_file"),
                        ("", "no_file")):
            r = self.open_video(p)
            self.assertEqual((r["_status"], r["error"]), (400, code), p)
        self.assertEqual(self.call("GET", "/api/doc-for?path=" + urllib.parse.quote(video))["doc"], {"id": tid, "rows": 0})
        self.assertIsNone(self.call("GET", "/api/doc-for?path=" + urllib.parse.quote(self.txt))["doc"])
        self.assertIsNone(self.call("GET", "/api/doc-for?path=")["doc"])
        n = len(self.call("GET", "/api/transcripts")["items"])
        self.assertEqual(self.call("POST", "/api/open-video", {"path": 3})["_status"], 400)
        self.assertEqual(len(self.call("GET", "/api/transcripts")["items"]), n)

    def test_peaks(self):
        tid = self.open_video(self.video)["id"]
        st, hd, body, seen = self.peaks(tid)
        self.assertEqual((st, hd["X-Peaks-Rate"], hd["X-Peaks-Scale"], hd["X-Peaks-Audio"], hd["Content-Type"]),
                         (200, "100", "sqrt", "1", "application/octet-stream"))
        self.assertAlmostEqual(float(hd["X-Peaks-Duration"]), 6.0, delta=0.1)
        self.assertAlmostEqual(len(body), 600, delta=3)
        loud, quiet = body[20:130], body[170:280]                    # 0.2–1.3 秒は鳴っている・1.7–2.8 秒は止まっている
        self.assertGreater(min(loud), 60)                            # lavfi の sine は最大の 1/8(平方根で約 90)
        self.assertLess(max(quiet), 20)
        t0 = time.time()
        st2, _, body2, seen2 = self.peaks(tid)                       # 2回目は保存したものを返す(すぐ・202 なし)
        self.assertEqual((st2, body2, seen2), (200, body, set()))
        self.assertLess(time.time() - t0, 2)
        self.assertEqual(len(os.listdir(os.path.join(self.tmp, "cache", "peaks"))), 2)   # 作業データの cache/peaks/ に .bin と .json
        # 音の無い動画は空(画面は「音声なし」)
        st, hd, body, _ = self.peaks(self.open_video(self.silent)["id"])
        self.assertEqual((st, hd["X-Peaks-Audio"], body), (200, "0", b""))
        # id の検査・元の動画が無い
        self.assertEqual(self.call("GET", "/api/peaks?id=../../x")["_status"], 404)
        gone = os.path.join(self.media_dir, "消える.wav")
        shutil.copy(self.wav, gone)
        gid = self.open_video(gone)["id"]
        os.unlink(gone)
        r = self.call("GET", "/api/peaks?id=" + gid)
        self.assertEqual((r["_status"], r["error"]), (404, "source_missing"))

    def test_edit_draft(self):
        """開いたときの下書き・たたき台「行から」は pack.TRANSCRIPT_ROWS(cut2resolve の規則)。fps・長さも返す"""
        tid = self.open_video(self.wav)["id"]
        r = self.call("GET", "/api/edit/draft?id=" + tid)
        self.assertEqual((r["_status"], r["unavailable"]["code"]), (200, "no_video"))   # 音声だけのファイルはカット・パックに使えない(理由は 200 で返す)
        video = os.path.join(self.media_dir, "下書き.mkv")
        shutil.copy(self.video, video)
        tid = self.open_video(video)["id"]
        r = self.call("GET", "/api/edit/draft?id=" + tid)                           # 行の無い文書 → 全部残す
        self.assertEqual((r["_status"], r["fps"], r["base"], r["planBeside"]), (200, [30, 1], "all", ""))
        self.assertAlmostEqual(r["durationSec"], 6.0, delta=0.05)
        self.assertEqual(r["keepsSec"], [[0.0, r["durationSec"]]])
        doc = self.call("GET", "/api/transcript?id=" + tid)                         # 行を入れて、2行目をカット済に(以前の使い方)
        segs = [{"id": "a", "start": 0.5, "end": 1.5, "text": "一"}, {"id": "b", "start": 1.5, "end": 3.0, "text": "二", "cutState": "cut"},
                {"id": "c", "start": 3.0, "end": 4.25, "text": "三"}, {"id": "d", "start": 4.5, "end": 5.0, "text": " "}]
        self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [], "segments": segs})
        with open(os.path.splitext(video)[0] + ".cut-plan.json", "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-cut-plan/v1", "segments": [{"start": 1, "end": 2}]}, f)
        r = self.call("GET", "/api/edit/draft?id=" + tid)
        self.assertEqual((r["base"], r["keepsSec"]), ("rows", [[0.5, 1.5], [3.0, 4.266667]]))   # 4.25 秒は 30fps のフレーム(128 = 4.2667)に丸める
        self.assertEqual(os.path.normcase(r["planBeside"]), os.path.normcase(os.path.splitext(video)[0] + ".cut-plan.json"))
        self.assertFalse(os.path.exists(os.path.splitext(video)[0] + ".transcript.json"))   # 動画の隣にファイルを増やさない
        # ネットワーク上の動画は調べない・動画の無い文書
        with open(os.path.join(self.tmp, "transcripts", "abcdefabcdef.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "abcdefabcdef", "title": "n", "sourcePath": r"\\server\share\x.mp4", "segments": [], "updatedAt": 1}, f)
        r = self.call("GET", "/api/edit/draft?id=abcdefabcdef")
        self.assertEqual((r["_status"], r["unavailable"]["code"]), (200, "network_path"))
        self.assertEqual(self.call("GET", "/api/edit/draft?id=zzz")["_status"], 404)

    def test_pack_preview_readme_zip_and_cut_plan(self):
        """3 パック のタブの見積もり(ファイルを作らない)・前回のパックの手順書・zip と「残す区間の保存」もカットのとおり"""
        import io
        import zipfile
        video = os.path.join(self.media_dir, "パック.mkv")
        shutil.copy(self.video, video)
        tid = self.open_video(video)["id"]
        doc = self.call("GET", "/api/transcript?id=" + tid)
        segs = [{"id": "a", "start": 0.5, "end": 1.5, "text": "一"}, {"id": "b", "start": 2.0, "end": 2.2, "text": "二"}, {"id": "c", "start": 3.0, "end": 5.0, "text": "三"}]
        self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [], "segments": segs})
        clips = [(0.5, 1.5), (1.5, 1.8), (2.0, 2.2), (3.0, 5.1)]   # 2つめは1つめと接している(分割しただけ)・3つめは 0.2 秒
        self.assertEqual(self.call("PUT", "/api/edit?id=" + tid, {"baseRev": 0, "edit": edit_obj(clips=clips, duration=6.0)})["rev"], 1)
        keeps = [[a, b] for a, b in clips]
        r = self.call("POST", "/api/edit/preview", {"id": tid, "keeps": keeps})
        self.assertEqual((r["_status"], r["count"], r["captions"], r["fps"]), (200, 3, 3, [30, 1]))   # 接している区間は1つに数える
        self.assertAlmostEqual(r["keptSec"], 1.3 + 0.2 + 2.1, places=3)
        self.assertTrue(any("0.5 秒より短い区間" in w for w in r["warnings"]), r["warnings"])
        self.assertFalse(os.path.exists(os.path.splitext(video)[0] + ".transcript.json"))   # 見積もりでは動画の隣にファイルを作らない
        for bad in ([], [[1, 0.5]], [[0, 1], [0.5, 2]], "x", [[0, True]]):
            self.assertEqual(self.call("POST", "/api/edit/preview", {"id": tid, "keeps": bad}).get("error"), "bad_keeps", bad)
        # zip もカットのとおり(3区間・30fps のフレーム)
        st, hd, body = self.call("POST", "/api/resolve-package", {"tid": tid, "fps": "30", "size": "1080x1920"}, raw=True)
        self.assertEqual((st, hd["X-Resolve-Cuts"]), (200, "3"))
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            ip = json.loads(z.read(next(n for n in z.namelist() if n.endswith("/textplus-import.json"))))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(15, 54), (60, 66), (90, 153)])
        # 残す区間(.cut-plan.json)の保存もカットのとおり
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "cut-plan-v1"})
        with open(r["path"], encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual([(g["start"], g["end"]) for g in plan["segments"]], [(0.5, 1.8), (2.0, 2.2), (3.0, 5.1)])
        # 前回のパックの手順書: 記録したフォルダが cut2resolve のパック(中に cut-plan.json)のときだけ読む
        out = os.path.join(self.media_dir, "パック_pack")
        os.makedirs(out, exist_ok=True)
        self.call("POST", "/api/edit/pack", {"id": tid, "rev": 1, "docUpdatedAt": 0, "dir": out, "files": ["友人へ.txt"]})
        with open(os.path.join(out, "友人へ.txt"), "w", encoding="utf-8") as f:
            f.write("Resolve で開く手順")
        self.assertEqual(self.call("GET", "/api/edit/pack-readme?id=" + tid)["_status"], 404)   # cut-plan.json が無い = パックではない
        with open(os.path.join(out, "cut-plan.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-cut-plan/v1"}, f)
        r = self.call("GET", "/api/edit/pack-readme?id=" + tid)
        self.assertEqual((r["name"], r["text"]), ("友人へ.txt", "Resolve で開く手順"))

    def test_edit_http_into_doc_and_delete(self):
        tid = self.open_video(self.wav)["id"]
        self.assertEqual(self.call("GET", "/api/edit?id=" + tid), {"edit": None, "rev": 0, "broken": False, "packStale": False, "_status": 200})
        e = edit_obj(clips=((0.0, 3.0), (6.0, 12.0)), duration=12.0)
        r = self.call("PUT", "/api/edit?id=" + tid, {"edit": e, "baseRev": 0})
        self.assertEqual((r["_status"], r["rev"], r["cutRows"]), (200, 1, []))
        r = self.call("PUT", "/api/edit?id=" + tid, {"edit": e, "baseRev": 0})
        self.assertEqual((r["_status"], r["error"], r["rev"]), (409, "conflict", 1))
        r = self.call("PUT", "/api/edit?id=" + tid, {"edit": dict(e, clips=[{"src": 0, "in": 5, "out": 1}]), "baseRev": 1})
        self.assertEqual((r["_status"], r["error"]), (400, "bad_edit"))
        self.assertEqual(self.call("PUT", "/api/edit?id=zzz", {"edit": e, "baseRev": 1})["_status"], 404)
        # 文字起こしの無い文書に文字起こしを入れる(疑似モードは 4 秒ごとの行 → 4–8 秒の行は 3–6 秒の削る区間を半分だけ含む・8–12 は残す)
        j = self.call("POST", "/api/transcribe", {"sourcePath": self.wav, "model": "small", "autoGloss": False, "intoDoc": tid})
        self.assertEqual(j["_status"], 200, j)
        end = time.time() + 60
        while time.time() < end:
            x = next(v for v in self.call("GET", "/api/jobs")["jobs"] if v["id"] == j["id"])
            if x["state"] in ("done", "error", "cancelled"):
                break
            time.sleep(0.05)
        self.assertEqual((x["state"], x["tid"]), ("done", tid), x)
        d = self.call("GET", "/api/transcript?id=" + tid)
        self.assertEqual(len(d["segments"]), 3)
        self.assertTrue(all("cutState" not in s for s in d["segments"]))
        r = self.call("PUT", "/api/edit?id=" + tid, {"edit": dict(e, clips=[{"src": 0, "in": 0, "out": 3.9}, {"src": 0, "in": 8.1, "out": 12}]), "baseRev": 1})
        self.assertEqual(r["cutRows"], [d["segments"][1]["id"]])                     # 4–8 秒の行はカット済
        # もう行がある文書・別の動画には入れない
        again = self.call("POST", "/api/transcribe", {"sourcePath": self.wav, "model": "small", "intoDoc": tid})
        self.assertEqual((again["_status"], again["error"]), (409, "not_empty"))
        other = self.open_video(self.video)["id"]
        r = self.call("POST", "/api/transcribe", {"sourcePath": self.wav, "model": "small", "intoDoc": other})
        self.assertEqual((r["_status"], r["error"]), (400, "bad_request"))
        # パックの記録・一覧
        out = os.path.join(self.media_dir, "声_pack")
        self.assertEqual(self.call("POST", "/api/edit/pack", {"id": tid, "rev": 2, "docUpdatedAt": d["updatedAt"], "dir": out})["packRev"], 2)
        item = next(i for i in self.call("GET", "/api/transcripts")["items"] if i["id"] == tid)
        self.assertEqual((item["hasEdit"], item["editRev"], item["packRev"], item["packStale"]), (True, 2, 2, False))
        # 削除すると編集の内容も消える
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "transcripts", tid + ".edit.json")))
        self.assertTrue(self.call("DELETE", "/api/transcript?id=" + tid)["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "transcripts", tid + ".edit.json")))
        self.assertEqual(self.call("GET", "/api/edit?id=" + tid)["_status"], 404)


if __name__ == "__main__":
    unittest.main()
