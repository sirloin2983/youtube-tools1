#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve パックの契約テスト(文字起こしの「Resolveパッケージ(zip)」と cut2resolve の Text+ パック)。

経緯: 2つの実装(transcribe-tool/resolve_export.py と cut2resolve/pack.py)があった(AGENTS.md の【高】リスク)。
2026-09-26 に、先にこのテストで「同じ入力から同じ中身」を固定してから、resolve_export を pack.py を呼ぶだけの形に寄せた。

このテストが守ること:
  A. 一本化の前後で動きが変わらない … 旧 resolve_export の計算(下の LEGACY。一本化の前のコードをそのまま凍結)と、
     今の文字起こしツールの経路(pack.plan_cut + pack.TRANSCRIPT_ROWS)で、残す区間・字幕・SRT が同じ。
     2026-09-26(⑥ 語頭・語尾が切れる)から TRANSCRIPT_ROWS は行の端を声の止まる所まで広げる(pack.ROW_EDGE)ので、
     A は「広げない」(row_edge=None)で比べる(行の時間を残す規則そのものは変わっていない)。広げ方の契約は RowEdgeContract
  B. 同じ入力から同じパック … 文字起こしツールの zip の中身と、cut2resolve で同じ文字起こしから作った Text+ パックが同じ
     (Lua・雛形・登録用の bat/ps1・手順書・動画のすべてのファイル。どちらも行の端を広げる既定・画面の既定の最小限(④)。予備ありも同じ)。
     2026-09-26(④)から textplus-import.json は出さない(中身は Lua に埋め込み済み。区間と字幕は resolve_textplus.read_script_plan で読む)

A の入力の範囲: 行は時刻順(開始が同じなら終わりの早い順)・動画の中に収まる・時刻は 0.02 秒刻み(faster-whisper の時刻の刻み。25fps を除く)・
選んだ fps = 動画の fps。この範囲の外では、旧 resolve_export に不具合があり、一本化で直した(KnownFixes に固定。詳しくは docs/resolve-pack-unification.md):
  - ちょうど半フレームの時刻 … 旧は float の誤差で1フレーム下に丸まることがあった(今は分数で正確に・0.5 は大きい方へ)
  - 動画の終わりをまたぐ行 … 旧は字幕を捨てていた(今は終わりで切って残す)
  - 時刻順でない行 … 旧は字幕を文書の順に並べていた(SRT の番号が時刻順にならない。今は時刻順)
  - 動画の終わり … 旧は文書の duration から数えた(実際のフレーム数を超えることがあった。今は ffprobe のフレーム数)
  - 選んだ fps が動画と違う … 旧は選んだ fps でフレームを数えた(Resolve の元クリップのフレームとずれた。今は動画の fps で数える)

