"""聞こえ方の音量(ラウドネス。LUFS)をそろえる決まりの1か所(スタジオの書き出し・パック作りが共通で使う。2026-09-29)。

測るのは ffmpeg の loudnorm(print_format=json)。ここは「どの値を選べるか」「測った結果の読み方」「どれだけ上げ下げするか」だけを持ち、
ffmpeg を動かすのは各ツール(スタジオ exporter.py の _pump・cut2resolve の _ffmpeg_run)。
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
