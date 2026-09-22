# -*- coding: utf-8 -*-
"""cut2resolve 共通部 v0.1.2

元動画 + カット(残す区間) + 字幕(SRT) から、DaVinci Resolve に読み込める
  ・EDL(カットリスト。動画の場所は書かず、ファイル名で元動画と結び付ける)
  ・カット後の時刻に直した字幕(SRT)
  ・友人向けの手順書
  ・(任意) ffmpeg で粗編集した動画(EDL が通らなかったときの代替)
を作る。動画の情報の読み取り・字幕の読み込みは srt2resolve.py を使い回す。

時刻はすべて「元動画のフレーム番号」で扱い、区間は [開始, 終了) の半開区間。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import srt2resolve as S  # noqa: E402

ToolError = S.ToolError
VERSION = "0.1.2"
CUT_EXTS = {".txt", ".csv"}


# ---------------------------------------------------------------- 時刻・カットリストの読み込み

_NUM = re.compile(r"\d+(?:\.\d+)?")
_RANGE_SPLIT = re.compile(r"\s*(?:-->|->|→|~|〜|～|–|—|-|\s)\s*")


def parse_time(text):
    """'12.5' / '1:02.5' / '0:01:02,5' -> 秒(float)。負数・空・変な文字は ToolError"""
    t = text.strip().replace(",", ".")
    parts = t.split(":")
    if not t or len(parts) > 3 or not all(_NUM.fullmatch(p) for p in parts):
        raise ToolError(f"時刻を読めません: {text!r}(例: 12.5 / 1:02.5 / 0:01:02)")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def parse_cut_list(text):
    """1行1区間「開始 終了」(区切りは空白 - ~ 〜 → など)。# 以降はコメント。[(開始秒, 終了秒)]"""
    out = []
    for no, raw in enumerate(text.replace("﻿", "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        toks = [t for t in _RANGE_SPLIT.split(line) if t]
        if len(toks) != 2:
            raise ToolError(f"{no}行目を読めません(「開始 終了」の形式で書いてください): {raw.strip()}")
        a, b = parse_time(toks[0]), parse_time(toks[1])
        if b <= a:
            raise ToolError(f"{no}行目: 終了が開始より前(または同じ)です: {raw.strip()}")
        out.append((a, b))
    return out


def parse_index_list(text):
    """'3,5-7' -> {3,5,6,7}(1始まり)"""
    idx = set()
    for tok in re.split(r"[,\s]+", text.strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", tok)
        if not m:
            raise ToolError(f"行番号を読めません: {tok!r}(例: 3,5-7)")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if b < a or a < 1:
            raise ToolError(f"行番号が正しくありません: {tok!r}")
        idx.update(range(a, b + 1))
    return idx


def sec_to_frames(sec, fps):
    return S.ms_to_frames(int(round(sec * 1000)), fps)


def cut_list_to_keeps(pairs, fps, total):
    """[(開始秒, 終了秒)] -> (フレームの区間[整理済み], 警告)。動画の長さを超える分は切る"""
    raw = [(sec_to_frames(a, fps), sec_to_frames(b, fps)) for a, b in pairs]
    warns = []
    if any(e > total or s >= total for s, e in raw):
        warns.append("動画の長さを超える区間は切り捨てました。")
    return normalize(raw, total), warns


def read_text_file(path):
    return S.read_sub_file(Path(path))  # 文字コード判別(UTF-8/Shift_JIS/UTF-16)と大きさ上限を流用


# ---------------------------------------------------------------- 区間の計算(フレーム, 半開区間)

def normalize(ranges, total=None):
    """範囲外を切り、空を捨て、並べ替え、重なり・接する区間を1つにまとめる"""
    rs = []
    for s, e in ranges:
        if total is not None:
            s, e = max(0, s), min(e, total)
        if e > s:
            rs.append((s, e))
    rs.sort()
    merged = []
    for s, e in rs:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def subtract(base, cuts):
    """base から cuts を引く"""
    out = []
    cuts = normalize(cuts)
    for s, e in normalize(base):
        cur = s
        for cs, ce in cuts:
            if ce <= cur:
                continue
            if cs >= e:
                break
            if cs > cur:
                out.append((cur, cs))
            cur = max(cur, ce)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def merge_close(ranges, gap):
    """区間どうしの隙間が gap フレーム以下なら1つにつなぐ(細切れ防止)"""
    out = []
    for s, e in ranges:
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def drop_short(ranges, min_len):
    return [(s, e) for s, e in ranges if e - s >= min_len]


# ---------------------------------------------------------------- 無音の検出

def _ffmpeg_run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except FileNotFoundError:
        raise ToolError("ffmpeg が見つかりません。ffmpeg をインストールして PATH に通してください。")
    except subprocess.TimeoutExpired:
        raise ToolError("ffmpeg の処理が時間内に終わりませんでした。")


def detect_silence(video, fps, total, noise_db=-35.0, min_sec=0.6, pad_sec=0.15):
    """無音区間 -> 削る区間[(開始f, 終了f)]。話の前後に pad_sec だけ残す"""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_sec}", "-f", "null", "-"]
    r = _ffmpeg_run(cmd, 3600)
    if r.returncode != 0:
        raise ToolError("無音の検出に失敗しました(音声が無い動画かもしれません): " + (r.stderr or "").strip()[-200:])
    total_sec = float(Fraction(total * fps[1], fps[0]))
    spans, cur = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            cur = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if m and cur is not None:
            spans.append((cur, float(m.group(1))))
            cur = None
    if cur is not None:  # 最後まで無音
        spans.append((cur, total_sec))
    out = []
    for a, b in spans:
        if b - a > 2 * pad_sec:
            out.append((sec_to_frames(a + pad_sec, fps), sec_to_frames(b - pad_sec, fps)))
    return normalize(out, total)


# ---------------------------------------------------------------- タイムコードと EDL

def nominal_rate(fps):
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


_TC_RE = re.compile(r"\d{1,2}[:;]\d{2}[:;]\d{2}[:;]\d{2}")


def read_start_tc(video):
    """動画に埋め込まれた開始タイムコード('HH:MM:SS:FF')。無ければ None。
    Resolve はこれをクリップの開始タイムコード(Start TC)として使う。EDL の元動画側の時刻がその範囲に
    入っていないと「タイムコードの範囲が一致しない」で結び付かないため、EDL にも同じ値を足す必要がある"""
    r = _ffmpeg_run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                     str(video)], 60)
    try:
        info = json.loads(r.stdout or "{}")
    except ValueError:
        return None
    tcs = [(s.get("tags") or {}).get("timecode") for s in info.get("streams", [])]
    tcs.append(((info.get("format") or {}).get("tags") or {}).get("timecode"))
    return next((t.strip() for t in tcs if t and _TC_RE.fullmatch(t.strip())), None)


