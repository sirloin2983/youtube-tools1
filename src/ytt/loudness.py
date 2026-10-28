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
# 届ける動画の音の符号化(10-23。決定は保管庫 plan/decisions.md): リミッターの出口はちょうど -3.0 dBTP なのに、AAC 192k は素材によって 3 dB 以上ふくらみ
# +0.7 dBTP まで出た(16 例)。256k では全部 -2.2 以下・LUFS と LRA は同じ。PACK_TP_SAFE = True: 256k で書く。False = 今までどおり 192k
PACK_TP_SAFE = True
PACK_ABITRATE = "256k"
# 測り方(10-23。決定は保管庫 plan/decisions.md): loudnorm は中で 192kHz に上げてから測るので 3 分の切り抜きで 9〜12 秒かかる。
# FAST_MEASURE = True: ebur128(同じ BS.1770・48kHz のまま。トゥルーピークは 4 倍で見る)で測る = 約 1 秒。値の差は I で 0.1 LU 以内・上げ下げの量で 0.04 dB 以内
# (実データ 3 本)。ebur128 の要約は小数 1 桁なので、ピークは丸めの分(PEAK_ROUND)を足して高めに見る(上限を超えない側)。False = 今までどおり loudnorm
FAST_MEASURE = True
PEAK_ROUND = 0.05
SILENT_LUFS = -70.0     # ebur128 は無音・短すぎる音を -70.0 と出す = 測れない
_FIELD = {k: re.compile(r'"%s"\s*:\s*"([^"]+)"' % k) for k in ("input_i", "input_tp")}   # loudnorm の JSON の値(文字列)
_EBUR = {"i": re.compile(r"\bI:\s+(-?[\d.]+|-?inf) LUFS"), "tp": re.compile(r"\bPeak:\s+(-?[\d.]+|-?inf) dBFS")}   # ebur128 の要約


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


def measure_filter():
    """測るだけのフィルタ(FAST_MEASURE = ebur128・違えば loudnorm)。出力は parse で読む"""
    return "ebur128=peak=true:framelog=quiet" if FAST_MEASURE else "loudnorm=print_format=json"


def parse(text):
    """測った出力(loudnorm の JSON か ebur128 の要約)-> (統合ラウドネス LUFS, トゥルーピーク dBTP)。無音・測れないときは (None, None)"""
    i, tp = _field(text, "input_i"), _field(text, "input_tp")
    if i is None:
        i, tp = _last(text, "i"), _last(text, "tp")
        if i is not None and i <= SILENT_LUFS:
            return None, None
        tp = tp + PEAK_ROUND if tp is not None else None
    if i is None or not (-70.0 <= i <= 10.0) or tp is None or not math.isfinite(tp):
        return None, None
    return i, tp


def _field(text, key):
    m = _FIELD[key].search(text or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def _last(text, key):
    found = _EBUR[key].findall(text or "")
    try:
        return float(found[-1]) if found else None
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
    """パックの結果の形: result + PACK_LEVEL ならリミッターの印 "limitDb"・PACK_TP_SAFE なら音の符号化の印 "aac"(どうそろえたかの記録)"""
    return dict(result(target, i, g), **({"limitDb": LIMIT_DB} if PACK_LEVEL else {}), **({"aac": PACK_ABITRATE} if PACK_TP_SAFE else {}))


def pack_aac():
    """パックの届ける動画(写し)の AAC のビットレート(PACK_TP_SAFE なら PACK_ABITRATE・違えば 192k)"""
    return PACK_ABITRATE if PACK_TP_SAFE else "192k"


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


def measure_args(ff, path, span=None):
    """測るだけ(書き換えない)の引数(measure_filter)。出力(標準エラー)を parse に渡す。
    span = (始まり, 終わり)(動画の中の秒)なら、その区間だけ測る(余白つきの切り抜きは候補の範囲だけで測る = 余白の音に引かれない)"""
    cut = ["-ss", "%.3f" % span[0], "-t", "%.3f" % (span[1] - span[0])] if span else []
    return [ff, "-hide_banner", "-nostdin"] + cut + ["-i", path, "-vn", "-af", measure_filter(), "-f", "null", "-"] + PROGRESS


def reencode_args(ff, path, out, afilter, first_streams=False):
    """映像は無劣化(-c:v copy)・音声だけ afilter で作り直す引数。
    first_streams: 映像と音声の最初の 1 本だけを残し、字幕・データは落とす(ライブの録画の作り直し。エラーだけ出す)"""
    head = [ff, "-hide_banner", "-nostdin", "-y"] + (["-v", "error"] if first_streams else []) + ["-i", path]
    pick = ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"] if first_streams else []
    return head + pick + ["-c:v", "copy", "-af", afilter, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"] + PROGRESS + [out]
