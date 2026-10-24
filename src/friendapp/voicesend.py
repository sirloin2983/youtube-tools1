# -*- coding: utf-8 -*-
"""友人の PC から送る声の材料(10-24 夜。ユーザー「誰の声をメンバー全員分」。案 = notes:plan/声の材料を友人のPCから-1024.md)。

友人の PC で文字起こしたソロ配信の文書から、話し声の行の短い音を切り出して、送り返しの zip にする。同期(friendapp/sync)が
いつもの送り返しの道で Dropbox の `/送り返し/` へ上げ、ユーザーの PC の受付(human/friend/returns)が誰の声のカードの材料にする。
  選び方    ② flow/voicematerial(ユーザーの PC のカードと同じ): ソロの文書・歌の配信と歌の行は外す・1 本の文書から PER_DOC 行
  外す物    歌の配信と歌の行だけ。覚えた人の分も送る(どれをカードにするかはユーザーの PC の並べ方。10-24 夜の決め直し = 送る側を複雑にしない)
  名前      `voice__<文書の印>.voice.zip`(文書の印 = 友人の PC の文書 id の頭 12 字)。中身 = meta.json と <行 id>.wav(16kHz・モノラル)
           meta.json = {"format": FORMAT, "doc", "streamer", "title", "appVersion", "rows": {行 id: {"start", "end", "a", "b", "text"}}}
  時機      同期の 1 回ごとに BATCH 本まで。録画中(ライブの録画)は作らない。文書が書かれて STABLE_SEC 秒たってから(書きかけを読まない)。
           送った文書は <friend>/voice-sent.json に覚え、2 回は作らない(元の動画が無い文書・ソロでない文書も覚えて見直さない)
  画面      何も足さない(記録に 1 行だけ)
"""
import json
import os
import shutil
import tempfile
import time
import zipfile

from flow import voicematerial as _vm
from ytt import docloc as _docloc, fsio, tools as _tools, version as _version

FORMAT = "youtube-tools-voice/v1"
PER_DOC = 3
BATCH = 4                 # 同期の 1 回で作る zip の上限
STABLE_SEC = 300
SENT_NAME = "voice-sent.json"
SENT_KEEP = 3000          # 覚えておく文書の数(古い順に忘れる)
MAX_DOC_BYTES = 32 * 1024 * 1024


def zip_name(tid):
    return "voice__%s.voice.zip" % tid[:12]


def _read(path):
    try:
        if os.path.getsize(path) > MAX_DOC_BYTES:
            return None
        return fsio.read_json_or(path, None, kind=dict)
    except OSError:
        return None


def build(outbox, sent_path, now=None, log=None, ffmpeg=None, data_dir=None):
    """まだ送っていない文書の声の材料の zip を outbox に作る -> 作った数"""
    log = log or (lambda m: None)
    now = time.time() if now is None else now
    sent = fsio.read_json_or(sent_path, {}, kind=dict)
    ff = ffmpeg or _tools.find_tool("ffmpeg")
    made, skips, seen = 0, {"song": 0}, 0
    for tid, path in sorted(_docloc.doc_files(data_dir).items(), key=lambda x: -_mtime(x[1])):
        if made >= BATCH:
            break
        if tid in sent or now - _mtime(path) < STABLE_SEC:
            continue
        doc = _read(path)
        if doc is None:
            continue
        why = _one(tid, doc, outbox, ff, skips)
        if why == "later":
            continue
        sent[tid] = {"at": int(now), "why": why}
        seen += 1
        made += why == "sent"
    if seen:
        if len(sent) > SENT_KEEP:
            sent = dict(sorted(sent.items(), key=lambda x: (x[1] or {}).get("at") or 0)[-SENT_KEEP:])
        fsio.write_json(sent_path, sent, indent=None)
    if made or skips["song"]:
        log("声の材料: %d 本を送り返しに置きました(歌の配信で外した %d 本)" % (made, skips["song"]))
    return made


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _one(tid, doc, outbox, ff, skips):
    """1 本の文書 -> "sent"(置いた)・"later"(あとで。ffmpeg が無い)・ほかは置かない理由(覚えて見直さない)"""
    who = _vm.solo_person(doc)
    if not who:
        return "notSolo"
    title = next((t for t in _vm.titles(doc) if t), "")
    if _vm.song_title(_vm.titles(doc)):
        skips["song"] += 1
        return "song"
    src = doc.get("sourcePath")
    if not isinstance(src, str) or not os.path.isfile(src):
        return "noMedia"
    if not ff:
        return "later"
    picks = _vm.pick(doc)[:PER_DOC]
    if not picks:
        return "noRows"
    tmp = tempfile.mkdtemp(prefix="ytt-voice-")
    try:
        rows = {}
        for g in picks:
            try:
                got = _vm.cut(ff, src, _vm.num(g.get("start")), _vm.num(g.get("end")), os.path.join(tmp, g["id"] + ".wav"))
            except OSError:
                return "later"
            if got:
                rows[g["id"]] = {"start": _vm.num(g.get("start")), "end": _vm.num(g.get("end")), "a": got[0], "b": got[1],
                                 "text": str(g.get("text") or "")[:200]}
        if not rows:
            return "noRows"
        meta = {"format": FORMAT, "doc": tid[:12], "streamer": who, "title": title[:200], "appVersion": _version.VERSION, "rows": rows}
        os.makedirs(outbox, exist_ok=True)
        out = os.path.join(outbox, zip_name(tid))
        with zipfile.ZipFile(out + ".part", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("meta.json", json.dumps(meta, ensure_ascii=False))
            for rid in rows:
                z.write(os.path.join(tmp, rid + ".wav"), rid + ".wav")
        os.replace(out + ".part", out)
        return "sent"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
