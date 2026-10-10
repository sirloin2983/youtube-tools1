"""1 秒ごとの音量(RMS, dB)を、ffmpeg 1 回のデコードで全帯域と高音域(2kHz 超)の 2 系列に測る決まり(OPT1。2026-10-11)。
スタジオのアーカイブの解析(analyze.audio_levels)と配信中の検出(live_excite_worker.measure_levels)が同じ物を読む。
動かし方(取り消し・時間の上限・進み具合)は呼ぶ側が持つ。

- フィルター: aresample=16000 → asplit で 2 つ → 全帯域 / highpass=f=2000 → asetnsamples=n=16000:p=0・astats・ametadata
  (1 秒 = 16000 サンプルごとの RMS。以前のスタジオは同じフィルターを 2 回のデコードで動かしていた = 値は同じ)
- 結果は ffmpeg の作業フォルダ(cwd)の full.txt・band.txt(2 つの系列の行が混ざらない)。cwd を渡して ffmpeg を動かすこと
- 値: 読めない・NaN・無限大・FLOOR 未満は FLOOR(-90)、LEVEL_MAX(20 dB。ふつうは 0 以下)より大きい値は切る(壊れた値で式が振り切れない)
"""
import math
import os

from ytt import fsio

FLOOR = -90.0
LEVEL_MAX = 20.0
HIGHPASS = 2000            # 高音域(笑い声・叫び)の下の端(Hz)
LEVEL_KEY = "lavfi.astats.Overall.RMS_level="
STATS = "asetnsamples=n=16000:p=0,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level"
OUTS = ("full.txt", "band.txt")


def args(path):
    """ffmpeg に渡す入力から出力までの引数(-i から。頭の ffmpeg・-hide_banner などと、-progress は呼ぶ側)。path は絶対パスにして渡す(cwd が作業フォルダのため)"""
    fc = "[0:a]aresample=16000,asplit=2[a][b];[a]%s:file=%s[oa];[b]highpass=f=%d,%s:file=%s[ob]" % (STATS, OUTS[0], HIGHPASS, STATS, OUTS[1])
    return ["-protocol_whitelist", "file,pipe", "-i", os.path.abspath(path), "-filter_complex", fc,
            "-map", "[oa]", "-f", "null", "-", "-map", "[ob]", "-f", "null", "-"]


def clear(wdir):
    """前の結果のファイルを消す(測る前に呼ぶ)"""
    for n in OUTS:
        fsio.unlink_quiet(os.path.join(wdir, n))


def level(v):
    """ffmpeg の RMS の値(dB の文字)-> FLOOR〜LEVEL_MAX"""
    try:
        x = float(v)
    except ValueError:
        return FLOOR
    if not math.isfinite(x) or x < FLOOR:
        return FLOOR
    return min(LEVEL_MAX, x)


def read(path):
    """ametadata の出力ファイル -> 値のリスト(読めなければ [])"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [level(line.split("=", 1)[1]) for line in f if line.startswith(LEVEL_KEY)]
    except OSError:
        return []


def collect(wdir):
    """測り終えた wdir の 2 つのファイルを読んで消す -> (full, band)。band は full の長さにそろえる(足りなければ最後の値か FLOOR で埋める)。
    full が空なら ([], [])"""
    full, band = read(os.path.join(wdir, OUTS[0])), read(os.path.join(wdir, OUTS[1]))
    clear(wdir)
    if not full:
        return [], []
    return full, (band + [band[-1] if band else FLOOR] * len(full))[:len(full)]
