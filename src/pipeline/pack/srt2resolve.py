#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""srt2resolve v0.1.4

動画 + 字幕(SRT/VTT)から、DaVinci Resolve に読み込める編集可能なデータを作る。

出力(動画と同じ場所の <動画名>_resolve フォルダ):
  <動画名>.fcpxml  動画を並べたタイムライン + 字幕を1行ずつ「タイトル」として配置したもの
  <動画名>.srt     フレーム境界に丸めた字幕(FCPXML の字幕が期待どおり出ないとき用の予備)

依存: Python 3.9+(標準ライブラリのみ) と ffprobe(ffmpeg に同梱)。
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

try:   # 全体の版(ytt/version.py の 1 か所)。単独のコマンドのときは src を足して読む
    from ytt.version import VERSION
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ytt.version import VERSION
from ytt import fsio
from ytt import tools as _ytools   # ffmpeg / ffprobe の場所(PATH → winget。RS7-1 F-k)

# 編集ソフトで一般的なフレームレート。動画の実測値をこれに丸める
STD_FPS = [(24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1),
           (48, 1), (50, 1), (60000, 1001), (60, 1)]
SUB_EXTS = {".srt", ".vtt"}
MAX_SUB_BYTES = 5 * 1024 * 1024
SEQ_AUDIO_RATE = {32000: "32k", 44100: "44.1k", 48000: "48k", 88200: "88.2k", 96000: "96k"}
TC_RE = re.compile(r"\d{1,2}[:;]\d{2}[:;]\d{2}[:;]\d{2}")


class ToolError(Exception):
    """利用者に見せる想定のエラー(原因と対処を書く)"""


def same_path(a, b):
    """同じファイルを指すか(Windows の大文字小文字・区切りの違いも同じとみなす)。どちらかが None なら False"""
    if a is None or b is None:
        return False
    try:
        if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(str(Path(a).resolve()))) == os.path.normcase(os.path.abspath(str(Path(b).resolve())))


@contextlib.contextmanager
def staged(dst, suffix=".part"):
    """dst の隣に作った一時ファイルのパスを渡す。with の中で書き終えて(ffmpeg の出力先にしてもよい)普通に抜けたら dst へ付け替える。
    失敗・取り消しで抜けたら一時ファイルを消す(書きかけを残さない。付け替え前の dst は壊さない)。書きかけの一時ファイルは「.tmp-」で始まる"""
    fd, tmp = tempfile.mkstemp(dir=arg_path(Path(dst).parent), prefix=".tmp-", suffix=suffix)
    os.close(fd)
    try:
        yield tmp
        fsio.replace_retry(tmp, str(dst))
    finally:
        fsio.unlink_quiet(tmp)   # 付け替えたあとは無い


def write_text_atomic(path, text, encoding="utf-8", newline="\n"):
    """Path.write_text と同じ引数(newline: "\n" はそのまま、"" は変換なし)。中身は一時ファイル経由で置き換える"""
    if newline is None:
        newline = os.linesep
    if newline not in ("", "\n"):
        text = text.replace("\n", newline)
    fsio.atomic_write(path, text.encode(encoding), fsync_required=True)   # 書きかけを Resolve・他のツールに読ませない(docs/spec/pipeline.md の 1)


def tool(name):
    """ffmpeg / ffprobe の実行ファイルのパス(ytt/tools.media_tool。見つからなければ名前のまま = 呼ぶと FileNotFoundError)"""
    return _ytools.media_tool(name)


def arg_path(p):
    """ffmpeg / ffprobe に渡すパス。絶対パスにする(「-」で始まる相対パスがオプションと解釈されるのを防ぐ。
    Windows の絶対パスは「C:\\」、Linux/Mac は「/」で始まるので、オプションと取り違えられない)"""
    return os.path.abspath(str(p))


# ---------------------------------------------------------------- 字幕の読み込み

