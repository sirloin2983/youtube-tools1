# -*- coding: utf-8 -*-
"""カットの計算(試算)とパックの作成。CLI(cut2resolve.py)と画面(serve.py)の両方から呼ぶ共通部(処理を二重に持たない)。

  plan_cut(Request)   … 動画を調べ、カットの決め方を組み合わせて「残す区間」を出す。ファイルは作らない(= --dry-run)
  build_pack(Plan, …) … EDL・カット後の字幕・友人へ.txt・cut-plan.json(+ 任意で FCPXML・粗編集 mp4・元動画のコピー・Text+パック)を作る。
                        Text+ パックは最小限にできる(backup=False: EDL・予備の手順書・SRT を入れない、plan_file=False: cut-plan.json を書かない
                        = 画面・API。記録は作業データ側。docs/edit-tool-design.md の 12 ④)

残す区間の決め方:
  base(土台): "all"(動画全体)/ "list"(時刻リストの残す区間)/ "plan"(cut-plan の採用区間 + 前後の余白)
              / "rows"(文字起こしの残す行 + 前後の余白。行と行の間のすき間は残さない = 文字起こしツールの kept_spans と同じ)
  drops(削る): 時刻リストの削る区間・字幕の行(--drop-lines)・文字起こしの「カット済」の行(残す行と重なる部分は残す)・無音
  残す区間 = base − drops → 近い区間をつなぐ(join_gap)→ 短い区間を捨てる(min_len)
字幕: SRT があればそれ、無ければ文字起こしの残す行(カット済でない・文字のある行)。時刻はカット後に直す。
"""
import copy
import dataclasses
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
import resolve_textplus as TP

ToolError = C.ToolError
BASES = ("all", "list", "plan", "rows")


@dataclass(frozen=True)
class RowEdge:
    """行から作るカット(base "rows")で、残す区間の端を「声が止まる所」まで広げる(語頭・語尾が切れないように。docs/edit-tool-design.md の 12 ⑥)。
    文字起こしは行の端を最初・最後の単語の時刻にそろえていて、Whisper の単語の時刻は始まりが遅く・終わりが早く出やすいため。
      終わり: after 秒先までに無音が始まれば、そこまで。始まり: before 秒前までに無音が終われば、そこから。
      端がもう無音の中なら動かさない。窓の中に無音が無い(BGM が続くなど)ときは決まった余白(pad_after・pad_before。上限を超えない = 上限 0 なら広げない)。
    無音は cut2resolve_core.detect_silence(話の前後の余白 0・短い無音も拾う)。detect=False は無音を調べずに決まった余白だけ(調べられないとき)"""
    after: float = 0.5
    before: float = 0.3
    noise: float = -35.0
    min_sil: float = 0.15
    pad_after: float = 0.2
    pad_before: float = 0.1
    detect: bool = True


ROW_EDGE = RowEdge()   # 既定(オン)。「編集」の「行から」の設定・cut2resolve の spec.rowEdge で変えられる(row_edge_from)
ROW_EDGE_MAX = 2.0     # 広げる上限(秒)の上限

# 文字起こしツールの「残す行」の規則(tools/test_resolve_pack_contract.py が確かめる):
# 行の時間を残す・短い行も捨てない(最短 0)・1フレーム以下の隙間はつなぐ(1フレームだけのジャンプカットを作らない)・
# 端を声の止まる所まで広げる(ROW_EDGE。2026-09-26 ⑥。以前は余白 0 で語頭・語尾が切れていた)
TRANSCRIPT_ROWS = {"base": "rows", "handles": 0.0, "min_len": 0.0, "join_frames": 1, "row_edge": ROW_EDGE}
# 「編集」ツールのカット(タイムラインで手で決めた残す区間。画面の指定 spec.keeps)のとおりに作る: 余白を足さない・最短の長さで捨てない・
# 無音を重ねない・「カット済」の行で削らない(削る所はもう keeps に入っている)・隙間をつながない(接している区間だけ1つにまとめる)。
# とても短い区間は捨てずに注意だけ出す(warn_short 秒)。docs/edit-tool-design.md の 5
EDIT_KEEPS = {"base": "list", "handles": 0.0, "min_len": 0.0, "join_frames": 0, "silence": False, "drop_cut_rows": False, "warn_short": 0.5}
MAX_KEEPS = 5000
PACK_FILE_KINDS = ("edl", "srt", "readme", "plan", "fcpxml", "roughcut", "video",
                   "textplus_script", "textplus_install", "textplus_launcher", "textplus_readme", "textplus_template")
