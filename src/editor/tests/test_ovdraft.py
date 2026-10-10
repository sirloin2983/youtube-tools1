#!/usr/bin/env python3
"""重なりの所の空の行の下書き(ed_speakers の ovdraft_・GET /api/overlap-drafts・行の印 draft)のテスト。
計画 plan/line-b-overlap.md の 5-3 の C・6-2 の 1・2(2026-10-05)。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_ovdraft -q                # これだけ(src/editor/tests で)

- 候補 = 判別の声の区間のうち、主の話者でなく、(a) 行が 1 つも付かなかったラベル か (b) ほかの話者と重なるラベル で、書いてある所が半分未満のもの
- 置いた空の行(印 draft)は保存で残り、字幕・カット・パックの transcript/v1 には出ない。判別のやり直しでは話者を変えない
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from test_backend import S, P, RE, TID, StoreDir, free_port, start_server, write_json  # noqa: F401  (S = serve・P = pipeline_io)


def _row(i, a, b, text="x", speaker="", **kw):
    d = {"id": "s%d" % i, "start": a, "end": b, "text": text, "speaker": speaker, "flag": ""}
    d.update(kw)
    return d


def _draft(i, a, b, speaker=""):
    return _row(i, a, b, "", speaker, tags=["overlap"], draft="overlap")


def _latest(turns, label_map, engine="sherpa-onnx"):
    """build_diar_run と同じ形の _latest(turns は元の動画の秒・overlaps は _turn_overlaps で作る)"""
    ts = sorted(turns)
    return {"at": 123, "engine": {"name": engine}, "offset": 0.0,
            "turns": [{"start": a, "end": b, "label": s} for a, b, s in ts],
            "overlaps": S._turn_overlaps(ts), "labelMap": {str(k): v for k, v in label_map.items()}, "rows": {}}


def _doc(segs, speakers=(("S1", "こより"), ("S2", "ラミィ")), start=0.0, end=60.0, duration=60.0):
    return {"start": start, "end": end, "duration": duration, "speakers": [{"id": i, "name": n, "color": "#888"} for i, n in speakers], "segments": segs}


# 5ef03b5d17a9 の形をまねた例: ラベル 0 が主(こより)・ラベル 1 は行の付かなかった声・ラベル 2 がラミィ(S2)。主の行だけが書いてある
_TURNS_5EF = [(0.03, 20.97, 0), (8.6, 10.04, 1), (11.19, 12.03, 1), (22.27, 27.86, 0), (24.43, 24.65, 2), (27.54, 28.68, 2),
             (28.72, 45.37, 0), (33.26, 34.54, 2), (44.4, 45.22, 2), (48.09, 51.62, 0), (52.21, 56.78, 0), (55.38, 56.24, 1)]
_ROWS_5EF = [_row(1, 0.0, 20.9, "a", "S1"), _row(2, 22.3, 27.8, "b", "S1"), _row(3, 28.8, 45.3, "c", "S1"), _row(4, 48.1, 56.7, "d", "S1")]


def OV(doc, latest):
    """重なり(why overlap・unassigned)だけ。抜け(why missing)は TestOvdraftMissing で見る"""
    return S.ovdraft_candidates(doc, latest, ["overlap"])


def _spans(res):
    return [(x["start"], x["end"], x["speaker"], x["why"]) for x in res["items"]]


class TestOvdraftCandidates(unittest.TestCase):
    def test_5ef_shape(self):
        res = OV(_doc(_ROWS_5EF, end=56.77, duration=56.77), _latest(_TURNS_5EF, {0: "S1", 2: "S2"}))
        self.assertIsNone(res["reason"])
        self.assertEqual(_spans(res), [(8.6, 10.04, "", "unassigned"), (11.19, 12.03, "", "unassigned"), (27.54, 28.68, "S2", "overlap"),
                                      (33.26, 34.54, "S2", "overlap"), (44.4, 45.22, "S2", "overlap"), (55.38, 56.24, "", "unassigned")])
        self.assertEqual([x["label"] for x in res["items"]], [1, 1, 2, 2, 2, 1])
        self.assertEqual(res["more"], 0)

    def test_main_speaker_is_never_a_candidate(self):
        """主の話者(区間の合計がいちばん長いラベル)の区間は、行が無くても出さない(ほかの声が乗っているだけの側)"""
        res = OV(_doc([]), _latest([(0, 30, 0), (5, 7, 1)], {0: "S1"}))
        self.assertEqual(_spans(res), [(5, 7, "", "unassigned")])

    def test_join_and_min(self):
        # 同じラベルの 0.3 秒以下のすき間はつなぐ(0.3 秒と 0.2 秒の区間 → 0.9 秒)・0.5 秒未満は出さない
        res = OV(_doc([]), _latest([(0, 30, 0), (8.6, 8.9, 1), (9.1, 9.5, 1), (20, 20.4, 1), (25, 25.3, 1), (25.7, 26.1, 1)], {0: "S1"}))
        self.assertEqual(_spans(res), [(8.6, 9.5, "", "unassigned")])

    def test_assigned_label_needs_overlap(self):
        """(b) は、ほかの話者の区間と重なる声だけ(重ならない所の抜けは出さない)"""
        res = OV(_doc([_row(1, 0, 30, "a", "S1")]), _latest([(0, 30, 0), (40, 45, 2), (29, 32, 2)], {0: "S1", 2: "S2"}))
        self.assertEqual(_spans(res), [(29, 32, "S2", "overlap")])

    def test_covered_by_same_speaker(self):
        """その話者の行が半分以上を覆っていれば出さない。ほかの話者の行は覆いに数えない。端の覆いは削る(同じ話者の行と重ねない)"""
        t, m = [(0, 30, 0), (10, 14, 2)], {0: "S1", 2: "S2"}
        main = _row(1, 0, 30, "a", "S1")
        self.assertEqual(_spans(OV(_doc([main, _row(2, 9, 12.5, "b", "S2")]), _latest(t, m))), [])                 # 2.5/4 秒
        self.assertEqual(_spans(OV(_doc([main, _row(2, 9, 11.5, "b", "S2")]), _latest(t, m))), [(11.5, 14, "S2", "overlap")])   # 1.5/4 秒 → 頭を削る
        self.assertEqual(_spans(OV(_doc([main, _row(2, 13, 15, "b", "S2")]), _latest(t, m))), [(10, 13, "S2", "overlap")])     # 尻を削る
        self.assertEqual(_spans(OV(_doc([main, _row(2, 9, 15, "b", "S1")]), _latest(t, m))), [(10, 14, "S2", "overlap")])     # 主の行は覆いにならない

    def test_unassigned_covered_by_unknown_or_kept_rows(self):
        """(a) の覆い = 話者の無い行・守る行(声が重なるのメモつきの話者のある行)・字幕に出さない行・ゲーム音声などの行"""
        t, m = [(0, 30, 0), (10, 14, 1)], {0: "S1"}
        main = _row(1, 0, 30, "a", "S1")
        for g in (_row(2, 10, 14, "b", ""), _row(2, 10, 14, "b", "S2", tags=["overlap"]), _row(2, 10, 14, "b", "S1", noSub=True),
                  _row(2, 10, 14, "b", "other"), _row(2, 10, 14, "b", "S9")):   # S9 = 文書に無い話者(話者の無い行と同じ)
            self.assertEqual(_spans(OV(_doc([main, g]), _latest(t, m))), [], g)
        self.assertEqual(len(OV(_doc([main, _row(2, 10, 14, "b", "S2")]), _latest(t, m))["items"]), 1)   # 普通の話者の行は覆わない
        self.assertEqual(len(OV(_doc([main, _row(2, 10, 14, "", "")]), _latest(t, m))["items"]), 1)      # 文字の無い(下書きでない)行も覆わない

    def test_placing_drafts_twice_adds_nothing(self):
        """置いた空の下書き(話者によらず)が覆う → 2 回押しても増えない。打って印が外れた行も、同じ話者なら覆う"""
        d0, lt = _doc(list(_ROWS_5EF), end=56.77, duration=56.77), _latest(_TURNS_5EF, {0: "S1", 2: "S2"})
        first = OV(d0, lt)["items"]
        d1 = dict(d0, segments=d0["segments"] + [_draft(100 + k, x["start"], x["end"], x["speaker"]) for k, x in enumerate(first)])
        self.assertEqual(OV(d1, lt)["items"], [])
        typed = [{k: v for k, v in dict(g, text="打った").items() if k != "draft"} if g.get("draft") else g for g in d1["segments"]]
        self.assertEqual(OV(dict(d0, segments=typed), lt)["items"], [])

    def test_doc_range_and_duration(self):
        lt = _latest([(0, 100, 0), (5, 8, 1), (48, 52, 1), (70, 75, 1)], {0: "S1"})
        self.assertEqual(_spans(OV(_doc([], start=6.0, end=50.0, duration=100.0), lt)), [(6.0, 8, "", "unassigned"), (48, 50.0, "", "unassigned")])
        self.assertEqual(_spans(OV(_doc([], start=0, end=None, duration=49.8), lt)), [(5, 8, "", "unassigned"), (48, 49.8, "", "unassigned")])   # 長さで切る
        self.assertEqual(len(OV(_doc([], start=0, end=None, duration=48.3), lt)["items"]), 1)                     # 48〜48.3 は短い・70〜75 は長さの外

    def test_max_and_order(self):
        turns = [(0, 400, 0)] + [(5 + 8 * k, 6 + 8 * k, 1) for k in reversed(range(45))]
        res = OV(_doc([], end=400, duration=400), _latest(turns, {0: "S1"}))
        self.assertEqual((len(res["items"]), res["more"]), (S.OVDRAFT_MAX, 5))
        self.assertEqual([x["start"] for x in res["items"]], sorted(x["start"] for x in res["items"]))
        self.assertEqual(res["items"][0]["start"], 5)

    def test_speaker_missing_from_doc(self):
        """判別のあとで話者を消した: 時刻は出すが話者は空(人が選ぶ)"""
        res = OV(_doc([_row(1, 0, 30, "a", "S1")], speakers=(("S1", "こより"),)), _latest([(0, 30, 0), (10, 14, 2)], {0: "S1", 2: "S2"}))
        self.assertEqual(_spans(res), [(10, 14, "", "overlap")])

    def test_reasons(self):
        self.assertEqual(OV(_doc([]), None)["reasonCode"], "no_diar")
        self.assertEqual(OV(_doc([]), _latest([], {0: "S1"}, engine="single"))["reasonCode"], "single")
        res = OV(_doc([]), _latest([], {}))
        self.assertEqual((res["reasonCode"], res["items"], res["more"]), ("no_turns", [], 0))
        self.assertTrue(res["reason"])
        self.assertIsNone(OV(_doc([]), _latest([(0, 5, 0)], {0: "S1"}))["reason"])   # 記録はある・候補 0 は理由なし


class TestOvdraftRows(StoreDir):
    """置いた行の印 draft の保存・判別のやり直し・作り直しの判定・字幕に出ないこと"""

    def setUp(self):
        super().setUp()
        self.saved_vdir = S.VOICES_DIR
        S.VOICES_DIR = os.path.join(self.tmp, "voices")

    def tearDown(self):
        S.VOICES_DIR = self.saved_vdir
        super().tearDown()

    def test_sanitize_keeps_known_draft_only(self):
        out = S.sanitize_transcript({"speakers": [{"id": "S1", "name": "a"}], "segments": [
            _draft(1, 0, 1, "S1"), dict(_draft(2, 1, 2), draft="x"), dict(_draft(3, 2, 3), draft=True), dict(_draft(4, 3, 4), text="打った")]}, {"segments": []})
        self.assertEqual([g.get("draft") for g in out["segments"]], ["overlap", None, None, "overlap"])   # 文字の入った行の印は画面が外す(サーバーは形だけ見る)
        self.assertEqual(out["segments"][0]["tags"], ["overlap"])
        self.assertTrue(S.blank_draft_row(out["segments"][0]))
        self.assertFalse(S.blank_draft_row(out["segments"][3]))

    def test_blank_draft_not_in_subtitles_or_cut(self):
        d = _doc([_row(1, 0, 5, "a", "S1"), _draft(2, 2, 4, "S2")])
        d.update({"sourcePath": "C:\\x\\clip.mp4", "title": "t"})
        v1 = RE.build_transcript_v1(d, "x")
        self.assertEqual([g["id"] for g in v1["segments"]], ["s1"])   # パック・cut2resolve へ渡す形に入らない
        from pipeline.pack import resolve_export
        self.assertFalse(resolve_export.is_kept(_draft(2, 2, 4)))       # カットの「残す」・cut-plan に数えない

    def test_diar_keep_row_keeps_blank_draft(self):
        ids = {"S1", "S2"}
        self.assertTrue(S.diar_keep_row(_draft(1, 0, 1, ""), ids))
        self.assertTrue(S.diar_keep_row(_draft(1, 0, 1, "S2"), ids))
        self.assertFalse(S.diar_keep_row(_row(1, 0, 1, "打った", "", draft="overlap"), ids))   # 文字のある話者なしの行は今までどおり判別で付く

    def test_rediarize_leaves_blank_drafts(self):
        """判別のやり直しは行を作り直さないので、空の下書きはそのまま残し、話者も変えない(話者なしの下書きを主の話者で埋めない)"""
        d = _doc([_row(1, 0, 25, "a", "S1"), _draft(2, 8, 10, ""), _row(3, 25, 50, "b", "S2"), _draft(4, 30, 32, "S2")])
        d.update({"sourcePath": "C:\\x\\clip.mp4", "title": "t", "createdAt": 1, "updatedAt": 1})
        self.put_doc(d)
        S.apply_diarization(TID, [(0, 25, 0), (25, 50, 1)], 0.0, 2)
        with open(S.tx_path(TID), encoding="utf-8") as f:
            out = json.load(f)
        g = {x["id"]: x for x in out["segments"]}
        names = {s["id"]: s["name"] for s in out["speakers"]}
        self.assertEqual((g["s2"]["speaker"], g["s2"]["draft"], g["s2"]["text"]), ("", "overlap", ""))
        self.assertEqual(names[g["s4"]["speaker"]], "ラミィ")   # 守った話者(id は新しい判別と重ならないように付け替えることがある)
        self.assertEqual(g["s4"]["draft"], "overlap")
        self.assertNotIn("要確認", g["s2"].get("flag", ""))

    def test_eval_redo_treats_draft_as_touched(self):
        segs = [_row(1, 0.0, 2.0, "a"), _row(2, 2.0, 4.0, "b")]
        d = {"evalSet": True, "model": "small", "segments": [dict(g) for g in segs], "original": [dict(g) for g in segs], "updatedAt": 1, "speakers": []}
        self.assertIsNone(S.eb_redo_why(TID, d, now=10 ** 13, media=False))   # 前提: 手つかず
        d["segments"].append(_draft(3, 1.0, 2.0))
        self.assertIn(S.eb_redo_why(TID, d, now=10 ** 13, media=False), S.EB_REDO_TOUCHED)   # 人が手を入れた側(音のメモ overlap・行の数)

    def test_for_doc_reads_saved_doc_and_diar(self):
        self.put_doc(dict(_doc(list(_ROWS_5EF)), id=TID))
        with self.assertRaises(S.ApiError) as cm:
            S.ovdraft_for_doc("fedcba987654")
        self.assertEqual(cm.exception.status, 404)
        r = S.ovdraft_for_doc(TID)
        self.assertEqual((r["reasonCode"], r["diarAt"]), ("no_diar", None))
        write_json(S.diar_path(TID), {"schema": S.DIAR_SCHEMA, "latest": _latest(_TURNS_5EF, {0: "S1", 2: "S2"}), "history": []})
        before = os.path.getmtime(S.tx_path(TID)), os.path.getmtime(S.diar_path(TID))
        r = S.ovdraft_for_doc(TID)
        self.assertEqual((len(r["items"]), r["diarAt"]), (6, 123))
        self.assertEqual(before, (os.path.getmtime(S.tx_path(TID)), os.path.getmtime(S.diar_path(TID))))   # 読むだけ


class TestOvdraftHttp(unittest.TestCase):
    """GET /api/overlap-drafts?id=(serve.py の振り分け。ほかの GET と同じ Host/Origin の検査の下)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.port = free_port()
        cls.proc = start_server(cls.tmp, cls.port, os.path.join(cls.tmp, ".runtime"))
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), headers=headers or {})
        try:
            with self.opener.open(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_get(self):
        txdir = os.path.join(self.tmp, "transcripts")
        os.makedirs(txdir, exist_ok=True)
        write_json(os.path.join(txdir, TID + ".json"), dict(_doc(list(_ROWS_5EF), end=56.77, duration=56.77), id=TID, title="t", createdAt=1, updatedAt=1))
        st, body = self.get("/api/overlap-drafts?id=" + TID)
        self.assertEqual((st, body["reasonCode"], body["items"]), (200, "no_diar", []))
        write_json(os.path.join(txdir, TID + ".diar.json"), {"schema": "youtube-tools-diar/v1", "latest": _latest(_TURNS_5EF, {0: "S1", 2: "S2"}), "history": []})
        st, body = self.get("/api/overlap-drafts?id=" + TID)
        self.assertEqual((st, len(body["items"]), body["more"], body["reason"], body["diarAt"]), (200, 6, 0, None, 123))
        self.assertEqual(body["counts"], {"overlap": 6, "missing": 0})
        st, body = self.get("/api/overlap-drafts?id=" + TID + "&kinds=missing")   # 選んだまとまりだけ(数は全部)
        self.assertEqual((st, body["items"], body["counts"]["overlap"]), (200, [], 6))
        self.assertEqual(self.get("/api/overlap-drafts?id=fedcba987654")[0], 404)
        self.assertEqual(self.get("/api/overlap-drafts?id=" + TID, {"Sec-Fetch-Site": "cross-site"})[0], 403)   # 別のサイトからの読み取りは断る


def _miss(i, a, b, speaker=""):
    return _row(i, a, b, "", speaker, draft="missing")


def _mspans(res):
    return [(x["start"], x["end"], x["speaker"]) for x in res["items"] if x["why"] == "missing"]


class TestOvdraftMissing(unittest.TestCase):
    """抜け(why missing): 主の話者も含めて、声の区間から書いてある所を引いた残りの切れ端(OVDRAFT_MISS_MIN 以上)"""

    def test_gap_between_rows_of_main_speaker(self):
        """1 人の話の途中で認識が落とした所(区間の中のすき間)も拾う。両端の書いてある所は削る"""
        res = S.ovdraft_candidates(_doc([_row(1, 0, 10, "a", "S1"), _row(2, 12, 30, "b", "S1")]), _latest([(0, 30, 0)], {0: "S1"}))
        self.assertEqual(_mspans(res), [(10.0, 12.0, "S1")])
        x = res["items"][0]
        self.assertEqual((x["why"], x["draft"], x["label"]), ("missing", S.OVDRAFT_MISS_KIND, 0))
        self.assertEqual(res["counts"], {"overlap": 0, "missing": 1})

    def test_cover_is_any_written_row(self):
        """覆い = 文字のある行(話者によらない)・空の下書き(どちらの種類も)・字幕に出さない行・ゲーム音声などの行。文字の無い普通の行は覆わない"""
        t, m = [(0, 30, 0)], {0: "S1"}
        base = [_row(1, 0, 10, "a", "S1"), _row(2, 12, 30, "b", "S1")]
        for g in (_row(3, 10, 12, "c", "S2"), _row(3, 10, 12, "c", ""), _draft(3, 10, 12), _miss(3, 10, 12, "S1"), _row(3, 10, 12, "", "", noSub=True),
                  _row(3, 10, 12, "", "other")):
            self.assertEqual(_mspans(S.ovdraft_candidates(_doc(base + [g]), _latest(t, m))), [], g)
        self.assertEqual(len(_mspans(S.ovdraft_candidates(_doc(base + [_row(3, 10, 12, "", "S1")]), _latest(t, m)))), 1)

    def test_min_length(self):
        t, m = [(0, 30, 0)], {0: "S1"}
        short = _doc([_row(1, 0, 10, "a", "S1"), _row(2, 10.7, 30, "b", "S1")])
        self.assertEqual(_mspans(S.ovdraft_candidates(short, _latest(t, m))), [])            # 0.7 秒 < 0.8
        ok = _doc([_row(1, 0, 10, "a", "S1"), _row(2, 10.9, 30, "b", "S1")])
        self.assertEqual(_mspans(S.ovdraft_candidates(ok, _latest(t, m))), [(10.0, 10.9, "S1")])
        self.assertEqual(S.OVDRAFT_MISS_MIN, 0.8)

    def test_not_twice_with_overlap_candidates(self):
        """重なりの候補(overlap・unassigned)と同じ所は抜けに出さない。重なりの候補の外にはみ出した主の声の切れ端だけが抜け"""
        res = S.ovdraft_candidates(_doc([_row(1, 0, 10, "a", "S1"), _row(2, 14, 30, "b", "S1")]), _latest([(0, 30, 0), (9.5, 12.5, 1)], {0: "S1"}))
        self.assertEqual([(x["start"], x["end"], x["why"]) for x in res["items"]], [(9.5, 12.5, "unassigned"), (12.5, 14.0, "missing")])
        res = S.ovdraft_candidates(_doc([_row(1, 0, 30, "a", "S1")]), _latest([(0, 30, 0), (29, 32, 2)], {0: "S1", 2: "S2"}))
        self.assertEqual([x["why"] for x in res["items"]], ["overlap"])   # (b) が 30〜32 も出す → 抜けにしない

    def test_labels_merge_and_speaker(self):
        """違うラベルの切れ端が重なればつなぐ(話者は長い方)。labelMap に無いラベルだけの所は話者が空"""
        rows = [_row(1, 0, 10, "a", "S1"), _row(2, 20, 30, "b", "S1"), _row(3, 30, 60, "c", "S2")]
        turns = [(0, 13, 0), (20, 30, 0), (11.5, 16, 2), (30, 60, 2), (40, 41, 1)]
        res = S.ovdraft_candidates(_doc(rows), _latest(turns, {0: "S1", 2: "S2"}))
        self.assertEqual(_mspans(res), [(10.0, 16.0, "S2")])   # 10〜13(S1 3 秒)と 11.5〜16(S2 4.5 秒)→ 1 つ・S2
        res = S.ovdraft_candidates(_doc([_row(1, 0, 10, "a", "S1")], end=30, duration=30), _latest([(0, 20, 0), (12, 14, 3)], {0: "S1"}))
        self.assertEqual([(x["start"], x["end"], x["speaker"], x["why"]) for x in res["items"]], [(10.0, 12.0, "S1", "missing"), (12.0, 14.0, "", "unassigned"), (14.0, 20.0, "S1", "missing")])

    def test_kinds_counts_and_max(self):
        rows = [_row(k, 10 * k, 10 * k + 7, "x", "S1") for k in range(50)]   # 7 秒の行・3 秒のすき間 × 50
        turns = [(0, 500, 0), (100, 101, 1), (200, 201.5, 1)]
        lt = _latest(turns, {0: "S1"})
        both = S.ovdraft_candidates(_doc(rows, end=500, duration=500), lt)
        self.assertEqual(both["counts"], {"overlap": 2, "missing": 50})   # (a) は主の話者の行と重なっていても出る(今までどおり)・上限の前の数
        self.assertEqual((len(both["items"]), both["more"]), (S.OVDRAFT_MAX, 52 - S.OVDRAFT_MAX))   # 上限は重なりと抜けを合わせて数える
        self.assertEqual([x["why"] for x in S.ovdraft_candidates(_doc(rows, end=500, duration=500), lt, ["overlap"])["items"]], ["unassigned"] * 2)
        self.assertEqual(len(S.ovdraft_candidates(_doc(rows, end=500, duration=500), lt, ["missing"])["items"]), S.OVDRAFT_MAX)
        self.assertEqual(S.ovdraft_candidates(_doc(rows, end=500, duration=500), lt, ["bogus"])["items"], [])
        self.assertEqual(S.ovdraft_candidates(_doc([]), None)["counts"], {"overlap": 0, "missing": 0})

    def test_placing_twice_adds_nothing(self):
        rows = [_row(1, 0, 10, "a", "S1"), _row(2, 12, 20, "b", "S1"), _row(3, 20, 30, "c", "S1")]
        lt = _latest([(0, 30, 0), (21, 24, 2)], {0: "S1", 2: "S2"})
        d0 = _doc(rows, end=30, duration=30)
        first = S.ovdraft_candidates(d0, lt)["items"]
        self.assertEqual([x["why"] for x in first], ["missing", "overlap"])
        placed = [(_miss if x["why"] == "missing" else _draft)(100 + k, x["start"], x["end"], x["speaker"]) for k, x in enumerate(first)]
        self.assertEqual(S.ovdraft_candidates(dict(d0, segments=rows + placed), lt)["items"], [])

    def test_kinds_query(self):
        d = _doc([_row(1, 0, 10, "a", "S1"), _row(2, 12, 30, "b", "S1")])
        lt = _latest([(0, 30, 0), (20, 23, 2)], {0: "S1", 2: "S2"})
        with mock.patch.object(S.ed_speakers.store, "read_transcript", return_value=d), mock.patch.object(S.ed_speakers, "read_diar", return_value={"latest": lt}):
            whys = lambda k: [x["why"] for x in S.ovdraft_for_doc(TID, k)["items"]]   # noqa: E731
            self.assertEqual(whys(None), ["missing", "overlap"])
            self.assertEqual(whys(""), ["missing", "overlap"])
            self.assertEqual(whys("missing"), ["missing"])
            self.assertEqual(whys("overlap,missing"), ["missing", "overlap"])
            self.assertEqual(whys("x,overlap"), ["overlap"])

    def test_missing_draft_row_rules(self):
        """印 missing も overlap と同じ決まり: 保存で残る・空のままは字幕に出ない・判別のやり直しで守る・精度に出ない"""
        self.assertIn("missing", S.ROW_DRAFT_KINDS)
        out = S.sanitize_transcript({"speakers": [{"id": "S1", "name": "a"}], "segments": [_miss(1, 0, 1, "S1")]}, {"segments": []})
        self.assertEqual(out["segments"][0].get("draft"), "missing")
        self.assertNotIn("overlap", out["segments"][0].get("tags") or [])
        self.assertTrue(S.blank_draft_row(out["segments"][0]))
        self.assertTrue(S.diar_keep_row(_miss(1, 0, 1, ""), {"S1"}))
        d = _doc([_row(1, 0, 5, "a", "S1"), _miss(2, 5, 7, "S1")])
        d.update({"sourcePath": "C:\\x\\clip.mp4", "title": "t"})
        self.assertEqual([g["id"] for g in RE.build_transcript_v1(d, "x")["segments"]], ["s1"])
        base = {"original": [_row(1, 0.0, 4.0, "こんにちは")], "segments": [_row(1, 0.0, 4.0, "こんにちわ", "S1", proofed=True)]}
        self.assertEqual(S.doc_metrics(dict(base, segments=base["segments"] + [_miss(2, 4.0, 5.0, "S1")])), S.doc_metrics(base))


class MetricsIgnoreBlankDraft(unittest.TestCase):
    def test_blank_draft_does_not_drop_proofed_group(self):
        """空のままの下書きが校正済みの行に重なっていても、精度の数え方は下書きの無い文書と同じ(文字を打った行は数える)"""
        orig = [_row(1, 0.0, 4.0, "こんにちは")]
        base = {"original": orig, "segments": [_row(1, 0.0, 4.0, "こんにちわ", "S1", proofed=True)]}
        with_draft = dict(base, segments=base["segments"] + [_draft(2, 1.0, 2.0, "S2")])
        self.assertIsNotNone(S.doc_metrics(base))
        self.assertEqual(S.doc_metrics(with_draft), S.doc_metrics(base))
        filled = dict(base, segments=base["segments"] + [_row(2, 1.0, 2.0, "うん", "S2", draft="overlap")])
        self.assertEqual(len(S._prep(filled)[1]), 2)


if __name__ == "__main__":
    unittest.main()