_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
_ARROW = re.compile(r"^\s*(\S+)\s*-->\s*(\S+)")
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_ASS = re.compile(r"\{\\[^}]*\}")
# XML 1.0 で使えない制御文字。残すと Resolve が読み込みに失敗する
_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def _ts_ms(s):
    m = _TS.fullmatch(s)
    if not m:
        return None
    h = int(m.group(1) or 0)
    return ((h * 60 + int(m.group(2))) * 60 + int(m.group(3))) * 1000 + int(m.group(4).ljust(3, "0"))


def clean_text(t):
    t = _ASS.sub("", _TAG.sub("", t))
    t = _BAD.sub("", t)
    lines = [ln.strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def parse_subs(text):
    """SRT / VTT のテキスト -> [(start_ms, end_ms, text)]。読めないブロックは黙って飛ばす"""
    text = text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        found = None
        for i, ln in enumerate(lines):
            m = _ARROW.match(ln)
            if m:
                found = (i, m)
                break
        if not found:
            continue  # WEBVTT ヘッダ・NOTE・番号だけのブロック
        i, m = found
        a, b = _ts_ms(m.group(1)), _ts_ms(m.group(2))
        if a is None or b is None:
            continue
        body = clean_text("\n".join(lines[i + 1:]))
        if body:
            cues.append((a, b, body))
    return cues


def read_sub_file(path):
    if path.stat().st_size > MAX_SUB_BYTES:
        raise ToolError(f"字幕ファイルが大きすぎます(上限 {MAX_SUB_BYTES // 1024 // 1024}MB): {path.name}")
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp932"):  # 日本語 Windows のメモ帳保存(Shift_JIS)も拾う
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ToolError("字幕ファイルの文字コードを判別できません。UTF-8 で保存し直してください。")


# ---------------------------------------------------------------- 動画の情報

def _frac(s):
    try:
        f = Fraction(s)
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def snap_fps(fr):
    """実測 fps を標準値へ。近い標準値が無ければ (分数, True)=独自レートとして返す"""
    best = min(STD_FPS, key=lambda s: abs(Fraction(*s) - fr))
    if abs(Fraction(*best) - fr) / fr <= Fraction(3, 1000):
        return best, False
    f = fr.limit_denominator(1001)
    return (f.numerator, f.denominator), True


_EDIT_FRIENDLY_CODECS = ("prores", "dnxhd", "dnxhr", "cfhd", "v210", "v410")


def codec_warnings(codec, pix_fmt):
    """無料版の DaVinci Resolve で読めないことが多い形式の警告(コンテナが .mov/.mp4 かは関係ない)"""
    if codec in ("vp9", "av1"):
        return [f"映像のコーデックが {codec} です。無料版の DaVinci Resolve では再生できないことがあります。"
                "H.264(8bit)の mp4 か mov に変換してください。"]
    if codec in ("hevc", "h265"):
        return ["映像のコーデックが H.265(HEVC)です。無料版の DaVinci Resolve では再生できないことがあります。"
                "H.264(8bit)に変換してください。"]
    if codec == "h264" and any(k in pix_fmt for k in ("10", "422", "444")):
        return [f"H.264 ですが形式が {pix_fmt} です(10bit や 4:2:2 など)。無料版の DaVinci Resolve では"
                "再生できないことがあります。yuv420p(8bit)に変換してください。"]
    # そのほかのコーデックでも 10bit(yuv420p10le・p010le など)は無料版で読めないことがある。ProRes・DNxHD などの編集用の形式は 10bit でも読めるので除く
    if (re.search(r"10(le|be)$", pix_fmt) or pix_fmt.startswith("p010")) and codec not in _EDIT_FRIENDLY_CODECS:
        return [f"映像が 10bit({pix_fmt})です。無料版の DaVinci Resolve では再生できないことがあります。"
                "yuv420p(8bit)の H.264 に変換してください。"]
    return []


def _exact_frames(video, v):
    """映像ストリームの実際のフレーム数。取れなければ None。
    コンテナの長さ(音声が長い動画だと映像より長い)から計算すると、Resolve が読む長さとずれて
    「タイムコードの範囲が一致しない」で取り込みに失敗するため、映像そのものの数を使う。"""
    nb = v.get("nb_frames")
    if isinstance(nb, str) and nb.isdigit() and int(nb) > 0:
        return int(nb)
    print("フレーム数を数えています…(長い動画は少し時間がかかります)", flush=True)
    cmd = [tool("ffprobe"), "-v", "error", "-select_streams", str(v["index"]), "-count_packets",
           "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", arg_path(video)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600, stdin=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"\s*(\d+)", r.stdout or "")
    return int(m.group(1)) if r.returncode == 0 and m and int(m.group(1)) > 0 else None


def probe(video, fps_override=None, frames_override=None):
    cmd = [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", arg_path(video)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise ToolError("ffprobe が見つかりません。ffmpeg をインストールして PATH に通してください。")
    except subprocess.TimeoutExpired:
        raise ToolError("ffprobe が 60 秒で終わりませんでした。動画ファイルを確認してください。")
    if r.returncode != 0:
        raise ToolError(f"動画を読めませんでした: {r.stderr.strip()[:200]}")
    try:
        info = json.loads(r.stdout or "{}")
    except ValueError:
        raise ToolError("動画の情報(ffprobe の出力)を読めませんでした。")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    if v is None:
        raise ToolError("動画ストリームが見つかりません。")
    warnings = []

    try:
        w, h = int(v["width"]), int(v["height"])
    except (KeyError, TypeError, ValueError):
        raise ToolError("動画の幅・高さを取得できません(映像のストリームが壊れているかもしれません)。")
    rot = (v.get("tags") or {}).get("rotate")
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = sd["rotation"]
    try:
        if rot is not None and abs(int(float(rot))) % 180 == 90:
            w, h = h, w  # スマホ縦撮り: 表示上の向きに合わせる
    except (TypeError, ValueError):
        pass

    avg, rfr = _frac(v.get("avg_frame_rate")), _frac(v.get("r_frame_rate"))
    fr = _frac(fps_override) if fps_override else (avg or rfr)
    if fr is None:
        raise ToolError("フレームレートを取得できません。--fps 30 のように指定してください。")
    vfr = bool(not fps_override and avg and rfr and abs(avg - rfr) / rfr > Fraction(1, 100))
    if vfr:
        warnings.append("可変フレームレート(VFR)の動画です。カット位置・字幕が数フレームずれることがあります。"
                        "気になる場合は固定フレームレートに変換してから使ってください。")
    fps, custom = snap_fps(fr)
    if custom:
        warnings.append(f"標準的でないフレームレート({float(fr):.3f}fps)です。")

    dur = None
    for cand in (v.get("duration"), (info.get("format") or {}).get("duration")):
        try:
            if float(cand) > 0:
                dur = float(cand)
                break
        except (TypeError, ValueError):
            pass
    if dur is None:
        raise ToolError("動画の長さを取得できません。")
    dur_frames = int(round(dur * fps[0] / fps[1]))
    total, source = dur_frames, "長さから計算"
    if frames_override:
        total, source = frames_override, "指定"
    elif not vfr:  # 可変フレームレートは「数」より「長さ」のほうが Resolve の解釈に近い
        exact = _exact_frames(video, v)
        if exact:
            total, source = exact, "実測"
            if abs(exact - dur_frames) > 2:
                warnings.append(f"映像({exact}フレーム)と動画全体の長さ({dur_frames}フレーム)が違います"
                                "(音声のほうが長い動画など)。映像の長さで作りました。")
    if total < 1:
        raise ToolError("動画が短すぎます。")
    tcs = timecode_tags(info)
    tc = next((t for t in tcs if t), None)
    if tc and not re.fullmatch(r"[0:;.]+", tc):
        warnings.append(f"この動画には開始タイムコード({tc})が埋め込まれています。"
                        "Resolve 側の開始位置とずれて、取り込めないことがあります。")

    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    audio = None
    if a:
        try:
            audio = (int(a.get("channels") or 2), int(a.get("sample_rate") or 48000))
        except ValueError:
            audio = (2, 48000)
    codec = (v.get("codec_name") or "").lower()
    pix_fmt = (v.get("pix_fmt") or "").lower()
    warnings.extend(codec_warnings(codec, pix_fmt))
    return {"w": w, "h": h, "fps": fps, "total": total, "frames_source": source,
            "codec": codec, "pix_fmt": pix_fmt, "audio": audio, "warnings": warnings,
            "vfr": vfr, "duration": dur, "start_tc": start_tc_from(tcs)}


def timecode_tags(info):
    """ffprobe の結果(-show_streams -show_format の JSON)の timecode のタグ。ストリームの順 → 最後にコンテナ(無い所は None)"""
    tcs = [(s.get("tags") or {}).get("timecode") for s in info.get("streams", [])]
    return tcs + [((info.get("format") or {}).get("tags") or {}).get("timecode")]


def start_tc_from(tcs):
    """開始タイムコード(HH:MM:SS:FF の形のものだけ。無ければ None)。Resolve はこれをクリップの Start TC にする"""
    return next((t.strip() for t in tcs if t and TC_RE.fullmatch(t.strip())), None)


# ---------------------------------------------------------------- 時刻の変換

def nominal_rate(fps):
    """タイムコードで数える1秒のフレーム数(29.97 → 30、59.94 → 60。ノンドロップ)"""
    return max(1, int(round(fps[0] / fps[1])))


def tc_to_frames(tc, nominal):
    if ";" in tc:
        raise ToolError("ドロップフレーム(; 区切り)のタイムコードは未対応です。")
    m = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2}):(\d{2})", tc.strip())
    if not m:
        raise ToolError(f"タイムコードを読めません(HH:MM:SS:FF の形式): {tc!r}")
    h, mi, s, f = (int(x) for x in m.groups())
    if mi >= 60 or s >= 60 or f >= nominal:
        raise ToolError(f"タイムコードの値が範囲外です: {tc!r}")
    return ((h * 60 + mi) * 60 + s) * nominal + f


