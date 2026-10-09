# -*- coding: utf-8 -*-
"""まとめて実行の「終わった実行の記録」の形と読み方(役割で組み直す RS3-0B。入口 src/home/autorun.py から移した。動きは変えていない)。

記録は入口の作業データの logs/autorun-runs.jsonl(と、上限を超えて回した .1)に 1 行 = 1 件の JSON で残る(書くのは AutoRunner。
書き足しは ytt/fsio.append_line)。この部品は**読む側**: 入口の起動時に前回の結果を作る・履歴の画面・あとから解析の取り込み(autorun)と、
ライブの失敗の集約(live_failures。書き出しのジョブの runId で紐づける)が、同じ読み方を使う。
autorun を読み込まずに記録を読めるようにして、① の部品(live_failures など)から app への向きの違反をなくすために出した。

標準ライブラリだけ(ファイルは読むだけ。書き換えない)。
"""
import json
import os

RUNS_LOG = "autorun-runs.jsonl"   # 終わった実行の記録(入口の作業データの logs の中。段2 B-6)
LOG_VERSION = 1                   # 記録の1行の形の版(v)


def _parse_rec(raw):
    """記録の1行 -> 辞書(壊れた行・形の違う行は None。途中で切れた行・手で直した行を飛ばす)"""
    raw = raw.strip()
    if not raw:
        return None
    try:
        rec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("v") != LOG_VERSION or not isinstance(rec.get("id"), str):
        return None
    if rec.get("state") not in ("done", "error", "cancelled") or not isinstance(rec.get("steps"), list):
        return None
    kind = rec.get("kind")
    if not ((kind == "doc" and isinstance(rec.get("docId"), str)) or (kind == "video" and isinstance(rec.get("videoId"), str))
            or (kind == "file" and isinstance(rec.get("sourcePath"), str))):
        return None
    return rec


def read_runs_log(path, max_bytes=None):
    """記録(.1 → 今のファイル = 書いた順)の中身のリスト。max_bytes = 末尾からこの大きさだけ読む(途中から読んだ最初の行は捨てる)"""
    chunks, left = [], max_bytes
    for p in (path, path + ".1"):
        if left is not None and left <= 0:
            break
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                start = 0 if left is None else max(0, size - left)
                f.seek(start)
                data = f.read()
        except OSError:
            continue
        if start > 0:
            nl = data.find(b"\n")
            data = data[nl + 1:] if nl >= 0 else b""
        if left is not None:
            left -= size - start
        chunks.insert(0, data)
    out = []
    for data in chunks:
        for raw in data.split(b"\n"):
            rec = _parse_rec(raw)
            if rec:
                out.append(rec)
    return out
