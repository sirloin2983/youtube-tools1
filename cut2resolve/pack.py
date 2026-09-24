# -*- coding: utf-8 -*-
"""カットの計算(試算)とパックの作成。CLI(cut2resolve.py)と画面(serve.py)の両方から呼ぶ共通部(処理を二重に持たない)。

  plan_cut(Request)   … 動画を調べ、カットの決め方を組み合わせて「残す区間」を出す。ファイルは作らない(= --dry-run)
  build_pack(Plan, …) … EDL・カット後の字幕・友人へ.txt・cut-plan.json(+ 任意で FCPXML・粗編集 mp4・元動画のコピー)を作る

残す区間の決め方:
  base(土台): "all"(動画全体)/ "list"(時刻リストの残す区間)/ "plan"(cut-plan の採用区間 + 前後の余白)
              / "rows"(文字起こしの残す行 + 前後の余白。行と行の間のすき間は残さない = 文字起こしツールの kept_spans と同じ)
  drops(削る): 時刻リストの削る区間・字幕の行(--drop-lines)・文字起こしの「カット済」の行(残す行と重なる部分は残す)・無音
  残す区間 = base − drops → 近い区間をつなぐ(join_gap)→ 短い区間を捨てる(min_len)
字幕: SRT があればそれ、無ければ文字起こしの残す行(カット済でない・文字のある行)。時刻はカット後に直す。
"""
import copy
import json
import os
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import List, Optional

import auto_cut as AC
import cut2resolve_core as C
import srt2resolve as S

ToolError = C.ToolError
BASES = ("all", "list", "plan", "rows")
PACK_FILE_KINDS = ("edl", "srt", "readme", "plan", "fcpxml", "roughcut", "video")


@dataclass
class Request:
    """カットの指定。時刻は秒、区間は (開始, 終了)。パスは Path(存在は plan_cut が確かめる)"""
    video: Path
    sub: Optional[Path] = None
    transcript: Optional[Path] = None
    plan: Optional[Path] = None
    base: str = "all"
    keep_pairs: Optional[list] = None
    drop_pairs: list = field(default_factory=list)
    drop_lines: Optional[set] = None
    handles: Optional[float] = None       # None = 入力しだいの既定(文字起こし由来は 0、スタジオの採用区間などは 10)
    silence: bool = False
    noise: float = -35.0
    silence_min: float = 0.6
    silence_pad: float = 0.15
    drop_cut_rows: bool = True            # 文字起こしの「カット済」の行を削る(= 文字起こしツールでの意味どおり)
    min_len: float = 0.3
    join_gap: float = 0.0
    fps: Optional[str] = None
    frames: Optional[int] = None
    src_start_tc: Optional[str] = None
    rec_start: str = "01:00:00:00"
    reel: str = "AX"
    name: Optional[str] = None
    extra_inputs: tuple = ()               # カットリストなど、出力で上書きしてはいけない入力ファイル

    def inputs(self):
        return tuple(Path(p) for p in (self.video, self.sub, self.transcript, self.plan) + tuple(self.extra_inputs) if p)


@dataclass
class Plan:
    req: Request
    video: Path
    meta: dict
    keeps: list
    base: list
    selected: list
    drops: dict
    cues: Optional[list]
    cues_out: Optional[list]
    vanished: int
    sub_source: Optional[str]
    src_start: str
    src_desc: str
    handles: float
    warnings: List[str]
    doc: dict                     # cut-plan.json の元(auto_cut.build_plan / plan_from_keeps と同じ形)
    transcript: Optional[dict] = None
    cutplan: Optional[dict] = None


