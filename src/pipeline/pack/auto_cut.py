# -*- coding: utf-8 -*-
"""カットの計画の部品(read_cut_plan・build_plan・plan_from_keeps・finalize_plan。pack.py が使う)。
パックを書くのは pack.py だけ。単独のコマンド(auto_cut.py)と FCPXML の書き出しは 10-16 のユーザー決定で消した(パックを作る道は入口と ② の CLI src/app/cli.py だけ)。
"""
import datetime
import math
from fractions import Fraction
from pathlib import Path

from . import cut2resolve_core as C

SCHEMA = C.CUT_PLAN_SCHEMA
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
    padded = [(max(0, a - handle), min(total, b + handle)) for a, b, _ in core]   # 余白つきの区間(残す区間と記録の両方に使う)
    records = [{"id": m["id"], "label": m["label"], "selected_frames": [a, b], "keep_with_handles_frames": list(span)}
               for (a, b, m), span in zip(core, padded)]
    return plan_from_keeps(C.normalize(padded, total), meta, records, handle)


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
    """出力フォルダに書く詳細版の cut-plan.json。notes:docs/spec/pipeline.md の共通の約束(tool・createdAt・media)と、
    そのまま入力に戻せる segments(= 最終的に残す区間。余白込みなので segmentsIncludeHandles: true)を足す。
    以前は segments が無く、同じ schema なのに自分で読み直せなかった"""
    fps = meta["fps"]
    keeps = [tuple(x) for x in plan["keep_frames"]]

    def sec(n):
        return round(C.frames_to_sec(n, fps), 6)
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
