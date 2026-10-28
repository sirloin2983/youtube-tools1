"""素材を 30fps にそろえる(Q1。資料の git:before-1028-cleanup:plan/line-bc-master-plan.md。ユーザー決定)。

決まり: **H.264・8bit・yuv420p・30/1 の固定(CFR)・AAC** ならそのまま使う(作り直さない)。違えば ffmpeg で作り直す。
画質の設定は 1 か所(libx264 crf 18。GPU は同じくらいの画質の値)。スタジオの書き出し・ライブの区間の作り直しもここの引数を使う。

作り直しの作り方(encode_tries。全体の作り直し normalize・スタジオの書き出し・ライブの区間の作り直しで同じ):
- GPU の作り方(NVIDIA h264_nvenc → AMD h264_amf → Intel h264_qsv の順で、最初に使える 1 つ)が使えればそれで作る(CPU の libx264 の数倍速い)。
  使えるかは ffmpeg で 0.1 秒の見本を作って確かめる(ffmpeg ごとに 1 回だけ覚える)。GPU で失敗したら libx264 で 1 回だけやり直す。
  環境変数 YTT_GPU_ENC=0 で GPU を使わない(スイッチ = 全部 libx264)。どれで作ったかは呼ぶ側が記録する(normalize は戻り値の "how")
- 読み込み(デコード)も GPU に(decode_tries・HW_DECODE。10-29): GPU の作り方では -hwaccel cuda / d3d11va を入力側に付けた回を先に、
  失敗したら同じ作り方を読み込み CPU で、最後は libx264。環境変数 YTT_HW_DEC=0 で読み込みは CPU のまま(スイッチ)。戻り値の "hwdec" が印
- GPU の画質の値は、元との VMAF と大きさが libx264 crf 18 と同じくらいになるように合わせた物(届ける zip を大きくしない)。
  環境変数 YTT_ENC_PREV=1 で前の値(PREV_ARGS)に戻す。どの値で作ったかの印は enc_set()(.clip.json の export.encodeSet)
- normalize() だけ、映像がもう条件どおりで音声だけが違う(AAC でない)ときは、映像はコピーして音声だけ作り直す(video_ok)

- 時刻は秒のまま保たれる(ずらさない): fps フィルタは各コマの表示時刻をそのまま 1/30 秒の格子に当てはめるだけなので、
  文字起こし・マークの時刻(秒)は作り直したあともそのまま使える。
- 60fps → 30fps は1コマおきに落とす。29.97fps → 30fps はコマを落とさず、約 33 秒に1コマを複製して揃う(目立たない)。
- VFR(コマの間隔が一定でない録画)も、fps フィルタ + -fps_mode cfr で一定の間隔になる。
- 重い処理の同時実行の上限(ytt.jobs.SLOTS)は**呼ぶ側が持つ**(このモジュールは SLOTS を取らない。呼ぶ側の処理の単位で順番を待つため)。

使い方:
    info = normalize.probe(src)                 # ffprobe が無ければ None
    need, why = normalize.needs_normalize(info)
    if need:
        with jobs.SLOTS.slot("intake", name, cancelled=...) as ok:
            if ok:
                normalize.normalize(src, dst, cancelled=..., on_progress=...)
"""
import os
import re
import subprocess
import uuid
from fractions import Fraction

from . import fsio, schemas, tools