OLD_TEXTPLUS_PLAN = "textplus-import.json"   # 2026-09-26 まで Text+ パックに入れていた計画(中身は Lua に埋め込み済みなので、もう書かない。④)


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
    join_frames: Optional[int] = None     # つなぐ隙間をフレームで(指定すると join_gap より優先)
    fps: Optional[str] = None
    frames: Optional[int] = None
    src_start_tc: Optional[str] = None
    rec_start: str = "01:00:00:00"
    reel: str = "AX"
    name: Optional[str] = None
    extra_inputs: tuple = ()               # カットリストなど、出力で上書きしてはいけない入力ファイル
    edit_media: bool = True               # 動画を同梱するパックで、スタジオの余白つき素材(.edit.json)があればそれを入れる
    warn_short: float = 0.0               # これより短い残す区間を注意に出す(秒。0 = 出さない。EDIT_KEEPS で使う)
    row_edge: Optional[RowEdge] = None    # base "rows" の区間の端を声の止まる所まで広げる(None = 広げない。TRANSCRIPT_ROWS は ROW_EDGE)

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


def row_edge_from(v):
    """画面・設定の指定 → RowEdge か None(広げない)。None・True = 既定(ROW_EDGE)、False・{"on": false} = 広げない、
    {"after": 秒, "before": 秒} = 上限を変える(0〜ROW_EDGE_MAX 秒)。形が違えば ToolError"""
    if v is None or v is True:
        return ROW_EDGE
    if v is False:
        return None
    if not isinstance(v, dict):
        raise ToolError("行の端を広げる設定(rowEdge)の形が正しくありません。")
    if v.get("on") is False:
        return None
    kw = {}
    for key, what in (("after", "終わりを広げる上限"), ("before", "始まりを広げる上限")):
        if v.get(key) not in (None, ""):
            kw[key] = _finite(v[key], what + "(秒)", 0, ROW_EDGE_MAX)
    return dataclasses.replace(ROW_EDGE, **kw)


def widen_row_edges(spans, silence, fps, total, edge, blocks=()):
    """残す区間(フレーム)の端を声の止まる所まで広げる(RowEdge の説明)。silence: 無音の区間(フレーム。None = 調べていない → 決まった余白)。
    blocks: 越えて広げない区間(フレーム。「カット済」の行。越えると、カット済の行の向こう側に切れ端が残るため)。
    広げて重なった・接した区間は1つにつなぐ。0〜total に収める"""
    import bisect
    blk = C.normalize(blocks or [], total)
    bstarts, bends = [s for s, _ in blk], [e for _, e in blk]
    f = lambda sec: C.sec_to_frames(sec, fps)
    after, before = f(edge.after), f(edge.before)
    pad_after, pad_before = min(after, f(edge.pad_after)), min(before, f(edge.pad_before))   # 決まった余白も上限の中(上限 0 = 広げない)
    sil = C.normalize(silence or [], total)
    starts, ends = [s for s, _ in sil], [e for _, e in sil]
    out = []
    for a, b in spans:
        # 終わり: b より後ろに終わる最初の無音。b がその中(もう無音)なら動かさない・窓の中で始まればそこまで・無ければ決まった余白
        i = bisect.bisect_right(ends, b)
        if silence is None or i == len(sil) or sil[i][0] > b + after:
            nb = b + pad_after
        else:
            nb = max(b, sil[i][0])
        k = bisect.bisect_left(bstarts, b)   # b から後ろで最初に始まるカット済の行
        if k < len(blk):
            nb = max(b, min(nb, bstarts[k]))
        # 始まり: a より前に始まる最後の無音。a がその中(声はまだ)なら動かさない・窓の中で終わればそこから・無ければ決まった余白
        j = bisect.bisect_left(starts, a) - 1
        if silence is None or j < 0 or sil[j][1] < a - before:
            na = a - pad_before
        else:
            na = min(a, sil[j][1])
        k = bisect.bisect_right(bends, a) - 1   # a より前で最後に終わるカット済の行
        if k >= 0:
            na = min(a, max(na, bends[k]))
        out.append((max(0, na), min(total, nb)))
    return C.normalize(out, total)


