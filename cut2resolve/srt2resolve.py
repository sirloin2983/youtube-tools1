#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""srt2resolve v0.1.2

動画 + 字幕(SRT/VTT)から、DaVinci Resolve に読み込める編集可能なデータを作る。

出力(動画と同じ場所の <動画名>_resolve フォルダ):
  <動画名>.fcpxml  動画を並べたタイムライン + 字幕を1行ずつ「タイトル」として配置したもの
  <動画名>.srt     フレーム境界に丸めた字幕(FCPXML の字幕が期待どおり出ないとき用の予備)

依存: Python 3.9+(標準ライブラリのみ) と ffprobe(ffmpeg に同梱)。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

VERSION = "0.1.2"

# 編集ソフトで一般的なフレームレート。動画の実測値をこれに丸める
STD_FPS = [(24000, 1001), (24, 1), (25, 1), (30000, 1001), (30, 1),
           (48, 1), (50, 1), (60000, 1001), (60, 1)]
SUB_EXTS = {".srt", ".vtt"}
MAX_SUB_BYTES = 5 * 1024 * 1024
SEQ_AUDIO_RATE = {32000: "32k", 44100: "44.1k", 48000: "48k", 88200: "88.2k", 96000: "96k"}


class ToolError(Exception):
    """利用者に見せる想定のエラー(原因と対処を書く)"""


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
    return []


def _exact_frames(video, v):
    """映像ストリームの実際のフレーム数。取れなければ None。
    コンテナの長さ(音声が長い動画だと映像より長い)から計算すると、Resolve が読む長さとずれて
    「タイムコードの範囲が一致しない」で取り込みに失敗するため、映像そのものの数を使う。"""
    nb = v.get("nb_frames")
    if isinstance(nb, str) and nb.isdigit() and int(nb) > 0:
        return int(nb)
    print("フレーム数を数えています…(長い動画は少し時間がかかります)", flush=True)
    cmd = ["ffprobe", "-v", "error", "-select_streams", str(v["index"]), "-count_packets",
           "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(video)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    m = re.match(r"\s*(\d+)", r.stdout or "")
    return int(m.group(1)) if r.returncode == 0 and m and int(m.group(1)) > 0 else None


def probe(video, fps_override=None, frames_override=None):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(video)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    except FileNotFoundError:
        raise ToolError("ffprobe が見つかりません。ffmpeg をインストールして PATH に通してください。")
    except subprocess.TimeoutExpired:
        raise ToolError("ffprobe が 60 秒で終わりませんでした。動画ファイルを確認してください。")
    if r.returncode != 0:
        raise ToolError(f"動画を読めませんでした: {r.stderr.strip()[:200]}")
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), None)
    if v is None:
        raise ToolError("動画ストリームが見つかりません。")
    warnings = []

    w, h = int(v["width"]), int(v["height"])
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
    tcs = [(s.get("tags") or {}).get("timecode") for s in streams]
    tcs.append(((info.get("format") or {}).get("tags") or {}).get("timecode"))
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
            "codec": codec, "pix_fmt": pix_fmt, "audio": audio, "warnings": warnings}


# ---------------------------------------------------------------- 時刻の変換

def ms_to_frames(ms, fps):
    return int(round(Fraction(ms * fps[0], 1000 * fps[1])))


def frames_to_ms(n, fps):
    return int(round(Fraction(n * 1000 * fps[1], fps[0])))


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