TARGET_FPS = 30
AVG_TOL = 0.01            # avg_frame_rate は 29.99〜30.01 を許す(長さの端数で 30/1 ちょうどにならないことがある)
DURATION_TOL = 0.5        # 作り直したあとの長さが元と ±この秒数なら良しとする
PRESET = "veryfast"       # スタジオの「精密」と同じ
FAST_PRESET = "ultrafast" # スタジオの「高速」(コピーでは fps を変えられないので、速い設定で作り直す)
CRF = "18"
IDLE_SEC = 600            # ffmpeg がこの秒数まったく出力しなければ止める
PART = ".normalizing-"    # 作り直しの途中の名前(<名前>.normalizing-xxxxxxxx.mp4。検証が済んでから本当の名前へ)
GPU_ENV = "YTT_GPU_ENC"   # "0" で GPU の作り方を使わない(全部 libx264)
PREV_ENV = "YTT_ENC_PREV" # "1" で GPU の画質の値を前の物(PREV_ARGS)に戻す
CPU = "libx264"
ENC_SET = "1021"          # GPU の画質の値の版(.clip.json の export.encodeSet の印。前の値に戻したときは prev)
# GPU の作り方(確かめる順)と、映像の作り方の引数(-c:v から。元との VMAF と大きさが libx264 crf 18 と同じくらい)。
# AMF は P 23(I 21・B 25)・quality。NVENC・QSV はこの PC で試せないので AMF で動かした幅(QP 20 → 23)に合わせた値
GPU_ENCODERS = (
    ("h264_nvenc", ["-preset", "p4", "-rc", "vbr", "-cq", "22", "-b:v", "0"]),   # p4 = 速さと画質の中ほど
    ("h264_amf", ["-quality", "quality", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23", "-qp_b", "25"]),
    ("h264_qsv", ["-preset", "medium", "-global_quality", "23"]),
)
PREV_ARGS = {"h264_nvenc": ["-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0"],   # 前の値(YTT_ENC_PREV=1)
             "h264_amf": ["-quality", "balanced", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20", "-qp_b", "22"],
             "h264_qsv": ["-preset", "medium", "-global_quality", "20"]}
# 読み込み(デコード)も GPU に(10-29 処理の速さの見直し 4-3。1080p60 の H.264 を CPU で読むのが作り直しの重さの大半)。
# 入力側の引数(-i の前)。コマは普通のメモリに戻す(-hwaccel_output_format は付けない)ので、fps・yuv420p のフィルタは今までどおり CPU 側で動く。
# GPU の読み込みが失敗したら(ドライバ・10 bit・対応しない形式)、同じ作り方を読み込み CPU で 1 回やり直し、最後は libx264(decode_tries)
HWDEC_ENV = "YTT_HW_DEC"   # "0" で読み込みに GPU を使わない(スイッチ。作り方の GPU はそのまま)
HW_DECODE = {"h264_nvenc": ["-hwaccel", "cuda"],      # NVIDIA(友人の PC)
             "h264_amf": ["-hwaccel", "d3d11va"],     # AMD(この PC)
             "h264_qsv": ["-hwaccel", "d3d11va"]}     # Intel(qsv の hwaccel は GPU のコマのままになるので d3d11va)
_PIX_DEPTH = re.compile(r"p(\d{2})(?:le|be)$")             # yuv420p10le などの bit 数


class NormalizeError(Exception):
    pass


class Cancelled(NormalizeError):
    pass


def fps_filter(vf=None):
    """-vf の中身。既に映像のフィルタ(例 scale=…)があれば、そのあとに fps=30 をつなぐ"""
    f = "fps=%d" % TARGET_FPS
    return "%s,%s" % (vf, f) if vf else f


def use_prev():
    """GPU の画質の値を前の物に戻すスイッチ(YTT_ENC_PREV=1)が入っているか"""
    return os.environ.get(PREV_ENV, "").strip() == "1"


def enc_set():
    """今の GPU の画質の値の版(印)。前の値に戻していれば prev"""
    return "prev" if use_prev() else ENC_SET


def video_args(codec=CPU, preset=PRESET):
    """映像の作り方の引数(-c:v から。preset は libx264 のときだけ使う)"""
    if codec == CPU:
        return ["-c:v", CPU, "-preset", preset, "-crf", CRF]
    return ["-c:v", codec] + (PREV_ARGS if use_prev() else dict(GPU_ENCODERS))[codec]


def encode_args(preset=PRESET, vf=None, in_graph=False, codec=CPU):
    """作り直しの ffmpeg の出力側の引数(入力・-progress・出力のパスは呼ぶ側)。codec = libx264 か GPU_ENCODERS の 1 つ。
    in_graph=True: -filter_complex の中で fps=30 をかける呼び出し側用(-vf と -filter_complex は同じ出力に一緒に使えないため -vf を付けない)。
    -r 30 は付けない(fps フィルタで足りる。両方付けると二重に丸める)。音声は AAC 192k(サンプリング周波数は元のまま。スタジオの書き出しと同じ)"""
    args = [] if in_graph else ["-vf", fps_filter(vf)]
    return args + ["-fps_mode", "cfr"] + video_args(codec, preset) + ["-pix_fmt", "yuv420p",
                                                                       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]


ENC_ARGS = encode_args()                     # スタジオの「精密」の CPU の作り方
ENC_FAST_ARGS = encode_args(FAST_PRESET)     # スタジオの「高速」の CPU の作り方


# 映像はコピーし、音声だけ AAC に作り直す(映像が条件どおりのとき)
AUDIO_ONLY_ARGS = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]

_gpu = {}   # ffmpeg のパス -> 使える GPU の作り方の名前か None(1 回だけ確かめる)


def _encoder_works(ffmpeg, codec, runner=None):
    """ffmpeg で codec が実際に使えるか(一覧に有ってもその GPU が無ければ失敗するので、0.1 秒の見本を作って確かめる)"""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=30:d=0.1",
           "-c:v", codec, "-pix_fmt", "yuv420p", "-f", "null", "-"]
    try:
        if runner is not None:
            return runner(cmd) == 0
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                              creationflags=tools.no_window_flags(new_group=True)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def gpu_encoder(ffmpeg, runner=None):
    """この PC の ffmpeg で使える GPU の作り方の名前(GPU_ENCODERS の順で最初に使える物)か None。
    YTT_GPU_ENC=0 なら None。runner(cmd) -> 終了コード はテスト用の差し替え(覚えない)"""
    if os.environ.get(GPU_ENV, "").strip() == "0" or not ffmpeg:
        return None
    if ffmpeg in _gpu and runner is None:
        return _gpu[ffmpeg]
    got = next((c for c, _a in GPU_ENCODERS if _encoder_works(ffmpeg, c, runner)), None)
    if runner is None:
        _gpu[ffmpeg] = got
    return got


def encode_tries(ffmpeg, preset=PRESET, vf=None, in_graph=False, runner=None):
    """作り直しの作り方の順 [(作り方の名前, encode_args の結果)]。GPU が使えれば GPU → libx264(前が失敗したら次で 1 回だけ)"""
    gpu = gpu_encoder(ffmpeg, runner)
    tries = [(gpu, encode_args(preset, vf, in_graph, gpu))] if gpu else []
    return tries + [(CPU, encode_args(preset, vf, in_graph))]


def decode_args(codec):
    """codec(作り方)に合わせた、読み込みを GPU にする入力側の引数(-i の前)。libx264・知らない作り方・YTT_HW_DEC=0 なら []"""
    if not codec or codec == CPU or os.environ.get(HWDEC_ENV, "").strip() == "0":
        return []
    return list(HW_DECODE.get(codec, []))


def hwdec_name(pre):
    """decode_args の結果 -> 読み込みの名前(cuda・d3d11va。印用。無ければ "")"""
    return str(pre[1]) if pre and len(pre) >= 2 else ""


def decode_tries(tries):
    """encode_tries の [(作り方, 出力側の引数)] -> [(作り方, 入力側の引数, 出力側の引数)]。
    GPU の作り方は「読み込みも GPU」の回を先に置き、だめなら同じ作り方を読み込み CPU で、最後は libx264(読み込み CPU)。
    入力側の引数が無い作り方(libx264・スイッチ切)はその 1 回だけ"""
    out = []
    for how, enc in tries:
        pre = decode_args(how)
        if pre:
            out.append((how, pre, enc))
        out.append((how, [], enc))
    return out


def video_ok(info):
    """映像が条件どおり(H.264・8bit・yuv420p・30/1 の固定)か = 作り直しが要るのは音声だけか"""
    return bool(info and info.get("has_video") and info.get("vcodec") == "h264" and info.get("bit_depth") in (8, None)
                and info.get("pix_fmt") == "yuv420p" and is_30fps(info))


# ---------- 古い ffmpeg への備え ----------
# -fps_mode は ffmpeg 5.1 から。それより古い ffmpeg(友人の PC など)は「Unrecognized option 'fps_mode'」で失敗するので、
# 同じ意味の古い書き方 -vsync cfr に替えて1回だけやり直す(新しい ffmpeg 7 以降は逆に -vsync が無いので、最初から -vsync にはしない)
def legacy_args(args):
    """-fps_mode X を -vsync X に替えた引数のリスト(ほかはそのまま)"""
    out = list(args)
    for i, a in enumerate(out):
        if a == "-fps_mode":
            out[i] = "-vsync"
    return out


def is_fps_mode_error(text):
    """ffmpeg のエラーの文が「-fps_mode を知らない」か(Unrecognized option 'fps_mode' / Option fps_mode not found など)"""
    t = str(text or "")
    return "fps_mode" in t and bool(re.search(r"Unrecognized option|not found|Invalid option|unknown option", t, re.I))


# ---------- 調べる ----------
def _ratio(s):
    """"30000/1001" → Fraction。0/0・読めないときは None"""
    try:
        n, _, d = str(s or "").partition("/")
        f = Fraction(int(n), int(d or 1))
    except (ValueError, ZeroDivisionError):
        return None
    return f if f > 0 else None


def _bit_depth(stream):
    try:
        n = int(stream.get("bits_per_raw_sample") or 0)
    except (TypeError, ValueError):
        n = 0
    if n:
        return n
    m = _PIX_DEPTH.search(str(stream.get("pix_fmt") or ""))
    return int(m.group(1)) if m else (8 if stream.get("pix_fmt") else None)


def probe(path, ffprobe=None, timeout=60):
    """ffprobe(JSON)で調べる。ffprobe が無い・読めないときは None。
    -> {"path", "duration", "width", "height", "vcodec", "pix_fmt", "bit_depth", "r_frame_rate", "avg_frame_rate",
        "fps"(r_frame_rate の値), "avg_fps", "cfr"(推定: r と avg がほぼ同じ), "acodec"(音声が無ければ None),
        "sample_rate", "has_video", "has_audio"}"""
    fp = ffprobe or tools.find_tool("ffprobe")
    if not fp:
        return None
    try:
        data = tools.ffprobe_json(fp, ["-show_entries", "format=duration:stream=index,codec_type,codec_name,pix_fmt,bits_per_raw_sample,"
                                       "width,height,r_frame_rate,avg_frame_rate,sample_rate,duration", path], timeout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = schemas.num_or((data.get("format") or {}).get("duration"))
    if dur is None and v:
        dur = schemas.num_or(v.get("duration"))
    info = {"path": path, "duration": dur, "has_video": v is not None, "has_audio": a is not None,
            "vcodec": None, "pix_fmt": None, "bit_depth": None, "width": None, "height": None,
            "r_frame_rate": None, "avg_frame_rate": None, "fps": None, "avg_fps": None, "cfr": None,
            "acodec": (a or {}).get("codec_name"), "sample_rate": int(schemas.num_or((a or {}).get("sample_rate")) or 0) or None}
    if v:
        r_, avg = _ratio(v.get("r_frame_rate")), _ratio(v.get("avg_frame_rate"))
        info.update(vcodec=v.get("codec_name"), pix_fmt=v.get("pix_fmt"), bit_depth=_bit_depth(v),
                    width=v.get("width"), height=v.get("height"),
                    r_frame_rate=v.get("r_frame_rate"), avg_frame_rate=v.get("avg_frame_rate"),
                    fps=float(r_) if r_ else None, avg_fps=float(avg) if avg else None,
                    # CFR の推定: r_frame_rate(いちばん多い間隔)と avg_frame_rate(平均)がほぼ同じ。VFR の録画は平均がずれる
                    cfr=bool(r_ and avg and abs(float(r_) - float(avg)) <= AVG_TOL))
    return info


def is_30fps(info):
    """30/1 の固定(r_frame_rate が 30/1・avg が 29.99〜30.01)"""
    return bool(info and _ratio(info.get("r_frame_rate")) == TARGET_FPS
                and info.get("avg_fps") is not None and abs(info["avg_fps"] - TARGET_FPS) <= AVG_TOL)


def needs_normalize(info):
    """(作り直しが要るか, 理由のリスト)。info は probe の結果(None = 調べられなかった → 要る扱い)。
    音声が無い動画は、音声の条件を見ない(作り直しても足せないため)"""
    if not info:
        return True, ["ffprobe で調べられませんでした"]
    why = []
    if not info.get("has_video"):
        return True, ["映像がありません"]
    if info.get("vcodec") != "h264":
        why.append("映像が H.264 ではありません(%s)" % (info.get("vcodec") or "不明"))
    if info.get("bit_depth") not in (8, None):
        why.append("%d bit です(8 bit にします)" % info["bit_depth"])
    if info.get("pix_fmt") != "yuv420p":
        why.append("色の形式が yuv420p ではありません(%s)" % (info.get("pix_fmt") or "不明"))
    if not is_30fps(info):
        why.append("30fps の固定ではありません(%s / 平均 %s)" % (info.get("r_frame_rate") or "不明",
                                                          "%.3f" % info["avg_fps"] if info.get("avg_fps") else "不明"))
    if info.get("has_audio") and info.get("acodec") != "aac":
        why.append("音声が AAC ではありません(%s)" % (info.get("acodec") or "不明"))
    return bool(why), why


# ---------- 作り直す ----------
def temp_path(dst):
    """作り直しの途中の名前(dst と同じフォルダ。拡張子は .mp4 のまま = ffmpeg は拡張子で形式を決める)"""
    d, n = os.path.split(os.path.abspath(dst))
    return os.path.join(d, os.path.splitext(n)[0] + PART + uuid.uuid4().hex[:8] + ".mp4")


def _report(on_progress, v):
    """進み具合を知らせる(知らせる側の失敗で作り直しを止めない)"""
    if on_progress:
        try:
            on_progress(v)
        except Exception:
            pass


def run_ffmpeg(cmd, flags=None, popen=None, cancelled=None, idle_sec=None, on_progress=None, dur=0.0):
    """ffmpeg を1回動かす(cmd は -progress pipe:1 つき)。cancelled() が真・idle_sec 秒なにも出力しなければ止める(ytt.tools.run_progress)。
    on_progress(0〜0.99) は out_time / dur(dur が 0 以下なら知らせない。知らせる側の失敗では止めない)。
    -> (終了コード, エラーの行の最後の 20 行, 止めた理由 None|"cancel"|"idle")。起動できなければ NormalizeError"""
    on_time = (lambda sec: _report(on_progress, min(0.99, sec / dur))) if on_progress and dur > 0 else None
    try:
        return tools.run_progress(cmd, flags, cancelled, idle_sec, on_time, popen, tail=20)
    except OSError as e:
        raise NormalizeError("ffmpeg を起動できませんでした: %s" % e)


def run_with_legacy(run, enc, tmp=None, cancelled=None):
    """run(出力側の引数) -> (終了コード, エラーの行, 止めた理由) を動かす。ffmpeg が 5.1 より古くて -fps_mode を知らなければ、
    書きかけ tmp を消して -vsync に替えて(legacy_args)1回だけやり直す。止めた・cancelled() が真ならやり直さない。
    -> 最後の (終了コード, エラーの行, 止めた理由)"""
    code, tail, why = run(enc)
    if code != 0 and why is None and not (cancelled and cancelled()) and is_fps_mode_error("\n".join(tail)):
        if tmp:
            fsio.unlink_quiet(tmp)
        code, tail, why = run(legacy_args(enc))
    return code, tail, why


def concat_list(paths, list_path):
    """ffmpeg の concat の一覧を list_path に書く(1 行 1 ファイル。区切りは / にそろえ、' は逃がす)。-> list_path"""
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write("file '%s'\n" % p.replace("\\", "/").replace("'", "'\\''"))
    return list_path


def section_cmd(ffmpeg, paths, ss, dur, out, enc, list_path=None):
    """区間を切り出して 30fps に作り直す ffmpeg の引数の全部(enc = encode_args() か legacy_args の結果。-progress pipe:1 つき)。
    paths が 1 つならそのまま読み、2 つ以上なら concat の一覧 list_path(concat_list で書いた物)を読む(時刻はファイルの長さで続ける)。
    -ss は入力の前(作り直しなので位置はコマ単位で正確)。長さは出力の -t で決める(入力の -t だけだと、fps フィルタが最後のコマを
    増やして映像が約 0.5 秒長くなる)。入力の -t は読む量を抑えるだけ(1 秒長め)"""
    src = ["-i", paths[0]] if len(paths) == 1 else ["-f", "concat", "-safe", "0", "-i", list_path]
    return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "%.3f" % ss, "-t", "%.3f" % (dur + 1.0)] + src + \
        ["-t", "%.3f" % dur, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"] + list(enc) + ["-progress", "pipe:1", "-nostats", out]


def encode_section(ffmpeg, paths, ss, dur, out, run, afilter=None):
    """paths(時刻の順。1 つか、つなぎ直しごとのファイル)の ss 秒から dur 秒を 30fps に作り直して out に書く(ライブの書き出し)。
    2 つ以上なら concat の一覧を最初のファイルと同じフォルダの parts.txt に書いてつなぐ。run(引数の全部) -> (終了コード, エラーの行, 止めた理由) は
    呼ぶ側の動かし方(取り消し・進み具合・優先度)。ffmpeg が 5.1 より古ければ -vsync で 1 回だけやり直す(run_with_legacy)。
    afilter: 音声の -af(音量。作り直しの中でかける = 後から音声だけ作り直さない。音声の無い録画では ffmpeg が使わない)。
    作り方は encode_tries の順(GPU が失敗したら書きかけを消して libx264 で 1 回だけ)。止めた・取り消しはやり直さない。
    -> 最後の (終了コード, エラーの行, 止めた理由)。検証(verify)と置き換えは呼ぶ側"""
    lst = concat_list(paths, os.path.join(os.path.dirname(paths[0]), "parts.txt")) if len(paths) > 1 else None
    res = None
    for _how, enc in encode_tries(ffmpeg):
        if res is not None:
            fsio.unlink_quiet(out)
        res = run_with_legacy(lambda enc: run(section_cmd(ffmpeg, paths, ss, dur, out, enc, lst)), enc + (["-af", afilter] if afilter else []), out)
        if res[0] == 0 or res[2] is not None:
            break
    return res


def verify(path, dur, tol=DURATION_TOL, ffprobe=None, what="作り直した動画", ref="元", got="作り直し", error=NormalizeError):
    """作り直した path が 30/1 の固定で、長さが dur と ±tol 秒か確かめる。-> probe の結果。違えば error(文)を上げる。
    dur が None なら長さは見ない。文は「<what>が 30fps になっていません(…)」「<what>の長さが<ref>と違います(<ref> … 秒 / <got> … 秒)」"""
    info = probe(path, ffprobe)
    if not is_30fps(info):
        raise error("%sが 30fps になっていません(%s)" % (what, (info or {}).get("r_frame_rate") or "読めません"))
    if dur is not None and (info.get("duration") is None or abs(info["duration"] - dur) > tol):
        raise error("%sの長さが%sと違います(%s %.2f 秒 / %s %s 秒)"
                    % (what, ref, ref, dur, got, "不明" if info.get("duration") is None else "%.2f" % info["duration"]))
    return info


def normalize(src, dst, cancelled=None, on_progress=None, priority_low=True, preset=PRESET, ffmpeg=None, ffprobe=None,
              popen=None, idle_sec=IDLE_SEC, gpu_runner=None):
    """src を 30fps(H.264・yuv420p・AAC)に作り直して dst に置く。dst と同じフォルダの一時の名前に書き、
    検証(probe で 30/1・長さが元と ±DURATION_TOL 秒)が済んでから dst へ置き換える(src と dst が同じでもよい = 置き換え)。
    失敗・取り消しでは一時ファイルを消して NormalizeError(取り消しは Cancelled)。成功したら dst の probe の結果を返す。
    - cancelled(): 真になったら ffmpeg を止める(0.3 秒ごとに見る)
    - on_progress(0〜1): ffmpeg の -progress の out_time から
    - priority_low: Windows では「通常より下」の優先度で動かす(画面の操作・ほかのツールが先に CPU を取れる)
    - popen: 子プロセスの起動を差し替える(呼ぶ側が終了の流れで止めるために覚えたいとき。既定 subprocess.Popen)
    - ffmpeg が 5.1 より古く -fps_mode を知らなければ、-vsync cfr に替えて1回だけやり直す(legacy_args)
    - 映像が条件どおりなら映像はコピー(音声だけ)・GPU が使えれば GPU・失敗したら次の作り方へ(最後は libx264)。
      戻り値の "how" = 作った作り方・"failed" = 失敗した作り方と理由。gpu_runner は gpu_encoder の確かめの差し替え(テスト用)
    SLOTS(ytt.jobs)は呼ぶ側が持つ。"""
    cancelled = cancelled or (lambda: False)
    ff = ffmpeg or tools.find_tool("ffmpeg")
    if not ff:
        raise NormalizeError("ffmpeg が見つかりません")
    info = probe(src, ffprobe)
    if not info:
        raise NormalizeError("動画を調べられませんでした(ffprobe が無いか、読めないファイルです)")
    if not info["has_video"]:
        raise NormalizeError("映像がありません")
    dur = info.get("duration") or 0.0
    tmp = temp_path(dst)
    head = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error"]
    inp = ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    flags = tools.no_window_flags(new_group=True, priority="low" if priority_low else None)
    # 作り方の順(前が失敗したら次で 1 回だけ。音声だけ・GPU は速い道、最後の libx264 が今までの作り方)。
    # GPU の作り方は読み込みも GPU の回(pre = decode_args)を先に(失敗の文には +cuda などの印。how はそのまま)
    tries = [("音声だけ作り直し", [], list(AUDIO_ONLY_ARGS))] if video_ok(info) else []
    tries += [("%s(%s)" % ("CPU" if c == CPU else "GPU", c), pre, a) for c, pre, a in decode_tries(encode_tries(ff, preset, runner=gpu_runner))]

    def run(pre, args):
        return run_ffmpeg(head + pre + inp + args + ["-progress", "pipe:1", "-nostats", tmp], flags, popen, cancelled, idle_sec, on_progress, dur)

    failed = []
    try:
        for i, (how, pre, enc) in enumerate(tries):
            last = i == len(tries) - 1
            tag = how + ("+" + hwdec_name(pre) if pre else "")
            code, tail, why = run_with_legacy(lambda args: run(pre, args), enc, tmp, cancelled)   # ffmpeg 5.1 より古ければ -vsync cfr で1回だけやり直す
            if why == "cancel" or cancelled():
                raise Cancelled("取り消しました")
            if why == "idle":
                raise NormalizeError("ffmpeg が %d 秒間なにも出力しなかったので止めました" % idle_sec)
            if code != 0:
                msg = " / ".join(tail[-3:]) or "終了コード %s" % code
                if last:
                    raise NormalizeError("作り直しに失敗しました: %s" % msg)
                failed.append("%s: %s" % (tag, msg[:120]))
                fsio.unlink_quiet(tmp)
                continue
            try:
                out = verify(tmp, dur or None, DURATION_TOL, ffprobe)   # 元の長さが分からなければ長さは見ない
            except NormalizeError as e:
                if last:
                    raise
                failed.append("%s: %s" % (tag, str(e)[:120]))
                fsio.unlink_quiet(tmp)
                continue
            fsio.replace_retry(tmp, dst)
            break
    except BaseException:
        fsio.unlink_quiet(tmp)
        raise
    _report(on_progress, 1.0)
    return dict(out, path=dst, how=how, hwdec=hwdec_name(pre), failed=failed)
