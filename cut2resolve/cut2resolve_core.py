# -*- coding: utf-8 -*-
"""cut2resolve 共通部 v0.2.0

元動画 + カット(残す区間) + 字幕(SRT) から、DaVinci Resolve に読み込める
  ・EDL(カットリスト。動画の場所は書かず、ファイル名で元動画と結び付ける)
  ・カット後の時刻に直した字幕(SRT)
  ・友人向けの手順書
  ・(任意) ffmpeg で粗編集した動画(EDL が通らなかったときの代替)
を作る。動画の情報の読み取り・字幕の読み込みは srt2resolve.py を使い回す。
カットの決め方を組み合わせて「残す区間」を出す流れ(試算とパック作成)は pack.py(CLI と画面の共通部)。

時刻はすべて「元動画のフレーム番号」で扱い、区間は [開始, 終了) の半開区間。
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import srt2resolve as S  # noqa: E402

ToolError = S.ToolError
VERSION = "0.11.0"   # cut2resolve の版の正はここ1か所(CLI・serve.py はこれを使う。README の見出しもそろえる)
CUT_EXTS = {".txt", ".csv"}
JSON_EXTS = {".json"}
TRANSCRIPT_SCHEMA = "youtube-tools-transcript/v1"
CUT_PLAN_SCHEMA = "youtube-tools-cut-plan/v1"
MAX_JSON_BYTES = 32 * 1024 * 1024   # 文字起こし・cut-plan の上限(3時間の配信でも数MB)
MAX_EDL_EVENTS = 999                # CMX3600 のイベント番号は 3 桁


class Cancelled(ToolError):
    """画面から取り消された(ToolError の仲間なので、CLI 側の扱いは他のエラーと同じ)"""

    def __init__(self, message="取り消しました。"):
        super().__init__(message)


class OutputExists(ToolError):
    """既存の出力があり、上書きが指定されていない。画面は existing を一覧にして確認を出す"""

    def __init__(self, existing):
        self.existing = [Path(p) for p in existing]
        super().__init__("出力ファイルが既にあります(上書きする場合は --force を指定): "
                         + ", ".join(p.name for p in self.existing))


class Task:
    """長い処理(無音の検出・粗編集の書き出し・動画のコピー)の進み具合の報告と取り消し。
    画面(serve.py)はジョブごとに1つ作って渡す。CLI は渡さない(None = 報告も取り消しもしない、従来どおりの動作)"""

    def __init__(self, on_progress=None, cancel_event=None):
        self._on = on_progress
        self.cancel_event = cancel_event or threading.Event()

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def cancel(self):
        self.cancel_event.set()

    def check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    def report(self, frac=None, message=None):
        if self._on:
            try:
                self._on(frac, message)
            except Exception:   # 報告の失敗で処理を止めない
                pass


# ---------------------------------------------------------------- 時刻・カットリストの読み込み

_NUM = re.compile(r"\d+(?:\.\d+)?")
_RANGE_SPLIT = re.compile(r"\s*(?:-->|->|→|~|〜|～|–|—|-|\s)\s*")
_FIELD_SPLIT = re.compile(r"\s*[,;\t]\s*")   # CSV(「開始,終了」)・タブ区切り


def parse_time(text):
    """'12.5' / '1:02.5' / '0:01:02,5' -> 秒(float)。負数・空・変な文字は ToolError。
    全角の数字・コロン(IME で打ったもの)も読む。分・秒の欄が 60 以上(1:75 など)は打ち間違いとみなして断る"""
    t = unicodedata.normalize("NFKC", text).strip().replace(",", ".")
    parts = t.split(":")
    if not t or len(parts) > 3 or not all(_NUM.fullmatch(p) for p in parts):
        raise ToolError(f"時刻を読めません: {text!r}(例: 12.5 / 1:02.5 / 0:01:02)")
    if any(float(p) >= 60 for p in parts[1:]):
        raise ToolError(f"時刻の分・秒は 60 未満で書いてください: {text!r}(例: 1:05 = 1分5秒、75 = 75秒)")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def _pair(line):
    """1行を (開始秒, 終了秒) に。区切りは空白・-・~・〜・→ など。読めなければ CSV(カンマ・タブ・;)として読み直す。
    「1,5 3,5」(小数点がカンマ)は前者で、「5,20」(CSV)は後者で読める。CSV は3列目以降(ラベルなど)を無視する"""
    cands = []
    toks = [t for t in _RANGE_SPLIT.split(line) if t]
    if len(toks) == 2:
        cands.append(toks)
    fields = [t for t in _FIELD_SPLIT.split(line) if t]
    if len(fields) >= 2 and fields[:2] != toks:
        cands.append(fields[:2])
    err = None
    for a, b in cands:
        try:
            return parse_time(a), parse_time(b)
        except ToolError as e:
            err = err or e
    if err:
        raise err
    return None


def parse_cut_list(text):
    """1行1区間「開始 終了」(区切りは空白 - ~ 〜 → など。CSV の「開始,終了」も可)。# 以降はコメント。
    最初の行が数字を含まない(CSV の見出し「start,end」など)なら飛ばす。[(開始秒, 終了秒)]"""
    out = []
    first = True
    for no, raw in enumerate(text.replace("\ufeff", "").splitlines(), 1):
        line = unicodedata.normalize("NFKC", raw).split("#", 1)[0].strip()
        if not line:
            continue
        if first and not re.search(r"\d", line):
            first = False
            continue
        first = False
        try:
            pair = _pair(line)
        except ToolError as e:
            raise ToolError(f"{no}行目: {e}")
        if pair is None:
            raise ToolError(f"{no}行目を読めません(「開始 終了」の形式で書いてください): {raw.strip()}")
        a, b = pair
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


def _sec_to_ms(sec):
    """秒 -> ミリ秒(四捨五入。0.5 は大きい方へ = 文字起こしツールの srt_time と同じ)"""
    return math.floor(sec * 1000 + 0.5)


def sec_to_frames(sec, fps):
    return S.ms_to_frames(_sec_to_ms(sec), fps)


def cut_list_to_keeps(pairs, fps, total):
    """[(開始秒, 終了秒)] -> (フレームの区間[整理済み], 警告)。動画の長さを超える分は切る"""
    raw = [(sec_to_frames(a, fps), sec_to_frames(b, fps)) for a, b in pairs]
    warns = []
    if any(e > total or s >= total for s, e in raw):
        warns.append("動画の長さを超える区間は切り捨てました。")
    zero = sum(1 for s, e in raw if e <= s)
    if zero:
        warns.append(f"フレームに直すと長さが 0 になる短い区間が {zero} か所あり、無視しました"
                     f"(1フレーム = {float(Fraction(fps[1], fps[0])):.3f}秒)。")
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

def _ffmpeg_run(cmd, timeout, task=None, duration=None):
    """ffmpeg / ffprobe を実行する(シェルは使わない。引数はリストのまま渡す)。
    task を渡すと、-progress で進み具合を報告し、取り消されたら ffmpeg を止めて Cancelled を出す(画面用)"""
    if task is not None:
        return _ffmpeg_stream(cmd, timeout, task, duration)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise ToolError("ffmpeg が見つかりません。ffmpeg をインストールして PATH に通してください。")
    except subprocess.TimeoutExpired:
        raise ToolError("ffmpeg の処理が時間内に終わりませんでした。")


def _ffmpeg_stream(cmd, timeout, task, duration):
    """-progress pipe:1 の「out_time_us=」を読んで task.report(0〜1)。取り消し・時間切れは見張りのスレッドが ffmpeg を止める
    (標準出力の読み取りで止まっていても取り消せるように)。標準エラーは別のスレッドで全部読む(パイプが詰まらないように)"""
    task.check()
    cmd = [cmd[0], "-progress", "pipe:1"] + list(cmd[1:])
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise ToolError("ffmpeg が見つかりません。ffmpeg をインストールして PATH に通してください。")
    err, why = [], []
    done = threading.Event()
    deadline = time.monotonic() + timeout

    def read_err():
        err.append(proc.stderr.read())

    def watch():
        while not done.wait(0.2):
            if task.cancelled or time.monotonic() > deadline:
                why.append("cancel" if task.cancelled else "timeout")
                try:
                    proc.kill()
                except OSError:
                    pass
                return
    t_err = threading.Thread(target=read_err, daemon=True)
    t_watch = threading.Thread(target=watch, daemon=True)
    t_err.start()
    t_watch.start()
    try:
        for line in proc.stdout:
            key, _, val = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms") and duration:   # out_time_ms も中身はマイクロ秒(ffmpeg の既知の名前違い)
                try:
                    sec = int(val) / 1e6
                except ValueError:
                    continue
                task.report(max(0.0, min(1.0, sec / duration)), None)
        proc.wait()
    finally:
        done.set()
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()
        t_err.join(10)
        t_watch.join(1)
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
    if why and why[0] == "cancel":
        raise Cancelled()
    if why:
        raise ToolError("ffmpeg の処理が時間内に終わりませんでした。")
    return subprocess.CompletedProcess(cmd, proc.returncode, "", "".join(x for x in err if x))


def check_silence_params(noise_db, min_sec, pad_sec):
    for v in (noise_db, min_sec, pad_sec):
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ToolError("無音の設定は数値で指定してください。")
    if not -90 <= noise_db <= 0:
        raise ToolError("無音とみなす音量(--noise)は -90〜0 dB で指定してください(例: -35)。")
    if not 0.05 <= min_sec <= 60:
        raise ToolError("無音の長さ(--silence-min)は 0.05〜60 秒で指定してください。")
    if not 0 <= pad_sec <= 10:
        raise ToolError("話の前後に残す秒数(--silence-pad)は 0〜10 秒で指定してください。")


def detect_silence(video, fps, total, noise_db=-35.0, min_sec=0.6, pad_sec=0.15, task=None):
    """無音区間 -> 削る区間[(開始f, 終了f)]。話の前後に pad_sec だけ残す。
    音声は最初の音声トラック(粗編集の書き出しと同じ)。複数の音声トラックがある録画でも、どちらを調べたか食い違わないように"""
    check_silence_params(noise_db, min_sec, pad_sec)
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", S.arg_path(video), "-map", "0:a:0", "-vn", "-sn", "-dn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_sec}", "-f", "null", "-"]
    total_sec = float(Fraction(total * fps[1], fps[0]))
    r = _ffmpeg_run(cmd, 3600, task, total_sec)
    if r.returncode != 0:
        raise ToolError("無音の検出に失敗しました(音声が無い動画かもしれません): " + (r.stderr or "").strip()[-200:])
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

# タイムコードの計算は srt2resolve と共通(FCPXML の開始タイムコードにも使うため、向こうに1か所だけ持つ)
nominal_rate = S.nominal_rate
tc_to_frames = S.tc_to_frames
frames_to_tc = S.frames_to_tc


def check_timecodes(fps, rec_start="01:00:00:00", src_start="00:00:00:00"):
    """重い処理(無音の検出・粗編集の書き出し)の前に、タイムコードの指定を確かめる。
    以前は EDL を書く直前まで確かめず、粗編集の動画だけ書き出してから失敗していた"""
    nom = nominal_rate(fps)
    for label, tc in (("タイムラインの開始タイムコード(--rec-start)", rec_start),
                      ("元動画の開始タイムコード(--src-start-tc)", src_start)):
        try:
            tc_to_frames(str(tc), nom)
        except ToolError as e:
            raise ToolError(f"{label}: {e}")


_TC_RE = S.TC_RE


def read_start_tc(video):
    """動画に埋め込まれた開始タイムコード('HH:MM:SS:FF')。無ければ None。
    Resolve はこれをクリップの開始タイムコード(Start TC)として使う。EDL の元動画側の時刻がその範囲に
    入っていないと「タイムコードの範囲が一致しない」で結び付かないため、EDL にも同じ値を足す必要がある"""
    r = _ffmpeg_run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                     S.arg_path(video)], 60)
    try:
        info = json.loads(r.stdout or "{}")
    except ValueError:
        return None
    tcs = [(s.get("tags") or {}).get("timecode") for s in info.get("streams", [])]
    tcs.append(((info.get("format") or {}).get("tags") or {}).get("timecode"))
    return next((t.strip() for t in tcs if t and _TC_RE.fullmatch(t.strip())), None)


def resolve_src_start(video, override=None, meta=None):
    """EDL の元動画側の開始タイムコード -> (値, 由来の説明, 警告リスト)。
    指定があればそれ、無ければ動画に埋め込まれた値、それも無ければ 00:00:00:00。
    meta(srt2resolve.probe の結果)を渡すと、そこで読んだ値を使う(ffprobe をもう一度呼ばない)"""
    if override and str(override).strip():
        tc, desc = str(override).strip(), "指定"
    else:
        tc = meta.get("start_tc") if meta is not None and "start_tc" in meta else read_start_tc(video)
        desc = "動画に埋め込まれた値"
        if not tc:
            return "00:00:00:00", "動画に埋め込みなし", []
    warns = []
    if ";" in tc:
        warns.append(f"開始タイムコード {tc} はドロップフレーム表記です。ノンドロップとして扱うため、"
                     "数フレームずれることがあります。")
        tc = tc.replace(";", ":")
    return tc, desc, warns


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
    clip_name = re.sub(r"[\r\n]+", " ", clip_name)   # 改行が入ると EDL の行が崩れる(Windows のファイル名には入らないが念のため)
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

def render_rough_cut(video, keeps, fps, has_audio, out_path, crf=18, task=None):
    """残す区間だけをつないだ H.264 の mp4 を作る(再エンコード。フレーム単位で切る)。
    一時ファイルに書き出してから置き換える(途中で失敗・取り消しても、書きかけの mp4 を残さない)"""
    if not keeps:
        raise ToolError("残す区間がありません。")
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
    kept_sec = float(Fraction(sum(e - s for s, e in keeps) * fps[1], fps[0]))
    out_path = Path(S.arg_path(out_path))
    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), prefix=".tmp-" , suffix=".mp4")
    os.close(fd)
    out_opts = ["-map", "[outv]"] + (["-map", "[outa]"] if has_audio else []) + [
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p",
        "-r", f"{fps[0]}/{fps[1]}"]
    if has_audio:
        out_opts += ["-c:a", "aac", "-b:a", "192k"]
    out_opts += ["-movflags", "+faststart", "-f", "mp4", tmp]
    try:
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "filter.txt"
            sp.write_text(script, encoding="utf-8")
            err = ""
            # 長い区間リストでも Windows のコマンド長制限に当たらないよう、フィルタはファイルで渡す。
            # 新しい ffmpeg では -filter_complex_script が -/filter_complex に置き換わっているため両方試す
            for opt in ("-filter_complex_script", "-/filter_complex"):
                r = _ffmpeg_run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", S.arg_path(video), opt, str(sp)] + out_opts,
                                7200, task, kept_sec)
                if r.returncode == 0:
                    S._replace_retry(tmp, str(out_path))
                    tmp = None
                    return
                err = (r.stderr or "").strip()
                if "nrecognized option" not in err and "not found" not in err:
                    break
        raise ToolError("粗編集の動画を書き出せませんでした: " + err[-300:])
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------- 表示・手順書・出力

def fmt_sec(sec):
    """0:05.20 / 1:02:03.45。先に 1/100 秒に丸める(以前は 59.996 秒が「0:60.00」になった)"""
    cs = int(round(max(0.0, sec) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s = rem / 100
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


def build_readme(video_name, meta, keeps, edl_name, srt_name, rough_name, rec_start, src_start, extras=None):
    """友人へ.txt。extras: [(ファイル名, 説明)](cut-plan.json・FCPXML など、追加で入れたもの)"""
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
    rough += "".join(f"\n  ・{n}  … {d}" for n, d in (extras or []))
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
   (Start TC が別の値のままにしたいときは、ツールの画面の「元動画の開始タイムコード」
    またはコマンドの --src-start-tc にその値を入れて、作り直してください)

残す区間(元動画のタイムコード)
   #    開始           終了
{rows}
"""