def frames_to_tc(n, nominal):
    """ノンドロップのタイムコード。29.97/59.94 も呼び名どおりの 30/60 で数える(Resolve の既定と同じ)"""
    s = n // nominal
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{n % nominal:02d}"


def start_tc_frames(tc, fps):
    """開始タイムコード → 元動画の先頭のフレーム番号(タイムコードの数え方)。(フレーム, 警告)。
    ドロップフレーム表記(;)はノンドロップとして読み替えて警告する(EDL と同じ扱い)"""
    if not tc:
        return 0, []
    warns = []
    if ";" in tc:
        warns.append(f"開始タイムコード {tc} はドロップフレーム表記です。ノンドロップとして扱うため、数フレームずれることがあります。")
        tc = tc.replace(";", ":")
    return tc_to_frames(tc, nominal_rate(fps)), warns


def round_half_up(x):
    """四捨五入(0.5 は大きい方へ)。Python の round() は偶数への丸め(2.5 -> 2)で、30fps の x.x5 秒のような
    ちょうど半フレームの時刻が、行ごとに上下ばらばらに丸まる。文字起こしツール(resolve_export・画面の SRT)と同じ規則にそろえる"""
    return math.floor(Fraction(x) + Fraction(1, 2))


def ms_to_frames(ms, fps):
    return round_half_up(Fraction(ms * fps[0], 1000 * fps[1]))


