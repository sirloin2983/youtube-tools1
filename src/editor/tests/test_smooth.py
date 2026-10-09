#!/usr/bin/env python3
"""話者の細切れをならす(S2。ed_speakers の smooth_labels・smooth_speakers・apply_diarization(smooth)・設定 diarSmooth)のテスト。2026-10-05。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_smooth -q                 # これだけ(src/editor/tests で)

- 短い 1 行だけ前後と違う話者で、根拠が弱い(自分のラベルの区間に入っている割合が低い)・前後とのすき間が小さい・重なりが無い → 前後の話者にする
- 判別の生の結果(turns・overlaps)は変えない。diar.json の rows に smoothed: true(label は元のラベル)。既定はオフ
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import unittest
import unittest.mock

from test_backend import S, TID, StoreDir  # noqa: F401  (S = serve)


def _r(a, b, label, ratio=0.3, skip=False):
    return {"start": a, "end": b, "label": label, "ratio": ratio, "skip": skip}


# 前後が 0(A)で、真ん中の短い 1 行だけ 1(B)・根拠が弱い(区間に 30% しか入っていない)
_BASE = [_r(0, 3, 0, 0.9), _r(3.2, 4.0, 1), _r(4.2, 7, 0, 0.9)]


class TestSmoothLabels(unittest.TestCase):
    def test_smooths_short_weak_island(self):
        self.assertEqual(S.smooth_labels(_BASE, []), {1: 0})

    def test_keeps_strong_evidence(self):
        """短くても、その人の声の区間にしっかり入っている行(本物の相づち・別の人)はならさない"""
        rows = [dict(r) for r in _BASE]
        rows[1]["ratio"] = 0.6
        self.assertEqual(S.smooth_labels(rows, []), {})
        rows[1]["ratio"] = 0.59
        self.assertEqual(S.smooth_labels(rows, []), {1: 0})

    def test_length_gap_overlap(self):
        long_ = [dict(r) for r in _BASE]
        long_[1].update(start=3.0, end=4.2)          # 1.2 秒(DIAR_SMOOTH_SHORT 以上)
        self.assertEqual(S.smooth_labels(long_, []), {})
        gap = [dict(r) for r in _BASE]
        gap[2].update(start=4.7)                     # 後ろのすき間 0.7 秒
        self.assertEqual(S.smooth_labels(gap, []), {})
        gap[2].update(start=4.6)                     # 0.6 秒はならす
        self.assertEqual(S.smooth_labels(gap, []), {1: 0})
        self.assertEqual(S.smooth_labels(_BASE, [(3.5, 3.6)]), {})   # 同時にしゃべっている(0.1 秒以上の重なり)
        self.assertEqual(S.smooth_labels(_BASE, [(3.5, 3.55)]), {1: 0})

    def test_neighbors_must_agree(self):
        rows = [dict(r) for r in _BASE]
        rows[2]["label"] = 2                         # 前後が違う人
        self.assertEqual(S.smooth_labels(rows, []), {})
        rows[2]["label"] = None                      # 後ろの話者が無い
        self.assertEqual(S.smooth_labels(rows, []), {})
        self.assertEqual(S.smooth_labels(_BASE[:2], []), {})   # 後ろの行が無い(最後の行)
        self.assertEqual(S.smooth_labels([_r(0, 0.8, 1)] + _BASE[2:], []), {})   # 最初の行

    def test_two_short_rows_in_a_row(self):
        """別の人の短い行が 2 行続くときはならさない(まず 1 行だけ)"""
        rows = [_r(0, 3, 0, 0.9), _r(3.1, 3.8, 1), _r(3.9, 4.6, 1), _r(4.7, 7, 0, 0.9)]
        self.assertEqual(S.smooth_labels(rows, []), {})

    def test_skip_rows(self):
        """守る行・文字の無い行は前後に数えない(あいだに挟まっても見えないものとして扱う)・それ自体もならさない"""
        rows = [_r(0, 3, 0, 0.9), _r(3.0, 3.2, 5, skip=True), _r(3.2, 4.0, 1), _r(4.2, 7, 0, 0.9)]
        self.assertEqual(S.smooth_labels(rows, []), {2: 0})
        rows = [_r(0, 3, 0, 0.9), _r(3.2, 4.0, 1, skip=True), _r(4.2, 7, 0, 0.9)]
        self.assertEqual(S.smooth_labels(rows, []), {})

    def test_order_by_time(self):
        rows = [_BASE[2], _BASE[0], _BASE[1]]
        self.assertEqual(S.smooth_labels(rows, []), {2: 0})

    def test_label_ratio(self):
        ts = [(0, 3, 0), (3.5, 3.74, 1)]
        self.assertAlmostEqual(S.label_ratio(3.2, 4.0, 1, ts), 0.3)
        self.assertEqual(S.label_ratio(3.2, 4.0, None, ts), 0.0)
        self.assertEqual(S.label_ratio(0, 2, 0, ts), 1.0)


class TestSmoothSpeakers(unittest.TestCase):
    """assign_speakers の結果から(本番と同じ道)"""

    def test_with_assign_speakers(self):
        segs = [{"start": 0.0, "end": 3.0, "text": "a"}, {"start": 3.2, "end": 4.0, "text": "b"}, {"start": 4.2, "end": 7.0, "text": "c"}]
        turns = [(0.0, 3.1, 0), (3.5, 3.74, 1), (4.1, 7.0, 0)]
        res = S.assign_speakers(segs, turns, 0.0)
        self.assertEqual([r[0] for r in res], [0, 1, 0])
        self.assertEqual(S.smooth_speakers(segs, res, sorted(turns), [False] * 3), {1: 0})
        self.assertEqual(S.smooth_speakers(segs, res, sorted(turns), [False, True, False]), {})   # 守る行
        segs[1]["text"] = " "
        self.assertEqual(S.smooth_speakers(segs, res, sorted(turns), [False] * 3), {})            # 文字の無い行

    def test_real_backchannel_is_kept(self):
        """短い行でも、その人の区間に入っていれば(本物の相づち)ならさない"""
        segs = [{"start": 0.0, "end": 3.0, "text": "a"}, {"start": 3.2, "end": 3.8, "text": "うん"}, {"start": 4.0, "end": 7.0, "text": "c"}]
        turns = [(0.0, 3.1, 0), (3.15, 3.85, 1), (3.95, 7.0, 0)]
        res = S.assign_speakers(segs, turns, 0.0)
        self.assertEqual(S.smooth_speakers(segs, res, sorted(turns), [False] * 3), {})


class TestSmoothApply(StoreDir):
    """apply_diarization(smooth=True): 行の話者だけならす・diar.json の記録・既定オフ・設定 diarSmooth"""

    SEGS = [{"id": "s1", "start": 0.0, "end": 3.0, "text": "a", "speaker": "", "flag": ""},
            {"id": "s2", "start": 3.2, "end": 4.0, "text": "b", "speaker": "", "flag": ""},
            {"id": "s3", "start": 4.2, "end": 7.0, "text": "c", "speaker": "", "flag": ""},
            {"id": "s4", "start": 8.0, "end": 12.0, "text": "d", "speaker": "", "flag": ""}]
    TURNS = [(0.0, 3.1, 0), (3.5, 3.74, 1), (4.1, 7.0, 0), (8.0, 12.0, 1)]

    def put(self):
        self.put_doc({"title": "t", "sourcePath": "C:\\x\\clip.mp4", "createdAt": 1, "updatedAt": 1, "speakers": [], "segments": [dict(g) for g in self.SEGS]})

    def read(self):
        with open(S.tx_path(TID), encoding="utf-8") as f:
            return json.load(f)

    def test_off_by_default(self):
        self.put()
        S.apply_diarization(TID, self.TURNS, 0.0, 0)
        d, run = self.read(), S.read_diar(TID)["latest"]
        self.assertEqual([g["speaker"] for g in d["segments"]], ["S1", "S2", "S1", "S2"])
        self.assertNotIn("smooth", run)
        self.assertNotIn("smoothed", d["diarization"])
        self.assertFalse(any(r.get("smoothed") for r in run["rows"].values()))

    def test_on(self):
        self.put()
        S.apply_diarization(TID, self.TURNS, 0.0, 0, smooth=True)
        d, run = self.read(), S.read_diar(TID)["latest"]
        self.assertEqual([g["speaker"] for g in d["segments"]], ["S1", "S1", "S1", "S2"])
        self.assertIn(S.WEAK_FLAG, d["segments"][1]["flag"])     # ならした行は「話者が不確か」を残す(人が見られるように)
        self.assertEqual(d["diarization"]["smoothed"], 1)
        r2 = run["rows"]["s2"]
        self.assertEqual((r2["label"], r2["speaker"], r2["smoothed"], r2["weak"]), (1, "S1", True, True))   # label は機械の元のラベル
        self.assertAlmostEqual(r2["ratio"], 0.3)
        self.assertNotIn("smoothed", run["rows"]["s1"])
        self.assertEqual(run["smooth"], {"on": True, "rows": 1, "short": S.DIAR_SMOOTH_SHORT, "gap": S.DIAR_SMOOTH_GAP, "ratio": S.DIAR_SMOOTH_RATIO})
        self.assertEqual([t["label"] for t in run["turns"]], [0, 1, 0, 1])   # 生の結果は変えない(空の行の下書きが読む)
        self.assertEqual(run["labelMap"], {"0": "S1", "1": "S2"})

    def test_on_nothing_to_smooth_still_records(self):
        self.put()
        S.apply_diarization(TID, [(0.0, 12.0, 0)], 0.0, 0, smooth=True)
        self.assertEqual(S.read_diar(TID)["latest"]["smooth"]["rows"], 0)

    def test_validate_and_setting(self):
        self.put()
        with unittest.mock.patch.object(S, "check_source", lambda p: p):
            self.assertIs(S.validate_diarize({"tid": TID})["smooth"], False)                 # 既定オフ
            self.assertIs(S.validate_diarize({"tid": TID, "smooth": True})["smooth"], True)
            S.patch_settings({"values": {"diarSmooth": True}})
            self.assertIs(S.validate_diarize({"tid": TID})["smooth"], True)                  # 要求に無ければ設定
            self.assertIs(S.validate_diarize({"tid": TID, "smooth": False})["smooth"], False)
            self.assertIs(S.validate_diarize({"tid": TID, "smooth": "yes"})["smooth"], True)  # 真偽値でなければ設定
        with self.assertRaises(S.ApiError):
            S.patch_settings({"values": {"diarSmooth": "on"}})
        self.assertIn("diarSmooth", S.SETTINGS_PATCH_KEYS)

    def test_run_diarize_fake_passes_smooth(self):
        """疑似の判別(10 秒ごとの入れ替わり)でも、ジョブの spec の smooth が apply_diarization まで届く"""
        self.put()
        seen = []
        real = S.ed_speakers.apply_diarization

        def spy(*a, **k):
            seen.append(a[6] if len(a) > 6 else k.get("smooth"))
            return real(*a, **k)
        with unittest.mock.patch.object(S.ed_speakers, "apply_diarization", spy), \
                unittest.mock.patch.object(S, "check_source", lambda p: p), \
                unittest.mock.patch.object(S.ed_jobs, "extract_audio", lambda job, spec, wav: None), \
                unittest.mock.patch.object(S, "media_duration", lambda p: 12.0), \
                unittest.mock.patch.object(S.ed_state, "backend_name", lambda: "fake"):
            spec = S.validate_diarize({"tid": TID, "smooth": True, "recognize": False})
            job = {"id": "j1", "spec": spec, "cancel": False, "state": "queued", "phase": "", "progress": 0.0, "kind": "diarize"}
            S.run_diarize(job)
        self.assertEqual((job["state"], seen), ("done", [True]), job.get("error"))


if __name__ == "__main__":
    unittest.main()