def write_pack(out_dir, video, meta, keeps, cues_out, args_reel="AX", rec_start="01:00:00:00",
               src_start="00:00:00:00", rough_path=None, edl_title=None, extras=None, readme_path=None, stem=None):
    """EDL・字幕・手順書を書く(どれも一時ファイル経由で置き換える)。書いたファイルのパス辞書を返す。
    extras: 友人へ.txt に載せる追加のファイル [(名前, 説明)](書くのは呼び出し側)
    readme_path: EDL の手順書の置き場所(既定は 友人へ.txt。Text+ パックでは予備の手順書にする)
    stem: EDL・SRT の名前(既定は video の名前。余白つき素材を使うときも、名前は元の切り抜きにそろえる)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = meta["fps"]
    stem = stem or video.stem
    edl_p = out_dir / f"{stem}.edl"
    srt_p = out_dir / f"{stem}_cut.srt"
    txt_p = Path(readme_path) if readme_path else out_dir / "友人へ.txt"
    S.write_text_atomic(edl_p, build_edl(edl_title or stem, video.name, keeps, fps, bool(meta["audio"]),
                                         args_reel, rec_start, src_start),
                        encoding="utf-8", newline="")
    files = {"edl": edl_p}
    if cues_out is not None:
        S.write_text_atomic(srt_p, S.build_srt(cues_out, fps), encoding="utf-8", newline="\n")
        files["srt"] = srt_p
    S.write_text_atomic(txt_p, build_readme(video.name, meta, keeps, edl_p.name,
                                            srt_p.name if cues_out is not None else None,
                                            rough_path.name if rough_path else None, rec_start, src_start, extras),
                        encoding="utf-8-sig", newline="\n")
    files["readme"] = txt_p
    return files


def validate_output_paths(paths, force=False, protected=()):
    """出力の誤上書きを防ぐ。入力ファイルとの衝突は --force でも禁止。
    既存の出力があれば OutputExists(ToolError の仲間。existing に一覧)"""
    outputs = [Path(p) for p in paths]
    collisions = [p for p in outputs if any(S.same_path(p, q) for q in protected if q is not None)]
    if collisions:
        raise ToolError("出力先が入力ファイルと同じです: " + ", ".join(p.name for p in collisions))
    existing = [p for p in outputs if p.exists()]
    if existing and not force:
        raise OutputExists(existing)


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


def split_json_inputs(paths):
    """(.json 以外, .json)。フル版は動画・字幕・カットリストに加えて、文字起こし・cut-plan の JSON も順不同で受け取る"""
    js = [p for p in paths if p.suffix.lower() in JSON_EXTS]
    return [p for p in paths if p not in js], js


def copy_video(video, out_dir, task=None, dst=None):
    """元動画を出力フォルダへコピーする(一時ファイル経由。途中で止めても書きかけを残さない)。task で進み具合と取り消し"""
    video = Path(video)
    dst = Path(dst) if dst else Path(out_dir) / video.name
    if S.same_path(dst, video):
        return dst
    size = video.stat().st_size
    fd, tmp = tempfile.mkstemp(dir=S.arg_path(dst.parent), prefix=".tmp-", suffix=".part")
    try:
        with open(video, "rb") as src, os.fdopen(fd, "wb") as out:
            done = 0
            while True:
                if task:
                    task.check()
                buf = src.read(8 * 1024 * 1024)
                if not buf:
                    break
                out.write(buf)
                done += len(buf)
                if task and size:
                    task.report(done / size, None)
        shutil.copystat(str(video), tmp)
        S._replace_retry(tmp, str(dst))
        tmp = None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return dst


# ---------------------------------------------------------------- 受け渡しの JSON(docs/pipeline.md)

def _reject_constant(name):
    raise ValueError(f"NaN / Infinity は使えません: {name}")


def read_json_file(path, what="JSON", max_bytes=MAX_JSON_BYTES):
    """UTF-8(BOM があっても可)の JSON を読む。大きすぎる・壊れている・NaN を含むものは ToolError"""
    p = Path(path)
    try:
        with open(p, "rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError as e:
        raise ToolError(f"{what}を読めません: {p.name}({e.strerror or e.__class__.__name__})")
    if len(raw) > max_bytes:
        raise ToolError(f"{what}が大きすぎます(上限 {max_bytes // 1024 // 1024}MB): {p.name}")
    try:
        return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError):
        raise ToolError(f"{what}を読めません(JSON の形式が正しくありません): {p.name}")


def check_schema(d, schema, what):
    """schema が一致しなければ ToolError。同じ種類の別の版は「未対応の版」と伝える(docs/pipeline.md の 1)"""
    got = d.get("schema") if isinstance(d, dict) else None
    if got == schema:
        return
    kind = schema.rsplit("/", 1)[0] + "/"
    if isinstance(got, str) and got.startswith(kind):
        raise ToolError(f"{what}は未対応の版です({got[:60]}。読めるのは {schema})。")
    raise ToolError(f"{what}ではありません(schema が {schema} ではありません)。")


def json_schema(path):
    """JSON の schema(読めなければ None)。フル版の CLI が、順不同で渡された .json の種類を見分けるのに使う"""
    try:
        d = read_json_file(path)
    except ToolError:
        return None
    s = d.get("schema") if isinstance(d, dict) else None
    return s if isinstance(s, str) else None


def num(v):
    """有限の数(真偽値は除く)なら float、それ以外は None"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def is_network_path(p):
    """ネットワーク上のパス(\\\\サーバー\\共有 など)か。他人が作ったかもしれない JSON の中のパスでは調べない
    (Windows では存在を確かめるだけでそのサーバーへ接続し、資格情報のハッシュを送ってしまうため。文字起こしツールと同じ扱い)"""
    return str(p or "").replace("/", "\\").startswith("\\\\")