def frames_to_ms(n, fps):
    return round_half_up(Fraction(n * 1000 * fps[1], fps[0]))


def frames_to_time(n, fps):
    """FCPXML の時刻表記。フレーム境界の分数(秒)で書く(境界外だと取り込み側がずれる)"""
    f = Fraction(n * fps[1], fps[0])
    return f"{f.numerator}s" if f.denominator == 1 else f"{f.numerator}/{f.denominator}s"


def to_frame_cues(cues, fps, total, offset_ms=0):
    """[(ms, ms, text)] -> [(start_f, end_f, text)]。範囲外は切る/捨てる。捨てた数も返す"""
    out, dropped = [], 0
    for a, b, t in sorted(cues, key=lambda c: (c[0], c[1])):
        a, b = a + offset_ms, b + offset_ms
        if b <= 0:
            dropped += 1
            continue
        sf = max(0, ms_to_frames(a, fps))
        ef = ms_to_frames(b, fps)
        if ef <= sf:
            ef = sf + 1  # 0 フレームの字幕は消えるので最低 1 フレーム
        if sf >= total:
            dropped += 1
            continue
        out.append((sf, min(ef, total), t))
    return out, dropped


def assign_lanes(items):
    """時間が重なる字幕を別トラック(レーン)へ。同じトラックで重なると Resolve が取り込めないため"""
    ends, out = [], []
    for sf, ef, t in items:
        for i, e in enumerate(ends):
            if e <= sf:
                ends[i] = ef
                lane = i + 1
                break
        else:
            ends.append(ef)
            lane = len(ends)
        out.append((sf, ef, t, lane))
    return out


