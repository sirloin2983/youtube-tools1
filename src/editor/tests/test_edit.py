#!/usr/bin/env python3
"""「編集」ツールのサーバー側(docs/design/edit-tool-design.md の 4・5・9)のテスト。

    python -m unittest test_metrics test_resolve_export -q   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_edit -q                          # これだけ

編集の内容(<id>.edit.json)の検査・rev と 409・行の cutState の同期(どの書き込みでも編集の内容から決まる)・パックの記録と「作り直し」、
文字起こしせずに開く(open-video)・音の波形(peaks)・文字起こしを文字起こしの無い文書に入れる(intoDoc)を確かめる。
HTTP のものは疑似モード(TRANSCRIBE_BACKEND=fake)のサーバーを空いているポートで起動する(ffmpeg が必要)。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from test_backend import HERE, S, TID, StoreDir, free_port, start_server, write_json  # noqa: F401  (S = serve)


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

    def test_doc_diar_num(self):
        """文書ごとの話者判別の人数 diarNum(段7 E-6。POST /api/doc-diarnum): 0〜8 の整数だけ・文書の updatedAt は変えない・画面の保存(PUT)では残る"""
        at = self.doc()["updatedAt"]
        self.assertEqual(S.set_diar_num({"id": TID, "diarNum": 3}), {"diarNum": 3})
        d = self.doc()
        self.assertEqual((d["diarNum"], d["updatedAt"]), (3, at))                                   # 人数を選んだだけで保存の競合・作り直しを起こさない
        self.assertEqual(S.set_diar_num({"id": TID, "diarNum": 0})["diarNum"], 0)                   # 0 = 自動
        S.save_transcript(TID, {"title": "t", "speakers": [], "segments": d["segments"], "baseUpdatedAt": at})
        self.assertEqual(self.doc()["diarNum"], 0)                                                   # 画面の保存(diarNum を送らない)では消えない
        for bad in (9, -1, 2.5, "3", True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(S.ApiError):
                    S.set_diar_num({"id": TID, "diarNum": bad})
        with self.assertRaises(S.ApiError):
            S.set_diar_num({"id": "../x", "diarNum": 2})

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
        # 字幕に出さない行(noSub。2026-10-05)も「残す」の判定は同じ(映像は削られない。cut.js の rowCutFlags も印を見ない)
        self.assertEqual(S.edit_cut_flags([dict(g, noSub=True, speaker="other") for g in segs], e), [True, False, False, True, False, False])

    @unittest.skipUnless(sys.platform == "win32", "Windows のパス(円記号の区切り・ドライブ名 C:)が前提(段1: Windows 以外では飛ばす)")
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

    @unittest.skipUnless(sys.platform == "win32", "Windows のパス(円記号の区切り・ドライブ名 C:)が前提(段1: Windows 以外では飛ばす)")
    def test_record_pack_output(self):
        """4-3: パックを作ったときの出力の設定(output)。決まった鍵だけ・型と長さを確かめる。壊れていれば output なしで記録する(エラーにしない)"""
        S.save_edit(TID, {"edit": edit_obj(), "baseRev": 0})
        out = os.path.join(self.tmp, "clip_pack")
        full = {"fps": "30", "size": "1080x1920", "wrap": 8, "textplus": True, "backup": False, "render": False, "speakerColors": True,
                "streamer": "さくらみこ", "loudness": -14, "volume": 100,
                "advanced": {"srcStartTc": "01:00:00:00", "recStart": "01:00:00:00", "reel": "A001"}}

        def rec(output, **kw):
            body = {"id": TID, "rev": 1, "docUpdatedAt": 1000, "dir": out}
            if output is not KEEP_OFF:
                body["output"] = output
            body.update(kw)
            self.assertEqual(S.record_pack(body)["packRev"], 1)
            return S.get_edit(TID)["edit"]["pack"]
        KEEP_OFF = object()
        self.assertEqual(rec(full).get("output"), full)                                     # 全部の鍵が入る
        p = rec(dict(full, junk=1, advanced=dict(full["advanced"], other="x")))
        self.assertEqual(p["output"], full)                                                 # 余計な鍵は黙って捨てる(全体は捨てない)
        mini = {"fps": "60", "size": "1920x1080", "wrap": 0, "textplus": False, "backup": True, "render": True, "speakerColors": False}
        self.assertEqual(rec(mini)["output"], mini)                                         # 任意の鍵(streamer・loudness・volume・advanced)は無くてよい
        self.assertEqual(rec(dict(mini, loudness=0, volume=200, streamer="", advanced={}))["output"],
                         dict(mini, loudness=0, volume=200, streamer="", advanced={}))
        # output が無い・壊れている → 記録はできて output は入らない
        self.assertNotIn("output", rec(KEEP_OFF))                                           # 古い画面・まとめて実行(home/autorun.py)
        self.assertEqual(S.get_edit(TID)["packStale"], False)
        for bad in (None, "x", [], 3, dict(full, fps=30), dict(full, fps="1000"), dict(full, fps="3a"), dict(full, fps="3\n"), dict(full, size="abc"),
                    dict(full, size="1080x1080"), dict(full, wrap=41), dict(full, wrap=-1), dict(full, wrap="8"), dict(full, wrap=True), dict(full, wrap=8.5),
                    dict(full, backup="yes"), dict(full, backup=1), dict(full, textplus=None), dict(full, render=0), dict(full, speakerColors="true"),
                    dict(full, streamer="あ" * 201), dict(full, streamer=5), dict(full, streamer="a\nb"), dict(full, loudness=-20), dict(full, loudness="-14"),
                    dict(full, loudness=True), dict(full, volume=500), dict(full, volume=0), dict(full, volume=True), dict(full, volume=100.5),
                    dict(full, advanced="x"), dict(full, advanced={"reel": "a\nb"}), dict(full, advanced={"reel": "x" * 41}),
                    dict(full, advanced={"srcStartTc": 5}), dict(full, advanced={"recStart": "a\x00"}),
                    {k: v for k, v in full.items() if k != "fps"}, {k: v for k, v in full.items() if k != "backup"}):
            self.assertNotIn("output", rec(bad), bad)
        self.assertEqual(rec(dict(full, streamer="あ" * 200))["output"]["streamer"], "あ" * 200)   # 上限ちょうどは通る
        self.assertEqual(S.get_edit(TID)["edit"]["pack"]["files"], [])
        # packStale・一覧は output に依らない
        rec(full)
        item = next(i for i in S.list_transcripts() if i["id"] == TID)
        self.assertEqual((item["packRev"], item["packStale"]), (1, False))

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
        from manage.cases import txindex
        self.assertEqual([d["id"] for d in txindex.load(self.tmp)], [TID])                 # 入口の案件・スタジオのセリフも文書だけを読む

    @unittest.skipUnless(sys.platform == "win32", "Windows のパス(円記号の区切り・ドライブ名 C:)が前提(段1: Windows 以外では飛ばす)")
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

    def test_settings_patch_keeps_other_values(self):
        """ほかの画面から直す設定(api/settings/patch。送ったキーだけ・許可した項目だけ)。丸ごとの保存(PUT)ではその値を残す(パックの音量。2026-09-29)"""
        orig = {k: v for k, v in self.call("GET", "/api/settings").items() if k != "_status"}
        try:
            self.assertEqual(self.call("PUT", "/api/settings", dict(orig, packLoudness=-11))["_status"], 200)
            self.assertNotIn("packLoudness", self.call("GET", "/api/settings"))           # 丸ごとの保存では直せない
            r = self.call("POST", "/api/settings/patch", {"values": {"packLoudness": 0, "packVolume": 70}})
            self.assertEqual((r["_status"], r["values"]), (200, {"packLoudness": 0, "packVolume": 70}))
            self.call("PUT", "/api/settings", dict(orig, quality="fast", packLoudness=-14, packVolume=100))   # 開いたままの古い画面の保存
            st = self.call("GET", "/api/settings")
            self.assertEqual((st.get("quality"), st["packLoudness"], st["packVolume"]), ("fast", 0, 70))   # ほかの値は直り、音量は残る
            for bad in ({"values": {"packLoudness": -20}}, {"values": {"packVolume": 0}}, {"values": {"packVolume": True}},
                        {"values": {"model": "x"}}, {"values": {}}, {}):
                self.assertEqual(self.call("POST", "/api/settings/patch", bad)["_status"], 400, bad)
        finally:
            self.call("PUT", "/api/settings", orig)

    def test_settings_device_goes_to_machine_json(self):
        """⚙ のデバイス(device)は machine.json(この PC の設定)に書かれ、GET /api/settings はその値を返す。settings.json の古い値は消さない(RS7-1 S6b)"""
        def machine_files():
            return [os.path.join(d, "machine.json") for d, _n, fs in os.walk(self.tmp) if "machine.json" in fs]
        orig = {k: v for k, v in self.call("GET", "/api/settings").items() if k != "_status"}
        try:
            self.assertEqual(self.call("PUT", "/api/settings", dict(orig, device="cpu"))["_status"], 200)   # 丸ごとの保存
            self.assertEqual(self.call("GET", "/api/settings").get("device"), "cpu")
            files = machine_files()
            self.assertEqual(len(files), 1)
            with open(files[0], encoding="utf-8") as f:
                self.assertEqual(json.load(f).get("device"), "cpu")
            self.assertEqual(self.call("PUT", "/api/settings", {"patch": {"device": "vulkan", "quality": "fast"}})["_status"], 200)   # 差分の保存
            st = self.call("GET", "/api/settings")
            self.assertEqual((st.get("device"), st.get("quality")), ("vulkan", "fast"))
            self.assertEqual(self.call("PUT", "/api/settings", {"patch": {"device": "nope"}})["_status"], 400)
            self.assertEqual(self.call("GET", "/api/settings").get("device"), "vulkan")
        finally:
            self.call("PUT", "/api/settings", {"patch": {"device": None}})
            self.call("PUT", "/api/settings", orig)
            for f in machine_files():
                os.remove(f)

    def test_settings_put_patch(self):
        """PUT /api/settings {"patch"}(段2 監査 11): 送ったキーだけ合わせる。2つの窓が別々のキーを保存しても消し合わない"""
        orig = {k: v for k, v in self.call("GET", "/api/settings").items() if k != "_status"}
        try:
            self.assertEqual(self.call("PUT", "/api/settings", dict(orig, glossary="元", replacements="元=>元"))["_status"], 200)
            self.assertEqual(self.call("PUT", "/api/settings", {"patch": {"glossary": "窓A"}})["_status"], 200)
            self.assertEqual(self.call("PUT", "/api/settings", {"patch": {"replacements": "窓B=>B"}})["_status"], 200)
            st = self.call("GET", "/api/settings")
            self.assertEqual((st["glossary"], st["replacements"]), ("窓A", "窓B=>B"))
            self.assertEqual(self.call("PUT", "/api/settings", {"patch": "x"})["_status"], 400)
            self.assertEqual(self.call("PUT", "/api/settings", {"patch": {"a": "x" * 210000}})["_status"], 413)
        finally:
            self.call("PUT", "/api/settings", orig)

    def test_settings_patch_keymap(self):
        """キー配置(UIKit.keymap が送る。段6)は「送ったキーだけ直す」。丸ごとの保存(古い画面)では戻らない・形の正しくない割り当ては断る"""
        orig = {k: v for k, v in self.call("GET", "/api/settings").items() if k != "_status"}
        try:
            km = {"rowNext": "h", "proof": "Shift+Space", "seekBack": "ArrowLeft", "del": "", "insert": "+"}
            self.assertEqual(self.call("POST", "/api/settings/patch", {"values": {"keymap": km}})["_status"], 200)
            self.call("PUT", "/api/settings", dict(orig, keymap={"rowNext": "s"}))   # 開いたままの古い画面の保存
            self.assertEqual(self.call("GET", "/api/settings")["keymap"], km)
            for bad in ({"rowNext": "Ctrl+s"}, {"rowNext": "s\n"}, {"1bad": "s"}, {"rowNext": 1}, ["s"], {"a%d" % i: "s" for i in range(61)}):
                self.assertEqual(self.call("POST", "/api/settings/patch", {"values": {"keymap": bad}})["_status"], 400, bad)
        finally:
            self.call("PUT", "/api/settings", orig)
            self.call("POST", "/api/settings/patch", {"values": {"keymap": orig.get("keymap") or {}}})

    def test_settings_patch_cut_silence(self):
        """2 カット の「無音 ▾」の値(cutSilence。段7 E-5)は「送ったキーだけ直す」。3 つの値がそろい、cut2resolve と同じ範囲のときだけ受ける。
        まとめて実行(pipeline/run.py の _pack_settings)は同じ鍵の noise・min・pad を読む"""
        orig = {k: v for k, v in self.call("GET", "/api/settings").items() if k != "_status"}
        try:
            v = {"noise": -30, "min": 0.8, "pad": 0.2}
            self.assertEqual(self.call("POST", "/api/settings/patch", {"values": {"cutSilence": v}})["_status"], 200)
            self.call("PUT", "/api/settings", dict(orig, cutSilence={"noise": -35, "min": 0.6, "pad": 0.15}))   # 開いたままの古い画面の丸ごとの保存では戻らない
            self.assertEqual(self.call("GET", "/api/settings")["cutSilence"], v)
            for bad in ({"noise": -91, "min": 0.6, "pad": 0.1}, {"noise": 1, "min": 0.6, "pad": 0.1}, {"noise": -35, "min": 0.01, "pad": 0.1},
                        {"noise": -35, "min": 61, "pad": 0.1}, {"noise": -35, "min": 0.6, "pad": 11}, {"noise": -35, "min": 0.6},
                        {"noise": -35, "min": 0.6, "pad": 0.1, "x": 1}, {"noise": "-35", "min": 0.6, "pad": 0.1}, {"noise": True, "min": 0.6, "pad": 0.1}, [-35, 0.6, 0.1]):
                self.assertEqual(self.call("POST", "/api/settings/patch", {"values": {"cutSilence": bad}})["_status"], 400, bad)
        finally:
            self.call("PUT", "/api/settings", orig)
            if "cutSilence" in orig:
                self.call("POST", "/api/settings/patch", {"values": {"cutSilence": orig["cutSilence"]}})

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
        # 行の端を声の止まる所まで広げる(⑥ pack.ROW_EDGE。音は 0〜1.5 秒・3〜4.5 秒):
        # 一 0.5〜1.5 → 前は無音が無いので 0.1 秒・後ろはカット済の行(二)を越えない。三 3.0〜4.25 → 無音の始まり 4.5 まで(前は無音の中なので動かさない)
        self.assertEqual((r["base"], r["keepsSec"]), ("rows", [[0.4, 1.5], [3.0, 4.5]]))
        self.assertEqual(os.path.normcase(r["planBeside"]), os.path.normcase(os.path.splitext(video)[0] + ".cut-plan.json"))
        stem = os.path.splitext(os.path.basename(video))[0]
        for p in (os.path.splitext(video)[0] + ".transcript.json", os.path.join(os.path.dirname(video), "作業用", stem + ".transcript.json")):
            self.assertFalse(os.path.exists(p))   # 動画の隣・作業用\ にファイルを増やさない
        # 設定の rowEdge で変えられる(zip・まとめて実行も同じ設定)
        settings = self.call("GET", "/api/settings")
        settings.pop("_status", None)
        try:
            self.call("PUT", "/api/settings", dict(settings, rowEdge={"on": False, "after": 0.5, "before": 0.3}))
            r = self.call("GET", "/api/edit/draft?id=" + tid)
            self.assertEqual(r["keepsSec"], [[0.5, 1.5], [3.0, 4.266667]])   # 広げない(4.25 秒は 30fps のフレーム 128 = 4.2667 に丸める)
            self.call("PUT", "/api/settings", dict(settings, rowEdge={"after": 0.1, "before": 0}))
            r = self.call("GET", "/api/edit/draft?id=" + tid)
            self.assertEqual(r["keepsSec"], [[0.5, 1.5], [3.0, 4.366667]])   # 上限 0.1 秒(4.5 の無音は窓の外 → 決まった余白も上限まで)
            self.call("PUT", "/api/settings", dict(settings, rowEdge="壊れた値"))
            r = self.call("GET", "/api/edit/draft?id=" + tid)
            self.assertEqual(r["keepsSec"], [[0.4, 1.5], [3.0, 4.5]])        # 読めない設定は既定にして知らせる
            self.assertTrue(any("既定にしました" in w for w in r["warnings"]), r["warnings"])
        finally:
            self.call("PUT", "/api/settings", settings)
        # カットを保存した文書は、開いただけでは「行から」を計算しない(rows=1 = 「行から」のボタンのときだけ)
        self.assertEqual(self.call("PUT", "/api/edit?id=" + tid, {"baseRev": 0, "edit": edit_obj(clips=((0.0, 2.0),), duration=6.0)})["rev"], 1)
        r = self.call("GET", "/api/edit/draft?id=" + tid)
        self.assertEqual((r["base"], r.get("skipped"), r["fps"]), ("all", True, [30, 1]))
        r = self.call("GET", "/api/edit/draft?rows=1&id=" + tid)
        # 保存したカット(0〜2 秒)で行の印が付け直された(二 は残す行・三 はカット済)→ 一・二 の 0.5〜3.0 を広げる(三 は越えない)
        self.assertEqual((r["base"], r["keepsSec"]), ("rows", [[0.4, 3.0]]))
        # ネットワーク上の動画は調べない・動画の無い文書
        with open(os.path.join(self.tmp, "transcripts", "abcdefabcdef.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "abcdefabcdef", "title": "n", "sourcePath": r"\\server\share\x.mp4", "segments": [], "updatedAt": 1}, f)
        r = self.call("GET", "/api/edit/draft?id=abcdefabcdef")
        self.assertEqual((r["_status"], r["unavailable"]["code"]), (200, "network_path"))
        self.assertEqual(self.call("GET", "/api/edit/draft?id=zzz")["_status"], 404)

    def test_draft_waits_for_heavy_slot_then_falls_back(self):
        """行の端の無音をまだ調べていないときだけ SLOTS の順番を待つ。取れなければ決まった余白で広げて知らせる"""
        import contextlib
        from pipeline.pack import resolve_export
        video = os.path.join(self.media_dir, "順番.mkv")
        shutil.copy(self.video, video)
        doc = {"sourcePath": video, "whole": True, "segments": [{"id": "a", "start": 0.5, "end": 1.2, "text": "一"}]}
        asked = []

        @contextlib.contextmanager
        def busy(label):
            asked.append(label)
            yield False
        r = resolve_export.edit_draft(doc, "t", heavy=busy)
        self.assertEqual((r["keepsSec"], len(asked)), ([[0.4, 1.4]], 1))              # 決まった余白(前 0.1・後 0.2)
        self.assertTrue(any("他の重い処理" in w for w in r["warnings"]), r["warnings"])

        @contextlib.contextmanager
        def free(label):
            asked.append(label)
            yield True
        r = resolve_export.edit_draft(doc, "t", heavy=free)
        self.assertEqual((r["keepsSec"], len(asked)), ([[0.4, 1.5]], 2))              # 無音の始まり 1.5 まで
        r = resolve_export.edit_draft(doc, "t", heavy=busy)
        self.assertEqual((r["keepsSec"], len(asked)), ([[0.4, 1.5]], 2))              # 調べた無音は覚えている(順番を待たない)

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
        segs2 = [dict(g) for g in segs]
        segs2[2]["text"] = "今日はいい天気ですね散歩に行こう"      # 見本と Text+ の改行(12 ②)を見るための長い字幕
        d2 = self.call("GET", "/api/transcript?id=" + tid)
        self.call("PUT", "/api/transcript?id=" + tid, {"title": d2["title"], "speakers": [], "segments": segs2, "baseUpdatedAt": d2["updatedAt"]})
        NL = chr(10)
        r = self.call("POST", "/api/edit/preview", {"id": tid, "keeps": [[3.0, 5.1]], "wrap": 8})
        self.assertEqual(r["samples"], ["今日はいい天気ですね" + NL + "散歩に行こう"])      # 見本もパックと同じ改行(resolve_textplus.wrap_caption)
        r = self.call("POST", "/api/edit/preview", {"id": tid, "keeps": [[3.0, 5.1]], "wrap": 0})
        self.assertEqual(r["samples"], ["今日はいい天気ですね散歩に行こう"])
        self.assertEqual(r["sampleSpeakers"], [None])                                       # 話者の無い文書: samples と同じ長さで全部 None
        # 4-5: 見本ごとの話者の名前(pack.cue_speakers = 実際のパックと同じ規則)。「一」= みこ・「三」= 話者なし
        spk_segs = [dict(segs[0], speaker="S1"), dict(segs[1]), dict(segs[2], text="三")]
        dd = self.call("GET", "/api/transcript?id=" + tid)
        self.call("PUT", "/api/transcript?id=" + tid, {"title": dd["title"], "speakers": [{"id": "S1", "name": "みこ"}], "segments": spk_segs,
                                                       "baseUpdatedAt": dd["updatedAt"]})
        r = self.call("POST", "/api/edit/preview", {"id": tid, "keeps": [[0.5, 1.5], [3.0, 5.1]]})
        self.assertEqual((r["samples"], r["sampleSpeakers"]), (["一", "三"], ["みこ", None]))
        dd = self.call("GET", "/api/transcript?id=" + tid)
        self.call("PUT", "/api/transcript?id=" + tid, {"title": dd["title"], "speakers": [], "segments": [dict(g, speaker=None) for g in spk_segs],
                                                       "baseUpdatedAt": dd["updatedAt"]})
        r = self.call("POST", "/api/edit/preview", {"id": tid, "keeps": [[0.5, 1.5], [3.0, 5.1]]})
        self.assertEqual((r["samples"], r["sampleSpeakers"]), (["一", "三"], [None, None]))
        dd = self.call("GET", "/api/transcript?id=" + tid)                                   # 以降の確認のため、元の文書(segs2)に戻す
        self.call("PUT", "/api/transcript?id=" + tid, {"title": dd["title"], "speakers": [], "segments": segs2, "baseUpdatedAt": dd["updatedAt"]})
        st, hd, body = self.call("POST", "/api/resolve-package", {"tid": tid, "fps": "30", "size": "1080x1920"}, raw=True)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            from pipeline.pack import resolve_textplus
            ipw =resolve_textplus.read_script_plan(z.read(next(n for n in z.namelist() if n.endswith("/create_resolve_textplus_project.lua"))).decode("utf-8"))
        self.assertIn("今日はいい天気ですね" + NL + "散歩に行こう", [c["text"] for c in ipw["captions"]])   # zip も設定の縦 8 で2段
        self.call("PUT", "/api/transcript?id=" + tid, {"title": d2["title"], "speakers": [], "segments": segs,
                                                       "baseUpdatedAt": self.call("GET", "/api/transcript?id=" + tid)["updatedAt"]})
        r = self.call("POST", "/api/edit/preview", {"id": tid, "keeps": keeps})
        self.assertEqual((r["_status"], r["count"], r["captions"], r["fps"]), (200, 3, 3, [30, 1]))   # 接している区間は1つに数える
        self.assertAlmostEqual(r["keptSec"], 1.3 + 0.2 + 2.1, places=3)
        self.assertTrue(any("0.5 秒より短い区間" in w for w in r["warnings"]), r["warnings"])
        self.assertFalse(os.path.exists(os.path.splitext(video)[0] + ".transcript.json"))   # 見積もりでは動画の隣にファイルを作らない
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(video), "作業用")))      # 作業用\ も作らない
        for bad in ([], [[1, 0.5]], [[0, 1], [0.5, 2]], "x", [[0, True]]):
            self.assertEqual(self.call("POST", "/api/edit/preview", {"id": tid, "keeps": bad}).get("error"), "bad_keeps", bad)
        # zip もカットのとおり(3区間・30fps のフレーム)
        st, hd, body = self.call("POST", "/api/resolve-package", {"tid": tid, "fps": "30", "size": "1080x1920"}, raw=True)
        self.assertEqual((st, hd["X-Resolve-Cuts"]), (200, "3"))
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            from pipeline.pack import resolve_textplus
            ip =resolve_textplus.read_script_plan(z.read(next(n for n in z.namelist() if n.endswith("/create_resolve_textplus_project.lua"))).decode("utf-8"))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(15, 54), (60, 66), (90, 153)])
        # 残す区間(.cut-plan.json)の保存もカットのとおり
        r = self.call("POST", "/api/export-file", {"id": tid, "format": "cut-plan-v1"})
        with open(r["path"], encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual([(g["start"], g["end"]) for g in plan["segments"]], [(0.5, 1.8), (2.0, 2.2), (3.0, 5.1)])
        # 前回のパックの手順書: 記録したフォルダが cut2resolve のパックのときだけ読む(cut2resolve の記録か、以前のパックなら cut2resolve の cut-plan.json。
        # 記録で読めることは ytt の test_pack_record・cut2resolve の test_serve で確かめる)
        out = os.path.join(self.media_dir, "パック_pack")
        os.makedirs(out, exist_ok=True)
        self.call("POST", "/api/edit/pack", {"id": tid, "rev": 1, "docUpdatedAt": 0, "dir": out, "files": ["友人へ.txt"]})
        with open(os.path.join(out, "友人へ.txt"), "w", encoding="utf-8") as f:
            f.write("Resolve で開く手順")
        self.assertEqual(self.call("GET", "/api/edit/pack-readme?id=" + tid)["_status"], 404)   # cut-plan.json が無い = パックではない
        with open(os.path.join(out, "cut-plan.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-cut-plan/v1", "tool": {"name": "transcribe"}}, f)
        self.assertEqual(self.call("GET", "/api/edit/pack-readme?id=" + tid)["_status"], 404)   # 他のツールの cut-plan.json はパックではない
        with open(os.path.join(out, "cut-plan.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-cut-plan/v1", "tool": {"name": "cut2resolve"}}, f)
        r = self.call("GET", "/api/edit/pack-readme?id=" + tid)
        self.assertEqual((r["name"], r["text"]), ("友人へ.txt", "Resolve で開く手順"))                # 2026-09-27 より前のパック
        # 今のパック(手順書のファイルが無い): パックの Lua に埋め込んだ計画から手順を作り直す
        from pipeline.pack import resolve_export
        _pk, tp = resolve_export._load_pack()
        plan = {"schema": tp.SCHEMA, "title": "パック", "fps": "30/1", "nominalFps": 30, "mediaFps": 30.0,
                "target": {"fps": 30, "width": 1080, "height": 1920},
                "media": {"file": "パック.mp4", "name": "パック.mp4", "width": 1920, "height": 1080},
                "cuts": [{"sourceStartFrame": 0, "sourceEndFrame": 30}], "captions": [], "captionWrap": 8,
                "sourceTimeline": {"startFrame": 0, "endFrame": 30}, "style": {"name": "見た目", "inputs": []}}
        with open(os.path.join(out, "create_resolve_textplus_project.lua"), "w", encoding="utf-8") as f:
            f.write(tp.importer_script(plan))
        r = self.call("GET", "/api/edit/pack-readme?id=" + tid)
        self.assertEqual(r["name"], "")
        self.assertIn("動画: パック.mp4", r["text"])
        self.assertIn("1080 x 1920", r["text"])

    def test_resplit_with_saved_words(self):
        """今の文書を分け直す(12 ②): 単語の時刻(words.json)で、校正済みでない・文字が単語と一致する長い行だけ分ける。前の版は履歴に残す"""
        tid = self.open_video(self.wav)["id"]
        doc = self.call("GET", "/api/transcript?id=" + tid)
        long1 = "きょうはいいてんきですねさんぽにいきましょうか"       # 23 文字(縦 16 + 2 を超える)
        segs = [{"id": "a", "start": 0.0, "end": 4.6, "text": long1, "speaker": "sp1", "flag": "自信が低い"},
                {"id": "b", "start": 5.0, "end": 9.6, "text": long1, "proofed": True},                 # 校正済み → 触らない
                {"id": "c", "start": 10.0, "end": 14.6, "text": "ぜんぜんちがうぶんしょうになおしたぎょうですよね"},   # 人が直した(単語と違う)
                {"id": "d", "start": 15.0, "end": 16.0, "text": "みじかい"}]
        r = self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [{"id": "sp1", "name": "話者A"}], "segments": segs})
        r = self.call("POST", "/api/resplit", {"id": tid})
        self.assertEqual((r["_status"], r["error"]), (400, "no_words"))                    # 単語の時刻が無い → 範囲の再認識を案内
        self.assertIn("範囲を再認識", r["message"])
        words = []
        for t0 in (0.0, 5.0, 10.0):
            words += [[round(t0 + i * 0.2, 2), round(t0 + (i + 1) * 0.2, 2), ch] for i, ch in enumerate(long1)]
        with open(os.path.join(self.tmp, "transcripts", tid + ".words.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "youtube-tools-words/v1", "words": words}, f, ensure_ascii=False)
        before = self.call("GET", "/api/transcript?id=" + tid)
        r = self.call("POST", "/api/resplit", {"id": tid, "baseUpdatedAt": before["updatedAt"] - 1})
        self.assertEqual(r["_status"], 409)                                                 # 別の画面で先に保存されている
        r = self.call("POST", "/api/resplit", {"id": tid, "orientation": "vertical", "baseUpdatedAt": before["updatedAt"]})
        self.assertEqual((r["_status"], r["changed"], r["skipped"]), (200, 1, 1), r)        # a だけ分ける・c は単語と違う
        after = self.call("GET", "/api/transcript?id=" + tid)
        got = [(g["id"], g["text"], g.get("speaker"), g.get("flag")) for g in after["segments"]]
        self.assertEqual([x[0] for x in got], ["a", "a-2", "b", "c", "d"])
        self.assertEqual("".join(x[1] for x in got[:2]), long1)
        self.assertTrue(all(len(x[1]) <= 18 for x in got[:2]))
        self.assertEqual((got[1][2], got[1][3]), ("sp1", "自信が低い"))                    # 話者・印を引き継ぐ
        self.assertEqual(after["segments"][2]["text"], long1)                               # 校正済みはそのまま
        hist = self.call("GET", "/api/history?id=" + tid)["items"]
        self.assertTrue(hist)                                                               # 分ける前の版が「以前の版に戻す」にある
        r = self.call("POST", "/api/resplit", {"id": tid, "orientation": "horizontal"})
        self.assertEqual(r["changed"], 0)                                                   # 横(28)では分ける行が無い
        # 文書を消すと words.json も消える
        wp = os.path.join(self.tmp, "transcripts", tid + ".words.json")
        self.assertTrue(os.path.isfile(wp))
        self.assertEqual(self.call("DELETE", "/api/transcript?id=" + tid)["_status"], 200)
        self.assertFalse(os.path.exists(wp))

    def test_redo_suspicious_rows(self):
        """疑わしい所だけ認識し直す(12 ③-2)の HTTP: 良くなった行だけ置き換える・校正済みは触らない・前の版は履歴・対象が無ければ 400"""
        video = os.path.join(self.media_dir, "認識し直し.wav")
        shutil.copy(self.wav, video)
        tid = self.open_video(video)["id"]
        doc = self.call("GET", "/api/transcript?id=" + tid)
        F = "長い区間に文字が少ない(抜けの可能性)"
        r = self.call("POST", "/api/redo", {"tid": tid})
        self.assertEqual((r["_status"], r["error"]), (400, "empty"))                         # 行が無い
        segs = [{"id": "p", "start": 0.0, "end": 0.9, "text": "前の行"},
                {"id": "a", "start": 1.0, "end": 6.0, "text": "黒", "flag": F},
                {"id": "b", "start": 6.5, "end": 11.0, "text": "あ", "flag": F, "proofed": True}]
        self.call("PUT", "/api/transcript?id=" + tid, {"title": doc["title"], "speakers": [], "segments": segs})
        r = self.call("POST", "/api/redo", {"tid": tid})
        self.assertEqual((r["_status"], r.get("kind")), (200, "redo"), r)
        end = time.time() + 30
        while time.time() < end:
            j = next(x for x in self.call("GET", "/api/jobs")["jobs"] if x["id"] == r["id"])
            if j["state"] in ("done", "error", "cancelled"):
                break
            time.sleep(0.1)
        self.assertEqual((j["state"], j["segments"]), ("done", 1), j)
        self.assertIn("1 か所を置き換えました", j["phase"])
        after = self.call("GET", "/api/transcript?id=" + tid)
        got = [(g["id"], g["text"]) for g in after["segments"]]
        self.assertEqual([x[0] for x in got], ["p", "a-r1", "b"], got)
        self.assertTrue(got[1][1].startswith("認識し直した文"))
        self.assertEqual(got[2][1], "あ")                                                     # 校正済みはそのまま
        self.assertTrue(after["segments"][1]["start"] >= 0.9 and after["segments"][1]["end"] <= 6.5)   # 隣の行にかからない範囲
        self.assertTrue(self.call("GET", "/api/history?id=" + tid)["items"])                  # 前の版が「以前の版に戻す」に
        self.assertEqual(after["redo"]["rows"], 1)
        r = self.call("POST", "/api/redo", {"tid": tid})
        self.assertEqual((r["_status"], r["error"]), (400, "empty"))                         # もう疑わしい行が無い

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

class TestRelinkStore(StoreDir):
    """動画を選び直す(段2 B-4)のうち、ロック・競合・ジョブ・長さの同意・控え・書き換える項目(動画を調べる部分は差し替える)"""

    def setUp(self):
        super().setUp()
        self.saved_check = S.relink_check
        self.chk = {"path": os.path.abspath("新しい.mp4"), "name": "新しい.mp4", "durationSec": 12.0, "fps": [30, 1], "hasVideo": True,
                    "docDuration": 12.0, "diffSec": 0.0, "mismatch": False, "sameAsNow": False, "usedBy": [], "rowsAfterEnd": 0, "warnings": []}
        S.relink_check = lambda obj: dict(self.chk)
        segs = doc_obj()["segments"]
        segs[0].update(proofed=True, speaker="A", tags=["bgm"])
        self.put_doc(doc_obj(segments=segs, speakers=[{"id": "A", "name": "まつり", "color": "#f80"}],
                             original=[{"start": 0.4, "end": 2.8, "text": "こんばんわ"}], clip={"schema": "x"}))
        write_json(S.edit_path(TID), dict(S.sanitize_edit(edit_obj()), schema=S.EDIT_SCHEMA, rev=3, packRev=0, updatedAt=5))
        d = self.doc()
        S.apply_edit_cuts(TID, d)   # 保存済みの文書と同じく、行の「カット済」はカットに合わせてある
        self.put_doc(d)

    def tearDown(self):
        S.relink_check = self.saved_check
        with S._jobs_lock:
            for k in [k for k in S._jobs if k.startswith("relinktest")]:
                S._jobs.pop(k)
        super().tearDown()

    def doc(self):
        with open(S.tx_path(TID), encoding="utf-8") as f:
            return json.load(f)

    def relink(self, **over):
        return S.relink_doc(dict({"id": TID, "path": "x", "baseUpdatedAt": 1000}, **over))

    def test_relink_keeps_rows_and_makes_backups(self):
        before = self.doc()
        r = self.relink()
        self.assertTrue(r["ok"])
        d = self.doc()
        self.assertEqual((d["sourcePath"], d["sourceName"], d["updatedAt"]), (self.chk["path"], "新しい.mp4", r["updatedAt"]))
        self.assertGreater(d["updatedAt"], 1000)
        self.assertEqual(d["relinks"], [{"from": "C:\\x\\clip.mp4", "at": r["updatedAt"], "diffSec": 0.0}])
        for k in ("segments", "speakers", "original", "clip", "start", "end", "duration", "title", "createdAt"):
            self.assertEqual(d[k], before[k], k)                                   # 行・校正・話者・元の出力・clip・範囲は変えない
        bak = os.path.join(self.tmp, ".bak")
        with open(os.path.join(bak, TID + ".pre-relink.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["sourcePath"], "C:\\x\\clip.mp4")        # 1) 直前の文書
        with open(os.path.join(bak, TID + ".edit.pre-relink.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rev"], 3)                               # 2) カット
        stamps = S.hist_stamps(TID)                                                # 3) 履歴(「以前の版に戻す」)
        self.assertEqual(len(stamps), 1)
        S.restore_history(TID, stamps[0])
        self.assertEqual(self.doc()["sourcePath"], "C:\\x\\clip.mp4")
        with open(S.edit_path(TID), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rev"], 3)                               # カット(edit.json)は書き換えない

    def test_relink_record_is_capped(self):
        d = self.doc()
        d["relinks"] = [{"from": "C:\\old%d.mp4" % i, "at": i, "diffSec": 0} for i in range(12)]
        self.put_doc(d)
        self.relink()
        rl = self.doc()["relinks"]
        self.assertEqual(len(rl), S.RELINK_KEEP)
        self.assertEqual(rl[-1]["from"], "C:\\x\\clip.mp4")

    def test_conflict_busy_mismatch(self):
        with self.assertRaises(S.ApiError) as c:
            self.relink(baseUpdatedAt=999)
        self.assertEqual((c.exception.status, c.exception.code), (409, "conflict"))
        with self.assertRaises(S.ApiError) as c:
            self.relink(baseUpdatedAt=None)
        self.assertEqual(c.exception.status, 400)
        for kind, spec in (("diarize", {"tid": TID}), ("transcribe", {"intoDoc": TID})):
            with S._jobs_lock:
                S._jobs["relinktest1"] = {"id": "relinktest1", "state": "running", "kind": kind, "tid": spec.get("tid"), "spec": spec}
            with self.assertRaises(S.ApiError) as c:
                self.relink()
            self.assertEqual((c.exception.status, c.exception.code), (409, "busy"), kind)
            with S._jobs_lock:
                S._jobs["relinktest1"]["state"] = "done"                            # 終わったジョブは妨げない
        self.chk.update(mismatch=True, diffSec=-30.0)
        with self.assertRaises(S.ApiError) as c:
            self.relink()
        self.assertEqual((c.exception.status, c.exception.code), (409, "duration_mismatch"))
        self.assertTrue(c.exception.extra["check"]["mismatch"])
        self.assertEqual(self.doc()["sourcePath"], "C:\\x\\clip.mp4")               # 同意が無ければ書かない
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".bak", TID + ".pre-relink.json")))
        self.assertTrue(self.relink(acceptDiff=True)["ok"])
        self.assertEqual(self.doc()["relinks"][-1]["diffSec"], -30.0)
        self.chk.update(mismatch=False, sameAsNow=True)
        with self.assertRaises(S.ApiError) as c:
            self.relink(baseUpdatedAt=self.doc()["updatedAt"])
        self.assertEqual(c.exception.code, "same_path")

    def test_relink_ref_rules(self):
        self.assertEqual(S._relink_ref({"whole": True, "duration": 100.0, "end": 100.0}), (100.0, True))
        self.assertEqual(S._relink_ref({"whole": False, "duration": 100.0, "end": 40.0}), (40.0, False))
        self.assertEqual(S._relink_ref({"segments": [{"end": 7.5}, {"end": 3}]}), (7.5, False))
        self.assertEqual(S._relink_ref({"segments": []}), (None, False))

    def test_relink_path_rejects(self):
        for bad in ("", "  ", "a\x00b.mp4", "動画.mp4", "\\\\server\\share\\a.mp4", "//server/share/a.mp4", "\\\\?\\UNC\\server\\s\\a.mp4"):
            with self.assertRaises(S.ApiError, msg=repr(bad)) as c:
                S.relink_path(bad)
            self.assertEqual(c.exception.status, 400)
        with self.assertRaises(S.ApiError) as c:
            S.relink_path("\\\\server\\share\\a.mp4")
        self.assertEqual(c.exception.code, "network_path")
        vid = os.path.join(self.tmp, "中.mp4")   # StoreDir は TX_DIR を差し替えるだけなので、DATA_DIR も一時的にここへ
        with open(vid, "wb") as f:
            f.write(b"x")
        saved = S.DATA_DIR
        S.DATA_DIR = self.tmp
        try:
            with self.assertRaises(S.ApiError) as c:
                S.relink_path(vid)
            self.assertIn("作業データ", c.exception.message)
        finally:
            S.DATA_DIR = saved
        with self.assertRaises(S.ApiError) as c:
            S.relink_path(os.path.join(self.tmp, "無い.mp4"))
        self.assertEqual(c.exception.code, "no_file")
        txt = os.path.join(self.tmp, "メモ.txt")
        with open(txt, "w") as f:
            f.write("x")
        with self.assertRaises(S.ApiError) as c:
            S.relink_path(txt)
        self.assertEqual(c.exception.code, "bad_ext")
        self.assertEqual(S.relink_path('"%s"' % vid), os.path.realpath(vid))       # 「パスとしてコピー」の " は外す

    @unittest.skipUnless(os.name == "nt", "Windows のパスの形(ドライブ・代替ストリーム)")
    def test_relink_path_windows_forms(self):
        vid = os.path.join(self.tmp, "a.mp4")
        with open(vid, "wb") as f:
            f.write(b"x")
        for bad in (vid + ":stream", vid + ":stream:$DATA", "C:a.mp4", "\\a.mp4"):
            with self.assertRaises(S.ApiError, msg=bad) as c:
                S.relink_path(bad)
            self.assertEqual(c.exception.status, 400)
        self.assertEqual(S.relink_path(vid.replace("\\", "/")), os.path.realpath(vid))


class TestRelinkFind(StoreDir):
    """まとめて付け替える・参照…(v0.31.0)のサーバー側: 見つからない文書の一覧・フォルダの中の同じファイル名の候補・参照の窓の API(窓そのものは差し替える)"""
    T1, T2, T3, T4 = "0123456789ab", "0123456789ac", "0123456789ad", "0123456789ae"

    def setUp(self):
        super().setUp()
        S._summary_cache.clear()   # 一時フォルダごとに同じ id・同じ大きさの文書を作るので、前のテストの要約を引かない
        self.media = tempfile.mkdtemp()
        self.saved_data = S.DATA_DIR

    def tearDown(self):
        S.DATA_DIR = self.saved_data
        S._summary_cache.clear()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def touch(self, *parts):
        p = os.path.join(self.media, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x")
        return p

    def doc(self, tid, source, **over):
        self.put_doc(doc_obj(id=tid, sourcePath=source, sourceName=os.path.basename(source.replace("\\", "/")), **over), tid)

    @unittest.skipUnless(os.name == "nt", "Windows のパスの形(ドライブ・ネットワークパス)")
    def test_missing_lists_only_docs_with_lost_video(self):
        here = self.touch("ある.mp4")
        self.doc(self.T1, here, updatedAt=10)                                       # 動画がある → 出さない
        self.doc(self.T2, os.path.join(self.media, "無い.mp4"), updatedAt=20, title="消えた")   # 動画が無い → 出す
        self.doc(self.T3, "", updatedAt=30)                                         # パスの記録が無い → 出さない・数えもしない
        self.doc(self.T4, os.path.join(self.media, "別の場所", "無い2.mp4"), updatedAt=40)       # フォルダごと無い → 出す
        r = S.relink_missing()
        self.assertEqual(r["skipped"], 0)
        self.assertEqual([i["id"] for i in r["items"]], [self.T4, self.T2])         # 新しい順
        it = r["items"][1]
        self.assertEqual((it["title"], it["sourceName"], it["updatedAt"], it["sourcePath"]),
                         ("消えた", "無い.mp4", 20, os.path.join(self.media, "無い.mp4")))

    @unittest.skipUnless(os.name == "nt", "Windows のパスの形(ドライブ・ネットワークパス)")
    def test_missing_skips_network_and_relative_paths(self):
        self.doc(self.T1, "\\\\server\\share\\a.mp4")   # ネットワークパスには触らず、数だけ返す
        self.doc(self.T2, "a.mp4")                      # 相対パスも調べない
        self.doc(self.T3, os.path.join(self.media, "無い.mp4"))
        r = S.relink_missing()
        self.assertEqual(r["skipped"], 2)
        self.assertEqual([i["id"] for i in r["items"]], [self.T3])

    def test_find_matches_same_name_only(self):
        self.doc(self.T1, "C:\\x\\clip.mp4")
        a = self.touch("下", "clip.mp4")
        b = self.touch("下", "さらに", "clip.mp4")
        self.touch("下", "clip.txt")        # 拡張子が違う
        self.touch("下", "clip2.mp4")       # 別名
        self.touch("clip.mp4.bak")
        r = S.relink_find({"folder": self.media, "ids": [self.T1]})
        self.assertEqual(sorted(r["candidates"][self.T1]), sorted([a, b]))
        self.assertFalse(r["truncated"])
        self.assertGreater(r["scanned"], 0)
        self.assertEqual(r["folder"], os.path.realpath(self.media))

    def test_find_ignores_non_media_names_and_bad_ids(self):
        self.doc(self.T1, "C:\\x\\clip.mp4")
        self.doc(self.T2, "C:\\x\\notes.txt")    # 動画・音声の拡張子でない名前は探さない
        self.touch("notes.txt")
        r = S.relink_find({"folder": self.media, "ids": [self.T1, self.T2, "../bad", "zzz"]})
        self.assertEqual(r["candidates"], {})

    @unittest.skipUnless(os.name == "nt", "Windows のファイル名は大文字小文字を区別しない(normcase)")
    def test_find_case_insensitive(self):
        self.doc(self.T1, "C:\\x\\Clip.MP4")
        p = self.touch("a", "CLIP.mp4")
        r = S.relink_find({"folder": self.media, "ids": [self.T1]})
        self.assertEqual(r["candidates"][self.T1], [p])

    def test_find_skips_dot_dirs_and_data_dir(self):
        self.doc(self.T1, "C:\\x\\clip.mp4")
        ok = self.touch("ふつう", "clip.mp4")
        self.touch(".隠し", "clip.mp4")
        S.DATA_DIR = os.path.join(self.media, "作業データ")
        self.touch("作業データ", "clip.mp4")
        r = S.relink_find({"folder": self.media, "ids": [self.T1]})
        self.assertEqual(r["candidates"][self.T1], [ok])

    def test_find_depth_limit_truncates(self):
        self.doc(self.T1, "C:\\x\\clip.mp4")
        near = self.touch("a", "clip.mp4")
        self.touch("a", "b", "clip.mp4")
        saved = S.FIND_MAX_DEPTH
        S.FIND_MAX_DEPTH = 1
        try:
            r = S.relink_find({"folder": self.media, "ids": [self.T1]})
        finally:
            S.FIND_MAX_DEPTH = saved
        self.assertEqual(r["candidates"][self.T1], [near])   # 深さ 1 の中までは見る・その下は見ない
        self.assertTrue(r["truncated"])                      # 見なかった下のフォルダがあると知らせる

    def test_find_per_doc_limit(self):
        self.doc(self.T1, "C:\\x\\clip.mp4")
        for i in range(S.FIND_PER_DOC + 3):
            self.touch("d%d" % i, "clip.mp4")
        r = S.relink_find({"folder": self.media, "ids": [self.T1]})
        self.assertEqual(len(r["candidates"][self.T1]), S.FIND_PER_DOC)

    def test_find_folder_checks(self):
        for bad, code in ((os.path.join(self.media, "無い"), "no_dir"), ("相対\\フォルダ", "bad_path"), ("", "bad_path"),
                          (None, "bad_path"), ("a\nb", "bad_path")):
            with self.assertRaises(S.ApiError, msg=repr(bad)) as c:
                S.relink_find({"folder": bad, "ids": []})
            self.assertEqual((c.exception.code, c.exception.status), (code, 400), repr(bad))
        # 作業データの中は断る(フォルダ自体も、その下も)
        S.DATA_DIR = self.media
        for inside in (self.media, os.path.join(self.media, "sub")):
            os.makedirs(inside, exist_ok=True)
            with self.assertRaises(S.ApiError, msg=inside) as c:
                S.relink_folder(inside)
            self.assertEqual((c.exception.code, c.exception.status), ("bad_path", 400))

    @unittest.skipUnless(os.name == "nt", "Windows のネットワークパス")
    def test_find_folder_refuses_network_path(self):
        with self.assertRaises(S.ApiError) as c:
            S.relink_folder("\\\\server\\share\\動画")
        self.assertEqual((c.exception.code, c.exception.status), ("network_path", 400))

    def test_pick_path_maps_errors_and_kind(self):
        from ytt import pick as _pick
        saved = _pick.pick
        calls = []

        def fake(kind, title, hint, exts):
            calls.append((kind, hint, exts))
            return fake.result

        _pick.pick = fake
        try:
            fake.result = os.path.join(self.media, "x.mp4")
            self.assertEqual(S.pick_path({"kind": "dir", "hint": "D:\\動画"}), {"path": fake.result})
            self.assertEqual(S.pick_path({"kind": "なんでも"})["path"], fake.result)   # dir 以外は file
            self.assertEqual([c[0] for c in calls], ["dir", "file"])
            self.assertEqual(calls[0][1], "D:\\動画")
            self.assertIs(calls[0][2], S.MEDIA_TYPES)
            fake.result = ""                                                         # やめたら "" のまま返す
            self.assertEqual(S.pick_path({"kind": "file"}), {"path": ""})
            for exc, status, code in ((_pick.PickBusy("開いている"), 409, "pick_busy"), (_pick.PickError("tk なし"), 400, "pick_unavailable")):
                def boom(*a, _e=exc):
                    raise _e
                _pick.pick = boom
                with self.assertRaises(S.ApiError) as c:
                    S.pick_path({"kind": "file"})
                self.assertEqual((c.exception.status, c.exception.code), (status, code))
        finally:
            _pick.pick = saved


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg が必要")
class TestRelinkHttp(unittest.TestCase):
    """POST /api/relink/check・/api/relink を本物の動画で(疑似モードのサーバー)。動画はサーバーの作業データの外の一時フォルダに置く。
    付け替えのあとの 30fps の作り直し(Q1)は test_normalize30.py で確かめるので、ここでは "normalize": False で止める(裏のジョブで付け替え直されて、確かめる途中で動画が変わらないように)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.media_dir = tempfile.mkdtemp()   # サーバーの作業データ(YTT_DATA_DIR=inplace = 写したフォルダ)の外
        ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        cls.v6 = os.path.join(cls.media_dir, "元の動画.mkv")
        subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                             "-c:v", "mpeg4", "-c:a", "pcm_s16le", "-shortest", cls.v6], check=True)
        cls.v3 = os.path.join(cls.media_dir, "短い動画.mkv")
        subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:duration=3", "-c:v", "mpeg4", cls.v3], check=True)
        cls.wav = os.path.join(cls.media_dir, "声.wav")
        subprocess.run(ff + ["-f", "lavfi", "-i", "sine=frequency=300:duration=6", cls.wav], check=True)
        cls.runtime = os.path.join(cls.tmp, ".runtime")
        cls.port = free_port()
        cls.proc = start_server(cls.tmp, cls.port, cls.runtime)
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.media_dir, ignore_errors=True)

    call = TestEditHttp.call

    def make_doc(self, name):
        src = os.path.join(self.media_dir, name)
        shutil.copy(self.v6, src)
        tid = self.call("POST", "/api/open-video", {"path": src})["id"]
        d = self.call("GET", "/api/transcript?id=" + tid)
        d["segments"] = [{"id": "s1", "start": 0.5, "end": 2.0, "text": "こんばんは", "proofed": True},
                         {"id": "s2", "start": 3.0, "end": 5.5, "text": "待って"}]
        r = self.call("PUT", "/api/transcript?id=" + tid, {"segments": d["segments"], "speakers": [], "baseUpdatedAt": d["updatedAt"]})
        self.assertEqual(r["_status"], 200, r)
        return tid, src

    def test_check_and_relink(self):
        tid, src = self.make_doc("移す前.mkv")
        moved = os.path.join(self.media_dir, "移した先.mkv")
        os.replace(src, moved)
        self.assertTrue(self.call("GET", "/api/edit/draft?id=" + tid)["unavailable"]["code"] == "source_missing")
        c = self.call("POST", "/api/relink/check", {"id": tid, "path": '"%s"' % moved})
        self.assertEqual(c["_status"], 200, c)
        self.assertEqual((c["name"], c["fps"], c["hasVideo"], c["mismatch"], c["sameAsNow"], c["rowsAfterEnd"]), ("移した先.mkv", [30, 1], True, False, False, 0))
        self.assertAlmostEqual(c["durationSec"], 6.0, delta=0.1)
        self.assertLess(abs(c["diffSec"]), 0.2)
        other = self.call("POST", "/api/open-video", {"path": self.v6})["id"]   # 同じ動画を使う別の文書は知らせる
        shutil.copy(self.v6, os.path.join(self.media_dir, "x.mkv"))
        c2 = self.call("POST", "/api/relink/check", {"id": tid, "path": self.v6})
        self.assertEqual([u["id"] for u in c2["usedBy"]], [other])
        # カットを保存してパックを作った → 付け替えると「作り直し」
        self.assertEqual(self.call("PUT", "/api/edit?id=" + tid, {"baseRev": 0, "edit": edit_obj(clips=((0.3, 2.2), (2.8, 5.8)), duration=6.0)})["rev"], 1)
        d = self.call("GET", "/api/transcript?id=" + tid)
        self.call("POST", "/api/edit/pack", {"id": tid, "rev": 1, "docUpdatedAt": d["updatedAt"], "dir": os.path.join(self.media_dir, "p_pack")})
        self.assertFalse(self.call("GET", "/api/edit?id=" + tid)["packStale"])
        r = self.call("POST", "/api/relink", {"id": tid, "path": moved, "baseUpdatedAt": d["updatedAt"], "normalize": False})
        self.assertEqual(r["_status"], 200, r)
        d2 = self.call("GET", "/api/transcript?id=" + tid)
        self.assertEqual((os.path.normcase(d2["sourcePath"]), d2["sourceName"]), (os.path.normcase(os.path.realpath(moved)), "移した先.mkv"))
        self.assertEqual(d2["segments"], d["segments"])
        self.assertTrue(self.call("GET", "/api/edit?id=" + tid)["packStale"])
        self.assertEqual(self.call("GET", "/api/edit?id=" + tid)["edit"]["clips"], [{"src": 0, "in": 0.3, "out": 2.2}, {"src": 0, "in": 2.8, "out": 5.8}])
        self.assertIn("fps", self.call("GET", "/api/edit/draft?id=" + tid))       # カットのタブが使える
        st, _hd, _b = self.call("GET", "/media?id=" + tid, raw=True)
        self.assertEqual(st, 200)
        again = self.call("POST", "/api/relink", {"id": tid, "path": moved, "baseUpdatedAt": d2["updatedAt"], "normalize": False})
        self.assertEqual((again["_status"], again["error"]), (400, "same_path"))
        old = self.call("POST", "/api/relink", {"id": tid, "path": self.v6, "baseUpdatedAt": d["updatedAt"], "normalize": False})   # 古い updatedAt
        self.assertEqual((old["_status"], old["error"]), (409, "conflict"))
        # 履歴から元のパスへ戻せる
        items = self.call("GET", "/api/history?id=" + tid)["items"]
        self.assertTrue(items)
        self.assertEqual(self.call("POST", "/api/restore", {"id": tid, "ts": items[0]["ts"]})["_status"], 200)
        self.assertEqual(os.path.normcase(self.call("GET", "/api/transcript?id=" + tid)["sourcePath"]), os.path.normcase(src))

    def test_duration_mismatch_needs_consent(self):
        tid, src = self.make_doc("長さ違い.mkv")
        os.remove(src)
        c = self.call("POST", "/api/relink/check", {"id": tid, "path": self.v3})
        self.assertEqual((c["mismatch"], c["fps"], c["rowsAfterEnd"]), (True, [25, 1], 1))
        self.assertTrue(any("長さ" in w for w in c["warnings"]))
        d = self.call("GET", "/api/transcript?id=" + tid)
        r = self.call("POST", "/api/relink", {"id": tid, "path": self.v3, "baseUpdatedAt": d["updatedAt"], "normalize": False})
        self.assertEqual((r["_status"], r["error"]), (409, "duration_mismatch"))
        self.assertEqual(self.call("GET", "/api/transcript?id=" + tid)["sourcePath"], d["sourcePath"])
        r = self.call("POST", "/api/relink", {"id": tid, "path": self.v3, "baseUpdatedAt": d["updatedAt"], "acceptDiff": True, "normalize": False})
        self.assertEqual(r["_status"], 200, r)
        self.assertLess(self.call("GET", "/api/transcript?id=" + tid)["relinks"][-1]["diffSec"], -2)

    def test_eval_audio_api_is_gone(self):
        """評価用の音声(ed_evalaudio)は 0.68.0 で消した(作業データの eval-audio/ は残る)"""
        self.assertEqual(self.call("GET", "/api/eval-audio")["_status"], 404)

    def test_rejects(self):
        tid, src = self.make_doc("断る.mkv")
        inside = os.path.join(self.tmp, "作業データの中.mkv")   # サーバーの作業データ(inplace = 写したフォルダ)の中
        shutil.copy(self.v6, inside)
        txt = os.path.join(self.media_dir, "メモ.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write("x")
        bad_mp4 = os.path.join(self.media_dir, "壊れた.mp4")
        with open(bad_mp4, "wb") as f:
            f.write(os.urandom(2048))
        for path, code in ((inside, "bad_path"), (txt, "bad_ext"), (os.path.join(self.media_dir, "無い.mkv"), "no_file"),
                           ("\\\\127.0.0.1\\share\\a.mkv", "network_path"), (bad_mp4, "bad_media")):
            r = self.call("POST", "/api/relink/check", {"id": tid, "path": path})
            self.assertEqual((r["_status"], r["error"]), (400, code), path)
        r = self.call("POST", "/api/relink/check", {"id": "000000000000", "path": self.v6})
        self.assertEqual(r["_status"], 404)
        a = self.call("POST", "/api/relink/check", {"id": tid, "path": self.wav})   # 音声だけ: 付け替えられるが、カット・パックに使えないと知らせる
        self.assertEqual((a["_status"], a["hasVideo"], a["fps"]), (200, False, None))
        self.assertTrue(any("音声だけ" in w for w in a["warnings"]))


class TestEvalFolder(StoreDir):
    """評価用のフォルダ(2026-10-01): 中の動画は評価用で外せない・整理で「フォルダ名_番号_状態」にそろえて付け替える"""

    def setUp(self):
        super().setUp()
        self.ev = tempfile.mkdtemp()
        self.mem = os.path.join(self.ev, "1_JP", "01_0期生", "評価用データ01_ときのそら")
        os.makedirs(self.mem)
        write_json(S.SETTINGS, {"evalDirs": [self.ev]})

    def tearDown(self):
        shutil.rmtree(self.ev, ignore_errors=True)
        super().tearDown()

    def video(self, name, mtime):
        p = os.path.join(self.mem, name)
        with open(p, "wb") as f:
            f.write(b"x")
        os.utime(p, (mtime, mtime))
        return p

    def doc(self, tid=TID):
        with open(S.tx_path(tid), encoding="utf-8") as f:
            return json.load(f)

    def test_settings_check_and_inside(self):
        self.assertTrue(S._eval_dirs_ok([self.ev]))
        for bad in (["relative\\x"], ["\\\\server\\share"], "E:\\x", [self.ev] * 11, ["C:\\a:b"]):
            self.assertFalse(S._eval_dirs_ok(bad), bad)
        self.assertEqual(S.eval_dirs(), [os.path.abspath(self.ev)])
        self.assertTrue(S.in_eval_dir(os.path.join(self.mem, "a.mp4")))
        self.assertFalse(S.in_eval_dir(self.ev + "x\\a.mp4"))   # 名前が前で一致するだけの隣のフォルダは外
        self.assertFalse(S.in_eval_dir("\\\\server\\share\\a.mp4"))
        write_json(S.SETTINGS, {"evalDirs": [os.path.join(self.ev, "無いフォルダ")]})
        self.assertEqual(S.eval_dirs(), [])

    def test_glossary_from_settings_when_request_has_none(self):
        """要求に用語集の鍵が無ければ(② のまとめて実行。RS7-1 S4 で用語集は束の外 = 学習データ)保存した設定の用語集。鍵があれば(空でも)要求のまま"""
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        plain = os.path.join(other, "y.mp4")
        with open(plain, "wb") as f:
            f.write(b"x")
        write_json(S.SETTINGS, {"evalDirs": [self.ev], "glossary": "用語1\n用語2"})
        self.assertEqual(S.validate_job({"sourcePath": plain, "autoGloss": False})["glossary"], ["用語1", "用語2"])
        self.assertEqual(S.validate_job({"sourcePath": plain, "autoGloss": False, "glossary": ""})["glossary"], [])
        self.assertEqual(S.validate_job({"sourcePath": plain, "autoGloss": False, "glossary": "別"})["glossary"], ["別"])
        self.assertEqual(S.validate_job({"sourcePath": self.video("a.mp4", 1000), "autoGloss": False})["glossary"], [])   # 評価用は渡さない

    def test_job_save_restore_force_eval(self):
        p = self.video("a.mp4", 1000)
        spec = S.validate_job({"sourcePath": p, "glossary": "用語"})
        self.assertTrue(spec["evalSet"])
        self.assertEqual(spec["glossary"], [])   # 評価用は用語集を渡さない
        self.put_doc(doc_obj(sourcePath=p, evalSet=True))
        S.save_transcript(TID, {"title": "t", "evalSet": False, "segments": doc_obj()["segments"], "speakers": []})
        self.assertTrue(self.doc()["evalSet"])   # 画面から外そうとしても残る
        self.put_doc(doc_obj(sourcePath="C:\\x\\clip.mp4", evalSet=True))
        S.save_transcript(TID, {"title": "t", "evalSet": False, "segments": doc_obj()["segments"], "speakers": []})
        self.assertNotIn("evalSet", self.doc())   # フォルダの外は今までどおり外せる

    def test_unset_eval_dirs_stops_eval_named_folder(self):
        """評価用のフォルダの設定が消えている(空)のに、フォルダ名に「評価用」を含む動画を文字起こし・付け替えしようとしたら止める(master-plan Q0)"""
        other = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        folder = os.path.join(other, "評価用データ", "評価用_仮置き")
        os.makedirs(folder)
        p = os.path.join(folder, "x.mp4")
        with open(p, "wb") as f:
            f.write(b"x")
        plain = os.path.join(other, "切り抜き", "y.mp4")
        os.makedirs(os.path.dirname(plain))
        with open(plain, "wb") as f:
            f.write(b"x")
        self.put_doc(doc_obj(sourcePath=plain))
        for unset in ({}, {"evalDirs": []}, {"evalDirs": "壊れた"}):
            write_json(S.SETTINGS, unset)
            with self.assertRaises(S.ApiError) as cm:
                S.validate_job({"sourcePath": p})
            self.assertEqual((cm.exception.code, cm.exception.status), ("eval_dir_unset", 400))
            self.assertIn("評価用のフォルダ", cm.exception.message)
            with self.assertRaises(S.ApiError) as cm:
                S.relink_check({"id": TID, "path": p})
            self.assertEqual(cm.exception.code, "eval_dir_unset")
            self.assertIn("付け替え", cm.exception.message)
            self.assertEqual(S.validate_job({"sourcePath": plain})["evalSet"], False)   # 名前に「評価用」が無い動画は今までどおり
            self.assertTrue(S.validate_job({"sourcePath": p, "evalSet": True})["evalSet"])   # 評価用として始めるなら学習用に混ざらないので通す
        # 設定があれば今までどおり(そのフォルダの外でも、名前だけでは止めない)
        write_json(S.SETTINGS, {"evalDirs": [os.path.join(other, "評価用データ")]})
        self.assertTrue(S.validate_job({"sourcePath": p})["evalSet"])
        write_json(S.SETTINGS, {"evalDirs": [self.ev]})
        self.assertFalse(S.validate_job({"sourcePath": p})["evalSet"])
        # すでに評価用の文書の付け替えは止めない(評価用のまま動かすだけ)
        write_json(S.SETTINGS, {})
        self.put_doc(doc_obj(sourcePath=plain, evalSet=True))
        try:
            S.relink_check({"id": TID, "path": p})
        except S.ApiError as e:
            self.assertNotEqual(e.code, "eval_dir_unset")

    def test_organize_names_numbers_and_relinks(self):
        old = self.video("配信の切り抜き.mp4", 2000)
        self.video("評価用データ01_ときのそら_01_未.mp4", 3000)   # 番号が付いているものは番号をそのまま
        newer = self.video("あとから.mp4", 4000)
        work = os.path.join(self.mem, "作業用")
        os.makedirs(work)
        with open(os.path.join(work, "配信の切り抜き.clip.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        segs = [dict(s, proofed=True) for s in doc_obj()["segments"]]
        self.put_doc(doc_obj(sourcePath=old, segments=segs))   # 全行が校正済み・印なし
        r = S.eval_organize("test")
        names = sorted(os.listdir(self.mem))
        self.assertEqual(names, ["作業用", "評価用データ01_ときのそら_01_未文字起こし.mp4", "評価用データ01_ときのそら_02_済.mp4",
                                 "評価用データ01_ときのそら_03_未文字起こし.mp4"])
        self.assertEqual(os.listdir(work), ["評価用データ01_ときのそら_02_済.clip.json"])
        d = self.doc()
        self.assertEqual(d["sourcePath"], os.path.join(self.mem, "評価用データ01_ときのそら_02_済.mp4"))
        self.assertTrue(d["evalSet"])
        self.assertEqual(d["relinks"][-1]["why"], "evalOrganize")
        self.assertEqual((r["videos"], len(r["renamed"]), r["marked"], r["skipped"]), (3, 3, 1, []))
        self.assertFalse(os.path.exists(newer))
        # 1行の校正を外すと「未」に・2回目は名前が同じなら何もしない
        d["segments"][0]["proofed"] = False
        self.put_doc(d)
        r = S.eval_organize("test")
        self.assertEqual(len(r["renamed"]), 1)
        self.assertTrue(self.doc()["sourcePath"].endswith("_02_未.mp4"))
        self.assertEqual(S.eval_organize("test")["renamed"], [])

    def test_organize_skips_busy_and_name_clash(self):
        p = self.video("a.mp4", 1000)
        with S._jobs_lock:
            S._jobs["evaltest1"] = {"id": "evaltest1", "state": "running", "kind": "transcribe", "spec": {"sourcePath": p}}
        try:
            r = S.eval_organize("test")
        finally:
            with S._jobs_lock:
                S._jobs.pop("evaltest1")
        self.assertEqual(len(r["skipped"]), 1)
        self.assertTrue(os.path.exists(p))

    def test_organize_rolls_back_when_relink_fails(self):
        p = self.video("a.mp4", 1000)
        self.put_doc(doc_obj(sourcePath=p, evalSet=True))
        saved = S._relink_write

        def boom(*a, **k):
            raise OSError("disk")
        S._relink_write = boom
        try:
            r = S.eval_organize("test")
        finally:
            S._relink_write = saved
        self.assertEqual(len(r["skipped"]), 1)
        self.assertTrue(os.path.exists(p))   # 名前は元に戻る
        self.assertEqual(self.doc()["sourcePath"], p)

    def test_no_dirs_does_nothing(self):
        write_json(S.SETTINGS, {})
        self.assertEqual(S.eval_organize("test")["dirs"], 0)

    def staged(self, name="仮の動画.mp4", proofed=True, speakers=True, names=("ときのそら", "さくらみこ")):
        stg = os.path.join(self.ev, S.EVAL_STAGING)
        os.makedirs(stg, exist_ok=True)
        p = os.path.join(stg, name)
        with open(p, "wb") as f:
            f.write(b"x")
        segs = doc_obj()["segments"]
        for i, g in enumerate(segs):
            g["proofed"] = proofed or i > 0
            if speakers:
                g["speaker"] = "A" if i != 1 else "B"   # A = 3 行(長い)・B = 1 行
        self.put_doc(doc_obj(sourcePath=p, segments=segs, speakers=[{"id": "A", "name": names[0]}, {"id": "B", "name": names[1]}]))
        return p

    def test_staging_moves_when_ready(self):
        self.video("評価用データ01_ときのそら_01_未.mp4", 1000)
        os.makedirs(os.path.join(self.ev, "1_JP", "01_0期生", "評価用データ03_さくらみこ"))
        p = self.staged()
        os.makedirs(os.path.join(os.path.dirname(p), "作業用"))
        with open(os.path.join(os.path.dirname(p), "作業用", "仮の動画.clip.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        r = S.eval_organize("test")
        dst = os.path.join(self.mem, "評価用データ01_ときのそら_02_済.mp4")
        self.assertEqual([(m["to"], m["member"]) for m in r["moved"]], [(dst, "ときのそら")])   # 長く話した人のフォルダ・空いている番号・済
        self.assertTrue(os.path.isfile(dst) and not os.path.exists(p))
        self.assertTrue(os.path.isfile(os.path.join(self.mem, "作業用", "評価用データ01_ときのそら_02_済.clip.json")))
        d = self.doc()
        self.assertEqual((d["sourcePath"], d["evalSet"], d["relinks"][-1]["why"]), (dst, True, "evalSettle"))
        self.assertEqual([os.path.basename(x["to"]) for x in r["renamed"]], ["評価用データ01_ときのそら_01_未文字起こし.mp4"])   # 移したものは数え直して名前のまま

    def test_staging_stays_until_ready(self):
        for kw, why in (({"proofed": False}, "校正していない行"), ({"speakers": False}, "話者が付いていない行"),
                        ({"names": ("話者1", "ゲスト")}, "移す先が決まりません")):
            p = self.staged(**kw)
            r = S.eval_organize("test")
            self.assertEqual(r["moved"], [])
            self.assertIn(why, r["staged"][0]["reason"])
            self.assertTrue(os.path.isfile(p))   # 仮置きの中は名前も変えない
            self.assertEqual(r["renamed"], [])

    def test_staging_copy_adopts_the_original_doc(self):
        """2026-10-02: 仮置きに置いたコピー(文書なし)は、同じ名前・同じ大きさの動画を指す文書が1つだけなら、その文書を付け替えてから移す"""
        orig_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, orig_dir, True)
        stg = os.path.join(self.ev, S.EVAL_STAGING)
        os.makedirs(stg)

        def put(folder, name, data):
            p = os.path.join(folder, name)
            with open(p, "wb") as f:
                f.write(data)
            return p
        orig = put(orig_dir, "clip.mp4", b"same-bytes")
        copy = put(stg, "clip.mp4", b"same-bytes")
        segs = [dict(g, proofed=True, speaker="A") for g in doc_obj()["segments"]]
        self.put_doc(doc_obj(sourcePath=orig, segments=segs, speakers=[{"id": "A", "name": "ときのそら"}]))
        put(stg, "other.mp4", b"different")                       # 大きさが違う → 付け替えない
        put(orig_dir, "other.mp4", b"other-size!!")
        self.put_doc(doc_obj(sourcePath=os.path.join(orig_dir, "other.mp4"), segments=segs, speakers=[{"id": "A", "name": "ときのそら"}]), tid="bbbbbbbbbbbb")
        r = S.eval_organize("test")
        self.assertEqual([a["id"] for a in r["adopted"]], [TID])
        d = self.doc()
        self.assertEqual((d["sourcePath"], d["evalSet"]), (os.path.join(self.mem, "評価用データ01_ときのそら_01_済.mp4"), True))
        self.assertEqual([x["why"] for x in d["relinks"]][-2:], ["evalStagingCopy", "evalSettle"])
        self.assertTrue(os.path.isfile(orig) and not os.path.exists(copy))   # 元の動画は残す(消さない)
        self.assertEqual([os.path.basename(s["path"]) for s in r["staged"]], ["other.mp4"])
        self.assertEqual(self.doc("bbbbbbbbbbbb")["sourcePath"], os.path.join(orig_dir, "other.mp4"))

    def test_staging_copy_with_two_candidates_is_left(self):
        dirs = [tempfile.mkdtemp(), tempfile.mkdtemp()]
        for d_ in dirs:
            self.addCleanup(shutil.rmtree, d_, True)
        stg = os.path.join(self.ev, S.EVAL_STAGING)
        os.makedirs(stg)
        for i, d_ in enumerate(dirs):
            with open(os.path.join(d_, "clip.mp4"), "wb") as f:
                f.write(b"x")
            self.put_doc(doc_obj(sourcePath=os.path.join(d_, "clip.mp4")), tid="%012d" % (i + 1))
        with open(os.path.join(stg, "clip.mp4"), "wb") as f:
            f.write(b"x")
        r = S.eval_organize("test")
        self.assertFalse(r.get("adopted"))
        self.assertIn("決められません", r["staged"][0]["reason"])

    def test_settle_one_doc(self):
        p = self.staged()
        self.assertEqual(S.eval_settle({"id": TID})["moved"]["member"], "ときのそら")
        self.assertFalse(os.path.exists(p))
        self.assertEqual(S.eval_settle({"id": TID}), {"moved": None, "reason": None})   # もう仮置きではない

    # ---- 2026-10-04: 評価用にした文書の動画を、評価用のフォルダの外から取り込む
    def outside(self, name="外の切り抜き.mp4", proofed=True, eval_set=True, tid=TID, names=("ときのそら", "さくらみこ")):
        src = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, src, True)
        p = os.path.join(src, name)
        with open(p, "wb") as f:
            f.write(b"video")
        os.makedirs(os.path.join(src, "作業用"))
        with open(os.path.join(src, "作業用", os.path.splitext(name)[0] + ".clip.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        segs = doc_obj()["segments"]
        for i, g in enumerate(segs):
            g["proofed"] = proofed or i > 0
            g["speaker"] = "A" if i != 1 else "B"
        kw = {"evalSet": True} if eval_set else {}
        self.put_doc(doc_obj(sourcePath=p, segments=segs, speakers=[{"id": "A", "name": names[0]}, {"id": "B", "name": names[1]}], **kw), tid)
        return p

    def test_intake_ready_goes_to_member_folder(self):
        p = self.outside()
        r = S.eval_organize("test")
        dst = os.path.join(self.mem, "評価用データ01_ときのそら_01_済.mp4")
        self.assertEqual([(x["from"], x["to"], x["member"], x["staged"]) for x in r["intaken"]], [(p, dst, "ときのそら", None)])
        self.assertTrue(os.path.isfile(dst) and not os.path.exists(p))
        self.assertTrue(os.path.isfile(os.path.join(self.mem, "作業用", "評価用データ01_ときのそら_01_済.clip.json")))
        d = self.doc()
        self.assertEqual((d["sourcePath"], d["evalSet"], d["relinks"][-1]["why"]), (dst, True, "evalIntake"))
        self.assertEqual(S.eval_organize("test")["intaken"], [])   # 2回目は何もしない

    def test_intake_not_ready_goes_to_staging(self):
        p = self.outside(proofed=False)
        stg = os.path.join(self.ev, S.EVAL_STAGING)
        os.makedirs(stg)
        with open(os.path.join(stg, "外の切り抜き.mp4"), "wb") as f:   # 同じ名前が仮置きにある → 「 (2)」
            f.write(b"other")
        r = S.eval_organize("test")
        dst = os.path.join(stg, "外の切り抜き (2).mp4")
        self.assertEqual([(x["to"], x["member"]) for x in r["intaken"]], [(dst, None)])
        self.assertIn("校正していない行", r["intaken"][0]["staged"])
        self.assertEqual(self.doc()["sourcePath"], dst)
        self.assertFalse(os.path.exists(p))

    def test_intake_skips_unmarked_and_shared(self):
        self.outside(eval_set=False)
        self.assertEqual(S.eval_organize("test")["intaken"], [])   # 評価用の印が無ければ動かさない
        p = self.outside()
        self.put_doc(doc_obj(sourcePath=p), "b" * len(TID))   # 同じ動画を、評価用でない文書も使っている
        r = S.eval_organize("test")
        self.assertEqual(r["intaken"], [])
        self.assertIn("評価用でない文書", r["skipped"][0]["reason"])
        self.assertTrue(os.path.isfile(p))

    def test_intake_across_drives_and_rollback(self):
        from unittest import mock
        from ytt import fsio   # 別のドライブへ移す move_file・same_drive の持ち主(RS3-1 に ed_relink の _move・_same_drive から)
        real = os.rename

        def no_rename_across(a, b):   # 別のドライブ: 名前の変更ができない(WinError 17)。.part → 本名 の同じフォルダの中だけ通す
            if os.path.dirname(a) != os.path.dirname(b):
                raise OSError(17, "別のドライブ")
            return real(a, b)
        p = self.outside()
        with mock.patch.object(fsio, "same_drive", lambda a, b: False), mock.patch.object(fsio.os, "rename", no_rename_across):
            r = S.eval_organize("test")
        dst = os.path.join(self.mem, "評価用データ01_ときのそら_01_済.mp4")
        self.assertEqual([x["to"] for x in r["intaken"]], [dst])
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"video")
        self.assertFalse(os.path.exists(p))
        self.assertTrue(os.path.isfile(os.path.join(self.mem, "作業用", "評価用データ01_ときのそら_01_済.clip.json")))
        self.assertEqual([f for f in os.listdir(self.mem) if f.endswith(".part")], [])
        # 元を消せない(開いている): コピーを消して元のまま・文書も元のまま
        p2 = self.outside(name="開いている.mp4", tid="c" * len(TID))
        real_remove = os.remove
        with mock.patch.object(fsio, "same_drive", lambda a, b: False), mock.patch.object(fsio.os, "rename", no_rename_across), \
                mock.patch.object(fsio.os, "remove", lambda x: (_ for _ in ()).throw(PermissionError(13, "使用中")) if x == p2 else real_remove(x)):
            r = S.eval_organize("test")
        self.assertEqual(r["intaken"], [])
        self.assertTrue(os.path.isfile(p2))
        self.assertFalse(any(f.startswith("評価用データ01_ときのそら_02") for f in os.listdir(self.mem)))
        self.assertEqual(self.doc("c" * len(TID))["sourcePath"], p2)

    def test_settle_intakes_in_background(self):
        p = self.outside()
        r = S.eval_settle({"id": TID})
        self.assertEqual(r, {"moved": None, "reason": None, "intake": True})
        for _ in range(100):
            if not S._evalorg_lock.locked():
                break
            time.sleep(0.05)
        self.assertFalse(os.path.exists(p))
        self.assertTrue(self.doc()["sourcePath"].endswith("_01_済.mp4"))


class TestToolIdentity(unittest.TestCase):
    """ツールの識別子(/api/ping の app・受け渡しの tool.name)は ytt.runtime.TOOL_APPS が正。写しが食い違っていない(値は互換のため固定)"""

    def test_same_as_runtime_table(self):
        from ytt import runtime
        import ed_state
        from manage.cases import pipeline_io
        self.assertEqual(runtime.TOOL_APPS["transcribe"], "transcribe-tool")
        self.assertEqual(S.APP_ID, runtime.TOOL_APPS["transcribe"])
        self.assertEqual(ed_state.APP_ID, runtime.TOOL_APPS["transcribe"])
        self.assertEqual(pipeline_io.TOOL_NAME, runtime.TOOL_APPS["transcribe"])


if __name__ == "__main__":
    unittest.main()