実行(リポジトリ直下): python -m unittest tools/test_resolve_pack_contract.py   (ffmpeg・ffprobe が要る)
"""
import json
import math
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for d in (ROOT / "cut2resolve", ROOT / "transcribe-tool", ROOT):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

import pack  # noqa: E402  cut2resolve
import resolve_textplus as TP  # noqa: E402  cut2resolve
import srt2resolve as S  # noqa: E402  cut2resolve
import pipeline_io  # noqa: E402  transcribe-tool
import resolve_export  # noqa: E402  transcribe-tool

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
FPS_RATE = {"24": "24", "25": "25", "29.97": "30000/1001", "30": "30", "50": "50", "59.94": "60000/1001", "60": "60"}
VIDEO_SEC = 12


# ---------------------------------------------------------------- LEGACY: 一本化の前の resolve_export の計算(凍結。直さない)
# 928c3b1 の transcribe-tool/resolve_export.py の build_plan と _build_srt から、区間と字幕の計算だけを写したもの
# (余白つき素材が無い場合。余白つき素材の場合の旧の結果は、test_same_pack_with_studio_edit_media に値で残す)

class LEGACY:
    SUPPORTED_FPS = {"24": Fraction(24), "25": Fraction(25), "29.97": Fraction(30000, 1001),
                     "30": Fraction(30), "50": Fraction(50), "59.94": Fraction(60000, 1001), "60": Fraction(60)}

    @staticmethod
    def frames(seconds, fps):
        return max(0, int(math.floor(float(seconds) * float(fps) + 0.5)))

    @staticmethod
    def seconds(frames, fps):
        return float(Fraction(frames, 1) / fps)

    @classmethod
    def kept_ranges(cls, segments, base, media_duration, fps):
        raw = []
        for span in resolve_export.kept_spans(segments):
            a = max(0.0, span["start"] - base)
            b = min(media_duration, span["end"] - base)
            if b > a:
                raw.append([cls.frames(a, fps), cls.frames(b, fps)])
        raw.sort()
        merged = []
        for a, b in raw:
            if merged and a <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out, record = [], 0
        for a, b in merged:
            if b <= a:
                continue
            out.append({"sourceStartFrame": a, "sourceEndFrame": b, "recordStartFrame": record, "recordEndFrame": record + b - a})
            record += b - a
        return out

    @classmethod
    def timeline_position(cls, source_seconds, cuts, fps):
        sf = cls.frames(source_seconds, fps)
        for cut in cuts:
            if cut["sourceStartFrame"] <= sf < cut["sourceEndFrame"]:
                return cls.seconds(cut["recordStartFrame"] + sf - cut["sourceStartFrame"], fps)
        return None

    @classmethod
    def plan(cls, doc, fps_text):
        """-> (区間, 字幕, SRT)。旧 build_plan と _build_srt と同じ計算"""
        fps = cls.SUPPORTED_FPS[fps_text]
        whole = doc.get("whole", True)
        base = float(doc.get("start") or 0) if not whole else 0.0
        file_duration = float(doc.get("duration") or 0)
        if whole:
            doc_duration = file_duration
        else:
            end = float(doc.get("end") or 0)
            doc_duration = end - base if end > base else max(0.0, file_duration - base)
        source_offset = base if not whole else 0.0
        media_duration = source_offset + max(0.0, doc_duration)
        shifted = []
        for seg in doc.get("segments") or []:
            one = dict(seg)
            one["start"] = source_offset + max(0.0, float(seg.get("start") or 0) - base)
            one["end"] = source_offset + max(0.0, float(seg.get("end") or 0) - base)
            shifted.append(one)
        cuts = cls.kept_ranges(shifted, 0.0, media_duration, fps)
        caps = []
        for seg in shifted:
            if not resolve_export.is_kept(seg):
                continue
            start = cls.timeline_position(float(seg["start"]), cuts, fps)
            end_probe = max(float(seg["start"]), float(seg["end"]) - 1.0 / float(fps))
            end = cls.timeline_position(end_probe, cuts, fps)
            if start is None or end is None:
                continue
            end += 1.0 / float(fps)
            if end > start:
                caps.append((cls.frames(start, fps), max(cls.frames(start, fps) + 1, cls.frames(end, fps)),
                             str(seg.get("text") or "").strip()))
        srt = resolve_export.srt_text((cls.seconds(a, fps), cls.seconds(b, fps), t) for a, b, t in caps)
        return [(c["sourceStartFrame"], c["sourceEndFrame"]) for c in cuts], caps, srt


def seg(i, a, b, text="x", cut=False, **kw):
    g = {"id": "s%d" % i, "start": a, "end": b, "text": text}
    if cut:
        g["cutState"] = "cut"
    g.update(kw)
    return g


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class ResolvePackContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="c2r-contract-")
        cls.videos = {}
        cls.cache = pack.Cache(size=32)   # 同じ動画の ffprobe を何度もしない

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def video(self, fps_text):
        if fps_text not in self.videos:
            p = os.path.join(self.tmp, "v%s.mp4" % fps_text.replace(".", "_"))
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=160x90:rate=%s:duration=%d" % (FPS_RATE[fps_text], VIDEO_SEC),
                            "-f", "lavfi", "-i", "sine=duration=%d" % VIDEO_SEC,
                            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", p], check=True)
            self.videos[fps_text] = p
        return self.videos[fps_text]

    def doc(self, segments, fps_text="30", **kw):
        d = {"title": "契約", "sourcePath": self.video(fps_text), "whole": True, "duration": VIDEO_SEC, "segments": segments}
        d.update(kw)
        return d

    def write_v1(self, doc):
        tp = Path(self.tmp) / (Path(doc["sourcePath"]).stem + ".transcript.json")
        tp.write_text(json.dumps(pipeline_io.build_transcript_v1(doc, "contract"), ensure_ascii=False), encoding="utf-8")
        return tp

    # ---- 今の文字起こしツールの経路(create_package と同じ: 文書 → transcript/v1 → pack.plan_cut(TRANSCRIPT_ROWS))

    def current(self, doc, row_edge=None):
        """row_edge=None: 行の端を広げない(A の LEGACY と比べる)。pack.ROW_EDGE: 今の既定(zip・まとめて実行・「行から」)"""
        p = pack.plan_cut(pack.Request(video=Path(doc["sourcePath"]), transcript=self.write_v1(doc),
                                       **dict(pack.TRANSCRIPT_ROWS, row_edge=row_edge)), cache=self.cache)
        caps = [tuple(c) for c in (p.cues_out or [])]
        return [tuple(k) for k in p.keeps], caps, S.build_srt(caps, p.meta["fps"])

    def assertUnchanged(self, doc, fps_text="30", msg=""):
        """A: 一本化の前(LEGACY)と今で、残す区間・字幕・SRT が同じ"""
        old, new = LEGACY.plan(doc, fps_text), self.current(doc)
        self.assertEqual(old[0], new[0], "残す区間が変わった %s" % msg)
        self.assertEqual(old[1], new[1], "字幕が変わった %s" % msg)
        self.assertEqual(old[2], new[2], "SRT が変わった %s" % msg)
        return new

    # ---- B: 文字起こしの zip と cut2resolve の Text+ パック

    def pack_files(self, doc, fps_text="30", size=None, backup=False):
        """-> (文字起こしの zip の中身 {名前: bytes}, cut2resolve のパックの中身 {名前: bytes})。日時を含む cut-plan.json は除く"""
        zp, tmp_dir, _ = resolve_export.create_package(doc, fps_text, size, backup=backup)
        self.addCleanup(shutil.rmtree, tmp_dir, True)
        with zipfile.ZipFile(zp) as z:
            a = {n.split("/", 1)[1]: z.read(n) for n in z.namelist() if not n.endswith("/")}
        out = Path(tempfile.mkdtemp(dir=self.tmp)) / "pack"
        plan = pack.plan_cut(pack.Request(video=Path(doc["sourcePath"]), transcript=self.write_v1(doc), **pack.TRANSCRIPT_ROWS))
        # cut2resolve の API(画面)と同じ: cut-plan.json はフォルダに書かない・予備は指定どおり
        res = pack.build_pack(plan, out, textplus=True, textplus_target=TP.parse_target(fps_text, size), backup=backup, plan_file=False)
        b = {p.relative_to(out).as_posix(): p.read_bytes() for _, p in res["files"]}
        return a, b

    def assertSamePack(self, doc, fps_text="30", size=None, backup=False):
        a, b = self.pack_files(doc, fps_text, size, backup)
        self.assertEqual(sorted(a), sorted(b))
        for name in sorted(a):
            self.assertEqual(a[name], b[name], "%s が違う" % name)
        self.assertNotIn("textplus-import.json", a)
        self.assertNotIn("cut-plan.json", a)
        self.assertEqual(any(n.endswith(".edl") for n in a), backup)
        return TP.read_script_plan(a["create_resolve_textplus_project.lua"].decode("utf-8"))

    # ---- A: 代表的な入力

    def test_cut_rows_are_removed(self):
        cuts, caps, _ = self.assertUnchanged(self.doc([seg(1, 0, 2, "残す"), seg(2, 2, 4, "切る", cut=True), seg(3, 4, 8, "もう一度")]))
        self.assertEqual(cuts, [(0, 60), (120, 240)])
        self.assertEqual(caps, [(0, 60, "残す"), (60, 180, "もう一度")])

    def test_gaps_between_rows_are_not_kept(self):
        cuts, _, _ = self.assertUnchanged(self.doc([seg(1, 0.5, 2, "a"), seg(2, 3, 4, "b"), seg(3, 6, 7.5, "c")]))
        self.assertEqual(cuts, [(15, 60), (90, 120), (180, 225)])

    def test_overlapping_rows_merge_and_keep_both_captions(self):
        _, caps, _ = self.assertUnchanged(self.doc([seg(1, 1, 3, "a"), seg(2, 2.5, 4, "b"), seg(3, 5, 6, "c")]))
        self.assertEqual([c[2] for c in caps], ["a", "b", "c"])

    def test_kept_row_wins_over_overlapping_cut_row(self):
        self.assertUnchanged(self.doc([seg(1, 1, 3, "a"), seg(2, 2.5, 4, "b", cut=True), seg(3, 5, 6, "c")]))

    def test_empty_text_rows_are_not_kept(self):
        cuts, _, _ = self.assertUnchanged(self.doc([seg(1, 1, 3, "a"), seg(2, 3, 4, "  "), seg(3, 4.5, 6, "c")]))
        self.assertEqual(cuts, [(30, 90), (135, 180)])

    def test_short_rows_are_kept(self):
        """0.2 秒の行も捨てない(cut2resolve の既定の最短 0.3 秒は使わない)"""
        cuts, _, _ = self.assertUnchanged(self.doc([seg(1, 1, 1.2, "短い"), seg(2, 3, 4, "b")]))
        self.assertEqual(cuts, [(30, 36), (90, 120)])

    def test_one_frame_gap_is_joined(self):
        """1フレームの隙間はつなぐ(1フレームだけのジャンプカットを作らない)"""
        cuts, caps, _ = self.assertUnchanged(self.doc([seg(1, 1, 2, "a"), seg(2, 2.034, 3, "b")]))
        self.assertEqual(cuts, [(30, 90)])
        self.assertEqual(caps, [(0, 30, "a"), (31, 60, "b")])

    def test_half_frame_boundary_of_cut(self):
        """半フレームの時刻(30fps の 3.35 秒 = 100.5 フレーム)は大きい方へ丸め、次の行(3.351 秒)と1つの区間になる"""
        cuts, caps, _ = self.assertUnchanged(self.doc([seg(1, 0.083, 1.517, "a"), seg(2, 2.083, 3.35, "b"), seg(3, 3.351, 5.049, "c")]))
        self.assertEqual(cuts, [(2, 46), (62, 151)])
        self.assertEqual(caps[1], (44, 83, "b"))

    def test_range_transcript(self):
        """範囲を指定した文字起こし(時刻は動画ファイルの先頭基準のまま)"""
        self.assertUnchanged(self.doc([seg(1, 3.2, 4.1, "a"), seg(2, 5, 6.5, "b", cut=True), seg(3, 7, 9.25, "c")],
                                      whole=False, start=3.0, end=10.0))

    def test_other_frame_rates(self):
        rows = [seg(1, 0.51, 2.23, "a"), seg(2, 2.23, 3.37, "b", cut=True), seg(3, 3.37, 4.41, "c"), seg(4, 4.42, 6.05, "d")]
        for fps_text in ("24", "25", "29.97", "50", "59.94", "60"):
            with self.subTest(fps=fps_text):
                self.assertUnchanged(self.doc(rows, fps_text), fps_text, fps_text)

    def test_random_documents(self):
        """乱数で作った文書(時刻は 0.02 秒刻み。行は時刻順・動画の中)"""
        rnd = random.Random(20260926)
        for fps_text in ("30", "29.97", "60", "59.94", "24", "50"):
            for n in range(60):
                rows, t = [], rnd.choice([0.0, 0.26])
                for i in range(rnd.randint(1, 14)):
                    t += rnd.choice([0.0, 0.0, 0.02, 0.04, 0.06, 0.4, 1.2])      # 接する・1〜2フレーム前後・離れる
                    if rnd.random() < 0.15:
                        t = max(0.0, t - rnd.choice([0.3, 0.8]))                  # 前の行と重なる
                    a = round(t, 2)
                    b = round(a + rnd.choice([0.06, 0.12, 0.3, 0.9, 2.16]), 2)
                    if b > VIDEO_SEC - 0.5:
                        break
                    rows.append(seg(i, a, b, rnd.choice(["はい", "こんばんは", "  ", "え"]), cut=rnd.random() < 0.3))
                    t = b
                rows.sort(key=lambda r: (r["start"], r["end"]))   # 開始が同じ行は、終わりの早い順
                if not any(r["text"].strip() and r.get("cutState") != "cut" for r in rows):
                    continue   # 残す行が無い文書はエラー(下のテスト)
                with self.subTest(fps=fps_text, n=n):
                    self.assertUnchanged(self.doc(rows, fps_text), fps_text, "fps=%s n=%d %r" % (fps_text, n, rows))

    def test_nothing_to_keep_is_an_error(self):
        d = self.doc([seg(1, 1, 2, "a", cut=True), seg(2, 3, 4, " ")])
        with self.assertRaises(resolve_export.ResolveExportError):
            resolve_export.create_package(d)
        with self.assertRaises(pack.ToolError):
            self.current(d)

    # ---- B: 文字起こしの zip = cut2resolve の Text+ パック

    def test_same_pack_as_cut2resolve(self):
        ip = self.assertSamePack(self.doc([seg(1, 0, 2, "残す"), seg(2, 2, 4, "切る", cut=True), seg(3, 4, 8, "もう一度")]))
        # 行の端を広げる(⑥): 契約の動画はずっと音(無音が無い)→ 後ろに決まった余白 0.2 秒(6 フレーム)。カット済の行(2〜4 秒)は越えない。
        # 広げる前(2026-09-26 まで)は [(0, 60), (120, 240)]
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(0, 60), (120, 246)])

    def test_zip_uses_transcribe_rules(self):
        """zip の区間も TRANSCRIPT_ROWS(短い行を残す・1フレームの隙間はつなぐ・端を広げる)。文字起こし側が別の規則で pack を呼ぶと、ここで分かる"""
        d = self.doc([seg(1, 1, 1.2, "短い"), seg(2, 3, 4, "a"), seg(3, 4.034, 5, "b"), seg(4, 6, 7, "c", cut=True)])
        ip = self.assertSamePack(d)
        cuts, caps, _ = self.current(d, pack.ROW_EDGE)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], cuts)
        self.assertEqual([(c["startFrame"], c["endFrame"], c["text"]) for c in ip["captions"]], caps)
        self.assertEqual(cuts, [(27, 42), (87, 156)])   # 広げる前(LEGACY)は [(30, 36), (90, 150)]。無音が無い動画なので決まった余白(前 3・後 6)
        self.assertEqual(LEGACY.plan(d, "30")[0], [(30, 36), (90, 150)])

    def test_same_pack_other_targets_and_rates(self):
        rows = [seg(1, 0.52, 2.2, "a"), seg(2, 2.2, 3.4, "b", cut=True), seg(3, 3.4, 4.4, "c"), seg(4, 11, 13, "終わりをまたぐ")]
        for fps_text, target, size in (("29.97", "30", "1080x1920"), ("60", "30", None), ("24", "24", "1920x1080")):
            with self.subTest(fps=fps_text, target=target, size=size):
                self.assertSamePack(self.doc(rows, fps_text), target, size)
        self.assertSamePack(self.doc(rows, "30"), "30", None, backup=True)   # 予備(EDL・予備の手順書・SRT)も入れたとき

    def test_same_pack_with_studio_edit_media(self):
        d = Path(self.tmp) / "studio"
        d.mkdir(exist_ok=True)
        clip, edit = d / "clip.mp4", d / "clip_edit.mp4"
        shutil.copy(self.video("30"), clip)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=32",
                        "-f", "lavfi", "-i", "sine=duration=32", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", str(edit)], check=True)
        (d / "clip.edit.json").write_text(json.dumps({"schema": "clip-studio/edit-media/v1", "media": "clip_edit.mp4",
                                                      "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}), encoding="utf-8")
        doc = self.doc([seg(1, 0, 2, "残す"), seg(2, 2, 4, "切る", cut=True), seg(3, 4, 8, "もう一度")], sourcePath=str(clip))
        ip = self.assertSamePack(doc)
        # 旧 resolve_export で同じ入力から出た値は [(300, 360), (420, 540)](一本化の前の test_resolve_export の
        # test_plan_uses_handle_media_and_keeps_recoverable_source_offsets と同じ)。⑥ から終わりに決まった余白 6 フレーム(無音が無い動画)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(300, 360), (420, 546)])
        self.assertEqual([c["startFrame"] for c in ip["captions"]], [0, 60])
        self.assertEqual(ip["media"]["file"], "media/clip_edit.mp4")


def _load_transcribe_serve():
    """文字起こしの serve.py(行の「カット済」を編集の内容から決める edit_cut_flags)。cut2resolve の serve と名前が同じなので別の名前で読む"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tx_serve_for_contract", str(ROOT / "transcribe-tool" / "serve.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class EditKeepsContract(unittest.TestCase):
    """「編集」ツール(docs/edit-tool-design.md)のパック:
      C. 編集の残す区間(spec.keeps → pack.EDIT_KEEPS)で作ったパック = 同じ区間を時刻リスト(mode list)で作ったパック
      D. 以前の文書(行の cutState だけ)を開いたときのたたき台「行から」(api/plan の keepsSec を編集の内容にして保存 →
         行の cutState は編集の内容から付け直す)で作ったパック = 今の「カットとパック」(preset transcript-rows)のパック
         (行が重ならない文書。重なる行の一方だけがカット済のときは、編集では時間の一部が残る行を「残す行」にするので字幕が1つ増える)"""
    setUpClass = ResolvePackContract.__dict__["setUpClass"]
    tearDownClass = ResolvePackContract.__dict__["tearDownClass"]
    video, doc, write_v1 = ResolvePackContract.video, ResolvePackContract.doc, ResolvePackContract.write_v1

    def build(self, req, fps_text="30"):
        out = Path(tempfile.mkdtemp(dir=self.tmp)) / "pack"
        plan = pack.plan_cut(req, cache=self.cache)
        target = {"29.97": "30", "59.94": "60"}.get(fps_text, fps_text)   # 置き先のプロジェクトの fps(Text+ は整数だけ)
        res = pack.build_pack(plan, out, textplus=True, textplus_target=TP.parse_target(target, None))
        files = {p.relative_to(out).as_posix(): p.read_bytes() for _, p in res["files"]}
        files.pop("cut-plan.json", None)   # 日時が入る
        return plan, files

    def assertSameFiles(self, a, b):
        self.assertEqual(sorted(a), sorted(b))
        for name in sorted(a):
            self.assertEqual(a[name], b[name], "%s が違う" % name)

    def test_keeps_same_as_time_list(self):
        rows = [seg(1, 0.5, 2.0, "一つめ"), seg(2, 2.4, 3.1, "削った", cut=True), seg(3, 3.5, 6.2, "二つめ"), seg(4, 7.0, 9.0, "三つめ")]
        for fps_text in ("30", "29.97", "60", "59.94"):
            with self.subTest(fps=fps_text):
                num, den = Fraction(FPS_RATE[fps_text]).as_integer_ratio()
                sec = lambda f: round(f * den / num, 3)   # noqa: E731  編集の内容の保存の形(フレームの境目の秒・小数3桁)
                frames = [(12, 66), (100, 190), (215, 280)] if num / den < 40 else [(24, 132), (200, 380), (430, 560)]
                keeps = [(sec(a), sec(b)) for a, b in frames]
                video, tr = Path(self.video(fps_text)), self.write_v1(self.doc(rows, fps_text))
                p1, a = self.build(pack.Request(video=video, transcript=tr, keep_pairs=keeps, **pack.EDIT_KEEPS), fps_text)
                # 画面の「③ 時刻リスト」と同じ指定(cut2resolve の serve.request_from_spec の mode list の既定)
                p2, b = self.build(pack.Request(video=video, transcript=tr, base="list", keep_pairs=keeps, min_len=0.3), fps_text)
                self.assertEqual([tuple(k) for k in p1.keeps], frames)      # 編集で決めたフレームのまま(1フレームもずれない)
                self.assertSameFiles(a, b)
                ip = TP.read_script_plan(a["create_resolve_textplus_project.lua"].decode("utf-8"))
                self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], frames)

    def test_rows_draft_same_as_transcript_rows(self):
        tx = _load_transcribe_serve()
        cases = [
            [seg(1, 0, 2, "残す"), seg(2, 2, 4, "切る", cut=True), seg(3, 4, 8, "もう一度")],
            [seg(1, 0.52, 2.2, "a"), seg(2, 2.2, 3.4, "b", cut=True), seg(3, 3.4, 4.4, "c"), seg(4, 4.42, 6.04, "d"), seg(5, 6.5, 6.62, "短い"),
             seg(6, 7.0, 8.0, "  "), seg(7, 8.0, 9.0, "e", cut=True), seg(8, 11.0, 13.0, "終わりをまたぐ")],
        ]
        rnd = random.Random(20260927)
        for _ in range(12):   # 重ならない乱数の文書(接する・1〜2フレーム・離れる)
            rows, t = [], 0.0
            for i in range(rnd.randint(2, 10)):
                t += rnd.choice([0.0, 0.02, 0.04, 0.4, 1.2])
                a, b = round(t, 2), round(t + rnd.choice([0.12, 0.3, 0.9, 2.16]), 2)
                if b > VIDEO_SEC - 0.5:
                    break
                rows.append(seg(i, a, b, rnd.choice(["はい", "こんばんは", "え"]), cut=rnd.random() < 0.3))
                t = b
            if any(r.get("cutState") != "cut" for r in rows):
                cases.append(rows)
        for fps_text in ("30", "29.97", "60"):
            for n, rows in enumerate(cases):
                with self.subTest(fps=fps_text, n=n):
                    doc = self.doc(rows, fps_text)
                    video = Path(doc["sourcePath"])
                    p_rows, a = self.build(pack.Request(video=video, transcript=self.write_v1(doc), **pack.TRANSCRIPT_ROWS), fps_text)
                    keeps_sec = [(round(x, 3), round(y, 3)) for x, y in pack.summary(p_rows)["keepsSec"]]   # 画面が編集の内容に保存する形
                    fps = p_rows.meta["fps"]
                    edit = tx.sanitize_edit({"sources": [{"fps": list(fps), "duration": VIDEO_SEC}],
                                             "clips": [{"src": 0, "in": x, "out": y} for x, y in keeps_sec]})
                    segs = [dict(r) for r in rows]
                    for r, cut in zip(segs, tx.edit_cut_flags(segs, edit)):   # 保存のときに行の cutState を編集の内容から付け直す
                        r.pop("cutState", None)
                        if cut:
                            r["cutState"] = "cut"
                    self.assertEqual([r.get("cutState") == "cut" for r in segs if r["text"].strip()],
                                     [r.get("cutState") == "cut" for r in rows if r["text"].strip()], "行の印が変わった %r" % rows)
                    p_edit, b = self.build(pack.Request(video=video, transcript=self.write_v1(dict(doc, segments=segs)), keep_pairs=keeps_sec,
                                                        **pack.EDIT_KEEPS), fps_text)
                    self.assertEqual(p_edit.keeps, p_rows.keeps)
                    self.assertSameFiles(a, b)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class KnownFixes(ResolvePackContract):
    """A の範囲の外で、一本化で直った所(旧 resolve_export の不具合)。旧の値と今の値を両方固定しておく"""

    def both(self, doc, fps_text="30"):
        return LEGACY.plan(doc, fps_text), self.current(doc)

    def test_float_error_at_half_frame(self):
        """0.55〜1.45 秒(30fps で 16.5〜43.5 フレーム)。旧は字幕の終わりが、区間の終わり(44)より1フレーム手前だった"""
        old, new = self.both(self.doc([seg(1, 0.25, 0.55, "え"), seg(2, 0.55, 1.45, "はい")]))
        self.assertEqual(old[0], new[0])
        self.assertEqual(old[1], [(0, 9, "え"), (9, 35, "はい")])
        self.assertEqual(new[1], [(0, 9, "え"), (9, 36, "はい")])

    def test_caption_crossing_end_of_video(self):
        old, new = self.both(self.doc([seg(1, 1, 2, "a"), seg(2, 11, 13.5, "終わりをまたぐ")]))
        self.assertEqual(old[0], new[0])
        self.assertEqual(old[1], [(0, 30, "a")])                                  # 旧: 捨てた
        self.assertEqual(new[1], [(0, 30, "a"), (30, 60, "終わりをまたぐ")])      # 今: 終わりで切って残す

    def test_rows_out_of_order(self):
        old, new = self.both(self.doc([seg(1, 4, 5, "後"), seg(2, 0.5, 1.5, "前"), seg(3, 2, 3, "中", cut=True)]))
        self.assertEqual(old[0], new[0])
        self.assertEqual([c[2] for c in old[1]], ["後", "前"])   # 旧: 文書の順(SRT の番号が時刻順でない)
        self.assertEqual([c[2] for c in new[1]], ["前", "後"])

    def test_end_of_video_counted_from_frames(self):
        """29.97fps・12 秒の動画の実際のフレーム数は 359。旧は 12 秒 × 29.97 = 359.64 → 360 まで残した"""
        old, new = self.both(self.doc([seg(1, 10, 12, "最後")], "29.97"), "29.97")
        self.assertEqual(old[0], [(300, 360)])
        self.assertEqual(new[0], [(300, 359)])

    def test_selected_fps_differs_from_video(self):
        """60fps の動画で 30 を選ぶと、旧は 30fps でフレームを数えた(Resolve の元クリップは 60fps で数えるので、半分の位置になった)"""
        d = self.doc([seg(1, 2, 4, "a")], "60")
        self.assertEqual(LEGACY.plan(d, "30")[0], [(60, 120)])
        zp, tmp_dir, _ = resolve_export.create_package(d, "30", row_edge=False)   # 行の端を広げない(fps の数え方だけを見る)
        self.addCleanup(shutil.rmtree, tmp_dir, True)
        with zipfile.ZipFile(zp) as z:
            ip = TP.read_script_plan(z.read("契約_pack/create_resolve_textplus_project.lua").decode("utf-8"))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(120, 240)])

    # 親クラスのテストは、ここでは繰り返さない
    for _n in [n for n in dir(ResolvePackContract) if n.startswith("test_")]:
        locals()[_n] = None
    del _n


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg / ffprobe が無い")
class RowEdgeContract(unittest.TestCase):
    """E. 行から作るカットの端を声の止まる所まで広げる(pack.ROW_EDGE。docs/edit-tool-design.md の 12 ⑥)。広げる前(A の LEGACY)と比べて:
      - 広げる前の残す区間は、広げたあとの残す区間にすべて入っている(削る所が増えない)
      - 端が動くのは上限まで(始まりは前 0.3 秒・終わりは後 0.5 秒。つながった所は除く)
      - カット済の行の時間(残す行と重ならない所)には入らない
      - 字幕の文字と数は同じ(時刻はカット後の位置が変わるので比べない)
      - 設定で広げない(rowEdge false)なら LEGACY と同じ
    声の代わりの音と無音が交互の動画(0.7 秒おき)で、乱数の文書を試す"""
    setUpClass = ResolvePackContract.__dict__["setUpClass"]
    tearDownClass = ResolvePackContract.__dict__["tearDownClass"]
    write_v1 = ResolvePackContract.write_v1

    def gappy(self, fps_text):
        key = "gaps" + fps_text
        if key not in self.videos:
            p = os.path.join(self.tmp, "g%s.mp4" % fps_text.replace(".", "_"))
            expr = "if(lt(mod(t\\,1.4)\\,0.7)\\,0.5*sin(2*PI*440*t)\\,0)"   # 0〜0.7 秒 音 / 0.7〜1.4 無音 …
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=160x90:rate=%s:duration=%d" % (FPS_RATE[fps_text], VIDEO_SEC),
                            "-f", "lavfi", "-i", "aevalsrc=%s:s=44100:d=%d" % (expr, VIDEO_SEC),
                            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-shortest", p], check=True)
            self.videos[key] = p
        return self.videos[key]

    def test_widening_contract(self):
        rnd = random.Random(20260928)
        seen = {"widened": 0, "silence": 0}   # 空振りで通らないように(広がった文書・無音の所で止まった端があったか)
        for fps_text in ("30", "29.97", "60"):
            video = self.gappy(fps_text)
            for n in range(25):
                rows, t = [], rnd.choice([0.0, 0.3])
                for i in range(rnd.randint(1, 12)):
                    t += rnd.choice([0.0, 0.02, 0.1, 0.4, 1.2])
                    a, b = round(t, 2), round(t + rnd.choice([0.12, 0.3, 0.6, 0.9, 2.16]), 2)
                    if b > VIDEO_SEC - 0.5:
                        break
                    rows.append(seg(i, a, b, rnd.choice(["はい", "こんばんは", "え", "  "]), cut=rnd.random() < 0.3))
                    t = b
                if not any(r["text"].strip() and r.get("cutState") != "cut" for r in rows):
                    continue
                doc = {"title": "契約", "sourcePath": video, "whole": True, "duration": VIDEO_SEC, "segments": rows}
                with self.subTest(fps=fps_text, n=n):
                    tr = self.write_v1(doc)
                    req = pack.Request(video=Path(video), transcript=tr, **pack.TRANSCRIPT_ROWS)
                    wide = pack.plan_cut(req, cache=self.cache)
                    narrow = pack.plan_cut(pack.Request(video=Path(video), transcript=tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=None)),
                                           cache=self.cache)
                    self.assertEqual([tuple(k) for k in narrow.keeps], LEGACY.plan(doc, fps_text)[0])
                    fps, total = wide.meta["fps"], wide.meta["total"]
                    f = lambda sec: pack.C.sec_to_frames(sec, fps)   # noqa: E731
                    for a, b in narrow.keeps:
                        self.assertTrue(any(x <= a and b <= y for x, y in wide.keeps), "広げる前の区間 %r が消えた %r" % ((a, b), rows))
                    for x, y in wide.keeps:
                        inside = [(a, b) for a, b in narrow.keeps if x <= a and b <= y]
                        self.assertTrue(inside, "広げる前に無かった区間 %r %r" % ((x, y), rows))
                        self.assertGreaterEqual(x, inside[0][0] - f(0.3), rows)
                        self.assertLessEqual(y, inside[-1][1] + f(0.5), rows)
                    cut_only = pack._cut_row_frames(pack.C.read_transcript(tr)["rows"], fps, total)
                    self.assertEqual(pack.C.subtract(cut_only, [tuple(k) for k in wide.keeps]), pack.C.normalize(cut_only, total),
                                     "カット済の行の時間に入った %r" % rows)
                    self.assertEqual([c[2] for c in wide.cues_out], [c[2] for c in narrow.cues_out])
                    if wide.keeps != narrow.keeps:
                        seen["widened"] += 1
                    ends = {b for _, b in narrow.keeps}
                    seen["silence"] += sum(1 for _, y in wide.keeps if y not in ends and (y - f(0.2)) not in ends)
        self.assertGreater(seen["widened"], 20, seen)
        self.assertGreater(seen["silence"], 5, seen)

    def test_rowedge_false_is_legacy(self):
        d = {"title": "契約", "sourcePath": self.gappy("30"), "whole": True, "duration": VIDEO_SEC,
             "segments": [seg(1, 0.2, 0.5, "a"), seg(2, 1.5, 1.9, "b"), seg(3, 2.0, 2.3, "c", cut=True)]}
        zp, tmp_dir, _ = resolve_export.create_package(d, "30", row_edge=False)
        self.addCleanup(shutil.rmtree, tmp_dir, True)
        with zipfile.ZipFile(zp) as z:
            ip = TP.read_script_plan(z.read("契約_pack/create_resolve_textplus_project.lua").decode("utf-8"))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], LEGACY.plan(d, "30")[0])


