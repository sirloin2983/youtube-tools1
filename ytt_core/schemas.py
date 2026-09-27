"""受け渡しの形式(docs/pipeline.md の 1・2)。youtube-tools-clip/v1 は、スタジオが書き(build_clip)、文字起こしが読む(load_clip_file)。
transcript/v1・cut-plan/v1 の組み立ては文字起こしツールの行の規則に依存するので、文字起こしの pipeline_io.py に残している。"""
import datetime
import json
import math
import os

from . import fsio

CLIP_SCHEMA = "youtube-tools-clip/v1"
TRANSCRIPT_SCHEMA = "youtube-tools-transcript/v1"
CUT_PLAN_SCHEMA = "youtube-tools-cut-plan/v1"
CLIP_SUFFIX = ".clip.json"
MAX_CLIP_BYTES = 256 * 1024   # .clip.json の上限(中身は数百バイト。巨大なファイルを読まない)
CLIP_MARK_SRCS = ("auto", "manual", "collab")


def iso_now():
    """書いた日時(ISO 8601・時差付き・秒まで。例: 2026-09-24T12:00:00+09:00)。"""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def num(v):
    """有限の数(bool は除く)なら float、それ以外は None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _r3(x):
    return None if x is None else round(float(x), 3)


# ---------- 途中のファイルの置き場所(2026-09-27。docs/followup-2026-09-27.md の 1) ----------
# 出力先(動画のフォルダ)の直下に並べるのはパックと元動画(書き出した切り抜き)だけ(ユーザー決定)。それ以外の途中のファイル
# (.clip.json・.edit.json・_edit.mp4・.transcript.json・.srt・.cut-plan.json・.studio-id)は下のフォルダ「作業用」に書く。
# 以前の置き方(動画の隣)のファイルは動かさない。読む側は「作業用/ → 動画の隣」の順に探す(find_sidecar)。
# cut2resolve(ytt_core を読まないコマンドもある)は cut2resolve_core.WORK_DIR に同じ名前を持つ(test_serve が同じか確かめる)
WORK_DIR = "作業用"


def work_dir(media_path):
    """動画の途中のファイルを書くフォルダ: 動画のフォルダの 作業用/(動画がもう 作業用 の中なら、そのフォルダ。_edit.mp4 など)"""
    folder = os.path.dirname(os.path.abspath(media_path))
    return folder if os.path.basename(folder) == WORK_DIR else os.path.join(folder, WORK_DIR)


def media_folder(sidecar_path):
    """途中のファイル → 動画のフォルダ(作業用 の中なら1つ上)"""
    folder = os.path.dirname(os.path.abspath(sidecar_path))
    return os.path.dirname(folder) if os.path.basename(folder) == WORK_DIR else folder


def sidecar_path(media_path, suffix):
    """途中のファイルを書く場所(動画_0012.mp4 + .clip.json → 作業用/動画_0012.clip.json)"""
    return os.path.join(work_dir(media_path), os.path.splitext(os.path.basename(media_path))[0] + suffix)


def sidecar_candidates(media_path, suffix):
    """途中のファイルを読む場所の候補(作業用/ → 以前の置き方 = 動画の隣)"""
    new, old = sidecar_path(media_path, suffix), os.path.splitext(os.path.abspath(media_path))[0] + suffix
    return [new] if os.path.normcase(new) == os.path.normcase(old) else [new, old]


def find_sidecar(media_path, suffix):
    """候補のうち、あるもの(無ければ None)。ネットワーク上のパスかどうかは呼び出し側で確かめる"""
    for p in sidecar_candidates(media_path, suffix):
        try:
            if os.path.isfile(p):
                return p
        except (OSError, ValueError):
            continue
    return None


# ---------- youtube-tools-clip/v1 ----------
def clip_path_for(media_path):
    """.clip.json を書くパス(作業用/ の中。動画_0012.mp4 → 作業用/動画_0012.clip.json)。読むときは find_clip_path"""
    return sidecar_path(media_path, CLIP_SUFFIX)


def find_clip_path(media_path):
    """動画の .clip.json(作業用/ → 以前の置き方 = 動画の隣)。無ければ None"""
    return find_sidecar(media_path, CLIP_SUFFIX)


def build_clip(media_path, duration, source, rng, mark, export, tool):
    """切り抜き1本ぶんの youtube-tools-clip/v1 を組み立てる。
    source: {"kind": "youtube"|"file", "videoId", "title", "path"(file のときだけ元のファイル)}
    rng: (元の配信での開始秒, 終了秒)。mark: {"id","label","status","src"}。export: {"mode": "precise"|"fast", ...}。tool: {"name","version"}。
    API キーなどの秘密や、元動画以外の個人のパスは入れない(ここに渡さない)。"""
    kind = "file" if source.get("kind") == "file" else "youtube"
    vid = str(source.get("videoId") or "")
    src = {"kind": kind, "videoId": vid,
           "url": ("https://www.youtube.com/watch?v=" + vid) if kind == "youtube" and vid else None,
           "title": str(source.get("title") or ""), "path": source.get("path") if kind == "file" else None}
    return {"schema": CLIP_SCHEMA, "tool": {"name": str(tool.get("name", "")), "version": str(tool.get("version", ""))}, "createdAt": iso_now(),
            "media": {"path": os.path.abspath(media_path), "name": os.path.basename(media_path), "durationSec": _r3(duration)},
            "source": src,
            "range": {"start": _r3(rng[0]), "end": _r3(rng[1])},
            "mark": {"id": str(mark.get("id") or ""), "label": str(mark.get("label") or ""), "status": str(mark.get("status") or ""),
                     "src": mark.get("src") if mark.get("src") in CLIP_MARK_SRCS else "manual"},
            "export": dict(export)}


def validate_clip(obj):
    """(clip, 警告)。使えるときは (中身の複製, None)、使えないときは (None, 理由)。
    知らない項目は残す(前方互換。transcript/v1 に「中身そのもの」を入れる約束のため)。範囲(range)が正しくないものは使わない。"""
    if not isinstance(obj, dict):
        return None, ".clip.json の形式が正しくありません(JSON のオブジェクトではありません)"
    schema = obj.get("schema")
    if schema != CLIP_SCHEMA:
        if isinstance(schema, str) and schema.startswith("youtube-tools-clip/"):
            return None, ".clip.json は未対応の版です(%s。このツールが読めるのは %s)" % (schema[:40], CLIP_SCHEMA)
        return None, ".clip.json の schema が %s ではありません" % CLIP_SCHEMA
    rng = obj.get("range")
    a, b = (num(rng.get("start")), num(rng.get("end"))) if isinstance(rng, dict) else (None, None)
    if a is None or b is None or a < 0 or b <= a:
        return None, ".clip.json の range(元の配信の範囲)が正しくありません"
    for key in ("source", "media", "mark", "export", "tool"):
        if key in obj and obj[key] is not None and not isinstance(obj[key], dict):
            return None, ".clip.json の %s の形式が正しくありません" % key
    ex = obj.get("export") or {}
    if "actualStart" in ex and ex["actualStart"] is not None:
        v = num(ex["actualStart"])
        if v is None or v < 0:
            return None, ".clip.json の export.actualStart が正しくありません"
    return json.loads(json.dumps(obj, ensure_ascii=False)), None   # 呼び出し側が書き換えても元に響かないよう複製


def clip_offset(clip):
    """切り抜きの中の時刻 t が、元の配信では offset + t になる offset(export.actualStart があれば優先)。"""
    ex = clip.get("export") or {}
    v = num(ex.get("actualStart")) if isinstance(ex, dict) else None
    return v if v is not None and v >= 0 else float(clip["range"]["start"])


def load_clip_file(path, max_bytes=MAX_CLIP_BYTES):
    """(clip, 警告)。読めない・壊れている・別の版なら (None, 理由)。"""
    try:
        obj = fsio.read_json_file(path, max_bytes)
    except (OSError, UnicodeError, ValueError) as e:
        return None, ".clip.json を読めません(%s)" % (e.__class__.__name__ if isinstance(e, OSError) else str(e)[:80])
    return validate_clip(obj)
