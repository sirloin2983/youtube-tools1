#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文字起こし/切り抜きスタジオ向け自動カット計画(v0.1.0)。

採用区間JSON + 元動画 + 任意のSRTから、編集余白付きのResolve素材一式を作る。
カット判断とResolve形式への書き出しを分離してあり、後で文字起こしUIから
build_plan()/write_package()を直接呼び出せる。
"""
import argparse
import datetime
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import cut2resolve_core as C
import srt2resolve as S

VERSION = "0.1.0"
SCHEMA = "youtube-tools-cut-plan/v1"
DEFAULT_HANDLES = 10.0   # スタジオの採用区間のような長い区間の既定(前後10秒の編集余白)


def read_cut_plan(path):
    """youtube-tools-cut-plan/v1 を読む -> {"segments": [...], "media": {...}, "tool": 書いたツール名,
    "fineGrained": 行単位の細かい区間か, "includesHandles": 区間に余白が含まれているか}。
    segments は status が adopted(省略時も adopted)の区間だけ: {"id","label","start_seconds","end_seconds"}。
    cut2resolve が以前に書いた詳細版(segments が無く keep_frames と frame_rate がある)も、残す区間として読む"""
    data = C.read_json_file(path, "採用区間JSON(cut-plan)")
    try:
        C.check_schema(data, SCHEMA, "採用区間JSON(youtube-tools-cut-plan/v1)")
    except C.ToolError as e:
        raise C.ToolError(f"{e} JSON schema は {SCHEMA!r} を指定してください。")
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    tool_name = str(tool.get("name") or "")
    marks = data.get("segments")
    includes = data.get("segmentsIncludeHandles") is True
    if marks is None and isinstance(data.get("keep_frames"), list) and data.get("frame_rate"):
        marks = _segments_from_keep_frames(data)
        includes = True
    if not isinstance(marks, list) or not marks:
        raise C.ToolError("segments に1件以上の採用区間が必要です。")
    out = []
    fine = False
    for i, m in enumerate(marks, 1):
        if not isinstance(m, dict):
            raise C.ToolError(f"segments[{i}] はオブジェクトではありません。")
        if m.get("status", "adopted") != "adopted":
            continue
        a, b = C.num(m.get("start")), C.num(m.get("end"))
        if a is None or b is None:
            raise C.ToolError(f"segments[{i}] に数値の start/end (秒) が必要です。")
        if not (0 <= a < b):
            raise C.ToolError(f"segments[{i}] の start/end が不正です。")
        fine = fine or isinstance(m.get("lines"), list)
        out.append({"id": str(m.get("id", i)), "label": str(m.get("label", "")),
                    "start_seconds": a, "end_seconds": b})
    if not out:
        raise C.ToolError("採用済み(status=adopted)の区間がありません。")
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    # 文字起こし由来(行単位の短い区間がたくさん)かどうか: 書いたツールが文字起こしツール、または区間に行の id(lines)がある
    fine = fine or tool_name == "transcribe-tool"
    return {"segments": out, "media": media, "tool": tool_name, "fineGrained": fine, "includesHandles": includes}


def _segments_from_keep_frames(data):
    try:
        fr = Fraction(str(data["frame_rate"]))
        if fr <= 0:
            raise ValueError
        segs = []
        for i, (a, b) in enumerate(data["keep_frames"], 1):
            segs.append({"id": f"keep-{i:03d}", "start": float(Fraction(int(a)) / fr), "end": float(Fraction(int(b)) / fr)})
        return segs
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        raise C.ToolError("cut-plan.json の keep_frames / frame_rate を読めません。")


def default_handles(doc):
    """編集余白の既定(秒)。文字起こし由来の細かい区間・余白を含んだ区間は 0、それ以外(スタジオの採用区間など)は 10。
    文字起こしの行単位の区間に 10 秒の余白を付けると区間どうしが全部つながり、カット済の行が消えないため"""
    return 0.0 if doc.get("fineGrained") or doc.get("includesHandles") else DEFAULT_HANDLES


def read_selection(path):
    """採用区間の一覧だけ(従来の関数。中身は read_cut_plan)"""
    return read_cut_plan(path)["segments"]


def build_plan(segments, meta, handle_seconds=10.0):
    """秒の採用区間から、フレーム精度の採用/保持/削除プランを作る。"""
    if not math.isfinite(handle_seconds) or handle_seconds < 0:
        raise C.ToolError("--handles は有限の0以上の秒数にしてください。")
    fps, total = meta["fps"], meta["total"]
    handle = C.sec_to_frames(handle_seconds, fps)
    core = []
    for m in segments:
        a = max(0, min(total, C.sec_to_frames(m["start_seconds"], fps)))
        b = max(0, min(total, C.sec_to_frames(m["end_seconds"], fps)))
        if a < b:
            core.append((a, b, m))
    if not core:
        raise C.ToolError("採用区間が動画の長さの範囲にありません。")
    core.sort(key=lambda x: (x[0], x[1]))
    keeps = C.normalize([(max(0, a - handle), min(total, b + handle)) for a, b, _ in core], total)
    removed = removed_between(keeps, total)
    records = []
    for a, b, m in core:
        records.append({"id": m["id"], "label": m["label"], "selected_frames": [a, b],
                        "keep_with_handles_frames": [max(0, a-handle), min(total, b+handle)]})
    return {"schema": SCHEMA, "frame_rate": f"{fps[0]}/{fps[1]}", "source_frames": total,
            "handle_frames": handle, "selected_segments": records,
            "keep_frames": [list(x) for x in keeps], "removed_frames": [list(x) for x in removed]}


def removed_between(keeps, total):
    removed, cur = [], 0
    for a, b in keeps:
        if cur < a:
            removed.append((cur, a))
        cur = b
    if cur < total:
        removed.append((cur, total))
    return removed


def plan_from_keeps(keeps, meta, selected=None, handle_frames=0):
    """build_plan と同じ形の計画を、最終的に残す区間から作る(無音カット・時刻リスト・削る区間を組み合わせた結果など)"""
    fps, total = meta["fps"], meta["total"]
    return {"schema": SCHEMA, "frame_rate": f"{fps[0]}/{fps[1]}", "source_frames": total,
            "handle_frames": handle_frames, "selected_segments": list(selected or []),
            "keep_frames": [list(x) for x in keeps], "removed_frames": [list(x) for x in removed_between(keeps, total)]}


def finalize_plan(plan, video, meta, src_start, copy_video=False, cues_out=None, tool=None):
    """出力フォルダに書く詳細版の cut-plan.json。docs/pipeline.md の共通の約束(tool・createdAt・media)と、
    そのまま入力に戻せる segments(= 最終的に残す区間。余白込みなので segmentsIncludeHandles: true)を足す。
    以前は segments が無く、同じ schema なのに自分で読み直せなかった"""
    fps = meta["fps"]
    keeps = [tuple(x) for x in plan["keep_frames"]]

    def sec(n):
        return round(float(Fraction(n * fps[1], fps[0])), 6)
    doc = dict(plan)
    doc["tool"] = tool or {"name": "cut2resolve", "version": C.VERSION}
    doc["createdAt"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    doc["media"] = {"path": str(Path(video).resolve()), "name": Path(video).name,
                    "durationSec": sec(meta["total"])}
    doc["segments"] = [{"id": f"keep-{i:03d}", "start": sec(a), "end": sec(b), "status": "adopted", "label": ""}
                       for i, (a, b) in enumerate(keeps, 1)]
    doc["segmentsIncludeHandles"] = True
    doc["handleSeconds"] = sec(plan.get("handle_frames") or 0)
    doc["source"] = {"name": Path(video).name, "path_hint": Path(video).name, "copied_into_package": bool(copy_video),
                     "start_timecode": src_start, "width": meta["w"], "height": meta["h"]}
    doc["timeline_frames"] = sum(b - a for a, b in keeps)
    doc["subtitles"] = len(cues_out) if cues_out is not None else None
    order = ["schema", "tool", "createdAt", "media", "segments", "segmentsIncludeHandles", "handleSeconds"]
    return {k: doc[k] for k in order + [k for k in doc if k not in order]}


def build_cut_fcpxml(video, meta, keeps, cues, start_frames=0):
    """Create one editable FCPXML timeline with trimmed source clips and title clips.
    start_frames: 元動画の開始タイムコード(フレーム)。asset の start と asset-clip の start はメディアの時刻で書く
    (Resolve は埋め込みの開始タイムコードで照合する。EDL の v0.1.1 と同じ理由)。
    タイトル(つながったクリップ)の offset は親の asset-clip の中の時刻 = 親の start 基準で書く
    (以前は 0 基準で、2つ目以降のクリップの字幕が親の範囲の外を指していた)。
    text-style-def の id は文書全体で重ならないよう通し番号にする(以前はクリップごとに ts1 から振り直していた)"""
    fps, total = meta["fps"], sum(b-a for a, b in keeps)
    t0 = int(start_frames or 0)

    def ft(n):
        return S.frames_to_time(n, fps)
    w, h = meta["w"], meta["h"]
    fps_label = f"{fps[0]/fps[1]:g}" if fps[1] == 1 else f"{fps[0]/fps[1]:.2f}"
    root = ET.Element("fcpxml", version="1.8")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", name=f"FFVideoFormat{w}x{h}p{fps_label}",
                  frameDuration=ft(1), width=str(w), height=str(h))
    uid = hashlib.md5(str(video.resolve()).encode("utf-8")).hexdigest().upper()
    attr = dict(id="r2", name=video.name, uid=uid,
                src=video.resolve().as_uri(), start=ft(t0), duration=ft(meta["total"]), hasVideo="1", format="r1")
    if meta.get("audio"):
        attr.update(hasAudio="1", audioSources="1", audioChannels=str(meta["audio"][0]),
                    audioRate=str(meta["audio"][1]))
    ET.SubElement(res, "asset", **attr)
    if cues:
        ET.SubElement(res, "effect", id="r3", name="Basic Title",
                      uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti")
    lib = ET.SubElement(root, "library")
    event = ET.SubElement(lib, "event", name="Auto Cut")
    project = ET.SubElement(event, "project", name=video.stem)
    audio = meta.get("audio")
    mono = bool(audio) and audio[0] == 1
    rate = S.SEQ_AUDIO_RATE.get(audio[1] if audio else 48000, "48k")
    seq = ET.SubElement(project, "sequence", format="r1", duration=ft(total), tcStart="0s", tcFormat="NDF",
                        audioLayout="mono" if mono else "stereo", audioRate=rate)
    spine = ET.SubElement(seq, "spine")
    timeline = 0
    n = 0
    for a, b in keeps:
        clip = ET.SubElement(spine, "asset-clip", ref="r2", offset=ft(timeline), name=video.stem,
                             start=ft(t0 + a), duration=ft(b-a), format="r1", tcFormat="NDF")
        local_cues = []
        for cs, ce, text in cues or []:
            gs, ge = timeline, timeline + (b-a)
            x, y = max(cs, gs), min(ce, ge)
            if x >= y:
                continue
            local_cues.append((x-gs, y-gs, text))
        for ls, le, text, lane in S.assign_lanes(local_cues):
            n += 1
            title = ET.SubElement(clip, "title", ref="r3", lane=str(lane), offset=ft(t0 + a + ls),
                                  name=text.replace("\n", " ")[:40], start=ft(round(3600*fps[0]/fps[1])),
                                  duration=ft(le-ls))
            tx = ET.SubElement(title, "text")
            st = ET.SubElement(tx, "text-style", ref=f"ts{n}")
            st.text = text
            definition = ET.SubElement(title, "text-style-def", id=f"ts{n}")
            ET.SubElement(definition, "text-style", font="Yu Gothic", fontSize="56", fontColor="1 1 1 1",
                          bold="1", alignment="center", strokeColor="0 0 0 1", strokeWidth="-4")
        timeline += b-a
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_package(video, out_dir, meta, plan, cues_out, src_start, copy_video=False, force=False, protected=()):
    """protected: 入力ファイル(字幕・採用区間JSON など)。出力と同じパスなら --force でも断る(動画は常に守る)"""
    keeps = [tuple(x) for x in plan["keep_frames"]]
    cut_srt = out_dir / f"{video.stem}_cut.srt"
    edl = out_dir / f"{video.stem}.edl"
    fcpxml = out_dir / f"{video.stem}_cut.fcpxml"
    plan_path = out_dir / "cut-plan.json"
    readme = out_dir / "友人へ.txt"
    video_out = out_dir / video.name
    paths = [edl, fcpxml, plan_path, readme]
    if cues_out is not None:
        paths.append(cut_srt)
    if copy_video:
        paths.append(video_out)
    C.validate_output_paths(paths, force, protected=(video,) + tuple(protected))
    t0 = C.tc_to_frames(src_start, C.nominal_rate(meta["fps"]))   # 書き始める前に確かめる
    out_dir.mkdir(parents=True, exist_ok=True)
    xml_video = C.copy_video(video, out_dir) if copy_video else video
    S.write_text_atomic(edl, C.build_edl(video.stem, video.name, keeps, meta["fps"], bool(meta["audio"]),
                                         src_start=src_start), encoding="utf-8", newline="")
    S.write_text_atomic(fcpxml, build_cut_fcpxml(xml_video, meta, keeps, cues_out, t0), encoding="utf-8", newline="\n")
    if cues_out is not None:
        S.write_text_atomic(cut_srt, S.build_srt(cues_out, meta["fps"]), encoding="utf-8", newline="\n")
    doc = finalize_plan(plan, video, meta, src_start, copy_video, cues_out, tool={"name": "cut2resolve-auto_cut", "version": VERSION})
    S.write_text_atomic(plan_path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    S.write_text_atomic(readme, "DaVinci Resolve 編集パッケージ\n\n"
                        "・EDL: カット可能な編集タイムライン。元動画は名前で照合します。\n"
                        "・FCPXML: カット済みタイムラインと字幕タイトルの取り込み用。動画を移動した場合は再リンクしてください。\n"
                        "・SRT: 字幕トラックとして読み込める予備。\n"
                        "・cut-plan.json: 採用区間、前後ハンドル、削除範囲の復旧用データ。\n"
                        "各採用区間の前後には指定秒数の編集余白を保持しています。\n"
                        "FCPXMLのタイトルがText+になるかはResolve実機で未確認です。確実な字幕トラックはSRTを使ってください。\n",
                        encoding="utf-8-sig", newline="\n")
    return paths


def run(args):
    video = Path(args.video)
    sub = Path(args.subtitle) if args.subtitle else None
    selection_path = Path(args.selection)
    if not video.is_file() or (sub and not sub.is_file()):
        raise C.ToolError("指定した動画または字幕ファイルがありません。")
    if not selection_path.is_file():
        raise C.ToolError(f"採用区間JSONがありません: {selection_path}")
    meta = S.probe(video)
    doc = read_cut_plan(selection_path)
    handles = default_handles(doc) if args.handles is None else args.handles
    plan = build_plan(doc["segments"], meta, handles)
    keeps = [tuple(x) for x in plan["keep_frames"]]
    cues_out = None
    if sub:
        cues = S.parse_subs(S.read_sub_file(sub))
        cues_out, _ = C.remap_cues(cues, keeps, meta["fps"])
    src_start, _, _ = C.resolve_src_start(video, args.src_start_tc, meta)
    out_dir = Path(args.output) if args.output else video.parent / f"{video.stem}_resolve_pack"
    write_package(video, out_dir, meta, plan, cues_out, src_start, args.copy_video, args.force,
                  protected=(sub, selection_path))
    print(f"保持区間 {len(keeps)}件 / 編集余白 {handles:g}秒 / 出力 {out_dir}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="採用区間JSONから編集余白付きのResolveカット計画を生成")
    ap.add_argument("video", help="元動画")
    ap.add_argument("selection", help="採用区間JSON (youtube-tools-cut-plan/v1)")
    ap.add_argument("subtitle", nargs="?", help="任意の字幕 SRT/VTT")
    ap.add_argument("--handles", type=float, default=None,
                    help="各採用区間の前後に残す編集余白(秒)。既定は10。文字起こし由来の行単位の区間と、"
                         "cut2resolve が書いた cut-plan.json(余白込み)は 0")
    ap.add_argument("--src-start-tc", help="埋め込み開始TCが不正な場合の手動指定 HH:MM:SS:FF")
    ap.add_argument("-o", "--output", help="出力先")
    ap.add_argument("--copy-video", action="store_true", help="元動画も出力フォルダへコピー")
    ap.add_argument("--force", action="store_true", help="既存の出力を上書き")
    ap.add_argument("--version", action="version", version=f"auto_cut {VERSION}")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except C.ToolError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