# ---------------------------------------------------------------- 出力の組み立て

def build_fcpxml(video, meta, cues_f, name, font, size, titles=True, start_frames=0):
    """start_frames: 元動画の開始タイムコードのフレーム番号。FCPXML では asset の start がメディアの先頭の時刻、
    asset-clip の start はそのメディアの時刻で書く。Resolve は動画に埋め込まれた開始タイムコードで照合するため、
    0 のままだと EDL の v0.1.0 と同じ「timecode extents do not match」になる(EDL は v0.1.1 で対応済み・実機確認済み)。
    つながったタイトルの offset は親(asset-clip)の中の時刻 = 親の start 基準で書く"""
    fps, total = meta["fps"], meta["total"]
    t0 = int(start_frames or 0)
    uid = hashlib.md5(str(video).encode("utf-8")).hexdigest().upper()
    root, spine = fcpxml_skeleton(video, meta, uid, t0, bool(titles and cues_f), "srt2resolve", name, total)
    clip = ET.SubElement(spine, "asset-clip", ref="r2", offset="0s", name=video.stem,
                         start=frames_to_time(t0, fps), duration=frames_to_time(total, fps), format="r1", tcFormat="NDF")
    lanes = 0
    if titles:
        for n, (sf, ef, text, lane) in enumerate(assign_lanes(cues_f), 1):
            lanes = max(lanes, lane)
            fcpxml_title(clip, n, lane, t0 + sf, ef - sf, text, fps, font, size)
    return fcpxml_text(root), lanes


TITLE_EFFECT_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"


def fcpxml_skeleton(video, meta, uid, start_frames, titles, event, project, seq_frames):
    """FCPXML の共通の骨組み(build_fcpxml と auto_cut.build_cut_fcpxml): format・asset(start = 元動画の開始タイムコードのフレーム)・
    タイトルの effect(titles のとき)・library > event > project > sequence(長さ seq_frames フレーム)。-> (root, spine)"""
    fps, audio = meta["fps"], meta.get("audio")
    w, h = meta["w"], meta["h"]
    fps_label = f"{fps[0] / fps[1]:g}" if fps[1] == 1 else f"{fps[0] / fps[1]:.2f}"
    root = ET.Element("fcpxml", version="1.8")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", name=f"FFVideoFormat{w}x{h}p{fps_label}",
                  frameDuration=frames_to_time(1, fps), width=str(w), height=str(h))
    asset_attr = dict(id="r2", name=video.name, uid=uid, src=video.resolve().as_uri(), start=frames_to_time(start_frames, fps),
                      duration=frames_to_time(meta["total"], fps), hasVideo="1", format="r1")
    if audio:
        asset_attr.update(hasAudio="1", audioSources="1", audioChannels=str(audio[0]), audioRate=str(audio[1]))
    ET.SubElement(res, "asset", **asset_attr)
    if titles:
        ET.SubElement(res, "effect", id="r3", name="Basic Title", uid=TITLE_EFFECT_UID)
    proj = ET.SubElement(ET.SubElement(ET.SubElement(root, "library"), "event", name=event), "project", name=project)
    seq = ET.SubElement(proj, "sequence", format="r1", duration=frames_to_time(seq_frames, fps), tcStart="0s", tcFormat="NDF",
                        audioLayout="mono" if audio and audio[0] == 1 else "stereo",
                        audioRate=SEQ_AUDIO_RATE.get(audio[1] if audio else 48000, "48k"))
    return root, ET.SubElement(seq, "spine")


