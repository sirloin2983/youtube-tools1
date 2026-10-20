# -*- coding: utf-8 -*-
"""カットの計算(試算)とパックの作成。画面(serve.py)と ② の自動の流れが呼ぶ共通部(処理を二重に持たない)。

  plan_cut(Request)   … 動画を調べ、カットの決め方を組み合わせて「残す区間」を出す。ファイルは作らない(= --dry-run)
  build_pack(Plan, …) … EDL・カット後の字幕・友人へ.txt・cut-plan.json(+ 任意で粗編集 mp4・元動画のコピー・Text+パック)を作る。
                        Text+ パックには EDL・カット後の SRT を入れない(「予備」の道は無い = 決定 3-34。Text+ でないパックは EDL が本体)。
                        plan_file=False: cut-plan.json を書かない = 画面・API。記録は作業データ側。notes:docs/design/edit-tool-design.md の 12 ④)

残す区間の決め方:
  base(土台): "all"(動画全体)/ "list"(時刻リストの残す区間)/ "plan"(cut-plan の採用区間 + 前後の余白)
              / "rows"(文字起こしの残す行 + 前後の余白。行と行の間のすき間は残さない = 文字起こしツールの kept_spans と同じ)
  drops(削る): 時刻リストの削る区間・字幕の行(--drop-lines)・文字起こしの「カット済」の行(残す行と重なる部分は残す)・無音
  残す区間 = base − drops → 近い区間をつなぐ(join_gap)→ 短い区間を捨てる(min_len)
字幕: SRT があればそれ、無ければ文字起こしの残す行(カット済でない・文字のある行。「字幕に出さない」noSub の行は除く)。時刻はカット後に直す。
      Text+ のパックでは、時刻の重なる字幕を段(上のトラック + 縦の位置)に分ける(resolve_textplus.stack_captions)。
"""
import bisect
import copy
import dataclasses
import json
import os
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ytt import fsio, loudness as LD
from . import auto_cut as AC
from . import cut2resolve_core as C
from . import srt2resolve as S
from . import resolve_textplus as TP
from ..analyze import breaks   # 話の切れ目(LD-2c。横動画の H3 と共有)

ToolError = C.ToolError
BASES = ("all", "list", "plan", "rows")


