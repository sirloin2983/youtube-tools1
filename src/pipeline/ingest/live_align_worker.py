# -*- coding: utf-8 -*-
"""音の照合(線 D の P4。plan/line-d-live-clipping.md の 0-9)の子プロセス。**入口のプロセスから import しない**
(入口では numpy を読み込まない決まり。src/pipeline/ingest/live_archive.py が `python live_align_worker.py <ref.wav> <window.wav>` で動かす)。

    py -3.10 src/pipeline/ingest/live_align_worker.py <ref.wav> <window.wav>
    (旧い場所 src/home/live_align_worker.py は起動中の古い入口のための runpy の転送。RS5 で消す)

ref(速報版の音)が window(アーカイブの窓の音)のどこから始まるかを、正規化した相互相関の山で求める。
入力は 8kHz・モノラル・16bit の WAV(wave モジュールで読む。ffmpeg で作る側が決まった形にそろえる)。
標準出力に JSON を1行:
  {"ok": true, "offset": window の中で ref が始まる秒, "score": 正規化した相関の山(0〜1), "ratio": 1 番の山 / 離れた 2 番目の山,
   "refSec": ref の秒, "winSec": window の秒}
  照合できない(無音・短すぎる・numpy が無い・読めない)ときは {"ok": false, "reason": 日本語の理由}

作り:
- 正規化 = 「ref と、それに重なる window の区間」の内積 ÷ 両方の長さ(ノルム)。音量の違い(速報版の音量の設定)に左右されない。
  window の区間のノルムは 2 乗の累積和で全部のずれについて一度に出す。
- 分子は FFT の相互相関を overlap-save で区切って計算する(window が 20 分 = 1000 万サンプルでも、一度に大きな FFT をしない = メモリを抑える)。
  scipy は入っていないので numpy の rfft だけ。
- 山の位置は前後の 3 点の放物線で 1 サンプル(0.125 ms)より細かく。
- ratio の「離れた」= 1 番の山の前後 SEP 秒より外(山のすそ野を 2 番目に数えない)。外に何も無い(window ≒ ref)ときは RATIO_MAX。
"""
import json
import sys
import wave

RATE = 8000
SEP = 0.25            # 2 番目の山を探すとき、1 番の山の前後これだけを外す(秒)
RATIO_MAX = 99.0
MIN_REF_SEC = 0.5
SILENT_RMS = 1e-4     # これより小さい(-80 dBFS 未満)は無音とみなす(16bit を -1〜1 にした値)
MAX_SEC = 3 * 3600


def fail(reason):
    print(json.dumps({"ok": False, "reason": reason}))   # ASCII だけ(\u…)= 親の文字コードの設定に左右されない
    return 0


def read_wav(path, np):
    """-> (float64 の配列(-1〜1), サンプリング周波数)。形が違えば ValueError"""
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if width != 2:
            raise ValueError("16bit の WAV ではありません")
        if n > MAX_SEC * rate:
            raise ValueError("長すぎます")
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    return x, rate


def next_pow2(n):
    """n 以上でいちばん小さい 2 の累乗(n が 1 以下なら 1)"""
    return 1 << max(0, n - 1).bit_length()


def xcorr_valid(ref, win, np):
    """sum_i ref[i] * win[i + k](k = 0 .. len(win) - len(ref))を overlap-save で。-> 長さ len(win) - len(ref) + 1 の配列"""
    m, n = len(ref), len(win)
    total = n - m + 1
    nfft = next_pow2(max(4 * m, 1 << 16))
    step = nfft - m + 1
    rf = np.conj(np.fft.rfft(ref, nfft))
    out = np.empty(total, dtype=np.float64)
    pos = 0
    while pos < total:
        seg = win[pos: pos + nfft]
        if len(seg) < nfft:
            seg = np.concatenate([seg, np.zeros(nfft - len(seg))])
        c = np.fft.irfft(np.fft.rfft(seg) * rf, nfft)[:step]   # 先頭の step 個は折り返しの無い(正しい)ずれ
        k = min(step, total - pos)
        out[pos: pos + k] = c[:k]
        pos += k
    return out


def align(ref, win, rate, np):
    m, n = len(ref), len(win)
    rnorm = float(np.sqrt(np.dot(ref, ref)))
    num = xcorr_valid(ref, win, np)
    cs = np.concatenate([[0.0], np.cumsum(win * win)])
    wnorm = np.sqrt(np.maximum(cs[m:] - cs[:-m], 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(wnorm > SILENT_RMS * np.sqrt(m), num / (rnorm * wnorm), 0.0)
    k = int(np.argmax(c))
    peak = float(c[k])
    frac = 0.0
    if 0 < k < len(c) - 1:   # 放物線で山の頂点を細かく
        y0, y1, y2 = float(c[k - 1]), peak, float(c[k + 1])
        den = y0 - 2 * y1 + y2
        if den < 0:
            frac = max(-0.5, min(0.5, 0.5 * (y0 - y2) / den))
    sep = int(SEP * rate)
    rest = np.concatenate([c[: max(0, k - sep)], c[k + sep + 1:]])
    second = float(rest.max()) if len(rest) else 0.0
    ratio = RATIO_MAX if second <= 0 else min(RATIO_MAX, peak / second)
    return {"ok": True, "offset": round((k + frac) / rate, 5), "score": round(max(0.0, min(1.0, peak)), 4), "ratio": round(ratio, 3),
            "refSec": round(m / rate, 3), "winSec": round(n / rate, 3)}


def main(argv):
    if len(argv) != 3:
        return fail("使い方: live_align_worker.py <ref.wav> <window.wav>")
    try:
        import numpy as np
    except ImportError:
        return fail("numpy が無いので照合できません(py -3.10 に入っている Python で動かしてください)")
    try:
        ref, r1 = read_wav(argv[1], np)
        win, r2 = read_wav(argv[2], np)
    except (OSError, EOFError, ValueError, wave.Error) as e:
        return fail("音を読めませんでした(%s)" % (str(e)[:100] or e.__class__.__name__))
    if r1 != r2:
        return fail("サンプリング周波数がそろっていません(%d / %d)" % (r1, r2))
    if len(ref) < MIN_REF_SEC * r1:
        return fail("速報版の音が短すぎます(%.2f 秒)" % (len(ref) / r1))
    if len(win) < len(ref):
        return fail("アーカイブの音が速報版より短いです(%.1f 秒 / %.1f 秒)" % (len(win) / r1, len(ref) / r1))
    if float(np.sqrt(np.mean(ref * ref))) < SILENT_RMS:
        return fail("速報版の音が無音なので照合できません")
    if float(np.sqrt(np.mean(win * win))) < SILENT_RMS:
        return fail("アーカイブの音が無音なので照合できません")
    ref = ref - ref.mean()
    win = win - win.mean()
    print(json.dumps(align(ref, win, r1, np)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
