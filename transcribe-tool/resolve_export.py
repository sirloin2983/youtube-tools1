"""Portable DaVinci Resolve package builder.

The package contains the media, an editable cut plan, recovery FCPXML/SRT files,
and a Resolve 21.1 Python importer that creates a new project and Text+ titles.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET


SUPPORTED_FPS = {"24": Fraction(24), "25": Fraction(25), "29.97": Fraction(30000, 1001),
                 "30": Fraction(30), "50": Fraction(50), "59.94": Fraction(60000, 1001), "60": Fraction(60)}


class ResolveExportError(ValueError):
    pass


def _safe_name(value: str, fallback: str = "resolve-package") -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    return value[:80] or fallback


def _frames(seconds: float, fps: Fraction) -> int:
    return max(0, int(math.floor(float(seconds) * float(fps) + 0.5)))


def _seconds(frames: int, fps: Fraction) -> float:
    return float(Fraction(frames, 1) / fps)


def _fcpx_time(frames: int, fps: Fraction) -> str:
    value = Fraction(frames, 1) / fps
    return "%ds" % value.numerator if value.denominator == 1 else "%d/%ds" % (value.numerator, value.denominator)


def _srt_time(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def discover_edit_media(source_path: str) -> dict:
    """Return clip-studio handle metadata, or a safe no-handle fallback."""
    source = os.path.realpath(source_path)
    stem, _ = os.path.splitext(source)
    sidecar = stem + ".edit.json"
    if os.path.isfile(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                meta = json.load(f)
            media = os.path.realpath(os.path.join(os.path.dirname(sidecar), str(meta.get("media") or "")))
            if os.path.isfile(media) and os.path.commonpath([os.path.dirname(sidecar), media]) == os.path.dirname(sidecar):
                return {"path": media, "selectionIn": max(0.0, float(meta.get("selectionIn") or 0)),
                        "handleBefore": max(0.0, float(meta.get("handleBefore") or 0)),
                        "handleAfter": max(0.0, float(meta.get("handleAfter") or 0)), "sidecar": sidecar}
        except (OSError, ValueError, TypeError):
            pass
    return {"path": source, "selectionIn": 0.0, "handleBefore": 0.0, "handleAfter": 0.0, "sidecar": ""}


def _kept_ranges(segments: list[dict], base: float, media_duration: float, fps: Fraction) -> list[dict]:
    raw = []
    for seg in segments:
        if seg.get("cutState") == "cut" or not str(seg.get("text") or "").strip():
            continue
        a = max(0.0, float(seg.get("start") or 0) - base)
        b = min(media_duration, float(seg.get("end") or 0) - base)
        if b > a:
            raw.append([_frames(a, fps), _frames(b, fps)])
    raw.sort()
    merged = []
    for a, b in raw:
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out, record = [], 0
    for i, (a, b) in enumerate(merged, 1):
        if b <= a:
            continue
        out.append({"id": "cut-%03d" % i, "sourceStartFrame": a, "sourceEndFrame": b,
                    "recordStartFrame": record, "recordEndFrame": record + b - a})
        record += b - a
    return out


def _timeline_position(source_seconds: float, cuts: list[dict], fps: Fraction) -> float | None:
    sf = _frames(source_seconds, fps)
    for cut in cuts:
        if cut["sourceStartFrame"] <= sf < cut["sourceEndFrame"]:
            return _seconds(cut["recordStartFrame"] + sf - cut["sourceStartFrame"], fps)
    return None


def build_plan(doc: dict, fps_text: str = "30") -> dict:
    if fps_text not in SUPPORTED_FPS:
        raise ResolveExportError("対応していないフレームレートです")
    source = str(doc.get("sourcePath") or "")
    if not os.path.isfile(source):
        raise ResolveExportError("元の動画が見つかりません")
    fps = SUPPORTED_FPS[fps_text]
    edit = discover_edit_media(source)
    base = float(doc.get("start") or 0) if not doc.get("whole", True) else 0.0
    doc_duration = float(doc.get("duration") or 0)
    if doc_duration <= 0:
        doc_duration = max([float(s.get("end") or 0) for s in doc.get("segments") or []] + [0.0]) - base
    sidecar_handles = bool(edit["sidecar"])
    source_offset = edit["selectionIn"] if sidecar_handles else (base if not doc.get("whole", True) else 0.0)
    handle_before = edit["handleBefore"] if sidecar_handles else (min(10.0, source_offset) if not doc.get("whole", True) else 0.0)
    handle_after = edit["handleAfter"] if sidecar_handles else (10.0 if not doc.get("whole", True) else 0.0)
    media_duration = source_offset + max(0.0, doc_duration)
    shifted = []
    for seg in doc.get("segments") or []:
        one = dict(seg)
        one["start"] = source_offset + max(0.0, float(seg.get("start") or 0) - base)
        one["end"] = source_offset + max(0.0, float(seg.get("end") or 0) - base)
        shifted.append(one)
    cuts = _kept_ranges(shifted, 0.0, media_duration, fps)
    if not cuts:
        raise ResolveExportError("残す区間がありません。カット指定を確認してください")
    captions = []
    for seg in shifted:
        if seg.get("cutState") == "cut" or not str(seg.get("text") or "").strip():
            continue
        start = _timeline_position(float(seg["start"]), cuts, fps)
        end_probe = max(float(seg["start"]), float(seg["end"]) - 1.0 / float(fps))
        end = _timeline_position(end_probe, cuts, fps)
        if start is None or end is None:
            continue
        end += 1.0 / float(fps)
        if end > start:
            captions.append({"id": str(seg.get("id") or ""), "startFrame": _frames(start, fps),
                             "endFrame": max(_frames(start, fps) + 1, _frames(end, fps)),
                             "text": str(seg.get("text") or "").strip()})
    return {"schema": "resolve-cut-plan/v1", "title": str(doc.get("title") or "無題"), "fps": fps_text,
            "media": {"file": "media/" + os.path.basename(edit["path"]), "originalName": os.path.basename(edit["path"]),
                      "selectionInSeconds": source_offset, "handleBeforeSeconds": handle_before,
                      "handleAfterSeconds": handle_after, "hasEditHandles": sidecar_handles or not doc.get("whole", True)},
            "cuts": cuts, "captions": captions, "durationFrames": cuts[-1]["recordEndFrame"],
            "sourceTimeline": {"startFrame": _frames(max(0.0, source_offset - handle_before), fps),
                               "endFrame": _frames(media_duration + handle_after, fps)},
            "_mediaPath": edit["path"]}


def _build_srt(plan: dict) -> str:
    fps = SUPPORTED_FPS[plan["fps"]]
    rows = []
    for i, cap in enumerate(plan["captions"], 1):
        rows.append("%d\n%s --> %s\n%s\n" % (i, _srt_time(_seconds(cap["startFrame"], fps)),
                                               _srt_time(_seconds(cap["endFrame"], fps)), cap["text"]))
    return "\n".join(rows)


def _build_fcpxml(plan: dict) -> bytes:
    fps = SUPPORTED_FPS[plan["fps"]]
    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", id="r1", name="FFVideoFormat", frameDuration=_fcpx_time(1, fps))
    ET.SubElement(resources, "asset", id="r2", name=plan["media"]["originalName"], src="file://./" + plan["media"]["file"],
                  start="0s", duration=_fcpx_time(plan["sourceTimeline"]["endFrame"], fps), hasVideo="1", hasAudio="1")
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Transcribe Tool")
    project = ET.SubElement(event, "project", name=plan["title"])
    sequence = ET.SubElement(project, "sequence", format="r1", duration=_fcpx_time(plan["durationFrames"], fps), tcStart="0s", tcFormat="NDF")
    spine = ET.SubElement(sequence, "spine")
    for cut in plan["cuts"]:
        ET.SubElement(spine, "asset-clip", ref="r2", name=plan["media"]["originalName"],
                      offset=_fcpx_time(cut["recordStartFrame"], fps), start=_fcpx_time(cut["sourceStartFrame"], fps),
                      duration=_fcpx_time(cut["sourceEndFrame"] - cut["sourceStartFrame"], fps))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _importer_script() -> str:
    return r'''#!/usr/bin/env python3
import json, os, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN_PATH = os.path.join(HERE, "cut-plan.json")

def tc(frame, fps):
    fps_i = round(fps)
    frame = max(0, int(frame))
    return "%02d:%02d:%02d:%02d" % (frame // (fps_i*3600), frame // (fps_i*60) % 60, frame // fps_i % 60, frame % fps_i)

def main():
    with open(PLAN_PATH, encoding="utf-8") as f: plan = json.load(f)
    try:
        import DaVinciResolveScript as dvr
        resolve = dvr.scriptapp("Resolve")
    except Exception:
        resolve = globals().get("resolve")
    if not resolve: raise RuntimeError("DaVinci Resolveに接続できません。Resolveを起動してから再実行してください")
    pm = resolve.GetProjectManager()
    base = "Transcribe_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in plan["title"])[:40]
    name, n = base, 2
    while pm.LoadProject(name): name, n = base + "_" + str(n), n + 1
    project = pm.CreateProject(name)
    if not project: raise RuntimeError("新規プロジェクトを作成できませんでした")
    project.SetSettings({"timelineFrameRate": str(plan["fps"]), "timelinePlaybackFrameRate": str(plan["fps"])})
    pool = project.GetMediaPool()
    media_path = os.path.normpath(os.path.join(HERE, plan["media"]["file"]))
    clips = pool.ImportMedia([{"FilePath": media_path}])
    if not clips: raise RuntimeError("素材を読み込めませんでした: " + media_path)
    clip = clips[0]
    timeline = pool.CreateEmptyTimeline("CUT_TextPlus")
    project.SetCurrentTimeline(timeline)
    entries = [{"mediaPoolItem": clip, "startFrame": c["sourceStartFrame"], "endFrame": c["sourceEndFrame"]-1}
               for c in plan["cuts"]]
    items = pool.AppendToTimeline(entries)
    if not items or len(items) != len(entries): raise RuntimeError("カットをタイムラインへ配置できませんでした")
    timeline.AddTrack("video")
    timeline_base = int(timeline.GetStartFrame())
    title_report = []
    for cap in plan["captions"]:
        title_start = timeline_base + cap["startFrame"]
        title_end = timeline_base + cap["endFrame"]
        timeline.SetCurrentTimecode(tc(title_start, float(plan["fps"])))
        timeline.SetMarkInOut(title_start, title_end-1, "video")
        item = timeline.InsertFusionTitleIntoTimeline("Text+")
        timeline.ClearMarkInOut("video")
        if not item:
            title_report.append({"id": cap["id"], "ok": False, "reason": "Text+ insert failed"}); continue
        comp = item.GetFusionCompByIndex(1)
        tools = comp.GetToolList(False, "TextPlus") if comp else {}
        tool = next(iter(tools.values()), None) if tools else None
        if tool: tool.SetInput("StyledText", cap["text"])
        title_report.append({"id": cap["id"], "ok": bool(tool), "start": item.GetStart(), "end": item.GetEnd(),
                             "expectedStart": title_start, "expectedEnd": title_end})
    source = pool.CreateEmptyTimeline("SOURCE_WITH_HANDLES")
    project.SetCurrentTimeline(source)
    pool.AppendToTimeline([{"mediaPoolItem": clip, "startFrame": plan["sourceTimeline"]["startFrame"],
                            "endFrame": plan["sourceTimeline"]["endFrame"]-1}])
    project.SetCurrentTimeline(timeline)
    report = {"project": name, "cuts": len(items), "captions": len(title_report), "textPlus": title_report,
              "media": media_path, "hasEditHandles": plan["media"]["hasEditHandles"]}
    with open(os.path.join(HERE, "resolve-import-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    pm.SaveProject()
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    try: main()
    except Exception:
        traceback.print_exc()
        raise
'''


def _installer_script() -> str:
    return r"""#!/usr/bin/env python3
