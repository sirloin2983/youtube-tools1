"""素材を 30fps にそろえる(Q1。plan/line-bc-master-plan.md。2026-10-04 ユーザー決定)。

決まり: **H.264・8bit・yuv420p・30/1 の固定(CFR)・AAC** ならそのまま使う(作り直さない)。違えば ffmpeg(libx264)で作り直す。
画質の設定はスタジオの書き出しと同じ(crf 18。ENC_ARGS を1か所にして、スタジオの exporter もこれを使う)。GPU(AMF)は測ってから。

- 時刻は秒のまま保たれる(ずらさない): fps フィルタは各コマの表示時刻をそのまま 1/30 秒の格子に当てはめるだけなので、
  文字起こし・マークの時刻(秒)は作り直したあともそのまま使える。
- 60fps → 30fps は1コマおきに落とす。29.97fps → 30fps はコマを落とさず、約 33 秒に1コマを複製して揃う(目立たない)。
- VFR(コマの間隔が一定でない録画)も、fps フィルタ + -fps_mode cfr で一定の間隔になる。
- 重い処理の同時実行の上限(ytt_core.jobs.SLOTS)は**呼ぶ側が持つ**(このモジュールは SLOTS を取らない。呼ぶ側の処理の単位で順番を待つため)。

使い方:
    info = normalize.probe(src)                 # ffprobe が無ければ None
    need, why = normalize.needs_normalize(info)
    if need:
        with jobs.SLOTS.slot("intake", name, cancelled=...) as ok:
            if ok:
                normalize.normalize(src, dst, cancelled=..., on_progress=...)
"""
import json
import os
import re
import subprocess
import threading
import time
import uuid
from fractions import Fraction

from . import fsio, tools

TARGET_FPS = 30
TARGET = "30/1"
AVG_TOL = 0.01            # avg_frame_rate は 29.99〜30.01 を許す(長さの端数で 30/1 ちょうどにならないことがある)
DURATION_TOL = 0.5        # 作り直したあとの長さが元と ±この秒数なら良しとする
PRESET = "veryfast"       # スタジオの「精密」と同じ
FAST_PRESET = "ultrafast" # スタジオの「高速」(コピーでは fps を変えられないので、速い設定で作り直す)
CRF = "18"
IDLE_SEC = 600            # ffmpeg がこの秒数まったく出力しなければ止める
PART = ".normalizing-"    # 作り直しの途中の名前(<名前>.normalizing-xxxxxxxx.mp4。検証が済んでから本当の名前へ)


class NormalizeError(Exception):
    pass


class Cancelled(NormalizeError):
    pass


def fps_filter(vf=None):
    """-vf の中身。既に映像のフィルタ(例 scale=…)があれば、そのあとに fps=30 をつなぐ"""
    f = "fps=%d" % TARGET_FPS
    return "%s,%s" % (vf, f) if vf else f