def _row_edge_args(req, meta):
    """無音を調べる引数(video, fps, total, noise, min, pad)。調べない(広げない・detect=False・音声が無い)なら None"""
    e = req.row_edge
    if req.base != "rows" or e is None or not e.detect or not meta.get("audio"):
        return None
    return (Path(req.video), meta["fps"], meta["total"], e.noise, e.min_sil, 0.0)


def row_edge_pending(req, cache):
    """plan_cut が無音の検出(動画の音声を全部読む重い処理)をするか。画面が SLOTS を通すかを決めるのに使う(cache にあれば False)"""
    if req.base != "rows" or req.row_edge is None or not req.row_edge.detect:
        return False
    meta = cache.probe(Path(req.video), req.fps, req.frames)
    args = _row_edge_args(req, meta)
    return bool(args) and not cache.silence_cached(*args)


def without_detect(req):
    """無音を調べずに決まった余白だけで広げる Request(重い処理の順番を待てないとき)"""
    return dataclasses.replace(req, row_edge=dataclasses.replace(req.row_edge, detect=False)) if req.row_edge else req


def _say(log, task, msg):
    if log:
        log(msg)
    if task:
        task.report(None, msg)


def _cut_row_frames(rows, fps, total):
    """「カット済」の行の時間(フレーム)。残す行と重なる部分は残す行を優先して引く"""
    def frames(spans):
        return C.normalize([(C.sec_to_frames(a, fps), C.sec_to_frames(b, fps)) for a, b in spans], total)
    return C.subtract(frames(C.transcript_cut_spans(rows)), frames(C.transcript_kept_spans(rows)))


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
    if req.join_frames is not None and (isinstance(req.join_frames, bool) or not isinstance(req.join_frames, int)
                                        or not 0 <= req.join_frames <= 1000):
        raise ToolError("つなぐ隙間(フレーム)は 0〜1000 の整数で指定してください。")
    if req.handles is not None:
        _finite(req.handles, "前後の余白(--handles)", 0, 3600)
    if req.silence:
        C.check_silence_params(req.noise, req.silence_min, req.silence_pad)
    if req.row_edge is not None:
        e = req.row_edge
        for v, what in ((e.after, "終わりを広げる上限"), (e.before, "始まりを広げる上限"), (e.pad_after, "終わりの余白"), (e.pad_before, "始まりの余白")):
            _finite(v, what + "(秒)", 0, ROW_EDGE_MAX)
        C.check_silence_params(e.noise, e.min_sil, 0.0)

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
        if req.base == "rows" and req.row_edge is not None and meta.get("audio"):
            # 行の端を声の止まる所まで広げる(RowEdge)。字幕(行の時刻)は変えない。カット済の行は下の drops で削るので、広げた所がかかっても残らない
            args, sil = _row_edge_args(req, meta), None
            if args:
                _say(log, task, "行の端の声の止まる所を調べています…")
                try:
                    sil = cache.silence(*args, task) if cache else C.detect_silence(*args, task)
                except ToolError as e:
                    warns.append(f"声の止まる所を調べられなかったため、行の端に決まった余白(前 {req.row_edge.pad_before:g} 秒・"
                                 f"後 {req.row_edge.pad_after:g} 秒)を付けました: {e}")
            blocks = _cut_row_frames(tr["rows"], fps, total) if req.drop_cut_rows else []
            base = widen_row_edges(base, sil, fps, total, req.row_edge, blocks)
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
        cut_rows = _cut_row_frames(tr["rows"], fps, total)
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
    elif req.base == "all" and req.silence and not (req.drop_pairs or req.drop_lines or drops.get("cutRows")):
        # 既定の「無音で自動」だけで削れた区間が 0 か、ごくわずか(動画全体の 1% 未満)なら、
        # 何も言わずにそのまま「動画全体を1区間」のパックを作ってしまわないよう注意する(問題3)
        removed_sec = sum(b - a for a, b in drops.get("silence", [])) * fps[1] / fps[0]
        total_sec = total * fps[1] / fps[0]
        if removed_sec < max(1.0, total_sec * 0.01):
            warns.append("切れる所が見つかりませんでした。「無音とみなす音量」を上げる(-30 など)か、"
                         "②残す区間・③時刻リストを試してみてください。")

    keeps = C.subtract(base, [x for v in drops.values() for x in v])
    keeps = C.merge_close(keeps, req.join_frames if req.join_frames is not None else C.sec_to_frames(join_gap, fps))
    keeps = C.drop_short(keeps, max(1, C.sec_to_frames(min_len, fps)))
    if not keeps:
        raise ToolError("残る区間がありません。カットの指定(無音の感度 --noise・最短の長さ --min-len など)を見直してください。")
    if req.warn_short:
        short = [(a, b) for a, b in keeps if (b - a) * fps[1] < req.warn_short * fps[0]]
        if short:
            eg = "・".join(f"{C.fmt_frames(a, fps)}〜{C.fmt_frames(b, fps)}({C.fmt_frames(b - a, fps)})" for a, b in short[:3])
            warns.append(f"{req.warn_short:g} 秒より短い区間が {len(short)} か所あります(元の動画の {eg}{' など' if len(short) > 3 else ''})。"
                         "意図どおりか確かめてください。")
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
        e = plan.req.row_edge
        if plan.req.base == "rows" and e is not None:
            out.append(f"行の端: 声の止まる所まで広げる(終わりは {e.after:g} 秒先・始まりは {e.before:g} 秒前まで。"
                       f"無音が無ければ 後 {e.pad_after:g} 秒・前 {e.pad_before:g} 秒)")
    out.append(C.describe_keeps(plan.keeps, fps, total))
    if plan.cues is not None:
        src = "" if plan.sub_source == "srt" else "(文字起こしから)"
        out.append(f"字幕{src}: {len(plan.cues)}件 -> カット後 {len(plan.cues_out)}件(カットで消えた字幕 {plan.vanished}件)")
    out += ["注意: " + w for w in plan.warnings]
    return out


