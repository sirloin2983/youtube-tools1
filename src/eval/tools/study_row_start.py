#!/usr/bin/env python3
"""行の始まりのずれの 3 案を測る道具(10-21 ユーザー「区間の始めが話し始めより前にくる」の調べ。**測るだけ・ツールの動きは変えない**)。

    py -3.12 -m eval.tools.study_row_start [--audio] [--dtw] [--only id,id] [--json 出力] [--data-dir 作業データの親フォルダ]

- 作業データは**読むだけ**(transcripts/<id>.json・<id>.words.json・元の動画)。音声と whisper-cli の出力は一時フォルダ(終わったら消す)
- 正解 = 校正済み(proofed)の人の行。機械の行 = 文書の original。突き合わせは eval/tools/eval_timing と同じ
  (いちばん長く重なる機械の行で、頭か末の 6 文字が合う行だけ)。ずれ = 機械の始まり − 人の始まり(負 = 早すぎる = 話し始めより前)
- 組: 全部の校正済みの行 / 人が始まりを直した行(|ずれ| ≥ 0.05 秒)
- 案(どれも機械の行から作る。人の文字は使わない = 認識したときに自動でかけられる形):
    base  … 今(original のまま)
    r1    … 案 1: 単語の時刻で全部の行を配り直す(pipeline/transcribe/retime.retime_candidates をそのまま全行に。重ならない守りつき)
    e3    … 案 3a: 音の大きさの立ち上がりに寄せる(10 ms ごとの dB・前後 1.5 秒の 20% 点 + ONSET_DB を越えた所のうち、今の始まりに近い所。±ONSET_WIN 秒まで)
    v3    … 案 3b: 声の検出(faster-whisper の silero VAD)の声の始まりに寄せる(±ONSET_WIN 秒まで)
    r1v3  … 案 1 のあと 3b
  --dtw: 案 2 = whisper-cli を同じ引数で 2 回(DTW なし・-dtw large.v3)流し、トークンの時刻(offsets と t_dtw)から単語を作って
    今の後処理(eval_timing.reapply)で行にする -> w0(DTW なし)・w2(DTW の単語)・w0r1・w2r1(それぞれ案 1)。文字が同じか・秒も出す
- 前の行に重ならない: e3・v3 は同じ話者の前の機械の行の終わりより前へは動かさない
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import wave

from eval.tools import _evalcommon as C  # noqa: E402  src を sys.path に足す
from eval.tools import eval_timing as T  # noqa: E402
from pipeline.transcribe import retime as R  # noqa: E402
from ytt import tools as ytools  # noqa: E402

CHANGED = 0.05     # 人が始まりを直したとみなす差(秒)
ONSET_WIN = 0.6    # 立ち上がり・声の始まりを探す前後の秒
ONSET_DB = 12.0    # 立ち上がりのしきい(床からの dB)
FRAME = 0.01
DTW_SHIFTS = (0.05, 0.1, 0.15)   # DTW の始まりを前へずらす秒(試すだけ)
WCPP = os.path.join("bin", "whisper.cpp-v1.9.4-vulkan", "whisper-cli.exe")
MODEL = os.path.join("models", "whispercpp", "ggml-large-v3.bin")


# ---------------------------------------------------------------- 物差し

def stats(ds):
    """ずれの並び -> {n, median, absMedian, in01, in02, in05, early, late}(early = 0.1 秒より早い・late = 0.1 秒より遅い)"""
    n = len(ds)
    if not n:
        return {"n": 0}
    a = [abs(d) for d in ds]
    return {"n": n, "median": round(statistics.median(ds), 3), "absMedian": round(statistics.median(a), 3),
            "in01": round(sum(1 for x in a if x <= 0.1) / n, 3), "in02": round(sum(1 for x in a if x <= 0.2) / n, 3),
            "in05": round(sum(1 for x in a if x <= 0.5) / n, 3),
            "early": round(sum(1 for d in ds if d < -0.1) / n, 3), "late": round(sum(1 for d in ds if d > 0.1) / n, 3)}


def pairs(human, machine):
    """校正済みの人の行と文字が合う機械の行の組 [(h, m の番号)](eval_timing.measure_rows と同じ当て方)"""
    out = []
    idx = {id(m): k for k, m in enumerate(machine)}
    for h in human:
        if h.get("proofed") is not True:
            continue
        m = T.best_overlap(h, machine)
        if m is not None and T.text_match(h.get("text"), m.get("text")):
            out.append((h, idx[id(m)]))
    return out


# ---------------------------------------------------------------- 案 1

def retimed(rows, words):
    """全部の行に案 1 -> (始まりの並び, 終わりの並び, 候補が出た行の数)"""
    segs = [dict(r, id=str(k)) for k, r in enumerate(rows)]
    got = {it["id"]: it for it in R.retime_candidates(segs, words)}
    st = [float(got[str(k)]["start"]) if str(k) in got else r["start"] for k, r in enumerate(rows)]
    en = [float(got[str(k)]["end"]) if str(k) in got else r["end"] for k, r in enumerate(rows)]
    moved = sum(1 for k, r in enumerate(rows) if str(k) in got and abs(got[str(k)]["start"] - r["start"]) >= 0.1)
    return st, en, moved


# ---------------------------------------------------------------- 音

def extract(src, a, b, out):
    ff = ytools.find_tool("ffmpeg") or "ffmpeg"
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.3f" % a, "-to", "%.3f" % b, "-i", src, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", out], check=True, creationflags=ytools.no_window_flags(), stdin=subprocess.DEVNULL)


def read_wav(p):
    import numpy as np
    with wave.open(p, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float32") / 32768.0


def db_frames(x):
    import numpy as np
    n = int(FRAME * 16000)
    k = len(x) // n
    e = (x[:k * n].reshape(k, n) ** 2).mean(axis=1)
    return 10 * np.log10(e + 1e-10)


def energy_onset(db, s, lo):
    """s(行の秒・音声の頭が 0)の前後 ONSET_WIN 秒で、床 + ONSET_DB を下から越えた所のうち s に近い所(無ければ None)。lo より前にしない"""
    import numpy as np
    i0, i1 = max(1, int((s - ONSET_WIN) / FRAME)), min(len(db) - 3, int((s + ONSET_WIN) / FRAME))
    if i1 <= i0:
        return None
    f0, f1 = max(0, int((s - 1.5) / FRAME)), min(len(db), int((s + 1.5) / FRAME))
    thr = float(np.percentile(db[f0:f1], 20)) + ONSET_DB
    ups = [i for i in range(i0, i1) if db[i - 1] <= thr < db[i] and db[i + 1] > thr and db[i + 2] > thr]
    ups = [i * FRAME for i in ups if i * FRAME >= lo]
    return min(ups, key=lambda t: abs(t - s)) if ups else None


def vad_starts(x):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    ts = get_speech_timestamps(x, VadOptions(threshold=0.5, min_silence_duration_ms=100, speech_pad_ms=30, min_speech_duration_ms=100))
    return [t["start"] / 16000.0 for t in ts]


def near(starts, s, lo):
    c = [t for t in starts if abs(t - s) <= ONSET_WIN and t >= lo]
    return min(c, key=lambda t: abs(t - s)) if c else None


def snapped(rows, base_starts, finder, off):
    """行ごとに finder(s, lo) で寄せる(off = 音声の頭の元の動画の秒・lo = 同じ話者の前の行の終わり)-> (始まり, 動いた行の数)"""
    out, moved = [], 0
    for k, r in enumerate(rows):
        s = base_starts[k]
        lo = max([rows[q]["end"] for q in range(max(0, k - 8), k) if R._retime_same_group(rows[q], r)] or [-1e9])
        t = finder(s - off, lo - off)
        if t is not None and abs(t + off - s) >= 0.05:
            out.append(round(t + off, 2))
            moved += 1
        else:
            out.append(s)
    return out, moved


# ---------------------------------------------------------------- 案 2(whisper-cli を 2 回)

def wcpp_run(root, wav, work, dtw):
    exe, model = os.path.join(root, WCPP), os.path.join(root, MODEL)
    base = os.path.join(work, "dtw" if dtw else "plain")
    cmd = [exe, "-m", model, "-f", wav, "-ojf", "-of", base, "-t", str(max(1, (os.cpu_count() or 2) // 2)), "-l", "ja", "-bs", "5", "-nfa",
           "-mc", "0", "-nth", "0.9"]   # 本番と同じ(worker_client.whisper_kwargs の既定 = 前の文を文脈にしない・声の検出 weak の no_speech 0.9。無いと長い音で同じ文を繰り返した)
    if dtw:
        cmd += ["-dtw", "large.v3"]
    t0 = time.time()
    subprocess.run(cmd, check=True, capture_output=True, creationflags=ytools.no_window_flags(), stdin=subprocess.DEVNULL, cwd=work)
    sec = time.time() - t0
    keep = os.environ.get("YTT_STUDY_KEEP")
    if keep:   # 崩れの形を見るために -ojf の結果を残す(一時フォルダの外)
        shutil.copyfile(base + ".json", os.path.join(keep, "%s-%d.json" % ("dtw" if dtw else "plain", int(time.time()))))
    with open(base + ".json", encoding="utf-8", errors="replace") as f:
        return json.load(f), sec


def wcpp_raw(data, dtw, shift=None):
    """-ojf の結果 -> 後処理に渡す分ける前の行(tx_engines.parse_json と同じ単語の選び方。dtw = 単語の始まりを t_dtw に・終わりは次の単語の始まり)。
    shift(秒)= 始まりだけ: 単語の始まりを t_dtw − shift(前の単語の始まり・0 より前にしない)・終わりは今の時刻(offsets)のまま"""
    if shift is not None:
        return wcpp_raw_start(data, shift)
    raw = []
    for seg in data.get("transcription") or []:
        off = seg.get("offsets") or {}
        if not isinstance(off.get("from"), (int, float)):
            continue
        ws = []
        for tok in seg.get("tokens") or []:
            t = str((tok or {}).get("text") or "")
            if not t or t.startswith("[_") or "�" in t:
                continue
            to = tok.get("offsets") or {}
            a, b = to.get("from"), to.get("to")
            if dtw and isinstance(tok.get("t_dtw"), (int, float)) and tok["t_dtw"] >= 0:
                a = tok["t_dtw"] * 10.0
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                ws.append([a / 1000.0, max(a, b) / 1000.0, t])
        if dtw:
            for i in range(len(ws) - 1):
                ws[i][1] = max(ws[i][0], min(ws[i][1], ws[i + 1][0]) if ws[i + 1][0] > ws[i][0] else ws[i][1])
        raw.append({"start": off["from"] / 1000.0, "end": off["to"] / 1000.0, "text": str(seg.get("text") or ""), "words": [tuple(w) for w in ws]})
    if dtw:   # 行の始まりも DTW の最初の単語へ(分ける前の行の時刻 = 単語のある行は単語から)
        for r in raw:
            if r["words"]:
                r["start"] = min(r["start"], r["words"][0][0]) if r["words"][0][0] < r["start"] else r["words"][0][0]
    return raw


DROPPED = {"words": 0, "dropped": 0}   # 始まりだけ DTW の形で今の時刻へ落とした単語の数(最後に作った分)


def wcpp_raw_start(data, shift):
    raw, prev = [], 0.0
    DROPPED.update(words=0, dropped=0)
    for seg in data.get("transcription") or []:
        off = seg.get("offsets") or {}
        if not isinstance(off.get("from"), (int, float)):
            continue
        ws = []
        for tok in seg.get("tokens") or []:
            t = str((tok or {}).get("text") or "")
            if not t or t.startswith("[_") or "�" in t:
                continue
            to = tok.get("offsets") or {}
            a, b = to.get("from"), to.get("to")
            if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
                continue
            a, b = a / 1000.0, b / 1000.0
            d = tok.get("t_dtw")
            DROPPED["words"] += 1
            if isinstance(d, (int, float)) and d >= 0 and off["from"] / 1000.0 - 1.0 <= d / 100.0 <= off["to"] / 1000.0 + 1.0:   # 崩れた(行の範囲の前後 1 秒の外)時刻は今の時刻のまま
                a = max(prev, 0.0, d / 100.0 - shift)
            else:
                DROPPED["dropped"] += 1
            prev = a
            ws.append((a, max(a, b), t))
        start = ws[0][0] if ws else off["from"] / 1000.0
        raw.append({"start": start, "end": max(start, off["to"] / 1000.0), "text": str(seg.get("text") or ""), "words": ws})
    return raw


# ---------------------------------------------------------------- 1 つの文書

def study_doc(root, doc, words, audio, dtw, work):
    machine = T.text_rows(doc.get("original"))
    human = T.text_rows(doc.get("segments"))
    pr = pairs(human, machine)
    out = {"id": doc.get("id"), "title": str(doc.get("title") or "")[:30], "rows": len(machine), "pairs": len(pr), "var": {}, "moved": {}}
    if not pr:
        return out, []
    base = [r["start"] for r in machine]
    st = {"base": base}
    ends = {"base": [r["end"] for r in machine]}
    st["r1"], ends["r1"], out["moved"]["r1"] = retimed(machine, words)
    if audio:
        src = doc.get("sourcePath")
        off = float(doc.get("start") or 0.0)
        wav = os.path.join(work, "a.wav")
        extract(src, off, float(doc.get("end")), wav)
        x = read_wav(wav)
        db = db_frames(x)
        vs = vad_starts(x)
        st["e3"], out["moved"]["e3"] = snapped(machine, base, lambda s, lo: energy_onset(db, s, lo), off)
        st["v3"], out["moved"]["v3"] = snapped(machine, base, lambda s, lo: near(vs, s, lo), off)
        st["r1v3"], out["moved"]["r1v3"] = snapped(machine, st["r1"], lambda s, lo: near(vs, s, lo), off)
    rows = []
    for h, k in pr:
        rows.append({"doc": doc.get("id"), "h": h["start"], "he": h["end"], "changed": abs(base[k] - h["start"]) >= CHANGED,
                     **{v: st[v][k] - h["start"] for v in st}, **{"end_" + v: ends[v][k] - h["end"] for v in ends}})
    if audio and dtw:
        out["dtw"] = study_dtw(root, doc, human, wav, work)
        rows += out["dtw"].pop("_rows")
    return out, rows


def dtw_anomalies(data, dur):
    """DTW のトークンの時刻の崩れ: 時刻なし(-1)・行の中で戻る・音の長さを超える・行の範囲の外(前後 1 秒より外)の数"""
    out = {"tokens": 0, "none": 0, "back": 0, "beyond": 0, "outside": 0}
    for seg in data.get("transcription") or []:
        off = seg.get("offsets") or {}
        prev = None
        for tok in seg.get("tokens") or []:
            t = str((tok or {}).get("text") or "")
            if not t or t.startswith("[_"):
                continue
            out["tokens"] += 1
            d = tok.get("t_dtw")
            if not isinstance(d, (int, float)) or d < 0:
                out["none"] += 1
                continue
            s = d / 100.0
            if prev is not None and s < prev - 1e-6:
                out["back"] += 1
            prev = s
            if s > dur + 0.05:
                out["beyond"] += 1
            if isinstance(off.get("from"), (int, float)) and not (off["from"] / 1000.0 - 1.0 <= s <= off["to"] / 1000.0 + 1.0):
                out["outside"] += 1
    return out


def changed_at(h, doc):
    """人が始まりを直した行か(original のいちばん重なる行の始まりと CHANGED 秒以上違う)"""
    m = T.best_overlap(h, T.text_rows(doc.get("original")))
    return m is not None and abs(m["start"] - h["start"]) >= CHANGED


def study_dtw(root, doc, human, wav, work):
    off = float(doc.get("start") or 0.0)
    params = doc.get("params") if isinstance(doc.get("params"), dict) else {}
    spec = {"wordSplit": params.get("wordSplit", True) is not False, "stripPunct": params.get("stripPunct", True) is not False, "engine": "whisper.cpp"}
    res, rows_out = {}, []
    texts = {}
    got = {}
    for key, dtw, shift in (("w0", False, None), ("w2", True, None), ("w3", True, 0.1), ("w3a", True, 0.05), ("w3c", True, 0.15)):   # w3 = 始まりだけ DTW − 0.1 秒・終わりは今のまま(w2 と同じ出力から)
        if dtw not in got:
            got[dtw] = wcpp_run(root, wav, work, dtw)
        data, sec = got[dtw]
        raw = wcpp_raw(data, dtw, shift)
        mrows = T.reapply(raw, spec, float(doc.get("end")) - off, off)
        mrows = T.text_rows(mrows)
        words = [[w[0] + off, w[1] + off, w[2]] for r in raw for w in r["words"]]
        texts[key] = "".join(T.letters(r.get("text")) for r in raw)
        st1, _en, moved = retimed(mrows, words)
        pr = pairs(human, mrows)
        res[key] = {"sec": round(sec, 1), "rows": len(mrows), "pairs": len(pr), "movedR1": moved, "boundary": T.boundary_agreement(human, mrows),
                    **({"dropped": dict(DROPPED)} if shift is not None else {}),
                    "rowTexts": [T.letters(r.get("text")) for r in mrows], "starts": [r["start"] for r in mrows], "ends": [r["end"] for r in mrows]}
        if dtw:
            res[key]["anomalies"] = dtw_anomalies(data, float(doc.get("end")) - off)
            sh = [s - 0.1 for s in res[key]["starts"]]
            res[key]["shiftOverlap"] = sum(1 for i in range(1, len(sh)) if sh[i] < res[key]["ends"][i - 1] - 1e-6 <= res[key]["starts"][i])
            res[key]["shiftNegative"] = sum(1 for s in sh if s < off)
        for h, k in pr:
            rows_out.append({"doc": doc.get("id"), "dtwKey": key, "h": h["start"], key: mrows[k]["start"] - h["start"], key + "r1": st1[k] - h["start"],
                             "end_" + key: mrows[k]["end"] - h["end"], "len": h["end"] - h["start"], "changed": changed_at(h, doc)})
    res["sameText"] = texts["w0"] == texts["w2"]
    a, b = res["w0"].pop("rowTexts"), res["w2"].pop("rowTexts")
    c = res["w3"].pop("rowTexts")
    for k in ("w3a", "w3c"):
        res[k].pop("rowTexts", None)
    res["rowsSameTextW3"] = round(sum(1 for t in c if t in set(a)) / len(c), 3) if c else None
    res["sameRows"] = a == b
    res["rowsSameText"] = round(sum(1 for t in b if t in set(a)) / len(b), 3) if b else None
    res["_rows"] = rows_out
    return res


def embed_check(root, ids, pre_wav, pre):
    """長い音の中の DTW の確かさ: 校正済みの文書の音の前に pre_wav の頭 pre 秒をつないで流し、文書の所の行を人の行と比べる(短い音だけでは長い配信の形が分からない)"""
    import numpy as np
    work = tempfile.mkdtemp(prefix="ytt-rowstart-embed-")
    out = {}
    try:
        lead = read_wav(pre_wav)[:int(pre * 16000)]
        for tid, doc in C.iter_docs(root, only=set(ids)):
            if not doc:
                continue
            off = float(doc.get("start") or 0.0)
            extract(doc.get("sourcePath"), off, float(doc.get("end")), os.path.join(work, "d.wav"))
            x = np.concatenate([lead, read_wav(os.path.join(work, "d.wav"))])
            wav = os.path.join(work, "a.wav")
            with wave.open(wav, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes((x.clip(-1, 1) * 32767).astype("<i2").tobytes())
            human = T.text_rows(doc.get("segments"))
            params = doc.get("params") if isinstance(doc.get("params"), dict) else {}
            spec = {"wordSplit": params.get("wordSplit", True) is not False, "stripPunct": params.get("stripPunct", True) is not False, "engine": "whisper.cpp"}
            rec = {}
            for key, dtw in (("w0", False), ("w2", True)):
                data, sec = wcpp_run(root, wav, work, dtw)
                raw = wcpp_raw(data, dtw)
                mrows = T.text_rows(T.reapply(raw, spec, len(x) / 16000.0, off - pre))
                pr = pairs(human, mrows)
                rec[key] = dict(stats([mrows[k]["start"] - h["start"] for h, k in pr]), sec=round(sec, 1))
                if dtw:
                    rec[key]["anomalies"] = dtw_anomalies(data, len(x) / 16000.0)
            out[tid] = rec
            print(tid, json.dumps(rec, ensure_ascii=False), file=sys.stderr, flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def long_check(root, src, secs):
    """長い音(配信の頭から secs 秒)で DTW なし・ありを 1 回ずつ -> 秒・崩れ・文字が同じか・行の数(標準出力に JSON)"""
    work = tempfile.mkdtemp(prefix="ytt-rowstart-long-")
    try:
        wav = os.path.join(work, "a.wav")
        extract(src, 0.0, secs, wav)
        out = {}
        for key, dtw in (("w0", False), ("w2", True)):
            data, sec = wcpp_run(root, wav, work, dtw)
            raw = wcpp_raw(data, dtw)
            out[key] = {"sec": round(sec, 1), "segments": len(raw), "text": "".join(T.letters(r.get("text")) for r in raw)}
            if dtw:
                out[key]["anomalies"] = dtw_anomalies(data, secs)
                ws = [w for r in raw for w in r["words"]]
                out[key]["zeroLen"] = sum(1 for w in ws if w[1] - w[0] <= 0.0)
                out[key]["words"] = len(ws)
        out["sameText"] = out["w0"]["text"] == out["w2"]["text"]
        out["chars"] = [len(out["w0"].pop("text")), len(out["w2"].pop("text"))]
        print(json.dumps(out, ensure_ascii=False, indent=1))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="study_row_start")
    ap.add_argument("--audio", action="store_true", help="案 3(音の立ち上がり・声の検出)も測る(元の動画から音を取る)")
    ap.add_argument("--dtw", action="store_true", help="案 2(whisper-cli を DTW なし・ありで 2 回。GPU)も測る(--audio が要る)")
    ap.add_argument("--only", default="", help="文書の id(, 区切り)")
    ap.add_argument("--json", default="", help="結果を書くファイル")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--long", default="", help="長い音の確かめ: この動画の頭から --secs 秒を DTW なし・ありで 1 回ずつ(崩れ・秒・文字が同じか)")
    ap.add_argument("--secs", type=float, default=3600.0)
    a = ap.parse_args(argv)
    root = C.locate("transcribe", a.data_dir)
    if a.long and a.only:   # 長い音の中の確かさ(--long の頭 --secs 秒を文書の前につなぐ)
        return embed_check(root, C.split_ids(a.only), a.long, a.secs)
    if a.long:
        return long_check(root, a.long, a.secs)
    only = set(C.split_ids(a.only)) if a.only else None
    docs, rows = [], []
    work = tempfile.mkdtemp(prefix="ytt-rowstart-")
    try:
        for tid, doc in C.iter_docs(root):
            if not doc or not doc.get("original") or (only and tid not in only):
                continue
            if not any(isinstance(g, dict) and g.get("proofed") is True for g in doc.get("segments") or []):
                continue
            try:
                with open(os.path.join(root, "transcripts", tid + ".words.json"), encoding="utf-8") as f:
                    words = [w for w in (json.load(f).get("words") or []) if isinstance(w, (list, tuple)) and len(w) >= 3]
            except (OSError, ValueError):
                words = []
            rec, rs = study_doc(root, doc, words, a.audio, a.dtw, work)
            docs.append(rec)
            rows += rs
            print("%s %s 組 %d" % (tid, rec["title"], rec["pairs"]), file=sys.stderr, flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    keys = [k for k in ("base", "r1", "e3", "v3", "r1v3") if any(k in r for r in rows)]
    res = {"docs": len([d for d in docs if d["pairs"]]), "pairs": sum(1 for r in rows if "base" in r), "overall": {}, "changed": {}, "ends": {}, "byDoc": docs}
    main_rows = [r for r in rows if "base" in r]
    for k in keys:
        res["overall"][k] = stats([r[k] for r in main_rows])
        res["changed"][k] = stats([r[k] for r in main_rows if r["changed"]])
    for k in ("base", "r1"):
        res["ends"][k] = stats([r["end_" + k] for r in main_rows])
    dr = [r for r in rows if "dtwKey" in r]
    if dr:
        res["dtw"] = {k: stats([r[k] for r in dr if k in r]) for k in ("w0", "w0r1", "w2", "w2r1", "w3", "w3a", "w3c")}
        for sh in DTW_SHIFTS:   # DTW の時刻は遅れぎみ(中央値 +0.11 秒)= 決まった秒だけ前へ
            res["dtw"]["w2-%g" % sh] = stats([r["w2"] - sh for r in dr if "w2" in r])
        res["dtwEnds"] = {k: stats([r["end_" + k] for r in dr if "end_" + k in r]) for k in ("w0", "w2", "w3", "w3a", "w3c")}
        res["dtwChanged"] = {k: stats([r[k] for r in dr if k in r and r.get("changed")]) for k in ("w0", "w2", "w3", "w3a", "w3c")}
        res["dtwChanged"].update({"w2-%g" % sh: stats([r["w2"] - sh for r in dr if "w2" in r and r.get("changed")]) for sh in DTW_SHIFTS})
    tot = {k: sum(d["moved"].get(k, 0) for d in docs) for k in keys if k != "base"}
    res["movedRows"] = tot
    res["machineRows"] = sum(d["rows"] for d in docs)
    print(json.dumps({k: v for k, v in res.items() if k != "byDoc"}, ensure_ascii=False, indent=1))
    if a.json:
        res["rowsData"] = rows
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