def fcpxml_title(clip, n, lane, offset, frames, text, fps, font, size):
    """つながったタイトル(字幕 1 件)を clip に足す。offset は親(asset-clip)の中の時刻(フレーム)。n = 文書の中の通し番号(text-style-def の id)。
    タイトルの内部の開始は FCP の流儀の 3600 秒をフレーム境界に合わせた値"""
    t = ET.SubElement(clip, "title", ref="r3", lane=str(lane), offset=frames_to_time(offset, fps), name=text.replace("\n", " ")[:40],
                      start=frames_to_time(round(3600 * fps[0] / fps[1]), fps), duration=frames_to_time(frames, fps))
    ET.SubElement(ET.SubElement(t, "text"), "text-style", ref=f"ts{n}").text = text
    ET.SubElement(ET.SubElement(t, "text-style-def", id=f"ts{n}"), "text-style", font=font, fontSize=str(size), fontColor="1 1 1 1",
                  bold="1", alignment="center", strokeColor="0 0 0 1", strokeWidth="-4")


def fcpxml_text(root):
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _srt_ts(ms):
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues_f, fps):
    parts = []
    for n, (sf, ef, text) in enumerate(cues_f, 1):
        parts.append(f"{n}\n{_srt_ts(frames_to_ms(sf, fps))} --> {_srt_ts(frames_to_ms(ef, fps))}\n{text}\n")
    return "\n".join(parts)


# ---------------------------------------------------------------- CLI

def default_font():
    return "Hiragino Sans" if sys.platform == "darwin" else "Yu Gothic"


def classify_inputs(paths):
    subs = [p for p in paths if p.suffix.lower() in SUB_EXTS]
    vids = [p for p in paths if p.suffix.lower() not in SUB_EXTS]
    if len(subs) != 1 or len(vids) != 1:
        raise ToolError("動画ファイル1つと字幕ファイル(.srt / .vtt)1つを指定してください(順不同)。")
    return vids[0], subs[0]