class RoundingRule(unittest.TestCase):
    """丸めの規則(四捨五入・0.5 は大きい方へ)。契約の土台なので、ffmpeg が無くても確かめる"""

    def test_ms_to_frames_rounds_half_up(self):
        self.assertEqual(S.ms_to_frames(150, (30, 1)), 5)       # 4.5 -> 5(偶数への丸めなら 4)
        self.assertEqual(S.ms_to_frames(3350, (30, 1)), 101)    # 100.5 -> 101
        self.assertEqual(S.ms_to_frames(50, (30, 1)), 2)        # 1.5 -> 2
        self.assertEqual(S.frames_to_ms(15, (30000, 1001)), 501)   # 500.5 -> 501

    def test_same_as_legacy_on_whisper_grid(self):
        """0.02 秒刻みの時刻では、旧 resolve_export(float で計算)と同じフレームになる"""
        for cs in range(0, 60000, 2):
            for fps_text in ("24", "29.97", "30", "50", "59.94", "60"):   # 25fps は 0.02 秒刻みでも半フレームになる(0.58 秒 = 14.5)
                fps = LEGACY.SUPPORTED_FPS[fps_text]
                self.assertEqual(S.ms_to_frames(cs * 10, (fps.numerator, fps.denominator)),
                                 LEGACY.frames(cs / 100, fps), (cs, fps_text))


if __name__ == "__main__":
    unittest.main()
