"""聞こえ方の音量(ラウドネス。LUFS)をそろえる決まりの1か所(スタジオの書き出し・パック作りが共通で使う)。

測るのは ffmpeg の loudnorm(print_format=json)。ここは「どの値を選べるか」「測った結果の読み方」「どれだけ上げ下げするか」だけを持ち、
ffmpeg を動かすのは各ツール(スタジオ exporter.py の _pump・ライブの書き出し・cut2resolve の _ffmpeg_run)。引数の形(測る・音声だけ作り直す)はここ(OPT2)。
YouTube は再生時に約 -14 LUFS に下げるので、それを目安にする。
"""
import math
import re

CHOICES = (-11.0, -14.0, -16.0, -18.0)
DEFAULT = -14.0
TRUE_PEAK_CEIL = -1.0   # 上げたときに音が割れないよう、ピーク(トゥルーピーク)をこれより上げない(dBTP)
MAX_GAIN_DB = 20.0      # 静かすぎる音を持ち上げすぎない(雑音まで大きくなる)
MIN_GAIN_DB = 0.1       # これより小さい調整はしない(音声を作り直すだけ損)
MAX_SPANS = 400         # 区間ごとに測るときの区間の数の上限(多すぎるときは全体で測る)
# パックの届ける動画の音(10-23 ユーザー「音の大きさがバラバラ」。決定は保管庫 plan/decisions.md):
# 配信の音はもとのピークが高く、ピークの手前で止める利得(gain)では静かな切り抜きも下げてしまい、届いた物が -15〜-19 LUFS・ピーク +2 dBTP とばらけていた。
# PACK_LEVEL = True: 目標まで上げ(MAX_GAIN_DB まで)、ピークはリミッター(LIMIT_DB)で止める。圧縮はしない(抑揚は残す・Fable の判断)。
# まとめて実行のパックは「そろえない(0)」でも DEFAULT にそろえる(flow/spec.pack_output)。False = 今までどおり(ピークの手前で止める利得・音量 %)
PACK_LEVEL = True
LIMIT_DB = -3.0         # リミッターの上限(dBFS)。AAC 192k で書き戻すとピークが 1.5〜2 dB ふくらむ(-2.0 では -0.2 dBTP の物があった。-3.0 で -2.2 以下)
_FIELD = {k: re.compile(r'"%s"\s*:\s*"([^"]+)"' % k) for k in ("input_i", "input_tp")}   # loudnorm の JSON の値(文字列)


def check_target(v):
    """画面・API から来た目標 -> float(CHOICES のどれか)か None(そろえない)。形が違えば ValueError"""
    if v in (None, "", 0, "0", False):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError("音量のそろえ方(LUFS)の値が正しくありません")
    if isinstance(v, bool) or f not in CHOICES:
        raise ValueError("音量のそろえ方(LUFS)は %s のどれかです" % " / ".join("%g" % x for x in CHOICES))
    return f


def check_volume(v):
    """音量(%。元の音量 = 100)-> int(1〜200)か None(変えない = 100・省略)。形が違えば ValueError(スタジオの書き出しの「音量 %」と同じ範囲)"""
    if v in (None, "", 100, "100"):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError("音量(%)の値が正しくありません")
    if isinstance(v, bool) or n != float(v) or not 1 <= n <= 200:
        raise ValueError("音量(%)は 1〜200 の整数で指定してください")
    return None if n == 100 else n


def pct_to_db(pct):
    return round(20 * math.log10(pct / 100.0), 2)


def parse(text):
    """loudnorm の出力 -> (統合ラウドネス LUFS, トゥルーピーク dBTP)。無音・測れないときは (None, None)"""
    i, tp = _field(text, "input_i"), _field(text, "input_tp")
    if i is None or not (-70.0 <= i <= 10.0) or tp is None or not math.isfinite(tp):
        return None, None
    return i, tp


def _field(text, key):
    m = _FIELD[key].search(text or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def gain(target, i, tp, *more_tps):
    """目標に合わせる量(dB)。ピーク(tp と more_tps のどれも)が TRUE_PEAK_CEIL を超えない・MAX_GAIN_DB を超えない範囲まで。小数2桁"""
    g = min([target - i, TRUE_PEAK_CEIL - tp, MAX_GAIN_DB] + [TRUE_PEAK_CEIL - x for x in more_tps if x is not None])
    return round(g, 2)


def pack_gain(target, i, tp):
    """パックの届ける動画を目標に合わせる量(dB)。PACK_LEVEL ならピークはリミッターで止めるので MAX_GAIN_DB だけで抑える・違えば gain と同じ"""
    return round(min(target - i, MAX_GAIN_DB), 2) if PACK_LEVEL else gain(target, i, tp)


def select_filter(spans):
    """区間 [(開始秒, 終了秒), …] だけの音を測る aselect(区間が無い・多すぎるときは '' = 全体)"""
    spans = [(a, b) for a, b in spans or () if b > a]
    if not spans or len(spans) > MAX_SPANS:
        return ""
    expr = "+".join("between(t,%.3f,%.3f)" % (a, b) for a, b in spans)
    return "aselect='%s',asetpts=N/SR/TB" % expr


def result(target, i, g):
    """結果の形(画面に出す): {"target", "measured", "gainDb"}"""
    return {"target": target, "measured": round(i, 1), "gainDb": g}


def pack_result(target, i, g):
    """パックの結果の形: result + PACK_LEVEL ならリミッターの印 "limitDb"(どうそろえたかの記録)"""
    return dict(result(target, i, g), **({"limitDb": LIMIT_DB} if PACK_LEVEL else {}))


# ---- ffmpeg の引数(OPT2: 音量・ラウドネスの引数の 1 か所。動かすのは各ツール = スタジオの exporter・ライブの書き出し)
PROGRESS = ["-progress", "pipe:1", "-nostats"]


def volume_filter(pct):
    """音量(%)の -af"""
    return "volume=%.3f" % (pct / 100.0)


def gain_filter(db):
    """上げ下げ(dB)の -af"""
    return "volume=%.2fdB" % db


def pack_filter(db):
    """パックの届ける動画の音にかける -af(上げ下げ + PACK_LEVEL ならピークを LIMIT_DB で止めるリミッター。自動の音量の上げ下げ level は切る)"""
    if not PACK_LEVEL:
        return gain_filter(db)
    return gain_filter(db) + ",alimiter=limit=%.4f:attack=5:release=100:level=false:asc=1" % (10 ** (LIMIT_DB / 20))


def measure_args(ff, path):
    """loudnorm で測るだけ(書き換えない)の引数。出力(標準エラー)を parse に渡す"""
    return [ff, "-hide_banner", "-nostdin", "-i", path, "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"] + PROGRESS


def reencode_args(ff, path, out, afilter, first_streams=False):
    """映像は無劣化(-c:v copy)・音声だけ afilter で作り直す引数。
    first_streams: 映像と音声の最初の 1 本だけを残し、字幕・データは落とす(ライブの録画の作り直し。エラーだけ出す)"""
    head = [ff, "-hide_banner", "-nostdin", "-y"] + (["-v", "error"] if first_streams else []) + ["-i", path]
    pick = ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"] if first_streams else []
    return head + pick + ["-c:v", "copy", "-af", afilter, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"] + PROGRESS + [out]
