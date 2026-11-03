# -*- coding: utf-8 -*-
"""配信・依頼・切り抜きの出来事の記録(11-03。正 = 資料の plan/情報をまとめる所-1103.md の「決まった形: 配信・依頼・切り抜き」。ユーザー OK)。

決まり:
- 配信 1 本に 1 つの id(stream = YouTube の動画 id 11 文字。録画 id <日付>-<時刻>-<動画 id> からも引ける = stream_of)。
  依頼・録画・文字起こし・切り抜きはその id を持つ。同じ配信を 2 回依頼できるので、依頼の行には依頼の id(request)も書く。
- 出来事は <データの根>\\app\\logs\\streams.jsonl に後ろに足すだけ(回さない・書き換えない)。直すときも行を足す(取り消した など)。
- 画面は、この記録から組み直せる写しを読む(写しは消しても作り直せる)。推測で結んだ行は guess = True(古い記録から取り込んだ時だけ)。
- 名簿 = 出来事の種類 KINDS と欄 FIELDS はここ 1 か所。種類を足すときはここに足す(知らない種類は ValueError = テストで見つかる)。
- 書くのは入口の 1 プロセス(app/server.py に取り込んだツール)だけ。録画の部品(別プロセス)からは書かない。
- 書けなくても呼び手は止めない(元の記録が今までどおりの正。移し終えるまでは、この記録は「今の書く所から 1 行ずつ写した物」)。
  今の書く所は note で呼ぶ(例外を出さない)。どこから呼ぶかは tests/ytt/test_streamlog_guard.py の WRITERS
  YTT_DATA_DIR=inplace(テスト・見本)では書かない(path が None)。

移し方の段(同じ資料): 1 この部品と見張りのテスト → 2 今の書く所から 1 行 → 3 古い記録から 1 回だけ取り込む → 4 画面を 1 つずつ写しへ(1 週間は旧の読み方と突き合わせ)→ 5 旧の記録は写しと明記(消すのは機能ごとに OK を取ってから)。
"""
import json
import os
import re
import threading
import time

from . import datadir

NAME = "streams.jsonl"
SCHEMA = 1

# 出来事の種類(名簿)。値 = 人の言葉(画面・記録を読む人のため)
KINDS = {
    "request": "依頼を受けた",
    "request-reject": "依頼を断った",
    "request-cancel": "依頼を取り消した",
    "rec-link": "依頼と録画を結んだ",
    "rec-start": "録画を始めた",
    "rec-end": "録画が終わった",
    "candidate": "候補を出した",
    "adopt": "採用した",
    "reject": "不採用にした",
    "export": "書き出した",
    "deliver": "届けた",
    "not-sent": "送らなかった",
    "feedback": "判定が来た",
    "discard": "要らないにした",
    "undo": "取り消した",
    "run-start": "まとめて実行を始めた",
    "run-end": "まとめて実行が終わった",
}
# 欄(stream と kind と at のほか)。値 = 何を入れるか。文字は MAX_TEXT 字まで(数は数のまま)
FIELDS = {
    "request": "依頼の id(<日付>-<時刻>-<6 桁>)",
    "recording": "録画の id(<日付>-<時刻>-<動画 id>)",
    "recorder": "録画元",
    "mark": "スタジオのマークの id",
    "run": "まとめて実行の実行の id",
    "doc": "文字起こしの文書の id",
    "path": "切り抜きの動画のパス",
    "zip": "届けた zip の名前",
    "start": "配信の頭からの秒(切り抜きの頭)",
    "end": "配信の頭からの秒(切り抜きの末)",
    "base": "start・end の基準(stream = 配信の頭から / recording = 録画の頭から)",
    "origin": "出どころ(auto・archive・manual・request など)",
    "state": "結果の札(done・error・cancelled など)",
    "by": "誰が(friend・self・auto など)",
    "title": "題名",
    "note": "短い説明",
    "guess": "推測で結んだ(古い記録から取り込んだ時だけ True)",
}
MAX_TEXT = 300
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REC_RE = re.compile(r"^\d{8}-\d{6}-([A-Za-z0-9_-]{11})$")   # 録画の id(app/homereq.REC_VID_RE・録画の部品の REC_ID_RE と同じ形)
_lock = threading.Lock()


def path(env=None):
    """記録のパス(YTT_DATA_DIR=inplace = テスト・見本なら None)"""
    root = datadir.data_root(env)
    return os.path.join(root, "app", "logs", NAME) if root else None


def stream_of(video_id=None, recording=None):
    """配信の id(動画 id 11 文字)か ""。video_id が正しい形ならそれ、無ければ録画の id の末の動画 id"""
    if isinstance(video_id, str) and VIDEO_RE.match(video_id):
        return video_id
    m = REC_RE.match(recording) if isinstance(recording, str) else None
    return m.group(1) if m else ""


def _value(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(v, 3) if isinstance(v, float) else v
    return str(v)[:MAX_TEXT]


def make_row(kind, stream="", now=None, **fields):
    """1 行の形 -> 辞書。知らない種類・欄は ValueError(名簿はここ 1 か所)。空の欄(None・"")は書かない"""
    if kind not in KINDS:
        raise ValueError("知らない出来事の種類: %r" % (kind,))
    bad = set(fields) - set(FIELDS)
    if bad:
        raise ValueError("知らない欄: %s" % ", ".join(sorted(bad)))
    row = {"v": SCHEMA, "at": int((time.time() if now is None else now) * 1000), "kind": kind, "stream": stream_of(stream, fields.get("recording"))}
    for k, v in fields.items():
        if v is None or v == "":
            continue
        row[k] = _value(v)
    return row


def record(kind, stream="", now=None, p=None, **fields):
    """出来事を 1 行足す -> 足した行か None(書かなかった・書けなかった)。stream = 動画 id(無ければ録画の id から引く)。
    知らない種類・欄は ValueError(呼び手の書き間違い = テストで見つける)。書けない(ディスク)は None で呼び手は止めない"""
    row = make_row(kind, stream, now=now, **fields)
    p = p or path()
    if not p:
        return None
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with _lock, open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return row


def note(kind, stream="", **fields):
    """今の書く所から呼ぶ口(段 2): record と同じ。何があっても例外を出さない(元の記録が正の間は、こちらが書けなくても呼び手の仕事を止めない)。
    種類・欄の書き間違いは tests/ytt/test_streamlog_guard.py が呼び出しの文字を読んで見つける"""
    try:
        return record(kind, stream, **fields)
    except Exception:   # noqa: BLE001
        return None


def rows(p=None):
    """記録の行(古い順)。壊れた行・形の違う行は飛ばす。記録が無ければ []"""
    p = p or path()
    if not p or not os.path.isfile(p):
        return []
    out = []
    with open(p, "rb") as f:
        for line in f.read().decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("kind") in KINDS and isinstance(d.get("at"), int):
                out.append(d)
    return out