def pack_paths(video, out_dir, has_subs, render=False, copy_video=False, fcpxml=False, textplus=False, media=None,
               backup=True, plan_file=True):
    """パックに書くファイル {種類: パス}。media: 同梱する動画が video と違うとき(スタジオの余白つき素材)。名前は video にそろえる。
    backup: Text+ パックに予備(EDL・予備_EDLで開く手順.txt・カット後の SRT)も入れる(Text+ でないパックは、EDL が本体なのでいつも入れる)。
    plan_file: cut-plan.json をフォルダに書く(コマンド。画面・API は作業データに記録する)"""
    video, out_dir = Path(video), Path(out_dir)
    media = Path(media) if media else video
    p = {}
    if not textplus or backup:
        # Text+ パックでは「友人へ.txt」を Text+ の手順書にし、EDL の手順書は予備として別の名前にする(手順が2つあると迷うため)
        p["edl"] = out_dir / f"{video.stem}.edl"
        p["readme"] = out_dir / (TP.EDL_README_NAME if textplus else "友人へ.txt")
        if has_subs:
            p["srt"] = out_dir / f"{video.stem}_cut.srt"
    if plan_file:
        p["plan"] = out_dir / "cut-plan.json"
    if fcpxml:
        p["fcpxml"] = out_dir / f"{video.stem}_cut.fcpxml"
    if render:
        p["roughcut"] = out_dir / f"{video.stem}_roughcut.mp4"
    if copy_video or textplus:
        p["video"] = (out_dir / "media" / media.name) if textplus else (out_dir / media.name)
    if textplus:
        p.update({
            "textplus_script": out_dir / "create_resolve_textplus_project.lua",
            "textplus_install": out_dir / "install_resolve_textplus_script.ps1",
            "textplus_launcher": out_dir / "ResolveにText+スクリプトを登録.bat",
            "textplus_readme": out_dir / TP.README_NAME,
            "textplus_template": out_dir / TP.TEMPLATE_NAME,
        })
    return p