import os
from pathlib import Path

package = Path(__file__).resolve().parent
appdata = Path(os.environ["APPDATA"])
scripts_root = appdata / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts"
edit_scripts = scripts_root / "Edit"
config_dir = appdata / "TranscribeResolve"
edit_scripts.mkdir(parents=True, exist_ok=True)
config_dir.mkdir(parents=True, exist_ok=True)
(config_dir / "package.txt").write_text(str(package), encoding="utf-8")
wrapper = '''import os\nfrom pathlib import Path\nconfig = Path(os.environ["APPDATA"]) / "TranscribeResolve" / "package.txt"\npackage = Path(config.read_text(encoding="utf-8").strip())\nscript = package / "create_resolve_project.py"\nnamespace = {"__file__": str(script), "__name__": "__main__", "resolve": globals().get("resolve")}\nexec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)\n'''
(edit_scripts / "Transcribe Resolve Import.py").write_text(wrapper, encoding="utf-8")
old_wrapper = scripts_root / "Utility" / "Transcribe Resolve Import.py"
if old_wrapper.exists():
    old_wrapper.unlink()
print("INSTALLED")
"""


def _launcher() -> str:
    return r'''@echo off
chcp 65001 >nul
set "RPY=C:\Program Files\Blackmagic Design\DaVinci Resolve\ResolvePython\ResolvePython.exe"
if not exist "%RPY%" (
  echo DaVinci Resolve 21.1以降のResolvePythonが見つかりません。
  pause
  exit /b 1
)
"%RPY%" "%~dp0install_resolve_script.py"
if errorlevel 1 pause
echo.
echo 登録しました。DaVinci Resolveを起動し直してください。
echo その後「ワークスペース」→「スクリプト」→「Edit」→「Transcribe Resolve Import」を選びます。
pause
'''


def _readme(plan: dict) -> str:
    handle = "前後の編集余白あり" if plan["media"]["hasEditHandles"] else "編集余白なし（旧データのため外側へ延長不可）"
    return f"""DaVinci Resolve Free 21.1 引き渡しパッケージ

