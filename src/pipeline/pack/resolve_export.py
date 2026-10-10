"""DaVinci Resolve への受け渡し(文字起こしツールの「Resolveパッケージ(zip)をダウンロード」)と、「残す行」の規則。

パックの中身は pipeline/pack の pack.py で作る(2026-09-26 一本化。以前はここに別の実装があり、Python の取り込みスクリプトで
新しいプロジェクトを作っていた)。zip の中身は cut2resolve の Text+ パックと同じ:
  動画(パックの直下。スタジオの余白つき素材があればそれ)・Text+ を作る Lua と雛形・登録用の bat と ps1(最小限。④。手順書は画面で見る)。
  backup=True のときだけ予備(EDL・予備_EDLで開く手順.txt・SRT)も。cut-plan.json は入れない(zip はダウンロードなので記録も残さない)
残す区間の決め方は pack.TRANSCRIPT_ROWS(行の時間・短い行も残す・1フレームの隙間はつなぐ・端を声の止まる所まで広げる)。
端を広げるか(設定の rowEdge)は pack.row_edge_from で読む(規則はここに書かない)。
同じ入力から同じ中身になることは dev/tests/test_resolve_pack_contract.py が確かめる。

このファイルに持っているもの: 「残す行」の規則(is_kept / kept_spans)・SRT の書式・受け渡しの JSON の組み立て
(transcript/v1・cut-plan/v1・SRT = build_*。RS3-E5b で編集の pipeline_io から移した。パックが読む形を作る側がここなので、
manage/cases の pipeline_io は読み・保存・.runtime だけになり、pipeline → manage の向きの違反が無くなった)。
パックの部品(同じフォルダの pack・resolve_textplus)は create_package などを呼んだときに初めて読み込む(文字起こしの他の機能はそれが無くても動く)。
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from ytt import runtime as _runtime, schemas as _schemas

TOOL_NAME = _runtime.TOOL_APPS["transcribe"]   # 受け渡しの tool.name(互換のため値は変えない。manage/cases/pipeline_io も同じ値を持つ)
_num = _schemas.num


class ResolveExportError(ValueError):
    pass


def _safe_name(value: str, fallback: str = "resolve-package") -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    return value[:80] or fallback


def srt_time(seconds: float) -> str:
    """SRT の時刻(HH:MM:SS,mmm)。画面の書き出し(index.html の tcode)と同じく、ミリ秒は四捨五入(0.5 は切り上げ)。"""
    ms = max(0, int(math.floor(float(seconds) * 1000 + 0.5)))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


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


# ---------------------------------------------------------------- 受け渡しの JSON と SRT の組み立て(RS3-E5b で pipeline_io から移した)

def tool_info(version):
    return {"name": TOOL_NAME, "version": str(version)}


def sorted_segments(doc):
    """文書の行を開始時刻の順に(画面の sortSegs と同じ、開始時刻だけの安定ソート)。時刻が壊れた行は除く。"""
    out = []
    for g in doc.get("segments") or []:
        if not isinstance(g, dict):
            continue
        a, b = _num(g.get("start")), _num(g.get("end"))
        if a is None or b is None or b < a:
            continue
        out.append(g)
    return sorted(out, key=lambda g: float(g["start"]))


def _media_of(doc):
    """受け渡しの JSON の media(動画のパス・名前・長さ。transcript/v1 と cut-plan/v1 で同じ)"""
    return {"path": str(doc.get("sourcePath") or ""), "name": str(doc.get("sourceName") or os.path.basename(str(doc.get("sourcePath") or ""))),
            "durationSec": _num(doc.get("duration"))}


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
        if g.get("noSub") is True:   # 字幕に出さない行(ゲームの声など。2026-10-05)。パックはこの行の字幕を作らず、残す区間には数える(cut2resolve の側)
            one["noSub"] = True
        segs.append(one)
    out = {"schema": _schemas.TRANSCRIPT_SCHEMA, "tool": tool_info(version), "createdAt": _schemas.iso_now(), "media": _media_of(doc)}
    if isinstance(doc.get("clip"), dict):
        out["clip"] = doc["clip"]
    out.update({"title": str(doc.get("title") or ""), "language": str(doc.get("language") or ""), "speakers": speakers, "segments": segs})
    if doc.get("whole") is False:   # 範囲を指定して文字起こしした文書は、その範囲も示す(約束に無い項目。読む側は無視してよい)
        out["transcribedRange"] = {"start": _num(doc.get("start")) or 0.0, "end": _num(doc.get("end"))}
    return out


def build_cut_plan_v1(doc, version):
    """文書 → youtube-tools-cut-plan/v1。区間 = kept_spans(「カット済」でない・文字のある行を、重なる・接するものでまとめる)。
    行と行の間のすき間は残さない(Resolve パッケージと同じ)。時刻は動画ファイルの先頭基準の秒(フレームへの変換は受け取る側)。"""
    spans = kept_spans(sorted_segments(doc))
    segs = []
    for i, sp in enumerate(spans, 1):
        label = "".join(str(g.get("text") or "").strip() for g in sp["segments"])
        segs.append({"id": "segment-%03d" % i, "start": round(sp["start"], 3), "end": round(sp["end"], 3), "status": "adopted",
                     "label": label[:40] + ("…" if len(label) > 40 else ""), "lines": [str(g.get("id") or "") for g in sp["segments"]]})
    return {"schema": _schemas.CUT_PLAN_SCHEMA, "tool": tool_info(version), "createdAt": _schemas.iso_now(), "media": _media_of(doc),
            "title": str(doc.get("title") or ""), "segments": segs}


def wrap_text(text, n):
    """n 文字ごとに改行(画面の wrapText と同じ。文字はコードポイント単位で数える)。n=0 は折り返さない。"""
    if not n:
        return text
    return "\n".join(text[i:i + n] for i in range(0, len(text), n))


def build_srt(doc, wrap=0, speaker_names=False, base=0.0):
    """画面の SRT 書き出し(index.html の exportRows / buildExport)と同じ規則:
    文字が空の行は出さない・終わりが基準より前の行は出さない・開始は 0 未満にしない・話者名は「[名前] 」を頭に付ける。
    動画の隣に保存する SRT は、その動画の先頭を 0 秒にする(base=0。範囲指定の文書でも動画の時刻のまま)。
    カット済の行も出す(字幕は動画全体に対するもの。カットは cut-plan と一緒に cut2resolve が適用する)。
    字幕に出さない行(noSub。ゲームの声など)は出さない。"""
    names = {s.get("id"): str(s.get("name") or "") for s in doc.get("speakers") or [] if isinstance(s, dict)}
    cues = []
    for g in sorted_segments(doc):
        text = str(g.get("text") or "").strip()
        a, b = float(g["start"]) - base, float(g["end"]) - base
        if not text or b <= 0 or g.get("noSub") is True:
            continue
        name = names.get(g.get("speaker"), "") if speaker_names and g.get("speaker") else ""
        cues.append((max(0.0, a), b, ("[%s] " % name if name else "") + wrap_text(text, wrap)))
    return srt_text(cues), len(cues)


# ---------------------------------------------------------------- パック(同じフォルダの pack.py で作る)

def pack_instructions(folder):
    """パックのフォルダ -> Resolve での手順(画面の「手順を見る」)。手順書のファイルは入れない(2026-09-27)ので、
    パックの Lua に埋め込んだ計画から作り直す(規則は cut2resolve の resolve_textplus.readme_from_script)。Lua が無い・読めなければ None"""
    _pack, tp = _load_pack()
    lua = Path(folder) / "create_resolve_textplus_project.lua"
    try:
        with open(lua, "rb") as f:
            text = f.read(64 * 1024 * 1024).decode("utf-8", "replace")
        return tp.readme_from_script(text, backup=(Path(folder) / tp.EDL_README_NAME).is_file())
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _load_pack():
    """パックの部品(同じフォルダの pack と resolve_textplus。役割で組み直す RS1-2 で cut2resolve から移した)。
    呼ばれたときに初めて読む(重い部品なので、残す行の規則・SRT・受け渡しの JSON だけ使うときは読まない)。
    RS3-E5b で resolve_export 自体が pipeline/pack に入ったので、以前の sys.path の探し方(YTT_CORE_DIR)は要らなくなった"""
    try:
        from . import pack, resolve_textplus
    except ImportError as e:
        raise ResolveExportError("パックの部品(pipeline.pack)を読み込めません: %s" % e)
    return pack, resolve_textplus


_DRAFT_CACHE = None   # pack.Cache(動画の情報(ffprobe)と行の端の無音を覚える。同じ動画を開き直しても調べ直さない)


def _source_and_pack(doc):
    """文書の動画のパスと cut2resolve の部品 -> (動画, pack, resolve_textplus)。動画が無ければ ResolveExportError"""
    source = str(doc.get("sourcePath") or "")
    if not source or not os.path.isfile(source):
        raise ResolveExportError("元の動画が見つかりません")
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


def _rows_request(pack, source, tpath, row_edge, warnings):
    return pack.Request(video=Path(source), transcript=Path(tpath), **dict(pack.TRANSCRIPT_ROWS, row_edge=_row_edge(pack, row_edge, warnings)))


def edit_draft(doc: dict, version: str = "", rows: bool = True, row_edge=None, heavy=None) -> dict:
    """「編集」のカットのたたき台(開いたときの下書き・「行から」)と、動画の fps・長さ(docs/design/edit-tool-design.md の 4)。
    残す区間は pack.TRANSCRIPT_ROWS(今の「カットとパック」・zip・入口のまとめて実行と同じ規則。ここに規則を書かない)。
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
        raise ResolveExportError(str(e))
    fps, total = meta["fps"], meta["total"]
    dur = round(total * fps[1] / fps[0], 6)
    out = {"fps": [int(fps[0]), int(fps[1])], "durationSec": dur, "keepsSec": [[0.0, dur]], "base": "all", "warnings": []}
    if not rows:
        out["skipped"] = True
        return out
    if not _has_kept(doc):
        return out
    with tempfile.TemporaryDirectory(prefix="edit-draft-", ignore_cleanup_errors=True) as tmp_dir:
        tpath = _write_transcript(doc, version, tmp_dir)
        warns = []
        try:
            req = _rows_request(pack, source, tpath, row_edge, warns)
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
            raise ResolveExportError(str(e))
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
                # 重なる字幕の段分けと字幕に出さない行(2026-10-05。cut2resolve の pack.summary のまま渡す。古い cut2resolve なら 0)
                **{k: int(sm.get(k) or 0) for k in ("captionLanes", "captionsStacked", "captionsTrimmed", "noSubRows")}}


