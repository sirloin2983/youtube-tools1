# -*- coding: utf-8 -*-
"""配信中の録画の 16kHz モノラルの音の控え(11-01 ライブを軽くする案の C = 同じ音を 1 回だけデコードする)。

書く側 = 検出のワーカー(live_excite_worker.py): 音を測る ffmpeg の同じ 1 回で、16kHz・モノラル・s16le の生の音も出し(levels.args の pcm)、
  録画の作業フォルダ <録画元>/<録画>/ の PCM_NAME に足して、IDX_NAME に 1 行 [始まりの時刻 epoch, 何バイト目から, 何バイト] を足す(先に音・後で行)。
  配信が終わって録画を締めたら消す(drop)。
読む側 = 配信中の候補の文字起こし(flow/live_tx.py): 候補の区間(+ 余白)が切れ目なくそろっていれば、ここから wav を作る(セグメントの取り直しと ffmpeg を外す)。
  そろっていなければ None = 今までの取り直しの道(検出のワーカーが止まっていた・測り始める前・つなぎ直しをまたぐ)。
スイッチ: 環境変数 YTT_LIVE_AUDIO_KEEP=off で書かない(読む側は控えが無いので今までの道)。標準ライブラリだけ。
"""
import json
import os
import wave

KEEP_ENV = "YTT_LIVE_AUDIO_KEEP"
PCM_NAME = "audio16k.pcm"
IDX_NAME = "audio16k.idx"
RATE = 16000
BPS = 2 * RATE       # 1 秒のバイト数(s16le・モノラル)
JOIN_GAP = 0.3       # これより短い隙間・重なりは続きとみなす(セグメントの時刻とデコードの長さの差)
IDX_MAX = 4 * 1024 * 1024


def enabled(env=None):
    return (os.environ if env is None else env).get(KEEP_ENV, "").strip().lower() not in ("off", "0", "false")


def append(folder, t, pcm_path):
    """pcm_path(ffmpeg が書いた生の音)を folder の控えに足す -> 足したバイト数(無い・空なら 0)。OSError はそのまま上げる"""
    try:
        with open(pcm_path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return 0
    data = data[:len(data) // 2 * 2]
    if not data:
        return 0
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, PCM_NAME)
    with open(dst, "ab") as f:
        off = f.tell()
        f.write(data)
    with open(os.path.join(folder, IDX_NAME), "a", encoding="utf-8") as f:
        f.write(json.dumps([round(float(t), 3), off, len(data)]) + "\n")
    return len(data)


def drop(folder):
    for n in (PCM_NAME, IDX_NAME):
        try:
            os.remove(os.path.join(folder, n))
        except OSError:
            pass


def _chunks(folder):
    """[(t, off, n)](時刻の順。音のファイルに収まっている行だけ)"""
    try:
        size = os.path.getsize(os.path.join(folder, PCM_NAME))
        with open(os.path.join(folder, IDX_NAME), "r", encoding="utf-8") as f:
            text = f.read(IDX_MAX)
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            t, off, n = json.loads(ln)
            t, off, n = float(t), int(off), int(n)
        except (ValueError, TypeError):
            continue
        if off >= 0 and n > 0 and off + n <= size:
            out.append((t, off, n))
    return sorted(out)


def cut(folder, a, b, margin=0.0):
    """候補の区間 [a, b](epoch 秒)を含む切れ目のない控えがあれば、前後に margin 秒まで(控えのある所まで)足して
    -> (wa, wb, 音のバイト列) か None(区間が欠けている・控えが無い)"""
    runs, cur = [], None
    for t, off, n in _chunks(folder):
        end = t + n / BPS
        if cur is not None and t <= cur["end"] + JOIN_GAP:
            if end <= cur["end"] + JOIN_GAP:   # 同じ所をもう一度測った(ワーカーの起こし直し): 前の方を使う
                continue
            cur["parts"].append((max(t, cur["end"]), t, off, n))
            cur["end"] = end
            continue
        cur = {"start": t, "end": end, "parts": [(t, t, off, n)]}
        runs.append(cur)
    run = next((r for r in runs if r["start"] <= a + JOIN_GAP and r["end"] >= b - JOIN_GAP), None)
    if run is None:
        return None
    wa = min(a, max(a - margin, run["start"]))   # 控えの端が区間の内側に JOIN_GAP までずれている時は区間の端のまま(ずれは 0.3 秒まで)
    wb = max(b, min(b + margin, run["end"]))
    buf = bytearray()
    with open(os.path.join(folder, PCM_NAME), "rb") as f:
        for from_t, t, off, n in run["parts"]:
            lo, hi = max(wa, from_t), min(wb, t + n / BPS)
            if hi <= lo:
                continue
            pad = int(round((lo - wa) * RATE)) * 2 - len(buf)   # 小さな隙間・端のずれは無音で埋める(行の時刻を wa からの秒に保つ)
            if pad > 0:
                buf += bytes(pad)
            s = off + int((lo - t) * RATE) * 2
            e = min(off + n, off + int(round((hi - t) * RATE)) * 2)
            f.seek(s)
            buf += f.read(max(0, e - s))
    return (wa, wb, bytes(buf)) if buf else None


def write_wav(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