def run(args):
    video, sub = classify_inputs([Path(p) for p in args.inputs])
    for p in (video, sub):
        if not p.is_file():
            raise ToolError(f"ファイルが見つかりません: {p}")
    meta = probe(video, args.fps, args.frames)
    cues = parse_subs(read_sub_file(sub))
    if not cues:
        raise ToolError("字幕を1件も読み取れませんでした(SRT/VTT の形式を確認してください)。")
    cues_f, dropped = to_frame_cues(cues, meta["fps"], meta["total"], int(round(args.offset * 1000)))
    if not cues_f:
        raise ToolError("動画の長さの範囲に入る字幕がありません。--offset を確認してください。")

    out_dir = Path(args.output) if args.output else video.parent / f"{video.stem}_resolve"
    fcp_path, srt_path = out_dir / f"{video.stem}.fcpxml", out_dir / f"{video.stem}.srt"
    existing = [p for p in (fcp_path, srt_path) if p.exists()]
    if same_path(srt_path, sub) or same_path(fcp_path, sub) or same_path(fcp_path, video) or same_path(srt_path, video):
        raise ToolError("出力先が入力ファイルと同じです。-o で別のフォルダを指定してください。")
    if existing and not args.force:
        raise ToolError("出力ファイルが既にあります(上書きする場合は --force を指定): "
                        + ", ".join(p.name for p in existing))

    # 開始タイムコードの確かめ・XML の組み立ては、フォルダを作る前に済ませる(失敗したとき空のフォルダを残さない)
    start_tc = args.src_start_tc or meta.get("start_tc")
    t0, tc_warns = start_tc_frames(start_tc, meta["fps"])
    size = args.size or round(min(meta["w"], meta["h"]) * 0.06)
    xml, lanes = build_fcpxml(video, meta, cues_f, video.stem, args.font or default_font(),
                              size, titles=not args.no_titles, start_frames=t0)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(fcp_path, xml, encoding="utf-8", newline="\n")
    write_text_atomic(srt_path, build_srt(cues_f, meta["fps"]), encoding="utf-8", newline="\n")

    fps = meta["fps"]
    print(f"動画: {video.name}  {meta['w']}x{meta['h']}  {fps[0] / fps[1]:.3f}fps  "
          f"{meta['total']}フレーム({meta['frames_source']})")
    print(f"映像: {meta['codec']} / {meta['pix_fmt']}   場所: {video.resolve()}")
    print(f"字幕: {len(cues_f)}件" + (f"(範囲外 {dropped}件は除外)" if dropped else ""))
    if start_tc:
        print(f"元動画の開始タイムコード: {start_tc}({'指定' if args.src_start_tc else '動画に埋め込まれた値'})を FCPXML に反映しました"
              "  ← Resolve の Clip Attributes の Start TC と同じになるはずです")
    if lanes > 1:
        print(f"注意: 時間が重なる字幕があるため、字幕トラックが {lanes} 本になります。")
    for wmsg in [m for m in meta["warnings"] if "開始タイムコード" not in m] + tc_warns:
        print("注意: " + wmsg)
    print(f"出力: {fcp_path}\n      {srt_path}")
    print("Resolve: File > Import > Timeline で .fcpxml を選び、"
          "「ソースクリップを自動的にメディアプールに読み込む」にチェックを入れて読み込みます。"
          "動画は移動・改名しないでください。")
    return 0


def safe_stdio():
    """画面(Windows の cp932 など)に出せない文字があっても、エラーで落ちずに「?」にする(コマンドの main の最初で呼ぶ)"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv=None):
    safe_stdio()
    ap = argparse.ArgumentParser(description="動画+字幕 -> DaVinci Resolve 用 FCPXML")
    ap.add_argument("inputs", nargs=2, metavar="FILE", help="動画ファイルと字幕ファイル(順不同)")
    ap.add_argument("-o", "--output", help="出力フォルダ(既定: 動画と同じ場所の <動画名>_resolve)")
    ap.add_argument("--offset", type=float, default=0.0, help="字幕を全体にずらす秒数(負で前へ)")
    ap.add_argument("--font", help="字幕のフォント名(既定: Windows=Yu Gothic / Mac=Hiragino Sans)")
    ap.add_argument("--size", type=int, help="字幕の文字サイズ(既定: 短辺の6%%)")
    ap.add_argument("--fps", help="フレームレートを指定(例: 30, 29.97, 60000/1001)。通常は自動")
    ap.add_argument("--frames", type=int,
                    help="動画のフレーム数を指定(Resolve のクリップ情報の値。取り込みで長さが合わないとき用)")
    ap.add_argument("--no-titles", action="store_true",
                    help="字幕を FCPXML に入れず、動画だけのタイムラインにする(字幕は SRT を Resolve で読み込む)")
    ap.add_argument("--src-start-tc", default=None,
                    help="元動画の開始タイムコード HH:MM:SS:FF(既定: 動画に埋め込まれた値、無ければ 00:00:00:00)")
    ap.add_argument("--force", action="store_true", help="既存の出力ファイルを上書きする")
    ap.add_argument("--version", action="version", version=f"srt2resolve {VERSION}")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except ToolError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