class Cache:
    """画面用: 動画の情報(ffprobe)と無音の検出結果を覚えておく(試算 → 作成で同じ処理を繰り返さない)。
    鍵はパス・大きさ・更新日時と設定。動画を書き換えたら別の鍵になる"""

    def __init__(self, size=16):
        self._lock = threading.Lock()
        self._size = size
        self._probe = OrderedDict()
        self._silence = OrderedDict()

    @staticmethod
    def _file_key(path):
        st = os.stat(path)
        return (os.path.normcase(os.path.realpath(str(path))), st.st_size, st.st_mtime_ns)

    def _get(self, store, key):
        with self._lock:
            if key in store:
                store.move_to_end(key)
                return copy.deepcopy(store[key])
        return None

    def _put(self, store, key, value):
        with self._lock:
            store[key] = copy.deepcopy(value)
            while len(store) > self._size:
                store.popitem(last=False)

    def probe(self, video, fps=None, frames=None):
        key = self._file_key(video) + (fps, frames)
        hit = self._get(self._probe, key)
        if hit is not None:
            return hit
        meta = S.probe(video, fps, frames)
        self._put(self._probe, key, meta)
        return meta

    def silence(self, video, fps, total, noise, min_sec, pad, task=None):
        key = self._file_key(video) + (tuple(fps), total, float(noise), float(min_sec), float(pad))
        hit = self._get(self._silence, key)
        if hit is not None:
            return [tuple(x) for x in hit]
        sil = C.detect_silence(video, fps, total, noise, min_sec, pad, task)
        self._put(self._silence, key, sil)
        return sil

    def silence_cached(self, video, fps, total, noise, min_sec, pad):
        try:
            key = self._file_key(video) + (tuple(fps), total, float(noise), float(min_sec), float(pad))
        except OSError:
            return False
        with self._lock:
            return key in self._silence


