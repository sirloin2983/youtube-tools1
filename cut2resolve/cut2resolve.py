#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve v0.4.0  (フル版)

元動画に対して「残す区間」を決め、Resolve に読み込める EDL と、カット後の時刻の字幕を作る。
出力先は <動画名>_pack フォルダ(EDL / 字幕SRT / 友人へ.txt / cut-plan.json / 任意で粗編集の動画・元動画のコピー・FCPXML・Text+パック)。
処理の中身は pack.py(画面 serve.py と共通)。

カットの決め方(組み合わせ可):
  ・カットリスト(.txt または --keep)   残す区間を「開始 終了」で1行ずつ書く。無ければ動画全体が対象
  ・--plan FILE / .json                採用区間(youtube-tools-cut-plan/v1)を残す。前後の余白は --handles
  ・--transcript FILE / .json          文字起こし(youtube-tools-transcript/v1)。字幕はカット済でない行から作り、
                                       「カット済」の行の時間帯を削る(--keep-cut-rows で削らない)
  ・--keep-rows                        文字起こしの残す行だけを残す(行と行の間のすき間は削る)
  ・--drop FILE                        削る区間を同じ形式で書く
  ・--drop-lines 3,5-7                 字幕ファイルの上から N 番目の行の時間帯を削る
  ・--silence                          無音を自動で削る(--noise / --silence-min / --silence-pad で調整)
  ・--min-len / --join-gap             短すぎる区間の除去 / 近い区間のつなぎ合わせ(細切れ防止)

例:
  python cut2resolve.py 動画.mp4 字幕.srt --silence --render
  python cut2resolve.py 動画.mp4 cuts.txt 字幕.srt --dry-run     # 何が残るか表示だけ
  python cut2resolve.py 動画.mp4 動画.transcript.json --silence  # 字幕は文字起こしから、カット済の行と無音を削る
"""
import argparse
import sys
from pathlib import Path

import cut2resolve_core as C
import pack
import resolve_textplus as TP


def build_request(args):
    """引数 → pack.Request(画面の serve.py も同じ Request を作って pack を呼ぶ)"""
    rest, jsons = C.split_json_inputs([Path(p) for p in args.inputs])
    video, sub, cutfile = C.classify_inputs(rest, need_cuts=False)
    transcript = Path(args.transcript) if args.transcript else None
    plan_file = Path(args.plan) if args.plan else None
    for j in jsons:   # 順不同で渡された .json は schema で見分ける(bat へのドラッグ&ドロップ用)
        sc = C.json_schema(j) if j.is_file() else None
        if sc == C.TRANSCRIPT_SCHEMA and transcript is None:
            transcript = j
        elif sc == C.CUT_PLAN_SCHEMA and plan_file is None:
            plan_file = j
        elif sc is None and not j.is_file():
            raise C.ToolError(f"ファイルが見つかりません: {j}")
        else:
            raise C.ToolError(f"{j.name}: 文字起こし(youtube-tools-transcript/v1)でも採用区間(youtube-tools-cut-plan/v1)でもないか、"
                              "同じ種類の JSON が2つあります。")
    if cutfile and args.keep:
        raise C.ToolError("カットリスト(.txt)と --keep は同時に指定できません。")
    keep_file = Path(args.keep) if args.keep else cutfile
    drop_file = Path(args.drop) if args.drop else None
    for p in (video, sub, keep_file, drop_file, transcript, plan_file):
        if p is not None and not p.is_file():
            raise C.ToolError(f"ファイルが見つかりません: {p}")
    if args.keep_rows and not transcript:
        raise C.ToolError("--keep-rows には文字起こし(--transcript)が必要です。")
    bases = [b for b, on in (("list", keep_file), ("plan", plan_file), ("rows", args.keep_rows)) if on]
    if len(bases) > 1:
        raise C.ToolError("残す区間の指定(カットリスト・--plan・--keep-rows)は1つだけにしてください。")
    return pack.Request(
        video=video, sub=sub, transcript=transcript, plan=plan_file, base=bases[0] if bases else "all",
        keep_pairs=C.parse_cut_list(C.read_text_file(keep_file)) if keep_file else None,
        drop_pairs=C.parse_cut_list(C.read_text_file(drop_file)) if drop_file else [],
        drop_lines=C.parse_index_list(args.drop_lines) if args.drop_lines else None,
        handles=args.handles, silence=args.silence, noise=args.noise, silence_min=args.silence_min,
        silence_pad=args.silence_pad, drop_cut_rows=not args.keep_cut_rows, min_len=args.min_len, join_gap=args.join_gap,
        fps=args.fps, frames=args.frames, src_start_tc=args.src_start_tc, rec_start=args.rec_start, reel=args.reel,
        name=args.name, extra_inputs=tuple(p for p in (keep_file, drop_file) if p), edit_media=not args.no_edit_media)


def run(args):
    try:
        textplus_target = TP.parse_target(args.textplus_fps, args.textplus_size)
    except ValueError as e:
        raise C.ToolError(str(e))
    req = build_request(args)
    plan = pack.plan_cut(req, log=lambda m: print(m, flush=True))
    for line in pack.describe(plan):
        print(line)
    if args.dry_run:
        print("(--dry-run: ファイルは作っていません)")
        return 0
    res = pack.build_pack(plan, args.output, render=args.render, copy_video=args.copy_video, fcpxml=args.fcpxml,
                          textplus=args.textplus, textplus_target=textplus_target,
                          force=args.force, crf=args.crf, log=lambda m: print(m, flush=True))
    for w in res["warnings"]:
        print("注意: " + w)
    print("出力: " + "\n      ".join(str(p) for _, p in res["files"]))
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="元動画+カット+字幕 -> Resolve 用 EDL(フル版)")
    ap.add_argument("inputs", nargs="+", metavar="FILE",
                    help="動画・字幕(.srt/.vtt)・カットリスト(.txt)・文字起こし/採用区間(.json) 順不同")
    ap.add_argument("--keep", help="残す区間のファイル(カットリスト .txt の代わり)")
    ap.add_argument("--plan", help="採用区間 JSON(youtube-tools-cut-plan/v1)の区間を残す")
    ap.add_argument("--transcript", help="文字起こし JSON(youtube-tools-transcript/v1)。字幕とカット済の行に使う")
    ap.add_argument("--keep-rows", action="store_true", help="文字起こしの残す行(カット済でない行)だけを残す")
    ap.add_argument("--handles", type=float, default=None,
                    help="--plan / --keep-rows の区間の前後に残す余白(秒)。既定: 文字起こし由来は 0、それ以外は 10")
    ap.add_argument("--keep-cut-rows", action="store_true", help="文字起こしの「カット済」の行を削らない")
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
    ap.add_argument("--fcpxml", action="store_true", help="補助の FCPXML(カット済みのタイムライン+字幕タイトル。実機未確認)も作る")
    ap.add_argument("--textplus", action="store_true", help="動画同梱・Resolve Free用Text+生成スクリプト・復旧タイムラインを含むパックを作る")
    ap.add_argument("--textplus-fps", default=None, help="Text+ を置くプロジェクトの fps(既定 30。24/25/30/50/60)")
    ap.add_argument("--textplus-size", default=None, help="Text+ を置くプロジェクトの解像度(既定 1080x1920。例: 1920x1080)")
    ap.add_argument("--no-edit-media", action="store_true",
                    help="動画を同梱するとき、切り抜きスタジオの余白つき素材(<動画名>.edit.json)があっても元の動画を入れる")
    ap.add_argument("--force", action="store_true", help="既存の出力ファイルを上書きする(入力ファイルとの衝突は不可)")
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
