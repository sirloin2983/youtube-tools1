# -*- coding: utf-8 -*-
"""友人の PC から届いた声の材料の受け取り(10-24 夜。作る側 = friendapp/voicesend。案 = notes:plan/声の材料を友人のPCから-1024.md)。

送り返し\\ の `<印>__<文書の印>.voice.zip` を、送り返しの受付(returns.scan)がここへ渡す。中身(meta.json と <行 id>.wav)を確かめて
  - 小さな文字起こしの文書(id = 文書の印・origin = friend-voice・元の動画なし・話者 = 配信者 1 人・行 = 送られた行)を作る
  - 行の音を誰の声の材料の置き場所(human/proof/voiceclips)へ写す
誰の声のカード(app/check/voice_solo)は、この文書も今の文書と同じに出し、送られた音で再生する。答えると覚え直しも送られた音で動く。
外す物(写さない): 歌の配信(題名)・歌の行(音符)・名簿に無い人・覚え終えた人(登録簿の秒が覚え直しの秒 × DONE_MARGIN に届いた人)。
覚え終えた人の名前は write_done が `送り返し\\声\\覚え終わり.json` に置き、友人の PC はその人の文書を送らない(受付の見回りごと・変わったときだけ書く)。
"""
import io
import json
import os
import re
import time
import wave
import zipfile

from flow import voicematerial as _vm
from human.check import voice as _voice
from human.proof import store as _store, voiceclips as _voiceclips
from ytt import fsio, schemas as _yschemas

SUFFIX = ".voice.zip"
NAME_RE = re.compile(r"^([0-9A-Za-z_-]{1,64})__([0-9a-f]{12})" + re.escape(SUFFIX) + r"\Z")
FORMAT = "youtube-tools-voice/v1"
ORIGIN = "friend-voice"
DONE_DIR, DONE_NAME = "声", "覚え終わり.json"
MAX_ZIP = 8 * 1024 * 1024
MAX_WAV = 2 * 1024 * 1024
MAX_ROWS = 6
MAX_META = 64 * 1024
WAV_RE = re.compile(r"^([A-Za-z0-9_-]{1,16})\.wav\Z")


class Refused(ValueError):
    pass


def done_names(cache=None):
    """覚え終えた人の名前(登録簿の秒が覚え直しの秒 × DONE_MARGIN に届いた人)"""
    need = _voice._relearn_sec() * _vm.DONE_MARGIN
    reg = _voice.registry(_voice.doc_embedding({}), cache)
    return sorted(n for n, v in reg.items() if isinstance(v, dict) and _vm.num(v.get("sec")) >= need)


_last_done = {}
DONE_EVERY = 600   # 覚え終わり.json を見直す間隔(秒。登録簿を読むので見回りごとにはしない)


def write_done(sync_folder, in_dir, clock=time.time):
    """`<同期フォルダ>\\送り返し\\声\\覚え終わり.json` を置く(DONE_EVERY 秒に 1 回・中身が変わったときだけ)。-> 書いたか"""
    now = clock()
    if now - _last_done.get(sync_folder, -DONE_EVERY) < DONE_EVERY:
        return False
    _last_done[sync_folder] = now
    names = done_names()
    path = os.path.join(sync_folder, in_dir, DONE_DIR, DONE_NAME)
    cur = fsio.read_json_or(path, None, kind=dict)
    if (isinstance(cur, dict) and cur.get("names") == names) or (cur is None and not names):
        return False   # 変わらない・まだ誰も覚え終えていない(ファイルが無い = 友人の PC は全部送る、と同じ)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fsio.write_json(path, {"names": names, "at": int(now * 1000)}, indent=None)
    return True


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
    if who in done_names():
        return "accepted", "覚え終えた人"
    have = _store.tx_path(tid)
    old = fsio.read_json_or(have, None, kind=dict) if have and os.path.isfile(have) else None
    if old is not None and old.get("origin") != ORIGIN:
        return "rejected", "同じ id の文書があります"
    rows, clips, songs = [], {}, 0
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
        rows.append(g)
        clips[rid] = (wavs[rid], a, b)
    if not rows:
        return "accepted", "使える行がありません(歌の行 %d)" % songs
    _write_doc(tid, old, who, title, rows, meta)
    got = _voiceclips.put_bytes(tid, clips)
    log("声の材料: %s(%s)の %d 行を写しました(歌の行で外した %d)" % (who, tid, got, songs))
    return "accepted", ""


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
