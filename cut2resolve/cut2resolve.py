#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve v0.1.2  (フル版)

元動画に対して「残す区間」を決め、Resolve に読み込める EDL と、カット後の時刻の字幕を作る。
出力先は <動画名>_pack フォルダ(EDL / 字幕SRT / 友人へ.txt / 任意で粗編集の動画・元動画のコピー)。

カットの決め方(組み合わせ可):
  ・カットリスト(.txt または --keep)   残す区間を「開始 終了」で1行ずつ書く。無ければ動画全体が対象
  ・--drop FILE                        削る区間を同じ形式で書く
  ・--drop-lines 3,5-7                 字幕ファイルの上から N 番目の行の時間帯を削る
  ・--silence                          無音を自動で削る(--noise / --silence-min / --silence-pad で調整)
  ・--min-len / --join-gap             短すぎる区間の除去 / 近い区間のつなぎ合わせ(細切れ防止)

例:
  python cut2resolve.py 動画.mp4 字幕.srt --silence --render
  python cut2resolve.py 動画.mp4 cuts.txt 字幕.srt --dry-run     # 何が残るか表示だけ
"""
import argparse
import sys
from pathlib import Path

import cut2resolve_core as C
import srt2resolve as S


def run(args):
    video, sub, cutfile = C.classify_inputs([Path(p) for p in args.inputs], need_cuts=False)
    if cutfile and args.keep:
        raise C.ToolError("カットリスト(.txt)と --keep は同時に指定できません。")
    keep_file = Path(args.keep) if args.keep else cutfile
    for p in (video, sub, keep_file, Path(args.drop) if args.drop else None):
        if p is not None and not p.is_file():
            raise C.ToolError(f"ファイルが見つかりません: {p}")

    meta = S.probe(video, args.fps, args.frames)
    fps, total = meta["fps"], meta["total"]
    src_start, src_desc, tc_warns = C.resolve_src_start(video, args.src_start_tc)
    warns = [m for m in meta["warnings"] if "開始タイムコード" not in m] + tc_warns + C.name_warnings(video)

    base = [(0, total)]
    if keep_file:
        base, w = C.cut_list_to_keeps(C.parse_cut_list(C.read_text_file(keep_file)), fps, total)
        warns += w
        if not base:
            raise C.ToolError("カットリストの区間が、動画の長さの範囲に入っていません。")
    drops = []
    if args.drop:
        d, w = C.cut_list_to_keeps(C.parse_cut_list(C.read_text_file(args.drop)), fps, total)
        drops += d
        warns += w
    cues = None
    if sub:
        cues = S.parse_subs(S.read_sub_file(sub))
        if not cues:
            raise C.ToolError("字幕を1件も読み取れませんでした(SRT/VTT の形式を確認してください)。")
    if args.drop_lines:
        if not cues:
            raise C.ToolError("--drop-lines には字幕ファイルが必要です。")
        idx = C.parse_index_list(args.drop_lines)
        over = sorted(i for i in idx if i > len(cues))
        if over:
            warns.append(f"--drop-lines: 字幕は {len(cues)} 件しかないため、{over} は無視しました。")
        for i in sorted(idx):
            if i <= len(cues):
                a, b, _ = cues[i - 1]
                cs = S.ms_to_frames(a, fps)
                drops.append((cs, max(S.ms_to_frames(b, fps), cs + 1)))
    if args.silence:
        print("無音を検出しています…", flush=True)
        sil = C.detect_silence(video, fps, total, args.noise, args.silence_min, args.silence_pad)
        drops += sil
        print(f"無音区間: {len(sil)}か所を削ります。", flush=True)
    if not (keep_file or args.drop or args.drop_lines or args.silence):
        warns.append("カットの指定がありません。動画全体を1区間として出力します。")

    keeps = C.subtract(base, drops)
    keeps = C.merge_close(keeps, C.sec_to_frames(args.join_gap, fps))
    keeps = C.drop_short(keeps, max(1, C.sec_to_frames(args.min_len, fps)))
    if not keeps:
        raise C.ToolError("残る区間がありません。カットの指定(--silence の感度・--min-len など)を見直してください。")

    cues_out, vanished = (None, 0)
    if cues:
        cues_out, vanished = C.remap_cues(cues, keeps, fps)

    print(f"動画: {video.name}  {meta['w']}x{meta['h']}  {fps[0] / fps[1]:.3f}fps  "
          f"{total}フレーム({meta['frames_source']})")
    print(f"映像: {meta['codec']} / {meta['pix_fmt']}")
    print(f"元動画の開始タイムコード: {src_start}({src_desc})"
          "  ← Resolve の Clip Attributes の Start TC と同じになるはずです")
    print(C.describe_keeps(keeps, fps, total))
    if cues is not None:
        print(f"字幕: {len(cues)}件 -> カット後 {len(cues_out)}件(カットで消えた字幕 {vanished}件)")
    for w in warns:
        print("注意: " + w)
    if args.dry_run:
        print("(--dry-run: ファイルは作っていません)")
        return 0

    out_dir = Path(args.output) if args.output else video.parent / f"{video.stem}_pack"
    out_dir.mkdir(parents=True, exist_ok=True)
    rough = None
    if args.render:
        rough = out_dir / f"{video.stem}_roughcut.mp4"
        if rough.resolve() == video.resolve():
            raise C.ToolError("粗編集の書き出し先が元動画と同じです。-o で別のフォルダを指定してください。")
        print("粗編集の動画を書き出しています…(時間がかかります)", flush=True)
        C.render_rough_cut(video, keeps, fps, bool(meta["audio"]), rough, args.crf)
    files = C.write_pack(out_dir, video, meta, keeps, cues_out, args.reel, args.rec_start,
                         src_start, rough, args.name)
    if rough:
        files["roughcut"] = rough
    if args.copy_video:
        files["video"] = C.copy_video(video, out_dir)
    print("出力: " + "\n      ".join(str(p) for p in files.values()))
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="元動画+カット+字幕 -> Resolve 用 EDL(フル版)")
    ap.add_argument("inputs", nargs="+", metavar="FILE", help="動画・字幕(.srt/.vtt)・カットリスト(.txt) 順不同")
    ap.add_argument("--keep", help="残す区間のファイル(カットリスト .txt の代わり)")
    ap.add_argument("--drop", help="削る区間のファイル(1行に「開始 終了」)")
    ap.add_argument("--drop-lines", help="削る字幕の行(字幕ファイルの上から何番目か。例: 3,5-7)")
    ap.add_argument("--silence", action="store_true", help="無音区間を自動で削る")
    ap.add_argument("--noise", type=float, default=-35.0, help="無音とみなす音量 dB(既定 -35。大きくすると多く削る)")
    ap.add_argument("--silence-min", type=float, default=0.6, help="この秒数以上続く無音だけ削る(既定 0.6)")
    ap.add_argument("--silence-pad", type=float, default=0.15, help="話の前後に残す秒数(既定 0.15)")
    ap.add_argument("--min-len", type=float, default=0.3, help="これより短い残り区間は捨てる(既定 0.3秒)")
    ap.add_argument("--join-gap", type=float, default=0.0, help="この秒数以下の隙間ならつなぐ(既定 0)")
    ap.add_argument("--render", action="store_true", help="残す区間をつないだ粗編集の動画(H.264 mp4)も作る")
    ap.add_argument("--crf", type=int, default=18, help="粗編集の画質(小さいほど高画質。既定 18)")
    ap.add_argument("--copy-video", action="store_true", help="元動画を出力フォルダにコピーする(大きいので注意)")
    ap.add_argument("--dry-run", action="store_true", help="残る区間を表示するだけで、ファイルは作らない")
    ap.add_argument("-o", "--output", help="出力フォルダ(既定: 動画と同じ場所の <動画名>_pack)")
    ap.add_argument("--name", help="EDL のタイトル(既定: 動画名)")
    ap.add_argument("--reel", default="AX", help="EDL のリール名(英数字8文字まで。既定 AX)")
    ap.add_argument("--rec-start", default="01:00:00:00", help="タイムラインの開始タイムコード(既定 01:00:00:00)")
    ap.add_argument("--src-start-tc", default=None,
                    help="元動画の開始タイムコード HH:MM:SS:FF(既定: 動画に埋め込まれた値、無ければ 00:00:00:00)")
    ap.add_argument("--fps", help="フレームレートを指定(通常は自動)")
    ap.add_argument("--frames", type=int, help="動画のフレーム数を指定(通常は自動)")
    ap.add_argument("--version", action="version", version=f"cut2resolve {C.VERSION}")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except C.ToolError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