EDIT_MEDIA_SCHEMA = "clip-studio/edit-media/v1"
EDIT_MEDIA_SUFFIX = ".edit.json"
MAX_EDIT_JSON_BYTES = 64 * 1024        # 中身は数百バイト


def find_edit_media(video):
    """切り抜きスタジオの「前後の余白つき素材」(<動画の名前>.edit.json と <名前>_edit.mp4)を探す。
    -> {"path", "sidecar", "selectionIn", "handleBefore", "handleAfter"}(秒)か None(無い・読めない・形が違う)。
    selectionIn = 余白つき素材の中で、切り抜き(= video)の先頭が何秒目か。video の時刻 t は、余白つき素材では selectionIn + t。
    素材は .edit.json と同じフォルダの中だけを見る(名前だけを使う。../ やネットワークのパスを指させない)"""
    video = Path(video)
    sidecar = video.with_name(video.stem + EDIT_MEDIA_SUFFIX)
    if is_network_path(str(video)) or not sidecar.is_file():
        return None
    try:
        d = read_json_file(sidecar, "余白つき素材の情報(.edit.json)", MAX_EDIT_JSON_BYTES)
    except ToolError:
        return None
    if not isinstance(d, dict) or d.get("schema") != EDIT_MEDIA_SCHEMA or not isinstance(d.get("media"), str):
        return None
    name = os.path.basename(d["media"].replace("\\", "/").strip())
    vals = [num(d.get(k)) for k in ("selectionIn", "handleBefore", "handleAfter")]
    if not name or any(v is None or v < 0 or v > 3600 for v in vals):
        return None
    media = sidecar.with_name(name)
    if not media.is_file() or S.same_path(media, video):
        return None
    return {"path": media, "sidecar": sidecar, "selectionIn": vals[0], "handleBefore": vals[1], "handleAfter": vals[2]}


