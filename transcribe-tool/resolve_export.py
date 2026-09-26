"""DaVinci Resolve への受け渡し(文字起こしツールの「Resolveパッケージ(zip)をダウンロード」)と、「残す行」の規則。

パックの中身は cut2resolve の pack.py で作る(2026-09-26 一本化。以前はここに別の実装があり、Python の取り込みスクリプトで
新しいプロジェクトを作っていた)。zip の中身は cut2resolve の Text+ パックと同じ:
  動画(media/。スタジオの余白つき素材があればそれ)・Text+ を作る Lua と登録用の bat・友人へ.txt・EDL・SRT・cut-plan.json
残す区間の決め方は pack.TRANSCRIPT_ROWS(行の時間だけ・短い行も残す・1フレームの隙間はつなぐ)。
同じ入力から同じ中身になることは tools/test_resolve_pack_contract.py が確かめる。

このファイルに残しているもの: 「残す行」の規則(is_kept / kept_spans)と SRT の書式。pipeline_io(cut-plan/v1・SRT の保存)も使う。
cut2resolve の部品は create_package を呼んだときに初めて読み込む(文字起こしの他の機能は cut2resolve が無くても動く)。
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


TEXTPLUS_FPS = ("24", "25", "30", "50", "60")          # Text+ を置くプロジェクトの fps(cut2resolve の resolve_textplus.TARGET_FPS)
TEXTPLUS_SIZES = ("1080x1920", "1920x1080")             # 縦(ショート)・横


class ResolveExportError(ValueError):
    pass


def _safe_name(value: str, fallback: str = "resolve-package") -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    return value[:80] or fallback


def srt_time(seconds: float) -> str:
    """SRT の時刻(HH:MM:SS,mmm)。画面の書き出し(index.html の tcode)と同じく、ミリ秒は四捨五入(0.5 は切り上げ)。"""
    ms = max(0, int(math.floor(float(seconds) * 1000 + 0.5)))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


_srt_time = srt_time   # 旧名(互換のため残す)


def srt_text(cues) -> str:
    """[(開始秒, 終了秒, 文章)] → SRT の本文。番号は1から。ブロックの間は空行1つ、末尾は改行1つ
    (画面の書き出し・動画の隣への保存が、同じ書式になるよう1か所にまとめる)。"""
    return "\n".join("%d\n%s --> %s\n%s\n" % (i, srt_time(a), srt_time(b), text) for i, (a, b, text) in enumerate(cues, 1))


def is_kept(seg: dict) -> bool:
    """この行を「残す」か。画面の「カット済」(cutState == "cut")の行と、文字が空の行は残さない。
    cut-plan/v1(動画の隣に保存)がこの規則を使う。cut2resolve の row_is_kept も同じ規則(契約テストが確かめる)。"""
    return seg.get("cutState") != "cut" and bool(str(seg.get("text") or "").strip())


def kept_spans(segments: list[dict]) -> list[dict]:
    """残す区間(秒)。is_kept の行の時間を、重なる・接する(前の終わり >= 次の始まり)ものどうしで1つにまとめる。
    行と行の間のすき間(無音など)は残さない。
    戻り値: [{"start", "end", "segments": [まとめた元の行, ...]}](開始時刻の順)。時刻の基準は渡した行のまま。"""
    items = []
    for seg in segments:
        if not isinstance(seg, dict) or not is_kept(seg):
            continue
        try:
            a, b = float(seg.get("start") or 0), float(seg.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(a) and math.isfinite(b) and b > a:
            items.append((a, b, seg))
    items.sort(key=lambda x: (x[0], x[1]))
    out = []
    for a, b, seg in items:
        if out and a <= out[-1]["end"]:
            out[-1]["end"] = max(out[-1]["end"], b)
            out[-1]["segments"].append(seg)
        else:
            out.append({"start": a, "end": b, "segments": [seg]})
    return out


# ---------------------------------------------------------------- パック(cut2resolve の pack.py で作る)

def cut2resolve_dir() -> str | None:
    """cut2resolve のフォルダ。環境変数 YTT_CUT2RESOLVE_DIR(一時フォルダに写して動かすテスト用)→ このフォルダの隣。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("YTT_CUT2RESOLVE_DIR"), os.path.join(os.path.dirname(here), "cut2resolve")):
        if d and os.path.isfile(os.path.join(d, "pack.py")):
            return os.path.abspath(d)
    return None


