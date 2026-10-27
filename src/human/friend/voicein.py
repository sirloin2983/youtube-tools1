# -*- coding: utf-8 -*-
"""友人の PC から届いた声の材料の受け取り(10-24 夜。作る側 = friendapp/voicesend。案 = 資料の git:before-1028-cleanup:plan/声の材料を友人のPCから-1024.md)。

送り返し\\ の `<印>__<文書の印>.voice.zip` を、送り返しの受付(returns.scan)がここへ渡す。中身(meta.json と <行 id>.wav)を確かめて
  - 小さな文字起こしの文書(id = 文書の印・origin = friend-voice・元の動画なし・話者 = 配信者 1 人・行 = 送られた行)を作る
  - 行の音を誰の声の材料の置き場所(human/proof/voiceclips)へ写す
誰の声のカード(app/check/voice_solo)は、この文書も今の文書と同じに出し、送られた音で再生する。答えると覚え直しも送られた音で動く。
外す物(写さない): 歌の配信(題名)・歌の行(音符)・名簿に無い人。覚えた人の分も写す(どれをカードにするかは voice_solo の並べ方。10-24 夜の決め直し)。
"""
import io
import json
import os
import re
import time
import wave
import zipfile

from flow import voicematerial as _vm
from human.proof import store as _store, voiceclips as _voiceclips
from ytt import docloc as _docloc, fsio, schemas as _yschemas

SUFFIX = ".voice.zip"
NAME_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__([0-9a-f]{12})" + re.escape(SUFFIX) + r"\Z")
FORMAT = "youtube-tools-voice/v1"
ORIGIN = "friend-voice"
MAX_ZIP = 8 * 1024 * 1024
MAX_WAV = 2 * 1024 * 1024
MAX_ROWS = 6
MAX_META = 64 * 1024
WAV_RE = re.compile(r"^([A-Za-z0-9_-]{1,16})\.wav\Z")


class Refused(ValueError):
    pass


def _read(p):
    """zip -> (meta, {行 id: wav の中身})。形が違えば Refused"""
    if os.path.getsize(p) > MAX_ZIP:
        raise Refused("大きすぎます")
    with zipfile.ZipFile(p) as z:
        infos = z.infolist()
        if len(infos) > MAX_ROWS + 1:
            raise Refused("中の数が多すぎます")
        meta, wavs = None, {}
        for i in infos:
            m = WAV_RE.match(i.filename)
            if i.filename == "meta.json" and i.file_size <= MAX_META:
                meta = json.loads(z.read(i).decode("utf-8"))
            elif m and i.file_size <= MAX_WAV:
                wavs[m.group(1)] = z.read(i)
            else:
                raise Refused("知らない物が入っています: %s" % i.filename[:60])
    if not isinstance(meta, dict) or meta.get("format") != FORMAT or not isinstance(meta.get("rows"), dict):
        raise Refused("meta.json の形が違います")
    return meta, wavs


def take(n, p, log):
    """1 本の声の材料 -> (state "accepted"|"rejected", 理由)。zip は呼び手(returns)が受付済み・失敗へ移す"""
    m = NAME_RE.match(n)
    if not m:
        return "rejected", "名前が <印>__<文書の印>%s の形ではありません" % SUFFIX
    tid = m.group(2)
    try:
        meta, wavs = _read(p)
    except (Refused, ValueError, UnicodeDecodeError) as e:
        return "rejected", str(e)[:200]
    who = _vm.member(meta.get("streamer"))
    title = str(meta.get("title") or "")[:200]
    if not who:
        return "rejected", "名簿に無い人です"
    if _vm.song_title(title):
        log("声の材料: %s は歌の配信なので写しませんでした" % n)
        return "accepted", "歌の配信"
    have = _store.tx_path(tid)
    old = fsio.read_json_or(have, None, kind=dict) if have and os.path.isfile(have) else None
    if old is not None and old.get("origin") != ORIGIN:
        return "rejected", "同じ id の文書があります"
    rows, clips, songs, dup = [], {}, 0, 0
    seen = _seen_starts(title, tid)
    for rid, r in sorted(meta["rows"].items()):
        if rid not in wavs or not isinstance(r, dict) or not _vm.ROW_ID_RE.match(rid):
            continue
        g = {"id": rid, "start": _vm.num(r.get("start")), "end": _vm.num(r.get("end")), "text": str(r.get("text") or "")[:200], "speaker": "S1"}
        a, b = _vm.num(r.get("a"), -1), _vm.num(r.get("b"), -1)
        if _vm.song_row(g):
            songs += 1
            continue
        if not _vm.row_ok(g) or not (0 <= a <= g["start"] < g["end"] <= b) or not _wav_ok(wavs[rid]):
            continue
        if any(abs(g["start"] - x) < DUP_SEC for x in seen):
            dup += 1   # 同じ配信の同じ所(別の文書で友人の PC から届いた)= 同じ声を 2 回覚えない(10-25)
            continue
        rows.append(g)
        clips[rid] = (wavs[rid], a, b)
    if not rows:
        return "accepted", "使える行がありません(歌の行 %d・同じ配信の同じ所 %d)" % (songs, dup)
    _write_doc(tid, old, who, title, rows, meta)
    got = _voiceclips.put_bytes(tid, clips)
    log("声の材料: %s(%s)の %d 行を写しました(歌の行で外した %d・同じ配信の同じ所で外した %d)" % (who, tid, got, songs, dup))
    return "accepted", ""


DUP_SEC = 1.0   # 同じ配信(題名)の、もう受け取った行の始まりとこれより近い行は受け取らない


def _seen_starts(title, tid):
    """同じ題名の、友人の PC から届いたほかの文書の行の始まり(元の配信の秒)"""
    out = []
    if not title:
        return out
    for t, p in _docloc.doc_files().items():
        if t == tid:
            continue
        d = fsio.read_json_or(p, {}, kind=dict)
        if d.get("origin") == ORIGIN and str(d.get("title") or "") == title:
            out += [_vm.num(g.get("start")) for g in d.get("segments") or () if isinstance(g, dict)]
    return out


def _wav_ok(data):
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.getframerate() == _vm.RATE and w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getnframes() > 0
    except (wave.Error, EOFError):
        return False


def _write_doc(tid, old, who, title, rows, meta):
    now = int(time.time() * 1000)
    doc = old or {"schema": "transcribe/v1", "id": tid, "title": title, "sourcePath": "", "sourceName": "友人の PC の声の材料",
                  "origin": ORIGIN, "language": "ja", "speakers": [{"id": "S1", "name": who}], "segments": [], "createdAt": now,
                  "friendVoice": {"appVersion": str(meta.get("appVersion") or "")[:40]}}
    seen = {g.get("id") for g in doc.get("segments") or ()}
    doc["segments"] = sorted(list(doc.get("segments") or []) + [g for g in rows if g["id"] not in seen], key=lambda g: g["start"])
    doc["start"], doc["end"] = 0.0, max(g["end"] for g in doc["segments"]) + _vm.PAD
    doc["duration"], doc["whole"] = doc["end"], False
    doc["updatedAt"] = now
    if not _yschemas.TID_RE.match(tid):
        raise Refused("文書の印の形")
    _store.commit(tid, doc, why="whole")