def resolve_src_start(video, override=None):
    """EDL の元動画側の開始タイムコード -> (値, 由来の説明, 警告リスト)。
    指定があればそれ、無ければ動画に埋め込まれた値、それも無ければ 00:00:00:00"""
    if override:
        return override, "指定", []
    tc = read_start_tc(video)
    if not tc:
        return "00:00:00:00", "動画に埋め込みなし", []
    warns = []
    if ";" in tc:
        warns.append(f"開始タイムコード {tc} はドロップフレーム表記です。ノンドロップとして扱うため、"
                     "数フレームずれることがあります。")
        tc = tc.replace(";", ":")
    return tc, "動画に埋め込まれた値", warns


def _reel(name):
    r = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()[:8]
    return r or "AX"


def build_edl(title, clip_name, keeps, fps, has_audio, reel="AX",
              rec_start="01:00:00:00", src_start="00:00:00:00"):
    """CMX3600 の EDL。イベント = 残す区間1つ。ファイル名は「* FROM CLIP NAME」で渡す"""
    nom = nominal_rate(fps)
    rec = tc_to_frames(rec_start, nom)
    src0 = tc_to_frames(src_start, nom)
    track = "AA/V" if has_audio else "V"
    reel = _reel(reel)
    title = re.sub(r"[\r\n]+", " ", title)
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for i, (s, e) in enumerate(keeps, 1):
        n = e - s
        lines.append(f"{i:03d}  {reel:<8s} {track:<5s} C        "
                     f"{frames_to_tc(src0 + s, nom)} {frames_to_tc(src0 + e, nom)} "
                     f"{frames_to_tc(rec, nom)} {frames_to_tc(rec + n, nom)}")
        lines.append(f"* FROM CLIP NAME: {clip_name}")
        lines.append(f"* SOURCE FILE: {clip_name}")
        lines.append("")
        rec += n
    return "\r\n".join(lines)


# ---------------------------------------------------------------- 字幕の時刻をカット後に直す

def remap_cues(cues_ms, keeps, fps, min_piece_frames=6):
    """[(開始ms, 終了ms, 文)] -> ([(開始f, 終了f, 文)](カット後の時刻), 消えた件数)。
    カットにまたがる字幕は区間ごとに分け、切れて短すぎる断片(min_piece_frames 未満)は捨てる"""
    spans, rec = [], 0
    for ks, ke in keeps:
        spans.append((ks, ke, rec))
        rec += ke - ks
    out, vanished = [], 0
    for a, b, text in cues_ms:
        cs = S.ms_to_frames(a, fps)
        ce = max(S.ms_to_frames(b, fps), cs + 1)
        made = 0
        for ks, ke, rs in spans:
            os_, oe = max(cs, ks), min(ce, ke)
            n = oe - os_
            if n > 0 and (n == ce - cs or n >= min_piece_frames):  # 切られていない字幕は短くても残す
                out.append((rs + os_ - ks, rs + oe - ks, text))
                made += 1
        if not made:
            vanished += 1
    out.sort(key=lambda c: (c[0], c[1]))
    return out, vanished