def build_fcpxml(video, meta, cues_f, name, font, size, titles=True):
    fps, total = meta["fps"], meta["total"]
    w, h = meta["w"], meta["h"]
    fd = frames_to_time(1, fps)
    fps_label = f"{fps[0] / fps[1]:g}" if fps[1] == 1 else f"{fps[0] / fps[1]:.2f}"

    root = ET.Element("fcpxml", version="1.8")
    res = ET.SubElement(root, "resources")
    ET.SubElement(res, "format", id="r1", name=f"FFVideoFormat{w}x{h}p{fps_label}",
                  frameDuration=fd, width=str(w), height=str(h))
    uid = hashlib.md5(str(video).encode("utf-8")).hexdigest().upper()
    asset_attr = dict(id="r2", name=video.name, uid=uid, src=video.resolve().as_uri(),
                      start="0s", duration=frames_to_time(total, fps), hasVideo="1", format="r1")
    if meta["audio"]:
        asset_attr.update(hasAudio="1", audioSources="1",
                          audioChannels=str(meta["audio"][0]), audioRate=str(meta["audio"][1]))
    ET.SubElement(res, "asset", **asset_attr)
    if titles and cues_f:
        ET.SubElement(res, "effect", id="r3", name="Basic Title",
                      uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti")

    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name="srt2resolve")
    proj = ET.SubElement(ev, "project", name=name)
    mono = bool(meta["audio"]) and meta["audio"][0] == 1
    seq_attr = dict(format="r1", duration=frames_to_time(total, fps), tcStart="0s",
                    tcFormat="NDF", audioLayout="mono" if mono else "stereo")
    seq_attr["audioRate"] = SEQ_AUDIO_RATE.get(meta["audio"][1] if meta["audio"] else 48000, "48k")
    seq = ET.SubElement(proj, "sequence", **seq_attr)
    spine = ET.SubElement(seq, "spine")
    clip = ET.SubElement(spine, "asset-clip", ref="r2", offset="0s", name=video.stem,
                         start="0s", duration=frames_to_time(total, fps), format="r1", tcFormat="NDF")

    lanes = 0
    if titles:
        gen_start = round(3600 * fps[0] / fps[1])  # FCP 流儀のタイトル内部開始(3600秒)をフレーム境界に合わせる
        for n, (sf, ef, text, lane) in enumerate(assign_lanes(cues_f), 1):
            lanes = max(lanes, lane)
            t = ET.SubElement(clip, "title", ref="r3", lane=str(lane),
                              offset=frames_to_time(sf, fps),
                              name=text.replace("\n", " ")[:40],
                              start=frames_to_time(gen_start, fps),
                              duration=frames_to_time(ef - sf, fps))
            tx = ET.SubElement(t, "text")
            st = ET.SubElement(tx, "text-style", ref=f"ts{n}")
            st.text = text
            defn = ET.SubElement(t, "text-style-def", id=f"ts{n}")
            ET.SubElement(defn, "text-style", font=font, fontSize=str(size), fontColor="1 1 1 1",
                          bold="1", alignment="center", strokeColor="0 0 0 1", strokeWidth="-4")
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + body + "\n", lanes


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
    out_dir.mkdir(parents=True, exist_ok=True)
    fcp_path, srt_path = out_dir / f"{video.stem}.fcpxml", out_dir / f"{video.stem}.srt"
    if srt_path.resolve() == sub.resolve():
        raise ToolError("出力先が入力の字幕ファイルと同じです。-o で別のフォルダを指定してください。")

    size = args.size or round(min(meta["w"], meta["h"]) * 0.06)
    xml, lanes = build_fcpxml(video, meta, cues_f, video.stem, args.font or default_font(),
                              size, titles=not args.no_titles)
    fcp_path.write_text(xml, encoding="utf-8", newline="\n")
    srt_path.write_text(build_srt(cues_f, meta["fps"]), encoding="utf-8", newline="\n")

    fps = meta["fps"]
    print(f"動画: {video.name}  {meta['w']}x{meta['h']}  {fps[0] / fps[1]:.3f}fps  "
          f"{meta['total']}フレーム({meta['frames_source']})")
    print(f"映像: {meta['codec']} / {meta['pix_fmt']}   場所: {video.resolve()}")
    print(f"字幕: {len(cues_f)}件" + (f"(範囲外 {dropped}件は除外)" if dropped else ""))
    if lanes > 1:
        print(f"注意: 時間が重なる字幕があるため、字幕トラックが {lanes} 本になります。")
    for wmsg in meta["warnings"]:
        print("注意: " + wmsg)
    print(f"出力: {fcp_path}\n      {srt_path}")
    print("Resolve: File > Import > Timeline で .fcpxml を選び、"
          "「ソースクリップを自動的にメディアプールに読み込む」にチェックを入れて読み込みます。"
          "動画は移動・改名しないでください。")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
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
    ap.add_argument("--version", action="version", version=f"srt2resolve {VERSION}")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except ToolError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
