# -*- coding: utf-8 -*-
"""ごみ箱フォルダの決まりの 1 か所(どの層からも使う。① の録画の部品も使うので ytt に置く)。

ごみ箱フォルダの中は <YYYY-MM-DD>/<種類>/... の日付のフォルダ。移した物は <日付>/manifest.jsonl に元の場所を 1 行ずつ残す(戻したいときに見る)。
日数(② の flow/retention.KEEP_DAYS)を過ぎた日付のフォルダは丸ごと消す(④ の manage/keep/cleanup.Cleanup.purge・① の pipeline/ingest/rec_core.Recordings.purge_trash)。
移し方・戻し方は ④ の manage/keep/trash.py(to_trash・put_back)。ここは名前・記録の形と古い日付の見つけ方だけを持つ。
"""
import json
import os
import time

MANIFEST = "manifest.jsonl"
TRASH_DIR = "ごみ箱"     # ごみ箱フォルダの名前(作業データ・書き出し先・録画の置き場所・友人のアプリの一時保管の直下)


def day_name(now=None):
    """日付のフォルダの名前(手元の時刻の YYYY-MM-DD)"""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))


def free_path(dest, first=1, check=None):
    """同じ名前があれば (1) (2) … を付ける。first = 最初に付ける番号・check = 「ある」の判定(既定は os.path.lexists)"""
    check = check or os.path.lexists
    k, (base, ext) = first, os.path.splitext(dest)
    while check(dest):
        dest = "%s (%d)%s" % (base, k, ext)
        k += 1
    return dest


def append_manifest(day_dir, rows):
    """ごみ箱フォルダの <日付>/manifest.jsonl に、移した物の元の場所を 1 行ずつ足す(rows = [{from, to, at, kind, ...}]。戻したいときに見る)。
    書けなければ OSError"""
    with open(os.path.join(day_dir, MANIFEST), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def old_day_dirs(root, days, now):
    """root の直下で、名前の頭 10 文字が YYYY-MM-DD の日付のフォルダのうち days 日より古いもの -> [(名前, パス)]。
    root を読めなければ []。日付でない名前・ファイルは飛ばす(受付済み と ごみ箱フォルダの両方の決まり)"""
    try:
        names = os.listdir(root)
    except OSError:
        return []
    out = []
    for name in names:
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        try:
            day = time.mktime(time.strptime(name[:10], "%Y-%m-%d"))
        except ValueError:
            continue
        if now - day > days * 86400:
            out.append((name, p))
    return out