# ---------------------------------------------------------------- 粗編集の動画(EDL が通らないときの代替)

def render_rough_cut(video, keeps, fps, has_audio, out_path, crf=18):
    """残す区間だけをつないだ H.264 の mp4 を作る(再エンコード。フレーム単位で切る)"""
    chains = []
    for i, (s, e) in enumerate(keeps):
        chains.append(f"[0:v]trim=start_frame={s}:end_frame={e},setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            t0 = float(Fraction(s * fps[1], fps[0]))
            t1 = float(Fraction(e * fps[1], fps[0]))
            chains.append(f"[0:a]atrim=start={t0:.6f}:end={t1:.6f},asetpts=PTS-STARTPTS[a{i}]")
    ins = "".join(f"[v{i}][a{i}]" if has_audio else f"[v{i}]" for i in range(len(keeps)))
    chains.append(f"{ins}concat=n={len(keeps)}:v=1:a={1 if has_audio else 0}"
                  + ("[outv][outa]" if has_audio else "[outv]"))
    script = ";\n".join(chains)
    out_opts = ["-map", "[outv]"] + (["-map", "[outa]"] if has_audio else []) + [
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p",
        "-r", f"{fps[0]}/{fps[1]}"]
    if has_audio:
        out_opts += ["-c:a", "aac", "-b:a", "192k"]
    out_opts += ["-movflags", "+faststart", str(out_path)]
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "filter.txt"
        sp.write_text(script, encoding="utf-8")
        err = ""
        # 長い区間リストでも Windows のコマンド長制限に当たらないよう、フィルタはファイルで渡す。
        # 新しい ffmpeg では -filter_complex_script が -/filter_complex に置き換わっているため両方試す
        for opt in ("-filter_complex_script", "-/filter_complex"):
            r = _ffmpeg_run(["ffmpeg", "-y", "-v", "error", "-i", str(video), opt, str(sp)] + out_opts, 7200)
            if r.returncode == 0:
                return
            err = (r.stderr or "").strip()
            if "nrecognized option" not in err and "not found" not in err:
                break
    raise ToolError("粗編集の動画を書き出せませんでした: " + err[-300:])


# ---------------------------------------------------------------- 表示・手順書・出力

def fmt_sec(sec):
    h, m, s = int(sec // 3600), int(sec % 3600 // 60), sec % 60
    return f"{h}:{m:02d}:{s:05.2f}" if h else f"{m}:{s:05.2f}"


def fmt_frames(n, fps):
    return fmt_sec(float(Fraction(n * fps[1], fps[0])))


def describe_keeps(keeps, fps, total, limit=40):
    kept = sum(e - s for s, e in keeps)
    lines = [f"残す区間: {len(keeps)}か所  合計 {fmt_frames(kept, fps)}"
             f"(元の {fmt_frames(total, fps)} の {kept * 100 / total:.0f}%)"]
    for i, (s, e) in enumerate(keeps[:limit], 1):
        lines.append(f"  {i:>3}  {fmt_frames(s, fps)} - {fmt_frames(e, fps)}  ({fmt_frames(e - s, fps)})")
    if len(keeps) > limit:
        lines.append(f"  … 残り {len(keeps) - limit} か所")
    return "\n".join(lines)


def build_readme(video_name, meta, keeps, edl_name, srt_name, rough_name, rec_start, src_start):
    fps = meta["fps"]
    nom = nominal_rate(fps)
    src0 = tc_to_frames(src_start, nom)
    rate = f"{fps[0] / fps[1]:.3f}".rstrip("0").rstrip(".")
    rows = "\n".join(
        f"  {i:>3}   {frames_to_tc(src0 + s, nom)}  →  {frames_to_tc(src0 + e, nom)}   ({fmt_frames(e - s, fps)})"
        for i, (s, e) in enumerate(keeps, 1))
    rough = (f"\n  ・{rough_name}  … 残す区間をつないだ粗編集の動画(EDLが通らないとき用)" if rough_name else "")
    alt = (f"\nA. 粗編集の動画 {rough_name} をタイムラインに置き、手順4で字幕だけ読み込む。"
           if rough_name else "")
    srt_item = (f"\n  ・{srt_name}  … 字幕(カット後の時刻に直してあります)" if srt_name else "")
    step4 = (f"""4. File > Import > Subtitle で {srt_name} を読み込み、メディアプールから
   字幕トラックの一番左(タイムラインの先頭)へドラッグします。
   ・字幕が見えない・ずれるときは、タイムラインの開始タイムコード({rec_start})とずれています。
     Timeline > Timeline Settings で開始タイムコードを確認してください。"""
             if srt_name else "4. (字幕は付いていません)")
    return f"""DaVinci Resolve での開く手順
================================

入っているもの
  ・{edl_name}  … カット(残す区間)のリスト(EDL){srt_item}
  ・{video_name}  … 元動画(このフォルダに入っているか、別に送られてきます。ファイル名は変えないでください){rough}

元動画の情報:  {meta['w']}x{meta['h']} / {rate} fps / 映像 {meta.get('codec', '?')}

手順
1. 新しいプロジェクトを作り、プロジェクト設定(Project Settings)で
   「タイムラインのフレームレート」を {rate} にします(元動画と同じにする)。
2. 元動画 {video_name} をメディアプールに読み込みます(ドラッグ)。
3. File > Import > Timeline > Import AAF, EDL, XML... で {edl_name} を選びます。
   ・読み込み画面に「ソースクリップを自動的にメディアプールに読み込む」があれば、
     動画は手順2で入れてあるのでオフにします。
   ・「リール名」の設定があれば「ソースクリップのファイル名」にします。合わないときは他の項目も試してください。
   ・成功すると、元動画のクリップが下の表の区間ごとに並んだタイムラインができます。
{step4}

うまく開けないとき
{alt if alt else ''}
B. 下の表のとおりに、元動画をカットする(数か所なら手作業でもできます)。
   元動画のタイムコード(開始 → 終了)を残す区間です。
C. EDLの読み込みで「ファイルが見つからない」と出るときは、元動画のファイル名に日本語や
   記号が入っていないか確認してください(英数字に変えて、同じ名前でメディアプールに入れ直す)。
D. 「タイムコードの範囲が一致しない(timecode extents do not match)」と出るときは、
   メディアプールの元動画を右クリック > Clip Attributes(クリップ属性)を開いて確認します。
   ・Video Frame Rate が {rate} で、プロジェクトのタイムラインのフレームレートと同じか
   ・Timecode の Start TC が {src_start} か
   違うときは Start TC を {src_start} に書き換えて(Apply)、EDLを読み込み直します。
   (Start TC が別の値のままにしたいときは、ツールを --src-start-tc 値 を付けて実行し直してください)

残す区間(元動画のタイムコード)
   #    開始           終了
{rows}
"""


def write_pack(out_dir, video, meta, keeps, cues_out, args_reel="AX", rec_start="01:00:00:00",
               src_start="00:00:00:00", rough_path=None, edl_title=None):
    """EDL・字幕・手順書を書く。書いたファイルのパス辞書を返す"""
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = meta["fps"]
    edl_p = out_dir / f"{video.stem}.edl"
    srt_p = out_dir / f"{video.stem}_cut.srt"
    txt_p = out_dir / "友人へ.txt"
    edl_p.write_text(build_edl(edl_title or video.stem, video.name, keeps, fps, bool(meta["audio"]),
                               args_reel, rec_start, src_start),
                     encoding="utf-8", newline="")
    files = {"edl": edl_p}
    if cues_out is not None:
        srt_p.write_text(S.build_srt(cues_out, fps), encoding="utf-8", newline="\n")
        files["srt"] = srt_p
    txt_p.write_text(build_readme(video.name, meta, keeps, edl_p.name,
                                  srt_p.name if cues_out is not None else None,
                                  rough_path.name if rough_path else None, rec_start, src_start),
                     encoding="utf-8-sig", newline="\n")
    files["readme"] = txt_p
    return files


def name_warnings(video):
    if not video.name.isascii():
        return ["動画のファイル名に日本語などが含まれています。EDLはファイル名で元動画と結び付けるため、"
                "Resolve で見つからないことがあります。英数字の名前に変えてから使うと確実です。"]
    return []


def classify_inputs(paths, need_cuts):
    subs = [p for p in paths if p.suffix.lower() in S.SUB_EXTS]
    cuts = [p for p in paths if p.suffix.lower() in CUT_EXTS]
    vids = [p for p in paths if p not in subs and p not in cuts]
    if len(vids) != 1:
        raise ToolError("動画ファイルを1つ指定してください(字幕は .srt/.vtt、カットリストは .txt を、順不同で)。")
    if len(subs) > 1 or len(cuts) > 1:
        raise ToolError("字幕ファイルとカットリストは、それぞれ1つまでです。")
    if need_cuts and not cuts:
        raise ToolError("カットリスト(.txt)が必要です。1行に「開始 終了」を書いたファイルを一緒に指定してください。")
    return vids[0], (subs[0] if subs else None), (cuts[0] if cuts else None)


def copy_video(video, out_dir):
    dst = out_dir / video.name
    if dst.resolve() != video.resolve():
        shutil.copy2(video, dst)
    return dst