def edit_media_path(video, req=None, include_video=True):
    """パックに入れる余白つき素材のパス(使わないなら None)。ffprobe を使わない下見(画面の上書き確認用)"""
    if not include_video or (req is not None and not req.edit_media):
        return None
    em = C.find_edit_media(video)
    return em["path"] if em else None


def media_for_pack(plan, include_video):
    """同梱する動画と、それに合わせた残す区間。-> dict(video, meta, keeps, src_start, edit, warnings)。
    スタジオの余白つき素材(前後に余白のある動画)があれば、それを入れて、残す区間を余白の分だけ後ろへずらす。
    Resolve でクリップの端を外へ延ばせる(カットで削った所・余白を後から戻せる)。字幕はタイムラインの位置なので変わらない。
    使えない(fps・大きさが違う・短すぎる)ときは、元の動画のままにして理由を警告に出す"""
    base = {"video": plan.video, "meta": plan.meta, "keeps": plan.keeps, "src_start": plan.src_start, "edit": None, "warnings": []}
    em = C.find_edit_media(plan.video) if include_video and plan.req.edit_media else None
    if not em:
        return base
    name = em["path"].name
    try:
        meta = S.probe(em["path"])
    except ToolError as e:
        base["warnings"].append(f"余白つき素材 {name} を調べられないため、元の動画を入れました({e})。")
        return base
    fps = plan.meta["fps"]
    if tuple(meta["fps"]) != tuple(fps) or (meta["w"], meta["h"]) != (plan.meta["w"], plan.meta["h"]):
        base["warnings"].append(f"余白つき素材 {name} は元の動画と fps・大きさが違うため使わず、元の動画を入れました。")
        return base
    off = C.sec_to_frames(em["selectionIn"], fps)
    keeps = [(a + off, b + off) for a, b in plan.keeps]
    if keeps[-1][1] > meta["total"]:
        base["warnings"].append(f"余白つき素材 {name} が元の動画より短いため使わず、元の動画を入れました。")
        return base
    src_start, _, w = C.resolve_src_start(em["path"], None, meta)
    before = float(Fraction(off * fps[1], fps[0]))
    after = float(Fraction((meta["total"] - off - plan.meta["total"]) * fps[1], fps[0]))
    info = {"path": str(em["path"]), "name": name, "selectionIn": em["selectionIn"],
            "handleBefore": round(before, 3), "handleAfter": round(max(0.0, after), 3)}
    return {"video": em["path"], "meta": meta, "keeps": keeps, "src_start": src_start, "edit": info,
            "warnings": w + [f"切り抜きスタジオの余白つき素材 {name} を入れました(Resolve でクリップの端を、前へ {before:.1f} 秒・"
                             f"後ろへ {max(0.0, after):.1f} 秒まで延ばせます)。"]}


