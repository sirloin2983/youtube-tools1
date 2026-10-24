# -*- coding: utf-8 -*-
"""声を覚える材料の短い音(10-24 夜。ユーザー「誰の声をメンバー全員分」・「精度に関係する物は残す」)。

ソロ配信の文書の行のうち、確かめるの誰の声のカード(app/check/voice_solo)に出す行の音だけを、元の動画から短く切り出して作業データに残す。
元の動画は自動の片付け(manage/keep/cleanup)が 3 日でごみ箱へ移すので、そのあとも
  - カードはこの音で再生する(入口の GET /api/check/voiceclip?doc=&row=)
  - 声を覚えるジョブ(speakers.run_voice_learn)は、この音を文書の時刻に並べた音(timeline_wav)から特徴を取る
置き場所: <編集の作業データ>/voice-clips/<文書 id>/<行 id>.wav(16kHz・モノラル・16bit = 認識の音と同じ形)と index.json
(行 id -> {"a", "b"} = 切り出した所の元の動画の秒)。作業データの中なので、片付けの外(評価用・学習用と同じく消さない)。
切り出すのは行の前後 PAD 秒まで(1 行数秒)。1 本の文書・1 行は 1 回だけ(作り直さない)。
"""
import json
import os
import threading
import wave

from ytt import fsio, tools as _tools, workdata as _workdata

DIR = "voice-clips"
INDEX = "index.json"
PAD = 1.0             # 行の前後に足す秒(カードの余白 0.3 秒・覚える行の時刻の揺れの分)
RATE = 16000
CUT_TIMEOUT = 60.0
MAX_ROW_SEC = 30.0    # これより長い行は切り出さない(カードは 12 秒まで)
_lock = threading.Lock()


def root():
    d = _workdata.DATA_DIR
    return os.path.join(d, DIR) if d else None


def _doc_dir(tid):
    r = root()
    if not r or not isinstance(tid, str) or not tid.isalnum() or not tid.isascii():
        return None
    return os.path.join(r, tid)


def index(tid):
    """文書の切り出した行 -> {行 id: {"a", "b"}}(無ければ {})"""
    d = _doc_dir(tid)
    if not d:
        return {}
    got = fsio.read_json_or(os.path.join(d, INDEX), {}, kind=dict)
    return {k: v for k, v in got.items() if isinstance(v, dict) and os.path.isfile(os.path.join(d, k + ".wav"))}


def _rid_ok(rid):
    """行 id の形(ファイル名にしてよい = 英数字と - _ だけ)"""
    return isinstance(rid, str) and 0 < len(rid) <= 64 and rid.replace("-", "").replace("_", "").isalnum() and rid.isascii()


def clip_path(tid, rid):
    """行の音のファイル(あれば)か None"""
    d = _doc_dir(tid)
    if not d or not _rid_ok(rid):
        return None
    p = os.path.join(d, rid + ".wav")
    return p if os.path.isfile(p) else None


def media(tid, rid, row_start, row_end):
    """カードの再生の形 {"url", "start", "end"}(この音の中の行の秒)か None(音が無い)"""
    it = index(tid).get(rid)
    if not it:
        return None
    a = float(it["a"])
    return {"url": "api/check/voiceclip?doc=%s&row=%s" % (tid, rid), "start": round(max(0.0, row_start - a), 3), "end": round(max(0.0, row_end - a), 3)}


def make(tid, doc, rows, ffmpeg=None):
    """文書の行(行の辞書 {id, start, end})の音を、まだ無い物だけ元の動画から切り出す。-> 作った数。元の動画が無ければ 0"""
    src = doc.get("sourcePath") if isinstance(doc, dict) else None
    d = _doc_dir(tid)
    if not d or not isinstance(src, str) or not os.path.isfile(src):
        return 0
    have = index(tid)
    todo = [g for g in rows if isinstance(g, dict) and _rid_ok(g.get("id")) and g["id"] not in have]
    if not todo:
        return 0
    ff = ffmpeg or _tools.find_tool("ffmpeg")
    if not ff:
        return 0
    os.makedirs(d, exist_ok=True)
    made = {}
    for g in todo:
        a0, b0 = float(g.get("start") or 0), float(g.get("end") or 0)
        if b0 <= a0 or b0 - a0 > MAX_ROW_SEC:
            continue
        a, b = max(0.0, a0 - PAD), b0 + PAD
        out = os.path.join(d, g["id"] + ".wav")
        cmd = [ff, "-hide_banner", "-nostdin", "-y", "-v", "error", "-ss", "%.3f" % a, "-i", src, "-t", "%.3f" % (b - a),
               "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "wav", out + ".part"]   # 認識の音と同じ形(16kHz・モノラル・16bit)
        try:
            r = _tools.run(cmd, timeout=CUT_TIMEOUT, flags=_tools.no_window_flags(priority="low"), stdout=False, err_tail=5)
        except OSError:
            break
        if r.why or r.code != 0 or not os.path.isfile(out + ".part"):
            continue
        os.replace(out + ".part", out)
        made[g["id"]] = {"a": round(a, 3), "b": round(b, 3)}
    if made:
        with _lock:
            cur = fsio.read_json_or(os.path.join(d, INDEX), {}, kind=dict)
            cur.update(made)
            fsio.write_json(os.path.join(d, INDEX), cur, indent=1)
    return len(made)


def timeline_wav(tid, out, start, end=None):
    """元の動画が無いときの、声を覚えるジョブの音: 文書の時刻 start〜end(秒)の長さの無音に、切り出した行の音をその時刻に置いた wav。
    -> 置いた行の数(0 なら何も書かない)"""
    clips = index(tid)
    if not clips:
        return 0
    start = float(start or 0)
    stop = float(end) if end else max(float(v["b"]) for v in clips.values())
    n = max(0, int((stop - start) * RATE))
    if n <= 0:
        return 0
    buf = bytearray(n * 2)
    placed = 0
    for rid, v in clips.items():
        try:
            with wave.open(os.path.join(_doc_dir(tid), rid + ".wav"), "rb") as w:
                if w.getframerate() != RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
                    continue
                data = w.readframes(w.getnframes())
        except (OSError, wave.Error, EOFError):
            continue
        off = int((float(v["a"]) - start) * RATE)
        if off < 0:
            data, off = data[-off * 2:], 0
        data = data[:max(0, (n - off) * 2)]
        if data:
            buf[off * 2:off * 2 + len(data)] = data
            placed += 1
    if placed:
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(bytes(buf))
    return placed
