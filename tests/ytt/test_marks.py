#!/usr/bin/env python3
"""ytt/marks.py(マークの純粋な語彙)の単体テスト。

    python -m unittest tests/ytt/test_marks.py

保存済みのマークの見本(壊れた行・重なる id・自動・書き出し済み・機械の採用・長い依頼の区間)を、読み込み(load_marks)→ 画面からの保存(validate_marks)
→ 解析の反映(replace_auto)→ 書き出し済みにする(exported_mark)の順に通して、まとめて確かめる。
期待値は store のテスト(tests/human/review/test_studio.py)と同じ。Store を通した動き(保存・学習の記録)はそちらが確かめる。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))   # src
from ytt import marks as M  # noqa: E402


def auto_mark(s, e, **kw):
    """保存済みの自動マーク(候補・手つかず)"""
    d = {"id": "a1", "start": s, "end": e, "label": "", "src": "auto", "score": 5.0, "status": "", "auto0": [s, e]}
    d.update(kw)
    return M.build_mark(d, None, True)


class TestMarksRun(unittest.TestCase):
    def test_load_then_save_from_screen(self):
        long = M.new_mark("r", 600, 600 + 3 * 3600, "adopted", limit=None)   # 友人の依頼の長い区間(読み込みは長さを見ない)
        raw = [{"id": "m1", "start": 1, "end": 9}, {"id": "m1", "start": 2, "end": 9}, {"id": "bad id!", "start": 1, "end": 9},
               {"id": "m2", "start": 9, "end": 1}, "x",
               {"id": "t1", "start": 10, "end": 40, "src": "auto", "score": 5.0, "auto0": [10, 40], "reasons": ["音量"] * 9,
                "parts": {"audio": 1.234, "x": 3}, "peak": 11.26, "status": "adopted", "adoptedBy": "auto"},
               {"id": "t2", "start": 50, "end": 60, "src": "auto", "score": 3.0, "auto0": [50, 60], "status": "adopted", "adoptedBy": "auto"},
               {"id": "e1", "start": 100, "end": 140, "status": "exported", "file": "f/a.mp4", "path": "C:/x/a.mp4", "archived": True},
               {"id": "e2", "start": 200, "end": 240, "status": "exported", "file": "f/b.mp4"},
               long]
        old = M.load_marks(raw)
        self.assertEqual([m["id"] for m in old], ["m1", "t1", "t2", "e1", "e2", long["id"]])   # 壊れた行・重なる id は読み飛ばす
        t1, e1 = old[1], old[3]
        self.assertEqual((t1["src"], t1["score"], t1["auto0"], t1["peak"], len(t1["reasons"]), t1["parts"]), ("auto", 5.0, [10.0, 40.0], 11.3, 6, {"audio": 1.23}))
        self.assertEqual((e1["status"], e1["path"], e1["archived"]), ("exported", "C:/x/a.mp4", True))
        self.assertEqual((len(M.load_marks([{"id": "m%d" % i, "start": i, "end": i + 1} for i in range(M.MAX_MARKS + 5)])), M.load_marks(None)), (M.MAX_MARKS, []))
        self.assertNotIn("archived", M.drop_archived([dict(e1)], "youtube")[0])   # 本番版の印は live の配信だけ
        self.assertTrue(M.drop_archived([dict(e1)], "live")[0]["archived"])

        saved = M.validate_marks([
            {"start": 1, "end": 9, "src": "auto", "score": 99, "status": "exported", "file": "x.mp4", "auto0": [1, 9]},   # 新しいマーク = 手動・サーバーの欄は無視
            {"id": "n2", "start": 1, "end": 9, "status": "rejected"},
            dict(t1), dict(old[2], status="rejected"),                    # 状態を変えなければ機械の採用の印は残る・人が変えたら外す
            {"id": "e1", "start": 100.02, "end": 140}, {"id": "e2", "start": 202, "end": 240},   # EDIT_TOL の中はそのまま・動かしたら採用に戻る
            dict(long, label="長い区間"),                                 # 前の長さのままなら 60 分を超えても保存できる
        ], old)
        new, n2, t1s, t2s, e1s, e2s, lg = saved
        self.assertTrue(M.ID_RE.match(new["id"]) and new["id"] not in {m["id"] for m in old})
        self.assertEqual((new["src"], new["status"], new["file"], new["score"], "auto0" in new), ("manual", "", "", None, False))
        self.assertEqual(n2["status"], "rejected")
        self.assertEqual((t1s.get("adoptedBy"), "adoptedBy" in t2s), ("auto", False))
        self.assertEqual((e1s["status"], e1s["file"], e1s["archived"]), ("exported", "f/a.mp4", True))
        self.assertEqual((e2s["status"], e2s["file"], "path" in e2s), ("adopted", "", False))
        self.assertEqual((lg["end"], lg["label"]), (11400.0, "長い区間"))
        self.assertEqual(M.validate_marks([dict(long, start=700)], old)[0]["start"], 700.0)   # 縮めるのもよい
        for bad in ([dict(long, end=11500)], [{"id": "new1", "start": 0, "end": 3601}], [{"id": "x", "start": 1, "end": 9}] * 2, ["x"]):
            with self.assertRaises(M.ApiError, msg=bad):                  # 前より長く・新しく 60 分を超える・id の重なり・形の違い
                M.validate_marks(bad, old)

        self.assertEqual(M.check_times(1.04, 10.26), (1.0, 10.3))
        self.assertEqual((M.check_times(0, 3600), M.check_times(0, 3 * 3600, None), M.check_times(0, 100, 100.0)), ((0.0, 3600.0), (0.0, 10800.0), (0.0, 100.0)))
        for a, b, lim in [("1", 2, 3600), (True, 2, 3600), (float("nan"), 2, 3600), (-1, 5, 3600), (5, 5, 3600), (5, 4, 3600), (0, 3601, 3600),
                          (0, 1e9, 3600), (None, 1, 3600), (0, 101, 100.0), (-1, 5, None), (5, 5, None), (0, 1e9, None)]:
            with self.assertRaises(M.BadMark, msg=(a, b, lim)):
                M.check_times(a, b, lim)
        self.assertEqual((M.clamp_end(600, 10, 700), M.clamp_end(0, 10, 700), M.clamp_end(600, 600, 700)), (600.0, 700, None))   # 長さ不明は切らない
        m = M.new_mark("r", 1.0, 9.0, "adopted")
        self.assertTrue(m["id"].startswith("r") and M.ID_RE.match(m["id"]))
        self.assertEqual((m["src"], m["status"], m["start"], m["end"]), ("manual", "adopted", 1.0, 9.0))
        with self.assertRaises(M.BadMark):
            M.new_mark("c", 0, 3601)   # 既定は 60 分まで(コラボの転写・解析の候補)
        self.assertEqual(M.collab_from({"videoId": "v1", "markId": "m1", "x": 1}), {"videoId": "v1", "markId": "m1"})
        self.assertIsNone(M.collab_from({"videoId": "bad id!", "markId": "m1"}))

    def test_same_place_rules(self):
        self.assertEqual([M.same({"start": 10, "end": 40}, b) for b in ({"start": 10.5, "end": 39.5}, {"start": 10.6, "end": 40})], [True, False])
        self.assertTrue(M.near(10, 40, 10.9, 40, tol=1.0))
        a = {"start": 100.0, "end": 140.0}
        self.assertEqual([M.similar(a, {"start": 104.9, "end": 144.9}), M.similar(a, {"start": 105.1, "end": 140.0}),   # ±5 秒の中 / 外
                          M.similar({"start": 0.0, "end": 6.0}, {"start": 4.0, "end": 10.0}), M.similar({"start": 0.0, "end": 6.0}, {"start": 3.0, "end": 9.0})],
                         [True, False, False, True])   # 短い区間どうしは重なりが半分以上のときだけ
        self.assertEqual((M.overlaps(10, 40, 39, 50), M.overlaps(10, 40, 40, 50)), (True, False))   # 端が接するだけは重ならない
        self.assertEqual([M.touched(x) for x in (auto_mark(10, 40), auto_mark(10, 40, status="rejected"), auto_mark(10, 40, label="x"),
                                                 dict(auto_mark(10, 40), start=12.0), dict(auto_mark(10, 40), start=10.04),
                                                 M.build_mark({"id": "m1", "start": 1, "end": 9}, None))],
                         [False, True, True, True, False, True])   # EDIT_TOL の中は手つかず・auto0 が無い = 手のマーク
        ms = [{"id": "b", "start": 50.0, "end": 60.0}, {"id": "a", "start": 10.0, "end": 20.0}, {"id": "c", "start": 10.0, "end": 15.0}, "壊れた"]
        self.assertEqual((M.near_mark(ms, 10.4, 19.6)["id"], M.near_mark(ms, 10.6, 20.0), M.near_mark(ms, 10.6, 20.0, tol=1.0)["id"]), ("a", None, "a"))
        self.assertEqual([M.order_of(ms, x) for x in ("c", "a", "b", "z")], [1, 2, 3, 0])   # 開始の順・同じなら終了の順・無ければ 0

    def test_replace_auto_then_exported(self):
        """解析の反映 replace_auto と書き出し済みにする exported_mark(スタジオの Store と flow/studiobook で同じ 1 つ)"""
        keep = dict(auto_mark(10, 40, label="手"), id="k")   # 手を入れた自動 = 手動として残す(auto0 は auto0Orig へ)
        drop = dict(auto_mark(100, 130), id="d")              # 手つかずの自動 = 置き換える
        man = M.build_mark({"id": "m", "start": 200, "end": 230}, None)
        cands = [{"start": 10.2, "end": 40.1, "score": 9}, {"start": 300, "end": 330, "score": 3, "reasons": ["音量"]}, {"start": "x", "end": 1}]
        out, n = M.replace_auto([keep, drop, man], cands)
        self.assertEqual(n, 1)   # 同じ区間(±0.5 秒)・形の違う候補は作らない
        self.assertEqual([(m["src"], m["start"]) for m in out], [("manual", 10.0), ("manual", 200.0), ("auto", 300.0)])
        self.assertEqual((out[0]["auto0Orig"], "auto0" in out[0]), ([10.0, 40.0], False))
        self.assertEqual((out[2]["auto0"], out[2]["score"], out[2]["reasons"]), ([300.0, 330.0], 3.0, ["音量"]))
        self.assertEqual(drop["src"], "auto", "元の一覧は変えない")
        out2, n2 = M.replace_auto([], cands, hide=lambda autos: [a for a in autos if a["start"] != 300.0])
        self.assertEqual((n2, [m["start"] for m in out2]), (1, [10.2]))

        m = dict(out[2], status="adopted")
        nm = M.exported_mark(m, "題/01.mp4", "C:/out/題/01.mp4" if os.name == "nt" else "/out/題/01.mp4")
        self.assertEqual((nm["status"], nm["file"], m["status"]), ("exported", "題/01.mp4", "adopted"))
        self.assertTrue(os.path.isabs(nm["path"]))
        self.assertNotIn("path", M.exported_mark(m, "題/01.mp4", "rel/01.mp4"))   # 絶対パスでなければ持たない
        arch = dict(nm, archived=True)
        self.assertTrue(M.exported_mark(arch, nm["file"], nm["path"], None, live=True).get("archived"))   # 同じファイル = 印のまま
        self.assertNotIn("archived", M.exported_mark(arch, "題/02.mp4", nm["path"], None, live=True))   # 違うファイル = 外す
        self.assertNotIn("archived", M.exported_mark(arch, nm["file"], nm["path"], True, live=False))   # live でなければ立てない
        pad = M.exported_mark(m, "題/01.mp4", None, clip=(0.0, 50.5))   # 余白つきの動画の実際の始まり・終わり
        self.assertEqual((pad["clipFrom"], pad["clipTo"]), (0.0, 50.5))
        self.assertNotIn("clipFrom", M.exported_mark(pad, "題/01.mp4", None))   # 余白なしで書き出し直したら外す


if __name__ == "__main__":
    unittest.main()