def _load_pack():
    """cut2resolve の pack と resolve_textplus。入口の中では取り込み済みのものをそのまま使う。
    単独で起動したときは cut2resolve のフォルダを sys.path の末尾に足す(先頭に足すと、同じ名前の serve.py などを隠してしまうため)。"""
    if "pack" not in sys.modules:
        d = cut2resolve_dir()
        if not d:
            raise ResolveExportError("cut2resolve のフォルダが見つかりません(文字起こしツールの隣に cut2resolve が必要です)")
        if d not in sys.path:
            sys.path.append(d)
    try:
        import pack
        import resolve_textplus
    except ImportError as e:
        raise ResolveExportError("cut2resolve の部品を読み込めません: %s" % e)
    return pack, resolve_textplus


_DRAFT_CACHE = None   # pack.Cache(動画の情報(ffprobe)を覚える。同じ動画を開き直しても調べ直さない)


def edit_draft(doc: dict, version: str = "") -> dict:
    """「編集」のカットのたたき台(開いたときの下書き・「行から」)と、動画の fps・長さ(docs/edit-tool-design.md の 4)。
    残す区間は pack.TRANSCRIPT_ROWS(今の「カットとパック」・zip・入口のまとめて実行と同じ規則。ここに規則を書かない)。
    文字起こしの一時ファイルは一時フォルダに作る(開いただけで動画の隣にファイルを増やさない)。残す行が無ければ動画全体。
    -> {"fps": [n, d], "durationSec", "keepsSec": [[開始, 終了], ...], "base": "rows" | "all", "warnings"}"""
    import pipeline_io
    global _DRAFT_CACHE
    source = str(doc.get("sourcePath") or "")
    if not source or not os.path.isfile(source):
        raise ResolveExportError("元の動画が見つかりません")
    pack, _tp = _load_pack()
    if _DRAFT_CACHE is None:
        _DRAFT_CACHE = pack.Cache(size=16)
    try:
        meta = _DRAFT_CACHE.probe(Path(source))
    except pack.ToolError as e:
        raise ResolveExportError(str(e))
    fps, total = meta["fps"], meta["total"]
    dur = round(total * fps[1] / fps[0], 6)
    out = {"fps": [int(fps[0]), int(fps[1])], "durationSec": dur, "keepsSec": [[0.0, dur]], "base": "all", "warnings": []}
    if not any(is_kept(g) for g in doc.get("segments") or [] if isinstance(g, dict)):
        return out
    tmp_dir = tempfile.mkdtemp(prefix="edit-draft-")
    try:
        tpath = os.path.join(tmp_dir, "input.transcript.json")
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(pipeline_io.build_transcript_v1(doc, version), f, ensure_ascii=False)
        try:
            plan = pack.plan_cut(pack.Request(video=Path(source), transcript=Path(tpath), **pack.TRANSCRIPT_ROWS), cache=_DRAFT_CACHE)
        except pack.ToolError as e:
            out["warnings"].append(str(e))
            return out
        out.update(keepsSec=pack.summary(plan)["keepsSec"], base="rows", warnings=list(plan.warnings))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _edit_request(pack, source: str, tpath: str | None, keeps):
    """カット(編集の内容の残す区間。秒)があればそのとおり(pack.EDIT_KEEPS)、無ければ文字起こしの行から(pack.TRANSCRIPT_ROWS)"""
    if keeps:
        return pack.Request(video=Path(source), transcript=Path(tpath) if tpath else None, keep_pairs=[tuple(k) for k in keeps], **pack.EDIT_KEEPS)
    return pack.Request(video=Path(source), transcript=Path(tpath), **pack.TRANSCRIPT_ROWS)