_SUB_COLOR_RE = re.compile(r"#?([0-9A-Fa-f]{6})")


def speaker_sub_colors(doc: dict) -> dict:
    """文書の話者の字幕の見た目(sub。2026-10-05)のうち色がある人 -> {話者の名前: "#RRGGBB"}。
    組み込みの話者「ゲーム音声など」(builtin)は字幕に出さないので除く。保存のときに human/proof/store.py の sanitize_transcript が検査済みだが、
    Lua に入る値なのでここでも 16 進 6 桁だけを通す"""
    out = {}
    for s in (doc or {}).get("speakers") or []:
        if not isinstance(s, dict) or s.get("builtin"):
            continue
        sub = s.get("sub") if isinstance(s.get("sub"), dict) else {}
        m = _SUB_COLOR_RE.fullmatch(sub["color"].strip()) if isinstance(sub.get("color"), str) else None
        name = str(s.get("name") or "").strip()
        if m and name:
            out[name] = "#" + m.group(1).upper()
    return out


def create_package(doc: dict, fps_text: str = "30", size_text: str | None = None, version: str = "", keeps=None,
                   row_edge=None, backup: bool = False, wrap=None, color=None, speaker_colors=None) -> tuple[str, str, dict]:
    """文字起こしの文書 → Resolve 用の Text+ パック(zip)。-> (zip のパス, 一時フォルダ, 情報)。一時フォルダは呼び出し側が消す。
    fps_text・size_text: Text+ を置くプロジェクト(友人が手で作る)の fps・解像度。既定 30fps・1080x1920(縦)。
    情報: {"cuts": 残す区間の数, "captions": 字幕の数, "media": {"file", "hasEditHandles"}, "warnings": [...]}
    keeps: 「編集」のカット(残す区間の秒)。あればそのとおりに作る(3 パック のタブのパックと同じ区間)。無ければ文字起こしの行から
    (row_edge: 設定の rowEdge。行の端を声の止まる所まで広げるか)。color: 字幕の文字の色 {"hex", "who"}(配信者の名前を入れたとき)。
    speaker_colors: {話者の名前: "#RRGGBB"}(A-2。その話者の字幕だけその色。ytt/colors.speaker_colors で決める)。
    文書の話者の字幕の色(sub.color。speaker_sub_colors)はこれより優先して足す(メンバーの色のスイッチを切っていても効く = 3 パック の speakerStyles と同じ)"""
    speaker_colors = dict(speaker_colors or {}, **speaker_sub_colors(doc))
    source, pack, tp = _source_and_pack(doc)
    try:
        target = tp.parse_target(fps_text, size_text)
    except ValueError as e:
        raise ResolveExportError(str(e))
    tmp_dir = tempfile.mkdtemp(prefix="resolve-package-")
    try:
        tpath = _write_transcript(doc, version, tmp_dir)
        folder = _safe_name(doc.get("title") or Path(source).stem) + "_pack"
        out_dir = Path(tmp_dir) / folder
        warns = []
        try:
            plan = pack.plan_cut(_edit_request(pack, source, tpath, keeps, row_edge, warns))
            res = pack.build_pack(plan, out_dir, textplus=True, textplus_target=target, backup=backup, plan_file=False, textplus_wrap=wrap,
                                  readme_file=False, textplus_color=color, speaker_colors=speaker_colors or None)
        except pack.ToolError as e:
            raise ResolveExportError(str(e))
        zip_path = os.path.join(tmp_dir, _safe_name(doc.get("title")) + "-resolve.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for kind, p in res["files"]:   # zip を展開するとフォルダが1つできる(Text+ の登録は、そのフォルダの場所を覚える)
                z.write(p, folder + "/" + p.relative_to(out_dir).as_posix())
        media = dict(res["files"])["video"]
        info = {"cuts": len(plan.keeps), "captions": len(plan.cues_out or []), "warnings": warns + res["warnings"],
                "media": {"file": media.relative_to(out_dir).as_posix(), "hasEditHandles": bool(res["editMedia"])}}
        shutil.rmtree(out_dir, ignore_errors=True)   # 動画のコピーを早めに消す(zip に入れた)
        return zip_path, tmp_dir, info
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
