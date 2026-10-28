"""文字起こしの文書から Resolve のパックへの受け渡し(カットのたたき台・パックの見積もり・手順)と、「残す行」の規則。

パックの中身は pipeline/pack の pack.py で作る。
残す区間の決め方は pack.TRANSCRIPT_ROWS(行の時間・短い行も残す・1フレームの隙間はつなぐ・端を声の止まる所まで広げる)。
端を広げるか(設定の rowEdge)は pack.row_edge_from で読む(規則はここに書かない)。

このファイルに持っているもの: 「残す行」の規則(is_kept / kept_spans)・受け渡しの JSON の組み立て
(transcript/v1 = build_*。パックが読む形を作る側がここなので、
manage/cases の handoff_io は .clip.json の動画と保存の名前だけで、pipeline → manage の向きの違反が無い)。
パックの部品(同じフォルダの pack・resolve_textplus)は edit_draft などを呼んだときに初めて読み込む(文字起こしの他の機能はそれが無くても動く)。
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from ytt import errors as _errors, runtime as _runtime, schemas as _schemas

TOOL_NAME = _runtime.TOOL_APPS["transcribe"]   # 受け渡しの tool.name(互換のため値は変えない。manage/cases/handoff_io も同じ値を持つ)


def is_kept(seg: dict) -> bool:
    """この行を「残す」か。画面の「カット済」(cutState == "cut")の行と、文字が空の行は残さない。
    cut2resolve の row_is_kept も同じ規則(契約テストが確かめる)。"""
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


# ---------------------------------------------------------------- 受け渡しの JSON の組み立て

def tool_info(version):
    return {"name": TOOL_NAME, "version": str(version)}


def sorted_segments(doc):
    """文書の行を開始時刻の順に(画面の sortSegs と同じ、開始時刻だけの安定ソート)。時刻が壊れた行は除く。"""
    out = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict):
            continue
        a, b = _schemas.num(g.get("start")), _schemas.num(g.get("end"))
        if a is None or b is None or b < a:
            continue
        out.append(g)
    return sorted(out, key=lambda g: float(g["start"]))


def _media_of(doc):
    """受け渡しの JSON の media(動画のパス・名前・長さ。transcript/v1)"""
    return {"path": str(doc.get("sourcePath") or ""), "name": str(doc.get("sourceName") or os.path.basename(str(doc.get("sourcePath") or ""))),
            "durationSec": _schemas.num(doc.get("duration"))}


def build_transcript_v1(doc, version):
    """文書 → youtube-tools-transcript/v1。時刻は「動画ファイルの先頭 = 0 秒」(文書の保存形式のまま。範囲指定の文字起こしでも同じ)。
    機械の出力(original)・学習用の情報(params・flag・tags・dismissed など)は入れない(受け渡しに不要で、個人データを増やさないため)。
    文字が空の行は入れない(画面の書き出しと同じ)。speaker は speakers の並び順の番号(話者なしは null)。"""
    speakers, index = [], {}
    for s in doc.get("speakers") or []:
        if isinstance(s, dict) and s.get("id") not in (None, "") and s.get("id") not in index:
            index[s["id"]] = len(speakers)
            speakers.append({"id": len(speakers), "name": str(s.get("name") or s["id"])[:60]})
    segs = []
    for g in sorted_segments(doc):
        text = str(g.get("text") or "").strip()
        if not text:
            continue
        one = {"id": str(g.get("id") or ""), "start": round(float(g["start"]), 3), "end": round(float(g["end"]), 3), "text": text,
               "speaker": index.get(g.get("speaker")), "proofed": g.get("proofed") is True, "cut": g.get("cutState") == "cut"}
        if g.get("noSub") is True:   # 字幕に出さない行(ゲームの声など)。パックはこの行の字幕を作らず、残す区間には数える(cut2resolve の側)
            one["noSub"] = True
        segs.append(one)
    out = {"schema": _schemas.TRANSCRIPT_SCHEMA, "tool": tool_info(version), "createdAt": _schemas.iso_now(), "media": _media_of(doc)}
    if isinstance(doc.get("clip"), dict):
        out["clip"] = doc["clip"]
    out.update({"title": str(doc.get("title") or ""), "language": str(doc.get("language") or ""), "speakers": speakers, "segments": segs})
    if doc.get("whole") is False:   # 範囲を指定して文字起こしした文書は、その範囲も示す(約束に無い項目。読む側は無視してよい)
        out["transcribedRange"] = {"start": _schemas.num(doc.get("start")) or 0.0, "end": _schemas.num(doc.get("end"))}
    return out


# ---------------------------------------------------------------- パック(同じフォルダの pack.py で作る)

def pack_instructions(folder):
    """パックのフォルダ -> Resolve での手順(画面の「手順を見る」)。手順書のファイルは入れないので、
    パックの Lua に埋め込んだ計画から作り直す(規則は cut2resolve の resolve_textplus.readme_from_script)。Lua が無い・読めなければ None"""
    _pack, tp = _load_pack()
    lua = Path(folder) / "create_resolve_textplus_project.lua"
    try:
        with open(lua, "rb") as f:
            text = f.read(64 * 1024 * 1024).decode("utf-8", "replace")
        return tp.readme_from_script(text)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _load_pack():
    """パックの部品(同じフォルダの pack と resolve_textplus)。
    呼ばれたときに初めて読む(重い部品なので、残す行の規則・受け渡しの JSON だけ使うときは読まない)。
    resolve_export 自体が pipeline/pack にあるので、sys.path を探す必要は無い"""
    from . import pack, resolve_textplus
    return pack, resolve_textplus


_DRAFT_CACHE = None   # pack.Cache(動画の情報(ffprobe)と行の端の無音を覚える。同じ動画を開き直しても調べ直さない)


def _source_and_pack(doc):
    """文書の動画のパスと cut2resolve の部品 -> (動画, pack, resolve_textplus)。動画が無ければ ResolveExportError"""
    source = str(doc.get("sourcePath") or "")
    if not source or not os.path.isfile(source):
        raise _errors.ResolveExportError("元の動画が見つかりません")
    return (source,) + tuple(_load_pack())


def _draft_cache(pack):
    global _DRAFT_CACHE
    if _DRAFT_CACHE is None:
        _DRAFT_CACHE = pack.Cache(size=16)
    return _DRAFT_CACHE


def _write_transcript(doc, version, folder):
    """文書 → 一時フォルダの transcript/v1(pack に渡す。開いただけで動画の隣にファイルを増やさない)-> パス"""
    tpath = os.path.join(folder, "input.transcript.json")
    with open(tpath, "w", encoding="utf-8") as f:
        json.dump(build_transcript_v1(doc, version), f, ensure_ascii=False)
    return tpath


def _row_edge(pack, value, warnings):
    """設定の rowEdge → pack.RowEdge か None。形が正しくなければ既定(pack.ROW_EDGE)にして注意を出す"""
    try:
        return pack.row_edge_from(value)
    except pack.ToolError as e:
        warnings.append("行の端を広げる設定が読めないため、既定にしました: %s" % e)
        return pack.ROW_EDGE


def _rows_request(pack, source, tpath, row_edge, warnings, clip_range=None):
    return pack.Request(video=Path(source), transcript=Path(tpath), clip_range=clip_range,
                        **dict(pack.TRANSCRIPT_ROWS, row_edge=_row_edge(pack, row_edge, warnings)))


def _draft_span(doc, dur):
    """たたき台の区間 (始まり, 終わり)(動画の中の秒): 余白つき(LD-2f)の切り抜きは文書の clip のマークの区間(余白を含めない =
    まとめて実行の spec.clipRange と同じ)。余白なし・clip が無い・形が違えば動画の全体"""
    span = _schemas.clip_mark_span(doc.get("clip"))
    if span:
        lo, hi = max(0.0, span[0]), min(span[1], dur)
        if hi - lo > 0:
            return lo, hi
    return 0.0, dur


def edit_draft(doc: dict, version: str = "", rows: bool = True, row_edge=None, heavy=None, words=None, form: str = "auto") -> dict:
    """「編集」のカットのたたき台(開いたときの下書き)と、動画の fps・長さ(資料の git:before-1028-cleanup:docs/design/edit-tool-design.md の 4)。
    form: "auto" = 単語の時刻 words があれば「無音を詰める」(tidy。人が直す土台は一番良い機械の結果)、無ければ「行から」/
    "rows" = 「行から」/ "tidy" = 「無音を詰める」(単語が無ければ「行から」)。tidy の詰めた所は drops [[開始, 終了, "pause"]](画面の印)。
    残す区間は pack.TRANSCRIPT_ROWS(今の「カットとパック」・入口のまとめて実行と同じ規則。ここに規則を書かない)。
    余白つき(LD-2f)の切り抜きは、文書の clip のマークの区間だけ(前後の余白はたたき台に入れない。まとめて実行の clipRange と同じ)。
    文字起こしの一時ファイルは一時フォルダに作る(開いただけで動画の隣にファイルを増やさない)。残す行が無ければ動画全体。
    rows=False: 「行から」を計算しない(カットが保存済みの文書を開いたとき。行の端の無音を調べる重い処理をしない)。
    row_edge: 設定の rowEdge(pack.row_edge_from)。heavy(label): 重い処理の順番を待つ文脈(ytt.jobs.SLOTS.slot。真なら取れた)。
      行の端の無音をまだ調べていないときだけ使う。順番を取れなければ、無音を調べずに決まった余白で広げて注意を出す
    -> {"fps": [n, d], "durationSec", "keepsSec": [[開始, 終了], ...], "base": "rows" | "all", "warnings", "skipped"?}"""
    source, pack, _tp = _source_and_pack(doc)
    cache = _draft_cache(pack)
    try:
        meta = cache.probe(Path(source))
    except pack.ToolError as e:
        raise _errors.ResolveExportError(str(e))
    fps, total = meta["fps"], meta["total"]
    dur = round(total * fps[1] / fps[0], 6)
    lo, hi = _draft_span(doc, dur)
    out = {"fps": [int(fps[0]), int(fps[1])], "durationSec": dur, "keepsSec": [[lo, hi]], "base": "all", "warnings": []}
    if not rows:
        out["skipped"] = True
        return out
    from . import tidy
    if form in ("auto", "tidy") and words and tidy.ON:
        cut = tidy.drops(source, words, lo, hi)
        out.update(keepsSec=[list(k) for k in tidy.keeps(lo, hi, cut)] or [[lo, hi]], base="tidy", drops=[list(d) for d in cut])
        return out
    if not _has_kept(doc):
        return out
    with tempfile.TemporaryDirectory(prefix="edit-draft-", ignore_cleanup_errors=True) as tmp_dir:
        tpath = _write_transcript(doc, version, tmp_dir)
        warns = []
        try:
            req = _rows_request(pack, source, tpath, row_edge, warns, (lo, hi) if (lo, hi) != (0.0, dur) else None)
            if heavy is not None and pack.row_edge_pending(req, cache):
                with heavy("行の端 " + os.path.basename(source)[:40]) as ok:
                    if ok:
                        plan = pack.plan_cut(req, cache=cache)
                if not ok:
                    plan = pack.plan_cut(pack.without_detect(req), cache=cache)
                    warns.append("他の重い処理が動いているため、行の端は声の止まる所を調べずに決まった余白で広げました"
                                 "(あとで「行から」を押し直すと調べ直します)")
            else:
                plan = pack.plan_cut(req, cache=cache)
        except pack.ToolError as e:
            out["warnings"].append(str(e))
            return out
        out.update(keepsSec=pack.summary(plan)["keepsSec"], base="rows", warnings=warns + list(plan.warnings))
        return out


def _has_kept(doc: dict) -> bool:
    """文書に「残す」行(is_kept)が 1 つでもあるか(無ければ字幕の元の文字起こしを書かない)"""
    return any(is_kept(g) for g in doc.get("segments") or [] if isinstance(g, dict))


def _edit_request(pack, source: str, tpath: str | None, keeps, row_edge=None, warnings=None):
    """カット(編集の内容の残す区間。秒)があればそのとおり(pack.EDIT_KEEPS)、無ければ文字起こしの行から(pack.TRANSCRIPT_ROWS。row_edge は設定の rowEdge)"""
    if keeps:
        return pack.Request(video=Path(source), transcript=Path(tpath) if tpath else None, keep_pairs=[tuple(k) for k in keeps], **pack.EDIT_KEEPS)
    return _rows_request(pack, source, tpath, row_edge, warnings if warnings is not None else [])


def edit_preview(doc: dict, keeps, version: str = "", wrap=None) -> dict:
    """「編集」3 パック のタブの「これから作るパック」: カットのとおりに作ったときの区間の数・カット後の長さ・Text+ 字幕の数・注意(ファイルは作らない)。
    文字起こしの一時ファイルは一時フォルダに作る(開いただけで動画の隣にファイルを増やさない)"""
    source, pack, _tp = _source_and_pack(doc)
    cache = _draft_cache(pack)
    with tempfile.TemporaryDirectory(prefix="edit-preview-", ignore_cleanup_errors=True) as tmp_dir:
        tpath = _write_transcript(doc, version, tmp_dir) if _has_kept(doc) else None
        try:
            plan = pack.plan_cut(_edit_request(pack, source, tpath, keeps), cache=cache)
        except pack.ToolError as e:
            raise _errors.ResolveExportError(str(e))
        sm = pack.summary(plan)
        subs = sm["subtitles"] or {}
        # 字幕の見本(最初の2つ)。改行は Text+ と同じ規則(resolve_textplus.wrap_caption。ここに規則を書かない)
        samples = [_tp.wrap_caption(t, wrap if wrap is not None else _tp.WRAP_DEFAULT["vertical"]) for _a, _b, t in (plan.cues_out or [])[:2]]
        # 見本ごとの話者の名前(A-2 の話者の色。実際のパックと同じ規則 = pack.cue_speakers。話者が無い・調べられないときは None)
        try:
            names = pack.cue_speakers(plan) or []
        except Exception:
            names = []
        sample_speakers = [(names[i] if i < len(names) and isinstance(names[i], str) and names[i] else None) for i in range(len(samples))]
        return {"count": sm["count"], "keptSec": sm["keptSec"], "durationSec": sm["durationSec"], "fps": sm["fps"],
                "captions": subs.get("out", 0), "vanished": subs.get("vanished", 0), "warnings": plan.warnings, "samples": samples,
                "sampleSpeakers": sample_speakers,
                # 重なる字幕の段分けと字幕に出さない行(cut2resolve の pack.summary のまま渡す。古い cut2resolve なら 0)
                **{k: int(sm.get(k) or 0) for k in ("captionLanes", "captionsStacked", "captionsTrimmed", "noSubRows")}}