def _finite(v, what, lo=0.0, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise ToolError(f"{what}は数値で指定してください。")
    if v < lo or (hi is not None and v > hi):
        raise ToolError(f"{what}は {lo:g}〜{hi:g} の範囲で指定してください。" if hi is not None else f"{what}は {lo:g} 以上にしてください。")
    return float(v)


def default_out_dir(video):
    return Path(video).parent / f"{Path(video).stem}_pack"


def _say(log, task, msg):
    if log:
        log(msg)
    if task:
        task.report(None, msg)


def plan_cut(req, task=None, cache=None, log=None):
    """残す区間を決める(ファイルは作らない)。task: 進み具合・取り消し(画面用)、cache: 画面用、log: CLI の表示(print)"""
    if req.base not in BASES:
        raise ToolError(f"カットの決め方が正しくありません: {req.base}")
    video = Path(req.video)
    for p in (video, req.sub, req.transcript, req.plan) + tuple(req.extra_inputs):
        if p is not None and not Path(p).is_file():
            raise ToolError(f"ファイルが見つかりません: {p}")
    min_len = _finite(req.min_len, "最短の長さ(--min-len)", 0, 3600)
    join_gap = _finite(req.join_gap, "つなぐ隙間(--join-gap)", 0, 3600)
    if req.handles is not None:
        _finite(req.handles, "前後の余白(--handles)", 0, 3600)
    if req.silence:
        C.check_silence_params(req.noise, req.silence_min, req.silence_pad)

    meta = cache.probe(video, req.fps, req.frames) if cache else S.probe(video, req.fps, req.frames)
    fps, total = meta["fps"], meta["total"]
    src_start, src_desc, tc_warns = C.resolve_src_start(video, req.src_start_tc, meta)
    C.check_timecodes(fps, req.rec_start, src_start)   # 無音の検出・書き出しの前に確かめる
    warns = [m for m in meta["warnings"] if "開始タイムコード" not in m] + tc_warns + C.name_warnings(video)

    tr = C.read_transcript(req.transcript) if req.transcript else None
    if tr and tr["bad"]:
        warns.append(f"文字起こしの {tr['bad']} 行は時刻が正しくないため使いませんでした。")
    cp = AC.read_cut_plan(req.plan) if req.plan else None

    cues, sub_source = None, None
    if req.sub:
        cues = S.parse_subs(S.read_sub_file(Path(req.sub)))
        if not cues:
            raise ToolError("字幕を1件も読み取れませんでした(SRT/VTT の形式を確認してください)。")
        sub_source = "srt"
        if tr:
            warns.append("字幕は SRT のほうを使いました(文字起こしはカットの判断にだけ使います)。")
    elif tr:
        cues = C.transcript_cues(tr["rows"]) or None
        sub_source = "transcript" if cues else None
        if not cues:
            warns.append("文字起こしに残す行が無いため、字幕は付けません。")

    # ---- 土台(残す区間の候補)
    selected, selected_records, handles = [], [], 0.0
    if req.base == "list":
        base, w = C.cut_list_to_keeps(req.keep_pairs or [], fps, total)
        warns += w
        if not base:
            raise ToolError("カットリストの区間が、動画の長さの範囲に入っていません。")
    elif req.base in ("plan", "rows"):
        if req.base == "plan":
            if not cp:
                raise ToolError("残す区間のファイル(cut-plan)を指定してください。")
            segs = cp["segments"]
            handles = AC.default_handles(cp) if req.handles is None else float(req.handles)
        else:
            if not tr:
                raise ToolError("文字起こしのファイル(.transcript.json)を指定してください。")
            spans = C.transcript_kept_spans(tr["rows"])
            if not spans:
                raise ToolError("文字起こしに残す行(カット済でない行)がありません。")
            segs = [{"id": f"rows-{i:03d}", "label": "", "start_seconds": a, "end_seconds": b}
                    for i, (a, b) in enumerate(spans, 1)]
            handles = 0.0 if req.handles is None else float(req.handles)
        bp = AC.build_plan(segs, meta, handles)
        base = [tuple(x) for x in bp["keep_frames"]]
        selected_records = bp["selected_segments"]
        selected = [tuple(r["selected_frames"]) for r in selected_records]
    else:
        base = [(0, total)]

    # ---- 削る区間
    drops = {}
    if req.drop_pairs:
        d, w = C.cut_list_to_keeps(req.drop_pairs, fps, total)
        drops["list"] = d
        warns += [x.replace("区間", "削る区間") for x in w]
    if req.drop_lines:
        if not cues:
            raise ToolError("--drop-lines には字幕ファイルが必要です。")
        over = sorted(i for i in req.drop_lines if i > len(cues))
        if over:
            warns.append(f"--drop-lines: 字幕は {len(cues)} 件しかないため、{over} は無視しました。")
        lines = []
        for i in sorted(req.drop_lines):
            if i <= len(cues):
                a, b, _ = cues[i - 1]
                cs = S.ms_to_frames(a, fps)
                lines.append((cs, max(S.ms_to_frames(b, fps), cs + 1)))
        drops["lines"] = C.normalize(lines, total)
    if tr and req.drop_cut_rows:
        def frames(spans):
            return C.normalize([(C.sec_to_frames(a, fps), C.sec_to_frames(b, fps)) for a, b in spans], total)
        cut_rows = C.subtract(frames(C.transcript_cut_spans(tr["rows"])), frames(C.transcript_kept_spans(tr["rows"])))
        if cut_rows:
            drops["cutRows"] = cut_rows
    if req.silence:
        _say(log, task, "無音を検出しています…")
        if cache:
            sil = cache.silence(video, fps, total, req.noise, req.silence_min, req.silence_pad, task)
        else:
            sil = C.detect_silence(video, fps, total, req.noise, req.silence_min, req.silence_pad, task)
        drops["silence"] = sil
        _say(log, task, f"無音区間: {len(sil)}か所を削ります。")
    if req.base == "all" and not (req.drop_pairs or req.drop_lines or req.silence or drops.get("cutRows")):
        warns.append("カットの指定がありません。動画全体を1区間として出力します。")

    keeps = C.subtract(base, [x for v in drops.values() for x in v])
    keeps = C.merge_close(keeps, C.sec_to_frames(join_gap, fps))
    keeps = C.drop_short(keeps, max(1, C.sec_to_frames(min_len, fps)))
    if not keeps:
        raise ToolError("残る区間がありません。カットの指定(無音の感度 --noise・最短の長さ --min-len など)を見直してください。")
    if len(keeps) > C.MAX_EDL_EVENTS:
        warns.append(f"残す区間が {len(keeps)} か所あり、EDL の番号が 3 桁(999)を超えます。Resolve で読めない可能性があります"
                     "(無音の長さを長くする・近い区間をつなぐ、で減らせます)。")

    cues_out, vanished = (None, 0)
    if cues:
        cues_out, vanished = C.remap_cues(cues, keeps, fps)
    doc = AC.plan_from_keeps(keeps, meta, selected_records, C.sec_to_frames(handles, fps))
    return Plan(req=req, video=video, meta=meta, keeps=keeps, base=base, selected=selected, drops=drops,
                cues=cues, cues_out=cues_out, vanished=vanished, sub_source=sub_source,
                src_start=src_start, src_desc=src_desc, handles=handles, warnings=warns, doc=doc,
                transcript=tr, cutplan=cp)


def describe(plan):
    """CLI の表示(従来の cut2resolve.py と同じ行)"""
    m, fps, total = plan.meta, plan.meta["fps"], plan.meta["total"]
    out = [f"動画: {plan.video.name}  {m['w']}x{m['h']}  {fps[0] / fps[1]:.3f}fps  {total}フレーム({m['frames_source']})",
           f"映像: {m['codec']} / {m['pix_fmt']}",
           f"元動画の開始タイムコード: {plan.src_start}({plan.src_desc})"
           "  ← Resolve の Clip Attributes の Start TC と同じになるはずです"]
    if plan.req.base in ("plan", "rows"):
        out.append(f"残す区間の元: {'採用区間(cut-plan)' if plan.req.base == 'plan' else '文字起こしの残す行'}"
                   f" {len(plan.selected)}件 + 前後の余白 {plan.handles:g}秒")
    out.append(C.describe_keeps(plan.keeps, fps, total))
    if plan.cues is not None:
        src = "" if plan.sub_source == "srt" else "(文字起こしから)"
        out.append(f"字幕{src}: {len(plan.cues)}件 -> カット後 {len(plan.cues_out)}件(カットで消えた字幕 {plan.vanished}件)")
    out += ["注意: " + w for w in plan.warnings]
    return out


def pack_paths(video, out_dir, has_subs, render=False, copy_video=False, fcpxml=False):
    """パックに書くファイル {種類: パス}"""
    video, out_dir = Path(video), Path(out_dir)
    p = {"edl": out_dir / f"{video.stem}.edl", "readme": out_dir / "友人へ.txt", "plan": out_dir / "cut-plan.json"}
    if has_subs:
        p["srt"] = out_dir / f"{video.stem}_cut.srt"
    if fcpxml:
        p["fcpxml"] = out_dir / f"{video.stem}_cut.fcpxml"
    if render:
        p["roughcut"] = out_dir / f"{video.stem}_roughcut.mp4"
    if copy_video:
        p["video"] = out_dir / video.name
    return p


def planned_outputs(plan, out_dir=None, render=False, copy_video=False, fcpxml=False):
    """作る予定のファイルと、すでにあるもの(画面の上書き確認用)"""
    out_dir = Path(out_dir) if out_dir else default_out_dir(plan.video)
    paths = pack_paths(plan.video, out_dir, plan.cues_out is not None, render, copy_video, fcpxml)
    return out_dir, paths, [p for p in paths.values() if p.exists()]


def build_pack(plan, out_dir=None, render=False, copy_video=False, fcpxml=False, force=False, crf=18,
               task=None, log=None):
    """パックを作る。-> {"out_dir", "files": [(種類, パス)], "readme": 友人へ.txt の中身, "warnings"}。
    重いもの(粗編集の mp4・元動画のコピー)は出力フォルダの中の一時的な名前で作り、最後に名前を付け替える
    (途中で失敗・取り消したとき、以前のパックを半端に壊さない・書きかけを残さない)"""
    if isinstance(crf, bool) or not isinstance(crf, int) or not 0 <= crf <= 51:
        raise ToolError("粗編集の画質(--crf)は 0〜51 の整数で指定してください。")
    video, meta, fps = plan.video, plan.meta, plan.meta["fps"]
    out_dir = Path(out_dir) if out_dir else default_out_dir(video)
    if out_dir.exists() and not out_dir.is_dir():
        raise ToolError(f"出力先がフォルダではありません: {out_dir}")
    paths = pack_paths(video, out_dir, plan.cues_out is not None, render, copy_video, fcpxml)
    C.validate_output_paths(list(paths.values()), force, protected=plan.req.inputs())
    req = plan.req
    t0 = C.tc_to_frames(plan.src_start, C.nominal_rate(fps))
    warnings = []
    known = pack_paths(video, out_dir, True, True, False, True)   # 前に作ったかもしれない、今回は作らないもの
    stale = [p for k, p in known.items() if k not in paths and p.exists()]
    if stale:
        warnings.append("前に作った " + "・".join(p.name for p in stale) + " がフォルダに残っています(今回のカットとは合いません。"
                        "要らなければ消してください)。")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = secrets.token_hex(4)
    staged = []
    try:
        if render:
            _say(log, task, "粗編集の動画を書き出しています…(時間がかかります)")
            tmp = out_dir / f".c2r-{tag}-{paths['roughcut'].name}"
            C.render_rough_cut(video, plan.keeps, fps, bool(meta["audio"]), tmp, crf, task)
            staged.append((tmp, paths["roughcut"], "roughcut"))
        if copy_video and not S.same_path(paths["video"], video):
            _say(log, task, "元動画をコピーしています…")
            tmp = out_dir / f".c2r-{tag}-{video.name}"
            C.copy_video(video, out_dir, task, dst=tmp)
            staged.append((tmp, paths["video"], "video"))
        if task:
            task.check()
        extras = []
        if fcpxml:
            extras.append((paths["fcpxml"].name, "補助: カット済みのタイムライン(字幕はタイトル)。Resolve の実機では未確認。"
                                                 "動画の場所を書いてあるので、動画を移動したら再リンクが必要"))
        extras.append(("cut-plan.json", "カットの記録(残す・削る区間)。ツールで読み直す用で、Resolve では使いません"))
        files = C.write_pack(out_dir, video, meta, plan.keeps, plan.cues_out, req.reel, req.rec_start,
                             plan.src_start, paths.get("roughcut"), req.name, extras)
        if fcpxml:
            xml_video = paths["video"] if copy_video else video   # FCPXML は動画の場所を書く。同梱したならそちら
            S.write_text_atomic(paths["fcpxml"], AC.build_cut_fcpxml(Path(xml_video), meta, plan.keeps, plan.cues_out, t0),
                                encoding="utf-8", newline="\n")
            files["fcpxml"] = paths["fcpxml"]
        doc = AC.finalize_plan(plan.doc, video, meta, plan.src_start, copy_video, plan.cues_out)
        S.write_text_atomic(paths["plan"], json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files["plan"] = paths["plan"]
        while staged:
            tmp, final, kind = staged[0]
            S._replace_retry(str(tmp), str(final))
            files[kind] = final
            staged.pop(0)
    finally:
        for tmp, _, _ in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if copy_video and "video" not in files:
        files["video"] = paths["video"]
    ordered = [(k, files[k]) for k in PACK_FILE_KINDS if k in files]
    readme = files["readme"].read_text(encoding="utf-8-sig")
    return {"out_dir": out_dir, "files": ordered, "readme": readme, "warnings": warnings}


# ---------------------------------------------------------------- 画面に返す形(JSON)

def _sec(n, fps):
    return round(float(Fraction(n * fps[1], fps[0])), 6)


def summary(plan, limit=5000):
    """試算の結果(画面のタイムライン・一覧・合計に使う)。区間はフレーム [開始, 終了)、fps で秒に直せる"""
    m, fps, total = plan.meta, plan.meta["fps"], plan.meta["total"]
    kept = sum(e - s for s, e in plan.keeps)
    removed = AC.removed_between(plan.keeps, total)
    subs = None
    if plan.cues is not None:
        subs = {"source": plan.sub_source, "in": len(plan.cues), "out": len(plan.cues_out), "vanished": plan.vanished,
                "cues": [[S.ms_to_frames(a, fps), max(S.ms_to_frames(b, fps), S.ms_to_frames(a, fps) + 1), t[:80]]
                         for a, b, t in plan.cues[:limit]]}
    rows = None
    if plan.transcript:
        rows = [[C.sec_to_frames(r["start"], fps), C.sec_to_frames(r["end"], fps), bool(r["cut"]), bool(C.row_is_kept(r))]
                for r in plan.transcript["rows"][:limit]]
    return {
        "fps": list(fps), "fpsValue": fps[0] / fps[1], "total": total, "durationSec": _sec(total, fps),
        "keeps": [list(x) for x in plan.keeps], "removed": [list(x) for x in removed],
        "selected": [list(x) for x in plan.selected], "base": [list(x) for x in plan.base],
        "drops": {k: [list(x) for x in v][:limit] for k, v in plan.drops.items()},
        "count": len(plan.keeps), "keptFrames": kept, "keptSec": _sec(kept, fps), "removedSec": _sec(total - kept, fps),
        "keptPercent": round(kept * 100 / total, 1),
        "handles": plan.handles, "baseKind": plan.req.base,
        "srcStart": plan.src_start, "srcStartDesc": plan.src_desc, "recStart": plan.req.rec_start,
        "subtitles": subs, "transcriptRows": rows, "warnings": plan.warnings,
        "text": "\n".join(describe(plan)),
    }