def resolve_media_path(media, json_path):
    """JSON の media から動画の実際のパス。①media.path にあればそれ ②無ければ JSON と同じフォルダの同名ファイル
    (フォルダごと移動した・友人に渡した場合への備え。docs/pipeline.md の 1)。見つからなければ None"""
    if not isinstance(media, dict):
        return None
    cands = []
    p = media.get("path")
    if isinstance(p, str) and p.strip():
        cands.append(p.strip())
    name = media.get("name") if isinstance(media.get("name"), str) and media.get("name").strip() else (
        p.strip() if isinstance(p, str) else "")
    if name:
        base = os.path.basename(name.strip().replace("\\", "/"))   # 名前だけを使う(../ でフォルダの外を指させない)
        if base:
            cands.append(os.path.join(os.path.dirname(os.path.abspath(str(json_path))), base))
    for c in cands:
        try:
            if is_network_path(c):
                continue
            if os.path.isfile(c):
                return os.path.abspath(c)
        except (OSError, ValueError):
            continue
    return None


def read_transcript(path):
    """youtube-tools-transcript/v1 -> {"rows": [{"id","start","end","text","cut"}](時刻順), "bad": 読めなかった行の数,
    "media": {...}, "title"}。時刻は秒(動画の先頭 = 0)"""
    d = read_json_file(path, "文字起こし(.transcript.json)")
    check_schema(d, TRANSCRIPT_SCHEMA, "文字起こし(youtube-tools-transcript/v1)")
    segs = d.get("segments")
    if not isinstance(segs, list):
        raise ToolError("文字起こしに segments(行の一覧)がありません。")
    rows, bad = [], 0
    for g in segs:
        if not isinstance(g, dict):
            bad += 1
            continue
        a, b = num(g.get("start")), num(g.get("end"))
        if a is None or b is None or a < 0 or b <= a:
            bad += 1
            continue
        text = g.get("text")
        rows.append({"id": str(g.get("id") or ""), "start": a, "end": b,
                     "text": text.strip() if isinstance(text, str) else "",
                     "cut": g.get("cut") in (True, "true")})
    rows.sort(key=lambda r: (r["start"], r["end"]))
    media = d.get("media") if isinstance(d.get("media"), dict) else {}
    return {"rows": rows, "bad": bad, "media": media, "title": str(d.get("title") or "")}


def row_is_kept(row):
    """残す行 = 「カット済」でなく、文字がある行(文字起こしツールの resolve_export.is_kept と同じ規則)"""
    return not row["cut"] and bool(row["text"])


def merge_sec_spans(spans):
    """[(開始秒, 終了秒)] の重なる・接するものをまとめる(文字起こしツールの kept_spans と同じ: 行と行の間のすき間は残さない)"""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def transcript_kept_spans(rows):
    return merge_sec_spans([(r["start"], r["end"]) for r in rows if row_is_kept(r)])


def transcript_cut_spans(rows):
    """「カット済」の行の時間(秒)。残す行と重なる部分は、呼び出し側で残す行を優先して引く"""
    return merge_sec_spans([(r["start"], r["end"]) for r in rows if r["cut"]])


def transcript_cues(rows):
    """字幕 = 残す行(カット済でない・文字がある行)。[(開始ms, 終了ms, 文)]"""
    return [(_sec_to_ms(r["start"]), _sec_to_ms(r["end"]), r["text"]) for r in rows if row_is_kept(r)]