def planned_outputs(plan, out_dir=None, render=False, copy_video=False, fcpxml=False, textplus=False, backup=True, plan_file=True):
    """作る予定のファイルと、すでにあるもの(画面の上書き確認用)"""
    out_dir = Path(out_dir) if out_dir else default_out_dir(plan.video)
    media = edit_media_path(plan.video, plan.req, copy_video or textplus)
    paths = pack_paths(plan.video, out_dir, plan.cues_out is not None, render, copy_video, fcpxml and not textplus, textplus, media,
                       backup, plan_file)
    return out_dir, paths, [p for p in paths.values() if p.exists()]


def build_pack(plan, out_dir=None, render=False, copy_video=False, fcpxml=False, textplus=False, force=False, crf=18,
               task=None, log=None, textplus_target=None, backup=True, plan_file=True, textplus_wrap=None):
    """パックを作る。-> {"out_dir", "files": [(種類, パス)], "readme": 友人へ.txt の中身, "warnings", "plan": cut-plan の中身(書かなくても返す)}。
    backup・plan_file は pack_paths(画面・API の既定は最小限: backup=False・plan_file=False。④)。
    重いもの(粗編集の mp4・元動画のコピー)は出力フォルダの中の一時的な名前で作り、最後に名前を付け替える
    (途中で失敗・取り消したとき、以前のパックを半端に壊さない・書きかけを残さない)"""
    if isinstance(crf, bool) or not isinstance(crf, int) or not 0 <= crf <= 51:
        raise ToolError("粗編集の画質(--crf)は 0〜51 の整数で指定してください。")
    if textplus and not plan.cues_out:
        raise ToolError("Text+ 用パックには字幕が必要です。SRT または文字起こしを指定してください。")
    video, meta, fps = plan.video, plan.meta, plan.meta["fps"]
    out_dir = Path(out_dir) if out_dir else default_out_dir(video)
    if out_dir.exists() and not out_dir.is_dir():
        raise ToolError(f"出力先がフォルダではありません: {out_dir}")
    fcpxml = bool(fcpxml and not textplus)
    copy_video = bool(copy_video or textplus)
    m = media_for_pack(plan, copy_video)   # 同梱する動画(余白つき素材なら、残す区間もそれに合わせる)
    mvideo, mmeta, mkeeps = m["video"], m["meta"], m["keeps"]
    paths = pack_paths(video, out_dir, plan.cues_out is not None, render, copy_video, fcpxml, textplus, mvideo, backup, plan_file)
    C.validate_output_paths(list(paths.values()), force, protected=plan.req.inputs() + ((mvideo,) if m["edit"] else ()))
    req = plan.req
    t0 = C.tc_to_frames(m["src_start"], C.nominal_rate(fps))
    warnings = list(m["warnings"])
    known = pack_paths(video, out_dir, True, True, False, True, True)   # 前に作ったかもしれない、今回は作らないもの
    known["textplus_plan"] = out_dir / OLD_TEXTPLUS_PLAN
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
        if copy_video and not S.same_path(paths["video"], mvideo):
            _say(log, task, "元動画をコピーしています…")
            paths["video"].parent.mkdir(parents=True, exist_ok=True)
            tmp = out_dir / f".c2r-{tag}-{mvideo.name}"
            C.copy_video(mvideo, out_dir, task, dst=tmp)
            staged.append((tmp, paths["video"], "video"))
        if task:
            task.check()
        extras = []
        if fcpxml:
            extras.append((paths["fcpxml"].name, "補助: カット済みのタイムライン(字幕はタイトル)。Resolve の実機では未確認。"
                                                 "動画の場所を書いてあるので、動画を移動したら再リンクが必要"))
        if textplus:
            extras.extend([
                (paths["textplus_launcher"].name, "Resolve のスクリプト一覧に Text+ 作成機能を登録する(明示実行)"),
                (paths["textplus_readme"].name, "本来の手順(Text+ 字幕つきのタイムラインを作る)。まずこちらを読んでください"),
            ])
        if plan_file:
            extras.append(("cut-plan.json", "カットの記録(残す・削る区間)。ツールで読み直す用で、Resolve では使いません"))
        files = {}
        if "edl" in paths:   # EDL・カット後の SRT・EDL の手順書(Text+ パックでは予備。最小限のときは入れない)
            files = C.write_pack(out_dir, mvideo, mmeta, mkeeps, plan.cues_out, req.reel, req.rec_start,
                                 m["src_start"], paths.get("roughcut"), req.name, extras, readme_path=paths["readme"], stem=video.stem)
        if fcpxml:
            xml_video = paths["video"] if copy_video else mvideo   # FCPXML は動画の場所を書く。同梱したならそちら
            S.write_text_atomic(paths["fcpxml"], AC.build_cut_fcpxml(Path(xml_video), mmeta, mkeeps, plan.cues_out, t0),
                                encoding="utf-8", newline="\n")
            files["fcpxml"] = paths["fcpxml"]
        doc = AC.finalize_plan(plan.doc, video, meta, plan.src_start, copy_video, plan.cues_out)
        if m["edit"]:   # 区間(segments)は元の切り抜きの時刻のまま(ツールで読み直す用)。同梱した素材はこちらに書く
            doc["editMedia"] = {"name": m["edit"]["name"], "selectionInSeconds": m["edit"]["selectionIn"],
                                "handleBeforeSeconds": m["edit"]["handleBefore"], "handleAfterSeconds": m["edit"]["handleAfter"],
                                "keep_frames": [list(x) for x in mkeeps]}
        if plan_file:
            S.write_text_atomic(paths["plan"], json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            files["plan"] = paths["plan"]
        while staged:
            tmp, final, kind = staged[0]
            S._replace_retry(str(tmp), str(final))
            files[kind] = final
            staged.pop(0)
        if textplus:
            tplan = plan if not m["edit"] else dataclasses.replace(
                plan, video=mvideo, meta=mmeta, keeps=mkeeps, req=dataclasses.replace(req, name=req.name or video.stem))
            files.update(TP.write_files(paths, tplan, out_dir, textplus_target, backup="edl" in paths, wrap=textplus_wrap))
    finally:
        for tmp, _, _ in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if copy_video and "video" not in files:
        files["video"] = paths["video"]
    ordered = [(k, files[k]) for k in PACK_FILE_KINDS if k in files]
    readme = files.get("textplus_readme", files.get("readme")).read_text(encoding="utf-8-sig")   # 画面に出すのは友人が最初に読む方
    return {"out_dir": out_dir, "files": ordered, "readme": readme, "warnings": warnings, "editMedia": m["edit"],
            "mediaKeeps": [list(x) for x in mkeeps], "plan": doc}


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
        "keepsSec": [[_sec(a, fps), _sec(b, fps)] for a, b in plan.keeps],   # 残す区間(秒)。「編集」のたたき台はこれで今の編集を置き換える
        "selected": [list(x) for x in plan.selected], "base": [list(x) for x in plan.base],
        "drops": {k: [list(x) for x in v][:limit] for k, v in plan.drops.items()},
        "count": len(plan.keeps), "keptFrames": kept, "keptSec": _sec(kept, fps), "removedSec": _sec(total - kept, fps),
        "keptPercent": round(kept * 100 / total, 1),
        "handles": plan.handles, "baseKind": plan.req.base,
        "srcStart": plan.src_start, "srcStartDesc": plan.src_desc, "recStart": plan.req.rec_start,
        "subtitles": subs, "transcriptRows": rows, "warnings": plan.warnings,
        "text": "\n".join(describe(plan)),
    }
