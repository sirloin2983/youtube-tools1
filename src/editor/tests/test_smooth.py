#!/usr/bin/env python3
"""話者の細切れをならす(smooth_labels・smooth_speakers・apply_diarization(smooth)・設定 diarSmooth)のテスト。

    python -m unittest src/editor/tests/test_metrics.py   # test_metrics がこのファイルのテストも読み込む
    python -m unittest test_smooth -q                 # これだけ(src/editor/tests で)

- 短い 1 行だけ前後と違う話者で、根拠が弱い(自分のラベルの区間に入っている割合が低い)・前後とのすき間が小さい・重なりが無い → 前後の話者にする
- 判別の生の結果(turns・overlaps)は変えない。diar.json の rows に smoothed: true(label は元のラベル)。既定はオフ
- 判別のジョブの要求 smooth が記録まで届くこと・既定でならさないことは、本物の判別の通し(test_voices.py の TestDiarRealRun)が確かめる
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import unittest
import unittest.mock

from test_backend import S, TID, StoreDir  # noqa: F401  (S = serve)


def _r(a, b, label, ratio=0.3, skip=False):
    return {"start": a, "end": b, "label": label, "ratio": ratio, "skip": skip}


def _episode(t, mid, before=None, after=None):
    """前後が 0(A)の長い行で、真ん中に短い行(既定は 1(B)・根拠が弱い 30%)。t から始める"""
    rows = [_r(t, t + 3, 0, 0.9)] + [dict(_r(t + 3 + a, t + 3 + b, lab, ratio), skip=skip) for a, b, lab, ratio, skip in mid]
    end = rows[-1]["end"]
    rows.append(_r(end + (after if after is not None else 0.2), end + (after if after is not None else 0.2) + 2.8, 0 if before is None else before, 0.9))
    return rows


class TestSmoothLabels(unittest.TestCase):
    def test_rows_with_every_case(self):
        """場面ごとに 13 秒以上離した行の見本を 1 回 smooth_labels に通す(並びは時刻と逆にして渡す)"""
        W = 0.3
        rows = ([_r(0, 0.8, 1), _r(1.0, 4.0, 0, 0.9)] +                                    # 最初の行はならさない
                _episode(10, [(0.2, 1.0, 1, W, False)]) +                                  # 短い・弱い・すき間が小さい・前後が同じ = ならす
                _episode(30, [(0.2, 1.0, 1, 0.6, False)]) +                                # その人の区間にしっかり入っている(本物の相づち)
                _episode(50, [(0.2, 1.0, 1, 0.59, False)]) +                               # 0.59 はならす
                _episode(70, [(0.0, 1.2, 1, W, False)], after=0.0) +                       # 1.2 秒(DIAR_SMOOTH_SHORT 以上)
                _episode(90, [(0.2, 1.0, 1, W, False)], after=0.7) +                       # 後ろのすき間 0.7 秒
                _episode(110, [(0.2, 1.0, 1, W, False)], after=0.6) +                      # 0.6 秒はならす
                _episode(130, [(0.2, 1.0, 1, W, False)]) +                                 # 同時にしゃべっている(0.1 秒以上の重なり)
                _episode(150, [(0.2, 1.0, 1, W, False)]) +                                 # 0.05 秒の重なりはならす
                _episode(170, [(0.2, 1.0, 1, W, False)], before=2) +                       # 前後が違う人
                _episode(190, [(0.2, 1.0, 1, W, False)], before=None) [:-1] + [_r(194.2, 197, None, 0.9)] +   # 後ろの話者が無い
                _episode(210, [(0.1, 0.8, 1, W, False), (0.9, 1.6, 1, W, False)]) +        # 別の人の短い行が 2 行続く
                _episode(230, [(0.0, 0.2, 5, W, True), (0.2, 1.0, 1, W, False)]) +         # 守る行・文字の無い行は前後に数えない
                _episode(250, [(0.2, 1.0, 1, W, True)]) +                                  # 守る行そのものはならさない
                [_r(300, 303, 0, 0.9), _r(303.2, 304.0, 1)])                               # 最後の行はならさない
        overlaps = [(133.5, 133.65), (153.5, 153.55)]
        got = S.smooth_labels(list(reversed(rows)), overlaps)
        rev = list(reversed(rows))
        self.assertEqual(sorted((rev[i]["start"], lab) for i, lab in got.items()), [(13.2, 0), (53.2, 0), (113.2, 0), (153.2, 0), (233.2, 0)])
        ts = [(0, 3, 0), (3.5, 3.74, 1)]
        self.assertEqual((round(S.label_ratio(3.2, 4.0, 1, ts), 6), S.label_ratio(3.2, 4.0, None, ts), S.label_ratio(0, 2, 0, ts)), (0.3, 0.0, 1.0))

    def test_with_assign_speakers(self):
        """assign_speakers の結果から(本番と同じ道)。守る行・文字の無い行・その人の区間に入っている短い行(本物の相づち)はならさない"""
        segs = [{"start": 0.0, "end": 3.0, "text": "a"}, {"start": 3.2, "end": 4.0, "text": "b"}, {"start": 4.2, "end": 7.0, "text": "c"}]
        turns = [(0.0, 3.1, 0), (3.5, 3.74, 1), (4.1, 7.0, 0)]
        res = S.assign_speakers(segs, turns, 0.0)
        self.assertEqual([r[0] for r in res], [0, 1, 0])
        self.assertEqual(S.smooth_speakers(segs, res, sorted(turns), [False] * 3), {1: 0})
        self.assertEqual(S.smooth_speakers(segs, res, sorted(turns), [False, True, False]), {})
        self.assertEqual(S.smooth_speakers([dict(segs[0]), dict(segs[1], text=" "), dict(segs[2])], res, sorted(turns), [False] * 3), {})
        segs = [{"start": 0.0, "end": 3.0, "text": "a"}, {"start": 3.2, "end": 3.8, "text": "うん"}, {"start": 4.0, "end": 7.0, "text": "c"}]
        turns = [(0.0, 3.1, 0), (3.15, 3.85, 1), (3.95, 7.0, 0)]
        self.assertEqual(S.smooth_speakers(segs, S.assign_speakers(segs, turns, 0.0), sorted(turns), [False] * 3), {})


class TestSmoothApply(StoreDir):
    """apply_diarization(smooth=True): 行の話者だけならす・diar.json の記録・設定 diarSmooth(決まった区間で、ならす 1 行を作る)"""

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
        self.assertEqual([t["label"] for t in run["turns"]], [0, 1, 0, 1])   # 生の結果は変えない
        self.assertEqual(run["labelMap"], {"0": "S1", "1": "S2"})
        S.apply_diarization(TID, [(0.0, 12.0, 0)], 0.0, 0, smooth=True)   # ならす所が無くても記録する
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


if __name__ == "__main__":
    unittest.main()
