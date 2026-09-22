#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve_simple v0.1.2  (シンプル版)

元動画 + カットリスト(.txt) + 字幕(.srt) から、次の3つを <動画名>_edl フォルダに作る。
  <動画名>.edl        残す区間のリスト。Resolve に読み込むとカット済みのタイムラインになる
  <動画名>_cut.srt    カット後の時刻に直した字幕
  友人へ.txt          友人向けの Resolve での開き方

カットリスト: 1行に「開始 終了」(残す区間)。例
    0:05 0:20.5
    1:02 - 1:30      # 区切りは空白 - ~ → など。# 以降はコメント
使い方: 動画・カットリスト・字幕(字幕は省略可)を順不同で指定する。
    python cut2resolve_simple.py 動画.mp4 cuts.txt 字幕.srt
機能を絞ってあります。無音の自動カット・粗編集動画の書き出しなどは cut2resolve.py(フル版)を使う。
"""
import argparse
import sys
from pathlib import Path

import cut2resolve_core as C
import srt2resolve as S


def run(args):
    video, sub, cutfile = C.classify_inputs([Path(p) for p in args.inputs], need_cuts=True)
    for p in (video, sub, cutfile):
        if p is not None and not p.is_file():
            raise C.ToolError(f"ファイルが見つかりません: {p}")
    meta = S.probe(video)
    fps, total = meta["fps"], meta["total"]
    keeps, warns = C.cut_list_to_keeps(C.parse_cut_list(C.read_text_file(cutfile)), fps, total)
    if not keeps:
        raise C.ToolError("カットリストの区間が、動画の長さの範囲に入っていません。")
    cues_out, vanished = None, 0
    if sub:
        cues = S.parse_subs(S.read_sub_file(sub))
        if not cues:
            raise C.ToolError("字幕を1件も読み取れませんでした(SRT/VTT の形式を確認してください)。")
        cues_out, vanished = C.remap_cues(cues, keeps, fps)
    out_dir = Path(args.output) if args.output else video.parent / f"{video.stem}_edl"
    src_start, src_desc, tc_warns = C.resolve_src_start(video, args.src_start_tc)
    files = C.write_pack(out_dir, video, meta, keeps, cues_out, src_start=src_start)

    print(f"動画: {video.name}  {meta['w']}x{meta['h']}  {fps[0] / fps[1]:.3f}fps  "
          f"{total}フレーム({meta['frames_source']})")
    print(f"元動画の開始タイムコード: {src_start}({src_desc})"
          "  ← Resolve の Clip Attributes の Start TC と同じになるはずです")
    print(C.describe_keeps(keeps, fps, total))
    if sub:
        print(f"字幕: {len(cues)}件 -> カット後 {len(cues_out)}件(カットで消えた字幕 {vanished}件)")
    for w in warns + tc_warns + [m for m in meta["warnings"] if "開始タイムコード" not in m] \
            + C.name_warnings(video):
        print("注意: " + w)
    print("出力: " + "\n      ".join(str(p) for p in files.values()))
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="元動画+カットリスト+字幕 -> Resolve 用 EDL(シンプル版)")
    ap.add_argument("inputs", nargs="+", metavar="FILE", help="動画・カットリスト(.txt)・字幕(.srt/.vtt) 順不同")
    ap.add_argument("-o", "--output", help="出力フォルダ(既定: 動画と同じ場所の <動画名>_edl)")
    ap.add_argument("--src-start-tc", default=None,
                    help="元動画の開始タイムコード HH:MM:SS:FF(既定: 動画に埋め込まれた値、無ければ 00:00:00:00)。"
                         "Resolve の Clip Attributes の Start TC と同じ値を指定する")
    ap.add_argument("--version", action="version", version=f"cut2resolve_simple {C.VERSION}")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except C.ToolError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