def edit_preview(doc: dict, keeps, version: str = "") -> dict:
    """「編集」3 パック のタブの「これから作るパック」: カットのとおりに作ったときの区間の数・カット後の長さ・Text+ 字幕の数・注意(ファイルは作らない)。
    文字起こしの一時ファイルは一時フォルダに作る(開いただけで動画の隣にファイルを増やさない)"""
    import pipeline_io
    global _DRAFT_CACHE
    source = str(doc.get("sourcePath") or "")
    if not source or not os.path.isfile(source):
        raise ResolveExportError("元の動画が見つかりません")
    pack, _tp = _load_pack()
    if _DRAFT_CACHE is None:
        _DRAFT_CACHE = pack.Cache(size=16)
    tmp_dir = tempfile.mkdtemp(prefix="edit-preview-")
    try:
        tpath = None
        if any(is_kept(g) for g in doc.get("segments") or [] if isinstance(g, dict)):
            tpath = os.path.join(tmp_dir, "input.transcript.json")
            with open(tpath, "w", encoding="utf-8") as f:
                json.dump(pipeline_io.build_transcript_v1(doc, version), f, ensure_ascii=False)
        try:
            plan = pack.plan_cut(_edit_request(pack, source, tpath, keeps), cache=_DRAFT_CACHE)
        except pack.ToolError as e:
            raise ResolveExportError(str(e))
        sm = pack.summary(plan)
        subs = sm["subtitles"] or {}
        return {"count": sm["count"], "keptSec": sm["keptSec"], "durationSec": sm["durationSec"], "fps": sm["fps"],
                "captions": subs.get("out", 0), "vanished": subs.get("vanished", 0), "warnings": plan.warnings}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def create_package(doc: dict, fps_text: str = "30", size_text: str | None = None, version: str = "", keeps=None) -> tuple[str, str, dict]:
    """文字起こしの文書 → Resolve 用の Text+ パック(zip)。-> (zip のパス, 一時フォルダ, 情報)。一時フォルダは呼び出し側が消す。
    fps_text・size_text: Text+ を置くプロジェクト(友人が手で作る)の fps・解像度。既定 30fps・1080x1920(縦)。
    情報: {"cuts": 残す区間の数, "captions": 字幕の数, "media": {"file", "hasEditHandles"}, "warnings": [...]}
    keeps: 「編集」のカット(残す区間の秒)。あればそのとおりに作る(3 パック のタブのパックと同じ区間)。無ければ文字起こしの行から"""
    import pipeline_io   # pipeline_io も resolve_export を読み込むので、ここで読む(循環を避ける)

    source = str(doc.get("sourcePath") or "")
    if not source or not os.path.isfile(source):
        raise ResolveExportError("元の動画が見つかりません")
    pack, tp = _load_pack()
    try:
        target = tp.parse_target(fps_text, size_text)
    except ValueError as e:
        raise ResolveExportError(str(e))
    tmp_dir = tempfile.mkdtemp(prefix="resolve-package-")
    try:
        tpath = os.path.join(tmp_dir, "input.transcript.json")
        with open(tpath, "w", encoding="utf-8") as f:
            json.dump(pipeline_io.build_transcript_v1(doc, version), f, ensure_ascii=False)
        folder = _safe_name(doc.get("title") or Path(source).stem) + "_pack"
        out_dir = Path(tmp_dir) / folder
        try:
            plan = pack.plan_cut(_edit_request(pack, source, tpath, keeps))
            res = pack.build_pack(plan, out_dir, textplus=True, textplus_target=target)
        except pack.ToolError as e:
            raise ResolveExportError(str(e))
        zip_path = os.path.join(tmp_dir, _safe_name(doc.get("title")) + "-resolve.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for kind, p in res["files"]:   # zip を展開するとフォルダが1つできる(Text+ の登録は、そのフォルダの場所を覚える)
                z.write(p, folder + "/" + p.relative_to(out_dir).as_posix())
        media = dict(res["files"])["video"]
        info = {"cuts": len(plan.keeps), "captions": len(plan.cues_out or []), "warnings": res["warnings"],
                "media": {"file": media.relative_to(out_dir).as_posix(), "hasEditHandles": bool(res["editMedia"])}}
        shutil.rmtree(out_dir, ignore_errors=True)   # 動画のコピーを早めに消す(zip に入れた)
        return zip_path, tmp_dir, info
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