def encode_args(preset=PRESET, vf=None, in_graph=False):
    """作り直しの ffmpeg の出力側の引数(入力・-progress・出力のパスは呼ぶ側)。
    in_graph=True: -filter_complex の中で fps=30 をかける呼び出し側用(-vf と -filter_complex は同じ出力に一緒に使えないため -vf を付けない)。
    -r 30 は付けない(fps フィルタで足りる。両方付けると二重に丸める)。音声は AAC 192k(サンプリング周波数は元のまま。スタジオの書き出しと同じ)"""
    args = [] if in_graph else ["-vf", fps_filter(vf)]
    return args + ["-fps_mode", "cfr", "-c:v", "libx264", "-preset", preset, "-crf", CRF, "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]


ENC_ARGS = encode_args()                     # スタジオの「精密」
ENC_FAST_ARGS = encode_args(FAST_PRESET)     # スタジオの「高速」


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


def _float(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _bit_depth(stream):
    try:
        n = int(stream.get("bits_per_raw_sample") or 0)
    except (TypeError, ValueError):
        n = 0
    if n:
        return n
    m = re.search(r"p(\d{2})(?:le|be)$", str(stream.get("pix_fmt") or ""))   # yuv420p10le など
    return int(m.group(1)) if m else (8 if stream.get("pix_fmt") else None)


def _no_window():
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def probe(path, ffprobe=None, timeout=60):
    """ffprobe(JSON)で調べる。ffprobe が無い・読めないときは None。
    -> {"path", "duration", "width", "height", "vcodec", "pix_fmt", "bit_depth", "r_frame_rate", "avg_frame_rate",
        "fps"(r_frame_rate の値), "avg_fps", "cfr"(推定: r と avg がほぼ同じ), "acodec"(音声が無ければ None),
        "sample_rate", "has_video", "has_audio"}"""
    fp = ffprobe or tools.find_tool("ffprobe", "YTT_FFPROBE")
    if not fp:
        return None
    cmd = [fp, "-v", "error", "-of", "json", "-show_entries",
           "format=duration:stream=index,codec_type,codec_name,pix_fmt,bits_per_raw_sample,width,height,r_frame_rate,avg_frame_rate,sample_rate,duration",
           path]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                           creationflags=_no_window())
        data = json.loads(r.stdout.decode("utf-8", "replace") or "null") if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = _float((data.get("format") or {}).get("duration"))
    if dur is None and v:
        dur = _float(v.get("duration"))
    info = {"path": path, "duration": dur, "has_video": v is not None, "has_audio": a is not None,
            "vcodec": None, "pix_fmt": None, "bit_depth": None, "width": None, "height": None,
            "r_frame_rate": None, "avg_frame_rate": None, "fps": None, "avg_fps": None, "cfr": None,
            "acodec": (a or {}).get("codec_name"), "sample_rate": int(_float((a or {}).get("sample_rate")) or 0) or None}
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


def _unlink(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def _kill(proc):
    if proc.poll() is not None:
        return
    try:
        proc.kill()
    except OSError:
        pass


def normalize(src, dst, cancelled=None, on_progress=None, priority_low=True, preset=PRESET, ffmpeg=None, ffprobe=None,
              popen=None, idle_sec=IDLE_SEC):
    """src を 30fps(H.264・yuv420p・AAC)に作り直して dst に置く。dst と同じフォルダの一時の名前に書き、
    検証(probe で 30/1・長さが元と ±DURATION_TOL 秒)が済んでから dst へ置き換える(src と dst が同じでもよい = 置き換え)。
    失敗・取り消しでは一時ファイルを消して NormalizeError(取り消しは Cancelled)。成功したら dst の probe の結果を返す。
    - cancelled(): 真になったら ffmpeg を止める(0.3 秒ごとに見る)
    - on_progress(0〜1): ffmpeg の -progress の out_time から
    - priority_low: Windows では「通常より下」の優先度で動かす(画面の操作・ほかのツールが先に CPU を取れる)
    - popen: 子プロセスの起動を差し替える(呼ぶ側が終了の流れで止めるために覚えたいとき。既定 subprocess.Popen)
    - ffmpeg が 5.1 より古く -fps_mode を知らなければ、-vsync cfr に替えて1回だけやり直す(legacy_args)
    SLOTS(ytt_core.jobs)は呼ぶ側が持つ。"""
    cancelled = cancelled or (lambda: False)
    ff = ffmpeg or tools.find_tool("ffmpeg", "YTT_FFMPEG")
    if not ff:
        raise NormalizeError("ffmpeg が見つかりません")
    info = probe(src, ffprobe)
    if not info:
        raise NormalizeError("動画を調べられませんでした(ffprobe が無いか、読めないファイルです)")
    if not info["has_video"]:
        raise NormalizeError("映像がありません")
    dur = info.get("duration") or 0.0
    tmp = temp_path(dst)
    base = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    enc = encode_args(preset)
    flags = _no_window()
    if os.name == "nt" and priority_low:
        flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

    def run(args):
        """ffmpeg を1回動かす。-> (終了コード, エラーの行の最後の 20 行, 止めた理由 None|"cancel"|"idle")"""
        tail = []
        try:
            proc = (popen or subprocess.Popen)(base + args + ["-progress", "pipe:1", "-nostats", tmp], stdin=subprocess.DEVNULL,
                                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as e:
            raise NormalizeError("ffmpeg を起動できませんでした: %s" % e)
        state = {"last": time.time(), "why": None}
        done = threading.Event()

        def watchdog():
            while not done.wait(0.3):
                if cancelled():
                    state["why"] = "cancel"
                elif time.time() - state["last"] > idle_sec:
                    state["why"] = "idle"
                else:
                    continue
                _kill(proc)
                return
        threading.Thread(target=watchdog, daemon=True).start()
        try:
            for raw in proc.stdout:
                state["last"] = time.time()
                line = raw.decode("utf-8", "replace").strip()
                m = re.match(r"^out_time_(?:us|ms)=(\d+)$", line)
                if m:
                    if on_progress and dur > 0:
                        try:
                            on_progress(min(0.99, int(m.group(1)) / 1e6 / dur))
                        except Exception:
                            pass
                    continue
                if line and "=" not in line[:20]:   # -progress の key=value 以外(= ffmpeg のエラー)
                    tail = (tail + [line])[-20:]
            proc.wait()
        finally:
            done.set()
            _kill(proc)
            try:
                proc.stdout.close()
            except OSError:
                pass
        return proc.returncode, tail, state["why"]

    try:
        code, tail, why = run(enc)
        if code != 0 and why is None and not cancelled() and is_fps_mode_error("\n".join(tail)):
            # ffmpeg 5.1 より古い: -fps_mode を知らない → -vsync cfr で1回だけやり直す(書きかけは消してから)
            _unlink(tmp)
            code, tail, why = run(legacy_args(enc))
        if why == "cancel" or cancelled():
            raise Cancelled("取り消しました")
        if why == "idle":
            raise NormalizeError("ffmpeg が %d 秒間なにも出力しなかったので止めました" % idle_sec)
        if code != 0:
            raise NormalizeError("作り直しに失敗しました: %s" % (" / ".join(tail[-3:]) or "終了コード %s" % code))
        out = probe(tmp, ffprobe)
        if not is_30fps(out):
            raise NormalizeError("作り直した動画が 30fps になっていません(%s)" % ((out or {}).get("r_frame_rate") or "読めません"))
        if dur and (out.get("duration") is None or abs(out["duration"] - dur) > DURATION_TOL):
            raise NormalizeError("作り直した動画の長さが元と違います(元 %.2f 秒 / 作り直し %s 秒)"
                                 % (dur, "不明" if out.get("duration") is None else "%.2f" % out["duration"]))
        fsio.replace_retry(tmp, dst)
    except BaseException:
        _unlink(tmp)
        raise
    if on_progress:
        try:
            on_progress(1.0)
        except Exception:
            pass
    return dict(out, path=dst)