@dataclass(frozen=True)
class RowEdge:
    """行から作るカット(base "rows")で、残す区間の端を「声が止まる所」まで広げる(語頭・語尾が切れないように。notes:docs/design/edit-tool-design.md の 12 ⑥)。
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
SNAP_MIN = 0.05        # 話の切れ目で両端を詰めるのは、これより大きく動くときだけ(秒)

# 文字起こしツールの「残す行」の規則(dev/tests/test_resolve_pack_contract.py が確かめる):
# 行の時間を残す・短い行も捨てない(最短 0)・1フレーム以下の隙間はつなぐ(1フレームだけのジャンプカットを作らない)・
# 端を声の止まる所まで広げる(ROW_EDGE。⑥)
TRANSCRIPT_ROWS = {"base": "rows", "handles": 0.0, "min_len": 0.0, "join_frames": 1, "row_edge": ROW_EDGE}
# 「編集」ツールのカット(タイムラインで手で決めた残す区間。画面の指定 spec.keeps)のとおりに作る: 余白を足さない・最短の長さで捨てない・
# 無音を重ねない・「カット済」の行で削らない(削る所はもう keeps に入っている)・隙間をつながない(接している区間だけ1つにまとめる)。
# とても短い区間は捨てずに注意だけ出す(warn_short 秒)。notes:docs/design/edit-tool-design.md の 5
EDIT_KEEPS = {"base": "list", "handles": 0.0, "min_len": 0.0, "join_frames": 0, "silence": False, "drop_cut_rows": False, "warn_short": 0.5}
MAX_KEEPS = 5000
PACK_FILE_KINDS = ("edl", "srt", "readme", "plan", "roughcut", "video",
                   "textplus_script", "textplus_install", "textplus_launcher", "textplus_readme", "textplus_template")
OLD_MEDIA_DIR = "media"                       # 古い Text+ パックの動画のフォルダ(今はパックの直下)
OLD_BACKUP_README = "予備_EDLで開く手順.txt"   # 古い Text+ パックの「予備」の手順書(EDL・SRT と組。決定 3-34)


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
    noise: float = C.DEFAULT_NOISE_DB
    silence_min: float = C.DEFAULT_SILENCE_MIN
    silence_pad: float = C.DEFAULT_SILENCE_PAD
    drop_cut_rows: bool = True            # 文字起こしの「カット済」の行を削る(= 文字起こしツールでの意味どおり)
    min_len: float = 0.3
    join_gap: float = 0.0
    join_frames: Optional[int] = None     # つなぐ隙間をフレームで(指定すると join_gap より優先)
    fps: Optional[str] = None
    frames: Optional[int] = None
    src_start_tc: Optional[str] = None
    rec_start: str = C.DEFAULT_REC_START
    reel: str = C.DEFAULT_REEL
    name: Optional[str] = None
    extra_inputs: tuple = ()               # カットリストなど、出力で上書きしてはいけない入力ファイル
    edit_media: bool = True               # 動画を同梱するパックで、スタジオの余白つき素材(.edit.json)があればそれを入れる
    warn_short: float = 0.0               # これより短い残す区間を注意に出す(秒。0 = 出さない。EDIT_KEEPS で使う)
    row_edge: Optional[RowEdge] = None    # base "rows" の区間の端を声の止まる所まで広げる(None = 広げない。TRANSCRIPT_ROWS は ROW_EDGE)
    snap_edges: bool = False              # 土台の両端を話の切れ目へ詰める(LD-2c。言葉の途中で始まる・終わる所を落とす。文字起こしがあるときだけ)
    clip_range: Optional[tuple] = None    # 余白つきの動画(LD-2f)の中のマークの区間 (始まり, 終わり)(秒)。土台をここに・snap_edges なら余白の中の切れ目へ外へも寄せる

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
    speaker_spans: Optional[list] = None   # [(開始秒, 終了秒, 話者の名前)](元の動画の時刻。字幕が文字起こしのときだけ。A-2: 話者ごとの字幕の色)
    cue_names: Optional[list] = None       # 字幕(cues)ごとの話者の名前("" = 話者なし)。字幕が文字起こしのときだけ
    cue_src: Optional[list] = None         # カット後の字幕(cues_out)ごとの元の字幕(cues)の番号(remap_cues の with_src)
    no_sub_rows: int = 0                   # 字幕に出さなかった行(残す行のうち noSub の行)の数。字幕が文字起こしのときだけ数える


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

    def _memo(self, store, key, make):
        """覚えていればその写し、無ければ make() の結果を覚えて返す"""
        hit = self._get(store, key)
        if hit is None:
            hit = make()
            self._put(store, key, hit)
        return hit

    def probe(self, video, fps=None, frames=None):
        return self._memo(self._probe, self._file_key(video) + (fps, frames), lambda: S.probe(video, fps, frames))

    def _silence_key(self, video, fps, total, noise, min_sec, pad):
        return self._file_key(video) + (tuple(fps), total, float(noise), float(min_sec), float(pad))

    def silence(self, video, fps, total, noise, min_sec, pad, task=None):
        sil = self._memo(self._silence, self._silence_key(video, fps, total, noise, min_sec, pad),
                         lambda: C.detect_silence(video, fps, total, noise, min_sec, pad, task))
        return [tuple(x) for x in sil]

    def silence_cached(self, video, fps, total, noise, min_sec, pad):
        try:
            key = self._silence_key(video, fps, total, noise, min_sec, pad)
        except OSError:
            return False
        with self._lock:
            return key in self._silence


def _finite(v, what, lo=0.0, hi=None):
    if C.num(v) is None:   # 真偽値・数でない・NaN・無限大
        raise ToolError(f"{what}は数値で指定してください。")
    if v < lo or (hi is not None and v > hi):
        raise ToolError(f"{what}は {lo:g}〜{hi:g} の範囲で指定してください。" if hi is not None else f"{what}は {lo:g} 以上にしてください。")
    return float(v)


def default_out_dir(video):
    return Path(video).parent / f"{Path(video).stem}_pack"


def row_edge_from(v):
    """画面・設定の指定 → RowEdge か None(広げない)。None・True = 既定(ROW_EDGE)、False・{"on": false} = 広げない、
    {"after": 秒, "before": 秒} = 上限を変える(0〜ROW_EDGE_MAX 秒)、{"padAfter": 秒} = 無音が見つからないときの終わりの余白を変える(0〜ROW_EDGE_MAX 秒。
    始まりの余白 pad_before は変えない)。padAfter が after より大きいときは after も padAfter まで上げる(決まった余白も上限の中に収めるため。
    上げないと上限より長い余白が効かない)。形が違えば ToolError"""
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
    if v.get("padAfter") not in (None, ""):
        pad = _finite(v["padAfter"], "終わりの余白(秒)", 0, ROW_EDGE_MAX)
        kw["pad_after"] = pad
        kw["after"] = max(kw.get("after", ROW_EDGE.after), pad)   # 余白は上限の中(widen_row_edges)なので、上限も余白まで上げる
    return dataclasses.replace(ROW_EDGE, **kw)


def widen_row_edges(spans, silence, fps, total, edge, blocks=()):
    """残す区間(フレーム)の端を声の止まる所まで広げる(RowEdge の説明)。silence: 無音の区間(フレーム。None = 調べていない → 決まった余白)。
    blocks: 越えて広げない区間(フレーム。「カット済」の行。越えると、カット済の行の向こう側に切れ端が残るため)。
    広げて重なった・接した区間は1つにつなぐ。0〜total に収める"""
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


def silence_pending(req, cache):
    """plan_cut が「無音で削る」(silence)の検出をするか(cache に無い設定のとき)。row_edge_pending と同じ使い方"""
    if not req.silence:
        return False
    meta = cache.probe(Path(req.video), req.fps, req.frames)
    return not cache.silence_cached(Path(req.video), meta["fps"], meta["total"], req.noise, req.silence_min, req.silence_pad)


def detect_pending(req, cache):
    """plan_cut が無音の検出(重い処理)をするか。画面の API が SLOTS を通すかを決める。調べられない(ファイル無し・形が違う)ときは False
    (そのまま plan_cut が正しいエラーを返す)"""
    try:
        return row_edge_pending(req, cache) or silence_pending(req, cache)
    except (ToolError, OSError, ValueError, KeyError):
        return False


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
    """残す区間を決める(ファイルは作らない)。task: 進み具合・取り消し(画面用)、cache: 画面用、log: CLI の表示(print)。
    流れ: 指定の検査 → 動画を調べる → 字幕 → 土台(_base_spans)→ 削る区間(_drop_spans)→ 残す区間 = 土台 − 削る区間 → つなぐ・短いのを捨てる"""
    video = Path(req.video)
    min_len, join_gap = _check_request(req, video)
    meta = cache.probe(video, req.fps, req.frames) if cache else S.probe(video, req.fps, req.frames)
    fps = meta["fps"]
    src_start, src_desc, tc_warns = C.resolve_src_start(video, req.src_start_tc, meta)
    C.check_timecodes(fps, req.rec_start, src_start)   # 無音の検出・書き出しの前に確かめる
    warns = [m for m in meta["warnings"] if "開始タイムコード" not in m] + tc_warns

    tr = C.read_transcript(req.transcript) if req.transcript else None
    if tr and tr["bad"]:
        warns.append(f"文字起こしの {tr['bad']} 行は時刻が正しくないため使いませんでした。")
    cp = AC.read_cut_plan(req.plan) if req.plan else None
    cues, sub_source, cue_names, no_sub = _subtitles(req, tr, warns)
    base, selected_records, handles = _base_spans(req, meta, tr, cp, warns, task, cache, log)
    if req.snap_edges and tr:
        base = snap_base(base, tr["rows"], fps, meta["total"], warns, req.clip_range)
    elif req.clip_range:   # 余白つきの動画(LD-2f)で寄せないとき: マークの区間だけ
        base = clip_base(base, fps, meta["total"], req.clip_range, warns)
    drops = _drop_spans(req, meta, cues, tr, warns, task, cache, log)

    keeps = C.subtract(base, [x for v in drops.values() for x in v])
    keeps = C.merge_close(keeps, req.join_frames if req.join_frames is not None else C.sec_to_frames(join_gap, fps))
    keeps = C.drop_short(keeps, max(1, C.sec_to_frames(min_len, fps)))
    if not keeps:
        raise ToolError("残る区間がありません。カットの指定(無音の感度 --noise・最短の長さ --min-len など)を見直してください。")
    warns += _keep_warnings(req, keeps, fps)
    cues_out, vanished, cue_src = C.remap_cues(cues, keeps, fps, with_src=True) if cues else (None, 0, None)
    from_tr = bool(tr and sub_source == "transcript")
    return Plan(req=req, video=video, meta=meta, keeps=keeps, base=base, selected=[tuple(r["selected_frames"]) for r in selected_records],
                drops=drops, cues=cues, cues_out=cues_out, vanished=vanished, sub_source=sub_source,
                src_start=src_start, src_desc=src_desc, handles=handles, warnings=warns,
                doc=AC.plan_from_keeps(keeps, meta, selected_records, C.sec_to_frames(handles, fps)), transcript=tr,
                speaker_spans=[(r["start"], r["end"], r["speaker"]) for r in tr["rows"] if C.row_has_caption(r) and r.get("speaker")]
                if from_tr else None,
                cue_names=cue_names if from_tr else None, cue_src=cue_src, no_sub_rows=no_sub)


def _check_request(req, video):
    """指定の検査(重い処理の前に)。-> (最短の長さ, つなぐ隙間)(秒)"""
    if req.base not in BASES:
        raise ToolError(f"カットの決め方が正しくありません: {req.base}")
    for p in req.inputs():
        if not p.is_file():
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
    e = req.row_edge
    if e is not None:
        for v, what in ((e.after, "終わりを広げる上限"), (e.before, "始まりを広げる上限"), (e.pad_after, "終わりの余白"), (e.pad_before, "始まりの余白")):
            _finite(v, what + "(秒)", 0, ROW_EDGE_MAX)
        C.check_silence_params(e.noise, e.min_sil, 0.0)
    return min_len, join_gap


def _silence(cache, task, *args):
    """無音の検出(cut2resolve_core.detect_silence の引数)。画面は cache に覚えたものを使う"""
    return cache.silence(*args, task) if cache else C.detect_silence(*args, task)


def _subtitles(req, tr, warns):
    """字幕: SRT があればそれ、無ければ文字起こしの残す行のうち「字幕に出さない」(noSub)でない行
    (noSub の行の時間は、残す区間ではそのまま数える)。字幕を付けない理由は warns へ。
    -> (字幕 [(開始ms, 終了ms, 文)] か None, 字幕の元 "srt" / "transcript" / None, 字幕ごとの話者の名前 か None, noSub の行の数)"""
    if req.sub:
        cues = S.parse_subs(S.read_sub_file(Path(req.sub)))
        if not cues:
            raise ToolError("字幕を1件も読み取れませんでした(SRT/VTT の形式を確認してください)。")
        if tr:
            warns.append("字幕は SRT のほうを使いました(文字起こしはカットの判断にだけ使います)。")
        return cues, "srt", None, 0
    if not tr:
        return None, None, None, 0
    cues = C.transcript_cues(tr["rows"])
    no_sub = sum(1 for r in tr["rows"] if C.row_is_kept(r) and r["noSub"])
    if cues:
        return cues, "transcript", [r["speaker"] for r in tr["rows"] if C.row_has_caption(r)], no_sub
    warns.append(f"文字起こしの残す行がすべて「字幕に出さない」行({no_sub} 行)のため、字幕は付けません。" if no_sub
                 else "文字起こしに残す行が無いため、字幕は付けません。")
    return None, None, None, no_sub


def _clamp(base, fa, fb):
    """土台(フレームの区間)を [fa, fb] の中だけにする"""
    return [(max(x, fa), min(y, fb)) for x, y in base if min(y, fb) > max(x, fa)]


def _moved(x, x2, inward):
    """端の動き(秒)の文。inward = 区間の内へ動いたら正"""
    d = (x2 - x) if inward else (x - x2)
    if abs(d) <= SNAP_MIN:
        return "そのまま"
    return "%.1f 秒詰めた" % d if d > 0 else "%.1f 秒伸ばした" % -d


def snap_base(base, rows, fps, total, warns, span=None):
    """LD-2c・LD-2f: 土台(フレームの区間)を、区間の両端から前後 breaks.RADIUS 秒の中の話の切れ目(① breaks。行の間・句読点)の内側だけにする
    = 言葉の途中で始まる・終わる所を落とす(話が端にかかっている端だけ)。
    span = 動画の中のマークの区間(秒。余白つきの動画 = LD-2f)。None = 動画の全体(余白なし = 詰めるだけ)。
    余白つきなら、端を余白の中の切れ目へ外へも寄せられる(動画の外へは出ない)。詰めた・伸ばしたら注意に 1 行(印。元の動画は全部パックに入るので
    Resolve で戻せる)。何も残らなければ寄せない"""
    dur = C.frames_to_sec(total, fps)
    x0, x1 = (0.0, dur) if span is None else (max(0.0, float(span[0])), min(dur, float(span[1])))
    kept = [r for r in rows if not r.get("cut")]
    if not kept or dur <= 0 or x1 <= x0:
        return base if span is None else (_clamp(base, C.sec_to_frames(x0, fps), C.sec_to_frames(x1, fps)) or base)
    near = breaks.MIN_GAP   # 話が端にかかっている(端の近くまで声がある)端だけ寄せる。端の前後が静かなら動かさない
    cs = [c for c in breaks.cuts(kept) if near <= c["t"] <= dur - near]   # 動画の外の「話の前後」は切れ目にしない(端で話が切れている)
    a, b, info = breaks.snap(x0, x1, cs)
    a = max(0.0, a) if any(r["start"] < x0 + near and r["end"] > max(0.0, x0 - near) for r in kept) else x0
    b = min(dur, b) if any(r["end"] > x1 - near and r["start"] < min(dur, x1 + near) for r in kept) else x1
    whole = (C.sec_to_frames(x0, fps), C.sec_to_frames(x1, fps))
    if abs(a - x0) <= SNAP_MIN and abs(b - x1) <= SNAP_MIN:
        if span is None:
            return base
        out = _clamp(base, *whole) or base
        warns.append(margin_note(x0, dur - x1))
        return out
    out = _clamp(base, C.sec_to_frames(a, fps), C.sec_to_frames(b, fps))
    if not out:
        return base if span is None else (_clamp(base, *whole) or base)
    if span is None:
        warns.append("話の切れ目に合わせて両端を詰めました(始まり %.1f 秒・終わり %.1f 秒を落とした。切れ目: %s / %s)" % (
            a, dur - b, info["in"][2] or "なし", info["out"][2] or "なし"))
    else:
        warns.append("話の切れ目に合わせて両端を決めました(マークより始まり %s・終わり %s。切れ目: %s / %s)。%s" % (
            _moved(x0, a, True), _moved(x1, b, False), info["in"][2] or "なし", info["out"][2] or "なし", margin_note(x0, dur - x1)))
    return out


def margin_note(before, after):
    """余白つきの動画(LD-2f)の注意の 1 行(印)"""
    return "切り抜きの動画には前 %.1f 秒・後 %.1f 秒の余白があります(タイムラインはマークの区間から。Resolve で伸ばせます)" % (before, after)


def clip_base(base, fps, total, span, warns):
    """余白つきの動画(LD-2f)で話の切れ目に寄せないとき: 土台をマークの区間 span(秒)だけにする + 注意に 1 行"""
    dur = C.frames_to_sec(total, fps)
    x0, x1 = max(0.0, float(span[0])), min(dur, float(span[1]))
    out = _clamp(base, C.sec_to_frames(x0, fps), C.sec_to_frames(x1, fps)) if x1 > x0 else []
    if not out:
        return base
    warns.append(margin_note(x0, dur - x1))
    return out


def _base_spans(req, meta, tr, cp, warns, task=None, cache=None, log=None):
    """土台(残す区間の候補。フレーム)。-> (土台, 採用区間の記録(auto_cut.build_plan の selected_segments), 前後の余白(秒))"""
    fps, total = meta["fps"], meta["total"]
    if req.base == "all":
        return [(0, total)], [], 0.0
    if req.base == "list":
        base, w = C.cut_list_to_keeps(req.keep_pairs or [], fps, total)
        warns += w
        if not base:
            raise ToolError("カットリストの区間が、動画の長さの範囲に入っていません。")
        return base, [], 0.0
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
    if req.base == "rows" and req.row_edge is not None and meta.get("audio"):
        # 行の端を声の止まる所まで広げる(RowEdge)。字幕(行の時刻)は変えない。カット済の行は _drop_spans で削るので、広げた所がかかっても残らない
        args, sil = _row_edge_args(req, meta), None
        if args:
            _say(log, task, "行の端の声の止まる所を調べています…")
            try:
                sil = _silence(cache, task, *args)
            except ToolError as e:
                warns.append(f"声の止まる所を調べられなかったため、行の端に決まった余白(前 {req.row_edge.pad_before:g} 秒・"
                             f"後 {req.row_edge.pad_after:g} 秒)を付けました: {e}")
        blocks = _cut_row_frames(tr["rows"], fps, total) if req.drop_cut_rows else []
        base = widen_row_edges(base, sil, fps, total, req.row_edge, blocks)
    return base, bp["selected_segments"], handles


def _drop_spans(req, meta, cues, tr, warns, task=None, cache=None, log=None):
    """削る区間 {"list": 時刻リスト, "lines": 字幕の行(--drop-lines), "cutRows": 「カット済」の行, "silence": 無音}(フレーム)"""
    fps, total = meta["fps"], meta["total"]
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
        lines = [C.cue_frames(cues[i - 1][0], cues[i - 1][1], fps) for i in sorted(req.drop_lines) if i <= len(cues)]
        drops["lines"] = C.normalize(lines, total)
    if tr and req.drop_cut_rows:
        cut_rows = _cut_row_frames(tr["rows"], fps, total)
        if cut_rows:
            drops["cutRows"] = cut_rows
    if req.silence:
        _say(log, task, "無音を検出しています…")
        drops["silence"] = _silence(cache, task, Path(req.video), fps, total, req.noise, req.silence_min, req.silence_pad)
        _say(log, task, f"無音区間: {len(drops['silence'])}か所を削ります。")
    others = req.drop_pairs or req.drop_lines or drops.get("cutRows")
    if req.base == "all" and not (others or req.silence):
        warns.append("カットの指定がありません。動画全体を1区間として出力します。")
    elif req.base == "all" and req.silence and not others:
        # 既定の「無音で自動」だけで削れた区間が 0 か、ごくわずか(動画全体の 1% 未満)なら、
        # 何も言わずにそのまま「動画全体を1区間」のパックを作ってしまわないよう注意する(問題3)
        removed_sec = C.frames_to_sec(sum(b - a for a, b in drops.get("silence", [])), fps)
        total_sec = C.frames_to_sec(total, fps)
        if removed_sec < max(1.0, total_sec * 0.01):
            warns.append("切れる所が見つかりませんでした。「無音とみなす音量」を上げる(-30 など)か、"
                         "②残す区間・③時刻リストを試してみてください。")
    return drops


def _keep_warnings(req, keeps, fps):
    """残す区間の注意: とても短い区間(warn_short 秒より短い)・EDL の番号の上限(999)を超える"""
    warns = []
    short = [(a, b) for a, b in keeps if (b - a) * fps[1] < req.warn_short * fps[0]] if req.warn_short else []
    if short:
        eg = "・".join(f"{C.fmt_frames(a, fps)}〜{C.fmt_frames(b, fps)}({C.fmt_frames(b - a, fps)})" for a, b in short[:3])
        warns.append(f"{req.warn_short:g} 秒より短い区間が {len(short)} か所あります(元の動画の {eg}{' など' if len(short) > 3 else ''})。"
                     "意図どおりか確かめてください。")
    if len(keeps) > C.MAX_EDL_EVENTS:
        warns.append(f"残す区間が {len(keeps)} か所あり、EDL の番号が 3 桁(999)を超えます。Resolve で読めない可能性があります"
                     "(無音の長さを長くする・近い区間をつなぐ、で減らせます)。")
    return warns


def cue_speakers(plan):
    """カット後の字幕(plan.cues_out)ごとの話者の名前 = 字幕を作った文字起こしの行の話者(plan_cut の cue_names・cue_src。
    時刻で探すと、時刻が重なる行では別の人の行に当たるので、行から直接たどる)。
    話者の区間が無ければ None(字幕の並びと同じ長さの list。話者の無い字幕は None)"""
    names, src = plan.cue_names, plan.cue_src
    if not plan.cues_out or not plan.speaker_spans or names is None or src is None:
        return None
    return [(names[i] or None) if 0 <= i < len(names) else None for i in src]


def cue_order(plan, names=None):
    """同時に始まる字幕を段に入れる順(resolve_textplus.stack_captions の order): 話者の並び順(文字起こしの speakers の順)。
    話者の無い字幕・並びに無い話者は後ろ。話者が分からなければ None(入力の順)。names: cue_speakers(plan)(渡せば作り直さない)"""
    names = cue_speakers(plan) if names is None else names
    order = (plan.transcript.get("speakerOrder") or []) if isinstance(plan.transcript, dict) else []
    if not names or not order:
        return None
    rank = {n: i for i, n in enumerate(order)}
    return [rank.get(n, len(order)) for n in names]


def caption_layout(plan):
    """カット後の字幕の段(Text+ のパックと同じ規則 = resolve_textplus.stack_captions)。字幕が無ければ None。
    -> {"count": 段の数, "stacked": 2 段目より上の字幕の数, "trimmed": 切った字幕の数}(見積もり・CLI の表示用)"""
    if not plan.cues_out:
        return None
    st = TP.stack_captions(plan.cues_out, plan.meta["fps"], cue_order(plan))
    return {"count": st["count"], "stacked": st["stacked"], "trimmed": st["trimmed"]}


def describe(plan, lay=None):
    """試算の表示の行。lay: caption_layout(plan)(渡せば作り直さない)"""
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
        lay = caption_layout(plan) if lay is None else lay
        if lay and (lay["count"] > 1 or lay["trimmed"]):   # 重なる字幕があるときだけ(Text+ のパックでの置き方)
            out.append(f"重なる字幕(Text+): {lay['count']} 段・上の段へ分けた字幕 {lay['stacked']}件・終わりを切った字幕 {lay['trimmed']}件")
    if plan.no_sub_rows:
        out.append(f"字幕に出さない行: {plan.no_sub_rows}行(時間は残します)")
    out += ["注意: " + w for w in plan.warnings]
    return out


def pack_paths(video, out_dir, has_subs, render=False, copy_video=False, textplus=False, media=None,
               plan_file=True, readme_file=True):
    """パックに書くファイル {種類: パス}。media: 同梱する動画が video と違うとき(スタジオの余白つき素材)。名前は video にそろえる。
    EDL・カット後の SRT・EDL の手順書(友人へ.txt)は Text+ でないパックだけ(EDL が本体)。Text+ パックには入れない
    (「予備」は決定 3-34 で入れない。古いパックの名前は OLD_BACKUP_README)。
    plan_file: cut-plan.json をフォルダに書く(コマンド。画面・API は作業データに記録する)。
    readme_file: 手順書の「友人へ.txt」をフォルダに書く(コマンド。画面・API は書かずに画面の「手順を見る」で出す。ユーザー: 要らない)。
    動画はパックのフォルダの直下(1つだけなので分けない = ユーザー)"""
    video, out_dir = Path(video), Path(out_dir)
    media = Path(media) if media else video
    p = {}
    if not textplus:
        p["edl"] = out_dir / f"{video.stem}.edl"
        if readme_file:
            p["readme"] = out_dir / "友人へ.txt"
        if has_subs:
            p["srt"] = out_dir / f"{video.stem}_cut.srt"
    if plan_file:
        p["plan"] = out_dir / "cut-plan.json"
    if render:
        p["roughcut"] = out_dir / f"{video.stem}_roughcut.mp4"
    if copy_video or textplus:
        p["video"] = out_dir / media.name
    if textplus:
        p.update({
            "textplus_script": out_dir / "create_resolve_textplus_project.lua",
            "textplus_install": out_dir / "install_resolve_textplus_script.ps1",
            "textplus_launcher": out_dir / "ResolveにText+スクリプトを登録.bat",
            "textplus_template": out_dir / TP.TEMPLATE_NAME,
        })
        if readme_file:
            p["textplus_readme"] = out_dir / TP.README_NAME
    return p


def normalize_outputs(copy_video, textplus):
    """出力の指定のつじつま合わせ(画面の API・パックの作成・上書き確認の下見で共通。1 か所):
    Text+ パックは動画を同梱する(copy_video が真)。-> copy_video"""
    return bool(copy_video or textplus)


def edit_media_path(video, req=None, include_video=True):
    """パックに入れる余白つき素材のパス(使わないなら None)。ffprobe を使わない下見(画面の上書き確認用)"""
    if not include_video or (req is not None and not req.edit_media):
        return None
    em = C.find_edit_media(video)
    return em["path"] if em else None


def media_for_pack(plan, include_video, cache=None):
    """同梱する動画と、それに合わせた残す区間。-> dict(video, meta, keeps, src_start, edit, warnings)。
    スタジオの余白つき素材(前後に余白のある動画)があれば、それを入れて、残す区間を余白の分だけ後ろへずらす。
    Resolve でクリップの端を外へ延ばせる(カットで削った所・余白を後から戻せる)。字幕はタイムラインの位置なので変わらない。
    使えない(fps・大きさが違う・短すぎる)ときは、元の動画のままにして理由を警告に出す。
    cache: 画面用の Cache があれば、余白つき素材の媒体情報(probe)をそこで使い回す(鍵は Cache の決まり)。無ければ毎回調べる"""
    base = {"video": plan.video, "meta": plan.meta, "keeps": plan.keeps, "src_start": plan.src_start, "edit": None, "warnings": []}
    em = C.find_edit_media(plan.video) if include_video and plan.req.edit_media else None
    if not em:
        return base
    name = em["path"].name
    try:
        meta = (cache.probe if cache is not None else S.probe)(em["path"])
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
    before = C.frames_to_sec(off, fps)
    after = C.frames_to_sec(meta["total"] - off - plan.meta["total"], fps)
    info = {"path": str(em["path"]), "name": name, "selectionIn": em["selectionIn"],
            "handleBefore": round(before, 3), "handleAfter": round(max(0.0, after), 3)}
    return {"video": em["path"], "meta": meta, "keeps": keeps, "src_start": src_start, "edit": info,
            "warnings": w + [f"切り抜きスタジオの余白つき素材 {name} を入れました(Resolve でクリップの端を、前へ {before:.1f} 秒・"
                             f"後ろへ {max(0.0, after):.1f} 秒まで延ばせます)。"]}


def expected_paths(req, out_dir, has_subs, render=False, copy_video=False, textplus=False, plan_file=True, readme_file=True):
    """作る予定のファイル {種類: パス}(pack_paths。同梱する余白つき素材の名前も。ffprobe を使わない下見)"""
    copy_video = normalize_outputs(copy_video, textplus)
    media = edit_media_path(req.video, req, copy_video)
    return pack_paths(req.video, out_dir, has_subs, render, copy_video, textplus, media, plan_file, readme_file)


def planned_outputs(plan, out_dir=None, render=False, copy_video=False, textplus=False, plan_file=True, readme_file=True):
    """作る予定のファイルと、すでにあるもの(画面の上書き確認用)"""
    out_dir = Path(out_dir) if out_dir else default_out_dir(plan.video)
    paths = expected_paths(plan.req, out_dir, plan.cues_out is not None, render, copy_video, textplus, plan_file, readme_file)
    return out_dir, paths, [p for p in paths.values() if p.exists()]


def build_pack(plan, out_dir=None, render=False, copy_video=False, textplus=False, force=False, crf=C.DEFAULT_CRF,
               task=None, log=None, textplus_target=None, plan_file=True, textplus_wrap=None, readme_file=True,
               textplus_color=None, speaker_colors=None, loudness=None, volume=None, textplus_style="default", speaker_outlines=None,
               video_tracks=1, prev_copy=None, cache=None):
    """パックを作る。-> {"out_dir", "files": [(種類, パス)], "readme": 手順書の中身(書かなくても返す。画面の「手順を見る」),
    "warnings", "plan": cut-plan の中身(書かなくても返す), "videoCopy": 音量をかけて写した動画の記録(C.gain_copy_record。それ以外は None)}。
    plan_file・readme_file は pack_paths(画面・API は最小限: plan_file=False・readme_file=False。④)。Text+ パックに EDL・SRT は入れない(決定 3-34)。
    textplus_color: Text+ の文字の色 {"hex", "who"}(配信者のメンバーカラー。resolve_textplus.text_style。None = 黒い文字)。
    speaker_colors: {話者の名前: "#RRGGBB"}(A-2)。字幕の話者(cue_speakers)がここにあれば、その字幕だけ文字をその色に(無ければ textplus_color)。
    textplus_style: 字幕の見た目の種類(resolve_textplus.TEXT_STYLES のキー。"default" = けいふぉんと / "lite" = 簡易版の MS ゴシック)。
    speaker_outlines: {話者の名前: "#RRGGBB"}(簡易版)。speaker_colors と同じ決め方で、字幕ごとのふちの色にする。
    video_tracks: Text+ のタイムラインの映像トラックの数(1〜5。V1 = 動画・V2〜 = 空)。字幕はその上のトラックに置く。
    loudness: 聞こえ方の音量をそろえる目標(LUFS。ytt/loudness.py の CHOICES。None = そろえない)。**カットで残す区間だけ**を測り、
    同梱する動画は音声だけ作り直して(映像はそのまま)、粗編集の動画も同じ量で書き出す。元の動画は書き換えない。
    volume: 音量(%。元 = 100)。loudness が無いときだけ、測らずにその量をかける(LUFS が分からない人向け。スタジオの書き出しの「音量 %」と同じ)
    prev_copy: 前にこのフォルダへ作ったパックの記録の videoCopy(serve.py が作業データの packs/ から読んで渡す。コマンドは渡さない = 毎回作り直す)。
    音量をかけて写すとき、これと今の条件(元の動画・かける量・書き出しの設定)が同じで、置き場所の動画も記録のままなら作り直さない(E-15 の続き。_stage_video)
    cache: 画面用の Cache(余白つき素材の媒体情報を覚えた物)。media_for_pack に渡す。None = 毎回調べる
    重いもの(粗編集の mp4・元動画のコピー)は出力フォルダの中の一時的な名前で作り、最後に名前を付け替える
    (途中で失敗・取り消したとき、以前のパックを半端に壊さない・書きかけを残さない)"""
    if isinstance(crf, bool) or not isinstance(crf, int) or not 0 <= crf <= 51:
        raise ToolError("粗編集の画質(--crf)は 0〜51 の整数で指定してください。")
    try:
        video_tracks = TP.video_tracks_value(video_tracks)
    except ValueError as e:
        raise ToolError(str(e))
    if textplus_style not in TP.TEXT_STYLES:
        raise ToolError("Text+ の字幕の見た目 %r は使えません(%s のどれか)。" % (textplus_style, " / ".join(TP.TEXT_STYLES)))
    if textplus and not plan.cues_out:
        raise ToolError("Text+ 用パックには字幕が必要です。SRT または文字起こしを指定してください。")
    video, meta, fps = plan.video, plan.meta, plan.meta["fps"]
    out_dir = Path(out_dir) if out_dir else default_out_dir(video)
    if out_dir.exists() and not out_dir.is_dir():
        raise ToolError(f"出力先がフォルダではありません: {out_dir}")
    copy_video = normalize_outputs(copy_video, textplus)
    m = media_for_pack(plan, copy_video, cache)   # 同梱する動画(余白つき素材なら、残す区間もそれに合わせる)。cache は画面用(probe を覚える)
    mvideo, mmeta, mkeeps = m["video"], m["meta"], m["keeps"]
    paths = pack_paths(video, out_dir, plan.cues_out is not None, render, copy_video, textplus, mvideo, plan_file, readme_file)
    C.validate_output_paths(list(paths.values()), force, protected=plan.req.inputs() + ((mvideo,) if m["edit"] else ()))
    req = plan.req
    warnings = list(m["warnings"])
    if "edl" in paths:   # 動画のファイル名の注意は EDL を書くときだけ(EDL がファイル名で元動画と結び付くため。ユーザー決定。試算 plan_cut には入れない)
        warnings += C.name_warnings(video)
    stale = _stale_warning(video, out_dir, paths, mvideo)
    if stale:
        warnings.append(stale)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = secrets.token_hex(4)
    staged = []
    same = copy_video and S.same_path(paths["video"], mvideo)
    copy_key = None   # 音量をかけて写したときの条件(パックの記録の videoCopy にする)
    try:
        loud, gain, w = _pack_gain(loudness, volume, render, copy_video, same, m, task, log)   # 画面に出す結果と、かける量(dB)
        warnings += w
        if render:
            _say(log, task, "粗編集の動画を書き出しています…(時間がかかります)")
            tmp = out_dir / f".c2r-{tag}-{paths['roughcut'].name}"
            C.render_rough_cut(video, plan.keeps, fps, bool(meta["audio"]), tmp, crf, task, gain_db=gain)
            staged.append((tmp, paths["roughcut"], "roughcut"))
        if copy_video and not same:
            paths["video"].parent.mkdir(parents=True, exist_ok=True)
            tmp, skipped, copy_key = _stage_video(m, out_dir, paths["video"], out_dir / f".c2r-{tag}-{mvideo.name}", gain, prev_copy,
                                                  task, log)
            if tmp:
                staged.append((tmp, paths["video"], "video"))
            else:
                warnings.append(skipped)
        if task:
            task.check()
        extras = []   # EDL の手順書(友人へ.txt)に載せる追加のファイル(EDL を書くのは Text+ でないパックだけ)
        if plan_file:
            extras.append(("cut-plan.json", "カットの記録(残す・削る区間)。ツールで読み直す用で、Resolve では使いません"))
        files = {}
        if "edl" in paths:   # EDL・カット後の SRT・EDL の手順書(Text+ でないパックだけ = EDL が本体)
            files = C.write_pack(out_dir, mvideo, mmeta, mkeeps, plan.cues_out, req.reel, req.rec_start,
                                 m["src_start"], paths.get("roughcut"), req.name, extras, readme_path=paths.get("readme", False),
                                 stem=video.stem)
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
            fsio.replace_retry(str(tmp), str(final))
            files[kind] = final
            staged.pop(0)
        if textplus:
            # 字幕ごとの色は、余白つき素材に置き換える前の計画(元の動画の時刻 = 文字起こしの時刻)で決める。字幕の並びは置き換えても同じ
            # 重なる字幕の段(TP.stack_captions)は字幕の並びを変えないので、色・ふちは字幕の並びのまま合う。同時に始まる字幕は話者の並び順(cue_order)
            names = cue_speakers(plan)
            fills, outlines, order = _cue_rgba(names, speaker_colors), _cue_rgba(names, speaker_outlines), cue_order(plan, names)
            tplan = plan if not m["edit"] else dataclasses.replace(
                plan, video=mvideo, meta=mmeta, keeps=mkeeps, req=dataclasses.replace(req, name=req.name or video.stem))
            files.update(TP.write_files(paths, tplan, out_dir, textplus_target, wrap=textplus_wrap,
                                        color=textplus_color, fills=fills, outlines=outlines, style=textplus_style,
                                        video_tracks=video_tracks, order=order))
    finally:
        for tmp, _, _ in staged:
            fsio.unlink_quiet(tmp)
    if copy_video and "video" not in files:
        files["video"] = paths["video"]
    # 付け替えたあとの置き場所の動画を記録に(次に同じ条件なら作り直さない)。量の決め方は人が読む用
    how = {"loudness": loudness} if loudness is not None else {"volume": volume}
    video_copy = C.gain_copy_record(copy_key, paths["video"], **how) if copy_key else None
    ordered = [(k, files[k]) for k in PACK_FILE_KINDS if k in files]
    # 画面に出す手順書: Text+ パックは Text+ の手順・それ以外は EDL の手順。ファイルに書かなかったときも中身は返す
    # (書いた側が files["readme_text"] に入れる。Text+ パックは EDL を書かないので Text+ の手順だけ)
    return {"out_dir": out_dir, "files": ordered, "readme": files["readme_text"], "warnings": warnings, "editMedia": m["edit"],
            "mediaKeeps": [list(x) for x in mkeeps], "plan": doc, "loudness": loud, "videoCopy": video_copy}


def _stage_video(m, out_dir, final, tmp, gain, prev_copy, task=None, log=None):
    """パックの動画(m = media_for_pack の結果)を一時の名前 tmp に写す(置き場所 final への付け替えは build_pack の最後)。
    -> (写した一時ファイル か None = 写さなかった, 写さなかったときの注意の文, 音量をかけたときの条件 C.gain_copy_key か None)。
    置き場所に前に写した同じ動画があれば写さない(E-15): 音量をかけないときは大きさ・更新日時が元と同じ(C.same_copy)、
    かけるときは前のパックの記録 prev_copy と条件・置き場所の動画が同じ(C.same_gain_copy)"""
    mvideo, mmeta = m["video"], m["meta"]
    if not gain:
        _say(log, task, "元動画をコピーしています…")
        tmp = C.copy_video(mvideo, out_dir, task, dst=tmp, final=final)
        return tmp, None if tmp else C.COPY_SKIPPED.format(final.name), None
    key = C.gain_copy_key(mvideo, final, gain, mmeta)
    if C.same_gain_copy(key, final, prev_copy):
        return None, C.GAIN_COPY_SKIPPED.format(final.name, gain), key
    _say(log, task, "音量をそろえて(%+.1f dB)元動画を写しています…" % gain)
    C.copy_video_gain(mvideo, tmp, gain, task, mmeta.get("duration"), meta=mmeta)
    return tmp, None, key


def _stale_warning(video, out_dir, paths, mvideo):
    """前に作ったかもしれない・今回は作らないファイルがフォルダに残っていれば、その注意の文(無ければ None)"""
    known = pack_paths(video, out_dir, True, render=True, textplus=True)
    known["old_fcpxml"] = out_dir / f"{video.stem}_cut.fcpxml"           # 古いパックの FCPXML(今は作らない)
    known["old_video"] = out_dir / OLD_MEDIA_DIR / mvideo.name        # 古い Text+ パックの動画の場所
    # 古い Text+ パックの予備(EDL・カット後の SRT・予備の手順書。決定 3-34)。Text+ でないパックでは EDL・SRT は今の中身
    known.update(old_edl=out_dir / f"{video.stem}.edl", old_srt=out_dir / f"{video.stem}_cut.srt", old_backup_readme=out_dir / OLD_BACKUP_README)
    now = set(paths.values())   # 種類の名前ではなくパスで比べる(Text+ でないパックの EDL・SRT・友人へ.txt を「残っている」と言わない)
    stale = [p for p in dict.fromkeys(known.values()) if p not in now and p.exists()]
    if stale:
        return ("前に作った " + "・".join(p.relative_to(out_dir).as_posix() for p in stale) + " がフォルダに残っています"
                "(今回のカットとは合いません。要らなければ消してください)。")
    return None


def _pack_gain(loudness, volume, render, copy_video, same, m, task=None, log=None):
    """同梱の動画・粗編集の動画の音量。loudness(目標の LUFS)= 残す区間だけ測ってそろえる、volume(%)= 測らずにその量をかける。
    same: パックの動画が元の動画と同じ場所(元の動画は書き換えないので、写さない動画にはかけない)。m: media_for_pack の結果。
    -> (画面に出す結果 か None, かける量(dB), 注意の文の list)"""
    same_msg = "パックの動画が元の動画と同じ場所です(元の動画は書き換えません)"
    mmeta = m["meta"]
    if loudness is not None:
        if not (render or (copy_video and not same)):
            if not same:
                return None, 0.0, []
            loud = {"target": loudness, "skipped": same_msg}
        elif not mmeta["audio"]:
            loud = {"target": loudness, "skipped": "音声の無い動画です"}
        else:
            _say(log, task, "残す区間の音量を測っています…")
            mf = mmeta["fps"]
            spans = [(C.frames_to_sec(a, mf), C.frames_to_sec(b, mf)) for a, b in m["keeps"]]
            i, tp = C.measure_loudness(m["video"], spans, task, sum(b - a for a, b in spans) or None)
            if i is not None:
                gain = LD.gain(loudness, i, tp)
                gain = gain if abs(gain) >= LD.MIN_GAIN_DB else 0.0
                return LD.result(loudness, i, gain), gain, []
            loud = {"target": loudness, "skipped": "無音のため測れませんでした"}
        return loud, 0.0, ["音量はそろえませんでした(%s)。" % loud["skipped"]]
    if not volume or volume == 100 or not (render or copy_video):
        return None, 0.0, []
    if same and not render:
        return {"volume": volume, "skipped": same_msg}, 0.0, ["音量は変えませんでした(%s)。" % same_msg]
    if not mmeta["audio"]:
        return {"volume": volume, "skipped": "音声の無い動画です"}, 0.0, []
    gain = LD.pct_to_db(volume)
    return {"volume": volume, "gainDb": gain}, gain, []


def _cue_rgba(names, colors):
    """字幕ごとの話者の名前 → 字幕ごとの色 [r, g, b, a](その話者の色が無い字幕は None)。名前か色の対応が無ければ None"""
    if not names or not colors:
        return None
    return [TP.hex_rgba(colors.get(n)) if n and colors.get(n) else None for n in names]


# ---------------------------------------------------------------- 画面に返す形(JSON)

def _sec(n, fps):
    return round(C.frames_to_sec(n, fps), 6)


def summary(plan, limit=5000):
    """試算の結果(画面のタイムライン・一覧・合計に使う)。区間はフレーム [開始, 終了)、fps で秒に直せる"""
    m, fps, total = plan.meta, plan.meta["fps"], plan.meta["total"]
    kept = sum(e - s for s, e in plan.keeps)
    subs = None
    if plan.cues is not None:
        subs = {"source": plan.sub_source, "in": len(plan.cues), "out": len(plan.cues_out), "vanished": plan.vanished,
                "cues": [[*C.cue_frames(a, b, fps), t[:80]] for a, b, t in plan.cues[:limit]]}
    rows = None
    if plan.transcript:
        rows = [[C.sec_to_frames(r["start"], fps), C.sec_to_frames(r["end"], fps), bool(r["cut"]), bool(C.row_is_kept(r))]
                for r in plan.transcript["rows"][:limit]]
    lay = caption_layout(plan)
    text = "\n".join(describe(plan, lay))
    lay = lay or {"count": 0, "stacked": 0, "trimmed": 0}
    return {
        "fps": list(fps), "fpsValue": fps[0] / fps[1], "total": total, "durationSec": _sec(total, fps),
        "keeps": [list(x) for x in plan.keeps], "removed": [list(x) for x in plan.doc["removed_frames"]],
        "keepsSec": [[_sec(a, fps), _sec(b, fps)] for a, b in plan.keeps],   # 残す区間(秒)。「編集」のたたき台はこれで今の編集を置き換える
        "selected": [list(x) for x in plan.selected], "base": [list(x) for x in plan.base],
        "drops": {k: [list(x) for x in v][:limit] for k, v in plan.drops.items()},
        "count": len(plan.keeps), "keptFrames": kept, "keptSec": _sec(kept, fps), "removedSec": _sec(total - kept, fps),
        "keptPercent": round(kept * 100 / total, 1),
        "handles": plan.handles, "baseKind": plan.req.base,
        "srcStart": plan.src_start, "srcStartDesc": plan.src_desc, "recStart": plan.req.rec_start,
        "subtitles": subs, "transcriptRows": rows, "warnings": plan.warnings,
        "text": text,
        # Text+ のパックでの字幕の段(重なる字幕。resolve_textplus.stack_captions): 段の数(字幕が無ければ 0)・上の段へ分けた字幕の数・終わりを切った字幕の数
        "captionLanes": lay["count"], "captionsStacked": lay["stacked"], "captionsTrimmed": lay["trimmed"],
        "noSubRows": plan.no_sub_rows,   # 字幕に出さなかった行(noSub)の数。時間は残す区間に数えてある
    }
