# -*- coding: utf-8 -*-
"""① 書き出しのあとの自動の点検(10-23。資料の git:before-1028-cleanup:plan/人の作業なしの候補-1023.md の 1)。書き出した切り抜き 1 本を測り、気になる所を返すだけ(出力は止めない・消さない)。
見る物(どれも ffmpeg で読むだけ。黒いコマはキーフレームだけ読む = 軽い):
  length   長さが期待と OC_LEN_TOL(秒か割合の大きい方)より違う
  silent   音が無い・ほとんど無音(平均 OC_SILENT_DB 未満)
  clip     音が割れている恐れ(ピークが OC_PEAK_DB 以上)
  black    黒いコマが OC_BLACK_SEC 秒以上続く(頭・末なら短くても)
声の途中の切れ(頭・末の OC_EDGE_SEC 秒の音量 ÷ この切り抜きの声の大きさ = 50 ミリ秒ごとの音量の上位 1 割)は値を edge に残すだけで知らせない:
  書き出しは余白つき(端はパックで決まる)・BGM や環境音でも上がるので、最近の本物 25 本で 13 本に出た = 知らせにならない(しきい値を決める材料として残す)
字幕のはみ出しはここでは見ない: 書き出しの動画に字幕は無く、パックの Text+ は 1 段 8 字(縦)で改行し、どの段も 10 字以下にそろえる(pack/resolve_textplus.wrap_caption)= 行の字数と上限(maxChars 縦 16)を比べても、はみ出しの知らせにならない。
結果は {"issues": [{"kind", "text"}], "edge": {"head", "tail"}(頭・末の音量の比), "sec": 測った秒}。.clip.json の export.check に残し、② の書き出しの段の文に数を出す。スイッチ OUTCHECK
"""
import array
import math
import re
import time

from ytt import tools as _tools

OUTCHECK = True           # False = 点検しない(前のまま)
OC_LEN_TOL = (1.0, 0.03)  # 長さの許す差(秒・割合。大きい方)
OC_SILENT_DB = -50.0      # 平均の音量がこれ未満 = ほとんど無音
OC_PEAK_DB = -0.1         # ピークがこれ以上 = 割れている恐れ
OC_BLACK_SEC = 1.0        # 途中の黒いコマがこれ以上続けば知らせる(頭・末は 0.5 秒)
OC_EDGE_SEC = 0.15        # 頭・末の音を見る長さ
OC_RATE = 8000            # 音を読むときの標本化(声の大きさを見るだけ)
OC_TIMEOUT = 120          # 1 本の点検の上限(秒)
_BLACK = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")
_MEAN = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf) dB")
_MAX = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")


def _db(m):
    return None if not m else (-math.inf if m.group(1) == "-inf" else float(m.group(1)))


def black_spans(err_text):
    """ffmpeg の blackdetect の行 -> [(始め, 終わり)]"""
    return [(float(a), float(b)) for a, b in _BLACK.findall(err_text)]


def edge_ratio(samples, rate=OC_RATE, edge=OC_EDGE_SEC):
    """音(-1〜1 の並び)の頭・末の音量 ÷ 声の大きさ(50 ミリ秒ごとの RMS の上位 1 割)-> (頭, 末)か None(短い・声がほとんど無い = -45 dB 未満)"""
    hop = max(1, int(rate * 0.05))
    rms = [math.sqrt(sum(x * x for x in samples[i:i + hop]) / hop) for i in range(0, len(samples) - hop + 1, hop)]
    if len(rms) < 6:
        return None
    loud = sorted(rms)[int(len(rms) * 0.9)]
    if loud < 10 ** (-45 / 20):
        return None
    n = max(1, int(edge / 0.05))
    return round(sum(rms[:n]) / n / loud, 3), round(sum(rms[-n:]) / n / loud, 3)


def judge(dur, expected, has_audio, mean_db, max_db, blacks):
    """測った値 -> 気になる所 [{"kind", "text"}](純粋)。blacks = [(始め, 終わり)]"""
    out = []
    if expected and dur is not None:
        tol = max(OC_LEN_TOL[0], OC_LEN_TOL[1] * expected)
        if abs(dur - expected) > tol:
            out.append({"kind": "length", "text": "長さが %.1f 秒(期待 %.1f 秒)" % (dur, expected)})
    if not has_audio:
        out.append({"kind": "silent", "text": "音がありません"})
    elif mean_db is not None and mean_db < OC_SILENT_DB:
        out.append({"kind": "silent", "text": "音がほとんど無音です(平均 %s dB)" % ("-∞" if mean_db == -math.inf else "%.0f" % mean_db)})
    elif max_db is not None and max_db >= OC_PEAK_DB:
        out.append({"kind": "clip", "text": "音が割れている恐れがあります(ピーク %.1f dB)" % max_db})
    for a, b in blacks:
        edge = a <= 0.1 or (dur is not None and b >= dur - 0.1)
        if b - a >= (0.5 if edge else OC_BLACK_SEC):
            out.append({"kind": "black", "text": "黒いコマが %.1f〜%.1f 秒に %.1f 秒" % (a, b, b - a)})
            break
    return out


def check(path, expected=None, ffmpeg=None, dur=None, has_audio=True):
    """書き出した切り抜き 1 本を点検する -> {"issues", "sec"} か None(OUTCHECK オフ・ffmpeg が無い・読めない = 点検しない。出力は止めない)"""
    if not OUTCHECK:
        return None
    t0 = time.monotonic()
    ffmpeg = ffmpeg or _tools.find_tool("ffmpeg")
    if not ffmpeg:
        return None
    try:
        v = _tools.run([ffmpeg, "-hide_banner", "-nostats", "-skip_frame", "nokey", "-i", path, "-an", "-vf", "blackdetect=d=0.1:pix_th=0.10",
                        "-f", "null", "-"], timeout=OC_TIMEOUT, stdout=False)
        blacks = black_spans(v.err.decode("utf-8", "replace"))
        mean_db = max_db = None
        edge = None
        if has_audio:
            a = _tools.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "volumedetect", "-ac", "1", "-ar", str(OC_RATE),
                            "-f", "s16le", "-"], timeout=OC_TIMEOUT)
            err = a.err.decode("utf-8", "replace")
            mean_db, max_db = _db(_MEAN.search(err)), _db(_MAX.search(err))
            pcm = array.array("h")
            pcm.frombytes(a.out[:len(a.out) // 2 * 2])
            if mean_db is None and not pcm:   # 音の流れが無い(読めなかった)
                has_audio = False
            edge = edge_ratio([x / 32768.0 for x in pcm]) if pcm else None
            if dur is None and pcm:
                dur = len(pcm) / OC_RATE
    except OSError:
        return None
    out = {"issues": judge(dur, expected, has_audio, mean_db, max_db, blacks), "sec": round(time.monotonic() - t0, 2)}
    if edge:
        out["edge"] = {"head": edge[0], "tail": edge[1]}
    return out