使い方
1. zipを展開します（フォルダはどこへ移動しても構いません）。
2. 「Resolveに登録.bat」をダブルクリックします（パッケージを移動した場合も、もう一度実行します）。
3. DaVinci Resolveを起動し直します。
4. 「ワークスペース」→「スクリプト」→「Edit」→「Transcribe Resolve Import」を選びます。
5. CUT_TextPlus が編集用、SOURCE_WITH_HANDLES が削除部分の復旧用です。

素材状態: {handle}
- CUT_TextPlusの映像・音声は同じクリップとして配置され、トリムを動かせます。
- Text+は各字幕が個別クリップです。文章・時間・スタイルをResolveで変更できます。
- 素材がオフラインになった場合は、メディアプールで右クリック→「選択したクリップを再リンク」し、mediaフォルダを1回指定します。
- timeline.fcpxml、subtitles.srt、cut-plan.jsonは復旧・他ソフト用です。
"""


def create_package(doc: dict, fps_text: str = "30") -> tuple[str, str, dict]:
    plan = build_plan(doc, fps_text)
    media_path = plan.pop("_mediaPath")
    tmp_dir = tempfile.mkdtemp(prefix="resolve-package-")
    zip_path = os.path.join(tmp_dir, _safe_name(plan["title"]) + "-resolve.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            z.write(media_path, plan["media"]["file"])
            z.writestr("cut-plan.json", json.dumps(plan, ensure_ascii=False, indent=2))
            z.writestr("timeline.fcpxml", _build_fcpxml(plan))
            z.writestr("subtitles.srt", _build_srt(plan).encode("utf-8-sig"))
            z.writestr("create_resolve_project.py", _importer_script().encode("utf-8"))
            z.writestr("install_resolve_script.py", _installer_script().encode("utf-8"))
            z.writestr("Resolveに登録.bat", _launcher().encode("utf-8-sig"))
            z.writestr("はじめに.txt", _readme(plan).encode("utf-8-sig"))
        return zip_path, tmp_dir, plan
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
